"""Canonical fail-closed validator for source-scoping provider output."""
from __future__ import annotations

from typing import Any

from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.domain import (
    ASSOCIATION_STATUSES,
    DECISION_BASES,
    SCHEMA_VERSION,
    SourceScopingDecision,
    SourceScopingResult,
)
from continuity_ai.source_scoping.validation_graph import validate_context_graph

_RESULT_KEYS = {
    "schema_version",
    "target_project",
    "anchor_evidence_ids",
    "decisions",
    "selected_evidence_ids",
    "ambiguous_evidence_ids",
    "excluded_evidence_ids",
}
_DECISION_KEYS = {
    "evidence_id",
    "association_status",
    "basis",
    "rationale",
    "span_ids",
    "related_evidence_ids",
}
_ALLOWED_BASIS_BY_STATUS = {
    "included": {"explicit_target", "corroborated_context"},
    "excluded": {"explicit_other_project", "corroborated_other_project"},
    "ambiguous": {"conflicting_context", "insufficient_context"},
}
_CONTEXTUAL_BASES = {"corroborated_context", "corroborated_other_project"}
_EXPLICIT_BASES = {"explicit_target", "explicit_other_project"}


def _canonical_project(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValidationError()
    return value


def _ordered_string_list(value: Any, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValidationError()
    if not allow_empty and not value:
        raise ValidationError()
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValidationError()
    if len(set(value)) != len(value):
        raise ValidationError()
    return tuple(value)


def _validate_authoritative_inputs(
    evidence: tuple[Any, ...], spans: tuple[Any, ...]
) -> tuple[tuple[str, ...], dict[str, str]]:
    evidence_ids = tuple(item.evidence_id for item in evidence)
    if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
        raise ValidationError()
    if any(
        not isinstance(evidence_id, str) or not evidence_id.strip()
        for evidence_id in evidence_ids
    ):
        raise ValidationError()

    evidence_id_set = set(evidence_ids)
    span_owner: dict[str, str] = {}
    for span in spans:
        span_id = span.span_id
        owner = span.evidence_id
        if (
            not isinstance(span_id, str)
            or not span_id.strip()
            or span_id in span_owner
            or owner not in evidence_id_set
        ):
            raise ValidationError()
        span_owner[span_id] = owner
    if not span_owner:
        raise ValidationError()
    return evidence_ids, span_owner


def _decision_from_payload(
    payload: Any,
    expected_evidence_id: str,
    evidence_id_set: set[str],
    span_owner: dict[str, str],
) -> SourceScopingDecision:
    if not isinstance(payload, dict) or set(payload) != _DECISION_KEYS:
        raise ValidationError()
    if payload["evidence_id"] != expected_evidence_id:
        raise ValidationError()

    status = payload["association_status"]
    basis = payload["basis"]
    if status not in ASSOCIATION_STATUSES or basis not in DECISION_BASES:
        raise ValidationError()
    if basis not in _ALLOWED_BASIS_BY_STATUS[status]:
        raise ValidationError()

    rationale = payload["rationale"]
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 1000:
        raise ValidationError()

    span_ids = _ordered_string_list(payload["span_ids"], allow_empty=False)
    if any(span_owner.get(span_id) != expected_evidence_id for span_id in span_ids):
        raise ValidationError()

    related = _ordered_string_list(payload["related_evidence_ids"])
    if any(
        evidence_id not in evidence_id_set or evidence_id == expected_evidence_id
        for evidence_id in related
    ):
        raise ValidationError()
    if basis in _CONTEXTUAL_BASES and not related:
        raise ValidationError()
    if basis in _EXPLICIT_BASES and related:
        raise ValidationError()

    return SourceScopingDecision(
        evidence_id=expected_evidence_id,
        association_status=status,
        basis=basis,
        rationale=rationale,
        span_ids=span_ids,
        related_evidence_ids=related,
    )


def validate_source_scoping_payload(
    candidate: Any,
    target_project: str,
    evidence: tuple[Any, ...],
    spans: tuple[Any, ...],
) -> SourceScopingResult:
    """Validate one complete provider result against authoritative input identity."""
    authoritative_target = _canonical_project(target_project)
    evidence_ids, span_owner = _validate_authoritative_inputs(evidence, spans)
    evidence_id_set = set(evidence_ids)

    if not isinstance(candidate, dict) or set(candidate) != _RESULT_KEYS:
        raise ValidationError()
    if candidate["schema_version"] != SCHEMA_VERSION:
        raise ValidationError()
    if candidate["target_project"] != authoritative_target:
        raise ValidationError()

    raw_decisions = candidate["decisions"]
    if not isinstance(raw_decisions, list) or len(raw_decisions) != len(evidence_ids):
        raise ValidationError()
    decisions = tuple(
        _decision_from_payload(raw, expected_id, evidence_id_set, span_owner)
        for raw, expected_id in zip(raw_decisions, evidence_ids)
    )
    validate_context_graph(decisions)

    anchors = _ordered_string_list(candidate["anchor_evidence_ids"])
    selected = _ordered_string_list(candidate["selected_evidence_ids"])
    ambiguous = _ordered_string_list(candidate["ambiguous_evidence_ids"])
    excluded = _ordered_string_list(candidate["excluded_evidence_ids"])

    expected_anchors = tuple(
        decision.evidence_id
        for decision in decisions
        if decision.basis == "explicit_target"
    )
    expected_selected = tuple(
        decision.evidence_id
        for decision in decisions
        if decision.association_status == "included"
    )
    expected_ambiguous = tuple(
        decision.evidence_id
        for decision in decisions
        if decision.association_status == "ambiguous"
    )
    expected_excluded = tuple(
        decision.evidence_id
        for decision in decisions
        if decision.association_status == "excluded"
    )
    if anchors != expected_anchors:
        raise ValidationError()
    if (
        selected != expected_selected
        or ambiguous != expected_ambiguous
        or excluded != expected_excluded
    ):
        raise ValidationError()
    if set(selected) | set(ambiguous) | set(excluded) != evidence_id_set:
        raise ValidationError()
    if (
        set(selected) & set(ambiguous)
        or set(selected) & set(excluded)
        or set(ambiguous) & set(excluded)
    ):
        raise ValidationError()

    return SourceScopingResult(
        schema_version=SCHEMA_VERSION,
        target_project=authoritative_target,
        anchor_evidence_ids=anchors,
        decisions=decisions,
        selected_evidence_ids=selected,
        ambiguous_evidence_ids=ambiguous,
        excluded_evidence_ids=excluded,
    )
