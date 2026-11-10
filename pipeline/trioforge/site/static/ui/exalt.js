// The section Effects to exalt of a trio page, and the hints under Wear this: the code the page loads once it has shown (when the browser is idle), or when the section is opened or scrolled into view, and not in the first load.
//
//   initExalt(section, env) -> {ready(), destroy()}
//
// `section` is the details element #exalt the page is made with (its summary, a short note, a status line and an empty #exalt-body). `env` is what the page script gives it:
//   doc, win, fetch(url, init)            the document and window, and the page's fetch (it asks for nothing but the two files below, and the item list of the site when a plan is re-matched)
//   effectsUrl, exaltUrl, release         the addresses of the two files the section is made from (the shared effects.json and the trio's exalt.json), and the data release the page was built for
//   view()                                the view the page shows: {role, race, tier, exact, kit}. `kit` is the 22 places of the kit drawn in Wear this, `{key, name}` or null for an empty place; `exact` is true when it is the kit
//                                         the files were made for (the default race at the default tier, buffs and weights, the role's best setup)
//   onView(callback)                      says when the kit drawn in Wear this has changed; returns a function that stops it
//   equipKit(), onEquipKit(callback)      the kit of Equip now in the Upgrade section, `{kit: [{key, name, tier} | null], record(key), defaults}`, or null; and when it changes
//   words                                 the page's own words: {slotLabel(index), raceName(code), roleLabel(code), tierLabel(tier), itemHref(key)}
//   announce(text), onUpdated(), reload() a live region, what to do when the files are of another release than the page's, and a reload
//   kitRows()                             the rows of Wear this (22, in the order of the places of a kit): under each one that the plan gives an effect, one short line says which effect to put on
//                                         it and from which donor item (the exalt hints); `view().pending` is true while the kit drawn is a stand-in for one that is being worked out (no line is shown then)
//   background                            true when the page loads the section before the visitor has asked for it: a failure is then not announced while the section is closed
//
// What it shows (the spec of the feature, 2026-10-22): the exalt plan for a kit (which effect to put on which item of the kit), the effects that have no room, the ranked lists (foci, clicks that must
// be equipped, worn effects, procs) with a plain meaning, what a focus touches of the spells of the class that gains most, the tier a socket opens at, the best donor with the others and how hard
// each is to get, and the carry list (the "Any Slot" clicks, which work from a bag and need no socket). It is labelled a planning aid: the scores are a model (the rules `effects.*`), and a row
// built on an assumption has an "unverified" mark that opens its reason.
//
// The lists do not depend on the kit. The plan does: for the kit the files were made for it is the plan in the file; for any other kit (another race, tier, setup or buffs, an answer of the
// optimizer, the kit of Equip now) it is made again in the browser by exalt-plan.js, the port of effects/plan.py that a test holds to Python's plans. The item list of the site (the one the optimizer's
// worker reads, named by engine-manifest.json) is fetched for that, once, only when a plan has to be made again for a kit of Wear this (since the donors are described in effects.json and the
// kit of Equip now brings its own records). With the section closed only the hints under Wear this are made, so that item list is then read when the browser is idle and not in the handler of a
// control; the section's own plan and lists are drawn when it is open.
//
// Everything is text (textContent, never markup). The styles are a constructed stylesheet made here: the section adds nothing to the stylesheet every page loads.

import { PLACES, SLOT_TIER, itemInfo, planKit } from "./exalt-plan.js";

const CLASS_NAMES = {
  WAR: "Warrior", CLR: "Cleric", PAL: "Paladin", RNG: "Ranger", SHD: "Shadow Knight", DRU: "Druid", MNK: "Monk", BRD: "Bard", ROG: "Rogue", SHM: "Shaman",
  NEC: "Necromancer", WIZ: "Wizard", MAG: "Magician", ENC: "Enchanter", BST: "Beastlord", BER: "Berserker",
}; // prettier-ignore
const SLOT_WORDS = { PRIMARY: "main hand", SECONDARY: "off hand", ANY: "any slot", POWERSOURCE: "power source" };
/** How hard a source is to get (effects/donors.py access_cost): the words, and the class of the dot (the dot only decorates the words). */
const ACCESS = { 1: ["Vendor", "a1"], 2: ["Quest or crafted", "a2"], 3: ["Drop", "a3"], 4: ["Raid drop", "a4"] };
const NO_SOURCE = ["No known source", "a9"];
const KIND_HEAD = {
  focus: "Focus effects",
  click: "Clicks you must equip",
  worn: "Worn effects",
  proc: "Procs",
  carry: "Carry list: clicks that work from a bag",
};
const KIND_ONE = { focus: "Focus", click: "Click", worn: "Worn", proc: "Proc", carry: "Carry" };
const FOCUS_WORDS = {
  spell_haste: "faster casts",
  improved_damage: "more spell damage",
  improved_healing: "more healing",
  mana_preservation: "lower mana cost",
  extended_duration: "longer durations",
  extended_range: "longer range",
  reagent_conservation: "fewer reagents used",
  pet_power: "stronger pets",
  instrument_mod: "stronger instrument songs",
}; // prettier-ignore
const UNVERIFIED_WHY = {
  ambiguous: "Several spells have this name, so the numbers are for the one most likely meant.",
  equip: "The wiki does not say whether this click has to be equipped, so it is treated as one that does.",
  inferred: "The wiki gives this effect on a weapon with no word on when it fires, so it is treated as a proc.",
  description: "Players describe this effect differently from the spell data.",
};
const NO_ROOM_WHY = {
  donor: "no copy of it can be worn by a class of the trio",
  primary: "it needs a main-hand item and none in the kit can carry it",
  slot: "no item in the kit shares a slot with the item it comes from",
  class: "no class of the trio that gains from it can use both items",
  tier: "the items of the kit are below the tier its socket opens at",
  taken: "a better effect of its kind has every item that could carry it",
};
const STYLE = `
.exalt-top{margin:.2rem 0 .8rem}
.exalt h3{margin:1.2rem 0 .4rem}
.exalt-source{border:0;padding:0;margin:.4rem 0 .8rem}
.exalt-source legend{font-weight:600;padding:0}
.exalt-source label{display:inline-block;margin:.2rem 1rem .2rem 0;min-height:1.6rem}
.exalt-table{background:var(--win);color:var(--win-text);border:2px solid var(--win-border);box-shadow:inset 0 0 0 1px #000,3px 3px 0 rgba(0,0,0,.4);margin:.4rem 0 .8rem}
.exalt-table caption{padding:.4rem .7rem;border:2px solid var(--win-border);border-bottom:0;background:var(--win);color:var(--win-muted)}
.exalt-table th,.exalt-table td{border-bottom:1px solid var(--win-line);color:var(--win-text)}
.exalt-table thead th{background:var(--win-head);border-bottom:2px solid var(--win-border);color:var(--win-gold);font-size:.8rem;letter-spacing:.06em;text-transform:uppercase}
.exalt-table tbody tr:nth-child(even){background:var(--win-alt)}
.exalt-table a{color:var(--win-link)}
.exalt-table a:visited{color:var(--win-visited)}
.exalt-table :focus-visible{outline-color:var(--frame-focus)}
.exalt-table .muted,.exalt-table .exalt-line{color:var(--win-muted)}
.exalt-table .exalt-name{font-weight:600;color:#fff}
.exalt-line{display:block;font-size:.85rem}
.exalt-slot{display:block;font-size:.85rem;color:var(--win-gold);text-transform:uppercase;letter-spacing:.04em}
.exalt-table th,.exalt-table td{padding:.5rem .55rem}
.exalt-table tbody th{font-weight:400;width:46%}
.exalt-chip{display:inline-block;margin:.15rem .3rem .15rem 0;padding:0 .4rem;border:1px solid var(--win-border);border-radius:.6rem;font-size:.8rem;color:var(--win-text)}
.exalt-mark{font:inherit;font-size:.8rem;margin:.1rem 0 .1rem .3rem;min-height:1.5rem;padding:0 .5rem;border:1px dashed var(--win-gold);border-radius:.6rem;background:transparent;color:var(--win-gold);cursor:pointer}
.exalt-reason{display:block;margin:.2rem 0;font-size:.85rem;color:var(--win-muted)}
.exalt-dot{display:inline-block;width:.7rem;height:.7rem;margin-right:.3rem;border-radius:50%;border:1px solid var(--win-text);vertical-align:baseline}
.exalt-dot.a1{background:#58b368}.exalt-dot.a2{background:#c9a24a}.exalt-dot.a3{background:#d9822b}.exalt-dot.a4{background:#c0392b}.exalt-dot.a9{background:transparent}
.exalt-table details{margin:.3rem 0}
.exalt-table summary{cursor:pointer;color:var(--win-link);min-height:1.5rem}
.exalt-noroom{margin:.4rem 0}
.exalt-ceiling{display:block;font-size:.85rem;color:var(--win-muted)}
.exalt h4{margin:.8rem 0 .3rem}
.exalt-donors{margin:.2rem 0 .8rem;padding-inline-start:1.2rem}
.exalt-donors li{margin:.15rem 0}
.exalt-hints{display:block;margin:.25rem 0 0}
.exalt-hint{display:block;margin:.1rem 0;font-size:.85rem;color:var(--win-muted)}
.exalt-hint-plan{margin-inline-start:.4rem;white-space:nowrap}
.exalt-eff{display:inline}
.exalt-effbtn{font:inherit;color:inherit;background:none;border:0;border-bottom:1px dotted currentColor;border-radius:0;padding:0;min-height:1.5rem;cursor:help;text-align:start}
.exalt-effbtn:focus-visible{outline:2px solid var(--frame-focus);outline-offset:2px}
.exalt-hint .exalt-effbtn{color:var(--win-text)}
.exalt-tip{display:block;margin:.25rem 0;padding:.4rem .6rem;border:1px solid var(--win-border);background:var(--win-head);color:var(--win-text);font-size:.85rem;font-weight:400;box-sizing:border-box;width:0;min-width:100%;overflow-wrap:anywhere;white-space:normal;text-transform:none;letter-spacing:normal}
.exalt-tip[hidden]{display:none}
html.exalt-tip-open{overflow-anchor:none}
.exalt-tip-note{display:block;margin-top:.2rem;color:var(--win-muted)}
`;

const el = (doc, tag, attributes = {}, ...children) => {
  const node = doc.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name === "text") node.textContent = value;
    else if (value !== false && value !== null && value !== undefined) node.setAttribute(name, value === true ? "" : String(value));
  }
  node.append(...children.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false));
  return node;
};

const classWords = (codes) => codes.map((code) => CLASS_NAMES[code] ?? code).join(", ");
const slotWords = (slots) => slots.map((slot) => SLOT_WORDS[slot] ?? slot.toLowerCase()).join(", ");
const percent = (n) => `${Number.isInteger(n) ? n : Math.round(n * 10) / 10}%`;

/** What a focus does, from its row: "15% faster casts: all spells with a cast time of 2 s or more, up to spell level 44 (weaker above)". */
export function focusMeaning(effect) {
  const f = effect.f;
  const how = FOCUS_WORDS[f.kind] ?? "a focus";
  const amount = f.lo === f.hi ? percent(f.lo) : `${f.lo} to ${percent(f.hi)}`;
  return `${amount} ${how} for ${f.lim}`;
}

/** The loss above a focus's highest spell level (the "tier ceiling" note), or "". */
export function focusCeiling(effect, cap) {
  const f = effect.f;
  if (!f.pen || f.max === null || f.max === undefined || f.max >= cap) return "";
  return `Spells up to level ${f.max} get all of it; each level above loses ${f.pen}% of it.`;
}

/** What a click, worn effect or proc does, composed from the spell data of its row. */
export function meaning(effect) {
  const m = effect.m;
  const n = m === null || m === undefined ? "" : String(Math.round(m * 10) / 10);
  const by = {
    damage: `${n} damage`,
    lifetap: `${n} damage, and it heals you`,
    dot: `${n} damage over time`,
    heal: `${n} hit points healed`,
    heal_over_time: `${n} hit points healed over time`,
    mana: `${n} mana`,
    haste: `${n}% attack speed`,
    slow: `slows the target by ${n}%`,
    snare: `slows the target's movement by ${n}%`,
    run_speed: `${n}% faster movement`,
    buff_stats: `${n} points of stats`,
    buff_resist: `${n} points of resistance`,
    debuff: effect.u === "mana" ? `drains ${n} mana` : `lowers the target by ${n} points`,
    dispel: `strips up to ${n} buffs from the target`,
    resurrect: `restores ${n}% of the experience lost`,
    melee_skill: `${n} extra damage on a skill`,
    levitate: "levitation",
    invisibility: "invisibility",
    see_invisible: "see invisible",
    vision: "better sight in the dark",
    water_breathing: "breathe water",
    teleport: "teleports you",
    summon_pet: "summons a pet",
    summon_item: "summons an item",
    crowd_control: "stuns, mesmerizes or roots the target",
    cure: "cures an affliction",
    illusion: "an illusion",
    mount: "a mount",
    feign_death: "feign death",
    bind: "binds your return point",
    buff_protection: "protection from harm",
  };
  let text = by[effect.c] ?? "a utility effect";
  if (effect.k === "proc" && effect.r) text += `, with proc rate +${effect.r}%`;
  if (effect.q) text += ` (cast as a level ${effect.q} spell)`;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function cssSheet(win) {
  try {
    const sheet = new win.CSSStyleSheet();
    sheet.replaceSync(STYLE);
    return sheet;
  } catch {
    return null; // (a browser without constructed stylesheets shows the section unstyled, and as readable)
  }
}

class Failure extends Error {}
class Updated extends Error {}

export function initExalt(section, env) {
  const { doc, win, words } = env;
  const body = section.querySelector("#exalt-body");
  const statusLine = section.querySelector("#exalt-status");
  if (!body) return null;

  let effectsDoc = null;
  let exaltDoc = null;
  let byId = new Map(); // effect id -> row of effects.json
  let donorInfo = new Map(); // item key -> {name, page, ...itemInfo}
  let hostTable = null; // item key -> itemInfo, from the item list of the site (null until a plan for another kit of Wear this needs it)
  let tablePromise = null;
  let source = "wear"; // "wear": the kit drawn in Wear this; "equip": the kit of Equip now
  let stamp = 0;
  let counter = 0;
  const offs = [];
  let skeleton = null;
  let stale = true; // the section has not been drawn for the view shown (it is drawn when it is open)
  let wear = null; // the plan for the kit drawn in Wear this, made once for a view: {view, entry, promise}
  const tips = new Set(); // the popups of the effect names that are on the page

  const sheet = Array.isArray(doc.adoptedStyleSheets) ? cssSheet(win) : null;
  if (sheet) doc.adoptedStyleSheets = [...doc.adoptedStyleSheets, sheet];
  const equipKit = () => (typeof env.equipKit === "function" ? env.equipKit() : null);
  const onEquipKit = (callback) => (typeof env.onEquipKit === "function" ? env.onEquipKit(callback) : () => {});

  // ---- the status line ---------------------------------------------------------------------------------------------------------

  /** The line under the summary (it is not a live region: the page has two, and a failure or a newer release is said through the page's #announce, once). */
  function say(text, retry = null, spoken = false) {
    if (spoken && text && (!env.background || section.open)) env.announce?.(text); // (a closed section that the page loaded ahead of time says it where it will be seen, not aloud)
    if (!statusLine) return;
    statusLine.replaceChildren();
    statusLine.hidden = !text;
    if (!text) return;
    statusLine.append(text);
    if (retry) {
      const button = el(doc, "button", { type: "button", class: "btn", text: retry.label });
      button.addEventListener("click", retry.run);
      statusLine.append(" ", button);
    }
  }

  // ---- loading -----------------------------------------------------------------------------------------------------------------

  async function getJson(url) {
    const response = await env.fetch(url, { credentials: "same-origin" });
    if (!response.ok) throw new Failure(`HTTP ${response.status}`);
    return response.json();
  }

  function check(document, what) {
    if (document === null || typeof document !== "object" || document.v !== 1) throw new Failure(`${what} is not a file of this version`);
    if (env.release !== null && env.release !== undefined && document.release !== env.release) throw new Updated();
    return document;
  }

  async function load() {
    const [effects, exalt] = await Promise.all([getJson(env.effectsUrl), getJson(env.exaltUrl)]);
    effectsDoc = check(effects, "the effects file");
    exaltDoc = check(exalt, "the file of this trio");
    if (!Array.isArray(effectsDoc.effects) || typeof exaltDoc.roles !== "object" || exaltDoc.roles === null) throw new Failure("a file is not what the site writes");
    byId = new Map(effectsDoc.effects.map((row) => [row.id, row]));
    donorInfo = new Map();
    for (const [key, entry] of Object.entries(effectsDoc.items ?? {})) {
      if (!Array.isArray(entry)) continue;
      const [name, page, slots, classes, twoHand, arrival] = entry;
      const info = itemInfo({ slots: String(slots).split(" ").filter(Boolean), classes: String(classes).split(" ").filter(Boolean), weapon: { skill: twoHand ? "2H" : "" }, tier_rule: arrival === 4 ? "drop" : arrival === 0 ? "fixed0" : "spell" });
      donorInfo.set(key, { ...info, name: String(name), page: page === 1 });
    }
  }

  /** The item list of the site, read for the hosts of a kit of Wear this: the path comes from engine-manifest.json and must be the item table's own. */
  function loadTable() {
    tablePromise ??= (async () => {
      try {
        return await readTable();
      } catch (error) {
        tablePromise = null; // (a failed read is not kept: the next kit asks again, and the site may have been released again meanwhile)
        throw error;
      }
    })();
    return tablePromise;
  }

  async function readTable() {
    const manifest = await getJson("/engine-manifest.json");
    const path = manifest?.items?.path;
    if (typeof path !== "string" || !/^\/assets\/engine\/data\/items-[A-Z0-9]{16}\.json$/.test(path)) throw new Failure("the item list is not where the site says");
    if (env.release && manifest.data_release !== env.release) throw new Updated();
    const table = await getJson(path);
    if (!Array.isArray(table?.items) || (env.release && table.data_release !== env.release)) throw new Updated();
    const found = new Map();
    for (const record of table.items) {
      if (record === null || typeof record !== "object") continue;
      found.set(typeof record.key === "string" ? record.key : `w${record.id}`, itemInfo(record, table.defaults));
    }
    return found;
  }

  // ---- words ---------------------------------------------------------------------------------------------------------------------

  function accessOf(effect, key) {
    const found = effect.d.find((pair) => pair[0] === key);
    return ACCESS[found ? found[1] : 0] ?? NO_SOURCE;
  }

  function itemName(key, kit) {
    const inKit = kit?.find((entry) => entry && entry.key === key);
    return (typeof inKit?.name === "string" && inKit.name !== "" ? inKit.name : null) ?? exaltDoc.names?.[key] ?? donorInfo.get(key)?.name ?? key;
  }

  /** A name, a link to the item's page where the page says it has one (`linked` is false for an item the files do not list as having a page). */
  function nameNode(key, text, linked = true) {
    const href = linked ? words.itemHref(key) : null;
    return href ? el(doc, "a", { href, text }) : doc.createTextNode(text);
  }

  function accessNode(effect, key, kit) {
    const [text, dot] = accessOf(effect, key);
    const info = donorInfo.get(key);
    return el(doc, "span", {}, nameNode(key, itemName(key, kit), info?.page ?? false), " ", el(doc, "span", { class: "muted" }, el(doc, "span", { class: `exalt-dot ${dot}`, "aria-hidden": "true" }), text));
  }

  /** The "unverified" mark of a row: a button that opens the reasons, for a keyboard and for a phone alike. */
  function markNode(effect) {
    if (!effect.x || effect.x.length === 0) return null;
    counter += 1;
    const id = `exalt-why-${counter}`;
    const reason = el(doc, "span", { id, class: "exalt-reason", hidden: true, text: effect.x.map((code) => UNVERIFIED_WHY[code] ?? "It rests on an assumption.").join(" ") });
    const button = el(doc, "button", { type: "button", class: "exalt-mark", "aria-expanded": "false", "aria-controls": id, text: "unverified" });
    button.addEventListener("click", () => {
      const open = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(open));
      reason.hidden = !open;
    });
    return [button, reason];
  }

  // ---- what an effect does, on hover, on focus and on a tap ---------------------------------------------------------------------------

  /**
   * The name of an effect as a button that shows what it does (the words of the lists below: focusMeaning and its ceiling for a focus, meaning for the rest, and the reason of an unverified
   * row). The text is in the page from the start, hidden, and is the description of the button (aria-describedby: the tooltip pattern, so no aria-expanded), so that a screen reader has it on arriving at the name; it is shown while
   * the pointer is over the name, while the name has the focus, and after a tap or a click, until a second one, Escape, or a tap elsewhere. The title attribute is not used.
   */
  function effectNode(effect) {
    counter += 1;
    const id = `exalt-tip-${counter}`;
    const isFocus = effect.k === "focus" && effect.f;
    const notes = [];
    const ceiling = isFocus ? focusCeiling(effect, effectsDoc.cap ?? 50) : "";
    if (ceiling) notes.push(ceiling);
    if (effect.x && effect.x.length > 0) notes.push(`Unverified: ${effect.x.map((code) => UNVERIFIED_WHY[code] ?? "It rests on an assumption.").join(" ")}`);
    const tip = el(doc, "span", { id, class: "exalt-tip", role: "tooltip", hidden: true }, el(doc, "span", { class: "exalt-tip-text", text: isFocus ? focusMeaning(effect) : meaning(effect) }), notes.map((text) => el(doc, "span", { class: "exalt-tip-note", text })));
    const button = el(doc, "button", { type: "button", class: "exalt-name exalt-effbtn", "aria-describedby": id, text: effect.n });
    const wrap = el(doc, "span", { class: "exalt-eff" }, button, tip);
    const state = { hover: false, focus: false, pin: false, off: false }; // off: closed by a second tap or by Escape, until the next hover, focus or tap
    const isOpen = () => !state.off && (state.hover || state.focus || state.pin);
    const sync = () => {
      const open = isOpen();
      tip.hidden = !open;
      // the tooltip pattern: the name is described by the text (aria-describedby, which reads it from the hidden text as well), and the open text is kept out of the page's reading order so it is not read a second time
      if (open) tip.setAttribute("aria-hidden", "true");
      else tip.removeAttribute("aria-hidden");
      markTips();
    };
    wrap.addEventListener("mouseenter", () => ((state.hover = true), (state.off = false), sync()));
    wrap.addEventListener("mouseleave", () => ((state.hover = false), sync()));
    button.addEventListener("focus", () => ((state.focus = true), (state.off = false), sync()));
    button.addEventListener("blur", () => ((state.focus = false), (state.pin = false), sync()));
    button.addEventListener("click", () => {
      if (isOpen() && state.pin) [state.pin, state.off] = [false, true];
      else [state.pin, state.off] = [true, false];
      sync();
    });
    tips.add({
      wrap,
      isOpen,
      escape() {
        if (isOpen()) [state.pin, state.off] = [false, true];
        sync();
      },
      outside(target) {
        if (wrap.contains(target)) return;
        Object.assign(state, { hover: false, focus: false, pin: false, off: false });
        sync();
      },
    });
    return wrap;
  }

  /** The text is in the flow and moves what is below it: while one is open the browser must not scroll the page to keep that in place, which would move the name from under the pointer and close the text again. */
  function markTips() {
    for (const tip of [...tips]) if (!tip.wrap.isConnected) tips.delete(tip);
    doc.documentElement.classList.toggle("exalt-tip-open", [...tips].some((tip) => tip.isOpen()));
  }

  const onPointerDown = (event) => {
    for (const tip of [...tips]) {
      if (tip.wrap.isConnected) tip.outside(event.target);
      else tips.delete(tip);
    }
  };
  const onKeyDown = (event) => {
    if (event.key === "Escape") for (const tip of tips) if (tip.wrap.isConnected) tip.escape();
  };
  doc.addEventListener("pointerdown", onPointerDown, true);
  doc.addEventListener("keydown", onKeyDown);

  // ---- the plan ---------------------------------------------------------------------------------------------------------------

  function kitLabel(view, rematched, fromEquip) {
    if (fromEquip) return "the kit in Equip now, matched in your browser";
    const where = `${words.roleLabel(view.role)}, ${words.raceName(view.race)}, ${words.tierLabel(view.tier)}`;
    return rematched ? `the kit shown in Wear this (${where}), matched in your browser` : `the kit shown in Wear this (${where}), as the site worked it out`;
  }

  /** Whether the name of a host is a link: a kit of the page has a page for every item (the page says so, `itemHref`); an item of Equip now only when it is one that has a page. */
  function hostLinked(key, fromEquip) {
    if (!fromEquip) return true;
    const donor = donorInfo.get(key);
    if (donor) return donor.page;
    const level = equipKit()?.record(key)?.evidence?.level;
    return level === "strict" || level === "wiki";
  }

  function planTable(plan, kit, fromEquip) {
    const rows = plan.rows.map((row) => {
      const effect = byId.get(row.e);
      const index = PLACES.indexOf(row.p);
      const donor = row.d === row.h ? null : accessNode(effect, row.d, kit);
      const marks = markNode(effect);
      const need = SLOT_TIER[row.k];
      const notes = [`opens at +${need}`];
      if (row.u) notes.push(`the donor needs +${need} too`);
      return el(
        doc,
        "tr",
        { id: `exalt-row-${row.e}` },
        el(
          doc,
          "th",
          { scope: "row" },
          el(doc, "span", { class: "exalt-slot", text: words.slotLabel(index) }),
          nameNode(row.h, itemName(row.h, kit), hostLinked(row.h, fromEquip)),
          el(doc, "span", { class: "exalt-line", text: `usable by ${classWords(row.c)}` }),
        ),
        el(
          doc,
          "td",
          {},
          effectNode(effect),
          " ",
          el(doc, "span", { class: "exalt-chip", text: KIND_ONE[row.k] }),
          marks,
          el(doc, "span", { class: "exalt-line" }, `(${notes.join("; ")})`),
          el(doc, "span", { class: "exalt-line" }, donor ? ["From ", donor] : "It is already on this item."),
        ),
      );
    });
    return el(
      doc,
      "table",
      { class: "exalt-table", id: "exalt-plan-table" },
      el(doc, "caption", { text: "Which effect to put on which item" }),
      el(doc, "thead", {}, el(doc, "tr", {}, ...["Item in your kit", "Effect to put on it"].map((text) => el(doc, "th", { scope: "col", text })))),
      el(doc, "tbody", {}, ...rows),
    );
  }

  function noRoomLine(plan) {
    if (plan.noroom.length === 0) return el(doc, "p", { class: "exalt-noroom note", text: "Every recommended effect has a place in this kit." });
    const parts = plan.noroom.map((row) => [effectNode(byId.get(row.e)), ` (${NO_ROOM_WHY[row.w] ?? row.w})`]);
    return el(doc, "p", { class: "exalt-noroom note", id: "exalt-noroom" }, el(doc, "strong", { text: `No room for ${plan.noroom.length}: ` }), parts.flatMap((part, index) => [index ? "; " : null, part]), ".");
  }

  /** The items of the kit drawn in Wear this, as the page shows them: {key (null where the page has no address for the item), name}. */
  function drawnItems() {
    const rows = typeof env.kitRows === "function" ? env.kitRows() : [];
    return rows.map((row) => {
      const name = row.querySelector('[data-f="name"]');
      const href = name?.querySelector("a")?.getAttribute("href") ?? "";
      const found = /^\/item\/([^/]+)\/$/.exec(href);
      return { key: found ? found[1] : null, name: name?.textContent ?? "" };
    });
  }

  /** The donor items of a plan that the kit does not have, once each, in the order of the plan: [{key, effect, need}] (`need` is the tier the donor has to be levelled to, or 0). */
  function donorsToFarm(plan, members) {
    const found = new Map();
    for (const row of plan.rows) {
      if (row.d === row.h) continue;
      const effect = byId.get(row.e);
      if (!effect) continue;
      const name = itemName(row.d, null);
      if (members.some((member) => (member.key !== null && member.key !== undefined ? member.key === row.d : member.name === name))) continue;
      const entry = found.get(row.d) ?? { key: row.d, effect, need: 0 };
      entry.need = Math.max(entry.need, row.u ? SLOT_TIER[row.k] : 0);
      found.set(row.d, entry);
    }
    return [...found.values()];
  }

  /** "Donor items to farm": a short list at the top of the plan, or nothing when the kit has every donor. */
  function donorList(plan, kit, members) {
    const donors = donorsToFarm(plan, members);
    if (donors.length === 0) return [];
    const items = donors.map(({ key, effect, need }) => {
      const [text, dot] = accessOf(effect, key);
      return el(doc, "li", {}, nameNode(key, itemName(key, kit), donorInfo.get(key)?.page ?? false), `: `, el(doc, "span", { class: `exalt-dot ${dot}`, "aria-hidden": "true" }), `${text}, ${need ? `needs +${need}` : "no level needed"}`);
    });
    return [el(doc, "h4", { id: "exalt-donors-h", text: "Donor items to farm" }), el(doc, "ul", { id: "exalt-donors", class: "exalt-donors" }, ...items)];
  }

  /**
   * What the plan box holds for a plan: the donor list, the table and the no-room line. The donors "already in the kit" are those of the kit the plan was made for: the kit of Equip now,
   * the kit drawn in Wear this, or (`members` given) another one when the plan on show is not for the kit that is drawn.
   */
  function planBoxContent(plan, kit, fromEquip, members = null) {
    members ??= fromEquip ? (kit ?? []).filter(Boolean).map((item) => ({ key: item.key, name: item.name })) : drawnItems();
    return [...donorList(plan, kit, members), planTable(plan, kit, fromEquip), noRoomLine(plan)];
  }

  async function planFor(view, entry, kitSpec) {
    const baseOptions = entry;
    const common = { options: baseOptions, effects: byId, mass: effectsDoc.mass ?? {}, classes: exaltDoc.classes };
    if (kitSpec.fromEquip) {
      const equip = equipKit();
      const hostInfo = (key) => {
        const record = equip.record(key);
        return record ? itemInfo(record, equip.defaults) : (donorInfo.get(key) ?? null);
      };
      const kit = equip.kit.map((it, index) => (it ? { place: PLACES[index], key: it.key, tier: it.tier } : null)).filter(Boolean);
      return { plan: planKit({ ...common, kit, items: hostInfo, tier: 0 }), rematched: true };
    }
    return wearPlan(view, entry);
  }

  /** The plan for the kit drawn in Wear this, made once for a view (the table of the plan and the hints under the places of the kit both ask for it). A failure is not kept. */
  function wearPlan(view, entry) {
    if (wear !== null && wear.view === view && wear.entry === entry) return wear.promise;
    const promise = (async () => {
      if (view.exact && view.race === exaltDoc.race && view.tier === exaltDoc.tier) return { plan: { rows: entry.plan, noroom: entry.noroom }, rematched: false };
      hostTable ??= await loadTable();
      const kit = (view.kit ?? []).map((it, index) => (it ? { place: PLACES[index], key: it.key } : null)).filter(Boolean);
      const items = (key) => hostTable.get(key) ?? donorInfo.get(key) ?? null;
      return { plan: planKit({ options: entry, effects: byId, mass: effectsDoc.mass ?? {}, classes: exaltDoc.classes, kit, items, tier: view.tier }), rematched: true };
    })();
    wear = { view, entry, promise };
    promise.catch(() => {
      if (wear !== null && wear.promise === promise) wear = null;
    });
    return promise;
  }

  // ---- the lists --------------------------------------------------------------------------------------------------------------------

  function whyNot(row) {
    if (!row.l || row.l.length === 0) return null;
    const details = el(doc, "details", {}, el(doc, "summary", { "aria-expanded": "false", text: "Why not the others" }), el(doc, "span", { class: "exalt-line", text: `Only one focus of a kind applies, so these lost to this one: ${row.l.join(", ")}.` }));
    details.addEventListener("toggle", () => details.querySelector("summary").setAttribute("aria-expanded", String(details.open)));
    return details;
  }

  function listTable(kind, rows, cap, late) {
    const body = rows.map((row) => {
      const effect = byId.get(row.e);
      const donor = donorInfo.get(row.d);
      const chip =
        kind === "focus" && effect.f?.cov?.[row.m] !== undefined
          ? `touches ${effect.f.cov[row.m]}% of what your ${CLASS_NAMES[row.m] ?? row.m} casts at ${late}+`
          : `most use to your ${CLASS_NAMES[row.m] ?? row.m}`;
      const ceiling = kind === "focus" ? focusCeiling(effect, cap) : "";
      const where = [kind === "carry" ? "Needs no socket" : `Opens at +${SLOT_TIER[kind]}`];
      if (donor) where.push(`classes: ${donor.classes.includes("ALL") ? "all" : classWords(donor.classes)}`, `slot: ${slotWords(donor.slots)}`);
      const others = row.o.length > 0 ? el(doc, "span", { class: "exalt-line" }, "Also: ", ...row.o.flatMap((key, i) => [i ? ", " : null, accessNode(effect, key, null)])) : null;
      return el(
        doc,
        "tr",
        {},
        el(
          doc,
          "td",
          {},
          el(doc, "span", { class: "exalt-name", text: effect.n }),
          markNode(effect),
          el(doc, "span", { class: "exalt-line", text: kind === "focus" ? focusMeaning(effect) : meaning(effect) }),
          ceiling ? el(doc, "span", { class: "exalt-ceiling", text: ceiling }) : null,
          el(doc, "span", { class: "exalt-chip", text: chip }),
          el(doc, "span", { class: "exalt-line", text: where.join(" · ") }),
          kind === "focus" ? whyNot(row) : null,
        ),
        el(doc, "td", {}, accessNode(effect, row.d, null), others),
      );
    });
    return el(
      doc,
      "table",
      { class: "exalt-table", id: `exalt-${kind}` },
      el(doc, "caption", { text: kind === "carry" ? "Just carry these: they work from a bag and use no socket" : `${KIND_HEAD[kind]} (a socket that opens at +${SLOT_TIER[kind]}), best first` }),
      el(doc, "thead", {}, el(doc, "tr", {}, ...["Effect", "Best source"].map((text) => el(doc, "th", { scope: "col", text })))),
      el(doc, "tbody", {}, ...body),
    );
  }

  // ---- drawing -----------------------------------------------------------------------------------------------------------------------

  function build() {
    const top = el(doc, "div", { class: "exalt-top" });
    const choice = el(doc, "fieldset", { class: "exalt-source", hidden: true }, el(doc, "legend", { text: "Match the plan to" }));
    for (const [value, text] of [["wear", "the kit in Wear this"], ["equip", "the kit in Equip now (Upgrade)"]]) {
      counter += 1;
      const id = `exalt-source-${counter}`;
      const input = el(doc, "input", { type: "radio", name: "exalt-source", id, value });
      input.checked = value === source;
      input.addEventListener("change", () => {
        if (input.checked) {
          source = value;
          refresh();
        }
      });
      choice.append(el(doc, "label", { for: id }, input, ` ${text}`));
    }
    const planHead = el(doc, "h3", { id: "exalt-plan-h", text: "Exalt plan for this kit" });
    const planLead = el(doc, "p", { class: "note", id: "exalt-plan-lead" });
    const planBox = el(doc, "div", { id: "exalt-plan" });
    const listHead = el(doc, "h3", { id: "exalt-lists-h", text: "Effects to exalt, best first" });
    const listLead = el(doc, "p", { class: "note", text: "Each item has one socket of each kind: a focus at +1, a click at +2, a worn effect at +3 and a proc at +4. The scores are a model for this trio and role and compare effects with each other only. Focus effects do not stack with one of their own type, so each type has one row." });
    const listBox = el(doc, "div", { id: "exalt-lists" });
    top.append(choice);
    body.replaceChildren(top, planHead, planLead, planBox, listHead, listLead, listBox);
    body.classList.add("exalt");
    return { choice, planLead, planBox, listBox, shownRole: null };
  }

  /** Nothing of an earlier view stays when this one cannot be shown (a file that does not fit the view): the plan and the lists go, and the line says so, once, through the live region. */
  function showFailure() {
    skeleton.planLead.textContent = "Couldn't show the effects for this view.";
    skeleton.planBox.replaceChildren();
    skeleton.listBox.replaceChildren();
    skeleton.shownRole = null;
    env.announce?.("Couldn't show the effects for this view.");
  }

  /**
   * The view changed (or the kit of Equip now, or the section was opened). The hints under the places of Wear this are made every time; the section itself (its plan, its lists, and the
   * item table a plan for another kit needs) is drawn only while it is open, and when it is opened next if anything changed meanwhile.
   */
  async function refresh() {
    if (exaltDoc === null) return;
    const mine = ++stamp;
    hint(mine);
    if (!section.open) {
      stale = true;
      return;
    }
    stale = false;
    try {
      await draw(mine);
    } catch (error) {
      if (mine !== stamp) return;
      if (error instanceof Updated) {
        env.onUpdated();
        say("Data updated, reload the page to see the new data.", { label: "Reload", run: () => env.reload() }, true);
        return;
      }
      showFailure();
    }
  }

  async function draw(mine) {
    const view = env.view();
    const equip = equipKit();
    if (source === "equip" && !equip) source = "wear";
    skeleton.choice.hidden = !equip;
    for (const input of skeleton.choice.querySelectorAll("input")) input.checked = input.value === source;
    const entry = exaltDoc.roles[view.role];
    if (!entry || typeof entry !== "object") {
      skeleton.planLead.textContent = `This site has no effect plan for the ${words.roleLabel(view.role)} role of this trio.`;
      skeleton.planBox.replaceChildren();
      skeleton.listBox.replaceChildren();
      skeleton.shownRole = null;
      return;
    }
    if (skeleton.shownRole !== view.role) {
      const late = effectsDoc.late ?? 30;
      const cap = effectsDoc.cap ?? 50;
      const tables = ["focus", "click", "worn", "proc", "carry"].filter((kind) => Array.isArray(entry[kind]) && entry[kind].length > 0).map((kind) => listTable(kind, entry[kind], cap, late));
      skeleton.listBox.replaceChildren(...tables);
      skeleton.shownRole = view.role;
    }
    const fromEquip = source === "equip";
    if (!fromEquip && view.pending) {
      // the kit drawn stands in for one that is being worked out: no plan is made for it (and no item list is read); the plan comes with the kit
      skeleton.planLead.textContent = "Waiting for the kit to be worked out.";
      skeleton.planBox.replaceChildren();
      return;
    }
    if (!fromEquip && !view.exact && !view.kit) {
      // the address asks for a view that has not been drawn yet: there is no kit to match the plan to, and the plan of the file is for another one
      skeleton.planLead.textContent = "Waiting for the view to load.";
      skeleton.planBox.replaceChildren();
      return;
    }
    let result;
    try {
      result = await planFor(view, entry, { fromEquip });
    } catch (error) {
      if (mine !== stamp) return;
      if (error instanceof Updated) throw error;
      // the lists stand; the plan shown is the one the site worked out for its own default kit, and the line says so
      skeleton.planLead.textContent = "Couldn't load the item list to match this kit, so this is the plan for the kit the site worked out.";
      // (that plan is for the default kit, of which the file names the items that carry an effect: those are what the donor list can leave out, not the items of the kit the visitor changed to)
      const made = entry.plan.map((row) => ({ key: row.h, name: itemName(row.h, null) }));
      skeleton.planBox.replaceChildren(...planBoxContent({ rows: entry.plan, noroom: entry.noroom }, null, false, made));
      return;
    }
    if (mine !== stamp) return;
    const kit = fromEquip ? equipKit().kit : view.kit; // (null for the answer the page was made with: the names of its items are in the file)
    const content = planBoxContent(result.plan, kit, fromEquip);
    skeleton.planLead.textContent = `For ${kitLabel(view, result.rematched, fromEquip)}.`;
    skeleton.planBox.replaceChildren(...content);
  }

  // ---- the hints under the places of Wear this -------------------------------------------------------------------------------------------

  /** Resolves when the browser is idle (requestIdleCallback; a short timeout where the browser has none). */
  const whenIdle = () => new Promise((resolve) => (typeof win.requestIdleCallback === "function" ? win.requestIdleCallback(() => resolve(), { timeout: 4000 }) : win.setTimeout(resolve, 300)));

  /** Take the lines off the places of Wear this. */
  function clearHints() {
    const rows = typeof env.kitRows === "function" ? env.kitRows() : [];
    for (const row of rows) for (const box of row.querySelectorAll(".exalt-hints")) box.remove();
    markTips(); // (a line taken off with its text open must not leave the page with scrolling held)
  }

  /**
   * Open the section and go to the row of the plan that the line is about. The line is for the kit drawn in Wear this: a section that shows the plan for the kit of Equip now is
   * switched to Wear this first (its rows belong to another kit), and the plan is drawn again before the row is looked for (a closed section has not drawn it).
   */
  async function toPlan(event, effect) {
    event.preventDefault();
    section.open = true;
    source = "wear";
    await refresh();
    const target = doc.getElementById(`exalt-row-${effect.id}`) ?? doc.getElementById("exalt-plan-h") ?? section;
    target.setAttribute("tabindex", "-1");
    target.scrollIntoView?.({ block: "center" });
    target.focus?.();
  }

  function hintLine(row, effect, kit) {
    const need = SLOT_TIER[row.k];
    const [access] = accessOf(effect, row.d);
    const link = el(doc, "a", { class: "exalt-hint-plan", href: `#exalt-row-${row.e}`, "aria-label": `In the plan: ${effect.n}`, text: "In the plan" });
    link.addEventListener("click", (event) => toPlan(event, effect));
    return el(doc, "span", { class: "exalt-hint" }, "Exalt: ", effectNode(effect), ` (${row.k}, +${need}) from ${itemName(row.d, kit)} (${access}); ${row.u ? "level both to" : "level this item to"} +${need} `, link);
  }

  /**
   * The lines under the places of the kit drawn in Wear this: one for each effect the plan puts on a place, unless it is on the item already. They are taken off at once when the view
   * changes, and drawn again only for the kit that is drawn (not while it is being worked out, for a role with no plan, or when the plan cannot be made).
   */
  async function hint(mine) {
    clearHints();
    const view = env.view();
    if (exaltDoc === null || view.pending) return;
    const entry = exaltDoc.roles[view.role];
    if (!entry || typeof entry !== "object" || (!view.exact && !view.kit)) return;
    // A plan for the default kit is in the file. For any other kit the matcher needs the item list of the site (some 1.9 MB, 190 KB gzipped): it is read once per page and not while the
    // visitor's control is being handled, so with the section closed (nobody asked for the plan) it waits until the browser is idle. An open section's own draw reads it at once, and this
    // takes the same promise.
    if (!section.open && hostTable === null && !(view.exact && view.race === exaltDoc.race && view.tier === exaltDoc.tier) && !(wear !== null && wear.view === view && wear.entry === entry)) {
      await whenIdle();
      if (mine !== stamp) return;
    }
    let result;
    try {
      result = await wearPlan(view, entry);
    } catch {
      return; // (the table stays as the page drew it; the section's own table says what went wrong)
    }
    if (mine !== stamp) return;
    try {
      const rows = env.kitRows();
      const groups = new Map();
      for (const row of result.plan.rows) {
        const index = PLACES.indexOf(row.p);
        if (row.d === row.h || !rows[index] || (view.kit && view.kit[index]?.key !== row.h)) continue;
        const effect = byId.get(row.e);
        if (!effect) throw new Failure("a plan row of an effect the shared file lacks");
        groups.set(index, [...(groups.get(index) ?? []), hintLine(row, effect, view.kit)]);
      }
      for (const [index, lines] of groups) {
        const cell = rows[index].cells?.[1] ?? rows[index].querySelector("td");
        if (!cell) continue;
        const box = el(doc, "span", { class: "exalt-hints" }, ...lines);
        const more = cell.querySelector('[data-f="more"]');
        if (more) cell.insertBefore(box, more);
        else cell.append(box);
      }
    } catch {
      clearHints();
    }
  }

  // ---- starting --------------------------------------------------------------------------------------------------------------------

  async function start() {
    say("Loading the effects…");
    try {
      await load();
    } catch (error) {
      if (error instanceof Updated) {
        env.onUpdated();
        say("Data updated, reload the page to see the new data.", { label: "Reload", run: () => env.reload() }, true);
      } else say("Couldn't load the effects.", { label: "Try again", run: () => (ready = start()) }, true);
      return;
    }
    say("");
    skeleton = build();
    offs.push(env.onView(() => refresh()), onEquipKit(() => refresh()));
    section.addEventListener("toggle", onToggle);
    offs.push(() => section.removeEventListener("toggle", onToggle));
    await refresh();
  }

  /** The section was opened: draw what changed while it was closed (or was never drawn). */
  function onToggle() {
    if (section.open && stale && skeleton !== null) refresh();
  }

  let ready = start();
  return {
    ready: () => ready,
    destroy() {
      for (const off of offs) off();
      doc.removeEventListener("pointerdown", onPointerDown, true);
      doc.removeEventListener("keydown", onKeyDown);
      clearHints();
    },
  };
}
