interface FindingRailProps {
  readonly onReviewBreak: () => void;
  readonly onOpenConversation: () => void;
}

export function FindingRail({ onReviewBreak, onOpenConversation }: FindingRailProps) {
  return (
    <aside className="finding-rail" aria-label="Continuity finding">
      <div className="finding-rail-head">
        <div className="eyebrow">Continuity finding</div>
        <h2>Location continuity break</h2>
      </div>

      <div className="state-compare" aria-label="Approved project state versus operational reality">
        <div className="state-compare-block approved">
          <span className="state-compare-label">Approved project state</span>
          <strong>Northlight Studio</strong>
        </div>
        <div className="state-compare-divider" aria-hidden="true">
          <span>≠</span>
        </div>
        <div className="state-compare-block operational">
          <span className="state-compare-label">Operational reality</span>
          <strong>Harbor House</strong>
        </div>
      </div>

      <div className="finding-rail-body">
        <section className="finding-rail-section">
          <h3>Recommended next action</h3>
          <p>Update the production calendar and call sheet before tomorrow’s crew briefing.</p>
          <div className="human-required">Human action required</div>
        </section>

        <div className="finding-rail-actions">
          <button className="primary-button" type="button" onClick={onReviewBreak}>
            Review continuity break
          </button>
          <button className="secondary-button" type="button" onClick={onOpenConversation}>
            Open conversation
          </button>
        </div>
      </div>
    </aside>
  );
}
