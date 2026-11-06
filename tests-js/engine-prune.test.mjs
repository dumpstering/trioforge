import loadHighs from "highs";
import { beforeAll, describe, expect, it } from "vitest";
import { CONSTANTS } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { ModelError, buildMilp } from "../pipeline/trioforge/site/static/engine/model.js";
import { PruneError, fitGroups, prune, pruneReport, scoredDimensions } from "../pipeline/trioforge/site/static/engine/prune.js";
import { closeSession, createSession, solveScenario } from "../pipeline/trioforge/site/static/engine/solve.js";
import { solveModelWith } from "../pipeline/trioforge/site/static/engine/worker.js";
import { FAMILIES, caseOf, clone, deepFreeze, exact, identOf, sharedOf, shuffled } from "./engine-cases.mjs";
import { MONK_BINS, MONK_CURVE, PMB_POOLS, buffOf, buffsetOf, gear, oneHand, profileWith, twoHand } from "./engine-hand.mjs";
import { SAMPLE, describeFull } from "./engine-fixtures.mjs";
import { mulberry32 } from "./engine-models.mjs";

// The dominance pruning of the browser (static/engine/prune.js) held to the Python one (pipeline/trioforge/solver/prune.py):
//
//   * Parity. For every solve of the parity fixtures that records its pruning (a pool, the options and the owned idents given to `prune`, and the
//     idents that stayed: the scenarios that check the pruning, and every step of the farm path) the port keeps the very items Python kept, whatever
//     the order of the pool.
//   * Exactness. The pruned pool has the optimum of the full pool: on every brute-force instance (whose best kit was found by trying every legal kit),
//     on the pools of the Upgrade steps under their owned-item options, and on random pools under the plain rule and the owned-item rule, solved by HiGHS.
//   * The rule, by hand. The cases of pipeline/tests/test_prune.py and test_prune_owned.py that read in the browser: Lore never justifies a drop, the
//     hands, the shield, the weight of a Monk, the owned items, the tiers.

const REL = 1e-9;
const relative = (got, want) => Math.abs(got - want) / Math.max(1, Math.abs(want));

/** HiGHS as the worker runs it, started once for this file. */
let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

/** The optimum of a pool, found by HiGHS under the options of the worker. */
function optimum(profile, items, setup, buffset, options) {
  const model = buildMilp(profile, items, setup, buffset, options);
  const got = solveModelWith(highs, model, { budgetMs: 60_000, startedAt: performance.now(), onProgress() {} });
  expect(got.status).toBe("optimal");
  return got.objective;
}

/** The truthful optimum of a pool (the weapons are paid the haste the kit counts, the options fixing none), as the worker finds it. */
function truthfulOptimum(profile, items, setup, buffset, options, monkBins) {
  const session = createSession({ highs, profile, setup, buffset, monkBins });
  try {
    const got = solveScenario(session, { name: "main", items, options: { ...options, haste_assumed: null, haste_floor: null, haste_exact: false }, budgetMs: 600_000 });
    expect(got.status).toBe("optimal");
    return got.F.toNumber();
  } finally {
    closeSession(session);
  }
}

// ---- parity with Python ---------------------------------------------------------------------------------------------------------------

function parityTests(set) {
  const shared = sharedOf(set);
  const recordedTotal = { matrix: 0, upgrade: 0, pmb36: 0, brute: 0 };

  for (const family of FAMILIES) {
    const paths = set.paths("case", `${family}/`);
    describe(`${family}/`, () => {
      it("has cases (all of the family the run made)", () => {
        expect(paths.length).toBeGreaterThan(0);
        expect(paths.length).toBe(set.manifest.families[family].count);
      });

      for (const path of paths) {
        const doc = set.read(path);
        const recorded = doc.solves.filter((solve) => solve.prune !== null);
        recordedTotal[family] += recorded.length;
        if (recorded.length === 0) continue;
        it(`${doc.id} (${doc.label}): the items kept are the items Python kept (${recorded.length} pruning${recorded.length === 1 ? "" : "s"})`, () => {
          const c = caseOf(shared, doc);
          for (const solve of recorded) {
            const { prune: recording } = solve;
            const input = recording.input.map(c.itemNamed);
            const options = c.withBins(recording.options);
            const kept = prune(input, c.profile, recording.tier, c.setup, c.buffset, options, recording.owned);
            expect(kept.map(identOf), `${doc.id} ${solve.label}`).toEqual(recording.kept);
            // the pool the model was built from is the pool that stayed
            expect(recording.kept, `${doc.id} ${solve.label}: the pool of the solve`).toEqual(solve.pool);
            // and the answer does not depend on the order of the pool
            const again = prune(shuffled(input, 11), c.profile, recording.tier, c.setup, c.buffset, options, shuffled(recording.owned, 5));
            expect(again.map(identOf), `${doc.id} ${solve.label}: another order of the pool`).toEqual(recording.kept);
          }
        });
      }
    });
  }

  it("the set records prunings of the scenarios and of the farm path (a family that records none would pass the cases above for nothing)", () => {
    expect(recordedTotal.matrix).toBeGreaterThan(0);
    expect(recordedTotal.pmb36).toBeGreaterThan(0);
    expect(recordedTotal.upgrade).toBeGreaterThan(0);
  });
}

describe("the committed sample", () => parityTests(SAMPLE));
describeFull("the full set", (full) => parityTests(full));

// ---- exactness on the fixtures -------------------------------------------------------------------------------------------------------

function bruteTests(set) {
  const shared = sharedOf(set);
  const paths = set.paths("case", "brute/");
  it("has brute-force cases", () => {
    expect(paths.length).toBeGreaterThan(0);
  });
  for (const path of paths) {
    const doc = set.read(path);
    it(`${doc.id} (${doc.label}): the pruned pool has the best kit of every legal kit, F = the brute-force maximum`, () => {
      const c = caseOf(shared, doc);
      const [solve] = doc.solves;
      const options = c.optionsOf(solve);
      const full = c.poolOf(solve);
      const kept = prune(full, c.profile, null, c.setup, c.buffset, options);
      expect(kept.length).toBeLessThanOrEqual(full.length);
      const want = exact(doc.expected.brute_F).toNumber();
      expect(relative(optimum(c.profile, kept, c.setup, c.buffset, options), want), `${doc.id}: pruned ${kept.length} of ${full.length}`).toBeLessThanOrEqual(REL);
    }, 60_000);
  }
}

describe("brute force, the committed sample", () => bruteTests(SAMPLE));
describeFull("brute force, the full set", (full) => bruteTests(full));

function stepTests(set) {
  const shared = sharedOf(set);
  for (const path of set.paths("case", "upgrade/")) {
    const doc = set.read(path);
    const steps = doc.solves.filter((solve) => solve.prune !== null);
    if (steps.length === 0) continue;
    it(`${doc.id} (${doc.label}): pruning the pool of a step changes no value, under the step's owned-item options`, () => {
      const c = caseOf(shared, doc);
      for (const solve of steps) {
        const { prune: recording } = solve;
        const options = c.withBins(recording.options);
        const input = recording.input.map(c.itemNamed);
        // the full pool under the options the step had, less the idents that the builder would not find in the pruned pool, as the step does
        const want = exact(solve.result.F).toNumber();
        // (the value the step recorded is the truthful one: the best over the haste levels a kit can count, which pruning must not change)
        const full = truthfulOptimum(c.profile, input, c.setup, c.buffset, options, c.bins);
        expect(relative(full, want), `${doc.id} ${solve.label}: the full pool of ${input.length} items`).toBeLessThanOrEqual(REL);
      }
    }, 300_000);
  }
}

describe("the Upgrade steps, the committed sample", () => stepTests(SAMPLE));
describeFull("the Upgrade steps, the full set", (full) => stepTests(full));

// ---- the rule, by hand ---------------------------------------------------------------------------------------------------------------

const OPT = deepFreeze({ any_rule: "explicit", haste_assumed: 0 }); // only items that list ANY fit the Any group
const prof = (weights, changes = {}) => profileWith({ weights, ...changes });
const PMB = { pools: PMB_POOLS };
const keysOf = (items) => items.map((item) => item.key).sort();
const run = (profile, items, setup = "stick", options = OPT, buffset = null, tier = 0) => prune(items, profile, tier, setup, buffset, options);
const close = (a, b) => relative(a, b) <= REL;

function agree(profile, items, setup = "stick", options = OPT, buffset = null) {
  const kept = run(profile, items, setup, options, buffset);
  const full = optimum(profile, items, setup, buffset, options);
  const small = optimum(profile, kept, setup, buffset, options);
  expect(close(full, small), `full ${full} against pruned ${small}`).toBe(true);
  return keysOf(kept);
}

const emptyValue = (profile) => optimum(profile, [], "stick", null, OPT);
const sorted = (set) => [...set].sort();

describe("a drop and what justifies it", () => {
  it("drops a dominated item, and the report names the item that replaces it", () => {
    const p = prof({ HP: 1 });
    const items = [gear("big", ["HEAD"], { stats: { HP: 50 } }), gear("small", ["HEAD"], { stats: { HP: 30 } })];
    const report = pruneReport(items, p, 0, "stick", null, OPT);
    expect(keysOf(report.kept)).toEqual(["big"]);
    expect([...report.dropped]).toEqual([["small@0", ["dominated", "big@0"]]]);
    expect(agree(p, items)).toEqual(["big"]);
  });

  it("does not drop a plain item for two Lore dominators: the ears can only be filled by them, so the fingers need the plain item", () => {
    const p = prof({ HP: 1 });
    const b = gear("b-ring", ["FINGER"], { stats: { HP: 50 } });
    const a2 = gear("a2-ring", ["EAR", "FINGER"], { stats: { HP: 60 }, lore: true });
    const a3 = gear("a3-ring", ["EAR", "FINGER"], { stats: { HP: 55 }, lore: true });
    const items = [b, a2, a3];
    expect(agree(p, items)).toEqual(["a2-ring", "a3-ring", "b-ring"]);
    expect(close(optimum(p, items, "stick", null, OPT), emptyValue(p) + 60 + 55 + 50 + 50)).toBe(true);
    expect(close(optimum(p, [a2, a3], "stick", null, OPT), emptyValue(p) + 60 + 55)).toBe(true); // without B only the two Lore rings are worn, once each
  });

  it("drops an item only for a plain dominator (the three ear cases)", () => {
    const p = prof({ MANA: 1 });
    const ear = (key, wis, lore) => gear(key, ["EAR"], { stats: { WIS: wis }, lore });
    const CASES = [
      [[10, true], [9, false], [8, false], ["a", "b"]], // A is Lore, so B stays; B is plain, so C goes
      [[10, true], [9, true], [8, false], ["a", "b", "c"]], // two Lore dominators: C stays
      [[10, false], [9, false], [8, false], ["a"]], // all plain: the best one is worn twice
      [[10, true], [9, true], [8, true], ["a", "b", "c"]], // all Lore: nothing can go
      [[10, false], [9, true], [8, true], ["a"]], // the plain A replaces both Lore items
    ];
    for (const [a, b, c, kept] of CASES) expect(agree(p, [ear("a", ...a), ear("b", ...b), ear("c", ...c)]), JSON.stringify([a, b, c])).toEqual(kept);
    const items = [ear("a", 10, true), ear("b", 9, false), ear("c", 8, false)];
    expect([...pruneReport(items, p, 0, "stick", null, OPT).dropped]).toEqual([["c@0", ["dominated", "b@0"]]]);
  });

  it("leaves exactly one of two identical items, the smaller key, whatever the order of the pool", () => {
    const p = prof({ HP: 1 });
    const twins = ["head-b", "head-c", "head-a"].map((key) => gear(key, ["HEAD"], { stats: { HP: 30 } }));
    const orders = [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]];
    for (const order of orders) expect(keysOf(run(p, order.map((at) => twins[at])))).toEqual(["head-a"]);
    expect(agree(p, twins)).toEqual(["head-a"]);
  });

  it("keeps identical Lore items (both ear places can hold one each), and an identical plain item replaces both", () => {
    const p = prof({ HP: 1 });
    const lores = ["e-b", "e-a"].map((key) => gear(key, ["EAR"], { stats: { HP: 30 }, lore: true }));
    expect(agree(p, lores)).toEqual(["e-a", "e-b"]);
    expect(agree(p, [...lores, gear("e-z", ["EAR"], { stats: { HP: 30 } })])).toEqual(["e-z"]);
  });

  it("does not let an item that fits fewer groups replace one that fits more, and lets equal stats with more groups replace the narrow twin", () => {
    const p = prof({ HP: 1 });
    const wide = gear("wide", ["EAR", "FINGER"], { stats: { HP: 20 } });
    const narrow = gear("narrow", ["EAR"], { stats: { HP: 90 } });
    expect(agree(p, [wide, narrow])).toEqual(["narrow", "wide"]); // the fingers still need the wide one
    expect(agree(p, [wide, narrow, gear("best", ["EAR", "FINGER"], { stats: { HP: 95 } })])).toEqual(["best"]);
    expect(agree(p, [gear("zz-wide", ["EAR", "FINGER"], { stats: { HP: 20 } }), gear("aa-narrow", ["EAR"], { stats: { HP: 20 } })])).toEqual(["zz-wide"]);
  });
});

describe("the dimensions that are compared", () => {
  const SCHOOLS = CONSTANTS.schools;
  const DIMENSIONS = {
    // dimension -> the fields of an item that is better in it only
    ...Object.fromEntries(["STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "ATK"].map((name) => [name, { stats: { [name]: 4 } }])),
    HP: { stats: { HP: 40 } }, MANA: { stats: { MANA: 40 } }, END: { stats: { END: 40 } },
    HPREG: { stats: { HPREG: 2 } }, MANAREG: { stats: { MANAREG: 2 } }, ENDREG: { stats: { ENDREG: 2 } },
    AC: { stats: { AC: 9 } }, HASTE: { haste: 9 },
    ...Object.fromEntries(SCHOOLS.map((school) => [`SV_${school}`, { sv: { [school]: 9 } }])),
  };
  const ALL_WEIGHTS = ["HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", "CHA", "HPREG", "MANAREG", "ENDREG", "DMG", "SV"];

  for (const dimension of Object.keys(DIMENSIONS).sort()) {
    it(`an item better in ${dimension} and worse in another dimension does not replace it`, () => {
      const scored = prof(Object.fromEntries(ALL_WEIGHTS.map((name) => [name, 1]))); // every weight on: every dimension counts
      const gives = gear("gives", ["HEAD"], DIMENSIONS[dimension]);
      const hp = gear("hp-only", ["HEAD"], { stats: dimension !== "HP" ? { HP: 41 } : { MANA: 41 } });
      expect(agree(scored, [gives, hp])).toEqual(["gives", "hp-only"]);
    });
  }

  for (const dimension of ["STR", "AGI", "DEX", "WIS", "INT", "CHA", "MANA", "END", "ATK", "AC", "HASTE", "SV_FIRE"]) {
    it(`an item better only in ${dimension}, which nothing scores here, is replaced`, () => {
      const onlyHp = prof({ HP: 1 }); // HP scores HP and STA and nothing else
      const gives = gear("gives", ["HEAD"], DIMENSIONS[dimension]);
      const hp = gear("hp-only", ["HEAD"], { stats: { HP: 41 } });
      expect(agree(onlyHp, [gives, hp])).toEqual(["hp-only"]);
    });
  }

  it("does not let the dimensions that a trio cannot use block a drop", () => {
    // Paladin, Monk, Berserker: the only mana class is the Paladin, on WIS, so INT is worth nothing to this trio
    const pmb = prof({ HP: 1, MANA: 1 }, PMB);
    const a = gear("a", ["HEAD"], { stats: { HP: 50 } });
    const b = gear("b", ["HEAD"], { stats: { HP: 40, INT: 30 } });
    expect(agree(pmb, [a, b])).toEqual(["a"]);
    expect(agree(pmb, [a, gear("c", ["HEAD"], { stats: { HP: 40, WIS: 30 } })])).toEqual(["a", "c"]);
    expect(agree(prof({ HP: 1, MANA: 1 }), [a, b])).toEqual(["a", "b"]); // an Enchanter's mana is on INT: there it counts
    const none = prof({ HP: 1, MANA: 1 }, { pools: { HP: PMB_POOLS.HP, MANA: [], END: PMB_POOLS.END } }); // no mana class: no mana to gain, whatever the weight
    expect(agree(none, [a, gear("m", ["HEAD"], { stats: { HP: 40, MANA: 90, WIS: 20 } })])).toEqual(["a"]);
  });

  const EXPECTED = {
    // the one weight that is on -> the dimensions the builder's terms read, written out by hand
    HP: ["HP", "STA"], AC: ["AC", "AGI"], MANA: ["INT", "MANA", "WIS"], ATK: ["ATK", "STR"], DEX: ["DEX"], HASTE: ["HASTE"],
    END: ["AGI", "DEX", "END", "STA", "STR"], CHA: ["CHA"], HPREG: ["HPREG"], MANAREG: ["MANAREG"], ENDREG: ["ENDREG"], DMG: ["DMG", "HASTE"],
    SV: SCHOOLS.map((school) => `SV_${school}`).sort(), SV_FIRE: ["SV_FIRE"],
  };
  for (const weight of Object.keys(EXPECTED)) {
    it(`the weight ${weight} scores exactly the dimensions the builder's terms read`, () => {
      expect(sorted(scoredDimensions(prof({ [weight]: 1 }), "2h"))).toEqual(EXPECTED[weight]);
    });
  }

  it("scores no weapon in the stick or without a setup", () => {
    const p = prof({ DMG: 5 });
    expect(scoredDimensions(p, "stick")).toEqual([]);
    expect(scoredDimensions(p, null)).toEqual([]);
    expect(sorted(scoredDimensions(p, "dw"))).toEqual(["DMG", "HASTE"]);
    expect(scoredDimensions(prof({ DMG: 5, HASTE: 1 }), "stick")).toEqual(["HASTE"]);
  });

  it("scores no dimension of a pool that the trio does not have", () => {
    expect(sorted(scoredDimensions(prof({ MANA: 1, MANAREG: 1 }, PMB), "stick"))).toEqual(["MANA", "MANAREG", "WIS"]);
    const none = prof({ MANA: 1, MANAREG: 1 }, { pools: { HP: PMB_POOLS.HP, MANA: [], END: PMB_POOLS.END } });
    expect(sorted(scoredDimensions(none, "stick"))).toEqual(["MANAREG"]);
  });

  it("names the weights of the profile only: every weight scores something", () => {
    for (const weight of CONSTANTS.weightKeys) expect(scoredDimensions(prof({ [weight]: 1 }), "2h").length, weight).toBeGreaterThan(0);
  });
});

describe("weapons", () => {
  const dwPool = () => [
    // in the primary hand w5 hits harder (the listed bonus); in the off hand w6 does (no bonus there); w7 is w6 plus HP
    gear("w5", ["PRIMARY", "SECONDARY"], { weapon: oneHand(18, 20, 30) }),
    gear("w6", ["PRIMARY", "SECONDARY"], { weapon: oneHand(20, 20) }),
    gear("w7", ["PRIMARY", "SECONDARY"], { stats: { HP: 5 }, weapon: oneHand(20, 20) }),
  ];
  const withHaste = (haste) => ({ any_rule: "explicit", haste_assumed: haste });

  for (const haste of [0, 25, 50, 85]) {
    it(`keeps a weapon that is better in one hand and worse in the other, at the assumed haste ${haste}`, () => {
      const p = prof({ DMG: 300, HP: 1 }, { dw_factor: 0.8 });
      expect(agree(p, dwPool(), "dw", withHaste(haste))).toEqual(["w5", "w7"]); // w6 is w7 without the HP
    });
  }

  it("prunes a weapon pool to the same items at every assumed haste", () => {
    const p = prof({ DMG: 300, HP: 1 }, { dw_factor: 0.8 });
    const kept = [0, 40, 85].map((haste) => keysOf(run(p, dwPool(), "dw", withHaste(haste))));
    expect(kept[0]).toEqual(kept[1]);
    expect(kept[1]).toEqual(kept[2]);
  });

  it("compares weapons per setup, and the stick scores no weapon at all", () => {
    const p = prof({ DMG: 300, HP: 1 }, { dw_factor: 0.8 });
    const heavy = gear("heavy", ["PRIMARY"], { weapon: twoHand(40, 60) });
    const light = gear("light", ["PRIMARY"], { stats: { HP: 3 }, weapon: { skill: "2H Blunt", dmg: 10, delay: 60, bonus: null, two_handed: true } });
    expect(agree(p, [heavy, light], "2h")).toEqual(["heavy", "light"]); // heavy hits harder, light has HP: neither goes
    expect(agree(p, [heavy, light], "stick")).toEqual(["light"]); // the stick scores no damage: the HP of the light one decides
    const onlyDamage = prof({ DMG: 300 });
    expect(agree(onlyDamage, [heavy, light], "2h")).toEqual(["heavy"]);
    expect(agree(onlyDamage, [heavy, light], "stick")).toEqual(["heavy"]); // nothing is scored in the stick: the smaller key stays
  });

  it("gives the off hand an index with no bonus and the dual-wield factor", () => {
    const p = prof({ DMG: 300 }, { dw_factor: 0.5 });
    const bonus = gear("bonus", ["PRIMARY", "SECONDARY"], { weapon: oneHand(10, 20, 40) });
    const plain = gear("plain", ["PRIMARY", "SECONDARY"], { weapon: oneHand(12, 20) });
    expect(agree(p, [bonus, plain], "dw")).toEqual(["bonus", "plain"]); // bonus wins the primary hand, plain wins the off hand
    const onlyPrimary = gear("only-primary", ["PRIMARY"], { weapon: oneHand(10, 20, 40) });
    expect(agree(p, [onlyPrimary, bonus], "dw")).toEqual(["bonus"]); // the wider item with the same primary index replaces it
  });

  it("compares a shield by its armor class, and a worn point does not stand for a shield point", () => {
    const p = prof({ AC: 3, HP: 1 }, { softcap: [100, 0.2] });
    const big = gear("big", ["SECONDARY"], { stats: { AC: 30 }, shield: true });
    const small = gear("small", ["SECONDARY"], { stats: { AC: 20 }, shield: true });
    expect(agree(p, [big, small], "1h-shield")).toEqual(["big"]);
    // in the stick a held item with more armor class does not replace a shield: past the softcap a shield point counts for more than a worn point
    const chest = gear("chest", ["CHEST"], { stats: { AC: 160 } });
    const held = gear("held", ["SECONDARY"], { stats: { AC: 25 } });
    const pool = [chest, small, held];
    expect(agree(p, pool, "stick")).toEqual(["chest", "held", "small"]);
    expect(optimum(p, pool, "stick", null, OPT)).toBeGreaterThan(optimum(p, [chest, held], "stick", null, OPT));
  });

  it("gives the off hand of the shield setup to a typed shield only, not to a held item with armor class", () => {
    const held = gear("focus", ["SECONDARY"], { stats: { AC: 30, WIS: 5 } });
    const guard = gear("guard", ["SECONDARY"], { stats: { AC: 10 }, shield: true });
    const p = prof({ AC: 3, HP: 1 }, { softcap: [100, 0.2] });
    expect(sorted(fitGroups(held, "1h-shield", "explicit"))).toEqual([]);
    expect(sorted(fitGroups(guard, "1h-shield", "explicit"))).toEqual(["SECONDARY"]);
    const report = pruneReport([held, guard], p, 0, "1h-shield", null, OPT);
    expect(keysOf(report.kept)).toEqual(["guard"]);
    expect([...report.dropped]).toEqual([["focus@0", ["no-slot", null]]]);
    expect(agree(p, [held, guard], "1h-shield")).toEqual(["guard"]);
    expect(agree(p, [held, guard], "stick")).toEqual(["focus", "guard"]); // a shield point and a worn point are not alike
  });

  it("does not let a two-hander replace a one-hander that could share the hands with a secondary item", () => {
    // T is better than O in every dimension and fits every hand O fits (O lists only the main hand), but a two-hander in the primary hand empties
    // the secondary hand, where the held item X is worth 100
    const p = prof({ HP: 1 });
    const t = gear("t", ["PRIMARY", "SECONDARY"], { stats: { HP: 60 }, weapon: twoHand(40, 60) });
    const o = gear("o", ["PRIMARY"], { stats: { HP: 50 }, weapon: oneHand(20, 30) });
    const x = gear("x", ["SECONDARY"], { stats: { HP: 100 } });
    expect(agree(p, [t, o, x])).toEqual(["o", "t", "x"]);
    expect(close(optimum(p, [t, o, x], "stick", null, OPT), emptyValue(p) + 150)).toBe(true);
    expect(optimum(p, [t, x], "stick", null, OPT)).toBeLessThan(emptyValue(p) + 150);
    const better = gear("better", ["PRIMARY", "SECONDARY"], { stats: { HP: 70 }, weapon: oneHand(20, 30) });
    expect(agree(p, [t, better, x])).toEqual(["better", "x"]); // a one-hander that beats a two-hander replaces it
  });

  it("does not let a two-hander that lists the off hand replace what fits it: it never stands there", () => {
    const p = prof({ HP: 1 });
    const t = gear("t", ["PRIMARY", "SECONDARY"], { stats: { HP: 60 }, weapon: twoHand(40, 60) });
    const b = gear("b", ["SECONDARY"], { stats: { HP: 50 } });
    const c = gear("c", ["PRIMARY"], { stats: { HP: 55 }, weapon: oneHand(20, 30) });
    for (const setup of [null, "stick", "2h", "dw", "1h-shield"]) {
      expect(fitGroups(t, setup, "explicit").has("SECONDARY")).toBe(false);
      expect(fitGroups(t, setup).has("SECONDARY")).toBe(false);
    }
    expect(sorted(fitGroups(t, "stick", "explicit"))).toEqual(["PRIMARY"]);
    expect(agree(p, [t, b, c])).toEqual(["b", "c", "t"]); // t cannot replace c either: it would empty the off hand
    expect(close(optimum(p, [t, b, c], "stick", null, OPT), emptyValue(p) + 105)).toBe(true);
    expect(close(optimum(p, [t, c], "stick", null, OPT), emptyValue(p) + 60)).toBe(true);
    // the builder makes no column for it in the off hand, which is what fitGroups says
    const model = buildMilp(p, [t, b, c], "stick", null, OPT);
    expect(model.item_cols.filter(([, , key]) => key === "t").map(([, group]) => group)).toEqual(["PRIMARY"]);
  });
});

describe("the weight of a Monk", () => {
  const pmb = (weights, changes = {}) => prof(weights, { pools: PMB_POOLS, monk: MONK_CURVE, haste_cap: 85, ...changes });
  const WITH_BINS = deepFreeze({ ...OPT, monk_bins: MONK_BINS });
  const pair = (heavyWeight) => [
    gear("heavy", ["CHEST"], { stats: { AC: 40, HP: 100 }, weight10: heavyWeight }),
    gear("light", ["CHEST"], { stats: { AC: 30, HP: 80 }, weight10: 10 }),
  ];
  const agreeMonk = (profile, items) => agree(profile, items, "stick", WITH_BINS);

  it("keeps a lighter, weaker item for a Monk trio whose weight matters, and not for a trio without a Monk", () => {
    const p = pmb({ AC: 3, HP: 1 });
    expect(agreeMonk(p, pair(330))).toEqual(["heavy", "light"]); // 33 stones against 1 stone: the fade costs more than the stats
    expect(optimum(p, pair(330), "stick", null, WITH_BINS)).toBeGreaterThan(optimum(p, pair(330).slice(0, 1), "stick", null, WITH_BINS));
    expect(agree(prof({ AC: 3, HP: 1 }), pair(330))).toEqual(["heavy"]);
  });

  it("ignores the weight when every reachable weight earns the full bonus", () => {
    const p = pmb({ AC: 3, HP: 1 });
    expect(agreeMonk(p, pair(60))).toEqual(["heavy"]); // one chest piece alone can never reach the seventeen stones of the fade
    expect(pruneReport(pair(60), p, 0, "stick", null, WITH_BINS).weightRule).toBeNull();
    const legs = [100, 90].map((weight, n) => gear(`legs${n}`, ["LEGS"], { stats: { HP: 1 }, weight10: weight }));
    const report = pruneReport([...pair(100), ...legs], p, 0, "stick", null, WITH_BINS);
    expect(report.weightRule).toBe("le"); // a chest piece and legs together can reach the fade
    expect(keysOf(report.kept)).toEqual(["heavy", "legs1", "light"]); // the lighter legs replace the heavier ones; the pair stays
    expect(agreeMonk(p, [...pair(100), ...legs])).toEqual(["heavy", "legs1", "light"]);
    expect(report.compared).toContain("WEIGHT");
  });

  it("does not score the weight without an armor class weight", () => {
    const p = pmb({ HP: 1 });
    expect(agreeMonk(p, pair(330))).toEqual(["heavy"]);
    expect(pruneReport(pair(330), p, 0, "stick", null, WITH_BINS).weightRule).toBeNull();
  });

  it("needs the Monk bins when the weight is scored, as the builder does, and not when it is not", () => {
    expect(() => run(pmb({ AC: 3, HP: 1 }), pair(330))).toThrow(/monk_bins/);
    expect(() => run(pmb({ HP: 1 }), pair(330))).not.toThrow();
    expect(() => run(prof({ AC: 3, HP: 1 }), pair(330))).not.toThrow();
  });

  for (const placement of ["top", "inside"]) {
    it(`holds the weight rule with the bonus ${placement === "top" ? "on top of the cap" : "inside it"}`, () => {
      const p = pmb({ AC: 3, HP: 1 }, { placement: { monk: placement, iksar: "top" } });
      const pool = [...pair(420), gear("mid", ["CHEST"], { stats: { AC: 35, HP: 90 }, weight10: 200 })];
      expect(agreeMonk(p, pool)).toEqual(["heavy", "light", "mid"]);
    });
  }

  it("makes the weight an equality when the bonus is not monotone in it", () => {
    const stones = MONK_BINS.bonus.length;
    const bumpy = deepFreeze({
      ...clone(MONK_BINS),
      bonus: Array.from({ length: stones }, (_, stone) => `${stone % 5 === 0 ? 40 : stone % 2 === 1 ? 0 : 10}/1`),
      alternatives: [],
    });
    const options = deepFreeze({ ...OPT, monk_bins: bumpy });
    const p = pmb({ AC: 3, HP: 1 });
    const twin = gear("heavy2", ["CHEST"], { stats: { AC: 39, HP: 99 }, weight10: 330 });
    const pool = [...pair(330), twin];
    expect(pruneReport(pool, p, 0, "stick", null, options).weightRule).toBe("eq");
    expect(agree(p, pool, "stick", options)).toEqual(["heavy", "light"]); // equal weight: heavy replaces heavy2; unequal weight: nothing else goes
  });
});

describe("haste, resists, eligibility and odds and ends", () => {
  it("lets haste block a drop only when haste is scored (the weapon term scores it too)", () => {
    const a = gear("a", ["HEAD"], { stats: { HP: 100 } });
    const b = gear("b", ["HEAD"], { stats: { HP: 10 }, haste: 60 });
    const scored = prof({ HASTE: 2, HP: 1 });
    expect(agree(scored, [a, b])).toEqual(["a", "b"]);
    expect(optimum(scored, [a, b], "stick", null, OPT)).toBeGreaterThan(optimum(scored, [a], "stick", null, OPT));
    expect(agree(prof({ HP: 1 }), [a, b])).toEqual(["a"]);
    const weaponsOnly = prof({ DMG: 300, HP: 1 });
    expect(agree(weaponsOnly, [a, b], "2h")).toEqual(["a", "b"]);
    expect(agree(weaponsOnly, [a, b], "stick")).toEqual(["a"]);
  });

  it("counts a slowing item for no haste at all", () => {
    const p = prof({ HASTE: 2, HP: 1 });
    const slow = gear("a-slow", ["HEAD"], { stats: { HP: 5 }, haste: -10 });
    const plain = gear("b-plain", ["HEAD"], { stats: { HP: 5 } });
    expect(agree(p, [slow, plain])).toEqual(["a-slow"]); // equal in every compared dimension: the smaller key stays
    expect(agree(p, [plain, gear("c-quick", ["HEAD"], { stats: { HP: 5 }, haste: 5 })])).toEqual(["c-quick"]);
  });

  it("drops a dominated resist, and not a resist of another school", () => {
    const p = prof({ SV: 1 });
    const [fire, cold, less] = [["fire", "FIRE", 150], ["cold", "COLD", 150], ["less", "FIRE", 100]].map(([key, school, amount]) => gear(key, ["EAR"], { sv: { [school]: amount } }));
    expect(agree(p, [fire, cold, less])).toEqual(["cold", "fire"]);
    expect(close(optimum(p, [fire, cold, less], "stick", null, OPT), emptyValue(p) + 150 + 150)).toBe(true);
    expect(agree(prof({ SV_FIRE: 1 }), [fire, cold, less])).toEqual(["fire"]); // only the fire resist is scored
  });

  it("drops items of other classes and deities first, and lets them replace nothing", () => {
    const p = prof({ HP: 1 });
    const mine = gear("mine", ["HEAD"], { stats: { HP: 10 }, classes: ["WAR"] });
    const other = gear("other", ["HEAD"], { stats: { HP: 99 }, classes: ["MNK"] });
    const god = gear("god", ["HEAD"], { stats: { HP: 98 }, deity: ["Brell"] });
    const report = pruneReport([mine, other, god], p, 0, "stick", null, OPT);
    expect(keysOf(report.kept)).toEqual(["mine"]);
    expect([...report.dropped]).toEqual([["other@0", ["class", null]], ["god@0", ["deity", null]]]);
    expect(agree(p, [mine, other, god])).toEqual(["mine"]);
    expect(agree(profileWith({ weights: { HP: 1 }, deity: "Brell" }), [mine, other, god])).toEqual(["god"]); // the Brell item beats "mine" and replaces it
    expect(agree(profileWith({ weights: { HP: 1 }, deity: "Tunare" }), [mine, god])).toEqual(["mine"]);
  });

  it("drops items that exclude the race of the profile first, and lets them replace nothing", () => {
    const plain = gear("plain", ["HEAD"], { stats: { HP: 10 } });
    const humans = gear("humans", ["HEAD"], { stats: { HP: 99 }, races: ["HUM"] });
    const erudite = profileWith({ weights: { HP: 1 }, race: "ERU" });
    const report = pruneReport([plain, humans], erudite, 0, "stick", null, OPT);
    expect(keysOf(report.kept)).toEqual(["plain"]);
    expect([...report.dropped]).toEqual([["humans@0", ["race", null]]]);
    expect(agree(erudite, [plain, humans])).toEqual(["plain"]);
    expect(agree(profileWith({ weights: { HP: 1 }, race: "HUM" }), [plain, humans])).toEqual(["humans"]);
    expect(agree(prof({ HP: 1 }), [plain, humans])).toEqual(["humans"]); // a profile with no race restricts nothing
  });

  it("assumes the haste the builder assumes, from the profile's spell haste and the pool's best worn haste", () => {
    const boots = gear("boots", ["FEET"], { haste: 20 });
    const hasty = profileWith({ weights: { DMG: 1 }, spell_haste: 30 });
    expect(pruneReport([boots], hasty, 0, "2h", null).hasteAssumed).toBe(50);
    expect(buildMilp(hasty, [boots], "2h", null, {}).info.haste_assumed).toBe(50);
    // without a spell haste of its own the profile takes the best on offer in the buff set
    const buffset = buffsetOf({ optional: [buffOf(1, { HASTE: 25 }), buffOf(2, { HASTE: 10 })], conflicts: [[1, 2]] });
    expect(pruneReport([boots], prof({ DMG: 1 }), 0, "2h", buffset).hasteAssumed).toBe(45);
    expect(pruneReport([boots], prof({ DMG: 1 }), 0, "2h", buffset, { haste_assumed: 7 }).hasteAssumed).toBe(7);
    expect(pruneReport([boots], prof({ DMG: 1 }), 0, "2h", buffset, { haste_assumed: 7 }).hasteAssumed).toBe(
      buildMilp(prof({ DMG: 1 }), [boots], "2h", buffset, { haste_assumed: 7 }).info.haste_assumed,
    );
    expect(pruneReport([boots], prof({ DMG: 1 }), 0, "2h", buffset).hasteAssumed).toBe(buildMilp(prof({ DMG: 1 }), [boots], "2h", buffset, {}).info.haste_assumed);
  });

  it("drops an item that fits no group as having no place, and follows the Any rule", () => {
    const p = prof({ HP: 1 });
    const ammo = gear("ammo", ["AMMO"], { stats: { HP: 99 } });
    const head = gear("head", ["HEAD"], { stats: { HP: 5 } });
    const report = pruneReport([ammo, head], p, 0, "stick", null, { any_rule: "all", haste_assumed: 0 });
    expect(keysOf(report.kept)).toEqual(["head"]);
    expect([...report.dropped]).toEqual([["ammo@0", ["no-slot", null]]]);
    const axe = gear("axe", ["PRIMARY"], { weapon: twoHand(40, 60) });
    expect(sorted(fitGroups(axe, "dw"))).toEqual(["ANY"]); // no hand takes it in dual wield; the Any group does
    expect(sorted(fitGroups(axe, "dw", "explicit"))).toEqual([]);
    expect(sorted(fitGroups(axe, "2h"))).toEqual(["ANY", "PRIMARY"]);
    expect(sorted(fitGroups(axe, null))).toEqual(sorted(fitGroups(axe, "stick")));
    expect(sorted(fitGroups(axe, "stick"))).toEqual(["ANY", "PRIMARY"]);

    const sticky = gear("sticky", ["ANY"], { stats: { HP: 60 } });
    const every = { any_rule: "all", haste_assumed: 0 };
    expect(agree(p, [gear("head", ["HEAD"], { stats: { HP: 50 } }), sticky], "stick", OPT)).toEqual(["head", "sticky"]);
    expect(agree(p, [gear("head", ["HEAD"], { stats: { HP: 50 } }), sticky], "stick", every)).toEqual(["head", "sticky"]); // sticky fits only Any; head fits both
    const better = gear("head2", ["HEAD"], { stats: { HP: 70 } });
    const heads = [gear("head", ["HEAD"], { stats: { HP: 50 } }), better, sticky];
    expect(agree(p, heads, "stick", every)).toEqual(["head2"]); // "all": the better head piece fits the Any group too, so it replaces the Any piece
    expect(agree(p, heads, "stick", OPT)).toEqual(["head2", "sticky"]); // "explicit": it does not fit there
  });

  it("sorts the result by key and tier, leaves the input alone, and works with the defaults", () => {
    const p = prof({ HP: 1, END: 1 });
    expect(prune([], p, 0, "stick", null, OPT)).toEqual([]);
    const items = deepFreeze([
      ...["c", "b", "a"].map((key, n) => gear(key, ["HEAD"], { stats: { STA: n + 1 } })),
      ...["q", "p"].map((key) => gear(key, ["NECK"], { stats: { HP: 7 } })),
    ]);
    const before = items.map(identOf);
    const kept = prune(items, p, 0, "stick", null, OPT);
    expect(items.map(identOf)).toEqual(before);
    expect(kept.map((item) => item.key)).toEqual(["a", "p"]); // a has the most STA; p is the smaller of the twins
    expect(prune(items, p, 0, "stick").map((item) => item.key)).toEqual(["a", "p"]);
    expect(prune([...items].reverse(), p, 0, "stick", null, OPT).map((item) => item.key)).toEqual(["a", "p"]);
    const tiers = [gear("x", ["HEAD"], { stats: { HP: 1 }, tier: 3 }), gear("x", ["HEAD"], { stats: { HP: 5 }, tier: 1 }), gear("a", ["HEAD"], { stats: { HP: 9 }, tier: 2 })];
    expect(prune(tiers, p, null, "stick", null, OPT).map(identOf)).toEqual(["a@2", "x@1", "x@3"]); // other tiers drop nothing; sorted by key, then tier
  });

  it("refuses bad input like the builder refuses it", () => {
    const p = prof({ HP: 1 });
    const ok = gear("ok", ["HEAD"], { stats: { HP: 1 } });
    expect(() => prune([ok], p, 0, "bow", null, OPT)).toThrow(/setup/);
    expect(() => prune([ok, ok], p, 0, "stick", null, OPT)).toThrow(/twice/);
    // a hole in a list is an error, as an entry that is not an item is: `forEach` and `map` would step over it
    const holey = [ok, undefined, gear("other", ["NECK"], { stats: { HP: 2 } })];
    delete holey[1];
    expect(1 in holey).toBe(false);
    expect(() => prune(holey, p, 0, "stick", null, OPT)).toThrow(PruneError);
    expect(() => prune(holey, p, 0, "stick", null, OPT)).toThrow(/hole/);
    expect(() => prune([ok, undefined], p, 0, "stick", null, OPT)).toThrow(ModelError);
    expect(() => prune([ok], p, 0, "stick", null, OPT, new Array(1))).toThrow(/owned names idents/); // a hole in the owned idents
    expect(() => prune([ok], p, 0, "stick", null, OPT, ["ok@0", undefined])).toThrow(PruneError);
    expect(() => prune([gear("bad", ["HEAD"], { stats: { LUCK: 3 } })], p, 0, "stick", null, OPT)).toThrow(/unknown stat/);
    expect(() => prune([gear("bad", ["HEAD"], { sv: { LUCK: 3 } })], p, 0, "stick", null, OPT)).toThrow(/unknown resist/);
    expect(() => prune([gear("high", ["HEAD"], { tier: 4 })], p, 0, "stick", null, OPT)).toThrow(/tier/);
    for (const tier of ["0", 1.5, true, -1, undefined]) expect(() => prune([ok], p, tier, "stick", null, OPT), String(tier)).toThrow(PruneError);
    const negative = prof({ HP: 1 }, { pools: { HP: [{ cls: "WAR", base: 1500, fac: -1 }, { cls: "CLR", base: 1320, fac: 4.4 }], MANA: [], END: [{ cls: "WAR", base: 900, fac: 4.5 }] } });
    expect(() => prune([ok], negative, 0, "stick", null, OPT)).toThrow(/factor/);
    expect(() => prune("ok", p, 0, "stick", null, OPT)).toThrow(PruneError);
    expect(() => prune([ok], p, 0, "stick", null, { any_rule: "all", hast_assumed: 3 })).toThrow(ModelError); // an option nothing reads: refused as the builder refuses it
    expect(() => prune([ok], p, 0, "stick", null, OPT, "ok@0")).toThrow(/owned is a set of idents/);
    expect(() => prune([ok], p, 0, "stick", null, OPT, [3])).toThrow(/owned names idents/);
    expect(() => prune([ok], p, 0, "stick", null, { ...OPT, upgrades: { "ok@4": "ok@0" } })).toThrow(ModelError); // an upgrade whose source is not owned
  });
});

// ---- the owned items and the tiers ----------------------------------------------------------------------------------------------------

describe("the owned-item mode", () => {
  const PROFILE = profileWith({ weights: { HP: 1 }, pools: PMB_POOLS });
  const options = (changes = {}) => ({ any_rule: "explicit", haste_assumed: 0, ...changes });
  const item = (key, hp, { tier = 0, slots = ["FINGER"], lore = false, ...more } = {}) => gear(key, slots, { stats: { HP: hp }, tier, lore, ...more });
  const idents = (items) => items.map(identOf).sort();
  const runOwned = (items, owned = [], tier = null, changes = {}) => prune(items, PROFILE, tier, "stick", null, options(changes), owned);
  const best = (items, changes = {}) => optimum(PROFILE, items, "stick", null, options(changes));

  it("never drops an owned item, even when a candidate is better in every way", () => {
    const own = item("chest-own", 10, { slots: ["CHEST"] });
    const top = item("chest-best", 100, { slots: ["CHEST"] });
    expect(idents(runOwned([own, top]))).toEqual(["chest-best@0"]); // nothing owned: the usual rule
    expect(idents(runOwned([own, top], ["chest-own@0"]))).toEqual(["chest-best@0", "chest-own@0"]);
    expect(idents(runOwned([own, top], [], null, { owned_caps: { "chest-own@0": 1 } }))).toEqual(["chest-best@0", "chest-own@0"]); // the caps name them too
  });

  it("keeps an owned item the profile cannot use, and drops a stranger", () => {
    const locked = gear("locked-ear", ["EAR"], { stats: { HP: 90 }, deity: ["Tunare"] });
    const stranger = gear("locked-twin", ["EAR"], { stats: { HP: 90 }, deity: ["Tunare"] });
    const caster = gear("caster-ring", ["FINGER"], { stats: { HP: 90 }, classes: ["CLR", "WIZ"] });
    const plain = item("plain", 4, { slots: ["EAR"] });
    const pool = [locked, stranger, caster, plain];
    const owned = ["locked-ear@0", "caster-ring@0"];
    const kept = runOwned(pool, owned);
    expect(idents(kept)).toEqual(["caster-ring@0", "locked-ear@0", "plain@0"]);
    const report = pruneReport(pool, PROFILE, null, "stick", null, options(), owned);
    expect([...report.dropped]).toEqual([["locked-twin@0", ["deity", null]]]);
    const caps = { "locked-ear@0": 1, "caster-ring@0": 1 };
    expect(best(pool, { owned_caps: caps })).toBe(best(kept, { owned_caps: caps })); // the builder gives the owned strangers no column, so nothing changes
  });

  it("asks for tier null when the pool holds many tiers, and for a whole number when every item is at one", () => {
    const pool = [item("a", 5, { slots: ["EAR"] }), item("b", 3, { tier: 4, slots: ["EAR"] })];
    expect(() => runOwned(pool, [], 0)).toThrow(/tier/);
    expect(() => runOwned(pool, [], 4)).toThrow(/tier/);
    expect(runOwned(pool, [], null).length).toBeGreaterThan(0);
  });

  it("drops a candidate only for a candidate at its own tier", () => {
    const [a, b, c] = [item("a", 50, { tier: 4, slots: ["EAR"] }), item("b", 10, { tier: 0, slots: ["EAR"] }), item("c", 10, { tier: 4, slots: ["EAR"] })];
    expect(idents(runOwned([a, b]))).toEqual(["a@4", "b@0"]); // a is better in every way but not at b's tier
    expect(idents(runOwned([a, c]))).toEqual(["a@4"]); // at its own tier it is dropped as always
    expect(idents(runOwned([a, b, c]))).toEqual(["a@4", "b@0"]);
  });

  it("drops a candidate of any tier for an owned item with enough copies, and keeps it when the owned row could bind", () => {
    const [own, cand] = [item("ring-own", 10, { tier: 4 }), item("ring-cand", 3)];
    expect(idents(runOwned([own, cand], ["ring-own@4"], null, { owned_caps: { "ring-own@4": 2 } }))).toEqual(["ring-own@4"]); // two copies fill the two finger places
    expect(idents(runOwned([own, cand], ["ring-own@4"], null, { owned_caps: { "ring-own@4": 9 } }))).toEqual(["ring-own@4"]);
    const [anyOwn, anyCand] = [item("any-own", 10, { slots: ["FINGER", "ANY"] }), item("any-cand", 3, { slots: ["FINGER", "ANY"] })];
    expect(idents(runOwned([anyOwn, anyCand], [], null, { owned_caps: { "any-own@0": 3 } }))).toEqual(["any-cand@0", "any-own@0"]);
    expect(idents(runOwned([anyOwn, anyCand], [], null, { owned_caps: { "any-own@0": 4 } }))).toEqual(["any-own@0"]);
  });

  it("lets the count decide whether the weaker ring is needed, and the pruned pool agrees", () => {
    const [own, cand] = [item("ring-own", 10), item("ring-cand", 3)];
    for (const [count, expected] of [[1, ["ring-cand@0", "ring-own@0"]], [2, ["ring-own@0"]]]) {
      const changes = { owned_caps: { "ring-own@0": count }, new_keys: ["ring-cand@0"], max_new: 1 };
      const kept = runOwned([own, cand], [], null, changes);
      expect(idents(kept), String(count)).toEqual(expected);
      const restricted = { ...changes, new_keys: ["ring-cand@0"].filter((name) => idents(kept).includes(name)) };
      expect(close(best([own, cand], changes), best(kept, restricted))).toBe(true);
    }
    const one = { owned_caps: { "ring-own@0": 1 }, new_keys: ["ring-cand@0"], max_new: 1 };
    expect(best([own, cand], one)).toBeGreaterThan(best([own], { owned_caps: { "ring-own@0": 1 } })); // with one copy the weaker ring is worth acquiring
  });

  it("lets an upgrade target replace nothing: it shares the copy of its source", () => {
    const [source, target, other] = [item("band", 1, { tier: 2 }), item("band", 20, { tier: 4 }), item("band2", 15, { tier: 4 })];
    const caps = { "band@2": 1 };
    const ups = { "band@4": "band@2" };
    for (const maxNew of [1, 2]) {
      const changes = { owned_caps: caps, upgrades: ups, new_keys: ["band2@4"], max_new: maxNew };
      const kept = runOwned([source, target, other], [], null, changes);
      expect(idents(kept)).toEqual(["band2@4", "band@2", "band@4"]);
      expect(close(best([source, target, other], changes), best(kept, changes))).toBe(true);
    }
    const two = best([source, target, other], { owned_caps: caps, upgrades: ups, new_keys: ["band2@4"], max_new: 2 });
    // the upgraded copy and a copy of the upgrade (20 + 20): band2 is no longer needed, though the pruning (exact, not tight) keeps it
    expect(close(two, best([]) + 40)).toBe(true);
  });

  it("lets an upgrade target replace nothing because its first wear costs a copy of its source", () => {
    const [source, target, other] = [item("band", 10, { tier: 2 }), item("band", 12, { tier: 4 }), item("band2", 11, { tier: 4 })];
    const changes = { owned_caps: { "band@2": 1 }, upgrades: { "band@4": "band@2" }, new_keys: ["band2@4"], max_new: 1 };
    const kept = runOwned([source, target, other], [], null, changes);
    expect(idents(kept)).toEqual(["band2@4", "band@2", "band@4"]);
    expect(close(best([source, target, other], changes), best([]) + 21)).toBe(true); // the owned copy and one acquired band2
    const only = { owned_caps: { "band@2": 1 }, upgrades: { "band@4": "band@2" }, max_new: 1 };
    expect(close(best([source, target], only), best([]) + 12)).toBe(true); // dropping band2 for the target would lose 9
  });

  it("does not drop a free item for a new one that the limit may forbid, and drops a new item for a free one", () => {
    const [fresh, free] = [item("new-ring", 20), item("free-ring", 10)];
    const changes = { new_keys: ["new-ring@0"], max_new: 0 };
    const kept = runOwned([fresh, free], [], null, changes);
    expect(idents(kept)).toContain("free-ring@0");
    expect(close(best(kept, changes), best([]) + 20)).toBe(true); // two free rings; the new one may not be acquired
    expect(close(best([fresh, free], changes), best([]) + 20)).toBe(true);
    expect(idents(runOwned([item("new-ring", 10), item("free-ring", 20)], [], null, changes))).toEqual(["free-ring@0"]);
  });

  it("lets a duplicate replace a new item of its tier and not one of another tier", () => {
    const [dup, weak] = [item("ring-dup", 10), item("ring-weak", 3)];
    const changes = { owned_caps: { "ring-dup@0": 1 }, new_keys: ["ring-dup@0", "ring-weak@0"], max_new: 1 };
    const kept = runOwned([dup, weak], [], null, changes);
    expect(idents(kept)).toEqual(["ring-dup@0"]);
    expect(close(best([dup, weak], changes), best(kept, { ...changes, new_keys: ["ring-dup@0"] }))).toBe(true);
    const otherTier = item("ring-weak", 3, { tier: 3 });
    const mixed = { owned_caps: { "ring-dup@0": 1 }, new_keys: ["ring-dup@0", "ring-weak@3"], max_new: 1 };
    expect(idents(runOwned([dup, otherTier], [], null, mixed))).toEqual(["ring-dup@0", "ring-weak@3"]);
  });

  it("lets a Lore item never justify a drop in the owned mode either", () => {
    const [lore, plain] = [item("band", 20, { slots: ["EAR"], lore: true }), item("stud", 5, { slots: ["EAR"] })];
    const changes = { owned_caps: { "band@0": 1 }, new_keys: ["stud@0"], max_new: 1 };
    expect(idents(runOwned([lore, plain], [], null, changes))).toEqual(["band@0", "stud@0"]);
  });

  it("changes nothing for a pool with no owned item", () => {
    const pool = [item("a", 5, { slots: ["EAR"] }), item("b", 3, { slots: ["EAR"] }), item("c", 9, { slots: ["FINGER"] })];
    expect(prune(pool, PROFILE, 0, "stick", null, options()).map(identOf)).toEqual(prune(pool, PROFILE, 0, "stick", null, options(), []).map(identOf));
    expect(prune(pool, PROFILE, 0, "stick", null, options()).map(identOf)).toEqual(prune(pool, PROFILE, 0, "stick", null, options(), new Set()).map(identOf));
  });
});

// ---- random pools --------------------------------------------------------------------------------------------------------------------

/**
 * A random instance for the exactness checks: a few items in the slots of the hands and of two or three armor places, some of them Lore, some a
 * two-hander or a shield, some with haste or resists, and weights that score some of it. The same seed gives the same instance.
 */
function randomInstance(seed) {
  const random = mulberry32(seed);
  const whole = (low, high) => low + Math.floor(random() * (high - low + 1));
  const pick = (list) => list[whole(0, list.length - 1)];
  const weights = {};
  for (const name of ["HP", "MANA", "END", "AC", "ATK", "HASTE", "DMG", "DEX", "CHA", "HPREG", "SV"]) if (random() < 0.5) weights[name] = whole(1, 4);
  if (Object.keys(weights).length === 0) weights.HP = 1;
  const setup = pick(["stick", "dw", "1h-shield", "2h", null]);
  const profile = profileWith({ weights, dw_factor: pick([0.5, 0.8, 1]), softcap: pick([[0, 0], [120, 0.3]]), haste_cap: 75 });
  const slotsOf = () => pick([["HEAD"], ["EAR"], ["EAR", "FINGER"], ["FINGER"], ["CHEST"], ["PRIMARY"], ["PRIMARY", "SECONDARY"], ["SECONDARY"], ["ANY"]]);
  const items = [];
  const count = whole(5, 11);
  for (let n = 0; n < count; n += 1) {
    const slots = slotsOf();
    const stats = {};
    for (const name of ["HP", "STA", "WIS", "INT", "AC", "AGI", "STR", "ATK", "MANA", "END", "HPREG"]) if (random() < 0.3) stats[name] = whole(1, 40);
    const more = { stats, lore: random() < 0.2, haste: random() < 0.15 ? whole(1, 30) : 0 };
    if (random() < 0.25) more.sv = { [pick(CONSTANTS.schools)]: whole(1, 30) };
    if (slots.includes("SECONDARY") && !slots.includes("PRIMARY") && random() < 0.5) more.shield = true;
    if (slots.includes("PRIMARY") && random() < 0.8) more.weapon = random() < 0.35 ? twoHand(whole(30, 60), whole(40, 70), random() < 0.3 ? whole(1, 20) : null) : oneHand(whole(8, 30), whole(15, 40), random() < 0.3 ? whole(1, 20) : null);
    items.push(gear(`it${String(n).padStart(2, "0")}`, slots, { ...more, tier: 0 }));
  }
  return { profile, items, setup, options: { any_rule: pick(["all", "explicit"]), haste_assumed: random() < 0.4 ? whole(0, 40) : null } };
}

describe("random pools", () => {
  const SEEDS = Array.from({ length: 60 }, (_, n) => n + 1);

  it("keep the optimum of the full pool, under the plain rule (60 pools, every setup)", () => {
    let dropped = 0;
    for (const seed of SEEDS) {
      const { profile, items, setup, options } = randomInstance(seed);
      const kept = prune(items, profile, 0, setup, null, options);
      dropped += items.length - kept.length;
      const full = optimum(profile, items, setup, null, options);
      const small = optimum(profile, kept, setup, null, options);
      expect(close(full, small), `seed ${seed} (${setup}): ${full} against ${small}, kept ${kept.length} of ${items.length}`).toBe(true);
    }
    expect(dropped, "the pools are made so that some items go").toBeGreaterThan(SEEDS.length);
  });

  it("keep the optimum of the full pool, under the owned-item options (60 pools of mixed tiers)", () => {
    let dropped = 0;
    let owners = 0;
    for (const seed of SEEDS) {
      const random = mulberry32(1000 + seed);
      const whole = (low, high) => low + Math.floor(random() * (high - low + 1));
      const base = randomInstance(seed);
      // some items become the same key at two tiers (the higher one a candidate for an upgrade), some are owned, with counts
      const items = [];
      for (const item of base.items) {
        items.push(item);
        if (random() < 0.3) items.push(gear(item.key, item.slots, { stats: Object.fromEntries(Object.entries(item.stats).map(([k, v]) => [k, v + whole(1, 10)])), lore: item.lore, haste: item.haste, sv: item.sv, weapon: item.weapon, shield: item.is_shield, tier: whole(1, 4) }));
      }
      const idents = items.map(identOf);
      const caps = {};
      for (const name of idents) if (random() < 0.35) caps[name] = whole(1, 3);
      const ups = {};
      for (const name of idents) {
        const key = name.slice(0, name.indexOf("@"));
        const tier = Number(name.slice(name.indexOf("@") + 1));
        const lower = idents.filter((other) => other.startsWith(`${key}@`) && Number(other.slice(other.indexOf("@") + 1)) < tier && caps[other] >= 1);
        if (!(name in caps) && lower.length > 0 && random() < 0.7) ups[name] = lower[lower.length - 1];
      }
      const news = idents.filter((name) => !(name in ups) && random() < 0.4);
      const changes = { ...base.options, owned_caps: caps, new_keys: news, upgrades: ups, max_new: random() < 0.7 ? whole(0, 2) : null };
      if (Object.keys(caps).length > 0) owners += 1;
      const kept = prune(items, base.profile, null, base.setup, null, changes, Object.keys(caps));
      const present = new Set(kept.map(identOf));
      // the options of the pruned pool name the items that are still in it, as the farm path does
      const restricted = {
        ...changes,
        new_keys: news.filter((name) => present.has(name)),
        upgrades: Object.fromEntries(Object.entries(ups).filter(([name]) => present.has(name))),
      };
      dropped += items.length - kept.length;
      for (const name of Object.keys(caps)) expect(present.has(name), `seed ${seed}: the owned ${name} stays`).toBe(true);
      const full = optimum(base.profile, items, base.setup, null, changes);
      const small = optimum(base.profile, kept, base.setup, null, restricted);
      expect(close(full, small), `seed ${seed} (${base.setup}): ${full} against ${small}, kept ${kept.length} of ${items.length}`).toBe(true);
    }
    expect(owners).toBeGreaterThan(SEEDS.length / 2);
    expect(dropped, "the pools are made so that some items go, though the owned ones stay").toBeGreaterThan(SEEDS.length / 4);
  });
});
