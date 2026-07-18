# Desktop Integration Checkpoint

Backend transport base:

- branch: `codex/implement-vertical-skeleton-from-commit`
- checkpoint: `8cf3845f3ad1da032406faaa985a099e67fcac4a`
- normative process contract: `docs/BRIDGE_PROCESS_CONTRACT_v0.1.md`

The desktop package adds only `desktop/` and does not modify Python core, vault, reasoning, or Bridge commands.

## Current scope

Implemented and locally tested:

- approved React/Tauri shell;
- persistent managed Python process;
- UTF-8 NDJSON transport;
- typed command/session layer for the transport checkpoint;
- TypeScript contract and display adapter prepared for Project Report schema `3.0`.

Not yet enabled:

- executable Project Report v3 rendering from Bridge responses.

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
$env:CONTINUITY_REASONING_PROVIDER = "fake_aurora"
$env:CONTINUITY_BACKEND_ROOT = (Resolve-Path "..").Path
npm run tauri dev
```

`fake_aurora` is development/test infrastructure and must not be described as a live model run.

## Stop conditions

Stop and report rather than changing the backend if:

- the Rust process cannot start the exact canonical module;
- stdout contains anything except one NDJSON response per command;
- a response command does not match the request command;
- the UI is asked to derive report conclusions from neutral evidence;
- any proposed fix would add HTTP/FastAPI;
- any proposed fix would duplicate vault or reasoning logic in Rust/TypeScript;
- executable Project Report integration is requested before the audited v3 backend SHA exists.
