import { describe, expect, it } from "vitest";
import {
  CLASS_CODES,
  ITEM_DEFAULTS,
  ItemError,
  REGEN_KEYS,
  STAT_KEYS,
  SV_KEYS,
  atTier,
} from "../pipeline/trioforge/site/static/engine/items.js";
import { BundleError, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { mulberry32 } from "./engine-models.mjs";
import { SAMPLE, describeFull } from "./engine-fixtures.mjs";
import { expectWithin, stopwatch } from "./timing.mjs";

// An item of the item table at an upgrade tier, 0 to 10: the stat rule, flat haste and regen, the weight, the weapon damage at 5% or 10% a tier.
// atTier is a port of at_tier in pipeline/trioforge/model/items.py with whole-number arithmetic only. It reads a record of the item table
// (items.json: only the fields that differ from the defaults of the table) under the rules of a bundle (`tier_rules`, `weapon_rules`), and
// it is held to the item at every tier and both weapon rates that Python wrote (items/vectors-NN.json) for every wearable of the table.

const BUNDLE = "profiles/pal-mnk-ber-l50.bundle.json";
const RULES = readBundle(SAMPLE.read(BUNDLE));
const clone = (value) => JSON.parse(JSON.stringify(value));

/** An invented record: a ring that nobody can find in a catalog. */
function record(changes = {}) {
  return { id: 9001, name: "Ring of Invented Tests", slots: ["FINGER"], weight10: 1, tier_rule: "drop", ...changes };
}
const sword = (skill = "1H Slashing", dmg = 20, delay = 30, bonus = null) => ({ skill, dmg, delay, bonus });

/** The rules of the sample with some values changed. */
function rulesWith(change) {
  const raw = clone(SAMPLE.read(BUNDLE));
  change(raw);
  return raw;
}

// ---- the item at every tier, as Python wrote it -------------------------------------------------------------------------------

function parityTests(set) {
  const table = set.read("items/table.json");
  const records = new Map(table.items.map((row) => [row.key ?? `w${row.id}`, row]));
  const chunks = set.paths("item-vectors");

  it("has the records and the vectors of the same items", () => {
    expect(chunks.length).toBeGreaterThan(0);
    const keys = chunks.flatMap((path) => set.read(path).items.map((entry) => entry.key));
    expect(keys).toEqual([...records.keys()]);
    expect(table.count).toBe(keys.length);
  });

  it("has the defaults the port knows", () => {
    expect(table.defaults).toEqual(ITEM_DEFAULTS);
  });

  for (const path of chunks) {
    it(`${path}: every item at every tier and both weapon rates is what Python made of it`, () => {
      const chunk = set.read(path);
      const { stat_order: statOrder, sv_order: svOrder } = chunk;
      expect(statOrder).toEqual([...STAT_KEYS, ...REGEN_KEYS]);
      expect(svOrder).toEqual([...SV_KEYS]);
      const wrong = [];
      let checked = 0;
      for (const entry of chunk.items) {
        const raw = records.get(entry.key);
        for (let tier = 0; tier <= 10; tier += 1) {
          for (const pct of chunk.weapon_pcts) {
            const item = atTier(raw, tier, RULES, { weaponPct: pct });
            checked += 1;
            const dense = [...statOrder.map((name) => item.stats[name] ?? 0), ...svOrder.map((name) => item.sv[name] ?? 0), item.haste, item.weight10];
            const fixed = entry.fixed;
            const same =
              JSON.stringify(dense) === JSON.stringify(entry.tiers[tier]) &&
              item.key === entry.key &&
              item.tier === tier &&
              item.name === fixed.name &&
              JSON.stringify(item.slots) === JSON.stringify(fixed.slots) &&
              JSON.stringify(item.classes) === JSON.stringify(fixed.classes) &&
              JSON.stringify(item.deity) === JSON.stringify(fixed.deity) &&
              item.lore === fixed.lore &&
              item.is_shield === fixed.is_shield &&
              JSON.stringify(item.races) === JSON.stringify(fixed.races) &&
              item.weight_known === fixed.weight_known &&
              (fixed.weapon === null
                ? item.weapon === null && entry.damage === null
                : item.weapon !== null &&
                  item.weapon.skill === fixed.weapon.skill &&
                  item.weapon.delay === fixed.weapon.delay &&
                  item.weapon.bonus === fixed.weapon.bonus &&
                  item.weapon.two_handed === fixed.weapon.two_handed &&
                  item.weapon.dmg === entry.damage[String(pct)][tier]);
            if (!same) wrong.push({ key: entry.key, tier, pct, item, want: entry.tiers[tier] });
            if (wrong.length >= 3) break;
          }
          if (wrong.length >= 3) break;
        }
        if (wrong.length >= 3) break;
      }
      expect(wrong).toEqual([]);
      expect(checked).toBe(chunk.items.length * 11 * chunk.weapon_pcts.length);
    });
  }

  it("never keeps a stat of zero, and lists the stats in the order of the model", () => {
    const order = [...STAT_KEYS, ...REGEN_KEYS];
    for (const raw of table.items) {
      const item = atTier(raw, 7, RULES);
      expect(Object.values(item.stats).every((value) => value !== 0)).toBe(true);
      expect(Object.values(item.sv).every((value) => value !== 0)).toBe(true);
      const names = Object.keys(item.stats);
      expect(names).toEqual(order.filter((name) => names.includes(name)));
      const schools = Object.keys(item.sv);
      expect(schools).toEqual(SV_KEYS.filter((name) => schools.includes(name)));
    }
  });
}

describe("the committed sample", () => parityTests(SAMPLE));
describeFull("the full set", (full) => parityTests(full));

// ---- the numbers, written out by hand ------------------------------------------------------------------------------------------

describe("the stat rule", () => {
  it("is base + max(n, base * n // 10): AC 20 is 20, 28 and 40 at +0, +4 and +10", () => {
    for (const [tier, want] of [[0, 20], [4, 28], [10, 40]]) expect(atTier(record({ stats: { AC: 20 } }), tier, RULES).stats).toEqual({ AC: want });
  });

  it("gives a small base at least one point a tier", () => {
    expect(atTier(record({ stats: { AC: 3 } }), 4, RULES).stats).toEqual({ AC: 7 });
  });

  it("does not scale attack at all (T1, the game client's own calculation): ATK is its +0 value at every tier, and a stat beside it is scaled", () => {
    for (const tier of [0, 1, 2, 4, 10]) {
      const item = atTier(record({ stats: { ATK: 10, STR: 10, AC: 3 } }), tier, RULES);
      expect(item.stats.ATK, `+${tier}`).toBe(10);
      expect(item.stats.STR, `+${tier}`).toBe(10 + Math.max(tier, Math.floor((10 * tier) / 10)));
      expect(item.stats.AC, `+${tier}`).toBe(3 + tier);
      expect(atTier(record({ stats: { ATK: 100 } }), tier, RULES).stats).toEqual({ ATK: 100 });
    }
  });

  it("takes the stats that do not tier from the rules (tier_rules.unscaled_stats), as the Python model does", () => {
    const none = rulesWith((raw) => (raw.tier_rules.unscaled_stats = []));
    expect(atTier(record({ stats: { ATK: 10 } }), 4, none).stats).toEqual({ ATK: 14 });
    const both = rulesWith((raw) => (raw.tier_rules.unscaled_stats = ["ATK", "STR"]));
    expect(atTier(record({ stats: { ATK: 10, STR: 10 } }), 4, both).stats).toEqual({ ATK: 10, STR: 10 });
  });

  it("rounds the tenth of the base down", () => {
    // 19 * 4 // 10 = 7 is above the +4 minimum; 9 * 4 // 10 = 3 is below it
    expect(atTier(record({ stats: { AC: 19 } }), 4, RULES).stats.AC).toBe(19 + 7);
    expect(atTier(record({ stats: { AC: 9 } }), 4, RULES).stats.AC).toBe(9 + 4);
  });

  it("moves a negative stat toward zero by the amount a positive one would grow and never past zero (T6), and drops a zero stat", () => {
    expect(atTier(record({ stats: { STR: -3, STA: 10 } }), 10, RULES).stats).toEqual({ STA: 20 }); // (-3 is gone at +10)
    expect(atTier(record({ stats: { AC: 0, STR: 5 } }), 1, RULES).stats).toEqual({ STR: 6 });
    for (const [base, tier, want] of [[-2, 0, -2], [-2, 1, -1], [-2, 2, 0], [-2, 4, 0], [-20, 4, -12], [-5, 4, -1], [-1, 1, 0], [-100, 10, 0], [-30, 1, -27], [-9, 3, -6], [-15, 3, -11], [-40, 10, 0]]) {
      expect(atTier(record({ stats: { STR: base } }), tier, RULES).stats.STR ?? 0, `${base} at +${tier}`).toBe(want);
    }
  });

  it("applies to the resists as well", () => {
    expect(atTier(record({ sv: { FIRE: 20, COLD: 3, MAGIC: -4, POISON: -20 } }), 4, RULES).sv).toEqual({ FIRE: 28, COLD: 7, POISON: -12 }); // (T6: -4 is gone at +4, -20 is -12)
  });

  it("adds a flat point a tier of worn haste and of each regen, when the base is above zero", () => {
    const vec = atTier(record({ stats: { HASTE: 41, AC: 5 } }), 5, RULES);
    expect(vec.haste).toBe(46);
    expect(vec.stats).toEqual({ AC: 10 });
    expect(atTier(record({ stats: { AC: 5 } }), 7, RULES).haste).toBe(0);
    expect(atTier(record({ stats: { HASTE: -5 } }), 6, RULES).haste).toBe(-5);
    for (const key of REGEN_KEYS) {
      expect(atTier(record({ stats: { [key]: 2 } }), 10, RULES).stats).toEqual({ [key]: 12 });
      expect(atTier(record({ stats: { [key]: 2 } }), 0, RULES).stats).toEqual({ [key]: 2 });
    }
  });

  it("follows the rules of the bundle for haste and regen, not a constant", () => {
    const rules = rulesWith((raw) => {
      raw.tier_rules.haste_per_tier = "2/1";
      raw.tier_rules.regen_per_tier = "3/1";
    });
    const vec = atTier(record({ stats: { HASTE: 10, HPREG: 1 } }), 4, rules);
    expect(vec.haste).toBe(18);
    expect(vec.stats.HPREG).toBe(13);
  });
});

describe("the weight", () => {
  it("falls nine percent of the base a tier, rounded down and with no minimum step, to a floor of a tenth of a stone", () => {
    for (const [weight10, tier, want] of [[100, 0, 100], [100, 4, 64], [100, 10, 10], [30, 10, 3], [19, 1, 18], [10, 4, 7], [2, 5, 2], [10, 10, 1], [1, 10, 1]]) {
      expect(atTier(record({ weight10 }), tier, RULES).weight10, `${weight10} at +${tier}`).toBe(want);
    }
    expect(atTier(record({ weight10: 73 }), 4, RULES).weight10).toBe(47); // 73 * 9 * 4 // 100 = 26
    expect(atTier(record({ weight10: 15 }), 4, RULES).weight10).toBe(10);
    expect(atTier(record({ weight10: 15 }), 1, RULES).weight10).toBe(14);
  });

  it("keeps a weightless item weightless and counts an unknown weight as one stone at every tier, flagged", () => {
    const zero = atTier(record({ weight10: 0 }), 6, RULES);
    expect([zero.weight10, zero.weight_known]).toEqual([0, true]);
    for (let tier = 0; tier <= 10; tier += 1) {
      const unknown = atTier(record({ weight10: null }), tier, RULES);
      expect([unknown.weight10, unknown.weight_known]).toEqual([10, false]);
    }
    expect(atTier(record({ weight10: 25 }), 0, RULES).weight_known).toBe(true);
  });

  it("takes a weight below zero for none", () => {
    expect(atTier(record({ weight10: -4 }), 3, RULES)).toMatchObject({ weight10: 0, weight_known: true });
  });
});

describe("weapons", () => {
  const primary = (weapon) => record({ slots: ["PRIMARY"], weapon });

  it("rises ten percent a tier of the damage, rounded down, with no minimum step, unless the rules say five", () => {
    expect(atTier(primary(sword("1H Slashing", 20, 30, 7)), 4, RULES).weapon).toEqual({ skill: "1H Slashing", dmg: 28, delay: 30, bonus: 7, two_handed: false });
    expect(atTier(primary(sword("1H Slashing", 3)), 4, RULES).weapon.dmg).toBe(4); // (7 with a point a tier)
    for (const [dmg, tier, want] of [[20, 0, 20], [20, 1, 22], [45, 3, 58], [45, 10, 90], [100, 10, 200]]) {
      expect(atTier(primary(sword("1H Slashing", dmg)), tier, RULES).weapon.dmg, `${dmg} at +${tier}`).toBe(want);
    }
    const five = rulesWith((raw) => {
      raw.weapon_rules.damage_pct = "5/1";
    });
    expect(atTier(primary(sword("1H Slashing", 20)), 4, five).weapon.dmg).toBe(24);
    // the option does the same without a second rules object
    expect(atTier(primary(sword("1H Slashing", 20)), 4, RULES, { weaponPct: 5 }).weapon.dmg).toBe(24);
    expect(atTier(primary(sword("1H Slashing", 20)), 4, five, { weaponPct: 10 }).weapon.dmg).toBe(28);
  });

  it("takes the rate of the rules when none is given, and null is none", () => {
    const five = rulesWith((raw) => {
      raw.weapon_rules.damage_pct = "5/1";
    });
    for (let tier = 0; tier <= 10; tier += 1) {
      const weapon = primary(sword("2H Blunt", 37, 40, 3));
      expect(atTier(weapon, tier, RULES)).toEqual(atTier(weapon, tier, RULES, { weaponPct: 10 }));
      expect(atTier(weapon, tier, RULES, { weaponPct: null })).toEqual(atTier(weapon, tier, RULES, { weaponPct: 10 }));
      expect(atTier(weapon, tier, RULES, {})).toEqual(atTier(weapon, tier, RULES, { weaponPct: 10 }));
      expect(atTier(weapon, tier, five)).toEqual(atTier(weapon, tier, RULES, { weaponPct: 5 }));
    }
  });

  it("never changes the delay or the listed bonus, and leaves a damage of zero at zero", () => {
    for (const tier of [0, 5, 10]) {
      const weapon = atTier(primary(sword("1H Piercing", 30, 44, 20)), tier, RULES).weapon;
      expect([weapon.delay, weapon.bonus]).toEqual([44, 20]);
    }
    expect(atTier(primary(sword("1H Piercing", 30, 44, null)), 3, RULES).weapon.bonus).toBeNull();
    expect(atTier(primary(sword("1H Piercing", 0, 44)), 9, RULES).weapon.dmg).toBe(0);
  });

  it("is two-handed by its skill", () => {
    for (const [skill, two] of [["2H Slashing", true], ["2H Blunt", true], ["2H Piercing", true], ["Two Hand Slashing", true], ["Two-Handed Blunt", true], ["1H Slashing", false], ["Piercing", false], ["Hand to Hand", false], [null, false], ["", false]]) {
      const weapon = atTier(primary(sword(skill)), 0, RULES).weapon;
      expect(weapon.two_handed, String(skill)).toBe(two);
      expect(weapon.skill).toBe(skill);
    }
  });

  it("is none without both a damage and a delay", () => {
    expect(atTier(record(), 0, RULES).weapon).toBeNull();
    expect(atTier(primary({ skill: "Brass Instruments", dmg: null, delay: null, bonus: null }), 4, RULES).weapon).toBeNull();
    expect(atTier(primary({ skill: "1H Blunt", dmg: 12, delay: null, bonus: null }), 4, RULES).weapon).toBeNull();
    expect(atTier(primary({ skill: "1H Blunt", dmg: null, delay: 30, bonus: null }), 4, RULES).weapon).toBeNull();
  });
});

describe("shields", () => {
  it("are the items of the off hand that the table types as a shield, in any case, and have no weapon", () => {
    for (const type of ["Shield", "shield", "SHIELD"]) {
      const shield = atTier(record({ slots: ["SECONDARY"], item_type: type, item_type_source: "x", stats: { AC: 35 } }), 0, RULES);
      expect(shield.is_shield, type).toBe(true);
      expect(shield.weapon).toBeNull();
    }
    const withDamage = atTier(record({ slots: ["SECONDARY"], item_type: "Shield", stats: { AC: 12 }, weapon: sword("1H Blunt", 3, 30) }), 0, RULES);
    expect(withDamage.is_shield).toBe(true);
    expect(withDamage.weapon).toBeNull();
  });

  it("are nothing else: not a skill, a slot, an armor class or another type", () => {
    for (const changes of [
      { slots: ["SECONDARY"], stats: { AC: 12 }, weapon: sword("Shield", 3, 30) },
      { slots: ["SECONDARY"], item_type: "Buckler", stats: { AC: 12 } },
      { slots: ["SECONDARY"], item_type: "Shield Augment", stats: { AC: 12 } },
      { slots: ["SECONDARY"], stats: { WIS: 5 } },
      { slots: ["PRIMARY", "SECONDARY"], stats: { AC: 3 } },
      { slots: ["CHEST"], stats: { AC: 30 } },
      { slots: ["PRIMARY"], item_type: "Shield", stats: { AC: 30 } },
    ]) {
      expect(atTier(record(changes), 2, RULES).is_shield, JSON.stringify(changes)).toBe(false);
    }
  });

  it("is a shield whatever else the slots list, as long as the off hand is there", () => {
    expect(atTier(record({ slots: ["PRIMARY", "SECONDARY"], item_type: "Shield" }), 0, RULES).is_shield).toBe(true);
  });
});

describe("who may wear it", () => {
  it("is every class, race and deity for an item whose record says nothing", () => {
    const item = atTier(record(), 0, RULES);
    expect(item.classes).toEqual([...CLASS_CODES]);
    expect(item.races).toBeNull();
    expect(item.deity).toBeNull();
    expect(item.lore).toBe(false);
  });

  it("has sixteen class codes, sorted", () => {
    expect(CLASS_CODES).toHaveLength(16);
    expect([...CLASS_CODES]).toEqual([...CLASS_CODES].sort());
    expect(new Set(CLASS_CODES).size).toBe(16);
  });

  it("takes the classes, the deities and the Lore flag of the record, sorted and without repeats", () => {
    const item = atTier(
      record({ id: 77, key: "r77", name: "Cloak of Invented Winds", slots: ["FACE", "BACK", "FACE"], classes: ["WAR", "PAL", "WAR"], deity: ["Tunare", "Karana"], lore: true }),
      3,
      RULES,
    );
    expect(item).toMatchObject({ key: "r77", name: "Cloak of Invented Winds", tier: 3, lore: true });
    expect(item.slots).toEqual(["BACK", "FACE"]);
    expect(item.classes).toEqual(["PAL", "WAR"]);
    expect(item.deity).toEqual(["Karana", "Tunare"]);
  });

  it("is every class when ALL is among them", () => {
    expect(atTier(record({ classes: ["ALL"] }), 0, RULES).classes).toEqual([...CLASS_CODES]);
    expect(atTier(record({ classes: ["WAR", "ALL"] }), 0, RULES).classes).toEqual([...CLASS_CODES]);
  });

  it("reads the races: none restriction for ALL in any case, the empty set for NONE, else the codes", () => {
    for (const [races, want] of [
      [["ALL"], null], [["all"], null], [["All"], null], [["HUM", "all"], null], [["all", "HUM", "ELF"], null], [["ALL", "ALL"], null],
      [[], []], [["HUM"], ["HUM"]], [["HUM", "ELF", "HEF", "HFL"], ["ELF", "HEF", "HFL", "HUM"]], [["HUM", "HUM"], ["HUM"]],
    ]) {
      expect(atTier(record({ races }), 0, RULES).races, JSON.stringify(races)).toEqual(want);
    }
    expect(atTier(record({ races: undefined }), 0, RULES).races).toBeNull();
    expect(atTier(record({ races: null }), 0, RULES).races).toBeNull();
  });

  it("refuses races that are not a list of texts", () => {
    for (const races of ["HUM", "ALL", "", ["HUM", 1], ["HUM", null], [["HUM"]], 5, true, {}, { HUM: 1 }]) {
      expect(() => atTier(record({ races }), 0, RULES), JSON.stringify(races)).toThrow(ItemError);
    }
    expect(() => atTier(record({ races: "HUM" }), 0, RULES)).toThrow(/r?w?9001.*races must be a list/);
    const holed = ["ELF", "HUM"];
    delete holed[1];
    expect(() => atTier(record({ races: holed }), 0, RULES)).toThrow(/races must be a list/);
  });
});

// ---- what comes back, and what is refused ---------------------------------------------------------------------------------------

describe("the result", () => {
  it("has the fields of ItemVec, in order, and cannot be changed", () => {
    const item = atTier(record({ stats: { AC: 20 }, weapon: sword() , slots: ["PRIMARY"] }), 4, RULES);
    expect(Object.keys(item)).toEqual([
      "key", "name", "slots", "classes", "deity", "lore", "stats", "sv", "haste", "weight10", "weapon", "is_shield", "tier", "weight_known", "races",
    ]);
    expect(item.key).toBe("w9001");
    for (const part of [item, item.stats, item.sv, item.slots, item.classes, item.weapon]) expect(Object.isFrozen(part)).toBe(true);
    expect(() => {
      item.stats.AC = 1;
    }).toThrow(TypeError);
    expect(() => {
      item.slots.push("HEAD");
    }).toThrow(TypeError);
  });

  it("leaves the record as it was, and does not share its parts", () => {
    const raw = record({ stats: { AC: 20, HASTE: 10 }, sv: { FIRE: 4 }, slots: ["PRIMARY"], weapon: sword(), classes: ["WAR"], races: ["HUM"] });
    const before = clone(raw);
    const item = atTier(raw, 9, RULES);
    expect(raw).toEqual(before);
    raw.slots.push("HEAD");
    raw.classes.push("PAL");
    raw.races.push("ELF");
    expect(item.slots).toEqual(["PRIMARY"]);
    expect(item.classes).toEqual(["WAR"]);
    expect(item.races).toEqual(["HUM"]);
  });

  it("takes a record that is frozen, and one made of objects that have no prototype", () => {
    const frozen = Object.freeze({ ...record({ stats: { AC: 20 } }), stats: Object.freeze({ AC: 20 }), slots: Object.freeze(["FINGER"]) });
    expect(atTier(frozen, 4, RULES).stats).toEqual({ AC: 28 });
    const bare = Object.assign(Object.create(null), record({ stats: Object.assign(Object.create(null), { AC: 20 }) }));
    expect(atTier(bare, 4, RULES).stats).toEqual({ AC: 28 });
  });

  it("names the item by its key when the record has one, and by w and its page id when it has not", () => {
    expect(atTier(record({ key: "r123" }), 0, RULES).key).toBe("r123");
    expect(atTier(record({ id: 77 }), 0, RULES).key).toBe("w77");
    expect(atTier(record({ id: null, key: "r5" }), 0, RULES).key).toBe("r5");
    expect(() => atTier(record({ id: null }), 0, RULES)).toThrow(ItemError);
    expect(() => atTier(record({ id: "77" }), 0, RULES)).toThrow(ItemError);
  });
});

describe("what is refused", () => {
  it("is a tier that is not a whole number from 0 to 10", () => {
    for (const tier of [-1, 11, 100, true, "4", null, undefined, 1.5, NaN, Infinity, 2 ** 40, [4], {}]) {
      expect(() => atTier(record({ stats: { AC: 1 } }), tier, RULES), String(tier)).toThrow(ItemError);
    }
    expect(atTier(record({ stats: { AC: 1 } }), 2.0, RULES).tier).toBe(2);
  });

  it("is a weapon rate other than 5 or 10", () => {
    for (const weaponPct of [7, 0, -5, 5.5, "5", true, NaN, Infinity, 50, [5], {}]) {
      expect(() => atTier(record(), 1, RULES, { weaponPct }), String(weaponPct)).toThrow(/weapon/);
    }
    expect(() => atTier(record(), 1, rulesWith((raw) => (raw.weapon_rules.damage_pct = "7/1")))).toThrow(BundleError);
  });

  it("is options that are not an object", () => {
    for (const bad of [5, "10", true, [10]]) expect(() => atTier(record(), 1, RULES, bad), String(bad)).toThrow(ItemError);
    expect(atTier(record({ stats: { AC: 20 } }), 4, RULES, null).stats).toEqual({ AC: 28 });
  });

  it("is an option that atTier does not read (a misspelt weaponPct would be ignored, and the item look right at the rate of the rules)", () => {
    const axe = record({ slots: ["PRIMARY"], weapon: sword("1H Slashing", 20) });
    expect(atTier(axe, 10, RULES).weapon.dmg).toBe(40); // 10 percent a tier
    expect(atTier(axe, 10, RULES, { weaponPct: 5 }).weapon.dmg).toBe(30);
    for (const key of ["weapon_pct", "weaponpct", "WeaponPct", "weaponPercent", "pct", "rate", "tier", "weaponPct "]) {
      const options = Object.defineProperty({}, key, { value: 10, enumerable: true });
      expect(() => atTier(axe, 10, RULES, options), JSON.stringify(key)).toThrow(ItemError);
      expect(() => atTier(axe, 10, RULES, options), JSON.stringify(key)).toThrow(/option/);
    }
    expect(() => atTier(axe, 10, RULES, { weapon_pct: 10 })).toThrow(/weapon_pct/);
    expect(() => atTier(axe, 10, RULES, { weaponPct: 10, rate: 1 })).toThrow(/rate/); // a right option does not excuse a wrong one
    expect(() => atTier(axe, 10, RULES, Object.defineProperty({}, "__proto__", { value: 10, enumerable: true }))).toThrow(ItemError);
    expect(() => atTier(axe, 10, RULES, { [`evil\n${"x".repeat(100)}`]: 1 })).toThrow(/\(\?\)/); // an odd key is not echoed back
  });

  it("is a record that is not an object, or lacks what the item needs", () => {
    for (const bad of [null, undefined, 5, "ring", [], true]) expect(() => atTier(bad, 0, RULES), String(bad)).toThrow(ItemError);
    for (const key of ["name", "slots", "weight10"]) {
      const broken = record();
      delete broken[key];
      expect(() => atTier(broken, 0, RULES), key).toThrow(ItemError);
    }
    expect(() => atTier(record({ name: 5 }), 0, RULES)).toThrow(ItemError);
    expect(() => atTier(record({ slots: "HEAD" }), 0, RULES)).toThrow(ItemError);
    expect(() => atTier(record({ slots: [1] }), 0, RULES)).toThrow(ItemError);
    expect(() => atTier(record({ classes: "ALL" }), 0, RULES)).toThrow(ItemError);
    expect(() => atTier(record({ classes: [5] }), 0, RULES)).toThrow(ItemError);
    expect(() => atTier(record({ deity: "Tunare" }), 0, RULES)).toThrow(ItemError);
    expect(() => atTier(record({ lore: "yes" }), 0, RULES)).toThrow(ItemError);
    expect(() => atTier(record({ item_type: 5 }), 0, RULES)).toThrow(ItemError);
  });

  it("is a stat or a resist that the model does not know, and a value that is not a whole number", () => {
    expect(() => atTier(record({ stats: { BOGUS: 3 } }), 1, RULES)).toThrow(/BOGUS/);
    expect(() => atTier(record({ sv: { ACID: 3 } }), 1, RULES)).toThrow(/ACID/);
    expect(() => atTier(record({ stats: Object.defineProperty({}, "__proto__", { value: 1, enumerable: true }) }), 1, RULES)).toThrow(ItemError);
    for (const value of [1.5, "5", NaN, Infinity, true, [], {}, 2 ** 31 * 1000]) {
      expect(() => atTier(record({ stats: { AC: value } }), 1, RULES), String(value)).toThrow(ItemError);
      expect(() => atTier(record({ sv: { FIRE: value } }), 1, RULES), String(value)).toThrow(ItemError);
      expect(() => atTier(record({ weight10: value }), 1, RULES), String(value)).toThrow(ItemError);
    }
    expect(() => atTier(record({ stats: [] }), 1, RULES)).toThrow(ItemError);
    expect(() => atTier(record({ sv: 5 }), 1, RULES)).toThrow(ItemError);
    expect(() => atTier(record({ stats: { AC: null } }), 1, RULES)).not.toThrow(); // null is none, as in Python
  });

  it("is a weapon that is not what the table writes", () => {
    for (const weapon of [5, "sword", [], { skill: 5, dmg: 1, delay: 1, bonus: null }, { skill: "x", dmg: 1.5, delay: 1, bonus: null }, { skill: "x", dmg: 1, delay: "1", bonus: null }, { skill: "x", dmg: 1, delay: 1, bonus: 1.5 }, { skill: "x", dmg: 1, delay: 1 }, { skill: "x", delay: 1, bonus: null }]) {
      expect(() => atTier(record({ slots: ["PRIMARY"], weapon }), 1, RULES), JSON.stringify(weapon)).toThrow(ItemError);
    }
  });

  it("is rules that are not the ones the port implements", () => {
    for (const [change, word] of [
      [(raw) => (raw.tier_rules.stat_rule = "base + n"), /stat_rule/],
      [(raw) => (raw.tier_rules.negatives_scale = true), /negatives_scale/],
      [(raw) => (raw.tier_rules.negatives_scale = "grow"), /negatives_scale/],
      [(raw) => (raw.tier_rules.negatives_scale = false), /negatives_scale/],
      [(raw) => (raw.tier_rules.unscaled_stats = ["HASTE"]), /unscaled_stats/],
      [(raw) => (raw.tier_rules.unscaled_stats = "ATK"), /unscaled_stats/],
      [(raw) => delete raw.tier_rules.unscaled_stats, /unscaled_stats/],
      [(raw) => (raw.tier_rules.weight_floor10 = "0/1"), /weight_floor10/],
      [(raw) => (raw.tier_rules.weight_floor10 = "3/2"), /weight_floor10/],
      [(raw) => (raw.tier_rules.haste_per_tier = "-1/1"), /haste_per_tier/],
      [(raw) => (raw.tier_rules.regen_per_tier = "1/2"), /regen_per_tier/],
      [(raw) => (raw.tier_rules.max_tier = "11/1"), /max_tier/],
      [(raw) => (raw.tier_rules.stat_divisor = "7/1"), /stat_divisor/],
      [(raw) => (raw.tier_rules.unknown_weight10 = "5/2"), /unknown_weight10/],
      [(raw) => (raw.weapon_rules.damage_pct = "7/1"), /damage_pct/],
      [(raw) => (raw.weapon_rules.damage_pct_choices = ["5/1"]), /damage_pct_choices/],
      [(raw) => (raw.weapon_rules.damage_rule = "dmg + n"), /damage_rule/],
    ]) {
      const bad = rulesWith(change);
      expect(() => atTier(record(), 1, bad), String(word)).toThrow(BundleError);
      expect(() => atTier(record(), 1, bad), String(word)).toThrow(word);
    }
    for (const bad of [null, undefined, {}, [], "rules", 5]) expect(() => atTier(record(), 1, bad), String(bad)).toThrow(BundleError);
  });

  it("is the same for rules read once and rules given raw each time", () => {
    const raw = clone(SAMPLE.read(BUNDLE));
    expect(atTier(record({ stats: { AC: 20 } }), 4, raw)).toEqual(atTier(record({ stats: { AC: 20 } }), 4, RULES));
  });
});

// ---- exactness -------------------------------------------------------------------------------------------------------------------

describe("exactness", () => {
  it("agrees with BigInt arithmetic on random stats, weights, damages, tiers and rates (a seeded series)", () => {
    const next = mulberry32(20261014);
    const below = (limit) => Math.floor(next() * limit);
    let checked = 0;
    for (let i = 0; i < 20_000; i += 1) {
      const magnitude = [10, 100, 10_000, 1_000_000, 1_000_000_000][below(5)];
      const base = below(magnitude) + 1;
      const negative = -(below(magnitude) + 1);
      const weight10 = below(magnitude) + 1;
      const dmg = below(magnitude) + 1;
      const tier = below(11);
      const pct = next() < 0.5 ? 5 : 10;
      const item = atTier(record({ stats: { AC: base, STR: negative }, weight10, slots: ["PRIMARY"], weapon: sword("1H Blunt", dmg) }), tier, RULES, { weaponPct: pct });
      const [b, n, w, d, p] = [BigInt(base), BigInt(tier), BigInt(weight10), BigInt(dmg), BigInt(pct)];
      const max = (x, y) => (x > y ? x : y);
      expect(BigInt(item.stats.AC)).toBe(b + max(n, (b * n) / 10n));
      const m = BigInt(-negative);
      expect(BigInt(item.stats.STR ?? 0)).toBe(-m + (m < max(n, (m * n) / 10n) ? m : max(n, (m * n) / 10n))); // (T6: toward zero by max(n, |b| n // 10), never past it)
      expect(BigInt(item.weight10)).toBe(max(1n, w - (w * 9n * n) / 100n)); // 9 percent of the base a tier, no minimum step
      expect(BigInt(item.weapon.dmg)).toBe(d + (d * n * p) / 100n); // and none for the damage either
      checked += 1;
    }
    expect(checked).toBe(20_000);
  });

  it("gives more at a higher tier for a base that is not negative, and at least a point a tier (a seeded series)", () => {
    const next = mulberry32(5);
    for (let i = 0; i < 2000; i += 1) {
      const base = Math.floor(next() * 500) + 1;
      let last = -Infinity;
      for (let tier = 0; tier <= 10; tier += 1) {
        const value = atTier(record({ stats: { AC: base } }), tier, RULES).stats.AC;
        expect(value).toBeGreaterThanOrEqual(base + tier);
        expect(value).toBeGreaterThan(last);
        last = value;
      }
    }
  });

  it("does not go through a double for the tenth of a base that a double cannot divide exactly", () => {
    // 999999999 * 10 // 10 in doubles is fine; the point is that the result is exact for the largest base the port takes
    const big = 1_000_000_000;
    expect(atTier(record({ stats: { AC: big } }), 10, RULES).stats.AC).toBe(big + big);
    expect(atTier(record({ stats: { AC: big - 1 } }), 9, RULES).stats.AC).toBe(big - 1 + Math.floor(((big - 1) * 9) / 10));
  });

  it("is fast enough to run on a whole table again and again (the rules are compiled once)", () => {
    const raw = record({ stats: { AC: 20, STA: 12 }, weight10: 25 });
    const watch = stopwatch();
    for (let i = 0; i < 20_000; i += 1) atTier(raw, i % 11, RULES, { weaponPct: 5 });
    expectWithin(watch.stop(), 5000, "20,000 calls of atTier");
  });
});

describe("the names it exports", () => {
  it("are the stats, regens and resists of the model, in its order, and the defaults of the table", () => {
    expect([...STAT_KEYS]).toEqual(["AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK"]);
    expect([...REGEN_KEYS]).toEqual(["HPREG", "MANAREG", "ENDREG"]);
    expect([...SV_KEYS]).toEqual(["FIRE", "COLD", "MAGIC", "POISON", "DISEASE", "CORRUPTION"]);
    expect(Object.isFrozen(STAT_KEYS) && Object.isFrozen(REGEN_KEYS) && Object.isFrozen(SV_KEYS) && Object.isFrozen(CLASS_CODES)).toBe(true);
    expect(Object.isFrozen(ITEM_DEFAULTS)).toBe(true);
  });

  it("match the item vectors of the bundle's constants", () => {
    const constants = RULES.constants;
    expect(constants.item_stat_order).toEqual([...STAT_KEYS, ...REGEN_KEYS]);
    expect(constants.sv_keys).toEqual([...SV_KEYS]);
  });
});
