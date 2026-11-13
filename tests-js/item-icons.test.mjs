// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// The pictures of the rows of Wear this: a shard says the picture of each of its items (`ic`: the item's own) and of each of the 22 places (`pl`: a worn place's own, the pouch for a held one), with the
// names they use (`icons`); the list of the site (`data/item-icons.json`) says the same of every item of the item table; and the page code draws a picture beside the name of a place, whatever view or
// answer of the optimizer it draws: in a worn place the item's own, else the place's; in a held place (the main hand, the off hand, the range, the any slots) the item's own, else the pouch, and none
// for an empty one; and a picture of armor only in the place of its own part (in a worn place). The rule that says which picture an item has is the generator's
// (pipeline/trioforge/site/itemicon.py, tried in pipeline/tests/test_site_itemicon.py); what the browser does is read the characters, refuse what is not what the generator writes, and draw. The
// characters are read here by a table of this file's own, so that a test of the page does not take its answer from the code it tests.

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseIcons, parseShard } from "../pipeline/trioforge/site/static/shard.js";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";
import { REFERENCE } from "./best-kit-harness.mjs";
import { ITEMS_BYTES, makeSite, siteFetch } from "./engine-site-fixture.mjs";
import { fakeEngine } from "./upgrade-answer-helpers.mjs";
import { $, $$, mountPage } from "./upgrade-helpers.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CONTRACT = resolve(ROOT, "fixtures/site/contract");
const shardFile = (name) => JSON.parse(readFileSync(resolve(CONTRACT, `data/${name}.json`), "utf8"));
/** The characters of a file, taken from the page code's own file (a test holds that string to the generator's, pipeline/tests/test_site_icons.py): a copy typed here would go stale the next time a character is added. */
const DIGITS = /^const ICON_DIGITS = "([^"]+)";$/m.exec(readFileSync(resolve(ROOT, "pipeline/trioforge/site/static/shard.js"), "utf8"))[1];
/** What a file says of one character: the name it stands for, or null. */
const decode = (names, char) => (char === "-" ? null : names[DIGITS.indexOf(char)]);
const encode = (value) => new TextEncoder().encode(JSON.stringify(value));
const HEAD = 0;
const FACE = 1;
const WRIST = 8;
const CHEST = 13;
const LEGS = 14;
const FEET = 15;
const RANGE = 17;
const ANY = 18; // (and 19)
const PRIMARY = 20; // the main hand, the place of a kit that takes a weapon
const SECONDARY = 21; // the off hand
const HELD = [RANGE, ANY, 19, PRIMARY, SECONDARY]; // the places that hold something
const ANYS = [ANY, 19]; // the two any rows: they take whatever fits, so the file has no picture for them and the item's own characters decide
const POUCH = "icon-pouch";
/** The thirteen pictures of the held things and the pouch: they stay on a held row (written here again, not taken from the page's code). */
const HELD_PICTURES = ["idol", "stone", "horn", "lantern", "cup", "scroll", "rod", "whip", "claw", "pick", "polearm", "charm", "fishing-pole", "pouch"].map((name) => `icon-${name}`);

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("the characters of a file", () => {
  it("have no vowel and no y, so that a string of them cannot spell a word, and none of the characters that could make a path or end a string", () => {
    expect(DIGITS).not.toMatch(/[aeiouyAEIOUY]/);
    expect(DIGITS).not.toMatch(/[:/\\"<>&'-]/);
    expect(new Set(DIGITS).size).toBe(DIGITS.length);
    expect(DIGITS.length).toBeGreaterThanOrEqual(69 + 4); // (the pictures the site can name in one file, and room for the next)
    expect(DIGITS.startsWith("0123456789")).toBe(true);
  });
});

describe("the pictures of a shard", () => {
  it("gives each item its picture, and the shard the pictures of its 22 places: the pouch for the main hand, the off hand and the range, none for the any rows", () => {
    const doc = shardFile("wiki-own");
    const shard = parseShard(structuredClone(doc));
    expect(doc.ic).toHaveLength(doc.items.length);
    expect("sl" in doc).toBe(false); // (a row needs the item's own picture and its place: nothing more is carried)
    expect(shard.items.map((item) => item.icon)).toEqual([...doc.ic].map((char) => decode(doc.icons, char)));
    expect(shard.places).toEqual([...doc.pl].map((char) => decode(doc.icons, char)));
    expect(shard.places).toHaveLength(22);
    for (const index of HELD) expect(shard.places[index]).toBe(ANYS.includes(index) ? null : POUCH);
    expect(shard.places.filter((name) => name !== null)).toHaveLength(20);
    expect(shard.items.some((item) => item.icon === POUCH)).toBe(true); // (an item that fits a held place and has no picture of its own: its character is the pouch, which the any rows draw)
    expect(shard.items.some((item) => item.icon !== null && !shard.places.includes(item.icon)) && shard.items.some((item) => shard.places.includes(item.icon))).toBe(true); // (the fixture has items of both kinds: an own picture, and the picture of the page heading or the pouch)
    expect(shard.items.every((item) => !("slotIcon" in item))).toBe(true);
  });

  it("is what it was where its file names no pictures: no icon on an item and no places", () => {
    const doc = shardFile("wiki-own");
    for (const name of ["icons", "ic", "pl"]) delete doc[name];
    const shard = parseShard(doc);
    expect(shard.places).toBeNull();
    expect(shard.items.every((item) => !("icon" in item))).toBe(true);
  });

  it.each([
    ["names that are not a list", (doc) => (doc.icons = "icon-helm")],
    ["a name that is no icon", (doc) => (doc.icons[0] = "helm")],
    ["a name with markup in it", (doc) => (doc.icons[0] = 'icon-x"><img src=x onerror=alert(1)>')],
    ["a name with a capital", (doc) => (doc.icons[0] = "icon-Helm")],
    ["a name that is not text", (doc) => (doc.icons[0] = 7)],
    ["more names than the characters are", (doc) => (doc.icons = Array.from({ length: DIGITS.length + 1 }, (_, n) => `icon-n${n}`))],
    ["a character for too few items", (doc) => (doc.ic = doc.ic.slice(1))],
    ["a character for too many items", (doc) => (doc.ic += "-")],
    ["a character that is no digit", (doc) => (doc.ic = " " + doc.ic.slice(1))],
    ["a character that is a quote", (doc) => (doc.ic = '"' + doc.ic.slice(1))],
    ["a digit that names nothing", (doc) => (doc.ic = DIGITS[doc.icons.length] + doc.ic.slice(1))],
    ["too few places", (doc) => (doc.pl = doc.pl.slice(1))],
    ["a place that names nothing", (doc) => (doc.pl = DIGITS[doc.icons.length] + doc.pl.slice(1))],
    ["characters that are not text", (doc) => (doc.ic = [...doc.ic])],
    ["pictures for the items only", (doc) => delete doc.pl],
    ["pictures for the places only", (doc) => delete doc.ic],
  ])("refuses a file with %s as a whole", (_, spoil) => {
    const doc = shardFile("wiki-own");
    spoil(doc);
    expect(() => parseShard(doc)).toThrow(/bad icons/);
  });
});

describe("the list of the pictures of the item table", () => {
  const list = { icons: ["icon-axe-2h", "icon-shield"], ic: "0-1-0", pl: `${"-".repeat(13)}1${"-".repeat(8)}` };

  it("gives the pictures of each item in the order of the table, and of each place", () => {
    expect(parseIcons(list, 5)).toEqual({
      items: ["icon-axe-2h", null, "icon-shield", null, "icon-axe-2h"],
      places: [...Array(13).fill(null), "icon-shield", ...Array(8).fill(null)],
    });
  });

  it("is refused for a table of another size, as a shard's pictures are for another", () => {
    expect(() => parseIcons(list, 4)).toThrow(/bad icons/);
    expect(() => parseIcons({ ...list, ic: "0-1-9" }, 5)).toThrow(/bad icons/);
    expect(() => parseIcons({ ...list, icons: ["icon-<b>"] }, 5)).toThrow(/bad icons/);
    expect(parseIcons({ icons: [], ic: "", pl: "-".repeat(22) }, 0)).toEqual({ items: [], places: Array(22).fill(null) });
    expect(parseIcons({}, 5)).toBeNull(); // (a file with no pictures at all is not an error)
  });
});

// ---- the rows ----------------------------------------------------------------------------------------------------------------------------------

const rows = () => $$("#kit-body tr");
/** The icon beside a place, "icon-chest", or null: the span the page puts first in the cell of the place. */
const pictureOf = (row) => {
  const first = row.querySelector("th")?.firstElementChild;
  if (!first || first.tagName !== "SPAN" || !first.classList.contains("art")) return null;
  return [...first.classList].find((name) => name.startsWith("art-icon-"))?.slice(4) ?? null;
};
const change = (element, value) => {
  if (value !== undefined) element.value = value;
  element.dispatchEvent(new Event("change", { bubbles: true }));
};

function mount(env = {}) {
  mountPage();
  window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
  const fetch = async (url) => {
    const name = String(url).replace("/data/pal-mnk-ber/", "").replace(".json", "");
    return { ok: true, status: 200, json: async () => structuredClone(shardFile(name)) };
  };
  return initTrio({ document, window, fetch, ...env });
}

/** The part of the body of a picture of armor or of a place of armor (`icon-chest-plate`, `icon-chest`), or null: written here again, so that a test of the page does not take its answer from the page's code. */
const armorOf = (name) => /^icon-(helm|chest|arms|legs|feet|hands)(?:-|$)/.exec(name ?? "")?.[1] ?? null;

/**
 * What a row of a kit shows for an item, as the rule says it (art.row_icon, written plainly): in a held place the item's own character, else the file's picture of the place (the pouch; an any row has none),
 * and none for an empty one; in a worn place the item's own, else the place's; a picture of the held things only on a held row and a picture of armor only in the place of its own part (the place's picture
 * instead); an empty worn place has the place's.
 */
const wanted = (item, place, index) => {
  const own = item === null ? null : (item.icon ?? null);
  if (HELD.includes(index)) return item === null ? null : (own ?? place);
  if (own === null || HELD_PICTURES.includes(own)) return place;
  return armorOf(own) !== null && armorOf(own) !== armorOf(place) ? place : own;
};

describe("the rows of a view the page draws from a shard", () => {
  it("show the picture of each item in a worn place and else the place's, and in a held place the item's own and else the pouch", async () => {
    const app = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const shard = parseShard(structuredClone(shardFile("wiki-own")));
    const scenario = shard.scenario(app.displayed.race, app.displayed.role, 10, app.displayed.setup);
    expect(scenario).not.toBeNull();
    const want = scenario.kit.map((item, index) => wanted(item, shard.places[index], index));
    expect(rows().map(pictureOf)).toEqual(want);
    expect(want.some((name, index) => name !== shard.places[index])).toBe(true); // (an item's own picture is among them)
    expect(scenario.kit.some((item, index) => item !== null && !HELD.includes(index) && item.icon !== null && want[index] === shard.places[index])).toBe(true); // (a worn place's own, for an item whose character is its heading's)
    for (const index of HELD) expect(scenario.kit[index] === null ? want[index] === null : want[index] === (scenario.kit[index].icon ?? (ANYS.includes(index) ? null : POUCH))).toBe(true);
    for (const index of HELD) if (scenario.kit[index] !== null && !ANYS.includes(index)) expect(rows().map(pictureOf)[index]).not.toBeNull(); // (no filled row of the main hand, the off hand or the range is without a picture)
    for (const index of ANYS) if (scenario.kit[index] !== null && scenario.kit[index].icon === POUCH) expect(pictureOf(rows()[index])).toBe(POUCH); // (an any row has the pouch for an item the file says fits a held place)
    // each picture is one empty span, hidden from a screen reader, with no style of its own, and a view drawn again replaces it and never adds a second
    for (const row of rows()) {
      for (const span of row.querySelectorAll("th > span")) {
        expect(span.getAttribute("aria-hidden")).toBe("true");
        expect(span.textContent).toBe("");
        expect(span.hasAttribute("style")).toBe(false);
      }
      expect(row.querySelectorAll("th > span.art").length).toBeLessThanOrEqual(1);
    }
  });

  it("go back to the pictures the page was made with when the view comes back to the baked one", async () => {
    const app = mount();
    const baked = rows().map(pictureOf);
    const role = app.config.defaults.role;
    $("#role-tank").checked = true;
    change($("#role-tank"));
    await app.whenIdle();
    expect(app.displayed.role).toBe("tank");
    expect(rows().map(pictureOf)).not.toEqual(baked); // (the tank's kit has a shield in the off hand)
    expect(pictureOf(rows()[SECONDARY])).toBe("icon-shield");
    $(`#role-${role}`).checked = true;
    change($(`#role-${role}`));
    await app.whenIdle();
    expect(rows().map(pictureOf)).toEqual(baked);
  });

  it("draw the rule of the rows for any item: a worn place keeps its picture, a held place has the item's own or the pouch, an armor picture stays in its own place", async () => {
    const app = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const shard = parseShard(structuredClone(shardFile("wiki-own")));
    const item = (key, icon) => ({ key, name: `Item ${key}`, rule: "fixed0", arrival: 0, source: "", evidence: "wiki", deity: [], icon });
    for (const index of HELD) expect(shard.places[index]).toBe(ANYS.includes(index) ? null : POUCH); // (the main hand has no sword of its own, and the range no bow: the pouch, for an item with no picture)
    const kit = Array(22).fill(null);
    kit[ANY] = item("w1", "icon-axe-2h"); // an any slot: the page was made with no picture here; the item's own is drawn
    kit[SECONDARY] = item("w2", null); // the off hand: none of its own, the pouch
    kit[PRIMARY] = item("w3", null); // the main hand, of an item that fits the off hand too: no sword stands in, the pouch
    kit[RANGE] = item("w6", null); // the range, of an item that has no picture: no bow stands in (the reviewer's brooch), the pouch
    kit[19] = item("w10", "icon-bow"); // an item that is an archery weapon, wherever it stands: its own
    kit[CHEST] = item("w4", null); // an item of no picture of its own in a worn place: the place's, whatever else the item fits
    kit[WRIST] = item("w5", null); // (the back straps that also fit the back: the wrist's)
    kit[LEGS] = item("w7", "icon-chest-plate"); // a chest picture is never on the legs row: the legs' own
    kit[FEET] = item("w8", "icon-feet-plate"); // a feet picture on the feet row: its own
    kit[HEAD] = item("w9", "icon-wand"); // a picture that is not armor, in a worn place: its own
    expect(app.drawSolved({ items: kit, tier: 10, hasteAssumed: 0, value: 1, kind: "role" })).toBe(true);
    expect(rows()[ANY].querySelector("th > span.art")?.className).toBe("art art-icon-axe-2h");
    expect(pictureOf(rows()[SECONDARY])).toBe(POUCH);
    expect(pictureOf(rows()[PRIMARY])).toBe(POUCH);
    expect(pictureOf(rows()[RANGE])).toBe(POUCH);
    expect(pictureOf(rows()[19])).toBe("icon-bow");
    expect(pictureOf(rows()[CHEST])).toBe(shard.places[CHEST]);
    expect(pictureOf(rows()[WRIST])).toBe(shard.places[WRIST]);
    expect(pictureOf(rows()[LEGS])).toBe(shard.places[LEGS]);
    expect(pictureOf(rows()[FEET])).toBe("icon-feet-plate");
    expect(pictureOf(rows()[HEAD])).toBe("icon-wand");
    expect(pictureOf(rows()[FACE])).toBe(shard.places[FACE]); // (an empty place has its own)
    kit[ANY] = null;
    app.drawSolved({ items: kit, tier: 10, hasteAssumed: 0, value: 1, kind: "role" });
    expect(rows()[ANY].querySelector("th > span.art")).toBeNull(); // (an empty any slot has no picture, as its place has none)
    expect(pictureOf(rows()[RANGE])).toBe(POUCH);
    for (const row of rows()) expect(row.querySelectorAll("th > span.art").length).toBeLessThanOrEqual(1);
    kit.fill(null);
    app.drawSolved({ items: kit, tier: 10, hasteAssumed: 0, value: 1, kind: "role" });
    for (const index of HELD) expect(rows()[index].querySelector("th > span.art")).toBeNull(); // (an empty held row is unchanged: none; the pouch is the picture of a filled one)
    for (const index of [HEAD, FACE, CHEST]) expect(pictureOf(rows()[index])).toBe(shard.places[index]); // (an empty worn row has its place's)
  });

  it("draw the pouch in each of the five held places for an item that has no picture, and the item's own picture in each for one that has, whatever else the row showed before", async () => {
    const app = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const item = (key, icon) => ({ key, name: `Item ${key}`, rule: "fixed0", arrival: 0, source: "", evidence: "wiki", deity: [], icon });
    for (const index of HELD) {
      const kit = Array(22).fill(null);
      kit[index] = item(`w${index}`, ANYS.includes(index) ? POUCH : null); // (an any row is told by the item's character: the pouch for an item that fits a held place)
      app.drawSolved({ items: kit, tier: 10, hasteAssumed: 0, value: 1, kind: "role" });
      expect(pictureOf(rows()[index])).toBe(POUCH);
      kit[index] = item(`w${index}`, "icon-idol");
      app.drawSolved({ items: kit, tier: 10, hasteAssumed: 0, value: 1, kind: "role" });
      expect(pictureOf(rows()[index])).toBe("icon-idol");
      kit[index] = null;
      app.drawSolved({ items: kit, tier: 10, hasteAssumed: 0, value: 1, kind: "role" });
      expect(rows()[index].querySelector("th > span.art")).toBeNull();
    }
  });

  it("keeps the held places where the data puts them: the last five of the 22, of which the generator gives the pouch to the range, the main hand and the off hand", () => {
    const doc = shardFile("wiki-own");
    const places = [...doc.pl].map((char) => decode(doc.icons, char));
    expect(places.map((name, index) => (name === POUCH ? index : null)).filter((index) => index !== null)).toEqual([RANGE, PRIMARY, SECONDARY]);
    for (const index of ANYS) expect(places[index]).toBeNull();
  });

  it("draw an any row as the item says it: a robe, a cloak and a girdle show their place's picture (the page heading's), an item that fits a held place the pouch, an item of two places of two pictures none", async () => {
    const app = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const item = (key, icon) => ({ key, name: `Item ${key}`, rule: "fixed0", arrival: 0, source: "", evidence: "wiki", deity: [], icon });
    const cases = [
      ["icon-chest", "icon-chest"], // a robe: the file's character for it is its heading's picture
      ["icon-back", "icon-back"], // a cloak
      ["icon-waist", "icon-waist"], // a girdle
      [POUCH, POUCH], // a held item with no picture of its own
      [null, null], // two worn places of two pictures: none (as its page heading), and an item the file does not know
      ["icon-claw", "icon-claw"], // one of the thirteen
      ["icon-chest-plate", "icon-chest-plate"], // an own picture of armor, as it was
    ];
    for (const index of ANYS) {
      for (const [icon, want] of cases) {
        const kit = Array(22).fill(null);
        kit[index] = item("w1", icon);
        app.drawSolved({ items: kit, tier: 10, hasteAssumed: 0, value: 1, kind: "role" });
        expect(pictureOf(rows()[index])).toBe(want);
      }
    }
  });

  it("keep a picture of the held things on a held row: on the worn row of the same item the place's picture, as before (Tsiraka's Claws, Pulsating Gem, Cinctured Whip)", async () => {
    const app = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const shard = parseShard(structuredClone(shardFile("wiki-own")));
    const item = (key, icon) => ({ key, name: `Item ${key}`, rule: "fixed0", arrival: 0, source: "", evidence: "wiki", deity: [], icon });
    const HANDS = 10;
    const NECK = 4;
    const WAIST = 16;
    for (const icon of HELD_PICTURES) {
      const kit = Array(22).fill(null);
      kit[HANDS] = item("w1", icon);
      kit[NECK] = item("w2", icon);
      kit[WAIST] = item("w3", icon);
      kit[PRIMARY] = item("w4", icon);
      kit[ANY] = item("w5", icon);
      app.drawSolved({ items: kit, tier: 10, hasteAssumed: 0, value: 1, kind: "role" });
      expect(pictureOf(rows()[HANDS])).toBe(shard.places[HANDS]);
      expect(pictureOf(rows()[NECK])).toBe(shard.places[NECK]);
      expect(pictureOf(rows()[WAIST])).toBe(shard.places[WAIST]);
      expect(pictureOf(rows()[PRIMARY])).toBe(icon);
      expect(pictureOf(rows()[ANY])).toBe(icon);
    }
    const kit = Array(22).fill(null);
    kit[HANDS] = item("w6", "icon-wand"); // (a picture the rule gave before the thirteen: on a worn row it is the item's own, as it was)
    app.drawSolved({ items: kit, tier: 10, hasteAssumed: 0, value: 1, kind: "role" });
    expect(pictureOf(rows()[HANDS])).toBe("icon-wand");
  });
});

// ---- the rows of an answer of the optimizer, whose items come from the item table, not from a shard -----------------------------------------------

const [AC2] = REFERENCE.cases;
const TABLE = JSON.parse(ITEMS_BYTES.toString("utf8"));
/** An item of the table that no shard of the fixture lists: invented. */
const AXE = { id: 90997, name: "Reaver of Test Fields", slots: ["PRIMARY"], stats: { STR: 3 }, weight10: 10, weapon: { skill: "2H Slashing", dmg: 20, delay: 30, bonus: null }, tier_rule: "drop", evidence: { level: "strict" }, source: { drops: ["Plane of Fear"] } };
const SWORD = { ...AXE, id: 90996, name: "A Plain Blade", weapon: { skill: "1H Slashing", dmg: 8, delay: 20, bonus: null } };
const result = (kit) => ({ kind: "scenario", mode: "best-kit", status: "optimal", proven: true, label: null, F: AC2.F, value: AC2.value, kit, buffs: [...AC2.buffs], hasteAssumed: AC2.hasteAssumed, elapsedMs: 12 });
const kitWith = (...idents) => AC2.kit.map((ident, place) => idents.find(([at]) => at === place)?.[1] ?? ident);

/** The page with a table that has the two invented items, and the list of the pictures of the site as `serve(good)` gives it (or the fault it makes). */
function open(serve) {
  const table = { ...TABLE, count: TABLE.items.length + 2, items: [...TABLE.items, AXE, SWORD] };
  const bytes = encode(table);
  const site = makeSite({ items: bytes });
  mountPage();
  document.getElementById("main").dataset.ev = "wiki";
  window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
  site.files.set("/engine-manifest.json", encode(site.manifestJson));
  const net = siteFetch(site);
  const engine = fakeEngine();
  const digest = createHash("sha256").update(bytes).digest("hex");
  const rest = "-".repeat(table.items.length - 2);
  const good = {
    v: 1,
    release: site.manifestJson.data_release,
    items: digest,
    icons: ["icon-axe-2h", "icon-sword-1h"],
    ic: `${rest}0-`, // the axe has a picture of its own, and the blade (the last item) has none
    pl: "-".repeat(22),
  };
  const asked = [];
  const fetchImpl = async (url, init) => {
    const path = new URL(String(url), "https://trioforge.test").pathname;
    const shard = /^\/data\/pal-mnk-ber\/(.+)\.json$/.exec(path);
    if (shard !== null) return { ok: true, status: 200, json: async () => structuredClone(shardFile(shard[1])) };
    if (path === "/data/item-icons.json") {
      asked.push(path);
      const answer = serve(good);
      return answer.ok === false ? { ok: false, status: answer.status ?? 404, json: async () => ({}) } : { ok: true, status: 200, json: async () => structuredClone(answer) };
    }
    return net.fetchImpl(url, init);
  };
  const app = initTrio({ document, window, fetch: fetchImpl, reload: vi.fn(), loadEngine: engine.loadEngine, loadWeights: () => import("../pipeline/trioforge/site/static/ui/weights.js") });
  return { app, engine, asked };
}

async function solved(t, kit) {
  $("#buffs-own").checked = true;
  change($("#buffs-own"));
  await t.app.whenIdle();
  const details = $("#assume-weights");
  details.open = true;
  details.dispatchEvent(new Event("toggle"));
  await t.app.whenIdle();
  const slider = $("#w-0-2");
  slider.checked = true;
  change(slider);
  await vi.waitFor(() => expect(t.engine.runs).toHaveLength(1), { timeout: 4000, interval: 10 });
  t.engine.runs[0].finish(result(kit));
  await vi.waitFor(() => expect($("#solve h3")?.textContent).toBe("Solved for your settings"));
}

describe("the rows of an answer of the optimizer", () => {
  const doc = shardFile("wiki-own");
  const places = [...doc.pl].map((char) => decode(doc.icons, char));

  it("show the picture the list of the site gives the item, as its shard and its page do, and the place's for an item with none in a worn place", async () => {
    const t = open((good) => good);
    await solved(t, kitWith([PRIMARY, "w90997@4"], [CHEST, "w90996@4"]));
    expect($$("#kit-body [data-f=\"name\"]")[PRIMARY].textContent).toBe("Reaver of Test Fields");
    expect(pictureOf(rows()[PRIMARY])).toBe("icon-axe-2h");
    expect(pictureOf(rows()[CHEST])).toBe(places[CHEST]); // (the blade has no picture of its own: a worn place shows its own, whatever the blade fits)
    expect(t.asked).toEqual(["/data/item-icons.json"]); // once, with the item table
    for (const row of rows()) expect(row.querySelectorAll("th > span.art").length).toBeLessThanOrEqual(1);
  });

  it("show the pouch, and no sword, in the main hand for the blade that has no picture of its own", async () => {
    const t = open((good) => good);
    await solved(t, kitWith([PRIMARY, "w90996@4"]));
    expect(pictureOf(rows()[PRIMARY])).toBe(POUCH); // (a held place has the item's own picture, else the pouch)
  });

  it.each([
    ["2", POUCH], // an item that fits a held place and has no picture of its own: the pouch
    ["3", "icon-chest"], // a robe: the picture of its page heading
    ["-", null], // an item of two places of two pictures: none, as its page heading
  ])("draw an any row from the character the list has for the item (%s): %s, as the page and the shard do", async (code, want) => {
    const t = open((good) => ({ ...good, icons: [...good.icons, POUCH, "icon-chest"], ic: good.ic.slice(0, -1) + code }));
    await solved(t, kitWith([ANY, "w90996@4"], [19, "w90996@4"], [PRIMARY, "w90996@4"]));
    expect(pictureOf(rows()[ANY])).toBe(want);
    expect(pictureOf(rows()[19])).toBe(want);
    expect(pictureOf(rows()[PRIMARY])).toBe(want ?? POUCH); // (the main hand has the item's character, else the pouch: only an item that fits it stands there)
  });

  it.each([
    ["is for another table", (good) => ({ ...good, items: "0".repeat(64) })],
    ["is for another release", (good) => ({ ...good, release: "data-2020-01-01" })],
    ["has a character too few", (good) => ({ ...good, ic: good.ic.slice(1) })],
    ["has a name with markup", (good) => ({ ...good, icons: ['icon-x"><i>'] })],
    ["is not there", () => ({ ok: false, status: 404 })],
    ["is not a list", () => "not a list"],
  ])("keep the picture of a worn place and show the pouch in a held place, for items they do not know, when the list %s", async (_, serve) => {
    const t = open(serve);
    await solved(t, kitWith([PRIMARY, "w90997@4"], [CHEST, "w90996@4"]));
    expect($$("#kit-body [data-f=\"name\"]")[PRIMARY].textContent).toBe("Reaver of Test Fields"); // (the answer is drawn all the same)
    expect(pictureOf(rows()[PRIMARY])).toBe(POUCH); // (not knowing what it is, a held place draws the pouch: no sword stands in)
    expect(pictureOf(rows()[CHEST])).toBe(places[CHEST]); // (a worn place still shows its own picture: the page never takes one away from a worn place)
    expect(pictureOf(rows()[FACE])).toBe(places[FACE]);
  });

  it("show an any row of an item the list does not know as none (it may be a robe), where a held place shows the pouch", async () => {
    const t = open(() => ({ ok: false, status: 404 }));
    await solved(t, kitWith([ANY, "w90996@4"], [19, "w90997@4"], [PRIMARY, "w90996@4"]));
    expect(pictureOf(rows()[ANY])).toBeNull();
    expect(pictureOf(rows()[19])).toBeNull();
    expect(pictureOf(rows()[PRIMARY])).toBe(POUCH);
  });
});
