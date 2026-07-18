import { SYNTHETIC_PROJECTS } from "../data/demoWorkspace";
import type { ProjectKey } from "../types/workspace";

interface WorkspaceProps {
  readonly onOpenProject: (project: ProjectKey) => void;
}

export function Workspace({ onOpenProject }: WorkspaceProps) {
  return (
    <section className="view active" aria-label="Workspace">
      <div className="page-shell workspace-shell">
        <div className="workspace-head">
          <div>
            <div className="eyebrow">Local project hub</div>
            <h1>Workspace</h1>
            <p className="report-subtitle">Open a reconstructed project report. Each report distinguishes confirmed state, continuity issues, and evidence gaps.</p>
          </div>
          <div className="workspace-note">Demonstration workspace · Synthetic production data</div>
        </div>

        <div className="project-list" role="group" aria-label="Projects">
          <button className="project-row featured" type="button" onClick={() => onOpenProject("aurora")}>
            <div className="project-status-mark" aria-hidden="true" />
            <div className="project-main">
              <div className="project-meta"><span>5 verified sources</span><span>Updated today</span></div>
              <h2>Project Aurora</h2>
              <p>Pre-production report with one time-sensitive continuity break.</p>
            </div>
            <div className="project-state">
              <strong>1 issue requires attention</strong>
              <span>Approved location does not match current operational documents.</span>
            </div>
            <div className="open-label">Open current report →</div>
          </button>

          {Object.values(SYNTHETIC_PROJECTS).map((project) => (
            <button className={`project-row ${project.mode}`} type="button" key={project.key} onClick={() => onOpenProject(project.key)}>
              <div className="project-status-mark" aria-hidden="true" />
              <div className="project-main">
                <div className="project-meta"><span>{project.sourceCount} verified sources</span><span>{project.updatedLabel}</span></div>
                <h2>{project.title}</h2>
                <p>{project.subtitle}</p>
              </div>
              <div className="project-state">
                <strong>{project.summaryLabel}</strong>
                <span>{project.workspaceDescription}</span>
              </div>
              <div className="open-label">Open current report →</div>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
