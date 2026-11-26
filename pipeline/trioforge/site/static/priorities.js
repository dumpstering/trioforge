// The priorities of the trio page: how much the visitor wants each stat to count, as five steps (Off, Low, Normal, High, Top) that multiply the weight the role gives it by 0, 0.5, 1, 2 and 4.
//
// This file is the part the page script holds: the eight stats and the five steps in their fixed order, the address parameter `p` (a character for each stat: 0 l n h t), the words for a choice,
// and the control, drawn by script into the section of the choices (the page is made with room for it, in the stylesheet: the markup does not grow). What a choice means for the optimizer, the
// custom weights of a request, is worked out by the chunk of the weights (ui/priority-weights.js), which this file does not share code with (a module that both used would be loaded with the
// page). The numbers there are held to the characters here by tests-js/priority-weights.test.mjs.
//
//   drawPriorities(doc, controls, {onChange, onReset, onPreset, onRates, onWarm}) -> {read(), sync(priorities), focus(), setCounted(counted), setPreset(shown), rearm()}
//
// A select for each stat, with a visible label (the page's own choices, Race and Tier, are selects too); an option is the step and the multiplier it makes of the role's own weight ("High (x2)"). `onChange(priorities)` is given the whole choice as the string of the address after
// any change of a select; `onPreset(priorities)` when the button "Resists first" is pressed (it is a choice of the steps like any other, so the page asks for the view it makes; `setPreset(shown)` shows or hides it:
// the page shows it for the builds that stand in front, the Tank and the Shield caster); `onReset()` when Reset is pressed (it is off while every step is Normal); `onRates()` when the button for the exchange rates is pressed (the line under the control
// is the chunk's to fill: it needs the evaluator, which a page does not load for nothing; the button is a disclosure; what the line says is said through the page's own live region, by the chunk). `onWarm()` is called
// at the first focus in the control, a moment before a step can be chosen, so that the page can read what the build weighs (it reads it only when asked: nothing is fetched for a page that is not touched;
// `rearm()` has the next focus after the next change of a step call it again, after a failure: a focus alone never asks twice, so a code that does not come is asked for once per action of the visitor). `sync` puts the controls in the state the page shows, and moves nothing else; `focus()` puts the focus on the first of the steps that can take it (a stat the build does not weigh
// is disabled), else on the button of the rates: where it goes when Reset, which is off then, had it. `setCounted(counted)` says, for each stat, whether the build weighs it (null: not known yet, and every stat is offered): the select of a stat that it does not is
// disabled at Normal, with a visible note that says why, and is never a choice.
//
// Everything is text (textContent, never markup).

/** The stats, in the order of the address's `p`: the id, and the label of the select. */
export const STATS = Object.freeze([
  ["hp", "Hit points"],
  ["ac", "Armor class"],
  ["mana", "Mana"],
  ["atk", "Attack (strength)"],
  ["dex", "Dexterity"],
  ["haste", "Haste"],
  ["resists", "Resists"],
  ["end", "Endurance"],
]);
/** The steps: the character of the address, the name, and the multiplier of the role's own weight that the option says beside it. */
export const STEPS = Object.freeze([
  ["0", "Off", "x0"],
  ["l", "Low", "x0.5"],
  ["n", "Normal", "x1"],
  ["h", "High", "x2"],
  ["t", "Top", "x4"],
]);
/** Every stat Normal: the role's own weights, and the page that is made. */
export const OWN_PRIORITIES = "n".repeat(STATS.length);
/** "Resists first": resists Top, armor class Low and the rest Normal, for a build that stands in front (the Tank and the Shield caster) and wants the resists capped before the armor class. */
export const RESISTS_FIRST = STATS.map(([id]) => (id === "resists" ? "t" : id === "ac" ? "l" : "n")).join("");
/** The builds that the button is shown for. */
export const PRESET_ROLES = Object.freeze(["tank", "shield"]);
const SHAPE = new RegExp(`^[${STEPS.map(([character]) => character).join("")}]{${STATS.length}}$`);
const LEGEND = "Your priorities: how much each stat counts for you";
const SHOW_RATES = "What is a point worth on this kit?";
const NOT_COUNTED = "not counted in this build";

/** A value of the address's `p` as it is when it is one the page can take (a character for each stat), else null: a value that is not is ignored whole. */
export function parsePriorities(text) {
  return typeof text === "string" && SHAPE.test(text) ? text : null;
}

/** A choice in words: the stats that are not Normal with their steps, in the control's order ("armor class High, mana Off"), or "all Normal". */
export function sayPriorities(priorities) {
  const named = [];
  STATS.forEach(([, label], index) => {
    const step = STEPS.find(([character]) => character === priorities[index]);
    if (step !== undefined && step[0] !== "n") named.push(`${label.toLowerCase()} ${step[1]}`);
  });
  return named.length === 0 ? "all Normal" : named.join(", ");
}

export function drawPriorities(doc, controls, { onChange, onReset, onPreset, onRates, onWarm }) {
  const el = (tag, attributes = {}, ...children) => {
    const node = doc.createElement(tag);
    for (const [name, value] of Object.entries(attributes)) {
      if (name === "text") node.textContent = value;
      else node.setAttribute(name, value === true ? "" : value);
    }
    node.append(...children);
    return node;
  };
  const selects = STATS.map(([id]) => {
    const select = el("select", { id: `prio-${id}`, name: `prio-${id}` });
    for (const [character, label, times] of STEPS) {
      const option = el("option", { value: character, text: `${label} (${times})` });
      if (character === "n") option.selected = true;
      select.append(option);
    }
    return select;
  });
  const grid = el("div", { class: "prio-grid" });
  const notes = STATS.map(([id]) => el("p", { class: "prio-note", id: `prio-${id}-note`, text: NOT_COUNTED, hidden: true }));
  STATS.forEach(([, label], index) => grid.append(el("div", { class: "control" }, el("label", { for: selects[index].id, text: label }), selects[index], notes[index])));
  const preset = el("button", { type: "button", id: "prio-preset-resists", class: "btn-quiet", text: "Resists first", hidden: true });
  const reset = el("button", { type: "button", id: "prio-reset", class: "btn-quiet", text: "Reset priorities", disabled: true });
  const show = el("button", { type: "button", id: "prio-rates-show", class: "btn-quiet", text: SHOW_RATES, "aria-expanded": "false", "aria-controls": "prio-rates-text" });
  const line = el("span", { id: "prio-rates-text", hidden: true });
  const box = el("fieldset", { class: "control prio", id: "prio" }, el("legend", { text: LEGEND }), grid, el("div", { class: "prio-foot" }, preset, reset, show, line));

  let counted = null; // for each stat, whether the build weighs it; null while that is not known
  const read = () => selects.map((select) => select.value).join("");
  let warmed = false;
  let failed = false; // the first touch found no code: a focus does not ask again (a focus is not an action), the next change of a step does re-arm it, once
  box.addEventListener("focusin", () => {
    if (warmed || typeof onWarm !== "function") return;
    warmed = true;
    onWarm();
  });
  box.addEventListener("change", (event) => {
    if (!selects.includes(event.target)) return;
    if (failed) {
      failed = false;
      warmed = false;
    }
    reset.disabled = read() === OWN_PRIORITIES;
    onChange(read());
  });
  preset.addEventListener("click", () => onPreset(RESISTS_FIRST));
  reset.addEventListener("click", () => onReset());
  show.addEventListener("click", () => onRates());
  controls.append(box);
  controls.setAttribute("data-prio", ""); // (the stylesheet kept the room it takes until now: nothing under it moves)

  /** The controls in the state the page shows: the steps, and Reset off while they are all Normal. */
  function sync(priorities) {
    selects.forEach((select, index) => {
      if (counted !== null && counted[index] === false) select.value = "n"; // (a stat the build does not weigh is never a choice)
      else if (STEPS.some(([character]) => character === priorities[index])) select.value = priorities[index];
    });
    reset.disabled = read() === OWN_PRIORITIES;
  }

  /** Which stats the build weighs: the select of one that it does not is disabled at Normal, and the note beside it says why. */
  function setCounted(next) {
    counted = next;
    selects.forEach((select, index) => {
      const off = counted !== null && counted[index] === false;
      select.disabled = off;
      notes[index].hidden = !off;
      if (off) {
        select.value = "n";
        select.setAttribute("aria-describedby", notes[index].id);
      } else select.removeAttribute("aria-describedby");
    });
    reset.disabled = read() === OWN_PRIORITIES;
  }
  return { read, sync, focus: () => (selects.find((select) => !select.disabled) ?? show).focus(), setCounted, setPreset: (shown) => (preset.hidden = !shown), rearm: () => (failed = true) };
}
