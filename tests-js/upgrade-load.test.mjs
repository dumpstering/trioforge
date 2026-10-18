// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// The code of the Upgrade section is loaded when the section is first used, and then it fetches the item list as the worker does: the path, the size and the SHA-256 of
// engine-manifest.json, checked before a byte is read as text, parsed with readItemTable, once for the page. The trio page carries the release of its data: when the manifest
// names another, the page's own "updated" notice is shown and none of the data is used. The page is the contract copy of the trio page, run with the code of the page (trio.js)
// against the fake site of the engine tests (makeSite and siteFetch), whose item table is the fixture's.

import { describe, expect, it, vi } from "vitest";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";
import { ITEMS_BYTES, ORIGIN, makeSite, piecesOf, siteFetch } from "./engine-site-fixture.mjs";
import { $, $$, choose, drop as dropOn, dumpText, mountPage, press, type } from "./upgrade-helpers.mjs";

const MAIN = "/engine-manifest.json";
const UPDATED = "Data updated, reload the page to see the new data.";
const SECTION_UPDATED = "Data updated, reload the page to see this section.";
/** Wait for something that happens after a read or a download, with room for a busy machine. */
const waitFor = (check) => vi.waitFor(check, { timeout: 5000, interval: 20 });
const encode = (value) => new TextEncoder().encode(typeof value === "string" ? value : JSON.stringify(value));

/** A site that serves the manifest as well (the fake site of the engine tests serves the data files and the manifests of the trios). */
function site({ manifest, items, ...options } = {}) {
  const made = makeSite({ items, ...options });
  const document = manifest ? manifest(structuredClone(made.manifestJson)) : made.manifestJson;
  made.files.set(MAIN, encode(document));
  return made;
}

/** The page with its code started; `fetch` is the site's (the page code fetches with it), `extra` replaces anything of the environment. */
function open(made = site(), { serve, delay, extra = {}, type: contentType, release } = {}) {
  mountPage();
  if (release !== undefined) document.getElementById("main").dataset.release = release;
  const net = siteFetch(made, { serve, type: contentType });
  // `delay(path)` may give a promise that the answer to a request waits for
  const fetchImpl = delay
    ? async (url, init) => {
        const wait = delay(new URL(url).pathname);
        if (wait) await wait;
        return net.fetchImpl(url, init);
      }
    : net.fetchImpl;
  const reload = vi.fn();
  const app = initTrio({ document, window, fetch: fetchImpl, reload, ...extra });
  return { app, net, reload, made };
}

const wake = (target = "#upgrade-pick") => $(target).dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
const loadText = () => $("#upgrade-load .status-text")?.textContent ?? "";
const options = () => $$('#upgrade-list [role="option"] .li-name').map((n) => n.textContent);
const asked = (net) => net.asked.map((url) => new URL(url).pathname);

// ---- nothing is loaded before the section is used -----------------------------------------------------------------------------------------------

describe("before the section is used", () => {
  it("nothing of it is loaded or fetched, and its controls are awake", () => {
    const { app, net } = open();
    expect(app.upgrade).toBeNull();
    expect(net.asked).toEqual([]);
    for (const id of ["upgrade-file", "upgrade-pick", "upgrade-tier"]) expect(document.getElementById(id).disabled, id).toBe(false);
    expect($("#upgrade-add").disabled).toBe(true); // until there is an item list to add from
  });

  it("is not woken by a click on the words of the section, nor by text or a link dragged over it", async () => {
    const { app, net } = open();
    $("#upgrade-h").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    $("#upgrade-file-help").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    for (const type of ["dragenter", "dragover", "drop"]) {
      const event = Object.assign(new Event(type, { bubbles: true, cancelable: true }), { dataTransfer: { types: ["text/plain", "text/uri-list"], files: [] } });
      $("#upgrade-drop").dispatchEvent(event);
      expect(event.defaultPrevented, `${type} of text is left to the browser`).toBe(false);
    }
    await app.whenIdle();
    expect(app.upgrade).toBeNull();
    expect(net.asked).toEqual([]);
  });

  it("is not woken by the page's other controls, nor by a switch", async () => {
    const { app, net } = open();
    $("#sw-race").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    $("#kit-body").click();
    await app.whenIdle();
    expect(app.upgrade).toBeNull();
    expect(net.asked).toEqual([]);
  });
});

// ---- the first use ------------------------------------------------------------------------------------------------------------------------------

describe("the first use", () => {
  it("is woken by the first focus on a control of the section, and fetches the manifest and then the item list the manifest names", async () => {
    const { app, net, made } = open();
    wake();
    await app.whenIdle();
    expect(asked(net)).toEqual([MAIN, made.itemsPath]);
    expect(app.upgrade).not.toBeNull();
    expect(app.upgrade.gear).not.toBeNull();
    expect($("#upgrade-add").disabled).toBe(false);
    type($("#upgrade-pick"), "lark");
    expect(options()).toEqual(["Larkspur Pauldrons"]);
  });

  it.each([
    ["a click", () => $("#upgrade-drop").dispatchEvent(new MouseEvent("click", { bubbles: true }))],
    ["a focus on the file input", () => wake("#upgrade-file")],
    ["a focus on the tier", () => wake("#upgrade-tier")],
    ["a drag of a file over the section", () => $("#upgrade-drop").dispatchEvent(Object.assign(new Event("dragenter", { bubbles: true, cancelable: true }), { dataTransfer: { types: ["Files"], files: [] } }))],
  ])("is woken by %s too", async (_, act) => {
    const { app, net } = open();
    act();
    await app.whenIdle();
    expect(app.upgrade).not.toBeNull();
    expect(asked(net)[0]).toBe(MAIN);
  });

  it("asks the server whether its copy of the manifest is current, and asks for the item list as the worker does: of this site only, with no credentials of another", async () => {
    const inits = [];
    const { app, net } = open(site(), { serve: (url, init) => void inits.push([new URL(url).pathname, init]) });
    wake();
    await app.whenIdle();
    expect(inits.map(([path]) => path)).toHaveLength(2);
    expect(inits[0][1]).toMatchObject({ credentials: "same-origin", cache: "no-cache" });
    expect(inits[1][1]).toMatchObject({ credentials: "same-origin" });
    expect(new Set(net.asked.map((url) => new URL(url).origin))).toEqual(new Set([ORIGIN]));
  });

  it("loads the item list once for the page, however often the section is used", async () => {
    const { app, net } = open();
    wake();
    wake("#upgrade-file");
    wake("#upgrade-tier");
    await app.whenIdle();
    $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    await app.whenIdle();
    expect(net.asked).toHaveLength(2);
  });

  it("says that it is loading the item list while it does, and nothing when it has", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const made = site();
    const { app } = open(made, { delay: (path) => (path === made.itemsPath ? gate : undefined) });
    $("#upgrade-pick").focus();
    await waitFor(() => expect(loadText()).toBe("Loading the item list…"));
    expect($("#upgrade-load").classList.contains("quiet")).toBe(false);
    expect($("#upgrade-add").disabled).toBe(true);
    type($("#upgrade-pick"), "lark"); // the box takes what is typed meanwhile, and shows nothing yet
    expect(options()).toEqual([]);
    release();
    await app.whenIdle();
    expect(loadText()).toBe("");
    expect($("#upgrade-load").classList.contains("quiet")).toBe(true);
    expect(options()).toEqual(["Larkspur Pauldrons"]); // and offers it as soon as the list is in, from the text that was typed meanwhile (the box has the focus)
  });

  it("refuses a manifest larger than the page reads (64 KB), as the worker does, though it is in the format", async () => {
    const letters = (n) => [Math.floor(n / 676) % 26, Math.floor(n / 26) % 26, n % 26].map((d) => String.fromCharCode(97 + d)).join("");
    const many = (m) => {
      for (let i = 0; i < 3600; i += 1) m.trios[`${letters(i)}-aaa-aaa`] = [50]; // 3,600 trios: about 68 KB, which the format allows (5,000 trios) and the limit does not
      return m;
    };
    const { app } = open(site({ manifest: many }));
    wake();
    await app.whenIdle();
    expect(loadText()).toBe("Couldn't load the item list. The list of the site's files is too large.");
    expect(app.upgrade.gear).toBeNull();
  });
});

// ---- a file that comes before the code does -------------------------------------------------------------------------------------------------------

describe("a file given before the item list is in", () => {
  it("is kept, and read when the list is: dropped on the section", async () => {
    const { app } = open();
    const file = new File([dumpText("site-small")], "secret.txt");
    const drop = Object.assign(new Event("drop", { bubbles: true, cancelable: true }), { dataTransfer: { types: ["Files"], files: [file] } });
    $("#upgrade-drop").dispatchEvent(drop);
    expect(drop.defaultPrevented).toBe(true);
    await app.whenIdle();
    await waitFor(() => expect(app.upgrade.gear.owned()).toHaveLength(12));
    expect($("#announce").textContent).toBe("12 items read, 1 not in the catalog.");
  });

  it("is kept, and read when the list is: chosen with the file input", async () => {
    const { app } = open();
    const input = $("#upgrade-file");
    Object.defineProperty(input, "files", { value: [new File([dumpText("site-small")], "secret.txt")], configurable: true });
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await app.whenIdle();
    await waitFor(() => expect(app.upgrade.gear.owned()).toHaveLength(12));
  });

  it("is kept too when it comes while the item list is loading, the code of the section being there already, and the browser does not open it", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const made = site();
    const { app } = open(made, { delay: (path) => (path === made.itemsPath ? gate : undefined) });
    wake();
    await waitFor(() => expect(loadText()).toBe("Loading the item list…"));
    const drop = Object.assign(new Event("drop", { bubbles: true, cancelable: true }), { dataTransfer: { types: ["Files"], files: [new File([dumpText("site-small")], "secret.txt")] } });
    $("#upgrade-drop").dispatchEvent(drop);
    expect(drop.defaultPrevented).toBe(true);
    const over = Object.assign(new Event("dragover", { bubbles: true, cancelable: true }), { dataTransfer: { types: ["Files"], files: [] } });
    $("#upgrade-drop").dispatchEvent(over);
    expect(over.defaultPrevented).toBe(true);
    expect($("#upgrade-owned").children).toHaveLength(0);
    release();
    await app.whenIdle();
    await waitFor(() => expect(app.upgrade.gear.owned()).toHaveLength(12));
  });

  it("is kept through a failure, and read when Try again works", async () => {
    let failing = true;
    const made = site();
    const { app } = open(made, { serve: (url) => (failing && new URL(url).pathname === made.itemsPath ? new Response("nope", { status: 503 }) : undefined) });
    const input = $("#upgrade-file");
    Object.defineProperty(input, "files", { value: [new File([dumpText("site-small")], "secret.txt")], configurable: true });
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await app.whenIdle();
    expect(loadText()).toMatch(/^Couldn't load the item list\./);
    expect($("#upgrade-owned").children).toHaveLength(0);
    failing = false;
    $("#upgrade-load button").click();
    await app.whenIdle();
    await waitFor(() => expect(app.upgrade.gear.owned()).toHaveLength(12));
  });

  it("is not read at all when the data was updated: the page says so and the file is left alone", async () => {
    const { app } = open(site({ manifest: (m) => ({ ...m, data_release: "data-2026-10-15" }) }));
    const drop = Object.assign(new Event("drop", { bubbles: true, cancelable: true }), { dataTransfer: { types: ["Files"], files: [new File([dumpText("site-small")], "x.txt")] } });
    $("#upgrade-drop").dispatchEvent(drop);
    await app.whenIdle();
    expect($("#upgrade-owned").children).toHaveLength(0);
    expect(app.upgrade.gear).toBeNull();
  });
});

// ---- the release --------------------------------------------------------------------------------------------------------------------------------

describe("a release of the data that is not the page's", () => {
  const newer = () => site({ manifest: (m) => ({ ...m, data_release: "data-2026-10-15" }) });

  it("shows the page's notice that the data was updated, with its Reload button, and uses none of the data", async () => {
    const made = newer();
    const { app, net, reload } = open(made);
    wake();
    await app.whenIdle();
    expect(asked(net)).toEqual([MAIN]); // the item list is not even asked for
    expect($("#status").querySelector(".status-text").textContent).toBe(UPDATED);
    const button = $("#status button");
    expect(button.textContent).toBe("Reload");
    button.click();
    expect(reload).toHaveBeenCalledTimes(1);
    expect(loadText()).toBe(SECTION_UPDATED);
    expect($("#upgrade-load").hasAttribute("aria-live") || $("#upgrade-load").hasAttribute("role"), "the page's notice is the one that is said; this line is not a live region").toBe(false);
    expect(app.upgrade.gear).toBeNull();
    expect($("#upgrade-add").disabled).toBe(true);
    type($("#upgrade-pick"), "lark");
    expect(options()).toEqual([]);
    expect($("#upgrade-owned").children).toHaveLength(0);
  });

  it("is compared with the release the page was built for, and a page of that release uses the data", async () => {
    const { app } = open(site(), { release: "data-2026-10-14" });
    wake();
    await app.whenIdle();
    expect(app.upgrade.gear).not.toBeNull();
    expect($("#status").textContent).toBe("");
    const stale = open(site(), { release: "data-2026-10-01" });
    wake();
    await stale.app.whenIdle();
    expect($("#status").querySelector(".status-text").textContent).toBe(UPDATED);
  });

  it("is looked at when the manifest is first read, and the data is not asked for again afterwards", async () => {
    const { app, net } = open(newer());
    wake();
    wake("#upgrade-file");
    await app.whenIdle();
    expect(asked(net)).toEqual([MAIN]);
    wake();
    await app.whenIdle();
    expect(asked(net)).toEqual([MAIN]); // the notice stays, and nothing is fetched again
  });

  it("is also refused when it is the item list that is of another release than the manifest's", async () => {
    const table = JSON.parse(new TextDecoder().decode(ITEMS_BYTES));
    table.data_release = "data-2026-10-15";
    const { app } = open(site({ items: encode(table) }));
    wake();
    await app.whenIdle();
    expect(loadText()).toMatch(/^Couldn't load the item list\. .*not .*release/);
    expect(app.upgrade.gear).toBeNull();
    expect($("#status button")).toBeNull(); // (it is no news of a new release: the manifest and the page agree)
  });
});

// ---- what fails ---------------------------------------------------------------------------------------------------------------------------------

describe("when the item list cannot be loaded", () => {
  it("says what failed, with a Try again button that fetches it again and puts the focus back in the section when it works", async () => {
    let failing = true;
    const made = site();
    const { app, net } = open(made, { serve: (url) => (failing && new URL(url).pathname === made.itemsPath ? new Response("nope", { status: 503 }) : undefined) });
    wake();
    await app.whenIdle();
    expect(loadText()).toBe("Couldn't load the item list. The optimizer's data file could not be loaded (503).");
    const retry = $("#upgrade-load button");
    expect(retry.textContent).toBe("Try again");
    expect($("#upgrade-add").disabled).toBe(true);
    failing = false;
    retry.focus();
    retry.click();
    await app.whenIdle();
    expect(loadText()).toBe("");
    expect($("#upgrade-load button")).toBeNull();
    expect($("#upgrade-add").disabled).toBe(false);
    expect(document.activeElement).toBe($("#upgrade-h"));
    expect(asked(net).filter((path) => path === MAIN)).toHaveLength(2); // (the manifest is read again with it: the release may have changed)
  });

  it("says so when the list of files cannot be read", async () => {
    const { app } = open(site(), { serve: (url) => (new URL(url).pathname === MAIN ? new Response("gone", { status: 404 }) : undefined) });
    wake();
    await app.whenIdle();
    expect(loadText()).toBe("Couldn't load the item list. The list of the site's files could not be loaded (404).");
    expect($("#upgrade-load button").textContent).toBe("Try again");
  });

  it("says so when the network is down", async () => {
    const { app } = open(site(), { serve: () => Promise.reject(new TypeError("Failed to fetch")) });
    wake();
    await app.whenIdle();
    expect(loadText()).toBe("Couldn't load the item list. The list of the site's files could not be loaded.");
    expect($("#upgrade-load button")).not.toBeNull();
  });

  it("refuses an item list whose SHA-256 is not the one the manifest lists, and uses none of it", async () => {
    const wrong = site({ lie: { items: { sha256: "0".repeat(64) } } });
    const { app } = open(wrong);
    wake();
    await app.whenIdle();
    expect(loadText()).toBe("Couldn't load the item list. The item list is not the one the site lists (its checksum differs).");
    expect($("#upgrade-load button").textContent).toBe("Try again");
    expect(app.upgrade.gear).toBeNull();
    type($("#upgrade-pick"), "lark");
    expect(options()).toEqual([]);
    expect($("#upgrade-add").disabled).toBe(true);
  });

  it("refuses bytes that are not the ones the manifest lists even when they are the right size, before they are parsed", async () => {
    const swapped = new Uint8Array(ITEMS_BYTES);
    swapped[swapped.length - 3] ^= 1; // one bit of the item list
    const made = site();
    const { app } = open(made, { serve: (url) => (new URL(url).pathname === made.itemsPath ? new Response(piecesOf(swapped), { status: 200, headers: { "content-type": "application/json" } }) : undefined) });
    wake();
    await app.whenIdle();
    expect(loadText()).toMatch(/checksum differs/);
    expect(app.upgrade.gear).toBeNull();
  });

  it("refuses a list that is longer or shorter than the manifest says, and one that is served as something else than JSON", async () => {
    const made = site();
    const longer = new Uint8Array([...ITEMS_BYTES, 32, 32]);
    const a = open(made, { serve: (url) => (new URL(url).pathname === made.itemsPath ? new Response(longer, { status: 200, headers: { "content-type": "application/json" } }) : undefined) });
    wake();
    await a.app.whenIdle();
    expect(loadText()).toMatch(/larger than it should be/);
    const b = open(site(), { type: "text/html" });
    wake();
    await b.app.whenIdle();
    expect(loadText()).toMatch(/served with the wrong type/);
  });

  it("refuses an item list that parses but is not what the site writes", async () => {
    const { app } = open(site({ items: encode({ version: 1, items: [] }) }));
    wake();
    await app.whenIdle();
    expect(loadText()).toBe("Couldn't load the item list. The item list is not what the site writes.");
    const bad = open(site({ items: encode("[1, 2") }));
    wake();
    await bad.app.whenIdle();
    expect(loadText()).toBe("Couldn't load the item list. The item list is not what the site writes.");
  });

  it("does not echo what the server sent: a message names no address and shows no content", async () => {
    const { app } = open(site(), { serve: (url) => (new URL(url).pathname === MAIN ? new Response("<script>alert(1)</script>https://evil.example/", { status: 200 }) : undefined) });
    wake();
    await app.whenIdle();
    expect(loadText()).not.toMatch(/script|evil|https?:/);
    expect(loadText()).toMatch(/^Couldn't load the item list\./);
  });
});

// ---- the code of the section itself fails to load -----------------------------------------------------------------------------------------------------

describe("when the code of the section cannot be loaded", () => {
  const NOT_LOADED = "Couldn't load the Upgrade section. Reload the page to try again.";
  const chunk = () => import("../pipeline/trioforge/site/static/ui/upgrade-input.js");
  const buttons = () => $$("#upgrade-load button").map((button) => button.textContent);

  it("says so in the section's own line, near the controls, with one Reload button and no Try again: a browser keeps a failed module fetch until the page is reloaded", async () => {
    const loadUpgrade = vi.fn(() => Promise.reject(new Error("chunk")));
    const { app, reload } = open(site(), { extra: { loadUpgrade } });
    wake();
    await app.whenIdle();
    expect(loadText()).toBe(NOT_LOADED);
    expect(buttons()).toEqual(["Reload"]);
    expect($("#status .status-text"), "the page's status at the top is far from the section, and is not used").toBeNull();
    expect($("#status button")).toBeNull();
    expect($("#upgrade-load").classList.contains("quiet")).toBe(false);
    expect(app.upgrade).toBeNull();
    $("#upgrade-load button").click();
    expect(reload, "the page's own reload").toHaveBeenCalledTimes(1);
    expect(loadUpgrade, "and no second go of its own").toHaveBeenCalledTimes(1);
  });

  it("says it through the page's live region too, once", async () => {
    const { app } = open(site(), { extra: { loadUpgrade: () => Promise.reject(new Error("chunk")) } });
    const said = recordTextOf($("#announce"));
    wake();
    await app.whenIdle();
    expect(said).toEqual([NOT_LOADED]);
  });

  it("says the same, with the same button, when the code is there and will not start", async () => {
    const initUpgrade = () => {
      throw new Error("start");
    };
    const { app, reload } = open(site(), { extra: { loadUpgrade: () => Promise.resolve({ initUpgrade }) } });
    wake();
    await app.whenIdle();
    expect(loadText()).toBe(NOT_LOADED);
    expect(buttons()).toEqual(["Reload"]);
    expect(app.upgrade).toBeNull();
    $("#upgrade-load button").click();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("is not a use of the section to focus or press the Reload button: the page is reloaded, and nothing is tried meanwhile", async () => {
    const loadUpgrade = vi.fn(() => Promise.reject(new Error("chunk")));
    const { app, reload } = open(site(), { extra: { loadUpgrade } });
    wake();
    await app.whenIdle();
    $("#upgrade-load button").focus();
    $("#upgrade-load button").click();
    await app.whenIdle();
    expect(loadUpgrade).toHaveBeenCalledTimes(1);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("is tried again, without a word, by the next use of a control of the section, for a browser that does not keep the failure; the line goes when that works", async () => {
    let fail = true;
    const loadUpgrade = vi.fn(() => (fail ? Promise.reject(new Error("chunk")) : chunk()));
    const { app } = open(site(), { extra: { loadUpgrade } });
    const said = recordTextOf($("#announce"));
    wake();
    await app.whenIdle();
    $("#upgrade-tier").focus(); // another use, and it fails again: there is nothing new to say
    await app.whenIdle();
    expect(loadUpgrade).toHaveBeenCalledTimes(2);
    expect(said).toEqual([NOT_LOADED]);
    expect(loadText()).toBe(NOT_LOADED);
    expect(buttons()).toEqual(["Reload"]);
    fail = false;
    $("#upgrade-pick").focus();
    await app.whenIdle();
    expect(app.upgrade).not.toBeNull();
    expect(loadText()).toBe("");
    expect(buttons()).toEqual([]);
    expect($("#upgrade-add").disabled).toBe(false);
  });

  it("keeps the focus on its button through a later use that fails, and gives it to the heading of the section when a later use works and the button goes", async () => {
    let fail = true;
    const loadUpgrade = vi.fn(() => (fail ? Promise.reject(new Error("chunk")) : chunk()));
    const { app } = open(site(), { extra: { loadUpgrade } });
    wake();
    await app.whenIdle();
    $("#upgrade-load button").focus();
    dropOn($("#upgrade-drop"), [], { type: "dragover" }); // (a file dragged over the section is a use of it that does not move the focus)
    await app.whenIdle();
    expect(loadUpgrade).toHaveBeenCalledTimes(2);
    expect(document.activeElement).toBe($("#upgrade-load button"));
    fail = false;
    dropOn($("#upgrade-drop"), [], { type: "dragover" });
    await app.whenIdle();
    expect(app.upgrade).not.toBeNull();
    expect($("#upgrade-load button")).toBeNull();
    expect(document.activeElement, "the button is gone: the focus is on the heading of the section").toBe($("#upgrade-h"));
  });

  it("does not take the focus from where the visitor moved it meanwhile", async () => {
    let fail = true;
    const loadUpgrade = vi.fn(() => (fail ? Promise.reject(new Error("chunk")) : chunk()));
    const { app } = open(site(), { extra: { loadUpgrade } });
    wake();
    await app.whenIdle();
    fail = false;
    $("#upgrade-tier").focus(); // the next use, which works
    await app.whenIdle();
    expect(app.upgrade).not.toBeNull();
    expect(document.activeElement).toBe($("#upgrade-tier"));
  });

  it("is told with a Reload only for the code: the item list is fetched again, and keeps its Try again", async () => {
    const made = site();
    const { app } = open(made, { serve: (url) => (new URL(url).pathname === made.itemsPath ? new Response("nope", { status: 503 }) : undefined) });
    wake();
    await app.whenIdle();
    expect(buttons()).toEqual(["Try again"]);
  });
});

// ---- nothing else is touched -------------------------------------------------------------------------------------------------------------------------

describe("what the section keeps to itself", () => {
  it("writes nothing to storage, and asks no one but the site for anything, whatever it does", async () => {
    const stored = [];
    for (const name of ["setItem", "removeItem", "clear"]) vi.spyOn(Storage.prototype, name).mockImplementation((...args) => stored.push([name, ...args]));
    const { app, net } = open();
    wake();
    await app.whenIdle();
    const input = $("#upgrade-file");
    Object.defineProperty(input, "files", { value: [new File([dumpText("site-small")], "secret.txt")], configurable: true });
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await waitFor(() => expect(app.upgrade.gear.owned()).toHaveLength(12));
    type($("#upgrade-pick"), "lark");
    press($("#upgrade-pick"), "ArrowDown");
    press($("#upgrade-pick"), "Enter");
    $("#upgrade-add").click();
    expect(stored).toEqual([]);
    expect(document.cookie).toBe("");
    expect(asked(net)).toHaveLength(2); // the manifest and the item list: reading a file and adding an item ask for nothing
    vi.restoreAllMocks();
  });
});

// ---- the live regions of the page ---------------------------------------------------------------------------------------------------------------------

describe("the live regions of the page", () => {
  const live = () => $$('[role="status"], [role="alert"], [role="log"], [aria-live]').map((node) => node.id);
  const TWO = ["status", "announce"];

  it("are the page's two, #status and #announce, and the section adds none: before it is used, while it loads, when it cannot load, when the data is newer, when it is ready", async () => {
    open();
    expect(live(), "before it is used").toEqual(TWO);

    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const made = site();
    const loading = open(made, { delay: (path) => (path === made.itemsPath ? gate : undefined) });
    wake();
    await waitFor(() => expect(loadText()).toBe("Loading the item list…"));
    expect(live(), "while the item list loads").toEqual(TWO);
    release();
    await loading.app.whenIdle();
    expect(live(), "when it is ready").toEqual(TWO);
    await loading.app.upgrade.gear.readFile(new File([dumpText("site-mixed")], "x.txt"));
    expect($("#upgrade-banner").hidden).toBe(false);
    expect(live(), "with a banner of choices").toEqual(TWO);

    const broken = open(made, { serve: (url) => (new URL(url).pathname === made.itemsPath ? new Response("nope", { status: 503 }) : undefined) });
    wake();
    await broken.app.whenIdle();
    expect($("#upgrade-load button")).not.toBeNull();
    expect(live(), "when it cannot load").toEqual(TWO);

    const newer = open(site({ manifest: (m) => ({ ...m, data_release: "data-2026-10-15" }) }));
    wake();
    await newer.app.whenIdle();
    expect(loadText()).toBe(SECTION_UPDATED);
    expect(live(), "when the data is newer").toEqual(TWO);

    const noCode = open(site(), { extra: { loadUpgrade: () => Promise.reject(new Error("chunk")) } });
    wake();
    await noCode.app.whenIdle();
    expect($("#upgrade-load button")).not.toBeNull();
    expect(live(), "when its code cannot be had").toEqual(TWO);
  });

  it("are used once for what the loading line shows: the loading, and the failure, are said through #announce", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const made = site();
    const { app } = open(made, { serve: (url) => (new URL(url).pathname === made.itemsPath ? new Response("nope", { status: 503 }) : undefined), delay: (path) => (path === made.itemsPath ? gate : undefined) });
    const said = recordTextOf($("#announce"));
    wake();
    await waitFor(() => expect(loadText()).toBe("Loading the item list…"));
    expect(said).toEqual(["Loading the item list…"]);
    release();
    await app.whenIdle();
    expect(loadText()).toBe("Couldn't load the item list. The optimizer's data file could not be loaded (503).");
    expect(said).toEqual(["Loading the item list…", loadText()]);
  });

  it("do not say again, through #announce, what the page's #status says when the data is newer", async () => {
    const { app } = open(site({ manifest: (m) => ({ ...m, data_release: "data-2026-10-15" }) }));
    const said = recordTextOf($("#announce"));
    wake();
    await app.whenIdle();
    expect($("#status .status-text").textContent).toBe(UPDATED);
    expect(said.filter((text) => text.includes("Data updated"))).toEqual([]);
  });
});

/** Every text that is put into an element as its text, in order (what a screen reader would be given one after the other). */
function recordTextOf(node) {
  const seen = [];
  const own = Object.getOwnPropertyDescriptor(Node.prototype, "textContent");
  Object.defineProperty(node, "textContent", {
    configurable: true,
    get() {
      return own.get.call(this);
    },
    set(value) {
      seen.push(String(value));
      own.set.call(this, value);
    },
  });
  return seen;
}

// ---- a file dragged over the page outside the section ------------------------------------------------------------------------------------------------

describe("a file dragged over the page outside the section", () => {
  const dumpFile = () => new File([dumpText("site-small")], "Zorbwick-faketown-inventory.txt");
  const outside = () => [document.body, document.documentElement, document, $("#main"), $("h1"), $("#kit-body"), $("#status"), $("#announce"), $("#upgrade").previousElementSibling].filter(Boolean);

  it("is not opened by the browser in place of the page: the dragover and the drop are cancelled, the drop effect is none, and nothing is loaded or read", async () => {
    const loadUpgrade = vi.fn(() => import("../pipeline/trioforge/site/static/ui/upgrade-input.js"));
    const { app, net } = open(site(), { extra: { loadUpgrade } });
    for (const target of outside()) {
      const over = dropOn(target, [dumpFile()], { type: "dragover", effect: "copy" });
      expect(over.defaultPrevented, `a dragover on ${target.nodeName}`).toBe(true);
      expect(over.dataTransfer.dropEffect, "and it will do nothing").toBe("none");
      const dropped = dropOn(target, [dumpFile()]);
      expect(dropped.defaultPrevented, `a drop on ${target.nodeName}`).toBe(true);
    }
    await app.whenIdle();
    expect(loadUpgrade, "dropped elsewhere than on the section is not a use of it").not.toHaveBeenCalled();
    expect(asked(net)).toEqual([]);
    expect(app.upgrade).toBeNull();
    expect($("#upgrade-owned").children).toHaveLength(0);
    expect($("#announce").textContent).toBe("");
    expect(window.location.href).toBe("https://trioforge.test/trio/pal-mnk-ber/");
  });

  it("leaves the drag of text or a link alone, anywhere on the page", () => {
    open();
    for (const type of ["dragover", "drop"]) {
      for (const target of outside()) {
        for (const types of [["text/plain"], ["text/uri-list", "text/html"], [], ["application/x-moz-file"]]) {
          const event = dropOn(target, [], { type, types, effect: "copy" });
          expect(event.defaultPrevented, `${type} of ${types.join(", ") || "nothing"} on ${target.nodeName}`).toBe(false);
          expect(event.dataTransfer.dropEffect).toBe("copy");
        }
      }
    }
    const bare = new Event("dragover", { bubbles: true, cancelable: true }); // an event with no data transfer at all
    document.body.dispatchEvent(bare);
    expect(bare.defaultPrevented).toBe(false);
  });

  it("is still refused after the code of the section is loaded, and the section itself takes a file dropped on it", async () => {
    const { app } = open();
    wake();
    await app.whenIdle();
    expect(app.upgrade.gear).not.toBeNull();
    const elsewhere = dropOn(document.body, [dumpFile()], { type: "dragover", effect: "copy" });
    expect(elsewhere.defaultPrevented).toBe(true);
    expect(elsewhere.dataTransfer.dropEffect).toBe("none");
    expect(dropOn(document.body, [dumpFile()]).defaultPrevented).toBe(true);
    expect($("#upgrade-owned").children).toHaveLength(0);

    const over = dropOn($("#upgrade-drop"), [dumpFile()], { type: "dragover" });
    expect(over.defaultPrevented).toBe(true);
    expect(over.dataTransfer.dropEffect, "a drop on the section copies").toBe("copy");
    dropOn($("#upgrade-drop"), [dumpFile()]);
    await waitFor(() => expect(app.upgrade.gear.owned()).toHaveLength(12));
  });

  it("is left to the section before its code is loaded: a drag over it is cancelled and its drop effect is not changed", () => {
    const { app } = open();
    const over = dropOn($("#upgrade-drop"), [dumpFile()], { type: "dragover", effect: "copy" });
    expect(over.defaultPrevented).toBe(true);
    expect(over.dataTransfer.dropEffect).toBe("copy");
    expect(app.upgrade).toBeNull();
  });
});

// ---- Try again keeps the focus in the section ----------------------------------------------------------------------------------------------------------

describe("Try again of the item list", () => {
  it("keeps the focus on the button through a retry that fails again, and moves it to the heading of the section when the retry works", async () => {
    let failing = true;
    let gate = null;
    const made = site();
    const { app } = open(made, {
      serve: (url) => (failing && new URL(url).pathname === made.itemsPath ? new Response("nope", { status: 503 }) : undefined),
      delay: (path) => (path === made.itemsPath ? gate : undefined),
    });
    wake();
    await app.whenIdle();
    const failure = "Couldn't load the item list. The optimizer's data file could not be loaded (503).";
    expect(loadText()).toBe(failure);
    $("#upgrade-load button").focus();

    let release;
    gate = new Promise((resolve) => (release = resolve));
    $("#upgrade-load button").click();
    await waitFor(() => expect(loadText()).toBe("Loading the item list…"));
    expect(document.activeElement, "while it loads").toBe($("#upgrade-load button"));
    release();
    await app.whenIdle();
    expect(loadText()).toBe(failure);
    expect(document.activeElement, "after it failed again").toBe($("#upgrade-load button"));
    expect(document.activeElement.textContent).toBe("Try again");

    failing = false;
    gate = null;
    $("#upgrade-load button").click();
    await app.whenIdle();
    expect(loadText()).toBe("");
    expect($("#upgrade-load button")).toBeNull();
    expect(document.activeElement, "the button is gone").toBe($("#upgrade-h"));
  });

  it("does not take the focus from where the visitor has moved it, when the retry works", async () => {
    let failing = true;
    const made = site();
    const { app } = open(made, { serve: (url) => (failing && new URL(url).pathname === made.itemsPath ? new Response("nope", { status: 503 }) : undefined) });
    wake();
    await app.whenIdle();
    failing = false;
    $("#upgrade-load button").focus();
    $("#upgrade-load button").click();
    $("#upgrade-pick").focus(); // (the visitor went on while it loaded)
    await app.whenIdle();
    expect(document.activeElement).toBe($("#upgrade-pick"));
  });

  it("is a Reload button instead, with the focus kept, when the site was released again meanwhile", async () => {
    let failing = true;
    const made = site();
    const { app, reload } = open(made, { serve: (url) => (failing && new URL(url).pathname === made.itemsPath ? new Response("nope", { status: 503 }) : undefined) });
    wake();
    await app.whenIdle();
    $("#upgrade-load button").focus();
    failing = false;
    made.files.set(MAIN, encode({ ...made.manifestJson, data_release: "data-2026-10-15" }));
    $("#upgrade-load button").click();
    await app.whenIdle();
    expect(loadText()).toBe(SECTION_UPDATED);
    expect(document.activeElement).toBe($("#upgrade-load button"));
    expect(document.activeElement.textContent).toBe("Reload");
    document.activeElement.click();
    expect(reload).toHaveBeenCalledTimes(1);
  });
});

describe("a release of the data that is not the page's, in the section", () => {
  it("is said in the section's own line, far from the page's status, with a Reload button of its own", async () => {
    const { app, reload } = open(site({ manifest: (m) => ({ ...m, data_release: "data-2026-10-15" }) }));
    wake();
    await app.whenIdle();
    expect(loadText()).toBe(SECTION_UPDATED);
    const button = $("#upgrade-load button");
    expect(button.textContent).toBe("Reload");
    expect($("#upgrade-load").classList.contains("quiet")).toBe(false);
    button.click();
    expect(reload).toHaveBeenCalledTimes(1);
    expect($("#status button").textContent, "and the page's own notice has its button too").toBe("Reload");
  });
});

// ---- the name of a file given early --------------------------------------------------------------------------------------------------------------------

describe("the name of a file given before the code of the section is there", () => {
  const SECRET = "Zorbwick-faketown-inventory.txt";

  it("is shown nowhere (no text, no attribute), is in no address, and is in no announcement: a file dropped and one chosen while the code is fetched", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const loadUpgrade = vi.fn(async () => {
      await gate;
      return import("../pipeline/trioforge/site/static/ui/upgrade-input.js");
    });
    const { app } = open(site(), { extra: { loadUpgrade } });
    const said = recordTextOf($("#announce"));
    dropOn($("#upgrade-drop"), [new File([dumpText("site-small")], SECRET)]); // (this wakes the section, and its code is not there)
    choose($("#upgrade-file"), [new File([dumpText("site-mixed")], SECRET)]);
    expect(loadUpgrade).toHaveBeenCalledTimes(1);
    expect(document.documentElement.outerHTML, "while the code is fetched").not.toMatch(/Zorbwick|faketown/);
    release();
    await app.whenIdle();
    await waitFor(() => expect(app.upgrade.gear.owned()).toHaveLength(4)); // the file that was chosen last is the one that is read
    expect(said.length).toBeGreaterThan(0);

    const everything = [document.documentElement.outerHTML, window.location.href, document.title, JSON.stringify(window.history.state), ...said].join("\n");
    for (const part of ["Zorbwick", "faketown", SECRET]) expect(everything, part).not.toContain(part);
    for (const node of document.querySelectorAll("*")) {
      for (const attribute of node.getAttributeNames()) expect(`${attribute}=${node.getAttribute(attribute)}`).not.toMatch(/Zorbwick|faketown/);
    }
    expect($("#upgrade-file").value).toBe("");
  });
});

// ---- a start of the section that fails --------------------------------------------------------------------------------------------------------------

describe("a start of the section that fails", () => {
  const throwing = {
    initUpgrade() {
      throw new Error("start");
    },
  };
  const installsNothing = { initUpgrade: () => ({ gear: null, ready: () => Promise.resolve(null), retry() {} }) };
  const dumpFile = () => new File([dumpText("site-small")], "x.txt");
  const chunk = () => import("../pipeline/trioforge/site/static/ui/upgrade-input.js");

  it("leaves no file that can open in place of the page: a file dropped on the section is cancelled when the code fails to start, and when it starts and installs nothing", async () => {
    for (const [name, module] of [["throws", throwing], ["installs nothing", installsNothing]]) {
      const { app } = open(site(), { extra: { loadUpgrade: () => Promise.resolve(module) } });
      wake();
      await app.whenIdle();
      for (const type of ["dragover", "drop"]) {
        const event = dropOn($("#upgrade-drop"), [dumpFile()], { type, effect: "copy" });
        expect(event.defaultPrevented, `${type}, when the start ${name}`).toBe(true);
        expect(event.dataTransfer.dropEffect, "over the section the drop effect is not the page's to set").toBe("copy");
      }
    }
  });

  it("still cancels a file that is dropped outside the section, with the drop effect none, and leaves a text alone", async () => {
    const { app } = open(site(), { extra: { loadUpgrade: () => Promise.resolve(throwing) } });
    wake();
    await app.whenIdle();
    const out = dropOn(document.body, [dumpFile()], { type: "dragover", effect: "copy" });
    expect(out.defaultPrevented).toBe(true);
    expect(out.dataTransfer.dropEffect).toBe("none");
    const text = dropOn($("#upgrade-drop"), [], { type: "drop", types: ["text/plain"], effect: "copy" });
    expect(text.defaultPrevented).toBe(false);
  });

  it("keeps the page's hold on the files when the code of the section fails to start: a file chosen afterwards is handed on when the next use works, and the button offered works", async () => {
    let broken = true;
    const loadUpgrade = vi.fn(() => (broken ? Promise.resolve(throwing) : chunk()));
    const { app, reload } = open(site(), { extra: { loadUpgrade } });
    wake();
    await app.whenIdle();
    expect(app.upgrade).toBeNull();
    expect($$("#upgrade-load button").map((button) => button.textContent)).toEqual(["Reload"]);
    choose($("#upgrade-file"), [dumpFile()]); // chosen after the failure (a use of the section, which fails to start again)
    await app.whenIdle();
    dropOn($("#upgrade-drop"), [dumpFile()], { type: "drop" }); // and one dropped: the last is the one that counts
    await app.whenIdle();
    expect(loadUpgrade).toHaveBeenCalledTimes(3);
    $("#upgrade-load button").click();
    expect(reload).toHaveBeenCalledTimes(1);
    broken = false;
    $("#upgrade-tier").focus(); // the next use
    await app.whenIdle();
    await waitFor(() => expect(app.upgrade.gear.owned()).toHaveLength(12));
  });

  it("keeps the hold on the files when the item list is in and the gear input cannot be made: a file chosen afterwards is read when Try again works", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const made = site();
    const { app } = open(made, { delay: (path) => (path === made.itemsPath ? gate : undefined) });
    wake();
    await waitFor(() => expect(loadText()).toBe("Loading the item list…"));
    const feedback = $("#upgrade-feedback");
    feedback.remove(); // (the gear input cannot be made without its place for the notes)
    release();
    await app.whenIdle();
    expect(loadText()).toBe("Couldn't load the item list. Something went wrong.");
    expect(app.upgrade.gear).toBeNull();
    choose($("#upgrade-file"), [dumpFile()]); // chosen after the failure: it is kept, as before it
    $("#upgrade").append(feedback); // what was wrong is mended
    $("#upgrade-load button").click();
    await app.whenIdle();
    expect($("#upgrade-load button")).toBeNull();
    await waitFor(() => expect(app.upgrade.gear.owned()).toHaveLength(12));
  });
});

// ---- the section when the data of the site is newer than the page -----------------------------------------------------------------------------------------

describe("the section when the data of the site is newer than the page", () => {
  const newer = () => site({ manifest: (m) => ({ ...m, data_release: "data-2026-10-15" }) });
  const dumpFile = () => new File([dumpText("site-small")], "x.txt");

  it("has its controls off, the Reload button apart, and answers a file dropped or chosen afterwards with the same words, keeping nothing", async () => {
    const { app } = open(newer());
    wake();
    await app.whenIdle();
    expect(loadText()).toBe(SECTION_UPDATED);
    for (const id of ["upgrade-file", "upgrade-pick", "upgrade-tier", "upgrade-add"]) expect($(`#${id}`).disabled, id).toBe(true);
    expect($("#upgrade-load button").disabled).toBe(false);
    const said = recordTextOf($("#announce"));
    expect(dropOn($("#upgrade-drop"), [dumpFile()], { type: "dragover" }).defaultPrevented).toBe(true);
    expect(dropOn($("#upgrade-drop"), [dumpFile()]).defaultPrevented, "the browser does not open it").toBe(true);
    expect(said).toEqual([SECTION_UPDATED]);
    choose($("#upgrade-file"), [dumpFile()]);
    expect(said, "the same for a file that is chosen").toEqual([SECTION_UPDATED, SECTION_UPDATED]);
    expect($("#upgrade-file").value).toBe("");
    expect($("#upgrade-owned").children).toHaveLength(0);
    expect(app.upgrade.gear).toBeNull();
  });

  it("moves the focus to the Reload button when it was on a control that is now off, and leaves it where it is when it was elsewhere", async () => {
    const { app } = open(newer());
    $("#upgrade-pick").focus(); // (this is the use that woke the section)
    await app.whenIdle();
    expect($("#upgrade-pick").disabled).toBe(true);
    expect(document.activeElement).toBe($("#upgrade-load button"));
    expect(document.activeElement.textContent).toBe("Reload");

    const other = open(newer());
    $("#upgrade-pick").focus();
    $("#status").tabIndex = -1;
    $("#status").focus(); // the visitor went on while the manifest was read
    await other.app.whenIdle();
    expect(document.activeElement).toBe($("#status"));
  });
});
