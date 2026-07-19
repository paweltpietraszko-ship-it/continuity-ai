# Local Codex Session Controller v0.2

## Product and architecture boundary

The controller manages exactly one locally installed Codex CLI as Continuity
AI's sole semantic agent. It has no OpenAIProvider or deterministic-provider
fallback. It does not implement Source Scoping, approved-workspace creation,
Project Report generation, desktop behavior, or Bridge integration. The
unseen-workspace spike continues to use the same process adapter and remains an
explicit ephemeral one-shot operation.

Controller session identity and Codex thread identity remain separate. A
controller session ID is generated locally. A Codex session ID is retained only
from one genuine UUID-valued thread.started event. Resume uses that same ID and
never silently creates a replacement session.

## Abandoned-operation threat model

The v0.1 active boolean could be persisted immediately before launch and survive
a hard controller crash. Every ordinary transition required the boolean to be
false, so no public method could establish that the operation had ended or
release the marker. The result was permanent session lockout.

Version 0.2 retains a typed ActiveCodexOperation with:

- an immutable operation UUID;
- the exact controller session UUID;
- the operation type;
- a durable stage: reserved, launching, running, or completed;
- the owner controller PID plus its OS creation token;
- after launch, the Codex child PID plus its OS creation token;
- the reservation timestamp, used only for audit and never for liveness.

The marker and active operation must either both be present or both be absent.
Corrupt or partially retained combinations fail closed.

## Production liveness mechanism

Codex operation liveness is proven from a durable process identity, not from
elapsed time or caller testimony. On Windows the verifier opens the target
process, reads its process creation FILETIME and exit status, and compares both
PID and creation token. On Linux it compares PID and the process start-time
field from procfs and treats zombie or exited state as dead. PID reuse therefore
does not make an abandoned earlier operation appear alive.

The production adapter owns launch through subprocess.Popen so it can persist
the child identity immediately after the OS returns a PID. An injected runner
used by deterministic tests is represented by the live controller identity.
Operation ownership covers:

1. reservation, persisted before any launch work;
2. a launching stage, persisted immediately before executable revalidation and
   process creation;
3. running, persisted with the concrete Codex child identity;
4. completed, persisted after the child has ended;
5. final receipt and lifecycle persistence, after which the marker is removed.

The verifier returns exactly ALIVE, DEAD, or UNKNOWN. Recovery is permitted only
for DEAD. ALIVE and UNKNOWN are typed rejections. No age threshold, force flag,
bare boolean, or caller-supplied liveness proof exists.

### Crash boundaries

- Crash while reserved, before entering the launch handoff: a dead owner process
  proves the operation dead and recovery may proceed.
- Crash after launching was persisted but before the child identity was
  durably saved: the OS may or may not have created a child. This deliberately
  evaluates to UNKNOWN and recovery is rejected.
- Crash immediately after process creation but before child identity
  persistence: this is the same ambiguous launching window and is UNKNOWN.
- Crash while running after child identity persistence: the exact child
  identity determines ALIVE, DEAD, or UNKNOWN.
- Crash after child completion or during final persistence: the retained child
  identity is dead, so recovery may proceed.

The two launch-adjacent crash cases are therefore defined and fail closed. The
design does not claim it can prove non-launch inside the narrow handoff window.

## Explicit recovery transition and atomicity

recover_abandoned_operation requires both the controller session ID and the
exact retained operation UUID. A stale, malformed, or incorrect operation UUID
is rejected before liveness inspection.

For OS-proven DEAD only, recovery atomically:

- leaves workflow phase unchanged;
- leaves original and approved workspace bindings unchanged;
- leaves the genuine Codex session ID unchanged;
- leaves last attempted and last successful invocation receipts unchanged;
- marks availability interrupted and records a sanitized failure code;
- appends an immutable sanitized recovery event;
- removes the active operation and active marker together.

The recovery event records only UUIDs, timestamp, abandoned stage, DEAD result,
and a fixed sanitized code. It contains no workspace path, prompt, source
content, process output, credential, or semantic output. Recovery never creates
an invocation receipt, structured output, workflow success, or semantic
success.

JsonSessionStore performs an operation-ID compare-and-save while holding both
its in-process lock and a same-directory OS advisory recovery lock. The JSON
document is still published by same-directory temporary write and atomic
replacement. Independent controllers therefore cannot both recover the same
operation. A failed write leaves the previously persisted active marker and
operation identity unchanged.

Ordinary transitions and availability methods still require an idle session.
They cannot clear an abandoned marker. Only normal operation completion or the
explicit DEAD-only recovery transition can release it. A recovered session can
subsequently execute another normal operation.

## Executable discovery and pinning

Discovery remains dynamic through shutil.which. The resolved absolute file is
required to be a regular non-link, non-reparse file. Before capability probing,
the adapter captures SHA-256, size, device, and inode identity. Version and
resume capability checks run against that exact resolved path, and discovery
fails if its identity changes during those checks.

Every invocation places the exact resolved path in argv[0]. PATH is never used
again for invocation selection. Immediately before process creation the adapter
rechecks file type, link or reparse status, full byte hash, size, device, and
inode. Deletion, byte replacement, same-path file replacement, symlink or
reparse substitution, hard-link substitution, and unsupported file-type
replacement fail closed before the runner is called.

No machine- or user-specific executable path is stored in a production default
or test fixture. The retained session and receipt record only the path actually
selected dynamically for that controller instance. Resume capability remains
version-proofed and requires the existing CLI flag checks plus the bounded
verified-version allowlist.

The legacy spike stays on CodexCliProcessAdapter. It now receives the same
resolved-path and identity validation while preserving its existing ephemeral
flag and compatibility environment behavior.

## Workspace error taxonomy

The workspace root is still exact, read-only, and fingerprinted from paths,
entry types, modes, sizes, and file bytes. Original and approved bindings remain
separate. Every controller fingerprint boundary, including creation, original
validation, approved binding, preflight failure, reporting, resume, and
conversation continuation, translates only CodexProcessBoundaryError into
WorkspaceBoundaryViolation.

WorkspaceBoundaryViolation is a CodexSessionError with failure category
workspace_boundary_invalid. Its public message is the fixed text "Workspace
boundary validation failed." The original process-boundary exception is
preserved as the cause for local diagnostics. Raw paths, source evidence, and
credentials are not copied into the public error. Unrelated exceptions are not
captured by this translation.

## Preserved process and receipt boundaries

CodexCliProcessAdapter remains the only Codex subprocess implementation. The
session controller continues to enforce exact cwd and --cd binding, read-only
sandbox, strict output schema, prompt delivery through stdin, before and after
workspace snapshots, and exclusion of application-managed OPENAI_API_KEY.

Last-successful-receipt semantics are unchanged. Failed and malformed
invocations may replace the last attempted receipt but cannot replace the last
successful receipt. Successful state is published only after structured output,
same-ID resume, input integrity, and final atomic persistence all pass.

## Remaining bounded limitations

- Durable OS process identity is implemented for Windows and Linux. Unsupported
  operating systems and inaccessible process metadata evaluate to UNKNOWN and
  cannot be recovered.
- The narrow launch handoff between persisted launching state and durable child
  identity is intentionally unrecoverable automatically because non-launch
  cannot be proven there.
- Recovery proves only that the retained OS operation identity is dead. It does
  not prove whether Codex produced useful output, whether any semantic work
  completed, or whether a new Codex thread was created before the crash.
- Session schema v2 is strict. A v0.1 retained document is incompatible and
  fails closed rather than receiving a validation-bypassing default.
- Recovery is local and explicit. There is no automatic expiry, automatic
  replacement session, global mutable recovery registry, or remote-process
  liveness claim.
