"""Shared fail-closed validation primitives for unseen-workspace boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from continuity_ai.unseen_workspace.models import ProjectReference, ScopeStatus


def is_unsafe_link(path: Path) -> bool:
    """Return whether a path is a symbolic link or Windows directory junction."""

    return path.is_symlink() or path.is_junction()


def load_utf8_json(path: Path, label: str, error_type: type[RuntimeError]) -> Any:
    """Load strict UTF-8 JSON while preserving the boundary's public error type."""

    try:
        raw_bytes = Path(path).read_bytes()
    except OSError as exc:
        raise error_type(f"{label} could not be read.") from exc
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise error_type(f"{label} is not valid UTF-8.") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise error_type(f"{label} is not valid JSON.") from exc


def require_exact_object(
    value: Any,
    fields: set[str],
    label: str,
    error_type: type[RuntimeError],
) -> dict[str, Any]:
    """Require an object with exactly the declared fields, rejecting schema drift."""

    if not isinstance(value, dict) or set(value) != fields:
        raise error_type(f"{label} fields are missing or unexpected.")
    return value


def canonical_nonempty_string(
    value: Any,
    label: str,
    error_type: type[RuntimeError],
) -> str:
    """Return canonical text or fail rather than silently trimming identity data."""

    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise error_type(f"{label} must be a canonical non-empty string.")
    return value


def parse_scope_status(
    value: Any,
    label: str,
    error_type: type[RuntimeError],
) -> ScopeStatus:
    """Parse the shared include/exclude/defer vocabulary."""

    if not isinstance(value, str):
        raise error_type(f"{label} must be a string.")
    try:
        return ScopeStatus(value)
    except ValueError as exc:
        raise error_type(f"{label} '{value}' is unsupported.") from exc


def parse_project_reference(
    value: Any,
    label: str,
    error_type: type[RuntimeError],
) -> ProjectReference:
    """Parse the one shared target-project identity contract."""

    payload = require_exact_object(
        value,
        {"project_id", "name"},
        label,
        error_type,
    )
    return ProjectReference(
        project_id=canonical_nonempty_string(
            payload.get("project_id"), f"{label} project_id", error_type
        ),
        name=canonical_nonempty_string(payload.get("name"), f"{label} name", error_type),
    )


def parse_identity_array(
    value: Any,
    label: str,
    error_type: type[RuntimeError],
) -> tuple[str, ...]:
    """Parse an identity array while retaining duplicates for evaluator proof."""

    if not isinstance(value, list):
        raise error_type(f"{label} must be an array.")
    return tuple(
        canonical_nonempty_string(item, f"{label} item", error_type) for item in value
    )
