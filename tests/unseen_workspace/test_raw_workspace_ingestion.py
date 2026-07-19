from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from continuity_ai.unseen_workspace.generator import generate_unseen_workspace
from continuity_ai.unseen_workspace.ingestion import (
    RawWorkspaceIngestionError,
    load_workspace,
)


def _manifest(run: Path) -> dict[str, object]:
    return json.loads((run / "input" / "workspace.json").read_text(encoding="utf-8"))


def _write_manifest(run: Path, payload: dict[str, object]) -> None:
    (run / "input" / "workspace.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _generated(tmp_path: Path, seed: int = 123) -> Path:
    run = tmp_path / "run"
    generate_unseen_workspace(run, seed)
    return run


def test_loader_ingests_all_three_raw_formats(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    workspace = load_workspace(run / "input")

    assert len(workspace.records) == 15
    assert {record.source_format for record in workspace.records} == {"txt", "md", "json"}
    assert all(record.content for record in workspace.records)
    assert workspace.target_project.name.startswith("Project ")


def test_loader_needs_only_detached_input_directory(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    detached = tmp_path / "detached-input"
    shutil.copytree(run / "input", detached)

    workspace = load_workspace(detached)

    assert len(workspace.records) == 15
    assert not (detached.parent / "oracle").exists()


def test_loader_rejects_generated_run_parent_and_cannot_discover_oracle(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    with pytest.raises(RawWorkspaceIngestionError):
        load_workspace(run)

    workspace = load_workspace(run / "input")
    returned_paths = {record.relative_path for record in workspace.records}
    assert all(path.startswith("records/") for path in returned_paths)
    assert all("oracle" not in path.casefold() for path in returned_paths)


def test_loader_rejects_path_traversal(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    payload = _manifest(run)
    payload["records"][0]["path"] = "records/../../oracle/expected_scope.json"
    _write_manifest(run, payload)

    with pytest.raises(RawWorkspaceIngestionError):
        load_workspace(run / "input")


def test_loader_rejects_absolute_and_windows_drive_paths(tmp_path: Path) -> None:
    for index, unsafe_path in enumerate(("/etc/passwd", "C:/outside.txt", "C:outside.txt")):
        run = tmp_path / f"run-{index}"
        generate_unseen_workspace(run, index)
        payload = _manifest(run)
        payload["records"][0]["path"] = unsafe_path
        _write_manifest(run, payload)
        with pytest.raises(RawWorkspaceIngestionError):
            load_workspace(run / "input")


def test_loader_rejects_unsafe_record_symlink_where_supported(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    payload = _manifest(run)
    record_path = run / "input" / Path(*payload["records"][0]["path"].split("/"))
    record_path.unlink()
    try:
        os.symlink(run / "oracle" / "expected_scope.json", record_path)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable on this platform: {exc}")

    with pytest.raises(RawWorkspaceIngestionError):
        load_workspace(run / "input")


def test_loader_rejects_symlinked_records_directory_where_supported(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    original_records = run / "input" / "records"
    moved_records = run / "real-records"
    original_records.rename(moved_records)
    try:
        os.symlink(moved_records, original_records, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks unavailable on this platform: {exc}")

    with pytest.raises(RawWorkspaceIngestionError):
        load_workspace(run / "input")


def test_loader_fails_closed_on_malformed_json_record(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    payload = _manifest(run)
    entry = next(record for record in payload["records"] if record["format"] == "json")
    record_path = run / "input" / Path(*entry["path"].split("/"))
    malformed = b"{not valid json"
    record_path.write_bytes(malformed)
    entry["sha256"] = hashlib.sha256(malformed).hexdigest()
    _write_manifest(run, payload)

    with pytest.raises(RawWorkspaceIngestionError, match="malformed JSON"):
        load_workspace(run / "input")


def test_loader_rejects_referenced_unsupported_format(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    payload = _manifest(run)
    entry = payload["records"][0]
    old_path = run / "input" / Path(*entry["path"].split("/"))
    new_path = old_path.with_suffix(".csv")
    old_path.rename(new_path)
    entry["format"] = "csv"
    entry["path"] = f"records/{new_path.name}"
    _write_manifest(run, payload)

    with pytest.raises(RawWorkspaceIngestionError, match="Unsupported record format"):
        load_workspace(run / "input")


def test_loader_rejects_unreferenced_unsupported_or_undeclared_files(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    (run / "input" / "records" / "surprise.csv").write_text("hidden,data\n", encoding="utf-8")

    with pytest.raises(RawWorkspaceIngestionError):
        load_workspace(run / "input")


def test_loader_rejects_empty_workspace(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    payload = _manifest(run)
    payload["records"] = []
    _write_manifest(run, payload)

    with pytest.raises(RawWorkspaceIngestionError, match="non-empty"):
        load_workspace(run / "input")


def test_loader_rejects_duplicate_record_identity_case_insensitively(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    payload = _manifest(run)
    payload["records"][1]["evidence_id"] = payload["records"][0]["evidence_id"].lower()
    _write_manifest(run, payload)

    with pytest.raises(RawWorkspaceIngestionError, match="Duplicate evidence_id"):
        load_workspace(run / "input")


def test_loader_rejects_duplicate_record_path_case_insensitively(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    payload = _manifest(run)
    payload["records"][1]["path"] = payload["records"][0]["path"].upper()
    payload["records"][1]["format"] = payload["records"][0]["format"]
    _write_manifest(run, payload)

    with pytest.raises(RawWorkspaceIngestionError):
        load_workspace(run / "input")


def test_loader_rejects_checksum_mismatch(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    payload = _manifest(run)
    record_path = run / "input" / Path(*payload["records"][0]["path"].split("/"))
    record_path.write_bytes(record_path.read_bytes() + b"tampered")

    with pytest.raises(RawWorkspaceIngestionError, match="checksum mismatch"):
        load_workspace(run / "input")


def test_loader_rejects_oracle_material_copied_into_input_root(tmp_path: Path) -> None:
    run = _generated(tmp_path)
    shutil.copy2(run / "oracle" / "expected_scope.json", run / "input" / "expected_scope.json")

    with pytest.raises(RawWorkspaceIngestionError):
        load_workspace(run / "input")


def test_loader_rejects_unexpected_json_fields_and_empty_content(tmp_path: Path) -> None:
    for seed, mutation in (
        (11, {"unexpected": "answer"}),
        (12, {"schema_version": 1, "content": "  \n "}),
    ):
        run = tmp_path / f"run-{seed}"
        generate_unseen_workspace(run, seed)
        payload = _manifest(run)
        entry = next(record for record in payload["records"] if record["format"] == "json")
        record_path = run / "input" / Path(*entry["path"].split("/"))
        record_bytes = (json.dumps(mutation) + "\n").encode("utf-8")
        record_path.write_bytes(record_bytes)
        entry["sha256"] = hashlib.sha256(record_bytes).hexdigest()
        _write_manifest(run, payload)
        with pytest.raises(RawWorkspaceIngestionError):
            load_workspace(run / "input")


def test_input_loader_source_has_no_oracle_contract_dependency() -> None:
    source = Path("src/continuity_ai/unseen_workspace/ingestion.py").read_text(encoding="utf-8")
    assert "expected_scope" not in source
    assert "scenario_tags" not in source
    assert "expected_status" not in source
