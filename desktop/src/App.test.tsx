import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { App, AppRoot } from "./App";
import type { BridgeBootstrapState } from "./bridge/bootstrap";
import type { WorkspaceState } from "./bridge/contracts";

const EMPTY_WORKSPACE_STATE: WorkspaceState = {
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

beforeEach(() => {
  window.history.replaceState(null, "", "#aurora");
});

afterEach(() => {
  cleanup();
});

describe("Continuity AI desktop shell", () => {
  it("opens directly on the Project Aurora current report", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Project Aurora", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Location continuity break" })).toBeInTheDocument();
    expect(screen.getByText("Human action required")).toBeInTheDocument();
  });

  it("opens Workspace as a vertical project list and returns to Aurora", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "← Workspace" }));

    expect(screen.getByRole("heading", { name: "Workspace", level: 1 })).toBeInTheDocument();
    const projects = screen.getByRole("group", { name: "Projects" });
    expect(projects).toHaveClass("project-list");
    expect(screen.getByRole("button", { name: /Project Aurora/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Project Meridian/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Project Ember/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Project Aurora/i }));
    expect(screen.getByRole("heading", { name: "Project Aurora", level: 1 })).toBeInTheDocument();
  });

  it("opens the evidence reconstruction and resolves a citation to its exact source", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Review continuity break" }));
    expect(screen.getByRole("heading", { name: "Decision propagation" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Investor approval" }));
    expect(screen.getByRole("complementary", { name: "Verified sources" })).toHaveAttribute("aria-hidden", "false");
    const source = screen.getByRole("heading", { name: "Investor approval for Northlight Studio move" }).closest("article");
    expect(source).toHaveTextContent("EV-AUR-001");
    expect(source).toHaveTextContent(/Mara Chen formally approves moving/);
  });

  it("requires confirmation before adding an authenticated attestation", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Ask Continuity" }));
    await user.type(screen.getByLabelText("Ask Continuity AI…"), "Add this statement to the project record: Crew transport has been reconfirmed.");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(screen.getByRole("heading", { name: "Pending attestation" })).toBeInTheDocument();
    expect(screen.getByText("Not yet part of project evidence")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Confirm attestation" }));
    expect(
      screen.getByText("This demo attestation was added to the local preview only. It was not sent to a backend or persisted."),
    ).toBeInTheDocument();
  });

  it("never claims the demo attestation was persisted by a backend", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Ask Continuity" }));
    await user.type(screen.getByLabelText("Ask Continuity AI…"), "Add this statement to the project record: Crew transport has been reconfirmed.");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await user.click(screen.getByRole("button", { name: "Confirm attestation" }));

    expect(screen.getByText(/was not sent to a backend or persisted/i)).toBeInTheDocument();
    expect(
      screen.queryByText("The authenticated attestation has been added to the project evidence log."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/^Authenticated User Attestation added/)).not.toBeInTheDocument();
  });

  it("shows Local owner before any real backend unlock", () => {
    render(<App />);

    expect(screen.getByText("Local owner", { selector: "strong" })).toBeInTheDocument();
    expect(screen.queryByText("Paweł", { selector: "strong" })).not.toBeInTheDocument();
  });

  it("shows a connected Bridge status when bootstrap succeeds, without exposing the process id", () => {
    render(
      <App
        bootstrap={{ mode: "connected", processId: 4242, workspaceState: EMPTY_WORKSPACE_STATE }}
      />,
    );

    expect(screen.getByText("Local Bridge connected")).toBeInTheDocument();
    expect(screen.queryByText(/4242/)).not.toBeInTheDocument();
  });

  it("shows an unavailable Bridge status with the demonstration fallback", () => {
    render(<App bootstrap={{ mode: "unavailable", message: "Local Bridge unavailable" }} />);

    expect(screen.getByText("Local Bridge unavailable · Demonstration mode")).toBeInTheDocument();
  });

  it("shows demonstration mode status when rendered outside Tauri", () => {
    render(<App />);

    expect(screen.getByText("Demonstration mode")).toBeInTheDocument();
  });

  it("marks the conversation drawer as a demonstration, not a backend response", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Ask Continuity" }));

    expect(screen.getByRole("heading", { name: "Ask Continuity AI · Demonstration conversation" })).toBeInTheDocument();
  });

  it("locking the vault invalidates a pending attestation", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Ask Continuity" }));
    await user.type(screen.getByLabelText("Ask Continuity AI…"), "Save this statement: Crew transport has been reconfirmed.");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(screen.getByRole("heading", { name: "Pending attestation" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close conversation" }));
    await user.click(screen.getByRole("button", { name: "Lock vault" }));

    expect(screen.getByRole("heading", { name: "Unlock Continuity AI" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Vault password"), "local-demo-password");
    await user.click(screen.getByRole("button", { name: "Unlock vault" }));
    await user.click(screen.getByRole("button", { name: "Ask Continuity" }));

    expect(screen.queryByRole("heading", { name: "Pending attestation" })).not.toBeInTheDocument();
  });
});

describe("AppRoot", () => {
  it("renders the demo shell in a connecting state immediately, before the bootstrap promise resolves", () => {
    const neverResolves = new Promise<BridgeBootstrapState>(() => {});
    render(<AppRoot bootstrapPromise={neverResolves} />);

    expect(screen.getByText("Connecting local Bridge…")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Project Aurora", level: 1 })).toBeInTheDocument();
  });

  it("updates to connected once the bootstrap promise resolves", async () => {
    const promise = Promise.resolve<BridgeBootstrapState>({
      mode: "connected",
      processId: 10,
      workspaceState: EMPTY_WORKSPACE_STATE,
    });
    render(<AppRoot bootstrapPromise={promise} />);

    expect(await screen.findByText("Local Bridge connected")).toBeInTheDocument();
  });

  it("falls back to unavailable if the bootstrap promise unexpectedly rejects", async () => {
    const promise = Promise.reject(new Error("unexpected bootstrap failure"));
    render(<AppRoot bootstrapPromise={promise} />);

    expect(await screen.findByText("Local Bridge unavailable · Demonstration mode")).toBeInTheDocument();
  });
});
