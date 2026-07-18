"""Standalone CLI for Project Source Scoping v0.1."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from continuity_ai.errors import PublicError
from continuity_ai.evidence import build_spans
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.io import load_workspace
from continuity_ai.source_scoping.openai_provider import OpenAISourceScopingProvider
from continuity_ai.source_scoping.service import run_source_scoping


def main() -> None:
    parser = argparse.ArgumentParser(prog="project-source-scoping")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--provider", choices=("fake", "openai"), default="fake")
    args = parser.parse_args()
    try:
        target, records = load_workspace(args.workspace)
        spans = build_spans(records)
        provider = (
            FakeSourceScopingProvider()
            if args.provider == "fake"
            else OpenAISourceScopingProvider()
        )
        result = run_source_scoping(target, records, spans, provider)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    except PublicError as exc:
        print(
            json.dumps(
                {"ok": False, "error": {"code": exc.code, "message": exc.public_message}},
                ensure_ascii=False,
            )
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
