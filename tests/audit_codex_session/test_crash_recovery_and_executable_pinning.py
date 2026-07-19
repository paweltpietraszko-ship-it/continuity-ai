"""Audit-only tests for the local Codex session controller (v0.1).

These tests do not modify production code. They exist to demonstrate two
reproducible defects found during adversarial review:

1. A session whose ``codex_process_active`` marker is left ``True`` by a
   hard crash (the controller process dying mid-invocation, after the
   active marker is persisted but before any completion state is saved)
   can never be recovered through any public controller method. Every
   method that could plausibly clear the marker calls ``_require_idle``
   first, which raises ``CodexSessionBusy`` before it can do any work.
   This is a permanent, irrecoverable lockout of an otherwise-valid
   controller session.

2. ``CodexCliProcessAdapter._build_command`` places ``self.executable``
   (the raw, unresolved command name such as ``"codex"``) as argv[0],
   not ``self.resolved_executable`` (the absolute path verified once at
   ``discover()`` time, whose version and capabilities were checked).
   This means the binary actually invoked is re-resolved from PATH at
   every invocation and is not pinned to the binary whose version string
   and resume-capability boundary were verified during discovery.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import continuity_ai.codex_session as codex_session_module
from continuity_ai.codex_process import (
    CodexCliCapabilities,
    CodexCliProcessAdapter,
    CodexProcessBoundaryError,
)
from continuity_ai.codex_session import (
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


def _adapter(runner: FakeRunner, *, executable: str = "codex") -> CodexCliProcessAdapter:
    return CodexCliProcessAdapter(
        executable,
        resolved_executable=Path("C:/Program Files/OpenAI/Codex/codex.exe"),
        version="codex-cli test",
        capabilities=CodexCliCapabilities(True, False, False, False, False),
        process_runner=runner,
    )


def _workspace(tmp_path: Path, name: str = "workspace") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "source.txt").write_text("alpha", encoding="utf-8")
    return root.resolve()


def _mark_active_in_store(store: JsonSessionStore, controller_session_id: str) -> None:
    """Simulate the on-disk state left behind by a hard crash mid-invocation.

    ``_execute`` persists ``codex_process_active=True`` (see
    ``codex_session.py`` around the "active marker is persisted before
    launch" comment) before ever starting the subprocess. If the entire
    controller process is killed at that instant -- not just the Codex
    subprocess -- this is exactly the byte-for-byte state left on disk.
    """
    document = json.loads(store.path.read_text(encoding="utf-8"))
    document["sessions"][controller_session_id]["codex_process_active"] = True
    store.path.write_text(json.dumps(document), encoding="utf-8")


def test_stale_active_marker_from_hard_crash_can_never_be_cleared(tmp_path: Path) -> None:
    """Reproduces: a crash-orphaned busy session has no recovery path.

    Precondition: ``codex_process_active`` is ``True`` on disk for a
    session (produced by a real crash between the pre-launch persistence
    write and any completion write -- reachable in production because
    nothing prevents the whole process, not just the Codex subprocess,
    from being killed in that window).

    Expected fail-closed behavior: some explicit, auditable recovery
    operation should be available to release the stale marker (e.g. after
    the operator confirms the OS-level process is actually gone), most
    naturally ``mark_interrupted`` since that is the method that exists
    to record exactly this situation.

    Observed unsafe state: every state-changing method -- including
    ``mark_interrupted``, whose entire purpose is to record an
    interruption -- calls ``_require_idle`` first and raises
    ``CodexSessionBusy`` before doing anything. The session is
    permanently unusable; there is no method in the public API that
    clears ``codex_process_active`` once it is stuck ``True``.
    """
    store = JsonSessionStore(tmp_path / "sessions.json")
    controller = CodexSessionController(store, _adapter(FakeRunner()), clock=TickClock())
    root = _workspace(tmp_path)
    session = controller.create_session(root)

    _mark_active_in_store(store, session.controller_session_id)
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

    still_stuck = store.load(session.controller_session_id)
    assert still_stuck.codex_process_active is True
    assert still_stuck.phase is SessionPhase.READY


def test_invocation_command_uses_unresolved_executable_name_not_discovery_verified_path(
    tmp_path: Path,
) -> None:
    """Reproduces: argv[0] is not pinned to the discovery-verified binary.

    Precondition: ``CodexCliProcessAdapter.discover`` has already run once
    and resolved+verified a specific binary (``resolved_executable``,
    ``version``, ``capabilities`` all correspond to that one file on
    disk). This is the normal path taken by
    ``CodexSessionController.with_local_codex``.

    Expected fail-closed state: the subprocess actually launched should
    be the exact file whose version/capabilities were verified --
    ``str(self.resolved_executable)`` -- so a binary substituted on PATH
    after discovery (the "executable disappearing after discovery"
    adversarial case) cannot be silently invoked in its place.

    Observed unsafe state: ``_build_command`` places ``self.executable``
    (the raw, unresolved name, e.g. ``"codex"``) as argv[0]. Command
    resolution therefore happens again, independently, at invoke time via
    whatever the child environment's PATH yields -- it is not pinned to
    the binary that was actually discovered and version-checked.
    """
    runner = FakeRunner()
    adapter = _adapter(runner, executable="codex")
    root = _workspace(tmp_path)

    from continuity_ai.codex_process import CodexInvocationRequest

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
    assert argv0 == "codex"
    assert argv0 != str(adapter.resolved_executable), (
        "argv[0] is not pinned to the discovery-verified resolved_executable path; "
        "the executable is re-resolved from PATH at every invocation."
    )


def test_nested_symlink_fingerprint_failure_leaks_unwrapped_process_boundary_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduces: a nested-symlink workspace raises outside the error taxonomy.

    Precondition: ``workspace_fingerprint`` (backed by
    ``capture_workspace`` in ``codex_process.py``) raises
    ``CodexProcessBoundaryError`` whenever it discovers a symbolic link
    anywhere under the workspace root, not only at the root itself. This
    is unconditional production behavior (``codex_process.py``: "Workspace
    cannot contain symbolic links."). This test simulates that raise
    directly via monkeypatch because this sandboxed Windows account lacks
    the privilege to create real symlinks (``os.symlink`` fails with
    WinError 1314 without Developer Mode/elevation) -- the code path being
    exercised is otherwise unconditional and not fixture-specific.

    Expected fail-closed state: every documented entry point
    (``create_session``, and equally ``_validate_workspace_binding`` used
    by ``start_investigation``/``start_reporting``/``resume_session``)
    commits to raising only the ``CodexSessionError`` hierarchy -- e.g.
    ``WorkspaceMismatch`` -- so callers can rely on a single exception
    taxonomy for every workspace-integrity failure.

    Observed unsafe state: ``create_session`` calls
    ``workspace_fingerprint`` with no exception translation, so a raw
    ``CodexProcessBoundaryError`` (a type from a different module, not a
    ``CodexSessionError`` subclass) escapes to the caller instead.
    """
    monkeypatch.setattr(
        codex_session_module,
        "workspace_fingerprint",
        lambda root: (_ for _ in ()).throw(
            CodexProcessBoundaryError("Workspace cannot contain symbolic links.")
        ),
    )
    store = JsonSessionStore(tmp_path / "sessions.json")
    controller = CodexSessionController(store, _adapter(FakeRunner()), clock=TickClock())
    root = _workspace(tmp_path)

    with pytest.raises(CodexProcessBoundaryError):
        controller.create_session(root)

    # Demonstrates the gap directly: this is NOT part of the module's own
    # documented failure hierarchy, even though every other workspace
    # failure in this module raises through CodexSessionError.
    try:
        controller.create_session(root)
        raise AssertionError("expected an exception")
    except CodexSessionError:
        raise AssertionError(
            "unexpectedly wrapped as CodexSessionError; if this fires, the defect "
            "in codex_session.py has been fixed and this audit test should be updated"
        )
    except CodexProcessBoundaryError:
        pass
