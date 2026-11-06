// The weapon tier rate of the best kit: the percent of damage a weapon grows a tier, 5 or 10, which a request names in `options: {weaponTierRate}`. The rule
// `tier.weapon_damage_pct` (10) is the default, and `at_tier(weapon_pct=)` is Python's reference. fixtures/site/weapon-rate.json (pipeline/tests/engine_fixture.py makes it, and
// test_site_engine_fixture.py keeps it current) has views of the whole pool at +10, +4 and +0, each with the answer that Python gives at 5 and at 10 and with the rate left to the
// rules. The worker's mode, asked for the same view and tier with the same rate, must give that answer: the exact value as a reduced p/q text, the kit place for place, the
// optional buffs and the haste assumed. The pool, its pruning and the evaluator all use the rate (the items of the pool carry the damage it gives), and nothing else changes.

import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { BestKitError, bestKit } from "../pipeline/trioforge/site/static/engine/bestkit.js";
import { readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { createScenarioEngine } from "../pipeline/trioforge/site/static/engine/scenario.js";
import { BASE, BUNDLE_BYTES, ITEMS_BYTES, WEAPON_RATE, makeSite, siteFetch } from "./engine-site-fixture.mjs";
import { bestKitRequest, harness, pageChecks } from "./best-kit-harness.mjs";

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const answerOf = (c) => ({ F: c.F, value: c.value, kit: c.kit, buffs: c.buffs, hasteAssumed: c.hasteAssumed });
const fieldsOf = (message) => ({ F: message.F, value: message.value, kit: message.kit, buffs: message.buffs, hasteAssumed: message.hasteAssumed });
const request = (c, rate) => bestKitRequest(c.scenario, c.tier, c.weights, rate === undefined ? {} : { options: { weaponTierRate: rate } });
const identsOf = (kit) => kit.map((item) => (item === null ? null : `${item.key}@${item.tier}`));

describe("the reference", () => {
  it("has the views the fixture promises: two-handers, dual wield and a shield, +10 and +4 and +0, and weights with a rate", () => {
    expect(WEAPON_RATE).toMatchObject({ trio: "pal-mnk-ber", level: 50 });
    expect(new Set(WEAPON_RATE.cases.map((c) => c.scenario.setup))).toEqual(new Set(["2h", "dw", "1h-shield"]));
    expect(new Set(WEAPON_RATE.cases.map((c) => c.tier))).toEqual(new Set([0, 4, 10]));
    expect(WEAPON_RATE.cases.some((c) => c.weights !== undefined)).toBe(true);
    const moved = WEAPON_RATE.cases.filter((c) => c.rates["5"].F !== c.rates["10"].F);
    expect(moved.length).toBeGreaterThanOrEqual(4);
    expect(moved.some((c) => JSON.stringify(c.rates["5"].kit) !== JSON.stringify(c.rates["10"].kit))).toBe(true);
    expect(WEAPON_RATE.cases.filter((c) => c.rates["5"].F === c.rates["10"].F).every((c) => c.tier === 0)).toBe(true);
  });
});

describe("the worker's best kit at a weapon tier rate", () => {
  for (const c of WEAPON_RATE.cases) {
    for (const rate of [5, 10]) {
      it(`gives Python's answer at ${rate} percent for ${c.name}`, async () => {
        const h = harness({ solver: highs });
        await h.start();
        const built = request(c, rate);
        const { id, last, messages } = await h.ask(built);
        expect(last).toMatchObject({ type: "result", mode: "best-kit", status: "optimal", proven: true, label: null });
        expect(fieldsOf(last)).toEqual(answerOf(c.rates[String(rate)])); // the exact value, the kit place for place, the buffs, the haste
        expect(last.kit.filter((ident) => ident !== null).every((ident) => ident.endsWith(`@${c.tier}`))).toBe(true);
        expect(pageChecks(built, id, messages).at(-1).F).toBe(c.rates[String(rate)].F);
      });
    }

    it(`gives the answer at 10 percent with no rate, with an empty options and with the rate of the rules: ${c.name}`, async () => {
      const h = harness({ solver: highs });
      await h.start();
      const none = (await h.ask(request(c))).last;
      expect(fieldsOf(none)).toEqual(answerOf(c.rules));
      expect(fieldsOf(none)).toEqual(answerOf(c.rates["10"]));
      const empty = (await h.ask(bestKitRequest(c.scenario, c.tier, c.weights, { options: {} }))).last;
      expect(fieldsOf(empty)).toEqual(fieldsOf(none));
    });
  }

  it("moves the answer between 5 and 10 where Python's does and nowhere else", async () => {
    const h = harness({ solver: highs });
    await h.start();
    for (const c of WEAPON_RATE.cases) {
      const five = (await h.ask(request(c, 5))).last;
      const ten = (await h.ask(request(c, 10))).last;
      expect(five.F === ten.F, c.name).toBe(c.rates["5"].F === c.rates["10"].F);
      expect(JSON.stringify(five.kit) === JSON.stringify(ten.kit), c.name).toBe(JSON.stringify(c.rates["5"].kit) === JSON.stringify(c.rates["10"].kit));
    }
  });

  it("asked for one rate after another, answers each for its own rate: a session is made for the request and closed with it", async () => {
    const h = harness({ solver: highs });
    await h.start();
    const c = WEAPON_RATE.cases.find((candidate) => candidate.tier === 10 && candidate.rates["5"].F !== candidate.rates["10"].F);
    const order = [10, 5, 10, undefined, 5];
    for (const rate of order) {
      const got = (await h.ask(request(c, rate))).last;
      expect(fieldsOf(got), `rate ${rate}`).toEqual(answerOf(c.rates[String(rate ?? 10)]));
    }
    expect(h.scenarios.stats().bestKits).toBe(order.length);
  });
});

describe("the best kit function at a weapon tier rate", () => {
  const table = readItemTable(JSON.parse(ITEMS_BYTES.toString("utf8")));
  const bundle = readBundle(JSON.parse(BUNDLE_BYTES.toString("utf8")));
  const solve = (c, rate, over = {}) =>
    bestKit({ highs, records: table.records, bundle, scenario: c.scenario, tier: c.tier, weights: c.weights, budgetMs: 120_000, canonical: true, ...(rate === undefined ? {} : { weaponTierRate: rate }), ...over });

  it("gives Python's canonical answer at each rate, kit place for place", () => {
    for (const c of WEAPON_RATE.cases) {
      for (const rate of [5, 10]) {
        const got = solve(c, rate);
        const want = c.rates[String(rate)];
        expect(got.answer.F.toString(), `${c.name} at ${rate}`).toBe(want.F);
        expect(identsOf(got.answer.kit), `${c.name} at ${rate}`).toEqual(want.kit);
        expect(got.answer.buffs).toEqual(want.buffs);
        expect(got.answer.hasteAssumed).toBe(want.hasteAssumed);
      }
    }
  });

  it("makes the pool, the pruned pool and the kit of the items the rate gives: the damage of a two-hander at +10 is 54 at 5 percent and 72 at 10", () => {
    const c = WEAPON_RATE.cases.find((candidate) => candidate.scenario.setup === "2h" && candidate.tier === 10);
    const damage = (items) => items.find((item) => item.key === "w80524")?.weapon.dmg; // a two-hander of 36 damage in the invented catalog
    const wants = { 5: 36 + Math.floor((36 * 10 * 5) / 100), 10: 36 + Math.floor((36 * 10 * 10) / 100) }; // no minimum step a tier
    expect(wants).toEqual({ 5: 54, 10: 72 });
    for (const rate of [5, 10, undefined]) {
      const got = solve(c, rate);
      const want = wants[rate ?? 10];
      expect(damage(got.pool), `the pool at ${rate}`).toBe(want);
      expect(damage(got.pruned), `the pruned pool at ${rate}`).toBe(want);
      expect(damage(got.answer.kit.filter((item) => item !== null)), `the kit at ${rate}`).toBe(want); // the evaluator values the kit with it
    }
  });

  it("does not read the rate for a weapon that has not grown: at +0 the pool is the same at both rates", () => {
    const c = WEAPON_RATE.cases.find((candidate) => candidate.tier === 0);
    const damages = (rate) => solve(c, rate).pool.map((item) => [item.key, item.weapon?.dmg ?? null]);
    expect(damages(10)).toEqual(damages(5));
  });

  it("takes the rate 5 and the rate 10 and no other, as a choice the bundle does not have", () => {
    const c = WEAPON_RATE.cases[0];
    for (const rate of [0, 1, 7, 15, 50, "5", "10", 5.5, null, true, [5], {}, Number.NaN, Infinity]) {
      expect(() => solve(c, rate), String(rate)).toThrow(BestKitError);
    }
    expect(() => solve(c, 5)).not.toThrow();
  });
});

describe("the scenario engine's best kit with a rate that the protocol did not check", () => {
  it("is a bad request for a rate other than 5 or 10, and for an option it does not read", async () => {
    const site = makeSite();
    const fetching = siteFetch(site);
    const engine = createScenarioEngine({ highs, fetchImpl: fetching.fetchImpl, baseUrl: BASE });
    const c = WEAPON_RATE.cases[0];
    const raw = { ...request(c, 10), options: { weaponTierRate: 7 } };
    await expect(engine.bestKit(raw, { manifest: site.manifest })).rejects.toMatchObject({ code: "bad-request" });
    await expect(engine.bestKit({ ...raw, options: { weaponTierRate: 10, lock: [] } }, { manifest: site.manifest })).rejects.toMatchObject({ code: "bad-request" });
    const good = await engine.bestKit({ ...raw, options: { weaponTierRate: 10 } }, { manifest: site.manifest });
    expect(fieldsOf(good)).toEqual(answerOf(c.rates["10"]));
    engine.close();
  });
});
