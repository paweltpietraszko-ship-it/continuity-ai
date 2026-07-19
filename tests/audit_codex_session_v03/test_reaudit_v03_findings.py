"""Independent final re-audit of the local Codex session controller v0.3 repair
(exact SHA 40341748c04e5b6617be7efe15cedbcfc1cde126).

This suite does not trust the producer report. It attempts to falsify the two
v0.2-blocker closure claims and the CAS contract from first principles.

Central finding exercised here: the v0.3 repair wraps every pre-launch and
persistence OS boundary in a bare ``except OSError: raise Typed(...) from
None`` pattern. ``from None`` sets ``__cause__ = None`` and
``__suppress_context__ = True`` -- it suppresses *default traceback
rendering* of the chained exception. It does **not** clear
``__context__``. Python still auto-populates ``__context__`` with the
original OSError whenever a new exception is raised while another is being
handled, `from` clause or not. That raw OSError instance -- including its
``.filename`` attribute carrying the exact raw workspace/session-store path
-- remains reachable via ``exc.__context__`` (and, in the full controller
call chain, via ``exc.__cause__.__context__``) on the publicly raised typed
exception.

The existing converted v0.2 audit regression
(tests/audit_codex_session_v02/test_reaudit_v02_findings.py::
test_workspace_deleted_before_adapter_launch_is_typed_persisted_and_reusable)
only walks ``__cause__`` looking for a raw OSError. It never inspects
``__context__``, so it passes while the leak below reproduces cleanly
through the identical TOCTOU trigger that test uses.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from continuity_ai.codex_process import (
    CodexCliCapabilities,
    CodexCliProcessAdapter,
    CodexWorkspaceUnavailableBeforeLaunch,
    _invocation_paths,
    _workspace_before_launch,
)
from continuity_ai.codex_session import (
    CodexOperationRequest,
    CodexSessionController,
    CodexSessionError,
    JsonSessionStore,
    SessionPersistenceError,
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
    """Identical TOCTOU trigger to the converted v0.2 regression: delete the
    bound workspace after the controller has validated it and persisted the
    RESERVED marker, but before the adapter's own pre-launch boundary runs."""

    def invoke(self, request):  # type: ignore[override]
        shutil.rmtree(request.workspace_root, ignore_errors=True)
        return super().invoke(request)


def _full_exception_chain(exc: BaseException) -> list[BaseException]:
    """Walk both __cause__ and __context__ links, not just __cause__."""

    seen: list[BaseException] = []
    frontier: list[BaseException | None] = [exc]
    while frontier:
        current = frontier.pop()
        if current is None or current in seen:
            continue
        seen.append(current)
        frontier.append(current.__cause__)
        frontier.append(current.__context__)
    return seen


def test_low_level_workspace_boundary_leaks_raw_os_error_via_context() -> None:
    """Direct falsification of Area A item 9 against the exact repaired
    helper, isolated from the rest of the controller call chain."""

    missing = Path("C:/__continuity_audit_v03_nonexistent_workspace__")
    assert not missing.exists()
    with pytest.raises(CodexWorkspaceUnavailableBeforeLaunch) as captured:
        _workspace_before_launch(missing)

    exc = captured.value
    assert exc.__cause__ is None, "producer's `from None` does clear __cause__"
    assert exc.__suppress_context__ is True

    # This is the actual defect: __context__ is NOT cleared by `from None`.
    assert isinstance(exc.__context__, OSError), (
        "EXPECTED LEAK NOT REPRODUCED: if this assertion ever fails, the "
        "underlying Python chaining behavior changed or the implementation "
        "was fixed to also clear __context__ (e.g. via "
        "`exc.__context__ = None`) -- re-verify before treating this as a pass."
    )
    leaked_filename = getattr(exc.__context__, "filename", None)
    assert leaked_filename is not None
    assert str(missing) in str(leaked_filename)


def test_invocation_paths_boundary_leaks_raw_os_error_via_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same leak shape in the adapter-owned temporary launch artifact
    boundary (Area A item 7)."""

    import continuity_ai.codex_process as codex_process

    class ExplodingTempDir:
        def __enter__(self) -> str:
            raise OSError(13, "Permission denied", str(tmp_path / "secret-temp-root"))

        def __exit__(self, *exc_info: object) -> None:
            return None

    monkeypatch.setattr(
        codex_process.tempfile, "TemporaryDirectory", lambda **_: ExplodingTempDir()
    )

    with pytest.raises(codex_process.CodexProcessBoundaryError) as captured:
        with _invocation_paths({"type": "object"}):
            pass  # pragma: no cover - context manager raises on __enter__

    exc = captured.value
    assert exc.__cause__ is None
    assert isinstance(exc.__context__, OSError)
    assert "secret-temp-root" in str(getattr(exc.__context__, "filename", ""))


def test_session_persistence_boundary_leaks_raw_os_error_via_context(
    tmp_path: Path,
) -> None:
    """Same leak shape in the session-store durable write boundary
    (Area A item 7 / Area B item 21)."""

    bogus_parent = tmp_path / "does_not_exist" / "sessions.json"
    store = JsonSessionStore(bogus_parent)

    with pytest.raises(SessionPersistenceError) as captured:
        store._write_document({"schema_version": 3, "sessions": {}})

    exc = captured.value
    assert exc.__cause__ is None
    assert isinstance(exc.__context__, OSError)
    assert "does_not_exist" in str(getattr(exc.__context__, "filename", ""))


def test_full_controller_toctou_still_leaks_raw_workspace_path_in_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end reproduction through the exact same public API and exact
    same TOCTOU trigger as the converted v0.2 regression
    (tests/audit_codex_session_v02/test_reaudit_v02_findings.py ::
    test_workspace_deleted_before_adapter_launch_is_typed_persisted_and_reusable).

    That test only walks ``__cause__`` and finds nothing. This test walks
    both ``__cause__`` and ``__context__`` and finds the raw workspace path
    still attached to the publicly raised exception, proving the v0.2
    "raw OSError leak" blocker is only partially closed: the sanitized
    message text is fixed, but the raw path remains reachable on the
    exception object itself.
    """

    from continuity_ai.openai_provider import OpenAIReasoningProvider

    provider_constructor_calls = 0

    def forbidden_provider_constructor(self, client=None):  # type: ignore[no-untyped-def]
        nonlocal provider_constructor_calls
        provider_constructor_calls += 1

    monkeypatch.setattr(
        OpenAIReasoningProvider, "__init__", forbidden_provider_constructor
    )
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

    with pytest.raises(CodexSessionError) as captured:
        controller.start_investigation(
            session.controller_session_id,
            root,
            CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
        )

    chain = _full_exception_chain(captured.value)
    raw_os_errors = [item for item in chain if isinstance(item, OSError)]

    assert raw_os_errors, (
        "EXPECTED LEAK NOT REPRODUCED: if this assertion ever fails, the "
        "repair now fully severs __context__ on every boundary and the "
        "finding no longer applies -- re-verify before treating this as a "
        "pass rather than editing this test to match."
    )
    leaked = raw_os_errors[0]
    leaked_filename = getattr(leaked, "filename", None)
    assert leaked_filename is not None
    assert str(root) in str(leaked_filename), (
        "The raw workspace path is reachable via the public exception's "
        "__cause__/__context__ chain: " + repr(leaked)
    )

    # Confirm this genuinely differs from what the converted v0.2 regression
    # checks: that test's cause-only walk finds no OSError anywhere.
    cause_only_chain: list[BaseException] = []
    current: BaseException | None = captured.value
    while current is not None:
        cause_only_chain.append(current)
        current = current.__cause__
    assert not any(isinstance(item, OSError) for item in cause_only_chain), (
        "cause-only walk unexpectedly found the OSError too; the existing "
        "v0.2 regression's assertion would already have failed"
    )


def test_permission_error_secret_path_leaks_via_context_despite_producer_assertion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mirrors tests/test_codex_session.py::
    test_permission_error_prelaunch_is_typed_sanitized_and_has_no_fallback
    exactly (same PermissionError trigger, same embedded "secret" string in
    the raw OS message). That production test asserts
    ``"secret" not in str(captured.value)`` and walks only ``__cause__`` via
    ``_assert_sanitized_prelaunch_failure`` -- both pass. This test proves
    the embedded secret string is nonetheless reachable on the same publicly
    raised exception object via ``__context__``, so a caller that logs or
    serializes ``exc.__context__`` (a normal thing to do with an exception
    object, not exotic traceback introspection) does disclose it.
    """

    from continuity_ai.codex_session import (
        CodexOperationRequest,
        CodexSessionController,
        JsonSessionStore,
        WorkspaceChanged,
    )

    root = _workspace(tmp_path)
    original_lstat = Path.lstat

    def lstat(path: Path) -> Any:
        if path == root:
            raise PermissionError("C:/secret/customer/source.txt")
        return original_lstat(path)

    class PermissionDeniedAdapter(CodexCliProcessAdapter):
        def invoke(self, request):  # type: ignore[override]
            monkeypatch.setattr(Path, "lstat", lstat)
            return super().invoke(request)

    runner = FakeRunner()
    base = _adapter(runner)
    adapter = PermissionDeniedAdapter(
        base.executable,
        resolved_executable=base.resolved_executable,
        version=base.version,
        capabilities=base.capabilities,
        executable_identity=base.executable_identity,
        process_runner=runner,
    )
    store = JsonSessionStore(tmp_path / "sessions.json")
    controller = CodexSessionController(store, adapter, clock=TickClock())
    session = controller.create_session(root)

    with pytest.raises(WorkspaceChanged) as captured:
        controller.start_investigation(
            session.controller_session_id,
            root,
            CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
        )

    # The producer's own assertions, reproduced verbatim -- both pass.
    assert "secret" not in str(captured.value)
    current: BaseException | None = captured.value
    while current is not None:
        assert not isinstance(current, OSError)
        current = current.__cause__

    # Yet the raw secret string is fully reachable one hop further, on the
    # same exception object, via __context__.
    chain = _full_exception_chain(captured.value)
    leaked = [item for item in chain if isinstance(item, OSError)]
    assert leaked, "EXPECTED LEAK NOT REPRODUCED -- re-verify before treating as a pass"
    assert any("secret" in str(item) for item in leaked), (
        "the embedded secret path is reachable via __context__: " + repr(leaked)
    )
