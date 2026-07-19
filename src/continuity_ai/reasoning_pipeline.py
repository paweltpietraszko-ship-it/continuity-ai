"""Reasoning provider protocol, deterministic offline fake, and validator."""
from __future__ import annotations
from typing import Protocol, Any
import uuid
from continuity_ai.domain import (
    AnalysisResult, GroundedStatement, PROJECT_REPORT_SECTION_NAMES, PROJECT_REPORT_STATUSES,
    ProjectReport, ProjectReportSection, SemanticAnnotation,
)
from continuity_ai.errors import ProviderError, ValidationError
from continuity_ai.evidence import make_snapshot, build_spans

class ReasoningProvider(Protocol):
    provider_id: str
    def analyze(self, evidence: tuple[Any, ...], spans: tuple[Any, ...], question: str) -> dict[str, Any]: ...

EVIDENCE_GAP_HEADLINE = "No verified status available"

def _evidence_gap_section(key: str) -> dict[str, Any]:
    return {
        "key": key,
        "status": "evidence_gap",
        "headline": EVIDENCE_GAP_HEADLINE,
        "detail": f"No available project source establishes the current {key} status.",
        "span_ids": [],
    }

class DeterministicOfflineReasoningProvider:
    """Conservative fake for tests and offline fallback only.

    This provider deliberately performs no semantic reasoning. It produces the
    schema's evidence-gap representation from identity-ordered evidence and fails
    closed when evidence/span ownership is incomplete or ambiguous. Its output is
    useful for exercising integration paths; it is not evidence that a real model
    generalizes to unseen projects. Schema 3.0 has no top-level evidence-gap
    status, so `no_material_break_found` is used only as the validator-compatible
    envelope for the explicit section gaps, not as a semantic no-break finding.
    """

    provider_id = "deterministic-offline-v1"

    def analyze(self, evidence, spans, question):
        if (
            not isinstance(evidence, (list, tuple))
            or not isinstance(spans, (list, tuple))
            or not isinstance(question, str)
            or not question.strip()
        ):
            raise ProviderError()

        evidence_by_id = {}
        for record in evidence:
            evidence_id = getattr(record, "evidence_id", None)
            if (
                not isinstance(evidence_id, str)
                or not evidence_id.strip()
                or evidence_id in evidence_by_id
            ):
                raise ProviderError()
            evidence_by_id[evidence_id] = record
        if not evidence_by_id:
            raise ProviderError()

        spans_by_evidence = {evidence_id: [] for evidence_id in evidence_by_id}
        seen_span_ids = set()
        for span in spans:
            span_id = getattr(span, "span_id", None)
            evidence_id = getattr(span, "evidence_id", None)
            if (
                not isinstance(span_id, str)
                or not span_id.strip()
                or span_id in seen_span_ids
                or evidence_id not in evidence_by_id
            ):
                raise ProviderError()
            seen_span_ids.add(span_id)
            spans_by_evidence[evidence_id].append(span_id)

        if any(not owned_spans for owned_spans in spans_by_evidence.values()):
            raise ProviderError()

        evidence_ids = sorted(evidence_by_id)
        grounded_span_ids = [
            min(spans_by_evidence[evidence_id]) for evidence_id in evidence_ids
        ]
        annotations = [
            {
                "evidence_id": evidence_id,
                "propagation_role": "none",
                "context_tags": [],
            }
            for evidence_id in evidence_ids
        ]
        sections = [
            _evidence_gap_section(key) for key in PROJECT_REPORT_SECTION_NAMES
        ]
        return {
            "schema_version": "3.0",
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

SUPPORTED_SCHEMA_VERSION = "3.0"
STATUSES = {"break_found", "no_material_break_found"}
BREAK_KINDS = {"propagation_break", "decision_provenance_not_found"}
ROLES = {"approved_decision", "reflects_decision", "conflicts_with_decision", "none"}
_RESULT_KEYS = {"schema_version", "analysis_status", "continuity_break_kind", "current_state", "semantic_annotations", "continuity_break", "next_action", "project_report"}
_ANNOTATION_KEYS = {"evidence_id", "propagation_role", "context_tags"}
_PROJECT_REPORT_KEYS = {"summary", "sections"}
_SECTION_KEYS = {"key", "status", "headline", "detail", "span_ids"}

def _grounded_statement(obj: Any) -> GroundedStatement:
    """Structural shape only; span ownership is checked separately against whichever
    evidence/span identity the caller is authoritative for."""
    if not isinstance(obj, dict) or set(obj) != {"statement", "span_ids"}: raise ValidationError()
    if not isinstance(obj["statement"], str) or not obj["statement"].strip(): raise ValidationError()
    spans = tuple(obj["span_ids"])
    if not spans or not all(isinstance(s, str) for s in spans): raise ValidationError()
    if len(set(spans)) != len(spans): raise ValidationError()
    return GroundedStatement(obj["statement"], spans)

def _span_owners(gs: GroundedStatement, span_owner: dict[str, str], evidence_ids: set[str]) -> set[str]:
    parents: set[str] = set()
    for sid in gs.span_ids:
        owner = span_owner.get(sid)
        if owner is None or owner not in evidence_ids: raise ValidationError()
        parents.add(owner)
    return parents

def _validate_section(obj: Any, expected_key: str, span_owner: dict[str, str], evidence_ids: set[str]) -> ProjectReportSection:
    if not isinstance(obj, dict) or set(obj) != _SECTION_KEYS: raise ValidationError()
    if obj["key"] != expected_key: raise ValidationError()
    status = obj["status"]
    if status not in PROJECT_REPORT_STATUSES: raise ValidationError()
    headline, detail, span_ids = obj["headline"], obj["detail"], obj["span_ids"]
    if not isinstance(headline, str) or not headline.strip(): raise ValidationError()
    if not isinstance(detail, str) or not detail.strip(): raise ValidationError()
    if not isinstance(span_ids, list) or not all(isinstance(s, str) for s in span_ids): raise ValidationError()
    if len(set(span_ids)) != len(span_ids): raise ValidationError()

    if status == "evidence_gap":
        if span_ids != []: raise ValidationError()
        if headline != EVIDENCE_GAP_HEADLINE: raise ValidationError()
        if detail != f"No available project source establishes the current {expected_key} status.": raise ValidationError()
        return ProjectReportSection(expected_key, status, headline, detail, ())

    if not span_ids: raise ValidationError()
    for sid in span_ids:
        owner = span_owner.get(sid)
        if owner is None or owner not in evidence_ids: raise ValidationError()
    return ProjectReportSection(expected_key, status, headline, detail, tuple(span_ids))

def _validate_project_report(obj: Any, evidence_ids: set[str], span_owner: dict[str, str], analysis_status: str, continuity_break: GroundedStatement | None) -> ProjectReport:
    if not isinstance(obj, dict) or set(obj) != _PROJECT_REPORT_KEYS: raise ValidationError()
    summary = _grounded_statement(obj["summary"])
    _span_owners(summary, span_owner, evidence_ids)

    raw_sections = obj["sections"]
    if not isinstance(raw_sections, list) or len(raw_sections) != len(PROJECT_REPORT_SECTION_NAMES): raise ValidationError()
    sections = tuple(
        _validate_section(raw, expected, span_owner, evidence_ids)
        for raw, expected in zip(raw_sections, PROJECT_REPORT_SECTION_NAMES)
    )

    attention_sections = [s for s in sections if s.status == "attention"]
    if analysis_status == "break_found":
        if not attention_sections: raise ValidationError()
        break_spans = set(continuity_break.span_ids) if continuity_break is not None else set()
        if not any(set(s.span_ids) & break_spans for s in attention_sections): raise ValidationError()
    if analysis_status == "no_material_break_found" and attention_sections:
        raise ValidationError()

    return ProjectReport(summary, sections)

def validate_analysis_payload(candidate: dict[str, Any], evidence_ids: set[str], span_owner: dict[str, str]) -> AnalysisResult:
    """The single canonical implementation of semantic AnalysisResult rules.

    Operates on authoritative evidence IDs and a span-ID-to-evidence-ID ownership map
    rather than live domain objects, so the exact same rules apply whether `candidate`
    is fresh provider output or a restored retained-analysis payload."""
    if set(candidate) != _RESULT_KEYS: raise ValidationError()
    if candidate["schema_version"] != SUPPORTED_SCHEMA_VERSION: raise ValidationError()
    status = candidate["analysis_status"]
    if status not in STATUSES: raise ValidationError()
    kind = candidate["continuity_break_kind"]
    if status == "break_found" and kind not in BREAK_KINDS: raise ValidationError()
    if status == "no_material_break_found" and kind is not None: raise ValidationError()

    current = _grounded_statement(candidate["current_state"])
    _span_owners(current, span_owner, evidence_ids)
    br = None if candidate["continuity_break"] is None else _grounded_statement(candidate["continuity_break"])
    na = None if candidate["next_action"] is None else _grounded_statement(candidate["next_action"])
    if status == "break_found" and (br is None or na is None): raise ValidationError()
    if status == "no_material_break_found" and (br is not None or na is not None): raise ValidationError()
    br_parents = _span_owners(br, span_owner, evidence_ids) if br else set()
    if na: _span_owners(na, span_owner, evidence_ids)

    annotations: list[SemanticAnnotation] = []; seen: set[str] = set(); roles: list[str] = []
    for a in candidate["semantic_annotations"]:
        if not isinstance(a, dict) or set(a) != _ANNOTATION_KEYS: raise ValidationError()
        if a["evidence_id"] not in evidence_ids or a["evidence_id"] in seen: raise ValidationError()
        if a["propagation_role"] not in ROLES: raise ValidationError()
        if any(t != "urgency" for t in a["context_tags"]): raise ValidationError()
        seen.add(a["evidence_id"]); roles.append(a["propagation_role"])
        annotations.append(SemanticAnnotation(a["evidence_id"], a["propagation_role"], tuple(a["context_tags"])))
    if seen != evidence_ids: raise ValidationError()
    if status == "break_found" and kind == "propagation_break" and ("approved_decision" not in roles or "conflicts_with_decision" not in roles): raise ValidationError()
    if status == "break_found" and kind == "decision_provenance_not_found" and ("approved_decision" in roles or len(br_parents) < 2): raise ValidationError()
    if status == "no_material_break_found" and ("conflicts_with_decision" in roles or kind is not None): raise ValidationError()

    project_report = _validate_project_report(candidate["project_report"], evidence_ids, span_owner, status, br)
    return AnalysisResult(SUPPORTED_SCHEMA_VERSION, status, kind, current, tuple(annotations), br, na, project_report)

def validate_analysis(candidate: dict[str, Any], evidence, spans) -> AnalysisResult:
    """Wrapper deriving authoritative evidence/span identity from live domain objects,
    then delegating to the canonical validator shared with retained-analysis restoration."""
    evidence_ids = {e.evidence_id for e in evidence}
    span_owner = {s.span_id: s.evidence_id for s in spans}
    return validate_analysis_payload(candidate, evidence_ids, span_owner)

def run_analysis(records, question: str, provider: ReasoningProvider):
    spans = build_spans(records)
    result = validate_analysis(provider.analyze(records, spans, question), records, spans)
    snapshot = make_snapshot("AN-" + uuid.uuid4().hex, records, spans, "g03_reasoning_v3", SUPPORTED_SCHEMA_VERSION, provider.provider_id)
    return result, spans, snapshot
