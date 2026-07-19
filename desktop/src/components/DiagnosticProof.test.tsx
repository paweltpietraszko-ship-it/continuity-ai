import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { desktopBridge } from "../bridge/client";
import type { BridgeCommand, BridgeCommandResultMap } from "../bridge/contracts";
import { DiagnosticProof } from "./DiagnosticProof";

const DECISIONS = [
  {
    evidence_id: "EV-1",
    association_status: "included" as const,
    basis: "explicit_target" as const,
    rationale: "Explicitly names the target project.",
  },
  {
    evidence_id: "EV-2",
    association_status: "excluded" as const,
    basis: "explicit_other_project" as const,
    rationale: "Explicitly names a different project.",
  },
  {
    evidence_id: "EV-3",
    association_status: "ambiguous" as const,
    basis: "insufficient_context" as const,
    rationale: "Not enough context to decide.",
  },
];

const PASS_REPORT = {
  result: "PASS" as const,
  codex_session_id: "12345678-aaaa-bbbb-cccc-1234567890ab",
  claims: [
    { name: "ORACLE_ABSENT_DURING_ENGINE_EXECUTION", status: "PASS" as const, observed: "true" },
    { name: "SAME_CODEX_SESSION_ID", status: "PASS" as const, observed: "12345678-aaaa-bbbb-cccc-1234567890ab" },
    { name: "UNSEEN_SEED_RECORDED", status: "PASS" as const, observed: "[redacted]" },
  ],
};

const FAIL_REPORT = {
  result: "FAIL" as const,
  codex_session_id: "12345678-aaaa-bbbb-cccc-1234567890ab",
  claims: [
    { name: "APPROVED_WORKSPACE_FINGERPRINT_MATCH", status: "FAIL" as const, observed: "false" },
    { name: "ORACLE_ABSENT_DURING_ENGINE_EXECUTION", status: "PASS" as const, observed: "true" },
  ],
};

function mockDiagnosticBridge(): void {
  vi.spyOn(desktopBridge, "start").mockResolvedValue({ running: true, process_id: 1 });
  vi.spyOn(desktopBridge, "request").mockImplementation(
    async <TCommand extends BridgeCommand>(
      command: TCommand,
    ): Promise<BridgeCommandResultMap[TCommand["command"]]> => {
      if (command.command === "diagnostic_prepare_workspace") {
        return { phase: "workspace_ready", input_fingerprint_prefix: "abcdef123456" } as BridgeCommandResultMap[TCommand["command"]];
      }
      if (command.command === "diagnostic_run_scoping") {
        return {
          phase: "awaiting_review",
          target_project: "Project Test Fixture",
          decisions: DECISIONS,
        } as unknown as BridgeCommandResultMap[TCommand["command"]];
      }
      if (command.command === "diagnostic_confirm_scope") {
        return { phase: "completed", ...PASS_REPORT } as unknown as BridgeCommandResultMap[TCommand["command"]];
      }
      if (command.command === "diagnostic_run_tamper_check") {
        return { phase: "tampered", ...FAIL_REPORT } as unknown as BridgeCommandResultMap[TCommand["command"]];
      }
      if (command.command === "diagnostic_reset") {
        return { phase: "idle" } as BridgeCommandResultMap[TCommand["command"]];
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

describe("DiagnosticProof", () => {
  it("never pre-selects a decision and only enables confirmation once every source is explicitly resolved", async () => {
    mockDiagnosticBridge();
    render(<DiagnosticProof onBack={() => {}} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Prepare a fresh synthetic unseen workspace" }));
    await user.click(await screen.findByRole("button", { name: "Run real Codex Source Scoping investigation" }));

    const unresolvedTags = await screen.findAllByText("unresolved");
    expect(unresolvedTags).toHaveLength(DECISIONS.length);

    const confirmButton = screen.getByRole("button", { name: /Confirm scope/ });
    expect(confirmButton).toBeDisabled();

    for (const decision of DECISIONS) {
      const group = screen.getByRole("group", { name: `Decision for ${decision.evidence_id}` });
      const { getByRole } = within(group);
      expect(confirmButton).toBeDisabled();
      await user.click(getByRole("button", { name: "Include" }));
    }

    expect(confirmButton).toBeEnabled();
  });

  it("issues the split-phase commands in order and renders PASS with claims and the short Codex session id, never the full id", async () => {
    mockDiagnosticBridge();
    const requestSpy = vi.mocked(desktopBridge.request);
    render(<DiagnosticProof onBack={() => {}} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Prepare a fresh synthetic unseen workspace" }));
    await user.click(await screen.findByRole("button", { name: "Run real Codex Source Scoping investigation" }));
    for (const decision of DECISIONS) {
      const group = screen.getByRole("group", { name: `Decision for ${decision.evidence_id}` });
      await user.click(within(group).getByRole("button", { name: "Include" }));
    }
    await user.click(screen.getByRole("button", { name: /Confirm scope/ }));

    expect(await screen.findByText("DIAGNOSTIC PROOF: PASS")).toBeInTheDocument();
    expect(screen.getByText(/Oracle absent during both Codex executions/)).toBeInTheDocument();
    expect(screen.getByText("SAME_CODEX_SESSION_ID")).toBeInTheDocument();
    // The prominent "Codex session" summary field always shows the
    // truncated form, matching the RunIdentity convention used elsewhere in
    // this app; the claims table below it separately shows full evidence,
    // including the raw session id, as part of "observed" claim content.
    const summary = screen.getByText("Codex session").closest("div");
    expect(summary).not.toBeNull();
    expect(summary).not.toHaveTextContent(PASS_REPORT.codex_session_id);
    expect(summary).toHaveTextContent("12345678…");

    expect(requestSpy.mock.calls.map(([command]) => command.command)).toEqual([
      "diagnostic_prepare_workspace",
      "diagnostic_run_scoping",
      "diagnostic_confirm_scope",
    ]);
  });

  it("only enables the controlled tamper check after a completed result, and shows its expected FAIL separately", async () => {
    mockDiagnosticBridge();
    render(<DiagnosticProof onBack={() => {}} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Prepare a fresh synthetic unseen workspace" }));
    await user.click(await screen.findByRole("button", { name: "Run real Codex Source Scoping investigation" }));
    for (const decision of DECISIONS) {
      const group = screen.getByRole("group", { name: `Decision for ${decision.evidence_id}` });
      await user.click(within(group).getByRole("button", { name: "Include" }));
    }
    await user.click(screen.getByRole("button", { name: /Confirm scope/ }));
    await screen.findByText("DIAGNOSTIC PROOF: PASS");

    const tamperButton = screen.getByRole("button", { name: /Run controlled tamper check/ });
    expect(tamperButton).toBeEnabled();
    await user.click(tamperButton);

    expect(await screen.findByText(/Expected FAIL/)).toBeInTheDocument();
    const results = screen.getAllByText(/DIAGNOSTIC PROOF:/);
    expect(results.map((node) => node.textContent)).toEqual([
      "DIAGNOSTIC PROOF: PASS",
      "DIAGNOSTIC PROOF: FAIL",
    ]);
  });

  it("never renders a full local path, the seed, or oracle content", async () => {
    mockDiagnosticBridge();
    render(<DiagnosticProof onBack={() => {}} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Prepare a fresh synthetic unseen workspace" }));
    await user.click(await screen.findByRole("button", { name: "Run real Codex Source Scoping investigation" }));
    for (const decision of DECISIONS) {
      const group = screen.getByRole("group", { name: `Decision for ${decision.evidence_id}` });
      await user.click(within(group).getByRole("button", { name: "Include" }));
    }
    await user.click(screen.getByRole("button", { name: /Confirm scope/ }));
    await screen.findByText("DIAGNOSTIC PROOF: PASS");

    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/[a-zA-Z]:\\/);
    expect(body).not.toMatch(/\/(Users|home)\//);
    expect(body).not.toContain("expected_status");
  });

  it("resets back to the initial idle phase and clears prior results", async () => {
    mockDiagnosticBridge();
    render(<DiagnosticProof onBack={() => {}} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Prepare a fresh synthetic unseen workspace" }));
    await screen.findByText(/Synthetic unseen workspace ready/);

    await user.click(screen.getByRole("button", { name: "Reset diagnostic run" }));

    expect(screen.queryByText(/Synthetic unseen workspace ready/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare a fresh synthetic unseen workspace" })).toBeEnabled();
  });
});
