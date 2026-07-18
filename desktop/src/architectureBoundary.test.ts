import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const appSource = readFileSync(join(process.cwd(), "src", "App.tsx"), "utf-8");

describe("Project Report runtime boundary", () => {
  it("does not import the Project Report adapter into the running App shell", () => {
    expect(appSource).not.toMatch(/projectReportProjection/);
  });

  it("still renders the report views from the synthetic demo workspace data", () => {
    expect(appSource).toMatch(/from\s+["']\.\/data\/demoWorkspace["']/);
  });
});
