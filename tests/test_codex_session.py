from __future__ import annotations

import json
import multiprocessing
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import continuity_ai.codex_process as codex_process_module
from continuity_ai.codex_operation import ActiveCodexOperation, OperationStage, capture_process_identity
from continuity_ai.openai_provider import OpenAIReasoningProvider
from continuity_ai.codex_process import (
    CodexCliCapabilities,
    CodexCliProcessAdapter,
    CodexProcessBoundaryError,
    workspace_fingerprint,
)
from continuity_ai.codex_session import (
    CodexAvailability,
    CodexControllerSession,
    CodexOperation,
    CodexLimitReached,
    CodexNotInstalled,
    CodexNotAuthenticated,
    CodexOperationRequest,
    CodexSessionBusy,
    CodexSessionController,
    CodexSessionMismatch,
    CodexUnavailable,
    ConcurrentSessionModification,
    CorruptSessionState,
    FailureCategory,
    IncompatibleSessionState,
    InvalidCodexOutput,
    InvalidSessionState,
    JsonSessionStore,
    ResumeUnsupported,
    SessionPhase,
    SessionPersistenceError,
    WorkspaceChanged,
    WorkspaceMismatch,
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string", "minLength": 1}},
}
VALID_RESPONSE = json.dumps({"answer": "bounded"})
THREAD_ID = "12345678-1234-5678-9234-567812345678"


class TickClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


@dataclass
class FakeRunner:
    response: str = VALID_RESPONSE
    returncode: int = 0
    stderr: str = ""
    thread_id: str | None = THREAD_ID
    mutate_input: bool = False
    block: bool = False

    def __post_init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(options)))
        self.started.set()
        if self.block:
            assert self.release.wait(timeout=5)
        if self.mutate_input:
            source = Path(options["cwd"]) / "source.txt"
            source.write_text(source.read_text(encoding="utf-8") + " changed", encoding="utf-8")
        response_path = Path(command[command.index("--output-last-message") + 1])
        response_path.write_text(self.response, encoding="utf-8")
        stdout = (
            ""
            if self.thread_id is None
            else json.dumps({"type": "thread.started", "thread_id": self.thread_id}) + "\n"
        )
        return subprocess.CompletedProcess(
            command, self.returncode, stdout=stdout, stderr=self.stderr
        )


def _workspace(tmp_path: Path, name: str = "workspace", content: str = "alpha") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "source.txt").write_text(content, encoding="utf-8")
    return root.resolve()


def _adapter(runner: FakeRunner, *, resume: bool = True) -> CodexCliProcessAdapter:
    return CodexCliProcessAdapter(
        "codex",
        resolved_executable=Path(sys.executable),
        version="codex-cli test",
        capabilities=CodexCliCapabilities(
            True, resume, resume, resume, resume, resume_verified=resume
        ),
        process_runner=runner,
    )


def _controller(
    tmp_path: Path,
    runner: FakeRunner | None = None,
    *,
    resume: bool = True,
) -> tuple[CodexSessionController, JsonSessionStore, FakeRunner]:
    selected = runner or FakeRunner()
    store = JsonSessionStore(tmp_path / "sessions.json")
    return (
        CodexSessionController(store, _adapter(selected, resume=resume), clock=TickClock()),
        store,
        selected,
    )


def _request() -> CodexOperationRequest:
    return CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5)


def _investigated(
    tmp_path: Path,
    *,
    runner: FakeRunner | None = None,
    resume: bool = True,
) -> tuple[CodexSessionController, JsonSessionStore, FakeRunner, Path, CodexControllerSession]:
    controller, store, selected = _controller(tmp_path, runner, resume=resume)
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    result = controller.start_investigation(created.controller_session_id, root, _request())
    return controller, store, selected, root, result.session


def test_controller_session_has_unique_internal_id_and_no_fabricated_codex_id(
    tmp_path: Path,
) -> None:
    controller, _, _ = _controller(tmp_path)
    first = controller.create_session(_workspace(tmp_path, "one"))
    second = controller.create_session(_workspace(tmp_path, "two"))

    assert first.controller_session_id != second.controller_session_id
    assert uuid.UUID(first.controller_session_id)
    assert first.codex_session_id is None


def test_resume_requires_version_proof_in_addition_to_cli_flags() -> None:
    flags_only = CodexCliCapabilities(True, True, True, True, True)

    assert flags_only.resume_supported is False


def test_state_serialization_reload_is_deterministic(tmp_path: Path) -> None:
    controller, store, _ = _controller(tmp_path)
    created = controller.create_session(_workspace(tmp_path))
    reloaded = store.load(created.controller_session_id)
    store.save(reloaded)

    assert reloaded == created
    retained_session = store.load(created.controller_session_id)
    assert retained_session == replace(reloaded, revision=reloaded.revision + 1)
    retained = json.loads(store.path.read_bytes())
    assert "prompt" not in json.dumps(retained).casefold()
    assert "token" not in json.dumps(retained).casefold()


def test_corrupt_persisted_state_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(CorruptSessionState):
        JsonSessionStore(path).load(str(uuid.uuid4()))


def test_incompatible_state_schema_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    path.write_text(
        json.dumps({"schema_version": 999, "sessions": {}}), encoding="utf-8"
    )

    with pytest.raises(IncompatibleSessionState):
        JsonSessionStore(path).load(str(uuid.uuid4()))


def test_corruption_anywhere_and_duplicate_codex_ownership_fail_closed(
    tmp_path: Path,
) -> None:
    controller, store, _ = _controller(tmp_path)
    first = controller.create_session(_workspace(tmp_path, "one"))
    second = controller.create_session(_workspace(tmp_path, "two"))
    document = json.loads(store.path.read_text(encoding="utf-8"))
    document["sessions"][first.controller_session_id]["codex_session_id"] = THREAD_ID
    document["sessions"][second.controller_session_id]["codex_session_id"] = THREAD_ID
    store.path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CorruptSessionState):
        store.load(first.controller_session_id)


def test_workspace_path_mismatch_blocks_execution(tmp_path: Path) -> None:
    controller, _, runner = _controller(tmp_path)
    root = _workspace(tmp_path, "bound")
    other = _workspace(tmp_path, "other")
    session = controller.create_session(root)

    with pytest.raises(WorkspaceMismatch):
        controller.start_investigation(session.controller_session_id, other, _request())

    assert runner.calls == []


def test_workspace_content_change_blocks_continuation_before_execution(
    tmp_path: Path,
) -> None:
    controller, _, runner = _controller(tmp_path)
    root = _workspace(tmp_path)
    session = controller.create_session(root)
    (root / "source.txt").write_text("changed bytes", encoding="utf-8")

    with pytest.raises(WorkspaceChanged):
        controller.start_investigation(session.controller_session_id, root, _request())

    assert runner.calls == []


def test_same_filenames_with_changed_bytes_change_fingerprint(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    before = workspace_fingerprint(root)
    (root / "source.txt").write_bytes(b"bravo")

    assert workspace_fingerprint(root) != before


def test_second_simultaneous_operation_is_rejected(tmp_path: Path) -> None:
    runner = FakeRunner(block=True)
    controller, _, _ = _controller(tmp_path, runner)
    root = _workspace(tmp_path)
    session = controller.create_session(root)
    failures: list[BaseException] = []

    def invoke() -> None:
        try:
            controller.start_investigation(session.controller_session_id, root, _request())
        except BaseException as exc:  # captured for assertion in the test thread
            failures.append(exc)

    thread = threading.Thread(target=invoke)
    thread.start()
    assert runner.started.wait(timeout=5)
    with pytest.raises(CodexSessionBusy):
        controller.start_investigation(session.controller_session_id, root, _request())
    runner.release.set()
    thread.join(timeout=5)

    assert not failures
    assert len(runner.calls) == 1


def test_explicit_interrupted_state_preserves_prior_receipt(tmp_path: Path) -> None:
    controller, store, _, _, investigated = _investigated(tmp_path)
    prior = investigated.last_successful_invocation_receipt

    interrupted = controller.mark_interrupted(investigated.controller_session_id)
    reloaded = store.load(investigated.controller_session_id)

    assert interrupted.phase is SessionPhase.INVESTIGATING
    assert interrupted.availability is CodexAvailability.INTERRUPTED
    assert interrupted.last_successful_invocation_receipt == prior
    assert reloaded == interrupted


def test_unavailable_codex_preserves_prior_state_and_successful_receipt(
    tmp_path: Path,
) -> None:
    controller, store, runner, root, investigated = _investigated(tmp_path)
    prior = investigated.last_successful_invocation_receipt
    runner.returncode = 1
    runner.stderr = "service temporarily unavailable"

    with pytest.raises(CodexUnavailable):
        controller.resume_session(
            investigated.controller_session_id,
            THREAD_ID,
            root,
            _request(),
        )

    retained = store.load(investigated.controller_session_id)
    assert retained.phase is SessionPhase.INVESTIGATING
    assert retained.availability is CodexAvailability.UNAVAILABLE
    assert retained.last_successful_invocation_receipt == prior
    assert retained.last_invocation_receipt is not prior
    assert retained.workspace_fingerprint == investigated.workspace_fingerprint


def test_unavailable_codex_never_invokes_provider_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import continuity_ai.openai_provider as provider_module
    import continuity_ai.deterministic_offline_provider as offline_module

    calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> object:
        calls.append("fallback")
        raise AssertionError("provider fallback invoked")

    monkeypatch.setattr(provider_module, "OpenAIReasoningProvider", forbidden)
    monkeypatch.setattr(offline_module, "DeterministicOfflineReasoningProvider", forbidden)
    runner = FakeRunner(returncode=1, stderr="service unavailable", thread_id=None)
    controller, _, _ = _controller(tmp_path, runner)
    root = _workspace(tmp_path)
    session = controller.create_session(root)

    with pytest.raises(CodexUnavailable):
        controller.start_investigation(session.controller_session_id, root, _request())

    assert calls == []


def test_approved_workspace_cannot_equal_or_widen_original_boundary(
    tmp_path: Path,
) -> None:
    controller, _, _, root, investigated = _investigated(tmp_path)
    waiting = controller.record_awaiting_human_review(
        investigated.controller_session_id
    )

    with pytest.raises(WorkspaceMismatch):
        controller.bind_approved_workspace(
            waiting.controller_session_id, root, workspace_fingerprint(root)
        )
    with pytest.raises(WorkspaceMismatch):
        controller.bind_approved_workspace(
            waiting.controller_session_id,
            tmp_path,
            workspace_fingerprint(tmp_path),
        )


def test_human_review_never_transitions_automatically_to_approved(
    tmp_path: Path,
) -> None:
    controller, store, _, _, investigated = _investigated(tmp_path)
    waiting = controller.record_awaiting_human_review(
        investigated.controller_session_id
    )

    assert waiting.phase is SessionPhase.AWAITING_HUMAN_REVIEW
    assert waiting.approved_workspace_root is None
    assert store.load(waiting.controller_session_id).phase is SessionPhase.AWAITING_HUMAN_REVIEW


def test_explicit_approved_binding_is_separate_and_reporting_uses_it(
    tmp_path: Path,
) -> None:
    controller, _, runner, original, investigated = _investigated(tmp_path)
    waiting = controller.record_awaiting_human_review(
        investigated.controller_session_id
    )
    approved = _workspace(tmp_path, "approved", "selected only")
    bound = controller.bind_approved_workspace(
        waiting.controller_session_id,
        approved,
        workspace_fingerprint(approved),
    )
    reported = controller.start_reporting(
        bound.controller_session_id, approved, _request()
    )

    assert bound.workspace_root == str(original)
    assert bound.approved_workspace_root == str(approved)
    assert reported.session.phase is SessionPhase.REPORTING
    assert runner.calls[-1][1]["cwd"] == approved


def _bound_for_reporting(
    tmp_path: Path,
    *,
    runner: FakeRunner | None = None,
    resume: bool = True,
) -> tuple[CodexSessionController, JsonSessionStore, FakeRunner, Path, CodexControllerSession]:
    controller, store, selected, original, investigated = _investigated(
        tmp_path, runner=runner, resume=resume
    )
    waiting = controller.record_awaiting_human_review(
        investigated.controller_session_id
    )
    approved = _workspace(tmp_path, "approved", "selected only")
    bound = controller.bind_approved_workspace(
        waiting.controller_session_id,
        approved,
        workspace_fingerprint(approved),
    )
    return controller, store, selected, approved, bound


def test_reporting_resumes_the_genuine_investigation_session_id(
    tmp_path: Path,
) -> None:
    controller, store, runner, approved, bound = _bound_for_reporting(tmp_path)
    assert bound.codex_session_id == THREAD_ID
    calls_before = len(runner.calls)

    reported = controller.start_reporting(
        bound.controller_session_id, approved, _request()
    )

    report_command = runner.calls[-1][0]
    assert len(runner.calls) == calls_before + 1
    assert "resume" in report_command
    assert THREAD_ID in report_command
    assert reported.session.phase is SessionPhase.REPORTING
    assert reported.session.codex_session_id == THREAD_ID
    assert reported.receipt.resume_attempted is True
    assert reported.receipt.new_codex_session_created is False
    assert reported.receipt.codex_session_id == THREAD_ID
    retained = store.load(bound.controller_session_id)
    assert retained.codex_session_id == THREAD_ID


def test_reporting_returned_id_mismatch_fails_closed(tmp_path: Path) -> None:
    controller, store, runner, approved, bound = _bound_for_reporting(tmp_path)
    replacement_id = "87654321-4321-6789-9234-567812345678"
    runner.thread_id = replacement_id

    with pytest.raises(CodexSessionMismatch):
        controller.start_reporting(bound.controller_session_id, approved, _request())

    retained = store.load(bound.controller_session_id)
    assert retained.phase is SessionPhase.APPROVED
    assert retained.codex_session_id == THREAD_ID
    assert retained.last_invocation_receipt.failure_category is FailureCategory.SESSION_MISMATCH
    assert retained.last_invocation_receipt.resume_attempted is True


def test_reporting_without_retained_codex_session_id_fails_closed_no_process(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(thread_id=None)
    controller, store, _, approved, bound = _bound_for_reporting(tmp_path, runner=runner)
    assert bound.codex_session_id is None
    calls_before = len(runner.calls)

    with pytest.raises(CodexSessionMismatch):
        controller.start_reporting(bound.controller_session_id, approved, _request())

    assert len(runner.calls) == calls_before
    retained = store.load(bound.controller_session_id)
    assert retained.phase is SessionPhase.APPROVED
    assert retained.last_invocation_receipt.resume_attempted is True
    assert retained.last_invocation_receipt.process_started is False


def test_reporting_never_invokes_provider_fallback_on_session_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import continuity_ai.openai_provider as provider_module
    import continuity_ai.deterministic_offline_provider as offline_module

    calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> object:
        calls.append("fallback")
        raise AssertionError("provider fallback invoked")

    monkeypatch.setattr(provider_module, "OpenAIReasoningProvider", forbidden)
    monkeypatch.setattr(offline_module, "DeterministicOfflineReasoningProvider", forbidden)
    controller, _, runner, approved, bound = _bound_for_reporting(tmp_path)
    runner.thread_id = "87654321-4321-6789-9234-567812345678"

    with pytest.raises(CodexSessionMismatch):
        controller.start_reporting(bound.controller_session_id, approved, _request())

    assert calls == []


def test_reporting_requires_approved_phase(tmp_path: Path) -> None:
    controller, store, runner, _, investigated = _investigated(tmp_path)
    waiting = controller.record_awaiting_human_review(
        investigated.controller_session_id
    )
    calls_before = len(runner.calls)

    with pytest.raises(InvalidSessionState):
        controller.start_reporting(
            waiting.controller_session_id,
            Path(waiting.workspace_root),
            _request(),
        )

    assert len(runner.calls) == calls_before


def test_controller_session_id_mismatch_is_rejected(tmp_path: Path) -> None:
    controller, _, _ = _controller(tmp_path)
    controller.create_session(_workspace(tmp_path))

    with pytest.raises(CodexSessionMismatch):
        controller.get_session(str(uuid.uuid4()))


def test_genuine_codex_id_from_another_controller_session_is_rejected(
    tmp_path: Path,
) -> None:
    controller, _, runner = _controller(tmp_path)
    first_root = _workspace(tmp_path, "first")
    first = controller.create_session(first_root)
    first = controller.start_investigation(
        first.controller_session_id, first_root, _request()
    ).session
    second_id = "87654321-4321-6789-9234-567812345678"
    runner.thread_id = second_id
    second_root = _workspace(tmp_path, "second")
    second = controller.create_session(second_root)
    controller.start_investigation(second.controller_session_id, second_root, _request())
    calls_before = len(runner.calls)

    with pytest.raises(CodexSessionMismatch):
        controller.resume_session(
            first.controller_session_id,
            second_id,
            first_root,
            _request(),
        )

    assert len(runner.calls) == calls_before


def test_non_uuid_event_identity_is_never_persisted_or_fabricated(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(thread_id="test-not-a-genuine-id")
    controller, _, _ = _controller(tmp_path, runner)
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    result = controller.start_investigation(
        created.controller_session_id, root, _request()
    )

    assert result.session.codex_session_id is None
    assert result.receipt.codex_session_id is None
    assert result.receipt.new_codex_session_created is False


def test_unsupported_resume_is_explicitly_rejected_without_process(
    tmp_path: Path,
) -> None:
    controller, store, runner, root, investigated = _investigated(
        tmp_path, resume=False
    )
    calls_before = len(runner.calls)

    with pytest.raises(ResumeUnsupported):
        controller.resume_session(
            investigated.controller_session_id,
            THREAD_ID,
            root,
            _request(),
        )

    retained = store.load(investigated.controller_session_id)
    assert retained.resume_supported is False
    assert retained.sanitized_error_code == "resume_unsupported"
    assert len(runner.calls) == calls_before


def test_malformed_output_cannot_produce_successful_receipt(tmp_path: Path) -> None:
    runner = FakeRunner(response="not-json", thread_id=None)
    controller, store, _ = _controller(tmp_path, runner)
    root = _workspace(tmp_path)
    created = controller.create_session(root)

    with pytest.raises(InvalidCodexOutput) as captured:
        controller.start_investigation(created.controller_session_id, root, _request())

    receipt = captured.value.receipt
    assert receipt is not None
    assert receipt.succeeded is False
    retained = store.load(created.controller_session_id)
    assert retained.phase is SessionPhase.READY
    assert retained.last_successful_invocation_receipt is None
    assert retained.last_invocation_receipt == receipt


def test_semantic_validator_rejection_fails_closed_before_success_commit(
    tmp_path: Path,
) -> None:
    controller, store, _ = _controller(tmp_path)
    root = _workspace(tmp_path)
    created = controller.create_session(root)

    def reject(_value: object) -> object:
        raise ValueError("semantically wrong")

    with pytest.raises(InvalidCodexOutput) as captured:
        controller.start_investigation(
            created.controller_session_id,
            root,
            CodexOperationRequest("q", SCHEMA, 5, structured_output_validator=reject),
        )

    receipt = captured.value.receipt
    assert receipt is not None
    assert receipt.succeeded is False
    assert receipt.failure_category is FailureCategory.INVALID_OUTPUT
    retained = store.load(created.controller_session_id)
    assert retained.phase is SessionPhase.READY
    assert retained.codex_session_id is None
    assert retained.codex_process_active is False
    assert retained.active_operation is None
    assert retained.last_successful_invocation_receipt is None
    assert retained.last_invocation_receipt == receipt

    # Retry on the same controller session is now allowed: phase never left READY.
    retried = controller.start_investigation(
        created.controller_session_id, root, _request()
    )
    assert retried.session.phase is SessionPhase.INVESTIGATING
    assert retried.session.codex_session_id == THREAD_ID


def test_semantic_validator_is_not_invoked_after_json_schema_rejection(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(response="not-json", thread_id=None)
    controller, _, _ = _controller(tmp_path, runner)
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    calls: list[object] = []

    def forbidden(value: object) -> object:
        calls.append(value)
        raise AssertionError("validator invoked after JSON Schema rejection")

    with pytest.raises(InvalidCodexOutput):
        controller.start_investigation(
            created.controller_session_id,
            root,
            CodexOperationRequest("q", SCHEMA, 5, structured_output_validator=forbidden),
        )

    assert calls == []


def test_semantic_validator_exception_is_sanitized_and_not_chained(
    tmp_path: Path,
) -> None:
    controller, _, _ = _controller(tmp_path)
    root = _workspace(tmp_path)
    created = controller.create_session(root)

    def leaky(_value: object) -> object:
        raise ValueError("evidence secret: top-secret-content")

    with pytest.raises(InvalidCodexOutput) as captured:
        controller.start_investigation(
            created.controller_session_id,
            root,
            CodexOperationRequest("q", SCHEMA, 5, structured_output_validator=leaky),
        )

    exc = captured.value
    assert "top-secret-content" not in str(exc)
    assert exc.__cause__ is None


def test_semantic_validator_accepting_payload_still_commits_investigating_with_retained_id(
    tmp_path: Path,
) -> None:
    controller, _, _ = _controller(tmp_path)
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    calls: list[object] = []

    def accept(value: object) -> None:
        calls.append(value)
        return None

    result = controller.start_investigation(
        created.controller_session_id,
        root,
        CodexOperationRequest("q", SCHEMA, 5, structured_output_validator=accept),
    )

    assert calls == [json.loads(VALID_RESPONSE)]
    assert result.session.phase is SessionPhase.INVESTIGATING
    assert result.session.codex_session_id == THREAD_ID
    assert result.receipt.succeeded is True
    assert result.structured_output == json.loads(VALID_RESPONSE)


def test_reporting_semantic_rejection_preserves_prior_successful_receipt_and_allows_retry(
    tmp_path: Path,
) -> None:
    controller, store, _, approved, bound = _bound_for_reporting(tmp_path)
    prior_successful = bound.last_successful_invocation_receipt
    assert prior_successful is not None

    def reject(_value: object) -> object:
        raise ValueError("bad report semantics")

    with pytest.raises(InvalidCodexOutput):
        controller.start_reporting(
            bound.controller_session_id,
            approved,
            CodexOperationRequest("q", SCHEMA, 5, structured_output_validator=reject),
        )

    retained = store.load(bound.controller_session_id)
    assert retained.phase is SessionPhase.APPROVED
    assert retained.last_successful_invocation_receipt == prior_successful
    assert retained.last_invocation_receipt != prior_successful
    assert retained.last_invocation_receipt.failure_category is FailureCategory.INVALID_OUTPUT

    # Retry at the same phase succeeds with a passing validator.
    retried = controller.start_reporting(
        bound.controller_session_id, approved, _request()
    )
    assert retried.session.phase is SessionPhase.REPORTING


def test_input_mutation_cannot_produce_successful_receipt(tmp_path: Path) -> None:
    runner = FakeRunner(mutate_input=True, thread_id=None)
    controller, store, _ = _controller(tmp_path, runner)
    root = _workspace(tmp_path)
    created = controller.create_session(root)

    with pytest.raises(WorkspaceChanged) as captured:
        controller.start_investigation(created.controller_session_id, root, _request())

    receipt = captured.value.receipt
    assert receipt is not None
    assert receipt.input_unchanged is False
    assert receipt.succeeded is False
    assert store.load(created.controller_session_id).last_successful_invocation_receipt is None


class FailingSaveStore:
    def __init__(self, delegate: JsonSessionStore) -> None:
        self.delegate = delegate
        self.fail = False

    def create(self, session: CodexControllerSession) -> None:
        self.delegate.create(session)

    def load(self, controller_session_id: str) -> CodexControllerSession:
        return self.delegate.load(controller_session_id)

    def save(self, session: CodexControllerSession) -> None:
        if self.fail:
            raise SessionPersistenceError("injected persistence failure")
        self.delegate.save(session)

    def recover(
        self,
        session: CodexControllerSession,
        expected_operation_id: str,
    ) -> None:
        if self.fail:
            raise SessionPersistenceError("injected persistence failure")
        self.delegate.recover(session, expected_operation_id)


def test_persistence_failure_cannot_publish_later_lifecycle_phase(
    tmp_path: Path,
) -> None:
    delegate = JsonSessionStore(tmp_path / "sessions.json")
    store = FailingSaveStore(delegate)
    runner = FakeRunner()
    controller = CodexSessionController(store, _adapter(runner), clock=TickClock())
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    investigated = controller.start_investigation(
        created.controller_session_id, root, _request()
    ).session
    store.fail = True

    with pytest.raises(SessionPersistenceError):
        controller.record_awaiting_human_review(investigated.controller_session_id)

    assert delegate.load(investigated.controller_session_id).phase is SessionPhase.INVESTIGATING


def test_controller_process_command_preserves_boundary_and_is_not_ephemeral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-enter-primary-path")
    controller, _, runner = _controller(tmp_path)
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    controller.start_investigation(created.controller_session_id, root, _request())
    command, options = runner.calls[0]

    assert options["cwd"] == root
    assert command[command.index("--cd") + 1] == str(root)
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--output-schema" in command
    assert "--ephemeral" not in command
    assert "OPENAI_API_KEY" not in options["env"]


@pytest.mark.parametrize(
    ("stderr", "error_type", "availability"),
    [
        (
            "Please run codex login; authentication required",
            CodexNotAuthenticated,
            "not_authenticated",
        ),
        ("usage limit reached", CodexLimitReached, "limit_reached"),
    ],
)
def test_supported_process_evidence_maps_to_narrow_failure_state(
    tmp_path: Path,
    stderr: str,
    error_type: type[Exception],
    availability: str,
) -> None:
    runner = FakeRunner(returncode=1, stderr=stderr, thread_id=None)
    controller, store, _ = _controller(tmp_path, runner)
    root = _workspace(tmp_path)
    created = controller.create_session(root)

    with pytest.raises(error_type):
        controller.start_investigation(created.controller_session_id, root, _request())

    assert store.load(created.controller_session_id).availability.value == availability


def test_invalid_transition_cannot_approve_without_explicit_binding(
    tmp_path: Path,
) -> None:
    controller, _, _ = _controller(tmp_path)
    created = controller.create_session(_workspace(tmp_path))

    with pytest.raises(InvalidSessionState):
        controller.enter_conversational_phase(created.controller_session_id)


class BeforeInvokeAdapter(CodexCliProcessAdapter):
    def __init__(self, base: CodexCliProcessAdapter, before: Any) -> None:
        super().__init__(
            base.executable,
            resolved_executable=base.resolved_executable,
            version=base.version,
            capabilities=base.capabilities,
            executable_identity=base.executable_identity,
            process_runner=base._runner,
        )
        self.before = before

    def invoke(self, request: Any) -> Any:
        self.before(Path(request.workspace_root))
        return super().invoke(request)


def _controller_with_prelaunch_action(
    tmp_path: Path,
    before: Any,
    runner: FakeRunner | None = None,
) -> tuple[CodexSessionController, JsonSessionStore, FakeRunner]:
    selected = runner or FakeRunner()
    base = _adapter(selected)
    store = JsonSessionStore(tmp_path / "sessions.json")
    return (
        CodexSessionController(
            store,
            BeforeInvokeAdapter(base, before),
            clock=TickClock(),
        ),
        store,
        selected,
    )


def _full_exception_graph(error: BaseException) -> list[BaseException]:
    seen_ids: set[int] = set()
    graph: list[BaseException] = []
    frontier: list[BaseException | None] = [error]
    while frontier:
        current = frontier.pop()
        if current is None or id(current) in seen_ids:
            continue
        seen_ids.add(id(current))
        graph.append(current)
        frontier.append(current.__cause__)
        frontier.append(current.__context__)
    return graph


def _assert_sanitized_prelaunch_failure(
    error: BaseException, root: Path, *forbidden_values: object
) -> None:
    for current in _full_exception_graph(error):
        assert not isinstance(
            current, (OSError, FileNotFoundError, PermissionError)
        )
        exposed = (
            str(current),
            repr(current),
            repr(current.args),
            str(getattr(current, "filename", "")),
        )
        for forbidden in (root, *forbidden_values):
            value = str(forbidden)
            assert value
            assert all(value not in candidate for candidate in exposed)


def test_missing_workspace_resolution_os_error_is_fully_severed(
    tmp_path: Path,
) -> None:
    controller, _, runner = _controller(tmp_path)
    missing = tmp_path / "secret-missing-workspace"

    with pytest.raises(WorkspaceMismatch) as captured:
        controller.create_session(missing)

    assert str(captured.value) == "Workspace root could not be resolved."
    _assert_sanitized_prelaunch_failure(
        captured.value, missing, tmp_path, "secret-missing-workspace"
    )
    assert runner.calls == []


def test_workspace_snapshot_os_error_is_fully_severed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path, content="audit-secret-source-content")
    source_path = root / "source.txt"
    original_read_bytes = Path.read_bytes

    def deny_source_read(path: Path) -> bytes:
        if path == source_path:
            raise PermissionError(
                13, "credential=audit-secret-snapshot", str(source_path)
            )
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", deny_source_read)
    with pytest.raises(CodexProcessBoundaryError) as captured:
        workspace_fingerprint(root)

    assert str(captured.value) == "Workspace snapshot could not be captured."
    _assert_sanitized_prelaunch_failure(
        captured.value,
        root,
        tmp_path,
        source_path,
        "credential=audit-secret-snapshot",
        "audit-secret-source-content",
    )


def test_missing_codex_discovery_file_error_is_fully_severed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_executable = tmp_path / "secret-codex.exe"

    def fail_discovery(cls: type[CodexCliProcessAdapter], executable: str):
        raise FileNotFoundError(2, "credential=audit-secret-codex", secret_executable)

    monkeypatch.setattr(
        CodexCliProcessAdapter, "discover", classmethod(fail_discovery)
    )
    with pytest.raises(CodexNotInstalled) as captured:
        CodexSessionController.with_local_codex(
            JsonSessionStore(tmp_path / "sessions.json")
        )

    assert str(captured.value) == "Codex executable is not installed."
    _assert_sanitized_prelaunch_failure(
        captured.value,
        secret_executable,
        tmp_path,
        "credential=audit-secret-codex",
    )


def test_deleted_workspace_prelaunch_failure_is_typed_persisted_and_released(
    tmp_path: Path,
) -> None:
    def remove(root: Path) -> None:
        shutil.rmtree(root)

    controller, store, runner = _controller_with_prelaunch_action(tmp_path, remove)
    root = _workspace(tmp_path)
    session = controller.create_session(root)

    with pytest.raises(WorkspaceChanged) as captured:
        controller.start_investigation(session.controller_session_id, root, _request())

    _assert_sanitized_prelaunch_failure(captured.value, root, tmp_path, "alpha")
    retained = store.load(session.controller_session_id)
    assert retained.codex_process_active is False
    assert retained.active_operation is None
    assert retained.last_invocation_receipt == captured.value.receipt
    assert retained.last_invocation_receipt is not None
    assert retained.last_invocation_receipt.process_started is False
    assert runner.calls == []


def test_permission_error_prelaunch_is_typed_sanitized_and_has_no_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    original_lstat = Path.lstat
    provider_calls = 0

    def forbidden_provider(self: Any, client: Any = None) -> None:
        nonlocal provider_calls
        provider_calls += 1

    def deny(bound_root: Path) -> None:
        def lstat(path: Path) -> Any:
            if path == bound_root:
                raise PermissionError("C:/secret/customer/source.txt")
            return original_lstat(path)

        monkeypatch.setattr(Path, "lstat", lstat)

    monkeypatch.setattr(OpenAIReasoningProvider, "__init__", forbidden_provider)
    controller, store, runner = _controller_with_prelaunch_action(tmp_path, deny)
    session = controller.create_session(root)

    with pytest.raises(WorkspaceChanged) as captured:
        controller.start_investigation(session.controller_session_id, root, _request())

    _assert_sanitized_prelaunch_failure(
        captured.value,
        root,
        tmp_path,
        "C:/secret/customer/source.txt",
        "secret",
        "alpha",
    )
    assert "secret" not in str(captured.value)
    assert provider_calls == 0
    assert runner.calls == []
    assert store.load(session.controller_session_id).codex_process_active is False


def test_environment_preparation_os_error_is_fully_severed_and_released(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_path = tmp_path / "secret-environment"
    provider_calls = 0

    def forbidden_provider(self: Any, client: Any = None) -> None:
        nonlocal provider_calls
        provider_calls += 1

    def fail_environment(*args: Any, **kwargs: Any) -> dict[str, str]:
        raise PermissionError(
            13, "credential=audit-secret-environment", str(secret_path)
        )

    monkeypatch.setattr(OpenAIReasoningProvider, "__init__", forbidden_provider)
    monkeypatch.setattr(
        codex_process_module, "codex_environment", fail_environment
    )
    controller, store, runner = _controller(tmp_path)
    root = _workspace(tmp_path)
    session = controller.create_session(root)
    store_document = store.path.read_text(encoding="utf-8")

    with pytest.raises(CodexUnavailable) as captured:
        controller.start_investigation(session.controller_session_id, root, _request())

    assert str(captured.value) == "Codex process boundary is unavailable."
    _assert_sanitized_prelaunch_failure(
        captured.value,
        root,
        tmp_path,
        secret_path,
        "credential=audit-secret-environment",
        "alpha",
        store_document,
    )
    retained = store.load(session.controller_session_id)
    assert captured.value.receipt is not None
    assert retained.last_invocation_receipt == captured.value.receipt
    assert retained.last_successful_invocation_receipt is None
    assert retained.active_operation is None
    assert retained.codex_process_active is False
    assert runner.calls == []
    assert provider_calls == 0


def test_executable_revalidation_os_error_is_fully_severed_and_released(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_calls = 0
    secret_executable = tmp_path / "secret-revalidated-codex.exe"

    def forbidden_provider(self: Any, client: Any = None) -> None:
        nonlocal provider_calls
        provider_calls += 1

    controller, store, runner = _controller(tmp_path)
    root = _workspace(tmp_path, content="audit-secret-source-content")
    session = controller.create_session(root)
    store_document = store.path.read_text(encoding="utf-8")

    def fail_identity(path: Path) -> object:
        raise PermissionError(
            13, "credential=audit-secret-executable", str(secret_executable)
        )

    monkeypatch.setattr(OpenAIReasoningProvider, "__init__", forbidden_provider)
    monkeypatch.setattr(codex_process_module, "_executable_identity", fail_identity)

    with pytest.raises(CodexUnavailable) as captured:
        controller.start_investigation(session.controller_session_id, root, _request())

    assert str(captured.value) == "Codex process boundary is unavailable."
    _assert_sanitized_prelaunch_failure(
        captured.value,
        root,
        tmp_path,
        secret_executable,
        "credential=audit-secret-executable",
        "audit-secret-source-content",
        store_document,
    )
    retained = store.load(session.controller_session_id)
    assert captured.value.receipt is not None
    assert retained.last_invocation_receipt == captured.value.receipt
    assert retained.last_successful_invocation_receipt is None
    assert retained.active_operation is None
    assert retained.codex_process_active is False
    assert runner.calls == []
    assert provider_calls == 0


def test_workspace_directory_to_file_change_is_rejected_before_launch(
    tmp_path: Path,
) -> None:
    def replace_with_file(root: Path) -> None:
        shutil.rmtree(root)
        root.write_text("substitution", encoding="utf-8")

    controller, store, runner = _controller_with_prelaunch_action(
        tmp_path, replace_with_file
    )
    root = _workspace(tmp_path)
    session = controller.create_session(root)

    with pytest.raises(WorkspaceChanged) as captured:
        controller.start_investigation(session.controller_session_id, root, _request())

    _assert_sanitized_prelaunch_failure(
        captured.value, root, tmp_path, "substitution", "alpha"
    )
    assert runner.calls == []
    retained = store.load(session.controller_session_id)
    assert retained.active_operation is None
    assert retained.codex_process_active is False


def test_workspace_reparse_substitution_is_rejected_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def substitute(_: Path) -> None:
        monkeypatch.setattr(codex_process_module, "_is_link_or_reparse", lambda value: True)

    controller, store, runner = _controller_with_prelaunch_action(tmp_path, substitute)
    root = _workspace(tmp_path)
    session = controller.create_session(root)

    with pytest.raises(WorkspaceChanged) as captured:
        controller.start_investigation(session.controller_session_id, root, _request())

    _assert_sanitized_prelaunch_failure(captured.value, root, tmp_path, "alpha")
    assert runner.calls == []
    retained = store.load(session.controller_session_id)
    assert retained.active_operation is None
    assert retained.codex_process_active is False


def test_prelaunch_failure_preserves_prior_successful_receipt(tmp_path: Path) -> None:
    runner = FakeRunner()

    def fail_only_after_success(root: Path) -> None:
        if runner.calls:
            shutil.rmtree(root)

    controller, store, _ = _controller_with_prelaunch_action(
        tmp_path, fail_only_after_success, runner
    )
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    successful = controller.start_investigation(
        created.controller_session_id, root, _request()
    )

    with pytest.raises(WorkspaceChanged) as captured:
        controller.resume_session(
            created.controller_session_id,
            THREAD_ID,
            root,
            _request(),
        )

    _assert_sanitized_prelaunch_failure(captured.value, root, tmp_path, "alpha")
    retained = store.load(created.controller_session_id)
    assert retained.last_successful_invocation_receipt == successful.receipt
    assert retained.last_invocation_receipt == captured.value.receipt
    assert len(runner.calls) == 1


def test_stale_session_revision_is_rejected_without_durable_change(
    tmp_path: Path,
) -> None:
    controller, store, _ = _controller(tmp_path)
    created = controller.create_session(_workspace(tmp_path))
    first = store.load(created.controller_session_id)
    stale = store.load(created.controller_session_id)
    store.save(replace(first, sanitized_error_code="first-writer"))
    durable = store.load(created.controller_session_id)

    with pytest.raises(ConcurrentSessionModification) as captured:
        store.save(replace(stale, sanitized_error_code="stale-writer"))

    assert str(captured.value) == "Controller session was modified concurrently."
    assert captured.value.__cause__ is None
    assert store.load(created.controller_session_id) == durable
    assert durable.sanitized_error_code == "first-writer"


def test_unrelated_session_survives_session_local_cas(tmp_path: Path) -> None:
    controller, store, _ = _controller(tmp_path)
    first = controller.create_session(_workspace(tmp_path, "one"))
    second = controller.create_session(_workspace(tmp_path, "two"))
    first_snapshot = store.load(first.controller_session_id)
    second_snapshot = store.load(second.controller_session_id)
    store.save(replace(second_snapshot, sanitized_error_code="second"))
    store.save(replace(first_snapshot, sanitized_error_code="first"))

    assert store.load(first.controller_session_id).sanitized_error_code == "first"
    assert store.load(second.controller_session_id).sanitized_error_code == "second"


def test_session_store_read_os_error_is_fully_severed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, store, _ = _controller(tmp_path)
    created = controller.create_session(_workspace(tmp_path))
    store_document = store.path.read_text(encoding="utf-8")
    original_read_text = Path.read_text

    def deny_store_read(path: Path, *args: Any, **kwargs: Any) -> str:
        if path == store.path:
            raise PermissionError(
                13, "credential=audit-secret-store-read", str(store.path)
            )
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_store_read)
    with pytest.raises(CorruptSessionState) as captured:
        store.load(created.controller_session_id)

    assert str(captured.value) == "Session state is corrupt."
    _assert_sanitized_prelaunch_failure(
        captured.value,
        store.path,
        tmp_path,
        "credential=audit-secret-store-read",
        store_document,
        "alpha",
    )


def test_atomic_replace_failure_does_not_advance_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, store, _ = _controller(tmp_path)
    created = controller.create_session(_workspace(tmp_path))
    snapshot = store.load(created.controller_session_id)
    store_document = store.path.read_text(encoding="utf-8")
    original_replace = Path.replace

    def fail_replace(path: Path, target: Path) -> Path:
        if Path(target) == store.path:
            raise OSError("C:/secret/store.json")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(SessionPersistenceError) as captured:
        store.save(replace(snapshot, sanitized_error_code="not-durable"))

    assert str(captured.value) == "Session state could not be persisted atomically."
    _assert_sanitized_prelaunch_failure(
        captured.value,
        store.path,
        tmp_path,
        "C:/secret/store.json",
        "secret",
        store_document,
    )
    assert store.load(created.controller_session_id) == snapshot


def test_lock_acquisition_failure_is_fail_closed(tmp_path: Path) -> None:
    controller, store, _ = _controller(tmp_path)
    created = controller.create_session(_workspace(tmp_path))
    snapshot = store.load(created.controller_session_id)
    lock_path = store.path.parent / f".{store.path.name}.lock"
    lock_path.unlink()
    lock_path.mkdir()

    with pytest.raises(SessionPersistenceError) as captured:
        store.save(replace(snapshot, sanitized_error_code="not-durable"))

    assert str(captured.value) == "Session store lock is unavailable."
    _assert_sanitized_prelaunch_failure(
        captured.value, lock_path, tmp_path, "not-durable"
    )
    assert store.load(created.controller_session_id) == snapshot


def test_lock_os_error_is_fully_severed_without_durable_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, store, _ = _controller(tmp_path)
    created = controller.create_session(_workspace(tmp_path))
    snapshot = store.load(created.controller_session_id)
    store_document = store.path.read_text(encoding="utf-8")
    lock_path = store.path.parent / f".{store.path.name}.lock"
    original_open = Path.open
    denied = False

    def deny_lock_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        nonlocal denied
        if Path(path) == lock_path and not denied:
            denied = True
            raise PermissionError(
                13, "credential=audit-secret-lock", str(lock_path)
            )
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_lock_open)
    with pytest.raises(SessionPersistenceError) as captured:
        store.save(replace(snapshot, sanitized_error_code="not-durable"))

    assert denied is True
    assert str(captured.value) == "Session store lock is unavailable."
    _assert_sanitized_prelaunch_failure(
        captured.value,
        lock_path,
        tmp_path,
        "credential=audit-secret-lock",
        store_document,
        "not-durable",
    )
    assert store.load(created.controller_session_id) == snapshot


def test_missing_revision_and_v02_state_are_explicitly_rejected(tmp_path: Path) -> None:
    controller, store, _ = _controller(tmp_path)
    created = controller.create_session(_workspace(tmp_path))
    document = json.loads(store.path.read_text(encoding="utf-8"))
    del document["sessions"][created.controller_session_id]["revision"]
    store.path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CorruptSessionState):
        store.load(created.controller_session_id)

    document["schema_version"] = 2
    store.path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(IncompatibleSessionState):
        store.load(created.controller_session_id)


def test_recovery_and_normal_save_share_one_revision_cas(tmp_path: Path) -> None:
    controller, store, _ = _controller(tmp_path)
    created = controller.create_session(_workspace(tmp_path))
    operation_id = str(uuid.uuid4())
    active = ActiveCodexOperation(
        operation_id=operation_id,
        controller_session_id=created.controller_session_id,
        operation_type=CodexOperation.INVESTIGATION.value,
        stage=OperationStage.RESERVED,
        owner_process=capture_process_identity(),
        codex_process=None,
        reserved_at=datetime.now(timezone.utc),
    )
    store.save(replace(created, codex_process_active=True, active_operation=active))
    snapshot = store.load(created.controller_session_id)
    candidates = (
        (JsonSessionStore(store.path).save, replace(snapshot, sanitized_error_code="save")),
        (
            lambda value: JsonSessionStore(store.path).recover(value, operation_id),
            replace(snapshot, codex_process_active=False, active_operation=None),
        ),
    )
    barrier = threading.Barrier(2)
    outcomes: list[BaseException | None] = []

    def write(call: Any, value: CodexControllerSession) -> None:
        barrier.wait(timeout=5)
        try:
            call(value)
            outcomes.append(None)
        except BaseException as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=write, args=item) for item in candidates]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert outcomes.count(None) == 1
    conflicts = [item for item in outcomes if item is not None]
    assert len(conflicts) == 1
    assert isinstance(conflicts[0], ConcurrentSessionModification)


class ProcessBarrierStore:
    def __init__(self, path: Path, barrier: Any) -> None:
        self.delegate = JsonSessionStore(path)
        self.barrier = barrier

    def create(self, session: CodexControllerSession) -> None:
        self.delegate.create(session)

    def load(self, controller_session_id: str) -> CodexControllerSession:
        session = self.delegate.load(controller_session_id)
        self.barrier.wait(timeout=10)
        return session

    def save(self, session: CodexControllerSession) -> None:
        self.delegate.save(session)

    def recover(
        self,
        session: CodexControllerSession,
        expected_operation_id: str,
    ) -> None:
        self.delegate.recover(session, expected_operation_id)


def _race_begin_worker(
    store_path: str,
    workspace_root: str,
    controller_session_id: str,
    barrier: Any,
    results: Any,
) -> None:
    try:
        controller = CodexSessionController(
            ProcessBarrierStore(Path(store_path), barrier),
            _adapter(FakeRunner()),
            clock=TickClock(),
        )
        controller.start_investigation(
            controller_session_id,
            Path(workspace_root),
            _request(),
        )
        results.put("success")
    except BaseException as exc:
        results.put(type(exc).__name__)


def test_two_spawned_processes_cannot_both_begin_same_operation(
    tmp_path: Path,
) -> None:
    controller, store, _ = _controller(tmp_path)
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_race_begin_worker,
            args=(
                str(store.path),
                str(root),
                created.controller_session_id,
                barrier,
                results,
            ),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)

    assert all(process.exitcode == 0 for process in processes)
    assert sorted(results.get(timeout=5) for _ in range(2)) == [
        "ConcurrentSessionModification",
        "success",
    ]
    retained = store.load(created.controller_session_id)
    assert retained.phase is SessionPhase.INVESTIGATING
    assert retained.last_successful_invocation_receipt is not None
