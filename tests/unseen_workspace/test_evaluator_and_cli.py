from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from continuity_ai.cli import main
from continuity_ai.unseen_workspace.evaluator import (
    ScopeEvaluationError,
    evaluate_scope,
    load_classification_result,
)
from continuity_ai.unseen_workspace.generator import generate_unseen_workspace
from continuity_ai.unseen_workspace.models import (
    ClassificationDecision,
    ClassificationResult,
    ScopeStatus,
)


def _oracle(run: Path) -> dict[str, object]:
    return json.loads((run / "oracle" / "expected_scope.json").read_text(encoding="utf-8"))


def _perfect_result(oracle: dict[str, object]) -> ClassificationResult:
    return ClassificationResult(
        decisions=tuple(
            ClassificationDecision(
                evidence_id=record["evidence_id"],
                status=ScopeStatus(record["expected_status"]),
            )
            for record in oracle["records"]
        )
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_perfect_evaluation_reports_all_minimum_metrics(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 55)
    oracle = _oracle(run)
    result = _perfect_result(oracle)

    report = evaluate_scope(run / "oracle" / "expected_scope.json", result)

    assert report.classified_records == report.total_records == 15
    assert report.records_classified_exactly_once == 15
    assert report.valid_evidence_references == report.total_evidence_references == 15
    assert report.invalid_evidence_references == ()
    assert report.unsafe_automatic_inclusions == ()
    assert report.correctly_deferred_ambiguous_records == report.total_ambiguous_records
    assert report.total_ambiguous_records >= 2
    assert report.exact_status_matches == 15


def test_evaluator_reports_duplicates_invalid_references_unsafe_inclusions_and_deferral(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 66)
    oracle = _oracle(run)
    include_id = next(record["evidence_id"] for record in oracle["records"] if record["expected_status"] == "include")
    exclude_id = next(record["evidence_id"] for record in oracle["records"] if record["expected_status"] == "exclude")
    defer_id = next(record["evidence_id"] for record in oracle["records"] if record["expected_status"] == "defer")
    result = ClassificationResult(
        decisions=(
            ClassificationDecision(include_id, ScopeStatus.INCLUDE),
            ClassificationDecision(include_id, ScopeStatus.INCLUDE),
            ClassificationDecision(exclude_id, ScopeStatus.INCLUDE),
            ClassificationDecision(defer_id, ScopeStatus.INCLUDE),
            ClassificationDecision("EV-UNKNOWN", ScopeStatus.EXCLUDE),
        )
    )

    report = evaluate_scope(run / "oracle" / "expected_scope.json", result)

    assert report.classified_records == 3
    assert report.records_classified_exactly_once == 2
    assert report.valid_evidence_references == 4
    assert report.total_evidence_references == 5
    assert report.invalid_evidence_references == ("EV-UNKNOWN",)
    assert report.unsafe_automatic_inclusions == tuple(sorted((exclude_id, defer_id)))
    assert report.correctly_deferred_ambiguous_records == 0
    assert report.exact_status_matches == 0


def test_classification_loader_preserves_duplicate_decisions_for_evaluation(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    _write_json(
        result_path,
        {
            "schema_version": 1,
            "decisions": [
                {"evidence_id": "EV-ONE", "status": "include"},
                {"evidence_id": "EV-ONE", "status": "defer"},
            ],
        },
    )

    result = load_classification_result(result_path)

    assert len(result.decisions) == 2
    assert result.decisions[0].evidence_id == result.decisions[1].evidence_id
    assert result.decisions[0].status is ScopeStatus.INCLUDE
    assert result.decisions[1].status is ScopeStatus.DEFER


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 1, "decisions": "not-an-array"},
        {"schema_version": 2, "decisions": []},
        {"schema_version": 1, "decisions": [{"evidence_id": "EV-X", "status": "maybe"}]},
        {"schema_version": 1, "decisions": [{"evidence_id": " EV-X", "status": "include"}]},
        {"schema_version": 1, "decisions": [], "unexpected": True},
    ],
)
def test_classification_loader_fails_closed_on_malformed_contract(
    tmp_path: Path, payload: object
) -> None:
    result_path = tmp_path / "result.json"
    _write_json(result_path, payload)

    with pytest.raises(ScopeEvaluationError):
        load_classification_result(result_path)


def test_evaluator_rejects_duplicate_oracle_identity(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 77)
    oracle_path = run / "oracle" / "expected_scope.json"
    oracle = _oracle(run)
    oracle["records"].append(dict(oracle["records"][0]))
    _write_json(oracle_path, oracle)

    with pytest.raises(ScopeEvaluationError, match="Duplicate oracle evidence_id"):
        evaluate_scope(oracle_path, ClassificationResult(decisions=()))


def test_oracle_and_classification_order_do_not_affect_metrics(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 87)
    oracle_path = run / "oracle" / "expected_scope.json"
    oracle = _oracle(run)
    oracle["records"] = list(reversed(oracle["records"]))
    _write_json(oracle_path, oracle)
    result = ClassificationResult(decisions=tuple(reversed(_perfect_result(oracle).decisions)))

    report = evaluate_scope(oracle_path, result)

    assert report.exact_status_matches == report.total_records == 15
    assert report.unsafe_automatic_inclusions == ()


def test_generator_cli_requires_seed_and_emits_run_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = tmp_path / "cli-run"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "continuity-ai",
            "generate-unseen-workspace",
            "--seed",
            "2468",
            "--output-root",
            str(run),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["record_count"] == 15
    assert output["input_root"] == str(run / "input")
    assert (run / "oracle" / "expected_scope.json").is_file()


def test_evaluator_cli_emits_json_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 97531)
    oracle = _oracle(run)
    result_path = tmp_path / "classification.json"
    _write_json(
        result_path,
        {
            "schema_version": 1,
            "decisions": [
                {"evidence_id": record["evidence_id"], "status": record["expected_status"]}
                for record in oracle["records"]
            ],
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "continuity-ai",
            "evaluate-unseen-workspace",
            "--expected-scope",
            str(run / "oracle" / "expected_scope.json"),
            "--classification-result",
            str(result_path),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["classified_records"] == output["total_records"] == 15
    assert output["unsafe_automatic_inclusions"] == []
    assert output["correctly_deferred_ambiguous_records"] >= 2
