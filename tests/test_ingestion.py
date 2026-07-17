from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from continuity_ai.aurora_fixture import ARTIFACT_ROOT, generate_project_aurora_fixture
from continuity_ai.ingestion import ArtifactIngestionError, ingest_artifacts
from continuity_ai.models import EvidenceRecord
from continuity_ai.reasoning import ReasoningPipelineNotImplementedError, answer_morning_question

MANIFEST_RELATIVE_PATH = ARTIFACT_ROOT / "evidence_manifest.json"

EXPECTED_SOURCE_IDS = {
    "aurora-email-investor-approval-001",
    "aurora-calendar-production-001",
    "aurora-budget-v4-001",
    "aurora-callsheet-current-001",
    "aurora-crew-briefing-note-001",
}

EXPECTED_EVIDENCE_IDS = {
    "EV-AUR-001",
    "EV-AUR-002",
    "EV-AUR-003",
    "EV-AUR-004",
    "EV-AUR-005",
}


def _load_manifest_payload(root: Path) -> dict:
    return json.loads((root / MANIFEST_RELATIVE_PATH).read_text(encoding="utf-8"))


def _write_manifest_payload(root: Path, payload: dict) -> None:
    (root / MANIFEST_RELATIVE_PATH).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_ingest_artifacts_produces_five_records(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    records = ingest_artifacts(tmp_path / ARTIFACT_ROOT)
    assert len(records) == 5
    assert all(isinstance(record, EvidenceRecord) for record in records)


def test_ingest_artifacts_has_exact_stable_ids(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    records = ingest_artifacts(tmp_path / ARTIFACT_ROOT)
    assert {record.source_id for record in records} == EXPECTED_SOURCE_IDS
    assert {record.evidence_id for record in records} == EXPECTED_EVIDENCE_IDS


def test_ingest_artifacts_returns_deterministic_order(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    records = ingest_artifacts(tmp_path / ARTIFACT_ROOT)
    assert [record.evidence_id for record in records] == [
        "EV-AUR-001",
        "EV-AUR-003",
        "EV-AUR-002",
        "EV-AUR-004",
        "EV-AUR-005",
    ]
    positions = [record.timeline_position for record in records]
    assert positions == sorted(positions)


def test_ingest_artifacts_preserves_material_evidence_text(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    records = {record.evidence_id: record for record in ingest_artifacts(tmp_path / ARTIFACT_ROOT)}

    assert "Northlight Studio" in records["EV-AUR-001"].content
    assert "Harbor House" in records["EV-AUR-002"].content
    assert "Northlight Studio" in records["EV-AUR-003"].content
    assert "Harbor House" in records["EV-AUR-004"].content
    assert "Briefing date: 2026-07-17" in records["EV-AUR-005"].content
    assert "mismatch" in records["EV-AUR-005"].content


def test_two_independent_generations_yield_identical_records(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    generate_project_aurora_fixture(first_root)
    generate_project_aurora_fixture(second_root)

    first_records = ingest_artifacts(first_root / ARTIFACT_ROOT)
    second_records = ingest_artifacts(second_root / ARTIFACT_ROOT)
    assert first_records == second_records


def test_evidence_manifest_is_deterministic(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    generate_project_aurora_fixture(first_root)
    generate_project_aurora_fixture(second_root)

    first_bytes = (first_root / MANIFEST_RELATIVE_PATH).read_bytes()
    second_bytes = (second_root / MANIFEST_RELATIVE_PATH).read_bytes()
    assert first_bytes == second_bytes


def test_evidence_manifest_excludes_ground_truth_and_test_only(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    payload = _load_manifest_payload(tmp_path)
    assert payload["schema_version"] == 1
    assert payload["project"] == "Project Aurora"
    assert len(payload["artifacts"]) == 5
    for entry in payload["artifacts"]:
        assert "test_only" not in entry["uri"]
        assert entry["uri"] != "ground_truth.json"
        assert entry["uri"] != MANIFEST_RELATIVE_PATH.name


def test_ingest_artifacts_rejects_checksum_mismatch(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    (artifact_root / "email" / "investor_approval.eml").write_bytes(b"tampered content")

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_missing_manifest(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    (artifact_root / "evidence_manifest.json").unlink()

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_malformed_manifest(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    (artifact_root / "evidence_manifest.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_duplicate_source_id(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    duplicate = copy.deepcopy(payload["artifacts"][0])
    duplicate["evidence_id"] = "EV-AUR-999"
    payload["artifacts"].append(duplicate)
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_duplicate_evidence_id(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    duplicate = copy.deepcopy(payload["artifacts"][0])
    duplicate["source_id"] = "aurora-duplicate-source-999"
    payload["artifacts"].append(duplicate)
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_unsupported_source_type(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    payload["artifacts"][0]["source_type"] = "audio"
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_absolute_path(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    payload["artifacts"][0]["uri"] = "/etc/passwd"
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_path_traversal(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    payload["artifacts"][0]["uri"] = "../../outside.txt"
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_ground_truth_and_test_only_reference(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    payload["artifacts"][0]["uri"] = "test_only/ground_truth.json"
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingestion_module_does_not_import_fixture_generator() -> None:
    source = Path("src/continuity_ai/ingestion.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="src/continuity_ai/ingestion.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "aurora_fixture" not in node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "aurora_fixture" not in alias.name


def test_production_reasoning_remains_unimplemented(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    with pytest.raises(ReasoningPipelineNotImplementedError):
        answer_morning_question(tmp_path / ARTIFACT_ROOT, "placeholder question")
