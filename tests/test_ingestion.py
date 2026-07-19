from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pytest
from openpyxl import Workbook
from pypdf import PdfWriter

from continuity_ai.artifact_io import GroundTruthAccessError
from continuity_ai.aurora_fixture import ARTIFACT_ROOT, generate_project_aurora_fixture
from continuity_ai.ingestion import ArtifactIngestionError, ingest_artifacts
from continuity_ai.models import EvidenceRecord
from continuity_ai.reasoning import answer_morning_question
from continuity_ai.reasoning_pipeline import DeterministicOfflineReasoningProvider

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


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _artifact_entry(
    *,
    source_id: str,
    evidence_id: str,
    author: str,
    timestamp: str,
    source_type: str,
    title: str,
    uri: str,
    data: bytes,
) -> dict:
    return {
        "source_id": source_id,
        "evidence_id": evidence_id,
        "author": author,
        "timestamp": timestamp,
        "source_type": source_type,
        "title": title,
        "uri": uri,
        "sha256": _sha256_hex(data),
    }


def _write_hand_built_manifest(root: Path, entries: list[dict], project: str = "Unrelated Test Project") -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "project": project, "artifacts": entries}
    (root / "evidence_manifest.json").write_text(
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
    parsed_timestamps = [datetime.fromisoformat(record.timestamp) for record in records]
    assert parsed_timestamps == sorted(parsed_timestamps)


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


def test_ingest_artifacts_rejects_unexpected_top_level_field(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    payload["unexpected_extra"] = "surprise"
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_reintroduced_interpretive_field(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    payload["artifacts"][0]["timeline_position"] = 1
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_non_hex_sha256(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    payload["artifacts"][0]["sha256"] = "g" * 64
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_malformed_timestamp(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    payload["artifacts"][0]["timestamp"] = "not-a-timestamp"
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_timestamp_without_timezone(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    payload["artifacts"][0]["timestamp"] = "2026-07-16T15:40:00"
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_non_string_timestamp(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    payload["artifacts"][0]["timestamp"] = 12345
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_invalid_utf8_manifest(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    (artifact_root / "evidence_manifest.json").write_bytes(b"\xff\xfe\x00invalid")

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_windows_drive_path(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    payload["artifacts"][0]["uri"] = "C:/outside.txt"
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_windows_drive_relative_path(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    payload["artifacts"][0]["uri"] = "C:outside.txt"
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_duplicate_uri(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    duplicate = copy.deepcopy(payload["artifacts"][0])
    duplicate["source_id"] = "aurora-duplicate-uri-source"
    duplicate["evidence_id"] = "EV-AUR-998"
    payload["artifacts"].append(duplicate)
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_duplicate_uri_differing_only_by_case(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    payload = _load_manifest_payload(tmp_path)
    duplicate = copy.deepcopy(payload["artifacts"][0])
    duplicate["source_id"] = "aurora-duplicate-uri-case-source"
    duplicate["evidence_id"] = "EV-AUR-997"
    duplicate["uri"] = duplicate["uri"].upper()
    payload["artifacts"].append(duplicate)
    _write_manifest_payload(tmp_path, payload)

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_case_variant_forbidden_directory(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    variant_dir = artifact_root / "TEST_ONLY"
    variant_dir.mkdir()
    (variant_dir / "notes.txt").write_text("irrelevant", encoding="utf-8")

    with pytest.raises(GroundTruthAccessError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_case_variant_forbidden_filename(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    (artifact_root / "Ground_Truth.json").write_text("{}", encoding="utf-8")

    with pytest.raises(GroundTruthAccessError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_forbidden_file_present_but_unreferenced(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / ARTIFACT_ROOT
    (artifact_root / "call_sheets" / "ground_truth.json").write_text("{}", encoding="utf-8")

    with pytest.raises(GroundTruthAccessError):
        ingest_artifacts(artifact_root)


def test_ingest_artifacts_rejects_empty_markdown(tmp_path: Path) -> None:
    root = tmp_path / "empty_markdown_root"
    content = b"   \n\n  \n"
    root.mkdir()
    (root / "empty.md").write_bytes(content)
    entry = _artifact_entry(
        source_id="src-empty-md",
        evidence_id="EV-EMPTY-MD",
        author="Tester",
        timestamp="2030-01-01T00:00:00Z",
        source_type="markdown",
        title="Empty markdown",
        uri="empty.md",
        data=content,
    )
    _write_hand_built_manifest(root, [entry])

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(root)


def test_ingest_artifacts_rejects_bodyless_email(tmp_path: Path) -> None:
    root = tmp_path / "empty_email_root"
    root.mkdir()
    message = EmailMessage()
    message["From"] = "nobody@example.invalid"
    message["To"] = "nobody@example.invalid"
    message["Subject"] = ""
    message.set_content("")
    content = message.as_bytes(policy=message.policy.clone(linesep="\n"))
    (root / "empty.eml").write_bytes(content)
    entry = _artifact_entry(
        source_id="src-empty-eml",
        evidence_id="EV-EMPTY-EML",
        author="Tester",
        timestamp="2030-01-01T00:00:00Z",
        source_type="email",
        title="Empty email",
        uri="empty.eml",
        data=content,
    )
    _write_hand_built_manifest(root, [entry])

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(root)


def test_ingest_artifacts_rejects_calendar_with_no_meaningful_fields(tmp_path: Path) -> None:
    root = tmp_path / "empty_ics_root"
    root.mkdir()
    text = "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Test//Empty//EN",
            "BEGIN:VEVENT",
            "UID:empty-event@example.invalid",
            "DTSTAMP:20300101T000000Z",
            "DTSTART:20300101T000000Z",
            "DTEND:20300101T010000Z",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    content = text.encode("utf-8")
    (root / "empty.ics").write_bytes(content)
    entry = _artifact_entry(
        source_id="src-empty-ics",
        evidence_id="EV-EMPTY-ICS",
        author="Tester",
        timestamp="2030-01-01T00:00:00Z",
        source_type="calendar",
        title="Empty calendar",
        uri="empty.ics",
        data=content,
    )
    _write_hand_built_manifest(root, [entry])

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(root)


def test_ingest_artifacts_rejects_spreadsheet_with_no_meaningful_cells(tmp_path: Path) -> None:
    root = tmp_path / "empty_xlsx_root"
    root.mkdir()
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([None, None])
    sheet.append([None])
    buffer = io.BytesIO()
    workbook.save(buffer)
    content = buffer.getvalue()
    (root / "empty.xlsx").write_bytes(content)
    entry = _artifact_entry(
        source_id="src-empty-xlsx",
        evidence_id="EV-EMPTY-XLSX",
        author="Tester",
        timestamp="2030-01-01T00:00:00Z",
        source_type="spreadsheet",
        title="Empty spreadsheet",
        uri="empty.xlsx",
        data=content,
    )
    _write_hand_built_manifest(root, [entry])

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(root)


def test_ingest_artifacts_rejects_pdf_with_no_extractable_text(tmp_path: Path) -> None:
    root = tmp_path / "empty_pdf_root"
    root.mkdir()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    content = buffer.getvalue()
    (root / "empty.pdf").write_bytes(content)
    entry = _artifact_entry(
        source_id="src-empty-pdf",
        evidence_id="EV-EMPTY-PDF",
        author="Tester",
        timestamp="2030-01-01T00:00:00Z",
        source_type="pdf",
        title="Empty pdf",
        uri="empty.pdf",
        data=content,
    )
    _write_hand_built_manifest(root, [entry])

    with pytest.raises(ArtifactIngestionError):
        ingest_artifacts(root)


def test_ingest_artifacts_follows_on_disk_contract_not_fixture_constants(tmp_path: Path) -> None:
    root = tmp_path / "unrelated_root"
    root.mkdir()
    content = b"# Unrelated Note\n\nThis project has nothing to do with the fixture scenario.\n"
    (root / "unrelated.md").write_bytes(content)
    entry = _artifact_entry(
        source_id="unrelated-source-42",
        evidence_id="EV-UNRELATED-042",
        author="Someone Else",
        timestamp="2030-01-02T03:04:05+00:00",
        source_type="markdown",
        title="Totally unrelated note",
        uri="unrelated.md",
        data=content,
    )
    _write_hand_built_manifest(root, [entry])

    records = ingest_artifacts(root)
    assert len(records) == 1
    record = records[0]
    assert record.source_id == "unrelated-source-42"
    assert record.evidence_id == "EV-UNRELATED-042"
    assert record.title == "Totally unrelated note"
    assert "Unrelated Note" in record.content
    assert "Aurora" not in record.content
    assert "Northlight" not in record.content
    assert "Harbor House" not in record.content


def test_ingest_artifacts_breaks_timestamp_ties_by_evidence_id(tmp_path: Path) -> None:
    root = tmp_path / "tie_break_root"
    root.mkdir()
    content_a = b"Alpha content unrelated to the fixture.\n"
    content_b = b"Bravo content unrelated to the fixture.\n"
    (root / "alpha.md").write_bytes(content_a)
    (root / "bravo.md").write_bytes(content_b)

    shared_timestamp = "2030-05-01T12:00:00Z"
    entry_b = _artifact_entry(
        source_id="source-bravo",
        evidence_id="EV-B",
        author="B Author",
        timestamp=shared_timestamp,
        source_type="markdown",
        title="Bravo",
        uri="bravo.md",
        data=content_b,
    )
    entry_a = _artifact_entry(
        source_id="source-alpha",
        evidence_id="EV-A",
        author="A Author",
        timestamp=shared_timestamp,
        source_type="markdown",
        title="Alpha",
        uri="alpha.md",
        data=content_a,
    )
    _write_hand_built_manifest(root, [entry_b, entry_a])

    records = ingest_artifacts(root)
    assert [record.evidence_id for record in records] == ["EV-A", "EV-B"]


def test_ingest_artifacts_orders_by_timestamp_not_manifest_order_or_alphabetical_id(tmp_path: Path) -> None:
    root = tmp_path / "chronology_root"
    root.mkdir()
    early = b"Earliest unrelated content.\n"
    middle = b"Middle unrelated content.\n"
    late = b"Latest unrelated content.\n"
    (root / "early.md").write_bytes(early)
    (root / "middle.md").write_bytes(middle)
    (root / "late.md").write_bytes(late)

    entry_late = _artifact_entry(
        source_id="src-late",
        evidence_id="EV-AAA-late",
        author="Tester",
        timestamp="2030-01-03T00:00:00Z",
        source_type="markdown",
        title="Late",
        uri="late.md",
        data=late,
    )
    entry_early = _artifact_entry(
        source_id="src-early",
        evidence_id="EV-ZZZ-early",
        author="Tester",
        timestamp="2030-01-01T00:00:00Z",
        source_type="markdown",
        title="Early",
        uri="early.md",
        data=early,
    )
    entry_middle = _artifact_entry(
        source_id="src-middle",
        evidence_id="EV-MMM-middle",
        author="Tester",
        timestamp="2030-01-02T00:00:00Z",
        source_type="markdown",
        title="Middle",
        uri="middle.md",
        data=middle,
    )
    # Manifest array order and evidence_id alphabetical order both differ from
    # chronological order, so a correct result proves sorting is timestamp-driven.
    _write_hand_built_manifest(root, [entry_late, entry_middle, entry_early])

    records = ingest_artifacts(root)
    assert [record.evidence_id for record in records] == [
        "EV-ZZZ-early",
        "EV-MMM-middle",
        "EV-AAA-late",
    ]


def test_ingestion_module_does_not_import_fixture_generator() -> None:
    source = Path("src/continuity_ai/ingestion.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="src/continuity_ai/ingestion.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "aurora_fixture" not in node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "aurora_fixture" not in alias.name


def test_production_reasoning_runs_offline_fake_provider(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    result = answer_morning_question(
        tmp_path / ARTIFACT_ROOT,
        "placeholder question",
        provider=DeterministicOfflineReasoningProvider(),
    )
    assert result["analysis_status"] == "no_material_break_found"
