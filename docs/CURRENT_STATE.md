# Current State

- GitHub-persisted state: PR #1 (Gate G-01), PR #4 (Gate G-02), PR #5 (Gate G-02 documentation closure), and PR #7 (revised MVP and roadmap boundary) are merged to main. Current main before PR #8: a6c5aa93f4c732cbdad6a067af56dbfcb36d97ce.
- Gate status: Gate G-01 passed. Gate G-02 (deterministic artifact ingestion and normalization) passed. G-SEC-01 and G-03 have not started implementation.
- Post-merge verification (Gate G-02): C:\Users\p_pie\.local\bin\uv.exe run pytest tests/test_aurora_fixture.py -v. Result: 10 passed. C:\Users\p_pie\.local\bin\uv.exe run pytest tests/test_ingestion.py -v. Result: 40 passed. C:\Users\p_pie\.local\bin\uv.exe run pytest tests/test_acceptance_project_promise.py -v. Result: 1 failed only with ReasoningPipelineNotImplementedError, intentionally. Local main and origin/main matched at 06de879024066e5af4c1a0ec28900861aeb82587. git status --short was empty. No files were modified after merge.
- What works: deterministic Project Aurora fixture generation and hardened G-02 ingestion for EML, ICS, XLSX, PDF, Markdown, and the production evidence manifest. Ground truth remains test-only and outside the production artifact root.
- Production evidence contract (final, G-02): EvidenceRecord contains source_id, evidence_id, author, timestamp, source_type, title, uri, artifact_sha256, and content. It excludes timeline_position, business_purpose, semantic classifications, expected conclusions, and next actions. Chronology is UTC timestamp then evidence_id.
- Accepted deferred G-02 finding: G02-NB-D1 — _pin_xlsx_modified_timestamp does not verify that exactly one dcterms:modified XML element was replaced. It is not on the MVP critical path.
- Known failure: the final product acceptance test still fails only because the reasoning pipeline is not implemented. This remains intentional until the vertical-skeleton branch replaces it with a real offline fake-provider pipeline acceptance test.
- G-03 history: v0.1 was independently falsified and rejected. The v0.2 candidate introduced universal versus Aurora-profile separation, deterministic evidence spans, break/no-break outcomes, open conversation, and closed-world source validation.
- Independent Fable 5 review of the combined security, reasoning, closed-evidence-world, and skeleton contracts returned REVISE BEFORE IMPLEMENTATION with two blockers. Both are accepted and resolved normatively in docs/FABLE5_CONTRACT_CORRECTIONS_v0.1.md.
- Blocker correction 1: a conversation may propose a complete analysis revision, but it cannot replace the retained analysis without a dedicated explicit owner confirmation command. Locking invalidates the pending revision.
- Blocker correction 2: every retained analysis stores an encrypted evidence snapshot containing canonical hashes and exact cited span text. Historical citation cards hydrate from the snapshot, never silently from changed source files.
- Additional accepted corrections: domain-neutral status-to-role consistency; versioned snapshot tests for every production prompt; no verified quotations in model prose; safe content-free controlled errors; fixed vault-lifetime salt and fresh per-write nonce; no plaintext password in VaultSession; best-effort key-buffer overwrite without a secure-erasure claim; UTF-8 bridge; backend-owned citation cards; non-empty bounded attestations; single-chain supersession.
- KDF implementation decision: argon2-cffi Argon2id raw derivation is used for the skeleton; cryptography AESGCM provides authenticated encryption. This avoids depending on OpenSSL Argon2id capability on the demo machine.
- The final implementation brief is docs/CODEX_VERTICAL_SKELETON_PROMPT.md. The earlier draft is not authoritative.
- Accepted MVP scope, not yet implemented: one local owner, encrypted application vault, append-only owner attestations, persistent natural conversation, evidence-grounded initial analysis, confirmed analysis revisions, encrypted evidence snapshots, and stable JSON bridge output.
- Excluded from MVP: LynxMask integration, voice, weather/web tools, multiple users or projects, biometrics, password recovery, cloud synchronization, autonomous source changes, and multi-model review inside the application.
- UI and film remain parallel. UI may render only backend-owned source metadata and exact snapshot quotations. The Project Aurora failure is described as an operational contradiction, document drift, or state drift, not a document-system hallucination.
- Next action: inspect PR #8 final diff, merge the frozen contracts, then start Codex from the resulting main commit using docs/CODEX_VERTICAL_SKELETON_PROMPT.md.

## 2026-07-17 Vertical Skeleton Correction Before Review

- After the first vertical-skeleton implementation commit `e4982f3`, and before review or merge, an implementation-blocking correction was discovered.
- Gate G-03 now distinguishes two `break_found` kinds: `propagation_break` and `decision_provenance_not_found`.
- A missing decision provenance case is a Continuity Break when the currently available project sources show a material project-state change but contain no approval, decision, rationale, or linked note explaining that change.
- User-visible language must describe what Continuity AI found or could not find in ordinary human language and must not expose internal enum values, error codes, raw exception class names, object identifiers, or traceback details.
- The normative record for this correction is `docs/GATE_G03_DECISION_PROVENANCE_AND_HUMAN_LANGUAGE_ADDENDUM_v0.1.md`.
