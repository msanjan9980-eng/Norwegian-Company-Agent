"""Deterministic summary generator.

Reads a cited envelope and produces a plain-text human summary that explains
what the company does, what the recent financials are, who runs it, and what
remains unknown. Every factual sentence traces to a claim in the same envelope.
"""
from __future__ import annotations

from typing import Any


def _claim_value(envelope: dict, field: str) -> Any:
    for c in envelope.get("claims") or []:
        if c.get("field") == field and c.get("availability") == "available":
            return c.get("value")
    return None


def _claims_with_prefix(envelope: dict, prefix: str) -> list[dict]:
    return [c for c in envelope.get("claims") or []
            if c.get("field", "").startswith(prefix) and c.get("availability") == "available"]


def _fmt_money(amount: Any, currency: str | None) -> str | None:
    if amount is None:
        return None
    try:
        n = float(amount)
    except (TypeError, ValueError):
        return None
    if abs(n) >= 1_000_000_000:
        return f"{n/1e9:.2f}B {currency or 'NOK'}"
    if abs(n) >= 1_000_000:
        return f"{n/1e6:.2f}M {currency or 'NOK'}"
    if abs(n) >= 1_000:
        return f"{n/1e3:.1f}K {currency or 'NOK'}"
    return f"{n:,.0f} {currency or 'NOK'}"


def _financial_trends(envelope: dict) -> tuple[dict, dict]:
    by_year: dict[str, dict] = {}
    for c in envelope.get("claims") or []:
        f = c.get("field", "")
        if not f.startswith("financials.") or c.get("availability") != "available":
            continue
        v = c.get("value")
        if not isinstance(v, dict):
            continue
        year = v.get("year") or "unknown"
        by_year.setdefault(year, {})[f.split(".", 1)[1]] = v

    if not by_year:
        return {}, {}

    sorted_years = sorted(by_year.keys(), reverse=True)
    latest_year = sorted_years[0]
    latest = {"year": latest_year, **by_year[latest_year]}

    prev = {}
    if len(sorted_years) > 1:
        prev_year = sorted_years[1]
        prev = {"year": prev_year, **by_year[prev_year]}

    return latest, prev


def _stated_unknowns(envelope: dict) -> list[str]:
    unknowns: list[str] = []
    for c in envelope.get("claims") or []:
        if c.get("availability") in {"not_available", "not_fetched"}:
            f = c.get("field", "")
            if f in {"official_website"}:
                unknowns.append("official website (not in registry)")
            elif f == "group_structure":
                unknowns.append("group structure (single-entity, no registered group)")
    return sorted(set(unknowns))


def generate_summary(envelope: dict) -> str:
    org = envelope.get("organisation_number") or "unknown"
    identity = _claim_value(envelope, "identity.name") or "Unknown company"
    legal = _claim_value(envelope, "identity.legal_form_label") or "entity"
    _ind = _claim_value(envelope, "identity.industry") or {}
    if isinstance(_ind, dict):
        nace = _ind.get("beskrivelse") or "unspecified industry"
        nace_code = _ind.get("kode") or ""
    else:
        nace = "unspecified industry"
        nace_code = ""
    _addr = _claim_value(envelope, "identity.business_address") or {}
    if isinstance(_addr, dict):
        municipality = _addr.get("kommune") or "unknown municipality"
    else:
        municipality = "unknown municipality"
    registered = _claim_value(envelope, "identity.registreringsdatoEnhetsregisteret") or ""
    employees = _claim_value(envelope, "identity.employees")

    lines: list[str] = []

    sentence = f"{identity} (org.nr {org}) is a registered Norwegian {legal}"
    if municipality:
        sentence += f" based in {municipality}"
    if nace:
        sentence += f", operating in {nace.lower()}"
        if nace_code:
            sentence += f" (NACE {nace_code})"
    sentence += "."
    lines.append(sentence)

    extra_bits = []
    if registered:
        extra_bits.append(f"registered {registered}")
    if employees and str(employees) != "0":
        extra_bits.append(f"{employees} employees reported")
    vat = _claim_value(envelope, "identity.registrertIMvaregisteret")
    if vat in (True, "true", "True"):
        extra_bits.append("VAT registered")
    if extra_bits:
        lines.append("Registry context: " + "; ".join(extra_bits) + ".")

    fin, prev_fin = _financial_trends(envelope)
    if fin:
        year = fin.get("year")
        parts = []
        currency = fin.get("revenue", {}).get("currency") if isinstance(fin.get("revenue"), dict) else "NOK"
        if "revenue" in fin:
            parts.append(f"revenue {_fmt_money(fin['revenue'].get('amount'), currency)}")
        if "operating_result" in fin:
            parts.append(f"operating result {_fmt_money(fin['operating_result'].get('amount'), currency)}")
        if "annual_result" in fin:
            parts.append(f"annual result {_fmt_money(fin['annual_result'].get('amount'), currency)}")
        if "total_assets" in fin:
            parts.append(f"total assets {_fmt_money(fin['total_assets'].get('amount'), currency)}")
        if "equity" in fin:
            parts.append(f"equity {_fmt_money(fin['equity'].get('amount'), currency)}")

        if parts:
            lines.append(f"Latest filed accounts (fiscal year {year}): " + ", ".join(parts) + ".")

        if prev_fin and "revenue" in fin and "revenue" in prev_fin:
            curr_rev = fin["revenue"].get("amount")
            prev_rev = prev_fin["revenue"].get("amount")
            if curr_rev is not None and prev_rev is not None and prev_rev != 0:
                pct = ((curr_rev - prev_rev) / abs(prev_rev)) * 100
                direction = "increased" if pct > 0 else "decreased"
                if abs(pct) > 1:
                    lines.append(f"Financial trend: Revenue {direction} by {abs(pct):.1f}% from {prev_fin.get('year')} to {year}.")

    else:
        lines.append("Latest filed accounts: not available for this entity.")

    people = _claims_with_prefix(envelope, "people.role.")
    if people:
        names = []
        for p in people[:6]:
            v = p.get("value") or {}
            n = v.get("name")
            if isinstance(n, list):
                n = ", ".join(str(x) for x in n if x)
            names.append(f"{n or '?'} ({v.get('role','?')})")
        line = f"Registered people: {len(people)} role(s) — " + "; ".join(names)
        if len(people) > 6:
            line += f"; and {len(people)-6} more"
        lines.append(line + ".")

    # Item 10a: the citation pass emits locations.subunit.*, not locations.workplace.
    subunit_names = _claims_with_prefix(envelope, "locations.subunit.name")
    subunit_munis = _claims_with_prefix(envelope, "locations.subunit.municipality")
    if subunit_names or subunit_munis:
        cities = sorted({
            str((c.get("value") or {}).get("municipality"))
            for c in subunit_munis
            if (c.get("value") or {}).get("municipality")
        })
        count = len(subunit_names) or len(subunit_munis)
        line = f"Registered workplaces: {count} subunit(s)"
        if cities:
            line += f" across {', '.join(cities)}"
        lines.append(line + ".")

    parent = _claim_value(envelope, "group.parent")
    children = _claims_with_prefix(envelope, "group.child")
    if parent or children:
        bits = []
        if parent:
            bits.append("registered parent entity")
        if children:
            bits.append(f"{len(children)} registered child/sub entity(ies)")
        lines.append("Corporate structure: " + "; ".join(bits) + ".")

    website = _claim_value(envelope, "official_website")
    if website:
        url = website if isinstance(website, str) else (website.get("final_url") or website.get("requested_url"))
        if url:
            lines.append(f"Official website: {url}")

    # Hiring
    hiring = _claim_value(envelope, "jobs.has_active_postings")
    if hiring is True:
        lines.append("Hiring: Active job postings found on NAV.")
    elif hiring is False:
        lines.append("Hiring: No active job postings found on NAV.")
    else:
        lines.append("Hiring: NAV was not checked or returned no data.")

    # Public Activity
    activities = _claims_with_prefix(envelope, "activity.") + _claims_with_prefix(envelope, "web.activity.")
    if activities:
        lines.append(f"Public activity: {len(activities)} dated event(s) found (e.g. role changes, registrations).")
    else:
        lines.append("Public activity: No dated public activity found in the checked sources.")

    unknowns = _stated_unknowns(envelope)
    if unknowns:
        lines.append("Unknown at this time: " + ", ".join(unknowns) + ".")

    n_claims = len(envelope.get("claims") or [])
    n_evidence = len(envelope.get("evidence") or [])
    lines.append("")
    lines.append(f"Data sources: {n_evidence} source snapshot(s) captured for {n_claims} claim(s) in this envelope.")
    lines.append("Every fact above traces to a claim with a source_url, retrieved_at and content_sha256.")

    changes = envelope.get("changes", [])
    if changes:
        changed_fields = [c["field"] for c in changes if c.get("old_value") != c.get("new_value")]
        if changed_fields:
            lines.append(f"Changes since last observation: {', '.join(changed_fields[:5])}")

    return "\n\n".join(lines)


def attach_summary(envelope: dict) -> dict:
    envelope["summary"] = generate_summary(envelope)
    return envelope