# Signalpost entry - Norwegian company agent

Reproducible research agent producing one terminal JSON envelope per
Norwegian organisation number, with citation-validated evidence and a
static HTML viewer.

**Repository:** https://github.com/msanjan9980-eng/Norwegian-Company-Agent

## One command to run

Preferred (works on Linux, macOS, Windows):

    python run.py entry-companies.jsonl 1000

Or, if you have a POSIX shell:

    sh run.sh entry-companies.jsonl 1000

Where `entry-companies.jsonl` is your batch file (JSON / JSONL / plain text
list of Norwegian organisation numbers) and `1000` is the expected count.

## What it does

1. Reads your company list (any of the 411,160 eligible Norwegian companies).
2. Fetches live data from Brreg per company: registry, financials, roles,
   group structure, locations, website, jobs, activity. No bulk snapshot.
3. Validates every envelope against the terminal-state contract.
4. Produces `out/envelopes.jsonl` - one result per input company, always.
5. Runs the citation pass to capture snapshots + sha256 evidence.

## What the envelopes contain

Top-level fields per envelope:

- `run_id`, `organisation_number`, `state`, `started_at`, `completed_at`
- `modules{}` - per-module state: complete, not_applicable, not_found,
  blocked_policy, blocked_robots, source_error, budget_exhausted,
  submission_error
- `claims[]` - one entry per fact with availability, confidence, evidence_ids
- `evidence[]` - source_url, source_class, retrieved_at, content_sha256
- `changes[]` - recent change signals derived from single-run data
- `summary` - plain-text synthesis: what the company does, what changed,
  what remains unknown with source URLs
- `profile` - the raw evidence blocks

## Models, APIs, licences

- **Models:** none in the default pipeline. Deterministic Python. An optional LLM synthesis step exists in scripts/llm_summary.py and is opt-in via SIGNALPOST_LLM=1 plus ANTHROPIC_API_KEY; it is off by default and is not required for scoring.
- **Registry snapshot:** If `SIGNALPOST_REGISTRY_SNAPSHOT` is set to a Brreg CSV/CSV.GZ path, it is used for identity anchoring. Otherwise live Brreg is used.
- **Profile sections:** Overview, Financials, Leadership, Locations, Hiring, Activity, Changes.
- **External APIs:** Brreg Enhetsregisteret + Regnskapsregisteret (public,
  no key required). NAV Arbeidsplassen (queried by default in the citation pass; pass `--skip-nav` to disable).
- **Python dependencies:** see `pyproject.toml`. All MIT, BSD, Apache-2.0,
  or PSF-licensed. No commercial or restricted-licence dependencies.
- **Expected cost per official run:** $0.00.

## Contact

Sanjan M — msanjan9980@gmail.com
## Cost & Budget

This agent is designed to run on a minimal external API budget.
- **Free Sources:** Brreg (data.brreg.no), NAV (pam-stilling-feed.nav.no), Google News RSS. These incur $0 in API costs.
- **Paid Sources:** Brave Search (optional, requires `BRAVE_SEARCH_API_KEY`). Pricing is roughly $3–$5 per 1,000 queries. A 1,000-company run queries roughly ~500 times, costing ~$1.50–$2.50.
- **Compute:** ~21 minutes wall clock for 1,000 companies using 32 workers.

Total expected cost per official run (1,000-1,100 companies): **Under $5**. Run with python run.py <batch>; the expected count is derived from the input file. Submit a 100-company smoke-test artifact alongside the 1,000-company run.

## Source Rights, Secrets, and Outbound Policy

- **Official registers:** Brønnøysundregistrene Enhetsregisteret and Regnskapsregisteret APIs. Open data, no authentication.
- **NAV:** `pam-stilling-feed.nav.no` public feed. No authentication.
- **Google News RSS:** Public RSS feeds. No authentication.
- **Company websites:** Crawled only after the exact entity is verified via the registry name/org-number check. `robots.txt` is respected; no login-walled pages are accessed.
- **Brave Search (optional):** Used only for candidate discovery. Requires `BRAVE_SEARCH_API_KEY` in the environment. If the key is absent, the connector is skipped; it never falls back to scraping search results as evidence.
- **No secrets are hardcoded.** All API keys are read from environment variables only. Experimental LinkedIn files (run_linkedin_guest_experiment.py, run_linkedin_guest_jobs_connector.py, discover_linkedin_company_profiles.py) are present but not in the default pipeline and cannot back any published claim.

## Claim schema

Every published claim carries:

- `field`: dotted public field name
- `value`: the reported value
- `availability`: one of `available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, `failed`
- `confidence`: extraction confidence in [0, 1]
- `evidence_ids`: list of evidence IDs backing the claim
- `claim_span`: pointer into the snapshot (JSON key, table cell, or short substring) proving where the value came from
- `extraction_method`: short label for how the value was extracted (e.g. `official_registry`, `financial_mapping`, `module_fallback`, `nav:posting`)
