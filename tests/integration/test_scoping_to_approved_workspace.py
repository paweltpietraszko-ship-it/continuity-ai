"""Cross-boundary proof: Source Scoping approval -> Approved-only materialization.

These tests exercise the only glue that connects the two independently
audited tracks (`continuity_ai.integration.source_scope_binding` and
`continuity_ai.integration.approved_workspace_flow`) and prove the invariants
required before either track may be treated as integrated:

* INCLUDE evidence is copied into the approved-only destination.
* EXCLUDE evidence is never copied, even though its file exists on disk.
* A registry entry whose declared hash disagrees with the real file fails
  closed, and no destination workspace is ever published.
* An approved evidence_id missing from the registry fails closed before any
  file is touched.
* The destination workspace is physically separate from the mixed source.
* `compute_source_scope_binding` is a deterministic, pure function of the
  approved scope, and changes if excluded/ambiguous decisions change even
  when the approved (INCLUDE) evidence set stays identical.
* Restoring this Source Scoping track did not remove `unseen_workspace` or
  the reasoning-hardening modules already present on the integration base.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from continuity_ai.approved_workspace.contracts import (
    ApprovedWorkspaceMaterializationError,
    FailureCategory,
    PublicationStatus,
)
from continuity_ai.aurora_fixture import generate_project_aurora_fixture
from continuity_ai.evidence import artifact_to_reasoning, build_spans, order_evidence
from continuity_ai.ingestion import ingest_artifacts, read_project_name
from continuity_ai.integration.approved_workspace_flow import (
    build_approved_workspace_request,
    materialize_approved_scope,
)
from continuity_ai.integration.source_scope_binding import (
    SourceRegistryEntry,
    compute_source_scope_binding,
)
from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.review import approve_source_scope
from continuity_ai.source_scoping.service import run_source_scoping


def _load_project(tmp_path: Path):
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / "fixtures/project_aurora/generated/artifacts"
    raw_records = ingest_artifacts(artifact_root)
    records = order_evidence(tuple(artifact_to_reasoning(r) for r in raw_records))
    spans = build_spans(records)
    target = read_project_name(artifact_root)
    return artifact_root, target, records, spans


def _approve_with_one_exclusion(target, records, spans):
    result = run_source_scoping(target, records, spans, FakeSourceScopingProvider())
    excluded_id = records[0].evidence_id
    overrides = {record.evidence_id: "included" for record in records}
    overrides[excluded_id] = "excluded"
    scope = approve_source_scope(result, records, overrides)
    return scope, excluded_id


def _registry(records, *, tamper_id: str | None = None, omit_id: str | None = None):
    registry = {}
    for record in records:
        if record.evidence_id == omit_id:
            continue
        sha256 = record.artifact_sha256
        if record.evidence_id == tamper_id:
            sha256 = ("0" if sha256[0] != "0" else "1") + sha256[1:]
        registry[record.evidence_id] = SourceRegistryEntry(
            relative_path=record.uri,
            sha256=sha256,
        )
    return registry


def test_include_copied_exclude_absent_and_destination_physically_separate(tmp_path):
    artifact_root, target, records, spans = _load_project(tmp_path)
    scope, excluded_id = _approve_with_one_exclusion(target, records, spans)
    excluded_record = next(r for r in records if r.evidence_id == excluded_id)
    registry = _registry(records)
    destination = tmp_path / "approved_out"

    receipt = materialize_approved_scope(artifact_root, scope, registry, destination)

    assert receipt.publication_status is PublicationStatus.PUBLISHED
    assert receipt.approved_artifact_count == len(scope.approved_evidence_ids)
    assert excluded_id not in scope.approved_evidence_ids

    for evidence_id in scope.approved_evidence_ids:
        source_relative = registry[evidence_id].relative_path
        assert (destination / source_relative).is_file()
        assert (destination / source_relative).read_bytes() == (
            artifact_root / source_relative
        ).read_bytes()

    assert not (destination / excluded_record.uri).exists()
    assert destination.resolve() != artifact_root.resolve()
    assert not destination.is_relative_to(artifact_root.resolve())


def test_ambiguous_and_excluded_never_reach_the_registry_lookup(tmp_path):
    artifact_root, target, records, spans = _load_project(tmp_path)
    scope, excluded_id = _approve_with_one_exclusion(target, records, spans)
    registry = _registry(records, omit_id=excluded_id)
    destination = tmp_path / "approved_out"

    receipt = materialize_approved_scope(artifact_root, scope, registry, destination)

    assert receipt.publication_status is PublicationStatus.PUBLISHED
    assert receipt.approved_artifact_count == len(records) - 1


def test_missing_registry_entry_for_approved_evidence_fails_closed(tmp_path):
    artifact_root, target, records, spans = _load_project(tmp_path)
    scope, excluded_id = _approve_with_one_exclusion(target, records, spans)
    missing_id = next(
        evidence_id
        for evidence_id in scope.approved_evidence_ids
        if evidence_id != excluded_id
    )
    registry = _registry(records, omit_id=missing_id)
    destination = tmp_path / "approved_out"

    with pytest.raises(ValidationError):
        build_approved_workspace_request(artifact_root, scope, registry, destination)

    assert not destination.exists()


def test_registry_hash_disagreeing_with_real_file_fails_closed_no_partial_publish(
    tmp_path,
):
    artifact_root, target, records, spans = _load_project(tmp_path)
    scope, excluded_id = _approve_with_one_exclusion(target, records, spans)
    tampered_id = next(
        evidence_id
        for evidence_id in scope.approved_evidence_ids
        if evidence_id != excluded_id
    )
    registry = _registry(records, tamper_id=tampered_id)
    destination = tmp_path / "approved_out"

    with pytest.raises(ApprovedWorkspaceMaterializationError) as excinfo:
        materialize_approved_scope(artifact_root, scope, registry, destination)

    assert excinfo.value.category is FailureCategory.SOURCE_FINGERPRINT_MISMATCH
    assert not destination.exists()
    assert list(tmp_path.glob(".continuity-approved-stage-*")) == []


def test_binding_is_deterministic_and_changes_with_excluded_decisions(tmp_path):
    artifact_root, target, records, spans = _load_project(tmp_path)
    scope, excluded_id = _approve_with_one_exclusion(target, records, spans)
    registry = _registry(records)

    first = compute_source_scope_binding(scope, registry)
    second = compute_source_scope_binding(scope, registry)
    assert first == second
    assert len(first.binding_sha256) == 64
    assert set(first.expected_source_fingerprints) == {
        registry[evidence_id].sha256 for evidence_id in scope.approved_evidence_ids
    }
    assert registry[excluded_id].sha256 not in first.expected_source_fingerprints

    excluded_decision = next(
        decision
        for decision in scope.reviewed_decisions
        if decision.evidence_id == excluded_id
    )
    mutated_decision = replace(excluded_decision, rationale="A different rationale.")
    mutated_scope = replace(
        scope,
        reviewed_decisions=tuple(
            mutated_decision if decision.evidence_id == excluded_id else decision
            for decision in scope.reviewed_decisions
        ),
    )
    mutated_binding = compute_source_scope_binding(mutated_scope, registry)

    assert mutated_binding.binding_sha256 != first.binding_sha256
    assert mutated_binding.expected_source_fingerprints == first.expected_source_fingerprints


def test_unseen_workspace_and_reasoning_hardening_survive_scoping_integration():
    from continuity_ai import analysis_validation, deterministic_offline_provider, reasoning_contract
    from continuity_ai.unseen_workspace import codex_workspace_spike, generator

    assert analysis_validation.validate_analysis is not None
    assert deterministic_offline_provider.DeterministicOfflineReasoningProvider is not None
    assert reasoning_contract.SUPPORTED_SCHEMA_VERSION == "3.0"
    assert codex_workspace_spike is not None
    assert generator is not None
