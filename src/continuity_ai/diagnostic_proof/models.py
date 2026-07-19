"""Immutable contracts crossing Diagnostic Proof Core phase boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from continuity_ai.approved_workspace.contracts import MaterializationReceipt
from continuity_ai.unseen_workspace.models import EvaluationReport, ProofStatus


@dataclass(frozen=True, slots=True)
class DiagnosticWorkspace:
    """Controller state; only standalone ``input_root`` crosses into the engine."""

    run_root: Path
    engine_root: Path
    input_root: Path
    seed: int
    generated_input_fingerprint: str


@dataclass(frozen=True, slots=True)
class DiagnosticEvaluationWorkspace:
    """Fresh post-engine regeneration accepted by the independent evaluator."""

    evaluation_root: Path
    generated_input_root: Path
    oracle_root: Path
    seed: int
    preparation_input_fingerprint: str
    regenerated_input_fingerprint: str
    oracle_absent_before_regeneration: bool


@dataclass(frozen=True, slots=True)
class CompletedDiagnosticRun:
    """Oracle-free evidence emitted only after reporting has completed."""

    input_root: Path
    input_fingerprint: str
    oracle_absent_during_engine_execution: bool
    approved_workspace_root: Path
    controller_session_id: str
    investigation_codex_session_id: str
    reporting_codex_session_id: str
    provider_identity: str
    automatic_decisions: tuple[tuple[str, str], ...]
    human_overrides: tuple[tuple[str, str], ...]
    approved_evidence_ids: tuple[str, ...]
    excluded_evidence_ids: tuple[str, ...]
    evidence_paths: tuple[tuple[str, str], ...]
    reported_relative_paths: tuple[str, ...]
    materialization: MaterializationReceipt


@dataclass(frozen=True, slots=True)
class DiagnosticClaim:
    name: str
    status: ProofStatus
    observed: str
    expected: str


@dataclass(frozen=True, slots=True)
class DiagnosticProofReport:
    """One canonical object rendered as both JSON and Markdown."""

    seed: int
    input_fingerprint: str
    controller_session_id: str
    codex_session_id: str
    claims: tuple[DiagnosticClaim, ...]
    oracle_evaluation: EvaluationReport
    result: ProofStatus

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "seed": self.seed,
            "input_fingerprint": self.input_fingerprint,
            "controller_session_id": self.controller_session_id,
            "codex_session_id": self.codex_session_id,
            "claims": [
                {
                    "name": claim.name,
                    "status": claim.status.value,
                    "observed": claim.observed,
                    "expected": claim.expected,
                }
                for claim in self.claims
            ],
            "oracle_evaluation": self.oracle_evaluation.to_dict(),
            "result": self.result.value,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticProofArtifacts:
    json_path: Path
    markdown_path: Path
