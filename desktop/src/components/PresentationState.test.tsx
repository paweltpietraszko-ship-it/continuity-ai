import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { PresentationState } from "./PresentationState";
import { presentationStateForBootstrap } from "./presentationStateForBootstrap";

describe("PresentationState", () => {
  it("maps bootstrap modes to presentation-only labels", () => {
    expect(presentationStateForBootstrap("connecting")).toBe("analysis_in_progress");
    expect(presentationStateForBootstrap("unavailable")).toBe("codex_unavailable");
    expect(presentationStateForBootstrap("browser_demo")).toBe("report_available");
  });

  it("renders analysis in progress without claiming backend completion", () => {
    render(<PresentationState state="analysis_in_progress" />);
    expect(screen.getByText("Analysis in progress")).toBeInTheDocument();
    expect(screen.getByText(/presentation preview remains visible/i)).toBeInTheDocument();
  });

  it("renders codex unavailable as a demonstration fallback", () => {
    render(<PresentationState state="codex_unavailable" />);
    expect(screen.getByText("Local Bridge unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Demonstration report only/i)).toBeInTheDocument();
  });
});

describe("ReportQuestions", () => {
  it("surfaces the three reconstruction questions", async () => {
    const { ReportQuestions } = await import("./ReportQuestions");
    render(<ReportQuestions />);
    expect(screen.getByRole("heading", { name: "What happened?" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What evidence supports it?" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What should happen next?" })).toBeInTheDocument();
  });
});
