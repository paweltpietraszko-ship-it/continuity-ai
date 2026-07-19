"""Canonical structural, grounding, and semantic validation for analysis payloads."""
from __future__ import annotations

from typing import Any

from continuity_ai.domain import (
    PROJECT_REPORT_SECTION_NAMES,
    PROJECT_REPORT_STATUSES,
    AnalysisResult,
    GroundedStatement,
    ProjectReport,
    ProjectReportSection,
    SemanticAnnotation,
)
from continuity_ai.errors import ValidationError
from continuity_ai.reasoning_contract import (
    EVIDENCE_GAP_HEADLINE,
    GroundingInputError,
    SUPPORTED_SCHEMA_VERSION,
    build_grounding_index,
    evidence_gap_detail,
)


STATUSES = {"break_found", "no_material_break_found"}
BREAK_KINDS = {"propagation_break", "decision_provenance_not_found"}
ROLES = {"approved_decision", "reflects_decision", "conflicts_with_decision", "none"}
_RESULT_KEYS = {
    "schema_version",
    "analysis_status",
    "continuity_break_kind",
    "current_state",
    "semantic_annotations",
    "continuity_break",
    "next_action",
    "project_report",
}
_ANNOTATION_KEYS = {"evidence_id", "propagation_role", "context_tags"}
_PROJECT_REPORT_KEYS = {"summary", "sections"}
_SECTION_KEYS = {"key", "status", "headline", "detail", "span_ids"}


def _grounded_statement(obj: Any) -> GroundedStatement:
    """Validate structure only; authoritative ownership is checked separately."""
    if not isinstance(obj, dict) or set(obj) != {"statement", "span_ids"}:
        raise ValidationError()
    if not isinstance(obj["statement"], str) or not obj["statement"].strip():
        raise ValidationError()
    raw_span_ids = obj["span_ids"]
    if (
        not isinstance(raw_span_ids, list)
        or not raw_span_ids
        or not all(isinstance(span_id, str) for span_id in raw_span_ids)
        or len(set(raw_span_ids)) != len(raw_span_ids)
    ):
        raise ValidationError()
    return GroundedStatement(obj["statement"], tuple(raw_span_ids))


def _span_owners(
    statement: GroundedStatement,
    span_owner: dict[str, str],
    evidence_ids: set[str],
) -> set[str]:
    parents: set[str] = set()
    for span_id in statement.span_ids:
        owner = span_owner.get(span_id)
        if owner is None or owner not in evidence_ids:
            raise ValidationError()
        parents.add(owner)
    return parents


def _validate_section(
    obj: Any,
    expected_key: str,
    span_owner: dict[str, str],
    evidence_ids: set[str],
) -> ProjectReportSection:
    if not isinstance(obj, dict) or set(obj) != _SECTION_KEYS:
        raise ValidationError()
    if obj["key"] != expected_key:
        raise ValidationError()

    status = obj["status"]
    headline = obj["headline"]
    detail = obj["detail"]
    span_ids = obj["span_ids"]
    if not isinstance(status, str) or status not in PROJECT_REPORT_STATUSES:
        raise ValidationError()
    if not isinstance(headline, str) or not headline.strip():
        raise ValidationError()
    if not isinstance(detail, str) or not detail.strip():
        raise ValidationError()
    if (
        not isinstance(span_ids, list)
        or not all(isinstance(span_id, str) for span_id in span_ids)
        or len(set(span_ids)) != len(span_ids)
    ):
        raise ValidationError()

    if status == "evidence_gap":
        if (
            span_ids
            or headline != EVIDENCE_GAP_HEADLINE
            or detail != evidence_gap_detail(expected_key)
        ):
            raise ValidationError()
        return ProjectReportSection(expected_key, status, headline, detail, ())

    if not span_ids:
        raise ValidationError()
    for span_id in span_ids:
        owner = span_owner.get(span_id)
        if owner is None or owner not in evidence_ids:
            raise ValidationError()
    return ProjectReportSection(
        expected_key, status, headline, detail, tuple(span_ids)
    )


def _validate_project_report(
    obj: Any,
    evidence_ids: set[str],
    span_owner: dict[str, str],
    analysis_status: str,
    continuity_break: GroundedStatement | None,
) -> ProjectReport:
    if not isinstance(obj, dict) or set(obj) != _PROJECT_REPORT_KEYS:
        raise ValidationError()
    summary = _grounded_statement(obj["summary"])
    _span_owners(summary, span_owner, evidence_ids)

    raw_sections = obj["sections"]
    if (
        not isinstance(raw_sections, list)
        or len(raw_sections) != len(PROJECT_REPORT_SECTION_NAMES)
    ):
        raise ValidationError()
    sections = tuple(
        _validate_section(raw, expected, span_owner, evidence_ids)
        for raw, expected in zip(raw_sections, PROJECT_REPORT_SECTION_NAMES)
    )

    attention_sections = [
        section for section in sections if section.status == "attention"
    ]
    if analysis_status == "break_found":
        if not attention_sections:
            raise ValidationError()
        break_spans = (
            set(continuity_break.span_ids) if continuity_break is not None else set()
        )
        if not any(
            set(section.span_ids) & break_spans for section in attention_sections
        ):
            raise ValidationError()
    if analysis_status == "no_material_break_found" and attention_sections:
        raise ValidationError()

    return ProjectReport(summary, sections)


def validate_analysis_payload(
    candidate: dict[str, Any],
    evidence_ids: set[str],
    span_owner: dict[str, str],
) -> AnalysisResult:
    """Apply the one canonical AnalysisResult validator at every trust boundary."""
    if not isinstance(candidate, dict) or set(candidate) != _RESULT_KEYS:
        raise ValidationError()
    if candidate["schema_version"] != SUPPORTED_SCHEMA_VERSION:
        raise ValidationError()

    status = candidate["analysis_status"]
    kind = candidate["continuity_break_kind"]
    if not isinstance(status, str) or status not in STATUSES:
        raise ValidationError()
    if status == "break_found" and (
        not isinstance(kind, str) or kind not in BREAK_KINDS
    ):
        raise ValidationError()
    if status == "no_material_break_found" and kind is not None:
        raise ValidationError()

    current_state = _grounded_statement(candidate["current_state"])
    _span_owners(current_state, span_owner, evidence_ids)
    continuity_break = (
        None
        if candidate["continuity_break"] is None
        else _grounded_statement(candidate["continuity_break"])
    )
    next_action = (
        None
        if candidate["next_action"] is None
        else _grounded_statement(candidate["next_action"])
    )
    if status == "break_found" and (
        continuity_break is None or next_action is None
    ):
        raise ValidationError()
    if status == "no_material_break_found" and (
        continuity_break is not None or next_action is not None
    ):
        raise ValidationError()

    break_parents = (
        _span_owners(continuity_break, span_owner, evidence_ids)
        if continuity_break
        else set()
    )
    if next_action:
        _span_owners(next_action, span_owner, evidence_ids)

    raw_annotations = candidate["semantic_annotations"]
    if not isinstance(raw_annotations, list):
        raise ValidationError()
    annotations: list[SemanticAnnotation] = []
    seen_evidence_ids: set[str] = set()
    roles: list[str] = []
    for annotation in raw_annotations:
        if not isinstance(annotation, dict) or set(annotation) != _ANNOTATION_KEYS:
            raise ValidationError()
        evidence_id = annotation["evidence_id"]
        role = annotation["propagation_role"]
        context_tags = annotation["context_tags"]
        if (
            not isinstance(evidence_id, str)
            or evidence_id not in evidence_ids
            or evidence_id in seen_evidence_ids
        ):
            raise ValidationError()
        if not isinstance(role, str) or role not in ROLES:
            raise ValidationError()
        if (
            not isinstance(context_tags, list)
            or not all(tag == "urgency" for tag in context_tags)
        ):
            raise ValidationError()
        seen_evidence_ids.add(evidence_id)
        roles.append(role)
        annotations.append(
            SemanticAnnotation(evidence_id, role, tuple(context_tags))
        )

    if seen_evidence_ids != evidence_ids:
        raise ValidationError()
    if (
        status == "break_found"
        and kind == "propagation_break"
        and (
            "approved_decision" not in roles
            or "conflicts_with_decision" not in roles
        )
    ):
        raise ValidationError()
    if (
        status == "break_found"
        and kind == "decision_provenance_not_found"
        and ("approved_decision" in roles or len(break_parents) < 2)
    ):
        raise ValidationError()
    if status == "no_material_break_found" and (
        "conflicts_with_decision" in roles or kind is not None
    ):
        raise ValidationError()

    project_report = _validate_project_report(
        candidate["project_report"],
        evidence_ids,
        span_owner,
        status,
        continuity_break,
    )
    return AnalysisResult(
        SUPPORTED_SCHEMA_VERSION,
        status,
        kind,
        current_state,
        tuple(annotations),
        continuity_break,
        next_action,
        project_report,
    )


def validate_analysis(
    candidate: dict[str, Any],
    evidence: object,
    spans: object,
) -> AnalysisResult:
    """Validate against authoritative live evidence and span identity."""
    try:
        grounding = build_grounding_index(evidence, spans)
    except GroundingInputError:
        raise ValidationError() from None
    return validate_analysis_payload(
        candidate,
        set(grounding.evidence_ids),
        dict(grounding.span_owner),
    )
