from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.review import approve_source_scope
from continuity_ai.source_scoping.service import run_source_scoping
from continuity_ai.vault import Vault


def test_vault_persists_approved_scope_encrypted(tmp_path, workspace):
    target, records, spans = workspace
    result = run_source_scoping(
        target, records, spans, FakeSourceScopingProvider()
    )
    overrides = {
        evidence_id: "excluded" for evidence_id in result.ambiguous_evidence_ids
    }
    scope = approve_source_scope(result, records, overrides)
    path = tmp_path / "scope.vault"
    vault = Vault(path)
    vault.initialize("Owner", "correct horse battery staple")
    vault.save_approved_source_scope(scope)
    assert vault.payload["approved_source_scopes"][-1]["scope_id"] == scope.scope_id
    assert scope.target_project not in path.read_text("utf-8")

    vault.lock()
    vault.unlock("correct horse battery staple")
    assert vault.payload["approved_source_scopes"][-1]["scope_id"] == scope.scope_id
