from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from continuity_ai.codex_process import (
    CodexCliCapabilities,
    CodexCliProcessAdapter,
    workspace_fingerprint,
)
from continuity_ai.codex_session import CodexSessionController, JsonSessionStore
from continuity_ai.diagnostic_proof import (
    apply_controlled_workspace_tamper,
    evaluate_completed_diagnostic_run,
    prepare_diagnostic_workspace,
    run_diagnostic_engine,
    write_diagnostic_reports,
)
from continuity_ai.unseen_workspace import load_workspace
from continuity_ai.unseen_workspace.models import ProofStatus

THREAD_ID = "12345678-1234-5678-9234-567812345678"


@dataclass
class ScriptedRunner:
    responses: list[str]

    def __post_init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(
        self, command: list[str], **options: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(options)))
        response = self.responses[len(self.calls) - 1]
        response_path = Path(command[command.index("--output-last-message") + 1])
        response_path.write_text(response, encoding="utf-8")
        stdout = json.dumps({"type": "thread.started", "thread_id": THREAD_ID}) + "\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def _controller(tmp_path: Path, runner: ScriptedRunner) -> CodexSessionController:
    adapter = CodexCliProcessAdapter(
        "codex",
        resolved_executable=Path(sys.executable),
        version="codex-cli diagnostic-test",
        capabilities=CodexCliCapabilities(
            True, True, True, True, True, resume_verified=True
        ),
        process_runner=runner,
    )
    return CodexSessionController(JsonSessionStore(tmp_path / "sessions.json"), adapter)


def _oracle_statuses(oracle_root: Path) -> dict[str, str]:
    payload = json.loads((oracle_root / "expected_scope.json").read_text(encoding="utf-8"))
    return {item["evidence_id"]: item["expected_status"] for item in payload["records"]}


def _classification_payload(input_root: Path, oracle_root: Path) -> str:
    workspace = load_workspace(input_root)
    statuses = _oracle_statuses(oracle_root)
    decisions = []
    for record in workspace.records:
        status = statuses[record.evidence_id]
        association = {
            "include": "included",
            "exclude": "excluded",
            "defer": "ambiguous",
        }[status]
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
                "rationale": "Deterministic diagnostic process response.",
                "span_ids": [f"{record.evidence_id}:L001"],
                "related_evidence_ids": [],
            }
        )
    return json.dumps(
        {
            "schema_version": "1.0",
            "target_project": workspace.target_project.name,
            "anchor_evidence_ids": [
                item["evidence_id"]
                for item in decisions
                if item["basis"] == "explicit_target"
            ],
            "decisions": decisions,
            "selected_evidence_ids": [
                item["evidence_id"]
                for item in decisions
                if item["association_status"] == "included"
            ],
            "ambiguous_evidence_ids": [
                item["evidence_id"]
                for item in decisions
                if item["association_status"] == "ambiguous"
            ],
            "excluded_evidence_ids": [
                item["evidence_id"]
                for item in decisions
                if item["association_status"] == "excluded"
            ],
        }
    )


def _approved_paths(input_root: Path, oracle_root: Path) -> list[str]:
    statuses = _oracle_statuses(oracle_root)
    return sorted(
        record.relative_path
        for record in load_workspace(input_root).records
        if statuses[record.evidence_id] == "include"
    )


def _review_ambiguities(result) -> dict[str, str]:
    return {evidence_id: "excluded" for evidence_id in result.ambiguous_evidence_ids}


def _run(tmp_path: Path, seed: int):
    workspace = prepare_diagnostic_workspace(tmp_path / "generated", seed)
    runner = ScriptedRunner(
        [
            _classification_payload(workspace.input_root, workspace.oracle_root),
            json.dumps(
                {"relative_paths": _approved_paths(workspace.input_root, workspace.oracle_root)}
            ),
        ]
    )
    completed = run_diagnostic_engine(
        _controller(tmp_path, runner),
        workspace.input_root,
        tmp_path / "approved",
        _review_ambiguities,
        timeout_seconds=30,
    )
    return workspace, runner, completed


@pytest.mark.parametrize("seed", [7, 314159, -90210])
def test_multiple_seeds_produce_complete_passing_proofs(tmp_path: Path, seed: int) -> None:
    workspace, runner, completed = _run(tmp_path, seed)
    report = evaluate_completed_diagnostic_run(completed, workspace.oracle_root)

    assert report.seed == seed
    assert report.result is ProofStatus.PASS
    assert report.input_fingerprint == workspace_fingerprint(workspace.input_root)
    assert report.controller_session_id == completed.controller_session_id
    assert report.codex_session_id == THREAD_ID
    assert completed.investigation_codex_session_id == THREAD_ID
    assert completed.reporting_codex_session_id == THREAD_ID
    assert len(runner.calls) == 2
    assert runner.calls[0][1]["cwd"] == workspace.input_root
    assert runner.calls[1][1]["cwd"] == completed.approved_workspace_root.resolve()
    assert str(workspace.oracle_root) not in " ".join(runner.calls[0][0])

    claims = {claim.name: claim.status for claim in report.claims}
    assert claims["EXACT_PARTITION_INTEGRITY"] is ProofStatus.PASS
    assert claims["APPROVED_WORKSPACE_EXACT_PARTITION"] is ProofStatus.PASS
    assert claims["EXCLUDED_OUTSIDE_APPROVED_WORKSPACE"] is ProofStatus.PASS
    assert claims["SAME_CODEX_SESSION_ID"] is ProofStatus.PASS


def test_oracle_is_not_present_or_nested_in_engine_root(tmp_path: Path) -> None:
    workspace = prepare_diagnostic_workspace(tmp_path / "generated", 101)

    assert workspace.input_root.parent == workspace.oracle_root.parent
    assert workspace.input_root != workspace.oracle_root
    assert not workspace.oracle_root.is_relative_to(workspace.input_root)
    assert not workspace.input_root.is_relative_to(workspace.oracle_root)
    assert {path.name for path in workspace.input_root.iterdir()} == {
        "workspace.json",
        "records",
    }
    engine_bytes = b"".join(
        path.read_bytes().lower() for path in workspace.input_root.rglob("*") if path.is_file()
    )
    assert b'"expected_status"' not in engine_bytes
    assert b'"seed"' not in engine_bytes


def test_excluded_artifacts_are_physically_absent_from_approved_workspace(
    tmp_path: Path,
) -> None:
    _, _, completed = _run(tmp_path, 202)
    path_by_id = dict(completed.evidence_paths)

    for evidence_id in completed.excluded_evidence_ids:
        assert not (
            completed.approved_workspace_root
            / Path(*path_by_id[evidence_id].split("/"))
        ).exists()
    for evidence_id in completed.approved_evidence_ids:
        assert (
            completed.approved_workspace_root
            / Path(*path_by_id[evidence_id].split("/"))
        ).is_file()


def test_controlled_post_completion_tamper_produces_fail(tmp_path: Path) -> None:
    workspace, _, completed = _run(tmp_path, 303)
    changed = apply_controlled_workspace_tamper(completed)

    report = evaluate_completed_diagnostic_run(completed, workspace.oracle_root)

    assert changed.is_file()
    assert report.result is ProofStatus.FAIL
    claims = {claim.name: claim.status for claim in report.claims}
    assert claims["APPROVED_WORKSPACE_FINGERPRINT_MATCH"] is ProofStatus.FAIL
    assert claims["APPROVED_WORKSPACE_EXACT_PARTITION"] is ProofStatus.FAIL


def test_same_seed_has_identical_standalone_input(tmp_path: Path) -> None:
    first = prepare_diagnostic_workspace(tmp_path / "first", 404)
    second = prepare_diagnostic_workspace(tmp_path / "second", 404)

    def snapshot(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    assert snapshot(first.input_root) == snapshot(second.input_root)
    assert workspace_fingerprint(first.input_root) == workspace_fingerprint(second.input_root)


def test_json_and_markdown_record_required_identity_and_claims(tmp_path: Path) -> None:
    workspace, _, completed = _run(tmp_path, 505)
    report = evaluate_completed_diagnostic_run(completed, workspace.oracle_root)
    artifacts = write_diagnostic_reports(report, tmp_path / "proof")

    payload = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    markdown = artifacts.markdown_path.read_text(encoding="utf-8")
    assert payload["seed"] == 505
    assert payload["input_fingerprint"] == report.input_fingerprint
    assert payload["controller_session_id"] == report.controller_session_id
    assert payload["codex_session_id"] == THREAD_ID
    assert payload["result"] == "PASS"
    assert payload["claims"]
    assert "DIAGNOSTIC PROOF: **PASS**" in markdown
    for value in (
        str(report.seed),
        report.input_fingerprint,
        report.controller_session_id,
        report.codex_session_id,
    ):
        assert value in markdown


def test_production_logic_contains_no_fixture_project_names() -> None:
    source_root = Path(__file__).parents[2] / "src/continuity_ai/diagnostic_proof"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in source_root.glob("*.py")
    ).casefold()
    forbidden = ("aur" + "ora", "meri" + "dian", "em" + "ber")
    assert all(name not in source for name in forbidden)
