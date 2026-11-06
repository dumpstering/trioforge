// Shared by the tests of the expanders of the Upgrade section (not a test file): the answers the optimizer gives to a best sets request and to an Every slot request, as the
// page's client hands them over, and what the expanders put in the page, read back as data. The answers are built the way protocol.js documents them and are held to protocol.js's
// own reader (validateFromWorker, against the request they answer), so that no test hands the page a shape that the protocol would refuse. Every name here is invented
// (pipeline/tests/test_site_fixture_items.py fails when a real item's key or name is in this file); the sample cases of the optimizer (fixtures/parity/upgrade/) are read as data,
// and each of their items is given an invented name.

import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, vi } from "vitest";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";
import { KIT_PLACE_NAMES, validateFromWorker } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { $, $$, ROOT, record, tableOf } from "./upgrade-helpers.mjs";
import { addByName, ended, equipStep, flush, kitOf, mountAnswer } from "./upgrade-answer-helpers.mjs";

/** An exact value as the text and the number the protocol carries (a number is read as the decimal it prints as). */
const exact = (number) => {
  const rational = Rational.fromNumber(number);
  return { text: rational.toString(), number: rational.toNumber() };
};

/** What a worker's message becomes in the hands of the page: the fields that belong to the request, without the envelope. */
const withoutEnvelope = (message) => {
  const { v: _v, type: _type, id: _id, ...rest } = message;
  return rest;
};

/** An answer, checked against the request it answers (the way the client checks it), and handed to the request's promise. */
function deliver(run, message, expectation) {
  const checked = validateFromWorker({ v: 1, type: "result", id: 7, kind: "scenario", ...message }, { id: 7, kind: "scenario", ...expectation });
  run.finish(withoutEnvelope(checked));
}

/**
 * The answer to a best sets request. `acquired` are `{ident, kind, sourceTier, cost}` (kind "new" by default); `kit` is the kit of the set (null: no set was found in the time);
 * `gain` its gain over Equip now, whose value is `baseline`. A set that is not proven has the status of a solve that ran out of time and its label.
 */
export function finishSet(run, { acquired = [], kit, gain = 0, baseline = 1000, status = "optimal", label = null, buffs = [] }) {
  const found = kit !== null;
  const value = exact(baseline + gain);
  const difference = exact(gain);
  const base = exact(baseline);
  const message = {
    mode: "best-sets",
    k: run.request.k,
    acquired: acquired.map(({ ident, kind = "new", sourceTier = null, cost = null }) => ({ ident, kind, sourceTier, cost })),
    F: found ? value.text : null,
    value: found ? value.number : null,
    gain: found ? difference.text : null,
    gainValue: found ? difference.number : null,
    kit,
    buffs: found ? buffs : [],
    status,
    proven: status === "optimal",
    label: status === "optimal" ? null : (label ?? (found ? "best found, not proven optimal" : "not found in time")),
    baseline: { F: base.text, value: base.number },
    hasteAssumed: 30,
    elapsedMs: 3,
  };
  deliver(run, message, { mode: "best-sets", owned: run.request.owned, k: run.request.k, tierMode: run.request.tierMode });
}

/** A set that was not found in the time. */
export const lostSet = (run, baseline = 1000) => finishSet(run, { kit: null, status: "time_limit", baseline });

/**
 * The answer to an Every slot request: for each place the swaps given in `swaps` (`{index: [{ident, delta}]}`, best first). The item worn in a place is the request's kit's.
 * A delta is a number (an exact value is made of it).
 */
export function finishSlots(run, swaps = {}) {
  const rows = KIT_PLACE_NAMES.map((place, index) => ({
    place,
    index,
    current: run.request.kit[index],
    swaps: (swaps[index] ?? []).map(({ ident, delta }) => {
      const change = exact(delta);
      return { ident, delta: change.text, deltaValue: change.number };
    }),
  }));
  deliver(run, { mode: "every-slot", rows, elapsedMs: 4 }, { mode: "every-slot", owned: run.request.owned, tierMode: run.request.tierMode, kit: run.request.kit, limit: run.request.limit });
}

/** An addition of a set that costs what bringing an item of the tier it arrives at to +4 costs: `cost` as a path step carries it. */
export const addition = (ident, kind = "new", cost = null, sourceTier = null) => ({ ident, kind, cost, sourceTier });

// ---- the section ---------------------------------------------------------------------------------------------------------------------------------

/**
 * The Upgrade section with the gear given (`gear`: [name, tier] pairs, added the way a visitor does), its request sent, and the path answered and ended: Equip now (`equip`, by
 * default the kit `kit` with the optional buffs `buffs`) and a path that found nothing more to add (`end` is its result). The expanders can be opened then. `file` is the
 * text of an inventory file to read first, for a list with places in it.
 */
export async function answered({ gear = [["tarn signet", "4"]], file = null, kit = kitOf({ 11: "w80301@4" }), buffs = [], equip = { ...equipStep({ kit }), buffs }, end = ended("no-gain", 0), ...options } = {}) {
  const t = mountAnswer({ pauseMs: 0, ...options });
  if (file !== null) await t.gear.readFile(new File([file], "inventory.txt"));
  for (const [name, tier] of gear) addByName(name, tier);
  await given(t, 1);
  const run = t.engine.runs[0];
  run.onStep(equip);
  run.finish(end);
  await flush();
  return { ...t, run };
}

/** Wait (with real timers) until the client was given `count` requests. */
export const given = (t, count) => vi.waitFor(() => expect(t.engine.runs).toHaveLength(count), { timeout: 5000, interval: 5 });

/** Wait a little, and say how many requests the client was given (for asserting that nothing more was sent). */
export async function quiet(t, ms = 60) {
  await new Promise((resolve) => setTimeout(resolve, ms));
  return t.engine.runs.length;
}

/** Open (or close) an expander the way a visitor does: a click on its summary. The browser tells the page with a toggle event a moment later, and that is waited for. */
export async function toggle(id) {
  const told = new Promise((resolve) => $(`#${id}`).addEventListener("toggle", resolve, { once: true }));
  $(`#${id} > summary`).click();
  await told; // (the page's own listener, which was there first, has been called)
  await flush();
}

/** The same with fake timers: the fake clock goes on a little (the browser's task for the event may be one of them) and the event is waited for. */
export async function toggleFake(id) {
  const told = new Promise((resolve) => $(`#${id}`).addEventListener("toggle", resolve, { once: true }));
  $(`#${id} > summary`).click();
  await vi.advanceTimersByTimeAsync(20);
  await told;
  await flush();
}
export const isOpen = (id) => $(`#${id}`).open;

// ---- the sample cases of the optimizer ---------------------------------------------------------------------------------------------------------------

/** The invented name of an item of a sample case, from its key (`w` and a number): six digits, so that no name is the beginning of another. */
const sampleNameOf = (key) => `Sample ${key.slice(1).padStart(6, "0")}`;
/** The name the page shows for an ident of a sample case: the invented name and the tier. */
export const sampleName = (ident) => {
  const [key, tier] = ident.split("@");
  return `${sampleNameOf(key)} +${tier}`;
};

/** The ids of the Upgrade cases of the committed sample (fixtures/parity/upgrade/upgrade-NNN.json; the invented upgrade-slots-* cases are not sessions), in order. */
export const sampleCaseIds = () =>
  readdirSync(resolve(ROOT, "fixtures", "parity", "upgrade"))
    .filter((name) => /^upgrade-\d+\.json$/.test(name))
    .map((name) => name.slice(0, -".json".length))
    .sort();

/** What a sample case says before the page is given anything: its tier mode, the owned counts (a Map from ident), the kit Every slot starts from, and the Every slot rows. */
export function rawCase(id) {
  const { inputs, expected } = JSON.parse(readFileSync(resolve(ROOT, "fixtures", "parity", "upgrade", `${id}.json`), "utf8"));
  const rows = expected.every_slot;
  return { id, mode: inputs.tier_mode, owned: new Map(inputs.owned), kit: rows.map((place) => place.current), rows };
}

/**
 * One of the cases of the optimizer's own fixtures (fixtures/parity/upgrade/<id>.json, the committed sample) in the section. The gear is the case's owned items, each under an invented
 * name; the tier mode is the case's, chosen before the gear is given; Equip now is the kit the case's Every slot starts from; and Every slot is opened and answered with the rows the
 * case expects, held to protocol.js's reader as any answer is. Returns the section (`t`), what the case says (`owned`: a Map from ident to count, `kit`, `rows`) and what the page
 * drew (`shown`, as `slotsDrawn` reads it).
 */
export async function sampleCase(id) {
  const { inputs, expected } = JSON.parse(readFileSync(resolve(ROOT, "fixtures", "parity", "upgrade", `${id}.json`), "utf8"));
  const rows = expected.every_slot;
  const kit = rows.map((place) => place.current);
  const owned = new Map(inputs.owned);
  const keys = new Set();
  for (const ident of [...owned.keys(), ...kit, ...rows.flatMap((place) => place.swaps.map((swap) => swap.item))]) if (ident !== null) keys.add(ident.split("@")[0]);
  // an item with a wiki page has the key w<page id>; one with none (rlt-..., read from EQ Legends Tools alone) has a key of its own and no page id
  const items = tableOf([...keys].sort().map((key) => (/^w[1-9][0-9]*$/.test(key) ? record(Number(key.slice(1)), sampleNameOf(key)) : record(null, sampleNameOf(key), { key }))));
  const t = mountAnswer({ pauseMs: 0, items });
  const mode = inputs.tier_mode;
  if (mode.mode === "arrives") {
    $("#upgrade-mode-d").value = String(mode.D);
    $("#upgrade-mode-d").dispatchEvent(new Event("change", { bubbles: true }));
  } else if (mode.mode === "fixed") {
    $("#upgrade-mode-fixed").click();
    $("#upgrade-mode-n").value = String(mode.N);
    $("#upgrade-mode-n").dispatchEvent(new Event("change", { bubbles: true }));
  }
  for (const [ident, count] of owned) {
    const [key, tier] = ident.split("@");
    for (let copy = 0; copy < count; copy += 1) addByName(sampleNameOf(key), tier);
  }
  await given(t, 1);
  expect(t.engine.runs[0].request.tierMode, "the first request has the mode of the case").toMatchObject({ mode: mode.mode });
  t.engine.runs[0].onStep(equipStep({ kit }));
  t.engine.runs[0].finish(ended("no-gain", 0));
  await flush();
  await toggle("upgrade-slots");
  await given(t, 2);
  const run = t.engine.runs[1];
  expect(run.request.kit, "Every slot starts from the kit of the case").toEqual(kit);
  const number = (fraction) => {
    const [numerator, denominator] = fraction.split("/").map(Number);
    return numerator / denominator;
  };
  finishSlots(run, Object.fromEntries(rows.map((place) => [place.index, place.swaps.map((swap) => ({ ident: swap.item, delta: number(swap.delta) }))])));
  await flush();
  return { t, owned, kit, rows, shown: slotsDrawn() };
}

// ---- what the expanders put in the page --------------------------------------------------------------------------------------------------------------

const clean = (node) => (node?.textContent ?? "").replace(/\s+/g, " ").trim();

/** An addition line of a set, or a step line: its parts. */
const lineOf = (node) => ({
  what: node.querySelector(".step-what")?.textContent ?? null,
  source: node.querySelector(".step-source")?.textContent ?? null,
  cost: node.querySelector(".step-cost")?.textContent ?? null,
  hint: node.querySelector(".step-hint")?.textContent ?? null,
  gain: node.querySelector(".step-gain")?.textContent ?? null,
});

/** The sets drawn: for each, its size, its heading, the line on how it differs from the path, its additions, what it adds up to and anything else it says. */
export const setsDrawn = () =>
  $$("#upgrade-sets .set").map((node) => ({
    k: Number(node.dataset.k),
    heading: clean(node.querySelector("h4")),
    difference: clean(node.querySelector(".set-note")),
    additions: $$("ul.steps > li", node).map(lineOf),
    gain: clean(node.querySelector(".set-gain")),
    other: clean(node.querySelector(".set-other")),
  }));

/**
 * The rows of the Every slot table: the place, what the kit wears there (`wears`: an item; `empty`: nothing) and the swaps, each with its change and what is said of an item the
 * visitor has: `have` ("you have it", and where) when there is a copy to spare, `get` ("get another copy") when the kit wears every copy; both null for an item not on the list.
 */
export const slotsDrawn = () =>
  $$("#upgrade-slots-table tbody tr").map((tr) => ({
    place: clean(tr.querySelector("th")),
    wears: tr.querySelector(".slot-now .owned-name")?.textContent ?? null,
    empty: tr.querySelector(".slot-now .muted")?.textContent ?? null,
    none: tr.querySelector(".slot-none")?.textContent ?? null,
    swaps: $$("ol.swaps > li", tr).map((li) => ({
      what: li.querySelector(".swap-what")?.textContent ?? null,
      delta: li.querySelector(".delta")?.textContent ?? null,
      have: li.querySelector(".swap-have")?.textContent ?? null,
      get: li.querySelector(".swap-get")?.textContent ?? null,
    })),
  }));

export const stateOf = (id) => clean($(`#${id}-state`));
export const faultOf = (id) => clean($(`#${id}-fault .status-text`));
export const faultButtons = (id) => $$(`#${id}-fault button`).map((button) => button.textContent);
export const summaryOf = (id) => clean($(`#${id} > summary`));
