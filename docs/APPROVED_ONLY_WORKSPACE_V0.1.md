# Approved-only workspace materializer v0.1

## Boundary and invariant

This component publishes a new downstream workspace from explicit human-approved
selections. It never discovers evidence. It opens only source-relative paths named
in the request and never enumerates the original workspace. Directory inspection is
limited to the ancestors of those selected paths and the destination parent for
link/reparse-point validation.

The v0.1 trust invariant is:

> An operation that reduces trust or changes the downstream channel must never
> widen the evidence set.

The component is intentionally not integrated with Source Scoping, Bridge, the
Codex session controller, desktop, reasoning providers, or Project Report.

## Public input contract

`ApprovedWorkspaceRequest` is a frozen typed value containing:

- `original_workspace_root: Path`;
- `approved_artifacts: tuple[ApprovedArtifactSelection, ...]`;
- `approved_attestations: tuple[ApprovedHumanAttestation, ...]`;
- `destination_workspace_root: Path`;
- optional `source_scope_binding: SourceScopeBinding`.

Each `ApprovedArtifactSelection` contains one stable `evidence_id`, one
canonical portable `source_relative_path`, a required lowercase SHA-256, and an
optional expected byte size. The expected hash is always verified. If a
`SourceScopeBinding` supplies `expected_source_fingerprints`, that tuple must be
the complete fingerprint multiset of the approved artifact selections; a mismatch
fails before staging. The binding itself is an opaque SHA-256, so it cannot carry
excluded names, paths, prompts, or identifiers.

An empty artifact approval is rejected in v0.1, including an attestation-only
request. This is deliberate fail-closed behavior.

## Approved human attestations

`ApprovedHumanAttestation` contains:

- stable `attestation_id`;
- JSON-compatible `downstream_data` that was explicitly approved;
- `human_actor_id`;
- `approval_reference`;
- `approval_status`.

Only the enum value `approved` is accepted. Pending and rejected values fail the
whole request. Data is copied into private normalized containers during validation,
so later mutation of a caller-owned dictionary cannot affect publication. JSON
objects are key-sorted recursively; floats and non-JSON values are rejected.
Credential-shaped fields (`password`, `secret`, `credentials`,
`session_key`, `owner_secret`, and `api_key`, including hyphen/space
variants) are rejected recursively. Because arbitrary approved text cannot be
semantically classified as a secret by a filesystem boundary, the caller remains
responsible for ensuring explicitly approved scalar text contains no credentials or
owner secrets.

The canonical generated file is:

`.continuity/approved_attestations.json`

It is UTF-8 canonical JSON with one final LF. Keys are sorted, insignificant
whitespace is absent, Unicode is emitted directly, and attestations are ordered by
attestation ID. Every entry is marked with provenance type
`human_attestation`. No vault or session state is consulted.

## Manifest

The canonical manifest is:

`.continuity/approved_workspace_manifest.json`

It uses the same canonical JSON encoding and contains:

- schema version `1.0`;
- deterministic `approved_workspace_id`;
- approved artifact evidence IDs, relative paths, verified SHA-256 values, and
  byte sizes;
- approved attestation IDs and per-attestation SHA-256 values;
- the generated attestation file's relative path, SHA-256, and byte size;
- the opaque source-scope binding and approved source fingerprints when supplied.

The manifest does not contain absolute roots, an original workspace inventory,
excluded/deferred metadata, prompts, credentials, vault contents, or timestamps.
The manifest fingerprint is SHA-256 over its exact canonical bytes and is returned
in the receipt. The manifest carries `approved_workspace_id` rather than its own
fingerprint, avoiding a self-referential hash.

## Deterministic identities

`approved_workspace_id` is SHA-256 over canonical JSON containing the verified
approved artifact entries, approved attestation fingerprints, schema version, and
optional opaque source binding. It identifies the approved logical inputs without
including a machine path.

The final workspace fingerprint is SHA-256 over canonical JSON of:

- schema version `1.0`; and
- every regular file in the staged approved workspace, ordered by portable
  relative path, with its relative path, SHA-256, and byte size.

This file list includes both generated `.continuity` JSON files. It includes no
directory timestamps, filesystem object identities, absolute paths, permissions, or
enumeration order. `compute_workspace_fingerprint` independently recomputes the
same identity from a published workspace and rejects links, reparse points,
directories masquerading as files, and other special file types.

## Path and file safety

Selected paths use canonical NFC-normalized forward-slash syntax. The materializer
rejects absolute paths, drive-qualified paths, backslashes, `.`, `..`, repeated
separators, Windows forbidden characters and device names, trailing spaces/dots,
control characters, and the reserved `.continuity` namespace. It rejects exact,
case-folded, and file-versus-parent path collisions on every platform.

The source root, every selected ancestor, and every selected item are checked with
`lstat`. Symbolic links, Windows junctions, and anything carrying
`FILE_ATTRIBUTE_REPARSE_POINT` are rejected without following them. Selected
items must be regular files. Opening uses `O_NOFOLLOW` where the host exposes it
and validates the opened file identity against the prior `lstat`. File identity,
size, and modification state are checked around the initial streaming copy.

Source and destination are normalized lexically and rejected if either contains the
other or they are equal. The destination must not exist. Every existing destination
parent component is validated as a real directory without a link or reparse point.

Each selected source is streamed to its one explicit staged path while hashing. Its
hash and optional size are checked, the staged copy is rehashed, and all approved
sources are opened and hashed again after the complete staged workspace has been
fingerprinted. Every staged artifact and generated file, plus the complete workspace
fingerprint, is revalidated immediately before publication.

## Atomic publication and failures

After all input and boundary validation, the materializer creates a unique temporary
sibling named with the reserved `.continuity-approved-stage-` prefix. It copies
approved files, writes attestations, writes the manifest, fingerprints the complete
stage, revalidates sources and staged bytes, then publishes with one same-parent
`os.rename`. Existing destinations are never intentionally replaced.

Any failure before the rename removes the known temporary sibling where safely
possible and returns no receipt. The original workspace is read-only. Public errors
contain only a `FailureCategory`; they do not include source paths, evidence IDs,
file contents, or operating-system error text.

## Receipt

A successful `MaterializationReceipt` is frozen and contains:

- schema version;
- approved workspace ID;
- destination root (non-identity operational field);
- final workspace fingerprint;
- manifest fingerprint;
- approved artifact and attestation counts;
- the caller-supplied opaque source-scope binding;
- publication status `published`;
- `failure_category=None`.

Failures raise `ApprovedWorkspaceMaterializationError` with a sanitized category
and never return a partial success receipt.
