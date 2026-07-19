import { describe, expect, it } from "vitest";

import { BridgeCommandError, BridgeProtocolError, parseBridgeEnvelope } from "./parsing";


describe("Bridge NDJSON response parsing", () => {
  it("accepts a valid success envelope", () => {
    const envelope = parseBridgeEnvelope<{ vault_unlocked: boolean }>({
      ok: true,
      command: "get_workspace_state",
      data: { vault_unlocked: false },
    });

    expect(envelope).toEqual({
      ok: true,
      command: "get_workspace_state",
      data: { vault_unlocked: false },
    });
  });

  it("accepts a controlled failure envelope", () => {
    const envelope = parseBridgeEnvelope({
      ok: false,
      command: "unlock_vault",
      error: { code: "vault_auth_failed", message: "The vault could not be unlocked.", object_id: null },
    });

    expect(envelope.ok).toBe(false);
    if (!envelope.ok) {
      const error = new BridgeCommandError(envelope.command, envelope.error);
      expect(error.code).toBe("vault_auth_failed");
      expect(error.message).toBe("The vault could not be unlocked.");
    }
  });

  it("rejects malformed envelopes before they reach the UI", () => {
    expect(() => parseBridgeEnvelope({ ok: true, command: "get_workspace_state" })).toThrow(BridgeProtocolError);
    expect(() => parseBridgeEnvelope({ ok: false, command: "get_workspace_state", error: { message: "x" } })).toThrow(BridgeProtocolError);
    expect(() => parseBridgeEnvelope({ ok: true, command: "not_real", data: {} })).toThrow(BridgeProtocolError);
  });
});
