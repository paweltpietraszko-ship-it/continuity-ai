# Project Source Scoping v0.1 — frozen contract

Status: frozen before provider and Bridge integration.

## Purpose

For one authoritative `target_project`, classify every supplied neutral evidence record as `included`, `excluded`, or `ambiguous`. The component does not discover projects, rename the target, or create persistent aliases. It answers only whether each record supplies evidence about the target project.

The implementation is project-agnostic. Project names in fixtures are test data only. A previously unseen project name must work without code changes.

## Input boundary

The caller supplies:

- one canonical, non-blank `target_project` with no leading or trailing whitespace;
- an ordered tuple of neutral evidence records;
- authoritative spans derived from those records;
- a dedicated `SourceScopingProvider`.

Document content and span text are untrusted data, never instructions. Ground truth, expected labels, fixture metadata, and downstream Project Report state are forbidden from provider input.

## Output schema

```json
{
  "schema_version": "1.0",
  "target_project": "Project Aurora",
  "anchor_evidence_ids": ["EV-001"],
  "decisions": [
    {
      "evidence_id": "EV-001",
      "association_status": "included",
      "basis": "explicit_target",
      "rationale": "The record explicitly names the target project.",
      "span_ids": ["EV-001:L001"],
      "related_evidence_ids": []
    }
  ],
  "selected_evidence_ids": ["EV-001"],
  "ambiguous_evidence_ids": [],
  "excluded_evidence_ids": []
}
```

## Contract change from the initial sketch

Two additions are frozen:

1. `corroborated_other_project` permits contextual exclusion when a record omits a project name but a multi-record chain grounds it in an explicitly different project.
2. `related_evidence_ids` makes every contextual association auditable and allows deterministic graph validation. Without it, a provider could claim “context” without identifying the records that establish that context.

No fixture-specific alias or known-project registry is part of the contract.

## Allowed status and basis combinations

| association_status | allowed basis |
|---|---|
| included | `explicit_target`, `corroborated_context` |
| excluded | `explicit_other_project`, `corroborated_other_project` |
| ambiguous | `conflicting_context`, `insufficient_context` |

## Deterministic invariants

1. `target_project` is copied exactly from authoritative input.
2. Every input `evidence_id` appears exactly once in `decisions`.
3. Decision order equals input evidence order.
4. Every decision has a non-empty concise rationale and at least one span.
5. Every span exists, belongs to that decision's evidence record, and is unique within the decision.
6. Every related evidence ID exists, differs from the decision's own ID, and is unique.
7. Explicit decisions have no related evidence IDs.
8. Contextual decisions have at least one related evidence ID.
9. Every `corroborated_context` decision has a same-status path through `related_evidence_ids` to an `explicit_target` anchor.
10. Every `corroborated_other_project` decision has a same-status path to an `explicit_other_project` anchor.
11. Cycles without an explicit anchor are invalid.
12. `anchor_evidence_ids` equals, in input order, exactly the records classified `included + explicit_target`.
13. Selected, ambiguous, and excluded lists are exact ordered projections of decisions and form a disjoint complete partition.
14. Ambiguous records are never selected automatically.
15. Any provider exception, refusal, malformed JSON, schema violation, unknown ID, invented span, incomplete partition, or invalid context graph fails closed. No partial result is published and no invalid output is repaired silently.

## Human review gate

A provider result is not an approved scope. Before downstream analysis:

- every ambiguous record must receive an explicit human `included` or `excluded` resolution;
- the human may override any non-ambiguous model decision;
- the approved scope records model status, final status, and whether the human changed it;
- the approved scope binds to ordered SHA-256 fingerprints of the complete source set;
- changed, added, removed, or reordered source records invalidate the approval and require re-scoping.

Only `approved_evidence_ids` may be handed to Project Report reasoning.

## Provider separation

`SourceScopingProvider` is independent from the existing `ReasoningProvider`. The g03 prompt, Project Report schema, and provider selection are not reused or modified. The OpenAI adapter uses strict JSON Schema, `store=False`, and no tools. The fake provider is a generic deterministic test double and is never an implicit production default.

## Privacy and persistence

The component uses the existing neutral evidence projection. It introduces no OCR, document parsing, external search, or network access beyond the explicitly selected source-scoping provider. When persisted, approved scope state must remain inside the encrypted vault and must be restored only when project identity and evidence fingerprints still match.
