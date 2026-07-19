import { useEffect, useMemo, useRef, useState } from "react";

import { AppHeader } from "./components/AppHeader";
import { AuroraReport } from "./components/AuroraReport";
import { BreakDetail } from "./components/BreakDetail";
import { ConversationDrawer } from "./components/ConversationDrawer";
import { GenericReport } from "./components/GenericReport";
import { LiveProjectFlow } from "./components/LiveProjectFlow";
import { SourcesDrawer } from "./components/SourcesDrawer";
import { VaultOverlay } from "./components/VaultOverlay";
import { Workspace } from "./components/Workspace";
import type { BridgeBootstrapState } from "./bridge/bootstrap";
import { AURORA_EVIDENCE, SYNTHETIC_PROJECTS } from "./data/demoWorkspace";
import { FilmDemoDirector } from "./demo/FilmDemoDirector";
import { filmDemoConfig } from "./demo/filmDemoEnv";
import type {
  AuthenticatedAttestation,
  ConversationMessage,
  DrawerName,
  ProjectKey,
  ViewName,
} from "./types/workspace";

const DEFAULT_BOOTSTRAP: BridgeBootstrapState = { mode: "browser_demo" };

const INITIAL_MESSAGES: readonly ConversationMessage[] = [
  {
    id: "message-initial",
    author: "agent",
    text: "Ask about the current project report, the identified discrepancy, or add a statement to the project record.",
  },
];

function initialRoute(): { view: ViewName; project: ProjectKey } {
  // The Film Demo Director is a fully separate, explicit-flag-only mode: a
  // launch with CONTINUITY_FILM_DEMO=1 fully configured always opens
  // straight into it, regardless of the current hash.
  if (filmDemoConfig()) return { view: "filmDemo", project: "aurora" };
  const hash = window.location.hash.replace("#", "");
  if (hash === "workspace") return { view: "workspace", project: "aurora" };
  if (hash === "live-project") return { view: "liveProject", project: "aurora" };
  if (hash === "film-demo") return { view: "filmDemo", project: "aurora" };
  if (hash === "aurora-break") return { view: "breakDetail", project: "aurora" };
  if (hash === "meridian" || hash === "ember") return { view: "genericReport", project: hash };
  return { view: "auroraReport", project: "aurora" };
}

function routeHash(view: ViewName, project: ProjectKey): string {
  if (view === "workspace") return "workspace";
  if (view === "liveProject") return "live-project";
  if (view === "filmDemo") return "film-demo";
  if (view === "breakDetail") return "aurora-break";
  if (view === "genericReport") return project;
  return "aurora";
}

interface AppProps {
  readonly bootstrap?: BridgeBootstrapState;
}

export function App({ bootstrap = DEFAULT_BOOTSTRAP }: AppProps) {
  const [initial] = useState(initialRoute);
  const [view, setView] = useState<ViewName>(initial.view);
  const [project, setProject] = useState<ProjectKey>(initial.project);
  const [drawer, setDrawer] = useState<DrawerName>(null);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  const [vaultUnlocked, setVaultUnlocked] = useState(true);
  const [pendingAttestation, setPendingAttestation] = useState<string | null>(null);
  const [attestations, setAttestations] = useState<readonly AuthenticatedAttestation[]>([]);
  const [messages, setMessages] = useState<readonly ConversationMessage[]>(INITIAL_MESSAGES);
  const [toast, setToast] = useState<string | null>(null);
  const messageCounter = useRef(1);
  const attestationCounter = useRef(1);

  const evidence = useMemo(() => [...AURORA_EVIDENCE, ...attestations], [attestations]);
  const syntheticReport = project === "aurora" ? undefined : SYNTHETIC_PROJECTS[project];

  useEffect(() => {
    window.history.replaceState(null, "", `#${routeHash(view, project)}`);
  }, [view, project]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 2800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent): void {
      if (event.key === "Escape") setDrawer(null);
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, []);

  function navigate(nextView: ViewName, nextProject: ProjectKey = project): void {
    setView(nextView);
    setProject(nextProject);
    setDrawer(null);
    setSelectedEvidenceId(null);
  }

  if (view === "filmDemo") {
    const config = filmDemoConfig();
    // Every hook above has already run unconditionally; only the returned
    // JSX branches here. The Director owns its whole screen -- no demo
    // header, drawers, or vault overlay from the synthetic Aurora shell.
    if (config) {
      return <FilmDemoDirector config={config} onExit={() => navigate("workspace", "aurora")} />;
    }
  }

  function openProject(nextProject: ProjectKey): void {
    if (nextProject === "aurora") navigate("auroraReport", "aurora");
    else navigate("genericReport", nextProject);
  }

  function openSources(evidenceId: string | null = null): void {
    setSelectedEvidenceId(evidenceId);
    setDrawer("sources");
  }

  function openConversation(): void {
    setDrawer("conversation");
  }

  function appendMessage(message: Omit<ConversationMessage, "id">): void {
    messageCounter.current += 1;
    setMessages((current) => [...current, { ...message, id: `message-${messageCounter.current}` }]);
  }

  function sendMessage(text: string): void {
    appendMessage({ author: "user", text });

    const attestationMatch = text.match(/(?:add|record|save)(?: this)?(?: statement)?(?: to the project record)?[:\s-]*(.*)/i);
    if (attestationMatch?.[1]?.trim()) {
      setPendingAttestation(attestationMatch[1].trim());
      return;
    }

    if (/where|stand|status|project/i.test(text)) {
      appendMessage({
        author: "agent",
        text: "Project Aurora is approaching tomorrow’s crew briefing. The move to Northlight Studio is approved and reflected in Budget v4, but the production calendar and current call sheet still show Harbor House. Casting and performer agreements cannot be verified from the current source set.",
        citations: ["EV-AUR-001", "EV-AUR-003", "EV-AUR-002", "EV-AUR-004", "EV-AUR-005"],
      });
      return;
    }

    if (/why|evidence|source|location|harbor|northlight/i.test(text)) {
      appendMessage({
        author: "agent",
        text: "The investor approval and Budget v4 support Northlight Studio. The later production calendar and current call sheet both still state Harbor House.",
        citations: ["EV-AUR-001", "EV-AUR-003", "EV-AUR-002", "EV-AUR-004"],
      });
      return;
    }

    appendMessage({
      author: "agent",
      text: "I can explain the current report, trace a conclusion to its sources, or prepare a statement for this preview's demo attestation flow.",
    });
  }

  function confirmAttestation(): void {
    if (!pendingAttestation) return;
    if (!vaultUnlocked) {
      setPendingAttestation(null);
      setToast("Attestation not added. Unlock the local vault and propose it again.");
      return;
    }

    const now = new Date();
    const id = `EV-AUR-ATT-${String(attestationCounter.current).padStart(3, "0")}`;
    attestationCounter.current += 1;
    const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const attestation: AuthenticatedAttestation = {
      id,
      type: "TEXT",
      title: "Demo attestation (preview only)",
      author: "Demo owner · Paweł",
      time,
      timestamp: now.toISOString(),
      filename: "Continuity AI",
      quote: pendingAttestation,
      role: "Demo attestation (preview only)",
    };

    setAttestations((current) => [...current, attestation]);
    setPendingAttestation(null);
    appendMessage({
      author: "agent",
      text: "This demo attestation was added to the local preview only. It was not sent to a backend or persisted.",
      citations: [id],
    });
    setToast("Demo attestation added to this preview only. It was not persisted.");
  }

  function cancelAttestation(): void {
    setPendingAttestation(null);
    appendMessage({ author: "agent", text: "The pending attestation was cancelled. No evidence was added." });
  }

  function lockVault(): void {
    setVaultUnlocked(false);
    setPendingAttestation(null);
    setDrawer(null);
    setToast("Demo vault view locked locally. Pending proposals were removed.");
  }

  function unlockVault(): void {
    setVaultUnlocked(true);
    setToast("Demo vault view unlocked locally.");
  }

  return (
    <div className="app">
      <AppHeader
        project={project}
        view={view}
        vaultUnlocked={vaultUnlocked}
        bootstrap={bootstrap}
        onOpenWorkspace={() => navigate("workspace", project)}
        onLockVault={lockVault}
      />

      <main className="main">
        {view === "auroraReport" ? (
          <AuroraReport
            sourceCount={evidence.length}
            bootstrap={bootstrap}
            onOpenSources={() => openSources()}
            onOpenConversation={openConversation}
            onReviewBreak={() => navigate("breakDetail", "aurora")}
          />
        ) : null}
        {view === "workspace" ? (
          <Workspace onOpenProject={openProject} onOpenLiveProject={() => navigate("liveProject", project)} />
        ) : null}
        {view === "liveProject" ? <LiveProjectFlow onBack={() => navigate("workspace", project)} /> : null}
        {view === "breakDetail" ? (
          <BreakDetail
            evidence={evidence}
            attestations={attestations}
            onBack={() => navigate("auroraReport", "aurora")}
            onOpenEvidence={(id) => openSources(id)}
            onOpenConversation={openConversation}
          />
        ) : null}
        {view === "genericReport" && syntheticReport ? (
          <GenericReport report={syntheticReport} onOpenSources={() => openSources()} />
        ) : null}
      </main>

      <div className={`scrim ${drawer ? "open" : ""}`} onClick={() => setDrawer(null)} aria-hidden="true" />

      <SourcesDrawer
        open={drawer === "sources"}
        project={project}
        evidence={evidence}
        selectedEvidenceId={selectedEvidenceId}
        syntheticReport={syntheticReport}
        onClose={() => setDrawer(null)}
      />

      <ConversationDrawer
        open={drawer === "conversation"}
        messages={messages}
        evidence={evidence}
        pendingAttestation={pendingAttestation}
        vaultUnlocked={vaultUnlocked}
        onClose={() => setDrawer(null)}
        onSend={sendMessage}
        onOpenEvidence={(id) => openSources(id)}
        onConfirmAttestation={confirmAttestation}
        onCancelAttestation={cancelAttestation}
      />

      <VaultOverlay open={!vaultUnlocked} onUnlock={unlockVault} />
      <div className={`toast ${toast ? "show" : ""}`} role="status" aria-live="polite">{toast}</div>
    </div>
  );
}
