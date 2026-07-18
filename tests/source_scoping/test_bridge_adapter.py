import copy

import pytest

from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.bridge_adapter import (
    STATUS_APPROVED,
    STATUS_INVALID,
    STATUS_PENDING_REVIEW,
    SourceScopingSession,
)
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.serialization import approved_scope_to_payload


class FakeVault:
    def __init__(self):
        self.payload = {"approved_source_scopes": []}
        self.saved = []

    def require(self):
        return object()

    def save_approved_source_scope(self, scope):
        payload = approved_scope_to_payload(scope)
        self.payload["approved_source_scopes"].append(payload)
        self.saved.append(payload)


def test_pending_review_blocks_downstream_evidence(workspace):
    target, records, _ = workspace
    session = SourceScopingSession(FakeSourceScopingProvider())
    session.classify(target, records)
    assert session.status == STATUS_PENDING_REVIEW
    with pytest.raises(ValidationError):
        session.active_evidence(records)


def test_approval_hands_only_reviewed_included_records_downstream(workspace):
    target, records, _ = workspace
    session = SourceScopingSession(FakeSourceScopingProvider())
    session.classify(target, records)
    overrides = {
        evidence_id: "excluded"
        for evidence_id in session.result.ambiguous_evidence_ids
    }
    session.approve(records, overrides)
    active = session.active_evidence(records)
    assert session.status == STATUS_APPROVED
    assert (
        tuple(record.evidence_id for record in active)
        == session.approved_scope.approved_evidence_ids
    )


def test_approved_scope_persists_and_restores(workspace):
    target, records, _ = workspace
    vault = FakeVault()
    session = SourceScopingSession(FakeSourceScopingProvider())
    session.classify(target, records)
    overrides = {
        evidence_id: "excluded"
        for evidence_id in session.result.ambiguous_evidence_ids
    }
    response = session.approve(records, overrides, vault=vault)
    assert response["persisted"] is True

    restored = SourceScopingSession(FakeSourceScopingProvider())
    restored.restore(target, records, vault)
    assert restored.status == STATUS_APPROVED
    assert restored.approved_scope == session.approved_scope


def test_malformed_newest_scope_does_not_fall_back(workspace):
    target, records, _ = workspace
    vault = FakeVault()
    session = SourceScopingSession(FakeSourceScopingProvider())
    session.classify(target, records)
    overrides = {
        evidence_id: "excluded"
        for evidence_id in session.result.ambiguous_evidence_ids
    }
    session.approve(records, overrides, vault=vault)
    malformed = copy.deepcopy(vault.payload["approved_source_scopes"][-1])
    malformed["approved_evidence_ids"] = ["invented"]
    vault.payload["approved_source_scopes"].append(malformed)

    restored = SourceScopingSession(FakeSourceScopingProvider())
    restored.restore(target, records, vault)
    assert restored.status == STATUS_INVALID
    with pytest.raises(ValidationError):
        restored.active_evidence(records)
