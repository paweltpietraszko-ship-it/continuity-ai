"""Genericity and fail-closed contract for the deterministic offline fake."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from continuity_ai.bridge import Bridge
from continuity_ai.domain import EvidenceSpan, ReasoningEvidence
from continuity_ai.errors import ProviderError
from continuity_ai.evidence import build_spans
from continuity_ai.reasoning_pipeline import (
    DeterministicOfflineReasoningProvider,
    validate_analysis,
)


def _record(evidence_id: str, title: str, content: str) -> ReasoningEvidence:
    return ReasoningEvidence(
        evidence_id,
        "markdown",
        "Offline Tester",
        "2031-02-03T04:05:06Z",
        title,
        content,
        "artifact",
    )


def _write_project(root: Path, project: str, evidence_id: str) -> Path:
    root.mkdir(parents=True)
    content = b"Neutral source content for offline contract testing.\n"
    (root / "source.md").write_bytes(content)
    manifest = {
        "schema_version": 1,
        "project": project,
        "artifacts": [
            {
                "source_id": "source-custom-1",
                "evidence_id": evidence_id,
                "author": "Offline Tester",
                "timestamp": "2031-02-03T04:05:06Z",
                "source_type": "markdown",
                "title": "Neutral source",
                "uri": "source.md",
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    (root / "evidence_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return root


@pytest.mark.parametrize(
    ("project", "evidence_id"),
    [
        ("Zephyr Documentary", "proof-9Z"),
        ("Kestrel Research Initiative", "item_X-42"),
    ],
)
def test_arbitrary_project_names_and_evidence_ids_flow_through_bridge(
    tmp_path: Path, project: str, evidence_id: str
) -> None:
    artifact_root = _write_project(tmp_path / evidence_id, project, evidence_id)
    bridge = Bridge(DeterministicOfflineReasoningProvider())

    loaded = bridge.handle(
        {"command": "load_project", "artifact_root": str(artifact_root)}
    )
    analyzed = bridge.handle(
        {"command": "analyze_project", "question": "What is safely established?"}
    )

    assert loaded["ok"] is True
    assert loaded["data"]["project"] == project
    assert loaded["data"]["evidence_records"][0]["evidence_id"] == evidence_id
    assert analyzed["ok"] is True
    assert analyzed["data"]["project"] == project
    assert analyzed["data"]["schema_version"] == "3.0"
    assert analyzed["data"]["analysis_status"] == "no_material_break_found"
    assert all(
        section["status"] == "evidence_gap"
        for section in analyzed["data"]["project_report"]["sections"]
    )


def test_reordering_records_and_spans_does_not_change_output_or_roles() -> None:
    records = (
        _record("evidence-zeta", "Later listing", "A value appears here."),
        _record("evidence-alpha", "Earlier listing", "Another value appears here."),
        _record("evidence-mid", "Middle listing", "A third value appears here."),
    )
    spans = build_spans(records)
    provider = DeterministicOfflineReasoningProvider()

    original = provider.analyze(records, spans, "Review safely")
    reordered_records = tuple(reversed(records))
    reordered_spans = tuple(reversed(build_spans(reordered_records)))
    reordered = provider.analyze(
        reordered_records, reordered_spans, "Review safely"
    )

    assert reordered == original
    assert [a["evidence_id"] for a in original["semantic_annotations"]] == [
        "evidence-alpha",
        "evidence-mid",
        "evidence-zeta",
    ]
    assert {
        a["evidence_id"]: a["propagation_role"]
        for a in original["semantic_annotations"]
    } == {
        "evidence-alpha": "none",
        "evidence-mid": "none",
        "evidence-zeta": "none",
    }
    validate_analysis(original, records, spans)
    validate_analysis(reordered, reordered_records, reordered_spans)


def test_output_is_schema_valid_and_explicitly_reports_evidence_gaps() -> None:
    records = (_record("unfamiliar-ID-77", "Unclassified note", "Only one fact."),)
    spans = build_spans(records)
    candidate = DeterministicOfflineReasoningProvider().analyze(
        records, spans, "Assess the evidence"
    )

    result = validate_analysis(candidate, records, spans)

    assert result.schema_version == "3.0"
    assert result.continuity_break is None
    assert result.next_action is None
    assert {annotation.propagation_role for annotation in result.semantic_annotations} == {
        "none"
    }
    assert {section.status for section in result.project_report.sections} == {
        "evidence_gap"
    }


@pytest.mark.parametrize(
    ("records", "spans", "question"),
    [
        ((), (), "question"),
        ((_record("missing-span", "Note", "Content"),), (), "question"),
        (
            (_record("owned", "Note", "Content"),),
            (EvidenceSpan("foreign:L001", "foreign", "Content", 1),),
            "question",
        ),
        (
            (
                _record("duplicate", "First", "Content"),
                _record("duplicate", "Second", "Other content"),
            ),
            (),
            "question",
        ),
        ((_record("blank-question", "Note", "Content"),), (), "   "),
    ],
)
def test_unsupported_or_insufficient_input_fails_closed(
    records: tuple, spans: tuple, question: str
) -> None:
    with pytest.raises(ProviderError):
        DeterministicOfflineReasoningProvider().analyze(records, spans, question)


def test_fixture_project_literals_are_absent_from_production_python() -> None:
    production_root = Path(__file__).parents[1] / "src" / "continuity_ai"
    # The fixture generator is explicitly out of scope for this corrective branch.
    production_paths = [
        path
        for path in production_root.rglob("*.py")
        if path.name != "aurora_fixture.py"
    ]
    forbidden = (
        "Project " + "Aurora",
        "Project " + "Meridian",
        "Project " + "Ember",
    )

    occurrences = {
        str(path.relative_to(production_root)): literal
        for path in production_paths
        for literal in forbidden
        if literal in path.read_text(encoding="utf-8")
    }

    assert occurrences == {}
