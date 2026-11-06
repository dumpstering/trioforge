// The browser's matcher of the exalt plan (static/ui/exalt-plan.js) against the plans Python made (fixtures/effects/plan-parity.json, written by `python -m trioforge.effects.fixtures`):
// every case is a kit, a tier and the lists of a trio and role, with the rows and the no-room list that effects/plan.py gave. The JavaScript must give the same, row for row.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { KINDS, MELEE_CLASSES, PLACES, REASON_ORDER, SLOT_TIER, assign, itemInfo, planKit, pySum, roundHalfEven } from "../pipeline/trioforge/site/static/ui/exalt-plan.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const fixture = JSON.parse(readFileSync(resolve(ROOT, "fixtures", "effects", "plan-parity.json"), "utf8"));
const effects = new Map(fixture.effects.map((row) => [row.id, row]));
const infos = new Map(Object.entries(fixture.items).map(([key, record]) => [key, itemInfo(record)]));
const items = (key) => infos.get(key) ?? null;

function run(testCase, { tier = testCase.tier, transform = (kit) => kit } = {}) {
  const list = fixture.lists[testCase.lists];
  const kit = transform(PLACES.map((place, index) => (testCase.kit[index] === null ? null : { place, key: testCase.kit[index] })).filter(Boolean));
  return planKit({ options: list.options, kit, items, effects, mass: fixture.mass, classes: list.classes, tier });
}

describe("the matcher equals Python's plan on every fixture", () => {
  test("the fixture is a real sample: many trios, every role, every reason, every kind", () => {
    expect(fixture.cases.length).toBeGreaterThanOrEqual(100);
    expect(new Set(Object.values(fixture.lists).map((list) => list.role))).toEqual(new Set(["balanced", "tank", "melee", "caster"]));
    expect(new Set(Object.values(fixture.lists).map((list) => list.classes.join("-"))).size).toBeGreaterThanOrEqual(20);
    const reasons = new Set(fixture.cases.flatMap((c) => c.noroom.map((row) => row.w)));
    expect([...reasons].sort()).toEqual(REASON_ORDER.filter((reason) => reason !== "donor").sort()); // ("donor" needs an option no class can wear a copy of: a list never offers one; tested by hand below)
    const kinds = new Set(fixture.cases.flatMap((c) => c.plan.map((row) => row.k)));
    expect([...kinds].sort()).toEqual(["click", "focus", "proc", "worn"]);
    expect(fixture.cases.some((c) => c.plan.some((row) => row.u === 1))).toBe(true);
    expect(fixture.cases.some((c) => c.plan.some((row) => row.u === 0))).toBe(true);
    expect(fixture.cases.some((c) => c.plan.some((row) => row.p === "ANY1" || row.p === "ANY2"))).toBe(true);
    expect(new Set(fixture.cases.map((c) => c.tier)).size).toBeGreaterThanOrEqual(5);
  });

  test("the constants are the ones Python has", () => {
    expect([...MELEE_CLASSES].sort()).toEqual(fixture.constants.melee);
    expect({ ...SLOT_TIER }).toEqual(fixture.constants.slot_tier);
    expect([...KINDS]).toEqual(fixture.constants.kinds);
    expect([...REASON_ORDER]).toEqual(fixture.constants.reasons);
    expect([...PLACES]).toEqual(fixture.constants.places);
  });

  fixture.cases.forEach((testCase, index) => {
    const list = fixture.lists[testCase.lists];
    test(`case ${index}: ${testCase.lists} at +${testCase.tier}`, () => {
      const got = run(testCase);
      expect(got.rows).toEqual(testCase.plan);
      expect(got.noroom).toEqual(testCase.noroom);
      expect(list.classes.length).toBe(3);
    });
  });

  test("the rows come in the order of the sockets, and every kind keeps the order of its list", () => {
    for (const testCase of fixture.cases) {
      const got = run(testCase);
      const order = got.rows.map((row) => KINDS.indexOf(row.k));
      expect(order).toEqual([...order].sort((a, b) => a - b));
    }
  });
});

describe("what the matcher is built on", () => {
  test("round goes to the even whole number at a half, as Python's does", () => {
    expect([0.5, 1.5, 2.5, 3.5, 0.4999, 2.5000001, 7].map(roundHalfEven)).toEqual([0, 2, 2, 4, 0, 3, 7]);
  });

  test("the sum of floats is Python's compensated sum", () => {
    expect(pySum([])).toBe(0);
    expect(pySum([0.1, 0.2, 0.3])).toBe(0.6); // Python 3.12: sum([0.1, 0.2, 0.3]) == 0.6 (a plain sum gives 0.6000000000000001)
    expect(pySum([1e100, 1.0, -1e100])).toBe(1.0); // (a plain sum gives 0.0)
    expect(pySum([2.5])).toBe(2.5);
  });

  test("the assignment gives the greatest total, and the first column among equal totals", () => {
    expect(assign([])).toEqual([]);
    // two rows both want column 0 (weight 10 and 9): the total is best with row 1 on column 1 (weight 8): 10 + 8 = 18 against 9 + 0
    expect(assign([[10, 1], [9, 8]])).toEqual([0, 1]);
    // greatest total, not first come: row 0 takes column 0 (5) and row 1 would get nothing (0), against row 0 on column 1 (4) and row 1 on column 0 (4)
    expect(assign([[5, 4], [4, 0]])).toEqual([1, 0]);
    // a row whose weights are all 0 is left out
    expect(assign([[0, 0], [3, 0]])).toEqual([null, 0]);
    // equal totals: the first column wins
    expect(assign([[7, 7]])).toEqual([0]);
  });

  test("an item record becomes what the matcher needs", () => {
    expect(itemInfo({ slots: ["PRIMARY"], weapon: { skill: "2H Slashing" }, tier_rule: "drop" })).toEqual({ classes: ["ALL"], slots: ["PRIMARY"], twoHand: true, arrival: 4 });
    expect(itemInfo({ slots: ["HEAD"], classes: ["CLR"], tier_rule: "fixed0" })).toEqual({ classes: ["CLR"], slots: ["HEAD"], twoHand: false, arrival: 0 });
    expect(itemInfo({ slots: ["HEAD"], tier_rule: "spell" }, { classes: ["WAR"] })).toEqual({ classes: ["WAR"], slots: ["HEAD"], twoHand: false, arrival: null });
  });
});

describe("what the matcher does that Python's plan does not", () => {
  const pick = fixture.cases.find((c) => c.tier === 4 && c.plan.length > 10);

  test("a host at a tier of its own opens only the sockets that tier reaches", () => {
    const base = run(pick);
    const hosts = new Set(base.rows.filter((row) => row.k === "proc").map((row) => row.h));
    expect(hosts.size).toBeGreaterThan(0);
    // every host drops to +3: no proc socket is open any more, the procs go to the no-room list as "tier" (or stay out for another reason)
    const lowered = run(pick, { transform: (kit) => kit.map((entry) => ({ ...entry, tier: 3 })) });
    expect(lowered.rows.some((row) => row.k === "proc")).toBe(false);
    const procs = lowered.noroom.filter((row) => row.k === "proc");
    expect(procs.length).toBeGreaterThan(0);
    // the same as a kit of one tier of +3
    expect(run(pick, { tier: 3 })).toEqual(lowered);
    // one host lowered to +0 loses its focus, click, worn and proc effects only
    const [first] = base.rows;
    const one = run(pick, { transform: (kit) => kit.map((entry) => (entry.key === first.h ? { ...entry, tier: 0 } : entry)) });
    expect(one.rows.every((row) => row.h !== first.h)).toBe(true);
  });

  test("an item the table does not know is not a host, and a donor it does not know is not offered", () => {
    const got = run(pick, { transform: (kit) => kit.map((entry, index) => (index === 0 ? { ...entry, key: "w999999999" } : entry)) });
    expect(got.rows.every((row) => row.h !== "w999999999")).toBe(true);
    const none = planKit({ options: fixture.lists[pick.lists].options, kit: [], items: () => null, effects, mass: fixture.mass, classes: fixture.lists[pick.lists].classes, tier: 4 });
    expect(none.rows).toEqual([]);
    expect(none.noroom.length).toBeGreaterThan(0);
    expect(none.noroom.every((row) => row.w === "donor")).toBe(true); // (no copy of any effect is known to be wearable)
  });

  test("an empty kit puts every effect of every socket kind in the no-room list, and never the carry list", () => {
    const list = fixture.lists[pick.lists];
    const none = planKit({ options: list.options, kit: [], items, effects, mass: fixture.mass, classes: list.classes, tier: 4 });
    const wanted = KINDS.reduce((sum, kind) => sum + list.options[kind].length, 0);
    expect(none.noroom).toHaveLength(wanted);
    expect(none.noroom.some((row) => row.k === "carry")).toBe(false);
  });
});

describe("the rules for a host, on a small hand-made kit", () => {
  const table = new Map([
    ["donor", { classes: ["MNK"], slots: ["HEAD"], twoHand: false, arrival: 4 }],
    ["both", { classes: ["MNK", "CLR"], slots: ["HEAD"], twoHand: false, arrival: 0 }],
    ["cleric", { classes: ["CLR"], slots: ["HEAD"], twoHand: false, arrival: 0 }],
    ["axe", { classes: ["ALL"], slots: ["PRIMARY"], twoHand: true, arrival: 4 }],
    ["blade", { classes: ["ALL"], slots: ["PRIMARY", "SECONDARY"], twoHand: false, arrival: 4 }],
    ["cap", { classes: ["ALL"], slots: ["HEAD"], twoHand: false, arrival: 4 }],
  ]);
  const lookup = (key) => table.get(key) ?? null;
  const one = (kind, category, donor, kit, classes, mass = { MNK: 0.1, CLR: 1, WAR: 0 }, places = null, tier = 4) =>
    planKit({
      options: { [kind]: [{ e: "e1", d: donor, o: [], s: 2, m: classes[0], g: { MNK: 1, CLR: 1 } }] },
      kit: kit.map((key, index) => ({ place: places ? places[index] : PLACES[index], key })),
      items: lookup,
      effects: new Map([["e1", { k: kind, c: category, d: [[donor, 1]] }]]),
      mass,
      classes,
      tier,
    });

  test("a mana click needs a class that casts: a Monk's mass of 0.1 counts, a Warrior's 0 does not", () => {
    expect(one("click", "mana", "donor", ["both"], ["MNK", "CLR"]).rows).toHaveLength(1);
    expect(one("click", "mana", "donor", ["cap"], ["MNK", "WAR"], { MNK: 0.1, WAR: 0 }).rows).toHaveLength(1);
    expect(one("click", "mana", "donor", ["cap"], ["WAR"], { WAR: 0 }).noroom).toEqual([{ k: "click", e: "e1", w: "donor" }]); // (the Warrior cannot use the only copy: no copy to move)
    const none = one("click", "mana", "cap", ["cap"], ["WAR", "ROG"], { WAR: 0, ROG: 0 });
    expect(none.rows).toEqual([]);
    expect(none.noroom).toEqual([{ k: "click", e: "e1", w: "class" }]);
  });

  test("a proc needs a melee class among those that can use both items, a cleric's cap is no host", () => {
    expect(one("proc", "damage", "both", ["cleric"], ["MNK", "CLR"]).noroom).toEqual([{ k: "proc", e: "e1", w: "class" }]);
    expect(one("proc", "damage", "both", ["both"], ["MNK", "CLR"]).rows.map((row) => row.h)).toEqual(["both"]);
  });

  test("a 2H donor needs a host in the primary hand itself: not an item that cannot be worn there, and not a weapon in the off hand or an Any place", () => {
    expect(one("worn", "damage", "axe", ["cap"], ["WAR"], undefined, ["PRIMARY"]).noroom).toEqual([{ k: "worn", e: "e1", w: "primary" }]);
    expect(one("worn", "damage", "axe", ["blade"], ["WAR"], undefined, ["PRIMARY"]).rows.map((row) => [row.h, row.p])).toEqual([["blade", "PRIMARY"]]);
    expect(one("worn", "damage", "axe", ["blade"], ["WAR"], undefined, ["SECONDARY"]).noroom).toEqual([{ k: "worn", e: "e1", w: "primary" }]);
    expect(one("worn", "damage", "axe", ["blade"], ["WAR"], undefined, ["ANY1"]).noroom).toEqual([{ k: "worn", e: "e1", w: "primary" }]);
  });

  test("a donor that is not primary-only goes on a weapon in an Any place or the off hand, by the weapon's own slots", () => {
    expect(one("worn", "damage", "blade", ["blade"], ["WAR"], undefined, ["ANY1"]).rows.map((row) => [row.h, row.p])).toEqual([["blade", "ANY1"]]);
  });

  test("a kit below the tier of the socket gives tier to every effect of the kind, and an effect no class can wear a copy of gives donor", () => {
    expect(one("proc", "damage", "both", ["both"], ["MNK", "CLR"], undefined, null, 3).noroom).toEqual([{ k: "proc", e: "e1", w: "tier" }]);
    expect(one("click", "damage", "both", [], ["MNK", "CLR"], undefined, null, 1).noroom).toEqual([{ k: "click", e: "e1", w: "tier" }]); // (an empty kit at +1 does not open a click socket either)
    expect(one("click", "damage", "cleric", ["cap"], ["WAR", "MNK"], undefined, null, 4).noroom).toEqual([{ k: "click", e: "e1", w: "donor" }]);
    expect(one("click", "damage", "cleric", ["cap"], ["WAR", "MNK"], undefined, null, 1).noroom).toEqual([{ k: "click", e: "e1", w: "tier" }]); // (tier is checked first)
  });

  test("a donor that arrives below the socket's tier is marked for an upgrade, one that arrives at +4 is not", () => {
    expect(one("click", "damage", "both", ["both"], ["MNK", "CLR"]).rows[0].u).toBe(1);
    expect(one("click", "damage", "cap", ["cap"], ["MNK", "CLR"]).rows[0].u).toBe(0);
  });
});

describe("a file that is not what the generator writes", () => {
  const base = { kit: [{ place: "HEAD", key: "cap" }], items: () => ({ classes: ["ALL"], slots: ["HEAD"], twoHand: false, arrival: 4 }), effects: new Map(), mass: {}, classes: ["WAR"], tier: 4 };

  test("treats a missing role entry, or a kind that is no list, as having nothing to place", () => {
    expect(planKit({ ...base, options: undefined })).toEqual({ rows: [], noroom: [] });
    expect(planKit({ ...base, options: null })).toEqual({ rows: [], noroom: [] });
    expect(planKit({ ...base, options: { focus: "none", click: { length: 2 }, worn: null, proc: 7 } })).toEqual({ rows: [], noroom: [] });
  });
});
