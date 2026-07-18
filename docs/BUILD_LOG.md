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

## 2026-07-17 Gate G-01 Post-Merge Verification

- Evidence: PR #1 was merged to main.
- Fixture result: uv run pytest tests/test_aurora_fixture.py -v completed with 9 passed.
- Acceptance result: uv run pytest tests/test_acceptance_project_promise.py -v produced 1 failed only with ReasoningPipelineNotImplementedError, intentionally.
- Working tree: git status --short was empty.
- Gate status: Gate G-01 passed.
- Next action: Implement Gate G-02 deterministic artifact ingestion and normalization without AI reasoning.

## 2026-07-17 Gate G-02 Deterministic Artifact Ingestion

- Gate: Started and implemented Gate G-02 Deterministic Artifact Ingestion and Normalization.
- Decision: Extend the fixture generator to write fixtures/project_aurora/generated/artifacts/evidence_manifest.json as production evidence metadata (schema_version, project, artifacts), deterministic and sorted, containing checksums of the five evidence artifacts but not its own checksum, and never referencing ground_truth.json or test_only.
- Decision: Add a frozen typed EvidenceRecord model (src/continuity_ai/models.py) holding normalized evidence content without Project Aurora expected conclusions.
- Decision: Add src/continuity_ai/ingestion.py with ingest_artifacts(artifact_root), which calls validate_production_artifact_root, reads and schema-validates evidence_manifest.json, rejects duplicate source_id/evidence_id, unsupported source types, absolute paths, path traversal, and any ground_truth/test_only reference, resolves and contains every artifact path under artifact_root, verifies SHA-256 before parsing, parses with real parsers (email.parser.BytesParser, icalendar, openpyxl, pypdf, UTF-8 text), and returns EvidenceRecord tuples sorted by timeline_position then evidence_id. The module does not import continuity_ai.aurora_fixture, ARTIFACTS, or ground truth, and makes no AI or network call.
- Decision: Gate G-02 performs no contradiction detection, summarization, or next-action generation; the Continuity Break is not detected in this gate.
- Evidence: fixtures/project_aurora/generated/artifacts/evidence_manifest.json is production evidence metadata, not test ground truth; it is generated only under the production artifact root.
- Tests: pytest tests/test_aurora_fixture.py -v completed with 9 passed (updated only to also expect evidence_manifest.json in the generated artifact set).
- Tests: pytest tests/test_ingestion.py -v completed with 18 passed, covering five-record production, stable source/evidence IDs, deterministic ordering, real-parser material-text extraction, byte-identical records and manifest across two independent generations, and fail-closed behavior for checksum mismatch, missing manifest, malformed manifest, duplicate source_id, duplicate evidence_id, unsupported source type, absolute paths, path traversal, and ground_truth/test_only references, plus static checks that ingestion does not import the fixture generator and that production reasoning remains unimplemented.
- Tests: pytest tests/test_acceptance_project_promise.py -v produced 1 failed only with ReasoningPipelineNotImplementedError; src/continuity_ai/reasoning.py and tests/test_acceptance_project_promise.py were not modified.
- Tooling note: `uv` was not available in this local verification environment; tests were executed directly against the project's pinned dependency versions instead of `uv run`.
- Gate status: Gate G-02 implemented and locally verified; not declared passed until the pull request is reviewed, merged, and re-verified from GitHub-persisted history.

## 2026-07-17 Gate G-02 Coordinator-Required Hardening (Cursor Audit)

- Audit: Cursor audited Gate G-02 and returned verdict PASS WITH NON-BLOCKING FINDINGS.
- Decision: The coordinator required pre-merge hardening before accepting G-02; the following corrections were applied on the same branch and PR.
- Decision: Removed timeline_position and business_purpose from the on-disk evidence_manifest.json entries and from EvidenceRecord. They remain internal to ArtifactDefinition for fixture generation only. The production evidence contract now carries only source_id, evidence_id, author, timestamp, source_type, title, uri, sha256, plus normalized content in EvidenceRecord. Manifest schema validation now rejects unexpected fields outright, so reintroducing either removed field into a manifest entry fails closed.
- Decision: Chronology is now derived from validated timestamps instead of a manifest-provided position. Every manifest timestamp is validated as ISO 8601 / RFC 3339 with an explicit timezone (malformed, timezone-naive, and non-string timestamps are rejected), normalized to canonical UTC ending in Z, and records are sorted by (parsed UTC timestamp, evidence_id); ties are broken by evidence_id.
- Decision: Hardened ground-truth isolation in src/continuity_ai/artifact_io.py and src/continuity_ai/ingestion.py to be case-insensitive for the test_only directory and ground_truth.json filename, and to scan the full artifact subtree so a forbidden path is rejected even when the manifest never references it. The existing resolved-path containment boundary is preserved.
- Decision: Hardened URI validation to reject POSIX absolute paths, Windows absolute and drive-relative paths (C:/outside.txt, C:outside.txt) using pathlib.PureWindowsPath and PurePosixPath regardless of host platform, backslashes, parent traversal, resolution-based escapes, and forbidden ground-truth names case-insensitively; duplicate URIs are now rejected case-insensitively.
- Decision: Strengthened manifest schema validation to reject unexpected top-level and per-entry fields, non-hexadecimal or wrong-length sha256 values, invalid UTF-8, read errors, and malformed JSON, all wrapped as ArtifactIngestionError. The project field remains an arbitrary non-empty string so ingestion is not hardcoded to Project Aurora.
- Decision: Parsers now fail closed on materially empty content: empty Markdown, PDF with no extractable text, spreadsheets with no meaningful cell values, emails with empty subject and body (the literal "Subject:" label is never treated as evidence on its own), and calendars requiring exactly one VEVENT with at least one meaningful SUMMARY/LOCATION/DESCRIPTION value (missing fields are omitted, never serialized as the string "None"). No OCR or document recovery was implemented.
- Fix: found and fixed a pre-existing, intermittent non-determinism defect in aurora_fixture.py's XLSX writer, surfaced while re-running the fixture suite under uv. openpyxl's save_workbook() unconditionally overwrites workbook.properties.modified with the actual wall-clock time during save, discarding the fixed timestamp set beforehand; this only manifested as a test failure when two independent generations' saves straddled a one-second boundary. The writer now re-pins the fixed modified timestamp directly in the saved docProps/core.xml after save, before zip normalization, so budget_v4.xlsx and evidence_manifest.json (which embeds its checksum) are deterministic across independent generations. Verified with 30 in-process generations producing a single distinct checksum.
- Tests: added regression coverage for case-variant forbidden directory and filename, a forbidden file present but unreferenced by the manifest, Windows drive absolute and drive-relative paths, duplicate URI and case-only-duplicate URI, invalid UTF-8 manifest, non-hex sha256, malformed timestamp, timestamp without timezone, non-string timestamp, timestamp-based ordering with ties broken by evidence_id, empty Markdown, bodyless email, calendar with no meaningful fields, spreadsheet with no meaningful cells, PDF with no extractable text, unexpected manifest fields (including a reintroduced timeline_position), and a hand-built, fixture-independent production artifact directory and manifest proving ingestion follows the on-disk contract rather than Project Aurora constants. No existing test was weakened or removed; none are marked xfail or skip.
- Tooling: this environment did not initially expose uv through PATH; the Windows audit found and successfully used C:\Users\p_pie\.local\bin\uv.exe.
- Tests: C:\Users\p_pie\.local\bin\uv.exe run pytest tests/test_aurora_fixture.py -v completed with 10 passed.
- Tests: C:\Users\p_pie\.local\bin\uv.exe run pytest tests/test_ingestion.py -v completed with 40 passed.
- Tests: C:\Users\p_pie\.local\bin\uv.exe run pytest tests/test_acceptance_project_promise.py -v produced 1 failed only with ReasoningPipelineNotImplementedError; src/continuity_ai/reasoning.py and tests/test_acceptance_project_promise.py were not modified.
- Gate status: Gate G-02 hardening implemented and locally verified; not declared passed until the updated pull request is reviewed, merged, and re-verified from GitHub-persisted history.

## 2026-07-17 Gate G-02 Post-Merge Closure

- Audit: full Cursor audit of Gate G-02 returned PASS WITH NON-BLOCKING FINDINGS; delta audit after coordinator-required hardening also returned PASS WITH NON-BLOCKING FINDINGS, with no blocking findings remaining. The coordinator authorized merge.
- Evidence: PR #4 (Implement deterministic artifact ingestion and normalization) was merged to main. PR #4 head: 6d2bcf47d5d15f4267ded952a167555f797a67f6. Merge commit: 06de879024066e5af4c1a0ec28900861aeb82587.
- Final production evidence contract: EvidenceRecord contains source_id, evidence_id, author, timestamp, source_type, title, uri, artifact_sha256, and content. It excludes timeline_position, business_purpose, semantic classifications, expected conclusions, and next actions. Chronology is derived from validated timezone-aware timestamps, normalized to UTC, and ordered by timestamp then evidence_id.
- Accepted deferred finding: G02-NB-D1 — _pin_xlsx_modified_timestamp does not verify that exactly one dcterms:modified XML element was replaced. Classification: accepted non-blocking technical debt; not part of the MVP critical path. Deliberately not fixed in the merge operation, per coordinator instruction, since dependencies are pinned, the correction works, repeated generations are byte-identical, openpyxl reopens the resulting workbook, and fixture and ingestion tests pass.
- Tests: C:\Users\p_pie\.local\bin\uv.exe run pytest tests/test_aurora_fixture.py -v completed with 10 passed.
- Tests: C:\Users\p_pie\.local\bin\uv.exe run pytest tests/test_ingestion.py -v completed with 40 passed.
- Tests: C:\Users\p_pie\.local\bin\uv.exe run pytest tests/test_acceptance_project_promise.py -v produced 1 failed only with ReasoningPipelineNotImplementedError; src/continuity_ai/reasoning.py and tests/test_acceptance_project_promise.py remain unmodified.
- Verification: local main and origin/main matched at 06de879024066e5af4c1a0ec28900861aeb82587 after merge; git status --short was empty; no files were modified after merge.
- Gate status: Gate G-02 passed.
- Next action: Define and freeze Gate G-03 evidence-grounded reasoning contract before implementation. Gate G-03 has not started.

## 2026-07-17 Vertical Skeleton Decision-Provenance and Human-Language Correction

- Context: After first vertical-skeleton implementation commit `e4982f3` and before review or merge, the coordinator identified an implementation-blocking correction.
- Decision: Add `continuity_break_kind` for G-03 `break_found` analyses, with `propagation_break` for approved decisions that have not propagated and `decision_provenance_not_found` for material changes where no approval, decision, rationale, or linked note is found in the available project sources.
- Decision: Preserve the Project Aurora scenario as `propagation_break`; do not alter the G-02 `EvidenceRecord` contract or move material-change interpretation into G-02.
- Decision: Add a normative addendum at `docs/GATE_G03_DECISION_PROVENANCE_AND_HUMAN_LANGUAGE_ADDENDUM_v0.1.md` and make it authoritative over earlier G-03 text where conflicts exist.
- Decision: Audit public output language so UI-facing messages describe what Continuity AI found or could not find, rather than exposing internal enum values, error codes, raw exception names, object IDs, or tracebacks.
- Tests: complete offline test suite and whitespace checks are required before committing the correction.

## 2026-07-17 PR #9 Repair Status and Outstanding Blockers

- Status: PR #9 remains open and unmerged.
- Frozen base: 792c5332b33310eca8e51216605ef9f75b13ead1.
- Original Codex implementation commit: a88b3f7dbe3fc4dd972cf206d4174078cdb41cf5.
- Audit: Cursor destructive audit returned BLOCK.
- Incident: an accidental local Cursor implementation commit 20676de was hard-reset to a88b3f7 before any push; the working tree was clean afterward and no Cursor implementation was retained.
- Accepted Windows portability repair:
  - commit 1a2fdc511ddfeb9b68b1dcea2c34c3e977fd10eb
  - message: Fix Windows vault directory sync
  - full suite: 63 passed
- Accepted vault initialization and stable error-contract repair:
  - commit d8066ae2bc0aeee9df1a2dd2bb1d610c7e0b0929
  - message: Protect vault initialization and restore error codes
  - full suite: 68 passed
- Accepted proposal-session ownership repair:
  - commit 88268b09161bbdfcc7115ad6ff6417cdd96087ca
  - message: Bind proposals to active vault sessions
  - targeted suite: 27 passed
  - full suite: 78 passed
- All three repair pushes were normal fast-forwards.
- No review-export .diff file was committed.
- These repairs do not close the full Cursor audit.
- Gate G-03 and PR #9 must not be described as passed or ready to merge yet.
- Remaining unresolved blocker groups:
  - bridge commands are still stubs rather than a real vertical flow;
  - production reasoning still selects the Aurora fake provider;
  - OpenAI adapter does not yet receive the evidence, spans, prompts, and strict schema required by the contract;
  - conversation routing and citations remain insufficiently grounded;
  - analyses, snapshots, and conversation state are not yet persisted end-to-end;
  - acceptance and end-to-end tests remain inadequate, including network isolation.
- Coordinator audit classifications:
  - Cursor N-3 was rejected as a production defect: the universal validator cannot prove semantic correctness; exact Aurora role mapping belongs in tests.
  - Cursor M-D2 was rejected because the later human-language addendum is authoritative.
  - B-D1 remains accepted only as structural span validation; deterministic code cannot prove semantic relevance.
  - Hostile live-model quotation testing, vault rollback, and coarse line spans remain deferred.

## 2026-07-18 PR #9 Real Bridge Vertical Flow

- Accepted commit: 9333d46de42548cb940a5d065eff7c543f9bb1bf.
- Parent commit: b276807f3cfb4a4d726f24ca059cc3c84b76011e.
- Commit message: Implement real bridge vertical flow.
- Push: normal, non-force push to origin codex/implement-vertical-skeleton-from-commit.
- Changed files: src/continuity_ai/bridge.py, tests/test_vertical_skeleton.py.
- Stat summary: 645 insertions, 24 deletions.
- Tests: targeted bridge/vertical-skeleton suite result: 47 passed.
- Tests: full suite result: 98 passed.
- Verification: git diff --check produced only the Windows LF-to-CRLF advisory and no conflict-marker or trailing-whitespace error.
- Verification: the final working tree was clean.
- Verification: the remote PR head was verified as the accepted commit.
- Status: PR #9 remains open and unmerged; no merge decision has been made.
- Repaired: commands delegate to real domain functions; evidence combines project artifacts with confirmed encrypted attestations; citation cards are hydrated from backend-owned records and spans; attestation confirmation triggers evidence refresh and reanalysis; analysis revision confirmation delegates to the real proposal flow; vault replacement, unlock, and project load are atomic at the bridge-state boundary; malformed commands and invalid field types return controlled public errors; lock/unlock removes and restores decrypted attestation evidence correctly; tests cover hostile provider prose and prove it cannot forge citation-card metadata.
- Remaining unresolved blocker groups:
  - production provider selection still defaults to the Aurora fake provider;
  - the OpenAI adapter still does not receive the full evidence, spans, prompts, and strict schema contract;
  - conversation routing and grounding remain insufficient;
  - analyses, evidence snapshots, and conversation state are not persisted end-to-end;
  - acceptance/end-to-end coverage and explicit network isolation remain incomplete.

## 2026-07-18 PR #9 OpenAI Reasoning Provider Contract

- Accepted commit: 9fe669ec447fbed8054dee5806af0da9aa297b0a.
- Parent commit: a6958dd8f089e7c300458db36bca5deda0cca44a.
- Commit message: Repair OpenAI reasoning provider contract.
- Changed files: src/continuity_ai/openai_provider.py, src/continuity_ai/prompts.py, tests/test_vertical_skeleton.py.
- Stat summary: 726 insertions, 27 deletions.
- Tests: targeted suite result: 67 passed.
- Tests: full suite result: 118 passed.
- Verification: git diff --check passed.
- Push: normal, non-force push.
- Verification: the final working tree was clean.
- Repaired: the provider uses the official OpenAI Python SDK and the Responses API; the API key comes from OPENAI_API_KEY; the model comes from CONTINUITY_OPENAI_MODEL; and the request contains the question, complete evidence records, and deterministic spans under a versioned prompt.
- Repaired: the request asks for strict JSON Schema output, sets store to false, uses an empty tools list, and does not use streaming, background execution, a previous response, or a conversation chain.
- Repaired: output_text is parsed; API failures, incomplete responses, refusals, malformed JSON, and non-object JSON fail safely; semantic validation remains owned by run_analysis.
- Data boundary: URIs, checksums, local paths, citation cards, and provider-owned display metadata are not sent to the model.
- Live-model status: no successful live OpenAI request was executed or claimed for this accepted commit.

## 2026-07-18 PR #9 Explicit Reasoning-Provider Selection

- Accepted commit: 31775b382e938507cd26ef3ec5d7d4d57c60e573.
- Parent commit: 9fe669ec447fbed8054dee5806af0da9aa297b0a.
- Commit message: Make reasoning provider selection explicit.
- Changed files: src/continuity_ai/bridge.py, src/continuity_ai/provider_selection.py, src/continuity_ai/reasoning.py, tests/test_acceptance_project_promise.py, tests/test_ingestion.py, tests/test_vertical_skeleton.py.
- Stat summary: 301 insertions, 14 deletions.
- Tests: focused stale-test regression result: 1 passed.
- Tests: targeted provider-selection suite result: 81 passed.
- Tests: full suite result: 131 passed.
- Verification: git diff --check passed.
- Push: normal, non-force push.
- Verification: the final working tree was clean.
- Repaired: reasoning-provider selection is explicit. CONTINUITY_REASONING_PROVIDER is required when no provider is injected; supported configured values are openai and fake_aurora; surrounding whitespace is ignored; and matching is case-insensitive.
- Repaired: missing, blank, or unsupported configured values fail safely; there is no implicit fake-provider fallback; an injected provider has precedence; and a falsy injected provider is not silently replaced.
- Network boundary: provider selection itself does not call the network, and importing the module does not call the network.
- Integration behavior: Bridge without injection requires explicit configuration, while answer_morning_question uses the shared provider factory when no provider is injected.
- Provider status: FakeAuroraProvider remains an explicitly selected test/demo provider only. It is not production reasoning and is not evidence of GPT-5.6 operation.
