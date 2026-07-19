# Integration Coherence Preflight v0.1

**Repository:** `ContinuityAI-integration-preflight`  
**Audit branch:** `audit/integration-coherence-preflight-v0.1`  
**Integration base:** `codex/main-unseen-project-mvp` @ `6b4b86ba287b2d814512bb36d5f44b7dc5f82bc1`  
**Auditor mode:** read-only preflight — no merge, cherry-pick, rebase, or production code changes  
**Date:** 2026-07-19

---

## 1. EXECUTIVE VERDICT

**INTEGRATION BLOCKED — ARCHITECTURAL DECISION REQUIRED**

The four audited tracks are **not yet composable into one frozen product architecture** without explicit synthesis decisions and new glue code. Git can apply some ranges cleanly in isolation, but a naive integration onto `6b4b86ba…` would **silently violate** the frozen architecture:

| Risk class | Severity | Summary |
|------------|----------|---------|
| **Semantic rollback** | BLOCKER | Merging Source Scoping tip (`ae9d82…`) onto integration base **deletes** the entire `unseen_workspace/` package and post-integrator reasoning hardening added in `6b4b86b…` ← `11bd8697…` (7 commits). |
| **Missing vertical glue** | BLOCKER | No Bridge commands wire Approved-only materialization or Codex session controller into the mixed → review → approved-only → same-session resume chain. |
| **Provisional controller** | BLOCKER | `codex/repair-local-codex-session-controller-v0.3` @ **`361729fe217980c5a23eb2891810bc1861482e71`** (origin) is under active security repair; must **not** enter integration until a separate PASS gate. |
| **UI contract gap** | MAJOR | Desktop UI (`73610f1…`) lacks Bridge commands and workspace fields for source scoping, approval, materialization, controller receipts, and scope review. |
| **Adapter gap** | MAJOR | Approved-only `SourceScopeBinding` is intentionally opaque and **not yet derived** from Source Scoping `ApprovedSourceScope.evidence_fingerprints`. |

**Controlled integration may begin only for Steps 0–2 below after coordinator sign-off on synthesis rules.** Steps 5–9 remain blocked until architectural questions in §15 are resolved and controller security repair passes.

---

## 2. BRANCH TOPOLOGY

Integration base:

| Item | Value |
|------|-------|
| Branch | `codex/main-unseen-project-mvp` |
| SHA | `6b4b86ba287b2d814512bb36d5f44b7dc5f82bc1` |
| Parent integrator fork | `11bd8697b4532883c4c6b02424769da1dc6bbaf3` (`backend/project-report-contract-v3`) |

### Track 1 — Source Scoping

| Item | Value |
|------|-------|
| Branch | `feature/project-source-scoping-v0.1` |
| Audited SHA | `ae9d82dbf6b87a817940a1bf039c88cd95970efa` |
| **Merge-base with integration base** | **`11bd8697…`** (not `6b4b86b…`) |
| Ahead / behind base | **+31 / −7** (relative to merge-base) |
| Integration mode | **File-level synthesis required** — not a safe fast-forward onto `6b4b86b…` |
| Audit-only / transient commits in range | Temporary CI audit workflows (`d2ec1a0`, `967eb55`, `e559a9f`, `7cbbbac`, `28a7d1d`, `7620131`); `[skip ci]` repair commits (`1f6d8de`, `75c6660`). Net tree is production-shaped, but **history replay onto `6b4b86b…` is unsafe**. |

### Track 2 — Approved-only workspace

| Item | Value |
|------|-------|
| Branch | `codex/approved-only-downstream-v0.1` |
| Audited SHA | `01ded4552e570856f155dbee1c94a5a53a663083` |
| Merge-base with integration base | `6b4b86ba…` |
| Ahead / behind base | **+1 / 0** |
| Integration mode | **Clean additive commit** (`01ded45`) — no shared-file conflict with base |
| Unrelated changes | None observed |

### Track 3 — Local Codex Session Controller (provisional)

| Item | Value |
|------|-------|
| Branch | `codex/repair-local-codex-session-controller-v0.3` |
| **Origin SHA (provisional)** | **`361729fe217980c5a23eb2891810bc1861482e71`** |
| Verified via | `git ls-remote origin refs/heads/codex/repair-local-codex-session-controller-v0.3` |
| Merge-base with integration base | `6b4b86ba…` |
| Ahead / behind base | **+7 / 0** |
| Integration mode | Additive on base, **but integration itself is blocked** pending security repair PASS |
| Audit-only commits | `51b3b48` (audit reproductions), `0dc1819` (v0.2 re-audit), `03493cb` (v0.3 re-audit) — keep tests/docs, do not treat as production behavior changes |
| Production commits | `a968225`, `a673ca4`, `4034174`, `361729f` (+ repair docs) |

### Track 4 — Desktop UI

| Item | Value |
|------|-------|
| Branch | `ui/project-report-v0.3` |
| Audited SHA | `73610f114137b5e48903dafbdc937d3b8a908f2e` |
| Merge-base with integration base | `8cf3845f3ad1da032406faaa985a099e67fcac4a` (transport checkpoint) |
| Ahead / behind base (Python tree) | **0 / 10** on `src/` — UI branch does not contain base’s 10 newer Python commits |
| Ahead on `desktop/**` | **+4 commits** from transport checkpoint |
| Integration mode | **Parallel subtree merge** — no textual Python conflicts; **contract gaps** vs future Bridge |

---

## 3. PRODUCTION COMMIT RANGES

Only commits that define deliverable component behavior (exclude audit-branch bookkeeping on `audit/*`).

| Step | Range | Commits | Notes |
|------|-------|---------|-------|
| Base | `6b4b86ba…` | 1 (tip) | Includes unseen-workspace spike + reasoning hardening since `11bd8697…` |
| Base delta (integrator → base) | `11bd8697…` → `6b4b86ba…` | 7 | Must be **preserved** during Source Scoping synthesis |
| Source Scoping | `11bd8697…` → `ae9d82…` | 31 | Production domain + Bridge wiring + tests; **do not replay blindly onto `6b4b86b…`** |
| Approved-only | `6b4b86ba…` → `01ded455…` | 1 | `01ded45 Add approved-only workspace materializer` |
| Controller (provisional) | `6b4b86ba…` → `361729fe…` | 7 | 4 production + 3 audit-reproduction |
| UI | `8cf3845…` → `73610f1…` | 4 | Desktop-only: shell, bootstrap, timeout, window constraints |

**Recommended integration artifact for Source Scoping:** final tree at `ae9d82…` **plus** restoration of base delta `11bd8697…` → `6b4b86b…`, with manual synthesis on `tests/test_vertical_skeleton.py` (only path-level overlap between the two ranges).

---

## 4. FILE COLLISION MATRIX

Legend: **T** = textual Git conflict likely, **S** = semantic-only, **G** = integration gap (missing wiring), **—** = no change in branch commit range.

| File | Scoping | Approved | Controller | UI | Conflict | Owner | Resolution |
|------|---------|----------|------------|-----|----------|-------|------------|
| `src/continuity_ai/bridge.py` | ✓ | — | — | — | **S** vs base | **Bridge / integration glue** | Synthesize: keep base retained-analysis + unseen-workspace-safe provider selection **and** scoping commands (`scope_project_sources`, `confirm_source_scope`, scoping-aware downstream evidence). |
| `src/continuity_ai/conversation.py` | ✓ | — | — | — | **S** | **Conversation + scoping** | Keep scoping revision context binding (`analysis_revision.py`); preserve base conversation semantics. |
| `src/continuity_ai/domain.py` | ✓ | — | — | — | **S** | **Domain** | Merge `AnalysisRevisionContextBinding` + scoping types; no duplicate status enums. |
| `src/continuity_ai/vault.py` | ✓ | — | — | — | **S** | **Vault** | Keep scoping persistence hooks; preserve base vault session invariants. |
| `src/continuity_ai/unseen_workspace/codex_workspace_spike.py` | **deletes in scoping tree** | — | ✓ | — | **S/T** | **Unseen workspace spike** | **Keep base/spike + controller patch** — never accept scoping tree deletion. |
| `tests/test_vertical_skeleton.py` | ✓ | — | — | — | **T/S** | **Vertical integration tests** | Manual synthesis: base bridge tests + scoping lifecycle tests. |
| `tests/unseen_workspace/test_codex_workspace_spike.py` | **absent in scoping tree** | — | ✓ | — | **S** | **Spike tests** | Restore from base; apply controller delta (`361729fe…`). |
| `pyproject.toml` | ✓ (minor) | — | — | — | **S** | **Build** | Union test paths; keep base provider deps. |
| `README.md` / docs | ✓ | ✓ | ✓ | ✓ | **S** | **Docs** | Merge narratives; do not drop unseen-workspace or scoping contracts. |
| `src/continuity_ai/approved_workspace/*` | — | ✓ (new) | — | — | **G** | **Approved-only** | Additive; needs Bridge + binding adapter. |
| `src/continuity_ai/codex_session.py` | — | — | ✓ (new) | — | **G** | **Controller** | Additive; blocked until security PASS. |
| `src/continuity_ai/source_scoping/*` | ✓ (new) | — | — | — | — | **Source Scoping** | Land as new package. |
| `desktop/src/bridge/contracts.ts` | — | — | — | ✓ | **G** | **UI contracts** | Extend after Python Bridge stabilizes. |
| `desktop/src/bridge/projectReportProjection.ts` | — | — | — | ✓ | **G** | **UI projection** | Keep adapter-only until backend wiring gate. |
| `desktop/src/types/workspace.ts` | — | — | — | ✓ | **G** | **UI types** | Presentation-only until Bridge fields exist. |
| `desktop/src/data/demoWorkspace.ts` | — | — | — | ✓ | **G** | **UI demo fixtures** | Retain for presentation; replace runtime claims only. |

---

## 5. SEMANTIC COLLISION MATRIX

| ID | Type | Tracks | Invariant violated if ignored | Detection |
|----|------|--------|------------------------------|-----------|
| SC-01 | **Semantic** | Scoping × Base | Unseen workspace generator + Codex classification spike removed | `git diff 6b4b86b ae9d82 -- src/continuity_ai/unseen_workspace/` shows full deletion |
| SC-02 | **Semantic** | Scoping × Base | Reasoning hardening (`reasoning_contract.py`, `analysis_validation.py`, `deterministic_offline_provider.py`) removed | Same diff removes modules restored in `6b4b86b…` |
| SC-03 | **Semantic** | Scoping × Base | Bridge downstream evidence uses approved scope, but base retained-analysis F-04/F-11 behavior must remain | Compare `get_workspace_state` + `_restore_from_vault` on both tips |
| SC-04 | **Integration gap** | Scoping × Approved-only | EXCLUDE/DEFER (`ambiguous`) must not cross approved boundary | `review.py` only emits `included`/`excluded`; materializer rejects undeclared artifacts |
| SC-05 | **Integration gap** | Approved-only × Scoping | `SourceScopeBinding.binding_sha256` must match scoping serialization | No shared function exists today |
| SC-06 | **Integration gap** | Controller × Scoping × Approved | Same Codex session must resume on **physically separate** approved workspace | Controller has `bind_approved_workspace()` + `resume_session()`; Bridge has no orchestration |
| SC-07 | **Semantic** | Controller × Base | Spike remains test adapter; controller owns production session | Docs state spike is not production controller |
| SC-08 | **Integration gap** | UI × Backend | UI TS commands omit scoping / materialization / controller | `contracts.ts` ends at `get_workspace_state` |
| SC-09 | **Semantic** | UI demo | `demoWorkspace.ts` must not imply backend vault/attestation persistence | Already bounded in `73610f1…`; must not regress during wiring |
| SC-10 | **Semantic** | Scoping history | Replaying 31 commits onto `6b4b86b…` reintroduces intermediate Bridge states | `git merge-tree 6b4b86b 6b4b86b ae9d82` shows destructive tree delta (−5135/+4760 lines) |

---

## 6. CONTRACT OWNERSHIP TABLE

| Contract | Owner track | Integration consumer | Notes |
|----------|-------------|---------------------|-------|
| Source Scoping domain + serialization | **Source Scoping** (`source_scoping/domain.py`, `serialization.py`) | Bridge, Approved-only adapter, UI scope review | Human terms: `included`/`excluded`/`ambiguous`; ambiguous = DEFER analog — never auto-selected |
| Bridge command dispatch | **Bridge** (`bridge.py`) — synthesized owner | UI, Tauri transport | Scoping adds commands; glue adds materialization/controller commands later |
| Conversation lifecycle | **Conversation** + Vault session binding | Bridge, UI | Scoping adds `approved_source_scope` to revision binding |
| Analysis revision binding | **analysis_revision.py** (Scoping track) | Bridge `confirm_analysis_revision` | Exact context binding required (`ae9d82…`) |
| Vault persistence | **Vault** | Bridge, Scoping persistence | Scoping stores approved scope in vault |
| Approved-only workspace | **Approved-only** (`approved_workspace/`) | Controller, Bridge glue | Physically separate destination root; atomic publish |
| evidence_id → path → SHA-256 | **Approved-only materializer** + artifact registry from Bridge/scoping | Controller bind, UI Evidence Inspector | Materializer validates `expected_sha256` at copy time |
| Codex session lifecycle | **Controller** (`codex_session.py`) — **provisional** | Vertical glue, UI receipts | `SessionPhase.AWAITING_HUMAN_REVIEW` → `bind_approved_workspace` → `APPROVED` |
| Operation receipts | **Controller** (`InvocationReceipt`) | UI status rail | Fields: `controller_session_id`, `codex_session_id`, fingerprints, `resume_attempted` |
| Same-session resume | **Controller** | Vertical glue | `resume_session(codex_session_id, workspace_root, …)` — **no new session after approval** |
| unavailable / interrupted | **Controller** + Bridge error mapping | UI presentation states | UI must not invent backend states |
| Project Report schema 3.0 | **Integrator `11bd8697…` lineage** | UI projection | Scoping tree retains v3; downstream uses **approved evidence only** after scope |
| Frontend projection | **UI** (`projectReportProjection.ts`) | App shell post-wiring | Not runtime owner of semantics |
| Evidence citations | **Bridge hydration** + retained snapshot rules | UI chips | F-04: retained quotes immutable |
| Restart restoration | **Bridge** + Vault + retained_analysis + Controller store | UI bootstrap | Must restore scope + controller session consistently |

**Architectural tension requiring coordinator decision:** Bridge is currently the de facto orchestrator for vault/project/analysis, but **Approved-only** and **Controller** docs explicitly say they are **not integrated** with Bridge yet. A second orchestration owner must be chosen (§15 Q1).

---

## 7. SOURCE SCOPING SYNTHESIS PLAN

### 7.1 Why not `git merge ae9d82` onto `6b4b86b`

`git diff --stat 6b4b86b ae9d82` shows **84 files**, net removal of unseen-workspace and reasoning modules. That is not a Git conflict — it is a **silent architectural rollback**.

### 7.2 Recommended synthesis procedure

1. Create integration staging branch from **`6b4b86ba…`** (preserves base delta).
2. **Copy in** entire `src/continuity_ai/source_scoping/` tree from `ae9d82…` (new files — no conflict).
3. **Manual file synthesis** (do not use merge=ours/theirs blindly):
   - `src/continuity_ai/bridge.py` — import scoping adapter; add commands; **retain** `retained_analysis`, `_hydrate_retained_cards`, provider selection from base.
   - `src/continuity_ai/conversation.py` — keep scoping-aware revision binding.
   - `src/continuity_ai/domain.py`, `vault.py`, `analysis_revision.py` — take scoping versions where they extend integrator contracts; verify retained-analysis types unchanged.
   - `src/continuity_ai/reasoning_pipeline.py` — **keep base** hardened pipeline; wire scoping-selected evidence into downstream calls (already partially done in scoping tip).
4. **Restore unchanged from base** everything under `src/continuity_ai/unseen_workspace/` and `tests/unseen_workspace/` deleted on scoping tip.
5. **Synthesize** `tests/test_vertical_skeleton.py` — union of:
   - base: bridge retained-analysis / F-11 tests (`6b4b86b…`)
   - scoping: lifecycle boundary tests (from `tests/source_scoping/test_lifecycle_boundary.py` coverage expectations reflected in vertical skeleton where appropriate)
6. Run focused gates (§13 Step 2).

### 7.3 History replay verdict

| Approach | Verdict |
|----------|---------|
| Replay all 31 commits onto `6b4b86b…` | **REJECT** — history contains superseded Bridge states; merge-base mismatch hides rollback |
| Cherry-pick production commits only | **RISKY** — same semantic rollback on shared files |
| **Final tree synthesis** (§7.2) | **RECOMMEND** |

### 7.4 bridge.py regression check

Scoping tip **does** include newer Bridge commands:

- `scope_project_sources`
- `confirm_source_scope`
- scoping fields in `get_workspace_state`: `source_scoping_status`, `source_scope`, `approved_source_scope`, `source_scope_persisted`

Scoping tip **also retains** `retained_analysis_status` from integrator lineage. Synthesis must verify both coexist after merge with base delta.

### 7.5 conversation.py revision binding

Scoping tip requires exact `AnalysisRevisionContextBinding` match on confirm (`confirm_analysis_revision` passes `build_analysis_revision_context_binding(… approved_source_scope=…)`). **Do not** integrate an older Bridge that omits this check.

---

## 8. APPROVED-ONLY ADAPTER PLAN

### 8.1 Contract alignment

| Source Scoping | Approved-only | Gap |
|----------------|---------------|-----|
| `ReviewedSourceDecision.final_status` ∈ `{included, excluded}` | `ApprovedArtifactSelection` for included only | Map `approved_evidence_ids` + artifact paths + SHA-256 |
| `ambiguous` decisions | Not materialized | **Correct** — human must resolve to included/excluded first |
| `ApprovedSourceScope.evidence_fingerprints: tuple[tuple[str,str], …]` | `SourceScopeBinding.expected_source_fingerprints: tuple[str,…]` | Needs canonical hash list + **`binding_sha256`** derivation |

Approved-only doc (`APPROVED_ONLY_WORKSPACE_V0.1.md`) states component is **intentionally not integrated** with Source Scoping yet.

### 8.2 Required glue module (design only)

**Proposed:** `src/continuity_ai/integration/approved_scope_materialization.py`

| Function | Input | Output | Invariants |
|----------|-------|--------|------------|
| `build_approved_workspace_request` | mixed root, `ApprovedSourceScope`, artifact path registry, human attestations, destination root | `ApprovedWorkspaceRequest` | Only `included` IDs; SHA-256 verified against scoping fingerprints |
| `compute_source_scope_binding` | `ApprovedSourceScope` | `SourceScopeBinding` | Opaque `binding_sha256`; fingerprint set equals approved included artifacts |

### 8.3 Bridge command gap

No Bridge command today calls `ApprovedWorkspaceMaterializer`. Step 4 must add a command (name TBD by coordinator) that:

1. Requires `source_scoping_status == approved`.
2. Builds binding via adapter.
3. Materializes to **new** destination path (never mixed root).
4. Returns sanitized `MaterializationReceipt` (no paths/secrets in errors).

### 8.4 Tests

| Test | File |
|------|------|
| Existing materializer suite | `tests/approved_workspace/test_materializer.py` (755 lines) |
| New cross-boundary tests | `tests/integration/test_scoping_to_approved_workspace.py` (to be created at integration time) |
| Regression | EXCLUDE/DEFER artifacts physically absent in destination |

---

## 9. SESSION CONTROLLER INTEGRATION PLAN

**Provisional SHA:** `361729fe217980c5a23eb2891810bc1861482e71` (origin `codex/repair-local-codex-session-controller-v0.3`)

**Integration status:** **DO NOT MERGE** until independent security re-audit PASS on latest SHA.

### 9.1 Exposed integration API (observed)

| API | Purpose |
|-----|---------|
| `CodexControllerSession` persisted state | `controller_session_id`, `codex_session_id`, `workspace_root`, fingerprints, `approved_workspace_*`, `phase`, receipts |
| `bind_approved_workspace(controller_session_id, approved_root, fingerprint)` | Requires `SessionPhase.AWAITING_HUMAN_REVIEW`; rejects widening/equal paths |
| `resume_session(controller_session_id, codex_session_id, workspace_root, request)` | Same UUID resume; fails with `ResumeUnsupported` if CLI boundary cannot resume |
| `InvocationReceipt` | Consumable by UI for unavailable/interrupted/resume proof |

### 9.2 Same-session resume topology (required, not optional)

```
mixed workspace path
  → controller launch (genuine codex_session_id)
  → source scoping classify + human confirm (Bridge)
  → approved-only materializer → NEW destination root
  → controller.bind_approved_workspace(approved_root, fingerprint)
  → controller.resume_session(SAME codex_session_id, approved_root, operation)
  → Project Report reasoning on approved evidence only
```

**No step may spawn a fresh Codex session after human approval.**

### 9.3 Spike boundary

`unseen_workspace/codex_workspace_spike.py` remains a **classification spike** per base docs. Controller patch at `361729fe…` modifies spike for CAS/concurrency tests — keep spike **test-only**, not production orchestration.

### 9.4 Audit-only artifacts (keep, don’t productize)

- `tests/audit_codex_session/test_crash_recovery_and_executable_pinning.py`
- `tests/audit_codex_session_v02/test_reaudit_v02_findings.py`
- `tests/audit_codex_session_v03/test_reaudit_v03_findings.py`

---

## 10. UI CONTRACT GAP ANALYSIS

Git: **no textual conflict** on `desktop/**` vs Python integration (disjoint paths).

### 10.1 TypeScript Bridge commands at `73610f1…`

Present: `initialize_vault`, `unlock_vault`, `lock_vault`, `load_project`, `analyze_project`, `send_message`, `confirm_attestation`, `confirm_analysis_revision`, `get_workspace_state`.

**Missing for frozen architecture:**

| Missing command / field | Backend owner (future) |
|-------------------------|------------------------|
| `scope_project_sources` | Scoping Bridge |
| `confirm_source_scope` | Scoping Bridge |
| Approved workspace materialization command | Approved-only glue |
| Controller session / resume commands | Controller glue |
| `source_scoping_status`, `source_scope`, `approved_source_scope`, `source_scope_persisted` in workspace state | Scoping adapter payload |
| Controller receipt surfaces | Controller |

### 10.2 demoWorkspace.ts — replace vs retain

| Keep as synthetic fixture (presentation only) | Must be replaced at wiring time by Bridge-backed state |
|-----------------------------------------------|------------------------------------------------------|
| Aurora narrative copy, section layout demos | `vault_unlocked`, owner display name |
| Static evidence cards for demo cinematography | `source_scoping_status`, scope review UI |
| Placeholder conversation scripts in `App.tsx` | `project_report` rendering from `get_workspace_state` |
| `Synthetic demo project` badges | Attestation / revision persistence claims |
| Evidence inspector **layout** patterns | Citation chips bound to live `evidence_records` IDs + SHA metadata |

`App.tsx` at `73610f1…` intentionally imports **`demoWorkspace.ts` only** (`architectureBoundary.test.ts` enforces). Wiring gate must switch data source without removing presentation fixtures used in non-Tauri/demo mode.

### 10.3 UI branch lag

UI merge-base `8cf3845…` is **10 commits behind** integration base on Python. Desktop transport docs reference older provider names (`fake_aurora` in INTEGRATION_CHECKPOINT.md). Wiring phase must target **`6b4b86b…` + integrated backend**, not transport checkpoint alone.

---

## 11. REQUIRED GLUE COMPONENTS

| Component | Path (proposed) | Responsibility | Depends on |
|-----------|-----------------|----------------|------------|
| **Scope binding adapter** | `src/continuity_ai/integration/source_scope_binding.py` | `ApprovedSourceScope` → `SourceScopeBinding` | Scoping + Approved-only |
| **Approved materialization orchestrator** | `src/continuity_ai/integration/approved_workspace_flow.py` | Build request, invoke materializer, return receipt | Approved-only |
| **Codex session orchestrator** | `src/continuity_ai/integration/codex_session_flow.py` | Phase transitions, bind + resume, no new session | Controller (post-PASS) |
| **Vertical glue coordinator** | `src/continuity_ai/integration/mixed_to_approved_pipeline.py` | Enforces frozen flow ordering | All backend tracks |
| **Bridge command extensions** | `src/continuity_ai/bridge.py` (synthesized) | Single NDJSON entry surface | Glue modules |
| **UI contract extension** | `desktop/src/bridge/contracts.ts` | Typed commands + workspace fields | Bridge stabilization |
| **UI scope review surfaces** | `desktop/src/components/*` (future) | Human INCLUDE/EXCLUDE/DEFER — **no filename inference** | Bridge scoping payloads |
| **Restart restoration glue** | Bridge + controller store | Restore scope + session + retained analysis jointly | Steps 1–6 complete |

**Minimalism rule:** no shared framework beyond these targeted modules.

---

## 12. ORDERED INTEGRATION SEQUENCE

Preferred order retained with one change: **Controller moved after vertical glue design sign-off**, not merely after tests.

### Step 0 — Staging branch

| Item | Detail |
|------|--------|
| Branch | `integration/staging-v0.1` from `6b4b86ba…` |
| Files unchanged | All of base |
| Owner | Integrator |
| STOP if | Working tree not clean |

### Step 1 — Source Scoping synthesis

| Item | Detail |
|------|--------|
| Source | Tree from `ae9d82…` per §7 |
| Manual synthesis | `bridge.py`, `conversation.py`, `domain.py`, `vault.py`, `tests/test_vertical_skeleton.py` |
| Restore from base | entire `unseen_workspace/**`, reasoning hardening modules |
| Owner | Backend integrator + scoping owner |
| Focused tests | `uv run pytest tests/source_scoping -q` |
| Full gate | `uv run pytest -q` (expect increase ~+13 scoping files) |
| STOP if | Any unseen_workspace test missing; Bridge missing retained_analysis fields; scoping downstream uses unscoped mixed evidence |

### Step 2 — Full regression

| Gate | `uv run pytest -q`; bridge process e2e |
| STOP if | Count drops vs Step 0 baseline |

### Step 3 — Approved-only additive merge

| Item | Detail |
|------|--------|
| Range | `01ded45` |
| Files | `src/continuity_ai/approved_workspace/**`, tests, docs |
| Glue | Implement §8 adapter (new code — integration step, not in audited branches) |
| Focused tests | `uv run pytest tests/approved_workspace -q` |
| STOP if | Materializer accepts EXCLUDE/DEFER or fingerprint mismatch |

### Step 4 — Full regression

Same as Step 2 + new integration tests for scoping→approved path.

### Step 5 — Controller (blocked until security PASS)

| Item | Detail |
|------|--------|
| SHA | Track **`origin/codex/repair-local-codex-session-controller-v0.3`** — re-verify SHA at integration time |
| Provisional audited SHA | `361729fe217980c5a23eb2891810bc1861482e71` |
| Manual synthesis | `codex_workspace_spike.py` with base spike + controller patch |
| Focused tests | `pytest tests/test_codex_session.py`, audit folders |
| STOP if | Security re-audit open; resume creates new session; bind accepts mixed root |

### Step 6 — Full regression + live Codex smoke

Manual: launch → classify → approve → materialize → bind → resume on Windows.

### Step 7 — Vertical integration glue

Implement §11 modules + Bridge commands; **single orchestrated entry** for the frozen flow.

### Step 8 — UI backend wiring

Merge `ui/project-report-v0.3` @ `73610f1…` (or successor), extend contracts, replace demo claims per §10.2.

### Step 9 — Windows runtime acceptance

Tauri + Bridge bootstrap + scope review + approved path + conversation with citations.

---

## 13. TEST GATES

| Stage | Focused | Full | Expected clean state |
|-------|---------|------|----------------------|
| Base | — | pytest @ `6b4b86b…` | 20 test modules under `tests/` |
| After Scoping | `tests/source_scoping/` (13 files) | full pytest | unseen_workspace tests present |
| After Approved-only | `tests/approved_workspace/` | full pytest | +755 materializer assertions |
| After Controller | `tests/test_codex_session.py` + audit v02/v03 | full pytest minus live | 39+ unit controller tests |
| UI wiring | `desktop npm test` | cargo test | 40 Node tests @ `73610f1…` baseline |
| Vertical glue | new `tests/integration/` | full + desktop | End-to-end mixed→approved flow |

Record exact counts at each gate during integration execution (not fixed in this preflight).

---

## 14. STOP CONDITIONS

Integration **must halt** if any of the following occur:

1. Merge would delete `src/continuity_ai/unseen_workspace/` or reasoning hardening modules.
2. `confirm_analysis_revision` loses exact context binding check.
3. Approved materializer copies from mixed workspace root instead of dedicated destination.
4. EXCLUDE, DEFER (`ambiguous`), or unresolved scope records appear in approved workspace manifest.
5. Controller integration proceeds before security re-audit PASS on current origin SHA.
6. `resume_session` uses a **new** `codex_session_id` after approval.
7. UI presents backend persistence, vault unlock, or agent responses not backed by Bridge envelopes.
8. Bridge bootstrap or UI wiring drops citation receipts / retained snapshot F-04 behavior.
9. Git merge completes with zero conflicts but pytest loses scoping, approved-only, or unseen_workspace coverage.

---

## 15. PRECISE OPEN QUESTIONS

**Q1 — Orchestration ownership:** Should the frozen mixed→approved→resume pipeline live entirely in `bridge.py` dispatch, or in a dedicated `integration/` package called by Bridge? (Both tracks currently assume the other will orchestrate.)

**Q2 — SourceScopeBinding derivation:** What canonical JSON (field order, hash algorithm) defines `binding_sha256` from `ApprovedSourceScope`? Approved-only expects opaque hash; scoping stores `evidence_fingerprints` pairs — who publishes the normative binding algorithm?

**Q3 — Codex session vs scoping order:** Does Codex classification run **before** Source Scoping provider classification, or does Source Scoping replace Codex for evidence association? Base spike vs scoping provider are parallel subsystems today.

**Q4 — Controller security gate:** What exact re-audit SHA and test checklist replaces provisional `361729fe…` for Step 5 entry?

**Q5 — UI wiring base:** Should UI wiring target `73610f1…` only, or wait for `ui/project-report-polish-v0.4` presentation branch merge first?

---

## 16. FINAL RECOMMENDATION

### Verdict

# **INTEGRATION BLOCKED — ARCHITECTURAL DECISION REQUIRED**

### Rationale (concise)

- **Source Scoping** is integratable **only by controlled tree synthesis**, not by merging `ae9d82…` onto `6b4b86ba…`.
- **Approved-only** is integratable as the next additive commit **after** scoping synthesis and adapter design (**Q2**).
- **Controller** topology supports same-session resume (`bind_approved_workspace`, `resume_session`) but remains **provisional** — do not integrate until **Q4** resolved.
- **UI** merges cleanly in Git but lacks **contract coverage** for the full frozen flow; keep `demoWorkspace.ts` as presentation fixture until Step 8.
- **Vertical glue does not exist** in any audited branch; **Q1** must be answered before Step 7.

### After decisions

Once **Q1–Q4** are answered, re-run this preflight against new SHAs and downgrade verdict to:

**READY FOR CONTROLLED INTEGRATION**

executing Steps 0–4 under the gates in §12–§13, with Controller (Step 5+) explicitly gated.

---

## Appendix A — Tooling evidence

| Command | Result |
|---------|--------|
| `git merge-base 6b4b86b ae9d82` | `11bd8697…` |
| `git rev-list --count 11bd8697..ae9d82` | 31 |
| `git rev-list --count 11bd8697..6b4b86b` | 7 |
| `git merge-base 6b4b86b 01ded45` | `6b4b86b…` (fast-forwardable) |
| `git merge-base 6b4b86b 361729fe` | `6b4b86b…` |
| `git ls-remote origin codex/repair-local-codex-session-controller-v0.3` | `361729fe217980c5a23eb2891810bc1861482e71` |
| `git merge-tree 6b4b86b 6b4b86b ae9d82` | Large destructive delta; shared file semantic conflicts on `bridge.py`, `conversation.py`, deletes `unseen_workspace/**` |
| `git merge-tree ae9d82 ae9d82 361729fe` | Adds controller modules; modifies spike if present — spike absent on scoping-only tree |
| Overlap `11bd8697..6b4b86b` ∩ `11bd8697..ae9d82` file paths | **`tests/test_vertical_skeleton.py` only** |

## Appendix B — Proposed minimal corrections (no production code in this audit)

| ID | Problem | Target | When | Acceptance test |
|----|---------|--------|------|-----------------|
| PC-01 | No binding between scopes | `integration/source_scope_binding.py` | Before Step 3 | Fingerprint mismatch → `FailureCategory.SOURCE_FINGERPRINT_MISMATCH` |
| PC-02 | No Bridge materialization | `bridge.py` + glue | Step 3–4 | Approved copy never reads mixed root |
| PC-03 | No orchestrated resume | `integration/codex_session_flow.py` | Step 7 | Same `codex_session_id` across bind+resume |
| PC-04 | UI missing commands | `desktop/src/bridge/contracts.ts` | Step 8 | Typed `scope_project_sources` / `confirm_source_scope` |
| PC-05 | Vertical skeleton incomplete | `tests/test_vertical_skeleton.py` | Step 1 synthesis | Passes both retained-analysis and scoping lifecycle cases |

---

*End of Integration Coherence Preflight v0.1*
