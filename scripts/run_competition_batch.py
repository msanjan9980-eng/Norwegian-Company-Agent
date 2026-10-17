#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.batch import (  # noqa: E402
    placeholder_profile,
    profile_complete_for_modules,
    profiles_from_orgs,
    read_organisation_inputs,
    terminal_envelope,
    validate_envelopes,
)
from norway_company_agent.evidence import utc_now, evidence  # noqa: E402
from norway_company_agent.identity import apply_website_identity_gate  # noqa: E402
from norway_company_agent.official import fetch_official_modules  # noqa: E402
from norway_company_agent.website import fetch_website  # noqa: E402


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluator-owned Signalpost batch contract")
    parser.add_argument("--organisations", required=True, help="JSON, JSONL, or text organisation-number list")
    parser.add_argument("--bulk", help="Optional frozen Brreg snapshot. When absent or incomplete, live Brreg API fills the gap.")
    parser.add_argument("--output", required=True, help="Terminal envelope JSONL")
    parser.add_argument("--profiles-output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-count", type=int, default=None,
                        help="Optional exact-count assertion. Derived from input if omitted.")
    parser.add_argument("--timeout", type=int, default=0, help="Global wall-clock budget in seconds")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--modules", default="registry,accounting_obligation,registry_live,financials,roles,group,locations,website")
    args = parser.parse_args()
    started = time.monotonic()

    started_at = utc_now()
    organisation_inputs = read_organisation_inputs(args.organisations)
    orgs = [item["organisation_number"] for item in organisation_inputs]
    expected = args.expected_count if args.expected_count is not None else len(orgs)
    if len(orgs) != expected:
        raise SystemExit(f"Expected {expected} organisations, received {len(orgs)}")

    profiles, registry_metadata = profiles_from_orgs(args.bulk, orgs)
    annotations = {item["organisation_number"]: item for item in organisation_inputs}
    for profile in profiles:
        for key in ("evaluation_split", "sample_slice"):
            if key in annotations[profile["organisation_number"]]:
                profile[key] = annotations[profile["organisation_number"]][key]
    requested_modules = [item.strip() for item in args.modules.split(",") if item.strip()]
    fetch_modules = set(requested_modules) - {"registry", "accounting_obligation", "website", "jobs"}
    operations = {"requests": 0, "bytes": 0, "latencies_ms": []}

    nav_result: dict = {}
    if "jobs" in requested_modules:
        try:
            from norway_company_agent.nav_fetcher import fetch_postings_for_orgnrs
            names_by_orgnr = {p["organisation_number"]: (p.get("name") or "") for p in profiles}
            print(f"Fetching NAV postings for {len(orgs)} orgs (14-day window)...", file=sys.stderr)
            nav_result = fetch_postings_for_orgnrs(orgs, names_by_orgnr, lookback_days=14)
            print(f"NAV: {len(nav_result)} companies with active postings", file=sys.stderr)
        except Exception as exc:
            print(f"NAV fetch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            nav_result = {}

    def enrich(profile: dict) -> tuple[dict, dict]:
        import time as _time
        _t0 = _time.monotonic()

        # Item 14: skip duplicate live-registry fetch when the profile already
        # has a fresh registry record from the bulk/live profile bootstrap.
        per_modules = set(fetch_modules)
        existing_registry = (profile.get("evidence") or {}).get("registry") or {}
        if existing_registry.get("status") == "available":
            per_modules.discard("registry_live")

        records, metrics = fetch_official_modules(profile["organisation_number"], per_modules)
        _t_brreg = _time.monotonic() - _t0
        profile["evidence"].update(records)

        website_metrics = {"requests": 0, "bytes": 0, "latencies_ms": []}
        if "website" in requested_modules:
            website_record, website_metrics = fetch_website(
                profile.get("website"),
                orgnr=profile["organisation_number"],
            )
            profile["evidence"]["website"] = apply_website_identity_gate(profile, website_record)["website"]
        if "jobs" in requested_modules:
            nav = nav_result.get(profile["organisation_number"])
            if nav and nav.get("postings"):
                first_ev = (nav.get("evidence") or [{}])[0]
                profile["evidence"]["jobs"] = evidence(
                    "jobs", "available", "public_job_posting_nav",
                    "https://pam-stilling-feed.nav.no/api/v1/feed",
                    value={"postings": nav["postings"]},
                    content_sha256=first_ev.get("content_sha256"),
                    retrieved_at=first_ev.get("retrieved_at"),
                )
            else:
                profile["evidence"]["jobs"] = evidence(
                    "jobs", "not_found", "public_job_posting_nav",
                    "https://pam-stilling-feed.nav.no/api/v1/feed",
                    note="No active NAV postings in last 14 days",
                )
        metric = {
            "requests": len(metrics) + website_metrics["requests"],
            "bytes": sum(item.bytes_received for item in metrics) + website_metrics["bytes"],
            "latencies_ms": [item.elapsed_ms for item in metrics] + website_metrics["latencies_ms"],
        }
        _t_total = _time.monotonic() - _t0
        metric["brreg_s"] = round(_t_brreg, 2)
        metric["total_s"] = round(_t_total, 2)
        metric["website_s"] = round(_t_total - _t_brreg, 2)
        profile["run_metrics"] = metric
        if _t_total > 5.0:
            print(f"SLOW {profile['organisation_number']}: brreg={_t_brreg:.1f}s website={_t_total-_t_brreg:.1f}s total={_t_total:.1f}s",
                  file=sys.stderr)
        return profile, metric

    def enrich_safe(profile: dict) -> tuple[dict, dict]:
        """Item 2: never let one company kill the whole batch."""
        try:
            return enrich(profile)
        except Exception as exc:
            org = profile["organisation_number"]
            profile.setdefault("evidence", {})["_batch_error"] = evidence(
                "batch_error", "source_error", "batch_runner",
                "local://scripts/run_competition_batch.py",
                note=f"{type(exc).__name__}: {str(exc)[:200]}",
            )
            print(f"Company {org} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return profile, {"requests": 0, "bytes": 0, "latencies_ms": []}

    state: dict[str, dict] = {}
    resumed_profiles = 0
    profiles_output = Path(args.profiles_output)
    if args.resume and profiles_output.exists():
        prior = [json.loads(line) for line in profiles_output.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not set(item["organisation_number"] for item in prior).issubset(set(orgs)):
            raise SystemExit("Resume profile membership is not a subset of this batch")
        state = {
            item["organisation_number"]: item
            for item in prior
            if profile_complete_for_modules(item, requested_modules)
        }
        resumed_profiles = len(state)

    pending_profiles = [profile for profile in profiles if profile["organisation_number"] not in state]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(enrich_safe, profile): profile["organisation_number"] for profile in pending_profiles}
        for index, future in enumerate(as_completed(futures), 1):
            if args.timeout and (time.monotonic() - started) > args.timeout:
                print(f"Timeout {args.timeout}s reached; stopping.", file=sys.stderr)
                break
            org = futures[future]
            try:
                profile, metric = future.result()
            except Exception as exc:
                profile = placeholder_profile(org, "source_error",
                                              f"{type(exc).__name__}: {exc}")
                metric = {"requests": 0, "bytes": 0, "latencies_ms": []}
            state[profile["organisation_number"]] = profile
            operations["requests"] += metric["requests"]
            operations["bytes"] += metric["bytes"]
            operations["latencies_ms"].extend(metric["latencies_ms"])
            if index % args.checkpoint_every == 0 or index == len(pending_profiles):
                checkpoint = [state[o] for o in orgs if o in state]
                write_jsonl(profiles_output, checkpoint)

    completed_at = utc_now()
    ordered_profiles = [state[o] for o in orgs]
    envelopes = [
        terminal_envelope(profile, run_id=args.run_id, modules=requested_modules,
                          started_at=started_at, completed_at=completed_at)
        for profile in ordered_profiles
    ]
    validation = validate_envelopes(envelopes, args.expected_count if args.expected_count is not None else len(orgs))
    write_jsonl(profiles_output, ordered_profiles)
    write_jsonl(Path(args.output), envelopes)
    latencies = sorted(operations.pop("latencies_ms"))
    operations["p50_ms"] = latencies[len(latencies) // 2] if latencies else None
    operations["p95_ms"] = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None
    report = {
        "run_id": args.run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "expected_count": args.expected_count,
        "emitted_envelopes": len(envelopes),
        "resumed_profiles": resumed_profiles,
        "profiles_fetched_this_run": len(pending_profiles),
        "modules": requested_modules,
        "registry": registry_metadata,
        "operations": operations,
        "validation": validation,
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if validation["passed"] else 1)


if __name__ == "__main__":
    main()
