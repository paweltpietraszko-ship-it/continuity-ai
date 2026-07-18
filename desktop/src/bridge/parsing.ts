import type {
  BridgeCommandName,
  BridgeEnvelope,
  BridgeFailure,
  BridgeSuccess,
  PublicBridgeError,
} from "./contracts";

const COMMANDS = new Set<BridgeCommandName>([
  "initialize_vault",
  "unlock_vault",
  "lock_vault",
  "load_project",
  "analyze_project",
  "send_message",
  "confirm_attestation",
  "confirm_analysis_revision",
  "get_workspace_state",
]);

export class BridgeProtocolError extends Error {
  readonly code = "bridge_protocol_error";

  constructor() {
    super("The local analysis process returned an invalid response.");
    this.name = "BridgeProtocolError";
  }
}

export class BridgeCommandError extends Error {
  readonly code: string;
  readonly objectId: null;
  readonly command: BridgeCommandName | null;

  constructor(command: BridgeCommandName | null, error: PublicBridgeError) {
    super(error.message);
    this.name = "BridgeCommandError";
    this.code = error.code;
    this.objectId = error.object_id;
    this.command = command;
  }
}

export function parseBridgeEnvelope<TData>(value: unknown): BridgeEnvelope<TData> {
  const object = asRecord(value);
  if (typeof object.ok !== "boolean") throw new BridgeProtocolError();

  if (object.ok) {
    const command = parseCommand(object.command, false);
    if (!("data" in object)) throw new BridgeProtocolError();
    return { ok: true, command, data: object.data as TData } satisfies BridgeSuccess<TData>;
  }

  const command = parseCommand(object.command, true);
  const error = parsePublicError(object.error);
  return { ok: false, command, error } satisfies BridgeFailure;
}

function parseCommand(value: unknown, nullable: false): BridgeCommandName;
function parseCommand(value: unknown, nullable: true): BridgeCommandName | null;
function parseCommand(value: unknown, nullable: boolean): BridgeCommandName | null {
  if (nullable && value === null) return null;
  if (typeof value !== "string" || !COMMANDS.has(value as BridgeCommandName)) {
    throw new BridgeProtocolError();
  }
  return value as BridgeCommandName;
}

function parsePublicError(value: unknown): PublicBridgeError {
  const object = asRecord(value);
  if (typeof object.code !== "string" || typeof object.message !== "string" || object.object_id !== null) {
    throw new BridgeProtocolError();
  }
  return { code: object.code, message: object.message, object_id: null };
}

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new BridgeProtocolError();
  }
  return value as Record<string, unknown>;
}
