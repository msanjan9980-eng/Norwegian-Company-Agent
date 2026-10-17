#!/bin/sh
# Signalpost entry - one command to run
# Usage: sh run.sh <organisations-file> [expected-count]
set -e
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"

ORGS="${1:?usage: sh run.sh <organisations-file> [expected-count]}"
COUNT="${2:-1000}"

uv sync

uv run python scripts/run_competition_batch.py \
  --organisations "$ORGS" \
  --output out/envelopes.jsonl \
  --profiles-output out/profiles.jsonl \
  --report out/run-report.json \
  --run-id "official-$(date +%Y%m%d-%H%M%S)" \
  --expected-count "$COUNT" \
  --workers 32

uv run python scripts/run_citation_pass.py \
  --envelopes out/envelopes.jsonl \
  --output out/cited-envelopes.jsonl \
  --report out/citation-report.json \
  --run-id "citation-official" \
  --workers 16 --skip-nav
