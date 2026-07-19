"""Permanent regressions converted from the independent v0.3 final re-audit.

The audit-only commit remains unchanged in history. This later repair converts
each one-way defect reproducer into a fixed-behavior assertion that traverses
both cause and context cycle-safely.
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
    CodexProcessBoundaryError,
    CodexWorkspaceUnavailableBeforeLaunch,
    _invocation_paths,
    _workspace_before_launch,
)
from continuity_ai.codex_session import (
    CodexOperationRequest,
    CodexSessionController,
    JsonSessionStore,
    SessionPersistenceError,
    WorkspaceChanged,
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


def _full_exception_graph(exc: BaseException) -> list[BaseException]:
    seen_ids: set[int] = set()
    graph: list[BaseException] = []
    frontier: list[BaseException | None] = [exc]
    while frontier:
        current = frontier.pop()
        if current is None or id(current) in seen_ids:
            continue
        seen_ids.add(id(current))
        graph.append(current)
        frontier.append(current.__cause__)
        frontier.append(current.__context__)
    return graph


def _assert_sanitized_exception_graph(
    error: BaseException, *forbidden_values: object
) -> None:
    graph = _full_exception_graph(error)
    assert not any(
        isinstance(item, (OSError, FileNotFoundError, PermissionError))
        for item in graph
    )
    for item in graph:
        exposed = (
            str(item),
            repr(item),
            repr(item.args),
            str(getattr(item, "filename", "")),
        )
        for forbidden in forbidden_values:
            value = str(forbidden)
            assert value
            assert all(value not in candidate for candidate in exposed)


def test_low_level_workspace_boundary_severs_raw_os_error_graph() -> None:
    missing = Path("C:/__continuity_audit_v03_nonexistent_workspace__")
    assert not missing.exists()
    with pytest.raises(CodexWorkspaceUnavailableBeforeLaunch) as captured:
        _workspace_before_launch(missing)

    exc = captured.value
    assert str(exc) == (
        "Workspace is unavailable before Codex process launch."
    )
    _assert_sanitized_exception_graph(exc, missing, missing.name)


def test_invocation_paths_boundary_severs_raw_os_error_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import continuity_ai.codex_process as codex_process

    secret_temp_root = tmp_path / "secret-temp-root"

    class ExplodingTempDir:
        def __enter__(self) -> str:
            raise OSError(13, "Permission denied", str(secret_temp_root))

        def __exit__(self, *exc_info: object) -> None:
            return None

    monkeypatch.setattr(
        codex_process.tempfile, "TemporaryDirectory", lambda **_: ExplodingTempDir()
    )

    schema = {"type": "object", "credential": "audit-secret-credential"}
    with pytest.raises(CodexProcessBoundaryError) as captured:
        with _invocation_paths(schema):
            pass  # pragma: no cover - context manager raises on __enter__

    exc = captured.value
    assert str(exc) == "Codex pre-launch boundary preparation failed."
    _assert_sanitized_exception_graph(
        exc,
        secret_temp_root,
        tmp_path,
        "secret-temp-root",
        "audit-secret-credential",
    )


def test_session_persistence_boundary_severs_raw_os_error_graph(
    tmp_path: Path,
) -> None:
    bogus_parent = tmp_path / "does_not_exist" / "sessions.json"
    store = JsonSessionStore(bogus_parent)
    document = {
        "schema_version": 3,
        "sessions": {"credential": "audit-secret-store-document"},
    }

    with pytest.raises(SessionPersistenceError) as captured:
        store._write_document(document)

    exc = captured.value
    assert str(exc) == "Session store parent is unavailable."
    _assert_sanitized_exception_graph(
        exc,
        bogus_parent,
        tmp_path,
        "does_not_exist",
        "audit-secret-store-document",
        json.dumps(document, sort_keys=True),
    )


def test_full_controller_toctou_severs_graph_releases_and_reuses_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the audit's exact post-reservation/pre-adapter deletion trigger."""

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
    store_document = store.path.read_text(encoding="utf-8")
    request = CodexOperationRequest(
        "credential=audit-secret-controller", SCHEMA, 5
    )

    with pytest.raises(WorkspaceChanged) as captured:
        controller.start_investigation(
            session.controller_session_id,
            root,
            request,
        )

    assert str(captured.value) == (
        "Workspace changed before Codex process launch."
    )
    _assert_sanitized_exception_graph(
        captured.value,
        root,
        tmp_path,
        "alpha",
        "audit-secret-controller",
        store_document,
    )
    retained = store.load(session.controller_session_id)
    assert captured.value.receipt is not None
    assert retained.last_invocation_receipt == captured.value.receipt
    assert retained.last_successful_invocation_receipt is None
    assert retained.active_operation is None
    assert retained.codex_process_active is False
    assert runner.calls == []
    assert provider_constructor_calls == 0

    root.mkdir()
    (root / "source.txt").write_text("alpha", encoding="utf-8")
    retry_controller = CodexSessionController(store, base, clock=TickClock())
    retried = retry_controller.start_investigation(
        session.controller_session_id,
        root,
        CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
    )
    assert retried.receipt.succeeded is True
    assert retried.session.controller_session_id == session.controller_session_id
    assert len(runner.calls) == 1
    assert provider_constructor_calls == 0


def test_permission_error_secret_path_is_absent_from_full_exception_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain the audit's injected PermissionError and secret-path probe."""

    from continuity_ai.openai_provider import OpenAIReasoningProvider
    from continuity_ai.codex_session import (
        CodexOperationRequest,
        CodexSessionController,
        JsonSessionStore,
        WorkspaceChanged,
    )

    provider_constructor_calls = 0

    def forbidden_provider_constructor(self, client=None):  # type: ignore[no-untyped-def]
        nonlocal provider_constructor_calls
        provider_constructor_calls += 1

    monkeypatch.setattr(
        OpenAIReasoningProvider, "__init__", forbidden_provider_constructor
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
    store_document = store.path.read_text(encoding="utf-8")

    with pytest.raises(WorkspaceChanged) as captured:
        controller.start_investigation(
            session.controller_session_id,
            root,
            CodexOperationRequest("Inspect only this workspace.", SCHEMA, 5),
        )

    assert str(captured.value) == (
        "Workspace changed before Codex process launch."
    )
    _assert_sanitized_exception_graph(
        captured.value,
        root,
        tmp_path,
        "C:/secret/customer/source.txt",
        "secret",
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
    assert provider_constructor_calls == 0
