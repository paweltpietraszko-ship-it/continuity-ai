from dataclasses import replace
from pathlib import Path

from continuity_ai.evidence import build_spans
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.prompts import SOURCE_SCOPING_PROMPT
from continuity_ai.source_scoping.service import run_source_scoping


def _rename(records, replacements):
    renamed = []
    for record in records:
        title = record.title
        content = record.content
        for old, new in replacements.items():
            title = title.replace(old, new)
            content = content.replace(old, new)
        renamed.append(replace(record, title=title, content=content))
    return tuple(renamed)


def test_complete_project_renaming_preserves_partition(workspace):
    target, records, _ = workspace
    baseline = run_source_scoping(
        target, records, build_spans(records), FakeSourceScopingProvider()
    )
    replacements = {
        "Project Aurora": "Project Zephyr",
        "Project Meridian": "Project Lattice",
        "Project Ember": "Project Quasar",
        "Aurora": "Zephyr",
        "Meridian": "Lattice",
        "Ember": "Quasar",
    }
    renamed = _rename(records, replacements)
    result = run_source_scoping(
        "Project Zephyr",
        renamed,
        build_spans(renamed),
        FakeSourceScopingProvider(),
    )
    assert result.selected_evidence_ids == baseline.selected_evidence_ids
    assert result.ambiguous_evidence_ids == baseline.ambiguous_evidence_ids
    assert result.excluded_evidence_ids == baseline.excluded_evidence_ids

    unseen = _rename(
        records,
        {"Project Aurora": "Project Xylophone", "Aurora": "Xylophone"},
    )
    unseen_result = run_source_scoping(
        "Project Xylophone",
        unseen,
        build_spans(unseen),
        FakeSourceScopingProvider(),
    )
    assert "EV-MIX-001" in unseen_result.anchor_evidence_ids
    assert "EV-MIX-002" in unseen_result.selected_evidence_ids


def test_identical_records_change_partition_when_target_project_changes(workspace):
    _, records, spans = workspace
    provider = FakeSourceScopingProvider()
    records_before = tuple(records)
    spans_before = tuple(spans)

    results = {
        target: run_source_scoping(target, records, spans, provider)
        for target in (
            "Project Aurora",
            "Project Meridian",
            "Project Ember",
        )
    }

    assert records == records_before
    assert spans == spans_before
    assert results["Project Aurora"].anchor_evidence_ids == (
        "EV-MIX-001",
        "EV-MIX-016",
    )
    assert results["Project Meridian"].anchor_evidence_ids == (
        "EV-MIX-004",
        "EV-MIX-014",
    )
    assert results["Project Ember"].anchor_evidence_ids == ("EV-MIX-006",)
    assert len(
        {
            result.selected_evidence_ids
            for result in results.values()
        }
    ) == 3
    assert "EV-MIX-001" in results["Project Aurora"].selected_evidence_ids
    assert "EV-MIX-001" in results["Project Meridian"].excluded_evidence_ids
    assert "EV-MIX-001" in results["Project Ember"].excluded_evidence_ids
    assert "EV-MIX-004" in results["Project Meridian"].selected_evidence_ids
    assert "EV-MIX-004" in results["Project Aurora"].excluded_evidence_ids
    assert "EV-MIX-006" in results["Project Ember"].selected_evidence_ids
    assert "EV-MIX-006" in results["Project Aurora"].excluded_evidence_ids


def test_production_prompt_contains_no_fixture_project_names():
    folded = SOURCE_SCOPING_PROMPT.casefold()
    for forbidden in ("aurora", "meridian", "ember", "ev-mix"):
        assert forbidden not in folded


def test_production_package_contains_no_fixture_ids_or_expected_results():
    package = Path(__file__).parents[2] / "src" / "continuity_ai" / "source_scoping"
    text = "\n".join(
        path.read_text("utf-8") for path in package.glob("*.py")
    ).casefold()
    assert "ev-mix" not in text
    assert "project aurora" not in text
    assert "project meridian" not in text
    assert "project ember" not in text
