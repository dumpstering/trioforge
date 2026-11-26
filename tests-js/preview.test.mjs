// The preview script (scripts/preview.mjs) and the browser tests' configuration (playwright.config.mjs) decide where a build goes and which results the second (exalt)
// preview is built from. Both are worked out by plain functions (scripts/preview-plan.mjs), tested here without a browser or a build.

import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import config from "../playwright.config.mjs";
import { ANALYTICS_TOKEN } from "../playwright.config.mjs";
import { BUILD_SETTING_VARIABLES, DEFAULT_DIST, PREVIEW_ANALYTICS_VARIABLE, RELEASE_DIST, buildSettings, distFolder, exaltResults } from "../scripts/preview-plan.mjs";

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
    expect(config.webServer.map((server) => server.env.TRIOFORGE_PREVIEW_DIST)).toEqual(["site/dist-e2e", "site/dist-exalt", "site/dist-analytics"]);
  });
});

describe("the settings a preview gives the site build", () => {
  const token = "0123456789abcdef0123456789abcdef";

  it("are none by default: a preview has no page counts, whatever the shell holds for a release", () => {
    const given = { PATH: "p", TRIOFORGE_ANALYTICS_TOKEN: "fedcba9876543210fedcba9876543210", TRIOFORGE_GOOGLE_VERIFICATION: "google0123456789abcdef.html" };
    const made = buildSettings(given);
    expect(made.args).toEqual([]);
    expect(made.env).toEqual({ PATH: "p" });
    expect(Object.keys(made.env).filter((name) => BUILD_SETTING_VARIABLES.includes(name))).toEqual([]);
    expect(given.TRIOFORGE_ANALYTICS_TOKEN, "the given environment is not changed").toBeDefined();
    expect(buildSettings({ [PREVIEW_ANALYTICS_VARIABLE]: "" }).args).toEqual([]);
  });

  it("are the token of $TRIOFORGE_PREVIEW_ANALYTICS_TOKEN, which only the third server of the browser tests sets", () => {
    expect(buildSettings({ [PREVIEW_ANALYTICS_VARIABLE]: token }).args).toEqual(["--analytics-token", token]);
    expect(config.webServer.map((server) => server.env[PREVIEW_ANALYTICS_VARIABLE])).toEqual([undefined, undefined, token]);
    expect(ANALYTICS_TOKEN).toBe(token);
  });

  it("refuse a token that is not 32 lower-case hex characters (the build refuses capitals too), without repeating it", () => {
    for (const value of ["abc", `${token}0`, token.slice(1), "g".repeat(32), ` ${token}`, `${token}\n`, token.toUpperCase(), `${token.slice(1)}A`]) {
      expect(() => buildSettings({ [PREVIEW_ANALYTICS_VARIABLE]: value }), JSON.stringify(value)).toThrow(/32 lower-case hex/);
      try {
        buildSettings({ [PREVIEW_ANALYTICS_VARIABLE]: value });
      } catch (error) {
        expect(error.message).not.toContain(value.trim() || "\u0000");
      }
    }
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
