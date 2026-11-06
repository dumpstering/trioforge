// The trio page: the race, role, tier and assumption switches.
//
// The page arrives with its default answer already in it. This code changes nothing until a switch changes (or the address
// asks for another view); then it fetches the data file for that buff set (of the one evidence level the page is made from), picks the scenario, and writes the
// answer into the elements that are already there. Text goes in with textContent only (the name of an item in Wear this is a link to the page of the item where the page
// says its items have pages: one element, made with the DOM, holding that text). If a fetch fails, the answer on the
// page stays, the controls go back to what the page shows, and a message says so, says what went back, and offers to try again.
//
// What a visitor who cannot see the page is told: #status holds what went wrong or what was changed under the visitor's hands
// (it is always on the page, empty, so that the first message is announced), and #announce says what each change of a switch
// made of the view, with the kit value, so that two changes never sound alike. On a phone the switches hide behind one line that says
// what is shown and a Change button; the rest of the page reads the same whether they are open or not.
//
// Every data file names the release it was made from, and the page names the release it was built for. A file of another release (the
// site was published again while the page was open) is not used: the page says that the data was updated and offers a reload.
//
// The Upgrade section at the end of the page has its controls in the page, and its code (ui/upgrade-input.js and what it uses) is a chunk of its own that is not
// loaded until the section is used: the first focus or click on it, or a file dragged over or dropped on it. The code of the section then takes it from there; this code
// only keeps a file that comes before it, says in the page's own status when the data of the site is newer than the page, says in the section's own line (with a Reload button: a
// browser keeps a failed module fetch until the page is reloaded, so a Try again could not work) when the code of the section could not be had or would not start, and cancels,
// from the first moment and for good, every drag of a file (the browser would open it in place of the page).
// What the section needs of the page it is given when it starts: the view the page shows (`view`, and `onView`, which says when that changed), and the words of the kit (`words`:
// the code of the section is not allowed to import format.js, which the page script imports: the build would then load a shared chunk with the page).
//
// The sliders and the buff choices. The Buffs assumption offers the own buffs, the common group buffs and the full raid, and an Enchanter in the group; the Weights assumption has a slider for each weight
// group of the trio's bundle (its names are the `data-groups` of the page), with the positions x0.5, x1 and x2. The shards answer the own buffs and the common group buffs with every slider at x1 (the
// precomputed answers: `view.exact`); every other combination is worked out by the optimizer in the visitor's browser, for the view the page shows, and its kit takes the place of the shard's
// in Wear this. The code for that (ui/weights.js: the sliders, the request, the answer area, the item list the answer's names are read from) is a chunk of its own, loaded the first time
// one of the controls is used or the address asks for a combination the shards lack; the page script only keeps the state (`state.buffs`, one of own, group, group+enchanter and raid, and
// `state.weights`, a character for each group: h, 1 or 2), writes it in the address (`buffs` and `w`, which is left out when every slider is at x1) and in the lines that say what is assumed, and gives
// the chunk what it draws the answer with. The answer of the optimizer is announced through #announce, once, and never when it is for settings that are no longer shown.
//
// Two things make the page load the code of the section at the start, without a first use: a kit link (a shared kit is shown at the top of the page, which needs the item table) and
// gear that the visitor asked the device to remember (it is restored into the list). The check for the second is one guarded read of the device, and nothing more is loaded
// for a page that has neither. The section is given the kit link that came in the address (`kit`, what first.js took out of it), where the gear is kept (`remember`: the key, the
// storage, which may be none, and what was stored, which may be nothing: the page script knows the key and no more of the format), and what a shared kit needs to be valued under the
// view the page shows (`valueView`: the role, buffs and evidence level of the view, the level being the one the page is made from, and no more: the kit's own hands give its weapon setup and its own items its haste, and the page's
// weapon switch and tier switch, which move the haste of the page's own answer, are not part of it; `words.raceName`, `words.viewText` and `words.setupText`).

import { getStorage } from "./theme.js";
import { DASH, EMPTY_NAME, EN_DASH, arrivalText, deityText, displayInt, fmtInt, fmtSigned, reachText, tierLabel } from "./format.js";
import { parseRobust, parseRunnerups, parseShard } from "./shard.js";

const SWITCHES = '#sw-race, #sw-tier, input[name="role"], input[name="setup"], input[name="buffs"], #buffs-ench';
const EXTRAS = ["runnerups", "robust"];
const NOT_LOADED = "Couldn't load this view; try again.";
const UPDATED = "Data updated, reload the page to see the new data.";
const SECTION_UPDATED = "Data updated, reload the page to see this section.";
const NOT_LOADED_UPGRADE = "Couldn't load the Upgrade section. Reload the page to try again.";
const NOT_LOADED_WEIGHTS = "Couldn't load the weights. Reload the page to try again.";
/** The weights in the address (`w`) that this page cannot take: a character for each weight group, h (x0.5), 1 or 2 (x2), and no more or fewer. */
const BAD_WEIGHTS = "The weights in the address do not fit the sliders of this page, so the role's own weights are shown.";
const OWN_WEIGHTS = "role's own";
/** What the Weights line says of sliders that are moved until the code that knows their words has come. */
const CUSTOM_WEIGHTS = "custom";
const POSITIONS = /^[h12]+$/;
/** The buff sets the optimizer works out for the visitor: the full raid and the group with an Enchanter (the shards have the own buffs and the common group buffs). */
const ENCHANTER = "group+enchanter";
/** What the address says for it: a word, with no plus sign for a browser to read as a space. The older spelling, group+enchanter, is read too, escaped or not. */
const ENCHANTER_WORD = "enchanter";
/** What starts the Upgrade section: a focus or a click on one of its controls, or a file brought to it (the file input's own choice comes as a change). */
const UPGRADE_EVENTS = ["focusin", "click", "dragenter", "dragover", "drop", "change"];
const UPGRADE_CONTROLS = "input, select, button, label";
/** Where the gear a visitor asked the device to remember is kept (the format is the section's: this file reads nothing of it). */
const GEAR_KEY = "trioforge-gear";
const KIT_NOT_LOADED = "Couldn't load the shared kit. Reload the page to try again.";
const NOT_LOADED_EXALT = "Couldn't load the effects. Reload the page to try again.";
/** The two files of the section Effects to exalt, as the page names them: the shared one and the trio's (the section only fetches an address of this form). */
const EXALT_FILES = /^\/data\/(?:[a-z]{3}-[a-z]{3}-[a-z]{3}\/)?(?:effects|exalt)\.json$/;
const NO_KIT = Object.freeze({ payload: null, source: null, cleared: false });
/** Where the pages of the items are. The build writes it as the `data-items` of the page when every item the page can show has a page, and the names the code paints are links only then. */
const ITEM_BASE = "/item/";
/** What the key of an item may be in an address: the one pattern of an item key (data.py: KEY_PATTERN, which the reader of the results and the build use as well), so that nothing a data file holds can steer a link elsewhere. */
const ITEM_KEY = /^(?:w[1-9][0-9]{0,14}|r[a-z0-9][a-z0-9-]{0,99})$/;
/** What a row says of an item whose stats the page does not have for the view (an item of the optimizer's answer that no shard of this page lists). */
const STATS_ON_PAGE = "Its stats at this tier are on the page of the item.";
const STATS_MISSING = "Its stats are not on this page.";

/** A data file of another release than the page's: the site was published again while the page was open. */
class DataUpdated extends Error {}

const field = (parent, name) => parent.querySelector('[data-f="' + name + '"]');

function setField(parent, name, text) {
  const node = field(parent, name);
  if (node) node.textContent = text;
}

/** The name of an item in its row: a link to the page of the item when it has an address (an element, an attribute and text, which replace whatever the name held), else plain text. */
function setName(row, text, href) {
  const node = field(row, "name");
  if (!node) return;
  if (href === null) {
    node.textContent = text;
    return;
  }
  const link = node.ownerDocument.createElement("a");
  link.setAttribute("href", href);
  link.textContent = text;
  node.replaceChildren(link);
}

export function initTrio(env = {}) {
  const doc = env.document ?? document;
  const win = env.window ?? window;
  const fetchJson = env.fetch ?? win.fetch.bind(win);
  const root = doc.getElementById("main");
  if (!root || root.dataset.page !== "trio") return null;
  const app = new TrioApp(
    root,
    doc,
    win,
    fetchJson,
    env.reload ?? (() => win.location.reload()),
    env.loadUpgrade ?? (() => import("./ui/upgrade-input.js")),
    env.loadEngine,
    env.kit ?? NO_KIT,
    env.loadWeights ?? (() => import("./ui/weights.js")),
    env.loadExalt ?? (() => import("./ui/exalt.js")),
  );
  app.start();
  return app;
}

class TrioApp {
  constructor(root, doc, win, fetchJson, reload, loadUpgrade, loadEngine, kit, loadWeights, loadExalt) {
    this.root = root;
    this.doc = doc;
    this.win = win;
    this.fetchJson = fetchJson;
    this.reload = reload;
    this.loadUpgrade = loadUpgrade; // gives the module of the Upgrade section (tests give another)
    this.loadEngine = loadEngine; // gives the module of the optimizer's client from an address (the section's own import when none is given; tests give another)
    this.kit = kit; // the kit link that came in the address: {payload, source, cleared} (first.js took it out)
    this.loadWeights = loadWeights; // gives the module of the sliders and of the answers for the settings no shard has (tests give another)
    this.loadExalt = loadExalt; // gives the module of the section Effects to exalt (tests give another)
    this.exalt = null; // what the module made of the section, once it was loaded
    this.wakingExalt = false;
    this.exaltShown = null; // what the section is told of the view: {role, race, tier, exact, kit}, the kit drawn in Wear this (set when the page is started; `kit` is null while the page shows the answer it was made with, whose items the files name)
    this.exaltWatchers = new Set();
    this.equipKit = null; // the kit of Equip now in the Upgrade section ({kit, record, defaults}), or null
    this.equipWatchers = new Set();
    this.weights = null; // what the module made, once it was loaded: {sync, text, settle, release}
    this.wakingWeights = null; // the promise of that, while it is being loaded
    this.groups = (root.dataset.groups ?? "").split(" ").filter(Boolean); // the weight groups of the trio's bundle, in its order: a slider and a character of `w` for each
    this.own = "1".repeat(this.groups.length); // every slider at x1: the role's own weights
    this.ench = root.querySelector("#buffs-ench"); // the Enchanter in the group
    this.stored = null; // what the device holds of the gear the visitor asked it to remember, read once at the start
    this.upgrade = null; // what the module made of the section, once it was loaded
    this.viewWatchers = new Set(); // what the Upgrade section wants to be told when the view the page shows has changed
    this.waking = false; // is the module being loaded?
    this.told = false; // has the visitor been told that it could not be loaded (and not that it has been since)?
    this.base = root.dataset.base;
    this.release = root.dataset.release ?? null; // the data release the page was built for
    this.reportBase = null; // the address of the link that reports a problem, as the build wrote it
    this.shards = new Map(); // "strict-own" -> Promise<Shard>
    this.extraData = new Map(); // "runnerups/balanced" | "robust" -> Promise<parsed>
    this.pending = new Set();
    this.dirty = { runnerups: false, robust: false };
    this.token = 0;
    this.applying = 0; // the token of the change that is loading its view (nothing shown is for that view yet), or 0
    this.retries = new Map(); // the line of a message -> what its button does now (#status, and the line of the Upgrade section)
    this.focusAfterRetry = false; // a retry that works moves the focus to the answer, since the button goes away
    this.rows = [...root.querySelectorAll("#kit-body tr")];
    // what the page was built with in the panel of each row (the stats and the why line of the default view), kept to be put back when the view comes back to it
    this.bakedKit = this.rows.map((row) => ({ stats: field(row, "stats")?.textContent ?? "", why: field(row, "why")?.textContent ?? null }));
    this.statIndex = new Map(); // item key -> {tier: text of its stats}, from every shard that was loaded: the stats of an item the optimizer's answer names
    this.openRows = new Set(); // the rows whose panel (stats and why) is open
    this.toggles = []; // the button of each row's panel, and the one that opens them all
    this.toggleAll = null;
    this.linkItems = root.dataset.items === ITEM_BASE; // the page says that every item it can show has a page of its own
    // the roles that have a runner-up file ("balanced"; it holds every tier of the run): nothing else is ever asked for
    this.runnerupFiles = new Set((root.querySelector("#runnerups")?.dataset.files ?? "").split(" ").filter(Boolean));
    this.config = this.readConfig();
    const d = this.config.defaults;
    this.exaltShown = { role: d.role, race: d.race, tier: d.tier, exact: false, kit: null }; // (the view of the address is not drawn yet: start() says whether it is the baked one)
    // what was asked for last and got. A setup of null means "the role's best": the visitor has not chosen one, so the view follows the
    // best of whatever role, tier and race comes next, and the address does not name a setup
    this.state = { race: d.race, role: d.role, tier: d.tier, ev: d.ev, buffs: d.buffs, setup: null, weights: this.own };
    // the setup the visitor chose last, shown yet or not (a change made while a view loads must not lose it); null is "the role's best"
    this.wantedSetup = null;
    this.wantedWeights = this.own; // the same for the sliders
    this.lastKind = false; // the switch the latest change was made with, which the answer of the optimizer is announced with
    // what the page shows (the baked answer to begin with)
    this.displayed = { ...d, weights: this.own, best: d.setup, offered: this.offeredFor(d.role) };
    this.shown = null;
  }

  // ---- reading the page -------------------------------------------------------------------------------------------------

  q(selector) {
    return this.root.querySelector(selector);
  }

  radios(name) {
    return [...this.root.querySelectorAll('input[name="' + name + '"]')];
  }

  checkedValue(name) {
    const radios = this.radios(name);
    return (radios.find((radio) => radio.checked) ?? radios[0])?.value;
  }

  /** The buff set the controls show: the own buffs, the common group buffs, the group with the Enchanter in it (the box is ticked while the group is chosen) or the full raid. */
  buffsValue() {
    const chosen = this.checkedValue("buffs");
    return chosen === "group" && this.ench?.checked ? ENCHANTER : chosen;
  }

  /** A buff set in words. */
  buffsPhrase(code) {
    const phrase = (list, one) => list.find((entry) => entry.code === one)?.phrase ?? one;
    return code === ENCHANTER ? phrase(this.config.buffs, "group") + " " + (this.ench?.dataset.phrase ?? "and an Enchanter") : phrase(this.config.buffs, code);
  }

  /** The assumptions of the shards' answer nearest to a buff choice: the own buffs, or the common group buffs for every other, and the role's own weights. */
  nearest(buffs) {
    return `${this.buffsPhrase(buffs === "own" ? "own" : "group")} and the role's own weights`;
  }

  /** A buff set as the address says it. */
  buffsWord(code) {
    return code === ENCHANTER ? ENCHANTER_WORD : code;
  }

  /** The sliders in words: the role's own, or the groups that are not at x1 (the words are the chunk's; until it has come they are only said to be something else). */
  weightsText(positions) {
    if (positions === this.own) return OWN_WEIGHTS;
    return this.weights ? this.weights.text(positions) : CUSTOM_WEIGHTS;
  }

  /** The sliders as a request carries them, `{multipliers: {group: position}}` for the groups that are not at x1, or null for the role's own (what the Upgrade section and the chunk ask with). */
  weightsTable(positions) {
    const multipliers = {};
    this.groups.forEach((group, index) => {
      if (positions[index] !== "1") multipliers[group] = positions[index] === "h" ? 0.5 : 2;
    });
    return Object.keys(multipliers).length === 0 ? null : { multipliers };
  }

  /** Whether the shards answer these settings: every slider at x1, and the own buffs or the common group buffs without the Enchanter. */
  isPrecomputed(settings) {
    return settings.weights === this.own && (settings.buffs === "own" || settings.buffs === "group");
  }

  offeredFor(role) {
    const radio = this.radios("role").find((r) => r.value === role);
    return (radio?.dataset.setups ?? "").split(" ").filter(Boolean);
  }

  readConfig() {
    const labelled = (radios) => radios.map((r) => ({ code: r.value, label: r.dataset.label ?? "", phrase: r.dataset.phrase ?? "" }));
    return {
      races: [...this.q("#sw-race").options].map((o) => ({ code: o.value, name: o.dataset.label })),
      roles: this.radios("role").map((r) => ({ code: r.value, label: r.dataset.label, hint: r.dataset.hint })),
      tiers: [...this.q("#sw-tier").options].map((o) => ({ value: Number(o.value), label: o.dataset.label })),
      setups: labelled(this.radios("setup")),
      buffs: labelled(this.radios("buffs")),
      defaults: {
        race: this.q("#sw-race").value,
        role: this.checkedValue("role"),
        tier: Number(this.q("#sw-tier").value),
        setup: this.checkedValue("setup"),
        ev: this.root.dataset.ev ?? "wiki", // the one evidence level the page is made from (wiki, in a release): there is no choice of it, in the page or in the address
        buffs: this.checkedValue("buffs"),
      },
    };
  }

  /**
   * The view an address asks for, and whether it names a value that means nothing here (`malformed`: a race, role, tier, setup or buff set that is not one of the page's
   * own, an empty one included) and whether its `w` (the sliders) is one that this page cannot take (`badWeights`). Anything it does not say clearly is left at the default.
   * An `ev` is taken and ignored, and never malformed: addresses written before wiki became the one evidence level carry it.
   */
  parseQuery(search) {
    const params = new URLSearchParams(search);
    let malformed = false;
    let badWeights = false;
    const known = (list, key, value) => {
      if (list.some((entry) => entry[key] === value)) return value;
      if (value !== null) malformed = true;
      return null;
    };
    const state = { ...this.state };
    state.race = known(this.config.races, "code", params.get("race")) ?? state.race;
    state.role = known(this.config.roles, "code", params.get("role")) ?? state.role;
    const tier = params.get("tier");
    state.tier = known(this.config.tiers, "value", tier !== null && /^\d{1,2}$/.test(tier) ? Number(tier) : tier) ?? state.tier;
    const spelled = params.get("buffs");
    const buffs = spelled === ENCHANTER_WORD || spelled === "group enchanter" ? ENCHANTER : spelled; // ("group enchanter" is the older spelling typed with a raw plus sign)
    state.buffs = known([...this.config.buffs, { code: ENCHANTER }], "code", buffs) ?? state.buffs;
    state.setup = known(this.config.setups, "code", params.get("setup"));
    // the sliders: a character for each group of the bundle. Anything else is not taken, and the page says so (a w given twice is not one the page can take: which of the two?)
    const weights = params.getAll("w");
    state.weights = this.own;
    if (weights.length > 0) {
      if (weights.length === 1 && weights[0].length === this.groups.length && POSITIONS.test(weights[0])) state.weights = weights[0];
      else badWeights = true;
    }
    return { state, malformed, badWeights };
  }

  // ---- starting and waiting --------------------------------------------------------------------------------------------

  start() {
    // the page is made with every switch disabled (there is nothing to switch to without this code); they are enabled here, and the
    // weapon setups that the role has no scenario for stay out of reach
    for (const control of this.root.querySelectorAll(SWITCHES)) control.disabled = false;
    this.setControls(this.displayed);
    this.bindChange();
    this.reportBase = this.doc.getElementById("report-link")?.getAttribute("href") ?? null;
    this.root.addEventListener("change", (event) => {
      const target = event.target;
      if (target && typeof target.matches === "function" && target.matches(SWITCHES)) this.onChange(target);
    });
    for (const name of EXTRAS) {
      const details = this.q("#" + name);
      if (!details) continue;
      const na = this.q("#" + name + "-na");
      if (na) na.dataset.original = na.textContent;
      details.addEventListener("toggle", () => {
        if (details.open && this.dirty[name]) this.track(this.fillExtra(name));
      });
    }
    const { state: asked, malformed, badWeights } = this.parseQuery(this.win.location.search);
    const d = this.config.defaults;
    // the baked answer is the role's best setup, so an address that names it asks for the best and not for a choice
    const baked = ["race", "role", "tier", "buffs"].every((key) => asked[key] === d[key]) && (asked.setup === null || asked.setup === d.setup) && asked.weights === this.own;
    this.exaltShown = { role: asked.role, race: asked.race, tier: asked.tier, exact: baked, kit: null }; // (the section is told only what is drawn: the baked answer, or nothing until the view of the address is)
    if (!baked) this.track(this.apply(asked, { url: true, notice: badWeights ? BAD_WEIGHTS : null }));
    // the page shows the default answer for an address with a value that means nothing: the address says so too, at once, and without
    // fetching anything, so that a malformed link never passes for a link to the default view
    else if (malformed || badWeights) {
      this.writeUrl({ state: this.state });
      if (badWeights) this.setStatus(BAD_WEIGHTS);
    }
    this.bindWeights();
    this.bindUpgrade();
    this.enhanceKit();
    this.bindExalt();
  }

  // ---- the section Effects to exalt: its code and its two files come when it is opened or scrolled into view --------------------------------------------------------------

  /**
   * The section is a details element the page is made with (closed), whose summary gets aria-expanded here. Its code (ui/exalt.js and the matcher it uses) is a chunk of its own, and its
   * two files are fetched by that code: nothing of it is asked for until the section is opened or its summary comes near the window, so the first load and the first view are what they were
   * without it. The section is told which kit Wear this draws (`exaltShown`) and which kit Equip now draws in the Upgrade section (`equipKit`), whenever they change.
   */
  bindExalt() {
    const section = this.q("#exalt");
    if (!section) return;
    const summary = section.querySelector("summary");
    summary?.setAttribute("aria-expanded", String(section.open));
    section.addEventListener("toggle", () => {
      summary?.setAttribute("aria-expanded", String(section.open));
      if (section.open) this.wakeExalt(section);
    });
    if (section.open) this.wakeExalt(section);
    else if (typeof this.win.IntersectionObserver === "function") {
      const watcher = new this.win.IntersectionObserver(
        (entries) => {
          if (!entries.some((entry) => entry.isIntersecting)) return;
          watcher.disconnect();
          this.wakeExalt(section);
        },
        { rootMargin: "300px" },
      );
      watcher.observe(section);
    }
  }

  wakeExalt(section) {
    if (this.wakingExalt || this.exalt !== null) return;
    const { effects, exalt } = section.dataset;
    if (!EXALT_FILES.test(effects ?? "") || !EXALT_FILES.test(exalt ?? "")) return;
    this.wakingExalt = true;
    const status = section.querySelector("#exalt-status");
    if (status && status.textContent === NOT_LOADED_EXALT) {
      status.hidden = true; // (the message of an earlier try: this one says its own)
      status.textContent = "";
    }
    this.track(
      this.loadExalt()
        .then((module) => {
          this.exalt = module.initExalt(section, {
            doc: this.doc,
            win: this.win,
            fetch: this.fetchJson,
            release: this.release,
            effectsUrl: effects,
            exaltUrl: exalt,
            view: () => this.exaltShown,
            onView: (callback) => {
              this.exaltWatchers.add(callback);
              return () => this.exaltWatchers.delete(callback);
            },
            equipKit: () => this.equipKit,
            onEquipKit: (callback) => {
              this.equipWatchers.add(callback);
              return () => this.equipWatchers.delete(callback);
            },
            words: {
              slotLabel: (index) => this.slotLabel(index),
              raceName: (code) => this.raceName(code),
              roleLabel: (code) => this.roleLabel(code),
              tierLabel,
              itemHref: (key) => this.itemHref(key),
            },
            announce: (text) => this.announce(text),
            onUpdated: () => this.dataUpdated(),
            reload: () => this.reload(),
          });
          return this.exalt.ready();
        })
        .catch(() => {
          // the code could not be had (a browser keeps a failed module fetch until the page is reloaded, so the way out is a reload)
          this.wakingExalt = false;
          if (status) {
            status.hidden = false;
            status.textContent = NOT_LOADED_EXALT;
            if (section.open) this.announce(NOT_LOADED_EXALT); // (a closed section has not been asked for: the line says it where it will be seen)
          }
        }),
    );
  }

  /** Tell the section what Wear this draws: the kit, the view it is of, and whether it is the kit the section's files were made for (the files have the plan for that kit). */
  setExaltView(scenario, exact) {
    const d = this.config.defaults;
    // the files' plan is for the default race's kit at the default tier, in the default view (evidence, buffs, weights) and the role's best setup; the role may be any the file has
    this.exaltShown = {
      role: this.displayed.role,
      race: this.displayed.race,
      tier: scenario.tier,
      exact: exact && this.displayed.race === d.race && scenario.tier === d.tier && this.displayed.ev === d.ev && this.displayed.buffs === d.buffs && this.displayed.weights === this.own,
      kit: scenario.kit.map((item) => (item ? { key: item.key, name: item.name } : null)),
    };
    for (const watcher of [...this.exaltWatchers]) {
      try {
        watcher();
      } catch {
        // a bug in the section is the section's, not the view's
      }
    }
  }

  /** The kit that Equip now draws (or null: none), as the Upgrade section tells it. */
  setEquipKit(kit) {
    this.equipKit = kit;
    for (const watcher of [...this.equipWatchers]) {
      try {
        watcher();
      } catch {
        // as above
      }
    }
  }

  // ---- the stats and the why of the rows of Wear this ----------------------------------------------------------------------------

  /**
   * Each row has a panel of its own (`data-f="more"`: a details element the page is made with, closed, whose summary is the button that opens it, so that it works without script and the
   * page does not move when this code starts). Here the summary is given what a disclosure button of this page has (aria-expanded and a name that says whose stats), and one button
   * of the title bar (`#kit-stats-all`, made disabled and out of sight, like the Change button) opens or closes all the rows.
   */
  enhanceKit() {
    const panels = this.rows.map((row) => field(row, "more"));
    if (!panels.some(Boolean)) return;
    this.rows.forEach((row, index) => {
      const panel = panels[index];
      const summary = panel?.querySelector("summary");
      if (!panel || !summary) return;
      summary.setAttribute("aria-expanded", String(panel.open));
      summary.className = "kit-toggle";
      this.toggles[index] = summary;
      if (panel.open) this.openRows.add(index);
      panel.addEventListener("toggle", () => this.syncRow(index));
      this.labelToggle(index, field(row, "name")?.textContent ?? "", Boolean(this.bakedKit[index].why));
    });
    const all = this.doc.getElementById("kit-stats-all");
    if (all) {
      all.disabled = false;
      all.addEventListener("click", () => {
        const open = !this.allOpen();
        this.rows.forEach((row, index) => {
          const panel = field(row, "more");
          if (panel && !panel.hidden) panel.open = open;
        });
        this.rows.forEach((row, index) => this.syncRow(index));
      });
      this.toggleAll = all;
    }
  }

  /** Are all the rows that have a panel open? */
  allOpen() {
    const shown = this.rows.map((row, index) => [field(row, "more"), index]).filter(([panel]) => panel && !panel.hidden);
    return shown.length > 0 && shown.every(([panel]) => panel.open);
  }

  /** Take the state of a row from its panel: the choice of a visitor (the browser opens and closes a details element itself). */
  syncRow(index) {
    const panel = field(this.rows[index], "more");
    if (!panel) return;
    if (panel.open) this.openRows.add(index);
    else this.openRows.delete(index);
    this.toggles[index]?.setAttribute("aria-expanded", String(panel.open));
    this.toggleAll?.setAttribute("aria-expanded", String(this.allOpen()));
  }

  labelToggle(index, name, why = false) {
    this.toggles[index]?.setAttribute("aria-label", (why ? "Stats and why for " : "Stats for ") + name);
  }

  /** Is the view the one the page was built with (the answer of the default view, which the why lines and the next best items are worked out for)? */
  isBaked(view) {
    const d = this.config.defaults;
    const s = view.scenario;
    return view.exact === true && view.state.weights === this.own && view.state.ev === d.ev && view.state.buffs === d.buffs && s.race === d.race && s.role === d.role && s.tier === d.tier && s.setup === d.setup;
  }

  /** The stats of an item at a tier: the shard's own, else those of another shard that lists the item, else nothing. */
  statsOf(item, tier) {
    return item.stats?.[tier] ?? this.statIndex.get(item.key)?.[tier] ?? null;
  }

  /** Keep the stats the shard carries, for the items an answer of the optimizer names (its own items have none). */
  indexStats(shard) {
    for (const item of shard.items) {
      if (item.stats) this.statIndex.set(item.key, { ...this.statIndex.get(item.key), ...item.stats });
    }
  }

  /** The panel of each row: the stats of the item at the tier shown and, for the view the page was built with, its why line; any other view has the note instead. */
  paintDetails(scenario, baked) {
    const note = this.q("#why-note");
    this.rows.forEach((row, index) => {
      const panel = field(row, "more");
      if (!panel) return;
      const item = scenario.kit[index] ?? null;
      const stats = field(panel, "stats");
      const why = field(panel, "why");
      let text = "";
      if (item) {
        const known = baked ? this.bakedKit[index].stats : this.statsOf(item, scenario.tier);
        text = known ?? (this.itemHref(item.key) !== null ? STATS_ON_PAGE : STATS_MISSING);
      }
      if (stats) stats.textContent = text;
      if (why) {
        const kept = baked && item ? this.bakedKit[index].why : null;
        why.textContent = kept ?? "";
        why.hidden = kept === null || kept === "";
      }
      panel.hidden = !item; // (a place left empty has nothing to open)
      if (item) this.labelToggle(index, item.name, baked && why !== null && !why.hidden);
    });
    this.toggleAll?.setAttribute("aria-expanded", String(this.allOpen()));
    if (note) note.hidden = baked;
  }

  // ---- the Upgrade section: its code comes with the first use ---------------------------------------------------------------------------------

  /**
   * The controls of the section that wait for this code are enabled (the page is made with them off: without script there is nothing behind them), and the first focus, click or
   * file on the section loads its code. A file that comes before the code does is kept (the last one), and the code is given it. The browser would open a file dropped on a page in
   * place of the page, so a drag of a file is taken here, from the first moment and for good, whatever happens to the code of the section: it is always cancelled, so that no file
   * dropped on the page can open in place of it (the gear entered would be lost, and the name of the file, which the game gives after the character and the server, would be in the
   * address and the history). Over the section the drop effect is the section's to set; anywhere else it is none. A drag of text or a link is left alone.
   */
  bindUpgrade() {
    const refuse = (event) => {
      const transfer = event.dataTransfer;
      if (!transfer || !Array.from(transfer.types ?? []).includes("Files")) return;
      event.preventDefault(); // (the section does too, but its handlers may be gone, or never have been made)
      const target = event.target;
      if (target && typeof target.closest === "function" && target.closest("#upgrade") !== null) return; // over the section the effect is the section's
      try {
        transfer.dropEffect = "none";
      } catch {
        // a transfer that cannot say what it will do is refused all the same
      }
    };
    const view = this.doc.defaultView ?? this.win; // (the window of the page: `win` may be a stand-in that only has an address and a history)
    view.addEventListener("dragover", refuse);
    view.addEventListener("drop", refuse);
    const section = this.q("#upgrade");
    if (!section) return;
    for (const control of section.querySelectorAll("[data-wake]")) control.disabled = false;
    const files = [];
    const onEvent = (event) => {
      const transfer = event.dataTransfer;
      const target = event.target;
      if (event.type === "dragenter" || event.type === "dragover" || event.type === "drop") {
        if (!transfer || !Array.from(transfer.types ?? []).includes("Files")) return; // text or a link dragged over the section: none of its business
        event.preventDefault();
        if (event.type === "drop" && transfer.files.length > 0) files.splice(0, files.length, ...transfer.files);
      } else {
        const control = target && typeof target.closest === "function" ? target.closest(UPGRADE_CONTROLS) : null;
        if (control === null || control.closest("#upgrade-load") !== null) return; // a click on the words of the section is not a use of it, nor is the button of its message (it has its own go)
        if (event.type === "change" && target.type === "file" && target.files.length > 0) {
          files.splice(0, files.length, ...target.files);
          target.value = "";
        }
      }
      this.wakeUpgrade(section, onEvent, files);
    };
    for (const type of UPGRADE_EVENTS) section.addEventListener(type, onEvent, true);
    // a kit to show and gear to restore do not wait for a first use of the section; nothing else is loaded for a page that has neither
    this.stored = this.readStoredGear();
    if (this.kit.payload !== null || this.stored !== null) this.wakeUpgrade(section, onEvent, files);
  }

  /** What the device holds of the remembered gear, or null: one read, guarded (the device may be missing, blocked or full). */
  readStoredGear() {
    try {
      return getStorage(this.win)?.getItem(GEAR_KEY) ?? null;
    } catch {
      return null;
    }
  }

  wakeUpgrade(section, onEvent, files) {
    if (this.waking || this.upgrade !== null) return;
    this.waking = true;
    const line = this.q("#upgrade-load");
    this.track(
      this.loadUpgrade()
        .then((module) => {
          this.setStatus("", undefined, undefined, line, "#upgrade-h"); // the message of an earlier use is cleared; the focus, if it was on its button, goes to the heading of the section
          this.upgrade = module.initUpgrade(section, {
            doc: this.doc,
            win: this.win,
            fetch: this.fetchJson,
            release: this.release,
            files: files.slice(),
            onUpdated: () => this.dataUpdated(),
            reload: () => this.reload(),
            announce: (text) => this.announce(text),
            track: (promise) => this.track(promise),
            loadEngine: this.loadEngine,
            kit: this.kit.payload === null ? null : this.kit,
            remember: { key: GEAR_KEY, storage: getStorage(this.win), stored: this.stored },
            valueView: () => this.valueView(),
            onEquipKit: (kit) => this.setEquipKit(kit),
            // the panel of the kit is code of a chunk of its own: when it cannot be had, the page says so at the top, where the kit would be shown
            onKitFailed: () => this.setStatus(KIT_NOT_LOADED, () => this.reload(), "Reload"),
            // the view the page shows, not the state of the switches (a view that could not be loaded is not shown); its setup is the one shown, never none
            view: () => ({ race: this.displayed.race, role: this.displayed.role, buffs: this.displayed.buffs, evidence: this.displayed.ev, setup: this.displayed.setup, weights: this.weightsTable(this.displayed.weights) }),
            onView: (callback) => {
              this.viewWatchers.add(callback);
              return () => this.viewWatchers.delete(callback);
            },
            words: {
              tierLabel,
              arrivalText,
              reachText,
              fmtInt,
              fmtSigned,
              displayInt,
              emptyName: EMPTY_NAME,
              slotLabel: (index) => this.slotLabel(index),
              raceName: (code) => this.raceName(code),
              viewText: () => this.viewText(),
              setupText: (code) => this.setupPhrase(code),
            },
          });
          // handed over: the section has its own handlers now. A start that fails leaves these where they are, so that a file given afterwards is still kept for the next use
          for (const type of UPGRADE_EVENTS) section.removeEventListener(type, onEvent, true);
          this.told = false;
          return this.upgrade.ready();
        })
        .catch(() => {
          // the code could not be fetched (or would not start). The next use of a control tries again, silently (a browser that does not keep a failed fetch then has the section), but
          // the visitor is told once, with the one thing that always works: a reload
          this.waking = false;
          this.sayUpgrade(NOT_LOADED_UPGRADE, !this.told);
          this.told = true;
          // a shared kit is shown at the top of the page, and the section's own line is far from it
          if (this.kit.payload !== null) this.setStatus(KIT_NOT_LOADED, () => this.reload(), "Reload");
        }),
    );
  }

  /** A message in the line of the Upgrade section, near its controls (the status at the top of the page is far from them), with a Reload button, and said to a screen reader as well. */
  sayUpgrade(text, speak = true) {
    this.setStatus(text, () => this.reload(), "Reload", this.q("#upgrade-load"), "#upgrade-h");
    if (speak) this.announce(text);
  }

  /** On a narrow screen the switches are folded away behind a line that says what is shown; the Change button opens them. */
  bindChange() {
    const button = this.q("#switches-toggle");
    const panel = this.q("#switches");
    if (!button || !panel) return;
    button.disabled = false; // the line is in the page from the start, with the button drawn invisible; there is something to open once this code runs
    this.q("#view-bar")?.setAttribute("data-ready", ""); // a browser that does not know the scripting media query shows the line by this mark
    button.addEventListener("click", () => {
      const open = !panel.hasAttribute("data-open");
      panel.toggleAttribute("data-open", open);
      button.setAttribute("aria-expanded", String(open));
    });
  }

  /** The sliders are drawn by their chunk, which comes the first time the Weights assumption is opened. */
  bindWeights() {
    const details = this.q("#assume-weights");
    if (details) details.addEventListener("toggle", () => details.open && this.wakeWeights());
  }

  /**
   * Load the chunk of the sliders and the answers for the settings the shards lack, once. A browser keeps a failed module fetch until the page is reloaded, so the visitor is told with
   * a Reload button; the next use tries again all the same (a browser that does not keep it then has the code). Resolves to what the chunk made, or null.
   */
  wakeWeights() {
    if (this.weights !== null) return Promise.resolve(this.weights);
    this.wakingWeights ??= this.loadWeights()
      .then((module) => {
        this.weights = module.initWeights(this, { fmtInt, displayInt });
        if (this.q("#status .status-text")?.textContent.startsWith(NOT_LOADED_WEIGHTS)) this.setStatus(""); // (the sentence, and what the table shows after it)
        this.paintAssumptions(this.displayed); // the words for the sliders are the chunk's: the lines that say them are drawn again
        if (this.shown && !this.shown.exact) this.weights.settle(this.shown, this.lastKind); // what the page shows is worked out now, whenever the code came
        return this.weights;
      })
      .catch(() => {
        this.wakingWeights = null;
        // the table then shows the shards' answer nearest to the choice (the common group buffs for the raid), and the line says so
        const view = this.shown;
        const standIn = view && !view.exact ? ` The table shows the precomputed answer for ${this.nearest(view.state.buffs)}, not for your settings.` : "";
        this.setStatus(NOT_LOADED_WEIGHTS + standIn, () => this.reload(), "Reload");
        return null;
      });
    this.track(this.wakingWeights);
    return this.wakingWeights;
  }

  /** Tell the chunk, if it is there or is needed, which view the page shows now, and the switch whose change the answer is announced with. */
  settle(view, kind) {
    if (this.weights !== null) {
      this.weights.settle(view, kind);
      return;
    }
    if (!view.exact) this.wakeWeights(); // (the code settles the view that is shown when it comes)
  }

  /** The data was published again since the page was made. */
  dataUpdated() {
    this.setStatus(UPDATED, () => this.reload(), "Reload");
  }

  track(promise) {
    this.pending.add(promise);
    const done = () => this.pending.delete(promise);
    promise.then(done, done);
    return promise;
  }

  /** Resolves when nothing is being loaded or drawn. */
  async whenIdle() {
    while (this.pending.size > 0) await Promise.allSettled([...this.pending]);
  }

  /** Draw the shown view again from the data, extras included. For tests, which compare it with the baked page. */
  async refresh() {
    await this.track(this.apply({ ...this.state }, { force: true }));
    await this.whenIdle();
  }

  onChange(target) {
    this.focusAfterRetry = false; // a new choice of the visitor's own ends the retry
    if (target.name === "buffs" && this.ench) this.ench.disabled = target.value !== "group"; // (the box goes with the group choice at once, not when the view has loaded)
    const kind = target.id === "sw-race" ? "race" : target.id === "sw-tier" ? "tier" : target.id === "buffs-ench" ? "buffs" : target.name; // race, tier, role, setup or buffs
    this.track(this.apply(this.desired(target.name === "setup" ? target.value : this.wantedSetup), { url: true, announce: kind }));
  }

  /** What the controls ask for: the switches as they are, the setup as given (null is the role's best) and the sliders as the visitor last left them. */
  desired(setup) {
    return {
      race: this.q("#sw-race").value,
      role: this.checkedValue("role"),
      tier: Number(this.q("#sw-tier").value),
      ev: this.state.ev,
      buffs: this.buffsValue(),
      setup,
      weights: this.wantedWeights,
    };
  }

  // ---- loading ------------------------------------------------------------------------------------------------------------

  loadJson(url) {
    return this.fetchJson(url, { credentials: "same-origin" }).then((response) => {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    });
  }

  /** A file that is made for another release than the page's is refused (a file that is no data file at all failed to parse before this). */
  sameRelease(parsed) {
    if (this.release !== null && parsed.release !== this.release) throw new DataUpdated();
    return parsed;
  }

  loadShard(evidence, buffs) {
    const key = evidence + "-" + buffs;
    if (!this.shards.has(key)) {
      const promise = this.loadJson(this.base + key + ".json")
        .then(parseShard)
        .then((shard) => {
          this.sameRelease(shard);
          this.indexStats(shard);
          return shard;
        });
      promise.catch(() => {
        if (this.shards.get(key) === promise) this.shards.delete(key);
      });
      this.shards.set(key, promise);
    }
    return this.shards.get(key);
  }

  loadExtra(key, path, parse) {
    if (!this.extraData.has(key)) {
      const promise = this.loadJson(this.base + path + ".json").then(parse).then((parsed) => this.sameRelease(parsed));
      promise.catch(() => {
        if (this.extraData.get(key) === promise) this.extraData.delete(key);
      });
      this.extraData.set(key, promise);
    }
    return this.extraData.get(key);
  }

  /** The runner-ups file of a role (every tier of the run is in it, so it is fetched once and the tier is read from it), or null when there is none. */
  async loadRunnerups(role) {
    if (!this.runnerupFiles.has(role)) return null;
    return this.loadExtra("runnerups/" + role, "runnerups/" + role, parseRunnerups);
  }

  // ---- the work -----------------------------------------------------------------------------------------------------------

  async apply(desired, { url = false, announce = false, force = false, notice = null } = {}) {
    const token = ++this.token;
    this.applying = token; // an answer of the optimizer for the view that is leaving is not drawn from here until this view is shown (or could not be)
    this.wantedSetup = desired.setup;
    this.wantedWeights = desired.weights;
    // the shards have the own buffs and the common group buffs: the other buff sets are shown with the shard of the group until the optimizer's answer takes its place
    const buffs = desired.buffs === "own" ? "own" : "group";
    let shard;
    try {
      // a retry keeps its button (and the focus on it) while the view loads again
      if (!this.shards.has(desired.ev + "-" + buffs)) this.setStatus("Loading this view…", this.focusAfterRetry ? this.retries.get(this.q("#status")) : undefined);
      shard = await this.loadShard(desired.ev, buffs);
    } catch (error) {
      if (token === this.token) this.fail(desired, { url, announce, force, notice }, error);
      return;
    }
    if (token !== this.token) return;
    const view = this.resolve(shard, desired);
    if (!view) {
      this.fail(desired, { url, announce, force, notice });
      return;
    }
    this.paint(view);
    this.state = view.state;
    this.wantedSetup = view.state.setup;
    this.wantedWeights = view.state.weights;
    this.lastKind = announce;
    this.setStatus([view.notice, notice].filter(Boolean).join(" "));
    this.updateReport(view);
    if (url) this.writeUrl(view);
    if (announce && view.exact) this.say(view, announce); // (the answer of the optimizer is announced when it is there)
    if (this.focusAfterRetry) {
      // the Try again button is gone now: the focus goes to the answer, a place that is always there
      this.focusAfterRetry = false;
      this.q("#wear-h")?.focus();
    }
    this.renderExtras(force);
    this.applying = 0;
    this.settle(view, announce);
  }

  /** Turn what was asked for into a scenario that exists. A setup the role does not have falls back to its best; so does a setup that is the best. */
  resolve(shard, desired) {
    const d = this.config.defaults;
    const pick = (set, wanted, fallback) => (set.has(wanted) ? wanted : set.has(fallback) ? fallback : [...set][0]);
    const race = pick(shard.races, desired.race, d.race);
    const role = pick(shard.roles, desired.role, d.role);
    const tier = pick(shard.tiers, desired.tier, d.tier);
    const offered = shard.setupsFor(role);
    const best = shard.bestSetup(race, role, tier);
    let setup = desired.setup;
    let notice = null;
    if (setup !== null && !offered.includes(setup)) {
      notice = this.setupLabel(setup) + " is not available for this role. Showing its best setup instead: " + this.setupLabel(best) + ".";
      setup = null;
    } else if (setup === best) setup = null; // choosing the best, or naming it in the address, is following it
    const scenario = shard.scenario(race, role, tier, setup ?? best);
    if (!scenario) return null;
    const state = { race, role, tier, ev: desired.ev, buffs: desired.buffs, setup, weights: desired.weights };
    return { shard, scenario, best, offered, notice, state, exact: this.isPrecomputed(state) };
  }

  setupLabel(code) {
    return this.config.setups.find((s) => s.code === code)?.label ?? code;
  }

  fail(desired, options, error) {
    this.wantedSetup = this.state.setup;
    this.wantedWeights = this.state.weights;
    this.setControls(this.displayed);
    this.applying = 0;
    this.weights?.release(); // (an answer for the view still shown that waited for this one is drawn now)
    if (error instanceof DataUpdated) {
      // the same file would come again: the way out is the page that goes with the data
      this.setStatus(UPDATED + " " + this.revertNote(desired), () => this.reload(), "Reload");
      return;
    }
    this.setStatus(NOT_LOADED + " " + this.revertNote(desired), () => {
      this.focusAfterRetry = true;
      this.track(this.apply(desired, options));
    });
  }

  /** Why the switches look as they did before: what the visitor changed went back, and what the page still shows. */
  revertNote(desired) {
    const shown = this.displayed;
    const changes = [];
    if (desired.race !== shown.race) changes.push(["race", "is", this.raceName(shown.race)]);
    if (desired.role !== shown.role) changes.push(["role", "is", this.roleLabel(shown.role)]);
    if (desired.tier !== shown.tier) changes.push(["tier", "is", tierLabel(shown.tier)]);
    if (desired.setup !== null && desired.setup !== shown.setup) changes.push(["weapons", "are", this.setupLabel(shown.setup)]);
    if (desired.buffs !== shown.buffs) changes.push(["buffs", "are", this.buffsPhrase(shown.buffs)]);
    if (desired.weights !== shown.weights) changes.push(["weights", "are", this.weightsText(shown.weights)]);
    if (changes.length === 1) return "The " + changes[0][0] + " " + changes[0][1] + " back at " + changes[0][2] + ".";
    return "Still showing " + this.summaryOf(shown) + ".";
  }

  summaryOf(shown) {
    return this.raceName(shown.race) + ", " + this.roleLabel(shown.role) + ", " + tierLabel(shown.tier) + ", " + this.setupLabel(shown.setup);
  }

  // ---- writing to the page --------------------------------------------------------------------------------------------------

  /**
   * The message of #status (or of the line `status` that is given, with `home` the selector of the heading the focus goes to), with a Try again button (or another, named by
   * `label`) when there is something to try. The button is made once and stays while the message goes on (a retry that fails again must not take it from under the
   * visitor's focus); it goes when the message does, and the focus goes to the answer then. An empty #status is hidden from the eye and not from the accessibility tree.
   */
  setStatus(text, retry, label = "Try again", status = this.q("#status"), home = "#wear-h") {
    if (!status) return;
    let words = status.querySelector(".status-text");
    let button = status.querySelector("button");
    if (text) {
      if (!words) {
        words = this.doc.createElement("span");
        words.className = "status-text";
        status.prepend(words);
      }
      words.textContent = text;
    } else if (words) words.remove();
    if (retry) {
      this.retries.set(status, retry);
      if (!button) {
        button = this.doc.createElement("button");
        button.setAttribute("type", "button");
        button.className = "btn";
        button.addEventListener("click", () => this.retries.get(status)?.());
        status.append(button);
      }
      button.textContent = label;
    } else if (button) {
      const held = this.doc.activeElement === button;
      button.remove();
      if (held) this.q(home)?.focus();
    }
    status.classList.toggle("quiet", !text && !retry);
  }

  /** Say something to a visitor who cannot see the page. */
  announce(text) {
    const live = this.q("#announce");
    if (live) live.textContent = text;
  }

  /**
   * Tell a visitor who cannot see the page what a change of a switch did: which switch, what is shown now, and what it is worth. The answer of the optimizer (`solved`: its kit value) says so,
   * and is told once, when it is there.
   */
  say(view, kind, solved = null) {
    const node = this.q("#announce");
    if (!node) return;
    const s = view.scenario;
    const lead = {
      race: "Race " + this.raceName(s.race),
      role: "Role " + this.roleLabel(s.role),
      tier: "Tier " + tierLabel(s.tier),
      setup: "Weapons " + this.setupLabel(s.setup),
      buffs: "Buffs " + this.buffsPhrase(view.state.buffs),
      weights: "Weights " + this.weightsText(view.state.weights),
      back: "Back at the precomputed answer",
    }[kind];
    const value = solved === null ? s.value : solved.value;
    node.textContent =
      (lead ? lead + ". " : "") +
      (solved === null ? "" : "Solved for your settings. ") +
      "Showing " +
      this.summaryOf({ race: s.race, role: s.role, tier: s.tier, setup: s.setup }) +
      ". Kit value " +
      fmtInt(displayInt(value)) +
      ".";
  }

  raceName(code) {
    return this.config.races.find((r) => r.code === code)?.name ?? code;
  }

  roleLabel(code) {
    return this.config.roles.find((r) => r.code === code)?.label ?? code;
  }

  /** The address of the view. The weapon setup is in it only if the visitor chose one: the role's best is not a choice, and writing it
   * down would turn it into one on the next visit. The address holds only the page's own parameters (that is its canonical form), so a
   * parameter that belongs to someone else, a campaign tag say, is dropped when it is written; the fragment (`#...`) is the visitor's own
   * and stays. */
  writeUrl(view) {
    const state = view.state;
    const params = new URLSearchParams({ race: state.race, role: state.role, tier: String(state.tier) });
    if (state.setup !== null) params.set("setup", state.setup);
    params.set("buffs", this.buffsWord(state.buffs));
    if (state.weights !== this.own) params.set("w", state.weights); // (the sliders; with every one at x1 it is the role's own, which is not written)
    try {
      // the entry keeps the state it has: something else may hold a state there (a link to a kit), and rewriting the address is not the place to drop it
      this.win.history.replaceState(this.win.history.state, "", "?" + params.toString() + this.win.location.hash);
    } catch {
      // a sandboxed frame may refuse; the page itself is right either way
    }
  }

  /** The link of the footer that reports a problem names the answer that the table shows, so that a report can be looked at as it was seen: the precomputed answer nearest to the settings
   * (the own buffs or the common group buffs, the role's own weights) until the answer of the optimizer for the settings is drawn, and the settings then (`solved`). The build writes
   * it for the view the page opens on; here its `page` (the address of the page, with the view as the query) follows what is shown. (The address of the page itself names the settings
   * the visitor asked for, so that a reload works them out again.) */
  updateReport(view, solved = false) {
    const link = this.doc.getElementById("report-link");
    if (!link || this.reportBase === null) return;
    let url;
    let page;
    try {
      url = new URL(this.reportBase);
      page = new URL(url.searchParams.get("page"));
    } catch {
      return; // not an address: left as the build wrote it
    }
    const s = view.scenario;
    const shown = view.exact || solved; // (else the table shows the shard of the nearest settings)
    const buffs = shown || view.state.buffs === "own" ? view.state.buffs : "group";
    const asked = { race: s.race, role: s.role, tier: String(s.tier), setup: s.setup, buffs: this.buffsWord(buffs) };
    if (shown && view.state.weights !== this.own) asked.w = view.state.weights;
    page.search = new URLSearchParams(asked).toString();
    url.searchParams.set("page", page.href);
    link.setAttribute("href", url.href);
  }

  /** Put the switches in the state the page shows. */
  setControls(shown) {
    this.q("#sw-race").value = shown.race;
    this.q("#sw-tier").value = String(shown.tier);
    for (const radio of this.radios("role")) radio.checked = radio.value === shown.role;
    // the Enchanter is a box under the group choice: it goes with the group, and keeps what the visitor left in it while the own buffs or the raid are chosen
    const chosen = shown.buffs === ENCHANTER ? "group" : shown.buffs;
    for (const radio of this.radios("buffs")) radio.checked = radio.value === chosen;
    if (this.ench) {
      if (chosen === "group") this.ench.checked = shown.buffs === ENCHANTER;
      this.ench.disabled = chosen !== "group";
    }
    this.weights?.sync(shown.weights);
    for (const radio of this.radios("setup")) {
      const offered = shown.offered.includes(radio.value);
      const wrapper = radio.closest(".opt");
      radio.hidden = !offered;
      radio.disabled = !offered;
      if (wrapper) wrapper.hidden = !offered;
      radio.checked = radio.value === shown.setup;
      const flag = wrapper?.querySelector(".best-flag");
      if (flag) flag.hidden = !(offered && radio.value === shown.best);
    }
    // an arrow key moves the focus with the choice; when the choice goes back the focus goes back with it, not left on a button
    // that is no longer the one that is on
    const held = this.doc.activeElement;
    if (held && typeof held.matches === "function" && held.matches('input[type="radio"]') && !held.checked) {
      this.radios(held.name).find((radio) => radio.checked && !radio.disabled)?.focus();
    }
  }

  paint(view) {
    const s = view.scenario;
    const state = view.state;
    this.displayed = { race: s.race, role: s.role, tier: s.tier, ev: state.ev, buffs: state.buffs, weights: state.weights, setup: s.setup, best: view.best, offered: view.offered };
    this.setControls(this.displayed);
    this.shown = view;
    this.root.classList.remove("solved"); // (the kit of the shard is drawn: an answer of the optimizer is drawn again when it is there)

    setField(this.root, "v-race", this.raceName(s.race));
    setField(this.root, "v-role", this.roleLabel(s.role));
    setField(this.root, "v-tier", tierLabel(s.tier));
    setField(this.root, "v-setup", this.setupLabel(s.setup));
    const hint = this.q("#role-hint");
    if (hint) hint.textContent = this.config.roles.find((r) => r.code === s.role)?.hint ?? "";
    setField(this.root, "assume-haste", s.hasteAssumed + "%");
    setField(this.root, "s-race", this.raceName(s.race));
    setField(this.root, "s-role", this.roleLabel(s.role));
    setField(this.root, "s-tier", tierLabel(s.tier));
    this.paintAssumptions(this.displayed);

    this.paintKit(s, this.isBaked(view));
    this.setExaltView(s, view.exact === true && s.setup === view.best);
    this.paintTotals(s);
    this.paintWeapons(view);
    for (const watcher of [...this.viewWatchers]) {
      try {
        watcher();
      } catch {
        // a bug in the Upgrade section is the section's, not the view's
      }
    }
  }

  /** The lines that say what is assumed: the buffs, the weapons and the weights, in the Assumes panel and in the line of the switches. */
  paintAssumptions(shown) {
    const phrase = (list, code) => list.find((entry) => entry.code === code)?.phrase ?? code;
    const weights = this.weightsText(shown.weights);
    setField(this.root, "assume-buffs", this.buffsPhrase(shown.buffs));
    setField(this.root, "assume-setup", phrase(this.config.setups, shown.setup));
    setField(this.root, "assume-weights", weights);
    const line = [phrase(this.config.setups, shown.setup), this.buffsPhrase(shown.buffs)];
    if (shown.weights !== this.own) line.push(weights);
    setField(this.root, "s-assumes", line.join(", "));
  }

  /**
   * The answer of the optimizer, in the rows of Wear this in place of the shard's kit (`items`: the shard's own shape, a kit of 22 places at the tier of the view), and said once. What the shard
   * says of its kit and the page cannot work out for this one (the totals and the weapon setups) is out of sight; the haste the weapons were scored at is the answer's. The answer is for the view
   * the page shows (the chunk keeps one that is for another from getting here), and not while another view is loading: then the page still shows the view the answer is for, but a visitor who
   * has just chosen another would see the kit of the one they left under their choice. It says whether it drew; the chunk keeps an answer that was not drawn until the page has a view.
   */
  drawSolved({ items, tier, hasteAssumed, value, kind }) {
    if (this.applying !== 0) return false;
    this.paintKit({ kit: items, tier }, false);
    this.setExaltView({ kit: items, tier }, false);
    setField(this.root, "assume-haste", hasteAssumed + "%");
    this.root.classList.add("solved");
    if (this.shown) {
      this.updateReport(this.shown, true);
      this.say(this.shown, kind, { value });
    }
    return true;
  }

  /** The address of the page of an item, or null: only where the page says its items have pages, and only for a key that is an item key. */
  itemHref(key) {
    return this.linkItems && typeof key === "string" && ITEM_KEY.test(key) ? ITEM_BASE + key + "/" : null;
  }

  paintKit(scenario, baked = false) {
    this.rows.forEach((row, index) => {
      const item = scenario.kit[index] ?? null;
      if (!item) {
        setName(row, EMPTY_NAME, null);
        setField(row, "deity", "");
        for (const name of ["tier", "arrival", "source"]) setField(row, name, DASH);
        setField(row, "reach", "");
      } else {
        setName(row, item.name, this.itemHref(item.key));
        setField(row, "deity", deityText(item.deity));
        setField(row, "tier", tierLabel(scenario.tier));
        setField(row, "arrival", arrivalText(item.arrival));
        setField(row, "reach", reachText(item.arrival, scenario.tier));
        setField(row, "source", item.source);
      }
      const deity = field(row, "deity");
      if (deity) deity.hidden = !(item && item.deity.length > 0);
    });
    this.paintDetails(scenario, baked);
  }

  paintTotals(scenario) {
    const t = scenario.totals;
    const text = {
      "t-ac": fmtInt(t.ac),
      "t-hp": fmtInt(t.hp),
      "t-mana": fmtInt(t.mana),
      "t-end": fmtInt(t.end),
      "t-haste": t.haste + "%",
      "t-atk": fmtInt(t.atk),
      "t-mr": fmtInt(t.mr),
      "t-fr": fmtInt(t.fr),
      "t-cr": fmtInt(t.cr),
      "t-dr": fmtInt(t.dr),
      "t-pr": fmtInt(t.pr),
      "t-hpreg": fmtInt(t.hpreg),
      "t-manareg": fmtInt(t.manareg),
      "t-endreg": fmtInt(t.endreg),
    };
    for (const [name, value] of Object.entries(text)) setField(this.root, name, value);
    const value = this.q("#kit-value");
    if (value) value.textContent = fmtInt(displayInt(scenario.value));
    const gain = this.q("#kit-gain");
    if (gain) gain.textContent = fmtSigned(displayInt(scenario.gain));
  }

  paintWeapons(view) {
    const s = view.scenario;
    const [main, off] = [s.kit[20], s.kit[21]];
    setField(this.root, "w-setup", this.setupLabel(s.setup));
    setField(this.root, "w-haste", s.hasteAssumed + "%");
    setField(this.root, "w-main", main ? main.name : "Empty");
    setField(this.root, "w-off", off ? off.name : "Empty");
    const list = this.q("#w-others");
    if (!list) return;
    list.replaceChildren();
    for (const setup of view.offered) {
      if (setup === s.setup) continue;
      const other = view.shard.scenario(s.race, s.role, s.tier, setup);
      if (!other) continue;
      const [m, o] = [other.kit[20], other.kit[21]];
      const pair = (m ? m.name : "nothing") + (o ? " + " + o.name : "");
      const li = this.doc.createElement("li");
      li.textContent = this.setupLabel(setup) + ": " + pair + " (" + fmtSigned(displayInt(other.value - s.value)) + ")";
      list.append(li);
    }
    const box = this.q("#other-setups");
    if (box) box.hidden = list.children.length === 0;
  }

  // ---- runner-ups and the robust core: fetched when opened ----------------------------------------------------------------------

  renderExtras(force) {
    for (const name of EXTRAS) {
      const details = this.q("#" + name);
      if (!details) continue;
      if (force || details.open) this.track(this.fillExtra(name));
      else this.dirty[name] = true;
    }
  }

  /** What an expander shows, by the nodes that hold it. */
  extraNodes(name) {
    const ids = name === "runnerups" ? ["runnerups-table", "runnerups-na"] : ["robust-summary", "robust-list", "robust-na"];
    return ids.map((id) => this.q("#" + id)).filter(Boolean);
  }

  /** The runner-ups and the robust core describe the view they were made for. While the file for another view comes, what they show is
   * not that view's, so it is taken off the page and a note says that it is coming (the expander is marked busy meanwhile). */
  markLoading(name) {
    const details = this.q("#" + name);
    const note = this.q("#" + name + "-loading");
    if (!details || !note) return;
    for (const node of this.extraNodes(name)) node.hidden = true;
    note.hidden = false;
    details.setAttribute("aria-busy", "true");
  }

  doneLoading(name) {
    const note = this.q("#" + name + "-loading");
    if (note) note.hidden = true;
    this.q("#" + name)?.removeAttribute("aria-busy");
  }

  async fillExtra(name) {
    const view = this.shown;
    this.dirty[name] = false;
    this.markLoading(name);
    try {
      if (name === "runnerups") {
        // runner-ups exist for the default assumptions only: the buffs the page started with and the role's best setup
        const s = view.scenario;
        const d = this.config.defaults;
        const standard = view.exact && view.state.ev === d.ev && view.state.buffs === d.buffs && s.setup === view.best;
        const data = standard ? await this.loadRunnerups(s.role) : null;
        if (view !== this.shown) return;
        const found = data ? data.view(s.tier, s.race) : null;
        this.doneLoading(name);
        this.paintRunnerups(found && found.setup === s.setup ? found : null, data);
      } else {
        const data = await this.loadExtra("robust", "robust", parseRobust);
        if (view !== this.shown) return;
        const s = view.scenario;
        // the seals describe the kit of the view they were made for (the race, the weapon setup, the evidence level and the buffs):
        // for any other view they would describe a kit that is not shown
        const sealed = data.race === s.race ? data.view(s.role, s.tier) : null;
        const same = view.exact && sealed !== null && sealed.setup === s.setup && sealed.ev === view.state.ev && sealed.buffs === view.state.buffs;
        this.doneLoading(name);
        this.paintRobust(same ? sealed.labels : null, s, sealed);
      }
    } catch (error) {
      // a failure that comes after the visitor has moved on belongs to a view that is no longer shown (the success paths above say the
      // same): the shown view's section is the business of the fill that was started for it
      if (view !== this.shown) return;
      this.dirty[name] = true;
      this.extraFailed(name, error);
    }
  }

  extraFailed(name, error) {
    this.doneLoading(name);
    const na = this.q("#" + name + "-na");
    if (!na) return;
    na.textContent = error instanceof DataUpdated ? SECTION_UPDATED : "Couldn't load this section; close it and open it again to try again.";
    na.hidden = false;
    for (const id of name === "runnerups" ? ["runnerups-table"] : ["robust-summary", "robust-list"]) {
      const node = this.q("#" + id);
      if (node) node.hidden = true;
    }
  }

  restoreNote(name) {
    const na = this.q("#" + name + "-na");
    if (na && na.dataset.original) na.textContent = na.dataset.original;
  }

  paintRunnerups(view, data) {
    const na = this.q("#runnerups-na");
    const table = this.q("#runnerups-table");
    this.restoreNote("runnerups");
    if (!view) {
      if (na) na.hidden = false;
      if (table) table.hidden = true;
      return;
    }
    if (na) na.hidden = true;
    if (table) table.hidden = false;
    this.root.querySelectorAll("#runnerups-body tr").forEach((row, index) => {
      const list = field(row, "swaps");
      list.replaceChildren();
      const swaps = view.slots[index] ?? [];
      for (const [itemIndex, delta] of swaps) {
        const item = data.items[itemIndex];
        const li = this.doc.createElement("li");
        li.append(this.span("r-name", item.name), this.doc.createTextNode(" "), this.span("r-delta", fmtSigned(displayInt(delta)), "delta"));
        if (item.deity.length > 0) li.append(this.doc.createTextNode(" "), this.span("r-deity", deityText(item.deity), "deity"));
        list.append(li);
      }
      list.hidden = swaps.length === 0;
      const none = field(row, "r-none");
      if (none) none.hidden = swaps.length !== 0;
    });
  }

  span(name, text, className) {
    const node = this.doc.createElement("span");
    node.setAttribute("data-f", name);
    if (className) node.className = className;
    node.textContent = text;
    return node;
  }

  paintRobust(labels, scenario, sealed) {
    const summary = this.q("#robust-summary");
    const list = this.q("#robust-list");
    const na = this.q("#robust-na");
    this.restoreNote("robust");
    if (!labels) {
      if (summary) summary.hidden = true;
      if (list) list.hidden = true;
      if (na) {
        // seals exist for this race, role and tier but for other assumptions: say which, so the visitor can go back to them
        if (sealed) na.textContent = this.notComputed(sealed);
        na.hidden = false;
      }
      return;
    }
    const depending = labels.map((label, index) => [index, label]).filter(([, label]) => label !== "robust");
    const held = labels.length - depending.length;
    let sentence;
    if (depending.length === 0) sentence = "All " + labels.length + " picks hold in every check.";
    else
      sentence =
        held + " of " + labels.length + " picks hold in every check. The other " + depending.length + (depending.length === 1 ? " depends" : " depend") + " on an assumption:";
    if (summary) {
      summary.textContent = sentence;
      summary.hidden = false;
    }
    if (list) {
      list.replaceChildren();
      for (const [index, label] of depending) {
        const item = scenario.kit[index];
        const li = this.doc.createElement("li");
        li.textContent = this.slotLabel(index) + ": " + (item ? item.name : "empty") + " " + EN_DASH + " " + label;
        list.append(li);
      }
      list.hidden = depending.length === 0;
    }
    if (na) na.hidden = true;
  }

  /** The note for a view whose assumptions are not the ones the seals were made for. */
  notComputed(sealed) {
    const phrase = (list, code) => list.find((entry) => entry.code === code)?.phrase ?? code;
    const made = [phrase(this.config.setups, sealed.setup), this.buffsPhrase(sealed.buffs)];
    return "Not computed for this view. The checks were made with " + made.join(", ") + " and the role's own weights. Change the assumptions back to see them.";
  }

  slotLabel(index) {
    return this.rows[index]?.querySelector("th")?.textContent ?? "";
  }

  /** The view the page shows, as a kit that came in a link is valued under it: the role, the buffs and the evidence level. Not the weapons and not the haste: the kit's hands and items give those. */
  valueView() {
    const shown = this.displayed;
    return { role: shown.role, buffs: shown.buffs, evidence: shown.ev };
  }

  /** The view in words, without the race (a kit has its own) and without the weapons (nor): the role, then the buffs, as the line under the title of the page says them. */
  viewText() {
    return this.roleLabel(this.displayed.role) + ", " + this.buffsPhrase(this.displayed.buffs);
  }

  /** A weapon setup in the page's words ("dual wield", "two-hander"), or nothing when the page has no such weapon setup among its switches (the section has words of its own for it). */
  setupPhrase(code) {
    return this.config.setups.find((s) => s.code === code)?.phrase;
  }
}
