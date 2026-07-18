import type { EvidenceRecord, ProjectKey, SyntheticProjectReport } from "../types/workspace";

interface SourcesDrawerProps {
  readonly open: boolean;
  readonly project: ProjectKey;
  readonly evidence: readonly EvidenceRecord[];
  readonly selectedEvidenceId: string | null;
  readonly syntheticReport: SyntheticProjectReport | undefined;
  readonly onClose: () => void;
}

export function SourcesDrawer({ open, project, evidence, selectedEvidenceId, syntheticReport, onClose }: SourcesDrawerProps) {
  return (
    <aside className={`drawer right ${open ? "open" : ""}`} aria-hidden={!open} aria-label="Verified sources">
      <div className="drawer-head">
        <h2>{project === "aurora" ? `${evidence.length} verified sources` : `${syntheticReport?.sourceCount ?? 0} verified sources`}</h2>
        <button className="close" type="button" onClick={onClose} aria-label="Close verified sources">×</button>
      </div>
      <div className="drawer-body">
        {project === "aurora" ? evidence.map((item) => (
          <article className={`source-item ${selectedEvidenceId === item.id ? "selected" : ""}`} key={item.id}>
            <div className="source-top">
              <div><span className="source-type">{item.type}</span><h3>{item.title}</h3></div>
              <span className="status-tag verified">Verified</span>
            </div>
            <p>“{item.quote}”</p>
            <details open={selectedEvidenceId === item.id}>
              <summary>Source details</summary>
              <div className="source-details">{item.author}<br />{item.timestamp}<br />{item.filename}<br />{item.id}</div>
            </details>
          </article>
        )) : (
          <>
            <p className="drawer-intro">This synthetic report demonstrates the project-level flow. Project Aurora is the fully grounded competition scenario with record-level evidence inspection.</p>
            {syntheticReport?.rows.map((row, index) => (
              <article className="source-item" key={`${row.label}-${index}`}>
                <div className="source-top">
                  <div><span className="source-type">S{String(index + 1).padStart(2, "0")}</span><h3>{row.label} source set</h3></div>
                  <span className={`status-tag ${row.tone === "gap" ? "gap" : "verified"}`}>{row.status}</span>
                </div>
                <p>{row.description}</p>
              </article>
            ))}
          </>
        )}
      </div>
    </aside>
  );
}
