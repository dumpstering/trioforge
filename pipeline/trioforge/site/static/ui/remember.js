// "Remember my gear on this device": a box in the Upgrade section that keeps the owned list on the device, for the next visit.
//
//   createRemember(root, {gear, records, storage, key, stored, announce, doc}) -> {box}
//
// `gear` is the gear input (createGearInput), `records` the item table's Map from a key to a record, `storage` the device's storage (the page script hands it over: it may be null, and
// every call to it is in a try, since it can be missing, full or blocked), `key` the name the gear is kept under, `stored` what the device held under it when the page was made (a text, or
// null), and `announce(text)` the page's live region. The box is unchecked until the visitor checks it, and nothing is written to the device before.
//
// Kept. Checked, the list is written as {v: 1, entries: [[page id, tier, count]]}, in the order of the list, at most 500 entries (past that, the visitor is told how many were left
// out) and only for an item whose key is "w" and a page number (the number a link holds too; another key cannot be kept, and is counted and said). Nothing else is kept: no place, no
// name, no file name. It is written again at every change of the list, and an empty list is not kept: there is nothing to remember. Unchecked, the copy is erased and the section says so.
// When the device refuses a write the section says so once ("Couldn't remember your gear ..."), works as before, and says when a write works again.
//
// Restored. A page that finds some (the page script reads the device once and hands over the text) puts it back on the list through the checks that any input goes through: the shape of
// each entry, the item list (an item the catalog no longer has is dropped and counted, "N remembered items are no longer in the catalog"), the protocol's limits (the list clamps a count
// to 99 and keeps at most 1,000 different items, with its own notes) and the keys. What is stored by another version of the site (or in a shape this one does not write) is ignored,
// erased from the device, and said once. The box shows checked, a line says how many were restored and that restored gear has no places (so Equip now gives no location notes for
// it), and it offers Forget: erase the copy, uncheck the box and clear the list. The copy on the device is written again as it is now, so that what the catalog dropped is gone from it.
//
// Another tab. The device is shared by every tab of the site, and a tab with the box checked writes the list at every change, so it would write the copy again after another tab erased
// it (Forget, the box unchecked, the storage cleared) and the erase would be undone. A tab hears the erase (the `storage` event of the key, or of the whole storage cleared), sets itself
// off, unchecks the box and says so; its list stays as it is. A write by another tab is not its business. The erase and the event that tells this tab of it are two things, and a change of
// the list that was queued here can run between them and write the copy again (the box is still checked): the key then holds the text this tab wrote last, and the erase would be undone
// by the very tab that the event sets off. So the tab that hears an erase takes the key out again when it holds exactly that text; a copy that another tab wrote stays.
//
// Everything is said through the page's #announce, once, and also in the line under the box (a plain element: the section has no live region of its own). The focus stays on the box
// when it is checked or unchecked, and goes to it when Forget, which goes with its line, was pressed.

import { MAX_PAGE_ID, MAX_TIER, keyFromPageId, pageIdFromKey } from "../input/kitcode.js";

export const GEAR_VERSION = 1;
/** The most entries that are kept. */
export const MAX_REMEMBERED = 500;

const plural = (n, one, many) => (n === 1 ? one : many);
const HELP = "Only the items, their tiers and how many are kept, in this browser. Nothing is sent.";
const REMEMBERED = "Your gear is remembered on this device.";
const NOTHING_YET = "Your gear will be remembered on this device as you add it.";
const ERASED = "Your remembered gear was erased from this device.";
const NOT_ERASED = "Couldn't erase your remembered gear: this browser would not let the page change its storage.";
const NOT_KEPT = "Couldn't remember your gear: this browser would not store it. The rest of the section works as before.";
const FORGOT = "Forgot your gear: the list is empty and nothing is remembered on this device.";
const NO_PLACES = "Restored gear has no places, so Equip now gives no location notes for it.";
const OTHER_VERSION = "Gear remembered by another version of this site was ignored and erased.";
const UNREADABLE = "The gear remembered on this device could not be read, so it was erased.";
const ERASED_ELSEWHERE = "Your remembered gear was erased from this device in another tab, so this page no longer remembers it.";

const isWhole = (value) => Number.isSafeInteger(value);

/** One stored entry as [page id, tier, count], or null when it is not one this site writes. */
function validEntry(entry) {
  if (!Array.isArray(entry) || entry.length !== 3 || !entry.every(isWhole)) return null;
  const [pageId, tier, count] = entry;
  if (pageId < 1 || pageId > MAX_PAGE_ID || tier < 0 || tier > MAX_TIER || count < 1) return null;
  return entry;
}

export function createRemember(root, { gear, records, storage, key, stored, announce, doc = root.ownerDocument }) {
  const make = (tag, attributes = {}, text) => {
    const node = doc.createElement(tag);
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    if (text !== undefined) node.textContent = text;
    return node;
  };

  // ---- the elements ----------------------------------------------------------------------------------------------------------------------------------
  const box = make("input", { type: "checkbox", id: "upgrade-remember-box", "aria-describedby": "upgrade-remember-help" });
  const row = make("div", { class: "remember-row" });
  row.append(box, make("label", { for: "upgrade-remember-box" }, "Remember my gear on this device"));
  const help = make("p", { id: "upgrade-remember-help", class: "note" }, HELP);
  const words = make("span", { class: "status-text" });
  const note = make("p", { id: "upgrade-remember-note", class: "note" }, undefined);
  note.append(words);
  note.hidden = true;
  const block = make("div", { id: "upgrade-remember", class: "remember" });
  block.append(row, help, note);
  const list = root.querySelector("#upgrade-owned");
  if (list && list.parentNode) list.after(block);
  else root.append(block);

  // ---- the device ------------------------------------------------------------------------------------------------------------------------------------
  let lastWrite = null; // the text this tab wrote to the device last, and has not erased since: what the key holds when the copy on the device is this tab's own
  function write(text) {
    try {
      storage.setItem(key, text);
      lastWrite = text;
      return true;
    } catch {
      return false;
    }
  }
  function erase() {
    try {
      storage.removeItem(key);
      lastWrite = null;
      return true;
    } catch {
      return false;
    }
  }
  /** What the device holds under the key, or null (nothing there, or it cannot be read). */
  function read() {
    try {
      return storage.getItem(key);
    } catch {
      return null;
    }
  }

  // ---- what is said ----------------------------------------------------------------------------------------------------------------------------------
  let forgetButton = null;
  /** The line under the box: the words, and Forget when `withForget`. */
  function setNote(text, withForget = false) {
    words.textContent = text;
    note.hidden = text === "";
    forgetButton?.remove();
    forgetButton = null;
    if (withForget && text !== "") {
      forgetButton = make("button", { type: "button", id: "upgrade-forget", class: "btn-quiet" }, "Forget");
      forgetButton.addEventListener("click", forget);
      note.append(" ", forgetButton);
    }
  }
  function say(text, withForget = false, loud = true) {
    setNote(text, withForget);
    if (loud && text !== "" && typeof announce === "function") announce(text);
  }

  // ---- keeping ---------------------------------------------------------------------------------------------------------------------------------------
  let on = false;
  let restoring = false;
  let failing = false; // the device refused the last write
  let lastLeft = ""; // the words about what was left out, as they were said last

  /** The list as it is kept: what can be kept (at most MAX_REMEMBERED), and how many were left out for being too many or for having a key that is not a page number. */
  function kept() {
    const entries = [];
    let unkeyed = 0;
    for (const entry of gear.owned()) {
      const pageId = pageIdFromKey(entry.key);
      if (pageId === null) unkeyed += 1;
      else entries.push([pageId, entry.tier, entry.count]);
    }
    return { entries: entries.slice(0, MAX_REMEMBERED), tooMany: Math.max(0, entries.length - MAX_REMEMBERED), unkeyed };
  }

  /** Write the list (or erase the copy of an empty one). Returns whether the device took it, and what was left out. */
  function persist() {
    const { entries, tooMany, unkeyed } = kept();
    const ok = entries.length === 0 ? erase() : write(JSON.stringify({ v: GEAR_VERSION, entries }));
    return { ok, entries, tooMany, unkeyed };
  }

  /** The words about what was left out of the copy, or nothing. */
  function leftWords(tooMany, unkeyed) {
    const parts = [];
    if (tooMany > 0) parts.push(`Only ${MAX_REMEMBERED} items can be remembered: ${tooMany} ${plural(tooMany, "was", "were")} left out.`);
    if (unkeyed > 0) parts.push(`${unkeyed} ${plural(unkeyed, "item", "items")} could not be remembered: ${plural(unkeyed, "its key is", "their keys are")} not a page number.`);
    return parts.join(" ");
  }

  /** Keep the list as it is now, if the box is checked. `loud`: the visitor just checked it, so what is kept is said; otherwise only a change in what is said (a failure, an amount left out) is. */
  function save(loud) {
    if (!on) return;
    const done = persist();
    if (!done.ok) {
      const first = !failing;
      failing = true;
      say(NOT_KEPT, forgetButton !== null, first);
      return;
    }
    const recovered = failing;
    failing = false;
    const left = leftWords(done.tooMany, done.unkeyed);
    const text = left !== "" ? left : done.entries.length > 0 ? REMEMBERED : NOTHING_YET;
    const changedLeft = left !== lastLeft;
    lastLeft = left;
    say(text, forgetButton !== null, loud || recovered || (left !== "" && changedLeft));
  }

  function forget() {
    on = false;
    box.checked = false;
    failing = false;
    lastLeft = "";
    const erased = erase();
    gear.clear();
    say(erased ? FORGOT : NOT_ERASED);
    box.focus();
  }

  box.addEventListener("change", () => {
    if (box.checked) {
      on = true;
      lastLeft = "";
      failing = false;
      save(true);
    } else {
      on = false;
      failing = false;
      lastLeft = "";
      const erased = erase();
      say(erased ? ERASED : NOT_ERASED);
    }
  });
  gear.onChange(() => {
    if (!restoring) save(false);
  });
  const view = doc.defaultView;
  if (view && typeof view.addEventListener === "function") {
    view.addEventListener("storage", (event) => {
      if (!on || (event.key !== null && event.key !== key) || event.newValue !== null) return; // (a write by another tab, or another key: not an erase of the copy)
      if (lastWrite !== null && read() === lastWrite) erase(); // (this tab's own late write: it would undo the erase. A copy that another tab wrote is left)
      lastWrite = null;
      on = false;
      box.checked = false;
      failing = false;
      lastLeft = "";
      say(ERASED_ELSEWHERE);
    });
  }

  // ---- restoring -------------------------------------------------------------------------------------------------------------------------------------
  function restore(text) {
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined;
    }
    const readable = parsed !== null && typeof parsed === "object" && !Array.isArray(parsed) && Object.prototype.hasOwnProperty.call(parsed, "v");
    if (!readable) {
      erase();
      say(UNREADABLE);
      return;
    }
    if (parsed.v !== GEAR_VERSION) {
      erase();
      say(OTHER_VERSION);
      return;
    }
    if (!Array.isArray(parsed.entries)) {
      erase();
      say(UNREADABLE);
      return;
    }
    const taken = [];
    let dropped = 0;
    let invalid = Math.max(0, parsed.entries.length - MAX_REMEMBERED); // (a copy this site wrote has no more; the rest is not read)
    for (const raw of parsed.entries.slice(0, MAX_REMEMBERED)) {
      const entry = validEntry(raw);
      if (entry === null) {
        invalid += 1;
        continue;
      }
      const itemKey = keyFromPageId(entry[0]);
      if (itemKey === null || !records.has(itemKey)) dropped += 1;
      else taken.push([itemKey, entry[1], entry[2]]);
    }
    restoring = true;
    try {
      gear.restore(taken);
    } finally {
      restoring = false;
    }
    const count = gear.owned().length;
    const parts = [];
    if (count > 0) parts.push(`Restored ${count} ${plural(count, "item", "items")} from this device.`);
    if (dropped > 0) parts.push(`${dropped} remembered ${plural(dropped, "item is", "items are")} no longer in the catalog.`);
    if (invalid > 0) parts.push(`${invalid} remembered ${plural(invalid, "entry was", "entries were")} not valid and ${plural(invalid, "was", "were")} dropped.`);
    if (count > 0) parts.push(NO_PLACES);
    if (count === 0) {
      erase(); // (nothing of it is left to remember)
      say(parts.join(" "), false);
      return;
    }
    on = true;
    box.checked = true;
    const done = persist(); // (written again as it is now, without what the catalog dropped)
    if (!done.ok) {
      failing = true;
      parts.push(NOT_KEPT);
    } else {
      lastLeft = leftWords(done.tooMany, done.unkeyed);
      if (lastLeft !== "") parts.push(lastLeft);
    }
    say(parts.join(" "), true);
  }

  if (typeof stored === "string") restore(stored);

  return { box };
}
