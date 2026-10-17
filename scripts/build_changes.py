#!/usr/bin/env python3
"""Compute per-company changes between two cited-envelope snapshots.

Usage:
    uv run python scripts/build_changes.py \
      --baseline out/cited-envelopes-day1.jsonl \
      --current  out/cited-envelopes-day2.jsonl \
      --output   out/envelopes-with-changes.jsonl \
      --report   out/changes-report.json

Change detection:
  * "added"   — field present in current, absent in baseline
  * "removed" — field present in baseline, absent in current
  * "changed" — field present in both with different value or availability

Every change carries old_value, new_value, and the union of evidence IDs
from both sides so the reviewer can inspect before and after snapshots.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_by_orgnr(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        env = json.loads(line)
        org = env.get("organisation_number")
        if org:
            rows[org] = env
    return rows


def claims_by_field(env: dict) -> dict[str, dict]:
    return {c.get("field"): c for c in (env.get("claims") or []) if c.get("field")}


def diff_company(baseline: dict, current: dict) -> list[dict]:
    b = claims_by_field(baseline)
    c = claims_by_field(current)
    changes: list[dict] = []

    for field in sorted(set(b) | set(c)):
        bc = b.get(field)
        cc = c.get(field)

        if bc is None and cc is not None:
            changes.append({
                "kind": "added",
                "field": field,
                "old_value": None,
                "new_value": cc.get("value"),
                "availability_before": None,
                "availability_after": cc.get("availability"),
                "evidence_ids": cc.get("evidence_ids") or [],
            })
        elif bc is not None and cc is None:
            changes.append({
                "kind": "removed",
                "field": field,
                "old_value": bc.get("value"),
                "new_value": None,
                "availability_before": bc.get("availability"),
                "availability_after": None,
                "evidence_ids": bc.get("evidence_ids") or [],
            })
        else:
            same_value = bc.get("value") == cc.get("value")
            same_state = bc.get("availability") == cc.get("availability")
            if not (same_value and same_state):
                changes.append({
                    "kind": "changed",
                    "field": field,
                    "old_value": bc.get("value"),
                    "new_value": cc.get("value"),
                    "availability_before": bc.get("availability"),
                    "availability_after": cc.get("availability"),
                    "evidence_ids": list({*(cc.get("evidence_ids") or []),
                                           *(bc.get("evidence_ids") or [])}),
                })
    return changes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--current", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    baseline = load_by_orgnr(Path(args.baseline))
    current = load_by_orgnr(Path(args.current))

    # Only companies present in both are diffable; report gaps separately.
    common = sorted(set(baseline) & set(current))
    only_baseline = sorted(set(baseline) - set(current))
    only_current = sorted(set(current) - set(baseline))

    out_rows: list[dict] = []
    total_changes = 0
    companies_with_changes = 0
    change_kind_counts = {"added": 0, "removed": 0, "changed": 0}

    for org in common:
        env = dict(current[org])
        changes = diff_company(baseline[org], current[org])
        env["changes"] = changes
        out_rows.append(env)
        total_changes += len(changes)
        if changes:
            companies_with_changes += 1
            for ch in changes:
                change_kind_counts[ch["kind"]] += 1

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.output).open("w", encoding="utf-8") as fh:
        for row in out_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "baseline_envelopes": len(baseline),
        "current_envelopes": len(current),
        "common_envelopes": len(common),
        "only_in_baseline": only_baseline[:10],
        "only_in_current": only_current[:10],
        "companies_with_changes": companies_with_changes,
        "total_changes": total_changes,
        "change_kind_counts": change_kind_counts,
        "idempotent": total_changes == 0,
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
