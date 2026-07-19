"""Fail-closed ingestion of only an unseen run's engine-visible input root."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from continuity_ai.unseen_workspace.models import (
    ProjectReference,
    RawWorkspaceRecord,
    WorkspaceInput,
)

WORKSPACE_FILENAME = "workspace.json"
RECORDS_DIRECTORY = "records"
SUPPORTED_FORMATS = frozenset({"txt", "md", "json"})

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_FIELDS = {"schema_version", "target_project", "records"}
_PROJECT_FIELDS = {"project_id", "name"}
_RECORD_FIELDS = {"evidence_id", "format", "path", "sha256"}
_JSON_RECORD_FIELDS = {"schema_version", "content"}


class RawWorkspaceIngestionError(RuntimeError):
    """Raised when raw workspace input cannot be loaded safely and completely."""


def load_workspace(input_root: Path) -> WorkspaceInput:
    """Load a raw workspace without consulting any path outside ``input_root``."""

    root = Path(input_root)
    if _is_unsafe_link(root) or not root.is_dir():
        raise RawWorkspaceIngestionError("Workspace input root must be a real directory, not a symlink.")
    root = root.resolve()
    _validate_root_shape(root)

    manifest_path = root / WORKSPACE_FILENAME
    payload = _load_json_file(manifest_path, "Workspace manifest")
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_FIELDS:
        raise RawWorkspaceIngestionError("Workspace manifest fields are missing or unexpected.")
    if payload.get("schema_version") != 1:
        raise RawWorkspaceIngestionError("Workspace manifest schema_version is unsupported.")

    target_project = _validate_project(payload.get("target_project"))
    entries = payload.get("records")
    if not isinstance(entries, list) or not entries:
        raise RawWorkspaceIngestionError("Workspace records must be a non-empty array.")

    records: list[RawWorkspaceRecord] = []
    seen_evidence_ids: set[str] = set()
    seen_paths: set[str] = set()
    referenced_names: set[str] = set()
    for entry in entries:
        record, filename = _load_record(root, entry, seen_evidence_ids, seen_paths)
        records.append(record)
        referenced_names.add(filename.casefold())

    records_root = root / RECORDS_DIRECTORY
    actual_names = {path.name.casefold() for path in records_root.iterdir()}
    if actual_names != referenced_names:
        raise RawWorkspaceIngestionError(
            "Records directory must contain exactly the files declared by the workspace manifest."
        )

    return WorkspaceInput(
        input_root=root,
        target_project=target_project,
        records=tuple(records),
    )


def _validate_root_shape(root: Path) -> None:
    entries = {path.name: path for path in root.iterdir()}
    if set(entries) != {WORKSPACE_FILENAME, RECORDS_DIRECTORY}:
        raise RawWorkspaceIngestionError(
            "Workspace input root must contain only workspace.json and records/."
        )
    manifest = entries[WORKSPACE_FILENAME]
    records = entries[RECORDS_DIRECTORY]
    if _is_unsafe_link(manifest) or not manifest.is_file():
        raise RawWorkspaceIngestionError("Workspace manifest must be a regular file.")
    if _is_unsafe_link(records) or not records.is_dir():
        raise RawWorkspaceIngestionError("Workspace records path must be a real directory.")
    for child in records.iterdir():
        if _is_unsafe_link(child) or not child.is_file():
            raise RawWorkspaceIngestionError("Workspace records must be regular files, not links or directories.")


def _validate_project(value: Any) -> ProjectReference:
    if not isinstance(value, dict) or set(value) != _PROJECT_FIELDS:
        raise RawWorkspaceIngestionError("Target project fields are missing or unexpected.")
    project_id = _canonical_nonempty_string(value.get("project_id"), "target project_id")
    name = _canonical_nonempty_string(value.get("name"), "target project name")
    return ProjectReference(project_id=project_id, name=name)


def _load_record(
    root: Path,
    value: Any,
    seen_evidence_ids: set[str],
    seen_paths: set[str],
) -> tuple[RawWorkspaceRecord, str]:
    if not isinstance(value, dict) or set(value) != _RECORD_FIELDS:
        raise RawWorkspaceIngestionError("Workspace record fields are missing or unexpected.")
    evidence_id = _canonical_nonempty_string(value.get("evidence_id"), "evidence_id")
    source_format = _canonical_nonempty_string(value.get("format"), "record format")
    relative_path = _canonical_nonempty_string(value.get("path"), "record path")
    sha256 = _canonical_nonempty_string(value.get("sha256"), "record sha256")

    evidence_key = evidence_id.casefold()
    if evidence_key in seen_evidence_ids:
        raise RawWorkspaceIngestionError(f"Duplicate evidence_id '{evidence_id}'.")
    seen_evidence_ids.add(evidence_key)

    if source_format not in SUPPORTED_FORMATS:
        raise RawWorkspaceIngestionError(f"Unsupported record format '{source_format}'.")
    if not _SHA256_PATTERN.fullmatch(sha256):
        raise RawWorkspaceIngestionError("Record sha256 must be lowercase hexadecimal.")

    posix_path = _validate_relative_record_path(relative_path, source_format)
    path_key = relative_path.casefold()
    if path_key in seen_paths:
        raise RawWorkspaceIngestionError(f"Duplicate record path '{relative_path}'.")
    seen_paths.add(path_key)

    resolved_path = (root / Path(*posix_path.parts)).resolve()
    if not resolved_path.is_relative_to(root):
        raise RawWorkspaceIngestionError(f"Record path '{relative_path}' escapes the input root.")
    if not resolved_path.is_file():
        raise RawWorkspaceIngestionError(f"Record file '{relative_path}' does not exist.")
    try:
        raw_bytes = resolved_path.read_bytes()
    except OSError as exc:
        raise RawWorkspaceIngestionError(f"Record file '{relative_path}' could not be read.") from exc
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha256 != sha256:
        raise RawWorkspaceIngestionError(f"Record checksum mismatch for '{relative_path}'.")
    content = _parse_content(source_format, raw_bytes, relative_path)
    return (
        RawWorkspaceRecord(
            evidence_id=evidence_id,
            relative_path=relative_path,
            source_format=source_format,
            sha256=sha256,
            content=content,
        ),
        posix_path.name,
    )


def _validate_relative_record_path(relative_path: str, source_format: str) -> PurePosixPath:
    if "\\" in relative_path:
        raise RawWorkspaceIngestionError("Record paths must use forward slashes.")
    windows_path = PureWindowsPath(relative_path)
    posix_path = PurePosixPath(relative_path)
    if windows_path.drive or windows_path.is_absolute() or posix_path.is_absolute():
        raise RawWorkspaceIngestionError("Record paths must be relative.")
    if len(posix_path.parts) != 2 or posix_path.parts[0] != RECORDS_DIRECTORY:
        raise RawWorkspaceIngestionError("Record paths must be direct children of records/.")
    if any(part in {"", ".", ".."} for part in posix_path.parts):
        raise RawWorkspaceIngestionError("Record paths cannot contain traversal components.")
    if posix_path.suffix != f".{source_format}":
        raise RawWorkspaceIngestionError("Record path extension must match its declared format.")
    return posix_path


def _parse_content(source_format: str, raw_bytes: bytes, relative_path: str) -> str:
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RawWorkspaceIngestionError(f"Record '{relative_path}' is not valid UTF-8.") from exc
    if source_format == "json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RawWorkspaceIngestionError(f"Record '{relative_path}' is malformed JSON.") from exc
        if not isinstance(payload, dict) or set(payload) != _JSON_RECORD_FIELDS:
            raise RawWorkspaceIngestionError(f"JSON record '{relative_path}' has an invalid schema.")
        if payload.get("schema_version") != 1:
            raise RawWorkspaceIngestionError(f"JSON record '{relative_path}' has an unsupported schema.")
        content = payload.get("content")
        if not isinstance(content, str):
            raise RawWorkspaceIngestionError(f"JSON record '{relative_path}' content must be text.")
    else:
        content = text
    normalized = _normalize_text(content)
    if not normalized:
        raise RawWorkspaceIngestionError(f"Record '{relative_path}' has no meaningful content.")
    return normalized


def _load_json_file(path: Path, label: str) -> Any:
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise RawWorkspaceIngestionError(f"{label} could not be read.") from exc
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RawWorkspaceIngestionError(f"{label} is not valid UTF-8.") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RawWorkspaceIngestionError(f"{label} is not valid JSON.") from exc


def _canonical_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RawWorkspaceIngestionError(f"{label} must be a canonical non-empty string.")
    return value


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()


def _is_unsafe_link(path: Path) -> bool:
    """Treat symbolic links and Windows directory junctions as unsafe input."""

    return path.is_symlink() or path.is_junction()
