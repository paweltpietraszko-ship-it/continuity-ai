import { describe, expect, it, vi } from "vitest";

import type { WorkspaceState } from "./contracts";
import { bootstrapBridge, bridgeStatusLabel } from "./bootstrap";

const WORKSPACE_STATE: WorkspaceState = {
  vault_unlocked: false,
  owner_display_name: null,
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

describe("bootstrapBridge", () => {
  it("starts the Bridge exactly once and fetches workspace state when running in Tauri", async () => {
    const start = vi.fn().mockResolvedValue({ running: true, process_id: 4242 });
    const workspaceState = vi.fn().mockResolvedValue(WORKSPACE_STATE);

    const result = await bootstrapBridge({
      isTauriRuntime: () => true,
      start,
      workspaceState,
    });

    expect(start).toHaveBeenCalledTimes(1);
    expect(workspaceState).toHaveBeenCalledTimes(1);
    expect(result).toEqual({
      mode: "connected",
      processId: 4242,
      workspaceState: WORKSPACE_STATE,
    });
  });

  it("does not attempt to start the Bridge outside a Tauri runtime", async () => {
    const start = vi.fn();
    const workspaceState = vi.fn();

    const result = await bootstrapBridge({
      isTauriRuntime: () => false,
      start,
      workspaceState,
    });

    expect(start).not.toHaveBeenCalled();
    expect(workspaceState).not.toHaveBeenCalled();
    expect(result).toEqual({ mode: "browser_demo" });
  });

  it("returns a controlled unavailable state when the Bridge fails to start, without leaking error detail", async () => {
    const start = vi
      .fn()
      .mockRejectedValue(new Error("ENOENT: python not found at C:\\secret\\path\\python.exe"));
    const workspaceState = vi.fn();

    const result = await bootstrapBridge({
      isTauriRuntime: () => true,
      start,
      workspaceState,
    });

    expect(result.mode).toBe("unavailable");
    if (result.mode === "unavailable") {
      expect(result.message).not.toMatch(/python|ENOENT|secret|path/i);
    }
    expect(workspaceState).not.toHaveBeenCalled();
  });

  it("returns a controlled unavailable state when the handshake fails after a successful start", async () => {
    const start = vi.fn().mockResolvedValue({ running: true, process_id: 99 });
    const workspaceState = vi.fn().mockRejectedValue(new Error("handshake failed"));

    const result = await bootstrapBridge({ isTauriRuntime: () => true, start, workspaceState });

    expect(result.mode).toBe("unavailable");
    expect(start).toHaveBeenCalledTimes(1);
  });
});

describe("bridgeStatusLabel", () => {
  it("labels each bootstrap mode without exposing a process id", () => {
    expect(bridgeStatusLabel({ mode: "connected", processId: 4242, workspaceState: WORKSPACE_STATE })).toBe(
      "Local Bridge connected",
    );
    expect(bridgeStatusLabel({ mode: "unavailable", message: "Local Bridge unavailable" })).toBe(
      "Local Bridge unavailable · Demonstration mode",
    );
    expect(bridgeStatusLabel({ mode: "browser_demo" })).toBe("Demonstration mode");
  });
});
