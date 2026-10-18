// How the worker gets the data for a visitor's own gear (scenario.js, createScenarioEngine): on the first scenario request for a trio it fetches the manifest
// of the trio (from an address it builds from the name of a trio that the main manifest lists), then the item table and the trio's bundle by the paths the
// manifests list and by nothing else, checks the type and the size against the manifest as the body is read and the SHA-256 before a byte is parsed, then
// parses and checks (the item table's reader, readBundle), and keeps them: the item table once, the manifest and the bundle of the last trio. Here the fetch
// is a fake, and the files are those of the synthetic site fixture; the answers are tested in engine-scenario.test.mjs.

import loadHighs from "highs";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { LABEL_NO_INCUMBENT } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { EngineFault } from "../pipeline/trioforge/site/static/engine/worker.js";
import { createScenarioEngine } from "../pipeline/trioforge/site/static/engine/scenario.js";
import { BASE, BUNDLE_BYTES, EQUIP_NOW, ITEMS_BYTES, ORIGIN, SLUG, bundleFor, makeSite, piecesOf, sha256, siteFetch } from "./engine-site-fixture.mjs";

vi.setConfig({ testTimeout: 60_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});
afterEach(() => {
  vi.restoreAllMocks();
});

const CASE = EQUIP_NOW.cases[0];
/** The request of a case of the fixture, as the page sends it. */
const requestOf = (c = CASE, over = {}) => ({ v: 1, kind: "scenario", trio: SLUG, level: 50, mode: "equip-now", scenario: { ...c.scenario }, owned: c.owned.map((pair) => [...pair]), budgetMs: 60_000, ...over });
const engineFor = (site, options = {}) => {
  const fetching = siteFetch(site, options.fetch);
  const progress = [];
  const engine = createScenarioEngine({ highs, fetchImpl: fetching.fetchImpl, baseUrl: BASE, stallMs: options.stallMs ?? 20_000, bodyMs: options.bodyMs ?? 60_000 });
  const run = (request = requestOf(), more = {}) => engine.equipNow(request, { manifest: site.manifest, startedAt: performance.now(), onProgress: (p) => progress.push(p), ...more });
  return { engine, run, progress, ...fetching };
};
const failure = async (promise) => promise.then(() => null, (error) => error);

describe("fetching the data", () => {
  it("asks for the manifest of the trio, then the item table and then the bundle, by the manifests' paths and by nothing else, as files of this site", async () => {
    const site = makeSite();
    const { run, asked } = engineFor(site);
    const answer = await run();
    expect(answer.status).toBe("optimal");
    expect(asked).toEqual([`${ORIGIN}/engine-trios/${SLUG}.json`, `${ORIGIN}${site.itemsPath}`, `${ORIGIN}${site.bundlePath}`]);
  });

  it("asks with the credentials of this site only, and takes no address from a request", async () => {
    const site = makeSite();
    const inits = [];
    const { run, asked } = engineFor(site, { fetch: { serve: (_url, init) => void inits.push(init) } });
    // a request that carries fields that a checked request never does: they are not read
    const forged = { ...requestOf(), url: "https://evil.example/items.json", itemsPath: "/elsewhere.json", path: "/x.json", manifest: { items: { path: "/y.json" } } };
    await run(forged);
    expect(asked.every((url) => url.startsWith(`${ORIGIN}/assets/engine/data/`) || url === `${ORIGIN}/engine-trios/${SLUG}.json`)).toBe(true);
    expect(asked).toHaveLength(3);
    expect(inits.every((init) => init.credentials === "same-origin" && init.signal instanceof AbortSignal)).toBe(true);
    expect(inits[0].cache).toBe("no-cache"); // the manifest of the trio keeps its name from one release to the next: the browser is asked whether its copy is current
  });

  it("keeps the item table and the bundle: a second request for the same trio fetches nothing", async () => {
    const { run, asked, engine } = engineFor(makeSite());
    await run();
    await run(requestOf(EQUIP_NOW.cases[1]));
    expect(asked).toHaveLength(3);
    expect(engine.stats()).toMatchObject({ itemTables: 1, bundles: 1, trioManifests: 1 });
  });

  it("keeps the item table once and the manifest and the bundle of the last trio only", async () => {
    const other = bundleFor("pal-shd-ber");
    const site = makeSite({ bundles: { [SLUG]: { 50: BUNDLE_BYTES }, "pal-shd-ber": { 50: other } } });
    const { run, asked, engine } = engineFor(site);
    const case0 = EQUIP_NOW.cases[0];
    await run(requestOf(case0));
    await run(requestOf(case0, { trio: "pal-shd-ber" }));
    expect(asked.map((url) => new URL(url).pathname)).toEqual([
      site.trioPaths[SLUG],
      site.itemsPath,
      site.bundlePath,
      site.trioPaths["pal-shd-ber"],
      site.trioJson["pal-shd-ber"].bundles[50].path,
    ]); // the item table was not asked for again
    await run(requestOf(case0)); // back to the first: its manifest and its bundle were dropped for the second's, so they are fetched again
    expect(asked).toHaveLength(7);
    expect(new URL(asked[5]).pathname).toBe(site.trioPaths[SLUG]);
    expect(new URL(asked[6]).pathname).toBe(site.bundlePath);
    expect(engine.stats()).toMatchObject({ itemTables: 1, bundles: 3, trioManifests: 3 });
    await run(requestOf(case0));
    expect(asked).toHaveLength(7);
  });

  it("reports how far the download is as one figure for the two files, rising to the whole", async () => {
    const { run, progress } = engineFor(makeSite(), { fetch: { chunk: 1024 } });
    await run();
    const loading = progress.filter((p) => p.phase === "loading");
    expect(loading.length).toBeGreaterThan(3);
    const total = ITEMS_BYTES.length + BUNDLE_BYTES.length;
    expect(loading.every((p) => p.total === total && p.loaded >= 0 && p.loaded <= total)).toBe(true);
    expect(loading.map((p) => p.loaded)).toEqual([...loading.map((p) => p.loaded)].sort((a, b) => a - b));
    expect(loading.at(-1)).toEqual({ phase: "loading", stage: "loading", loaded: total, total });
    expect(progress.map((p) => p.phase)).toEqual(expect.arrayContaining(["loading", "building"]));
  });

  it("reports only the bundle when the item table is already there", async () => {
    const other = bundleFor("pal-shd-ber");
    const { run, progress } = engineFor(makeSite({ bundles: { [SLUG]: { 50: BUNDLE_BYTES }, "pal-shd-ber": { 50: other } } }));
    await run();
    progress.length = 0;
    await run(requestOf(CASE, { trio: "pal-shd-ber" }));
    const loading = progress.filter((p) => p.phase === "loading");
    expect(loading.at(-1)).toEqual({ phase: "loading", stage: "loading", loaded: other.length, total: other.length });
  });
});

describe("refusing what is not the file the manifest lists", () => {
  it("a file whose SHA-256 is not the manifest's is refused before a byte of it is parsed", async () => {
    const tampered = new Uint8Array(ITEMS_BYTES);
    tampered[tampered.length >> 1] ^= 1; // one bit: the right type and the right size
    const site = makeSite();
    const lying = engineFor(site, { fetch: { serve: (url) => (new URL(url).pathname === site.itemsPath ? new Response(tampered, { headers: { "content-type": "application/json" } }) : undefined) } });
    const parse = vi.spyOn(JSON, "parse");
    const decode = vi.spyOn(TextDecoder.prototype, "decode");
    const error = await failure(lying.run());
    expect(error).toBeInstanceOf(EngineFault);
    expect(error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/checksum/i) });
    expect(parse.mock.calls.filter(([text]) => typeof text === "string" && text.length > 1000)).toEqual([]);
    expect(decode.mock.calls.filter(([bytes]) => bytes.length > 1000)).toEqual([]); // not even read as text (the manifest of the trio, a few hundred bytes, was)
    expect(lying.asked).toHaveLength(2); // the manifest of the trio and the item table; the bundle was not asked for
    // the same bytes get as far as the parser for a manifest that lists their digest, so it was the digest that decided
    const honest = makeSite({ items: Buffer.from(tampered) });
    const ok = engineFor(honest);
    await ok.run().then(
      () => {},
      () => {},
    );
    expect(decode).toHaveBeenCalled();
  });

  it("a bundle whose SHA-256 is not the manifest's is refused as well, before it is parsed", async () => {
    const tampered = new Uint8Array(BUNDLE_BYTES);
    tampered[100] ^= 1;
    const site = makeSite();
    const lying = engineFor(site, { fetch: { serve: (url) => (new URL(url).pathname === site.bundlePath ? new Response(tampered, { headers: { "content-type": "application/json" } }) : undefined) } });
    const error = await failure(lying.run());
    expect(error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/checksum/i) });
  });

  it("a file with the right SHA-256 that is not JSON is a file that cannot be read, and says so in its own words", async () => {
    const junk = new TextEncoder().encode("this is not json");
    const { run } = engineFor(makeSite({ items: junk }));
    const error = await failure(run());
    expect(error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/could not be read/i) });
    expect(error.message).not.toMatch(/checksum/i);
  });

  it("a file with the right SHA-256 that is not valid UTF-8 is a file that cannot be read", async () => {
    const { run } = engineFor(makeSite({ items: Uint8Array.of(0x7b, 0xff, 0xfe, 0x7d) }));
    expect(await failure(run())).toMatchObject({ code: "engine-load", message: expect.stringMatching(/could not be read/i) });
  });

  it("a body larger than the manifest says is refused while it is read: the rest of it is never asked for", async () => {
    const seen = { pulled: 0, cancelled: false };
    const site = makeSite();
    const body = new Uint8Array(ITEMS_BYTES.length + 5_000_000);
    const { run } = engineFor(site, { fetch: { serve: (url) => (new URL(url).pathname === site.itemsPath ? new Response(piecesOf(body, 4096, seen), { headers: { "content-type": "application/json" } }) : undefined) } });
    const error = await failure(run());
    expect(error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/larger than it should be/i) });
    expect(seen.pulled).toBeLessThanOrEqual(Math.ceil(ITEMS_BYTES.length / 4096) + 2); // it stopped within a piece or two of the size listed
    expect(seen.cancelled).toBe(true);
    expect(seen.pulled * 4096).toBeLessThan(body.length / 10);
  });

  it("a body that ends short of the manifest's size is refused", async () => {
    const site = makeSite();
    const { run } = engineFor(site, { fetch: { serve: (url) => (new URL(url).pathname === site.bundlePath ? new Response(BUNDLE_BYTES.subarray(0, 1000), { headers: { "content-type": "application/json" } }) : undefined) } });
    expect(await failure(run())).toMatchObject({ code: "engine-load", message: expect.stringMatching(/incomplete \(1000 of \d+ bytes\)/i) });
  });

  it("a body of the right size is accepted down to the last byte", async () => {
    const { run } = engineFor(makeSite(), { fetch: { chunk: 1 << 20 } });
    expect((await run()).status).toBe("optimal");
  });

  it("a file served with a type that is not JSON is refused, and a charset after the type does no harm", async () => {
    const { run } = engineFor(makeSite(), { fetch: { type: "text/html" } });
    expect(await failure(run())).toMatchObject({ code: "engine-load", message: expect.stringMatching(/wrong type/i) });
    const none = engineFor(makeSite(), { fetch: { type: "" } });
    expect(await failure(none.run())).toMatchObject({ code: "engine-load" });
    const wasm = engineFor(makeSite(), { fetch: { type: "application/wasm" } });
    expect(await failure(wasm.run())).toMatchObject({ code: "engine-load" });
    const charset = engineFor(makeSite(), { fetch: { type: "application/json; charset=utf-8" } });
    expect((await charset.run()).status).toBe("optimal");
  });

  it("an answer that is an error is refused with its status, and a request that fails is refused without the address", async () => {
    const down = engineFor(makeSite(), { fetch: { serve: () => new Response("busy", { status: 503 }) } });
    expect(await failure(down.run())).toMatchObject({ code: "engine-load", message: expect.stringMatching(/503/) });
    const gone = engineFor(makeSite(), { fetch: { serve: () => Promise.reject(new TypeError("Failed to fetch https://evil.example/secret")) } });
    const error = await failure(gone.run());
    expect(error).toMatchObject({ code: "engine-load" });
    expect(error.message).not.toContain("evil.example");
  });

  it("a response with no body to read in pieces is read whole, and checked all the same", async () => {
    const whole = (bytes) => ({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      body: null,
      text: async () => new TextDecoder().decode(bytes), // (the manifest of the trio is read as text)
      arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    });
    const site = makeSite();
    const fine = engineFor(site, { fetch: { serve: (url) => whole(new Uint8Array(site.files.get(new URL(url).pathname))) } });
    expect((await fine.run()).status).toBe("optimal");
    const tampered = new Uint8Array(ITEMS_BYTES);
    tampered[7] ^= 1;
    const bad = engineFor(site, { fetch: { serve: (url) => whole(new Uint8Array(new URL(url).pathname === site.itemsPath ? tampered : site.files.get(new URL(url).pathname))) } });
    expect(await failure(bad.run())).toMatchObject({ code: "engine-load", message: expect.stringMatching(/checksum/i) });
  });

  it("a download that stalls is given up, and the request is aborted", async () => {
    const site = makeSite();
    let signal;
    const { run } = engineFor(site, {
      stallMs: 40,
      fetch: {
        serve: (url, init) => {
          if (new URL(url).pathname !== site.itemsPath) return undefined;
          signal = init.signal;
          return new Response(new ReadableStream({ pull: () => new Promise(() => {}) }), { headers: { "content-type": "application/json" } });
        },
      },
    });
    const error = await failure(run());
    expect(error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/stalled/i) });
    expect(signal.aborted).toBe(true);
  });

  it("does not keep what it refused: the next request fetches the files again and works", async () => {
    const site = makeSite();
    let broken = true;
    const junk = new Uint8Array(ITEMS_BYTES.length); // the right size, and not the file
    const { run, asked, engine } = engineFor(site, { fetch: { serve: (url) => (broken && new URL(url).pathname === site.itemsPath ? new Response(junk, { headers: { "content-type": "application/json" } }) : undefined) } });
    expect(await failure(run())).toMatchObject({ code: "engine-load" });
    expect(engine.stats()).toMatchObject({ itemTables: 0, bundles: 0 });
    broken = false;
    expect((await run()).status).toBe("optimal");
    expect(asked).toHaveLength(4); // the manifest of the trio and the refused item table, then the item table again and the bundle (the manifest was fine, and is kept)
    expect(engine.stats()).toMatchObject({ itemTables: 1, bundles: 1, trioManifests: 1 });
  });
});

describe("refusing a table or a bundle that is not what the precompute writes, though the manifest lists it", () => {
  const withTable = (change) => {
    const table = JSON.parse(ITEMS_BYTES.toString("utf8"));
    change(table);
    return new TextEncoder().encode(JSON.stringify(table));
  };
  const withBundle = (change) => {
    const bundle = JSON.parse(BUNDLE_BYTES.toString("utf8"));
    change(bundle);
    return new TextEncoder().encode(JSON.stringify(bundle));
  };
  const TABLES = {
    "an item table of another version": withTable((t) => (t.version = 2)),
    "an item table with a record that has a field it should not": withTable((t) => (t.items[0].price = 5)),
    "an item table whose count is wrong": withTable((t) => (t.count += 1)),
  };
  for (const [name, items] of Object.entries(TABLES)) {
    it(name, async () => {
      const { run } = engineFor(makeSite({ items }));
      expect(await failure(run())).toMatchObject({ code: "engine-load", message: expect.stringMatching(/item table/i) });
    });
  }
  const BUNDLES = {
    "a bundle of another version": withBundle((b) => (b.version = 2)),
    "a bundle with a field it should not have": withBundle((b) => (b.partial = false)),
    "a bundle without its profile": withBundle((b) => delete b.profile_common),
    "a bundle of another trio than the one asked for": withBundle((b) => {
      b.trio = ["PAL", "SHD", "BER"];
      b.profile_common.trio = ["PAL", "SHD", "BER"];
    }),
    "a bundle of another level than the one asked for": withBundle((b) => {
      b.level = 55;
      b.profile_common.level = 55;
    }),
    "a bundle with an exact number that is not reduced": withBundle((b) => (b.constants.stat_knee = "510/2")),
  };
  for (const [name, bundle] of Object.entries(BUNDLES)) {
    it(name, async () => {
      const { run } = engineFor(makeSite({ bundles: { [SLUG]: { 50: bundle } } }));
      expect(await failure(run())).toMatchObject({ code: "engine-load" });
    });
  }

  it("a bundle and an item table of two releases", async () => {
    const { run } = engineFor(makeSite({ bundles: { [SLUG]: { 50: withBundle((b) => (b.data_release = "data-2026-10-20")) } } }));
    expect(await failure(run())).toMatchObject({ code: "engine-load", message: expect.stringMatching(/release/i) });
    const rules = engineFor(makeSite({ bundles: { [SLUG]: { 50: withBundle((b) => (b.rules_version = "2026-10-20")) } } }));
    expect(await failure(rules.run())).toMatchObject({ code: "engine-load", message: expect.stringMatching(/release|rules/i) });
  });

  it("a bundle and an item table made from other inputs: another catalog, or other flags merged into the levels (their fingerprints differ)", async () => {
    const A = "a".repeat(64);
    const B = "b".repeat(64);
    const pair = (table, bundle) => makeSite({ items: withTable((t) => (table === undefined ? delete t.inputs : (t.inputs = table))), bundles: { [SLUG]: { 50: withBundle((b) => (bundle === undefined ? delete b.inputs : (b.inputs = bundle))) } } });
    for (const [table, bundle] of [[A, B], [A, undefined], [undefined, B]]) {
      const { run, asked } = engineFor(pair(table, bundle));
      const error = await failure(run());
      expect(error, `${table} ${bundle}`).toMatchObject({ code: "engine-load", message: expect.stringMatching(/same inputs/i) });
      expect(asked).toHaveLength(3); // both files were fetched and read: it is the pair that is refused
    }
    // the same fingerprint in both, or none in either, is a pair
    for (const [table, bundle] of [[A, A], [undefined, undefined]]) {
      const { run } = engineFor(pair(table, bundle));
      expect((await run()).status, `${table} ${bundle}`).toBe("optimal");
    }
  });

  it("does not keep a bundle that was refused for its inputs: the next request fetches it again", async () => {
    const site = makeSite({ items: withTable((t) => (t.inputs = "a".repeat(64))), bundles: { [SLUG]: { 50: withBundle((b) => (b.inputs = "b".repeat(64))) } } });
    const { run, engine } = engineFor(site);
    expect(await failure(run())).toMatchObject({ code: "engine-load" });
    expect(engine.stats().bundles).toBe(0);
  });

  it("messages that say nothing of the files' content", async () => {
    const { run } = engineFor(makeSite({ items: withTable((t) => (t.items[0].name = "https://evil.example/x\u0000")) }));
    const error = await failure(run());
    expect(error.message).not.toContain("evil.example");
    expect(error.message.length).toBeLessThanOrEqual(300);
  });
});

describe("the manifest of the trio", () => {
  const JSON_TYPE = { "content-type": "application/json" };
  /** Answer the request for the manifest of the trio with `body` (a text, bytes or a stream); every other request goes on to the site. */
  const trioServed = (site, body) => ({ serve: (url) => (new URL(url).pathname === site.trioPath ? new Response(body, { headers: JSON_TYPE }) : undefined) });
  /** The manifest of the trio of the fixture, changed, as text. */
  const trioWith = (site, change) => {
    const document = structuredClone(site.trioJson[SLUG]);
    change(document);
    return JSON.stringify(document);
  };

  it("is asked for first, at an address built from the name of the trio in the main manifest: /engine-trios/<trio>.json, asked again for no one", async () => {
    const site = makeSite();
    const { run, asked } = engineFor(site);
    await run();
    expect(asked[0]).toBe(`${ORIGIN}/engine-trios/${SLUG}.json`);
    expect(site.trioPath).toBe(`/engine-trios/${SLUG}.json`);
    expect(asked.filter((url) => url.includes("/engine-trios/"))).toHaveLength(1);
  });

  it("is not asked for, nor anything else, when the request names a trio that the main manifest does not list: the address is not made from the request's text", async () => {
    const site = makeSite();
    const { run, asked, engine } = engineFor(site);
    // (a request is checked before it comes this far; these are the names that a check let through by mistake would make into an address)
    for (const trio of ["war-war-war", "pal-mnk-ber/../pal-mnk-ber", "pal-mnk-ber?x=1", "pal-mnk-ber#x", "constructor", "__proto__", "PAL-MNK-BER", "pal-mnk-ber.json", "../etc", "pal-mnk-ber\n", "//evil.example/x"]) {
      expect(await failure(run(requestOf(CASE, { trio })))).toMatchObject({ code: "bad-request" });
    }
    expect(asked).toEqual([]);
    expect(engine.stats()).toMatchObject({ itemTables: 0, bundles: 0, trioManifests: 0 });
    // and a level that the manifest does not list for the trio
    expect(await failure(run(requestOf(CASE, { level: 55 })))).toMatchObject({ code: "bad-request" });
    expect(asked).toEqual([]);
  });

  it("is refused when its release is not the main manifest's, with a message that says so; nothing else is asked for after it", async () => {
    for (const change of [(d) => (d.data_release = "data-2026-10-20"), (d) => (d.rules_version = "2026-10-20")]) {
      const site = makeSite();
      const { run, asked } = engineFor(site, { fetch: trioServed(site, trioWith(site, change)) });
      const error = await failure(run());
      expect(error).toBeInstanceOf(EngineFault);
      expect(error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/another release/i) });
      expect(asked).toHaveLength(1);
    }
  });

  it("is refused when it is too large, while it is read: the rest of it is never asked for", async () => {
    const site = makeSite();
    const seen = { pulled: 0, cancelled: false };
    const { run, asked } = engineFor(site, { fetch: trioServed(site, piecesOf(new Uint8Array(5_000_000).fill(0x20), 1024, seen)) });
    const error = await failure(run());
    expect(error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/too large/i) });
    expect(seen.cancelled).toBe(true);
    expect(seen.pulled).toBeLessThanOrEqual(10); // 8 KB is the limit: a few pieces of 1 KB, not 5 MB
    expect(asked).toHaveLength(1);
  });

  it("is refused when it is not what the site writes, in a message that says nothing of what it holds", async () => {
    const site = makeSite();
    const BAD = {
      "text that is not JSON": "this is not json",
      "a list": "[]",
      "an object of another version": trioWith(site, (d) => (d.version = 2)),
      "a field that is not allowed": trioWith(site, (d) => (d.url = "https://evil.example/x")),
      "a manifest of another trio": trioWith(site, (d) => (d.trio = "pal-shd-ber")),
      "a bundle of another trio": trioWith(site, (d) => (d.bundles[50].path = d.bundles[50].path.replace("pal-mnk-ber", "pal-shd-ber"))),
      "a bundle on another site": trioWith(site, (d) => (d.bundles[50].path = "https://evil.example/x.json")),
      "a bundle for a level the main manifest does not list": trioWith(site, (d) => (d.bundles[55] = d.bundles[50])),
      "a level named with a zero in front": trioWith(site, (d) => ((d.bundles = { "050": d.bundles[50] }), d)),
      "no bundle": trioWith(site, (d) => (d.bundles = {})),
      "a bundle with no digest": trioWith(site, (d) => delete d.bundles[50].sha256),
      "a bundle too large for the build": trioWith(site, (d) => (d.bundles[50].bytes = 10_000_000)),
    };
    for (const [name, body] of Object.entries(BAD)) {
      const { run, asked } = engineFor(site, { fetch: trioServed(site, body) });
      const error = await failure(run());
      expect(error, name).toMatchObject({ code: "engine-load", message: expect.stringMatching(/not what the site writes/i) });
      expect(error.message, name).not.toContain("evil.example");
      expect(asked, name).toHaveLength(1);
    }
  });

  it("is given up when it does not arrive, and the request is aborted; a refusal by the host is told with its status; a request that fails is told without the address", async () => {
    const site = makeSite();
    let signal;
    const stalled = engineFor(site, {
      stallMs: 40,
      fetch: {
        serve: (url, init) => {
          if (new URL(url).pathname !== site.trioPath) return undefined;
          signal = init.signal;
          return new Response(new ReadableStream({ pull: () => new Promise(() => {}) }), { headers: JSON_TYPE });
        },
      },
    });
    expect(await failure(stalled.run())).toMatchObject({ code: "engine-load", message: expect.stringMatching(/in time/i) });
    expect(signal.aborted).toBe(true);
    const down = engineFor(site, { fetch: { serve: (url) => (new URL(url).pathname === site.trioPath ? new Response("gone", { status: 404 }) : undefined) } });
    expect(await failure(down.run())).toMatchObject({ code: "engine-load", message: expect.stringMatching(/\(404\)/) });
    const broken = engineFor(site, { fetch: { serve: () => Promise.reject(new TypeError("Failed to fetch https://evil.example/secret")) } });
    const error = await failure(broken.run());
    expect(error).toMatchObject({ code: "engine-load" });
    expect(error.message).not.toContain("evil.example");
  });

  it("is not kept when it is refused: the next request fetches it again and works", async () => {
    const site = makeSite();
    let broken = true;
    const { run, asked, engine } = engineFor(site, { fetch: { serve: (url) => (broken && new URL(url).pathname === site.trioPath ? new Response("[]", { headers: JSON_TYPE }) : undefined) } });
    expect(await failure(run())).toMatchObject({ code: "engine-load" });
    expect(engine.stats()).toMatchObject({ trioManifests: 0, itemTables: 0, bundles: 0 });
    broken = false;
    expect((await run()).status).toBe("optimal");
    expect(asked.map((url) => new URL(url).pathname)).toEqual([site.trioPath, site.trioPath, site.itemsPath, site.bundlePath]);
  });

  it("lists the bundle that is fetched: its path, its size and its digest are the manifest of the trio's, and a bundle that is another file is refused", async () => {
    const site = makeSite();
    expect(site.trioJson[SLUG].bundles[50].path).toBe(site.bundlePath);
    const lying = makeSite({ lie: { bundle: { sha256: "0".repeat(64) } } });
    expect(await failure(engineFor(lying).run())).toMatchObject({ code: "engine-load", message: expect.stringMatching(/checksum/i) });
    const short = makeSite({ lie: { bundle: { bytes: BUNDLE_BYTES.length + 10 } } });
    expect(await failure(engineFor(short).run())).toMatchObject({ code: "engine-load", message: expect.stringMatching(/incomplete/i) });
  });
});

describe("the integrity of what is fetched", () => {
  it("the digests of the fixture are those the site lists", () => {
    const site = makeSite();
    expect(site.manifestJson.items.sha256).toBe(sha256(ITEMS_BYTES));
    expect(site.trioJson[SLUG].bundles[50].sha256).toBe(sha256(BUNDLE_BYTES));
    expect(site.itemsPath).toBe(`/assets/engine/data/items-${sha256(ITEMS_BYTES).slice(0, 16).toUpperCase()}.json`);
    expect(LABEL_NO_INCUMBENT).toBe("not found in time");
  });
});
