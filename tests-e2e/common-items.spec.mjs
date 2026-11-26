// "Get these first" in a real browser: the section below Wear this that lists the items most of the trio's roles wear. It is a closed details whose summary and empty body are in the page. Nothing is
// fetched for it before it is opened: opening it loads the shard of the view shown (the baked answer has none), and any change of view that loads a shard draws it too, open or closed; it is
// drawn again when the race, the tier or the shard changes, and never for the role or the weapons.
//
// A test without @once runs in the four views of playwright.config.mjs (1280 and 360 px wide, light and dark). What the section must say is worked out here from the data file the page is made from (support.mjs
// reads it the plain way), never from the page's own code, so the tests run unchanged on the fixture build and on real results.

import { DATA, TRIO, axe, expect, loadShard, open, openAssumptions, openSwitches, pick, test } from "./support.mjs";

const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

/** The items the best kits of the roles have in common, as the section must list them: [names of "every role", names of "most roles"], each by the first place of the kit, then by name. */
function commonOf(shard, race, tier) {
  const roles = shard.roles.filter((role) => shard.best(race, role, tier) !== null);
  const worn = new Map();
  for (const role of roles) {
    shard.scenario(race, role, tier, shard.best(race, role, tier)).kit.forEach((item, place) => {
      if (!item) return;
      const entry = worn.get(item[0]) ?? { name: item[1], place, roles: new Set() };
      entry.place = Math.min(entry.place, place);
      entry.roles.add(role);
      worn.set(item[0], entry);
    });
  }
  const order = (a, b) => a.place - b.place || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
  const all = [...worn.values()];
  if (roles.length < 2) return [[], []];
  return [
    all.filter((entry) => entry.roles.size === roles.length).sort(order).map((entry) => entry.name),
    all.filter((entry) => entry.roles.size < roles.length && entry.roles.size * 2 > roles.length).sort(order).map((entry) => entry.name),
  ];
}

const listed = (page, group) => page.locator(`#common-body ul[data-group="${group}"] > li`).evaluateAll((items) => items.map((li) => li.querySelector("a, .common-name").textContent));

/** The shard the page is made from, and the race and tier it shows. */
async function shown(page, request) {
  const evidence = (await page.locator("#main").getAttribute("data-ev")) ?? "wiki";
  const shard = await loadShard(request, evidence, "own");
  return { shard, race: await page.locator("#sw-race").inputValue(), tier: Number(await page.locator("#sw-tier").inputValue()) };
}

/** The words the summary must say for these two counts. */
const wordsFor = (every, most) =>
  `Get these first: ${[every > 0 ? `${every} ${every === 1 ? "item" : "items"} every role wears` : "", most > 0 ? `${most} ${every === 0 ? (most === 1 ? "item " : "items ") : ""}most roles wear` : ""].filter(Boolean).join(", ")}`;

test("the section is a closed summary until it is opened, asks for no data before that, then lists the items in two lists, and passes axe without scrolling the page sideways", async ({ page, request, watch }, testInfo) => {
  const shardRequests = [];
  page.on("request", (made) => {
    if (/\/data\/pal-mnk-ber\/(?:strict|wiki)-(?:own|group)\.json$/.test(made.url())) shardRequests.push(made.url());
  });
  await open(page, TRIO);
  const section = page.locator("#common");
  await expect(section).toBeVisible();
  await expect(section).not.toHaveAttribute("open", "");
  await expect(section.locator("summary")).toHaveText("Get these first");
  // directly below Wear this: the next sibling of the answer section is the section, and the next sibling of the section is Why this kit (nothing is between them)
  const neighbours = await page.evaluate(() => {
    const answer = document.querySelector('section.answer[aria-labelledby="wear-h"]');
    const box = document.querySelector("#common");
    return { below: answer.nextElementSibling === box, next: box.nextElementSibling?.id, above: box.previousElementSibling === answer };
  });
  expect(neighbours).toEqual({ below: true, next: "why", above: true });
  await page.waitForTimeout(1_500); // (the page's idle time: nothing was asked for the section)
  expect(shardRequests, "no data file is asked for before the section is opened").toEqual([]);
  const { shard, race, tier } = await shown(page, request);
  const [every, most] = commonOf(shard, race, tier);
  expect(every.length + most.length, "the fixture has items in common").toBeGreaterThan(0);
  await section.locator("summary").click();
  await expect(section).toHaveAttribute("open", "");
  await expect(section.locator("summary")).toHaveText(wordsFor(every.length, most.length));
  await expect(page.locator("#common-body")).toBeVisible();
  const headings = await page.locator("#common-body h3").allTextContents();
  expect(headings).toEqual([every.length > 0 ? "Every role" : null, most.length > 0 ? "Most roles" : null].filter(Boolean));
  await expect(page.locator("#common-body ul")).toHaveCount(headings.length);
  expect(await listed(page, "every")).toEqual(every);
  expect(await listed(page, "most")).toEqual(most);
  // each row: the name as a link to the item's page, then its slot, how it arrives and where it comes from
  const row = page.locator("#common-body li").first();
  await expect(row.locator("a")).toHaveAttribute("href", /^\/item\/[a-z0-9-]+\/$/);
  await expect(row.locator(".common-how")).toHaveText(/^Slot: .+\. Arrives at: (?:\+\d+|spell rank)(?:, [\d,]+ copies to reach \+\d+)?\. Source: .+$/);
  await expect(page.locator("#common-body p.note")).toHaveText("The items each role's best kit has in common at this race and tier. Exalt advice differs by role: see Wear this. Each role uses its own best weapon setup.");
  expect(await overflow(page), "no sideways scroll with the section open").toBeLessThanOrEqual(0);
  const box = await page.locator("#common").boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width, "the section is inside the window").toBeLessThanOrEqual(page.viewportSize().width);
  await axe(page, testInfo);
  // closing it and opening it again asks for nothing
  const asked = shardRequests.length;
  await section.locator("summary").click();
  await section.locator("summary").click();
  await expect(section).toHaveAttribute("open", "");
  expect(shardRequests).toHaveLength(asked);
  expect(watch.problems()).toEqual([]);
});

test("the rows of the second group name the roles that do not wear the item, in the words of the role switch", async ({ page, request, watch }) => {
  await open(page, TRIO);
  const { shard, race, tier } = await shown(page, request);
  const [, most] = commonOf(shard, race, tier);
  test.skip(most.length === 0, "no item is worn by most roles but not all in this view");
  await page.locator("#common > summary").click();
  await expect(page.locator("#common > summary")).toContainText("most roles wear");
  const labels = await page.locator('input[name="role"]').evaluateAll((radios) => radios.map((radio) => radio.dataset.label));
  const notes = await page.locator('#common-body ul[data-group="most"] .common-miss').allTextContents();
  expect(notes).toHaveLength(most.length);
  for (const note of notes) {
    const missing = note.replace(/^not /, "").split(/, | or /);
    expect(missing.length).toBeGreaterThan(0);
    for (const word of missing) expect(labels, `"${word}" is a role of the page`).toContain(word);
  }
  expect(watch.problems()).toEqual([]);
});

test("it follows the tier and the race, closed or open, and not the role or the weapons: the same list stays put when they change", async ({ page, request, watch }) => {
  await open(page, TRIO);
  const { shard } = await shown(page, request);
  await openSwitches(page);
  const tiers = await page.locator("#sw-tier option").evaluateAll((options) => options.map((option) => option.value));
  const races = await page.locator("#sw-race option").evaluateAll((options) => options.map((option) => option.value));
  // a change of view draws the section though it is closed: the summary says what the shard says of that race and tier
  await page.locator("#sw-tier").selectOption(tiers.at(-1));
  await expect(page.locator('[data-f="v-tier"]')).toHaveText(`+${tiers.at(-1)}`);
  await page.locator("#sw-race").selectOption(races.at(-1));
  await expect(page.locator('[data-f="v-race"]')).toHaveText((await page.locator("#sw-race option").last().getAttribute("data-label")) ?? "");
  const [every, most] = commonOf(shard, races.at(-1), Number(tiers.at(-1)));
  await expect(page.locator("#common > summary")).toHaveText(wordsFor(every.length, most.length));
  await expect(page.locator("#common")).not.toHaveAttribute("open", "");
  await page.locator("#common > summary").click();
  expect(await listed(page, "every")).toEqual(every);
  expect(await listed(page, "most")).toEqual(most);
  // the role and the weapons do not touch it: the elements of the lists are the very ones that were there
  await page.evaluate(() => (document.querySelector("#common-body ul").dataset.mark = "drawn"));
  const before = await page.locator("#common-body").textContent();
  await pick(page, "role-melee");
  await expect(page.locator("#kit-caption")).toContainText("Melee");
  await openSwitches(page);
  await page.locator("#assume-weapons > summary").click();
  const other = await page.locator('input[name="setup"]:not([disabled]):not(:checked)').first().getAttribute("id");
  const wasSetup = await page.locator('[data-f="v-setup"]').textContent();
  await pick(page, other);
  await expect(page.locator('[data-f="v-setup"]')).not.toHaveText(wasSetup);
  await pick(page, "role-tank");
  await expect(page.locator("#kit-caption")).toContainText("Tank");
  await expect(page.locator("#common-body ul").first()).toHaveAttribute("data-mark", "drawn");
  expect(await page.locator("#common-body").textContent()).toBe(before);
  expect(watch.problems()).toEqual([]);
});

test("a shard that does not load when the section is opened closes it again with its summary, and no word of the failure @once", async ({ page, watch }) => {
  await open(page, TRIO);
  await page.route(`**${DATA}*-own.json`, (route) => route.abort("failed"));
  const asked = page.waitForEvent("requestfailed", { predicate: (request) => request.url().includes("-own.json"), timeout: 15_000 });
  await page.locator("#common > summary").click();
  await asked;
  await expect(page.locator("#common")).not.toHaveAttribute("open", "");
  await expect(page.locator("#common > summary")).toHaveText("Get these first");
  await expect(page.locator("#common")).toBeVisible();
  await expect(page.locator("#status")).toHaveText("");
  expect(await page.locator("#common-body").evaluate((node) => node.childNodes.length)).toBe(0);
  expect(watch.problems(["console", "requestfailed"]), "nothing but the failed request went wrong").toEqual([]);
  // with the data back, opening it again shows the lists
  await page.unroute(`**${DATA}*-own.json`);
  await page.locator("#common > summary").click();
  await expect(page.locator("#common-body ul").first()).toBeVisible();
});

test("the summary keeps its height when it is filled and when it is emptied while a shard loads, so that nothing under it moves, at the widths of a phone and up @once", async ({ page }) => {
  // the longest shape of the words ("Get these first: 13 items every role wears, 6 most roles wear") wraps on a phone: its room has to be there from the start (the fixture's trio offers two builds, so
  // no item is worn by most roles but not all, and the words are the short shape)
  const SHAPE = /^Get these first: \d+ items every role wears(?:, \d+ most roles wear)?$/;
  const height = () => page.locator("#common > summary").evaluate((node) => node.getBoundingClientRect().height);
  const near = (a, b, why) => expect(Math.abs(a - b), `${why}: ${a} and ${b}`).toBeLessThan(0.5);
  for (const width of [320, 360, 390, 600, 640, 1280]) {
    await page.setViewportSize({ width, height: 740 });
    let release;
    const gate = new Promise((go) => (release = go));
    await page.route("**/data/pal-mnk-ber/*-group.json", async (route) => {
      await gate;
      await route.continue();
    });
    await open(page, TRIO);
    const summary = page.locator("#common > summary");
    const shut = await height();
    await expect(summary).toHaveText("Get these first");
    await summary.click(); // opens it: the shard of the default view is loaded, and the summary is filled
    await expect(summary).toHaveText(SHAPE);
    const filledOpen = await height();
    await summary.click(); // closed again, with what it says kept
    await expect(page.locator("#common")).not.toHaveAttribute("open", "");
    near(await height(), shut, `${width} px: the summary is as high shut and filled as it was shut and empty`);
    await summary.click();
    if (width <= 600) await page.locator("#switches-toggle").click(); // (on a phone the switches are behind the Change button)
    await openAssumptions(page);
    await page.locator("#assume-buffs > summary").click();
    await pick(page, "buffs-group"); // another shard, held back: the section is emptied
    await expect(summary).toHaveText("Get these first");
    const emptiedOpen = await height();
    near(emptiedOpen, filledOpen, `${width} px: the open summary is as high emptied as it was filled`);
    release(); // the shard comes: the section is filled again
    await expect(summary).toHaveText(SHAPE);
    near(await height(), filledOpen, `${width} px: and as high filled again`);
    // (not vacuous: the words do take two lines at 360 px, and the room is kept for them from the start; at 1280 px they are one line and no second is kept)
    if (width === 360) for (const high of [shut, filledOpen]) expect(high, "two lines at 360 px, shut and empty as well as filled").toBeGreaterThan(60);
    if (width === 1280) for (const high of [shut, filledOpen]) expect(high, "one line at 1280 px").toBeLessThan(50);
    await page.unroute("**/data/pal-mnk-ber/*-group.json");
  }
});

test("the keyboard opens it and closes it: the summary takes the focus, Enter opens and fills it, the next Tab is the first link in it, and Space closes it", async ({ page, watch }) => {
  await open(page, TRIO);
  const section = page.locator("#common");
  const summary = page.locator("#common > summary");
  await summary.focus();
  await expect(summary).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(section).toHaveAttribute("open", "");
  await expect(summary).toHaveText(/^Get these first: \d+ items every role wears/);
  await expect(page.locator("#common-body ul").first()).toBeVisible();
  await expect(summary).toBeFocused(); // (the focus stays on the summary: opening it moves nothing)
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => document.activeElement?.getAttribute("href")), "the next stop is the link of the first item").toMatch(/^\/item\/[a-z0-9-]+\/$/);
  expect(await page.evaluate(() => document.activeElement?.closest("#common-body") !== null)).toBe(true);
  await page.keyboard.press("Shift+Tab");
  await expect(summary).toBeFocused();
  await page.keyboard.press("Space");
  await expect(section).not.toHaveAttribute("open", "");
  await page.keyboard.press("Enter"); // and open again: what it says is still there
  await expect(section).toHaveAttribute("open", "");
  await expect(page.locator("#common-body ul").first()).toBeVisible();
  expect(watch.problems()).toEqual([]);
});
