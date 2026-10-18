// What the tests of the best-kit mode share: the Python reference views (fixtures/site/best-kit.json), the request of the mode, a worker core on the real solver and the
// scenario engine over the files of a site, and what the page makes of the messages of a request. Nothing here is a test and nothing here is read by the site.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createScenarioEngine } from "../pipeline/trioforge/site/static/engine/scenario.js";
import { createPathWatch, validateFromWorker, validateRequest } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { createWorkerCore } from "../pipeline/trioforge/site/static/engine/worker.js";
import { BASE, SLUG, makeSite, siteFetch } from "./engine-site-fixture.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/** Python's answers for the best-kit views of the invented catalog: `{trio, level, cases}`, a case `{name, scenario, tier, weights?, F, value, kit, buffs, hasteAssumed, own?}`. */
export const REFERENCE = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/best-kit.json"), "utf8"));

/** A request for the best kit of a view at a tier, with the weights if there are any (a copy: a test may change it). */
export const bestKitRequest = (view, tier, weights, over = {}) => ({
  v: 1,
  kind: "scenario",
  trio: SLUG,
  level: 50,
  mode: "best-kit",
  scenario: { ...view },
  tier,
  ...(weights === undefined ? {} : { weights: structuredClone(weights) }),
  budgetMs: 120_000,
  ...over,
});

/**
 * The finest weights a request may carry: every number is at the floor of the protocol in size and has the six significant digits it may have, in all fourteen custom weights, the
 * five sliders and the regen window. The exact value of the answer to them is the longest the protocol lets a request make (it is some 40 characters, where the page reads up to 200).
 */
export const FINEST_WEIGHTS = {
  multipliers: { AC: 2, MANA: 0.5, "ATK+HASTE": 2, SV: 0.5, regen: 2 },
  custom: {
    HP: 1.23457e-6,
    AC: 2.34567e-6,
    MANA: 3.45671e-6,
    ATK: 4.56712e-6,
    DEX: 5.67123e-6,
    HASTE: 6.71234e-6,
    END: 7.12345e-6,
    SV: 8.23456e-6,
    CHA: 9.34567e-6,
    SV_FIRE: 1.11111e-6,
    SV_COLD: 2.22222e-6,
    SV_MAGIC: 3.33333e-6,
    SV_POISON: 4.44445e-6,
    SV_DISEASE: 5.55556e-6,
  },
  regenT: 1.23457e-6,
};

/** The request of a case of the reference, with its weights (`own: true` leaves them out: the role's own). */
export const caseRequest = (c, { own = false, ...over } = {}) => bestKitRequest(c.scenario, c.tier, own ? undefined : c.weights, over);

/**
 * A worker core on the real solver and the scenario engine, with the fake fetch of a site; `engineOver` replaces methods of the engine, `post` sees every message as it is
 * sent. The engine has the five modes the worker answers.
 */
export function harness({ site = makeSite(), fetch, now = () => performance.now(), solver, scenarioOptions = {}, engineOver = {} } = {}) {
  const fetching = siteFetch(site, fetch);
  const scenarios = createScenarioEngine({ highs: solver, fetchImpl: fetching.fetchImpl, baseUrl: BASE, now, ...scenarioOptions });
  const posted = [];
  const hooks = { onPost: null };
  const core = createWorkerCore({
    post: (message) => {
      posted.push(structuredClone(message));
      hooks.onPost?.(message);
    },
    loadManifest: async () => site.manifest,
    loadEngine: async () => ({
      version: "1.15.3",
      wasm: site.manifest.wasm.sha256,
      async solveModel() {
        throw new Error("a model request is not what is tested here");
      },
      equipNow: (request, options) => scenarios.equipNow(request, options),
      farmPath: (request, options) => scenarios.farmPath(request, options),
      bestSets: (request, options) => scenarios.bestSets(request, options),
      everySlot: (request, options) => scenarios.everySlot(request, options),
      bestKit: (request, options) => scenarios.bestKit(request, options),
      ...engineOver,
    }),
    now,
  });
  let id = 0;
  return {
    core,
    posted,
    hooks,
    /** The id of the request that was asked last (the one in flight, when called while it runs). */
    currentId: () => id,
    /** Send a stop for the request with the id. */
    stopOf: (to) => core.handle({ v: 1, type: "stop", id: to }),
    scenarios,
    site,
    ...fetching,
    async start() {
      await core.handle({ v: 1, type: "init" });
      posted.length = 0;
    },
    /** Send a request and return what came back for it: its id, the messages after it, and the last one. */
    async ask(request) {
      id += 1;
      const mine = id;
      posted.length = 0;
      await core.handle({ v: 1, type: "solve", id: mine, request });
      return { id: mine, messages: [...posted], last: posted[posted.length - 1] };
    },
  };
}

/**
 * What the page does with the messages of a request: the request is checked, and each message is held to what was asked, with the expectation that the client builds
 * from the request (client.js, `onMessage`), the tier of the request included, and a farm path is watched as a whole (the steps in order, each gaining exactly its value
 * less the value before it).
 */
export function pageChecks(request, id, messages) {
  const clean = validateRequest(request);
  const expectation = {
    id,
    kind: "scenario",
    mode: clean.mode,
    owned: clean.owned,
    steps: clean.steps,
    k: clean.k,
    limit: clean.limit,
    tierMode: clean.tierMode,
    kit: clean.kit,
    tier: clean.tier,
    path: clean.mode === "farm-path" ? createPathWatch(clean) : undefined,
  };
  return messages.map((message) => validateFromWorker(message, expectation));
}

export const progressOf = (messages) => messages.filter((message) => message.type === "progress");
