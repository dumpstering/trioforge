// The best kit under the sliders, the custom weights and the regen window, held to Python's reference. fixtures/site/best-kit.json (pipeline/tests/engine_fixture.py makes it, and
// test_site_engine_fixture.py keeps it current) has views of the whole pool of the invented catalog, each at a tier and with the weights a request carries, and the answer that Python
// gives for it: the profile's weights composed by `weights_override`, the precompute's pruning, the model, the canonical solve and the exact value of the kit. The worker's mode, asked
// for the same view, tier and weights, must give that answer: the exact value as a reduced p/q text, the kit place for place, the optional buffs and the haste assumed. A view with
// weights also has the answer at the role's own weights, and the weights must move the answer there as Python's do: the kit or its value.

import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { bestKit } from "../pipeline/trioforge/site/static/engine/bestkit.js";
import { readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";
import { BUNDLE_BYTES, ITEMS_BYTES } from "./engine-site-fixture.mjs";
import { REFERENCE, caseRequest, harness, pageChecks } from "./best-kit-harness.mjs";

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const answerOf = (c) => ({ F: c.F, value: c.value, kit: c.kit, buffs: c.buffs, hasteAssumed: c.hasteAssumed });
const fieldsOf = (message) => ({ F: message.F, value: message.value, kit: message.kit, buffs: message.buffs, hasteAssumed: message.hasteAssumed });
const weighted = REFERENCE.cases.filter((c) => c.weights !== undefined);
const plain = REFERENCE.cases.filter((c) => c.weights === undefined);

describe("the reference", () => {
  it("has the views the fixture promises: the sliders at x0.5 and x2 of every group, a custom weight, a window, the four buff sets (and three of their haste twins) and a deity", () => {
    expect(REFERENCE).toMatchObject({ trio: "pal-mnk-ber", level: 50 });
    expect(weighted.length).toBeGreaterThanOrEqual(10);
    expect(plain.length).toBeGreaterThanOrEqual(2);
    expect(new Set(REFERENCE.cases.map((c) => c.scenario.buffs))).toEqual(new Set(["own", "group", "group+enchanter", "raid", "own+haste", "group+enchanter+haste", "raid+haste"]));
    expect(new Set(weighted.flatMap((c) => Object.keys(c.weights.multipliers ?? {})))).toEqual(new Set(["AC", "MANA", "ATK+HASTE", "SV", "regen"]));
    expect(new Set(weighted.flatMap((c) => Object.values(c.weights.multipliers ?? {})))).toEqual(new Set([0.5, 2]));
    expect(weighted.some((c) => c.weights.custom !== undefined) && weighted.some((c) => c.weights.regenT !== undefined)).toBe(true);
    expect(REFERENCE.cases.some((c) => c.scenario.deity !== undefined)).toBe(true);
  });
});

describe("the worker's best kit with the weights of a request", () => {
  for (const c of REFERENCE.cases) {
    it(`gives Python's answer for ${c.name}`, async () => {
      const h = harness({ solver: highs });
      await h.start();
      const request = caseRequest(c);
      const { id, last, messages } = await h.ask(request);
      expect(last).toMatchObject({ type: "result", mode: "best-kit", status: "optimal", proven: true, label: null });
      expect(fieldsOf(last)).toEqual(answerOf(c)); // the exact value, the kit place for place, the buffs, the haste
      expect(last.kit.filter((ident) => ident !== null).every((ident) => ident.endsWith(`@${c.tier}`))).toBe(true);
      expect(pageChecks(request, id, messages).at(-1).F).toBe(c.F);
    });
  }

  for (const c of weighted) {
    it(`moves the kit or its value from the role's own as Python's weights do, and gives Python's own answer without them: ${c.name}`, async () => {
      const h = harness({ solver: highs });
      await h.start();
      const asked = (await h.ask(caseRequest(c))).last;
      const own = (await h.ask(caseRequest(c, { own: true }))).last;
      expect(fieldsOf(own)).toEqual(answerOf(c.own));
      expect(own.F, "the weights move the value").not.toBe(asked.F);
      expect(Rational.parseLong(asked.F).equals(Rational.parseLong(own.F))).toBe(false);
      const movedKit = JSON.stringify(asked.kit) !== JSON.stringify(own.kit);
      expect(movedKit, "and the kit moves as it does in Python").toBe(JSON.stringify(c.kit) !== JSON.stringify(c.own.kit));
      expect(JSON.stringify(asked.buffs) !== JSON.stringify(own.buffs)).toBe(JSON.stringify(c.buffs) !== JSON.stringify(c.own.buffs));
    });
  }

  it("moves the kit for most of the views, leaves it for some and moves the buffs for one: the reference is not one answer said many times", () => {
    expect(weighted.filter((c) => JSON.stringify(c.kit) !== JSON.stringify(c.own.kit)).length).toBeGreaterThanOrEqual(8);
    expect(weighted.filter((c) => JSON.stringify(c.kit) === JSON.stringify(c.own.kit)).length).toBeGreaterThanOrEqual(2);
    expect(weighted.filter((c) => JSON.stringify(c.buffs) !== JSON.stringify(c.own.buffs)).length).toBeGreaterThanOrEqual(1);
  });
});

describe("the shared function, with the tie stage as the parity test asks for it", () => {
  const table = readItemTable(JSON.parse(ITEMS_BYTES.toString("utf8")));
  const bundle = readBundle(JSON.parse(BUNDLE_BYTES.toString("utf8")));

  it("gives Python's canonical answer for every view of the reference, kit place for place", () => {
    for (const c of REFERENCE.cases) {
      const got = bestKit({ highs, records: table.records, bundle, scenario: c.scenario, tier: c.tier, weights: c.weights, budgetMs: 120_000, canonical: true });
      expect(got.answer.F.toString(), c.name).toBe(c.F);
      expect(got.answer.kit.map((item) => (item === null ? null : `${item.key}@${item.tier}`)), c.name).toEqual(c.kit);
      expect(got.answer.buffs, c.name).toEqual(c.buffs);
      expect(got.answer.hasteAssumed, c.name).toBe(c.hasteAssumed);
    }
  });
});
