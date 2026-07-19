import copy
import json
from dataclasses import replace

import pytest

import continuity_ai.vault as vault_module
from continuity_ai.analysis_revision import (
    build_analysis_revision_context_binding,
)
from continuity_ai.bridge import Bridge
from continuity_ai.conversation import (
    confirm_analysis_revision,
    send_message,
)
from continuity_ai.evidence import (
    attestation_to_reasoning,
    build_spans,
    order_evidence,
)
from continuity_ai.errors import ValidationError
from continuity_ai.reasoning_pipeline import (
    FakeDecisionProvenanceProvider,
    validate_analysis,
)
from continuity_ai.source_scoping.fake_provider import (
    FakeSourceScopingProvider,
)
from continuity_ai.source_scoping.review import approve_source_scope
from continuity_ai.source_scoping.service import run_source_scoping
from continuity_ai.vault import Vault


PASSWORD = 'correct horse battery staple'


class ForgedEqualBinding:
    def __eq__(self, other):
        return True


def _candidate(records):
    spans = build_spans(records)
    return FakeDecisionProvenanceProvider().analyze(
        records,
        spans,
        'Candidate',
    )


def _binding(
    vault,
    target,
    records,
    *,
    status='none',
    scope=None,
):
    return build_analysis_revision_context_binding(
        vault,
        target_project=target,
        source_scoping_status=status,
        approved_source_scope=scope,
        records=records,
    )


def _propose(
    vault,
    target,
    records,
    *,
    status='none',
    scope=None,
):
    response = send_message(
        'Prepare this revision.',
        records,
        build_spans(records),
        vault=vault,
        revision_candidate=_candidate(records),
        target_project=target,
        source_scoping_status=status,
        approved_source_scope=scope,
    )
    return response.analysis_revision_proposal


def _assert_rejection_is_atomic(
    vault,
    proposal,
    current_binding,
):
    payload_before = copy.deepcopy(vault.payload)
    encrypted_before = vault.path.read_bytes()
    with pytest.raises(ValidationError):
        confirm_analysis_revision(
            vault,
            proposal.proposal_id,
            current_binding,
        )
    assert vault.pending_revisions[proposal.proposal_id] is proposal
    assert vault.payload == payload_before
    assert vault.path.read_bytes() == encrypted_before


def test_omitted_current_binding_is_rejected_fail_closed(
    tmp_path,
    workspace,
):
    target, records, _ = workspace
    vault = Vault(tmp_path / 'omitted-binding.vault')
    vault.initialize('Owner', PASSWORD)
    proposal = _propose(vault, target, records)
    payload_before = copy.deepcopy(vault.payload)
    encrypted_before = vault.path.read_bytes()

    try:
        confirm_analysis_revision(vault, proposal.proposal_id)
    except ValidationError:
        rejected = True
    else:
        rejected = False

    actual = (
        rejected,
        vault.pending_revisions.get(proposal.proposal_id) is proposal,
        vault.payload == payload_before,
        vault.path.read_bytes() == encrypted_before,
    )
    assert actual == (True, True, True, True)


def test_malformed_equal_binding_cannot_bypass_validation(
    tmp_path,
    workspace,
):
    target, records, _ = workspace
    vault = Vault(tmp_path / 'forged-binding.vault')
    vault.initialize('Owner', PASSWORD)
    proposal = _propose(vault, target, records)
    payload_before = copy.deepcopy(vault.payload)
    encrypted_before = vault.path.read_bytes()

    try:
        confirm_analysis_revision(
            vault,
            proposal.proposal_id,
            ForgedEqualBinding(),
        )
    except ValidationError:
        rejected = True
    else:
        rejected = False

    actual = (
        rejected,
        vault.pending_revisions.get(proposal.proposal_id) is proposal,
        vault.payload == payload_before,
        vault.path.read_bytes() == encrypted_before,
    )
    assert actual == (True, True, True, True)


def test_binding_from_another_context_is_rejected(
    tmp_path,
    workspace,
):
    target, records, _ = workspace
    vault = Vault(tmp_path / 'other-proposal.vault')
    vault.initialize('Owner', PASSWORD)
    first = _propose(vault, target, records)
    changed = (
        replace(records[0], content=records[0].content + ' changed'),
    ) + records[1:]
    second = _propose(vault, target, changed)
    assert first.context_binding != second.context_binding
    _assert_rejection_is_atomic(
        vault,
        first,
        second.context_binding,
    )


def test_session_change_rejects_reinserted_old_proposal(
    tmp_path,
    workspace,
):
    target, records, _ = workspace
    vault = Vault(tmp_path / 'session-change.vault')
    old_session = vault.initialize('Owner', PASSWORD)
    proposal = _propose(vault, target, records)
    vault.unlock(PASSWORD)
    assert vault.session.session_id != old_session.session_id
    vault.pending_revisions[proposal.proposal_id] = proposal
    _assert_rejection_is_atomic(
        vault,
        proposal,
        _binding(vault, target, records),
    )


@pytest.mark.parametrize(
    'field,changed_value',
    [
        ('content', 'changed content'),
        ('provenance', 'authenticated_user_attestation'),
        ('uri', 'changed/location.bin'),
        ('artifact_sha256', 'f' * 64),
        ('title', 'Changed title'),
        ('author_or_actor', 'Changed actor'),
        ('timestamp', '2030-01-01T00:00:00Z'),
        ('source_type', 'changed-type'),
    ],
)
def test_every_downstream_evidence_field_changes_binding(
    tmp_path,
    workspace,
    field,
    changed_value,
):
    target, records, _ = workspace
    vault = Vault(tmp_path / f'{field}.vault')
    vault.initialize('Owner', PASSWORD)
    expected = _binding(vault, target, records)
    changed = (
        replace(records[0], **{field: changed_value}),
    ) + records[1:]
    assert _binding(vault, target, changed) != expected


def test_changed_approved_scope_changes_binding(
    tmp_path,
    workspace,
):
    target, records, spans = workspace
    vault = Vault(tmp_path / 'scope.vault')
    vault.initialize('Owner', PASSWORD)
    result = run_source_scoping(
        target,
        records,
        spans,
        FakeSourceScopingProvider(),
    )
    overrides_a = {
        evidence_id: 'excluded'
        for evidence_id in result.ambiguous_evidence_ids
    }
    scope_a = approve_source_scope(result, records, overrides_a)
    overrides_b = dict(overrides_a)
    overrides_b[result.selected_evidence_ids[0]] = 'excluded'
    scope_b = approve_source_scope(result, records, overrides_b)
    assert scope_a.approved_evidence_ids != scope_b.approved_evidence_ids
    assert _binding(
        vault,
        target,
        records,
        status='approved',
        scope=scope_a,
    ) != _binding(
        vault,
        target,
        records,
        status='approved',
        scope=scope_b,
    )


def test_reordered_attestation_dictionary_keys_do_not_change_binding(
    tmp_path,
    workspace,
):
    target, records, _ = workspace
    vault = Vault(tmp_path / 'key-order.vault')
    vault.initialize('Owner', PASSWORD)
    pending = vault.propose_attestation('Authenticated project fact.')
    attestation = vault.confirm_attestation(pending.proposal_id)
    records = order_evidence(
        records + (attestation_to_reasoning(attestation),)
    )
    expected = _binding(vault, target, records)
    payload = vault.payload['attestations'][0]
    vault.payload['attestations'] = [
        dict(reversed(tuple(payload.items())))
    ]
    assert _binding(vault, target, records) == expected


def test_bridge_persistence_failure_is_atomic_and_hash_is_private(
    tmp_path,
    workspace,
    monkeypatch,
):
    target, records, _ = workspace
    vault = Vault(tmp_path / 'write-failure.vault')
    vault.initialize('Owner', PASSWORD)
    bridge = Bridge(
        provider=object(),
        source_scoping_provider=FakeSourceScopingProvider(),
    )
    bridge.vault = vault
    bridge.project = target
    bridge.artifact_records = records
    bridge.records = records
    bridge.spans = build_spans(records)
    proposed = bridge.handle(
        {
            'command': 'send_message',
            'message': 'Prepare this revision.',
            'revision_candidate': _candidate(records),
        }
    )
    assert proposed['ok'] is True
    proposal_id = proposed['data']['analysis_revision_proposal'][
        'proposal_id'
    ]
    proposal = vault.pending_revisions[proposal_id]
    public_json = json.dumps(proposed, sort_keys=True)
    assert 'context_binding' not in public_json
    assert proposal.context_binding.sha256 not in public_json

    existing_analysis = validate_analysis(
        _candidate(records),
        records,
        bridge.spans,
    )
    bridge.analysis = existing_analysis
    records_before = bridge.records
    spans_before = bridge.spans
    payload_before = copy.deepcopy(vault.payload)
    encrypted_before = vault.path.read_bytes()
    grounded_before = bridge.handle(
        {
            'command': 'send_message',
            'message': 'Project status?',
        }
    )

    def fail_write(path, envelope):
        raise OSError('injected persistence failure')

    monkeypatch.setattr(vault_module, '_write', fail_write)
    confirmation = bridge.handle(
        {
            'command': 'confirm_analysis_revision',
            'proposal_id': proposal_id,
        }
    )
    grounded_after = bridge.handle(
        {
            'command': 'send_message',
            'message': 'Project status?',
        }
    )

    assert confirmation['ok'] is False
    assert vault.pending_revisions[proposal_id] is proposal
    assert vault.payload == payload_before
    assert vault.path.read_bytes() == encrypted_before
    assert bridge.analysis is existing_analysis
    assert bridge.records is records_before
    assert bridge.spans is spans_before
    assert grounded_after['data']['citation_cards'] == grounded_before[
        'data'
    ]['citation_cards']
