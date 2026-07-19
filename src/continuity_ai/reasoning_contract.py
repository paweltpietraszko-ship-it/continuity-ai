"""Typed contracts shared by reasoning providers and canonical validation."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping, Protocol, TypedDict

from continuity_ai.domain import (
    BreakKind,
    EvidenceSpan,
    ProjectReportSectionName,
    ReasoningEvidence,
    Role,
    Status,
)


SUPPORTED_SCHEMA_VERSION = "3.0"
EVIDENCE_GAP_HEADLINE = "No verified status available"


class GroundedStatementCandidate(TypedDict):
    statement: str
    span_ids: list[str]


class SemanticAnnotationCandidate(TypedDict):
    evidence_id: str
    propagation_role: Role
    context_tags: list[Literal["urgency"]]


class ProjectReportSectionCandidate(TypedDict):
    key: ProjectReportSectionName
    status: Literal["confirmed", "attention", "evidence_gap", "not_applicable"]
    headline: str
    detail: str
    span_ids: list[str]


class ProjectReportCandidate(TypedDict):
    summary: GroundedStatementCandidate
    sections: list[ProjectReportSectionCandidate]


class AnalysisCandidate(TypedDict):
    schema_version: str
    analysis_status: Status
    continuity_break_kind: BreakKind | None
    current_state: GroundedStatementCandidate
    semantic_annotations: list[SemanticAnnotationCandidate]
    continuity_break: GroundedStatementCandidate | None
    next_action: GroundedStatementCandidate | None
    project_report: ProjectReportCandidate


class ReasoningProvider(Protocol):
    provider_id: str

    def analyze(
        self,
        evidence: tuple[ReasoningEvidence, ...],
        spans: tuple[EvidenceSpan, ...],
        question: str,
    ) -> AnalysisCandidate: ...


class GroundingInputError(ValueError):
    """Raised when evidence/span identity cannot form a safe grounding index."""


@dataclass(frozen=True)
class GroundingIndex:
    """Identity-only grounding view; no semantic role is derived here."""

    evidence_ids: tuple[str, ...]
    span_ids_by_evidence: Mapping[str, tuple[str, ...]]
    span_owner: Mapping[str, str]


def evidence_gap_detail(section_key: str) -> str:
    return (
        "No available project source establishes the current "
        f"{section_key} status."
    )


def evidence_gap_section(
    section_key: ProjectReportSectionName,
) -> ProjectReportSectionCandidate:
    """Build the one canonical schema representation of a report evidence gap."""
    return {
        "key": section_key,
        "status": "evidence_gap",
        "headline": EVIDENCE_GAP_HEADLINE,
        "detail": evidence_gap_detail(section_key),
        "span_ids": [],
    }


def build_grounding_index(
    evidence: object,
    spans: object,
) -> GroundingIndex:
    """Validate identity and ownership once for all local reasoning boundaries.

    Every evidence record must own at least one span. Duplicate identities and
    foreign spans are rejected because either condition makes citations
    ambiguous even if a later payload happens to reference only a safe subset.
    """
    if not isinstance(evidence, (list, tuple)) or not isinstance(
        spans, (list, tuple)
    ):
        raise GroundingInputError()

    evidence_by_id: dict[str, ReasoningEvidence] = {}
    for record in evidence:
        if not isinstance(record, ReasoningEvidence):
            raise GroundingInputError()
        evidence_id = record.evidence_id
        if not evidence_id.strip() or evidence_id in evidence_by_id:
            raise GroundingInputError()
        evidence_by_id[evidence_id] = record
    if not evidence_by_id:
        raise GroundingInputError()

    spans_by_evidence: dict[str, list[str]] = {
        evidence_id: [] for evidence_id in evidence_by_id
    }
    span_owner: dict[str, str] = {}
    for span in spans:
        if not isinstance(span, EvidenceSpan):
            raise GroundingInputError()
        if (
            not span.span_id.strip()
            or span.span_id in span_owner
            or span.evidence_id not in evidence_by_id
        ):
            raise GroundingInputError()
        span_owner[span.span_id] = span.evidence_id
        spans_by_evidence[span.evidence_id].append(span.span_id)

    if any(not owned_spans for owned_spans in spans_by_evidence.values()):
        raise GroundingInputError()

    ordered_evidence_ids = tuple(sorted(evidence_by_id))
    immutable_spans = {
        evidence_id: tuple(sorted(spans_by_evidence[evidence_id]))
        for evidence_id in ordered_evidence_ids
    }
    return GroundingIndex(
        evidence_ids=ordered_evidence_ids,
        span_ids_by_evidence=MappingProxyType(immutable_spans),
        span_owner=MappingProxyType(dict(sorted(span_owner.items()))),
    )
