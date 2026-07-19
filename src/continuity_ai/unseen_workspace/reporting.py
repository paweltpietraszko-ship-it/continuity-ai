"""Deterministic JSON/Markdown rendering and atomic proof-report persistence."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from continuity_ai.unseen_workspace.models import EvaluationReport
from continuity_ai.unseen_workspace.validation import is_unsafe_link

JSON_REPORT_FILENAME = "report.json"
MARKDOWN_REPORT_FILENAME = "report.md"


class EvaluationReportWriteError(RuntimeError):
    """Raised when equivalent proof artifacts cannot be persisted atomically."""


@dataclass(frozen=True)
class EvaluationReportArtifacts:
    """Paths to the two persisted views of one canonical evaluation report."""

    json_path: Path
    markdown_path: Path


def render_evaluation_json(report: EvaluationReport) -> str:
    """Render the canonical report as stable machine-readable JSON."""

    return json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_evaluation_markdown(report: EvaluationReport) -> str:
    """Render every canonical proof fact as demo-suitable Markdown."""

    lines = [
        "# Unseen Workspace Evaluation Proof",
        "",
        f"MACHINE-EVALUABLE PROOF: **{report.machine_evaluable_proof.value}**",
        "",
        "## Run Identity",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Unseen seed | `{report.unseen_seed}` |",
        f"| Target project | `{_escape(report.target_project.project_id)}` — {_escape(report.target_project.name)} |",
        f"| Provider identity | `{_escape(report.provider_identity)}` |",
        f"| Oracle exposure status | `{report.oracle_exposure_status.value}` |",
        "",
        "## Evaluation Metrics",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Total and classified record count | {report.classified_records} / {report.total_records} |",
        f"| Records classified exactly once | {report.records_classified_exactly_once} / {report.total_records} |",
        f"| Exact partition integrity | `{str(report.exact_partition_integrity).lower()}` |",
        f"| Evidence-reference validity | `{str(report.evidence_reference_validity).lower()}` ({report.valid_evidence_references} / {report.total_evidence_references} valid references) |",
        f"| Unsafe automatic inclusions | {len(report.unsafe_automatic_inclusions)} |",
        f"| Ambiguous records deferred to human review | {report.ambiguous_records_deferred_to_human_review} / {report.total_ambiguous_records} |",
        f"| Human overrides | {len(report.human_overrides)} ({len(report.invalid_human_overrides)} invalid) |",
        f"| Approved scope size | {report.approved_scope_size} |",
        f"| Approved scope integrity | `{str(report.approved_scope_integrity).lower()}` |",
        f"| Declared Project Report references outside approved scope | {len(report.declared_project_report_references_outside_approved_scope)} |",
        f"| Exact oracle status matches | {report.exact_status_matches} / {report.total_records} |",
        "",
        "## Named Proof Claims",
        "",
        "| Claim | Status | Observed | Expected |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| `{claim.name}` | **{claim.status.value}** | {_escape(claim.observed)} | {_escape(claim.expected)} |"
        for claim in report.claims
    )
    lines.extend(
        [
            "",
            "> Boundary: this checkpoint validates only the declared Project Report evidence-reference set against approved scope. It does not inspect or certify Project Report statements, spans, or statement-level citations.",
            "",
            "## Human Overrides",
            "",
        ]
    )
    if report.human_overrides:
        lines.extend(["| Evidence ID | Final status |", "|---|---|"])
        lines.extend(
            f"| `{_escape(override.evidence_id)}` | `{override.status.value}` |"
            for override in report.human_overrides
        )
    else:
        lines.append("No human overrides were submitted.")
    lines.extend(
        [
            "",
            "## Evidence Sets",
            "",
            f"- Invalid evidence references: {_identity_list(report.invalid_evidence_references)}",
            f"- Unsafe automatic inclusions: {_identity_list(report.unsafe_automatic_inclusions)}",
            f"- Ambiguous records not deferred: {_identity_list(report.ambiguous_records_not_deferred)}",
            f"- Invalid human overrides: {_identity_list(report.invalid_human_overrides)}",
            f"- Approved scope evidence IDs: {_identity_list(report.approved_scope_evidence_ids)}",
            f"- Project Report evidence IDs: {_identity_list(report.project_report_evidence_ids)}",
            f"- Declared Project Report references outside approved scope: {_identity_list(report.declared_project_report_references_outside_approved_scope)}",
            "",
        ]
    )
    return "\n".join(lines)


def write_evaluation_reports(
    report: EvaluationReport,
    output_root: Path,
) -> EvaluationReportArtifacts:
    """Atomically persist equivalent JSON and Markdown views of one report."""

    output_root = Path(output_root)
    if output_root.exists() or is_unsafe_link(output_root):
        raise EvaluationReportWriteError(f"Report output root already exists: {output_root}.")
    unresolved_parent = output_root.parent
    if is_unsafe_link(unresolved_parent):
        raise EvaluationReportWriteError("Report output parent must be a real existing directory.")
    parent = unresolved_parent.resolve()
    if not parent.is_dir():
        raise EvaluationReportWriteError("Report output parent must be a real existing directory.")
    temporary_root = parent / f".{output_root.name}.tmp-{uuid.uuid4().hex}"
    try:
        temporary_root.mkdir()
        (temporary_root / JSON_REPORT_FILENAME).write_text(
            render_evaluation_json(report), encoding="utf-8", newline="\n"
        )
        (temporary_root / MARKDOWN_REPORT_FILENAME).write_text(
            render_evaluation_markdown(report), encoding="utf-8", newline="\n"
        )
        temporary_root.replace(output_root)
    except OSError as exc:
        if temporary_root.exists():
            try:
                shutil.rmtree(temporary_root)
            except OSError as cleanup_error:
                errors = ExceptionGroup(
                    "Report writing and temporary-output cleanup both failed.",
                    [exc, cleanup_error],
                )
                raise EvaluationReportWriteError(
                    f"Evaluation report failed and temporary data remains at {temporary_root}."
                ) from errors
        raise EvaluationReportWriteError("Evaluation reports could not be written atomically.") from exc
    return EvaluationReportArtifacts(
        json_path=output_root / JSON_REPORT_FILENAME,
        markdown_path=output_root / MARKDOWN_REPORT_FILENAME,
    )


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _identity_list(values: tuple[str, ...]) -> str:
    if not values:
        return "none"
    return ", ".join(f"`{_escape(value)}`" for value in values)
