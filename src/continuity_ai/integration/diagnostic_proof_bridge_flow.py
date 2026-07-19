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

Thread lifecycle: each scoping attempt gets its own `_EngineRun`, its own
attempt-numbered session-store directory, and its own approved-workspace
destination -- never shared with any other attempt, live or dead. A
background attempt is only ever abandoned by first setting its `cancelled`
event (which the review callback polls and honors even if it only reaches
that callback after the coordinator already gave up) and then performing a
bounded `thread.join`. State (`controller`, `_run`, the temp workspace
root) is only released once that join actually confirms the thread has
exited; if it has not, the run is parked as `_pending_run` and no new
attempt -- and no `reset()`-driven deletion of the temp root -- is allowed
until a later call confirms it has finished.
"""
from __future__ import annotations

import queue
import secrets
import shutil
import tempfile
import threading
import time
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
from continuity_ai.unseen_workspace.models import ProofStatus

CONTROLLER_STORE_FILENAME = ".continuity_diagnostic_sessions.json"

# Codex operations (investigation, reporting) use the same bound already
# used elsewhere in the vertical flow. The human-review wait is bounded
# separately and generously, since it is genuinely waiting on a person. The
# outer bound gives the underlying CodexCliProcessAdapter room to run its
# own timeout-driven process kill first, in the normal case, before this
# coordinator's own fail-closed backstop ever fires. The join bound is how
# long a cancelled attempt's thread gets to actually exit before it is
# parked as a still-live pending run instead of released.
_CODEX_TIMEOUT_SECONDS = 300.0
_REVIEW_WAIT_SECONDS = 1800.0
_OUTER_TIMEOUT_SECONDS = _CODEX_TIMEOUT_SECONDS + 30
_JOIN_TIMEOUT_SECONDS = 15.0
_CANCEL_POLL_SECONDS = 0.5

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


@dataclass
class _EngineRun:
    """One background-thread execution of `run_diagnostic_engine`, split at
    its synchronous `review` callback so a real Bridge command round trip
    can sit between investigation and confirmation. Every attempt gets its
    own instance -- queues, events, and thread are never reused or shared
    across attempts, so a stale attempt's late message has nowhere to land
    that anything still reads."""

    attempt_id: int
    to_ui: "queue.Queue[tuple[str, object]]" = field(default_factory=lambda: queue.Queue(maxsize=1))
    to_engine: "queue.Queue[Mapping[str, str]]" = field(default_factory=lambda: queue.Queue(maxsize=1))
    thread: threading.Thread | None = None
    cancelled: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)

    def publish(self, kind: str, payload: object) -> None:
        """Best-effort handoff to the coordinator: if nobody is listening
        any more (the coordinator already gave up on this attempt), this
        gives up too rather than blocking forever on a full queue."""
        try:
            self.to_ui.put((kind, payload), timeout=5.0)
        except queue.Full:
            pass


class DiagnosticFlowState:
    """In-memory-only, per-Bridge-process diagnostic session. Never
    persisted; a fresh Bridge (including a restarted `bridge_main.py`
    process) always starts at ``phase == "idle"``, so every diagnostic
    command other than ``diagnostic_prepare_workspace`` fails closed until
    a new workspace is prepared again."""

    def __init__(self) -> None:
        self._pending_run: _EngineRun | None = None
        self._attempt_counter = 0
        self._temp_root: Path | None = None
        self.reset()

    def reset(self) -> None:
        _cancel_and_join(getattr(self, "_run", None))
        pending = self._pending_run
        if pending is not None:
            _cancel_and_join(pending)
            if not _run_alive(pending):
                self._pending_run = None

        temp_root = self._temp_root
        run_still_live = _run_alive(getattr(self, "_run", None)) or _run_alive(self._pending_run)
        if temp_root is not None and not run_still_live:
            shutil.rmtree(temp_root, ignore_errors=True)
            self._temp_root = None
        # If a run is still live despite the bounded join above, the temp
        # root is deliberately left in place -- it is only ever released by
        # a later reset()/prepare() call once that run is confirmed dead.

        self.phase: str = "idle"
        self.workspace: DiagnosticWorkspace | None = None
        self.controller: CodexSessionController | None = None
        self.controller_session_id: str | None = None
        self.scoping_result: SourceScopingResult | None = None
        self.completed: CompletedDiagnosticRun | None = None
        self.evaluation: DiagnosticEvaluationWorkspace | None = None
        self.report: DiagnosticProofReport | None = None
        self.tamper_report: DiagnosticProofReport | None = None
        self._run: _EngineRun | None = None


def _run_alive(run: _EngineRun | None) -> bool:
    return run is not None and run.thread is not None and run.thread.is_alive()


def _cancel_and_join(run: _EngineRun | None) -> None:
    """Signal cancellation and wait, bounded, for the attempt's thread to
    actually exit. The review callback polls `cancelled` and fails closed
    as soon as it notices -- including if it only reaches that check after
    this call already returned, since `cancelled` stays set."""
    if run is None or run.thread is None:
        return
    run.cancelled.set()
    if run.thread.is_alive():
        run.thread.join(timeout=_JOIN_TIMEOUT_SECONDS)


def _reap_pending_run(state: DiagnosticFlowState) -> None:
    """Re-check a previously-parked still-live attempt. Clears it once its
    thread is confirmed to have actually exited; otherwise leaves it in
    place so the caller can keep failing closed."""
    pending = state._pending_run
    if pending is None:
        return
    if pending.thread is not None and pending.thread.is_alive():
        pending.thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
    if not _run_alive(pending):
        state._pending_run = None


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
    state._attempt_counter = 0
    state.workspace = workspace
    state.phase = "workspace_ready"
    return workspace.generated_input_fingerprint[:12]


def start_diagnostic_scoping(state: DiagnosticFlowState) -> dict[str, Any]:
    """Phase workspace_ready -> awaiting_review. Creates a real Codex
    controller session, in its own attempt-numbered session-store
    directory, and runs the frozen engine's investigation step on a
    background thread, blocking this call only until the engine reaches its
    `review` callback (i.e. until Codex's own classification is ready), not
    until the whole engine completes.

    Refuses to start a new attempt while a previous one has not been
    confirmed to have actually finished -- this is a real, explicit retry
    the caller must click again, never a hidden loop, and two attempts
    never run concurrently."""

    if state.phase != "workspace_ready" or state.workspace is None or state._temp_root is None:
        raise ValidationError()

    _reap_pending_run(state)
    if state._pending_run is not None:
        raise ValidationError()

    state._attempt_counter += 1
    attempt_id = state._attempt_counter
    attempt_dir = state._temp_root / f"attempt-{attempt_id}"
    attempt_dir.mkdir(parents=True, exist_ok=False)
    approved_root = state._temp_root / f"approved-{attempt_id}"

    controller = CodexSessionController.with_local_codex(
        JsonSessionStore(attempt_dir / CONTROLLER_STORE_FILENAME)
    )
    run = _EngineRun(attempt_id=attempt_id)
    workspace = state.workspace

    def _review(scoping_result: SourceScopingResult) -> Mapping[str, str]:
        if run.cancelled.is_set():
            raise TimeoutError("Diagnostic engine attempt was cancelled.")
        run.publish("review", scoping_result)
        deadline = time.monotonic() + _REVIEW_WAIT_SECONDS
        while True:
            if run.cancelled.is_set():
                raise TimeoutError("Diagnostic engine attempt was cancelled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Diagnostic human review was never submitted.")
            try:
                return run.to_engine.get(timeout=min(remaining, _CANCEL_POLL_SECONDS))
            except queue.Empty:
                continue

    def _run_engine() -> None:
        try:
            completed = run_diagnostic_engine(
                controller,
                workspace.input_root,
                approved_root,
                _review,
                timeout_seconds=_CODEX_TIMEOUT_SECONDS,
            )
            run.publish("done", completed)
        except Exception as exc:  # noqa: BLE001 - fail-closed handoff, never re-raised here
            run.publish("error", exc)
        finally:
            run.finished.set()

    thread = threading.Thread(target=_run_engine, daemon=True)
    run.thread = thread
    state._run = run
    state.controller = controller
    thread.start()

    try:
        kind, payload = run.to_ui.get(timeout=_OUTER_TIMEOUT_SECONDS)
    except queue.Empty:
        _settle_failed_attempt(state, run)
        raise ProviderError()

    if kind != "review":
        _settle_failed_attempt(state, run)
        raise ProviderError()

    scoping_result = payload
    assert isinstance(scoping_result, SourceScopingResult)
    state.scoping_result = scoping_result
    state.phase = "awaiting_review"
    return _render_decisions(scoping_result)


def _settle_failed_attempt(state: DiagnosticFlowState, run: _EngineRun) -> None:
    """A semantic/provider rejection, a process failure, or an outer
    timeout during `diagnostic_run_scoping` -- a real, honest Codex failure,
    not a bug -- always signals cancellation and performs a bounded join
    before releasing anything. The already-prepared, oracle-free workspace
    (`state._temp_root`/`state.workspace`) is never touched here: it stays
    exactly as-is so the user can explicitly click "Run real Codex Source
    Scoping investigation" again -- a genuine new real Codex call, never a
    hidden retry loop or a fallback to any local/OpenAI/deterministic
    provider. If the thread has not actually exited by the time the bounded
    join returns, it is parked as the pending run and no new attempt is
    allowed until it is confirmed to have finished."""
    _cancel_and_join(run)
    state.controller = None
    state._run = None
    state.scoping_result = None
    state.phase = "workspace_ready"
    state._pending_run = run if _run_alive(run) else None


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
    # pre-approved. A click that simply agrees with Codex's own confident
    # (non-ambiguous) classification is a confirmation, not a correction,
    # and is not submitted as an "override" the engine never asked to
    # resolve. But a click that genuinely disagrees with a confident
    # classification is a real human correction and MUST reach the engine:
    # it has to physically move that source in or out of the approved-only
    # workspace, and the diagnostic proof must be free to honestly FAIL when
    # a human overrides a confident decision, exactly like it can already
    # fail on any other integrity claim. Silently dropping a disagreeing
    # click here would make human review decorative.
    decisions_by_id = {decision.evidence_id: decision for decision in state.scoping_result.decisions}
    engine_overrides = {
        evidence_id: value
        for evidence_id, value in submitted.items()
        if decisions_by_id[evidence_id].association_status == "ambiguous"
        or value != decisions_by_id[evidence_id].association_status
    }

    run = state._run
    run.to_engine.put(engine_overrides)
    try:
        kind, payload = run.to_ui.get(timeout=_OUTER_TIMEOUT_SECONDS)
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
        "claims": [_render_claim(claim) for claim in report.claims],
    }


def _render_claim(claim: Any) -> dict[str, Any]:
    # SAME_CODEX_SESSION_ID's own `observed`/`expected` are full Codex
    # session UUIDs (see unseen_workspace/proof_claims.py and
    # diagnostic_proof/evaluator.py's `_diagnostic_claims`, neither rewritten
    # here): a full session id must never reach the screen, not even inside
    # a claims table. The claim's own PASS/FAIL status already proves the
    # "same session" fact; a neutral phrase communicates it without exposing
    # the id.
    if claim.name == "SAME_CODEX_SESSION_ID":
        observed = "same retained session" if claim.status is ProofStatus.PASS else "different session (not shown)"
    elif claim.name in _REDACTED_CLAIM_OBSERVED:
        observed = "[redacted]"
    else:
        observed = claim.observed
    return {"name": claim.name, "status": claim.status.value, "observed": observed}
