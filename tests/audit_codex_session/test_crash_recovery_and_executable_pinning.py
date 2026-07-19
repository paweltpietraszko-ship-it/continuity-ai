"""Adversarial repair regressions for the local Codex session controller v0.2."""

from __future__ import annotations

import json
import os
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

import continuity_ai.codex_session as codex_session_module
from continuity_ai.codex_operation import (
    ActiveCodexOperation,
    OperationLiveness,
    OperationStage,
    OsProcessLivenessVerifier,
    ProcessIdentity,
    capture_process_identity,
)
from continuity_ai.codex_process import (
    CodexCliCapabilities,
    CodexCliProcessAdapter,
    CodexInvocationRequest,
    CodexProcessBoundaryError,
)
from continuity_ai.codex_session import (
    AbandonedOperationRecoveryError,
    ActiveOperationAlive,
    ActiveOperationLivenessUnknown,
    ActiveOperationMismatch,
    CodexAvailability,
    CodexOperation,
    CodexOperationRequest,
    CodexSessionBusy,
    CodexSessionController,
    CodexSessionError,
    JsonSessionStore,
    SessionPersistenceError,
    SessionPhase,
    WorkspaceBoundaryViolation,
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string", "minLength": 1}},
}


class TickClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


@dataclass
class FakeRunner:
    response: str = json.dumps({"answer": "bounded"})
    returncode: int = 0

    def __post_init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(command))
        response_path = Path(command[command.index("--output-last-message") + 1])
        response_path.write_text(self.response, encoding="utf-8")
        return subprocess.CompletedProcess(command, self.returncode, stdout="", stderr="")


@dataclass
class FakeLivenessVerifier:
    result: OperationLiveness

    def __post_init__(self) -> None:
        self.calls: list[ProcessIdentity] = []

    def check(self, identity: ProcessIdentity) -> OperationLiveness:
        self.calls.append(identity)
        return self.result


def test_production_os_verifier_distinguishes_live_and_dead_processes() -> None:
    verifier = OsProcessLivenessVerifier()
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"],
        stdin=subprocess.PIPE,
    )
    try:
        identity = capture_process_identity(process.pid)
        assert verifier.check(identity) is OperationLiveness.ALIVE
    finally:
        process.terminate()
        process.wait(timeout=5)
    assert verifier.check(identity) is OperationLiveness.DEAD


def _adapter(runner: FakeRunner, *, executable: str = "codex") -> CodexCliProcessAdapter:
    return CodexCliProcessAdapter(
        executable,
        resolved_executable=Path(sys.executable),
        version="codex-cli test",
        capabilities=CodexCliCapabilities(True, False, False, False, False),
        process_runner=runner,
    )


def _workspace(tmp_path: Path, name: str = "workspace") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "source.txt").write_text("alpha", encoding="utf-8")
    return root.resolve()


def _retain_active_operation(
    store: JsonSessionStore,
    controller_session_id: str,
    *,
    stage: OperationStage = OperationStage.RESERVED,
) -> str:
    session = store.load(controller_session_id)
    operation_id = str(uuid.uuid4())
    process = (
        ProcessIdentity(90210, "test-child:1")
        if stage in {OperationStage.RUNNING, OperationStage.COMPLETED}
        else None
    )
    operation = ActiveCodexOperation(
        operation_id=operation_id,
        controller_session_id=controller_session_id,
        operation_type=CodexOperation.INVESTIGATION.value,
        stage=stage,
        owner_process=ProcessIdentity(90100, "test-owner:1"),
        codex_process=process,
        reserved_at=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
    )
    store.save(
        replace(
            session,
            codex_process_active=True,
            active_operation=operation,
        )
    )
    return operation_id


def test_stale_active_marker_recovers_only_through_explicit_dead_operation(
    tmp_path: Path,
) -> None:
    """A dead retained operation has one explicit recovery path and can be reused."""
    store = JsonSessionStore(tmp_path / "sessions.json")
    runner = FakeRunner()
    verifier = FakeLivenessVerifier(OperationLiveness.DEAD)
    controller = CodexSessionController(
        store,
        _adapter(runner),
        clock=TickClock(),
        liveness_verifier=verifier,
    )
    root = _workspace(tmp_path)
    session = controller.create_session(root)

    operation_id = _retain_active_operation(store, session.controller_session_id)
    reloaded = store.load(session.controller_session_id)
    assert reloaded.codex_process_active is True

    with pytest.raises(CodexSessionBusy):
        controller.mark_interrupted(session.controller_session_id)

    with pytest.raises(CodexSessionBusy):
        controller.mark_unavailable(session.controller_session_id)

    with pytest.raises(CodexSessionBusy):
        controller.start_investigation(
            session.controller_session_id,
            root,
            CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
        )

    with pytest.raises(CodexSessionBusy):
        controller.record_awaiting_human_review(session.controller_session_id)

    recovered = controller.recover_abandoned_operation(
        session.controller_session_id,
        operation_id,
    )
    assert recovered.codex_process_active is False
    assert recovered.active_operation is None
    assert recovered.phase is SessionPhase.READY
    assert recovered.availability is CodexAvailability.INTERRUPTED
    assert recovered.last_successful_invocation_receipt is None
    assert recovered.last_invocation_receipt is None
    assert recovered.recovery_events[-1].operation_id == operation_id
    assert recovered.recovery_events[-1].observed_liveness is OperationLiveness.DEAD
    assert verifier.calls

    later = controller.start_investigation(
        session.controller_session_id,
        root,
        CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
    )
    assert later.session.phase is SessionPhase.INVESTIGATING
    assert later.receipt.succeeded is True
    assert len(runner.calls) == 1


def test_invocation_command_is_pinned_to_discovery_verified_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """argv[0] remains the verified resolved file after PATH substitution."""
    runner = FakeRunner()
    adapter = _adapter(runner, executable="codex")
    root = _workspace(tmp_path)

    monkeypatch.setenv("PATH", str(tmp_path / "attacker-path"))
    adapter.invoke(
        CodexInvocationRequest(
            workspace_root=root,
            prompt="Inspect only this workspace.",
            output_schema=SCHEMA,
            timeout_seconds=5,
        )
    )

    assert len(runner.calls) == 1
    argv0 = runner.calls[0][0]
    assert argv0 == str(adapter.resolved_executable)
    assert argv0 != "codex"


def test_nested_symlink_fingerprint_failure_is_typed_and_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nested-link evidence is retained only as the cause of a sanitized error."""
    monkeypatch.setattr(
        codex_session_module,
        "workspace_fingerprint",
        lambda root: (_ for _ in ()).throw(
            CodexProcessBoundaryError(
                "C:/secret/customer/password=credential/source.txt is a symbolic link."
            )
        ),
    )
    store = JsonSessionStore(tmp_path / "sessions.json")
    controller = CodexSessionController(store, _adapter(FakeRunner()), clock=TickClock())
    root = _workspace(tmp_path)

    with pytest.raises(WorkspaceBoundaryViolation) as captured:
        controller.create_session(root)

    assert isinstance(captured.value, CodexSessionError)
    assert isinstance(captured.value.__cause__, CodexProcessBoundaryError)
    public = str(captured.value)
    assert public == "Workspace boundary validation failed."
    assert "secret" not in public
    assert "credential" not in public
    assert str(root) not in public


@pytest.mark.parametrize(
    ("liveness", "error_type"),
    [
        (OperationLiveness.ALIVE, ActiveOperationAlive),
        (OperationLiveness.UNKNOWN, ActiveOperationLivenessUnknown),
    ],
)
def test_recovery_rejects_live_and_unknown_liveness(
    tmp_path: Path,
    liveness: OperationLiveness,
    error_type: type[Exception],
) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    verifier = FakeLivenessVerifier(liveness)
    controller = CodexSessionController(
        store,
        _adapter(FakeRunner()),
        clock=TickClock(),
        liveness_verifier=verifier,
    )
    session = controller.create_session(_workspace(tmp_path))
    operation_id = _retain_active_operation(store, session.controller_session_id)

    with pytest.raises(error_type):
        controller.recover_abandoned_operation(
            session.controller_session_id,
            operation_id,
        )

    retained = store.load(session.controller_session_id)
    assert retained.codex_process_active is True
    assert retained.active_operation is not None
    assert retained.active_operation.operation_id == operation_id


def test_recovery_rejects_wrong_operation_id_without_liveness_check(
    tmp_path: Path,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    verifier = FakeLivenessVerifier(OperationLiveness.DEAD)
    controller = CodexSessionController(
        store,
        _adapter(FakeRunner()),
        clock=TickClock(),
        liveness_verifier=verifier,
    )
    session = controller.create_session(_workspace(tmp_path))
    operation_id = _retain_active_operation(store, session.controller_session_id)

    with pytest.raises(ActiveOperationMismatch):
        controller.recover_abandoned_operation(
            session.controller_session_id,
            str(uuid.uuid4()),
        )

    assert verifier.calls == []
    retained = store.load(session.controller_session_id)
    assert retained.codex_process_active is True
    assert retained.active_operation is not None
    assert retained.active_operation.operation_id == operation_id


class RecoveryFailingStore:
    def __init__(self, delegate: JsonSessionStore) -> None:
        self.delegate = delegate

    def create(self, session: Any) -> None:
        self.delegate.create(session)

    def load(self, controller_session_id: str) -> Any:
        return self.delegate.load(controller_session_id)

    def save(self, session: Any) -> None:
        self.delegate.save(session)

    def recover(self, session: Any, expected_operation_id: str) -> None:
        raise SessionPersistenceError("injected recovery persistence failure")


def test_recovery_persistence_failure_leaves_active_marker_unchanged(
    tmp_path: Path,
) -> None:
    delegate = JsonSessionStore(tmp_path / "sessions.json")
    store = RecoveryFailingStore(delegate)
    controller = CodexSessionController(
        store,
        _adapter(FakeRunner()),
        clock=TickClock(),
        liveness_verifier=FakeLivenessVerifier(OperationLiveness.DEAD),
    )
    session = controller.create_session(_workspace(tmp_path))
    operation_id = _retain_active_operation(delegate, session.controller_session_id)

    with pytest.raises(SessionPersistenceError):
        controller.recover_abandoned_operation(
            session.controller_session_id,
            operation_id,
        )

    retained = delegate.load(session.controller_session_id)
    assert retained.codex_process_active is True
    assert retained.active_operation is not None
    assert retained.recovery_events == ()


def test_recovery_preserves_phase_bindings_identity_and_success_receipts(
    tmp_path: Path,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    runner = FakeRunner()
    controller = CodexSessionController(
        store,
        _adapter(runner),
        clock=TickClock(),
        liveness_verifier=FakeLivenessVerifier(OperationLiveness.DEAD),
    )
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    investigated = controller.start_investigation(
        created.controller_session_id,
        root,
        CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
    ).session
    operation_id = _retain_active_operation(store, investigated.controller_session_id)

    recovered = controller.recover_abandoned_operation(
        investigated.controller_session_id,
        operation_id,
    )

    assert recovered.phase is investigated.phase
    assert recovered.workspace_root == investigated.workspace_root
    assert recovered.workspace_fingerprint == investigated.workspace_fingerprint
    assert recovered.approved_workspace_root == investigated.approved_workspace_root
    assert recovered.codex_session_id == investigated.codex_session_id
    assert (
        recovered.last_successful_invocation_receipt
        == investigated.last_successful_invocation_receipt
    )
    assert recovered.last_invocation_receipt == investigated.last_invocation_receipt
    assert recovered.last_successful_invocation_receipt is not None
    assert recovered.last_successful_invocation_receipt.succeeded is True
    assert recovered.recovery_events[-1].sanitized_error_code == (
        "abandoned_operation_recovered"
    )


def test_ambiguous_launch_handoff_is_unknown_and_running_dead_process_recovers(
    tmp_path: Path,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    verifier = FakeLivenessVerifier(OperationLiveness.DEAD)
    controller = CodexSessionController(
        store,
        _adapter(FakeRunner()),
        clock=TickClock(),
        liveness_verifier=verifier,
    )
    first = controller.create_session(_workspace(tmp_path, "first"))
    launching_id = _retain_active_operation(
        store,
        first.controller_session_id,
        stage=OperationStage.LAUNCHING,
    )
    with pytest.raises(ActiveOperationLivenessUnknown):
        controller.recover_abandoned_operation(
            first.controller_session_id,
            launching_id,
        )

    second = controller.create_session(_workspace(tmp_path, "second"))
    running_id = _retain_active_operation(
        store,
        second.controller_session_id,
        stage=OperationStage.RUNNING,
    )
    recovered = controller.recover_abandoned_operation(
        second.controller_session_id,
        running_id,
    )
    assert recovered.codex_process_active is False


class BlockingDeadVerifier:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def check(self, identity: ProcessIdentity) -> OperationLiveness:
        self.started.set()
        assert self.release.wait(timeout=5)
        return OperationLiveness.DEAD


def test_two_concurrent_recoveries_cannot_both_succeed(tmp_path: Path) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    verifier = BlockingDeadVerifier()
    controller = CodexSessionController(
        store,
        _adapter(FakeRunner()),
        clock=TickClock(),
        liveness_verifier=verifier,
    )
    session = controller.create_session(_workspace(tmp_path))
    operation_id = _retain_active_operation(store, session.controller_session_id)
    outcomes: list[object] = []

    def recover() -> None:
        try:
            outcomes.append(
                controller.recover_abandoned_operation(
                    session.controller_session_id,
                    operation_id,
                )
            )
        except BaseException as exc:
            outcomes.append(exc)

    thread = threading.Thread(target=recover)
    thread.start()
    assert verifier.started.wait(timeout=5)
    with pytest.raises(CodexSessionBusy):
        controller.recover_abandoned_operation(
            session.controller_session_id,
            operation_id,
        )
    verifier.release.set()
    thread.join(timeout=5)

    assert len(outcomes) == 1
    assert not isinstance(outcomes[0], BaseException)
    assert len(store.load(session.controller_session_id).recovery_events) == 1


class BarrierDeadVerifier:
    def __init__(self, barrier: threading.Barrier) -> None:
        self.barrier = barrier

    def check(self, identity: ProcessIdentity) -> OperationLiveness:
        self.barrier.wait(timeout=5)
        return OperationLiveness.DEAD


def test_independent_controllers_share_atomic_recovery_cas(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    first_store = JsonSessionStore(path)
    bootstrap = CodexSessionController(
        first_store,
        _adapter(FakeRunner()),
        clock=TickClock(),
    )
    session = bootstrap.create_session(_workspace(tmp_path))
    operation_id = _retain_active_operation(first_store, session.controller_session_id)
    barrier = threading.Barrier(2)
    controllers = (
        CodexSessionController(
            first_store,
            _adapter(FakeRunner()),
            clock=TickClock(),
            liveness_verifier=BarrierDeadVerifier(barrier),
        ),
        CodexSessionController(
            JsonSessionStore(path),
            _adapter(FakeRunner()),
            clock=TickClock(),
            liveness_verifier=BarrierDeadVerifier(barrier),
        ),
    )
    outcomes: list[object] = []

    def recover(controller: CodexSessionController) -> None:
        try:
            outcomes.append(
                controller.recover_abandoned_operation(
                    session.controller_session_id,
                    operation_id,
                )
            )
        except BaseException as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=recover, args=(item,)) for item in controllers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    successes = [item for item in outcomes if not isinstance(item, BaseException)]
    failures = [item for item in outcomes if isinstance(item, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ActiveOperationMismatch)
    assert len(first_store.load(session.controller_session_id).recovery_events) == 1


def _copied_executable_adapter(
    tmp_path: Path,
    runner: FakeRunner,
) -> CodexCliProcessAdapter:
    executable = tmp_path / Path(sys.executable).name
    shutil.copy2(sys.executable, executable)
    return CodexCliProcessAdapter(
        "codex",
        resolved_executable=executable,
        version="codex-cli test",
        capabilities=CodexCliCapabilities(True, False, False, False, False),
        process_runner=runner,
    )


def _invoke_adapter(adapter: CodexCliProcessAdapter, workspace: Path) -> None:
    adapter.invoke(
        CodexInvocationRequest(
            workspace_root=workspace,
            prompt="Inspect only this workspace.",
            output_schema=SCHEMA,
            timeout_seconds=5,
        )
    )


def test_validated_executable_launches_with_exact_resolved_argv0(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    adapter = _copied_executable_adapter(tmp_path, runner)
    root = _workspace(tmp_path)

    _invoke_adapter(adapter, root)

    assert runner.calls == [runner.calls[0]]
    assert runner.calls[0][0] == str(adapter.resolved_executable)


def test_deleting_pinned_executable_fails_before_runner(tmp_path: Path) -> None:
    runner = FakeRunner()
    adapter = _copied_executable_adapter(tmp_path, runner)
    root = _workspace(tmp_path)
    adapter.resolved_executable.unlink()

    with pytest.raises(CodexProcessBoundaryError):
        _invoke_adapter(adapter, root)

    assert runner.calls == []


def test_same_path_executable_byte_replacement_fails_before_runner(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    adapter = _copied_executable_adapter(tmp_path, runner)
    root = _workspace(tmp_path)
    adapter.resolved_executable.write_bytes(b"attacker replacement bytes")

    with pytest.raises(CodexProcessBoundaryError):
        _invoke_adapter(adapter, root)

    assert runner.calls == []


def test_same_path_link_replacement_fails_even_with_identical_bytes(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    adapter = _copied_executable_adapter(tmp_path, runner)
    root = _workspace(tmp_path)
    adapter.resolved_executable.unlink()
    os.link(sys.executable, adapter.resolved_executable)

    with pytest.raises(CodexProcessBoundaryError):
        _invoke_adapter(adapter, root)

    assert runner.calls == []


def test_same_path_unsupported_type_replacement_fails_before_runner(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    adapter = _copied_executable_adapter(tmp_path, runner)
    root = _workspace(tmp_path)
    adapter.resolved_executable.unlink()
    adapter.resolved_executable.mkdir()

    with pytest.raises(CodexProcessBoundaryError):
        _invoke_adapter(adapter, root)

    assert runner.calls == []


def _raise_sensitive_workspace_error(root: Path) -> str:
    raise CodexProcessBoundaryError(
        "C:/raw/customer/source.txt contained password=top-secret"
    )


def _assert_typed_workspace_failure(call: Any) -> None:
    with pytest.raises(WorkspaceBoundaryViolation) as captured:
        call()
    assert isinstance(captured.value.__cause__, CodexProcessBoundaryError)
    public = str(captured.value)
    assert public == "Workspace boundary validation failed."
    assert "customer" not in public
    assert "password" not in public
    assert "top-secret" not in public


def test_original_workspace_operation_boundary_translates_process_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    controller = CodexSessionController(store, _adapter(FakeRunner()), clock=TickClock())
    root = _workspace(tmp_path)
    session = controller.create_session(root)
    monkeypatch.setattr(
        codex_session_module,
        "workspace_fingerprint",
        _raise_sensitive_workspace_error,
    )

    _assert_typed_workspace_failure(
        lambda: controller.start_investigation(
            session.controller_session_id,
            root,
            CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
        )
    )


def test_approved_workspace_binding_translates_process_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    controller = CodexSessionController(store, _adapter(FakeRunner()), clock=TickClock())
    original = _workspace(tmp_path, "original")
    approved = _workspace(tmp_path, "approved")
    session = controller.create_session(original)
    investigated = controller.start_investigation(
        session.controller_session_id,
        original,
        CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
    ).session
    waiting = controller.record_awaiting_human_review(
        investigated.controller_session_id
    )
    monkeypatch.setattr(
        codex_session_module,
        "workspace_fingerprint",
        _raise_sensitive_workspace_error,
    )

    _assert_typed_workspace_failure(
        lambda: controller.bind_approved_workspace(
            waiting.controller_session_id,
            approved,
            "0" * 64,
        )
    )


def test_resume_and_preflight_boundaries_translate_process_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    controller = CodexSessionController(store, _adapter(FakeRunner()), clock=TickClock())
    root = _workspace(tmp_path)
    approved = _workspace(tmp_path, "approved")
    created = controller.create_session(root)
    codex_id = "12345678-1234-5678-9234-567812345678"
    retained = replace(
        created,
        codex_session_id=codex_id,
        phase=SessionPhase.CONVERSATIONAL,
        resume_supported=True,
        approved_workspace_root=str(approved),
        approved_workspace_fingerprint=codex_session_module.workspace_fingerprint(
            approved
        ),
    )
    store.save(retained)
    monkeypatch.setattr(
        codex_session_module,
        "workspace_fingerprint",
        _raise_sensitive_workspace_error,
    )

    _assert_typed_workspace_failure(
        lambda: controller.resume_session(
            retained.controller_session_id,
            codex_id,
            approved,
            CodexOperationRequest("Continue this conversation.", SCHEMA, 5),
        )
    )
    _assert_typed_workspace_failure(
        lambda: controller.resume_session(
            retained.controller_session_id,
            str(uuid.uuid4()),
            approved,
            CodexOperationRequest("Continue this conversation.", SCHEMA, 5),
        )
    )


def test_provider_constructors_remain_unused_across_recovery_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import continuity_ai.deterministic_offline_provider as offline_module
    import continuity_ai.openai_provider as provider_module

    calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> object:
        calls.append("provider")
        raise AssertionError("provider fallback invoked")

    monkeypatch.setattr(provider_module, "OpenAIReasoningProvider", forbidden)
    monkeypatch.setattr(
        offline_module,
        "DeterministicOfflineReasoningProvider",
        forbidden,
    )
    for index, liveness in enumerate(
        (
            OperationLiveness.ALIVE,
            OperationLiveness.UNKNOWN,
            OperationLiveness.DEAD,
        )
    ):
        store = JsonSessionStore(tmp_path / f"sessions-{index}.json")
        controller = CodexSessionController(
            store,
            _adapter(FakeRunner()),
            clock=TickClock(),
            liveness_verifier=FakeLivenessVerifier(liveness),
        )
        session = controller.create_session(_workspace(tmp_path, f"workspace-{index}"))
        operation_id = _retain_active_operation(store, session.controller_session_id)
        if liveness is OperationLiveness.DEAD:
            controller.recover_abandoned_operation(
                session.controller_session_id,
                operation_id,
            )
        else:
            with pytest.raises(AbandonedOperationRecoveryError):
                controller.recover_abandoned_operation(
                    session.controller_session_id,
                    operation_id,
                )

    assert calls == []
