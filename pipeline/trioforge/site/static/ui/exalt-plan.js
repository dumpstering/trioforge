// The exalt plan in the browser: the recommended effects of a trio and role matched onto the items of a kit, by the same rules as pipeline/trioforge/effects/plan.py.
//
//   planKit({options, kit, items, effects, mass, classes, tier}) -> {rows, noroom}
//
// `options` are the lists of a role as exalt.json holds them (`{focus: [row], click: [row], carry: [row], worn: [row], proc: [row]}`, a row `{e, d, o, s, m, g?}`; only focus, click, worn and
// proc are placed). `kit` is the kit to place them on, `[{place, key, tier?}]` in the order of the 22 places of a kit (PLACES), a `tier` of its own for an item that is not at the kit's
// (an item the visitor owns at another tier); `tier` is the tier of the kit. `items(key)` gives what the matcher needs to know of an item, `{classes, slots, twoHand, arrival}` (`itemInfo` makes
// it from a record of the item table), or null for an item it does not know (such a host is left out, such a donor is not offered). `effects` is a Map from an effect id to its row of
// effects.json (`{k: kind, c: category, d: [[donor key, access cost], ...]}`), `mass` the `mass` of that file (how much each class fights by casting), `classes` the codes of the trio's classes.
// A row of `rows` is `{k, e, d, p, h, c, u}`: the kind, the effect, the donor's key, the place of the host, the host's key, the classes that can use both items and `u` (1 when the donor has to be
// upgraded to the socket's tier). A row of `noroom` is `{k, e, w}` with the reason (REASONS) an effect has no host.
//
// The rules (the wiki's Exaltations page, as the spec of the feature states them): an item has one focus socket at +1, a click socket at +2, a worn socket at +3 and a proc socket at +4. An effect moves
// from its donor item onto a host, a like item that shares a slot with the donor; a 2H or primary-only donor needs a host that can be worn in the primary hand; a class of the trio that gains
// from the effect has to be able to use both items; the host has to have reached the tier of the socket; a host carries one effect of a kind. Within a kind the placement is the one of the greatest
// total score (an exact assignment, the Hungarian method on whole numbers), and a tie goes to the donor that is easiest to get, to a host that is its own donor and to one a class that gains most can use.
//
// A kit below the tier a socket opens at gives "tier" to every effect of that kind; an effect with no copy that a class of the trio can wear gives "donor"; "taken" is for an effect that fitted
// a host that a better effect of its kind has.
//
// This file is a port, and a test (tests-js/exalt-plan.test.mjs) holds it to the plans that Python made of several hundred kits (fixtures/effects/plan-parity.json): the same rows in the same order and
// the same no-room list, to the last tie. The arithmetic follows Python's: `round` goes to the even whole number at a half, and `sum` of floats is the compensated sum of CPython 3.12. The one thing
// this file does that Python's does not is a tier of its own for a host (`kit[i].tier`): Python makes plans for one tier of the kit.

/** The tier at which each exaltation slot opens (effects/layer.py: SLOT_TIER). */
export const SLOT_TIER = Object.freeze({ focus: 1, click: 2, worn: 3, proc: 4 });
/** The kinds that need a socket, in the order the sockets open (effects/plan.py: KINDS). */
export const KINDS = Object.freeze(["focus", "click", "worn", "proc"]);
/** Why an effect has no host (effects/plan.py: REASONS, in its order). */
export const REASON_ORDER = Object.freeze(["donor", "primary", "slot", "class", "tier", "taken"]);
/** The rules a donor and a host are held to, in the order they are checked: of the hosts an effect could not go on, the reason is the one of the furthest it got (effects/plan.py: _STEP). */
const STEP = Object.freeze(["primary", "slot", "class"]);
/** The 22 places of a kit, in kit order (the order of the columns of an assignment, which decides ties). */
export const PLACES = Object.freeze(
  "HEAD FACE EAR1 EAR2 NECK SHOULDERS ARMS BACK WRIST1 WRIST2 HANDS FINGER1 FINGER2 CHEST LEGS FEET WAIST RANGE ANY1 ANY2 PRIMARY SECONDARY".split(" "),
);
/** The classes that fight in melee (model/roles.py: MELEE_CLASSES): a proc needs one of them among the classes that can use both items. */
export const MELEE_CLASSES = Object.freeze(["BER", "BRD", "BST", "MNK", "PAL", "RNG", "ROG", "SHD", "WAR"]);

const SCALE = 1_000_000; // an assignment weight is the score to six decimals, then two bonus points
const BONUS_MEMBER = 1;
const BONUS_OWN = 1;
const MANA_MASS = 0.1; // a class "casts" at this much mass (effects/layer.py: gain_possible)

/** What the matcher knows of an item, from its record in the item table (items.json); `defaults` is the table's `defaults`. */
export function itemInfo(record, defaults = { classes: ["ALL"] }) {
  const skill = typeof record?.weapon?.skill === "string" ? record.weapon.skill : "";
  const rule = record?.tier_rule;
  return {
    classes: Array.isArray(record?.classes) ? record.classes : (defaults.classes ?? ["ALL"]),
    slots: Array.isArray(record?.slots) ? record.slots : [],
    twoHand: skill.startsWith("2H"),
    arrival: rule === "drop" ? 4 : rule === "fixed0" ? 0 : null,
  };
}

/** Python's `round` of a float that is not negative: a half goes to the even whole number. */
export function roundHalfEven(x) {
  const floor = Math.floor(x);
  const rest = x - floor;
  if (rest < 0.5) return floor;
  if (rest > 0.5) return floor + 1;
  return floor % 2 === 0 ? floor : floor + 1;
}

/** Python's `sum` of floats (CPython 3.12: Neumaier's compensated sum), so that a sum of gains is the same number here. */
export function pySum(values) {
  if (values.length === 0) return 0;
  let total = values[0];
  let compensation = 0;
  for (let index = 1; index < values.length; index += 1) {
    const x = values[index];
    const t = total + x;
    if (Math.abs(total) >= Math.abs(x)) compensation += total - t + x;
    else compensation += x - t + total;
    total = t;
  }
  if (compensation !== 0 && Number.isFinite(compensation)) total += compensation;
  return total;
}

function canUse(allowed, cls) {
  return allowed.includes("ALL") || allowed.includes(cls);
}

/** The classes of `classes` that can use an item. */
export function usableBy(info, classes) {
  return classes.filter((cls) => canUse(info.classes, cls));
}

/** A donor that only fits the primary hand: a 2H weapon or an item whose one slot is PRIMARY. */
export function needsPrimary(donor) {
  return donor.twoHand || (donor.slots.length === 1 && donor.slots[0] === "PRIMARY");
}

/** `[null, overlap]` when the donor's effect can sit on the host, else `[the first rule it breaks, []]`. A 2H or primary-only donor needs the host in the primary hand itself (the place PRIMARY),
 * not in the off hand or an Any place; every other rule goes by the host's own slots, wherever it is worn. */
function fit(donor, host, classes, place) {
  if (needsPrimary(donor) && !(place === "PRIMARY" && host.slots.includes("PRIMARY"))) return ["primary", []];
  if (!donor.slots.some((slot) => host.slots.includes(slot))) return ["slot", []];
  const both = classes.filter((cls) => canUse(donor.classes, cls) && canUse(host.classes, cls));
  if (both.length === 0) return ["class", []];
  return [null, both];
}

/** Whether any class of `overlap` can profit from a click, worn effect or proc that is not a focus (effects/layer.py: gain_possible). */
function gainPossible(effect, kind, overlap, classes, mass) {
  if (kind === "proc") {
    const melee = classes.filter((cls) => MELEE_CLASSES.includes(cls));
    return melee.length > 0 ? overlap.some((cls) => melee.includes(cls)) : overlap.length > 0;
  }
  if (effect.c === "mana") return overlap.some((cls) => (mass[cls] ?? 0) >= MANA_MASS);
  return overlap.length > 0;
}

/**
 * The columns that give the greatest total weight, one for each row (null for a row left out: its weight there is 0). The Hungarian method on whole numbers, with a dummy column for each row so that
 * every row has a place; the first column wins among equal totals (the e-maxx algorithm effects/plan.py uses, step for step).
 */
export function assign(weights) {
  const rows = weights.length;
  if (rows === 0) return [];
  const real = weights[0].length;
  const cols = real + rows;
  const cost = weights.map((line) => Array.from({ length: cols }, (_, j) => (j < real ? -line[j] : 0)));
  const u = new Array(rows + 1).fill(0);
  const v = new Array(cols + 1).fill(0);
  const owner = new Array(cols + 1).fill(0);
  const way = new Array(cols + 1).fill(0);
  for (let i = 1; i <= rows; i += 1) {
    owner[0] = i;
    let j0 = 0;
    const minimum = new Array(cols + 1).fill(Infinity);
    const used = new Array(cols + 1).fill(false);
    for (;;) {
      used[j0] = true;
      const i0 = owner[j0];
      let delta = Infinity;
      let j1 = 0;
      for (let j = 1; j <= cols; j += 1) {
        if (!used[j]) {
          const current = cost[i0 - 1][j - 1] - u[i0] - v[j];
          if (current < minimum[j]) {
            minimum[j] = current;
            way[j] = j0;
          }
          if (minimum[j] < delta) {
            delta = minimum[j];
            j1 = j;
          }
        }
      }
      for (let j = 0; j <= cols; j += 1) {
        if (used[j]) {
          u[owner[j]] += delta;
          v[j] -= delta;
        } else minimum[j] -= delta;
      }
      j0 = j1;
      if (owner[j0] === 0) break;
    }
    while (j0 !== 0) {
      const j1 = way[j0];
      owner[j0] = owner[j1];
      j0 = j1;
    }
  }
  const answer = new Array(rows).fill(null);
  for (let j = 1; j <= cols; j += 1) {
    if (owner[j] !== 0 && j - 1 < real && weights[owner[j] - 1][j - 1] > 0) answer[owner[j] - 1] = j - 1;
  }
  return answer;
}

/** The donors an effect has that can be worn, are known and can be used by a class of the trio, the easiest to get first (stable: the file lists them easiest first, then by key). */
function donorsOf(effect, items, classes) {
  const found = [];
  for (const [key, access] of effect.d) {
    const info = items(key);
    if (!info || info.slots.length === 0 || usableBy(info, classes).length === 0) continue;
    found.push({ key, access, ...info });
  }
  return found.sort((a, b) => a.access - b.access || b.slots.length - a.slots.length);
}

/** Place the `options` of a role on the items of `kit` (see the top of this file). */
export function planKit({ options: given, kit, items, effects, mass, classes, tier }) {
  const options = given !== null && typeof given === "object" ? given : {}; // (a file with no entry for the role places nothing)
  const rows = [];
  const noroom = [];
  const places = [];
  for (const entry of kit) {
    if (!entry || typeof entry.key !== "string") continue;
    const info = items(entry.key);
    if (info) places.push({ place: entry.place, key: entry.key, info, tier: Number.isInteger(entry.tier) ? entry.tier : tier });
  }
  for (const kind of KINDS) {
    const entries = Array.isArray(options[kind]) ? options[kind] : [];
    if (entries.length === 0) continue;
    const needs = SLOT_TIER[kind];
    // the kit has not reached the tier the socket opens at: nothing of this kind can be placed (a host of a tier of its own that is below it is left out of this kind; with none left, all are "tier")
    const open = places.filter((host) => host.tier >= needs);
    if (open.length === 0 && (places.length > 0 || tier < needs)) {
      for (const option of entries) noroom.push({ k: kind, e: option.e, w: "tier" });
      continue;
    }
    const cells = [];
    const failed = [];
    for (const option of entries) {
      const effect = effects.get(option.e);
      const donors = effect ? donorsOf(effect, items, classes) : [];
      if (donors.length === 0) {
        cells.push(open.map(() => null));
        failed.push(-2);
        continue;
      }
      const gains = kind === "focus" ? option.g ?? {} : {};
      let deepest = -1;
      const line = [];
      for (const host of open) {
        let best = null;
        for (const donor of donors) {
          let [step, overlap] = fit(donor, host.info, classes, host.place);
          let value = 0;
          if (step === null) {
            if (kind === "focus") {
              const gain = pySum(overlap.map((cls) => gains[cls] ?? 0));
              const full = pySum(usableBy(donor, classes).map((cls) => gains[cls] ?? 0));
              step = gain > 0 ? null : "class";
              value = gain > 0 ? (option.s * gain) / full : 0;
            } else {
              value = option.s;
              step = gainPossible(effect, kind, overlap, classes, mass) ? null : "class";
            }
          }
          if (step !== null) {
            deepest = Math.max(deepest, STEP.indexOf(step));
            continue;
          }
          const bonus = (overlap.includes(option.m) ? BONUS_MEMBER : 0) + (donor.key === host.key ? BONUS_OWN : 0);
          const weight = roundHalfEven(value * SCALE) * 100 + 1 + bonus;
          if (best === null || weight > best.weight) best = { weight, donor, overlap };
        }
        line.push(best);
      }
      cells.push(line);
      failed.push(deepest);
    }
    const chosen = open.length > 0 ? assign(cells.map((line) => line.map((cell) => (cell ? cell.weight : 0)))) : entries.map(() => null);
    entries.forEach((option, index) => {
      const column = chosen[index];
      if (column === null || column === undefined) {
        let reason;
        if (failed[index] === -2) reason = "donor";
        else if (cells[index].some((cell) => cell !== null)) reason = "taken";
        else reason = failed[index] >= 0 ? STEP[failed[index]] : "slot";
        noroom.push({ k: kind, e: option.e, w: reason });
        return;
      }
      const host = open[column];
      const cell = cells[index][column];
      rows.push({
        k: kind,
        e: option.e,
        d: cell.donor.key,
        p: host.place,
        h: host.key,
        c: cell.overlap,
        u: cell.donor.arrival !== null && cell.donor.arrival < needs ? 1 : 0,
      });
    });
  }
  return { rows, noroom };
}
