export type BridgeCommandName =
  | "initialize_vault"
  | "unlock_vault"
  | "lock_vault"
  | "load_project"
  | "scope_project_sources"
  | "confirm_source_scope"
  | "analyze_project"
  | "send_message"
  | "confirm_attestation"
  | "confirm_analysis_revision"
  | "get_workspace_state"
  | "diagnostic_prepare_workspace"
  | "diagnostic_run_scoping"
  | "diagnostic_confirm_scope"
  | "diagnostic_run_tamper_check"
  | "diagnostic_reset";

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

/**
 * Safe, non-secret run-observability metadata read from the Codex
 * controller's own retained session state. Never a local path, prompt,
 * stderr, password, evidence/oracle content, or internal exception:
 * `codex_session_id`/`controller_session_id` are opaque UUIDs, and both
 * fingerprints are SHA-256 hex digests of workspace content, not paths.
 */
export interface RunIdentity {
  readonly controller_session_id: string;
  readonly codex_session_id: string | null;
  readonly mixed_workspace_fingerprint: string;
  readonly approved_workspace_fingerprint: string | null;
  readonly reporting_resumed_retained_session: boolean;
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
  readonly run_identity?: RunIdentity;
}

export type SourceAssociationStatus = "included" | "excluded" | "ambiguous";
export type SourceDecisionBasis =
  | "explicit_target"
  | "corroborated_context"
  | "explicit_other_project"
  | "corroborated_other_project"
  | "conflicting_context"
  | "insufficient_context";
export type SourceFinalStatus = "included" | "excluded";
export type SourceScopingStatus = "none" | "pending_review" | "approved" | "invalid";

export interface SourceScopingDecision {
  readonly evidence_id: string;
  readonly association_status: SourceAssociationStatus;
  readonly basis: SourceDecisionBasis;
  readonly rationale: string;
  readonly span_ids: readonly string[];
  readonly related_evidence_ids: readonly string[];
}

export interface SourceScopingResult {
  readonly schema_version: "1.0";
  readonly target_project: string;
  readonly anchor_evidence_ids: readonly string[];
  readonly decisions: readonly SourceScopingDecision[];
  readonly selected_evidence_ids: readonly string[];
  readonly ambiguous_evidence_ids: readonly string[];
  readonly excluded_evidence_ids: readonly string[];
}

export interface ReviewedSourceDecision {
  readonly evidence_id: string;
  readonly final_status: SourceFinalStatus;
  readonly model_status: SourceAssociationStatus;
  readonly basis: SourceDecisionBasis;
  readonly rationale: string;
  readonly span_ids: readonly string[];
  readonly related_evidence_ids: readonly string[];
  readonly user_overridden: boolean;
}

export interface ApprovedSourceScope {
  readonly schema_version: "1.0";
  readonly scope_id: string;
  readonly target_project: string;
  readonly reviewed_decisions: readonly ReviewedSourceDecision[];
  readonly approved_evidence_ids: readonly string[];
  readonly excluded_evidence_ids: readonly string[];
  readonly user_resolved_evidence_ids: readonly string[];
  readonly evidence_fingerprints: readonly (readonly [string, string])[];
  readonly created_at: string;
}

export interface ScopeProjectSourcesData {
  readonly project: string;
  readonly source_scope: SourceScopingResult;
  readonly citation_cards: readonly CitationCard[];
  readonly run_identity?: RunIdentity;
}

export interface ConfirmSourceScopeData {
  readonly project: string;
  readonly evidence_count: number;
  readonly approved_source_scope: ApprovedSourceScope;
  readonly persisted: boolean;
  readonly run_identity?: RunIdentity;
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
  readonly source_scoping_status?: SourceScopingStatus;
  readonly source_scope?: SourceScopingResult | null;
  readonly approved_source_scope?: ApprovedSourceScope | null;
  readonly source_scope_persisted?: boolean;
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

export type DiagnosticPhase =
  | "idle"
  | "workspace_ready"
  | "awaiting_review"
  | "completed"
  | "tampered";

export interface DiagnosticDecision {
  readonly evidence_id: string;
  readonly association_status: SourceAssociationStatus;
  readonly basis: SourceDecisionBasis;
  readonly rationale: string;
}

export interface DiagnosticPrepareData {
  readonly phase: DiagnosticPhase;
  readonly input_fingerprint_prefix: string;
}

export interface DiagnosticScopingData {
  readonly phase: DiagnosticPhase;
  readonly target_project: string;
  readonly decisions: readonly DiagnosticDecision[];
}

export type DiagnosticClaimStatus = "PASS" | "FAIL";

export interface DiagnosticClaim {
  readonly name: string;
  readonly status: DiagnosticClaimStatus;
  readonly observed: string;
}

export interface DiagnosticReportData {
  readonly phase: DiagnosticPhase;
  readonly result: DiagnosticClaimStatus;
  readonly codex_session_id: string;
  readonly claims: readonly DiagnosticClaim[];
}

export interface DiagnosticResetData {
  readonly phase: DiagnosticPhase;
}

export type BridgeCommand =
  | { readonly command: "initialize_vault"; readonly path: string; readonly password: string; readonly owner_name?: string }
  | { readonly command: "unlock_vault"; readonly path: string; readonly password: string }
  | { readonly command: "lock_vault" }
  | { readonly command: "load_project"; readonly artifact_root: string }
  | { readonly command: "scope_project_sources"; readonly target_project?: string }
  | { readonly command: "confirm_source_scope"; readonly overrides: Readonly<Record<string, SourceFinalStatus>> }
  | { readonly command: "analyze_project"; readonly question: string }
  | { readonly command: "send_message"; readonly message: string; readonly revision_candidate?: unknown }
  | { readonly command: "confirm_attestation"; readonly proposal_id: string }
  | { readonly command: "confirm_analysis_revision"; readonly proposal_id: string }
  | { readonly command: "get_workspace_state" }
  | { readonly command: "diagnostic_prepare_workspace" }
  | { readonly command: "diagnostic_run_scoping" }
  | { readonly command: "diagnostic_confirm_scope"; readonly overrides: Readonly<Record<string, SourceFinalStatus>> }
  | { readonly command: "diagnostic_run_tamper_check" }
  | { readonly command: "diagnostic_reset" };

export interface BridgeCommandResultMap {
  readonly initialize_vault: SessionData;
  readonly unlock_vault: SessionData;
  readonly lock_vault: LockVaultData;
  readonly load_project: LoadProjectData;
  readonly scope_project_sources: ScopeProjectSourcesData;
  readonly confirm_source_scope: ConfirmSourceScopeData;
  readonly analyze_project: AnalysisData;
  readonly send_message: ConversationData;
  readonly confirm_attestation: ConfirmAttestationData;
  readonly confirm_analysis_revision: ConfirmAnalysisRevisionData;
  readonly get_workspace_state: WorkspaceState;
  readonly diagnostic_prepare_workspace: DiagnosticPrepareData;
  readonly diagnostic_run_scoping: DiagnosticScopingData;
  readonly diagnostic_confirm_scope: DiagnosticReportData;
  readonly diagnostic_run_tamper_check: DiagnosticReportData;
  readonly diagnostic_reset: DiagnosticResetData;
}
