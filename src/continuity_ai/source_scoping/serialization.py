"""Strict serialization for encrypted persistence of approved source scopes."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.domain import (
    ApprovedSourceScope,
    ReviewedSourceDecision,
    SCHEMA_VERSION,
)

_KEYS = {
    "schema_version",
    "scope_id",
    "target_project",
    "reviewed_decisions",
    "approved_evidence_ids",
    "excluded_evidence_ids",
    "user_resolved_evidence_ids",
    "evidence_fingerprints",
    "created_at",
}
_DECISION_KEYS = {
    "evidence_id",
    "final_status",
    "model_status",
    "user_overridden",
}


def approved_scope_to_payload(scope: ApprovedSourceScope) -> dict[str, Any]:
    return asdict(scope)


def approved_scope_from_payload(payload: Any) -> ApprovedSourceScope:
    if (
        not isinstance(payload, dict)
        or set(payload) != _KEYS
        or payload["schema_version"] != SCHEMA_VERSION
    ):
        raise ValidationError()
    reviewed: list[ReviewedSourceDecision] = []
    seen: set[str] = set()
    for raw in payload["reviewed_decisions"]:
        if not isinstance(raw, dict) or set(raw) != _DECISION_KEYS:
            raise ValidationError()
        if (
            raw["evidence_id"] in seen
            or raw["final_status"] not in {"included", "excluded"}
        ):
            raise ValidationError()
        if (
            raw["model_status"] not in {"included", "excluded", "ambiguous"}
            or not isinstance(raw["user_overridden"], bool)
        ):
            raise ValidationError()
        seen.add(raw["evidence_id"])
        reviewed.append(ReviewedSourceDecision(**raw))

    approved = tuple(payload["approved_evidence_ids"])
    excluded = tuple(payload["excluded_evidence_ids"])
    resolved = tuple(payload["user_resolved_evidence_ids"])
    fingerprints = tuple(tuple(pair) for pair in payload["evidence_fingerprints"])
    if set(approved) | set(excluded) != seen or set(approved) & set(excluded):
        raise ValidationError()
    if len(fingerprints) != len(seen) or {item[0] for item in fingerprints} != seen:
        raise ValidationError()
    if any(
        len(pair) != 2
        or not all(isinstance(value, str) and value for value in pair)
        for pair in fingerprints
    ):
        raise ValidationError()
    if not set(resolved) <= seen:
        raise ValidationError()
    for key in ("scope_id", "target_project", "created_at"):
        if not isinstance(payload[key], str) or not payload[key].strip():
            raise ValidationError()

    return ApprovedSourceScope(
        schema_version=SCHEMA_VERSION,
        scope_id=payload["scope_id"],
        target_project=payload["target_project"],
        reviewed_decisions=tuple(reviewed),
        approved_evidence_ids=approved,
        excluded_evidence_ids=excluded,
        user_resolved_evidence_ids=resolved,
        evidence_fingerprints=fingerprints,
        created_at=payload["created_at"],
    )
