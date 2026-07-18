export type BridgeCommandName =
  | "initialize_vault"
  | "unlock_vault"
  | "lock_vault"
  | "load_project"
  | "analyze_project"
  | "send_message"
  | "confirm_attestation"
  | "confirm_analysis_revision"
  | "get_workspace_state";

export interface PublicBridgeError {
  readonly code: string;
  readonly message: string;
  readonly object_id: null;
}

export interface BridgeSuccess<TData> {
  readonly ok: true;
  readonly command: BridgeCommandName;
  readonly data: TData;
}

export interface BridgeFailure {
  readonly ok: false;
  readonly command: BridgeCommandName | null;
  readonly error: PublicBridgeError;
}

export type BridgeEnvelope<TData> = BridgeSuccess<TData> | BridgeFailure;

export interface BridgeStatus {
  readonly running: boolean;
  readonly process_id: number | null;
}

export interface SessionData {
  readonly session_id: string;
  readonly owner_display_name: string;
}

export interface LockVaultData {
  readonly locked: true;
}

export interface NeutralEvidenceRecord {
  readonly source_id: string;
  readonly evidence_id: string;
  readonly author: string;
  readonly timestamp: string;
  readonly source_type: string;
  readonly title: string;
  readonly uri: string;
  readonly artifact_sha256: string;
  readonly content: string;
}

export interface LoadProjectData {
  readonly project: string;
  readonly artifact_evidence_count: number;
  readonly evidence_count: number;
  readonly evidence_records: readonly NeutralEvidenceRecord[];
}

export type RetainedAnalysisStatus = "none" | "valid" | "invalid";
export type AnalysisStatus = "break_found" | "no_material_break_found";
export type ContinuityBreakKind = "propagation_break" | "decision_provenance_not_found" | null;
export type PropagationRole = "approved_decision" | "reflects_decision" | "conflicts_with_decision" | "none";
export type CitationSourceStatus = "snapshot" | "source_changed_since_analysis";
export type EvidenceProvenance = "artifact" | "authenticated_user_attestation";

export type ProjectReportSectionKey =
  | "decision"
  | "budget"
  | "schedule"
  | "operations"
  | "readiness"
  | "casting"
  | "agreements";

export type ProjectReportSectionStatus =
  | "confirmed"
  | "attention"
  | "evidence_gap"
  | "not_applicable";

export interface GroundedStatement {
  readonly statement: string;
  readonly span_ids: readonly string[];
}

export interface ProjectReportSection {
  readonly key: ProjectReportSectionKey;
  readonly status: ProjectReportSectionStatus;
  readonly headline: string;
  readonly detail: string;
  readonly span_ids: readonly string[];
}

export interface ProjectReport {
  readonly summary: GroundedStatement;
  readonly sections: readonly ProjectReportSection[];
}

export interface SemanticAnnotation {
  readonly evidence_id: string;
  readonly propagation_role: PropagationRole;
  readonly context_tags: readonly "urgency"[];
}

export interface CitationCard {
  readonly evidence_id: string;
  readonly span_id: string;
  readonly exact_text: string;
  readonly title: string;
  readonly author_or_actor: string;
  readonly timestamp: string;
  readonly source_type: string;
  readonly provenance: EvidenceProvenance;
  readonly source_status: CitationSourceStatus;
}

export interface AnalysisResultFields {
  readonly schema_version: "3.0";
  readonly analysis_status: AnalysisStatus;
  readonly continuity_break_kind: ContinuityBreakKind;
  readonly current_state: GroundedStatement;
  readonly semantic_annotations: readonly SemanticAnnotation[];
  readonly continuity_break: GroundedStatement | null;
  readonly next_action: GroundedStatement | null;
  readonly project_report: ProjectReport;
}

export interface AnalysisProjection extends AnalysisResultFields {
  readonly project: string;
  readonly citation_cards: readonly CitationCard[];
}

export interface AnalysisData extends AnalysisProjection {
  readonly analysis_id: string;
  readonly created_at: string;
  readonly prompt_version: "g03_reasoning_v3";
  readonly provider_id: string;
}

export interface WorkspaceStateBase {
  readonly vault_unlocked: boolean;
  readonly owner_display_name: string | null;
  readonly project: string | null;
  readonly artifact_evidence_count: number;
  readonly evidence_count: number;
  readonly evidence_records: readonly NeutralEvidenceRecord[];
  readonly retained_analysis_status: RetainedAnalysisStatus;
  readonly pending_attestation_count: number;
  readonly pending_revision_count: number;
}

export type WorkspaceState =
  | (WorkspaceStateBase & {
      readonly has_analysis: false;
      readonly project_report: null;
    })
  | (Omit<WorkspaceStateBase, "project" | "retained_analysis_status"> & {
      readonly has_analysis: true;
      readonly project: string;
      readonly retained_analysis_status: "valid";
      readonly project_report: ProjectReport;
    } & Omit<AnalysisProjection, "project" | "project_report">);

export interface AttestationProposal {
  readonly proposal_id: string;
  readonly statement: string;
  readonly session_id: string;
  readonly created_at: string;
  readonly channel: "text";
  readonly supersedes_evidence_id: string | null;
}

export interface AnalysisRevisionProposal {
  readonly proposal_id: string;
  readonly session_id: string;
  readonly created_at: string;
  readonly candidate: AnalysisResultFields;
}

export type ConversationKind =
  | "general"
  | "project_grounded"
  | "insufficient_evidence"
  | "attestation_proposal"
  | "analysis_revision_proposal";

export interface ConversationData {
  readonly kind: ConversationKind;
  readonly message: string;
  readonly citation_cards: readonly CitationCard[];
  readonly attestation_proposal: AttestationProposal | null;
  readonly analysis_revision_proposal: AnalysisRevisionProposal | null;
}

export interface ConfirmAttestationData extends AnalysisProjection {
  readonly evidence_id: string;
  readonly evidence_count: number;
}

export interface ConfirmAnalysisRevisionData extends AnalysisProjection {
  readonly confirmed: true;
  readonly proposal_id: string;
}

export type BridgeCommand =
  | { readonly command: "initialize_vault"; readonly path: string; readonly password: string; readonly owner_name?: string }
  | { readonly command: "unlock_vault"; readonly path: string; readonly password: string }
  | { readonly command: "lock_vault" }
  | { readonly command: "load_project"; readonly artifact_root: string }
  | { readonly command: "analyze_project"; readonly question: string }
  | { readonly command: "send_message"; readonly message: string; readonly revision_candidate?: unknown }
  | { readonly command: "confirm_attestation"; readonly proposal_id: string }
  | { readonly command: "confirm_analysis_revision"; readonly proposal_id: string }
  | { readonly command: "get_workspace_state" };

export interface BridgeCommandResultMap {
  readonly initialize_vault: SessionData;
  readonly unlock_vault: SessionData;
  readonly lock_vault: LockVaultData;
  readonly load_project: LoadProjectData;
  readonly analyze_project: AnalysisData;
  readonly send_message: ConversationData;
  readonly confirm_attestation: ConfirmAttestationData;
  readonly confirm_analysis_revision: ConfirmAnalysisRevisionData;
  readonly get_workspace_state: WorkspaceState;
}
