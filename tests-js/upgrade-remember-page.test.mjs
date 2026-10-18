// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// Remembered gear on a trio page, end to end in jsdom: the page code reads the device once at the start, starts the code of the Upgrade section for gear it finds, the section puts it
// on the list through the box (remember.js), and the answer, which was made before the box, asks the optimizer about the restored list as it does for any gear. The page is the contract
// copy, the page code and the real code of the section run against the fake site of the engine tests, whose item table is the fixture's (every name in it is invented).

import { afterEach, describe, expect, it, vi } from "vitest";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";
import { makeSite, siteFetch } from "./engine-site-fixture.mjs";
import { fakeEngine } from "./upgrade-answer-helpers.mjs";
import { $, $$, dumpText, mountPage } from "./upgrade-helpers.mjs";

const KEY = "trioforge-gear";
const MAIN = "/engine-manifest.json";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  document.body.replaceChildren();
});

/** The page code on the contract page, with `stored` on the device before it starts. */
function open(stored, { engine = fakeEngine() } = {}) {
  mountPage();
  window.localStorage.clear();
  if (stored !== undefined) window.localStorage.setItem(KEY, stored);
  const made = makeSite();
  made.files.set(MAIN, new TextEncoder().encode(JSON.stringify(made.manifestJson)));
  const net = siteFetch(made);
  const app = initTrio({ document, window, fetch: net.fetchImpl, loadEngine: engine.loadEngine });
  return { app, engine, net };
}
const rows = () => $$("#upgrade-owned > li").map((li) => [li.querySelector(".owned-name").textContent, li.querySelector(".owned-tier").textContent, li.querySelector(".owned-count")?.textContent ?? ""]);
const waitFor = (check) => vi.waitFor(check, { timeout: 5000, interval: 20 });

describe("remembered gear on a page", () => {
  const TEXT = JSON.stringify({ v: 1, entries: [[90001, 4, 1], [90011, 0, 2], [99991, 0, 1]] });

  it("is put back on the list at the start, with no use of the section, and the answer asks the optimizer about it", async () => {
    const { app, engine, net } = open(TEXT);
    expect(net.asked, "nothing is fetched before the code of the section has run").toEqual([]);
    await app.whenIdle();
    await waitFor(() => expect(rows()).toHaveLength(2));
    expect(rows()).toEqual([["Choker of the Deep", "+0", "2 copies"], ["Helm of the Stoneward", "+4", ""]]);
    expect($("#upgrade-remember-box").checked).toBe(true);
    expect($("#upgrade-remember-note").textContent).toMatch(/^Restored 2 items from this device\. 1 remembered item is no longer in the catalog\. Restored gear has no places/);
    expect($("#announce").textContent).toMatch(/^Restored 2 items from this device\./);
    // the pause of the answer is over after 0.6 s; the request names the restored list, in the form the protocol takes
    await waitFor(() => expect(engine.runs).toHaveLength(1));
    expect(engine.runs[0].request.owned).toEqual([["w90011@0", 2], ["w90001@4", 1]]);
    expect(engine.runs[0].request.mode).toBe("farm-path");
  });

  it("keeps the copy on the device as it is now (without what the catalog dropped) and Forget clears the list, the copy and the box", async () => {
    const { app, engine } = open(TEXT);
    await app.whenIdle();
    await waitFor(() => expect(rows()).toHaveLength(2));
    expect(JSON.parse(window.localStorage.getItem(KEY))).toEqual({ v: 1, entries: [[90011, 0, 2], [90001, 4, 1]] });
    $("#upgrade-forget").click();
    expect(window.localStorage.getItem(KEY)).toBeNull();
    expect(rows()).toEqual([]);
    expect($("#upgrade-remember-box").checked).toBe(false);
    expect(document.activeElement).toBe($("#upgrade-remember-box"));
    await new Promise((resolve) => setTimeout(resolve, 800)); // (past the pause: an empty list asks for nothing)
    expect(engine.runs.length).toBeLessThanOrEqual(1);
  });

  it("is replaced by a file read after it: nothing is counted twice, what is kept is the list of the file, and a reload restores the same list", async () => {
    const small = () => new File([dumpText("site-small")], "inventory.txt");
    // a first visit: the gear is read from a file, and the box is checked
    const first = open(undefined);
    $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    await first.app.whenIdle();
    await waitFor(() => expect($("#upgrade-remember-box")).not.toBeNull());
    await first.app.upgrade.readFile(small());
    $("#upgrade-remember-box").checked = true;
    $("#upgrade-remember-box").dispatchEvent(new Event("change", { bubbles: true }));
    const alone = rows();
    expect(alone).toHaveLength(12);
    expect(alone.find(([name]) => name === "Helm of the Stoneward")).toEqual(["Helm of the Stoneward", "+4", "2 copies"]);
    const saved = window.localStorage.getItem(KEY);
    // a second visit: the list comes back, and the same file is read again
    const second = open(saved);
    await second.app.whenIdle();
    await waitFor(() => expect(rows()).toHaveLength(12));
    expect(rows(), "restored").toEqual(alone);
    await second.app.upgrade.readFile(small());
    expect(rows(), "and read again: the Helm is still two, not four").toEqual(alone);
    expect(window.localStorage.getItem(KEY), "what the device keeps is the list of the file").toBe(saved);
    // a third visit
    const third = open(window.localStorage.getItem(KEY));
    await third.app.whenIdle();
    await waitFor(() => expect(rows()).toHaveLength(12));
    expect(rows()).toEqual(alone);
  });

  it("loads nothing and touches the device not at all for a page with nothing stored", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const removeItem = vi.spyOn(Storage.prototype, "removeItem");
    const { app, net } = open(undefined);
    await app.whenIdle();
    expect(net.asked).toEqual([]);
    expect($("#upgrade-remember-box")).toBeNull();
    expect(setItem).not.toHaveBeenCalled();
    expect(removeItem).not.toHaveBeenCalled();
  });

  it("is erased, and said once, when another version of the site stored it", async () => {
    const { app } = open(JSON.stringify({ v: 2, entries: [[90001, 4, 1]] }));
    await app.whenIdle();
    await waitFor(() => expect($("#upgrade-remember-note")).not.toBeNull());
    expect($("#upgrade-remember-note").textContent).toBe("Gear remembered by another version of this site was ignored and erased.");
    expect(window.localStorage.getItem(KEY)).toBeNull();
    expect(rows()).toEqual([]);
    expect($("#upgrade-remember-box").checked).toBe(false);
  });

  it("is checked for the first time on a page that started with nothing: the box keeps what the list holds from then on", async () => {
    const { app } = open(undefined);
    $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    await app.whenIdle();
    await waitFor(() => expect($("#upgrade-remember-box")).not.toBeNull());
    expect(window.localStorage.getItem(KEY)).toBeNull();
    $("#upgrade-remember-box").checked = true;
    $("#upgrade-remember-box").dispatchEvent(new Event("change", { bubbles: true }));
    expect(window.localStorage.getItem(KEY), "an empty list is not kept").toBeNull();
    expect($("#upgrade-remember-note").textContent).toBe("Your gear will be remembered on this device as you add it.");
  });
});
