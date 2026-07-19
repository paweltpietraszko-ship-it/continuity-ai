# Local Codex Session Controller v0.3 — Final Independent Re-Audit

Independent, first-principles audit of the closed production SHA
`40341748c04e5b6617be7efe15cedbcfc1cde126` ("Repair Codex session prelaunch
and CAS boundaries"). This audit does not trust the producer report. No
production code, existing production tests, or the imported v0.2 audit test
were modified.

## AUDITED PRODUCTION SHA
`40341748c04e5b6617be7efe15cedbcfc1cde126`

## AUDIT BRANCH
`audit/local-codex-session-controller-v0.3`

## AUDIT SHA
`40341748c04e5b6617be7efe15cedbcfc1cde126` (audit branch HEAD == audited SHA at
the start of this audit; audit-only files added on top, see PUSH section for
the commit that adds them)

## UPSTREAM AUDIT SHA
`0dc1819f84fd1fc5a9430adfa1e98cef7c33bb9c` — confirmed as `HEAD^`, preserved
unchanged in history.

## PRODUCTION FILES MODIFIED
None by this audit. (`git status --short` was clean before this audit began;
this audit only adds files under `tests/audit_codex_session_v03/` and
`docs/audits/`.)

## AUDIT FILES ADDED
- `tests/audit_codex_session_v03/test_reaudit_v03_findings.py`
- `docs/audits/LOCAL_CODEX_SESSION_CONTROLLER_V03_FINAL_REAUDIT.md` (this file)

## PRE-LAUNCH BOUNDARY RESULT
PARTIAL FAIL. `_workspace_before_launch`, `_invocation_paths`, and
`JsonSessionStore._write_document` / `_session_store_lock` all correctly
raise a typed, narrowly-scoped exception whose **message text** contains no
raw path, and whose **`__cause__`** is explicitly cleared (`from None`).
Directory-to-file substitution, link/reparse substitution, workspace-identity
drift between validation and snapshot, and `active_operation`/
`codex_process_active` clearing on failure were all independently verified
and behave correctly. However, every one of these boundaries is implemented
as a bare `except OSError: raise Typed(...) from None`, and `from None` does
**not** clear `__context__` — see RAW EXCEPTION LEAKAGE RESULT.

## RAW EXCEPTION LEAKAGE RESULT
FAIL — reproducible, blocking. `raise X(...) from None` sets `__cause__ =
None` and `__suppress_context__ = True`, which only suppresses *default
traceback rendering*. Python still auto-populates `__context__` with the
original exception whenever a new one is raised while handling it, `from`
clause or not. The raw `OSError`/`PermissionError`/`FileNotFoundError`
instance — including its `.filename` attribute carrying the exact raw
workspace path, temp-directory path, or session-store path — remains
reachable as a plain object attribute on the publicly raised typed
exception (`exc.__context__`, or one hop further via
`exc.__cause__.__context__` in the full controller call chain).

Independently reproduced at every pre-launch/persistence OS boundary in the
v0.3 diff:
- `_workspace_before_launch` (`codex_process.py`)
- `_invocation_paths` (`codex_process.py`)
- `JsonSessionStore._write_document` (`codex_session.py`)
- End-to-end through `CodexSessionController.start_investigation`, using the
  *exact* TOCTOU trigger (`DeleteWorkspaceBeforeInvokeAdapter`) that the
  producer's own converted v0.2 regression uses.
- The producer's own new production test
  `tests/test_codex_session.py::test_permission_error_prelaunch_is_typed_sanitized_and_has_no_fallback`
  embeds a raw `"C:/secret/customer/source.txt"` string in the injected
  `PermissionError` specifically to probe for leakage, and asserts
  `"secret" not in str(captured.value)` — true, and irrelevant, because the
  secret string is one hop away on `__context__`, which that test (and its
  helper `_assert_sanitized_prelaunch_failure`, and the converted v0.2 audit
  test) never inspects.

This is a genuine violation of Area A item 9 ("Exception chaining does not
expose a raw OSError through `__cause__` or `__context__`") and, by
extension, item 8 ("No public error contains: raw workspace paths ...") —
the raw path is part of the publicly raised exception object, retrievable by
any caller that logs, serializes, or inspects `exc.__context__`, which is an
ordinary thing to do with a caught exception (e.g. `logging.exception(...)`
without traceback suppression, or any structured-error-reporting code that
walks the chain itself rather than relying on default traceback formatting).
The v0.2 blocker ("raw OSError/path leak on pre-launch workspace deletion")
is therefore only **partially** closed: the exception *type* and *message*
are sanitized; the exception *object graph* is not.

Five independent, deterministic reproducers are in
`tests/audit_codex_session_v03/test_reaudit_v03_findings.py`; all currently
PASS (i.e., successfully reproduce the leak). See FOCUSED AUDIT TESTS.

## MARKER RELEASE RESULT
PASS. In every prelaunch-failure path independently exercised (deleted
workspace, permission denial, directory-to-file substitution, reparse
substitution), `active_operation` is cleared and `codex_process_active`
becomes `false` in durable state before the call returns.

## SESSION REUSE RESULT
PASS. After a failed prelaunch attempt, recreating the identical workspace
binding and retrying `start_investigation` on the same `controller_session_id`
succeeds without recovery and without a replacement session, confirmed via
the existing converted v0.2 regression and independently observed while
building the v0.3 reproducers.

## CAS RESULT
PASS (code inspection + existing regression suite; not independently
re-derived with new multiprocessing tests — see scope note below).
`CodexControllerSession.revision` is a required positive int
(`_positive_int`, rejects missing/zero/negative/bool). `create()` requires
`revision == 1`. `save()` and `recover()` both route through the single
`_compare_and_swap()` method, which re-reads durable state under the real
cross-process file lock (`_session_store_lock`, `msvcrt.locking` on Windows)
before comparing `current.revision != session.revision` and raising
`ConcurrentSessionModification` on mismatch; `recover()` additionally checks
`active.operation_id != expected_operation_id` first. Revision is bumped
only after `_write_document` succeeds (`persisted = replace(session,
revision=session.revision + 1)` happens inside the locked, re-read
comparison, immediately before the atomic write).

## REVISION RESULT
PASS. Positive-int-only (`_positive_int`), starts at 1 on `create()`, missing
`revision` key is rejected by `_SESSION_FIELDS` shape check
(`CorruptSessionState`) rather than defaulted/repaired, confirmed by the
producer's own `test_missing_revision_and_v02_state_are_explicitly_rejected`
(passing) and by direct code inspection of `_session_from_dict`.

## CROSS-PROCESS WINDOWS RESULT
PASS (relying on the producer's own `multiprocessing.get_context("spawn")`
test `test_two_spawned_processes_cannot_both_begin_same_operation`, which
passed in the full suite run, plus code inspection confirming
`_session_store_lock` uses `msvcrt.locking`, a real OS-level, cross-process
file lock on Windows, not a thread-local primitive). Not independently
re-implemented as a fresh spawn-based reproducer — see scope note.

## STALE-WRITER RESULT
PASS. The imported v0.2 stale-writer audit
(`test_stale_reader_can_silently_erase_an_already_completed_operation`)
passed unmodified. Independent review confirms `JsonSessionStore.save` now
routes through `_compare_and_swap`, so a stale writer whose loaded
`revision` no longer matches durable state receives
`ConcurrentSessionModification` and no durable field changes.

## RECOVERY RACE RESULT
PASS (code inspection + producer's `test_recovery_and_normal_save_share_one_revision_cas`,
which passed). `recover()` and `save()` share the identical CAS
invariant via `_compare_and_swap`; a racing recovery against a newer normal
save (or vice versa) is rejected by the shared revision check under the
shared lock.

## ATOMIC-REPLACE FAILURE RESULT
PASS (code inspection + producer's `test_atomic_replace_failure_does_not_advance_revision`,
which passed). `_write_document` only bumps revision as a side effect of a
successful `temporary.replace(self.path)`; on `OSError` it raises
`SessionPersistenceError` without having written `sessions[...]` back to a
persisted document (the in-memory `persisted` dict was only ever staged into
the `document` object, never flushed).

## UNRELATED-SESSIONS RESULT
PASS. `_compare_and_swap` only reads/writes the single
`session.controller_session_id` key inside `sessions`; other keys in the
same JSON document are round-tripped unchanged. Confirmed via producer's
`test_unrelated_session_survives_session_local_cas` (passed) and independent
code reading.

## BACKWARD-STATE RESULT
PASS. `_read_document` rejects any `schema_version != SESSION_SCHEMA_VERSION`
(3) via `IncompatibleSessionState`, so a genuine v0.2 document
(`schema_version == 2`) is explicitly rejected rather than silently
migrated. Confirmed via producer's `test_incompatible_state_schema_fails_closed`
(passed) and code inspection.

## AUDIT-TEST-CONVERSION RESULT
PARTIAL FAIL. `0dc1819f84fd1fc5a9430adfa1e98cef7c33bb9c` is preserved
unchanged as `HEAD^`; only the later repair commit
(`40341748c04e5b6617be7efe15cedbcfc1cde126`) touched
`tests/audit_codex_session_v02/test_reaudit_v02_findings.py`. The conversion
does assert genuinely fixed behavior (typed exception, no phrase-match of the
raw path in `str(exc)`, marker release, failure persistence, session reuse)
rather than merely deleting the failing reproducer — it is not xfail'd,
skipped, or weakened in the sense of asserting less than it used to. However,
its cause-chain sanitization check
(`while current is not None: ... current = current.__cause__`) only walks
`__cause__`, never `__context__`, so it does not actually close the loophole
it was written to guard: RAW EXCEPTION LEAKAGE RESULT reproduces a real leak
through the exact same trigger this converted test exercises, and the
converted test does not catch it. The stale-writer audit
(`test_stale_reader_can_silently_erase_an_already_completed_operation`) is
substantively unchanged and correctly accepts only a typed
`CodexSessionError` as safe conflict behavior.

## NO-FALLBACK RESULT
PASS. `OpenAIReasoningProvider.__init__` was monkeypatched to a call counter
in both the converted v0.2 test and this audit's independent reproducers;
`provider_constructor_calls == 0` held in every prelaunch-failure scenario
exercised, including the ones that also reproduce the `__context__` leak.

## PRESERVED CONTRACT RESULT
PASS. Full existing suite (375 tests, excluding the live-network file) passed
unmodified, including genuine-thread-ID retention, same-ID resume, pinned
executable identity, exact `--cd`/read-only sandboxing, exact workspace
binding, last-attempted/last-successful receipt semantics, interruption
behavior, explicit-recovery-only, no automatic replacement session,
unrelated-session isolation, and fail-closed corrupt-state handling
(`tests/audit_codex_session/test_crash_recovery_and_executable_pinning.py`,
`tests/test_codex_session.py`, `tests/unseen_workspace/test_codex_workspace_spike.py`
all green).

## FOCUSED AUDIT TESTS
```
uv run pytest tests/audit_codex_session_v03 -q
```
Result: **5 passed** (all five independently reproduce the `__context__`
leak; a "pass" here means the defect was successfully and deterministically
reproduced, per this audit's mandate to report FAIL with a minimal
reproducer rather than fix or xfail).

## EXISTING FOCUSED TESTS
```
uv run pytest tests/audit_codex_session_v02 -q                                     -> 2 passed
uv run pytest tests/audit_codex_session/test_crash_recovery_and_executable_pinning.py -q -> 21 passed
uv run pytest tests/test_codex_session.py -q                                       -> 39 passed
uv run pytest tests/unseen_workspace/test_codex_workspace_spike.py -q              -> 12 passed
```
All existing production and audit tests pass unmodified; no regression
against the preserved controller contract.

## FULL BACKEND TESTS
```
uv run pytest -q --ignore=tests/test_codex_session_live.py
```
Result: **376 passed, 2 skipped** (skips pre-exist and are unrelated to this
audit's scope — Windows-optional filesystem primitives elsewhere in the
suite).

## LIVE CODEX TEST
NOT RUN. The deterministic gate is green and the local `codex` executable is
present on PATH, so the live test was runnable per protocol. It was withheld
because a reproducible blocking finding (RAW EXCEPTION LEAKAGE) was already
established independently of the live path, so running it would spend real
API cost/network access without being able to change the FAIL verdict.
Available on request.

## COMPILEALL
```
uv run python -m compileall -q src
```
Result: OK, no errors.

## GIT DIFF CHECK
```
git diff --check
```
Result: clean, no output.

## GIT STATUS
Clean at audit start (verified branch `audit/local-codex-session-controller-v0.3`,
HEAD `40341748c04e5b6617be7efe15cedbcfc1cde126`, parent
`0dc1819f84fd1fc5a9430adfa1e98cef7c33bb9c`). This audit adds exactly two new
files (`tests/audit_codex_session_v03/test_reaudit_v03_findings.py`,
`docs/audits/LOCAL_CODEX_SESSION_CONTROLLER_V03_FINAL_REAUDIT.md`), commits
them, and leaves the worktree clean.

## PUSH
Audit-only files committed on `audit/local-codex-session-controller-v0.3` and
pushed to `origin`. See commit recorded after this report was written.

## BLOCKING FINDINGS

1. **Raw OSError (including `.filename` with the exact raw workspace,
   temp-directory, or session-store path, and — where the underlying OS
   message itself contains sensitive text — that text too) remains
   reachable via `exc.__context__` on every "sanitized" typed exception
   produced by the v0.3 pre-launch and persistence boundaries.**
   `raise Typed(...) from None` only clears `__cause__` and sets
   `__suppress_context__` (suppressing *default traceback printing*); it
   does not clear `__context__`, which Python auto-populates with the
   original exception regardless of the `from` clause. Affects
   `_workspace_before_launch`, `_invocation_paths`, `codex_environment`'s
   call site in `invoke()`, `JsonSessionStore._write_document`, and
   `_session_store_lock` in `codex_process.py`/`codex_session.py`. Violates
   Area A items 8 and 9 explicitly. Reproduced independently five ways in
   `tests/audit_codex_session_v03/test_reaudit_v03_findings.py`, including
   through the identical TOCTOU trigger the producer's own converted v0.2
   regression uses (which does not detect it because it only walks
   `__cause__`), and through the producer's own new
   `test_permission_error_prelaunch_is_typed_sanitized_and_has_no_fallback`
   scenario (whose embedded `"secret"` string is not caught by that test's
   `str(captured.value)` / `__cause__`-only check either). This means the
   v0.2 "raw OSError/path leak on pre-launch workspace deletion" blocker is
   only partially closed — the message text is sanitized, but the exception
   object graph, an ordinary and expected place for calling/logging code to
   inspect, is not.

## NON-BLOCKING NOTES

- Area B (CAS) was reviewed by static code inspection and by running the
  producer's own new CAS-focused production tests (revision positivity,
  stale-writer rejection, recovery/normal-save shared invariant, atomic
  replace failure not advancing revision, unrelated-session isolation,
  missing-revision/v0.2 rejection, and a `multiprocessing.get_context("spawn")`
  two-process race), all of which passed. This audit did not additionally
  author brand-new independent multiprocess/spawn reproducers for Area B,
  since the Area A finding above already renders exact SHA
  `40341748c04e5b6617be7efe15cedbcfc1cde126` FAIL regardless of Area B's
  outcome, and further exhaustive Area B adversarial testing would not
  change that verdict. Nothing observed in code inspection or the existing
  regression suite contradicts the CAS contract; this is recorded as a scope
  limitation, not a finding.
- The two pre-existing skips in the full suite run predate this audit and
  are unrelated to the Codex session controller (Windows-optional
  filesystem primitives used elsewhere in the repository's test suite).

## FINAL RECOMMENDATION

FAIL — CONTROLLER V0.3 MUST NOT BE INTEGRATED
