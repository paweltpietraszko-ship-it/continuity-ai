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

REVIEWED_SOURCE_DECISION_FIELDS: tuple[str, ...] = (
    "evidence_id",
    "final_status",
    "model_status",
    "basis",
    "rationale",
    "span_ids",
    "related_evidence_ids",
    "user_overridden",
)
APPROVED_SOURCE_SCOPE_FIELDS: tuple[str, ...] = (
    "schema_version",
    "scope_id",
    "target_project",
    "reviewed_decisions",
    "approved_evidence_ids",
    "excluded_evidence_ids",
    "user_resolved_evidence_ids",
    "evidence_fingerprints",
    "created_at",
)


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
    final_status: FinalAssociationStatus
    model_status: AssociationStatus
    basis: DecisionBasis
    rationale: str
    span_ids: tuple[str, ...]
    related_evidence_ids: tuple[str, ...]
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
