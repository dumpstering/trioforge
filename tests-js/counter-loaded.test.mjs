// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// The page counter judges the address the document was LOADED with, not only the one it has now (Part R, R1). trio.js rewrites the address at start-up (history.replaceState, keeping only the
// page's own switches) when a switch of it is malformed, so that a link such as /trio/x/?race=zzz&utm_source=newsletter, or with a kit spelled as `k=<payload>` in its query, looks clean to a counter that
// is added after the page code has started (the page script adds it last). first.js therefore keeps the address as it was at the very start, in a constant that no later script can write, app.js
// hands it to addCounter, and the counter is added only when both the loaded address and the current one may be counted. The tests run the real start-up: first.js, then the trio page code against the
// baked page, then addCounter. Every token and payload here is invented.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it, vi } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const STATIC = resolve(HERE, "../pipeline/trioforge/site/static");
const CONTRACT = resolve(HERE, "../fixtures/site/contract");
const file = (name) => resolve(STATIC, name).replaceAll("\\", "/");
const TOKEN = "0123456789abcdef0123456789abcdef"; // (invented)
const PAYLOAD = "AQIDBAUGBwgJCgsMDQ4P"; // (made up)
const PAGE = "/trio/pal-mnk-ber/";

/** Open the baked trio page at `address` and run what the page script runs, in its order: first.js, the page code, then the counter. `options.now` is an address that the page is moved to (history.replaceState)
 * after the page code has started and before the counter is added, as a script that runs between them could do it. */
async function open(address, options = {}) {
  vi.resetModules();
  document.head.innerHTML = `<meta name="trioforge-counter" content="${TOKEN}">`;
  document.body.innerHTML = readFileSync(resolve(CONTRACT, "trio-main.html"), "utf8");
  document.documentElement.removeAttribute("data-kit-fragment");
  window.history.replaceState(null, "", address);
  const first = await import(file("first.js"));
  const { initTrio } = await import(file("trio.js"));
  const counter = await import(file("counter.js"));
  initTrio({ document, window, fetch: () => new Promise(() => {}), kit: first.kit });
  if (options.now !== undefined) window.history.replaceState(null, "", options.now);
  const here = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  const added = counter.addCounter({ document, window, kit: first.kit, loaded: "loaded" in options ? options.loaded : first.loadedAddress, trustedTypes: undefined });
  return { added, here, first, counted: document.querySelectorAll("script[data-cf-beacon]").length };
}

beforeEach(() => {
  document.head.innerHTML = "";
});

describe("a trio page whose address the page code rewrites at start-up", () => {
  // the four addresses of the review: every switch that is wrong falls back to its default, the page rewrites the address at once, and what is left looks clean
  for (const [what, address, rewritten] of [
    ["a malformed race and a campaign parameter", `${PAGE}?race=zzz&utm_source=newsletter`, "utm_source"],
    ["an impossible tier and a click identifier", `${PAGE}?tier=99&fbclid=abc`, "fbclid"],
    ["a malformed race and a kit spelled as a query parameter", `${PAGE}?race=zzz&k=${PAYLOAD}`, `k=${PAYLOAD}`],
    ["a malformed race and the old evidence parameter", `${PAGE}?race=zzz&ev=strict`, "ev="],
  ]) {
    it(`is not counted: ${what}`, async () => {
      const opened = await open(address);
      expect(opened.here, "the page code did rewrite the address (so that the address now looks clean)").not.toContain(rewritten);
      expect(opened.first.loadedAddress, "first.js kept the address as it was loaded").toBe(`https://trioforge.test${address}`);
      expect(opened.added).toBe(false);
      expect(opened.counted).toBe(0);
    });
  }

  it("is not counted when the copy of the loaded address is missing (nothing that cannot be judged is counted)", async () => {
    for (const missing of [undefined, null, "", 5, {}]) {
      const opened = await open(`${PAGE}?race=OGR&role=tank&tier=4`, { loaded: missing });
      expect(opened.added, String(missing)).toBe(false);
      expect(opened.counted).toBe(0);
    }
  });

  it("is not counted when the loaded address is the one that is bad and the current one is clean, in either order of the two", async () => {
    const opened = await open(`${PAGE}?race=OGR`, { loaded: `https://trioforge.test${PAGE}?race=OGR&utm_source=x` });
    expect(opened.added).toBe(false);
  });

  it("is not counted when the loaded address is clean and the current one is not: the current address is judged on its own (a kit, a foreign parameter, a malformed switch)", async () => {
    const loaded = `${PAGE}?race=OGR`;
    for (const now of [`${PAGE}?race=OGR&utm_source=x`, `${PAGE}?race=OGR&fbclid=abc`, `${PAGE}?race=OGR&k=${PAYLOAD}`, `${PAGE}?race=OGR#k=${PAYLOAD}`, `${PAGE}?race=zzz`]) {
      const opened = await open(loaded, { now });
      expect(opened.first.loadedAddress, "the loaded address is a clean one").toBe(`https://trioforge.test${loaded}`);
      expect(opened.here, "the page was moved to the other address").toBe(now);
      expect(opened.added, now).toBe(false);
      expect(opened.counted).toBe(0);
    }
    const unmoved = await open(loaded, { now: loaded }); // (the control: the same two addresses, both clean, is counted)
    expect(unmoved.added).toBe(true);
  });

  it("is still counted when its switches are the site's own and nothing is rewritten: an ordinary switch link", async () => {
    for (const address of [PAGE, `${PAGE}?race=OGR&role=tank&tier=4&buffs=own`, `${PAGE}?race=OGR#main`]) {
      const opened = await open(address);
      expect(opened.first.loadedAddress).toBe(`https://trioforge.test${address}`);
      expect(opened.added, address).toBe(true);
      expect(opened.counted).toBe(1);
    }
  });
});
