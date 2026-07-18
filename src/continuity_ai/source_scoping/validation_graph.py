"""Graph reachability rules for contextual source-scoping decisions."""
from __future__ import annotations

from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.domain import SourceScopingDecision


def _has_path_to_anchor(
    evidence_id: str,
    decisions: dict[str, SourceScopingDecision],
    anchor_basis: str,
    permitted_status: str,
    visiting: set[str],
) -> bool:
    if evidence_id in visiting:
        return False
    decision = decisions[evidence_id]
    if decision.basis == anchor_basis:
        return True
    if decision.association_status != permitted_status:
        return False
    next_visiting = visiting | {evidence_id}
    return any(
        related in decisions
        and decisions[related].association_status == permitted_status
        and _has_path_to_anchor(
            related, decisions, anchor_basis, permitted_status, next_visiting
        )
        for related in decision.related_evidence_ids
    )


def validate_context_graph(decisions: tuple[SourceScopingDecision, ...]) -> None:
    by_id = {decision.evidence_id: decision for decision in decisions}
    for decision in decisions:
        if decision.basis == "corroborated_context" and not _has_path_to_anchor(
            decision.evidence_id, by_id, "explicit_target", "included", set()
        ):
            raise ValidationError()
        if decision.basis == "corroborated_other_project" and not _has_path_to_anchor(
            decision.evidence_id, by_id, "explicit_other_project", "excluded", set()
        ):
            raise ValidationError()
