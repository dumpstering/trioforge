// The value of a kit in the page, held to the worker's own answer for the same kit: the kit is the whole owned set of an Equip now request, so the best kit the optimizer finds from it is
// the kit itself when the kit is the best arrangement of its items under the view, and its value is the kit's value with the best buffs of the set. The optimizer is the real one (HiGHS,
// through the scenario engine the worker uses), the data is the synthetic site fixture's (every name in it is invented), and the page's evaluator (static/engine/kitvalue.js) has to give
// the exact value, the setup of the kit's hands and the haste of the model's rule that the worker's answer has, for every buff set the bundle offers, the raid set (32 buffs, 8 pairs that
// exclude each other, a cap of 15) included. The same numbers are in fixtures/site/kit-values.json, from Python's reference; this holds them to the code that ships.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { valueOfKit } from "../pipeline/trioforge/site/static/engine/kitvalue.js";
import { createScenarioEngine } from "../pipeline/trioforge/site/static/engine/scenario.js";
import { BASE, SLUG, makeSite, siteFetch } from "./engine-site-fixture.mjs";

vi.setConfig({ testTimeout: 120_000 });

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const RESULTS = resolve(ROOT, "fixtures/site/results");
const table = readItemTable(JSON.parse(readFileSync(resolve(RESULTS, "items.json"), "utf8")));
const bundle = JSON.parse(readFileSync(resolve(RESULTS, "pal-mnk-ber/engine-l50.json"), "utf8"));
const { kits, values } = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/kit-values.json"), "utf8"));

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const placesOf = (kit) => kit.flatMap((ident, slotIndex) => (ident === null ? [] : [{ slotIndex, key: ident.slice(0, ident.lastIndexOf("@")), tier: Number(ident.slice(ident.lastIndexOf("@") + 1)) }]));
const ownedOf = (kit) => {
  const counts = new Map();
  for (const ident of kit) if (ident !== null) counts.set(ident, (counts.get(ident) ?? 0) + 1);
  return [...counts];
};

describe("the page's value of a kit and the optimizer's answer for the same kit", () => {
  const site = makeSite();
  const net = siteFetch(site);
  const engine = () => createScenarioEngine({ highs, fetchImpl: net.fetchImpl, baseUrl: BASE, now: () => performance.now() });

  /** The worker's answer to Equip now with the kit as the owned set, at the weapon setup of the kit's hands. */
  async function workerAnswer(scenarios, kit, role, buffs) {
    const scenario = { race: kit.race, role, buffs, evidence: kit.evidence, setup: kit.setup, ...(kit.deity === null ? {} : { deity: kit.deity }) };
    const request = { v: 1, kind: "scenario", trio: SLUG, level: 50, mode: "equip-now", scenario, owned: ownedOf(kit.kit), budgetMs: 120_000 };
    return scenarios.equipNow(request, { manifest: site.manifest, onProgress() {} });
  }

  // the worker takes a setup that the role offers (the melee role has no shield), as the page's own switches do; the evaluator takes any, and the rows of the others are the reference's only
  const offered = (row) => bundle.roles[row.role].setups_by_evidence[kits[row.kit].evidence].includes(kits[row.kit].setup);
  const rows = values.filter(offered).map((row) => [`${kits[row.kit].name} / ${row.role} / ${row.buffs}`, row]);
  it("asks the worker for the rows whose setup the role offers: most of them", () => {
    expect(rows.length).toBeGreaterThanOrEqual(50);
    expect(rows.length).toBeLessThan(values.length);
  });

  it.each(rows)("gives the value the worker gives, the buffs' worth and the haste included: %s", async (_, row) => {
    const kit = kits[row.kit];
    const scenarios = engine();
    const worker = await workerAnswer(scenarios, kit, row.role, row.buffs);
    expect(worker).toMatchObject({ status: "optimal", proven: true });
    expect(worker.kit, "the best kit from the kit's own items is the kit").toEqual(kit.kit);
    const page = valueOfKit({ bundle, records: table.records, race: kit.race, role: row.role, buffs: row.buffs, evidence: kit.evidence, deity: kit.deity, places: placesOf(kit.kit) });
    expect(page.F).toBe(worker.F);
    expect(page.value).toBe(worker.value);
    expect(page.hasteAssumed).toBe(worker.hasteAssumed);
    expect(page.exact).toBe(true);
    // the optional buffs it chose are as good as the worker's: the same value (the sets themselves may differ where two are worth the same)
    const set = bundle.buffs[row.buffs].set;
    expect(page.buffs.length).toBeLessThanOrEqual(set.cardinality ?? Infinity);
    expect(worker.buffs.length).toBeLessThanOrEqual(set.cardinality ?? Infinity);
  });
});
