// The pruning of a best kit depends on the race only through the items that only some races can wear.
//
// bestKit (engine/bestkit.js) prunes the pool of a view with the profile of the race itself. The precompute (pipeline/trioforge/precompute/grid.py, `solve_chunk`) prunes once for each
// set of race-only items that a race can wear, with the profile of the first race of the chunk that wears that set, and every race that wears the same ones takes the result.
// The two are the same pruning because `prune` reads nothing that differs between races but the race itself, to leave out the race-only items the race cannot wear. The rest of the
// profile that differs between races (the naked attributes and the Iksar armor class: RACE_FIELDS of profile.js) is not read by the pruning.
//
// This test holds that over the views of the results (the invented catalog of fixtures/site/results-solved, or the folder TRIOFORGE_RESULTS names, in samples as in
// best-kit-parity.test.mjs), for every race of the bundle, in two ways.
//   * The pruning is the same: for each view and each set of race-only items, the races that wear it keep the very items the first of them keeps, and bestKit's pool pruned
//     (`viewPool`, the function bestKit calls) is the pool the precompute's rule gives. Pools in which a third of the items are race-only (seeded) are held to the same.
//   * Nothing that differs between races is read: `prune` is run with a profile that records what is read of it, and the fields it reads (of the profile and of the profile as the
//     evaluator compiles it) are none of the fields that differ between the races of the bundle, but the race. Which fields differ is worked out from the bundle itself. A
//     pruning that began to read the naked attributes, say, fails here at once, on whatever view, whether or not it changed a kept item on these views.
// And the guard is held too: a pruning made to read a field that differs between races is found by the recording, and one whose result depends on it by the comparison.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { poolRecords, viewPool } from "../pipeline/trioforge/site/static/engine/bestkit.js";
import { profileOf } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { atTier } from "../pipeline/trioforge/site/static/engine/items.js";
import { assembleProfile } from "../pipeline/trioforge/site/static/engine/profile.js";
import { prune } from "../pipeline/trioforge/site/static/engine/prune.js";
import { mulberry32 } from "./engine-models.mjs";
import { chunksOf, parseSample, readResults } from "./shard-results.mjs";

/**
 * What the recording does: the names read of a profile and of its compiled form while `active`, the profiles it wrapped, and a pruning to use in the place of the real one.
 * `noting(target, sink)` is a proxy of `target` that notes in `sink` the name of every property read of it, in each way a property is read: its value, its descriptor (what
 * Object.getOwnPropertyDescriptor, Object.keys, Object.entries and a spread ask for) and whether it is there (`in`). The profile and its compiled form are both read through it.
 */
const spy = vi.hoisted(() => {
  const noting = (target, sink) =>
    new Proxy(target, {
      get(object, name, receiver) {
        if (typeof name === "string") sink.add(name);
        return Reflect.get(object, name, receiver);
      },
      getOwnPropertyDescriptor(object, name) {
        if (typeof name === "string") sink.add(name);
        return Reflect.getOwnPropertyDescriptor(object, name);
      },
      has(object, name) {
        if (typeof name === "string") sink.add(name);
        return Reflect.has(object, name);
      },
    });
  return { active: false, raw: new Set(), compiled: new Set(), targets: new WeakMap(), prune: null, real: null, noting };
});

// profileOf of the evaluator compiles a profile (it reads all of it, once: that is the compile and not the pruning), and the pruning reads the compiled form. While the recording is
// on, the pruning gets a compiled profile that notes the names it reads; what is compiled is the profile that was wrapped.
vi.mock("../pipeline/trioforge/site/static/engine/evaluate.js", async (importOriginal) => {
  const real = await importOriginal();
  return {
    ...real,
    profileOf(profile) {
      const compiled = real.profileOf(spy.targets.get(profile) ?? profile);
      return spy.active ? spy.noting(compiled, spy.compiled) : compiled;
    },
  };
});
// the pruning is the real one, unless a test puts another in its place to see that the guard finds it (bestKit and the precompute's rule below both call this one)
vi.mock("../pipeline/trioforge/site/static/engine/prune.js", async (importOriginal) => {
  const real = await importOriginal();
  spy.real = real.prune;
  return { ...real, prune: (...args) => (spy.prune ?? real.prune)(...args) };
});

const FIXTURE = fileURLToPath(new URL("../fixtures/site/results-solved/", import.meta.url));
const NAMED = process.env.TRIOFORGE_RESULTS;
const FOLDER = NAMED !== undefined && NAMED !== "" ? resolve(NAMED) : FIXTURE;
const SAMPLE = process.env.TRIOFORGE_SHARD_SAMPLE ? parseSample(process.env.TRIOFORGE_SHARD_SAMPLE) : null;
const results = readResults(FOLDER);
const units = chunksOf(results).filter((unit) => SAMPLE === null || unit.index % SAMPLE.count === SAMPLE.index);

vi.setConfig({ testTimeout: NAMED !== undefined && NAMED !== "" ? 24 * 3_600_000 : 120_000 });

// ---- what differs between races ---------------------------------------------------------------------------------------------------------

/** A value as text, all through (an exact number as its text), so that two values can be told apart by it. */
function canon(value) {
  if (value !== null && typeof value === "object" && value.constructor?.name === "Rational") return `R${value.toString()}`;
  if (Array.isArray(value)) return `[${value.map(canon).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${key}:${canon(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "undefined";
}

/** The names of the top-level fields of the profiles of every race (`of(race)`) that are not all the same. */
function differing(races, of) {
  const profiles = races.map(of);
  const names = new Set(profiles.flatMap((profile) => Object.keys(profile)));
  return [...names].filter((name) => new Set(profiles.map((profile) => canon(profile[name]))).size > 1).sort();
}

const deityOf = (unit) => unit.shard.assumptions.deity ?? undefined;

/** The names a view's pruning must not read: the fields that differ between the races of the bundle, for the role, buffs, evidence and deity of the view. */
function racyFields(unit) {
  const { bundle } = unit.level;
  const races = bundle.races.map((row) => row.code);
  const choices = (race) => ({ race, role: unit.chunk.role, buffs: unit.shard.buffs, evidence: unit.shard.evidence, deity: deityOf(unit) });
  return {
    raw: differing(races, (race) => assembleProfile(bundle, choices(race))),
    compiled: differing(races, (race) => profileOf(assembleProfile(bundle, choices(race)))),
  };
}

// ---- a profile that records what is read of it ---------------------------------------------------------------------------------------------

/** The profile as the pruning gets it: the very values, and the names read of it noted in `spy.raw`. A frozen profile cannot be wrapped, so the recording one is a copy. */
function recording(profile) {
  const proxy = spy.noting({ ...profile }, spy.raw);
  spy.targets.set(proxy, profile);
  return proxy;
}

/** The names a pruning (`run(profile)`) reads of the profile and of its compiled form. The compile is not counted. */
function readsOf(profile, run) {
  spy.raw.clear();
  spy.compiled.clear();
  spy.active = true;
  try {
    run(recording(profile));
  } finally {
    spy.active = false;
  }
  return { raw: new Set(spy.raw), compiled: new Set(spy.compiled) };
}

/** The fields read that differ between races (the race itself, which the race-only items are judged by, is no fault). */
const offences = (reads, racy) => ({
  raw: racy.raw.filter((name) => name !== "race" && reads.raw.has(name)),
  compiled: racy.compiled.filter((name) => reads.compiled.has(name)),
});
const NONE = { raw: [], compiled: [] };

// ---- the views ------------------------------------------------------------------------------------------------------------------------

/** The scenario of a race in a chunk of a shard, as the shard assumed it. */
function scenarioOf(unit, race) {
  const scenario = { race, role: unit.chunk.role, buffs: unit.shard.buffs, evidence: unit.shard.evidence, setup: unit.chunk.setup };
  const deity = deityOf(unit);
  if (deity !== undefined) scenario.deity = deity;
  return scenario;
}

const keysOf = (items) => items.map((item) => `${item.key}@${item.tier}`);
const raceCodes = (unit) => unit.level.bundle.races.map((row) => row.code);
const nameOf = (unit, race) => `${unit.trio.slug} ${unit.shard.name} ${unit.chunk.role} ${unit.chunk.setup} +${unit.chunk.tier} ${race}`;
const viewOf = (records, unit, race) => viewPool({ records, bundle: unit.level.bundle, scenario: scenarioOf(unit, race), tier: unit.chunk.tier });

/**
 * The precompute's rule (`solve_chunk`): the pool of every race at once (`Context.pool`: the items of the evidence level at the tier, the race-only ones in it) is pruned
 * once for each set of race-only items that a race can wear, with the profile of the first race that wears that set. Returns the keys each race keeps by that rule.
 */
function byThePrecompute(records, unit) {
  const { bundle } = unit.level;
  const pool = poolRecords(records, bundle.trio, { evidence: unit.shard.evidence }).map((record) => atTier(record, unit.chunk.tier, bundle));
  const raceOnly = pool.filter((item) => item.races !== null);
  const kept = new Map();
  const result = new Map();
  for (const race of raceCodes(unit)) {
    const wearable = raceOnly.filter((item) => item.races.includes(race)).map((item) => item.key).join("|");
    if (!kept.has(wearable)) {
      const view = viewOf(records, unit, race);
      kept.set(wearable, keysOf(prune(pool, view.profile, unit.chunk.tier, unit.chunk.setup, view.buffset, view.pruneOptions)));
    }
    result.set(race, kept.get(wearable));
  }
  return { result, groups: kept.size };
}

/** bestKit's pruning for every race of every view against the precompute's rule: how many race-views, how many sets of race-only items, and which races differ. */
function compareWithThePrecompute(recordsOf) {
  let views = 0;
  let groups = 0;
  const different = [];
  for (const unit of units) {
    const records = recordsOf(unit);
    const rule = byThePrecompute(records, unit);
    groups += rule.groups;
    for (const race of raceCodes(unit)) {
      views += 1;
      if (JSON.stringify(keysOf(viewOf(records, unit, race).pruned)) !== JSON.stringify(rule.result.get(race))) different.push(nameOf(unit, race));
    }
  }
  return { views, groups, different };
}

/**
 * The table's records with some of the pool's made race-only (seeded): `count` records of the pool of the view, each with a list of about half of the races. A few such items, so
 * that races share the set they wear (a pool with many would give every race a set of its own, and the rule would prune once for each race, as bestKit does).
 */
function withRaceOnlyItems(unit, seed, count) {
  const random = mulberry32(seed + unit.index);
  const races = raceCodes(unit);
  const records = new Map(results.table.records);
  const pool = poolRecords(results.table.records, unit.level.bundle.trio, { evidence: unit.shard.evidence });
  const chosen = new Set();
  while (chosen.size < Math.min(count, pool.length)) chosen.add(pool[Math.floor(random() * pool.length)]);
  for (const record of chosen) {
    const listed = races.filter(() => random() < 0.5);
    if (listed.length > 0 && listed.length < races.length) records.set(record.key ?? `w${record.id}`, { ...record, races: listed });
  }
  return records;
}

describe("the pruning of a view depends on the race only through the race-only items", () => {
  it("is the same for the views of the results: bestKit's pool for a race is the pruning of the precompute's rule, for every race of the bundle", () => {
    const found = compareWithThePrecompute(() => results.table.records);
    console.log(`prune guard: ${found.views} race-views of ${units.length} chunks, ${found.groups} sets of race-only items, ${found.different.length} differ`);
    expect(found.views).toBeGreaterThan(0);
    expect(found.different.slice(0, 20)).toEqual([]);
  });

  it("is the same when some of the pool's items are race-only, whichever races wear them (seeded pools of one to four such items)", () => {
    let shared = 0;
    for (const [seed, count] of [[20261017, 1], [7, 2], [4242, 3], [99, 4], [31337, 3]]) {
      const found = compareWithThePrecompute((unit) => withRaceOnlyItems(unit, seed, count));
      expect(found.groups, `seed ${seed}: the pools have several sets of race-only items`).toBeGreaterThan(units.length);
      expect(found.views).toBeGreaterThan(0);
      expect(found.different.slice(0, 20), `seed ${seed}`).toEqual([]);
      shared += found.views - found.groups;
    }
    expect(shared, "and races share them: most race-views take the pruning of the first race that wears the same items, so that the rule is not one pruning said for each race").toBeGreaterThan(units.length * 15);
  });

  it("is found to differ when the pruning reads a field that differs between races: the comparison is not one pruning said twice", () => {
    // a pruning that drops the first kept item for a race whose first naked attribute is above the median of the races' (it reads the naked attributes of the profile)
    const median = (unit) => [...unit.level.bundle.races.map((row) => row.naked.STR)].sort((a, b) => a - b)[Math.floor(unit.level.bundle.races.length / 2)];
    const racy = (items, profile, ...rest) => {
      const kept = spy.real(items, profile, ...rest);
      return profile.naked.STR > median(units[0]) ? kept.slice(1) : kept;
    };
    spy.prune = racy;
    try {
      const found = compareWithThePrecompute(() => results.table.records);
      expect(found.different.length, "the races that differ in the naked attributes are told apart").toBeGreaterThan(0);
    } finally {
      spy.prune = null;
    }
  });

  it("differs between races in the naked attributes and the Iksar armor class, which the pruning does not read, and in the race itself, which it reads for the race-only items", () => {
    const racy = racyFields(units[0]);
    expect(racy.raw).toEqual(["iksar_ac", "naked", "race"]);
    expect(racy.compiled).toEqual(["iksarAc", "naked"]);
  });

  it("reads of the profile and of its compiled form none of the fields that differ between races, but the race: the recording sees what the pruning reads, and nothing else", () => {
    let views = 0;
    const seen = { raw: new Set(), compiled: new Set() };
    for (const unit of units) {
      const racy = racyFields(unit);
      for (const race of raceCodes(unit)) {
        const view = viewOf(results.table.records, unit, race);
        let kept;
        const reads = readsOf(view.profile, (profile) => {
          kept = prune(view.pool, profile, unit.chunk.tier, unit.chunk.setup, view.buffset, view.pruneOptions);
        });
        expect(keysOf(kept), "the recorded pruning is the pruning").toEqual(keysOf(view.pruned));
        expect(offences(reads, racy), nameOf(unit, race)).toEqual(NONE);
        reads.raw.forEach((name) => seen.raw.add(name));
        reads.compiled.forEach((name) => seen.compiled.add(name));
        views += 1;
      }
    }
    expect(views).toBeGreaterThan(0);
    // the recording works: the pruning does read the race, the pools, the weights and the haste, so an empty record would be a recording that sees nothing
    expect(seen.raw.has("race")).toBe(true);
    expect([...seen.compiled]).toEqual(expect.arrayContaining(["pools", "weights", "buff", "hasteCap"]));
  });

  describe("the recording finds a pruning that reads a field that differs between races", () => {
    const [unit] = units;
    const racy = racyFields(unit);
    const view = viewOf(results.table.records, unit, raceCodes(unit)[0]);
    const pruning = (profile) => prune(view.pool, profile, unit.chunk.tier, unit.chunk.setup, view.buffset, view.pruneOptions);
    const finds = (run) => offences(readsOf(view.profile, run), racy);

    it("passes the pruning as it is", () => {
      expect(finds(pruning)).toEqual(NONE);
    });

    it("sees a pruning that reads the naked attributes of the compiled profile, or the Iksar armor class, even when it uses it for nothing", () => {
      expect(finds((profile) => (void profileOf(profile).naked, pruning(profile)))).toEqual({ raw: [], compiled: ["naked"] });
      expect(finds((profile) => (void profileOf(profile).iksarAc, pruning(profile)))).toEqual({ raw: [], compiled: ["iksarAc"] });
    });

    it("sees a pruning that reads a raw field that differs between races", () => {
      expect(finds((profile) => (void profile.naked, pruning(profile)))).toEqual({ raw: ["naked"], compiled: [] });
      expect(finds((profile) => (void profile.iksar_ac, pruning(profile)))).toEqual({ raw: ["iksar_ac"], compiled: [] });
      expect(finds((profile) => (void Object.keys(profile), pruning(profile))).raw, "listing the fields reads them all").toEqual(["iksar_ac", "naked"]);
    });

    it("sees a read of a field through its descriptor, a question whether it is there, or a list of the fields, of the compiled profile as of the raw one", () => {
      expect(finds((profile) => (void Object.getOwnPropertyDescriptor(profileOf(profile), "naked"), pruning(profile)))).toEqual({ raw: [], compiled: ["naked"] });
      expect(finds((profile) => (void ("iksarAc" in profileOf(profile)), pruning(profile)))).toEqual({ raw: [], compiled: ["iksarAc"] });
      expect(finds((profile) => (void Object.keys(profileOf(profile)), pruning(profile))).compiled, "listing the fields reads them all").toEqual(["iksarAc", "naked"]);
      expect(finds((profile) => (void Object.entries(profileOf(profile)), pruning(profile))).compiled).toEqual(["iksarAc", "naked"]);
      expect(finds((profile) => (void Object.getOwnPropertyDescriptor(profile, "iksar_ac"), pruning(profile)))).toEqual({ raw: ["iksar_ac"], compiled: [] });
      expect(finds((profile) => (void ("naked" in profile), pruning(profile)))).toEqual({ raw: ["naked"], compiled: [] });
    });

    it("lets the race itself be read, for the race-only items", () => {
      expect(finds((profile) => (void profile.race, pruning(profile)))).toEqual(NONE);
    });

    it("does not count the compile: the evaluator reads the whole profile once, and that is not the pruning", () => {
      expect(finds((profile) => void profileOf(profile))).toEqual(NONE);
    });
  });

  it("is in the source of the pruning as it is in the test: prune.js names the race of the profile and no field that differs between races", () => {
    const source = readFileSync(resolve(fileURLToPath(new URL(".", import.meta.url)), "../pipeline/trioforge/site/static/engine/prune.js"), "utf8");
    const code = source.split("\n").filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line)).join("\n");
    expect(code).not.toMatch(/\bnaked\b|\biksarAc\b|\biksar_ac\b/);
    expect(code).toMatch(/own\(profile, "race"\)/);
  });
});
