// The choices of a request that the bundle does not have, and what is left of a profile that cannot be made. A race, a role, a buff set, an evidence level, a weapon setup or a deity
// that the bundle does not have is the visitor's choice (a crafted address can carry one), and it is a bad request in every mode of the worker, the best kit and the four Upgrade
// modes: the bundle is not dropped, it is not fetched again, and the worker goes on. Only what is left once every choice is one the bundle has, the bundle's own rules that
// `viewProfile` (engine/bestkit.js) cannot use, is a fault of the data: engine-load, with the bundle dropped. The profile is made by `assembleProfile` (profile.js), which a test
// here makes fail once with an error that is no choice.

import loadHighs from "highs";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { BundleError } from "../pipeline/trioforge/site/static/engine/profile.js";
import { validateFromWorker } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { EQUIP_NOW, SLUG } from "./engine-site-fixture.mjs";
import { bestKitRequest, harness } from "./best-kit-harness.mjs";

const failing = vi.hoisted(() => ({ profile: null }));
vi.mock("../pipeline/trioforge/site/static/engine/profile.js", async (importOriginal) => {
  const real = await importOriginal();
  return {
    ...real,
    assembleProfile(...args) {
      if (failing.profile !== null) {
        const error = failing.profile;
        failing.profile = null;
        throw error;
      }
      return real.assembleProfile(...args);
    },
  };
});

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});
afterEach(() => {
  failing.profile = null;
});

const [C0] = EQUIP_NOW.cases;
const READY4 = { mode: "ready4" };
const base = (scenario, over) => ({ v: 1, kind: "scenario", trio: SLUG, level: 50, scenario: { ...scenario }, owned: C0.owned.map((pair) => [...pair]), budgetMs: 120_000, ...over });
const BUILD = {
  "equip-now": (scenario) => base(scenario, { mode: "equip-now" }),
  "farm-path": (scenario) => base(scenario, { mode: "farm-path", tierMode: { ...READY4 }, steps: 2 }),
  "best-sets": (scenario) => base(scenario, { mode: "best-sets", tierMode: { ...READY4 }, k: 2 }),
  "every-slot": (scenario) => base(scenario, { mode: "every-slot", tierMode: { ...READY4 }, kit: [...C0.kit], buffs: [...C0.buffs] }),
  "best-kit": (scenario) => bestKitRequest(scenario, 4),
};
/** The method of the scenario engine that answers each mode. */
const METHOD = { "equip-now": "equipNow", "farm-path": "farmPath", "best-sets": "bestSets", "every-slot": "everySlot", "best-kit": "bestKit" };
const WRONG = {
  "a race the bundle does not have": [{ race: "ZZZ" }, /race/i],
  "a role the trio is not offered": [{ role: "caster" }, /role/i],
  "a buff set the bundle does not have": [{ buffs: "everything" }, /buff/i],
  "an evidence level the bundle does not have": [{ evidence: "hidden" }, /evidence/i],
  "a weapon setup the role does not play": [{ role: "melee", setup: "1h-shield" }, /setup/i],
};

describe("a choice the bundle does not have is a bad request in every mode", () => {
  for (const mode of Object.keys(BUILD)) {
    for (const [name, [wrong, words]] of Object.entries(WRONG)) {
      it(`${mode}: ${name}: the bundle is kept, nothing is fetched again and the worker goes on`, async () => {
        const h = harness({ solver: highs });
        await h.start();
        const bad = await h.ask(BUILD[mode]({ ...C0.scenario, ...wrong })); // (the first request: it loads the data and then refuses the choice)
        expect(bad.last).toMatchObject({ type: "error", code: "bad-request", id: bad.id });
        expect(bad.last.message).toMatch(words);
        expect(validateFromWorker(bad.last, { id: bad.id, kind: "scenario", mode }).code).toBe("bad-request");
        expect(bad.messages.filter((message) => message.type === "result" || message.type === "step")).toHaveLength(0);
        const next = await h.ask(BUILD[mode](C0.scenario));
        expect(next.last.type, "the next request is answered").not.toBe("error");
        expect(h.asked, "the data was fetched once: the trio's list of files, the item table and the bundle").toHaveLength(3);
        expect(h.scenarios.stats(), "the bundle was not dropped for it").toMatchObject({ bundles: 1, itemTables: 1 });
      });
    }

    it(`${mode}: a deity that is blank, or no name, is a bad request too (the protocol never lets one through, so the engine is asked directly)`, async () => {
      const h = harness({ solver: highs });
      await h.start();
      for (const deity of ["   ", "\t\n", 5, true, ["Karana"]]) {
        await expect(h.scenarios[METHOD[mode]](BUILD[mode]({ ...C0.scenario, deity }), { manifest: h.site.manifest }), JSON.stringify(deity)).rejects.toMatchObject({ code: "bad-request" });
      }
      const next = await h.ask(BUILD[mode](C0.scenario));
      expect(next.last.type).not.toBe("error");
      expect(h.asked).toHaveLength(3);
      expect(h.scenarios.stats()).toMatchObject({ bundles: 1 });
    });
  }
});

describe("what is left after the choices is the bundle's own fault", () => {
  for (const mode of Object.keys(BUILD)) {
    it(`${mode}: a profile that the bundle cannot give for choices that it has is engine-load, and the bundle is dropped and fetched again`, async () => {
      const h = harness({ solver: highs });
      await h.start();
      expect((await h.ask(BUILD[mode](C0.scenario))).last.type).not.toBe("error");
      expect(h.scenarios.stats()).toMatchObject({ bundles: 1 });
      failing.profile = new BundleError("the parts of the profile are not what the exporter writes");
      const faulty = await h.ask(BUILD[mode]({ ...C0.scenario, race: "HUM" })); // (a scenario of its own: no session is kept for it, so the profile is asked for)
      expect(failing.profile, "the fault was reached").toBeNull();
      expect(faulty.last).toMatchObject({ type: "error", code: "engine-load", id: faulty.id });
      expect(faulty.last.message).toMatch(/bundle/i);
      expect(h.scenarios.stats()).toMatchObject({ bundles: 1 });
      const next = await h.ask(BUILD[mode](C0.scenario));
      expect(next.last.type, "the next request is answered").not.toBe("error");
      expect(h.scenarios.stats(), "the bundle that was found wrong was dropped and fetched again").toMatchObject({ bundles: 2 });
    });
  }
});
