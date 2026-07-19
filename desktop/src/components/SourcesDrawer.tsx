import type { EvidenceRecord, ProjectKey, SyntheticProjectReport } from "../types/workspace";

interface SourcesDrawerProps {
  readonly open: boolean;
  readonly project: ProjectKey;
  readonly evidence: readonly EvidenceRecord[];
  readonly selectedEvidenceId: string | null;
  readonly syntheticReport: SyntheticProjectReport | undefined;
  readonly onClose: () => void;
}

function formatEvidenceDate(timestamp: string, time: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return time;
  return `${parsed.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })} · ${time}`;
}

function sourceStatusLabel(record: EvidenceRecord): string {
  if (record.role?.toLowerCase().includes("gap")) return "Evidence gap";
  if (record.role?.toLowerCase().includes("still")) return "Stale relative to approval";
  if (record.role?.toLowerCase().includes("approved") || record.role?.toLowerCase().includes("updated")) {
    return "Supports current finding";
  }
  return record.role ?? "Source on file";
}

export function SourcesDrawer({
  open,
  project,
  evidence,
  selectedEvidenceId,
  syntheticReport,
  onClose,
}: SourcesDrawerProps) {
  const presentationState = selectedEvidenceId ? "citation_selected" : "source_review_required";

  return (
    <aside
      className={`drawer right evidence-inspector ${open ? "open" : ""}`}
      aria-hidden={!open}
      aria-label="Evidence inspector"
    >
      <div className="drawer-head">
        <div>
          <div className="eyebrow">Evidence inspector</div>
          <h2>
            {project === "aurora"
              ? `${evidence.length} source records`
              : `${syntheticReport?.sourceCount ?? 0} source records`}
          </h2>
        </div>
        <button className="close" type="button" onClick={onClose} aria-label="Close evidence inspector">
          ×
        </button>
      </div>
      <div className="drawer-body">
        <p className={`inspector-state ${presentationState}`} role="status">
          {selectedEvidenceId
            ? "Citation selected · matching source record highlighted below"
            : "Review source records to trace report citations"}
        </p>

        {project === "aurora" ? (
          evidence.map((item) => (
            <article
              className={`source-item ${selectedEvidenceId === item.id ? "selected" : ""}`}
              key={item.id}
              id={`evidence-${item.id}`}
            >
              <div className="source-top">
                <div className="source-heading">
                  <div className="source-meta-row">
                    <span className="source-type">{item.type}</span>
                    <span className="citation-chip">{item.id}</span>
                  </div>
                  <h3>{item.title}</h3>
                </div>
                <span className="status-tag verified">{sourceStatusLabel(item)}</span>
              </div>

              <dl className="source-facts">
                <div>
                  <dt>File</dt>
                  <dd>{item.filename}</dd>
                </div>
                <div>
                  <dt>Recorded</dt>
                  <dd>{formatEvidenceDate(item.timestamp, item.time)}</dd>
                </div>
                <div>
                  <dt>Author</dt>
                  <dd>{item.author}</dd>
                </div>
              </dl>

              <blockquote className="source-excerpt">“{item.quote}”</blockquote>
            </article>
          ))
        ) : (
          <>
            <p className="drawer-intro">
              This synthetic report demonstrates the project-level flow. Project Aurora is the full competition scenario with record-level evidence inspection.
            </p>
            {syntheticReport?.rows.map((row, index) => (
              <article className="source-item" key={`${row.label}-${index}`}>
                <div className="source-top">
                  <div className="source-heading">
                    <div className="source-meta-row">
                      <span className="source-type">S{String(index + 1).padStart(2, "0")}</span>
                    </div>
                    <h3>{row.label} source set</h3>
                  </div>
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
