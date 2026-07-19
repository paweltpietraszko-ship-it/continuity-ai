/**
 * Film Demo Director v0.1 — explicit-flag configuration reader.
 *
 * The whole mode exists only when `CONTINUITY_FILM_DEMO=1` is set in the
 * process environment that launched `npm run tauri dev` (see
 * `scripts/run_film_demo.ps1`); Vite's `envPrefix` (`VITE_`, see
 * `vite.config.ts`) is the only channel by which a plain process
 * environment variable reaches this browser-side code, so the launcher
 * mirrors the flag and its parameters under `VITE_CONTINUITY_FILM_DEMO*`.
 * There is no other way to enable this mode (no UI toggle, no default-on
 * fallback) and no default artifact root, vault path, or password is ever
 * baked in here.
 */

export interface FilmDemoConfig {
  readonly artifactRoot: string;
  readonly vaultPath: string;
  readonly ownerName: string;
  readonly question: string;
  readonly password: string;
}

function readEnv(key: string): string | undefined {
  const value = (import.meta.env as Record<string, string | undefined>)[key];
  return typeof value === "string" && value.trim() ? value : undefined;
}

export function filmDemoEnabled(): boolean {
  return readEnv("VITE_CONTINUITY_FILM_DEMO") === "1";
}

/**
 * Returns the full launcher-supplied configuration only when the flag is
 * set *and* every required parameter was actually supplied; otherwise
 * `null`, so a half-configured environment never silently starts the
 * scenario with a fabricated or missing value.
 */
export function filmDemoConfig(): FilmDemoConfig | null {
  if (!filmDemoEnabled()) return null;

  const artifactRoot = readEnv("VITE_CONTINUITY_FILM_DEMO_ARTIFACT_ROOT");
  const vaultPath = readEnv("VITE_CONTINUITY_FILM_DEMO_VAULT_PATH");
  const ownerName = readEnv("VITE_CONTINUITY_FILM_DEMO_OWNER_NAME");
  const question = readEnv("VITE_CONTINUITY_FILM_DEMO_QUESTION");
  const password = readEnv("VITE_CONTINUITY_FILM_DEMO_PASSWORD");

  if (!artifactRoot || !vaultPath || !ownerName || !question || !password) {
    return null;
  }

  return { artifactRoot, vaultPath, ownerName, question, password };
}
