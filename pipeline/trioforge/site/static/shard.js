// The compact data files the page fetches (written by pipeline/trioforge/site/data.py) and the questions the page asks of them.

export const SETUP_ORDER = ["1h-shield", "2h", "dw", "stick", "ranged"];
/** The setup a build lists first where that is not the first of `SETUP_ORDER` (`_LISTED_FIRST` of model/weapons.py, which a test holds this to): the first of two setups of equal value wins a tie, and for the Caster that is the stat stick. */
export const LISTED_FIRST = { caster: "stick" };
const KIT_SIZE = 22;
const TOTALS_FIELDS = ["ac", "hp", "mana", "end", "haste", "atk", "mr", "fr", "cr", "dr", "pr", "hpreg", "manareg", "endreg"];

function fail(message) {
  throw new Error(message);
}

const EVIDENCE = ["strict", "wiki"];

/** The characters that stand for an icon in a file (a name's place in the file's `icons`), and the one that stands for none (site/data.py: ICON_DIGITS and NO_ICON_DIGIT). */
const ICON_DIGITS = "0123456789bcdfghjklmnpqrstvwxzBCDFGHJKLMNPQRSTVWXZ!#$%()*+,.;=?@[]^_{|}~`";
const NO_ICON = "-";
/** What the name of an icon is: the class of the span that draws it is `art-` and this, so nothing a file holds may be more than letters, digits and hyphens. */
const ICON_NAME = /^icon-[a-z0-9]+(?:-[a-z0-9]+)*$/;

/**
 * The pictures a file carries beside its items (the generator's rule says which an item has; this only reads what it wrote): `icons` (the names, at most as many as there are characters), `ic` (a character
 * for each of the `count` items, in the order of the file: the picture the item has where its place does not decide, which is its own, else the pouch if it fits a held place, else the picture of its page
 * heading) and `pl` (a character for each of the 22 places of a kit: the picture a filled row of it shows for an item with none, which is the place's own in a worn place, the pouch in the range, the main hand
 * and the off hand, and none in an any row, where the item's character decides). Each character is a place in `icons` or `-`. Returns `{items, places}` (a name or null for each), or null where the file names no pictures at all; a file that names some and is not what the generator writes is refused as a
 * whole.
 */
export function parseIcons(document, count) {
  const { icons, ic, pl } = document;
  if (icons === undefined && ic === undefined && pl === undefined) return null;
  if (!Array.isArray(icons) || icons.length > ICON_DIGITS.length || typeof ic !== "string" || typeof pl !== "string") fail("bad icons");
  if (!icons.every((name) => typeof name === "string" && name.length <= 48 && ICON_NAME.test(name))) fail("bad icons");
  const items = Array.from(ic);
  const places = Array.from(pl);
  if (items.length !== count || places.length !== KIT_SIZE) fail("bad icons");
  const name = (char) => {
    if (char === NO_ICON) return null;
    const at = ICON_DIGITS.indexOf(char);
    if (at < 0 || at >= icons.length) fail("bad icons");
    return icons[at];
  };
  return { items: items.map(name), places: places.map(name) };
}

/**
 * An item of the file. A shard that carries the stats (`stat_tiers`, the tiers of the shard) ends each item with the text of its stats at each of them, as a row of Wear this says
 * them; the item then has `stats`, a text for each tier. The text is the generator's own: the page only shows it.
 */
function itemOf(entry, statTiers = null) {
  if (!Array.isArray(entry)) fail("bad item");
  const [key, name, rule, arrival, source, evidence, deity, lines] = entry;
  if (typeof name !== "string" || !(arrival === null || Number.isInteger(arrival)) || !EVIDENCE.includes(evidence) || !Array.isArray(deity)) fail("bad item");
  if (statTiers === null) return { key, name, rule, arrival, source, evidence, deity };
  if (!Array.isArray(lines) || lines.length !== statTiers.length || !lines.every((line) => typeof line === "string")) fail("bad item");
  return { key, name, rule, arrival, source, evidence, deity, stats: Object.fromEntries(statTiers.map((tier, index) => [tier, lines[index]])) };
}

/** The tiers a shard carries the stats of, or null where it carries none. */
function statTiersOf(document) {
  const tiers = document.stat_tiers;
  if (tiers === undefined) return null;
  if (!Array.isArray(tiers) || !tiers.every((tier) => Number.isInteger(tier) && tier >= 0) || new Set(tiers).size !== tiers.length) fail("bad stat tiers");
  return tiers;
}

/** The data release a file says it was made from (the page compares it with its own), or null where it names none. */
function releaseOf(document) {
  return typeof document.release === "string" ? document.release : null;
}

function rowKey(race, role, tier, setup) {
  return race + "|" + role + "|" + tier + "|" + setup;
}

/** Whether `value` is a position in a list of `size` entries: a whole number, so that "length" or "1" or 1.5 point at nothing. */
const isIndex = (value, size) => Number.isInteger(value) && value >= 0 && value < size;

export class Shard {
  constructor(document) {
    if (!document || document.v !== 1) fail("not a shard of this version");
    const { items, kits, totals, rows } = document;
    if (![items, kits, totals, rows].every(Array.isArray)) fail("not a shard");
    this.release = releaseOf(document);
    this.evidence = document.ev;
    this.buffs = document.buffs;
    const statTiers = statTiersOf(document);
    this.items = items.map((entry) => itemOf(entry, statTiers));
    // the pictures of the items and of the places of a kit, where the file has them: a row draws an item's own picture (`icon`), else the picture of its place (the pouch in a held place)
    const pictures = parseIcons(document, items.length);
    this.places = pictures === null ? null : pictures.places;
    if (pictures !== null) {
      this.items.forEach((item, index) => {
        item.icon = pictures.items[index];
      });
    }
    // Whatever the page draws from the file is checked here, before it draws, so that a file that is not what the generator writes is
    // refused as a whole (the page says it could not load the view) and never fails half way through a draw. Every kit and every row of
    // totals is checked, whether a row names it or not.
    for (const kit of kits) {
      if (!Array.isArray(kit) || kit.length !== KIT_SIZE || !kit.every((place) => Number.isInteger(place) && place >= -1 && place < items.length)) fail("bad kit");
    }
    for (const row of totals) {
      if (!Array.isArray(row) || row.length !== TOTALS_FIELDS.length || !row.every((number) => Number.isFinite(number))) fail("bad totals");
    }
    this.kits = kits;
    this.totals = totals;
    this.rows = new Map();
    this.roleSetups = new Map();
    this.cells = new Map(); // race -> role -> tiers that have a row (of any setup)
    this.races = new Set();
    this.roles = new Set();
    this.tiers = new Set();
    for (const row of rows) {
      if (!Array.isArray(row) || row.length !== 9) fail("bad row");
      const [race, role, tier, setup, kit, value, gain, totalsIndex, haste] = row;
      if (![race, role, setup].every((name) => typeof name === "string") || !Number.isInteger(tier) || !Number.isInteger(haste)) fail("bad row");
      if (!isIndex(kit, kits.length) || !isIndex(totalsIndex, totals.length) || !Number.isFinite(value) || !Number.isFinite(gain)) fail("bad row");
      this.rows.set(rowKey(race, role, tier, setup), row);
      this.races.add(race);
      this.roles.add(role);
      this.tiers.add(tier);
      if (!this.roleSetups.has(role)) this.roleSetups.set(role, new Set());
      this.roleSetups.get(role).add(setup);
      if (!this.cells.has(race)) this.cells.set(race, new Map());
      if (!this.cells.get(race).has(role)) this.cells.get(race).set(role, new Set());
      this.cells.get(race).get(role).add(tier);
    }
    if (this.rows.size === 0) fail("empty shard");
  }

  /** Whether the shard has a row for this race, role and tier (of any setup): the parts it knows are not the cells it has. */
  has(race, role, tier) {
    return this.cells.get(race)?.get(role)?.has(tier) ?? false;
  }

  /** The setups this role has scenarios for. A setup not listed is never offered. */
  setupsFor(role) {
    const have = this.roleSetups.get(role) ?? new Set();
    const first = LISTED_FIRST[role];
    const order = first === undefined ? SETUP_ORDER : [first, ...SETUP_ORDER.filter((setup) => setup !== first)];
    return order.filter((setup) => have.has(setup));
  }

  scenario(race, role, tier, setup) {
    const row = this.rows.get(rowKey(race, role, tier, setup));
    if (!row) return null;
    const [, , , , kit, value, gain, totalsIndex, hasteAssumed] = row;
    const totals = Object.fromEntries(TOTALS_FIELDS.map((name, index) => [name, this.totals[totalsIndex][index]]));
    return {
      race,
      role,
      tier,
      setup,
      value,
      gain,
      totals,
      hasteAssumed,
      kit: this.kits[kit].map((index) => (index < 0 ? null : this.items[index])),
    };
  }

  /** The role's best setup here: the highest value, the earlier setup on a tie. */
  bestSetup(race, role, tier) {
    let best = null;
    for (const setup of this.setupsFor(role)) {
      const row = this.rows.get(rowKey(race, role, tier, setup));
      if (row && (best === null || row[5] > best.value)) best = { setup, value: row[5] };
    }
    return best ? best.setup : null;
  }
}

export function parseShard(document) {
  return new Shard(document);
}

/**
 * The runner-ups of one role: the file holds every tier of the run, and for each race at each tier the role's best setup and the swaps for each of
 * the 22 places. `view(tier, race)` gives `{ setup, slots }`, or null where the file has none (a tier it does not list, a race it has no view of).
 */
export function parseRunnerups(document) {
  if (!document || document.v !== 2 || !Array.isArray(document.items) || !Array.isArray(document.views) || !Array.isArray(document.tiers)) fail("not runner-ups");
  const tiers = new Set();
  for (const tier of document.tiers) {
    if (!Number.isInteger(tier) || tier < 0 || tiers.has(tier)) fail("bad runner-up tiers");
    tiers.add(tier);
  }
  const items = document.items.map((entry) => itemOf(entry));
  const views = new Map();
  for (const view of document.views) {
    if (!Array.isArray(view) || view.length !== 4) fail("bad runner-up view");
    const [tier, race, setup, slots] = view;
    if (!tiers.has(tier) || typeof race !== "string" || typeof setup !== "string" || !Array.isArray(slots) || slots.length !== KIT_SIZE) fail("bad runner-up view");
    // every swap is checked here, before the page draws from it: an item that points nowhere would fail half way through the table
    for (const swaps of slots) {
      if (!Array.isArray(swaps) || !swaps.every((swap) => Array.isArray(swap) && swap.length === 2 && isIndex(swap[0], items.length) && Number.isFinite(swap[1]))) fail("bad runner-up view");
    }
    const key = tier + "|" + race; // (a tier is digits only, so the first bar ends it, whatever the race is called)
    if (views.has(key)) fail("a runner-up view twice");
    views.set(key, { setup, slots });
  }
  return {
    release: releaseOf(document),
    role: document.role,
    tiers: [...tiers],
    items,
    view: (tier, race) => (Number.isInteger(tier) ? (views.get(tier + "|" + race) ?? null) : null),
  };
}

/**
 * The seals of the robust core: for the default race, each role and tier has 22 labels, made for one weapon setup, evidence level
 * and buff set. `view(role, tier)` gives `{ setup, ev, buffs, labels }`, or null where nothing was sealed; the page compares what
 * was sealed with the view it shows and uses the labels only for that view.
 */
export function parseRobust(document) {
  if (!document || document.v !== 2 || !Array.isArray(document.views)) fail("not robustness data");
  const views = new Map();
  for (const row of document.views) {
    if (!Array.isArray(row) || row.length !== 6) fail("bad robustness view");
    const [role, tier, setup, ev, buffs, labels] = row;
    if (!Array.isArray(labels) || labels.length !== KIT_SIZE || ![setup, ev, buffs].every((value) => typeof value === "string")) fail("bad robustness view");
    views.set(role + "|" + tier, { setup, ev, buffs, labels });
  }
  return { release: releaseOf(document), race: document.race, view: (role, tier) => views.get(role + "|" + tier) ?? null };
}
