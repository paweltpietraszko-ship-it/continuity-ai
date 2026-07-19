"""Bridge-level proof for the split-phase Diagnostic Proof screen: prepare a
synthetic unseen workspace -> real Codex Source Scoping investigation ->
human review across a genuinely separate Bridge command -> confirm ->
approved-only materialization -> same-session report resume -> oracle
regenerated only after the engine finishes -> PASS/FAIL + claims, plus a
separate controlled-tamper check.

All Codex CLI calls here are driven by a scripted fake process runner (no
live network), matching `tests/integration/test_bridge_real_vertical_flow.py`.
This module never touches `continuity_ai.diagnostic_proof` itself (the
frozen core) -- only Bridge's own coordinator around it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import continuity_ai.integration.diagnostic_proof_bridge_flow as diag_flow_module
from continuity_ai.bridge import Bridge
from continuity_ai.codex_process import CodexCliCapabilities, CodexCliProcessAdapter
from continuity_ai.codex_session import CodexSessionController
from continuity_ai.unseen_workspace import generate_unseen_workspace, load_workspace

THREAD_ID = "12345678-1234-5678-9234-567812345678"


class _UnusedReasoningProvider:
    provider_id = "unused-in-diagnostic-flow"

    def analyze(self, evidence, spans, question):
        raise AssertionError("local reasoning provider invoked during diagnostic flow")


@dataclass
class ScriptedRunner:
    responses: list[str]

    def __post_init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(options)))
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        response_path = Path(command[command.index("--output-last-message") + 1])
        response_path.write_text(response, encoding="utf-8")
        stdout = json.dumps({"type": "thread.started", "thread_id": THREAD_ID}) + "\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def _patch_local_codex(monkeypatch: pytest.MonkeyPatch, runner: ScriptedRunner) -> None:
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


def _oracle_statuses(oracle_root: Path) -> dict[str, str]:
    payload = json.loads((oracle_root / "expected_scope.json").read_text(encoding="utf-8"))
    return {item["evidence_id"]: item["expected_status"] for item in payload["records"]}


def _classification_payload(input_root: Path, oracle_root: Path) -> str:
    workspace = load_workspace(input_root)
    statuses = _oracle_statuses(oracle_root)
    decisions = []
    for record in workspace.records:
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
                "rationale": "Deterministic diagnostic test response.",
                "span_ids": [f"{record.evidence_id}:L001"],
                "related_evidence_ids": [],
            }
        )
    return json.dumps(
        {
            "schema_version": "1.0",
            "target_project": workspace.target_project.name,
            "anchor_evidence_ids": [d["evidence_id"] for d in decisions if d["basis"] == "explicit_target"],
            "decisions": decisions,
            "selected_evidence_ids": [d["evidence_id"] for d in decisions if d["association_status"] == "included"],
            "ambiguous_evidence_ids": [d["evidence_id"] for d in decisions if d["association_status"] == "ambiguous"],
            "excluded_evidence_ids": [d["evidence_id"] for d in decisions if d["association_status"] == "excluded"],
        }
    )


def _approved_paths(input_root: Path, oracle_root: Path) -> list[str]:
    statuses = _oracle_statuses(oracle_root)
    return sorted(
        record.relative_path
        for record in load_workspace(input_root).records
        if statuses[record.evidence_id] == "include"
    )


def _prepare_and_script(bridge: Bridge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScriptedRunner:
    """Prepares a real diagnostic workspace through Bridge, then peeks at the
    resulting seed only at the Python-object level (bridge._diagnostic), the
    same way other tests in this suite read bridge._vertical directly --
    never through the NDJSON response, which never contains it."""
    prepared = bridge.handle({"command": "diagnostic_prepare_workspace"})
    assert prepared["ok"] is True
    workspace = bridge._diagnostic.workspace
    assert workspace is not None

    scripted_evaluation_root = tmp_path / "scripted-evaluation"
    generated = generate_unseen_workspace(scripted_evaluation_root, workspace.seed)
    generated_input_root = Path(str(generated["input_root"])).resolve(strict=True)
    oracle_root = Path(str(generated["oracle_root"])).resolve(strict=True)

    responses = [
        _classification_payload(generated_input_root, oracle_root),
        json.dumps({"relative_paths": _approved_paths(generated_input_root, oracle_root)}),
    ]
    runner = ScriptedRunner(responses)
    _patch_local_codex(monkeypatch, runner)
    return runner


def _prepare_and_script_with_confident_override(
    bridge: Bridge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    original_status: str,
) -> tuple[str, str, str]:
    """Like `_prepare_and_script`, but also picks one non-ambiguous evidence
    id with the given automatic Codex status and pre-scripts the reporting
    response to reflect the human's planned correction of it -- the test
    itself controls the oracle deterministically, so the correct final
    report contents are already knowable before `diagnostic_run_scoping`
    ever runs, exactly as a real Codex CLI would be asked to report on
    whatever the approved-only workspace actually contains."""
    prepared = bridge.handle({"command": "diagnostic_prepare_workspace"})
    assert prepared["ok"] is True
    workspace = bridge._diagnostic.workspace
    assert workspace is not None

    scripted_evaluation_root = tmp_path / "scripted-evaluation"
    generated = generate_unseen_workspace(scripted_evaluation_root, workspace.seed)
    generated_input_root = Path(str(generated["input_root"])).resolve(strict=True)
    oracle_root = Path(str(generated["oracle_root"])).resolve(strict=True)

    statuses = _oracle_statuses(oracle_root)
    flipped_evidence_id = next(
        evidence_id for evidence_id, status in statuses.items() if status == original_status
    )
    new_status = "included" if original_status == "exclude" else "excluded"

    final_included_ids = {
        evidence_id
        for evidence_id, status in statuses.items()
        if (status == "include" and evidence_id != flipped_evidence_id)
        or (evidence_id == flipped_evidence_id and new_status == "included")
    }
    path_by_id = {record.evidence_id: record.relative_path for record in load_workspace(generated_input_root).records}
    final_report_paths = sorted(path_by_id[evidence_id] for evidence_id in final_included_ids)

    responses = [
        _classification_payload(generated_input_root, oracle_root),
        json.dumps({"relative_paths": final_report_paths}),
    ]
    runner = ScriptedRunner(responses)
    _patch_local_codex(monkeypatch, runner)
    return flipped_evidence_id, new_status, path_by_id[flipped_evidence_id]


def _run_full_flow(bridge: Bridge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    _prepare_and_script(bridge, tmp_path, monkeypatch)

    scoping_resp = bridge.handle({"command": "diagnostic_run_scoping"})
    assert scoping_resp["ok"] is True, scoping_resp.get("error")
    decisions = scoping_resp["data"]["decisions"]
    overrides = {decision["evidence_id"]: "excluded" for decision in decisions}
    for decision in decisions:
        if decision["association_status"] == "included":
            overrides[decision["evidence_id"]] = "included"

    confirm_resp = bridge.handle({"command": "diagnostic_confirm_scope", "overrides": overrides})
    assert confirm_resp["ok"] is True, confirm_resp.get("error")
    return confirm_resp["data"]


def test_full_split_phase_flow_produces_pass_with_same_codex_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = Bridge(provider=_UnusedReasoningProvider())
    data = _run_full_flow(bridge, tmp_path, monkeypatch)

    assert data["phase"] == "completed"
    assert data["result"] == "PASS"
    assert data["codex_session_id"] == THREAD_ID
    claims = {claim["name"]: claim["status"] for claim in data["claims"]}
    assert claims["SAME_CODEX_SESSION_ID"] == "PASS"
    assert claims["ORACLE_ABSENT_DURING_ENGINE_EXECUTION"] == "PASS"
    assert claims["APPROVED_WORKSPACE_EXACT_PARTITION"] == "PASS"


def test_no_seed_oracle_or_local_path_ever_appears_in_any_bridge_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = Bridge(provider=_UnusedReasoningProvider())
    prepared = bridge.handle({"command": "diagnostic_prepare_workspace"})
    scripted_evaluation_root = tmp_path / "scripted-evaluation"
    workspace = bridge._diagnostic.workspace
    generated = generate_unseen_workspace(scripted_evaluation_root, workspace.seed)
    generated_input_root = Path(str(generated["input_root"])).resolve(strict=True)
    oracle_root = Path(str(generated["oracle_root"])).resolve(strict=True)
    responses = [
        _classification_payload(generated_input_root, oracle_root),
        json.dumps({"relative_paths": _approved_paths(generated_input_root, oracle_root)}),
    ]
    runner = ScriptedRunner(responses)
    _patch_local_codex(monkeypatch, runner)

    scoping_resp = bridge.handle({"command": "diagnostic_run_scoping"})
    decisions = scoping_resp["data"]["decisions"]
    overrides = {d["evidence_id"]: ("included" if d["association_status"] == "included" else "excluded") for d in decisions}
    confirm_resp = bridge.handle({"command": "diagnostic_confirm_scope", "overrides": overrides})
    tamper_resp = bridge.handle({"command": "diagnostic_run_tamper_check"})

    real_seed = str(workspace.seed)
    real_input_root = str(workspace.input_root)
    real_run_root = str(workspace.run_root)

    for response in (prepared, scoping_resp, confirm_resp, tamper_resp):
        body = json.dumps(response, ensure_ascii=False)
        assert real_seed not in body
        assert real_input_root not in body
        assert real_run_root not in body
        assert "\"seed\"" not in body
        assert "expected_status" not in body
        assert "oracle" not in body.casefold() or "oracle_evaluation" not in body


def test_confirm_requires_every_decision_explicitly_no_auto_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = Bridge(provider=_UnusedReasoningProvider())
    _prepare_and_script(bridge, tmp_path, monkeypatch)
    scoping_resp = bridge.handle({"command": "diagnostic_run_scoping"})
    decisions = scoping_resp["data"]["decisions"]
    assert len(decisions) > 1

    # Omit exactly one required decision: must fail closed, never silently
    # approve on the caller's behalf.
    partial_overrides = {
        d["evidence_id"]: "included" for d in decisions[:-1]
    }
    resp = bridge.handle({"command": "diagnostic_confirm_scope", "overrides": partial_overrides})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_error"
    assert bridge._diagnostic.phase == "awaiting_review"


def test_commands_fail_closed_out_of_order(tmp_path: Path) -> None:
    bridge = Bridge(provider=_UnusedReasoningProvider())

    for command in (
        {"command": "diagnostic_run_scoping"},
        {"command": "diagnostic_confirm_scope", "overrides": {}},
        {"command": "diagnostic_run_tamper_check"},
    ):
        resp = bridge.handle(command)
        assert resp["ok"] is False
        assert resp["error"]["code"] == "validation_error"
        assert bridge._diagnostic.phase == "idle"


def test_fresh_bridge_process_has_no_diagnostic_state_to_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulates a Bridge restart: a brand new Bridge instance never carries
    over diagnostic progress from a previous one."""
    first = Bridge(provider=_UnusedReasoningProvider())
    _prepare_and_script(first, tmp_path, monkeypatch)
    first.handle({"command": "diagnostic_run_scoping"})
    assert first._diagnostic.phase == "awaiting_review"

    second = Bridge(provider=_UnusedReasoningProvider())
    assert second._diagnostic.phase == "idle"
    resp = second.handle({"command": "diagnostic_confirm_scope", "overrides": {}})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_error"


def test_reset_allows_a_fresh_workspace_and_discards_the_previous_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = Bridge(provider=_UnusedReasoningProvider())
    data = _run_full_flow(bridge, tmp_path, monkeypatch)
    assert data["result"] == "PASS"
    first_input_root = bridge._diagnostic.workspace.input_root

    reset_resp = bridge.handle({"command": "diagnostic_reset"})
    assert reset_resp["ok"] is True
    assert reset_resp["data"]["phase"] == "idle"
    assert bridge._diagnostic.workspace is None
    assert not first_input_root.exists()

    prepared_again = bridge.handle({"command": "diagnostic_prepare_workspace"})
    assert prepared_again["ok"] is True
    assert bridge._diagnostic.workspace.input_root != first_input_root


def test_controlled_tamper_produces_expected_fail_without_overwriting_pass_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = Bridge(provider=_UnusedReasoningProvider())
    pass_data = _run_full_flow(bridge, tmp_path, monkeypatch)
    assert pass_data["result"] == "PASS"

    tamper_resp = bridge.handle({"command": "diagnostic_run_tamper_check"})
    assert tamper_resp["ok"] is True
    assert tamper_resp["data"]["phase"] == "tampered"
    assert tamper_resp["data"]["result"] == "FAIL"

    # The original PASS report is retained untouched alongside the tamper result.
    assert bridge._diagnostic.report is not None
    assert bridge._diagnostic.report.result.value == "PASS"
    assert bridge._diagnostic.tamper_report is not None
    assert bridge._diagnostic.tamper_report.result.value == "FAIL"

    # Tamper before completion fails closed.
    fresh = Bridge(provider=_UnusedReasoningProvider())
    resp = fresh.handle({"command": "diagnostic_run_tamper_check"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_error"


def test_human_review_happens_on_a_genuinely_separate_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves the review step is a real round trip, not a callback that
    silently approves: the background engine thread is still alive and
    blocked between diagnostic_run_scoping and diagnostic_confirm_scope."""
    bridge = Bridge(provider=_UnusedReasoningProvider())
    _prepare_and_script(bridge, tmp_path, monkeypatch)

    scoping_resp = bridge.handle({"command": "diagnostic_run_scoping"})
    assert scoping_resp["ok"] is True
    assert bridge._diagnostic.phase == "awaiting_review"
    assert bridge._diagnostic.completed is None

    run = bridge._diagnostic._run
    assert run is not None
    assert isinstance(run.thread, threading.Thread)
    assert run.thread.is_alive()

    decisions = scoping_resp["data"]["decisions"]
    overrides = {d["evidence_id"]: ("included" if d["association_status"] == "included" else "excluded") for d in decisions}
    bridge.handle({"command": "diagnostic_confirm_scope", "overrides": overrides})
    assert bridge._diagnostic.completed is not None


def _confirm_with_one_confident_override(
    bridge: Bridge, flipped_evidence_id: str, new_status: str
) -> dict[str, Any]:
    scoping_resp = bridge.handle({"command": "diagnostic_run_scoping"})
    assert scoping_resp["ok"] is True, scoping_resp.get("error")
    decisions = scoping_resp["data"]["decisions"]
    overrides: dict[str, str] = {}
    for decision in decisions:
        evidence_id = decision["evidence_id"]
        if evidence_id == flipped_evidence_id:
            overrides[evidence_id] = new_status
        elif decision["association_status"] == "ambiguous":
            overrides[evidence_id] = "excluded"
        else:
            overrides[evidence_id] = decision["association_status"]

    confirm_resp = bridge.handle({"command": "diagnostic_confirm_scope", "overrides": overrides})
    assert confirm_resp["ok"] is True, confirm_resp.get("error")
    return confirm_resp["data"]


def test_confident_included_to_excluded_override_physically_removes_the_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A human correcting a confident Codex 'included' decision to
    'excluded' must physically remove that source from the approved-only
    workspace, must be reflected in what reporting actually sees, and must
    be allowed to make the proof honestly FAIL -- the correction is real,
    not decorative."""
    bridge = Bridge(provider=_UnusedReasoningProvider())
    flipped_evidence_id, new_status, relative_path = _prepare_and_script_with_confident_override(
        bridge, tmp_path, monkeypatch, original_status="include"
    )
    assert new_status == "excluded"

    data = _confirm_with_one_confident_override(bridge, flipped_evidence_id, new_status)

    completed = bridge._diagnostic.completed
    assert completed is not None
    assert flipped_evidence_id in completed.excluded_evidence_ids
    assert flipped_evidence_id not in completed.approved_evidence_ids

    approved_root = completed.approved_workspace_root
    removed_path = approved_root.joinpath(*relative_path.split("/"))
    assert not removed_path.exists()
    assert relative_path not in completed.reported_relative_paths

    assert data["result"] == "FAIL"
    claims = {claim["name"]: claim["status"] for claim in data["claims"]}
    assert claims["PROJECT_REPORT_PATHS_MATCH_APPROVED_SCOPE"] == "PASS"


def test_confident_excluded_to_included_override_physically_adds_the_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A human correcting a confident Codex 'excluded' decision to
    'included' must physically add that source to the approved-only
    workspace and must be reflected in what reporting actually sees."""
    bridge = Bridge(provider=_UnusedReasoningProvider())
    flipped_evidence_id, new_status, relative_path = _prepare_and_script_with_confident_override(
        bridge, tmp_path, monkeypatch, original_status="exclude"
    )
    assert new_status == "included"

    data = _confirm_with_one_confident_override(bridge, flipped_evidence_id, new_status)

    completed = bridge._diagnostic.completed
    assert completed is not None
    assert flipped_evidence_id in completed.approved_evidence_ids
    assert flipped_evidence_id not in completed.excluded_evidence_ids

    approved_root = completed.approved_workspace_root
    added_path = approved_root.joinpath(*relative_path.split("/"))
    assert added_path.is_file()
    assert relative_path in completed.reported_relative_paths

    assert data["result"] == "FAIL"
    claims = {claim["name"]: claim["status"] for claim in data["claims"]}
    assert claims["PROJECT_REPORT_PATHS_MATCH_APPROVED_SCOPE"] == "PASS"


def test_agreeing_review_with_no_confident_corrections_still_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirms the fix does not regress the ordinary case: a human who
    clicks in agreement with every confident decision (and only resolves
    ambiguous ones) still produces a clean PASS, exactly as before."""
    bridge = Bridge(provider=_UnusedReasoningProvider())
    data = _run_full_flow(bridge, tmp_path, monkeypatch)
    assert data["result"] == "PASS"


def test_same_codex_session_id_claim_never_exposes_the_full_session_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = Bridge(provider=_UnusedReasoningProvider())
    data = _run_full_flow(bridge, tmp_path, monkeypatch)

    claims_by_name = {claim["name"]: claim for claim in data["claims"]}
    same_session_claim = claims_by_name["SAME_CODEX_SESSION_ID"]
    assert same_session_claim["status"] == "PASS"
    assert THREAD_ID not in same_session_claim["observed"]
    assert same_session_claim["observed"] == "same retained session"

    body = json.dumps(data, ensure_ascii=False)
    # The dedicated summary field is allowed to carry the full id (the
    # desktop layer truncates it for display, matching RunIdentity
    # elsewhere); no *claim* observed/expected value may ever contain it.
    for claim in data["claims"]:
        assert THREAD_ID not in claim["observed"]


def test_scoping_rejection_preserves_the_prepared_workspace_for_an_explicit_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First diagnostic_run_scoping call gets a controlled semantic
    rejection from Codex; the prepared oracle-free workspace and its
    fingerprint must survive unchanged, phase must fall back to
    workspace_ready (not idle), a second explicit call must succeed with the
    exact same workspace, no fallback provider is ever consulted, and the
    oracle stays absent for both attempts."""
    import continuity_ai.deterministic_offline_provider as offline_module
    import continuity_ai.openai_provider as provider_module

    fallback_calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> object:
        fallback_calls.append("fallback")
        raise AssertionError("provider fallback invoked")

    monkeypatch.setattr(provider_module, "OpenAIReasoningProvider", forbidden)
    monkeypatch.setattr(offline_module, "DeterministicOfflineReasoningProvider", forbidden)

    bridge = Bridge(provider=_UnusedReasoningProvider())
    prepared = bridge.handle({"command": "diagnostic_prepare_workspace"})
    assert prepared["ok"] is True
    workspace_before = bridge._diagnostic.workspace
    fingerprint_before = workspace_before.generated_input_fingerprint
    run_root_before = workspace_before.run_root

    scripted_evaluation_root = tmp_path / "scripted-evaluation"
    generated = generate_unseen_workspace(scripted_evaluation_root, workspace_before.seed)
    generated_input_root = Path(str(generated["input_root"])).resolve(strict=True)
    oracle_root = Path(str(generated["oracle_root"])).resolve(strict=True)

    def _oracle_absent(root: Path) -> bool:
        return not any(
            path.name.casefold() in {"oracle", "expected_scope.json"} for path in root.rglob("*")
        )

    assert _oracle_absent(run_root_before)

    responses = [
        json.dumps({"not": "the expected source scoping shape"}),
        _classification_payload(generated_input_root, oracle_root),
        json.dumps({"relative_paths": _approved_paths(generated_input_root, oracle_root)}),
    ]
    runner = ScriptedRunner(responses)
    _patch_local_codex(monkeypatch, runner)

    first_attempt = bridge.handle({"command": "diagnostic_run_scoping"})
    assert first_attempt["ok"] is False
    assert first_attempt["error"]["code"] == "provider_error"
    assert fallback_calls == []
    assert bridge._diagnostic.phase == "workspace_ready"
    assert bridge._diagnostic.workspace is workspace_before
    assert bridge._diagnostic.workspace.generated_input_fingerprint == fingerprint_before
    assert bridge._diagnostic.controller is None
    assert bridge._diagnostic._run is None
    assert _oracle_absent(run_root_before)

    second_attempt = bridge.handle({"command": "diagnostic_run_scoping"})
    assert second_attempt["ok"] is True, second_attempt.get("error")
    assert bridge._diagnostic.phase == "awaiting_review"
    assert bridge._diagnostic.workspace.generated_input_fingerprint == fingerprint_before
    assert fallback_calls == []
    assert _oracle_absent(run_root_before)
    assert len(runner.calls) == 2
