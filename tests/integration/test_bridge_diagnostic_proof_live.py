"""Real local Codex proof of the split-phase Bridge Diagnostic flow end to
end: prepare -> real Source Scoping investigation -> explicit human review
-> confirm -> PASS with the same Codex session id resumed for reporting ->
a separate controlled tamper check -> expected FAIL.

This test may call the explicit `diagnostic_run_scoping` command up to three
times in a row -- exactly the same explicit retry a user clicking the same
button would perform after a real, honest Codex rejection (see
`diagnostic_proof_bridge_flow.py`'s M2 retry-safety design). The production
coordinator itself contains no automatic retry loop; only this test's own
outer loop, mirroring a human, calls the command again.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from continuity_ai.bridge import Bridge

_MAX_EXPLICIT_SCOPING_ATTEMPTS = 3


class _UnusedReasoningProvider:
    """Placeholder so `Bridge()` does not need `CONTINUITY_REASONING_PROVIDER`
    set; the diagnostic flow never consults this provider."""

    provider_id = "unused-in-diagnostic-live-flow"

    def analyze(self, evidence, spans, question):
        raise AssertionError("local reasoning provider invoked during diagnostic flow")


@pytest.mark.live_network
def test_bridge_diagnostic_proof_full_flow_against_real_codex(tmp_path: Path) -> None:
    bridge = Bridge(provider=_UnusedReasoningProvider())

    prepared = bridge.handle({"command": "diagnostic_prepare_workspace"})
    assert prepared["ok"] is True, prepared.get("error")
    assert prepared["data"]["phase"] == "workspace_ready"
    assert isinstance(prepared["data"]["input_fingerprint_prefix"], str)
    assert prepared["data"]["input_fingerprint_prefix"]

    scoping_resp = None
    for attempt in range(1, _MAX_EXPLICIT_SCOPING_ATTEMPTS + 1):
        scoping_resp = bridge.handle({"command": "diagnostic_run_scoping"})
        if scoping_resp["ok"]:
            break
        assert bridge._diagnostic.phase == "workspace_ready", (
            f"attempt {attempt} left the flow in an unexpected phase after a real Codex rejection"
        )

    assert scoping_resp is not None
    assert scoping_resp["ok"] is True, (
        f"real Codex scoping failed on all {_MAX_EXPLICIT_SCOPING_ATTEMPTS} explicit attempts: "
        f"{scoping_resp.get('error')}"
    )
    assert scoping_resp["data"]["phase"] == "awaiting_review"
    decisions = scoping_resp["data"]["decisions"]
    assert decisions

    # Explicit human review: every source gets an explicit decision: agree
    # with Codex's own confident classification, resolve every ambiguous one.
    overrides = {
        decision["evidence_id"]: (
            "included" if decision["association_status"] == "included" else "excluded"
        )
        for decision in decisions
    }

    confirm_resp = bridge.handle({"command": "diagnostic_confirm_scope", "overrides": overrides})
    assert confirm_resp["ok"] is True, confirm_resp.get("error")
    assert confirm_resp["data"]["phase"] == "completed"
    assert confirm_resp["data"]["result"] == "PASS"
    codex_session_id = confirm_resp["data"]["codex_session_id"]
    assert isinstance(codex_session_id, str) and codex_session_id

    claims = {claim["name"]: claim for claim in confirm_resp["data"]["claims"]}
    assert claims["SAME_CODEX_SESSION_ID"]["status"] == "PASS"
    # The same-session claim itself never carries the raw id, even here.
    assert claims["SAME_CODEX_SESSION_ID"]["observed"] == "same retained session"
    assert claims["ORACLE_ABSENT_DURING_ENGINE_EXECUTION"]["status"] == "PASS"

    tamper_resp = bridge.handle({"command": "diagnostic_run_tamper_check"})
    assert tamper_resp["ok"] is True, tamper_resp.get("error")
    assert tamper_resp["data"]["phase"] == "tampered"
    assert tamper_resp["data"]["result"] == "FAIL"

    # The original PASS report is retained untouched alongside the FAIL.
    assert bridge._diagnostic.report is not None
    assert bridge._diagnostic.report.result.value == "PASS"
    assert bridge._diagnostic.tamper_report is not None
    assert bridge._diagnostic.tamper_report.result.value == "FAIL"
