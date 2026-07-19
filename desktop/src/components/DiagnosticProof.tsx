import { useState } from "react";

import { isTauriRuntime } from "../bridge/client";
import type { DiagnosticClaim, DiagnosticDecision, DiagnosticPhase, SourceFinalStatus } from "../bridge/contracts";
import { continuitySession } from "../bridge/session";

interface DiagnosticProofProps {
  readonly onBack: () => void;
}

interface DiagnosticReportView {
  readonly result: "PASS" | "FAIL";
  readonly codexSessionId: string;
  readonly claims: readonly DiagnosticClaim[];
}

/**
 * Truncates an opaque Codex session id for compact display. Never pass a
 * local path, seed, or oracle value here -- this component never receives
 * any of those from Bridge in the first place (see
 * `diagnostic_proof_bridge_flow.py`'s explicit response allowlist).
 */
function shortId(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}

function decisionTone(status: string): string {
  if (status === "included") return "verified";
  if (status === "excluded") return "gap";
  return "attention";
}

export function DiagnosticProof({ onBack }: DiagnosticProofProps) {
  const [phase, setPhase] = useState<DiagnosticPhase>("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fingerprintPrefix, setFingerprintPrefix] = useState<string | null>(null);
  const [targetProject, setTargetProject] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<readonly DiagnosticDecision[]>([]);
  const [overrides, setOverrides] = useState<Readonly<Record<string, SourceFinalStatus>>>({});
  const [report, setReport] = useState<DiagnosticReportView | null>(null);
  const [tamperReport, setTamperReport] = useState<DiagnosticReportView | null>(null);

  const runtimeAvailable = isTauriRuntime();

  async function run(action: () => Promise<void>): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The local Bridge request failed.");
    } finally {
      setBusy(false);
    }
  }

  async function prepareWorkspace(): Promise<void> {
    await run(async () => {
      const data = await continuitySession.prepareDiagnosticWorkspace();
      setPhase(data.phase);
      setFingerprintPrefix(data.input_fingerprint_prefix);
      setTargetProject(null);
      setDecisions([]);
      setOverrides({});
      setReport(null);
      setTamperReport(null);
    });
  }

  async function runScoping(): Promise<void> {
    await run(async () => {
      const data = await continuitySession.runDiagnosticScoping();
      setPhase(data.phase);
      setTargetProject(data.target_project);
      setDecisions(data.decisions);
      setOverrides({});
    });
  }

  function setDecision(evidenceId: string, status: SourceFinalStatus): void {
    setOverrides((current) => ({ ...current, [evidenceId]: status }));
  }

  const allDecisionsResolved =
    decisions.length > 0 && decisions.every((decision) => overrides[decision.evidence_id] !== undefined);

  async function confirmScope(): Promise<void> {
    if (!allDecisionsResolved) {
      setError("Resolve every source (include or exclude) before confirming — nothing is approved automatically.");
      return;
    }
    await run(async () => {
      const data = await continuitySession.confirmDiagnosticScope(overrides);
      setPhase(data.phase);
      setReport({ result: data.result, codexSessionId: data.codex_session_id, claims: data.claims });
    });
  }

  async function runTamperCheck(): Promise<void> {
    await run(async () => {
      const data = await continuitySession.runDiagnosticTamperCheck();
      setPhase(data.phase);
      setTamperReport({ result: data.result, codexSessionId: data.codex_session_id, claims: data.claims });
    });
  }

  async function resetAll(): Promise<void> {
    await run(async () => {
      const data = await continuitySession.resetDiagnosticState();
      setPhase(data.phase);
      setFingerprintPrefix(null);
      setTargetProject(null);
      setDecisions([]);
      setOverrides({});
      setReport(null);
      setTamperReport(null);
    });
  }

  const oracleAbsentClaim = report?.claims.find((claim) => claim.name === "ORACLE_ABSENT_DURING_ENGINE_EXECUTION") ?? null;

  return (
    <section className="view active" aria-label="Diagnostic proof">
      <div className="page-shell workspace-shell live-project-shell">
        <div className="workspace-head">
          <div>
            <div className="eyebrow">Experimental · isolated diagnostic</div>
            <h1>Diagnostic Proof</h1>
            <p className="report-subtitle">
              Synthetic unseen workspace → real Codex Source Scoping → mandatory human review → approved-only
              materialization → the same Codex session resumed to report. A machine-evaluable PASS/FAIL proof, not a
              demonstration of real project data.
            </p>
          </div>
          <button className="crumb-button" type="button" onClick={onBack}>
            ← Workspace
          </button>
        </div>

        {!runtimeAvailable ? (
          <div className="locked-note" role="status">
            This flow requires the Tauri desktop runtime (the local Bridge process). Run the packaged app, or{" "}
            <code>npm run tauri dev</code>, to use it.
          </div>
        ) : null}

        {error ? (
          <div className="locked-note" role="alert">
            {error}
          </div>
        ) : null}

        <section className="finding-rail-section live-project-panel">
          <h3>1. Synthetic unseen workspace</h3>
          <button
            className="primary-button"
            type="button"
            disabled={busy || !runtimeAvailable || phase !== "idle"}
            onClick={() => void prepareWorkspace()}
          >
            Prepare a fresh synthetic unseen workspace
          </button>
          {fingerprintPrefix ? (
            <p className="live-project-path">Synthetic unseen workspace ready · fingerprint {fingerprintPrefix}…</p>
          ) : null}
        </section>

        {phase !== "idle" ? (
          <section className="finding-rail-section live-project-panel">
            <h3>2. Real Codex Source Scoping</h3>
            <button
              className="primary-button"
              type="button"
              disabled={busy || phase !== "workspace_ready"}
              onClick={() => void runScoping()}
            >
              Run real Codex Source Scoping investigation
            </button>
          </section>
        ) : null}

        {decisions.length > 0 ? (
          <section className="finding-rail-section live-project-panel">
            <h3>
              3. Human review — {decisions.length} sources{targetProject ? ` · ${targetProject}` : ""}
            </h3>
            <p className="report-subtitle">
              Every source needs an explicit human decision. Nothing is pre-selected from Codex's own classification.
            </p>
            <div className="status-list source-review-list">
              {decisions.map((decision) => {
                const current = overrides[decision.evidence_id];
                return (
                  <section className="status-row source-review-row" key={decision.evidence_id}>
                    <div className="status-label">
                      <span className="status-icon" aria-hidden="true">
                        {decision.evidence_id.slice(-2)}
                      </span>
                      {decision.evidence_id}
                    </div>
                    <div className="status-copy">
                      <span>
                        model classification: {decision.association_status} ({decision.basis})
                      </span>
                      <span>{decision.rationale}</span>
                    </div>
                    <div
                      className="source-review-controls"
                      role="group"
                      aria-label={`Decision for ${decision.evidence_id}`}
                    >
                      <span className={`status-tag ${decisionTone(current ?? "unresolved")}`}>
                        {current ?? "unresolved"}
                      </span>
                      <button
                        type="button"
                        className={current === "included" ? "primary-button" : "secondary-button"}
                        disabled={phase !== "awaiting_review" || busy}
                        onClick={() => setDecision(decision.evidence_id, "included")}
                      >
                        Include
                      </button>
                      <button
                        type="button"
                        className={current === "excluded" ? "primary-button" : "secondary-button"}
                        disabled={phase !== "awaiting_review" || busy}
                        onClick={() => setDecision(decision.evidence_id, "excluded")}
                      >
                        Exclude
                      </button>
                    </div>
                  </section>
                );
              })}
            </div>
            {phase === "awaiting_review" ? (
              <button
                className="primary-button"
                type="button"
                disabled={busy || !allDecisionsResolved}
                onClick={() => void confirmScope()}
              >
                Confirm scope &amp; materialize approved-only workspace
              </button>
            ) : null}
          </section>
        ) : null}

        {report ? (
          <section className="finding-rail-section live-project-panel" aria-label="Diagnostic proof result">
            <h3>4. Result</h3>
            <p className={`presentation-state tone-${report.result === "PASS" ? "neutral" : "attention"}`}>
              <span className="presentation-state-label">DIAGNOSTIC PROOF: {report.result}</span>
            </p>
            <dl className="source-facts">
              <div>
                <dt>Codex session</dt>
                <dd>{shortId(report.codexSessionId)}</dd>
              </div>
            </dl>
            {oracleAbsentClaim ? (
              <p className="live-project-path">
                Oracle absent during both Codex executions: <strong>{oracleAbsentClaim.status}</strong>
              </p>
            ) : null}
            <DiagnosticClaimsTable claims={report.claims} />

            {phase === "completed" ? (
              <button className="secondary-button" type="button" disabled={busy} onClick={() => void runTamperCheck()}>
                Run controlled tamper check (expected FAIL)
              </button>
            ) : null}
          </section>
        ) : null}

        {tamperReport ? (
          <section className="finding-rail-section live-project-panel" aria-label="Controlled tamper result">
            <h3>5. Controlled tamper check</h3>
            <p className={`presentation-state tone-${tamperReport.result === "PASS" ? "neutral" : "attention"}`}>
              <span className="presentation-state-label">DIAGNOSTIC PROOF: {tamperReport.result}</span>
            </p>
            <p className="report-subtitle">
              Expected FAIL — one already-approved artifact was deliberately altered after the PASS proof above.
            </p>
            <DiagnosticClaimsTable claims={tamperReport.claims} />
          </section>
        ) : null}

        {phase !== "idle" ? (
          <button className="crumb-button" type="button" disabled={busy} onClick={() => void resetAll()}>
            Reset diagnostic run
          </button>
        ) : null}
      </div>
    </section>
  );
}

function DiagnosticClaimsTable({ claims }: { readonly claims: readonly DiagnosticClaim[] }) {
  return (
    <div className="diagnostic-claims-table-wrap">
      <table className="diagnostic-claims-table">
        <thead>
          <tr>
            <th>Claim</th>
            <th>Status</th>
            <th>Observed</th>
          </tr>
        </thead>
        <tbody>
          {claims.map((claim) => (
            <tr key={claim.name}>
              <td>{claim.name}</td>
              <td>
                <span className={`status-tag ${claim.status === "PASS" ? "verified" : "attention"}`}>{claim.status}</span>
              </td>
              <td>{claim.observed}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
