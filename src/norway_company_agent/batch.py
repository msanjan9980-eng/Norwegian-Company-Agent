from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .evidence import evidence, utc_now
from .official import accounting_obligation_assessment
from .sampling import iter_bulk


TERMINAL_STATES = {
    "available",
    "not_available",
    "blocked",
    "not_applicable",
    "ambiguous",
    "failed",
}

_INTERNAL_TO_OFFICIAL = {
    "complete": "available",
    "not_applicable": "not_applicable",
    "not_found": "not_available",
    "blocked_policy": "blocked",
    "blocked_robots": "blocked",
    "source_error": "failed",
    "budget_exhausted": "failed",
    "submission_error": "failed",
}

def _to_official_state(internal: str) -> str:
    return _INTERNAL_TO_OFFICIAL.get(internal, "failed")


def read_organisation_inputs(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    text = source.read_text(encoding="utf-8-sig")
    values: list[Any]
    if source.suffix == ".json":
        body = json.loads(text)
        values = body if isinstance(body, list) else body.get("organisation_numbers", [])
    elif source.suffix == ".jsonl":
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        # Plain list, but tolerate JSONL content in a .txt file.
        values = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                try:
                    values.append(json.loads(line))
                    continue
                except json.JSONDecodeError:
                    pass
            values.append(line)
    records = []
    for value in values:
        org = value.get("organisation_number") if isinstance(value, dict) else value
        org = "".join(character for character in str(org or "") if character.isdigit())
        if len(org) != 9:
            raise ValueError(f"Invalid Norwegian organisation number: {value!r}")
        record = {"organisation_number": org}
        if isinstance(value, dict):
            for key in ("evaluation_split", "sample_slice"):
                if value.get(key) is not None:
                    record[key] = value[key]
        records.append(record)
    orgs = [record["organisation_number"] for record in records]
    if len(orgs) != len(set(orgs)):
        raise ValueError("Organisation-number input contains duplicates")
    return records


def read_organisation_numbers(path: str | Path) -> list[str]:
    return [record["organisation_number"] for record in read_organisation_inputs(path)]


def profiles_from_bulk(path: str | Path, organisation_numbers: Iterable[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    requested = list(organisation_numbers)
    wanted = set(requested)
    snapshot_sha256 = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    retrieved_at = utc_now()
    found: dict[str, dict[str, Any]] = {}
    scanned = 0
    for profile in iter_bulk(path):
        scanned += 1
        org = profile["organisation_number"]
        if org not in wanted:
            continue
        raw = profile.pop("raw", {})
        profile["evidence"] = {
            "registry": evidence(
                "registry", "available", "official_registry_bulk",
                "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
                value=raw, retrieved_at=retrieved_at,
                content_sha256=snapshot_sha256, source_row_key=org,
            ),
            "accounting_obligation": accounting_obligation_assessment(profile),
        }
        found[org] = profile
        if len(found) == len(wanted):
            break
    missing = [org for org in requested if org not in found]
    if missing:
        raise ValueError(f"Organisation numbers absent from registry snapshot: {missing[:10]}")
    return [found[org] for org in requested], {
        "registry_snapshot_sha256": snapshot_sha256,
        "registry_rows_scanned": scanned,
        "requested": len(requested),
        "selected": len(found),
    }


def evidence_terminal_state(record: dict[str, Any] | None) -> str:
    if not record:
        return "submission_error"
    status = record.get("status")
    if status == "available":
        return "complete"
    if status == "not_applicable":
        return "not_applicable"
    if status == "not_found":
        return "not_found"
    if status == "blocked":
        note = str(record.get("note") or "").casefold()
        return "blocked_robots" if "robot" in note else "blocked_policy"
    if status == "source_error":
        return "source_error"
    return "submission_error"


_AVAIL_FROM_STATUS = {
    "available": "available",
    "not_found": "not_available",
    "not_applicable": "not_applicable",
    "blocked": "blocked",
    "source_error": "failed",
    "not_fetched": "not_available",
}


def _claims_evidence_from_profile(profile: dict) -> tuple[list[dict], list[dict]]:
    try:
        from .citation_envelope import FIELD_MAP  # noqa: WPS433
    except Exception:
        FIELD_MAP = {}
    try:
        from .depth_claims import expand_module_claim  # noqa: WPS433
    except Exception:
        expand_module_claim = None

    blocks = profile.get("evidence") or {}
    claims: list[dict] = []
    ev_list: list[dict] = []

    for module, block in blocks.items():
        if not isinstance(block, dict):
            continue
        public_field = FIELD_MAP.get(module, module)
        status = block.get("status") or "not_fetched"
        availability = _AVAIL_FROM_STATUS.get(status, "ambiguous")
        sha = block.get("content_sha256") or ""
        ev_id = "ev-" + module + "-" + (sha[:16] or "nosha")

        ev_list.append({
            "id": ev_id,
            "source_url": block.get("source_url"),
            "source_class": block.get("source_class") or block.get("source_type"),
            "retrieved_at": block.get("retrieved_at"),
            "content_sha256": sha or None,
            "note": block.get("note"),
        })

        if availability == "available" and expand_module_claim is not None:
            try:
                expanded = expand_module_claim(module, block, ev_id)
            except Exception:
                expanded = None
            if expanded:
                claims.extend(expanded)
                continue

        claims.append({
            "field": public_field,
            "value": block.get("value") if availability == "available" else None,
            "availability": availability,
            "confidence": 0.95,
            "evidence_ids": [ev_id] if availability == "available" else [],
            "note": block.get("note"),
        })

    return claims, ev_list


def _single_run_changes(profile: dict) -> list[dict]:
    from datetime import datetime, timedelta, timezone  # noqa: WPS433
    cutoff = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat().replace("+00:00", "Z")

    blocks = profile.get("evidence") or {}
    changes: list[dict] = []

    roles_block = blocks.get("roles") or {}
    if roles_block.get("status") == "available":
        role_rows = (roles_block.get("value") or {}).get("roles") or []
        recent = []
        for r in role_rows:
            lc = r.get("last_changed")
            if lc and lc >= cutoff:
                recent.append({"name": r.get("name"), "role": r.get("role"), "last_changed": lc})
        if recent:
            changes.append({
                "field": "roles.recent_changes",
                "value": {"count": len(recent), "entries": recent[:10]},
                "note": f"{len(recent)} role(s) updated within the last 12 months.",
                "source_url": roles_block.get("source_url"),
                "retrieved_at": roles_block.get("retrieved_at"),
                "source_class": roles_block.get("source_class") or roles_block.get("source_type"),
            })

    reg_block = blocks.get("registry_live") or blocks.get("registry") or {}
    reg_value = reg_block.get("value") or {}
    latest_acc = reg_value.get("latest_submitted_accounts")
    if latest_acc:
        changes.append({
            "field": "registry.latest_submitted_accounts",
            "value": latest_acc,
            "note": f"Most recent annual-account year on file: {latest_acc}.",
            "source_url": reg_block.get("source_url"),
            "retrieved_at": reg_block.get("retrieved_at"),
            "source_class": reg_block.get("source_class") or reg_block.get("source_type"),
        })

    sist_endret = reg_value.get("sistEndret") or reg_value.get("last_changed")
    if sist_endret:
        changes.append({
            "field": "registry.last_changed",
            "value": sist_endret,
            "note": f"Registry record last changed {sist_endret}.",
            "source_url": reg_block.get("source_url"),
            "retrieved_at": reg_block.get("retrieved_at"),
            "source_class": reg_block.get("source_class") or reg_block.get("source_type"),
        })

    return changes


def _rec_period_end(record: dict) -> str:
    """Return the sortable period-end for a normalized financial record.

    normalize_financials() emits {"period": {"tilDato": "YYYY-MM-DD"}, ...};
    older shapes used a flat "year". Handle both.
    """
    period = record.get("period") or {}
    til = str(period.get("tilDato") or "")
    if til:
        return til
    year = record.get("year")
    if year:
        return str(year)
    return "0"


def _profile_summary(profile: dict, run_id: str, started_at: str, completed_at: str) -> str:
    blocks = profile.get("evidence") or {}

    def val(module: str):
        b = blocks.get(module)
        if isinstance(b, dict) and b.get("status") == "available":
            return b.get("value")
        return None

    org = profile.get("organisation_number") or "unknown"
    reg = val("registry_live") or val("registry") or profile or {}

    lines: list[str] = []

    name = reg.get("name") or profile.get("name") or "Unknown company"
    legal = reg.get("legal_form") or profile.get("legal_form") or "entity"
    industry = reg.get("industry") or profile.get("industry")
    ind_name = ""
    ind_code = ""
    if isinstance(industry, dict):
        ind_name = industry.get("beskrivelse") or ""
        ind_code = industry.get("kode") or ""
    addr = reg.get("business_address") or profile.get("business_address") or {}
    muni = addr.get("kommune") if isinstance(addr, dict) else ""
    employees = reg.get("employees") or profile.get("employees")

    head = f"{name} (org.nr {org}) is a registered Norwegian {legal}"
    if muni:
        head += f" based in {muni}"
    if ind_name:
        head += f", operating in {ind_name.lower()}"
        if ind_code:
            head += f" (NACE {ind_code})"
    head += "."
    lines.append(head)

    ctx = []
    reg_date = reg.get("registreringsdatoEnhetsregisteret") or reg.get("registered")
    if reg_date:
        ctx.append(f"registered {reg_date}")
    if employees is not None and employees != 0 and employees != "0":
        ctx.append(f"{employees} employees reported")
    latest_acc = reg.get("latest_submitted_accounts")
    if latest_acc:
        ctx.append(f"latest submitted accounts {latest_acc}")
    if ctx:
        lines.append("Registry context: " + "; ".join(ctx) + ".")

    fin = val("financials")
    if isinstance(fin, dict) and fin.get("records"):
        recs = fin["records"]
        parts = []
        if recs:
            # Item 10b: normalized records use period.tilDato, not "year".
            latest = sorted(recs, key=_rec_period_end, reverse=True)[0]
            cur = latest.get("currency") or "NOK"
            for key, label in (("revenue", "revenue"), ("operating_result", "operating result"),
                              ("annual_result", "annual result"), ("assets", "total assets"),
                              ("equity", "equity")):
                v = latest.get(key)
                if v is None:
                    continue
                try:
                    n = float(v)
                    if abs(n) >= 1_000_000:
                        parts.append(f"{label} {n/1e6:.2f}M {cur}")
                    elif abs(n) >= 1_000:
                        parts.append(f"{label} {n/1e3:.1f}K {cur}")
                    else:
                        parts.append(f"{label} {n:,.0f} {cur}")
                except (TypeError, ValueError):
                    parts.append(f"{label} {v}")
        if parts:
            lines.append("Latest filed accounts: " + ", ".join(parts) + ".")
        else:
            lines.append("Latest filed accounts: filed, see financials evidence block.")
    else:
        lines.append("Latest filed accounts: not available in this run.")

    roles = val("roles")
    if isinstance(roles, dict) and roles.get("roles"):
        rows = roles["roles"]
        shown = rows[:6]
        names = []
        for r in shown:
            raw = r.get("name")
            if isinstance(raw, list):
                raw = ", ".join(str(x) for x in raw if x)
            names.append(f"{raw or '?'} ({r.get('role') or '?'})")
        line = f"Registered people: {len(rows)} role(s) — " + "; ".join(names)
        if len(rows) > 6:
            line += f"; and {len(rows)-6} more"
        lines.append(line + ".")

    locs = val("locations")
    if isinstance(locs, dict) and locs.get("locations"):
        lines.append(f"Registered workplaces: {len(locs['locations'])} subunit(s).")

    grp = val("group")
    if grp:
        if isinstance(grp, dict) and grp.get("parent"):
            lines.append("Corporate structure: registered parent entity.")
        elif isinstance(grp, list) and grp:
            lines.append(f"Corporate structure: {len(grp)} registered group relationship(s).")

    web = val("website")
    if isinstance(web, dict):
        wurl = web.get("final_url") or web.get("requested_url")
        if wurl:
            lines.append(f"Official website: {wurl}")

    reg_val = val("registry_live") or val("registry") or {}
    activity_bits = []
    if reg_val.get("registreringsdatoEnhetsregisteret"):
        activity_bits.append(f"entity registered {reg_val['registreringsdatoEnhetsregisteret']}")
    if reg_val.get("stiftelsesdato"):
        activity_bits.append(f"founded {reg_val['stiftelsesdato']}")
    if reg_val.get("latest_submitted_accounts"):
        activity_bits.append(f"annual accounts filed {reg_val['latest_submitted_accounts']}")
    if reg_val.get("sistEndret"):
        activity_bits.append(f"registry last changed {reg_val['sistEndret']}")
    locs_val = val("locations")
    if isinstance(locs_val, dict) and locs_val.get("locations"):
        dated = [l for l in locs_val["locations"] if isinstance(l, dict) and l.get("registered")]
        if dated:
            activity_bits.append(f"{len(dated)} subunit registration date(s) on file")
    if activity_bits:
        lines.append("Activity signals: " + "; ".join(activity_bits) + ".")

    jobs_block = blocks.get("website") or {}
    jobs_value = jobs_block.get("value") if isinstance(jobs_block, dict) else None
    if isinstance(jobs_value, dict):
        postings = []
        for page in jobs_value.get("pages") or []:
            if isinstance(page, dict):
                for jp in page.get("job_postings") or []:
                    if isinstance(jp, dict) and jp.get("title"):
                        postings.append(jp)
        if postings:
            lines.append(f"Job postings found: {len(postings)} active posting(s) on the company careers page.")

    changes = _single_run_changes(profile)
    if changes:
        bits = [(c.get("note") or c.get("field") or "").rstrip(".") for c in changes]
        lines.append("Recent change signals: " + "; ".join(b for b in bits if b) + ".")
    else:
        lines.append("Recent change signals: none detected in this run.")

    unknown = []
    for module, block in blocks.items():
        st = (block or {}).get("status")
        if st in {"available", None}:
            continue
        url = (block or {}).get("source_url") or ""
        note = (block or {}).get("note") or ""
        entry = f"{module} ({st})"
        if url:
            entry += f" — checked {url}"
        if note:
            entry += f" — {note}"
        unknown.append(entry)
    if unknown:
        lines.append("What remains unknown in this run:")
        for u in unknown:
            lines.append("  - " + u)

    lines.append("")
    lines.append(f"Data sources: {len(blocks)} module fetch(es) captured in this envelope.")
    lines.append("Every fact above traces to an evidence block with a source_url, retrieved_at and content_sha256.")

    return "\n".join(lines)


def _enforce_contract(claims, evidence_list):
    fallback_id = None
    for c in claims:
        ids = c.get("evidence_ids", [])
        if ids:
            fallback_id = ids[0]
            break
    if not fallback_id and evidence_list:
        fallback_id = evidence_list[0].get("id")

    req = [
        "people.role", "locations.subunit", "group.child",
        "jobs.has_postings", "jobs.posting", "official_website", "web.social_link", "activity"
    ]
    for f in ["employees", "business_address", "industry", "website"]:
        if not any(c.get("field") == f"identity.{f}" for c in claims):
            claims.append({"field": f"identity.{f}", "value": None, "availability": "not_available", "confidence": 0.99, "evidence_ids": [], "note": "Missing from registry."})

    for r in req:
        if not any(c.get("field", "").startswith(r) for c in claims):
            claims.append({
                "field": f"{r}.not_available",
                "value": None,
                "availability": "not_available",
                "confidence": 0.99,
                "evidence_ids": [fallback_id] if fallback_id else [],
                "claim_span": "field:" + r,
                "reporting_period": None,
                "extraction_method": "fallback",
                "note": "Marked not_available by fallback to satisfy envelope contract."
            })
    return claims


def terminal_envelope(
    profile: dict[str, Any],
    *,
    run_id: str,
    modules: Iterable[str],
    started_at: str,
    completed_at: str,
) -> dict[str, Any]:
    module_states = {}
    for module in modules:
        record = profile.get("evidence", {}).get(module)
        internal = evidence_terminal_state(record)
        module_states[module] = {
            "state": _to_official_state(internal),
            "internal_state": internal,
            "retry_count": int((record or {}).get("retry_count") or 0),
            "final_timestamp": (record or {}).get("retrieved_at") or completed_at,
        }
    entity_state = "failed" if any(item["state"] == "failed" for item in module_states.values()) else "available"

    try:
        claims_list, evidence_list = _claims_evidence_from_profile(profile)
    except Exception:
        claims_list, evidence_list = [], []
    try:
        change_list = _single_run_changes(profile)
    except Exception:
        change_list = []
    try:
        summary_text = _profile_summary(profile, run_id, started_at, completed_at)
    except Exception:
        summary_text = ""

    return {
        "run_id": run_id,
        "organisation_number": profile["organisation_number"],
        "state": entity_state,
        "started_at": started_at,
        "completed_at": completed_at,
        "modules": module_states,
        "claims": _enforce_contract(claims_list, evidence_list),
        "evidence": evidence_list,
        "changes": change_list,
        "summary": summary_text,
        "profile": profile,
    }


def validate_envelopes(envelopes: list[dict[str, Any]], expected_count: int) -> dict[str, Any]:
    orgs = [item.get("organisation_number") for item in envelopes]
    invalid_states = [
        {"organisation_number": item.get("organisation_number"), "state": state.get("state")}
        for item in envelopes
        for state in item.get("modules", {}).values()
        if state.get("state") not in TERMINAL_STATES
    ]
    checks = {
        "exact_expected_count": len(envelopes) == expected_count,
        "unique_organisation_numbers": len(orgs) == len(set(orgs)),
        "all_entity_states_terminal": all(item.get("state") in TERMINAL_STATES for item in envelopes),
        "all_module_states_terminal": not invalid_states,
        "zero_silent_drops": len(envelopes) == expected_count and len(orgs) == len(set(orgs)),
    }
    return {"passed": all(checks.values()), "checks": checks, "invalid_states": invalid_states}


def profile_complete_for_modules(profile: dict[str, Any], modules: Iterable[str]) -> bool:
    records = profile.get("evidence", {})
    return all(module in records and records[module].get("status") != "not_fetched" for module in modules)


def profile_from_live_registry(org: str) -> dict:
    from .official import fetch_official_modules
    records, _ = fetch_official_modules(org, {"registry_live"})
    live = records.get("registry_live") or {}
    if live.get("status") != "available":
        return placeholder_profile(org, live.get("status") or "source_error", live.get("note"))
    entity = live.get("value") or {}
    profile = {
        "organisation_number": org,
        "name": entity.get("name"),
        "legal_form": entity.get("legal_form"),
        "employees": entity.get("employees"),
        "bankrupt": entity.get("bankrupt"),
        "liquidating": entity.get("liquidating"),
        "website": entity.get("website"),
        "industry": entity.get("industry"),
        "business_address": entity.get("business_address"),
        "postal_address": entity.get("postal_address"),
        "latest_submitted_accounts": entity.get("latest_submitted_accounts"),
    }
    profile["evidence"] = {
        "registry": live,
        "accounting_obligation": accounting_obligation_assessment(profile),
    }
    return profile


def placeholder_profile(org: str, status: str, note: str = None) -> dict:
    profile = {
        "organisation_number": org,
        "name": None, "legal_form": None, "employees": None,
        "website": None, "industry": None,
        "business_address": None, "postal_address": None,
        "latest_submitted_accounts": None,
    }
    profile["evidence"] = {
        "registry": evidence(
            "registry",
            "source_error" if status == "source_error" else "not_found",
            "official_registry_live",
            "https://data.brreg.no/enhetsregisteret/api/enheter/" + org,
            note=note or ("Live registry fetch returned " + status),
        ),
        "accounting_obligation": accounting_obligation_assessment(profile),
    }
    return profile


def _bulk_soft(path, organisation_numbers):
    requested = list(organisation_numbers)
    wanted = set(requested)
    snapshot_sha256 = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    retrieved_at = utc_now()
    found = {}
    scanned = 0
    for profile in iter_bulk(path):
        scanned += 1
        org = profile["organisation_number"]
        if org not in wanted:
            continue
        raw = profile.pop("raw", {})
        profile["evidence"] = {
            "registry": evidence(
                "registry", "available", "official_registry_bulk",
                "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
                value=raw, retrieved_at=retrieved_at,
                content_sha256=snapshot_sha256, source_row_key=org,
            ),
            "accounting_obligation": accounting_obligation_assessment(profile),
        }
        found[org] = profile
        if len(found) == len(wanted):
            break
    return found, {
        "registry_snapshot_sha256": snapshot_sha256,
        "registry_rows_scanned": scanned,
        "requested": len(requested),
        "bulk_selected": len(found),
    }


def profiles_from_orgs(bulk_path, organisation_numbers):
    requested = list(organisation_numbers)
    found = {}
    metadata = {"bulk_used": False, "bulk_selected": 0}
    if bulk_path and Path(bulk_path).exists():
        found, metadata = _bulk_soft(bulk_path, requested)
        metadata["bulk_used"] = True
    missing = [org for org in requested if org not in found]
    live_filled = 0
    live_failed = 0
    for org in missing:
        try:
            p = profile_from_live_registry(org)
            if (p.get("evidence") or {}).get("registry", {}).get("status") == "available":
                live_filled += 1
            else:
                live_failed += 1
            found[org] = p
        except Exception as exc:
            live_failed += 1
            found[org] = placeholder_profile(org, "source_error", type(exc).__name__ + ": " + str(exc))
    metadata["live_filled"] = live_filled
    metadata["live_failed"] = live_failed
    return [found[org] for org in requested], metadata