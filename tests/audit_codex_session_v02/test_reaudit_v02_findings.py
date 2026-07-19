"""Independent re-audit of the local Codex session controller v0.2 repair.

These tests do not assume the prior repair report is correct. They attempt to
falsify each closed-defect claim from first principles, and probe two code
paths the existing audit suite (tests/audit_codex_session/) does not exercise:

1. ``CodexCliProcessAdapter.invoke`` resolves ``request.workspace_root`` with a
   bare ``Path.resolve(strict=True)`` *before* entering its own try/except
   boundary. If the workspace disappears in the narrow window between the
   controller's own workspace validation and the adapter call, a raw OS
   exception (not ``CodexProcessBoundaryError``) can escape ``invoke`` and,
   because it is not one of the exception types the controller's ``_execute``
   catches, it also escapes the public controller API. Because the exception
   is raised before ``lifecycle.before_launch`` even runs, the RESERVED active
   marker persisted immediately before the call is never cleared by a failure
   path -- there is no ``store.save(failed)``. This reproduces the shape of
   the original "persisted active-operation marker can permanently lock a
   session" defect through a different trigger than the one already closed.

2. ``JsonSessionStore.save`` performs no compare-and-swap against the durable
   document it is about to overwrite -- only ``JsonSessionStore.recover``
   takes the cross-process advisory lock and re-reads current state before
   committing. Two independent controller instances (standing in for two OS
   processes) that both load the same controller session before either
   writes can both believe they have exclusively reserved the session, and
   the second writer's save silently discards the first writer's persisted
   operation/receipt with no error raised to either caller.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from continuity_ai.codex_process import (
    CodexCliCapabilities,
    CodexCliProcessAdapter,
)
from continuity_ai.codex_session import (
    ActiveOperationAlive,
    CodexOperationRequest,
    CodexSessionBusy,
    CodexSessionController,
    CodexSessionError,
    JsonSessionStore,
    SessionPhase,
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


def _adapter(runner: FakeRunner) -> CodexCliProcessAdapter:
    return CodexCliProcessAdapter(
        "codex",
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


class DeleteWorkspaceBeforeInvokeAdapter(CodexCliProcessAdapter):
    """Stand-in for a real TOCTOU race: the workspace vanishes right as the
    adapter begins its own invocation, after the controller already validated
    it and persisted the RESERVED marker."""

    def invoke(self, request):  # type: ignore[override]
        shutil.rmtree(request.workspace_root, ignore_errors=True)
        return super().invoke(request)


def test_workspace_deleted_between_controller_validation_and_adapter_invoke_leaks_raw_oserror(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    base = _adapter(runner)
    adapter = DeleteWorkspaceBeforeInvokeAdapter(
        base.executable,
        resolved_executable=base.resolved_executable,
        version=base.version,
        capabilities=base.capabilities,
        executable_identity=base.executable_identity,
        process_runner=runner,
    )
    store = JsonSessionStore(tmp_path / "sessions.json")
    controller = CodexSessionController(store, adapter, clock=TickClock())
    root = _workspace(tmp_path)
    session = controller.create_session(root)

    with pytest.raises(Exception) as captured:
        controller.start_investigation(
            session.controller_session_id,
            root,
            CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
        )

    # FALSIFICATION: the escaping exception is a raw OSError, not the typed
    # CodexSessionError boundary the public API is supposed to guarantee.
    assert not isinstance(captured.value, CodexSessionError), (
        "expected a raw, untyped exception to escape (proving the gap); "
        "got a typed CodexSessionError instead, which would mean this is "
        "already handled"
    )
    assert isinstance(captured.value, OSError)

    stuck = store.load(session.controller_session_id)
    # FALSIFICATION: no failure receipt was ever persisted, so the active
    # marker set immediately before the adapter call is still active.
    assert stuck.codex_process_active is True
    assert stuck.active_operation is not None
    assert stuck.last_invocation_receipt is None

    # The owning process (this test process) is still alive, so every further
    # attempt to use the session is rejected as busy, and recovery is
    # rejected because the owner is provably ALIVE. There is no documented
    # operator-level path out of this state short of killing the process that
    # holds the owner identity -- reproducing the original permanent-lockout
    # defect through a different, still-open trigger.
    with pytest.raises(CodexSessionBusy):
        controller.start_investigation(
            session.controller_session_id,
            root,
            CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
        )
    with pytest.raises(ActiveOperationAlive):
        controller.recover_abandoned_operation(
            session.controller_session_id,
            stuck.active_operation.operation_id,
        )

    pytest.fail(
        "REPRODUCED: CodexCliProcessAdapter.invoke resolves "
        "request.workspace_root with a bare Path.resolve(strict=True) before "
        "entering its own try/except boundary (codex_process.py, invoke). "
        "When the workspace disappears between the controller's own "
        "workspace validation and this call, a raw OSError -- not "
        "CodexProcessBoundaryError, not any CodexSessionError -- escapes "
        "through the public controller API. Because the exception fires "
        "before lifecycle.before_launch, no failure receipt is ever "
        "persisted and the RESERVED active marker is never cleared. Every "
        "further call on this session raises CodexSessionBusy, and recovery "
        "is correctly rejected as ActiveOperationAlive because the owning "
        "process is genuinely still alive -- so the session is permanently "
        "locked for the remaining lifetime of that process, with no "
        "documented operator-level path out short of killing it."
    )


class ReleaseAfterLoadStore:
    """Wraps a JsonSessionStore so ``load`` returns a real, correctly-read
    snapshot but then blocks the caller inside ``load`` until told to
    proceed. This captures exactly what a second OS process's stale
    in-memory read would look like without also forcing concurrent real
    file I/O (which introduces unrelated Windows file-replace contention
    noise on top of the compare-and-swap gap this isolates)."""

    def __init__(self, delegate: JsonSessionStore, hold_until: threading.Event) -> None:
        self.delegate = delegate
        self.hold_until = hold_until

    def create(self, session: Any) -> None:
        self.delegate.create(session)

    def load(self, controller_session_id: str) -> Any:
        session = self.delegate.load(controller_session_id)
        assert self.hold_until.wait(timeout=5)
        return session

    def save(self, session: Any) -> None:
        self.delegate.save(session)

    def recover(self, session: Any, expected_operation_id: str) -> None:
        self.delegate.recover(session, expected_operation_id)


def test_stale_reader_can_silently_erase_an_already_completed_operation(
    tmp_path: Path,
) -> None:
    """Simulate two OS processes sharing one JsonSessionStore file. Process
    "stale" reads the session first but is descheduled before it acts
    (a realistic pause: GC, page fault, scheduler preemption). Process
    "authoritative" then runs an entire investigation to completion and its
    success is durably persisted and returned to its caller. Only after that
    does "stale" resume and persist its own (also successful) result, built
    from the pre-authoritative snapshot it read first.

    JsonSessionStore.save performs no compare-and-swap -- it is a blind
    last-writer-wins overwrite of the whole record -- so "stale" finishing
    second silently erases the authoritative, already-completed, already
    caller-acknowledged result with no error raised anywhere.
    """

    path = tmp_path / "sessions.json"
    bootstrap = CodexSessionController(
        JsonSessionStore(path), _adapter(FakeRunner()), clock=TickClock()
    )
    root = _workspace(tmp_path)
    session = bootstrap.create_session(root)

    release = threading.Event()
    stale_controller = CodexSessionController(
        ReleaseAfterLoadStore(JsonSessionStore(path), release),
        _adapter(FakeRunner(response=json.dumps({"answer": "stale-writer"}))),
        clock=TickClock(),
    )
    stale_outcome: dict[str, object] = {}

    def run_stale() -> None:
        try:
            stale_outcome["result"] = stale_controller.start_investigation(
                session.controller_session_id,
                root,
                CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
            )
        except BaseException as exc:  # noqa: BLE001 - captured for assertion
            stale_outcome["result"] = exc

    thread = threading.Thread(target=run_stale)
    thread.start()
    # The stale thread's load() call is synchronous and does no real I/O
    # delay before reaching the blocking wait(); this margin only protects
    # against scheduler jitter, it is not load-bearing for correctness.
    time.sleep(0.2)

    authoritative_controller = CodexSessionController(
        JsonSessionStore(path),
        _adapter(FakeRunner(response=json.dumps({"answer": "authoritative-writer"}))),
        clock=TickClock(),
    )
    completed = authoritative_controller.start_investigation(
        session.controller_session_id,
        root,
        CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
    )
    assert completed.session.phase is SessionPhase.INVESTIGATING
    assert completed.receipt.succeeded is True
    durable_after_authoritative = JsonSessionStore(path).load(session.controller_session_id)
    assert durable_after_authoritative.last_successful_invocation_receipt == completed.receipt

    release.set()
    thread.join(timeout=10)

    result = stale_outcome["result"]
    final = JsonSessionStore(path).load(session.controller_session_id)

    if isinstance(result, BaseException):
        # An implementation that is actually safe would reject the stale
        # writer with a typed conflict error instead of silently clobbering.
        assert isinstance(result, CodexSessionError)
        assert final.last_successful_invocation_receipt == completed.receipt
        return

    pytest.fail(
        "REPRODUCED: JsonSessionStore.save performs no compare-and-swap "
        "against the durable state it is about to overwrite (unlike "
        "JsonSessionStore.recover, which takes the cross-process advisory "
        "lock and re-reads current state first). A second controller "
        "process that read this session before an authoritative, already "
        "fully-persisted, already caller-acknowledged successful "
        "investigation (receipt=" + repr(completed.receipt) + ") went on to "
        "silently overwrite it with its own stale-based result "
        "(now persisted receipt=" + repr(final.last_invocation_receipt) + "). "
        "No error was raised to either caller, and the authoritative "
        "result is now permanently absent from durable state."
    )
