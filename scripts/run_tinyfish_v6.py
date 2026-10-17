#!/usr/bin/env python3
"""TinyFish website discovery v6 - parallel fetch, serial query."""
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


TINYFISH_URL = "https://api.search.tinyfish.ai"
UA = "SignalpostResearchPOC/1.0 (+https://builderr.ai)"
MIN_INTERVAL = 2.2
_last_query = 0.0


DIRECTORY_DOMAINS = {
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
    "purehelp.no", "smilefjes.mattilsynet.no", "foretak.io.no",
    "mn24.no", "bestilletransport.no", "aikidovation.com",
    "wyssenavalanche.com", "finn.no", "mittanbud.no", "anbudstorget.no",
    "bedriftsdatabasen.no", "norskebedrifter.no", "firmasok.no",
    "proff-forvalt.no", "local.ch", "yelp.com", "tripadvisor.com",
    "sgregister.dibk.no", "dibk.no", "skatteetaten.no", "altinn.no",
    "doffin.no", "nav.no", "ssb.no", "regjeringen.no", "kommune.no",
    "bt.no", "ba.no", "vg.no", "nrk.no", "e24.no", "dn.no",
    "aftenposten.no", "aftenbladet.no", "adressa.no", "nettavisen.no",
    "tu.no", "lister24.no", "abcnyheter.no", "nordnorskdebatt.no",
    "energiwatch.no", "energiogklima.no", "dagbladet.no", "tv2.no",
    "hegnar.no", "finansavisen.no", "forskning.no", "fhi.no",
    "trustpilot.com", "yelp.no",
    "facebook.com", "linkedin.com", "instagram.com", "youtube.com",
    "youtu.be", "x.com", "twitter.com", "tiktok.com",
    "pinterest.com", "snapchat.com",
    "wikipedia.org", "snl.no", "storenorske.no", "britannica.com",
    "liveabout.com", "thespruce.com", "thoughtco.com", "about.com",
    "quora.com", "reddit.com", "medium.com",
    "ac.id", "scholar.google.com", "researchgate.net",
    "ssrn.com", "jstor.org", "sciencedirect.com",
    "arkitektbedriftene.no", "arkitektkontorer.no", "arkitektplassen.no",
    "malerplassen.no", "mesterbedriftene.no", "elektroforeningen.no",
    "google.com", "google.no", "bing.com", "apple.com", "mapquest.com",
    "openstreetmap.org",
}

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
    "/legal-notice/", "/personvernerklaering/", "/foretak/", "/foretak-",
    "/kredittverdi/",
)

_STOPWORDS = {
    "as", "asa", "sa", "ans", "da", "enk", "nuf", "ba", "sti", "iks", "kf",
    "og", "the", "of", "and", "for", "i", "pa", "av", "til", "med", "en",
    "et", "den", "det", "de", "som", "er", "har", "nor", "norge", "norway",
}


def _throttle() -> None:
    global _last_query
    elapsed = time.monotonic() - _last_query
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_query = time.monotonic()


def _host_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return ""


def _is_directory(url: str) -> bool:
    host = _host_of(url).lower().lstrip("www.")
    if any(host == d or host.endswith("." + d) for d in DIRECTORY_DOMAINS):
        return True
    path = urllib.parse.urlparse(url).path.lower()
    return any(pat in path for pat in DIRECTORY_PATH_PATTERNS)


def _name_tokens(name: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9\u00e6\u00f8\u00e5]+", (name or "").lower())
        if len(t) > 3 and t not in _STOPWORDS
    }


def _domain_shares_token(url: str, name: str) -> bool:
    host = _host_of(url).lower().lstrip("www.")
    parts = host.split(".")
    slug = "".join(parts[:-1]) if len(parts) >= 2 else host
    tokens = _name_tokens(name)
    return bool(tokens) and any(tok in slug for tok in tokens)


def _spaced(orgnr: str) -> str:
    return f"{orgnr[:3]} {orgnr[3:6]} {orgnr[6:]}" if len(orgnr) == 9 else orgnr


def _orgnr_on_page(value: dict, orgnr: str) -> bool:
    texts = [
        str(value.get("title") or ""),
        str(value.get("description") or ""),
        str(value.get("main_text_excerpt") or ""),
    ]
    for page in (value.get("pages") or []):
        texts.append(str(page.get("main_text_excerpt") or ""))
    blob = re.sub(r"\s+", " ", " ".join(texts)).lower()
    spaced = _spaced(orgnr)
    return orgnr in blob or spaced in blob


def tinyfish(query: str, key: str) -> list[dict]:
    _throttle()
    url = f"{TINYFISH_URL}?{urllib.parse.urlencode({'query': query, 'location': 'NO', 'language': 'no'})}"
    req = urllib.request.Request(url, headers={
        "X-API-Key": key, "User-Agent": UA, "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()).get("results", []) or []
    except Exception:
        return []


def collect_candidates(env: dict, key: str) -> tuple[int, dict, str, list[str]]:
    """Serial phase: returns (index, env, state, candidate_urls)."""
    profile = env.get("profile") or {}
    ev = profile.get("evidence") or {}
    if (ev.get("website") or {}).get("status") == "available":
        return (0, env, "already_has_website", [])

    reg = (ev.get("registry") or {}).get("value") or {}
    orgnr = str(env.get("organisation_number") or "")
    name = str(reg.get("navn") or profile.get("name") or "").strip()
    if not orgnr or not name:
        return (0, env, "missing_inputs", [])

    results = tinyfish(f'"{name}"', key)
    if not results:
        return (0, env, "no_results", [])

    spaced = _spaced(orgnr).replace(" ", "")
    candidates: list[str] = []
    for r in results:
        u = r.get("url") or ""
        if not u or _is_directory(u):
            continue
        pq = urllib.parse.urlparse(u).path + urllib.parse.urlparse(u).query
        if orgnr in pq or spaced in pq:
            continue
        if not _domain_shares_token(u, name):
            continue
        candidates.append(u)

    if not candidates:
        return (0, env, "only_directories", [])
    return (0, env, "has_candidates", candidates)


def verify_and_publish(env: dict, candidates: list[str]) -> tuple[str, str | None]:
    """Parallel phase: fetch candidates, verify, publish first match."""
    profile = env.get("profile") or {}
    reg = (profile.get("evidence") or {}).get("registry") or {}
    value = reg.get("value") or {}
    orgnr = str(env.get("organisation_number") or "")

    for candidate_url in candidates[:5]:
        try:
            rec, _ = fetch_website(candidate_url)
        except Exception:
            continue
        if rec.get("status") != "available":
            continue
        if not _orgnr_on_page(rec.get("value") or {}, orgnr):
            continue

        final_url = (rec.get("value") or {}).get("final_url") or candidate_url
        parsed = urllib.parse.urlparse(final_url)
        root_url = f"{parsed.scheme}://{parsed.netloc}/"

        new_ev = dict(rec)
        new_ev["source_url"] = root_url
        new_ev["value"] = dict(rec.get("value") or {})
        new_ev["value"]["requested_url"] = root_url
        new_ev["value"]["final_url"] = final_url
        new_ev["source_type"] = "web_search_verified"
        new_ev["source_class"] = "web_search_verified"
        new_ev["note"] = (
            "Website discovered via TinyFish Search on exact legal name; "
            "exact-entity verification passed because the company's "
            "organisation number appears on the fetched page."
        )
        env["profile"]["evidence"]["website"] = new_ev
        return ("published", candidate_url)

    return ("no_entity_match", None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envelopes", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    key = os.environ.get("TINYFISH_API_KEY")
    if not key:
        raise SystemExit("TINYFISH_API_KEY not set")

    envelopes = [json.loads(l) for l in Path(args.envelopes).read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        envelopes = envelopes[:args.limit]

    t0 = time.monotonic()
    states: dict[str, int] = {}
    published_rows: list[dict] = []

    # Phase 1 — serial TinyFish queries
    print(f"Phase 1: querying TinyFish for {len(envelopes)} companies...")
    candidates_by_idx: dict[int, tuple[dict, str, list[str]]] = {}
    for i, env in enumerate(envelopes):
        _, env2, state, candidates = collect_candidates(env, key)
        if state in ("already_has_website", "missing_inputs", "no_results", "only_directories"):
            states[state] = states.get(state, 0) + 1
        else:
            candidates_by_idx[i] = (env2, state, candidates)
        if (i + 1) % 100 == 0:
            elapsed = time.monotonic() - t0
            print(f"  query {i+1}/{len(envelopes)}  ({elapsed:.0f}s elapsed)  candidates_pending={len(candidates_by_idx)}")

    # Phase 2 — parallel fetch + verify
    print(f"Phase 2: fetching/verifying {len(candidates_by_idx)} candidate sets with {args.workers} workers...")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(verify_and_publish, env, cands): idx
            for idx, (env, _state, cands) in candidates_by_idx.items()
        }
        done = 0
        for fut in as_completed(futures):
            idx = futures[fut]
            env = candidates_by_idx[idx][0]
            try:
                state, url = fut.result()
            except Exception:
                state, url = "no_entity_match", None
            states[state] = states.get(state, 0) + 1
            if state == "published":
                published_rows.append({"orgnr": env.get("organisation_number"), "url": url})
            done += 1
            if done % 25 == 0:
                elapsed = time.monotonic() - t0
                print(f"  verify {done}/{len(candidates_by_idx)}  ({elapsed:.0f}s elapsed)  published={len(published_rows)}")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.output).open("w", encoding="utf-8") as fh:
        for env in envelopes:
            fh.write(json.dumps(env, ensure_ascii=False) + "\n")

    report = {
        "input_envelopes": len(envelopes),
        "published": len(published_rows),
        "state_counts": states,
        "runtime_s": round(time.monotonic() - t0, 1),
        "published_urls": published_rows,
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "published_urls"}, indent=2))


if __name__ == "__main__":
    main()
