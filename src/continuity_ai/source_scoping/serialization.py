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
_FINAL_STATUSES = frozenset({"included", "excluded"})
_MODEL_STATUSES = frozenset({"included", "excluded", "ambiguous"})


def approved_scope_to_payload(scope: ApprovedSourceScope) -> dict[str, Any]:
    return asdict(scope)


def _string_sequence(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValidationError()
    result = tuple(value)
    if not all(isinstance(item, str) and item for item in result):
        raise ValidationError()
    if len(set(result)) != len(result):
        raise ValidationError()
    return result


def _reviewed_decisions(value: Any) -> tuple[ReviewedSourceDecision, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValidationError()
    decisions: list[ReviewedSourceDecision] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != _DECISION_KEYS:
            raise ValidationError()
        evidence_id = raw["evidence_id"]
        if not isinstance(evidence_id, str) or not evidence_id or evidence_id in seen:
            raise ValidationError()
        if raw["final_status"] not in _FINAL_STATUSES:
            raise ValidationError()
        if raw["model_status"] not in _MODEL_STATUSES:
            raise ValidationError()
        if not isinstance(raw["user_overridden"], bool):
            raise ValidationError()
        if raw["model_status"] == "ambiguous" and not raw["user_overridden"]:
            raise ValidationError()
        seen.add(evidence_id)
        decisions.append(ReviewedSourceDecision(**raw))
    return tuple(decisions)


def _fingerprints(value: Any, evidence_ids: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValidationError()
    pairs: list[tuple[str, str]] = []
    for raw in value:
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raise ValidationError()
        evidence_id, digest = raw
        if (
            not isinstance(evidence_id, str)
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise ValidationError()
        try:
            int(digest, 16)
        except ValueError:
            raise ValidationError() from None
        pairs.append((evidence_id, digest))
    result = tuple(pairs)
    if tuple(evidence_id for evidence_id, _ in result) != evidence_ids:
        raise ValidationError()
    return result


def approved_scope_from_payload(payload: Any) -> ApprovedSourceScope:
    if (
        not isinstance(payload, dict)
        or set(payload) != _KEYS
        or payload["schema_version"] != SCHEMA_VERSION
    ):
        raise ValidationError()
    for key in ("scope_id", "target_project", "created_at"):
        if not isinstance(payload[key], str) or not payload[key].strip():
            raise ValidationError()

    reviewed = _reviewed_decisions(payload["reviewed_decisions"])
    evidence_ids = tuple(decision.evidence_id for decision in reviewed)
    approved = _string_sequence(payload["approved_evidence_ids"])
    excluded = _string_sequence(payload["excluded_evidence_ids"])
    resolved = _string_sequence(payload["user_resolved_evidence_ids"])
    fingerprints = _fingerprints(payload["evidence_fingerprints"], evidence_ids)

    expected_approved = tuple(
        decision.evidence_id
        for decision in reviewed
        if decision.final_status == "included"
    )
    expected_excluded = tuple(
        decision.evidence_id
        for decision in reviewed
        if decision.final_status == "excluded"
    )
    expected_resolved = tuple(
        decision.evidence_id
        for decision in reviewed
        if decision.model_status == "ambiguous"
    )
    if approved != expected_approved or excluded != expected_excluded:
        raise ValidationError()
    if resolved != expected_resolved:
        raise ValidationError()

    return ApprovedSourceScope(
        schema_version=SCHEMA_VERSION,
        scope_id=payload["scope_id"],
        target_project=payload["target_project"],
        reviewed_decisions=reviewed,
        approved_evidence_ids=approved,
        excluded_evidence_ids=excluded,
        user_resolved_evidence_ids=resolved,
        evidence_fingerprints=fingerprints,
        created_at=payload["created_at"],
    )
