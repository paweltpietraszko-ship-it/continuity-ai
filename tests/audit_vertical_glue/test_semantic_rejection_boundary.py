"""Fix verification for VG-01: semantic Source Scoping rejection must fail
closed *before* the controller commits any success.

See `docs/audits/VERTICAL_GLUE_BOUNDED_REVIEW.md` (audit SHA
f8ec47acecdd01aa7e308c6ee1e4374afe5cbbf0) for the original bounded review that
found this blocker on `bddcc936af71a723793e185ad06499eef534f774`. That audit
commit was never cherry-picked or merged; this file is authored independently
against the fixed `codex_session.py` / `codex_source_scoping_provider.py`,
reproducing the same scenario the audit used (a controller-schema-valid
payload with a substituted `target_project`) and proving the fix instead of
the blocker.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import continuity_ai.integration.mixed_to_approved_pipeline as pipeline_module
from continuity_ai.codex_process import CodexCliCapabilities, CodexCliProcessAdapter
from continuity_ai.codex_session import (
    CodexOperationRequest,
    CodexSessionController,
    FailureCategory,
    JsonSessionStore,
    SessionPhase,
)
from continuity_ai.errors import ProviderError, ValidationError
from continuity_ai.evidence import build_spans
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.io import load_workspace
from continuity_ai.source_scoping.validator import validate_source_scoping_payload

THREAD_ID = "12345678-1234-5678-9234-567812345678"
FIXTURE = Path(__file__).parents[2] / "fixtures" / "source_scoping_mixed_workspace"


@dataclass
class OneResponseCodexRunner:
    response: str

    def __post_init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(
        self, command: list[str], **options: Any
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(options)))
        response_path = Path(command[command.index("--output-last-message") + 1])
        response_path.write_text(self.response, encoding="utf-8")
        stdout = json.dumps({"type": "thread.started", "thread_id": THREAD_ID}) + "\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def _controller(
    tmp_path: Path, runner: OneResponseCodexRunner
) -> tuple[CodexSessionController, JsonSessionStore]:
    adapter = CodexCliProcessAdapter(
        "codex",
        resolved_executable=Path(sys.executable),
        version="codex-cli test",
        capabilities=CodexCliCapabilities(
            True, True, True, True, True, resume_verified=True
        ),
        process_runner=runner,
    )
    store = JsonSessionStore(tmp_path / "sessions.json")
    return CodexSessionController(store, adapter), store


def test_vg01_semantically_substituted_target_project_fails_closed_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduce VG-01 exactly: schema-valid JSON with a substituted
    `target_project`. Before the fix, the controller committed a false
    success (phase=INVESTIGATING, successful receipt, retained Codex ID)
    before `validate_source_scoping_payload` ever ran downstream, stranding
    the session in an unretriable state. The fix routes the same canonical
    validator into the controller as a pre-commit gate."""
    target, evidence = load_workspace(FIXTURE)
    spans = build_spans(evidence)
    payload = FakeSourceScopingProvider().classify(target, evidence, spans)
    payload["target_project"] = "Semantically substituted project"

    # Confirm this is still the intended split: schema-valid, semantically invalid.
    with pytest.raises(ValidationError):
        validate_source_scoping_payload(payload, target, evidence, spans)

    runner = OneResponseCodexRunner(json.dumps(payload))
    controller, store = _controller(tmp_path, runner)
    downstream_calls: list[str] = []

    def forbidden(name: str):
        def call(*args: object, **kwargs: object) -> object:
            downstream_calls.append(name)
            raise AssertionError(f"downstream step ran after semantic rejection: {name}")

        return call

    monkeypatch.setattr(
        pipeline_module, "record_scope_awaiting_review", forbidden("human_review")
    )
    monkeypatch.setattr(pipeline_module, "approve_source_scope", forbidden("approval"))
    monkeypatch.setattr(
        pipeline_module, "materialize_approved_scope", forbidden("materialization")
    )
    monkeypatch.setattr(
        pipeline_module,
        "bind_and_report_on_approved_workspace",
        forbidden("reporting"),
    )
    destination = tmp_path / "approved"

    # The provider boundary now converts the controller's pre-commit rejection
    # into ProviderError, exactly as it already does for every other
    # controller-side failure (unavailable, workspace changed, ...); it never
    # reaches run_source_scoping's own downstream validate_source_scoping_payload call.
    with pytest.raises(ProviderError):
        pipeline_module.run_mixed_to_approved_pipeline(
            controller,
            FIXTURE,
            target,
            evidence,
            {},
            {},
            destination,
            CodexOperationRequest(
                "Report only approved evidence.",
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["report"],
                    "properties": {"report": {"type": "string", "minLength": 1}},
                },
                30,
            ),
        )

    assert len(runner.calls) == 1
    assert downstream_calls == []
    assert not destination.exists()

    document = json.loads(store.path.read_text(encoding="utf-8"))
    ((session_id, _persisted),) = document["sessions"].items()
    retained = controller.get_session(session_id)

    # The fix: rejection is a normal fail-closed failure, never a false success.
    assert retained.phase is SessionPhase.READY
    assert retained.codex_session_id is None
    assert retained.last_invocation_receipt is not None
    assert retained.last_invocation_receipt.succeeded is False
    assert (
        retained.last_invocation_receipt.failure_category
        is FailureCategory.INVALID_OUTPUT
    )
    assert retained.last_successful_invocation_receipt is None
    assert retained.codex_process_active is False
    assert retained.active_operation is None

    # The same controller session can now safely retry the investigation.
    retry_runner = OneResponseCodexRunner(
        json.dumps({"ok": True})
    )
    retry_adapter = CodexCliProcessAdapter(
        "codex",
        resolved_executable=Path(sys.executable),
        version="codex-cli test",
        capabilities=CodexCliCapabilities(
            True, True, True, True, True, resume_verified=True
        ),
        process_runner=retry_runner,
    )
    retry_controller = CodexSessionController(store, retry_adapter)
    retried = retry_controller.start_investigation(
        session_id,
        FIXTURE,
        CodexOperationRequest(
            "Retry with a corrected response.",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
            30,
        ),
    )
    assert retried.session.phase is SessionPhase.INVESTIGATING
    assert retried.session.codex_session_id == THREAD_ID
