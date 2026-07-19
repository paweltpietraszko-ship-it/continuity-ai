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
from continuity_ai.domain import AnalysisRevisionContextBinding
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


class MatchingFieldProxy:
    def __init__(self, binding):
        self.schema_version = binding.schema_version
        self.sha256 = binding.sha256


class RecordingEqualityBinding:
    def __init__(self):
        self.called = False

    def __eq__(self, other):
        self.called = True
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


def _assert_invocation_rejected_is_atomic(
    vault,
    proposal,
    invocation,
    *,
    exception_types=(ValidationError,),
):
    payload_before = copy.deepcopy(vault.payload)
    encrypted_before = vault.path.read_bytes()
    with pytest.raises(exception_types):
        invocation()
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


@pytest.mark.parametrize('binding_count', [2, 3])
def test_multiple_binding_arguments_are_rejected_before_mutation(
    tmp_path,
    workspace,
    binding_count,
):
    target, records, _ = workspace
    vault = Vault(tmp_path / f'{binding_count}-bindings.vault')
    vault.initialize('Owner', PASSWORD)
    proposal = _propose(vault, target, records)
    bindings = (proposal.context_binding,) * binding_count
    _assert_invocation_rejected_is_atomic(
        vault,
        proposal,
        lambda: confirm_analysis_revision(
            vault,
            proposal.proposal_id,
            *bindings,
        ),
    )


def test_matching_binding_via_single_item_args_confirms(
    tmp_path,
    workspace,
):
    target, records, _ = workspace
    vault = Vault(tmp_path / 'single-args.vault')
    vault.initialize('Owner', PASSWORD)
    proposal = _propose(vault, target, records)
    args = (proposal.context_binding,)
    confirmed = confirm_analysis_revision(
        vault,
        proposal.proposal_id,
        *args,
    )
    assert confirmed is proposal.candidate
    assert proposal.proposal_id not in vault.pending_revisions


def test_binding_keyword_is_not_a_compatibility_bypass(
    tmp_path,
    workspace,
):
    target, records, _ = workspace
    vault = Vault(tmp_path / 'keyword-binding.vault')
    vault.initialize('Owner', PASSWORD)
    proposal = _propose(vault, target, records)
    _assert_invocation_rejected_is_atomic(
        vault,
        proposal,
        lambda: confirm_analysis_revision(
            vault=vault,
            proposal_id=proposal.proposal_id,
            current_context_binding_values=proposal.context_binding,
        ),
        exception_types=(TypeError,),
    )


def test_matching_field_proxy_and_untrusted_equality_are_rejected(
    tmp_path,
    workspace,
):
    target, records, _ = workspace
    vault = Vault(tmp_path / 'proxy-binding.vault')
    vault.initialize('Owner', PASSWORD)
    proposal = _propose(vault, target, records)
    equality_probe = RecordingEqualityBinding()
    invalid_values = (
        MatchingFieldProxy(proposal.context_binding),
        equality_probe,
    )
    for invalid_value in invalid_values:
        _assert_invocation_rejected_is_atomic(
            vault,
            proposal,
            lambda invalid_value=invalid_value: confirm_analysis_revision(
                vault,
                proposal.proposal_id,
                invalid_value,
            ),
        )
    assert equality_probe.called is False


def test_complete_malformed_supplied_binding_matrix_rejects(
    tmp_path,
    workspace,
):
    target, records, _ = workspace
    vault = Vault(tmp_path / 'malformed-supplied.vault')
    vault.initialize('Owner', PASSWORD)
    proposal = _propose(vault, target, records)
    valid = proposal.context_binding
    invalid_bindings = (
        AnalysisRevisionContextBinding(1, valid.sha256),
        AnalysisRevisionContextBinding(valid.schema_version, b'0' * 64),
        AnalysisRevisionContextBinding(
            valid.schema_version,
            valid.sha256.upper(),
        ),
        AnalysisRevisionContextBinding(
            valid.schema_version,
            valid.sha256[:-1],
        ),
        AnalysisRevisionContextBinding(
            valid.schema_version,
            'g' * 64,
        ),
    )
    for invalid_binding in invalid_bindings:
        _assert_invocation_rejected_is_atomic(
            vault,
            proposal,
            lambda invalid_binding=invalid_binding: confirm_analysis_revision(
                vault,
                proposal.proposal_id,
                invalid_binding,
            ),
        )


def test_complete_malformed_stored_binding_matrix_rejects(
    tmp_path,
    workspace,
):
    target, records, _ = workspace
    vault = Vault(tmp_path / 'malformed-stored.vault')
    vault.initialize('Owner', PASSWORD)
    proposal = _propose(vault, target, records)
    valid = proposal.context_binding
    invalid_bindings = (
        MatchingFieldProxy(valid),
        AnalysisRevisionContextBinding(1, valid.sha256),
        AnalysisRevisionContextBinding(valid.schema_version, b'0' * 64),
        AnalysisRevisionContextBinding(
            valid.schema_version,
            valid.sha256.upper(),
        ),
        AnalysisRevisionContextBinding(
            valid.schema_version,
            valid.sha256[:-1],
        ),
        AnalysisRevisionContextBinding(
            valid.schema_version,
            'g' * 64,
        ),
    )
    for invalid_binding in invalid_bindings:
        malformed = replace(
            proposal,
            context_binding=invalid_binding,
        )
        vault.pending_revisions[proposal.proposal_id] = malformed
        _assert_invocation_rejected_is_atomic(
            vault,
            malformed,
            lambda: confirm_analysis_revision(
                vault,
                proposal.proposal_id,
                valid,
            ),
        )


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
