# Semantic Project and Decision Scope Resolution Contract v0.1

Status: normative contract candidate v0.1
Date: 2026-07-18
Scope: Semantic Project Resolution and Decision Scope Resolution

This document is authoritative for semantic-resolution behavior where older documents are silent or conflict within this scope. It does not replace or modify the G-02 `EvidenceRecord` contract. It does not replace the existing continuity-analysis result contract. It does not alter vault, citation, attestation, or bridge invariants unless explicitly stated.

Implementation is forbidden until this contract is independently falsified and accepted.

## 1. Product boundary

The current system analyzes user-selected, already grouped project artifacts.

The capability introduced by this contract is narrower than general discovery: Continuity AI resolves how naturally written references relate to backend-known projects and operational targets inside a user-selected candidate workspace.

This contract does not authorize:

- a universal knowledge graph;
- automatic project discovery across a computer;
- filesystem-wide scanning;
- persistent alias learning;
- arbitrary multi-project infrastructure;
- full persistence of resolution records;
- a complete entity-management UI;
- a production-grade universal resolver;
- automatic modification of source documents;
- automatic broadening from one variant to all variants.

## 2. Frozen competition slice

The competition implementation boundary is exactly:

- one candidate workspace;
- one canonical Project Aurora profile;
- naturally varied references to Aurora;
- one minimal unrelated decoy source for the Aurora profile;
- deterministic supporting span IDs;
- backend validation;
- no automatic assignment when ambiguity remains;
- one controlled live semantic-resolution run followed by continuity analysis;
- one small test-only LynxMask Mobile/Desktop Decision Scope fixture;
- no LynxMask UI integration;
- no LynxMask production workflow;
- no full persistence of resolution confirmations.

The presence of only one registered project in the competition workspace MUST NOT cause every source to be assigned to that project.

## 3. Frozen logical pipeline

```text
candidate workspace
-> unchanged deterministic G-02 ingestion
-> resolution-context adapter
-> canonical project/object registry
-> source-level reference extraction
-> cross-document reconciliation
-> deterministic backend validation
-> ambiguity/unrelated handling
-> resolved EvidenceSet
-> existing continuity analysis
-> backend-owned citation cards
```

The following invariants apply:

- The G-02 `EvidenceRecord` remains unchanged.
- Semantic resolution is a layer above G-02.
- Continuity analysis MUST NOT run before the semantic-resolution gate permits it.
- Source content MUST NOT be rewritten by the resolution layer.
- G-02 deterministic ordering MUST be preserved in the resolved `EvidenceSet`.

## 4. Definitions

### 4.1 Candidate workspace

A **candidate workspace** is the bounded, user-selected set of already ingested source artifacts presented for resolution together with a backend-owned canonical registry. It is not a filesystem search scope and does not imply that every contained source belongs to the target project.

### 4.2 Canonical project

A **canonical project** is a backend-registered project identity represented by one opaque `project_id`, one canonical display name, zero or more known aliases, and zero or more owned object IDs. The model MUST NOT create, rename, or merge canonical projects.

### 4.3 Canonical object

A **canonical object** is a backend-registered operational target, product variant, subsystem, release, workflow, or other bounded object owned by exactly one canonical project and represented by one opaque `object_id`.

### 4.4 Known alias

A **known alias** is a backend-provided string that may help interpret a source reference. A known alias is a clue, not automatic proof. A known alias MUST NOT resolve a source when the same alias maps to multiple candidates or when the cited source context contradicts the mapping.

The absence of a registered alias does not prevent contextual resolution.

### 4.5 Natural reference

A **natural reference** is text that refers to a project or object through ordinary language rather than necessarily using a canonical name or registered alias. Examples of its linguistic form include ownership, pronouns, descriptions, short names, production references, and relational phrases. A natural reference MAY be implicit or elliptical. The model may recognize natural references that are not pre-registered aliases, but it may resolve them only to backend-provided candidate IDs.

Implicit or elliptical examples include:

- “Approved.”;
- “Do it.”;
- “Move it there.”;
- “Update the budget.”;
- “That works.”

These utterances are natural references when their project meaning comes from bounded parent/reply, thread, adjacency, participant, or cross-document context. Their text need not contain a project name, alias, noun phrase, or pronoun.

### 4.6 Project resolution

**Project resolution** is the grounded assignment, exclusion, or non-assignment of each candidate source relative to backend-provided canonical project IDs. It uses source text plus bounded cross-document and relationship context and produces one validated source resolution per input `EvidenceRecord`.

### 4.7 Decision-scope resolution

**Decision-scope resolution** is the grounded determination of which backend-provided operational target IDs a decision applies to, or that the scope remains ambiguous or unresolved. It MUST NOT broaden a decision beyond the supported target set.

### 4.8 Resolved EvidenceSet

A **resolved EvidenceSet** is the deterministic ordered collection of unchanged G-02 evidence records admitted for one caller-selected target project after a valid semantic project-resolution result passes the resolution gate.

### 4.9 Supporting span

A **supporting span** is a deterministic backend-generated `EvidenceSpan` supplied in the request and returned by ID to ground a resolution. Supporting spans identify inspectable source text; they do not by themselves prove that the model's interpretation is semantically true.

### 4.10 Reason code

A **reason code** is a value from a closed, layer-specific enum that classifies the grounded basis or failure mode of a resolution. It is not free prose, confidence, or a substitute for supporting spans.

### 4.11 Unrelated

**Unrelated** means the supplied evidence positively supports that a source has no supported relation to any candidate project in the registry for this request. An unrelated source is excluded but does not, by itself, block continuity analysis.

### 4.12 Unresolved

**Unresolved** means the available bounded evidence is insufficient to resolve a source or decision scope and insufficient to make the stronger applicable finding. Unresolved is not a negative match and requires human confirmation before the gate can open.

### 4.13 Ambiguous

**Ambiguous** means at least two backend-provided candidates remain plausible and the available evidence does not safely choose among them. No candidate may be selected automatically.

### 4.14 Resolution confirmation

A **resolution confirmation** is an explicit authenticated local-owner mapping from a grounded natural reference or ambiguous decision scope to existing backend-owned IDs. It governs grouping or scope; it is not automatically historical source evidence.

### 4.15 Project fact attestation

A **project fact attestation** is an authenticated owner statement that, after the existing explicit proposal-and-confirmation flow, becomes provenance-bearing project evidence. In the current system this semantic role is carried by the existing `AuthenticatedUserAttestation` contract. It asserts project content; it is distinct from a resolution confirmation, which maps meaning or scope. This definition does not modify the existing attestation contract.

## 5. Canonical project/object registry

The registry top-level object MUST contain exactly these fields:

- `schema_version`;
- `workspace_id`;
- `projects`;
- `objects`.

`schema_version` MUST be `semantic-resolution-registry.v1`.

Each project record MUST contain exactly:

- `project_id`;
- `canonical_name`;
- `known_aliases`;
- `object_ids`.

Each object record MUST contain exactly:

- `object_id`;
- `project_id`;
- `object_type`;
- `canonical_name`.

All IDs are backend-owned. The model MUST NOT create IDs. `project_id` and `object_id` values are opaque identifiers. Every object MUST belong to an existing project. The `object_ids` in a project MUST exactly match the objects owned by that project.

The registry MUST NOT contain expected model answers. The registry MUST NOT contain test ground truth. Filename, folder, and registry membership alone are not evidence that a source belongs to a project.

### 5.1 Minimal Aurora registry example

This is a shape and authority example, not a production expected answer:

```json
{
  "schema_version": "semantic-resolution-registry.v1",
  "workspace_id": "WORKSPACE-AURORA-CANDIDATE",
  "projects": [
    {
      "project_id": "PROJECT-AURORA",
      "canonical_name": "Project Aurora",
      "known_aliases": ["Aurora"],
      "object_ids": ["OBJECT-AURORA-PRODUCTION"]
    }
  ],
  "objects": [
    {
      "object_id": "OBJECT-AURORA-PRODUCTION",
      "project_id": "PROJECT-AURORA",
      "object_type": "production",
      "canonical_name": "Aurora production"
    }
  ]
}
```

The example does not establish that a particular source belongs to Aurora. Even with a sole candidate, the model and backend MUST preserve `unrelated`, `unresolved`, and gate-blocking behavior.

### 5.2 Separate test-only LynxMask registry example

The following registry is permitted only for the bounded Decision Scope test profile:

```json
{
  "schema_version": "semantic-resolution-registry.v1",
  "workspace_id": "WORKSPACE-LYNXMASK-TEST-ONLY",
  "projects": [
    {
      "project_id": "PROJECT-LYNXMASK",
      "canonical_name": "LynxMask",
      "known_aliases": [],
      "object_ids": [
        "PRODUCT-LYNXMASK-DESKTOP",
        "PRODUCT-LYNXMASK-MOBILE"
      ]
    }
  ],
  "objects": [
    {
      "object_id": "PRODUCT-LYNXMASK-DESKTOP",
      "project_id": "PROJECT-LYNXMASK",
      "object_type": "product_variant",
      "canonical_name": "LynxMask Desktop"
    },
    {
      "object_id": "PRODUCT-LYNXMASK-MOBILE",
      "project_id": "PROJECT-LYNXMASK",
      "object_type": "product_variant",
      "canonical_name": "LynxMask Mobile"
    }
  ]
}
```

The competition fixture MUST NOT require a LynxMask family object ID unless that ID has a precise validation purpose. No such family object ID is required by v0.1.

## 6. Resolution context adapter

Semantic resolution adds a context record above G-02 named `ResolutionContextRecord`. It MUST NOT add fields to or reinterpret `EvidenceRecord`.

`ResolutionContextRecord` MUST contain exactly:

- `evidence_id`;
- `thread_subject`;
- `participant_ids`;
- `parent_evidence_id`;
- `adjacent_evidence_ids`;
- `attachment_evidence_ids`.

Field rules are:

- `evidence_id` MUST be a non-null ID of one request evidence record.
- `thread_subject` MUST be a non-empty string or null. Missing or empty source metadata MUST become null, not an invented subject.
- `participant_ids` MUST be a list of unique backend-owned participant IDs and MAY be empty.
- `parent_evidence_id` MUST be an evidence ID in the candidate workspace or null.
- `adjacent_evidence_ids` MUST be a list of unique evidence IDs in the candidate workspace and MAY be empty.
- `attachment_evidence_ids` MUST be a list of unique evidence IDs in the candidate workspace and MAY be empty.

There MUST be exactly one `ResolutionContextRecord` for every request evidence record. Duplicate relationship IDs within a record are forbidden.

All relationships are backend-owned. Relationship metadata MUST be derived deterministically from available source metadata. Missing relationship data remains null or empty. The backend MUST NOT fabricate relationships.

Every textual proposition used to support a resolution MUST be identified through valid deterministic `supporting_span_ids`. Backend-owned relationship facts such as `thread_subject`, participant overlap, parent/reply linkage, adjacency, and attachment linkage MUST remain inspectable through the relevant `ResolutionContextRecord` values. Relationship metadata MUST NOT be converted into fabricated `EvidenceSpan` records.

A resolution MAY rely on both textual spans and deterministic relationship metadata. The result's `evidence_id`, `supporting_span_ids`, and `reason_codes` together identify which source and supporting evidence records, and therefore which corresponding `ResolutionContextRecord` relationships, the backend MUST validate.

The backend MUST preserve the exact `ResolutionContextRecord` values used for request construction for audit and testing. `ResolutionContextRecord` is semantic-layer request metadata, not historical source quotation and not a citation card.

User-visible citations remain exact historical source spans. Backend relationship explanations MAY be displayed separately as resolution metadata and MUST NOT be presented as source quotations.

Folders and filenames MAY be included only as weak operational metadata in an adapter implementation, outside the provider request fields frozen below, and MUST NOT independently resolve project identity.

## 7. Deterministic request and result ordering

Canonical ordering is backend-owned and MUST be deterministic:

- `projects` MUST be ordered by `project_id`.
- `objects` MUST be ordered by `object_id`.
- Each project's `object_ids` MUST be ordered by `object_id`.
- `known_aliases` MUST be Unicode-normalized to NFC and ordered deterministically by normalized Unicode scalar value. Normalized duplicates are forbidden.
- `evidence` MUST preserve G-02 order.
- `spans` MUST be ordered by evidence order and then ascending `index`.
- `resolution_context` MUST be ordered by evidence order.
- `participant_ids`, `adjacent_evidence_ids`, and `attachment_evidence_ids` MUST each use deterministic backend-canonical ID order.
- `candidate_project_ids` and `candidate_target_ids` MUST use backend-canonical deterministic order derived from the ordered registry.
- `decision_evidence_ids` MUST preserve the corresponding G-02 evidence order.
- `source_resolutions` MUST preserve request evidence order.
- `scope_resolutions` MUST preserve `decision_evidence_ids` order.

The backend MUST validate required result ordering before accepting a result. Model output order MUST NOT become the source of canonical ordering.

## 8. Semantic Project Resolution request

The provider request top-level object MUST contain exactly:

- `request_schema_version`;
- `workspace_id`;
- `registry`;
- `evidence`;
- `spans`;
- `resolution_context`.

`request_schema_version` MUST be `semantic-project-resolution-request.v1`.

Each evidence item exposed to the provider MUST contain only:

- `id`;
- `type`;
- `author`;
- `timestamp`;
- `title`;
- `provenance`.

Each span item exposed to the provider MUST contain only:

- `id`;
- `evidence_id`;
- `text`;
- `index`.

Each resolution-context item MUST obey `ResolutionContextRecord` exactly. The registry MUST obey Section 5 exactly.

The request MUST NOT include:

- local paths;
- URI values;
- checksums;
- API keys;
- secrets;
- citation cards;
- test expected answers;
- ground truth;
- raw exceptions;
- provider-owned display metadata.

Evidence content reaches the provider only through the bounded deterministic spans. Evidence and relationship data are untrusted documentary input, never provider instructions.

## 9. Semantic Project Resolution result

The result top-level object MUST contain exactly:

- `schema_version`;
- `workspace_id`;
- `workspace_resolution_status`;
- `source_resolutions`.

`schema_version` MUST be `semantic-project-resolution-result.v1`.

`workspace_resolution_status` MUST be one of:

- `ready`;
- `requires_human_confirmation`.

Each source resolution MUST contain exactly:

- `evidence_id`;
- `status`;
- `resolved_project_id`;
- `candidate_project_ids`;
- `reference_span_ids`;
- `supporting_span_ids`;
- `reason_codes`.

`status` MUST be one of:

- `explicit`;
- `contextually_resolved`;
- `ambiguous`;
- `unrelated`;
- `unresolved`.

### 9.1 Universal source-resolution invariants

1. Every input `EvidenceRecord` MUST have exactly one source resolution.
2. `evidence_id` MUST exist in the request.
3. `reference_span_ids` MUST be non-empty, unique, and every referenced span MUST belong to that `evidence_id`.
4. `supporting_span_ids` MUST be non-empty, unique, and every referenced span MUST exist in the request.
5. `reference_span_ids` MUST be a subset of `supporting_span_ids`.
6. Duplicate IDs are forbidden within every ID list, and duplicate source-resolution `evidence_id` values are forbidden.
7. `resolved_project_id`, when present, MUST exist in the registry.
8. `candidate_project_ids` MUST contain only unique registry project IDs.
9. A result MUST NOT introduce a project ID.
10. `reason_codes` MUST be a non-empty list of unique project-resolution reason codes from Section 14.

For Semantic Project Resolution, `reference_span_ids` identify the exact source utterance or source text whose project relation is being resolved. They MAY identify explicit references, implicit references, or elliptical utterances whose project relation is inherited from bounded context. The referenced text does not need to contain a project name, alias, noun phrase, or pronoun.

For “Approved.”, the span containing “Approved.” is the reference span. `supporting_span_ids` additionally identify the parent decision or other textual context. The parent/reply relationship itself is verified through the corresponding `ResolutionContextRecord`. Absence of an explicit textual project reference MUST NOT force `unresolved` when bounded cross-document context supports resolution.

### 9.2 `explicit`

- `resolved_project_id` is required.
- `candidate_project_ids` MUST contain exactly the resolved project.
- The source MUST contain an explicit canonical project identifier, canonical name, or uniquely mapped known alias.
- A known alias is not explicit if it maps to multiple candidates.
- `reference_span_ids` and `supporting_span_ids` MUST ground the explicit text in the source.

### 9.3 `contextually_resolved`

- `resolved_project_id` is required.
- `candidate_project_ids` MUST contain the resolved project and MAY contain other backend-provided candidates that were considered.
- `reference_span_ids` MUST identify the explicit, implicit, or elliptical source utterance or text whose project relation is resolved.
- `supporting_span_ids` MUST include every reference span and at least one additional valid contextual span.
- At least one additional contextual span MUST differ from the reference spans.
- A contextually resolved project result MAY be semantically supported by: additional textual context within the same evidence record; textual context from another evidence record; deterministic parent, thread, participant, adjacency, or attachment relationships; or a combination of these.
- Relationship metadata used by the resolution MUST remain in `ResolutionContextRecord`; it MUST NOT be converted into an additional span.
- Deterministic validation proves only the required valid span IDs and any declared structural relationship prerequisites. It does not prove that the context semantically establishes the selected project.

### 9.4 `ambiguous`

- `resolved_project_id` MUST be null.
- `candidate_project_ids` MUST contain at least two plausible registry projects.
- The source MUST NOT be included automatically.
- `workspace_resolution_status` MUST be `requires_human_confirmation`.

### 9.5 `unrelated`

- `resolved_project_id` MUST be null.
- `candidate_project_ids` MUST be empty.
- The source MUST be excluded.
- `reference_span_ids` MUST identify the exact source text whose subject or wording is classified as unrelated and MUST remain included in `supporting_span_ids`.
- `supporting_span_ids` MUST ground the positive unrelated finding.
- `unrelated` alone MUST NOT block continuity analysis.

### 9.6 `unresolved`

- `resolved_project_id` MUST be null.
- `candidate_project_ids` MAY be empty or MAY contain the backend-provided candidates still under consideration.
- `reference_span_ids` MUST identify the exact source text whose subject or wording remains unresolved and MUST remain included in `supporting_span_ids`.
- The available context does not support either resolution or a positive unrelated finding.
- The source MUST be excluded.
- `workspace_resolution_status` MUST be `requires_human_confirmation`.

`workspace_resolution_status` is `ready` only when no source is `ambiguous` or `unresolved`. It MUST be `requires_human_confirmation` when any source is `ambiguous` or `unresolved`.

An ambiguous or unresolved source MUST NOT silently disappear into Pass B.

## 10. Resolved EvidenceSet

Resolved `EvidenceSet` composition is deterministic:

1. The caller identifies the target `project_id`.
2. The backend validates the complete project-resolution result before composing anything.
3. Only sources with status `explicit` or `contextually_resolved` whose `resolved_project_id` equals the caller's target are included.
4. Sources with status `unrelated` are excluded.
5. Any source with status `ambiguous` or `unresolved` blocks the resolution gate and prevents continuity analysis.
6. G-02 evidence records and their content remain unchanged.
7. Original G-02 ordering is preserved; the resolution layer MUST NOT re-sort by model output order, status, or confidence.
8. Only valid spans belonging to included evidence are supplied to continuity analysis.
9. Backend-owned citation hydration remains unchanged.
10. The resolution result is not itself a historical source quotation and MUST NOT be rendered as one.

The caller's target ID MUST exist in the request registry. A sole target candidate MUST NOT turn excluded, ambiguous, or unresolved material into included evidence.

## 11. Decision Scope Resolution request

The request top-level object MUST contain exactly:

- `request_schema_version`;
- `project_id`;
- `candidate_target_ids`;
- `decision_evidence_ids`;
- `registry`;
- `evidence`;
- `spans`;
- `resolution_context`.

`request_schema_version` MUST be `decision-scope-resolution-request.v1`.

`project_id`, `candidate_target_ids`, and `decision_evidence_ids` are backend-provided. The registry MUST obey the canonical registry contract in Section 5. `project_id` MUST exist in that registry. `candidate_target_ids` MUST be non-empty, unique, and contain only object IDs owned by `project_id`.

For every candidate target, the provider MUST receive its `canonical_name` and `object_type` through the registry. Every `candidate_target_ids` value MUST resolve to exactly one registry object. The provider MUST NOT infer target meaning from the spelling of project or object IDs.

`decision_evidence_ids` MUST be non-empty and unique. Every ID MUST exist in request `evidence`. The list identifies exactly the decision-bearing sources for which scope resolution is required. It is backend-owned; the model cannot add or remove coverage.

The `evidence`, `spans`, and `resolution_context` items MUST obey the provider-safe field boundaries in Sections 6 and 8. The request MUST obey the same forbidden-data boundary as the Semantic Project Resolution request.

Renaming every project and object ID to semantically opaque values while preserving registry metadata MUST NOT change the semantic result.

## 12. Decision Scope Resolution result

The result top-level object MUST contain exactly:

- `schema_version`;
- `project_id`;
- `scope_resolutions`.

`schema_version` MUST be `decision-scope-resolution-result.v1`.

Each scope resolution MUST contain exactly:

- `evidence_id`;
- `decision_span_ids`;
- `status`;
- `resolved_target_ids`;
- `candidate_target_ids`;
- `supporting_span_ids`;
- `reason_codes`.

`status` MUST be one of:

- `explicit`;
- `contextually_resolved`;
- `global`;
- `ambiguous`;
- `unresolved`.

### 12.1 Universal scope-resolution invariants

- The result MUST contain exactly one scope resolution for every `decision_evidence_ids` value and no scope resolution for any other evidence ID.
- `scope_resolutions` MUST preserve `decision_evidence_ids` order.
- `evidence_id` MUST exist in the request and MUST appear in `decision_evidence_ids`.
- `decision_span_ids` MUST be non-empty and unique, and every decision span MUST belong to the source `evidence_id`.
- `supporting_span_ids` MUST be non-empty, unique, and exist in the request.
- `decision_span_ids` MUST be a subset of `supporting_span_ids`.
- `candidate_target_ids` and `resolved_target_ids` MUST contain no duplicates.
- All target IDs MUST exist.
- All target IDs MUST belong to `project_id`.
- `candidate_target_ids` MUST be a subset of the backend-provided request candidates.
- `resolved_target_ids` MUST be a subset of `candidate_target_ids`.
- No unknown ID is permitted.
- `reason_codes` MUST be a non-empty list of unique Decision Scope reason codes from Section 14.

### 12.2 `explicit`

- `resolved_target_ids` MUST be non-empty.
- The source explicitly identifies the variant or target.
- Resolved targets MUST be a strict supported subset of `candidate_target_ids` unless explicit global language exists.
- When explicit global language exists and the full allowed candidate set is intended, the status MUST be `global`, not `explicit`.

### 12.3 `contextually_resolved`

- `resolved_target_ids` MUST be non-empty.
- Supporting spans MUST establish platform, subsystem, release, or workflow context.
- Supporting spans MUST include the decision spans and at least one additional contextual span.
- Deterministic validation proves only that at least one additional distinct valid supporting span ID exists. Whether that span establishes relevant platform, subsystem, release, or workflow context belongs to test-only evaluation and controlled live evaluation.
- Contextual resolution MUST NOT broaden to all candidates merely because all are available.
- `resolved_target_ids` MUST be a proper subset of `candidate_target_ids`.

### 12.4 `global`

- Explicit all-versions, all-platforms, whole-family, or equivalent language is required.
- `reason_codes` MUST contain `explicit_global_language`.
- `resolved_target_ids` MUST exactly equal `candidate_target_ids`.
- `candidate_target_ids` MUST exactly equal the full allowed candidate set supplied by the backend for this request.
- `decision_span_ids` MUST be included in `supporting_span_ids`.
- `global` MUST NOT be inferred from silence or a family name alone.
- Deterministic validation does not prove that the cited text actually expresses global scope. That semantic judgment belongs to test-only evaluation and controlled live evaluation.

### 12.5 `ambiguous`

- `resolved_target_ids` MUST be empty.
- `candidate_target_ids` MUST contain at least two plausible targets.
- No target is automatically selected.
- Human confirmation is required.

### 12.6 `unresolved`

- `resolved_target_ids` MUST be empty.
- `candidate_target_ids` MAY be empty or MAY contain backend-provided targets still under consideration.
- Available context is insufficient.
- Human confirmation is required.

“Remove Express Mode from LynxMask” without variant context is ambiguous, not global and not both.

A bounded Android/CameraX/three-tap context may support `PRODUCT-LYNXMASK-MOBILE` when the cited spans actually contain that context.

## 13. Resolution gates and Decision Scope use

Project resolution gates admission to Pass B. Decision Scope resolution gates application of a decision to operational targets. A Decision Scope result containing `ambiguous` or `unresolved` MUST stop any automatic target-specific interpretation or action. It MUST NOT cause the source itself to vanish from an already valid project `EvidenceSet`; rather, its decision scope remains unconfirmed.

No source or target may be selected because it is the only available candidate. Availability bounds authority; it does not prove semantic identity or scope.

## 14. Closed reason-code enums

`reason_codes` is a closed enum list, not free prose.

### 14.1 Project-resolution reason codes

- `explicit_project_id`;
- `canonical_name_match`;
- `known_alias_match`;
- `same_thread_context`;
- `parent_reply_context`;
- `shared_participants`;
- `shared_dates`;
- `shared_location`;
- `shared_operational_object`;
- `cross_document_sequence`;
- `insufficient_disambiguating_context`;
- `no_supported_project_relation`;
- `insufficient_context`.

### 14.2 Decision-scope reason codes

- `explicit_target_id`;
- `explicit_variant_language`;
- `explicit_global_language`;
- `platform_specific_context`;
- `subsystem_specific_context`;
- `workflow_specific_context`;
- `product_family_without_variant_context`;
- `insufficient_scope_context`.

Reason codes do not replace supporting spans. A reason code without valid spans is invalid. The backend MUST reject reason codes from the wrong layer or outside these enums.

Numeric confidence MUST NOT be used as the safety gate. Confidence is outside v0.1.

## 15. Backend validation

The backend MUST validate the complete response before exposing a resolution, composing an `EvidenceSet`, or continuing to Pass B. One failure rejects the entire resolution result; partial acceptance is forbidden.

### 15.1 Complete rejection matrix

| Condition | Project result | Scope result | Required backend outcome |
|---|---:|---:|---|
| Top-level fields differ from the exact schema | Yes | Yes | Reject entire result |
| Schema version differs | Yes | Yes | Reject entire result |
| Returned workspace or project ID differs from the request | Yes | Yes | Reject entire result |
| An evidence ID is unknown | Yes | Yes | Reject entire result |
| Required source coverage is incomplete, duplicated, or includes an extra source | Yes | Yes, against `decision_evidence_ids` | Reject entire result |
| A project or target ID is unknown | Yes | Yes | Reject entire result |
| A target does not belong to the stated project | N/A | Yes | Reject entire result |
| A span ID is unknown | Yes | Yes | Reject entire result |
| A reference or decision span belongs to the wrong evidence | Yes | Yes | Reject entire result |
| A supporting span is outside the request | Yes | Yes | Reject entire result |
| A reference or decision span is omitted from `supporting_span_ids` | Yes | Yes | Reject entire result |
| Candidate IDs exceed the backend-provided registry or request candidates | Yes | Yes | Reject entire result |
| Resolved IDs exceed candidate IDs | Yes | Yes | Reject entire result |
| Duplicate IDs occur where forbidden | Yes | Yes | Reject entire result |
| `ambiguous` contains a resolved ID | Yes | Yes | Reject entire result |
| `unrelated` contains candidate IDs | Yes | N/A | Reject entire result |
| `global` does not equal the full allowed candidate set | N/A | Yes | Reject entire result |
| `global` lacks the `explicit_global_language` reason code | N/A | Yes | Reject entire result |
| `global` decision spans are not included in supporting spans | N/A | Yes | Reject entire result |
| Contextual resolution lacks at least one additional distinct valid supporting span ID | Yes | Yes | Reject entire result |
| The model creates a new entity | Yes | Yes | Reject entire result |
| Result status and nullability or empty-list rules conflict | Yes | Yes | Reject entire result |
| Reason codes are empty, duplicated, unknown, or from the wrong layer | Yes | Yes | Reject entire result |
| `workspace_resolution_status` conflicts with source statuses | Yes | N/A | Reject entire result |
| Required deterministic ordering is violated | Yes | Yes | Reject entire result |
| `parent_reply_context` lacks the required parent-to-supporting-evidence relationship | Yes | N/A | Reject entire result |
| `same_thread_context` lacks a shared non-null thread subject with supporting evidence | Yes | N/A | Reject entire result |
| `shared_participants` lacks a non-empty participant intersection with supporting evidence | Yes | N/A | Reject entire result |
| `cross_document_sequence` lacks external supporting evidence or a qualifying adjacency, parent, or attachment relationship | Yes | N/A | Reject entire result |

For project resolution, coverage means exactly one source resolution for every input evidence record. For Decision Scope Resolution, coverage means exactly one scope resolution for every backend-owned `decision_evidence_ids` value and no scope resolution for any other evidence ID.

The backend orchestration layer MUST NOT rewrite an `ambiguous` or `unresolved` result into a resolved status without a new valid provider result or an authorized `AuthenticatedResolutionConfirmation`. The universal result validator cannot determine whether a structurally valid resolved status is a semantic misclassification.

### 15.2 Relationship reason-code prerequisites

For this section, a **relationship supporting evidence record** is a request evidence record other than the resolved source that is represented by at least one `supporting_span_ids` value. The universal validator MUST reject:

- `parent_reply_context` when the resolved source's `parent_evidence_id` does not identify a relationship supporting evidence record;
- `same_thread_context` when the resolved source and no relationship supporting evidence record share the same non-null `thread_subject`;
- `shared_participants` when the resolved source and no relationship supporting evidence record have a non-empty `participant_ids` intersection;
- `cross_document_sequence` unless at least one supporting span belongs to a relationship supporting evidence record and a backend-owned adjacent, parent, or attachment relationship connects the resolved source to such a record.

These checks prove only that the declared relationship exists. They MUST NOT claim that the relationship semantically proves the selected project.

Reason codes based on textual meaning, including `canonical_name_match`, `known_alias_match`, `shared_dates`, `shared_location`, and `shared_operational_object`, remain semantically evaluated through test-only profiles and controlled live evaluation. Their presence is structurally validated as closed-enum membership, but the universal validator does not prove their truth.

### 15.3 Deterministic proof boundary

The deterministic validator MAY prove only:

- exact fields;
- versions;
- enum membership;
- IDs;
- membership;
- nullability;
- array cardinality;
- exact coverage;
- span existence;
- span ownership;
- required span containment;
- candidate/resolved set relations;
- required reason-code presence;
- additional distinct contextual span IDs;
- the declared relationship prerequisites in Section 15.2.

The deterministic validator MUST NOT claim to prove:

- that a span semantically expresses global language;
- that a contextual span is actually relevant;
- that an alias truly denotes the selected project;
- that CameraX semantically proves Mobile;
- that an unrelated finding is semantically correct.

For `global`, structural validation MUST require that `reason_codes` contains `explicit_global_language`, that `resolved_target_ids` equals the full allowed candidate set, and that `decision_span_ids` is a subset of `supporting_span_ids`. Whether the cited text really expresses global scope belongs to test-only evaluation and controlled live evaluation.

For contextual resolution, deterministic validation proves only that the required additional distinct valid supporting span IDs exist. Their semantic relevance belongs to test-only evaluation and controlled live evaluation.

The validator proves structural grounding and authority boundaries.

The validator does not prove semantic truth.

The production validator MUST NOT hard-code:

- that Mara always means Aurora;
- that Northlight always means Aurora;
- that CameraX always means Mobile;
- that a folder name decides scope;
- that the newest document is true;
- the expected Aurora resolution output.

Semantic accuracy belongs in dedicated test-only evaluation profiles and controlled live evaluation, never in production request data, prompts, registries, or validators.

## 16. Human confirmation

The frozen confirmation record name is `AuthenticatedResolutionConfirmation`.

Its semantic role is constrained as follows:

- It records an authenticated local-owner mapping of a natural reference or ambiguous decision scope to existing backend-owned IDs.
- It is a provenance-bearing workspace mapping.
- It is not a `ProjectFactAttestation`.
- It does not prove that the underlying decision is true.
- It does not become source evidence automatically.
- It MAY affect grouping or scope in a later analysis.
- It requires a separate explicit confirmation control.
- A model cannot create or confirm it autonomously.

The minimal conceptual record MUST contain exactly:

- `schema_version`;
- `confirmation_id`;
- `workspace_id`;
- `actor_id`;
- `display_name`;
- `timestamp`;
- `resolution_kind`;
- `evidence_id`;
- `reference_span_ids`;
- `project_id`;
- `confirmed_target_ids`.

`resolution_kind` MUST be one of:

- `project_reference`;
- `decision_scope`.

Common rules are:

- `schema_version` MUST be `authenticated-resolution-confirmation.v1`.
- `confirmation_id`, `workspace_id`, `actor_id`, `display_name`, and `timestamp` are backend-owned and MUST NOT be supplied by the model.
- `workspace_id` MUST identify the candidate workspace in which the mapping was confirmed.
- `project_id` MUST always be an existing backend-owned project ID in the registry for `workspace_id`.
- `evidence_id` MUST identify an existing source belonging to `workspace_id`.
- `reference_span_ids` MUST be non-empty, unique, belong to `evidence_id`, and therefore belong to `workspace_id`.
- Confirmed IDs MUST already exist in the backend registry and MUST NOT be invented.

The field rules are mutually exclusive:

- For `project_reference`, `project_id` is the confirmed project and `confirmed_target_ids` MUST be empty.
- For `decision_scope`, `project_id` is the already resolved project and `confirmed_target_ids` MUST be a non-empty unique list of existing objects that all belong to `project_id`.

The record MUST NOT depend on an unstored external “established project context”. Its `workspace_id`, `project_id`, `evidence_id`, grounded spans, and any targets MUST make its authority boundary self-contained.

The dedicated confirmation proposal MUST be bound to the active unlocked vault session before confirmation. A confirmation MUST be created only by a dedicated authenticated confirmation command after the exact mapping is displayed to the owner. A generic message such as “yes” MUST NOT create it. The model cannot create or confirm the record. The record is not project fact evidence.

Full persistence, editing, supersession, and UI management of these records are outside the competition implementation unless separately authorized.

The bounded implementation MAY surface `requires_human_confirmation` and stop without implementing persistent confirmation storage.

## 17. Cross-document requirement

One-document classification is insufficient.

The provider MUST receive all bounded evidence and relevant relationships needed to interpret:

- short approvals;
- pronouns;
- “the project”;
- “the production”;
- participants;
- dates;
- locations;
- parent/reply relations;
- thread relations;
- adjacency relations;
- attachment relations;
- operational sequence.

The logical semantic pass MUST perform:

```text
source-level reference identification
-> cross-document reconciliation
```

This MAY occur in one auditable semantic-resolution Responses call for the competition slice. Every textual basis for a resolution MUST remain inspectable through deterministic span IDs. Backend-owned thread, participant, parent, adjacency, and attachment relationships MUST remain separately inspectable through the corresponding `ResolutionContextRecord` values. Relationship metadata MUST NOT be represented as fabricated historical spans.

Continuity analysis remains a separate Pass B.

## 18. Test profiles

All expected semantic outputs described in this section are test-only and MUST remain outside production inputs, prompts, registries, and validators.

### 18.1 Project Aurora semantic-resolution profile

The Aurora semantic-resolution profile MUST NOT change the existing G-01/G-02 fixture contract. It MUST use a separate dedicated resolution fixture or a derived candidate workspace.

The profile MUST contain:

- one source using `Project Aurora`;
- one source using `Aurora`;
- one source using `Mara's film`;
- one source using `the Northlight shoot` or `the production`;
- one source using `the current project`;
- one unrelated decoy source;
- no requirement for a full second project;
- test-only expected outputs stored outside production inputs;
- no expected answer in the production prompt, registry, or validator.

The expected test behavior MUST prove:

- varied natural references resolve to `PROJECT-AURORA`;
- each contextual resolution has supporting spans;
- the unrelated decoy is excluded;
- the model cannot assign every source to the sole known project;
- resolved `EvidenceSet` ordering remains deterministic.

The Aurora semantic-resolution profile MUST include at least one genuinely cross-document case in which the source utterance alone is insufficient, at least one supporting span belongs to a different evidence record, and a valid `ResolutionContextRecord` relationship connects the source to that supporting evidence. Removing either the relationship or the external supporting evidence MUST cause the test-only semantic profile to expect `unresolved` or `ambiguous`, not `contextually_resolved`.

The required short-approval case is:

- Parent source: “Move the production to Northlight Studio.”
- Reply source: “Approved.”
- The reply source MUST cite its own “Approved.” reference span and the parent decision span in `supporting_span_ids`.
- The reply source MUST use `parent_reply_context`, and its `ResolutionContextRecord.parent_evidence_id` MUST identify the parent source.

The expected Aurora project mapping for this case MUST remain test-only. It MUST NOT be encoded in the production validator or production prompt.

The decoy MUST have sufficient source text to ground the `unrelated` result; its unrelated status MUST NOT be inferred only from a filename or folder.

### 18.2 Test-only LynxMask profile

The separate LynxMask profile is limited to:

- `PROJECT-LYNXMASK`;
- `PRODUCT-LYNXMASK-MOBILE`;
- `PRODUCT-LYNXMASK-DESKTOP`;
- one contextually resolved Mobile case;
- one ambiguous family-name case;
- no automatic both;
- no `global` status without explicit all-versions language;
- no UI or production workflow.

The contextual Mobile case MUST cite the actual Android, CameraX, three-tap, or equivalent bounded platform/workflow spans used for the mapping. The ambiguous family-name case MUST return both plausible candidates and no resolved target.

The implementation MUST test ID opacity by remapping Mobile and Desktop to identifiers that contain no semantic words while preserving their registry `canonical_name`, `object_type`, project ownership, and source evidence. The remapped request MUST produce the same semantic result after IDs are mapped back for comparison.

### 18.3 Contract-level falsification cases

Tests MUST prove all of the following:

- opaque-ID remapping produces the same semantic result;
- removing registry object metadata makes the Decision Scope request invalid;
- omitting one `decision_evidence_ids` result rejects the entire scope result;
- adding a scope result for an evidence ID outside `decision_evidence_ids` rejects the entire scope result;
- `decision_span_ids` outside `supporting_span_ids` reject the entire result;
- `reference_span_ids` outside `supporting_span_ids` reject the entire result;
- an `explicit_global_language` reason code without structurally linked decision and supporting spans rejects the entire result;
- a semantically wrong but structurally valid `global` output can pass the universal validator but MUST fail the test-only semantic profile;
- a confirmation whose `workspace_id` differs from the candidate workspace is rejected;
- target IDs owned by another project are rejected;
- `parent_reply_context` without a parent evidence record represented by a supporting span rejects the entire result;
- `same_thread_context` without a shared non-null `thread_subject` between the source and a relationship supporting evidence record rejects the entire result;
- `shared_participants` without a non-empty participant intersection between the source and a relationship supporting evidence record rejects the entire result;
- `cross_document_sequence` without external supporting evidence and a qualifying adjacency, parent, or attachment relationship rejects the entire result.

## 19. Default test network rule

All default and acceptance tests MUST be network-isolated.

Fake or injected deterministic providers MUST be explicit.

No test may silently fall back from OpenAI to a fake provider.

Tests MUST fail closed if configuration selects OpenAI without a deliberately injected fake client or explicitly authorized live-test boundary.

## 20. Live evaluation contract

Exactly one controlled live evaluation sequence is authorized after contract acceptance and implementation of the bounded package:

```text
Pass A:
semantic project resolution for the Aurora candidate workspace

Backend validation

Resolution gate

Resolved EvidenceSet

Pass B:
existing continuity analysis

Backend validation

Backend-owned citation hydration
```

The live run MUST prove:

- varied natural Aurora references resolve correctly;
- supporting span IDs are valid;
- the decoy is not included;
- no invented IDs appear;
- continuity analysis receives only resolved evidence;
- the approved location change remains a `propagation_break`;
- next action remains human-owned.

Before the run, the exact API model ID MUST be verified. The model ID MUST NOT be guessed from the ChatGPT UI name.

The API key, paths, prompts containing secrets, and raw provider errors MUST NOT enter the repository, screenshots, or film.

One live run MAY contain one semantic-resolution API call and one continuity-analysis API call. Cost and latency MUST be recorded.

Failure MUST NOT cause validator bypass, schema weakening, or fake fallback. A failed call or invalid result MUST stop the sequence and be recorded as a failed live attempt without exposing confidential content.

## 21. Public claim boundary

Before a successful live run, public wording MUST remain:

> Continuity AI currently analyzes a user-selected, already grouped project workspace.

After a successful validated live run, permitted demo-bounded wording MAY become:

> In the demonstrated Project Aurora candidate workspace, Continuity AI resolved naturally varied project references, excluded an unrelated source, and then identified the continuity break.

A broader product-positioning sentence MAY be used only when clearly qualified as the intended capability, not as proof of general reliability.

One synthetic controlled run MUST NOT be described as validation across arbitrary projects, organizations, or document types.

Neither wording authorizes claims of autonomous project discovery. No UI, film, submission, or PR description may imply automatic computer-wide discovery or a universal resolver.

## 22. Stop rules

Implementation MUST stop and the deviation MUST be reported when:

- G-02 `EvidenceRecord` is changed;
- model-created project or target IDs are allowed;
- all workspace sources default to the sole known project;
- folder or filename becomes decisive evidence;
- known alias matching becomes the only mechanism;
- absence of a known alias excludes contextual resolution;
- ambiguity becomes automatic assignment;
- family naming becomes global scope;
- numeric confidence replaces source grounding;
- supporting spans become optional;
- human resolution confirmation becomes project fact evidence;
- continuity analysis runs before resolution gating;
- production prompt or validator contains expected Aurora answers;
- tests omit a decoy or ambiguity case;
- default tests call the network;
- live failure falls back to fake;
- UI or film claims semantic resolution before a validated live run.

No implementation team may reinterpret a stop condition as permission to weaken the contract. Contract changes require a separate reviewed documentation correction.

## 23. Exact bounded implementation package after acceptance

Only after this contract is independently falsified and accepted, one implementation package MAY include only:

- canonical registry models for the thin slice;
- `ResolutionContextRecord`;
- Semantic Project Resolution request builder and provider adapter;
- Decision Scope Resolution request builder and provider adapter;
- strict Semantic Project Resolution result schema and validator;
- strict Decision Scope Resolution result schema and validator;
- resolved `EvidenceSet` composition;
- dedicated Aurora resolution fixture;
- test-only LynxMask scope fixture;
- network-isolated tests;
- one controlled live runner.

The controlled live runner is authorized only for the Aurora Semantic Project Resolution path followed by the existing continuity-analysis Pass B. LynxMask Decision Scope remains test-only. No LynxMask live API run, UI integration, or production workflow is authorized.

That package MUST NOT include:

- universal discovery;
- knowledge graph infrastructure;
- persistent alias learning;
- arbitrary project counts;
- full resolution persistence;
- full confirmation UI;
- production-grade resolver;
- LynxMask integration;
- unrelated conversation or persistence repairs.

Do not write implementation code in this contract package.
