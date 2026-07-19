import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const appSource = readFileSync(join(process.cwd(), "src", "App.tsx"), "utf-8");
const liveProjectFlowSource = readFileSync(
  join(process.cwd(), "src", "components", "LiveProjectFlow.tsx"),
  "utf-8",
);

describe("Project Report runtime boundary", () => {
  it("still renders the demonstration report views from the synthetic demo workspace data", () => {
    expect(appSource).toMatch(/from\s+["']\.\/data\/demoWorkspace["']/);
  });

  it("wires a real, non-demo entry point into the running App shell", () => {
    expect(appSource).toMatch(/from\s+["']\.\/components\/LiveProjectFlow["']/);
  });

  it("only the real Live Project entry point imports the Project Report adapter and the Bridge session, never the synthetic demo workspace", () => {
    expect(liveProjectFlowSource).toMatch(/from\s+["']\.\.\/bridge\/projectReportProjection["']/);
    expect(liveProjectFlowSource).toMatch(/from\s+["']\.\.\/bridge\/session["']/);
    expect(liveProjectFlowSource).not.toMatch(/demoWorkspace/);
  });
});
