"""The one narrow bridge-facing coordinator for the split-phase Diagnostic
Proof screen: prepare a synthetic unseen workspace -> real Codex Source
Scoping investigation -> human review (no automatic approval) -> confirm
-> approved-only materialization -> same-session report resume -> oracle
regenerated only after the engine finishes -> PASS/FAIL + claims -> an
explicit, separate controlled-tamper check.

This module never rewrites `continuity_ai.diagnostic_proof` (the frozen
core): it only calls the core's existing public functions from a real
Codex controller, in a background thread, so a genuine human decision
(delivered by a later, separate Bridge command) can sit between the
investigation and `run_diagnostic_engine`'s synchronous review callback.

Every response-shaping function here is an explicit allowlist: nothing
from the core's dataclasses (which do carry real local filesystem paths,
e.g. `CompletedDiagnosticRun.input_root`) is ever serialized wholesale.
The unseen-workspace seed and the oracle are never read, computed, or
referenced here at all -- only the frozen core's own already-oracle-blind
outputs (`CompletedDiagnosticRun`, `DiagnosticProofReport`) are read, and
even those are filtered field-by-field before crossing into a Bridge
response.
"""
from __future__ import annotations

import queue
import secrets
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from continuity_ai.codex_session import CodexSessionController, JsonSessionStore
from continuity_ai.diagnostic_proof import (
    CompletedDiagnosticRun,
    DiagnosticEvaluationWorkspace,
    DiagnosticProofReport,
    DiagnosticWorkspace,
    apply_controlled_workspace_tamper,
    evaluate_completed_diagnostic_run,
    prepare_diagnostic_workspace,
    regenerate_diagnostic_evaluation,
    run_diagnostic_engine,
)
from continuity_ai.errors import ProviderError, ValidationError
from continuity_ai.source_scoping.domain import SourceScopingResult

CONTROLLER_STORE_FILENAME = ".continuity_diagnostic_sessions.json"

# Codex operations (investigation, reporting) use the same bound already
# used elsewhere in the vertical flow. The human-review wait is bounded
# separately and generously, since it is genuinely waiting on a person.
_CODEX_TIMEOUT_SECONDS = 300.0
_REVIEW_WAIT_SECONDS = 1800.0

# Claim fields that the frozen core's own dataclasses legitimately compute
# from real local content (the unseen-workspace seed, a real filesystem
# path) but that must never reach the desktop UI. Every other claim field
# is either a PASS/FAIL-relevant boolean, a count, a fingerprint hash, an
# evidence ID, or a Codex session ID -- all already treated as safe to
# display elsewhere in this project (see `RunIdentity`).
_REDACTED_CLAIM_OBSERVED = {
    "UNSEEN_SEED_RECORDED",
    "ENGINE_INPUT_PHYSICALLY_ISOLATED_FROM_ORACLE",
}


class DiagnosticFlowState:
    """In-memory-only, per-Bridge-process diagnostic session. Never
    persisted; a fresh Bridge (including a restarted `bridge_main.py`
    process) always starts at ``phase == "idle"``, so every diagnostic
    command other than ``diagnostic_prepare_workspace`` fails closed until
    a new workspace is prepared again."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        if getattr(self, "_temp_root", None) is not None:
            shutil.rmtree(self._temp_root, ignore_errors=True)
        self.phase: str = "idle"
        self._temp_root: Path | None = None
        self.workspace: DiagnosticWorkspace | None = None
        self.controller: CodexSessionController | None = None
        self.controller_session_id: str | None = None
        self.scoping_result: SourceScopingResult | None = None
        self.completed: CompletedDiagnosticRun | None = None
        self.evaluation: DiagnosticEvaluationWorkspace | None = None
        self.report: DiagnosticProofReport | None = None
        self.tamper_report: DiagnosticProofReport | None = None
        self._run: _EngineRun | None = None


@dataclass
class _EngineRun:
    """One background-thread execution of `run_diagnostic_engine`, split at
    its synchronous `review` callback so a real Bridge command round trip
    can sit between investigation and confirmation."""

    to_ui: "queue.Queue[tuple[str, object]]" = field(default_factory=lambda: queue.Queue(maxsize=1))
    to_engine: "queue.Queue[Mapping[str, str]]" = field(default_factory=lambda: queue.Queue(maxsize=1))
    thread: threading.Thread | None = None


def start_diagnostic_workspace(state: DiagnosticFlowState) -> str:
    """Phase idle -> workspace_ready. Generates a fresh, unpredictable seed
    (never returned) and a fresh temp run root, then publishes only the
    standalone engine input via the frozen core's own preparation function.
    Returns a short, non-reversible fingerprint prefix safe to display."""

    if state.phase != "idle":
        raise ValidationError()

    temp_root = Path(tempfile.mkdtemp(prefix="continuity_diagnostic_"))
    seed = secrets.randbelow(2**31 - 1) + 1
    try:
        workspace = prepare_diagnostic_workspace(temp_root / "run", seed)
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise ValidationError()

    state._temp_root = temp_root
    state.workspace = workspace
    state.phase = "workspace_ready"
    return workspace.generated_input_fingerprint[:12]


def start_diagnostic_scoping(state: DiagnosticFlowState) -> dict[str, Any]:
    """Phase workspace_ready -> awaiting_review. Creates a real Codex
    controller session and runs the frozen engine's investigation step on a
    background thread, blocking this call only until the engine reaches its
    `review` callback (i.e. until Codex's own classification is ready), not
    until the whole engine completes."""

    if state.phase != "workspace_ready" or state.workspace is None or state._temp_root is None:
        raise ValidationError()

    controller = CodexSessionController.with_local_codex(
        JsonSessionStore(state._temp_root / CONTROLLER_STORE_FILENAME)
    )
    run = _EngineRun()
    workspace = state.workspace
    approved_root = state._temp_root / "approved"

    def _review(scoping_result: SourceScopingResult) -> Mapping[str, str]:
        run.to_ui.put(("review", scoping_result))
        try:
            return run.to_engine.get(timeout=_REVIEW_WAIT_SECONDS)
        except queue.Empty as exc:
            raise TimeoutError("Diagnostic human review was never submitted.") from exc

    def _run_engine() -> None:
        try:
            completed = run_diagnostic_engine(
                controller,
                workspace.input_root,
                approved_root,
                _review,
                timeout_seconds=_CODEX_TIMEOUT_SECONDS,
            )
            run.to_ui.put(("done", completed))
        except Exception as exc:  # noqa: BLE001 - fail-closed handoff, never re-raised here
            run.to_ui.put(("error", exc))

    thread = threading.Thread(target=_run_engine, daemon=True)
    run.thread = thread
    state._run = run
    state.controller = controller
    thread.start()

    try:
        kind, payload = run.to_ui.get(timeout=_CODEX_TIMEOUT_SECONDS + 30)
    except queue.Empty:
        state.reset()
        raise ProviderError()

    if kind != "review":
        state.reset()
        raise ProviderError()

    scoping_result = payload
    assert isinstance(scoping_result, SourceScopingResult)
    state.scoping_result = scoping_result
    state.phase = "awaiting_review"
    return _render_decisions(scoping_result)


def confirm_diagnostic_scope(
    state: DiagnosticFlowState, overrides: Mapping[str, str]
) -> dict[str, Any]:
    """Phase awaiting_review -> completed. Requires an explicit
    included/excluded decision for every source Codex classified; nothing
    is ever pre-approved. Only after this human confirmation does the
    engine materialize the approved-only workspace and resume the same
    Codex session to report -- then, only after the engine has fully
    finished, the oracle is regenerated and the run is evaluated."""

    if (
        state.phase != "awaiting_review"
        or state.scoping_result is None
        or state._run is None
        or state.workspace is None
    ):
        raise ValidationError()

    required_ids = {decision.evidence_id for decision in state.scoping_result.decisions}
    if not isinstance(overrides, Mapping):
        raise ValidationError()
    submitted = {str(k): str(v) for k, v in overrides.items()}
    if set(submitted) != required_ids or any(
        value not in {"included", "excluded"} for value in submitted.values()
    ):
        raise ValidationError()

    # Every source above required an explicit human click -- nothing was
    # pre-approved. The frozen core's own oracle evaluator (unseen_workspace
    # proof_claims/evaluator, not part of this Diagnostic Proof Core import
    # and not rewritten here) structurally only accepts a human override for
    # a record Codex itself deferred as ambiguous: forwarding a decision for
    # an already-decided record as an "override" makes that claim -- and so
    # the whole proof -- FAIL, even when the human's choice simply agrees
    # with Codex. So only the ambiguous resolutions cross into the engine's
    # review callback; the human's confirmation of every other decision is
    # still required above, just never submitted as an "override" the core
    # was never designed to accept one for.
    ambiguous_ids = {
        decision.evidence_id
        for decision in state.scoping_result.decisions
        if decision.association_status == "ambiguous"
    }
    engine_overrides = {
        evidence_id: value for evidence_id, value in submitted.items() if evidence_id in ambiguous_ids
    }

    run = state._run
    run.to_engine.put(engine_overrides)
    try:
        kind, payload = run.to_ui.get(timeout=_CODEX_TIMEOUT_SECONDS + 30)
    except queue.Empty:
        state.reset()
        raise ProviderError()

    if kind != "done":
        state.reset()
        raise ProviderError()

    completed = payload
    assert isinstance(completed, CompletedDiagnosticRun)
    try:
        evaluation = regenerate_diagnostic_evaluation(state.workspace, completed)
        report = evaluate_completed_diagnostic_run(completed, evaluation)
    except Exception:
        state.reset()
        raise ProviderError()

    state.completed = completed
    state.evaluation = evaluation
    state.report = report
    state.phase = "completed"
    return _render_report(report)


def run_diagnostic_tamper_check(state: DiagnosticFlowState) -> dict[str, Any]:
    """Phase completed -> tampered. A separate, explicit action: alters one
    already-approved artifact after the PASS proof above, then re-evaluates
    the same completed run against the same regenerated oracle to show the
    expected FAIL. Never overwrites the original PASS report."""

    if (
        state.phase != "completed"
        or state.completed is None
        or state.evaluation is None
    ):
        raise ValidationError()

    try:
        apply_controlled_workspace_tamper(state.completed)
        tamper_report = evaluate_completed_diagnostic_run(state.completed, state.evaluation)
    except Exception:
        raise ValidationError()

    state.tamper_report = tamper_report
    state.phase = "tampered"
    return _render_report(tamper_report)


def reset_diagnostic_state(state: DiagnosticFlowState) -> None:
    state.reset()


def _render_decisions(scoping_result: SourceScopingResult) -> dict[str, Any]:
    return {
        "target_project": scoping_result.target_project,
        "decisions": [
            {
                "evidence_id": decision.evidence_id,
                "association_status": decision.association_status,
                "basis": decision.basis,
                "rationale": decision.rationale,
            }
            for decision in scoping_result.decisions
        ],
    }


def _render_report(report: DiagnosticProofReport) -> dict[str, Any]:
    return {
        "result": report.result.value,
        "codex_session_id": report.codex_session_id,
        "claims": [
            {
                "name": claim.name,
                "status": claim.status.value,
                "observed": (
                    "[redacted]" if claim.name in _REDACTED_CLAIM_OBSERVED else claim.observed
                ),
            }
            for claim in report.claims
        ],
    }
