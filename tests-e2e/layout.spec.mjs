// The layout polish of the home page and the trio page in a real browser (branch layout-polish): nothing here is about numbers, it is about where things stand and how they wrap, measured with the
// boxes the browser gives (never by eye). The headers of a table do not break inside a word; the Stats buttons stand in one column and the names in another; Race, Role and Tier are one row and the
// assumptions one folded line; the page says what its seals mean once; the home page has one picture beside its text, the picker on the first screen, a status line that is there only once a class is
// chosen, a footer row of links and four badges in an even grid.
//
// A test without @once in its title runs in the four views of playwright.config.mjs (1280 and 360 px wide, light and dark); those that set the width themselves are @once.

import { EXALT_ORIGIN, ORIGIN } from "../playwright.config.mjs";
import { withDonorSources } from "./exalt-source-support.mjs";
import { axe, expect, open, openSwitches, pick, test, TRIO } from "./support.mjs";

const DESKTOP = { width: 1280, height: 800 };
const PHONE = { width: 360, height: 740 };

// ---- headers ---------------------------------------------------------------------------------------------------------------------------------

/** In the page: every word of every column header of every table that the browser has broken over two lines (a row header is an item's name or a label of a figure, and may break anywhere, as a long name must) (a word has one box when it is on one line, and one for each line when it is not). */
function brokenHeaderWords() {
  const broken = [];
  for (const th of document.querySelectorAll('table thead th, table th[scope="col"]')) {
    const walker = document.createTreeWalker(th, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      for (const word of node.data.matchAll(/\S+/g)) {
        const range = document.createRange();
        range.setStart(node, word.index);
        range.setEnd(node, word.index + word[0].length);
        const lines = new Set([...range.getClientRects()].filter((box) => box.width > 0).map((box) => Math.round(box.top / 4)));
        if (lines.size > 1) broken.push(`${th.closest("table")?.id || th.closest("table")?.className || "table"}: ${word[0]} (${th.textContent.trim()})`);
      }
    }
  }
  return broken;
}

async function openEverything(page) {
  await page.evaluate(() => document.querySelectorAll("main details").forEach((details) => (details.open = true)));
  await page.waitForTimeout(150);
}

test("no table header breaks inside a word at 360, 768 or 1280 px, on the trio page, an item page and the sources page @once", async ({ page }) => {
  for (const origin of [ORIGIN, EXALT_ORIGIN]) {
    for (const width of [360, 768, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await open(page, origin + TRIO);
      await openEverything(page);
      expect(await page.evaluate(brokenHeaderWords), `the trio page at ${width} px (${origin})`).toEqual([]);
      if (origin === ORIGIN) {
        const item = await page.locator('#kit-body a[href^="/item/"]').first().getAttribute("href");
        for (const path of [item, "/sources/"]) {
          await open(page, origin + path);
          await openEverything(page);
          expect(await page.evaluate(brokenHeaderWords), `${path} at ${width} px`).toEqual([]);
        }
      }
    }
  }
});

// ---- the Stats buttons and the names of the kit -------------------------------------------------------------------------------------------------

async function kitBoxes(page) {
  return page.$$eval("#kit-body tr", (rows) =>
    rows
      .map((row) => {
        const button = row.querySelector(".kit-more > summary");
        const name = row.querySelector('[data-f="name"]');
        if (!button || row.querySelector(".kit-more")?.hidden || !name?.textContent.trim()) return null;
        const at = (node) => {
          const box = node.getBoundingClientRect();
          return { left: box.left, top: box.top + window.scrollY, width: box.width, height: box.height, center: box.top + window.scrollY + box.height / 2 };
        };
        const line = name.getClientRects()[0];
        const art = row.querySelector("th .art");
        return {
          row: at(row),
          button: at(button),
          name: { ...at(name), line: { top: line.top + window.scrollY, center: line.top + window.scrollY + line.height / 2 } },
          icon: art ? at(art) : null,
          text: name.textContent.trim(),
        };
      })
      .filter(Boolean),
  );
}

test("the Stats buttons stand in one column level with the first line of their names, and the names have one left edge, in the built rows and in the rows the browser draws @once", async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  for (const origin of [ORIGIN, EXALT_ORIGIN]) {
    await open(page, origin + TRIO);
    await openSwitches(page);
    const check = async (when) => {
      const boxes = await kitBoxes(page);
      expect(boxes.length, `${when}: rows with a button`).toBeGreaterThan(5);
      const lefts = new Set(boxes.map((one) => Math.round(one.button.left)));
      expect([...lefts], `${when}: the Stats buttons stand at one x (${origin})`).toHaveLength(1);
      expect(new Set(boxes.map((one) => Math.round(one.name.left))).size, `${when}: the names share one left edge`).toBe(1);
      for (const one of boxes) {
        // the button is level with the first line of its name, whatever else the row holds (a second line, notes under it, a chip), and that line is level with the middle of the picture of the place
        expect(Math.abs(one.button.center - one.name.line.center), `${when}: the button of "${one.text}" is level with its name`).toBeLessThanOrEqual(2);
        if (one.icon) expect(Math.abs(one.name.line.center - one.icon.center), `${when}: the name of "${one.text}" is level with the middle of its picture`).toBeLessThanOrEqual(3);
      }
    };
    await check("built");
    const tiers = await page.locator("#sw-tier option").evaluateAll((options) => options.map((option) => option.value));
    await page.locator("#sw-tier").selectOption(tiers.find((tier) => tier !== "4") ?? tiers[0]);
    await expect(page.locator("#view-summary")).toBeAttached();
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await check("drawn by the browser"); // (the same rules hold when the browser draws the rows: a column of a table is as wide as its cells make it, so its place may differ from one view to the next)
  }
});

/** In the page: every place where a word of the item cell of a row meets the Stats button of that row (the words of the button itself are not counted), as lines of text. */
function buttonClashes() {
  const found = [];
  for (const row of document.querySelectorAll("#kit-body tr")) {
    const cell = row.cells[1];
    const button = row.querySelector(".kit-more > summary");
    if (!button || row.querySelector(".kit-more")?.hidden) continue;
    const near = button.getBoundingClientRect();
    const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!node.data.trim() || button.contains(node)) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const box of range.getClientRects()) {
        if (box.width < 1) continue;
        const across = Math.min(box.right, near.right) - Math.max(box.left, near.left);
        const down = Math.min(box.bottom, near.bottom) - Math.max(box.top, near.top);
        if (across > 0.5 && down > 0.5) found.push(`${cell.querySelector('[data-f="name"]')?.textContent.trim().slice(0, 40)}: "${node.data.trim().slice(0, 30)}" meets the button by ${across.toFixed(1)} x ${down.toFixed(1)} px`);
      }
    }
  }
  return found;
}

test("the Stats button never meets a word of its row (the name at any length, the haste chip, the notes, the open panel) at 360, 768 and 1280 px @once", async ({ page }) => {
  for (const origin of [ORIGIN, EXALT_ORIGIN]) {
    for (const width of [360, 768, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await open(page, origin + TRIO);
      const swept = async (label) => {
        // a name of every length from 8 characters to 70 (a name that ends just where the button begins is the case), with a chip of haste in every row
        const clashes = await page.evaluate((clashesOf) => {
          const meets = new Function(`return (${clashesOf})`)();
          const long = "Zorblax's Imaginary Girdle of the Unbroken Name and Another Long Word Spelled Out Twice";
          const rows = [...document.querySelectorAll("#kit-body tr")];
          for (const row of rows) {
            if (!row.querySelector(".kit-haste") && row.querySelector(".kit-more")) {
              const chip = document.createElement("span");
              chip.className = "kit-haste";
              chip.textContent = "Haste 36%";
              row.querySelector(".kit-more").before(chip);
            }
          }
          const found = [];
          for (let length = 8; length <= 70 && found.length < 6; length += 1) {
            for (const row of rows) {
              const name = row.querySelector('[data-f="name"]');
              if (name) name.textContent = long.slice(0, length);
            }
            found.push(...meets());
          }
          return [...new Set(found)].slice(0, 6);
        }, buttonClashes.toString());
        expect(clashes, `${label} at ${width} px (${origin})`).toEqual([]);
      };
      await swept("closed");
      await page.locator("#kit-stats-all").click();
      await swept("every panel open");
    }
  }
});

test("the Stats button does not move when its panel opens or closes, on a tall row and on a short one, at 768 and 1280 px @once", async ({ page }) => {
  let spread = 0;
  for (const origin of [ORIGIN, EXALT_ORIGIN]) {
    for (const width of [768, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await open(page, origin + TRIO);
      const boxes = await kitBoxes(page);
      const tall = boxes.reduce((a, b) => (b.row.height > a.row.height ? b : a));
      const short = boxes.reduce((a, b) => (b.row.height < a.row.height ? b : a));
      spread = Math.max(spread, tall.row.height - short.row.height);
      for (const [kind, one] of [["tall", tall], ["short", short]]) {
        const row = page.locator("#kit-body tr", { has: page.locator('[data-f="name"]', { hasText: one.text }) }).first();
        const button = row.locator(".kit-more > summary");
        const place = () =>
          button.evaluate((node) => {
            const rect = node.getBoundingClientRect();
            return { left: rect.left, top: rect.top + window.scrollY, width: rect.width, height: rect.height };
          });
        const before = await place();
        await button.click();
        await expect(row.locator(".kit-more")).toHaveJSProperty("open", true);
        expect(await place(), `the button of the ${kind} row "${one.text}" does not move when its panel opens (${width} px, ${origin})`).toEqual(before);
        await button.click();
        await expect(row.locator(".kit-more")).toHaveJSProperty("open", false);
        expect(await place(), `nor when it closes again (${kind} row, ${width} px)`).toEqual(before);
      }
    }
  }
  expect(spread, "the rows tried include a tall one (notes under the name) and a short one").toBeGreaterThan(15);
});

// With the text of where a donor comes from open under a line of the Exalt hints (branch exalt-source): the text is in the item cell, in the flow, under the line, so it grows the row and nothing else.
test("the Stats button does not move and never meets a word when the source of a donor is open, in every row that has one, with a long text and one that has no space, at 360, 768 and 1280 px @once", async ({ page }) => {
  await withDonorSources(page);
  let tried = 0;
  for (const width of [360, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await open(page, EXALT_ORIGIN + TRIO);
    await expect(page.locator("#kit-body .exalt-srcbtn").first()).toBeVisible();
    const rows = page.locator("#kit-body tr", { has: page.locator(".exalt-srcbtn") });
    const count = await rows.count();
    expect(count, "rows with a source to open").toBeGreaterThan(3);
    for (let n = 0; n < count; n += 1) {
      const row = rows.nth(n);
      const stats = row.locator(".kit-more > summary");
      const place = () =>
        stats.evaluate((node) => {
          const rect = node.getBoundingClientRect();
          return { left: rect.left, top: rect.top + window.scrollY, width: rect.width, height: rect.height };
        });
      const before = await place();
      const opens = await row.locator(".exalt-srcbtn").all();
      for (const toggle of opens) await toggle.click();
      await expect(row.locator(".exalt-src").first()).toBeVisible();
      expect(await place(), `the Stats button of row ${n + 1} does not move when a source opens (${width} px)`).toEqual(before);
      expect(await page.evaluate(buttonClashes), `a source open in row ${n + 1} meets the Stats button (${width} px)`).toEqual([]);
      // the longest text the page may be given (60 characters), in words and in one word
      for (const text of ["Hollow Vale (a creature whose name runs on and on and on ok)", "Plane_of_Fear_(a_creature_whose_name_has_no_space_at_all_ok)"]) {
        await row.locator(".exalt-src-text").evaluateAll((nodes, value) => nodes.forEach((node) => (node.textContent = value)), text);
        expect(await place(), `nor with a text of 60 characters (${width} px)`).toEqual(before);
        expect(await page.evaluate(buttonClashes), `the long text meets the Stats button (${width} px)`).toEqual([]);
        const overflow = await row.evaluate((node) => node.scrollWidth - node.clientWidth);
        expect(overflow, `the row does not run sideways (${width} px)`).toBeLessThanOrEqual(0);
      }
      for (const toggle of opens) await toggle.click();
      await expect(row.locator(".exalt-src").first()).toBeHidden();
      expect(await place(), `nor when they close again (${width} px)`).toEqual(before);
      tried += 1;
    }
  }
  expect(tried).toBeGreaterThan(9);
});

// ---- the settings block ------------------------------------------------------------------------------------------------------------------------

test("Race, Role and Tier are one row at desktop width and wrap on a phone @once", async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await open(page, TRIO);
  const tops = async () =>
    page.evaluate(() => ["label[for=sw-race]", "#sw-role > legend", "label[for=sw-tier]"].map((selector) => Math.round(document.querySelector(selector).getBoundingClientRect().top)));
  expect(new Set(await tops()).size, "one row at 1280").toBe(1);
  await page.setViewportSize(PHONE);
  await openSwitches(page);
  const stacked = await tops();
  expect(stacked[0] < stacked[1] && stacked[1] < stacked[2], `wrapped on a phone: ${stacked}`).toBe(true);
});

test("the assumptions are one folded line that says the choices, opens from the keyboard, and shows at once that one is not the default", async ({ page }) => {
  await open(page, TRIO);
  await openSwitches(page, { assumptions: false });
  const disclosure = page.locator("details#assumes");
  const summary = page.locator("#assumes > summary");
  await expect(disclosure).toHaveJSProperty("open", false);
  await expect(summary).toBeVisible();
  const line = (await summary.innerText()).replace(/\s+/g, " ");
  expect(line, "it says what is assumed").toMatch(/^Assumptions: /);
  expect(line).toContain(await page.locator('[data-f="assume-buffs"]').first().textContent());
  expect(line).toContain(await page.locator('[data-f="assume-setup"]').first().textContent());
  expect(line, "nothing is changed yet").not.toMatch(/changed/i);
  await expect(page.locator("#assume-buffs")).toBeHidden();
  // a block of settings that is compact: the folded line is under the row of the three choices, and one line tall
  const box = await summary.boundingBox();
  const phone = (await page.viewportSize()).width < 600;
  expect(box.height, phone ? "the folded line is one or two lines on a phone" : "the folded line is one line").toBeLessThanOrEqual(phone ? 96 : 64);
  // it opens with the keyboard alone, and the controls inside are today's
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(disclosure).toHaveJSProperty("open", true);
  await expect(page.locator("#assume-buffs")).toBeVisible();
  await expect(page.locator("#assume-weapons")).toBeVisible();
  await expect(page.locator("#assume-weights")).toBeVisible();
  await expect(page.locator("#assume-aa")).toBeVisible();
  // a choice that is not the default shows in the folded line, and says so, without opening anything
  await page.locator("#assume-buffs > summary").click();
  await pick(page, "buffs-group");
  await expect(page.locator('[data-f="assume-buffs"]').first()).toHaveText("common group buffs", { timeout: 30_000 });
  await summary.focus();
  await page.keyboard.press("Space");
  await expect(disclosure).toHaveJSProperty("open", false);
  const changed = (await summary.innerText()).replace(/\s+/g, " ");
  expect(changed).toContain("common group buffs");
  expect(changed).toMatch(/changed/i);
});

test("the assumptions line is the next stop after the three choices and the link that explains the roles @once", async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await open(page, TRIO);
  await page.locator("#sw-tier").focus();
  await page.keyboard.press("Tab");
  await expect(page.locator(".controls .hint a")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.locator("#assumes > summary")).toBeFocused();
  await page.keyboard.press("Tab"); // closed: its three assumptions are not stops, the next is the button that opens every row's stats
  await expect(page.locator("#kit-stats-all")).toBeFocused();
});

// ---- accessibility with the assumptions folded ---------------------------------------------------------------------------------------------------

test("axe: the trio page with the switches open and the Assumptions line closed", async ({ page }, testInfo) => {
  await open(page, TRIO);
  await openSwitches(page, { assumptions: false });
  await expect(page.locator("#assumes")).toHaveJSProperty("open", false);
  await axe(page, testInfo);
});

test("axe: the trio page with the Assumptions line closed and saying Assumptions changed", async ({ page }, testInfo) => {
  await open(page, TRIO);
  await openSwitches(page);
  await page.locator("#assume-buffs > summary").click();
  await pick(page, "buffs-group");
  await expect(page.locator('[data-f="assume-buffs"]').first()).toHaveText("common group buffs", { timeout: 30_000 });
  await page.locator("#assumes > summary").click();
  await expect(page.locator("#assumes")).toHaveJSProperty("open", false);
  await expect(page.locator("#assumes > summary")).toContainText("Assumptions changed");
  await axe(page, testInfo);
});

// ---- the key to the seals ----------------------------------------------------------------------------------------------------------------------

test("the page says once what a Developer and a Model marker mean, and every one of them says it in a title", async ({ page }) => {
  await open(page, TRIO);
  const key = page.locator("#seal-key");
  await expect(key).toHaveCount(1);
  await expect(key).toBeVisible();
  const text = (await key.innerText()).replace(/\s+/g, " ");
  expect(text).toContain("a developer statement or patch note");
  expect(text).toContain("our or EQEmu's formula, or a judgment constant");
  // it comes before the kit and the lists of rules in the page (what is read, and what is tabbed to, in this order)
  const order = await page.evaluate(() => {
    const key = document.getElementById("seal-key");
    const follows = (id) => Boolean(key.compareDocumentPosition(document.getElementById(id)) & Node.DOCUMENT_POSITION_FOLLOWING);
    return [follows("kit"), follows("kit-rules")];
  });
  expect(order, "the key is before the kit and before the rules line of the kit").toEqual([true, true]);
  // where it stands: under the settings and above the kit on a wide window; on a phone, where the first row of the kit has to be on the first screen, under the kit
  const where = await page.evaluate(() => {
    const box = (selector) => document.querySelector(selector).getBoundingClientRect();
    return { key: box("#seal-key"), kit: box("#kit"), settings: box("#assumes"), wide: window.innerWidth > 600, width: window.innerWidth };
  });
  if (where.wide) {
    expect(where.key.bottom, "above the kit").toBeLessThanOrEqual(where.kit.top);
    expect(where.key.top, "under the settings block").toBeGreaterThanOrEqual(where.settings.bottom);
    if (where.width >= 1200) expect(where.key.height, "one line at 1280 px").toBeLessThan(32);
  } else {
    expect(where.key.top, "under the kit, on a phone").toBeGreaterThanOrEqual(where.kit.bottom - 1);
  }
  const untitled = await page.$$eval(".seal-developer, .seal-model", (seals) => seals.filter((seal) => !seal.closest("#seal-key") && !(seal.getAttribute("title") ?? "").trim()).map((seal) => seal.textContent.trim()));
  expect(untitled, "Developer and Model markers with no title").toEqual([]);
  expect(await page.locator(".seal-model[title]").first().getAttribute("title")).toBe("our or EQEmu's formula, or a judgment constant");
  // the marker in the sidebar is one of them
  expect(await page.locator(".data-strip .seal").first().getAttribute("title")).toContain("developer statement");
});

// ---- no layout shift ----------------------------------------------------------------------------------------------------------------------------

// What this change made does not move when the page code starts: the first words and their picture, the folded assumptions and the three choices, the key, the status line of the picker, the chips, the
// footer's links and badges. (Other things move, as they did: the picker of the home page is hidden in the page until the code runs, so that a visitor without it has the list of links, and what stands
// under it moves with it; the theme button of the menu is hidden until then; the kit's rows are painted again. The browser's own sum of them depends on how soon the code runs, and is not held here.)
const MINE = ".intro, .controls, #assumes, #seal-key, #picker-status, .chips, .foot-links, .badges, .badge-row";
for (const [name, path] of [["home", "/"], ["trio", TRIO]]) {
  test(`the parts of the ${name} page that this change made do not move when its code starts`, async ({ page }) => {
    await page.addInitScript((mine) => {
      window.__moved = [];
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          for (const source of entry.sources ?? []) {
            const node = source.node;
            if (node && node.closest?.(mine)) window.__moved.push(`${node.nodeName}#${node.id}.${node.className} (${entry.value.toFixed(4)})`);
          }
        }
      }).observe({ type: "layout-shift", buffered: true });
    }, MINE);
    await open(page, path);
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    expect(await page.evaluate(() => window.__moved), "what moved").toEqual([]);
  });
}

// ---- the home page -----------------------------------------------------------------------------------------------------------------------------

const box = (page, selector) => page.locator(selector).first().evaluate((node) => {
  const rect = node.getBoundingClientRect();
  return { left: rect.left, top: rect.top + window.scrollY, right: rect.right, bottom: rect.bottom + window.scrollY, width: rect.width, height: rect.height };
});

test("the class picker starts on the first screen at 1280 x 800, and within one and a half screens at 360 x 740 @once", async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await open(page, "/");
  const wide = await box(page, "#picker");
  expect(wide.top, "the picker starts on the first screen").toBeLessThan(DESKTOP.height);
  expect((await box(page, ".chips")).bottom, "and its chips are all on it").toBeLessThanOrEqual(DESKTOP.height);
  await page.setViewportSize(PHONE);
  await open(page, "/");
  expect((await box(page, "#picker")).top, "the picker starts within one and a half screens of a phone").toBeLessThanOrEqual(PHONE.height * 1.5);
});

test("the home page has one picture, the archway, beside the first words at desktop width and above or below them on a phone @once", async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await open(page, "/");
  await expect(page.locator("main figure.shot")).toHaveCount(1);
  await expect(page.locator("main figure.shot-hero-trio")).toHaveCount(1);
  const [lead, picture] = [await box(page, "main .lead"), await box(page, "main figure.shot")];
  expect(picture.left, "beside the words, on their right").toBeGreaterThanOrEqual(lead.right - 1);
  expect(picture.top < lead.bottom && picture.bottom > lead.top, "on the same lines as the words").toBe(true);
  expect(picture.height, "smaller than the 2x picture it was (297 px with its frame)").toBeLessThan(220);
  await page.setViewportSize(PHONE);
  await open(page, "/");
  await expect(page.locator("main figure.shot-hero-trio")).toBeVisible();
  const [phoneLead, phonePicture] = [await box(page, "main .lead"), await box(page, "main figure.shot")];
  expect(phonePicture.top >= phoneLead.bottom - 1 || phonePicture.bottom <= phoneLead.top + 1, "stacked, not beside").toBe(true);
  expect(phonePicture.height, "capped in height").toBeLessThanOrEqual(170);
  expect(phonePicture.right, "inside the window").toBeLessThanOrEqual(PHONE.width);
});

test("Pick three classes is said once on the home page: the heading says it, the group label is for a screen reader, and the status line is there only once a class is chosen", async ({ page }) => {
  await open(page, "/");
  const sayings = await page.evaluate(() => {
    const visible = (node) => {
      const rect = node.getBoundingClientRect();
      return rect.width > 2 && rect.height > 2 && getComputedStyle(node).visibility === "visible";
    };
    return [...document.querySelectorAll("#picker h2, #picker legend, #picker-status")].filter(visible).map((node) => node.textContent.trim());
  });
  expect(sayings, "what is seen of the picker's three sayings").toEqual(["Pick your three classes"]);
  const legend = page.locator("#picker legend");
  await expect(legend, "the group label stays for a screen reader").toHaveText(/choose three/i);
  const status = page.locator("#picker-status");
  await expect(status).toHaveAttribute("role", "status");
  await expect(status).toHaveAttribute("aria-live", "polite");
  await expect(status, "no words in it yet").toHaveText("");
  expect((await box(page, "#picker-status")).height, "and no room").toBeLessThanOrEqual(2);
  await pick(page, "class-PAL");
  await expect(status).toHaveText("Pick 2 more classes.");
  expect((await box(page, "#picker-status")).height, "it is shown once a class is chosen").toBeGreaterThan(10);
  await pick(page, "class-PAL", false);
  await expect(status).toHaveText("");
});

test("the first words of the home page say what a trio is", async ({ page }) => {
  await open(page, "/");
  const first = (await page.locator("main .lead").innerText()).replace(/\s+/g, " ");
  expect(first).toBe("A trio is the three classes one character combines in EverQuest Legends. Pick three classes and see the one kit to wear: exact answers, with the evidence and the confidence behind every rule. TrioForge is a fan project.");
  expect(first.match(/EverQuest Legends/g), "the game is named once").toHaveLength(1);
});

// ---- the footer ---------------------------------------------------------------------------------------------------------------------------------

test("the footer has one row of links that wraps cleanly with no separator at its start, its end or its wraps, at every width @once", async ({ page }) => {
  for (const width of [320, 360, 768, 1280]) {
    await page.setViewportSize({ width, height: 800 });
    await open(page, "/");
    const row = await page.evaluate(() => {
      const items = [...document.querySelectorAll(".foot-links > li")];
      return {
        count: items.length,
        texts: items.map((item) => item.textContent.replace(/\s+/g, " ").trim()),
        boxes: items.map((item) => {
          const rect = item.getBoundingClientRect();
          return { left: rect.left, right: rect.right, middle: rect.top + rect.height / 2 };
        }),
        all: document.querySelector(".foot-links")?.textContent.replace(/\s+/g, " ").trim() ?? "",
        overflow: document.documentElement.scrollWidth - window.innerWidth,
      };
    });
    expect(row.count, `three links at ${width} px`).toBe(3);
    expect(row.texts.slice(1), "About and Changelog").toEqual(["About", "Changelog"]);
    for (const text of row.texts) expect(text, `no separator at the start or the end of "${text}"`).not.toMatch(/^[\s·|/•-]|[\s·|/•-]$/);
    expect(row.all, "no separator anywhere in the row").not.toMatch(/[·|•]/);
    expect(row.overflow, "the page is not wider than the window").toBeLessThanOrEqual(0);
    // (the links are level with each other by their middles: a text and a link have not the same height)
    if (width >= 768) expect(Math.max(...row.boxes.map((one) => one.middle)) - Math.min(...row.boxes.map((one) => one.middle)), `one line at ${width} px`).toBeLessThanOrEqual(3);
  }
});

test("the four badges are an even grid at every width, and the Notepad badge is a link to the Changelog @once", async ({ page }) => {
  for (const width of [360, 768, 1280]) {
    await page.setViewportSize({ width, height: 800 });
    await open(page, "/");
    const badges = await page.$$eval(".badges .badge", (nodes) =>
      nodes.map((node) => {
        const rect = node.getBoundingClientRect();
        return { top: Math.round(rect.top), left: Math.round(rect.left), width: Math.round(rect.width), text: node.textContent.trim(), href: node.getAttribute("href") };
      }),
    );
    expect(badges, `four badges at ${width} px`).toHaveLength(4);
    const rows = [...new Set(badges.map((one) => one.top))];
    const per = rows.map((top) => badges.filter((one) => one.top === top).length);
    expect(per.every((count) => count === per[0]) && [1, 2, 4].includes(per[0]), `an even grid at ${width} px: ${JSON.stringify(per)}`).toBe(true);
    expect(new Set(badges.map((one) => one.width)).size, `badges of one width at ${width} px`).toBe(1);
    expect(badges.some((one) => /notepad/i.test(one.text)), "the Notepad badge is gone").toBe(false);
    expect(badges.filter((one) => one.href === "/changelog/"), "a badge that links to the Changelog").toHaveLength(1);
  }
});
