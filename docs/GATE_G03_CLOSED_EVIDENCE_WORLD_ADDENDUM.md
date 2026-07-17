# Gate G-03 Closed Evidence World Addendum

Status: normative amendment to `GATE_G03_CONTRACT_v0.2.md` before falsification and implementation

## 1. Product terminology

The Project Aurora failure is an `operational contradiction`: the organization is maintaining two incompatible versions of operational reality.

`Document drift` and `state drift` may be used as explanatory terms. Product narration and film copy must not call this a hallucination, because that term suggests a model-generation error rather than divergence among real project artifacts.

## 2. Closed evidence world invariant

Every project-grounded result exists inside the current verified `EvidenceSet`.

The model may reference only:

- `evidence_id` values present in the current `EvidenceSet`;
- `span_id` values deterministically generated from those evidence records;
- authenticated user attestations already committed through G-SEC-01.

The model must not create or supply authoritative source metadata. In particular, it is not the source of truth for:

- document titles;
- authors or actors;
- timestamps;
- source types;
- evidence IDs;
- span text;
- displayed quotations;
- file paths or URIs.

Those values are resolved by deterministic backend code from the current canonical evidence collection.

## 3. Analysis output

Initial analysis continues to use `span_ids` for grounded statements rather than model-copied quotations.

Semantic annotations may contain an `evidence_id`, but every such identifier must resolve to exactly one record in the current `EvidenceSet`.

Unknown evidence IDs, unknown span IDs, cross-record-invalid span IDs, or references to sources absent from the current request invalidate the complete semantic result.

The backend derives the supporting evidence-ID set from validated span IDs where a statement does not otherwise require an explicit evidence-ID field.

## 4. Backend-owned citation rendering

The UI must never render a citation card from model-generated source metadata.

For every validated `span_id`, the backend supplies:

- canonical `evidence_id`;
- exact span text;
- canonical title;
- canonical author or actor;
- canonical timestamp;
- canonical source type;
- canonical provenance.

The model-generated message may explain an interpretation, but it does not establish source identity. Visible evidence metadata always comes from the backend-owned record.

## 5. Project-grounded conversation

A conversational response is `project_grounded` only when every cited span resolves inside the current `EvidenceSet`.

A valid span reference proves source existence and quotation provenance. It does not deterministically prove that the model interpreted the source correctly.

When the user asks about a document or source that does not exist in the verified evidence set, the agent must not speculate about its possible contents. The response kind is `insufficient_evidence` and the preferred user-facing message is:

```text
No matching source exists in the verified Project Aurora evidence set.
```

The project remains open to ordinary general conversation. This closed-world rule applies only to claims about project state, project evidence, and source provenance.

## 6. Fail-closed conditions

The complete analysis or conversational project-grounded turn is rejected when:

- any referenced evidence ID is unknown;
- any referenced span ID is unknown;
- a span is attributed to a different evidence record than its canonical parent;
- a project-grounded answer contains no valid supporting span;
- a source card cannot be hydrated entirely from canonical backend data;
- a model attempts to introduce a source as evidence without a valid identifier;
- a proposed analysis revision fails the same closed-world checks.

The neutral evidence timeline remains visible after rejection. The invalid semantic output is not partially displayed.

## 7. Required negative tests

G-03 tests must include:

1. fabricated `evidence_id` in an initial analysis;
2. fabricated `span_id` using a valid evidence-ID prefix;
3. valid span ID attributed to the wrong evidence record;
4. project-grounded chat turn with no spans;
5. project-grounded chat turn containing an unknown span;
6. user asks about a nonexistent Project Aurora document and receives `insufficient_evidence` without speculative contents;
7. citation display metadata is hydrated from canonical evidence even when a fake provider supplies conflicting author, title, or quotation fields;
8. strict schemas reject model-provided source metadata fields that are not part of the contract;
9. one invalid source reference rejects the entire semantic result rather than only the affected claim;
10. authenticated user attestation becomes referenceable only after confirmation and commit through G-SEC-01.

## 8. Residual semantic risk

The closed evidence world prevents a fabricated document, author, evidence ID, or quotation from being presented as verified evidence.

It does not eliminate semantic interpretation errors. GPT-5.6 may still misunderstand a real source or select a real but irrelevant span. Those failures remain inspectable because the user can open the canonical evidence behind every project-grounded claim.
