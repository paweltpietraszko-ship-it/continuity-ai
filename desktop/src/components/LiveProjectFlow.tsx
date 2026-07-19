import { useState } from "react";

import { isTauriRuntime } from "../bridge/client";
import type {
  AnalysisData,
  ConfirmSourceScopeData,
  ScopeProjectSourcesData,
  SourceFinalStatus,
  WorkspaceState,
} from "../bridge/contracts";
import { selectArtifactRoot, selectExistingVault, selectNewVaultPath } from "../bridge/dialogs";
import { createProjectReportDisplay, ProjectReportContractError } from "../bridge/projectReportProjection";
import { continuitySession } from "../bridge/session";

type FlowStep = "setup" | "loaded" | "reviewing" | "approved" | "reported";

interface LiveProjectFlowProps {
  readonly onBack: () => void;
}

function statusTone(status: "included" | "excluded" | "ambiguous"): string {
  if (status === "included") return "verified";
  if (status === "excluded") return "gap";
  return "attention";
}

/**
 * Truncates an opaque identifier or fingerprint for compact display. Never
 * pass a local path, prompt, or other free-text value here — this is only
 * for the fixed-format UUIDs and SHA-256 hex digests in `RunIdentity`.
 */
function shortId(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}

export function LiveProjectFlow({ onBack }: LiveProjectFlowProps) {
  const [step, setStep] = useState<FlowStep>("setup");
  const [vaultPath, setVaultPath] = useState("");
  const [password, setPassword] = useState("");
  const [ownerName, setOwnerName] = useState("Owner");
  const [artifactRoot, setArtifactRoot] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [workspaceState, setWorkspaceState] = useState<WorkspaceState | null>(null);
  const [scoping, setScoping] = useState<ScopeProjectSourcesData | null>(null);
  const [overrides, setOverrides] = useState<Readonly<Record<string, SourceFinalStatus>>>({});
  const [confirmed, setConfirmed] = useState<ConfirmSourceScopeData | null>(null);
  const [question, setQuestion] = useState("What is the current project state?");
  const [analysis, setAnalysis] = useState<AnalysisData | null>(null);

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

  async function createVault(): Promise<void> {
    const path = await selectNewVaultPath();
    if (!path) return;
    await run(async () => {
      const state = await continuitySession.initializeVault(path, password, ownerName);
      setVaultPath(path);
      setWorkspaceState(state);
    });
  }

  async function unlockVault(): Promise<void> {
    const path = vaultPath || (await selectExistingVault());
    if (!path) return;
    await run(async () => {
      const state = await continuitySession.unlockVault(path, password);
      setVaultPath(path);
      setWorkspaceState(state);
    });
  }

  async function pickAndLoadProject(): Promise<void> {
    const root = await selectArtifactRoot();
    if (!root) return;
    await run(async () => {
      const state = await continuitySession.loadProject(root);
      setArtifactRoot(root);
      setWorkspaceState(state);
      setStep("loaded");
    });
  }

  async function startScoping(): Promise<void> {
    await run(async () => {
      const result = await continuitySession.scopeProjectSources();
      const initialOverrides: Record<string, SourceFinalStatus> = {};
      for (const decision of result.source_scope.decisions) {
        if (decision.association_status !== "ambiguous") {
          initialOverrides[decision.evidence_id] = decision.association_status;
        }
      }
      setScoping(result);
      setOverrides(initialOverrides);
      setConfirmed(null);
      setAnalysis(null);
      setStep("reviewing");
    });
  }

  function setDecision(evidenceId: string, status: SourceFinalStatus): void {
    setOverrides((current) => ({ ...current, [evidenceId]: status }));
  }

  const allDecisionsResolved =
    scoping !== null &&
    scoping.source_scope.decisions.every((decision) => overrides[decision.evidence_id] !== undefined);

  async function confirmScope(): Promise<void> {
    if (!allDecisionsResolved) {
      setError("Resolve every source (include or exclude) before confirming — nothing is approved automatically.");
      return;
    }
    await run(async () => {
      const result = await continuitySession.confirmSourceScope(overrides);
      setConfirmed(result);
      setStep("approved");
    });
  }

  async function generateReport(): Promise<void> {
    await run(async () => {
      const { analysis: result, state } = await continuitySession.analyzeProject(question);
      setAnalysis(result);
      setWorkspaceState(state);
      setStep("reported");
    });
  }

  const investigationIdentity = scoping?.run_identity ?? null;
  const reportingIdentity = analysis?.run_identity ?? confirmed?.run_identity ?? null;

  let reportDisplay: ReturnType<typeof createProjectReportDisplay> | null = null;
  let reportError: string | null = null;
  if (analysis) {
    try {
      reportDisplay = createProjectReportDisplay(
        analysis.project_report,
        analysis.citation_cards,
        analysis.analysis_status,
        analysis.continuity_break,
      );
    } catch (caught) {
      reportError =
        caught instanceof ProjectReportContractError
          ? caught.message
          : "The report returned by the local analysis process could not be displayed.";
    }
  }

  return (
    <section className="view active" aria-label="Live project">
      <div className="page-shell workspace-shell live-project-shell">
        <div className="workspace-head">
          <div>
            <div className="eyebrow">Real backend flow</div>
            <h1>Live Project</h1>
            <p className="report-subtitle">
              Mixed workspace → real Codex Source Scoping → human review → approved-only materialization → report,
              resumed in the same Codex session, backed entirely by the local Bridge process.
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

        {investigationIdentity ? (
          <section className="finding-rail-section live-project-panel" aria-label="Run identity">
            <h3>Run identity</h3>
            <dl className="source-facts">
              <div>
                <dt>Codex session</dt>
                <dd>{shortId(investigationIdentity.codex_session_id)}</dd>
              </div>
              <div>
                <dt>Mixed workspace</dt>
                <dd>{shortId(investigationIdentity.mixed_workspace_fingerprint)}</dd>
              </div>
              {reportingIdentity?.reporting_resumed_retained_session ? (
                <>
                  <div>
                    <dt>Same Codex session resumed</dt>
                    <dd>{shortId(reportingIdentity.codex_session_id)}</dd>
                  </div>
                  <div>
                    <dt>Approved-only workspace</dt>
                    <dd>{shortId(reportingIdentity.approved_workspace_fingerprint)}</dd>
                  </div>
                </>
              ) : null}
            </dl>
          </section>
        ) : null}

        <section className="finding-rail-section live-project-panel">
          <h3>1. Vault</h3>
          <div className="field">
            <label htmlFor="live-password">Vault password</label>
            <input
              id="live-password"
              type="password"
              autoComplete="off"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={busy}
            />
          </div>
          <div className="field">
            <label htmlFor="live-owner">Owner display name (new vault only)</label>
            <input
              id="live-owner"
              type="text"
              value={ownerName}
              onChange={(event) => setOwnerName(event.target.value)}
              disabled={busy}
            />
          </div>
          <div className="live-project-actions">
            <button
              className="primary-button"
              type="button"
              disabled={busy || !runtimeAvailable}
              onClick={() => void createVault()}
            >
              Create new vault…
            </button>
            <button
              className="secondary-button"
              type="button"
              disabled={busy || !runtimeAvailable}
              onClick={() => void unlockVault()}
            >
              Unlock existing vault…
            </button>
          </div>
          {vaultPath ? <p className="live-project-path">Vault: {vaultPath}</p> : null}
        </section>

        {workspaceState ? (
          <section className="finding-rail-section live-project-panel">
            <h3>2. Project</h3>
            <button
              className="primary-button"
              type="button"
              disabled={busy || !runtimeAvailable}
              onClick={() => void pickAndLoadProject()}
            >
              Select project artifact folder…
            </button>
            {artifactRoot ? <p className="live-project-path">Folder: {artifactRoot}</p> : null}
            {workspaceState.project ? (
              <p className="live-project-path">
                Loaded: {workspaceState.project} · {workspaceState.evidence_count} evidence records
              </p>
            ) : null}
          </section>
        ) : null}

        {step !== "setup" ? (
          <section className="finding-rail-section live-project-panel">
            <h3>3. Source Scoping investigation</h3>
            <button className="primary-button" type="button" disabled={busy} onClick={() => void startScoping()}>
              Run real Codex Source Scoping investigation
            </button>
          </section>
        ) : null}

        {scoping ? (
          <section className="finding-rail-section live-project-panel">
            <h3>4. Human review — {scoping.source_scope.decisions.length} sources</h3>
            <p className="report-subtitle">
              Every source needs an explicit human decision. Ambiguous sources are never selected automatically.
            </p>
            <div className="status-list source-review-list">
              {scoping.source_scope.decisions.map((decision) => {
                const citation = scoping.citation_cards.find((card) =>
                  decision.span_ids.includes(card.span_id),
                );
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
                      <strong>{citation?.title ?? "Untitled source"}</strong>
                      <span>
                        model classification: {decision.association_status} ({decision.basis})
                      </span>
                      <span>{decision.rationale}</span>
                    </div>
                    <div className="source-review-controls" role="group" aria-label={`Decision for ${decision.evidence_id}`}>
                      <span className={`status-tag ${statusTone(decision.association_status)}`}>
                        {current ?? "unresolved"}
                      </span>
                      <button
                        type="button"
                        className={current === "included" ? "primary-button" : "secondary-button"}
                        disabled={step !== "reviewing" || busy}
                        onClick={() => setDecision(decision.evidence_id, "included")}
                      >
                        Include
                      </button>
                      <button
                        type="button"
                        className={current === "excluded" ? "primary-button" : "secondary-button"}
                        disabled={step !== "reviewing" || busy}
                        onClick={() => setDecision(decision.evidence_id, "excluded")}
                      >
                        Exclude
                      </button>
                    </div>
                  </section>
                );
              })}
            </div>
            {step === "reviewing" ? (
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

        {confirmed ? (
          <section className="finding-rail-section live-project-panel">
            <h3>5. Approved-only workspace</h3>
            <p className="live-project-path">
              {confirmed.approved_source_scope.approved_evidence_ids.length} sources approved ·{" "}
              {confirmed.approved_source_scope.excluded_evidence_ids.length} excluded · persisted:{" "}
              {String(confirmed.persisted)}
            </p>
            {step === "approved" ? (
              <>
                <div className="field">
                  <label htmlFor="live-question">Question for the resumed Codex session</label>
                  <input
                    id="live-question"
                    type="text"
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    disabled={busy}
                  />
                </div>
                <button className="primary-button" type="button" disabled={busy} onClick={() => void generateReport()}>
                  Generate report (same Codex session, approved workspace only)
                </button>
              </>
            ) : null}
          </section>
        ) : null}

        {step === "reported" && analysis ? (
          <section className="finding-rail-section live-project-panel">
            <h3>6. Project Report</h3>
            {reportError ? (
              <div className="locked-note" role="alert">
                {reportError}
              </div>
            ) : reportDisplay ? (
              <>
                <p className="report-summary">{reportDisplay.summary}</p>
                <div className="status-list">
                  {reportDisplay.sections.map((section) => (
                    <section className="status-row" key={section.key}>
                      <div className="status-label">
                        <span className="status-icon" aria-hidden="true">
                          {section.icon}
                        </span>
                        {section.label}
                      </div>
                      <div className="status-copy">
                        <strong>{section.headline}</strong>
                        <span>{section.detail}</span>
                      </div>
                      <span className={`status-tag ${section.tone === "neutral" ? "" : section.tone}`}>
                        {section.statusLabel}
                      </span>
                    </section>
                  ))}
                </div>

                <section className="finding-rail-section">
                  <h3>Recommended next action</h3>
                  <p>
                    {analysis.next_action?.statement ??
                      "No material continuity break was found; no human action is required."}
                  </p>
                  {analysis.next_action ? <div className="human-required">Human action required</div> : null}
                </section>

                <h3>Evidence inspector</h3>
                {analysis.citation_cards.map((card) => (
                  <article className="source-item" key={card.span_id}>
                    <div className="source-top">
                      <div className="source-heading">
                        <div className="source-meta-row">
                          <span className="source-type">{card.source_type}</span>
                          <span className="citation-chip">{card.evidence_id}</span>
                        </div>
                        <h3>{card.title}</h3>
                      </div>
                      <span className={`status-tag ${card.source_status === "snapshot" ? "verified" : "attention"}`}>
                        {card.source_status === "snapshot" ? "Current" : "Source changed since analysis"}
                      </span>
                    </div>
                    <dl className="source-facts">
                      <div>
                        <dt>Author</dt>
                        <dd>{card.author_or_actor}</dd>
                      </div>
                      <div>
                        <dt>Recorded</dt>
                        <dd>{card.timestamp}</dd>
                      </div>
                    </dl>
                    <blockquote className="source-excerpt">“{card.exact_text}”</blockquote>
                  </article>
                ))}
              </>
            ) : null}
          </section>
        ) : null}
      </div>
    </section>
  );
}
