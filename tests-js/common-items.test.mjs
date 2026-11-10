// The function behind "Get these first" (static/ui/common-items.js): given the parsed shard, a race and a tier, which items the best kits of the roles have in common. It is pure, so
// these tests give it shards made by hand (tests-js/common-items.mjs) and read what it says of them.

import { describe, expect, it } from "vitest";
import { commonItems } from "../pipeline/trioforge/site/static/ui/common-items.js";
import { parseShard } from "../pipeline/trioforge/site/static/shard.js";
import { shardDocument } from "./common-items.mjs";

const HEAD = 0;
const EAR1 = 2;
const EAR2 = 3;
const NECK = 4;
const FINGER1 = 11;
const FINGER2 = 12;
const ANY1 = 18;
const MAIN = 20;

/** One scenario with the kit given as { place: key }. */
const at = (role, kit, over = {}) => ({ race: "HUM", role, tier: 4, setup: "dw", value: 10, kit, ...over });
const shardOf = (scenarios, names) => parseShard(shardDocument(scenarios, names));
const keys = (group) => group.map((entry) => entry.item.key);

describe("commonItems: which items the best kits have in common", () => {
  it("every item that all the roles wear is in the first group, and the second is empty", () => {
    const shard = shardOf([
      at("balanced", { [HEAD]: "helm", [NECK]: "amulet" }),
      at("tank", { [HEAD]: "helm", [NECK]: "amulet", [MAIN]: "club" }),
      at("melee", { [HEAD]: "helm", [NECK]: "amulet", [MAIN]: "axe" }),
    ]);
    const found = commonItems(shard, "HUM", 4);
    expect(found.roles).toEqual(["balanced", "tank", "melee"]);
    expect(keys(found.every)).toEqual(["helm", "amulet"]);
    expect(found.most).toEqual([]);
  });

  it("an item that three of four roles wear is in the second group, with the role that does not", () => {
    const shard = shardOf([
      at("balanced", { [HEAD]: "helm", [NECK]: "amulet" }),
      at("tank", { [HEAD]: "helm", [NECK]: "amulet" }),
      at("melee", { [HEAD]: "helm", [NECK]: "amulet" }),
      at("caster", { [HEAD]: "helm", [NECK]: "robe-collar" }),
    ]);
    const found = commonItems(shard, "HUM", 4);
    expect(keys(found.every)).toEqual(["helm"]);
    expect(keys(found.most)).toEqual(["amulet"]);
    expect(found.most[0].missing).toEqual(["caster"]);
    expect(found.every[0].missing).toEqual([]);
  });

  it("an item that half of the roles wear, or fewer, is in neither group", () => {
    const shard = shardOf([
      at("balanced", { [HEAD]: "helm", [NECK]: "amulet", [MAIN]: "club" }),
      at("tank", { [HEAD]: "helm", [NECK]: "amulet" }),
      at("melee", { [HEAD]: "cap" }),
      at("caster", { [HEAD]: "hood" }),
    ]);
    const found = commonItems(shard, "HUM", 4);
    expect(keys(found.every)).toEqual([]);
    expect(keys(found.most)).toEqual([]); // helm and amulet are worn by two of four: not more than half
  });

  it("with three roles, two is more than half, and the role that does not wear it is named", () => {
    const shard = shardOf([
      at("balanced", { [HEAD]: "helm" }),
      at("tank", { [HEAD]: "helm" }),
      at("melee", { [HEAD]: "cap" }),
    ]);
    const found = commonItems(shard, "HUM", 4);
    expect(keys(found.every)).toEqual([]);
    expect(keys(found.most)).toEqual(["helm"]);
    expect(found.most[0].missing).toEqual(["melee"]);
  });

  it("two roles share only what both wear: the second group is always empty", () => {
    const shard = shardOf([at("balanced", { [HEAD]: "helm", [NECK]: "amulet" }), at("tank", { [HEAD]: "helm", [NECK]: "chain" })]);
    const found = commonItems(shard, "HUM", 4);
    expect(found.roles).toEqual(["balanced", "tank"]);
    expect(keys(found.every)).toEqual(["helm"]);
    expect(found.most).toEqual([]);
  });

  it("one role has nothing in common with any other: both groups are empty", () => {
    const shard = shardOf([at("balanced", { [HEAD]: "helm", [NECK]: "amulet" })]);
    const found = commonItems(shard, "HUM", 4);
    expect(found.roles).toEqual(["balanced"]);
    expect(found.every).toEqual([]);
    expect(found.most).toEqual([]);
  });

  it("an item is counted once for a role however many places it fills; 2x is shown when every role that has it wears two", () => {
    const shard = shardOf(
      [
        at("balanced", { [EAR1]: "stud", [EAR2]: "stud", [HEAD]: "helm", [FINGER1]: "band", [FINGER2]: "band" }),
        at("tank", { [EAR1]: "stud", [EAR2]: "stud", [HEAD]: "helm", [FINGER1]: "band" }),
        at("melee", { [EAR1]: "stud", [EAR2]: "stud", [HEAD]: "helm", [FINGER1]: "band", [FINGER2]: "band" }),
      ],
      { stud: "Stud of Bashing", band: "Plain Band" },
    );
    const found = commonItems(shard, "HUM", 4);
    expect(keys(found.every)).toEqual(["helm", "stud", "band"]); // (by first place: Head 0, Ear 1 2, Finger 1 11)
    const by = Object.fromEntries(found.every.map((entry) => [entry.item.key, entry]));
    expect(by.stud.copies).toBe(2); // all three wear two
    expect(by.band.copies).toBe(1); // the tank wears one, so no count is shown
    expect(by.helm.copies).toBe(1);
  });

  it("an item that two of three roles wear twice is two wearers, not four: the second group, with the count of the roles that have it", () => {
    // each of the two wears it in two places, but each is one wearer; the roles that list it both wear two, so 2x is shown
    const shard = shardOf([
      at("balanced", { [EAR1]: "stud", [EAR2]: "stud" }),
      at("tank", { [EAR1]: "stud", [EAR2]: "stud" }),
      at("melee", { [EAR1]: "loop" }),
    ]);
    const found = commonItems(shard, "HUM", 4);
    expect(keys(found.every)).toEqual([]);
    expect(keys(found.most)).toEqual(["stud"]);
    expect(found.most[0].copies).toBe(2);
    expect(found.most[0].missing).toEqual(["melee"]);
  });

  it("the same item in different places counts once per role, and takes its place from the first place any role puts it in", () => {
    const shard = shardOf([
      at("balanced", { [FINGER2]: "band" }),
      at("tank", { [ANY1]: "band" }),
      at("melee", { [FINGER1]: "band" }),
    ]);
    const found = commonItems(shard, "HUM", 4);
    expect(keys(found.every)).toEqual(["band"]);
    expect(found.every[0].place).toBe(FINGER1);
    expect(found.every[0].copies).toBe(1);
  });

  it("is ordered by the first place the item fills, then by name", () => {
    const shard = shardOf(
      [
        at("balanced", { [HEAD]: "h", [NECK]: "n2", [FINGER1]: "f", [MAIN]: "m", [ANY1]: "n1" }),
        at("tank", { [HEAD]: "h", [NECK]: "n2", [FINGER1]: "f", [MAIN]: "m", [ANY1]: "n1" }),
      ],
      { h: "Zed Helm", n2: "Beta Neck", f: "Mid Ring", m: "Mace", n1: "Alpha Charm" },
    );
    expect(commonItems(shard, "HUM", 4).every.map((entry) => entry.item.name)).toEqual(["Zed Helm", "Beta Neck", "Mid Ring", "Alpha Charm", "Mace"]);
    // two items in the same place (the first place of one of them is the other's: one is worn there by one role and the other by the other): the name decides
    const tied = shardOf(
      [at("balanced", { [HEAD]: "b", [NECK]: "a" }), at("tank", { [HEAD]: "a", [NECK]: "b" })],
      { a: "Apple Helm", b: "Banana Helm" },
    );
    const found = commonItems(tied, "HUM", 4);
    expect(found.every.map((entry) => [entry.item.name, entry.place])).toEqual([["Apple Helm", HEAD], ["Banana Helm", HEAD]]);
  });

  it("takes the best setup of each role: the highest value, and the setup the page picks on a tie (the earlier in its order)", () => {
    const shard = shardOf([
      // the balanced role: the dual-wield kit is worth more than the shield kit, and is the one that counts
      at("balanced", { [HEAD]: "helm", [MAIN]: "sword" }, { setup: "dw", value: 12 }),
      at("balanced", { [HEAD]: "cap", [MAIN]: "club" }, { setup: "1h-shield", value: 9 }),
      // the tank: a tie between two setups; the page picks the earlier one of its order (1h-shield before 2h)
      at("tank", { [HEAD]: "helm", [MAIN]: "club" }, { setup: "1h-shield", value: 7 }),
      at("tank", { [HEAD]: "cap", [MAIN]: "sword" }, { setup: "2h", value: 7 }),
      // the melee: a tie between dw and stick, which are both after the setups above; dw is earlier
      at("melee", { [HEAD]: "helm", [MAIN]: "sword" }, { setup: "stick", value: 5 }),
      at("melee", { [HEAD]: "helm", [MAIN]: "stave" }, { setup: "dw", value: 5 }),
    ]);
    expect(shard.bestSetup("HUM", "tank", 4)).toBe("1h-shield"); // (the page's own rule, which the function uses)
    const found = commonItems(shard, "HUM", 4);
    expect(keys(found.every)).toEqual(["helm"]); // the weapons differ: sword, club, stave
    expect(keys(found.most)).toEqual([]);
  });

  it("compares the race and tier it is given, and no other", () => {
    const shard = shardOf([
      at("balanced", { [HEAD]: "helm" }),
      at("tank", { [HEAD]: "helm" }),
      at("balanced", { [HEAD]: "cap" }, { tier: 10 }),
      at("tank", { [HEAD]: "hood" }, { tier: 10 }),
      at("balanced", { [HEAD]: "cap" }, { race: "OGR" }),
      at("tank", { [HEAD]: "cap" }, { race: "OGR" }),
    ]);
    expect(keys(commonItems(shard, "HUM", 4).every)).toEqual(["helm"]);
    expect(keys(commonItems(shard, "HUM", 10).every)).toEqual([]);
    expect(keys(commonItems(shard, "OGR", 4).every)).toEqual(["cap"]);
  });

  it("a role the shard has no kit for at that race and tier is not compared, and does not count as missing", () => {
    const shard = shardOf([
      at("balanced", { [HEAD]: "helm" }),
      at("tank", { [HEAD]: "helm" }),
      at("melee", { [HEAD]: "cap" }),
      at("caster", { [HEAD]: "helm" }, { tier: 10 }), // only at another tier
    ]);
    const found = commonItems(shard, "HUM", 4);
    expect(found.roles).toEqual(["balanced", "tank", "melee"]);
    expect(keys(found.most)).toEqual(["helm"]);
    expect(found.most[0].missing).toEqual(["melee"]);
    expect(commonItems(shard, "HUM", 10).roles).toEqual(["caster"]);
  });

  it("a race or tier the shard does not have gives no roles and nothing in common", () => {
    const shard = shardOf([at("balanced", { [HEAD]: "helm" }), at("tank", { [HEAD]: "helm" })]);
    expect(commonItems(shard, "ELF", 4)).toEqual({ roles: [], every: [], most: [] });
    expect(commonItems(shard, "HUM", 7)).toEqual({ roles: [], every: [], most: [] });
  });

  it("an empty place is not an item", () => {
    const shard = shardOf([at("balanced", {}), at("tank", { [HEAD]: "helm" })]);
    const found = commonItems(shard, "HUM", 4);
    expect(found.every).toEqual([]);
    expect(found.most).toEqual([]);
  });

  it("gives the items of the shard as they are (name, arrival, source, deity), so that the rows can say what a kit row says", () => {
    const shard = shardOf([at("balanced", { [HEAD]: "helm" }), at("tank", { [HEAD]: "helm" })], { helm: "Helm of Testing" });
    const [entry] = commonItems(shard, "HUM", 4).every;
    expect(entry.item).toBe(shard.items[0]);
    expect(entry.item).toMatchObject({ key: "helm", name: "Helm of Testing", arrival: 4, source: "Dropped by helm", deity: [] });
  });
});
