// The smoke check of the live site (scripts/smoke_live.mjs) in a real browser, against the preview that `wrangler pages dev` serves (scripts/preview.mjs, started by the
// config of Playwright: the port is TRIOFORGE_PREVIEW_PORT) and against stand-ins of it: small servers that pass every request on to the preview and change one thing in
// the answer, so that each check of the script has a site that fails it.
//
//   TRIOFORGE_PREVIEW_PORT=8799 npx playwright test tests-e2e/smoke-live.spec.mjs --project=once --workers=2
//
// The checks take the headers from site/_headers, the lists of trios and items from the preview itself, and need nothing from outside the machine.
//
// The 404 page of the site gives itself a policy (a <meta http-equiv="Content-Security-Policy"> element at the top of its head), which the smoke check requires. A build
// that does not give it yet fails that one check, and the first test says so; the other tests give the page the policy in the stand-in (`givesNotFoundPolicy`, which
// changes nothing in a build that has it), so that what each of them fails is only the check it is about.

import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import http from "node:http";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { chromium, expect, test } from "@playwright/test";
import { ANALYTICS_ORIGIN } from "../playwright.config.mjs";
import { NOTFOUND_PATH, NOTFOUND_POLICY, checksDir, itemPageKeys, main, sample, trioSlugs } from "../scripts/smoke_live.mjs";

test.describe.configure({ timeout: 240_000 });

const NOW = new Date("2026-10-18T10:00:03Z");
const SEED = 202642; // (the ISO week of NOW)
const FOLDERS = [];
// The folder of the checks is a temp folder of this file's own, in every worker: a command line that is refused is logged in it (the check cannot read --out of a command line that it
// refuses), and it must never be the real folder of the maintainer's computer.
test.beforeAll(() => {
  const folder = mkdtempSync(join(tmpdir(), "smoke-live-e2e-checks-"));
  FOLDERS.push(folder);
  process.env.TRIOFORGE_CHECKS_DIR = folder;
});
test.afterAll(() => {
  for (const folder of FOLDERS.splice(0)) rmSync(folder, { recursive: true, force: true });
});

// ---- the command, run in this process ---------------------------------------------------------------------------------------------------

/** Run the command against `base`, with the stamp going to a folder of its own; returns what it printed and where its stamp would be. */
async function smoke(base, ...argv) {
  const out = [];
  const err = [];
  const folder = mkdtempSync(join(tmpdir(), "smoke-live-e2e-"));
  FOLDERS.push(folder);
  // (a page gets 20 seconds to show its theme button, which a machine that is running a release build may need; a test that waits for a button that never shows gives less, later in argv.
  // A page is watched for 0.3 seconds after its network is idle and not the 5 of a real run, so that a test does not last all day: a test that is about the settle says --settle.
  // No data release is expected unless a test says one, since releases/ of the repository will hold pointers once a release has been made)
  const code = await main(["--base", base, "--out", folder, "--wait", "20", "--settle", "0.3", "--expect-data", "none", ...argv], { log: (line) => out.push(line), error: (line) => err.push(line), now: () => NOW });
  return { code, out, err, stamp: join(folder, "smoke-live.last-run") };
}

/** A folder of release pointers, such as releases/ of the repository, with one for each tag (only the names matter to the check). */
function pointers(...tags) {
  const folder = mkdtempSync(join(tmpdir(), "smoke-live-releases-"));
  FOLDERS.push(folder);
  for (const tag of tags) writeFileSync(join(folder, `${tag}.json`), "{}");
  return folder;
}

/** The header line and the problem lines of a failed check, with the address of the site in the header made constant. */
function failed(result) {
  if (result.err.length === 0) throw new Error(`the check passed (exit ${result.code}, ${JSON.stringify(result.out)}), and was expected to fail`);
  const [header, ...problems] = result.err;
  return { header: header.replace(/ on http:\/\/127\.0\.0\.1:\d+ /, " on SITE "), problems };
}

// ---- stand-ins: the preview with one thing changed ---------------------------------------------------------------------------------------

/**
 * A server on a port of its own that passes every request to `upstream` and answers with what `mutate` makes of the answer. An answer is `{ path, status, headers, body }` (the
 * path without its query, the headers in lower case, the body a Buffer); `mutate` returns a changed answer, or nothing to let it through. `files` are answered by the stand-in itself.
 * `requests` lists what was asked of it, with the time. `delays` makes the answer for a path late by that many milliseconds.
 */
async function standIn(upstream, mutate = () => undefined, files = {}, delays = {}) {
  const requests = [];
  const server = http.createServer(async (request, response) => {
    const { pathname } = new URL(request.url, "http://stand-in.invalid");
    requests.push({ path: request.url, pathname, at: performance.now(), accept: request.headers.accept ?? "" });
    try {
      if (delays[pathname] !== undefined) await new Promise((done) => setTimeout(done, delays[pathname])); // (an answer that comes late, to keep the network busy)
      if (files[pathname] !== undefined) {
        response.writeHead(200, { "content-type": "text/javascript", "content-length": String(Buffer.byteLength(files[pathname])) });
        response.end(files[pathname]);
        return;
      }
      const answered = await fetch(upstream + request.url, { redirect: "manual", headers: { accept: request.headers.accept ?? "*/*" } });
      const headers = {};
      answered.headers.forEach((value, name) => {
        headers[name] = value;
      });
      for (const name of ["content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive"]) delete headers[name];
      const answer = { path: pathname, status: answered.status, headers, body: Buffer.from(await answered.arrayBuffer()) };
      const sent = (await mutate(answer)) ?? answer;
      response.writeHead(sent.status, { ...sent.headers, "content-length": String(sent.body.length) });
      response.end(sent.body);
    } catch (error) {
      response.writeHead(502, { "content-type": "text/plain" });
      response.end(String(error));
    }
  });
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  return {
    origin: `http://127.0.0.1:${server.address().port}`,
    requests,
    close: () => new Promise((done) => server.close(done)),
  };
}

/** Run a test body with a stand-in, and close it afterwards. */
async function withStandIn(upstream, mutate, body, files, delays) {
  const site = await standIn(upstream, mutate, files, delays);
  try {
    return await body(site);
  } finally {
    await site.close();
  }
}

const isHtml = (answer) => (answer.headers["content-type"] ?? "").includes("text/html");
const textOf = (answer) => answer.body.toString("utf8");
const withText = (answer, text) => ({ ...answer, body: Buffer.from(text, "utf8") });
const compose = (...changes) => async (answer) => {
  let current = answer;
  for (const change of changes) current = (await change(current)) ?? current;
  return current;
};
/** Apply `change` to the answers for the paths that `match` (an exact path, or a regular expression). */
const onPath = (match, change) => (answer) => ((typeof match === "string" ? answer.path === match : match.test(answer.path)) ? change(answer) : undefined);
const dropHeader = (name) => (answer) => {
  const { [name]: _, ...headers } = answer.headers;
  return { ...answer, headers };
};
const setHeader = (name, value) => (answer) => ({ ...answer, headers: { ...answer.headers, [name]: value } });
const setStatus = (status) => (answer) => ({ ...answer, status });
const edit = (pattern, replacement) => (answer) => (isHtml(answer) ? withText(answer, textOf(answer).replace(pattern, replacement)) : undefined);

const POLICY_META = `<meta http-equiv="Content-Security-Policy" content="${NOTFOUND_POLICY}">`;
const POLICY_ELEMENTS = /<meta[^>]*http-equiv="Content-Security-Policy"[^>]*>/gi; // (only for replace(): a regular expression with g keeps a place in the text it last looked at)
const hasPolicy = (html) => /http-equiv="Content-Security-Policy"/i.test(html);
/** What the build is to give the 404 page: the policy at the top of its head. Nothing is changed in a page that has it. */
const givesNotFoundPolicy = onPath(NOTFOUND_PATH, (answer) =>
  isHtml(answer) && !hasPolicy(textOf(answer)) ? withText(answer, textOf(answer).replace('<meta charset="utf-8">', `<meta charset="utf-8">${POLICY_META}`)) : undefined,
);

const TRIO = "/trio/pal-mnk-ber/";
const ITEM = /^\/item\//;
const SMALL = ["--trios", "1", "--items", "1"];

// ---- no test of this file writes into the real folder of the checks ------------------------------------------------------------------------------

test("no test of this file writes into the real folder of the checks: the folder is a temp one that the file makes, and a refused command line logs there and only there @once", async ({ baseURL }) => {
  const folder = process.env.TRIOFORGE_CHECKS_DIR;
  expect(folder, "TRIOFORGE_CHECKS_DIR is set").toBeTruthy();
  expect(basename(folder)).toMatch(/^smoke-live-e2e-checks-/);
  expect(folder.startsWith(tmpdir())).toBe(true);
  expect(checksDir()).toBe(folder);
  expect(existsSync(join(folder, "smoke-live.log"))).toBe(false);
  const result = await smoke(baseURL, ...SMALL, "--settle=soon"); // (a command line that is wrong is logged in the folder of the checks, since it cannot say where --out is)
  expect(result.code).toBe(2);
  expect(readFileSync(join(folder, "smoke-live.log"), "utf8")).toBe("2026-10-18T10:00:03Z refused --settle must be a number from 0 to 60\n");
});

// ---- the preview of this checkout -----------------------------------------------------------------------------------------------------------

test("the preview of this checkout passes, apart from the policy of the 404 page when the build does not give it yet @once", async ({ baseURL, request }) => {
  const notFound = await (await request.get(NOTFOUND_PATH)).text();
  const result = await smoke(baseURL, ...SMALL);
  if (hasPolicy(notFound)) {
    expect(result.err).toEqual([]);
    expect(result.code).toBe(0);
    expect(existsSync(result.stamp)).toBe(true);
  } else {
    const { header, problems } = failed(result);
    expect(header).toBe("smoke-live: FAILED, 1 problem on SITE (seed 202642)");
    expect(problems).toEqual([`- ${NOTFOUND_PATH}: does not give itself the policy ${NOTFOUND_POLICY} in one <meta> element`]);
    expect(result.code).toBe(1);
    expect(existsSync(result.stamp)).toBe(false);
  }
});

test("a site with the 404 policy passes: five trio pages, five item pages and the 404 page, one line of output and the stamp @once", async ({ baseURL, request }) => {
  await withStandIn(baseURL, givesNotFoundPolicy, async (site) => {
    const result = await smoke(site.origin);
    expect(result.err).toEqual([]);
    expect(result.code).toBe(0);
    const manifest = await (await request.get("/engine-manifest.json")).json();
    const table = await (await request.get(manifest.items.path)).json();
    expect(result.out).toEqual([`smoke-live: ok, 7 pages of ${site.origin} (1 trio, 5 items, 1 not-found page), seed ${SEED}, ${manifest.data_release}`]);
    // the pages it loaded are the seeded choice from the site's own lists
    const wanted = [
      ...sample(trioSlugs(manifest), 5, SEED).map((slug) => `/trio/${slug}/`),
      ...sample(itemPageKeys(table), 5, SEED + 1).map((key) => `/item/${key}/`),
      NOTFOUND_PATH,
    ].sort();
    const loaded = site.requests.filter((asked) => asked.accept.includes("text/html")).map((asked) => asked.pathname).sort();
    expect(loaded).toEqual(wanted);
    // and the stamp is the time in the form the release build reads
    expect(readFileSync(result.stamp, "utf8")).toBe("2026-10-18T10:00:03Z\n");
  });
});

test("every run leaves a line in the log beside the stamp, ok for a pass and failed for a failure, with the first problem @once", async ({ baseURL, request }) => {
  const manifest = await (await request.get("/engine-manifest.json")).json();
  const out = mkdtempSync(join(tmpdir(), "smoke-live-e2e-log-"));
  FOLDERS.push(out);
  await withStandIn(baseURL, givesNotFoundPolicy, async (site) => {
    expect((await smoke(site.origin, ...SMALL, "--out", out)).code).toBe(0);
    expect(readFileSync(join(out, "smoke-live.log"), "utf8")).toBe(
      `2026-10-18T10:00:03Z ok smoke-live: ok, 3 pages of ${site.origin} (1 trio, 1 item, 1 not-found page), seed ${SEED}, ${manifest.data_release}\n`,
    );
    expect((await smoke(site.origin, ...SMALL, "--out", out, "--expect-data", "data-2099-01-01")).code).toBe(1);
    const lines = readFileSync(join(out, "smoke-live.log"), "utf8").trimEnd().split("\n");
    expect(lines).toHaveLength(2);
    expect(lines[1]).toBe(
      `2026-10-18T10:00:03Z failed smoke-live: FAILED, 3 problems on ${site.origin} (seed ${SEED}); first: /engine-manifest.json names the data release ${manifest.data_release}, not data-2099-01-01`,
    );
  });
});

test("a check that is asked for no trio page or no item page is refused, with nothing asked of the site and no stamp, since its stamp would say that pages were checked @once", async ({ baseURL }) => {
  await withStandIn(baseURL, givesNotFoundPolicy, async (site) => {
    for (const argv of [["--trios", "0", "--items", "0"], ["--trios", "0"], ["--items", "0"]]) {
      const result = await smoke(site.origin, ...argv);
      expect(result.code, argv.join(" ")).toBe(2);
      expect(result.err[0], argv.join(" ")).toMatch(/^smoke-live: --(trios|items) must be a whole number from 1 to 100$/);
      expect(result.out).toEqual([]);
      expect(existsSync(result.stamp)).toBe(false);
    }
    expect(site.requests).toEqual([]);
  });
});

test("the data release the pages name is the one that is expected, when one is, and a second release of the day is not the first @once", async ({ baseURL, request }) => {
  const manifest = await (await request.get("/engine-manifest.json")).json();
  await withStandIn(baseURL, givesNotFoundPolicy, async (site) => {
    const matching = await smoke(site.origin, ...SMALL, "--expect-data", manifest.data_release);
    expect(matching.err).toEqual([]);
    expect(matching.code).toBe(0);
    const other = await smoke(site.origin, ...SMALL, "--expect-data", `${manifest.data_release}-2`);
    const { header, problems } = failed(other);
    expect(header).toBe("smoke-live: FAILED, 2 problems on SITE (seed 202642)"); // (the manifest and the trio page, which name the release exactly; the other pages name its date)
    expect(problems).toEqual([
      `- /engine-manifest.json names the data release ${manifest.data_release}, not ${manifest.data_release}-2`,
      `- ${TRIO}: names the data release ${manifest.data_release}, not ${manifest.data_release}-2`,
    ]);
    expect(other.code).toBe(1);
  });
});

test("a release that is not the one expected is named on every trio and item page, and the manifest too @once", async ({ baseURL }) => {
  await withStandIn(baseURL, givesNotFoundPolicy, async (site) => {
    const result = await smoke(site.origin, ...SMALL, "--expect-data", "data-2099-01-01");
    expect(result.code).toBe(1);
    const { header, problems } = failed(result);
    expect(header).toBe("smoke-live: FAILED, 3 problems on SITE (seed 202642)");
    expect(problems.map((line) => line.replace(/\/item\/[a-z0-9-]+\//, "/item/KEY/"))).toEqual([
      expect.stringMatching(/^- \/engine-manifest\.json names the data release data-\d{4}-\d{2}-\d{2}(-\d+)?, not data-2099-01-01$/),
      expect.stringMatching(/^- \/trio\/pal-mnk-ber\/: names the data release data-\d{4}-\d{2}-\d{2}(-\d+)?, not data-2099-01-01$/),
      expect.stringMatching(/^- \/item\/KEY\/: names the data release \d{4}-\d{2}-\d{2}, not data-2099-01-01$/),
    ]);
    expect(existsSync(result.stamp)).toBe(false);
  });
});

test("the data release is read from the trio and item pages, and not from the 404 page, which need not name one @once", async ({ baseURL, request }) => {
  const manifest = await (await request.get("/engine-manifest.json")).json();
  const noStrip = onPath(NOTFOUND_PATH, edit(/<p class="wrap data-strip">[\s\S]*?<\/p>/, "")); // (a 404 page that names no date and no release)
  await withStandIn(baseURL, compose(givesNotFoundPolicy, noStrip), async (site) => {
    const result = await smoke(site.origin, ...SMALL, "--expect-data", manifest.data_release);
    expect(result.err).toEqual([]);
    expect(result.code).toBe(0);
    expect(existsSync(result.stamp)).toBe(true);
    const stale = await smoke(site.origin, ...SMALL, "--expect-data", "data-2099-01-01"); // (and the pages that do name one are still held to it)
    expect(failed(stale).problems.some((line) => line.startsWith(`- ${TRIO}: names the data release`))).toBe(true);
    expect(failed(stale).problems.some((line) => line.startsWith(`- ${NOTFOUND_PATH}: names`))).toBe(false);
  });
});

test("the data release of the newest pointer in releases/ is the one expected by default, and the report says so @once", async ({ baseURL, request }) => {
  const manifest = await (await request.get("/engine-manifest.json")).json();
  const folder = pointers("data-2025-01-01", manifest.data_release); // (an old release, and the one the preview is at: the newest is the second)
  await withStandIn(baseURL, givesNotFoundPolicy, async (site) => {
    const result = await smoke(site.origin, ...SMALL, "--expect-data", "newest", "--releases-dir", folder);
    expect(result.err).toEqual([]);
    expect(result.out).toEqual([
      `smoke-live: ok, 3 pages of ${site.origin} (1 trio, 1 item, 1 not-found page), seed ${SEED}, ${manifest.data_release} (the newest pointer in releases/)`,
    ]);
    expect(existsSync(result.stamp)).toBe(true);
  });
});

test("a site that is not at the release of the newest pointer fails on the manifest and on the trio and item pages, and the report says where the release was expected from @once", async ({
  baseURL,
  request,
}) => {
  const manifest = await (await request.get("/engine-manifest.json")).json();
  const folder = pointers(manifest.data_release, "data-2099-01-01");
  await withStandIn(baseURL, givesNotFoundPolicy, async (site) => {
    const result = await smoke(site.origin, ...SMALL, "--expect-data", "newest", "--releases-dir", folder);
    const { header, problems } = failed(result);
    expect(header).toBe("smoke-live: FAILED, 3 problems on SITE (seed 202642)");
    expect(problems.map((line) => line.replace(/\/item\/[a-z0-9-]+\//, "/item/KEY/"))).toEqual([
      `- /engine-manifest.json names the data release ${manifest.data_release}, not data-2099-01-01`,
      `- ${TRIO}: names the data release ${manifest.data_release}, not data-2099-01-01`,
      expect.stringMatching(/^- \/item\/KEY\/: names the data release \d{4}-\d{2}-\d{2}, not data-2099-01-01$/),
      "  (data-2099-01-01 is expected because it is the newest pointer in releases/; --expect-data none turns that off)",
    ]);
    expect(existsSync(result.stamp)).toBe(false);
  });
});

test("with no pointer in releases/ nothing is expected, and the report says that @once", async ({ baseURL, request }) => {
  const manifest = await (await request.get("/engine-manifest.json")).json();
  await withStandIn(baseURL, givesNotFoundPolicy, async (site) => {
    const result = await smoke(site.origin, ...SMALL, "--expect-data", "newest", "--releases-dir", pointers());
    expect(result.err).toEqual([]);
    expect(result.out).toEqual([
      `smoke-live: ok, 3 pages of ${site.origin} (1 trio, 1 item, 1 not-found page), seed ${SEED}, ${manifest.data_release} (no pointer in releases/, so no data release was expected)`,
    ]);
    const missing = await smoke(site.origin, ...SMALL, "--expect-data", "newest", "--releases-dir", join(pointers(), "no-such-folder"));
    expect(missing.err).toEqual([]);
    expect(missing.out[0]).toContain("(no pointer in releases/, so no data release was expected)");
  });
});

test("--expect-data none turns the expectation off, and a tag beats the newest pointer @once", async ({ baseURL, request }) => {
  const manifest = await (await request.get("/engine-manifest.json")).json();
  const folder = pointers("data-2099-01-01");
  await withStandIn(baseURL, givesNotFoundPolicy, async (site) => {
    const none = await smoke(site.origin, ...SMALL, "--expect-data", "none", "--releases-dir", folder);
    expect(none.err).toEqual([]);
    expect(none.out).toEqual([`smoke-live: ok, 3 pages of ${site.origin} (1 trio, 1 item, 1 not-found page), seed ${SEED}, ${manifest.data_release}`]);
    const tag = await smoke(site.origin, ...SMALL, "--expect-data", manifest.data_release, "--releases-dir", folder);
    expect(tag.err).toEqual([]);
    expect(tag.out).toEqual([`smoke-live: ok, 3 pages of ${site.origin} (1 trio, 1 item, 1 not-found page), seed ${SEED}, ${manifest.data_release}`]);
  });
});

test("a page that names another release than the others is the one that fails @once", async ({ baseURL, request }) => {
  const manifest = await (await request.get("/engine-manifest.json")).json();
  const changed = onPath(TRIO, edit(/data-release="[^"]*"/, 'data-release="data-2026-10-15"'));
  await withStandIn(baseURL, compose(givesNotFoundPolicy, changed), async (site) => {
    const result = await smoke(site.origin, ...SMALL, "--expect-data", manifest.data_release);
    expect(failed(result).problems).toEqual([`- ${TRIO}: names the data release data-2026-10-15, not ${manifest.data_release}`]);
  });
});

// ---- each check, failed in turn ---------------------------------------------------------------------------------------------------------------

/** What a failed check prints when exactly one thing is wrong. */
const ONE_PROBLEM = "smoke-live: FAILED, 1 problem on SITE (seed 202642)";

const STATUS_AND_HEADERS = [
  ["a trio page that answers 500", onPath(TRIO, setStatus(500)), `- ${TRIO}: answered 500, not 200`],
  ["an item page that answers 404", onPath(ITEM, setStatus(404)), /^- \/item\/[a-z0-9-]+\/: answered 404, not 200$/],
  ["a trio page with no policy header", onPath(TRIO, dropHeader("content-security-policy")), `- ${TRIO}: no content-security-policy header`],
  [
    "an item page with a weaker policy",
    onPath(ITEM, (answer) => setHeader("content-security-policy", `${answer.headers["content-security-policy"]}; frame-src *`)(answer)),
    /^- \/item\/[a-z0-9-]+\/: content-security-policy is not what site\/_headers sets$/,
  ],
  ["a trio page that does not say nosniff", onPath(TRIO, setHeader("x-content-type-options", "none")), `- ${TRIO}: x-content-type-options is not what site/_headers sets`],
  ["an item page with no referrer policy", onPath(ITEM, dropHeader("referrer-policy")), /^- \/item\/[a-z0-9-]+\/: no referrer-policy header$/],
  ["a trio page of a preview that does not keep search engines out", onPath(TRIO, dropHeader("x-robots-tag")), `- ${TRIO}: no x-robots-tag noindex (a preview must keep search engines out)`],
  ["a 404 answer with no policy header", onPath(NOTFOUND_PATH, dropHeader("content-security-policy")), `- ${NOTFOUND_PATH}: no content-security-policy header`],
  ["an address that does not exist and gets a 200", onPath(NOTFOUND_PATH, setStatus(200)), `- ${NOTFOUND_PATH}: answered 200, not 404`],
];

for (const [what, change, problem] of STATUS_AND_HEADERS) {
  test(`a site with ${what} fails that and only that @once`, async ({ baseURL }) => {
    await withStandIn(baseURL, compose(givesNotFoundPolicy, change), async (site) => {
      const result = await smoke(site.origin, ...SMALL);
      const { header, problems } = failed(result);
      expect(header).toBe(ONE_PROBLEM);
      expect(problems).toHaveLength(1);
      if (typeof problem === "string") expect(problems[0]).toBe(problem);
      else expect(problems[0]).toMatch(problem);
      expect(result.code).toBe(1);
      expect(result.out).toEqual([]);
      expect(existsSync(result.stamp)).toBe(false); // (a failure leaves no stamp)
    });
  });
}

// ---- the page that came is the page that was asked for ------------------------------------------------------------------------------------------

const sendsTo = (location, status = 302) => () => ({ status, headers: { location }, body: Buffer.alloc(0) });

test("a trio page and an item page that the server sends to the home page fail @once", async ({ baseURL }) => {
  for (const [what, match, problem] of [
    ["a trio page", TRIO, `- ${TRIO}: ended at /, not at its own address (a redirect)`],
    ["an item page", ITEM, /^- \/item\/[a-z0-9-]+\/: ended at \/, not at its own address \(a redirect\)$/],
  ]) {
    await withStandIn(baseURL, compose(givesNotFoundPolicy, onPath(match, sendsTo("/"))), async (site) => {
      const result = await smoke(site.origin, ...SMALL);
      const { header, problems } = failed(result);
      expect(header, what).toBe(ONE_PROBLEM);
      expect(problems, what).toHaveLength(1);
      if (typeof problem === "string") expect(problems[0], what).toBe(problem);
      else expect(problems[0], what).toMatch(problem);
      expect(result.code, what).toBe(1);
      expect(existsSync(result.stamp), what).toBe(false);
    });
  }
});

test("a page that a script of its own moves to the home page after it has loaded fails the same way @once", async ({ baseURL }) => {
  const files = { "/assets/smoke-move.js": 'addEventListener("load", () => setTimeout(() => location.replace("/"), 200));' };
  const moves = onPath(TRIO, edit("</head>", '<script src="/assets/smoke-move.js"></script></head>'));
  await withStandIn(baseURL, compose(givesNotFoundPolicy, moves), async (site) => {
    const { header, problems } = failed(await smoke(site.origin, ...SMALL));
    expect(header).toBe(ONE_PROBLEM);
    expect(problems).toEqual([`- ${TRIO}: ended at /, not at its own address (a redirect)`]);
  }, files);
});

test("a page that is sent to another site is named by its whole address @once", async ({ baseURL }) => {
  await withStandIn(baseURL, undefined, async (elsewhere) => {
    await withStandIn(baseURL, compose(givesNotFoundPolicy, onPath(TRIO, sendsTo(`${elsewhere.origin}/`, 301))), async (site) => {
      const { header, problems } = failed(await smoke(site.origin, ...SMALL));
      expect(header).toBe(ONE_PROBLEM);
      expect(problems).toEqual([`- ${TRIO}: ended at ${elsewhere.origin}/, not at its own address (a redirect)`]);
    });
  });
});

test("an address that does not exist and is sent to the home page fails as a redirect, not only as a status @once", async ({ baseURL }) => {
  await withStandIn(baseURL, compose(givesNotFoundPolicy, onPath(NOTFOUND_PATH, sendsTo("/"))), async (site) => {
    const { problems } = failed(await smoke(site.origin, ...SMALL));
    // (the status of the page it came to, and the redirect; not also that the page is not the 404 page, which is the same thing said again)
    expect(problems).toEqual([`- ${NOTFOUND_PATH}: answered 200, not 404`, `- ${NOTFOUND_PATH}: ended at /, not at its own address (a redirect)`]);
  });
});

test("a page at its own address that is another kind of page fails, trio and item alike @once", async ({ baseURL }) => {
  for (const [what, match, kind, problem] of [
    ["a trio address that serves the about page", TRIO, "trio", `- ${TRIO}: is not a trio page (its main element says data-page=about)`],
    ["an item address that serves the about page", ITEM, "item", /^- \/item\/[a-z0-9-]+\/: is not an item page \(its main element says data-page=about\)$/],
  ]) {
    const change = onPath(match, edit(new RegExp(`data-page="${kind}"`), 'data-page="about"'));
    await withStandIn(baseURL, compose(givesNotFoundPolicy, change), async (site) => {
      const { header, problems } = failed(await smoke(site.origin, ...SMALL));
      expect(header, what).toBe(ONE_PROBLEM);
      expect(problems, what).toHaveLength(1);
      if (typeof problem === "string") expect(problems[0], what).toBe(problem);
      else expect(problems[0], what).toMatch(problem);
    });
  }
});

test("a real site is not expected to keep search engines out: --indexable wants no noindex, and says so for each page that has one @once", async ({ baseURL }) => {
  await withStandIn(baseURL, givesNotFoundPolicy, async (site) => {
    const result = await smoke(site.origin, ...SMALL, "--indexable");
    const { header, problems } = failed(result);
    expect(header).toBe("smoke-live: FAILED, 3 problems on SITE (seed 202642)");
    expect(problems.map((line) => line.replace(/^- [^:]+: /, ""))).toEqual(Array(3).fill("x-robots-tag keeps search engines out, and the site is meant to be found"));
  });
  const real = compose(givesNotFoundPolicy, (answer) => dropHeader("x-robots-tag")(answer));
  await withStandIn(baseURL, real, async (site) => {
    const result = await smoke(site.origin, ...SMALL, "--indexable");
    expect(result.err).toEqual([]);
    expect(result.code).toBe(0);
    expect(existsSync(result.stamp)).toBe(true);
  });
});

test("a page with a console error fails, and so does one with an error of the page @once", async ({ baseURL }) => {
  const files = {
    "/assets/smoke-console-error.js": 'console.error("smoke test: a console error");',
    "/assets/smoke-page-error.js": 'throw new Error("smoke test: a page error");',
  };
  const adds = (name) => onPath(TRIO, edit("</head>", `<script src="/assets/${name}.js"></script></head>`));
  await withStandIn(baseURL, compose(givesNotFoundPolicy, adds("smoke-console-error")), async (site) => {
    const { header, problems } = failed(await smoke(site.origin, ...SMALL));
    expect(header).toBe(ONE_PROBLEM);
    expect(problems).toEqual([`- ${TRIO}: console error: smoke test: a console error`]);
  }, files);
  await withStandIn(baseURL, compose(givesNotFoundPolicy, adds("smoke-page-error")), async (site) => {
    const { header, problems } = failed(await smoke(site.origin, ...SMALL));
    expect(header).toBe(ONE_PROBLEM);
    expect(problems).toEqual([`- ${TRIO}: page error: smoke test: a page error`]);
  }, files);
});

test("a page that asks for a file that is not there fails with the console errors the browser gives @once", async ({ baseURL }) => {
  const adds = onPath(TRIO, edit("</head>", '<link rel="stylesheet" href="/assets/no-such-file.css"></head>'));
  await withStandIn(baseURL, compose(givesNotFoundPolicy, adds), async (site) => {
    const { problems } = failed(await smoke(site.origin, ...SMALL));
    // (the browser says twice what is wrong, once for the answer and once for the type of what came; the page gets one line, with the first and how many more)
    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatch(new RegExp(`^- ${TRIO}: console error: .+`));
    expect(problems[0]).toMatch(/\(and \d+ more\)$/);
  });
});

test("an error that a page makes six seconds after it loaded is seen, when the network was busy for the first three @once", async ({ baseURL }) => {
  // (the page asks for a file that the stand-in answers three seconds late, so the network is idle at three and a half; the check then watches for five seconds more, and the error is at six)
  const files = {
    "/assets/smoke-late-error.js": 'fetch("/assets/smoke-slow.js").catch(() => {}); setTimeout(() => console.error("smoke test: an error at six seconds"), 6000);',
    "/assets/smoke-slow.js": "// answered late",
  };
  const adds = onPath(TRIO, edit("</head>", '<script src="/assets/smoke-late-error.js"></script></head>'));
  await withStandIn(
    baseURL,
    compose(givesNotFoundPolicy, adds),
    async (site) => {
      const result = await smoke(site.origin, ...SMALL, "--settle", "5");
      const { header, problems } = failed(result);
      expect(header).toBe(ONE_PROBLEM);
      expect(problems).toEqual([`- ${TRIO}: console error: smoke test: an error at six seconds`]);
      expect(existsSync(result.stamp)).toBe(false);
    },
    files,
    { "/assets/smoke-slow.js": 3000 },
  );
});

test("a page whose script does not run fails, with the theme button that never showed @once", async ({ baseURL }) => {
  const noScript = onPath(TRIO, edit(/<script type="module"[^>]*><\/script>/g, ""));
  await withStandIn(baseURL, compose(givesNotFoundPolicy, noScript), async (site) => {
    const result = await smoke(site.origin, ...SMALL, "--wait", "1.5");
    const { header, problems } = failed(result);
    expect(header).toBe(ONE_PROBLEM);
    expect(problems).toEqual([`- ${TRIO}: the page script did not run (the theme button never showed)`]);
  });
});

test("the 404 page is held to its own policy: it must give it, once, before anything it loads @once", async ({ baseURL }) => {
  const policyProblem = `- ${NOTFOUND_PATH}: does not give itself the policy ${NOTFOUND_POLICY} in one <meta> element`;
  const cases = [
    ["gives none", edit(POLICY_ELEMENTS, ""), policyProblem],
    ["gives it twice", edit("</head>", `${POLICY_META}</head>`), policyProblem],
    ["gives another policy", edit(POLICY_ELEMENTS, '<meta http-equiv="Content-Security-Policy" content="script-src *">'), policyProblem],
    [
      "gives it after the stylesheet and the scripts",
      (answer) => (isHtml(answer) ? withText(answer, textOf(answer).replace(POLICY_ELEMENTS, "").replace("</head>", `${POLICY_META}</head>`)) : undefined),
      `- ${NOTFOUND_PATH}: gives its own policy after a stylesheet or a script, where it governs nothing that came before`,
    ],
    ["is another page", edit('data-page="notfound"', 'data-page="home"'), `- ${NOTFOUND_PATH}: is not the 404 page of the site (its main element is not data-page=notfound)`],
  ];
  for (const [what, change, problem] of cases) {
    // (the page is given a good policy first, so that what is wrong with it is the one thing the case changes)
    await withStandIn(baseURL, compose(givesNotFoundPolicy, onPath(NOTFOUND_PATH, change)), async (site) => {
      const result = await smoke(site.origin, ...SMALL);
      expect(failed(result).problems, `a 404 page that ${what}`).toEqual([problem]);
    });
  }
});

test("a manifest that is not JSON ends the check at once, with no browser and no stamp @once", async ({ baseURL }) => {
  const maintenance = onPath("/engine-manifest.json", (answer) => ({ ...withText(answer, "<html>Maintenance</html>"), headers: { ...answer.headers, "content-type": "text/html" } }));
  await withStandIn(baseURL, maintenance, async (site) => {
    const result = await smoke(site.origin);
    expect(failed(result)).toEqual({ header: ONE_PROBLEM, problems: ["- /engine-manifest.json is not JSON"] });
    expect(existsSync(result.stamp)).toBe(false);
  });
});

test("--pace puts every request of the check, the browser's included, through one queue, so a check of n requests lasts the n - 1 paces between them @once", async ({ baseURL }) => {
  await withStandIn(baseURL, givesNotFoundPolicy, async (site) => {
    const result = await smoke(site.origin, ...SMALL, "--pace", "0.5");
    expect(result.err).toEqual([]);
    const times = site.requests.map((asked) => asked.at).sort((a, b) => a - b);
    expect(times.length).toBeGreaterThan(5);
    // the first request and the last came at least n - 1 paces apart, less two seconds for requests the browser makes of itself (it is not the pages' own) and for the way there. This is a floor on
    // the time of a deliberate wait, which only a slow machine makes longer; no gap between two requests is measured, because the way of one request can be late and the next not.
    expect(times.at(-1) - times[0]).toBeGreaterThanOrEqual((times.length - 1) * 500 - 2000);
  });
});

// ---- a counting site (--analytics), a tag that was put into the pages, and the kit link --------------------------------------------------------------------------

/** Run the command in this process with a browser whose two hosts of the counter are answered by the test (nothing leaves the machine): the script is a stand-in that does nothing, the report is taken and dropped. */
async function smokeWithTheCounterAnswered(base, ...argv) {
  const out = [];
  const err = [];
  const asked = [];
  const folder = mkdtempSync(join(tmpdir(), "smoke-live-e2e-"));
  FOLDERS.push(folder);
  const launch = async () => {
    const browser = await chromium.launch();
    const newContext = browser.newContext.bind(browser);
    browser.newContext = async (options) => {
      const context = await newContext(options);
      await context.route(/^https:\/\/(static\.)?cloudflareinsights\.com\//, (route) => {
        asked.push(route.request().url());
        return route.request().url().endsWith(".js") ? route.fulfill({ status: 200, contentType: "text/javascript", body: "" }) : route.fulfill({ status: 204, body: "" });
      });
      return context;
    };
    return browser;
  };
  const code = await main(["--base", base, "--out", folder, "--wait", "20", "--settle", "0.3", "--expect-data", "none", ...argv], { log: (line) => out.push(line), error: (line) => err.push(line), now: () => NOW, launch });
  return { code, out, err, asked };
}

const TAG = '<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon=\'{"token": "0123456789abcdef0123456789abcdef"}\'></script>';

test("a counting site passes --analytics: its pages are counted (the counter is asked for, and answered by the test), and the page opened from a kit link asks for nothing of it @once", async ({ request }) => {
  expect((await request.get(`${ANALYTICS_ORIGIN}/`)).ok()).toBe(true);
  await withStandIn(ANALYTICS_ORIGIN, givesNotFoundPolicy, async (site) => {
    const result = await smokeWithTheCounterAnswered(site.origin, ...SMALL, "--analytics");
    expect(result.err).toEqual([]);
    expect(result.code).toBe(0);
    expect(result.asked.length, "the counted pages did ask for the counter").toBeGreaterThan(0);
  });
});

test("a counting tag that was put into the pages (what the dashboard switch of Cloudflare does) is found in both modes, and in --analytics mode the kit link page is found asking for the counter too @once", async ({ baseURL }) => {
  const injected = compose(givesNotFoundPolicy, edit("</body>", `${TAG}</body>`));
  await withStandIn(ANALYTICS_ORIGIN, injected, async (site) => {
    const result = await smokeWithTheCounterAnswered(site.origin, ...SMALL, "--analytics");
    const { problems } = failed({ ...result, err: result.err });
    const tags = problems.filter((line) => line.includes("counting tag"));
    expect(tags).toHaveLength(3); // the trio page, the item page and the 404 page: every page that was opened
    expect(tags.some((line) => line.startsWith(`- ${TRIO}:`)) && tags.some((line) => line.startsWith(`- ${NOTFOUND_PATH}:`))).toBe(true);
    // the kit link page is found three ways (Q5), and the check says exactly these three lines about it, in this order (R4): the counter's script element in the page, the entry of its resource timing, and
    // the request that the browser reported (read after the page has been sent away). Any other line about it (a failed look into the page, a page that could not be loaded) is a failure of this test.
    const kit = problems.filter((line) => line.includes("(a kit link)"));
    expect(kit).toHaveLength(3);
    expect(kit[0].startsWith(`- ${TRIO} (a kit link): has 1 counter script element in the page: a page opened from a kit link is never counted`)).toBe(true);
    expect(kit[1]).toMatch(/\(a kit link\): resource timing lists 1 request to the counter's hosts \(first: static\.cloudflareinsights\.com\) in the page$/);
    expect(kit[2]).toMatch(/\(a kit link\): made [1-9][0-9]* requests? to the counter's hosts \(first: (static\.)?cloudflareinsights\.com\): a page opened from a kit link is never counted/);
  });
  await withStandIn(baseURL, injected, async (site) => {
    const result = await smokeWithTheCounterAnswered(site.origin, ...SMALL);
    const { problems } = failed(result);
    expect(problems.filter((line) => line.includes("counting tag")), "the plain mode finds it as well").toHaveLength(3);
    expect(problems.filter((line) => line.includes("(a kit link)")), "the plain mode opens no kit link page").toEqual([]);
  });
});
