# Local Codex Session Controller v0.3 — Bounded Delta Verification

Scope: independent verification of the repair of the blocking raw-exception-leakage
finding recorded in the imported v0.3 final re-audit (commit `03493cb`), and
confirmation that the repair introduced no control-flow regression. This is not a
re-audit of CAS, revision semantics, cross-process locking, stale-writer rejection,
recovery behavior, session reuse, receipts, pinned executable handling, or the
preserved controller contract — those were accepted by the original independent
audit and are out of scope here.

## Commit identity

| Ref | SHA |
| --- | --- |
| Pre-repair production | `40341748c04e5b6617be7efe15cedbcfc1cde126` |
| Imported audit commit | `03493cb672161feb97a89e637cb95d6bc3ad7cb5` |
| Audited production (repair) | `361729fe217980c5a23eb2891810bc1861482e71` |
| Original independent audit commit | `4fc82224a141bf8491ae93b6b2117bbe6685b3e8` |

Verified before testing:

- Branch `audit/local-codex-session-controller-v0.3-delta`, HEAD `361729f`, working
  tree clean.
- `HEAD^` == `03493cb`, `HEAD^^` == `4034174` (the pre-repair production commit is
  reachable at `40341748c04e5b6617be7efe15cedbcfc1cde126`, matching the audit brief).
- Tree of `03493cb` (`947fa96...`) is byte-identical to the tree of the original
  independent audit commit `4fc8222` (`947fa96...`) — no historical audit verdict
  was rewritten or re-derived.
- `docs/audits/LOCAL_CODEX_SESSION_CONTROLLER_V03_FINAL_REAUDIT.md` was introduced
  by `03493cb` and is untouched by `361729f`.
- The repair delta `03493cb..361729f` touches exactly the five expected files and
  no others:
  - `src/continuity_ai/codex_process.py`
  - `src/continuity_ai/codex_session.py`
  - `tests/audit_codex_session_v02/test_reaudit_v02_findings.py`
  - `tests/audit_codex_session_v03/test_reaudit_v03_findings.py`
  - `tests/test_codex_session.py`

## The repair pattern

Every affected boundary in `codex_process.py` and `codex_session.py` previously
raised its sanitized public exception **from inside** the `except OSError:` clause
that caught the raw error (in most cases using `raise ... from None`). `from None`
only suppresses `__cause__` and the traceback's *printed* chain — it does not clear
`__context__`, which Python sets automatically and unconditionally whenever a new
exception is raised while another is being handled. The raw `OSError` (with its
`filename`, `strerror`, `winerror`, and message text) therefore remained reachable
via `__context__` even though `__cause__` was `None` — the exact finding recorded
in `03493cb`.

The repair replaces this with a two-step pattern at every affected boundary:

1. `except OSError:` (or `except (OSError, CodexProcessBoundaryError):`) sets a
   local boolean flag or a short non-sensitive sentinel string — never the caught
   exception object itself, never any of its attributes.
2. Outside the `try/except` block entirely — after the handler has fully exited —
   `if <flag>: raise <SanitizedError>(...)`.

Because the raise now happens with no exception currently being handled in that
frame, Python does not populate `__context__`, and there is nothing to suppress.
This severs both `__cause__` and `__context__` structurally rather than by
suppression. Verified at all eleven affected call sites:

- `capture_workspace` (root resolution, snapshot walk) — `codex_process.py`
- `_workspace_before_launch` (initial lstat, resolve, validation) — `codex_process.py`
- `_invocation_paths` (tempdir/schema preparation) — `codex_process.py`
- `CodexCliProcessAdapter.invoke` (environment preparation) — `codex_process.py`
- `CodexCliProcessAdapter._revalidate_executable` — `codex_process.py`
- `JsonSessionStore._read_document` — `codex_session.py`
- `JsonSessionStore._write_document` (parent resolution, atomic write) — `codex_session.py`
- `_session_store_lock` (acquisition, and — newly — `close()` in `finally`) — `codex_session.py`
- `CodexSessionController.with_local_codex` (discover: `FileNotFoundError` and
  `CodexProcessBoundaryError` arms) — `codex_session.py`
- `_resolved_workspace` — `codex_session.py`

One location gained genuinely new protection, not just a mechanical rewrite: the
`finally` block in `_session_store_lock` previously called `lock_file.close()`
with no `try/except` at all. A `close()` failure there would have propagated as a
**fully raw, unwrapped `OSError`** straight out of the context manager — a leak
that `from None` chaining could never have masked in the first place, and one the
producer's own converted tests do not exercise. The repair wraps that `close()` in
its own `try/except OSError`, folding a close failure into the same sentinel/raise
pattern. This delta audit specifically targets that new surface (see
`test_session_store_lock_close_failure_is_severed_not_a_raw_leak`).

## Fresh independent adversarial tests

Added: `tests/audit_codex_session_v03_delta/test_delta_verification.py` (13 tests).
Every test uses an injection point, attribute surface, or control-flow edge that is
distinct from the producer's converted reproductions in
`tests/audit_codex_session_v03/test_reaudit_v03_findings.py` and
`tests/test_codex_session.py`:

1. `test_workspace_deleted_between_lstat_and_resolve_is_severed` — genuine TOCTOU
   deletion as a side effect of the first successful `lstat`, forcing failure on
   the *second* boundary (`resolve(strict=True)`) rather than at entry.
2. `test_capture_workspace_lstat_failure_has_no_unbound_local` — control-flow
   safety: confirms the sentinel-flag refactor does not leave `resolved`
   referenced before assignment when the very first OS call fails (a regression
   here would surface as `UnboundLocalError`, not the intended typed exception).
3. `test_permission_error_secret_in_strerror_winerror_filename2_is_severed` —
   injects a secret via the 5-argument `PermissionError` constructor's
   `strerror`, `winerror`, and `filename2` fields specifically, and asserts none
   of them leak. The producer's own sanitization helper only inspects
   `str`/`repr`/`args`/`filename`; this audit's helper (`_assert_fully_sanitized`)
   additionally inspects `strerror`, `winerror`, and `filename2` on every node in
   the graph, per the audit brief.
4. `test_invocation_paths_schema_write_failure_severed_and_tempdir_cleaned` —
   fails `schema_path.write_text` *inside* a live temp directory (not at
   `TemporaryDirectory.__enter__`), and independently confirms the real temp
   directory is removed by `contextlib`/`tempfile` cleanup even though the OS
   error originates from inside the `with` block.
5. `test_write_document_temp_write_failure_leaves_durable_file_untouched` — fails
   the temp file's own `write_text` (not `replace`), and independently verifies
   the durable document is byte-identical and no partial `.tmp-*` document is
   left on disk to ever become authoritative.
6. `test_session_store_lock_close_failure_is_severed_not_a_raw_leak` — the new
   coverage described above; not exercised anywhere in the producer's own tests.
7. `test_session_store_lock_non_os_exception_is_not_swallowed` — proves a
   `ValueError` raised by caller code inside `with _session_store_lock():` is
   **not** caught by `except OSError:` and is **not** replaced by
   `SessionPersistenceError`; also proves the lock is still released (a
   subsequent acquisition on the same path succeeds).
8. `test_session_store_lock_acquisition_failure_is_severed` — fails the
   platform-locking call (`msvcrt.locking`/`fcntl.flock`) itself, a different
   point in the `try` block than open/close.
9. `test_full_controller_toctou_deleted_during_snapshot_walk_preserves_lifecycle`
   — establishes a genuine prior successful receipt via a real first
   investigation, then triggers the TOCTOU deletion specifically inside
   `capture_workspace`'s `rglob` walk during the second (resumed) call's
   pre-launch validation, distinct from the producer's whole-tree
   `shutil.rmtree`-before-`invoke()` trigger. Verifies the full controller
   lifecycle contract end to end (see below).
10. `test_revalidate_executable_boundary_error_is_severed_not_just_os_error` —
    exercises the `CodexProcessBoundaryError` arm of
    `_revalidate_executable`'s `except (OSError, CodexProcessBoundaryError):`
    directly, which the producer's test suite only exercises via the `OSError`
    arm.
11. `test_unrelated_session_document_byte_identical_when_sibling_write_fails` —
    two independent sessions in one JSON document; forces a persistence failure
    while saving session B and proves session A's data and the whole durable
    document are byte-identical to before the failed attempt.
12. `test_workspace_type_changed_to_file_still_raises_specific_error` — confirms
    a non-OS-exception-driven typed-error branch inside the same function was
    not accidentally folded into the generic sentinel/raise pattern by the
    refactor.
13. `test_controller_with_local_codex_boundary_error_severed` — independent of
    the producer's `FileNotFoundError`-only discovery test; exercises the
    `CodexProcessBoundaryError` arm of `with_local_codex`, which maps to
    `CodexUnavailable` rather than `CodexNotInstalled`.

All 13 pass. Full exception-graph traversal in every test follows both
`__cause__` and `__context__`, cycle-safely, and rejects `OSError`,
`FileNotFoundError`, and `PermissionError` anywhere in the graph, and further
rejects the forbidden probe values in `str`, `repr`, `repr(args)`, `filename`,
`filename2`, `strerror`, and `winerror` on every node.

## Full controller path (test 9)

Verified on the same controller session across the TOCTOU failure:

- Controller session ID unchanged.
- Active-operation marker durably cleared (`active_operation is None`).
- `codex_process_active` is `False`.
- A sanitized failure receipt is retained (`last_invocation_receipt` matches the
  raised exception's `.receipt`).
- The prior successful receipt is preserved (`last_successful_invocation_receipt`
  still equals the first investigation's receipt).
- The same session is reused for a subsequent successful `resume_session` call
  with no recovery or replacement step.
- Runner calls remain at `1` (the successful first call only) on the failed
  attempt; a real second runner call only occurs on the successful retry.
- The reasoning-provider constructor (`OpenAIReasoningProvider.__init__`) is
  never called on the failed attempt.

## Persistence boundary (test 11, plus reused focused suites)

- Durable JSON is byte-identical when persistence fails.
- Revision does not advance on a failed write.
- The unrelated sibling session is completely unaffected (same equality check on
  the full loaded record).
- No temporary partial document (`.tmp-*`) is left on disk to become
  authoritative (test 5 in the list above).

## Control-flow safety

Checked, with a dedicated test where feasible:

- No uninitialized-local risk from the sentinel-flag refactor (test 2).
- No accidental continuation after a failed boundary — every affected function
  raises before any subsequent statement can execute on the failure path (code
  read at all eleven sites; also implied by every failing test's specific typed
  exception).
- No loss of the intended typed exception — every test asserts the exact
  exception type and exact message string.
- No duplicate persistence — the write-failure test confirms exactly one
  document state after a failed write.
- No swallowed non-OS exceptions — `_session_store_lock`'s `except OSError:`
  does not widen to catch a `ValueError` raised by caller code (test 7).
- No skipped cleanup — temp directory removal (test 4) and lock release after
  both `close()` failure and unrelated-exception propagation (tests 6, 7) are
  verified.
- No replacement of a more specific typed error by a generic one — the
  non-OS-driven `CodexWorkspaceTypeChangedBeforeLaunch` branch still raises its
  specific type, not the generic `CodexWorkspaceUnavailableBeforeLaunch`
  sentinel (test 12).
- No changed context-manager behavior outside the intended OS translation —
  `_invocation_paths`' real tempdir is still cleaned up by `contextlib` on
  failure (test 4); `_session_store_lock` still releases the lock on both an
  OS-level close failure and a non-OS exception (tests 6, 7).
- No runner or provider call after a pre-launch failure — verified directly in
  test 9 and by the reused producer tests in the focused suites.

## Test gate

All commands below were run from the repository root on
`audit/local-codex-session-controller-v0.3-delta` at `361729f`, in order:

| Command | Result |
| --- | --- |
| `uv run pytest tests/audit_codex_session_v03_delta -q` | 13 passed |
| `uv run pytest tests/audit_codex_session_v03 -q` | 5 passed |
| `uv run pytest tests/audit_codex_session_v02 -q` | 2 passed |
| `uv run pytest tests/audit_codex_session/test_crash_recovery_and_executable_pinning.py -q` | 21 passed |
| `uv run pytest tests/test_codex_session.py -q` | 46 passed |
| `uv run pytest tests/unseen_workspace/test_codex_workspace_spike.py -q` | 12 passed |
| `uv run pytest -q --ignore=tests/test_codex_session_live.py` | 396 passed, 2 skipped |
| `uv run python -m compileall -q src` | clean |
| `git diff --check` | clean |
| `uv run pytest tests/test_codex_session_live.py -q -m live_network --force-enable-socket` | 1 passed |

The live test ran against the pinned local Codex CLI executable
(`codex-cli 0.144.6`, discovered via `CodexCliProcessAdapter.discover`), a fresh
synthetic workspace created under `tmp_path`, the controller's read-only sandbox
mode, and no application-managed API key (the controller never sets
`allow_api_key_environment=True` on any path exercised here).

## Non-blocking notes

- `_invocation_paths` and `_session_store_lock` both wrap a `yield` inside the
  same `try/except OSError:` that performs the sentinel conversion. This means an
  *unrelated* raw `OSError` raised by caller code inside the `with` block (not
  originating from the boundary's own preparation/acquisition logic) would be
  mischaracterized as a preparation/lock failure rather than propagating with its
  own identity. This structure is unchanged by this delta — it existed
  identically in `03493cb` before the repair — and is out of the bounded scope of
  this verification (no redesign of these context managers was authorized). It
  does not reintroduce the raw-exception-leak finding: any `OSError` caught this
  way is still fully sanitized by the same fixed sentinel/raise pattern. Flagged
  for awareness only, not as a blocking finding.

## Verdict

- Original v0.3 leak (raw `OSError` reachable via `__context__` despite
  `from None`) cannot be reproduced anywhere in the exception graph, at any of
  the eleven affected boundaries, under any of the fresh independent
  reproductions in this delta or the producer's converted regressions.
- Fresh independent tests cover both `__cause__` and `__context__`, cycle-safely,
  at injection points and attribute surfaces distinct from the producer's own
  tests.
- No raw OS exception, raw path, or secret value is reachable in any tested
  exception graph.
- Structural severing (raise outside the active handler) is confirmed at every
  affected call site by direct code reading and by every passing test.
- Controller lifecycle and persistence invariants remain intact.
- All focused tests, the full backend suite, compileall, and `git diff --check`
  pass. The live Codex test passes.
- No production file was modified by this audit; only test and documentation
  files were added, within the authorized paths.

**PASS — CONTROLLER V0.3 APPROVED FOR INTEGRATION**
