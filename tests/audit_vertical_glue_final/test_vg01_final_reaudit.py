"""Independent final delta re-audit evidence for the VG-01 repair.

The tests exercise the production controller boundary through a scripted Codex
process adapter.  They intentionally do not import or reuse either earlier
audit test suite.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

import continuity_ai.codex_session as codex_session_module
import continuity_ai.integration.codex_source_scoping_provider as provider_module
import continuity_ai.source_scoping.service as service_module
from continuity_ai.codex_process import (
    CodexCliCapabilities,
    CodexCliProcessAdapter,
    workspace_fingerprint,
)
from continuity_ai.codex_session import (
    CodexOperationRequest,
    CodexSessionController,
    FailureCategory,
    InvalidCodexOutput,
    JsonSessionStore,
    SessionPhase,
)
from continuity_ai.evidence import build_spans
from continuity_ai.integration.codex_source_scoping_provider import (
    CodexSourceScopingProvider,
)
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.io import load_workspace
from continuity_ai.source_scoping.validator import validate_source_scoping_payload


THREAD_ID = "12345678-1234-5678-9234-567812345678"
FIXTURE = Path(__file__).parents[2] / "fixtures" / "source_scoping_mixed_workspace"
NESTED_PAYLOAD = {
    "answer": "schema-valid",
    "details": {
        "tags": ["first", "second"],
        "metadata": {"owner": "original-owner"},
    },
}
NESTED_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "details"],
    "properties": {
        "answer": {"type": "string", "minLength": 1},
        "details": {
            "type": "object",
            "additionalProperties": False,
            "required": ["tags", "metadata"],
            "properties": {
                "tags": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "metadata": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["owner"],
                    "properties": {
                        "owner": {"type": "string", "minLength": 1}
                    },
                },
            },
        },
    },
}


@dataclass
class ScriptedRunner:
    responses: list[str]
    thread_ids: list[str | None]

    def __post_init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(
        self, command: list[str], **options: Any
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(options)))
        index = len(self.calls) - 1
        response = self.responses[min(index, len(self.responses) - 1)]
        thread_id = self.thread_ids[min(index, len(self.thread_ids) - 1)]
        response_path = Path(command[command.index("--output-last-message") + 1])
        response_path.write_text(response, encoding="utf-8")
        stdout = (
            ""
            if thread_id is None
            else json.dumps({"type": "thread.started", "thread_id": thread_id})
            + "\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def _controller(
    tmp_path: Path,
    responses: list[dict[str, object]] | None = None,
    thread_ids: list[str | None] | None = None,
) -> tuple[CodexSessionController, JsonSessionStore, ScriptedRunner]:
    selected_responses = responses or [NESTED_PAYLOAD]
    runner = ScriptedRunner(
        [json.dumps(response) for response in selected_responses],
        thread_ids or [THREAD_ID] * len(selected_responses),
    )
    adapter = CodexCliProcessAdapter(
        "codex",
        resolved_executable=Path(sys.executable),
        version="codex-cli final-reaudit",
        capabilities=CodexCliCapabilities(
            True, True, True, True, True, resume_verified=True
        ),
        process_runner=runner,
    )
    store = JsonSessionStore(tmp_path / "sessions.json")
    return CodexSessionController(store, adapter), store, runner


def _workspace(tmp_path: Path, name: str = "workspace") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "source.txt").write_text("final re-audit input", encoding="utf-8")
    return root.resolve()


def _request(
    validator: Callable[[object], object] | None = None,
) -> CodexOperationRequest:
    return CodexOperationRequest(
        "Inspect only the bounded workspace.",
        NESTED_SCHEMA,
        30,
        structured_output_validator=validator,
    )


def _assert_invalid_output_state(
    error: InvalidCodexOutput,
    store: JsonSessionStore,
    controller_session_id: str,
) -> None:
    receipt = error.receipt
    assert receipt is not None
    assert receipt.failure_category is FailureCategory.INVALID_OUTPUT
    assert receipt.structured_output_valid is False
    assert receipt.succeeded is False
    retained = store.load(controller_session_id)
    assert retained.phase is SessionPhase.READY
    assert retained.codex_session_id is None
    assert retained.last_successful_invocation_receipt is None
    assert retained.last_invocation_receipt == receipt
    assert retained.codex_process_active is False
    assert retained.active_operation is None


def test_none_acceptance_gets_deep_copy_and_publishes_exact_schema_validated_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nested mutation, deletion, and addition cannot affect publication."""
    controller, store, _runner = _controller(tmp_path)
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    schema_validated: list[object] = []
    real_validated_output = codex_session_module._validated_output

    def capture_schema_validated(
        final_response: str, schema: dict[str, object]
    ) -> object:
        value = real_validated_output(final_response, schema)
        schema_validated.append(value)
        return value

    monkeypatch.setattr(
        codex_session_module, "_validated_output", capture_schema_validated
    )

    validator_arguments: list[object] = []

    def mutate_copy(value: object) -> None:
        validator_arguments.append(value)
        assert isinstance(value, dict)
        assert value is not schema_validated[0]
        assert value["details"] is not schema_validated[0]["details"]
        details = value["details"]
        assert isinstance(details, dict)
        assert details["tags"] is not schema_validated[0]["details"]["tags"]
        assert details["metadata"] is not schema_validated[0]["details"]["metadata"]
        tags = details["tags"]
        metadata = details["metadata"]
        assert isinstance(tags, list)
        assert isinstance(metadata, dict)
        tags[0] = "validator-mutated"
        tags.append("validator-added")
        del metadata["owner"]
        metadata["injected"] = "validator-added"
        value["extra"] = {"nested": ["validator-added"]}
        return None

    result = controller.start_investigation(
        created.controller_session_id, root, _request(mutate_copy)
    )

    assert len(validator_arguments) == 1
    assert len(schema_validated) == 1
    assert result.structured_output is schema_validated[0]
    assert result.structured_output == NESTED_PAYLOAD
    assert result.receipt.succeeded is True
    assert result.receipt.structured_output_valid is True
    assert result.session.phase is SessionPhase.INVESTIGATING
    assert result.session.codex_session_id == THREAD_ID
    assert store.load(created.controller_session_id).last_successful_invocation_receipt == (
        result.receipt
    )


@pytest.mark.parametrize(
    "returned",
    [False, 0, "", [], {}],
    ids=["false", "zero", "empty-string", "empty-list", "empty-dict"],
)
def test_every_false_like_non_none_return_is_invalid_output(
    tmp_path: Path, returned: object
) -> None:
    controller, store, _runner = _controller(tmp_path)
    root = _workspace(tmp_path)
    created = controller.create_session(root)

    with pytest.raises(InvalidCodexOutput) as captured:
        controller.start_investigation(
            created.controller_session_id,
            root,
            _request(lambda _value: returned),
        )

    _assert_invalid_output_state(
        captured.value, store, created.controller_session_id
    )


def test_returning_validator_argument_instead_of_none_is_invalid_output(
    tmp_path: Path,
) -> None:
    controller, store, _runner = _controller(tmp_path)
    root = _workspace(tmp_path)
    created = controller.create_session(root)

    with pytest.raises(InvalidCodexOutput) as captured:
        controller.start_investigation(
            created.controller_session_id, root, _request(lambda value: value)
        )

    _assert_invalid_output_state(
        captured.value, store, created.controller_session_id
    )


def test_returning_different_but_schema_valid_object_is_invalid_output(
    tmp_path: Path,
) -> None:
    controller, store, _runner = _controller(tmp_path)
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    replacement = {
        "answer": "different-but-schema-valid",
        "details": {"tags": ["replacement"], "metadata": {"owner": "other"}},
    }

    with pytest.raises(InvalidCodexOutput) as captured:
        controller.start_investigation(
            created.controller_session_id,
            root,
            _request(lambda _value: replacement),
        )

    _assert_invalid_output_state(
        captured.value, store, created.controller_session_id
    )


def test_validator_exception_is_severed_from_every_retained_surface_and_retry_works(
    tmp_path: Path,
) -> None:
    secret = "validator-private-evidence-7f9c"
    controller, store, _runner = _controller(
        tmp_path, responses=[NESTED_PAYLOAD, NESTED_PAYLOAD]
    )
    root = _workspace(tmp_path)
    created = controller.create_session(root)

    def reject(_value: object) -> None:
        raise ValueError(secret, {"nested-secret": [secret]})

    with pytest.raises(InvalidCodexOutput) as captured:
        controller.start_investigation(
            created.controller_session_id, root, _request(reject)
        )

    error = captured.value
    _assert_invalid_output_state(error, store, created.controller_session_id)
    retained = store.load(created.controller_session_id)
    persisted = store.path.read_text(encoding="utf-8")
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.args == (
        "Codex operation failed closed with invalid_codex_output.",
    )
    assert secret not in repr(error.args)
    assert secret not in repr(error.receipt)
    assert secret not in repr(retained)
    assert secret not in persisted

    retried = controller.start_investigation(
        created.controller_session_id, root, _request()
    )
    assert retried.receipt.succeeded is True
    assert retried.session.phase is SessionPhase.INVESTIGATING
    assert retried.session.codex_session_id == THREAD_ID


def test_later_non_none_rejection_preserves_prior_success_and_same_session_retry(
    tmp_path: Path,
) -> None:
    controller, store, runner = _controller(
        tmp_path,
        responses=[NESTED_PAYLOAD, NESTED_PAYLOAD, NESTED_PAYLOAD],
        thread_ids=[THREAD_ID, THREAD_ID, THREAD_ID],
    )
    mixed = _workspace(tmp_path, "mixed")
    created = controller.create_session(mixed)
    investigated = controller.start_investigation(
        created.controller_session_id, mixed, _request()
    )
    prior_success = investigated.receipt
    waiting = controller.record_awaiting_human_review(created.controller_session_id)
    approved = _workspace(tmp_path, "approved")
    bound = controller.bind_approved_workspace(
        waiting.controller_session_id,
        approved,
        workspace_fingerprint(approved),
    )

    with pytest.raises(InvalidCodexOutput) as captured:
        controller.start_reporting(
            bound.controller_session_id,
            approved,
            _request(lambda _value: {"schema": "validity is irrelevant"}),
        )

    receipt = captured.value.receipt
    assert receipt is not None
    assert receipt.failure_category is FailureCategory.INVALID_OUTPUT
    assert receipt.succeeded is False
    rejected = store.load(bound.controller_session_id)
    assert rejected.phase is SessionPhase.APPROVED
    assert rejected.codex_session_id == THREAD_ID
    assert rejected.last_successful_invocation_receipt == prior_success
    assert rejected.last_invocation_receipt == receipt
    assert rejected.codex_process_active is False
    assert rejected.active_operation is None

    retried = controller.start_reporting(
        bound.controller_session_id, approved, _request()
    )
    assert retried.receipt.succeeded is True
    assert retried.receipt.resume_attempted is True
    assert retried.receipt.codex_session_id == THREAD_ID
    assert retried.session.phase is SessionPhase.REPORTING
    assert retried.session.codex_session_id == THREAD_ID
    assert "resume" in runner.calls[-1][0]
    assert THREAD_ID in runner.calls[-1][0]


def test_json_schema_rejection_happens_before_runtime_validator(
    tmp_path: Path,
) -> None:
    controller, store, _runner = _controller(
        tmp_path, responses=[{"answer": 7}]
    )
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    calls: list[object] = []

    def forbidden(value: object) -> None:
        calls.append(value)
        raise AssertionError("runtime validator ran after schema rejection")

    with pytest.raises(InvalidCodexOutput) as captured:
        controller.start_investigation(
            created.controller_session_id, root, _request(forbidden)
        )

    assert calls == []
    _assert_invalid_output_state(
        captured.value, store, created.controller_session_id
    )


def test_source_scoping_keeps_two_independent_canonical_validation_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, evidence = load_workspace(FIXTURE)
    spans = build_spans(evidence)
    payload = FakeSourceScopingProvider().classify(target, evidence, spans)
    controller, _store, _runner = _controller(tmp_path, responses=[payload])
    created = controller.create_session(FIXTURE)
    provider = CodexSourceScopingProvider(
        controller, created.controller_session_id, FIXTURE, timeout_seconds=30
    )
    calls: list[tuple[str, int]] = []

    def controller_pass(*args: object, **kwargs: object) -> object:
        calls.append(("controller", id(args[0])))
        return validate_source_scoping_payload(*args, **kwargs)

    def service_pass(*args: object, **kwargs: object) -> object:
        calls.append(("service", id(args[0])))
        return validate_source_scoping_payload(*args, **kwargs)

    monkeypatch.setattr(
        provider_module, "validate_source_scoping_payload", controller_pass
    )
    monkeypatch.setattr(service_module, "validate_source_scoping_payload", service_pass)

    result = service_module.run_source_scoping(target, evidence, spans, provider)

    assert result.target_project == target
    assert [name for name, _identity in calls] == ["controller", "service"]
    assert calls[0][1] != calls[1][1]
