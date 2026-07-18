# Project Source Scoping v0.1 — Bridge integration

The integration is optional and backward compatible until scoping is started.

## Commands

`scope_project_sources`

- precondition: a project and artifact evidence are loaded;
- authoritative target: `Bridge.project`;
- an optional `target_project` command field must equal `Bridge.project` exactly;
- success: validated `source_scope` plus hydrated citation cards;
- effect: invalidates any in-memory analysis and enters `pending_review`.

`confirm_source_scope`

- required: `overrides`, an object mapping evidence IDs to `included` or `excluded`;
- every ambiguous record must be present;
- non-ambiguous records may also be corrected;
- success: `approved_source_scope`, filtered evidence count, and persistence status;
- effect: only approved artifact records remain active for downstream analysis.

`analyze_project`

- unchanged when source scoping was never started;
- fails closed while review is pending or restored scope state is invalid;
- after approval, runs Project Report reasoning only on approved artifacts plus any existing authenticated user attestations.

`get_workspace_state`

- remains byte-shape compatible before scoping: no source-scoping keys are added while status is `none`;
- after scoping, adds `source_scoping_status`, `source_scope`, `approved_source_scope`, and `source_scope_persisted`.

## Persistence and restart

Approved scope state is appended inside encrypted vault payload field `approved_source_scopes`. Old vaults without this field remain readable. The newest matching scope is restored only when target project and the ordered SHA-256 fingerprint set of all artifact records still match. A malformed newest matching scope is `invalid`; restoration never falls back to an older scope.

If a restored retained analysis was produced from a different evidence snapshot than the restored approved scope, the in-memory analysis is invalidated rather than displayed against a new source boundary. A malformed or stale restored scope also removes any retained report from the visible workspace state and blocks downstream analysis.

## Desktop status

No Rust/Tauri desktop file exists in the audited backend checkpoint used by this branch. The backend command contract and response fields are implemented and tested; visual review controls are not fabricated on this branch and remain a later integration task.
