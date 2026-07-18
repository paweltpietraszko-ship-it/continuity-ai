"""Immutable domain models for project source scoping and human review."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AssociationStatus = Literal["included", "excluded", "ambiguous"]
DecisionBasis = Literal[
    "explicit_target",
    "corroborated_context",
    "explicit_other_project",
    "corroborated_other_project",
    "conflicting_context",
    "insufficient_context",
]
FinalAssociationStatus = Literal["included", "excluded"]

SCHEMA_VERSION = "1.0"
ASSOCIATION_STATUSES = frozenset({"included", "excluded", "ambiguous"})
DECISION_BASES = frozenset({
    "explicit_target",
    "corroborated_context",
    "explicit_other_project",
    "corroborated_other_project",
    "conflicting_context",
    "insufficient_context",
})


@dataclass(frozen=True)
class SourceScopingDecision:
    evidence_id: str
    association_status: AssociationStatus
    basis: DecisionBasis
    rationale: str
    span_ids: tuple[str, ...]
    related_evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceScopingResult:
    schema_version: str
    target_project: str
    anchor_evidence_ids: tuple[str, ...]
    decisions: tuple[SourceScopingDecision, ...]
    selected_evidence_ids: tuple[str, ...]
    ambiguous_evidence_ids: tuple[str, ...]
    excluded_evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReviewedSourceDecision:
    evidence_id: str
    model_status: AssociationStatus
    model_basis: DecisionBasis
    model_rationale: str
    span_ids: tuple[str, ...]
    related_evidence_ids: tuple[str, ...]
    final_status: FinalAssociationStatus
    user_overridden: bool


@dataclass(frozen=True)
class ApprovedSourceScope:
    schema_version: str
    scope_id: str
    target_project: str
    reviewed_decisions: tuple[ReviewedSourceDecision, ...]
    approved_evidence_ids: tuple[str, ...]
    excluded_evidence_ids: tuple[str, ...]
    user_resolved_evidence_ids: tuple[str, ...]
    evidence_fingerprints: tuple[tuple[str, str], ...]
    created_at: str
