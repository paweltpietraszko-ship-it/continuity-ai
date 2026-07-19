"""Deterministic non-semantic reasoning provider for tests and offline fallback."""
from __future__ import annotations

from continuity_ai.domain import (
    PROJECT_REPORT_SECTION_NAMES,
    EvidenceSpan,
    ReasoningEvidence,
)
from continuity_ai.errors import ProviderError
from continuity_ai.reasoning_contract import (
    AnalysisCandidate,
    GroundingInputError,
    ProjectReportSectionCandidate,
    SemanticAnnotationCandidate,
    SUPPORTED_SCHEMA_VERSION,
    build_grounding_index,
    evidence_gap_section,
)


class DeterministicOfflineReasoningProvider:
    """Conservative provider for tests and offline integration only.

    Schema 3.0 has no top-level evidence-gap status. Consequently,
    `no_material_break_found` is only the validator-compatible envelope for
    explicit section gaps; it is not a semantic finding that no break exists.
    This provider cannot demonstrate real-model generalization.
    """

    provider_id = "deterministic-offline-v1"

    def analyze(
        self,
        evidence: tuple[ReasoningEvidence, ...],
        spans: tuple[EvidenceSpan, ...],
        question: str,
    ) -> AnalysisCandidate:
        if not isinstance(question, str) or not question.strip():
            raise ProviderError()
        try:
            grounding = build_grounding_index(evidence, spans)
        except GroundingInputError:
            raise ProviderError() from None

        grounded_span_ids = [
            grounding.span_ids_by_evidence[evidence_id][0]
            for evidence_id in grounding.evidence_ids
        ]
        annotations: list[SemanticAnnotationCandidate] = [
            {
                "evidence_id": evidence_id,
                "propagation_role": "none",
                "context_tags": [],
            }
            for evidence_id in grounding.evidence_ids
        ]
        sections: list[ProjectReportSectionCandidate] = [
            evidence_gap_section(section_key)
            for section_key in PROJECT_REPORT_SECTION_NAMES
        ]
        return {
            "schema_version": SUPPORTED_SCHEMA_VERSION,
            "analysis_status": "no_material_break_found",
            "continuity_break_kind": None,
            "current_state": {
                "statement": (
                    "The available evidence cannot establish a semantic project "
                    "state through the deterministic offline provider."
                ),
                "span_ids": grounded_span_ids,
            },
            "semantic_annotations": annotations,
            "continuity_break": None,
            "next_action": None,
            "project_report": {
                "summary": {
                    "statement": (
                        "No semantic conclusion is asserted; every report section "
                        "remains an explicit evidence gap."
                    ),
                    "span_ids": grounded_span_ids,
                },
                "sections": sections,
            },
        }
