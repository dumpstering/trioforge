// The helper that opens a page for the other tests (support.mjs: open) says why the page's script did not start. It waits for the script to show the theme button, and a page whose script never
// ran used to fail with "#theme-toggle is hidden" and nothing else: not which request had failed, stalled or been refused, nor what the console said. These tests break the page's script on
// purpose (a route that never answers it, one that refuses it, one that cuts it off, one that throws) and read what the failure says; the lists are also tried on a stand-in for a page, to see
// that they hold paths and not addresses, that they are cut at 20 and that they stop listening when the page has loaded.

import { EventEmitter } from "node:events";
import * as support from "./support.mjs";

const { expect, open, test } = support;

/** The page script of the built site (the module that app.js is hashed into). */
const PAGE_SCRIPT = /\/assets\/app-[A-Z0-9]{8}\.js$/;
const SCRIPT_PATH = /\/assets\/app-[A-Z0-9]{8}\.js/;

/** What open() throws when the page is opened with its script held back, for a short wait. */
async function failureOf(page, holdBack) {
  await page.route(PAGE_SCRIPT, holdBack);
  return open(page, "/", { toggleMs: 1500 }).then(
    () => null,
    (error) => error,
  );
}

test.describe("open() says why the theme button did not show", () => {
  test.describe.configure({ timeout: 12_000 });

  test("a page script that is never answered is named among the requests that never finished @once", async ({ page }) => {
    const failure = await failureOf(page, () => {}); // (the route takes the request and never answers it)
    expect(failure, "open() fails when the script does not come").not.toBeNull();
    expect(failure.message).toMatch(new RegExp(`requests that never finished \\(1\\):\\n {2}GET ${SCRIPT_PATH.source}\\n`));
    expect(failure.message, "the button and the wait are named").toMatch(/#theme-toggle did not show in 1\.5 s/);
    expect(failure.message, "paths, not addresses").not.toMatch(/https?:\/\//);
  });

  test("a page script that is refused is named with its status, and the console's account of it is given @once", async ({ page }) => {
    const failure = await failureOf(page, (route) => route.fulfill({ status: 503, contentType: "text/plain", body: "busy" }));
    expect(failure).not.toBeNull();
    expect(failure.message).toMatch(new RegExp(`answers with a status of 400 or more \\(1\\):\\n {2}503 ${SCRIPT_PATH.source}\\n`));
    expect(failure.message).toMatch(/console errors \(\d+\):[\s\S]*503/);
    expect(failure.message).toMatch(/requests that never finished \(0\): none/);
  });

  test("a page script that is cut off is named among the requests that failed, with the browser's reason @once", async ({ page }) => {
    const failure = await failureOf(page, (route) => route.abort("connectionreset"));
    expect(failure).not.toBeNull();
    expect(failure.message).toMatch(new RegExp(`requests that failed \\(1\\):\\n {2}GET ${SCRIPT_PATH.source} net::ERR_CONNECTION_RESET\\n`));
  });

  test("a page script that throws is named among the page errors, with what it threw @once", async ({ page }) => {
    const failure = await failureOf(page, (route) => route.fulfill({ status: 200, contentType: "text/javascript", body: 'throw new Error("invented failure of the script");' }));
    expect(failure).not.toBeNull();
    expect(failure.message).toMatch(/page errors \(1\):\n {2}.*invented failure of the script/);
    expect(failure.message).toMatch(/requests that failed \(0\): none/);
  });

  test("a page whose script runs opens as before: it has loaded when open() returns, and nothing is left listening @once", async ({ page }) => {
    const listeners = () => Object.fromEntries(["request", "requestfinished", "requestfailed", "response", "console", "pageerror"].map((name) => [name, page.listenerCount(name)]));
    const before = listeners();
    await open(page, "/");
    await expect(page.locator("#theme-toggle")).toBeVisible();
    expect(await page.evaluate(() => document.readyState), "open() returns when the page has loaded, as it did").toBe("complete");
    expect(listeners(), "the recording of the load is stopped").toEqual(before);
  });

  test("the wait is the 20 seconds it was, and it can be shortened for a test @once", () => {
    expect(support.THEME_TOGGLE_WAIT_MS).toBe(20_000);
  });
});

test.describe("what is recorded while a page loads", () => {
  const request = (n, url = `https://trioforge.test/assets/lazy-${n}.js?x=1#y`) => ({ url: () => url, method: () => "GET", failure: () => ({ errorText: "net::ERR_FAILED" }) });

  test("is cut at 20 of each kind, with the number that was left out, and holds paths, not addresses @once", () => {
    const page = new EventEmitter();
    const record = support.recordLoad(page);
    for (let n = 0; n < 25; n += 1) page.emit("requestfailed", request(n));
    const stalled = Array.from({ length: 22 }, (_, n) => request(100 + n));
    for (const one of stalled) page.emit("request", one);
    for (let n = 0; n < 21; n += 1) page.emit("response", { status: () => 500 + n, url: () => `https://trioforge.test/data/x-${n}.json?v=2` });
    const report = record.report();
    expect(report.match(/^ {2}GET \/assets\/lazy-\d+\.js net::ERR_FAILED$/gm)).toHaveLength(20);
    expect(report).toContain("requests that failed (25):");
    expect(report).toContain("… and 5 more");
    expect(report.match(/^ {2}GET \/assets\/lazy-1\d\d\.js$/gm)).toHaveLength(20);
    expect(report).toContain("requests that never finished (22):");
    expect(report).toContain("answers with a status of 400 or more (21):");
    expect(report.match(/^ {2}5\d\d \/data\/x-\d+\.json$/gm)).toHaveLength(20);
    expect(report).not.toContain("trioforge.test");
    expect(report).not.toContain("?x=1");
    expect(report).not.toContain("#y");
    record.stop();
  });

  test("leaves a request out of 'never finished' once it has finished or failed @once", () => {
    const page = new EventEmitter();
    const record = support.recordLoad(page);
    const [done, failed, held] = [request(1), request(2), request(3)];
    for (const one of [done, failed, held]) page.emit("request", one);
    page.emit("requestfinished", done);
    page.emit("requestfailed", failed);
    const report = record.report();
    expect(report).toMatch(/requests that never finished \(1\):\n {2}GET \/assets\/lazy-3\.js\n/);
    expect(report).toMatch(/requests that failed \(1\):\n {2}GET \/assets\/lazy-2\.js net::ERR_FAILED\n/);
    record.stop();
  });

  test("lists console errors and page errors, and no warnings or logs @once", () => {
    const page = new EventEmitter();
    const record = support.recordLoad(page);
    const message = (type, text) => ({ type: () => type, text: () => text, location: () => ({ url: "https://trioforge.test/assets/app-AAAAAAAA.js", lineNumber: 3 }) });
    page.emit("console", message("error", "Failed to load resource"));
    page.emit("console", message("warning", "only a warning"));
    page.emit("console", message("log", "only a log"));
    page.emit("pageerror", new Error("an uncaught exception"));
    const report = record.report();
    expect(report).toMatch(/console errors \(1\):\n {2}Failed to load resource \(\/assets\/app-AAAAAAAA\.js\)\n/);
    expect(report).toMatch(/page errors \(1\):\n {2}an uncaught exception$/m);
    expect(report).not.toContain("only a warning");
    expect(report).not.toContain("only a log");
    record.stop();
  });

  test("says that nothing was seen when nothing was, so that an empty list is not mistaken for one that was not kept @once", () => {
    const page = new EventEmitter();
    const record = support.recordLoad(page);
    const report = record.report();
    for (const title of ["requests that failed", "requests that never finished", "answers with a status of 400 or more", "console errors", "page errors"]) {
      expect(report).toContain(`${title} (0): none`);
    }
    record.stop();
  });

  test("stops listening when it is told to @once", () => {
    const page = new EventEmitter();
    const record = support.recordLoad(page);
    expect(page.listenerCount("requestfailed")).toBe(1);
    record.stop();
    for (const name of ["request", "requestfinished", "requestfailed", "response", "console", "pageerror"]) expect(page.listenerCount(name), name).toBe(0);
  });
});
