"""Shared semantic and graph rules for source-scoping decisions."""
from __future__ import annotations

from typing import Any

from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.domain import ASSOCIATION_STATUSES, DECISION_BASES

_ALLOWED_BASIS_BY_STATUS = {
    "included": frozenset({"explicit_target", "corroborated_context"}),
    "excluded": frozenset(
        {"explicit_other_project", "corroborated_other_project"}
    ),
    "ambiguous": frozenset({"conflicting_context", "insufficient_context"}),
}
_CONTEXTUAL_BASES = frozenset(
    {"corroborated_context", "corroborated_other_project"}
)
_EXPLICIT_BASES = frozenset({"explicit_target", "explicit_other_project"})


def validate_decision_relations(
    status: str,
    basis: str,
    related_evidence_ids: tuple[str, ...],
) -> None:
    """Apply the canonical status/basis and relation-cardinality rules."""
    if status not in ASSOCIATION_STATUSES or basis not in DECISION_BASES:
        raise ValidationError()
    if basis not in _ALLOWED_BASIS_BY_STATUS[status]:
        raise ValidationError()
    if basis in _CONTEXTUAL_BASES and not related_evidence_ids:
        raise ValidationError()
    if basis in _EXPLICIT_BASES and related_evidence_ids:
        raise ValidationError()


def _decision_status(decision: Any) -> str:
    if hasattr(decision, "association_status"):
        return decision.association_status
    if hasattr(decision, "model_status"):
        return decision.model_status
    raise ValidationError()


def _has_path_to_anchor(
    evidence_id: str,
    decisions: dict[str, Any],
    anchor_basis: str,
    permitted_status: str,
    visiting: set[str],
) -> bool:
    if evidence_id in visiting:
        return False
    decision = decisions[evidence_id]
    if decision.basis == anchor_basis:
        return True
    if _decision_status(decision) != permitted_status:
        return False
    next_visiting = visiting | {evidence_id}
    return any(
        related in decisions
        and _decision_status(decisions[related]) == permitted_status
        and _has_path_to_anchor(
            related, decisions, anchor_basis, permitted_status, next_visiting
        )
        for related in decision.related_evidence_ids
    )


def validate_context_graph(decisions: tuple[Any, ...]) -> None:
    """Require every contextual model decision to reach an explicit anchor."""
    by_id = {decision.evidence_id: decision for decision in decisions}
    for decision in decisions:
        if decision.basis == "corroborated_context" and not _has_path_to_anchor(
            decision.evidence_id, by_id, "explicit_target", "included", set()
        ):
            raise ValidationError()
        if decision.basis == "corroborated_other_project" and not _has_path_to_anchor(
            decision.evidence_id,
            by_id,
            "explicit_other_project",
            "excluded",
            set(),
        ):
            raise ValidationError()
