"""Command line interface for Continuity AI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from continuity_ai.aurora_fixture import generate_project_aurora_fixture, manifest


def main() -> None:
    """Run the Continuity AI command line interface."""

    parser = argparse.ArgumentParser(prog="continuity-ai")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate-aurora-fixture")
    generate.add_argument("--output-root", default=".", type=Path)
    args = parser.parse_args()

    if args.command == "generate-aurora-fixture":
        generate_project_aurora_fixture(args.output_root)
        print(json.dumps(manifest(args.output_root), indent=2, sort_keys=True))
