"""Oracle-backed evaluation isolated from production workspace ingestion."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from continuity_ai.unseen_workspace.models import (
    ClassificationDecision,
    ClassificationResult,
    EvaluationReport,
    ScopeStatus,
)

_RESULT_FIELDS = {"schema_version", "decisions"}
_DECISION_FIELDS = {"evidence_id", "status"}
_EXPECTED_FIELDS = {"schema_version", "target_project", "records"}
_EXPECTED_RECORD_FIELDS = {"evidence_id", "expected_status", "scenario_tags"}


class ScopeEvaluationError(RuntimeError):
    """Raised when a classification result or hidden oracle is malformed."""


def load_classification_result(path: Path) -> ClassificationResult:
    """Load a later classifier's strict JSON output contract."""

    payload = _load_json(path, "Classification result")
    if not isinstance(payload, dict) or set(payload) != _RESULT_FIELDS:
        raise ScopeEvaluationError("Classification result fields are missing or unexpected.")
    if payload.get("schema_version") != 1:
        raise ScopeEvaluationError("Classification result schema_version is unsupported.")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        raise ScopeEvaluationError("Classification decisions must be an array.")

    parsed: list[ClassificationDecision] = []
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != _DECISION_FIELDS:
            raise ScopeEvaluationError("Classification decision fields are missing or unexpected.")
        evidence_id = _canonical_string(decision.get("evidence_id"), "decision evidence_id")
        parsed.append(
            ClassificationDecision(
                evidence_id=evidence_id,
                status=_parse_status(decision.get("status"), "decision status"),
            )
        )
    return ClassificationResult(decisions=tuple(parsed))


def evaluate_scope(
    expected_scope_path: Path,
    classification_result: ClassificationResult,
) -> EvaluationReport:
    """Compare a classification result with an explicitly supplied hidden oracle."""

    expected = _load_expected_scope(expected_scope_path)
    expected_ids = set(expected)
    counts = Counter(decision.evidence_id for decision in classification_result.decisions)
    by_id: dict[str, list[ScopeStatus]] = defaultdict(list)
    for decision in classification_result.decisions:
        by_id[decision.evidence_id].append(decision.status)

    invalid = tuple(sorted({evidence_id for evidence_id in counts if evidence_id not in expected_ids}))
    unsafe = tuple(
        sorted(
            evidence_id
            for evidence_id, expected_status in expected.items()
            if expected_status is not ScopeStatus.INCLUDE and ScopeStatus.INCLUDE in by_id[evidence_id]
        )
    )
    ambiguous_ids = {
        evidence_id for evidence_id, status in expected.items() if status is ScopeStatus.DEFER
    }
    correctly_deferred = sum(
        counts[evidence_id] == 1 and by_id[evidence_id] == [ScopeStatus.DEFER]
        for evidence_id in ambiguous_ids
    )
    exact_matches = sum(
        counts[evidence_id] == 1 and by_id[evidence_id] == [expected_status]
        for evidence_id, expected_status in expected.items()
    )

    return EvaluationReport(
        classified_records=sum(counts[evidence_id] > 0 for evidence_id in expected_ids),
        total_records=len(expected_ids),
        records_classified_exactly_once=sum(counts[evidence_id] == 1 for evidence_id in expected_ids),
        valid_evidence_references=sum(
            decision.evidence_id in expected_ids for decision in classification_result.decisions
        ),
        total_evidence_references=len(classification_result.decisions),
        invalid_evidence_references=invalid,
        unsafe_automatic_inclusions=unsafe,
        correctly_deferred_ambiguous_records=correctly_deferred,
        total_ambiguous_records=len(ambiguous_ids),
        exact_status_matches=exact_matches,
    )


def _load_expected_scope(path: Path) -> dict[str, ScopeStatus]:
    payload = _load_json(path, "Expected scope oracle")
    if not isinstance(payload, dict) or set(payload) != _EXPECTED_FIELDS:
        raise ScopeEvaluationError("Expected scope fields are missing or unexpected.")
    if payload.get("schema_version") != 1:
        raise ScopeEvaluationError("Expected scope schema_version is unsupported.")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ScopeEvaluationError("Expected scope records must be a non-empty array.")

    expected: dict[str, ScopeStatus] = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != _EXPECTED_RECORD_FIELDS:
            raise ScopeEvaluationError("Expected scope record fields are missing or unexpected.")
        evidence_id = _canonical_string(record.get("evidence_id"), "oracle evidence_id")
        if evidence_id in expected:
            raise ScopeEvaluationError(f"Duplicate oracle evidence_id '{evidence_id}'.")
        tags = record.get("scenario_tags")
        if (
            not isinstance(tags, list)
            or not tags
            or any(not isinstance(tag, str) or not tag for tag in tags)
        ):
            raise ScopeEvaluationError("Oracle scenario_tags must be a non-empty string array.")
        expected[evidence_id] = _parse_status(record.get("expected_status"), "oracle expected_status")
    return expected


def _parse_status(value: Any, label: str) -> ScopeStatus:
    if not isinstance(value, str):
        raise ScopeEvaluationError(f"{label} must be a string.")
    try:
        return ScopeStatus(value)
    except ValueError as exc:
        raise ScopeEvaluationError(f"{label} '{value}' is unsupported.") from exc


def _canonical_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ScopeEvaluationError(f"{label} must be a canonical non-empty string.")
    return value


def _load_json(path: Path, label: str) -> Any:
    try:
        raw_bytes = Path(path).read_bytes()
    except OSError as exc:
        raise ScopeEvaluationError(f"{label} could not be read.") from exc
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScopeEvaluationError(f"{label} is not valid UTF-8.") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScopeEvaluationError(f"{label} is not valid JSON.") from exc
