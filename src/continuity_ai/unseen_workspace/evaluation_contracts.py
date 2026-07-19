"""Strict classification, oracle, metadata, and engine-input proof boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from continuity_ai.unseen_workspace.ingestion import (
    RawWorkspaceIngestionError,
    load_workspace,
)
from continuity_ai.unseen_workspace.models import (
    ClassificationDecision,
    ClassificationResult,
    HumanOverride,
    OracleExposureStatus,
    ProjectReference,
    ScopeStatus,
)
from continuity_ai.unseen_workspace.validation import (
    canonical_nonempty_string,
    load_utf8_json,
    parse_identity_array,
    parse_project_reference,
    parse_scope_status,
    require_exact_object,
)

_RESULT_FIELDS = {
    "schema_version",
    "provider_identity",
    "decisions",
    "human_overrides",
    "approved_scope_evidence_ids",
    "project_report_evidence_ids",
}
_DECISION_FIELDS = {"evidence_id", "status"}
_EXPECTED_FIELDS = {"schema_version", "target_project", "records"}
_EXPECTED_RECORD_FIELDS = {"evidence_id", "expected_status", "scenario_tags"}
_METADATA_FIELDS = {
    "schema_version",
    "generator_version",
    "seed",
    "projects",
    "record_count",
}
_METADATA_PROJECT_FIELDS = {
    "project_id",
    "name",
    "lead",
    "coordinator",
    "location",
    "milestone",
}
_ENGINE_INPUT_ORACLE_MARKERS = (
    b'"expected_status"',
    b'"scenario_tags"',
    b'"seed"',
    b'"oracle"',
    b'"expected_scope"',
)


class ScopeEvaluationError(RuntimeError):
    """Raised when a classification submission or generated oracle is malformed."""


@dataclass(frozen=True)
class ExpectedScope:
    """Validated hidden partition and its target project."""

    target_project: ProjectReference
    statuses: dict[str, ScopeStatus]
    ambiguous_evidence_ids: frozenset[str]


@dataclass(frozen=True)
class RunMetadata:
    """Validated hidden generation identity needed by the proof report."""

    seed: int
    target_project: ProjectReference
    record_count: int


def load_classification_result(path: Path) -> ClassificationResult:
    """Load the strict later-stage submission contract used by proof evaluation."""

    payload = require_exact_object(
        load_utf8_json(path, "Classification result", ScopeEvaluationError),
        _RESULT_FIELDS,
        "Classification result",
        ScopeEvaluationError,
    )
    if payload.get("schema_version") != 1:
        raise ScopeEvaluationError("Classification result schema_version is unsupported.")
    result = ClassificationResult(
        provider_identity=canonical_nonempty_string(
            payload.get("provider_identity"), "provider_identity", ScopeEvaluationError
        ),
        decisions=_parse_decisions(payload.get("decisions")),
        human_overrides=_parse_human_overrides(payload.get("human_overrides")),
        approved_scope_evidence_ids=parse_identity_array(
            payload.get("approved_scope_evidence_ids"),
            "approved_scope_evidence_ids",
            ScopeEvaluationError,
        ),
        project_report_evidence_ids=parse_identity_array(
            payload.get("project_report_evidence_ids"),
            "project_report_evidence_ids",
            ScopeEvaluationError,
        ),
    )
    validate_classification_result(result)
    return result


def validate_classification_result(result: ClassificationResult) -> None:
    """Enforce runtime invariants even for directly constructed typed submissions."""

    if not isinstance(result, ClassificationResult):
        raise ScopeEvaluationError("Submission must be a ClassificationResult.")
    canonical_nonempty_string(
        result.provider_identity, "provider_identity", ScopeEvaluationError
    )
    if not isinstance(result.decisions, tuple):
        raise ScopeEvaluationError("decisions must be a tuple in the typed contract.")
    for decision in result.decisions:
        if not isinstance(decision, ClassificationDecision):
            raise ScopeEvaluationError("Every decision must be a ClassificationDecision.")
        canonical_nonempty_string(
            decision.evidence_id, "decision evidence_id", ScopeEvaluationError
        )
        if not isinstance(decision.status, ScopeStatus):
            raise ScopeEvaluationError("Decision status must be a ScopeStatus.")
    if not isinstance(result.human_overrides, tuple):
        raise ScopeEvaluationError("human_overrides must be a tuple in the typed contract.")
    for override in result.human_overrides:
        if not isinstance(override, HumanOverride):
            raise ScopeEvaluationError("Every human override must be a HumanOverride.")
        canonical_nonempty_string(
            override.evidence_id, "human override evidence_id", ScopeEvaluationError
        )
        if not isinstance(override.status, ScopeStatus) or override.status is ScopeStatus.DEFER:
            raise ScopeEvaluationError("Human overrides must resolve to include or exclude.")
    for label, identities in (
        ("approved_scope_evidence_ids", result.approved_scope_evidence_ids),
        ("project_report_evidence_ids", result.project_report_evidence_ids),
    ):
        if not isinstance(identities, tuple):
            raise ScopeEvaluationError(f"{label} must be a tuple in the typed contract.")
        for identity in identities:
            canonical_nonempty_string(identity, f"{label} item", ScopeEvaluationError)


def load_expected_scope(path: Path) -> ExpectedScope:
    """Load and validate the hidden expected partition."""

    payload = require_exact_object(
        load_utf8_json(path, "Expected scope oracle", ScopeEvaluationError),
        _EXPECTED_FIELDS,
        "Expected scope",
        ScopeEvaluationError,
    )
    if payload.get("schema_version") != 1:
        raise ScopeEvaluationError("Expected scope schema_version is unsupported.")
    target_project = parse_project_reference(
        payload.get("target_project"), "Oracle target project", ScopeEvaluationError
    )
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ScopeEvaluationError("Expected scope records must be a non-empty array.")

    expected: dict[str, ScopeStatus] = {}
    ambiguous_ids: set[str] = set()
    seen_casefolded: set[str] = set()
    for value_item in records:
        item = require_exact_object(
            value_item,
            _EXPECTED_RECORD_FIELDS,
            "Expected scope record",
            ScopeEvaluationError,
        )
        evidence_id = canonical_nonempty_string(
            item.get("evidence_id"), "oracle evidence_id", ScopeEvaluationError
        )
        identity_key = evidence_id.casefold()
        if identity_key in seen_casefolded:
            raise ScopeEvaluationError(f"Duplicate oracle evidence_id '{evidence_id}'.")
        seen_casefolded.add(identity_key)
        tags = item.get("scenario_tags")
        if not isinstance(tags, list) or not tags:
            raise ScopeEvaluationError("Oracle scenario_tags must be a non-empty string array.")
        for tag in tags:
            canonical_nonempty_string(tag, "oracle scenario tag", ScopeEvaluationError)
        expected_status = parse_scope_status(
            item.get("expected_status"), "oracle expected_status", ScopeEvaluationError
        )
        if "ambiguous" in tags:
            if expected_status is not ScopeStatus.DEFER:
                raise ScopeEvaluationError(
                    "Oracle records tagged ambiguous must have expected_status 'defer'."
                )
            ambiguous_ids.add(evidence_id)
        expected[evidence_id] = expected_status
    if len(ambiguous_ids) < 2:
        raise ScopeEvaluationError("Expected scope must identify at least two ambiguous records.")
    return ExpectedScope(
        target_project=target_project,
        statuses=expected,
        ambiguous_evidence_ids=frozenset(ambiguous_ids),
    )


def load_run_metadata(path: Path) -> RunMetadata:
    """Load and cross-validate deterministic run identity metadata."""

    payload = require_exact_object(
        load_utf8_json(path, "Run metadata", ScopeEvaluationError),
        _METADATA_FIELDS,
        "Run metadata",
        ScopeEvaluationError,
    )
    if payload.get("schema_version") != 1:
        raise ScopeEvaluationError("Run metadata schema_version is unsupported.")
    canonical_nonempty_string(
        payload.get("generator_version"), "generator_version", ScopeEvaluationError
    )
    seed = payload.get("seed")
    record_count = payload.get("record_count")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ScopeEvaluationError("Run metadata seed must be an integer.")
    if isinstance(record_count, bool) or not isinstance(record_count, int) or record_count < 1:
        raise ScopeEvaluationError("Run metadata record_count must be a positive integer.")
    projects = payload.get("projects")
    if not isinstance(projects, list) or len(projects) != 3:
        raise ScopeEvaluationError("Run metadata must describe exactly three projects.")

    project_references: list[ProjectReference] = []
    for value_item in projects:
        project = require_exact_object(
            value_item,
            _METADATA_PROJECT_FIELDS,
            "Run metadata project",
            ScopeEvaluationError,
        )
        project_references.append(
            ProjectReference(
                project_id=canonical_nonempty_string(
                    project.get("project_id"), "metadata project_id", ScopeEvaluationError
                ),
                name=canonical_nonempty_string(
                    project.get("name"), "metadata project name", ScopeEvaluationError
                ),
            )
        )
        for field in ("lead", "coordinator", "location", "milestone"):
            canonical_nonempty_string(
                project.get(field), f"metadata project {field}", ScopeEvaluationError
            )
    if len({project.project_id.casefold() for project in project_references}) != 3:
        raise ScopeEvaluationError("Run metadata project_id values must be unique.")
    if len({project.name.casefold() for project in project_references}) != 3:
        raise ScopeEvaluationError("Run metadata project names must be unique.")
    return RunMetadata(
        seed=seed,
        target_project=project_references[0],
        record_count=record_count,
    )


def inspect_engine_input(
    input_root: Path,
) -> tuple[OracleExposureStatus, ProjectReference | None]:
    """Prove the precise oracle-exposure state of the validated engine input tree."""

    try:
        workspace = load_workspace(input_root)
    except RawWorkspaceIngestionError:
        return OracleExposureStatus.INPUT_VALIDATION_FAILED, None
    try:
        for path in sorted(input_root.rglob("*")):
            if path.is_file():
                lowered = path.read_bytes().lower()
                if any(marker in lowered for marker in _ENGINE_INPUT_ORACLE_MARKERS):
                    return (
                        OracleExposureStatus.DETECTED_IN_ENGINE_INPUT,
                        workspace.target_project,
                    )
    except OSError:
        return OracleExposureStatus.INPUT_VALIDATION_FAILED, workspace.target_project
    return OracleExposureStatus.NOT_PRESENT_IN_ENGINE_INPUT, workspace.target_project


def _parse_decisions(value: Any) -> tuple[ClassificationDecision, ...]:
    if not isinstance(value, list):
        raise ScopeEvaluationError("Classification decisions must be an array.")
    parsed: list[ClassificationDecision] = []
    for value_item in value:
        item = require_exact_object(
            value_item,
            _DECISION_FIELDS,
            "Classification decision",
            ScopeEvaluationError,
        )
        parsed.append(
            ClassificationDecision(
                evidence_id=canonical_nonempty_string(
                    item.get("evidence_id"), "decision evidence_id", ScopeEvaluationError
                ),
                status=parse_scope_status(
                    item.get("status"), "decision status", ScopeEvaluationError
                ),
            )
        )
    return tuple(parsed)


def _parse_human_overrides(value: Any) -> tuple[HumanOverride, ...]:
    if not isinstance(value, list):
        raise ScopeEvaluationError("human_overrides must be an array.")
    parsed: list[HumanOverride] = []
    for value_item in value:
        item = require_exact_object(
            value_item,
            _DECISION_FIELDS,
            "Human override",
            ScopeEvaluationError,
        )
        status = parse_scope_status(
            item.get("status"), "human override status", ScopeEvaluationError
        )
        if status is ScopeStatus.DEFER:
            raise ScopeEvaluationError("Human overrides must resolve to include or exclude.")
        parsed.append(
            HumanOverride(
                evidence_id=canonical_nonempty_string(
                    item.get("evidence_id"), "human override evidence_id", ScopeEvaluationError
                ),
                status=status,
            )
        )
    return tuple(parsed)
