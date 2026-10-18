import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { poolRecords } from "../pipeline/trioforge/site/static/engine/bestkit.js";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";
import { harness, pageChecks, bestKitRequest } from "./best-kit-harness.mjs";
import { makeSite } from "./engine-site-fixture.mjs";
import { chunksOf, compareRow, parseSample, readResults } from "./shard-results.mjs";

// The worker's best kit for a view of the trio page is the shard's, for the views the precompute solved: the role's own weights, the buff sets own and group, and every race, role, tier, weapon
// setup and evidence level of the grid. Each view of the results is asked of the worker as a request for the best kit (the pool is the worker's: it makes it from the item table, as the
// precompute does), and the answer is held to the row of the shard by the rule of the shard parity test (tests-js/shard-results.mjs `compareRow`): the value as the shard rounds it, the
// kit place for place, the optional buffs and the haste assumed.
//
// The worker answers without the tie stage, as a browser does, and a shard was made with it. Where several kits are worth the same, the tie stage picks one by a rule, and a plain solve
// may pick another. In the invented catalog of fixtures/site/results-solved and in every one of the 5,280 views of the maintainer's results the two agree (the pruning keeps the smaller
// (key, tier) of two items that are alike, which leaves the tie stage little to decide), so the test holds the worker to the shard in everything, on the invented results and on the
// maintainer's alike (TRIOFORGE_RESULTS, TRIOFORGE_SHARD_SAMPLE=i/n as in shard-parity.test.mjs): any difference of the value, the kit, the optional buffs or the haste fails it, and the
// views that differ are listed with their first difference. A catalog in which a plain kit is another kit of the same value would show here as a difference, to be decided on, not counted.
// The shard parity test itself solves the same views with the tie stage, through the same function the worker calls.

const FIXTURE = fileURLToPath(new URL("../fixtures/site/results-solved/", import.meta.url));
const NAMED = process.env.TRIOFORGE_RESULTS;
const REAL = NAMED !== undefined && NAMED !== "";
const FOLDER = REAL ? resolve(NAMED) : FIXTURE;

vi.setConfig({ testTimeout: REAL ? 24 * 3_600_000 : 120_000 });

let highs;
let results;
beforeAll(async () => {
  highs = await loadHighs();
  results = readResults(FOLDER);
});

/** The answer of the worker as `compareRow` reads an answer of the solver. */
const asSolved = (message) => ({
  status: message.status,
  F: message.F === null ? null : Rational.parseLong(message.F),
  kit: message.kit === null ? null : message.kit.map((name) => (name === null ? null : { key: name.slice(0, name.lastIndexOf("@")) })),
  buffs: message.buffs,
  hasteAssumed: message.hasteAssumed,
});

/** A site that serves the files of the results: the item table, and the bundle of each trio and level. */
function siteOf(folder, found) {
  const bundles = {};
  for (const trio of found.trios) {
    bundles[trio.slug] = Object.fromEntries(trio.levels.map((level) => [level.level, readFileSync(resolve(folder, trio.slug, `engine-l${level.level}.json`))]));
  }
  return makeSite({ items: readFileSync(resolve(folder, "items.json")), bundles });
}

describe(REAL ? "the worker's best kit, the results named by TRIOFORGE_RESULTS" : "the worker's best kit, the results of the invented catalog", () => {
  it("equals its shard for every view of the results: the value, the kit place for place, the optional buffs and the haste", async () => {
    const sample = process.env.TRIOFORGE_SHARD_SAMPLE ? parseSample(process.env.TRIOFORGE_SHARD_SAMPLE) : null;
    const h = harness({ site: siteOf(FOLDER, results), solver: highs });
    await h.start();
    const wanted = chunksOf(results).filter((unit) => sample === null || unit.index % sample.count === sample.index);
    const different = [];
    let views = 0;
    let slowest = { ms: 0, name: "" };
    for (const { trio, level, shard, chunk } of wanted) {
      for (const row of chunk.rows) {
        const view = { race: row.race, role: chunk.role, buffs: shard.buffs, evidence: shard.evidence, setup: chunk.setup };
        const request = bestKitRequest(view, chunk.tier, undefined, { trio: trio.slug, level: level.level, budgetMs: 300_000 });
        const began = performance.now();
        const { id, last, messages } = await h.ask(request);
        const ms = performance.now() - began;
        const name = `${trio.slug} L${level.level} ${shard.evidence}/${shard.buffs} ${row.race} ${chunk.role} ${chunk.setup} +${chunk.tier}`;
        if (ms > slowest.ms) slowest = { ms, name };
        views += 1;
        if (last.type !== "result") {
          different.push(`${name}: ${last.type} ${last.code ?? ""} ${last.message ?? ""}`);
          continue;
        }
        expect(pageChecks(request, id, messages).at(-1).mode, name).toBe("best-kit");
        // the first difference is named first, in the order F, kit, buffs, haste (compareRow)
        const found = compareRow(shard, row, asSolved(last));
        if (found.length > 0) different.push(`${name}: ${found[0]}${found.length > 1 ? ` (and ${found.length - 1} more)` : ""}`);
      }
    }
    console.log(
      `best-kit parity: ${views} views in ${wanted.length} chunks${sample === null ? "" : ` (sample ${sample.index}/${sample.count})`}, ${different.length} differ; ` +
        `the slowest ${(slowest.ms / 1000).toFixed(1)} s (${slowest.name})`,
    );
    expect(views).toBeGreaterThan(0);
    expect(different.slice(0, 20)).toEqual([]);
  });

  it("is asked of a worker that makes the pool itself: the pool of every evidence level is the size the shards count", () => {
    for (const trio of results.trios) {
      for (const level of trio.levels) {
        for (const shard of level.shards) {
          const found = poolRecords(results.table.records, level.bundle.trio, { evidence: shard.evidence }).length;
          expect(found, `${trio.slug} ${shard.name}`).toBe(shard.pool);
        }
      }
    }
  });
});

describe("the worker and the shard parity test share one function", () => {
  const source = readFileSync(resolve(fileURLToPath(new URL(".", import.meta.url)), "shard-results.mjs"), "utf8");
  const importsOf = (text) => [...text.matchAll(/import\s+(?:\{([^}]*)\}|(\w+))\s+from\s+"([^"]+)"/g)].map((found) => ({ names: (found[1] ?? found[2]).split(",").map((name) => name.trim()).filter(Boolean), from: found[3] }));

  it("is where the pool, the pruning, the session and the solve of a view are made: the shard parity test calls it and carries none of that logic itself", () => {
    const imports = importsOf(source);
    const engine = imports.filter((entry) => entry.from.includes("/static/engine/"));
    const bestkit = engine.find((entry) => entry.from.endsWith("/engine/bestkit.js"));
    expect(bestkit, "tests-js/shard-results.mjs imports the engine's bestkit.js").toBeDefined();
    expect(bestkit.names).toEqual(expect.arrayContaining(["bestKit", "poolRecords"]));
    // what it may still take from the engine: to read the files (the item table, the bundle) and the constants of the kit's places
    for (const entry of engine) {
      for (const name of entry.names) {
        expect(["bestKit", "poolRecords", "readItemTable", "readBundle", "CONSTANTS"], `${name} from ${entry.from}`).toContain(name);
      }
    }
    for (const word of ["prune", "createSession", "setScenario", "closeSession", "atTier", "assembleProfile", "usableBy", "weightsOverride"]) {
      expect(source, `${word} is the engine's, not the test's`).not.toMatch(new RegExp(`\\b${word}\\b`));
    }
    expect(source).not.toMatch(/\bsolve\(/);
    expect(source).not.toMatch(/function\s+(poolRecords|poolAt|profileOf|checkPool)\b/);
  });
});
