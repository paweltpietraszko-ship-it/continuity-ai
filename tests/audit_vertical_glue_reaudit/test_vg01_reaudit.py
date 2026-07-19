"""Independent re-audit evidence for the VG-01 repair.

The final test intentionally characterizes the remaining blocker required by
the re-audit brief: a validator return value can widen the already validated
JSON Schema contract and is currently committed as a successful result.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

import continuity_ai.integration.codex_source_scoping_provider as provider_module
import continuity_ai.source_scoping.service as service_module
from continuity_ai.codex_process import (
    CodexCliCapabilities,
    CodexCliProcessAdapter,
    workspace_fingerprint,
)
from continuity_ai.codex_session import (
    CodexOperationRequest,
    CodexSessionController,
    FailureCategory,
    InvalidCodexOutput,
    JsonSessionStore,
    SessionPhase,
)
from continuity_ai.evidence import build_spans
from continuity_ai.integration.codex_source_scoping_provider import (
    CodexSourceScopingProvider,
)
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.io import load_workspace
from continuity_ai.source_scoping.validator import validate_source_scoping_payload


THREAD_ID = "12345678-1234-5678-9234-567812345678"
REPLACEMENT_THREAD_ID = "87654321-4321-6789-9234-567812345678"
FIXTURE = Path(__file__).parents[2] / "fixtures" / "source_scoping_mixed_workspace"
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string", "minLength": 1}},
}


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
        version="codex-cli reaudit",
        capabilities=CodexCliCapabilities(
            True, True, True, True, True, resume_verified=True
        ),
        process_runner=runner,
    )
    store = JsonSessionStore(tmp_path / "sessions.json")
    return CodexSessionController(store, adapter), store


def _workspace(tmp_path: Path, name: str = "workspace") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "source.txt").write_text("audit input", encoding="utf-8")
    return root.resolve()


def _request(
    validator: Callable[[object], object] | None = None,
) -> CodexOperationRequest:
    return CodexOperationRequest(
        "Inspect the bounded input.",
        SCHEMA,
        30,
        structured_output_validator=validator,
    )


def test_semantic_rejection_is_retriable_and_severs_all_validator_exception_paths(
    tmp_path: Path,
) -> None:
    secret = "validator-secret-evidence"
    runner = ScriptedRunner(
        [json.dumps({"answer": "schema-valid"}), json.dumps({"answer": "retry"})],
        [THREAD_ID, THREAD_ID],
    )
    controller, store = _controller(tmp_path, runner)
    root = _workspace(tmp_path)
    created = controller.create_session(root)

    def reject(_value: object) -> object:
        raise ValueError(secret, {"private": secret})

    with pytest.raises(InvalidCodexOutput) as captured:
        controller.start_investigation(
            created.controller_session_id, root, _request(reject)
        )

    error = captured.value
    receipt = error.receipt
    retained = store.load(created.controller_session_id)
    persisted = store.path.read_text(encoding="utf-8")

    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.args == (
        "Codex operation failed closed with invalid_codex_output.",
    )
    assert secret not in repr(error.args)
    assert secret not in repr(receipt)
    assert secret not in repr(retained)
    assert secret not in persisted
    assert receipt is not None
    assert receipt.failure_category is FailureCategory.INVALID_OUTPUT
    assert receipt.succeeded is False
    assert retained.phase is SessionPhase.READY
    assert retained.codex_session_id is None
    assert retained.last_successful_invocation_receipt is None
    assert retained.last_invocation_receipt == receipt
    assert retained.codex_process_active is False
    assert retained.active_operation is None

    retried = controller.start_investigation(
        created.controller_session_id, root, _request()
    )
    assert retried.receipt.succeeded is True
    assert retried.session.phase is SessionPhase.INVESTIGATING
    assert retried.session.codex_session_id == THREAD_ID


def test_later_semantic_rejection_preserves_prior_success_and_reporting_retry(
    tmp_path: Path,
) -> None:
    runner = ScriptedRunner(
        [json.dumps({"answer": value}) for value in ("investigation", "bad", "retry")],
        [THREAD_ID, THREAD_ID, THREAD_ID],
    )
    controller, store = _controller(tmp_path, runner)
    mixed = _workspace(tmp_path, "mixed")
    created = controller.create_session(mixed)
    investigated = controller.start_investigation(
        created.controller_session_id, mixed, _request()
    )
    prior_success = investigated.receipt
    waiting = controller.record_awaiting_human_review(created.controller_session_id)
    approved = _workspace(tmp_path, "approved")
    bound = controller.bind_approved_workspace(
        waiting.controller_session_id,
        approved,
        workspace_fingerprint(approved),
    )

    def reject(_value: object) -> object:
        raise RuntimeError("semantic report rejection")

    with pytest.raises(InvalidCodexOutput):
        controller.start_reporting(
            bound.controller_session_id, approved, _request(reject)
        )

    rejected = store.load(bound.controller_session_id)
    assert rejected.phase is SessionPhase.APPROVED
    assert rejected.codex_session_id == THREAD_ID
    assert rejected.last_successful_invocation_receipt == prior_success
    assert rejected.last_invocation_receipt != prior_success
    assert (
        rejected.last_invocation_receipt.failure_category
        is FailureCategory.INVALID_OUTPUT
    )
    assert rejected.codex_process_active is False
    assert rejected.active_operation is None

    retried = controller.start_reporting(
        bound.controller_session_id, approved, _request()
    )
    assert retried.receipt.succeeded is True
    assert retried.session.phase is SessionPhase.REPORTING
    assert retried.session.codex_session_id == THREAD_ID


def test_json_schema_rejection_skips_semantic_validator(tmp_path: Path) -> None:
    runner = ScriptedRunner([json.dumps({"answer": 7})], [THREAD_ID])
    controller, store = _controller(tmp_path, runner)
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    calls: list[object] = []

    def forbidden(value: object) -> object:
        calls.append(value)
        raise AssertionError("semantic validator ran after schema rejection")

    with pytest.raises(InvalidCodexOutput):
        controller.start_investigation(
            created.controller_session_id, root, _request(forbidden)
        )

    retained = store.load(created.controller_session_id)
    assert calls == []
    assert retained.phase is SessionPhase.READY
    assert retained.codex_session_id is None
    assert retained.last_successful_invocation_receipt is None
    assert retained.codex_process_active is False
    assert retained.active_operation is None


def test_source_scoping_runs_controller_gate_and_second_canonical_validation_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, evidence = load_workspace(FIXTURE)
    spans = build_spans(evidence)
    payload = FakeSourceScopingProvider().classify(target, evidence, spans)
    runner = ScriptedRunner([json.dumps(payload)], [THREAD_ID])
    controller, _store = _controller(tmp_path, runner)
    created = controller.create_session(FIXTURE)
    provider = CodexSourceScopingProvider(
        controller, created.controller_session_id, FIXTURE, timeout_seconds=30
    )
    calls: list[str] = []

    def controller_pass(*args: object, **kwargs: object) -> object:
        calls.append("controller")
        return validate_source_scoping_payload(*args, **kwargs)

    def service_pass(*args: object, **kwargs: object) -> object:
        calls.append("service")
        return validate_source_scoping_payload(*args, **kwargs)

    monkeypatch.setattr(
        provider_module, "validate_source_scoping_payload", controller_pass
    )
    monkeypatch.setattr(service_module, "validate_source_scoping_payload", service_pass)

    result = service_module.run_source_scoping(target, evidence, spans, provider)

    assert result.target_project == target
    assert calls == ["controller", "service"]


def test_blocker_validator_return_value_can_widen_schema_and_commit_success(
    tmp_path: Path,
) -> None:
    """Required negative probe: the hook must not widen the schema contract."""
    runner = ScriptedRunner([json.dumps({"answer": "schema-valid"})], [THREAD_ID])
    controller, store = _controller(tmp_path, runner)
    root = _workspace(tmp_path)
    created = controller.create_session(root)

    def widen_contract(_value: object) -> object:
        return {"answer": 7}

    result = controller.start_investigation(
        created.controller_session_id, root, _request(widen_contract)
    )
    retained = store.load(created.controller_session_id)

    assert result.structured_output == {"answer": 7}
    assert not isinstance(result.structured_output["answer"], str)
    assert result.receipt.succeeded is True
    assert result.receipt.structured_output_valid is True
    assert result.session.phase is SessionPhase.INVESTIGATING
    assert retained.last_successful_invocation_receipt == result.receipt
    assert retained.codex_session_id == THREAD_ID
