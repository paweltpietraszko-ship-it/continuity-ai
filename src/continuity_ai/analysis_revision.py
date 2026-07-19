'''Canonical semantic-boundary binding for analysis revision proposals.'''
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from continuity_ai.domain import (
    AnalysisRevisionContextBinding,
    AuthenticatedUserAttestation,
    ReasoningEvidence,
)
from continuity_ai.source_scoping.domain import ApprovedSourceScope
from continuity_ai.source_scoping.serialization import approved_scope_to_payload


CONTEXT_BINDING_SCHEMA_VERSION = '1.0'


def build_analysis_revision_context_binding(
    vault,
    *,
    target_project: str | None,
    source_scoping_status: str,
    approved_source_scope: ApprovedSourceScope | None,
    records: tuple[ReasoningEvidence, ...],
) -> AnalysisRevisionContextBinding:
    '''Bind a proposal to the exact semantic context used for validation.'''
    session = vault.require()
    attestations = tuple(
        AuthenticatedUserAttestation(**payload)
        for payload in vault.payload.get('attestations', [])
    )
    canonical_payload = {
        'schema_version': CONTEXT_BINDING_SCHEMA_VERSION,
        'vault_session': {
            'vault_id': session.vault_id,
            'owner_id': session.owner_id,
            'session_id': session.session_id,
        },
        'target_project': target_project,
        'source_scoping': {
            'status': source_scoping_status,
            'approved_scope': (
                approved_scope_to_payload(approved_source_scope)
                if approved_source_scope is not None
                else None
            ),
        },
        'downstream_evidence': tuple(
            _evidence_binding_payload(record) for record in records
        ),
        'authenticated_attestations': tuple(
            asdict(attestation) for attestation in attestations
        ),
    }
    encoded = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        allow_nan=False,
    ).encode('utf-8')
    return AnalysisRevisionContextBinding(
        schema_version=CONTEXT_BINDING_SCHEMA_VERSION,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )


def _evidence_binding_payload(record: ReasoningEvidence) -> dict[str, str | None]:
    return {
        'evidence_id': record.evidence_id,
        'source_type': record.source_type,
        'author_or_actor': record.author_or_actor,
        'timestamp': record.timestamp,
        'title': record.title,
        'content': record.content,
        'provenance': record.provenance,
        'uri': record.uri,
        'artifact_sha256': record.artifact_sha256,
    }
