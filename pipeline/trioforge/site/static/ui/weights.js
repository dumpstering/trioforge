// The sliders of the Weights assumption of a trio page, and the answers for the settings that no shard answers: the code the page loads the first time the Weights assumption is
// opened, a buff choice the shards lack (the full raid, the Enchanter in the group) is used, or the address asks for one of them or for sliders.
//
//   initWeights(app, words) -> {sync(positions), text(positions), settle(view, kind), release()}
//
// `app` is the page script's own object (trio.js), and this code is the part of the page that only the sliders and the answers for the settings that no shard answers use, so it works on that
// object: what the page is (`doc`, `win`, `root` (the main element of the page), `groups` (the weight groups of the trio's bundle, in its order), `own` (every slider at x1), `displayed` (the
// view shown, and its sliders), `fetchJson`, `release` (the data release the page was built for, or null), `loadEngine(url)` (imports the optimizer's client; the default is the browser's own
// import)), what it knows of words and requests (`weightsTable(positions)`: the sliders as a request carries them, or null for the role's own; `buffsPhrase(code)`; `nearest(buffs)`: the
// assumptions of the precomputed answer nearest to a buff choice), and what it does for this code (`track(promise)`, `desired(setup)` and `apply(desired, options)`: the view the controls ask
// for, and the change of the view; `drawSolved(answer)`: put the optimizer's kit in the rows of Wear this and say it, which says whether it did, since it does not while the page loads another
// view; `announce(text)`, `setStatus(...)`, `dataUpdated()`, `reload()`). `words` is `fmtInt` and `displayInt`: this file is not allowed to import format.js, which the page script imports, or the
// build would load a chunk with the page. `settle(view, kind)` is given the view of the page (the page's `resolve`) and the switch that was changed.
//
// The sliders. One segmented control for each weight group of the bundle, a fieldset with a legend, the words for what the group weighs, and the three positions x0.5, x1 and x2
// (a position is a character of the address's `w`: h, 1 or 2). They are drawn once, when this code starts, and only their state changes after that (a control that is drawn again loses
// the focus). A change is the page's to apply, as any other switch is; `sync(positions)` puts the controls in the state the page shows. `text(positions)` says the sliders in words,
// "role's own" or the groups that are not at x1, and the lines of the page that say what is assumed use it.
//
// The answer. `settle(view, kind)` is told, after every change of the view, what the page shows (`view`: the page's own, from which this code takes the race, role, tier and setup shown, the
// evidence, the buff set, the sliders and whether a shard answers them, `exact`), and `kind` is the switch the change was made with. A view that a shard answers needs nothing: whatever is going on is forgotten. Any other is worked
// out by the optimizer's client (engine/client.js, the page's one client, loaded from the address the manifest names and asked a question once), as a best-kit request for the view, a pause
// (PAUSE_MS) after the last change, with `replaceWaiting`: only the latest request is waited for, and a request is never sent for each step of a keyboard going over the positions. While the
// optimizer works, the answer area says so, with Stop; while the visitor's answer to the question is awaited (the question may have been asked for the Upgrade section, far from here) it says
// that, with a button that moves the focus to the question (and, once the question is answered, that it works: the line looks at the question while it stands). Its answer replaces the kit shown, headed "Solved for your settings", with its F and a button back to
// the precomputed answer. A fault stays in the answer area with Try again; the kit shown then is the shard's, and the line says that it is not for the visitor's settings. The answer of a request
// for settings that are no longer shown (its `settings` are not the latest) is never drawn, said or complained of; nor is one that comes while the page loads another view (`draw` says no):
// it waits, and `release()` (the page stays on its view, the other could not be loaded) draws it after all. The names, the sources and the seals of the kit's items are read from the item
// table of the site, which the page fetches by the path, size and SHA-256 the manifest lists, once, when the first answer is there (the worker fetched the same file, and the browser has it).
//
// The client is the page's, and the Upgrade section has requests on it too, so a request here is never ended with cancel(), which ends them all: each request has a signal, and Stop, a change
// of the view and the page's going back to a precomputed answer take back that request alone. A request that has not reached the worker is taken back whenever it is not wanted; one the worker
// has is taken back by Stop only (a worker costs a start), and otherwise left to end, its answer dropped. A request that comes back cancelled when this code did not take it back (another
// part of the page cancelled it) is asked for again, once, unless the visitor cancelled it with the Cancel button of the loading panel.
//
// Everything is text (textContent, never markup). The answer is said once through the page's #announce (`drawSolved`, for an answer; `announce`, for a fault): there is no live region here.

import { DATA_FILE, EngineFault, fetchBytes, sameOriginUrl, sha256Hex } from "../engine/download.js";
import { MANIFEST_PATH, fetchTextWithin, parseManifest } from "../engine/manifest.js";
import { BEST_KIT, LIMITS, PROTOCOL_VERSION, STARTUP_COMPILE_MS, STARTUP_STALL_MS } from "../engine/protocol.js";
import { MAX_DIFFICULTY, arrivalTier, wornHaste } from "../engine/tiers.js";

/** The list of the pictures of the items of the item table (site/data.py: ICONS_NAME), at a fixed address like the shared file of the effects. */
const ICONS_PATH = "/data/item-icons.json";
/** The pause after the last change before a request is sent, and the time a solve may take (the phone gate's). */
const PAUSE_MS = 300;
const BUDGET_MS = 60_000;
/** How often the line that says that the question is awaited looks whether it has been answered (the client has no event for that). */
const LOOK_MS = 250;
const OWN = "role's own";
const WORKING = "Working out the kit for these settings…";
const WAITING = "The optimizer is waiting for your answer to the question below.";
const HEADING = "Solved for your settings";
const BACK = "Back to the precomputed answer";
const COULD_NOT = "Couldn't work out the kit for these settings.";
const UPDATED = "Data updated, reload the page to see this answer.";
/** The three positions of a slider: the character of the address, the words, and the number that multiplies the weights of the group. */
const POSITIONS = [
  ["h", "x0.5", 0.5],
  ["1", "x1", 1],
  ["2", "x2", 2],
];
/** The words for each weight group of the bundle: its name as a slider is called, and what it weighs. A group these words do not know is called by the name the bundle gives it. */
const GROUP_WORDS = new Map([
  ["AC", ["Armor class", "armor class (AC)"]],
  ["MANA", ["Mana", "maximum mana"]],
  ["ATK+HASTE", ["Attack and haste", "attack, haste and weapon damage"]],
  ["SV", ["Resists", "fire, cold, magic, poison and disease resists"]],
  ["regen", ["Regeneration", "hit point, mana and endurance regeneration"]],
]);

/** The manifest or the item list could not be had: the message is for the visitor. */
class Failure extends Error {}
/** The same, for the item list: its message is the whole sentence the answer area says. */
class ItemFailure extends Failure {}
/** The site was released again since the page was made. */
class Updated extends Error {}

/** Where an item comes from, as the Upgrade section words it: where it drops, the quest, the vendor, a recipe, foraging. */
function sourceText(record) {
  const source = record.source;
  if (source === undefined || source === null || typeof source !== "object") return "";
  const more = source.more ?? {};
  const list = (kind, lead) => (Array.isArray(source[kind]) ? lead + source[kind].join(", ") + (more[kind] ? ` and ${more[kind]} more` : "") : "");
  return list("drops", "") || list("quests", "quest: ") || list("sold", "vendor: ") || (source.crafted ? "crafted" : "") || list("forage", "Foraged in ");
}

export function initWeights(app, words) {
  const { doc, win, root, groups, own } = app;
  const fetchImpl = app.fetchJson;
  const importModule = app.loadEngine ?? ((url) => import(url));
  const section = root.querySelector("#upgrade"); // (what a request names: the trio and the level of the page)
  const trio = section?.dataset.trio ?? "";
  const level = Number(section?.dataset.level);
  const el = (tag, attributes = {}, ...children) => {
    const node = doc.createElement(tag);
    for (const [name, value] of Object.entries(attributes)) {
      if (name === "text") node.textContent = value;
      else node.setAttribute(name, value === true ? "" : value);
    }
    node.append(...children);
    return node;
  };
  const nameOf = (group) => GROUP_WORDS.get(group)?.[0] ?? group;

  // ---- the sliders -------------------------------------------------------------------------------------------------------------------
  const inputs = groups.map(() => new Map());
  const host = root.querySelector("#assume-weights fieldset");
  const reset = el("button", { type: "button", id: "weights-reset", class: "btn weights-reset", text: "Reset weights" });
  if (host) {
    const box = el("div", { class: "weights" });
    const sets = el("div", { class: "weights-sets" });
    groups.forEach((group, index) => {
      const hint = GROUP_WORDS.get(group)?.[1];
      const set = el("fieldset", { class: "control seg", "data-group": group }, el("legend", { text: nameOf(group) }));
      if (hint !== undefined) {
        set.setAttribute("aria-describedby", `w-${index}-hint`);
        set.append(el("p", { class: "hint", id: `w-${index}-hint`, text: hint }));
      }
      const items = el("div", { class: "seg-items" });
      for (const [character, label] of POSITIONS) {
        const input = el("input", { type: "radio", name: `w-${index}`, id: `w-${index}-${character}`, value: character });
        inputs[index].set(character, input);
        items.append(el("span", { class: "seg-item" }, input, el("label", { for: input.id, text: label })));
      }
      set.append(items);
      sets.append(set);
    });
    box.append(sets, reset);
    host.append(box);
    box.addEventListener("change", (event) => {
      if (event.target?.type === "radio") change(read());
    });
    reset.addEventListener("click", () => {
      if (read() !== own) change(own);
    });
  }

  /** The positions the controls show. */
  function read() {
    return groups.map((_, index) => [...inputs[index]].find(([, input]) => input.checked)?.[0] ?? "1").join("");
  }

  /** The visitor moved the sliders (or put them all back): the page applies the new view, as it does for any other switch. */
  function change(positions) {
    app.focusAfterRetry = false;
    app.track(app.apply({ ...app.desired(app.wantedSetup), weights: positions }, { url: true, announce: "weights" }));
  }

  /** The button of a solved answer: the settings that have a precomputed answer, the nearest to the visitor's (every slider at x1; the common group buffs for the raid and for the Enchanter's). */
  function back() {
    const desired = { ...app.desired(app.wantedSetup), weights: own };
    if (desired.buffs !== "own") desired.buffs = "group";
    app.track(app.apply(desired, { url: true, announce: "back" }));
    wearing?.focus(); // (the button goes with the answer)
  }

  function sync(positions) {
    groups.forEach((_, index) => {
      const input = inputs[index].get(positions[index]);
      if (input !== undefined) input.checked = true;
    });
  }

  function text(positions) {
    const named = [];
    groups.forEach((group, index) => {
      const position = POSITIONS.find(([character]) => character === positions[index]);
      if (position !== undefined && position[2] !== 1) named.push(`${nameOf(group).toLowerCase()} ${position[1]}`);
    });
    return named.length === 0 ? OWN : named.join(", ");
  }

  // ---- the answer area -------------------------------------------------------------------------------------------------------------------
  const wearing = root.querySelector("#wear-h");
  const slot = el("div", { class: "engine-slot" }); // the client's question and its progress go here
  const heading = el("h3", { id: "solve-h", hidden: true });
  const line = el("p", { class: "solve-text" });
  const button = el("button", { type: "button", class: "btn", hidden: true });
  const block = el("div", { id: "solve", class: "status solve", hidden: true }, heading, line, button);
  wearing?.after(block, slot); // (the question, which the client puts in the slot, comes after the line that points to it)
  let act = null;
  button.addEventListener("click", () => act?.());

  /** The button goes; a button that had the focus hands it to the heading of the answer (a hidden button cannot keep it). */
  function hideButton() {
    const held = doc.activeElement === button;
    button.hidden = true;
    act = null;
    if (held) wearing?.focus();
  }

  /** The answer area says something, with a button if it has a label for one. The button is the same element in every state, so that the focus on it stays through them. */
  function say(message, { title = false, label = null, action = null } = {}) {
    heading.hidden = !title;
    heading.textContent = title ? HEADING : "";
    line.textContent = message;
    if (label === null) hideButton();
    else {
      act = action;
      button.textContent = label;
      button.hidden = false;
    }
    block.hidden = false;
  }

  /** Nothing in the answer area. */
  function clear() {
    stopLooking();
    hideButton();
    block.hidden = true;
    heading.hidden = true;
    heading.textContent = "";
    line.textContent = "";
    root.classList.remove("solving");
  }

  // ---- what is wanted --------------------------------------------------------------------------------------------------------------------
  let wanted = null; // {key, settings, kind, stopped, attempt, ask, resent, parked}: the latest settings that no shard answers, while there are any
  let timer = null;
  let looking = null; // the timer that looks at the answer to the question while the line says that it is awaited
  let client = null;
  let clientPromise = null;
  let manifestPromise = null;
  let recordsPromise = null;

  const keyOf = (settings) => [settings.race, settings.role, settings.tier, settings.setup, settings.ev, settings.buffs, settings.weights].join("|");
  const nearest = (settings) => app.nearest(settings.buffs);
  /** What the chunk works the answer out for, from the view of the page: the view shown, whether a shard answers it, and the sliders. */
  const settingsOf = (view) => {
    const s = view.scenario;
    return { race: s.race, role: s.role, tier: s.tier, setup: s.setup, ev: view.state.ev, buffs: view.state.buffs, weights: view.state.weights, exact: view.exact };
  };

  function settle(view, kind) {
    clearTimeout(timer);
    timer = null;
    const before = wanted;
    const settings = settingsOf(view);
    if (settings.exact) {
      wanted = null;
      withdrawUnsent(before);
      clear();
      return;
    }
    const one = { key: keyOf(settings), settings, kind, stopped: false, attempt: 0, ask: null, resent: false, parked: null };
    wanted = one;
    withdrawUnsent(before);
    root.classList.add("solving");
    say(WORKING, { label: "Stop", action: () => stop(one) });
    timer = setTimeout(() => {
      timer = null;
      work(one);
    }, PAUSE_MS);
  }

  /** The request of settings nobody wants any more, if it has not reached the worker: it is taken back alone, at no cost. One the worker has is left to end (the worker costs a start). */
  function withdrawUnsent(one) {
    if (one !== null && one.ask !== null && !one.ask.sent) one.ask.controller.abort();
  }

  // ---- the data ----------------------------------------------------------------------------------------------------------------------------
  function readManifest() {
    manifestPromise ??= (async () => {
      const what = "The list of the site's files";
      const url = sameOriginUrl(MANIFEST_PATH, win.location.href);
      const answer = await fetchTextWithin(fetchImpl, url.href, { credentials: "same-origin", cache: "no-cache" }, STARTUP_STALL_MS, LIMITS.maxManifestBytes);
      if (answer.state === "timeout") throw new Failure(`${what} did not arrive in time.`);
      if (answer.state === "status") throw new Failure(`${what} could not be loaded (${answer.status}).`);
      if (answer.state === "toolarge") throw new Failure(`${what} is too large.`);
      if (answer.state !== "ok" || typeof answer.text !== "string") throw new Failure(`${what} could not be loaded.`);
      let listed;
      try {
        listed = parseManifest(JSON.parse(answer.text));
      } catch {
        throw new Failure(`${what} is not what was expected.`);
      }
      if (app.release !== null && app.release !== undefined && listed.dataRelease !== app.release) throw new Updated();
      return listed;
    })();
    manifestPromise.catch(() => {
      manifestPromise = null; // (the next attempt reads it again: after a failure the site may have been released again)
    });
    return manifestPromise;
  }

  /** The optimizer's client: the one the page shares, loaded from the address the manifest names. */
  function getClient() {
    clientPromise ??= (async () => {
      const listed = await readManifest();
      const module = await importModule(sameOriginUrl(listed.client.path, win.location.href).href);
      client = module.getEngineClient({ window: win, document: doc, mount: slot });
      return client;
    })();
    clientPromise.catch(() => {
      clientPromise = null; // (a browser may keep a failed module fetch until the page is reloaded; a browser that does not has it at the next attempt)
    });
    return clientPromise;
  }

  /**
   * The pictures of the items of the table (`{items, places}`: a name or null for each item, in the order of the table, and for each place), from the list of the site, or null: the list is for the
   * table whose SHA-256 it says and the release of the page, and a list that is not, that could not be had or that is not what the generator writes costs the items' own pictures and nothing else (an
   * item of an answer is then known by none of its own: a worn place still shows the place's picture, and a held place the pouch).
   */
  async function pictures(digest, count) {
    try {
      const list = await app.loadJson(ICONS_PATH);
      if (list === null || typeof list !== "object" || list.items !== digest) return null;
      if (app.release !== null && app.release !== undefined && list.release !== app.release) return null;
      return app.readIcons(list, count) ?? null;
    } catch {
      return null;
    }
  }

  /** The item table of the site, by the path, size and SHA-256 the manifest lists: a Map from the key of an item to its record. */
  function getRecords() {
    recordsPromise ??= (async () => {
      const listed = await readManifest();
      const file = listed.items;
      const sorry = (message) => new ItemFailure(`Couldn't load the item list. ${message}`);
      let bytes;
      try {
        bytes = await fetchBytes(sameOriginUrl(file.path, win.location.href), file.bytes, fetchImpl, () => {}, STARTUP_STALL_MS, STARTUP_COMPILE_MS, DATA_FILE);
      } catch (error) {
        throw sorry(error instanceof EngineFault ? error.message : "It could not be loaded.");
      }
      let digest;
      try {
        digest = await sha256Hex(bytes);
      } catch (error) {
        throw sorry(error instanceof EngineFault ? error.message : "This browser cannot check it, so it will not use it.");
      }
      if (digest !== file.sha256) throw sorry("It is not the one the site lists (its checksum differs).");
      let table;
      try {
        table = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
      } catch {
        throw sorry("It is not what the site writes.");
      }
      if (table === null || typeof table !== "object" || !Array.isArray(table.items) || table.data_release !== listed.dataRelease) {
        throw sorry("It is not of the release the site lists.");
      }
      const icons = await pictures(file.sha256, table.items.length);
      // only what a row of Wear this shows is kept of a record (the table is some two megabytes, and the rest of it is not needed once the rows are drawn)
      const records = new Map();
      let at = -1;
      for (const record of table.items) {
        at += 1;
        if (record === null || typeof record !== "object") continue;
        records.set(typeof record.key === "string" ? record.key : `w${record.id}`, {
          icon: icons === null ? null : icons.items[at], // (the picture of what the item is, from the list of the site: the same as its shard's and its page's)
          name: record.name,
          tier_rule: record.tier_rule,
          evidence: record.evidence,
          deity: record.deity,
          source: record.source,
          haste: record.stats?.HASTE, // (the worn haste at +0, for the chip of a row: an item of an answer is in no shard that says it)
        });
      }
      return records;
    })();
    recordsPromise.catch(() => {
      recordsPromise = null;
    });
    return recordsPromise;
  }

  /** An item of the kit in the shape the page draws a shard's items in (shard.js), from its record in the item table; `haste` is its worn haste at the tier of the answer (0 for none). */
  function itemOf(records, ident, tier) {
    const key = ident.slice(0, ident.lastIndexOf("@"));
    const record = records.get(key);
    if (record === undefined) return { key, name: `Unknown item (${key})`, rule: "fixed0", arrival: 0, source: "", evidence: "unknown", deity: [], haste: 0 };
    const base = Number.isSafeInteger(record.haste) ? record.haste : 0;
    const step = Number.isSafeInteger(app.hastePerTier) ? app.hastePerTier : 0;
    const rule = typeof record.tier_rule === "string" ? record.tier_rule : "drop";
    const deity = Array.isArray(record.deity) ? record.deity.filter((name) => typeof name === "string") : typeof record.deity === "string" ? [record.deity] : [];
    return {
      key,
      name: typeof record.name === "string" ? record.name : key,
      rule,
      arrival: rule === "spell" ? null : arrivalTier(rule, MAX_DIFFICULTY), // (a summoned item is made at its spell rank, and has no tier it arrives at)
      source: sourceText(record),
      evidence: typeof record.evidence?.level === "string" ? record.evidence.level : "unknown",
      deity,
      haste: wornHaste(base, tier, step),
      icon: typeof record.icon === "string" ? record.icon : null,
    };
  }

  /** The request for the best kit of the view shown, with the sliders that are not at x1 (the role's own weights when none is). */
  function requestFor(settings) {
    const request = {
      v: PROTOCOL_VERSION,
      kind: "scenario",
      trio,
      level,
      mode: BEST_KIT,
      scenario: { race: settings.race, role: settings.role, buffs: settings.buffs, evidence: settings.ev, setup: settings.setup },
      tier: settings.tier,
      budgetMs: BUDGET_MS,
    };
    const weights = app.weightsTable(settings.weights);
    if (weights !== null) request.weights = weights;
    return request;
  }

  // ---- the work --------------------------------------------------------------------------------------------------------------------------
  /**
   * One attempt at the answer for settings. Each attempt has a number, and after every wait it goes on only if it is the latest attempt, the settings are still wanted and Stop was not
   * pressed: a Stop (or a Try again after it) that came while the code of the optimizer or the item list was on its way is not undone when they arrive.
   */
  async function work(one) {
    const attempt = (one.attempt += 1);
    const ask = { controller: new AbortController(), sent: false }; // (this request's: taken back alone, and whether the worker has it)
    one.ask = ask;
    one.parked = null;
    const live = () => wanted === one && one.attempt === attempt && !one.stopped;
    try {
      const engine = await track(getClient());
      if (!live()) return;
      // while the visitor's answer to the question is awaited nothing is being worked out: no Stop for a request that has not begun, and a line that says what is awaited
      if (engine.consentState?.() === "unknown") waiting(one, attempt);
      else say(WORKING, { label: "Stop", action: () => stop(one) });
      const result = await engine.runScenario(requestFor(one.settings), {
        replaceWaiting: true,
        signal: ask.controller.signal,
        onSent: () => {
          ask.sent = true;
        },
        onProgress: () => {
          if (live()) say(WORKING, { label: "Stop", action: () => stop(one) });
        },
      });
      if (!live()) return;
      if (result.kit === null) throw new Failure(`The optimizer found no kit (${result.label ?? "not found in time"}).`);
      const records = await track(getRecords());
      if (!live()) return;
      show(one, result, records);
    } catch (error) {
      if (!live()) return;
      if (!one.resent && cancelledByOthers(error, ask.controller)) {
        one.resent = true; // (once: a request that is cancelled again is a fault)
        work(one);
        return;
      }
      fault(one, error);
    }
  }

  /** Did another part of the page cancel the request? It came back cancelled though it was not taken back here, the optimizer is agreed to, and the visitor's own Cancel on the panel did not end it. */
  function cancelledByOthers(error, controller) {
    return error?.code === "cancelled" && error.byVisitor !== true && !controller.signal.aborted && client?.consentState?.() === "granted";
  }

  /** The answer, in the rows of Wear this and in the answer area. When the page cannot draw it now (another view is on its way) it is kept for `release()`. */
  function show(one, result, records) {
    const items = result.kit.map((ident) => (ident === null ? null : itemOf(records, ident, one.settings.tier)));
    if (app.drawSolved({ items, tier: one.settings.tier, hasteAssumed: result.hasteAssumed, value: result.value, kind: one.kind }) === false) {
      one.parked = () => show(one, result, records);
      return;
    }
    root.classList.remove("solving");
    const label = result.label === null || result.label === undefined ? "" : ` (${result.label})`;
    say(`Kit value ${words.fmtInt(words.displayInt(result.value))}${label}. Exact value (F): ${result.F}.`, { title: true, label: BACK, action: back });
  }

  /** The page stayed on the view it showed (the one it was loading could not be had): an answer that waited for the page is drawn now, if it is still for the settings shown. */
  function release() {
    const one = wanted;
    if (one === null || one.parked === null || one.stopped) return;
    const draw = one.parked;
    one.parked = null;
    draw();
  }

  /**
   * The question is open, or about to be, and nothing is worked out until it is answered: the line says so, and its button goes to the question. The kit shown stays dimmed. The button is
   * there when the question is in the page (a button to a question that is not there would move the focus to the table), and comes when the client has mounted it. The client has no
   * event for either, and this request may have nothing to report for a while after the answer (it can wait behind the request the question was asked for), so the line looks at the
   * page and at the state of the question while it stands, and once the question is answered says that the work is on, with Stop. A line that something else has replaced meanwhile (a
   * fault, the answer) is left alone.
   */
  function waiting(one, attempt) {
    const question = () => doc.querySelector(".engine-consent");
    const point = () => say(WAITING, { label: "Go to the question", action: () => question()?.focus() });
    let pointing = question() !== null;
    if (pointing) point();
    else say(WAITING);
    stopLooking();
    looking = setInterval(() => {
      const mine = root.isConnected && wanted === one && one.attempt === attempt && !one.stopped;
      if (mine && client?.consentState?.() === "unknown") {
        if (!pointing && question() !== null && line.textContent === WAITING) {
          pointing = true;
          point();
        }
        return;
      }
      stopLooking();
      if (mine && line.textContent === WAITING) say(WORKING, { label: "Stop", action: () => stop(one) });
    }, LOOK_MS);
  }

  function stopLooking() {
    clearInterval(looking);
    looking = null;
  }

  const track = (promise) => {
    app.track(promise);
    return promise;
  };

  /** Stop: this request is taken back, alone. One that waits leaves the queue; one the worker has stops the worker (it starts again from the module the client kept, with no download). */
  function stop(one) {
    clearTimeout(timer);
    timer = null;
    if (wanted !== one) return;
    one.stopped = true;
    stopLooking();
    one.ask?.controller.abort();
    root.classList.remove("solving");
    say(`Stopped. The table shows the precomputed answer for ${nearest(one.settings)}, not for your settings.`, { label: "Try again", action: () => again(one) });
  }

  function again(one) {
    if (wanted !== one) return;
    one.stopped = false;
    one.resent = false;
    root.classList.add("solving");
    say(WORKING, { label: "Stop", action: () => stop(one) });
    work(one);
  }

  /** The visitor said no to the question: on a later yes the request is made again. */
  async function load(one) {
    let yes = false;
    try {
      yes = (await client.askConsent()) === true;
    } catch {
      yes = false;
    }
    if (yes) again(one);
  }

  function fault(one, error) {
    const code = typeof error?.code === "string" ? error.code : "";
    const detail = typeof error?.message === "string" ? error.message : "";
    let sentence;
    let label = "Try again";
    let action = () => again(one);
    let released = false;
    if (error instanceof Updated || (code === "engine-load" && client?.stats?.().updated === true)) {
      [sentence, label, action, released] = [UPDATED, "Reload", () => app.reload(), true];
    } else if (code === "declined" || (code === "cancelled" && client?.consentState?.() !== "granted")) {
      sentence = `The optimizer was not loaded, so the table shows the precomputed answer for ${nearest(one.settings)}, not for your settings.`;
      [label, action] = ["Load the optimizer", () => load(one)];
    } else if (code === "bad-request") {
      sentence = `${COULD_NOT} The optimizer would not take them: ${detail.endsWith(".") ? detail.slice(0, -1) : detail}.`;
    } else if (code === "protocol") {
      sentence = `${COULD_NOT} The optimizer sent something that was not expected, so it was stopped.`;
    } else if (error instanceof ItemFailure) {
      sentence = detail;
    } else {
      sentence = `${COULD_NOT} ${detail === "" ? "Something went wrong." : detail}`;
      if (code === "unsupported") label = null;
    }
    root.classList.remove("solving");
    say(sentence, { label, action });
    app.announce(sentence);
    if (released) app.dataUpdated();
  }

  sync(app.displayed.weights);
  return { sync, text, settle, release };
}
