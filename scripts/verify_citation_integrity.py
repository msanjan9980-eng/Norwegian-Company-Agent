#!/usr/bin/env python3
"""Verify that every claim's evidence resolves to a captured file whose
SHA-256 matches the recorded digest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def verify_envelope(env: dict, root: Path) -> list[str]:
    problems: list[str] = []
    ids = {e["id"] for e in env.get("evidence") or []}

    for i, c in enumerate(env.get("claims") or []):
        if c.get("availability") != "available":
            continue
        if not c.get("evidence_ids"):
            problems.append(f"claim[{i}] {c.get('field')} available with no evidence")
        for eid in c.get("evidence_ids") or []:
            if eid not in ids:
                problems.append(f"claim[{i}] references missing evidence {eid}")

    for ev in env.get("evidence") or []:
        sp = ev.get("snapshot_path")
        if not sp:
            problems.append(f"evidence {ev.get('id')} has no snapshot_path")
            continue
        p = root / sp
        if not p.is_file():
            problems.append(f"evidence {ev.get('id')} file missing at {sp}")
            continue
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != ev.get("content_sha256"):
            problems.append(f"evidence {ev.get('id')} sha mismatch")

    return problems


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envelopes", default="out/cited-envelopes.jsonl")
    ap.add_argument("--root", default=".")
    ap.add_argument("--sample", type=int, default=0, help="0 = verify all")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    rows = [json.loads(l) for l in Path(args.envelopes).read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.sample:
        rows = rows[:args.sample]

    total_problems = 0
    for env in rows:
        problems = verify_envelope(env, root)
        if problems:
            total_problems += len(problems)
            print(f"[{env.get('organisation_number')}]")
            for p in problems[:5]:
                print(f"  {p}")

    print()
    print(f"Verified {len(rows)} envelopes; {total_problems} problem(s)")


if __name__ == "__main__":
    main()
