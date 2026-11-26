import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { valueOfKit } from "../pipeline/trioforge/site/static/engine/kitvalue.js";

// A kit made for the Bow setup is valued under it when its link says so (the optional setup marker of the link: input/kitcode.js), and a kit with no marker is valued as it always was,
// under the setup its hands are. The marker is accepted only for a setup that the trio offers (the bundle lists it for some role at the evidence level) and a kit that has a bow in its range
// place; anything else is ignored, and the kit is valued exactly as it is without it. The kits are the rows of the Bow setup that the precompute solved for the invented catalog of the
// site fixture (fixtures/site/results-solved), so the value must be the value of the row. Every name in them is invented.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SOLVED = resolve(ROOT, "fixtures/site/results-solved");
const table = readItemTable(JSON.parse(readFileSync(resolve(SOLVED, "items.json"), "utf8")));
const bundle = JSON.parse(readFileSync(resolve(SOLVED, "pal-mnk-ber/engine-l50.json"), "utf8"));
const shard = JSON.parse(readFileSync(resolve(SOLVED, "pal-mnk-ber/wiki-own.json"), "utf8"));
const RANGE = shard.places.indexOf("RANGE");

/** The rows of a setup of the shard: race, role, tier, F, and the places of the kit as `valueOfKit` takes them. */
function rowsOf(setup) {
  return shard.scenarios
    .filter((row) => row[3] === setup)
    .map(([race, role, tier, , kit, F]) => ({
      race,
      role,
      tier,
      F,
      places: shard.kits[kit].flatMap((at, slotIndex) => (at < 0 ? [] : [{ slotIndex, key: shard.items[at][0], tier }])),
    }));
}
const BOW_ROWS = rowsOf("ranged");
const value = (row, over = {}) => valueOfKit({ bundle, records: table.records, race: row.race, role: row.role, buffs: "own", evidence: "wiki", places: row.places, ...over });
const rounded = (answer) => Math.round(answer.value * 100) / 100;

describe("a kit of the Bow setup, with the marker of its link", () => {
  it("has rows to hold the engine to: bows in the range place, in both roles, at both tiers, for both races", () => {
    expect(BOW_ROWS).toHaveLength(8);
    expect(new Set(BOW_ROWS.map((row) => `${row.race} ${row.role} ${row.tier}`)).size).toBe(8);
    for (const row of BOW_ROWS) expect(row.places.some((place) => place.slotIndex === RANGE)).toBe(true);
  });
  it.each(BOW_ROWS.map((row) => [`${row.race} ${row.role} +${row.tier}`, row]))("is worth what the precompute's row says, under the Bow setup, with its bow scored: %s", (_, row) => {
    const answer = value(row, { madeFor: "ranged" });
    expect(answer.setup).toBe("ranged");
    expect(rounded(answer)).toBe(row.F);
    expect(answer.exact).toBe(true);
    expect(answer.left).toEqual([]);
    expect(answer.named).toBe(true); // (the answer says that the setup is the link's, not the hands')
  });
  it.each(BOW_ROWS.map((row) => [`${row.race} ${row.role} +${row.tier}`, row]))("is worked out under the hands' setup when the link has no marker, the bow unscored and the hands' weapons scored (another number): %s", (_, row) => {
    const plain = value(row);
    expect(plain.setup).not.toBe("ranged");
    expect(plain.value).not.toBe(value(row, { madeFor: "ranged" }).value);
    expect("named" in plain).toBe(false);
    expect(Object.keys(plain).sort()).toEqual(["F", "buffs", "counted", "evaluations", "exact", "hasteAssumed", "left", "setup", "value"]); // (an old link's answer has the keys it had)
  });
});

describe("a marker that is not accepted", () => {
  const row = BOW_ROWS[0];
  const as = (over) => JSON.stringify(value(row, over));

  it("is ignored for a setup that is not the Bow's, whatever else it is", () => {
    for (const madeFor of ["dw", "2h", "1h-shield", "stick", "RANGED", "", 7, true, {}, [], undefined, null]) {
      expect(as({ madeFor }), String(madeFor)).toBe(as({}));
    }
  });
  it("is ignored by a trio that does not offer the Bow setup: the kit is valued as today", () => {
    const without = structuredClone(bundle);
    for (const role of Object.values(without.roles)) {
      role.setups = role.setups.filter((setup) => setup !== "ranged");
      for (const level of Object.keys(role.setups_by_evidence)) role.setups_by_evidence[level] = role.setups_by_evidence[level].filter((setup) => setup !== "ranged");
    }
    expect(JSON.stringify(valueOfKit({ bundle: without, records: table.records, race: row.race, role: row.role, buffs: "own", evidence: "wiki", places: row.places, madeFor: "ranged" }))).toBe(
      JSON.stringify(valueOfKit({ bundle: without, records: table.records, race: row.race, role: row.role, buffs: "own", evidence: "wiki", places: row.places })),
    );
    expect(valueOfKit({ bundle: without, records: table.records, race: row.race, role: row.role, buffs: "own", evidence: "wiki", places: row.places, madeFor: "ranged" }).setup).not.toBe("ranged");
  });
  it("is ignored at an evidence level whose pool the bundle lists no Bow setup for", () => {
    const strictOnly = structuredClone(bundle);
    for (const role of Object.values(strictOnly.roles)) role.setups_by_evidence.wiki = role.setups_by_evidence.wiki.filter((setup) => setup !== "ranged");
    const asked = (extra) => valueOfKit({ bundle: strictOnly, records: table.records, race: row.race, role: row.role, buffs: "own", evidence: "wiki", places: row.places, ...extra });
    expect(JSON.stringify(asked({ madeFor: "ranged" }))).toBe(JSON.stringify(asked({})));
  });
  it("is ignored for a kit with no bow in its range place: the kit is valued as today", () => {
    const noBow = { ...row, places: row.places.filter((place) => place.slotIndex !== RANGE) };
    expect(JSON.stringify(value(noBow, { madeFor: "ranged" }))).toBe(JSON.stringify(value(noBow)));
    const charm = { ...row, places: [...noBow.places, { slotIndex: RANGE, key: "w90030", tier: 4 }] }; // (an item that is no bow, where the link puts it or not: not a bow)
    expect(JSON.stringify(value(charm, { madeFor: "ranged" }))).toBe(JSON.stringify(value(charm)));
  });
});

describe("a kit with no marker", () => {
  it("is valued as it was: the answer has the keys it had and says nothing of a named setup", () => {
    for (const setup of ["dw", "2h", "1h-shield"]) {
      for (const row of rowsOf(setup).slice(0, 2)) {
        const answer = value(row);
        expect(Object.keys(answer).sort()).toEqual(["F", "buffs", "counted", "evaluations", "exact", "hasteAssumed", "left", "setup", "value"]);
        expect(answer.setup).not.toBe("ranged");
        expect(Number.isFinite(answer.value)).toBe(true);
      }
    }
  });
});
