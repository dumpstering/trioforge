// The items the best kits of a trio's roles have in common (the section "Get these first" of the trio page). Pure: no page, no network. It reads the shard the page already has.
//
// For the race and tier asked, every role the shard has a kit for at that race and tier is compared, each by its best weapon setup (the page's own pick: `shard.bestSetup`, the
// highest kit value and the earlier setup on a tie). An item is counted once for a role however many places it fills in that role's kit. It is in `every` when all the roles wear it, and in
// `most` when more than half of them do but not all. With fewer than two roles there is nothing to compare, and with two there is no "most".
//
// Each entry: `item` (the shard's own item), `place` (the first place of the kit, in the page's order of places, that any role puts it in), `copies` (how many places it fills in each
// role that wears it, when that is the same for all of them; else 1) and `missing` (the roles that do not wear it, in the shard's order of roles). Entries are in order of place, then name.

export function commonItems(shard, race, tier) {
  const roles = [...shard.roles].filter((role) => shard.has(race, role, tier));
  const wearing = new Map(); // item key -> { item, place, worn: role -> the places it fills in that role's kit }
  for (const role of roles) {
    shard.scenario(race, role, tier, shard.bestSetup(race, role, tier)).kit.forEach((item, place) => {
      if (!item) return;
      const entry = wearing.get(item.key) ?? { item, place, worn: new Map() };
      entry.place = Math.min(entry.place, place);
      entry.worn.set(role, (entry.worn.get(role) ?? 0) + 1);
      wearing.set(item.key, entry);
    });
  }
  const found = { roles, every: [], most: [] };
  if (roles.length < 2) return found;
  for (const { item, place, worn } of wearing.values()) {
    const group = worn.size === roles.length ? found.every : worn.size * 2 > roles.length ? found.most : null;
    const copies = new Set(worn.values());
    group?.push({ item, place, copies: copies.size === 1 ? [...copies][0] : 1, missing: roles.filter((role) => !worn.has(role)) });
  }
  const order = (a, b) => a.place - b.place || (a.item.name < b.item.name ? -1 : a.item.name > b.item.name ? 1 : 0);
  found.every.sort(order);
  found.most.sort(order);
  return found;
}
