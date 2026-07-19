"""Independent bounded delta verification of the v0.3 raw-exception-leak repair.

These tests are deliberately NOT copies of the producer's converted tests in
``tests/audit_codex_session_v03`` or ``tests/test_codex_session.py``. Each one
exercises a different injection point, a different attribute surface, or a
different control-flow edge than the producer's own regressions, per the
bounded delta audit's requirement for fresh independent adversarial coverage.

Scope: only the raw-OS-exception-leak repair in
``src/continuity_ai/codex_process.py`` and ``src/continuity_ai/codex_session.py``
(commit 03493cb..361729f). No other behavior is re-audited here.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import continuity_ai.codex_process as codex_process_module
from continuity_ai.codex_process import (
    CodexCliCapabilities,
    CodexCliProcessAdapter,
    CodexProcessBoundaryError,
    CodexWorkspaceTypeChangedBeforeLaunch,
    CodexWorkspaceUnavailableBeforeLaunch,
    _invocation_paths,
    _workspace_before_launch,
    capture_workspace,
)
from continuity_ai.codex_session import (
    CodexOperationRequest,
    CodexSessionController,
    CodexUnavailable,
    JsonSessionStore,
    SessionPersistenceError,
    WorkspaceChanged,
    _session_store_lock,
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


THREAD_ID = "87654321-4321-8765-4321-876543214321"


@dataclass
class FakeRunner:
    response: str = json.dumps({"answer": "bounded"})
    returncode: int = 0
    thread_id: str | None = None

    def __post_init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **options: Any) -> Any:
        import subprocess

        self.calls.append(list(command))
        response_path = Path(command[command.index("--output-last-message") + 1])
        response_path.write_text(self.response, encoding="utf-8")
        stdout = (
            ""
            if self.thread_id is None
            else json.dumps({"type": "thread.started", "thread_id": self.thread_id}) + "\n"
        )
        return subprocess.CompletedProcess(command, self.returncode, stdout=stdout, stderr="")


def _adapter(runner: FakeRunner, *, resume: bool = False) -> CodexCliProcessAdapter:
    return CodexCliProcessAdapter(
        "codex",
        resolved_executable=Path(sys.executable),
        version="codex-cli test",
        capabilities=CodexCliCapabilities(
            True, resume, resume, resume, resume, resume_verified=resume
        ),
        process_runner=runner,
    )


def _workspace(tmp_path: Path, name: str = "workspace", content: str = "alpha") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "source.txt").write_text(content, encoding="utf-8")
    return root.resolve()


def _full_exception_graph(error: BaseException) -> list[BaseException]:
    """Cycle-safe traversal of both __cause__ and __context__."""

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


def _assert_fully_sanitized(error: BaseException, *forbidden_values: object) -> None:
    """Stricter than the producer's helper: also inspects strerror, winerror
    and filename2, which the producer's ``_assert_sanitized_exception_graph``
    helper does not check."""

    graph = _full_exception_graph(error)
    assert graph, "exception graph must contain at least the raised exception"
    for item in graph:
        assert not isinstance(item, (OSError, FileNotFoundError, PermissionError)), (
            f"raw OS exception reachable in graph: {type(item).__name__}"
        )
        exposed = [
            str(item),
            repr(item),
            repr(getattr(item, "args", ())),
            str(getattr(item, "filename", "") or ""),
            str(getattr(item, "filename2", "") or ""),
            str(getattr(item, "strerror", "") or ""),
            str(getattr(item, "winerror", "") or ""),
        ]
        for forbidden in forbidden_values:
            value = str(forbidden)
            assert value, "forbidden probe value must be non-empty"
            for candidate in exposed:
                assert value not in candidate, (
                    f"forbidden value {value!r} leaked via {candidate!r} on "
                    f"{type(item).__name__}"
                )


# ---------------------------------------------------------------------------
# 1. _workspace_before_launch: genuine TOCTOU deletion between lstat and resolve
# ---------------------------------------------------------------------------


def test_workspace_deleted_between_lstat_and_resolve_is_severed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unlike the producer's 'missing from the start' reproduction, this
    deletes the workspace as a side effect of the *first* successful lstat,
    forcing the failure to occur on the second boundary (.resolve(strict=True))
    inside _workspace_before_launch rather than at entry."""

    root = _workspace(tmp_path, name="toctou-lstat-resolve")
    original_lstat = Path.lstat
    triggered = False

    def deleting_lstat(path: Path, *args: Any, **kwargs: Any) -> Any:
        nonlocal triggered
        result = original_lstat(path, *args, **kwargs)
        if path == root and not triggered:
            triggered = True
            import shutil

            shutil.rmtree(root)
        return result

    monkeypatch.setattr(Path, "lstat", deleting_lstat)

    with pytest.raises(CodexWorkspaceUnavailableBeforeLaunch) as captured:
        _workspace_before_launch(root)

    assert triggered is True
    exc = captured.value
    assert str(exc) == "Workspace is unavailable before Codex process launch."
    _assert_fully_sanitized(exc, root, tmp_path, "toctou-lstat-resolve")


def test_capture_workspace_lstat_failure_has_no_unbound_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control-flow safety: the sentinel-flag refactor must not leave
    ``resolved`` referenced before assignment when the *very first* OS call
    fails. A regression here would surface as UnboundLocalError, not the
    intended typed exception -- an even worse leak than the original finding."""

    root = tmp_path / "capture-lstat-failure"
    root.mkdir()

    def failing_lstat(path: Path, *args: Any, **kwargs: Any) -> Any:
        raise OSError(13, "credential=audit-secret-capture-lstat", str(root))

    monkeypatch.setattr(Path, "lstat", failing_lstat)

    with pytest.raises(CodexProcessBoundaryError) as captured:
        capture_workspace(root)

    exc = captured.value
    assert type(exc) is CodexProcessBoundaryError
    assert str(exc) == "Workspace root could not be resolved."
    _assert_fully_sanitized(exc, root, tmp_path, "credential=audit-secret-capture-lstat")


# ---------------------------------------------------------------------------
# 2. PermissionError with secret carried in winerror/strerror/filename2
# ---------------------------------------------------------------------------


def test_permission_error_secret_in_strerror_winerror_filename2_is_severed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The producer's helper only inspects str/repr/args/filename. This probes
    the additional attributes the audit brief explicitly calls out: strerror,
    winerror, and filename2 -- all of which the 5-argument OSError/
    PermissionError constructor populates and which a naive `str(exc)` check
    would miss entirely."""

    root = _workspace(tmp_path, name="winerror-probe")
    secret_strerror = "credential=audit-secret-strerror-9f2c"
    secret_filename2 = str(tmp_path / "audit-secret-filename2-target")

    def failing_resolve(path: Path, *, strict: bool = False) -> Any:
        if path == root:
            err = PermissionError(
                13,
                secret_strerror,
                str(root),
                5,
                secret_filename2,
            )
            raise err
        return Path.resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", failing_resolve)

    with pytest.raises(CodexWorkspaceUnavailableBeforeLaunch) as captured:
        _workspace_before_launch(root)

    exc = captured.value
    _assert_fully_sanitized(
        exc,
        root,
        tmp_path,
        secret_strerror,
        secret_filename2,
        "winerror-probe",
        5,
    )
    # Belt-and-suspenders: confirm the injected PermissionError really did
    # carry these values, so a future refactor of this test can't silently
    # start asserting against an exception that never had the secrets at all.
    probe = PermissionError(13, secret_strerror, str(root), 5, secret_filename2)
    assert probe.strerror == secret_strerror
    assert probe.filename2 == secret_filename2
    assert probe.winerror == 5


# ---------------------------------------------------------------------------
# 3. _invocation_paths: failure writing the schema file inside a live tempdir
# ---------------------------------------------------------------------------


def test_invocation_paths_schema_write_failure_severed_and_tempdir_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The producer's reproduction fails at TemporaryDirectory.__enter__
    itself. This instead lets the real temp directory get created and fails
    the schema write_text call that happens inside it, proving the OS
    boundary is sanitized regardless of which operation inside the `with`
    fails, and that the real tempdir is still cleaned up by contextlib."""

    captured_temp_root: list[Path] = []
    original_write_text = Path.write_text

    def failing_write_text(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path.name == "response.schema.json":
            captured_temp_root.append(path.parent)
            raise OSError(28, "credential=audit-secret-schema-write", str(path))
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write_text)

    schema = {"type": "object", "credential": "audit-secret-schema-body"}
    with pytest.raises(CodexProcessBoundaryError) as captured:
        with _invocation_paths(schema):
            pass  # pragma: no cover - failure occurs before yield resumes caller

    exc = captured.value
    assert str(exc) == "Codex pre-launch boundary preparation failed."
    assert captured_temp_root, "the schema write must have actually been attempted"
    assert not captured_temp_root[0].exists(), (
        "temp directory must be cleaned up by contextlib even though the "
        "OS error was raised from inside the `with tempfile.TemporaryDirectory` block"
    )
    _assert_fully_sanitized(
        exc,
        captured_temp_root[0],
        tmp_path,
        "credential=audit-secret-schema-write",
        "audit-secret-schema-body",
    )


# ---------------------------------------------------------------------------
# 4. JsonSessionStore._write_document: failure during the temp write (not replace)
# ---------------------------------------------------------------------------


def test_write_document_temp_write_failure_leaves_durable_file_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Distinct from the producer's atomic-replace-failure test: this fails
    ``temporary.write_text`` itself (before replace is ever attempted), and
    verifies (a) the durable file is byte-identical to before, (b) the
    partial .tmp-* file was cleaned up rather than left on disk as a
    potential future authoritative document, and (c) the failure is
    sanitized."""

    store_path = tmp_path / "sessions.json"
    store = JsonSessionStore(store_path)
    original_document = {
        "schema_version": 3,
        "sessions": {"existing-session": {"marker": "must-survive"}},
    }
    store_path.write_text(
        json.dumps(original_document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    before_bytes = store_path.read_bytes()

    secret_document = {
        "schema_version": 3,
        "sessions": {"existing-session": {"marker": "audit-secret-document-body"}},
    }
    original_write_text = Path.write_text

    def failing_write_text(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path.name.startswith(".sessions.json.tmp-"):
            raise OSError(28, "credential=audit-secret-write-doc", str(path))
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write_text)

    with pytest.raises(SessionPersistenceError) as captured:
        store._write_document(secret_document)

    exc = captured.value
    assert str(exc) == "Session state could not be persisted atomically."
    assert store_path.read_bytes() == before_bytes, (
        "durable document must remain byte-identical when the temp write fails"
    )
    leftover_tmp = list(tmp_path.glob(".sessions.json.tmp-*"))
    assert leftover_tmp == [], "partial temp document must not remain on disk"
    _assert_fully_sanitized(
        exc,
        store_path,
        tmp_path,
        "credential=audit-secret-write-doc",
        "audit-secret-document-body",
    )


# ---------------------------------------------------------------------------
# 5. _session_store_lock: close() failure -- a path the producer never tests
# ---------------------------------------------------------------------------


class _CloseFailsProxy:
    """Delegates every operation to a real file object except close(), which
    performs the real close (so the OS handle is not leaked by the test
    itself) and then raises an OSError carrying a secret payload."""

    def __init__(self, real: Any, secret: str) -> None:
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_secret", secret)

    def close(self) -> None:
        real = object.__getattribute__(self, "_real")
        secret = object.__getattribute__(self, "_secret")
        real.close()
        raise OSError(9, "credential=" + secret, "SECRET_LOCK_HANDLE")

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_real"), name)


def test_session_store_lock_close_failure_is_severed_not_a_raw_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before the repair, ``lock_file.close()`` in the finally block had no
    try/except at all: a close() failure would propagate as a completely raw,
    unsanitized OSError straight out of the context manager. This is new
    surface introduced specifically by this delta (the finally now wraps
    close() in its own try/except OSError) and the producer's converted tests
    do not exercise it at all."""

    lock_path = tmp_path / ".sessions.json.lock"
    original_open = Path.open
    secret = "audit-secret-lock-close-9d31"

    def wrapping_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        real = original_open(path, *args, **kwargs)
        if path == lock_path:
            return _CloseFailsProxy(real, secret)
        return real

    monkeypatch.setattr(Path, "open", wrapping_open)

    with pytest.raises(SessionPersistenceError) as captured:
        with _session_store_lock(tmp_path / "sessions.json"):
            pass

    exc = captured.value
    assert str(exc) == "Session store lock is unavailable."
    _assert_fully_sanitized(exc, lock_path, tmp_path, secret, "SECRET_LOCK_HANDLE")


def test_session_store_lock_non_os_exception_is_not_swallowed(
    tmp_path: Path,
) -> None:
    """Control-flow safety: the lock context manager's except OSError clause
    must not accidentally widen to catch business-logic exceptions raised by
    caller code inside the `with` block. A ValueError from the body must
    propagate completely unmodified -- not be replaced by
    SessionPersistenceError -- and the lock must still be released so a
    subsequent acquisition on the same path succeeds."""

    store_path = tmp_path / "sessions.json"

    class _Marker(ValueError):
        pass

    with pytest.raises(_Marker):
        with _session_store_lock(store_path):
            raise _Marker("business logic failure, not an OS error")

    # The lock must have been released (not left held) despite the exception.
    with _session_store_lock(store_path):
        pass


def test_session_store_lock_acquisition_failure_is_severed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent variant of the lock-open failure: fails at the platform
    locking call (msvcrt.locking / fcntl.flock) rather than at Path.open,
    covering the middle of the try block instead of its start or end."""

    store_path = tmp_path / "sessions.json"
    secret = "audit-secret-lock-acquire-77ab"

    def failing_lock(*args: Any, **kwargs: Any) -> None:
        raise OSError(11, "credential=" + secret, "SECRET_LOCK_TARGET")

    if sys.platform == "win32":
        import msvcrt

        monkeypatch.setattr(msvcrt, "locking", failing_lock)
    else:
        import fcntl

        monkeypatch.setattr(fcntl, "flock", failing_lock)

    with pytest.raises(SessionPersistenceError) as captured:
        with _session_store_lock(store_path):
            pass  # pragma: no cover - locking fails before yield resumes caller

    exc = captured.value
    assert str(exc) == "Session store lock is unavailable."
    _assert_fully_sanitized(exc, store_path, tmp_path, secret, "SECRET_LOCK_TARGET")

    # The lock file handle must have been released, not left open/held.
    monkeypatch.undo()
    with _session_store_lock(store_path):
        pass


# ---------------------------------------------------------------------------
# 6. Full controller TOCTOU at a different point: deletion mid-snapshot-walk
# ---------------------------------------------------------------------------


def test_full_controller_toctou_deleted_during_snapshot_walk_preserves_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The producer's TOCTOU reproduction deletes the whole workspace with
    shutil.rmtree before invoke() runs at all, on a session with no prior
    receipt. This instead lets a first investigation succeed (establishing a
    genuine prior successful receipt), then resumes the session and deletes
    the workspace file being hashed mid-iteration of capture_workspace's
    rglob walk -- exercising the `except OSError: snapshot_failed = True`
    path specifically -- to prove the *prior* successful receipt survives a
    second, distinct failure on the same controller session."""

    from continuity_ai.openai_provider import OpenAIReasoningProvider

    provider_calls = 0

    def forbidden_provider(self: Any, client: Any = None) -> None:
        nonlocal provider_calls
        provider_calls += 1

    monkeypatch.setattr(OpenAIReasoningProvider, "__init__", forbidden_provider)

    runner = FakeRunner(thread_id=THREAD_ID)
    adapter = _adapter(runner, resume=True)
    store = JsonSessionStore(tmp_path / "sessions.json")
    controller = CodexSessionController(store, adapter, clock=TickClock())
    root = _workspace(tmp_path, name="snapshot-walk-toctou")

    session = controller.create_session(root)
    successful = controller.start_investigation(
        session.controller_session_id,
        root,
        CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
    )
    assert successful.receipt.succeeded is True
    assert len(runner.calls) == 1

    original_read_bytes = Path.read_bytes
    target = root / "source.txt"
    match_count = 0
    triggered = False

    def deleting_read_bytes(path: Path, *args: Any, **kwargs: Any) -> bytes:
        nonlocal match_count, triggered
        if path == target:
            match_count += 1
            # The 1st read of this call happens inside
            # _validate_workspace_binding's own fingerprint check, which runs
            # *before* the active-operation marker is reserved. Let that one
            # succeed so the deletion lands squarely in the audit brief's
            # post-reservation/pre-adapter-launch TOCTOU window instead --
            # i.e. inside _workspace_before_launch's own capture_workspace
            # validation call, invoked from within process_adapter.invoke().
            if match_count == 2:
                triggered = True
                path.unlink()
                raise OSError(2, "credential=audit-secret-snapshot-walk", str(path))
        return original_read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", deleting_read_bytes)

    request = CodexOperationRequest(
        "credential=audit-secret-request-body", SCHEMA, 5
    )
    with pytest.raises(WorkspaceChanged) as captured:
        controller.resume_session(
            session.controller_session_id, THREAD_ID, root, request
        )

    assert triggered is True
    exc = captured.value
    assert str(exc) == "Workspace changed before Codex process launch."
    _assert_fully_sanitized(
        exc,
        root,
        tmp_path,
        "credential=audit-secret-snapshot-walk",
        "credential=audit-secret-request-body",
        "snapshot-walk-toctou",
    )

    retained = store.load(session.controller_session_id)
    assert retained.controller_session_id == session.controller_session_id
    assert retained.active_operation is None
    assert retained.codex_process_active is False
    assert exc.receipt is not None
    assert retained.last_invocation_receipt == exc.receipt
    assert retained.last_successful_invocation_receipt == successful.receipt
    assert len(runner.calls) == 1, "no new runner call must occur on the failed attempt"
    assert provider_calls == 0, "no provider constructor call must occur"

    # The same session must be reusable without recovery or replacement.
    monkeypatch.undo()
    target.write_text("alpha", encoding="utf-8")
    retried = controller.resume_session(
        session.controller_session_id,
        THREAD_ID,
        root,
        CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
    )
    assert retried.receipt.succeeded is True
    assert retried.session.controller_session_id == session.controller_session_id
    assert len(runner.calls) == 2


# ---------------------------------------------------------------------------
# 7. Executable revalidation: CodexProcessBoundaryError (not OSError) severed too
# ---------------------------------------------------------------------------


def test_revalidate_executable_boundary_error_is_severed_not_just_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_revalidate_executable's except clause catches (OSError,
    CodexProcessBoundaryError). The producer only exercises the OSError arm.
    This exercises the CodexProcessBoundaryError arm directly against the
    module-level function, verifying the internal boundary error carrying a
    sensitive message is fully severed rather than merely partially chained,
    and that the specific CodexProcessBoundaryError text does not leak into
    the new exception's own graph."""

    runner = FakeRunner()
    adapter = _adapter(runner)
    secret_message = "credential=audit-secret-identity-check C:/secret/codex/internal.exe"

    def failing_identity(path: Path) -> Any:
        raise CodexProcessBoundaryError(secret_message)

    monkeypatch.setattr(
        codex_process_module, "_executable_identity", failing_identity
    )

    with pytest.raises(CodexProcessBoundaryError) as captured:
        adapter._revalidate_executable()

    exc = captured.value
    assert str(exc) == "Codex executable identity validation failed before launch."
    assert str(exc) != secret_message
    _assert_fully_sanitized(exc, secret_message, "audit-secret-identity-check")


# ---------------------------------------------------------------------------
# 8. Persistence boundary: unrelated session fully unaffected by a write failure
# ---------------------------------------------------------------------------


def test_unrelated_session_document_byte_identical_when_sibling_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two independent sessions share one JSON document. Force a persistence
    failure while saving session B and verify the durable document (which
    necessarily also contains session A) is completely byte-identical to
    before the failed attempt, and that session A's fields are unaffected."""

    store = JsonSessionStore(tmp_path / "sessions.json")
    runner = FakeRunner()
    adapter = _adapter(runner)
    controller = CodexSessionController(store, adapter, clock=TickClock())

    session_a = controller.create_session(_workspace(tmp_path, name="session-a"))
    session_b = controller.create_session(_workspace(tmp_path, name="session-b"))

    before_bytes = store.path.read_bytes()
    a_before = store.load(session_a.controller_session_id)

    from dataclasses import replace as dc_replace

    snapshot_b = store.load(session_b.controller_session_id)
    original_replace = Path.replace

    def failing_replace(path: Path, target: Path) -> Any:
        raise OSError(28, "credential=audit-secret-sibling-write", str(target))

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(SessionPersistenceError):
        store.save(dc_replace(snapshot_b, sanitized_error_code="tampered"))

    monkeypatch.undo()
    assert store.path.read_bytes() == before_bytes
    a_after = store.load(session_a.controller_session_id)
    assert a_after == a_before
    b_after = store.load(session_b.controller_session_id)
    assert b_after == snapshot_b
    assert b_after.revision == snapshot_b.revision
    assert b_after.sanitized_error_code != "tampered"


# ---------------------------------------------------------------------------
# 9. Control-flow regression: non-exception-driven typed errors still specific
# ---------------------------------------------------------------------------


def test_workspace_type_changed_to_file_still_raises_specific_error(
    tmp_path: Path,
) -> None:
    """This branch is not guarded by an OS-exception sentinel at all (no
    try/except involved) -- it is a pure stat-mode check. Confirms the
    sentinel-flag refactor applied to neighboring code in the same function
    did not accidentally fold this specific-error branch into the generic
    CodexWorkspaceUnavailableBeforeLaunch sentinel path."""

    root = tmp_path / "type-change-workspace"
    root.mkdir()
    (root / "source.txt").write_text("alpha", encoding="utf-8")
    resolved_root = root.resolve()

    import shutil

    shutil.rmtree(resolved_root)
    resolved_root.write_text("now a file, not a directory", encoding="utf-8")

    with pytest.raises(CodexWorkspaceTypeChangedBeforeLaunch) as captured:
        _workspace_before_launch(resolved_root)

    exc = captured.value
    assert type(exc) is CodexWorkspaceTypeChangedBeforeLaunch
    assert str(exc) == "Workspace is no longer a directory before Codex process launch."
    _assert_fully_sanitized(exc, resolved_root, tmp_path)


# ---------------------------------------------------------------------------
# 10. discover(): CodexProcessBoundaryError arm produces CodexUnavailable, severed
# ---------------------------------------------------------------------------


def test_controller_with_local_codex_boundary_error_severed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent of the producer's FileNotFoundError-only discovery test:
    exercises the CodexProcessBoundaryError arm of
    CodexSessionController.with_local_codex, which maps to CodexUnavailable
    rather than CodexNotInstalled, and confirms that arm is severed too."""

    secret_message = "credential=audit-secret-discover-boundary /opt/secret/codex"

    def failing_discover(cls: type, executable: str) -> Any:
        raise CodexProcessBoundaryError(secret_message)

    monkeypatch.setattr(
        CodexCliProcessAdapter, "discover", classmethod(failing_discover)
    )

    store = JsonSessionStore(tmp_path / "sessions.json")
    with pytest.raises(CodexUnavailable) as captured:
        CodexSessionController.with_local_codex(store)

    exc = captured.value
    assert str(exc) == "Codex capability discovery failed."
    _assert_fully_sanitized(exc, secret_message, "audit-secret-discover-boundary")
