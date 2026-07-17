# Codex Vertical Skeleton Implementation Prompt — Draft

Status: prepared in advance; do not execute until PR #8 contract falsification is resolved and the contracts are frozen.

---

You are the primary implementation engineer for the Continuity AI vertical skeleton.

Repository:

- `paweltpietraszko-ship-it/continuity-ai`
- Start from the frozen post-contract `main` commit named by the coordinator.
- Create a new branch: `feat/vertical-skeleton`.
- Do not implement on the documentation-contract branch.

Read before editing:

- `docs/SCOPE_AND_GROUND_TRUTH.md`
- `docs/CURRENT_STATE.md`
- `docs/SECURITY_AND_PROVENANCE_CONTRACT_v0.1.md`
- `docs/GATE_G03_CONTRACT_v0.2.md`
- `docs/GATE_G03_CLOSED_EVIDENCE_WORLD_ADDENDUM.md`
- `docs/SKELETON_BUILD_PLAN.md`

Goal:

Implement the thinnest real end-to-end vertical path:

```text
Project Aurora artifacts
-> existing deterministic G-02 ingestion
-> canonical reasoning evidence
-> deterministic evidence spans
-> validated fake-provider analysis
-> OpenAI provider seam
-> persistent conversation turn
-> explicit attestation proposal and confirmation
-> encrypted local vault
-> re-analysis with committed attestation
-> stable JSON bridge for the UI
```

This is a vertical skeleton, not a finished product.

## Hard invariants

1. Keep the existing G-02 `EvidenceRecord` unchanged.
2. Production code must not read, name, construct, import, or receive test-only ground truth or Aurora expected answers.
3. Project-grounded outputs operate in a closed evidence world.
4. Unknown `evidence_id` or `span_id`, cross-record-invalid references, or one invalid source reference invalidate the complete semantic result.
5. The model never owns canonical source metadata. Titles, authors, actors, timestamps, source types, provenance, paths, evidence IDs, exact quotations, and citation cards are hydrated from backend-owned records.
6. Model output may reference only supplied evidence IDs and deterministic span IDs.
7. Model text never becomes evidence without explicit authenticated-owner confirmation.
8. Conversation does not silently mutate evidence or the validated analysis.
9. A confirmed attestation is appended; corrections use supersession and never silently overwrite history.
10. No confidential content in normal logs, tracebacks, temporary plaintext files, test output, or bridge errors.
11. No network access in the default test suite.
12. No autonomous document, calendar, call-sheet, email, or message changes.

## Required implementation slices

### A. Typed contracts

Add typed immutable domain models for at least:

- `ReasoningEvidence`
- `EvidenceSpan`
- `AuthenticatedUserAttestation`
- `AttestationProposal`
- `SemanticAnnotation`
- grounded statement type
- `AnalysisResult`
- `ConversationResponse`
- vault payload/session models
- controlled error categories

Use strict validation and explicit discriminators for break/no-break and conversation response kinds. Do not add fixture-specific fields to production types.

### B. Encrypted vault core

Implement one local-owner encrypted application vault.

Requirements:

- password-derived key using Argon2id;
- authenticated encryption using AES-GCM;
- fresh random salt for vault creation;
- fresh unique nonce for every encryption operation;
- atomic write through same-directory temporary file, flush/fsync where supported, then replacement;
- wrong password and tampered ciphertext fail closed;
- no plaintext fallback;
- lock invalidates the active write session;
- attestation, conversation, analysis, owner profile, and audit events are inside encrypted payload;
- append-only logical evidence/audit history;
- supersession target must exist and supersession cycles are rejected;
- ordinary exceptions do not expose vault contents or password material.

The skeleton may use a single encrypted file rather than SQLite. Make crypto parameters explicit and testable. Do not invent password recovery, biometrics, multiple users, or cloud synchronization.

### C. Evidence adapter and deterministic spans

Implement:

- adapter from existing G-02 artifact `EvidenceRecord` to `ReasoningEvidence`;
- adapter from confirmed user attestation to `ReasoningEvidence`;
- chronological ordering by normalized UTC timestamp and then `evidence_id`;
- deterministic non-empty line spans with IDs `<evidence_id>:L001`;
- stable lookup from span ID to canonical evidence record and exact text;
- citation hydration objects generated only by backend code.

An attestation becomes available to reasoning only after confirmation and encrypted commit.

### D. Reasoning core and universal validator

Implement a provider protocol and deterministic fake provider.

Support:

- `break_found`;
- `no_material_break_found`;
- current-state grounded statement;
- complete semantic annotations, exactly one per supplied evidence record;
- nullable continuity break and next action according to status;
- grounding through span IDs;
- complete-result rejection after any schema, ID, span, ownership, enum, or consistency failure.

The production validator verifies structure, identifier resolution, provenance, and internal consistency only. It must not claim to prove semantic truth and must not encode Project Aurora expected roles or sentences.

Replace the intentionally failing acceptance test with a real offline pipeline acceptance test using the fake provider. Preserve a test-only Aurora evaluation profile separately from production code.

### E. OpenAI adapter seam

Use the official OpenAI Python SDK and Responses API with:

- model from `CONTINUITY_OPENAI_MODEL`;
- API key from `OPENAI_API_KEY`;
- strict structured output;
- `store=False`;
- no tools;
- no streaming;
- no background mode;
- controlled provider/refusal/output errors.

Do not guess or hard-code a GPT-5.6 API model identifier. Unit-test the adapter through a fake client. A real network call must be opt-in and excluded from default pytest.

### F. Conversation and attestation

Implement response kinds:

- `project_grounded`
- `project_hypothetical`
- `general`
- `analysis_revision`
- `insufficient_evidence`
- `external_data_unavailable`
- `attestation_proposal`

Rules:

- `project_grounded` requires valid supplied spans;
- project source cards are hydrated from canonical backend records;
- `general` conversation does not require Project Aurora citations;
- a query about a nonexistent project source returns `insufficient_evidence` without speculative contents;
- `analysis_revision` contains a complete replacement analysis and passes the same validator;
- `attestation_proposal` does not write evidence;
- confirmation is a separate deterministic command carrying the proposal ID;
- after confirmation, commit to vault and perform full re-analysis with the expanded evidence set.

### G. Stable JSON bridge

Extend the CLI or create a narrow bridge that supports stable JSON commands:

- `initialize_vault`
- `unlock_vault`
- `lock_vault`
- `load_project`
- `analyze_project`
- `send_message`
- `confirm_attestation`
- `get_workspace_state`

Use newline-delimited JSON or an equivalent deterministic request/response protocol.

Every response contains:

```json
{
  "ok": true,
  "command": "...",
  "data": {}
}
```

or:

```json
{
  "ok": false,
  "command": "...",
  "error": {
    "code": "controlled_code",
    "message": "safe public message"
  }
}
```

No confidential traceback in normal bridge output. UI-facing citation objects must contain backend-hydrated canonical metadata and exact span text.

## Required offline tests

At minimum add tests for:

- existing fixture and ingestion regression;
- vault round trip;
- wrong password;
- tamper detection;
- plaintext canary absent from vault file;
- write rejected while locked;
- nonce uniqueness across writes;
- interrupted/failed temporary write does not destroy last valid vault;
- attestation append and persistence after close/reopen;
- valid supersession;
- missing supersession target;
- supersession cycle rejection;
- deterministic span generation and stable IDs;
- artifact versus attestation provenance;
- valid break result;
- valid no-break result;
- fabricated evidence ID;
- fabricated span suffix under a real evidence ID;
- valid span attributed to the wrong evidence record;
- one invalid citation rejects the entire result;
- project-grounded reply with no spans;
- project-grounded reply with an unknown span;
- nonexistent project document returns `insufficient_evidence` without speculation;
- fake provider attempts to supply title, author, quote, timestamp, or path and strict schema rejects or ignores those fields in favor of canonical hydration;
- model text cannot commit an attestation;
- proposal confirmation requires an unlocked authenticated session;
- committed attestation is present in the next reasoning input;
- prompt snapshot and forbidden Aurora literals;
- hostile evidence text is treated as evidence data, not instructions;
- OpenAI adapter options are strict, tool-free, non-streaming, non-background, and `store=False`;
- production reasoning and vault modules do not import fixture ground truth or Aurora expected answers.

## Target state for this implementation pass

Required:

- all existing tests remain green;
- new vault, span, validation, conversation, and bridge tests are green;
- one offline Aurora flow works through the stable bridge;
- one attestation is proposed, explicitly confirmed, encrypted, survives reopen, and enters re-analysis;
- the fake-provider pipeline returns a validated analysis with backend-hydrated citations;
- OpenAI adapter exists and is tested through a fake client.

Desirable, not required for the skeleton:

- one successful live Aurora call;
- full UI integration;
- polished user-facing errors;
- final cryptographic parameter benchmark;
- final live semantic evaluation.

## Stop rules

Stop and report instead of improvising when:

- a required change would modify G-02 `EvidenceRecord`;
- production code appears to require Aurora expected answers;
- semantic truth would need to be guessed by deterministic validation;
- confidential plaintext would need to be persisted outside the vault;
- the UI requires an autonomous source mutation;
- an unavailable or uncertain API capability would need to be invented;
- a proposed change falls outside the vertical skeleton.

## Deliverables

1. Working branch with complete files, not snippets.
2. Updated `uv.lock` and dependency declarations.
3. Tests and exact commands executed.
4. `docs/BUILD_LOG.md` update.
5. `docs/CURRENT_STATE.md` update that distinguishes implemented, tested, untested, and deferred behavior.
6. Pull request with a precise summary, test evidence, known limitations, and explicit statement that live semantic quality is not proven by fake-provider tests.

Before coding, inspect the repository and return a concise implementation plan plus the exact files you intend to modify or create. Then implement without waiting for another approval unless a stop rule is reached.
