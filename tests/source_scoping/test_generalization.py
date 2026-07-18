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
    renamed = _rename(
        records,
        {
            "Project Aurora": "Project Zephyr",
            "Project Meridian": "Project Lattice",
            "Project Ember": "Project Quasar",
            "Aurora": "Zephyr",
            "Meridian": "Lattice",
            "Ember": "Quasar",
        },
    )
    result = run_source_scoping(
        "Project Zephyr",
        renamed,
        build_spans(renamed),
        FakeSourceScopingProvider(),
    )
    assert result.selected_evidence_ids == baseline.selected_evidence_ids
    assert result.ambiguous_evidence_ids == baseline.ambiguous_evidence_ids
    assert result.excluded_evidence_ids == baseline.excluded_evidence_ids


def test_unseen_target_name_is_not_required_in_code(workspace):
    _, records, _ = workspace
    renamed = _rename(
        records,
        {"Project Aurora": "Project Xylophone", "Aurora": "Xylophone"},
    )
    result = run_source_scoping(
        "Project Xylophone",
        renamed,
        build_spans(renamed),
        FakeSourceScopingProvider(),
    )
    assert "EV-MIX-001" in result.anchor_evidence_ids
    assert "EV-MIX-002" in result.selected_evidence_ids


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
