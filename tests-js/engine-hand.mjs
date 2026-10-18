// Hand-made profiles, items and buff sets for the tests of the pruning, the sessions and the farm path: the same small invented scenarios as the
// hand-made models of tests-js/engine-model.test.mjs (a Warrior, a Cleric and an Enchanter with 100 in every attribute), shared by the three files.
// Every name, race and item here is invented. Nothing here is read by the site.

import { CLASS_CODES } from "../pipeline/trioforge/site/static/engine/items.js";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";
import { clone, deepFreeze } from "./engine-cases.mjs";
import { SAMPLE } from "./engine-fixtures.mjs";

export const q = (numerator, denominator = 1) => new Rational(BigInt(numerator), BigInt(denominator));
export const NAKED = { STR: 100, STA: 100, AGI: 100, DEX: 100, WIS: 100, INT: 100, CHA: 100 };
export const POOLS = {
  HP: [{ cls: "WAR", base: 1500, fac: 5 }, { cls: "CLR", base: 1320, fac: 4.4 }, { cls: "ENC", base: 1200, fac: 4 }],
  MANA: [{ cls: "CLR", base: 900, fac: 4.5, stat: "WIS" }, { cls: "ENC", base: 900, fac: 4.5, stat: "INT" }],
  END: [{ cls: "WAR", base: 900, fac: 4.5 }, { cls: "CLR", base: 456, fac: 3.25 }, { cls: "ENC", base: 260, fac: 1.25 }],
};
/** The pools of a Paladin, a Monk and a Berserker: the only mana class is the Paladin, on WIS. */
export const PMB_POOLS = {
  HP: [{ cls: "PAL", base: 1440, fac: 4.8 }, { cls: "MNK", base: 1380, fac: 4.6 }, { cls: "BER", base: 1500, fac: 5 }],
  MANA: [{ cls: "PAL", base: 900, fac: 4.5, stat: "WIS" }],
  END: [{ cls: "PAL", base: 652, fac: 3.25 }, { cls: "MNK", base: 700, fac: 3.5 }, { cls: "BER", base: 900, fac: 4.5 }],
};

/** A profile like an evaluator's: it has no race, no deity and no spell haste (the builder reads the haste on offer from the buffs). */
export function profileWith(changes = {}) {
  return deepFreeze({
    level: 50,
    naked: { ...NAKED },
    weights: {},
    pools: clone(POOLS),
    buff_totals: {},
    haste_cap: 75,
    softcap: [0, 0],
    cs_pct: 0,
    pe_pct: 0,
    defense_cap: 0,
    monk: null,
    iksar_ac: 0,
    placement: { monk: "top", iksar: "top" },
    caps: { regen: { HP: 30, MANA: 15, END: 15 }, resist: 200 },
    bands: null,
    dw_factor: 1,
    ...clone(changes),
  });
}

/** An item as atTier gives it. */
export function gear(key, slots, more = {}) {
  const { stats = {}, sv = {}, haste = 0, weight10 = 0, lore = false, weapon = null, shield = false, classes = CLASS_CODES, deity = null, races = null, tier = 0 } = more;
  return deepFreeze({
    key,
    name: key,
    slots: [...slots].sort(),
    classes: [...classes],
    deity,
    lore,
    stats: Object.fromEntries(Object.entries(stats).filter(([, amount]) => amount !== 0)),
    sv,
    haste,
    weight10,
    weapon,
    is_shield: shield,
    tier,
    weight_known: true,
    races,
  });
}
export const oneHand = (dmg, delay, bonus = null) => ({ skill: "1H Slashing", dmg, delay, bonus, two_handed: false });
export const twoHand = (dmg, delay, bonus = null) => ({ skill: "2H Slashing", dmg, delay, bonus, two_handed: true });

/** A buff set as the bundle writes it, from `{id, ...components}` buffs. */
export function buffsetOf({ always = [], optional = [], conflicts = [], cliques, cardinality = null }) {
  const table = {};
  for (const { id, ...vec } of [...always, ...optional]) table[String(id)] = { name: `buff-${id}`, classes: {}, vec, source: "own" };
  const pairs = [...conflicts].map(([a, b]) => (a < b ? [a, b] : [b, a])).sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  return deepFreeze({
    set: {
      always_on: always.map(({ id }) => id).sort((a, b) => a - b),
      optional: optional.map(({ id }) => id).sort((a, b) => a - b),
      conflicts: pairs.map(([a, b]) => [a, b, ["test"]]),
      cliques: (cliques ?? pairs).map((clique) => [...clique]),
      cardinality,
      dropped: [],
    },
    table,
  });
}
export const buffOf = (id, vec = {}) => ({ id, ...vec });

/** The Monk bins of level 50 (the evaluator's listing in the committed sample) and the curve they belong to. */
export const MONK_BINS = deepFreeze(clone(SAMPLE.read("evaluate/profiles.json").monk_bins["50"]));
export const MONK_CURVE = Object.freeze(
  Object.fromEntries(["softcap_stones", "hardcap_stones", "full_bonus_ac"].map((name) => [name, Number(MONK_BINS.curve[name].split("/")[0])])),
);
