"""Independent, post-completion oracle evaluation and proof rendering."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path, PurePosixPath

from continuity_ai.approved_workspace.materializer import (
    APPROVED_MANIFEST_RELATIVE_PATH,
    compute_workspace_fingerprint,
)
from continuity_ai.codex_process import workspace_fingerprint
from continuity_ai.diagnostic_proof.models import (
    CompletedDiagnosticRun,
    DiagnosticClaim,
    DiagnosticProofArtifacts,
    DiagnosticProofReport,
)
from continuity_ai.unseen_workspace.evaluation_contracts import load_run_metadata
from continuity_ai.unseen_workspace.evaluator import evaluate_generated_run
from continuity_ai.unseen_workspace.models import (
    ClassificationDecision,
    ClassificationResult,
    HumanOverride,
    ProofStatus,
    ScopeStatus,
)
from continuity_ai.unseen_workspace.validation import is_unsafe_link


class DiagnosticEvaluationError(RuntimeError):
    """Raised when phase boundaries or proof artifacts are malformed."""


def evaluate_completed_diagnostic_run(
    completed: CompletedDiagnosticRun,
    oracle_root: Path,
) -> DiagnosticProofReport:
    """Evaluate a completed engine run; oracle access begins only here."""

    if not isinstance(completed, CompletedDiagnosticRun):
        raise DiagnosticEvaluationError("A completed diagnostic run is required.")
    oracle = Path(oracle_root).resolve(strict=True)
    input_root = completed.input_root.resolve(strict=True)
    evaluation_root = oracle.parent.resolve(strict=True)
    generated_input_root = (evaluation_root / "input").resolve(strict=True)
    if (
        oracle.name != "oracle"
        or input_root.name != "input"
        or generated_input_root.name != "input"
        or generated_input_root.parent != oracle.parent
        or oracle == input_root
        or oracle.is_relative_to(input_root)
        or input_root.is_relative_to(oracle)
        or input_root.is_relative_to(evaluation_root)
        or evaluation_root.is_relative_to(input_root)
        or (input_root.parent / "oracle").exists()
        or is_unsafe_link(input_root.parent / "oracle")
    ):
        raise DiagnosticEvaluationError(
            "Standalone engine input is not physically isolated from the oracle."
        )

    submission = _classification_submission(completed)
    oracle_evaluation = evaluate_generated_run(evaluation_root, submission)
    metadata = load_run_metadata(oracle / "metadata.json")
    diagnostic_claims = _diagnostic_claims(completed, oracle)
    oracle_claims = tuple(
        DiagnosticClaim(claim.name, claim.status, claim.observed, claim.expected)
        for claim in oracle_evaluation.claims
    )
    claims = diagnostic_claims + oracle_claims
    result = (
        ProofStatus.PASS
        if oracle_evaluation.machine_evaluable_proof is ProofStatus.PASS
        and all(claim.status is ProofStatus.PASS for claim in diagnostic_claims)
        else ProofStatus.FAIL
    )
    return DiagnosticProofReport(
        seed=metadata.seed,
        input_fingerprint=completed.input_fingerprint,
        controller_session_id=completed.controller_session_id,
        codex_session_id=completed.investigation_codex_session_id,
        claims=claims,
        oracle_evaluation=oracle_evaluation,
        result=result,
    )


def apply_controlled_workspace_tamper(completed: CompletedDiagnosticRun) -> Path:
    """Deliberately alter one approved artifact after completion for a FAIL demo."""

    path_by_id = dict(completed.evidence_paths)
    if not completed.approved_evidence_ids:
        raise DiagnosticEvaluationError("Controlled tamper requires an approved artifact.")
    relative_path = path_by_id[completed.approved_evidence_ids[0]]
    target = completed.approved_workspace_root.joinpath(*PurePosixPath(relative_path).parts)
    target.write_bytes(target.read_bytes() + b"\nCONTROLLED-DIAGNOSTIC-TAMPER\n")
    return target


def render_diagnostic_json(report: DiagnosticProofReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_diagnostic_markdown(report: DiagnosticProofReport) -> str:
    lines = [
        "# Diagnostic Proof Core Report",
        "",
        f"DIAGNOSTIC PROOF: **{report.result.value}**",
        "",
        "## Run Identity",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Seed | `{report.seed}` |",
        f"| Input fingerprint | `{report.input_fingerprint}` |",
        f"| Controller ID | `{report.controller_session_id}` |",
        f"| Codex ID | `{report.codex_session_id}` |",
        "",
        "## Claims",
        "",
        "| Claim | Status | Observed | Expected |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| `{claim.name}` | **{claim.status.value}** | {_escape(claim.observed)} | {_escape(claim.expected)} |"
        for claim in report.claims
    )
    lines.append("")
    return "\n".join(lines)


def write_diagnostic_reports(
    report: DiagnosticProofReport, output_root: Path
) -> DiagnosticProofArtifacts:
    root = Path(output_root)
    if root.exists() or is_unsafe_link(root):
        raise DiagnosticEvaluationError(f"Proof output root already exists: {root}.")
    if is_unsafe_link(root.parent):
        raise DiagnosticEvaluationError('Proof output parent must be a real directory.')
    parent = root.parent.resolve(strict=True)
    if not parent.is_dir():
        raise DiagnosticEvaluationError('Proof output parent must be a real directory.')
    temporary = parent / f".{root.name}.tmp-{uuid.uuid4().hex}"
    try:
        temporary.mkdir()
        (temporary / "report.json").write_text(
            render_diagnostic_json(report), encoding="utf-8", newline="\n"
        )
        (temporary / "report.md").write_text(
            render_diagnostic_markdown(report), encoding="utf-8", newline="\n"
        )
        temporary.replace(root)
    except OSError as exc:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        raise DiagnosticEvaluationError("Diagnostic proof reports could not be written.") from exc
    return DiagnosticProofArtifacts(root / "report.json", root / "report.md")


def _classification_submission(completed: CompletedDiagnosticRun) -> ClassificationResult:
    status_map = {
        "included": ScopeStatus.INCLUDE,
        "excluded": ScopeStatus.EXCLUDE,
        "ambiguous": ScopeStatus.DEFER,
    }
    final_status_map = {
        "included": ScopeStatus.INCLUDE,
        "excluded": ScopeStatus.EXCLUDE,
    }
    path_to_id = {path: evidence_id for evidence_id, path in completed.evidence_paths}
    reported_ids = tuple(
        path_to_id[path]
        for path in completed.reported_relative_paths
        if path in path_to_id
    )
    try:
        return ClassificationResult(
            provider_identity=completed.provider_identity,
            decisions=tuple(
                ClassificationDecision(evidence_id, status_map[status])
                for evidence_id, status in completed.automatic_decisions
            ),
            human_overrides=tuple(
                HumanOverride(evidence_id, final_status_map[status])
                for evidence_id, status in completed.human_overrides
            ),
            approved_scope_evidence_ids=completed.approved_evidence_ids,
            project_report_evidence_ids=reported_ids,
        )
    except KeyError as exc:
        raise DiagnosticEvaluationError("Completed run contains an unsupported scope status.") from exc


def _diagnostic_claims(
    completed: CompletedDiagnosticRun, oracle_root: Path
) -> tuple[DiagnosticClaim, ...]:
    evaluation_root = oracle_root.parent
    generated_input_root = evaluation_root / "input"
    try:
        input_unchanged = (
            workspace_fingerprint(completed.input_root) == completed.input_fingerprint
        )
    except Exception:
        input_unchanged = False
    same_codex = (
        completed.investigation_codex_session_id
        == completed.reporting_codex_session_id
    )
    approved_fingerprint_ok = False
    try:
        approved_fingerprint_ok = (
            compute_workspace_fingerprint(completed.approved_workspace_root)
            == completed.materialization.final_workspace_fingerprint
        )
    except Exception:
        approved_fingerprint_ok = False

    manifest_ids, manifest_paths, manifest_files_valid = _approved_manifest_state(completed)
    approved_ids = tuple(completed.approved_evidence_ids)
    exact_partition = (
        manifest_files_valid
        and len(manifest_ids) == len(set(manifest_ids))
        and set(manifest_ids) == set(approved_ids)
    )
    excluded_absent = not set(completed.excluded_evidence_ids).intersection(manifest_ids)
    expected_report_paths = tuple(sorted(manifest_paths))
    observed_report_paths = completed.reported_relative_paths
    report_exact = (
        len(observed_report_paths) == len(set(observed_report_paths))
        and tuple(sorted(observed_report_paths)) == expected_report_paths
    )
    engine_input_parent_oracle = completed.input_root.parent / "oracle"
    isolated = (
        not completed.input_root.is_relative_to(evaluation_root)
        and not evaluation_root.is_relative_to(completed.input_root)
        and not engine_input_parent_oracle.exists()
        and not is_unsafe_link(engine_input_parent_oracle)
    )
    try:
        input_matches_generated = (
            workspace_fingerprint(completed.input_root)
            == workspace_fingerprint(generated_input_root)
        )
    except Exception:
        input_matches_generated = False
    return (
        _claim("INPUT_FINGERPRINT_UNCHANGED", input_unchanged, completed.input_fingerprint, "unchanged"),
        _claim("ENGINE_INPUT_PHYSICALLY_ISOLATED_FROM_ORACLE", isolated, str(completed.input_root), "outside evaluation root with no ../oracle"),
        _claim("ENGINE_INPUT_MATCHES_GENERATED_INPUT", input_matches_generated, str(input_matches_generated).lower(), "true"),
        _claim("SAME_CODEX_SESSION_ID", same_codex, completed.reporting_codex_session_id, completed.investigation_codex_session_id),
        _claim("APPROVED_WORKSPACE_FINGERPRINT_MATCH", approved_fingerprint_ok, str(approved_fingerprint_ok).lower(), "true"),
        _claim("APPROVED_WORKSPACE_EXACT_PARTITION", exact_partition, ", ".join(manifest_ids), ", ".join(approved_ids)),
        _claim("EXCLUDED_OUTSIDE_APPROVED_WORKSPACE", excluded_absent, str(excluded_absent).lower(), "true"),
        _claim("PROJECT_REPORT_PATHS_MATCH_APPROVED_SCOPE", report_exact, ", ".join(observed_report_paths), ", ".join(expected_report_paths)),
    )


def _approved_manifest_state(
    completed: CompletedDiagnosticRun,
) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    root = completed.approved_workspace_root
    try:
        payload = json.loads((root / APPROVED_MANIFEST_RELATIVE_PATH).read_text(encoding="utf-8"))
        entries = payload["approved_artifacts"]
        manifest_ids = tuple(entry["evidence_id"] for entry in entries)
        manifest_paths = tuple(entry["relative_path"] for entry in entries)
        expected_files = set(manifest_paths)
        actual_files = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.parts[len(root.parts)] != ".continuity"
        }
        hashes_valid = all(
            hashlib.sha256(
                root.joinpath(*PurePosixPath(entry["relative_path"]).parts).read_bytes()
            ).hexdigest()
            == entry["sha256"]
            for entry in entries
        )
        return manifest_ids, manifest_paths, actual_files == expected_files and hashes_valid
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return (), (), False


def _claim(name: str, passed: bool, observed: str, expected: str) -> DiagnosticClaim:
    return DiagnosticClaim(
        name=name,
        status=ProofStatus.PASS if passed else ProofStatus.FAIL,
        observed=observed,
        expected=expected,
    )


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
