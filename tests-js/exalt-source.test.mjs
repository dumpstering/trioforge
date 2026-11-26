// @vitest-environment jsdom
//
// Where a donor comes from (branch exalt-source): the shared effects file says, for a donor that has sources, `src`: a list of the texts the Source column of a kit row says of its sources (the kind of source that the
// word of the line names first, at most four), and after them, when more did not fit, the count of the others. The build makes them from the catalog, and the Python tests hold them to the function that words a
// Source column. The line of Wear this keeps its words and the "(Drop)" or "(Quest or crafted)" in it, kept together with its brackets, becomes a button that opens all of the texts beneath the line, the note of
// those that did not fit and a link to the item's page; the section's plan, its list of donors to farm and its ranked lists show the first text in plain view beside the donor, and "+N more" as a link to the item's page
// when there are others. A donor with no text says nothing more than it did, and a text is text, never markup. Run against the committed contract of the section (fixtures/site/contract-exalt/), as
// exalt-inline.test.mjs is, with texts given to some of its donors.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PLACES } from "../pipeline/trioforge/site/static/ui/exalt-plan.js";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract");
const WITH_EFFECTS = resolve(HERE, "../fixtures/site/contract-exalt");
const read = (path) => JSON.parse(readFileSync(resolve(path), "utf8"));
const EFFECTS = read(resolve(WITH_EFFECTS, "data/effects.json"));
const EXALT = read(resolve(WITH_EFFECTS, "data/exalt.json"));
const ITEMS = read(resolve(HERE, "../fixtures/site/results/items.json"));
const PAGE_HTML = readFileSync(resolve(WITH_EFFECTS, "trio-main.html"), "utf8");
const ITEM_PATH = "/assets/engine/data/items-0123456789ABCDEF.json";
const $ = (selector) => document.querySelector(selector);
const BODY = () => [...document.querySelectorAll("#kit-body tr")];
const ROW = (place) => BODY()[PLACES.indexOf(place)];
const waitFor = (check) => vi.waitFor(check, { timeout: 2000 });

/** The donors of the lines of the contract and the texts they are given here (the files of the contract say none: the fixture is built without the catalog). */
const HEAD_DONOR = "w90003"; // Crown of the Vanguard, a Vendor: the focus of the Head
const BACK_DONOR = "w80974"; // Choker of Seven Pebbles, Quest or crafted: the worn effect of the Neck (the one donor of the plan that is a quest item: the old name BACK of the constant is kept)
const CHEST_DONOR = "w90046"; // Mantle of the Faithful, Raid drop: a focus of the Chest
const WORN_DONOR = "w90029"; // Breastplate of Warding, Drop: a worn effect of the Chest, which has no text here
const HOSTILE = '<img src=x onerror="window.__owned = 1"> & <b>bold</b> "quoted"';
/** The `src` of the file: a list of texts, and after them the count of the sources that did not fit. The Crown has two texts and two more that did not fit, the Shawl one, the Mantle two. */
const TEXTS = {
  [HEAD_DONOR]: ["Lake of Ill Omen (a fixture lurker)", "Hollow Vale (a fixture shade)", 2],
  [BACK_DONOR]: ["quest: Fixture Rite"],
  [CHEST_DONOR]: [HOSTILE, "Plane of Hate (a fixture wraith)"],
};

const withSources = (src) => ({ ...structuredClone(EFFECTS), ...(src === undefined ? {} : { src }) });

function makeFetch(calls, effects) {
  return async (url) => {
    calls.push(String(url));
    const answer = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (url === "/data/effects.json") return answer(effects);
    if (url === "/data/pal-mnk-ber/exalt.json") return answer(EXALT);
    if (url === "/engine-manifest.json") return answer({ data_release: EXALT.release, items: { path: ITEM_PATH } });
    if (url === ITEM_PATH) return answer({ data_release: EXALT.release, defaults: ITEMS.defaults, items: ITEMS.items });
    if (String(url).startsWith("/data/pal-mnk-ber/")) return answer(read(resolve(CONTRACT, `data/${String(url).replace("/data/pal-mnk-ber/", "")}`)));
    throw new Error(`not asked for: ${url}`);
  };
}

let idle = [];
const runIdle = () => idle.splice(0).forEach((run) => run());

function mount(effects) {
  document.body.innerHTML = PAGE_HTML;
  window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
  const calls = [];
  const app = initTrio({
    document,
    window,
    fetch: makeFetch(calls, effects),
    exaltAhead: true,
    loadExalt: () => import("../pipeline/trioforge/site/static/ui/exalt.js"),
  });
  return { app, calls };
}

async function shown(effects) {
  const made = mount(effects);
  runIdle();
  await waitFor(() => expect(document.querySelectorAll("#kit-body .exalt-hint").length).toBeGreaterThan(0));
  return made;
}

async function openSection() {
  const section = $("#exalt");
  section.open = true;
  section.dispatchEvent(new Event("toggle"));
  await waitFor(() => expect($("#exalt-plan-table")).not.toBeNull());
}

/** What a line says, without its popup, its link to the plan and the text under it (they have their own tests). */
const lineText = (node) => {
  const copy = node.cloneNode(true);
  for (const extra of copy.querySelectorAll(".exalt-tip, .exalt-hint-plan, .exalt-src")) extra.remove();
  return copy.textContent.replace(/\s+/g, " ").trim();
};
const lines = (place) => [...ROW(place).querySelectorAll(".exalt-hint")];
const button = (place, index = 0) => lines(place)[index].querySelector("button.exalt-srcbtn");
const panelOf = (place, index = 0) => $(`#${button(place, index).getAttribute("aria-controls")}`);

beforeEach(() => {
  idle = [];
  delete window.IntersectionObserver;
  window.requestIdleCallback = (run) => idle.push(run);
  delete window.__owned;
});
afterEach(() => {
  document.documentElement.classList.remove("exalt-tip-open");
  document.body.replaceChildren();
  delete window.requestIdleCallback;
});

describe("the line under a place of Wear this", () => {
  it("keeps its words, and the word for how hard the donor is to get is a button, in its brackets as one piece, when the donor has texts", async () => {
    await shown(withSources(TEXTS));
    expect(lineText(lines("HEAD")[0])).toBe("Exalt: Spell Haste II (focus, +1) from Crown of the Vanguard (Vendor); level this item to +1");
    expect(lineText(lines("NECK")[0])).toBe("Exalt: Heritage of Mistmoore (worn, +3) from Choker of Seven Pebbles (Quest or crafted); level both to +3");
    const open = button("HEAD");
    expect(open).not.toBeNull();
    expect(open.textContent).toBe("Vendor");
    expect(button("NECK").textContent).toBe("Quest or crafted");
    expect(lines("HEAD")[0].querySelectorAll("button.exalt-srcbtn")).toHaveLength(1);
    // the bracket, the word and the bracket are one piece, which the page keeps on a line (it wraps before it, or not at all)
    const unit = open.parentElement;
    expect(unit.classList.contains("exalt-where")).toBe(true);
    expect(unit.textContent).toBe("(Vendor)");
    expect(unit.parentElement).toBe(lines("HEAD")[0]);
  });

  it("names what the button opens, and the name starts with the word it shows; it says whether it is open, and points at the text", async () => {
    await shown(withSources(TEXTS));
    const open = button("HEAD");
    expect(open.getAttribute("type")).toBe("button");
    expect(open.getAttribute("aria-label")).toBe("Vendor: where Crown of the Vanguard comes from");
    expect(button("NECK").getAttribute("aria-label")).toBe("Quest or crafted: where Choker of Seven Pebbles comes from");
    expect(open.getAttribute("aria-expanded")).toBe("false");
    const panel = panelOf("HEAD");
    expect(panel).not.toBeNull();
    expect(panel.hidden).toBe(true);
    expect(panel.id).toMatch(/^exalt-src-\d+$/);
    expect(lines("HEAD")[0].contains(panel)).toBe(true);
    expect(panel.getAttribute("role")).toBe("group");
    expect(panel.getAttribute("aria-label")).toBe("Where Crown of the Vanguard comes from"); // (it belongs to the donor, for a screen reader as well)
  });

  it("opens all the texts beneath the line, then the note of those that did not fit, then the link to the item's page", async () => {
    await shown(withSources(TEXTS));
    button("HEAD").click();
    const panel = panelOf("HEAD");
    expect(panel.hidden).toBe(false);
    expect([...panel.children].map((node) => node.className)).toEqual(["exalt-src-label", "exalt-src-text", "exalt-src-text", "exalt-src-more", "exalt-src-page"]);
    expect(panel.querySelector(".exalt-src-label").textContent).toBe("Where:");
    expect([...panel.querySelectorAll(".exalt-src-text")].map((node) => node.textContent)).toEqual(["Lake of Ill Omen (a fixture lurker)", "Hollow Vale (a fixture shade)"]);
    expect(panel.querySelector(".exalt-src-more").textContent).toBe("and 2 more on the item page");
    expect(panel.querySelector("a.exalt-src-page").textContent).toBe("Item page");
    // a donor with one source and none left over has the one text and the link
    button("NECK").click();
    expect([...panelOf("NECK").children].map((node) => node.className)).toEqual(["exalt-src-label", "exalt-src-text", "exalt-src-page"]);
    expect(panelOf("NECK").querySelector(".exalt-src-text").textContent).toBe("quest: Fixture Rite");
  });

  it("closes the text with a second click", async () => {
    await shown(withSources(TEXTS));
    const open = button("HEAD");
    open.click();
    expect(open.getAttribute("aria-expanded")).toBe("true");
    expect(panelOf("HEAD").textContent).toContain("Lake of Ill Omen (a fixture lurker)");
    open.click();
    expect(open.getAttribute("aria-expanded")).toBe("false");
    expect(panelOf("HEAD").hidden).toBe(true);
  });

  it("opens the text of each line on its own: the other lines of the place and of the other places stay as they are", async () => {
    await shown(withSources(TEXTS));
    button("HEAD").click();
    expect(panelOf("NECK").hidden).toBe(true);
    expect(button("NECK").getAttribute("aria-expanded")).toBe("false");
    button("NECK").click();
    expect(panelOf("HEAD").hidden).toBe(false);
    expect(panelOf("NECK").hidden).toBe(false);
    expect(lines("CHEST")).toHaveLength(2);
    expect(lines("CHEST")[0].querySelector("button.exalt-srcbtn")).not.toBeNull(); // the Mantle has texts
    expect(lines("CHEST")[1].querySelector("button.exalt-srcbtn")).toBeNull(); // the Breastplate has none: its line says "(Drop)" as it always did
  });

  it("says nothing more for a donor that has no text: the line is what it was, with no button, no bracket piece and nothing hidden", async () => {
    await shown(withSources(TEXTS));
    const line = lines("CHEST")[1];
    expect(lineText(line)).toBe("Exalt: Ultravision (worn, +3) from Breastplate of Warding (Drop); level this item to +3");
    expect(line.querySelector("button.exalt-srcbtn, .exalt-src, .exalt-where")).toBeNull();
    expect(line.textContent).toContain("(Drop)");
    expect(lines("SHOULDERS")[0].querySelector(".exalt-src, .exalt-srcbtn")).toBeNull();
  });

  it("is the line it was when the file has no table of texts at all, or one that is not a table, or entries that are not lists of texts", async () => {
    const bad = [
      undefined, null, [], "a text", 4,
      { [HEAD_DONOR]: "Lake of Ill Omen (a fixture lurker)", [BACK_DONOR]: 3, [CHEST_DONOR]: null, [WORN_DONOR]: { a: 1 } }, // (the texts of one are not a list)
      { [HEAD_DONOR]: [], [BACK_DONOR]: [""], [CHEST_DONOR]: [3], [WORN_DONOR]: [["a"]], w1: ["a", null, "b"] }, // (no text, an empty text, a number, a list, a hole)
      { [HEAD_DONOR]: [2], [BACK_DONOR]: ["   "] },
    ]; // prettier-ignore
    for (const given of bad) {
      document.body.replaceChildren();
      idle = [];
      await shown(withSources(given));
      expect(document.querySelectorAll(".exalt-srcbtn, .exalt-src, .exalt-where"), JSON.stringify(given)).toHaveLength(0);
      expect(lineText(lines("HEAD")[0])).toBe("Exalt: Spell Haste II (focus, +1) from Crown of the Vanguard (Vendor); level this item to +1");
    }
  });

  it("keeps the texts of an entry that is a list of texts, and ignores a count that is not a whole number of at least one", async () => {
    await shown(withSources({ [HEAD_DONOR]: ["Lake of Ill Omen (a fixture lurker)", 0], [BACK_DONOR]: ["quest: Fixture Rite", 1.5], [CHEST_DONOR]: ["Plane of Hate (a fixture wraith)", -3] }));
    for (const place of ["HEAD", "NECK"]) {
      button(place).click();
      expect(panelOf(place).querySelector(".exalt-src-more"), place).toBeNull();
      expect(panelOf(place).querySelectorAll(".exalt-src-text")).toHaveLength(1);
    }
  });

  it("sets the text as text: nothing of it becomes markup, whatever it says", async () => {
    await shown(withSources(TEXTS));
    button("CHEST", 0).click();
    const panel = panelOf("CHEST", 0);
    expect(panel.querySelector(".exalt-src-text").textContent).toBe(HOSTILE);
    expect(panel.querySelector("img, b, script")).toBeNull();
    expect(panel.querySelector(".exalt-src-text").children).toHaveLength(0);
    expect(window.__owned).toBeUndefined();
  });

  it("links the item's page from the opened text, when the donor has one and the line has none", async () => {
    await shown(withSources(TEXTS));
    expect(lines("HEAD")[0].querySelector("a:not(.exalt-hint-plan)")?.getAttribute("href")).toBe("/item/w90003/");
    const link = lines("HEAD")[0].querySelector(".exalt-src a");
    expect(link.textContent).toBe("Item page");
    expect(link.getAttribute("aria-label")).toBe("Item page of Crown of the Vanguard");
    expect(panelOf("HEAD").contains(link)).toBe(true);
  });

  it("is drawn again with its texts for the kit of another tier, which the browser matches itself", async () => {
    const { app, calls } = await shown(withSources(TEXTS));
    const change = (value) => {
      const node = $("#sw-tier");
      node.value = value;
      node.dispatchEvent(new Event("change", { bubbles: true }));
    };
    change("10");
    await waitFor(() => expect(app.exaltShown.tier).toBe(10));
    await waitFor(() => (runIdle(), expect(calls).toContain(ITEM_PATH)));
    await waitFor(() => (runIdle(), expect(document.querySelectorAll("#kit-body .exalt-hint").length).toBeGreaterThan(0)));
    const drawn = [...document.querySelectorAll("#kit-body .exalt-hint")];
    for (const line of drawn) {
      const open = line.querySelector("button.exalt-srcbtn");
      const donor = /from (.+?) \(/.exec(lineText(line))?.[1];
      const key = Object.keys(EFFECTS.items).find((k) => EFFECTS.items[k][0] === donor);
      if (TEXTS[key]) {
        expect(open, `${donor} has texts`).not.toBeNull();
        const want = TEXTS[key].filter((one) => typeof one === "string");
        expect([...$(`#${open.getAttribute("aria-controls")}`).querySelectorAll(".exalt-src-text")].map((node) => node.textContent)).toEqual(want);
      } else {
        expect(open, `${donor} has none`).toBeNull();
      }
    }
    expect(drawn.some((line) => line.querySelector("button.exalt-srcbtn"))).toBe(true);
  });

  it("asks for nothing more than it did: the files are the same two, and the texts are in the one that is fetched", async () => {
    const { calls } = await shown(withSources(TEXTS));
    expect(calls.filter((url) => /effects\.json|exalt\.json/.test(url)).sort()).toEqual(["/data/effects.json", "/data/pal-mnk-ber/exalt.json"]);
    expect(calls.filter((url) => /source|src/.test(url))).toEqual([]);
  });
});

describe("the section's plan and lists", () => {
  const FIRST = { [HEAD_DONOR]: "Lake of Ill Omen (a fixture lurker)", [BACK_DONOR]: "quest: Fixture Rite", [CHEST_DONOR]: HOSTILE };

  it("shows the first text of each donor in plain view, without a click, beside the donor in the table of the plan, and no other", async () => {
    await shown(withSources(TEXTS));
    await openSection();
    const table = $("#exalt-plan-table");
    const found = [...table.querySelectorAll(".exalt-from")];
    expect(found.map((node) => node.textContent)).toEqual(expect.arrayContaining(Object.values(FIRST)));
    for (const node of found) {
      expect(node.closest("[hidden]"), "in plain view").toBeNull();
      expect(node.closest("details:not([open])"), "not behind a closed disclosure").toBeNull();
      expect(node.querySelector("*")).toBeNull(); // text, never markup
    }
    expect(window.__owned).toBeUndefined();
    const row = [...table.querySelectorAll("tbody tr")].find((tr) => tr.textContent.includes("Crown of the Vanguard") && tr.textContent.includes("Spell Haste II"));
    expect(row.querySelector(".exalt-from").textContent).toBe(FIRST[HEAD_DONOR]);
    expect(row.textContent).toContain("Vendor");
    expect(row.textContent).not.toContain("Hollow Vale"); // (the second text is the opened one's)
  });

  it("says '+N more' as a link to the item's page where the donor has other sources, N counting those that did not fit, and nothing where it has one", async () => {
    await shown(withSources(TEXTS));
    await openSection();
    const row = (donor, effect) => [...$("#exalt-plan-table").querySelectorAll("tbody tr")].find((tr) => tr.textContent.includes(donor) && tr.textContent.includes(effect));
    const crown = row("Crown of the Vanguard", "Spell Haste II").querySelector("a.exalt-more");
    expect(crown.textContent).toBe("+3 more"); // (two more texts and two that did not fit, less the one that is shown)
    expect(crown.getAttribute("href")).toBe("/item/w90003/");
    expect(crown.getAttribute("aria-label")).toBe("+3 more sources of Crown of the Vanguard, on its item page");
    expect(row("Mantle of the Faithful", "Improved Healing III").querySelector("a.exalt-more").textContent).toBe("+1 more");
    expect(row("Choker of Seven Pebbles", "Heritage of Mistmoore").querySelector(".exalt-more")).toBeNull();
    expect(row("Choker of Seven Pebbles", "Heritage of Mistmoore").querySelector(".exalt-from").textContent).toBe("quest: Fixture Rite");
  });

  it("shows the same in the list of donors to farm, and says no more of a donor that has none", async () => {
    await shown(withSources(TEXTS));
    await openSection();
    const items = [...document.querySelectorAll("#exalt-donors li")];
    expect(items.length).toBeGreaterThan(2);
    const crown = items.find((li) => li.textContent.includes("Crown of the Vanguard"));
    expect(crown.querySelector(".exalt-from").textContent).toBe(FIRST[HEAD_DONOR]);
    expect(crown.querySelector("a.exalt-more").textContent).toBe("+3 more");
    expect(crown.textContent).toContain("Vendor");
    const plain = items.find((li) => !li.querySelector(".exalt-from"));
    expect(plain).toBeDefined();
    expect(plain.textContent).toMatch(/: .?(Vendor|Quest or crafted|Drop|Raid drop|No known source), (needs \+\d|no level needed)$/);
  });

  it("shows it in the ranked lists, for the best donor and the others", async () => {
    await shown(withSources(TEXTS));
    await openSection();
    const lists = [...$("#exalt-lists").querySelectorAll(".exalt-from")].map((node) => node.textContent);
    expect(lists).toEqual(expect.arrayContaining([FIRST[HEAD_DONOR], FIRST[BACK_DONOR]]));
    for (const node of $("#exalt-lists").querySelectorAll(".exalt-from, a.exalt-more")) expect(node.closest("[hidden]")).toBeNull();
    expect([...$("#exalt-lists").querySelectorAll("a.exalt-more")].some((node) => node.textContent === "+3 more")).toBe(true);
  });

  it("draws nothing extra for a donor that has no text, and nothing at all when the file has no table", async () => {
    await shown(withSources(undefined));
    await openSection();
    expect($("#exalt").querySelectorAll(".exalt-from, .exalt-more, .exalt-src, .exalt-srcbtn")).toHaveLength(0);
    const plain = $("#exalt-plan").textContent;
    document.body.replaceChildren();
    idle = [];
    await shown(withSources({}));
    await openSection();
    expect($("#exalt-plan").textContent).toBe(plain);
  });
});
