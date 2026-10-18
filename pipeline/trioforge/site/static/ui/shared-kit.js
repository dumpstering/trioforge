// A kit that came in a link, shown at the top of the answer area of a trio page, before "Wear this".
//
//   createSharedKit({doc, win, announce, words, trio, level, payload, valueView, onView, loadEngine, track, reload}) -> {loading(), loaded(env), failed(text, button)}
//
// `payload` is what first.js took out of the address (the text after `#k=`). The panel is made at once, with "A kit shared with you" and a line that says it is a shared kit, and says
// that it is loading; the section's code drives the rest: `loaded({records, kitvalue, data})` when the item list is in (`records` its Map from a key to a record, `kitvalue` the
// file of the evaluator as the manifest lists it, `{path, bytes, gzip, sha256}`, or null when the manifest lists none, `data` what the loader of the bundle of the trio is given: the
// manifest, the means to fetch with, the address the paths are made absolute against, and the limits of time), and `failed(text, {label, action})` when it could not be had.
//
// The evaluator (engine/kitvalue.js) is a script of its own, listed in the manifest with its size and its SHA-256, and the optimizer's client is not part of it: the panel fetches the
// script, checks its type, its size and its SHA-256 against the manifest, and only then imports it (from the same address, which the browser has by then). A script that is not the one the
// manifest lists is not run, and the value says that it could not be worked out. The loader of the bundle of the trio is in it too. The import has the time that the body of a download has
// (`bodyMs` of the data the section gives): it has no limit of its own, and one that hangs would leave the panel saying that it is working for good. Past the limit the value could not be
// worked out, and the panel offers a Reload (`reload()`, else the page's own), not a Try again: a browser keeps a failed module fetch until the page is reloaded.
//
// What is shown, in order. The link is decoded once the item list is in (input/kitdecode.js, decodeKit): a link that cannot be read says "This kit link could not be read" (and only then;
// while the list loads the panel says that it is loading). Then the kit, in the page's own words, place by place (`words.slotLabel`, the names of the items with `words.tierLabel`, the
// page's words for a place left empty) and a placeholder, "Unknown item (w<page id>) +<tier>", for every item the list does not have. A link of another trio than the page's, or of another
// level than the bundle's, is said plainly, and its value is not worked out. Otherwise the kit is valued under the role, buffs and evidence level the page shows (`valueView()`; the race
// and the level are the kit's) with the engine's own evaluator (engine/kitvalue.js, the script the manifest lists for it: it needs no worker, no download of the optimizer and no question
// to the visitor), and again whenever the page's view changes (`onView`). The weapons are the kit's own, not the page's: the evaluator reads the weapon setup from the kit's hands and
// scores the weapons at the haste of the model's rule for the kit's items, so the page's weapon switch and tier switch change nothing, and the line says the setup and the haste the
// value is for. The best buffs are searched out exactly; when the search ran out of its calls the value is "at least" what it says, and the line says that too. The value leaves out the
// unknown items, and any item that cannot be worn where the link puts it (it says which, and why, in the row); the line says how many. The shared kit has a Share button
// of its own (share.js): its link is made from the decoded kit, so it is the canonical text of the kit, placeholders included (their page ids and tiers are kept so that the next page
// may know them), and not the text that came in.
//
// Everything is text (textContent, never markup). The panel has no live region: what it says is said once through the page's #announce. The focus is never moved.

import { ImportTimeout, fetchBytes, importWithin, sameOriginUrl, sha256Hex } from "../engine/download.js";
import { decodeKit } from "../input/kitdecode.js";
import { createShare } from "./share.js";

/** What a file is called in a message, and the types it is served with: a script (the evaluator). */
const SCRIPT_FILE = Object.freeze({ type: /^(?:text|application)\/(?:x-)?(?:java|ecma)script(?:$|[\s;])/i, noun: "The kit evaluator", stalled: "The kit evaluator download stalled" });

const LEAD = "This is a shared kit. Its link lists the items and nothing else; this page works out its value.";
const LOADING = "Loading the shared kit…";
const WORKING = "Working out its value…";
const UNREADABLE = "This kit link could not be read";
const NO_VALUE = "The value could not be worked out here.";
const NO_VALUE_RELOAD = "The value could not be worked out here. Reload the page to try again.";
const HEADING = "A kit shared with you";
const NOT_EXACT = "The best buffs were not searched out completely, so the kit may be worth more.";
/** The words for a weapon setup, for one that the page has none of among its switches (the same as the page's, view.py SETUP_PHRASES; a test holds them equal). */
const SETUP_WORDS = new Map([
  ["1h-shield", "1H + shield"],
  ["2h", "two-hander"],
  ["dw", "dual wield"],
  ["stick", "stat stick"],
]);
/** Why an item that is on the list is not worn where the link puts it (the reasons of valueOfKit). */
const REASONS = new Map([
  ["slot", "does not fit this place"],
  ["class", "none of this trio's classes can use it"],
  ["race", "this race cannot use it"],
  ["deity", "needs a deity"],
  ["hands", "a two-hander takes both hands"],
  ["lore", "a second copy of a lore item"],
]);
const plural = (n, one, many) => (n === 1 ? one : many);
const PLACES = 22;
/** "pal-mnk-ber" -> "PAL/MNK/BER". */
const trioWords = (code) => String(code).toUpperCase().split("-").join("/");

export function createSharedKit({ doc, win, announce, words, trio, level, payload, valueView, onView, loadEngine, track, reload }) {
  const importModule = loadEngine ?? ((url) => import(url));
  const reloadPage = () => (typeof reload === "function" ? reload() : win.location.reload());
  const el = (tag, attributes = {}, ...children) => {
    const node = doc.createElement(tag);
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    node.append(...children);
    return node;
  };

  // ---- the panel ---------------------------------------------------------------------------------------------------------------------------------
  const stateWords = el("span", { class: "status-text" });
  const state = el("p", { id: "shared-kit-state", class: "note" }, stateWords);
  const value = el("p", { id: "shared-kit-value", class: "shared-value" });
  const body = el("tbody");
  const table = el(
    "table",
    { id: "shared-kit-table", class: "equip" },
    el("caption", { class: "sr-only" }, "The shared kit"),
    el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Slot"), el("th", { scope: "col" }, "Item"))),
    body,
  );
  let kit = null; // the kit as decodeKit gives it, once it was read
  let elsewhere = false; // is it a kit of another trio or level than the page's? Its value is not worked out
  let records = null;
  const share = createShare({
    doc,
    win,
    announce: (text) => say(text),
    id: "shared-kit-share",
    build: () =>
      kit === null ? null : { kit: { v: 1, trio: kit.trio, race: kit.race, level: kit.level, slots: kit.slots.map((slot) => [slot.slotIndex, slot.pageId, slot.tier]) }, left: 0 },
  });
  const heading = el("h2", { id: "shared-kit-h", tabindex: "-1" }, HEADING);
  const panel = el("section", { id: "shared-kit", class: "result shared", "aria-labelledby": "shared-kit-h" }, heading, el("p", { id: "shared-kit-lead", class: "note" }, LEAD), state, value, table, share.node);
  for (const part of [value, table, share.node]) part.hidden = true;
  const answer = doc.getElementById("wear-h")?.closest("section");
  if (answer && answer.parentNode) answer.parentNode.insertBefore(panel, answer);
  else (doc.getElementById("main") ?? doc.body).prepend(panel);

  let button = null;
  function setState(text, offer = null) {
    stateWords.textContent = text;
    state.hidden = text === "";
    button?.remove();
    button = null;
    if (offer !== null) {
      button = el("button", { type: "button", class: "btn" }, offer.label);
      button.addEventListener("click", () => offer.action());
      state.append(" ", button);
    }
  }
  setState(LOADING);

  // ---- what is said ------------------------------------------------------------------------------------------------------------------------------
  let spoken = false;
  function say(text) {
    if (typeof announce === "function") announce(text);
  }
  /** The first thing the panel has to say about the kit is said once, with the heading; later changes of the value are not announced (the page's own announcement of a switch speaks). */
  function sayFirst(text) {
    if (spoken) return;
    spoken = true;
    say(`${HEADING}. ${text}`);
  }

  // ---- the kit ------------------------------------------------------------------------------------------------------------------------------------
  function drawKit() {
    const bySlot = new Map(kit.slots.map((slot) => [slot.slotIndex, slot]));
    const rows = [];
    for (let index = 0; index < PLACES; index += 1) {
      const slot = bySlot.get(index);
      let cell;
      if (slot === undefined) cell = el("td", {}, el("span", { class: "muted" }, words.emptyName));
      else if (slot.unknown === true) cell = el("td", {}, el("span", { class: "muted" }, `Unknown item (w${slot.pageId}) ${words.tierLabel(slot.tier)}`));
      else cell = el("td", {}, el("span", { class: "owned-name" }, `${slot.item.name} ${words.tierLabel(slot.tier)}`));
      rows.push(el("tr", {}, el("th", { scope: "row" }, words.slotLabel(index)), cell));
    }
    body.replaceChildren(...rows);
    table.hidden = false;
  }

  /** In each row whose item the value does not hold: why. */
  function markLeft(left) {
    const rows = [...body.children];
    for (const row of rows) row.querySelector(".owned-meta")?.remove();
    for (const { slotIndex, reason } of left) {
      const why = REASONS.get(reason);
      if (why === undefined) continue;
      const cell = rows[slotIndex]?.querySelector("td");
      if (cell) cell.append(" ", el("span", { class: "owned-meta" }, `Not counted: ${why}`));
    }
  }

  // ---- the value ----------------------------------------------------------------------------------------------------------------------------------
  let engineFile = null; // the file of the evaluator, from the manifest: {path, bytes, gzip, sha256}, or null
  let fetching = null; // what the engine's loader of the bundle is given, besides the trio and the level
  let bundleOnce = null;
  let engineOnce = null;
  let run = 0; // the number of the last valuation: the answer of an older one is not drawn
  let shownKey = null; // the view the value on the page is for

  const getBundle = () => {
    bundleOnce ??= getEngine()
      .then((engine) => engine.loadKitBundle({ ...fetching, trio, level }))
      .catch((error) => {
        bundleOnce = null;
        throw error;
      });
    return bundleOnce;
  };
  /** The script of the evaluator is fetched in pieces and checked (its type, its size, its SHA-256) before it is run: one that is not the one the manifest lists is refused. */
  async function checkScript() {
    if (engineFile === null) throw new Error("the manifest lists no evaluator");
    const bytes = await fetchBytes(sameOriginUrl(engineFile.path, fetching.base), engineFile.bytes, fetching.fetchImpl, () => {}, fetching.stallMs, fetching.bodyMs, SCRIPT_FILE);
    if ((await sha256Hex(bytes)) !== engineFile.sha256) throw new Error("the evaluator is not the one the manifest lists");
  }
  const getEngine = () => {
    engineOnce ??= Promise.resolve()
      .then(() => checkScript())
      .then(() => importWithin(importModule(sameOriginUrl(engineFile.path, fetching.base).href), fetching.bodyMs, SCRIPT_FILE.noun))
      .then((module) => {
        if (typeof module?.valueOfKit !== "function" || typeof module.loadKitBundle !== "function") throw new Error("the evaluator's script has no evaluator");
        return module;
      })
      .catch((error) => {
        engineOnce = null;
        throw error;
      });
    return engineOnce;
  };

  function showValue(result, unknownCount) {
    const n = (result.exact ? "" : "at least ") + words.fmtInt(words.displayInt(result.value));
    const race = typeof words.raceName === "function" ? words.raceName(kit.race) : kit.race;
    const view = typeof words.viewText === "function" ? words.viewText() : "";
    const setup = (typeof words.setupText === "function" ? words.setupText(result.setup) : undefined) ?? SETUP_WORDS.get(result.setup) ?? result.setup;
    let line = `Kit value ${n} for ${race}${view === "" ? "" : `, ${view}`}.`;
    // a stat stick scores no weapon damage, so the haste of the weapons is nothing to say
    line += ` Weapons: ${setup}, read from the kit's hands${result.setup === "stick" ? "" : `, at ${result.hasteAssumed}% haste`}.`;
    if (unknownCount > 0) line += ` Excludes ${unknownCount} unknown ${plural(unknownCount, "item", "items")}.`;
    const other = result.left.length;
    if (other > 0) line += ` ${other} ${plural(other, "item cannot", "items cannot")} be worn where the link puts ${plural(other, "it", "them")} and ${plural(other, "is", "are")} not counted.`;
    if (!result.exact) line += ` ${NOT_EXACT}`;
    value.textContent = line;
    value.hidden = false;
    markLeft(result.left);
    return n;
  }

  /** Work out the value under the view the page shows now; a valuation for the view that is shown is not made again. */
  function refresh(force = false) {
    if (kit === null || elsewhere) return Promise.resolve();
    let view;
    try {
      view = valueView();
    } catch {
      view = null;
    }
    const key = JSON.stringify(view);
    if (!force && key === shownKey) return Promise.resolve();
    const mine = (run += 1);
    if (shownKey === null) setState(WORKING);
    return (async () => {
      try {
        const [bundle, engine] = await Promise.all([getBundle(), getEngine()]);
        if (mine !== run) return;
        const places = kit.slots.filter((slot) => slot.unknown !== true).map((slot) => ({ slotIndex: slot.slotIndex, key: slot.key, tier: slot.tier }));
        const result = engine.valueOfKit({ bundle, records, race: kit.race, ...view, places });
        if (mine !== run) return;
        shownKey = key;
        setState("");
        const n = showValue(result, kit.slots.length - places.length);
        sayFirst(`Kit value ${n}.`);
      } catch (error) {
        if (mine !== run) return;
        shownKey = null;
        value.hidden = true;
        // an import that ran past its time is pending in the browser still, or has failed there for good: a Try again would find the same, and only a reload starts it again
        const late = error instanceof ImportTimeout;
        setState(late ? NO_VALUE_RELOAD : NO_VALUE, late ? { label: "Reload", action: reloadPage } : { label: "Try again", action: () => track?.(refresh(true)) ?? refresh(true) });
        sayFirst(late ? NO_VALUE_RELOAD : NO_VALUE);
      }
    })();
  }

  // ---- what the section's code tells it ------------------------------------------------------------------------------------------------------------
  function hideAll() {
    value.hidden = true;
    table.hidden = true;
    share.show(false);
  }

  const unreadable = () => {
    hideAll();
    setState(UNREADABLE);
    sayFirst(`${UNREADABLE}.`);
  };

  if (typeof onView === "function") {
    onView(() => {
      const work = refresh(false);
      if (typeof track === "function") track(work);
    });
  }

  return {
    /** The item list is being loaded (again). */
    loading() {
      run += 1;
      hideAll();
      setState(LOADING);
    },
    /** The item list is in: read the link, show the kit, and work out its value. */
    loaded(env) {
      records = env.records;
      engineFile = env.kitvalue ?? null;
      fetching = env.data;
      const decoded = decodeKit(payload, records);
      if (decoded.kit === null) {
        kit = null;
        unreadable();
        return;
      }
      kit = decoded.kit;
      drawKit();
      shownKey = null;
      value.hidden = true;
      elsewhere = kit.trio !== trio || kit.level !== level;
      if (elsewhere) {
        const text =
          kit.trio !== trio
            ? `This kit is for the trio ${trioWords(kit.trio)}, and this page is for ${trioWords(trio)}, so its value is not worked out here.`
            : `This kit is for level ${kit.level}, and this page is for level ${level}, so its value is not worked out here.`;
        share.show(false);
        setState(text);
        sayFirst(text);
        run += 1;
        return;
      }
      share.show(true);
      const work = refresh(true);
      if (typeof track === "function") track(work);
    },
    /** The item list could not be had: say so, with a button for what can be done. */
    failed(text, offer = null) {
      run += 1;
      kit = null;
      hideAll();
      setState(text, offer);
    },
  };
}
