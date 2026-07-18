"""Strict serialization for encrypted persistence of approved source scopes."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.domain import (
    ASSOCIATION_STATUSES,
    DECISION_BASES,
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
    "model_status",
    "model_basis",
    "model_rationale",
    "span_ids",
    "related_evidence_ids",
    "final_status",
    "user_overridden",
}
_FINAL_STATUSES = frozenset({"included", "excluded"})
_ALLOWED_BASIS_BY_STATUS = {
    "included": {"explicit_target", "corroborated_context"},
    "excluded": {"explicit_other_project", "corroborated_other_project"},
    "ambiguous": {"conflicting_context", "insufficient_context"},
}
_CONTEXTUAL_BASES = {"corroborated_context", "corroborated_other_project"}
_EXPLICIT_BASES = {"explicit_target", "explicit_other_project"}


def approved_scope_to_payload(scope: ApprovedSourceScope) -> dict[str, Any]:
    return asdict(scope)


def _string_sequence(value: Any, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValidationError()
    result = tuple(value)
    if not allow_empty and not result:
        raise ValidationError()
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
        status = raw["model_status"]
        basis = raw["model_basis"]
        rationale = raw["model_rationale"]
        if not isinstance(evidence_id, str) or not evidence_id or evidence_id in seen:
            raise ValidationError()
        if status not in ASSOCIATION_STATUSES or basis not in DECISION_BASES:
            raise ValidationError()
        if basis not in _ALLOWED_BASIS_BY_STATUS[status]:
            raise ValidationError()
        if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 1000:
            raise ValidationError()
        span_ids = _string_sequence(raw["span_ids"], allow_empty=False)
        related = _string_sequence(raw["related_evidence_ids"])
        if basis in _CONTEXTUAL_BASES and not related:
            raise ValidationError()
        if basis in _EXPLICIT_BASES and related:
            raise ValidationError()
        if raw["final_status"] not in _FINAL_STATUSES:
            raise ValidationError()
        if not isinstance(raw["user_overridden"], bool):
            raise ValidationError()
        if status == "ambiguous" and not raw["user_overridden"]:
            raise ValidationError()
        seen.add(evidence_id)
        decisions.append(
            ReviewedSourceDecision(
                evidence_id=evidence_id,
                model_status=status,
                model_basis=basis,
                model_rationale=rationale,
                span_ids=span_ids,
                related_evidence_ids=related,
                final_status=raw["final_status"],
                user_overridden=raw["user_overridden"],
            )
        )
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
    scope_id = payload["scope_id"]
    target_project = payload["target_project"]
    created_at = payload["created_at"]
    if not isinstance(scope_id, str) or not scope_id.strip():
        raise ValidationError()
    if (
        not isinstance(target_project, str)
        or not target_project.strip()
        or target_project != target_project.strip()
    ):
        raise ValidationError()
    if not isinstance(created_at, str) or not created_at.strip():
        raise ValidationError()
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError() from None

    reviewed = _reviewed_decisions(payload["reviewed_decisions"])
    evidence_ids = tuple(decision.evidence_id for decision in reviewed)
    evidence_id_set = set(evidence_ids)
    if any(
        related not in evidence_id_set or related == decision.evidence_id
        for decision in reviewed
        for related in decision.related_evidence_ids
    ):
        raise ValidationError()

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
        scope_id=scope_id,
        target_project=target_project,
        reviewed_decisions=reviewed,
        approved_evidence_ids=approved,
        excluded_evidence_ids=excluded,
        user_resolved_evidence_ids=resolved,
        evidence_fingerprints=fingerprints,
        created_at=created_at,
    )
