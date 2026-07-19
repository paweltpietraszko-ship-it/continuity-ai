"""Proof that Bridge, in production mode (no injected test provider), wires
the real Codex vertical flow: mixed workspace -> real Codex Source Scoping
investigation -> AWAITING_HUMAN_REVIEW -> human overrides -> approved-only
materialization -> bind -> same-session report resume.

All Codex CLI calls here are driven by a scripted fake process runner (no
live network); see `tests/integration/test_mixed_to_approved_vertical_flow.py`
and `tests/test_codex_session_live.py` for the corresponding real-Codex
proof.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import continuity_ai.integration.bridge_vertical_flow as vertical_module
from continuity_ai.aurora_fixture import generate_project_aurora_fixture
from continuity_ai.bridge import Bridge
from continuity_ai.codex_process import CodexCliCapabilities, CodexCliProcessAdapter
from continuity_ai.codex_session import CodexSessionController, JsonSessionStore
from continuity_ai.evidence import artifact_to_reasoning, build_spans, order_evidence
from continuity_ai.ingestion import ingest_artifacts
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.io import load_workspace
from continuity_ai.source_scoping.review import approve_source_scope
from continuity_ai.source_scoping.service import run_source_scoping

THREAD_ID = "12345678-1234-5678-9234-567812345678"
PASSWORD = "correct horse battery staple"


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
            else json.dumps({"type": "thread.started", "thread_id": thread_id}) + "\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def _patch_local_codex(monkeypatch: pytest.MonkeyPatch, runner: ScriptedRunner) -> None:
    """Bridge's production path calls `CodexSessionController.with_local_codex`
    directly; substitute the process runner without requiring a real
    installed Codex CLI, matching the pattern used across this test suite."""

    def fake_with_local_codex(store, **_kwargs: Any) -> CodexSessionController:
        adapter = CodexCliProcessAdapter(
            "codex",
            resolved_executable=Path(sys.executable),
            version="codex-cli test",
            capabilities=CodexCliCapabilities(
                True, True, True, True, True, resume_verified=True
            ),
            process_runner=runner,
        )
        return CodexSessionController(store, adapter)

    monkeypatch.setattr(
        vertical_module.CodexSessionController,
        "with_local_codex",
        classmethod(lambda cls, store, **kw: fake_with_local_codex(store, **kw)),
    )


def _project(tmp_path: Path):
    generate_project_aurora_fixture(tmp_path)
    artifact_root = (tmp_path / "fixtures/project_aurora/generated/artifacts").resolve()
    records = order_evidence(
        tuple(artifact_to_reasoning(r) for r in ingest_artifacts(artifact_root))
    )
    return artifact_root, records


def _classification_response(target: str, records) -> str:
    spans = build_spans(records)
    return json.dumps(FakeSourceScopingProvider().classify(target, records, spans))


class _UnusedReasoningProvider:
    """Placeholder so `Bridge()` does not need `CONTINUITY_REASONING_PROVIDER`
    set; the real Codex vertical flow never consults this provider."""

    provider_id = "unused-in-real-vertical-flow"

    def analyze(self, evidence, spans, question):
        raise AssertionError("local reasoning provider invoked during Codex-resumed reporting")


def _init_bridge_and_load(tmp_path: Path):
    bridge = Bridge(provider=_UnusedReasoningProvider())
    vault_path = tmp_path / "vault.bin"
    bridge.handle(
        {
            "command": "initialize_vault",
            "path": str(vault_path),
            "password": PASSWORD,
            "owner_name": "Paweł",
        }
    )
    artifact_root, records = _project(tmp_path)
    load_resp = bridge.handle(
        {"command": "load_project", "artifact_root": str(artifact_root)}
    )
    assert load_resp["ok"] is True
    return bridge, artifact_root, records


def test_bridge_full_flow_uses_same_codex_session_and_excludes_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge, artifact_root, records = _init_bridge_and_load(tmp_path)
    target = bridge.project
    classification = _classification_response(target, records)
    # Exactly one exclusion, forced by explicit human override regardless of
    # the model's own classification, so the approved set is deterministic:
    # every record except the first.
    excluded_id = records[0].evidence_id
    approved_records = tuple(r for r in records if r.evidence_id != excluded_id)
    approved_spans = build_spans(approved_records)
    report_response = json.dumps(
        {
            "schema_version": "3.0",
            "analysis_status": "no_material_break_found",
            "continuity_break_kind": None,
            "current_state": {
                "statement": "All approved evidence is grounded.",
                "span_ids": [approved_spans[0].span_id],
            },
            "semantic_annotations": [
                {"evidence_id": r.evidence_id, "propagation_role": "none", "context_tags": []}
                for r in approved_records
            ],
            "continuity_break": None,
            "next_action": None,
            "project_report": {
                "summary": {
                    "statement": "Nothing material changed.",
                    "span_ids": [approved_spans[0].span_id],
                },
                "sections": [
                    {
                        "key": key,
                        "status": "evidence_gap",
                        "headline": "No verified status available",
                        "detail": f"No available project source establishes the current {key} status.",
                        "span_ids": [],
                    }
                    for key in (
                        "decision", "budget", "schedule", "operations",
                        "readiness", "casting", "agreements",
                    )
                ],
            },
        }
    )
    runner = ScriptedRunner([classification, report_response], [THREAD_ID, THREAD_ID])
    _patch_local_codex(monkeypatch, runner)

    scoped = bridge.handle({"command": "scope_project_sources"})
    assert scoped["ok"] is True
    assert bridge._vertical.controller_session_id is not None
    assert bridge._vertical.controller.get_session(
        bridge._vertical.controller_session_id
    ).codex_session_id == THREAD_ID

    excluded_record = records[0]
    overrides = {r.evidence_id: "included" for r in records}
    overrides[excluded_id] = "excluded"

    confirmed = bridge.handle(
        {"command": "confirm_source_scope", "overrides": overrides}
    )
    assert confirmed["ok"] is True
    approved_ids = confirmed["data"]["approved_source_scope"]["approved_evidence_ids"]
    assert excluded_id not in approved_ids
    assert bridge._vertical.approved_workspace_root is not None
    assert not (bridge._vertical.approved_workspace_root / excluded_record.uri).exists()
    for evidence_id in approved_ids:
        record = next(r for r in records if r.evidence_id == evidence_id)
        assert (bridge._vertical.approved_workspace_root / record.uri).is_file()

    analyzed = bridge.handle(
        {"command": "analyze_project", "question": "What is the current state?"}
    )
    assert analyzed["ok"] is True
    assert analyzed["data"]["analysis_status"] == "no_material_break_found"

    retained = bridge._vertical.controller.get_session(bridge._vertical.controller_session_id)
    assert retained.codex_session_id == THREAD_ID
    assert retained.last_successful_invocation_receipt.resume_attempted is True
    assert retained.last_successful_invocation_receipt.new_codex_session_created is False

    investigation_command = runner.calls[0][0]
    reporting_command = runner.calls[1][0]
    assert "resume" not in investigation_command
    assert "resume" in reporting_command
    assert THREAD_ID in reporting_command


def test_bridge_analyze_project_blocked_before_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge, artifact_root, records = _init_bridge_and_load(tmp_path)
    classification = _classification_response(bridge.project, records)
    runner = ScriptedRunner([classification], [THREAD_ID])
    _patch_local_codex(monkeypatch, runner)

    scoped = bridge.handle({"command": "scope_project_sources"})
    assert scoped["ok"] is True

    blocked = bridge.handle(
        {"command": "analyze_project", "question": "Current state?"}
    )
    assert blocked["ok"] is False
    assert blocked["error"]["code"] == "validation_error"
    assert len(runner.calls) == 1


def test_bridge_no_fallback_provider_on_codex_investigation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import continuity_ai.openai_provider as provider_module
    import continuity_ai.deterministic_offline_provider as offline_module

    fallback_calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> object:
        fallback_calls.append("fallback")
        raise AssertionError("provider fallback invoked")

    monkeypatch.setattr(provider_module, "OpenAIReasoningProvider", forbidden)
    monkeypatch.setattr(offline_module, "DeterministicOfflineReasoningProvider", forbidden)

    bridge, artifact_root, records = _init_bridge_and_load(tmp_path)
    runner = ScriptedRunner(
        [json.dumps({"not": "the expected source scoping shape"})], [None]
    )
    _patch_local_codex(monkeypatch, runner)

    response = bridge.handle({"command": "scope_project_sources"})

    assert response["ok"] is False
    assert fallback_calls == []


def test_bridge_investigation_retry_after_fail_closed_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge, artifact_root, records = _init_bridge_and_load(tmp_path)
    spans = build_spans(records)
    bad_payload = FakeSourceScopingProvider().classify(bridge.project, records, spans)
    bad_payload["target_project"] = "Semantically substituted project"
    good_payload = FakeSourceScopingProvider().classify(bridge.project, records, spans)
    runner = ScriptedRunner(
        [json.dumps(bad_payload), json.dumps(good_payload)],
        [THREAD_ID, THREAD_ID],
    )
    _patch_local_codex(monkeypatch, runner)

    first = bridge.handle({"command": "scope_project_sources"})
    assert first["ok"] is False
    # CodexSourceScopingProvider.classify() converts every controller-side
    # failure (including this pre-commit semantic rejection) to ProviderError,
    # exactly like it already does for unavailable/workspace-changed/etc.
    assert first["error"]["code"] == "provider_error"
    assert "Semantically substituted" not in json.dumps(first)

    second = bridge.handle({"command": "scope_project_sources"})
    assert second["ok"] is True
    assert len(runner.calls) == 2


def test_bridge_errors_never_leak_internal_names_or_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge, artifact_root, records = _init_bridge_and_load(tmp_path)
    secret = "TOP-SECRET-EVIDENCE-CONTENT"
    runner = ScriptedRunner([json.dumps({"boom": secret})], [None])
    _patch_local_codex(monkeypatch, runner)

    response = bridge.handle({"command": "scope_project_sources"})

    assert response["ok"] is False
    assert set(response["error"].keys()) == {"code", "message", "object_id"}
    body = json.dumps(response, ensure_ascii=False)
    assert secret not in body
    assert "Traceback" not in body
    assert "CodexSessionController" not in body


def test_workspace_identity_recognizes_equivalent_windows_path_spellings(
    tmp_path: Path,
) -> None:
    """Path identity for the same on-disk workspace must be recognized
    regardless of separator spelling (`/` vs `\\`), without weakening the
    underlying identity check: `Path.resolve()` is the authoritative,
    filesystem-verified identity, not a string heuristic."""
    root = tmp_path / "mixed"
    root.mkdir()
    (root / "source.txt").write_text("content", encoding="utf-8")
    native = root.resolve()
    forward_slash_spelling = Path(str(native).replace("\\", "/"))

    assert forward_slash_spelling.resolve() == native
    assert str(forward_slash_spelling.resolve()) == str(native)

    store = JsonSessionStore(tmp_path / "sessions.json")
    from continuity_ai.codex_process import (
        CodexCliCapabilities as _Caps,
        CodexCliProcessAdapter as _Adapter,
    )

    class _NullRunner:
        def __call__(self, command, **options):
            response_path = Path(command[command.index("--output-last-message") + 1])
            response_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    adapter = _Adapter(
        "codex",
        resolved_executable=Path(sys.executable),
        version="codex-cli test",
        capabilities=_Caps(True, True, True, True, True, resume_verified=True),
        process_runner=_NullRunner(),
    )
    controller = CodexSessionController(store, adapter)
    created = controller.create_session(native)

    from continuity_ai.codex_session import CodexOperationRequest

    result = controller.start_investigation(
        created.controller_session_id,
        forward_slash_spelling,
        CodexOperationRequest(
            "q",
            {"type": "object", "additionalProperties": False, "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
            5,
        ),
    )
    assert result.receipt.succeeded is True


def _report_response(approved_records) -> str:
    spans = build_spans(approved_records)
    return json.dumps(
        {
            "schema_version": "3.0",
            "analysis_status": "no_material_break_found",
            "continuity_break_kind": None,
            "current_state": {
                "statement": "All approved evidence is grounded.",
                "span_ids": [spans[0].span_id],
            },
            "semantic_annotations": [
                {"evidence_id": r.evidence_id, "propagation_role": "none", "context_tags": []}
                for r in approved_records
            ],
            "continuity_break": None,
            "next_action": None,
            "project_report": {
                "summary": {
                    "statement": "Nothing material changed.",
                    "span_ids": [spans[0].span_id],
                },
                "sections": [
                    {
                        "key": key,
                        "status": "evidence_gap",
                        "headline": "No verified status available",
                        "detail": f"No available project source establishes the current {key} status.",
                        "span_ids": [],
                    }
                    for key in (
                        "decision", "budget", "schedule", "operations",
                        "readiness", "casting", "agreements",
                    )
                ],
            },
        }
    )


def _run_real_flow_to_reporting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Shared setup for the run_identity proofs: real production Bridge,
    scripted Codex CLI, one deterministic exclusion, all the way through a
    successful analyze_project."""
    bridge, artifact_root, records = _init_bridge_and_load(tmp_path)
    target = bridge.project
    classification = _classification_response(target, records)
    excluded_id = records[0].evidence_id
    approved_records = tuple(r for r in records if r.evidence_id != excluded_id)
    runner = ScriptedRunner(
        [classification, _report_response(approved_records)], [THREAD_ID, THREAD_ID]
    )
    _patch_local_codex(monkeypatch, runner)

    scoped = bridge.handle({"command": "scope_project_sources"})
    assert scoped["ok"] is True

    overrides = {r.evidence_id: "included" for r in records}
    overrides[excluded_id] = "excluded"
    confirmed = bridge.handle({"command": "confirm_source_scope", "overrides": overrides})
    assert confirmed["ok"] is True

    analyzed = bridge.handle(
        {"command": "analyze_project", "question": "What is the current state?"}
    )
    assert analyzed["ok"] is True

    return bridge, scoped, confirmed, analyzed


def test_run_identity_codex_session_id_matches_between_investigation_and_reporting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge, scoped, confirmed, analyzed = _run_real_flow_to_reporting(tmp_path, monkeypatch)

    investigation_identity = scoped["data"]["run_identity"]
    reporting_identity = analyzed["data"]["run_identity"]

    assert investigation_identity["codex_session_id"] == THREAD_ID
    assert reporting_identity["codex_session_id"] == THREAD_ID
    assert investigation_identity["codex_session_id"] == reporting_identity["codex_session_id"]
    assert investigation_identity["controller_session_id"] == reporting_identity["controller_session_id"]

    # Not yet claimed as a resumed report right after investigation...
    assert investigation_identity["reporting_resumed_retained_session"] is False
    # ...but true once reporting has actually resumed that same session.
    assert reporting_identity["reporting_resumed_retained_session"] is True

    # Confirmation response also carries the identity (approval/reporting phase).
    confirmation_identity = confirmed["data"]["run_identity"]
    assert confirmation_identity["codex_session_id"] == THREAD_ID


def test_run_identity_approved_fingerprint_differs_from_mixed_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, scoped, confirmed, analyzed = _run_real_flow_to_reporting(tmp_path, monkeypatch)

    mixed_fingerprint = scoped["data"]["run_identity"]["mixed_workspace_fingerprint"]
    assert scoped["data"]["run_identity"]["approved_workspace_fingerprint"] is None
    # Binding happens during confirm_source_scope itself, so the approved
    # fingerprint is already present in that response, before reporting runs.
    approved_fingerprint = confirmed["data"]["run_identity"]["approved_workspace_fingerprint"]
    assert analyzed["data"]["run_identity"]["approved_workspace_fingerprint"] == approved_fingerprint

    assert isinstance(mixed_fingerprint, str) and len(mixed_fingerprint) == 64
    assert isinstance(approved_fingerprint, str) and len(approved_fingerprint) == 64
    assert approved_fingerprint != mixed_fingerprint
    # Mixed workspace fingerprint is stable across the whole flow (unchanged).
    assert analyzed["data"]["run_identity"]["mixed_workspace_fingerprint"] == mixed_fingerprint


def test_run_identity_is_sourced_from_controller_runtime_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The metadata must be a read of the controller's own retained session,
    not something computed independently by the response-building code."""
    bridge, scoped, confirmed, analyzed = _run_real_flow_to_reporting(tmp_path, monkeypatch)

    controller_session = bridge._vertical.controller.get_session(
        bridge._vertical.controller_session_id
    )
    identity = analyzed["data"]["run_identity"]

    assert identity["controller_session_id"] == controller_session.controller_session_id
    assert identity["codex_session_id"] == controller_session.codex_session_id
    assert identity["mixed_workspace_fingerprint"] == controller_session.workspace_fingerprint
    assert (
        identity["approved_workspace_fingerprint"]
        == controller_session.approved_workspace_fingerprint
    )
    receipt = controller_session.last_successful_invocation_receipt
    assert identity["reporting_resumed_retained_session"] == (
        receipt is not None
        and receipt.operation_type.value == "report"
        and receipt.resume_attempted is True
        and receipt.new_codex_session_created is False
    )


def test_bridge_analyze_project_rejects_direct_call_when_source_scoping_never_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production Bridge (no injected source_scoping_provider): calling
    analyze_project directly after only load_project, with scope_project_sources
    never invoked at all, must fail closed with source_scoping_required -- not
    silently fall back to run_analysis with a local provider."""
    import continuity_ai.openai_provider as provider_module
    import continuity_ai.deterministic_offline_provider as offline_module

    fallback_calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> object:
        fallback_calls.append("fallback")
        raise AssertionError("provider fallback invoked")

    monkeypatch.setattr(provider_module, "OpenAIReasoningProvider", forbidden)
    monkeypatch.setattr(offline_module, "DeterministicOfflineReasoningProvider", forbidden)

    bridge, artifact_root, records = _init_bridge_and_load(tmp_path)

    blocked = bridge.handle(
        {"command": "analyze_project", "question": "Current state?"}
    )

    assert blocked["ok"] is False
    assert blocked["error"]["code"] == "source_scoping_required"
    assert fallback_calls == []
    assert bridge.analysis is None
    assert bridge.retained_analysis_status == "none"


def test_bridge_analyze_project_rejects_direct_call_after_investigation_without_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same production gate, exercised mid-flow: a real investigation has
    started (controller active) but confirm_source_scope was never called, so
    there is no approved-only workspace, no retained phase transition. This
    must also fail closed and must never resume run_analysis."""
    bridge, artifact_root, records = _init_bridge_and_load(tmp_path)
    classification = _classification_response(bridge.project, records)
    runner = ScriptedRunner([classification], [THREAD_ID])
    _patch_local_codex(monkeypatch, runner)

    scoped = bridge.handle({"command": "scope_project_sources"})
    assert scoped["ok"] is True
    assert bridge._vertical.controller is not None
    assert bridge._vertical.approved_workspace_root is None

    blocked = bridge.handle(
        {"command": "analyze_project", "question": "Current state?"}
    )
    assert blocked["ok"] is False
    # Blocked here by the pre-existing pending-review evidence boundary, one
    # layer before the vertical-flow readiness gate -- either way, no report
    # is ever produced without a completed, approved vertical flow.
    assert blocked["error"]["code"] in {"validation_error", "source_scoping_required"}
    assert len(runner.calls) == 1


def test_bridge_legacy_analyze_path_only_reachable_with_explicitly_injected_source_scoping_provider() -> None:
    """The old run_analysis fallback stays reachable, but only when a test
    double is explicitly injected -- never for a plain Bridge() or, by
    extension, bridge_main.py, which always constructs Bridge() with no
    arguments."""
    target, records = load_workspace(
        Path(__file__).parents[2] / "fixtures" / "source_scoping_mixed_workspace"
    )
    records = order_evidence(records)

    class _RecordingProvider:
        provider_id = "recording-legacy-path-provider"

        def __init__(self) -> None:
            self.calls = 0

        def analyze(self, evidence, spans, question):
            self.calls += 1
            return DeterministicOfflineReasoningProviderForTest().analyze(evidence, spans, question)

    from continuity_ai.reasoning_pipeline import (
        DeterministicOfflineReasoningProvider as DeterministicOfflineReasoningProviderForTest,
    )

    provider = _RecordingProvider()
    bridge = Bridge(provider=provider, source_scoping_provider=FakeSourceScopingProvider())
    bridge.project = target
    bridge.artifact_records = records
    bridge.records = records
    bridge.spans = build_spans(records)

    response = bridge.handle({"command": "analyze_project", "question": "q"})

    assert response["ok"] is True
    assert provider.calls == 1
    assert bridge._vertical.controller is None


def test_fake_source_scoping_provider_path_omits_run_identity() -> None:
    target, records = load_workspace(
        Path(__file__).parents[2] / "fixtures" / "source_scoping_mixed_workspace"
    )
    records = order_evidence(records)
    bridge = Bridge(provider=_UnusedReasoningProvider(), source_scoping_provider=FakeSourceScopingProvider())
    bridge.project = target
    bridge.artifact_records = records
    bridge.records = records
    bridge.spans = build_spans(records)

    scoped = bridge.handle({"command": "scope_project_sources"})
    assert scoped["ok"] is True
    assert "run_identity" not in scoped["data"]
    assert bridge._vertical.controller is None

    ambiguous = scoped["data"]["source_scope"]["ambiguous_evidence_ids"]
    confirmed = bridge.handle(
        {
            "command": "confirm_source_scope",
            "overrides": {evidence_id: "excluded" for evidence_id in ambiguous},
        }
    )
    assert confirmed["ok"] is True
    assert "run_identity" not in confirmed["data"]
