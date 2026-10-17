#!/usr/bin/env python3
"""TinyFish Search-based website discovery.

For envelopes where the website claim is not_found, query TinyFish Search with
the exact legal name, filter out known directory domains, fetch the top
candidate, and publish only if the exact entity is verified on the fetched page.

Usage:
    uv run python scripts/run_tinyfish_discovery.py \
      --envelopes out/envelopes.jsonl \
      --output out/envelopes-with-search.jsonl \
      --report out/tinyfish-report.json \
      [--limit 100] [--workers 4]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from norway_company_agent.website import fetch_website


# Domains we never publish as a company website. Adding more is safe.
DIRECTORY_DOMAINS = {
    # Business directories (learned from smoke test)
    "proff.no", "vexter.no", "brreg.no", "virksomhet.brreg.no",
    "merinfo.no", "gulesider.no", "1881.no", "utdanning.no",
    "forvalt.no", "regnskapstall.no", "opplysning.byndle.no",
    "haandverkere.no", "haandverkerportalen.no", "mesteralliansen.no",
    "listings.no", "cylex.no", "byndle.no", "bedriftsok.no",
    "firmaregisteret.no", "norge.no", "arbeidsplassen.nav.no",
    "firmadatabasen.no", "aksjegrafen.com", "1850.no",
    "sameieplassen.no", "borettslagsportalen.no", "norgelei.no",
    "eiendomssjekk.no", "visverdi.no", "nabonytt.no",
    "barnehagelisten.no", "startuplink.no", "fagfolkguiden.no",
    "jobbi.no", "bestemeglere.no", "partnerinnhold.no",
    "regnskapstall.no", "purehelp.no", "smilefjes.mattilsynet.no",
    "finn.no", "mittanbud.no", "anbudstorget.no", "bedriftsdatabasen.no",
    "norskebedrifter.no", "firmasok.no", "proff-forvalt.no",
    "local.ch", "yelp.com", "tripadvisor.com",
    "foretak.io.no", "mn24.no", "bestilletransport.no",
    "aikidovation.com", "wyssenavalanche.com",
    # Government / public
    "sgregister.dibk.no", "dibk.no", "skatteetaten.no", "altinn.no",
    "doffin.no", "nav.no", "ssb.no", "regjeringen.no", "kommune.no",
    # News sites (learned from smoke test)
    "bt.no", "ba.no", "vg.no", "nrk.no", "e24.no", "dn.no",
    "aftenposten.no", "aftenbladet.no", "adressa.no", "nettavisen.no",
    "tu.no", "lister24.no", "abcnyheter.no", "nordnorskdebatt.no",
    "energiwatch.no", "energiogklima.no", "dagbladet.no", "tv2.no",
    "hegnar.no", "finansavisen.no", "forskning.no", "fhi.no",
    # Ratings / marketplaces
    "trustpilot.com", "yelp.no",
    # Social / video
    "facebook.com", "linkedin.com", "instagram.com", "youtube.com",
    "youtu.be", "x.com", "twitter.com", "tiktok.com",
    "pinterest.com", "snapchat.com",
    # Encyclopaedias / reference
    "wikipedia.org", "snl.no", "storenorske.no", "britannica.com",
    "liveabout.com", "thespruce.com", "thoughtco.com", "about.com",
    "quora.com", "reddit.com", "medium.com",
    # Academic
    "ac.id", "scholar.google.com", "researchgate.net",
    "ssrn.com", "jstor.org", "sciencedirect.com",
    # Sector niches
    "arkitektbedriftene.no", "arkitektkontorer.no", "arkitektplassen.no",
    "malerplassen.no", "mesterbedriftene.no", "elektroforeningen.no",
    # Map/aggregators
    "google.com", "google.no", "bing.com", "apple.com", "mapquest.com",
    "openstreetmap.org",
}

SOCIAL_HOSTS = {
    "facebook.com", "linkedin.com", "instagram.com", "youtube.com",
    "youtu.be", "x.com", "twitter.com", "tiktok.com", "pinterest.com",
    "snapchat.com",
}

TINYFISH_URL = "https://api.search.tinyfish.ai"
UA = "SignalpostResearchPOC/1.0 (+https://builderr.ai)"

# Simple in-process rate limiter — TinyFish free tier allows 30 queries/minute.
# One query per 2.2 seconds keeps us safely under.
MIN_QUERY_INTERVAL = 2.2
_last_query_at = 0.0


def _throttle() -> None:
    global _last_query_at
    elapsed = time.monotonic() - _last_query_at
    if elapsed < MIN_QUERY_INTERVAL:
        time.sleep(MIN_QUERY_INTERVAL - elapsed)
    _last_query_at = time.monotonic()


def tinyfish_search(query: str, key: str) -> list[dict]:
    _throttle()
    url = f"{TINYFISH_URL}?{urllib.parse.urlencode({'query': query, 'location': 'NO', 'language': 'no'})}"
    req = urllib.request.Request(url, headers={
        "X-API-Key": key,
        "User-Agent": UA,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read())
    return data.get("results", []) or []


def _host_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return ""


# URL path patterns that indicate a directory/listing page, not a company site.
DIRECTORY_PATH_PATTERNS = (
    "/selskap/", "/bedrift/", "/company/", "/firma/", "/virksomhet/",
    "/details/", "/profil/", "/profil-", "/m/company/", "/a/company/",
    "/barnehage/", "/startup/", "/startup-", "/medlemsbedrift/",
    "/spisested/", "/bedriftsroboten/", "/nyheter/", "/artikkel/",
    "/stilling/", "/eiendomsmeglere/", "/borettslag/", "/sameie/",
    "/aksjonaer", "/aksjon%C3%A6r", "/account/", "/nettbutikk/",
    "/informasjon-om/", "/company-details", "/finn-arkitekt/",
    "/finn-", "/bedrifter/", "/overtakelse/", "/konkurs/",
    "/transportfirmaer/", "/regnskapsnytt/", "/topics/",
    "/foretak/", "/foretak-", "/kredittverdi/",
    "/legal-notice/", "/personvernerklaering/",
)


def _is_directory(url: str) -> bool:
    host = _host_of(url).lower().lstrip("www.")
    if any(host == d or host.endswith("." + d) for d in DIRECTORY_DOMAINS | SOCIAL_HOSTS):
        return True
    # Path-pattern heuristic
    path = urllib.parse.urlparse(url).path.lower()
    if any(pat in path for pat in DIRECTORY_PATH_PATTERNS):
        return True
    return False


def _is_social(url: str) -> bool:
    host = _host_of(url).lower().lstrip("www.")
    return any(host == d or host.endswith("." + d) for d in SOCIAL_HOSTS)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


# Legal-form suffixes and stop words we never use as tokens.
_STOPWORDS = {
    "as", "asa", "sa", "ans", "da", "enk", "nuf", "ba", "sti", "iks", "kf",
    "og", "the", "of", "and", "for", "i", "pa", "av", "til", "med", "en",
    "et", "den", "det", "de", "som", "er", "har", "nor", "norge", "norway",
}


def name_tokens(name: str) -> set[str]:
    """Significant tokens from a company legal name (>3 chars, not legal form)."""
    return {
        t for t in re.findall(r"[a-z0-9æøå]+", (name or "").lower())
        if len(t) > 3 and t not in _STOPWORDS
    }


def domain_shares_token(url: str, legal_name: str) -> bool:
    """True if the URL's registered domain contains any significant token
    from the company legal name. Directories never do."""
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return False
    host = host.lower().lstrip("www.")
    # Use the "middle" part (before the TLD) as the slug
    parts = host.split(".")
    slug = "".join(parts[:-1]) if len(parts) >= 2 else host
    tokens = name_tokens(legal_name)
    if not tokens:
        return False
    return any(tok in slug for tok in tokens)


def spaced_orgnr(orgnr: str) -> str:
    if len(orgnr) != 9:
        return orgnr
    return f"{orgnr[:3]} {orgnr[3:6]} {orgnr[6:]}"


def entity_in_page(evidence_value: dict, orgnr: str, legal_name: str) -> tuple[bool, str]:
    """Publish only if orgnr is present ANYWHERE, or the exact legal name
    appears in the page TITLE (not just anywhere in the body)."""
    title = str(evidence_value.get("title") or "")
    description = str(evidence_value.get("description") or "")
    body = str(evidence_value.get("main_text_excerpt") or "")
    all_body = [description, body]
    for page in (evidence_value.get("pages") or []):
        all_body.append(str(page.get("title") or ""))
        all_body.append(str(page.get("main_text_excerpt") or ""))

    # ONLY orgnr in body text counts. Name matches are too weak on
    # directory pages because directories put the company name in their titles.
    body_blob = norm(" ".join(all_body))
    spaced = norm(spaced_orgnr(orgnr))
    if orgnr in body_blob or spaced in body_blob:
        return True, "orgnr_in_body"

    return False, "no_entity_match"


def process_one(idx: int, env: dict, key: str) -> dict:
    """Return a stats row describing what happened for this envelope."""
    result = {"idx": idx, "state": "skipped", "reason": None, "published_url": None}

    profile = env.get("profile") or {}
    ev = profile.get("evidence") or {}
    web = ev.get("website") or {}
    if web.get("status") == "available":
        result["state"] = "already_has_website"
        return result

    orgnr = str(env.get("organisation_number") or "")
    name = str(profile.get("name") or "").strip()
    if not orgnr or not name:
        result["state"] = "missing_inputs"
        return result

    # Query TinyFish with the quoted legal name only (winner from testing)
    try:
        results = tinyfish_search(f'"{name}"', key)
    except Exception as e:
        result["state"] = "search_error"
        result["reason"] = f"{type(e).__name__}: {str(e)[:80]}"
        return result

    if not results:
        result["state"] = "no_results"
        return result

    # Filter directories/socials and try candidates in order
    # Extra gate: reject any candidate whose URL path contains the orgnr.
    # This is a 100% directory signal — company-owned sites never put their
    # orgnr in the URL slug.
    spaced_path = spaced_orgnr(orgnr).replace(" ", "")
    candidates = []
    for r in results:
        u = r.get("url") or ""
        if not u or _is_directory(u):
            continue
        path_and_query = urllib.parse.urlparse(u).path + urllib.parse.urlparse(u).query
        if orgnr in path_and_query or spaced_path in path_and_query:
            continue
        candidates.append(r)

    if not candidates:
        result["state"] = "only_directories"
        return result

    for cand in candidates[:3]:
        candidate_url = cand["url"]
        # Token-match gate — the domain must share a significant name token
        if not domain_shares_token(candidate_url, name):
            continue
        try:
            rec, _ = fetch_website(candidate_url)
        except Exception as e:
            continue
        if rec.get("status") != "available":
            continue
        ok, reason = entity_in_page(rec.get("value") or {}, orgnr, name)
        if not ok:
            continue

        # Normalize published URL to the site root (drop deep paths)
        final_url = rec.get("value", {}).get("final_url") or candidate_url
        parsed_final = urllib.parse.urlparse(final_url)
        root_url = f"{parsed_final.scheme}://{parsed_final.netloc}/"

        new_ev = dict(rec)
        new_ev["source_url"] = root_url
        new_ev["value"] = dict(rec.get("value") or {})
        new_ev["value"]["requested_url"] = root_url
        new_ev["value"]["final_url"] = final_url
        new_ev["source_type"] = "web_search_verified"
        new_ev["source_class"] = "web_search_verified"
        new_ev["note"] = (
            "Website discovered via TinyFish Search on exact legal name; "
            f"exact-entity verification passed on the fetched page ({reason}); "
            "published URL normalized to site root."
        )
        env["profile"]["evidence"]["website"] = new_ev
        result["state"] = "published"
        result["reason"] = reason
        result["published_url"] = root_url
        return result

    result["state"] = "no_entity_match"
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envelopes", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1,
                    help="Keep 1 for safety; the internal throttle is global.")
    args = ap.parse_args()

    key = os.environ.get("TINYFISH_API_KEY")
    if not key:
        raise SystemExit("TINYFISH_API_KEY not set")

    envelopes = [json.loads(l) for l in Path(args.envelopes).read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit and args.limit > 0:
        envelopes = envelopes[:args.limit]

    t0 = time.monotonic()
    rows: list[dict] = []

    # Sequential execution — TinyFish throttles at 30/min and adding more
    # concurrency risks 429s. Runtime for 1000 is ~40-50 minutes; acceptable.
    for i, env in enumerate(envelopes):
        row = process_one(i, env, key)
        rows.append(row)
        if (i + 1) % 25 == 0:
            elapsed = time.monotonic() - t0
            rate = (i + 1) / elapsed * 60
            print(f"  {i+1}/{len(envelopes)}  ({rate:.1f}/min)  "
                  f"published={sum(1 for r in rows if r['state']=='published')}")

    # Post-hoc frequency filter: any registered domain appearing for
    # >2 companies in this run is a directory. Block those.
    from collections import Counter
    import tldextract
    domain_counts = Counter()
    for env in envelopes:
        ev = (env.get("profile") or {}).get("evidence") or {}
        web = ev.get("website") or {}
        if web.get("source_type") == "web_search_verified" and web.get("source_url"):
            host = urllib.parse.urlparse(web["source_url"]).hostname or ""
            ext = tldextract.extract(host)
            dom = ext.top_domain_under_public_suffix
            if dom:
                domain_counts[dom] += 1

    blocked_by_freq = {d for d, n in domain_counts.items() if n > 2}
    if blocked_by_freq:
        print(f"Frequency filter blocking {len(blocked_by_freq)} domains: {sorted(blocked_by_freq)[:10]}")

    for env in envelopes:
        ev = (env.get("profile") or {}).get("evidence") or {}
        web = ev.get("website") or {}
        if web.get("source_type") == "web_search_verified" and web.get("source_url"):
            host = urllib.parse.urlparse(web["source_url"]).hostname or ""
            ext = tldextract.extract(host)
            dom = ext.top_domain_under_public_suffix
            if dom in blocked_by_freq:
                # Revert to not_found with a diagnostic note
                env["profile"]["evidence"]["website"] = {
                    "field": "website",
                    "status": "not_found",
                    "source_type": "registry_linked_company_website",
                    "source_class": "registry_linked_company_website",
                    "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter",
                    "retrieved_at": web.get("retrieved_at"),
                    "value": None,
                    "as_of": None,
                    "note": f"Candidate {web.get('source_url')} rejected: domain appears for multiple companies (likely directory).",
                    "content_sha256": None,
                    "source_row_key": None,
                    "effective_at": None,
                }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.output).open("w", encoding="utf-8") as fh:
        for env in envelopes:
            fh.write(json.dumps(env, ensure_ascii=False) + "\n")

    stats = {
        "input_envelopes": len(envelopes),
        "published_websites": sum(1 for r in rows if r["state"] == "published"),
        "already_has_website": sum(1 for r in rows if r["state"] == "already_has_website"),
        "no_results": sum(1 for r in rows if r["state"] == "no_results"),
        "only_directories": sum(1 for r in rows if r["state"] == "only_directories"),
        "no_entity_match": sum(1 for r in rows if r["state"] == "no_entity_match"),
        "search_error": sum(1 for r in rows if r["state"] == "search_error"),
        "missing_inputs": sum(1 for r in rows if r["state"] == "missing_inputs"),
        "skipped": sum(1 for r in rows if r["state"] == "skipped"),
        "runtime_s": round(time.monotonic() - t0, 1),
        "published_rows": [r for r in rows if r["state"] == "published"],
    }
    Path(args.report).write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "published_rows"}, indent=2))


if __name__ == "__main__":
    main()
