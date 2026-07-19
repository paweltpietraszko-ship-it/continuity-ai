"""Cross-boundary proof: Source Scoping approval -> Approved-only materialization.

These tests exercise the only glue that connects the two independently
audited tracks (`continuity_ai.integration.source_scope_binding` and
`continuity_ai.integration.approved_workspace_flow`) and prove the invariants
required before either track may be treated as integrated:

* INCLUDE evidence is copied into the approved-only destination.
* EXCLUDE evidence is never copied, even though its file exists on disk.
* A `source_registry` is only trusted once it has been proven to describe the
  exact evidence snapshot the scope was approved against: a stale scope
  (content changed, a record added/removed/reordered), or a registry entry
  whose hash disagrees with the approved record's own `artifact_sha256` —
  even when that hash is a genuinely real hash of a *different* file — fails
  closed before any byte is staged.
* An approved evidence_id missing from the registry fails closed before any
  file is touched.
* The destination workspace is physically separate from the mixed source.
* `compute_source_scope_binding` is a deterministic, pure function of the
  approved scope (and the validated snapshot/registry), and changes if
  excluded/ambiguous decisions change even when the approved (INCLUDE)
  evidence set stays identical.
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
from continuity_ai.errors import ValidationError
from continuity_ai.evidence import artifact_to_reasoning, build_spans, order_evidence
from continuity_ai.ingestion import ingest_artifacts, read_project_name
from continuity_ai.integration.approved_workspace_flow import (
    build_approved_workspace_request,
    materialize_approved_scope,
)
from continuity_ai.integration.source_scope_binding import (
    SourceRegistryEntry,
    compute_source_scope_binding,
    resolve_approved_registry_entries,
)
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

    receipt = materialize_approved_scope(
        artifact_root, scope, records, registry, destination
    )

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

    receipt = materialize_approved_scope(
        artifact_root, scope, records, registry, destination
    )

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
        build_approved_workspace_request(
            artifact_root, scope, records, registry, destination
        )

    assert not destination.exists()


def test_registry_hash_disagreeing_with_approved_record_fails_closed(tmp_path):
    """A registry entry whose declared hash disagrees with the approved
    evidence record's own `artifact_sha256` (e.g. bit-flipped) is now caught
    by `resolve_approved_registry_entries` itself, before the materializer
    (or any file I/O) is ever reached."""
    artifact_root, target, records, spans = _load_project(tmp_path)
    scope, excluded_id = _approve_with_one_exclusion(target, records, spans)
    tampered_id = next(
        evidence_id
        for evidence_id in scope.approved_evidence_ids
        if evidence_id != excluded_id
    )
    registry = _registry(records, tamper_id=tampered_id)
    destination = tmp_path / "approved_out"

    with pytest.raises(ValidationError):
        materialize_approved_scope(artifact_root, scope, records, registry, destination)

    assert not destination.exists()
    assert list(tmp_path.glob(".continuity-approved-stage-*")) == []


def test_source_file_mutated_after_approval_fails_closed_no_partial_publish(tmp_path):
    """The registry entry still agrees with the approved record's
    `artifact_sha256` (so `resolve_approved_registry_entries` accepts it), but
    the real file on disk was mutated after ingestion. Only the Approved-only
    materializer's own byte-for-byte re-hash during copy can catch this, and
    it must still fail closed with no destination ever published."""
    artifact_root, target, records, spans = _load_project(tmp_path)
    scope, excluded_id = _approve_with_one_exclusion(target, records, spans)
    tampered_id = next(
        evidence_id
        for evidence_id in scope.approved_evidence_ids
        if evidence_id != excluded_id
    )
    registry = _registry(records)
    tampered_path = artifact_root / registry[tampered_id].relative_path
    tampered_path.write_bytes(tampered_path.read_bytes() + b"mutated after approval")
    destination = tmp_path / "approved_out"

    with pytest.raises(ApprovedWorkspaceMaterializationError) as excinfo:
        materialize_approved_scope(artifact_root, scope, records, registry, destination)

    assert excinfo.value.category is FailureCategory.SOURCE_FINGERPRINT_MISMATCH
    assert not destination.exists()
    assert list(tmp_path.glob(".continuity-approved-stage-*")) == []


def test_registry_hash_matching_a_different_real_file_fails_closed(tmp_path):
    """A registry entry can declare a hash that is a genuinely real SHA-256 of
    *some* file on disk — just not the file the scope actually approved for
    that evidence_id (e.g. two approved evidence_ids' registry entries were
    swapped). The materializer alone would happily accept this, since it only
    re-hashes whatever `source_relative_path`/`expected_sha256` pair it is
    given. `resolve_approved_registry_entries` must reject it before that,
    by requiring the registry hash to equal the *approved* record's own
    `artifact_sha256`."""
    artifact_root, target, records, spans = _load_project(tmp_path)
    scope, excluded_id = _approve_with_one_exclusion(target, records, spans)
    approved_ids = [
        evidence_id
        for evidence_id in scope.approved_evidence_ids
        if evidence_id != excluded_id
    ]
    assert len(approved_ids) >= 2
    id_a, id_b = approved_ids[0], approved_ids[1]
    record_a = next(r for r in records if r.evidence_id == id_a)
    record_b = next(r for r in records if r.evidence_id == id_b)
    assert record_a.artifact_sha256 != record_b.artifact_sha256

    registry = _registry(records)
    registry[id_a] = SourceRegistryEntry(
        relative_path=record_b.uri,
        sha256=record_b.artifact_sha256,
    )
    destination = tmp_path / "approved_out"

    with pytest.raises(ValidationError):
        build_approved_workspace_request(
            artifact_root, scope, records, registry, destination
        )
    with pytest.raises(ValidationError):
        compute_source_scope_binding(scope, records, registry)

    assert not destination.exists()


def test_stale_scope_after_evidence_content_change_fails_closed(tmp_path):
    artifact_root, target, records, spans = _load_project(tmp_path)
    scope, excluded_id = _approve_with_one_exclusion(target, records, spans)
    approved_id = next(
        evidence_id
        for evidence_id in scope.approved_evidence_ids
        if evidence_id != excluded_id
    )
    changed_records = tuple(
        replace(record, content=record.content + " changed after approval")
        if record.evidence_id == approved_id
        else record
        for record in records
    )
    registry = _registry(records)
    destination = tmp_path / "approved_out"

    with pytest.raises(ValidationError):
        build_approved_workspace_request(
            artifact_root, scope, changed_records, registry, destination
        )
    with pytest.raises(ValidationError):
        compute_source_scope_binding(scope, changed_records, registry)
    with pytest.raises(ValidationError):
        materialize_approved_scope(
            artifact_root, scope, changed_records, registry, destination
        )

    assert not destination.exists()


def test_added_removed_or_reordered_evidence_fails_closed(tmp_path):
    artifact_root, target, records, spans = _load_project(tmp_path)
    scope, excluded_id = _approve_with_one_exclusion(target, records, spans)
    registry = _registry(records)
    destination = tmp_path / "approved_out"

    removed_evidence = records[1:]
    reordered_evidence = (records[1], records[0]) + records[2:]
    extra_record = replace(
        records[0],
        evidence_id=records[0].evidence_id + "-DUPLICATE",
    )
    added_evidence = records + (extra_record,)

    for label, tampered_evidence in (
        ("removed", removed_evidence),
        ("reordered", reordered_evidence),
        ("added", added_evidence),
    ):
        with pytest.raises(ValidationError):
            resolve_approved_registry_entries(scope, tampered_evidence, registry)
        with pytest.raises(ValidationError):
            build_approved_workspace_request(
                artifact_root, scope, tampered_evidence, registry, destination
            )
        assert not destination.exists(), label


def test_binding_is_deterministic_and_changes_with_excluded_decisions(tmp_path):
    artifact_root, target, records, spans = _load_project(tmp_path)
    scope, excluded_id = _approve_with_one_exclusion(target, records, spans)
    registry = _registry(records)

    first = compute_source_scope_binding(scope, records, registry)
    second = compute_source_scope_binding(scope, records, registry)
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
    mutated_binding = compute_source_scope_binding(mutated_scope, records, registry)

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
