import { invoke } from "@tauri-apps/api/core";

import type {
  BridgeCommand,
  BridgeCommandResultMap,
  BridgeEnvelope,
  BridgeStatus,
} from "./contracts";
import { BridgeCommandError, parseBridgeEnvelope } from "./parsing";

export class DesktopBridgeClient {
  async start(): Promise<BridgeStatus> {
    const status = await invoke<BridgeStatus>("bridge_status");
    return status.running ? status : invoke<BridgeStatus>("bridge_start");
  }

  async status(): Promise<BridgeStatus> {
    return invoke<BridgeStatus>("bridge_status");
  }

  async stop(): Promise<BridgeStatus> {
    return invoke<BridgeStatus>("bridge_stop");
  }

  async request<TCommand extends BridgeCommand>(
    command: TCommand,
  ): Promise<BridgeCommandResultMap[TCommand["command"]]> {
    const raw = await invoke<unknown>("bridge_request", { command });
    const envelope = parseBridgeEnvelope<BridgeCommandResultMap[TCommand["command"]]>(raw);
    this.assertMatchingCommand(command.command, envelope);
    if (!envelope.ok) throw new BridgeCommandError(envelope.command, envelope.error);
    return envelope.data;
  }

  private assertMatchingCommand(
    command: BridgeCommand["command"],
    envelope: BridgeEnvelope<unknown>,
  ): void {
    if (envelope.command !== command) {
      throw new Error("The local analysis response did not match the request.");
    }
  }
}

export function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in window;
}

export const desktopBridge = new DesktopBridgeClient();
