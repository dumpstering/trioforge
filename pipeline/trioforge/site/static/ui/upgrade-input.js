// The input of the Upgrade section of a trio page: the gear the visitor has.
//
//   createGearInput(root, {items, trio, doc, win, announce}) -> {owned, toOwnedPairs, onChange, clear, readFile}
//
// `root` is the section the generator writes (templates/upgrade.html.j2), `items` the item table as readItemTable gives it (or a list of its records), `trio` the class codes of
// the page's trio. The visitor gives the gear in two ways, both always on the page: the file that /outputfile inventory writes (chosen with the file input or dropped on the
// section), and the picker (gear-picker.js), which adds an item by name at a tier. What the answers read is the list, one row for each item at each tier with how many are owned
// and, for what came from the file, where each is: `worn`, `bag`, `bank`, `sharedbank`, `cursor` or `keyring` (the parser's names, which "in your bank: move to worn" is made from).
//
//   owned()           [{key, tier, count, locations: [{location, count}]}], by name and tier; a copy, so that nothing a caller does to it changes the list. An item added by name
//                     has no location. A count is 1 to 99, what the protocol takes (engine/protocol.js LIMITS.maxOwnedCount).
//   toOwnedPairs()    [[ident, count], ...] with the ident `key@tier`, as a scenario request names its owned items, at most LIMITS.maxOwnedEntries of them. The list never has more
//                     than the protocol takes: a count past 99 is used as 99, and an item past the 1,000th is left out of the list, and both are SAID, in a note under the controls and
//                     to a screen reader, as they happen: nothing is cut in silence.
//   onChange(cb)      cb() is called after the list changed (not after a read that gave the same list); returns the function that stops it. A callback that throws is ignored.
//   clear()           empties the section: the list, the choices, the notes.
//   readFile(file)    reads a File as the parser does (a refusal is shown in the parser's own words), and resolves to {ok, ...} when the list shows it.
//   restore(entries) puts gear that was remembered on the list: [key, tier, count] each, for an item the item table has (the others are skipped; the remember box, remember.js, checks the
//                     entries before it hands them over). What is restored is the list of an earlier visit, as the file that made it was, so it is a layer of its own that the next file read
//                     replaces (the file read before would have been); what the visitor adds by hand is not in it, and stays. A restored item says "remembered" where a file's says where it is.
//                     The list's own limits apply: a count past 99 is used as 99, and a list past 1,000 items is cut, and both are said in its notes. Nothing is said aloud.
//   takeFiles(files)  what the file input and a drop do with the files they got: one is read, more than one are refused (the page code hands over a file that came before the code did).
//
// What the file says is untrusted. The parser (input/dump.js) has its limits before anything else is done with the file: its size, its lines, its characters. The name of the file is
// never looked at. Everything that comes from the file or the item table is shown as text (textContent, or the value of an attribute): never as markup, and never as an address.
// Nothing is looked up by a name that came from outside in an object: the lookups are Maps. Nothing is stored. Nothing is sent anywhere: the file goes no further than this code.
//
// `initUpgrade(root, env)` is what the trio page runs the first time the section is used (trio.js imports this file then and not before): it reads the manifest of the site
// (engine-manifest.json), compares its data release with the page's, fetches the item table by the path, size and SHA-256 the manifest lists (the worker's own download code,
// engine/download.js), checks the SHA-256 before a byte is read as text, parses it with readItemTable, once for the page, and makes the gear input from it. While that goes on
// the section says so; when it fails the section says what failed and offers Try again, and the focus stays on the button through the retries. A release of the data that is
// not the page's is not used: the page's own "updated" notice is shown (in its status), the section says the same near its controls with a Reload button, and the item table is
// not even asked for.
//
// The section has no live region of its own (the page has two, #status and #announce, and a third would say things twice): what it shows in its line, its banner and its notes
// it says once, through the page's #announce (`announce(text)`), except what the page's own status says already.
//
// A row of the file that the table cannot tell (it fits more than one item, or fits one only by a name that is close) is left out of the list and offered in a banner with a
// Choose button for each item it could be: nothing is picked for the visitor, and the rest of the list does not wait. A name that fits nothing is listed as not in the catalog and
// not scored. A bag is not an item, and is not listed there.

import { ERRORS, parseDump } from "../input/dump.js";
import { matchItems } from "../input/match.js";
import { DATA_FILE, EngineFault, fetchBytes, importWithin, sameOriginUrl, sha256Hex } from "../engine/download.js";
import { readItemTable } from "../engine/items.js";
import { MANIFEST_PATH, fetchTextWithin, parseManifest } from "../engine/manifest.js";
import { LIMITS, STARTUP_COMPILE_MS, STARTUP_STALL_MS } from "../engine/protocol.js";
import { createGearPicker } from "./gear-picker.js";
import { createRemember } from "./remember.js";
import { SECTION_UPDATED, createUpgradeAnswer } from "./upgrade-answer.js";

export { SECTION_UPDATED };

/** How many groups of rows that need a choice, and how many names that are not in the catalog, the banner shows (the rest are counted). */
const MAX_SHOWN = 50;
/** The places of the parser, in the order a row lists them, and the words for them. */
const PLACE_ORDER = ["worn", "bag", "bank", "sharedbank", "cursor", "keyring"];
const PLACE_WORDS = new Map([
  ["worn", "worn"],
  ["bag", "in a bag"],
  ["bank", "in the bank"],
  ["sharedbank", "in the shared bank"],
  ["cursor", "on the cursor"],
  ["keyring", "on the key ring"],
]);
/** The stats a candidate is described by, in the order of a tie. */
const STAT_ORDER = ["AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG", "HASTE"];

const plural = (n, one, many) => (n === 1 ? one : many);
const fmt = (n) => n.toLocaleString("en-US");
/** Where an item that has no place came from: the visitor added it, or it was put back from the device. */
const BY_HAND = "hand";
const REMEMBERED = "remembered";

const COUNT_LIMIT_NOTE = (n) => `${fmt(n)} ${plural(n, "item has", "items have")} more than ${LIMITS.maxOwnedCount} copies: ${LIMITS.maxOwnedCount} are used.`;
const ENTRY_LIMIT_NOTE = (n) =>
  `The optimizer takes at most ${fmt(LIMITS.maxOwnedEntries)} different items: ${fmt(n)} ${plural(n, "was", "were")} left out.`;
const FULL_NOTE = `The list holds at most ${fmt(LIMITS.maxOwnedEntries)} different items. Remove one to add another.`;
const COPIES_NOTE = `You can have at most ${LIMITS.maxOwnedCount} copies of one item at one tier.`;
const ONE_FILE_NOTE = "Drop one file at a time.";

/** "SHOULDERS" -> "Shoulders"; two slots -> "Primary or Secondary". */
function slotWords(slots) {
  const words = (Array.isArray(slots) ? slots : []).filter((slot) => typeof slot === "string").map((slot) => slot.charAt(0) + slot.slice(1).toLowerCase());
  return words.join(" or ");
}

/** The stats that tell an item from another, as "ATK 9, STR 7": a weapon's damage and delay first, then the three largest stats. */
function keyStats(record) {
  const parts = [];
  const weapon = record.weapon;
  if (weapon && typeof weapon.dmg === "number" && typeof weapon.delay === "number") parts.push(`Dmg ${weapon.dmg} / Delay ${weapon.delay}`);
  const stats = record.stats ?? {};
  const present = [];
  for (const name of STAT_ORDER) {
    const value = stats[name];
    if (typeof value === "number" && value > 0) present.push([name, value]);
  }
  present.sort((a, b) => b[1] - a[1]);
  for (const [name, value] of present.slice(0, 3)) parts.push(`${name} ${value}`);
  return parts.length > 0 ? parts.join(", ") : "no stats";
}

/** The records of an item table: readItemTable's result, a Map of its records or a list of them. */
function recordsOf(items) {
  if (Array.isArray(items)) return items;
  if (items instanceof Map) return [...items.values()];
  if (items && items.records instanceof Map) return [...items.records.values()];
  return [];
}

const keyOf = (record) => (typeof record.key === "string" ? record.key : `w${record.id}`);

/** Say something through the page's live region: `announce(text)`, or the element #announce itself. */
function speak(doc, announce, text) {
  if (typeof announce === "function") {
    announce(text);
    return;
  }
  const live = doc.getElementById("announce");
  if (live) live.textContent = text;
}

function usableBy(record, trio) {
  const classes = Array.isArray(record.classes) ? record.classes : ["ALL"];
  return classes.includes("ALL") || classes.some((code) => trio.includes(code));
}

function splitIdent(ident) {
  const at = ident.lastIndexOf("@");
  return { key: ident.slice(0, at), tier: Number(ident.slice(at + 1)) };
}

export function createGearInput(root, { items, trio = [], doc = root.ownerDocument, win = doc.defaultView, announce } = {}) {
  const classes = (Array.isArray(trio) ? trio : []).filter((code) => typeof code === "string");

  // ---- the item table: what each key is, what the matcher is told, and what the picker offers ----------------------------------------------------------
  const info = new Map(); // key -> {key, name, slot, usable, record}
  const matchTable = [];
  const pickerEntries = [];
  for (const record of recordsOf(items)) {
    if (record === null || typeof record !== "object" || typeof record.name !== "string") continue;
    const key = keyOf(record);
    const usable = usableBy(record, classes);
    const slot = slotWords(record.slots);
    info.set(key, { key, name: record.name, slot, usable, record });
    matchTable.push({ key, match_name: record.match_name || record.name, aliases: Array.isArray(record.aliases) ? record.aliases : [], owned_only: record.owned_only === true, name: record.name });
    if (usable) pickerEntries.push({ key, name: record.name, slot });
  }

  // ---- the elements -----------------------------------------------------------------------------------------------------------------------------------
  const $ = (id) => root.querySelector(`#${id}`);
  const fileInput = $("upgrade-file");
  const zone = $("upgrade-drop");
  const ownedList = $("upgrade-owned");
  const heading = $("upgrade-owned-h");
  const countNode = $("upgrade-count");
  const emptyNode = $("upgrade-empty");
  const clearButton = $("upgrade-clear");
  const feedback = $("upgrade-feedback");
  const addButton = $("upgrade-add");

  const make = (tag, className, text) => {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  // the parts of the feedback, made once and shown when there is something in them: the last problem, the banner (with its choices and the names that are not in the catalog),
  // what the limits did, and the notes of the parser
  const noteNode = make("p", "note");
  noteNode.id = "upgrade-note";
  noteNode.hidden = true;
  const bannerNode = make("div", "banner");
  bannerNode.id = "upgrade-banner";
  bannerNode.hidden = true; // (a plain element: what it says is said through the page's #announce, once)
  const bannerText = make("p");
  bannerText.id = "upgrade-banner-text";
  const choicesList = make("ul", "choices");
  choicesList.setAttribute("aria-label", "Items that need a choice");
  const unknownNode = make("details", "expander");
  unknownNode.id = "upgrade-unknown";
  unknownNode.hidden = true;
  const unknownSummary = make("summary");
  const unknownList = make("ul", "plain");
  unknownNode.append(unknownSummary, unknownList);
  bannerNode.append(bannerText, choicesList, unknownNode);
  const limitsNode = make("p", "note");
  limitsNode.id = "upgrade-limits";
  limitsNode.hidden = true;
  const warningsNode = make("details", "expander");
  warningsNode.id = "upgrade-warnings";
  warningsNode.hidden = true;
  const warningsSummary = make("summary");
  const warningsList = make("ul", "plain");
  warningsNode.append(warningsSummary, warningsList);
  feedback.replaceChildren(noteNode, bannerNode, limitsNode, warningsNode);

  // ---- what is said -----------------------------------------------------------------------------------------------------------------------------------
  const say = (text) => speak(doc, announce, text);

  function setNote(text) {
    noteNode.textContent = text;
    noteNode.hidden = text === "";
  }

  // ---- the state --------------------------------------------------------------------------------------------------------------------------------------
  const picked = new Map(); // ident -> how many were added by name
  const restored = new Map(); // ident -> how many were put back from the device: the list of an earlier visit, which the next file that is read replaces
  let dump = null; // the last file that was read: {matched: [{key, row}], groups: [...], unknown: [...], warnings: [...]}
  let choices = new Map(); // group key (the ID in the file and the name) -> the item chosen for it; kept when a file is read again, dropped by Clear
  let removed = new Set(); // idents of the list that the visitor took out: the file's rows for them are left out
  let readToken = 0;
  let shown = { list: [], idents: new Map(), pending: [], fileCount: 0, clamped: 0, leftOut: 0 };
  const listeners = new Set();

  /** The list from the state: what was added by name first (the visitor typed it), then what was restored, then the file's rows in the order of the file, each item once for each tier. */
  function derive() {
    const entries = new Map(); // ident -> {ident, key, tier, raw, places: Map, fromFile, byHand, remembered}
    const leftOut = new Set();
    const put = (key, tier, count, place, origin) => {
      const ident = `${key}@${tier}`;
      let entry = entries.get(ident);
      if (entry === undefined) {
        if (entries.size >= LIMITS.maxOwnedEntries) {
          leftOut.add(ident);
          return;
        }
        entry = { ident, key, tier, raw: 0, places: new Map(), fromFile: false, byHand: false, remembered: false };
        entries.set(ident, entry);
      }
      entry.raw += count;
      if (place !== null) {
        entry.places.set(place, (entry.places.get(place) ?? 0) + count);
        entry.fromFile = true;
      } else if (origin === REMEMBERED) entry.remembered = true;
      else entry.byHand = true;
    };
    for (const [ident, count] of picked) {
      const { key, tier } = splitIdent(ident);
      put(key, tier, count, null, BY_HAND);
    }
    for (const [ident, count] of restored) {
      const { key, tier } = splitIdent(ident);
      put(key, tier, count, null, REMEMBERED);
    }
    const pending = [];
    if (dump !== null) {
      const fromFile = dump.matched.map(({ key, row }) => ({ key, row }));
      for (const group of dump.groups) {
        const chosen = choices.get(group.key);
        if (chosen === undefined) pending.push(group);
        else for (const row of group.rows) fromFile.push({ key: chosen, row });
      }
      fromFile.sort((a, b) => a.row.line - b.row.line);
      for (const { key, row } of fromFile) {
        if (removed.has(`${key}@${row.tier}`)) continue;
        put(key, row.tier, row.count, row.place, null);
      }
    }
    let clamped = 0;
    const list = [];
    for (const entry of entries.values()) {
      if (entry.raw > LIMITS.maxOwnedCount) clamped += 1;
      const locations = [];
      for (const place of PLACE_ORDER) {
        const here = entry.places.get(place);
        if (here !== undefined) locations.push({ location: place, count: Math.min(here, LIMITS.maxOwnedCount) });
      }
      list.push({ ident: entry.ident, key: entry.key, tier: entry.tier, count: Math.min(entry.raw, LIMITS.maxOwnedCount), locations, fromFile: entry.fromFile, byHand: entry.byHand, remembered: entry.remembered });
    }
    const lower = (entry) => info.get(entry.key).name.toLowerCase();
    list.sort((a, b) => {
      const x = lower(a);
      const y = lower(b);
      return x < y ? -1 : x > y ? 1 : a.tier - b.tier || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0);
    });
    return {
      list,
      idents: new Map(list.map((entry) => [entry.ident, entry])),
      pending,
      fileCount: list.filter((entry) => entry.fromFile).length,
      clamped,
      leftOut: leftOut.size,
    };
  }

  const copyOf = (entry) => ({ key: entry.key, tier: entry.tier, count: entry.count, locations: entry.locations.map((place) => ({ ...place })) });
  const signature = () => JSON.stringify(shown.list.map(copyOf));

  // ---- drawing ----------------------------------------------------------------------------------------------------------------------------------------
  function rowNode(entry) {
    const item = info.get(entry.key);
    const li = make("li", "owned-row");
    li.dataset.ident = entry.ident;
    // the words of the row (the name, and under it the tier, how many and where) and, beside them, its button
    const words = make("div", "owned-text");
    words.append(make("span", "owned-name", item.name), doc.createTextNode(" "), make("span", "owned-meta owned-tier", `+${entry.tier}`));
    if (entry.count > 1) words.append(doc.createTextNode(" "), make("span", "owned-meta owned-count", `${entry.count} copies`));
    const where =
      entry.locations.length === 0
        ? [entry.remembered ? "remembered" : "", entry.byHand || !entry.remembered ? "added by hand" : ""].filter(Boolean).join(", ")
        : entry.locations.map((place) => PLACE_WORDS.get(place.location) + (place.count > 1 ? ` ×${place.count}` : "")).join(", ");
    words.append(doc.createTextNode(" "), make("span", "owned-meta owned-where", where));
    if (!item.usable) words.append(doc.createTextNode(" "), make("span", "owned-meta owned-note", "not for this trio's classes"));
    const remove = make("button", "btn-quiet", "Remove");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${item.name} +${entry.tier}`);
    li.append(words, doc.createTextNode(" "), remove);
    return li;
  }

  function candidateNode(group, key, index) {
    const item = info.get(key);
    const li = make("li");
    const description = make("span", "choice-desc", `${item.name} · ${item.slot} · ${keyStats(item.record)} · ${key}`);
    description.id = `upgrade-choice-${group.id}-${index}`;
    const button = make("button", "btn-quiet", "Choose");
    button.type = "button";
    button.id = `${description.id}-go`;
    button.setAttribute("aria-labelledby", `${button.id} ${description.id}`);
    button.addEventListener("click", () => choose(group, key));
    li.append(description, doc.createTextNode(" "), button);
    return li;
  }

  function groupNode(group) {
    const li = make("li", "choice");
    li.dataset.group = String(group.id);
    const intro = group.offered
      ? `"${group.name}" is close to ${group.keys.length === 1 ? "this item" : `one of ${group.keys.length} items`}:`
      : `"${group.name}" could be one of ${group.keys.length} items:`;
    const name = make("p", "choice-name", intro);
    name.id = `upgrade-choice-${group.id}`;
    const options = make("ul", "choice-options");
    options.setAttribute("aria-labelledby", name.id);
    group.keys.slice(0, MAX_SHOWN).forEach((key, index) => options.append(candidateNode(group, key, index)));
    if (group.keys.length > MAX_SHOWN) {
      const rest = group.keys.length - MAX_SHOWN;
      options.append(make("li", "choice-more", `${fmt(rest)} more ${plural(rest, "is", "are")} not shown.`));
    }
    li.append(name, options);
    return li;
  }

  function renderBanner() {
    const pending = shown.pending;
    const unknown = dump === null ? [] : dump.unknown;
    const parts = [];
    if (pending.length > 0) parts.push(`${fmt(pending.length)} ${plural(pending.length, "item needs", "items need")} a choice.`);
    if (unknown.length > 0) parts.push(`${fmt(unknown.length)} ${plural(unknown.length, "item is", "items are")} not in the catalog.`);
    bannerNode.hidden = parts.length === 0;
    bannerText.textContent = parts.join(" ");
    const groups = pending.slice(0, MAX_SHOWN).map(groupNode);
    if (pending.length > MAX_SHOWN) {
      const rest = pending.length - MAX_SHOWN;
      groups.push(make("li", "choice-more", `${fmt(rest)} more ${plural(rest, "is", "are")} not shown.`));
    }
    choicesList.replaceChildren(...groups);
    choicesList.hidden = groups.length === 0;
    unknownNode.hidden = unknown.length === 0;
    unknownSummary.textContent = `Not in the catalog (${fmt(unknown.length)})`;
    const names = unknown.slice(0, MAX_SHOWN).map((entry) => make("li", "", entry.name + (entry.count > 1 ? ` ×${fmt(entry.count)}` : "")));
    if (unknown.length > MAX_SHOWN) names.push(make("li", "", `and ${fmt(unknown.length - MAX_SHOWN)} more.`));
    unknownList.replaceChildren(...names);
  }

  function limitsText() {
    const parts = [];
    if (shown.clamped > 0) parts.push(COUNT_LIMIT_NOTE(shown.clamped));
    if (shown.leftOut > 0) parts.push(ENTRY_LIMIT_NOTE(shown.leftOut));
    return parts.join(" ");
  }

  function render() {
    shown = derive();
    ownedList.replaceChildren(...shown.list.map(rowNode));
    countNode.textContent = shown.list.length > 0 ? `(${fmt(shown.list.length)})` : "";
    emptyNode.hidden = shown.list.length > 0;
    renderBanner();
    const text = limitsText();
    limitsNode.textContent = text;
    limitsNode.hidden = text === "";
    const warnings = dump === null ? [] : dump.warnings;
    warningsNode.hidden = warnings.length === 0;
    warningsSummary.textContent = `Notes about the file (${fmt(warnings.length)})`;
    warningsList.replaceChildren(...warnings.map((warning) => make("li", "", warning)));
    clearButton.hidden = shown.list.length === 0 && dump === null; // (a file that was read leaves its notes, its choices and its names that are not in the catalog, whatever rows it gave)
  }

  /** Draw again after a change, and tell the listeners if the list is not the one it was. */
  function update(before) {
    render();
    if (signature() !== before) {
      for (const listener of [...listeners]) {
        try {
          listener();
        } catch {
          // a bug in a listener is the listener's
        }
      }
    }
  }

  const focusRemove = (ident) => {
    const li = [...ownedList.children].find((child) => child.dataset.ident === ident);
    const button = li ? li.querySelector("button") : null;
    if (button) button.focus();
    else heading.focus();
  };

  // ---- the actions --------------------------------------------------------------------------------------------------------------------------------------
  function remove(ident) {
    const entry = shown.idents.get(ident);
    if (entry === undefined) return;
    const children = [...ownedList.children];
    const at = children.findIndex((child) => child.dataset.ident === ident);
    const next = (children[at + 1] ?? children[at - 1] ?? null)?.dataset.ident ?? null;
    const before = signature();
    const needsBefore = shown.pending.length;
    setNote("");
    picked.delete(ident);
    restored.delete(ident);
    removed.add(ident);
    if (dump !== null) {
      for (const group of dump.groups) {
        const chosen = choices.get(group.key);
        if (chosen === undefined || !group.rows.some((row) => `${chosen}@${row.tier}` === ident)) continue;
        // while another row of the item is left the item stays and the choice with it; with the last row gone it needs a choice again
        if (group.rows.every((row) => removed.has(`${chosen}@${row.tier}`))) choices.delete(group.key);
      }
    }
    update(before);
    const needs = shown.pending.length;
    // (the banner is not a live region: a choice that is asked for again with the last row of an item is said here)
    say(`Removed ${info.get(entry.key).name} +${entry.tier}.${needs > needsBefore ? ` ${fmt(needs)} ${plural(needs, "item needs", "items need")} a choice.` : ""}`);
    if (next === null) heading.focus();
    else focusRemove(next);
  }

  function choose(group, key) {
    const before = signature();
    const pendingBefore = shown.pending.map((entry) => entry.id);
    const at = pendingBefore.indexOf(group.id);
    const nextGroup = pendingBefore[at + 1] ?? pendingBefore[at - 1] ?? null;
    setNote("");
    choices.set(group.key, key);
    for (const row of group.rows) removed.delete(`${key}@${row.tier}`); // a choice made again after a Remove puts the row back
    update(before);
    const left = shown.pending.length;
    say(`Chose ${info.get(key).name}.${left > 0 ? ` ${fmt(left)} ${plural(left, "item needs", "items need")} a choice.` : ""}`);
    const target = nextGroup === null ? null : choicesList.querySelector(`li[data-group="${nextGroup}"] button`);
    if (target) target.focus();
    else heading.focus();
  }

  function addByName(entry, tier) {
    const ident = `${entry.key}@${tier}`;
    setNote("");
    const have = shown.idents.get(ident);
    if (have === undefined && shown.list.length >= LIMITS.maxOwnedEntries) return refuse(FULL_NOTE);
    if (have !== undefined && have.count >= LIMITS.maxOwnedCount) return refuse(COPIES_NOTE);
    const before = signature();
    picked.set(ident, (picked.get(ident) ?? 0) + 1);
    update(before);
    const count = shown.idents.get(ident).count;
    say(`Added ${entry.name} +${tier}${count > 1 ? `, now ${count} copies` : ""}.`);
    return true;
  }

  function refuse(text) {
    setNote(text);
    say(text);
    return false;
  }

  function restore(entries) {
    const before = signature();
    for (const [key, tier, count] of entries) {
      if (!info.has(key)) continue;
      const ident = `${key}@${tier}`;
      restored.set(ident, (restored.get(ident) ?? 0) + count);
    }
    update(before);
    return shown.list.length;
  }

  function clear(focusHeading = false) {
    const before = signature();
    picked.clear();
    restored.clear();
    dump = null;
    choices = new Map();
    removed = new Set();
    readToken += 1; // a file that is still being read is not wanted any more
    setNote("");
    picker.reset();
    update(before);
    say("Cleared your gear.");
    if (focusHeading) heading.focus();
  }

  /** Group the rows of a file for the banner: the rows that fit more than one item by the ID they have (the same name and the same ID is the same item), and the names that fit none. */
  function groupsOf(matched) {
    const byId = new Map();
    const groups = [];
    for (const { row, keys, stage } of matched.ambiguous) {
      const id = `${row.id}\u0000${row.name}`;
      let group = byId.get(id);
      if (group === undefined) {
        group = { id: groups.length, key: id, name: row.name, keys: keys.filter((key) => info.has(key)), offered: stage === 4, rows: [] };
        byId.set(id, group);
        groups.push(group);
      }
      group.rows.push(row);
    }
    const byName = new Map();
    const unknown = [];
    for (const { row } of matched.unknown) {
      let entry = byName.get(row.name);
      if (entry === undefined) {
        entry = { name: row.name, count: 0 };
        byName.set(row.name, entry);
        unknown.push(entry);
      }
      entry.count += row.count;
    }
    return { groups: groups.filter((group) => group.keys.length > 0), unknown };
  }

  async function readFile(file) {
    const token = ++readToken;
    let parsed;
    try {
      parsed = await parseDump(file);
    } catch (error) {
      if (token !== readToken) return { ok: false, stale: true }; // a read that fails after the visitor cleared the list or gave another file is nobody's business
      throw error;
    }
    if (token !== readToken) return { ok: false, stale: true };
    setNote("");
    if (parsed.errors.length > 0) {
      const message = parsed.errors[0];
      refuse(message);
      return { ok: false, error: message };
    }
    const found = matchItems(parsed.rows.filter((row) => row.container !== true), matchTable);
    const { groups, unknown } = groupsOf(found);
    const before = signature();
    dump = { matched: found.matched.map(({ row, key }) => ({ key, row })), groups, unknown, warnings: parsed.warnings };
    restored.clear(); // the list of an earlier visit was a file's, and this file replaces it as it would replace the file read before: it is not added to it
    for (const group of groups) {
      const chosen = choices.get(group.key);
      if (chosen !== undefined && !group.keys.includes(chosen)) choices.delete(group.key); // (the same name gives the same items, so this is for an item that is not there any more)
    }
    removed = new Set(); // what was taken out of the list is the list of the file before: a new file is a new list, and the choices stay
    update(before);
    const needs = shown.pending.length;
    let text = `${fmt(shown.fileCount)} ${plural(shown.fileCount, "item", "items")} read`;
    if (needs > 0) text += `, ${fmt(needs)} ${plural(needs, "needs", "need")} a choice`;
    if (unknown.length > 0) text += `, ${fmt(unknown.length)} not in the catalog`;
    text += ".";
    const limits = limitsText();
    say(limits === "" ? text : `${text} ${limits}`);
    return { ok: true, read: shown.fileCount, needChoice: needs, unknown: unknown.length };
  }

  /** The files that came from the file input or a drop: one is read, more than one are not. */
  function take(files) {
    if (files.length === 0) return;
    if (files.length > 1) {
      refuse(ONE_FILE_NOTE);
      return;
    }
    readFile(files[0]).catch(() => {
      refuse(ERRORS.internal);
    });
  }

  // ---- the controls -------------------------------------------------------------------------------------------------------------------------------------
  const picker = createGearPicker({
    input: $("upgrade-pick"),
    list: $("upgrade-list"),
    tier: $("upgrade-tier"),
    add: addButton,
    doc,
    entries: pickerEntries,
    onAdd: addByName,
    onNote: (text) => {
      setNote(text);
      say(text);
    },
    onMatches: say,
  });
  addButton.disabled = false;

  fileInput.addEventListener("change", () => {
    const files = Array.from(fileInput.files ?? []);
    fileInput.value = ""; // so that the same file can be chosen again
    take(files);
  });
  const hasFiles = (event) => {
    const types = event.dataTransfer && event.dataTransfer.types;
    return Boolean(types) && Array.from(types).includes("Files");
  };
  let over = 0;
  root.addEventListener("dragenter", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    over += 1;
    zone.classList.add("is-over");
  });
  root.addEventListener("dragover", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault(); // without this the browser does not allow a drop here
    try {
      event.dataTransfer.dropEffect = "copy";
    } catch {
      // a transfer that cannot say what it will do is still a drop
    }
  });
  root.addEventListener("dragleave", (event) => {
    if (!hasFiles(event)) return;
    over = Math.max(0, over - 1);
    if (over === 0) zone.classList.remove("is-over");
  });
  root.addEventListener("drop", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault(); // the browser would open the file in place of the page
    over = 0;
    zone.classList.remove("is-over");
    take(Array.from(event.dataTransfer.files ?? []));
  });
  ownedList.addEventListener("click", (event) => {
    const button = event.target && typeof event.target.closest === "function" ? event.target.closest("button") : null;
    const li = button === null ? null : button.closest("li");
    if (li !== null && li.dataset.ident) remove(li.dataset.ident);
  });
  clearButton.addEventListener("click", () => clear(true));

  render();

  return {
    owned: () => shown.list.map(copyOf),
    toOwnedPairs: () => shown.list.slice(0, LIMITS.maxOwnedEntries).map((entry) => [entry.ident, Math.min(entry.count, LIMITS.maxOwnedCount)]),
    onChange(callback) {
      listeners.add(callback);
      return () => listeners.delete(callback);
    },
    clear: () => clear(false),
    readFile,
    restore,
    /** Files that were dropped or chosen: one is read, more than one are refused. */
    takeFiles: take,
  };
}

// ---- loading the section ---------------------------------------------------------------------------------------------------------------------------------

const LOADING = "Loading the item list…";
const KIT_UPDATED = "Data updated, reload the page to see this kit.";
/** The code of the panel of a shared kit (a chunk of its own) could not be had: only a reload can try again, since a browser keeps a failed module fetch until the page is reloaded. */
const KIT_CODE_FAILED = "Couldn't load the shared kit. Reload the page to try again.";

/** Something went wrong with the item list: the message is for the visitor, and says nothing of the server's answer. */
class Failure extends Error {}
/** The site was released again since the page was made. */
class Updated extends Error {}

/**
 * Start the section on the page. `env`: `doc`, `win`, `fetch` (the page's), `release` (the data release the page was built for, or null), `files` (what was dropped or
 * chosen before this code was there), `onUpdated()` (what the page does to say that its data was updated), `reload()` (what the Reload button of the section does, and that of the panel of a shared kit), `announce(text)`
 * (the page's live region), `track(promise)` (the page's list of what it is waiting for). For a kit that came in a link (shared-kit.js) the page gives `kit` (what first.js took out of the address, `{payload, source, cleared}`, or null) and
 * `valueView()` (the role, buffs and evidence level of the view it shows); the kit is shown at the top of the page once the item list is in, and the section is started at once for it, not at a first use.
 * The panel is code of a chunk of its own, which this code loads by a dynamic import (`loadShared()`, for tests) at that start, in step with the manifest and the item list, and for no page that
 * has no kit link; when it cannot be had, or has no panel to make (no `createSharedKit`, or one that throws or gives back nothing), the section's line says so, with a Reload, and `onKitFailed()` lets
 * the page say so at the top, where the kit would have been. For the gear a visitor asked the device to remember (remember.js) it gives `remember` (`{key, storage, stored}`: the
 * name the gear is kept under, the storage, or null, and what was stored, or null). For the answer (upgrade-answer.js) the page gives `view()` and `onView(callback)` (the view
 * it shows, and a way to be told when that changes), `words` (its own words for a tier, a cost and a place of the kit) and, for tests, `loadEngine(url)`. Returns
 * `{gear, answer, ready(), retry(), readFile(file)}`: `gear` is the gear input once the item list is in (null before, and when it cannot be had), `answer` what draws the answer under it
 * (null when the page gives no view), `ready()` a promise of it that settles when the load that is going on has ended, with the gear input or with null.
 */
export function initUpgrade(
  root,
  { doc = root.ownerDocument, win = doc.defaultView, fetch: fetchImpl = (...args) => win.fetch(...args), release = null, files = [], onUpdated, reload, announce, track, view, onView, words, loadEngine, kit = null, remember = null, valueView, loadShared, onKitFailed, stallMs = STARTUP_STALL_MS, bodyMs = STARTUP_COMPILE_MS } = {},
) {
  const trio = String(root.dataset.trio ?? "").split("-").map((part) => part.toUpperCase());
  const loadNode = root.querySelector("#upgrade-load");
  const heading = root.querySelector("#upgrade-h");
  const fileInput = root.querySelector("#upgrade-file");
  for (const control of root.querySelectorAll("[data-wake]")) control.disabled = false;

  // a kit that came in a link has its panel from the start (it says that it is loading); the rest of it is drawn when the item list is in. The code of the panel is a chunk of its
  // own: it is loaded now, by a dynamic import, while the manifest and the item list are fetched, and by no page that has no kit link. The import has the time that the body of a
  // download has, as the import of the evaluator has in the panel: one that hangs would leave the section waiting for the panel for good, and the code is then given up as if it could not be had
  const reloadPage = () => (typeof reload === "function" ? reload() : win.location.reload());
  let shared = null; // the panel, once its code is in
  let sharedCode = null; // a promise of it (never rejected: null when the code could not be had or the panel could not be made)
  let codeFailed = false; // the code of the panel could not be had, or it could not make the panel
  let toldKit = false; // the page was told so
  if (kit !== null && typeof kit === "object" && typeof kit.payload === "string" && words) {
    const importPanel = typeof loadShared === "function" ? loadShared : () => import("./shared-kit.js");
    sharedCode = importWithin(Promise.resolve().then(() => importPanel()), bodyMs, "The code of the shared kit")
      .then(
        (module) => {
          try {
            const made = module.createSharedKit({ doc, win, announce, words, trio: String(root.dataset.trio ?? ""), level: Number(root.dataset.level), payload: kit.payload, valueView, onView, loadEngine, track, reload: reloadPage });
            if (made === null || typeof made !== "object") throw new TypeError("no panel");
            shared = made;
          } catch {
            // (the section works without it.) A panel that cannot be made is said as code that could not be had is: the section's line with a Reload, and the page's status at the top
            shared = null;
            codeFailed = true;
          }
          return shared;
        },
        () => {
          codeFailed = true;
          return null;
        },
      );
    if (typeof track === "function") track(sharedCode);
  }

  let held = Array.isArray(files) ? files.slice() : []; // what came before the item list: the last file or files
  let gear = null;
  let answer = null;
  let updated = false;
  let loading = null;
  const say = (text) => speak(doc, announce, text);

  // Until the item list is in there is no list to put a file in, but a file dropped meanwhile must not be opened by the browser in place of the page, nor lost.
  const carries = (event) => {
    const types = event.dataTransfer && event.dataTransfer.types;
    return Boolean(types) && Array.from(types).includes("Files");
  };
  const keep = (list) => {
    if (list.length > 0) held = list;
  };
  const onChange = () => {
    const chosen = Array.from(fileInput.files ?? []);
    fileInput.value = "";
    if (updated) {
      if (chosen.length > 0) say(SECTION_UPDATED); // the data is newer than the page: there is nothing to read the file with
      return;
    }
    keep(chosen);
  };
  const onOver = (event) => {
    if (carries(event)) event.preventDefault();
  };
  const onDrop = (event) => {
    if (!carries(event)) return;
    event.preventDefault();
    const dropped = Array.from(event.dataTransfer.files ?? []);
    if (updated) {
      if (dropped.length > 0) say(SECTION_UPDATED);
      return;
    }
    keep(dropped);
  };
  fileInput.addEventListener("change", onChange);
  root.addEventListener("dragenter", onOver);
  root.addEventListener("dragover", onOver);
  root.addEventListener("drop", onDrop);
  const letGo = () => {
    fileInput.removeEventListener("change", onChange);
    root.removeEventListener("dragenter", onOver);
    root.removeEventListener("dragover", onOver);
    root.removeEventListener("drop", onDrop);
  };

  // The line under the heading says what is going on, and has a button when there is something to do about it (Try again, Reload). It is a plain element: what it says is said
  // through the page's #announce, and the page's own status says the notice of a newer release. Empty, it is out of sight.
  const tidy = () => loadNode.classList.toggle("quiet", loadNode.querySelector(".status-text") === null && loadNode.querySelector("button") === null);

  function setLine(text) {
    let words = loadNode.querySelector(".status-text");
    if (text) {
      if (!words) {
        words = doc.createElement("span");
        words.className = "status-text";
        loadNode.prepend(words);
      }
      words.textContent = text;
    } else if (words) {
      words.remove();
    }
    tidy();
  }

  let button = null; // the button that this code made, and what it does now
  let action = null;

  /**
   * A button in the line with this label and this action. The one that is there stays, with the focus on it if it has it, through the retries; a button that the page made
   * when this code could not be had is taken over.
   */
  function offer(label, what) {
    action = what;
    const old = loadNode.querySelector("button");
    if (old !== null && old === button) {
      old.textContent = label;
    } else {
      const focused = old !== null && doc.activeElement === old;
      button = doc.createElement("button");
      button.type = "button";
      button.className = "btn";
      button.textContent = label;
      button.addEventListener("click", () => {
        if (typeof action === "function") action();
      });
      if (old !== null) old.replaceWith(button);
      else loadNode.append(button);
      if (focused) button.focus();
    }
    tidy();
  }

  /** The button goes, and the focus with it to the heading of the section if it was on the button: a visitor who has gone on elsewhere is not moved. */
  function withdraw() {
    const old = loadNode.querySelector("button");
    if (old === null) return;
    const focused = doc.activeElement === old;
    old.remove();
    button = null;
    action = null;
    if (focused) heading.focus();
    tidy();
  }

  async function readManifest() {
    const what = "The list of the site's files";
    const url = sameOriginUrl(MANIFEST_PATH, win.location.href);
    const answer = await fetchTextWithin(fetchImpl, url.href, { credentials: "same-origin", cache: "no-cache" }, stallMs, LIMITS.maxManifestBytes);
    if (answer.state === "timeout") throw new Failure(`${what} did not arrive in time.`);
    if (answer.state === "status") throw new Failure(`${what} could not be loaded (${answer.status}).`);
    if (answer.state === "toolarge") throw new Failure(`${what} is too large.`);
    if (answer.state !== "ok" || typeof answer.text !== "string") throw new Failure(`${what} could not be loaded.`);
    try {
      return parseManifest(JSON.parse(answer.text));
    } catch {
      throw new Failure(`${what} is not what was expected.`);
    }
  }

  /** The item table by the path, size and SHA-256 the manifest lists: the type and the size are checked as it is read, the SHA-256 before a byte of it is parsed. */
  async function readTable(listed) {
    const file = listed.items;
    let bytes;
    try {
      bytes = await fetchBytes(sameOriginUrl(file.path, win.location.href), file.bytes, fetchImpl, () => {}, stallMs, bodyMs, DATA_FILE);
    } catch (error) {
      throw new Failure(error instanceof EngineFault ? error.message : "The item list could not be loaded.");
    }
    let digest;
    try {
      digest = await sha256Hex(bytes);
    } catch (error) {
      throw new Failure(error instanceof EngineFault ? error.message : "This browser cannot check the item list, so it will not use it.");
    }
    if (digest !== file.sha256) throw new Failure("The item list is not the one the site lists (its checksum differs).");
    let table;
    try {
      table = readItemTable(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)));
    } catch {
      throw new Failure("The item list is not what the site writes.");
    }
    if (table.dataRelease !== listed.dataRelease) throw new Failure("The item list is not of the release the site lists.");
    return table;
  }

  function retry() {
    load();
  }

  /** One attempt; it never throws. */
  async function attempt() {
    setLine(LOADING);
    say(LOADING);
    shared?.loading();
    try {
      // the manifest is read at every attempt: after a failure the site may have been released again, and the item list it named is then gone
      const listed = await readManifest();
      if (release !== null && listed.dataRelease !== release) throw new Updated();
      const table = await readTable(listed);
      gear = createGearInput(root, { items: table, trio, doc, win, announce });
      letGo(); // handed over: the gear input has its own handlers now (if it could not be made, these stay, and a file given meanwhile is still kept for the next try)
      if (typeof view === "function" && typeof onView === "function" && words) {
        try {
          answer = createUpgradeAnswer(root, {
            gear,
            records: table.records,
            trio: String(root.dataset.trio ?? ""),
            level: Number(root.dataset.level),
            view,
            onView,
            words,
            clientPath: listed.client.path,
            loadEngine,
            announce,
            onUpdated,
            reload: () => (typeof reload === "function" ? reload() : win.location.reload()),
            doc,
            win,
          });
        } catch {
          answer = null; // (the gear is in and works, whatever the answer could not do: the list is not lost with it, and no half of an answer is left in its place)
          root.querySelector("#upgrade-results")?.replaceChildren();
        }
      }
      // the box that remembers the gear comes after the answer, so that the answer sees the list fill when gear is restored into it
      if (remember !== null && typeof remember === "object") {
        try {
          createRemember(root, { gear, records: table.records, storage: remember.storage ?? null, key: remember.key, stored: remember.stored ?? null, announce, doc });
        } catch {
          root.querySelector("#upgrade-remember")?.remove(); // (the gear is in and works without it)
        }
      }
      const panel = sharedCode === null ? null : await sharedCode;
      if (panel !== null) {
        try {
          panel.loaded({ records: table.records, kitvalue: listed.kitvalue, data: { manifest: listed, fetchImpl, base: win.location.href, stallMs, bodyMs } });
        } catch {
          panel.failed("The shared kit could not be shown.");
        }
      }
      if (codeFailed) {
        // the item list is in and the section works; what could not be had is the panel, which only a reload can bring (a browser keeps a failed module fetch until the page is reloaded).
        // The page's status says it at the top, where the kit would be (and a screen reader hears it there), and the section's line says it near the controls.
        setLine(KIT_CODE_FAILED);
        offer("Reload", reloadPage);
        if (!toldKit && typeof onKitFailed === "function") {
          toldKit = true;
          onKitFailed();
        }
      } else {
        setLine("");
        withdraw();
      }
      if (held.length > 0) {
        const given = held;
        held = [];
        gear.takeFiles(given);
      }
      return gear;
    } catch (error) {
      if (error instanceof Updated) {
        updated = true;
        held = [];
        sharedCode?.then((panel) => panel?.failed(KIT_UPDATED, { label: "Reload", action: reloadPage }));
        setLine(SECTION_UPDATED); // (not said again: the page's own status says it to a screen reader; this line is for the eye, near the section, with a Reload of its own)
        offer("Reload", () => (typeof reload === "function" ? reload() : win.location.reload()));
        // nothing is behind the controls of the section any more, and the Reload button is what is left; a visitor whose focus was on one of them has it there
        const controls = Array.from(root.querySelectorAll("[data-wake]"));
        const lost = controls.includes(doc.activeElement);
        for (const control of controls) control.disabled = true;
        if (lost) button.focus();
        if (typeof onUpdated === "function") onUpdated();
        return null;
      }
      const message = `Couldn't load the item list. ${error instanceof Failure ? error.message : "Something went wrong."}`;
      sharedCode?.then((panel) => panel?.failed(`Couldn't load the item list, so the shared kit cannot be shown. ${error instanceof Failure ? error.message : "Something went wrong."}`, { label: "Try again", action: retry }));
      setLine(message);
      offer("Try again", retry);
      say(message);
      return null;
    }
  }

  function load() {
    if (gear !== null || updated) return Promise.resolve(gear);
    if (loading === null) {
      const run = attempt();
      loading = run;
      run.then(() => {
        if (loading === run) loading = null;
      });
      if (typeof track === "function") track(run);
    }
    return loading;
  }

  load();
  return {
    get gear() {
      return gear;
    },
    get answer() {
      return answer;
    },
    ready: () => loading ?? Promise.resolve(gear),
    retry,
    async readFile(file) {
      const made = await this.ready();
      return made === null ? { ok: false } : made.readFile(file);
    },
  };
}
