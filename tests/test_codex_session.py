from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from continuity_ai.codex_process import (
    CodexCliCapabilities,
    CodexCliProcessAdapter,
    workspace_fingerprint,
)
from continuity_ai.codex_session import (
    CodexAvailability,
    CodexControllerSession,
    CodexLimitReached,
    CodexNotAuthenticated,
    CodexOperationRequest,
    CodexSessionBusy,
    CodexSessionController,
    CodexSessionMismatch,
    CodexUnavailable,
    CorruptSessionState,
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
    before = store.path.read_bytes()
    reloaded = store.load(created.controller_session_id)
    store.save(reloaded)

    assert reloaded == created
    assert store.path.read_bytes() == before
    retained = json.loads(before)
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
