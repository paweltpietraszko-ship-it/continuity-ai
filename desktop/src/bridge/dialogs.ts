import { open, save } from "@tauri-apps/plugin-dialog";

export async function selectArtifactRoot(): Promise<string | null> {
  const selected = await open({
    directory: true,
    multiple: false,
    title: "Select project artifact folder",
  });
  return typeof selected === "string" ? selected : null;
}

export async function selectExistingVault(): Promise<string | null> {
  const selected = await open({
    directory: false,
    multiple: false,
    title: "Open Continuity AI vault",
  });
  return typeof selected === "string" ? selected : null;
}

export async function selectNewVaultPath(): Promise<string | null> {
  return save({
    title: "Create encrypted Continuity AI vault",
    defaultPath: "continuity-ai.vault",
  });
}
