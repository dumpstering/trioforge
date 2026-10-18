// The gear picker of the Upgrade section: a text box that offers the items of a trio as the visitor types, a tier, and an Add button.
//
// The text box is the editable combobox with list autocomplete of the ARIA Authoring Practices
// (https://www.w3.org/WAI/ARIA/apg/patterns/combobox/, examples/combobox-autocomplete-list): role combobox with aria-autocomplete="list", aria-expanded and aria-controls
// on the text box, a listbox of options, and aria-activedescendant for the option that has the visual focus while the focus of the page stays in the text box.
//   Down Arrow    opens the list (all the items for an empty text box) and moves the visual focus to the first option, then to the next, and from the last to the first
//   Up Arrow      the same the other way, from the text box to the last option
//   Alt+Down      opens the list and leaves the visual focus in the text box
//   Enter         with an option in focus: its name goes into the text box and the list closes. With the list closed and an item chosen: Add
//   Escape        closes the list and keeps the text; with the list closed it clears the text box
//   Home, End, Left, Right   move the caret as in any text box, and the visual focus returns to the text box
//   Tab           takes the option in focus, if there is one, and the focus goes on to the tier
// While an input method editor composes (isComposing, or the key code 229) none of these keys is acted on: they are the editor's.
// The options are matched on the name as the item table writes it, case ignored and every quotation mark counted as one (the game writes many names with a backtick, the wiki
// with an apostrophe, and a phone turns a typed apostrophe into a typographic one: the fold is the matcher's own, input/match.js foldQuotes): first the names that begin with
// what was typed, then those in which every part of what was typed begins a word ("pauld" finds "Larkspur Pauldrons"), each kind in alphabetical order, at most MAX_OPTIONS of
// them. What is typed is only ever compared with text: it is never made into a pattern, and a name is never looked up by a key of an object (Maps and lists only).
//
// A visitor who cannot see the list is told how many items match, once for each pause in the typing (COUNT_PAUSE_MS), never for each key: `onMatches(text)`.
//
// The picker knows nothing of the owned list: it calls `onAdd(entry, tier)` and, when that says yes (true), empties the text box. It tells the visitor what is wrong
// (nothing chosen) through `onNote(text)`. Text goes into the page with textContent only.

import { foldQuotes } from "../input/match.js";

export const MAX_OPTIONS = 20;
const MAX_TERMS = 8;
const MAX_QUERY = 100;
const MAX_TIER = 10;
/** How long the typing must pause before the visitor is told how many items match (ms). */
export const COUNT_PAUSE_MS = 500;

/** Whether a character belongs to a word: a digit, a lower-case ASCII letter (the text is lower-cased first) or anything past ASCII. */
const isWordCode = (code) => (code >= 48 && code <= 57) || (code >= 97 && code <= 122) || code > 127;
/** Whether a character is a space, a tab or a line end. */
const isSpace = (code) => code === 32 || code === 9 || code === 10 || code === 13;

/** The words of a lower-case text: its runs of word characters, in order. */
function wordsOf(lower) {
  const words = [];
  let start = -1;
  for (let i = 0; i <= lower.length; i += 1) {
    const inside = i < lower.length && isWordCode(lower.charCodeAt(i));
    if (inside && start < 0) start = i;
    else if (!inside && start >= 0) {
      words.push(lower.slice(start, i));
      start = -1;
    }
  }
  return words;
}

/** A text as the picker compares it: every quotation mark one apostrophe, lower case, each run of spaces one space. */
const fold = (text) => collapse(foldQuotes(text).toLowerCase());

/** A text with each run of spaces turned into one space, and none at either end. */
function collapse(text) {
  let out = "";
  let pending = false;
  for (let i = 0; i < text.length; i += 1) {
    if (isSpace(text.charCodeAt(i))) {
      pending = out.length > 0;
    } else {
      if (pending) out += " ";
      pending = false;
      out += text[i];
    }
  }
  return out;
}

/**
 * The index of a list of entries `{key, name, slot}`: `search(query, limit)` gives at most `limit` of the entries (the very objects), those whose name begins with the
 * query first and then those in which each word of the query begins a word, each kind in alphabetical order (equal names by key). An empty query gives the first
 * `limit` entries. What is not text matches nothing. `count(query)` is how many entries `search` would find without a limit. `exact(name)` gives the entries that have
 * exactly this name (case ignored, spaces collapsed, quotation marks counted as one).
 */
export function buildIndex(entries) {
  const prepared = [];
  for (const entry of entries) {
    if (entry === null || typeof entry !== "object" || typeof entry.name !== "string" || typeof entry.key !== "string") continue;
    const lower = fold(entry.name);
    prepared.push({ entry, lower, words: wordsOf(lower) });
  }
  prepared.sort((a, b) => (a.lower < b.lower ? -1 : a.lower > b.lower ? 1 : a.entry.key < b.entry.key ? -1 : a.entry.key > b.entry.key ? 1 : 0));
  const byName = new Map();
  for (const item of prepared) {
    const same = byName.get(item.lower);
    if (same === undefined) byName.set(item.lower, [item.entry]);
    else same.push(item.entry);
  }
  /** What a query asks for: the text folded, and the parts of it that must each begin a word. */
  const parse = (query) => {
    const folded = fold(query.slice(0, MAX_QUERY * 4)).slice(0, MAX_QUERY);
    return { folded, terms: wordsOf(folded).slice(0, MAX_TERMS) };
  };
  const begins = (item, asked) => item.lower.startsWith(asked.folded);
  const holds = (item, asked) => asked.terms.length > 0 && asked.terms.every((term) => item.words.some((word) => word.startsWith(term)));
  return {
    size: prepared.length,
    search(query, limit = MAX_OPTIONS) {
      if (typeof query !== "string") return [];
      const asked = parse(query);
      if (asked.folded === "") return prepared.slice(0, limit).map((item) => item.entry);
      const starts = [];
      const inside = [];
      for (const item of prepared) {
        if (begins(item, asked)) {
          starts.push(item.entry);
          if (starts.length >= limit) break;
        } else if (inside.length < limit && holds(item, asked)) {
          inside.push(item.entry);
        }
      }
      return starts.concat(inside).slice(0, limit);
    },
    /** How many entries `search` would find with no limit. */
    count(query) {
      if (typeof query !== "string") return 0;
      const asked = parse(query);
      if (asked.folded === "") return prepared.length;
      let found = 0;
      for (const item of prepared) if (begins(item, asked) || holds(item, asked)) found += 1;
      return found;
    },
    exact(name) {
      if (typeof name !== "string") return [];
      return (byName.get(fold(name.slice(0, MAX_QUERY * 4))) ?? []).slice();
    },
  };
}

/**
 * Wire the controls of the picker. `input` is the text box, `list` the (empty, hidden) listbox that follows it, `tier` the select of the tier and `add` the button;
 * `entries` are `{key, name, slot}` (the slot is the words that tell where the item is worn). `onMatches(text)` is told how many items match, after each pause in the typing.
 * Returns `{setEntries(entries), selected(), reset(), destroy()}`.
 */
export function createGearPicker({ input, list, tier, add, doc, entries = [], onAdd, onNote, onMatches }) {
  let index = buildIndex(entries);
  let found = []; // the entries the options show now
  let nodes = []; // the option elements, in the same order
  let at = -1; // the option with the visual focus, or -1
  let open = false;
  let chosen = null;
  let pause = null; // the timer of the count that is about to be said

  const note = (text) => {
    if (typeof onNote === "function") onNote(text);
  };

  const cancelCount = () => {
    if (pause !== null) {
      clearTimeout(pause);
      pause = null;
    }
  };

  /** "3 items match", "1 item matches", "No item matches"; when the list shows fewer than there are, how many it shows. */
  function matchWords(total, shown) {
    if (total === 0) return "No item matches";
    const words = `${total.toLocaleString("en-US")} ${total === 1 ? "item matches" : "items match"}`;
    return total > shown ? `${words}, showing the first ${shown.toLocaleString("en-US")}` : words;
  }

  /** Said when the typing has paused, from what is in the box then: an emptied box says nothing. */
  function sayCount() {
    pause = null;
    if (typeof onMatches !== "function" || collapse(input.value) === "") return;
    const total = index.count(input.value);
    onMatches(matchWords(total, Math.min(total, MAX_OPTIONS)));
  }

  function countSoon() {
    cancelCount();
    pause = setTimeout(sayCount, COUNT_PAUSE_MS);
  }

  function setActive(next) {
    at = next;
    nodes.forEach((node, i) => node.setAttribute("aria-selected", i === at ? "true" : "false"));
    if (at >= 0) {
      input.setAttribute("aria-activedescendant", nodes[at].id);
      if (typeof nodes[at].scrollIntoView === "function") nodes[at].scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function hide() {
    cancelCount(); // a choice, Escape, a Tab or a click elsewhere takes back the count that was about to be said: the list is closed
    open = false;
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    setActive(-1);
  }

  function show(entriesToShow) {
    found = entriesToShow;
    nodes = entriesToShow.map((entry, i) => {
      const option = doc.createElement("li");
      option.id = `${list.id}-${i}`;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", "false");
      const name = doc.createElement("span");
      name.className = "li-name";
      name.textContent = entry.name;
      const where = doc.createElement("span");
      where.className = "li-meta";
      where.textContent = entry.slot;
      option.append(name, doc.createTextNode(" "), where);
      return option;
    });
    list.replaceChildren(...nodes);
    at = -1;
    input.removeAttribute("aria-activedescendant");
    open = true;
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  /** The list for what is in the text box (all the items for an empty one when the visitor asked for the list). */
  function openList() {
    const entriesToShow = index.search(input.value);
    if (entriesToShow.length === 0) {
      found = [];
      nodes = [];
      list.replaceChildren(); // no option of an earlier text is left behind in the closed list
      hide();
      return false;
    }
    show(entriesToShow);
    return true;
  }

  function refresh() {
    chosen = null;
    if (collapse(input.value) === "") hide();
    else openList();
  }

  function choose(entry) {
    chosen = entry;
    input.value = entry.name;
    hide();
  }

  /** The item the visitor means: the one chosen from the list, else the one whose name is what was typed, if only one item has it. */
  function meant() {
    if (chosen !== null) return chosen;
    const same = index.exact(input.value);
    return same.length === 1 ? same[0] : null;
  }

  function tierValue() {
    const n = Number(tier.value);
    return Number.isInteger(n) && n >= 0 && n <= MAX_TIER ? n : 0;
  }

  function commit() {
    const entry = meant();
    if (entry === null) {
      note("Choose an item from the list first.");
      return;
    }
    const added = typeof onAdd === "function" ? onAdd(entry, tierValue()) : false;
    if (added === true) {
      reset();
      input.focus();
    }
  }

  function reset() {
    input.value = "";
    chosen = null;
    hide();
  }

  function step(direction) {
    if (nodes.length === 0) return;
    const last = nodes.length - 1;
    if (at < 0) setActive(direction > 0 ? 0 : last);
    else setActive(direction > 0 ? (at === last ? 0 : at + 1) : at === 0 ? last : at - 1);
  }

  function onKeydown(event) {
    if (event.isComposing || event.keyCode === 229) return; // an input method editor is composing: Enter, the arrows, Escape and Tab are its keys
    if (event.ctrlKey || event.metaKey || event.shiftKey) return;
    let taken = true;
    switch (event.key) {
      case "ArrowDown":
      case "ArrowUp":
        if (!open && !openList()) sayCount(); // nothing fits: the list stays closed, so that is said at once and not left to the pause (a closed list takes the pending count back)
        if (open && !event.altKey) step(event.key === "ArrowDown" ? 1 : -1);
        break;
      case "Enter":
        if (open && at >= 0) {
          choose(found[at]);
        } else if (open) {
          const only = index.exact(input.value);
          if (only.length === 1) choose(only[0]);
          else hide();
        } else if (meant() !== null) {
          commit();
        } else {
          taken = false;
        }
        break;
      case "Escape":
        if (open) {
          hide();
        } else if (input.value !== "") {
          reset();
        } else {
          taken = false;
        }
        break;
      case "Tab":
        if (open && at >= 0) choose(found[at]);
        else hide();
        taken = false;
        break;
      case "Home":
      case "End":
      case "ArrowLeft":
      case "ArrowRight":
        setActive(-1);
        taken = false;
        break;
      default:
        taken = false;
    }
    if (taken) {
      event.preventDefault();
      event.stopPropagation();
    }
  }

  const onInput = () => {
    refresh();
    countSoon();
  };
  const onBlur = () => hide();
  const onMouseDown = (event) => event.preventDefault(); // pressing the mouse button on the list must not take the focus from the text box
  const onClick = (event) => {
    const option = event.target && typeof event.target.closest === "function" ? event.target.closest('[role="option"]') : null;
    const position = option === null ? -1 : nodes.indexOf(option);
    if (position < 0) return;
    choose(found[position]);
    input.focus();
  };

  input.addEventListener("keydown", onKeydown);
  input.addEventListener("input", onInput);
  input.addEventListener("blur", onBlur);
  list.addEventListener("mousedown", onMouseDown);
  list.addEventListener("click", onClick);
  add.addEventListener("click", commit);
  // what was typed before the items were there (the box has the focus) is answered now
  if (doc.activeElement === input && collapse(input.value) !== "") {
    openList();
    countSoon();
  }

  return {
    /** The items to offer, replaced; a list in view is made again from what is typed. */
    setEntries(next) {
      index = buildIndex(next);
      if (chosen !== null && index.exact(chosen.name).every((entry) => entry.key !== chosen.key)) chosen = null;
      if (doc.activeElement === input && collapse(input.value) !== "") {
        openList();
        countSoon();
      }
    },
    /** The item chosen from the list, or null. */
    selected: () => chosen,
    reset,
    destroy() {
      input.removeEventListener("keydown", onKeydown);
      input.removeEventListener("input", onInput);
      input.removeEventListener("blur", onBlur);
      list.removeEventListener("mousedown", onMouseDown);
      list.removeEventListener("click", onClick);
      add.removeEventListener("click", commit);
      hide();
    },
  };
}
