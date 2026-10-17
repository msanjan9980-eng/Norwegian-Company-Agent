"""Build citation-validator-compliant envelopes. Dedupe evidence by SHA-256."""
from __future__ import annotations

from typing import Any

from .depth_claims import expand_module_claim
from .summary import attach_summary

ALLOWED_AVAILABILITY = {
    "available", "not_available", "blocked", "not_applicable", "ambiguous", "failed",
}

FIELD_MAP = {
    "registry": "identity",
    "registry_live": "identity_live",
    "accounting_obligation": "accounting_obligation",
    "financials": "financials",
    "roles": "people",
    "locations": "locations",
    "group": "group_structure",
    "website": "official_website",
}


def _confidence_for(source_class: str) -> float:
    cls = (source_class or "").lower()
    if "official_registry" in cls or "official_roles" in cls:
        return 0.99
    if "official_annual_accounts" in cls or "official_subunits" in cls:
        return 0.97
    if "official_group" in cls or "official_rule" in cls:
        return 0.95
    if "company_owned" in cls or "registry_linked_company_website" in cls:
        return 0.90
    if "web_search" in cls or "email_domain" in cls:
        return 0.85
    return 0.70


_STATUS_TO_AVAILABILITY = {
    "available": "available",
    "not_found": "not_available",
    "source_error": "failed",
    "blocked": "blocked",
    "not_applicable": "not_applicable",
    "not_fetched": "not_available",
}


def _availability_from_status(status: str) -> str:
    mapped = _STATUS_TO_AVAILABILITY.get(status)
    if mapped:
        return mapped
    return status if status in ALLOWED_AVAILABILITY else "ambiguous"


def build_claims_and_evidence(
    internal_evidence: dict[str, dict],
    captured: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    claims: list[dict] = []
    evidence: list[dict] = []
    sha_to_id: dict[str, str] = {}

    for internal_key, block in internal_evidence.items():
        if not isinstance(block, dict):
            continue
        public_field = FIELD_MAP.get(internal_key, internal_key)
        status = block.get("status") or "not_fetched"
        availability = _availability_from_status(status)

        evidence_ids: list[str] = []
        snap = captured.get(internal_key)
        primary_evidence_id: str | None = None
        if snap is not None:
            sha = snap.get("content_sha256") or ""
            if sha and sha in sha_to_id:
                primary_evidence_id = sha_to_id[sha]
            else:
                evidence.append(snap)
                primary_evidence_id = snap["id"]
                if sha:
                    sha_to_id[sha] = snap["id"]
            evidence_ids.append(primary_evidence_id)

        if availability == "available" and not primary_evidence_id:
            availability = "failed"
            block_note = "Evidence fetch failed; claim not published as available."
        else:
            block_note = block.get("note")

        if availability == "available" and internal_key == "website":
            assessment = (block.get("value") or {}).get("identity_assessment") or {}
            if assessment.get("publishable") is False:
                availability = "ambiguous"
                gate_status = str(assessment.get("status") or "unknown")
                block_note = (
                    (block.get("note") or "")
                    + f" [identity gate declined: {gate_status}, score {assessment.get('score')}]"
                )

        if availability == "available" and primary_evidence_id:
            expanded = expand_module_claim(internal_key, block, primary_evidence_id)
            if expanded:
                claims.extend(expanded)
                continue

        claims.append({
            "field": public_field,
            "value": block.get("value") if availability == "available" else None,
            "availability": availability,
            "confidence": _confidence_for(block.get("source_class") or block.get("source_type") or ""),
            "evidence_ids": evidence_ids,
            "note": block_note,
        })

    return claims, evidence


def build_nav_claims(
    orgnr: str, nav_bucket: dict | None, *, nav_checked: bool = True,
) -> tuple[list[dict], list[dict]]:
    """Return (claims, evidence) for NAV jobs for a single company.

    nav_checked=False means NAV was not consulted. That is a distinct
    terminal state from "checked, no postings found".
    """
    if not nav_checked:
        return ([{
            "field": "jobs.has_active_postings",
            "value": None,
            "availability": "not_available",
            "confidence": 1.0,
            "evidence_ids": [],
            "note": "NAV was not consulted in this run; absence of postings is not asserted.",
        }], [])

    if not nav_bucket or not nav_bucket.get("postings"):
        return ([{
            "field": "jobs.has_active_postings",
            "value": False,
            "availability": "not_available",
            "confidence": 0.95,
            "evidence_ids": [],
            "note": "No ACTIVE job postings found for this orgnr on NAV Arbeidsplassen in the lookback window.",
        }], [])

    postings = nav_bucket["postings"]
    evidence = list(nav_bucket["evidence"])

    claims: list[dict] = []
    claims.append({
        "field": "jobs.has_active_postings",
        "value": True,
        "availability": "available",
        "confidence": 0.95,
        "evidence_ids": [p["evidence_id"] for p in postings],
        "note": f"{len(postings)} ACTIVE job posting(s) on NAV Arbeidsplassen.",
    })
    for p in postings:
        claims.append({
            "field": "jobs.posting",
            "value": {
                "title": p.get("title"),
                "jobtitle": p.get("jobtitle"),
                "published": p.get("published"),
                "expires": p.get("expires"),
                "application_due": p.get("application_due"),
                "extent": p.get("extent"),
                "engagementtype": p.get("engagementtype"),
                "positioncount": p.get("positioncount"),
                "sector": p.get("sector"),
                "link": p.get("link"),
                "municipalities": p.get("municipalities"),
                "occupation_categories": p.get("occupation_categories"),
            },
            "availability": "available",
            "confidence": 0.95,
            "evidence_ids": [p["evidence_id"]],
            "note": f"Active NAV posting: {p.get('title')}",
        })
    return claims, evidence


def build_envelope(
    orgnr: str,
    run_meta: dict,
    internal_evidence: dict[str, dict],
    captured: dict[str, dict],
    changes: list[dict] | None = None,
    errors: list[dict] | None = None,
    operations: dict | None = None,
    nav_bucket: dict | None = None,
    nav_checked: bool = True,
) -> dict:
    claims, evidence = build_claims_and_evidence(internal_evidence, captured)
    nav_claims, nav_evidence = build_nav_claims(orgnr, nav_bucket, nav_checked=nav_checked)
    claims.extend(nav_claims)
    evidence.extend(nav_evidence)
    envelope = {
        "organisation_number": orgnr,
        "run": {
            "run_id": run_meta.get("run_id"),
            "started_at": run_meta.get("started_at"),
            "completed_at": run_meta.get("completed_at"),
            "terminal_status": run_meta.get("terminal_status", "completed"),
        },
        "claims": claims,
        "evidence": evidence,
        "changes": changes or [],
        "errors": errors or [],
        "operations": operations or {"requests": 0, "runtime_ms": 0, "third_party_cost_usd": 0},
    }
    attach_summary(envelope)
    return envelope


def validate_citation_shape(envelope: dict) -> list[str]:
    problems: list[str] = []
    if not isinstance(envelope.get("organisation_number"), str):
        problems.append("missing or non-string organisation_number")
    if "run" not in envelope or not isinstance(envelope["run"], dict):
        problems.append("missing run block")
    elif not envelope["run"].get("run_id"):
        problems.append("run.run_id missing")

    claims = envelope.get("claims") or []
    evidence = envelope.get("evidence") or []
    ids = [e.get("id") for e in evidence]
    if len(ids) != len(set(ids)):
        problems.append("duplicate evidence ids")
    id_set = set(ids)

    for i, ev in enumerate(evidence):
        if not ev.get("source_url", "").startswith(("http://", "https://")):
            problems.append(f"evidence[{i}] bad source_url")
        rt = ev.get("retrieved_at") or ""
        if "T" not in rt or not (rt.endswith("Z") or "+" in rt):
            problems.append(f"evidence[{i}] bad retrieved_at")
        sha = ev.get("content_sha256") or ""
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            problems.append(f"evidence[{i}] bad content_sha256")
        sp = ev.get("snapshot_path") or ""
        if not sp or sp.startswith("/") or ".." in sp:
            problems.append(f"evidence[{i}] bad snapshot_path")

    for i, c in enumerate(claims):
        if c.get("availability") not in ALLOWED_AVAILABILITY:
            problems.append(f"claims[{i}] bad availability")
        if c.get("availability") == "available" and not c.get("evidence_ids"):
            problems.append(f"claims[{i}] available but no evidence_ids")
        for eid in c.get("evidence_ids") or []:
            if eid not in id_set:
                problems.append(f"claims[{i}] references missing evidence id {eid}")

    return problems