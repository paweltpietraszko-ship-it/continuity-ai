# Current State

- GitHub-persisted state: PR #1 (Gate G-01), PR #4 (Gate G-02), PR #5 (Gate G-02 documentation closure), and PR #7 (revised MVP and roadmap boundary) are merged to main. PR #9 remains open and unmerged; its base main commit remains 792c5332b33310eca8e51216605ef9f75b13ead1. No merge decision has been made.
- Active PR branch: codex/implement-vertical-skeleton-from-commit.
- Current branch HEAD after semantic-resolution contract freeze: 63ddc6530eb242a41ae0ac920253030cbb6f08fa.
- Semantic-resolution contract freeze commit message: `Freeze semantic resolution contract`.
- Semantic-resolution contract freeze parent: 11c210555a4f6259a0b5a360212485e8f8a9a074.
- The latest reviewed code checkpoint remains: 31775b382e938507cd26ef3ec5d7d4d57c60e573.
- Current verification baseline: the full local suite completed with 131 passed.
- Gate status: Gate G-01 passed. Gate G-02 (deterministic artifact ingestion and normalization) passed. Gate G-03 has not passed, and PR #9 is not merge-ready.
- Historical Gate G-02 post-merge verification: the fixture suite completed with 10 passed, the ingestion suite completed with 40 passed, and the acceptance test produced the then-expected ReasoningPipelineNotImplementedError. That acceptance-test result describes the earlier G-02 checkpoint, not the current PR #9 branch.
- What works: deterministic Project Aurora fixture generation and hardened G-02 ingestion for EML, ICS, XLSX, PDF, Markdown, and the production evidence manifest. Ground truth remains test-only and outside the production artifact root.
- Production evidence contract (final, G-02): EvidenceRecord contains source_id, evidence_id, author, timestamp, source_type, title, uri, artifact_sha256, and content. It excludes timeline_position, business_purpose, semantic classifications, expected conclusions, and next actions. Chronology is UTC timestamp then evidence_id.
- Accepted deferred G-02 finding: G02-NB-D1 — _pin_xlsx_modified_timestamp does not verify that exactly one dcterms:modified XML element was replaced. It is not on the MVP critical path.
- Current repaired blockers: the real bridge vertical flow, the OpenAI reasoning-provider contract, and the implicit fake-provider fallback are repaired.
- Production provider selection: CONTINUITY_REASONING_PROVIDER is required when no provider is injected. Production requires explicit provider selection. DeterministicOfflineReasoningProvider remains available only as an explicitly selected test/offline-fallback provider; it performs no semantic inference and is not production reasoning or proof of real-model generalization.
- Current operating boundary: the bridge, OpenAI adapter contract, and explicit provider selection operate against a pre-grouped candidate workspace. The system currently analyzes user-selected, already grouped project artifacts.
- `docs/SEMANTIC_PROJECT_AND_DECISION_SCOPE_RESOLUTION_CONTRACT_v0.1.md` is accepted, falsified, frozen, and normative.
- Semantic Project Resolution and Decision Scope Resolution are still not implemented. The system must not yet be described as resolving naturally inconsistent project references across scattered sources or deciding whether Mobile, Desktop, both variants, or global product-family scope applies.
- Freezing the semantic-resolution contract authorizes only the bounded implementation package described in that contract. It does not authorize broader product claims.
- Live-model status: semantic project-identity reconstruction and decision-scope reconstruction have not been live-evaluated. No successful live GPT-5.6 semantic-resolution or continuity-analysis result may be claimed.
- Strong-claim blocker: semantic resolution must precede the claim that Continuity AI reconstructs project state from scattered, naturally written artifacts and must precede the final live evaluation.
- G-03 history: v0.1 was independently falsified and rejected. The v0.2 candidate introduced universal versus Aurora-profile separation, deterministic evidence spans, break/no-break outcomes, open conversation, and closed-world source validation.
- Independent Fable 5 review of the combined security, reasoning, closed-evidence-world, and skeleton contracts returned REVISE BEFORE IMPLEMENTATION with two blockers. Both are accepted and resolved normatively in docs/FABLE5_CONTRACT_CORRECTIONS_v0.1.md.
- Blocker correction 1: a conversation may propose a complete analysis revision, but it cannot replace the retained analysis without a dedicated explicit owner confirmation command. Locking invalidates the pending revision.
- Blocker correction 2: every retained analysis stores an encrypted evidence snapshot containing canonical hashes and exact cited span text. Historical citation cards hydrate from the snapshot, never silently from changed source files.
- Additional accepted corrections: domain-neutral status-to-role consistency; versioned snapshot tests for every production prompt; no verified quotations in model prose; safe content-free controlled errors; fixed vault-lifetime salt and fresh per-write nonce; no plaintext password in VaultSession; best-effort key-buffer overwrite without a secure-erasure claim; UTF-8 bridge; backend-owned citation cards; non-empty bounded attestations; single-chain supersession.
- KDF implementation decision: argon2-cffi Argon2id raw derivation is used for the skeleton; cryptography AESGCM provides authenticated encryption. This avoids depending on OpenSSL Argon2id capability on the demo machine.
- The final implementation brief is docs/CODEX_VERTICAL_SKELETON_PROMPT.md. The earlier draft is not authoritative.
- Accepted MVP scope: one local owner, encrypted application vault, append-only owner attestations, persistent natural conversation, evidence-grounded initial analysis, confirmed analysis revisions, encrypted evidence snapshots, and stable JSON bridge output. The current vertical skeleton implements only part of this scope; the persistence and conversation work listed below remains unresolved.
- Excluded from MVP: LynxMask integration, voice, weather/web tools, multiple users or projects, biometrics, password recovery, cloud synchronization, autonomous source changes, and multi-model review inside the application.
- UI and film remain parallel. UI may render only backend-owned source metadata and exact snapshot quotations. The Project Aurora failure is described as an operational contradiction, document drift, or state drift, not a document-system hallucination.
- Competition slice: one candidate workspace; Project Aurora; varied natural references; one minimal decoy or ambiguous source; deterministic supporting spans; backend validation; ambiguity handling; and a small LynxMask Mobile/Desktop decision-scope fixture. It is not a universal resolver.
- Scope exclusions: this checkpoint does not claim or authorize automatic project discovery, general knowledge-graph capability, persistent alias learning, full resolution-record persistence, arbitrary multi-project support, full UI integration, a finished film, or a completed Devpost submission.
- Remaining unresolved groups: Semantic Project Resolution and Decision Scope Resolution; conversation routing and grounding; persistence of retained analyses, evidence snapshots, conversation history, the full audit trail, and confirmed analysis revisions; controlled live-model evaluation; final UI-to-bridge-to-OpenAI-to-UI end-to-end coverage; consolidated default-suite network isolation; and a packaged demo runner.
- Immediate sequence:
  1. complete and review this pitch/current-state docs-only checkpoint;
  2. run the bounded Retained Analysis Persistence and Snapshot Fidelity CC package;
  3. perform a point Cursor re-audit of that repair only;
  4. perform independent Codex destructive testing and diff verification;
  5. commit only after acceptance;
  6. continue with the separately approved conversation-grounding and test-hardening packages;
  7. implement the frozen bounded Semantic Resolution slice;
  8. run the controlled live semantic-resolution plus continuity-analysis evaluation;
  9. update UI, film, README, pitch, and submission claims only from validated results.

## 2026-07-17 Vertical Skeleton Correction Before Review

- After the first vertical-skeleton implementation commit `e4982f3`, and before review or merge, an implementation-blocking correction was discovered.
- Gate G-03 now distinguishes two `break_found` kinds: `propagation_break` and `decision_provenance_not_found`.
- A missing decision provenance case is a Continuity Break when the currently available project sources show a material project-state change but contain no approval, decision, rationale, or linked note explaining that change.
- User-visible language must describe what Continuity AI found or could not find in ordinary human language and must not expose internal enum values, error codes, raw exception class names, object identifiers, or traceback details.
- The normative record for this correction is `docs/GATE_G03_DECISION_PROVENANCE_AND_HUMAN_LANGUAGE_ADDENDUM_v0.1.md`.

## 2026-07-18 PR #9 Repair Status

- PR #9 remains open and unmerged. Its base main commit remains 792c5332b33310eca8e51216605ef9f75b13ead1. The active branch is codex/implement-vertical-skeleton-from-commit, and the latest reviewed code checkpoint is 31775b382e938507cd26ef3ec5d7d4d57c60e573.
- The branch contains the original Codex implementation (a88b3f7dbe3fc4dd972cf206d4174078cdb41cf5) plus six reviewed repair commits: Windows vault directory sync, vault initialization protection with restored error codes, proposal-session ownership binding, the real bridge vertical flow, the OpenAI reasoning-provider contract repair, and explicit reasoning-provider selection.
- Accepted bridge vertical-flow repair:
  - commit 9333d46de42548cb940a5d065eff7c543f9bb1bf
  - message: Implement real bridge vertical flow
  - parent: b276807f3cfb4a4d726f24ca059cc3c84b76011e
  - files: src/continuity_ai/bridge.py, tests/test_vertical_skeleton.py
  - targeted bridge/vertical-skeleton suite: 47 passed
  - full suite: 98 passed
- The real bridge vertical-flow blocker is now repaired:
  - commands delegate to real domain functions;
  - evidence combines project artifacts with confirmed encrypted attestations;
  - citation cards are hydrated from backend-owned records and spans;
  - attestation confirmation triggers evidence refresh and reanalysis;
  - analysis revision confirmation delegates to the real proposal flow;
  - vault replacement, unlock, and project load are atomic at the bridge-state boundary;
  - malformed commands and invalid field types return controlled public errors;
  - lock/unlock removes and restores decrypted attestation evidence correctly;
  - tests cover hostile provider prose and prove it cannot forge citation-card metadata.
- The OpenAI reasoning-provider contract blocker is now repaired:
  - the official OpenAI Python SDK and Responses API are used;
  - the request includes the question, complete evidence records, deterministic spans, a versioned prompt, and strict JSON Schema output;
  - store is false, tools are empty, and no streaming, background execution, previous response, or conversation chain is used;
  - provider output and failure modes fail safely before semantic validation by run_analysis;
  - URI, checksums, local paths, citation cards, and provider-owned display metadata are not sent to the model.
- The implicit fake-provider fallback blocker is now repaired:
  - provider selection is explicit, with openai and deterministic_offline as the supported configured values;
  - missing, blank, and unsupported configuration fails safely when no provider is injected;
  - injected providers retain precedence, including falsy injected providers;
  - selection and module import do not call the network;
  - DeterministicOfflineReasoningProvider is an explicitly selected test/demo provider only.
- Operating boundary: the repaired bridge, OpenAI adapter contract, and explicit provider selection still operate against a user-selected, already grouped candidate workspace. Semantic Project Resolution and Decision Scope Resolution are not implemented.
- Verification at the latest reviewed code checkpoint: focused stale-test regression 1 passed; targeted provider-selection suite 81 passed; full suite 131 passed; git diff --check passed; the normal non-force push completed; and the final working tree was clean.
- Semantic project identity and decision scope have not been live-evaluated. No successful live GPT-5.6 semantic-resolution or continuity-analysis result may be claimed.
- Do not claim Gate G-03 has passed.
- Do not claim PR #9 is ready to merge.
- Semantic Project Resolution and Decision Scope Resolution remain bounded implementation-planning work and prerequisites to stronger claims; the Cursor audit did not classify their absence as a current executable defect.
- Remaining unresolved blocker and completion groups:
  - conversation routing and grounding;
  - persistence of retained analyses, evidence snapshots, conversation history, the full audit trail, and confirmed analysis revisions;
  - controlled live-model evaluation;
  - final UI-to-bridge-to-OpenAI-to-UI end-to-end coverage;
  - consolidated default-suite network isolation;
  - a packaged demo runner.
- The semantic-resolution contract is frozen; its bounded implementation and any live evaluation remain pending.
- Gate G-03 has not passed. PR #9 is not merge-ready. No merge decision has been made.

## 2026-07-19 Generic Reasoning Fake Hardening

- The fixture-named reasoning fake and selector were removed. The explicitly
  selectable offline provider is now
  `DeterministicOfflineReasoningProvider` via
  `CONTINUITY_REASONING_PROVIDER=deterministic_offline`.
- The provider has a neutral deterministic contract: evidence and citations are
  sorted by identity, every semantic role is `none`, every Project Report
  section is an explicit canonical `evidence_gap`, and no continuity break or
  next action is inferred.
- The offline provider accepts arbitrary project identities and evidence IDs.
  Record order cannot assign or change semantic roles.
- Empty, duplicated, incomplete, or foreign evidence/span ownership fails closed
  with a provider error.
- This provider exists only for tests and offline integration fallback. Its
  schema-valid output does not demonstrate real-model generalization or establish
  that no real continuity break exists.
- Architectural boundary: typed candidate and grounding contracts live in
  `reasoning_contract.py`; deterministic candidate generation lives in
  `deterministic_offline_provider.py`; all semantic/schema validation lives in
  `analysis_validation.py`; and `reasoning_pipeline.py` is a thin stable
  orchestration facade.

## 2026-07-18 Read-Only Cursor Audit

- Audit HEAD: 63ddc6530eb242a41ae0ac920253030cbb6f08fa.
- The branch was clean before and after the audit. Nothing was staged, committed, or pushed.
- Full suite: 131 passed.
- Confirmed blocker groups:
  - retained-analysis and snapshot persistence;
  - historical citation hydration from live evidence instead of the retained snapshot;
  - conversation routing and grounding.
- Confirmed high-priority gaps:
  - conversation persistence;
  - exact attestation-statement extraction;
  - fake Aurora role mapping by list position.
- Test-hardening gaps:
  - default-suite socket isolation;
  - process-level UTF-8 NDJSON runner test;
  - supersession and validator negative tests.
- Semantic Resolution findings were classified as implementation-planning risks, not current defects.

## 2026-07-18 Approved First CC Repair Package

The first approved CC repair package is:

**Retained Analysis Persistence and Snapshot Fidelity**

Its authorized scope is limited to:

- persistence of complete initial `SavedAnalysis` and `EvidenceSnapshot`;
- snapshot-owned historical citation hydration;
- transactional saved-analysis persistence;
- restoration after lock/unlock and in a new `Bridge` instance;
- prevention of cross-vault in-memory analysis leakage.

Explicitly excluded from that first package:

- conversation routing;
- conversation persistence;
- confirmed revision persistence;
- Semantic Resolution implementation;
- network isolation;
- fake Aurora changes;
- documentation and pitch edits.

## Permanent Pitch Maintenance Rule

Any accepted MVP shortcut, deferred material risk, or change to a public capability claim MUST update `docs/PITCH_DRAFT.md` in the same documentation checkpoint that records the decision.

This rule applies to architectural decisions and accepted deferrals. It does not require pitch edits for ordinary implementation details. A closed risk MUST also be updated or removed from the pitch. No instance may treat `docs/PITCH_DRAFT.md` as optional administrative documentation.
