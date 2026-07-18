import { AURORA_STATUS_ROWS } from "../data/demoWorkspace";
import { StatusList } from "./StatusList";

interface AuroraReportProps {
  readonly sourceCount: number;
  readonly onOpenSources: () => void;
  readonly onOpenConversation: () => void;
  readonly onReviewBreak: () => void;
}

export function AuroraReport({ sourceCount, onOpenSources, onOpenConversation, onReviewBreak }: AuroraReportProps) {
  return (
    <section className="view active" aria-label="Project Aurora current report">
      <div className="page-shell">
        <div className="report-head">
          <div>
            <div className="eyebrow">Current project report</div>
            <h1>Project Aurora</h1>
            <p className="report-subtitle">
              A verified summary of what is current, what remains unknown, and what requires attention before the next production milestone.
            </p>
          </div>
          <div className="report-tools">
            <button className="tool-button" type="button" onClick={onOpenSources}>
              <span className="count">{sourceCount}</span> verified sources ›
            </button>
            <button className="tool-button" type="button" onClick={onOpenConversation}>Ask Continuity</button>
          </div>
        </div>

        <div className="report-grid">
          <article className="report-paper">
            <section className="report-summary">
              <div className="eyebrow">Where the project stands</div>
              <h2>The location change is approved and reflected in Budget v4. The production calendar and current call sheet have not been updated.</h2>
              <p>The crew briefing is tomorrow. Casting and performer agreements cannot be verified from the current artifact set.</p>
            </section>
            <StatusList rows={AURORA_STATUS_ROWS} />
          </article>

          <aside className="attention-panel">
            <div className="attention-top">
              <div className="eyebrow">Attention required</div>
              <h2>Location continuity break</h2>
              <p>An approved project decision did not reach the documents the crew is working from.</p>
            </div>
            <div className="mismatch">
              <div className="mismatch-state"><small>Approved</small><strong>Northlight Studio</strong></div>
              <div className="mismatch-symbol" aria-hidden="true">≠</div>
              <div className="mismatch-state"><small>Operational</small><strong>Harbor House</strong></div>
            </div>
            <div className="attention-body">
              <p className="finding-statement">The approved location change reached the budget, but not the production calendar or current call sheet.</p>
              <div className="next-action">
                <h3>Next action</h3>
                <p>Update the production calendar and call sheet before tomorrow’s crew briefing.</p>
                <div className="human-required">Human action required</div>
              </div>
              <div className="attention-actions">
                <button className="primary-button" type="button" onClick={onReviewBreak}>Review continuity break</button>
                <button className="secondary-button" type="button" onClick={onOpenConversation}>Continue conversation</button>
              </div>
            </div>
          </aside>
        </div>
        <p className="report-footnote">Demonstration workspace · Synthetic production data</p>
      </div>
    </section>
  );
}
