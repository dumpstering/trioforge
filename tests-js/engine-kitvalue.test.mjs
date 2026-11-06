// The value of a kit, worked out in the page with the engine's own evaluator (static/engine/kitvalue.js): what the Upgrade section shows for a kit that came in a link. The bundle of
// the trio is fetched as the worker fetches it, by the paths the manifests list and checked against their sizes and SHA-256. The items and the bundle are those of the synthetic site
// fixture (every name in them is invented).
//
// The value of a kit is the kit's own: the weapon setup is read from its hands (a two-hander in the main hand is "2h", a shield in the off hand "1h-shield", two weapons "dw", and a hand
// that holds something that is not a weapon makes it a stat stick), the haste its weapons are scored at is the model's rule for the items the value counts (the best spell haste the buff
// set offers and the best worn haste of those items, up to the cap), and the buffs are the best the set allows for that kit. The exact numbers are those Python's reference gives for the
// kit as the whole owned set (fixtures/site/kit-values.json: 66 values of 6 kits under up to 12 views), and the worker's own answer for the same kit (engine-kitvalue-worker.test.mjs).

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { evaluate } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { atTier, readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { allowedInHand, readItem } from "../pipeline/trioforge/site/static/engine/model.js";
import { BundleError, assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { BUFF_SEARCH_LIMIT, loadKitBundle, valueOfKit } from "../pipeline/trioforge/site/static/engine/kitvalue.js";
import { BUNDLE_BYTES, makeSite, siteFetch } from "./engine-site-fixture.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const RESULTS = resolve(ROOT, "fixtures/site/results");
const table = readItemTable(JSON.parse(readFileSync(resolve(RESULTS, "items.json"), "utf8")));
const bundle = JSON.parse(readFileSync(resolve(RESULTS, "pal-mnk-ber/engine-l50.json"), "utf8"));
const CASES = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/equip-now.json"), "utf8")).cases;
const KIT_VALUES = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/kit-values.json"), "utf8"));
const KITS = KIT_VALUES.kits;

const AS_OF_THE_PAGE = { race: "OGR", role: "balanced", buffs: "own", evidence: "wiki" };
/** The heavy tests (every legal choice of buffs, the reference kits under every buff set) take 2.5 s alone and 5.4 to 6.0 s in a loaded full run, and vitest gives a test 5 s. */
const HEAVY = 30_000;

/** The places of a kit of idents ("w90001@4", or null for a place left empty): what the section gives the evaluator. */
function placesOf(kit) {
  const places = [];
  kit.forEach((ident, slotIndex) => {
    if (ident === null) return;
    const at = ident.lastIndexOf("@");
    places.push({ slotIndex, key: ident.slice(0, at), tier: Number(ident.slice(at + 1)) });
  });
  return places;
}

const run = (over = {}) => valueOfKit({ bundle, records: table.records, ...AS_OF_THE_PAGE, places: placesOf(CASES[0].kit), ...over });
/** The item table with some records more (plain records, as the table holds them; the key of a record is `w<id>`). */
const tableWith = (...records) => {
  const made = new Map(table.records);
  for (const record of records) made.set(`w${record.id}`, record);
  return made;
};
const PRIMARY = 20;
const SECONDARY = 21;

describe("a kit that Python's reference valued", () => {
  const rows = KIT_VALUES.values.map((row) => [`${KITS[row.kit].name} / ${row.role} / ${row.buffs}`, row]);
  it("has values of 6 kits under the four buff sets and the three roles of the bundle", () => {
    expect(KITS).toHaveLength(6);
    expect(KIT_VALUES.values.length).toBeGreaterThanOrEqual(60);
    expect(new Set(KIT_VALUES.values.map((row) => row.buffs))).toEqual(new Set(["own", "group", "group+enchanter", "raid"]));
    expect(new Set(KIT_VALUES.values.map((row) => row.role))).toEqual(new Set(["balanced", "tank", "melee"]));
  });

  it.each(rows)("is worth what the reference says, exactly, with the setup of its hands and the haste of the model's rule: %s", (_, row) => {
    const kit = KITS[row.kit];
    const answer = valueOfKit({ bundle, records: table.records, race: kit.race, role: row.role, buffs: row.buffs, evidence: kit.evidence, deity: kit.deity, places: placesOf(kit.kit) });
    expect(answer.F).toBe(row.F); // (the exact value, as a reduced fraction)
    expect(answer.value).toBe(row.value);
    expect(answer.setup, "the setup of the kit's hands").toBe(kit.setup);
    expect(answer.hasteAssumed, "the haste of the model's rule for the kit's own items").toBe(row.hasteAssumed);
    expect(answer.exact).toBe(true);
    expect(answer.left).toEqual([]);
    expect(answer.counted).toBe(kit.kit.filter((ident) => ident !== null).length);
  }, HEAVY);
});

describe("the value follows the view, and nothing else", () => {
  it("changes with the role, the buffs and the race", () => {
    const base = run();
    const melee = run({ role: "melee" });
    const tank = run({ role: "tank" });
    expect(new Set([base.value, melee.value, tank.value]).size).toBe(3);
    expect(run({ buffs: "group" }).value).toBeGreaterThan(base.value); // (a group has more to offer than one's own buffs)
    expect(run({ race: "HUM" }).value).not.toBe(run({ race: "OGR" }).value);
  });

  it("is exact: the same call gives the same value, however often it is made", () => {
    const first = run();
    for (let i = 0; i < 3; i += 1) expect(run()).toEqual(first);
  });

  it("answers in plain data that can be written as JSON", () => {
    const answer = run();
    expect(JSON.parse(JSON.stringify(answer))).toEqual(answer);
    expect(Object.keys(answer).sort()).toEqual(["F", "buffs", "counted", "evaluations", "exact", "hasteAssumed", "left", "setup", "value"]);
    expect(typeof answer.F).toBe("string");
    expect(answer.buffs.every((id) => Number.isInteger(id))).toBe(true);
    expect(Number.isInteger(answer.hasteAssumed) && Number.isInteger(answer.evaluations)).toBe(true);
  });

  it("takes no weapon setup and no haste from the caller: the kit's hands and the model's rule give them", () => {
    expect(() => run({ setup: "2h" })).toThrow(TypeError);
    expect(() => run({ hasteAssumed: 66 })).toThrow(TypeError);
    expect(() => run({ setup: undefined })).toThrow(TypeError);
  });
});

describe("the weapon setup is read from the kit's hands", () => {
  const setupOf = (places, over) => valueOfKit({ bundle, records: table.records, ...AS_OF_THE_PAGE, ...over, places }).setup;
  const head = { slotIndex: 0, key: "w90001", tier: 4 };
  const orb = { ...table.records.get("w90027"), id: 90701, name: "Orb of Idle Hands", slots: ["PRIMARY", "SECONDARY"], stats: { WIS: 11, MANA: 50 } };
  const twinPike = { ...table.records.get("w80524"), id: 90702, name: "Pike of Two Hands", slots: ["PRIMARY", "SECONDARY"] };

  it("is dual wield for two one-handers, one-hander and shield for a shield in the off hand, and two-hander for a two-hander in the main hand", () => {
    expect(setupOf([head, { slotIndex: PRIMARY, key: "w80988", tier: 4 }, { slotIndex: SECONDARY, key: "w80113", tier: 0 }])).toBe("dw");
    expect(setupOf([head, { slotIndex: PRIMARY, key: "w80988", tier: 4 }, { slotIndex: SECONDARY, key: "w80583", tier: 4 }])).toBe("1h-shield");
    expect(setupOf([head, { slotIndex: PRIMARY, key: "w80524", tier: 4 }])).toBe("2h");
  });

  it("is dual wield for hands that are empty and for a one-hander alone: the value is the same under both", () => {
    expect(setupOf([head])).toBe("dw");
    expect(setupOf([head, { slotIndex: PRIMARY, key: "w80988", tier: 4 }])).toBe("dw");
    expect(setupOf([head, { slotIndex: SECONDARY, key: "w80113", tier: 0 }])).toBe("dw");
  });

  it("is a stat stick when a hand holds something that is not a weapon, and then no weapon damage is scored", () => {
    const records = tableWith(orb);
    const places = [head, { slotIndex: PRIMARY, key: "w80988", tier: 4 }, { slotIndex: SECONDARY, key: "w90701", tier: 0 }];
    const answer = valueOfKit({ bundle, records, ...AS_OF_THE_PAGE, places });
    expect(answer.setup).toBe("stick");
    expect(answer.left).toEqual([]); // (the orb in the off hand is worn, as the stat-stick setup lets it be)
    const read = readBundle(structuredClone(bundle));
    const profile = assembleProfile(read, AS_OF_THE_PAGE);
    const worn = [];
    worn[0] = atTier(records.get("w90001"), 4, read);
    worn[PRIMARY] = atTier(records.get("w80988"), 4, read);
    worn[SECONDARY] = atTier(records.get("w90701"), 0, read);
    const kit = Array.from({ length: 22 }, (_, index) => worn[index] ?? null);
    const direct = evaluate(profile, kit, answer.buffs, { setup: "stick", hasteAssumed: answer.hasteAssumed, monkBins: read.monk_bins ?? undefined, buffset: { set: read.buffs.own.set, table: read.buff_table } });
    expect(answer.F).toBe(direct.F.toString());
    expect(setupOf(places.slice(0, 2), { records })).toBe("dw"); // (the same weapon without the orb is a dual wielder's)
  });

  it("is two-hander for a two-hander in the main hand, and the off hand's item is not counted", () => {
    const records = tableWith(twinPike);
    const answer = valueOfKit({ bundle, records, ...AS_OF_THE_PAGE, places: [{ slotIndex: PRIMARY, key: "w90702", tier: 0 }, { slotIndex: SECONDARY, key: "w80583", tier: 4 }] });
    expect(answer.setup).toBe("2h");
    expect(answer.left).toEqual([{ slotIndex: SECONDARY, reason: "hands" }]);
  });
});

describe("the hands: what the model's rules let into them", () => {
  const head = { slotIndex: 0, key: "w90001", tier: 4 };
  const maul = { slotIndex: PRIMARY, key: "w80524", tier: 4 }; // a two-hander that lists the main hand only
  const pike = { slotIndex: PRIMARY, key: "w80988", tier: 4 };
  const mallet = { slotIndex: SECONDARY, key: "w80113", tier: 0 }; // a one-hander that lists both hands
  const shield = { slotIndex: SECONDARY, key: "w80583", tier: 4 };
  const orb = { ...table.records.get("w90027"), id: 90701, name: "Orb of Idle Hands", slots: ["PRIMARY", "SECONDARY"], stats: { WIS: 11, MANA: 50 } };
  // a two-hander that lists the off hand too: its page says so, and the model never lets it stand there (it needs both hands, whatever its page lists)
  const twin = { ...table.records.get("w80524"), id: 90702, name: "Pike of Two Hands", slots: ["PRIMARY", "SECONDARY"] };
  const records = tableWith(orb, twin);
  const worth = (places) => valueOfKit({ bundle, records, ...AS_OF_THE_PAGE, places });

  it("leave out an item in the off hand when a two-hander is in the main hand, and say why: a two-hander leaves the off hand empty", () => {
    for (const second of [mallet, shield]) {
      const answer = worth([head, maul, second]);
      expect(answer.left, second.key).toEqual([{ slotIndex: SECONDARY, reason: "hands" }]);
      expect(answer.setup).toBe("2h");
      expect(answer.F, "and the value is the two-hander's alone").toBe(worth([head, maul]).F);
      expect(answer.counted).toBe(2);
    }
  });

  it("leave out a two-hander in the off hand, whatever its page lists, and keep the main hand's one-hander", () => {
    const answer = worth([head, pike, { slotIndex: SECONDARY, key: "w90702", tier: 0 }]);
    expect(answer.left).toEqual([{ slotIndex: SECONDARY, reason: "hands" }]);
    expect(answer.F).toBe(worth([head, pike]).F);
    const alone = worth([head, { slotIndex: SECONDARY, key: "w90702", tier: 0 }]);
    expect(alone.left).toEqual([{ slotIndex: SECONDARY, reason: "hands" }]);
    expect(alone.F).toBe(worth([head]).F);
  });

  it("leave out the second of two two-handers: the one in the main hand stands", () => {
    const answer = worth([maul, { slotIndex: SECONDARY, key: "w90702", tier: 0 }]);
    expect(answer.left).toEqual([{ slotIndex: SECONDARY, reason: "hands" }]);
    expect(answer.counted).toBe(1);
  });

  it("let a two-hander stand alone in the main hand, a one-hander with a shield or with a second one-hander, and an empty pair", () => {
    for (const places of [[head, maul], [head, pike, shield], [head, pike, mallet], [head], []]) expect(worth(places).left, JSON.stringify(places)).toEqual([]);
  });

  it("are the model's own: whatever the hands hold, what is counted there is what allowedInHand lets in under the setup, and a two-hander in the main hand leaves the off hand empty", () => {
    const mains = [null, pike, maul, { slotIndex: PRIMARY, key: "w90702", tier: 0 }, { slotIndex: PRIMARY, key: "w90701", tier: 0 }];
    const seconds = [null, mallet, shield, { slotIndex: SECONDARY, key: "w90702", tier: 0 }, { slotIndex: SECONDARY, key: "w90701", tier: 0 }];
    const read = readBundle(structuredClone(bundle));
    let tried = 0;
    for (const main of mains) {
      for (const second of seconds) {
        const places = [head, ...(main === null ? [] : [main]), ...(second === null ? [] : [second])];
        const answer = worth(places);
        const left = new Set(answer.left.map((one) => one.slotIndex));
        const items = (place) => (place === null || left.has(place.slotIndex) ? null : readItem(atTier(records.get(place.key), place.tier, read), 0));
        const [one, other] = [items(main), items(second)];
        const name = `${main?.key ?? "empty"} / ${second?.key ?? "empty"} -> ${answer.setup}`;
        if (one !== null) expect(allowedInHand(one, "PRIMARY", answer.setup), name).toBe(true);
        if (other !== null) expect(allowedInHand(other, "SECONDARY", answer.setup), name).toBe(true);
        if (one !== null && one.weapon !== null && one.weapon.twoHanded) expect(other, name).toBeNull();
        for (const slotIndex of left) expect([PRIMARY, SECONDARY], name).toContain(slotIndex);
        for (const { reason } of answer.left) expect(["slot", "hands"], name).toContain(reason);
        // what is left out is the only thing that differs: the same call with the counted items alone counts all of them and leaves none
        const counted = places.filter((place) => !left.has(place.slotIndex));
        const again = worth(counted);
        expect(again.left, name).toEqual([]);
        expect(again.F, name).toBe(answer.F);
        expect(again.setup, name).toBe(answer.setup);
        tried += 1;
      }
    }
    expect(tried).toBe(25);
  });
});

describe("the haste the weapons are scored at", () => {
  const hoop = { ...table.records.get("w90008"), id: 90703, name: "Hoop of the Quick", stats: { HASTE: 30 } };
  const wizard = { ...hoop, id: 90704, name: "Hoop of the Quick Archmage", classes: ["WIZ"] };
  const swift = { ...hoop, id: 90705, name: "Hoop of the Impossibly Quick", stats: { HASTE: 90 } };
  const places = (key, tier = 0) => [{ slotIndex: 2, key, tier }];
  const hasteOf = (records, list, over) => valueOfKit({ bundle, records, ...AS_OF_THE_PAGE, ...over, places: list }).hasteAssumed;
  const spell = (buffs) => bundle.buffs[buffs].spell_haste;

  it("is the spell haste of the buffs the value counts when the kit wears no haste: the best of the haste buffs it takes, with the 10 of the Monk's Unbound Alacrity", () => {
    const bonus = bundle.profile_common.haste_bonus;
    for (const buffs of ["own", "group", "group+enchanter", "raid"]) {
      const answer = run({ buffs, places: [] });
      const { set, table: spells } = { set: bundle.buffs[buffs].set, table: bundle.buff_table };
      const taken = [...set.always_on, ...answer.buffs].map((id) => spells[String(id)].vec.HASTE ?? 0);
      expect(answer.hasteAssumed, buffs).toBe(Math.min(bundle.profile_common.haste_cap, Math.max(0, ...taken) + bonus));
      expect(answer.hasteAssumed, buffs).toBeLessThanOrEqual(spell(buffs)); // (never more than the best spell haste on offer: what the fixture's bundle says is 25, 40, 60 and 60 and the 10 of the Monk)
    }
    expect([35, 50, 70, 70]).toEqual(["own", "group", "group+enchanter", "raid"].map(spell));
  });

  it("adds the best worn haste of the items the value counts", () => {
    const records = tableWith(hoop);
    expect(hasteOf(records, places("w90703"), { buffs: "own" })).toBe(35 + 30);
    expect(hasteOf(records, places("w90703"), { buffs: "group" })).toBe(50 + 30);
    expect(hasteOf(records, [...places("w90703"), { slotIndex: 3, key: "w90008", tier: 0 }], { buffs: "own" }), "the best one counts, not the sum").toBe(35 + 30);
    const read = readBundle(structuredClone(bundle));
    const worn = atTier(table.records.get("w90008"), 4, read).haste;
    expect(worn).toBeGreaterThan(15); // (a hoop of haste is scored by its tier)
    expect(hasteOf(table.records, [{ slotIndex: 2, key: "w90008", tier: 4 }], { buffs: "own" })).toBe(35 + worn);
  });

  it("stops at the cap of the bundle", () => {
    const records = tableWith(swift);
    expect(bundle.profile_common.haste_cap).toBe(85);
    expect(hasteOf(records, places("w90705"), { buffs: "own" })).toBe(85);
    expect(hasteOf(records, places("w90705"), { buffs: "raid" })).toBe(85);
  });

  it("does not count an item the value leaves out: one the trio cannot use, one in a place it does not fit, one the table does not have", () => {
    const records = tableWith(hoop, wizard);
    expect(hasteOf(records, places("w90704"), { buffs: "own" })).toBe(35);
    expect(hasteOf(records, [{ slotIndex: 0, key: "w90703", tier: 0 }], { buffs: "own" }), "an ear piece in the head place").toBe(35);
    expect(hasteOf(records, places("w99999"), { buffs: "own" })).toBe(35);
    expect(hasteOf(records, [...places("w90703"), { slotIndex: 0, key: "w90704", tier: 0 }], { buffs: "own" })).toBe(65);
  });

  it("is the haste the value is worked out at: the evaluator's value for the kit at that haste, with the setup and the buffs of the answer, is the answer's", () => {
    const records = tableWith(hoop);
    const worn = placesOf(CASES[0].kit).map((place) => (place.slotIndex === 3 ? { slotIndex: 3, key: "w90703", tier: 0 } : place));
    const answer = valueOfKit({ bundle, records, ...AS_OF_THE_PAGE, places: worn });
    expect(answer.hasteAssumed).toBe(35 + 30);
    const read = readBundle(structuredClone(bundle));
    const profile = assembleProfile(read, AS_OF_THE_PAGE);
    const kit = Array.from({ length: 22 }, (_, index) => {
      const place = worn.find((one) => one.slotIndex === index);
      return place === undefined ? null : atTier(records.get(place.key), place.tier, read);
    });
    const direct = evaluate(profile, kit, answer.buffs, { setup: answer.setup, hasteAssumed: answer.hasteAssumed, monkBins: read.monk_bins ?? undefined, buffset: { set: read.buffs.own.set, table: read.buff_table } });
    expect(answer.F).toBe(direct.F.toString());
    expect(Number.isInteger(answer.hasteAssumed)).toBe(true);
  });
});

describe("the optional buffs", () => {
  const kit = CASES[2].kit;
  const view = { race: "IKS", role: "melee", evidence: "wiki" };
  const ofKit = (over = {}) => valueOfKit({ bundle, records: table.records, ...view, buffs: "raid", places: placesOf(kit), ...over });

  it("are at most as many as the set allows and never two that exclude each other", () => {
    for (const buffs of ["own", "group", "group+enchanter", "raid"]) {
      const set = bundle.buffs[buffs].set;
      const answer = ofKit({ buffs });
      if (set.cardinality !== null) expect(answer.buffs.length, buffs).toBeLessThanOrEqual(set.cardinality);
      for (const id of answer.buffs) expect(set.optional, buffs).toContain(id);
      for (const [a, b] of set.conflicts) expect(answer.buffs.includes(a) && answer.buffs.includes(b), `${buffs}: ${a} and ${b}`).toBe(false);
    }
  });

  it("add to the value: each set is worth more with them than with its always-on buffs alone", () => {
    for (const buffs of ["own", "group", "raid"]) {
      const read = readBundle(structuredClone(bundle));
      const profile = assembleProfile(read, { race: view.race, role: view.role, buffs, evidence: view.evidence });
      const items = kit.map((ident) => (ident === null ? null : atTier(table.records.get(ident.slice(0, ident.lastIndexOf("@"))), Number(ident.slice(ident.lastIndexOf("@") + 1)), read)));
      const best = ofKit({ buffs });
      const alone = evaluate(profile, items, null, { setup: best.setup, hasteAssumed: best.hasteAssumed, monkBins: read.monk_bins ?? undefined }).F.toNumber();
      expect(best.value, buffs).toBeGreaterThan(alone);
      if (buffs === "group") expect(best.value / alone).toBeGreaterThan(1.2);
    }
  });

  it("are the best set there is for the kit: none of the (19 choose 15) and fewer choices of the group set is worth more", () => {
    const read = readBundle(structuredClone(bundle));
    const profile = assembleProfile(read, { ...view, buffs: "group" });
    const items = kit.map((ident) => (ident === null ? null : atTier(table.records.get(ident.slice(0, ident.lastIndexOf("@"))), Number(ident.slice(ident.lastIndexOf("@") + 1)), read)));
    const answer = ofKit({ buffs: "group" });
    const options = { setup: answer.setup, hasteAssumed: answer.hasteAssumed, monkBins: read.monk_bins ?? undefined, buffset: { set: read.buffs.group.set, table: read.buff_table } };
    const optional = read.buffs.group.set.optional;
    let best = null;
    let tried = 0;
    // every set of 13, 14 or 15 of the 19 (the sets of fewer would have to be worth more than all of these, which a buff that adds nothing never makes them)
    const choose = (from, chosen) => {
      if (chosen.length >= 13) {
        tried += 1;
        const worth = evaluate(profile, items, chosen, options).F;
        if (best === null || worth.compare(best) > 0) best = worth;
      }
      if (chosen.length === 15) return;
      for (let i = from; i < optional.length; i += 1) choose(i + 1, [...chosen, optional[i]]);
    };
    choose(0, []);
    expect(tried).toBe(27132 + 11628 + 3876);
    expect(answer.F).toBe(best.toString());
    expect(answer.exact).toBe(true);
  }, HEAVY);

  it("are left out when they take away more than they give, though the set has room: a buff that costs a great deal of regeneration is not chosen", () => {
    const damaged = structuredClone(bundle);
    damaged.buff_table["1453"].vec = { MANAREG: -500, HPREG: -500, ENDREG: -500 }; // Divine Purpose, made a curse
    const answer = valueOfKit({ bundle: damaged, records: table.records, ...AS_OF_THE_PAGE, buffs: "group", places: placesOf(CASES[0].kit) });
    expect(answer.buffs).not.toContain(1453);
    const withIt = valueOfKit({ bundle, records: table.records, ...AS_OF_THE_PAGE, buffs: "group", places: placesOf(CASES[0].kit) });
    expect(withIt.buffs).toContain(1453);
    expect(answer.value).toBeLessThan(withIt.value);
    expect(answer.exact).toBe(true);
  });

  it("are chosen with a number of calls to the evaluator that is far below the limit: the raid set, the largest, takes a few thousand at most", () => {
    expect(BUFF_SEARCH_LIMIT).toBe(6000);
    for (const buffs of ["own", "group", "group+enchanter", "raid"]) {
      for (const one of CASES) {
        const { race, role, evidence, deity } = one.scenario;
        const answer = valueOfKit({ bundle, records: table.records, race, role, buffs, evidence, deity, places: placesOf(one.kit) });
        expect(answer.exact, `${one.name} / ${buffs}`).toBe(true);
        expect(answer.evaluations, `${one.name} / ${buffs}`).toBeLessThan(BUFF_SEARCH_LIMIT / 2);
      }
    }
  }, HEAVY);

  it("are reported as a lower bound when the search runs out of calls: the value is at least what was found, never more than the best, and the answer says it is not exact", () => {
    const full = ofKit();
    expect(full.exact).toBe(true);
    for (const searchLimit of [1, 5, 40, 150]) {
      const cut = ofKit({ searchLimit });
      expect(cut.exact, String(searchLimit)).toBe(false);
      expect(cut.evaluations, String(searchLimit)).toBeLessThanOrEqual(searchLimit);
      expect(cut.value, String(searchLimit)).toBeLessThanOrEqual(full.value);
      const set = bundle.buffs.raid.set;
      expect(cut.buffs.length).toBeLessThanOrEqual(set.cardinality);
      for (const [a, b] of set.conflicts) expect(cut.buffs.includes(a) && cut.buffs.includes(b)).toBe(false);
    }
    expect(ofKit({ searchLimit: 150 }).value, "a longer search finds at least as much").toBeGreaterThanOrEqual(ofKit({ searchLimit: 40 }).value);
    expect(() => ofKit({ searchLimit: 0 })).toThrow(RangeError);
    expect(() => ofKit({ searchLimit: 1.5 })).toThrow(RangeError);
  });
});

describe("the bound of the search for the buffs", () => {
  // The search cuts a branch when the best it could reach is no better than the best kit found, and works that bound out with the evaluator and a buff of its own, which the bundle does
  // not have. That buff needs an id that nothing the evaluator reads has. The ids of one spell line are consecutive (Divine Vigor 2584 and Valor of Marr 2585 in the real bundle), so a buff of
  // the set that is always on can have the id one above the largest optional one; the bound's buff would then take its place in the table the bound is worked out with.
  const kit = CASES[0].kit;
  const OPTIONAL = [1440, 1441, 1442, 1443, 1444, 1453];
  const NEXT = Math.max(...OPTIONAL) + 1;

  /** Six optional buffs of different kinds (three of them at most, two that exclude each other) for the own set, and the buff `always` among the ones that are always on. */
  function craft(always) {
    const made = structuredClone(bundle);
    const row = made.buffs.own;
    const vecs = {
      1440: { STR: 35, HP: 100 },
      1441: { AC: 60 },
      1442: { HP: 250, MANAREG: -4 },
      1443: { HPREG: 12, AC: 10 },
      1444: { STR: 20, AC: 20, HP: 60 },
    };
    for (const [id, vec] of Object.entries(vecs)) made.buff_table[id] = { name: `Invented buff ${id}`, vec };
    row.set.optional = [...OPTIONAL];
    row.set.conflicts = [[1440, 1444, ["the same line"]]];
    row.set.cliques = [[1440, 1444]];
    row.set.cardinality = 3;
    made.buff_table[String(NEXT)] = { name: "Invented always-on buff", vec: always.vec };
    row.set.always_on = [...row.set.always_on.filter((id) => !always.replaces?.includes(id)), NEXT];
    for (const [name, amount] of Object.entries(always.vec)) {
      row.buff_totals[name] = name === "HASTE" ? Math.max(row.buff_totals[name] ?? 0, amount) : (row.buff_totals[name] ?? 0) + amount; // (the profile's totals are those of the always-on buffs)
    }
    for (const id of always.replaces ?? []) {
      for (const [name, amount] of Object.entries(bundle.buff_table[String(id)].vec)) {
        if (name !== "HASTE") row.buff_totals[name] -= amount;
      }
    }
    return made;
  }

  /** The best value of every choice there is: at most three of the optional buffs, never both of the two that exclude each other, worked out with the buff set as the bundle has it. */
  function bestOfEvery(made, answer) {
    const read = readBundle(structuredClone(made));
    const profile = assembleProfile(read, AS_OF_THE_PAGE);
    const items = kit.map((ident) => (ident === null ? null : atTier(table.records.get(ident.slice(0, ident.lastIndexOf("@"))), Number(ident.slice(ident.lastIndexOf("@") + 1)), read)));
    const options = { setup: answer.setup, hasteAssumed: answer.hasteAssumed, monkBins: read.monk_bins ?? undefined, buffset: { set: read.buffs.own.set, table: read.buff_table } };
    let best = null;
    let tried = 0;
    const choose = (from, chosen) => {
      if (chosen.includes(1440) && chosen.includes(1444)) return;
      tried += 1;
      const worth = evaluate(profile, items, chosen, options).F;
      if (best === null || worth.compare(best) > 0) best = worth;
      if (chosen.length === 3) return;
      for (let i = from; i < OPTIONAL.length; i += 1) choose(i + 1, [...chosen, OPTIONAL[i]]);
    };
    choose(0, []);
    return { best, tried };
  }

  const CASES_OF_ALWAYS_ON = [
    ["with a large vector", { vec: { AC: 300, HP: 800, STR: 40 } }],
    ["that is the haste buff of the set, moved next to the optional ids", { vec: { HASTE: 25 }, replaces: [2585] }],
  ];

  it.each(CASES_OF_ALWAYS_ON)("is exact when a buff that is always on has the id next to the optional ones, %s", (_, always) => {
    const made = craft(always);
    expect(made.buffs.own.set.always_on).toContain(NEXT);
    expect(Math.max(...made.buffs.own.set.optional) + 1).toBe(NEXT);
    const answer = valueOfKit({ bundle: made, records: table.records, ...AS_OF_THE_PAGE, places: placesOf(kit) });
    const { best, tried } = bestOfEvery(made, answer);
    expect(tried).toBe(1 + 6 + 14 + 16); // (the empty choice, 6 of one, the 15 pairs less the 1 that names both buffs that exclude each other, the 20 triples less the 4 that do)
    expect(answer.F).toBe(best.toString());
    expect(answer.exact).toBe(true);
    for (const id of answer.buffs) expect(OPTIONAL).toContain(id);
    expect(answer.buffs.length).toBeLessThanOrEqual(3);
  }, HEAVY);

  it("is the same whatever the id of that buff is: the value does not depend on where the always-on buff stands among the ids", () => {
    const at = (id) => {
      const made = craft({ vec: { AC: 300, HP: 800, STR: 40 } });
      made.buff_table[String(id)] = made.buff_table[String(NEXT)];
      made.buffs.own.set.always_on = made.buffs.own.set.always_on.map((one) => (one === NEXT ? id : one));
      return valueOfKit({ bundle: made, records: table.records, ...AS_OF_THE_PAGE, places: placesOf(kit) });
    };
    const next = at(NEXT);
    for (const id of [NEXT + 1, NEXT + 7, 9000]) {
      const other = at(id);
      expect(other.F, String(id)).toBe(next.F);
      expect(other.exact, String(id)).toBe(true);
    }
  });
});

describe("what is left out of the value", () => {
  // the kit of the first reference case: slot 0 (Head) wears w90001, slot 11 and 12 (Fingers) wear w90026 (a lore item) and w90027, slot 15 (Feet) w90033 (Ogre and Troll only)
  const kit = CASES[0].kit;
  const without = (slotIndex) => placesOf(kit).filter((place) => place.slotIndex !== slotIndex);
  const valued = (places, over) => run({ places, ...over });

  it("is an item that does not fit its place: the item counts for nothing, and the answer says which place and why", () => {
    const wrong = [...placesOf(kit).filter((place) => place.slotIndex !== 4), { slotIndex: 4, key: "w90027", tier: 4 }]; // (a ring in the Neck place)
    const answer = valued(wrong);
    expect(answer.left).toEqual([{ slotIndex: 4, reason: "slot" }]);
    expect(answer.value).toBe(valued(without(4)).value);
    expect(answer.counted).toBe(without(4).length);
  });

  it("lets an item that has a place of the kit stand in an Any place, and one that has none not", () => {
    expect(valued([{ slotIndex: 18, key: "w90003", tier: 4 }]).left).toEqual([]); // (a head piece in an Any place)
    const records = new Map(table.records);
    records.set("w90999", { ...table.records.get("w90027"), id: 90999, name: "Quiver of Nothing in Particular", slots: ["AMMO"] });
    expect(run({ records, places: [{ slotIndex: 18, key: "w90999", tier: 4 }] }).left).toEqual([{ slotIndex: 18, reason: "slot" }]);
  });

  it("is an item that the trio's classes cannot use", () => {
    const answer = valued([{ slotIndex: 0, key: "w90040", tier: 4 }]); // (the Cap of the Archmage: Wizards only)
    expect(answer.left).toEqual([{ slotIndex: 0, reason: "class" }]);
    expect(answer.counted).toBe(0);
  });

  it("is an item that the race cannot use", () => {
    const answer = valued(placesOf(kit), { race: "HUM" }); // (the Sabatons of Might are for Ogres and Trolls)
    expect(answer.left).toEqual([{ slotIndex: 15, reason: "race" }]);
  });

  it("is an item that needs a deity when the page has none", () => {
    const answer = valued([{ slotIndex: 0, key: "w90004", tier: 4 }]); // (the Crown of the Tribunal)
    expect(answer.left).toEqual([{ slotIndex: 0, reason: "deity" }]);
    expect(valued([{ slotIndex: 0, key: "w90004", tier: 4 }], { deity: "The Tribunal" }).left).toEqual([]);
  });

  it("is the second copy of a lore item", () => {
    const places = [...without(12), { slotIndex: 12, key: "w90026", tier: 4 }]; // (the Band of the Stalwart in both Finger places)
    const answer = valued(places);
    expect(answer.left).toEqual([{ slotIndex: 12, reason: "lore" }]);
  });

  it("is an item that the item table does not have", () => {
    const answer = valued([{ slotIndex: 0, key: "w99999", tier: 4 }]);
    expect(answer.left).toEqual([{ slotIndex: 0, reason: "unknown" }]);
    expect(answer.counted).toBe(0);
  });

  it("leaves every place out of an empty kit, and values it at the naked value of the race", () => {
    const empty = valued([]);
    expect(empty.counted).toBe(0);
    expect(empty.left).toEqual([]);
    expect(empty.value).toBeLessThan(valued(placesOf(kit)).value);
  });
});

describe("what it refuses", () => {
  it("is a race, a role, a buff set or an evidence level that the bundle does not have", () => {
    expect(() => run({ race: "XXX" })).toThrow(BundleError);
    expect(() => run({ role: "wizardry" })).toThrow(BundleError);
    expect(() => run({ buffs: "everyone" })).toThrow(BundleError);
    expect(() => run({ evidence: "rumour" })).toThrow(BundleError);
  });

  it("is two items for one place", () => {
    expect(() => run({ places: [{ slotIndex: 0, key: "w90001", tier: 4 }, { slotIndex: 0, key: "w90003", tier: 4 }] })).toThrow(/place/i);
  });

  it("is a place outside the kit, a tier outside 0 to 10 and a bundle that is not one", () => {
    expect(() => run({ places: [{ slotIndex: 22, key: "w90001", tier: 4 }] })).toThrow();
    expect(() => run({ places: [{ slotIndex: -1, key: "w90001", tier: 4 }] })).toThrow();
    expect(() => run({ places: [{ slotIndex: 0, key: "w90001", tier: 11 }] })).toThrow();
    expect(() => run({ bundle: { version: 1 } })).toThrow(BundleError);
  });

  it("does not look anything up by a name that a link could choose in an object", () => {
    // the keys come from page ids, but the lookups are Maps whatever the key is
    const answer = run({ places: [{ slotIndex: 0, key: "__proto__", tier: 4 }, { slotIndex: 1, key: "constructor", tier: 4 }] });
    expect(answer.left).toEqual([
      { slotIndex: 0, reason: "unknown" },
      { slotIndex: 1, reason: "unknown" },
    ]);
  });
});

describe("the module", () => {
  it("is a script of its own, listed in the manifest, and the optimizer's client file does not carry it: it exports neither function and does not import the module", async () => {
    const client = await import("../pipeline/trioforge/site/static/engine/client.js");
    expect(client.valueOfKit).toBeUndefined();
    expect(client.loadKitBundle).toBeUndefined();
    const source = readFileSync(resolve(ROOT, "pipeline/trioforge/site/static/engine/client.js"), "utf8");
    expect(source).not.toMatch(/kitvalue/);
    expect(typeof valueOfKit).toBe("function");
    expect(typeof loadKitBundle).toBe("function");
  });

  it("imports nothing but the engine's own modules, and none of the worker's, the solver's or the client's", () => {
    const source = readFileSync(resolve(ROOT, "pipeline/trioforge/site/static/engine/kitvalue.js"), "utf8");
    const imported = [...source.matchAll(/^import .* from "(.+)";$/gm)].map((match) => match[1]);
    expect(imported.length).toBeGreaterThan(5);
    for (const name of imported) expect(name, name).toMatch(/^\.\/[a-z]+\.js$/);
    for (const name of ["./worker.js", "./client.js", "./solve.js", "./highs-data.js", "./path.js", "./scenario.js"]) expect(imported, name).not.toContain(name);
  });
});

describe("the bundle of the trio, fetched for the page", () => {
  const ORIGIN = "https://trioforge.test";
  const BASE = `${ORIGIN}/trio/pal-mnk-ber/`;
  const ask = (made, over = {}, net = siteFetch(made)) => ({ net, done: loadKitBundle({ manifest: made.manifest, trio: "pal-mnk-ber", level: 50, fetchImpl: net.fetchImpl, base: BASE, ...over }) });
  const paths = (net) => net.asked.map((url) => new URL(url).pathname);

  it("is fetched by the path of the manifest of the trio and the path that manifest lists for the level, and is the document the manifest lists", async () => {
    const made = makeSite();
    const { net, done } = ask(made);
    expect(await done).toEqual(JSON.parse(BUNDLE_BYTES.toString("utf8")));
    expect(paths(net)).toEqual([made.trioPath, made.bundlePath]);
  });

  it("asks for the manifest of the trio as the worker does, of this site only, with no credentials of another", async () => {
    const made = makeSite();
    const inits = [];
    const net = siteFetch(made, { serve: (url, init) => void inits.push(init) });
    await ask(made, {}, net).done;
    expect(inits[0]).toMatchObject({ credentials: "same-origin", cache: "no-cache" });
    expect(new Set(net.asked.map((url) => new URL(url).origin))).toEqual(new Set([ORIGIN]));
  });

  it("gives a bundle that the evaluator takes, and gets the value the reference gave", async () => {
    const row = KIT_VALUES.values.find((one) => one.kit === 0 && one.role === "balanced" && one.buffs === "own");
    const got = await ask(makeSite()).done;
    const kit = KITS[0];
    const answer = valueOfKit({ bundle: got, records: table.records, race: kit.race, role: row.role, buffs: row.buffs, evidence: kit.evidence, deity: kit.deity, places: placesOf(kit.kit) });
    expect(answer.F).toBe(row.F);
  });

  it("refuses a trio, or a level of a trio, that the manifest does not list, and fetches nothing", async () => {
    const made = makeSite();
    for (const over of [{ trio: "war-clr-pal" }, { level: 51 }, { trio: "" }]) {
      const { net, done } = ask(made, over);
      await expect(done, JSON.stringify(over)).rejects.toMatchObject({ code: "engine-load", message: "The site lists no data for this trio and level." });
      expect(net.asked).toEqual([]);
    }
  });

  it("refuses a bundle whose SHA-256 is not the one the manifest lists, before a byte of it is read", async () => {
    const { done } = ask(makeSite({ lie: { bundle: { sha256: "0".repeat(64) } } }));
    await expect(done).rejects.toMatchObject({ code: "engine-load", message: "The data of this trio is not the one the site lists (its checksum differs)." });
  });

  it("refuses a bundle of the wrong size, a manifest of the trio of another release and a server that answers with an error", async () => {
    await expect(ask(makeSite({ lie: { bundle: { bytes: 10 } } })).done).rejects.toMatchObject({ code: "engine-load" });
    const stale = makeSite();
    stale.files.set(stale.trioPath, new TextEncoder().encode(JSON.stringify({ ...stale.trioJson["pal-mnk-ber"], data_release: "data-2000-01-01" })));
    await expect(ask(stale).done).rejects.toMatchObject({ message: "The list of files for this trio is of another release than the site's." });
    const broken = makeSite();
    const net = siteFetch(broken, { serve: (url) => (new URL(url).pathname === broken.trioPath ? new Response("no", { status: 500 }) : undefined) });
    await expect(ask(broken, {}, net).done).rejects.toMatchObject({ message: "The list of files for this trio could not be loaded (500)." });
  });

  it("is refused when the bundle is not JSON, or the manifest of the trio is not what the site writes", async () => {
    const notJson = makeSite({ bundles: { "pal-mnk-ber": { 50: new TextEncoder().encode("this is not json") } } });
    await expect(ask(notJson).done).rejects.toMatchObject({ message: "The data of this trio is not what the site writes." });
    const garbled = makeSite();
    garbled.files.set(garbled.trioPath, new TextEncoder().encode("{not json"));
    await expect(ask(garbled).done).rejects.toMatchObject({ message: "The list of files for this trio is not what was expected." });
  });
});
