import loadHighs from "highs";
import { beforeAll, describe, expect, it } from "vitest";
import { SLOT_INSTANCES, evaluate } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { SAMPLE } from "./engine-fixtures.mjs";
import { BUNDLE_BYTES, ITEMS_BYTES } from "./engine-site-fixture.mjs";
import { ModelError, NO_BOW, NoBowError, allowedInHand, buildMilp, damageIndex, readItem } from "../pipeline/trioforge/site/static/engine/model.js";
import { BestKitError, bestKit } from "../pipeline/trioforge/site/static/engine/bestkit.js";
import { readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { PathError, bestSets, equipNow, farmPath } from "../pipeline/trioforge/site/static/engine/path.js";
import { closeSession, createSession } from "../pipeline/trioforge/site/static/engine/solve.js";
import { scenarioErrorCode } from "../pipeline/trioforge/site/static/engine/worker.js";
import { gear, oneHand, profileWith, q } from "./engine-hand.mjs";

// Part E, items E8 (the weapon skills that never stand in a melee hand) and E9 (an Archer whose list has no bow). Every item here is invented.

const bowOf = (dmg, delay, skill = "Archery") => ({ skill, dmg, delay, bonus: null, two_handed: false });
const SETUPS = ["1h-shield", "2h", "dw", "stick", "ranged"];

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

describe("a weapon of a ranged skill in a melee hand (E8)", () => {
  it.each(["Archery", "archery", "Throwing", "Throwingv1", "Throwingv2"])("is never allowed there, whatever the setup: %s", (skill) => {
    const listed = readItem(gear("listed", ["PRIMARY", "SECONDARY", "RANGE"], { weapon: bowOf(30, 40, skill) }), 0);
    for (const setup of SETUPS) {
      expect(allowedInHand(listed, "PRIMARY", setup), `${skill} ${setup} primary`).toBe(false);
      expect(allowedInHand(listed, "SECONDARY", setup), `${skill} ${setup} secondary`).toBe(false);
    }
    expect(allowedInHand(listed, "RANGE", "ranged")).toBe(skill.toLowerCase() === "archery");
    expect(allowedInHand(listed, "RANGE", "dw")).toBe(true);
  });

  it.each(["Piercing", "Hand to Hand", "1H Slash", "1H Blunt", "2H Piercing", null])("is not said of the skills of melee weapons the catalog has: %s", (skill) => {
    const listed = readItem(gear("listed", ["PRIMARY", "SECONDARY"], { weapon: { skill, dmg: 30, delay: 40, bonus: null, two_handed: false } }), 0);
    expect(allowedInHand(listed, "PRIMARY", "dw")).toBe(true);
    expect(allowedInHand(listed, "PRIMARY", "stick")).toBe(true);
  });
});

describe("an Archer whose list has no bow (E9)", () => {
  const profile = profileWith({ weights: { HP: 1, DMG: 600 } });
  const options = { any_rule: "explicit", haste_assumed: 0 };
  const make = () => createSession({ highs, profile, setup: "ranged", options });
  const ring = gear("ring", ["FINGER"], { stats: { HP: 30 } });
  const sword = gear("sword", ["PRIMARY", "SECONDARY"], { weapon: oneHand(20, 30) });
  const bow = gear("bow", ["RANGE"], { weapon: bowOf(33, 40) });
  const SAY = "Add a bow to your list, or switch build";

  it("is refused with a plain sentence by every function that begins with Equip now, and the sentence is a bad request of the page, not an internal fault", () => {
    const session = make();
    try {
      const owned = [[ring, 1], [sword, 1]];
      const candidates = [bow, gear("other", ["HEAD"], { stats: { HP: 9 } })];
      for (const call of [
        () => equipNow(session, owned, { budgetMs: 60_000 }),
        () => farmPath(session, owned, candidates, { steps: 2, budgetMs: 60_000 }),
        () => bestSets(session, owned, candidates, 1, { budgetMs: 60_000 }),
      ]) {
        let caught = null;
        try {
          call();
        } catch (error) {
          caught = error;
        }
        expect(caught, "the refusal").toBeInstanceOf(PathError);
        expect(caught.message).toContain(SAY);
        expect(scenarioErrorCode(caught), "the worker says bad-request and is not replaced").toBe("bad-request");
      }
    } finally {
      closeSession(session);
    }
  });

  it("is answered normally once a bow is in the list, and a session of another setup needs none", () => {
    const session = make();
    try {
      const got = equipNow(session, [[ring, 1], [bow, 1]], { budgetMs: 60_000, canonical: true });
      expect(got.status).toBe("optimal");
      expect(got.kit.some((item) => item !== null && item.key === "bow")).toBe(true);
      const path = farmPath(session, [[ring, 1], [bow, 1]], [sword], { steps: 1, budgetMs: 60_000 });
      expect(path.baseline.status).toBe("optimal");
    } finally {
      closeSession(session);
    }
    const stick = createSession({ highs, profile, setup: "stick", options });
    try {
      expect(equipNow(stick, [[ring, 1]], { budgetMs: 60_000 }).status).toBe("optimal");
    } finally {
      closeSession(stick);
    }
  });

  it("counts a thrown weapon or a charm in the range place as no bow", () => {
    const session = make();
    try {
      const thrown = gear("spear", ["RANGE"], { weapon: bowOf(9, 30, "Throwing") });
      const charm = gear("charm", ["RANGE"], { stats: { HP: 50 } });
      for (const owned of [[[thrown, 1]], [[charm, 1]], []]) expect(() => equipNow(session, owned, { budgetMs: 60_000 }), JSON.stringify(owned.map(([item]) => item.key))).toThrow(PathError);
    } finally {
      closeSession(session);
    }
  });
});

describe("the evaluator holds the same rule as the builder (F5)", () => {
  const bundle = readBundle(SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json"));
  const profile = assembleProfile(bundle, { race: "OGR", role: "tank", buffs: "own" });
  const monkBins = bundle.monk_bins;
  const PRIMARY = SLOT_INSTANCES.indexOf("PRIMARY");
  const SECONDARY = SLOT_INSTANCES.indexOf("SECONDARY");
  const RANGE = SLOT_INSTANCES.indexOf("RANGE");
  const kit = (...entries) => {
    const places = new Array(SLOT_INSTANCES.length).fill(null);
    for (const [place, item] of entries) places[place] = item;
    return places;
  };
  const weaponPart = (placed, setup) => evaluate(profile, placed, null, { setup, hasteAssumed: 20, monkBins }).breakdown.parts.WEAPON;

  it.each(["Archery", "archery", "Throwing", "Throwingv1", "Throwingv2"])("scores nothing for a weapon of the %s skill in a hand, in every setup, as the builder refuses it the hand", (skill) => {
    for (const setup of ["1h-shield", "2h", "dw", "stick", "ranged"]) {
      for (const place of [PRIMARY, SECONDARY]) {
        const ranged = gear("it-ranged", ["PRIMARY", "SECONDARY", "RANGE"], { weapon: bowOf(30, 40, skill) });
        expect(weaponPart(kit([place, ranged]), setup).sign(), `${skill} ${setup} ${SLOT_INSTANCES[place]}`).toBe(0);
      }
    }
    // the same numbers of a melee skill score, so it is the skill that decides
    const sword = gear("it-sword", ["PRIMARY", "SECONDARY"], { weapon: oneHand(30, 40) });
    expect(weaponPart(kit([PRIMARY, sword]), "dw").sign()).toBeGreaterThan(0);
  });

  it("scores a bow in the range place under the bow setup, and a thrown weapon in no place", () => {
    const bow = gear("it-bow", ["RANGE"], { weapon: bowOf(30, 40, "Archery") });
    const thrown = gear("it-spear", ["RANGE"], { weapon: bowOf(30, 40, "Throwing") });
    expect(weaponPart(kit([RANGE, bow]), "ranged").sign()).toBeGreaterThan(0);
    expect(weaponPart(kit([RANGE, thrown]), "ranged").sign()).toBe(0);
  });

  it.each(["Archery", "Throwing", "Piercing", "Hand to Hand", "1H Slash"])("is what the model's damage index says for the %s skill: the same refusal in the builder and in the evaluator", (skill) => {
    const item = readItem(gear("it-x", ["PRIMARY", "SECONDARY", "RANGE"], { weapon: bowOf(30, 40, skill) }), 0);
    for (const setup of ["1h-shield", "2h", "dw", "stick", "ranged"]) {
      for (const [hand, place] of [["PRIMARY", PRIMARY], ["SECONDARY", SECONDARY], ["RANGE", RANGE]]) {
        const built = damageIndex(item, hand, setup, 20, q(4, 5), q(1));
        const raw = gear("it-x", ["PRIMARY", "SECONDARY", "RANGE"], { weapon: bowOf(30, 40, skill) });
        const evaluated = weaponPart(kit([place, raw]), setup);
        // (the evaluator multiplies the index by the weight of damage: zero where the builder's index is zero, and not zero where it is not)
        expect(evaluated.sign() === 0, `${skill} ${setup} ${hand}`).toBe(built.sign() === 0);
      }
    }
  });
});

describe("an Archer whose only bow the view cannot wear (F8)", () => {
  const options = { any_rule: "explicit", haste_assumed: 0 };
  const SAY = "Add a bow to your list, or switch build";
  const ring = gear("ring", ["FINGER"], { stats: { HP: 30 } });
  const sword = gear("sword", ["PRIMARY", "SECONDARY"], { weapon: oneHand(20, 30) });
  const lockedBows = {
    "a bow of another race": gear("troll-bow", ["RANGE"], { weapon: bowOf(33, 40), races: ["TRL"] }),
    "a bow of a deity the view does not follow": gear("temple-bow", ["RANGE"], { weapon: bowOf(33, 40), deity: ["The Tribunal"] }),
  };
  const make = (profile) => createSession({ highs, profile, setup: "ranged", options });

  it("says the typed NO_BOW refusal, a bad request, where the model had thrown a bare error (an internal fault that replaced the worker)", () => {
    expect(NO_BOW).toBe(SAY);
    expect(new NoBowError()).toBeInstanceOf(ModelError);
    expect(new NoBowError().message).toBe(SAY);
    expect(scenarioErrorCode(new NoBowError())).toBe("bad-request");
    expect(scenarioErrorCode(new ModelError("a bad item"))).toBe("internal"); // (a model error of the data is still a fault of the engine)
    const profile = profileWith({ race: "OGR", weights: { HP: 1, DMG: 600 } });
    for (const [name, bow] of Object.entries(lockedBows)) {
      expect(() => buildMilp(profile, [ring, bow], "ranged", null, options), name).toThrow(NoBowError);
    }
  });

  for (const [name, bow] of Object.entries(lockedBows)) {
    it(`is refused with the sentence by Equip now, the farm path and the best sets when the list has ${name}`, () => {
      const profile = profileWith({ race: "OGR", weights: { HP: 1, DMG: 600 } });
      const session = make(profile);
      try {
        const owned = [[ring, 1], [sword, 1], [bow, 1]];
        const candidates = [gear("other", ["HEAD"], { stats: { HP: 9 } })];
        for (const call of [
          () => equipNow(session, owned, { budgetMs: 60_000 }),
          () => farmPath(session, owned, candidates, { steps: 2, budgetMs: 60_000 }),
          () => bestSets(session, owned, candidates, 1, { budgetMs: 60_000 }),
        ]) {
          let caught = null;
          try {
            call();
          } catch (error) {
            caught = error;
          }
          expect(caught, "the refusal").toBeInstanceOf(PathError);
          expect(caught.message).toContain(SAY);
          expect(scenarioErrorCode(caught)).toBe("bad-request");
        }
      } finally {
        closeSession(session);
      }
    });
  }

  it("is answered once the same bow is one the view can wear (a Troll)", () => {
    const profile = profileWith({ race: "TRL", weights: { HP: 1, DMG: 600 } });
    const session = make(profile);
    try {
      const got = equipNow(session, [[ring, 1], [lockedBows["a bow of another race"], 1]], { budgetMs: 60_000, canonical: true });
      expect(got.status).toBe("optimal");
      expect(got.kit.some((item) => item !== null && item.key === "troll-bow")).toBe(true);
    } finally {
      closeSession(session);
    }
  });

  describe("and the best kit of a view whose pool has no bow it can wear", () => {
    const TABLE = readItemTable(JSON.parse(ITEMS_BYTES.toString("utf8")));
    const BUNDLE = readBundle(JSON.parse(BUNDLE_BYTES.toString("utf8")));
    const VIEW = { race: "OGR", role: "tank", buffs: "own", evidence: "wiki", setup: "ranged" };
    const withBow = (over) => new Map([...TABLE.records].map(([key, record]) => [key, key === "w90038" ? { ...record, ...over } : record]));
    const solve = (records) => bestKit({ highs, records, bundle: BUNDLE, scenario: VIEW, tier: 4, budgetMs: 60_000 });

    it("answers while the bow can be worn", () => {
      expect(solve(TABLE.records).answer.status).toBe("optimal");
    });

    it.each([
      ["a race the view is not", { races: ["TRL"] }],
      ["a deity the view does not follow", { deity: ["The Tribunal"] }],
    ])("is a BestKitError (a bad request, the sentence says which build to pick) for a bow of %s", (_, over) => {
      let caught = null;
      try {
        solve(withBow(over));
      } catch (error) {
        caught = error;
      }
      expect(caught, "the refusal").toBeInstanceOf(BestKitError);
      expect(caught).not.toBeInstanceOf(ModelError);
      expect(caught.message).toMatch(/bow/i);
    });
  });
});

describe("the evaluator does not judge where an item stands, and only the weapon term refuses a hand to a ranged weapon (G8)", () => {
  const bundle = readBundle(SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json"));
  const profile = assembleProfile(bundle, { race: "OGR", role: "tank", buffs: "own" });
  const monkBins = bundle.monk_bins;
  const at = (name) => SLOT_INSTANCES.indexOf(name);
  const value = (name, item) => {
    const kit = new Array(SLOT_INSTANCES.length).fill(null);
    kit[at(name)] = item;
    return evaluate(profile, kit, null, { setup: "dw", hasteAssumed: 0, monkBins }).F;
  };

  it("counts the stats of an item in any place and no swing of a weapon that is not in a hand it is allowed in", () => {
    const ring = gear("ring", ["FINGER"], { stats: { HP: 40 } });
    const bow = gear("bow", ["RANGE", "PRIMARY"], { stats: { HP: 40 }, weapon: bowOf(30, 40, "Archery") });
    const sword = gear("sword", ["PRIMARY"], { stats: { HP: 40 }, weapon: oneHand(30, 40) });
    expect(value("HEAD", ring).equals(value("FINGER", ring))).toBe(true); // (no place is refused)
    expect(value("CHEST", sword).equals(value("FINGER", ring))).toBe(true);
    expect(value("PRIMARY", bow).equals(value("FINGER", ring))).toBe(true); // the stats, and no swing
    expect(value("PRIMARY", sword).compare(value("PRIMARY", bow))).toBeGreaterThan(0);
  });
});
