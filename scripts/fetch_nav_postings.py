#!/usr/bin/env python3
"""Fetch active job postings from NAV Arbeidsplassen for our tracked companies.

Strategy:
  1. Fetch the current public token.
  2. Page through the change feed with If-Modified-Since = N days.
  3. Pre-filter list items whose businessName matches one of our companies.
  4. Fetch the detail JSON for each match.
  5. Verify employer.orgnr equals the target — this is the exact-entity anchor.
  6. Snapshot the detail JSON, emit one claim per posting.

Output:
  out/nav-postings.json  — {"by_orgnr": {orgnr: {postings: [...], evidence: [...]}}}
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import certifi

from norway_company_agent import snapshot_store


TOKEN_URL = "https://pam-stilling-feed.nav.no/api/publicToken"
FEED_URL = "https://pam-stilling-feed.nav.no/api/v1/feed"
FEED_ENTRY_URL = "https://pam-stilling-feed.nav.no/api/v1/feedentry/{uuid}"
UA = "SignalpostResearchPOC/1.0 (+https://builderr.ai)"
TIMEOUT = 30
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
MAX_PAGES = 200


def fetch_public_token() -> str:
    req = urllib.request.Request(TOKEN_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CONTEXT) as r:
        raw = r.read().decode("utf-8").strip()
    # Response is a sentence: "Current public token for Nav Job Vacancy Feed: <JWT>"
    return raw.split(":", 1)[1].strip() if ":" in raw else raw


def _get_json(url: str, token: str | None = None, extra_headers: dict | None = None) -> dict:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CONTEXT) as r:
        return json.loads(r.read())


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().upper())


def load_targets(profiles_path: Path) -> dict[str, dict]:
    """Return {normalized_name: {orgnr, original_name}}."""
    targets: dict[str, dict] = {}
    for line in profiles_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        env = json.loads(line)
        org = env.get("organisation_number")
        internal = ((env.get("profile") or {}).get("evidence") or {})
        reg = (internal.get("registry") or {}).get("value") or {}
        name = reg.get("navn") or (env.get("profile") or {}).get("name")
        if not org or not name:
            continue
        targets[norm_name(name)] = {"orgnr": org, "name": name}
    return targets


def walk_feed(token: str, since_iso: str, max_pages: int) -> list[dict]:
    """Return list items from the feed up to max_pages."""
    items: list[dict] = []
    url: str | None = FEED_URL
    pages = 0
    while url and pages < max_pages:
        pages += 1
        try:
            page = _get_json(url, token, {"If-Modified-Since": since_iso})
        except Exception as e:
            print(f"  feed page {pages}: {type(e).__name__}: {str(e)[:100]}")
            break
        batch = page.get("items") or []
        items.extend(batch)
        print(f"  feed page {pages}: {len(batch)} items (total {len(items)})")
        next_url = page.get("next_url")
        if not next_url or not batch:
            break
        url = "https://pam-stilling-feed.nav.no" + next_url if next_url.startswith("/") else next_url
        time.sleep(0.5)
    return items


def fetch_detail(uuid: str, token: str) -> dict | None:
    try:
        return _get_json(FEED_ENTRY_URL.format(uuid=uuid), token)
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envelopes", default="out/envelopes.jsonl")
    ap.add_argument("--output", default="out/nav-postings.json")
    ap.add_argument("--lookback-days", type=int, default=14)
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    print("Loading targets...")
    targets = load_targets(Path(args.envelopes))
    print(f"  {len(targets)} target names")

    print("Fetching public token...")
    token = fetch_public_token()
    print(f"  token length {len(token)}")

    since = format_datetime(
        datetime.now(timezone.utc) - timedelta(days=args.lookback_days), usegmt=True
    )
    print(f"Fetching feed since {since}")
    items = walk_feed(token, since, args.max_pages)
    print(f"Total list items: {len(items)}")

    # Pre-filter: ACTIVE + businessName matches one of our targets
    candidates: list[tuple[str, str, str]] = []  # (uuid, target_orgnr, target_name)
    seen_uuids: set[str] = set()
    for it in items:
        fe = it.get("_feed_entry") or {}
        if fe.get("status") != "ACTIVE":
            continue
        biz = norm_name(fe.get("businessName"))
        if not biz or biz not in targets:
            continue
        uuid = it.get("id")
        if not uuid or uuid in seen_uuids:
            continue
        seen_uuids.add(uuid)
        targets_row = targets[biz]
        candidates.append((uuid, targets_row["orgnr"], targets_row["name"]))

    print(f"Candidates matching our companies: {len(candidates)}")

    # Fetch details in parallel
    by_orgnr: dict[str, dict] = {}
    confirmed = 0
    rejected = 0
    snapshot_count = 0
    t0 = time.monotonic()

    def worker(uuid: str) -> tuple[str, dict | None]:
        return uuid, fetch_detail(uuid, token)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(worker, uuid): (uuid, org, name) for uuid, org, name in candidates}
        for fut in as_completed(futures):
            uuid, org, name = futures[fut]
            try:
                _uuid, detail = fut.result()
            except Exception:
                continue
            if not detail:
                continue
            ac = detail.get("ad_content") or {}
            emp = ac.get("employer") or {}
            nav_orgnr = str(emp.get("orgnr") or "").strip()
            if nav_orgnr != org:
                rejected += 1
                continue
            confirmed += 1

            # Snapshot the detail JSON
            raw = json.dumps(detail, ensure_ascii=False).encode("utf-8")
            rec = snapshot_store.capture(
                orgnr=org,
                raw=raw,
                source_url=FEED_ENTRY_URL.format(uuid=uuid),
                source_class="public_job_posting_nav",
                content_type="application/json",
                claim_span=ac.get("title"),
            )
            snapshot_count += 1

            bucket = by_orgnr.setdefault(org, {"postings": [], "evidence": []})
            bucket["evidence"].append(rec)
            bucket["postings"].append({
                "uuid": uuid,
                "title": ac.get("title"),
                "jobtitle": ac.get("jobtitle"),
                "employer_name": emp.get("name"),
                "employer_orgnr": nav_orgnr,
                "employer_homepage": emp.get("homepage"),
                "published": ac.get("published"),
                "expires": ac.get("expires"),
                "updated": ac.get("updated"),
                "application_due": ac.get("applicationDue"),
                "engagementtype": ac.get("engagementtype"),
                "extent": ac.get("extent"),
                "positioncount": ac.get("positioncount"),
                "sector": ac.get("sector"),
                "source": ac.get("source"),
                "link": ac.get("link"),
                "municipalities": sorted({
                    (w.get("municipal") or "").strip()
                    for w in (ac.get("workLocations") or [])
                    if w.get("municipal")
                }),
                "occupation_categories": ac.get("occupationCategories") or [],
                "evidence_id": rec["id"],
            })

    runtime = round(time.monotonic() - t0, 1)
    summary = {
        "lookback_days": args.lookback_days,
        "feed_items": len(items),
        "candidates": len(candidates),
        "confirmed_employer_orgnr_match": confirmed,
        "rejected_orgnr_mismatch": rejected,
        "snapshots_captured": snapshot_count,
        "companies_with_postings": len(by_orgnr),
        "total_postings": sum(len(v["postings"]) for v in by_orgnr.values()),
        "runtime_s": runtime,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps({"summary": summary, "by_orgnr": by_orgnr}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
