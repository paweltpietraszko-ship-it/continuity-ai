"""End-to-end proof of the frozen mixed -> review -> approved-only ->
same-session resume flow, driven entirely through a scripted fake Codex CLI
process (no live network). See test_codex_session_live.py for the
corresponding real-Codex proof that resume survives a `--cd` change to a
physically separate approved workspace.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from continuity_ai.aurora_fixture import generate_project_aurora_fixture
from continuity_ai.codex_process import (
    CodexCliCapabilities,
    CodexCliProcessAdapter,
    workspace_fingerprint,
)
from continuity_ai.codex_session import (
    CodexOperationRequest,
    CodexSessionController,
    CodexSessionMismatch,
    JsonSessionStore,
    SessionPhase,
    WorkspaceMismatch,
)
from continuity_ai.errors import ValidationError
from continuity_ai.evidence import artifact_to_reasoning, build_spans, order_evidence
from continuity_ai.ingestion import ingest_artifacts, read_project_name
from continuity_ai.integration.approved_workspace_flow import materialize_approved_scope
from continuity_ai.integration.codex_session_flow import (
    record_scope_awaiting_review,
    start_mixed_workspace_investigation,
)
from continuity_ai.integration.mixed_to_approved_pipeline import (
    run_mixed_to_approved_pipeline,
)
from continuity_ai.integration.source_scope_binding import SourceRegistryEntry
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.review import approve_source_scope

THREAD_ID = "12345678-1234-5678-9234-567812345678"

REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["report"],
    "properties": {"report": {"type": "string", "minLength": 1}},
}
REPORT_RESPONSE = json.dumps({"report": "Approved evidence only."})


@dataclass
class ScriptedRunner:
    """Returns one scripted response/thread-id pair per successive invocation."""

    responses: list[str]
    thread_ids: list[str | None]

    def __post_init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(options)))
        index = len(self.calls) - 1
        response = self.responses[min(index, len(self.responses) - 1)]
        thread_id = self.thread_ids[min(index, len(self.thread_ids) - 1)]
        response_path = Path(command[command.index("--output-last-message") + 1])
        response_path.write_text(response, encoding="utf-8")
        stdout = (
            ""
            if thread_id is None
            else json.dumps({"type": "thread.started", "thread_id": thread_id}) + "\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def _controller(tmp_path: Path, runner: ScriptedRunner) -> tuple[CodexSessionController, JsonSessionStore]:
    adapter = CodexCliProcessAdapter(
        "codex",
        resolved_executable=Path(sys.executable),
        version="codex-cli test",
        capabilities=CodexCliCapabilities(True, True, True, True, True, resume_verified=True),
        process_runner=runner,
    )
    store = JsonSessionStore(tmp_path / "sessions.json")
    return CodexSessionController(store, adapter), store


def _load_project(tmp_path: Path):
    generate_project_aurora_fixture(tmp_path)
    artifact_root = (tmp_path / "fixtures/project_aurora/generated/artifacts").resolve()
    raw_records = ingest_artifacts(artifact_root)
    records = order_evidence(tuple(artifact_to_reasoning(r) for r in raw_records))
    target = read_project_name(artifact_root)
    return artifact_root, target, records


def _registry(records) -> dict[str, SourceRegistryEntry]:
    return {
        record.evidence_id: SourceRegistryEntry(
            relative_path=record.uri, sha256=record.artifact_sha256
        )
        for record in records
    }


def _overrides_with_one_exclusion(records) -> tuple[dict[str, str], str]:
    excluded_id = records[0].evidence_id
    overrides = {record.evidence_id: "included" for record in records}
    overrides[excluded_id] = "excluded"
    return overrides, excluded_id


def test_same_controller_and_codex_session_used_throughout_and_exclude_absent(
    tmp_path: Path,
) -> None:
    mixed_root, target, records = _load_project(tmp_path)
    spans = build_spans(records)
    classification = json.dumps(
        FakeSourceScopingProvider().classify(target, records, spans)
    )
    runner = ScriptedRunner([classification, REPORT_RESPONSE], [THREAD_ID, THREAD_ID])
    controller, store = _controller(tmp_path, runner)
    overrides, excluded_id = _overrides_with_one_exclusion(records)
    registry = _registry(records)
    destination = tmp_path / "approved_out"

    result = run_mixed_to_approved_pipeline(
        controller,
        mixed_root,
        target,
        records,
        overrides,
        registry,
        destination,
        CodexOperationRequest("Report on the approved evidence only.", REPORT_SCHEMA, 30),
    )

    assert result.codex_session_id == THREAD_ID
    assert result.reporting.codex_session_id == THREAD_ID
    assert result.reporting.session.phase is SessionPhase.REPORTING
    assert result.reporting.receipt.resume_attempted is True
    assert result.reporting.receipt.new_codex_session_created is False
    assert len(runner.calls) == 2

    investigation_command, investigation_options = runner.calls[0]
    reporting_command, reporting_options = runner.calls[1]
    assert "resume" not in investigation_command
    assert investigation_options["cwd"] == mixed_root
    assert "resume" in reporting_command
    assert THREAD_ID in reporting_command
    assert reporting_options["cwd"] == destination.resolve()

    excluded_record = next(r for r in records if r.evidence_id == excluded_id)
    assert not (destination / excluded_record.uri).exists()
    for evidence_id in result.approved_scope.approved_evidence_ids:
        record = next(r for r in records if r.evidence_id == evidence_id)
        assert (destination / record.uri).is_file()

    stored = store.load(result.controller_session_id)
    assert stored.codex_session_id == THREAD_ID
    assert stored.phase is SessionPhase.REPORTING


def test_reporting_cannot_use_mixed_workspace(tmp_path: Path) -> None:
    mixed_root, target, records = _load_project(tmp_path)
    spans = build_spans(records)
    classification = json.dumps(
        FakeSourceScopingProvider().classify(target, records, spans)
    )
    runner = ScriptedRunner([classification, REPORT_RESPONSE], [THREAD_ID, THREAD_ID])
    controller, _ = _controller(tmp_path, runner)

    investigation = start_mixed_workspace_investigation(
        controller, mixed_root, target, records, spans
    )
    record_scope_awaiting_review(controller, investigation.controller_session_id)
    overrides, _ = _overrides_with_one_exclusion(records)
    approved_scope = approve_source_scope(investigation.scoping_result, records, overrides)
    registry = _registry(records)
    destination = tmp_path / "approved_out"
    materialization = materialize_approved_scope(
        mixed_root, approved_scope, records, registry, destination
    )
    controller.bind_approved_workspace(
        investigation.controller_session_id,
        materialization.destination_root,
        workspace_fingerprint(materialization.destination_root),
    )
    calls_before = len(runner.calls)

    with pytest.raises(WorkspaceMismatch):
        controller.start_reporting(
            investigation.controller_session_id,
            mixed_root,
            CodexOperationRequest("Report.", REPORT_SCHEMA, 30),
        )

    assert len(runner.calls) == calls_before


def test_failed_materialization_prevents_binding_and_reporting(tmp_path: Path) -> None:
    mixed_root, target, records = _load_project(tmp_path)
    spans = build_spans(records)
    classification = json.dumps(
        FakeSourceScopingProvider().classify(target, records, spans)
    )
    runner = ScriptedRunner([classification, REPORT_RESPONSE], [THREAD_ID, THREAD_ID])
    controller, store = _controller(tmp_path, runner)
    overrides, excluded_id = _overrides_with_one_exclusion(records)
    registry = _registry(records)
    missing_id = next(
        evidence_id for evidence_id, status in overrides.items() if status == "included"
    )
    del registry[missing_id]
    destination = tmp_path / "approved_out"

    with pytest.raises(ValidationError):
        run_mixed_to_approved_pipeline(
            controller,
            mixed_root,
            target,
            records,
            overrides,
            registry,
            destination,
            CodexOperationRequest("Report.", REPORT_SCHEMA, 30),
        )

    assert len(runner.calls) == 1
    assert not destination.exists()
    document = json.loads(store.path.read_text(encoding="utf-8"))
    (session_record,) = document["sessions"].values()
    assert session_record["phase"] == "awaiting_human_review"
    assert session_record["codex_session_id"] == THREAD_ID


def test_stale_scope_after_evidence_change_fails_closed_before_reporting(
    tmp_path: Path,
) -> None:
    mixed_root, target, records = _load_project(tmp_path)
    spans = build_spans(records)
    classification = json.dumps(
        FakeSourceScopingProvider().classify(target, records, spans)
    )
    runner = ScriptedRunner([classification, REPORT_RESPONSE], [THREAD_ID, THREAD_ID])
    controller, _ = _controller(tmp_path, runner)

    investigation = start_mixed_workspace_investigation(
        controller, mixed_root, target, records, spans
    )
    record_scope_awaiting_review(controller, investigation.controller_session_id)
    overrides, _ = _overrides_with_one_exclusion(records)
    approved_scope = approve_source_scope(investigation.scoping_result, records, overrides)
    registry = _registry(records)
    destination = tmp_path / "approved_out"

    approved_id = approved_scope.approved_evidence_ids[0]
    changed_records = tuple(
        replace(record, content=record.content + " changed after approval")
        if record.evidence_id == approved_id
        else record
        for record in records
    )
    calls_before = len(runner.calls)

    with pytest.raises(ValidationError):
        materialize_approved_scope(
            mixed_root, approved_scope, changed_records, registry, destination
        )

    assert len(runner.calls) == calls_before
    assert not destination.exists()
    retained = controller.get_session(investigation.controller_session_id)
    assert retained.phase is SessionPhase.AWAITING_HUMAN_REVIEW


def test_no_replacement_session_on_reporting_id_mismatch(tmp_path: Path) -> None:
    mixed_root, target, records = _load_project(tmp_path)
    spans = build_spans(records)
    classification = json.dumps(
        FakeSourceScopingProvider().classify(target, records, spans)
    )
    replacement_id = "87654321-4321-6789-9234-567812345678"
    runner = ScriptedRunner(
        [classification, REPORT_RESPONSE], [THREAD_ID, replacement_id]
    )
    controller, store = _controller(tmp_path, runner)
    overrides, _ = _overrides_with_one_exclusion(records)
    registry = _registry(records)
    destination = tmp_path / "approved_out"

    with pytest.raises(CodexSessionMismatch):
        run_mixed_to_approved_pipeline(
            controller,
            mixed_root,
            target,
            records,
            overrides,
            registry,
            destination,
            CodexOperationRequest("Report.", REPORT_SCHEMA, 30),
        )

    assert len(runner.calls) == 2
    document = json.loads(store.path.read_text(encoding="utf-8"))
    (session_record,) = document["sessions"].values()
    assert session_record["codex_session_id"] == THREAD_ID
    assert session_record["phase"] == "approved"


@pytest.mark.live_network
def test_real_local_codex_runs_the_full_vertical_flow_and_resumes_on_approved_workspace(
    tmp_path: Path,
) -> None:
    """The full vertical flow against the real local Codex CLI: a genuine
    Codex-backed Source Scoping classification, human-approved materialization,
    and reporting resumed in the exact same Codex thread on a physically
    separate approved-only workspace."""
    mixed_root, target, records = _load_project(tmp_path)
    store = JsonSessionStore(tmp_path / "sessions.json")
    controller = CodexSessionController.with_local_codex(store)
    if not controller.process_adapter.capabilities.resume_supported:
        pytest.skip("Local Codex CLI does not support verified resume.")

    overrides, excluded_id = _overrides_with_one_exclusion(records)
    registry = _registry(records)
    destination = tmp_path / "approved_out"
    listing_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["relative_paths"],
        "properties": {
            "relative_paths": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            }
        },
    }

    result = run_mixed_to_approved_pipeline(
        controller,
        mixed_root,
        target,
        records,
        overrides,
        registry,
        destination,
        CodexOperationRequest(
            (
                "List the relative path of every regular file in the current "
                "workspace, excluding anything under a directory named "
                ".continuity. Return them sorted as relative_paths."
            ),
            listing_schema,
            120,
        ),
        investigation_timeout_seconds=120,
    )

    assert result.reporting.session.phase is SessionPhase.REPORTING
    assert result.reporting.receipt.resume_attempted is True
    assert result.reporting.receipt.new_codex_session_created is False
    assert result.reporting.codex_session_id == result.codex_session_id

    excluded_record = next(r for r in records if r.evidence_id == excluded_id)
    reported_paths = set(result.reporting.structured_output["relative_paths"])
    approved_paths = {
        next(r for r in records if r.evidence_id == evidence_id).uri
        for evidence_id in result.approved_scope.approved_evidence_ids
    }
    assert reported_paths == approved_paths
    assert excluded_record.uri not in reported_paths
