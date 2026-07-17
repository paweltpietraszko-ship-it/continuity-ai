"""Reasoning provider protocol, fake provider, and validator."""
from __future__ import annotations
from typing import Protocol, Any
import uuid
from continuity_ai.domain import AnalysisResult, GroundedStatement, SemanticAnnotation
from continuity_ai.errors import ValidationError
from continuity_ai.evidence import make_snapshot, build_spans

class ReasoningProvider(Protocol):
    provider_id: str
    def analyze(self, evidence: tuple[Any, ...], spans: tuple[Any, ...], question: str) -> dict[str, Any]: ...

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
        return {
            "schema_version": "2.0",
            "analysis_status": "break_found",
            "continuity_break_kind": "propagation_break",
            "current_state": {"statement": "The project sources show an approved change that has not reached every operational artifact.", "span_ids": [by_ev[ids[0]][0], by_ev[ids[1]][0]]},
            "semantic_annotations": anns,
            "continuity_break": {"statement": "An approved decision is reflected by some project sources but contradicted by current operational sources.", "span_ids": [by_ev[ids[0]][0], by_ev[ids[1]][0], by_ev[ids[2]][0], by_ev[ids[3]][0]]},
            "next_action": {"statement": "Update the affected operational sources before the time-sensitive briefing.", "span_ids": [by_ev[ids[3]][0], by_ev[ids[4]][0]]},
        }

class FakeDecisionProvenanceProvider:
    provider_id = "fake-decision-provenance-v1"
    def analyze(self, evidence, spans, question):
        ids = [e.evidence_id for e in evidence]
        by_ev = {e.evidence_id: [] for e in evidence}
        for s in spans:
            by_ev[s.evidence_id].append(s.span_id)
        return {
            "schema_version": "2.0",
            "analysis_status": "break_found",
            "continuity_break_kind": "decision_provenance_not_found",
            "current_state": {"statement": "A project item changed between available sources, and no approving source was found in the available project sources.", "span_ids": [by_ev[ids[0]][0], by_ev[ids[1]][0]]},
            "semantic_annotations": [{"evidence_id": eid, "propagation_role": "none", "context_tags": []} for eid in ids],
            "continuity_break": {"statement": "Change with no decision found: The feature changed from present to absent. We couldn’t find an approval, decision, or note for this change in the project sources currently available to Continuity AI.", "span_ids": [by_ev[ids[0]][0], by_ev[ids[1]][0]]},
            "next_action": {"statement": "Add or link the decision that approved this change before treating the new value as current.", "span_ids": [by_ev[ids[0]][0], by_ev[ids[1]][0]]},
        }

def _gs(obj: Any) -> GroundedStatement:
    if not isinstance(obj, dict) or set(obj) != {"statement", "span_ids"}: raise ValidationError()
    if not isinstance(obj["statement"], str) or not obj["statement"].strip(): raise ValidationError()
    spans = tuple(obj["span_ids"])
    if not spans or not all(isinstance(s, str) for s in spans): raise ValidationError()
    return GroundedStatement(obj["statement"], spans)

def validate_analysis(candidate: dict[str, Any], evidence, spans) -> AnalysisResult:
    if set(candidate) != {"schema_version", "analysis_status", "continuity_break_kind", "current_state", "semantic_annotations", "continuity_break", "next_action"}: raise ValidationError()
    if candidate["schema_version"] != "2.0": raise ValidationError()
    status = candidate["analysis_status"]
    if status not in {"break_found", "no_material_break_found"}: raise ValidationError()
    kind = candidate["continuity_break_kind"]
    if status == "break_found" and kind not in {"propagation_break", "decision_provenance_not_found"}: raise ValidationError()
    if status == "no_material_break_found" and kind is not None: raise ValidationError()
    span_map = {s.span_id: s for s in spans}; ev_ids = {e.evidence_id for e in evidence}
    def check(gs: GroundedStatement) -> set[str]:
        parents: set[str] = set()
        for sid in gs.span_ids:
            if sid not in span_map or span_map[sid].evidence_id not in ev_ids: raise ValidationError()
            parents.add(span_map[sid].evidence_id)
        return parents
    current = _gs(candidate["current_state"]); check(current)
    br = None if candidate["continuity_break"] is None else _gs(candidate["continuity_break"])
    na = None if candidate["next_action"] is None else _gs(candidate["next_action"])
    if status == "break_found" and (br is None or na is None): raise ValidationError()
    if status == "no_material_break_found" and (br is not None or na is not None): raise ValidationError()
    br_parents = check(br) if br else set()
    if na: check(na)
    anns=[]; seen=set(); roles=[]
    for a in candidate["semantic_annotations"]:
        if set(a) != {"evidence_id", "propagation_role", "context_tags"}: raise ValidationError()
        if a["evidence_id"] not in ev_ids or a["evidence_id"] in seen: raise ValidationError()
        if a["propagation_role"] not in {"approved_decision", "reflects_decision", "conflicts_with_decision", "none"}: raise ValidationError()
        if any(t != "urgency" for t in a["context_tags"]): raise ValidationError()
        seen.add(a["evidence_id"]); roles.append(a["propagation_role"])
        anns.append(SemanticAnnotation(a["evidence_id"], a["propagation_role"], tuple(a["context_tags"])))
    if seen != ev_ids: raise ValidationError()
    if status == "break_found" and kind == "propagation_break" and ("approved_decision" not in roles or "conflicts_with_decision" not in roles): raise ValidationError()
    if status == "break_found" and kind == "decision_provenance_not_found" and ("approved_decision" in roles or len(br_parents) < 2): raise ValidationError()
    if status == "no_material_break_found" and ("conflicts_with_decision" in roles or kind is not None): raise ValidationError()
    return AnalysisResult("2.0", status, kind, current, tuple(anns), br, na)

def run_analysis(records, question: str, provider: ReasoningProvider):
    spans = build_spans(records)
    result = validate_analysis(provider.analyze(records, spans, question), records, spans)
    snapshot = make_snapshot("AN-" + uuid.uuid4().hex, records, spans, "g03_reasoning_v2", "2.0", provider.provider_id)
    return result, spans, snapshot
