export type ProjectKey = "aurora" | "meridian" | "ember";

export type ViewName = "auroraReport" | "workspace" | "breakDetail" | "genericReport";

export type DrawerName = "sources" | "conversation" | null;

export type EvidenceType = "EML" | "XLSX" | "ICS" | "PDF" | "MD" | "TEXT";

export interface EvidenceRecord {
  readonly id: string;
  readonly type: EvidenceType;
  readonly title: string;
  readonly author: string;
  readonly time: string;
  readonly timestamp: string;
  readonly filename: string;
  readonly quote: string;
  readonly role?: string;
}

export type StatusTone = "verified" | "attention" | "gap" | "neutral";

export interface StatusRow {
  readonly label: string;
  readonly icon: string;
  readonly title: string;
  readonly description: string;
  readonly status: string;
  readonly tone: StatusTone;
}

export interface SyntheticProjectReport {
  readonly key: Exclude<ProjectKey, "aurora">;
  readonly title: string;
  readonly sourceCount: number;
  readonly updatedLabel: string;
  readonly summaryLabel: string;
  readonly workspaceDescription: string;
  readonly subtitle: string;
  readonly summary: string;
  readonly detail: string;
  readonly mode: "on-track" | "incomplete";
  readonly sideTitle: string;
  readonly sideCopy: string;
  readonly rows: readonly StatusRow[];
}

export interface ConversationMessage {
  readonly id: string;
  readonly author: "agent" | "user";
  readonly text: string;
  readonly citations?: readonly string[];
}

export interface AuthenticatedAttestation extends EvidenceRecord {
  readonly type: "TEXT";
  readonly role: "Authenticated User Attestation";
}
