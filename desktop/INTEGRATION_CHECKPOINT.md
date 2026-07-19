# Desktop Integration Checkpoint

Backend transport base:

- branch: `codex/implement-vertical-skeleton-from-commit`
- checkpoint: `8cf3845f3ad1da032406faaa985a099e67fcac4a`
- normative process contract: `docs/BRIDGE_PROCESS_CONTRACT_v0.1.md`

The desktop package adds only `desktop/` and does not modify Python core, vault, reasoning, or Bridge commands.

## Current scope

Implemented and runtime active (following the Cursor audit bounded correction):

- approved React/Tauri shell;
- immediate UI render — `AppRoot` mounts the demo shell synchronously in a `connecting` state; it never blocks the first paint on the Python process;
- Bridge process startup, run exactly once from `main.tsx` before React mounts (`src/bridge/bootstrap.ts`), never from an `App.tsx` effect — avoids the double-invoke Bridge start that `React.StrictMode` would otherwise cause;
- 8-second fail-closed bootstrap timeout — if the whole bootstrap has not settled within `BOOTSTRAP_TIMEOUT_MS`, the UI switches itself to `Local Bridge unavailable · Demonstration mode` rather than staying on "connecting" forever;
- `get_workspace_state` handshake, performed by the bootstrap after a successful start;
- controlled connection status shown in the header (`Connecting local Bridge…` / `Local Bridge connected` / `Local Bridge unavailable · Demonstration mode` / `Demonstration mode`), with no process id or Python error detail exposed to the user;
- Bridge response timeout in Rust — the blocking read of a Bridge response (handshake and every later request) is bounded by `BRIDGE_RESPONSE_TIMEOUT` (8 seconds); a hung subprocess is killed and removed from `BridgeManager` state on timeout, which also bounds how long `RunEvent::Exit` shutdown can ever block on the manager's mutex;
- shutdown cleanup on `tauri::RunEvent::Exit`, calling the idempotent `BridgeManager::stop()`;
- persistent managed Python process;
- UTF-8 NDJSON transport;
- typed command/session layer for the transport checkpoint;
- TypeScript contract and display adapter prepared for Project Report schema `3.0`.

Still demonstration-only, not enabled:

- executable Project Report v3 rendering from Bridge responses — `App.tsx` still renders only `src/data/demoWorkspace.ts` synthetic data; the schema `3.0` adapter is not imported by `App.tsx`;
- vault UI workflow, owner identity, conversation, and attestations remain a local React simulation with copy that explicitly says so (see `desktop/README.md`).

The v3 runtime must wait for the new audited backend commit created from parent `8cf3845...`. The current checkpoint does not expose those report fields.

## Apply transport package

From a clean checkout:

```text
git checkout codex/implement-vertical-skeleton-from-commit
git pull --ff-only
git rev-parse HEAD
```

For the original transport checkpoint, HEAD must equal:

```text
8cf3845f3ad1da032406faaa985a099e67fcac4a
```

Create a desktop branch and copy the package `desktop/` directory into the repository root. Do not overwrite Python files.

## Required validation

```text
cd desktop
npm ci
npm run lint
npm run build
npm run test
npm audit --audit-level=low
cd src-tauri
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test
cd ..
npm run tauri dev
```

Start development with an explicit provider, for example in PowerShell:

```powershell
$env:CONTINUITY_REASONING_PROVIDER = "deterministic_offline"
$env:CONTINUITY_BACKEND_ROOT = (Resolve-Path "..").Path
npm run tauri dev
```

`deterministic_offline` is development/test infrastructure and must not be described as a live model run.

## Stop conditions

Stop and report rather than changing the backend if:

- the Rust process cannot start the exact canonical module;
- stdout contains anything except one NDJSON response per command;
- a response command does not match the request command;
- the UI is asked to derive report conclusions from neutral evidence;
- any proposed fix would add HTTP/FastAPI;
- any proposed fix would duplicate vault or reasoning logic in Rust/TypeScript;
- executable Project Report integration is requested before the audited v3 backend SHA exists.
