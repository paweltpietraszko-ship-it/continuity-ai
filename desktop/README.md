# Continuity AI Desktop

Tauri 2 + React 18 + TypeScript desktop client for Continuity AI.

## Current implementation status

Implemented:

- approved UI shell and navigation;
- managed persistent Python child process;
- UTF-8 NDJSON request/response transport over stdin/stdout;
- explicit provider and backend-root configuration;
- process startup handshake and graceful EOF shutdown with bounded kill fallback;
- exact command/response ordering validation;
- typed frontend Bridge contracts and controlled-error handling;
- canonical restart sequence that restores retained analysis without re-running analysis;
- native folder/file picker dependency for artifact and vault selection.

Not yet connected to product components:

- project report sections;
- owner display identity;
- source drawer neutral evidence records.

The current backend contract does not return these fields. The UI must not infer them.

## Required environment

Run from the Continuity AI repository root or set:

```text
CONTINUITY_BACKEND_ROOT=<absolute repository root>
CONTINUITY_PYTHON=<python executable, optional; defaults to python>
CONTINUITY_REASONING_PROVIDER=fake_aurora | openai
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
