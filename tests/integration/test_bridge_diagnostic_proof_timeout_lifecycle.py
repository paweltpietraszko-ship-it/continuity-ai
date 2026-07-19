"""Bridge-level proof for M2: bounded, cancellation-aware background thread
lifecycle for the Diagnostic Proof split-phase scoping attempt.

All Codex CLI calls here are driven by scripted fake process runners (no
live network). This module never touches `continuity_ai.diagnostic_proof`
itself (the frozen core) -- only Bridge's own coordinator around it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import continuity_ai.integration.diagnostic_proof_bridge_flow as diag_flow_module
from continuity_ai.bridge import Bridge
from continuity_ai.codex_process import CodexCliCapabilities, CodexCliProcessAdapter
from continuity_ai.codex_session import CodexSessionController

THREAD_ID = "12345678-1234-5678-9234-567812345678"


class _UnusedReasoningProvider:
    provider_id = "unused-in-diagnostic-timeout-tests"

    def analyze(self, evidence, spans, question):
        raise AssertionError("local reasoning provider invoked during diagnostic flow")


def _patch_local_codex(monkeypatch: pytest.MonkeyPatch, runner: Any) -> None:
    def fake_with_local_codex(store, **_kwargs: Any) -> CodexSessionController:
        adapter = CodexCliProcessAdapter(
            "codex",
            resolved_executable=Path(sys.executable),
            version="codex-cli test",
            capabilities=CodexCliCapabilities(True, True, True, True, True, resume_verified=True),
            process_runner=runner,
        )
        return CodexSessionController(store, adapter)

    monkeypatch.setattr(
        diag_flow_module.CodexSessionController,
        "with_local_codex",
        classmethod(lambda cls, store, **kw: fake_with_local_codex(store, **kw)),
    )


@dataclass
class _RejectingRunner:
    """Simulates a semantic rejection: Codex responds fast, but with a
    payload that fails schema/semantic validation."""

    calls: list[tuple[list[str], dict[str, Any]]] = field(default_factory=list)

    def __call__(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(options)))
        response_path = Path(command[command.index("--output-last-message") + 1])
        response_path.write_text(json.dumps({"not": "the expected shape"}), encoding="utf-8")
        stdout = json.dumps({"type": "thread.started", "thread_id": THREAD_ID}) + "\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


@dataclass
class _ProcessFailureRunner:
    """Simulates a genuine process-level failure: non-zero exit code, no
    usable response at all -- distinct from a semantic rejection."""

    calls: list[tuple[list[str], dict[str, Any]]] = field(default_factory=list)

    def __call__(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(options)))
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="simulated process crash")


@dataclass
class _SlowRunner:
    """Simulates a hung Codex CLI process: ignores the timeout entirely
    (unlike a real subprocess, which the CodexCliProcessAdapter would kill)
    so the test can prove the coordinator's own outer bound is a genuine,
    independent fail-closed backstop."""

    delay_seconds: float
    calls: list[tuple[list[str], dict[str, Any]]] = field(default_factory=list)
    finished: threading.Event = field(default_factory=threading.Event)

    def __call__(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(options)))
        time.sleep(self.delay_seconds)
        response_path = Path(command[command.index("--output-last-message") + 1])
        response_path.write_text(json.dumps({"not": "the expected shape"}), encoding="utf-8")
        stdout = json.dumps({"type": "thread.started", "thread_id": THREAD_ID}) + "\n"
        self.finished.set()
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def _oracle_absent(root: Path) -> bool:
    return not any(
        path.name.casefold() in {"oracle", "expected_scope.json"} for path in root.rglob("*")
    )


def _set_fast_timeouts(monkeypatch: pytest.MonkeyPatch, *, codex: float = 5.0, outer: float = 5.0, join: float = 1.0) -> None:
    monkeypatch.setattr(diag_flow_module, "_CODEX_TIMEOUT_SECONDS", codex)
    monkeypatch.setattr(diag_flow_module, "_OUTER_TIMEOUT_SECONDS", outer)
    monkeypatch.setattr(diag_flow_module, "_JOIN_TIMEOUT_SECONDS", join)


def _forbid_fallback(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import continuity_ai.deterministic_offline_provider as offline_module
    import continuity_ai.openai_provider as provider_module

    fallback_calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> object:
        fallback_calls.append("fallback")
        raise AssertionError("provider fallback invoked")

    monkeypatch.setattr(provider_module, "OpenAIReasoningProvider", forbidden)
    monkeypatch.setattr(offline_module, "DeterministicOfflineReasoningProvider", forbidden)
    return fallback_calls


def test_semantic_rejection_allows_an_explicit_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fast_timeouts(monkeypatch)
    fallback_calls = _forbid_fallback(monkeypatch)
    bridge = Bridge(provider=_UnusedReasoningProvider())
    prepared = bridge.handle({"command": "diagnostic_prepare_workspace"})
    assert prepared["ok"] is True

    runner = _RejectingRunner()
    _patch_local_codex(monkeypatch, runner)

    first = bridge.handle({"command": "diagnostic_run_scoping"})
    assert first["ok"] is False
    assert first["error"]["code"] == "provider_error"
    assert bridge._diagnostic.phase == "workspace_ready"
    assert bridge._diagnostic._pending_run is None
    assert fallback_calls == []

    second = bridge.handle({"command": "diagnostic_run_scoping"})
    assert second["ok"] is False  # the rejecting runner rejects every attempt
    assert second["error"]["code"] == "provider_error"
    assert bridge._diagnostic.phase == "workspace_ready"
    assert len(runner.calls) == 2
    assert fallback_calls == []


def test_process_failure_allows_an_explicit_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fast_timeouts(monkeypatch)
    fallback_calls = _forbid_fallback(monkeypatch)
    bridge = Bridge(provider=_UnusedReasoningProvider())
    prepared = bridge.handle({"command": "diagnostic_prepare_workspace"})
    assert prepared["ok"] is True
    workspace_before = bridge._diagnostic.workspace

    runner = _ProcessFailureRunner()
    _patch_local_codex(monkeypatch, runner)

    first = bridge.handle({"command": "diagnostic_run_scoping"})
    assert first["ok"] is False
    assert first["error"]["code"] == "provider_error"
    assert bridge._diagnostic.phase == "workspace_ready"
    assert bridge._diagnostic.workspace is workspace_before
    assert fallback_calls == []

    second = bridge.handle({"command": "diagnostic_run_scoping"})
    assert second["ok"] is False
    assert second["error"]["code"] == "provider_error"
    assert len(runner.calls) == 2
    assert fallback_calls == []


def test_outer_timeout_blocks_retry_until_the_old_thread_actually_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fake runner ignores its own timeout, unlike a real subprocess the
    # CodexCliProcessAdapter would kill -- this specifically exercises the
    # coordinator's own independent fail-closed backstop.
    _set_fast_timeouts(monkeypatch, codex=0.3, outer=0.4, join=0.3)
    fallback_calls = _forbid_fallback(monkeypatch)
    bridge = Bridge(provider=_UnusedReasoningProvider())
    prepared = bridge.handle({"command": "diagnostic_prepare_workspace"})
    assert prepared["ok"] is True
    workspace_before = bridge._diagnostic.workspace
    run_root = workspace_before.run_root
    assert _oracle_absent(run_root)

    runner = _SlowRunner(delay_seconds=2.0)
    _patch_local_codex(monkeypatch, runner)

    outer_timeout_resp = bridge.handle({"command": "diagnostic_run_scoping"})
    assert outer_timeout_resp["ok"] is False
    assert outer_timeout_resp["error"]["code"] == "provider_error"
    assert bridge._diagnostic.phase == "workspace_ready"
    # The old thread has not actually exited yet (still sleeping well past
    # the outer+join bound), so it must be parked, not released.
    assert bridge._diagnostic._pending_run is not None
    assert _oracle_absent(run_root)
    assert fallback_calls == []

    # An explicit retry attempt while the old thread is still alive fails
    # closed instead of starting a second, concurrent attempt.
    blocked_retry = bridge.handle({"command": "diagnostic_run_scoping"})
    assert blocked_retry["ok"] is False
    assert blocked_retry["error"]["code"] == "validation_error"
    assert len(runner.calls) == 1  # no second Codex call was ever made
    assert bridge._diagnostic.workspace is workspace_before
    assert _oracle_absent(run_root)

    # Once the old runner actually finishes (well past its 2s delay), the
    # pending attempt's thread is confirmed dead.
    assert runner.finished.wait(timeout=10.0)
    pending = bridge._diagnostic._pending_run
    assert pending is not None
    pending.thread.join(timeout=5.0)
    assert not pending.thread.is_alive()

    # A fresh explicit retry -- a genuinely new attempt -- now succeeds in
    # reaching Codex again (this scripted attempt itself rejects, proving
    # the retry really ran, not that it silently reused any prior result).
    fresh_runner = _RejectingRunner()
    _patch_local_codex(monkeypatch, fresh_runner)
    final_attempt = bridge.handle({"command": "diagnostic_run_scoping"})
    assert final_attempt["ok"] is False
    assert final_attempt["error"]["code"] == "provider_error"
    assert bridge._diagnostic._pending_run is None
    assert len(fresh_runner.calls) == 1
    assert fallback_calls == []
    assert _oracle_absent(run_root)


def test_late_review_from_a_cancelled_attempt_never_reaches_new_attempt_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old, cancelled attempt's review callback is designed to fail
    closed as soon as it notices cancellation, even though it only reaches
    that check after the coordinator already gave up. This proves the old
    attempt's data never lands in `state` at all -- there is nothing to
    ignore because it was never delivered in the first place."""
    _set_fast_timeouts(monkeypatch, codex=0.3, outer=0.4, join=0.3)
    bridge = Bridge(provider=_UnusedReasoningProvider())
    bridge.handle({"command": "diagnostic_prepare_workspace"})

    slow_runner = _SlowRunner(delay_seconds=1.5)
    _patch_local_codex(monkeypatch, slow_runner)
    outer_timeout_resp = bridge.handle({"command": "diagnostic_run_scoping"})
    assert outer_timeout_resp["ok"] is False
    old_run = bridge._diagnostic._pending_run
    assert old_run is not None

    assert slow_runner.finished.wait(timeout=10.0)
    # Give the background thread a moment to reach its now-cancelled review
    # callback (it always fails closed there instead of publishing).
    old_run.thread.join(timeout=5.0)
    assert not old_run.thread.is_alive()
    assert bridge._diagnostic.scoping_result is None
    assert bridge._diagnostic.controller is None
    assert bridge._diagnostic.phase == "workspace_ready"


def test_diagnostic_reset_does_not_delete_the_temp_root_while_a_thread_is_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_fast_timeouts(monkeypatch, codex=0.3, outer=0.4, join=0.2)
    bridge = Bridge(provider=_UnusedReasoningProvider())
    bridge.handle({"command": "diagnostic_prepare_workspace"})
    run_root = bridge._diagnostic.workspace.run_root
    temp_root = bridge._diagnostic._temp_root

    slow_runner = _SlowRunner(delay_seconds=1.5)
    _patch_local_codex(monkeypatch, slow_runner)
    outer_timeout_resp = bridge.handle({"command": "diagnostic_run_scoping"})
    assert outer_timeout_resp["ok"] is False
    assert bridge._diagnostic._pending_run is not None

    reset_resp = bridge.handle({"command": "diagnostic_reset"})
    assert reset_resp["ok"] is True
    assert reset_resp["data"]["phase"] == "idle"
    # The old thread was still alive (well inside its 1.5s sleep) when reset
    # ran with only a 0.2s join bound: the temp root must survive.
    assert run_root.exists()
    assert temp_root.exists()

    assert slow_runner.finished.wait(timeout=10.0)


def test_each_scoping_attempt_uses_its_own_session_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fast_timeouts(monkeypatch)
    bridge = Bridge(provider=_UnusedReasoningProvider())
    bridge.handle({"command": "diagnostic_prepare_workspace"})
    temp_root = bridge._diagnostic._temp_root

    first_runner = _RejectingRunner()
    _patch_local_codex(monkeypatch, first_runner)
    bridge.handle({"command": "diagnostic_run_scoping"})
    first_attempt_id = bridge._diagnostic._attempt_counter
    first_session_store = temp_root / f"attempt-{first_attempt_id}" / diag_flow_module.CONTROLLER_STORE_FILENAME
    assert first_session_store.is_file()

    second_runner = _RejectingRunner()
    _patch_local_codex(monkeypatch, second_runner)
    bridge.handle({"command": "diagnostic_run_scoping"})
    second_attempt_id = bridge._diagnostic._attempt_counter
    second_session_store = temp_root / f"attempt-{second_attempt_id}" / diag_flow_module.CONTROLLER_STORE_FILENAME
    assert second_session_store.is_file()

    assert first_attempt_id != second_attempt_id
    assert first_session_store != second_session_store
    # Both attempt directories still exist independently -- neither was
    # ever overwritten or shared by the other.
    assert first_session_store.is_file()
    assert second_session_store.is_file()


def test_oracle_absent_throughout_a_rejected_attempt_and_a_successful_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from continuity_ai.unseen_workspace import generate_unseen_workspace, load_workspace

    _set_fast_timeouts(monkeypatch)
    bridge = Bridge(provider=_UnusedReasoningProvider())
    bridge.handle({"command": "diagnostic_prepare_workspace"})
    workspace = bridge._diagnostic.workspace
    run_root = workspace.run_root
    assert _oracle_absent(run_root)

    rejecting_runner = _RejectingRunner()
    _patch_local_codex(monkeypatch, rejecting_runner)
    first = bridge.handle({"command": "diagnostic_run_scoping"})
    assert first["ok"] is False
    assert _oracle_absent(run_root)

    scripted_evaluation_root = tmp_path / "scripted-evaluation"
    generated = generate_unseen_workspace(scripted_evaluation_root, workspace.seed)
    generated_input_root = Path(str(generated["input_root"])).resolve(strict=True)
    oracle_root = Path(str(generated["oracle_root"])).resolve(strict=True)

    def _oracle_statuses() -> dict[str, str]:
        payload = json.loads((oracle_root / "expected_scope.json").read_text(encoding="utf-8"))
        return {item["evidence_id"]: item["expected_status"] for item in payload["records"]}

    statuses = _oracle_statuses()
    ws = load_workspace(generated_input_root)
    decisions = []
    for record in ws.records:
        status = statuses[record.evidence_id]
        association = {"include": "included", "exclude": "excluded", "defer": "ambiguous"}[status]
        basis = {
            "included": "explicit_target",
            "excluded": "explicit_other_project",
            "ambiguous": "insufficient_context",
        }[association]
        decisions.append(
            {
                "evidence_id": record.evidence_id,
                "association_status": association,
                "basis": basis,
                "rationale": "Deterministic test response.",
                "span_ids": [f"{record.evidence_id}:L001"],
                "related_evidence_ids": [],
            }
        )
    classification = json.dumps(
        {
            "schema_version": "1.0",
            "target_project": ws.target_project.name,
            "anchor_evidence_ids": [d["evidence_id"] for d in decisions if d["basis"] == "explicit_target"],
            "decisions": decisions,
            "selected_evidence_ids": [d["evidence_id"] for d in decisions if d["association_status"] == "included"],
            "ambiguous_evidence_ids": [d["evidence_id"] for d in decisions if d["association_status"] == "ambiguous"],
            "excluded_evidence_ids": [d["evidence_id"] for d in decisions if d["association_status"] == "excluded"],
        }
    )

    @dataclass
    class _SucceedingRunner:
        calls: list[Any] = field(default_factory=list)

        def __call__(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
            self.calls.append((list(command), dict(options)))
            response_path = Path(command[command.index("--output-last-message") + 1])
            response_path.write_text(classification, encoding="utf-8")
            stdout = json.dumps({"type": "thread.started", "thread_id": THREAD_ID}) + "\n"
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    succeeding_runner = _SucceedingRunner()
    _patch_local_codex(monkeypatch, succeeding_runner)
    second = bridge.handle({"command": "diagnostic_run_scoping"})
    assert second["ok"] is True, second.get("error")
    assert bridge._diagnostic.phase == "awaiting_review"
    assert _oracle_absent(run_root)
