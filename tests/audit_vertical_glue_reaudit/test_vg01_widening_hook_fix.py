"""Fix verification for the VG-01 re-audit finding: the semantic validator
hook must be rejection-only and must never widen the already JSON-Schema-
validated structured output.

See `docs/audits/VERTICAL_GLUE_VG01_REAUDIT.md` (re-audit SHA
16f3645b84efddde8bfce0952ea966d345a65236) for the bounded independent review
that found this remaining blocker on `fc7afe9c9517a963d48f846d5469aac06de3fe13`
(the first VG-01 fix, which correctly closed the exception-based rejection
path but still let a validator's *return value* replace the schema-valid
object without re-validating it). That re-audit commit was never
cherry-picked or merged; this file is authored independently against the
fixed `codex_session.py` / `codex_source_scoping_provider.py`, in which
`CodexOperationRequest.structured_output_validator` has contract
`Callable[[object], None] | None`: it must return exactly `None` to accept,
any other return value (or a raised exception) is `INVALID_OUTPUT`, it is
called on a deep copy of the structured output (so in-place mutation cannot
reach the published value), and the controller always publishes the
original, untouched, schema-valid object.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import continuity_ai.integration.codex_source_scoping_provider as provider_module
import continuity_ai.source_scoping.service as service_module
from continuity_ai.codex_process import CodexCliCapabilities, CodexCliProcessAdapter
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
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string", "minLength": 1}},
}
VALID_RESPONSE = json.dumps({"answer": "schema-valid"})


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
    tmp_path: Path, response: str = VALID_RESPONSE
) -> tuple[CodexSessionController, JsonSessionStore, OneResponseCodexRunner]:
    runner = OneResponseCodexRunner(response)
    adapter = CodexCliProcessAdapter(
        "codex",
        resolved_executable=Path(sys.executable),
        version="codex-cli reaudit-fix",
        capabilities=CodexCliCapabilities(
            True, True, True, True, True, resume_verified=True
        ),
        process_runner=runner,
    )
    store = JsonSessionStore(tmp_path / "sessions.json")
    return CodexSessionController(store, adapter), store, runner


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "source.txt").write_text("reaudit input", encoding="utf-8")
    return root.resolve()


def _request(validator=None) -> CodexOperationRequest:
    return CodexOperationRequest(
        "Inspect the bounded input.", SCHEMA, 30, structured_output_validator=validator
    )


def test_validator_returning_schema_invalid_value_is_rejected(tmp_path: Path) -> None:
    """The former blocker: a validator return value that does not even match
    the original JSON Schema (`answer` must be a non-empty string) must not
    be published as a successful result."""
    controller, store, _ = _controller(tmp_path)
    root = _workspace(tmp_path)
    created = controller.create_session(root)

    def widen_to_schema_invalid(_value: object) -> object:
        return {"answer": 7}

    with pytest.raises(InvalidCodexOutput) as captured:
        controller.start_investigation(
            created.controller_session_id, root, _request(widen_to_schema_invalid)
        )

    receipt = captured.value.receipt
    assert receipt is not None
    assert receipt.succeeded is False
    assert receipt.failure_category is FailureCategory.INVALID_OUTPUT
    retained = store.load(created.controller_session_id)
    assert retained.phase is SessionPhase.READY
    assert retained.codex_session_id is None
    assert retained.last_successful_invocation_receipt is None
    assert retained.codex_process_active is False
    assert retained.active_operation is None


def test_validator_returning_original_payload_instead_of_none_is_rejected(
    tmp_path: Path,
) -> None:
    """Even returning the exact, unmodified, schema-valid object is a
    contract violation: the hook must return `None` to accept."""
    controller, store, _ = _controller(tmp_path)
    root = _workspace(tmp_path)
    created = controller.create_session(root)

    def return_original(value: object) -> object:
        return value

    with pytest.raises(InvalidCodexOutput) as captured:
        controller.start_investigation(
            created.controller_session_id, root, _request(return_original)
        )

    assert captured.value.receipt.failure_category is FailureCategory.INVALID_OUTPUT
    retained = store.load(created.controller_session_id)
    assert retained.phase is SessionPhase.READY
    assert retained.codex_session_id is None
    assert retained.last_successful_invocation_receipt is None


def test_validator_returning_none_commits_original_schema_valid_object(
    tmp_path: Path,
) -> None:
    controller, store, _ = _controller(tmp_path)
    root = _workspace(tmp_path)
    created = controller.create_session(root)
    calls: list[object] = []

    def accept(value: object) -> None:
        calls.append(value)

    result = controller.start_investigation(
        created.controller_session_id, root, _request(accept)
    )

    assert calls == [{"answer": "schema-valid"}]
    assert result.structured_output == {"answer": "schema-valid"}
    assert result.receipt.succeeded is True
    assert result.receipt.structured_output_valid is True
    assert result.session.phase is SessionPhase.INVESTIGATING
    assert result.session.codex_session_id == THREAD_ID
    retained = store.load(created.controller_session_id)
    assert retained.last_successful_invocation_receipt == result.receipt


def test_validator_in_place_mutation_never_reaches_the_published_result(
    tmp_path: Path,
) -> None:
    """The hook receives a deep copy: mutating it in place must never alter
    the object the controller publishes as `structured_output`."""
    controller, store, _ = _controller(tmp_path)
    root = _workspace(tmp_path)
    created = controller.create_session(root)

    def mutate_in_place(value: object) -> None:
        assert isinstance(value, dict)
        value["answer"] = "mutated-by-validator"
        value["extra_key_injected_by_validator"] = True

    result = controller.start_investigation(
        created.controller_session_id, root, _request(mutate_in_place)
    )

    assert result.structured_output == {"answer": "schema-valid"}
    assert "extra_key_injected_by_validator" not in result.structured_output
    assert result.receipt.succeeded is True
    retained = store.load(created.controller_session_id)
    assert retained.last_successful_invocation_receipt == result.receipt


def test_source_scoping_runs_controller_gate_and_second_canonical_validation_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`CodexSourceScopingProvider` must call the canonical validator as a
    rejection-only controller gate, and `run_source_scoping` must
    independently call it again afterward (defense in depth) — the validator
    logic itself is never moved into the controller."""
    target, evidence = load_workspace(FIXTURE)
    spans = build_spans(evidence)
    payload = FakeSourceScopingProvider().classify(target, evidence, spans)
    controller, _store, _runner = _controller(tmp_path, json.dumps(payload))
    created = controller.create_session(FIXTURE)
    provider = CodexSourceScopingProvider(
        controller, created.controller_session_id, FIXTURE, timeout_seconds=30
    )
    calls: list[str] = []

    def controller_pass(*args: object, **kwargs: object) -> object:
        calls.append("controller")
        return validate_source_scoping_payload(*args, **kwargs)

    def service_pass(*args: object, **kwargs: object) -> object:
        calls.append("service")
        return validate_source_scoping_payload(*args, **kwargs)

    monkeypatch.setattr(
        provider_module, "validate_source_scoping_payload", controller_pass
    )
    monkeypatch.setattr(service_module, "validate_source_scoping_payload", service_pass)

    result = service_module.run_source_scoping(target, evidence, spans, provider)

    assert result.target_project == target
    assert calls == ["controller", "service"]
