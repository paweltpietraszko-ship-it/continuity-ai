import { describe, expect, it } from "vitest";

import type {
  CitationCard,
  GroundedStatement,
  ProjectReport,
  ProjectReportSection,
  WorkspaceState,
} from "./contracts";
import {
  ProjectReportContractError,
  createProjectReportDisplay,
  ownerDisplayLabel,
} from "./projectReportProjection";

const CITATIONS: readonly CitationCard[] = [
  citation("SPAN-DECISION", "EV-1"),
  citation("SPAN-BUDGET", "EV-2"),
  citation("SPAN-SCHEDULE", "EV-3"),
  citation("SPAN-OPERATIONS", "EV-4"),
  citation("SPAN-READINESS", "EV-5"),
];

const BREAK: GroundedStatement = {
  statement: "An approved decision did not reach current operating documents.",
  span_ids: ["SPAN-SCHEDULE", "SPAN-OPERATIONS"],
};

const VALID_REPORT: ProjectReport = {
  summary: {
    statement: "The approved location is not reflected in the current operating documents.",
    span_ids: ["SPAN-DECISION", "SPAN-SCHEDULE", "SPAN-OPERATIONS"],
  },
  sections: [
    section("decision", "confirmed", "Decision confirmed", "The current decision is supported.", ["SPAN-DECISION"]),
    section("budget", "confirmed", "Budget updated", "The current budget reflects the decision.", ["SPAN-BUDGET"]),
    section("schedule", "attention", "Schedule is stale", "The current schedule conflicts with the decision.", ["SPAN-SCHEDULE"]),
    section("operations", "attention", "Operations are stale", "The current operating document conflicts with the decision.", ["SPAN-OPERATIONS"]),
    section("readiness", "attention", "Crew briefing is time-sensitive", "The current briefing creates urgency.", ["SPAN-READINESS"]),
    evidenceGap("casting", "No available project source establishes the current casting status."),
    evidenceGap("agreements", "No available project source establishes the current agreements status."),
  ],
};

describe("Project Report schema 3.0 projection", () => {
  it("maps the seven backend-owned sections without deriving report conclusions", () => {
    const display = createProjectReportDisplay(VALID_REPORT, CITATIONS, "break_found", BREAK);

    expect(display.summary).toBe(VALID_REPORT.summary.statement);
    expect(display.sections.map((item) => item.key)).toEqual([
      "decision",
      "budget",
      "schedule",
      "operations",
      "readiness",
      "casting",
      "agreements",
    ]);
    expect(display.sections[2]).toMatchObject({
      label: "Schedule",
      icon: "S",
      statusLabel: "Attention",
      tone: "attention",
      headline: "Schedule is stale",
    });
    expect(display.sections[2]?.citations[0]?.exactText).toBe("Exact text for SPAN-SCHEDULE");
    expect(display.sections[5]).toMatchObject({
      label: "Casting",
      statusLabel: "Evidence gap",
      citations: [],
    });
  });

  it("rejects omitted, duplicated, reordered or renamed sections", () => {
    const missing = { ...VALID_REPORT, sections: VALID_REPORT.sections.slice(0, 6) };
    expect(() => createProjectReportDisplay(missing, CITATIONS, "break_found", BREAK)).toThrow(ProjectReportContractError);

    const reordered = {
      ...VALID_REPORT,
      sections: [VALID_REPORT.sections[1]!, VALID_REPORT.sections[0]!, ...VALID_REPORT.sections.slice(2)],
    };
    expect(() => createProjectReportDisplay(reordered, CITATIONS, "break_found", BREAK)).toThrow(ProjectReportContractError);
  });

  it("rejects speculative or grounded-looking text in an evidence-gap section", () => {
    const sections = [...VALID_REPORT.sections];
    sections[5] = {
      ...sections[5]!,
      detail: "The casting tracker may be missing because the producer has not uploaded it.",
    };

    expect(() => createProjectReportDisplay({ ...VALID_REPORT, sections }, CITATIONS, "break_found", BREAK)).toThrow(
      ProjectReportContractError,
    );
  });

  it("rejects report spans that do not resolve to backend-owned citation cards", () => {
    const sections = [...VALID_REPORT.sections];
    sections[0] = { ...sections[0]!, span_ids: ["SPAN-NOT-RETURNED"] };

    expect(() => createProjectReportDisplay({ ...VALID_REPORT, sections }, CITATIONS, "break_found", BREAK)).toThrow(
      ProjectReportContractError,
    );
  });

  it("enforces break/no-break consistency", () => {
    expect(() => createProjectReportDisplay(VALID_REPORT, CITATIONS, "no_material_break_found", null)).toThrow(
      ProjectReportContractError,
    );

    const noBreakReport: ProjectReport = {
      ...VALID_REPORT,
      sections: VALID_REPORT.sections.map((item) =>
        item.status === "attention" ? { ...item, status: "confirmed" as const } : item,
      ),
    };
    expect(() => createProjectReportDisplay(noBreakReport, CITATIONS, "no_material_break_found", null)).not.toThrow();
  });
});

describe("owner privacy projection", () => {
  it("never exposes a cached owner label while the vault is locked", () => {
    const locked = workspaceState(false, "Paweł");
    expect(ownerDisplayLabel(locked)).toBe("Local owner");
  });

  it("uses the decrypted owner display name only after successful unlock", () => {
    const unlocked = workspaceState(true, "Paweł");
    expect(ownerDisplayLabel(unlocked)).toBe("Paweł");
  });
});

function citation(spanId: string, evidenceId: string): CitationCard {
  return {
    evidence_id: evidenceId,
    span_id: spanId,
    exact_text: `Exact text for ${spanId}`,
    title: `Source ${evidenceId}`,
    author_or_actor: "Author",
    timestamp: "2026-07-18T12:00:00Z",
    source_type: "text",
    provenance: "artifact",
    source_status: "snapshot",
  };
}

function section(
  key: ProjectReportSection["key"],
  status: ProjectReportSection["status"],
  headline: string,
  detail: string,
  spanIds: readonly string[],
): ProjectReportSection {
  return { key, status, headline, detail, span_ids: spanIds };
}

function evidenceGap(
  key: ProjectReportSection["key"],
  detail: string,
): ProjectReportSection {
  return section(key, "evidence_gap", "No verified status available", detail, []);
}

function workspaceState(vaultUnlocked: boolean, ownerDisplayName: string | null): WorkspaceState {
  return {
    vault_unlocked: vaultUnlocked,
    owner_display_name: ownerDisplayName,
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
}
