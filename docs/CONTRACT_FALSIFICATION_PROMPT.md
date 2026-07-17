# Independent Contract Falsification Prompt

Use this prompt with an independent model before implementation.

---

You are an adversarial architecture and security reviewer.

Review these three repository documents together:

- `docs/SECURITY_AND_PROVENANCE_CONTRACT_v0.1.md`
- `docs/GATE_G03_CONTRACT_v0.2.md`
- `docs/SKELETON_BUILD_PLAN.md`

Context:

- This is a time-constrained hackathon MVP.
- G-01 and G-02 are already implemented and must not be redesigned.
- The next implementation target is a working vertical skeleton, not a finished product.
- The product must support one local owner, encrypted application storage, authenticated user attestations, evidence-grounded reasoning, and normal conversation with the agent.
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
11. permit citation or span IDs that do not support the displayed source;
12. create a contradiction between the vault contract and the reasoning input boundary;
13. require implementation work that is unnecessary for the vertical skeleton;
14. omit a dependency that would block the skeleton on Windows or Python 3.12;
15. create a hidden requirement for the UI that the JSON bridge cannot support;
16. make the intended GPT-5.6 API model impossible to configure or verify honestly;
17. rely on deterministic code to prove semantic truth;
18. leave confidential data in logs, exceptions, temporary files, or test output.

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
