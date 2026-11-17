// What the browser tests of "where a donor comes from" share (branch exalt-source).
//
// The page draws the texts of a donor from `src` of the shared effects file (data/effects.json): for each donor a list of the texts the Source column of a kit row says of its sources (the kind the word of the
// line names first, at most four) and, after them, when more did not fit, the count of the others. The build makes them from the catalog the results were made from. The synthetic fixture the browser
// tests are built from has no catalog (it is built with --no-item-catalog), so its file has no `src`: `withDonorSources` gives each donor of the file a list on its way to the page, by a route, and hands the
// tests the file as the page got it, so that the page is held to the data it was given and not to its own code. Results that are a release's (TRIOFORGE_RESULTS) have `src` already, and are left as they are.

/** Invented lists in the words of a Source column: one text; two; four and three more that did not fit; a crafted one; a long text (the most there is, 60 characters) and a word of 60 characters with no space; and
 * one that is markup if it were read as such. */
export const SOURCE_LISTS = [
  ["Lake of Ill Omen (a fixture lurker)"],
  ["quest: Fixture Rite", "Hollow Vale (a fixture shade)"],
  ["vendor: Fixture Market", "Plane of Fear (a fixture wraith)", "quest: Rite of Tinkers", "crafted: Fixture Forge", 3],
  ["crafted: Fixture Forge"],
  ["Hollow Vale (a creature whose name runs on and on and on ok)", "Plane_of_Fear_(a_creature_whose_name_has_no_space_at_all_ok)"],
  ['Plane of Fear (<b>a fixture</b> & "quoted")', "quest: Fixture Rite"],
];

/** The texts of an entry of `src` (the strings of it). */
export const textsOf = (entry) => entry.filter((one) => typeof one === "string");
/** How many sources an entry says there are that its texts do not (the count at its end, or 0). */
export const moreOf = (entry) => (Number.isInteger(entry.at(-1)) ? entry.at(-1) : 0);

/**
 * Route the shared effects file of the page so that every donor has a list of texts (unless the file has them). Call it before the page is opened. Returns an object whose `file` is the file as the page
 * got it (set when it has been fetched) and whose `keyOf(name)` is the item key of a donor by its name in that file.
 */
export async function withDonorSources(page) {
  const got = { file: null, keyOf: (name) => Object.entries(got.file.items).find(([, entry]) => entry[0] === name)?.[0] };
  await page.route("**/data/effects.json", async (route) => {
    const response = await route.fetch();
    const document = await response.json();
    if (document.src === undefined) {
      document.src = Object.fromEntries(Object.keys(document.items).sort().map((key, n) => [key, structuredClone(SOURCE_LISTS[n % SOURCE_LISTS.length])]));
    }
    got.file = document;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(document) });
  });
  return got;
}
