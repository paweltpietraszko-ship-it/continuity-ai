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

## Additional Project Report v3 preparation audit

The runtime report is intentionally not enabled yet. Also verify:

18. `ProjectReport` types match schema `3.0`, with exactly seven closed section keys in the normative order.
19. Section statuses are limited to `confirmed`, `attention`, `evidence_gap`, and `not_applicable`.
20. Evidence-gap sections accept only empty span lists and the exact backend-fixed wording.
21. Every non-gap report span resolves only through a returned backend citation card.
22. No adapter searches source content, filenames, semantic annotations, evidence IDs, or cached demo records to construct report conclusions.
23. Locked owner display is always `Local owner`; a decrypted owner name is not cached across lock.
24. `App.tsx` does not claim executable Project Report v3 integration before the new audited backend SHA exists.
