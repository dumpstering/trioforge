// The pictures of the rows of Wear this in a real browser (Chromium), served by `wrangler pages dev` with the production headers.
//
// A test without @once in its title runs in four views: a 1280 px and a 360 px wide window, each with the system in light and in dark mode (see playwright.config.mjs).
//
// What a row shows beside the name of its place is checked against the data file the page is built with (a reader of our own: the characters of `ic` and `pl` are decoded here, not by the page's
// code), when the page arrives and after the view is drawn again in the browser, and against the page of the item (the same item has the same picture there).

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DATA, TRIO, expect, open, openSwitches, pick, test } from "./support.mjs";

/** The characters of a file, taken from the page code's own file (pipeline/tests/test_site_icons.py holds that string to the generator's): a copy typed here would go stale the next time a character is added. */
const SHARD_JS = resolve(dirname(fileURLToPath(import.meta.url)), "../pipeline/trioforge/site/static/shard.js");
const DIGITS = /^const ICON_DIGITS = "([^"]+)";$/m.exec(readFileSync(SHARD_JS, "utf8"))[1];
const name = (names, char) => (char === "-" ? null : names[DIGITS.indexOf(char)]);
const HELD = [17, 18, 19, 20, 21]; // the range, the two any slots, the main hand and the off hand: places that hold something
const ANYS = [18, 19]; // the two any slots take whatever fits: the file has no picture for them and the item's own character decides
const POUCH = "icon-pouch";
/** The thirteen pictures of the held things and the pouch: they stay on a held row (written here again, not taken from the page's code). */
const HELD_PICTURES = ["idol", "stone", "horn", "lantern", "cup", "scroll", "rod", "whip", "claw", "pick", "polearm", "charm", ["fishing", "pole"].join("-"), "pouch"].map((name) => `icon-${name}`); // (the two words are joined: a name of a real item may not stand in a file of the fixture or the specs)
/** The part of the body a picture of armor, or of the place of a part, is of (`icon-chest-plate`, `icon-chest`), or null: written here again, not taken from the page's code. */
const armorOf = (picture) => /^icon-(helm|chest|arms|legs|feet|hands)(?:-|$)/.exec(picture ?? "")?.[1] ?? null;

/**
 * What the published shard says of the pictures: for each item (by its key and by its name) its character (its own picture, else the pouch if it fits a held place, else the picture of its page heading), and
 * the picture of each of the 22 places (the pouch for the range, the main hand and the off hand, none for an any slot). A row in a worn place shows the item's own picture, else the place's, and never a
 * picture of the held things, which stay on a held row; a row in a held place the item's character, else the place's (the pouch), none when it is empty; a picture of armor stays in its own part's place.
 */
function readPictures(doc) {
  const byKey = new Map();
  const byName = new Map();
  doc.items.forEach((item, index) => {
    const pictures = { own: name(doc.icons, doc.ic[index]) };
    byKey.set(item[0], pictures);
    byName.set(item[1], pictures);
  });
  expect(doc.sl, "a shard carries no third character for an item").toBeUndefined();
  const places = [...doc.pl].map((char) => name(doc.icons, char));
  for (const index of HELD) expect(places[index], "the range, the main hand and the off hand have the pouch, an any slot none").toBe(ANYS.includes(index) ? null : POUCH);
  expect([...byKey.values()].some((pictures) => pictures.own === POUCH), "an item that fits a held place and has no picture of its own has the pouch").toBe(true);
  return { byKey, byName, places };
}

/** The rows of the kit as the page shows them: the picture beside the place ("icon-chest" or null, and how many pictures the cell holds) and the item's name and key. */
function readRows(page) {
  return page.$$eval("#kit-body tr", (rows) =>
    rows.map((tr) => {
      const cell = tr.querySelector("th");
      const marks = [...cell.querySelectorAll("span.art")];
      const link = tr.querySelector('[data-f="name"] a');
      return {
        picture: marks.length === 0 ? null : ([...marks[0].classList].find((c) => c.startsWith("art-icon-")) ?? "").slice(4),
        marks: marks.length,
        first: cell.firstElementChild === marks[0],
        name: tr.querySelector('[data-f="name"]').textContent,
        key: link === null ? null : link.getAttribute("href").split("/").filter(Boolean).pop(),
        hidden: marks.every((mark) => mark.getAttribute("aria-hidden") === "true" && mark.textContent === "" && !mark.hasAttribute("style")),
      };
    }),
  );
}

async function pictures(page, request) {
  const ev = await page.locator("main").getAttribute("data-ev");
  const response = await request.get(`${DATA}${ev}-own.json`);
  expect(response.status()).toBe(200);
  return readPictures(await response.json());
}

/** What each row should show: in a held place the item's character, else the place's (the pouch; none in an any slot) and none when it is empty; in a worn place the item's own, else the place's (a picture of the held things never, an armor picture only in its own part's place). */
function expected(rows, known) {
  return rows.map((row, index) => {
    const found = row.key !== null && known.byKey.has(row.key) ? known.byKey.get(row.key) : (known.byName.get(row.name) ?? null);
    const own = found === null ? null : found.own;
    const place = known.places[index];
    if (HELD.includes(index)) return found === null ? null : (own ?? place); // (an empty held place has none)
    if (own === null || HELD_PICTURES.includes(own)) return place;
    return armorOf(own) !== null && armorOf(own) !== armorOf(place) ? place : own;
  });
}

test("the rows of Wear this show the picture of their item, or of their place, as the data says, and a view drawn in the browser does the same", async ({ page, request, watch }) => {
  await open(page, TRIO);
  const known = await pictures(page, request);
  let rows = await readRows(page);
  expect(rows).toHaveLength(22);
  expect(rows.map((row) => row.picture)).toEqual(expected(rows, known));
  expect(rows.every((row) => row.marks <= 1 && row.hidden && (row.marks === 0 || row.first))).toBe(true);
  expect(rows.some((row, index) => HELD.includes(index) && row.picture === POUCH), "the pouch is on a held row of an item with no picture of its own").toBe(true);
  const baked = rows.map((row) => row.picture);
  expect(baked.some((picture, index) => picture !== known.places[index]), "an item's own picture is among them").toBe(true);
  expect(baked.every((picture) => picture === null || /^icon-[a-z0-9]+(-[a-z0-9]+)*$/.test(picture))).toBe(true);

  await openSwitches(page);
  const shownRole = page.locator('[data-f="v-role"]').first(); // (the page says which role the table is drawn for, once it is)
  const first = await shownRole.textContent();
  const other = (await page.locator('input[name="role"]').evaluateAll((radios) => radios.map((radio) => radio.value))).find((value) => value !== "balanced") ?? "balanced";
  await pick(page, `role-${other}`);
  await expect(shownRole).not.toHaveText(first ?? "");
  const now = await readRows(page);
  expect(now.map((row) => row.picture)).toEqual(expected(now, known)); // the rows drawn in the browser have the pictures the data gives their items
  expect(now.every((row) => row.marks <= 1 && row.hidden)).toBe(true);

  await pick(page, "role-balanced");
  await expect(shownRole).toHaveText(first ?? "");
  expect((await readRows(page)).map((row) => row.picture)).toEqual(baked); // and back to the pictures the page was made with
  expect(watch.problems()).toEqual([]);
});

test("the picture beside an item in Wear this is the picture on the page of that item", async ({ page, request }) => {
  await open(page, TRIO);
  const known = await pictures(page, request);
  const rows = await readRows(page);
  const shown = rows.filter((row) => row.key !== null && row.picture !== null);
  const owned = shown.filter((row) => known.byKey.get(row.key)?.own === row.picture && row.picture !== POUCH); // (the picture is the item's own, or the one its page heading has: an any row of a robe)
  const placed = shown.filter((row) => known.byKey.get(row.key)?.own === null || known.byKey.get(row.key)?.own === POUCH); // (the picture is its place's, or the pouch of an item that fits a held place: its page has the pouch, or none for an item of both places)
  expect(owned.length, "an item's own picture is among them").toBeGreaterThan(0);
  expect(placed.length, "a place's picture is among them").toBeGreaterThan(0);
  // the page of an item has its own picture, the same as its row; of an item with none the place's picture, only where every place the item fits is one worn place of one picture, and else none
  for (const row of owned.slice(0, 4)) {
    await page.goto(`/item/${row.key}/`);
    await expect(page.locator("main")).toHaveAttribute("data-page", "item");
    const marks = page.locator("h1 > span.art");
    await expect(marks).toHaveCount(1);
    await expect(marks).toHaveClass(new RegExp(`(^| )art-${row.picture}( |$)`));
    await expect(marks).toHaveAttribute("aria-hidden", "true");
  }
  for (const row of placed.slice(0, 4)) {
    await page.goto(`/item/${row.key}/`);
    await expect(page.locator("main")).toHaveAttribute("data-page", "item");
    const marks = page.locator("h1 > span.art");
    const count = await marks.count();
    expect(count).toBeLessThanOrEqual(1);
    if (count === 1) await expect(marks).toHaveClass(new RegExp(`(^| )art-${row.picture}( |$)`)); // (never another picture than the row's)
  }
});

test("a place without a picture keeps the room of one, so that a picture that comes or goes moves nothing @once", async ({ page }) => {
  await open(page, TRIO);
  const boxes = await page.evaluate(() => {
    const rows = [...document.querySelectorAll("#kit-body tr")];
    const withMark = rows.map((tr) => tr.querySelector("th > span.art")).find((span) => span !== null);
    const without = rows.map((tr) => tr.querySelector("th")).find((th) => th.querySelector(":scope > span.art") === null);
    const mark = getComputedStyle(withMark);
    const room = getComputedStyle(without, "::before");
    const box = (style) => ({ width: style.width, height: style.height, margin: style.marginInlineEnd, border: style.borderTopWidth, boxSizing: style.boxSizing });
    return { mark: box(mark), room: box(room), have: without !== null };
  });
  expect(boxes.have, "the page has a place without a picture (an any slot)").toBe(true);
  expect(boxes.room).toEqual(boxes.mark); // the same box: a picture put in its place fills it
  expect(parseFloat(boxes.mark.width)).toBeGreaterThanOrEqual(32);
});
