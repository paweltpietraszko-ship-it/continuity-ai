"""Deterministic Diagnostic Proof workspace preparation."""

from __future__ import annotations

from pathlib import Path

from continuity_ai.diagnostic_proof.models import DiagnosticWorkspace
from continuity_ai.unseen_workspace import generate_unseen_workspace


def prepare_diagnostic_workspace(run_root: Path, seed: int) -> DiagnosticWorkspace:
    """Generate physically separate input and oracle roots for one seed."""

    generated = generate_unseen_workspace(Path(run_root), seed)
    input_root = Path(str(generated["input_root"])).resolve(strict=True)
    oracle_root = Path(str(generated["oracle_root"])).resolve(strict=True)
    if input_root == oracle_root or input_root.is_relative_to(oracle_root) or oracle_root.is_relative_to(input_root):
        raise RuntimeError("Diagnostic input and oracle roots must be physically separate.")
    return DiagnosticWorkspace(input_root=input_root, oracle_root=oracle_root)
