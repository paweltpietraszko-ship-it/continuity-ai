"""Contract tests for the Project Report schema 3.0: exact section shape and
order, all status rules, and the relationship between `attention` sections,
`continuity_break`, and `analysis_status`.
"""
from __future__ import annotations
import pytest
from continuity_ai.domain import ReasoningEvidence
from continuity_ai.errors import ValidationError
from continuity_ai.evidence import build_spans
from continuity_ai.reasoning_pipeline import validate_analysis

SECTION_NAMES = ("decision", "budget", "schedule", "operations", "readiness", "casting", "agreements")


def _world():
    records = (
        ReasoningEvidence("EV-A", "decision", "Alex", "2026-01-01T00:00:00Z", "Approval", "The team approves the change.", "artifact"),
        ReasoningEvidence("EV-B", "runbook", "Blair", "2026-01-02T00:00:00Z", "Runbook", "The runbook still lists the old value.", "artifact"),
    )
    return records, build_spans(records)


def _evidence_gap(key: str) -> dict:
    return {
        "key": key,
        "status": "evidence_gap",
        "headline": "No verified status available",
        "detail": f"No available project source establishes the current {key} status.",
        "span_ids": [],
    }


def _candidate(records, spans, attention: bool = True) -> dict:
    span_a, span_b = spans[0].span_id, spans[1].span_id
    sections = [
        {
            "key": "decision",
            "status": "attention" if attention else "confirmed",
            "headline": "Needs review" if attention else "Confirmed",
            "detail": "The approved change has not fully propagated." if attention else "The decision is confirmed.",
            "span_ids": [span_a, span_b],
        },
        *[_evidence_gap(name) for name in SECTION_NAMES[1:]],
    ]
    return {
        "schema_version": "3.0",
        "analysis_status": "break_found" if attention else "no_material_break_found",
        "continuity_break_kind": "propagation_break" if attention else None,
        "current_state": {"statement": "Current state.", "span_ids": [span_a]},
        "semantic_annotations": [
            {"evidence_id": "EV-A", "propagation_role": "approved_decision" if attention else "none", "context_tags": []},
            {"evidence_id": "EV-B", "propagation_role": "conflicts_with_decision" if attention else "none", "context_tags": []},
        ],
        "continuity_break": {"statement": "Break statement.", "span_ids": [span_a, span_b]} if attention else None,
        "next_action": {"statement": "Next action.", "span_ids": [span_b]} if attention else None,
        "project_report": {
            "summary": {"statement": "Summary statement.", "span_ids": [span_a]},
            "sections": sections,
        },
    }


def test_valid_break_found_report_has_seven_sections_in_exact_order():
    records, spans = _world()
    result = validate_analysis(_candidate(records, spans, attention=True), records, spans)
    assert [s.key for s in result.project_report.sections] == list(SECTION_NAMES)
    assert result.project_report.summary.statement.strip()
    assert result.project_report.summary.span_ids


def test_valid_no_material_break_found_report_has_no_attention_section():
    records, spans = _world()
    result = validate_analysis(_candidate(records, spans, attention=False), records, spans)
    assert all(s.status != "attention" for s in result.project_report.sections)


def test_missing_section_rejected():
    records, spans = _world()
    candidate = _candidate(records, spans)
    candidate["project_report"]["sections"] = candidate["project_report"]["sections"][:-1]
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_extra_section_rejected():
    records, spans = _world()
    candidate = _candidate(records, spans)
    candidate["project_report"]["sections"].append(_evidence_gap("agreements"))
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_duplicate_section_name_rejected():
    records, spans = _world()
    candidate = _candidate(records, spans)
    # Position 1 (expected "budget") is overwritten with a second "decision" section.
    candidate["project_report"]["sections"][1] = dict(candidate["project_report"]["sections"][0])
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_reordered_sections_rejected():
    records, spans = _world()
    candidate = _candidate(records, spans)
    sections = candidate["project_report"]["sections"]
    sections[0], sections[1] = sections[1], sections[0]
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_invalid_status_value_rejected():
    records, spans = _world()
    candidate = _candidate(records, spans)
    candidate["project_report"]["sections"][1]["status"] = "bogus_status"
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_evidence_gap_must_have_empty_span_list():
    records, spans = _world()
    candidate = _candidate(records, spans)
    candidate["project_report"]["sections"][1]["span_ids"] = [spans[0].span_id]
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_evidence_gap_headline_is_fixed():
    records, spans = _world()
    candidate = _candidate(records, spans)
    candidate["project_report"]["sections"][1]["headline"] = "Something else"
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_evidence_gap_statement_is_the_fixed_per_section_message():
    records, spans = _world()
    candidate = _candidate(records, spans)
    candidate["project_report"]["sections"][1]["detail"] = "wrong statement"
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_confirmed_status_requires_at_least_one_span():
    records, spans = _world()
    candidate = _candidate(records, spans)
    candidate["project_report"]["sections"][4]["status"] = "confirmed"
    candidate["project_report"]["sections"][4]["headline"] = "Confirmed"
    candidate["project_report"]["sections"][4]["detail"] = "Confirmed with no span."
    candidate["project_report"]["sections"][4]["span_ids"] = []
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_not_applicable_status_requires_at_least_one_valid_span():
    records, spans = _world()
    candidate = _candidate(records, spans)
    candidate["project_report"]["sections"][5]["status"] = "not_applicable"
    candidate["project_report"]["sections"][5]["headline"] = "Not applicable"
    candidate["project_report"]["sections"][5]["detail"] = "Not applicable here."
    candidate["project_report"]["sections"][5]["span_ids"] = ["EV-GHOST:L001"]
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_section_span_must_be_owned_by_authoritative_evidence():
    records, spans = _world()
    candidate = _candidate(records, spans)
    candidate["project_report"]["sections"][0]["span_ids"] = ["EV-GHOST:L001"]
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_break_found_requires_at_least_one_attention_section():
    records, spans = _world()
    candidate = _candidate(records, spans, attention=True)
    candidate["project_report"]["sections"][0]["status"] = "confirmed"
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_attention_section_must_share_a_span_with_continuity_break():
    records, spans = _world()
    candidate = _candidate(records, spans, attention=True)
    candidate["project_report"]["sections"][0]["span_ids"] = [spans[0].span_id]
    candidate["continuity_break"]["span_ids"] = [spans[1].span_id]
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_no_material_break_found_forbids_any_attention_section():
    records, spans = _world()
    candidate = _candidate(records, spans, attention=False)
    candidate["project_report"]["sections"][0]["status"] = "attention"
    candidate["project_report"]["sections"][0]["headline"] = "Needs review"
    candidate["project_report"]["sections"][0]["detail"] = "Needs review."
    candidate["project_report"]["sections"][0]["span_ids"] = [spans[0].span_id]
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_summary_requires_nonempty_statement():
    records, spans = _world()
    candidate = _candidate(records, spans)
    candidate["project_report"]["summary"]["statement"] = "   "
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_summary_requires_at_least_one_valid_span():
    records, spans = _world()
    candidate = _candidate(records, spans)
    candidate["project_report"]["summary"]["span_ids"] = []
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_summary_span_must_be_owned_by_authoritative_evidence():
    records, spans = _world()
    candidate = _candidate(records, spans)
    candidate["project_report"]["summary"]["span_ids"] = ["EV-GHOST:L001"]
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)
