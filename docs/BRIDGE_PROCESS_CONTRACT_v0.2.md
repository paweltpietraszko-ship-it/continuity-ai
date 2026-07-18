# Bridge Process Contract v0.2

Status: normative backend handoff to the desktop/Tauri UI instance.
Supersedes: `docs/BRIDGE_PROCESS_CONTRACT_v0.1.md`, which is retained as the historical record of the schema `2.0` contract and must not be used as ground truth for the current codebase.
Ground truth: `src/continuity_ai/bridge.py`, `src/continuity_ai/bridge_main.py`, and their direct dependencies, as they exist on this branch. This document describes only what that code currently does.

## What changed since v0.1

This revision reflects the Project Report contract, schema `3.0`:

- every `AnalysisResult` now includes a mandatory `project_report` (a whole-project summary across seven fixed sections; section 10 documents the exact frozen field names);
- `load_project` and `get_workspace_state` now carry an explicit `project` identity and a neutral `evidence_records` projection;
- `analyze_project`'s success response also carries `project` (section 4), sourced from the authoritative `Bridge.project`, never from provider output;
- retained analyses now bind their `project` alongside their evidence snapshot; loading a different project while a retained analysis is active is rejected atomically as `project_mismatch`;
- `initialize_vault`, `unlock_vault`, and `get_workspace_state` now expose `owner_display_name` (`null` while locked);
- retained analyses from schema `2.0` are rejected as `retained_analysis_status: "invalid"` with no migration path;
- `initialize_vault` and `unlock_vault` never compose the new vault's evidence against the previous vault's `artifact_records`: switching vaults always clears live artifact evidence (`project`, `artifact_evidence_count`, `evidence_count`, `evidence_records` all reset) until `load_project` is called again for the newly active vault (section 9);
- every grounded span list (`current_state`, `continuity_break`, `next_action`, `project_report.summary`, and each `project_report` section) rejects a repeated span ID rather than silently deduplicating it;
- `evidence_manifest.json`'s `project` field must be a canonical string — non-empty after trimming and free of leading/trailing whitespace — or ingestion fails; a non-canonical name is never silently trimmed (section 9).

## 1. Process startup

Canonical command:

```text
python -m continuity_ai.bridge_main
```

The parent process must set the reasoning provider explicitly via environment variables. Provider selection is never silent:

- for deterministic local tests or development:

  ```text
  CONTINUITY_REASONING_PROVIDER=fake_aurora
  ```

- for a real provider run:

  ```text
  CONTINUITY_REASONING_PROVIDER=openai
  CONTINUITY_OPENAI_MODEL=<explicit model>
  OPENAI_API_KEY=<secret>
  ```

Rules:

- `CONTINUITY_REASONING_PROVIDER` missing, blank, or set to any value other than `openai` or `fake_aurora` causes the process to fail at startup (`Bridge()` construction raises before the read loop begins; `bridge_main.main()` returns exit code `1` with empty stdout and empty stderr).
- `fake_aurora` is test/development infrastructure only. It must never be presented to the user as a live model run.
- The parent process is responsible for setting `OPENAI_API_KEY` and `CONTINUITY_OPENAI_MODEL` when selecting `openai`; the Bridge process performs no other provider configuration.

## 2. Transport

- The Bridge runs as a single persistent child process for the lifetime of one working session; it is not restarted per command.
- Communication uses the process's binary stdin and stdout.
- Encoding is UTF-8 on both directions.
- Protocol is newline-delimited JSON: exactly one JSON object per input line, exactly one JSON object per output line, in the same order commands were sent.
- stdout carries protocol responses only. No banner, log line, or diagnostic text is ever written to stdout.
- stderr is not part of the protocol and must not be parsed by the parent.
- A clean EOF on stdin (parent closes stdin, e.g. by closing the pipe) causes the process to exit with code `0`.
- Malformed input (invalid UTF-8, invalid JSON, a JSON value that is not an object) produces exactly one controlled error response on stdout for that line, and the process continues reading subsequent lines normally.
- No OS-level process sandboxing or socket isolation is claimed by this contract. The default test suite blocks accidental socket access, while bridge process tests use an explicit offline provider and make no network requests.

## 3. Response envelope

Success:

```json
{
  "ok": true,
  "command": "<command>",
  "data": {}
}
```

Failure:

```json
{
  "ok": false,
  "command": "<command-or-null>",
  "error": {
    "code": "<public-code>",
    "message": "<public-message>",
    "object_id": null
  }
}
```

`command` is `null` in the failure envelope only when the input line could not be parsed into a dict with a valid `command` field at all (malformed JSON/UTF-8, non-object payload, missing or non-string `command`). For a recognized-but-failing command, `command` echoes the requested command name.

Internal exceptions, tracebacks, passwords, API keys, decrypted content, and filesystem paths must never appear in `error.message` or `error.object_id`. Every controlled error the Bridge can currently raise serializes to exactly the three fields above, with a fixed, safe, human-readable `message` and `object_id` always `null` in the current codebase.

## 4. Supported command contract

All commands are sent as a single JSON object with a `command` field. Fields not listed below are ignored; a missing required field, or a field of the wrong type, produces a controlled `validation_error`.

### `initialize_vault`

- Required: `path` (string), `password` (string, non-blank after trim)
- Optional: `owner_name` (string; defaults to `"Owner"` if omitted, must be non-blank if supplied)
- Success data: `{"session_id": "<string>", "owner_display_name": "<string>"}`
- Failure categories: `vault_already_exists` (a vault file already exists at `path`); `validation_error` (blank owner name/password, malformed request, or evidence-composition failure)
- Establishing (or replacing) the active vault always clears any previously loaded project identity and retained analysis in Bridge memory before restoring from the new vault (section 6, section 9).

### `unlock_vault`

- Required: `path` (string), `password` (string)
- Success data: `{"session_id": "<string>", "owner_display_name": "<string>"}`
- Failure categories: `vault_auth_failed` (wrong password or unreadable/corrupt vault file); `validation_error` (malformed request or evidence-composition failure)
- A failed `unlock_vault` never replaces the Bridge's currently active vault or session.

### `lock_vault`

- Required fields: none
- Success data: `{"locked": true}`
- Failure categories: `vault_locked` (no vault has ever been initialized or unlocked in this process)
- Effect: clears decrypted attestation evidence, `owner_display_name`, and the in-memory analysis/snapshot/question/`project_report` from Bridge state. The currently loaded `project` and `evidence_records` are unaffected — they describe live artifact evidence, not vault-derived state. The encrypted vault file and its retained analyses are untouched.

### `load_project`

- Required: `artifact_root` (string; path to the artifact directory only, not the vault)
- Success data: `{"project": "<string>", "artifact_evidence_count": <int>, "evidence_count": <int>, "evidence_records": [...]}` (section 9 for `evidence_records`)
- Failure categories:
  - `validation_error` (missing artifact root, malformed evidence manifest, checksum mismatch between a manifest entry and the file on disk, or any other ingestion failure);
  - `project_mismatch` (the manifest's `project` differs from the project of the currently active in-memory analysis — see below).
- A failed `load_project` (either category) leaves all prior Bridge state (`project`, artifact records, composed records, spans, `evidence_records`, retained analysis, snapshot, question) exactly as it was before the call.
- A successful `load_project` re-evaluates the retained analysis from the currently active vault (see section 6); it does not invoke the reasoning provider.
- **Project mismatch**: a retained analysis is grounded in one specific project. If an analysis is currently active in Bridge memory and the newly loaded manifest declares a different `project`, the call is rejected atomically:

  ```json
  {
    "ok": false,
    "command": "load_project",
    "error": {
      "code": "project_mismatch",
      "message": "The selected project does not match the retained analysis.",
      "object_id": null
    }
  }
  ```

  When no analysis is currently active (fresh session, locked vault, or a vault with no retained analysis), `load_project` accepts whatever project the manifest declares and establishes it as the current project identity.

### `analyze_project`

- Required: `question` (string, non-blank after trim)
- Preconditions: at least one evidence record must already be composed (`load_project` and/or an unlocked vault with attestations), and a `project` must already be established (i.e. `load_project` has succeeded at least once in this process)
- Success data: `project` (the authoritative `Bridge.project`, never taken from provider output), current-state, continuity-break, next-action, semantic-annotation, and `project_report` fields (section 10), `citation_cards` (section 7), and snapshot metadata: `analysis_id`, `created_at`, `prompt_version`, `schema_version`, `provider_id`
- Failure categories: `validation_error` (no evidence loaded, no project established, blank/non-string question, or the reasoning provider's output failing the canonical semantic validator); `provider_error` (the configured provider itself fails)
- If the vault is currently unlocked, the analysis (bound to the current `project`) is transactionally persisted to the encrypted vault before this response is returned, and `retained_analysis_status` becomes `valid`. If no vault is unlocked at the time of the call, the analysis is still produced and returned, but it is not retained; `retained_analysis_status` becomes `none`. It is never reported as `valid` unless persistence actually succeeded.

### `send_message`

- Required: `message` (string)
- Optional: `revision_candidate` (a complete candidate analysis object; only meaningful together with an unlocked vault)
- Success data: a conversation response (`kind`, `message`, and, depending on `kind`, `citation_cards`, `attestation_proposal`, or `analysis_revision_proposal`)
- Failure categories: `vault_locked` (an attestation or revision was requested but no vault is unlocked)

### `confirm_attestation`

- Required: `proposal_id` (string)
- Preconditions: an unlocked vault and an existing in-memory analysis
- Success data: `evidence_id`, `evidence_count`, `citation_cards`, and current analysis fields (the analysis is recomputed against the newly confirmed evidence; this recomputed analysis is not itself persisted — see the excluded scope in section 8)
- Failure categories: `vault_locked` (no vault, or vault locked); `validation_error` (no prior analysis/question, or the proposal ID does not belong to the current session)

### `confirm_analysis_revision`

- Required: `proposal_id` (string)
- Preconditions: an unlocked vault with a matching pending revision proposal
- Success data: `confirmed: true`, `proposal_id`, `citation_cards`, and the revised analysis fields
- Failure categories: `vault_locked` (no vault, or vault locked); `validation_error` (unknown or already-confirmed proposal ID)

### `get_workspace_state`

- Required fields: none
- Success data: always includes the fields in section 6; includes analysis and citation fields only when a valid analysis is currently available (section 6)
- This command never fails with a controlled error in the current implementation; it always returns `ok: true`.

## 5. Competition UI sequence

Minimum filmable backend sequence:

```text
initialize_vault or unlock_vault
→ load_project
→ get_workspace_state
→ analyze_project
→ get_workspace_state
→ lock_vault
```

Restart sequence:

```text
start a new bridge_main process
→ unlock_vault
→ get_workspace_state
→ load_project
→ get_workspace_state
```

Explicit guarantees for the restart sequence:

- After restart and `unlock_vault`, a valid retained analysis (if one was successfully persisted before the restart) is restored from the encrypted vault, together with its `project` and complete `project_report`. The parent must not send `analyze_project` merely to display restored history.
- Restoration never invokes the reasoning provider.
- After current evidence is loaded (`load_project`), citation `source_status` is recomputed against that evidence the next time `get_workspace_state` or `analyze_project` hydrates cards.
- Historical `exact_text` and citation metadata remain snapshot-owned regardless of what `load_project` reloads.
- If `load_project` is called with evidence belonging to a different project than the restored analysis, it is rejected as `project_mismatch` (section 4) and the restored analysis remains exactly as it was.

## 6. Workspace-state semantics

`get_workspace_state` always returns:

```text
vault_unlocked             bool
owner_display_name         string | null  — the vault owner's display name when unlocked, null while locked or with no vault (section 9)
project                    string | null  — the currently established project identity (section 9)
artifact_evidence_count    int   — records ingested by the most recent successful load_project
evidence_count             int   — artifact records combined with any decrypted attestations
evidence_records           array — the neutral G-02 evidence projection (section 9); [] when nothing is loaded
has_analysis               bool
retained_analysis_status   string — "none" | "valid" | "invalid"
project_report              object | null — present only when `has_analysis` is true (section 10); otherwise `null`
pending_attestation_count  int
pending_revision_count     int
```

When `has_analysis` is `true`, the response additionally includes:

```text
analysis_status
continuity_break_kind
current_state
semantic_annotations
continuity_break
next_action
citation_cards
```

(`project_report` is always present as a key; its value is populated only when `has_analysis` is `true`, otherwise `null`. `owner_display_name`, `project`, and `evidence_records` are populated independently of `has_analysis`.)

`retained_analysis_status` values and meaning:

- `none` — no successfully retained analysis is currently available (fresh vault, locked vault, vault switched, or the most recent `analyze_project` ran without an unlocked vault).
- `valid` — the newest retained analysis (from a persisted `analyze_project`, or restored from the encrypted vault on `initialize_vault`/`unlock_vault`/`load_project`) passed canonical restoration validation and is the currently active analysis.
- `invalid` — the newest retained entry in the vault failed canonical restoration validation. There is deliberately no fallback to an older valid entry: an invalid newest entry never causes stale history to be silently presented as current. This includes any retained entry from the superseded schema `2.0` contract — there is no migration path.

When `retained_analysis_status` is `invalid`, `has_analysis` is `false` and none of the analysis fields or `citation_cards` are present in the response (`project_report` is `null`). Vault authentication and the neutral `evidence_count`/`artifact_evidence_count`/`project`/`evidence_records` fields remain available regardless.

## 7. Citation-card contract

Every citation card has exactly these fields:

```text
evidence_id
span_id
exact_text
title
author_or_actor
timestamp
source_type
provenance
source_status
```

`source_status` values currently observable through this path:

- `snapshot` — the citation's underlying evidence, as currently loaded (or as of the last comparison performed), matches the canonical content hash recorded at analysis time; this is also the value used whenever no live evidence is loaded to compare against, since no honest comparison claim can be made in that case.
- `source_changed_since_analysis` — the corresponding evidence ID's current content hash (or its absence from currently loaded evidence) no longer matches the hash recorded in the retained snapshot.

Rules:

- `exact_text`, `title`, `author_or_actor`, `timestamp`, `source_type`, and `provenance` always come from the retained `EvidenceSnapshot`, never from live re-ingested files.
- Only `source_status` is recomputed against whatever evidence is currently loaded in the Bridge process.
- `citation_cards` is the ordered, deduplicated union of every span ID referenced by `current_state`, `continuity_break`, `next_action`, `project_report.summary`, and every `project_report.sections[*]` entry, in that order.
- The frontend must not reconstruct citation content from model prose, current files, or any source other than the fields listed above.

## 8. Trust boundary

Backend owns:

```text
ingestion validation (evidence manifest, checksum verification, format parsing)
evidence normalization and ordering
project identity (evidence_manifest.json "project", project_mismatch protection)
semantic validation of analysis results (initial and restored), including project_report
continuity-break result, next action
citation hydration and source-status computation
retained-analysis structural and semantic validation, and the fail-closed newest-entry policy
vault encryption, key derivation, and transactional persistence
the public controlled-error boundary
```

Desktop/Tauri owns:

```text
process lifecycle (starting, restarting, and stopping bridge_main)
trusted local path selection (vault file, artifact root)
passing commands over stdin and reading responses from stdout
displaying backend-returned fields as-is, including the owner_display_name fallback text "Local owner" before any vault is unlocked
```

The UI must not infer evidence ownership, semantic roles, source status, continuity-break kind, project-report status, quotations, evidence/span IDs, or next action; it only displays what the Bridge response already contains. This document does not prescribe visual design or Rust implementation details.

## 9. Project identity, the evidence_records projection, and owner privacy

**`project`** is read exclusively from the `project` field of `evidence_manifest.json` at the root of the loaded `artifact_root`. It is never derived from a directory name, a fixture constant, or any other source. It is bound into `SavedAnalysis` alongside the evidence snapshot, persisted encrypted in the vault, and restored together with the rest of the retained analysis (section 5).

The manifest's `project` value must be canonical: a non-empty string with no leading or trailing whitespace. A blank, whitespace-only, or leading/trailing-whitespace-padded value fails ingestion outright (`validation_error` from `load_project`); it is never silently trimmed to a canonical form.

**Vault-switch isolation**: a successful `initialize_vault` or `unlock_vault` never composes the new vault's evidence against whatever `artifact_records` a previous vault had loaded. `project`, `artifact_records`, `artifact_evidence_records`, `records`, and `spans` are all reset before the new vault's own retained analysis (if any) is restored. Concretely: immediately after a vault switch and before any `load_project` call, `artifact_evidence_count == 0`, `evidence_count == 0` (or only the new vault's own decrypted attestations, if it has any), and `evidence_records == []`, regardless of what was loaded for the previous vault. A valid retained analysis for the newly active vault still restores its own `project` and `project_report` at this point — only the *live artifact* projection is cleared, not the retained history.

**`evidence_records`** is a full, neutral projection of the ingested (G-02) evidence — no interpretive, semantic, or analysis-derived content. Each entry contains exactly:

```text
source_id
evidence_id
author
timestamp
source_type
title
uri
artifact_sha256
content
```

This is the same shape ingestion already produces for every artifact; the Bridge does not add, remove, or reinterpret fields when exposing it.

**`owner_display_name`** is read from the vault's already-encrypted owner profile (`payload["owner"]["display_name"]`) purely for display; it is never written to the plaintext vault envelope (the on-disk file's outer JSON keeps exactly `format`, `version`, `kdf`, `salt`, `encryption`, `nonce`, `ciphertext` — the owner's name lives only inside the encrypted `ciphertext`). It is `null` whenever no vault is unlocked. Before any vault is unlocked, the UI displays the fixed text `Local owner` instead of inventing or caching a name.

## 10. Project Report shape (frozen)

`project_report` (present whenever `has_analysis` is `true`, on `analyze_project` and `get_workspace_state`) is:

```json
{
  "summary": {"statement": "<string>", "span_ids": ["<span-id>", "..."]},
  "sections": [
    {"key": "decision", "status": "confirmed", "headline": "<string>", "detail": "<string>", "span_ids": []},
    {"key": "budget", "...": "..."},
    {"key": "schedule", "...": "..."},
    {"key": "operations", "...": "..."},
    {"key": "readiness", "...": "..."},
    {"key": "casting", "...": "..."},
    {"key": "agreements", "...": "..."}
  ]
}
```

`summary` is a `GroundedStatement`: exactly `statement` and `span_ids`, same shape as `current_state`/`continuity_break`/`next_action`.

Each entry in `sections` has exactly these fields — **`key` and `detail`, not `section` and `statement`**:

```text
key         one of: decision, budget, schedule, operations, readiness, casting, agreements
status      one of: confirmed, attention, evidence_gap, not_applicable
headline    non-empty string
detail      non-empty string
span_ids    array of span IDs (possibly empty only for evidence_gap)
```

Rules:

- `sections` always has exactly seven entries, in exactly this order, each `key` appearing exactly once: `decision, budget, schedule, operations, readiness, casting, agreements`. A missing, extra, duplicated, or reordered section is rejected.
- `evidence_gap` requires `span_ids == []`, the fixed `headline` `"No verified status available"`, and the fixed `detail` `"No available project source establishes the current <key> status."` with the literal key substituted.
- `confirmed`, `attention`, and `not_applicable` each require at least one `span_ids` entry, and every span ID must belong to the analysis's authoritative evidence.
- No grounded span list — `current_state`, `continuity_break`, `next_action`, `project_report.summary`, or any section's `span_ids` — may repeat the same span ID twice; a duplicate is rejected rather than silently deduplicated.
- When `analysis_status` is `break_found`, at least one section has status `attention`, and at least one `attention` section shares a span ID with `continuity_break`.
- When `analysis_status` is `no_material_break_found`, no section may have status `attention`.
- `summary.statement` is non-empty and `summary.span_ids` has at least one entry belonging to the authoritative evidence.

`citation_cards` (section 7) is the ordered, deduplicated union of every span ID referenced by `current_state`, `continuity_break`, `next_action`, `project_report.summary`, and every `project_report.sections[*]` entry, in that order.
