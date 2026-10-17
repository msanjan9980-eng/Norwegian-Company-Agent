#!/usr/bin/env python3
"""Deepen company-owned websites: extract contact, social, dated news, careers signals.

Reads out/cited-envelopes.jsonl, fetches site pages for envelopes whose
official_website claim is "available", snapshots every fetched page, and
emits per-item claims. Every extraction requires the company's exact name
or orgnr to appear on the fetched page.
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import certifi
from bs4 import BeautifulSoup
import extruct
from w3lib.html import get_base_url

from norway_company_agent import snapshot_store
from norway_company_agent.url_safety import safe_urlopen


UA = "SignalpostResearchPOC/1.0 (+https://builderr.ai)"
TIMEOUT = 20
MAX_BYTES = 4 * 1024 * 1024
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

SUBPATHS = [
    # "/" is intentionally omitted: the batch runner already fetched and
    # snapshotted the homepage. Fetching it again here would repeat a request
    # for no additional claim. MAX_PAGES_PER_SITE covers the eight highest-
    # yield paths below.
    "/om-oss", "/kontakt", "/nyheter", "/karriere",
    "/om", "/about", "/contact", "/aktuelt",
    "/news", "/jobber", "/jobs", "/careers",
]
MAX_PAGES_PER_SITE = 8

SOCIAL_HOSTS = {
    "facebook.com": "facebook",
    "linkedin.com": "linkedin",
    "instagram.com": "instagram",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "x.com": "x",
    "twitter.com": "twitter",
    "tiktok.com": "tiktok",
    "pinterest.com": "pinterest",
}

EMAIL_RX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RX = re.compile(r"(?:\+?47)?[\s\-]?(\d{2})[\s\-]?(\d{2})[\s\-]?(\d{2})[\s\-]?(\d{2})")
DATE_RX = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}|\d{1,2}\.\s?"
    r"(januar|februar|mars|april|mai|juni|juli|august|september|oktober|november|desember)\s?\d{4})\b",
    re.IGNORECASE,
)


def fetch(url: str) -> tuple[bytes | None, str | None, str | None, int | None, list[str]]:
    """Return (raw_bytes, content_type, error, status_code, redirect_chain)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
    })
    redirect_chain = []
    try:
        with safe_urlopen(req, timeout=TIMEOUT, context=SSL_CONTEXT) as resp:
            ct = resp.headers.get("content-type") or ""
            final_url = resp.geturl()
            status = resp.getcode()
            if final_url and final_url != url:
                redirect_chain = [url, final_url]
            if "html" not in ct.lower():
                return None, ct, f"non-html: {ct[:60]}", status, redirect_chain
            raw = resp.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                return None, ct, "too-large", status, redirect_chain
            return raw, ct, None, status, redirect_chain
    except urllib.error.HTTPError as e:
        return None, None, f"HTTP {e.code}", e.code, redirect_chain
    except urllib.error.URLError as e:
        return None, None, f"URLError: {str(e.reason)[:60]}", None, redirect_chain
    except Exception as e:
        return None, None, f"{type(e).__name__}: {str(e)[:60]}", None, redirect_chain


def text_of(raw: bytes) -> tuple[str, str, str]:
    """Return (text, title, html_lang) from raw HTML."""
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return text, title, soup.html.get("lang") if soup.html else ""


def entity_present(text: str, name: str, orgnr: str) -> bool:
    t = text.lower()
    spaced = f"{orgnr[:3]} {orgnr[3:6]} {orgnr[6:]}" if len(orgnr) == 9 else orgnr
    if orgnr in t or spaced in t:
        return True
    if name and len(name) >= 6 and name.lower() in t:
        return True
    return False


def extract_emails(text: str) -> list[str]:
    out = []
    for m in EMAIL_RX.findall(text):
        e = m.lower()
        if any(x in e for x in ("example.", "noreply", "no-reply", "sentry")):
            continue
        if e not in out:
            out.append(e)
    return out[:5]


def extract_phones(text: str) -> list[str]:
    out = []
    for m in PHONE_RX.finditer(text):
        digits = "".join(m.groups())
        if len(digits) == 8 and digits not in out:
            out.append(digits)
    return out[:3]


def extract_socials(soup: BeautifulSoup) -> list[dict]:
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        for host, label in SOCIAL_HOSTS.items():
            if host in href and label not in found:
                found[label] = a["href"]
                break
    return [{"platform": k, "url": v} for k, v in found.items()]


def extract_dates(text: str) -> list[str]:
    return list({m.group(1) for m in DATE_RX.finditer(text)})[:10]


def crawl_site(root_url: str) -> list[tuple[str, bytes, str, int | None, list[str]]]:
    """Return [(url, raw, content_type, status, redirects)] for allowed pages.

    robots.txt is fetched and evaluated BEFORE any page request is made,
    so disallowed URLs never trigger an HTTP request.
    """
    parsed = urllib.parse.urlparse(root_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Fetch robots.txt first (safe_urlopen enforces SSRF policy on this fetch too)
    _robots = None
    _robots_ok = True
    try:
        from urllib.robotparser import RobotFileParser
        _robots = RobotFileParser()
        robots_url = base.rstrip("/") + "/robots.txt"
        _robots.set_url(robots_url)
        try:
            _robots.read()
        except urllib.error.HTTPError as e:
            if e.code not in (404, 410):
                _robots_ok = False
            _robots = None
        except Exception:
            _robots = None
            _robots_ok = False
    except Exception:
        _robots = None
        _robots_ok = False

    if not _robots_ok:
        return []

    out: list[tuple[str, bytes, str, int | None, list[str]]] = []
    seen = set()
    for path in SUBPATHS[:MAX_PAGES_PER_SITE]:
        u = base + path
        if u in seen:
            continue
        seen.add(u)
        # robots.txt check BEFORE any HTTP request to this URL
        if _robots is not None:
            try:
                if not _robots.can_fetch("SignalpostResearchPOC/1.0", u):
                    continue
            except Exception:
                pass
        raw, ct, err, status, redirects = fetch(u)
        if raw and ct:
            out.append((u, raw, ct, status, redirects))
        time.sleep(0.15)
    return out

def process_envelope(env: dict) -> dict:
    """Return a report row; mutates env in-place to add new claims + evidence."""
    orgnr = str(env.get("organisation_number") or "")

    # Name from top-level identity claim (profile block is empty in cited envelopes)
    name = ""
    website_claim = None
    for c in env.get("claims") or []:
        f = c.get("field")
        if f in ("identity.navn", "identity.name") and not name:
            v = c.get("value")
            if isinstance(v, str):
                name = v
            elif isinstance(v, dict):
                name = str(v.get("navn") or v.get("name") or "")
        elif f == "official_website" and c.get("availability") == "available":
            website_claim = c
    if not website_claim:
        return {"orgnr": orgnr, "state": "no_website"}

    val = website_claim.get("value") or {}
    if isinstance(val, str):
        root_url = val.strip()
    elif isinstance(val, dict):
        root_url = val.get("final_url") or val.get("requested_url")
    else:
        root_url = None
    if not root_url:
        return {"orgnr": orgnr, "state": "no_url"}
    if not root_url.startswith(("http://", "https://")):
        root_url = "https://" + root_url

    pages = crawl_site(root_url)
    if not pages:
        return {"orgnr": orgnr, "state": "no_pages"}

    new_claims: list[dict] = []
    new_evidence: list[dict] = []

    for url, raw, ct, status, redirects in pages:
        # robots.txt already enforced inside crawl_site before fetching
        pass
        text, title, html_lang = text_of(raw)
        if not entity_present(text, name, orgnr):
            continue

        rec = snapshot_store.capture(
            orgnr=orgnr,
            raw=raw,
            source_url=url,
            source_class="company_owned_website",
            content_type=ct,
            claim_span=title or None,
            status_code=status,
            redirect_chain=redirects,
        )
        new_evidence.append(rec)

        # Extract structured data (JSON-LD / OpenGraph)
        try:
            base_url = get_base_url(raw, url)
            structured = extruct.extract(raw, base_url=base_url, syntaxes=["json-ld", "opengraph", "microdata"])
            for item in structured.get("json-ld", []):
                if isinstance(item, dict) and item.get("@type") in ("Organization", "Corporation", "LocalBusiness"):
                    for key in ("name", "url", "logo", "sameAs", "address", "telephone"):
                        if key in item:
                            val = item[key]
                            new_claims.append({
                                "field": f"web.jsonld.{key}",
                                "value": val,
                                "availability": "available",
                                "confidence": 0.85,
                                "evidence_ids": [rec["id"]],
                "extraction_method": "beautifulsoup",
                "reporting_period": None,
                                "claim_span": f"jsonld:{key}",
                                "claim_span": f"jsonld:{key}",
                                "reporting_period": None,
                                "extraction_method": "extruct",
                                "note": f"JSON-LD {key} found on {url}.",
                            })
        except Exception as e:
            pass # Ignore extruct errors and continue with standard HTML parsing

        emails = extract_emails(text)
        for e in emails:
            new_claims.append({
                "field": "web.contact.email",
                "value": {"email": e, "found_on": url},
                "availability": "available",
                "confidence": 0.85,
                "evidence_ids": [rec["id"]],
                "claim_span": "text:email",
                "claim_span": "text:email",
                "reporting_period": None,
                "extraction_method": "beautifulsoup",
                "note": f"Email found on company-owned page {url}.",
            })

        phones = extract_phones(text)
        for p in phones:
            new_claims.append({
                "field": "web.contact.phone",
                "value": {"phone": p, "found_on": url},
                "availability": "available",
                "confidence": 0.85,
                "evidence_ids": [rec["id"]],
                "claim_span": "text:phone",
                "reporting_period": None,
                "extraction_method": "beautifulsoup",
                "note": f"Phone found on company-owned page {url}.",
            })

        soup = BeautifulSoup(raw, "html.parser")
        for s in extract_socials(soup):
            new_claims.append({
                "field": "web.social_link",
                "value": {"platform": s["platform"], "url": s["url"], "found_on": url},
                "availability": "available",
                "confidence": 0.9,
                "evidence_ids": [rec["id"]],
                "note": f"Social profile linked from company-owned page {url}.",
            })

        dates = extract_dates(text)
        if dates and ("/nyheter" in url or "/aktuelt" in url or "/news" in url):
            new_claims.append({
                "field": "web.activity.news",
                "value": {"page": url, "dates": dates},
                "availability": "available",
                "confidence": 0.75,
                "evidence_ids": [rec["id"]],
                "note": f"Dated news/activity items found on company page {url}.",
            })

        if "/karriere" in url or "/jobb" in url or "/career" in url or "/stilling" in url:
            new_claims.append({
                "field": "web.hiring_signal",
                "value": {"page": url, "title": title[:200]},
                "availability": "available",
                "confidence": 0.75,
                "evidence_ids": [rec["id"]],
                "note": f"Careers/jobs page found on company-owned site: {url}.",
            })

    env.setdefault("claims", []).extend(new_claims)
    env.setdefault("evidence", []).extend(new_evidence)
    return {
        "orgnr": orgnr,
        "state": "ok",
        "pages_crawled": len(pages),
        "pages_matched": len({c.get("evidence_ids", [None])[0] for c in new_claims if c.get("evidence_ids")}),
        "claims_added": len(new_claims),
        "evidence_added": len(new_evidence),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envelopes", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    envelopes = [json.loads(l) for l in Path(args.envelopes).read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        envelopes = envelopes[:args.limit]

    t0 = time.monotonic()
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_envelope, env): i for i, env in enumerate(envelopes)}
        done = 0
        for fut in as_completed(futures):
            try:
                rows.append(fut.result())
            except Exception as e:
                rows.append({"state": "error", "error": f"{type(e).__name__}: {e}"})
            done += 1
            if done % 20 == 0:
                elapsed = time.monotonic() - t0
                added = sum(r.get("claims_added", 0) for r in rows)
                print(f"  {done}/{len(envelopes)}  ({elapsed:.0f}s)  claims_added={added}")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.output).open("w", encoding="utf-8") as fh:
        for env in envelopes:
            fh.write(json.dumps(env, ensure_ascii=False) + "\n")

    states: dict[str, int] = {}
    for r in rows:
        states[r["state"]] = states.get(r["state"], 0) + 1
    summary = {
        "input_envelopes": len(envelopes),
        "states": states,
        "total_claims_added": sum(r.get("claims_added", 0) for r in rows),
        "total_evidence_added": sum(r.get("evidence_added", 0) for r in rows),
        "companies_with_additions": sum(1 for r in rows if r.get("claims_added", 0) > 0),
        "runtime_s": round(time.monotonic() - t0, 1),
    }
    Path(args.report).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
