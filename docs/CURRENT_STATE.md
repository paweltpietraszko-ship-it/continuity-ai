# Current State

- GitHub-persisted state: PR #1 contains the Gate G-01 implementation and audit fixes.
- Local Codex evidence: earlier local commits and a local tag existed in the Codex workspace but were flattened when PR #1 was exported to GitHub.
- What works: repository identity verified by README description; deterministic Project Aurora fixture generator creates uncommitted EML, ICS, XLSX, PDF, Markdown, and test-only JSON outputs under fixtures/project_aurora/generated/; production artifact inputs are isolated under fixtures/project_aurora/generated/artifacts/; test-only ground truth is isolated under fixtures/project_aurora/generated/test_only/; fixture metadata includes stable source IDs, evidence IDs, authors, timestamps, source types, timeline positions, business purposes, repository-relative URIs, and SHA-256 checksums.
- Tests run: uv run pytest tests/test_aurora_fixture.py; uv run pytest tests/test_acceptance_project_promise.py.
- Known failures: final product acceptance test fails because the evidence-grounded reasoning pipeline is not implemented yet; Windows fixture test verification is pending after the path-separator fix.
- Current gate: G-01 is pending Windows verification, merge, and post-merge verification.
- Invariants: English-only repository content; frozen MVP scope; ground truth is test-only and must not be present in or passed as the production artifact input directory; production reasoning code must not name or construct ground_truth.json.
- Forbidden scope changes: live integrations, OAuth, multiple cases, organization memory, LynxMask, Triangulum, folder monitoring, autonomous orchestration, multi-model triangulation, general synthetic company generation, desktop packaging, or features outside the Project Aurora demo.
- Next action: Export the fixes to PR #1, rerun the fixture tests on Windows, and merge only after all fixture tests pass and the acceptance test fails solely with ReasoningPipelineNotImplementedError.
