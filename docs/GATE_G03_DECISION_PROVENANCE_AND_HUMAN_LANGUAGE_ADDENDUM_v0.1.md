# Gate G-03 Decision Provenance and Human-Language Addendum v0.1

Status: normative implementation-blocking correction
Applies to: `GATE_G03_CONTRACT_v0.2.md`, `GATE_G03_CLOSED_EVIDENCE_WORLD_ADDENDUM.md`, `FABLE5_CONTRACT_CORRECTIONS_v0.1.md`, and the vertical-skeleton implementation branch.
Precedence: where this document conflicts with earlier G-03 candidate text, this document wins.

## 1. Continuity Break kinds

A `break_found` analysis must include a required `continuity_break_kind` discriminator. A `no_material_break_found` analysis must set `continuity_break_kind` to null.

Supported break kinds are:

- `propagation_break`;
- `decision_provenance_not_found`.

### propagation_break

Use `propagation_break` when an approved decision exists but has not reached all relevant project artifacts.

Deterministic validation requires:

- at least one `approved_decision` annotation;
- at least one `conflicts_with_decision` annotation;
- a non-null grounded continuity-break statement;
- a non-null grounded next action.

Project Aurora remains a `propagation_break` scenario.

### decision_provenance_not_found

Use `decision_provenance_not_found` when available project evidence shows a material project-state change, but no approval, decision, rationale, or linked note explaining that change was found in the current verified project sources.

Continuity AI may say only that it could not find a decision in the sources currently available to Continuity AI. It must not claim that no decision exists.

Deterministic validation requires:

- zero `approved_decision` annotations;
- a grounded continuity-break statement;
- cited spans from at least two distinct evidence records representing earlier and later states;
- a non-null grounded next action.

The validator proves only structure and grounding. It does not prove that the change is genuinely material or that a decision does not exist outside the supplied evidence.

G-02 remains unchanged. G-02 only ingests and normalizes artifacts. Material-change interpretation and decision-provenance assessment belong to G-03.

## 2. Prompt rule for material changes

The reasoning prompt must instruct the model to consider changes to functionality, scope, budget, timing, location, responsibility, or an accepted project direction.

Mechanical changes such as export dates, version counters, or formatting must not by themselves create a Continuity Break.

## 3. Human-language contract

Internal enum values and controlled error codes may remain technical. User-visible titles, messages, findings, actions, and bridge error messages must use ordinary human language.

The UI must not expose internal phrases such as `EvidenceSet`, `insufficient_evidence`, `decision_provenance_not_found`, raw exception class names, `object_id`, or traceback content.

Language principle: describe what Continuity AI found or could not find. Do not narrate the internal mechanism.

Canonical wording for a change without found provenance:

Title: `Change with no decision found`

Message pattern: `The [item] changed from [earlier value] to [later value]. We couldn’t find an approval, decision, or note for this change in the project sources currently available to Continuity AI.`

Next action pattern: `Add or link the decision that approved this change before treating the new value as current.`

Canonical fixed messages:

- Missing project document: `I couldn’t find that document in the project sources currently available to Continuity AI.`
- Locked vault: `Unlock the project vault to continue.`
- Current external information unavailable: `I can’t check current external information because web access is not available in this version.`
- Safe generic failure: `Continuity AI couldn’t complete this request safely. Nothing was changed.`

Do not replace every specific controlled error with the generic failure. Use the most useful safe human message available.
