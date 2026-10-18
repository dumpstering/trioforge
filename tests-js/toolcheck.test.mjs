import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import highsLoader from "highs";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));

// maximize x + y  subject to  x + 2y <= 4,  3x + y <= 6,  x, y integer >= 0.
// The LP relaxation optimum is 2.8; the integer optimum is 2. The "General"
// section is what makes x and y integer in the CPLEX LP format.
const TINY_MIP = `Maximize
 obj: x + y
Subject To
 c1: x + 2 y <= 4
 c2: 3 x + y <= 6
Bounds
 x >= 0
 y >= 0
General
 x y
End
`;

describe("highs-js", () => {
  it("solves the tiny MIP to the integer optimum", async () => {
    const highs = await highsLoader();
    const solution = highs.solve(TINY_MIP);
    expect(solution.Status).toBe("Optimal");
    expect(solution.ObjectiveValue).toBe(2);
  });
});

// ---- the pinned versions and the toolcheck script ----

describe("toolchain pins and scripts", () => {
  it("package.json pins every dependency to an exact version", () => {
    const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
    expect(pkg.dependencies).toEqual({ highs: "1.15.3" });
    expect(pkg.devDependencies).toEqual({
      "@axe-core/playwright": "4.13.0",
      "@playwright/test": "1.63.0",
      esbuild: "0.28.2",
      jsdom: "30.1.1",
      vitest: "5.0.2",
      wrangler: "4.144.0",
    });
  });

  it("scripts/toolcheck.mjs prints one highs-js-core line", () => {
    const out = execFileSync(process.execPath, ["scripts/toolcheck.mjs"], {
      cwd: repoRoot,
      encoding: "utf8",
    });
    expect(out.trim()).toMatch(/^highs-js-core (\d+\.\d+\.\d+|unknown)$/);
  }, 60000);
});
