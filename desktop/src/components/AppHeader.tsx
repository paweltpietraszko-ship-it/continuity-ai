import type { ProjectKey, ViewName } from "../types/workspace";
import { SYNTHETIC_PROJECTS } from "../data/demoWorkspace";

interface AppHeaderProps {
  readonly project: ProjectKey;
  readonly view: ViewName;
  readonly vaultUnlocked: boolean;
  readonly onOpenWorkspace: () => void;
  readonly onLockVault: () => void;
}

function projectLabel(project: ProjectKey): string {
  if (project === "aurora") return "Project Aurora";
  return SYNTHETIC_PROJECTS[project].title;
}

function viewLabel(view: ViewName): string {
  if (view === "workspace") return "Local projects";
  if (view === "breakDetail") return "Location Continuity Break";
  return "Current Report";
}

export function AppHeader({ project, view, vaultUnlocked, onOpenWorkspace, onLockVault }: AppHeaderProps) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true" />
        <span>Continuity AI</span>
      </div>

      <div className="context-line">
        {view !== "workspace" ? (
          <>
            <button className="crumb-button" type="button" onClick={onOpenWorkspace}>
              ← Workspace
            </button>
            <span aria-hidden="true">/</span>
          </>
        ) : null}
        <strong>{view === "workspace" ? "Workspace" : projectLabel(project)}</strong>
        <span>{viewLabel(view)}</span>
      </div>

      <div className="owner">
        <div className="owner-copy">
          <strong>Paweł</strong>
          <span>{vaultUnlocked ? "Vault unlocked" : "Vault locked"}</span>
        </div>
        <div className="avatar" aria-hidden="true">P</div>
        <button className="lock-button" type="button" onClick={onLockVault} disabled={!vaultUnlocked}>
          Lock vault
        </button>
      </div>
    </header>
  );
}
