# Scope and Ground Truth

## Product Definition and Promise

Continuity AI reconstructs the current state of a project from scattered work artifacts, detects where those artifacts contradict each other, and tells the user what requires attention next, with evidence for every material claim.

Core promise: Never lose the story behind your project.

Continuity AI is an evidence-grounded continuity layer, not another project manager.

## Frozen MVP

The frozen MVP is: one local owner, one project, one verified artifact set, one initial morning question, one meaningful Continuity Break, one evidence-grounded next action, and a continuing conversation with the Continuity AI agent.

Included:
- One authenticated local owner.
- One case: Project Aurora.
- One deterministic synthetic project world.
- Multiple local artifact formats.
- One grounded project brief.
- One meaningful Continuity Break.
- Openable evidence.
- One recommended next action.
- Persistent natural conversation with the Continuity AI agent after the initial analysis.
- Project-grounded conversational replies linked to evidence; general conversation does not require Project Aurora citations.
- Authenticated User Attestations added by the owner as evidence, with actor identity, timestamp, channel, provenance, and stable evidence ID.
- Corrections through superseding evidence records rather than silent overwrite.
- One encrypted local vault for application-stored project-derived data, conversation history, and user attestations.
- An append-only evidence log and no anonymous write path.
- Explicit disclosure that selected evidence is sent to the configured OpenAI API for semantic analysis.
- Text entry for user attestations. Voice capture and transcription are not required for MVP.
- Tests.
- README.
- Implementation evidence for Codex and GPT-5.6.

Excluded:
- Live Gmail, Notion, Drive, or Frame.io integrations.
- OAuth.
- Multiple projects or users.
- Organization memory.
- LynxMask integration.
- Voice capture, speech-to-text, or raw-audio storage.
- Biometric unlock.
- Team roles or organization authorization.
- Managed cloud service and centrally funded model usage.
- Folder monitoring.
- Autonomous orchestration.
- Multi-model triangulation.
- A general synthetic company generator.
- Automatic editing of source documents, calendars, call sheets, or messages.
- Any feature that does not strengthen the Project Aurora demo or the accepted evidence, conversation, and local-security boundary.

## Evidence Authority and Provenance

The authenticated local owner has authority to add information directly to the project record as an Authenticated User Attestation. Continuity AI does not challenge the owner's authority to add that evidence.

The system must preserve provenance so that artifact evidence and owner attestations remain distinguishable. An attestation records the exact statement, actor identity, timestamp, channel, and evidence ID.

A correction does not silently replace an earlier attestation. It creates a later evidence record that explicitly supersedes the earlier record.

## Conversation Boundary

The user may converse naturally with Continuity AI, including discussion unrelated to Project Aurora.

The product constrains authority, not conversational topics:
- Project-state claims must be grounded in project evidence or clearly identified user-provided assumptions.
- General conversation does not require project citations.
- Current external information requires an implemented external-data tool or an honest statement that the data is unavailable.
- Conversation alone does not modify project evidence unless the authenticated owner explicitly instructs the system to add an attestation.
- No source document is modified and no external action is performed without an explicit implemented control.

## Local Security Boundary

The MVP security boundary is intentionally narrow:
- one local owner;
- one unlockable local vault;
- encryption at rest for data stored by Continuity AI;
- no anonymous write path;
- append-only evidence history;
- no confidential document or conversation content in ordinary technical logs.

Original source files remain in locations selected and controlled by the user. Continuity AI is responsible for protecting data it stores itself.

The security contract must describe limitations honestly. Local encryption does not protect an already unlocked process from malware, an operating-system administrator, screen capture, or deliberate export by the owner.

## External Model Boundary

GPT-5.6 is accessed through the OpenAI API, not through a ChatGPT desktop or Plus subscription.

The MVP uses a developer API key held outside source control. The product must state clearly that application-stored project data is encrypted locally, while selected evidence is sent to the configured OpenAI API for semantic analysis.

## Project Aurora Ground Truth

This ground truth may be used by tests but must never be read by the production reasoning pipeline to manufacture the answer.

1. The production team considers moving the shoot from Harbor House to Northlight Studio.
2. The investor formally approves the move by email.
3. Budget v4 includes the Northlight Studio costs.
4. The production calendar still lists Harbor House.
5. The latest call sheet still lists Harbor House.
6. The crew briefing is scheduled for the following day.

Expected Continuity Break:

The approved location change is reflected in the budget but not in the production calendar or current call sheet.

Required evidence:
- Investor approval email.
- Budget v4.
- Production calendar event.
- Current call sheet.

Expected next action:

Update the production calendar and call sheet before tomorrow's crew briefing.

## Gate G-01 Acceptance Criteria

Gate G-01 creates a deterministic Project Aurora fixture generator.

Acceptance criteria:
- Python 3.12 or newer is used.
- uv is used for project and test commands.
- The repository uses a src layout.
- Production code uses full type annotations.
- pytest is configured.
- The architecture is clean and modular.
- No production AI call exists yet.
- One documented command creates production scenario artifacts into fixtures/project_aurora/generated/artifacts/ and test-only ground truth into fixtures/project_aurora/generated/test_only/.
- Required production artifact formats are generated into fixtures/project_aurora/generated/artifacts/: EML investor approval email, ICS production calendar, XLSX budget v4, PDF current call sheet, and Markdown crew briefing or project note. JSON ground truth is generated only into fixtures/project_aurora/generated/test_only/.
- Every artifact has a stable source ID, author, timestamp, source type, timeline position, business purpose, and openable repository-relative path or URI.
- Fixture definitions are fixed.
- Output is deterministic and generated artifact outputs are intentionally not committed to Git.
- Evidence IDs are stable.
- Checksums are stable where practical.
- Business content is not random.
- Production modules do not depend on `ground_truth.json`, do not receive the test_only directory, and the production artifact input directory contains no ground_truth.json file.
- Tests verify required artifacts, required source IDs, parseability with real parsers, two independent byte-identical generations, ground truth contents, and production independence from `ground_truth.json`.
- A separate final-product acceptance test exists and fails because the reasoning pipeline does not exist yet.
- The acceptance test is not marked xfail or skip.
- The acceptance test does not pass through placeholder production output, mocks, or copied expected output.
- Fixture tests pass.
- The final product acceptance test fails for the correct reason.

## Competition Submission Obligations

The implementation evidence must support a competition submission by preserving:
- What was built.
- How it satisfies the frozen MVP.
- Which tests were executed.
- Which failures are known.
- Why the demo is evidence grounded.
- How Codex and GPT-5.6 contributed to implementation.
- The final `/feedback` Session ID when available.

## Pitch and Roadmap

Pitch:
- People do not lose files; they lose orientation.
- Continuity AI rebuilds project orientation from scattered evidence.
- Continuity AI finds where a project no longer agrees with itself.
- Project Aurora demonstrates a real continuity break: an approved production location change appears in some artifacts but not in operational documents.
- Continuity AI builds Continuity AI by keeping project memory in the repository.
- The user can discuss, challenge, and refine the interpretation without surrendering traceability to evidence.
- Authenticated owner attestations allow real-world information that exists outside documents to enter the project record with provenance.

Roadmap after MVP:
- LynxMask as a local privacy gateway before external model processing, with the insertion point chosen only after a post-MVP pipeline audit.
- Voice-originated attestations and local transcription; raw audio is not stored by default.
- Bring-your-own-key configuration for user-managed OpenAI API access.
- A managed service only after a separate backend, billing, retention, and security review.
- Biometric unlock, multi-user roles, team authorization, secure export policy, organization-controlled retention, and enterprise key management.
- Semantic Contract: a repository-level agreement about the meaning of operational terms such as done, verified, current, and decision.
- Interpretation Break: detection of cases where collaborators use the same word or artifact to mean different things.
- Live integrations may be considered only after the MVP proves the Project Aurora continuity workflow.

## Operational Semantic Contract

- done: Implemented, tested, documented, and committed.
- verified: Actually executed or inspected with evidence, not inferred from source code.
- gate passed: Every acceptance criterion is satisfied.
- current: Confirmed at the explicitly named commit.
- decision: Approved by the human decision owner, not merely proposed by a model.
- failure: A known failing state recorded explicitly, not hidden by xfail, mocks, skipped tests, or wording.
