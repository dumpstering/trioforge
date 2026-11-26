import { describe, expect, it } from "vitest";
import { ChoiceError, assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { SAMPLE } from "./engine-fixtures.mjs";
import { allowedInHand, readItem } from "../pipeline/trioforge/site/static/engine/model.js";
import { fitGroups } from "../pipeline/trioforge/site/static/engine/prune.js";
import { gear } from "./engine-hand.mjs";

// The fourth round of the bow setup in the browser's engine. The Ranged role is offered by a pool alone (a bow in it): with no pool to read no role has the Bow setup and the Ranged role
// has none either, so a bundle gives its profile only at an evidence level, as pipeline/tests/test_ranged_site.py holds the exporter's `assemble` to. Every name here is invented.

describe("the Ranged role of a bundle", () => {
  const raw = structuredClone(SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json"));
  // (a bundle that has the role: the melee row with the one setup of the role, offered at the wiki level and not at the strict one)
  raw.roles.ranged = { ...structuredClone(raw.roles.melee), setups: ["ranged"], setups_by_evidence: { strict: [], wiki: ["ranged"] } };
  const bundle = readBundle(raw);
  const asked = { race: "OGR", role: "ranged", buffs: "own" };

  it("is made at an evidence level that offers it", () => {
    const profile = assembleProfile(bundle, { ...asked, evidence: "wiki" });
    expect(profile.setups).toEqual(["ranged"]);
    expect(profile.role).toBe("ranged");
    expect(profile.evidence).toBe("wiki");
  });
  it("is refused at a level that does not offer it, and with no level named", () => {
    expect(() => assembleProfile(bundle, { ...asked, evidence: "strict" })).toThrow(ChoiceError);
    expect(() => assembleProfile(bundle, asked)).toThrow(/evidence level/);
    expect(() => assembleProfile(bundle, { ...asked, evidence: null })).toThrow(/evidence level/);
  });
  it("leaves every other role as it was: a profile with no level is made, and has no Bow setup", () => {
    for (const role of ["tank", "melee"]) {
      const profile = assembleProfile(bundle, { race: "OGR", role, buffs: "own" });
      expect(profile.setups, role).not.toContain("ranged");
    }
  });
});

// The range place under the four old setups: the groups the weapons rules decide are the two hands and the range place for every setup, as WEAPON_GROUPS of solver/model.py has them
// (the rules admit every item that lists the range place in the four old setups and only a bow in the bow setup), so the browser's pruner is held to the table that
// pipeline/tests/test_ranged_round4.py holds the builder's to.
describe("the range place of the pruner", () => {
  const arrows = gear("it-bow", ["RANGE"], { weapon: { skill: "Archery", dmg: 45, delay: 60, bonus: null, two_handed: false } });
  const ornament = gear("it-ornament", ["RANGE"]);
  const sword = gear("it-sword", ["PRIMARY", "RANGE"], { weapon: { skill: "1H Slashing", dmg: 20, delay: 30, bonus: null, two_handed: false } });
  const old = {
    "it-bow": { "1h-shield": ["RANGE"], "2h": ["RANGE"], dw: ["RANGE"], stick: ["RANGE"] },
    "it-ornament": { "1h-shield": ["RANGE"], "2h": ["RANGE"], dw: ["RANGE"], stick: ["RANGE"] },
    "it-sword": { "1h-shield": ["PRIMARY", "RANGE"], "2h": ["RANGE"], dw: ["PRIMARY", "RANGE"], stick: ["PRIMARY", "RANGE"] },
  };
  it("admits every item that lists it in the four old setups, as the builder's pruner does", () => {
    for (const item of [arrows, ornament, sword]) {
      for (const [setup, groups] of Object.entries(old[item.key])) {
        expect([...fitGroups(item, setup, "explicit")].sort(), `${item.key} ${setup}`).toEqual(groups);
        expect(allowedInHand(readItem(item, 0), "RANGE", setup), `${item.key} ${setup}`).toBe(true);
      }
    }
  });
  it("admits only a bow in the bow setup", () => {
    expect([...fitGroups(arrows, "ranged", "explicit")]).toEqual(["RANGE"]);
    expect([...fitGroups(ornament, "ranged", "explicit")]).toEqual([]);
    expect([...fitGroups(sword, "ranged", "explicit")]).toEqual(["PRIMARY"]);
  });
});
