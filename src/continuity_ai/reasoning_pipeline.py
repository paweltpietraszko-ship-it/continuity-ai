"""Reasoning provider protocol, fake provider, and validator."""
from __future__ import annotations
from typing import Protocol, Any
import uuid
from continuity_ai.domain import (
    AnalysisResult, GroundedStatement, PROJECT_REPORT_SECTION_NAMES, PROJECT_REPORT_STATUSES,
    ProjectReport, ProjectReportSection, SemanticAnnotation,
)
from continuity_ai.errors import ValidationError
from continuity_ai.evidence import make_snapshot, build_spans

class ReasoningProvider(Protocol):
    provider_id: str
    def analyze(self, evidence: tuple[Any, ...], spans: tuple[Any, ...], question: str) -> dict[str, Any]: ...

EVIDENCE_GAP_HEADLINE = "No verified status available"

def _evidence_gap_section(section: str) -> dict[str, Any]:
    return {
        "section": section,
        "status": "evidence_gap",
        "headline": EVIDENCE_GAP_HEADLINE,
        "statement": f"No available project source establishes the current {section} status.",
        "span_ids": [],
    }

def _grounded_section(section: str, status: str, headline: str, statement: str, span_ids: list[str]) -> dict[str, Any]:
    return {"section": section, "status": status, "headline": headline, "statement": statement, "span_ids": span_ids}

class FakeAuroraProvider:
    provider_id = "fake-provider-v1"
    def analyze(self, evidence, spans, question):
        by_ev = {e.evidence_id: [] for e in evidence}
        for s in spans:
            by_ev[s.evidence_id].append(s.span_id)
        ids = [e.evidence_id for e in evidence]
        anns = []
        for i, eid in enumerate(ids):
            role = ["approved_decision", "conflicts_with_decision", "reflects_decision", "conflicts_with_decision", "none"][i] if i < 5 else "none"
            tags = ["urgency"] if i == 4 else []
            anns.append({"evidence_id": eid, "propagation_role": role, "context_tags": tags})
        sections = [
            _grounded_section("decision", "confirmed", "Location change approved", "An approved decision authorizes the location change.", [by_ev[ids[0]][0]]),
            _evidence_gap_section("budget"),
            _grounded_section("schedule", "attention", "Operational sources not yet aligned", "The approved change has not reached every operational schedule source.", [by_ev[ids[0]][0], by_ev[ids[1]][0]]),
            _evidence_gap_section("operations"),
            _grounded_section("readiness", "not_applicable", "Not evaluated", "Readiness is not evaluated by this analysis.", [by_ev[ids[2]][0]]),
            _evidence_gap_section("casting"),
            _evidence_gap_section("agreements"),
        ]
        return {
            "schema_version": "3.0",
            "analysis_status": "break_found",
            "continuity_break_kind": "propagation_break",
            "current_state": {"statement": "The project sources show an approved change that has not reached every operational artifact.", "span_ids": [by_ev[ids[0]][0], by_ev[ids[1]][0]]},
            "semantic_annotations": anns,
            "continuity_break": {"statement": "An approved decision is reflected by some project sources but contradicted by current operational sources.", "span_ids": [by_ev[ids[0]][0], by_ev[ids[1]][0], by_ev[ids[2]][0], by_ev[ids[3]][0]]},
            "next_action": {"statement": "Update the affected operational sources before the time-sensitive briefing.", "span_ids": [by_ev[ids[3]][0], by_ev[ids[4]][0]]},
            "project_report": {
                "summary": {"statement": "Project Aurora shows an approved change that has not fully propagated to operational sources.", "span_ids": [by_ev[ids[0]][0]]},
                "sections": sections,
            },
        }

class FakeDecisionProvenanceProvider:
    provider_id = "fake-decision-provenance-v1"
    def analyze(self, evidence, spans, question):
        ids = [e.evidence_id for e in evidence]
        by_ev = {e.evidence_id: [] for e in evidence}
        for s in spans:
            by_ev[s.evidence_id].append(s.span_id)
        break_spans = [by_ev[ids[0]][0], by_ev[ids[1]][0]]
        sections = [
            _grounded_section("decision", "attention", "No decision provenance found", "No supplied approval, decision, or note establishes who approved this change.", break_spans),
            _evidence_gap_section("budget"),
            _evidence_gap_section("schedule"),
            _evidence_gap_section("operations"),
            _evidence_gap_section("readiness"),
            _evidence_gap_section("casting"),
            _evidence_gap_section("agreements"),
        ]
        return {
            "schema_version": "3.0",
            "analysis_status": "break_found",
            "continuity_break_kind": "decision_provenance_not_found",
            "current_state": {"statement": "A project item changed between available sources, and no approving source was found in the available project sources.", "span_ids": [by_ev[ids[0]][0], by_ev[ids[1]][0]]},
            "semantic_annotations": [{"evidence_id": eid, "propagation_role": "none", "context_tags": []} for eid in ids],
            "continuity_break": {"statement": "Change with no decision found: The feature changed from present to absent. We couldn’t find an approval, decision, or note for this change in the project sources currently available to Continuity AI.", "span_ids": break_spans},
            "next_action": {"statement": "Add or link the decision that approved this change before treating the new value as current.", "span_ids": [by_ev[ids[0]][0], by_ev[ids[1]][0]]},
            "project_report": {
                "summary": {"statement": "A material change appears with no recorded decision provenance.", "span_ids": break_spans},
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
_SECTION_KEYS = {"section", "status", "headline", "statement", "span_ids"}

def _grounded_statement(obj: Any) -> GroundedStatement:
    """Structural shape only; span ownership is checked separately against whichever
    evidence/span identity the caller is authoritative for."""
    if not isinstance(obj, dict) or set(obj) != {"statement", "span_ids"}: raise ValidationError()
    if not isinstance(obj["statement"], str) or not obj["statement"].strip(): raise ValidationError()
    spans = tuple(obj["span_ids"])
    if not spans or not all(isinstance(s, str) for s in spans): raise ValidationError()
    return GroundedStatement(obj["statement"], spans)

def _span_owners(gs: GroundedStatement, span_owner: dict[str, str], evidence_ids: set[str]) -> set[str]:
    parents: set[str] = set()
    for sid in gs.span_ids:
        owner = span_owner.get(sid)
        if owner is None or owner not in evidence_ids: raise ValidationError()
        parents.add(owner)
    return parents

def _validate_section(obj: Any, expected_section: str, span_owner: dict[str, str], evidence_ids: set[str]) -> ProjectReportSection:
    if not isinstance(obj, dict) or set(obj) != _SECTION_KEYS: raise ValidationError()
    if obj["section"] != expected_section: raise ValidationError()
    status = obj["status"]
    if status not in PROJECT_REPORT_STATUSES: raise ValidationError()
    headline, statement, span_ids = obj["headline"], obj["statement"], obj["span_ids"]
    if not isinstance(headline, str) or not headline.strip(): raise ValidationError()
    if not isinstance(statement, str) or not statement.strip(): raise ValidationError()
    if not isinstance(span_ids, list) or not all(isinstance(s, str) for s in span_ids): raise ValidationError()

    if status == "evidence_gap":
        if span_ids != []: raise ValidationError()
        if headline != EVIDENCE_GAP_HEADLINE: raise ValidationError()
        if statement != f"No available project source establishes the current {expected_section} status.": raise ValidationError()
        return ProjectReportSection(expected_section, status, headline, statement, ())

    if not span_ids: raise ValidationError()
    for sid in span_ids:
        owner = span_owner.get(sid)
        if owner is None or owner not in evidence_ids: raise ValidationError()
    return ProjectReportSection(expected_section, status, headline, statement, tuple(span_ids))

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
