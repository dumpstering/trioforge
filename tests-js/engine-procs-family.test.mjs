// The family of the site fixture with a table of procs in its bundle (fixtures/site/results-procs, fixtures/site/procs-family.json, made by pipeline/tests/engine_fixture.py): every other
// bundle of the fixture holds `"procs": null`, so the browser's weapon term with procs, its mote order and its Upgrade answers were held to nothing. Here the worker's four Upgrade modes
// and the page's mote order, run over a bundle with five invented procs, one of them on a Lore weapon that a kit wears, are held to what Python's reference gives with the same table (upgrade.equip_now, farm_path, best_sets and
// every_slot with `BuildOptions(procs=...)`, motes.mote_order with `procs=`): the exact values, the kits, every step, every swap. The same requests over the bundle with no table give the
// answers of the other fixtures, so the table is what moves them.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { atTier, readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { moteWalkOf } from "../pipeline/trioforge/site/static/engine/kitvalue.js";
import { collect } from "../pipeline/trioforge/site/static/engine/motes.js";
import { equipNow as pathEquipNow } from "../pipeline/trioforge/site/static/engine/path.js";
import { procsOf } from "../pipeline/trioforge/site/static/engine/procs.js";
import { buffsetOf, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { closeSession, createSession } from "../pipeline/trioforge/site/static/engine/solve.js";
import { viewProfile } from "../pipeline/trioforge/site/static/engine/view.js";
import { harness, pageChecks } from "./best-kit-harness.mjs";
import { BUNDLE_BYTES, PROCS_BUNDLE_BYTES, PROCS_FAMILY, PROCS_ITEMS_BYTES, SLUG, makeSite } from "./engine-site-fixture.mjs";

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
// the family's item table is the fixture's and a Lore weapon, so its bundle (and the same bundle with no table of procs, which has the same inputs) go with it
const PLAIN_BYTES = new TextEncoder().encode(JSON.stringify({ ...JSON.parse(PROCS_BUNDLE_BYTES.toString("utf8")), procs: null }));
const procsSite = () => makeSite({ items: PROCS_ITEMS_BYTES, bundles: { [SLUG]: { 50: PROCS_BUNDLE_BYTES } } });
const plainSite = () => makeSite({ items: PROCS_ITEMS_BYTES, bundles: { [SLUG]: { 50: PLAIN_BYTES } } });
const pick = (object, keys) => Object.fromEntries(keys.map((key) => [key, object[key]]));
const ANSWER = ["F", "value", "kit", "buffs", "hasteAssumed"];
const START = ["F", "value", "kit", "buffs"];
const STEP = ["ident", "kind", "sourceTier", "F", "value", "gain", "gainValue", "kit", "buffs", "hasteAssumed"];
const stepsOf = (messages) => messages.filter((message) => message.type === "step");

const request = (c, mode, over = {}) => ({ v: 1, kind: "scenario", trio: SLUG, level: 50, mode, scenario: { ...c.scenario }, owned: c.owned.map((pair) => [...pair]), budgetMs: 120_000, ...over });
const equip = (c, over) => request(c, "equip-now", over);
const farm = (c, over) => request(c, "farm-path", { tierMode: { ...c.tierMode }, steps: c.farmPath.steps, ...over });
const sets = (c, k, over) => request(c, "best-sets", { tierMode: { ...c.tierMode }, k, ...over });
const slots = (c, over) => request(c, "every-slot", { tierMode: { ...c.tierMode }, kit: [...c.everySlot.kit], buffs: [...c.everySlot.buffs], limit: c.everySlot.limit, ...over });

describe("the reference", () => {
  it("is the invented family with six procs (two on a Lore weapon, one of them on a plain weapon as well), answered for four cases, and moves every answer from the bundle with none", () => {
    const bundle = JSON.parse(PROCS_BUNDLE_BYTES.toString("utf8"));
    expect(JSON.parse(BUNDLE_BYTES.toString("utf8")).procs).toBeNull();
    expect(bundle.procs.effects.map((row) => row[0])).toEqual(PROCS_FAMILY.procs.map((row) => row[0]).sort()); // (the bundle holds the effects by id)
    expect(bundle.procs.socket_tier).toBe(4);
    expect(bundle.procs.donors.filter((row) => row[5] === 1).map((row) => row[1]), "one Lore item, which the Lore case wears (it carries two effects)").toEqual(["w91101", "w91101"]);
    expect(bundle.procs.donors.filter((row) => row[0] === "e-prop-squall").map((row) => row[1]), "H3: the Lore weapon's key is the smaller of the two donors of Prop Squall").toEqual(["w91101", "w91102"]);
    expect(PROCS_FAMILY.cases.map((c) => [c.index, c.variant ?? null])).toEqual([[0, null], [1, null], [2, null], [0, "lore"]]);
    expect(PROCS_FAMILY.cases.every((c) => c.equipNow.F !== c.withoutProcs.F)).toBe(true);
    expect(PROCS_FAMILY.motes.length).toBe(5);
  });
});

describe("the worker's four Upgrade modes over a bundle with a table of procs", () => {
  for (const c of PROCS_FAMILY.cases) {
    it(`gives Python's Equip now for ${c.name}, and the plain bundle gives the answer without procs`, async () => {
      const h = harness({ solver: highs, site: procsSite() });
      await h.start();
      const built = equip(c);
      const { id, last, messages } = await h.ask(built);
      expect(last).toMatchObject({ type: "result", mode: "equip-now", status: "optimal", proven: true, label: null });
      expect(pick(last, ANSWER)).toEqual(pick(c.equipNow, ANSWER));
      expect(pageChecks(built, id, messages).at(-1).F).toBe(c.equipNow.F);
      const plain = harness({ solver: highs, site: plainSite() });
      await plain.start();
      const bare = (await plain.ask(equip(c))).last;
      expect(bare.F).toBe(c.withoutProcs.F);
      expect(bare.kit).toEqual(c.withoutProcs.kit);
      expect(bare.F).not.toBe(last.F);
    });

    it(`takes Python's farm path for ${c.name}`, async () => {
      const h = harness({ solver: highs, site: procsSite() });
      await h.start();
      const built = farm(c);
      const { id, last, messages } = await h.ask(built);
      const steps = stepsOf(pageChecks(built, id, messages));
      expect(pick(steps[0], START)).toEqual(c.farmPath.start);
      expect(steps.slice(1).map((step) => pick(step, STEP))).toEqual(c.farmPath.path);
      expect(last).toMatchObject({ type: "result", mode: "farm-path", stopped: c.farmPath.stopped, steps: c.farmPath.path.length });
    });

    for (const k of [2, 3]) {
      it(`gives Python's best ${k} sets for ${c.name}`, async () => {
        const h = harness({ solver: highs, site: procsSite() });
        await h.start();
        const built = sets(c, k);
        const { id, last, messages } = await h.ask(built);
        expect(last).toMatchObject({ type: "result", mode: "best-sets", k, status: "optimal", proven: true, label: null });
        const got = {
          k: last.k,
          acquired: last.acquired.map(({ ident, kind, sourceTier }) => ({ ident, kind, sourceTier })),
          ...pick(last, ["F", "value", "gain", "gainValue", "kit", "buffs", "hasteAssumed"]),
          baseline: last.baseline,
        };
        expect(got).toEqual(c.bestSets.find((set) => set.k === k));
        expect(pageChecks(built, id, messages).at(-1).F).toBe(got.F);
      });
    }

    it(`gives Python's swaps for every place for ${c.name}`, async () => {
      const h = harness({ solver: highs, site: procsSite() });
      await h.start();
      const built = slots(c);
      const { id, last, messages } = await h.ask(built);
      const rows = last.rows.map((row) => ({ place: row.place, index: row.index, current: row.current, swaps: row.swaps.map(({ ident, delta, deltaValue }) => ({ ident, delta, deltaValue })) }));
      expect(rows).toEqual(c.everySlot.rows);
      expect(pageChecks(built, id, messages).at(-1).rows).toHaveLength(22);
    });
  }
});

describe("the page's mote order over a bundle with a table of procs", () => {
  const table = readItemTable(JSON.parse(PROCS_ITEMS_BYTES.toString("utf8")));
  const bundleWith = JSON.parse(PROCS_BUNDLE_BYTES.toString("utf8"));
  const bundleWithout = { ...bundleWith, procs: null };
  const split = (ident) => [ident.slice(0, ident.lastIndexOf("@")), Number(ident.slice(ident.lastIndexOf("@") + 1))];
  const placesOf = (kit) => kit.flatMap((ident, slotIndex) => (ident === null ? [] : [{ slotIndex, key: split(ident)[0], tier: split(ident)[1] }]));
  const walkOf = (row, bundle) => {
    const { race, role, buffs, evidence, setup, deity } = row.scenario;
    return moteWalkOf({ bundle, records: table.records, race, role, buffs, evidence, deity: deity ?? null, setup, chosen: row.buffs, motes: row.motes, places: placesOf(row.kit) });
  };
  const shown = (step) => ({
    index: step.index,
    place: step.place,
    key: step.key,
    from: step.from,
    to: step.to,
    motes: step.motes,
    spent: step.spent,
    gain: step.gain.toString(),
    F: step.F.toString(),
    moved: step.moved.map(([name, amount]) => [name, amount.toString()]),
  });

  it.each(PROCS_FAMILY.motes.map((row) => [row.name, row]))("gives the order Python gives with the table: %s", (_, row) => {
    const result = collect(walkOf(row, bundleWith));
    expect(result.start.toString()).toBe(row.start);
    expect(result.ending).toBe(row.ending);
    expect(result.left).toBe(row.left);
    expect(result.spent).toBe(row.spent);
    expect(result.nextRun).toBe(row.nextRun);
    expect(result.steps.map(shown)).toEqual(row.steps);
  });

  it.each(PROCS_FAMILY.motes.map((row) => [row.name, row]))("gives, over the bundle with no table, the order without procs: %s", (_, row) => {
    const result = collect(walkOf(row, bundleWithout));
    expect(result.steps.map((step) => [step.place, step.key, step.from, step.to, step.gain.toString()])).toEqual(row.withoutProcs);
  });

  it("shows the jump at the socket tier: the mace's step to +4 gains the best proc it can host over its own", () => {
    const row = PROCS_FAMILY.motes.find((one) => one.name.includes("socket tier"));
    const first = collect(walkOf(row, bundleWith)).steps[0];
    const without = collect(walkOf(row, bundleWithout)).steps.find((step) => step.key === "w80113");
    expect([first.key, first.from, first.to]).toEqual(["w80113", 3, 4]);
    expect(first.gain.sub(without.gain).toString()).toBe("8811/1"); // (9,500 against 700 over 600 tenths of a minute, at the Tank's weight of 600.75 on damage: 8,800 x 600.75 / 600 = 8,811, exactly)
  });
});

describe("the donors a proc records, which the evaluator's breakdown names (G4)", () => {
  const document = readBundle(JSON.parse(PROCS_BUNDLE_BYTES.toString("utf8")));
  const records = readItemTable(JSON.parse(PROCS_ITEMS_BYTES.toString("utf8"))).records;
  const shown = (entry) => (entry === null ? null : [entry.effect, entry.donor, entry.mode, entry.value.toString()]);

  it.each(PROCS_FAMILY.cases.map((c) => [c.name, c]))("are Python's for the kit of Equip now: %s", (_, c) => {
    const session = createSession({
      highs,
      profile: viewProfile(document, c.scenario, undefined),
      setup: c.scenario.setup,
      buffset: buffsetOf(document, c.scenario.buffs),
      monkBins: document.monk_bins === null ? undefined : document.monk_bins,
      procs: procsOf(document),
      options: {},
    });
    try {
      const owned = c.owned.map(([name, count]) => [atTier(records.get(name.slice(0, name.lastIndexOf("@"))), Number(name.slice(name.lastIndexOf("@") + 1)), document), count]);
      const got = pathEquipNow(session, owned, { budgetMs: 120_000, canonical: false });
      expect(got.F.toString(), "the same kit and value as Python's").toBe(c.equipNow.F);
      const counted = got.breakdown.totals.procs;
      expect({ PRIMARY: shown(counted.PRIMARY), SECONDARY: shown(counted.SECONDARY) }).toEqual(c.equipNow.procs);
    } finally {
      closeSession(session);
    }
  });

  it("show the Lore rule: the kit wears the Lore weapon in a hand, which counts its own proc, and the other hand hosts the next best, from another donor (H3: the donor is not the smallest key)", () => {
    const c = PROCS_FAMILY.cases.find((one) => one.variant === "lore");
    expect(c.equipNow.kit[20]).toBe("w91101@4");
    expect(c.equipNow.procs.PRIMARY).toEqual(["e-prop-gust", "w91101", "n", "9500/1"]);
    expect(c.equipNow.procs.SECONDARY[1], "the copy that is worn supplies no other hand").not.toBe("w91101");
    expect(c.equipNow.procs.SECONDARY, "Prop Squall has two donors: the Lore weapon (the smaller key, worn in the other hand) and the plain one").toEqual(["e-prop-squall", "w91102", "h", "9200/1"]);
  });
});
