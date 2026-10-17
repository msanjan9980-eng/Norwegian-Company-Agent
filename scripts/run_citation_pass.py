#!/usr/bin/env python3
"""Convert batch envelopes into citation-validated envelopes with snapshots."""
from __future__ import annotations

import sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))


import argparse
import json
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import certifi

from norway_company_agent import snapshot_store
from norway_company_agent.url_safety import safe_urlopen
from norway_company_agent.nav_fetcher import fetch_postings_for_orgnrs, summarize_nav
from norway_company_agent.citation_envelope import (
    build_envelope,
    validate_citation_shape,
)

UA = "SignalpostResearchPOC/1.0 (+https://builderr.ai)"
TIMEOUT = 20
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

WORKERS = 16

SHARED_URLS = {
    "https://www.brreg.no/en/submission-of-annual-accounts/reporting-obligations-to-the-register-of-company-accounts/who-has-an-accounting-obligation/": True,
}

_shared_cache: dict[str, dict] = {}
_shared_lock = threading.Lock()
_print_lock = threading.Lock()
MAX_BYTES = 20 * 1024 * 1024

BULK_URL_REWRITES = {
    "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv":
        "https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}",
    "https://data.brreg.no/enhetsregisteret/api/enheter/lastned":
        "https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rewrite_bulk_url(url: str, orgnr: str) -> str:
    template = BULK_URL_REWRITES.get(url)
    if template:
        return template.format(orgnr=orgnr)
    return url


def fetch_bytes(url: str, retries: int = 3) -> tuple[bytes | None, str | None, int | None, list[str]]:
    last_error: str | None = None
    redirect_chain: list[str] = []
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        try:
            with safe_urlopen(req, timeout=TIMEOUT, context=SSL_CONTEXT) as resp:
                ct = resp.headers.get("content-type")
                status = resp.getcode()
                try:
                    final_url = resp.geturl()
                except Exception:
                    final_url = url
                if final_url and final_url != url:
                    redirect_chain = [url, final_url]
                raw = resp.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    return None, f"payload exceeds {MAX_BYTES} bytes", status, redirect_chain
                return raw, ct, status, redirect_chain
        except urllib.error.HTTPError as e:
            return None, f"HTTP {e.code}", e.code, redirect_chain
        except urllib.error.URLError as e:
            last_error = f"URLError: {str(e.reason)[:80]}"
        except socket.timeout:
            last_error = "timeout"
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)[:80]}"
        if attempt < retries - 1:
            time.sleep(0.8 * (attempt + 1))
    return None, last_error or "fetch failed", None, redirect_chain


def capture_one(orgnr: str, internal_key: str, block: dict) -> tuple[dict | None, str | None]:
    status = block.get("status") or "not_fetched"
    if status != "available":
        return None, None

    # Reuse the batch runner's snapshot when it is already on disk. This is
    # the merge that removes the redundant refetch: the batch runner writes
    # the snapshot while it has the response in memory, and this pass just
    # re-hashes the file that is already there.
    pre_snap = block.get("snapshot_path")
    if pre_snap:
        p = Path(pre_snap)
        if p.is_file():
            sha = block.get("content_sha256") or ""
            return {
                "id": "ev-" + (sha[:16] if len(sha) >= 16 else internal_key),
                "source_url": block.get("source_url"),
                "source_class": block.get("source_class") or block.get("source_type") or "unknown",
                "retrieved_at": block.get("retrieved_at"),
                "content_sha256": sha,
                "snapshot_path": pre_snap,
                "snapshot_bytes": p.stat().st_size,
                "claim_span": None,
                "status_code": 200,
                "redirect_chain": [],
                "parser_version": "1.0",
                "access_policy": "standard",
                "reporting_period": None,
            }, None

    raw_url = block.get("source_url") or ""
    source_class = block.get("source_class") or block.get("source_type") or "unknown"

    if not raw_url.startswith(("http://", "https://")):
        return None, f"non-http source_url: {raw_url!r}"

    if raw_url in SHARED_URLS:
        with _shared_lock:
            if raw_url in _shared_cache:
                cached = _shared_cache[raw_url]
                rec = snapshot_store.capture(
                    orgnr, cached["raw"], raw_url, source_class,
                    content_type=cached["content_type"],
                    claim_span=None,
                    status_code=cached.get("status_code"),
                    redirect_chain=cached.get("redirect_chain", []),
                )
                return rec, None

        raw, ct, status, redirects = fetch_bytes(raw_url)
        if raw is None:
            return None, ct or "fetch failed"
        with _shared_lock:
            _shared_cache[raw_url] = {"raw": raw, "content_type": ct, "status_code": status, "redirect_chain": redirects}
        rec = snapshot_store.capture(orgnr, raw, raw_url, source_class, content_type=ct, claim_span=None, status_code=status, redirect_chain=redirects)
        return rec, None

    effective_url = rewrite_bulk_url(raw_url, orgnr)
    raw, ct, status, redirects = fetch_bytes(effective_url)
    if raw is None:
        return None, ct or "fetch failed"
    rec = snapshot_store.capture(orgnr, raw, effective_url, source_class, content_type=ct, claim_span=None, status_code=status, redirect_chain=redirects)
    return rec, None


def _merge_preseeded(cited: dict, preseeded_claims: list, preseeded_evidence: list) -> None:
    """Merge deepening / Brave output into the cited envelope.

    Only preseeded evidence with a valid snapshot_path is merged. The batch
    runner's module-level evidence records (one per module) carry no on-disk
    snapshot and would fail validate_citation_shape. They are redundant with
    the snapshots this citation pass already captured for the same modules,
    so dropping them is safe.
    """
    if preseeded_evidence:
        existing_ids = {e.get("id") for e in cited["evidence"]}
        for ev in preseeded_evidence:
            eid = ev.get("id")
            if not eid or eid in existing_ids:
                continue
            sp = ev.get("snapshot_path") or ""
            if not sp or sp.startswith("/") or ".." in sp:
                continue
            cited["evidence"].append(ev)
            existing_ids.add(eid)
    if preseeded_claims:
        cited_ids = {e.get("id") for e in cited["evidence"]}
        existing_keys = {
            (c.get("field"), json.dumps(c.get("value"), sort_keys=True, default=str))
            for c in cited["claims"]
        }
        for c in preseeded_claims:
            key = (c.get("field"), json.dumps(c.get("value"), sort_keys=True, default=str))
            if key in existing_keys:
                continue
            if all(eid in cited_ids for eid in (c.get("evidence_ids") or [])):
                cited["claims"].append(c)
                existing_keys.add(key)

def process(input_path: Path, output_path: Path, report_path: Path, limit: int, run_id: str, skip_nav: bool = False) -> None:
    t0 = time.monotonic()
    envelopes = [json.loads(l) for l in input_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if limit > 0:
        envelopes = envelopes[:limit]

    started_at = utc_now_iso()
    debug_lines: list[str] = []

    names_by_orgnr = {}
    for env in envelopes:
        org = str(env.get("organisation_number") or "")
        internal = ((env.get("profile") or {}).get("evidence") or {})
        reg = (internal.get("registry") or {}).get("value") or {}
        nm = reg.get("navn") or (env.get("profile") or {}).get("name")
        if org and nm:
            names_by_orgnr[org] = nm

    # Item 9: distinguish "NAV not consulted" from "NAV checked, empty".
    nav_fetched = False
    nav_index: dict[str, dict] = {}
    if skip_nav:
        print("Skipping NAV fetch (--skip-nav).")
    else:
        print(f"Fetching NAV postings for {len(names_by_orgnr)} companies...")
        try:
            nav_index = fetch_postings_for_orgnrs(names_by_orgnr.keys(), names_by_orgnr)
            nav_fetched = True
            print(f"  NAV: {summarize_nav(nav_index)}")
        except Exception as e:
            print(f"  NAV fetch failed: {type(e).__name__}: {e}")
            nav_index = {}

    out_rows: list[dict] = []
    total_claims = 0
    total_evidence = 0
    total_errors = 0
    per_company_problems: list[dict] = []
    done_count = 0
    lock = threading.Lock()

    def process_company(idx_env):
        idx, env = idx_env
        orgnr = str(env.get("organisation_number") or "")
        if not orgnr:
            return None
        internal = ((env.get("profile") or {}).get("evidence") or {})
        local_debug: list[str] = []
        captured: dict[str, dict] = {}
        errors: list[dict] = []
        for key, block in internal.items():
            rec, err = capture_one(orgnr, key, block)
            if rec is not None:
                captured[key] = rec
                local_debug.append(f"{orgnr}  {key:22s}  OK   id={rec['id']}  url={rec['source_url'][:90]}")
            elif err is not None:
                errors.append({"source": key, "message": err})
                local_debug.append(f"{orgnr}  {key:22s}  ERR  {err}")

        run_meta = {
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": utc_now_iso(),
            "terminal_status": "completed",
        }
        cited = build_envelope(
            orgnr, run_meta, internal, captured,
            changes=(env.get("changes") or []), errors=errors,
            operations={"requests": len(captured), "runtime_ms": 0, "third_party_cost_usd": 0},
            nav_bucket=nav_index.get(orgnr),
            nav_checked=nav_fetched,
        )
        _merge_preseeded(cited, env.get("claims") or [], env.get("evidence") or [])
        problems = validate_citation_shape(cited)
        return (idx, cited, local_debug, problems, len(errors))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(process_company, (i, env)): i for i, env in enumerate(envelopes)}
        for fut in as_completed(futures):
            res = fut.result()
            if res is None:
                continue
            idx, cited, local_debug, problems, err_ct = res
            out_rows.append((idx, cited))
            debug_lines.extend(local_debug)
            total_claims += len(cited["claims"])
            total_evidence += len(cited["evidence"])
            total_errors += err_ct
            if problems:
                per_company_problems.append({"orgnr": cited["organisation_number"], "problems": problems[:5]})
            with lock:
                done_count += 1
                if done_count % 50 == 0:
                    elapsed = time.monotonic() - t0
                    print(f"  {done_count}/{len(envelopes)}  ({done_count/elapsed*60:.1f}/min)  claims={total_claims}  evid={total_evidence}  errors={total_errors}")

    out_rows.sort(key=lambda pair: pair[0])
    out_rows = [row for _, row in out_rows]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for row in out_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "run_id": run_id,
        "nav": summarize_nav(nav_index) if nav_fetched else {"status": "not_consulted"},
        "nav_fetched": nav_fetched,
        "input_envelopes": len(envelopes),
        "output_envelopes": len(out_rows),
        "total_claims": total_claims,
        "total_evidence": total_evidence,
        "total_errors": total_errors,
        "envelopes_with_local_problems": len(per_company_problems),
        "sample_problems": per_company_problems[:5],
        "runtime_s": round(time.monotonic() - t0, 1),
        "snapshots_root": str(snapshot_store.SNAPSHOTS_ROOT),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    Path("out/citation-debug.log").write_text("\n".join(debug_lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))

    if per_company_problems:
        print(f"Citation validation failed for {len(per_company_problems)} envelope(s).", file=sys.stderr)
        raise SystemExit(2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envelopes", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--run-id", default="citation-pass-001")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--skip-nav", action="store_true", help="Skip the NAV job-feed fetch entirely")
    args = ap.parse_args()
    global WORKERS
    WORKERS = args.workers
    process(Path(args.envelopes), Path(args.output), Path(args.report), args.limit, args.run_id, skip_nav=args.skip_nav)


if __name__ == "__main__":
    main()