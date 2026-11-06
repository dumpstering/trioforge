// The solver worker in a real browser (Chromium), served by `wrangler pages dev` with the production headers: the policy of
// site/_headers is the one that applies to the page, to the worker and to the WebAssembly.
//
// The page code that will use the engine (the Upgrade tab, the sliders) comes later, so these tests load the engine client the way that
// code will: from the address in engine-manifest.json, by a dynamic import. The worker and the WebAssembly are then fetched from the
// addresses of the same manifest, through the Trusted Types policy of the client. Everything here runs once, in the "once" project.

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { check, handMilp, handOptimum, knapsackMilp, lpMilp, openRowMilp } from "../tests-js/engine-models.mjs";
import { ROOT, TRIO, axe, expect, open, test } from "./support.mjs";

test.describe.configure({ timeout: 90_000 });

async function readManifest(request) {
  const response = await request.get("/engine-manifest.json");
  expect(response.status(), "the build writes engine-manifest.json").toBe(200);
  expect(response.headers()["content-type"]).toMatch(/json/);
  // the one file of the optimizer whose name is the same in every release: it is asked for again on every visit, never kept for a year
  expect(response.headers()["cache-control"] ?? "", "the manifest is asked for again on every visit").not.toMatch(/immutable|max-age=[1-9]/);
  return response.json();
}

/**
 * The size the question gives, worked out here from the manifests' gzip sizes (what is downloaded), not from the page's code: the worker and the WebAssembly,
 * and for a scenario (`bundle` is the file of the trio's manifest) the item table and the bundle as well.
 */
function megabytes(manifest, bundle) {
  const data = bundle === undefined ? 0 : manifest.items.gzip + bundle.gzip;
  return (Math.ceil((manifest.worker.gzip + manifest.wasm.gzip + data) / 100_000) / 10).toFixed(1);
}

/** Watch the page for the workers it starts and the WebAssembly it fetches. */
function observe(page) {
  const seen = { workers: [], wasm: [], data: [], trios: [] };
  page.on("worker", (worker) => seen.workers.push(worker));
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.endsWith(".wasm")) seen.wasm.push(request.url());
    if (path.startsWith("/assets/engine/data/")) seen.data.push(request.url());
    if (path.startsWith("/engine-trios/")) seen.trios.push(request.url());
  });
  return seen;
}

/** Load the client from the manifest, the way the page code will, and keep one on the page. */
async function installEngine(page, manifest) {
  await page.evaluate(async (path) => {
    const { createEngineClient } = await import(new URL(path, location.href).href);
    window.__engine = { client: createEngineClient({ window, document }), progress: [] };
  }, manifest.client.path);
}

/** Start a request in the page. Resolves with what came back: the result or the error's code, and the progress seen on the way. */
function solveInPage(page, request) {
  return page.evaluate(async (body) => {
    const engine = window.__engine;
    const progress = [];
    const began = performance.now();
    try {
      const result = await engine.client.solve(body, {
        onProgress: (p) => {
          progress.push(p.phase);
          engine.progress.push(p.phase);
        },
      });
      return { ok: true, result, progress, ms: performance.now() - began };
    } catch (error) {
      return { ok: false, code: error.code, message: error.message, progress, ms: performance.now() - began };
    }
  }, request);
}

const question = (page, manifest, bundle) => page.getByRole("button", { name: `Load the optimizer (about ${megabytes(manifest, bundle)} MB)` });
const model = (extra = {}) => ({ v: 1, kind: "model", model: handMilp(), budgetMs: 20_000, ...extra });

/** Open the trio page, load the client, and answer the question with yes on the first request. Returns what a test needs. */
async function startEngine(page, request) {
  const seen = observe(page);
  await open(page, TRIO);
  const manifest = await readManifest(request);
  await installEngine(page, manifest);
  const first = solveInPage(page, model());
  await question(page, manifest).click();
  const outcome = await first;
  expect(outcome.ok, JSON.stringify(outcome)).toBe(true);
  return { seen, manifest, outcome };
}

test("the worker loads under the production policy and solves a hand-written model to its known optimum @once", async ({ page, request, watch }) => {
  const seen = observe(page);
  await open(page, TRIO);
  const manifest = await readManifest(request);

  // the engine files are served as the site is built for: the same headers as every page, and the WebAssembly as WebAssembly
  const policy = (await request.get(TRIO)).headers()["content-security-policy"];
  for (const path of [manifest.client.path, manifest.worker.path, manifest.wasm.path]) {
    const response = await request.get(path);
    expect(response.status(), path).toBe(200);
    expect(response.headers()["content-security-policy"], `${path} carries the policy`).toBe(policy);
    expect(response.headers()["x-content-type-options"], path).toBe("nosniff");
  }
  expect((await request.get(manifest.wasm.path)).headers()["content-type"]).toBe("application/wasm");
  expect((await request.get(manifest.worker.path)).headers()["content-type"]).toMatch(/javascript/);
  expect(policy).toContain("require-trusted-types-for 'script'");
  expect(policy).toContain("'wasm-unsafe-eval'");

  await installEngine(page, manifest);
  const solving = solveInPage(page, model());

  // the visitor is asked first; nothing has been downloaded
  const ask = question(page, manifest);
  await expect(ask).toBeVisible();
  expect(seen.workers).toHaveLength(0);
  expect(seen.wasm).toHaveLength(0);
  await ask.click();

  const outcome = await solving;
  expect(outcome.ok, JSON.stringify(outcome)).toBe(true);
  const { result } = outcome;
  const optimum = handOptimum();
  expect(result).toMatchObject({ kind: "model", status: "optimal", proven: true, label: null });
  expect(result.objective).toBeCloseTo(optimum.objective, 9);
  const verdict = check(model().model, result.x);
  expect(verdict.problems).toEqual([]);
  expect(verdict.objective).toBeCloseTo(optimum.objective, 9);
  expect(outcome.progress).toEqual(expect.arrayContaining(["loading", "compiling", "building"]));

  // one worker, from the manifest's address, and the WebAssembly fetched once, from the manifest's address
  expect(seen.workers).toHaveLength(1);
  expect(new URL(seen.workers[0].url()).pathname).toBe(manifest.worker.path);
  expect(seen.wasm.map((u) => new URL(u).pathname)).toEqual([manifest.wasm.path]);
  await expect(page.locator(".engine-consent")).toHaveCount(0); // the question goes away when the optimizer is ready

  // the policy and the Trusted Types of the page were never in the way
  expect(watch.violations()).toEqual([]);
  expect(watch.problems()).toEqual([]);
});

test("the page and the worker both ask the server whether their copy of the manifest is current @once", async ({ page, request, watch }) => {
  // the manifest keeps its name from one release to the next, so a copy in the HTTP cache could be the last release's, whatever the host sends
  const asked = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/engine-manifest.json") asked.push(r);
  });
  await startEngine(page, request);
  expect(asked, "one read by the page's client, one by the worker").toHaveLength(2);
  for (const r of asked) expect(await r.headerValue("cache-control"), "the request says no-cache").toBe("max-age=0");
  expect(watch.problems()).toEqual([]);
});

test("a model with no integer column is answered with its optimum as its bound and no nodes, and a null row bound is no bound @once", async ({ page, request, watch }) => {
  await startEngine(page, request);
  const lp = await solveInPage(page, { v: 1, kind: "model", model: lpMilp(), budgetMs: 20_000 });
  expect(lp.ok, JSON.stringify(lp)).toBe(true);
  expect(lp.result).toMatchObject({ status: "optimal", proven: true, nodes: 0, gap: 0, label: null });
  expect(lp.result.objective).toBeCloseTo(19, 9);
  expect(lp.result.bound).toBeCloseTo(19, 9);
  expect(lp.result.x[0]).toBeCloseTo(4, 9);
  expect(lp.result.x[1]).toBeCloseTo(1, 9);
  const open = await solveInPage(page, { v: 1, kind: "model", model: openRowMilp(), budgetMs: 20_000 });
  expect(open.ok, JSON.stringify(open)).toBe(true);
  expect(open.result.objective).toBeCloseTo(-10, 9); // a row lower bound read as 0 would give 0
  expect(await page.evaluate(() => window.__engine.client.stats())).toMatchObject({ spawns: 1 }); // and the worker was not dropped for either
  expect(watch.problems()).toEqual([]);
});

test("a second solve uses the engine that is already loaded @once", async ({ page, request, watch }) => {
  const { seen, manifest } = await startEngine(page, request);
  const second = await solveInPage(page, model({ model: { ...handMilp(), const: 11 } }));
  expect(second.ok, JSON.stringify(second)).toBe(true);
  expect(second.result.objective).toBeCloseTo(handOptimum().objective + 1, 9);
  expect(second.progress, "no loading, no compiling: the engine was there").toEqual(expect.not.arrayContaining(["loading", "compiling"]));
  await expect(page.locator(".engine-consent")).toHaveCount(0); // and nobody was asked again
  expect(seen.workers).toHaveLength(1);
  expect(seen.wasm).toHaveLength(1);
  expect(await page.evaluate(() => window.__engine.client.stats())).toMatchObject({ spawns: 1, solves: 2 });
  expect(manifest.wasm.path).toMatch(/\.wasm$/);
  expect(watch.problems()).toEqual([]);
});

test("a cancelled solve is followed by a new worker that starts from the kept module, with no second download @once", async ({ page, request, watch }) => {
  const { seen } = await startEngine(page, request);
  const long = solveInPage(page, { v: 1, kind: "model", model: knapsackMilp(), budgetMs: 60_000 });
  await expect.poll(() => page.evaluate(() => window.__engine.progress.filter((p) => p === "building").length)).toBe(2); // the first request's, then this one's
  await page.waitForTimeout(400); // the solver is inside its search
  await page.evaluate(() => window.__engine.client.cancel());
  const cancelled = await long;
  expect(cancelled).toMatchObject({ ok: false, code: "cancelled" });
  expect(cancelled.ms, "cancelling does not wait for the solve").toBeLessThan(10_000);

  const after = await solveInPage(page, model());
  expect(after.ok, JSON.stringify(after)).toBe(true);
  expect(after.result.objective).toBeCloseTo(handOptimum().objective, 9);
  expect(seen.workers).toHaveLength(2);
  expect(seen.wasm, "the WebAssembly is not fetched again").toHaveLength(1);
  expect(after.progress).toEqual(expect.not.arrayContaining(["loading"]));
  const stats = await page.evaluate(() => window.__engine.client.stats());
  expect(stats).toMatchObject({ spawns: 2, moduleKept: true });
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(watch.problems()).toEqual([]);
});

test("a slider that previews on input and settles on change is answered at every key press: the cancelled preview is never posted and the client goes on @once", async ({ page, request, watch }) => {
  test.setTimeout(120_000);
  await open(page, TRIO);
  const manifest = await readManifest(request);
  // The budgets tell the requests apart in what is posted to the worker: the first request 21,000 ms, the preview 30,000, the answer 22,000.
  await page.evaluate(
    async ({ path, hand, knapsack }) => {
      const { createEngineClient } = await import(new URL(path, location.href).href);
      const posted = [];
      const client = createEngineClient({
        window,
        document,
        createWorker: (url) => {
          const worker = new Worker(url, { type: "module", name: "trioforge-engine" });
          const post = worker.postMessage.bind(worker);
          worker.postMessage = (message, transfer) => {
            post(message, transfer);
            posted.push(message.type === "solve" ? `solve:${message.request.budgetMs}` : message.type);
          };
          return worker;
        },
      });
      const results = {};
      let count = 0;
      const ask = (label, model, budgetMs) => {
        count += 1;
        const name = `${label}${count}`;
        results[name] = "pending";
        client.solve({ v: 1, kind: "model", model, budgetMs }).then(
          (result) => (results[name] = result.status),
          (error) => (results[name] = error.code),
        );
      };
      const slider = Object.assign(document.createElement("input"), { type: "range", min: "0", max: "10", value: "5", id: "probe-slider" });
      slider.setAttribute("aria-label", "probe");
      slider.addEventListener("input", () => ask("preview", knapsack, 30_000));
      slider.addEventListener("change", () => {
        client.cancel();
        ask("final", hand, 22_000);
      });
      document.body.prepend(slider);
      window.__slider = { client, posted, results };
    },
    { path: manifest.client.path, hand: handMilp(), knapsack: knapsackMilp() },
  );
  const first = page.evaluate((hand) => window.__slider.client.solve({ v: 1, kind: "model", model: hand, budgetMs: 21_000 }).then((result) => result.status), handMilp());
  await question(page, manifest).click();
  expect(await first).toBe("optimal"); // the worker has worked now, so the next request asks it first whether it is there
  const state = () => page.evaluate(() => ({ results: { ...window.__slider.results }, posted: window.__slider.posted.filter((type) => type.startsWith("solve:")) }));
  await page.locator("#probe-slider").focus();
  for (const press of [1, 2, 3]) {
    await page.keyboard.press("ArrowRight"); // `input`, then `change`, in one task
    await expect.poll(async () => (await state()).results[`final${press * 2}`], { message: `press ${press}: the final request is answered`, timeout: 15_000 }).toBe("optimal");
    const seen = await state();
    expect(seen.results[`preview${press * 2 - 1}`], `press ${press}`).toBe("cancelled");
    expect(seen.posted, `press ${press}: the cancelled previews were never posted`).not.toContain("solve:30000");
    expect(Object.values(seen.results).filter((outcome) => outcome === "pending"), `press ${press}`).toEqual([]);
  }
  expect((await state()).posted).toEqual(["solve:21000", "solve:22000", "solve:22000", "solve:22000"]);
  expect(watch.problems()).toEqual([]);
});

test("a worker that dies without an error is noticed: the next request starts a new one from the kept module, long before the watchdog would speak @once", async ({ page, request, watch }) => {
  const { seen } = await startEngine(page, request);
  await seen.workers[0].evaluate(() => self.close()); // no message and no error event: the page is not told
  const next = await solveInPage(page, { v: 1, kind: "model", model: handMilp(), budgetMs: 1000 });
  expect(next.ok, JSON.stringify(next)).toBe(true);
  expect(next.result.objective).toBeCloseTo(handOptimum().objective, 9);
  expect(next.ms, "well under budget plus five seconds, which is when the watchdog would have given up on it").toBeLessThan(4000);
  expect(seen.workers).toHaveLength(2);
  expect(seen.wasm, "the WebAssembly is not downloaded again").toHaveLength(1);
  expect(next.progress).toEqual(expect.not.arrayContaining(["loading"]));
  expect(await page.evaluate(() => window.__engine.client.stats())).toMatchObject({ spawns: 2, moduleKept: true });
  // and the worker after it works as usual, with no new question to the visitor
  const third = await solveInPage(page, model());
  expect(third.ok, JSON.stringify(third)).toBe(true);
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(watch.problems()).toEqual([]);
});

test("the page stays responsive while a large model solves in the worker @once", async ({ page, request, watch }) => {
  await startEngine(page, request); // the download and the start are done; what follows is the solving
  await page.evaluate(() => {
    const field = document.createElement("input");
    field.id = "latency-probe";
    field.setAttribute("aria-label", "probe");
    document.body.append(field);
    const probe = (window.__probe = { delays: [], gaps: [], keys: 0 });
    field.addEventListener("keydown", (event) => {
      probe.keys += 1;
      probe.delays.push(performance.now() - event.timeStamp);
    });
    let last = performance.now();
    window.__probeTimer = setInterval(() => {
      const now = performance.now();
      probe.gaps.push(now - last - 10);
      last = now;
    }, 10);
    field.focus();
  });
  const budgetMs = 4000;
  const solving = solveInPage(page, { v: 1, kind: "model", model: knapsackMilp(), budgetMs });
  await expect.poll(() => page.evaluate(() => window.__engine.progress.filter((p) => p === "building").length)).toBe(2);
  for (let i = 0; i < 20; i += 1) {
    await page.keyboard.press("a");
    await page.waitForTimeout(60);
  }
  const outcome = await solving;
  expect(outcome.ok, JSON.stringify(outcome)).toBe(true);
  expect(["optimal", "time_limit"]).toContain(outcome.result.status);
  expect(outcome.ms, "the solve lasted, so the typing happened during it").toBeGreaterThan(1500);
  const probe = await page.evaluate(() => {
    clearInterval(window.__probeTimer);
    return { keys: window.__probe.keys, maxDelay: Math.max(...window.__probe.delays), maxGap: Math.max(...window.__probe.gaps) };
  });
  test.info().annotations.push({ type: "latency", description: `solve ${Math.round(outcome.ms)} ms (${outcome.result.status}); longest key wait ${probe.maxDelay.toFixed(1)} ms; longest timer gap ${probe.maxGap.toFixed(1)} ms` });
  expect(probe.keys).toBe(20);
  expect(probe.maxDelay, "the longest wait of a key press before the page handled it, in ms").toBeLessThan(100);
  expect(probe.maxGap, "the longest the page's own timer was held up, in ms").toBeLessThan(100);
  expect(watch.problems()).toEqual([]);
});

test("a WebAssembly that is not the file the manifest lists is refused before it is compiled, and the next request downloads the real one @once", async ({ page, request, watch }) => {
  const seen = observe(page);
  await open(page, TRIO);
  const manifest = await readManifest(request);
  expect(manifest.wasm.sha256, "the manifest lists the SHA-256 of the WebAssembly").toMatch(/^[0-9a-f]{64}$/);
  let tamper = true;
  await page.route("**/assets/engine/*.wasm", async (route) => {
    const response = await route.fetch();
    const body = Buffer.from(await response.body());
    if (tamper) body[body.length >> 1] ^= 1; // the same size and the same type, with one bit changed
    await route.fulfill({ response, body });
  });
  await installEngine(page, manifest);
  const first = solveInPage(page, model());
  await question(page, manifest).click();
  const refused = await first;
  expect(refused).toMatchObject({ ok: false, code: "engine-load" });
  expect(refused.message).toMatch(/checksum/i);
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(await page.evaluate(() => window.__engine.client.stats())).toMatchObject({ moduleKept: false }); // nothing of it is kept
  tamper = false;
  // the yes does not start the next download by itself: the next request asks again, and says that the optimizer did not load last time
  const next = solveInPage(page, model());
  await expect(question(page, manifest)).toBeVisible();
  await expect(page.locator(".engine-consent-warning")).toHaveText("The optimizer did not load last time.");
  expect(seen.wasm, "nothing was downloaded before the answer").toHaveLength(1);
  await question(page, manifest).click();
  const second = await next;
  expect(second.ok, JSON.stringify(second)).toBe(true);
  expect(second.result.objective).toBeCloseTo(handOptimum().objective, 9);
  expect(seen.wasm, "downloaded twice: the refused file, and the real one").toHaveLength(2);
  expect(await page.evaluate(() => window.__engine.client.stats())).toMatchObject({ spawns: 2, moduleKept: true });
  expect(watch.problems()).toEqual([]);
});

test("a scenario request of the old generic shape (a mode with candidates) is a bad request at once: no question, no worker, no download, no stored yes @once", async ({ page, request, watch }) => {
  const seen = observe(page);
  await open(page, TRIO);
  const manifest = await readManifest(request);
  await installEngine(page, manifest);
  const [trio] = Object.keys(manifest.trios);
  const scenario = { v: 1, kind: "scenario", trio, level: manifest.trios[trio][0], scenario: { race: "OGR", role: "balanced" }, owned: [], candidates: [], mode: "farm-path", budgetMs: 10_000 };
  const outcome = await solveInPage(page, scenario);
  expect(outcome).toMatchObject({ ok: false, code: "bad-request" });
  expect(outcome.ms, "it fails at once, it does not wait for anything").toBeLessThan(2000);
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(seen.workers).toHaveLength(0);
  expect(seen.wasm).toHaveLength(0);
  expect(await page.evaluate(() => window.__engine.client.consentState())).toBe("unknown");
  expect(await page.evaluate(() => sessionStorage.getItem("trioforge-engine-consent"))).toBeNull();
  expect(watch.problems()).toEqual([]);
});

/** The Equip now answers that Python's reference gave for the synthetic results (pipeline/tests/engine_fixture.py makes them; the answers are only for those results). */
const EQUIP_NOW = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/equip-now.json"), "utf8"));
const equipNowRequest = (c, over = {}) => ({ v: 1, kind: "scenario", trio: EQUIP_NOW.trio, level: EQUIP_NOW.level, mode: "equip-now", scenario: c.scenario, owned: c.owned, budgetMs: 60_000, ...over });

test("the real worker works out Equip now from the data the build published, and answers the kit that Python's reference gives @once", async ({ page, request, watch }) => {
  test.skip(Boolean(process.env.TRIOFORGE_RESULTS), "the answers are those of the synthetic results, which these are not"); // (as scripts/preview.mjs reads it: empty means the fixture)
  const seen = observe(page);
  await open(page, TRIO);
  const manifest = await readManifest(request);
  expect(manifest.version).toBe(2);
  expect(manifest.trios).toEqual({ [EQUIP_NOW.trio]: [EQUIP_NOW.level] }); // the main manifest lists the levels of a trio; its bundles are in the manifest of the trio
  expect(manifest.data_release).toMatch(/^data-\d{4}-\d{2}-\d{2}$/);

  // the manifest of the trio: at a fixed address beside the main one, outside /assets/ (asked again on every visit, as the main one is), in the release of the main one
  const trioPath = `/engine-trios/${EQUIP_NOW.trio}.json`;
  const trioResponse = await request.get(trioPath);
  expect(trioResponse.status(), trioPath).toBe(200);
  expect(trioResponse.headers()["content-type"]).toMatch(/json/);
  expect(trioResponse.headers()["cache-control"] ?? "", "the manifest of a trio is asked for again on every visit").not.toMatch(/immutable|max-age=[1-9]/);
  const trioManifest = await trioResponse.json();
  expect(trioManifest).toMatchObject({ version: 1, trio: EQUIP_NOW.trio, data_release: manifest.data_release, rules_version: manifest.rules_version });
  expect(Object.keys(trioManifest.bundles)).toEqual([String(EQUIP_NOW.level)]);
  const bundle = trioManifest.bundles[EQUIP_NOW.level];

  // the data files are served as the site is built for: hashed files of the folder that is kept for a year, as JSON, the size and the SHA-256 the manifest lists
  const policy = (await request.get(TRIO)).headers()["content-security-policy"];
  for (const file of [manifest.items, bundle]) {
    expect(file.path, "a hashed file under assets/engine/data").toMatch(/^\/assets\/engine\/data\/[a-z0-9-]+-[A-Z0-9]{16}\.json$/);
    const response = await request.get(file.path);
    expect(response.status(), file.path).toBe(200);
    expect(response.headers()["content-type"], file.path).toMatch(/^application\/json/);
    expect(response.headers()["content-security-policy"], `${file.path} carries the policy`).toBe(policy);
    expect(response.headers()["cache-control"], `${file.path} is kept`).toMatch(/immutable/);
    const body = await response.body();
    expect(body.length, file.path).toBe(file.bytes);
    expect(createHash("sha256").update(body).digest("hex"), file.path).toBe(file.sha256);
  }
  await installEngine(page, manifest);
  const [first, second, third] = EQUIP_NOW.cases;
  const asking = solveInPage(page, equipNowRequest(first));
  await question(page, manifest, bundle).click(); // (the question names the item table and the bundle as well as the worker and the WebAssembly)
  const outcome = await asking;
  expect(outcome.ok, JSON.stringify(outcome)).toBe(true);
  expect(outcome.result).toMatchObject({ kind: "scenario", mode: "equip-now", status: "optimal", proven: true, label: null });
  expect(outcome.result.kit, "the kit, place for place").toEqual(first.kit);
  expect(outcome.result.F).toBe(first.F);
  expect(outcome.result.value).toBe(first.value);
  expect(outcome.result.buffs).toEqual(first.buffs);
  expect(outcome.result.hasteAssumed).toBe(first.hasteAssumed);
  expect(outcome.progress).toEqual(expect.arrayContaining(["loading", "compiling", "building"]));

  // the worker fetched the item table and the bundle by the manifests' paths, once each, and nothing else of the data; the manifest of the trio was read
  // (by the page, for the question, and by the worker) and is the only one
  expect(seen.data.map((url) => new URL(url).pathname)).toEqual([manifest.items.path, bundle.path]);
  expect(seen.trios.length).toBeGreaterThanOrEqual(1);
  expect(new Set(seen.trios.map((url) => new URL(url).pathname))).toEqual(new Set([trioPath]));
  const trioReads = seen.trios.length;
  expect(seen.workers).toHaveLength(1);
  expect(seen.wasm.map((url) => new URL(url).pathname)).toEqual([manifest.wasm.path]);

  // the next requests are answered from what the worker kept: no question, no worker, no fetch; another scenario of the same trio makes another session
  for (const c of [second, third, first]) {
    const next = await solveInPage(page, equipNowRequest(c));
    expect(next.ok, JSON.stringify(next)).toBe(true);
    expect(next.result).toMatchObject({ kind: "scenario", mode: "equip-now", status: "optimal", proven: true, label: null, F: c.F, value: c.value, kit: c.kit, buffs: c.buffs, hasteAssumed: c.hasteAssumed });
  }
  expect(seen.data, "nothing of the data was asked for again").toHaveLength(2);
  expect(seen.trios, "nor the manifest of the trio").toHaveLength(trioReads);
  expect(seen.workers).toHaveLength(1);
  await expect(page.locator(".engine-consent")).toHaveCount(0);

  // a request that does not fit the data is told so, and the worker goes on
  const refused = await solveInPage(page, equipNowRequest(first, { owned: [["w999999@4", 1]] }));
  expect(refused).toMatchObject({ ok: false, code: "bad-request" });
  expect((await solveInPage(page, equipNowRequest(second))).ok).toBe(true);
  expect(seen.workers).toHaveLength(1);

  // the policy, the Trusted Types and the content type of the data never were in the way
  expect(watch.violations()).toEqual([]);
  expect(watch.problems()).toEqual([]);
});

const farmPathRequest = (c, over = {}) => ({ v: 1, kind: "scenario", trio: EQUIP_NOW.trio, level: EQUIP_NOW.level, mode: "farm-path", scenario: c.scenario, owned: c.owned, tierMode: { mode: "ready4" }, steps: 8, budgetMs: 60_000, ...over });

/**
 * Run a scenario request in the page with `runScenario`, keeping what each step message says as it is handed to `onStep`. `stopAt` is the index of the step from whose
 * callback the page calls `stop()`. After the result it waits a moment and reads the client's counts: a worker that sent anything after its result would have been dropped.
 */
function pathInPage(page, request, stopAt = null) {
  return page.evaluate(
    async ({ body, stopAt: at }) => {
      const engine = window.__engine;
      const steps = [];
      const began = performance.now();
      try {
        const result = await engine.client.runScenario(body, {
          onStep: (step) => {
            steps.push({ index: step.index, found: step.found ?? null, status: step.status });
            if (step.index === at) engine.client.stop();
          },
        });
        const atResult = steps.length;
        await new Promise((resolve) => setTimeout(resolve, 400));
        return { ok: true, result, steps, afterResult: steps.length - atResult, stats: engine.client.stats(), ms: performance.now() - began };
      } catch (error) {
        return { ok: false, code: error.code, message: error.message, steps, ms: performance.now() - began };
      }
    },
    { body: request, stopAt },
  );
}

test("a farm path through the real worker streams Equip now and then its steps in order, and a stop sent from a step ends it @once", async ({ page, request, watch }) => {
  test.skip(Boolean(process.env.TRIOFORGE_RESULTS), "the owned sets are those of the synthetic results, which these are not"); // (as the Equip now test above)
  const seen = observe(page);
  await open(page, TRIO);
  const manifest = await readManifest(request);
  const trioManifest = await (await request.get(`/engine-trios/${EQUIP_NOW.trio}.json`)).json();
  const bundle = trioManifest.bundles[EQUIP_NOW.level];
  await installEngine(page, manifest);
  const [first] = EQUIP_NOW.cases;
  const consecutive = (steps) => steps.map((step) => step.index);

  // the whole path, with no stop: Equip now is the step 0 and the steps follow in order, the result counts them, and it is the last thing the worker says. The very same
  // request is asked again below with a stop sent from the first step; what it finds here is what that stop has to cut short.
  const pathRequest = farmPathRequest(first, { steps: 8 });
  const asking = pathInPage(page, pathRequest);
  await question(page, manifest, bundle).click();
  const whole = await asking;
  expect(whole.ok, JSON.stringify(whole)).toBe(true);
  expect(whole.result).toMatchObject({ kind: "scenario", mode: "farm-path" });
  expect(whole.steps[0]).toMatchObject({ index: 0, status: "optimal" });
  expect(consecutive(whole.steps), "Equip now, then the steps one after the other").toEqual(whole.steps.map((_, at) => at));
  expect(whole.result.steps, "the result counts the steps after Equip now").toBe(whole.steps.length - 1);
  expect(whole.result.steps, "the fixture gives this request at least three steps, so that a stop after the first has something to cut short").toBeGreaterThanOrEqual(3);
  expect(["limit", "no-gain"]).toContain(whole.result.stopped);
  expect(whole.afterResult, "no step came after the result").toBe(0);
  expect(whole.stats).toMatchObject({ spawns: 1 });

  // the same request with a stop sent from the callback of the first step: the path ends before the next step the worker begins after it has seen the stop. In a browser
  // that may be one step later than in a test that delivers the messages as microtasks (the worker may have looked for the stop before it arrived and begun the second
  // step), so the path has one step, or two, and it is shorter than the path without a stop. A stop that is ignored gives the whole path and fails here.
  const stopped = await pathInPage(page, pathRequest, 1);
  expect(stopped.ok, JSON.stringify(stopped)).toBe(true);
  expect(stopped.result.stopped, "the stop was not ignored: the path says it was stopped").toBe("stopped");
  expect(stopped.result.steps, "the step the stop was sent from, at least").toBeGreaterThanOrEqual(1);
  expect(stopped.result.steps, "and at most the one the worker had begun before it had the stop").toBeLessThanOrEqual(2);
  expect(stopped.result.steps, "fewer steps than the path without a stop").toBeLessThan(whole.result.steps);
  expect(consecutive(stopped.steps), "no step is skipped or comes twice").toEqual(stopped.steps.map((_, at) => at));
  expect(stopped.result.steps).toBe(stopped.steps.length - 1);
  expect(stopped.afterResult, "no step came after the result").toBe(0);
  expect(stopped.stats, "the worker was not dropped, by the stop or by anything after the result").toMatchObject({ spawns: 1 });

  // the same worker answers the next request, and nothing was asked of the visitor or downloaded again
  const next = await solveInPage(page, equipNowRequest(first));
  expect(next.ok, JSON.stringify(next)).toBe(true);
  expect(next.result).toMatchObject({ mode: "equip-now", status: "optimal", F: first.F });
  expect(seen.workers).toHaveLength(1);
  expect(seen.data).toHaveLength(2);
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(watch.violations()).toEqual([]);
  expect(watch.problems()).toEqual([]);
});

/** The best kits that Python's reference gave for the views of the synthetic results, with the weights a request carries (pipeline/tests/engine_fixture.py makes them). */
const BEST_KIT = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/best-kit.json"), "utf8"));
const bestKitRequest = (c, over = {}) => ({
  v: 1,
  kind: "scenario",
  trio: BEST_KIT.trio,
  level: BEST_KIT.level,
  mode: "best-kit",
  scenario: c.scenario,
  tier: c.tier,
  ...(c.weights === undefined ? {} : { weights: c.weights }),
  budgetMs: 60_000,
  ...over,
});

/** Run a scenario request in the page with `runScenario`, keeping the stage of every report of progress; resolves with the result or the error's code. */
function scenarioInPage(page, request) {
  return page.evaluate(async (body) => {
    const engine = window.__engine;
    const stages = [];
    const began = performance.now();
    try {
      const result = await engine.client.runScenario(body, { onProgress: (report) => stages.push(report.stage ?? null) });
      return { ok: true, result, stages, ms: performance.now() - began };
    } catch (error) {
      return { ok: false, code: error.code, message: error.message, stages, ms: performance.now() - began };
    }
  }, request);
}

test("the real worker works out the best kit of a view, with the weights of a request, and answers the kit that Python's reference gives @once", async ({ page, request, watch }) => {
  test.skip(Boolean(process.env.TRIOFORGE_RESULTS), "the answers are those of the synthetic results, which these are not"); // (as the Equip now test above)
  const seen = observe(page);
  await open(page, TRIO);
  const manifest = await readManifest(request);
  const trioManifest = await (await request.get(`/engine-trios/${BEST_KIT.trio}.json`)).json();
  const bundle = trioManifest.bundles[BEST_KIT.level];
  await installEngine(page, manifest);
  const [slider] = BEST_KIT.cases;
  const answerOf = (c) => ({ F: c.F, value: c.value, kit: c.kit, buffs: c.buffs, hasteAssumed: c.hasteAssumed });

  // the first request asks the visitor, downloads what the other modes download (the item table and the bundle) and answers with the progress of loading and then of the best kit
  const asking = scenarioInPage(page, bestKitRequest(slider));
  await question(page, manifest, bundle).click();
  const first = await asking;
  expect(first.ok, JSON.stringify(first)).toBe(true);
  expect(first.result).toMatchObject({ kind: "scenario", mode: "best-kit", status: "optimal", proven: true, label: null, ...answerOf(slider) });
  expect([...new Set(first.stages.filter((stage) => stage !== null))], "loading while it fetches the data, and then the best kit").toEqual(["loading", "best-kit"]);
  expect(seen.data.map((url) => new URL(url).pathname)).toEqual([manifest.items.path, bundle.path]);

  // every view of the reference, with and without weights: the exact value, the kit place for place, the buffs and the haste are Python's; the worker and its data stay
  for (const c of BEST_KIT.cases) {
    const next = await scenarioInPage(page, bestKitRequest(c));
    expect(next.ok, `${c.name}: ${JSON.stringify(next)}`).toBe(true);
    expect(next.result, c.name).toMatchObject({ mode: "best-kit", status: "optimal", proven: true, label: null, ...answerOf(c) });
    expect(next.stages.every((stage) => stage === "best-kit" || stage === null), "the data was in already: no loading").toBe(true);
    if (c.own !== undefined) {
      const { weights, ...bare } = bestKitRequest(c); // (the same view with no weights: the role's own)
      const own = await scenarioInPage(page, bare);
      expect(own.ok, JSON.stringify(own)).toBe(true);
      expect(own.result, `${c.name}, the role's own`).toMatchObject(answerOf(c.own));
    }
  }
  expect(seen.data, "nothing of the data was asked for again").toHaveLength(2);
  expect(seen.workers).toHaveLength(1);

  // a request the data does not fit is a bad request, and the worker goes on; so is a request the protocol refuses, which never reaches the worker
  const [plain] = BEST_KIT.cases.filter((c) => c.weights === undefined);
  expect(await scenarioInPage(page, bestKitRequest(slider, { weights: { multipliers: { NOPE: 2 } } }))).toMatchObject({ ok: false, code: "bad-request" });
  expect(await scenarioInPage(page, bestKitRequest(slider, { weights: { custom: { HP: 1001 } } }))).toMatchObject({ ok: false, code: "bad-request" });
  expect(await scenarioInPage(page, bestKitRequest(slider, { weights: { manaReachable: true } }))).toMatchObject({ ok: false, code: "bad-request" });
  expect(await scenarioInPage(page, bestKitRequest(slider, { owned: [] }))).toMatchObject({ ok: false, code: "bad-request" });
  // a weight too small or too fine is a bad request too, and does not cost the visitor the worker (its exact value would have been 657 and 209 characters, where the page reads 200)
  expect(await scenarioInPage(page, bestKitRequest(slider, { weights: { custom: { HP: 5e-324 } } }))).toMatchObject({ ok: false, code: "bad-request" });
  expect(await scenarioInPage(page, bestKitRequest(slider, { weights: { regenT: 1e-100 } }))).toMatchObject({ ok: false, code: "bad-request" });
  const finest = await scenarioInPage(page, bestKitRequest(slider, { weights: { custom: { HP: 1.23457e-6, AC: 2.34567e-6 }, regenT: 1.23457e-6 } })); // (the finest the protocol lets through)
  expect(finest.ok, JSON.stringify(finest)).toBe(true);
  expect(finest.result.F.length).toBeLessThan(100);
  const after = await scenarioInPage(page, bestKitRequest(plain));
  expect(after.ok, JSON.stringify(after)).toBe(true);
  expect(after.result).toMatchObject(answerOf(plain));
  expect(seen.workers).toHaveLength(1);
  await expect(page.locator(".engine-consent")).toHaveCount(0);

  // the policy, the Trusted Types and the content type of the data never were in the way
  expect(watch.violations()).toEqual([]);
  expect(watch.problems()).toEqual([]);
});

/** Python's answers for the four Upgrade modes under weights drawn from fixed seeds, and for the best kit at the weapon tier rates (pipeline/tests/engine_fixture.py makes them). */
const WEIGHTED = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/weighted.json"), "utf8"));
const WEAPON_RATE = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/weapon-rate.json"), "utf8"));
const upgradeRequest = (c, mode, over = {}) => ({
  v: 1,
  kind: "scenario",
  trio: WEIGHTED.trio,
  level: WEIGHTED.level,
  mode,
  scenario: c.scenario,
  owned: c.owned,
  weights: c.weights,
  budgetMs: 60_000,
  ...over,
});

/** Run a farm path in the page and keep every step message as it is handed to `onStep` (index 0 is Equip now); resolves with the steps and the result, or the error's code. */
function stepsInPage(page, request) {
  return page.evaluate(async (body) => {
    const steps = [];
    try {
      const result = await window.__engine.client.runScenario(body, { onStep: (step) => steps.push(step) });
      return { ok: true, result, steps };
    } catch (error) {
      return { ok: false, code: error.code, message: error.message, steps };
    }
  }, request);
}

const pickOf = (object, keys) => Object.fromEntries(keys.map((key) => [key, object[key]]));

test("the real worker answers Equip now, the farm path, the best sets and Every slot under the weights of a request, and gives the steps, sets and swaps that Python's reference gives @once", async ({ page, request, watch }) => {
  test.skip(Boolean(process.env.TRIOFORGE_RESULTS), "the answers are those of the synthetic results, which these are not"); // (as the Equip now test above)
  const seen = observe(page);
  await open(page, TRIO);
  const manifest = await readManifest(request);
  const trioManifest = await (await request.get(`/engine-trios/${WEIGHTED.trio}.json`)).json();
  const bundle = trioManifest.bundles[WEIGHTED.level];
  await installEngine(page, manifest);
  const ANSWER = ["F", "value", "kit", "buffs", "hasteAssumed"];
  const STEP = ["ident", "kind", "sourceTier", "F", "value", "gain", "gainValue", "kit", "buffs", "hasteAssumed"];
  // one case in each tier mode: ready4, arrives and fixed
  const cases = [0, 1, 3].map((at) => WEIGHTED.cases[at]);
  expect(new Set(cases.map((c) => c.tierMode.mode))).toEqual(new Set(["ready4", "arrives", "fixed"]));

  for (const [at, c] of cases.entries()) {
    const asking = scenarioInPage(page, upgradeRequest(c, "equip-now"));
    if (at === 0) await Promise.race([question(page, manifest, bundle).click(), asking]); // (the first request asks the visitor, unless the page refuses it first; the others find the worker and its data)
    const first = await asking;
    expect(first.ok, `${c.name}: ${JSON.stringify(first)}`).toBe(true);
    expect(first.result, c.name).toMatchObject({ mode: "equip-now", status: "optimal", proven: true, label: null, ...pickOf(c.equipNow, ANSWER) });

    const path = await stepsInPage(page, upgradeRequest(c, "farm-path", { tierMode: c.tierMode, steps: c.farmPath.steps }));
    expect(path.ok, `${c.name}: ${JSON.stringify(path)}`).toBe(true);
    expect(pickOf(path.steps[0], ["F", "value", "kit", "buffs"]), `${c.name}: Equip now`).toEqual(c.farmPath.start);
    expect(path.steps.slice(1).map((step) => pickOf(step, STEP)), `${c.name}: the steps`).toEqual(c.farmPath.path);
    expect(path.result).toMatchObject({ mode: "farm-path", stopped: c.farmPath.stopped, steps: c.farmPath.path.length, hasteAssumed: c.equipNow.hasteAssumed });

    for (const want of c.bestSets) {
      const set = await scenarioInPage(page, upgradeRequest(c, "best-sets", { tierMode: c.tierMode, k: want.k }));
      expect(set.ok, JSON.stringify(set)).toBe(true);
      expect(set.result.acquired.map(({ ident, kind, sourceTier }) => ({ ident, kind, sourceTier })), `${c.name}: the best ${want.k}`).toEqual(want.acquired);
      expect(pickOf(set.result, ["F", "value", "gain", "gainValue", "kit", "buffs", "hasteAssumed"]), `${c.name}: the best ${want.k}`).toEqual(
        pickOf(want, ["F", "value", "gain", "gainValue", "kit", "buffs", "hasteAssumed"]),
      );
    }

    const slots = await scenarioInPage(page, upgradeRequest(c, "every-slot", { tierMode: c.tierMode, kit: c.everySlot.kit, buffs: c.everySlot.buffs, limit: c.everySlot.limit }));
    expect(slots.ok, JSON.stringify(slots)).toBe(true);
    const rows = slots.result.rows.map((row) => ({ place: row.place, index: row.index, current: row.current, swaps: row.swaps.map(({ ident, delta, deltaValue }) => ({ ident, delta, deltaValue })) }));
    expect(rows, `${c.name}: Every slot`).toEqual(c.everySlot.rows);

    // the role's own weights are the answer of no weights: the worker goes on with the session of the request with none
    const { weights, ...bare } = upgradeRequest(c, "equip-now");
    const own = await scenarioInPage(page, bare);
    expect(own.ok, JSON.stringify(own)).toBe(true);
    expect(own.result.F, `${c.name}: the weights move the value`).not.toBe(c.equipNow.F);
  }
  expect(seen.data.map((url) => new URL(url).pathname), "the data was asked for once").toEqual([manifest.items.path, bundle.path]);
  expect(seen.workers).toHaveLength(1);

  // a request the bundle does not fit is a bad request in every mode, and the worker goes on; so is one the protocol refuses, which never reaches the worker
  const [c] = cases;
  const modes = [
    ["equip-now", {}],
    ["farm-path", { tierMode: c.tierMode, steps: 3 }],
    ["best-sets", { tierMode: c.tierMode, k: 2 }],
    ["every-slot", { tierMode: c.tierMode, kit: c.everySlot.kit, buffs: c.everySlot.buffs }],
  ];
  for (const [mode, extra] of modes) {
    for (const weights of [{ multipliers: { NOPE: 2 } }, { custom: { HP: 1001 } }, { regenT: 61 }, { manaReachable: true }, { custom: { HP: 5e-324 } }, { regenT: 1e-100 }]) {
      expect(await scenarioInPage(page, upgradeRequest(c, mode, { ...extra, weights })), `${mode} ${JSON.stringify(weights)}`).toMatchObject({ ok: false, code: "bad-request" });
    }
  }
  const after = await scenarioInPage(page, upgradeRequest(c, "equip-now"));
  expect(after.ok, JSON.stringify(after)).toBe(true);
  expect(after.result).toMatchObject(pickOf(c.equipNow, ANSWER));
  expect(seen.workers).toHaveLength(1);
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(watch.violations()).toEqual([]);
  expect(watch.problems()).toEqual([]);
});

test("the real worker works out the best kit at the weapon tier rate 5 and at 10, and answers the kit that Python's reference gives at each @once", async ({ page, request, watch }) => {
  test.skip(Boolean(process.env.TRIOFORGE_RESULTS), "the answers are those of the synthetic results, which these are not"); // (as the Equip now test above)
  const seen = observe(page);
  await open(page, TRIO);
  const manifest = await readManifest(request);
  const trioManifest = await (await request.get(`/engine-trios/${WEAPON_RATE.trio}.json`)).json();
  const bundle = trioManifest.bundles[WEAPON_RATE.level];
  await installEngine(page, manifest);
  const ANSWER = ["F", "value", "kit", "buffs", "hasteAssumed"];
  const rateRequest = (c, options) => ({
    v: 1,
    kind: "scenario",
    trio: WEAPON_RATE.trio,
    level: WEAPON_RATE.level,
    mode: "best-kit",
    scenario: c.scenario,
    tier: c.tier,
    ...(c.weights === undefined ? {} : { weights: c.weights }),
    ...(options === undefined ? {} : { options }),
    budgetMs: 60_000,
  });

  for (const [at, c] of WEAPON_RATE.cases.entries()) {
    for (const rate of [5, 10]) {
      const asking = scenarioInPage(page, rateRequest(c, { weaponTierRate: rate }));
      if (at === 0 && rate === 5) await Promise.race([question(page, manifest, bundle).click(), asking]); // (the first request asks the visitor, unless the page refuses it first; the others find the worker and its data)
      const got = await asking;
      expect(got.ok, `${c.name} at ${rate}: ${JSON.stringify(got)}`).toBe(true);
      expect(got.result, `${c.name} at ${rate}`).toMatchObject({ mode: "best-kit", status: "optimal", proven: true, label: null, ...pickOf(c.rates[String(rate)], ANSWER) });
    }
    // with no rate the rule's own (5) is the rate
    const plain = await scenarioInPage(page, rateRequest(c));
    expect(plain.ok, JSON.stringify(plain)).toBe(true);
    expect(plain.result, `${c.name}: no rate`).toMatchObject(pickOf(c.rules, ANSWER));
  }
  expect(seen.workers).toHaveLength(1);
  expect(seen.data, "the data was asked for once").toHaveLength(2);

  // a rate that is neither 5 nor 10, and an option that is not the rate, are bad requests that never reach the worker, and the worker goes on
  const [c] = WEAPON_RATE.cases;
  for (const options of [{ weaponTierRate: 7 }, { weaponTierRate: "10" }, { weaponTierRate: null }, { rate: 10 }, { weaponTierRate: 10, lock: [] }]) {
    expect(await scenarioInPage(page, rateRequest(c, options)), JSON.stringify(options)).toMatchObject({ ok: false, code: "bad-request" });
  }
  const after = await scenarioInPage(page, rateRequest(c, { weaponTierRate: 10 }));
  expect(after.ok, JSON.stringify(after)).toBe(true);
  expect(after.result).toMatchObject(pickOf(c.rates["10"], ANSWER));
  expect(seen.workers).toHaveLength(1);
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(watch.violations()).toEqual([]);
  expect(watch.problems()).toEqual([]);
});

test("declining the question keeps the page as it was: nothing is downloaded and the request says why @once", async ({ page, request, watch }) => {
  const seen = observe(page);
  await open(page, TRIO);
  const manifest = await readManifest(request);
  await installEngine(page, manifest);
  const asking = solveInPage(page, model());
  const dismiss = page.getByRole("button", { name: "Not now" });
  await expect(dismiss).toBeVisible();
  // the focus is on the question itself, never on the button that says yes (see the test of a key meant for something else)
  await expect(page.getByRole("group", { name: "Load the optimizer?" })).toBeFocused();
  await expect(question(page, manifest)).not.toBeFocused();
  await dismiss.click();
  const outcome = await asking;
  expect(outcome).toMatchObject({ ok: false, code: "declined" });
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(seen.workers).toHaveLength(0);
  expect(seen.wasm).toHaveLength(0);
  // the answer stands for the session: a second request is declined at once, without a question
  const again = await solveInPage(page, model());
  expect(again).toMatchObject({ ok: false, code: "declined" });
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(await page.evaluate(() => window.__engine.client.consentState())).toBe("declined");
  expect(watch.problems()).toEqual([]);
});

test("a key pressed for something else cannot accept the download: a second Enter, a held Enter or a Space while the question opens @once", async ({ page, request, watch }) => {
  const seen = observe(page);
  await open(page, TRIO);
  const manifest = await readManifest(request);
  await installEngine(page, manifest);
  // a field of the page whose Enter starts a request, as the gear picker's will
  await page.evaluate((body) => {
    const field = document.createElement("input");
    field.id = "gear-field";
    field.setAttribute("aria-label", "gear");
    document.querySelector("main").append(field);
    window.__asked = [];
    field.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      const outcome = { settled: false };
      window.__asked.push(outcome);
      window.__engine.client.solve(body).then(
        () => Object.assign(outcome, { settled: true, ok: true }),
        (error) => Object.assign(outcome, { settled: true, ok: false, code: error.code }),
      );
    });
    field.focus();
  }, model());
  await page.keyboard.press("Enter"); // starts the request
  await page.keyboard.down("Enter"); // and the key stays down: it repeats
  await page.keyboard.down("Enter");
  await expect(question(page, manifest)).toBeVisible();
  await page.keyboard.down("Enter"); // the question is open and the key still repeats
  await page.keyboard.down("Enter");
  await page.keyboard.up("Enter");
  await page.keyboard.press("Enter"); // and the visitor, meaning the field, presses Enter and Space again
  await page.keyboard.press("Space");
  await page.waitForTimeout(500); // long enough for a worker to start, if one were going to
  await expect(question(page, manifest)).toBeVisible(); // still asked
  expect(seen.workers, "no worker was started").toHaveLength(0);
  expect(seen.wasm, "nothing was downloaded").toHaveLength(0);
  expect(await page.evaluate(() => window.__engine.client.consentState())).toBe("unknown");
  expect(await page.evaluate(() => sessionStorage.getItem("trioforge-engine-consent"))).toBeNull();
  expect(await page.evaluate(() => window.__asked.every((outcome) => !outcome.settled))).toBe(true);
  // the visitor who means yes gets there with the keyboard: Tab to the button, Enter
  await page.keyboard.press("Tab");
  await expect(question(page, manifest)).toBeFocused();
  await page.keyboard.press("Enter");
  await expect.poll(() => page.evaluate(() => window.__asked.some((outcome) => outcome.ok === true))).toBe(true);
  expect(seen.workers).toHaveLength(1);
  expect(watch.problems()).toEqual([]);
});

test("the panel says what it is doing during a long first answer, and not that it is getting the optimizer ready @once", async ({ page, request, watch }) => {
  await open(page, TRIO);
  const manifest = await readManifest(request);
  await installEngine(page, manifest);
  const solving = solveInPage(page, { v: 1, kind: "model", model: knapsackMilp(), budgetMs: 3000 });
  await question(page, manifest).click();
  const status = page.locator(".engine-consent [role='status']");
  await expect(status).toHaveText("Looking for the best answer…");
  await expect(page.locator(".engine-consent progress")).not.toHaveAttribute("value", /.*/); // no figure: the bar only shows that it works
  await expect(page.getByRole("button", { name: "Cancel" })).toBeVisible(); // and a long solve can still be given up
  const outcome = await solving;
  expect(outcome.ok, JSON.stringify(outcome)).toBe(true);
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(watch.problems()).toEqual([]);
});

test("Cancel on the loading panel gives up the download: the request is cancelled, the worker is gone and the yes is taken back @once", async ({ page, request, watch }) => {
  const seen = observe(page);
  let release;
  const held = new Promise((resolve) => (release = resolve));
  await page.route("**/assets/engine/*.wasm", async (route) => {
    await held; // the download does not progress
    await route.continue().catch(() => {}); // (by then the worker that asked is gone)
  });
  await open(page, TRIO);
  const manifest = await readManifest(request);
  await installEngine(page, manifest);
  const solving = solveInPage(page, model());
  await question(page, manifest).click();
  await expect(page.locator(".engine-consent [role='status']")).toContainText("Loading the optimizer");
  await expect.poll(() => seen.workers.length).toBe(1);
  // a visitor at the keyboard: one Tab from the panel to the button, and Enter
  await page.keyboard.press("Tab");
  const cancel = page.getByRole("button", { name: "Cancel" });
  await expect(cancel).toBeFocused();
  await page.keyboard.press("Enter");
  expect(await solving).toMatchObject({ ok: false, code: "cancelled" });
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(await page.evaluate(() => window.__engine.client.consentState())).toBe("declined"); // the precomputed answers stay
  expect(await page.evaluate(() => sessionStorage.getItem("trioforge-engine-consent"))).toBeNull(); // and a reload asks again
  expect(await solveInPage(page, model())).toMatchObject({ ok: false, code: "declined" }); // no question, no download
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(seen.workers).toHaveLength(1);
  release();
  expect(watch.problems()).toEqual([]);
});

test("a download that stalls is given up after the stall time: the request fails with engine-load and the next request downloads again @once", async ({ page, request, watch }) => {
  test.setTimeout(120_000);
  const seen = observe(page);
  let stall = true;
  await page.route("**/assets/engine/*.wasm", async (route) => {
    if (stall) return; // never answered: not a byte comes
    await route.continue();
  });
  await open(page, TRIO);
  const manifest = await readManifest(request);
  await installEngine(page, manifest);
  const solving = solveInPage(page, model());
  await question(page, manifest).click();
  await expect(page.locator(".engine-consent [role='status']")).toContainText("Loading the optimizer");
  const outcome = await solving;
  expect(outcome).toMatchObject({ ok: false, code: "engine-load" });
  expect(outcome.message).toMatch(/stalled|too long/i);
  expect(outcome.ms, "given up after about 20 seconds without a byte").toBeGreaterThan(19_000);
  expect(outcome.ms).toBeLessThan(45_000);
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  // the yes does not start the next download by itself: the next request asks again, and says that the optimizer did not load last time
  expect(await page.evaluate(() => window.__engine.client.consentState())).toBe("unknown");
  expect(await page.evaluate(() => sessionStorage.getItem("trioforge-engine-consent"))).toBeNull();
  stall = false;
  const next = solveInPage(page, model());
  await expect(question(page, manifest)).toBeVisible();
  await expect(page.locator(".engine-consent-warning")).toHaveText("The optimizer did not load last time.");
  expect(seen.wasm, "nothing was asked for before the answer").toHaveLength(1);
  await question(page, manifest).click();
  const again = await next;
  expect(again.ok, JSON.stringify(again)).toBe(true);
  expect(again.result.objective).toBeCloseTo(handOptimum().objective, 9);
  expect(seen.wasm, "the real file came the second time").toHaveLength(2);
  expect(await page.evaluate(() => window.__engine.client.stats())).toMatchObject({ spawns: 2, moduleKept: true });
  expect(watch.violations()).toEqual([]);
});

test("Escape during the download does nothing, and Cancel is still the way out @once", async ({ page, request, watch }) => {
  const seen = observe(page);
  let release;
  const held = new Promise((resolve) => (release = resolve));
  await page.route("**/assets/engine/*.wasm", async (route) => {
    await held; // the download does not progress
    await route.continue().catch(() => {});
  });
  await open(page, TRIO);
  const manifest = await readManifest(request);
  await installEngine(page, manifest);
  const solving = solveInPage(page, model());
  await question(page, manifest).click();
  await expect(page.locator(".engine-consent [role='status']")).toContainText("Loading the optimizer");
  await expect(page.locator(".engine-consent")).toBeFocused(); // (the focus is on the panel, where a key meant for the question would land)
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  await expect(page.locator(".engine-consent [role='status']")).toContainText("Loading the optimizer");
  expect(await page.evaluate(() => window.__engine.client.consentState())).toBe("granted");
  expect(await page.evaluate(() => sessionStorage.getItem("trioforge-engine-consent"))).toBe("1");
  expect(seen.workers).toHaveLength(1);
  await page.getByRole("button", { name: "Cancel" }).click();
  expect(await solving).toMatchObject({ ok: false, code: "cancelled" });
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  release();
  expect(watch.problems()).toEqual([]);
});

test("a download that follows a yes remembered in the session is under the loading panel as well, with a Cancel that takes the yes back @once", async ({ page, request, watch }) => {
  const seen = observe(page);
  let release;
  const held = new Promise((resolve) => (release = resolve));
  await page.route("**/assets/engine/*.wasm", async (route) => {
    await held;
    await route.continue().catch(() => {});
  });
  await open(page, TRIO);
  const manifest = await readManifest(request);
  await page.evaluate(() => sessionStorage.setItem("trioforge-engine-consent", "1")); // the visitor said yes earlier, before a reload
  await installEngine(page, manifest);
  expect(await page.evaluate(() => window.__engine.client.consentState())).toBe("granted");
  const solving = solveInPage(page, model());
  await expect(page.locator(".engine-consent [role='status']")).toContainText("Loading the optimizer");
  await expect(page.locator(".engine-consent progress")).toBeVisible();
  await expect(page.getByRole("button", { name: /Load the optimizer/ })).toHaveCount(0); // nobody is asked
  await expect.poll(() => seen.workers.length, { message: "the worker of the download has started" }).toBe(1); // the page's worker event can come a moment after the panel shows
  await page.getByRole("button", { name: "Cancel" }).click();
  expect(await solving).toMatchObject({ ok: false, code: "cancelled" });
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(await page.evaluate(() => window.__engine.client.consentState())).toBe("declined");
  expect(await page.evaluate(() => sessionStorage.getItem("trioforge-engine-consent"))).toBeNull();
  release();
  expect(watch.problems()).toEqual([]);
});

test("the question asked on its own leaves no panel behind after a yes, and loads nothing @once", async ({ page, request, watch }) => {
  const seen = observe(page);
  await open(page, TRIO);
  const manifest = await readManifest(request);
  await installEngine(page, manifest);
  const asking = page.evaluate(() => window.__engine.client.askConsent());
  await question(page, manifest, { gzip: 0 }).click(); // (asked on its own, the figure counts the item table and no bundle: no trio is known)
  expect(await asking).toBe(true);
  await expect(page.locator(".engine-consent")).toHaveCount(0); // not "Loading the optimizer" for ever, with a Cancel that does nothing
  expect(seen.workers).toHaveLength(0);
  expect(seen.wasm).toHaveLength(0);
  const outcome = await solveInPage(page, model()); // the first request loads it, and nobody is asked again
  expect(outcome.ok, JSON.stringify(outcome)).toBe(true);
  expect(seen.wasm).toHaveLength(1);
  expect(watch.problems()).toEqual([]);
});

test("a release that lands during the start stops the trying: a notice with a Reload button, no more downloads, and the reload starts afresh @once", async ({ page, request, watch }, testInfo) => {
  test.setTimeout(120_000);
  const seen = observe(page);
  await open(page, TRIO);
  const manifest = await readManifest(request);
  // The release: the worker reads another manifest than the page did, one that lists another WebAssembly (the same file with a section more), and gets that file.
  const real = Buffer.from(await (await request.get(manifest.wasm.path)).body());
  const section = Buffer.concat([Buffer.from([7]), Buffer.from("release"), Buffer.from("the next release")]);
  const newer = Buffer.concat([real, Buffer.from([0, section.length]), section]); // a custom section at the end: still a module, and another file
  const next = { ...manifest, wasm: { ...manifest.wasm, bytes: newer.length, sha256: createHash("sha256").update(newer).digest("hex") } };
  await page.route("**/assets/engine/*.wasm", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, body: newer });
  });
  let reads = 0;
  let reloaded = false;
  await page.route("**/engine-manifest.json", async (route) => {
    reads += 1;
    const response = await route.fetch();
    await route.fulfill({ response, json: reloaded || reads > 1 ? next : manifest }); // the page's first read is of the old release, every other one of the new
  });
  await installEngine(page, manifest);
  const first = solveInPage(page, model());
  await question(page, manifest).click();
  const outcome = await first;
  expect(outcome).toMatchObject({ ok: false, code: "engine-load", message: "The optimizer was updated. Reload the page to use it." });
  const notice = page.locator(".engine-consent");
  await expect(notice).toContainText("The optimizer was updated. Reload the page to use it.");
  await expect(notice.getByRole("button", { name: "Reload" })).toBeVisible();
  await expect(notice.locator("progress")).toHaveCount(0);
  for (const colorScheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme });
    await axe(page, testInfo); // the notice passes the accessibility checks as the question does
  }
  // no more tries: the next requests fail at once, and nothing is started or downloaded
  for (let i = 0; i < 2; i += 1) {
    const refused = await solveInPage(page, model());
    expect(refused).toMatchObject({ ok: false, code: "engine-load", message: "The optimizer was updated. Reload the page to use it." });
    expect(refused.ms).toBeLessThan(1000);
  }
  expect(seen.workers).toHaveLength(1);
  expect(seen.wasm).toHaveLength(1);
  expect(await page.evaluate(() => window.__engine.client.stats())).toMatchObject({ spawns: 1, moduleKept: false, updated: true });
  await expect(notice).toHaveCount(1);
  // Reload: the page reads the new manifest and starts as the first visit did (the yes of the session stands, so only the loading panel shows)
  reloaded = true;
  await Promise.all([page.waitForEvent("load"), notice.getByRole("button", { name: "Reload" }).click()]);
  await installEngine(page, manifest);
  const afresh = await solveInPage(page, model());
  expect(afresh.ok, JSON.stringify(afresh)).toBe(true);
  expect(afresh.result.objective).toBeCloseTo(handOptimum().objective, 9);
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(watch.problems()).toEqual([]);
});

test("the question and the progress bar pass the accessibility checks, in light and in dark @once", async ({ page, request }, testInfo) => {
  // the download is held back, so that the progress bar stays on the page long enough to be checked
  let release;
  const held = new Promise((resolve) => (release = resolve));
  await page.route("**/assets/engine/*.wasm", async (route) => {
    await held;
    await route.continue();
  });
  await open(page, TRIO);
  const manifest = await readManifest(request);
  await installEngine(page, manifest);
  const solving = solveInPage(page, model());
  await expect(question(page, manifest)).toBeVisible();
  await expect(page.getByRole("group", { name: "Load the optimizer?" })).toBeVisible();
  for (const colorScheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme });
    await axe(page, testInfo);
  }
  // on the narrowest window (WCAG reflow: 320 px) the page still does not scroll sideways, with the question and then with the bar
  const fits = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  await page.setViewportSize({ width: 320, height: 640 });
  expect(await fits(), "the question fits a 320 px window").toBe(true);
  await page.setViewportSize({ width: 1280, height: 900 });
  await question(page, manifest).click();
  await expect(page.locator(".engine-consent [role='status']")).toContainText("Loading the optimizer");
  await expect(page.locator(".engine-consent progress")).toBeVisible();
  for (const colorScheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme });
    await axe(page, testInfo);
  }
  await page.setViewportSize({ width: 320, height: 640 });
  expect(await fits(), "the progress bar fits a 320 px window").toBe(true);
  release();
  const outcome = await solving;
  expect(outcome.ok, JSON.stringify(outcome)).toBe(true);
  await expect(page.locator(".engine-consent")).toHaveCount(0);
});

test("a refusal by the policy inside the worker reaches the page's console, where the watcher sees it @once", async ({ page, request, watch }) => {
  // The page does not see events of the worker's own global object, so the worker reports them to the console. That is what makes
  // "no violation" in the other tests mean something; this is the positive control: a refusal, and the watcher notices.
  const { seen } = await startEngine(page, request);
  expect(watch.problems()).toEqual([]);
  await seen.workers[0].evaluate(() => {
    self.dispatchEvent(new SecurityPolicyViolationEvent("securitypolicyviolation", { effectiveDirective: "script-src", disposition: "enforce" }));
  });
  await expect.poll(() => watch.problems()).toEqual([expect.stringMatching(/^console: error: The page's security policy refused something in the optimizer \(script-src\)/)]);
});

test("the page and the worker may create the one Trusted Types policy the code names, and no other: not a second, not a default @once", async ({ page, request, watch }) => {
  const { seen } = await startEngine(page, request); // the client has made its policy by now
  expect((await request.get(TRIO)).headers()["content-security-policy"]).toContain("require-trusted-types-for 'script'; trusted-types trioforge");
  const attempts = await page.evaluate(() => {
    const attempt = (name) => {
      try {
        trustedTypes.createPolicy(name, { createScriptURL: (s) => s, createHTML: (s) => s, createScript: (s) => s });
        return "created";
      } catch (error) {
        return `refused (${error.name})`;
      }
    };
    return { again: attempt("trioforge"), other: attempt("analytics"), fallback: attempt("default") };
  });
  // a pass-through "default" policy would turn every plain string into a trusted one, which is the whole of what the header keeps out
  expect(attempts).toEqual({ again: "refused (TypeError)", other: "refused (TypeError)", fallback: "refused (TypeError)" });
  const plain = await page.evaluate(() => {
    try {
      new Worker("/assets/engine/worker-AAAAAAAA.js", { type: "module" });
      return "allowed";
    } catch (error) {
      return `refused (${error.name})`;
    }
  });
  expect(plain, "a plain string is still refused after the attempts").toBe("refused (TypeError)");
  const inWorker = await seen.workers[0].evaluate(() => {
    try {
      self.trustedTypes.createPolicy("anything", { createScriptURL: (s) => s });
      return "created";
    } catch (error) {
      return `refused (${error.name})`;
    }
  });
  expect(inWorker).toBe("refused (TypeError)");
  // the refusals are the policy's, enforced, and they are what the watcher is shown (the worker reports its own to the console)
  await expect.poll(() => watch.violations().map((v) => v.directive)).toEqual(["trusted-types", "trusted-types", "trusted-types", "require-trusted-types-for"]);
  expect(watch.violations().every((v) => v.disposition === "enforce")).toBe(true);
  await expect.poll(() => watch.problems(["csp"]).filter((line) => /trusted-types/.test(line)).length).toBeGreaterThan(0);
  // and the engine still works under it
  const solved = await solveInPage(page, model());
  expect(solved.ok, JSON.stringify(solved)).toBe(true);
});

test("Trusted Types refuses a worker started from a plain address @once", async ({ page, request, watch }) => {
  await open(page, TRIO);
  const manifest = await readManifest(request);
  const outcome = await page.evaluate((path) => {
    try {
      new Worker(path, { type: "module" });
      return "allowed";
    } catch (error) {
      return `refused (${error.name})`;
    }
  }, manifest.worker.path);
  expect(outcome).toBe("refused (TypeError)");
  await expect.poll(() => watch.violations().map((v) => v.directive)).toEqual(["require-trusted-types-for"]);
  expect(watch.violations()[0].disposition).toBe("enforce");
});
