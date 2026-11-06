import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { chunksOf, checkResults, parsePart, parseSample, readResults, ResultsError, workOf } from "./shard-results.mjs";

// Every view that the precompute solved and published is solved again by the browser engine, from the files the browser reads, and must come out as its shard:
//
//   * the exact value F (a shard keeps `round(float(F), 2)`, so the engine's value is brought to that the way Python does it, and the two must be equal),
//   * the kit, place for place (the engine solves with `canonical: true`: the tie stage and the canonical placement, as the precompute does),
//   * the optional buffs, and
//   * the haste the weapons were scored at.
//
// A view is a race, a role, a tier, a weapon setup, an evidence level and a buff set. The views are the rows of the four shards (`<evidence>-<buffs>.json`) of each trio
// folder, at each level that has a bundle (`engine-l<level>.json`), and `defaults.json` is held to the same values (its race, runner-up, margin, and the value and best
// setup of each race). The profile, the pool, the pruning and the options of each view are made from the files of the folder, the way the precompute made them: the head of
// tests-js/shard-results.mjs says how. One view that differs prints its name and the first difference; the check goes on, and all of them are listed at the end, with the count.
// A view whose F, kit and haste are equal and whose buff sets differ passes, as a tie of buffs of equal value; the ties are counted and printed (the count in the summary
// line, then the views, as many as TRIOFORGE_SHARD_LINES allows).
//
// The folder is the results of a real precompute run (a narrow one) on the invented catalog of the site fixture: fixtures/site/results-solved, which
// pipeline/tests/shard_fixture.py makes again and test_shard_fixture.py keeps current. That is what the CI runs, in a few seconds. The maintainer's own results, which are
// never in the repository, are checked on the maintainer's computer:
//
//   TRIOFORGE_RESULTS=<folder of results> npx vitest run tests-js/shard-parity.test.mjs
//
// A folder of real results has thousands of views, each solved with the tie stage, and takes a long time. TRIOFORGE_SHARD_SAMPLE=i/n checks only the chunks i, i+n, i+2n ...
// of the folder (a chunk is a view across the races: one evidence level, buff set, role, setup and tier, in a fixed order), so that n runs, i = 0 to n-1, check every view
// once and can run side by side; every sample also solves the views `defaults.json` is made from, and checks it. TRIOFORGE_SHARD_LINES=all lists every view that differs
// (the default is the first 100).
// TRIOFORGE_SHARD_PART=k/K does the part k of K of all the work (the sample's chunks and the chunks of each defaults.json, which are never divided between parts): K processes,
// k = 0 to K-1, share one check and between them do all of it once. A part beyond the units of the work (k at least the number of units) checks nothing and passes.

const FIXTURE = fileURLToPath(new URL("../fixtures/site/results-solved/", import.meta.url));
const NAMED = process.env.TRIOFORGE_RESULTS;
const REAL = NAMED !== undefined && NAMED !== "";
const FOLDER = REAL ? resolve(NAMED) : FIXTURE;
const FIXTURE_FOLDER = resolve(FIXTURE);
const LINES = process.env.TRIOFORGE_SHARD_LINES === "all" ? Infinity : Math.max(1, Math.floor(Number(process.env.TRIOFORGE_SHARD_LINES)) || 100);
const DETAILED = 3;

// a solve of the hard programs takes a second or two; the results of the maintainer's computer are thousands of them
vi.setConfig({ testTimeout: REAL ? 24 * 3_600_000 : 120_000 });

const seconds = (ms) => (ms / 1000).toFixed(1);

/** The failures as the text of the error: the count, then each view with its first difference, and the kits of the first few. */
function describeFailures(report) {
  const problems = [...report.failures, ...report.defaults];
  const lines = [`${report.failures.length} of ${report.views} views differ from their shard${report.defaults.length > 0 ? `, and ${report.defaults.length} values of defaults.json differ` : ""}:`];
  for (const problem of problems.slice(0, LINES)) {
    const more = problem.all.length > 1 ? ` (and ${problem.all.length - 1} more: ${problem.all.slice(1).map((text) => text.split(":")[0]).join(", ")})` : "";
    lines.push(`  ${problem.name}: ${problem.first}${more}`);
  }
  if (problems.length > LINES) lines.push(`  ... and ${problems.length - LINES} more (TRIOFORGE_SHARD_LINES=all lists every one)`);
  for (const problem of report.failures.filter((found) => found.kitDiffers).slice(0, DETAILED)) {
    lines.push(`  ${problem.name}`);
    lines.push(`    shard kit : ${problem.shardKit.map((key) => key ?? "-").join(" ")}`);
    lines.push(`    engine kit: ${problem.engineKit.map((key) => key ?? "-").join(" ")}`);
    if (problem.shardItems.length > 0) lines.push(`    the shard's items at the places that differ: ${problem.shardItems.join("; ")}`);
  }
  if (report.failures.some((problem) => problem.keptFirst > 0)) {
    lines.push("  (a shard that has rows whose tie stage kept the first stage's kit may differ from the engine in a kit of equal value; solver.kept_first says how many rows)");
  }
  return lines.join("\n");
}

/** The ties as text: the views that differ from their shard in the optional buffs alone, which pass (buffs of equal value; see `isBuffTie` of shard-results.mjs). */
function describeTies(report) {
  const lines = [`shard parity: ${report.ties.length} of ${report.views} views are ties (the buff set differs; F, the kit and the haste are equal), and pass:`];
  for (const tie of report.ties.slice(0, LINES)) lines.push(`  ${tie.name}: ${tie.first}`);
  if (report.ties.length > LINES) lines.push(`  ... and ${report.ties.length - LINES} more (TRIOFORGE_SHARD_LINES=all lists every one)`);
  return lines.join("\n");
}

describe(REAL ? "shard parity, the results named by TRIOFORGE_RESULTS" : "shard parity, the results of the invented catalog", () => {
  let highs;
  let results;
  let fixture; // the committed fixture, whatever TRIOFORGE_RESULTS names: for the self-tests of the partition
  beforeAll(async () => {
    highs = await loadHighs();
    results = readResults(FOLDER);
    fixture = REAL ? readResults(FIXTURE_FOLDER) : results;
  });

  it("the folder is one run, and the views of it are in a fixed order that the samples cover once each", () => {
    const units = chunksOf(results);
    expect(units.length).toBeGreaterThan(0);
    expect(units.map((unit) => unit.index)).toEqual(units.map((_, at) => at));
    for (const count of [1, 2, 3, 7]) {
      const taken = new Map();
      for (let index = 0; index < count; index += 1) {
        const sample = parseSample(`${index}/${count}`);
        for (const unit of units) if (unit.index % sample.count === sample.index) taken.set(unit.index, (taken.get(unit.index) ?? 0) + 1);
      }
      expect([...taken.values()].every((times) => times === 1) && taken.size === units.length, `${count} samples`).toBe(true);
    }
  });

  // The self-tests of the partition use the committed fixture and nothing else: in a release run TRIOFORGE_RESULTS names a folder of hundreds of thousands of views,
  // and no test but the one below may solve or even list the work of that.
  it("TRIOFORGE_SHARD_PART=k/K: the K parts hold every unit of the work (the sampled chunks, and the plan of each defaults.json) exactly once, and a part beyond the units has none", () => {
    for (const sample of [null, parseSample("1/3")]) {
      const whole = workOf(fixture, { directory: FIXTURE_FOLDER, sample });
      const units = whole.items.length;
      expect(units).toBeGreaterThan(0);
      expect(whole.items.map((item) => item.id)).toEqual(whole.items.map((_, at) => at));
      for (const count of [1, 2, 3, 5, units, units + 3]) {
        const taken = new Map();
        const chunks = new Map();
        for (let index = 0; index < count; index += 1) {
          const mine = workOf(fixture, { directory: FIXTURE_FOLDER, sample, part: parsePart(`${index}/${count}`) });
          expect(mine.items.length > 0, `part ${index}/${count} has units exactly when its index is below the number of units`).toBe(index < units);
          if (index >= units) expect([mine.wanted.length, mine.total, mine.plans.length]).toEqual([0, 0, 0]);
          for (const item of mine.items) taken.set(item.id, (taken.get(item.id) ?? 0) + 1);
          for (const unit of mine.wanted) chunks.set(unit.index, (chunks.get(unit.index) ?? 0) + 1);
          for (const plan of mine.plans) expect(plan.chunks.every((chunk) => mine.wanted.some((unit) => unit.chunk === chunk)), "a plan is whole in its part").toBe(true);
        }
        expect([...taken.values()].every((times) => times === 1) && taken.size === units, `${count} parts: every unit once`).toBe(true);
        expect([...chunks.values()].every((times) => times === 1) && chunks.size === whole.wanted.length, `${count} parts: every chunk once`).toBe(true);
      }
    }
  });

  it("TRIOFORGE_SHARD_PART is read as strictly as the sample: k/K, with k from 0 to K-1", () => {
    expect(parsePart("0/1")).toEqual({ index: 0, count: 1 });
    expect(parsePart(" 11/12 ")).toEqual({ index: 11, count: 12 });
    for (const bad of ["", "1", "a/b", "5/3", "3/3", "0/0", "-1/4", "1/2/3", "0/ 1", "1.5/4", "0/1000000"]) expect(() => parsePart(bad), JSON.stringify(bad)).toThrow(ResultsError);
  });

  it("the parts solve between them what the whole run solves: the same views, and the defaults of each trio checked in one part", () => {
    const whole = checkResults(fixture, { highs, directory: FIXTURE_FOLDER });
    const parts = [0, 1].map((index) => checkResults(fixture, { highs, directory: FIXTURE_FOLDER, part: parsePart(`${index}/2`) }));
    expect(parts.map((report) => report.views).reduce((sum, views) => sum + views, 0)).toBe(whole.views);
    expect(parts.map((report) => report.chunks).reduce((sum, chunks) => sum + chunks, 0)).toBe(whole.chunks);
    expect(parts.map((report) => report.defaultsChecked).reduce((sum, checked) => sum + checked, 0)).toBe(whole.defaultsChecked);
    for (const report of [whole, ...parts]) expect(report.views).toBe(report.planned);
    expect(parts.flatMap((report) => [...report.failures, ...report.defaults])).toEqual([...whole.failures, ...whole.defaults]);
  });

  it("more parts than units is harmless: the parts beyond the units check nothing and pass with 0 views, and the others still cover the work once", () => {
    const sample = parseSample("0/40");
    const whole = checkResults(fixture, { highs, directory: FIXTURE_FOLDER, sample });
    const units = workOf(fixture, { directory: FIXTURE_FOLDER, sample }).items.length;
    expect(units).toBeGreaterThan(0);
    const count = units + 3;
    const parts = Array.from({ length: count }, (_, index) => checkResults(fixture, { highs, directory: FIXTURE_FOLDER, sample, part: parsePart(`${index}/${count}`) }));
    for (const [index, report] of parts.entries()) {
      expect(report.views, `part ${index}/${count}`).toBe(report.planned);
      if (index >= units) expect([report.views, report.chunks, report.failures.length, report.defaults.length, report.defaultsChecked]).toEqual([0, 0, 0, 0, 0]);
    }
    expect(parts.map((report) => report.views).reduce((sum, views) => sum + views, 0)).toBe(whole.views);
    expect(parts.map((report) => report.defaultsChecked).reduce((sum, checked) => sum + checked, 0)).toBe(whole.defaultsChecked);
  });

  it("every precomputed view, solved by the engine with canonical: true, equals its shard: the exact value, the kit place for place, the optional buffs and the haste assumed", () => {
    const sample = process.env.TRIOFORGE_SHARD_SAMPLE ? parseSample(process.env.TRIOFORGE_SHARD_SAMPLE) : null;
    const part = process.env.TRIOFORGE_SHARD_PART ? parsePart(process.env.TRIOFORGE_SHARD_PART) : null;
    const report = checkResults(results, { highs, directory: FOLDER, sample, part, progress: (text) => console.log(`shard parity: ${text}`) });
    // the views of the chunks the sample takes (of the part's units, when there is a part): the least the check must have solved
    const mine = part === null ? chunksOf(results) : workOf(results, { directory: FOLDER, sample, part }).wanted;
    const rows = mine.filter((unit) => sample === null || unit.index % sample.count === sample.index).reduce((sum, unit) => sum + unit.chunk.rows.length, 0);
    const { timing } = report;
    console.log(
      `shard parity: ${report.views} views in ${report.chunks} chunks${sample === null ? "" : ` (sample ${sample.index}/${sample.count})`}${part === null ? "" : ` (part ${part.index}/${part.count})`}, ${report.failures.length} differ, ${report.ties.length} ties, ` +
        `defaults.json ${report.defaultsChecked === 0 ? "not checked" : `checked, ${report.defaults.length} differ`}; ` +
        `${seconds(timing.totalMs)} s in all (solves ${seconds(timing.solveMs)} s, models ${seconds(timing.buildMs)} s, pruning ${seconds(timing.pruneMs)} s), ` +
        `the slowest solve ${seconds(timing.slowest.ms)} s (${timing.slowest.name})`,
    );
    if (report.ties.length > 0) console.log(describeTies(report));
    // every view of the folder (or of the sample; the sample 0 also solves the chunks that defaults.json is made from) was checked, and none was left out
    expect(report.views, "the views checked").toBe(report.planned);
    expect(report.views, "the views of the folder or of the sample").toBeGreaterThanOrEqual(rows);
    if (part === null || mine.length > 0) expect(report.views).toBeGreaterThan(0); // (a part beyond the units of the work has none to check, and passes)
    if (sample === null && part === null) expect(report.views, "every view of the folder").toBe(rows);
    if (report.failures.length > 0 || report.defaults.length > 0) expect.fail(describeFailures(report));
  });
});
