// The best kit of a view, in the engine (engine/bestkit.js) and in the worker (the mode "best-kit"): the pool of the view as the precompute makes it, pruned as the precompute prunes it,
// the weights of the role or the weights the request asks for, and one solve. The function is the one the worker calls and the one the shard parity test calls, so that the two can never
// drift; the worker answers without the tie stage (a browser's answer), the parity test with it. The files are those of the synthetic site fixture (the item table and the bundle of
// PAL/MNK/BER, made from an invented catalog), and the solver is the real one.

import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { BestKitError, bestKit, poolRecords, weightsAreOwn } from "../pipeline/trioforge/site/static/engine/bestkit.js";
import { readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { LABEL_NO_INCUMBENT, LABEL_TIME_LIMIT, LIMITS, validateFromWorker } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { weightsOverride } from "../pipeline/trioforge/site/static/engine/weights.js";
import { BUNDLE_BYTES, ITEMS_BYTES, SLUG, makeSite } from "./engine-site-fixture.mjs";
import { FINEST_WEIGHTS, REFERENCE, bestKitRequest, caseRequest, harness, pageChecks, progressOf } from "./best-kit-harness.mjs";
import { spyOn } from "./engine-spy.mjs";

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const TABLE = readItemTable(JSON.parse(ITEMS_BYTES.toString("utf8")));
const BUNDLE = readBundle(JSON.parse(BUNDLE_BYTES.toString("utf8")));
const VIEW = { race: "OGR", role: "balanced", buffs: "own", evidence: "wiki", setup: "dw" };
const TRIBUNAL = "The Tribunal";
const solveView = (over = {}) => bestKit({ highs, records: TABLE.records, bundle: BUNDLE, scenario: VIEW, tier: 4, budgetMs: 120_000, ...over });
const keysOf = (items) => items.map((item) => item.key);
const wornIdents = (kit) => kit.filter((item) => item !== null).map((item) => `${item.key}@${item.tier}`);

// ---- the pool --------------------------------------------------------------------------------------------------------------------------

describe("the records that make the pool of an evidence level", () => {
  const TRIO = ["PAL", "MNK", "BER"];
  const record = (key, over = {}) => ({ id: Number(key.slice(1)), key, name: key, slots: ["HEAD"], tier_rule: "drop", evidence: { level: "strict" }, ...over });
  const table = (...records) => new Map(records.map((one) => [one.key, one]));
  const picked = (records, options = { evidence: "wiki" }) => poolRecords(records, TRIO, options).map((one) => one.key);

  it("are the strict records for the strict level, and the strict and the wiki records for the wiki level, and no record of another level", () => {
    const records = table(record("w1"), record("w2", { evidence: { level: "wiki" } }), record("w3", { evidence: { level: "disputed" } }), record("w4", { evidence: { level: "hidden" }, owned_only: true }));
    expect(picked(records, { evidence: "strict" })).toEqual(["w1"]);
    expect(picked(records, { evidence: "wiki" })).toEqual(["w1", "w2"]);
  });

  it("leave out a record marked not-for-bis at either level, and keep one with another reason code", () => {
    const records = table(
      record("w1", { evidence: { level: "strict", codes: ["not-for-bis"] } }),
      record("w2", { evidence: { level: "wiki", codes: ["not-for-bis", "not-for-default-kits"] } }),
      record("w3", { evidence: { level: "wiki", codes: ["not-for-default-kits"] } }),
      record("w4"),
    );
    expect(picked(records, { evidence: "strict" })).toEqual(["w4"]);
    expect(picked(records)).toEqual(["w3", "w4"]);
  });

  it("leave out a record that only a player may own, whatever its level says", () => {
    expect(picked(table(record("w1", { owned_only: true }), record("w2")))).toEqual(["w2"]);
  });

  it("keep the records that have a place in a kit, and leave out ammunition and the slots no place of a kit has", () => {
    const records = table(
      record("w1", { slots: ["AMMO"] }),
      record("w2", { slots: ["CHARM"] }),
      record("w3", { slots: ["POWERSOURCE"] }),
      record("w4", { slots: ["AMMO", "HEAD"] }),
      record("w5", { slots: ["PRIMARY", "SECONDARY"] }),
      record("w6", { slots: ["RANGE"] }),
    );
    expect(picked(records)).toEqual(["w4", "w5", "w6"]);
  });

  it("keep the records a class of the trio can wear: all classes, one of the trio's, or one of the trio's among others", () => {
    const records = table(
      record("w1", { classes: ["WIZ"] }),
      record("w2", { classes: ["ALL"] }),
      record("w3", { classes: ["PAL"] }),
      record("w4", { classes: ["WIZ", "BER", "CLR"] }),
      record("w5"),
      record("w6", { classes: [] }),
    );
    expect(picked(records)).toEqual(["w2", "w3", "w4", "w5"]);
  });

  it("leave out a record locked to a deity unless the request has that deity, and then keep it", () => {
    const records = table(record("w1"), record("w2", { deity: [TRIBUNAL] }), record("w3", { deity: ["Karana", TRIBUNAL] }), record("w4", { deity: ["Karana"] }));
    expect(picked(records)).toEqual(["w1"]);
    expect(picked(records, { evidence: "wiki", deity: null })).toEqual(["w1"]);
    expect(picked(records, { evidence: "wiki", deity: TRIBUNAL })).toEqual(["w1", "w2", "w3"]);
    expect(picked(records, { evidence: "wiki", deity: "Karana" })).toEqual(["w1", "w3", "w4"]);
    expect(picked(records, { evidence: "wiki", deity: "Brell Serilis" })).toEqual(["w1"]);
  });

  it("are in the order of the table, and leave the race to the profile (the pruning and the builder leave out what a race cannot wear)", () => {
    const records = table(record("w9"), record("w2", { races: ["OGR"] }), record("w5"));
    expect(picked(records)).toEqual(["w9", "w2", "w5"]);
  });

  it("are, for the invented catalog, the 43 strict and the 44 strict and wiki records that the precompute's shards count, and the Tribunal's two more with the deity", () => {
    expect(poolRecords(TABLE.records, BUNDLE.trio, { evidence: "strict" })).toHaveLength(43);
    expect(poolRecords(TABLE.records, BUNDLE.trio, { evidence: "wiki" })).toHaveLength(44);
    expect(poolRecords(TABLE.records, BUNDLE.trio, { evidence: "wiki", deity: TRIBUNAL })).toHaveLength(46);
    expect(poolRecords(TABLE.records, BUNDLE.trio, { evidence: "strict", deity: TRIBUNAL })).toHaveLength(43);
  });
});

describe("the weights that are the role's own", () => {
  it("are none, an empty table, sliders at x1 and no custom weight and no window", () => {
    for (const own of [undefined, null, {}, { multipliers: {} }, { multipliers: { AC: 1, "ATK+HASTE": 1, SV: 1 } }, { custom: {} }, { regenT: null }, { regenT: undefined }, { multipliers: { AC: 1 }, custom: {}, regenT: null }]) {
      expect(weightsAreOwn(own), JSON.stringify(own)).toBe(true);
    }
    for (const other of [{ multipliers: { AC: 2 } }, { multipliers: { AC: 0.5 } }, { multipliers: { AC: 1, SV: 2 } }, { custom: { HP: 1 } }, { regenT: 3 }, { regenT: 0 }, { multipliers: { AC: 1 }, regenT: 10 }]) {
      expect(weightsAreOwn(other), JSON.stringify(other)).toBe(false);
    }
  });
});

// ---- the function -------------------------------------------------------------------------------------------------------------------------

describe("the best kit of a view (bestKit)", () => {
  it("gives the answer of the solve, the profile it solved, the pool of the view, the pruned pool and the milliseconds each part took", () => {
    const got = solveView();
    expect(got.answer).toMatchObject({ status: "optimal", proven: true, label: null, canonical: false, tieStage: null });
    expect(got.answer.kit).toHaveLength(22);
    expect(got.answer.F.toString()).toMatch(/^\d+\/\d+$/);
    expect(got.profile).toMatchObject({ race: "OGR", role: "balanced", evidence: "wiki", level: 50 });
    expect(got.pool).toHaveLength(44);
    expect(got.pruned.length).toBeGreaterThan(0);
    expect(got.pruned.length).toBeLessThan(got.pool.length);
    expect(Object.keys(got.timings).sort()).toEqual(["buildMs", "poolMs", "pruneMs", "solveMs"]);
    for (const ms of Object.values(got.timings)) expect(ms).toBeGreaterThanOrEqual(0);
  });

  it("works with the tie stage when it is asked to, as the parity test asks, and says so", () => {
    const tied = solveView({ canonical: true });
    expect(tied.answer.canonical === true || tied.answer.tieStage === "kept-first").toBe(true);
    expect(["applied", "kept-first"]).toContain(tied.answer.tieStage);
    expect(tied.answer.F.equals(solveView().answer.F)).toBe(true);
  });

  it("solves over the pool at the tier of the request: every item of the pool, of the pruned pool and of the kit is at that tier", () => {
    for (const tier of [0, 4, 10]) {
      const got = solveView({ tier });
      for (const list of [got.pool, got.pruned, got.answer.kit.filter((item) => item !== null)]) {
        expect(list.length).toBeGreaterThan(0);
        expect(new Set(list.map((item) => item.tier))).toEqual(new Set([tier]));
      }
    }
  });

  it("makes the pool of a view the records of its evidence level that the profile can use: the race decides what the race-only items are", () => {
    const ogre = solveView();
    const iksar = solveView({ scenario: { ...VIEW, race: "IKS" } });
    expect(keysOf(ogre.pool)).toContain("w90033"); // sabatons for Ogres and Trolls
    expect(keysOf(iksar.pool)).not.toContain("w90033");
    expect(keysOf(iksar.pool)).toHaveLength(keysOf(ogre.pool).length - 1);
    const strict = solveView({ scenario: { ...VIEW, evidence: "strict" } });
    expect(strict.pool.length).toBeLessThan(ogre.pool.length);
    expect(keysOf(strict.pool)).not.toContain("w90003"); // a wiki-level crown
    expect(keysOf(ogre.pool)).toContain("w90003");
  });

  it("is pruned as the precompute prunes: the kept items are a subset of the pool, in the order of (key, tier), and the best kit wears only kept items", () => {
    const got = solveView();
    const pool = new Set(got.pool);
    expect(got.pruned.every((item) => pool.has(item))).toBe(true);
    const names = got.pruned.map((item) => `${item.key}@${item.tier}`);
    expect(names).toEqual([...names].sort((a, b) => (a.slice(0, a.lastIndexOf("@")) < b.slice(0, b.lastIndexOf("@")) ? -1 : a.slice(0, a.lastIndexOf("@")) > b.slice(0, b.lastIndexOf("@")) ? 1 : 0)));
    const kept = new Set(names);
    expect(wornIdents(got.answer.kit).every((name) => kept.has(name))).toBe(true);
  });

  it("admits the items locked to the deity of the request, and no other: a Troll tank who follows the Tribunal wears a crown that the same Troll without a deity cannot", () => {
    const view = { race: "TRL", role: "tank", buffs: "group", evidence: "wiki", setup: "1h-shield" };
    const without = solveView({ scenario: view });
    const follower = solveView({ scenario: { ...view, deity: TRIBUNAL } });
    const other = solveView({ scenario: { ...view, deity: "Karana" } });
    expect(keysOf(without.pool)).not.toContain("w90004");
    expect(keysOf(follower.pool)).toEqual(expect.arrayContaining(["w90004", "w90046"]));
    expect(keysOf(other.pool)).not.toContain("w90004");
    expect(follower.profile.deity).toBe(TRIBUNAL);
    expect(wornIdents(follower.answer.kit)).toContain("w90004@4");
    expect(wornIdents(without.answer.kit)).not.toContain("w90004@4");
    expect(solveView({ scenario: { ...view, deity: null } }).answer.F.equals(without.answer.F)).toBe(true);
  });

  describe("takes the weights of the role as the bundle has them, or composes the weights of the request", () => {
    const base = BUNDLE.roles.balanced.weights;

    it("without weights, and with weights that are the role's own: the profile of the bundle, its weights the very ones of the bundle", () => {
      for (const weights of [undefined, {}, { multipliers: {} }, { multipliers: { AC: 1, "ATK+HASTE": 1, MANA: 1, SV: 1, regen: 1 } }, { custom: {}, regenT: null }]) {
        const got = solveView({ weights });
        expect(got.profile.weights, JSON.stringify(weights)).toBe(base);
        expect(got.profile).toEqual(assembleProfile(BUNDLE, { race: "OGR", role: "balanced", buffs: "own", evidence: "wiki" }));
      }
    });

    it("with weights that are not: the weights of weightsOverride on the role's own, with the mana of the trio", () => {
      const asked = { multipliers: { AC: 2, "ATK+HASTE": 0.5 }, custom: { HP: 3 }, regenT: 10 };
      const got = solveView({ weights: asked });
      const want = weightsOverride(BUNDLE, base, { ...asked, manaReachable: true });
      expect(got.profile.weights).toEqual(want);
      expect(got.profile.weights).not.toEqual(base);
      expect(Object.isFrozen(got.profile) && Object.isFrozen(got.profile.weights)).toBe(true);
      expect(got.profile.pools).toEqual(assembleProfile(BUNDLE, { race: "OGR", role: "balanced", buffs: "own", evidence: "wiki" }).pools);
      expect(BUNDLE.roles.balanced.weights).toBe(base); // and the bundle's own weights are as they were
    });

    it("leaves mana to the trio: a trio with no mana pool has no weight on mana, whatever the request asks", () => {
      const raw = JSON.parse(BUNDLE_BYTES.toString("utf8"));
      raw.profile_common.pools.MANA = [];
      const dry = readBundle(raw);
      const asked = { multipliers: { MANA: 2 }, custom: { MANA: 5 } };
      const got = bestKit({ highs, records: TABLE.records, bundle: dry, scenario: VIEW, tier: 4, weights: asked, budgetMs: 120_000 });
      expect(got.profile.weights.MANA).toBe(0);
      expect(got.profile.weights.MANAREG).toBe(0);
      const wet = solveView({ weights: asked });
      expect(wet.profile.weights.MANA).toBe(10);
      expect(wet.profile.weights.MANAREG).toBeGreaterThan(0);
    });

    it("composes the same weights whatever order the request lists them in", () => {
      const one = solveView({ weights: { multipliers: { AC: 2, SV: 0.5 }, custom: { HP: 2, CHA: 1 }, regenT: 5 } });
      const two = solveView({ weights: { regenT: 5, custom: { CHA: 1, HP: 2 }, multipliers: { SV: 0.5, AC: 2 } } });
      expect(two.profile.weights).toEqual(one.profile.weights);
      expect(two.answer.F.equals(one.answer.F)).toBe(true);
    });

    it("answers differently when the sliders move, and the same when they move and come back", () => {
      const own = solveView();
      const heavy = solveView({ weights: { multipliers: { AC: 2 } } });
      const light = solveView({ weights: { multipliers: { AC: 0.5 } } });
      const again = solveView({ weights: { multipliers: { AC: 2 } } });
      const back = solveView({ weights: { multipliers: { AC: 1 } } });
      expect(heavy.answer.F.equals(own.answer.F)).toBe(false);
      expect(light.answer.F.equals(own.answer.F)).toBe(false);
      expect(again.answer.F.equals(heavy.answer.F) && JSON.stringify(wornIdents(again.answer.kit)) === JSON.stringify(wornIdents(heavy.answer.kit))).toBe(true);
      expect(back.answer.F.equals(own.answer.F) && JSON.stringify(wornIdents(back.answer.kit)) === JSON.stringify(wornIdents(own.answer.kit))).toBe(true);
    });
  });

  describe("refuses what the visitor asked for that the data does not have, as a BestKitError", () => {
    const REFUSED = {
      "a race the bundle does not have": { scenario: { ...VIEW, race: "ZZZ" } },
      "a role the trio is not offered": { scenario: { ...VIEW, role: "caster" } },
      "a buff set the bundle does not have": { scenario: { ...VIEW, buffs: "everything" } },
      "an evidence level the bundle does not have": { scenario: { ...VIEW, evidence: "hidden" } },
      "a weapon setup the role does not play at that level": { scenario: { ...VIEW, role: "melee", setup: "1h-shield" } },
      "a weapon setup that is not one": { scenario: { ...VIEW, setup: "spear" } },
      "a blank deity": { scenario: { ...VIEW, deity: "   " } },
      "no evidence level": { scenario: { race: "OGR", role: "balanced", buffs: "own", setup: "dw" } },
      "an evidence level that is not text": { scenario: { ...VIEW, evidence: 5 } },
      "a tier above 10": { tier: 11 },
      "a tier below 0": { tier: -1 },
      "a tier that is not whole": { tier: 4.5 },
      "a slider group there is not": { weights: { multipliers: { NOPE: 2 } } },
      "a slider group there is not, at x1": { weights: { multipliers: { NOPE: 1 } } },
      "a slider position that is not one of the three": { weights: { multipliers: { AC: 3 } } },
      "a slider position of 0": { weights: { multipliers: { AC: 0 } } },
      "a slider position between two": { weights: { multipliers: { AC: 1.5 } } },
      "a custom weight that cannot be set": { weights: { custom: { ZZZ: 1 } } },
      "a custom weight that follows another (DMG)": { weights: { custom: { DMG: 5 } } },
      "a custom weight above the largest": { weights: { custom: { HP: 1000.5 } } },
      "a custom weight below 0": { weights: { custom: { HP: -1 } } },
      "a regen window above the longest": { weights: { regenT: 60.5 } },
      "a regen window below 0": { weights: { regenT: -1 } },
    };
    for (const [name, over] of Object.entries(REFUSED)) {
      it(name, () => {
        expect(() => solveView(over)).toThrow(BestKitError);
        try {
          solveView(over);
        } catch (error) {
          expect(error.name).toBe("BestKitError");
          expect(error.message.length).toBeGreaterThan(0);
          expect(error.message.length).toBeLessThan(300);
          expect(error.message).not.toMatch(/[\u0000-\u001f]/);
        }
      });
    }

    it("and takes the largest custom weight, the longest window and the whole range of positions", () => {
      expect(() => solveView({ weights: { custom: { HP: 1000, SV: 0, SV_FIRE: 1000 }, regenT: 60 } })).not.toThrow();
      expect(() => solveView({ weights: { regenT: 0, multipliers: { AC: 0.5, MANA: 2, regen: 1 } } })).not.toThrow();
    });
  });

  it("answers the naked character when the pool has nothing in it: a kit of 22 empty places, and the value of the character with its best buffs", () => {
    const got = bestKit({ highs, records: new Map(), bundle: BUNDLE, scenario: VIEW, tier: 4, budgetMs: 120_000 });
    expect(got.pool).toEqual([]);
    expect(got.pruned).toEqual([]);
    expect(got.answer).toMatchObject({ status: "optimal", proven: true, label: null });
    expect(got.answer.kit).toEqual(new Array(22).fill(null));
    expect(got.answer.F.toNumber()).toBeGreaterThan(0);
    expect(got.answer.F.toNumber()).toBeLessThan(solveView().answer.F.toNumber());
  });

  it("closes the session it made and keeps nothing: every model the solver made for it is disposed when it returns, and when it fails", () => {
    const made = [];
    const spy = spyOn(highs, { created: (solver) => made.push(solver) });
    bestKit({ highs: spy.highs, records: TABLE.records, bundle: BUNDLE, scenario: VIEW, tier: 4, budgetMs: 120_000, canonical: true });
    expect(made.length).toBeGreaterThanOrEqual(2); // the model, and the model of the tie stage
    expect(made.every((solver) => solver.disposed)).toBe(true);
    // a solver that fails in the middle of the solve leaves nothing open either
    made.length = 0;
    const failing = spyOn(highs, {
      created: (solver) => made.push(solver),
      outcome: () => {
        throw new Error("the solver stopped");
      },
    });
    expect(() => bestKit({ highs: failing.highs, records: TABLE.records, bundle: BUNDLE, scenario: VIEW, tier: 4, budgetMs: 120_000 })).toThrow("the solver stopped");
    expect(made.length).toBeGreaterThanOrEqual(1);
    expect(made.every((solver) => solver.disposed)).toBe(true);
  });

  it("is honest when the time is spent: a budget of nothing gives no kit, and the label that says so", () => {
    let clock = 0;
    const got = solveView({ budgetMs: 1, now: () => (clock += 1000) });
    expect(got.answer).toMatchObject({ status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT, kit: null, F: null });
  });

  it("gives the builder's options to the pruning, the model and the solve: an assumed haste of the request's own is the haste of the answer", () => {
    expect(solveView({ options: { haste_assumed: 30 } }).answer.hasteAssumed).toBe(30);
    expect(solveView().answer.hasteAssumed).toBe(54); // and the model's rule, when there are none (44 and the 10 of the Monk's Unbound Alacrity)
    expect(() => solveView({ options: { depth: 3 } })).toThrow();
  });
});

// ---- the worker --------------------------------------------------------------------------------------------------------------------------

describe("the best kit through the worker's handler", () => {
  const [PLAIN, SLIDER] = [REFERENCE.cases.find((c) => c.weights === undefined), REFERENCE.cases.find((c) => c.weights !== undefined)];
  const [PLAIN_CASE, SLIDER_VIEW] = [PLAIN, SLIDER.scenario];

  it("answers a result of the mode with the fields of an answer, as the page checks them, at the tier of the request", async () => {
    const h = harness({ solver: highs });
    await h.start();
    const request = caseRequest(SLIDER);
    const { id, last, messages } = await h.ask(request);
    expect(last).toMatchObject({ v: 1, type: "result", id, kind: "scenario", mode: "best-kit", status: "optimal", proven: true, label: null });
    expect(Object.keys(last).sort()).toEqual(["F", "buffs", "elapsedMs", "hasteAssumed", "id", "kind", "kit", "label", "mode", "proven", "status", "type", "v", "value"].sort());
    expect(last.elapsedMs).toBeGreaterThan(0);
    expect(last.kit).toHaveLength(22);
    expect(last.kit.filter((name) => name !== null).every((name) => name.endsWith(`@${SLIDER.tier}`))).toBe(true);
    // what the page makes of it, with the expectation of the client (the tier of the request in it)
    expect(pageChecks(request, id, messages).at(-1)).toMatchObject({ mode: "best-kit", F: last.F });
    expect(pageChecks(request, id, messages).at(-1).kit).toEqual(last.kit);
  });

  it("reports the stage loading while it fetches the data, and then the stage best-kit, and no other", async () => {
    const h = harness({ solver: highs });
    await h.start();
    const request = caseRequest(SLIDER);
    const { id, messages } = await h.ask(request);
    const reports = progressOf(pageChecks(request, id, messages));
    expect(reports.length).toBeGreaterThan(1);
    expect(reports.every((report) => report.stage !== undefined)).toBe(true);
    expect([...new Set(reports.map((report) => report.stage))]).toEqual(["loading", "best-kit"]);
    expect(reports.filter((report) => report.stage === "best-kit")).toEqual([{ v: 1, type: "progress", id, phase: "building", stage: "best-kit" }]);
    expect(reports.at(-1).stage).toBe("best-kit"); // the data is in before the work is begun
    expect(messages.map((message) => message.type).filter((type) => type !== "progress")).toEqual(["result"]);
  });

  it("works from the data the site lists and fetches it once for all the requests: the manifest of the trio, the item table and the bundle", async () => {
    const h = harness({ solver: highs });
    await h.start();
    await h.ask(caseRequest(SLIDER));
    expect(h.asked).toHaveLength(3);
    await h.ask(caseRequest(PLAIN));
    await h.ask(caseRequest(SLIDER, { own: true }));
    expect(h.asked, "nothing of the data was asked for again").toHaveLength(3);
    expect(h.scenarios.stats()).toMatchObject({ itemTables: 1, bundles: 1, trioManifests: 1, bestKits: 3 });
  });

  it("keeps no session of its own and leaves the session of the other modes alone: Equip now's stays kept and serves the next Equip now", async () => {
    const h = harness({ solver: highs });
    await h.start();
    const equip = { v: 1, kind: "scenario", trio: SLUG, level: 50, mode: "equip-now", scenario: { ...VIEW }, owned: [["w90003@4", 1], ["w80113@4", 1]], budgetMs: 120_000 };
    const first = (await h.ask(equip)).last;
    expect(first.type).toBe("result");
    expect(h.scenarios.stats()).toMatchObject({ sessions: 1, sessionsClosed: 0 });
    const best = (await h.ask(caseRequest(SLIDER))).last;
    expect(best).toMatchObject({ type: "result", mode: "best-kit" });
    expect(h.scenarios.stats()).toMatchObject({ sessions: 1, sessionsClosed: 0, bestKits: 1 });
    expect((await h.ask(equip)).last).toMatchObject({ F: first.F, kit: first.kit });
    expect(h.scenarios.stats()).toMatchObject({ sessions: 1, sessionsClosed: 0 });
  });

  it("models of its solves are all disposed when the answer is out", async () => {
    const made = [];
    const spy = spyOn(highs, { created: (solver) => made.push(solver) });
    const h = harness({ solver: spy.highs });
    await h.start();
    await h.ask(caseRequest(SLIDER));
    expect(made.length).toBeGreaterThan(0);
    expect(made.every((solver) => solver.disposed)).toBe(true);
  });

  it("gives the same answer to the same request, and another to another weights, in whatever order they come", async () => {
    const h = harness({ solver: highs });
    await h.start();
    const heavy = caseRequest(SLIDER);
    const light = bestKitRequest(SLIDER.scenario, SLIDER.tier, { multipliers: { AC: 0.5 } });
    const a = (await h.ask(heavy)).last;
    const b = (await h.ask(light)).last;
    const c = (await h.ask(heavy)).last;
    const strip = ({ id, elapsedMs, ...rest }) => rest;
    expect(strip(c)).toEqual(strip(a));
    expect(strip(b)).not.toEqual(strip(a));
  });

  it("treats the sliders at x1 as the role's own: the answer of no weights", async () => {
    const h = harness({ solver: highs });
    await h.start();
    const strip = ({ id, elapsedMs, ...rest }) => rest;
    const none = (await h.ask(caseRequest(SLIDER, { own: true }))).last;
    const ones = (await h.ask(bestKitRequest(SLIDER.scenario, SLIDER.tier, { multipliers: { AC: 1, MANA: 1, "ATK+HASTE": 1, SV: 1, regen: 1 }, custom: {}, regenT: null }))).last;
    expect(strip(ones)).toEqual(strip(none));
  });

  describe("tells a request the data does not fit as a bad request, and goes on", () => {
    const view = SLIDER.scenario;
    const REFUSED = {
      "a race the bundle does not have": () => bestKitRequest({ ...view, race: "ZZZ" }, 4),
      "a role the trio is not offered": () => bestKitRequest({ ...view, role: "caster" }, 4),
      "a buff set the bundle does not have": () => bestKitRequest({ ...view, buffs: "everything" }, 4),
      "an evidence level the bundle does not have": () => bestKitRequest({ ...view, evidence: "hidden" }, 4),
      "a setup the role does not play": () => bestKitRequest({ ...view, role: "melee", setup: "1h-shield" }, 4),
      "a slider group there is not": () => bestKitRequest(view, 4, { multipliers: { NOPE: 2 } }),
      "a slider group there is not, at x1": () => bestKitRequest(view, 4, { multipliers: { NOPE: 1 } }),
      "a slider position that is not one of the three": () => bestKitRequest(view, 4, { multipliers: { AC: 3 } }),
      "a custom weight that cannot be set": () => bestKitRequest(view, 4, { custom: { ZZZ: 1 } }),
      "a custom weight above the largest": () => bestKitRequest(view, 4, { custom: { HP: 1001 } }),
      "a regen window above the longest": () => bestKitRequest(view, 4, { regenT: 61 }),
      "a regen window below 0": () => bestKitRequest(view, 4, { regenT: -0.5 }),
    };
    for (const [name, build] of Object.entries(REFUSED)) {
      it(name, async () => {
        const h = harness({ solver: highs });
        await h.start();
        const { id, last, messages } = await h.ask(build());
        expect(last).toMatchObject({ type: "error", code: "bad-request", id });
        expect(typeof last.message).toBe("string");
        expect(last.message.length).toBeGreaterThan(0);
        expect(validateFromWorker(last, { id, kind: "scenario", mode: "best-kit" }).code).toBe("bad-request");
        expect(messages.filter((message) => message.type === "result")).toHaveLength(0);
        const next = await h.ask(caseRequest(PLAIN));
        expect(next.last).toMatchObject({ type: "result", status: "optimal", F: PLAIN.F });
        expect(h.asked, "the data was not dropped for it").toHaveLength(3);
      });
    }
  });

  describe("holds the numbers of the weights to the floor and the digits of the protocol", () => {
    // A weight is read as the decimal it prints as, so the digits of the weights set the size of the exact value of the answer, and the page drops a worker that answers with a
    // text of more than LIMITS.maxExactLength characters. The protocol refuses the numbers that could do that, in the worker as in the page (they are one function), as a bad request.
    it("refuses a custom weight of 5e-324 and a regen window of 1e-100 as a bad request, before any data is fetched, and the worker goes on", async () => {
      for (const weights of [{ custom: { HP: 5e-324 } }, { regenT: 1e-100 }, { multipliers: { AC: 1e-300 } }, { custom: { HP: 1.234567 } }]) {
        const h = harness({ solver: highs });
        await h.start();
        const { id, last, messages } = await h.ask(bestKitRequest(SLIDER_VIEW, 4, weights));
        expect(last, JSON.stringify(weights)).toMatchObject({ type: "error", code: "bad-request", id });
        expect(last.message).toMatch(/6 significant digits/);
        expect(messages.filter((message) => message.type === "result")).toHaveLength(0);
        expect(h.asked, "nothing was fetched for it").toHaveLength(0);
        expect((await h.ask(caseRequest(PLAIN_CASE))).last).toMatchObject({ type: "result", status: "optimal", F: PLAIN_CASE.F });
      }
    });

    it("answers the finest weights it lets through with an exact value of far fewer characters than the page reads, and the page accepts the answer", async () => {
      const h = harness({ solver: highs });
      await h.start();
      for (const weights of [
        FINEST_WEIGHTS,
        { custom: { HP: 1e-6 } },
        { regenT: 1e-6 },
        { custom: { HP: 5.55556e-6, AC: 1.11111e-6 }, regenT: 9.87654e-6 },
        { custom: { HP: 999.999, AC: 888.888, MANA: 777.777, ATK: 666.667, SV: 555.555, SV_FIRE: 99.9999 }, regenT: 59.9999 },
      ]) {
        const request = bestKitRequest(SLIDER_VIEW, 4, weights);
        const { id, last, messages } = await h.ask(request);
        expect(last, JSON.stringify(weights)).toMatchObject({ type: "result", status: "optimal", proven: true });
        expect(last.F.length, JSON.stringify(weights)).toBeLessThan(100);
        expect(last.F.length).toBeLessThanOrEqual(LIMITS.maxExactLength);
        expect(pageChecks(request, id, messages).at(-1).F).toBe(last.F);
      }
    });
  });

  it("tells a bundle whose weight rules the engine cannot use as a fault of the data when weights are asked for, and drops it: the plain best kit does not need them", async () => {
    const raw = JSON.parse(BUNDLE_BYTES.toString("utf8"));
    raw.weight_groups.custom_max = "not a number";
    const site = makeSite({ bundles: { [SLUG]: { 50: new TextEncoder().encode(JSON.stringify(raw)) } } });
    const h = harness({ site, solver: highs });
    await h.start();
    expect((await h.ask(caseRequest(PLAIN))).last).toMatchObject({ type: "result", status: "optimal", F: PLAIN.F });
    const faulty = await h.ask(caseRequest(SLIDER));
    expect(faulty.last).toMatchObject({ type: "error", code: "engine-load" });
    expect(h.scenarios.stats()).toMatchObject({ bundles: 1 });
    expect((await h.ask(caseRequest(PLAIN))).last).toMatchObject({ type: "result", F: PLAIN.F });
    expect(h.scenarios.stats(), "the data that was found wrong was dropped and fetched again").toMatchObject({ bundles: 2 });
  });

  it("is a mode the worker answers only when its engine has it: otherwise it is not implemented, before any data is fetched", async () => {
    const h = harness({ solver: highs, engineOver: { bestKit: undefined } });
    await h.start();
    const { last } = await h.ask(caseRequest(PLAIN));
    expect(last).toMatchObject({ type: "error", code: "not-implemented" });
    expect(h.asked).toHaveLength(0);
  });

  describe("counts its time as the other modes do", () => {
    it("from the moment the data is in: a download that takes a minute of the clock does not eat the budget of the solve", async () => {
      let clock = 0;
      const h = harness({
        solver: highs,
        now: () => clock,
        fetch: {
          serve: () => {
            clock += 20_000;
            return undefined;
          },
        },
      });
      await h.start();
      const request = caseRequest(PLAIN, { budgetMs: 5000 });
      const { id, last, messages } = await h.ask(request);
      expect(h.asked).toHaveLength(3);
      expect(last).toMatchObject({ type: "result", status: "optimal", proven: true, label: null, F: PLAIN.F, elapsedMs: 60_000 }); // three files of twenty seconds, counted in the elapsed time
      expect(pageChecks(request, id, messages).at(-1).kit).toEqual(PLAIN.kit);
    });

    it("and is spent when the clock has run past the budget since the data came in: no kit, and it says so honestly", async () => {
      let clock = 0;
      const h = harness({ solver: highs, now: () => (clock += 1000) });
      await h.start();
      const request = caseRequest(PLAIN, { budgetMs: 1 });
      const { id, last } = await h.ask(request);
      expect(last).toMatchObject({ type: "result", status: "time_limit", proven: false, F: null, value: null, kit: null, buffs: [], label: LABEL_NO_INCUMBENT });
      expect(validateFromWorker(last, { id, kind: "scenario", mode: "best-kit" }).label).toBe(LABEL_NO_INCUMBENT);
      expect(LABEL_TIME_LIMIT).not.toBe(LABEL_NO_INCUMBENT);
    });

    it("and gives the solver the whole budget, never more", async () => {
      const limits = [];
      const spy = spyOn(highs, {
        before: (run) => {
          limits.push(run.limitMs);
        },
      });
      const h = harness({ solver: spy.highs });
      await h.start();
      await h.ask(caseRequest(PLAIN, { budgetMs: 30_000 }));
      expect(limits.length).toBeGreaterThan(0);
      expect(Math.max(...limits)).toBeLessThanOrEqual(30_000);
      expect(Math.max(...limits)).toBeGreaterThan(29_000); // the whole budget, less only the little that building the pool and the model took
    });
  });
});
