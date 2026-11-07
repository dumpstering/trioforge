// The preview script (scripts/preview.mjs) and the browser tests' configuration (playwright.config.mjs) decide where a build goes and which results the second (exalt)
// preview is built from. Both are worked out by plain functions (scripts/preview-plan.mjs), tested here without a browser or a build.

import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import config from "../playwright.config.mjs";
import { DEFAULT_DIST, RELEASE_DIST, distFolder, exaltResults } from "../scripts/preview-plan.mjs";

const ROOT = resolve("/the/repository");
const inRoot = (folder) => resolve(ROOT, folder);

describe("where a preview is built", () => {
  it("is never site/dist, which holds only what `python -m trioforge.site.build --out site/dist` writes", () => {
    expect(RELEASE_DIST).toBe("site/dist");
    expect(DEFAULT_DIST).not.toBe(RELEASE_DIST);
    expect(distFolder(ROOT, {})).toBe(inRoot(DEFAULT_DIST));
  });

  it("is the folder $TRIOFORGE_PREVIEW_DIST names, when it is set", () => {
    expect(distFolder(ROOT, { TRIOFORGE_PREVIEW_DIST: "site/dist-other" })).toBe(inRoot("site/dist-other"));
  });

  it("is refused when $TRIOFORGE_PREVIEW_DIST names site/dist in any spelling, because the build replaces its output folder", () => {
    for (const value of ["site/dist", "./site/dist", "site/dist/", "site//dist", "site/../site/dist", inRoot("site/dist"), `${inRoot("site/dist")}/`]) {
      expect(() => distFolder(ROOT, { TRIOFORGE_PREVIEW_DIST: value }), value).toThrow(/site\/dist/);
    }
    for (const value of ["site/dist-e2e", "site/dist2", "site/distant", "dist", "site/dist/inner"]) {
      expect(() => distFolder(ROOT, { TRIOFORGE_PREVIEW_DIST: value }), value).not.toThrow();
    }
  });

  it("is a folder of its own for each server of the browser tests, and none of them is site/dist", () => {
    const folders = config.webServer.map((server) => distFolder(ROOT, server.env));
    expect(new Set(folders).size, "two servers must not build into one folder").toBe(folders.length);
    expect(folders).not.toContain(inRoot(RELEASE_DIST));
    expect(config.webServer.map((server) => server.env.TRIOFORGE_PREVIEW_DIST)).toEqual(["site/dist-e2e", "site/dist-exalt"]);
  });
});

describe("the results of the exalt preview", () => {
  it("are the given results as they are when they have the effects files of their own (real results do)", () => {
    expect(exaltResults({ usingFixture: false, hasEffects: true })).toEqual({ use: "given" });
    expect(exaltResults({ usingFixture: true, hasEffects: true })).toEqual({ use: "given" });
  });

  it("are a copy of the fixture results with the effects files made for them, when it is the fixture without them", () => {
    expect(exaltResults({ usingFixture: true, hasEffects: false })).toEqual({ use: "fixture-with-effects" });
  });

  it("refuse results that are not the fixture and have no effects files, in words that say what to do (the fixture's effects cannot be paired with other results' items)", () => {
    const plan = exaltResults({ usingFixture: false, hasEffects: false });
    expect(plan.use).toBe("refuse");
    expect(plan.message).toMatch(/effects\.json/);
    expect(plan.message).toMatch(/precompute|release/);
  });
});
