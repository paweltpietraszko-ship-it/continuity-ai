# Local Codex Session Controller v0.1

## Product boundary

The controller in `continuity_ai.codex_session` manages one locally installed
Codex CLI as Continuity AI's only semantic agent. It does not import or invoke
the OpenAI reasoning provider or deterministic offline provider, and it has no
provider fallback. The existing unseen-workspace spike remains an explicit,
ephemeral one-shot operation.

## Validated CLI

- Version: `codex-cli 0.144.6`
- Shell command resolution observed for this checkpoint:
  `C:\Users\p_pie\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe`
- Production adapter resolution under the repository-managed `uv run`
  environment:
  `C:\Users\p_pie\.codex\packages\standalone\releases\0.144.6-x86_64-pc-windows-msvc\bin\codex.exe`
- Production resolution: `shutil.which` followed by an exact resolved path;
  no user-specific path is embedded in production code.
- Non-interactive start: `codex exec`
- Non-interactive continuation: `codex exec resume <SESSION_ID> -`
- JSON events: a genuine UUID is accepted only from a unique
  `thread.started.thread_id` event.
- Resume schema: `codex exec resume --help` exposes `--output-schema`,
  `--output-last-message`, and `--json`.
- Resume boundary: the exact CLI accepts top-level `--sandbox read-only` and
  `--cd <workspace>` before `exec resume`.

Resume is version-proofed, not inferred from command presence. The adapter
reports resume support only when all required flags are present and the exact
CLI version is in the bounded real-test allowlist. Version `0.144.6` passed a
real initial invocation and same-ID resume with strict schemas, the same cwd and
`--cd` root, read-only sandbox, and unchanged input fingerprint. An unverified
future version reports `resume_supported = false` until separately proven.

## Separation of identities and state

`controller_session_id` is a Continuity AI UUID. `codex_session_id` is
optional and is retained only when the CLI emits a genuine UUID event. The
controller never derives, substitutes, or invents a Codex ID.

Workflow phase and Codex availability are separate:

- workflow: `ready`, `investigating`, `awaiting_human_review`,
  `approved`, `reporting`, `conversational`, `completed`;
- availability: `available`, `not_installed`, `not_authenticated`,
  `unavailable`, `interrupted`, `limit_reached`.

An availability failure preserves the workflow phase, original and approved
workspace bindings, and last successful receipt.

## Workspace boundary

The workspace root is resolved exactly. Symbolic-link roots and linked entries
are rejected. The deterministic fingerprint covers every relative path, entry
type, mode, file size, and file byte hash, including empty directories. A
separate full snapshot also retains modification metadata for before/after
integrity comparison.

Every operation checks the caller's path and retained fingerprint before the
process adapter runs. The adapter repeats the expected-fingerprint check at the
last pre-launch boundary, then captures a post-run snapshot. A mismatch never
updates the retained fingerprint and never produces a successful receipt.

The approved workspace requires an explicit operation from
`awaiting_human_review`. Its path and supplied fingerprint are independently
verified and retained separately. The original workspace cannot be rebound as
approved, and an ancestor that widens the original boundary is rejected.

## Process adapter

`continuity_ai.codex_process.CodexCliProcessAdapter` is the sole Codex
subprocess implementation. Both the controller and legacy spike use it. It
owns:

- executable and capability discovery;
- sanitized environment construction;
- exact cwd and `--cd` binding;
- read-only sandbox selection;
- temporary strict schema and response paths;
- prompt delivery through stdin;
- JSON event UUID extraction;
- timeout, interruption, and launch evidence;
- before/after workspace snapshots.

The session controller's primary path excludes `OPENAI_API_KEY` from the
child environment. It does not inspect authentication secrets. Authentication
and usage-limit states are inferred only from Codex process evidence. The
legacy spike retains its prior environment behavior for compatibility and
remains `--ephemeral`.

## Persistence and receipts

`JsonSessionStore` requires a caller-provided path. It has no global-user
directory default. The document and nested contracts are schema-versioned and
strictly decoded. Corruption and incompatible versions fail closed.

Serialization is sorted and deterministic. Writes use a same-directory
temporary file and atomic replacement. No prompt, raw source content, model
output, token, API key, or authentication material is stored. Output is
represented only by a SHA-256 fingerprint.

An immutable receipt records the controller/Codex identities, operation,
timestamps, executable/version, exact workspace and before/after fingerprints,
sandbox, exit status, structured validation, output fingerprint, sanitized
failure, resume attempt, process launch, and new genuine Codex-session status.
A failed or malformed operation can be the last attempted receipt but never
replaces the last successful receipt.

The controller persists an active marker before subprocess launch and rejects a
second operation for the same controller session. Successful lifecycle state is
published only after output and input validation and successful persistence.

## Human gates

The controller implements lifecycle transitions only. It performs no Source
Scoping, approved-workspace creation, Project Report generation, or
conversation integration in this track. In particular,
`awaiting_human_review` cannot become `approved` without an explicit,
separately fingerprinted approved-workspace binding from the caller.
