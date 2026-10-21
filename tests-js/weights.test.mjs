// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// The sliders and the buff choices of the trio page as the page code runs them: the contract copy of the trio page with the page code (trio.js), the chunk it loads on the first use of
// either control (ui/weights.js), the fake site of the engine tests (the manifest and the item table), the data files of the page's own views, and a stand-in for the optimizer's
// client that the test drives. The kits and the idents are those of the invented catalog of the site fixture, with the answers Python's reference gives (fixtures/site/best-kit.json).
// Two kinds of client here: the stand-in, and the real client over a scripted worker (for the rule that the last request wins).

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createEngineClient } from "../pipeline/trioforge/site/static/engine/client.js";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";
import { makeSite, siteFetch } from "./engine-site-fixture.mjs";
import { REFERENCE } from "./best-kit-harness.mjs";
import { $, $$, mountPage } from "./upgrade-helpers.mjs";
import { addByName, fakeEngine, flush } from "./upgrade-answer-helpers.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CONTRACT = resolve(ROOT, "fixtures/site/contract");
const shardFile = (name) => JSON.parse(readFileSync(resolve(CONTRACT, `data/${name}.json`), "utf8"));
const ITEMS = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/results/items.json"), "utf8")).items;
const MAIN = "/engine-manifest.json";
const encode = (value) => new TextEncoder().encode(JSON.stringify(value));
const WEIGHTS_CHUNK = "../pipeline/trioforge/site/static/ui/weights.js";

const GROUPS = ["AC", "MANA", "ATK+HASTE", "SV", "regen"];
const LEGENDS = ["Armor class", "Mana", "Attack and haste", "Resists", "Regeneration"];
const WORKING = "Working out the kit for these settings…";
const HEADING = "Solved for your settings";
const BACK = "Back to the precomputed answer";
/** The reference's view of the Ogre, balanced, own buffs, wiki evidence, dual wield at +4, with armor class x2 (Python's answer), and the one with attack and haste x2. */
const [AC2, , ATK2] = REFERENCE.cases;

const nameOf = (ident) => {
  const key = ident.split("@")[0];
  return ITEMS.find((record) => (record.key ?? `w${record.id}`) === key).name;
};

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

// ---- the page, the site and the stand-in ------------------------------------------------------------------------------------------------------------

/** The page with its code started, a site that serves the manifest, the item table and the page's own views, and the stand-in for the optimizer. */
function open({ search = "", offline = [], consent = "granted", engine = fakeEngine(), loadWeights, site = makeSite(), tableFails = false, tableGate = null, footer = "", gate = null, hold = null, ev = "wiki" } = {}) {
  mountPage(footer);
  document.getElementById("main").dataset.ev = ev; // (the one evidence level the page is made from: the reference cases are wiki views)
  window.history.replaceState(null, "", `/trio/pal-mnk-ber/${search}`);
  site.files.set(MAIN, encode(site.manifestJson));
  const net = siteFetch(site);
  engine.consent = consent;
  const reload = vi.fn();
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push(String(url));
    const path = new URL(String(url), "https://trioforge.test").pathname;
    const view = /^\/data\/pal-mnk-ber\/(.+)\.json$/.exec(path);
    if (view === null) {
      if (tableGate !== null && path === site.itemsPath) await tableGate; // (the item list comes when the test lets it)
      return tableFails && path === site.itemsPath ? new Response("no", { status: 500 }) : net.fetchImpl(url, init);
    }
    if (hold !== null && view[1] === hold.view) await hold.until; // (this view comes when the test lets it; then it is served, or is offline)
    if (offline.includes(view[1])) throw new TypeError("Failed to fetch");
    if (gate !== null && view[1].endsWith("-group")) await gate; // (the views of the common group buffs come when the test lets them)
    return { ok: true, status: 200, json: async () => structuredClone(shardFile(view[1])) };
  };
  const chunk = loadWeights ?? vi.fn(() => import(WEIGHTS_CHUNK));
  const app = initTrio({ document, window, fetch: fetchImpl, reload, loadEngine: engine.loadEngine, loadWeights: chunk });
  return { app, engine, reload, site, net, calls, chunk };
}

const ANNOUNCED = [];
let observer = null;
beforeEach(() => {
  ANNOUNCED.length = 0;
});
/** Record every text the page's live region is given from now on. */
function listen() {
  observer?.disconnect();
  const live = $("#announce");
  observer = new MutationObserver(() => {
    if (live.textContent !== "") ANNOUNCED.push(live.textContent);
  });
  observer.observe(live, { childList: true, characterData: true, subtree: true });
}

const change = (element) => element.dispatchEvent(new Event("change", { bubbles: true }));
function choose(selector) {
  const input = $(selector);
  input.checked = true;
  change(input);
  return input;
}
const tick = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
/** A result of the best kit as the client resolves it, from a case of the reference. */
const result = (c = AC2, over = {}) => ({ kind: "scenario", mode: "best-kit", status: "optimal", proven: true, label: null, F: c.F, value: c.value, kit: [...c.kit], buffs: [...c.buffs], hasteAssumed: c.hasteAssumed, elapsedMs: 12, ...over });
const sent = (t, count) => vi.waitFor(() => expect(t.engine.runs).toHaveLength(count), { timeout: 4000, interval: 10 });
const text = (selector) => ($(selector)?.textContent ?? "").replace(/\s+/g, " ").trim();
const slider = (index, position) => `#w-${index}-${position}`;
const checkedOf = (name) => $(`input[name="${name}"]:checked`)?.value;
const positions = () => GROUPS.map((_, index) => checkedOf(`w-${index}`)).join("");
const rowNames = () => $$("#kit-body tr").map((tr) => tr.querySelector('[data-f="name"]').textContent);
/** The names a view of a data file of the page's must show, read the plain way. */
function shardNames(file, race, role, tier, setup) {
  const doc = shardFile(file);
  const row = doc.rows.find((r) => r[0] === race && r[1] === role && r[2] === tier && r[3] === setup);
  return doc.kits[row[4]].map((index) => (index < 0 ? "Leave empty" : doc.items[index][1]));
}

/** The first use of the Weights control: the details opens and the chunk comes. */
async function openWeights(t) {
  const details = $("#assume-weights");
  details.open = true;
  details.dispatchEvent(new Event("toggle"));
  await t.app.whenIdle();
  expect($$("#assume-weights input[type=radio]")).toHaveLength(15);
}
/** The reference's view on the page: the page is made from the wiki level, so a change event on the buffs it already has makes it read the wiki view; the sliders in hand. */
async function wikiView(t) {
  choose("#buffs-own");
  await t.app.whenIdle();
  await openWeights(t);
}
/** Move a slider, and let the pause pass until the request is on the client. */
async function move(t, index, position, count) {
  choose(slider(index, position));
  await sent(t, count);
}
const query = () => Object.fromEntries(new URLSearchParams(window.location.search));

// ---- the controls ------------------------------------------------------------------------------------------------------------------------------------

describe("the Buffs and Weights controls in the page as the generator writes it", () => {
  it("are switched off until the code runs, the Enchanter checkbox stays off until the group choice is on, and the Weights assumption holds no slider", async () => {
    mountPage();
    expect($("#buffs-ench").disabled && $("#buffs-raid").disabled).toBe(true);
    expect($$('#assume-weights input')).toHaveLength(0);
    document.body.innerHTML = "";
    const t = open();
    await t.app.whenIdle();
    expect($("#buffs-raid").disabled).toBe(false);
    expect($("#buffs-ench").disabled).toBe(true); // (the default is the own buffs)
    expect(text("#assume-weights summary")).toBe("Weights: role's own change");
    choose("#buffs-group");
    await t.app.whenIdle();
    expect($("#buffs-ench").disabled).toBe(false);
    choose("#buffs-raid");
    await t.app.whenIdle();
    expect($("#buffs-ench").disabled).toBe(true);
  });

  it("give the Enchanter box to the group choice at once: it can be ticked before the view of the group has loaded", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const t = open({ gate });
    await t.app.whenIdle();
    choose("#buffs-group");
    expect($("#buffs-ench").disabled, "the box is on as the group choice is made").toBe(false);
    choose("#buffs-own");
    expect($("#buffs-ench").disabled).toBe(true);
    choose("#buffs-raid");
    expect($("#buffs-ench").disabled).toBe(true);
    release();
    await t.app.whenIdle();
  });

  it("load nothing of the sliders or the solver before one of them is used: the page script holds the page, and the chunk is asked for on the first use only", async () => {
    const t = open();
    await t.app.whenIdle();
    choose("#buffs-group"); // the buffs the answers are precomputed for, and every other switch, are the page's own
    $("#sw-tier").value = "10";
    change($("#sw-tier"));
    await t.app.whenIdle();
    expect(t.chunk).not.toHaveBeenCalled();
    expect(t.calls.filter((url) => !url.startsWith("/data/pal-mnk-ber/"))).toEqual([]);
    expect(t.engine.loaded).toEqual([]);
    await openWeights(t);
    expect(t.chunk).toHaveBeenCalledTimes(1);
    expect(t.engine.loaded, "the optimizer itself is not asked for by the sliders' being drawn").toEqual([]);
    expect(t.calls.filter((url) => url.includes("engine-manifest") || url.includes("/assets/"))).toEqual([]);
    $("#assume-weights").open = false;
    $("#assume-weights").dispatchEvent(new Event("toggle"));
    $("#assume-weights").open = true;
    $("#assume-weights").dispatchEvent(new Event("toggle"));
    await t.app.whenIdle();
    expect(t.chunk).toHaveBeenCalledTimes(1);
  });

  it("are drawn when the chunk comes: a fieldset with a legend and the three positions for each slider group of the bundle, in its order, x1 chosen, and a Reset weights button", async () => {
    const t = open();
    await openWeights(t);
    const sets = $$("#assume-weights fieldset.seg");
    expect(sets.map((set) => set.querySelector("legend").textContent)).toEqual(LEGENDS);
    expect(sets.map((set) => set.dataset.group)).toEqual(GROUPS);
    for (const [index, set] of sets.entries()) {
      const radios = [...set.querySelectorAll('input[type="radio"]')];
      expect(radios.map((radio) => radio.value)).toEqual(["h", "1", "2"]);
      expect(radios.map((radio) => set.querySelector(`label[for="${radio.id}"]`).textContent)).toEqual(["x0.5", "x1", "x2"]);
      expect(radios.map((radio) => radio.checked)).toEqual([false, true, false]);
      expect(new Set(radios.map((radio) => radio.name)).size).toBe(1);
      expect(radios[0].name).toBe(`w-${index}`);
      expect(set.classList.contains("seg") && set.querySelector(".seg-items .seg-item")).toBeTruthy(); // the Role control's own classes: a segmented control
      expect(set.querySelector(".hint").textContent.length).toBeGreaterThan(5); // the group's words for what it weighs
    }
    expect($("#weights-reset").textContent).toBe("Reset weights");
    expect(text('[data-f="assume-weights"]')).toBe("role's own");
  });

  it("say, in the words of the group, what each slider weighs", async () => {
    const t = open();
    await openWeights(t);
    const hints = $$("#assume-weights fieldset.seg .hint").map((hint) => hint.textContent);
    expect(hints[0]).toMatch(/armor class/i);
    expect(hints[1]).toMatch(/mana/i);
    expect(hints[2]).toMatch(/attack/i);
    expect(hints[2]).toMatch(/haste/i);
    expect(hints[3]).toMatch(/resist/i);
    expect(hints[4]).toMatch(/regen/i);
    for (const set of $$("#assume-weights fieldset.seg")) expect(set.getAttribute("aria-describedby")).toBe(set.querySelector(".hint").id);
  });

  it("draw a slider for each group the page names and for no other: a bundle with another set of groups gets another set of sliders", async () => {
    mountPage();
    $("#main").dataset.groups = "AC SV newgroup";
    window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
    const engine = fakeEngine();
    const app = initTrio({ document, window, fetch: async () => ({ ok: true, status: 200, json: async () => structuredClone(shardFile("strict-own")) }), loadEngine: engine.loadEngine });
    const details = $("#assume-weights");
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
    await app.whenIdle();
    expect($$("#assume-weights fieldset.seg").map((set) => [set.dataset.group, set.querySelector("legend").textContent])).toEqual([
      ["AC", "Armor class"],
      ["SV", "Resists"],
      ["newgroup", "newgroup"],
    ]);
  });
});

// ---- the request ------------------------------------------------------------------------------------------------------------------------------------

describe("a request for the best kit", () => {
  it("is sent for a slider that is not at x1, a pause after the change, with the view the page shows, and nothing else of the page in it", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(0, 2));
    await tick(120);
    expect(t.engine.runs, "the page waits for the pause").toHaveLength(0);
    await sent(t, 1);
    const run = t.engine.runs[0];
    expect(run.request).toEqual({
      v: 1,
      kind: "scenario",
      trio: "pal-mnk-ber",
      level: 50,
      mode: "best-kit",
      scenario: { race: "OGR", role: "balanced", buffs: "own", evidence: "wiki", setup: "dw" },
      tier: 4,
      weights: { multipliers: { AC: 2 } },
      budgetMs: 60_000,
    });
    expect(run.replaceWaiting, "the newest request replaces the one that waits").toBe(true);
    expect(t.engine.options[0].mount.closest("section.answer")).not.toBeNull(); // the client's question and its progress go in the answer area
  });

  it("changes exactly the field of the slider that was moved: each group, each position", async () => {
    const t = open();
    await wikiView(t);
    const asked = [];
    for (const [index, group] of GROUPS.entries()) {
      for (const [position, number] of [["h", 0.5], ["2", 2]]) {
        choose(slider(index, position));
        await sent(t, asked.length + 1);
        const { request } = t.engine.runs[asked.length];
        asked.push(request);
        expect(request.weights, `${group} ${position}`).toEqual({ multipliers: { [group]: number } });
        expect(request.scenario).toEqual({ race: "OGR", role: "balanced", buffs: "own", evidence: "wiki", setup: "dw" });
        expect(request.tier).toBe(4);
        choose(slider(index, "1"));
        await t.app.whenIdle(); // (back at x1: nothing is asked)
      }
    }
    expect(t.engine.runs).toHaveLength(10);
  }, 30_000);

  it("carries every slider that is not at x1 and none that is", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(0, "2"));
    choose(slider(3, "h"));
    choose(slider(4, "2"));
    await sent(t, 1);
    expect(t.engine.runs[0].request.weights).toEqual({ multipliers: { AC: 2, SV: 0.5, regen: 2 } });
  });

  it("changes exactly the field of the switch that was changed: the race, the role, the tier, the weapons and the buffs", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    const base = structuredClone(t.engine.runs[0].request);
    const diff = (request) => {
      const found = [];
      const walk = (a, b, path) => {
        for (const key of new Set([...Object.keys(a ?? {}), ...Object.keys(b ?? {})])) {
          const left = a?.[key];
          const right = b?.[key];
          if (left !== null && typeof left === "object" && right !== null && typeof right === "object") walk(left, right, `${path}${key}.`);
          else if (JSON.stringify(left) !== JSON.stringify(right)) found.push(`${path}${key}`);
        }
      };
      walk(base, request, "");
      return found;
    };
    let count = 1;
    const ask = async (act) => {
      act();
      await sent(t, ++count);
      return diff(t.engine.runs[count - 1].request);
    };
    const race = $("#sw-race");
    const other = [...race.options].find((option) => option.value !== race.value).value;
    expect(await ask(() => { race.value = other; change(race); })).toEqual(["scenario.race"]);
    expect(await ask(() => { race.value = "OGR"; change(race); })).toEqual([]);
    expect(await ask(() => { $("#sw-tier").value = "10"; change($("#sw-tier")); })).toEqual(["tier"]);
    expect(await ask(() => { $("#sw-tier").value = "4"; change($("#sw-tier")); })).toEqual([]);
    expect(await ask(() => choose("#setup-2h"))).toEqual(["scenario.setup"]);
    expect(await ask(() => choose("#setup-dw"))).toEqual([]);
    expect(await ask(() => choose("#buffs-group"))).toEqual(["scenario.buffs"]);
    expect(await ask(() => choose("#buffs-own"))).toEqual([]);
    const role = await ask(() => choose("#role-tank"));
    expect(role).toContain("scenario.role");
    expect(role.every((field) => ["scenario.role", "scenario.setup"].includes(field)), "(the role's best weapons follow the role)").toBe(true);
  }, 30_000);

  it("carries the four buff sets: own, common group buffs, common group buffs with an Enchanter, and the full raid", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    const buffsOf = (n) => t.engine.runs[n - 1].request.scenario.buffs;
    expect(buffsOf(1)).toBe("own");
    choose("#buffs-group");
    await sent(t, 2);
    expect(buffsOf(2)).toBe("group");
    $("#buffs-ench").checked = true;
    change($("#buffs-ench"));
    await sent(t, 3);
    expect(buffsOf(3)).toBe("group+enchanter");
    choose("#buffs-raid");
    await sent(t, 4);
    expect(buffsOf(4)).toBe("raid");
    expect($("#buffs-ench").disabled).toBe(true);
    choose("#buffs-group");
    await sent(t, 5);
    expect(buffsOf(5), "(the Enchanter is still in the group)").toBe("group+enchanter");
    $("#buffs-ench").checked = false;
    change($("#buffs-ench"));
    await sent(t, 6);
    expect(buffsOf(6)).toBe("group");
    for (const run of t.engine.runs) expect(run.request.weights).toEqual({ multipliers: { AC: 2 } });
  }, 30_000);

  it("is sent for the raid and for the Enchanter at the role's own weights too, with no weights in it", async () => {
    const t = open();
    await t.app.whenIdle();
    choose("#buffs-raid");
    await sent(t, 1);
    expect(t.engine.runs[0].request.scenario.buffs).toBe("raid");
    expect(t.engine.runs[0].request).not.toHaveProperty("weights");
    choose("#buffs-group");
    await t.app.whenIdle(); // (a precomputed answer: nothing is asked)
    $("#buffs-ench").checked = true;
    change($("#buffs-ench"));
    await sent(t, 2);
    expect(t.engine.runs[1].request.scenario.buffs).toBe("group+enchanter");
    expect(t.engine.runs[1].request).not.toHaveProperty("weights");
  });

  it("is not sent for what the shards answer: x1 everywhere with the own buffs or the common group buffs, at any race, role, tier or weapons", async () => {
    const t = open();
    await t.app.whenIdle();
    choose("#buffs-group");
    $("#sw-tier").value = "10";
    change($("#sw-tier"));
    choose("#role-tank");
    await t.app.whenIdle();
    await tick(450);
    expect(t.engine.runs).toHaveLength(0);
    expect(t.chunk).not.toHaveBeenCalled();
    expect(text("#solve")).toBe("");
  });

  it("is sent a pause after the last of the changes that come quickly, and carries the last of them", async () => {
    const t = open();
    await wikiView(t);
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    choose(slider(0, "2"));
    await vi.advanceTimersByTimeAsync(200);
    choose(slider(1, "2"));
    await vi.advanceTimersByTimeAsync(200);
    choose(slider(3, "h"));
    await vi.advanceTimersByTimeAsync(299);
    expect(t.engine.runs).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    await vi.advanceTimersByTimeAsync(50);
    expect(t.engine.runs).toHaveLength(1);
    expect(t.engine.runs[0].request.weights).toEqual({ multipliers: { AC: 2, MANA: 2, SV: 0.5 } });
  });
});

// ---- the answer ------------------------------------------------------------------------------------------------------------------------------------

describe("the answer for settings that have no precomputed answer", () => {
  it("says that it is working, with Stop, while it works: the kit shown is dimmed, and nothing else of the page speaks", async () => {
    const t = open();
    await wikiView(t);
    listen();
    choose(slider(0, "2"));
    await sent(t, 1);
    expect($("#solve").hidden).toBe(false);
    expect(text("#solve")).toContain(WORKING);
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Stop"]);
    expect($("#main").classList.contains("solving")).toBe(true);
    expect($("#solve").closest("section.answer")).not.toBeNull();
    expect(ANNOUNCED, "no word is said until there is an answer").toEqual([]);
  });

  it("replaces the kit shown with the answer, headed Solved for your settings, with its F and a button back to the precomputed answer; and says it once, through the page's own live region", async () => {
    const t = open();
    await wikiView(t);
    const before = rowNames();
    listen();
    choose(slider(0, "2"));
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    expect(rowNames()).toEqual(AC2.kit.map((ident) => (ident === null ? "Leave empty" : nameOf(ident))));
    expect(rowNames()).not.toEqual(before);
    expect(text("#solve")).toContain(AC2.F);
    expect(text("#solve")).toContain("19,069");
    expect($$("#solve button").map((button) => button.textContent)).toEqual([BACK]);
    expect($("#main").classList.contains("solving")).toBe(false);
    expect($("#main").classList.contains("solved")).toBe(true);
    const tiers = $$('#kit-body [data-f="tier"]').filter((cell) => cell.textContent !== "—").map((cell) => cell.textContent);
    expect(new Set(tiers)).toEqual(new Set(["+4"]));
    expect(text("#kit-caption")).toBe("For Ogre · Balanced · +4 · Dual wield");
    expect(text('[data-f="assume-weights"]')).toBe("armor class x2");
    expect(ANNOUNCED).toEqual(["Weights armor class x2. Solved for your settings. Showing Ogre, Balanced, +4, Dual wield. Kit value 19,069."]);
    // the rows are the shard's rows: a name that is a link where the page links its items, the deity badge and the seal of the item's level
    const row = $$("#kit-body tr")[0];
    expect(row.querySelector('[data-f="arrival"]').textContent).toBe("+4");
    expect(row.querySelector('[data-f="source"]').textContent).toBe("Plane of Fear");
    expect($$("#kit-body tr")[7].querySelector('[data-f="arrival"]').textContent).toBe("+0"); // (a crafted item arrives at +0)
    expect($$("#kit-body tr")[10].querySelector('[data-f="source"]').textContent).toBe("quest: Kael Drakkel quest");
    expect($$("#kit-body tr")[3].querySelector('[data-f="name"]').textContent).toBe("Stud of the Fallen");
    // the figures that describe the shard's kit (the totals, the weapons block) are not shown for the answer, whose totals the page does not work out: the stylesheet hides them by this class
    expect($("#main").classList.contains("solved")).toBe(true);
  });

  it("says a time-limited answer for what it is: the label of the solver is in the line", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    t.engine.runs[0].finish(result(AC2, { status: "time_limit", proven: false, label: "best found, not proven optimal" }));
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    expect(text("#solve")).toContain("best found, not proven optimal");
  });

  it("is a fault in the answer area, with Try again, when the optimizer says so: the precomputed answer stays, and the page says it once", async () => {
    const t = open();
    await wikiView(t);
    const before = rowNames();
    listen();
    choose(slider(0, "2"));
    await sent(t, 1);
    t.engine.runs[0].fail(Object.assign(new Error("The optimizer stopped working."), { code: "worker-failed" }));
    await vi.waitFor(() => expect(text("#solve")).toContain("Couldn't work out the kit for these settings."));
    expect(text("#solve")).toContain("The optimizer stopped working.");
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Try again"]);
    expect(rowNames()).toEqual(before);
    expect($("#main").classList.contains("solving")).toBe(false);
    expect(ANNOUNCED).toHaveLength(1);
    expect(ANNOUNCED[0]).toContain("Couldn't work out the kit for these settings.");
    $$("#solve button")[0].click();
    await sent(t, 2);
    expect(t.engine.runs[1].request).toEqual(t.engine.runs[0].request);
    expect(text("#solve")).toContain(WORKING);
    t.engine.runs[1].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
  });

  it("is a fault, and not a kit, when the optimizer found nothing in time", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    t.engine.runs[0].finish({ ...result(), status: "time_limit", proven: false, label: "not found in time", F: null, value: null, kit: null, buffs: [] });
    await vi.waitFor(() => expect(text("#solve")).toContain("not found in time"));
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Try again"]);
    expect(text("#solve h3")).toBe("");
  });

  it("stops when Stop is pressed: the worker is stopped, the precomputed answer is shown with a line that says it is not for these settings, and Try again asks again", async () => {
    const t = open();
    await wikiView(t);
    const before = rowNames();
    choose(slider(0, "2"));
    await sent(t, 1);
    $("#solve button").click();
    await vi.waitFor(() => expect(text("#solve")).toMatch(/^Stopped\./));
    expect(t.engine.log, "the request is taken back, alone: the client is the page's, and cancel() ends what every part of the page asked for").toContain("withdraw");
    expect(t.engine.log).not.toContain("cancel");
    expect(text("#solve")).toMatch(/precomputed answer for your own buffs/);
    expect(text("#solve")).toMatch(/not for your settings/);
    expect(rowNames()).toEqual(before);
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Try again"]);
    expect($("#main").classList.contains("solving")).toBe(false);
    $("#solve button").click();
    await sent(t, 2);
    expect(text("#solve")).toContain(WORKING);
  });

  it("is declined when the visitor declines the question: the precomputed answer stays, and the line offers to load the optimizer", async () => {
    const t = open({ consent: "unknown" });
    await wikiView(t);
    const before = rowNames();
    choose(slider(0, "2"));
    await sent(t, 1);
    t.engine.runs[0].fail(Object.assign(new Error("The optimizer was not loaded: the visitor chose to keep the precomputed answers."), { code: "declined" }));
    await vi.waitFor(() => expect(text("#solve")).toMatch(/optimizer was not loaded/i));
    expect(text("#solve")).toMatch(/precomputed answer/);
    expect(rowNames()).toEqual(before);
    const [button] = $$("#solve button");
    expect(button.textContent).toBe("Load the optimizer");
    t.engine.consent = "granted";
    button.click();
    await sent(t, 2);
    expect(t.engine.client.askConsent).toHaveBeenCalledTimes(1);
    t.engine.runs[1].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
  });

  it("waits for the visitor's answer to the question before it says that it is working: there is no Stop for a request that has not begun", async () => {
    const t = open({ consent: "unknown" });
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    // the line says why nothing is happening, and there is no Stop for a request that has not begun (nor a button to a question that is not in the page yet: G10)
    expect(text("#solve .solve-text")).toBe("The optimizer is waiting for your answer to the question below.");
    expect($$("#solve button").filter((button) => !button.hidden)).toEqual([]);
    t.engine.runs[0].onProgress({ phase: "loading", loaded: 10, total: 100 });
    await vi.waitFor(() => expect(text("#solve")).toContain(WORKING));
  });

  it("goes back to the precomputed answer with the button: the sliders at x1, the buffs the answers are precomputed for, the shard's kit, no request, and the focus on the answer", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(0, "2"));
    choose("#buffs-raid");
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    listen();
    $$("#solve button")[0].click();
    await t.app.whenIdle();
    expect(positions()).toBe("11111");
    expect(checkedOf("buffs")).toBe("group");
    expect($("#buffs-ench").checked).toBe(false);
    expect(rowNames()).toEqual(shardNames("wiki-group", "OGR", "balanced", 4, "dw")); // (the shard of the common group buffs, the wiki level)
    expect($("#solve").hidden).toBe(true);
    expect($("#main").classList.contains("solved")).toBe(false);
    expect(t.engine.runs).toHaveLength(1);
    expect(document.activeElement.id).toBe("wear-h");
    expect(query()).toMatchObject({ buffs: "group" });
    expect(query()).not.toHaveProperty("w");
    expect(ANNOUNCED).toHaveLength(1);
    expect(ANNOUNCED[0]).toMatch(/^Back at the precomputed answer\. Showing .+\. Kit value [\d,]+\.$/);
  });
});

// ---- restoring the shard's kit ------------------------------------------------------------------------------------------------------------------------

describe("moving a slider and back", () => {
  it("restores the shard's kit and asks for nothing: before the pause, and after the answer came", async () => {
    const t = open();
    await wikiView(t);
    const shard = rowNames();
    // before the pause is over
    choose(slider(0, "2"));
    await tick(80);
    choose(slider(0, "1"));
    await tick(450);
    expect(t.engine.runs).toHaveLength(0);
    expect(rowNames()).toEqual(shard);
    expect(t.engine.loaded, "no optimizer, no manifest, no item table").toEqual([]);
    expect(t.calls.filter((url) => url.includes("engine-manifest") || url.includes("/assets/"))).toEqual([]);
    expect($("#solve").hidden).toBe(true);
    // after the answer is drawn
    choose(slider(0, "2"));
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    listen();
    choose(slider(0, "1"));
    await t.app.whenIdle();
    expect(rowNames()).toEqual(shard);
    expect(t.engine.runs).toHaveLength(1);
    expect($("#solve").hidden).toBe(true);
    expect(ANNOUNCED).toHaveLength(1);
    expect(ANNOUNCED[0]).toMatch(/^Weights role's own\. Showing /);
    expect(text('[data-f="assume-weights"]')).toBe("role's own");
  });

  it("is the same for Reset weights, which puts every slider back at x1 at once", async () => {
    const t = open();
    await wikiView(t);
    const shard = rowNames();
    choose(slider(0, "2"));
    choose(slider(4, "h"));
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    $("#weights-reset").focus();
    $("#weights-reset").click();
    await t.app.whenIdle();
    expect(positions()).toBe("11111");
    expect(rowNames()).toEqual(shard);
    expect(t.engine.runs).toHaveLength(1);
    expect(document.activeElement.id, "the button is still there, and still has the focus").toBe("weights-reset");
    expect(query()).not.toHaveProperty("w");
  });
});

// ---- the focus and the voice ---------------------------------------------------------------------------------------------------------------------------

describe("the focus and the live regions", () => {
  it("leaves the focus on the control that changed, through the pause, the work and the answer", async () => {
    const t = open();
    await wikiView(t);
    const radio = $(slider(2, "2"));
    radio.focus();
    choose(slider(2, "2"));
    expect(document.activeElement).toBe(radio);
    await sent(t, 1);
    expect(document.activeElement).toBe(radio);
    t.engine.runs[0].finish(result(ATK2));
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    expect(document.activeElement).toBe(radio);
    const raid = $("#buffs-raid");
    raid.focus();
    choose("#buffs-raid");
    await sent(t, 2);
    expect(document.activeElement).toBe(raid);
    t.engine.runs[1].finish(result(ATK2));
    await vi.waitFor(() => expect(t.engine.runs[1].settled).toBe(true));
    await flush();
    expect(document.activeElement).toBe(raid);
  });

  it("keeps the focus on the button while the question opens (it is the same button, and now the way to the question), and hands it to the heading of the answer when a fault has no button", async () => {
    const asked = open({ consent: "unknown" });
    await wikiView(asked);
    // the question is in the page already, asked for the Upgrade section
    const panel = document.createElement("div");
    panel.className = "engine-consent";
    panel.tabIndex = -1;
    $("#upgrade").append(panel);
    choose(slider(0, "2"));
    await vi.waitFor(() => expect(text("#solve")).toContain(WORKING));
    const stop = $("#solve button");
    stop.focus(); // (Stop, in the pause before the request is sent)
    expect(document.activeElement.textContent).toBe("Stop");
    await sent(asked, 1);
    expect(text("#solve .solve-text"), "the question is open: nothing is being worked out, and the line says what is awaited").toBe("The optimizer is waiting for your answer to the question below.");
    expect(document.activeElement, "the focus stays on the button, which is the way to the question now").toBe(stop);
    expect(document.activeElement.textContent).toBe("Go to the question");
    document.body.innerHTML = "";
    const t = open();
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    $("#solve button").focus();
    t.engine.runs[0].fail(Object.assign(new Error("This browser cannot run the optimizer."), { code: "unsupported" }));
    await vi.waitFor(() => expect(text("#solve")).toContain("This browser cannot run the optimizer."));
    expect($$("#solve button").filter((button) => !button.hidden)).toHaveLength(0); // (nothing to try again)
    expect(document.activeElement.id).toBe("wear-h");
  });

  it("adds no live region to the page, and says each answer once", async () => {
    const live = (root) => [...root.querySelectorAll('[aria-live], [role="status"], [role="alert"], [role="log"]')].map((node) => node.id);
    mountPage();
    const bakedRegions = live(document);
    document.body.innerHTML = "";
    const t = open();
    await wikiView(t);
    listen();
    choose(slider(0, "2"));
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    await tick(50);
    expect(live(document)).toEqual(bakedRegions);
    expect(ANNOUNCED).toHaveLength(1);
    choose("#buffs-raid");
    await sent(t, 2);
    t.engine.runs[1].finish(result(ATK2));
    await vi.waitFor(() => expect(ANNOUNCED).toHaveLength(2));
    expect(ANNOUNCED[1]).toMatch(/^Buffs full raid buffs\. Solved for your settings\. Showing /);
    await tick(50);
    expect(ANNOUNCED).toHaveLength(2);
  });
});

// ---- the address -----------------------------------------------------------------------------------------------------------------------------------

describe("the address", () => {
  it("carries the buff set, and the slider positions as w= with a character for each group in the bundle's order (h, 1 or 2), and leaves w out when every slider is at x1", async () => {
    const t = open();
    await wikiView(t);
    expect(query()).toEqual({ race: "OGR", role: "balanced", tier: "4", buffs: "own" });
    choose(slider(0, "2"));
    choose(slider(3, "h"));
    await sent(t, 1);
    expect(query()).toEqual({ race: "OGR", role: "balanced", tier: "4", buffs: "own", w: "211h1" });
  });

  it("writes each buff set by its name, the Enchanter's group as enchanter: a word with no plus sign to be read as a space (G4)", async () => {
    const t = open();
    await t.app.whenIdle();
    choose("#buffs-group");
    $("#buffs-ench").checked = true;
    change($("#buffs-ench"));
    await sent(t, 1);
    expect(query().buffs).toBe("enchanter");
    expect(window.location.search).toContain("buffs=enchanter");
    expect(window.location.search).not.toMatch(/\+|%2B/i);
    expect(t.engine.runs[0].request.scenario.buffs, "(the request keeps the optimizer's name for it)").toBe("group+enchanter");
    choose("#buffs-raid");
    await sent(t, 2);
    expect(query().buffs).toBe("raid");
    choose("#buffs-own");
    await t.app.whenIdle();
    expect(query().buffs).toBe("own");
    expect(query()).not.toHaveProperty("w");
  });

  it("writes nothing else of the weights, and nothing the visitor owns", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(1, "2"));
    await sent(t, 1);
    expect(Object.keys(query()).sort()).toEqual(["buffs", "race", "role", "tier", "w"]);
    // gear in the Upgrade section never goes in the address (here it is added by name)
    $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    await t.app.whenIdle();
    addByName("larkspur", "4");
    choose(slider(2, "2"));
    await vi.waitFor(() => expect(t.engine.runs.length).toBeGreaterThanOrEqual(2));
    const search = window.location.search;
    expect(Object.keys(query()).sort()).toEqual(["buffs", "race", "role", "tier", "w"]);
    expect(search).not.toMatch(/larkspur|8091|owned|lock|exclude|gear/i);
    expect(window.location.hash).toBe("");
  });

  it("is read back when the page is opened with it: the sliders, the buffs (the old spelling of the Enchanter's group among them), and a request that is sent at once", async () => {
    const t = open({ search: "?race=OGR&role=balanced&tier=4&ev=wiki&buffs=group%2Benchanter&w=2111h" });
    await sent(t, 1);
    expect(t.engine.runs[0].request).toMatchObject({
      scenario: { race: "OGR", role: "balanced", buffs: "group+enchanter", evidence: "wiki", setup: "dw" },
      tier: 4,
      weights: { multipliers: { AC: 2, regen: 0.5 } },
    });
    expect(positions()).toBe("2111h");
    expect(checkedOf("buffs")).toBe("group");
    expect($("#buffs-ench").checked).toBe(true);
    expect(text('[data-f="assume-weights"]')).toBe("armor class x2, regeneration x0.5");
    expect(text("#solve")).toContain(WORKING);
    expect(query(), "(the address is written in its own form)").toMatchObject({ buffs: "enchanter", w: "2111h" });
  });

  it.each([["enchanter"], ["group%2Benchanter"], ["group+enchanter"]])("takes buffs=%s for the Enchanter's group: the new spelling, the old one escaped, and the old one typed with a raw plus sign (which a browser reads as a space) (G4)", async (spelled) => {
    const t = open({ search: `?buffs=${spelled}&w=2111h` });
    await sent(t, 1);
    expect(t.engine.runs[0].request.scenario.buffs).toBe("group+enchanter");
    expect(checkedOf("buffs")).toBe("group");
    expect($("#buffs-ench").checked).toBe(true);
    expect(text("#status"), "(it is a buff set, not a malformed address)").toBe("");
    expect(window.location.search).toBe("?race=OGR&role=balanced&tier=4&buffs=enchanter&w=2111h");
  });

  it("goes round: what the page writes opens the same view", async () => {
    const first = open();
    await wikiView(first);
    choose("#buffs-raid");
    choose(slider(2, "h"));
    choose(slider(4, "2"));
    await sent(first, 1);
    const search = window.location.search;
    const asked = structuredClone(first.engine.runs[0].request);
    first.engine.runs[0].finish(result());
    document.body.innerHTML = "";
    const second = open({ search });
    await sent(second, 1);
    expect(second.engine.runs[0].request).toEqual(asked);
    expect(window.location.search).toBe(search);
    expect(positions()).toBe("11h12");
  });

  it("ignores a w of the wrong length or with another character, and says so once", async () => {
    for (const bad of ["2111", "211111", "21x11", "H1111", "", "2 111", "21111%"]) {
      const t = open({ search: `?w=${encodeURIComponent(bad)}` });
      await t.app.whenIdle();
      expect(t.engine.runs, bad).toHaveLength(0);
      expect(t.chunk, bad).not.toHaveBeenCalled();
      expect(text("#status"), bad).toMatch(/weights in the address/i);
      expect(text("#status"), bad).toMatch(/role's own weights are shown/i);
      expect(window.location.search, bad).toBe("?race=OGR&role=balanced&tier=4&buffs=own");
      // said once: the next change of the page clears it, and nothing says it again
      $("#sw-tier").value = "10";
      change($("#sw-tier"));
      await t.app.whenIdle();
      expect(text("#status"), bad).toBe("");
      document.body.innerHTML = "";
    }
  });

  it("ignores an address that gives w twice, whichever the two are: the first is not taken for the sliders", async () => {
    for (const search of ["?w=21111&w=11111", "?w=11111&w=21111", "?w=21111&w=21111", "?w=21111&w="]) {
      const t = open({ search });
      await t.app.whenIdle();
      expect(t.engine.runs, search).toHaveLength(0);
      expect(t.chunk, search).not.toHaveBeenCalled();
      expect(text("#status"), search).toMatch(/weights in the address/i);
      expect(window.location.search, search).toBe("?race=OGR&role=balanced&tier=4&buffs=own");
      document.body.innerHTML = "";
    }
  });

  it("says that the weights of the address were not taken and also that the weapons it names are not the role's, when both are so", async () => {
    const t = open({ search: "?role=melee&setup=1h-shield&w=zz" });
    await t.app.whenIdle();
    expect(text("#status")).toMatch(/1H \+ shield is not available for this role/i);
    expect(text("#status")).toMatch(/weights in the address do not fit the sliders of this page/i);
    expect(window.location.search).not.toContain("w=");
  });

  it("ignores a bad w and still reads the rest of the address", async () => {
    const t = open({ search: "?tier=10&ev=wiki&w=zz" });
    await t.app.whenIdle();
    expect($("#sw-tier").value).toBe("10");
    expect(text("#status")).toMatch(/weights in the address/i);
    expect(query()).toEqual({ race: "OGR", role: "balanced", tier: "10", buffs: "own" });
    expect(t.engine.runs).toHaveLength(0);
  });

  it("reads a buff set that is none of the four as no buff set: the own buffs are shown, the rest of the address is read as it is, and the address is written in its own form", async () => {
    const t = open({ search: "?buffs=group+enchanters&w=2111h" });
    await sent(t, 1);
    expect(t.engine.runs[0].request.scenario.buffs).toBe("own");
    expect(t.engine.runs[0].request.weights).toEqual({ multipliers: { AC: 2, regen: 0.5 } });
    expect(checkedOf("buffs")).toBe("own");
    expect(positions()).toBe("2111h");
    expect(window.location.search).toBe("?race=OGR&role=balanced&tier=4&buffs=own&w=2111h");
  });

  it("takes w=11111 for the role's own weights: no request", async () => {
    const t = open({ search: "?w=11111" });
    await t.app.whenIdle();
    await tick(450);
    expect(t.engine.runs).toHaveLength(0);
    expect(t.chunk).not.toHaveBeenCalled();
    expect(text("#status")).toBe("");
  });

  it("solves the buff set of an address after consent, and shows the precomputed answer and offers the solve if consent is not given", async () => {
    const asked = open({ search: "?buffs=raid", consent: "unknown" });
    await sent(asked, 1);
    expect(asked.engine.runs[0].request.scenario.buffs).toBe("raid");
    expect(asked.engine.runs[0].request).not.toHaveProperty("weights");
    asked.engine.runs[0].fail(Object.assign(new Error("declined"), { code: "declined" }));
    await vi.waitFor(() => expect(text("#solve")).toMatch(/optimizer was not loaded/i));
    expect(rowNames()).toHaveLength(22);
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Load the optimizer"]);
    expect(checkedOf("buffs")).toBe("raid");
  });

  it("keeps the fragment of the address, which is the kit link's", async () => {
    const t = open();
    await wikiView(t);
    window.history.replaceState(null, "", `${window.location.pathname}#robust`);
    choose(slider(0, "2"));
    await sent(t, 1);
    expect(window.location.hash).toBe("#robust");
    expect(query().w).toBe("2" + "1111");
  });
});

// ---- the report link and the summary lines --------------------------------------------------------------------------------------------------------------

describe("the lines that say what is assumed", () => {
  it("say the sliders that are not at x1 in the Weights line and in the line of the switches, and the full raid and the Enchanter in the Buffs line", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(3, "h"));
    choose(slider(0, "2"));
    await sent(t, 1);
    expect(text("#assume-weights summary")).toBe("Weights: armor class x2, resists x0.5 change");
    expect(text('[data-f="s-assumes"]')).toBe("dual wield, your own buffs, armor class x2, resists x0.5");
    choose("#buffs-group");
    $("#buffs-ench").checked = true;
    change($("#buffs-ench"));
    await sent(t, 2);
    expect(text('[data-f="assume-buffs"]')).toBe("common group buffs and an Enchanter");
    choose("#buffs-raid");
    await sent(t, 3);
    expect(text('[data-f="assume-buffs"]')).toBe("full raid buffs");
    $("#weights-reset").click();
    await vi.waitFor(() => expect(text('[data-f="assume-weights"]')).toBe("role's own"));
    expect(text('[data-f="s-assumes"]')).toBe("dual wield, full raid buffs");
  });

  it("name, in the link that reports a problem, the answer the table shows, so that a report can be looked at as it was seen: the precomputed answer until the answer for the settings is drawn, then the settings (G7)", async () => {
    const report = `https://example.org/issues/new?page=${encodeURIComponent("https://trioforge.test/trio/pal-mnk-ber/?race=OGR")}`;
    const t = open({ footer: `<p><a id="report-link" href="${report}">Report a problem</a></p>` });
    await wikiView(t);
    const shown = () => Object.fromEntries(new URL(new URL($("#report-link").getAttribute("href")).searchParams.get("page")).searchParams);
    expect(shown()).toMatchObject({ race: "OGR", buffs: "own" });
    expect(shown()).not.toHaveProperty("w");
    choose(slider(1, "2"));
    await sent(t, 1);
    expect(shown(), "the table still shows the precomputed answer").toMatchObject({ race: "OGR", buffs: "own" });
    expect(shown()).not.toHaveProperty("w");
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    expect(shown(), "the answer for the sliders is shown").toMatchObject({ race: "OGR", buffs: "own", w: "12111" });
    choose("#buffs-raid");
    await sent(t, 2);
    expect(shown().buffs, "the table shows the common group buffs' answer while the raid is worked out").toBe("group");
    expect(shown()).not.toHaveProperty("w");
    t.engine.runs[1].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    expect(shown()).toMatchObject({ buffs: "raid", w: "12111" });
    $$("#solve button")[0].click(); // Back to the precomputed answer
    await t.app.whenIdle();
    expect(shown().buffs).toBe("group");
    expect(shown()).not.toHaveProperty("w");
  });

  it("write the Enchanter's group in the link that reports a problem as the address does (G4)", async () => {
    const report = `https://example.org/issues/new?page=${encodeURIComponent("https://trioforge.test/trio/pal-mnk-ber/?race=OGR")}`;
    const t = open({ footer: `<p><a id="report-link" href="${report}">Report a problem</a></p>` });
    await t.app.whenIdle();
    choose("#buffs-group");
    $("#buffs-ench").checked = true;
    change($("#buffs-ench"));
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    const page = new URL($("#report-link").getAttribute("href")).searchParams.get("page");
    expect(new URL(page).searchParams.get("buffs")).toBe("enchanter");
    expect(page).not.toMatch(/\+|%2B/i);
  });
});

// ---- the Upgrade section -------------------------------------------------------------------------------------------------------------------------------

/** The paths the Upgrade section has asked the client for, in order. */
const paths = (t) => t.engine.runs.filter((run) => run.request.mode === "farm-path");
/** The first use of the section: its code and the item list come, a piece of gear is added, and the path for it is asked for. */
async function withGear(t) {
  $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
  await t.app.whenIdle();
  addByName("larkspur", "4");
  await vi.waitFor(() => expect(paths(t)).toHaveLength(1), { timeout: 4000 });
}

describe("the Upgrade section", () => {  it("is given the weights of the view: the path it asks for carries the sliders that are not at x1, a slider moved makes a new path, and every slider at x1 a path with none", async () => {
    const t = open();
    await wikiView(t);
    await withGear(t);
    expect(paths(t)[0].request).not.toHaveProperty("weights");
    choose(slider(0, "2"));
    choose(slider(3, "h"));
    await vi.waitFor(() => expect(paths(t)).toHaveLength(2), { timeout: 4000 });
    expect(paths(t)[1].request.weights).toEqual({ multipliers: { AC: 2, SV: 0.5 } });
    choose(slider(4, "2"));
    await vi.waitFor(() => expect(paths(t)).toHaveLength(3), { timeout: 4000 });
    expect(paths(t)[2].request.weights).toEqual({ multipliers: { AC: 2, SV: 0.5, regen: 2 } });
    $("#weights-reset").click();
    await vi.waitFor(() => expect(paths(t)).toHaveLength(4), { timeout: 4000 });
    expect(paths(t)[3].request).not.toHaveProperty("weights");
    // the weights it carries are the ones the best kit was asked for: one view, one set of sliders
    for (const run of t.engine.runs.filter((one) => one.request.mode === "best-kit")) expect(run.request.weights).toBeDefined();
  }, 30_000);

  it("has no line of its own about the weights: its answers are for the sliders now", async () => {
    const t = open();
    await wikiView(t);
    await withGear(t);
    choose(slider(0, "2"));
    await vi.waitFor(() => expect(paths(t)).toHaveLength(2), { timeout: 4000 });
    expect($("#upgrade-weights")).toBeNull();
    expect(text("#upgrade")).not.toMatch(/role's own weights/);
  }, 30_000);

  it("is given the buff set of the view, the full raid and the Enchanter's included, and no weights while every slider is at x1", async () => {
    const t = open();
    await t.app.whenIdle();
    await withGear(t);
    choose("#buffs-raid");
    await vi.waitFor(() => expect(paths(t).some((run) => run.request.scenario.buffs === "raid")).toBe(true), { timeout: 4000 });
    choose("#buffs-group");
    $("#buffs-ench").checked = true;
    change($("#buffs-ench"));
    await vi.waitFor(() => expect(paths(t).some((run) => run.request.scenario.buffs === "group+enchanter")).toBe(true), { timeout: 4000 });
    for (const run of paths(t)) expect(run.request).not.toHaveProperty("weights");
  }, 30_000);
});

// ---- the code that does not come ------------------------------------------------------------------------------------------------------------------------

describe("when the code of the sliders cannot be had", () => {
  it("says so with a Reload button, keeps the page as it was, and tries again at the next use", async () => {
    let fail = true;
    const loadWeights = vi.fn(() => (fail ? Promise.reject(new Error("chunk")) : import(WEIGHTS_CHUNK)));
    const t = open({ loadWeights });
    await t.app.whenIdle();
    const before = rowNames();
    const details = $("#assume-weights");
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
    await t.app.whenIdle();
    expect(text("#status")).toMatch(/couldn.t load the weights/i);
    expect($$("#status button").map((button) => button.textContent)).toEqual(["Reload"]);
    $("#status button").click();
    expect(t.reload).toHaveBeenCalledTimes(1);
    expect(rowNames()).toEqual(before);
    fail = false;
    details.open = false;
    details.dispatchEvent(new Event("toggle"));
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
    await t.app.whenIdle();
    expect(loadWeights).toHaveBeenCalledTimes(2);
    expect($$("#assume-weights input[type=radio]")).toHaveLength(15);
  });

  it("keeps the raid choice and shows the precomputed answer, with the line, when the code for it cannot be had", async () => {
    const loadWeights = vi.fn(() => Promise.reject(new Error("chunk")));
    const t = open({ loadWeights });
    await t.app.whenIdle();
    choose("#buffs-raid");
    await t.app.whenIdle();
    expect(text("#status")).toMatch(/couldn.t load the weights/i);
    expect(checkedOf("buffs")).toBe("raid");
    expect(rowNames()).toHaveLength(22);
    // the line says what the table shows: the precomputed answer for the common group buffs, not the full raid the choice says
    expect(text("#status .status-text")).toBe("Couldn't load the weights. Reload the page to try again. The table shows the precomputed answer for common group buffs and the role's own weights, not for your settings.");
    expect(rowNames()).toEqual(shardNames("strict-group", "OGR", "balanced", 4, "dw"));
  });

  it("says nothing of a table that is not for the settings when the settings are the shards' own", async () => {
    const loadWeights = vi.fn(() => Promise.reject(new Error("chunk")));
    const t = open({ loadWeights });
    await t.app.whenIdle();
    const details = $("#assume-weights");
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
    await t.app.whenIdle();
    expect(text("#status .status-text")).toBe("Couldn't load the weights. Reload the page to try again.");
  });
});

// ---- the data the answer is drawn from -------------------------------------------------------------------------------------------------------------------

describe("the item list the answer is drawn from", () => {
  it("is read by the path, the size and the checksum of the manifest, once, and the optimizer's client is the one the manifest names", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    expect(t.engine.loaded).toEqual(["https://trioforge.test/assets/engine/client-AAAAAAAA.js"]);
    const table = t.net.asked.filter((url) => url.includes("/assets/engine/data/"));
    expect(table.map((url) => new URL(url).pathname)).toEqual([t.site.itemsPath]);
    choose(slider(0, "h"));
    await sent(t, 2);
    t.engine.runs[1].finish(result());
    await vi.waitFor(() => expect(t.engine.runs[1].settled).toBe(true));
    await flush();
    expect(t.net.asked.filter((url) => url.includes("/assets/engine/data/"))).toHaveLength(1);
    expect(t.net.asked.filter((url) => url.includes("engine-manifest"))).toHaveLength(1);
    expect(t.engine.options).toHaveLength(1);
  });

  it("is a fault with Try again when it cannot be had, and the answer is drawn when it can", async () => {
    const t = open({ tableFails: true });
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve")).toMatch(/couldn.t load the item list/i));
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Try again"]);
    expect(text("#solve h3")).toBe("");
  });

  it("is not trusted when the manifest names a release that is not the page's: the page says that the data was updated", async () => {
    const site = makeSite();
    site.manifestJson.data_release = "data-2099-01-01";
    const t = open({ site });
    await wikiView(t);
    choose(slider(0, "2"));
    await vi.waitFor(() => expect(text("#status")).toMatch(/data updated, reload the page/i));
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Reload"]);
    expect(t.engine.runs).toHaveLength(0);
  });
});

// ---- the last request wins ---------------------------------------------------------------------------------------------------------------------------

/** The real client over a worker that the test drives: `sent` are the requests it was given, and `reply` says what the worker says. */
class ScriptedWorker {
  constructor(site) {
    this.site = site;
    this.sent = [];
    this.terminated = false;
    this.onmessage = null;
    this.onerror = null;
    this.onmessageerror = null;
  }

  reply(message) {
    queueMicrotask(() => this.terminated || this.onmessage?.({ data: structuredClone(message) }));
  }

  postMessage(data) {
    this.sent.push(structuredClone(data));
    if (data.type === "init") this.reply({ v: 1, type: "ready", highs: "1.15.1", wasm: this.site.manifest.wasm.sha256 });
    if (data.type === "ping") this.reply({ v: 1, type: "pong" });
  }

  terminate() {
    this.terminated = true;
  }
}

describe("the last request wins", () => {
  /** The page over the real client, a worker that says nothing until the test does, and a record of what became of every request. */
  function openReal({ search = "", panel = false } = {}) {
    const site = makeSite();
    const workers = [];
    const outcomes = [];
    const ask = vi.fn(async () => true);
    let real = null;
    const loadEngine = async () => ({
      getEngineClient(options) {
        real ??= createEngineClient({
          window,
          document,
          mount: options.mount,
          fetch: async (url) => ({ ok: true, status: 200, text: async () => (String(url).startsWith("/engine-trios/") ? JSON.stringify(site.trioJson["pal-mnk-ber"]) : JSON.stringify(site.manifestJson)) }),
          createWorker: () => {
            const worker = new ScriptedWorker(site);
            workers.push(worker);
            return worker;
          },
          ...(panel ? {} : { consent: { ask } }), // (the client's own panel and its buttons, or the stand-in that says yes)
          trustedTypes: null,
        });
        return new Proxy(real, {
          get(target, name) {
            if (name !== "runScenario") return target[name];
            return (request, callbacks) => {
              const promise = target.runScenario(request, callbacks);
              const outcome = { state: "pending", request };
              promise.then(
                (value) => Object.assign(outcome, { state: "resolved", value }),
                (error) => Object.assign(outcome, { state: "rejected", error }),
              );
              outcomes.push(outcome);
              return promise;
            };
          },
        });
      },
    });
    const t = open({ search, site, engine: { loadEngine, consent: "granted", runs: [], loaded: [], options: [], log: [] } });
    return { ...t, workers, outcomes, ask, real: () => real };
  }
  const solvesOf = (workers) => workers.flatMap((worker) => worker.sent.filter((message) => message.type === "solve"));
  const answerFor = (id, c) => ({ v: 1, type: "result", id, kind: "scenario", mode: "best-kit", status: "optimal", proven: true, label: null, F: c.F, value: c.value, kit: [...c.kit], buffs: [...c.buffs], hasteAssumed: c.hasteAssumed, elapsedMs: 5 });

  it("draws only the answer to the last of ten changes: the running request's answer is stale and never drawn, eight are cancelled, one worker", async () => {
    const t = openReal();
    await t.app.whenIdle();
    await openWeights(t);
    listen();
    const positionsOf = ["2", "h", "2", "h", "2", "h", "2", "h", "2", "h"]; // ten changes of the armor class slider, a pause apart
    choose(slider(0, positionsOf[0]));
    await vi.waitFor(() => expect(solvesOf(t.workers)).toHaveLength(1), { timeout: 4000 }); // the first is running
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    for (const position of positionsOf.slice(1)) {
      choose(slider(0, position));
      await vi.advanceTimersByTimeAsync(310); // (the pause is over: the page sends it)
    }
    vi.useRealTimers();
    expect(t.outcomes).toHaveLength(10);
    expect(t.outcomes.slice(1, 9).map((outcome) => [outcome.state, outcome.error?.code])).toEqual(Array(8).fill(["rejected", "cancelled"]));
    expect(t.outcomes[0].state).toBe("pending");
    expect(t.outcomes[9].state).toBe("pending");
    // the running request's answer comes: it is for settings that are no longer shown, so it is not drawn and not said
    const [first] = solvesOf(t.workers);
    t.workers[0].reply(answerFor(first.id, ATK2));
    await vi.waitFor(() => expect(t.outcomes[0].state).toBe("resolved"));
    await vi.waitFor(() => expect(solvesOf(t.workers)).toHaveLength(2), { timeout: 4000 });
    expect(text("#solve h3"), "the answer of the running request was not drawn").toBe("");
    expect(ANNOUNCED).toEqual([]);
    expect($("#main").classList.contains("solved")).toBe(false);
    // the last request's answer is drawn and said, once
    const last = solvesOf(t.workers)[1];
    expect(last.request.weights).toEqual({ multipliers: { AC: 0.5 } });
    t.workers[0].reply(answerFor(last.id, AC2));
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    expect(rowNames()).toEqual(AC2.kit.map((ident) => (ident === null ? "Leave empty" : nameOf(ident))));
    expect(ANNOUNCED).toHaveLength(1);
    expect(t.workers).toHaveLength(1);
    expect(t.ask).toHaveBeenCalledTimes(1);
    expect(t.net.asked.filter((url) => url.includes("/assets/engine/data/"))).toHaveLength(1); // (the item table, once, for the page; the worker here is the script)
  }, 60_000);

  it("never draws the answer of a request after the page went back to a precomputed answer", async () => {
    const t = openReal();
    await t.app.whenIdle();
    await openWeights(t);
    choose(slider(0, "2"));
    await vi.waitFor(() => expect(solvesOf(t.workers)).toHaveLength(1), { timeout: 4000 });
    listen();
    choose(slider(0, "1"));
    await t.app.whenIdle();
    const shard = rowNames();
    t.workers[0].reply(answerFor(solvesOf(t.workers)[0].id, AC2));
    await vi.waitFor(() => expect(t.outcomes[0].state).toBe("resolved"));
    await tick(60);
    expect(rowNames()).toEqual(shard);
    expect($("#solve").hidden).toBe(true);
    expect(ANNOUNCED.filter((said) => said.includes("Solved"))).toEqual([]);
  });

  it("shows no fault for a request that is no longer wanted", async () => {
    const t = openReal();
    await t.app.whenIdle();
    await openWeights(t);
    choose(slider(0, "2"));
    await vi.waitFor(() => expect(solvesOf(t.workers)).toHaveLength(1), { timeout: 4000 });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    choose(slider(1, "2"));
    await vi.advanceTimersByTimeAsync(310);
    vi.useRealTimers();
    expect(t.outcomes).toHaveLength(2);
    t.workers[0].reply({ v: 1, type: "error", id: solvesOf(t.workers)[0].id, code: "bad-request", message: "Nothing fits." });
    await vi.waitFor(() => expect(t.outcomes[0].state).toBe("rejected"));
    await tick(60);
    expect(text("#solve")).not.toMatch(/couldn.t/i);
    expect(text("#solve")).toContain(WORKING);
  });

  it("draws nothing for the request that the Cancel of the loading panel ended, and a late word from the worker that was dropped changes nothing", async () => {
    window.sessionStorage.clear(); // (the yes of an earlier test of this file is not the visitor's here)
    const t = openReal({ panel: true });
    await t.app.whenIdle();
    await openWeights(t);
    listen();
    choose(slider(0, "2"));
    await vi.waitFor(() => expect($('.engine-consent [data-action="accept"]')).not.toBeNull(), { timeout: 5000 });
    $('.engine-consent [data-action="accept"]').click();
    await vi.waitFor(() => expect(solvesOf(t.workers)).toHaveLength(1), { timeout: 5000 });
    const shard = rowNames();
    $('.engine-consent [data-action="cancel"]').click(); // the Cancel of the panel ends everything
    await vi.waitFor(() => expect(t.outcomes[0].state).toBe("rejected"));
    expect(t.outcomes[0].error).toMatchObject({ code: "cancelled", byVisitor: true });
    await tick(80);
    expect(text("#solve")).toMatch(/The request was cancelled/);
    expect(rowNames()).toEqual(shard);
    t.workers[0].reply(answerFor(solvesOf(t.workers)[0].id, AC2)); // (a worker that was dropped does not speak)
    await tick(80);
    expect(rowNames()).toEqual(shard);
    expect($("#main").classList.contains("solved")).toBe(false);
    expect(ANNOUNCED.filter((said) => said.includes("Solved"))).toEqual([]);
  }, 30_000);

  it("keeps the path of the Upgrade section that the worker has when Stop is pressed on the request of the sliders that waits behind it: the worker is not stopped", async () => {
    const t = openReal();
    await t.app.whenIdle();
    await openWeights(t);
    $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    await t.app.whenIdle();
    addByName("larkspur", "4");
    await vi.waitFor(() => expect(solvesOf(t.workers).some((message) => message.request.mode === "farm-path")).toBe(true), { timeout: 8000 });
    choose(slider(0, "2"));
    await vi.waitFor(() => expect(t.outcomes.some((outcome) => outcome.request.mode === "best-kit")).toBe(true), { timeout: 4000 });
    await tick(30);
    expect(text("#solve")).toContain(WORKING);
    $("#solve button").click();
    const best = t.outcomes.find((outcome) => outcome.request.mode === "best-kit");
    await vi.waitFor(() => expect(best.state).toBe("rejected"));
    expect(best.error.code).toBe("cancelled");
    const path = t.outcomes.find((outcome) => outcome.request.mode === "farm-path");
    await tick(60);
    expect(path.state, "the path of the Upgrade section is still on the worker").toBe("pending");
    expect(t.workers[0].terminated).toBe(false);
    expect(t.workers).toHaveLength(1);
    expect(text("#upgrade-fault")).toBe("");
  }, 30_000);
});

// ---- Stop, Try again and the one client of the page ---------------------------------------------------------------------------------------------------

describe("the sliders and the Upgrade section on the one client", () => {
  const cancelled = (over = {}) => Object.assign(new Error("The request was cancelled."), { code: "cancelled", ...over });
  const bestKits = (t) => t.engine.runs.filter((run) => run.request.mode === "best-kit");

  it("takes back the request of the sliders alone when Stop is pressed: the path of the Upgrade section that the worker has goes on, and no worker is stopped", async () => {
    const engine = fakeEngine();
    engine.serial = true; // (the client works at one request at a time)
    const t = open({ engine });
    await wikiView(t);
    await withGear(t); // the path: the worker has it
    expect(paths(t)[0].sent).toBe(true);
    choose(slider(0, "2"));
    await sent(t, 2); // the best kit of the sliders waits behind it
    expect(bestKits(t)[0].sent).toBe(false);
    expect(text("#solve")).toContain(WORKING);
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Stop"]);
    $("#solve button").click();
    await vi.waitFor(() => expect(text("#solve")).toMatch(/^Stopped\./));
    expect(t.engine.log).toContain("withdraw");
    expect(t.engine.log, "cancel() ends what every part of the page asked for").not.toContain("cancel");
    expect(bestKits(t)[0].withdrawn).toBe(true);
    expect(paths(t)[0].settled, "the path of the Upgrade section goes on").toBe(false);
    await tick(60);
    expect(text("#upgrade-fault"), "and says no fault").toBe("");
  }, 30_000);

  it("does not end the request of the sliders when the Upgrade section sends a new path while the question is open: the sliders do not say that the optimizer was not loaded", async () => {
    const engine = fakeEngine();
    const t = open({ engine, consent: "unknown" });
    await wikiView(t);
    await withGear(t); // the path waits for the question
    choose(slider(0, "2"));
    await sent(t, 2); // so does the best kit
    addByName("fenwick greaves", "4"); // a change of the gear: the section sends a new path
    await sent(t, 3);
    expect(t.engine.log).not.toContain("cancel");
    expect(t.engine.runs[0].withdrawn, "the section took its own path back").toBe(true);
    expect(t.engine.runs[1].settled, "the request of the sliders still waits for the question").toBe(false);
    await tick(80);
    expect(text("#solve")).not.toMatch(/not loaded/i);
    expect($$("#solve button").map((button) => button.textContent)).not.toContain("Load the optimizer");
  }, 30_000);

  it("asks again, once, for a request that comes back cancelled when the sliders did not take it back: another part of the page cancelled it", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    t.engine.runs[0].fail(cancelled());
    await sent(t, 2);
    expect(t.engine.runs[1].request).toEqual(t.engine.runs[0].request);
    expect(text("#solve"), "no fault is told: the answer is asked for again").toContain(WORKING);
    t.engine.runs[1].fail(cancelled());
    await vi.waitFor(() => expect(text("#solve")).toMatch(/The request was cancelled\./));
    await tick(60);
    expect(t.engine.runs, "and not for ever").toHaveLength(2);
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Try again"]);
    $("#solve button").click();
    await sent(t, 3);
  });

  it("does not ask again for a request that the visitor cancelled with the Cancel button of the panel", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    t.engine.runs[0].fail(cancelled({ byVisitor: true }));
    await vi.waitFor(() => expect(text("#solve")).toMatch(/The request was cancelled\./));
    await tick(60);
    expect(t.engine.runs).toHaveLength(1);
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Try again"]);
  });

  it("takes back the request that waits when the page goes back to a precomputed answer, and leaves the one the worker has to end: x2 running, x0.5 waiting, x1", async () => {
    const engine = fakeEngine();
    engine.serial = true;
    const t = open({ engine });
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1); // the worker has it
    choose(slider(0, "h"));
    await sent(t, 2); // x0.5 waits behind it
    expect(t.engine.runs[1].sent).toBe(false);
    choose(slider(0, "1")); // every slider at x1: a shard answers
    await t.app.whenIdle();
    expect(t.engine.runs[1].withdrawn, "nobody wants the x0.5 answer: it is not solved").toBe(true);
    expect(t.engine.runs[0].withdrawn, "the one the worker has is left to end (a worker costs a start)").toBe(false);
    expect(t.engine.log).not.toContain("cancel");
    expect($("#solve").hidden).toBe(true);
  }, 30_000);

  it("takes back the request that waits for the question when the page goes back to a precomputed answer", async () => {
    const engine = fakeEngine();
    const t = open({ engine, consent: "unknown" });
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1); // it waits for the visitor's answer to the question
    choose(slider(0, "1"));
    await t.app.whenIdle();
    expect(t.engine.runs[0].withdrawn, "a yes to the question loads nothing for it").toBe(true);
  });
});

describe("Stop and Try again", () => {
  it("is not undone by the code of the optimizer that comes after Stop: the line stays and nothing is sent", async () => {
    const engine = fakeEngine();
    let arrive;
    const real = engine.loadEngine;
    engine.loadEngine = (url) => new Promise((resolve) => (arrive = () => resolve(real(url))));
    const t = open({ engine });
    await wikiView(t);
    listen();
    choose(slider(0, "2"));
    await vi.waitFor(() => expect(arrive).toBeDefined(), { timeout: 4000 }); // the pause is over and the code of the optimizer is on its way
    expect(text("#solve")).toContain(WORKING);
    $("#solve button").click();
    expect(text("#solve")).toMatch(/^Stopped\./);
    arrive();
    await tick(100);
    expect(text("#solve"), "not back at Working").toMatch(/^Stopped\./);
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Try again"]);
    expect($("#main").classList.contains("solving")).toBe(false);
    expect(t.engine.runs, "the request is not sent").toHaveLength(0);
    expect(ANNOUNCED).toEqual([]);
  }, 30_000);

  it("asks once when Try again is pressed before the code of the optimizer has come: one request, one answer said", async () => {
    const engine = fakeEngine();
    let arrive;
    const real = engine.loadEngine;
    engine.loadEngine = (url) => new Promise((resolve) => (arrive = () => resolve(real(url))));
    const t = open({ engine });
    await wikiView(t);
    listen();
    choose(slider(0, "2"));
    await vi.waitFor(() => expect(arrive).toBeDefined(), { timeout: 4000 });
    $("#solve button").click(); // Stop
    $("#solve button").click(); // Try again
    expect(text("#solve")).toContain(WORKING);
    arrive();
    await sent(t, 1);
    await tick(100);
    expect(t.engine.runs, "two attempts are one request").toHaveLength(1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    await tick(60);
    expect(ANNOUNCED).toHaveLength(1);
  }, 30_000);

  it("is not undone by the item list that comes after Stop: the answer is not drawn or said", async () => {
    let release;
    const tableGate = new Promise((resolve) => (release = resolve));
    const t = open({ tableGate });
    await wikiView(t);
    listen();
    choose(slider(0, "2"));
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await tick(40); // the answer is there, and the item list it is drawn from is on its way
    expect(text("#solve")).toContain(WORKING);
    $("#solve button").click(); // Stop
    expect(text("#solve")).toMatch(/^Stopped\./);
    release();
    await tick(120);
    expect(text("#solve"), "the answer is not drawn after Stop").toMatch(/^Stopped\./);
    expect($("#main").classList.contains("solved")).toBe(false);
    expect(ANNOUNCED).toEqual([]);
  }, 30_000);
});

describe("an answer for a view the page is leaving", () => {
  it("is neither drawn nor said while the next view loads, and the answer for the next view is: a slider at x2 on the own buffs, then the common group buffs", async () => {
    let release;
    const until = new Promise((resolve) => (release = resolve));
    const t = open({ hold: { view: "wiki-group", until } });
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    const wikiRows = rowNames();
    listen();
    choose("#buffs-group"); // the data of the group view is on its way
    await tick(30);
    t.engine.runs[0].finish(result()); // the answer for the own-buffs view comes meanwhile
    await tick(150);
    expect($("#main").classList.contains("solved"), "not drawn under the group buffs").toBe(false);
    expect(rowNames()).toEqual(wikiRows);
    expect(ANNOUNCED, "and not said").toEqual([]);
    release();
    await sent(t, 2);
    expect(t.engine.runs[1].request.scenario.buffs).toBe("group");
    t.engine.runs[1].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    expect(ANNOUNCED).toHaveLength(1);
    expect(ANNOUNCED[0]).toMatch(/^Buffs common group buffs/i);
  }, 30_000);

  it("is drawn after all when the next view cannot be loaded and the page stays where it was", async () => {
    let release;
    const until = new Promise((resolve) => (release = resolve));
    const t = open({ hold: { view: "wiki-group", until }, offline: ["wiki-group"] });
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    listen();
    choose("#buffs-group");
    await tick(30);
    t.engine.runs[0].finish(result());
    await tick(150);
    expect($("#main").classList.contains("solved")).toBe(false);
    release(); // the data of the group view does not come: the page goes back to the own-buffs view
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    expect(checkedOf("buffs")).toBe("own");
    expect($("#main").classList.contains("solved")).toBe(true);
    expect(rowNames()).toEqual(AC2.kit.map((ident) => (ident === null ? "Leave empty" : nameOf(ident))));
    expect(ANNOUNCED).toHaveLength(1);
  }, 30_000);
});

describe("the question to the visitor, when another part of the page asked it", () => {
  it("is said in the answer area, with a button that moves the focus to it, and the first report of the optimizer takes the place of the line", async () => {
    const t = open({ consent: "unknown" });
    await wikiView(t);
    // the Upgrade section's request asked the question: its panel is in that section, far from the answer area
    const panel = document.createElement("div");
    panel.className = "engine-consent";
    panel.tabIndex = -1;
    panel.textContent = "Load the optimizer?";
    $("#upgrade").append(panel);
    choose(slider(0, "2"));
    await sent(t, 1);
    expect($("#solve").hidden, "the answer area is not left empty").toBe(false);
    expect(text("#solve .solve-text")).toBe("The optimizer is waiting for your answer to the question below.");
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Go to the question"]);
    expect($("#main").classList.contains("solving")).toBe(true);
    $("#solve button").click();
    expect(document.activeElement).toBe(panel);
    t.engine.runs[0].onProgress({ phase: "loading", loaded: 10, total: 100 });
    await vi.waitFor(() => expect(text("#solve")).toContain(WORKING));
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Stop"]);
  }, 30_000);

  it("says again that it is working once the question is answered, though its request waits behind the one the question was asked for and has nothing to report", async () => {
    const t = open({ consent: "unknown" });
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    expect(text("#solve .solve-text")).toBe("The optimizer is waiting for your answer to the question below.");
    t.engine.agree(); // the visitor said yes
    await vi.waitFor(() => expect(text("#solve .solve-text")).toBe(WORKING), { timeout: 3000 });
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Stop"]);
    expect($("#main").classList.contains("solving")).toBe(true);
  }, 30_000);

  it("does not write over the fault that a no to the question brought", async () => {
    const t = open({ consent: "unknown" });
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    t.engine.consent = "declined";
    t.engine.runs[0].fail(Object.assign(new Error("The optimizer was not loaded: the visitor chose to keep the precomputed answers."), { code: "declined" }));
    await vi.waitFor(() => expect(text("#solve")).toMatch(/optimizer was not loaded/i));
    await tick(700);
    expect(text("#solve")).toMatch(/optimizer was not loaded/i);
    expect($$("#solve button").map((button) => button.textContent)).toEqual(["Load the optimizer"]);
  }, 30_000);

  it("has no button to the question while the question is not in the page, and has it, working, once the question is (G10)", async () => {
    const t = open({ consent: "unknown" });
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    expect(text("#solve .solve-text")).toBe("The optimizer is waiting for your answer to the question below.");
    expect($$("#solve button").filter((button) => !button.hidden), "(a button that would move the focus to the table)").toEqual([]);
    const panel = document.createElement("div"); // the client mounts its question
    panel.className = "engine-consent";
    panel.tabIndex = -1;
    $(".engine-slot").append(panel);
    await vi.waitFor(() => expect($$("#solve button").filter((button) => !button.hidden).map((button) => button.textContent)).toEqual(["Go to the question"]), { timeout: 3000 });
    $("#solve button").click();
    expect(document.activeElement).toBe(panel);
  }, 30_000);

  it("is below the line that says it: the question comes after the answer area", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    const slot = $("#solve").parentNode.querySelector(".engine-slot");
    expect($("#solve").compareDocumentPosition(slot) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("the notes of the runner-ups and of the robust core", () => {
  it("name the role's own weights among the assumptions they were made for, when only the weights are not the default", async () => {
    const t = open();
    $("#sw-tier").value = "10";
    change($("#sw-tier"));
    await t.app.whenIdle();
    for (const id of ["robust", "runnerups"]) {
      const details = $(`#${id}`);
      details.open = true;
      details.dispatchEvent(new Event("toggle"));
    }
    await t.app.whenIdle();
    await openWeights(t);
    choose(slider(0, "2"));
    await t.app.whenIdle();
    await vi.waitFor(() => expect($("#robust-na").hidden).toBe(false));
    expect(text("#robust-na")).toBe("Not computed for this view. The checks were made with dual wield, your own buffs and the role's own weights. Change the assumptions back to see them.");
    expect($("#runnerups-na").hidden).toBe(false);
    expect(text("#runnerups-na")).toMatch(/and the role's own weights\)\. Change the assumptions back to see them\.$/);
  }, 30_000);
});

// ---- claims of the review that are held to a test ---------------------------------------------------------------------------------------------------------

describe("an answer and the settings the page shows now (G1)", () => {
  it("is not drawn, said or kept when it arrives in the pause of a newer change: x2 is on the worker, the visitor moves to x0.5, and the answer for x2 comes before the request for x0.5 is sent", async () => {
    const t = open();
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1); // the worker has it
    const shard = rowNames();
    listen();
    choose(slider(0, "h")); // a newer change: its request goes after 300 ms
    await t.app.whenIdle();
    t.engine.runs[0].finish(result()); // the answer for x2 comes in that pause
    await tick(120);
    expect(rowNames()).toEqual(shard);
    expect($("#main").classList.contains("solved")).toBe(false);
    expect(text("#solve h3")).toBe("");
    expect(ANNOUNCED).toEqual([]);
    await sent(t, 2);
    expect(t.engine.runs[1].request.weights).toEqual({ multipliers: { AC: 0.5 } });
    t.engine.runs[1].finish(result(ATK2));
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    expect(rowNames()).toEqual(ATK2.kit.map((ident) => (ident === null ? "Leave empty" : nameOf(ident))));
    expect(ANNOUNCED).toHaveLength(1);
  }, 30_000);

  it("is not drawn when the answer is for settings the visitor has left and the page is loading another view, and is drawn when the page stays where it was", async () => {
    // (held here with the page's own steps: the answer parked by the page loading another view is for the view that is still shown if the other cannot be had, and for no view if it can)
    let release;
    const until = new Promise((resolve) => (release = resolve));
    const t = open({ hold: { view: "wiki-group", until } });
    await wikiView(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    choose("#buffs-group"); // the other view is loading
    await tick(30);
    t.engine.runs[0].finish(result()); // parked
    await tick(100);
    choose(slider(0, "h")); // and another change while it loads: the page will show the group buffs at x0.5 (or nothing, if that cannot be had)
    release();
    await sent(t, 2);
    expect(t.engine.runs[1].request).toMatchObject({ scenario: { buffs: "group" }, weights: { multipliers: { AC: 0.5 } } });
    await tick(100);
    expect($("#main").classList.contains("solved"), "the answer for the own buffs at x2 is nobody's now").toBe(false);
    expect(text("#solve h3")).toBe("");
  }, 30_000);

});

describe("a failure to load the sliders' code, for a screen reader (G6)", () => {
  it("is told in the page's status line, which is a polite live region: the visitor hears that the weights could not be loaded, and what the table shows", async () => {
    const loadWeights = vi.fn(() => Promise.reject(new Error("chunk")));
    const t = open({ loadWeights });
    await t.app.whenIdle();
    choose("#buffs-raid");
    await t.app.whenIdle();
    const status = $("#status");
    expect(status.getAttribute("role")).toBe("status");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(text("#status .status-text")).toMatch(/^Couldn't load the weights\. Reload the page to try again\. The table shows the precomputed answer/);
  });
});

describe("the role's own weights, however the sliders came to be at x1 (G8)", () => {
  it("are said in the same words for an address with w at x1 everywhere, and for sliders moved and put back by hand", async () => {
    const own = () => [text('[data-f="assume-weights"]'), text('[data-f="s-assumes"]')];
    const t = open({ search: "?tier=10&w=11111" });
    await t.app.whenIdle();
    expect(own()).toEqual(["role's own", "dual wield, your own buffs"]);
    expect(query()).not.toHaveProperty("w");
    await openWeights(t);
    choose(slider(0, "2"));
    await sent(t, 1);
    expect(text('[data-f="s-assumes"]')).toContain("armor class x2");
    choose(slider(0, "1")); // put back by hand
    await t.app.whenIdle();
    expect(own()).toEqual(["role's own", "dual wield, your own buffs"]);
    expect(query()).not.toHaveProperty("w");
    expect(t.engine.runs).toHaveLength(1);
  }, 30_000);
});

describe("the focus when the button of the answer area goes (G9)", () => {
  it("is handed to the heading, which can take it", async () => {
    const t = open();
    await wikiView(t);
    expect($("#wear-h").getAttribute("tabindex")).toBe("-1");
    choose(slider(0, "2"));
    await sent(t, 1);
    $("#solve button").focus();
    expect(document.activeElement.textContent).toBe("Stop");
    choose(slider(0, "1")); // back to a precomputed answer: the answer area is cleared, and its button goes
    await t.app.whenIdle();
    expect(document.activeElement).toBe($("#wear-h"));
  }, 30_000);
});

// ---- G5: the failure of the sliders' code goes when the code comes -----------------------------------------------------------------------------------------

describe("the sliders' code that comes at a later use, after it could not be had", () => {
  it("clears the failure with its Reload button, and works out what the page shows (G5)", async () => {
    let fail = true;
    const loadWeights = vi.fn(() => (fail ? Promise.reject(new Error("chunk")) : import(WEIGHTS_CHUNK)));
    const t = open({ loadWeights });
    await t.app.whenIdle();
    choose("#buffs-raid");
    await t.app.whenIdle();
    expect(text("#status .status-text")).toMatch(/^Couldn't load the weights\..*The table shows the precomputed answer/);
    expect(t.engine.runs).toHaveLength(0);
    fail = false;
    const details = $("#assume-weights");
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
    await t.app.whenIdle();
    expect($$("#assume-weights input[type=radio]")).toHaveLength(15);
    expect(text("#status"), "the failure is gone").toBe("");
    expect($$("#status button")).toHaveLength(0);
    await sent(t, 1); // and the raid the page shows is worked out
    expect(t.engine.runs[0].request.scenario.buffs).toBe("raid");
    expect(text("#solve")).toContain(WORKING);
  }, 30_000);
});
