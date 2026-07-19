import type { PresentationStateKind } from "./PresentationState";

export function presentationStateForBootstrap(
  mode: "connecting" | "connected" | "unavailable" | "browser_demo",
): PresentationStateKind {
  switch (mode) {
    case "connecting":
      return "analysis_in_progress";
    case "unavailable":
      return "codex_unavailable";
    case "connected":
      return "report_available";
    case "browser_demo":
      return "browser_demo";
  }
}
