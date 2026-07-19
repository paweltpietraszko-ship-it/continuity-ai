import { createRef } from "react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { desktopBridge } from "../bridge/client";
import type {
  BridgeCommand,
  BridgeCommandResultMap,
  ScopeProjectSourcesData,
  WorkspaceState,
} from "../bridge/contracts";
import * as dialogs from "../bridge/dialogs";
import type { FilmDemoConfig } from "../demo/filmDemoEnv";
import { LiveProjectFlow, type LiveProjectFlowHandle } from "./LiveProjectFlow";

const EMPTY_STATE: WorkspaceState = {
  vault_unlocked: true,
  owner_display_name: "Demo Owner",
  project: null,
  artifact_evidence_count: 0,
  evidence_count: 0,
  evidence_records: [],
  has_analysis: false,
  retained_analysis_status: "none",
  project_report: null,
  pending_attestation_count: 0,
  pending_revision_count: 0,
};

const DEMO_CONFIG: FilmDemoConfig = {
  artifactRoot: "C:/demo/aurora",
  vaultPath: "C:/demo/vault",
  ownerName: "Demo Owner",
  question: "What is the current project state?",
  password: "demo-password",
};

const SCOPING_RESULT: ScopeProjectSourcesData = {
  project: "Project Aurora",
  source_scope: {
    schema_version: "1.0",
    target_project: "Project Aurora",
    anchor_evidence_ids: ["EV-1"],
    decisions: [
      {
        evidence_id: "EV-1",
        association_status: "included",
        basis: "explicit_target",
        rationale: "Explicitly names Project Aurora.",
        span_ids: [],
        related_evidence_ids: [],
      },
      {
        evidence_id: "EV-2",
        association_status: "excluded",
        basis: "explicit_other_project",
        rationale: "Explicitly names a different project.",
        span_ids: [],
        related_evidence_ids: [],
      },
      {
        evidence_id: "EV-3",
        association_status: "ambiguous",
        basis: "insufficient_context",
        rationale: "Not enough context.",
        span_ids: [],
        related_evidence_ids: [],
      },
    ],
    selected_evidence_ids: ["EV-1"],
    ambiguous_evidence_ids: ["EV-3"],
    excluded_evidence_ids: ["EV-2"],
  },
  citation_cards: [],
};

function mockBridgeSuccess(): void {
  vi.spyOn(desktopBridge, "start").mockResolvedValue({ running: true, process_id: 1 });
  vi.spyOn(desktopBridge, "request").mockImplementation(
    async <TCommand extends BridgeCommand>(
      command: TCommand,
    ): Promise<BridgeCommandResultMap[TCommand["command"]]> => {
      if (command.command === "get_workspace_state") {
        return EMPTY_STATE as BridgeCommandResultMap[TCommand["command"]];
      }
      if (command.command === "initialize_vault") {
        return { session_id: "SES-demo", owner_display_name: "Demo Owner" } as BridgeCommandResultMap[TCommand["command"]];
      }
      if (command.command === "load_project") {
        return {
          project: "Project Aurora",
          artifact_evidence_count: 5,
          evidence_count: 5,
          evidence_records: [],
        } as unknown as BridgeCommandResultMap[TCommand["command"]];
      }
      if (command.command === "scope_project_sources") {
        return SCOPING_RESULT as BridgeCommandResultMap[TCommand["command"]];
      }
      throw new Error(`Unexpected command in test: ${command.command}`);
    },
  );
}

beforeEach(() => {
  (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
});

describe("LiveProjectFlow imperative handle", () => {
  it("never exposes a way to confirm or approve the source scope", () => {
    mockBridgeSuccess();
    const ref = createRef<LiveProjectFlowHandle>();
    render(<LiveProjectFlow ref={ref} onBack={() => {}} demoConfig={DEMO_CONFIG} filmDemoMode />);

    expect(ref.current).not.toBeNull();
    const exposedKeys = Object.keys(ref.current as object).sort();
    expect(exposedKeys).toEqual(["getPhase", "runCreateVault", "runGenerateReport", "runLoadProject", "runStartScoping"].sort());
  });

  it("issues the exact same Bridge commands whether triggered by the manual button or the imperative handle", async () => {
    mockBridgeSuccess();
    const requestSpy = vi.mocked(desktopBridge.request);
    const selectNewVaultPathSpy = vi.spyOn(dialogs, "selectNewVaultPath");
    const ref = createRef<LiveProjectFlowHandle>();
    render(<LiveProjectFlow ref={ref} onBack={() => {}} demoConfig={DEMO_CONFIG} filmDemoMode />);

    // Manual path: the real button, clicked by a user.
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Create new vault…" }));
    await waitFor(() => expect(requestSpy).toHaveBeenCalled());
    const manualCommands = requestSpy.mock.calls.map(([command]) => command);

    requestSpy.mockClear();

    // Imperative path: the same action, invoked the way the Film Demo
    // Director invokes it — never through a dialog.
    await ref.current!.runCreateVault();
    const imperativeCommands = requestSpy.mock.calls.map(([command]) => command);

    expect(imperativeCommands).toEqual(manualCommands);
    expect(manualCommands.map((command) => command.command)).toEqual(["initialize_vault", "get_workspace_state"]);
    expect(selectNewVaultPathSpy).not.toHaveBeenCalled();
  });

  it("skips the folder dialog and loads the configured synthetic project directly", async () => {
    mockBridgeSuccess();
    const requestSpy = vi.mocked(desktopBridge.request);
    const selectArtifactRootSpy = vi.spyOn(dialogs, "selectArtifactRoot");
    const ref = createRef<LiveProjectFlowHandle>();
    render(<LiveProjectFlow ref={ref} onBack={() => {}} demoConfig={DEMO_CONFIG} filmDemoMode />);

    await ref.current!.runCreateVault();
    requestSpy.mockClear();
    await ref.current!.runLoadProject();

    expect(requestSpy.mock.calls.map(([command]) => command.command)).toEqual(["load_project", "get_workspace_state"]);
    const loadCommand = requestSpy.mock.calls[0]?.[0];
    expect(loadCommand).toMatchObject({ command: "load_project", artifact_root: DEMO_CONFIG.artifactRoot });
    expect(selectArtifactRootSpy).not.toHaveBeenCalled();
  });

  it("reports a failed Bridge command through getPhase and onPhaseChange instead of silently continuing", async () => {
    vi.spyOn(desktopBridge, "start").mockResolvedValue({ running: true, process_id: 1 });
    vi.spyOn(desktopBridge, "request").mockRejectedValue(new Error("The local Bridge request failed."));
    const onPhaseChange = vi.fn();
    const ref = createRef<LiveProjectFlowHandle>();
    render(
      <LiveProjectFlow ref={ref} onBack={() => {}} demoConfig={DEMO_CONFIG} filmDemoMode onPhaseChange={onPhaseChange} />,
    );

    await ref.current!.runCreateVault();

    expect(ref.current!.getPhase().error).not.toBeNull();
    await waitFor(() =>
      expect(onPhaseChange).toHaveBeenCalledWith(expect.objectContaining({ error: expect.any(String) })),
    );
  });
});

describe("LiveProjectFlow path display", () => {
  it("never renders the full vault path or artifact root in the manual flow", async () => {
    mockBridgeSuccess();
    vi.spyOn(dialogs, "selectNewVaultPath").mockResolvedValue("C:/Users/real-owner/Documents/secret-vault.bin");
    vi.spyOn(dialogs, "selectArtifactRoot").mockResolvedValue("C:/Users/real-owner/Documents/secret-project");
    render(<LiveProjectFlow onBack={() => {}} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Create new vault…" }));
    expect(await screen.findByText("Vault ready")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select project artifact folder…" }));
    expect(await screen.findByText("Project folder selected")).toBeInTheDocument();

    expect(screen.queryByText(/secret-vault\.bin/)).not.toBeInTheDocument();
    expect(screen.queryByText(/secret-project/)).not.toBeInTheDocument();
    expect(screen.queryByText(/C:\/Users\/real-owner/)).not.toBeInTheDocument();
  });

  it("shows demo-specific copy for the synthetic project in Film Demo mode, never the configured paths", async () => {
    mockBridgeSuccess();
    const ref = createRef<LiveProjectFlowHandle>();
    render(<LiveProjectFlow ref={ref} onBack={() => {}} demoConfig={DEMO_CONFIG} filmDemoMode />);

    await ref.current!.runCreateVault();
    await ref.current!.runLoadProject();

    expect(await screen.findByText("Vault ready")).toBeInTheDocument();
    expect(await screen.findByText("Synthetic Aurora project selected")).toBeInTheDocument();
    expect(screen.queryByText(DEMO_CONFIG.vaultPath)).not.toBeInTheDocument();
    expect(screen.queryByText(DEMO_CONFIG.artifactRoot)).not.toBeInTheDocument();
    expect(screen.queryByText("Project folder selected")).not.toBeInTheDocument();
  });
});

describe("LiveProjectFlow human review", () => {
  it("never pre-selects a source, even one Codex classified as clearly included or excluded", async () => {
    mockBridgeSuccess();
    const ref = createRef<LiveProjectFlowHandle>();
    render(<LiveProjectFlow ref={ref} onBack={() => {}} demoConfig={DEMO_CONFIG} filmDemoMode />);

    await ref.current!.runCreateVault();
    await ref.current!.runLoadProject();
    await ref.current!.runStartScoping();

    const unresolvedTags = await screen.findAllByText("unresolved");
    expect(unresolvedTags).toHaveLength(SCOPING_RESULT.source_scope.decisions.length);
    expect(screen.getByRole("button", { name: /Confirm scope/ })).toBeDisabled();
  });

  it("only enables confirmation once every source -- included, excluded, and ambiguous -- has an explicit click", async () => {
    mockBridgeSuccess();
    const ref = createRef<LiveProjectFlowHandle>();
    render(<LiveProjectFlow ref={ref} onBack={() => {}} demoConfig={DEMO_CONFIG} filmDemoMode />);
    const user = userEvent.setup();

    await ref.current!.runCreateVault();
    await ref.current!.runLoadProject();
    await ref.current!.runStartScoping();
    await screen.findAllByText("unresolved");

    const confirmButton = screen.getByRole("button", { name: /Confirm scope/ });
    for (const decision of SCOPING_RESULT.source_scope.decisions) {
      expect(confirmButton).toBeDisabled();
      const group = screen.getByRole("group", { name: `Decision for ${decision.evidence_id}` });
      const { getByRole } = within(group);
      await user.click(getByRole("button", { name: "Include" }));
    }

    expect(confirmButton).toBeEnabled();
  });
});
