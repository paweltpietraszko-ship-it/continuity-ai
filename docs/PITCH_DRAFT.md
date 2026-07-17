# Pitch Draft

People do not lose files; they lose orientation.

Continuity AI is a continuity layer, not another project manager. It reconstructs the current state of a project from scattered artifacts and shows where the project no longer agrees with itself.

The memorable differentiation is contradiction detection with evidence. Continuity AI does not merely summarize a project; it identifies the continuity break that needs attention next.

Project Aurora is the demonstration metaphor. The production move to Northlight Studio has been approved and budgeted, but the operating artifacts still point the crew to Harbor House. The story exists in the evidence, but the project has lost alignment.

Continuity AI builds Continuity AI. The product's own repository keeps the implementation story, current state, scope, build log, and pitch draft so the team does not lose orientation while building under pressure.

The authoritative MVP definition belongs in `docs/SCOPE_AND_GROUND_TRUTH.md`. This file keeps pitch language and post-MVP product direction; it is not the implementation contract.

## Post-MVP Direction

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
