#!/usr/bin/env python3
"""Signalpost entry - one command to run.

import shutil
Usage:
    python run.py <organisations-file> [expected-count]

Works identically on Linux, macOS, and Windows. No POSIX shell required.

Environment:
    SIGNALPOST_REGISTRY_SNAPSHOT  Optional path to a frozen Brreg CSV snapshot
                                  (.csv or .csv.gz) for identity anchoring.
    SIGNALPOST_LLM=1              Opt-in to optional LLM synthesis. Default off.
"""
from __future__ import annotations

import os
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _count_inputs(path: str) -> int:
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"Input file not found: {path}")
    if p.suffix == ".json":
        body = json.loads(p.read_text(encoding="utf-8-sig"))
        return len(body) if isinstance(body, list) else len(body.get("organisation_numbers", []))
    return sum(1 for line in p.read_text(encoding="utf-8-sig").splitlines() if line.strip())


def _run(step: str, argv: list[str], env: dict, *, optional: bool = False) -> int:
    print(step, file=sys.stderr)
    rc = subprocess.run(argv, env=env).returncode
    if rc != 0:
        tag = "Optional step failed" if optional else "Step failed"
        print(f"{tag}: {step} (exit {rc})", file=sys.stderr)
    return rc


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    orgs = sys.argv[1]
    root = Path(__file__).resolve().parent
    os.chdir(root)

    derived = _count_inputs(orgs)
    if len(sys.argv) > 2:
        supplied = int(sys.argv[2])
        if supplied != derived:
            print(f"Note: --expected-count {supplied} differs from file count {derived}; using file count.",
                  file=sys.stderr)
    count = derived

    env = os.environ.copy()
    timeout_s = int(os.environ.get("SIGNALPOST_TIMEOUT_S", "0") or 0)
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    snapshot  = env.get("SIGNALPOST_REGISTRY_SNAPSHOT", "").strip()
    enable_llm = env.get("SIGNALPOST_LLM", "0").strip() == "1"
    run_id = "official-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    import socket
    try:
        socket.create_connection(("data.brreg.no", 443), timeout=5).close()
    except OSError as exc:
        print(f"Pre-flight failed: cannot reach data.brreg.no: {exc}", file=sys.stderr)
        return 3

    import shutil
    if shutil.which("uv"):
        rc = _run("[1/9] uv sync", ["uv", "sync"], env)
    else:
        print("[1/9] uv not found. Falling back to pip install -r requirements.txt", file=sys.stderr)
        rc = _run("[1/9] pip install", [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], env)
        
    if rc:
        return rc

    snapshot = env.get("SIGNALPOST_REGISTRY_SNAPSHOT", "").strip()
    batch = [
        "uv", "run", "python", "-X", "utf8", "scripts/run_competition_batch.py",
        "--organisations", orgs,
        "--output", "out/envelopes.jsonl",
        "--profiles-output", "out/profiles.jsonl",
        "--report", "out/run-report.json",
        "--run-id", run_id,
        "--expected-count", str(count),
        "--workers", "32",
    ]
    if timeout_s:
        batch += ["--timeout", str(timeout_s)]
    if snapshot:
        batch += ["--bulk", snapshot]
    if snapshot:
        batch.extend(["--bulk", snapshot])
    if _run("[2/9] batch runner", batch, env):
        return 1

    if _run("[3/9] deepen websites",
            ["uv", "run", "python", "-X", "utf8", "scripts/deepen_websites.py",
             "--envelopes", "out/envelopes.jsonl",
             "--output", "out/envelopes.jsonl",
             "--report", "out/deepen-report.json",
             "--workers", "32"], env):
        return 1

    if env.get("BRAVE_SEARCH_API_KEY", "").strip():
        _run("[4/9] brave discovery (optional)",
             ["uv", "run", "python", "-X", "utf8", "scripts/run_brave_discovery.py",
              "--input", "out/envelopes.jsonl",
              "--output", "out/envelopes.jsonl",
              "--report", "out/brave-report.json"], env, optional=True)
    else:
        print("[4/9] brave discovery skipped (BRAVE_SEARCH_API_KEY not set)", file=sys.stderr)

    if _run("[5/9] citation pass",
            ["uv", "run", "python", "-X", "utf8", "scripts/run_citation_pass.py",
             "--envelopes", "out/envelopes.jsonl",
             "--output", "out/cited-envelopes.jsonl",
             "--report", "out/citation-report.json",
             "--run-id", "citation-" + run_id,
             "--workers", "16"], env):
        return 1

    _run("[5.5/9] refresh merge", ["uv", "run", "python", "-X", "utf8", "scripts/merge_refresh_failures.py"], env)
    if _run("[6/9] enforce contract",
            ["uv", "run", "python", "-X", "utf8", "scripts/enforce_contract.py",
             "--input", "out/cited-envelopes.jsonl",
             "--output", "out/cited-envelopes.jsonl"], env):
        return 1

    # Refresh metadata runs AFTER citation/enforce so that its field vocabulary
    # matches the cited envelope (previous design compared against batch-runner
    # claims and mismatched on field names).
    if _run("[7/9] update refresh metadata",
            ["uv", "run", "python", "-X", "utf8", "scripts/update_refresh_metadata.py",
             "--input", "out/cited-envelopes.jsonl",
             "--output", "out/cited-envelopes.jsonl",
             "--state", "out/state/previous_envelopes.jsonl"], env):
        return 1

    if enable_llm:
        _run("[7.5/9] llm synthesis (opt-in)",
             ["uv", "run", "python", "-X", "utf8", "scripts/llm_summary.py"],
             env, optional=True)

    return _run("[9/9] build viewer",
                ["uv", "run", "python", "-X", "utf8", "scripts/build_viewer.py",
                 "--envelopes", "out/cited-envelopes.jsonl",
                 "--out", "."], env)


if __name__ == "__main__":
    raise SystemExit(main())
