"""Deterministic preparation and post-engine oracle regeneration."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from continuity_ai.codex_process import workspace_fingerprint
from continuity_ai.diagnostic_proof.models import (
    CompletedDiagnosticRun,
    DiagnosticEvaluationWorkspace,
    DiagnosticWorkspace,
)
from continuity_ai.unseen_workspace import generate_unseen_workspace
from continuity_ai.unseen_workspace.validation import is_unsafe_link


def prepare_diagnostic_workspace(run_root: Path, seed: int) -> DiagnosticWorkspace:
    """Publish only standalone input while retaining seed and fingerprint in memory."""

    root = Path(run_root)
    if root.exists() or is_unsafe_link(root):
        raise RuntimeError(f"Diagnostic run root already exists: {root}.")
    if is_unsafe_link(root.parent):
        raise RuntimeError("Diagnostic run root parent must be a real directory.")
    parent = root.parent.resolve(strict=True)
    if not parent.is_dir():
        raise RuntimeError("Diagnostic run root parent must be a real directory.")

    temporary_root = parent / f".{root.name}.tmp-{uuid.uuid4().hex}"
    try:
        temporary_root.mkdir()
        temporary_evaluation_root = temporary_root / "seed-evaluation"
        generated = generate_unseen_workspace(temporary_evaluation_root, seed)
        generated_input_root = Path(str(generated["input_root"])).resolve(strict=True)
        generated_input_fingerprint = workspace_fingerprint(generated_input_root)
        engine_root = temporary_root / "engine"
        engine_root.mkdir()
        shutil.copytree(generated_input_root, engine_root / "input")
        shutil.rmtree(temporary_evaluation_root)
        if temporary_evaluation_root.exists() or is_unsafe_link(temporary_evaluation_root):
            raise OSError("Temporary evaluation tree remains after preparation.")
        if not _oracle_artifacts_absent(temporary_root):
            raise OSError("Oracle artifacts remain after preparation.")
        if root.exists() or is_unsafe_link(root):
            raise OSError(f"Diagnostic run root appeared during preparation: {root}.")
        temporary_root.replace(root)
    except Exception:
        if temporary_root.exists():
            shutil.rmtree(temporary_root, ignore_errors=True)
        raise

    published_root = root.resolve(strict=True)
    engine_root = (published_root / "engine").resolve(strict=True)
    input_root = (engine_root / "input").resolve(strict=True)
    if not _oracle_artifacts_absent(published_root):
        raise RuntimeError("Oracle artifacts remain in the published diagnostic run.")
    if workspace_fingerprint(input_root) != generated_input_fingerprint:
        raise RuntimeError("Standalone input differs from the generated input.")
    return DiagnosticWorkspace(
        run_root=published_root,
        engine_root=engine_root,
        input_root=input_root,
        seed=seed,
        generated_input_fingerprint=generated_input_fingerprint,
    )


def regenerate_diagnostic_evaluation(
    workspace: DiagnosticWorkspace,
    completed: CompletedDiagnosticRun,
) -> DiagnosticEvaluationWorkspace:
    """Regenerate and verify a fresh evaluation tree only after engine completion."""

    if not isinstance(workspace, DiagnosticWorkspace):
        raise RuntimeError("A prepared diagnostic workspace is required.")
    if not isinstance(completed, CompletedDiagnosticRun):
        raise RuntimeError("A completed diagnostic run is required.")
    run_root = workspace.run_root.resolve(strict=True)
    input_root = workspace.input_root.resolve(strict=True)
    if completed.input_root.resolve(strict=True) != input_root:
        raise RuntimeError("Completed run does not belong to the prepared workspace.")
    if not completed.oracle_absent_during_engine_execution:
        raise RuntimeError("Engine execution did not prove oracle absence.")
    if not _oracle_artifacts_absent(run_root):
        raise RuntimeError("Oracle artifacts existed before post-engine regeneration.")

    standalone_fingerprint = workspace_fingerprint(input_root)
    if (
        completed.input_fingerprint != workspace.generated_input_fingerprint
        or standalone_fingerprint != workspace.generated_input_fingerprint
    ):
        raise RuntimeError("Standalone input no longer matches preparation state.")

    evaluation_root = run_root / "evaluation"
    if evaluation_root.exists() or is_unsafe_link(evaluation_root):
        raise RuntimeError(f"Evaluation root already exists: {evaluation_root}.")
    generated = generate_unseen_workspace(evaluation_root, workspace.seed)
    generated_input_root = Path(str(generated["input_root"])).resolve(strict=True)
    oracle_root = Path(str(generated["oracle_root"])).resolve(strict=True)
    regenerated_fingerprint = workspace_fingerprint(generated_input_root)
    if (
        regenerated_fingerprint != workspace.generated_input_fingerprint
        or regenerated_fingerprint != standalone_fingerprint
    ):
        shutil.rmtree(evaluation_root, ignore_errors=True)
        raise RuntimeError("Regenerated input does not match the prepared standalone input.")
    return DiagnosticEvaluationWorkspace(
        evaluation_root=evaluation_root.resolve(strict=True),
        generated_input_root=generated_input_root,
        oracle_root=oracle_root,
        seed=workspace.seed,
        preparation_input_fingerprint=workspace.generated_input_fingerprint,
        regenerated_input_fingerprint=regenerated_fingerprint,
        oracle_absent_before_regeneration=True,
    )


def _oracle_artifacts_absent(run_root: Path) -> bool:
    """Return true only when the run tree contains no oracle directory or payload."""

    root = Path(run_root)
    if not root.exists() or is_unsafe_link(root):
        return False
    try:
        for path in root.rglob("*"):
            name = path.name.casefold()
            if name == "oracle" or name == "expected_scope.json":
                return False
    except OSError:
        return False
    return True
