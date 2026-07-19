import copy
from dataclasses import replace

import pytest

from continuity_ai.analysis_revision import (
    build_analysis_revision_context_binding,
)
from continuity_ai.aurora_fixture import generate_project_aurora_fixture
from continuity_ai.conversation import (
    confirm_analysis_revision,
    send_message,
)
from continuity_ai.evidence import (
    artifact_to_reasoning,
    attestation_to_reasoning,
    build_spans,
    order_evidence,
)
from continuity_ai.errors import ValidationError
from continuity_ai.ingestion import ingest_artifacts
from continuity_ai.reasoning_pipeline import FakeAuroraProvider
from continuity_ai.vault import Vault


PASSWORD = 'secret'


def _records(tmp_path):
    generate_project_aurora_fixture(tmp_path)
    root = tmp_path / 'fixtures/project_aurora/generated/artifacts'
    return order_evidence(
        tuple(artifact_to_reasoning(record) for record in ingest_artifacts(root))
    )


def _binding(vault, records):
    return build_analysis_revision_context_binding(
        vault,
        target_project='Project Aurora',
        source_scoping_status='none',
        approved_source_scope=None,
        records=records,
    )


def test_binding_is_deterministic_and_covers_content_provenance_and_attestations(
    tmp_path,
):
    vault = Vault(tmp_path / 'vault.bin')
    vault.initialize('Owner', PASSWORD)
    proposal = vault.propose_attestation('Authenticated project fact.')
    attestation = vault.confirm_attestation(proposal.proposal_id)
    records = order_evidence(
        _records(tmp_path) + (attestation_to_reasoning(attestation),)
    )

    expected = _binding(vault, records)
    attestation_payload = vault.payload['attestations'][0]
    vault.payload['attestations'] = [
        dict(reversed(tuple(attestation_payload.items())))
    ]

    assert _binding(vault, tuple(records)) == expected
    assert _binding(
        vault,
        (replace(records[0], content=records[0].content + ' changed'),)
        + records[1:],
    ) != expected
    assert _binding(
        vault,
        (
            replace(
                records[0],
                provenance='authenticated_user_attestation',
            ),
        )
        + records[1:],
    ) != expected

    changed_attestation = dict(attestation_payload)
    changed_attestation['statement'] += ' changed'
    vault.payload['attestations'] = [changed_attestation]
    assert _binding(vault, records) != expected


def test_stale_content_rejection_is_atomic_and_does_not_persist(tmp_path):
    vault = Vault(tmp_path / 'vault.bin')
    vault.initialize('Owner', PASSWORD)
    records = _records(tmp_path)
    spans = build_spans(records)
    candidate = FakeAuroraProvider().analyze(records, spans, 'q')
    response = send_message(
        'Prepare this revision.',
        records,
        spans,
        vault=vault,
        revision_candidate=candidate,
        target_project='Project Aurora',
    )
    proposal = response.analysis_revision_proposal
    changed_records = (
        replace(records[0], content=records[0].content + ' changed'),
    ) + records[1:]
    payload_before = copy.deepcopy(vault.payload)
    encrypted_before = vault.path.read_bytes()

    with pytest.raises(ValidationError):
        confirm_analysis_revision(
            vault,
            proposal.proposal_id,
            _binding(vault, changed_records),
        )

    assert vault.pending_revisions[proposal.proposal_id] is proposal
    assert vault.payload == payload_before
    assert vault.path.read_bytes() == encrypted_before


def test_unchanged_bound_proposal_confirms_and_persists(tmp_path):
    path = tmp_path / 'vault.bin'
    vault = Vault(path)
    vault.initialize('Owner', PASSWORD)
    records = _records(tmp_path)
    spans = build_spans(records)
    candidate = FakeAuroraProvider().analyze(records, spans, 'q')
    response = send_message(
        'Prepare this revision.',
        records,
        spans,
        vault=vault,
        revision_candidate=candidate,
        target_project='Project Aurora',
    )
    proposal = response.analysis_revision_proposal

    confirmed = confirm_analysis_revision(
        vault,
        proposal.proposal_id,
        _binding(vault, records),
    )

    assert confirmed == proposal.candidate
    assert proposal.proposal_id not in vault.pending_revisions
    assert vault.payload['saved_analyses'] == [
        {'proposal_id': proposal.proposal_id}
    ]
    reopened = Vault(path)
    reopened.unlock(PASSWORD)
    assert reopened.payload['saved_analyses'] == vault.payload['saved_analyses']
