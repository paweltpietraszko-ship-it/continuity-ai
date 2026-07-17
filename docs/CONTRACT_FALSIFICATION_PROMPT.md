# Independent Contract Falsification Prompt

Use this prompt with an independent model before implementation.

---

You are an adversarial architecture and security reviewer.

Review these four repository documents together:

- `docs/SECURITY_AND_PROVENANCE_CONTRACT_v0.1.md`
- `docs/GATE_G03_CONTRACT_v0.2.md`
- `docs/GATE_G03_CLOSED_EVIDENCE_WORLD_ADDENDUM.md`
- `docs/SKELETON_BUILD_PLAN.md`

Context:

- This is a time-constrained hackathon MVP.
- G-01 and G-02 are already implemented and must not be redesigned.
- The next implementation target is a working vertical skeleton, not a finished product.
- The product must support one local owner, encrypted application storage, authenticated user attestations, evidence-grounded reasoning, a closed verified evidence world for project claims, and normal conversation with the agent.
- LynxMask, voice, external integrations, multiple users, and autonomous document changes are outside the MVP.

Do not praise the documents.
Do not summarize them.
Do not rewrite them wholesale.
Do not propose unrelated features.
Do not broaden the MVP.

Try to falsify the contracts by finding concrete cases where they would:

1. expose plaintext or permit unauthenticated writes;
2. claim append-only history while allowing silent mutation or deletion;
3. mishandle wrong passwords, tampered ciphertext, interrupted writes, nonce reuse, or supersession cycles;
4. confuse authentication with evidence provenance;
5. let model-generated text become evidence without explicit owner confirmation;
6. let general conversation silently alter project state;
7. accept a structurally grounded but internally inconsistent analysis;
8. reject a valid no-break analysis;
9. encode Project Aurora expectations into production prompt or validation;
10. allow prompt injection from evidence content;
11. accept fabricated or cross-record-invalid evidence IDs or span IDs;
12. permit model-generated titles, authors, timestamps, quotations, paths, or source cards to be displayed as canonical evidence metadata;
13. accept a project-grounded conversational claim with no valid supporting span;
14. speculate about a nonexistent project document instead of returning `insufficient_evidence`;
15. display part of an analysis after any source-reference failure;
16. create a contradiction between the vault contract and the reasoning input boundary;
17. require implementation work that is unnecessary for the vertical skeleton;
18. omit a dependency that would block the skeleton on Windows or Python 3.12;
19. create a hidden requirement for the UI that the JSON bridge cannot support;
20. make the intended GPT-5.6 API model impossible to configure or verify honestly;
21. rely on deterministic code to prove semantic truth;
22. leave confidential data in logs, exceptions, temporary files, or test output.

Use adversarial counterexamples. At minimum test mentally:

- a valid evidence ID with a fabricated span suffix;
- a valid span attributed to the wrong evidence record;
- one invalid citation among several otherwise valid citations;
- a fake provider returning its own author, title, quotation, or path;
- a user asking about an artifact absent from the verified evidence set;
- an attestation proposed but not confirmed;
- an attestation committed after vault relock or session expiry;
- a tampered encrypted vault file;
- a write interrupted between temporary-file creation and atomic replacement;
- a no-break evidence set containing an approved and fully propagated decision.

For every finding provide:

- ID
- Severity: BLOCKER / MAJOR / MINOR
- Document and section
- Exact rule or omission
- Concrete failure scenario
- Why existing tests would miss it
- Minimal correction
- Estimated effect on the vertical skeleton: NONE / SMALL / MATERIAL

Then provide exactly:

VERDICT:
- FREEZE
- FREEZE AFTER MINOR CORRECTIONS
- REVISE BEFORE IMPLEMENTATION

BLOCKERS

MAJOR FINDINGS

MINOR FINDINGS

RULES TO REMOVE

MISSING TESTS

MINIMAL DECISIONS TO FREEZE

SKELETON RISKS FOR THE NEXT IMPLEMENTATION DAY

Stop after the report.
