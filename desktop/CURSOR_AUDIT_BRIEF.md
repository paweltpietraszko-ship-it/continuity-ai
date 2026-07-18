# Cursor Audit Brief — Managed NDJSON Desktop Bridge

Audit only the new `desktop/` package against backend checkpoint `8cf3845f3ad1da032406faaa985a099e67fcac4a` and `docs/BRIDGE_PROCESS_CONTRACT_v0.1.md`.

Do not redesign the product UI and do not modify Python business logic.

Verify:

1. Rust starts one persistent `python -m continuity_ai.bridge_main` process, not one process per command.
2. No HTTP server, FastAPI, local port, socket transport, or LynxMask code was introduced.
3. stdin/stdout are piped and encoded as UTF-8 NDJSON with exactly one request and one response per line.
4. stderr is drained separately and never parsed as protocol data.
5. requests are serialized, and the returned command must equal the sent command.
6. process startup performs a harmless `get_workspace_state` handshake.
7. closing stdin is attempted before bounded kill fallback.
8. no Windows console window is created for the Python child.
9. backend root and Python executable resolution contain no user-specific hardcoded path.
10. provider selection is explicit and missing/unsupported provider fails safely.
11. JavaScript receives controlled response envelopes but never provider secrets.
12. TypeScript command/result mappings match the normative Bridge command contract.
13. the restart helper performs `unlock_vault → get_workspace_state → load_project → get_workspace_state` and never sends `analyze_project` for history restoration.
14. frontend code does not infer semantic roles, citation text, source status, continuity break, or next action.
15. capabilities are minimal and do not grant filesystem scopes beyond native path selection.
16. errors exposed by Rust contain no filesystem paths, stderr contents, passwords, API keys, or Python exceptions.
17. all Rust code passes fmt, clippy with warnings denied, and tests on Windows.

Return findings grouped as BLOCKER, MAJOR, MINOR, or PASS. Include exact file and line references. Do not implement fixes during the audit.

## Bounded correction after the first Cursor audit

The first audit confirmed the Rust/TypeScript Bridge transport is correctly implemented, but that normal application lifecycle never called `bridge_start` and never performed the `get_workspace_state` handshake, that vault/conversation/attestations are local React simulation only, and that `tauri-plugin-dialog` had drifted to `2.7.2` in `Cargo.lock` against `2.4.0` in `package.json`.

Implemented and runtime active as of this correction:

- Bridge process startup — exactly once, from `main.tsx`, before React mounts;
- `get_workspace_state` handshake immediately after a successful start;
- controlled connection status (`connected` / `unavailable` / `browser_demo`) shown in the header, no process id or Python error detail exposed;
- shutdown cleanup on `tauri::RunEvent::Exit` calling the idempotent `BridgeManager::stop()`;
- `tauri-plugin-dialog` pinned to `=2.4.0` in `Cargo.toml`, matching `@tauri-apps/plugin-dialog@2.4.0` in `package.json`.

Still demonstration-only, unchanged in scope:

- Project Report rendering (`App.tsx` still renders only `src/data/demoWorkspace.ts`; the schema `3.0` adapter is not imported by `App.tsx`);
- vault UI workflow, owner identity, conversation, and attestations — local React simulation, with copy corrected so no message claims a backend performed or persisted an operation.

## Bounded correction after the Cursor retest

The retest found that React only mounted after `bootstrapBridge()` resolved, so a hung `bridge_start`/`get_workspace_state` left the user staring at an empty window indefinitely, and that a TypeScript-only `Promise.race` would not help because a blocking Rust read could still leave the process and the `BridgeManager` mutex stuck.

Implemented and runtime active as of this correction:

- the UI renders the demo shell immediately — `AppRoot` (`src/App.tsx`) mounts synchronously in a `connecting` state and only updates once the bootstrap promise settles; it never waits for the Python process before the first paint;
- the bootstrap promise is still created exactly once, at module scope in `main.tsx`, outside any component or effect — `React.StrictMode` re-mounting `AppRoot` only re-subscribes to that same promise, it cannot start the Bridge twice;
- an 8-second fail-closed timeout on the whole TypeScript bootstrap (`BOOTSTRAP_TIMEOUT_MS` in `src/bridge/bootstrap.ts`) — past that point the UI switches itself to `Local Bridge unavailable · Demonstration mode` with a fixed, generic message (no path, stderr, exception text, PID, or secret), and the timer is cleared on normal completion;
- a matching bounded timeout on the Rust side (`BRIDGE_RESPONSE_TIMEOUT`, 8 seconds, `src-tauri/src/bridge/process.rs`) around every blocking Bridge response read, including the handshake performed inside `spawn`: the read runs on a dedicated thread joined via `recv_timeout`; on timeout the hung Python process is killed, stdin is closed, the abandoned reader is left for the (now unblocked) background thread to drop on its own, and a generic `bridge_timeout` `DesktopError` is returned;
- `BridgeManager` removes a timed-out process from its state, so `status()` reports `running: false` afterward, and `stop()` remains idempotent in that state;
- because no Bridge operation can hold the `BridgeManager` mutex longer than `BRIDGE_RESPONSE_TIMEOUT`, `RunEvent::Exit`'s call into `BridgeManager::stop()` is transitively bounded by the same 8-second ceiling, even if it fires mid-request — no separate shutdown-specific timeout was needed.

Still demonstration-only, unchanged in scope:

- Project Report rendering, vault UI workflow, owner identity, conversation, and attestations remain exactly as described above — this correction only changes bootstrap timing/timeout behavior, not what is real vs. simulated.

## Additional Project Report v3 preparation audit

The runtime report is intentionally not enabled yet. Also verify:

18. `ProjectReport` types match schema `3.0`, with exactly seven closed section keys in the normative order.
19. Section statuses are limited to `confirmed`, `attention`, `evidence_gap`, and `not_applicable`.
20. Evidence-gap sections accept only empty span lists and the exact backend-fixed wording.
21. Every non-gap report span resolves only through a returned backend citation card.
22. No adapter searches source content, filenames, semantic annotations, evidence IDs, or cached demo records to construct report conclusions.
23. Locked owner display is always `Local owner`; a decrypted owner name is not cached across lock.
24. `App.tsx` does not claim executable Project Report v3 integration before the new audited backend SHA exists.
