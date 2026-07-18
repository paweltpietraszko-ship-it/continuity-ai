import type {
  AnalysisStatus,
  CitationCard,
  GroundedStatement,
  ProjectReport,
  ProjectReportSection,
  ProjectReportSectionKey,
  ProjectReportSectionStatus,
  WorkspaceState,
} from "./contracts";

export const PROJECT_REPORT_SECTION_KEYS = [
  "decision",
  "budget",
  "schedule",
  "operations",
  "readiness",
  "casting",
  "agreements",
] as const satisfies readonly ProjectReportSectionKey[];

const SECTION_PRESENTATION: Readonly<
  Record<ProjectReportSectionKey, { readonly label: string; readonly icon: string; readonly evidenceGapDetail: string }>
> = {
  decision: {
    label: "Decision",
    icon: "D",
    evidenceGapDetail: "No available project source establishes the current decision status.",
  },
  budget: {
    label: "Budget",
    icon: "B",
    evidenceGapDetail: "No available project source establishes the current budget status.",
  },
  schedule: {
    label: "Schedule",
    icon: "S",
    evidenceGapDetail: "No available project source establishes the current schedule status.",
  },
  operations: {
    label: "Operations",
    icon: "O",
    evidenceGapDetail: "No available project source establishes the current operations status.",
  },
  readiness: {
    label: "Readiness",
    icon: "R",
    evidenceGapDetail: "No available project source establishes the current readiness status.",
  },
  casting: {
    label: "Casting",
    icon: "C",
    evidenceGapDetail: "No available project source establishes the current casting status.",
  },
  agreements: {
    label: "Agreements",
    icon: "A",
    evidenceGapDetail: "No available project source establishes the current agreements status.",
  },
};

const STATUS_PRESENTATION: Readonly<
  Record<ProjectReportSectionStatus, { readonly label: string; readonly tone: ReportStatusTone }>
> = {
  confirmed: { label: "Verified", tone: "verified" },
  attention: { label: "Attention", tone: "attention" },
  evidence_gap: { label: "Evidence gap", tone: "gap" },
  not_applicable: { label: "Not applicable", tone: "neutral" },
};

export type ReportStatusTone = "verified" | "attention" | "gap" | "neutral";

export interface ReportCitationDisplay {
  readonly spanId: string;
  readonly evidenceId: string;
  readonly exactText: string;
  readonly title: string;
  readonly authorOrActor: string;
  readonly timestamp: string;
  readonly sourceType: string;
  readonly provenance: CitationCard["provenance"];
  readonly sourceStatus: CitationCard["source_status"];
}

export interface ProjectReportSectionDisplay {
  readonly key: ProjectReportSectionKey;
  readonly label: string;
  readonly icon: string;
  readonly status: ProjectReportSectionStatus;
  readonly statusLabel: string;
  readonly tone: ReportStatusTone;
  readonly headline: string;
  readonly detail: string;
  readonly citations: readonly ReportCitationDisplay[];
}

export interface ProjectReportDisplay {
  readonly summary: string;
  readonly summaryCitations: readonly ReportCitationDisplay[];
  readonly sections: readonly ProjectReportSectionDisplay[];
}

export class ProjectReportContractError extends Error {
  readonly code = "project_report_contract_error";

  constructor() {
    super("The project report returned by the local analysis process is invalid.");
    this.name = "ProjectReportContractError";
  }
}

export function createProjectReportDisplay(
  report: ProjectReport,
  citationCards: readonly CitationCard[],
  analysisStatus: AnalysisStatus,
  continuityBreak: GroundedStatement | null,
): ProjectReportDisplay {
  const citationIndex = buildCitationIndex(citationCards);
  validateSummary(report.summary, citationIndex);
  validateSections(report.sections, citationIndex);
  validateAnalysisConsistency(report.sections, analysisStatus, continuityBreak);

  return {
    summary: report.summary.statement.trim(),
    summaryCitations: resolveCitations(report.summary.span_ids, citationIndex),
    sections: report.sections.map((section) => toSectionDisplay(section, citationIndex)),
  };
}

export function ownerDisplayLabel(state: Pick<WorkspaceState, "vault_unlocked" | "owner_display_name">): string {
  if (!state.vault_unlocked) return "Local owner";
  const owner = state.owner_display_name?.trim();
  return owner ? owner : "Local owner";
}

function buildCitationIndex(citationCards: readonly CitationCard[]): ReadonlyMap<string, CitationCard> {
  const index = new Map<string, CitationCard>();
  for (const card of citationCards) {
    if (!isNonEmpty(card.span_id) || index.has(card.span_id)) throw new ProjectReportContractError();
    index.set(card.span_id, card);
  }
  return index;
}

function validateSummary(summary: GroundedStatement, citationIndex: ReadonlyMap<string, CitationCard>): void {
  if (!isNonEmpty(summary.statement)) throw new ProjectReportContractError();
  validateSpanIds(summary.span_ids, citationIndex, true);
}

function validateSections(
  sections: readonly ProjectReportSection[],
  citationIndex: ReadonlyMap<string, CitationCard>,
): void {
  if (sections.length !== PROJECT_REPORT_SECTION_KEYS.length) throw new ProjectReportContractError();

  sections.forEach((section, index) => {
    const expectedKey = PROJECT_REPORT_SECTION_KEYS[index];
    if (section.key !== expectedKey) throw new ProjectReportContractError();
    if (!isNonEmpty(section.headline) || !isNonEmpty(section.detail)) throw new ProjectReportContractError();

    if (section.status === "evidence_gap") {
      const presentation = SECTION_PRESENTATION[section.key];
      if (section.span_ids.length !== 0) throw new ProjectReportContractError();
      if (section.headline !== "No verified status available") throw new ProjectReportContractError();
      if (section.detail !== presentation.evidenceGapDetail) throw new ProjectReportContractError();
      return;
    }

    validateSpanIds(section.span_ids, citationIndex, true);
  });
}

function validateAnalysisConsistency(
  sections: readonly ProjectReportSection[],
  analysisStatus: AnalysisStatus,
  continuityBreak: GroundedStatement | null,
): void {
  const attentionSections = sections.filter((section) => section.status === "attention");

  if (analysisStatus === "no_material_break_found") {
    if (continuityBreak !== null || attentionSections.length !== 0) throw new ProjectReportContractError();
    return;
  }

  if (continuityBreak === null || attentionSections.length === 0) throw new ProjectReportContractError();
  const breakSpans = new Set(continuityBreak.span_ids);
  if (!attentionSections.some((section) => section.span_ids.some((spanId) => breakSpans.has(spanId)))) {
    throw new ProjectReportContractError();
  }
}

function validateSpanIds(
  spanIds: readonly string[],
  citationIndex: ReadonlyMap<string, CitationCard>,
  requireAtLeastOne: boolean,
): void {
  if (requireAtLeastOne && spanIds.length === 0) throw new ProjectReportContractError();
  const unique = new Set<string>();
  for (const spanId of spanIds) {
    if (!isNonEmpty(spanId) || unique.has(spanId) || !citationIndex.has(spanId)) {
      throw new ProjectReportContractError();
    }
    unique.add(spanId);
  }
}

function resolveCitations(
  spanIds: readonly string[],
  citationIndex: ReadonlyMap<string, CitationCard>,
): readonly ReportCitationDisplay[] {
  return spanIds.map((spanId) => {
    const card = citationIndex.get(spanId);
    if (!card) throw new ProjectReportContractError();
    return {
      spanId: card.span_id,
      evidenceId: card.evidence_id,
      exactText: card.exact_text,
      title: card.title,
      authorOrActor: card.author_or_actor,
      timestamp: card.timestamp,
      sourceType: card.source_type,
      provenance: card.provenance,
      sourceStatus: card.source_status,
    };
  });
}

function toSectionDisplay(
  section: ProjectReportSection,
  citationIndex: ReadonlyMap<string, CitationCard>,
): ProjectReportSectionDisplay {
  const sectionPresentation = SECTION_PRESENTATION[section.key];
  const statusPresentation = STATUS_PRESENTATION[section.status];
  return {
    key: section.key,
    label: sectionPresentation.label,
    icon: sectionPresentation.icon,
    status: section.status,
    statusLabel: statusPresentation.label,
    tone: statusPresentation.tone,
    headline: section.headline.trim(),
    detail: section.detail.trim(),
    citations: resolveCitations(section.span_ids, citationIndex),
  };
}

function isNonEmpty(value: string): boolean {
  return value.trim().length > 0;
}
