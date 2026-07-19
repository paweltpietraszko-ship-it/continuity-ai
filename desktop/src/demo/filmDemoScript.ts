/**
 * Film Demo Director v0.1 — the fixed 11-shot narration script.
 *
 * Every shot maps to exactly one already-existing `LiveProjectFlow` action
 * (or a pure scroll/highlight within its already-rendered output); this
 * file never invents a new Bridge command or a new outcome.
 */

export type DemoAction =
  | "enter"
  | "create-vault"
  | "load-project"
  | "run-scoping"
  | "show-human-review"
  | "await-manual-approval"
  | "show-approved-workspace"
  | "generate-report"
  | "scroll-continuity-break"
  | "show-recommended-action"
  | "open-evidence-inspector";

export interface DemoShot {
  readonly number: number;
  readonly name: string;
  readonly voiceover: string;
  readonly expectedElement: string;
  readonly action: DemoAction;
  readonly requiresManualApproval?: boolean;
}

export const FILM_DEMO_SHOTS: readonly DemoShot[] = [
  {
    number: 1,
    name: "Open Live Project",
    voiceover:
      "We start in Live Project. Every screen from here is backed by the real local Bridge process, not a script.",
    expectedElement: "The Live Project header and its numbered flow panels",
    action: "enter",
  },
  {
    number: 2,
    name: "Create a clean demo vault",
    voiceover: "Continuity AI creates a brand-new, empty encrypted vault for this run.",
    expectedElement: "The Vault panel confirming a freshly created vault",
    action: "create-vault",
  },
  {
    number: 3,
    name: "Load the synthetic Aurora project",
    voiceover:
      "It loads a prepared synthetic Project Aurora artifact folder directly — no file picker for this recording.",
    expectedElement: "The Project panel showing the loaded project and its evidence count",
    action: "load-project",
  },
  {
    number: 4,
    name: "Run real Source Scoping",
    voiceover:
      "Continuity AI launches a genuine Codex session and asks it to classify every source for this project.",
    expectedElement: "The Source Scoping investigation panel completing",
    action: "run-scoping",
  },
  {
    number: 5,
    name: "Human review",
    voiceover:
      "Every source Codex classified is listed here with its model classification and rationale, waiting for a human decision.",
    expectedElement: "The human review list with Include / Exclude controls for every source",
    action: "show-human-review",
  },
  {
    number: 6,
    name: "Mandatory manual approval",
    voiceover:
      "This is the one step Continuity AI never performs automatically. Click “Confirm scope & materialize approved-only workspace” below to continue.",
    expectedElement: "The real “Confirm scope & materialize approved-only workspace” button",
    action: "await-manual-approval",
    requiresManualApproval: true,
  },
  {
    number: 7,
    name: "Approved-only workspace & run identity",
    voiceover:
      "The approved-only workspace is now materialized, physically separate from the mixed folder, and bound to the same Codex session — see the Run identity panel.",
    expectedElement: "The Run identity panel and the approved-only workspace summary",
    action: "show-approved-workspace",
  },
  {
    number: 8,
    name: "Generate the real report",
    voiceover:
      "Continuity AI resumes that exact Codex session on the approved-only workspace to produce the project report.",
    expectedElement: "The Project Report panel with its section statuses",
    action: "generate-report",
  },
  {
    number: 9,
    name: "Scroll to the continuity break",
    voiceover: "Here is the section Continuity AI flagged for attention.",
    expectedElement: "The highlighted attention section in the report",
    action: "scroll-continuity-break",
  },
  {
    number: 10,
    name: "Recommended action",
    voiceover: "And here is the one recommended next action a human owner should take.",
    expectedElement: "The Recommended next action panel",
    action: "show-recommended-action",
  },
  {
    number: 11,
    name: "Evidence inspector",
    voiceover: "Finally, every citation in this report traces back to a real, quoted source record.",
    expectedElement: "The evidence inspector list of citation cards",
    action: "open-evidence-inspector",
  },
];

/** Clamps into `[0, FILM_DEMO_SHOTS.length - 1]`, always returning a real shot. */
export function shotAt(index: number): DemoShot {
  const clamped = Math.min(Math.max(index, 0), FILM_DEMO_SHOTS.length - 1);
  const shot = FILM_DEMO_SHOTS[clamped];
  if (!shot) throw new Error("FILM_DEMO_SHOTS is unexpectedly empty.");
  return shot;
}
