// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// The worn haste chip of a row the optimizer's answer fills (race-explain, fix round): the answer's items come from the item table (ui/weights.js), not from a shard, so an item that no loaded
// shard lists has no stats text to take the haste from. The item then carries its worn haste at the tier of the answer, from its record, made by the one rule the engine's `atTier` uses
// (`wornHaste`, engine/tiers.js: `atTier` calls it too), and the step a tier is the page's own (`data-haste-tier` of the main element, the rule `haste.worn_per_tier` as the build read it).
//
// Every name and number of the item is invented (pipeline/tests/test_site_fixture_items.py).

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { atTier } from "../pipeline/trioforge/site/static/engine/items.js";
import { MAX_TIER, wornHaste } from "../pipeline/trioforge/site/static/engine/tiers.js";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";
import { BUNDLE_BYTES, ITEMS_BYTES, makeSite, siteFetch } from "./engine-site-fixture.mjs";
import { REFERENCE } from "./best-kit-harness.mjs";
import { $, $$, mountPage } from "./upgrade-helpers.mjs";
import { fakeEngine } from "./upgrade-answer-helpers.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CONTRACT = resolve(ROOT, "fixtures/site/contract");
const shardFile = (name) => JSON.parse(readFileSync(resolve(CONTRACT, `data/${name}.json`), "utf8"));
const TABLE = JSON.parse(ITEMS_BYTES.toString("utf8"));
const BUNDLE = JSON.parse(BUNDLE_BYTES.toString("utf8"));
const encode = (value) => new TextEncoder().encode(JSON.stringify(value));
const [AC2] = REFERENCE.cases;
const WAIST = 16; // the place of the belt in a kit
const [STEP_TOP, STEP_BOTTOM = "1"] = String(BUNDLE.tier_rules.haste_per_tier).split("/"); // (a rule of the bundle is an exact fraction, "1/1")
const STEP = Number(STEP_TOP) / Number(STEP_BOTTOM);

/** An item that is in no shard of the fixture: invented, with worn haste 37 at +0. */
const SASH = { id: 90999, name: "Gale-Hide Sash", slots: ["WAIST"], stats: { HASTE: 37, AGI: 4 }, weight10: 3, tier_rule: "drop", evidence: { level: "strict" }, source: { sold: ["Freeport"] } };
const PLAIN = { id: 90998, name: "Dull Sash", slots: ["WAIST"], stats: { AGI: 4 }, weight10: 3, tier_rule: "drop", evidence: { level: "strict" }, source: { sold: ["Freeport"] } };

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

function open(extra) {
  const table = { ...TABLE, count: TABLE.items.length + extra.length, items: [...TABLE.items, ...extra] };
  const site = makeSite({ items: encode(table) });
  mountPage();
  document.getElementById("main").dataset.ev = "wiki";
  window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
  site.files.set("/engine-manifest.json", encode(site.manifestJson));
  const net = siteFetch(site);
  const engine = fakeEngine();
  const fetchImpl = async (url, init) => {
    const path = new URL(String(url), "https://trioforge.test").pathname;
    const view = /^\/data\/pal-mnk-ber\/(.+)\.json$/.exec(path);
    if (view === null) return net.fetchImpl(url, init);
    return { ok: true, status: 200, json: async () => structuredClone(shardFile(view[1])) };
  };
  const app = initTrio({ document, window, fetch: fetchImpl, reload: vi.fn(), loadEngine: engine.loadEngine, loadWeights: () => import("../pipeline/trioforge/site/static/ui/weights.js") });
  return { app, engine };
}

const change = (element) => element.dispatchEvent(new Event("change", { bubbles: true }));
const result = (kit) => ({ kind: "scenario", mode: "best-kit", status: "optimal", proven: true, label: null, F: AC2.F, value: AC2.value, kit, buffs: [...AC2.buffs], hasteAssumed: AC2.hasteAssumed, elapsedMs: 12 });
const kitWith = (...idents) => AC2.kit.map((ident, place) => idents.find(([at]) => at === place)?.[1] ?? ident);
const sent = (t, count) => vi.waitFor(() => expect(t.engine.runs).toHaveLength(count), { timeout: 4000, interval: 10 });
const rows = () => $$("#kit-body tr");
const seen = (row) => {
  const chip = row.querySelector(".kit-haste");
  return chip === null || chip.hidden ? "" : chip.textContent;
};
const chips = () => rows().map(seen);

async function solved(t, kit, count = 1) {
  if (count === 1) {
    $("#buffs-own").checked = true;
    change($("#buffs-own"));
    await t.app.whenIdle();
    const details = $("#assume-weights");
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
    await t.app.whenIdle();
    const slider = $("#w-0-2");
    slider.checked = true;
    change(slider);
  } else {
    $("#sw-tier").value = "10";
    change($("#sw-tier"));
  }
  await sent(t, count);
  t.engine.runs[count - 1].finish(result(kit));
  await vi.waitFor(() => expect($("#solve h3")?.textContent).toBe("Solved for your settings"));
}

describe("the rule the chip and the engine share", () => {
  it("is the one function that atTier calls: an item's worn haste at every tier is atTier's, for every item of the fixture's table", () => {
    let checked = 0;
    for (const record of TABLE.items) {
      for (let tier = 0; tier <= MAX_TIER; tier += 1) {
        expect(wornHaste(record.stats?.HASTE ?? 0, tier, STEP), `${record.name} at +${tier}`).toBe(atTier(record, tier, BUNDLE).haste);
        checked += 1;
      }
    }
    expect(checked).toBeGreaterThan(400);
    expect(TABLE.items.some((record) => record.stats?.HASTE > 0)).toBe(true);
  });

  it("raises a worn haste by the step for each tier, leaves an item with none alone, and does not raise a slow piece", () => {
    expect(wornHaste(37, 0, 1)).toBe(37);
    expect(wornHaste(37, 4, 1)).toBe(41);
    expect(wornHaste(37, 10, 1)).toBe(47);
    expect(wornHaste(37, 4, 2)).toBe(45);
    expect(wornHaste(0, 4, 1)).toBe(0);
    expect(wornHaste(-3, 4, 1)).toBe(-3);
  });

  it("has its step from the page, the same as the bundle's rule (the build reads it from the rules: pipeline/tests/test_site_kit_haste.py)", () => {
    mountPage();
    expect(document.getElementById("main").dataset.hasteTier).toBe(String(STEP));
  });
});

describe("an answer of the optimizer", () => {
  it("shows the chip of an item that no shard lists, at the tier of the answer: the record's haste and the step of the tier", async () => {
    const t = open([SASH]);
    await solved(t, kitWith([WAIST, "w90999@4"]));
    expect($$("#kit-body [data-f=\"name\"]")[WAIST].textContent).toBe("Gale-Hide Sash");
    expect(seen(rows()[WAIST])).toBe(`Haste ${37 + 4 * STEP}%`);
    // a shard lists the Gold Hoop of Haste: its chip is the one its stats say, and the sash is the only other chip
    expect(chips().filter(Boolean).sort()).toEqual([`Haste ${15 + 4 * STEP}%`, `Haste ${37 + 4 * STEP}%`].sort());
  });

  it("follows the tier of the answer: the same item says the haste of +10 when the answer is for +10", async () => {
    const t = open([SASH]);
    await solved(t, kitWith([WAIST, "w90999@4"]));
    await solved(t, kitWith([WAIST, "w90999@10"]), 2);
    await vi.waitFor(() => expect(seen(rows()[WAIST])).toBe(`Haste ${37 + 10 * STEP}%`));
  });

  it("shows no chip for an item whose record has no worn haste, for an item the table does not have, and for a place left empty", async () => {
    const t = open([PLAIN]);
    await solved(t, kitWith([WAIST, "w90998@4"], [17, "w424242@4"]));
    expect(seen(rows()[WAIST])).toBe("");
    expect(seen(rows()[17])).toBe("");
    expect(seen(rows()[21])).toBe("");
  });

  it("takes only a whole worn haste above zero of a record: nothing for a hostile or a slow one", async () => {
    for (const haste of [-5, 0, 2.5, "41", null, Number.MAX_SAFE_INTEGER + 1]) {
      const t = open([{ ...SASH, stats: { HASTE: haste } }]);
      await solved(t, kitWith([WAIST, "w90999@4"]));
      expect(seen(rows()[WAIST]), String(haste)).toBe("");
      document.body.innerHTML = "";
    }
  });

  it("agrees with the page on an item both know: a shard's own text and the record's haste say the same figure at the tier", async () => {
    const t = open([]);
    await solved(t, kitWith([2, "w90008@4"]));
    expect(seen(rows()[2])).toBe(`Haste ${15 + 4 * STEP}%`);
    expect(rows()[2].querySelector('[data-f="stats"]').textContent).toContain(`Haste +${15 + 4 * STEP}%`);
  });
});
