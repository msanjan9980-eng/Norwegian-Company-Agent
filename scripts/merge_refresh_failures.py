#!/usr/bin/env python3
"""Preserve last known supported values when a refresh source fails."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

CURRENT = Path("out/cited-envelopes.jsonl")
PREVIOUS = Path("out/state/previous_envelopes.jsonl")


def load_jsonl(path: Path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def by_org(envs):
    out = {}
    for env in envs:
        org = str(env.get("organisation_number") or "")
        if org:
            out[org] = env
    return out


def claim_map(env):
    out = {}
    for c in env.get("claims", []) or []:
        f = c.get("field")
        if f:
            out[f] = c
    return out


def main():
    current = load_jsonl(CURRENT)
    previous = by_org(load_jsonl(PREVIOUS))
    if not current or not previous:
        print("No current or previous envelopes; nothing to merge.")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    merged_total = 0

    for env in current:
        org = str(env.get("organisation_number") or "")
        prev = previous.get(org)
        if not prev:
            continue

        prev_claims = claim_map(prev)
        merged_here = 0
        new_claims = []

        for c in env.get("claims", []) or []:
            field = c.get("field")
            pc = prev_claims.get(field)
            if (
                pc
                and pc.get("availability") == "available"
                and c.get("availability") in ("failed", "not_available")
            ):
                c = dict(pc)
                c["note"] = (c.get("note") or "") + " [refresh failed; last known supported value retained]"
                c["refresh_error"] = "source failed in this run"
                c["refresh_checked_at"] = now
                merged_here += 1
            new_claims.append(c)

        if merged_here:
            env["claims"] = new_claims
            env["refresh_merge"] = {
                "merged_claims": merged_here,
                "checked_at": now,
            }
            merged_total += merged_here

    CURRENT.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False, default=str) for e in current) + "\n",
        encoding="utf-8",
    )
    print(f"Merged {merged_total} last-known claims into {CURRENT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())