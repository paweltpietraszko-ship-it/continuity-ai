"""Bounded audit probes for the mixed-to-approved vertical glue delta."""

from __future__ import annotations

import copy
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
    InvalidSessionState,
    JsonSessionStore,
    SessionPhase,
)
from continuity_ai.errors import ValidationError
from continuity_ai.evidence import build_spans
from continuity_ai.integration.codex_source_scoping_provider import _codex_schema
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.io import load_workspace
from continuity_ai.source_scoping.openai_provider import serialize_request_document
from continuity_ai.source_scoping.prompts import (
    SOURCE_SCOPING_PROMPT,
    source_scoping_response_schema,
)
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
        version="codex-cli audit",
        capabilities=CodexCliCapabilities(
            True, True, True, True, True, resume_verified=True
        ),
        process_runner=runner,
    )
    store = JsonSessionStore(tmp_path / "sessions.json")
    return CodexSessionController(store, adapter), store


def _request(target: str, evidence: tuple[Any, ...], spans: tuple[Any, ...]):
    document = serialize_request_document(target, evidence, spans)
    prompt = f"{SOURCE_SCOPING_PROMPT}\n\n{document}"
    return CodexOperationRequest(
        prompt, _codex_schema(source_scoping_response_schema()), 30
    )


def test_semantically_rejected_codex_payload_publishes_false_success_and_strands_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduce the blocker without changing the production transaction boundary.

    The returned object satisfies the controller's JSON schema, but substitutes
    the authoritative project identity and is therefore rejected by the Source
    Scoping validator after the controller has already committed success.
    """
    target, evidence = load_workspace(FIXTURE)
    spans = build_spans(evidence)
    payload = FakeSourceScopingProvider().classify(target, evidence, spans)
    payload["target_project"] = "Semantically substituted project"

    # Establish that this is the requested split: controller-schema-valid JSON,
    # but invalid under the canonical semantic validator.
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

    with pytest.raises(ValidationError):
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
    ((session_id, persisted),) = document["sessions"].items()
    retained = controller.get_session(session_id)

    # These assertions intentionally capture the current blocking behavior.
    assert retained.phase is SessionPhase.INVESTIGATING
    assert retained.last_invocation_receipt is not None
    assert retained.last_invocation_receipt.succeeded is True
    assert retained.last_successful_invocation_receipt is not None
    assert retained.last_successful_invocation_receipt.succeeded is True
    assert retained.codex_process_active is False
    assert retained.active_operation is None
    assert persisted["phase"] == "investigating"
    assert persisted["last_invocation_receipt"]["failure_category"] is None

    # The same controller session cannot safely retry the investigation.
    calls_before_retry = len(runner.calls)
    with pytest.raises(InvalidSessionState):
        controller.start_investigation(
            session_id, FIXTURE, _request(target, evidence, spans)
        )
    assert len(runner.calls) == calls_before_retry


def test_codex_schema_adaptation_preserves_input_and_only_removes_max_length() -> None:
    original = source_scoping_response_schema()
    before = copy.deepcopy(original)

    adapted = _codex_schema(original)

    assert original == before

    def strip_max_length(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: strip_max_length(child)
                for key, child in value.items()
                if key != "maxLength"
            }
        if isinstance(value, list):
            return [strip_max_length(child) for child in value]
        return value

    assert adapted == strip_max_length(before)
