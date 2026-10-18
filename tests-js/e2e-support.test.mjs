// The browser tests (tests-e2e/) state what the page must show from the data files alone, with helpers of their own in
// tests-e2e/support.mjs. The helpers are plain functions, so they are tested here without a browser: every word and number
// they print for a row of "Wear this" must be the one the page prints, whatever kind of item the row holds.

import { describe, expect, it } from "vitest";
import { DASH, EMPTY_NAME, ITEM_SEALS, arrivalText, deityText, tierLabel } from "../pipeline/trioforge/site/static/format.js";
import { UNKNOWN_TO_THE_TEST_BROWSER, expectedKit, readHeadersFile, unknownToTheTestBrowser } from "../tests-e2e/support.mjs";

// an item row of a data file: [key, name, tier rule, arrival, source, evidence, deities]
const DROP = ["w1", "Helm of the Test", "drop", 4, "Test Zone (a keeper)", "strict", []];
const QUEST = ["w2", "Cloak of the Quest", "fixed0", 0, "quest: Test Quest", "wiki", []];
const SUMMONED = ["w3", "Orb of Summoning", "spell", null, "Test Cleric spell", "wiki", []];
const LOCKED = ["w4", "Crown of the Faithful", "drop", 4, "Test Zone", "strict", ["The Tribunal", "Rodcet Nife"]];

describe("the kit the browser tests expect", () => {
  it("is worded as the page words it, for every kind of item and for an empty place", () => {
    const tier = 7;
    const rows = expectedKit({ kit: [DROP, QUEST, SUMMONED, LOCKED, null] }, tier);
    const page = [DROP, QUEST, SUMMONED, LOCKED].map((item) => ({
      name: item[1],
      deity: deityText(item[6]),
      tier: tierLabel(tier),
      arrival: arrivalText(item[3]),
      source: item[4],
      seal: ITEM_SEALS[item[5]][0],
    }));
    expect(rows.slice(0, 4)).toEqual(page);
    expect(rows[4]).toEqual({ name: EMPTY_NAME, deity: "", tier: DASH, arrival: DASH, source: DASH, seal: DASH });
  });

  it("says spell rank for an item that arrives with no tier, never +null", () => {
    const [row] = expectedKit({ kit: [SUMMONED] }, 4);
    expect(row.arrival).toBe("spell rank");
    expect(expectedKit({ kit: [DROP, QUEST] }, 4).map((r) => r.arrival)).toEqual(["+4", "+0"]);
  });
});

describe("the console warnings the browser tests let pass", () => {
  const warning = (name) => `Error with Permissions-Policy header: Unrecognized feature: '${name}'.`;

  it("are the warnings of the test browser about the six Privacy Sandbox names it is built without", () => {
    expect(UNKNOWN_TO_THE_TEST_BROWSER).toHaveLength(6);
    for (const name of UNKNOWN_TO_THE_TEST_BROWSER) expect(unknownToTheTestBrowser(warning(name)), name).toBe(true);
  });

  it("are only those: a mistyped name, any other warning and another kind of message still count as a problem of the page", () => {
    expect(unknownToTheTestBrowser(warning("atribution-reporting"))).toBe(false); // a typo in the header
    expect(unknownToTheTestBrowser(warning("camera"))).toBe(false);
    expect(unknownToTheTestBrowser("Error with Permissions-Policy header: Origin trial controlled feature not enabled: 'shared-storage'.")).toBe(false);
    expect(unknownToTheTestBrowser("Refused to load the stylesheet")).toBe(false);
    expect(unknownToTheTestBrowser(`${warning("shared-storage")} and more`)).toBe(false);
  });

  it("name features that the header does name, so that the list holds nothing the header lost", () => {
    const named = readHeadersFile().get("permissions-policy").split(/,\s*/).map((part) => part.replace("=()", ""));
    for (const name of UNKNOWN_TO_THE_TEST_BROWSER) expect(named, name).toContain(name);
  });
});
