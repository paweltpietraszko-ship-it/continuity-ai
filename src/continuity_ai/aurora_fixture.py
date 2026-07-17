"""Deterministic Project Aurora fixture generator."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from continuity_ai.models import ArtifactDefinition

FIXED_ZIP_TIMESTAMP = (2026, 7, 17, 9, 0, 0)
GENERATED_ROOT = Path("fixtures/project_aurora/generated")
ARTIFACT_ROOT = GENERATED_ROOT / "artifacts"
TEST_ONLY_ROOT = GENERATED_ROOT / "test_only"
GROUND_TRUTH_PATH = TEST_ONLY_ROOT / "ground_truth.json"
EVIDENCE_MANIFEST_PATH = ARTIFACT_ROOT / "evidence_manifest.json"
_ARTIFACT_ROOT_PREFIX = ARTIFACT_ROOT.as_posix() + "/"

ARTIFACTS: tuple[ArtifactDefinition, ...] = (
    ArtifactDefinition(
        source_id="aurora-email-investor-approval-001",
        evidence_id="EV-AUR-001",
        author="Mara Chen, Investor",
        timestamp="2026-07-16T15:40:00Z",
        source_type="email",
        timeline_position=2,
        business_purpose="Formal investor approval for moving the shoot to Northlight Studio.",
        relative_path="fixtures/project_aurora/generated/artifacts/email/investor_approval.eml",
        title="Investor approval for Northlight Studio move",
    ),
    ArtifactDefinition(
        source_id="aurora-calendar-production-001",
        evidence_id="EV-AUR-002",
        author="Production Office",
        timestamp="2026-07-16T18:10:00Z",
        source_type="calendar",
        timeline_position=4,
        business_purpose="Production calendar entry that still directs crew to Harbor House.",
        relative_path="fixtures/project_aurora/generated/artifacts/calendar/production_calendar.ics",
        title="Production calendar shoot location",
    ),
    ArtifactDefinition(
        source_id="aurora-budget-v4-001",
        evidence_id="EV-AUR-003",
        author="Jon Bell, Line Producer",
        timestamp="2026-07-16T17:05:00Z",
        source_type="spreadsheet",
        timeline_position=3,
        business_purpose="Budget v4 carrying Northlight Studio cost lines.",
        relative_path="fixtures/project_aurora/generated/artifacts/budget/budget_v4.xlsx",
        title="Project Aurora budget v4",
    ),
    ArtifactDefinition(
        source_id="aurora-callsheet-current-001",
        evidence_id="EV-AUR-004",
        author="Assistant Director Office",
        timestamp="2026-07-16T19:30:00Z",
        source_type="pdf",
        timeline_position=5,
        business_purpose="Current call sheet that still lists Harbor House.",
        relative_path="fixtures/project_aurora/generated/artifacts/call_sheets/current_call_sheet.pdf",
        title="Current call sheet",
    ),
    ArtifactDefinition(
        source_id="aurora-crew-briefing-note-001",
        evidence_id="EV-AUR-005",
        author="Nina Patel, Production Coordinator",
        timestamp="2026-07-16T20:00:00Z",
        source_type="markdown",
        timeline_position=6,
        business_purpose="Crew briefing note scheduled for the following day.",
        relative_path="fixtures/project_aurora/generated/artifacts/notes/crew_briefing.md",
        title="Crew briefing preparation note",
    ),
)


def generate_project_aurora_fixture(output_root: Path) -> list[dict[str, str]]:
    """Generate all deterministic Project Aurora artifacts under output_root."""

    written: list[dict[str, str]] = []
    for artifact in ARTIFACTS:
        path = output_root / artifact.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        content_writer = _WRITERS[artifact.source_type]
        content_writer(artifact, path)
        written.append({"path": artifact.relative_path, "sha256": _sha256(path)})

    manifest_path = output_root / EVIDENCE_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_if_changed(manifest_path, _evidence_manifest_json(output_root))
    written.append({"path": EVIDENCE_MANIFEST_PATH.as_posix(), "sha256": _sha256(manifest_path)})

    truth_path = output_root / GROUND_TRUTH_PATH
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_if_changed(truth_path, _ground_truth_json())
    written.append({"path": GROUND_TRUTH_PATH.as_posix(), "sha256": _sha256(truth_path)})
    return written


def manifest(output_root: Path) -> dict[str, Any]:
    """Return metadata and checksums for generated artifacts."""

    return {
        "project": "Project Aurora",
        "artifacts": [
            {
                "source_id": artifact.source_id,
                "evidence_id": artifact.evidence_id,
                "author": artifact.author,
                "timestamp": artifact.timestamp,
                "source_type": artifact.source_type,
                "timeline_position": artifact.timeline_position,
                "business_purpose": artifact.business_purpose,
                "uri": artifact.relative_path,
                "sha256": _sha256(output_root / artifact.relative_path),
            }
            for artifact in ARTIFACTS
        ],
    }


def _write_email(artifact: ArtifactDefinition, path: Path) -> None:
    message = EmailMessage()
    message["From"] = "Mara Chen <mara.chen@example.invalid>"
    message["To"] = "Project Aurora Production <production@example.invalid>"
    message["Date"] = "Thu, 16 Jul 2026 15:40:00 +0000"
    message["Message-ID"] = "<aurora-investor-approval-001@example.invalid>"
    message["Subject"] = "Approved: Project Aurora move to Northlight Studio"
    message.set_content(
        "Mara Chen formally approves moving the Project Aurora shoot from "
        "Harbor House to Northlight Studio. The approval covers the studio "
        "rental and controlled-lighting cost changes reflected in budget v4.\n"
    )
    _write_bytes_if_changed(path, message.as_bytes(policy=message.policy.clone(linesep="\n")))


def _write_ics(artifact: ArtifactDefinition, path: Path) -> None:
    text = "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Continuity AI//Project Aurora Fixture//EN",
            "BEGIN:VEVENT",
            "UID:aurora-production-calendar-001@example.invalid",
            "DTSTAMP:20260716T181000Z",
            "DTSTART:20260718T130000Z",
            "DTEND:20260718T230000Z",
            "SUMMARY:Project Aurora principal photography",
            "LOCATION:Harbor House",
            "DESCRIPTION:Production calendar still lists Harbor House for the shoot.",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    _write_text_if_changed(path, text)


def _write_xlsx(artifact: ArtifactDefinition, path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Budget v4"
    rows = [
        ("Source ID", artifact.source_id),
        ("Prepared by", artifact.author),
        ("Timestamp", artifact.timestamp),
        ("Line item", "Amount USD"),
        ("Northlight Studio rental", 7800),
        ("Northlight controlled lighting package", 2400),
        ("Harbor House location hold release", -1200),
    ]
    for row in rows:
        sheet.append(row)
    workbook.properties.creator = artifact.author
    fixed_time = datetime(2026, 7, 17, 9, 0, 0, tzinfo=timezone.utc)
    workbook.properties.created = fixed_time
    workbook.properties.modified = fixed_time
    workbook.save(path)
    # openpyxl's save_workbook() unconditionally overwrites properties.modified
    # with the real wall-clock time during save, discarding the fixed value set
    # above; repin it in the written XML so output is deterministic regardless.
    _pin_xlsx_modified_timestamp(path, fixed_time)
    _normalize_zip(path)


def _write_pdf(artifact: ArtifactDefinition, path: Path) -> None:
    lines = [
        "%PDF-1.4",
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj",
    ]
    stream_text = (
        "BT /F1 12 Tf 72 720 Td (Project Aurora Current Call Sheet) Tj "
        "0 -24 Td (Source ID: aurora-callsheet-current-001) Tj "
        "0 -24 Td (Location: Harbor House) Tj "
        "0 -24 Td (Crew briefing: 2026-07-17) Tj ET"
    )
    stream = f"4 0 obj << /Length {len(stream_text.encode('latin-1'))} >> stream\n{stream_text}\nendstream endobj"
    lines.append(stream)
    lines.append("5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj")
    offsets: list[int] = [0]
    rendered = "%PDF-1.4\n"
    objects = lines[1:]
    for obj in objects:
        offsets.append(len(rendered.encode("latin-1")))
        rendered += obj + "\n"
    xref_offset = len(rendered.encode("latin-1"))
    xref = ["xref", "0 6", "0000000000 65535 f "]
    xref.extend(f"{offset:010d} 00000 n " for offset in offsets[1:])
    rendered += "\n".join(xref) + "\n"
    rendered += "trailer << /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref_offset) + "\n%%EOF\n"
    _write_bytes_if_changed(path, rendered.encode("latin-1"))


def _write_markdown(artifact: ArtifactDefinition, path: Path) -> None:
    text = f"""# Project Aurora Crew Briefing

- Source ID: {artifact.source_id}
- Author: {artifact.author}
- Timestamp: {artifact.timestamp}
- Briefing date: 2026-07-17
- Purpose: Prepare crew for tomorrow's operational briefing.

The briefing must resolve any mismatch between approved production changes and crew-facing documents before call time.
"""
    _write_text_if_changed(path, text)


def _evidence_manifest_json(output_root: Path) -> str:
    # timeline_position and business_purpose are deliberately omitted: they are
    # interpretive fixture metadata, not facts the artifact itself attests to,
    # and production ingestion must never receive them.
    payload = {
        "schema_version": 1,
        "project": "Project Aurora",
        "artifacts": [
            {
                "source_id": artifact.source_id,
                "evidence_id": artifact.evidence_id,
                "author": artifact.author,
                "timestamp": artifact.timestamp,
                "source_type": artifact.source_type,
                "title": artifact.title,
                "uri": artifact.relative_path.removeprefix(_ARTIFACT_ROOT_PREFIX),
                "sha256": _sha256(output_root / artifact.relative_path),
            }
            for artifact in sorted(ARTIFACTS, key=lambda item: item.source_id)
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _ground_truth_json() -> str:
    payload = {
        "project": "Project Aurora",
        "continuity_break": "The approved location change is reflected in the budget but not in the production calendar or current call sheet.",
        "required_evidence": [
            "aurora-email-investor-approval-001",
            "aurora-budget-v4-001",
            "aurora-calendar-production-001",
            "aurora-callsheet-current-001",
        ],
        "expected_next_action": "Update the production calendar and call sheet before tomorrow's crew briefing.",
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _write_text_if_changed(path: Path, text: str) -> None:
    _write_bytes_if_changed(path, text.encode("utf-8"))


def _write_bytes_if_changed(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() == data:
        return
    path.write_bytes(data)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_CORE_XML_MODIFIED_PATTERN = re.compile(
    rb'(<dcterms:modified xsi:type="dcterms:W3CDTF">)[^<]*(</dcterms:modified>)'
)


def _pin_xlsx_modified_timestamp(path: Path, fixed_time: datetime) -> None:
    fixed_iso = fixed_time.strftime("%Y-%m-%dT%H:%M:%SZ").encode("ascii")
    with zipfile.ZipFile(path, "r") as archive:
        entries = {info.filename: archive.read(info.filename) for info in archive.infolist()}
    entries["docProps/core.xml"] = _CORE_XML_MODIFIED_PATTERN.sub(
        lambda match: match.group(1) + fixed_iso + match.group(2),
        entries["docProps/core.xml"],
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def _normalize_zip(path: Path) -> None:
    original_entries: list[tuple[zipfile.ZipInfo, bytes]] = []
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            original_entries.append((info, archive.read(info.filename)))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for old_info, data in sorted(original_entries, key=lambda item: item[0].filename):
            info = zipfile.ZipInfo(old_info.filename, FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = old_info.external_attr
            archive.writestr(info, data)


_WRITERS = {
    "email": _write_email,
    "calendar": _write_ics,
    "spreadsheet": _write_xlsx,
    "pdf": _write_pdf,
    "markdown": _write_markdown,
}
