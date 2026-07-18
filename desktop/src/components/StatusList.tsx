import type { StatusRow } from "../types/workspace";

interface StatusListProps {
  readonly rows: readonly StatusRow[];
}

export function StatusList({ rows }: StatusListProps) {
  return (
    <div className="status-list">
      {rows.map((row) => (
        <section className="status-row" key={row.label}>
          <div className="status-label">
            <span className="status-icon" aria-hidden="true">{row.icon}</span>
            {row.label}
          </div>
          <div className="status-copy">
            <strong>{row.title}</strong>
            <span>{row.description}</span>
          </div>
          <span className={`status-tag ${row.tone === "neutral" ? "" : row.tone}`}>{row.status}</span>
        </section>
      ))}
    </div>
  );
}
