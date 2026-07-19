# Continuity AI Desktop

Tauri 2 + React 18 + TypeScript desktop client for Continuity AI.

## Current implementation status

Implemented and runtime active:

- approved UI shell and navigation;
- immediate UI render — `main.tsx` mounts `AppRoot` (`src/App.tsx`) synchronously with the demo shell already visible in a `connecting` state; it never waits for the Python process before the first paint;
- Bridge process startup — the bootstrap promise (`src/bridge/bootstrap.ts`) is created exactly once, at module scope in `main.tsx`, before the first React render and outside any component effect, so `React.StrictMode`'s double-invoked effects cannot start the process twice; `AppRoot`'s effect only subscribes to that single promise and updates state when it settles;
- 8-second fail-closed bootstrap timeout — if `bridge_start`/`get_workspace_state` have not resolved within `BOOTSTRAP_TIMEOUT_MS` (8000 ms, `src/bridge/bootstrap.ts`), the UI switches to `Local Bridge unavailable · Demonstration mode` on its own; the timer is cleared on normal completion and a late resolution after timeout is ignored;
- `get_workspace_state` handshake — performed once by the bootstrap immediately after a successful start, and independently by the Rust process manager on every spawn (`src-tauri/src/bridge/process.rs`);
- controlled connection status — the header shows a small, discreet `Connecting local Bridge…` / `Local Bridge connected` / `Local Bridge unavailable · Demonstration mode` / `Demonstration mode` label (`bridgeStatusLabel` in `src/bridge/bootstrap.ts`); the process id is never shown to the user;
- bounded Bridge response timeout in Rust — every blocking read of a Bridge response (the handshake in `spawn` and every later `request`) runs on a dedicated thread and is joined with `recv_timeout(BRIDGE_RESPONSE_TIMEOUT)` (8 seconds, `src-tauri/src/bridge/process.rs`); on timeout the hung Python process is killed, stdin is closed, the abandoned reader is left for the now-unblocked background thread to drop on its own, and a generic `bridge_timeout` `DesktopError` is returned with no stderr, command text, path, or PID in the message; `BridgeManager` removes the dead process from its state on this error, so `status()` correctly reports `running: false` afterward;
- bounded shutdown — because no Bridge operation can hold the `BridgeManager` mutex for longer than `BRIDGE_RESPONSE_TIMEOUT`, `tauri::RunEvent::Exit`'s call to `BridgeManager::stop()` can likewise never block indefinitely, even if it fires while a request is in flight;
- shutdown cleanup — `tauri::RunEvent::Exit` in `src-tauri/src/lib.rs` calls `BridgeManager::stop()`, which is idempotent and safe even if the Bridge never started; the existing `Drop` on the process handle remains as a secondary safety net;
- managed persistent Python child process;
- UTF-8 NDJSON request/response transport over stdin/stdout;
- explicit provider and backend-root configuration;
- graceful EOF shutdown with bounded kill fallback;
- exact command/response ordering validation;
- typed frontend Bridge contracts and controlled-error handling;
- canonical restart sequence that restores retained analysis without re-running analysis;
- native folder/file picker dependency for artifact and vault selection.

Still demonstration-only (no backend involvement):

- Project Report rendering — `App.tsx` renders only `src/data/demoWorkspace.ts` synthetic data; `src/bridge/projectReportProjection.ts` exists and is unit-tested but is not imported by `App.tsx`. Schema `3.0` types/adapter are **not** wired into the running UI;
- vault UI workflow — lock/unlock is a local React state toggle only; the overlay and header copy explicitly say so and never claim a backend session was created or restored;
- owner identity — always displays `Local owner` until a real `unlock_vault` call exists; no decrypted name is shown or cached;
- conversation — the drawer is explicitly labeled "Demonstration conversation" and its replies are local regex pattern matches, not Continuity AI backend output;
- attestations — added to local React state only; all copy (toast, conversation message, proposal note) explicitly states the attestation is not sent to a backend and is not persisted;
- source drawer neutral evidence records.

The current backend contract does not return these fields for a real run, and the UI must not infer them.

## Required environment

Run from the Continuity AI repository root or set:

```text
CONTINUITY_BACKEND_ROOT=<absolute repository root>
CONTINUITY_PYTHON=<python executable, optional; defaults to python>
CONTINUITY_REASONING_PROVIDER=deterministic_offline | openai
```

For an OpenAI-backed run, the parent environment must also contain:

```text
CONTINUITY_OPENAI_MODEL=<explicit model identifier>
OPENAI_API_KEY=<secret>
```

The Rust process manager passes provider configuration to `python -m continuity_ai.bridge_main`. Secrets are inherited by the Python child and are never returned to JavaScript.

## Checks

```text
npm ci
npm run lint
npm run build
npm run test
npm audit --audit-level=low
npm run tauri build
```

Rust checks from `desktop/src-tauri`:

```text
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test
```

The Rust checks require the local Rust/Tauri Windows toolchain.
