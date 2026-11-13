// What a phone is sent in pictures: the PNG bytes a 390 x 844 window fetches on the home page, a trio page, an item page, the about, sources and changelog pages and the 404 page stay under 120 KB on
// each page, in the light and in the dark theme (the two themes draw different tiles under the content). The art of the whole build may weigh more (215 KB, `art.BUDGET_BYTES`): what is
// held here is the phone's share, because a picture that is not shown on a phone (display: none on the element that carries it) is never fetched, and a scene that is shown is at 1x.

import { expect, test } from "@playwright/test";

/** The most PNG bytes a phone may fetch on any one page. */
const PHONE_BUDGET_BYTES = 120 * 1024;
const PHONE = { width: 390, height: 844 };
const PAGES = {
  home: "/",
  trio: "/trio/pal-mnk-ber/",
  item: "the first item the kit of the trio page links to",
  about: "/about/",
  sources: "/sources/",
  changelog: "/changelog/",
  notfound: "/this-address-has-no-page/",
};

/** Open a page and return the PNGs it fetched, each as { path, bytes }, once the network is quiet (a picture is fetched when its element is drawn, so the page is scrolled to its end first). */
async function fetchedPictures(page, path) {
  const pictures = new Map();
  page.on("response", async (response) => {
    const url = new URL(response.url());
    if (!url.pathname.endsWith(".png")) return;
    try {
      pictures.set(url.pathname, (await response.body()).length);
    } catch {
      // (a response that was cancelled with the page has no body to count)
    }
  });
  await page.goto(path, { waitUntil: "load" });
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForLoadState("networkidle");
  return [...pictures].map(([pathname, bytes]) => ({ path: pathname, bytes }));
}

for (const scheme of ["light", "dark"]) {
  test.describe(`a phone, ${scheme} theme`, () => {
    test.use({ viewport: PHONE, colorScheme: scheme });

    for (const [name, path] of Object.entries(PAGES)) {
      test(`@once the pictures the ${name} page sends a phone are under 120 KB (${scheme})`, async ({ page, request }) => {
        const address = name === "item" ? (await (await request.get(PAGES.trio)).text()).match(/href="(\/item\/[^"]+)"/)?.[1] : path;
        expect(address, `${name}: an address to open`).toBeTruthy();
        const pictures = await fetchedPictures(page, address);
        const total = pictures.reduce((sum, picture) => sum + picture.bytes, 0);
        expect(pictures.length, `${name} fetched no picture at all: the measure would hold for nothing`).toBeGreaterThan(0);
        expect(total, `${name}: ${pictures.map((p) => `${p.path.split("/").pop()} ${p.bytes}`).join(", ")}`).toBeLessThanOrEqual(PHONE_BUDGET_BYTES);
        // no character is fetched on a phone: the race picture of the trio page would push the first kit row below the first screen, and the two of the footer are not shown
        expect(pictures.filter((p) => /\/race-/.test(p.path)), `${name}: a race picture was fetched`).toEqual([]);
        // the scenes that are not shown on a phone are never fetched
        expect(pictures.filter((p) => /\/(hero-trio|hyenamen|city-gate|campfire)-/.test(p.path)), `${name}: a hidden scene was fetched`).toEqual([]);
      });
    }
  });
}
