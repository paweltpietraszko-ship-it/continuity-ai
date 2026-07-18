import copy

import pytest

from continuity_ai.errors import ValidationError, VaultLockedError
from continuity_ai.source_scoping.bridge_adapter import (
    STATUS_APPROVED,
    STATUS_INVALID,
    STATUS_LOCKED,
    STATUS_PENDING_REVIEW,
    STATUS_RESCOPING_REQUIRED,
    SourceScopingSession,
)
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.serialization import approved_scope_to_payload


class FakeVault:
    def __init__(self):
        self.payload = {"approved_source_scopes": []}
        self.saved = []
        self.locked = False

    def require(self):
        if self.locked:
            raise VaultLockedError()
        return object()

    def save_approved_source_scope(self, scope):
        self.require()
        payload = approved_scope_to_payload(scope)
        self.payload["approved_source_scopes"].append(payload)
        self.saved.append(payload)


def _classified_session(workspace):
    target, records, _ = workspace
    session = SourceScopingSession(FakeSourceScopingProvider())
    session.classify(target, records)
    overrides = {
        evidence_id: "excluded"
        for evidence_id in session.result.ambiguous_evidence_ids
    }
    return target, records, session, overrides


def test_pending_review_blocks_downstream_evidence(workspace):
    _, records, session, _ = _classified_session(workspace)
    assert session.status == STATUS_PENDING_REVIEW
    with pytest.raises(ValidationError):
        session.active_evidence(records)


def test_approval_hands_only_reviewed_included_records_downstream(workspace):
    _, records, session, overrides = _classified_session(workspace)
    session.approve(records, overrides)
    active = session.active_evidence(records)
    assert session.status == STATUS_APPROVED
    assert (
        tuple(record.evidence_id for record in active)
        == session.approved_scope.approved_evidence_ids
    )


def test_approval_with_configured_locked_vault_fails_closed(workspace):
    _, records, session, overrides = _classified_session(workspace)
    vault = FakeVault()
    vault.locked = True
    with pytest.raises(VaultLockedError):
        session.approve(records, overrides, vault=vault)
    assert session.status == STATUS_PENDING_REVIEW
    assert session.approved_scope is None


def test_approved_scope_persists_and_restores_with_model_grounds(workspace):
    target, records, session, overrides = _classified_session(workspace)
    vault = FakeVault()
    session.approve(records, overrides, vault=vault)

    restored = SourceScopingSession(FakeSourceScopingProvider())
    restored.restore(target, records, vault)
    assert restored.status == STATUS_APPROVED
    assert restored.approved_scope == session.approved_scope
    assert restored.approved_scope.reviewed_decisions[0].model_rationale
    assert restored.approved_scope.reviewed_decisions[0].span_ids


def test_lock_preserves_fail_closed_gate_until_valid_restore(workspace):
    target, records, session, overrides = _classified_session(workspace)
    vault = FakeVault()
    session.approve(records, overrides, vault=vault)
    session.lock()
    assert session.status == STATUS_LOCKED
    assert session.approved_scope is None
    with pytest.raises(ValidationError):
        session.active_evidence(records)

    session.after_unlock()
    assert session.status == STATUS_RESCOPING_REQUIRED
    session.restore(target, records, vault)
    assert session.status == STATUS_APPROVED
    assert session.active_evidence(records)


def test_unpersisted_scope_requires_rescoping_after_lock(workspace):
    target, records, session, overrides = _classified_session(workspace)
    session.approve(records, overrides)
    session.lock()
    session.after_unlock()
    session.restore(target, records, FakeVault())
    assert session.status == STATUS_RESCOPING_REQUIRED
    with pytest.raises(ValidationError):
        session.active_evidence(records)


def test_malformed_newest_scope_does_not_fall_back(workspace):
    target, records, session, overrides = _classified_session(workspace)
    vault = FakeVault()
    session.approve(records, overrides, vault=vault)
    malformed = copy.deepcopy(vault.payload["approved_source_scopes"][-1])
    malformed["approved_evidence_ids"] = ["invented"]
    vault.payload["approved_source_scopes"].append(malformed)

    restored = SourceScopingSession(FakeSourceScopingProvider())
    restored.restore(target, records, vault)
    assert restored.status == STATUS_INVALID
    with pytest.raises(ValidationError):
        restored.active_evidence(records)
