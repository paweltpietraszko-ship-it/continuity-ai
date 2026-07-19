"""Command line interface for Continuity AI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from continuity_ai.aurora_fixture import generate_project_aurora_fixture, manifest
from continuity_ai.unseen_workspace import (
    evaluate_generated_run,
    generate_unseen_workspace,
    load_classification_result,
    render_evaluation_markdown,
    write_evaluation_reports,
)


def main() -> None:
    """Run the Continuity AI command line interface."""

    parser = argparse.ArgumentParser(prog="continuity-ai")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate-aurora-fixture")
    generate.add_argument("--output-root", default=".", type=Path)
    generate_unseen = subparsers.add_parser("generate-unseen-workspace")
    generate_unseen.add_argument("--output-root", default="generated-run", type=Path)
    generate_unseen.add_argument("--seed", required=True, type=int)
    evaluate_unseen = subparsers.add_parser("evaluate-unseen-workspace")
    evaluate_unseen.add_argument("--run-root", required=True, type=Path)
    evaluate_unseen.add_argument("--classification-result", required=True, type=Path)
    evaluate_unseen.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()

    if args.command == "generate-aurora-fixture":
        generate_project_aurora_fixture(args.output_root)
        print(json.dumps(manifest(args.output_root), indent=2, sort_keys=True))
    elif args.command == "generate-unseen-workspace":
        result = generate_unseen_workspace(args.output_root, args.seed)
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.command == "evaluate-unseen-workspace":
        classification = load_classification_result(args.classification_result)
        report = evaluate_generated_run(args.run_root, classification)
        artifacts = write_evaluation_reports(report, args.output_root)
        print(render_evaluation_markdown(report), end="")
        print(f"JSON report: {artifacts.json_path}")
        print(f"Markdown report: {artifacts.markdown_path}")
