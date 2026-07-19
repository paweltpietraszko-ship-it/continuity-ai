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
    case "browser_demo":
      return "report_available";
  }
}
