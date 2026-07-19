from __future__ import annotations

from pathlib import Path

import pytest

from continuity_ai.codex_session import CodexSessionController, JsonSessionStore
from continuity_ai.diagnostic_proof import (
    evaluate_completed_diagnostic_run,
    prepare_diagnostic_workspace,
    regenerate_diagnostic_evaluation,
    run_diagnostic_engine,
    write_diagnostic_reports,
)
from continuity_ai.unseen_workspace.models import ProofStatus


@pytest.mark.live_network
def test_real_local_codex_runs_diagnostic_core_on_isolated_roots(tmp_path: Path) -> None:
    workspace = prepare_diagnostic_workspace(tmp_path / "generated", 8675309)
    assert not any(
        path.name.casefold() in {"oracle", "expected_scope.json"}
        for path in workspace.run_root.rglob("*")
    )
    controller = CodexSessionController.with_local_codex(
        JsonSessionStore(tmp_path / "sessions.json")
    )
    if not controller.process_adapter.capabilities.resume_supported:
        pytest.skip("Local Codex CLI does not support verified resume.")

    completed = run_diagnostic_engine(
        controller,
        workspace.input_root,
        tmp_path / "approved",
        lambda result: {
            evidence_id: "excluded" for evidence_id in result.ambiguous_evidence_ids
        },
        timeout_seconds=180,
    )
    assert completed.oracle_absent_during_engine_execution
    assert not any(
        path.name.casefold() in {"oracle", "expected_scope.json"}
        for path in workspace.run_root.rglob("*")
    )

    evaluation = regenerate_diagnostic_evaluation(workspace, completed)
    report = evaluate_completed_diagnostic_run(completed, evaluation)
    artifacts = write_diagnostic_reports(report, tmp_path / "proof")
    claims = {claim.name: claim.status for claim in report.claims}

    assert claims["ORACLE_ABSENT_DURING_ENGINE_EXECUTION"] is ProofStatus.PASS
    assert claims["ENGINE_INPUT_MATCHES_GENERATED_INPUT"] is ProofStatus.PASS
    assert completed.investigation_codex_session_id == completed.reporting_codex_session_id
    assert evaluation.oracle_root.is_dir()
    assert artifacts.json_path.is_file()
    assert artifacts.markdown_path.is_file()
