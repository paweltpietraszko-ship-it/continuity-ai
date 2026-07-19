"""Pure unit tests for the Codex-only mechanical integrity checklist added to
`codex_source_scoping_provider._build_prompt` (M1). No Codex CLI, no schema,
and no validator involved: these tests only check what the generated prompt
text says, computed strictly from the same authoritative evidence/spans the
real classify() call already carries.
"""
from __future__ import annotations

from continuity_ai.domain import EvidenceSpan, ReasoningEvidence
from continuity_ai.integration.codex_source_scoping_provider import (
    _build_prompt,
    _integrity_checklist,
)

_TIMESTAMP = "2026-01-01T00:00:00Z"


def _evidence(evidence_id: str, uri: str = "records/should-never-appear.txt") -> ReasoningEvidence:
    return ReasoningEvidence(
        evidence_id,
        "markdown",
        "Author",
        _TIMESTAMP,
        f"Title for {evidence_id}",
        f"Content for {evidence_id}",
        "artifact",
        uri=uri,
        artifact_sha256="0" * 64,
    )


def _fixture() -> tuple[tuple[ReasoningEvidence, ...], tuple[EvidenceSpan, ...]]:
    evidence = (
        _evidence("EV-B"),
        _evidence("EV-A"),
        _evidence("EV-C"),
    )
    spans = (
        EvidenceSpan("EV-B:L001", "EV-B", "text b1", 1),
        EvidenceSpan("EV-B:L002", "EV-B", "text b2", 2),
        EvidenceSpan("EV-A:L001", "EV-A", "text a1", 1),
        EvidenceSpan("EV-C:L001", "EV-C", "text c1", 1),
    )
    return evidence, spans


def test_checklist_states_exact_decision_count_and_evidence_id_order() -> None:
    evidence, spans = _fixture()
    checklist = _integrity_checklist(evidence, spans)

    assert "exactly 3 entries" in checklist
    assert "EV-B, EV-A, EV-C" in checklist


def test_checklist_lists_only_each_evidence_ids_own_span_ids() -> None:
    evidence, spans = _fixture()
    checklist = _integrity_checklist(evidence, spans)

    assert 'evidence_id "EV-B" may only cite span_id values from this exact set: EV-B:L001, EV-B:L002' in checklist
    assert 'evidence_id "EV-A" may only cite span_id values from this exact set: EV-A:L001' in checklist
    assert 'evidence_id "EV-C" may only cite span_id values from this exact set: EV-C:L001' in checklist
    # No evidence_id's allowed set leaks another evidence_id's span.
    assert "EV-A:L001" not in checklist.split('evidence_id "EV-B"')[1].split("\n")[0]


def test_checklist_states_anchor_and_partition_projection_rules() -> None:
    evidence, spans = _fixture()
    checklist = _integrity_checklist(evidence, spans)

    assert "anchor_evidence_ids" in checklist
    assert "explicit_target" in checklist
    assert "selected_evidence_ids" in checklist
    assert "ambiguous_evidence_ids" in checklist
    assert "excluded_evidence_ids" in checklist
    assert "mutually exclusive" in checklist


def test_checklist_states_related_evidence_ids_rules() -> None:
    evidence, spans = _fixture()
    checklist = _integrity_checklist(evidence, spans)

    assert "related_evidence_ids" in checklist
    assert "own evidence_id" in checklist
    assert "corroborated_context" in checklist
    assert "corroborated_other_project" in checklist


def test_checklist_never_contains_a_seed_oracle_or_local_path() -> None:
    evidence, spans = _fixture()
    checklist = _integrity_checklist(evidence, spans)

    lowered = checklist.casefold()
    assert "seed" not in lowered
    assert "oracle" not in lowered
    assert "expected_status" not in lowered
    assert "expected status" not in lowered
    assert "records/should-never-appear.txt" not in checklist
    assert ":\\" not in checklist
    assert "/records/" not in checklist


def test_checklist_handles_an_evidence_id_with_no_spans() -> None:
    evidence = (_evidence("EV-ONLY"),)
    spans: tuple[EvidenceSpan, ...] = ()
    checklist = _integrity_checklist(evidence, spans)

    assert "exactly 1 entries" in checklist
    assert "(no spans available)" in checklist


def test_build_prompt_includes_both_the_checklist_and_the_request_document() -> None:
    evidence, spans = _fixture()
    prompt = _build_prompt("Project Fixture", evidence, spans)

    assert "Mechanical integrity checklist" in prompt
    assert "EV-B, EV-A, EV-C" in prompt
    assert "Project Fixture" in prompt
    # The frozen Source Scoping prompt itself still leads the combined prompt.
    assert prompt.index("Mechanical integrity checklist") > prompt.index("\n\n")

    lowered = prompt.casefold()
    assert "seed" not in lowered
    assert "oracle" not in lowered
    assert "records/should-never-appear.txt" not in prompt
