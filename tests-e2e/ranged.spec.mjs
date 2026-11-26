// The bow setup and the Ranged role in a real browser, on the page of the synthetic fixture: its trio (a Paladin, a Monk and a Berserker) has no Ranger and no bow in its
// pool, so its page has none of the new controls, and a link that asks for them means nothing here (the same answer as for any value the page does not offer). The controls of a
// trio that has them are held to the address by tests-js/ranged-page.test.mjs (the page code in jsdom, on the page and the data a run of the precompute made for such a trio) and
// by pipeline/tests/test_ranged_site.py (the page that run makes).

import { TRIO, expect, open, openSwitches, queryOf, readControls, test } from "./support.mjs";

test("a trio with no bow and no Ranger has no Ranged role, no Bow setup, no range line and no note about arrows", async ({ page }) => {
  await open(page, TRIO);
  await openSwitches(page);
  await expect(page.locator("#role-ranged")).toHaveCount(0);
  await expect(page.locator("#setup-ranged")).toHaveCount(0);
  await expect(page.locator("#w-range-row")).toHaveCount(0);
  await expect(page.locator("#weapons")).not.toContainText(/arrow/i);
  const roles = await page.$$eval('input[name="role"]', (inputs) => inputs.map((input) => input.value));
  expect(roles).not.toContain("ranged");
});

test("a link that asks for the Ranged role or the bow setup on such a trio shows the default view and writes the address of it", async ({ page }) => {
  await open(page, TRIO);
  await openSwitches(page);
  const baked = await readControls(page);
  for (const search of ["?role=ranged", "?setup=ranged", "?role=ranged&setup=ranged"]) {
    await open(page, `${TRIO}${search}`);
    await openSwitches(page);
    expect(await readControls(page), search).toEqual(baked);
    const asked = queryOf(page);
    expect(asked.role ?? null, search).not.toBe("ranged");
    expect(asked.setup ?? null, search).not.toBe("ranged");
  }
});
