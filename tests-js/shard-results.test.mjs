import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import loadHighs from "highs";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";
import { ResultsError, checkResults, compareRow, parseSample, pythonRound2, readResults } from "./shard-results.mjs";

// The reading and the comparing of tests-js/shard-results.mjs, which tests-js/shard-parity.test.mjs holds the engine to the shards with: that Python's rounding is
// reproduced, that a sample names its chunks, and, above all, that the check can fail: a shard of the fixture changed in one view (its value, one place of its kit, its
// buffs or its haste) is reported as that view, with that difference first, and a folder that is not one run is refused.

const FIXTURE = fileURLToPath(new URL("../fixtures/site/results-solved/", import.meta.url));

// a solve takes a fraction of a second here, and the suite runs its files side by side: the time of a test is not the default five seconds
vi.setConfig({ testTimeout: 60_000 });

describe("pythonRound2 is Python's round(x, 2)", () => {
  it("rounds the exact value of the double, a tie to the even last digit", () => {
    // (the expected values are what Python's round gives) 0.125, 0.375, 0.625 and 0.875 are exact in binary: ties. 2.675, 1.005 and 0.285 are a little below their
    // decimals and 99.995 a little above, whatever they look like.
    expect([0.125, 0.375, 0.625, 0.875, 1.125, 1.375].map(pythonRound2)).toEqual([0.12, 0.38, 0.62, 0.88, 1.12, 1.38]);
    expect([2.675, 99.995, 1.005, 0.285].map(pythonRound2)).toEqual([2.67, 100, 1, 0.28]);
    expect([0, 0.004, 0.005, 0.0049999, 1234.5678, 15607.41, 17455.7, 1e12 + 0.5].map(pythonRound2)).toEqual([0, 0, 0.01, 0, 1234.57, 15607.41, 17455.7, 1e12 + 0.5]);
    expect([-0.125, -2.675].map(pythonRound2)).toEqual([-0.12, -2.67]);
  });

  it("agrees with toFixed(2) wherever the value is not an exact tie, on thousands of values the size of a value of F", () => {
    let seed = 20261016;
    const random = () => {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    };
    for (let n = 0; n < 20000; n += 1) {
      const x = random() * 40000 + (n % 3 === 0 ? 0 : random() * 1e-9);
      expect(pythonRound2(x)).toBe(Number(x.toFixed(2)));
    }
  });

  it("refuses what is not a finite number", () => {
    for (const bad of [NaN, Infinity, "1", null, undefined]) expect(() => pythonRound2(bad)).toThrow(ResultsError);
  });
});

describe("a sample is named i/n", () => {
  it("reads i/n for 0 <= i < n and nothing else", () => {
    expect(parseSample("0/1")).toEqual({ index: 0, count: 1 });
    expect(parseSample(" 3/20 ")).toEqual({ index: 3, count: 20 });
    for (const bad of ["", "1", "1/0", "20/20", "21/20", "-1/3", "1.5/2", "a/b", "1/2/3", "1 /2", "0/1000000"]) expect(() => parseSample(bad), bad).toThrow(ResultsError);
  });
});

describe("compareRow", () => {
  const places = Array.from({ length: 22 }, (_, at) => `P${at}`);
  const shard = { places };
  const kit = Array.from({ length: 22 }, () => null);
  kit[3] = "w80113";
  kit[9] = "w80158";
  const row = { race: "HUM", role: "balanced", tier: 4, setup: "dw", kit, F: 15607.41, buffs: [5, 9], haste: 66 };
  const answer = (changes = {}) => ({
    status: "optimal",
    F: Rational.fromNumber(15607.41),
    kit: kit.map((key) => (key === null ? null : { key, tier: 4 })),
    buffs: [9, 5],
    hasteAssumed: 66,
    ...changes,
  });

  it("finds nothing in an answer that is the row (the buffs are a set, and F is the value rounded as the shard rounds it)", () => {
    expect(compareRow(shard, row, answer())).toEqual([]);
    expect(compareRow(shard, row, answer({ F: new Rational(156074099999n, 10_000_000n) }))).toEqual([]); // 15607.4099999 rounds to 15607.41
  });

  it("names the first difference first: F, then the kit, then the buffs, then the haste", () => {
    const found = compareRow(shard, row, answer({ F: Rational.fromNumber(15607.42), kit: kit.map((key) => (key === "w80113" ? { key: "w80236", tier: 4 } : key === null ? null : { key, tier: 4 })), buffs: [5], hasteAssumed: 67 }));
    expect(found).toHaveLength(4);
    expect(found[0]).toMatch(/^F: shard 15607\.41, engine 15607\.42 /);
    expect(found[1]).toBe("kit: 1 place differs, the first P3: shard w80113, engine w80236");
    expect(found[2]).toBe("buffs: shard [5,9], engine [5]");
    expect(found[3]).toBe("haste assumed: shard 66, engine 67");
  });

  it("counts the places that differ, and says empty for an empty place", () => {
    const have = kit.map((key) => (key === null ? null : { key, tier: 4 }));
    have[3] = null;
    have[10] = { key: "w80392", tier: 4 };
    expect(compareRow(shard, row, answer({ kit: have }))).toEqual(["kit: 2 places differ, the first P3: shard w80113, engine empty"]);
  });

  it("says when the engine found no kit, or did not finish", () => {
    expect(compareRow(shard, row, answer({ status: "time_limit" }))[0]).toBe('the engine\'s solve ended "time_limit", not optimal');
    expect(compareRow(shard, row, answer({ F: null, kit: null }))).toContain("the engine found no kit");
  });
});

describe("the check can fail", () => {
  let highs;
  let scratch;
  beforeAll(async () => {
    highs = await loadHighs();
    scratch = mkdtempSync(join(tmpdir(), "shard-parity-"));
  });
  afterAll(() => {
    rmSync(scratch, { recursive: true, force: true });
  });

  let count = 0;
  /** A copy of the fixture with `change(shard documents by name, bundle, items, defaults)` done to it; the folder is removed with the scratch folder. */
  function changed(change) {
    const folder = join(scratch, `copy-${count++}`);
    cpSync(FIXTURE, folder, { recursive: true });
    const documents = {};
    const path = (name) => join(folder, "pal-mnk-ber", `${name}.json`);
    for (const name of ["strict-own", "strict-group", "wiki-own", "wiki-group", "defaults", "engine-l50"]) documents[name] = JSON.parse(readFileSync(path(name), "utf8"));
    change(documents);
    for (const [name, document] of Object.entries(documents)) writeFileSync(path(name), JSON.stringify(document));
    return folder;
  }

  /** The views of one row of a shard, solved and compared: the failures. The chunk of the row is the only one checked. */
  function checkRow(folder, shardName, at) {
    const results = readResults(folder);
    const [race, role, tier, setup] = JSON.parse(readFileSync(join(folder, "pal-mnk-ber", `${shardName}.json`), "utf8")).scenarios[at];
    const report = checkResults(results, {
      highs,
      directory: folder,
      select: (unit) => unit.shard.name === shardName && unit.chunk.role === role && unit.chunk.setup === setup && unit.chunk.tier === tier,
    });
    return { race, role, tier, setup, report };
  }

  it("finds no difference in the fixture as it is", () => {
    const { report } = checkRow(FIXTURE, "wiki-own", 0);
    expect(report.views).toBeGreaterThan(0);
    expect(report.failures).toEqual([]);
  });

  it("reports a view whose F differs by a hundredth, with F first", () => {
    const folder = changed((d) => {
      d["wiki-own"].scenarios[0][5] = Math.round((d["wiki-own"].scenarios[0][5] + 0.01) * 100) / 100;
    });
    const { race, report } = checkRow(folder, "wiki-own", 0);
    expect(report.failures).toHaveLength(1);
    expect(report.failures[0].name).toContain(`wiki/own ${race}`);
    expect(report.failures[0].first).toMatch(/^F: shard \d+(\.\d+)?, engine \d+(\.\d+)? \(exactly /);
    expect(report.failures[0].all).toHaveLength(1);
  });

  it("reports a view with one place of its kit changed, and says where the shard's item stands in the engine's pool", () => {
    let item;
    let place;
    const folder = changed((d) => {
      const shard = d["wiki-own"];
      const kit = [...shard.kits[shard.scenarios[0][4]]];
      place = kit.findIndex((index) => index >= 0);
      item = shard.items[kit[place]][0];
      kit[place] = shard.items.findIndex((row) => row[0] !== item && !kit.includes(shard.items.indexOf(row)));
      shard.kits.push(kit);
      shard.scenarios[0][4] = shard.kits.length - 1;
    });
    const { report } = checkRow(folder, "wiki-own", 0);
    expect(report.failures).toHaveLength(1);
    expect(report.failures[0].first).toMatch(new RegExp(`^kit: 1 place differs, the first ${readPlaceName(folder, place)}: shard w\\d+, engine ${item}$`));
    expect(report.failures[0].all).toHaveLength(1);
    expect(report.failures[0].shardItems).toHaveLength(1);
  });

  it("reports a view whose buffs differ", () => {
    const folder = changed((d) => {
      const shard = d["wiki-own"];
      shard.buff_sets.push([...shard.buff_sets[shard.scenarios[0][8]], 424242]);
      shard.scenarios[0][8] = shard.buff_sets.length - 1;
    });
    const { report } = checkRow(folder, "wiki-own", 0);
    expect(report.failures).toHaveLength(1);
    expect(report.failures[0].first).toMatch(/^buffs: shard \[.*424242\], engine \[/);
  });

  it("reports a view whose assumed haste differs", () => {
    const folder = changed((d) => {
      d["wiki-own"].scenarios[0][9] += 1;
    });
    const { report } = checkRow(folder, "wiki-own", 0);
    expect(report.failures).toHaveLength(1);
    expect(report.failures[0].first).toMatch(/^haste assumed: shard \d+, engine \d+$/);
  });

  it("reports every view that differs, and goes on after the first", () => {
    let rows = 0;
    const folder = changed((d) => {
      const shard = d["wiki-own"];
      const [, role, tier, setup] = shard.scenarios[0];
      for (const row of shard.scenarios) {
        if (row[1] === role && row[2] === tier && row[3] === setup) {
          row[9] += 1;
          rows += 1;
        }
      }
    });
    expect(rows).toBeGreaterThan(1); // the races of one view
    const { report } = checkRow(folder, "wiki-own", 0);
    expect(report.views).toBe(rows);
    expect(report.failures).toHaveLength(rows);
    expect(new Set(report.failures.map((failure) => failure.name)).size).toBe(rows);
    for (const failure of report.failures) expect(failure.first).toMatch(/^haste assumed: /);
  });

  it("holds defaults.json to the engine too: a changed margin is reported, by every sample (not the sample 0 alone) as well as by the whole folder", () => {
    const folder = changed((d) => {
      d.defaults.margin += 1;
    });
    const results = readResults(folder);
    for (const text of ["0/40", "3/40", "39/40"]) {
      const report = checkResults(results, { highs, directory: folder, sample: parseSample(text) });
      expect(report.failures, text).toEqual([]);
      expect(report.defaultsChecked, text).toBe(1);
      expect(report.defaults, text).toHaveLength(1);
      expect(report.defaults[0].first, text).toMatch(/^margin: file \d+(\.\d+)?, engine \d+(\.\d+)?$/);
    }
  });

  it("holds the value and the best setup of each race in defaults.json to the engine", () => {
    const folder = changed((d) => {
      d.defaults.races[0].F += 0.01;
      d.defaults.races[1].setup = d.defaults.races[1].setup === "dw" ? "2h" : "dw";
    });
    const report = checkResults(readResults(folder), { highs, directory: folder, sample: parseSample("0/40") });
    expect(report.defaults.map((found) => found.first.split(":")[0])).toEqual(["F", "best setup"]);
  });

  it("checks defaults.json in every sample, whatever its offset and its count, and without a defaults.json checks nothing of it", () => {
    const results = readResults(FIXTURE);
    const first = checkResults(results, { highs, directory: FIXTURE, sample: parseSample("0/20") });
    expect(first.defaultsChecked).toBe(1);
    expect(first.failures).toEqual([]);
    expect(first.chunks).toBeGreaterThan(2); // its own two chunks, and the chunks of the default view
    for (const text of ["1/20", "19/20", "7/999999", "999998/999999"]) {
      const report = checkResults(results, { highs, directory: FIXTURE, sample: parseSample(text) });
      expect(report.defaultsChecked, text).toBe(1);
      expect(report.failures, text).toEqual([]);
      expect(report.chunks, text).toBeGreaterThanOrEqual(1); // the chunks of the default view, and the sample's own if it has any
    }
    const folder = changed(() => {});
    rmSync(join(folder, "pal-mnk-ber", "defaults.json"));
    expect(checkResults(readResults(folder), { highs, directory: folder, sample: parseSample("0/40") }).defaultsChecked).toBe(0);
  });

  it("refuses a bundle made from other inputs than the item table", () => {
    const folder = changed((d) => {
      d["engine-l50"].inputs = "0".repeat(64);
    });
    expect(() => readResults(folder)).toThrow(/other inputs than items\.json/);
  });

  it("refuses a shard of another release than its bundle", () => {
    const folder = changed((d) => {
      d["wiki-own"].data_release = "data-2020-01-01";
    });
    expect(() => readResults(folder)).toThrow(/not of the data release and rules version of the bundle/);
  });

  it("refuses a shard that was not made with the tie stage, whose kits are not canonical", () => {
    const folder = changed((d) => {
      d["wiki-own"].solver.canonical = false;
    });
    expect(() => readResults(folder)).toThrow(/without the tie stage/);
  });

  it("refuses a shard that shows an item the item table lacks or describes otherwise", () => {
    const folder = changed((d) => {
      d["wiki-own"].items[0][6] = d["wiki-own"].items[0][6] === "strict" ? "wiki" : "strict";
    });
    expect(() => readResults(folder)).toThrow(/items\.json lacks or describes otherwise/);
  });

  it("refuses a shard whose pool had another size than the pool the item table makes", () => {
    const folder = changed((d) => {
      d["wiki-own"].pool += 1;
    });
    expect(() => readResults(folder)).toThrow(/pool made from items\.json has \d+ items, and wiki-own\.json says its pool had \d+/);
  });

  it("refuses a shard of a level that has no bundle", () => {
    const folder = changed((d) => {
      d["wiki-own"].level = 55;
    });
    expect(() => readResults(folder)).toThrow(/no bundle \(engine-l55\.json\)/);
  });

  it("refuses a folder with no trio in it, and a folder that is not there", () => {
    const empty = join(scratch, "empty");
    cpSync(FIXTURE, empty, { recursive: true });
    rmSync(join(empty, "pal-mnk-ber"), { recursive: true });
    expect(() => readResults(empty)).toThrow(/holds no trio/);
    expect(() => readResults(join(scratch, "nothing-here"))).toThrow(/does not exist/);
  });
});

/** The name the shard gives a place of a kit. */
function readPlaceName(folder, place) {
  return JSON.parse(readFileSync(join(folder, "pal-mnk-ber", "wiki-own.json"), "utf8")).places[place];
}
