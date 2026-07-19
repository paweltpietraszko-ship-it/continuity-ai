import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { desktopBridge } from "../bridge/client";
import type { BridgeCommand, BridgeCommandResultMap, WorkspaceState } from "../bridge/contracts";
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
});
