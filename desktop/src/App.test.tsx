import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { App } from "./App";

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
    expect(screen.getByText("The authenticated attestation has been added to the project evidence log.")).toBeInTheDocument();
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
