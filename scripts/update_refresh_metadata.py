"""Diff current envelopes against the previous state and record changes.

Item 12: compares the union of previous+current fields so that added and
removed fields are recorded, and uses the previous evidence records (not
the claims) to derive first_observed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone


def classify_change(field, old_avail, new_avail):
    if old_avail is None:
        if field.startswith("people.role"): return "new_role"
        if field.startswith("locations.subunit"): return "new_location"
        if field.startswith("financials"): return "new_filing"
        if field.startswith("jobs.posting"): return "new_job"
        if field.startswith("activity"): return "new_activity"
        return "new_field"
    if new_avail is None:
        return "removed_field"
    if old_avail == "not_available" and new_avail == "available":
        if field.startswith("people.role"): return "new_role"
        if field.startswith("locations.subunit"): return "new_location"
        if field.startswith("financials"): return "new_filing"
        if field.startswith("jobs.posting"): return "new_job"
        if field.startswith("activity"): return "new_activity"
        return "new_field"
    if old_avail == "available" and new_avail == "not_available":
        if field.startswith("jobs.has_postings"): return "closed_job"
        return "removed_field"
    return "changed_value"


def _first_observed(previous_env: dict, evidence_ids: list[str]) -> str:
    evidence_by_id = {e.get("id"): e for e in (previous_env.get("evidence") or [])}
    for eid in evidence_ids or []:
        ev = evidence_by_id.get(eid)
        if ev and ev.get("retrieved_at"):
            return ev["retrieved_at"]
    return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="out/envelopes.jsonl")
    ap.add_argument("--output", default=None,
                    help="Where to write merged envelopes. If omitted, overwrite --input.")
    ap.add_argument("--state", default="out/state/previous_envelopes.jsonl")
    args = ap.parse_args()

    input_file = Path(args.input)
    output_file = Path(args.output) if args.output else input_file
    state_file = Path(args.state)

    if not input_file.exists():
        print("No envelopes to process.")
        return

    prev = {}
    if state_file.exists():
        with open(state_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    env = json.loads(line)
                    prev[env["organisation_number"]] = env

    new_envs = []
    with open(input_file, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            env = json.loads(line)
            org = env["organisation_number"]
            prev_env = prev.get(org) or {}
            prev_claims = {c["field"]: c for c in prev_env.get("claims", []) if c.get("field")}
            current_claims = {c["field"]: c for c in env.get("claims", []) if c.get("field")}

            changes = []
            for field_name in sorted(set(prev_claims) | set(current_claims)):
                old_c = prev_claims.get(field_name)
                new_c = current_claims.get(field_name)
                old_value = old_c.get("value") if old_c else None
                new_value = new_c.get("value") if new_c else None
                old_avail = old_c.get("availability") if old_c else None
                new_avail = new_c.get("availability") if new_c else None
                if old_value == new_value and old_avail == new_avail:
                    continue
                old_ev_ids = (old_c or {}).get("evidence_ids") or []
                new_ev_ids = (new_c or {}).get("evidence_ids") or []
                now = datetime.now(timezone.utc).isoformat()
                changes.append({
                    "field": field_name,
                    "old_value": old_value,
                    "new_value": new_value,
                    "old_availability": old_avail,
                    "new_availability": new_avail,
                    "changed_at": now,
                    "first_observed": _first_observed(prev_env, old_ev_ids) if old_c else now,
                    "last_observed": now,
                    "change_type": classify_change(field_name, old_avail, new_avail),
                    "materiality": "material" if field_name.startswith(("identity", "financials", "people")) else "cosmetic",
                    "sources_supporting_old": old_ev_ids,
                    "sources_supporting_new": new_ev_ids,
                })

            env["changes"] = changes
            new_envs.append(env)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        for env in new_envs:
            f.write(json.dumps(env) + "\n")

    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        for env in new_envs:
            f.write(json.dumps(env) + "\n")

    print(f"Updated refresh metadata for {len(new_envs)} envelopes.")


if __name__ == "__main__":
    main()