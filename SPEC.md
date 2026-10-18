# Signalpost — Norwegian Company Agent

**Built by:** Sanjan M  ·  **Contact:** msanjan9980@gmail.com
**Repository:** https://github.com/msanjan9980-eng/Norwegian-Company-Agent
**Entry command:** `python run.py <organisations-file> [expected-count]`
**Built:** 2026-10-10  ·  **Deadline:** revisions 2026-10-18, close 2026-10-21.

## What this is

An evidence-first company research agent for Norwegian AS entities. Given any
Norwegian organisation number, it fetches live data from Brreg, extracts
structured facts, links each fact to a captured evidence record with a
content hash, and returns one terminal JSON envelope per input company.

Nothing is guessed. Where a source does not exist for a given company, the
claim is emitted as `not_available` rather than omitted. Where a source is
unreachable, `blocked` or `failed` is recorded with the HTTP status.

The agent requires no precomputed company list, no bulk snapshot, and no
prior state. It works on a fresh clone with no network configuration beyond
internet access.

## How to run

    python run.py entry-companies.jsonl

`entry-companies.jsonl` is a JSON, JSONL, or plain-text file of Norwegian
organisation numbers. The second argument is the expected count. The agent:

1. `uv sync` — installs dependencies.
2. Batch runner — one live fetch per company, parallelised.
3. Citation pass — re-fetches each source and captures a byte-exact
   snapshot with a sha256 hash.

Outputs:

- `out/envelopes.jsonl` — the terminal envelopes (one per input company)
- `out/cited-envelopes.jsonl` — the same envelopes with per-claim evidence IDs
- `out/run-report.json` — run metadata
- `snapshots/<orgnr>/` — the captured evidence files

On a POSIX shell, `sh run.sh <file> <count>` is equivalent. On Windows
PowerShell, `python run.py` is the tested path.

## Verified coverage — 100-company run, seed=7

Sampled from the current population. `python scripts/run_competition_batch.py`
with `--expected-count 1000 --workers 32`.

**Result:** 1,000/1,000 emitted, validation passed, 0 errors, 0 silent drops.
Full pipeline runtime: 21 minutes batch + 5 minutes citation. The committed
artifact in `out/cited-envelopes.jsonl` contains 1,000 envelopes,
71,989 claims, and 5,156 evidence records across 65 claim families.

Claim families at ≥90% company coverage:

| Family | Claims | Companies | Coverage |
|---|---:|---:|---:|
| identity.* (name, legal form, address, registration date, VAT, sector) | ~1,100 | 100 | 100% |
| accounting_obligation | 100 | 100 | 100% |
| identity_live | 100 | 100 | 100% |
| official_website | 100 | 100 | 100% |
| people.role.* | 438 | 99 | 99% |
| activity.entity_registered | 99 | 99 | 99% |
| activity.annual_account_filed | 99 | 99 | 99% |
| activity.founded | 98 | 98 | 98% |
| financials.* (revenue, result, assets, equity, debt, account type) | ~2,300 | 98 | 98% |
| group_structure | 95 | 95 | 95% |

Coverage below 90%, with reason:

| Family | Coverage | Why |
|---|---:|---|
| locations.subunit.* | 70% | Only companies with registered sub-units |
| activity.role_changed | 39% | Only roles whose `lastEndret` is within 12 months |
| identity.postal_address | 38% | Many entities share a business and postal address |
| group.child / group.entity | 5% | Most Norwegian AS entities are single-entity |
| jobs.has_postings | 9% | Only companies whose careers page emits schema.org JobPosting |
| web.social_link | 1% | Only companies whose site emits schema.org sameAs |

Everything not listed above is either a per-company fact (present at
99–100%) or a structural ceiling for this population.

## The six information types named in the brief

| Brief type | Our claim family | Coverage |
|---|---|---:|
| company details | `identity.*`, `identity_live` | 100% |
| people | `people.role.*` | 99% |
| locations | `locations.subunit.*` | 70% |
| financial results | `financials.*` | 98% |
| jobs | `jobs.posting`, `jobs.has_postings` | 9% |
| public activity | `activity.*` | 99% |

Jobs and locations are structural limits of the population, not coverage
gaps in the agent. Every eligible company has an Enhetsregisteret row and
a latest submitted annual-account year; not every eligible company has
sub-units or schema.org JobPosting on its site.

## Evidence model

Every claim carries `evidence_ids`. Each evidence record has:

- `source_url` — the exact URL that was fetched
- `source_class` — `official_registry_live`, `official_annual_accounts`,
  `official_roles`, `official_subunits`, `official_group_structure`,
  `official_rule_interpretation`, `registry_linked_company_website`
- `retrieved_at` — ISO-8601 UTC timestamp
- `content_sha256` — the SHA-256 of the raw response body
- `note` — the source's own status message (`HTTP 404`, `URLError: ...`)

A claim with `availability: available` and no `evidence_ids` is never
emitted. Where the fetch fails, the availability is `failed` or `blocked`,
never `available`.

## Envelope shape

Top-level keys per envelope:

    run_id, organisation_number, state, started_at, completed_at,
    modules{}, claims[], evidence[], changes[], summary, profile

`modules{}` records one terminal state per fetched module from the set:

    complete, not_applicable, not_found, blocked_policy, blocked_robots,
    source_error, budget_exhausted, submission_error

`claims[]` is the flat list of facts. Each claim carries:

    field, value, availability, confidence, evidence_ids, note

`evidence[]` is the flat list of sources. Each record carries:

    id, source_url, source_class, retrieved_at, content_sha256, note

`changes[]` is the derived change signals. Each entry carries:

    field, value, note, source_url, retrieved_at, source_class

`summary` is a plain-text narrative answering three questions with sources:

- What the company does — identity, industry, address, employees
- What changed — recent role changes, latest account year, registration dates
- What remains unknown — every module that returned `not_found`,
  `source_error`, or `blocked`, with the URL that was checked

`profile` is the raw evidence blocks as fetched by the batch runner.

## Models, APIs, licences

- **Models:** none in the default pipeline. Deterministic Python. An opt-in LLM synthesis step exists behind SIGNALPOST_LLM=1 and is not used for scoring.
- **Registry snapshot:** optional `SIGNALPOST_REGISTRY_SNAPSHOT` (CSV or CSV.GZ) used for identity anchoring when supplied.

- **Profile sections:** Overview, Financials, Leadership, Locations, Hiring, Activity, Changes.

- **External APIs:** Brreg Enhetsregisteret and Regnskapsregisteret (public,
  no key, no cost). NAV Arbeidsplassen is queried by default in the citation pass; pass `--skip-nav` to disable
  because its token endpoint is unreliable from some networks.
- **Python dependencies:** see `pyproject.toml`. All MIT, BSD, Apache-2.0,
  or PSF-licensed.
- **Expected cost per official run:** $0.00.

## Dead ends — evaluated and rejected

1. **NAV Arbeidsplassen jobs feed.** `pam-stilling-feed.nav.no` token
   endpoint times out from our network in under 15 seconds. Alternative
   paths return HTTP 404. Kept in the repository (`fetch_nav_postings.py`)
   for completeness, disabled by default.
2. **Google News RSS as a public-activity source.** Discovery-only. The
   connector's own report marks observations as `rights_review_required`
   and does not snapshot article bodies. Wired in, it would add
   unverifiable claims without adding verifiable recall.
3. **HTML anchor extraction for careers pages.** Tested. Career pages are
   rarely in the top-4 priority links the crawler visits, so the extractor
   ran on almost no pages. Yield 0/5. Reverted.
4. **External connectors** (`run_linkedin_guest_*.py`, `run_tinyfish_*.py`,
   `run_brave_discovery.py`, `run_email_domain_discovery.py`). Kept in the
   repository as experiments. None is in the default pipeline.

## Tested

- Fresh clone on a clean machine: `git clone`, `uv sync`, `run.py`,
  citation pass — all three stages completed, 3/3 emitted, validation passed.
- Scale: 100 companies, 32 workers, 157 seconds, 100/100 emitted.
- Evidence audit: 5/5 random `financials.*` claims traced from claim ID to
  evidence record to on-disk snapshot to a matching sha256.
- Viewer: `index.html` renders the 1,000-company table and individual
  company pages.

## Contact

Sanjan M — msanjan9980@gmail.com
## Jobs coverage at 1,000-company scale

Across a 1,000-company run, zero companies emitted a schema.org
JobPosting block. The `jobs.has_postings` claim was emitted 90 times,
always with `value: false` ? an explicit "checked, found none" for
companies with an available website. The other 910 companies have no
website on file, so the jobs check is not applicable.

`jobs.posting` (individual posting) is therefore unused at this scale,
but the code path is exercised and the claim type is populated the
moment a company publishes the structured markup.

The NAV connector exists (`fetch_nav_postings.py`) but its token
endpoint is unreachable from our network; `--skip-nav` is default. It
emits `jobs.has_active_postings: not_available` for every company so
the family is never silently missing.


## Viewer

`index.html` and `compare.html` are static HTML built from
`out/cited-envelopes.jsonl`. No framework, no build step. Open either
file from disk or serve the repo root.

- **Find** ? search by name, orgnr, municipality, or industry. Press `/`
  to focus, Esc to clear. Sort by name or by claim / evidence count.
  Filter chips for every claim family.
- **Compare** ? select two or more rows to open a side-by-side table at
  `compare.html`. Rows where every company has the same value are shown
  in grey; rows that differ are highlighted.
- **Verify** ? every claim links to its evidence record. The evidence
  table lists the snapshot path, the live source URL, the retrieval
  timestamp and the full SHA-256. A copy button puts the hash on the
  clipboard.
- **Mobile** ? the index table collapses to cards below 700px. The
  compare bar reflows to full width. Tested at 375px.

## Claim schema

Every published claim carries:

- `field`: dotted public field name
- `value`: the reported value
- `availability`: one of `available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, `failed`
- `confidence`: extraction confidence in [0, 1]
- `evidence_ids`: list of evidence IDs backing the claim
- `claim_span`: pointer into the snapshot (JSON key, table cell, or short substring) proving where the value came from
- `extraction_method`: short label for how the value was extracted (e.g. `official_registry`, `financial_mapping`, `module_fallback`, `nav:posting`)

## Installation & Usage

**1. Install dependencies**
Preferred (uses uv.lock for exact reproducibility):
`uv sync`

Fallback (if uv is not installed):
`pip install -r requirements.txt`

**2. Run the agent**
`python run.py <organisations-file>`
