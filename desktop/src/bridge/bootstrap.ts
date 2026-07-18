import type { BridgeStatus, WorkspaceState } from "./contracts";
import { desktopBridge, isTauriRuntime } from "./client";
import { continuitySession } from "./session";

export type BridgeBootstrapState =
  | {
      readonly mode: "connected";
      readonly processId: number | null;
      readonly workspaceState: WorkspaceState;
    }
  | {
      readonly mode: "unavailable";
      readonly message: string;
    }
  | {
      readonly mode: "browser_demo";
    };

export interface BridgeBootstrapDeps {
  readonly isTauriRuntime: () => boolean;
  readonly start: () => Promise<BridgeStatus>;
  readonly workspaceState: () => Promise<WorkspaceState>;
}

const UNAVAILABLE_MESSAGE = "Local Bridge unavailable";

const defaultDeps: BridgeBootstrapDeps = {
  isTauriRuntime,
  start: () => desktopBridge.start(),
  workspaceState: () => continuitySession.workspaceState(),
};

export async function bootstrapBridge(
  deps: BridgeBootstrapDeps = defaultDeps,
): Promise<BridgeBootstrapState> {
  if (!deps.isTauriRuntime()) {
    return { mode: "browser_demo" };
  }

  try {
    const status = await deps.start();
    const workspaceState = await deps.workspaceState();
    return { mode: "connected", processId: status.process_id, workspaceState };
  } catch {
    return { mode: "unavailable", message: UNAVAILABLE_MESSAGE };
  }
}

export function bridgeStatusLabel(state: BridgeBootstrapState): string {
  switch (state.mode) {
    case "connected":
      return "Local Bridge connected";
    case "unavailable":
      return "Local Bridge unavailable · Demonstration mode";
    case "browser_demo":
      return "Demonstration mode";
  }
}
