from continuity_ai.bridge import Bridge
from continuity_ai.evidence import build_spans, order_evidence
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider


class AnalysisProvider:
    provider_id = "unused"


class LockableVault:
    payload = {"attestations": []}

    def lock(self):
        self.locked = True


def _bridge(workspace):
    target, records, _ = workspace
    bridge = Bridge(
        provider=AnalysisProvider(),
        source_scoping_provider=FakeSourceScopingProvider(),
    )
    records = order_evidence(records)
    bridge.project = target
    bridge.artifact_records = records
    bridge.records = records
    bridge.spans = build_spans(records)
    return bridge


def _scope_and_confirm(bridge):
    scoped = bridge.handle({"command": "scope_project_sources"})
    ambiguous = scoped["data"]["source_scope"]["ambiguous_evidence_ids"]
    confirmed = bridge.handle(
        {
            "command": "confirm_source_scope",
            "overrides": {
                evidence_id: "excluded" for evidence_id in ambiguous
            },
        }
    )
    return scoped, confirmed


def test_bridge_scope_review_gate_and_handoff(workspace):
    bridge = _bridge(workspace)
    scoped = bridge.handle({"command": "scope_project_sources"})
    assert scoped["ok"] is True
    ambiguous = scoped["data"]["source_scope"]["ambiguous_evidence_ids"]

    blocked = bridge.handle(
        {"command": "analyze_project", "question": "Current state?"}
    )
    assert blocked["ok"] is False
    assert blocked["error"]["code"] == "validation_error"

    confirmed = bridge.handle(
        {
            "command": "confirm_source_scope",
            "overrides": {
                evidence_id: "excluded" for evidence_id in ambiguous
            },
        }
    )
    assert confirmed["ok"] is True
    approved = confirmed["data"]["approved_source_scope"]["approved_evidence_ids"]
    assert tuple(record.evidence_id for record in bridge.records) == tuple(approved)


def test_vault_lock_blocks_analysis_and_project_conversation(workspace):
    bridge = _bridge(workspace)
    _, confirmed = _scope_and_confirm(bridge)
    assert confirmed["ok"] is True
    bridge.vault = LockableVault()

    locked = bridge.handle({"command": "lock_vault"})
    assert locked["ok"] is True
    assert bridge.records == ()

    analyze = bridge.handle(
        {"command": "analyze_project", "question": "Current state?"}
    )
    message = bridge.handle(
        {"command": "send_message", "message": "What is current?"}
    )
    assert analyze["ok"] is False
    assert analyze["error"]["code"] == "validation_error"
    assert message["ok"] is False
    assert message["error"]["code"] == "validation_error"


def test_bridge_rejects_target_project_substitution(workspace):
    bridge = _bridge(workspace)
    response = bridge.handle(
        {
            "command": "scope_project_sources",
            "target_project": "Project Unknown",
        }
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "project_mismatch"


def test_workspace_state_exposes_review_only_after_scoping(workspace):
    bridge = _bridge(workspace)
    initial = bridge.handle({"command": "get_workspace_state"})
    assert "source_scoping_status" not in initial["data"]
    bridge.handle({"command": "scope_project_sources"})
    pending = bridge.handle({"command": "get_workspace_state"})
    assert pending["data"]["source_scoping_status"] == "pending_review"


def test_invalid_restored_scope_clears_visible_retained_analysis(
    monkeypatch, workspace
):
    import continuity_ai.bridge as bridge_module

    target, records, _ = workspace
    bridge = _bridge(workspace)
    bridge.analysis = object()
    bridge.snapshot = object()
    bridge.last_question = "Previous question"

    class InvalidScopeVault:
        payload = {
            "attestations": [],
            "approved_source_scopes": [
                {
                    "schema_version": "1.0",
                    "target_project": target,
                    "approved_evidence_ids": ["invented"],
                }
            ],
        }

        def require(self):
            return object()

    bridge.vault = InvalidScopeVault()
    monkeypatch.setattr(bridge, "_restore_from_vault", lambda clear_project: None)
    monkeypatch.setattr(bridge_module, "ingest_artifacts", lambda root: records)
    monkeypatch.setattr(bridge_module, "read_project_name", lambda root: target)
    monkeypatch.setattr(bridge_module, "artifact_to_reasoning", lambda record: record)

    response = bridge.handle(
        {"command": "load_project", "artifact_root": "unused"}
    )

    assert response["ok"] is True
    assert bridge.source_scoping.status == "invalid"
    assert bridge.records == ()
    assert bridge.analysis is None
    assert bridge.snapshot is None
    assert bridge.last_question is None
