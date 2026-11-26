// @vitest-environment jsdom
//
// What a click, a worn effect or a proc says it does (static/ui/exalt.js `meaning`): one sentence composed from the category, the magnitude, the unit, the kind, the proc rate and the cast
// level of its row in effects.json. The table holds each category's words as literal text, so that a change of a word is a change of this table and is read as one (the other tests of the
// section compare the page with a function's own output). Written for Part L, L10.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { meaning } from "../pipeline/trioforge/site/static/ui/exalt.js";

// [category, magnitude, what the sentence says]; a category that says no number leaves the magnitude out.
const BY_CATEGORY = [
  ["damage", 120, "120 damage"],
  ["lifetap", 45.5, "45.5 damage, and it heals you"],
  ["dot", 300, "300 damage over time"],
  ["heal", 250, "250 hit points healed"],
  ["heal_over_time", 90, "90 hit points healed over time"],
  ["mana", 40, "40 mana"],
  ["haste", 30, "30% attack speed"],
  ["slow", 20, "Slows the target by 20%"],
  ["snare", 35, "Slows the target's movement by 35%"],
  ["run_speed", 15, "15% faster movement"],
  ["buff_stats", 12, "12 points of stats"],
  ["buff_resist", 8, "8 points of resistance"],
  ["dispel", 2, "Strips up to 2 buffs from the target"],
  ["resurrect", 96, "Restores 96% of the experience lost"],
  ["melee_skill", 14, "14 extra damage on a skill"],
  ["levitate", 0, "Levitation"],
  ["invisibility", 0, "Invisibility"],
  ["see_invisible", 0, "See invisible"],
  ["vision", 0, "Better sight in the dark"],
  ["water_breathing", 0, "Breathe water"],
  ["teleport", 0, "Teleports you"],
  ["summon_pet", 0, "Summons a pet"],
  ["summon_item", 0, "Summons an item"],
  ["crowd_control", 0, "Stuns, mesmerizes or roots the target"],
  ["cure", 0, "Cures an affliction"],
  ["illusion", 0, "An illusion"],
  ["mount", 0, "A mount"],
  ["feign_death", 0, "Feign death"],
  ["bind", 0, "Binds your return point"],
  ["buff_protection", 0, "Protection from harm"],
];

describe("what an effect says it does (meaning)", () => {
  it.each(BY_CATEGORY)("%s with a magnitude of %s: %s", (c, m, text) => {
    expect(meaning({ c, m, k: "click" })).toBe(text);
  });

  it("has a row in the table for every category that meaning() has words for, and for no other", () => {
    const source = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../pipeline/trioforge/site/static/ui/exalt.js"), "utf8");
    const block = source.slice(source.indexOf("const by = {"), source.indexOf("  };", source.indexOf("const by = {")));
    const known = [...block.matchAll(/^ {4}(\w+):/gm)].map((found) => found[1]);
    expect(known.length).toBeGreaterThan(25);
    expect([...known].sort()).toEqual([...BY_CATEGORY.map(([c]) => c), "debuff"].sort()); // (the debuff has its own test: its words depend on the unit)
  });

  it("splits a debuff by its unit: mana drained, or points taken off", () => {
    expect(meaning({ c: "debuff", m: 25, u: "mana", k: "click" })).toBe("Drains 25 mana");
    expect(meaning({ c: "debuff", m: 25, u: "ac", k: "click" })).toBe("Lowers the target by 25 points");
    expect(meaning({ c: "debuff", m: 25, k: "click" })).toBe("Lowers the target by 25 points");
  });

  it("shows the magnitude to one decimal and without a trailing zero", () => {
    expect(meaning({ c: "damage", m: 12.34, k: "click" })).toBe("12.3 damage");
    expect(meaning({ c: "damage", m: 12.0, k: "click" })).toBe("12 damage");
    expect(meaning({ c: "damage", m: 0.05, k: "click" })).toBe("0.1 damage");
  });

  it("falls back to a utility effect for a category it has no words for, and for none", () => {
    expect(meaning({ c: "something_new", m: 3, k: "click" })).toBe("A utility effect");
    expect(meaning({ m: 3, k: "worn" })).toBe("A utility effect");
  });

  it("adds the rate of a proc, only for a proc that has one", () => {
    expect(meaning({ c: "damage", m: 100, k: "proc", r: 25 })).toBe("100 damage, with proc rate +25%");
    expect(meaning({ c: "damage", m: 100, k: "proc" })).toBe("100 damage");
    expect(meaning({ c: "damage", m: 100, k: "proc", r: 0 })).toBe("100 damage");
    expect(meaning({ c: "damage", m: 100, k: "click", r: 25 })).toBe("100 damage");
  });

  it("adds the level of the spell that a click casts, after the proc rate", () => {
    expect(meaning({ c: "heal", m: 80, k: "click", q: 39 })).toBe("80 hit points healed (cast as a level 39 spell)");
    expect(meaning({ c: "damage", m: 100, k: "proc", r: 25, q: 20 })).toBe("100 damage, with proc rate +25% (cast as a level 20 spell)");
    expect(meaning({ c: "heal", m: 80, k: "click", q: 0 })).toBe("80 hit points healed");
  });
});
