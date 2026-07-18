# Project Report v3 Frontend Preparation

Normative backend contract:

- `AnalysisResult.schema_version`: `3.0`
- prompt version: `g03_reasoning_v3`
- current transport checkpoint: `8cf3845f3ad1da032406faaa985a099e67fcac4a`
- executable report integration gate: the new audited backend commit created from that parent on `codex/implement-vertical-skeleton-from-commit`

The current checkpoint proves the persistent UTF-8 NDJSON process contract. It does not yet implement the Project Report display projection.

## Prepared now

`src/bridge/contracts.ts` defines:

- decrypted owner display name after initialize/unlock;
- neutral G-02 evidence-record projection;
- project identity;
- the exact seven Project Report section keys;
- the closed section-status enum;
- schema `3.0` analysis and workspace state;
- Project Report persistence/restoration projection.

`src/bridge/projectReportProjection.ts`:

- requires all seven sections exactly once and in contract order;
- rejects invalid evidence-gap wording or evidence-gap citations;
- rejects duplicate, empty, or unresolvable span IDs;
- resolves report citations only from backend-returned citation cards;
- enforces break/no-break consistency at the UI trust boundary;
- maps only presentation labels, icons, and visual tones;
- displays `Local owner` whenever the vault is locked, regardless of any prior decrypted name.

The adapter does not inspect source content, filenames, evidence IDs, semantic roles, or citation order to derive conclusions.

## Deliberately not enabled

The approved Aurora Current Report remains backed by demonstration data until the audited backend commit implements the v3 runtime response.

Do not wire the report adapter into `App.tsx` against checkpoint `8cf3845...`.

## Validation performed

```text
npm run lint
npm run test       # 17 passed
npm run build
npm audit --audit-level=low   # 0 vulnerabilities
```

## Runtime integration gate

Before enabling backend report rendering:

1. obtain the new audited backend commit SHA;
2. verify `docs/BRIDGE_PROCESS_CONTRACT_v0.1.md` and the Project Report contract are implemented at that SHA;
3. run the real process sequence on Windows;
4. validate initialize/unlock owner behavior;
5. validate `load_project` project and evidence records;
6. validate fresh analysis and restart restoration of `project_report`;
7. recreate old schema `2.0` demonstration vaults rather than silently migrating them.
