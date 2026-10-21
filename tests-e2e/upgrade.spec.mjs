// The Upgrade section of the trio page in a real browser (Chromium), served by `wrangler pages dev` with the production headers (Trusted Types and the content security policy
// included): a file of /outputfile inventory dropped on the section or chosen with the file input, the picker used with the keyboard alone, the choices a name that is close needs,
// the notice when the data of the site is newer than the page, and the accessibility checks in the four views.
//
// The code of the section is a chunk of its own, loaded the first time the section is used; the file is read in the browser and nothing of it is sent anywhere. The dumps are those
// of the invented items of the site fixture (fixtures/dumps/site-*.txt), so the tests that read them are skipped on real results (TRIOFORGE_RESULTS), whose items have other
// names; the ones that need no name run on both.
//
// A test without @once in its title runs in the four views (a 1280 px and a 360 px wide window, in light and in dark).

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { encodeKit } from "../pipeline/trioforge/site/static/input/kitcode.js";
import { decodeKit } from "../pipeline/trioforge/site/static/input/kitdecode.js";
import { ROOT, TRIO, axe, expect, madeFrom, open, openSwitches, pick, tabTo, test } from "./support.mjs";

const REAL_RESULTS = "the dumps are made of the synthetic fixture's items, which real results do not have";
/** The file as /outputfile inventory writes it: CRLF line ends (git keeps the fixtures with LF). */
const dump = (name) => readFileSync(resolve(ROOT, "fixtures", "dumps", `${name}.txt`), "latin1").split("\r\n").join("\n").split("\n").join("\r\n");
/** The name of the file stands for a character and a server: it must be shown nowhere, and kept nowhere. */
const SECRET = "Zorbwick-faketown-inventory.txt";

/** What a dump of the site fixture gives: name, tier, how many, where. */
const SITE_SMALL = [
  ["Band of Quiet Lanterns", "+4", "", "worn"],
  ["Bracer of the Iron Oath", "+0", "", "worn"],
  ["Breastplate of Warding", "+4", "", "worn"],
  ["Choker of the Deep", "+0", "", "worn"],
  ["Gauntlets of Endless Wrath", "+1", "", "in the shared bank"],
  ["Helm of the Stoneward", "+4", "2 copies", "worn, in the bank"],
  ["Larkspur Pauldrons", "+4", "", "in a bag"],
  ["Mask of the Weary", "+0", "", "on the key ring"],
  ["Pellbrook Mallet", "+3", "", "worn"],
  ["Rune-etched Earring", "+2", "2 copies", "worn ×2"],
  ["Tinker's Awl", "+0", "", "in a bag"],
  ["Vambraces of Might", "+1", "", "worn"],
];

/** Drop a file on the drop zone the way a browser does: it enters, it moves over, it is dropped. */
async function dropFile(page, text, name = SECRET) {
  const dataTransfer = await page.evaluateHandle(
    ([content, fileName]) => {
      const transfer = new DataTransfer();
      transfer.items.add(new File([content], fileName, { type: "text/plain" }));
      return transfer;
    },
    [text, name],
  );
  for (const type of ["dragenter", "dragover", "drop"]) await page.dispatchEvent("#upgrade-drop", type, { dataTransfer });
}

/**
 * A file and then a text dragged over the page outside the section: is each drag cancelled (a browser opens a file that is dropped on a page, in place of the page, unless the
 * page cancels the drag), and what drop effect did the page ask for? (An event made by a script never navigates, so what a test can ask is whether the page refuses the drag.)
 */
function dragOutside(page) {
  return page.evaluate(() => {
    const record = (transfer) => {
      const asked = { effect: "none" };
      Object.defineProperty(transfer, "dropEffect", { get: () => asked.effect, set: (value) => (asked.effect = value) }); // (a transfer made by a script cannot be given an effect: this one takes it)
      return asked;
    };
    const file = new DataTransfer();
    file.items.add(new File(["x"], "outside.txt", { type: "text/plain" }));
    const text = new DataTransfer();
    text.setData("text/plain", "some words");
    const fileEffect = record(file);
    const textEffect = record(text);
    textEffect.effect = "copy";
    const target = document.querySelector("h1");
    const cancelled = (type, transfer) => !target.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: transfer }));
    return {
      fileDragover: cancelled("dragover", file),
      fileDrop: cancelled("drop", file),
      fileEffect: fileEffect.effect,
      textDragover: cancelled("dragover", text),
      textDrop: cancelled("drop", text),
      textEffect: textEffect.effect,
    };
  });
}

const readRows = (page) =>
  page.$$eval("#upgrade-owned > li", (items) =>
    items.map((li) => [
      li.querySelector(".owned-name").textContent,
      li.querySelector(".owned-tier").textContent,
      li.querySelector(".owned-count")?.textContent ?? "",
      li.querySelector(".owned-where").textContent,
    ]),
  );

/** Everything the page asked for, by address: the section is checked by what it fetches and what it does not. */
function watchRequests(page) {
  const seen = [];
  page.on("request", (request) => seen.push({ method: request.method(), url: new URL(request.url()), body: request.postData() }));
  return seen;
}
const paths = (seen) => seen.map((request) => request.url.pathname);

// ---- loaded when it is used -------------------------------------------------------------------------------------------------------------------

test("the code of the section and the item list are fetched when the section is first used, and not before @once", async ({ page, watch }) => {
  const seen = watchRequests(page);
  await open(page, TRIO);
  expect(paths(seen).filter((path) => /upgrade-input|engine-manifest|\/assets\/engine\//.test(path)), "nothing of the section before it is used").toEqual([]);
  await expect(page.locator("#upgrade-add")).toBeDisabled();
  await page.locator("#upgrade-pick").focus();
  await expect(page.locator("#upgrade-add")).toBeEnabled();
  const after = paths(seen);
  expect(after.filter((path) => /^\/assets\/upgrade-input-[A-Z0-9]{8}\.js$/.test(path))).toHaveLength(1);
  expect(after.filter((path) => path === "/engine-manifest.json")).toHaveLength(1);
  expect(after.filter((path) => /^\/assets\/engine\/data\/items-[A-Z0-9]{16}\.json$/.test(path))).toHaveLength(1);
  expect(after.filter((path) => /\/assets\/engine\/(client|worker|highs)-/.test(path)), "the optimizer itself is not asked for by an input").toEqual([]);
  expect(watch.problems()).toEqual([]);
});

// ---- the file ------------------------------------------------------------------------------------------------------------------------------

test("a file dropped on the section is read in the browser: the list shows what is owned, at which tier, how many and where, and nothing is sent or kept @once", async ({ page, watch }) => {
  test.skip(Boolean(process.env.TRIOFORGE_RESULTS), REAL_RESULTS);
  const seen = watchRequests(page);
  await open(page, TRIO);
  await dropFile(page, dump("site-small")); // (the first thing the visitor does: the code and the item list come meanwhile)
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(SITE_SMALL.length);
  expect(await readRows(page)).toEqual(SITE_SMALL);
  await expect(page.locator("#announce")).toHaveText("12 items read, 1 not in the catalog.");
  await expect(page.locator("#upgrade-count")).toHaveText("(12)");
  await expect(page.locator("#upgrade-unknown summary")).toHaveText("Not in the catalog (1)");

  // nothing of the file left the page, and the page keeps nothing of it
  expect(seen.length).toBeGreaterThan(0);
  for (const request of seen) {
    expect(request.method, `${request.url.pathname} is a read`).toBe("GET");
    expect(request.body).toBeNull();
    for (const piece of ["Stoneward", "Larkspur Pauldrons", "Tin Flask", "520002"]) expect(decodeURIComponent(request.url.href)).not.toContain(piece);
  }
  const html = await page.content();
  for (const part of ["Zorbwick", "faketown", SECRET]) expect(html, `the file name (${part}) is shown nowhere`).not.toContain(part);
  const kept = await page.evaluate(async () => ({
    local: localStorage.length,
    session: sessionStorage.length,
    cookie: document.cookie,
    databases: indexedDB.databases ? (await indexedDB.databases()).length : 0,
  }));
  expect(kept).toEqual({ local: 0, session: 0, cookie: "", databases: 0 });
  expect(watch.problems()).toEqual([]);
});

test("a file dragged over the page outside the section is refused, so that the browser does not open it in place of the page; a text or a link is left alone @once", async ({ page, watch }) => {
  await open(page, TRIO);
  // (a file dropped elsewhere than on the section would be opened in place of the page, the gear entered would be lost, and the name of the file, which the game gives after the character
  // and the server, would be in the address and the history)
  expect(await dragOutside(page)).toEqual({ fileDragover: true, fileDrop: true, fileEffect: "none", textDragover: false, textDrop: false, textEffect: "copy" });
  await page.locator("#upgrade-pick").focus(); // and the same once the code of the section is in
  await expect(page.locator("#upgrade-add")).toBeEnabled();
  expect(await dragOutside(page)).toEqual({ fileDragover: true, fileDrop: true, fileEffect: "none", textDragover: false, textDrop: false, textEffect: "copy" });
  expect(watch.problems()).toEqual([]);
});

test("the file input takes a file too, and a keyboard opens its chooser from the drop zone @once", async ({ page, watch }) => {
  test.skip(Boolean(process.env.TRIOFORGE_RESULTS), REAL_RESULTS);
  await open(page, TRIO);
  await page.locator("#upgrade-file").focus(); // (the keyboard's way in: the drop zone is a label for it)
  const chooser = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  await (await chooser).setFiles({ name: SECRET, mimeType: "text/plain", buffer: Buffer.from(dump("site-small"), "latin1") });
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(SITE_SMALL.length);
  expect(await readRows(page)).toEqual(SITE_SMALL);
  expect(await page.evaluate(() => document.getElementById("upgrade-file").value)).toBe("");
  await expect(page.locator("body")).not.toContainText("Zorbwick");
  expect(watch.problems()).toEqual([]);
});

test("a file the parser refuses is answered in the parser's words, and the list stays as it was @once", async ({ page, watch }) => {
  await open(page, TRIO);
  await page.locator("#upgrade-pick").focus();
  await expect(page.locator("#upgrade-add")).toBeEnabled();
  await page.setInputFiles("#upgrade-file", { name: SECRET, mimeType: "text/plain", buffer: Buffer.from("this is not an inventory dump\r\n") });
  await expect(page.locator("#upgrade-note")).toHaveText("This is not an inventory dump: the first line is not the expected header; re-run /outputfile inventory.");
  await expect(page.locator("#announce")).toHaveText(await page.locator("#upgrade-note").textContent());
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("Zorbwick");
  expect(watch.problems()).toEqual([]);
});

test("a name that is close to an item's is offered and never taken: Choose adds it, the rest of the list does not wait @once", async ({ page, watch }) => {
  test.skip(Boolean(process.env.TRIOFORGE_RESULTS), REAL_RESULTS);
  await open(page, TRIO);
  await dropFile(page, dump("site-mixed"));
  const banner = page.locator("#upgrade-banner");
  await expect(banner).toBeVisible();
  expect(await banner.evaluate((node) => node.hasAttribute("role") || node.hasAttribute("aria-live")), "the page has two live regions, and the banner is not a third").toBe(false);
  await expect(page.locator("#upgrade-banner-text")).toHaveText("2 items need a choice. 3 items are not in the catalog.");
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(4); // what matched is there while the two wait
  await expect(page.locator("#announce")).toHaveText("4 items read, 2 need a choice, 3 not in the catalog.");
  const choices = page.locator("#upgrade-banner .choice");
  await expect(choices).toHaveCount(2);
  await expect(choices.first().locator(".choice-name")).toHaveText('"Millrace pavise" is close to this item:');
  await expect(choices.first().locator(".choice-desc")).toHaveText("Millrace Pavise · Secondary · AC 19, STR 6 · w80869");
  // the keyboard: the Choose button takes the focus, Enter chooses, and the focus goes to the next choice
  await choices.first().getByRole("button", { name: /^Choose/ }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#upgrade-banner-text")).toHaveText("1 item needs a choice. 3 items are not in the catalog.");
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(5);
  expect(await page.evaluate(() => document.activeElement.closest(".choice") !== null && document.activeElement.textContent)).toBe("Choose");
  await page.locator("#upgrade-banner .choice button").first().click();
  await expect(banner.locator(".choice")).toHaveCount(0);
  await expect(page.locator("#upgrade-banner-text")).toHaveText("3 items are not in the catalog.");
  expect((await readRows(page)).map((row) => row[0])).toEqual(["Breastplate of Warding", "Choker of the Deep", "Helm of the Stoneward", "Larkspur Pauldrons", "Millrace Pavise", "Tinker's Awl"]);
  await expect(page.locator("#upgrade-unknown li")).toHaveText(["Tin Flask ×20", "Dented Thimble ×3", "Cracked Whistle"]);
  expect(watch.problems()).toEqual([]);
});

test("when the code of the section cannot be fetched, the section says so near its controls with one Reload button, and a reload brings the section @once", async ({ page, watch }) => {
  const chunk = "**/assets/upgrade-input-*.js";
  await page.route(chunk, (route) => route.abort());
  await open(page, TRIO);
  await page.locator("#upgrade-pick").focus();
  const words = "Couldn't load the Upgrade section. Reload the page to try again.";
  const line = page.locator("#upgrade-load");
  await expect(line.locator(".status-text")).toHaveText(words);
  await expect(page.locator("#status .status-text"), "the page's status at the top is far from the section").toHaveCount(0);
  await expect(page.locator("#announce"), "and a visitor who cannot see the page is told").toHaveText(words);
  expect(await page.evaluate(() => document.getElementById("upgrade-load").hasAttribute("role") || document.getElementById("upgrade-load").hasAttribute("aria-live"))).toBe(false);
  await expect(line.getByRole("button"), "one button, and it is not a Try again: the browser keeps a failed module fetch until the page is reloaded").toHaveText("Reload");

  // the network is back, and the browser would still not fetch the code again: the button reloads the page, and the section works
  await page.unroute(chunk);
  await Promise.all([page.waitForEvent("load"), line.getByRole("button", { name: "Reload" }).click()]);
  await page.locator("#upgrade-pick").focus();
  await expect(page.locator("#upgrade-add")).toBeEnabled();
  await expect(line.locator(".status-text")).toHaveCount(0);
  expect(watch.problems(["console", "requestfailed"])).toEqual([]);
});

// ---- the picker --------------------------------------------------------------------------------------------------------------------------------

test("the picker is used with the keyboard alone: type, the arrows, Enter, the tier, Add, and Remove @once", async ({ page, watch }) => {
  test.skip(Boolean(process.env.TRIOFORGE_RESULTS), REAL_RESULTS);
  await open(page, TRIO);
  await tabTo(page, "#upgrade-pick", 160); // (the section is reached by Tab from the top of the page, through the file input)
  await expect(page.locator("#upgrade-add")).toBeEnabled();
  const input = page.locator("#upgrade-pick");
  await page.keyboard.type("lark");
  await expect(input).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator('#upgrade-list [role="option"]')).toHaveText(["Larkspur Pauldrons Shoulders"]);
  await expect(page.locator("#announce"), "when the typing pauses, a visitor who cannot see the list is told how many items match").toHaveText("1 item matches");
  await page.keyboard.press("ArrowDown");
  const option = page.locator('#upgrade-list [role="option"]').first();
  await expect(option).toHaveAttribute("aria-selected", "true");
  expect(await input.getAttribute("aria-activedescendant")).toBe(await option.getAttribute("id"));
  expect(await page.evaluate(() => document.activeElement.id), "the focus of the page stays in the text box").toBe("upgrade-pick");
  await page.keyboard.press("Enter");
  await expect(input).toHaveValue("Larkspur Pauldrons");
  await expect(input).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Tab"); // the tier
  expect(await page.evaluate(() => document.activeElement.id)).toBe("upgrade-tier");
  for (let i = 0; i < 4; i += 1) await page.keyboard.press("ArrowDown");
  await expect(page.locator("#upgrade-tier")).toHaveValue("4");
  await page.keyboard.press("Tab"); // Add
  expect(await page.evaluate(() => document.activeElement.id)).toBe("upgrade-add");
  await page.keyboard.press("Enter");
  expect(await readRows(page)).toEqual([["Larkspur Pauldrons", "+4", "", "added by hand"]]);
  await expect(page.locator("#announce")).toHaveText("Added Larkspur Pauldrons +4.");
  expect(await page.evaluate(() => document.activeElement.id), "the focus is back in the text box, which is empty").toBe("upgrade-pick");
  await expect(input).toHaveValue("");
  // Escape: closes the list and keeps the text; with the list closed it clears the text
  await page.keyboard.type("hel");
  await expect(input).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(input).toHaveAttribute("aria-expanded", "false");
  await expect(input).toHaveValue("hel");
  await page.keyboard.press("Escape");
  await expect(input).toHaveValue("");
  // the same item again adds to its count
  await page.keyboard.type("larkspur pauldrons");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await page.keyboard.press("Enter"); // the item is chosen and the list is closed: Enter adds it, at the tier that is set (+4 still)
  expect(await readRows(page)).toEqual([["Larkspur Pauldrons", "+4", "2 copies", "added by hand"]]);
  await expect(page.locator("#announce")).toHaveText("Added Larkspur Pauldrons +4, now 2 copies.");
  // Remove with the keyboard: it is the fourth Tab from the text box (the tier, Add, Clear, Remove), and the focus stays in the list
  for (let i = 0; i < 4; i += 1) await page.keyboard.press("Tab");
  expect(await page.evaluate(() => document.activeElement.textContent)).toBe("Remove");
  await page.keyboard.press("Enter");
  expect(await readRows(page)).toEqual([]);
  expect(await page.evaluate(() => document.activeElement.id), "no row is left: the focus is on the heading of the list").toBe("upgrade-owned-h");
  await expect(page.locator("#upgrade-empty")).toBeVisible();
  expect(watch.problems()).toEqual([]);
});

test("Clear empties the section: the list, the choices and the notes @once", async ({ page, watch }) => {
  test.skip(Boolean(process.env.TRIOFORGE_RESULTS), REAL_RESULTS);
  await open(page, TRIO);
  await dropFile(page, dump("site-mixed"));
  await expect(page.locator("#upgrade-banner")).toBeVisible();
  await page.locator("#upgrade-clear").click();
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(0);
  await expect(page.locator("#upgrade-banner")).toBeHidden();
  await expect(page.locator("#upgrade-clear")).toBeHidden();
  await expect(page.locator("#announce")).toHaveText("Cleared your gear.");
  expect(await page.evaluate(() => document.activeElement.id)).toBe("upgrade-owned-h");
  expect(watch.problems()).toEqual([]);
});

// ---- the data of the site is newer than the page ---------------------------------------------------------------------------------------------------

test("when the data of the site is newer than the page, the page's notice with Reload is shown and none of the item list is used @once", async ({ page, watch }) => {
  const seen = watchRequests(page);
  await page.route("**/engine-manifest.json", async (route) => {
    const response = await route.fetch();
    const manifest = await response.json();
    manifest.data_release = "data-2099-01-01"; // a release the page was not built for
    await route.fulfill({ response, json: manifest });
  });
  await open(page, TRIO);
  await page.locator("#upgrade-pick").focus();
  const status = page.locator("#status");
  await expect(status.locator(".status-text")).toHaveText("Data updated, reload the page to see the new data.");
  await expect(page.locator("#upgrade-load .status-text")).toHaveText("Data updated, reload the page to see this section.");
  await expect(page.locator("#upgrade-load").getByRole("button", { name: "Reload" }), "the section is far from the page's status: it has a Reload of its own").toBeVisible();
  for (const id of ["upgrade-file", "upgrade-pick", "upgrade-tier", "upgrade-add"]) await expect(page.locator(`#${id}`), `#${id} has nothing behind it now`).toBeDisabled();
  await expect(page.locator("#upgrade-load").getByRole("button", { name: "Reload" }), "the focus was on the picker, which is off now: it is on the button").toBeFocused();
  await dropFile(page, "this file is not read at all"); // a file dropped now is answered with the same words, and kept nowhere
  await expect(page.locator("#announce")).toHaveText("Data updated, reload the page to see this section.");
  expect(paths(seen).filter((path) => /\/assets\/engine\/data\//.test(path)), "the item list is not asked for").toEqual([]);
  await page.keyboard.type("lark");
  await expect(page.locator("#upgrade-list")).toBeHidden();
  await page.unroute("**/engine-manifest.json");
  await Promise.all([page.waitForEvent("load"), status.getByRole("button", { name: "Reload" }).click()]);
  await page.locator("#upgrade-pick").focus();
  await expect(page.locator("#upgrade-add")).toBeEnabled();
  await expect(status.locator(".status-text")).toHaveCount(0);
  expect(watch.problems()).toEqual([]);
});

// ---- accessibility, in the four views ---------------------------------------------------------------------------------------------------------

/** Put the section into a state with something in each part: a list with rows, a banner with its choices and its names, and (when asked) an open list of options. */
async function furnish(page) {
  if (process.env.TRIOFORGE_RESULTS) {
    // real results: the items are theirs, and none is named here
    await page.locator("#upgrade-pick").focus();
    await expect(page.locator("#upgrade-add")).toBeEnabled();
    for (let i = 0; i < 2; i += 1) {
      await page.keyboard.type("a");
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("Enter");
      await page.keyboard.press("Enter");
    }
    await expect(page.locator("#upgrade-owned > li").first()).toBeVisible();
  } else {
    await dropFile(page, dump("site-mixed"));
    await expect(page.locator("#upgrade-banner")).toBeVisible();
    await expect(page.locator("#upgrade-owned > li")).toHaveCount(4);
  }
}

test("the section passes the accessibility checks before it is used", async ({ page }, testInfo) => {
  await open(page, TRIO);
  await page.locator("#upgrade").scrollIntoViewIfNeeded();
  await axe(page, testInfo);
});

test("the section passes the accessibility checks with a list, a banner with choices, and the list of options open", async ({ page }, testInfo) => {
  await open(page, TRIO);
  await furnish(page);
  await page.locator("#upgrade-owned-h").scrollIntoViewIfNeeded(); // (on real results there is no banner: the list that the picker made is what is in view)
  await page.locator("#upgrade-pick").focus();
  await page.keyboard.type("a");
  await page.keyboard.press("ArrowDown");
  await expect(page.locator("#upgrade-pick")).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator('#upgrade-list [role="option"]').first()).toBeVisible();
  await axe(page, testInfo);
  await page.keyboard.press("Escape");
  await axe(page, testInfo);
});

test("the section does not make the page wider than the window, and the open list of options stays inside it", async ({ page }) => {
  await open(page, TRIO);
  await furnish(page);
  await page.locator("#upgrade-pick").focus();
  await page.keyboard.type("a");
  await page.keyboard.press("ArrowDown");
  await expect(page.locator('#upgrade-list [role="option"]').first()).toBeVisible();
  const fits = await page.evaluate(() => {
    const list = document.getElementById("upgrade-list").getBoundingClientRect();
    return {
      page: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      list: list.left >= 0 && list.right <= document.documentElement.clientWidth,
    };
  });
  expect(fits).toEqual({ page: true, list: true });
});

test("the drop zone and the controls of the section show where the focus is, when it comes from the keyboard", async ({ page }) => {
  await open(page, TRIO);
  await tabTo(page, "#upgrade-file", 160);
  const ring = await page.evaluate(() => {
    const zone = getComputedStyle(document.getElementById("upgrade-drop"));
    return { style: zone.outlineStyle, width: Number.parseFloat(zone.outlineWidth) };
  });
  expect(ring.style, "the ring is drawn on the drop zone, whose input is invisible").not.toBe("none");
  expect(ring.width).toBeGreaterThanOrEqual(2);
  await expect(page.locator("#upgrade-add")).toBeEnabled(); // (the focus on the file input woke the section: Add can be tabbed to once the item list is in)
  for (const selector of ["#upgrade-pick", "#upgrade-tier", "#upgrade-add"]) {
    await tabTo(page, selector, 4);
    const outline = await page.evaluate((s) => Number.parseFloat(getComputedStyle(document.querySelector(s)).outlineWidth), selector);
    expect(outline, `${selector} shows the focus`).toBeGreaterThanOrEqual(2);
  }
});

// ---- the answer: Equip now, the Next step and the steps after it, worked out by the optimizer in a real worker -----------------------------------------------------

const FIXTURE = !process.env.TRIOFORGE_RESULTS;
/** What the question of the optimizer says, in the results area of the section (it is the client's own question). */
const question = (page) => page.locator("#upgrade-results .engine-consent");
const yes = (page) => question(page).getByRole("button", { name: /^Load the optimizer \(about/ });

/**
 * Make the steps and the result of the optimizer reach the page slowly, one after the other, `window.__tfDelay` ms apart (0: as they come), so that a test can look at a path
 * that is still running, and change the gear while the worker's last messages are still on their way. The worker itself is not touched.
 */
function slowStream(page) {
  return page.addInitScript(() => {
    const Native = window.Worker;
    const own = Object.getOwnPropertyDescriptor(Native.prototype, "onmessage");
    window.__tfDelay = 0;
    window.Worker = class extends Native {
      constructor(...args) {
        super(...args);
        let queue = Promise.resolve();
        Object.defineProperty(this, "onmessage", {
          configurable: true,
          get: () => own.get.call(this),
          set: (handler) =>
            own.set.call(
              this,
              handler === null
                ? null
                : (event) => {
                    const type = event.data && event.data.type;
                    const wait = window.__tfDelay > 0 && (type === "step" || type === "result") ? window.__tfDelay : 0;
                    queue = queue.then(() => (wait > 0 ? new Promise((resolve) => setTimeout(resolve, wait)) : undefined)).then(() => handler.call(this, event));
                  },
            ),
        });
      }
    };
  });
}

/** The first item the picker offers for what is typed, added at +0 `times` times; no item is named (on real results, whose items have other names). */
async function pickFirst(page, typed, times) {
  const input = page.locator("#upgrade-pick");
  await input.focus();
  await expect(page.locator("#upgrade-add")).toBeEnabled();
  for (let i = 0; i < times; i += 1) {
    await page.keyboard.type(typed);
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await page.keyboard.press("Enter");
  }
}

/** The gear a test starts with: the dump of the fixture's items, or on real results two copies of the first item the picker offers for "a". */
async function giveGear(page) {
  if (FIXTURE) await dropFile(page, dump("site-small"));
  else await pickFirst(page, "a", 2);
}

/** Something more, that changes the answer: a better head piece on the fixture; on real results the first item for "b". */
async function giveMore(page) {
  if (FIXTURE) {
    await page.locator("#upgrade-pick").focus();
    await page.keyboard.type("crown of the tribunal");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await page.selectOption("#upgrade-tier", "4");
    await page.locator("#upgrade-add").click();
  } else {
    await pickFirst(page, "b", 1);
  }
}

/** The answer as text, part by part: what a visitor reads. */
const answerText = (page) => page.evaluate(() => ["upgrade-equip", "upgrade-next", "upgrade-then"].map((id) => document.getElementById(id).textContent.replace(/\s+/g, " ").trim()));
const liveRegions = (page) => page.evaluate(() => document.querySelectorAll('#upgrade [role="status"], #upgrade [role="alert"], #upgrade [role="log"], #upgrade [aria-live]').length);

test("a gear list is answered by the optimizer in the browser: the question comes in the section, then Equip now, the Next step and the steps as they arrive, and Stop ends the path @once", async ({ page, watch }) => {
  test.setTimeout(120_000);
  const seen = watchRequests(page);
  await open(page, TRIO);
  // Stop is pressed the moment the first step under Then is drawn, as a visitor's click would be were it fast enough
  await page.evaluate(() => {
    const watcher = new MutationObserver(() => {
      const stop = document.getElementById("upgrade-stop");
      if (stop !== null && document.querySelectorAll("#upgrade-then-list > li").length >= 1) {
        stop.click();
        watcher.disconnect();
      }
    });
    watcher.observe(document.getElementById("upgrade-results"), { childList: true, subtree: true });
  });
  await giveGear(page);

  // nothing is downloaded before the visitor says yes, and the question is asked where the answer will be
  await expect(question(page)).toBeVisible();
  await expect(page.locator("#upgrade-results > .engine-slot > .engine-consent")).toHaveCount(1);
  await expect(page.locator("main > .engine-consent")).toHaveCount(0);
  expect(paths(seen).filter((path) => /\/assets\/engine\/(worker|highs)-/.test(path))).toEqual([]);
  await expect(page.locator("#upgrade-equip")).toBeHidden();
  await expect(page.locator("#upgrade-stop"), "nothing is worked out while the question waits: no Stop").toHaveCount(0);
  await expect(page.locator("#upgrade-progress"), "and no working line").toBeHidden();
  await yes(page).click();

  // Equip now, then the Next step, then the first step under Then, which is where Stop was pressed
  await expect(page.locator("#upgrade-equip")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("#upgrade-end")).toHaveText("Stopped.", { timeout: 60_000 });
  await expect(question(page)).toHaveCount(0); // (the question goes away when the optimizer is ready)
  await expect(page.locator("#upgrade-equip-label")).toHaveText(/^The best kit from the gear you have \(kit value [\d,]+\)\.$/);
  const rows = await page.$$eval("#upgrade-equip tbody tr", (trs) =>
    trs.map((tr) => [tr.querySelector("th").textContent, tr.querySelector(".owned-name")?.textContent ?? tr.querySelector(".muted")?.textContent, tr.querySelector(".equip-where")?.textContent ?? ""]),
  );
  expect(rows).toHaveLength(22);
  if (FIXTURE) {
    // the kit the engine gives for the dump of the invented items, and where the copies it wears but the file does not say are worn are
    expect(rows.filter(([, item]) => item !== "Leave empty")).toEqual([
      ["Head", "Helm of the Stoneward +4", ""],
      ["Face", "Mask of the Weary +0", "on your key ring: move to worn"],
      ["Ear 1", "Rune-etched Earring +2", ""],
      ["Ear 2", "Rune-etched Earring +2", ""],
      ["Neck", "Choker of the Deep +0", ""],
      ["Shoulders", "Larkspur Pauldrons +4", "in your bags: move to worn"],
      ["Arms", "Vambraces of Might +1", ""],
      ["Wrist 1", "Bracer of the Iron Oath +0", ""],
      ["Hands", "Gauntlets of Endless Wrath +1", "in your shared bank: move to worn"],
      ["Finger 1", "Band of Quiet Lanterns +4", ""],
      ["Chest", "Breastplate of Warding +4", ""],
      ["Any slot 1", "Helm of the Stoneward +4", "in your bank: move to worn"],
      ["Main hand", "Tinker's Awl +0", "in your bags: move to worn"],
      ["Off hand", "Pellbrook Mallet +3", ""],
    ]);
    await expect(page.locator("#upgrade-next .step-what")).toHaveText("Get Ferryman's Pike +4");
    await expect(page.locator("#upgrade-next .step-gain")).toHaveText("Gain +435 kit value");
    await expect(page.locator("#upgrade-next .step-source")).toHaveText("Source: The Hole");
    await expect(page.locator("#upgrade-then-list > li").first().locator(".step-what")).toHaveText("Get another Helm of the Stoneward +4");
  }
  await expect(page.locator("#upgrade-next .step-what")).toHaveText(/^(Get|Upgrade your) /);
  await expect(page.locator("#upgrade-next .step-gain")).toHaveText(/^Gain \+[\d,]+ kit value$/);
  const streamed = await page.locator("#upgrade-then-list > li").count();
  expect(streamed, "the first step under Then is where Stop was pressed").toBeGreaterThanOrEqual(1);
  expect(streamed, "and the path ended before its limit (a busy page may take the stop in a step or two late: \"Stopped.\" above says it was taken)").toBeLessThan(7);
  await expect(page.locator("#upgrade-then-label")).toContainText("Each step is the single best addition after the steps before it");
  await expect(page.locator("#upgrade-stop")).toHaveCount(0);
  await expect(page.locator("#upgrade-progress")).toBeHidden();

  // what a visitor who cannot see the page is told: once for the answer and once for the end, through the page's own live region, and the page has the two it had
  await expect(page.locator("#announce")).toHaveText(/^\d+ steps\.$/);
  expect(await liveRegions(page), "the section has no live region of its own").toBe(0);
  expect(await page.$$eval('[role="status"], [aria-live]', (nodes) => nodes.map((node) => node.id))).toEqual(["status", "announce"]);

  // nothing of the gear left the page
  for (const request of seen) {
    expect(request.method, `${request.url.pathname} is a read`).toBe("GET");
    expect(request.body).toBeNull();
    expect(decodeURIComponent(request.url.href)).not.toMatch(/Stoneward|Larkspur|inventory/);
  }
  const html = await page.content();
  for (const part of ["Zorbwick", "faketown", SECRET]) expect(html, `the file name (${part}) is shown nowhere`).not.toContain(part);
  expect(watch.problems()).toEqual([]);
});

test("a change of the gear in the middle of the path draws only the answer for the new gear, as if the new gear had been given alone @once", async ({ page, watch }) => {
  test.setTimeout(240_000);
  await slowStream(page);
  await open(page, TRIO);
  await page.evaluate(() => (window.__tfDelay = 800)); // the worker is done long before the page has had its steps, so the path is still running when the gear changes
  await giveGear(page);
  await yes(page).click();
  const stepsUnderThen = page.locator("#upgrade-then-list > li");
  await expect(stepsUnderThen.first()).toBeVisible({ timeout: 60_000 });
  // the older path is running now: its Stop is there, and nothing of an end has been drawn
  await expect(page.locator("#upgrade-stop")).toBeVisible();
  await expect(page.locator("#upgrade-end")).toHaveText("");
  const before = await answerText(page);

  // From here the page is watched. When the new request goes out the answer goes (Equip now is hidden): what the answer was just before is kept. Between that moment and the new
  // Equip now, nothing of an answer may be drawn (no Next step, no step, no end line); at no time after it may an end line stand while a Stop is there (a result of the older
  // request would be one); and what is said of an answer after it is collected.
  await page.evaluate(() => {
    const q = (id) => document.getElementById(id);
    const state = () => ({ equip: !q("upgrade-equip").hidden, next: !q("upgrade-next").hidden, then: q("upgrade-then-list").children.length, end: q("upgrade-end").textContent, stop: q("upgrade-stop") !== null });
    const seen = { before: state(), sent: false, fresh: false, stale: [], said: [] };
    window.__seen = seen;
    let last = seen.before;
    new MutationObserver(() => {
      const now = state();
      if (!seen.sent) {
        if (now.equip) last = now;
        else {
          seen.sent = true;
          seen.before = last;
        }
      } else if (!seen.fresh) {
        if (now.equip) seen.fresh = true;
        else if (now.next || now.then > 0 || now.end !== "") seen.stale.push(now);
      }
      if (seen.sent && now.end !== "" && now.stop) seen.stale.push(now);
    }).observe(q("upgrade-results"), { childList: true, subtree: true, attributes: true, characterData: true });
    new MutationObserver(() => {
      if (seen.sent) seen.said.push(q("announce").textContent);
    }).observe(q("announce"), { childList: true, subtree: true, characterData: true });
  });
  await giveMore(page);
  await expect(page.locator("#upgrade-equip")).toBeHidden({ timeout: 10_000 }); // (the new request was sent after the pause, and the old answer went)
  await expect(page.locator("#upgrade-end")).toHaveText(/\S/, { timeout: 120_000 });
  await expect(page.locator("#upgrade-stop")).toHaveCount(0);
  const changed = await answerText(page);
  const seen = await page.evaluate(() => window.__seen);
  expect(seen.sent, "the new request was sent").toBe(true);
  expect(seen.before, "the older path was still running when the new request went out: its Stop was there and no end had been drawn").toMatchObject({ stop: true, end: "" });
  expect(seen.before.then, "with steps under Then, and not all of them").toBeGreaterThanOrEqual(1);
  expect(seen.before.then).toBeLessThan(7);
  expect(seen.stale, "nothing of the older request was drawn after the newer one was sent: no step, no result, no end line").toEqual([]);
  const answers = seen.said.filter((text) => /^Equip now|steps?\.$|^Stopped|^Nothing more|^These are|^Couldn't/.test(text));
  expect(answers, "and nothing of it was said: Equip now with the Next step, and the end, once each, for the new request").toHaveLength(2);
  expect(answers[0]).toMatch(/^Equip now is ready: \d+ of 22 places filled\. Next step: /);
  expect(answers[1]).toMatch(/^\d+ steps?\.$/);
  if (FIXTURE) expect(changed, "the new gear gives another answer").not.toEqual(before);

  // the same gear given alone, from nothing, gives the same answer
  await page.evaluate(() => (window.__tfDelay = 0));
  await page.locator("#upgrade-clear").click();
  await expect(page.locator("#upgrade-equip")).toBeHidden();
  await giveGear(page);
  await giveMore(page);
  await expect(page.locator("#upgrade-equip")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("#upgrade-end")).toHaveText(/\S/, { timeout: 90_000 });
  expect(await answerText(page)).toEqual(changed);
  expect(watch.problems()).toEqual([]);
});

test("Stop keeps its place while the steps arrive: Equip now, the Next step and every row under Then come below it @once", async ({ page, watch }) => {
  test.setTimeout(180_000);
  await slowStream(page);
  await open(page, TRIO);
  await page.evaluate(() => (window.__tfDelay = 600));
  await giveGear(page);
  const stop = page.locator("#upgrade-stop");
  await expect(question(page)).toBeVisible();
  await expect(stop, "no Stop while the question waits").toHaveCount(0);
  await yes(page).click();
  await expect(stop, "it comes when the optimizer reports after the yes").toBeVisible({ timeout: 30_000 });
  const top = () => page.evaluate(() => Math.round(document.getElementById("upgrade-stop").getBoundingClientRect().top + window.scrollY));
  await expect(page.locator("#upgrade-next .step-what")).toBeVisible({ timeout: 60_000 });
  await expect(stop).toBeVisible();
  const placed = await top();
  const rows = page.locator("#upgrade-then-list > li");
  await expect(rows.first()).toBeVisible({ timeout: 30_000 });
  const first = await rows.count();
  await expect(rows).toHaveCount(first + 2, { timeout: 30_000 }); // two more rows come under it
  await expect(stop, "the path is still running").toBeVisible();
  expect(await top(), "no row that came pushed Stop down").toBe(placed);
  await page.evaluate(() => (window.__tfDelay = 0));
  await expect(page.locator("#upgrade-end")).toHaveText(/\S/, { timeout: 90_000 });
  expect(watch.problems()).toEqual([]);
});

test("when the visitor does not want the optimizer, the section says so and keeps the gear, and a button asks the question again @once", async ({ page, watch }) => {
  test.setTimeout(120_000);
  const workers = [];
  page.on("worker", (worker) => workers.push(worker));
  await open(page, TRIO);
  await giveGear(page);
  await expect(question(page)).toBeVisible();
  await question(page).getByRole("button", { name: "Not now" }).click();
  await expect(question(page)).toHaveCount(0);
  const line = page.locator("#upgrade-fault");
  await expect(line.locator(".status-text")).toHaveText("The optimizer was not loaded, so there is no answer for your gear yet.");
  await expect(page.locator("#announce")).toHaveText("The optimizer was not loaded, so there is no answer for your gear yet.");
  await expect(page.locator("#upgrade-owned > li").first()).toBeVisible();
  expect(workers, "nothing was downloaded or started").toHaveLength(0);
  expect(await liveRegions(page)).toBe(0);
  await line.getByRole("button", { name: "Load the optimizer" }).click();
  await expect(question(page)).toBeVisible(); // (the client's own question, again)
  await yes(page).click();
  await expect(page.locator("#upgrade-equip")).toBeVisible({ timeout: 60_000 });
  await expect(line).toBeHidden();
  expect(watch.problems()).toEqual([]);
});

test("when Clear empties the section while the question is up, a yes afterwards downloads nothing and leaves no panel, and the next gear is answered without a second question @once", async ({ page, watch }) => {
  test.setTimeout(120_000);
  const seen = watchRequests(page);
  const workers = [];
  page.on("worker", (worker) => workers.push(worker));
  await open(page, TRIO);
  await giveGear(page);
  await expect(question(page)).toBeVisible();
  await page.locator("#upgrade-clear").click(); // the gear is gone while the question is still up
  await yes(page).click(); // (the visitor answers a question about an answer that is not wanted any more)
  await expect(question(page)).toHaveCount(0);
  await page.waitForTimeout(500);
  expect(workers, "no worker was started for it").toHaveLength(0);
  expect(paths(seen).filter((path) => /\/assets\/engine\/(worker|highs)-/.test(path)), "and nothing of the optimizer was downloaded").toEqual([]);
  // the yes stands: the next gear is answered, and nobody is asked again
  await giveGear(page);
  await expect(page.locator("#upgrade-equip")).toBeVisible({ timeout: 60_000 });
  await expect(question(page)).toHaveCount(0);
  expect(workers).toHaveLength(1);
  expect(watch.problems()).toEqual([]);
});

test("the section passes the accessibility checks with the answer on the page: while the steps stream, and when the path has ended", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await slowStream(page);
  await open(page, TRIO);
  await page.evaluate(() => (window.__tfDelay = 700));
  await giveGear(page);
  await expect(question(page)).toBeVisible();
  await axe(page, testInfo); // with the question of the optimizer on the page
  await yes(page).click();
  await expect(page.locator("#upgrade-next .step-what")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("#upgrade-stop")).toBeVisible();
  await page.locator("#upgrade-results").scrollIntoViewIfNeeded();
  await axe(page, testInfo); // Equip now, the Next step, the line of progress and Stop
  await page.evaluate(() => (window.__tfDelay = 0));
  await expect(page.locator("#upgrade-end")).toHaveText(/\S/, { timeout: 90_000 });
  await expect(page.locator("#upgrade-then-list > li").first()).toBeVisible();
  await axe(page, testInfo); // the whole path
});

test("the answer does not make the page wider than the window", async ({ page }) => {
  test.setTimeout(120_000);
  await open(page, TRIO);
  await giveGear(page);
  await yes(page).click();
  await expect(page.locator("#upgrade-end")).toHaveText(/\S/, { timeout: 90_000 });
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
  expect(fits).toBe(true);
});

test("Stop on the sliders takes back their own request and leaves the path of the Upgrade section running, on the one worker @once", async ({ page, watch }) => {
  test.setTimeout(300_000);
  await slowStream(page);
  await recordRequests(page);
  await open(page, TRIO);
  // the sliders first: armor class x2, the question answered for them (it is in their answer area), and the answer drawn
  await openSwitches(page);
  await page.locator("#assume-weights > summary").click();
  await pick(page, "w-0-2");
  await page.locator(".engine-consent").getByRole("button", { name: /^Load the optimizer \(about/ }).click({ timeout: 30_000 });
  await expect(page.locator("#solve h3")).toHaveText("Solved for your settings", { timeout: 90_000 });
  // the gear: the section's path carries the sliders, and its steps reach the page slowly, so that it is on the worker while the tier changes (the section's request does not name the tier)
  await page.evaluate(() => {
    window.__tfDelay = 1500;
  });
  await giveGear(page);
  await expect(page.locator("#upgrade-stop")).toBeVisible({ timeout: 60_000 });
  const steps = () => page.locator("#upgrade-then-list > li").count();
  await expect.poll(steps, { timeout: 60_000 }).toBeGreaterThan(0);
  const drawn = await steps();
  await page.selectOption("#sw-tier", "10");
  await expect(page.locator("#solve")).toContainText("Working out the kit for these settings", { timeout: 20_000 });
  await expect.poll(steps, { timeout: 60_000 }).toBeGreaterThan(drawn); // (a step came, a second and a half apart, after the change: the sliders' request, sent after 300 ms, is queued behind the path)
  await page.locator("#solve").getByRole("button", { name: "Stop" }).click();
  await expect(page.locator("#solve")).toContainText("Stopped.");
  // the path goes on to its end, and says no fault: Stop was the sliders' own
  await page.evaluate(() => {
    window.__tfDelay = 0;
  });
  await expect(page.locator("#upgrade-stop")).toHaveCount(0, { timeout: 150_000 });
  await expect(page.locator("#upgrade-fault"), "the path was not cancelled").toBeHidden();
  await expect(page.locator("#upgrade-end")).not.toHaveText("");
  expect(await startsOf(page), "the worker was not stopped: one start").toBe(1);
  expect((await requested(page)).map((request) => request.mode), "the request for the new tier never reached the worker").toEqual(["best-kit", "farm-path"]);
  expect(watch.problems()).toEqual([]);
});

test("a slider moved while the question of the Upgrade section is open is told where the question is, and its button moves the focus there @once", async ({ page, watch }) => {
  test.setTimeout(120_000);
  await open(page, TRIO);
  await giveGear(page);
  await expect(question(page)).toBeVisible(); // asked for the Upgrade section, far from the sliders
  await openSwitches(page);
  await page.locator("#assume-weights > summary").click();
  await pick(page, "w-0-2");
  await expect(page.locator("#solve .solve-text")).toHaveText("The optimizer is waiting for your answer to the question below.", { timeout: 20_000 });
  await expect(page.locator("#kit")).toHaveCSS("opacity", "0.6"); // (the kit shown is not for these settings)
  await page.locator("#solve").getByRole("button", { name: "Go to the question" }).click();
  await expect(question(page)).toBeFocused();
  await yes(page).click();
  // answered: the line no longer says that the question is awaited (the sliders' request waits behind the section's path, and has nothing to report yet), and says that the work is on
  await expect(page.locator("#solve .solve-text")).toHaveText("Working out the kit for these settings…", { timeout: 20_000 });
  expect(watch.problems()).toEqual([]);
});

// ---- the expanders under the answer: best sets, Every slot and the tier mode --------------------------------------------------------------------------------------

/**
 * Record what the page asks of the optimizer's worker: `window.__tfRequests` holds, in the order they were posted, the mode of each request and what the mode adds to it, and
 * `window.__tfStarts` how many workers were started (each is given one `init` message).
 */
function recordRequests(page) {
  return page.addInitScript(() => {
    window.__tfRequests = [];
    window.__tfStarts = 0;
    const post = Worker.prototype.postMessage;
    Worker.prototype.postMessage = function (data, ...rest) {
      if (data && data.type === "init") window.__tfStarts += 1;
      if (data && data.type === "solve") {
        const { mode, k, tierMode, kit, limit } = data.request;
        window.__tfRequests.push({ mode, k, tierMode, kit: Array.isArray(kit) ? kit.length : undefined, limit });
      }
      return post.call(this, data, ...rest);
    };
  });
}
const requested = (page) => page.evaluate(() => window.__tfRequests);
const startsOf = (page) => page.evaluate(() => window.__tfStarts);
const modesOf = (list) => list.map((request) => (request.k === undefined ? request.mode : `${request.mode}:${request.k}`));

/** The gear given, the question answered, and the path run to its end (it takes a few seconds: `wait` is how long a slow machine is given). */
async function pathEnded(page, wait = 90_000) {
  await giveGear(page);
  await expect(question(page)).toBeVisible();
  await yes(page).click();
  await expect(page.locator("#upgrade-end")).toHaveText(/\S/, { timeout: wait });
  await expect(page.locator("#upgrade-stop")).toHaveCount(0);
}

/** A change in kit value as the answer writes it, as a number ("+1,234", "−56", "+<1"); null for text that has none. */
function amount(text) {
  const found = /([+−])(<1|[\d,]+)/.exec(text ?? "");
  if (found === null) return null;
  const size = found[2] === "<1" ? 0.5 : Number(found[2].replaceAll(",", ""));
  return found[1] === "−" ? -size : size;
}

const openExpander = (page, id) => page.locator(`#${id} > summary`).click();
/** Equip now as a visitor reads it: for each place, what the kit wears. */
const equipOf = (page) => page.$$eval("#upgrade-equip tbody tr", (rows) => rows.map((row) => [row.querySelector("th").textContent, row.querySelector(".owned-name")?.textContent ?? row.querySelector(".muted").textContent]));

test("the expanders come with the answer, closed; each is worked out when it is opened, through the same optimizer, and says so once: best sets, then Every slot @once", async ({ page, watch }) => {
  test.setTimeout(240_000);
  await recordRequests(page);
  await open(page, TRIO);
  await pathEnded(page);

  // they are there with the answer, closed, and nothing of theirs has been asked of the optimizer
  await expect(page.locator("#upgrade-more")).toBeVisible();
  await expect(page.locator("#upgrade-more > details")).toHaveCount(3);
  for (const id of ["upgrade-sets", "upgrade-slots", "upgrade-mode"]) expect(await page.locator(`#${id}`).evaluate((node) => node.open), `${id} is closed`).toBe(false);
  await expect(page.locator("#upgrade-sets > summary")).toHaveText("Best 2 and 3 sets: sets, not a path");
  await expect(page.locator("#upgrade-slots > summary")).toHaveText("Every slot: Swap only this slot");
  await expect(page.locator("#upgrade-mode > summary")).toHaveText("Tier mode: Ready +4");
  expect(modesOf(await requested(page)), "only the path was asked for").toEqual(["farm-path"]);

  // Best 2 and 3 sets: the set of 2 and the set of 3, in that order, and one announcement
  await openExpander(page, "upgrade-sets");
  const sets = page.locator("#upgrade-sets .set");
  await expect(sets).toHaveCount(2, { timeout: 90_000 });
  await expect(page.locator("#announce")).toHaveText("Best 2 and 3 sets are ready.");
  await expect(page.locator("#upgrade-sets > summary"), "the focus stayed on the summary that was opened").toBeFocused();
  expect(modesOf(await requested(page))).toEqual(["farm-path", "best-sets:2", "best-sets:3"]);
  const drawn = await sets.evaluateAll((nodes) =>
    nodes.map((node) => ({
      k: Number(node.dataset.k),
      heading: node.querySelector("h4").textContent,
      difference: node.querySelector(".set-note").textContent,
      additions: [...node.querySelectorAll("ul.steps > li .step-what")].map((what) => what.textContent),
      gain: node.querySelector(".set-gain")?.textContent ?? null,
      other: node.querySelector(".set-other")?.textContent ?? null,
    })),
  );
  expect(drawn.map((set) => [set.k, set.heading])).toEqual([[2, "Best set of 2"], [3, "Best set of 3"]]);
  for (const set of drawn) {
    expect(set.difference).toBe(`The best ${set.k} additions made at once; the path adds one at a time, so its first ${set.k} steps can differ.`);
    for (const what of set.additions) expect(what).toMatch(/^(Get|Get another|Upgrade your) /);
    if (set.additions.length > 0) expect(set.gain).toMatch(/^Gain over Equip now: \+(<1|[\d,]+) kit value( \(.+\))?$/);
    else expect(set.other).toBeTruthy();
  }
  // the best k additions made at once are worth at least what the path's first k steps add one at a time (the best set can always be those steps), so a set that is below them is wrong.
  // The figures are rounded half up, each step and each set: the sum of k steps may be half a unit a step out, and the set half a unit
  const path = (await page.locator("#upgrade-next .step-gain, #upgrade-then-list .step-gain").allTextContents()).map(amount);
  expect(path.length, "the path has the three steps that the sets are compared with").toBeGreaterThanOrEqual(3);
  for (const set of drawn) {
    expect(set.gain, `a set of ${set.k} adds something`).not.toBeNull();
    const first = path.slice(0, set.k).reduce((sum, gain) => sum + gain, 0);
    expect(amount(set.gain), `the best ${set.k} is not below the first ${set.k} steps of the path`).toBeGreaterThanOrEqual(first - set.k / 2 - 0.5);
  }
  expect(amount(drawn[1].gain), "and a set of 3 is not below a set of 2").toBeGreaterThanOrEqual(amount(drawn[0].gain) - 1);

  // Every slot: one request, the 22 places of Equip now, what the kit wears in each, and the best swaps
  await openExpander(page, "upgrade-slots");
  const rows = page.locator("#upgrade-slots-table tbody tr");
  await expect(rows).toHaveCount(22, { timeout: 60_000 });
  await expect(page.locator("#announce")).toHaveText("Every slot is ready.");
  await expect(page.locator("#upgrade-slots > summary")).toBeFocused();
  await expect(page.locator("#upgrade-slots-note")).toContainText("an evaluation, not a solve");
  expect(await requested(page)).toMatchObject([{ mode: "farm-path" }, { mode: "best-sets", k: 2 }, { mode: "best-sets", k: 3 }, { mode: "every-slot", kit: 22, limit: 3 }]);
  const worn = await page.$$eval("#upgrade-slots-table tbody tr", (trs) => trs.map((tr) => [tr.querySelector("th").textContent, tr.querySelector(".slot-now .owned-name")?.textContent ?? tr.querySelector(".slot-now .muted").textContent]));
  expect(worn, "the places and what the kit wears there are those of Equip now").toEqual(await equipOf(page));
  const swaps = await page.$$eval("#upgrade-slots-table tbody tr", (trs) => trs.map((tr) => [...tr.querySelectorAll("ol.swaps > li .delta")].map((delta) => delta.textContent)));
  expect(swaps.flat().length, "some place has a swap").toBeGreaterThan(0);
  for (const changes of swaps) {
    for (const change of changes) expect(change, "a change as the page writes a difference").toMatch(/^([+−](<1|[\d,]+)|0)$/);
  }
  for (const text of await page.locator("#upgrade-slots .swap-have").allTextContents()) expect(text).toMatch(/^you have it( \((worn|in your bags|in your bank|in your shared bank|on your cursor|on your key ring)(, [a-z ]+)*\))?$/);
  for (const text of await page.locator("#upgrade-slots .swap-get").allTextContents()) expect(text).toBe("get another copy");
  // the dump has one Band of Quiet Lanterns, which Equip now wears in Finger 1, and Finger 2 is offered a second one: a swap that is hidden is a swap that is lost
  if (FIXTURE) expect(await page.locator("#upgrade-slots .swap-get").count(), "an item the visitor has, and the kit wears, is offered as a copy to get").toBeGreaterThan(0);

  // what a visitor who cannot see the page is told: the page has the two live regions it had, and the expanders have none
  expect(await liveRegions(page)).toBe(0);
  expect(await page.$$eval('[role="status"], [aria-live]', (nodes) => nodes.map((node) => node.id))).toEqual(["status", "announce"]);
  await expect(page.locator("#upgrade-fault")).toBeHidden();
  expect(watch.problems()).toEqual([]);
});

test("a change of the tier mode restarts the answer with it; the expanders that are open are worked out again for it and the closed ones are not @once", async ({ page, watch }) => {
  test.setTimeout(300_000);
  await recordRequests(page);
  await open(page, TRIO);
  await pathEnded(page);
  const equip = await equipOf(page);
  await openExpander(page, "upgrade-sets");
  await expect(page.locator("#upgrade-sets .set")).toHaveCount(2, { timeout: 90_000 });
  await openExpander(page, "upgrade-mode");
  await expect(page.locator("#upgrade-mode > summary")).toHaveText("Tier mode: Ready +4");
  await expect(page.locator("#upgrade-mode-d option")).toHaveText(["+0", "+1", "+2", "+3", "+4"]);
  await expect(page.locator("#upgrade-mode-n option")).toHaveText(["+0", "+1", "+2", "+3", "+4", "+5", "+6", "+7", "+8", "+9", "+10"]);

  // Fixed +6: the path is asked for again with it (the choice of the tier is the choice of the mode), and so are the sets that were open
  await page.selectOption("#upgrade-mode-n", "6");
  await expect(page.locator("#upgrade-mode > summary")).toHaveText("Tier mode: Fixed +6");
  await expect.poll(async () => modesOf(await requested(page)).filter((mode) => mode === "farm-path").length, { timeout: 30_000 }).toBe(2);
  await expect(page.locator("#upgrade-end")).toHaveText(/\S/, { timeout: 90_000 });
  await expect(page.locator("#upgrade-stop")).toHaveCount(0);
  await expect(page.locator("#upgrade-sets .set")).toHaveCount(2, { timeout: 90_000 });
  let asked = await requested(page);
  expect(modesOf(asked)).toEqual(["farm-path", "best-sets:2", "best-sets:3", "farm-path", "best-sets:2", "best-sets:3"]);
  for (const request of asked.slice(3)) expect(request.tierMode, "the new mode is in the path and in the sets").toEqual({ mode: "fixed", N: 6 });
  for (const request of asked.slice(0, 3)) expect(request.tierMode).toEqual({ mode: "ready4" });
  expect(await equipOf(page), "Equip now does not depend on the tier mode").toEqual(equip);

  // As it arrives, drops at +2, and back to Ready +4: the optimizer takes each shape of the tier mode
  await page.selectOption("#upgrade-mode-d", "2");
  await expect(page.locator("#upgrade-mode > summary")).toHaveText("Tier mode: As it arrives, drops at +2");
  await expect.poll(async () => modesOf(await requested(page)).filter((mode) => mode === "farm-path").length, { timeout: 30_000 }).toBe(3);
  await expect(page.locator("#upgrade-sets .set")).toHaveCount(2, { timeout: 90_000 });
  await expect(page.locator("#upgrade-end")).toHaveText(/\S/, { timeout: 90_000 });
  await pick(page, "upgrade-mode-ready4");
  await expect(page.locator("#upgrade-mode > summary")).toHaveText("Tier mode: Ready +4");
  await expect.poll(async () => modesOf(await requested(page)).filter((mode) => mode === "farm-path").length, { timeout: 30_000 }).toBe(4);
  await expect(page.locator("#upgrade-sets .set")).toHaveCount(2, { timeout: 90_000 });
  await expect(page.locator("#upgrade-end")).toHaveText(/\S/, { timeout: 90_000 });
  asked = await requested(page);
  expect(asked.filter((request) => request.mode === "farm-path").map((request) => request.tierMode)).toEqual([{ mode: "ready4" }, { mode: "fixed", N: 6 }, { mode: "arrives", D: 2 }, { mode: "ready4" }]);
  expect(asked.some((request) => request.mode === "every-slot"), "Every slot was closed all along: it was never asked").toBe(false);
  await expect(page.locator("#upgrade-fault"), "the optimizer took every request").toBeHidden();
  expect(watch.problems()).toEqual([]);
});

// each expander in turn: one path, then Best 2 and 3 sets, Every slot and Tier mode opened one after the other, axe after each (so that each is checked open, and the three together at
// the end), with tight waits: what is waited for takes a second or two, and a machine that needs ten times that is a machine on which the page is slow
test("the section passes the accessibility checks with each of the expanders open in turn, and does not make the page wider than the window", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  await open(page, TRIO);
  await pathEnded(page, 30_000);
  const ready = {
    "upgrade-sets": () => expect(page.locator("#upgrade-sets .set")).toHaveCount(2, { timeout: 15_000 }),
    "upgrade-slots": () => expect(page.locator("#upgrade-slots-table tbody tr")).toHaveCount(22, { timeout: 15_000 }),
    "upgrade-mode": () => expect(page.locator("#upgrade-mode-d")).toBeVisible({ timeout: 5_000 }),
  };
  for (const id of ["upgrade-sets", "upgrade-slots", "upgrade-mode"]) {
    await openExpander(page, id);
    await ready[id]();
    await page.locator(`#${id}`).scrollIntoViewIfNeeded();
    await axe(page, testInfo);
  }
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
  expect(fits, "the page is not wider than the window").toBe(true);
});

test("Every slot says of an item that the visitor has: 'you have it' when there is a copy to spare, and 'get another copy' when the kit wears every copy, and hides no swap @once", async ({ page, watch }) => {
  test.setTimeout(90_000);
  await recordRequests(page);
  await open(page, TRIO);
  if (FIXTURE) {
    // the dump of the fixture, and in the bag's last slot three Pauldrons of the Vanguard: Equip now wears one of them (in an Any slot), and the other two are spare
    await dropFile(page, dump("site-small").replace("General 1-Slot4\tEmpty\t0\t0\t0", "General 1-Slot4\tPauldrons of the Vanguard +4\t520013\t3\t10"));
    await expect(question(page)).toBeVisible();
    await yes(page).click();
    await expect(page.locator("#upgrade-end")).toHaveText(/\S/, { timeout: 30_000 });
    await expect(page.locator("#upgrade-stop")).toHaveCount(0);
  } else {
    await pathEnded(page, 30_000);
  }
  await openExpander(page, "upgrade-slots");
  await expect(page.locator("#upgrade-slots-table tbody tr")).toHaveCount(22, { timeout: 15_000 });
  expect(modesOf(await requested(page))).toEqual(["farm-path", "every-slot"]);
  // the gear as the list says it (the name and the tier of an item, and how many copies there are), what Equip now wears in each place, and the swaps of each place
  const copies = new Map((await readRows(page)).map(([name, tier, count]) => [`${name} ${tier}`, count === "" ? 1 : Number.parseInt(count, 10)]));
  const worn = await page.$$eval("#upgrade-equip tbody tr", (trs) => trs.map((tr) => tr.querySelector(".owned-name")?.textContent ?? null));
  const swaps = await page.$$eval("#upgrade-slots-table tbody tr", (trs) =>
    trs.map((tr) => [...tr.querySelectorAll("ol.swaps > li")].map((li) => ({ what: li.querySelector(".swap-what").textContent, have: li.querySelector(".swap-have")?.textContent ?? null, get: li.querySelector(".swap-get")?.textContent ?? null }))),
  );
  expect(swaps.flat().length, "there are swaps to look at").toBeGreaterThan(0);
  swaps.forEach((places, place) => {
    for (const swap of places) {
      const have = copies.get(swap.what);
      if (have === undefined) {
        expect([swap.have, swap.get], `${swap.what} is not on the list`).toEqual([null, null]);
        continue;
      }
      const elsewhere = worn.filter((item, at) => at !== place && item === swap.what).length;
      const said = `${swap.what} in place ${place + 1}: ${have} copies, ${elsewhere} of them worn in other places`;
      if (have > elsewhere) expect([swap.have?.startsWith("you have it"), swap.get], said).toEqual([true, null]);
      else expect([swap.have, swap.get], said).toEqual([null, "get another copy"]);
    }
  });
  if (FIXTURE) {
    // the gear of the dump: one Band of Quiet Lanterns, which Equip now wears in Finger 1, and two Helms of the Stoneward, which it wears in the Head and in Any slot 1: each is
    // offered for another place as a copy to get
    expect(swaps[12].find((swap) => swap.what === "Band of Quiet Lanterns +4")?.get, "the only band is worn in Finger 1, and Finger 2 is offered another").toBe("get another copy");
    expect(swaps[19].find((swap) => swap.what === "Helm of the Stoneward +4")?.get, "both helms are worn, and the second Any slot is offered a third").toBe("get another copy");
    // and the pauldrons are a copy the visitor has: the one that is worn is one of three, and the spare is in the bags
    expect(swaps[5].find((swap) => swap.what === "Pauldrons of the Vanguard +4")?.have, "a spare is offered for Shoulders, and said to be in the bags").toBe("you have it (in your bags)");
  }
  await expect(page.locator("#upgrade-slots-note")).toContainText('"get another copy" that the kit wears every copy you have');
  expect(watch.problems()).toEqual([]);
});

test("a change made while an expander is being worked out ends that request, and the new path begins at once: it does not wait for a solve that nobody wants @once", async ({ page, watch }) => {
  test.setTimeout(120_000);
  const seen = watchRequests(page);
  await slowStream(page);
  await recordRequests(page);
  await open(page, TRIO);
  await pathEnded(page, 30_000);
  // what the worker answers from now on reaches the page 20 s late: the solve is over, but the request of the page is not
  await page.evaluate(() => (window.__tfDelay = 20_000));
  await openExpander(page, "upgrade-sets");
  await expect.poll(async () => modesOf(await requested(page)), { timeout: 10_000 }).toEqual(["farm-path", "best-sets:2"]);
  const began = Date.now();
  await giveMore(page); // a change of the gear while the set is being worked out
  await expect.poll(async () => modesOf(await requested(page)).filter((mode) => mode === "farm-path").length, { timeout: 12_000, message: "the new path was asked for" }).toBe(2);
  expect(Date.now() - began, "long before the answer of the set could have come").toBeLessThan(18_000);
  // the optimizer was started again from the module the page kept: two workers, and its WebAssembly was downloaded once
  expect(await startsOf(page)).toBe(2);
  expect(paths(seen).filter((path) => path.endsWith(".wasm")), "and its WebAssembly was downloaded once").toHaveLength(1);
  await expect(page.locator("#upgrade-sets .set")).toHaveCount(0);
  await expect(page.locator("#upgrade-sets-fault"), "a request that was ended is no fault").toBeHidden();
  expect(watch.problems()).toEqual([]);
});

test("the expander that was opened first is worked out first, whichever it is, though both were opened while the path ran @once", async ({ page, watch }) => {
  test.setTimeout(120_000);
  await slowStream(page);
  await recordRequests(page);
  await open(page, TRIO);
  await page.evaluate(() => (window.__tfDelay = 500)); // the steps reach the page half a second apart: the path takes a few seconds, and the expanders are opened meanwhile
  await giveGear(page);
  await expect(question(page)).toBeVisible();
  await yes(page).click();
  await expect(page.locator("#upgrade-equip")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#upgrade-stop")).toBeVisible();
  await openExpander(page, "upgrade-slots");
  await openExpander(page, "upgrade-sets");
  await expect(page.locator("#upgrade-stop"), "the path is still running: both were opened before it ended").toBeVisible();
  await page.evaluate(() => (window.__tfDelay = 0));
  await expect(page.locator("#upgrade-end")).toHaveText(/\S/, { timeout: 30_000 });
  await expect(page.locator("#upgrade-sets .set")).toHaveCount(2, { timeout: 20_000 });
  await expect(page.locator("#upgrade-slots-table tbody tr")).toHaveCount(22, { timeout: 20_000 });
  expect(modesOf(await requested(page)), "Every slot was opened first").toEqual(["farm-path", "every-slot", "best-sets:2", "best-sets:3"]);
  expect(watch.problems()).toEqual([]);
});

test("the expander that was opened first is worked out first even when two are opened in one task, before the page is told of the first: either order @once", async ({ page, watch }) => {
  test.setTimeout(180_000);
  await recordRequests(page);
  await open(page, TRIO);
  await pathEnded(page, 30_000);
  // two expanders opened in one task: the browser tells the page of the first, and then of the second, and the first is told of while the second is open already
  const together = (tab, ids) =>
    tab.evaluate(async (list) => {
      const told = list.map((id) => new Promise((resolve) => document.getElementById(id).addEventListener("toggle", resolve, { once: true })));
      for (const id of list) document.getElementById(id).open = true;
      await Promise.all(told);
    }, ids);
  await together(page, ["upgrade-slots", "upgrade-sets"]);
  await expect(page.locator("#upgrade-slots-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
  await expect(page.locator("#upgrade-sets .set")).toHaveCount(2, { timeout: 30_000 });
  expect(modesOf(await requested(page)), "Every slot was opened first").toEqual(["farm-path", "every-slot", "best-sets:2", "best-sets:3"]);

  // and the other way round, in a tab of its own with the same gear
  const other = await page.context().newPage();
  await recordRequests(other);
  await open(other, TRIO);
  await pathEnded(other, 30_000);
  await together(other, ["upgrade-sets", "upgrade-slots"]);
  await expect(other.locator("#upgrade-sets .set")).toHaveCount(2, { timeout: 30_000 });
  await expect(other.locator("#upgrade-slots-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
  expect(modesOf(await requested(other)), "the sets were opened first").toEqual(["farm-path", "best-sets:2", "best-sets:3", "every-slot"]);
  await other.close();
  expect(watch.problems()).toEqual([]);
});

test("a change that leaves the request the same keeps what the expanders have drawn: a mode chosen and then the one it was, within the pause, asks for nothing @once", async ({ page, watch }) => {
  test.setTimeout(90_000);
  await recordRequests(page);
  await open(page, TRIO);
  await pathEnded(page, 30_000);
  await openExpander(page, "upgrade-sets");
  await openExpander(page, "upgrade-slots");
  await expect(page.locator("#upgrade-sets .set")).toHaveCount(2, { timeout: 15_000 });
  await expect(page.locator("#upgrade-slots-table tbody tr")).toHaveCount(22, { timeout: 15_000 });
  const asked = modesOf(await requested(page));
  expect(asked).toEqual(["farm-path", "best-sets:2", "best-sets:3", "every-slot"]);
  await openExpander(page, "upgrade-mode");
  const end = await page.locator("#upgrade-end").textContent();
  // both choices in one task, so that the pause cannot end between them
  await page.evaluate(() => {
    document.getElementById("upgrade-mode-fixed").click();
    document.getElementById("upgrade-mode-ready4").click();
  });
  await page.waitForTimeout(1500); // the pause is 0.6 s: it has ended, and nothing was sent
  expect(modesOf(await requested(page)), "nothing was asked again").toEqual(asked);
  await expect(page.locator("#upgrade-sets .set")).toHaveCount(2);
  await expect(page.locator("#upgrade-slots-table tbody tr")).toHaveCount(22);
  await expect(page.locator("#upgrade-end"), "and the path was not sent again").toHaveText(end);
  await expect(page.locator("#upgrade-mode > summary")).toHaveText("Tier mode: Ready +4");
  expect(watch.problems()).toEqual([]);
});

test("a new file in which only the place of a copy has changed keeps the answer, asks for nothing, and says where the copies are now @once", async ({ page, watch }) => {
  test.skip(Boolean(process.env.TRIOFORGE_RESULTS), REAL_RESULTS);
  test.setTimeout(90_000);
  await recordRequests(page);
  await open(page, TRIO);
  // the dump of the fixture with three Pauldrons of the Vanguard: in the last slot of the bag, then in the second slot of the bank (nothing else differs)
  const pauldrons = "Pauldrons of the Vanguard +4\t520013\t3\t10";
  const inTheBag = dump("site-small").replace("General 1-Slot4\tEmpty\t0\t0\t0", `General 1-Slot4\t${pauldrons}`);
  const inTheBank = dump("site-small").replace("SharedBank1\tGauntlets", `Bank2\t${pauldrons}\r\nSharedBank1\tGauntlets`);
  expect(inTheBag).not.toBe(inTheBank);
  await dropFile(page, inTheBag);
  await expect(question(page)).toBeVisible();
  await yes(page).click();
  await expect(page.locator("#upgrade-end")).toHaveText(/\S/, { timeout: 30_000 });
  await openExpander(page, "upgrade-slots");
  await expect(page.locator("#upgrade-slots-table tbody tr")).toHaveCount(22, { timeout: 15_000 });
  // Equip now wears one of the three in the second Any slot, and says where it is; Every slot offers a spare for Shoulders, and says where that is
  const wornAt = page.locator("#upgrade-equip tbody tr").nth(19);
  const spare = page.locator("#upgrade-slots-table tbody tr").nth(5).locator("li", { hasText: "Pauldrons of the Vanguard" }).locator(".swap-have");
  await expect(wornAt.locator("th")).toHaveText("Any slot 2");
  await expect(wornAt).toContainText("Pauldrons of the Vanguard +4");
  await expect(wornAt.locator(".equip-where")).toHaveText("in your bags: move to worn");
  await expect(spare).toHaveText("you have it (in your bags)");
  const asked = modesOf(await requested(page));
  const end = await page.locator("#upgrade-end").textContent();

  await dropFile(page, inTheBank);
  await expect(page.locator("#upgrade-owned > li", { hasText: "Pauldrons of the Vanguard" })).toContainText("in the bank");
  await expect(wornAt.locator(".equip-where"), "Equip now says where the copy is now").toHaveText("in your bank: move to worn", { timeout: 5_000 });
  await expect(spare, "and so does Every slot").toHaveText("you have it (in your bank)");
  await page.waitForTimeout(1500); // (the pause is 0.6 s: it has ended, and nothing was sent)
  expect(modesOf(await requested(page)), "nothing was asked again").toEqual(asked);
  await expect(page.locator("#upgrade-slots-table tbody tr")).toHaveCount(22);
  await expect(page.locator("#upgrade-end")).toHaveText(end);
  await expect(page.locator("#upgrade-stop")).toHaveCount(0);
  expect(watch.problems()).toEqual([]);
});

// ---- sharing a kit, opening a shared kit, and remembering the gear --------------------------------------------------------------------------------------------
// Share this kit on Equip now copies a link (the trio page's address and #k= and the kit); a page opened from the link takes the kit out of the address into its history entry,
// shows it at the top with the value worked out in the page (no optimizer asked for), and keeps it through a reload. "Remember my gear on this device" keeps the owned list on the
// device as page ids, tiers and counts, and a page that finds some restores it. The fixture's kit has known items; real results are given placeholders only (no item is named).

const GEAR_KEY = "trioforge-gear";
/** A kit of the site fixture's invented items, with one the fixture does not have; real results know none of these items, so every place is a placeholder there. */
const SHARED_SLOTS = [[0, 90001, 4], [1, 90006, 4], [2, 90007, 4], [4, 90011, 4], [6, 90016, 4], [10, 90023, 4], [13, 90029, 10], [14, 90030, 4], [20, 80923, 4], [21, 80113, 0]];
const UNKNOWN_SLOTS = [[0, 2000000001, 4], [5, 2000000002, 0]];
const sharedPayload = (slots = FIXTURE ? [...SHARED_SLOTS, [11, 2000000003, 2]] : UNKNOWN_SLOTS) => encodeKit({ v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots });

/** Record what is copied to the clipboard (the real call is made too, unless the test has the browser refuse). */
function recordClipboard(page, { refuse = false } = {}) {
  return page.addInitScript((refuses) => {
    window.__tfCopied = [];
    const clipboard = navigator.clipboard;
    if (!clipboard || typeof clipboard.writeText !== "function") return;
    const write = clipboard.writeText.bind(clipboard);
    clipboard.writeText = (text) => {
      window.__tfCopied.push(text);
      return refuses ? Promise.reject(new DOMException("not allowed", "NotAllowedError")) : write(text);
    };
  }, refuse);
}
const copied = (page) => page.evaluate(() => window.__tfCopied);
/** The shared kit as a visitor reads it: for each place, what the kit wears there (the same two columns as equipOf gives for Equip now). */
const sharedRows = (page) =>
  page.$$eval("#shared-kit-table tbody tr", (rows) => rows.map((row) => [row.querySelector("th").textContent, row.querySelector(".owned-name")?.textContent ?? row.querySelector(".muted").textContent]));
/** The gear given as the other tests give it, and the wait until the list shows it (a file is read after the section has loaded). */
async function gearShown(page) {
  await giveGear(page);
  await expect(page.locator("#upgrade-owned > li").first()).toBeVisible({ timeout: 30_000 });
}
/** What the owned list shows: name, tier and how many (not where: a restored list has no places). */
const readGear = (page) => page.$$eval("#upgrade-owned > li", (items) => items.map((li) => [li.querySelector(".owned-name").textContent, li.querySelector(".owned-tier").textContent, li.querySelector(".owned-count")?.textContent ?? ""]));

test("Share this kit copies the link of Equip now, and the link opened in a new page shows the same items and works the kit out again, without asking for the optimizer @once", async ({ page, watch }) => {
  test.setTimeout(180_000);
  await page.context().grantPermissions(["clipboard-write"]);
  await recordClipboard(page);
  await open(page, TRIO);
  await pathEnded(page);
  const equip = await equipOf(page);
  await expect(page.locator("#upgrade-share-button")).toHaveText("Share this kit");
  await expect(page.locator("#upgrade-share-words")).toHaveText("This link lists the items in this kit.");
  expect(await copied(page), "nothing is copied until the visitor asks").toEqual([]);
  await page.locator("#upgrade-share-button").click();
  await expect(page.locator("#upgrade-share-result")).toHaveText(/^Link copied/);
  const [link] = await copied(page);
  const home = new URL(TRIO, page.url()).href;
  expect(link.startsWith(`${home}#k=`), "the trio page's own address and #k=").toBe(true);
  const payload = link.slice(link.indexOf("#k=") + 3);
  const worn = equip.filter(([, name]) => name !== "Leave empty");
  const decoded = decodeKit(payload, new Map());
  expect(decoded.errors).toEqual([]);
  expect(decoded.kit.slots, "every item Equip now wears, and nothing else").toHaveLength(worn.length);
  const slotsOf = (kit) => kit.slots.map((slot) => [slot.slotIndex, slot.pageId, slot.tier]);
  expect(encodeKit({ v: 1, trio: decoded.kit.trio, race: decoded.kit.race, level: decoded.kit.level, slots: slotsOf(decoded.kit) }), "the canonical text").toBe(payload);
  expect(payload.length, "the places of the kit and no inventory").toBeLessThan(215);
  await expect(page.locator("#upgrade-share-field")).toBeHidden();
  expect(watch.problems()).toEqual([]);

  // the link, opened in a page of its own
  const other = await page.context().newPage();
  const trouble = [];
  other.on("pageerror", (error) => trouble.push(error.message));
  other.on("console", (message) => ["error", "warning"].includes(message.type()) && !/Permissions-Policy/.test(message.text()) && trouble.push(message.text()));
  const seen = watchRequests(other);
  await other.goto(link);
  await expect(other.locator("#shared-kit-h")).toHaveText("A kit shared with you");
  await expect(other.locator("#shared-kit-value")).toContainText("Kit value", { timeout: 60_000 });
  expect(await sharedRows(other), "the same items, place by place").toEqual(equip);
  expect(other.url(), "the address is clean").toBe(home);
  expect(await other.evaluate(() => history.state)).toEqual({ k: payload });
  expect(await other.evaluate(() => document.documentElement.dataset.kitFragment)).toBe("cleared");
  await expect(other.locator(".engine-consent"), "the optimizer's question is not asked").toHaveCount(0);
  expect(paths(seen).filter((path) => /\/assets\/engine\/(client|worker|highs)-/.test(path)), "and the optimizer is not downloaded, nor even its client").toEqual([]);
  // the evaluator of a shared kit is a script of its own: fetched to be checked against the manifest, and then imported (the browser has it from the cache by then, a year-long copy)
  expect(paths(seen).filter((path) => /\/assets\/engine\/kitvalue-[A-Z0-9]{8}\.js$/.test(path)), "the evaluator is asked for to be checked and to be run").toHaveLength(2);
  expect(paths(seen).filter((path) => /\/assets\/engine\/data\/[a-z]{3}-[a-z]{3}-[a-z]{3}-l50-/.test(path)), "the bundle of the trio is fetched once, for the evaluator").toHaveLength(1);
  for (const request of seen) expect(request.url.href.includes(payload) || request.url.search.includes("k="), request.url.pathname).toBe(false);
  // the value line: the race of the kit, the view, and the weapons of the kit's own hands with the haste (the numbers are held to Python's reference in the test of the values below)
  await expect(other.locator("#shared-kit-value")).toContainText(/^Kit value [\d,]+ for [^.]+\. Weapons: [^,]+, read from the kit's hands/);
  expect(trouble).toEqual([]);
  await other.close();
});

test("when the browser will not copy, the link is in a read-only field, selected, and the button keeps the focus @once", async ({ page, watch }) => {
  test.setTimeout(180_000);
  await recordClipboard(page, { refuse: true });
  await open(page, TRIO);
  await pathEnded(page);
  await page.locator("#upgrade-share-button").focus();
  await page.keyboard.press("Enter");
  const field = page.locator("#upgrade-share-link");
  await expect(field).toBeVisible();
  await expect(page.locator('label[for="upgrade-share-link"]')).toHaveText("Copy the link from here");
  await expect(field).toHaveJSProperty("readOnly", true);
  const [link] = await copied(page);
  await expect(field).toHaveValue(link);
  expect(await field.evaluate((input) => [input.selectionStart, input.selectionEnd, input.value.length])).toEqual([0, link.length, link.length]);
  await expect(page.locator("#upgrade-share-button")).toBeFocused();
  expect(watch.problems()).toEqual([]);
});

test("a link that cannot be read says so after the decode, the address is clean, and the page shows its own answer as ever @once", async ({ page, watch }) => {
  await open(page, `${TRIO}#k=!!!`);
  await expect(page.locator("#shared-kit-h")).toHaveText("A kit shared with you");
  await expect(page.locator("#shared-kit-state")).toHaveText("This kit link could not be read", { timeout: 30_000 });
  await expect(page.locator("#announce")).toHaveText("A kit shared with you. This kit link could not be read.");
  expect(new URL(page.url()).hash).toBe("");
  expect(await page.evaluate(() => history.state)).toEqual({ k: "!!!" });
  await expect(page.locator("#shared-kit-table")).toBeHidden();
  await expect(page.locator("#kit-body tr")).toHaveCount(22);
  expect(watch.problems()).toEqual([]);
});

test("a shared kit stays through a reload, and the skip link does not make a history entry that would lose it @once", async ({ page, watch }) => {
  const payload = sharedPayload();
  await open(page, `${TRIO}#k=${payload}`);
  await expect(page.locator("#shared-kit-h")).toHaveText("A kit shared with you");
  await expect(page.locator("#shared-kit-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
  expect(await page.evaluate(() => document.documentElement.dataset.kitFragment)).toBe("cleared");
  expect(new URL(page.url()).hash).toBe("");
  await expect(page.locator("#shared-kit-value")).toContainText("Excludes", { timeout: 60_000 });
  // the skip link, followed with the keyboard, scrolls to the content and moves the focus, and the address and the history entry stay
  const entries = await page.evaluate(() => history.length);
  await tabTo(page, ".skip-link", 5);
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  expect(new URL(page.url()).hash).toBe("");
  expect(await page.evaluate(() => history.length)).toBe(entries);
  await page.reload();
  await expect(page.locator("#shared-kit-h")).toHaveText("A kit shared with you");
  await expect(page.locator("#shared-kit-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
  expect(await page.evaluate(() => "kitFragment" in document.documentElement.dataset), "nothing was in the address of a reload").toBe(false);
  expect(await page.evaluate(() => history.state)).toEqual({ k: payload });
  expect(watch.problems()).toEqual([]);
});

test("the code of a shared kit is a chunk of its own: asked for when a kit link is opened, and not when the section is used without one @once", async ({ page, watch }) => {
  test.setTimeout(120_000);
  const chunks = (seen, name) => paths(seen).filter((path) => new RegExp(`/assets/${name}-[A-Z0-9]{8}\.js$`).test(path));
  const seen = watchRequests(page);
  await open(page, TRIO);
  await gearShown(page);
  expect(chunks(seen, "upgrade-input"), "the code of the section").toHaveLength(1);
  expect(chunks(seen, "shared-kit"), "and none of the code of a shared kit, nor of its evaluator").toEqual([]);
  expect(paths(seen).filter((path) => /\/assets\/engine\/kitvalue-/.test(path))).toEqual([]);
  const other = await page.context().newPage();
  const second = watchRequests(other);
  await other.goto(`${TRIO}#k=${sharedPayload()}`);
  await expect(other.locator("#shared-kit-value")).toContainText("Kit value", { timeout: 60_000 });
  expect(chunks(second, "upgrade-input"), "a kit link starts the section's code at once").toHaveLength(1);
  expect(chunks(second, "shared-kit"), "and the code of the panel, once, as a chunk of its own").toHaveLength(1);
  await other.close();
  expect(watch.problems()).toEqual([]);
});

// A chunk that loads is not yet a panel. The test answers the chunk of the panel itself (page.route), with a module that has no createSharedKit and with one whose createSharedKit throws:
// the page says so at the top, where the kit would be, and the section says so near its controls, each with a Reload, and the section works on without the kit.

const KIT_CODE_FAILED = "Couldn't load the shared kit. Reload the page to try again.";
const PANEL_CHUNK = "**/assets/shared-kit-*.js";

for (const [what, source] of [
  ["has no createSharedKit", "export const nothing = 1;\n"],
  ["throws from createSharedKit", "export function createSharedKit() { throw new Error('no panel'); }\n"],
]) {
  test(`a chunk of the shared kit that loads but ${what} is said like code that could not be had: the page's status and the section's line, each with a Reload @once`, async ({ page, watch }) => {
    test.setTimeout(120_000);
    await page.route(PANEL_CHUNK, (route) => route.fulfill({ status: 200, contentType: "text/javascript; charset=utf-8", body: source }));
    await open(page, `${TRIO}#k=${sharedPayload()}`);
    await expect(page.locator("#status .status-text")).toHaveText(KIT_CODE_FAILED, { timeout: 30_000 });
    await expect(page.locator("#upgrade-load .status-text")).toHaveText(KIT_CODE_FAILED);
    await expect(page.locator("#status").getByRole("button")).toHaveText("Reload");
    await expect(page.locator("#upgrade-load").getByRole("button")).toHaveText("Reload");
    await expect(page.locator("#shared-kit")).toHaveCount(0);
    await expect(page.locator("#upgrade-add")).toBeEnabled(); // (the section works on)
    // the chunk is there again, and the Reload brings the kit
    await page.unroute(PANEL_CHUNK);
    await Promise.all([page.waitForEvent("load"), page.locator("#upgrade-load").getByRole("button", { name: "Reload" }).click()]);
    await expect(page.locator("#shared-kit-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
    await expect(page.locator("#status .status-text")).toHaveCount(0);
    expect(watch.problems()).toEqual([]);
  });
}

// A dynamic import has no time limit of its own. The test leaves the request of the panel's own chunk, and then that of the evaluator's import, unanswered (page.route) and moves the page's
// clock (page.clock) past the time that the body of a download has, 60 s, so that no test waits for it. Past it the page says so, with a Reload; a browser keeps a failed module fetch until the
// page is reloaded, so a Try again would do nothing. (The reload cancels the request that was never answered: a failed request is expected here.)

const EVALUATOR = "**/assets/engine/kitvalue-*.js";
const BODY_LIMIT_MS = 60_000;
const VALUE_RELOAD = "The value could not be worked out here. Reload the page to try again.";

test("a chunk of the shared kit that never arrives is given up at the time limit of a body: the page's status and the section's line say so, each with a Reload, and the section works on @once", async ({ page, watch }) => {
  test.setTimeout(120_000);
  await page.clock.install();
  const asked = page.waitForRequest(/\/assets\/shared-kit-[A-Z0-9]{8}\.js$/);
  await page.route(PANEL_CHUNK, () => {}); // (never answered)
  await open(page, `${TRIO}#k=${sharedPayload()}`);
  await asked;
  await expect(page.locator("#upgrade-add")).toBeEnabled({ timeout: 30_000 }); // (the item list comes meanwhile, and the section can be used)
  await expect(page.locator("#status .status-text")).toHaveCount(0);
  await page.clock.fastForward(BODY_LIMIT_MS);
  await expect(page.locator("#status .status-text")).toHaveText(KIT_CODE_FAILED);
  await expect(page.locator("#upgrade-load .status-text")).toHaveText(KIT_CODE_FAILED);
  await expect(page.locator("#status").getByRole("button")).toHaveText("Reload");
  await expect(page.locator("#upgrade-load").getByRole("button")).toHaveText("Reload");
  await expect(page.locator("#shared-kit")).toHaveCount(0);
  await expect(page.locator("#upgrade-add")).toBeEnabled();
  // the chunk is there again, and the Reload brings the kit
  await page.unroute(PANEL_CHUNK);
  await Promise.all([page.waitForEvent("load"), page.locator("#upgrade-load").getByRole("button", { name: "Reload" }).click()]);
  await expect(page.locator("#shared-kit-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
  await expect(page.locator("#status .status-text")).toHaveCount(0);
  expect(watch.problems(["requestfailed"])).toEqual([]);
});

test("an evaluator whose import never settles is given up at the time limit of a body: the panel says that the value could not be worked out, with a Reload @once", async ({ page, watch }) => {
  test.setTimeout(120_000);
  await page.clock.install();
  let asked = 0;
  // the first request for the script is the page's check of it against the manifest; the second is the import, which is never answered
  await page.route(EVALUATOR, (route) => {
    asked += 1;
    if (asked === 1) route.continue();
  });
  await open(page, `${TRIO}#k=${sharedPayload()}`);
  await expect(page.locator("#shared-kit-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
  await expect.poll(() => asked, { timeout: 30_000, message: "the script was asked for twice: to be checked, and to be imported" }).toBe(2);
  await expect(page.locator("#shared-kit-state .status-text")).toHaveText("Working out its value…");
  await page.clock.fastForward(BODY_LIMIT_MS);
  await expect(page.locator("#shared-kit-state .status-text")).toHaveText(VALUE_RELOAD);
  await expect(page.locator("#shared-kit-state").getByRole("button")).toHaveText("Reload");
  await expect(page.locator("#shared-kit-value")).toBeHidden();
  await expect(page.locator("#shared-kit-table tbody tr")).toHaveCount(22);
  await expect(page.locator("#announce")).toHaveText(`A kit shared with you. ${VALUE_RELOAD}`);
  // the script is served again, and the Reload brings the value
  await page.unroute(EVALUATOR);
  await Promise.all([page.waitForEvent("load"), page.locator("#shared-kit-state").getByRole("button", { name: "Reload" }).click()]);
  await expect(page.locator("#shared-kit-value")).toContainText("Kit value", { timeout: 60_000 });
  expect(watch.problems(["requestfailed"])).toEqual([]);
});

test("a second kit link opened in the same tab shows its kit, with the address clean, and so does the same link opened again @once", async ({ page, watch }) => {
  test.setTimeout(120_000);
  const first = sharedPayload();
  const second = encodeKit({ v: 1, trio: "pal-mnk-ber", race: "TRL", level: 50, slots: FIXTURE ? [[0, 90003, 4], [4, 90011, 0], [20, 80923, 4]] : [[0, 2000000007, 1], [4, 2000000008, 0]] });
  await open(page, `${TRIO}#k=${first}`);
  await expect(page.locator("#shared-kit-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
  const rowsOfFirst = await sharedRows(page);
  expect(await page.evaluate(() => document.documentElement.dataset.kitFragment)).toBe("cleared");

  // the link of another kit, pasted into the address bar of this tab: only the fragment differs, so the browser does not load the page by itself
  const opened = async (payload, marker) => {
    await page.evaluate((text) => (window.__tfMarker = text), marker);
    await page.goto(`${TRIO}#k=${payload}`);
    // (a page that is being replaced has no script context to ask: that is the page being loaded again)
    await expect.poll(() => page.evaluate(() => window.__tfMarker ?? null).catch(() => null), { timeout: 30_000, message: "the page was loaded again, and shows the kit of the link" }).toBeNull();
    await expect(page.locator("#shared-kit-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
    expect(new URL(page.url()).hash, "the address is clean").toBe("");
    expect(await page.evaluate(() => history.state)).toEqual({ k: payload });
  };
  await opened(second, "first load");
  const rowsOfSecond = await sharedRows(page);
  expect(rowsOfSecond, "the second kit, not the first").not.toEqual(rowsOfFirst);
  if (FIXTURE) {
    expect(rowsOfSecond[0]).toEqual(["Head", "Crown of the Vanguard +4"]);
    expect(rowsOfFirst[0]).toEqual(["Head", "Helm of the Stoneward +4"]);
  } else {
    expect(rowsOfSecond[0]).toEqual(["Head", "Unknown item (w2000000007) +1"]);
  }
  await expect(page.locator("#shared-kit-value")).toContainText("Kit value", { timeout: 60_000 });

  // the same link, opened again
  await opened(second, "second load");
  expect(await sharedRows(page)).toEqual(rowsOfSecond);
  await expect(page.locator("#shared-kit-value")).toContainText("Kit value", { timeout: 60_000 });
  // and the first one again
  await opened(first, "third load");
  expect(await sharedRows(page)).toEqual(rowsOfFirst);
  expect(watch.problems()).toEqual([]);
});

const KIT_VALUES = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/kit-values.json"), "utf8"));
const slotsOfKit = (kit) => kit.kit.flatMap((ident, slot) => (ident === null ? [] : [[slot, Number(ident.slice(1, ident.indexOf("@"))), Number(ident.slice(ident.indexOf("@") + 1))]]));
const SETUP_WORDS = { dw: "dual wield", "1h-shield": "1H + shield", "2h": "two-hander", stick: "stat stick" };
const ROLE_WORDS = { balanced: "Balanced", tank: "Tank", melee: "Melee" };
const RACE_WORDS = { OGR: "Ogre", TRL: "Troll", IKS: "IKS", HUM: "HUM" }; // (the fixture's shards list three races; the page shows the code of one it does not list)
const BUFF_WORDS = { own: "your own buffs", group: "common group buffs" };
/** The assumptions of the page are three disclosures: a choice in them is made once they are open. */
async function openAssumes(page) {
  for (const id of ["assume-buffs", "assume-weapons"]) {
    const node = page.locator(`#${id}`);
    if ((await node.getAttribute("open")) === null) await node.locator("> summary").click();
  }
}
/** The line the page writes for a row of Python's reference: the number as the page writes a number (rounded half up), and the setup and the haste of the kit. */
const lineOf = (kit, row) =>
  `Kit value ${Math.floor(row.value + 0.5).toLocaleString("en-US")} for ${RACE_WORDS[kit.race]}, ${ROLE_WORDS[row.role]}, ${BUFF_WORDS[row.buffs]}. Weapons: ${SETUP_WORDS[kit.setup]}, read from the kit's hands, at ${row.hasteAssumed}% haste.`;

test("a shared kit is worth what Python's reference says, under each role and buffs the page offers, made from the evidence level of the kit, with the weapons of its own hands and the haste of its own items @once", async ({ page, watch }) => {
  test.skip(!FIXTURE, "the reference's kits are made of the fixture's items");
  test.setTimeout(240_000);
  const rows = KIT_VALUES.values.filter((row) => ["own", "group"].includes(row.buffs) && KIT_VALUES.kits[row.kit].deity === null);
  const kitsShown = [...new Set(rows.map((row) => row.kit))];
  expect(kitsShown.length).toBeGreaterThanOrEqual(4);
  for (const index of kitsShown) {
    const kit = KIT_VALUES.kits[index];
    await madeFrom(page, kit.evidence);
    await open(page, `${TRIO}#k=${encodeKit({ v: 1, trio: "pal-mnk-ber", race: kit.race, level: 50, slots: slotsOfKit(kit) })}`);
    await expect(page.locator("#shared-kit-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
    await openAssumes(page);
    for (const row of rows.filter((one) => one.kit === index)) {
      await pick(page, `role-${row.role}`);
      await pick(page, `buffs-${row.buffs}`);
      await expect(page.locator("#shared-kit-value"), `${kit.name} / ${row.role} / ${row.buffs}`).toHaveText(lineOf(kit, row), { timeout: 30_000 });
    }
  }
  expect(watch.problems()).toEqual([]);
});

test("the value of a shared kit does not follow the page's weapon switch or its tier switch, which move the haste of the page's own answer @once", async ({ page, watch }) => {
  test.skip(!FIXTURE, "the reference's kits are made of the fixture's items");
  test.setTimeout(120_000);
  const kit = KIT_VALUES.kits[0];
  const row = KIT_VALUES.values.find((one) => one.kit === 0 && one.role === "balanced" && one.buffs === "own");
  await madeFrom(page, kit.evidence);
  await open(page, `${TRIO}#k=${encodeKit({ v: 1, trio: "pal-mnk-ber", race: kit.race, level: 50, slots: slotsOfKit(kit) })}`);
  await expect(page.locator("#shared-kit-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
  await openAssumes(page);
  await expect(page.locator("#shared-kit-value")).toHaveText(lineOf(kit, row), { timeout: 30_000 });
  const hastes = new Set([await page.locator('[data-f="assume-haste"]').textContent()]);
  for (const setup of ["2h", "dw", "1h-shield"]) {
    const radio = page.locator(`#setup-${setup}`);
    if (!(await radio.isEnabled())) continue;
    await pick(page, `setup-${setup}`);
    await expect(page.locator('[data-f="assume-setup"]')).toHaveText(SETUP_WORDS[setup]);
    hastes.add(await page.locator('[data-f="assume-haste"]').textContent());
    await expect(page.locator("#shared-kit-value"), `the page shows ${setup}`).toHaveText(lineOf(kit, row));
  }
  for (const [tier, label] of await page.locator("#sw-tier option").evaluateAll((options) => options.map((option) => [option.value, option.dataset.label]))) {
    await page.selectOption("#sw-tier", tier);
    await expect(page.locator('[data-f="v-tier"]').first()).toHaveText(label);
    hastes.add(await page.locator('[data-f="assume-haste"]').textContent());
    await expect(page.locator("#shared-kit-value"), `the page shows tier ${tier}`).toHaveText(lineOf(kit, row));
  }
  expect(hastes.size, "the haste of the page's own answer did move").toBeGreaterThan(1);
  expect(watch.problems()).toEqual([]);
});

test("a two-hander in the main hand takes both hands: the item in the off hand is not counted, and its row says why @once", async ({ page, watch }) => {
  test.skip(!FIXTURE, "the items are the fixture's");
  const slots = [[0, 90001, 4], [20, 80524, 4], [21, 80113, 0]];
  await open(page, `${TRIO}#k=${encodeKit({ v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots })}`);
  await expect(page.locator("#shared-kit-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
  await expect(page.locator("#shared-kit-table tbody tr").nth(21).locator(".owned-meta")).toHaveText("Not counted: a two-hander takes both hands", { timeout: 30_000 });
  await expect(page.locator("#shared-kit-value")).toContainText("Weapons: two-hander, read from the kit's hands");
  await expect(page.locator("#shared-kit-value")).toContainText("1 item cannot be worn where the link puts it and is not counted.");
  expect(watch.problems()).toEqual([]);
});

test("remembered gear comes back after a reload with Forget, is kept as page ids, tiers and counts only, and Forget clears it @once", async ({ page, watch }) => {
  test.setTimeout(150_000);
  const seen = watchRequests(page);
  await open(page, TRIO);
  expect(paths(seen).filter((path) => /upgrade-input/.test(path)), "no remembered gear: the section's code is not asked for").toEqual([]);
  await gearShown(page);
  await expect(page.locator("#upgrade-remember-box")).not.toBeChecked();
  expect(await page.evaluate((key) => localStorage.getItem(key), GEAR_KEY), "nothing is kept until it is asked").toBeNull();
  await page.locator("#upgrade-remember-box").check();
  await expect(page.locator("#upgrade-remember-note")).toHaveText("Your gear is remembered on this device.");
  const kept = JSON.parse(await page.evaluate((key) => localStorage.getItem(key), GEAR_KEY));
  expect(Object.keys(kept).sort()).toEqual(["entries", "v"]);
  expect(kept.v).toBe(1);
  expect(kept.entries.length).toBeGreaterThan(0);
  for (const entry of kept.entries) expect(entry.length === 3 && entry.every(Number.isInteger), JSON.stringify(entry)).toBe(true);
  expect(Object.keys(await page.evaluate(() => ({ ...localStorage }))), "and nothing else is kept").toEqual([GEAR_KEY]);
  const before = await readGear(page);

  await page.reload();
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(before.length, { timeout: 30_000 });
  expect(await readGear(page)).toEqual(before);
  expect((await readRows(page)).map((row) => row[3]), "what was restored says that it was remembered: the visitor did not add it by hand").toEqual(before.map(() => "remembered"));
  await expect(page.locator("#upgrade-remember-box")).toBeChecked();
  await expect(page.locator("#upgrade-remember-note")).toContainText(`Restored ${before.length} `);
  await expect(page.locator("#upgrade-remember-note")).toContainText("Restored gear has no places, so Equip now gives no location notes for it.");
  await expect(page.locator("#upgrade-forget")).toHaveText("Forget");
  expect(await page.evaluate((key) => JSON.parse(localStorage.getItem(key)).entries.length, GEAR_KEY)).toBe(kept.entries.length);

  await page.locator("#upgrade-forget").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(0);
  await expect(page.locator("#upgrade-remember-box")).not.toBeChecked();
  await expect(page.locator("#upgrade-remember-box")).toBeFocused();
  expect(await page.evaluate((key) => localStorage.getItem(key), GEAR_KEY)).toBeNull();
  await expect(page.locator("#upgrade-remember-note")).toHaveText("Forgot your gear: the list is empty and nothing is remembered on this device.");

  const asked = seen.length;
  await page.reload();
  await page.waitForTimeout(500);
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(0);
  await expect(page.locator("#upgrade-add")).toBeDisabled(); // (nothing is stored: the section's code waits for its first use, as before)
  expect(paths(seen.slice(asked)).filter((path) => /upgrade-input|engine-manifest|\/assets\/engine\//.test(path)), "and none of it is asked for").toEqual([]);
  expect(watch.problems()).toEqual([]);
});

test("gear that was remembered is replaced by the file read after it, not added to: the counts are the file's, in the list and on the device, and a reload restores the same list @once", async ({ page, watch }) => {
  test.skip(!FIXTURE, REAL_RESULTS);
  test.setTimeout(150_000);
  await open(page, TRIO);
  await dropFile(page, dump("site-small"));
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(SITE_SMALL.length, { timeout: 30_000 });
  await page.locator("#upgrade-remember-box").check();
  await expect(page.locator("#upgrade-remember-note")).toHaveText("Your gear is remembered on this device.");
  const kept = () => page.evaluate((key) => localStorage.getItem(key), GEAR_KEY);
  const saved = await kept();
  const counted = (rows) => rows.map(([name, tier, count]) => [name, tier, count]); // (a restored list has no places)

  // the next visit restores the list; the same file is read on top of it, twice
  await page.reload();
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(SITE_SMALL.length, { timeout: 30_000 });
  await expect(page.locator("#upgrade-forget")).toBeVisible();
  expect(counted(await readRows(page)), "restored").toEqual(counted(SITE_SMALL));
  for (const time of [1, 2]) {
    await dropFile(page, dump("site-small"));
    await expect.poll(() => readRows(page), { timeout: 30_000, message: `the file was read (${time})` }).toEqual(SITE_SMALL);
    expect(await kept(), `what the device keeps is the file's list (${time})`).toBe(saved);
  }

  // and the visit after it
  await page.reload();
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(SITE_SMALL.length, { timeout: 30_000 });
  expect(counted(await readRows(page))).toEqual(counted(SITE_SMALL));
  expect(watch.problems()).toEqual([]);
});

test("an erase in one tab is not undone by another tab that has the box checked: that tab sets itself off, says so, and writes nothing @once", async ({ page, watch }) => {
  test.setTimeout(150_000);
  await open(page, TRIO);
  await gearShown(page);
  await page.locator("#upgrade-remember-box").check();
  await expect(page.locator("#upgrade-remember-note")).toHaveText("Your gear is remembered on this device.");
  const stored = (tab) => tab.evaluate((key) => localStorage.getItem(key), GEAR_KEY);
  expect(await stored(page)).not.toBeNull();

  // a second tab of the same browser restores the list and keeps it too
  const other = await page.context().newPage();
  await other.goto(TRIO);
  await expect(other.locator("#upgrade-remember-box")).toBeChecked({ timeout: 30_000 });
  await expect(other.locator("#upgrade-forget")).toBeVisible();

  // the first tab erases the copy by unchecking the box
  await page.locator("#upgrade-remember-box").uncheck();
  await expect(page.locator("#upgrade-remember-note")).toHaveText("Your remembered gear was erased from this device.");
  expect(await stored(page)).toBeNull();

  // the second tab hears about it
  const words = "Your remembered gear was erased from this device in another tab, so this page no longer remembers it.";
  await expect(other.locator("#upgrade-remember-box")).not.toBeChecked({ timeout: 10_000 });
  await expect(other.locator("#upgrade-remember-note")).toHaveText(words);
  await expect(other.locator("#announce")).toHaveText(words);
  await expect(other.locator("#upgrade-forget")).toHaveCount(0);
  const kept = await other.locator("#upgrade-owned > li").count();
  expect(kept, "its list stays as it was").toBeGreaterThan(0);

  // and a change there does not write the copy again
  await giveMore(other);
  await expect(other.locator("#upgrade-owned > li")).not.toHaveCount(kept);
  expect(await stored(other), "the erase is not undone").toBeNull();
  expect(await stored(page)).toBeNull();
  await other.close();
  expect(watch.problems()).toEqual([]);
});

// The erase of the other tab and the event that tells this tab of it are two things, and a task of this tab can run between them: a change of the list that was queued here writes the copy
// again (the box is still checked), and the tab that the event then sets off would leave its own late write on the device. A listener added before the page's own (an init script runs first)
// makes that change in the task of the event, so the page's listener finds the key written again; the other tab's erase is made on the same storage, from a page of the site that has no
// section. A tab that hears an erase takes the key out again when it holds the text it wrote last, and leaves a copy that another tab wrote.

for (const [what, late, left] of [
  ["its own late write is taken out again, so the key is gone", "mine", null],
  ["a copy that another tab wrote after the erase stays", "theirs", '{"v":1,"entries":[[90001,0,1]]}'],
]) {
  test(`an erase in one tab that this tab hears of after a change of its own: ${what} @once`, async ({ page, watch }) => {
    test.skip(!FIXTURE, "the list needs more than one row, which the dump of the fixture gives");
    test.setTimeout(150_000);
    await page.addInitScript(
      ({ key, how, theirs }) => {
        window.addEventListener("storage", (event) => {
          if (!window.__tfLate || event.key !== key || event.newValue !== null) return;
          window.__tfLate = false;
          if (how === "mine") document.querySelector("#upgrade-owned li button")?.click(); // Remove on the first row: the list changes, and the box, still checked, keeps it
          else localStorage.setItem(key, theirs);
        });
      },
      { key: GEAR_KEY, how: late, theirs: left },
    );
    await open(page, TRIO);
    await gearShown(page);
    await page.locator("#upgrade-remember-box").check();
    await expect(page.locator("#upgrade-remember-note")).toHaveText("Your gear is remembered on this device.");
    const stored = (tab) => tab.evaluate((key) => localStorage.getItem(key), GEAR_KEY);
    expect(await stored(page)).not.toBeNull();
    const rows = await page.locator("#upgrade-owned > li").count();
    expect(rows).toBeGreaterThan(1);
    await page.evaluate(() => {
      window.__tfLate = true;
    });

    // another tab of the same browser erases the copy
    const other = await page.context().newPage();
    await other.goto("/about/");
    await other.evaluate((key) => localStorage.removeItem(key), GEAR_KEY);

    // this tab hears about it
    const words = "Your remembered gear was erased from this device in another tab, so this page no longer remembers it.";
    await expect(page.locator("#upgrade-remember-box")).not.toBeChecked({ timeout: 10_000 });
    await expect(page.locator("#upgrade-remember-note")).toHaveText(words);
    if (late === "mine") await expect(page.locator("#upgrade-owned > li"), "the change that ran first").toHaveCount(rows - 1);
    expect(await stored(page), "what the device holds after the event").toBe(left);
    expect(await stored(other)).toBe(left);

    // and a change here writes nothing more
    await giveMore(page);
    await expect(page.locator("#upgrade-owned > li")).not.toHaveCount(late === "mine" ? rows - 1 : rows);
    expect(await stored(page)).toBe(left);
    await other.close();
    expect(watch.problems()).toEqual([]);
  });
}

test("a device that refuses to store says so, and the section works the same @once", async ({ page, watch }) => {
  test.setTimeout(120_000);
  await page.addInitScript(() => {
    Storage.prototype.setItem = function () {
      throw new DOMException("full", "QuotaExceededError");
    };
  });
  await open(page, TRIO);
  await gearShown(page);
  const rows = await page.locator("#upgrade-owned > li").count();
  await page.locator("#upgrade-remember-box").check();
  const words = "Couldn't remember your gear: this browser would not store it. The rest of the section works as before.";
  await expect(page.locator("#upgrade-remember-note")).toHaveText(words);
  await expect(page.locator("#announce")).toHaveText(words);
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(rows);
  await expect(question(page)).toBeVisible(); // (the answer is asked for as ever)
  expect(watch.problems()).toEqual([]);
});

test("the page passes the accessibility checks with a shared kit shown", async ({ page }, testInfo) => {
  await open(page, `${TRIO}#k=${sharedPayload()}`);
  await expect(page.locator("#shared-kit-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
  await expect(page.locator("#shared-kit-value")).toContainText("Kit value", { timeout: 60_000 });
  await page.locator("#shared-kit").scrollIntoViewIfNeeded();
  await axe(page, testInfo);
});

test("the page passes the accessibility checks with a link that cannot be read", async ({ page }, testInfo) => {
  await open(page, `${TRIO}#k=!!!`);
  await expect(page.locator("#shared-kit-state")).toHaveText("This kit link could not be read", { timeout: 30_000 });
  await axe(page, testInfo);
});

test("the page passes the accessibility checks with remembered gear, and with Share's field shown", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await recordClipboard(page, { refuse: true });
  await open(page, TRIO);
  await gearShown(page);
  await page.locator("#upgrade-remember-box").check();
  await page.reload();
  await expect(page.locator("#upgrade-forget")).toBeVisible({ timeout: 30_000 });
  await page.locator("#upgrade-remember").scrollIntoViewIfNeeded();
  await axe(page, testInfo); // the restored list, the box and its line with Forget
  await expect(question(page)).toBeVisible();
  await yes(page).click();
  await expect(page.locator("#upgrade-end")).toHaveText(/\S/, { timeout: 90_000 });
  await page.locator("#upgrade-share-button").click();
  await expect(page.locator("#upgrade-share-field")).toBeVisible();
  await page.locator("#upgrade-equip").scrollIntoViewIfNeeded();
  await axe(page, testInfo); // Equip now with Share, and the link in its field
});

test("the shared kit does not make the page wider than the window, whatever its names", async ({ page }) => {
  await open(page, `${TRIO}#k=${sharedPayload()}`);
  await expect(page.locator("#shared-kit-table tbody tr")).toHaveCount(22, { timeout: 30_000 });
  await expect(page.locator("#shared-kit-value")).toContainText("Kit value", { timeout: 60_000 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
