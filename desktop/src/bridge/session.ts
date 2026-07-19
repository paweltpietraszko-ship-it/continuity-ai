import type {
  AnalysisData,
  BridgeCommand,
  BridgeCommandResultMap,
  ConfirmAnalysisRevisionData,
  ConfirmAttestationData,
  ConfirmSourceScopeData,
  ConversationData,
  DiagnosticPrepareData,
  DiagnosticReportData,
  DiagnosticResetData,
  DiagnosticScopingData,
  ScopeProjectSourcesData,
  SourceFinalStatus,
  WorkspaceState,
} from "./contracts";
import { desktopBridge } from "./client";

export interface BridgeTransport {
  start(): Promise<unknown>;
  request<TCommand extends BridgeCommand>(
    command: TCommand,
  ): Promise<BridgeCommandResultMap[TCommand["command"]]>;
}

export interface RestoredSession {
  readonly stateBeforeProjectLoad: WorkspaceState;
  readonly stateAfterProjectLoad: WorkspaceState;
}

export class ContinuitySession {
  constructor(private readonly transport: BridgeTransport = desktopBridge) {}

  async initializeVault(path: string, password: string, ownerName: string): Promise<WorkspaceState> {
    await this.transport.start();
    await this.transport.request({ command: "initialize_vault", path, password, owner_name: ownerName });
    return this.workspaceState();
  }

  async unlockVault(path: string, password: string): Promise<WorkspaceState> {
    await this.transport.start();
    await this.transport.request({ command: "unlock_vault", path, password });
    return this.workspaceState();
  }

  async loadProject(artifactRoot: string): Promise<WorkspaceState> {
    await this.transport.request({ command: "load_project", artifact_root: artifactRoot });
    return this.workspaceState();
  }

  async scopeProjectSources(targetProject?: string): Promise<ScopeProjectSourcesData> {
    return this.transport.request(
      targetProject !== undefined
        ? { command: "scope_project_sources", target_project: targetProject }
        : { command: "scope_project_sources" },
    );
  }

  async confirmSourceScope(
    overrides: Readonly<Record<string, SourceFinalStatus>>,
  ): Promise<ConfirmSourceScopeData> {
    return this.transport.request({ command: "confirm_source_scope", overrides });
  }

  async analyzeProject(question: string): Promise<{ analysis: AnalysisData; state: WorkspaceState }> {
    const analysis = await this.transport.request({ command: "analyze_project", question });
    const state = await this.workspaceState();
    return { analysis, state };
  }

  async restoreAfterProcessRestart(
    vaultPath: string,
    password: string,
    artifactRoot: string,
  ): Promise<RestoredSession> {
    await this.transport.start();
    await this.transport.request({ command: "unlock_vault", path: vaultPath, password });
    const stateBeforeProjectLoad = await this.workspaceState();
    await this.transport.request({ command: "load_project", artifact_root: artifactRoot });
    const stateAfterProjectLoad = await this.workspaceState();
    return { stateBeforeProjectLoad, stateAfterProjectLoad };
  }

  async sendMessage(message: string): Promise<ConversationData> {
    return this.transport.request({ command: "send_message", message });
  }

  async confirmAttestation(proposalId: string): Promise<ConfirmAttestationData> {
    return this.transport.request({ command: "confirm_attestation", proposal_id: proposalId });
  }

  async confirmAnalysisRevision(proposalId: string): Promise<ConfirmAnalysisRevisionData> {
    return this.transport.request({ command: "confirm_analysis_revision", proposal_id: proposalId });
  }

  async lockVault(): Promise<WorkspaceState> {
    await this.transport.request({ command: "lock_vault" });
    return this.workspaceState();
  }

  async workspaceState(): Promise<WorkspaceState> {
    return this.transport.request({ command: "get_workspace_state" });
  }

  async prepareDiagnosticWorkspace(): Promise<DiagnosticPrepareData> {
    return this.transport.request({ command: "diagnostic_prepare_workspace" });
  }

  async runDiagnosticScoping(): Promise<DiagnosticScopingData> {
    return this.transport.request({ command: "diagnostic_run_scoping" });
  }

  async confirmDiagnosticScope(
    overrides: Readonly<Record<string, SourceFinalStatus>>,
  ): Promise<DiagnosticReportData> {
    return this.transport.request({ command: "diagnostic_confirm_scope", overrides });
  }

  async runDiagnosticTamperCheck(): Promise<DiagnosticReportData> {
    return this.transport.request({ command: "diagnostic_run_tamper_check" });
  }

  async resetDiagnosticState(): Promise<DiagnosticResetData> {
    return this.transport.request({ command: "diagnostic_reset" });
  }
}

export const continuitySession = new ContinuitySession();
