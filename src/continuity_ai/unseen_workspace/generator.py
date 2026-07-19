"""Filesystem orchestration for deterministic unseen-workspace generation."""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import uuid
from pathlib import Path
from typing import Any

from continuity_ai.unseen_workspace.scenario_factory import (
    build_semantic_run,
    deterministic_subseed,
)
from continuity_ai.unseen_workspace.validation import is_unsafe_link

GENERATOR_VERSION = "0.1"
SUPPORTED_FORMATS = ("txt", "md", "json")


class UnseenWorkspaceGenerationError(RuntimeError):
    """Raised when a run cannot be generated without overwriting or ambiguity."""


def generate_unseen_workspace(run_root: Path, seed: int) -> dict[str, Any]:
    """Create one deterministic run with physically separate input and oracle roots.

    ``run_root`` must not already exist. The seed is written only to hidden oracle
    metadata, never to the engine-visible input tree.
    """

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise UnseenWorkspaceGenerationError("Seed must be an explicit integer.")
    run_root = Path(run_root)
    if run_root.exists() or is_unsafe_link(run_root):
        raise UnseenWorkspaceGenerationError(f"Run root already exists: {run_root}.")
    unresolved_parent = run_root.parent
    if is_unsafe_link(unresolved_parent):
        raise UnseenWorkspaceGenerationError("Run root parent must be a real existing directory.")
    parent = unresolved_parent.resolve()
    if not parent.is_dir():
        raise UnseenWorkspaceGenerationError("Run root parent must be a real existing directory.")
    temporary_root = parent / f".{run_root.name}.tmp-{uuid.uuid4().hex}"
    try:
        temporary_root.mkdir()
        record_count, target_name = _generate_run(temporary_root, seed)
        if run_root.exists() or is_unsafe_link(run_root):
            raise OSError(f"Run root appeared during generation: {run_root}.")
        temporary_root.replace(run_root)
    except OSError as exc:
        _remove_failed_temporary_run(temporary_root, exc)
        raise UnseenWorkspaceGenerationError(
            "Unseen workspace could not be published atomically."
        ) from exc
    return {
        "run_root": str(run_root),
        "input_root": str(run_root / "input"),
        "oracle_root": str(run_root / "oracle"),
        "record_count": record_count,
        "target_project": target_name,
    }


def _generate_run(run_root: Path, seed: int) -> tuple[int, str]:
    """Write a complete run inside an unpublished temporary root."""

    projects, semantic_records = build_semantic_run(seed)
    layout_rng = random.Random(deterministic_subseed(seed, "layout"))
    scenarios = list(semantic_records)
    layout_rng.shuffle(scenarios)

    input_root = run_root / "input"
    records_root = input_root / "records"
    oracle_root = run_root / "oracle"
    records_root.mkdir(parents=True)
    oracle_root.mkdir(parents=True)

    manifest_records: list[dict[str, str]] = []
    expected_records: list[dict[str, object]] = []
    used_evidence_ids: set[str] = set()
    used_filenames: set[str] = set()
    formats = list(SUPPORTED_FORMATS) * 5
    layout_rng.shuffle(formats)

    for scenario, source_format in zip(scenarios, formats, strict=True):
        evidence_id = _unique_token(layout_rng, "EV-", 64, used_evidence_ids)
        filename_token = _unique_token(layout_rng, "record-", 48, used_filenames)
        filename = f"{filename_token}.{source_format}"
        relative_path = f"records/{filename}"
        raw_bytes = _render_record(source_format, scenario.content)
        (records_root / filename).write_bytes(raw_bytes)
        manifest_records.append(
            {
                "evidence_id": evidence_id,
                "format": source_format,
                "path": relative_path,
                "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            }
        )
        expected_records.append(
            {
                "evidence_id": evidence_id,
                "expected_status": scenario.expected_status.value,
                "scenario_tags": list(scenario.tags),
            }
        )

    target_project = {
        "project_id": projects[0].project_id,
        "name": projects[0].name,
    }
    _write_json(
        input_root / "workspace.json",
        {
            "schema_version": 1,
            "target_project": target_project,
            "records": manifest_records,
        },
    )
    _write_json(
        oracle_root / "expected_scope.json",
        {
            "schema_version": 1,
            "target_project": target_project,
            "records": sorted(expected_records, key=lambda item: str(item["evidence_id"])),
        },
    )
    _write_json(
        oracle_root / "metadata.json",
        {
            "schema_version": 1,
            "generator_version": GENERATOR_VERSION,
            "seed": seed,
            "projects": [
                {
                    "project_id": project.project_id,
                    "name": project.name,
                    "lead": project.lead,
                    "coordinator": project.coordinator,
                    "location": project.location,
                    "milestone": project.milestone,
                }
                for project in projects
            ],
            "record_count": len(manifest_records),
        },
    )
    return len(manifest_records), projects[0].name


def _remove_failed_temporary_run(temporary_root: Path, original_error: OSError) -> None:
    if not temporary_root.exists():
        return
    try:
        shutil.rmtree(temporary_root)
    except OSError as cleanup_error:
        errors = ExceptionGroup(
            "Generation and temporary-run cleanup both failed.",
            [original_error, cleanup_error],
        )
        raise UnseenWorkspaceGenerationError(
            f"Unseen workspace failed and temporary data remains at {temporary_root}."
        ) from errors


def _unique_token(
    rng: random.Random,
    prefix: str,
    bits: int,
    used: set[str],
) -> str:
    while True:
        candidate = f"{prefix}{rng.getrandbits(bits):0{bits // 4}X}"
        key = candidate.casefold()
        if key not in used:
            used.add(key)
            return candidate


def _render_record(source_format: str, content: str) -> bytes:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if source_format == "txt":
        return (normalized + "\n").encode("utf-8")
    if source_format == "md":
        return ("# Workspace Record\n\n" + normalized + "\n").encode("utf-8")
    if source_format == "json":
        return _json_bytes({"schema_version": 1, "content": normalized})
    raise UnseenWorkspaceGenerationError(f"Unsupported generated record format: {source_format}.")


def _write_json(path: Path, payload: object) -> None:
    path.write_bytes(_json_bytes(payload))


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
