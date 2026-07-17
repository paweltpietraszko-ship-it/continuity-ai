# Vertical Skeleton Build Plan

Status: execution plan for the next implementation day
Purpose: produce a real end-to-end skeleton, not a finished product

## 1. Definition of Skeleton

The skeleton is the thinnest integrated path that proves the accepted architecture can work:

```text
Project Aurora files
-> deterministic ingestion
-> canonical project evidence
-> deterministic evidence spans
-> reasoning provider boundary
-> validated analysis JSON
-> persistent conversation turn
-> confirmed authenticated user attestation
-> encrypted local vault
-> re-analysis after new evidence
-> stable JSON bridge for UI
```

The skeleton may still have limited error presentation, incomplete UI wiring, provisional cryptographic parameter tuning, and missing final audit coverage. It must not contain fake production answers or bypass the real boundaries.

## 2. Implementation Order

### Slice A — Contracts and Types

Create typed immutable models for:

- `ReasoningEvidence`;
- `EvidenceSpan`;
- `AuthenticatedUserAttestation`;
- `AttestationProposal`;
- `AnalysisResult`;
- `SemanticAnnotation`;
- `ConversationResponse`;
- `VaultSession`;
- controlled error categories.

Keep the existing G-02 `EvidenceRecord` unchanged.

### Slice B — Encrypted Vault Core

Implement:

- vault creation;
- Argon2id key derivation;
- AES-GCM encryption and authentication;
- lock and unlock;
- atomic rewrite;
- owner profile;
- audit-event append;
- attestation append and supersession validation.

Minimum tests:

- round trip;
- wrong password;
- tamper detection;
- plaintext canary absent from file;
- write requires unlocked session;
- supersession preserves history.

### Slice C — Evidence Adapter and Spans

Implement:

- adapter from artifact `EvidenceRecord` to `ReasoningEvidence`;
- adapter from confirmed owner attestation to `ReasoningEvidence`;
- deterministic line spans;
- stable span lookup;
- complete provenance preservation.

Minimum tests:

- current five Aurora records keep chronological order;
- spans are stable across runs;
- artifact and attestation source types remain distinguishable.

### Slice D — Reasoning Core with Fake Provider

Implement:

- provider protocol;
- strict analysis candidate models;
- universal validator;
- `break_found` and `no_material_break_found`;
- complete-result failure on any invalid ID or span;
- revised pipeline acceptance test using a deterministic fake provider.

At the end of Slice D, the former intentionally failing acceptance test must become a real pipeline acceptance test and pass without network access.

### Slice E — OpenAI Adapter

Implement:

- official OpenAI Python SDK dependency;
- Responses API call;
- configured `CONTINUITY_OPENAI_MODEL`;
- strict JSON schema;
- `store=False`;
- no tools, streaming, or background mode;
- controlled provider and refusal errors.

Do not guess the GPT-5.6 API identifier. Verify account availability before the first live call and record the selected identifier.

### Slice F — Conversation and Attestation Proposal

Implement:

- one general conversation turn;
- one project-grounded turn with span references;
- one insufficient-evidence turn;
- one attestation proposal;
- explicit deterministic confirmation;
- encrypted commit to vault;
- complete re-analysis after confirmation.

Conversation history used by the application is stored locally in the encrypted vault.

### Slice G — Stable UI Bridge

Expose newline-delimited JSON or equivalent stable JSON commands for:

- `initialize_vault`;
- `unlock_vault`;
- `lock_vault`;
- `load_project`;
- `analyze_project`;
- `send_message`;
- `confirm_attestation`;
- `get_workspace_state`.

Every response contains:

- `ok`;
- `command`;
- `data` or controlled `error`;
- no confidential technical traceback in normal output.

The bridge is the UI contract. The UI must not import Python domain modules or infer semantic classifications.

## 3. Target State by End of the Next Implementation Day

Required:

- all existing fixture and ingestion tests remain green;
- vault core tests are green;
- span tests are green;
- fake-provider analysis pipeline is green;
- stable JSON bridge can run one complete Aurora flow;
- one confirmed attestation survives vault close and reopen;
- re-analysis receives that attestation with correct provenance;
- OpenAI adapter exists and is unit tested through a fake client;
- a live call is attempted only when model access and credentials are verified.

Desirable but not required for the skeleton:

- first successful live Aurora analysis;
- UI connected to every bridge command;
- polished error states;
- full conversation persistence UX;
- final cryptographic parameter benchmark.

## 4. Work After the Skeleton

After the vertical path exists, remaining work is stabilization rather than architecture invention:

- Fable falsification decisions incorporated;
- Cursor code and contract audit;
- live-model evaluation window;
- hostile-evidence test;
- Windows packaging and bridge reliability;
- UI integration and visual state corrections;
- film capture from the real application;
- README and competition evidence;
- final regression and post-merge verification.

## 5. Stop Rules

During skeleton implementation, stop and escalate instead of improvising when:

- a change would modify the G-02 `EvidenceRecord` contract;
- production code would need Aurora expected answers;
- a provider output cannot be validated without semantic guessing;
- a UI requirement would require autonomous source modification;
- security implementation would log or persist plaintext confidential data outside the encrypted vault;
- a new feature is proposed that is not required by the vertical path.

## 6. Explicit Non-Goals for the Skeleton

Do not implement:

- LynxMask;
- voice capture;
- web or weather tools;
- biometric unlock;
- password recovery;
- multiple users or projects;
- cloud synchronization;
- automatic document changes;
- production installer polish;
- multi-model review inside the application.
