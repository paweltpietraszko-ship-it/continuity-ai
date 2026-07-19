"""Tests for the Codex-backed Project Report generation adapter."""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from continuity_ai.aurora_fixture import generate_project_aurora_fixture
from continuity_ai.codex_process import CodexCliCapabilities, CodexCliProcessAdapter
from continuity_ai.codex_session import (
    CodexSessionController,
    InvalidCodexOutput,
    JsonSessionStore,
    SessionPhase,
)
from continuity_ai.errors import ValidationError
from continuity_ai.evidence import artifact_to_reasoning, build_spans, order_evidence
from continuity_ai.ingestion import ingest_artifacts
from continuity_ai.integration.codex_reasoning_provider import (
    _codex_report_schema,
    run_codex_reporting_analysis,
)
from continuity_ai.prompts import reasoning_response_schema
from continuity_ai.reasoning_pipeline import DeterministicOfflineReasoningProvider

THREAD_ID = "12345678-1234-5678-9234-567812345678"


@dataclass
class ScriptedRunner:
    responses: list[str]
    thread_ids: list[str | None]

    def __post_init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(
        self, command: list[str], **options: Any
    ) -> subprocess.CompletedProcess[str]:
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


def _controller(
    tmp_path: Path, runner: ScriptedRunner
) -> tuple[CodexSessionController, JsonSessionStore]:
    adapter = CodexCliProcessAdapter(
        "codex",
        resolved_executable=Path(sys.executable),
        version="codex-cli test",
        capabilities=CodexCliCapabilities(
            True, True, True, True, True, resume_verified=True
        ),
        process_runner=runner,
    )
    store = JsonSessionStore(tmp_path / "sessions.json")
    return CodexSessionController(store, adapter), store


def _project(tmp_path: Path):
    generate_project_aurora_fixture(tmp_path)
    artifact_root = (tmp_path / "fixtures/project_aurora/generated/artifacts").resolve()
    records = order_evidence(
        tuple(artifact_to_reasoning(r) for r in ingest_artifacts(artifact_root))
    )
    return artifact_root, records


def test_codex_report_schema_rewrites_multi_type_union_to_any_of() -> None:
    schema = reasoning_response_schema()
    adapted = _codex_report_schema(schema)

    kind_schema = adapted["properties"]["continuity_break_kind"]
    assert "type" not in kind_schema
    assert kind_schema == {
        "anyOf": [
            {
                "type": "string",
                "enum": ["propagation_break", "decision_provenance_not_found"],
            },
            {"type": "null"},
        ]
    }
    # continuity_break/next_action already used anyOf and must pass through untouched.
    assert adapted["properties"]["continuity_break"] == schema["properties"]["continuity_break"]
    assert adapted["properties"]["next_action"] == schema["properties"]["next_action"]
    # Original schema is not mutated.
    assert reasoning_response_schema() == schema


def _investigated_and_approved(tmp_path: Path, runner: ScriptedRunner):
    artifact_root, records = _project(tmp_path)
    controller, store = _controller(tmp_path, runner)
    created = controller.create_session(artifact_root)
    from continuity_ai.codex_session import CodexOperationRequest

    controller.start_investigation(
        created.controller_session_id,
        artifact_root,
        CodexOperationRequest(
            "investigate",
            {"type": "object", "additionalProperties": False, "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            5,
        ),
    )
    waiting = controller.record_awaiting_human_review(created.controller_session_id)
    approved_root = tmp_path / "approved"
    approved_root.mkdir()
    (approved_root / "note.txt").write_text("approved only", encoding="utf-8")
    from continuity_ai.codex_process import workspace_fingerprint

    bound = controller.bind_approved_workspace(
        waiting.controller_session_id, approved_root, workspace_fingerprint(approved_root)
    )
    return controller, store, records, bound.controller_session_id, approved_root


def test_run_codex_reporting_analysis_success(tmp_path: Path) -> None:
    _, first_records = _project(tmp_path)
    spans = build_spans(first_records)
    candidate = DeterministicOfflineReasoningProvider().analyze(first_records, spans, "q")
    runner = ScriptedRunner(
        [json.dumps({"ok": True}), json.dumps(candidate)], [THREAD_ID, THREAD_ID]
    )
    controller, store, records, controller_session_id, approved_root = (
        _investigated_and_approved(tmp_path, runner)
    )

    result, result_spans, snapshot = run_codex_reporting_analysis(
        controller, controller_session_id, approved_root, records, "q"
    )

    assert result.analysis_status == candidate["analysis_status"]
    assert snapshot.provider_id == "codex-reasoning-v1"
    assert result_spans == build_spans(records)
    retained = store.load(controller_session_id)
    assert retained.phase is SessionPhase.REPORTING
    assert retained.codex_session_id == THREAD_ID
    assert retained.last_successful_invocation_receipt.resume_attempted is True
    assert retained.last_successful_invocation_receipt.new_codex_session_created is False


def test_run_codex_reporting_analysis_semantic_rejection_fails_closed(
    tmp_path: Path,
) -> None:
    _, first_records = _project(tmp_path)
    spans = build_spans(first_records)
    candidate = DeterministicOfflineReasoningProvider().analyze(first_records, spans, "q")
    bad_candidate = dict(candidate)
    bad_candidate["current_state"] = dict(
        candidate["current_state"], span_ids=["not-a-real-span-id"]
    )
    runner = ScriptedRunner(
        [json.dumps({"ok": True}), json.dumps(bad_candidate)], [THREAD_ID, THREAD_ID]
    )
    controller, store, records, controller_session_id, approved_root = (
        _investigated_and_approved(tmp_path, runner)
    )

    with pytest.raises(InvalidCodexOutput):
        run_codex_reporting_analysis(
            controller, controller_session_id, approved_root, records, "q"
        )

    retained = store.load(controller_session_id)
    assert retained.phase is SessionPhase.APPROVED
    # The prior successful investigation receipt is preserved, not erased.
    assert retained.last_successful_invocation_receipt is not None
    assert retained.last_successful_invocation_receipt.new_codex_session_created is True
    assert retained.last_invocation_receipt.failure_category is not None
