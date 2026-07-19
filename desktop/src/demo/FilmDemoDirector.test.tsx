import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { desktopBridge } from "../bridge/client";
import type {
  BridgeCommand,
  BridgeCommandResultMap,
  ScopeProjectSourcesData,
  WorkspaceState,
} from "../bridge/contracts";
import { FilmDemoDirector } from "./FilmDemoDirector";
import type { FilmDemoConfig } from "./filmDemoEnv";

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
    ],
    selected_evidence_ids: ["EV-1"],
    ambiguous_evidence_ids: [],
    excluded_evidence_ids: [],
  },
  citation_cards: [],
};

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: unknown) => void } {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
  vi.spyOn(desktopBridge, "start").mockResolvedValue({ running: true, process_id: 1 });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
});

describe("FilmDemoDirector", () => {
  it("blocks Space from advancing while a Bridge request is in flight", async () => {
    const initializeVault = deferred<BridgeCommandResultMap["initialize_vault"]>();
    const requestSpy = vi
      .spyOn(desktopBridge, "request")
      .mockImplementation(async <TCommand extends BridgeCommand>(command: TCommand) => {
        if (command.command === "initialize_vault") {
          return initializeVault.promise as Promise<BridgeCommandResultMap[TCommand["command"]]>;
        }
        if (command.command === "get_workspace_state") {
          return EMPTY_STATE as BridgeCommandResultMap[TCommand["command"]];
        }
        throw new Error(`Unexpected command in test: ${command.command}`);
      });

    render(<FilmDemoDirector config={DEMO_CONFIG} onExit={() => {}} />);
    const user = userEvent.setup();

    // Shot 1 -> shot 2 ("create-vault"): starts the (never-resolving) request.
    await user.click(screen.getByRole("button", { name: "Continue (Space)" }));
    await waitFor(() => expect(requestSpy).toHaveBeenCalledWith(expect.objectContaining({ command: "initialize_vault" })));
    expect(screen.getByText("Request status: Working…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue (Space)" })).toBeDisabled();

    const callsWhileBusy = requestSpy.mock.calls.length;

    // Space must not advance to shot 3 while the request is still busy.
    await user.keyboard(" ");
    expect(screen.getByText("Shot 2 / 11")).toBeInTheDocument();
    expect(requestSpy.mock.calls.length).toBe(callsWhileBusy);

    initializeVault.resolve({ session_id: "SES-demo", owner_display_name: "Demo Owner" });
    await waitFor(() => expect(screen.getByText("Request status: Idle")).toBeInTheDocument());
  });

  it("stops the scenario fail-closed on a Bridge error and never auto-advances afterward", async () => {
    vi.spyOn(desktopBridge, "request").mockImplementation(async <TCommand extends BridgeCommand>(command: TCommand) => {
      if (command.command === "initialize_vault") {
        throw new Error("The local Bridge request failed.");
      }
      if (command.command === "get_workspace_state") {
        return EMPTY_STATE as BridgeCommandResultMap[TCommand["command"]];
      }
      throw new Error(`Unexpected command in test: ${command.command}`);
    });

    render(<FilmDemoDirector config={DEMO_CONFIG} onExit={() => {}} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Continue (Space)" }));

    const panel = screen.getByRole("complementary", { name: "Film demo director" });
    await waitFor(() => expect(panel).toHaveTextContent("Scenario stopped:"));
    expect(screen.getByText("Shot 2 / 11")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue (Space)" })).toBeDisabled();

    // Neither the button nor Space can push the fail-closed scenario forward.
    await user.keyboard(" ");
    expect(screen.getByText("Shot 2 / 11")).toBeInTheDocument();
  });

  it("drives shots 1-5 through the exact same Bridge commands as the manual flow, then halts at shot 6 for manual approval", async () => {
    const requestSpy = vi
      .spyOn(desktopBridge, "request")
      .mockImplementation(async <TCommand extends BridgeCommand>(command: TCommand) => {
        if (command.command === "get_workspace_state") {
          return EMPTY_STATE as BridgeCommandResultMap[TCommand["command"]];
        }
        if (command.command === "initialize_vault") {
          return { session_id: "SES-demo", owner_display_name: "Demo Owner" } as BridgeCommandResultMap[TCommand["command"]];
        }
        if (command.command === "load_project") {
          return {
            project: "Project Aurora",
            artifact_evidence_count: 1,
            evidence_count: 1,
            evidence_records: [],
          } as unknown as BridgeCommandResultMap[TCommand["command"]];
        }
        if (command.command === "scope_project_sources") {
          return SCOPING_RESULT as BridgeCommandResultMap[TCommand["command"]];
        }
        throw new Error(`Unexpected command in test: ${command.command}`);
      });

    render(<FilmDemoDirector config={DEMO_CONFIG} onExit={() => {}} />);
    const user = userEvent.setup();
    const continueButton = () => screen.getByRole("button", { name: "Continue (Space)" });

    // Shot 1 -> 2: create-vault
    await user.click(continueButton());
    await waitFor(() => expect(screen.getByText("Shot 2 / 11")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Request status: Idle")).toBeInTheDocument());

    // Shot 2 -> 3: load-project
    await user.click(continueButton());
    await waitFor(() => expect(screen.getByText("Shot 3 / 11")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Request status: Idle")).toBeInTheDocument());

    // Shot 3 -> 4: run-scoping
    await user.click(continueButton());
    await waitFor(() => expect(screen.getByText("Shot 4 / 11")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Request status: Idle")).toBeInTheDocument());

    // Shot 4 -> 5: show-human-review (display-only, no Bridge command)
    const callsBeforeShot5 = requestSpy.mock.calls.length;
    await user.click(continueButton());
    await waitFor(() => expect(screen.getByText("Shot 5 / 11")).toBeInTheDocument());
    expect(requestSpy.mock.calls.length).toBe(callsBeforeShot5);

    // Shot 5 -> 6: mandatory manual approval. Continue/Space must refuse to
    // advance any further -- the real approval button (rendered inside
    // LiveProjectFlow, never in the Director's own panel) is the only way
    // past this point, and this test never clicks it.
    await user.click(continueButton());
    await waitFor(() => expect(screen.getByText("Shot 6 / 11")).toBeInTheDocument());
    expect(continueButton()).toBeDisabled();

    const callsAtShot6 = requestSpy.mock.calls.length;
    await user.keyboard(" ");
    expect(screen.getByText("Shot 6 / 11")).toBeInTheDocument();
    expect(requestSpy.mock.calls.length).toBe(callsAtShot6);

    expect(
      screen.getByText(/Waiting for the explicit.*Confirm scope/i, { exact: false }),
    ).toBeInTheDocument();

    // The exact same commands, in the exact same order, that the manual
    // Live Project flow issues for these steps -- nothing demo-specific.
    expect(requestSpy.mock.calls.map(([command]) => command.command)).toEqual([
      "initialize_vault",
      "get_workspace_state",
      "load_project",
      "get_workspace_state",
      "scope_project_sources",
    ]);
  });
});
