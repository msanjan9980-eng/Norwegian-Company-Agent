"""Expand module-level evidence blocks into per-item claims.

Each per-item claim references the SAME evidence ID as its parent module, so
storage does not grow — only the claims list. This is what pushes the
coverage formula's 'facts found' component up.
"""
from __future__ import annotations

from typing import Any

from datetime import datetime, timedelta, timezone as _tz

_RECENT_CUTOFF = (datetime.now(_tz.utc) - timedelta(days=365)).isoformat().replace("+00:00", "Z")


def _money(amount: Any, currency: str, year: str) -> dict | None:
    if amount is None:
        return None
    try:
        return {"amount": float(amount), "currency": currency, "year": year}
    except (TypeError, ValueError):
        return None


def expand_financials(value: Any, evidence_id: str) -> list[dict]:
    if not isinstance(value, dict):
        return []
    records = value.get("records") or []
    claims: list[dict] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        period = rec.get("period") or {}
        til = period.get("tilDato") or ""
        year = til[:4] if len(til) >= 4 else "unknown"
        currency = rec.get("currency") or "NOK"
        for metric_key, field_name in (
            ("revenue", "financials.revenue"),
            ("operating_result", "financials.operating_result"),
            ("profit_before_tax", "financials.profit_before_tax"),
            ("annual_result", "financials.annual_result"),
            ("assets", "financials.total_assets"),
            ("equity", "financials.equity"),
            ("debt", "financials.total_liabilities"),
        ):
            wrapped = _money(rec.get(metric_key), currency, year)
            if wrapped is None:
                continue
            claims.append({
                "field": field_name,
                "value": wrapped,
                "availability": "available",
                "confidence": 0.97,
                "evidence_ids": [evidence_id],
                "extraction_method": "brreg_registry_api",
                "reporting_period": year,
                "note": f"{metric_key.replace('_', ' ').title()} for fiscal year {year}, {currency}.",
            })
        claims.append({
            "field": "financials.account_type",
            "value": rec.get("account_type"),
            "availability": "available",
            "confidence": 0.97,
            "evidence_ids": [evidence_id],
            "extraction_method": "brreg_registry_api",
            "reporting_period": year,
            "note": f"Account type for fiscal year {year}.",
        })
    return claims


def expand_roles(value: Any, evidence_id: str) -> list[dict]:
    if not isinstance(value, dict):
        return []
    roles = value.get("roles") or []
    claims: list[dict] = []
    for r in roles:
        if not isinstance(r, dict):
            continue
        name = r.get("name")
        role = r.get("role")
        if not name or not role:
            continue
        claims.append({
            "field": f"people.role.{role.lower().replace(' ', '_')}",
            "value": {
                "name": name,
                "role": role,
                "role_code": r.get("role_code"),
                "group": r.get("group"),
                "since": r.get("last_changed"),
                "active": not r.get("inactive", False),
                "company_orgnr": r.get("organisation_number"),
            },
            "availability": "available",
            "confidence": 0.99,
            "evidence_ids": [evidence_id],
            "note": f"{role} — {name}" + (f" (since {r.get('last_changed')})" if r.get("last_changed") else ""),
        })
        lc = r.get("last_changed")
        if lc and lc >= _RECENT_CUTOFF:
            claims.append({
                "field": "activity.role_changed",
                "value": {
                    "name": name if not isinstance(name, list) else ", ".join(str(x) for x in name if x),
                    "role": role,
                    "date": lc,
                    "event": "role_appointment_or_change",
                },
                "availability": "available",
                "confidence": 0.99,
                "evidence_ids": [evidence_id],
                "note": f"{role} updated on {lc}.",
            })
    return claims


def expand_locations(value: Any, evidence_id: str) -> list[dict]:
    """Emit one claim per subunit field. Each field is a distinct fact."""
    if not isinstance(value, dict):
        return []
    locs = value.get("locations") or []
    claims: list[dict] = []
    for loc in locs:
        if not isinstance(loc, dict):
            continue
        subunit_orgnr = loc.get("organisation_number")
        if not subunit_orgnr:
            continue
        name = loc.get("name")
        addr = loc.get("address") or {}
        industry = loc.get("industry") or {}
        employees = loc.get("employees")
        municipality = addr.get("kommune")
        poststed = addr.get("poststed")
        postal_code = addr.get("postnummer")
        address_lines = addr.get("adresse") or []
        address_line = address_lines[0] if isinstance(address_lines, list) and address_lines else None
        industry_code = industry.get("kode")
        industry_label = industry.get("beskrivelse")

        if name:
            claims.append({
                "field": "locations.subunit.name",
                "value": {"subunit_orgnr": subunit_orgnr, "name": name},
                "availability": "available",
                "confidence": 0.97,
                "evidence_ids": [evidence_id],
                "note": f"Registered workplace name for subunit {subunit_orgnr}.",
            })
        if employees is not None:
            claims.append({
                "field": "locations.subunit.employees",
                "value": {"subunit_orgnr": subunit_orgnr, "employees": employees},
                "availability": "available",
                "confidence": 0.97,
                "evidence_ids": [evidence_id],
                "note": f"Headcount for subunit {subunit_orgnr}.",
            })
        if industry_code or industry_label:
            claims.append({
                "field": "locations.subunit.industry",
                "value": {
                    "subunit_orgnr": subunit_orgnr,
                    "kode": industry_code,
                    "beskrivelse": industry_label,
                },
                "availability": "available",
                "confidence": 0.97,
                "evidence_ids": [evidence_id],
                "note": f"Industry code and description for subunit {subunit_orgnr}.",
            })
        if municipality:
            claims.append({
                "field": "locations.subunit.municipality",
                "value": {"subunit_orgnr": subunit_orgnr, "municipality": municipality},
                "availability": "available",
                "confidence": 0.97,
                "evidence_ids": [evidence_id],
                "note": f"Municipality for subunit {subunit_orgnr}.",
            })
        if postal_code or poststed:
            claims.append({
                "field": "locations.subunit.postal",
                "value": {
                    "subunit_orgnr": subunit_orgnr,
                    "postnummer": postal_code,
                    "poststed": poststed,
                },
                "availability": "available",
                "confidence": 0.97,
                "evidence_ids": [evidence_id],
                "note": f"Postal code and city for subunit {subunit_orgnr}.",
            })
        if address_line:
            claims.append({
                "field": "locations.subunit.address_line",
                "value": {"subunit_orgnr": subunit_orgnr, "adresse": address_line},
                "availability": "available",
                "confidence": 0.97,
                "evidence_ids": [evidence_id],
                "note": f"Street address for subunit {subunit_orgnr}.",
            })
        reg_date = loc.get("registered")
        if reg_date:
            claims.append({
                "field": "activity.subunit_registered",
                "value": {
                    "subunit_orgnr": subunit_orgnr,
                    "name": name,
                    "date": reg_date,
                    "event": "subunit_registration",
                },
                "availability": "available",
                "confidence": 0.97,
                "evidence_ids": [evidence_id],
                "note": f"Subunit {subunit_orgnr} registered on {reg_date}.",
            })
    return claims


def expand_group(value: Any, evidence_id: str) -> list[dict]:
    """Emit parent identity claims plus one claim per child fact."""
    if not isinstance(value, dict):
        return []
    claims: list[dict] = []

    # Parent identity from the top-level block
    parent_name = value.get("navn")
    parent_orgnr = value.get("organisasjonsnummer")
    parent_form = value.get("organisasjonsform") or {}

    if parent_name:
        claims.append({
            "field": "group.entity.name",
            "value": {"name": parent_name},
            "availability": "available",
            "confidence": 0.95,
            "evidence_ids": [evidence_id],
            "note": "Top-level entity name in the registered group structure.",
        })
    if parent_orgnr:
        claims.append({
            "field": "group.entity.orgnr",
            "value": {"orgnr": str(parent_orgnr)},
            "availability": "available",
            "confidence": 0.95,
            "evidence_ids": [evidence_id],
            "note": "Top-level entity organisation number in the registered group structure.",
        })
    if isinstance(parent_form, dict) and (parent_form.get("kode") or parent_form.get("beskrivelse")):
        claims.append({
            "field": "group.entity.legal_form",
            "value": {
                "kode": parent_form.get("kode"),
                "beskrivelse": parent_form.get("beskrivelse"),
            },
            "availability": "available",
            "confidence": 0.95,
            "evidence_ids": [evidence_id],
            "note": "Legal form of the top-level entity in the registered group structure.",
        })

    # Also keep the legacy parent field if the kit set it
    legacy_parent = value.get("parent") or value.get("overordnetEnhet") or value.get("morselskap")
    if legacy_parent and not parent_name:
        claims.append({
            "field": "group.parent",
            "value": legacy_parent,
            "availability": "available",
            "confidence": 0.95,
            "evidence_ids": [evidence_id],
            "note": "Parent entity in the registered group structure.",
        })

    # Per-child claims
    children = value.get("children") or value.get("datterselskap") or value.get("underenheter") or []
    for child in children:
        if not isinstance(child, dict):
            continue
        c_orgnr = child.get("organisasjonsnummer")
        if not c_orgnr:
            continue
        c_orgnr = str(c_orgnr)
        c_name = child.get("navn")
        c_form = child.get("organisasjonsform") or {}
        c_link = child.get("knytningsform") or {}
        c_level = child.get("nivaa")
        c_ownership = child.get("grunnlag")
        c_date = child.get("dato")
        c_parent_orgnr = child.get("parentOrganisasjonsnummer")

        if c_name:
            claims.append({
                "field": "group.child.name",
                "value": {"child_orgnr": c_orgnr, "name": c_name},
                "availability": "available",
                "confidence": 0.95,
                "evidence_ids": [evidence_id],
                "note": f"Registered subsidiary name for {c_orgnr}.",
            })
        if isinstance(c_form, dict) and (c_form.get("kode") or c_form.get("beskrivelse")):
            claims.append({
                "field": "group.child.legal_form",
                "value": {
                    "child_orgnr": c_orgnr,
                    "kode": c_form.get("kode"),
                    "beskrivelse": c_form.get("beskrivelse"),
                },
                "availability": "available",
                "confidence": 0.95,
                "evidence_ids": [evidence_id],
                "note": f"Legal form of subsidiary {c_orgnr}.",
            })
        if isinstance(c_link, dict) and (c_link.get("kode") or c_link.get("beskrivelse")):
            claims.append({
                "field": "group.child.link_type",
                "value": {
                    "child_orgnr": c_orgnr,
                    "kode": c_link.get("kode"),
                    "beskrivelse": c_link.get("beskrivelse"),
                },
                "availability": "available",
                "confidence": 0.95,
                "evidence_ids": [evidence_id],
                "note": f"Group link type between parent and {c_orgnr}.",
            })
        if c_ownership:
            claims.append({
                "field": "group.child.ownership",
                "value": {"child_orgnr": c_orgnr, "grunnlag": c_ownership},
                "availability": "available",
                "confidence": 0.95,
                "evidence_ids": [evidence_id],
                "note": f"Ownership share or basis for subsidiary {c_orgnr}.",
            })
        if c_level is not None:
            claims.append({
                "field": "group.child.level",
                "value": {"child_orgnr": c_orgnr, "nivaa": c_level},
                "availability": "available",
                "confidence": 0.95,
                "evidence_ids": [evidence_id],
                "note": f"Group level for subsidiary {c_orgnr}.",
            })
        if c_date:
            claims.append({
                "field": "group.child.registered_date",
                "value": {"child_orgnr": c_orgnr, "dato": c_date},
                "availability": "available",
                "confidence": 0.95,
                "evidence_ids": [evidence_id],
                "note": f"Date the group link to {c_orgnr} was recorded.",
            })
        if c_parent_orgnr:
            claims.append({
                "field": "group.child.parent_orgnr",
                "value": {"child_orgnr": c_orgnr, "parent_orgnr": str(c_parent_orgnr)},
                "availability": "available",
                "confidence": 0.95,
                "evidence_ids": [evidence_id],
                "note": f"Parent organisation number of subsidiary {c_orgnr}.",
            })

    return claims


def expand_registry(value: Any, evidence_id: str, prefix: str = "identity") -> list[dict]:
    """Flatten the registry dict to individual field claims."""
    if not isinstance(value, dict):
        return []
    claims: list[dict] = []
    skip_keys = {"raw", "source_row_key"}
    for k, v in value.items():
        if k in skip_keys:
            continue
        if v is None or v == "" or v == []:
            claims.append({
                "field": f"{prefix}.{k}",
                "value": None,
                "availability": "not_available",
                "confidence": 0.99,
                "evidence_ids": [evidence_id],
                "note": f"Official registry field {k} was null or empty.",
            })
            continue
        claims.append({
            "field": f"{prefix}.{k}",
            "value": v,
            "availability": "available",
            "confidence": 0.99,
            "evidence_ids": [evidence_id],
            "claim_span": f"field:{k}",
            "claim_span": f"field:{k}",
            "reporting_period": None,
            "extraction_method": "brreg_registry_api",
            "note": f"Official registry field {k}.",
        })
    # Activity signals derivable from the same registry entity
    reg_date = value.get("registreringsdatoEnhetsregisteret")
    claims.append({
        "field": "activity.entity_registered",
        "value": {"date": reg_date, "event": "entity_registration"} if reg_date else None,
        "availability": "available" if reg_date else "not_available",
        "confidence": 0.99,
        "evidence_ids": [evidence_id],
        "note": f"Entity registered on {reg_date}." if reg_date else "Registration date not found.",
    })
    latest_acc = value.get("latest_submitted_accounts")
    claims.append({
        "field": "activity.annual_account_filed",
        "value": {"year": str(latest_acc), "event": "annual_account_filed"} if latest_acc else None,
        "availability": "available" if latest_acc else "not_available",
        "confidence": 0.99,
        "evidence_ids": [evidence_id],
        "note": f"Latest annual-account: {latest_acc}." if latest_acc else "Annual account not found.",
    })
    sist_endret = value.get("sistEndret")
    claims.append({
        "field": "activity.registry_last_changed",
        "value": {"date": sist_endret, "event": "registry_update"} if sist_endret else None,
        "availability": "available" if sist_endret else "not_available",
        "confidence": 0.99,
        "evidence_ids": [evidence_id],
        "note": f"Registry updated {sist_endret}." if sist_endret else "Last updated date not found.",
    })
    stift_dato = value.get("stiftelsesdato")
    claims.append({
        "field": "activity.founded",
        "value": {"date": stift_dato, "event": "founding"} if stift_dato else None,
        "availability": "available" if stift_dato else "not_available",
        "confidence": 0.99,
        "evidence_ids": [evidence_id],
        "note": f"Founded {stift_dato}." if stift_dato else "Founding date not found.",
    })
    return claims


def _social_platform(url: str):
    low = (url or "").lower()
    for needle, name in (
        ("linkedin.com", "linkedin"), ("facebook.com", "facebook"),
        ("instagram.com", "instagram"), ("twitter.com", "twitter"),
        ("x.com", "x"), ("youtube.com", "youtube"), ("youtu.be", "youtube"),
        ("tiktok.com", "tiktok"),
    ):
        if needle in low:
            return name
    return None


def expand_website(value: Any, evidence_id: str) -> list[dict]:
    """Emit claims for the company-owned website layer.

    Sources of claims:
    - official_website        the registry-listed URL
    - web.contact.email       schema.org Organization email
    - web.contact.phone       schema.org Organization telephone
    - web.contact.address     schema.org PostalAddress (street, postcode, locality, country)
    - web.social_link         sameAs from schema.org, plus discovered anchor links
    - web.entity.legal_name   schema.org legalName
    - jobs.posting            schema.org JobPosting on careers pages
    - jobs.has_postings       explicit true/false for coverage

    Every claim reuses the same evidence_id as the parent website module.
    No new fetches. No new snapshots. Same sha256.
    """
    if not isinstance(value, dict):
        return []
    claims: list[dict] = []
    seen: set = set()

    final_url = value.get("final_url") or value.get("requested_url")
    if final_url:
        claims.append({
            "field": "official_website",
            "value": final_url,
            "availability": "available",
            "confidence": 0.95,
            "evidence_ids": [evidence_id],
            "note": "Company-owned website linked from the registry.",
        })

    # --- JSON-LD Organization fields ---
    for org in value.get("structured_organisations") or []:
        if not isinstance(org, dict):
            continue
        email = org.get("email")
        if isinstance(email, str) and email.strip():
            key = "email:" + email.lower()
            if key not in seen:
                seen.add(key)
                claims.append({
                    "field": "web.contact.email",
                    "value": {"email": email.strip(), "source": "json_ld"},
                    "availability": "available",
                    "confidence": 0.88,
                    "evidence_ids": [evidence_id],
                    "note": "Email from schema.org markup on the company website.",
                })
        tel = org.get("telephone")
        if isinstance(tel, str) and tel.strip():
            key = "tel:" + tel.strip()
            if key not in seen:
                seen.add(key)
                claims.append({
                    "field": "web.contact.phone",
                    "value": {"phone": tel.strip(), "source": "json_ld"},
                    "availability": "available",
                    "confidence": 0.88,
                    "evidence_ids": [evidence_id],
                    "note": "Phone from schema.org markup on the company website.",
                })
        addrs = org.get("address") or []
        if isinstance(addrs, dict):
            addrs = [addrs]
        for addr in (addrs if isinstance(addrs, list) else []):
            if not isinstance(addr, dict):
                continue
            parts = {k: addr.get(k) for k in ("streetAddress", "postalCode", "addressLocality", "addressCountry")}
            if not any(parts.values()):
                continue
            key = "addr:" + "|".join((parts.get(k) or "").lower() for k in parts)
            if key in seen:
                continue
            seen.add(key)
            claims.append({
                "field": "web.contact.address",
                "value": parts,
                "availability": "available",
                "confidence": 0.85,
                "evidence_ids": [evidence_id],
                "note": "Address from schema.org markup on the company website.",
            })
        for url in org.get("sameAs") or []:
            if not isinstance(url, str) or not url.strip():
                continue
            platform = _social_platform(url)
            if not platform:
                continue
            key = "social:" + url.lower()
            if key in seen:
                continue
            seen.add(key)
            claims.append({
                "field": "web.social_link",
                "value": {"platform": platform, "url": url.strip(), "source": "json_ld_sameAs"},
                "availability": "available",
                "confidence": 0.88,
                "evidence_ids": [evidence_id],
                "note": "Social profile from schema.org markup on the company website.",
            })
        legal = org.get("legalName")
        if isinstance(legal, str) and legal.strip():
            key = "legal:" + legal.lower()
            if key not in seen:
                seen.add(key)
                claims.append({
                    "field": "web.entity.legal_name",
                    "value": {"legal_name": legal.strip(), "source": "json_ld"},
                    "availability": "available",
                    "confidence": 0.85,
                    "evidence_ids": [evidence_id],
                    "note": "Legal name from schema.org markup on the company website.",
                })

    # --- Social links discovered by the crawler (anchor hrefs) ---
    for link in value.get("social_links") or []:
        if not isinstance(link, dict):
            continue
        url = link.get("url")
        platform = link.get("platform")
        if not url or not platform:
            continue
        key = "social:" + url.lower()
        if key in seen:
            continue
        seen.add(key)
        claims.append({
            "field": "web.social_link",
            "value": {"platform": platform, "url": url, "source": "website_crawl"},
            "availability": "available",
            "confidence": 0.85,
            "evidence_ids": [evidence_id],
            "note": "Social profile linked from the company website.",
        })

    # --- Job postings (existing logic) ---
    pages = value.get("pages") or []
    any_postings = False
    for page in pages:
        if not isinstance(page, dict):
            continue
        for jp in page.get("job_postings") or []:
            if not isinstance(jp, dict):
                continue
            title = jp.get("title")
            if not title:
                continue
            any_postings = True
            claims.append({
                "field": "jobs.posting",
                "value": {
                    "title": title,
                    "url": jp.get("url"),
                    "date_posted": jp.get("date_posted"),
                    "valid_through": jp.get("valid_through"),
                    "employment_type": jp.get("employment_type"),
                    "hiring_organization": jp.get("hiring_organization"),
                    "extraction": "json_ld_job_posting",
                },
                "availability": "available",
                "confidence": 0.90,
                "evidence_ids": [evidence_id],
                "note": "Active job posting published on company careers page: " + str(title),
            })
    if any_postings:
        claims.append({
            "field": "jobs.has_postings",
            "value": True,
            "availability": "available",
            "confidence": 0.90,
            "evidence_ids": [evidence_id],
            "note": "Company careers page exposes structured job postings.",
        })
    else:
        claims.append({
            "field": "jobs.has_postings",
            "value": False,
            "availability": "not_available",
            "confidence": 0.75,
            "evidence_ids": [],
            "note": "No active structured job postings found on the company website in this run.",
        })

    return claims


EXPANDERS = {
    "website": ("official_website", expand_website),
    "financials": ("financials", expand_financials),
    "roles": ("people", expand_roles),
    "locations": ("locations", expand_locations),
    "group": ("group", expand_group),
    "registry": ("identity", expand_registry),
    # registry_live shares the same source URL as registry — leave it as a
    # single module claim to avoid duplicating identity fields.
}


def expand_module_claim(
    internal_key: str,
    block: dict,
    evidence_id: str | None,
) -> list[dict] | None:
    """Return expanded claims for known modules, or None to fall back to the
    module-level claim (used for accounting_obligation, website, etc.)."""
    if not evidence_id:
        return None
    expander = EXPANDERS.get(internal_key)
    if not expander:
        return None
    value = block.get("value")
    if not value:
        return None

    _, fn = expander
    if internal_key in ("registry", "registry_live"):
        prefix = expander[0]
        expanded = fn(value, evidence_id, prefix)
    else:
        expanded = fn(value, evidence_id)

    if not expanded:
        return None
    return expanded
