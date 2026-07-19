from __future__ import annotations

from pathlib import Path

import pytest

from continuity_ai.unseen_workspace.evaluator import (
    ScopeEvaluationError,
    evaluate_generated_run,
    load_classification_result,
)
from continuity_ai.unseen_workspace.generator import generate_unseen_workspace
from continuity_ai.unseen_workspace.models import ClassificationResult
from .proof_test_support import (
    load_oracle,
    perfect_submission,
    submission_payload,
    write_json,
)


@pytest.mark.parametrize(
    "mutation",
    [
        {"provider_identity": ""},
        {"decisions": "not-an-array"},
        {"human_overrides": "not-an-array"},
        {"approved_scope_evidence_ids": "not-an-array"},
        {"project_report_evidence_ids": "not-an-array"},
    ],
)
def test_classification_submission_contract_fails_closed(
    tmp_path: Path, mutation: dict[str, object]
) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 71)
    payload = submission_payload(perfect_submission(load_oracle(run)))
    payload.update(mutation)
    result_path = tmp_path / "submission.json"
    write_json(result_path, payload)

    with pytest.raises(ScopeEvaluationError):
        load_classification_result(result_path)


def test_direct_typed_submission_contract_fails_closed_like_json_boundary(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 72)
    valid = perfect_submission(load_oracle(run))
    invalid = ClassificationResult(
        provider_identity="",
        decisions=valid.decisions,
        human_overrides=(),
        approved_scope_evidence_ids=valid.approved_scope_evidence_ids,
        project_report_evidence_ids=valid.project_report_evidence_ids,
    )

    with pytest.raises(ScopeEvaluationError):
        evaluate_generated_run(run, invalid)
