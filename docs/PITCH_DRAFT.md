# Pitch Draft

People do not lose files; they lose orientation.

Continuity AI is a continuity layer, not another project manager. It reconstructs the current state of a project from scattered artifacts and shows where the project no longer agrees with itself.

The memorable differentiation is contradiction detection with evidence. Continuity AI does not merely summarize a project; it identifies the continuity break that needs attention next.

Project Aurora is the demonstration metaphor. The production move to Northlight Studio has been approved and budgeted, but the operating artifacts still point the crew to Harbor House. The story exists in the evidence, but the project has lost alignment.

Continuity AI builds Continuity AI. The product's own repository keeps the implementation story, current state, scope, build log, and pitch draft so the team does not lose orientation while building under pressure.

## Frozen MVP

The MVP proves one project, one verified artifact set, one morning question, one continuity break, one evidence-grounded next action, and one continuing conversation with the Continuity AI agent.

The agent is not a restricted challenge form. The user may discuss the analysis, question it, ask for clarification, change topics, or continue a general conversation. Project claims remain governed by verified evidence; general conversation does not need Project Aurora citations.

An authenticated local owner may add information directly to the project record as an `Authenticated User Attestation`. Continuity AI records the exact statement, actor identity, time, channel, and evidence ID. Corrections supersede earlier attestations rather than silently overwriting history.

The MVP security boundary is intentionally narrow: one local owner, one encrypted local vault, an append-only evidence log, encrypted storage for project-derived content and conversations, and no anonymous write path. Original source files remain under the user's control. Continuity AI is responsible for protecting the data it stores.

GPT-5.6 is accessed through the OpenAI API, not through a ChatGPT desktop subscription. The MVP uses a developer API key. A future product may support bring-your-own-key configuration.

The MVP must state the external-processing boundary honestly: stored project data is encrypted locally, while selected evidence is sent to the configured OpenAI API for semantic analysis.

## Roadmap After MVP

### Local Privacy Gateway with LynxMask

Continuity AI is designed for a future local privacy gateway powered by LynxMask. Sensitive evidence, user attestations, conversation history, and user questions can be pseudonymized before external model processing while stable `evidence_id` and `span_id` references preserve traceability. Depseudonymization remains local.

The exact insertion point is deliberately not frozen before MVP. Candidate boundaries include normalized `EvidenceRecord.content`, deterministic evidence spans, or the final outbound model request. The decision will follow a post-MVP privacy and pipeline audit.

### Voice Attestations

The evidence model is prepared for future voice-originated attestations, but the MVP does not claim working voice capture or transcription. Raw audio is not stored by default. The authenticated statement transcript is the project evidence record.

### Managed and Bring-Your-Own-Key Deployment

The local application may later support user-managed OpenAI API keys. A managed service with centrally funded model usage would require a separate backend, billing controls, retention policy, and expanded security review.

### Extended Security

Future security work may add biometric unlock, multi-user roles, team authorization, secure export policy, organization-controlled retention, and enterprise key management. These are pitch roadmap items, not current MVP capabilities.

### Semantic Contract and Interpretation Break

Semantic Contract and Interpretation Break remain roadmap concepts beyond the Project Aurora proof. The MVP first establishes that a verified evidence set can be reconstructed, interpreted, discussed with the user, and converted into one grounded recovery action without autonomous execution.

## Product Boundary

Continuity AI may recommend and explain. It does not silently edit source documents, update calendars, send messages, or claim that a recommended action has been completed.

The long-term product principle is freedom of conversation with constrained authority: the owner may talk to the agent naturally and may add authenticated evidence, while every project-state claim preserves its provenance and every external action requires an explicit, implemented control.
