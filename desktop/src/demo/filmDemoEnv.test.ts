import { afterEach, describe, expect, it } from "vitest";

import { filmDemoConfig, filmDemoEnabled } from "./filmDemoEnv";

const ENV_KEYS = [
  "VITE_CONTINUITY_FILM_DEMO",
  "VITE_CONTINUITY_FILM_DEMO_ARTIFACT_ROOT",
  "VITE_CONTINUITY_FILM_DEMO_VAULT_PATH",
  "VITE_CONTINUITY_FILM_DEMO_OWNER_NAME",
  "VITE_CONTINUITY_FILM_DEMO_QUESTION",
  "VITE_CONTINUITY_FILM_DEMO_PASSWORD",
] as const;

function env(): Record<string, string | undefined> {
  return import.meta.env as unknown as Record<string, string | undefined>;
}

function clearEnv(): void {
  for (const key of ENV_KEYS) {
    delete env()[key];
  }
}

afterEach(() => {
  clearEnv();
});

describe("filmDemoEnv", () => {
  it("is unavailable with no environment configured at all", () => {
    clearEnv();

    expect(filmDemoEnabled()).toBe(false);
    expect(filmDemoConfig()).toBeNull();
  });

  it("stays unavailable when every parameter is set but the flag itself is not \"1\"", () => {
    clearEnv();
    env().VITE_CONTINUITY_FILM_DEMO = "0";
    env().VITE_CONTINUITY_FILM_DEMO_ARTIFACT_ROOT = "C:/demo/aurora";
    env().VITE_CONTINUITY_FILM_DEMO_VAULT_PATH = "C:/demo/vault";
    env().VITE_CONTINUITY_FILM_DEMO_OWNER_NAME = "Demo Owner";
    env().VITE_CONTINUITY_FILM_DEMO_QUESTION = "What is the current project state?";
    env().VITE_CONTINUITY_FILM_DEMO_PASSWORD = "secret";

    expect(filmDemoEnabled()).toBe(false);
    expect(filmDemoConfig()).toBeNull();
  });

  it("stays unavailable when the flag is set but a required parameter is missing", () => {
    clearEnv();
    env().VITE_CONTINUITY_FILM_DEMO = "1";
    env().VITE_CONTINUITY_FILM_DEMO_ARTIFACT_ROOT = "C:/demo/aurora";
    env().VITE_CONTINUITY_FILM_DEMO_VAULT_PATH = "C:/demo/vault";
    env().VITE_CONTINUITY_FILM_DEMO_OWNER_NAME = "Demo Owner";
    env().VITE_CONTINUITY_FILM_DEMO_QUESTION = "What is the current project state?";
    // password intentionally left unset

    expect(filmDemoConfig()).toBeNull();
  });

  it("is available only once the flag and every parameter are explicitly set", () => {
    clearEnv();
    env().VITE_CONTINUITY_FILM_DEMO = "1";
    env().VITE_CONTINUITY_FILM_DEMO_ARTIFACT_ROOT = "C:/demo/aurora";
    env().VITE_CONTINUITY_FILM_DEMO_VAULT_PATH = "C:/demo/vault";
    env().VITE_CONTINUITY_FILM_DEMO_OWNER_NAME = "Demo Owner";
    env().VITE_CONTINUITY_FILM_DEMO_QUESTION = "What is the current project state?";
    env().VITE_CONTINUITY_FILM_DEMO_PASSWORD = "secret";

    expect(filmDemoEnabled()).toBe(true);
    expect(filmDemoConfig()).toEqual({
      artifactRoot: "C:/demo/aurora",
      vaultPath: "C:/demo/vault",
      ownerName: "Demo Owner",
      question: "What is the current project state?",
      password: "secret",
    });
  });
});
