import type { SyntheticProjectReport } from "../types/workspace";
import { StatusList } from "./StatusList";

interface GenericReportProps {
  readonly report: SyntheticProjectReport;
  readonly onOpenSources: () => void;
}

export function GenericReport({ report, onOpenSources }: GenericReportProps) {
  return (
    <section className="view active" aria-label={`${report.title} current report`}>
      <div className="page-shell">
        <div className="report-head">
          <div>
            <div className="eyebrow">Current project report</div>
            <h1>{report.title}</h1>
            <p className="report-subtitle">{report.subtitle}</p>
          </div>
          <div className="report-tools">
            <button className="tool-button" type="button" onClick={onOpenSources}>
              <span className="count">{report.sourceCount}</span> verified sources ›
            </button>
          </div>
        </div>

        <div className="report-grid">
          <article className="report-paper">
            <section className="report-summary">
              <div className="eyebrow">Where the project stands</div>
              <h2>{report.summary}</h2>
              <p>{report.detail}</p>
            </section>
            <StatusList rows={report.rows} />
          </article>
          <aside className={`generic-attention ${report.mode}`}>
            <div className="eyebrow">Current finding</div>
            <h2>{report.sideTitle}</h2>
            <p>{report.sideCopy}</p>
            <div className="mini-list">
              {report.mode === "on-track" ? (
                <>
                  <div className="mini-item"><strong>Decision path aligned</strong><span>Approvals and operating documents support the same current state.</span></div>
                  <div className="mini-item"><strong>No manual correction required</strong><span>The report contains no grounded continuity break.</span></div>
                </>
              ) : (
                <>
                  <div className="mini-item"><strong>Conclusion withheld</strong><span>Continuity AI does not fill evidence gaps with assumptions.</span></div>
                  <div className="mini-item"><strong>Next step</strong><span>Add current casting, agreements, and location-readiness records.</span></div>
                </>
              )}
            </div>
          </aside>
        </div>
        <p className="report-footnote">Demonstration workspace · Synthetic production data</p>
      </div>
    </section>
  );
}
