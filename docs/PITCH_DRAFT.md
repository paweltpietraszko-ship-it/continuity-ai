# Pitch Draft

People do not lose files; they lose orientation.

## Product Idea — Less Project Bureaucracy

Continuity AI reduces the administrative work required to keep a project coherent. In the intended product, records arriving from work sources authorized by the user—such as email, documents, calendars, and versions—are analyzed together and assigned to the relevant project, decision trail, and operational context. Continuity AI maintains an evidence-backed view of current state and identifies where sources still reflect an older decision or where the decision trail itself breaks.

The owner should not have to manually assemble project history, repeatedly identify which project each record belongs to, remember where a decision was recorded, compare work sources by hand, or maintain another administrative system solely for the AI. Ambiguity stops automatic assignment and requires human confirmation. The system does not invent decisions or take autonomous corrective action; the owner intervenes only where judgment, confirmation, or action is required.

Continuity AI is a continuity layer, not another project manager.

## What the Competition MVP Demonstrates

The competition MVP does not yet continuously ingest connected sources or provide production-grade automatic project discovery. The current competition implementation begins with a user-selected, already grouped candidate project workspace. This is a deliberate demonstration boundary, not the intended final user workflow.

Project Aurora is the proof case for the reasoning core required by the broader product. The frozen bounded slice is planned to recognize that naturally varied references concern Aurora, exclude or block unrelated and ambiguous evidence, connect records to a decision trail, reconstruct current project state, detect an evidence-backed continuity break, and identify what requires human attention next. Semantic Project Resolution and Decision Scope Resolution are contractually frozen but not yet implemented.

The hardest problem is not fetching another email or file. It is determining where information belongs and how it changes project state. Connectors and continuous intake are deferred transport and operational layers around that cognitive core.

Continuity AI does not merely summarize a project. It detects an evidence-backed continuity break and shows what requires attention next.

Project Aurora is the demonstration metaphor. The production move to Northlight Studio has been approved and budgeted, but the operating artifacts still point the crew to Harbor House. The story exists in the evidence, but the project has lost alignment.

## What Did Not Fit

Continuous source intake, production connectors, automatic discovery across arbitrary projects, persistent assignment management, and broader reliability evaluation remain outside the competition implementation. These are not unrelated roadmap features. They are the unfinished operational layer that would turn the demonstrated reasoning core into the full low-bureaucracy product.

Continuity AI builds Continuity AI. The product's own repository keeps the implementation story, current state, scope, build log, and pitch draft so the team does not lose orientation while building under pressure.

The authoritative MVP definition belongs in `docs/SCOPE_AND_GROUND_TRUTH.md`. This file keeps pitch language and post-MVP product direction; it is not the implementation contract.

## Deliberate MVP Shortcuts and Known Risks

| Deliberate shortcut | Risk we recognize | MVP control | Deferred beyond MVP |
|---|---|---|---|
| The competition MVP begins with a user-selected, already grouped candidate workspace. | The demonstrated workflow still requires manual preparation that the intended product is designed to remove. | The pitch clearly distinguishes the demonstrated reasoning core from production-grade automatic intake and assignment. | Continuous intake from authorized sources, automatic project assignment, and arbitrary multi-project discovery. |
| The frozen competition scope limits the planned Semantic Project Resolution implementation to one Project Aurora candidate workspace with varied natural references and one unrelated decoy. | A successful Aurora result would not prove universal alias or entity resolution. | Backend-owned candidate IDs, deterministic spans, strict validation, a contract requirement that ambiguity blocks automatic assignment, and a demo-bounded public claim. | A production-grade resolver across arbitrary projects, organizations, and document types. |
| The frozen competition scope limits the planned Decision Scope Resolution implementation to a small test-only LynxMask Mobile/Desktop fixture. | The competition build would not prove production integration with LynxMask or arbitrary product families. | The contract requires opaque-ID tests, candidate ownership validation, and no automatic family-to-global inference. | LynxMask workflow integration, persistent scope records, and generalized product-family support. |
| The frozen design requires the backend to validate schemas, IDs, spans, ownership, ordering, and relationship prerequisites, but deterministic validation cannot prove that the model’s semantic interpretation is correct. | A structurally valid model result may still be semantically wrong. | Test-only semantic profiles, unrelated and ambiguity cases, a planned controlled live run, and human-owned next actions. | Broader evaluation sets, monitoring, and production reliability evidence. |
| The frozen contract requires ambiguous project or decision-scope resolution to stop the flow; full persistent management of resolution confirmations is not implemented in the competition slice. | Some real workspaces require manual disambiguation before analysis can continue. | The contract forbids automatic assignment under ambiguity and forbids a generic “yes” from acting as confirmation. | Persistent confirmation history, editing, supersession, and complete management UI. |
| The branch currently demonstrates only part of the accepted vertical skeleton. | Retained analyses, encrypted snapshot restoration, historical citation fidelity, conversation grounding, and final end-to-end coverage are not yet complete. | These are tracked as explicit blockers; PR #9 remains not merge-ready and Gate G-03 remains open. | Only items explicitly excluded by the MVP contract; accepted blockers must be repaired before gate closure. |
| The competition plan permits one controlled Project Aurora semantic-resolution call followed by one continuity-analysis call. | One successful synthetic run would not establish general reliability. | The planned run records cost and latency; invalid output or provider failure must stop it; no fake fallback is allowed. | Repeated evaluation across broader real-world workspaces and operational monitoring. |

These limitations are deliberate boundaries, not hidden omissions. They keep the competition implementation testable and honest while preserving its core differentiation: evidence-backed continuity-break detection. The submission will distinguish demonstrated capability from intended product direction.

## Post-MVP Direction

### Automatic Workstream Intake and Assignment

The intended product connects only to work sources authorized by the user and processes new records as they arrive. It assigns each record to the relevant project and decision trail, preserves its operational context, or places it in an ambiguity queue. Validated evidence and backend-owned identities preserve traceability; ambiguous records wait for owner confirmation instead of being silently assigned. The owner should intervene only when judgment or action is required. This is the operational layer that removes the MVP's manual workspace-preparation burden.

### Local Privacy Gateway with LynxMask

Continuity AI is designed for a future local privacy gateway powered by LynxMask. Sensitive evidence, user attestations, conversation history, and user questions can be pseudonymized before external model processing while stable `evidence_id` and `span_id` references preserve traceability. Depseudonymization remains local.

The exact insertion point is deliberately not frozen before MVP. Candidate boundaries include normalized `EvidenceRecord.content`, deterministic evidence spans, or the final outbound model request. The decision follows a post-MVP privacy and pipeline audit.

### Voice Attestations

Future voice capture and local transcription can turn an authenticated owner's spoken statement into a provenance-marked evidence record. Raw audio is not stored by default.

### Deployment Options

A later local product may support bring-your-own-key OpenAI API configuration. A managed service with centrally funded model usage requires a separate backend, billing controls, retention policy, and expanded security review.

### Extended Security

Future security work may add biometric unlock, multi-user roles, team authorization, secure export policy, organization-controlled retention, and enterprise key management.

### Broader Continuity Reasoning

Semantic Contract and Interpretation Break remain roadmap concepts beyond the Project Aurora proof. Semantic Contract captures shared operational meaning for terms such as done, verified, current, and decision. Interpretation Break identifies cases where collaborators use the same word or artifact to mean different things.
