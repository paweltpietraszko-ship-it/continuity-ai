from __future__ import annotations

from pathlib import Path

import pytest

from continuity_ai.codex_session import CodexSessionController, JsonSessionStore
from continuity_ai.diagnostic_proof import (
    evaluate_completed_diagnostic_run,
    prepare_diagnostic_workspace,
    run_diagnostic_engine,
    write_diagnostic_reports,
)


@pytest.mark.live_network
def test_real_local_codex_runs_diagnostic_core_on_isolated_roots(tmp_path: Path) -> None:
    workspace = prepare_diagnostic_workspace(tmp_path / "generated", 8675309)
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
    report = evaluate_completed_diagnostic_run(completed, workspace.oracle_root)
    artifacts = write_diagnostic_reports(report, tmp_path / "proof")

    assert completed.investigation_codex_session_id == completed.reporting_codex_session_id
    assert artifacts.json_path.is_file()
    assert artifacts.markdown_path.is_file()
