from __future__ import annotations

import csv
import gzip
import json
import hashlib
import random
import heapq
import urllib.parse
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def _first(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return ""


def normalize_row(row: dict[str, str]) -> dict[str, Any]:
    org = _first(row, "organisasjonsnummer", "Organisasjonsnummer")
    employees_raw = _first(row, "antallAnsatte", "Antall ansatte")
    try:
        employees = int(employees_raw) if employees_raw else None
    except ValueError:
        employees = None
    return {
        "organisation_number": org,
        "name": _first(row, "navn", "Navn"),
        "legal_form": _first(row, "organisasjonsform.kode", "Organisasjonsform.kode"),
        "employees": employees,
        "bankrupt": _first(row, "konkurs", "Konkurs").lower() == "true",
        "liquidating": _first(row, "underAvvikling", "Under avvikling").lower() == "true",
        "municipality": _first(row, "forretningsadresse.kommune", "Forretningsadresse.kommune"),
        "municipality_number": _first(row, "forretningsadresse.kommunenummer", "Forretningsadresse.kommunenummer"),
        "industry_code": _first(row, "naeringskode1.kode", "Næringskode1.kode"),
        "industry_label": _first(row, "naeringskode1.beskrivelse", "Næringskode1.beskrivelse"),
        "website": _first(row, "hjemmeside", "Hjemmeside"),
        "latest_submitted_accounts": _first(row, "sisteInnsendteAarsregnskap", "Siste innsendte årsregnskap"),
        "raw": row,
    }


def stratum(record: dict[str, Any]) -> str:
    form = record["legal_form"] if record["legal_form"] in {"AS", "ASA", "ENK"} else "OTHER"
    employees = record["employees"]
    employee_band = "missing" if employees is None else "0" if employees == 0 else "1-4" if employees < 5 else "5-19" if employees < 20 else "20-99" if employees < 100 else "100+"
    state = "adverse" if record["bankrupt"] or record["liquidating"] else "active"
    web = "web" if record["website"] else "no-web"
    return "|".join([form, employee_band, state, web])


def financial_filer_eligible(record: dict[str, Any], latest_year: str, *, active_only: bool = True) -> bool:
    if str(record.get("latest_submitted_accounts") or "") != str(latest_year):
        return False
    if active_only and (record.get("bankrupt") or record.get("liquidating")):
        return False
    return True


def financial_filer_stratum(record: dict[str, Any]) -> str:
    legal_form = str(record.get("legal_form") or "missing")
    employees = record.get("employees")
    employee_band = "missing" if employees is None else "0" if employees == 0 else "1-4" if employees < 5 else "5-19" if employees < 20 else "20-99" if employees < 100 else "100+"
    industry_division = str(record.get("industry_code") or "missing").split(".", 1)[0]
    geography = str(record.get("municipality_number") or "missing")[:2]
    return "|".join([legal_form, employee_band, industry_division, geography, "web" if record.get("website") else "no-web"])


def deterministic_financial_filer_sample(
    path: str | Path,
    count: int,
    *,
    latest_year: str,
    preserved_organisation_numbers: set[str] | None = None,
    excluded_organisation_numbers: set[str] | None = None,
    seed: int = 20260825,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    preserved = set(preserved_organisation_numbers or set())
    excluded = set(excluded_organisation_numbers or set())
    preserved_rows: dict[str, dict[str, Any]] = {}
    heap: list[tuple[int, str, dict[str, Any]]] = []
    registry_rows = 0
    eligible_rows = 0
    for record in iter_bulk(path):
        registry_rows += 1
        if not financial_filer_eligible(record, latest_year) or record["organisation_number"] in excluded:
            continue
        eligible_rows += 1
        org = record["organisation_number"]
        if org in preserved:
            preserved_rows[org] = record
            continue
        rank = int(hashlib.sha256(f"{seed}:{org}".encode()).hexdigest(), 16)
        item = (-rank, org, record)
        if len(heap) < count:
            heapq.heappush(heap, item)
        elif rank < -heap[0][0]:
            heapq.heapreplace(heap, item)

    retained = [preserved_rows[org] for org in sorted(preserved_rows)]
    if len(retained) > count:
        retained = sorted(retained, key=lambda item: hashlib.sha256(f"{seed}:preserved:{item['organisation_number']}".encode()).hexdigest())[:count]
    needed = count - len(retained)
    ranked = [item[2] for item in sorted(heap, key=lambda item: (-item[0], item[1]))]
    selected = retained + ranked[:needed]
    selected = sorted(selected, key=lambda item: hashlib.sha256(f"{seed}:order:{item['organisation_number']}".encode()).hexdigest())
    development = round(count * 0.6)
    validation = round(count * 0.2)
    for index, item in enumerate(selected):
        item["sample_slice"] = "preserved_eligible" if item["organisation_number"] in preserved_rows else "financial_filer_population"
        item["evaluation_split"] = "development" if index < development else "validation" if index < development + validation else "held_out"
    selected_orgs = {item["organisation_number"] for item in selected}
    metadata = {
        "seed": seed,
        "latest_year": str(latest_year),
        "active_only": True,
        "requested": count,
        "selected": len(selected),
        "registry_rows": registry_rows,
        "eligible_rows": eligible_rows,
        "preserved_requested": len(preserved),
        "preserved_eligible_selected": len(selected_orgs & preserved),
        "excluded_organisation_numbers": len(excluded),
        "overlap_with_excluded": len(selected_orgs & excluded),
        "selected_sha256": hashlib.sha256("\n".join(sorted(selected_orgs)).encode()).hexdigest(),
        "evaluation_splits": dict(sorted(__import__("collections").Counter(item["evaluation_split"] for item in selected).items())),
        "legal_form_counts": dict(sorted(__import__("collections").Counter(item["legal_form"] or "missing" for item in selected).items())),
        "financial_stratum_counts": dict(sorted(__import__("collections").Counter(financial_filer_stratum(item) for item in selected).items())),
    }
    return selected, metadata


def _first_path(row: dict, *paths: str):
    """Return the first non-empty value at any of the given keys.

    Accepts both a flat dotted key ("organisasjonsform.kode") and a nested
    dict ({"organisasjonsform": {"kode": ...}}), so the CSV reader and the
    JSONL universe file share the same normalisation shape.
    """
    for path in paths:
        if path in row and row[path] not in (None, ""):
            return row[path]
        cursor = row
        ok = True
        for part in path.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                ok = False
                break
            cursor = cursor[part]
        if ok and cursor not in (None, ""):
            return cursor
    return ""


def _employees(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_json_row(row: dict) -> dict:
    """Same shape as normalize_row() but for a JSONL universe row."""
    org = _first_path(row, "organisasjonsnummer", "Organisasjonsnummer",
                      "orgnr", "organisation_number")
    org = "".join(ch for ch in str(org or "") if ch.isdigit())
    return {
        "organisation_number": org,
        "name": _first_path(row, "navn", "Navn", "name"),
        "legal_form": _first_path(row, "organisasjonsform.kode",
                                  "Organisasjonsform.kode", "legal_form"),
        "employees": _employees(_first_path(row, "antallAnsatte",
                                             "Antall ansatte", "employees")),
        "bankrupt": str(_first_path(row, "konkurs", "Konkurs")).lower() == "true",
        "liquidating": str(_first_path(row, "underAvvikling",
                                        "Under avvikling")).lower() == "true",
        "municipality": _first_path(row, "forretningsadresse.kommune",
                                    "Forretningsadresse.kommune"),
        "municipality_number": _first_path(row, "forretningsadresse.kommunenummer",
                                           "Forretningsadresse.kommunenummer"),
        "industry_code": _first_path(row, "naeringskode1.kode",
                                      "Næringskode1.kode"),
        "industry_label": _first_path(row, "naeringskode1.beskrivelse",
                                       "Næringskode1.beskrivelse"),
        "website": _first_path(row, "hjemmeside", "Hjemmeside", "website"),
        "latest_submitted_accounts": _first_path(row, "sisteInnsendteAarsregnskap",
                                                 "Siste innsendte årsregnskap",
                                                 "latest_submitted_accounts"),
        "raw": row,
    }


def _iter_csv(path) -> Iterable[dict]:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(8192)
        handle.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        for row in csv.DictReader(handle, dialect=dialect):
            record = normalize_row(row)
            if len(record["organisation_number"]) == 9:
                yield record


def _iter_jsonl(path) -> Iterable[dict]:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            record = normalize_json_row(row)
            if len(record["organisation_number"]) == 9:
                yield record


def iter_bulk(path: str | Path) -> Iterable[dict[str, Any]]:
    """Iterate a Brreg snapshot.

    Accepts .csv, .csv.gz, .jsonl and .jsonl.gz. The Builderr universe is
    JSONL; the public Brreg bulk endpoint is CSV. Same normalised shape
    either way.
    """
    suffix = str(path).lower()
    if suffix.endswith((".jsonl", ".jsonl.gz")):
        yield from _iter_jsonl(path)
    else:
        yield from _iter_csv(path)


def deterministic_sample(path: str | Path, count: int, seed: int = 20260822) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(seed)
    population_count = round(count * 0.7)
    stress_count = count - population_count
    reservoir_size = max(30, count // 5)
    population: list[dict[str, Any]] = []
    reservoirs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: dict[str, int] = defaultdict(int)
    total = 0
    hasher = hashlib.sha256()
    for record in iter_bulk(path):
        total += 1
        key = stratum(record)
        seen[key] += 1
        hasher.update(record["organisation_number"].encode())
        if len(population) < population_count:
            population.append(record)
        else:
            position = rng.randrange(total)
            if position < population_count:
                population[position] = record
        bucket = reservoirs[key]
        if len(bucket) < reservoir_size:
            bucket.append(record)
        else:
            position = rng.randrange(seen[key])
            if position < reservoir_size:
                bucket[position] = record

    for item in population:
        item["sample_slice"] = "population"
    chosen: list[dict[str, Any]] = list(population)
    chosen_orgs = {item["organisation_number"] for item in chosen}
    keys = sorted(reservoirs)
    minimum = max(1, min(3, stress_count // max(1, len(keys))))
    for key in keys:
        rng.shuffle(reservoirs[key])
        additions = [item for item in reservoirs[key] if item["organisation_number"] not in chosen_orgs][:minimum]
        for item in additions:
            item["sample_slice"] = "stress"
            chosen_orgs.add(item["organisation_number"])
        chosen.extend(additions)
    candidates = [item for key in keys for item in reservoirs[key][minimum:] if item["organisation_number"] not in chosen_orgs]
    rng.shuffle(candidates)
    additions = candidates[: max(0, count - len(chosen))]
    for item in additions:
        item["sample_slice"] = "stress"
    chosen.extend(additions)
    chosen = chosen[:count]
    split_counts = {"development": round(count * 0.6), "validation": round(count * 0.2)}
    by_hash = sorted(chosen, key=lambda item: hashlib.sha256(f"{seed}:{item['organisation_number']}".encode()).hexdigest())
    for index, item in enumerate(by_hash):
        item["evaluation_split"] = "development" if index < split_counts["development"] else "validation" if index < split_counts["development"] + split_counts["validation"] else "held_out"
    metadata = {
        "seed": seed,
        "requested": count,
        "selected": len(chosen),
        "population_selected": sum(item["sample_slice"] == "population" for item in chosen),
        "stress_selected": sum(item["sample_slice"] == "stress" for item in chosen),
        "evaluation_splits": dict(sorted(__import__("collections").Counter(item["evaluation_split"] for item in chosen).items())),
        "registry_rows": total,
        "registry_org_sequence_sha256": hasher.hexdigest(),
        "stratum_counts": dict(sorted(seen.items())),
        "selected_stratum_counts": dict(sorted(__import__("collections").Counter(stratum(item) for item in chosen).items())),
        "population_stratum_counts": dict(sorted(__import__("collections").Counter(stratum(item) for item in chosen if item["sample_slice"] == "population").items())),
        "stress_stratum_counts": dict(sorted(__import__("collections").Counter(stratum(item) for item in chosen if item["sample_slice"] == "stress").items())),
    }
    return chosen, metadata


def deterministic_extension_sample(
    path: str | Path,
    count: int,
    excluded_organisation_numbers: set[str],
    seed: int = 20260824,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    heap: list[tuple[int, str, dict[str, Any]]] = []
    registry_rows = 0
    eligible_rows = 0
    for record in iter_bulk(path):
        registry_rows += 1
        org = record["organisation_number"]
        if org in excluded_organisation_numbers:
            continue
        eligible_rows += 1
        rank = int(hashlib.sha256(f"{seed}:{org}".encode()).hexdigest(), 16)
        item = (-rank, org, record)
        if len(heap) < count:
            heapq.heappush(heap, item)
        elif rank < -heap[0][0]:
            heapq.heapreplace(heap, item)
    selected = [item[2] for item in sorted(heap, key=lambda item: (-item[0], item[1]))]
    for item in selected:
        item["sample_slice"] = "extension"
        item["evaluation_split"] = "extension_holdout"
    selected_orgs = {item["organisation_number"] for item in selected}
    return selected, {
        "seed": seed,
        "requested": count,
        "selected": len(selected),
        "registry_rows": registry_rows,
        "eligible_rows_after_exclusion": eligible_rows,
        "excluded_organisation_numbers": len(excluded_organisation_numbers),
        "overlap_with_excluded": len(selected_orgs & excluded_organisation_numbers),
        "selected_sha256": hashlib.sha256("\n".join(sorted(selected_orgs)).encode()).hexdigest(),
        "selected_stratum_counts": dict(sorted(__import__("collections").Counter(stratum(item) for item in selected).items())),
        "legal_form_counts": dict(sorted(__import__("collections").Counter(item["legal_form"] or "missing" for item in selected).items())),
    }


def deterministic_website_audit_sample(
    path: str | Path,
    count: int,
    excluded_organisation_numbers: set[str],
    excluded_website_hosts: set[str] | None = None,
    seed: int = 20260823,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    registry_rows = 0
    website_rows = 0
    hasher = hashlib.sha256()
    for record in iter_bulk(path):
        registry_rows += 1
        hasher.update(record["organisation_number"].encode())
        if not record.get("website") or record["organisation_number"] in excluded_organisation_numbers:
            continue
        website_rows += 1
        minimal = {key: value for key, value in record.items() if key != "raw"}
        rank = hashlib.sha256(f"{seed}:{record['organisation_number']}".encode()).hexdigest()
        candidates.append((rank, minimal))

    selected: list[dict[str, Any]] = []
    seen_hosts: set[str] = set(excluded_website_hosts or set())
    selected_hosts: set[str] = set()
    for _, record in sorted(candidates, key=lambda item: item[0]):
        supplied = str(record["website"]).strip()
        parsed = urllib.parse.urlparse(supplied if "://" in supplied else "https://" + supplied)
        host = (parsed.hostname or "").casefold().removeprefix("www.")
        if not host or host in seen_hosts:
            continue
        seen_hosts.add(host)
        selected_hosts.add(host)
        record["sample_slice"] = "fresh_website_audit"
        record["evaluation_split"] = "independent_final"
        selected.append(record)
        if len(selected) == count:
            break

    return selected, {
        "seed": seed,
        "requested": count,
        "selected": len(selected),
        "excluded_organisation_numbers": len(excluded_organisation_numbers),
        "excluded_website_hosts": len(excluded_website_hosts or set()),
        "registry_rows": registry_rows,
        "registry_rows_with_website_after_exclusion": website_rows,
        "unique_hosts_selected": len(selected_hosts),
        "registry_org_sequence_sha256": hasher.hexdigest(),
    }