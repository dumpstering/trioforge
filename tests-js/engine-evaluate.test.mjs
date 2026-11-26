import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { CONSTANTS, EvaluateError, MONK_STONES_PAST_HARDCAP, PART_NAMES, SLOT_INSTANCES, UNITS, evaluate, monkTable, profileOf } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { atTier } from "../pipeline/trioforge/site/static/engine/items.js";
import { assembleProfile, buffsetOf, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";
import { mulberry32 } from "./engine-models.mjs";
import { SAMPLE, describeFull } from "./engine-fixtures.mjs";
import { expectWithin, stopwatch } from "./timing.mjs";

// The exact evaluator: evaluate(profile, kit, buffsChosen, {setup, hasteAssumed, monkBins, buffset}) is formulas.evaluate of
// pipeline/trioforge/model/formulas.py on BigInt rationals. It is held to Python three ways:
//   * the parity fixtures: every kit of the committed sample, always, and the 5,000 kits of the full set when it is there, valued field by
//     field and exactly (every number a reduced "p/q" text, the classes whose pools count as lists of class codes);
//   * one test per term (fixtures/evaluate-terms.json, made by trioforge.export.evaluate_terms): invented profiles and kits on both sides
//     of every knee (100, 200 and 201, 255, 510), the softcap with and without a shield, the Monk bins below, at and above a bin edge,
//     Iksar, mixed WIS/INT mana and END, each with the breakdown that Python gave;
//   * the constants it carries are the constants of the bundle, and a profile, a kit or an option that is not what the evaluator reads
//     is an EvaluateError.

const BUNDLE_PATH = "profiles/pal-mnk-ber-l50.bundle.json";
const BUNDLE = readBundle(SAMPLE.read(BUNDLE_PATH));
const TERMS = JSON.parse(readFileSync(new URL("../fixtures/evaluate-terms.json", import.meta.url), "utf8"));
const clone = (value) => JSON.parse(JSON.stringify(value));
const PLACES = SLOT_INSTANCES.length;

/** A copy that nothing can change, all through (an input that the evaluator cannot write to without a TypeError). */
function deepFreeze(value) {
  const stack = [value];
  while (stack.length > 0) {
    const node = stack.pop();
    if (node === null || typeof node !== "object" || Object.isFrozen(node)) continue;
    Object.freeze(node);
    for (const child of Array.isArray(node) ? node : Object.values(node)) stack.push(child);
  }
  return value;
}
const frozen = (value) => deepFreeze(clone(value));

/** Where two parsed JSON values first differ (a path and the two values), or null. Key order does not count. */
function firstDifference(got, want, path = "breakdown") {
  if (got === want) return null;
  if (typeof got !== typeof want || got === null || want === null || typeof got !== "object") {
    return `${path}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`;
  }
  if (Array.isArray(got) !== Array.isArray(want)) return `${path}: an array against something that is not`;
  if (Array.isArray(got) && got.length !== want.length) return `${path}: ${got.length} entries, want ${want.length}`;
  for (const key of Object.keys(want)) {
    if (!(key in got)) return `${path}.${key}: missing`;
  }
  for (const key of Object.keys(got)) {
    if (!(key in want)) return `${path}.${key}: should not be there`;
  }
  for (const key of Object.keys(want)) {
    const found = firstDifference(got[key], want[key], `${path}.${key}`);
    if (found !== null) return found;
  }
  return null;
}

/** What an evaluation gives, as the fixtures write it ("p/q" texts). */
const written = (result) => JSON.parse(JSON.stringify(result.breakdown));
/** The numerator of a "p/q" text of a whole number. */
const whole = (text) => Number(text.split("/")[0]);

// ---- the parity fixtures -----------------------------------------------------------------------------------------------------------

function parityTests(set) {
  const listing = set.read("evaluate/profiles.json");
  const records = new Map(listing.records.map((record) => [record.key ?? `w${record.id}`, record]));
  const rows = listing.profiles.map((row) => ({
    id: row.id,
    level: row.level,
    profile: frozen(row.profile),
    buffset: row.buffset === null ? undefined : frozen(row.buffset),
  }));
  const bins = new Map(Object.entries(listing.monk_bins).map(([level, block]) => [Number(level), frozen(block)]));
  const items = new Map();
  const itemAt = (key, tier) => {
    const ident = `${key}@${tier}`;
    if (!items.has(ident)) items.set(ident, atTier(records.get(key), tier, BUNDLE, { weaponPct: listing.weapon_pct }));
    return items.get(ident);
  };
  const chunks = set.paths("evaluate-kits");

  /** The evaluation of a stored kit, as the port makes it. */
  function valued(evaluation) {
    const row = rows[evaluation.profile];
    const kit = evaluation.kit.map((entry) => (entry === null ? null : itemAt(entry[0], entry[1])));
    const options = { setup: evaluation.setup, hasteAssumed: evaluation.haste, buffset: row.buffset };
    if (row.profile.monk !== null) options.monkBins = bins.get(row.level);
    return evaluate(row.profile, kit, evaluation.buffs, options);
  }

  it("has the evaluations, and the Monk bins of every level that has a Monk profile", () => {
    expect(chunks.length).toBeGreaterThan(0);
    const monkLevels = [...new Set(listing.profiles.filter((row) => row.profile.monk !== null).map((row) => row.level))].sort((a, b) => a - b);
    expect(monkLevels.length).toBeGreaterThan(0);
    expect([...bins.keys()]).toEqual(monkLevels);
  });

  for (const path of chunks) {
    it(`${path}: every kit is worth what Python said, field by field and exactly`, () => {
      const chunk = set.read(path);
      const wrong = [];
      for (const [number, evaluation] of chunk.evaluations.entries()) {
        const result = valued(evaluation);
        const difference = firstDifference(written(result), evaluation.breakdown);
        if (difference !== null) wrong.push(`evaluation ${number} of ${rows[evaluation.profile].id}: ${difference}`);
        else if (result.F.toString() !== evaluation.breakdown.F || result.breakdown.F !== result.F) wrong.push(`evaluation ${number}: F`);
        if (wrong.length >= 3) break;
      }
      expect(wrong).toEqual([]);
    }, 60_000);
  }

  it("holds Monk kits of every level, with a bonus above, at and below zero", () => {
    const seen = { levels: new Set(), negative: 0, positive: 0, zero: 0 };
    for (const path of chunks) {
      for (const evaluation of set.read(path).evaluations) {
        const row = rows[evaluation.profile];
        if (row.profile.monk === null) continue;
        seen.levels.add(row.level);
        const bonus = whole(evaluation.breakdown.totals.sheet.monk_bonus);
        seen[bonus < 0 ? "negative" : bonus > 0 ? "positive" : "zero"] += 1;
      }
    }
    expect([...seen.levels].sort()).toEqual([...bins.keys()]);
    expect(seen.positive).toBeGreaterThan(0);
    expect(seen.negative).toBeGreaterThan(0);
    expect(seen.zero).toBeGreaterThan(0);
  });
}

describe("the committed sample", () => parityTests(SAMPLE));
describeFull("the full set", (full) => {
  parityTests(full);

  it("has 5,000 evaluations", () => {
    const total = full.paths("evaluate-kits").reduce((sum, path) => sum + full.read(path).evaluations.length, 0);
    expect(total).toBe(5000);
  });
});

// ---- every profile that a bundle assembles -----------------------------------------------------------------------------------------------

function assembledTests(set) {
  const listing = SAMPLE.read("evaluate/profiles.json");
  const records = new Map(listing.records.map((record) => [record.key ?? `w${record.id}`, record]));
  const kits = SAMPLE.read(SAMPLE.paths("evaluate-kits")[0])
    .evaluations.slice(0, 4)
    .map((evaluation) => evaluation.kit.map((entry) => (entry === null ? null : atTier(records.get(entry[0]), entry[1], BUNDLE, { weaponPct: listing.weapon_pct }))));

  for (const path of set.paths("profiles")) {
    it(`${path}: evaluates every profile of the list, assembled (frozen) and as the plain profile of the list, alike`, () => {
      const listed = set.read(path);
      const bundle = readBundle(set.read(`profiles/${listed.bundle}`));
      let count = 0;
      for (const entry of listed.profiles) {
        const assembled = assembleProfile(bundle, { race: entry.race, role: entry.role, buffs: entry.buffs, ...entry.options });
        const plain = clone(entry.profile);
        const buffset = Object.freeze(buffsetOf(bundle, entry.buffs)); // (a twin of a buff set reads the table of the haste spells)
        const chosen = bundle.buffs[entry.buffs].set.optional.slice(0, 3);
        for (const [index, kit] of kits.entries()) {
          const options = { setup: entry.profile.setups[index % entry.profile.setups.length], hasteAssumed: 25, monkBins: bundle.monk_bins ?? undefined, buffset };
          for (const buffs of [null, chosen]) {
            const a = evaluate(assembled, kit, buffs, options);
            const b = evaluate(plain, kit, buffs, options);
            if (JSON.stringify(a.breakdown) !== JSON.stringify(b.breakdown)) expect(written(a), `${entry.race} ${entry.role} ${entry.buffs}`).toEqual(written(b));
            count += 1;
          }
        }
      }
      expect(count).toBe(listed.profiles.length * kits.length * 2);
      expect(listed.profiles.length).toBeGreaterThan(100);
    }, 60_000);
  }
}

describe("every profile that a bundle assembles, from the sample", () => assembledTests(SAMPLE));
describeFull("every profile that a bundle assembles, from the full set", (full) => assembledTests(full));

// ---- one test per term ---------------------------------------------------------------------------------------------------------------

const termProfiles = TERMS.profiles.map(frozen);

/** The evaluation of a stored term case; `change` replaces its profile, its kit or some of its options. */
function termValue(stored, change = {}) {
  const kit = new Array(PLACES).fill(null);
  for (const [index, item] of stored.kit) kit[index] = frozen(item);
  const options = {
    setup: stored.setup,
    hasteAssumed: stored.haste,
    monkBins: BUNDLE.monk_bins,
    buffset: stored.buffset === null ? undefined : frozen(stored.buffset),
    ...change.options,
  };
  return evaluate(change.profile ?? termProfiles[stored.profile], change.kit ?? kit, stored.buffs, options);
}

/** Every case with the tag is worth what Python said; the cases, for the checks of the test. */
function exactly(tag) {
  const cases = TERMS.cases.filter((stored) => stored.tags.includes(tag));
  expect(cases.length, `cases with the tag ${tag}`).toBeGreaterThan(0);
  for (const stored of cases) {
    const result = termValue(stored);
    expect(firstDifference(written(result), stored.breakdown), stored.id).toBeNull();
    expect(result.F.toString(), stored.id).toBe(stored.breakdown.F);
  }
  return cases;
}

const totalsOf = (cases, name) => new Set(cases.map((stored) => stored.breakdown.totals.attributes[name]));
const texts = (...numbers) => numbers.map((n) => `${n}/1`);
const ATTRIBUTES = ["STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA"];
const AROUND = [99, 100, 101, 199, 200, 201, 202, 254, 255, 256, 509, 510, 511];

describe("one test per term", () => {
  it("has the cases of the file, made for these rules and this Monk curve", () => {
    expect(TERMS.kind).toBe("evaluate-terms");
    expect(TERMS.rules_version).toBe(SAMPLE.manifest.rules_version);
    expect(TERMS.level).toBe(BUNDLE.level);
    expect(Object.keys(TERMS.terms).length).toBeGreaterThanOrEqual(20);
    for (const tag of Object.keys(TERMS.terms)) {
      expect(TERMS.cases.filter((stored) => stored.tags.includes(tag)).length, tag).toBeGreaterThanOrEqual(2);
    }
    const monk = TERMS.profiles.find((profile) => profile.monk !== null).monk;
    expect(BUNDLE.monk_bins.curve.softcap_stones).toBe(`${monk.softcap_stones}/1`);
    expect(BUNDLE.monk_bins.curve.hardcap_stones).toBe(`${monk.hardcap_stones}/1`);
    expect(BUNDLE.monk_bins.curve.full_bonus_ac).toBe(`${monk.full_bonus_ac}/1`);
  });

  it("every attribute alike, on both sides of every knee (99 to 511), and at 0 and below", () => {
    const cases = exactly("attributes-alike");
    for (const total of [...AROUND, 0, -7]) expect(totalsOf(cases, "STA").has(`${total}/1`), `${total}`).toBe(true);
  });

  it("every attribute rotated, so that each of the seven stands at each knee while the others do not", () => {
    const cases = exactly("attributes-rotated");
    for (const name of ATTRIBUTES) {
      for (const total of AROUND) expect(totalsOf(cases, name).has(`${total}/1`), `${name} ${total}`).toBe(true);
    }
  });

  it("knee 100: the first band of WIS and INT, and of the END average", () => {
    const cases = exactly("knee-100");
    for (const total of texts(99, 100, 101)) expect(totalsOf(cases, "WIS").has(total), total).toBe(true);
    for (const stored of cases.filter((c) => c.tags.includes("attributes-alike"))) {
      expect(stored.breakdown.totals.end_average).toBe(stored.breakdown.totals.attributes.WIS);
    }
  });

  it("knee 200: the second band of WIS and INT", () => {
    const cases = exactly("knee-200");
    for (const total of texts(199, 200, 201)) expect(totalsOf(cases, "INT").has(total), total).toBe(true);
  });

  it("knee 201: the second band of the END average, 352.5 at 201", () => {
    const cases = exactly("knee-201");
    for (const total of texts(200, 201, 202)) expect(totalsOf(cases, "STR").has(total), total).toBe(true);
  });

  it("knee 255: the one knee of the client (STA for HP); DEX, WIS and INT do not bend there (T5: DEX counts in full to 510)", () => {
    const cases = exactly("knee-255");
    for (const total of texts(254, 255, 256)) {
      for (const name of ["STA", "DEX", "WIS", "INT"]) expect(totalsOf(cases, name).has(total), `${name} ${total}`).toBe(true);
    }
  });

  it("two WIS pools: the mana curve runs at one slope from 200 to 510, 10 more WIS at 270 is 12.5 converted points in each pool", () => {
    const cases = exactly("mana-wis-curve");
    const pools = new Map(cases.map((stored) => [stored.breakdown.totals.attributes.WIS, Rational.parse(stored.breakdown.totals.pools.MANA)]));
    // 2 pools x factor 4.5 x 12.5 converted points; the game's window floors each pool (437 and 450), which Python's stat_window pins at 118
    expect(pools.get("280/1").sub(pools.get("270/1")).toString()).toBe("225/2");
    expect(pools.get("255/1").sub(pools.get("200/1")).toString()).toBe("2475/4");
    expect(pools.get("510/1").sub(pools.get("255/1")).toString()).toBe("11475/4");
  });

  it("Natural Durability: the percent of the rank is in the factor of the HP pools, STA past the knee and the cap, and the flat HP is not scaled", () => {
    const cases = exactly("natural-durability");
    const ranks = BUNDLE.constants.aa.natural_durability_pct; // rank -> "p/1", from rules.json hp.natural_durability_pct
    expect(Object.keys(ranks)).toEqual(["1", "2", "3", "4"]);
    expect(Object.values(ranks)).toEqual(texts(2, 5, 10, 12));
    const percents = new Set(cases.map((stored) => termProfiles[stored.profile].nd_pct));
    expect([...percents].sort((a, b) => a - b)).toEqual([0, 2, 5, 10, 12]);
    const rankOf = (profile) => String(profile.aa.natural_durability);
    for (const stored of cases) {
      const profile = termProfiles[stored.profile];
      expect(profile.nd_pct, stored.id).toBe(profile.aa.natural_durability === 0 ? 0 : Number(ranks[rankOf(profile)].split("/")[0]));
    }
    // the pools of rank 4 are the pools of rank 0 with the factor of each HP pool times 112/100 (the base and the constant 5 are not scaled)
    const melee = (rank) => TERMS.profiles.find((profile) => profile.aa.natural_durability === rank && profile.trio.join() === "WAR,ROG,BER" && profile.pools.HP.length === 3);
    const [plain, scaled] = [melee(0), melee(4)];
    plain.pools.HP.forEach((pool, index) => {
      expect(scaled.pools.HP[index].base).toBe(pool.base);
      expect(Rational.fromNumber(scaled.pools.HP[index].fac).equals(Rational.fromNumber(pool.fac).mul(new Rational(112n, 100n)))).toBe(true);
    });
    expect(scaled.pools.MANA).toEqual(plain.pools.MANA);
    expect(scaled.pools.END).toEqual(plain.pools.END);
    // the flat HP of an item is not scaled: the case's kit with and without its flat-HP item differs by exactly that HP, at every rank
    for (const stored of cases.filter((c) => c.kit.length === 2)) {
      const flat = stored.kit.find(([, item]) => item.key === "itnd-hp")[1].stats.HP;
      const bare = stored.kit.filter(([, item]) => item.key !== "itnd-hp");
      const kit = new Array(PLACES).fill(null);
      for (const [index, item] of bare) kit[index] = frozen(item);
      const without = termValue(stored, { kit });
      const withFlat = termValue(stored);
      expect(withFlat.breakdown.totals.pools.HP.sub(without.breakdown.totals.pools.HP).equals(new Rational(BigInt(flat))), stored.id).toBe(true);
    }
  });

  it("knee 510: the cap of every stat, and of each stat in the END average", () => {
    const cases = exactly("knee-510");
    for (const total of texts(509, 510, 511)) {
      for (const name of ATTRIBUTES) expect(totalsOf(cases, name).has(total), `${name} ${total}`).toBe(true);
    }
  });

  it("END: the average of STR, STA, DEX and AGI, each counted to 510, beside 100 and 201, between whole numbers, below 0", () => {
    const cases = exactly("end");
    const averages = new Set(cases.map((stored) => stored.breakdown.totals.end_average));
    for (const average of ["99/1", "100/1", "101/1", "200/1", "201/1", "202/1", "401/4", "803/4", "805/4", "405/2", "510/1"]) {
      expect(averages.has(average), average).toBe(true);
    }
    expect([...averages].some((text) => whole(text) < 100)).toBe(true);
  });

  it("mixed WIS/INT mana: which two pools count changes with the stats, and a tie keeps the trio's order", () => {
    const cases = exactly("mixed-mana");
    const counted = new Set(cases.map((stored) => stored.breakdown.totals.counted.MANA.join(" ")));
    expect(counted.has("CLR SHD")).toBe(true);
    expect(counted.has("SHD ENC")).toBe(true);
  });

  it("a trio with no mana class has no mana, whatever its items give", () => {
    const cases = exactly("mana-none");
    for (const stored of cases) expect(stored.breakdown.totals.pools.MANA).toBe("0/1");
  });

  it("a profile with no bands of its own reads the rule's, and one with bands of its own reads those", () => {
    const own = exactly("bands-custom");
    const rule = exactly("bands-default");
    expect(termProfiles[own[0].profile].bands.breaks).toHaveLength(3);
    expect(termProfiles[own[0].profile].bands.slopes).toHaveLength(4);
    expect(termProfiles[rule[0].profile].bands).toBeNull();
  });

  it("HP and END pools that cross and tie: the two largest count, a tie in the order of the trio", () => {
    const cases = exactly("pool-order");
    expect(new Set(cases.map((stored) => stored.breakdown.totals.counted.HP.join(" "))).size).toBeGreaterThanOrEqual(3);
    expect(new Set(cases.map((stored) => stored.breakdown.totals.counted.END.join(" "))).size).toBeGreaterThanOrEqual(2);
  });

  it("the softcap with no shield: below, at and above it, for each rate past it", () => {
    const cases = exactly("softcap");
    const sides = cases.map((stored) => {
      const [xp, xq] = stored.breakdown.totals.sheet.X.split("/").map(BigInt);
      const [yp, yq] = stored.breakdown.totals.sheet.Y.split("/").map(BigInt);
      const difference = xp * yq - yp * xq;
      return difference < 0n ? -1 : difference > 0n ? 1 : 0;
    });
    expect([...new Set(sides)].sort()).toEqual([-1, 0, 1]);
    expect(new Set(cases.map((stored) => termProfiles[stored.profile].softcap[1])).size).toBeGreaterThanOrEqual(3);
    for (const stored of cases) expect(stored.breakdown.totals.sheet.shield_ac).toBe("0/1");
  });

  it("the softcap with a shield in the off hand: it adds to X and to the softcap", () => {
    const cases = exactly("softcap-shield");
    for (const stored of cases) expect(stored.breakdown.totals.sheet.shield_ac).not.toBe("0/1");
  });

  it("a shield in an Any place, and a plain item in the off hand, are worn armor class and not the shield", () => {
    const cases = exactly("shield-not-offhand");
    for (const stored of cases) {
      expect(stored.breakdown.totals.sheet.shield_ac).toBe("0/1");
      expect(stored.breakdown.totals.sheet.worn_ac).toBe("378/1");
    }
  });

  it("the Monk bins: below, at and above every bin edge, on top and inside, past the table and under the alternative curve", () => {
    const cases = exactly("monk");
    const table = BUNDLE.monk_bins.bonus;
    for (const stored of cases) {
      if ("full_until_stones" in termProfiles[stored.profile].monk) continue;
      const stones = Math.floor(whole(stored.breakdown.totals.weight10) / 10);
      expect(stored.breakdown.totals.sheet.monk_bonus, stored.id).toBe(table[Math.min(stones, table.length - 1)]);
    }
    const weights = new Set(cases.map((stored) => whole(stored.breakdown.totals.weight10)));
    for (const stone of [17, 18, 34, 35, 36, 37, 38, 136]) {
      for (const tenths of [10 * stone - 1, 10 * stone, 10 * stone + 1]) expect(weights.has(tenths), `${tenths}`).toBe(true);
    }
    expect(Math.max(...weights) / 10).toBeGreaterThan(table.length - 1);
    expect(new Set(cases.map((stored) => termProfiles[stored.profile].placement.monk))).toEqual(new Set(["top", "inside"]));
    expect(cases.some((stored) => "full_until_stones" in termProfiles[stored.profile].monk)).toBe(true);
    const bonuses = cases.map((stored) => whole(stored.breakdown.totals.sheet.monk_bonus));
    expect(Math.max(...bonuses)).toBeGreaterThan(0);
    expect(Math.min(...bonuses)).toBeLessThan(0);
    expect(bonuses).toContain(0);
  });

  it("the bins are read by the whole stones of the worn weight, and the last bin for a weight at the end of the table and past it", () => {
    const bins = clone(BUNDLE.monk_bins);
    const last = bins.bonus.length - 1;
    bins.bonus[last] = "-99/1"; // a bin of its own, which the one before it is not
    const cases = TERMS.cases.filter((stored) => stored.tags.includes("monk") && termProfiles[stored.profile].placement.monk === "top");
    const seen = new Set();
    for (const stored of cases) {
      if ("full_until_stones" in termProfiles[stored.profile].monk) continue;
      const stones = Math.floor(whole(stored.breakdown.totals.weight10) / 10);
      const got = termValue(stored, { options: { monkBins: frozen(bins) } }).breakdown.totals.sheet.monk_bonus.toString();
      expect(got, stored.id).toBe(stones >= last ? "-99/1" : BUNDLE.monk_bins.bonus[stones]);
      seen.add(stones >= last ? "end" : stones === last - 1 ? "before" : "inside");
    }
    expect([...seen].sort()).toEqual(["before", "end", "inside"]);
  });

  it("Iksar: the racial armor class on top of the cap and inside X, with and without a Monk", () => {
    const cases = exactly("iksar");
    expect(new Set(cases.map((stored) => termProfiles[stored.profile].placement.iksar))).toEqual(new Set(["top", "inside"]));
    expect(new Set(cases.map((stored) => termProfiles[stored.profile].monk === null))).toEqual(new Set([true, false]));
    for (const stored of cases) expect(stored.breakdown.totals.sheet.iksar).toBe(`${termProfiles[stored.profile].iksar_ac}/1`);
    expect(new Set(cases.map((stored) => stored.breakdown.parts.IKSAR === "0/1"))).toEqual(new Set([true, false]));
  });

  it("haste: spell haste against the cap, the best worn haste in the room that is left", () => {
    const cases = exactly("haste");
    const trimmed = cases.map((stored) => stored.breakdown.totals.haste.worn_counted !== stored.breakdown.totals.haste.worn_best);
    expect(new Set(trimmed)).toEqual(new Set([true, false]));
  });

  it("regen counts gear up to its cap and buff regen outside it, and resists count gear and buffs up to theirs", () => {
    exactly("regen");
    exactly("resists");
  });

  it("weapon damage: every setup against the hands that fill it, a listed bonus or none, three assumed hastes", () => {
    const cases = exactly("weapons");
    expect(new Set(cases.map((stored) => stored.setup))).toEqual(new Set([null, "1h-shield", "2h", "dw", "stick", "ranged"]));
    expect(cases.some((stored) => stored.breakdown.parts.WEAPON !== "0/1")).toBe(true);
    expect(cases.some((stored) => stored.breakdown.parts.WEAPON === "0/1")).toBe(true);
    expect(new Set(cases.map((stored) => stored.haste))).toEqual(new Set([0, 12.5, 25, 100]));
  });

  it("buffs chosen among the optional ones: none, one, the best haste of several, a duplicate, an id that is always on", () => {
    const cases = exactly("buffs");
    expect(cases.some((stored) => stored.buffs === null)).toBe(true);
    expect(cases.some((stored) => Array.isArray(stored.buffs) && stored.buffs.length === 0)).toBe(true);
    expect(new Set(cases.map((stored) => stored.breakdown.totals.haste.spell)).size).toBeGreaterThanOrEqual(3);
  });

  it("profile numbers that are not whole, and a pool number that only p/q can write", () => {
    const cases = exactly("decimals");
    expect(JSON.stringify(termProfiles[cases[0].profile].pools)).toContain('"1/3"');
    expect(termProfiles[cases[0].profile].naked.STR).toBe(90.5);
  });

  it("the largest numbers held exactly: 22 items at 2^40 in every stat, weights up to 2^53 - 1, a weight in exponent notation", () => {
    const cases = exactly("limits");
    const weights = cases.map((stored) => BigInt(stored.breakdown.totals.weight10.split("/")[0]));
    expect(weights).toContain(22n * 2n ** 40n);
    expect(weights).toContain(-22n * 2n ** 40n);
    const hp = cases.map((stored) => BigInt(stored.breakdown.parts.HP.split("/")[0]));
    expect(hp.some((part) => part > 2n ** 90n || part < -(2n ** 90n))).toBe(true); // far past what a double holds
    expect(TERMS.profiles.some((profile) => profile.weights.HP === 1.5e-8)).toBe(true);
  });

  it("an empty kit, and a kit under a profile with no weights", () => {
    const cases = exactly("empty");
    expect(cases.some((stored) => stored.kit.length === 0)).toBe(true);
    expect(cases.some((stored) => stored.breakdown.F === "0/1" && stored.kit.length > 0)).toBe(true);
  });

  it("reads the same whether the inputs are frozen or not, and whatever the order of the cases", () => {
    const order = TERMS.cases.map((_, index) => index).sort((a, b) => ((a * 7919) % 257) - ((b * 7919) % 257));
    for (const index of order) {
      const stored = TERMS.cases[index];
      const kit = new Array(PLACES).fill(null);
      for (const [place, item] of stored.kit) kit[place] = clone(item);
      const loose = termValue(stored, { profile: clone(TERMS.profiles[stored.profile]), kit });
      expect(firstDifference(written(loose), stored.breakdown), stored.id).toBeNull();
    }
  });

  it("reads a profile that is changed between two calls anew, and the frozen one it was made from once", () => {
    const stored = TERMS.cases.find((c) => c.id === "attributes-alike-004");
    const profile = clone(TERMS.profiles[stored.profile]);
    const before = termValue(stored, { profile });
    profile.weights.HP *= 2;
    const after = termValue(stored, { profile });
    expect(after.breakdown.parts.HP.equals(before.breakdown.parts.HP.mul(2))).toBe(true);
    expect(termValue(stored).breakdown.parts.HP.equals(before.breakdown.parts.HP)).toBe(true);
  });
});

// ---- what comes back -----------------------------------------------------------------------------------------------------------------

describe("the result", () => {
  const stored = TERMS.cases.find((c) => c.id === "attributes-alike-004");
  let made;
  const result = () => (made ??= termValue(stored));

  it("is {F, breakdown} with F a Rational, the F of the breakdown, and the fields of Python's Breakdown", () => {
    const { F, breakdown } = result();
    expect(Object.keys(result())).toEqual(["F", "breakdown"]);
    expect(F).toBeInstanceOf(Rational);
    expect(breakdown.F).toBe(F);
    expect(Object.keys(breakdown)).toEqual(["F", "parts", "totals"]);
    expect(Object.keys(breakdown.parts)).toEqual([...PART_NAMES]);
    expect(Object.keys(breakdown.totals)).toEqual(["attributes", "pools", "counted", "end_average", "sheet", "haste", "regen", "resists", "weight10", "atk"]);
    expect(Object.keys(breakdown.totals.attributes)).toEqual(ATTRIBUTES);
    expect(Object.keys(breakdown.totals.pools)).toEqual(["HP", "MANA", "END"]);
    expect(Object.keys(breakdown.totals.counted)).toEqual(["HP", "MANA", "END"]);
    expect(Object.keys(breakdown.totals.sheet)).toEqual(["worn_ac", "shield_ac", "X", "Y", "capped", "monk_bonus", "iksar", "total"]);
    expect(Object.keys(breakdown.totals.haste)).toEqual(["spell", "worn_best", "worn_counted", "counted"]);
    expect(Object.keys(breakdown.totals.regen)).toEqual(["HPREG", "MANAREG", "ENDREG"]);
    expect(Object.keys(breakdown.totals.resists)).toEqual(["FIRE", "COLD", "MAGIC", "POISON", "DISEASE"]);
    expect(Object.keys(breakdown.totals.regen.HPREG)).toEqual(["gear", "buff", "counted"]);
  });

  it("holds Rationals for every number, lists of class codes for the pools that count, and is the sum of its parts", () => {
    let sum = new Rational(0n);
    for (const part of Object.values(result().breakdown.parts)) {
      expect(part).toBeInstanceOf(Rational);
      sum = sum.add(part);
    }
    expect(sum.equals(result().F)).toBe(true);
    const { totals } = result().breakdown;
    expect(totals.counted.HP.every((code) => /^[A-Z]{3}$/.test(code))).toBe(true);
    expect(totals.pools.HP).toBeInstanceOf(Rational);
    expect(totals.weight10).toBeInstanceOf(Rational);
    expect(totals.sheet.monk_bonus).toBeInstanceOf(Rational);
  });

  it("is frozen all through, so that a caller cannot change what another reads", () => {
    const { breakdown } = result();
    const nodes = [result(), breakdown, breakdown.parts, breakdown.totals, breakdown.totals.attributes, breakdown.totals.pools, breakdown.totals.counted];
    nodes.push(breakdown.totals.counted.HP, breakdown.totals.sheet, breakdown.totals.haste, breakdown.totals.regen, breakdown.totals.regen.HPREG, breakdown.totals.resists.FIRE);
    for (const node of nodes) expect(Object.isFrozen(node)).toBe(true);
  });

  it("gives F as a double for display only: the nearest one, from the exact value", () => {
    const { F } = result();
    expect(typeof F.toNumber()).toBe("number");
    expect(F.toNumber()).toBe(new Rational(F.numerator, F.denominator).toNumber());
    expect(Math.abs(F.toNumber() - Number(F.numerator) / Number(F.denominator))).toBeLessThan(1e-9 * Math.abs(F.toNumber()));
  });

  it("gives the same answer twice, and changes nothing it was given (the inputs are frozen: a write would throw)", () => {
    const again = termValue(stored);
    expect(written(again)).toEqual(written(result()));
    expect(again.F.equals(result().F)).toBe(true);
  });
});

// ---- the constants -------------------------------------------------------------------------------------------------------------------

const CAMEL = (name) => name.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());

function constantsTests(bundles) {
  const NAMES = [
    "attributes", "schools", "setups", "handPlaces", "placements", "breakdownParts", "weightKeys", "buffTotalKeys", "itemStats", "buffComponents",
    "slotGroups", "statKnee", "statCap", "hpPoolConstant", "poolsCounted", "staCurve", "manaBands", "endCurve", "strToAtk", "agiToAc", "dexPastKnee",
    "sheet", "weaponIndex",
  ];

  it("carries the constants of the formulas module, each the one the bundle exports", () => {
    expect(Object.keys(CONSTANTS).sort()).toEqual([...NAMES].sort());
    for (const [label, bundle] of bundles) {
      const exported = new Map(Object.entries(bundle.constants).map(([name, value]) => [CAMEL(name), value]));
      for (const name of NAMES) {
        expect(exported.has(name), `${label}: ${name}`).toBe(true);
        let want = exported.get(name);
        if (name === "weaponIndex") want = { bonusFromLevel: want.bonus_from_level, bonusOneHanded: want.bonus_one_handed, bonusTwoHanded: want.bonus_two_handed, bonusDelayCap: want.bonus_delay_cap, bonusDelayDiv: want.bonus_delay_div, bonusLevelDiv: want.bonus_level_div };
        if (name === "sheet") want = { itemMult: want.item_mult, defenseDiv: want.defense_div, spellAcDiv: want.spell_ac_div, agiDiv: want.agi_div };
        expect(JSON.stringify(CONSTANTS[name]), `${label}: ${name}`).toBe(JSON.stringify(want));
      }
    }
  });

  it("has the 22 places of a kit and the 14 parts of the breakdown, in the order of the model", () => {
    expect(SLOT_INSTANCES).toHaveLength(22);
    for (const [label, bundle] of bundles) {
      expect(SLOT_INSTANCES, label).toEqual(bundle.constants.slot_groups.flatMap(([name, count]) => new Array(whole(count)).fill(name)));
      expect([...PART_NAMES], label).toEqual(bundle.constants.breakdown_parts);
    }
  });
}

describe("the constants, against the bundle of the sample", () => constantsTests([["the sample bundle", BUNDLE]]));
describeFull("the constants, against every bundle of the full set", (full) => {
  constantsTests(full.paths("bundle").map((path) => [path, readBundle(full.read(path))]));
});

// ---- what the MILP builder reads from the evaluator ---------------------------------------------------------------------------------------

describe("what the builder reads", () => {
  const listing = SAMPLE.read("evaluate/profiles.json");
  const row = listing.profiles.find((candidate) => candidate.profile.monk !== null && candidate.level === 50);
  const bins = frozen(listing.monk_bins["50"]);
  const profile = frozen(row.profile);

  it("has the units that the formulas count in: a percent and the tenths of a stone of the weights", () => {
    expect(UNITS.percent.toString()).toBe("100/1");
    expect(UNITS.tenthsPerStone.toString()).toBe("10/1");
    expect(Object.isFrozen(UNITS)).toBe(true);
    expect(Object.keys(UNITS).sort()).toEqual(["percent", "tenthsPerStone"]);
  });

  it("reads a profile that is frozen all through once, and any other at each call", () => {
    const compiled = profileOf(profile);
    expect(profileOf(profile)).toBe(compiled);
    expect(Object.isFrozen(compiled)).toBe(true);
    const loose = clone(row.profile);
    expect(profileOf(loose)).not.toBe(profileOf(loose));
    expect(profileOf(loose).level).toBe(compiled.level);
    expect(() => profileOf({ ...clone(row.profile), pools: null })).toThrow(EvaluateError);
  });

  it("gives a compiled profile that nothing can change, all through, since the one remembered for a profile is shared by every reader of it", () => {
    const compiled = profileOf(profile);
    const seen = new Set();
    const stack = [["profile", compiled]];
    while (stack.length > 0) {
      const [path, node] = stack.pop();
      if (node === null || typeof node !== "object" || seen.has(node)) continue;
      seen.add(node);
      expect(Object.isFrozen(node), path).toBe(true);
      for (const key of Reflect.ownKeys(node)) stack.push([`${path}.${String(key)}`, node[key]]);
    }
    expect(seen.size).toBeGreaterThan(40); // the lists, the pools and their entries, the curves, the weights ... and the exact numbers in them
    const lists = { naked: compiled.naked, buff: compiled.buff, regenCaps: compiled.regenCaps, "weights.regen": compiled.weights.regen, "weights.schools": compiled.weights.schools };
    for (const [name, list] of Object.entries(lists)) {
      expect(list.length, name).toBeGreaterThan(1);
      expect(() => { list[1] = list[0]; }, name).toThrow(TypeError);
      expect(() => list.push(list[0]), name).toThrow(TypeError);
      expect(() => { list.length = 0; }, name).toThrow(TypeError);
    }
    // and a reader that tries to change what it was handed leaves the next reader's profile as it was
    const HEAD = SLOT_INSTANCES.indexOf("HEAD");
    const kit = new Array(PLACES).fill(null);
    kit[HEAD] = { key: "stone", stats: { STR: 10 }, sv: {}, haste: 0, weight10: 10, weapon: null, is_shield: false };
    const before = evaluate(profile, kit, null, { monkBins: bins }).F.toString();
    expect(() => { profileOf(profile).naked[0] = profileOf(profile).naked[1].add(profileOf(profile).naked[1]); }).toThrow(TypeError);
    expect(evaluate(profile, kit, null, { monkBins: bins }).F.toString()).toBe(before);
  });

  it("gives the Monk bonus of each whole stone of worn weight, which is what evaluate reads for a kit", () => {
    const table = monkTable(profileOf(profile), bins);
    expect(table).toHaveLength(Number(bins.curve.hardcap_stones.split("/")[0]) + MONK_STONES_PAST_HARDCAP + 1);
    expect(table[0]).toBe(whole(bins.curve.full_bonus_ac)); // a light kit has the full bonus
    expect(table.every((bonus) => Number.isSafeInteger(bonus))).toBe(true);
    expect(table[table.length - 1]).toBeLessThan(0); // and a heavy one a penalty, which stops growing
    expect(Object.isFrozen(table)).toBe(true);
    const HEAD = SLOT_INSTANCES.indexOf("HEAD");
    for (const weight10 of [0, 9, 10, 99, 100, 169, 170, 171, 359, 360, 361, 1000, 1369, 1370, 100_000]) {
      const kit = new Array(PLACES).fill(null);
      kit[HEAD] = { key: "stone", stats: {}, sv: {}, haste: 0, weight10, weapon: null, is_shield: false };
      const bonus = evaluate(profile, kit, null, { monkBins: bins }).breakdown.totals.sheet.monk_bonus;
      expect(bonus.toString(), `weight ${weight10}`).toBe(`${table[Math.min(Math.floor(weight10 / 10), table.length - 1)]}/1`);
    }
  });

  it("reads the bins of the alternative reading for a curve that has it, and names the option that it is missing", () => {
    const alternative = { ...clone(row.profile), monk: { ...clone(row.profile).monk, full_until_stones: 34 } };
    const plain = monkTable(profileOf(profile), bins);
    const until = monkTable(profileOf(frozen(alternative)), bins);
    expect(until).not.toEqual(plain);
    expect(until[34]).toBe(plain[0]); // the full bonus up to 34 whole stones
    expect(() => monkTable(profileOf(profile), undefined)).toThrow(/options\.monkBins/);
    expect(() => monkTable(profileOf(profile), null, "options.monk_bins")).toThrow(/options\.monk_bins/);
    expect(() => monkTable(profileOf(profile), { ...clone(bins), curve: { ...clone(bins).curve, hardcap_stones: "30/1" } }, "options.monk_bins")).toThrow(EvaluateError);
  });
});

// ---- input that is not what the evaluator reads --------------------------------------------------------------------------------------

describe("malformed input", () => {
  const monkCase = TERMS.cases.find((c) => c.tags.includes("monk") && termProfiles[c.profile].placement.monk === "top" && c.kit.length > 0);
  const buffsCase = TERMS.cases.find((c) => c.tags.includes("buffs") && Array.isArray(c.buffs) && c.buffs.length > 0);
  const CHEST = SLOT_INSTANCES.indexOf("CHEST");

  /**
   * An evaluation of a stored case with something changed, to be called: the hooks change the copies of the profile, of the kit (a list of
   * 22 places) and of the options in place; the `Value` forms replace the whole of one (a value, or a function of the copy).
   */
  function broken({ profile, kit, options, buffs, profileValue, kitValue, optionsValue, source = monkCase }) {
    const copy = clone(TERMS.profiles[source.profile]);
    profile?.(copy);
    const items = new Array(PLACES).fill(null);
    for (const [place, item] of source.kit) items[place] = clone(item);
    kit?.(items);
    const given = { setup: source.setup, hasteAssumed: source.haste, monkBins: BUNDLE.monk_bins, buffset: source.buffset === null ? undefined : clone(source.buffset) };
    options?.(given);
    const pick = (value, copied) => (value === undefined ? copied : typeof value === "function" ? value(copied) : value);
    return () => evaluate(pick(profileValue, copy), pick(kitValue, items), buffs === undefined ? source.buffs : buffs, pick(optionsValue, given));
  }

  /** Calls a function that must throw an EvaluateError, and checks its message. */
  function refuses(call, pattern) {
    let error;
    try {
      call();
    } catch (caught) {
      error = caught;
    }
    expect(error, "an error").toBeInstanceOf(EvaluateError);
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("EvaluateError");
    if (pattern !== undefined) expect(error.message).toMatch(pattern);
  }

  it("works on the cases that are changed below, unchanged", () => {
    expect(() => broken({})()).not.toThrow();
    expect(() => broken({ source: buffsCase })()).not.toThrow();
  });

  describe("the profile", () => {
    const FIELDS = [
      "level", "naked", "weights", "pools", "buff_totals", "haste_cap", "softcap", "cs_pct", "pe_pct", "defense_cap", "monk", "iksar_ac", "placement",
      "caps", "bands", "dw_factor",
    ];
    for (const field of FIELDS) {
      it(`refuses a profile with no ${field}`, () => {
        refuses(broken({ profile: (p) => { delete p[field]; } }), new RegExp(field));
      });
    }
    for (const [name, value] of [["null", null], ["a number", 5], ["a text", "profile"], ["a list", []], ["undefined", undefined]]) {
      it(`refuses ${name} for a profile`, () => refuses(broken({ profileValue: () => value }), /profile/));
    }
    for (const [name, change, pattern] of [
      ["a level of 0", (p) => { p.level = 0; }, /level/],
      ["a level that is not whole", (p) => { p.level = 50.5; }, /level/],
      ["a level as text", (p) => { p.level = "50"; }, /level/],
      ["a stat of the race as text", (p) => { p.naked.STR = "90"; }, /naked/],
      ["a stat of the race that is not finite", (p) => { p.naked.WIS = Number.NaN; }, /naked/],
      ["no WIS in the race", (p) => { delete p.naked.WIS; }, /WIS/],
      ["a weight the evaluator does not read", (p) => { p.weights.FOO = 1; }, /FOO/],
      ["a negative weight", (p) => { p.weights.HP = -1; }, /HP/],
      ["a weight as text", (p) => { p.weights.HP = "1"; }, /HP/],
      ["a weight that is a whole number past 2^53 - 1 (a double does not hold it exactly)", (p) => { p.weights.HP = 2 ** 60; }, /weights\.HP/],
      ["a stat of the race past 2^53 - 1", (p) => { p.naked.STR = 2 ** 53; }, /naked\.STR/],
      ["a pool number past 2^53 - 1", (p) => { p.pools.HP[0].base = 1e21; }, /base/],
      ["weights as a list", (p) => { p.weights = []; }, /weights/],
      ["no HP pool", (p) => { p.pools.HP = []; }, /HP/],
      ["no END pool", (p) => { p.pools.END = []; }, /END/],
      ["a mana pool with no stat", (p) => { p.pools.MANA.push({ cls: "XXX", base: 1, fac: 1 }); }, /stat/],
      ["a mana pool of STR", (p) => { p.pools.MANA.push({ cls: "XXX", base: 1, fac: 1, stat: "STR" }); }, /stat/],
      ["a pool number as text that is not p/q", (p) => { p.pools.HP[0].fac = "four"; }, /fac/],
      ["a pool number as a ratio not in lowest terms", (p) => { p.pools.HP[0].base = "2/4"; }, /base/],
      ["a pool with no class", (p) => { delete p.pools.HP[0].cls; }, /cls/],
      ["a buff total the evaluator does not read", (p) => { p.buff_totals.FOO = 1; }, /FOO/],
      ["a buff total as text", (p) => { p.buff_totals.AC = "20"; }, /AC/],
      ["a resist school that does not exist", (p) => { p.buff_totals.SV = { FOO: 1 }; }, /FOO/],
      ["a negative haste cap", (p) => { p.haste_cap = -1; }, /haste_cap/],
      ["a softcap that is not a pair", (p) => { p.softcap = [392]; }, /softcap/],
      ["a rate past the softcap above 1", (p) => { p.softcap = [392, 1.5]; }, /softcap/],
      ["a rate past the softcap below 0", (p) => { p.softcap = [392, -0.1]; }, /softcap/],
      ["a negative percent", (p) => { p.cs_pct = -1; }, /cs_pct/],
      ["a Monk curve with no hardcap", (p) => { delete p.monk.hardcap_stones; }, /hardcap_stones/],
      ["a placement that is neither top nor inside", (p) => { p.placement.monk = "under"; }, /placement/],
      ["a placement with a third key", (p) => { p.placement.extra = "top"; }, /placement/],
      ["caps with no regen cap for END", (p) => { delete p.caps.regen.END; }, /END/],
      ["bands whose breaks do not rise", (p) => { p.bands = { breaks: [100, 100], slopes: [1, 1, 1] }; }, /bands/],
      ["bands with the wrong number of slopes", (p) => { p.bands = { breaks: [100], slopes: [1] }; }, /bands/],
      ["bands with a negative slope", (p) => { p.bands = { breaks: [100], slopes: [1, -1] }; }, /bands/],
      ["a weight named __proto__", (p) => { Object.defineProperty(p.weights, "__proto__", { value: 1, enumerable: true, configurable: true }); }, /__proto__/],
    ]) {
      it(`refuses ${name}`, () => refuses(broken({ profile: change }), pattern));
    }

    it("reads the own properties of a profile, and not what it inherits", () => {
      const inherited = broken({ profileValue: (p) => Object.create(p) });
      refuses(inherited, /profile\./);
    });
    it("reads a Monk curve with no full_bonus_ac as Python does (the level's), and the same bonus", () => {
      const without = broken({ profile: (p) => { delete p.monk.full_bonus_ac; } });
      expect(firstDifference(written(without()), monkCase.breakdown)).toBeNull();
    });
    it("refuses a Monk curve whose full bonus is not the level's", () => {
      refuses(broken({ profile: (p) => { p.monk.full_bonus_ac = 74; } }), /full_bonus_ac/);
    });
  });

  describe("the kit", () => {
    for (const [name, value, pattern] of [
      ["a kit that is not a list", () => "kit", /kit/],
      ["a kit of 21 places", (items) => items.slice(1), /22/],
      ["a kit of 23 places", (items) => [...items, null], /22/],
      ["a place that is undefined", (items) => items.map((item, index) => (index === 0 ? undefined : item)), /kit\[0\]/],
      ["an item that is a text", (items) => items.map((item, index) => (index === CHEST ? "item" : item)), /kit\[/],
      ["an item that is a list", (items) => items.map((item, index) => (index === CHEST ? [] : item)), /kit\[/],
    ]) {
      it(`refuses ${name}`, () => refuses(broken({ kitValue: value }), pattern));
    }
    for (const [name, change, pattern] of [
      ["an item with a stat the evaluator does not know", (item) => { item.stats.FOO = 1; }, /FOO/],
      ["an item with HASTE among its stats (worn haste is the field haste)", (item) => { item.stats.HASTE = 5; }, /HASTE/],
      ["a stat that is not a whole number", (item) => { item.stats.AC = 1.5; }, /AC/],
      ["a stat that is not finite", (item) => { item.stats.AC = Number.POSITIVE_INFINITY; }, /AC/],
      ["a stat as text", (item) => { item.stats.AC = "5"; }, /AC/],
      ["a stat past what 22 items can add exactly", (item) => { item.stats.AC = 2 ** 50; }, /AC/],
      ["a stat one past the limit of 2^40", (item) => { item.stats.AC = 2 ** 40 + 1; }, /AC/],
      ["a stat one below minus the limit of 2^40", (item) => { item.stats.AC = -(2 ** 40) - 1; }, /AC/],
      ["a resist the evaluator does not know", (item) => { item.sv.FOO = 1; }, /FOO/],
      ["a resist as text", (item) => { item.sv.FIRE = "5"; }, /FIRE/],
      ["haste that is not whole", (item) => { item.haste = 1.5; }, /haste/],
      ["a weight as text", (item) => { item.weight10 = "10"; }, /weight10/],
      ["no stats", (item) => { delete item.stats; }, /stats/],
      ["stats as a list", (item) => { item.stats = []; }, /stats/],
      ["no key", (item) => { delete item.key; }, /key/],
      ["a shield flag that is not a boolean", (item) => { item.is_shield = 1; }, /is_shield/],
      ["a weapon that is a text", (item) => { item.weapon = "sword"; }, /weapon/],
      ["a weapon with a damage that is not whole", (item) => { item.weapon = { skill: "1H Slashing", dmg: 1.5, delay: 30, bonus: null, two_handed: false }; }, /dmg/],
      ["a weapon with a bonus as text", (item) => { item.weapon = { skill: "1H Slashing", dmg: 20, delay: 30, bonus: "5", two_handed: false }; }, /bonus/],
      ["a weapon with a two-hander flag that is not a boolean", (item) => { item.weapon = { skill: "1H Slashing", dmg: 20, delay: 30, bonus: null, two_handed: 0 }; }, /two_handed/],
      ["a stat named __proto__", (item) => { item.stats = JSON.parse('{"__proto__": 5}'); }, /__proto__/],
      ["a stat named constructor", (item) => { item.stats = JSON.parse('{"constructor": 5}'); }, /constructor/],
    ]) {
      it(`refuses ${name}`, () => refuses(broken({ kit: (items) => change(items[CHEST]) }), pattern));
    }
  });

  describe("the buffs chosen and the options", () => {
    for (const [name, buffs, pattern] of [
      ["buffs that are not a list", 903, /buffs/],
      ["a buff id that is not whole", [903.5], /buff/],
      ["a buff id as text", ["903"], /buff/],
      ["an id that is not an optional buff of the set", [999], /999/],
    ]) {
      it(`refuses ${name}`, () => refuses(broken({ source: buffsCase, buffs }), pattern));
    }
    it("refuses a choice among buffs with no buff set to choose from", () => {
      refuses(broken({ source: buffsCase, options: (o) => { delete o.buffset; } }), /buffset/);
    });
    it("takes an empty choice with no buff set as the profile's own buffs", () => {
      const noSet = (o) => { delete o.buffset; };
      const own = broken({ source: buffsCase, buffs: null, options: noSet });
      const empty = broken({ source: buffsCase, buffs: [], options: noSet });
      expect(written(empty())).toEqual(written(own()));
    });
    for (const [name, change, pattern] of [
      ["a buff set with no table", (o) => { delete o.buffset.table; }, /table/],
      ["a buff set whose always-on buff has no entry", (o) => { delete o.buffset.table["901"]; }, /901/],
      ["a buff set with an amount as text", (o) => { o.buffset.table["901"].vec.AC = "20"; }, /AC/],
      ["a buff set with a component that does not exist", (o) => { o.buffset.table["901"].vec.FOO = 1; }, /FOO/],
      ["a buff set with ids that are not a list", (o) => { o.buffset.set.always_on = 901; }, /always_on/],
    ]) {
      it(`refuses ${name}`, () => refuses(broken({ source: buffsCase, options: change }), pattern));
    }
    for (const [name, change, pattern] of [
      ["an option the evaluator does not know", (o) => { o.haste = 25; }, /haste/],
      ["a setup that does not exist", (o) => { o.setup = "bow"; }, /setup/],
      ["a haste assumed that is not a number", (o) => { o.hasteAssumed = "25"; }, /hasteAssumed/],
      ["a haste assumed that is not finite", (o) => { o.hasteAssumed = Number.NaN; }, /hasteAssumed/],
    ]) {
      it(`refuses ${name}`, () => refuses(broken({ options: change }), pattern));
    }
    it("refuses options that are a text, and takes none as the defaults", () => {
      refuses(broken({ optionsValue: "options" }), /options/);
      const plain = TERMS.cases.find((c) => termProfiles[c.profile].monk === null && c.setup === null && c.haste === 0 && c.buffs === null);
      const kit = new Array(PLACES).fill(null);
      for (const [place, item] of plain.kit) kit[place] = frozen(item);
      expect(firstDifference(written(evaluate(termProfiles[plain.profile], kit, null)), plain.breakdown)).toBeNull();
    });
    it("takes no setup and no assumed haste for none: a kit of weapons scores nothing without a setup, and no haste is none", () => {
      const dual = TERMS.cases.find((c) => c.tags.includes("weapons") && c.setup === "dw" && c.haste === 0 && c.breakdown.parts.WEAPON !== "0/1");
      expect(dual).toBeDefined();
      const run = (options) => termValue(dual, { options });
      const unset = { setup: undefined, hasteAssumed: undefined, monkBins: BUNDLE.monk_bins, buffset: undefined };
      expect(run({ ...unset, setup: "dw" }).breakdown.parts.WEAPON.toString()).toBe(dual.breakdown.parts.WEAPON); // no haste: as Python's 0
      expect(run(unset).breakdown.parts.WEAPON.toString()).toBe("0/1"); // no setup: no weapon damage
      const kit = new Array(PLACES).fill(null);
      for (const [place, item] of dual.kit) kit[place] = frozen(item);
      const noMonk = frozen({ ...termProfiles[dual.profile], monk: null }); // so that no Monk bins are needed
      for (const none of [undefined, null, {}]) expect(evaluate(noMonk, kit, null, none).breakdown.parts.WEAPON.toString()).toBe("0/1");
    });
    it("takes a null buff set as none: an empty choice is then the profile's own buffs", () => {
      const own = broken({ source: buffsCase, buffs: null, options: (o) => { o.buffset = null; } });
      const empty = broken({ source: buffsCase, buffs: [], options: (o) => { o.buffset = null; } });
      expect(written(empty())).toEqual(written(own()));
    });
    it("takes a haste assumed as a Rational as well as a number", () => {
      const weapons = TERMS.cases.find((c) => c.tags.includes("weapons") && c.haste === 25 && c.breakdown.parts.WEAPON !== "0/1");
      const as = (haste) => termValue(weapons, { options: { hasteAssumed: haste } });
      expect(written(as(new Rational(25n)))).toEqual(written(as(25)));
    });
    it("refuses a Monk profile with no Monk bins, bins that are not for its level, and bins that are not bins", () => {
      refuses(broken({ options: (o) => { delete o.monkBins; } }), /monkBins/);
      const level55 = { ...BUNDLE.monk_bins, curve: { ...BUNDLE.monk_bins.curve, full_bonus_ac: "80/1" } };
      refuses(broken({ options: (o) => { o.monkBins = level55; } }), /monkBins/);
      refuses(broken({ options: (o) => { o.monkBins = { curve: {}, bonus: [], alternatives: [] }; } }), /monkBins/);
      refuses(broken({ options: (o) => { o.monkBins = { ...clone(BUNDLE.monk_bins), bonus: [...BUNDLE.monk_bins.bonus.slice(1), "x/1"] }; } }), /monkBins/);
      refuses(broken({ options: (o) => { o.monkBins = null; } }), /monkBins/);
    });
    it("refuses bins whose full bonus is another level's when the profile's curve names none of its own", () => {
      const other = clone(BUNDLE.monk_bins);
      other.curve.full_bonus_ac = "80/1";
      other.alternatives[0].curve.full_bonus_ac = "80/1";
      const unnamed = (p) => { delete p.monk.full_bonus_ac; };
      refuses(broken({ profile: unnamed, options: (o) => { o.monkBins = other; } }), /another level/);
      expect(() => broken({ profile: unnamed })()).not.toThrow(); // the bins of the level are taken
    });
    it("needs no Monk bins for a profile with no Monk", () => {
      const plain = TERMS.cases.find((c) => termProfiles[c.profile].monk === null && c.buffs === null);
      expect(() => termValue(plain, { options: { monkBins: undefined } })).not.toThrow();
    });
  });

  // `map` and `forEach` skip a hole, so a list with a hole passed the checks made with them and failed later on an `undefined` with a raw
  // TypeError (or was not read at all). Every list the evaluator reads from its arguments is refused with an EvaluateError.
  describe("a list with a hole in it", () => {
    /** A sparse copy of a list: the same entries, and none at `at`. */
    const withHole = (list, at) => {
      const copy = list.slice();
      delete copy[at];
      expect(at in copy).toBe(false);
      expect(copy).toHaveLength(list.length);
      return copy;
    };
    const monkBins = BUNDLE.monk_bins;
    const alternative = (change) => (o) => {
      o.monkBins = clone(monkBins);
      change(o.monkBins);
    };

    for (const [name, make, pattern, source] of [
      ["the optional buffs of the buff set (the probe)", (o) => { o.buffset.set.optional = withHole(o.buffset.set.optional, 0); }, /optional\[0\].*hole/, buffsCase],
      ["the optional buffs of the buff set, in the middle", (o) => { o.buffset.set.optional = withHole(o.buffset.set.optional, 1); }, /optional\[1\].*hole/, buffsCase],
      ["the always-on buffs of the buff set", (o) => { o.buffset.set.always_on = withHole(o.buffset.set.always_on, 0); }, /always_on\[0\].*hole/, buffsCase],
      ["the always-on buffs of the buff set, at the end", (o) => { o.buffset.set.always_on = withHole(o.buffset.set.always_on, 2); }, /always_on\[2\].*hole/, buffsCase],
      ["the bins of the Monk curve", alternative((b) => { b.bonus = withHole(b.bonus, 0); }), /monkBins\.bonus\[0\].*hole/, monkCase],
      ["the bins of the Monk curve, in the middle", alternative((b) => { b.bonus = withHole(b.bonus, 70); }), /monkBins\.bonus\[70\].*hole/, monkCase],
      ["the bins of the Monk curve, at the end", alternative((b) => { b.bonus = withHole(b.bonus, b.bonus.length - 1); }), /bonus\[136\].*hole/, monkCase],
      ["the bins of an alternative", alternative((b) => { b.alternatives[0].bonus = withHole(b.alternatives[0].bonus, 3); }), /alternatives\[0\]\.bonus\[3\].*hole/, monkCase],
      ["the alternatives of the Monk bins", alternative((b) => { b.alternatives = withHole([...b.alternatives, b.alternatives[0]], 1); }), /alternatives\[1\].*hole/, monkCase],
    ]) {
      it(`refuses a hole in ${name}`, () => refuses(broken({ options: make, source }), pattern));
    }

    for (const [name, make, pattern] of [
      ["the breaks of the bands", (p) => { p.bands.breaks = withHole(p.bands.breaks, 1); }, /bands\.breaks\[1\].*hole/],
      ["the breaks of the bands, the first", (p) => { p.bands.breaks = withHole(p.bands.breaks, 0); }, /bands\.breaks\[0\].*hole/],
      ["the slopes of the bands", (p) => { p.bands.slopes = withHole(p.bands.slopes, 2); }, /bands\.slopes\[2\].*hole/],
      ["the slopes of the bands, the last", (p) => { p.bands.slopes = withHole(p.bands.slopes, 3); }, /bands\.slopes\[3\].*hole/],
      ["the HP pools", (p) => { p.pools.HP = withHole(p.pools.HP, 0); }, /pools\.HP\[0\].*hole/],
      ["the HP pools, the last", (p) => { p.pools.HP = withHole(p.pools.HP, p.pools.HP.length - 1); }, /pools\.HP\[\d\].*hole/],
      ["the mana pools", (p) => { p.pools.MANA = withHole(p.pools.MANA, 1); }, /pools\.MANA\[1\].*hole/],
      ["the END pools", (p) => { p.pools.END = withHole(p.pools.END, 2); }, /pools\.END\[2\].*hole/],
    ]) {
      it(`refuses a hole in ${name}`, () => refuses(broken({ profile: make }), pattern));
    }

    // these are read by index, so a hole is read as undefined and was refused already: held here so that it stays so
    it("refuses a hole in the softcap pair, in the kit and in the buffs chosen", () => {
      refuses(broken({ profile: (p) => { p.softcap = withHole(p.softcap, 0); } }), /softcap\[0\]/);
      refuses(broken({ profile: (p) => { p.softcap = withHole(p.softcap, 1); } }), /softcap\[1\]/);
      refuses(broken({ kitValue: (items) => withHole(items, 0) }), /kit\[0\]/);
      refuses(broken({ kitValue: (items) => withHole(items, 21) }), /kit\[21\]/);
      refuses(broken({ kitValue: (items) => withHole(items, CHEST) }), /kit\[13\]/);
      refuses(broken({ source: buffsCase, buffs: withHole([903, 905, 902], 1) }), /buffsChosen\[1\]/);
      refuses(broken({ source: buffsCase, buffs: withHole([903], 0) }), /buffsChosen\[0\]/);
    });
    it("refuses a hole in arguments that are frozen all through, every time (what is frozen is remembered once it has been read: not before)", () => {
      const bins = deepFreeze({ ...clone(monkBins), bonus: withHole(clone(monkBins.bonus), 5) });
      expect(Object.isFrozen(bins.bonus)).toBe(true);
      for (let round = 0; round < 2; round += 1) refuses(broken({ options: (o) => { o.monkBins = bins; } }), /bonus\[5\].*hole/);
    });
    it("takes the same lists without a hole, and an entry that is undefined is still not a hole (it is refused as what it is)", () => {
      expect(() => broken({ profile: (p) => { p.bands.breaks = [...p.bands.breaks]; } })()).not.toThrow();
      refuses(broken({ profile: (p) => { p.bands.breaks[1] = undefined; } }), /bands\.breaks\[1\]/);
    });
  });

  // The bonus of a weight past the end of a table is the last bin, which is right only once the penalty has stopped growing. The exporter writes a
  // bin for each whole stone from 0 to the hardcap and 100 more (the penalty stops growing 90 stones past the hardcap), so a table of any other
  // length is refused: with the tables cut to 5 entries, a Monk at 60 stones was given the bonus of 5 stones (73) instead of -24.
  describe("the Monk bins", () => {
    const profile = assembleProfile(BUNDLE, { race: "HUM", role: "tank", buffs: "own" });
    const HARD = Number(BUNDLE.monk_bins.curve.hardcap_stones.split("/")[0]);
    const kitOf = (weight10) => {
      const kit = new Array(PLACES).fill(null);
      kit[CHEST] = { key: "heavy", stats: {}, sv: {}, haste: 0, weight10, weapon: null, is_shield: false };
      return kit;
    };
    const bonusAt = (weight10, monkBins = BUNDLE.monk_bins) => evaluate(profile, kitOf(weight10), null, { monkBins }).breakdown.totals.sheet.monk_bonus.toString();
    const binsWith = (change) => {
      const bins = clone(BUNDLE.monk_bins);
      change(bins);
      return bins;
    };
    const pythonConstant = () => {
      const source = readFileSync(new URL("../pipeline/trioforge/export/browser.py", import.meta.url), "utf8");
      return Number(/^_MONK_STONES_PAST_HARDCAP = (\d+)/m.exec(source)[1]);
    };

    it("run for the stones past the hardcap that the exporter writes (the constant of browser.py)", () => {
      expect(MONK_STONES_PAST_HARDCAP).toBe(pythonConstant());
      expect(BUNDLE.monk_bins.bonus).toHaveLength(HARD + MONK_STONES_PAST_HARDCAP + 1);
      for (const alternative of BUNDLE.monk_bins.alternatives) expect(alternative.bonus).toHaveLength(HARD + MONK_STONES_PAST_HARDCAP + 1);
    });
    it("give the bonus of 60 stones (-24) and, past the table, the bonus of its last stone", () => {
      expect(bonusAt(600)).toBe("-24/1");
      const last = BUNDLE.monk_bins.bonus[BUNDLE.monk_bins.bonus.length - 1];
      expect(last).toBe("-73/1");
      for (const stones of [HARD + MONK_STONES_PAST_HARDCAP, HARD + MONK_STONES_PAST_HARDCAP + 1, 1000, 100_000]) expect(bonusAt(10 * stones)).toBe(last);
    });
    it("are refused when the table is cut short, the main table and an alternative alike (the probe: 5 entries)", () => {
      refuses(() => bonusAt(600, binsWith((b) => { b.bonus = b.bonus.slice(0, 5); })), /monkBins\.bonus must have 137 entries.*not 5/);
      refuses(() => bonusAt(600, binsWith((b) => { b.alternatives[0].bonus = b.alternatives[0].bonus.slice(0, 5); })), /alternatives\[0\]\.bonus must have 137 entries/);
      refuses(() => bonusAt(600, binsWith((b) => { b.bonus = b.bonus.slice(0, 5); b.alternatives[0].bonus = b.alternatives[0].bonus.slice(0, 5); })), /137/);
    });
    it("are refused when the table is one entry short or one entry long, wherever the weight is", () => {
      for (const weight10 of [0, 600, 10 * HARD, 10 * (HARD + MONK_STONES_PAST_HARDCAP), 100_000]) {
        refuses(() => bonusAt(weight10, binsWith((b) => { b.bonus.pop(); })), /must have 137 entries.*not 136/);
        refuses(() => bonusAt(weight10, binsWith((b) => { b.bonus.push("-73/1"); })), /must have 137 entries.*not 138/);
        refuses(() => bonusAt(weight10, binsWith((b) => { b.alternatives[0].bonus.pop(); })), /alternatives\[0\]\.bonus must have 137 entries/);
        refuses(() => bonusAt(weight10, binsWith((b) => { b.alternatives[0].bonus.push("-73/1"); })), /alternatives\[0\]\.bonus must have 137 entries/);
      }
    });
    it("are refused when the table is the length of another hardcap's, which the curve does not give", () => {
      refuses(() => bonusAt(600, binsWith((b) => { b.curve.hardcap_stones = "40/1"; })), /must have 141 entries.*not 137/);
      refuses(() => bonusAt(600, binsWith((b) => { b.alternatives[0].curve.hardcap_stones = "40/1"; })), /alternatives\[0\]\.bonus must have 141 entries/);
    });
    it("are refused when the hardcap is not a whole number, or not a rational at all", () => {
      refuses(() => bonusAt(600, binsWith((b) => { b.curve.hardcap_stones = "73/2"; })), /curve\.hardcap_stones must be a whole number/);
      refuses(() => bonusAt(600, binsWith((b) => { b.alternatives[0].curve.hardcap_stones = "73/2"; })), /alternatives\[0\]\.curve\.hardcap_stones must be a whole number/);
      refuses(() => bonusAt(600, binsWith((b) => { b.curve.hardcap_stones = 36; })), /hardcap_stones/);
      refuses(() => bonusAt(600, binsWith((b) => { b.curve.hardcap_stones = "1000000000000/1"; })), /hardcap_stones must be a whole number/);
    });
    it("are checked when they are read, whichever table the profile's curve picks (a table that is not used is refused too)", () => {
      refuses(() => bonusAt(600, binsWith((b) => { b.alternatives[0].bonus.pop(); })), /alternatives\[0\]/); // the profile's curve picks the main table
    });
  });

  // A choice among the optional buffs is a choice on top of the always-on buffs of the set, and those are the buffs of the profile
  // (`profile.buff_totals`): another set would value the kit under buffs that the profile never had, with no sign of it.
  describe("the buff set of a choice", () => {
    const NOT_THE_PROFILES = /not the buff set of the profile/;
    const profileOf = (key) => assembleProfile(BUNDLE, { race: "HUM", role: "tank", buffs: key });
    const setOf = (key) => Object.freeze(buffsetOf(BUNDLE, key));
    const run = (profileKey, setKey, chosen) => () =>
      evaluate(profileOf(profileKey), new Array(PLACES).fill(null), chosen, { monkBins: BUNDLE.monk_bins, buffset: setOf(setKey) });

    it("is refused when it is the raid set under the own buffs of the profile, whatever is chosen (the F that was 6486.85 for 7436.895)", () => {
      refuses(run("own", "raid", []), NOT_THE_PROFILES);
      refuses(run("own", "raid", BUNDLE.buffs.raid.set.optional.slice(0, 2)), NOT_THE_PROFILES);
      refuses(run("raid", "own", []), NOT_THE_PROFILES);
      refuses(run("raid", "own", BUNDLE.buffs.own.set.optional), NOT_THE_PROFILES);
    });
    it("says which total differs", () => {
      refuses(run("own", "raid", []), /AC .*160/);
    });
    it("is taken when it is the set of the profile's own buff key, with no choice and with every kind of choice", () => {
      for (const key of Object.keys(BUNDLE.buffs)) {
        const optional = BUNDLE.buffs[key].set.optional;
        for (const chosen of [[], optional.slice(0, 1), optional.slice(0, 3)]) expect(run(key, key, chosen), `${key} ${chosen.length}`).not.toThrow();
      }
      const own = evaluate(profileOf("own"), new Array(PLACES).fill(null), null, { monkBins: BUNDLE.monk_bins });
      expect(run("own", "own", [])().F.equals(own.F)).toBe(true); // no buff chosen is the profile's own buffs
    });
    it("is taken when both give no totals at all (a profile whose set has no always-on buffs, under another set of that kind)", () => {
      expect(BUNDLE.buffs.group.set.always_on).toEqual([]);
      expect(BUNDLE.buffs.raid.set.always_on).toEqual([]);
      expect(run("group", "raid", BUNDLE.buffs.raid.set.optional.slice(0, 2))).not.toThrow();
      expect(run("raid", "group", [])).not.toThrow();
    });
    // the rules of BuffSet.is_legal: no excluded pair, and no more distinct optional buffs than the cardinality; the ids that are always on are
    // skipped, as BuffSet.totals skips them
    describe("that is legal", () => {
      const raidProfile = profileOf("raid");
      const raidSet = setOf("raid");
      const [firstA, firstB] = BUNDLE.buffs.raid.set.conflicts[0];
      const loose = BUNDLE.buffs.raid.set.optional.filter((id) => BUNDLE.buffs.raid.set.conflicts.every(([a, b]) => a !== id && b !== id));
      const evaluated = (chosen) => () => evaluate(raidProfile, new Array(PLACES).fill(null), chosen, { monkBins: BUNDLE.monk_bins, buffset: raidSet });

      it("has the cardinality and the conflicts that the tests below rely on", () => {
        expect(BUNDLE.buffs.raid.set.cardinality).toBe(15);
        expect(loose.length).toBeGreaterThan(16);
      });
      it("is refused when it holds an excluded pair, wherever the two are in it", () => {
        refuses(evaluated([firstA, firstB]), /exclude each other/);
        refuses(evaluated([firstB, loose[0], firstA]), new RegExp(`${firstA}|${firstB}`));
        for (const [a, b] of BUNDLE.buffs.raid.set.conflicts) refuses(evaluated([b, a]), /exclude/);
      });
      it("takes one of every excluded pair", () => {
        for (const [a, b] of BUNDLE.buffs.raid.set.conflicts) {
          expect(evaluated([a]), `${a}`).not.toThrow();
          expect(evaluated([b, loose[0]]), `${b}`).not.toThrow();
        }
      });
      it("is refused when it names more distinct optional buffs than the cardinality (16 against 15), and taken at the cardinality", () => {
        refuses(evaluated(loose.slice(0, 16)), /15/);
        expect(evaluated(loose.slice(0, 15))).not.toThrow();
        expect(evaluated([...loose.slice(0, 15), ...loose.slice(0, 15)])).not.toThrow(); // a repeat counts once
      });
      it("has no limit on its size when the cardinality is null, and ids that are always on do not count against it", () => {
        const optional = buffsCase.buffset.set.optional;
        expect(broken({ source: buffsCase, buffs: [...optional], options: (o) => { o.buffset.set.conflicts = []; } })).not.toThrow();
        const one = (o) => { o.buffset.set.cardinality = 1; o.buffset.set.conflicts = []; };
        expect(broken({ source: buffsCase, buffs: [903, 901, 902, 906, 901], options: one })).not.toThrow();
        refuses(broken({ source: buffsCase, buffs: [903, 905], options: one }), /at most 1/);
      });
      for (const [name, change] of [
        ["conflicts that are not a list", (o) => { o.buffset.set.conflicts = 5; }],
        ["a hole among the conflicts", (o) => { const list = [[903, 904, ["haste"]], [903, 905, []]]; delete list[0]; o.buffset.set.conflicts = list; }],
        ["a conflict that is not a pair of ids", (o) => { o.buffset.set.conflicts = [[903]]; }],
        ["a conflict of ids that are not whole", (o) => { o.buffset.set.conflicts = [[903, "904", []]]; }],
        ["a cardinality that is not whole", (o) => { o.buffset.set.cardinality = 1.5; }],
        ["a cardinality that is negative", (o) => { o.buffset.set.cardinality = -1; }],
        ["a cardinality as text", (o) => { o.buffset.set.cardinality = "15"; }],
      ]) {
        it(`refuses a set with ${name}`, () => refuses(broken({ source: buffsCase, buffs: [903], options: change }), /conflicts|cardinality/));
      }
    });
    for (const [name, change] of [
      ["a profile that has a buff total more than the always-on buffs give", { profile: (p) => { p.buff_totals.AC += 1; } }],
      ["a profile that has a buff total less", { profile: (p) => { p.buff_totals.HP -= 1; } }],
      ["a profile with another spell haste", { profile: (p) => { p.buff_totals.HASTE += 1; } }],
      ["a profile with a resist the set does not give", { profile: (p) => { p.buff_totals.SV = { FIRE: 5 }; } }],
      ["a table whose always-on buff gives other amounts", { options: (o) => { o.buffset.table["901"].vec.AC = 21; } }],
      ["a table whose always-on buff gives another haste", { options: (o) => { o.buffset.table["902"].vec.HASTE = 31; } }],
      ["a set that lacks one of the profile's always-on buffs", { options: (o) => { o.buffset.set.always_on = [901, 902]; } }],
      ["a set whose always-on buffs are another", { options: (o) => { o.buffset.set.always_on = [901, 902, 906, 905]; o.buffset.set.optional = [903, 904]; } }],
    ]) {
      for (const chosen of [[], [903]]) {
        it(`refuses ${name} (choice of ${chosen.length})`, () => refuses(broken({ source: buffsCase, buffs: chosen, ...change }), NOT_THE_PROFILES));
      }
    }
  });
});

// ---- input broken at random ------------------------------------------------------------------------------------------------------------

describe("input broken at random", () => {
  const BASES = ["monk", "weapons", "buffs", "pool-order", "decimals"].map((tag) => {
    const stored = TERMS.cases.find((c) => c.tags.includes(tag) && (tag !== "buffs" || (c.buffs ?? []).length > 1) && (tag !== "weapons" || c.setup === "dw"));
    return stored;
  });
  const JUNK = [
    undefined, null, true, false, 0, -1, 1, 1.5, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, 2 ** 40, 2 ** 53, 2 ** 60, -(2 ** 41),
    "", "x", "1/2", "0/0", "-1/1", "__proto__", [], [0], [null], {}, { a: 1 }, 10n, Symbol("junk"), () => 1, new Date(0), new Map(), new Rational(1n),
  ];

  /** The paths (lists of keys) of every value under a root, root excluded. */
  function paths(root) {
    const found = [];
    const stack = [[root, []]];
    while (stack.length > 0) {
      const [node, path] = stack.pop();
      if (node === null || typeof node !== "object") continue;
      for (const key of Object.keys(node)) {
        found.push([...path, key]);
        stack.push([node[key], [...path, key]]);
      }
    }
    return found;
  }

  it("is valued or refused with an EvaluateError, and fails in no other way (the profile, the kit, the choice of buffs and the options)", () => {
    const random = mulberry32(20261014);
    const pick = (list) => list[Math.floor(random() * list.length)];
    const failures = [];
    let refused = 0;
    let valued = 0;
    for (let round = 0; round < 6000; round += 1) {
      const stored = pick(BASES);
      const kit = new Array(PLACES).fill(null);
      for (const [place, item] of stored.kit) kit[place] = clone(item);
      const input = {
        profile: clone(TERMS.profiles[stored.profile]),
        kit,
        buffs: clone(stored.buffs),
        options: { setup: stored.setup, hasteAssumed: stored.haste, monkBins: clone(BUNDLE.monk_bins), buffset: stored.buffset === null ? undefined : clone(stored.buffset) },
      };
      const where = [];
      for (let change = 0, count = 1 + Math.floor(random() * 3); change < count; change += 1) {
        const target = pick(paths(input));
        let parent = input;
        for (const key of target.slice(0, -1)) parent = parent[key];
        const key = target[target.length - 1];
        const junk = pick(JUNK);
        if (Object.isFrozen(parent)) continue; // (an earlier change of the round put a frozen object, a Rational, in the input: there is nothing to write into)
        if (junk === undefined && !Array.isArray(parent)) delete parent[key];
        else parent[key] = junk;
        where.push(`${target.join(".")} = ${typeof junk === "symbol" ? "a symbol" : typeof junk === "function" ? "a function" : String(junk)}`);
      }
      try {
        evaluate(input.profile, input.kit, input.buffs, input.options);
        valued += 1;
      } catch (error) {
        if (error instanceof EvaluateError) refused += 1;
        else failures.push(`${where.join("; ")} -> ${error?.name}: ${error?.message}`);
      }
      if (failures.length >= 5) break;
    }
    expect(failures).toEqual([]);
    expect(refused).toBeGreaterThan(1000); // most of the breakage is refused ...
    expect(valued).toBeGreaterThan(0); // ... and some of it breaks nothing the evaluator reads
  }, 60_000);

  it("refuses a kit entry, a profile or options of the wrong kind outright", () => {
    const stored = BASES[0];
    const kit = new Array(PLACES).fill(null);
    for (const [place, item] of stored.kit) kit[place] = clone(item);
    for (const junk of JUNK) {
      if (junk === undefined || junk === null) continue;
      if (typeof junk !== "object" || Array.isArray(junk) || junk instanceof Rational) {
        expect(() => evaluate(junk, kit, null, { monkBins: BUNDLE.monk_bins }), `profile ${String(typeof junk)}`).toThrow(EvaluateError);
      }
    }
  });
});

// ---- speed -----------------------------------------------------------------------------------------------------------------------------

describe("speed", () => {
  it("values 10,000 kits in under 2 seconds on a read bundle and a profile of it", () => {
    const bundle = readBundle(SAMPLE.read(BUNDLE_PATH));
    const profile = assembleProfile(bundle, { race: "HUM", role: "melee", buffs: "group" });
    const buffset = Object.freeze({ set: bundle.buffs.group.set, table: bundle.buff_table });
    const chosen = bundle.buffs.group.set.optional.slice(0, 6);
    expect(chosen.length).toBeGreaterThan(0);
    const listing = SAMPLE.read("evaluate/profiles.json");
    const records = new Map(listing.records.map((record) => [record.key ?? `w${record.id}`, record]));
    const kits = SAMPLE.read(SAMPLE.paths("evaluate-kits")[0])
      .evaluations.slice(0, 60)
      .map((evaluation) => evaluation.kit.map((entry) => (entry === null ? null : atTier(records.get(entry[0]), entry[1], bundle, { weaponPct: listing.weapon_pct }))));
    const setups = [null, "1h-shield", "2h", "dw", "stick"];
    const run = (count) => {
      let last;
      for (let i = 0; i < count; i += 1) {
        const options = { setup: setups[i % setups.length], hasteAssumed: 25, monkBins: bundle.monk_bins, buffset };
        last = evaluate(profile, kits[i % kits.length], i % 2 === 0 ? null : chosen, options);
      }
      return last;
    };
    run(1000); // warm-up
    const watch = stopwatch();
    const last = run(10_000);
    const took = watch.stop();
    console.log(`10,000 evaluations: ${took.ms.toFixed(0)} ms (${(took.ms / 10).toFixed(1)} us each)`);
    expect(last.F).toBeInstanceOf(Rational);
    expectWithin(took, 2000, "10,000 evaluations");
  }, 60_000);
});
