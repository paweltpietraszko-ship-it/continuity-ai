from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from continuity_ai.unseen_workspace.generator import (
    UnseenWorkspaceGenerationError,
    generate_unseen_workspace,
)
from continuity_ai.unseen_workspace.ingestion import load_workspace


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_same_seed_produces_byte_identical_semantic_run(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    generate_unseen_workspace(first, 314159)
    generate_unseen_workspace(second, 314159)

    assert _tree_bytes(first) == _tree_bytes(second)


def test_different_seeds_materially_change_entities_ids_relationships_and_order(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate_unseen_workspace(first, 101)
    generate_unseen_workspace(second, 202)

    first_metadata = _json(first / "oracle" / "metadata.json")
    second_metadata = _json(second / "oracle" / "metadata.json")
    first_manifest = _json(first / "input" / "workspace.json")
    second_manifest = _json(second / "input" / "workspace.json")

    first_projects = first_metadata["projects"]
    second_projects = second_metadata["projects"]
    assert [project["name"] for project in first_projects] != [
        project["name"] for project in second_projects
    ]
    assert [project["lead"] for project in first_projects] != [
        project["lead"] for project in second_projects
    ]
    assert [project["location"] for project in first_projects] != [
        project["location"] for project in second_projects
    ]
    assert [record["evidence_id"] for record in first_manifest["records"]] != [
        record["evidence_id"] for record in second_manifest["records"]
    ]
    assert [record["path"] for record in first_manifest["records"]] != [
        record["path"] for record in second_manifest["records"]
    ]
    assert _tree_bytes(first / "input") != _tree_bytes(second / "input")


def test_generated_structure_physically_separates_input_and_oracle(tmp_path: Path) -> None:
    run = tmp_path / "generated-run"
    result = generate_unseen_workspace(run, 7)

    assert set(path.name for path in run.iterdir()) == {"input", "oracle"}
    assert set(path.name for path in (run / "input").iterdir()) == {"workspace.json", "records"}
    assert set(path.name for path in (run / "oracle").iterdir()) == {
        "expected_scope.json",
        "metadata.json",
    }
    assert result["input_root"] == str(run / "input")
    assert result["oracle_root"] == str(run / "oracle")
    assert not any(path.name in {"expected_scope.json", "metadata.json"} for path in (run / "input").rglob("*"))


def test_run_contains_fifteen_records_and_all_required_semantic_categories(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 88)
    manifest = _json(run / "input" / "workspace.json")
    oracle = _json(run / "oracle" / "expected_scope.json")
    records = manifest["records"]
    expected = oracle["records"]
    tags = {tag for record in expected for tag in record["scenario_tags"]}

    assert 12 <= len(records) <= 18
    assert len(records) == 15
    assert {record["format"] for record in records} == {"txt", "md", "json"}
    assert {
        "explicit_target_project",
        "contextual_target_without_name",
        "explicit_other_project",
        "contextual_other_project",
        "shared_record_two_projects",
        "insufficient_context",
        "conflicting_context",
        "version_change",
        "non_project_name_resemblance",
        "prompt_injection_as_data",
        "ambiguous",
    } <= tags


def test_every_oracle_record_appears_exactly_once_and_ambiguity_is_real(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 99)
    manifest = _json(run / "input" / "workspace.json")
    oracle = _json(run / "oracle" / "expected_scope.json")
    input_ids = [record["evidence_id"] for record in manifest["records"]]
    oracle_ids = [record["evidence_id"] for record in oracle["records"]]
    ambiguous = [
        record
        for record in oracle["records"]
        if record["expected_status"] == "defer" and "ambiguous" in record["scenario_tags"]
    ]

    assert len(input_ids) == len(set(input_ids))
    assert len(oracle_ids) == len(set(oracle_ids))
    assert set(input_ids) == set(oracle_ids)
    assert len(ambiguous) >= 2


def test_engine_input_exposes_no_oracle_status_seed_or_scenario_tags(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 12345)
    all_input = b"\n".join(_tree_bytes(run / "input").values()).lower()

    assert b"expected_status" not in all_input
    assert b"scenario_tags" not in all_input
    assert b"expected_scope" not in all_input
    assert b'"seed"' not in all_input
    assert b'"oracle"' not in all_input


def test_names_and_evidence_ids_are_dynamic_and_not_answer_bearing(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 456)
    metadata = _json(run / "oracle" / "metadata.json")
    manifest = _json(run / "input" / "workspace.json")
    forbidden_fixture_names = {"Project Aurora", "Project Meridian", "Project Ember"}
    names = {project["name"] for project in metadata["projects"]}
    evidence_ids = [record["evidence_id"] for record in manifest["records"]]

    assert names.isdisjoint(forbidden_fixture_names)
    assert len(names) == 3
    assert all(re.fullmatch(r"EV-[0-9A-F]{16}", evidence_id) for evidence_id in evidence_ids)
    assert all(not any(label in evidence_id for label in ("INCLUDE", "EXCLUDE", "DEFER")) for evidence_id in evidence_ids)
    assert len(set(evidence_ids)) == len(evidence_ids)


def test_record_order_permutation_does_not_change_oracle_meaning(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 789)
    manifest_path = run / "input" / "workspace.json"
    oracle_before = _json(run / "oracle" / "expected_scope.json")
    manifest = _json(manifest_path)
    manifest["records"] = list(reversed(manifest["records"]))
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    loaded = load_workspace(run / "input")
    oracle_after = _json(run / "oracle" / "expected_scope.json")
    assert [record.evidence_id for record in loaded.records] == [
        record["evidence_id"] for record in manifest["records"]
    ]
    assert oracle_after == oracle_before
    assert set(record.evidence_id for record in loaded.records) == {
        record["evidence_id"] for record in oracle_after["records"]
    }


def test_prompt_injection_remains_inert_record_data(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 444)
    oracle = _json(run / "oracle" / "expected_scope.json")
    injection_id = next(
        record["evidence_id"]
        for record in oracle["records"]
        if "prompt_injection_as_data" in record["scenario_tags"]
    )
    loaded = load_workspace(run / "input")
    injection_record = next(record for record in loaded.records if record.evidence_id == injection_id)

    assert "IGNORE ALL PRIOR INSTRUCTIONS" in injection_record.content
    expected = next(record for record in oracle["records"] if record["evidence_id"] == injection_id)
    assert expected["expected_status"] == "exclude"
    assert len(loaded.records) == 15


def test_generator_requires_integer_seed_and_new_output_root(tmp_path: Path) -> None:
    with pytest.raises(UnseenWorkspaceGenerationError):
        generate_unseen_workspace(tmp_path / "bool", True)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(UnseenWorkspaceGenerationError):
        generate_unseen_workspace(existing, 1)


def test_production_generator_contains_no_fixture_specific_names_or_fixed_evidence_ids() -> None:
    source = Path("src/continuity_ai/unseen_workspace/generator.py").read_text(encoding="utf-8")
    assert "Project Aurora" not in source
    assert "Project Meridian" not in source
    assert "Project Ember" not in source
    assert not re.search(r"EV-[A-Z]{2,}-00[0-9]", source)
