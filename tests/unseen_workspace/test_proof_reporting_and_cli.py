from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from continuity_ai.cli import main
from continuity_ai.unseen_workspace.evaluator import evaluate_generated_run
from continuity_ai.unseen_workspace.generator import generate_unseen_workspace
from continuity_ai.unseen_workspace.reporting import (
    EvaluationReportWriteError,
    render_evaluation_json,
    render_evaluation_markdown,
    write_evaluation_reports,
)
from .proof_test_support import (
    load_oracle,
    perfect_submission,
    submission_payload,
    write_json,
)


def test_json_and_markdown_are_equivalent_views_of_one_canonical_report(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 69)
    report = evaluate_generated_run(run, perfect_submission(load_oracle(run)))

    json_text = render_evaluation_json(report)
    markdown = render_evaluation_markdown(report)

    assert json.loads(json_text) == report.to_dict()
    assert f"Unseen seed | `{report.unseen_seed}`" in markdown
    assert report.target_project.name in markdown
    assert report.provider_identity in markdown
    assert report.oracle_exposure_status.value in markdown
    assert f"MACHINE-EVALUABLE PROOF: **{report.machine_evaluable_proof.value}**" in markdown
    assert all(claim.name in markdown for claim in report.claims)


def test_report_writer_atomically_emits_json_and_markdown_from_canonical_model(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 70)
    report = evaluate_generated_run(run, perfect_submission(load_oracle(run)))
    output_root = tmp_path / "proof"

    artifacts = write_evaluation_reports(report, output_root)

    assert json.loads(artifacts.json_path.read_text(encoding="utf-8")) == report.to_dict()
    assert artifacts.markdown_path.read_text(encoding="utf-8") == render_evaluation_markdown(report)
    with pytest.raises(EvaluationReportWriteError):
        write_evaluation_reports(report, output_root)


def test_evaluator_cli_emits_machine_json_human_markdown_and_video_visible_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 97531)
    result_path = tmp_path / "classification.json"
    write_json(
        result_path,
        submission_payload(perfect_submission(load_oracle(run))),
    )
    output_root = tmp_path / "evaluation-proof"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "continuity-ai",
            "evaluate-unseen-workspace",
            "--run-root",
            str(run),
            "--classification-result",
            str(result_path),
            "--output-root",
            str(output_root),
        ],
    )

    main()

    visible_output = capsys.readouterr().out
    machine_report = json.loads((output_root / "report.json").read_text(encoding="utf-8"))
    human_report = (output_root / "report.md").read_text(encoding="utf-8")
    assert machine_report["machine_evaluable_proof"] == "PASS"
    assert "MACHINE-EVALUABLE PROOF: **PASS**" in human_report
    assert "MACHINE-EVALUABLE PROOF: **PASS**" in visible_output
    assert "JSON report:" in visible_output
    assert "Markdown report:" in visible_output
