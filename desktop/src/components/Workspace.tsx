import { SYNTHETIC_PROJECTS } from "../data/demoWorkspace";
import type { ProjectKey } from "../types/workspace";

interface WorkspaceProps {
  readonly onOpenProject: (project: ProjectKey) => void;
  readonly onOpenLiveProject: () => void;
}

export function Workspace({ onOpenProject, onOpenLiveProject }: WorkspaceProps) {
  return (
    <section className="view active" aria-label="Workspace">
      <div className="page-shell workspace-shell">
        <div className="workspace-head">
          <div>
            <div className="eyebrow">Local project hub</div>
            <h1>Workspace</h1>
            <p className="report-subtitle">Open a reconstructed project report. Each report distinguishes confirmed state, continuity issues, and evidence gaps.</p>
          </div>
          <div className="workspace-note">Demonstration workspace · preview data only</div>
        </div>

        <button className="project-row live-project-row" type="button" onClick={onOpenLiveProject}>
          <div className="project-status-mark" aria-hidden="true" />
          <div className="project-main">
            <div className="project-meta"><span>Real local Bridge</span><span>Genuine Codex session</span></div>
            <h2>Live Project</h2>
            <p>Load any project artifact folder and run the real mixed → review → approved-only → report flow.</p>
          </div>
          <div className="project-state">
            <strong>Backed by the local Bridge process</strong>
            <span>No synthetic data — every screen reflects real backend responses.</span>
          </div>
          <div className="open-label">Open live flow →</div>
        </button>

        <div className="project-list" role="group" aria-label="Projects">
          <button className="project-row featured" type="button" onClick={() => onOpenProject("aurora")}>
            <div className="project-status-mark" aria-hidden="true" />
            <div className="project-main">
              <div className="project-meta"><span>5 source records</span><span>Synthetic demo project</span></div>
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
