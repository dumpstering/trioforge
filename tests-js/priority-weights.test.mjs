// What a choice of priorities means for the optimizer (static/ui/priority-weights.js): the custom weights of a request, each stat's own weight in the role times the step (0, 0.5, 1, 2, 4), set
// as custom weights and nothing more, so that the one definition of how weights compose (weights_override, and its port static/engine/weights.js) does the rest: the derived weights follow their
// stat (the weapon damage follows attack, a regeneration its resource), a currency the trio cannot reach stays 0, and a stat left Normal is not set at all. The numbers are checked against that
// definition, on the bundle of the synthetic site fixture, and against the rules of the protocol that a request must satisfy (a custom weight has at most six significant digits).

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { isLegalWeightNumber } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { weightsOverride } from "../pipeline/trioforge/site/static/engine/weights.js";
import { STATS, STEPS } from "../pipeline/trioforge/site/static/priorities.js";
import { STEP_MULTIPLIERS, WEIGHTS_OF, allOff, countedOf, customOf, manaSource, normalizeOf, ratesText } from "../pipeline/trioforge/site/static/ui/priority-weights.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const bundle = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/results/pal-mnk-ber/engine-l50.json"), "utf8"));
const ROLES = Object.keys(bundle.roles);
const SCHOOLS = ["SV_FIRE", "SV_COLD", "SV_MAGIC", "SV_POISON", "SV_DISEASE"];
/** Every stat Normal except those given: `at({ac: "t"})`. */
const at = (steps) => STATS.map(([id]) => steps[id] ?? "n").join("");
const own = (role) => bundle.roles[role].weights;
const composed = (role, priorities, options = {}) => weightsOverride(bundle, own(role), { custom: customOf(own(role), priorities), manaReachable: true, ...options });

describe("the steps and the stats of the chunk are the page script's", () => {
  it("have the same five characters and the same eight stats, in the same order", () => {
    expect(Object.keys(STEP_MULTIPLIERS)).toEqual(STEPS.map(([character]) => character));
    expect(Object.values(STEP_MULTIPLIERS)).toEqual([0, 0.5, 1, 2, 4]);
    expect(Object.keys(WEIGHTS_OF)).toEqual(STATS.map(([id]) => id));
  });
});

describe("a step is the role's own weight times 0, 0.5, 1, 2 or 4, set as a custom weight", () => {
  it("sets nothing for a stat that is Normal, so that every stat Normal is the role's own weights, to the last digit", () => {
    for (const role of ROLES) {
      expect(customOf(own(role), at({}))).toEqual({});
      expect(composed(role, at({}))).toEqual(weightsOverride(bundle, own(role)));
      expect(composed(role, at({}))).toEqual(own(role));
    }
  });

  it("multiplies the weight of the stat by the step: Off 0, Low x0.5, High x2, Top x4", () => {
    for (const role of ROLES) {
      const base = own(role);
      for (const [character, multiplier] of Object.entries({ 0: 0, l: 0.5, h: 2, t: 4 })) {
        const custom = customOf(base, at({ ac: character }));
        expect(Object.keys(custom), `${role} ${character}`).toEqual(["AC"]);
        expect(custom.AC).toBeCloseTo(base.AC * multiplier, 5);
        expect(composed(role, at({ ac: character })).AC).toBe(custom.AC);
      }
    }
  });

  it("names the stats as the page does: hit points HP, armor class AC, mana MANA, attack ATK, dexterity DEX, haste HASTE, endurance END, and the five schools for resists", () => {
    const base = own("tank");
    const keysOf = (id) => Object.keys(customOf(base, at({ [id]: "t" })));
    expect(keysOf("hp")).toEqual(["HP"]);
    expect(keysOf("ac")).toEqual(["AC"]);
    expect(keysOf("mana")).toEqual(["MANA"]);
    expect(keysOf("atk")).toEqual(["ATK"]);
    expect(keysOf("dex")).toEqual(["DEX"]);
    expect(keysOf("haste")).toEqual(["HASTE"]);
    expect(keysOf("end")).toEqual(["END"]);
    expect(keysOf("resists")).toEqual(SCHOOLS);
  });

  it("makes hit points Top raise the hit point regeneration with it, as the composition does: the regeneration follows the weight of its resource", () => {
    for (const role of ROLES) {
      const base = own(role);
      const got = composed(role, at({ hp: "t" }));
      expect(got.HP).toBeCloseTo(base.HP * 4, 5);
      expect(got.HPREG / base.HPREG).toBeCloseTo(4, 5);
      expect(got.MANAREG).toBe(base.MANAREG); // (a stat that was not asked for does not move)
      expect(got.ENDREG).toBe(base.ENDREG);
      expect(got.ATK).toBe(base.ATK);
    }
  });

  it("makes attack Top raise the weapon damage with it, as the composition does: the damage weight follows the attack weight", () => {
    for (const role of ROLES) {
      const base = own(role);
      const got = composed(role, at({ atk: "t" }));
      expect(got.ATK).toBeCloseTo(base.ATK * 4, 5);
      expect(got.DMG / base.DMG).toBeCloseTo(4, 5);
      expect(got.HASTE, "haste is a stat of its own").toBe(base.HASTE);
      const half = composed(role, at({ atk: "l" }));
      expect(half.DMG / base.DMG).toBeCloseTo(0.5, 5);
      expect(composed(role, at({ atk: "0" })).DMG).toBe(0);
    }
  });

  it("makes endurance and mana take their regeneration with them, and dexterity, haste and armor class take nothing", () => {
    const base = own("tank");
    expect(composed("tank", at({ end: "h" })).ENDREG / base.ENDREG).toBeCloseTo(2, 5);
    expect(composed("tank", at({ mana: "h" })).MANAREG / base.MANAREG).toBeCloseTo(2, 5);
    const dex = composed("tank", at({ dex: "t", haste: "t", ac: "t" }));
    for (const key of ["HPREG", "MANAREG", "ENDREG", "DMG", "HP", "MANA", "END", "ATK"]) expect(dex[key], key).toBe(base[key]);
  });

  it("leaves a mana weight of 0 at 0 under any step: a trio with no mana pool has no mana to gain, and Top on it is no more than Normal", () => {
    const base = { ...own("tank"), MANA: 0, MANAREG: 0 };
    for (const character of ["0", "l", "n", "h", "t"]) {
      const custom = customOf(base, at({ mana: character }));
      expect(custom.MANA ?? 0).toBe(0);
      const got = weightsOverride(bundle, base, { custom, manaReachable: false });
      expect(got.MANA, character).toBe(0);
      expect(got.MANAREG, character).toBe(0);
    }
    // and for a trio that has a pool the composition gives the step: the same priorities on the same weights are not a no-op there
    expect(composed("tank", at({ mana: "t" })).MANA).toBeCloseTo(own("tank").MANA * 4, 5);
  });

  it("sets the five schools to the step times each school's own weight, so that unequal schools keep their proportions", () => {
    const base = { ...own("tank"), SV_FIRE: 0.3, SV_COLD: 0.6, SV_MAGIC: 0.15, SV_POISON: 0.3, SV_DISEASE: 0 };
    const custom = customOf(base, at({ resists: "h" }));
    expect(custom, "a school the role gives no weight is not sent: there is nothing to scale").toEqual({ SV_FIRE: 0.6, SV_COLD: 1.2, SV_MAGIC: 0.3, SV_POISON: 0.6 });
  });

  it("never sends a stat the build does not weigh, at any step: a weight of 0 times a step is 0, which the role has already", () => {
    const base = { ...own("tank"), HASTE: 0, MANA: 0, MANAREG: 0 };
    for (const character of ["0", "l", "h", "t"]) {
      expect(customOf(base, at({ haste: character, mana: character })), character).toEqual({});
    }
    expect(customOf(base, at({ haste: "t", ac: "h" }))).toEqual({ AC: base.AC * 2 });
  });

  it("combines: several stats at once, each by its own step, and the rest as they were", () => {
    const base = own("tank");
    const got = composed("tank", at({ ac: "t", resists: "0", haste: "l", end: "h" }));
    expect(got.AC).toBeCloseTo(base.AC * 4, 5);
    for (const key of SCHOOLS) expect(got[key], key).toBe(0);
    expect(got.HASTE).toBeCloseTo(base.HASTE / 2, 5);
    expect(got.END).toBeCloseTo(base.END * 2, 5);
    expect(got.HP).toBe(base.HP);
    expect(got.DEX).toBe(base.DEX);
  });

  it("is a weight that the protocol takes, for every role, stat and step: zero, or at most six significant digits and at least 0.000001, and under the largest custom weight", () => {
    for (const role of ROLES) {
      for (const [id] of STATS) {
        for (const [character] of STEPS) {
          const custom = customOf(own(role), at({ [id]: character }));
          for (const [key, value] of Object.entries(custom)) {
            expect(isLegalWeightNumber(value), `${role} ${id} ${character} ${key} ${value}`).toBe(true);
            expect(value).toBeLessThanOrEqual(1000);
          }
        }
      }
    }
  });

  it("rounds a weight with more digits than the protocol takes to six significant digits, and no more: a mean of three weights, times four", () => {
    const base = { ...own("tank"), HP: 7 / 6 };
    const custom = customOf(base, at({ hp: "t" }));
    expect(custom.HP).toBe(4.66667);
    expect(isLegalWeightNumber(custom.HP)).toBe(true);
    expect(composed("tank", at({ hp: "t" })).HP).toBeCloseTo(own("tank").HP * 4, 5);
  });

  it("does not take a weight the role does not have: a key that is not in the role's weights is not set", () => {
    expect(customOf({ HP: 1 }, at({ hp: "t", ac: "t", resists: "t" }))).toEqual({ HP: 4 });
  });
});

describe("the stats the build weighs", () => {
  const casterLike = { ...own("tank"), HASTE: 0 };
  const noPool = { ...own("tank"), MANA: 0, MANAREG: 0 };

  it("are every stat of the control that has a weight in the role: a stat of weight 0 is not counted, and resists are counted when any school has a weight", () => {
    expect(countedOf(own("tank"))).toEqual([true, true, true, true, true, true, true, true]);
    expect(countedOf(casterLike)).toEqual([true, true, true, true, true, false, true, true]);
    expect(countedOf(noPool)).toEqual([true, true, false, true, true, true, true, true]);
    const noResists = { ...own("tank"), SV_FIRE: 0, SV_COLD: 0, SV_MAGIC: 0, SV_POISON: 0, SV_DISEASE: 0 };
    expect(countedOf(noResists)[6]).toBe(false);
    expect(countedOf({ ...noResists, SV_COLD: 0.1 })[6]).toBe(true);
  });

  it("make the step of a stat that is not counted Normal, and leave every other character as it is", () => {
    expect(normalizeOf(casterLike, at({ haste: "t", ac: "h" }))).toBe(at({ ac: "h" }));
    expect(normalizeOf(noPool, at({ mana: "0", haste: "l" }))).toBe(at({ haste: "l" }));
    expect(normalizeOf(own("tank"), at({ haste: "t", mana: "0" }))).toBe(at({ haste: "t", mana: "0" }));
    expect(normalizeOf(casterLike, at({}))).toBe(at({}));
  });

  it("are all at nothing when every stat is Off or not counted: the only weight left is charisma, which the control does not offer", () => {
    expect(allOff(own("tank"), "00000000")).toBe(true);
    expect(allOff(own("tank"), "0n000000")).toBe(false);
    expect(allOff(own("tank"), "nnnnnnnn")).toBe(false);
    expect(allOff(casterLike, "000000n0"), "resists are counted and Normal").toBe(false);
    expect(allOff(casterLike, "0000n000"), "dexterity is counted and is Normal").toBe(false);
    expect(allOff(casterLike, "00000n00"), "haste is not counted: its Normal is nothing, and every stat that is counted is Off").toBe(true);
    expect(allOff(noPool, "00n00000")).toBe(true);
  });

  it("leave charisma its own weight: the control does not offer it, nothing here sets it, and every step Off leaves it standing", () => {
    const got = composed("tank", "00000000");
    expect(got.CHA).toBe(own("tank").CHA);
    for (const key of ["HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", ...SCHOOLS]) expect(got[key], key).toBe(0);
  });
});

describe("the words for the rates of a kit", () => {
  const rates = { STA: 8.0157, STR: 3.8541675, WIS: 5.625, INT: 0, AC: 1.2375, DEX: 0.45, MANA: 0.5, END: 0.4, HASTE: 2.25, resist: 0.3 };
  const all = { casting: ["WIS"], mana: true, haste: true, steps: false };
  it("say each rate to one decimal under ten and as a whole number from ten, in the order of the stats of the kit, and one resist", () => {
    expect(ratesText({ rates, exact: true, ...all })).toBe(
      "A point more on this kit is worth about: stamina 8, strength 3.9, WIS 5.6, armor class 1.2, dexterity 0.5, haste 2.3, maximum mana 0.5, endurance 0.4, one resist 0.3 (hit points of kit value). Haste counts the best single piece, so its figure is for one more point on that piece.",
    );
    expect(ratesText({ rates: { ...rates, STA: 12.4, STR: 0, AC: 0.04, resist: 0 }, exact: true, ...all })).toContain("stamina 12, strength 0, WIS 5.6, armor class under 0.1,");
  });

  it("show WIS and INT apart and only the casting stats the trio has: a WIS trio has no INT figure, an INT trio no WIS, a trio with no mana pool neither and no mana figure", () => {
    const wis = ratesText({ rates, exact: true, ...all });
    expect(wis).toContain("WIS 5.6");
    expect(wis).not.toContain("INT");
    const int = ratesText({ rates: { ...rates, INT: 7.2 }, exact: true, ...all, casting: ["INT"] });
    expect(int).toContain("INT 7.2");
    expect(int).not.toContain("WIS");
    const both = ratesText({ rates: { ...rates, INT: 7.2 }, exact: true, ...all, casting: ["WIS", "INT"] });
    expect(both).toContain("WIS 5.6, INT 7.2, armor class");
    const none = ratesText({ rates, exact: true, ...all, casting: [], mana: false });
    for (const word of ["WIS", "INT", "mana"]) expect(none, word).not.toContain(word);
  });

  it("say where the mana of the trio comes from, from its classes' pools and the two pools the rules count: one stat and its pools, or two stats", () => {
    expect(manaSource([])).toBe("");
    expect(manaSource(["INT", "INT"])).toBe("Mana here comes from INT (2 pools).");
    expect(manaSource(["WIS"])).toBe("Mana here comes from WIS (1 pool).");
    expect(manaSource(["WIS", "INT"])).toBe("Mana here comes from WIS and INT (1 pool each).");
    expect(manaSource(["INT", "WIS"])).toBe("Mana here comes from WIS and INT (1 pool each).");
    expect(manaSource(["WIS", "WIS", "INT"])).toBe("Mana here comes from WIS and INT (the two largest of 3 pools count).");
    expect(manaSource(["WIS", "WIS", "WIS"])).toBe("Mana here comes from WIS (2 pools).");
    expect(manaSource(["STR", null, undefined])).toBe(""); // (a pool of no mana stat says nothing)
  });

  it("put that line after the rates when the build weighs mana, and leave it out when it does not or the pools are not given", () => {
    const text = ratesText({ rates, exact: true, ...all, pools: ["WIS", "INT"] });
    expect(text).toContain(" Mana here comes from WIS and INT (1 pool each).");
    expect(text.indexOf("Mana here comes")).toBeGreaterThan(text.indexOf("one resist"));
    expect(ratesText({ rates, exact: true, ...all, mana: false, pools: ["WIS", "INT"] })).not.toContain("Mana here");
    expect(ratesText({ rates, exact: true, ...all })).not.toContain("Mana here"); // (no pools given: the line as it was)
  });

  it("leave out the haste of a build that gives haste no weight, and the sentence about the best piece with it", () => {
    const text = ratesText({ rates, exact: true, ...all, haste: false });
    expect(text).not.toContain("haste");
    expect(text).not.toContain("Haste counts");
  });

  it("call the unit hit points of kit value while every step is Normal and points of this build's score when a step is set: with a step set no stat is the unit", () => {
    expect(ratesText({ rates, exact: true, ...all })).toContain("(hit points of kit value)");
    const set = ratesText({ rates, exact: true, ...all, steps: true });
    expect(set).toContain("(points of this build's score)");
    expect(set).not.toContain("hit point");
  });

  it("say so when the best buffs of the kit were not searched out completely", () => {
    expect(ratesText({ rates, exact: false, ...all })).toContain("The best buffs were not searched out completely");
  });
});
