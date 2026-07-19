import copy
import json
from types import SimpleNamespace

import pytest

from continuity_ai.bridge import Bridge
from continuity_ai.errors import ProviderError, ValidationError
from continuity_ai.evidence import build_spans, order_evidence
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.openai_provider import OpenAISourceScopingProvider
from continuity_ai.source_scoping.restoration import (
    RESTORATION_INVALID,
    restore_latest_approved_scope,
)
from continuity_ai.source_scoping.review import approve_source_scope
from continuity_ai.source_scoping.serialization import (
    approved_scope_from_payload,
    approved_scope_to_payload,
)
from continuity_ai.source_scoping.service import run_source_scoping
from continuity_ai.vault import Vault


class FalsyAnalysisProvider:
    provider_id = "falsy-analysis-provider"

    def __bool__(self):
        return False


class Responses:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class Client:
    def __init__(self, response):
        self.responses = Responses(response)


def _approved_scope_and_payload(workspace):
    target, records, spans = workspace
    result = run_source_scoping(
        target,
        records,
        spans,
        FakeSourceScopingProvider(),
    )
    overrides = {
        evidence_id: "excluded"
        for evidence_id in result.ambiguous_evidence_ids
    }
    scope = approve_source_scope(result, records, overrides)
    return target, records, scope, approved_scope_to_payload(scope)


def _rebuild_final_partition(payload):
    payload["approved_evidence_ids"] = tuple(
        decision["evidence_id"]
        for decision in payload["reviewed_decisions"]
        if decision["final_status"] == "included"
    )
    payload["excluded_evidence_ids"] = tuple(
        decision["evidence_id"]
        for decision in payload["reviewed_decisions"]
        if decision["final_status"] == "excluded"
    )


def _decision(payload, *, basis=None, model_status=None):
    return next(
        decision
        for decision in payload["reviewed_decisions"]
        if (basis is None or decision["basis"] == basis)
        and (model_status is None or decision["model_status"] == model_status)
    )


def _tamper_override_provenance(payload):
    decision = _decision(payload, model_status="included")
    decision["final_status"] = "excluded"
    decision["user_overridden"] = False
    _rebuild_final_partition(payload)


def test_codex_audit_1_preserves_injection_and_enforces_approved_scope(workspace):
    target, records, _ = workspace
    ordered_records = order_evidence(records)
    injected_records = ordered_records[:2]
    provider = FalsyAnalysisProvider()

    injected_bridge = Bridge(
        provider=provider,
        source_scoping_provider=FakeSourceScopingProvider(),
    )
    injected_bridge.project = target
    injected_bridge.records = injected_records
    injected_bridge.spans = build_spans(injected_records)
    injected_bridge._prepare_analysis_evidence()

    assert injected_bridge.provider is provider
    assert injected_bridge.records is injected_records

    scoped_bridge = Bridge(
        provider=provider,
        source_scoping_provider=FakeSourceScopingProvider(),
    )
    scoped_bridge.project = target
    scoped_bridge.artifact_records = ordered_records
    scoped_bridge.records = ordered_records
    scoped_bridge.spans = build_spans(ordered_records)
    scoped_bridge.source_scoping.classify(target, ordered_records)
    result = scoped_bridge.source_scoping.result
    overrides = {
        evidence_id: "excluded"
        for evidence_id in result.ambiguous_evidence_ids
    }
    scoped_bridge.source_scoping.approve(ordered_records, overrides)
    approved_ids = scoped_bridge.source_scoping.approved_scope.approved_evidence_ids

    scoped_bridge.records = ordered_records
    scoped_bridge._prepare_analysis_evidence()

    assert tuple(record.evidence_id for record in scoped_bridge.records) == approved_ids
    assert len(scoped_bridge.records) < len(ordered_records)


def test_codex_audit_2_rejects_false_human_override_provenance_on_restore(
    tmp_path,
    workspace,
):
    target, records, scope, payload = _approved_scope_and_payload(workspace)
    tampered = copy.deepcopy(payload)
    _tamper_override_provenance(tampered)

    with pytest.raises(ValidationError):
        approved_scope_from_payload(tampered)

    path = tmp_path / "override-provenance.vault"
    vault = Vault(path)
    vault.initialize("Owner", "correct horse battery staple")
    vault.save_approved_source_scope(scope)
    persisted = vault.payload["approved_source_scopes"][-1]
    _tamper_override_provenance(persisted)
    vault.persist()
    vault.lock()
    vault.unlock("correct horse battery staple")

    restoration = restore_latest_approved_scope(
        vault.payload["approved_source_scopes"],
        target,
        records,
    )
    assert restoration.status == RESTORATION_INVALID


def test_codex_audit_3_reapplies_relation_semantics_and_graph_after_restart(
    tmp_path,
    workspace,
):
    target, records, _, payload = _approved_scope_and_payload(workspace)
    evidence_ids = tuple(
        decision["evidence_id"] for decision in payload["reviewed_decisions"]
    )

    tampered_payloads = []
    for basis in ("explicit_target", "explicit_other_project"):
        candidate = copy.deepcopy(payload)
        decision = _decision(candidate, basis=basis)
        decision["related_evidence_ids"] = (
            next(item for item in evidence_ids if item != decision["evidence_id"]),
        )
        tampered_payloads.append(candidate)

    for basis in ("corroborated_context", "corroborated_other_project"):
        candidate = copy.deepcopy(payload)
        _decision(candidate, basis=basis)["related_evidence_ids"] = ()
        tampered_payloads.append(candidate)

    contextual = _decision(payload, basis="corroborated_context")
    valid_related = contextual["related_evidence_ids"][0]
    for relations in (
        ("EV-UNKNOWN",),
        (valid_related, valid_related),
        (contextual["evidence_id"],),
    ):
        candidate = copy.deepcopy(payload)
        _decision(candidate, basis="corroborated_context")[
            "related_evidence_ids"
        ] = relations
        tampered_payloads.append(candidate)

    graph_tampered = copy.deepcopy(payload)
    excluded_id = _decision(graph_tampered, model_status="excluded")["evidence_id"]
    _decision(graph_tampered, basis="corroborated_context")[
        "related_evidence_ids"
    ] = (excluded_id,)
    tampered_payloads.append(graph_tampered)

    for candidate in tampered_payloads:
        with pytest.raises(ValidationError):
            approved_scope_from_payload(candidate)

    path = tmp_path / "relation-semantics.vault"
    vault = Vault(path)
    vault.initialize("Owner", "correct horse battery staple")
    vault.payload["approved_source_scopes"].append(graph_tampered)
    vault.persist()
    vault.lock()
    vault.unlock("correct horse battery staple")

    restoration = restore_latest_approved_scope(
        vault.payload["approved_source_scopes"],
        target,
        records,
    )
    assert restoration.status == RESTORATION_INVALID


def test_codex_audit_4_rejects_executable_openai_output_items(workspace):
    target, records, spans = workspace
    payload = FakeSourceScopingProvider().classify(target, records, spans)

    legitimate_response = SimpleNamespace(
        status="completed",
        refusal=None,
        output=(
            SimpleNamespace(type="reasoning", summary=()),
            SimpleNamespace(
                type="message",
                content=(SimpleNamespace(type="output_text", text="json"),),
            ),
        ),
        output_text=json.dumps(payload),
    )
    legitimate_provider = OpenAISourceScopingProvider(
        Client(legitimate_response),
        model="test-model",
    )
    assert legitimate_provider.classify(target, records, spans) == payload

    for output_type in ("function_call", "tool_call", "unknown_executable"):
        response = SimpleNamespace(
            status="completed",
            refusal=None,
            output=(SimpleNamespace(type=output_type),),
            output_text=json.dumps(payload),
        )
        provider = OpenAISourceScopingProvider(
            Client(response),
            model="test-model",
        )
        with pytest.raises(ProviderError):
            provider.classify(target, records, spans)
