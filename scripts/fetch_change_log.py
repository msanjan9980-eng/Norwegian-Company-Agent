#!/usr/bin/env python3
"""Fetch Brreg registry change events and match to our tracked companies."""
from __future__ import annotations

import argparse
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import certifi

from norway_company_agent import snapshot_store


UA = "SignalpostResearchPOC/1.0 (+https://builderr.ai)"
TIMEOUT = 60
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
CHANGE_URL = "https://data.brreg.no/enhetsregisteret/api/oppdateringer/enheter"


def _get(url: str, params: dict | None = None) -> dict:
    if params:
        q = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CONTEXT) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envelopes", default="out/envelopes.jsonl")
    ap.add_argument("--output", default="out/activity-events.json")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--max-pages", type=int, default=200)
    args = ap.parse_args()

    # Load our 1,000 orgnrs
    targets: set[str] = set()
    for line in Path(args.envelopes).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        env = json.loads(line)
        org = env.get("organisation_number")
        if org:
            targets.add(str(org))
    print(f"Targets: {len(targets)}")

    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%dT00:00:00.000Z")
    print(f"Fetching registry changes since {since}")

    url = CHANGE_URL
    params = {"dato": since, "size": 2000}
    events_by_orgnr: dict[str, list[dict]] = {}
    total_scanned = 0
    matched = 0
    pages = 0
    t0 = time.monotonic()

    while url and pages < args.max_pages:
        pages += 1
        try:
            if pages == 1:
                data = _get(url, params)
            else:
                data = _get(url)
        except Exception as e:
            print(f"  page {pages}: {type(e).__name__}: {str(e)[:100]}")
            break

        entries = (data.get("_embedded") or {}).get("oppdaterteEnheter") or []
        total_scanned += len(entries)

        for e in entries:
            org = str(e.get("organisasjonsnummer") or "")
            if org not in targets:
                continue
            kind = (e.get("endringstype") or "").lower()
            if kind == "slettet":
                continue
            events_by_orgnr.setdefault(org, []).append({
                "oppdateringsid": e.get("oppdateringsid"),
                "dato": e.get("dato"),
                "endringstype": e.get("endringstype"),
            })
            matched += 1

        next_url = (data.get("_links") or {}).get("next", {}).get("href")
        if not next_url or not entries:
            break
        url = next_url
        if pages % 5 == 0:
            elapsed = time.monotonic() - t0
            print(f"  page {pages}: scanned={total_scanned}  matched={matched}  ({elapsed:.0f}s)")
        time.sleep(0.2)

    # Snapshot the whole result set as one evidence record per company
    for org, events in events_by_orgnr.items():
        raw = json.dumps(events, ensure_ascii=False).encode("utf-8")
        rec = snapshot_store.capture(
            orgnr=org,
            raw=raw,
            source_url=f"{CHANGE_URL}?dato={since}",
            source_class="official_registry_changelog",
            content_type="application/json",
            claim_span=f"{len(events)} event(s)",
        )
        events_by_orgnr[org] = {"events": events, "evidence_id": rec["id"]}

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps({"by_orgnr": events_by_orgnr}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = {
        "targets": len(targets),
        "pages_fetched": pages,
        "total_scanned": total_scanned,
        "companies_with_events": len(events_by_orgnr),
        "total_events_matched": matched,
        "runtime_s": round(time.monotonic() - t0, 1),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
