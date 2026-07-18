"""Validation of restored approved scopes against authoritative live evidence."""
from __future__ import annotations

from typing import Any

from continuity_ai.errors import ValidationError
from continuity_ai.evidence import build_spans
from continuity_ai.source_scoping.domain import (
    ApprovedSourceScope,
    SourceScopingDecision,
)
from continuity_ai.source_scoping.fingerprints import evidence_fingerprint
from continuity_ai.source_scoping.validation_graph import validate_context_graph

_ALLOWED_BASIS_BY_STATUS = {
    "included": {"explicit_target", "corroborated_context"},
    "excluded": {"explicit_other_project", "corroborated_other_project"},
    "ambiguous": {"conflicting_context", "insufficient_context"},
}
_CONTEXTUAL_BASES = {"corroborated_context", "corroborated_other_project"}
_EXPLICIT_BASES = {"explicit_target", "explicit_other_project"}


def validate_approved_scope_against_evidence(
    scope: ApprovedSourceScope,
    evidence: tuple[Any, ...],
) -> None:
    evidence_ids = tuple(record.evidence_id for record in evidence)
    reviewed_ids = tuple(
        decision.evidence_id for decision in scope.reviewed_decisions
    )
    if evidence_ids != reviewed_ids:
        raise ValidationError()

    live_fingerprints = tuple(
        (record.evidence_id, evidence_fingerprint(record)) for record in evidence
    )
    if live_fingerprints != scope.evidence_fingerprints:
        raise ValidationError()

    span_owner = {
        span.span_id: span.evidence_id for span in build_spans(evidence)
    }
    evidence_id_set = set(evidence_ids)
    model_decisions: list[SourceScopingDecision] = []
    for reviewed in scope.reviewed_decisions:
        if reviewed.model_basis not in _ALLOWED_BASIS_BY_STATUS[reviewed.model_status]:
            raise ValidationError()
        if not reviewed.model_rationale.strip():
            raise ValidationError()
        if not reviewed.span_ids or len(set(reviewed.span_ids)) != len(reviewed.span_ids):
            raise ValidationError()
        if any(
            span_owner.get(span_id) != reviewed.evidence_id
            for span_id in reviewed.span_ids
        ):
            raise ValidationError()
        if len(set(reviewed.related_evidence_ids)) != len(
            reviewed.related_evidence_ids
        ):
            raise ValidationError()
        if any(
            related not in evidence_id_set or related == reviewed.evidence_id
            for related in reviewed.related_evidence_ids
        ):
            raise ValidationError()
        if reviewed.model_basis in _CONTEXTUAL_BASES and not reviewed.related_evidence_ids:
            raise ValidationError()
        if reviewed.model_basis in _EXPLICIT_BASES and reviewed.related_evidence_ids:
            raise ValidationError()
        model_decisions.append(
            SourceScopingDecision(
                evidence_id=reviewed.evidence_id,
                association_status=reviewed.model_status,
                basis=reviewed.model_basis,
                rationale=reviewed.model_rationale,
                span_ids=reviewed.span_ids,
                related_evidence_ids=reviewed.related_evidence_ids,
            )
        )
    validate_context_graph(tuple(model_decisions))
