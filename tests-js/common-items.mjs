// A small builder of shard files for the tests of the section "Get these first" (common-items.test.mjs and common-items-page.test.mjs): the shard of the fixture is too
// regular to say which items are common to which roles, so these are made by hand. A scenario names the item (by key) in each place of the kit it wants; every other place is empty.

const KIT_SIZE = 22;
const TOTALS = Array.from({ length: 14 }, () => 0);

/**
 * `scenarios`: [{ race, role, tier, setup, value, kit: { place: key } }]; `names`: { key: name } for the items (a key without a name is named by its key).
 * The result is the document a shard file is (`v: 1`), which parseShard reads.
 */
export function shardDocument(scenarios, names = {}, extra = {}) {
  const keys = [];
  const kits = [];
  const rows = [];
  for (const scenario of scenarios) {
    const kit = Array.from({ length: KIT_SIZE }, () => -1);
    for (const [place, key] of Object.entries(scenario.kit)) {
      if (!keys.includes(key)) keys.push(key);
      kit[Number(place)] = keys.indexOf(key);
    }
    kits.push(kit);
    rows.push([scenario.race, scenario.role, scenario.tier, scenario.setup, kits.length - 1, scenario.value ?? 1, 0, 0, 0]);
  }
  const items = keys.map((key) => [key, names[key] ?? key, "fixed0", 4, "Dropped by " + key, "wiki", []]);
  return { v: 1, release: "data-test", ev: "wiki", buffs: "own", items, kits, totals: [TOTALS], rows, ...extra };
}
