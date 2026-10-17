"""Content-addressable snapshot store for Signalpost evidence.

Every fact published by the agent must reference a captured file on disk.
The filename encodes the SHA-256 so duplicate fetches do not duplicate storage,
and the citation validator can re-hash the file to verify integrity.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path


SNAPSHOTS_ROOT = Path("snapshots")

_EXT_FROM_CONTENT_TYPE = {
    "application/json": ".json",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "text/html": ".html",
    "text/plain": ".txt",
    "application/rss+xml": ".rss",
    "text/csv": ".csv",
    "application/gzip": ".gz",
}

# Max size per snapshot — mirrors the validator's 20 MB ceiling.
MAX_SNAPSHOT_BYTES = 20 * 1024 * 1024


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extension_for(content_type: str | None, source_url: str) -> str:
    if content_type:
        ct = content_type.split(";", 1)[0].strip().lower()
        if ct in _EXT_FROM_CONTENT_TYPE:
            return _EXT_FROM_CONTENT_TYPE[ct]
    path = source_url.split("?", 1)[0].split("#", 1)[0]
    tail = path.rsplit("/", 1)[-1]
    if "." in tail:
        return "." + tail.rsplit(".", 1)[1][:8]
    return ".bin"


def capture(
    orgnr: str,
    raw: bytes,
    source_url: str,
    source_class: str,
    content_type: str | None = None,
    claim_span: str | None = None,
    status_code: int | None = None,
    redirect_chain: list[str] | None = None,
    parser_version: str = "1.0",
    access_policy: str = "standard",
    reporting_period: str | None = None,
) -> dict:
    """Persist raw bytes and return an evidence record."""
    if not raw:
        raise ValueError("refusing to snapshot empty payload")
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError(f"snapshot exceeds {MAX_SNAPSHOT_BYTES} bytes")

    sha = hashlib.sha256(raw).hexdigest()
    evidence_id = f"ev-{sha[:16]}"
    ext = _extension_for(content_type, source_url)

    dir_path = SNAPSHOTS_ROOT / orgnr
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / f"{evidence_id}{ext}"

    # Write once; if the exact bytes already exist we skip the IO.
    if not file_path.exists():
        file_path.write_bytes(raw)

    rel = str(file_path).replace("\\", "/")

    return {
        "id": evidence_id,
        "source_url": source_url,
        "source_class": source_class,
        "retrieved_at": utc_now_iso(),
        "content_sha256": sha,
        "snapshot_path": rel,
        "snapshot_bytes": len(raw),
        "claim_span": claim_span,
        "status_code": status_code,
        "redirect_chain": redirect_chain or [],
        "parser_version": parser_version,
        "access_policy": access_policy,
        "reporting_period": reporting_period,
    }


def capture_from_disk(
    orgnr: str,
    local_path: str | Path,
    source_url: str,
    source_class: str,
    content_type: str | None = None,
    claim_span: str | None = None,
    **kwargs,
) -> dict:
    """Snapshot a file we already have on disk (e.g. the bulk registry CSV)."""
    raw = Path(local_path).read_bytes()
    return capture(orgnr, raw, source_url, source_class, content_type, claim_span, **kwargs)


def verify(record: dict) -> bool:
    """Re-read the file and confirm its SHA-256 matches the record."""
    p = Path(record["snapshot_path"])
    if not p.is_file():
        return False
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    return digest == record["content_sha256"]
