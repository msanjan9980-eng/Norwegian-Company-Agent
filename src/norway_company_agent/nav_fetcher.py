#!/usr/bin/env python3
"""Standalone NAV fetcher used by run_citation_pass.py.

Fetches the full 14-day window of ACTIVE postings, filters to a supplied
list of orgnrs, returns {orgnr: {"postings": [...], "evidence": [...]}}.
"""
from __future__ import annotations

import json
import re
import ssl
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Iterable

import certifi

from norway_company_agent import snapshot_store


TOKEN_URL = "https://pam-stilling-feed.nav.no/api/publicToken"
FEED_URL = "https://pam-stilling-feed.nav.no/api/v1/feed"
FEED_ENTRY_URL = "https://pam-stilling-feed.nav.no/api/v1/feedentry/{uuid}"
UA = "SignalpostResearchPOC/1.0 (+https://builderr.ai)"
TIMEOUT = 30
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _get_json(url: str, token: str | None = None, extra_headers: dict | None = None) -> dict:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CONTEXT) as r:
        return json.loads(r.read())


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().upper())


def fetch_postings_for_orgnrs(
    orgnrs: Iterable[str],
    names_by_orgnr: dict[str, str],
    lookback_days: int = 14,
    max_pages: int = 3,
) -> dict[str, dict]:
    """Return {orgnr: {"postings": [...], "evidence": [...]}} for matching companies."""
    targets_by_name = {_norm(n): o for o, n in names_by_orgnr.items() if n}
    target_orgnrs = set(orgnrs)

    # 1. Token
    req = urllib.request.Request(TOKEN_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CONTEXT) as r:
        raw = r.read().decode("utf-8").strip()
    token = raw.split(":", 1)[1].strip() if ":" in raw else raw

    # 2. Walk feed
    since = format_datetime(
        datetime.now(timezone.utc) - timedelta(days=lookback_days), usegmt=True
    )
    url = FEED_URL
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    pages = 0

    while url and pages < max_pages:
        pages += 1
        try:
            data = _get_json(url, token, {"If-Modified-Since": since})
        except Exception:
            break
        items = data.get("items") or []
        for it in items:
            fe = it.get("_feed_entry") or {}
            if fe.get("status") != "ACTIVE":
                continue
            biz = _norm(fe.get("businessName"))
            target_org = targets_by_name.get(biz)
            if not target_org:
                continue
            uid = it.get("id")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            candidates.append((uid, target_org))
        next_url = data.get("next_url")
        if not next_url or not items:
            break
        url = "https://pam-stilling-feed.nav.no" + next_url if next_url.startswith("/") else next_url
        time.sleep(0.2)

    # 3. Fetch details for candidates
    by_orgnr: dict[str, dict] = {}
    for uid, target_org in candidates:
        if target_org not in target_orgnrs:
            continue
        try:
            detail = _get_json(FEED_ENTRY_URL.format(uuid=uid), token)
        except Exception:
            continue
        ac = detail.get("ad_content") or {}
        emp = ac.get("employer") or {}
        nav_orgnr = str(emp.get("orgnr") or "").strip()
        if nav_orgnr != target_org:
            continue

        raw_bytes = json.dumps(detail, ensure_ascii=False).encode("utf-8")
        rec = snapshot_store.capture(
            orgnr=target_org,
            raw=raw_bytes,
            source_url=FEED_ENTRY_URL.format(uuid=uid),
            source_class="public_job_posting_nav",
            content_type="application/json",
            claim_span=ac.get("title"),
        )

        bucket = by_orgnr.setdefault(target_org, {"postings": [], "evidence": []})
        bucket["evidence"].append(rec)
        bucket["postings"].append({
            "uuid": uid,
            "title": ac.get("title"),
            "jobtitle": ac.get("jobtitle"),
            "published": ac.get("published"),
            "expires": ac.get("expires"),
            "application_due": ac.get("applicationDue"),
            "extent": ac.get("extent"),
            "engagementtype": ac.get("engagementtype"),
            "positioncount": ac.get("positioncount"),
            "sector": ac.get("sector"),
            "link": ac.get("link"),
            "municipalities": sorted({
                (w.get("municipal") or "").strip()
                for w in (ac.get("workLocations") or [])
                if w.get("municipal")
            }),
            "occupation_categories": ac.get("occupationCategories") or [],
            "evidence_id": rec["id"],
        })

    return by_orgnr


def summarize_nav(postings: dict[str, dict]) -> dict:
    return {
        "companies_with_postings": len(postings),
        "total_postings": sum(len(v["postings"]) for v in postings.values()),
        "total_snapshots": sum(len(v["evidence"]) for v in postings.values()),
    }
