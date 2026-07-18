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

## Additional Project Report v3 preparation audit

The runtime report is intentionally not enabled yet. Also verify:

18. `ProjectReport` types match schema `3.0`, with exactly seven closed section keys in the normative order.
19. Section statuses are limited to `confirmed`, `attention`, `evidence_gap`, and `not_applicable`.
20. Evidence-gap sections accept only empty span lists and the exact backend-fixed wording.
21. Every non-gap report span resolves only through a returned backend citation card.
22. No adapter searches source content, filenames, semantic annotations, evidence IDs, or cached demo records to construct report conclusions.
23. Locked owner display is always `Local owner`; a decrypted owner name is not cached across lock.
24. `App.tsx` does not claim executable Project Report v3 integration before the new audited backend SHA exists.
