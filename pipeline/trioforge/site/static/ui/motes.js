// Spend your motes: in which order to spend void-touched motes on a kit, drawn in the Upgrade section of a trio page.
//
//   createMotes(root, {records, listed, trio, level, view, onView, words, announce, doc, win, fetchImpl, base, stallMs, bodyMs, loadEngine, track, reload}) -> {setGear(source, pending), destroy()} | null
//
// A void-touched mote raises any one item by one whole tier, at any tier, up to +10, with no limit on the motes one item takes (the rule `tier.void_mote`). The order is greedy: each line
// is the best run after the lines before it, never a proven best plan for the motes a visitor has; the panel says so. A line is a RUN of motes on one item: usually one mote, but a gain can sit
// more than one mote away on one item (a weapon whose damage rises every second tier, a haste that counts only once it passes the best worn one), and then the line is the fewest motes that
// gain something, with their count ("+0 to +6, 6 motes"); the lines are numbered by the list and the motes spent so far are said on the lines once they differ from the number of the line. The
// kit is fixed (the same items in the same places, only the tiers change), valued as the page values a kit everywhere, under the view the kit is for, with the optional buffs it has now held
// fixed (the panel says so). The numbers are worked out by the evaluator's own script (engine/kitvalue.js, `moteWalkOf`, which is held to the Python reference by a recorded fixture): no
// solver, no worker and no download of the optimizer are needed, so the panel asks the visitor nothing. The script is fetched as a shared kit's is (by the path, size and SHA-256 of the
// manifest, checked before it is run), with the bundle of the trio.
//
// The panel is made with the section's code and kept out of sight until the check box the page is made with (`#upgrade-motes-open`, one of the controls that wake the code) is on; the box's
// own state is the panel's, so a click that came before this code was there is not lost. It is for one of two kits, which a visitor chooses:
//   * the gear: the kit that Equip now (upgrade-answer.js) wears, at the tiers of the gear. The answer tells the panel (`setGear`) when it draws that kit, and again with null the moment
//     anything that kit was worked out for changes (the gear, the view, the tier mode): an order never stands for a kit that is no longer shown, and is worked out again when the new
//     Equip now is there;
//   * the best kit of the page: the published kit Wear this shows, every item at the tier of the view. It is read from the rows of Wear this (the item key is in the link of its name, the tier in
//     its Tier cell): the page's script knows no kit while the baked answer is shown. It is offered only where the page shows a published kit (the own or the common group buffs with the
//     role's own weights; anything else is the optimizer's answer, not a published one), and it follows the page: when the rows or the view change, the list is cleared and worked out again.
// The optional buffs of the page's kit are the best choice for it (the exact search a shared kit's value uses), and held fixed; when that search ran out of calls the panel says that they may not
// be the best ones, and still gives the order.
//
// A number of motes is an order of its own, not a cut of the whole one: a run longer than the motes left is not taken (the next-best run is), so each number is worked out once and kept for the
// kit that is on the page, and the whole order is one of them. The numbers are worked out in slices of a few milliseconds, with a quiet line of progress, so that nothing freezes; a change of the
// kit, the view or the source ends the run in flight, and a list that belongs to an older kit is never left on the page. A run that failed stays failed (with Try again) until a real change.
// What is said through `announce` is said once for a list the visitor asked for (opening the panel, choosing the kit, a number, Try again), after a pause when a number is being typed, and never
// for a list that a change of the gear or the view starts again by itself: Equip now and the page say their own. Nothing is stored, sent or tracked.
//
// Everything is text (textContent, never markup). The panel has no live region of its own. The focus is never moved.

import { ImportTimeout, fetchBytes, importWithin, sameOriginUrl, sha256Hex } from "../engine/download.js";

const PLACES = 22;
/** How long one slice of the work may take before the page gets a turn, in milliseconds. */
const SLICE_MS = 12;
/** The pause in typing after which what the box says is taken and said. */
const TYPING_MS = 500;
/** The pause that lets a change of the page's kit settle (the rows of Wear this are written in one go) before the order is worked out again. */
const SETTLE_MS = 120;
/** The numbers of motes kept for one kit: more are let go, the oldest first. */
const KEPT = 12;
const SCRIPT_FILE = Object.freeze({
  type: /^(?:text|application)\/(?:x-)?(?:java|ecma)script(?:$|[\s;])/i,
  noun: "The motes evaluator",
  stalled: "The motes evaluator download stalled",
});
const FOR_GEAR = "your gear (the kit Equip now wears)";
const NO_GEAR = "There is no kit from Equip now yet. Add your gear above: the order is worked out for the kit Equip now finds.";
const WAITING_GEAR = "Waiting for Equip now's kit for your gear…";
const NO_PUBLISHED = "The kit shown here is the optimizer's answer for these buffs or weights, not a published one. Choose your gear, or the own or group buffs with the role's own weights.";
const NO_READ = "The kit shown on this page could not be read here.";
const NO_EVALUATOR = "The order of motes could not be worked out here.";
const NO_EVALUATOR_RELOAD = "The order of motes could not be worked out here. Reload the page to try again.";
const WORKING = "Working out the order of motes…";
const BAD_NUMBER = "Use a whole number of motes from 1, or leave the box empty.";
const LEAD =
  "A mote raises one item by one whole tier, at any tier, up to +10, and an item can take as many as you give it. Each line is the best next step after the lines before it: the motes on one item that add the most kit value for each mote, usually one mote and sometimes a few in a row when the gain is further away. This is the best single next step, not a proven best plan for the motes you have.";
const SAVES = "A mote gives one whole tier at any tier, so it saves the most work on the highest tiers.";
const BUFFS = "The order is worked out with the buffs this kit has now, and they stay as they are however the tiers change.";
const INEXACT = "The best buffs for this kit were not searched out completely, so they may not be the best ones.";
const HELP = "Leave empty for every mote there is to spend.";
/** What a stat is called in the line of a step (the codes of the evaluator's totals). */
const STAT_WORDS = new Map([
  ["HASTE", "Haste"], ["FIRE", "FR"], ["COLD", "CR"], ["MAGIC", "MR"], ["POISON", "PR"], ["DISEASE", "DR"], ["MANA", "Mana"], ["END", "End"],
  ["HPREG", "HP regen"], ["MANAREG", "Mana regen"], ["ENDREG", "End regen"], ["DMG", "Damage"],
]); // fmt: skip

const plural = (n, one, many) => (n === 1 ? one : many);
const split = (ident) => {
  const at = ident.lastIndexOf("@");
  return [ident.slice(0, at), Number(ident.slice(at + 1))];
};

export function createMotes(root, env) {
  const { records, listed, trio, level, view, onView, words, announce, fetchImpl, base, stallMs, bodyMs, track } = env;
  const doc = env.doc ?? root.ownerDocument;
  const win = env.win ?? doc.defaultView;
  const importModule = env.loadEngine ?? ((url) => import(url));
  const toggle = root.querySelector("#upgrade-motes-open");
  if (toggle === null || typeof view !== "function" || typeof onView !== "function" || !(records instanceof Map)) return null;
  const clock = () => win.performance?.now?.() ?? Date.now();

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
  const choice = (value, label) => {
    const input = el("input", { type: "radio", name: "upgrade-motes-source", id: `upgrade-motes-source-${value}`, value });
    return { input, node: el("span", { class: "opt" }, input, el("label", { for: `upgrade-motes-source-${value}`, text: label })) };
  };
  const gearChoice = choice("gear", "Your gear (Equip now)");
  const pageChoice = choice("page", "The best kit of this page");
  const sources = el("fieldset", { class: "mode-set" }, el("legend", { text: "Spend them on" }), gearChoice.node, pageChoice.node);
  const field = el("input", { type: "number", id: "upgrade-motes-n", min: "1", step: "1", inputmode: "numeric", autocomplete: "off", "aria-describedby": "upgrade-motes-help" });
  const entry = el("div", { class: "pick" }, el("div", { class: "control combo" }, el("label", { for: "upgrade-motes-n", text: "Motes to spend" }), field));
  const help = el("p", { id: "upgrade-motes-help", class: "note", text: HELP });
  const bad = el("p", { id: "upgrade-motes-bad", class: "note", hidden: true, text: BAD_NUMBER }); // (its own place: what the work says in the line below never takes it away)
  const stateWords = el("span", { class: "status-text" });
  const state = el("p", { id: "upgrade-motes-state", class: "status quiet" }, stateWords);
  const inexact = el("p", { id: "upgrade-motes-inexact", class: "note", hidden: true, text: INEXACT });
  const about = el("p", { id: "upgrade-motes-for", class: "note", hidden: true });
  const list = el("ol", { id: "upgrade-motes-list", class: "steps", "aria-labelledby": "upgrade-motes-h" });
  const end = el("p", { id: "upgrade-motes-end", class: "note", hidden: true });
  const heading = el("h3", { id: "upgrade-motes-h", tabindex: "-1", text: "Spend your motes" });
  const panel = el(
    "section",
    { id: "upgrade-motes", class: "result", "aria-labelledby": "upgrade-motes-h", hidden: true },
    heading,
    el("p", { class: "note", text: LEAD }),
    el("p", { class: "note", text: SAVES }),
    el("p", { id: "upgrade-motes-buffs", class: "note", text: BUFFS }),
    el("p", { class: "rules" }, "Rule: ", el("a", { href: "/rules/#tier.void_mote", text: "Void-touched mote" })),
    sources,
    entry,
    help,
    bad,
    state,
    inexact,
    about,
    list,
    end,
  );
  toggle.closest(".opt")?.after(panel);
  if (panel.parentNode === null) root.querySelector("#upgrade-results")?.before(panel);
  toggle.setAttribute("aria-controls", "upgrade-motes");
  toggle.setAttribute("aria-expanded", String(toggle.checked));

  // ---- what is said ---------------------------------------------------------------------------------------------------------------------------------
  let button = null;
  function setState(text, offer = null) {
    stateWords.textContent = text;
    state.classList.toggle("quiet", text === "");
    button?.remove();
    button = null;
    if (offer !== null) {
      button = el("button", { type: "button", class: "btn", text: offer.label });
      button.addEventListener("click", () => offer.action());
      state.append(" ", button);
    }
  }
  function say(text) {
    if (typeof announce === "function") announce(text);
  }
  let speaking = null; // the summary that waits to be said
  let typing = null; // the word about a number that is no number, which waits to be said
  let settling = null; // the pause that lets a change of the page's kit settle
  const clearTimers = () => {
    win.clearTimeout(speaking);
    win.clearTimeout(typing);
    win.clearTimeout(settling);
    speaking = typing = settling = null;
  };
  /** Say what the panel shows, once, after `delay` (a number being typed settles first); a later call takes the place of one that waits. */
  function speakSoon(delay) {
    win.clearTimeout(speaking);
    speaking = win.setTimeout(() => {
      speaking = null;
      const run = session?.run;
      if (!open() || session === null || session.failed || run === undefined || !run.done) return;
      say(summary(run));
    }, delay);
  }

  // ---- the words ------------------------------------------------------------------------------------------------------------------------------------
  const nameOf = (key) => records.get(key)?.name ?? key;
  /** A change in kit value as the page shows a difference: rounded half up, with its sign. One that is more than nothing but rounds to nothing is "+<1", and a loss of the like "−<1". */
  function signed(value) {
    const shown = words.displayInt(value);
    if (shown === 0 && value > 0) return "+<1";
    if (shown === 0 && value < 0) return `${words.fmtSigned(-1).slice(0, -1)}<1`;
    return words.fmtSigned(shown);
  }
  const whole = (value) => words.fmtInt(words.displayInt(value));
  const stepText = (step) =>
    `${words.slotLabel(step.place)}: ${nameOf(step.key)} ${words.tierLabel(step.from)} to ${words.tierLabel(step.to)}, ${step.motes > 1 ? `${step.motes} motes, ` : ""}${signed(step.gain.toNumber())}`;
  const movedText = (step) => step.moved.map(([name, amount]) => `${STAT_WORDS.get(name) ?? name} ${signed(amount.toNumber())}`).join(", ");

  // ---- the kits -------------------------------------------------------------------------------------------------------------------------------------
  let gear = null; // {request, kit, buffs} of the Equip now that is shown, or null
  let gearPending = false; // Equip now is being worked out again (a change was made): the kit comes
  let gearNumber = 0; // moved by every change of it: a run is for the number it started with

  /** The kit shown in Wear this, as `[{slotIndex, key, tier}]`, or null when the rows cannot be read (a name that is no link, a tier that is no tier). */
  function shownKit() {
    const rows = [...doc.querySelectorAll("#kit-body tr")];
    if (rows.length !== PLACES) return null;
    const places = [];
    for (let slotIndex = 0; slotIndex < PLACES; slotIndex += 1) {
      const name = rows[slotIndex].querySelector('[data-f="name"]');
      const link = name === null ? null : name.querySelector("a[href]");
      if (link === null) {
        if (name !== null && name.textContent.trim() === words.emptyName) continue; // (an empty place)
        return null;
      }
      const key = /\/item\/([^/?#]+)\/?$/.exec(link.getAttribute("href") ?? "")?.[1];
      const tier = /^\+(\d{1,2})$/.exec((rows[slotIndex].querySelector('[data-f="tier"]')?.textContent ?? "").trim());
      if (key === undefined || !records.has(key) || tier === null || Number(tier[1]) > 10) return null;
      places.push({ slotIndex, key, tier: Number(tier[1]) });
    }
    return places;
  }

  /** What the order is worked out for, for a source: `{key, about, scenario...}`, or `{words}` for what to say when there is nothing to work from. */
  function targetOf(source) {
    if (source === "gear") {
      if (gear === null) return { words: gearPending ? WAITING_GEAR : NO_GEAR };
      const { scenario, weights } = gear.request;
      return {
        key: JSON.stringify(["gear", gearNumber]),
        about: FOR_GEAR,
        scenario,
        weights,
        chosen: gear.buffs,
        places: gear.kit.flatMap((ident, slotIndex) => (ident === null ? [] : [{ slotIndex, key: split(ident)[0], tier: split(ident)[1] }])),
      };
    }
    const shown = view();
    if (shown.weights || (shown.buffs !== "own" && shown.buffs !== "group")) return { words: NO_PUBLISHED };
    const places = shownKit();
    if (places === null) return { words: NO_READ };
    const raceName = typeof words.raceName === "function" ? words.raceName(shown.race) : shown.race;
    const viewText = typeof words.viewText === "function" ? words.viewText() : "";
    return {
      key: JSON.stringify(["page", shown, places]),
      about: `the best kit of this page (${raceName}${viewText === "" ? "" : `, ${viewText}`})`,
      scenario: { race: shown.race, role: shown.role, buffs: shown.buffs, evidence: shown.evidence, setup: shown.setup },
      weights: undefined,
      chosen: null, // (the best choice for the kit: the page does not have the buffs that were chosen for it)
      places,
    };
  }

  // ---- the evaluator --------------------------------------------------------------------------------------------------------------------------------
  const fetching = { manifest: listed, fetchImpl, base, stallMs, bodyMs };
  let engineOnce = null;
  let bundleOnce = null;
  const getEngine = () => {
    engineOnce ??= Promise.resolve()
      .then(async () => {
        const file = listed?.kitvalue;
        if (file === null || file === undefined) throw new Error("the manifest lists no evaluator");
        const bytes = await fetchBytes(sameOriginUrl(file.path, base), file.bytes, fetchImpl, () => {}, stallMs, bodyMs, SCRIPT_FILE);
        if ((await sha256Hex(bytes)) !== file.sha256) throw new Error("the evaluator is not the one the manifest lists");
        return importWithin(importModule(sameOriginUrl(file.path, base).href), bodyMs, SCRIPT_FILE.noun);
      })
      .then((module) => {
        if (typeof module?.moteWalkOf !== "function" || typeof module.bestBuffsOfKit !== "function" || typeof module.loadKitBundle !== "function") throw new Error("the evaluator's script has no order of motes");
        return module;
      })
      .catch((error) => {
        engineOnce = null;
        throw error;
      });
    return engineOnce;
  };
  const getBundle = () => {
    bundleOnce ??= getEngine()
      .then((engine) => engine.loadKitBundle({ ...fetching, trio, level }))
      .catch((error) => {
        bundleOnce = null;
        throw error;
      });
    return bundleOnce;
  };

  // ---- the run --------------------------------------------------------------------------------------------------------------------------------------
  const open = () => toggle.checked;
  let destroyed = false;
  let source = null; // "gear" or "page", once the panel was opened (the first time it is the gear when Equip now has a kit, else the page)
  let limit = null; // the motes asked for: a whole number from 1, or null for every one
  let generation = 0; // the number of the latest session: an older one is never drawn
  let session = null; // the kit that is on the page: {id, key, about, items, announce, failed, exact, make, runs, run}
  let drawn = null; // the run whose lines are in the list, and how many of them
  let drawnCount = 0;

  const tick = () => new Promise((resolve) => win.setTimeout(resolve, 0));

  /** The order that is on the page is no more: what the session had is gone, and so is its work in flight. */
  function stop() {
    generation += 1;
    session = null;
    drawn = null;
    drawnCount = 0;
    clearTimers();
  }
  function clearList() {
    list.replaceChildren();
    about.hidden = true;
    about.textContent = "";
    end.hidden = true;
    end.textContent = "";
    inexact.hidden = true;
  }
  function reset() {
    stop();
    clearList();
    setState("");
  }

  /** How the list ends, from the run ("" while there is more to come). */
  function endWords(run) {
    if (!run.done) return "";
    const lines = run.steps.length;
    const how = lines === run.spent ? "" : `, in ${lines} ${plural(lines, "line", "lines")}`;
    if (run.ending === "motes") {
      if (run.nextRun !== null) {
        const left = limit === null ? 0 : limit - run.spent;
        return `The next gain needs ${run.nextRun} motes on one item and only ${left} ${plural(left, "is", "are")} left, so the list stops here.`;
      }
      return `These are the first ${run.spent} ${plural(run.spent, "mote", "motes")}${how}.`;
    }
    if (run.ending === "no-gain") {
      return lines === 0
        ? `No mote adds any kit value: ${run.left} could be spent, and none of them gains anything.`
        : `After these, no mote adds any kit value: ${run.left} could still be spent, and none of them gains anything.`;
    }
    if (lines === 0) return session.items === 0 ? "There is no item in this kit, so there is nothing to spend a mote on." : "Every item is at +10, so there is nothing to spend a mote on.";
    return "That is every mote there is to spend: every item is then at +10.";
  }

  /** What the page says of the order that is shown (the same words as the line under the list, with how many motes and lines and the first of them). */
  function summary(run) {
    const lines = run.steps.length;
    if (lines === 0) return endWords(run);
    const how = lines === run.spent ? "" : ` in ${lines} ${plural(lines, "line", "lines")}`;
    return `Spend your motes: ${run.spent} ${plural(run.spent, "mote", "motes")}${how} for ${session.about}. First: ${stepText(run.steps[0])}. ${endWords(run)}`.trim();
  }

  /** Draw the run: the lines that are not yet drawn (the list is made again when it was another run's), the line about it and the end. */
  function render(run) {
    if (drawn !== run) {
      list.replaceChildren();
      drawn = run;
      drawnCount = 0;
    }
    for (; drawnCount < run.steps.length; drawnCount += 1) {
      const step = run.steps[drawnCount];
      const facts = [el("span", { class: "step-what", text: stepText(step) })];
      const moved = movedText(step);
      if (moved !== "") facts.push(" ", el("span", { class: "owned-meta", text: moved }));
      facts.push(" ", el("span", { class: "owned-meta", text: `kit value ${whole(step.F.toNumber())}` }));
      if (step.spent !== step.index) facts.push(" ", el("span", { class: "owned-meta", text: `${step.spent} ${plural(step.spent, "mote", "motes")} so far` })); // (a run makes the motes differ from the lines)
      list.append(el("li", {}, ...facts));
    }
    about.textContent = `For ${session.about}: kit value now ${whole(run.walk.start.toNumber())}.`;
    about.hidden = false;
    inexact.hidden = session.exact !== false;
    const text = endWords(run);
    end.textContent = text;
    end.hidden = text === "";
    setState(run.done ? "" : `${WORKING} ${run.steps.length} ${plural(run.steps.length, "step", "steps")} so far.`);
  }

  /** The session could not go on: what happened and a button. It stays so until Try again or a real change. */
  function fail(mine, error) {
    if (mine.id !== generation) return;
    mine.failed = true;
    const late = error instanceof ImportTimeout;
    setState(late ? NO_EVALUATOR_RELOAD : NO_EVALUATOR, late ? { label: "Reload", action: () => (typeof env.reload === "function" ? env.reload() : win.location.reload()) } : { label: "Try again", action: () => start(true) });
    say(late ? NO_EVALUATOR_RELOAD : NO_EVALUATOR);
  }

  /** Carry a run on in slices until it is over. A run of a session that was replaced, or that failed, stops at its next slice. */
  async function pump(mine, run) {
    if (run.pumping) return;
    run.pumping = true;
    try {
      for (;;) {
        if (mine.id !== generation || mine.failed || mine.run !== run) return;
        const until = clock() + SLICE_MS;
        while (!run.done) {
          const step = run.walk.step();
          if (step === null) {
            run.done = true;
            run.ending = run.walk.ending();
            run.left = run.walk.left();
            run.spent = run.walk.spent();
            run.nextRun = run.walk.nextRun();
            break;
          }
          run.steps.push(step);
          run.spent = step.spent;
          if (clock() >= until) break;
        }
        render(run);
        if (run.done) {
          if (mine.announce) speakSoon(0);
          return;
        }
        await tick();
      }
    } catch (error) {
      fail(mine, error);
    } finally {
      run.pumping = false;
    }
  }

  /** Put up the order for the number of motes in the box (the whole order when it is empty): the one that was worked out, or a new walk. */
  function showRun(mine) {
    if (mine.id !== generation || mine.failed || mine.make === null) return;
    let run = mine.runs.get(limit);
    if (run === undefined) {
      run = { walk: mine.make(limit), steps: [], done: false, ending: null, left: null, spent: 0, nextRun: null, pumping: false };
      mine.runs.set(limit, run);
      if (mine.runs.size > KEPT) mine.runs.delete(mine.runs.keys().next().value);
    }
    mine.run = run;
    render(run);
    if (!run.done) void pump(mine, run);
    else if (mine.announce) speakSoon(0);
  }

  /** Work out the order for the source that is chosen, if the panel is open: nothing of an older one stays. `byVisitor` is whether the visitor asked for it (and so for its being said). */
  function start(byVisitor) {
    reset();
    if (destroyed || !open() || source === null) return;
    const target = targetOf(source);
    if (target.words !== undefined) {
      setState(target.words);
      return;
    }
    const mine = { id: generation, key: target.key, about: target.about, items: target.places.length, announce: byVisitor, failed: false, exact: true, make: null, runs: new Map(), run: undefined };
    session = mine;
    setState(WORKING);
    const work = (async () => {
      try {
        const [bundle, engine] = await Promise.all([getBundle(), getEngine()]);
        await tick(); // (the data and the script came in: the page gets a turn before the work begins, and again before each stage of it)
        if (mine.id !== generation) return;
        const { scenario, weights, places } = target;
        const shared = { bundle, records, race: scenario.race, role: scenario.role, buffs: scenario.buffs, evidence: scenario.evidence, deity: null, weights, setup: scenario.setup, places };
        let chosen = target.chosen;
        if (chosen === null) {
          const found = engine.bestBuffsOfKit(shared);
          chosen = found.buffs;
          mine.exact = found.exact;
          await tick();
          if (mine.id !== generation) return;
        }
        mine.make = (motes) => engine.moteWalkOf({ ...shared, chosen, motes });
        showRun(mine);
      } catch (error) {
        fail(mine, error);
      }
    })();
    if (typeof track === "function") track(work);
  }

  // ---- what the visitor does -------------------------------------------------------------------------------------------------------------------------
  function sync() {
    if (destroyed) return;
    toggle.setAttribute("aria-expanded", String(open()));
    panel.hidden = !open();
    if (!open()) {
      reset();
      return;
    }
    if (source === null) {
      source = gear === null ? "page" : "gear";
      (source === "gear" ? gearChoice : pageChoice).input.checked = true;
    }
    start(true);
  }

  /** The number in the box: null for none, a whole number from 1 (any length: more than there are to spend is the whole order), or NaN for anything else. */
  function numberIn() {
    const text = field.value.trim();
    if (field.validity?.badInput === true) return Number.NaN;
    if (text === "") return null;
    if (!/^[0-9]+$/.test(text)) return Number.NaN;
    const n = Number(text);
    if (n < 1) return Number.NaN;
    return Number.isSafeInteger(n) ? n : Number.MAX_SAFE_INTEGER;
  }

  const listeners = [];
  const listen = (target, type, handler) => {
    target.addEventListener(type, handler);
    listeners.push(() => target.removeEventListener(type, handler));
  };

  function onNumber() {
    if (destroyed) return;
    const parsed = numberIn();
    const wrong = Number.isNaN(parsed);
    field.setAttribute("aria-invalid", String(wrong));
    field.setAttribute("aria-describedby", wrong ? "upgrade-motes-help upgrade-motes-bad" : "upgrade-motes-help");
    bad.hidden = !wrong;
    win.clearTimeout(typing);
    typing = null;
    if (wrong) {
      typing = win.setTimeout(() => {
        typing = null;
        if (open()) say(BAD_NUMBER);
      }, TYPING_MS);
      return;
    }
    limit = parsed;
    const mine = session;
    if (mine === null || mine.failed || mine.make === null) return; // (nothing is worked out yet, or it failed, and stays so: the box is read when there is something to read it)
    mine.announce = true; // (a number is the visitor's: what it makes is said)
    showRun(mine);
    speakSoon(TYPING_MS);
  }

  /** The page's kit or view may have changed: for the best kit of the page, an order that belongs to another kit goes, and the order for the kit now shown is worked out. */
  function pageChanged() {
    if (destroyed || !open() || source !== "page") return;
    win.clearTimeout(settling);
    const target = targetOf("page");
    if (session !== null && !session.failed && target.key !== undefined && session.key === target.key) return; // (the same kit, in the same view: what is shown stands)
    reset(); // (an order of another kit is never left on the page while this one is waited for)
    settling = win.setTimeout(() => {
      settling = null;
      if (!destroyed && open() && source === "page") start(false); // (made again by itself: the page says what its switch did)
    }, SETTLE_MS);
  }

  // what can fail comes first, and the listeners last: a panel that could not be made leaves nothing listening
  const unwatch = onView(pageChanged);
  const body = doc.querySelector("#kit-body");
  let watcher = null;
  if (body !== null && typeof win.MutationObserver === "function") {
    watcher = new win.MutationObserver(pageChanged);
    watcher.observe(body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["href"] });
  }
  listen(toggle, "change", sync);
  for (const { input } of [gearChoice, pageChoice]) {
    listen(input, "change", () => {
      if (destroyed || !input.checked || source === input.value) return;
      source = input.value;
      start(true);
    });
  }
  listen(field, "input", onNumber);

  if (open()) sync(); // (the box was ticked before this code was there)

  return {
    /** Equip now's kit has been drawn, as `{request, kit, buffs}`, or has gone (null: something it was worked out for changed, and `pending` says that a new one is being worked out). */
    setGear(next, pending = false) {
      if (destroyed) return;
      gear = next === null || next === undefined ? null : next;
      gearPending = gear === null && pending === true;
      gearNumber += 1;
      if (!open() || source !== "gear") return;
      start(false); // (the answer starts again by itself: Equip now says its own)
    },
    /** Let go of everything: the listeners, the watchers, the pauses that wait and the work in flight. What is on the page stays as it is. */
    destroy() {
      if (destroyed) return;
      destroyed = true;
      stop();
      for (const off of listeners.splice(0)) off();
      watcher?.disconnect();
      if (typeof unwatch === "function") unwatch();
    },
  };
}
