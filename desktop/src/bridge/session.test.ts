import { describe, expect, it } from "vitest";

import type { BridgeCommand, BridgeCommandResultMap, WorkspaceState } from "./contracts";
import { ContinuitySession, type BridgeTransport } from "./session";

const EMPTY_STATE: WorkspaceState = {
  vault_unlocked: true,
  owner_display_name: "Paweł",
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

class RecordingTransport implements BridgeTransport {
  readonly commands: BridgeCommand[] = [];

  async start(): Promise<void> {
    return undefined;
  }

  async request<TCommand extends BridgeCommand>(
    command: TCommand,
  ): Promise<BridgeCommandResultMap[TCommand["command"]]> {
    this.commands.push(command);
    if (command.command === "get_workspace_state") {
      return EMPTY_STATE as BridgeCommandResultMap[TCommand["command"]];
    }
    if (command.command === "unlock_vault" || command.command === "initialize_vault") {
      return { session_id: "SES-test", owner_display_name: "Paweł" } as BridgeCommandResultMap[TCommand["command"]];
    }
    if (command.command === "load_project") {
      return { project: "Project Aurora", artifact_evidence_count: 5, evidence_count: 5, evidence_records: [] } as unknown as BridgeCommandResultMap[TCommand["command"]];
    }
    throw new Error(`Unexpected command in test: ${command.command}`);
  }
}

describe("ContinuitySession process sequences", () => {
  it("restores retained state after restart without sending analyze_project", async () => {
    const transport = new RecordingTransport();
    const session = new ContinuitySession(transport);

    await session.restoreAfterProcessRestart("C:/vault", "secret", "C:/artifacts");

    expect(transport.commands.map((command) => command.command)).toEqual([
      "unlock_vault",
      "get_workspace_state",
      "load_project",
      "get_workspace_state",
    ]);
    expect(transport.commands.some((command) => command.command === "analyze_project")).toBe(false);
  });

  it("loads a project and then refreshes canonical workspace state", async () => {
    const transport = new RecordingTransport();
    const session = new ContinuitySession(transport);

    await session.loadProject("C:/artifacts");

    expect(transport.commands.map((command) => command.command)).toEqual([
      "load_project",
      "get_workspace_state",
    ]);
  });
});
