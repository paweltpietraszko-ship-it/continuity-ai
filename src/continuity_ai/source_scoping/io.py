"""Neutral JSON workspace loading for CLI and tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from continuity_ai.domain import ReasoningEvidence
from continuity_ai.errors import ValidationError

_WORKSPACE_KEYS = {"schema_version", "target_project", "evidence_records"}
_RECORD_KEYS = {
    "evidence_id",
    "source_type",
    "author_or_actor",
    "timestamp",
    "title",
    "content",
    "uri",
    "artifact_sha256",
}


def load_workspace(path: Path) -> tuple[str, tuple[ReasoningEvidence, ...]]:
    workspace_path = path / "workspace.json" if path.is_dir() else path
    try:
        payload: Any = json.loads(workspace_path.read_text("utf-8"))
    except Exception:
        raise ValidationError() from None
    if (
        not isinstance(payload, dict)
        or set(payload) != _WORKSPACE_KEYS
        or payload["schema_version"] != "1.0"
    ):
        raise ValidationError()
    target = payload["target_project"]
    if (
        not isinstance(target, str)
        or not target.strip()
        or target != target.strip()
    ):
        raise ValidationError()
    raw_records = payload["evidence_records"]
    if not isinstance(raw_records, list) or not raw_records:
        raise ValidationError()
    records: list[ReasoningEvidence] = []
    try:
        for raw in raw_records:
            if not isinstance(raw, dict) or set(raw) != _RECORD_KEYS:
                raise ValidationError()
            records.append(
                ReasoningEvidence(
                    evidence_id=raw["evidence_id"],
                    source_type=raw["source_type"],
                    author_or_actor=raw["author_or_actor"],
                    timestamp=raw["timestamp"],
                    title=raw["title"],
                    content=raw["content"],
                    provenance="artifact",
                    uri=raw["uri"],
                    artifact_sha256=raw["artifact_sha256"],
                )
            )
    except (KeyError, TypeError, ValueError):
        raise ValidationError() from None
    return target, tuple(records)
