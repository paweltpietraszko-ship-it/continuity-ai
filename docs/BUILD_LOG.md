# Build Log

## 2026-07-17

- Decision: Use the Codex Cloud work branch as the active implementation branch after the human corrected repository verification rules.
- Evidence: Root README contains the required repository identity description.
- Gate: Started Gate G-01 Deterministic Aurora Fixture.
- Model/tool used: Codex primary project thread.
- Commit planned: docs: establish Continuity AI implementation baseline.
- Tests: none run before baseline documentation.
- Known Continuity Breaks in the development process: initial repository verification rule conflicted with Codex Cloud branch and remote behavior; human correction resolved it.

## 2026-07-17 Gate G-01 Initial Implementation

- Local Codex evidence: baseline documentation was locally committed as e330e3f12571a41a967d475e413eb2b6c4d8f0f8; implementation was locally committed as c9dd61df58770c92691145dc473b62f5e0bd3531; a local tag named implementation-start-2026-07-17 existed in the Codex workspace.
- GitHub-persisted evidence: PR #1 was exported as a flattened GitHub commit with head b5259f541eb8fead099b435a9f73fa58984b73a3, so the local Codex commit graph and local tag were not preserved in GitHub.
- Development Continuity Break: repository documentation previously implied local commit and tag evidence would persist as PR history; GitHub PR #1 instead preserved a flattened commit only.
- Decision: Do not attempt to create or claim a GitHub tag from Codex Cloud.
- Model/tool used: Codex primary project thread with local Python, uv, and pytest.
- Evidence: Fixture generator writes EML, ICS, XLSX, PDF, Markdown, and test-only JSON outputs under fixtures/project_aurora/generated/, which is ignored by Git.
- Tests: uv run pytest tests/test_aurora_fixture.py passed with 6 tests in the initial implementation.
- Tests: uv run pytest tests/test_acceptance_project_promise.py failed because answer_morning_question raised ReasoningPipelineNotImplementedError.
- Gate status: not declared passed; Gate G-01 requires merge and verification from GitHub-persisted history.

## 2026-07-17 Gate G-01 Blocker Fixes

- Decision: Isolate production artifact inputs from test-only ground truth.
- Evidence: Generated production artifacts are under fixtures/project_aurora/generated/artifacts/ and generated test-only ground truth is under fixtures/project_aurora/generated/test_only/ground_truth.json.
- Evidence: The acceptance test passes only fixtures/project_aurora/generated/artifacts/ to answer_morning_question.
- Decision: Replace the overbroad open() ban with focused protections against ground_truth.json in reasoning modules, production artifact roots, and guarded artifact file opening.
- Tests: uv run pytest tests/test_aurora_fixture.py passed with 8 tests.
- Tests: uv run pytest tests/test_acceptance_project_promise.py failed only with ReasoningPipelineNotImplementedError.
- Known Continuity Breaks in the development process: local Codex history and the GitHub PR history differ; current documentation distinguishes local Codex evidence from GitHub-persisted evidence.
- Gate status: not declared passed until the PR is merged and verified.

## 2026-07-17 Gate G-01 Windows Path Audit

- Audit: Cursor/Composer 2.5 performed a read-only static and ad hoc audit.
- Audit: Claude Code performed an independent read-only Windows audit.
- Finding: The Windows audit found a path-separator failure in tests/test_aurora_fixture.py::test_generates_all_required_artifacts.
- Scope: The failure concerned test path representation, not generated artifact contents or byte determinism.
- Handoff: The fix was returned to Codex, the primary implementer.
- Gate status: Windows verification has not passed until the fixture tests are rerun on Windows.

## 2026-07-17 Gate G-01 Human Windows Verification

- Environment: Windows 11 local checkout synchronized to the GitHub PR head.
- Tooling: uv 0.11.29 installed.
- Setup: uv sync completed using CPython 3.14.4.
- Fixture result: uv run pytest tests/test_aurora_fixture.py -v completed with 9 passed.
- Acceptance result: uv run pytest tests/test_acceptance_project_promise.py -v produced the expected failure only with ReasoningPipelineNotImplementedError.
- Resolution: The previously reported Windows path-separator blocker is resolved.
- Gate status: G-01 is not declared passed; merge and post-merge verification remain.
