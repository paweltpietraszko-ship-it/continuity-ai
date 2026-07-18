import type { BridgeStatus, WorkspaceState } from "./contracts";
import { desktopBridge, isTauriRuntime } from "./client";
import { continuitySession } from "./session";

export type BridgeBootstrapState =
  | {
      readonly mode: "connecting";
    }
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

// Bounds the whole bootstrap, including a Rust-side handshake that never
// responds. Fail-closed: past this point the UI shows the demonstration
// fallback rather than staying on "connecting" forever.
export const BOOTSTRAP_TIMEOUT_MS = 8000;

const defaultDeps: BridgeBootstrapDeps = {
  isTauriRuntime,
  start: () => desktopBridge.start(),
  workspaceState: () => continuitySession.workspaceState(),
};

async function connect(deps: BridgeBootstrapDeps): Promise<BridgeBootstrapState> {
  try {
    const status = await deps.start();
    const workspaceState = await deps.workspaceState();
    return { mode: "connected", processId: status.process_id, workspaceState };
  } catch {
    return { mode: "unavailable", message: UNAVAILABLE_MESSAGE };
  }
}

function withTimeout(
  promise: Promise<BridgeBootstrapState>,
  timeoutMs: number,
): Promise<BridgeBootstrapState> {
  return new Promise((resolve) => {
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      resolve({ mode: "unavailable", message: UNAVAILABLE_MESSAGE });
    }, timeoutMs);

    promise.then((result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    });
  });
}

export async function bootstrapBridge(
  deps: BridgeBootstrapDeps = defaultDeps,
): Promise<BridgeBootstrapState> {
  if (!deps.isTauriRuntime()) {
    return { mode: "browser_demo" };
  }

  return withTimeout(connect(deps), BOOTSTRAP_TIMEOUT_MS);
}

export function bridgeStatusLabel(state: BridgeBootstrapState): string {
  switch (state.mode) {
    case "connecting":
      return "Connecting local Bridge…";
    case "connected":
      return "Local Bridge connected";
    case "unavailable":
      return "Local Bridge unavailable · Demonstration mode";
    case "browser_demo":
      return "Demonstration mode";
  }
}
