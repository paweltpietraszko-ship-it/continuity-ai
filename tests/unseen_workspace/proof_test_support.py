from __future__ import annotations

import json
from pathlib import Path

from continuity_ai.unseen_workspace.models import (
    ClassificationDecision,
    ClassificationResult,
    HumanOverride,
    ProofStatus,
    ScopeStatus,
)


def load_oracle(run: Path) -> dict[str, object]:
    return json.loads((run / "oracle" / "expected_scope.json").read_text(encoding="utf-8"))


def perfect_submission(
    oracle: dict[str, object],
    *,
    provider_identity: str = "deterministic-contract-provider",
    human_overrides: tuple[HumanOverride, ...] = (),
) -> ClassificationResult:
    decisions = tuple(
        ClassificationDecision(
            evidence_id=record["evidence_id"],
            status=ScopeStatus(record["expected_status"]),
        )
        for record in oracle["records"]
    )
    final_statuses = {decision.evidence_id: decision.status for decision in decisions}
    for override in human_overrides:
        final_statuses[override.evidence_id] = override.status
    approved = tuple(
        sorted(
            evidence_id
            for evidence_id, status in final_statuses.items()
            if status is ScopeStatus.INCLUDE
        )
    )
    return ClassificationResult(
        provider_identity=provider_identity,
        decisions=decisions,
        human_overrides=human_overrides,
        approved_scope_evidence_ids=approved,
        project_report_evidence_ids=approved,
    )


def claim_status(report: object, claim_name: str) -> ProofStatus:
    claim = next(claim for claim in report.claims if claim.name == claim_name)
    return claim.status


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def submission_payload(result: ClassificationResult) -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider_identity": result.provider_identity,
        "decisions": [
            {"evidence_id": decision.evidence_id, "status": decision.status.value}
            for decision in result.decisions
        ],
        "human_overrides": [
            {"evidence_id": override.evidence_id, "status": override.status.value}
            for override in result.human_overrides
        ],
        "approved_scope_evidence_ids": list(result.approved_scope_evidence_ids),
        "project_report_evidence_ids": list(result.project_report_evidence_ids),
    }
