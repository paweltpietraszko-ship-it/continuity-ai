import { AURORA_STATUS_ROWS } from "../data/demoWorkspace";
import type { BridgeBootstrapState } from "../bridge/bootstrap";
import { FindingRail } from "./FindingRail";
import { PresentationState } from "./PresentationState";
import { presentationStateForBootstrap } from "./presentationStateForBootstrap";
import { ReportQuestions } from "./ReportQuestions";
import { StatusList } from "./StatusList";

interface AuroraReportProps {
  readonly sourceCount: number;
  readonly bootstrap: BridgeBootstrapState;
  readonly onOpenSources: () => void;
  readonly onOpenConversation: () => void;
  readonly onReviewBreak: () => void;
}

export function AuroraReport({
  sourceCount,
  bootstrap,
  onOpenSources,
  onOpenConversation,
  onReviewBreak,
}: AuroraReportProps) {
  const presentationState = presentationStateForBootstrap(bootstrap.mode);

  return (
    <section className="view active" aria-label="Project Aurora current report">
      <div className="page-shell">
        <PresentationState state={presentationState} />

        <header className="report-head">
          <div className="report-title-block">
            <div className="report-title-row">
              <div className="eyebrow">Current Report</div>
              <span className="project-badge">Synthetic demo project</span>
            </div>
            <h1>Project Aurora</h1>
            <p className="overall-status" role="status">
              <span className="overall-status-mark attention" aria-hidden="true" />
              Attention required · Crew briefing tomorrow
            </p>
          </div>
          <div className="report-tools">
            <button className="tool-button" type="button" onClick={onOpenSources}>
              <span className="count">{sourceCount}</span>
              Evidence inspector ›
            </button>
            <button className="tool-button" type="button" onClick={onOpenConversation} aria-label="Ask Continuity">
              Ask Continuity
            </button>
          </div>
        </header>

        <section className="dominant-finding" aria-label="Primary continuity finding">
          <h2>The approved location change reached the budget, but not the production calendar or current call sheet.</h2>
          <p>Casting and performer agreements cannot be verified from the current artifact set.</p>
        </section>

        <ReportQuestions />

        <div className="report-grid">
          <article className="report-paper">
            <header className="report-sections-head">
              <div className="eyebrow">Report sections</div>
              <h2>Project state by domain</h2>
            </header>
            <StatusList rows={AURORA_STATUS_ROWS} />
          </article>

          <FindingRail onReviewBreak={onReviewBreak} onOpenConversation={onOpenConversation} />
        </div>
      </div>
    </section>
  );
}
