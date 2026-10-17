#!/usr/bin/env python3
"""Email-domain website discovery.

For envelopes where the website claim is not_found, use the registry-listed
email domain (unless consumer) as a candidate company website. Fetch and verify
the exact entity appears on the page before publishing.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from norway_company_agent.website import fetch_website
from norway_company_agent.evidence import evidence


CONSUMER_DOMAINS = {
    "gmail.com","hotmail.com","outlook.com","yahoo.com","live.com","live.no",
    "online.no","broadpark.no","icloud.com","me.com","protonmail.com",
    "proton.me","msn.com","aol.com","mail.com","yandex.com","gmx.com",
    "gmx.no","hotmail.no","outlook.no","yahoo.no","telenor.com","lyse.net",
    "getmail.no","start.no","sensewave.com","c2i.net","nett.no",
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def spaced_orgnr(orgnr: str) -> str:
    if len(orgnr) != 9:
        return orgnr
    return f"{orgnr[:3]} {orgnr[3:6]} {orgnr[6:]}"


def entity_in_page(evidence_value: dict, orgnr: str, legal_name: str) -> tuple[bool, str]:
    """Return (found, reason)."""
    # Gather text from homepage and any crawled pages
    texts = [
        str(evidence_value.get("title") or ""),
        str(evidence_value.get("description") or ""),
        str(evidence_value.get("main_text_excerpt") or ""),
    ]
    for page in (evidence_value.get("pages") or []):
        texts.append(str(page.get("title") or ""))
        texts.append(str(page.get("main_text_excerpt") or ""))
    blob = norm(" ".join(texts))
    if not blob:
        return False, "no_text"

    spaced = spaced_orgnr(orgnr)
    if orgnr in blob or norm(spaced) in blob:
        return True, "orgnr_in_page"

    n_name = norm(legal_name)
    if n_name and len(n_name) >= 6 and n_name in blob:
        return True, "legal_name_in_page"

    return False, "no_entity_match"


def process(input_path: Path, output_path: Path, report_path: Path, limit: int = 0) -> dict:
    t0 = time.monotonic()
    envelopes = [json.loads(l) for l in input_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if limit and limit > 0:
        envelopes = envelopes[:limit]

    stats = {
        "input_envelopes": len(envelopes),
        "already_had_website": 0,
        "no_email": 0,
        "consumer_domain": 0,
        "candidate_domains": 0,
        "unique_domains_fetched": 0,
        "fetch_available": 0,
        "verified_entity": 0,
        "no_entity_match": 0,
        "fetch_failed": 0,
        "published_websites": 0,
        "requests": 0,
        "bytes": 0,
    }

    # Build per-org domains to fetch
    todo: list[tuple[int, str, str, str]] = []  # (idx, orgnr, name, domain)
    unique_domains: dict[str, list[int]] = {}
    for idx, env in enumerate(envelopes):
        profile = env.get("profile") or {}
        ev = profile.get("evidence") or {}
        web = ev.get("website") or {}
        if web.get("status") == "available":
            stats["already_had_website"] += 1
            continue
        reg = (ev.get("registry") or {}).get("value") or {}
        email = str(reg.get("epostadresse") or "").strip().lower()
        if not email or "@" not in email:
            stats["no_email"] += 1
            continue
        domain = email.split("@", 1)[1].strip()
        if not domain or domain in CONSUMER_DOMAINS:
            stats["consumer_domain"] += 1
            continue
        orgnr = str(env.get("organisation_number") or "")
        name = str(profile.get("name") or reg.get("navn") or "")
        if not orgnr or not name:
            continue
        todo.append((idx, orgnr, name, domain))
        unique_domains.setdefault(domain, []).append(idx)

    stats["candidate_domains"] = len(todo)
    stats["unique_domains_fetched"] = len(unique_domains)

    # Fetch each domain once
    cache: dict[str, tuple[dict, dict]] = {}
    for domain in unique_domains:
        url = f"https://{domain}/"
        try:
            rec, metrics = fetch_website(url)
        except Exception as exc:
            rec = evidence("website", "source_error", "email_domain_verified", url,
                           note=f"{type(exc).__name__}: {str(exc)[:120]}")
            metrics = {"requests": 0, "bytes": 0, "latencies_ms": []}
        cache[domain] = (rec, metrics)
        stats["requests"] += int(metrics.get("requests") or 0)
        stats["bytes"] += int(metrics.get("bytes") or 0)

    # Verify and publish per company
    for idx, orgnr, name, domain in todo:
        rec, _ = cache[domain]
        if rec.get("status") == "available":
            stats["fetch_available"] += 1
            ok, reason = entity_in_page(rec.get("value") or {}, orgnr, name)
            if ok:
                stats["verified_entity"] += 1
                # Rewrite evidence block as email_domain_verified
                new_ev = dict(rec)
                new_ev["source_type"] = "email_domain_verified"
                new_ev["source_class"] = "email_domain_verified"
                new_ev["note"] = (
                    "Website discovered via registry-listed email domain; "
                    f"exact-entity verification passed ({reason})."
                )
                envelopes[idx]["profile"]["evidence"]["website"] = new_ev
                stats["published_websites"] += 1
            else:
                stats["no_entity_match"] += 1
        else:
            stats["fetch_failed"] += 1
            # Preserve original not_found state; do not overwrite
            # (Optional: could set to ambiguous, but keeping original is safest for precision)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for env in envelopes:
            fh.write(json.dumps(env, ensure_ascii=False) + "\n")

    stats["runtime_ms"] = int((time.monotonic() - t0) * 1000)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envelopes", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    args = ap.parse_args()
    stats = process(Path(args.envelopes), Path(args.output), Path(args.report), args.limit)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
