import json
from pathlib import Path

import pytest

from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.domain import REVIEWED_SOURCE_DECISION_FIELDS
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.review import approve_source_scope
from continuity_ai.source_scoping.serialization import approved_scope_from_payload, approved_scope_to_payload
from continuity_ai.source_scoping.service import run_source_scoping


def test_ground_truth_is_outside_workspace_provider_input():
    root = Path(__file__).parents[2] / "fixtures" / "source_scoping_mixed_workspace"
    workspace = json.loads((root / "workspace.json").read_text("utf-8"))
    assert "ground_truth" not in json.dumps(workspace).casefold()
    assert (root / "test_only" / "ground_truth.json").is_file()


def test_approved_scope_round_trip(workspace):
    target, records, spans = workspace
    result = run_source_scoping(target, records, spans, FakeSourceScopingProvider())
    overrides = {evidence_id: "excluded" for evidence_id in result.ambiguous_evidence_ids}
    scope = approve_source_scope(result, records, overrides)
    payload = approved_scope_to_payload(scope)
    assert all(
        tuple(decision) == REVIEWED_SOURCE_DECISION_FIELDS
        for decision in payload["reviewed_decisions"]
    )
    assert approved_scope_from_payload(payload) == scope


def test_malformed_persisted_scope_is_rejected(workspace):
    target, records, spans = workspace
    result = run_source_scoping(target, records, spans, FakeSourceScopingProvider())
    overrides = {evidence_id: "excluded" for evidence_id in result.ambiguous_evidence_ids}
    payload = approved_scope_to_payload(approve_source_scope(result, records, overrides))
    payload["approved_evidence_ids"] = (*payload["approved_evidence_ids"], payload["excluded_evidence_ids"][0])
    with pytest.raises(ValidationError):
        approved_scope_from_payload(payload)


def test_persisted_partition_order_is_authoritative(workspace):
    target, records, spans = workspace
    result = run_source_scoping(
        target, records, spans, FakeSourceScopingProvider()
    )
    overrides = {
        evidence_id: "excluded" for evidence_id in result.ambiguous_evidence_ids
    }
    payload = approved_scope_to_payload(
        approve_source_scope(result, records, overrides)
    )
    payload["excluded_evidence_ids"] = tuple(reversed(payload["excluded_evidence_ids"]))
    with pytest.raises(ValidationError):
        approved_scope_from_payload(payload)


def test_persisted_resolved_ids_are_exactly_model_ambiguous(workspace):
    target, records, spans = workspace
    result = run_source_scoping(
        target, records, spans, FakeSourceScopingProvider()
    )
    overrides = {
        evidence_id: "excluded" for evidence_id in result.ambiguous_evidence_ids
    }
    payload = approved_scope_to_payload(
        approve_source_scope(result, records, overrides)
    )
    payload["user_resolved_evidence_ids"] = payload["user_resolved_evidence_ids"][:-1]
    with pytest.raises(ValidationError):
        approved_scope_from_payload(payload)


def test_persisted_fingerprint_order_matches_reviewed_records(workspace):
    target, records, spans = workspace
    result = run_source_scoping(
        target, records, spans, FakeSourceScopingProvider()
    )
    overrides = {
        evidence_id: "excluded" for evidence_id in result.ambiguous_evidence_ids
    }
    payload = approved_scope_to_payload(
        approve_source_scope(result, records, overrides)
    )
    payload["evidence_fingerprints"] = tuple(reversed(payload["evidence_fingerprints"]))
    with pytest.raises(ValidationError):
        approved_scope_from_payload(payload)
