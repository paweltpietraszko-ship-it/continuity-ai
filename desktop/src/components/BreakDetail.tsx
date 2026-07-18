import type { AuthenticatedAttestation, EvidenceRecord } from "../types/workspace";

interface BreakDetailProps {
  readonly evidence: readonly EvidenceRecord[];
  readonly attestations: readonly AuthenticatedAttestation[];
  readonly onBack: () => void;
  readonly onOpenEvidence: (evidenceId: string) => void;
  readonly onOpenConversation: () => void;
}

function EvidenceCard({ record, tone, onOpen }: { readonly record: EvidenceRecord; readonly tone: string; readonly onOpen: () => void }) {
  return (
    <button className={`evidence-card ${tone}`} type="button" onClick={onOpen}>
      <span className="evidence-role">{record.role}</span>
      <h4>{record.type === "EML" ? "Investor approval" : record.type === "XLSX" ? "Budget v4" : record.type === "ICS" ? "Production calendar" : record.type === "PDF" ? "Current call sheet" : record.title}</h4>
      <blockquote>“{record.quote}”</blockquote>
      <div className="evidence-meta">{record.author} · {record.time}</div>
    </button>
  );
}

export function BreakDetail({ evidence, attestations, onBack, onOpenEvidence, onOpenConversation }: BreakDetailProps) {
  const byId = new Map(evidence.map((record) => [record.id, record]));
  const approval = byId.get("EV-AUR-001");
  const budget = byId.get("EV-AUR-003");
  const calendar = byId.get("EV-AUR-002");
  const callSheet = byId.get("EV-AUR-004");

  if (!approval || !budget || !calendar || !callSheet) {
    throw new Error("Project Aurora evidence fixture is incomplete.");
  }

  return (
    <section className="view active" aria-label="Location continuity break detail">
      <div className="detail-shell">
        <div className="detail-head">
          <div>
            <div className="eyebrow">Project Aurora · Attention item</div>
            <h1>Location continuity break</h1>
            <p className="report-subtitle">How the approved move to Northlight Studio failed to become operational reality.</p>
          </div>
          <button className="back-report" type="button" onClick={onBack}>← Current report</button>
        </div>

        <div className="detail-grid">
          <article className="reconstruction">
            <div className="reconstruction-head">
              <div className="eyebrow">Evidence reconstruction</div>
              <h2>Decision propagation</h2>
              <p>The records are grouped by meaning. Timestamps remain secondary source metadata.</p>
            </div>

            <section className="state-group">
              <div className="group-title"><h3>Approved project state</h3><strong>Northlight Studio</strong></div>
              <div className="evidence-grid">
                <EvidenceCard record={approval} tone="approved" onOpen={() => onOpenEvidence(approval.id)} />
                <EvidenceCard record={budget} tone="partial" onOpen={() => onOpenEvidence(budget.id)} />
              </div>
            </section>

            <div className="break-band">
              <div className="break-symbol">!</div>
              <div><strong>Continuity break</strong><span>The approved state is not reflected in the later operational documents.</span></div>
            </div>

            <section className="state-group">
              <div className="group-title"><h3>Current operational reality</h3><strong>Harbor House</strong></div>
              <div className="evidence-grid">
                <EvidenceCard record={calendar} tone="stale" onOpen={() => onOpenEvidence(calendar.id)} />
                <EvidenceCard record={callSheet} tone="stale" onOpen={() => onOpenEvidence(callSheet.id)} />
              </div>
            </section>

            {attestations.length > 0 ? (
              <section className="state-group">
                <div className="group-title"><h3>Additional provenance</h3><strong>Authenticated owner</strong></div>
                <div className="evidence-grid">
                  {attestations.map((attestation) => (
                    <EvidenceCard key={attestation.id} record={attestation} tone="attestation" onOpen={() => onOpenEvidence(attestation.id)} />
                  ))}
                </div>
              </section>
            ) : null}
          </article>

          <aside className="detail-side">
            <section className="side-section prominent">
              <h3>Continuity break</h3>
              <p>The approved location change is reflected in the budget but not in the production calendar or current call sheet.</p>
            </section>
            <section className="side-section subdued">
              <h3>Sources</h3>
              <div className="citation-list">
                <button className="citation" type="button" onClick={() => onOpenEvidence("EV-AUR-001")}>Investor approval</button>
                <button className="citation" type="button" onClick={() => onOpenEvidence("EV-AUR-003")}>Budget v4</button>
                <button className="citation" type="button" onClick={() => onOpenEvidence("EV-AUR-002")}>Calendar</button>
                <button className="citation" type="button" onClick={() => onOpenEvidence("EV-AUR-004")}>Call sheet</button>
              </div>
            </section>
            <section className="side-section subdued">
              <h3>Why this matters now</h3>
              <p>Crew briefing tomorrow.</p>
            </section>
            <section className="side-section prominent">
              <h3>Next action</h3>
              <p>Update the production calendar and call sheet before tomorrow’s crew briefing.</p>
              <div className="human-required">Human action required</div>
            </section>
            <button className="primary-button" type="button" onClick={onOpenConversation}>Ask Continuity</button>
          </aside>
        </div>
      </div>
    </section>
  );
}
