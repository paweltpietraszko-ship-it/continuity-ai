import type { ProjectKey, ViewName } from "../types/workspace";
import { SYNTHETIC_PROJECTS } from "../data/demoWorkspace";
import { bridgeStatusLabel, type BridgeBootstrapState } from "../bridge/bootstrap";

interface AppHeaderProps {
  readonly project: ProjectKey;
  readonly view: ViewName;
  readonly vaultUnlocked: boolean;
  readonly bootstrap: BridgeBootstrapState;
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

export function AppHeader({ project, view, vaultUnlocked, bootstrap, onOpenWorkspace, onLockVault }: AppHeaderProps) {
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
        <span className="demo-banner">Demonstration workspace · Synthetic production data</span>
      </div>

      <div className="owner">
        <div className="owner-copy">
          <strong>Local owner</strong>
          <span>{vaultUnlocked ? "Demo vault view unlocked" : "Demo vault view locked"}</span>
          <span className="bridge-status">{bridgeStatusLabel(bootstrap)}</span>
        </div>
        <div className="avatar" aria-hidden="true">L</div>
        <button className="lock-button" type="button" onClick={onLockVault} disabled={!vaultUnlocked}>
          Lock vault
        </button>
      </div>
    </header>
  );
}
