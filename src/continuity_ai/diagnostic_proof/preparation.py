"""Deterministic Diagnostic Proof workspace preparation."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from continuity_ai.diagnostic_proof.models import DiagnosticWorkspace
from continuity_ai.unseen_workspace import generate_unseen_workspace
from continuity_ai.unseen_workspace.validation import is_unsafe_link


def prepare_diagnostic_workspace(run_root: Path, seed: int) -> DiagnosticWorkspace:
    """Generate controller-only evaluation data and a standalone engine input."""

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
        generated = generate_unseen_workspace(temporary_root / "evaluation", seed)
        generated_input_root = Path(str(generated["input_root"])).resolve(strict=True)
        engine_root = temporary_root / "engine"
        engine_root.mkdir()
        shutil.copytree(generated_input_root, engine_root / "input")
        if root.exists() or is_unsafe_link(root):
            raise OSError(f"Diagnostic run root appeared during preparation: {root}.")
        temporary_root.replace(root)
    except Exception:
        if temporary_root.exists():
            shutil.rmtree(temporary_root, ignore_errors=True)
        raise

    published_root = root.resolve(strict=True)
    evaluation_root = (published_root / "evaluation").resolve(strict=True)
    generated_input_root = (evaluation_root / "input").resolve(strict=True)
    oracle_root = (evaluation_root / "oracle").resolve(strict=True)
    engine_root = (published_root / "engine").resolve(strict=True)
    input_root = (engine_root / "input").resolve(strict=True)
    if (
        input_root.is_relative_to(evaluation_root)
        or evaluation_root.is_relative_to(input_root)
        or (engine_root / "oracle").exists()
        or is_unsafe_link(engine_root / "oracle")
    ):
        raise RuntimeError("Standalone engine input is not physically isolated from the oracle.")
    return DiagnosticWorkspace(
        evaluation_root=evaluation_root,
        generated_input_root=generated_input_root,
        engine_root=engine_root,
        input_root=input_root,
        oracle_root=oracle_root,
    )
