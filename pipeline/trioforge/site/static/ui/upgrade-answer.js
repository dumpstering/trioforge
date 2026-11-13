// The answer of the Upgrade section of a trio page, drawn under the list of the gear the visitor has (upgrade-input.js): what to wear now, the best next addition, and the steps
// after it, all worked out by the optimizer (engine/client.js) in the visitor's browser.
//
//   createUpgradeAnswer(root, {gear, records, trio, level, view, onView, words, clientPath, loadEngine, announce, onUpdated, reload, doc, win, pauseMs}) -> {send, halt} | null
//
// `gear` is the gear input (createGearInput), `records` the item table's records (a Map from key to record), `trio` the trio's code ("pal-mnk-ber") and `level` the page's level.
// `view()` gives the view the page shows, `{race, role, buffs, evidence, setup, weights}` (the setup is the one shown, never none; `weights` is the table of slider positions that
// a request carries, `{multipliers: {group: position}}`, or nothing for the role's own: every request of the section has it), and `onView(callback)` tells the answer when the page
// shows another one. `words` are the page's own words, which the page code hands over (this file may not import format.js: the page script imports it, and the build would then
// load a chunk that the page and the section share with the page): `tierLabel`, `arrivalText` (the words for the tier an item arrives at), `reachText`, `fmtInt`, `fmtSigned`,
// `displayInt`, `emptyName` and `slotLabel(index)`, the name of a place of the kit as the page's kit table writes it. `clientPath` is the address of the client's code, as
// engine-manifest.json names it; `loadEngine(url)` imports a module (the default is the browser's own import; tests give another). `announce(text)` is the page's live region. The
// container is #upgrade-results, which the template writes empty; the section has no live region of its own, and what it says is said once through `announce`.
//
// When it runs. Whenever the list of the gear is not empty and changes, and whenever the view the page shows changes in a way the request uses (the race, the role, the setup, the
// buffs, the evidence level, the weights), the answer waits for a pause (PAUSE_MS), ends the path in flight (client.stop(); a path that the worker has not got, because it waits for the
// visitor's answer to the question or for another request, is taken back with the signal of the request instead, so that a yes loads nothing for it; so is the request of an expander
// that is on the client, which nobody wants any more: it is not waited for, and the worker starts again from the module the client kept, with no download. The section never calls
// client.cancel(), which ends what every part of the page asked for: the sliders have requests on the same client) and sends one farm path request: the view, the owned pairs of the list (gear.toOwnedPairs(), which
// keeps the protocol's limits), the tier mode in force ("ready4" until the visitor chooses another in the Tier mode expander), eight steps and a minute. A request that is the same as
// the one sent last (a view that came back, an item added and taken out, a file in which a copy only changed its place) is not sent again, unless that one failed: what is on the page
// stands, and so do the answers the expanders have drawn and the request they have on the client; the words about where the copies are (Equip now's notes, the spare of Every slot)
// are drawn again. The client is given a request only when the one before it is over, and only if no newer request was made meanwhile (it works out every request it is given, a
// superseded one too): of the requests made while a long step ends, the last one waits, and the others never begin. A step, a report of progress or a result of a request that a newer
// one superseded is never drawn (each request has a number, and its callbacks look at it), and when the newer one is sent whatever the older one drew is cleared. An empty list sends
// nothing, and ends the path and clears the results. A request that comes back cancelled when the section did not take it back (another part of the page cancelled it), with the optimizer
// agreed to, is sent again, once; the Cancel button of the loading panel marks its error as the visitor's, and for that one nothing is sent again.
//
// What it draws. Equip now (step 0): the kit, place by place in the order of the kit, at the tiers of the owned copies; for each copy that the kit wears but the file does not say is
// worn, where it is ("in your bank: move to worn"); a copy added by name has no place and no note. The label says what the solver can say: the best kit when it proved it, "best found,
// not proven optimal" or "not found in time" with the protocol's own words otherwise, and never the best of a solve that ran out of time. Next step (step 1): the single best addition,
// with its gain (as the page shows a runner-up's difference in kit value), where it comes from (the item table's summary of its source, as the page words a source) and what reaching
// the tier costs (as the page words the reach of an item); for a copy, when the visitor owns a lower copy of the same item that the kit after the step does not wear (and that no
// line offered already), the offer to upgrade that one instead, when that takes no more copies than another one (the copy itself and what brings it to the tier). Then (steps 2 to 8):
// one line each (what, gain, cost), as they arrive, with the Stop button (above the answer, where no row pushes it down) while the path runs, and the end said honestly. Progress
// is one quiet line. Neither Stop nor that line is there while the client's question waits for the visitor's answer, when nothing is being worked out: they come when the client
// reports (its loading, its progress or a step) after a yes, or at once for a visitor who had agreed already. A fault is a line with what happened and a button (Try again, Reload, Load the optimizer); the steps already shown stay.
//
// Under Then are three expanders, closed until the visitor opens them (nothing of theirs is worked out before): Best 2 and 3 sets (the best 2 and the best 3 additions made at once,
// each set with its additions and its gain over Equip now), Every slot (for each of the 22 places what Equip now wears there and the best three swaps, with their change in
// kit value: an evaluation, not a solve) and Tier mode (Ready +4, As it arrives with a difficulty, or Fixed at a tier: the tier the additions are worked out at, which
// a change restarts the answer with). They come with the answer. The first two ask the optimizer through the answer's one client and its rule of one request at a time: a request is
// given to the client when the path has ended and the one before it is over, and only if nothing has changed meanwhile; of the open ones the one that was opened first is worked out
// first, whichever it is. Of a best sets request the sets of 2 and 3 are two requests, and Every slot is one, made from the kit and the optional buffs of Equip now. The optimizer counts the copies of the items the visitor has: it offers, for a place, the
// swap to an item that can be got at the tier of the mode whatever the visitor has (a copy to get), and the swap to any other item the visitor has only while a copy is spare. The page
// hides none of them: of an item on the list it says "you have it" (and where the spare is) when a copy is spare, and "get another copy" when the kit wears every copy. A change of the
// gear, the view or the tier mode marks what they have computed as old (a result of an older request is never drawn, and what they show is cleared when the request that follows the change is sent): an open one is
// worked out again after the path, a closed one when it is next opened. A fault in one says so inside it, with its button, and leaves the answer of the path alone. When an answer is
// drawn it is said once, through `announce`; the section has no live region of its own, and the focus stays on the summary that was opened.
//
// Share. Equip now has a "Share this kit" button (share.js) once it shows a kit: the link is the trio page's own address and the kit, place by place (page id and tier), at the
// race the answer was asked for; it never holds the gear the visitor owns, a count, a place, a value or a word. The page's #announce says what the click did.
//
// Everything is text (textContent, never markup). Focus does not move by itself while the steps stream. When the control that has the focus goes (Stop at the end of the path, Try
// again when a request is sent), the focus goes to the control that takes its place, else to the answer.

import { sameOriginUrl } from "../engine/download.js";
import { BEST_SETS, EVERY_SLOT, FARM_PATH, LIMITS, PROTOCOL_VERSION } from "../engine/protocol.js";
import { MAX_DIFFICULTY, MAX_TIER, READY_TIER, costToReach } from "../engine/tiers.js";
import { createShare, slotsOfIdents } from "./share.js";

/** What the section says in its own place when the data is of another release than the page's (the page says a longer sentence in its status). */
export const SECTION_UPDATED = "Data updated, reload the page to see this section.";

/** The time the gear and the view must stay as they are before a request is sent, and the time a path may take (the phone gate's, engine/protocol.js). */
const PAUSE_MS = 600;
const BUDGET_MS = 60_000;
const PLACES = 22;
/** Where a copy that is not worn can be, in the order a visitor would look for it, and the words for it. */
const AWAY = [
  ["bag", "in your bags"],
  ["bank", "in your bank"],
  ["sharedbank", "in your shared bank"],
  ["cursor", "on your cursor"],
  ["keyring", "on your key ring"],
];
/** Where the copies of an item on the list are, worn or away, for "you have it". */
const HERE = [["worn", "worn"], ...AWAY];
const ENDINGS = new Map([
  ["no-gain", "Nothing more you can add gains anything."],
  ["time", "Stopped at the time limit: the next steps were not computed."],
  ["stopped", "Stopped."],
]);
const WORKING = "Working out your answer…";
const REST = "The rest could not be computed.";
const NOT_LOADED = "The optimizer was not loaded, so there is no answer for your gear yet.";
const CODE_NOT_LOADED = "Couldn't load the optimizer. Reload the page to try again.";
const WORKER_DROPPED = "Couldn't work out your answer. The optimizer sent something that was not expected, so it was stopped.";
/** The sizes of the sets the optimizer works out, the swaps it gives for a place, and what the expanders say while they wait (they are worked out when the path has ended). */
const SET_SIZES = [2, 3];
const SWAPS_A_PLACE = 3;
const WAITING = "Waiting for the answer above…";
const QUEUED = "Waiting its turn…";
const BLOCKED = "There is no answer above to work from yet.";
const NO_KIT = "Equip now was not found in time, so there is nothing to work from.";
const NOTHING_FITS = "Nothing else fits here";
const GET_ANOTHER = "get another copy";
const EVALUATION =
  'This is an evaluation, not a solve: each figure is the change in kit value if you swapped just that slot and kept the rest of the kit. For an item you have, "you have it" means that you have a copy to spare, and "get another copy" that the kit wears every copy you have.';

const split = (ident) => {
  const at = ident.lastIndexOf("@");
  return [ident.slice(0, at), Number(ident.slice(at + 1))];
};
const plural = (n, one, many) => (n === 1 ? one : many);
/** A copy of the table of weights the page gave (a table of numbers: what the view holds is not the request's to change). */
const copyOf = (weights) => JSON.parse(JSON.stringify(weights));

/** What the item table says of where an item comes from, in the order and the words of the page's Source column: where it drops, the quest, the vendor, a recipe, foraging. */
function sourceText(record) {
  const source = record === undefined ? undefined : record.source;
  if (source === undefined || source === null) return "";
  const more = source.more ?? {};
  const list = (kind, lead) => (source[kind] === undefined ? "" : lead + source[kind].join(", ") + (more[kind] ? ` and ${more[kind]} more` : ""));
  return list("drops", "") || list("quests", "quest: ") || list("sold", "vendor: ") || (source.crafted ? "crafted" : "") || list("forage", "Foraged in ");
}

/** The note for each place of a kit, from the owned list as it was when the request was sent: where a copy that the kit wears but the file does not say is worn is. */
function placeNotes(kit, owned) {
  const copies = new Map();
  for (const entry of owned) {
    const here = (location) => entry.locations.find((place) => place.location === location)?.count ?? 0;
    copies.set(`${entry.key}@${entry.tier}`, { worn: here("worn"), away: AWAY.map(([location, words]) => [words, here(location)]) });
  }
  return kit.map((ident) => {
    const have = ident === null ? undefined : copies.get(ident);
    if (have === undefined) return "";
    if (have.worn > 0) {
      have.worn -= 1; // (the copies the file says are worn are the first the kit wears)
      return "";
    }
    const place = have.away.find((entry) => entry[1] > 0);
    if (place === undefined) return ""; // (added by name: it has no place)
    place[1] -= 1;
    return `${place[0]}: move to worn`;
  });
}

/**
 * What is said of an item that is on the list when the kit wears `elsewhere` copies of it in other places: that the visitor has it, and where the spare is (worn, in a bag, in the bank
 * ...; a copy added by name has no place, and nothing more is said). The copies the kit wears are the first ones, in the order Equip now's notes count them (the worn ones, then the
 * bags, the bank, the shared bank ...), so what is left is the spare. When no copy is spare the swap is to a copy that is still to be got: null.
 */
function spareText(entry, elsewhere) {
  if (entry.count <= elsewhere) return null;
  const left = HERE.map(([location, text]) => [text, entry.locations.find((place) => place.location === location)?.count ?? 0]);
  let wearing = elsewhere;
  for (const place of left) {
    const used = Math.min(place[1], wearing);
    place[1] -= used;
    wearing -= used;
  }
  const places = left.filter((place) => place[1] > 0).map((place) => place[0]);
  return places.length === 0 ? "you have it" : `you have it (${places.join(", ")})`;
}

export function createUpgradeAnswer(root, env) {
  const { gear, records, trio, level, view, onView, words, clientPath, announce, onUpdated, reload } = env;
  const onEquipKit = typeof env.onEquipKit === "function" ? env.onEquipKit : null; // told the kit of Equip now whenever it is drawn, and null when there is none (the section Effects to exalt matches a plan to it)
  const onGear = typeof env.onGear === "function" ? env.onGear : null; // told the same for the panel Spend your motes (motes.js), which also needs the request the kit was worked out for
  const doc = env.doc ?? root.ownerDocument;
  const win = env.win ?? doc.defaultView;
  const loadEngine = env.loadEngine ?? ((url) => import(url));
  const pauseMs = env.pauseMs ?? PAUSE_MS;
  const box = root.querySelector("#upgrade-results");
  if (box === null) return null;

  // ---- the elements ---------------------------------------------------------------------------------------------------------------------------------
  const el = (tag, attributes = {}, ...children) => {
    const node = doc.createElement(tag);
    for (const [name, value] of Object.entries(attributes)) {
      if (name === "text") node.textContent = value;
      else node.setAttribute(name, value === true ? "" : value);
    }
    node.append(...children);
    return node;
  };
  const heading = (id, text) => el("h3", { id, tabindex: "-1", text });
  const slot = el("div", { class: "engine-slot" }); // the optimizer's question and its loading panel go here (the client builds them)
  const equipHead = heading("upgrade-equip-h", "Equip now");
  const equipLabel = el("p", { id: "upgrade-equip-label", class: "note" });
  const equipRows = el("tbody");
  // the kit that Equip now shows, for the Share button: its places (the race is the one the answer was asked for, which the page may have left since)
  const share = createShare({
    doc,
    win,
    announce: (text) => say(text),
    id: "upgrade-share",
    build() {
      const shown = last === null ? null : last.ctx;
      if (shown === null || !shown.equip) return null;
      const { slots, left } = slotsOfIdents(shown.equip.kit);
      return { kit: { v: 1, trio, race: shown.request.scenario.race, level, slots }, left };
    },
  });
  const equip = el(
    "section",
    { id: "upgrade-equip", class: "result", "aria-labelledby": "upgrade-equip-h", hidden: true },
    equipHead,
    equipLabel,
    share.node,
    el(
      "table",
      { class: "equip" },
      el("caption", { class: "sr-only", text: "What to wear now" }),
      el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Slot" }), el("th", { scope: "col", text: "Item" }))),
      equipRows,
    ),
  );
  const nextHead = heading("upgrade-next-h", "Next step");
  const nextBody = el("div", { class: "step" });
  const next = el("section", { id: "upgrade-next", class: "result", "aria-labelledby": "upgrade-next-h", hidden: true }, nextHead, nextBody);
  const thenHead = heading("upgrade-then-h", "Then");
  const thenList = el("ol", { id: "upgrade-then-list", class: "steps", start: "2" });
  const end = el("p", { id: "upgrade-end", class: "note", hidden: true });
  const then = el(
    "section",
    { id: "upgrade-then", class: "result", "aria-labelledby": "upgrade-then-h", hidden: true },
    thenHead,
    el("p", { id: "upgrade-then-label", class: "note", text: "Each step is the single best addition after the steps before it." }),
    thenList,
    end,
  );
  const progress = el("p", { id: "upgrade-progress", class: "note", hidden: true });
  const bar = el("div", { class: "path-bar" }, progress);
  const faultWords = el("span", { class: "status-text" });
  const fault = el("p", { id: "upgrade-fault", class: "status", hidden: true }, faultWords);
  // the line with Stop and the progress, and the line of a fault, are above the answer: the rows that come under Equip now and Then never push them down
  box.replaceChildren(slot, bar, fault, equip, next, then);

  // ---- what is said ---------------------------------------------------------------------------------------------------------------------------------
  const say = (text) => {
    if (typeof announce === "function") announce(text);
    else {
      const live = doc.getElementById("announce");
      if (live) live.textContent = text;
    }
  };

  // ---- the state ------------------------------------------------------------------------------------------------------------------------------------
  let run = 0; // the number of the latest request: what an older one says is never drawn
  let timer = null; // the pause before a request is sent
  let sentKey = null; // the view the latest request was for
  let last = null; // the latest request that was sent: {key, ctx, failed, epoch}, to know that a request that is the same need not be sent again, and under which epoch its answers were asked
  let inFlight = null; // the client's work on the latest request it was given: a promise that is kept when that request is over, however it ended
  let pathAsk = null; // the path request the client has (its ctx: {controller, sent}), until it is over: `sent` says that the worker has it, and until then it can be taken back
  let onClient = null; // the request of an expander the client is working on, {controller, sent} (a request of an expander is not a path: stop() does not end it)
  let client = null;
  let clientPromise = null;
  let stopButton = null;
  let faultButton = null;
  let faultAction = null;
  let tierMode = { mode: "ready4" }; // the tier mode in force: the requests name it, and the summary of its expander says it
  let epoch = 0; // moved by every change (of the gear, the view or the tier mode), and by every request that is sent: what an expander computed or is computing before is old
  let pumping = false; // is a loop giving the expanders' requests to the client?
  let opening = 0; // counts the openings of expanders: of the open ones, the one opened first is worked out first (the number of an expander that is closed is 0)
  let more = null; // the block of the expanders (made with the rest that can fail, last)
  const expanders = []; // best sets, Every slot: the ones that ask the optimizer, in the order of the page

  const nameOf = (key) => records.get(key)?.name ?? key;
  const viewKey = () => JSON.stringify(view());

  // ---- focus ----------------------------------------------------------------------------------------------------------------------------------------
  /** Where the focus goes when the control that had it is gone: the control that takes its place, else the answer, else the list of the gear. */
  const refuge = () =>
    faultButton ?? stopButton ?? [thenHead, nextHead, equipHead].find((node) => node.closest("[hidden]") === null) ?? root.querySelector("#upgrade-owned-h");
  /** Change what is drawn; if the focus was in the answer (but not in the optimizer's own panel) and the change took it, put it on the refuge. */
  function keepFocus(change) {
    const held = doc.activeElement;
    const inside = held !== null && held !== doc.body && box.contains(held) && !slot.contains(held);
    change();
    const now = doc.activeElement;
    if (inside && (now === null || now === doc.body || now.closest("[hidden]") !== null)) refuge()?.focus();
  }

  // ---- drawing --------------------------------------------------------------------------------------------------------------------------------------
  function clearLine() {
    faultWords.textContent = "";
    fault.hidden = true;
    faultAction = null;
    faultButton?.remove();
    faultButton = null;
  }

  function clearStop() {
    stopButton?.remove();
    stopButton = null;
  }

  /** Tell the page the kit that Equip now shows, or that there is none: each place `{key, name, tier}` or null, and the record of an item of the item table (it says what a class may wear and where). */
  function publishEquip(kit) {
    if (onEquipKit === null) return;
    try {
      onEquipKit(
        kit === null
          ? null
          : {
              kit: kit.map((ident) => {
                if (ident === null) return null;
                const [key, tier] = split(ident);
                return { key, name: nameOf(key), tier };
              }),
              record: (key) => records.get(key) ?? null,
              defaults: env.itemDefaults ?? null,
            },
      );
    } catch {
      // a fault in the other section is its own, not the answer's
    }
  }

  /**
   * Tell the panel Spend your motes the kit of Equip now as `{request, kit, buffs}` (the request it was worked out for: its view and weights; the kit as idents; the optional buffs it was found with), or that there is
   * none: null, with whether another is on its way (a change was made, and a new answer is being worked out) or nothing is coming (the list of the gear is empty, or no kit was found).
   */
  function tellGear(source, pending = false) {
    if (onGear === null) return;
    try {
      onGear(source, pending);
    } catch {
      // a fault in the panel is its own, not the answer's
    }
  }
  const gearOf = (ctx) => (ctx.equip ? { request: ctx.request, kit: [...ctx.equip.kit], buffs: [...ctx.equip.buffs] } : null);

  /** Nothing of an answer on the page. */
  function reset() {
    publishEquip(null);
    for (const part of [equip, next, then]) part.hidden = true;
    equipLabel.textContent = "";
    share.show(false);
    equipRows.replaceChildren();
    nextBody.replaceChildren();
    thenList.replaceChildren();
    end.textContent = "";
    end.hidden = true;
    progress.textContent = "";
    progress.hidden = true;
    clearStop();
    clearLine();
    clearMore();
  }

  function setProgress(text) {
    if (progress.textContent !== text) progress.textContent = text;
    progress.hidden = text === "";
  }

  function setLine(text, label, action) {
    fault.hidden = false;
    faultWords.textContent = text;
    faultAction = action ?? null;
    if (label === null) {
      faultButton?.remove();
      faultButton = null;
      return;
    }
    if (faultButton === null) {
      faultButton = el("button", { type: "button", class: "btn" });
      faultButton.addEventListener("click", () => faultAction?.());
      fault.append(faultButton);
    }
    faultButton.textContent = label;
  }

  const filledOf = (kit) => kit.filter((ident) => ident !== null).length;

  function equipText(step) {
    if (step.kit === null) return `${step.label.charAt(0).toUpperCase()}${step.label.slice(1)}.`; // (the protocol's own words: "not found in time")
    const worth = `kit value ${words.fmtInt(words.displayInt(step.value))}`;
    return step.proven ? `The best kit from the gear you have (${worth}).` : `Time limit reached: ${step.label} (${worth}).`;
  }

  /** The rows of Equip now: the kit place by place, and for a copy that is not worn where it is, from the list `owned` as it is. */
  function drawEquipRows(step, owned) {
    const notes = step.kit === null ? [] : placeNotes(step.kit, owned);
    equipRows.replaceChildren(
      ...(step.kit ?? []).map((ident, index) => {
        let cell;
        if (ident === null) cell = el("td", { class: "muted", text: words.emptyName });
        else {
          const [key, tier] = split(ident);
          cell = el("td", {}, el("span", { class: "owned-name", text: `${nameOf(key)} ${words.tierLabel(tier)}` }));
          if (notes[index] !== "") cell.append(" ", el("span", { class: "owned-meta equip-where", text: notes[index] }));
        }
        return el("tr", {}, el("th", { scope: "row", text: words.slotLabel(index) }), cell);
      }),
    );
  }

  function drawEquip(ctx, step) {
    ctx.equipStep = step;
    drawEquipRows(step, ctx.owned);
    equipLabel.textContent = equipText(step);
    equip.hidden = false;
    ctx.drawn = true;
    ctx.equip = step.kit === null ? null : { kit: [...step.kit], buffs: [...(step.buffs ?? [])] }; // (what Every slot starts from; none when no kit was found)
    publishEquip(step.kit === null || filledOf(step.kit) === 0 ? null : step.kit);
    tellGear(gearOf(ctx), false);
    share.show(step.kit !== null && filledOf(step.kit) > 0);
    if (more !== null) more.hidden = false;
    ctx.equipSaid = step.kit === null ? `Equip now: ${step.label}.` : `Equip now is ready: ${filledOf(step.kit)} of ${PLACES} places filled.`;
  }

  /**
   * The offer to upgrade a lower copy of the item instead of getting another: the nearest copy below the tier that the kit after the step does not wear and that no line has offered
   * already, when upgrading it takes no more copies than getting another. Another copy is the copy itself and the merging that brings it to the tier (what the line's own reach counts:
   * `copiesAtArrival` is the merging alone); upgrading a copy that is owned is the merging alone, which `costToReach` counts from the tier of the copy.
   */
  function hintOf(ctx, step, key, tier) {
    if (step.kind !== "copy" || step.cost === null) return "";
    const wornAfter = (ident) => step.kit.filter((place) => place === ident).length;
    const D = ctx.request.tierMode.mode === "arrives" ? ctx.request.tierMode.D : MAX_DIFFICULTY;
    const another = step.cost.copiesAtArrival + 1;
    for (let lower = tier - 1; lower >= 0; lower -= 1) {
      const ident = `${key}@${lower}`;
      if ((ctx.available.get(ident) ?? 0) - wornAfter(ident) - (ctx.offered.get(ident) ?? 0) <= 0) continue;
      try {
        const copies = costToReach(records.get(key), lower, tier, { D }).copies_at_arrival;
        if (copies > another) return "";
        ctx.offered.set(ident, (ctx.offered.get(ident) ?? 0) + 1); // (a spare is the copy of one line only)
        return `or upgrade your spare ${words.tierLabel(lower)} copy (${copies < another ? "cheaper" : "the same cost"})`;
      } catch {
        return ""; // (an item the tier rules cannot read: no offer)
      }
    }
    return "";
  }

  /**
   * A change in kit value as the page shows a difference: rounded half up, with its sign and its thousands separated. One that is more than nothing but rounds to nothing is "+<1", not
   * 0, and a loss of the like is "−<1" (with the page's minus sign).
   */
  function signed(value) {
    const shown = words.displayInt(value);
    if (shown === 0 && value > 0) return "+<1";
    if (shown === 0 && value < 0) return `${words.fmtSigned(-1).slice(0, -1)}<1`;
    return words.fmtSigned(shown);
  }

  const gainOf = (step) => signed(step.gainValue);

  function costText(step, tier) {
    const cost = step.cost;
    if (cost === null) return "";
    if (step.kind !== "upgrade") return words.reachText(tier - cost.potentials, tier);
    return `${words.fmtInt(cost.copiesAtArrival)} ${plural(cost.copiesAtArrival, "copy", "copies")} to reach ${words.tierLabel(tier)}`;
  }

  /**
   * The parts of the line of a step that was found (the Next step has its source, and its name on a line of its own; a step under Then is one line), and the copies there are after it.
   * An addition of a best set (`inSet`) is a line of its own with its source: the set has one gain for all its additions and one label, and its copies are counted before its lines.
   */
  function describe(ctx, step, withSource, inSet = false) {
    const [key, tier] = split(step.ident);
    const name = nameOf(key);
    const what =
      step.kind === "upgrade"
        ? `Upgrade your ${name} ${words.tierLabel(step.sourceTier)} to ${words.tierLabel(tier)}`
        : `Get ${step.kind === "copy" ? "another " : ""}${name} ${words.tierLabel(tier)}`;
    const source = withSource ? sourceText(records.get(key)) : "";
    const parts = [
      [withSource && !inSet ? "owned-name step-what" : "step-what", what],
      ["owned-meta step-gain", inSet ? "" : `Gain ${gainOf(step)} kit value`],
      ["owned-meta step-source", source === "" ? "" : `Source: ${source}`],
      ["owned-meta step-cost", costText(step, tier)],
      ["owned-meta step-hint", hintOf(ctx, step, key, tier)],
      ["owned-meta step-label", inSet || step.status === "optimal" ? "" : `(${step.label})`],
    ];
    if (!inSet) {
      ctx.available.set(step.ident, (ctx.available.get(step.ident) ?? 0) + 1);
      if (step.kind === "upgrade") ctx.available.set(`${key}@${step.sourceTier}`, (ctx.available.get(`${key}@${step.sourceTier}`) ?? 0) - 1);
    }
    const nodes = [];
    for (const [className, text] of parts) {
      if (text !== "") nodes.push(el("span", { class: className, text }), " ");
    }
    return { what, nodes };
  }

  function drawStep(ctx, step) {
    const lost = !step.found;
    if (step.index === 1) {
      const line = lost ? { what: "", nodes: [el("span", { text: `Step 1: ${step.label}.` })] } : describe(ctx, step, true);
      nextBody.replaceChildren(...line.nodes);
      next.hidden = false;
      ctx.drawn = true;
      tell(ctx, lost ? `Next step: ${step.label}.` : `Next step: ${line.what}, gain ${gainOf(step)}.`);
      return;
    }
    const line = lost ? { nodes: [`Step ${step.index}: ${step.label}.`] } : describe(ctx, step, false);
    thenList.append(el("li", {}, ...line.nodes));
    then.hidden = false;
  }

  /** One announcement: what is to be said, and Equip now's before it if that was not said yet. */
  function tell(ctx, text) {
    const lead = ctx.equipSaid === null ? "" : `${ctx.equipSaid} `;
    ctx.equipSaid = null;
    say(lead + text);
  }

  // ---- the expanders: best sets, Every slot and the tier mode ---------------------------------------------------------------------------------------
  /** Change what an expander shows; if the focus was in it, on a button that goes, it is put on the summary, which is always there. */
  function holdFocus(exp, change) {
    const held = doc.activeElement;
    const inside = held !== null && held !== exp.summary && exp.node.contains(held);
    change();
    if (inside && !exp.node.contains(doc.activeElement)) exp.summary.focus();
  }

  const nameOfIdent = (ident) => {
    const [key, tier] = split(ident);
    return `${nameOf(key)} ${words.tierLabel(tier)}`;
  };

  /** The path of the answer in hand: the latest request, when nothing has superseded it. */
  const currentPath = () => (last !== null && last.ctx.id === run ? last.ctx : null);

  /** The request of an expander: the scenario, the owned pairs and the tier mode of the request of the path, and what the mode adds. */
  function expanderRequest(ctx, mode, extra) {
    const asked = ctx.request;
    return {
      v: PROTOCOL_VERSION,
      kind: "scenario",
      trio,
      level,
      mode,
      scenario: { ...asked.scenario },
      owned: asked.owned.map((pair) => [...pair]),
      tierMode: { ...asked.tierMode },
      ...(asked.weights === undefined ? {} : { weights: copyOf(asked.weights) }),
      ...extra,
      budgetMs: BUDGET_MS,
    };
  }

  /**
   * An expander: a details with its summary, a quiet line for what it waits for or works at, the line of a fault with its button, and the place for its answer. `todo(exp, ctx)` gives
   * the requests it still lacks for the path `ctx`, in the order they are asked in: `{key, working, request(), draw(result)}`. `epoch` is the epoch its content is of: when a change
   * has moved the epoch, what it has is old.
   */
  function makeExpander({ id, title, headline, ready, todo }) {
    const summary = el("summary", { text: headline });
    const state = el("p", { id: `${id}-state`, class: "note", hidden: true });
    const lineWords = el("span", { class: "status-text" });
    const line = el("p", { id: `${id}-fault`, class: "status", hidden: true }, lineWords);
    const body = el("div", { id: `${id}-body`, class: "expander-body" });
    const node = el("details", { id, class: "expander" }, summary, state, line, body);
    let button = null;
    const hideLine = () => {
      lineWords.textContent = "";
      line.hidden = true;
      button?.remove();
      button = null;
    };
    const exp = {
      title,
      ready,
      node,
      summary,
      body,
      drawn: new Set(), // the keys of the requests whose answers are in the body
      redraw: null, // draws the body again from the same answer, for the words that depend on where the copies of the gear are (null: there is nothing to draw)
      fault: false,
      busy: false, // is a request of it being given to the client, or is the client working it out?
      stamp: 0, // the epoch of that request
      opened: 0, // the number of its opening: 0 while it is closed, and until it is first seen open
      epoch,
      jobs: (ctx) => todo(exp, ctx),
      isOpen: () => node.open,
      /**
       * Number the opening of an expander that is open and has no number (the first time it is seen open, whoever sees it), and forget the number of one that is closed. The page is told
       * of an opening by a toggle event a moment after `open` changes, so an expander can be open, and in the way of the one the page was told of, before it has its number: the pump
       * looks at every expander before it chooses, and numbers what it finds, so that the order of the openings is the order in which they were seen, never the order of the page.
       */
      sight() {
        if (!node.open) exp.opened = 0;
        else if (exp.opened === 0) exp.opened = opening += 1;
      },
      /** What the quiet line says (nothing: it is out of sight). */
      note(text) {
        if (state.textContent !== text) state.textContent = text;
        state.hidden = text === "";
      },
      /** A fault inside the expander: what happened, and a button (no label: none). The answer in the body stays, and so does the rest of the page. */
      showFault(text, label, action) {
        exp.fault = true;
        holdFocus(exp, () => {
          exp.note("");
          lineWords.textContent = text;
          line.hidden = false;
          button?.remove();
          button = null;
          if (label !== null) {
            button = el("button", { type: "button", class: "btn", text: label });
            button.addEventListener("click", () => action());
            line.append(button);
          }
        });
      },
      clearFault() {
        exp.fault = false;
        holdFocus(exp, hideLine);
      },
      /** Nothing of an answer in it. */
      clear() {
        exp.drawn.clear();
        exp.redraw = null;
        exp.fault = false;
        holdFocus(exp, () => {
          body.replaceChildren();
          exp.note("");
          hideLine();
        });
      },
    };
    // a visitor's click on the summary is the first sight of an opening (or of a closing): it is numbered, or forgotten, there, before the browser has changed `open`
    summary.addEventListener("click", () => {
      exp.opened = node.open ? 0 : (opening += 1);
    });
    node.addEventListener("toggle", () => {
      exp.sight();
      if (!node.open) {
        if (!exp.busy) exp.note("");
        return;
      }
      if (exp.epoch !== epoch) {
        exp.clear(); // (what it holds is of a request before a change: it is not shown, it is worked out again)
        exp.epoch = epoch;
      }
      pumpMore();
    });
    return exp;
  }

  /** A best set: its additions as lines of the Next step's words (no gain of their own: the set has one), and its gain over Equip now, with its label if the solve ran out of time. */
  function drawSet(exp, ctx, k, result) {
    const block = el(
      "section",
      { class: "set", "data-k": String(k) },
      el("h4", { text: `Best set of ${k}` }),
      el("p", { class: "note set-note", text: `The best ${k} additions made at once; the path adds one at a time, so its first ${k} steps can differ.` }),
    );
    const found = result.acquired;
    if (result.kit === null) {
      block.append(el("p", { class: "set-other", text: `${result.label.charAt(0).toUpperCase()}${result.label.slice(1)}.` })); // (the protocol's own words: "not found in time")
    } else if (found.length === 0) {
      block.append(el("p", { class: "set-other", text: "No addition gains anything." }));
    } else {
      // the copies there are for the hints: what is owned, less the copies that the set itself upgrades (they are not spares), whatever the order of its additions
      const counts = { request: ctx.request, available: new Map(ctx.request.owned), offered: new Map() };
      for (const addition of found) {
        if (addition.kind !== "upgrade") continue;
        const source = `${split(addition.ident)[0]}@${addition.sourceTier}`;
        counts.available.set(source, (counts.available.get(source) ?? 0) - 1);
      }
      const lines = found.map((addition) => el("li", {}, ...describe(counts, { ...addition, kit: result.kit }, true, true).nodes));
      block.append(el("ul", { class: "steps" }, ...lines));
      if (found.length < k) block.append(el("p", { class: "note set-other", text: `Only ${found.length} ${plural(found.length, "addition gains", "additions gain")} anything.` }));
      const label = result.status === "optimal" ? "" : ` (${result.label})`;
      block.append(el("p", { class: "set-gain", text: `Gain over Equip now: ${signed(result.gainValue)} kit value${label}` }));
    }
    holdFocus(exp, () => exp.body.append(block));
  }

  /**
   * Every slot: for each place what Equip now wears there and the best swaps, each with its change in kit value and, for an item on the list, what the visitor has of it: "you have it"
   * (and where the spare is) when a copy is spare, "get another copy" when the kit wears every copy the visitor has. The optimizer counts the copies, so every swap it gives is one that
   * can be made, by a copy the visitor has or by one that can be got; none is hidden.
   */
  function drawSlots(exp, ctx, result) {
    exp.redraw = () => drawSlots(exp, ctx, result);
    const have = new Map(ctx.owned.map((entry) => [`${entry.key}@${entry.tier}`, entry]));
    const rows = result.rows.map((place) => {
      const now =
        place.current === null ? el("span", { class: "muted", text: words.emptyName }) : el("span", { class: "owned-name", text: nameOfIdent(place.current) });
      const swaps = place.swaps.map((swap) => {
        const parts = [el("span", { class: "swap-what", text: nameOfIdent(swap.ident) }), " ", el("span", { class: "delta", text: signed(swap.deltaValue) })];
        const owned = have.get(swap.ident);
        if (owned !== undefined) {
          const elsewhere = ctx.equip.kit.filter((ident, index) => index !== place.index && ident === swap.ident).length;
          const spare = spareText(owned, elsewhere);
          parts.push(" ", spare === null ? el("span", { class: "owned-meta swap-get", text: GET_ANOTHER }) : el("span", { class: "owned-meta swap-have", text: spare }));
        }
        return el("li", {}, ...parts);
      });
      const under = swaps.length === 0 ? el("span", { class: "muted slot-none", text: NOTHING_FITS }) : el("ol", { class: "swaps" }, ...swaps);
      const cell = el("td", {}, el("div", { class: "slot-now" }, now), under);
      return el("tr", {}, el("th", { scope: "row", text: words.slotLabel(place.index) }), cell);
    });
    const table = el(
      "table",
      { id: "upgrade-slots-table", class: "runnerups" },
      el("caption", { class: "sr-only", text: "The best swaps for each slot, with the change in kit value" }),
      el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Slot" }), el("th", { scope: "col", text: "Equip now wears, and the best swaps (change in kit value)" }))),
      el("tbody", {}, ...rows),
    );
    holdFocus(exp, () => exp.body.replaceChildren(el("p", { id: "upgrade-slots-note", class: "note", text: EVALUATION }), table));
  }

  /** The Tier mode expander: the tier that the additions are worked out at. Its summary says the mode in force, and a choice restarts the answer with it, as any other change does. */
  function makeMode() {
    const modeText = () =>
      tierMode.mode === "ready4"
        ? `Ready ${words.tierLabel(READY_TIER)}`
        : tierMode.mode === "arrives"
          ? `As it arrives, drops at ${words.arrivalText(tierMode.D)}`
          : `Fixed ${words.tierLabel(tierMode.N)}`;
    const summary = el("summary", { text: `Tier mode: ${modeText()}` });
    const choice = (value, label) => {
      const input = el("input", { type: "radio", name: "upgrade-mode", id: `upgrade-mode-${value}`, value });
      return { input, node: el("span", { class: "opt" }, input, el("label", { for: `upgrade-mode-${value}`, text: label })) };
    };
    const picker = (id, label, top, shown, wording) => {
      const field = el("select", { id }, ...Array.from({ length: top + 1 }, (_, n) => el("option", { value: String(n), text: wording(n) })));
      field.value = String(shown);
      return { field, node: el("div", { class: "control" }, el("label", { for: id, text: label }), field) };
    };
    const ready = choice("ready4", `Ready ${words.tierLabel(READY_TIER)}`);
    const arrives = choice("arrives", "As it arrives");
    const fixed = choice("fixed", "Fixed");
    const drops = picker("upgrade-mode-d", "Drops arrive at", MAX_DIFFICULTY, MAX_DIFFICULTY, (n) => words.arrivalText(n));
    const tier = picker("upgrade-mode-n", "Fixed at", MAX_TIER, READY_TIER, (n) => words.tierLabel(n));
    ready.input.checked = true;
    const fieldset = el(
      "fieldset",
      { class: "mode-set" },
      el("legend", { text: "Which tier the additions are worked out at" }),
      el("div", { class: "mode-opt" }, ready.node, el("p", { class: "note", text: `Every addition is worked out at ${words.tierLabel(READY_TIER)}, as if you had brought it there. This is the default.` })),
      el("div", { class: "mode-opt" }, arrives.node, drops.node, el("p", { class: "note", text: `A drop is worked out at the tier of the instance it drops in, anything else at ${words.tierLabel(0)}.` })),
      el("div", { class: "mode-opt" }, fixed.node, tier.node, el("p", { class: "note", text: "Every addition is worked out at that tier." })),
    );
    fieldset.addEventListener("change", (event) => {
      if (event.target === drops.field) arrives.input.checked = true; // (a choice of the difficulty is a choice of the mode that uses it)
      else if (event.target === tier.field) fixed.input.checked = true;
      const chosen = fixed.input.checked ? { mode: "fixed", N: Number(tier.field.value) } : arrives.input.checked ? { mode: "arrives", D: Number(drops.field.value) } : { mode: "ready4" };
      if (chosen.mode === tierMode.mode && chosen.D === tierMode.D && chosen.N === tierMode.N) return;
      tierMode = chosen;
      summary.textContent = `Tier mode: ${modeText()}`;
      if (gear.toOwnedPairs().length > 0) schedule();
    });
    return el("details", { id: "upgrade-mode", class: "expander" }, summary, fieldset);
  }

  /** The block under the answer: best sets, Every slot, tier mode. It is out of sight until the first answer is drawn. */
  function makeMore() {
    const sets = makeExpander({
      id: "upgrade-sets",
      title: "Best 2 and 3 sets",
      headline: "Best 2 and 3 sets: sets, not a path",
      ready: "Best 2 and 3 sets are ready.",
      todo: (exp, ctx) =>
        SET_SIZES.filter((k) => !exp.drawn.has(k)).map((k) => ({
          key: k,
          working: `Working out the best ${k} additions…`,
          request: () => expanderRequest(ctx, BEST_SETS, { k }),
          draw: (result) => drawSet(exp, ctx, k, result),
        })),
    });
    const slots = makeExpander({
      id: "upgrade-slots",
      title: "Every slot",
      headline: "Every slot: Swap only this slot",
      ready: "Every slot is ready.",
      todo: (exp, ctx) =>
        exp.drawn.has("all")
          ? []
          : [
              {
                key: "all",
                working: "Working out the swaps for every slot…",
                request: () => expanderRequest(ctx, EVERY_SLOT, { kit: [...ctx.equip.kit], buffs: [...ctx.equip.buffs], limit: SWAPS_A_PLACE }),
                draw: (result) => drawSlots(exp, ctx, result),
              },
            ],
    });
    expanders.push(sets, slots);
    more = el("div", { id: "upgrade-more", class: "more", hidden: true }, sets.node, slots.node, makeMode());
    box.append(more);
  }

  /** Nothing of the expanders' answers on the page (the forms and the open or closed state of the expanders stay). */
  function clearMore() {
    for (const exp of expanders) {
      exp.clear();
      exp.epoch = epoch;
    }
  }

  /**
   * The request that follows a change is the one that was sent last, so the change was undone or only moved a copy: what the answer and the expanders have stands. The epoch goes back
   * to the one of that request, which makes what the expanders drew, and the request they have on the client, valid again; what came in the pause was not drawn, and is asked for again.
   * The request does not name where the copies are, so the list as it is now is taken, and the words that depend on it are drawn again.
   */
  function keepAnswer() {
    epoch = last.epoch;
    for (const exp of expanders) exp.epoch = epoch;
    const ctx = last.ctx;
    ctx.owned = gear.owned();
    if (ctx.equipStep !== undefined) drawEquipRows(ctx.equipStep, ctx.owned);
    for (const exp of expanders) exp.redraw?.();
    tellGear(gearOf(ctx), ctx.equip === undefined); // (the kit that stands again, or the one that is still being worked out)
    pumpMore();
  }

  /** The answer has gone: so does the block of the expanders, closed. */
  function hideMore() {
    if (more === null) return;
    more.hidden = true;
    for (const part of more.querySelectorAll("details")) part.open = false;
  }

  /** In each open expander that lacks an answer and cannot begin, say why it waits. */
  function tellWhy() {
    const ctx = currentPath();
    for (const exp of expanders) {
      if (!exp.isOpen() || exp.fault || (exp.busy && exp.stamp === epoch)) continue; // (a request that a change has made old is not being worked at: it is waited out)
      if (ctx === null || exp.jobs(ctx).length === 0) exp.note("");
      else exp.note(timer !== null || !ctx.over ? WAITING : ctx.equip === undefined ? BLOCKED : ctx.equip === null ? NO_KIT : QUEUED);
    }
  }

  /** Ask again for what a fault in an expander left unanswered. */
  function retry(exp) {
    exp.clearFault();
    pumpMore();
  }

  /**
   * Give the open expanders' requests to the client, one at a time, the expander that was opened first before the others, once the path of the answer has ended and Equip now is there. Each request
   * waits for the one the client has (the path, or another request of an expander: `inFlight`), and is given only if nothing has changed meanwhile and the expander is still open.
   * While a change waits for its pause nothing is begun: the path that follows it comes first. Called when an expander is opened, when the path ends, and when a change was
   * undone; the loop that is running looks again when it has finished its request.
   */
  function pumpMore() {
    tellWhy();
    if (pumping || timer !== null) return;
    pumping = true;
    (async () => {
      try {
        for (;;) {
          const ctx = currentPath();
          if (ctx === null || !ctx.over || !ctx.equip || timer !== null) return;
          for (const one of expanders) one.sight(); // (an expander that is open and not yet numbered is numbered now, before the choice)
          const waiting = expanders.filter((one) => one.isOpen() && !one.fault && one.jobs(ctx).length > 0);
          if (waiting.length === 0) return;
          const exp = waiting.reduce((first, one) => (one.opened < first.opened ? one : first)); // (the first opened; the one of the page when it comes to a tie)
          await work(exp, exp.jobs(ctx)[0], ctx);
        }
      } finally {
        pumping = false;
        tellWhy();
      }
    })();
  }

  /**
   * One request of an expander. It never throws: a fault is told inside the expander, and an answer that a change has made old is not drawn. A request that comes back cancelled when this
   * section did not take it back (another part of the page cancelled it) is asked for again, once.
   */
  async function work(exp, job, ctx) {
    const stamp = epoch;
    let controller = null;
    exp.busy = true;
    exp.stamp = stamp;
    exp.note(job.working);
    try {
      const engine = await getClient();
      if (inFlight !== null) await inFlight; // (the path, or the request of an expander before it, is over first)
      if (stamp !== epoch || !exp.isOpen()) return;
      controller = new AbortController();
      const ask = { controller, sent: false };
      const asking = engine.runScenario(job.request(), { signal: controller.signal, onSent: () => (ask.sent = true) });
      onClient = ask;
      inFlight = asking
        .then(
          () => {},
          () => {},
        )
        .then(() => {
          if (onClient === ask) onClient = null;
        });
      const result = await asking;
      if (stamp !== epoch) return;
      job.draw(result);
      exp.drawn.add(job.key);
      if (exp.jobs(ctx).length === 0) {
        exp.note("");
        if (exp.isOpen()) say(exp.ready);
      }
    } catch (error) {
      if (stamp !== epoch) return;
      if (!ctx.askedAgain.has(job.key) && cancelledByOthers(error, controller)) {
        ctx.askedAgain.add(job.key); // (the job is still to be done: the loop of pumpMore gives it to the client again)
        return;
      }
      const { text, label, action, released } = explain(error, () => retry(exp));
      exp.showFault(text, label, action);
      say(`${exp.title}: ${text}`);
      if (released && typeof onUpdated === "function") onUpdated();
    } finally {
      exp.busy = false;
      if (!exp.isOpen()) exp.note("");
    }
  }

  // ---- the engine -----------------------------------------------------------------------------------------------------------------------------------
  function getClient() {
    if (clientPromise === null) {
      clientPromise = (async () => {
        const module = await loadEngine(sameOriginUrl(clientPath, win.location.href).href);
        client = module.getEngineClient({ window: win, document: doc, mount: slot });
        return client;
      })();
      clientPromise.catch(() => {
        clientPromise = null; // (the next change tries again; a browser may keep a failed module until the page is reloaded, which the line says)
      });
    }
    return clientPromise;
  }

  /** The request for the gear in the list and the view the page shows, with the weights of the view when it has any (the role's own are none). */
  function requestFor(pairs) {
    const shown = view();
    return {
      v: PROTOCOL_VERSION,
      kind: "scenario",
      trio,
      level,
      mode: FARM_PATH,
      scenario: { race: shown.race, role: shown.role, buffs: shown.buffs, evidence: shown.evidence, setup: shown.setup },
      owned: pairs,
      tierMode: { ...tierMode },
      steps: LIMITS.maxPathSteps,
      ...(shown.weights ? { weights: copyOf(shown.weights) } : {}),
      budgetMs: BUDGET_MS,
    };
  }

  /** Ask the visitor again for the optimizer; on a yes, `after` asks again for what was wanted. */
  async function ask(after = send) {
    let yes = false;
    try {
      yes = (await client.askConsent()) === true;
    } catch {
      yes = false;
    }
    if (yes) after();
  }

  /**
   * Did another part of the page cancel this request? It came back cancelled though the section did not take it back (its signal did not fire), the visitor's Cancel on the panel did not
   * end it, and the optimizer is agreed to: the answer is asked for again. (With the question unanswered or answered no, a cancelled request is the question's answer.)
   */
  function cancelledByOthers(error, controller) {
    return controller !== null && error?.code === "cancelled" && error.byVisitor !== true && !controller.signal.aborted && client?.consentState?.() === "granted";
  }

  /** What a fault is to the visitor: the sentence, the label of the button and what it does (no label for no button), and whether the site was released again. `again` is what Try again does. */
  function explain(error, again) {
    const code = typeof error?.code === "string" ? error.code : "";
    const detail = typeof error?.message === "string" ? error.message : "";
    let text;
    let label = "Try again";
    let action = again;
    let released = false;
    if (code === "engine-load" && client?.stats().updated === true) {
      [text, label, action, released] = [SECTION_UPDATED, "Reload", () => reload(), true];
    } else if (code === "declined" || (code === "cancelled" && client?.consentState?.() !== "granted")) {
      // (a request that is cancelled once the optimizer was agreed to, from the Cancel of its panel after it had started, is a request that was cancelled, and not an optimizer that was not loaded)
      [text, label, action] = [NOT_LOADED, "Load the optimizer", () => ask(again)];
    } else if (code === "bad-request") {
      text = `The optimizer would not take your gear list: ${detail.endsWith(".") ? detail.slice(0, -1) : detail}.`;
    } else if (code === "protocol") {
      text = WORKER_DROPPED; // (the detail is the protocol's, written for whoever reads the code)
    } else {
      text = `Couldn't work out your answer. ${detail === "" ? "Something went wrong." : detail}`;
      if (code === "unsupported") label = null;
    }
    return { text, label, action, released };
  }

  function onFault(ctx, error) {
    if (ctx.id !== run) return;
    if (!ctx.resent && cancelledByOthers(error, ctx.controller)) {
      send(true, true); // (once: a request that is cancelled again is a fault)
      return;
    }
    const { text, label, action, released } = explain(error, send);
    failed(ctx, text, label, action);
    if (released && typeof onUpdated === "function") onUpdated();
  }

  /** The request cannot go on: the steps shown stay, with what happened and a button. */
  function failed(ctx, text, label, action) {
    ctx.over = true;
    if (last !== null && last.ctx === ctx) last.failed = true;
    keepFocus(() => {
      clearStop();
      setProgress("");
      if (ctx.drawn) {
        end.textContent = REST;
        end.hidden = false;
        then.hidden = false;
      }
      setLine(text, label, action);
    });
    tell(ctx, ctx.drawn ? `${text} ${REST}` : text);
    pumpMore();
  }

  function finish(ctx, result) {
    if (ctx.id !== run) return;
    ctx.over = true;
    const steps = Number.isInteger(result?.steps) ? result.steps : 0;
    const why = result?.stopped === "limit" ? `These are the first ${steps} steps.` : (ENDINGS.get(result?.stopped) ?? "");
    keepFocus(() => {
      clearStop();
      setProgress("");
      end.textContent = why;
      end.hidden = why === "";
      if (why !== "") then.hidden = false;
    });
    tell(ctx, steps === 0 && why !== "" ? why : `${steps} ${plural(steps, "step", "steps")}.`);
    pumpMore();
  }

  function onStep(ctx, step) {
    if (ctx.id !== run || ctx.over || step === null || typeof step !== "object") return; // (nothing comes after the result)
    showRunning(ctx);
    if (step.index === 0) drawEquip(ctx, step);
    else drawStep(ctx, step);
  }

  function onProgress(ctx, report) {
    if (ctx.id !== run || ctx.over || report === null || typeof report !== "object") return;
    showRunning(ctx); // (a report comes only once the visitor has agreed to the optimizer: the loading of it is the first)
    if (report.stage === "loading") setProgress("Loading the data…");
    else if (report.stage === "equip-now") setProgress("Working out what to equip now…");
    else if (report.stage === "step" && Number.isInteger(report.step)) setProgress(`Working out step ${report.step}…`);
  }

  /**
   * Stop and the working line: the path is being worked out. They are not there while the client's question waits for the visitor's answer (nothing is worked out then, and a Stop
   * there would stop nothing), nor before the client has said whether it is up (the first request); they come when the visitor has agreed, with the first report of the client
   * or step, or at once when the visitor had agreed before.
   */
  function showRunning(ctx) {
    if (ctx.running || ctx.over || ctx.id !== run) return;
    ctx.running = true;
    const button = el("button", { type: "button", id: "upgrade-stop", class: "btn-quiet", text: "Stop" });
    button.addEventListener("click", () => {
      if (button.getAttribute("aria-disabled") === "true") return; // (the first press is taken: the path ends when the step being worked out is done)
      button.setAttribute("aria-disabled", "true"); // (not disabled: a disabled button loses the focus)
      ctx.stopRequested = true;
      client?.stop();
    });
    stopButton = button;
    bar.append(button);
    setProgress(WORKING);
  }

  /**
   * End what this section has on the client, which is not wanted any more, and nothing else: the client is the page's, and the sliders have requests on it too, so this is never
   * cancel(), which ends them all. A path that the worker has not got (it waits for the visitor's answer to the question, so that nothing is agreed to yet and a yes loads nothing for an
   * answer that is thrown away, or for the request that is on the worker) is taken back, alone. A path that the worker has is told to stop, before the next step it begins: the worker
   * that is there is kept, and so is the optimizer that was agreed to. The request of an expander is not a path, and a stop does not reach it: it is taken back, which stops its worker
   * at once if it has the request (a solve cannot be interrupted), and the next request starts a worker again from the compiled module the client kept, with no download. Without that
   * the new path would wait for a solve whose answer is thrown away, up to the minute it is given.
   */
  function endPath(engine) {
    if (pathAsk !== null && !pathAsk.sent) pathAsk.controller.abort();
    else if (engine.consentState?.() !== "unknown") engine.stop();
    if (onClient !== null) onClient.controller.abort();
  }

  /**
   * Send the request for the gear in the list and the view the page shows. `forced` is false for the request that follows a change after its pause: when it is the same as the one
   * sent last (a view that came back, an item that was added and taken out), what is being worked out, or was, is right, and nothing is stopped or sent, unless that one failed.
   * `resent` is for the request that asks again for one that another part of the page cancelled: if that is cancelled too, it is a fault.
   */
  async function send(forced = true, resent = false) {
    clearTimeout(timer);
    timer = null;
    const pairs = gear.toOwnedPairs();
    if (pairs.length === 0) {
      halt();
      return;
    }
    const request = requestFor(pairs);
    const key = JSON.stringify(request);
    if (!forced && last !== null && last.key === key && !last.failed) {
      keepAnswer();
      return;
    }
    const id = (run += 1);
    epoch += 1;
    // (`equip` is what the expanders work from, Equip now's kit and optional buffs: not there until Equip now is drawn, and null when no kit was found)
    const ctx = {
      id,
      request,
      owned: gear.owned(),
      available: new Map(pairs),
      offered: new Map(),
      drawn: false,
      equipSaid: null,
      equip: undefined,
      stopRequested: false,
      running: false,
      over: false,
      controller: new AbortController(), // (takes the request back, alone)
      sent: false, // (the worker has the request)
      resent,
      askedAgain: new Set(), // the requests of the expanders for this path that were asked for again after another part of the page cancelled them
    };
    last = { key, ctx, failed: false, epoch };
    sentKey = viewKey();
    keepFocus(() => {
      reset();
      tellGear(null, true); // (the kit of the old answer is gone, and the new one is being worked out)
      // the client is there already (a later request) and the visitor has agreed: Stop takes the place, and the focus, of the button of the line of a fault that went with the old answer
      if (client !== null && client.consentState?.() !== "unknown") showRunning(ctx);
    });
    tellWhy(); // (the expanders that are open wait for this answer)
    let engine;
    try {
      engine = await getClient();
    } catch {
      if (ctx.id === run) failed(ctx, CODE_NOT_LOADED, "Reload", () => reload());
      return;
    }
    if (ctx.id !== run) return; // (a newer request was made, or the list was emptied, while the code of the optimizer came)
    if (engine.consentState?.() !== "unknown") showRunning(ctx); // (the first request: the client says now whether the question is up)
    try {
      endPath(engine);
      // The client queues what it is given, and works out every request in its turn, a superseded one too (it loads and solves Equip now for it). So the client is given a request only
      // when the one before it is over, and only if no newer request was made meanwhile: of the requests made while a long step ends, one waits, the last.
      if (inFlight !== null) {
        await inFlight;
        if (ctx.id !== run) return;
      }
      pathAsk = ctx;
      inFlight = engine
        .runScenario(request, { onStep: (step) => onStep(ctx, step), onProgress: (report) => onProgress(ctx, report), signal: ctx.controller.signal, onSent: () => (ctx.sent = true) })
        .then(
          (result) => finish(ctx, result),
          (error) => onFault(ctx, error),
        )
        .catch(() => {})
        .then(() => {
          if (pathAsk === ctx) pathAsk = null;
        });
      if (ctx.stopRequested) engine.stop(); // (Stop was pressed before the request could be sent)
    } catch (error) {
      onFault(ctx, error); // (a client that cannot even take the request)
    }
  }

  /** The list is empty or was cleared: the path is ended and the results go. */
  function halt() {
    clearTimeout(timer);
    timer = null;
    run += 1;
    epoch += 1;
    sentKey = null;
    last = null;
    if (client !== null) endPath(client);
    keepFocus(() => {
      reset();
      hideMore();
    });
    tellGear(null, false); // (nothing is coming: the list is empty)
  }

  /**
   * A change was made: whatever the expanders computed or are computing is old from now on (an answer that comes in the pause is not drawn), and the request that follows the pause
   * deals with it: a new path clears it, and the request that is the same as the last one (the change was undone) gives it back.
   */
  function schedule() {
    clearTimeout(timer);
    epoch += 1;
    tellGear(null, true); // (the kit that is shown was worked out for what has changed: the panel drops its order now, and waits for the new answer)
    timer = setTimeout(() => send(false), pauseMs);
  }

  // What listens is set up last, and so that nothing is left listening when a part of it cannot be: the expanders' block (made here, with the rest that can fail, so that none of it is left
  // in the page when a part cannot be made), the page's view (it is what can fail), then the list.
  let unwatch = null;
  try {
    makeMore();
    unwatch = onView(() => {
      if (gear.toOwnedPairs().length > 0 && viewKey() !== sentKey) schedule();
    });
    gear.onChange(() => {
      if (gear.toOwnedPairs().length === 0) halt();
      else schedule();
    });
  } catch (error) {
    if (typeof unwatch === "function") unwatch();
    box.replaceChildren(); // (no half of an answer in its place)
    throw error;
  }

  return { send, halt };
}
