"""Stable reasoning orchestration and validation import surface."""
from __future__ import annotations

import uuid

from continuity_ai.analysis_validation import (
    BREAK_KINDS,
    ROLES,
    STATUSES,
    _grounded_statement,
    validate_analysis,
    validate_analysis_payload,
)
from continuity_ai.deterministic_offline_provider import (
    DeterministicOfflineReasoningProvider,
)
from continuity_ai.domain import (
    AnalysisResult,
    EvidenceSnapshot,
    EvidenceSpan,
    ReasoningEvidence,
)
from continuity_ai.evidence import build_spans, make_snapshot
from continuity_ai.reasoning_contract import (
    EVIDENCE_GAP_HEADLINE,
    SUPPORTED_SCHEMA_VERSION,
    ReasoningProvider,
)


__all__ = [
    "BREAK_KINDS",
    "DeterministicOfflineReasoningProvider",
    "EVIDENCE_GAP_HEADLINE",
    "ROLES",
    "ReasoningProvider",
    "STATUSES",
    "SUPPORTED_SCHEMA_VERSION",
    "run_analysis",
    "validate_analysis",
    "validate_analysis_payload",
]


def run_analysis(
    records: tuple[ReasoningEvidence, ...],
    question: str,
    provider: ReasoningProvider,
) -> tuple[AnalysisResult, tuple[EvidenceSpan, ...], EvidenceSnapshot]:
    """Run one provider call, validate it, and bind its evidence snapshot."""
    spans = build_spans(records)
    candidate = provider.analyze(records, spans, question)
    result = validate_analysis(candidate, records, spans)
    snapshot = make_snapshot(
        "AN-" + uuid.uuid4().hex,
        records,
        spans,
        "g03_reasoning_v3",
        SUPPORTED_SCHEMA_VERSION,
        provider.provider_id,
    )
    return result, spans, snapshot
