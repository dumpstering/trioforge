// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// The page's part of a shared kit and of the gear a visitor asked the device to remember, run in jsdom against the baked page of the contract and the page code (app.js, first.js,
// trio.js): the page script takes a kit link out of the address before any other module of it runs, keeps whether it could, leaves the history alone when an in-page link is followed,
// and loads the code of the Upgrade section at once (not at the first use) when there is a kit to show or gear to restore, and only then.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";
import { encodeKit } from "../pipeline/trioforge/site/static/input/kitcode.js";
import { mountPage } from "./upgrade-helpers.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const STATIC = resolve(HERE, "../pipeline/trioforge/site/static");
const module = (name) => resolve(STATIC, name).replaceAll("\\", "/"); // (the path of a module of the page, as the mocks name it)
const CONTRACT = resolve(HERE, "../fixtures/site/contract");
const PAGE = "/trio/pal-mnk-ber/";
const GEAR_KEY = "trioforge-gear";
const KIT = encodeKit({ v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: [[0, 90001, 4], [4, 90011, 4]] });

const $ = (selector) => document.querySelector(selector);
const dataFile = (name) => JSON.parse(readFileSync(resolve(CONTRACT, `data/${name}.json`), "utf8"));
const fakeFetch = () => async (url) => {
  const name = String(url).replace("/data/pal-mnk-ber/", "").replace(".json", "");
  return { ok: true, status: 200, json: async () => structuredClone(dataFile(name)) };
};

/** The listeners for `hashchange` that the code under test put on the window: first.js adds one each time it is evaluated, and one that is left would answer the next test's navigation. */
const hashListeners = [];
beforeEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.kitFragment;
  window.history.replaceState(null, "", PAGE);
  const add = window.addEventListener.bind(window);
  vi.spyOn(window, "addEventListener").mockImplementation((type, handler, options) => {
    if (type === "hashchange") hashListeners.push(handler);
    return add(type, handler, options);
  });
});
afterEach(() => {
  for (const handler of hashListeners.splice(0)) window.removeEventListener("hashchange", handler);
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.resetModules();
  document.body.replaceChildren();
});

// ---- the page script runs the take first ------------------------------------------------------------------------------------------------------

describe("the page script", () => {
  const PAGE_MODULES = ["picker.js", "theme.js", "trio.js"];
  const appSource = readFileSync(resolve(STATIC, "app.js"), "utf8");

  it("imports first.js first, so that the take is the first code the page script runs", () => {
    const imports = [...appSource.matchAll(/^import .* from "(.+)";$/gm)].map((match) => match[1]);
    expect(imports[0]).toBe("./first.js");
    expect(imports).toEqual(expect.arrayContaining(["./picker.js", "./theme.js", "./trio.js"]));
    const first = readFileSync(resolve(STATIC, "first.js"), "utf8");
    expect(first).toMatch(/import \{ takeKitFromLocation \} from "\.\/input\/kitlocation\.js";/);
    expect(first).toMatch(/export const kit = takeKitFromLocation\(\);/);
    expect(first, "and nothing of the codec").not.toMatch(/kitcode/);
  });

  /** Run the page script (app.js) on a trio page at `address`, with the other modules of it replaced by ones that note the address as they are evaluated and as `initTrio` is called. */
  async function runPageScript(address, { state = null } = {}) {
    mountPage();
    document.body.insertAdjacentHTML("afterbegin", '<a class="skip-link" href="#main">Skip to the content</a>');
    window.history.replaceState(state, "", address);
    const seen = [];
    const note = (who) => seen.push({ who, hash: window.location.hash, state: window.history.state });
    vi.resetModules();
    const initTrio = vi.fn((env) => {
      note("initTrio");
      return env;
    });
    vi.doMock(module("picker.js"), () => (note("picker.js"), { initPicker: vi.fn() }));
    vi.doMock(module("theme.js"), () => (note("theme.js"), { bindThemeToggle: vi.fn(), getStorage: vi.fn(() => null) }));
    vi.doMock(module("trio.js"), () => (note("trio.js"), { initTrio }));
    vi.stubGlobal("fetch", vi.fn());
    await import(module("app.js"));
    return { seen, initTrio };
  }

  it("has taken a kit link out of the address before any other module of the page script is evaluated, and hands it to the page", async () => {
    const { seen, initTrio } = await runPageScript(`${PAGE}?race=OGR#k=${KIT}`);
    expect(seen.map((entry) => entry.who)).toEqual(expect.arrayContaining([...PAGE_MODULES, "initTrio"]));
    for (const entry of seen) {
      expect(entry.hash, `${entry.who} sees an address without the fragment`).toBe("");
      expect(entry.state, `${entry.who} sees the payload in the history entry`).toEqual({ k: KIT });
    }
    expect(window.location.search).toBe("?race=OGR"); // (the query stays)
    expect(initTrio).toHaveBeenCalledTimes(1);
    expect(initTrio.mock.calls[0][0].kit).toEqual({ payload: KIT, source: "fragment", cleared: true });
  });

  it("hands a page opened by a reload the payload that its history entry kept", async () => {
    const { initTrio } = await runPageScript(PAGE, { state: { k: KIT } });
    expect(initTrio.mock.calls[0][0].kit).toEqual({ payload: KIT, source: "state", cleared: false });
  });

  it("hands a page with no kit link nothing", async () => {
    const { initTrio } = await runPageScript(`${PAGE}#robust`);
    expect(initTrio.mock.calls[0][0].kit).toEqual({ payload: null, source: null, cleared: false });
    expect(window.location.hash).toBe("#robust"); // (a fragment that is not a kit's is left alone)
  });

  it("keeps whether the fragment could be cleared in one place: the data-kit-fragment attribute of the document element", async () => {
    await runPageScript(`${PAGE}#k=${KIT}`);
    expect(document.documentElement.dataset.kitFragment).toBe("cleared");
  });

  it("says that the fragment is still there when it could not be cleared", async () => {
    mountPage();
    window.history.replaceState(null, "", `${PAGE}#k=${KIT}`);
    vi.spyOn(window.history, "replaceState").mockImplementation(() => {
      throw new Error("refused");
    });
    vi.resetModules();
    vi.doMock(module("trio.js"), () => ({ initTrio: vi.fn() }));
    vi.doMock(module("picker.js"), () => ({ initPicker: vi.fn() }));
    vi.doMock(module("theme.js"), () => ({ bindThemeToggle: vi.fn(), getStorage: vi.fn(() => null) }));
    vi.stubGlobal("fetch", vi.fn());
    await import(module("app.js"));
    expect(document.documentElement.dataset.kitFragment).toBe("kept");
    expect(window.location.hash).toBe(`#k=${KIT}`);
  });

  it("writes nothing when the address had no kit link, or the kit came from the history entry of a reload", async () => {
    await runPageScript(PAGE);
    expect("kitFragment" in document.documentElement.dataset).toBe(false);
    document.body.replaceChildren();
    await runPageScript(PAGE, { state: { k: KIT } });
    expect("kitFragment" in document.documentElement.dataset).toBe(false);
  });

  it("makes no history entry of the skip link: the page scrolls to the content and moves the focus there, so that a reload still has the kit", async () => {
    await runPageScript(`${PAGE}#k=${KIT}`);
    const length = window.history.length;
    const link = $(".skip-link");
    const click = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    link.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(true);
    expect(window.location.hash).toBe("");
    expect(window.history.length).toBe(length);
    expect(window.history.state).toEqual({ k: KIT });
    expect(document.activeElement).toBe($("#main"));
  });

  it("leaves a click that opens the link somewhere else to the browser", async () => {
    await runPageScript(PAGE);
    let prevented = null;
    document.addEventListener("click", (event) => {
      prevented = event.defaultPrevented; // (what the page script decided; the browser's own follow-up is stopped here, so that jsdom has no navigation to refuse)
      event.preventDefault();
    });
    for (const init of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }]) {
      $(".skip-link").dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ...init }));
      expect(prevented, JSON.stringify(init)).toBe(false);
    }
  });
});

// ---- a second kit link opened in the page that is already showing a kit -------------------------------------------------------------------------------------
// Opening another link of this page in the same tab changes only the fragment of its address, so the browser does not load the page again: it fires `hashchange` and nothing else. The page
// script takes the kit out of the address as it did the first time (the payload goes into the history entry, the fragment goes, the attribute says whether it could) and loads the page
// again, which shows the new kit; the same link opened twice shows its kit again. A fragment that is not a kit's is nobody's business here.

describe("a second kit link opened in the page that is showing a kit", () => {
  const OTHER = encodeKit({ v: 1, trio: "pal-mnk-ber", race: "TRL", level: 50, slots: [[0, 90003, 0], [4, 90011, 2]] });

  /** First.js, run against `address`; the listener it registers on its own (which would reload the page for real) is taken off, and the module is returned with the handlers it added. */
  async function loaded(address = `${PAGE}#k=${KIT}`) {
    document.body.replaceChildren();
    window.history.replaceState(null, "", address);
    vi.resetModules();
    const before = hashListeners.length;
    const first = await import(module("first.js"));
    const own = hashListeners.splice(before);
    for (const handler of own) window.removeEventListener("hashchange", handler);
    return { first, own };
  }
  const open = async (hash) => {
    window.location.hash = hash;
    await new Promise((resolve) => setTimeout(resolve, 20)); // (jsdom fires hashchange after a task)
  };

  it("is looked for from the first import of the page script: first.js listens for hashchange", async () => {
    const { own } = await loaded();
    expect(own).toHaveLength(1);
  });

  it("is taken out of the address as the first one was, and the page is loaded again to show it", async () => {
    const { first } = await loaded();
    const reload = vi.fn();
    first.followKitLinks({ reload });
    expect(window.history.state).toEqual({ k: KIT });
    await open(`#k=${OTHER}`);
    expect(window.location.hash).toBe("");
    expect(window.history.state).toEqual({ k: OTHER });
    expect(document.documentElement.dataset.kitFragment).toBe("cleared");
    expect(reload).toHaveBeenCalledTimes(1);
    expect(window.location.pathname).toBe(PAGE);
  });

  it("keeps the query of the address, and the other keys of the history entry", async () => {
    const { first } = await loaded(`${PAGE}?race=OGR&role=tank`);
    window.history.replaceState({ mine: 1 }, "", `${PAGE}?race=OGR&role=tank`);
    const reload = vi.fn();
    first.followKitLinks({ reload });
    await open(`#k=${OTHER}`);
    expect(window.location.search).toBe("?race=OGR&role=tank");
    expect(window.history.state).toEqual({ k: OTHER });
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("is taken again when it is the same link: the page is loaded again each time, and the kit is the one in the link", async () => {
    const { first } = await loaded();
    const reload = vi.fn();
    first.followKitLinks({ reload });
    await open(`#k=${KIT}`);
    expect(window.history.state).toEqual({ k: KIT });
    expect(window.location.hash).toBe("");
    expect(reload).toHaveBeenCalledTimes(1);
    await open(`#k=${KIT}`);
    expect(reload).toHaveBeenCalledTimes(2);
    await open(`#k=${OTHER}`);
    expect(window.history.state).toEqual({ k: OTHER });
    expect(reload).toHaveBeenCalledTimes(3);
  });

  it("says that the fragment is still in the address when the browser would not rewrite it, and the page is loaded again all the same", async () => {
    const { first } = await loaded();
    const reload = vi.fn();
    first.followKitLinks({ reload });
    vi.spyOn(window.history, "replaceState").mockImplementation(() => {
      throw new Error("refused");
    });
    await open(`#k=${OTHER}`);
    expect(document.documentElement.dataset.kitFragment).toBe("kept");
    expect(window.location.hash).toBe(`#k=${OTHER}`);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("leaves a fragment that is not a kit's alone: no reload, the address and the history entry as they were", async () => {
    const { first } = await loaded();
    const reload = vi.fn();
    first.followKitLinks({ reload });
    await open("#robust");
    expect(window.location.hash).toBe("#robust");
    expect(reload).not.toHaveBeenCalled();
    expect(document.documentElement.dataset.kitFragment).toBe("cleared"); // (the page was opened with a kit fragment, and nothing has been said since)
  });

  it("stops when it is told to", async () => {
    const { first } = await loaded();
    const reload = vi.fn();
    const stop = first.followKitLinks({ reload });
    stop();
    await open(`#k=${OTHER}`);
    expect(reload).not.toHaveBeenCalled();
    expect(window.location.hash).toBe(`#k=${OTHER}`);
  });

  it("loads the page again with the window's own reload when it is given none", async () => {
    const { first } = await loaded();
    const handlers = [];
    const reload = vi.fn();
    const location = { hash: `#k=${OTHER}`, href: `https://trioforge.test${PAGE}#k=${OTHER}`, reload };
    const history = {
      state: null,
      replaceState(state, _title, url) {
        this.state = state;
        location.hash = "";
        location.href = new URL(url, location.href).href;
      },
    };
    first.followKitLinks({ window: { addEventListener: (type, handler) => handlers.push([type, handler]), removeEventListener() {}, location, history, document } });
    expect(handlers.map(([type]) => type)).toEqual(["hashchange"]);
    handlers[0][1]();
    expect(history.state).toEqual({ k: OTHER });
    expect(reload).toHaveBeenCalledTimes(1);
  });
});

// ---- the section's code is loaded at once when there is a kit or gear to restore ----------------------------------------------------------------

describe("the page loads the code of the Upgrade section at the start, and only when there is something for it", () => {
  /** The page code on the contract page with a stand-in for the section's code, which notes what it is started with. */
  function open({ kit, stored, loadUpgrade } = {}) {
    mountPage();
    if (stored !== undefined) window.localStorage.setItem(GEAR_KEY, stored);
    const starts = [];
    const initUpgrade = vi.fn((root, env) => {
      starts.push(env);
      return { ready: () => Promise.resolve(null) };
    });
    const load = loadUpgrade ?? vi.fn(() => Promise.resolve({ initUpgrade }));
    const app = initTrio({ document, window, fetch: fakeFetch(), loadUpgrade: load, ...(kit === undefined ? {} : { kit }) });
    return { app, load, initUpgrade, starts };
  }

  it("does not, for a page with no kit link and no remembered gear, and reads the device once for the check", async () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem");
    const { app, load } = open();
    await app.whenIdle();
    expect(load).not.toHaveBeenCalled();
    expect(app.upgrade).toBeNull();
    expect(getItem.mock.calls.filter(([key]) => key === GEAR_KEY)).toHaveLength(1);
    expect(getItem).toHaveBeenCalledTimes(1);
  });

  it("does, for a kit link, with the kit in what the section is started with", async () => {
    const kit = { payload: KIT, source: "fragment", cleared: true };
    const { app, load, starts } = open({ kit });
    await app.whenIdle();
    expect(load).toHaveBeenCalledTimes(1);
    expect(starts).toHaveLength(1);
    expect(starts[0].kit).toEqual(kit);
  });

  it("does, for gear that was remembered, with what was stored, the key and the storage it is kept in", async () => {
    const text = JSON.stringify({ v: 1, entries: [[90001, 4, 1]] });
    const { app, load, starts } = open({ stored: text });
    await app.whenIdle();
    expect(load).toHaveBeenCalledTimes(1);
    expect(starts[0].remember).toMatchObject({ key: GEAR_KEY, stored: text });
    expect(starts[0].remember.storage).toBe(window.localStorage);
  });

  it("loads it once, for a kit and remembered gear both, and a use of the section afterwards loads nothing more", async () => {
    const { app, load } = open({ kit: { payload: KIT, source: "state", cleared: false }, stored: "{}" });
    await app.whenIdle();
    $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    await app.whenIdle();
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("hands the section the storage and the key on a use too, with nothing stored", async () => {
    const { app, starts } = open();
    $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    await app.whenIdle();
    expect(starts[0].remember).toMatchObject({ key: GEAR_KEY, stored: null });
    expect(starts[0].kit ?? null).toBeNull();
  });

  it("goes on when the device refuses to be read: no wake, no error, and the section is told there is no storage", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { app, load, starts } = open();
    await app.whenIdle();
    expect(load).not.toHaveBeenCalled();
    $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    await app.whenIdle();
    expect(starts[0].remember.stored).toBeNull();
  });

  it("goes on when the browser will not even hand over its storage", async () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { app, load, starts } = open();
    await app.whenIdle();
    expect(load).not.toHaveBeenCalled();
    $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    await app.whenIdle();
    expect(starts[0].remember).toMatchObject({ key: GEAR_KEY, storage: null, stored: null });
  });

  it("says at the top of the page, with a Reload button, that the shared kit could not be shown when the code of the section could not be loaded", async () => {
    const { app } = open({ kit: { payload: KIT, source: "fragment", cleared: true }, loadUpgrade: () => Promise.reject(new Error("chunk")) });
    await app.whenIdle();
    expect($("#status .status-text").textContent).toBe("Couldn't load the shared kit. Reload the page to try again.");
    expect($("#status button").textContent).toBe("Reload");
    expect($("#upgrade-load .status-text").textContent).toBe("Couldn't load the Upgrade section. Reload the page to try again."); // (the section says its own, as before)
  });

  it("does not use the top of the page for the section's own failure when there is no kit", async () => {
    const { app } = open({ loadUpgrade: () => Promise.reject(new Error("chunk")) });
    $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    await app.whenIdle();
    expect($("#status .status-text")).toBeNull();
  });
});

// ---- what the section is given of the page ----------------------------------------------------------------------------------------------------

describe("what the section is given for the value of a shared kit", () => {
  async function started() {
    mountPage();
    const starts = [];
    const initUpgrade = (root, env) => {
      starts.push(env);
      return { ready: () => Promise.resolve(null) };
    };
    const app = initTrio({ document, window, fetch: fakeFetch(), loadUpgrade: () => Promise.resolve({ initUpgrade }), kit: { payload: KIT, source: "fragment", cleared: true } });
    await app.whenIdle();
    return { app, env: starts[0] };
  }
  const choose = (selector) => {
    const radio = $(selector);
    radio.checked = true;
    radio.dispatchEvent(new Event("change", { bubbles: true }));
  };

  it("is the role, the buffs and the evidence level the page shows, and no more: the weapon setup is read from the kit's hands and the haste is the model's, neither the page's", async () => {
    const { env } = await started();
    expect(env.valueView()).toEqual({ role: "balanced", buffs: "own", evidence: "strict" });
    expect(Object.keys(env.valueView()).sort()).toEqual(["buffs", "evidence", "role"]);
  });

  it("has the words for the race, for the view without its weapons, and for a weapon setup", async () => {
    const { env } = await started();
    expect(env.words.raceName("OGR")).toBe("Ogre");
    expect(env.words.raceName("TRL")).toBe("Troll");
    expect(env.words.raceName("XXX")).toBe("XXX"); // (a race the page has no name for is shown by its code)
    expect(env.words.viewText()).toBe("Balanced, strict evidence, your own buffs");
    expect(env.words.viewText()).not.toContain($('[data-f="assume-setup"]').textContent);
    expect([env.words.setupText("dw"), env.words.setupText("1h-shield"), env.words.setupText("2h")]).toEqual(["dual wield", "1H + shield", "two-hander"]);
    expect(env.words.setupText("stick"), "the page of this trio has no stat stick among its weapons: the section has the words").toBeUndefined();
    expect(env.words.setupText("club")).toBeUndefined();
  });

  it("follows the page's role, buffs and evidence switches, and tells the section when the view it shows has changed", async () => {
    const { app, env } = await started();
    const told = vi.fn();
    env.onView(told);
    choose('input[name="role"][value="tank"]');
    await app.whenIdle();
    expect(env.valueView().role).toBe("tank");
    expect(env.words.viewText()).toBe("Tank, strict evidence, your own buffs");
    expect(told).toHaveBeenCalled();
    choose('input[name="ev"][value="wiki"]');
    choose('input[name="buffs"][value="group"]');
    await app.whenIdle();
    expect(env.valueView()).toEqual({ role: "tank", buffs: "group", evidence: "wiki" });
    expect(env.words.viewText()).toBe("Tank, wiki evidence, common group buffs");
  });

  it("does not follow the weapon switch or the tier switch: the value does not depend on them", async () => {
    const { app, env } = await started();
    const before = env.valueView();
    for (const value of ["2h", "dw"]) {
      const radio = $(`input[name="setup"][value="${value}"]`);
      if (radio === null || radio.disabled) continue;
      choose(`input[name="setup"][value="${value}"]`);
      await app.whenIdle();
      expect(env.valueView()).toEqual(before);
    }
    $("#sw-tier").value = [...$("#sw-tier").options].at(-1).value;
    $("#sw-tier").dispatchEvent(new Event("change", { bubbles: true }));
    await app.whenIdle();
    expect(env.valueView()).toEqual(before);
  });
});
