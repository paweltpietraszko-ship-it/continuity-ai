"""Deterministic ingestion and normalization of Project Aurora production artifacts.

This module converts the production artifact directory into typed, normalized
evidence records. It performs no AI reasoning, contradiction detection,
summarization, or next-action generation, and it never reads test-only ground
truth. It must not depend on the fixture generator's fixed artifact
definitions, so that ingestion is verified purely against the on-disk
production contract (the evidence manifest), not against in-process constants.
"""

from __future__ import annotations

import hashlib
import io
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any

from icalendar import Calendar
from openpyxl import load_workbook
from pypdf import PdfReader

from continuity_ai.artifact_io import validate_production_artifact_root
from continuity_ai.models import EvidenceRecord

MANIFEST_FILENAME = "evidence_manifest.json"

_REQUIRED_ARTIFACT_FIELDS = (
    "source_id",
    "evidence_id",
    "author",
    "timestamp",
    "source_type",
    "timeline_position",
    "business_purpose",
    "title",
    "uri",
    "sha256",
)

_FORBIDDEN_DIRECTORY_NAME = "test_only"
_FORBIDDEN_FILENAME = "ground_truth.json"


class ArtifactIngestionError(RuntimeError):
    """Raised when Project Aurora artifact ingestion cannot proceed safely."""


def ingest_artifacts(artifact_root: Path) -> tuple[EvidenceRecord, ...]:
    """Read, validate, and normalize production artifacts into typed evidence records."""

    validate_production_artifact_root(artifact_root)

    manifest_path = artifact_root / MANIFEST_FILENAME
    payload = _load_manifest(manifest_path)
    entries = _validate_manifest_entries(payload)

    records: list[EvidenceRecord] = []
    for entry in entries:
        resolved_path = _resolve_and_validate_uri(artifact_root, entry["uri"])
        raw_bytes = _read_verified_bytes(resolved_path, entry["sha256"])
        content = _parse_artifact(entry["source_type"], raw_bytes)
        records.append(
            EvidenceRecord(
                source_id=entry["source_id"],
                evidence_id=entry["evidence_id"],
                author=entry["author"],
                timestamp=entry["timestamp"],
                source_type=entry["source_type"],
                timeline_position=entry["timeline_position"],
                business_purpose=entry["business_purpose"],
                title=entry["title"],
                uri=entry["uri"],
                artifact_sha256=entry["sha256"],
                content=content,
            )
        )

    return tuple(sorted(records, key=lambda record: (record.timeline_position, record.evidence_id)))


def _load_manifest(manifest_path: Path) -> Any:
    if not manifest_path.is_file():
        raise ArtifactIngestionError(f"Evidence manifest not found at {manifest_path}.")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactIngestionError(f"Evidence manifest at {manifest_path} is not valid JSON.") from exc


def _validate_manifest_entries(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ArtifactIngestionError("Evidence manifest must be a JSON object.")
    if payload.get("schema_version") != 1:
        raise ArtifactIngestionError("Evidence manifest schema_version is missing or unsupported.")
    if not isinstance(payload.get("project"), str) or not payload["project"]:
        raise ArtifactIngestionError("Evidence manifest project field is missing or invalid.")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ArtifactIngestionError("Evidence manifest artifacts field is missing or empty.")

    validated: list[dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    seen_evidence_ids: set[str] = set()
    for entry in artifacts:
        if not isinstance(entry, dict):
            raise ArtifactIngestionError("Evidence manifest artifact entries must be JSON objects.")
        for field in _REQUIRED_ARTIFACT_FIELDS:
            if field not in entry:
                raise ArtifactIngestionError(
                    f"Evidence manifest artifact entry is missing required field '{field}'."
                )

        source_id = entry["source_id"]
        evidence_id = entry["evidence_id"]
        source_type = entry["source_type"]
        timeline_position = entry["timeline_position"]
        uri = entry["uri"]
        sha256 = entry["sha256"]

        if not isinstance(source_id, str) or not source_id:
            raise ArtifactIngestionError("Evidence manifest source_id must be a non-empty string.")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ArtifactIngestionError("Evidence manifest evidence_id must be a non-empty string.")
        if not isinstance(entry["author"], str) or not entry["author"]:
            raise ArtifactIngestionError("Evidence manifest author must be a non-empty string.")
        if not isinstance(entry["timestamp"], str) or not entry["timestamp"]:
            raise ArtifactIngestionError("Evidence manifest timestamp must be a non-empty string.")
        if not isinstance(source_type, str) or source_type not in _PARSERS:
            raise ArtifactIngestionError(f"Evidence manifest source_type '{source_type}' is not supported.")
        if not isinstance(timeline_position, int) or isinstance(timeline_position, bool):
            raise ArtifactIngestionError("Evidence manifest timeline_position must be an integer.")
        if not isinstance(entry["business_purpose"], str) or not entry["business_purpose"]:
            raise ArtifactIngestionError("Evidence manifest business_purpose must be a non-empty string.")
        if not isinstance(entry["title"], str) or not entry["title"]:
            raise ArtifactIngestionError("Evidence manifest title must be a non-empty string.")
        if not isinstance(uri, str) or not uri:
            raise ArtifactIngestionError("Evidence manifest uri must be a non-empty string.")
        if not isinstance(sha256, str) or len(sha256) != 64:
            raise ArtifactIngestionError("Evidence manifest sha256 must be a 64-character string.")

        if source_id in seen_source_ids:
            raise ArtifactIngestionError(f"Duplicate source_id '{source_id}' in evidence manifest.")
        if evidence_id in seen_evidence_ids:
            raise ArtifactIngestionError(f"Duplicate evidence_id '{evidence_id}' in evidence manifest.")
        seen_source_ids.add(source_id)
        seen_evidence_ids.add(evidence_id)

        _reject_unsafe_uri(uri)

        validated.append(entry)

    return validated


def _reject_unsafe_uri(uri: str) -> None:
    if "\\" in uri:
        raise ArtifactIngestionError(f"Evidence manifest uri '{uri}' must use forward slashes only.")
    posix_uri = PurePosixPath(uri)
    if posix_uri.is_absolute():
        raise ArtifactIngestionError(f"Evidence manifest uri '{uri}' must not be absolute.")
    if any(part == ".." for part in posix_uri.parts):
        raise ArtifactIngestionError(f"Evidence manifest uri '{uri}' must not contain path traversal.")
    if _FORBIDDEN_DIRECTORY_NAME in posix_uri.parts or posix_uri.name == _FORBIDDEN_FILENAME:
        raise ArtifactIngestionError(f"Evidence manifest uri '{uri}' cannot reference test-only ground truth.")


def _resolve_and_validate_uri(artifact_root: Path, uri: str) -> Path:
    resolved_root = artifact_root.resolve()
    resolved_path = (artifact_root / uri).resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise ArtifactIngestionError(f"Evidence manifest uri '{uri}' escapes the artifact root.")
    return resolved_path


def _read_verified_bytes(resolved_path: Path, expected_sha256: str) -> bytes:
    if not resolved_path.is_file():
        raise ArtifactIngestionError(f"Artifact file not found at {resolved_path}.")
    data = resolved_path.read_bytes()
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ArtifactIngestionError(
            f"Checksum mismatch for {resolved_path}: expected {expected_sha256}, got {actual_sha256}."
        )
    return data


def _parse_artifact(source_type: str, data: bytes) -> str:
    try:
        return _PARSERS[source_type](data)
    except ArtifactIngestionError:
        raise
    except Exception as exc:
        raise ArtifactIngestionError(f"Failed to parse artifact of type '{source_type}'.") from exc


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def _parse_email(data: bytes) -> str:
    message = BytesParser(policy=policy.default).parsebytes(data)
    subject = message["Subject"] or ""
    body = message.get_content()
    return _normalize_text(f"Subject: {subject}\n\n{body}")


def _parse_calendar(data: bytes) -> str:
    calendar = Calendar.from_ical(data)
    events = [component for component in calendar.walk() if component.name == "VEVENT"]
    if len(events) != 1:
        raise ArtifactIngestionError("Expected exactly one VEVENT in the production calendar artifact.")
    event = events[0]
    lines = [
        f"Summary: {event.get('SUMMARY')}",
        f"Location: {event.get('LOCATION')}",
        f"Description: {event.get('DESCRIPTION')}",
    ]
    return _normalize_text("\n".join(lines))


def _parse_spreadsheet(data: bytes) -> str:
    workbook = load_workbook(io.BytesIO(data), data_only=True)
    sheet = workbook.active
    lines = [
        " | ".join(str(cell) for cell in row if cell is not None)
        for row in sheet.iter_rows(values_only=True)
    ]
    return _normalize_text("\n".join(lines))


def _parse_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages_text = [page.extract_text() or "" for page in reader.pages]
    return _normalize_text("\n".join(pages_text))


def _parse_markdown(data: bytes) -> str:
    return _normalize_text(data.decode("utf-8"))


_PARSERS = {
    "email": _parse_email,
    "calendar": _parse_calendar,
    "spreadsheet": _parse_spreadsheet,
    "pdf": _parse_pdf,
    "markdown": _parse_markdown,
}
