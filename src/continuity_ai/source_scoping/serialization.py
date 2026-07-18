"""Strict serialization for encrypted persistence of approved source scopes."""
from __future__ import annotations

from typing import Any

from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.domain import (
    APPROVED_SOURCE_SCOPE_FIELDS,
    ASSOCIATION_STATUSES,
    DECISION_BASES,
    REVIEWED_SOURCE_DECISION_FIELDS,
    ApprovedSourceScope,
    ReviewedSourceDecision,
    SCHEMA_VERSION,
)

_SCOPE_KEYS = frozenset(APPROVED_SOURCE_SCOPE_FIELDS)
_DECISION_KEYS = frozenset(REVIEWED_SOURCE_DECISION_FIELDS)
_FINAL_STATUSES = frozenset({"included", "excluded"})
_ALLOWED_BASIS_BY_MODEL_STATUS = {
    "included": frozenset({"explicit_target", "corroborated_context"}),
    "excluded": frozenset(
        {"explicit_other_project", "corroborated_other_project"}
    ),
    "ambiguous": frozenset({"conflicting_context", "insufficient_context"}),
}


def _decision_to_payload(decision: ReviewedSourceDecision) -> dict[str, Any]:
    """Serialize exactly the frozen ReviewedSourceDecision contract."""
    return {
        field: getattr(decision, field)
        for field in REVIEWED_SOURCE_DECISION_FIELDS
    }


def approved_scope_to_payload(scope: ApprovedSourceScope) -> dict[str, Any]:
    """Serialize exactly the frozen ApprovedSourceScope persistence contract."""
    payload = {
        "schema_version": scope.schema_version,
        "scope_id": scope.scope_id,
        "target_project": scope.target_project,
        "reviewed_decisions": tuple(
            _decision_to_payload(decision)
            for decision in scope.reviewed_decisions
        ),
        "approved_evidence_ids": scope.approved_evidence_ids,
        "excluded_evidence_ids": scope.excluded_evidence_ids,
        "user_resolved_evidence_ids": scope.user_resolved_evidence_ids,
        "evidence_fingerprints": scope.evidence_fingerprints,
        "created_at": scope.created_at,
    }
    if set(payload) != _SCOPE_KEYS:
        raise ValidationError()
    return payload


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

        final_status = raw["final_status"]
        model_status = raw["model_status"]
        basis = raw["basis"]
        rationale = raw["rationale"]
        if final_status not in _FINAL_STATUSES:
            raise ValidationError()
        if model_status not in ASSOCIATION_STATUSES:
            raise ValidationError()
        if basis not in DECISION_BASES:
            raise ValidationError()
        if basis not in _ALLOWED_BASIS_BY_MODEL_STATUS[model_status]:
            raise ValidationError()
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValidationError()

        span_ids = _string_sequence(raw["span_ids"])
        related_evidence_ids = _string_sequence(raw["related_evidence_ids"])
        if evidence_id in related_evidence_ids:
            raise ValidationError()
        user_overridden = raw["user_overridden"]
        if not isinstance(user_overridden, bool):
            raise ValidationError()
        if model_status == "ambiguous" and not user_overridden:
            raise ValidationError()

        seen.add(evidence_id)
        decisions.append(
            ReviewedSourceDecision(
                evidence_id=evidence_id,
                final_status=final_status,
                model_status=model_status,
                basis=basis,
                rationale=rationale,
                span_ids=span_ids,
                related_evidence_ids=related_evidence_ids,
                user_overridden=user_overridden,
            )
        )

    if any(
        related not in seen
        for decision in decisions
        for related in decision.related_evidence_ids
    ):
        raise ValidationError()
    return tuple(decisions)


def _fingerprints(
    value: Any, evidence_ids: tuple[str, ...]
) -> tuple[tuple[str, str], ...]:
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
        or set(payload) != _SCOPE_KEYS
        or payload["schema_version"] != SCHEMA_VERSION
    ):
        raise ValidationError()
    for key in ("scope_id", "target_project", "created_at"):
        if (
            not isinstance(payload[key], str)
            or not payload[key].strip()
            or payload[key] != payload[key].strip()
        ):
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
