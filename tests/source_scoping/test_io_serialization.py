import json
from pathlib import Path

import pytest

from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.review import (
    approve_source_scope,
    select_approved_evidence,
)
from continuity_ai.source_scoping.serialization import (
    approved_scope_from_payload,
    approved_scope_to_payload,
)
from continuity_ai.source_scoping.service import run_source_scoping


def _approved(workspace):
    target, records, spans = workspace
    result = run_source_scoping(
        target, records, spans, FakeSourceScopingProvider()
    )
    overrides = {
        evidence_id: "excluded" for evidence_id in result.ambiguous_evidence_ids
    }
    scope = approve_source_scope(result, records, overrides)
    return records, scope, approved_scope_to_payload(scope)


def test_ground_truth_is_outside_workspace_provider_input():
    root = (
        Path(__file__).parents[2]
        / "fixtures"
        / "source_scoping_mixed_workspace"
    )
    workspace = json.loads((root / "workspace.json").read_text("utf-8"))
    assert "ground_truth" not in json.dumps(workspace).casefold()
    assert (root / "test_only" / "ground_truth.json").is_file()


def test_approved_scope_round_trip_preserves_review_evidence(workspace):
    _, scope, payload = _approved(workspace)
    restored = approved_scope_from_payload(payload)
    assert restored == scope
    assert restored.reviewed_decisions[0].model_rationale
    assert restored.reviewed_decisions[0].span_ids
    assert approved_scope_to_payload(restored) == payload


def test_malformed_persisted_scope_is_rejected(workspace):
    _, _, payload = _approved(workspace)
    payload["approved_evidence_ids"] = (
        *payload["approved_evidence_ids"],
        payload["excluded_evidence_ids"][0],
    )
    with pytest.raises(ValidationError):
        approved_scope_from_payload(payload)


def test_persisted_partition_order_is_authoritative(workspace):
    _, _, payload = _approved(workspace)
    payload["excluded_evidence_ids"] = tuple(
        reversed(payload["excluded_evidence_ids"])
    )
    with pytest.raises(ValidationError):
        approved_scope_from_payload(payload)


def test_persisted_resolved_ids_are_exactly_model_ambiguous(workspace):
    _, _, payload = _approved(workspace)
    payload["user_resolved_evidence_ids"] = payload[
        "user_resolved_evidence_ids"
    ][:-1]
    with pytest.raises(ValidationError):
        approved_scope_from_payload(payload)


def test_persisted_fingerprint_order_matches_reviewed_records(workspace):
    _, _, payload = _approved(workspace)
    payload["evidence_fingerprints"] = tuple(
        reversed(payload["evidence_fingerprints"])
    )
    with pytest.raises(ValidationError):
        approved_scope_from_payload(payload)


def test_persisted_model_status_basis_pair_is_validated(workspace):
    _, _, payload = _approved(workspace)
    payload["reviewed_decisions"][0]["model_basis"] = "explicit_other_project"
    with pytest.raises(ValidationError):
        approved_scope_from_payload(payload)


def test_tampered_persisted_span_is_rejected_against_live_evidence(workspace):
    records, _, payload = _approved(workspace)
    payload["reviewed_decisions"][0]["span_ids"] = ("EV-MIX-001:L999",)
    restored = approved_scope_from_payload(payload)
    with pytest.raises(ValidationError):
        select_approved_evidence(restored, records)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_project", " Project Aurora"),
        ("created_at", "not-a-timestamp"),
    ],
)
def test_noncanonical_scope_metadata_is_rejected(workspace, field, value):
    _, _, payload = _approved(workspace)
    payload[field] = value
    with pytest.raises(ValidationError):
        approved_scope_from_payload(payload)
