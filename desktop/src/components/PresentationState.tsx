export type PresentationStateKind =
  | "report_available"
  | "analysis_in_progress"
  | "source_review_required"
  | "approved_scope"
  | "codex_unavailable"
  | "operation_interrupted"
  | "no_report_yet"
  | "citation_selected"
  | "evidence_unavailable";

interface PresentationStateCopy {
  readonly label: string;
  readonly detail: string;
  readonly tone: "neutral" | "progress" | "attention" | "unavailable";
}

const COPY: Record<PresentationStateKind, PresentationStateCopy> = {
  report_available: {
    label: "Current report available",
    detail: "Synthetic demo scenario · presentation preview only",
    tone: "neutral",
  },
  analysis_in_progress: {
    label: "Analysis in progress",
    detail: "Connecting to the local Bridge · presentation preview remains visible",
    tone: "progress",
  },
  source_review_required: {
    label: "Source review required",
    detail: "Open the evidence inspector to trace a citation to its source record",
    tone: "attention",
  },
  approved_scope: {
    label: "Approved scope",
    detail: "Decision and budget reflect Northlight Studio · operational documents still lag",
    tone: "neutral",
  },
  codex_unavailable: {
    label: "Local Bridge unavailable",
    detail: "Demonstration report only · no live analysis session",
    tone: "unavailable",
  },
  operation_interrupted: {
    label: "Operation interrupted",
    detail: "The last action did not complete · review the report before continuing",
    tone: "attention",
  },
  no_report_yet: {
    label: "No report yet",
    detail: "Load a project artifact set to reconstruct the current report",
    tone: "unavailable",
  },
  citation_selected: {
    label: "Citation selected",
    detail: "Evidence inspector shows the matching source record",
    tone: "neutral",
  },
  evidence_unavailable: {
    label: "Evidence unavailable",
    detail: "This citation cannot be opened in the current preview set",
    tone: "unavailable",
  },
};

interface PresentationStateProps {
  readonly state: PresentationStateKind;
}

export function PresentationState({ state }: PresentationStateProps) {
  const copy = COPY[state];
  return (
    <div className={`presentation-state tone-${copy.tone}`} role="status" aria-live="polite">
      <span className="presentation-state-label">{copy.label}</span>
      <span className="presentation-state-detail">{copy.detail}</span>
    </div>
  );
}
