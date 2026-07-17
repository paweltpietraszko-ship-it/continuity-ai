# Security and Provenance Contract v0.1

Status: contract candidate for falsification before implementation
Gate: G-SEC-01 — Local Identity, Encrypted Vault, and Evidence Provenance
Scope: narrow Project Aurora MVP

## 1. Objective

G-SEC-01 provides the minimum trustworthy local state boundary required by conversation and user-created evidence.

It must establish:

- one authenticated local owner;
- one encrypted local vault;
- no anonymous project write path;
- append-only evidence history at the domain level;
- Authenticated User Attestations with explicit provenance;
- encrypted storage for application-created project state;
- no confidential content in ordinary technical logs.

This contract does not claim enterprise security or protection from a compromised unlocked operating system.

## 2. Ownership and Authentication

The MVP has exactly one local owner profile.

The owner profile contains:

- a stable random `actor_id`;
- an owner-selected display name;
- vault creation timestamp;
- no stored plaintext password.

A project write operation is permitted only through an active unlocked `VaultSession` associated with that owner.

The application must not attempt to decide whether the authenticated owner is substantively entitled to make a statement. Authentication establishes authority to add an owner attestation to this local project record.

## 3. Vault File

The MVP uses one encrypted local vault file rather than a database server.

The cleartext envelope may contain only:

- vault format version;
- KDF algorithm and parameters;
- random salt;
- encryption algorithm identifier;
- random nonce;
- authenticated ciphertext.

The encrypted payload contains application-created state, including:

- owner profile;
- Authenticated User Attestations;
- supersession links;
- conversation messages retained by the application;
- validated analyses retained by the application;
- audit events;
- schema version.

The vault does not copy original EML, ICS, XLSX, PDF, or Markdown source files in the MVP. Original files remain in user-controlled locations.

## 4. Cryptographic Construction

Implementation target:

- `cryptography>=49`;
- Argon2id password-based key derivation;
- 16-byte random salt;
- 32-byte derived key;
- authenticated encryption using `AESGCM`;
- a fresh random 12-byte nonce for every vault rewrite;
- authenticated additional data containing the vault format identifier and version.

Initial Argon2id parameters:

- iterations: 3;
- lanes: 4;
- memory cost: 64 MiB;
- output length: 32 bytes.

The implementation may tune parameters only through a reviewed contract correction. Parameters are stored in the cleartext envelope so future migration remains possible.

Wrong passwords and modified ciphertext must fail closed. They must never produce partial plaintext.

The password, derived key, decrypted payload, and API key must not be written to logs.

## 5. Atomic Persistence

A vault update must:

1. serialize the complete new plaintext payload deterministically;
2. encrypt it with a fresh nonce;
3. write to a temporary file in the same directory;
4. flush and close the temporary file;
5. replace the prior vault atomically;
6. preserve the previous file if encryption or temporary writing fails before replacement.

Logical evidence history is append-only even though the encrypted file is rewritten atomically.

## 6. Authenticated User Attestation

A user statement becomes evidence only after an explicit proposal-and-confirmation flow.

Conversation may produce a pending proposal:

```json
{
  "proposal_id": "random identifier",
  "statement": "exact proposed text",
  "channel": "text",
  "supersedes_evidence_id": null
}
```

A pending proposal is not evidence and must not affect analysis.

The UI displays the exact proposed text. Only an explicit confirmation control commits it.

The committed record contains:

```json
{
  "evidence_id": "EV-UA-<random identifier>",
  "source_type": "authenticated_user_attestation",
  "actor_id": "stable owner actor ID",
  "actor_display_name": "owner display name",
  "asserted_at": "UTC timestamp",
  "channel": "text",
  "statement": "exact confirmed text",
  "supersedes_evidence_id": null
}
```

MVP channel values are restricted to `text`. Voice is post-MVP.

The backend, not the model, assigns actor identity, timestamp, and evidence ID.

## 7. Corrections and Supersession

Committed evidence is never edited or deleted through the normal product interface.

A correction creates a new attestation with `supersedes_evidence_id` pointing to an existing attestation created by the same owner.

Supersession does not erase the earlier record. Current effective state is derived from the complete chain.

The system must reject:

- a supersession target that does not exist;
- a supersession target that is artifact evidence;
- self-supersession;
- a supersession cycle;
- duplicate evidence IDs.

## 8. Evidence Boundary

G-02 `EvidenceRecord` remains unchanged.

G-SEC-01 introduces `AuthenticatedUserAttestation` as a separate typed record.

Reasoning receives a canonical read-only union produced by an adapter:

```text
Artifact EvidenceRecord | AuthenticatedUserAttestation
        -> ReasoningEvidence
```

The adapter preserves source type and provenance. It must not disguise a user attestation as an email, calendar event, spreadsheet, PDF, or note.

## 9. Conversation Storage

Conversation stored by Continuity AI is encrypted inside the vault.

For the MVP, conversation persistence is local only. The application does not use the OpenAI Conversations endpoint as project memory.

Locking the vault removes access to retained conversation and project-created evidence until the owner unlocks it again.

## 10. External Model Boundary

`OPENAI_API_KEY` and the configured model identifier are read from environment configuration during development.

They are not committed to the repository and are not stored in the project vault in G-SEC-01.

The UI must disclose that locally stored application data is encrypted while selected evidence and conversation context may be sent to the configured OpenAI API.

LynxMask integration is explicitly outside this gate.

## 11. Audit Events

Every committed project write creates an audit event containing only:

- event ID;
- event type;
- actor ID;
- UTC timestamp;
- affected evidence ID or analysis ID;
- success state.

An audit event must not duplicate confidential statement or conversation content.

Minimum event types:

- `vault_created`;
- `vault_unlocked`;
- `vault_locked`;
- `attestation_committed`;
- `attestation_superseded`;
- `analysis_saved`;
- `conversation_message_saved`.

Failed password attempts are not written into the encrypted vault because the vault is unavailable. They may be counted in volatile process state without logging the attempted password.

## 12. Logging Rules

Ordinary technical logs must not contain:

- artifact content;
- evidence span text;
- attestation statements;
- conversation messages;
- prompts;
- model outputs;
- passwords;
- derived keys;
- API keys;
- decrypted vault payloads.

Logs may contain opaque IDs, timestamps, operation names, duration, and controlled error categories.

## 13. Failure Model

Controlled failures include:

- `VaultAlreadyExistsError`;
- `VaultNotFoundError`;
- `VaultLockedError`;
- `VaultAuthenticationError`;
- `VaultIntegrityError`;
- `VaultFormatError`;
- `AttestationValidationError`;
- `SupersessionError`.

Authentication, integrity, or format failure returns no decrypted state.

## 14. Required Tests

Tests must prove:

- vault create, lock, and unlock;
- correct password round trip;
- wrong password fails closed;
- one-bit ciphertext modification fails closed;
- salt and nonce differ across independently created or rewritten vaults;
- known confidential plaintext is absent from vault bytes;
- interrupted pre-replacement write preserves the previous vault;
- writes require an unlocked owner session;
- pending attestation proposals do not enter evidence;
- confirmation commits exactly the displayed statement;
- backend assigns actor, timestamp, channel, and evidence ID;
- supersession preserves the earlier record;
- missing, artifact, self, and cyclic supersession are rejected;
- technical logs contain no supplied confidential canary text;
- G-02 ingestion tests remain unchanged and green.

## 15. Skeleton Target vs Gate Completion

The first vertical skeleton is complete when:

- the vault can be created, locked, and unlocked;
- one attestation can be proposed, confirmed, encrypted, reopened, and read;
- one superseding attestation can be appended;
- the canonical reasoning-evidence adapter exposes artifact and attestation provenance;
- core tests for password failure, ciphertext tampering, and plaintext absence pass.

G-SEC-01 is not fully passed until all required tests, independent audit, merge, and post-merge verification are complete.

## 16. Explicit Exclusions

This gate does not implement:

- biometric authentication;
- password recovery;
- multiple owners;
- roles or permissions;
- cloud synchronization;
- remote backup;
- hardware-backed key storage;
- secure deletion guarantees;
- protection from malware in an unlocked process;
- source-file encryption;
- LynxMask;
- voice capture;
- autonomous actions.
