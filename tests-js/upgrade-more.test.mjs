// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// The expanders under the answer of the Upgrade section: Best 2 and 3 sets, Every slot and the tier mode. Each is closed until the visitor opens it, and nothing of its is worked
// out before: the optimizer's client (a stand-in that the test drives, with the answers that protocol.js documents, held to protocol.js's own reader) is given its requests one at a
// time, through the answer's one client, after the path of the answer has ended. The section is the contract copy of the page with the gear input on a table of invented items,
// and the page's own words come from format.js. Every name is invented.

import { afterEach, describe, expect, it, vi } from "vitest";
import { LIMITS, validateRequest } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { dump, empty, row } from "./dump-helpers.mjs";
import { $, $$ } from "./upgrade-helpers.mjs";
import { CLIENT_URL, UPDATED_TEXT, VIEW, addByName, costOf, ended, equipStep, flush, kitOf, mountAnswer, pathStep, textOf } from "./upgrade-answer-helpers.mjs";
import {
  addition,
  answered,
  faultButtons,
  faultOf,
  finishSet,
  finishSlots,
  given,
  isOpen,
  lostSet,
  quiet,
  rawCase,
  sampleCase,
  sampleCaseIds,
  sampleName,
  setsDrawn,
  slotsDrawn,
  stateOf,
  summaryOf,
  toggle,
  toggleFake,
} from "./upgrade-more-helpers.mjs";

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

const PLACES = ["Head", "Face", "Ear 1", "Ear 2", "Neck", "Shoulders", "Arms", "Back", "Wrist 1", "Wrist 2", "Hands", "Finger 1", "Finger 2", "Chest", "Legs", "Feet", "Waist", "Range", "Any slot 1", "Any slot 2", "Main hand", "Off hand"];
const IDS = ["upgrade-sets", "upgrade-slots", "upgrade-mode"];
const failure = (code, message) => Object.assign(new Error(message), { code });
const DIFFERENCE = (k) => `The best ${k} additions made at once; the path adds one at a time, so its first ${k} steps can differ.`;
/** A gear list with a place for each item: worn, in a bag, in the bank, in the shared bank. */
const inventory = () =>
  dump(
    [
      empty("Any Slot"),
      row("Head", "Dunmere Helm +4", 610001),
      row("General 1", "Wicker Basket", 610100, 1, 4),
      row("General 1-Slot1", "Tarn Signet +4", 610002),
      row("Bank1", "Ashen Gorget +4", 610003),
      row("SharedBank1", "Quillmark Bracer +4", 610004),
    ],
    [],
  );
/** Two sets that the optimizer finds for the gear of `answered()` (a Tarn Signet +4): drops, which arrive at +4, and a bracer from a vendor, which arrives at +0. */
const TWO = {
  acquired: [addition("w80308@4", "new", costOf(4, 4)), addition("w80304@4", "new", costOf(4, 4))],
  kit: kitOf({ 0: "w80304@4", 11: "w80301@4", 14: "w80308@4" }),
  gain: 500,
};
const THREE = {
  acquired: [...TWO.acquired, addition("w80302@4", "new", costOf(0, 4))],
  kit: kitOf({ 0: "w80304@4", 8: "w80302@4", 11: "w80301@4", 14: "w80308@4" }),
  gain: 700,
};
/** The section answered, and Best 2 and 3 sets opened. */
async function withSets(options) {
  const t = await answered(options);
  await toggle("upgrade-sets");
  await given(t, 2);
  return t;
}
/** The section answered, and Every slot opened. */
async function withSlots(options) {
  const t = await answered(options);
  await toggle("upgrade-slots");
  await given(t, 2);
  return t;
}
const modeOf = (t, n) => t.engine.runs[n].request.tierMode;

// ---- they come with the answer, closed ------------------------------------------------------------------------------------------------------------

describe("the expanders", () => {
  it("come with the answer and not before, in the order best sets, Every slot, tier mode, each closed and each saying in its summary what it is", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    expect($("#upgrade-more"), "the place for them is there").not.toBeNull();
    expect($("#upgrade-more").hidden).toBe(true);
    addByName("tarn signet", "4");
    await given(t, 1);
    expect($("#upgrade-more").hidden, "nothing to put beside before there is an answer").toBe(true);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    expect($("#upgrade-more").hidden).toBe(false);
    expect([...$("#upgrade-more").children].map((node) => node.id)).toEqual(IDS);
    for (const id of IDS) {
      expect($(`#${id}`).tagName).toBe("DETAILS");
      expect(isOpen(id), id).toBe(false);
    }
    expect(summaryOf("upgrade-sets")).toBe("Best 2 and 3 sets: sets, not a path");
    expect(summaryOf("upgrade-slots")).toBe("Every slot: Swap only this slot");
    expect(summaryOf("upgrade-mode")).toBe("Tier mode: Ready +4");
    expect($("#upgrade-more").nextElementSibling, "below the answer").toBeNull();
    expect($("#upgrade-then").nextElementSibling).toBe($("#upgrade-more"));
  });

  it("send nothing while they are closed: the client has the request of the path and no other", async () => {
    const t = await answered();
    expect(await quiet(t)).toBe(1);
    expect(t.engine.log).toEqual(["stop", "run1"]);
    expect(stateOf("upgrade-sets")).toBe("");
    expect(slotsDrawn()).toEqual([]);
  });

  it("go away with the answer when the list is emptied, and come back closed with the next one", async () => {
    const t = await answered();
    await toggle("upgrade-sets");
    await given(t, 2);
    $("#upgrade-clear").click();
    expect($("#upgrade-more").hidden).toBe(true);
    expect(isOpen("upgrade-sets"), "closed again: the next answer starts as the first did").toBe(false);
    finishSet(t.engine.runs[1], TWO); // (the request that was on the client is over: what it says is not drawn)
    expect(setsDrawn()).toEqual([]);
    addByName("tarn signet", "4");
    await vi.waitFor(() => expect(t.engine.runs.filter((run) => run.request.mode === "farm-path")).toHaveLength(2), { timeout: 5000, interval: 5 });
    const second = t.engine.runs.at(-1);
    second.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    expect($("#upgrade-more").hidden).toBe(false);
    expect(isOpen("upgrade-sets")).toBe(false);
  });
});

// ---- Best 2 and 3 sets ----------------------------------------------------------------------------------------------------------------------------

describe("Best 2 and 3 sets", () => {
  it("sends k=2 and then k=3 when opened, each with the path's scenario, owned pairs and tier mode, as protocol.js takes it, the second only when the first is over", async () => {
    const t = await withSets();
    const [path, two] = t.engine.runs;
    expect(two.request).toEqual({
      v: 1,
      kind: "scenario",
      trio: "pal-mnk-ber",
      level: 50,
      mode: "best-sets",
      scenario: { race: VIEW.race, role: VIEW.role, buffs: VIEW.buffs, evidence: VIEW.evidence, setup: VIEW.setup },
      owned: [["w80301@4", 1]],
      tierMode: { mode: "ready4" },
      k: 2,
      budgetMs: 60_000,
    });
    expect(two.request.owned).toEqual(path.request.owned);
    expect(two.request.budgetMs).toBeLessThanOrEqual(LIMITS.maxBudgetMs);
    expect(validateRequest(two.request), "protocol.js takes it as it is").toEqual(two.request);
    expect(await quiet(t), "the set of 3 waits for the set of 2").toBe(2);
    finishSet(two, TWO);
    await given(t, 3);
    const three = t.engine.runs[2];
    expect(three.request).toEqual({ ...two.request, k: 3 });
    expect(validateRequest(three.request)).toEqual(three.request);
    finishSet(three, THREE);
    expect(await quiet(t), "and that is all").toBe(3);
  });

  it("draws each set with its additions in the words, source and cost of the Next step, its gain over Equip now, and one line on how a set differs from the path", async () => {
    const t = await withSets();
    expect(stateOf("upgrade-sets")).toBe("Working out the best 2 additions…");
    finishSet(t.engine.runs[1], TWO);
    await given(t, 3);
    expect(stateOf("upgrade-sets"), "the set of 2 is there, the set of 3 is being worked out").toBe("Working out the best 3 additions…");
    expect(setsDrawn().map((set) => set.k)).toEqual([2]);
    finishSet(t.engine.runs[2], THREE);
    await flush();
    expect(stateOf("upgrade-sets")).toBe("");
    expect(setsDrawn()).toEqual([
      {
        k: 2,
        heading: "Best set of 2",
        difference: DIFFERENCE(2),
        additions: [
          { what: "Get Fenwick Greaves +4", source: "Source: Plane of Hate", cost: null, hint: null, gain: null },
          { what: "Get Dunmere Helm +4", source: "Source: Plane of Fear, Befallen, Lower Guk and 2 more", cost: null, hint: null, gain: null },
        ],
        gain: "Gain over Equip now: +500 kit value",
        other: "",
      },
      {
        k: 3,
        heading: "Best set of 3",
        difference: DIFFERENCE(3),
        additions: [
          { what: "Get Fenwick Greaves +4", source: "Source: Plane of Hate", cost: null, hint: null, gain: null },
          { what: "Get Dunmere Helm +4", source: "Source: Plane of Fear, Befallen, Lower Guk and 2 more", cost: null, hint: null, gain: null },
          { what: "Get Quillmark Bracer +4", source: "Source: vendor: Freeport", cost: "16 copies to reach +4", hint: null, gain: null },
        ],
        gain: "Gain over Equip now: +700 kit value",
        other: "",
      },
    ]);
  });

  it("words an addition as a new item, another copy or an upgrade, and shows the cost of an upgrade as the copies the worker costed", async () => {
    const t = await withSets({ gear: [["quillmark bracer", "4"], ["quillmark bracer", "2"]], kit: kitOf({ 8: "w80302@4", 9: "w80302@2" }) });
    finishSet(t.engine.runs[1], {
      acquired: [addition("w80302@4", "upgrade", costOf(2, 4, 0), 2), addition("w80302@4", "copy", costOf(0, 4))],
      kit: kitOf({ 8: "w80302@4", 9: "w80302@4", 10: "w80302@4" }),
      gain: 250,
    });
    await flush();
    expect(setsDrawn()[0].additions).toEqual([
      { what: "Upgrade your Quillmark Bracer +2 to +4", source: "Source: vendor: Freeport", cost: "12 copies to reach +4", hint: null, gain: null },
      { what: "Get another Quillmark Bracer +4", source: "Source: vendor: Freeport", cost: "16 copies to reach +4", hint: null, gain: null },
    ]);
  });

  describe("the spare copy", () => {
    const BRACERS = { gear: [["quillmark bracer", "4"], ["quillmark bracer", "2"]], kit: kitOf({ 8: "w80302@4", 9: "w80302@2" }) };

    it("offers to upgrade the spare copy instead of getting another, as the path does, when that costs fewer copies", async () => {
      const t = await withSets(BRACERS);
      finishSet(t.engine.runs[1], { acquired: [addition("w80302@4", "copy", costOf(0, 4))], kit: kitOf({ 8: "w80302@4", 9: "w80302@4" }), gain: 400 });
      await flush();
      expect(setsDrawn()[0].additions).toMatchObject([{ what: "Get another Quillmark Bracer +4", cost: "16 copies to reach +4", hint: "or upgrade your spare +2 copy (cheaper)" }]);
    });

    it("says that it costs the same when a drop arrives at the tier, and so upgrading the spare costs a drop too", async () => {
      const t = await withSets({ gear: [["tarn signet", "4"], ["tarn signet", "2"]], kit: kitOf({ 11: "w80301@4", 12: "w80301@2" }) });
      finishSet(t.engine.runs[1], { acquired: [addition("w80301@4", "copy", costOf(4, 4))], kit: kitOf({ 11: "w80301@4", 12: "w80301@4" }), gain: 90 });
      await flush();
      expect(setsDrawn()[0].additions).toMatchObject([{ what: "Get another Tarn Signet +4", cost: null, hint: "or upgrade your spare +2 copy (the same cost)" }]);
    });

    it("offers nothing when the kit of the set wears the lower copy", async () => {
      const t = await withSets(BRACERS);
      finishSet(t.engine.runs[1], { acquired: [addition("w80302@4", "copy", costOf(0, 4))], kit: kitOf({ 8: "w80302@4", 9: "w80302@2", 10: "w80302@4" }), gain: 400 });
      await flush();
      expect(setsDrawn()[0].additions[0].hint).toBeNull();
    });

    it("offers a spare once: of two copies in a set, the second is not told to use the spare the first was", async () => {
      const t = await withSets(BRACERS);
      finishSet(t.engine.runs[1], {
        acquired: [addition("w80302@4", "copy", costOf(0, 4)), addition("w80302@4", "copy", costOf(0, 4))],
        kit: kitOf({ 8: "w80302@4", 9: "w80302@4", 10: "w80302@4" }),
        gain: 600,
      });
      await flush();
      expect(setsDrawn()[0].additions.map((line) => line.hint)).toEqual(["or upgrade your spare +2 copy (cheaper)", null]);
    });

    it.each([
      ["the upgrade before the copy", [addition("w80302@4", "upgrade", costOf(2, 4, 0), 2), addition("w80302@4", "copy", costOf(0, 4))]],
      ["the copy before the upgrade", [addition("w80302@4", "copy", costOf(0, 4)), addition("w80302@4", "upgrade", costOf(2, 4, 0), 2)]],
    ])("does not offer the copy that the set itself upgrades as a spare (%s)", async (_, acquired) => {
      const t = await withSets(BRACERS);
      finishSet(t.engine.runs[1], { acquired, kit: kitOf({ 8: "w80302@4", 9: "w80302@4", 10: "w80302@4" }), gain: 250 });
      await flush();
      expect(setsDrawn()[0].additions.map((line) => line.hint)).toEqual([null, null]);
    });
  });

  it("says honestly what it found when the solve ran out of time: the best found with its label, never the best", async () => {
    const t = await withSets();
    finishSet(t.engine.runs[1], { ...TWO, gain: 300, status: "time_limit" });
    await flush();
    expect(setsDrawn()[0].gain).toBe("Gain over Equip now: +300 kit value (best found, not proven optimal)");
    expect(setsDrawn()[0].additions).toHaveLength(2);
  });

  it("says that a set was not found in the time, with the words of the protocol, and goes on to the next", async () => {
    const t = await withSets();
    lostSet(t.engine.runs[1]);
    await given(t, 3);
    expect(setsDrawn()).toMatchObject([{ k: 2, heading: "Best set of 2", additions: [], gain: "", other: "Not found in time." }]);
    finishSet(t.engine.runs[2], THREE);
    await flush();
    expect(setsDrawn().map((set) => [set.k, set.other, set.gain])).toEqual([
      [2, "Not found in time.", ""],
      [3, "", "Gain over Equip now: +700 kit value"],
    ]);
  });

  it("says that no addition gains anything when the set is Equip now again, and that fewer additions than the size of the set gain when that is so", async () => {
    const t = await withSets();
    finishSet(t.engine.runs[1], { acquired: [], kit: kitOf({ 11: "w80301@4" }), gain: 0 });
    await given(t, 3);
    finishSet(t.engine.runs[2], { acquired: [addition("w80308@4", "new", costOf(4, 4))], kit: kitOf({ 11: "w80301@4", 14: "w80308@4" }), gain: 80 });
    await flush();
    expect(setsDrawn().map((set) => [set.k, set.additions.length, set.other, set.gain])).toEqual([
      [2, 0, "No addition gains anything.", ""],
      [3, 1, "Only 1 addition gains anything.", "Gain over Equip now: +80 kit value"],
    ]);
  });

  it("shows a gain that is more than nothing but rounds to nothing as +<1", async () => {
    const t = await withSets();
    finishSet(t.engine.runs[1], { acquired: [addition("w80308@4", "new", costOf(4, 4))], kit: kitOf({ 11: "w80301@4", 14: "w80308@4" }), gain: 0.3 });
    await flush();
    expect(setsDrawn()[0].gain).toBe("Gain over Equip now: +<1 kit value");
  });

  it("waits for the path: opened while the path runs, it sends nothing until the path has ended, and says that it waits", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    const path = t.engine.runs[0];
    path.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    await toggle("upgrade-sets");
    expect(await quiet(t)).toBe(1);
    expect(stateOf("upgrade-sets")).toBe("Waiting for the answer above…");
    path.onStep(pathStep(1, { ident: "w80308@4", gain: 50, kit: kitOf({ 11: "w80301@4", 14: "w80308@4" }) }));
    expect(await quiet(t, 30), "a step is not the end").toBe(1);
    path.finish(ended("no-gain", 1));
    await given(t, 2);
    expect(t.engine.runs[1].request).toMatchObject({ mode: "best-sets", k: 2 });
    expect(stateOf("upgrade-sets")).toBe("Working out the best 2 additions…");
    expect($("#upgrade-stop"), "Stop is for the path, and the path is over").toBeNull();
    expect($("#upgrade-progress").hidden).toBe(true);
  });

  it("is not worked out for a visitor who closes it before the path has ended", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    await toggle("upgrade-sets");
    await toggle("upgrade-sets"); // closed again
    t.engine.runs[0].finish(ended("no-gain", 0));
    expect(await quiet(t)).toBe(1);
    expect(stateOf("upgrade-sets")).toBe("");
  });

  it("never begins when the list is emptied while it waits for the path", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    const path = t.engine.runs[0];
    path.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    await toggle("upgrade-sets");
    $("#upgrade-clear").click();
    path.finish(ended("stopped", 0)); // the path that was stopped by Clear ends a moment later
    await flush();
    expect(await quiet(t)).toBe(1);
    expect($("#upgrade-more").hidden).toBe(true);
    expect(stateOf("upgrade-sets")).toBe("");
  });

  it("opened between a change and the request that follows it, waits for that request's path, and asks for the new gear", async () => {
    vi.useFakeTimers();
    const t = mountAnswer();
    addByName("tarn signet", "4");
    await vi.advanceTimersByTimeAsync(600);
    await flush();
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.engine.runs[0].finish(ended("no-gain", 0));
    await flush();
    addByName("corbel cap", "4"); // the change; the pause has not ended
    await toggleFake("upgrade-sets");
    expect(stateOf("upgrade-sets"), "the answer above is about to change").toBe("Waiting for the answer above…");
    expect(t.engine.runs, "and nothing is asked for the old gear").toHaveLength(1);
    await vi.advanceTimersByTimeAsync(600);
    await flush();
    const second = t.engine.runs[1];
    expect(second.request.mode).toBe("farm-path");
    second.onStep(equipStep({ kit: kitOf({ 1: "w80305@4", 11: "w80301@4" }) }));
    second.finish(ended("no-gain", 0));
    await vi.advanceTimersByTimeAsync(20);
    await flush();
    expect(t.engine.runs).toHaveLength(3);
    expect(t.engine.runs[2].request).toMatchObject({ mode: "best-sets", k: 2 });
    expect(t.engine.runs[2].request.owned.map(([ident]) => ident)).toEqual(["w80305@4", "w80301@4"]);
  });

  it("keeps what it has drawn when it is closed and opened again: nothing is asked twice", async () => {
    const t = await withSets();
    finishSet(t.engine.runs[1], TWO);
    await given(t, 3);
    finishSet(t.engine.runs[2], THREE);
    await flush();
    await toggle("upgrade-sets");
    await toggle("upgrade-sets");
    expect(await quiet(t)).toBe(3);
    expect(setsDrawn()).toHaveLength(2);
  });

  it("asks only for what it lacks when it is closed while the first set is being worked out, and opened again: the set of 2 is drawn, the set of 3 waits for the visitor", async () => {
    const t = await withSets();
    await toggle("upgrade-sets"); // closed while the set of 2 is on the client
    finishSet(t.engine.runs[1], TWO);
    await flush();
    expect(await quiet(t), "the visitor closed it: the set of 3 is not begun").toBe(2);
    expect(setsDrawn().map((set) => set.k)).toEqual([2]);
    await toggle("upgrade-sets");
    await given(t, 3);
    expect(t.engine.runs[2].request).toMatchObject({ mode: "best-sets", k: 3 });
    finishSet(t.engine.runs[2], THREE);
    await flush();
    expect(setsDrawn().map((set) => set.k)).toEqual([2, 3]);
    expect(t.spoken.filter((text) => /sets are ready/.test(text))).toEqual(["Best 2 and 3 sets are ready."]);
  });

  it("is not told about the optimizer a second time: the client's code is loaded once for the path and the expanders", async () => {
    const t = await withSets();
    finishSet(t.engine.runs[1], TWO);
    await given(t, 3);
    expect(t.engine.loaded).toEqual([CLIENT_URL]);
    expect(t.engine.options).toHaveLength(1);
  });
});

// ---- Every slot -----------------------------------------------------------------------------------------------------------------------------------

describe("Every slot", () => {
  const KIT = kitOf({ 0: "w80304@4", 4: "w80303@4", 8: "w80302@4", 11: "w80301@4" });
  const FILE = { file: inventory(), gear: [], kit: KIT };

  it("sends one request when opened: the kit of Equip now as kit, its optional buffs as buffs, and the 3 best swaps for a place, with the path's scenario, owned pairs and tier mode", async () => {
    const t = await withSlots({ ...FILE, buffs: [3, 9] });
    const [path, request] = t.engine.runs.map((run) => run.request);
    expect(request).toEqual({
      v: 1,
      kind: "scenario",
      trio: "pal-mnk-ber",
      level: 50,
      mode: "every-slot",
      scenario: path.scenario,
      owned: path.owned,
      tierMode: { mode: "ready4" },
      kit: KIT,
      buffs: [3, 9],
      limit: 3,
      budgetMs: 60_000,
    });
    expect(request.kit).toHaveLength(22);
    expect(validateRequest(request), "protocol.js takes it as it is").toEqual(request);
    expect(await quiet(t), "one request").toBe(2);
  });

  it("draws the 22 places in the page's names: what the kit wears there and the best swaps, each with its change in kit value as the page writes a difference, a loss with the minus sign", async () => {
    const t = await withSlots(FILE);
    finishSlots(t.engine.runs[1], {
      1: [{ ident: "w80305@4", delta: 120 }, { ident: "w80307@4", delta: 40.4 }, { ident: "w80306@4", delta: -3 }],
      4: [{ ident: "w80302@4", delta: 0.3 }, { ident: "w80305@4", delta: -0.2 }],
      11: [{ ident: "w80308@4", delta: -1234 }],
    });
    await flush();
    const rows = slotsDrawn();
    expect(rows.map((r) => r.place)).toEqual(PLACES);
    expect(rows[1]).toEqual({
      place: "Face",
      wears: null,
      empty: "Leave empty",
      none: null,
      swaps: [
        { what: "Corbel Cap +4", delta: "+120", have: null, get: null },
        { what: "Sedge-woven Mantle +4", delta: "+40", have: null, get: null },
        { what: "Reedwater Anklet +4", delta: "−3", have: null, get: null },
      ],
    });
    expect(rows[4]).toMatchObject({ place: "Neck", wears: "Ashen Gorget +4", empty: null });
    expect(rows[4].swaps.map((swap) => swap.delta)).toEqual(["+<1", "−<1"]);
    expect(rows[11]).toMatchObject({ place: "Finger 1", wears: "Tarn Signet +4", swaps: [{ what: "Fenwick Greaves +4", delta: "−1,234" }] });
    expect(rows[0]).toMatchObject({ place: "Head", wears: "Dunmere Helm +4", none: "Nothing else fits here", swaps: [] });
    expect($("#upgrade-slots-table").tagName).toBe("TABLE");
    expect($$("#upgrade-slots-table thead th")).toHaveLength(2);
    expect($$("#upgrade-slots-table tbody th").every((th) => th.getAttribute("scope") === "row")).toBe(true);
  });

  it("marks the swaps of items that the visitor has a copy to spare of with 'you have it' and where the spare is: worn, in a bag, in the bank, in the shared bank, or nothing more for an item added by name", async () => {
    // Equip now wears none of these (it wears a Mantle only), so every copy the visitor has is a spare; two Corbel Caps were added by name
    const t = await withSlots({ file: inventory(), gear: [["corbel cap", "4"], ["corbel cap", "4"]], kit: kitOf({ 7: "w80307@4" }) });
    finishSlots(t.engine.runs[1], {
      1: [{ ident: "w80304@4", delta: 90 }, { ident: "w80301@4", delta: 80 }, { ident: "w80303@4", delta: 70 }],
      5: [{ ident: "w80302@4", delta: 60 }, { ident: "w80305@4", delta: 50 }, { ident: "w80308@4", delta: 40 }],
    });
    await flush();
    const rows = slotsDrawn();
    expect(rows[1].swaps.map((swap) => swap.have)).toEqual(["you have it (worn)", "you have it (in your bags)", "you have it (in your bank)"]);
    expect(rows[5].swaps.map((swap) => [swap.what, swap.have])).toEqual([
      ["Quillmark Bracer +4", "you have it (in your shared bank)"],
      ["Corbel Cap +4", "you have it"],
      ["Fenwick Greaves +4", null],
    ]);
  });

  it("says in one line that it is an evaluation and not a solve, and what it says of an item the visitor has: that there is a copy to spare, or that another copy is to be got", async () => {
    const t = await withSlots(FILE);
    finishSlots(t.engine.runs[1]);
    await flush();
    expect(textOf("#upgrade-slots-note")).toBe(
      'This is an evaluation, not a solve: each figure is the change in kit value if you swapped just that slot and kept the rest of the kit. For an item you have, "you have it" means that you have a copy to spare, and "get another copy" that the kit wears every copy you have.',
    );
  });

  describe("what the page says of an item the visitor has", () => {
    /** A gear list that is a Wicker Basket and the given rows, in the form of the file. */
    const listing = (...places) => dump([empty("Any Slot"), row("General 1", "Wicker Basket", 610100, 1, 4), ...places], []);
    /** One Tarn Signet, in a bag, and the Helm, Gorget and Bracer of the listing above; Equip now wears all four, the ring in Finger 1. */
    const WORN = FILE;

    it("says 'get another copy' of an item that the kit wears in another place when the visitor has no other copy of it: the ring worn in Finger 1 is offered for Finger 2 as a copy to get, and is not said to be in the bags", async () => {
      const t = await withSlots(WORN);
      finishSlots(t.engine.runs[1], { 12: [{ ident: "w80301@4", delta: 300 }, { ident: "w80305@4", delta: 50 }] });
      await flush();
      expect(slotsDrawn()[12]).toMatchObject({
        place: "Finger 2",
        swaps: [
          { what: "Tarn Signet +4", delta: "+300", have: null, get: "get another copy" },
          { what: "Corbel Cap +4", delta: "+50", have: null, get: null },
        ],
      });
      expect(textOf("#upgrade-slots")).not.toContain("in your bags");
    });

    it("counts the copies of each item at each tier on its own: with two +4 copies worn in Finger 1 and 2, the +4 swap for a third place is a copy to get, and the +2 copy is one the visitor has", async () => {
      const t = await withSlots({ gear: [["tarn signet", "4"], ["tarn signet", "4"], ["tarn signet", "2"]], kit: kitOf({ 11: "w80301@4", 12: "w80301@4" }) });
      finishSlots(t.engine.runs[1], { 18: [{ ident: "w80301@4", delta: 200 }, { ident: "w80301@2", delta: 100 }] });
      await flush();
      expect(slotsDrawn()[18].swaps).toEqual([
        { what: "Tarn Signet +4", delta: "+200", have: null, get: "get another copy" },
        { what: "Tarn Signet +2", delta: "+100", have: "you have it", get: null },
      ]);
    });

    it("says that the visitor has it, and where the spare is, when there is a copy to spare, and not where the copy that the kit wears is", async () => {
      // one Tarn Signet in a bag and one in the bank; Equip now wears one in Finger 1: the copies the kit wears come first from the bags, so the spare is in the bank
      const file = listing(row("General 1-Slot1", "Tarn Signet +4", 610002), row("Bank1", "Tarn Signet +4", 610002));
      const t = await withSlots({ file, gear: [], kit: kitOf({ 11: "w80301@4" }) });
      finishSlots(t.engine.runs[1], { 12: [{ ident: "w80301@4", delta: 300 }] });
      await flush();
      expect(slotsDrawn()[12].swaps).toEqual([{ what: "Tarn Signet +4", delta: "+300", have: "you have it (in your bank)", get: null }]);
    });

    it("uses the copy that is worn first for the kit, as Equip now's notes do: of a copy worn and a copy in the bank, the one in the bank is the spare", async () => {
      const file = listing(row("Fingers", "Tarn Signet +4", 610002), row("Bank1", "Tarn Signet +4", 610002));
      const t = await withSlots({ file, gear: [], kit: kitOf({ 11: "w80301@4" }) });
      finishSlots(t.engine.runs[1], { 12: [{ ident: "w80301@4", delta: 300 }] });
      await flush();
      expect(slotsDrawn()[12].swaps[0].have).toBe("you have it (in your bank)");
    });

    it("shows every swap the optimizer gives, in its order, and hides none: a copy to get, a spare and an item the visitor does not have", async () => {
      const t = await withSlots({ file: inventory(), gear: [["corbel cap", "4"]], kit: KIT });
      finishSlots(t.engine.runs[1], {
        18: [
          { ident: "w80301@4", delta: 500 }, // the ring: the visitor has one, and the kit wears it in Finger 1
          { ident: "w80305@4", delta: 300 }, // the cap: the visitor has one, and the kit does not wear it
          { ident: "w80308@4", delta: 150 }, // greaves: the visitor does not have them
        ],
      });
      await flush();
      expect(slotsDrawn()[18].swaps).toEqual([
        { what: "Tarn Signet +4", delta: "+500", have: null, get: "get another copy" },
        { what: "Corbel Cap +4", delta: "+300", have: "you have it", get: null },
        { what: "Fenwick Greaves +4", delta: "+150", have: null, get: null },
      ]);
      expect(slotsDrawn().map((place) => place.none), "no place says that its swaps could not be made").not.toContain("None of the best swaps here is one you could make");
    });
  });

  it("waits for the path and sends nothing when Equip now found no kit, and says so", async () => {
    const noKit = { ...equipStep({ kit: null, status: "time_limit", proven: false, label: "not found in time" }) };
    const t = await answered({ equip: noKit });
    await toggle("upgrade-slots");
    await toggle("upgrade-sets");
    expect(await quiet(t)).toBe(1);
    expect(stateOf("upgrade-slots")).toBe("Equip now was not found in time, so there is nothing to work from.");
    expect(stateOf("upgrade-sets")).toBe("Equip now was not found in time, so there is nothing to work from.");
  });

  it("works from the Equip now the path had when it failed after it: the kit is there, and so is the swap", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.engine.runs[0].fail(failure("worker-failed", "The optimizer stopped working."));
    await flush();
    await toggle("upgrade-slots");
    await given(t, 2);
    expect(t.engine.runs[1].request).toMatchObject({ mode: "every-slot", kit: kitOf({ 11: "w80301@4" }) });
  });

  it("says that there is no answer to work from, and sends nothing, when the path that follows a change failed before Equip now", async () => {
    const t = await answered();
    addByName("corbel cap", "4");
    await given(t, 2);
    t.engine.runs[1].fail(failure("engine-load", "The optimizer's data file could not be loaded (404)."));
    await flush();
    await toggle("upgrade-sets");
    expect(await quiet(t)).toBe(2);
    expect(stateOf("upgrade-sets")).toBe("There is no answer above to work from yet.");
  });
});

// ---- the cases of the optimizer's own fixtures ------------------------------------------------------------------------------------------------------------

describe("Every slot on the cases of the optimizer's own fixtures", () => {
  /**
   * What the page shows of a change in kit value, worked out here from the exact fraction the Python reference wrote ("p/q"): rounded half up (floor of the value plus a half),
   * with its sign (the page's minus sign) and its thousands separated; a change that is more than nothing and rounds to nothing is "+<1" or "−<1". Not read from the page.
   */
  const shownDelta = (fraction) => {
    const [numerator, denominator = 1n] = fraction.split("/").map(BigInt); // ("5" is 5/1: the reference writes every exact number as p/q, and a bare integer is read the same)
    const doubled = 2n * numerator + denominator; // floor((p / q) + 1/2) = floor((2p + q) / 2q), q > 0
    let rounded = doubled / (2n * denominator);
    if (doubled % (2n * denominator) < 0n) rounded -= 1n; // (BigInt division truncates toward zero)
    if (numerator === 0n) return "0"; // nothing: the page writes a zero change as 0, with no sign
    if (rounded === 0n) return numerator > 0n ? "+<1" : "\u2212<1";
    const digits = (rounded < 0n ? -rounded : rounded).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return `${rounded < 0n ? "\u2212" : "+"}${digits}`;
  };

  /** What the page draws of a swap the case expects, by the rules of the case: the Python delta, and for an item the visitor has, "you have it" when a copy is spare or "get another copy" when the kit wears every copy elsewhere. */
  const expectedSwap = (place, swap, owned, kit) => {
    const count = owned.get(swap.item);
    const elsewhere = kit.filter((ident, index) => index !== place.index && ident === swap.item).length;
    const have = count !== undefined && count > elsewhere;
    return { what: sampleName(swap.item), delta: shownDelta(swap.delta), have: have ? "you have it" : null, get: count !== undefined && !have ? "get another copy" : null };
  };

  /** The swaps of the case that offer an item the visitor has and the kit wears in every copy it has elsewhere ("get another copy"), with their places. */
  const copiesToGet = (rows, owned, kit) =>
    rows.flatMap((place) => place.swaps.filter((swap) => owned.has(swap.item) && owned.get(swap.item) <= kit.filter((ident, index) => index !== place.index && ident === swap.item).length).map((swap) => ({ place, swap })));

  it("offers a copy to get for an item that the visitor has once and the kit wears elsewhere, and does not hide it (upgrade-007: the second Wrist and both Any slots are offered the item of the first Wrist)", async () => {
    const { shown, rows, owned, kit } = await sampleCase("upgrade-007");
    // (which places have such a swap is what the Python rows say: the sample is made from a seed, so the places and the deltas are read from it and not written here)
    const offers = copiesToGet(rows, owned, kit).filter(({ swap }) => owned.get(swap.item) === 1);
    expect(offers.map(({ place }) => place.index), "the places the Python rows offer a copy to get").toEqual([9, 18, 19]);
    expect(new Set(offers.map(({ swap }) => swap.item)), "all of them the item of the first Wrist").toEqual(new Set([kit[8]]));
    for (const { place, swap } of offers) {
      expect(shown[place.index].swaps.find((drawn) => drawn.what === sampleName(swap.item)), `place ${place.index}`).toEqual(expectedSwap(place, swap, owned, kit));
      expect(shown[place.index].swaps.find((drawn) => drawn.what === sampleName(swap.item)).get).toBe("get another copy");
    }
    expect(shown[8].swaps, "the first Wrist, which has the item and is offered one it does not have").toEqual(rows[8].swaps.map((swap) => expectedSwap(rows[8], swap, owned, kit)));
    expect(shown.map((place) => place.none)).not.toContain("None of the best swaps here is one you could make");
  });

  /** The tier a mode of the tiers gives every item, or null where it depends on the item (as it arrives). */
  const grantedTier = (mode) => (mode.mode === "ready4" ? 4 : mode.mode === "fixed" ? mode.N : null);
  const elsewhereOf = (raw, index, ident) => raw.kit.filter((worn, at) => at !== index && worn === ident).length;
  /** Every swap of the case, with its place and the counts that decide what the page says of it. */
  const swapsOf = (raw) =>
    raw.rows.flatMap((place) => place.swaps.map((swap) => ({ place, swap, count: raw.owned.get(swap.item), elsewhere: elsewhereOf(raw, place.index, swap.item) })));

  it("does the same in the mode 'as it arrives': a case of that mode whose rows offer an item the visitor has in every copy the kit wears elsewhere is drawn with 'get another copy' and the delta Python computed", async () => {
    const found = sampleCaseIds().map(rawCase).filter((raw) => raw.mode.mode === "arrives" && swapsOf(raw).some(({ count, elsewhere }) => count !== undefined && count <= elsewhere));
    expect(found.length, "the sample has a case in the mode 'as it arrives' with a copy to get (fixture_plan.SAMPLE_SESSIONS is chosen to have one)").toBeGreaterThan(0);
    for (const raw of found) {
      const { shown, rows, owned, kit } = await sampleCase(raw.id);
      const offers = copiesToGet(rows, owned, kit);
      expect(offers.length, raw.id).toBeGreaterThan(0);
      for (const { place, swap } of offers) {
        const drawn = shown[place.index].swaps.find((one) => one.what === sampleName(swap.item));
        expect(drawn, `${raw.id}, place ${place.index}`).toEqual(expectedSwap(place, swap, owned, kit));
        expect(drawn.get, `${raw.id}, place ${place.index}`).toBe("get another copy");
        expect(drawn.have).toBeNull();
      }
      expect(shown.flatMap((place) => place.swaps).filter((swap) => swap.get === "get another copy"), `${raw.id}: no more copies to get than the rows offer`).toHaveLength(offers.length);
      document.body.innerHTML = "";
    }
  });

  it("offers an item the visitor has at a tier the mode does not give because a copy is spare, and says 'you have it' of it (the sample has such an offer; upgrade-007: Head)", async () => {
    const found = sampleCaseIds().map(rawCase).filter((raw) => grantedTier(raw.mode) !== null && swapsOf(raw).some(({ swap, count, elsewhere }) => count !== undefined && count > elsewhere && Number(swap.item.split("@")[1]) !== grantedTier(raw.mode)));
    expect(found.length, "the sample has a case of a tier the mode gives with such an offer (fixture_plan.SAMPLE_SESSIONS)").toBeGreaterThan(0);
    expect(found.map((raw) => raw.id)).toContain("upgrade-007");
    for (const raw of found) {
      const { shown, owned, kit } = await sampleCase(raw.id);
      const granted = grantedTier(raw.mode);
      const spare = swapsOf(raw).filter(({ swap, count, elsewhere }) => count !== undefined && count > elsewhere && Number(swap.item.split("@")[1]) !== granted);
      for (const { place, swap } of spare) {
        const drawn = shown[place.index].swaps.find((one) => one.what === sampleName(swap.item));
        expect(drawn, `${raw.id}, place ${place.index}`).toEqual(expectedSwap(place, swap, owned, kit));
        expect([drawn.have, drawn.get], `${raw.id}, place ${place.index}`).toEqual(["you have it", null]);
      }
      document.body.innerHTML = "";
    }
  });

  it("writes a change of nothing as 0, with no sign (upgrade-007: Off hand), and the writer of the expected text agrees", async () => {
    expect(shownDelta("0/1")).toBe("0");
    expect(shownDelta("5")).toBe("+5");
    expect(shownDelta("-7/2")).toBe("\u22123"); // (rounded half up: -3.5 is -3)
    const zero = sampleCaseIds().map(rawCase).flatMap((raw) => swapsOf(raw).filter(({ swap }) => swap.delta === "0/1").map((one) => ({ ...one, id: raw.id })));
    expect(zero.length, "the sample has a swap that changes nothing").toBeGreaterThan(0);
    const { id, place, swap } = zero[0];
    const { shown } = await sampleCase(id);
    expect(shown[place.index].swaps.find((one) => one.what === sampleName(swap.item)).delta, `${id}, place ${place.index}`).toBe("0");
  });

  it("says 'you have it' of a spare and nothing of an item the visitor does not have, and of one the visitor has twice and the kit wears in no other place (upgrade-007: Head and Chest)", async () => {
    const { shown, rows, owned, kit } = await sampleCase("upgrade-007");
    // Head: each swap is the Python delta, with "you have it" for an item the visitor has and a copy is spare, and nothing for one the visitor does not have
    expect(shown[0].swaps.map((swap) => [swap.delta, swap.have, swap.get])).toEqual(rows[0].swaps.map((swap) => {
      const drawn = expectedSwap(rows[0], swap, owned, kit);
      return [drawn.delta, drawn.have, drawn.get];
    }));
    expect(rows[0].swaps.map((swap) => (owned.has(swap.item) ? "owned" : "not owned")), "Head is offered an item the visitor has, and then two they do not").toEqual(["owned", "not owned", "not owned"]);
    expect(shown[0].swaps.map((swap) => swap.have), "the item the visitor has, and nothing of the others").toEqual(["you have it", null, null]);
    const twice = rows[13].swaps.find((swap) => owned.get(swap.item) === 2); // (the Chest's other swap is an item the visitor does not have)
    expect(twice, "the Chest is offered an item the visitor has twice").toBeDefined();
    expect(shown[13].swaps.find((swap) => swap.what === sampleName(twice.item)), "the Chest").toMatchObject({ have: "you have it", get: null });
  });

  it.each([["upgrade-007", 8], ["upgrade-002", 8], ["upgrade-009", 0], ["upgrade-014", 0]])("%s: every swap is drawn, in the optimizer's order, and says 'you have it' when the kit leaves a copy, 'get another copy' when it does not, and nothing of an item not on the list", async (id, least) => {
    const { shown, rows, owned, kit } = await sampleCase(id);
    let ofOwned = 0;
    for (const place of rows) {
      expect(shown[place.index].swaps.map((swap) => swap.what), `place ${place.index}`).toEqual(place.swaps.map((swap) => sampleName(swap.item)));
      place.swaps.forEach((swap, rank) => {
        const drawn = shown[place.index].swaps[rank];
        const count = owned.get(swap.item);
        if (count === undefined) {
          expect([drawn.have, drawn.get], `place ${place.index}, swap ${rank}: not on the list`).toEqual([null, null]);
          return;
        }
        ofOwned += 1;
        const elsewhere = kit.filter((ident, index) => index !== place.index && ident === swap.item).length;
        if (count > elsewhere) expect([drawn.have?.startsWith("you have it"), drawn.get], `place ${place.index}, swap ${rank}: a copy to spare`).toEqual([true, null]);
        else expect([drawn.have, drawn.get], `place ${place.index}, swap ${rank}: every copy is worn`).toEqual([null, "get another copy"]);
      });
    }
    expect(ofOwned, "the case has swaps of items the visitor has to look at").toBeGreaterThan(least);
  });
});

// ---- the tier mode --------------------------------------------------------------------------------------------------------------------------------

describe("Tier mode", () => {
  const choose = (id) => {
    $(`#${id}`).click();
  };
  const setSelect = (id, value) => {
    $(`#${id}`).value = value;
    $(`#${id}`).dispatchEvent(new Event("change", { bubbles: true }));
  };

  it("has the three modes: Ready +4 (the default), As it arrives with a difficulty from +0 to +4 (+4 by default), and Fixed with a tier from +0 to +10, in the page's words for a tier", async () => {
    await answered();
    const radios = $$('#upgrade-mode input[type="radio"]');
    expect(radios.map((radio) => [radio.value, radio.checked])).toEqual([["ready4", true], ["arrives", false], ["fixed", false]]);
    expect(radios.every((radio) => radio.name === "upgrade-mode" && $(`label[for="${radio.id}"]`) !== null)).toBe(true);
    expect($$('#upgrade-mode label[for^="upgrade-mode-"]').map((label) => label.textContent)).toEqual(expect.arrayContaining(["Ready +4", "As it arrives", "Fixed"]));
    expect($$("#upgrade-mode-d option").map((o) => o.textContent)).toEqual(["+0", "+1", "+2", "+3", "+4"]);
    expect($("#upgrade-mode-d").value).toBe("4");
    expect($$("#upgrade-mode-n option").map((o) => o.textContent)).toEqual(["+0", "+1", "+2", "+3", "+4", "+5", "+6", "+7", "+8", "+9", "+10"]);
    expect($("#upgrade-mode-n").value).toBe("4");
    expect($("label[for='upgrade-mode-d']").textContent).toBe("Drops arrive at");
    expect($("label[for='upgrade-mode-n']").textContent).toBe("Fixed at");
    expect($("#upgrade-mode fieldset legend").textContent).toBe("Which tier the additions are worked out at");
  });

  it("restarts the answer with the new tier mode, as any other change does (the path is stopped, one request is sent after the pause), and says the mode in force in its summary", async () => {
    const t = await answered();
    choose("upgrade-mode-fixed");
    await given(t, 2);
    expect(t.engine.log).toEqual(["stop", "run1", "stop", "run2"]);
    expect(modeOf(t, 1)).toEqual({ mode: "fixed", N: 4 });
    expect(t.engine.runs[1].request.mode).toBe("farm-path");
    expect(validateRequest(t.engine.runs[1].request)).toEqual(t.engine.runs[1].request);
    expect(summaryOf("upgrade-mode")).toBe("Tier mode: Fixed +4");
    setSelect("upgrade-mode-n", "7");
    await given(t, 3);
    expect(modeOf(t, 2)).toEqual({ mode: "fixed", N: 7 });
    expect(summaryOf("upgrade-mode")).toBe("Tier mode: Fixed +7");
    setSelect("upgrade-mode-d", "2"); // a choice of the difficulty is a choice of the mode that uses it
    await given(t, 4);
    expect($("#upgrade-mode-arrives").checked).toBe(true);
    expect(modeOf(t, 3)).toEqual({ mode: "arrives", D: 2 });
    expect(summaryOf("upgrade-mode")).toBe("Tier mode: As it arrives, drops at +2");
    choose("upgrade-mode-ready4");
    await given(t, 5);
    expect(modeOf(t, 4)).toEqual({ mode: "ready4" });
    expect(summaryOf("upgrade-mode")).toBe("Tier mode: Ready +4");
    for (const run of t.engine.runs) expect(validateRequest(run.request)).toEqual(run.request);
  });

  it("does not restart for nothing: a mode chosen and then the one it was, within the pause, sends nothing", async () => {
    vi.useFakeTimers();
    const t = mountAnswer();
    addByName("tarn signet", "4");
    await vi.advanceTimersByTimeAsync(600);
    await flush();
    expect(t.engine.runs).toHaveLength(1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    const log = [...t.engine.log];
    choose("upgrade-mode-fixed");
    await vi.advanceTimersByTimeAsync(100);
    choose("upgrade-mode-ready4");
    await vi.advanceTimersByTimeAsync(2000);
    await flush();
    expect(t.engine.log).toEqual(log);
    expect(summaryOf("upgrade-mode")).toBe("Tier mode: Ready +4");
  });

  it("recomputes the expanders that are open for the new mode, and leaves the closed ones alone", async () => {
    const t = await withSets();
    finishSet(t.engine.runs[1], TWO);
    await given(t, 3);
    finishSet(t.engine.runs[2], THREE);
    await flush();
    expect(setsDrawn()).toHaveLength(2);
    choose("upgrade-mode-fixed");
    setSelect("upgrade-mode-n", "6");
    await given(t, 4);
    expect(t.engine.runs[3].request).toMatchObject({ mode: "farm-path", tierMode: { mode: "fixed", N: 6 } });
    expect(setsDrawn(), "the sets of the old mode are not shown with the answer of the new one").toEqual([]);
    expect(stateOf("upgrade-sets")).toBe("Waiting for the answer above…");
    const path = t.engine.runs[3];
    path.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    path.finish(ended("no-gain", 0));
    await given(t, 5);
    expect(t.engine.runs[4].request).toMatchObject({ mode: "best-sets", k: 2, tierMode: { mode: "fixed", N: 6 } });
    expect(await quiet(t), "Every slot is closed: it is not asked").toBe(5);
  });

  it("recomputes Every slot, when it is open, with the kit of the new Equip now", async () => {
    const t = await withSlots();
    finishSlots(t.engine.runs[1]);
    await flush();
    expect(slotsDrawn()).toHaveLength(22);
    setSelect("upgrade-mode-d", "1");
    await given(t, 3);
    expect(slotsDrawn()).toEqual([]);
    const path = t.engine.runs[2];
    path.onStep(equipStep({ kit: kitOf({ 12: "w80301@4" }) }));
    path.finish(ended("no-gain", 0));
    await given(t, 4);
    expect(t.engine.runs[3].request).toMatchObject({ mode: "every-slot", tierMode: { mode: "arrives", D: 1 }, kit: kitOf({ 12: "w80301@4" }) });
  });

  it("keeps the mode when the list is emptied, and uses it for the next request", async () => {
    const t = await answered();
    setSelect("upgrade-mode-n", "9");
    await given(t, 2);
    $("#upgrade-clear").click();
    expect(await quiet(t, 80)).toBe(2);
    addByName("tarn signet", "4");
    await given(t, 3);
    expect(modeOf(t, 2)).toEqual({ mode: "fixed", N: 9 });
    t.engine.runs[2].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    expect(summaryOf("upgrade-mode")).toBe("Tier mode: Fixed +9");
  });
});

// ---- a change marks what was computed as old -------------------------------------------------------------------------------------------------------

describe("a change of the gear, the view or the tier mode", () => {
  async function computedSets(options) {
    const t = await withSets(options);
    finishSet(t.engine.runs[1], TWO);
    await given(t, 3);
    finishSet(t.engine.runs[2], THREE);
    await flush();
    expect(setsDrawn()).toHaveLength(2);
    return t;
  }

  it("marks the sets that were computed as old: they are cleared when the new request is sent, never drawn again, and worked out anew after the path, for the new gear", async () => {
    const t = await computedSets();
    addByName("corbel cap", "4"); // a change of the gear
    await given(t, 4);
    expect(t.engine.runs[3].request.mode).toBe("farm-path");
    expect(setsDrawn(), "the old answer is gone").toEqual([]);
    expect(stateOf("upgrade-sets")).toBe("Waiting for the answer above…");
    t.engine.runs[3].onStep(equipStep({ kit: kitOf({ 1: "w80305@4", 11: "w80301@4" }) }));
    t.engine.runs[3].finish(ended("no-gain", 0));
    await given(t, 5);
    expect(t.engine.runs[4].request).toMatchObject({ mode: "best-sets", k: 2 });
    expect(t.engine.runs[4].request.owned.map(([ident]) => ident)).toEqual(["w80305@4", "w80301@4"]);
    expect(setsDrawn()).toEqual([]);
  });

  it("does the same for a change of the view the request uses", async () => {
    const t = await computedSets();
    t.setView({ role: "melee" });
    await given(t, 4);
    expect(setsDrawn()).toEqual([]);
    t.engine.runs[3].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.engine.runs[3].finish(ended("no-gain", 0));
    await given(t, 5);
    expect(t.engine.runs[4].request.scenario.role).toBe("melee");
  });

  it("does not show a closed expander's old answer when it is opened after a change: it is worked out when it is next opened", async () => {
    const t = await computedSets();
    await toggle("upgrade-sets"); // closed, with its two sets in it
    addByName("corbel cap", "4");
    await given(t, 4);
    t.engine.runs[3].onStep(equipStep({ kit: kitOf({ 1: "w80305@4", 11: "w80301@4" }) }));
    t.engine.runs[3].finish(ended("no-gain", 0));
    expect(await quiet(t), "closed: nothing is asked").toBe(4);
    expect(setsDrawn(), "and nothing of the old answer is left in it").toEqual([]);
    await toggle("upgrade-sets");
    await given(t, 5);
    expect(t.engine.runs[4].request.owned.map(([ident]) => ident)).toEqual(["w80305@4", "w80301@4"]);
    expect(setsDrawn()).toEqual([]);
  });

  it("ends the request of an expander that is on the client when a change is made, by taking it back, so that the new path begins at once and does not wait for a solve that nobody wants", async () => {
    const t = await withSets();
    const old = t.engine.runs[1]; // the set of 2 is on the client, and nobody answers it
    expect(stateOf("upgrade-sets")).toBe("Working out the best 2 additions…");
    addByName("corbel cap", "4"); // a change of the gear
    await given(t, 3); // the new path is given to the client though the set was not answered
    expect(t.engine.log.slice(-3), "the path in flight is stopped (there is none), the set is taken back, the new path is given").toEqual(["stop", "withdraw", "run3"]);
    expect(t.engine.log, "the client is never told to cancel what every part of the page asked for").not.toContain("cancel");
    expect(old.settled).toBe(true);
    expect(old.withdrawn).toBe(true);
    expect(t.engine.runs[2].request.mode).toBe("farm-path");
    expect(setsDrawn(), "nothing of the old set is drawn").toEqual([]);
    expect(faultOf("upgrade-sets"), "a request that was ended is no fault").toBe("");
    expect(stateOf("upgrade-sets"), "the expander says that it waits for the new answer").toBe("Waiting for the answer above…");
    finishSet(old, TWO); // (an answer that came after all is not drawn either)
    await flush();
    expect(setsDrawn()).toEqual([]);
    expect(t.spoken.filter((text) => /sets are ready|Best 2 and 3 sets:/.test(text))).toEqual([]);
  });

  it("ends the request of Every slot the same way", async () => {
    const t = await withSlots();
    addByName("corbel cap", "4");
    await given(t, 3);
    expect(t.engine.log.slice(-3)).toEqual(["stop", "withdraw", "run3"]);
    expect(t.engine.runs[1].settled).toBe(true);
    expect(slotsDrawn()).toEqual([]);
    expect(faultOf("upgrade-slots")).toBe("");
  });

  it("ends it when the list is emptied too: Clear does not leave a solve running on the client", async () => {
    const t = await withSets();
    $("#upgrade-clear").click();
    expect(t.engine.log.slice(-2)).toEqual(["stop", "withdraw"]);
    expect(t.engine.runs[1].settled).toBe(true);
    expect($("#upgrade-more").hidden).toBe(true);
  });

  it("has nothing to end when the request of the expander has not begun, nor when what is on the client is the path: the path is stopped, and the worker stays", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    await toggle("upgrade-sets"); // it waits for the path, which goes on
    addByName("corbel cap", "4");
    await given(t, 2); // the path was stopped (it ended a moment later), and the new one is given
    expect(t.engine.log, "no request of an expander was on the client: nothing was ended but the path, and that by stop").not.toContain("withdraw");
    expect(t.engine.log.slice(-3)).toEqual(["run1", "stop", "run2"]);
  });

  it("never draws a result that comes between the change and the new request, in the pause", async () => {
    vi.useFakeTimers();
    const t = mountAnswer();
    addByName("tarn signet", "4");
    await vi.advanceTimersByTimeAsync(600);
    await flush();
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.engine.runs[0].finish(ended("no-gain", 0));
    await flush();
    await toggleFake("upgrade-sets");
    expect(t.engine.runs).toHaveLength(2);
    addByName("corbel cap", "4"); // the change; the pause has not ended
    finishSet(t.engine.runs[1], TWO); // the answer for the gear before it
    await flush();
    expect(setsDrawn(), "it is old as soon as the change is made").toEqual([]);
    await vi.advanceTimersByTimeAsync(700);
    await flush();
    expect(t.engine.runs.at(-1).request.mode).toBe("farm-path");
    expect(setsDrawn()).toEqual([]);
  });

  /** The section with the sets open and drawn (fake timers: the pause of 600 ms is the section's own). */
  async function setsDrawnUnderFakeTimers() {
    vi.useFakeTimers();
    const t = mountAnswer();
    addByName("tarn signet", "4");
    await vi.advanceTimersByTimeAsync(600);
    await flush();
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.engine.runs[0].finish(ended("no-gain", 0));
    await flush();
    await toggleFake("upgrade-sets");
    finishSet(t.engine.runs[1], TWO);
    await vi.advanceTimersByTimeAsync(20);
    await flush();
    finishSet(t.engine.runs[2], THREE);
    await flush();
    expect(setsDrawn()).toHaveLength(2);
    return t;
  }
  const takeOut = (ident) => $$("#upgrade-owned li").find((li) => li.dataset.ident === ident).querySelector("button").click();

  it("keeps what the expanders have drawn, and asks for nothing, when the change is undone within the pause (an item added and taken out)", async () => {
    const t = await setsDrawnUnderFakeTimers();
    const log = [...t.engine.log];
    addByName("corbel cap", "4");
    await vi.advanceTimersByTimeAsync(100);
    takeOut("w80305@4");
    await vi.advanceTimersByTimeAsync(2000);
    await flush();
    expect(t.engine.log, "nothing was stopped, ended or asked").toEqual(log);
    expect(t.engine.runs).toHaveLength(3);
    expect(setsDrawn(), "and both sets are where they were").toHaveLength(2);
    expect(stateOf("upgrade-sets")).toBe("");
  });

  it("keeps the request that was on the client for an expander when the change that came while it was worked out is undone: its answer is drawn when it comes", async () => {
    vi.useFakeTimers();
    const t = mountAnswer();
    addByName("tarn signet", "4");
    await vi.advanceTimersByTimeAsync(600);
    await flush();
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.engine.runs[0].finish(ended("no-gain", 0));
    await flush();
    await toggleFake("upgrade-sets"); // the set of 2 is on the client
    addByName("corbel cap", "4");
    await vi.advanceTimersByTimeAsync(100);
    takeOut("w80305@4");
    await vi.advanceTimersByTimeAsync(2000);
    await flush();
    expect(t.engine.log, "the request was not ended: the change that would have made it old is undone").not.toContain("withdraw");
    finishSet(t.engine.runs[1], TWO);
    await vi.advanceTimersByTimeAsync(20);
    await flush();
    expect(setsDrawn().map((set) => set.k), "the set of 2 is drawn").toEqual([2]);
    expect(t.engine.runs[2].request).toMatchObject({ mode: "best-sets", k: 3 });
  });

  it("asks again, after the pause, for what came in the pause and so was not drawn", async () => {
    vi.useFakeTimers();
    const t = mountAnswer();
    addByName("tarn signet", "4");
    await vi.advanceTimersByTimeAsync(600);
    await flush();
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.engine.runs[0].finish(ended("no-gain", 0));
    await flush();
    await toggleFake("upgrade-sets");
    addByName("corbel cap", "4"); // a change: until the pause is over nobody knows whether it stands
    finishSet(t.engine.runs[1], TWO); // the answer comes in the pause: it is not drawn
    await flush();
    expect(setsDrawn()).toEqual([]);
    await vi.advanceTimersByTimeAsync(100);
    takeOut("w80305@4"); // and the change is undone
    await vi.advanceTimersByTimeAsync(2000);
    await flush();
    expect(t.engine.runs.filter((run) => run.request.mode === "farm-path"), "the path is not sent again").toHaveLength(1);
    expect(t.engine.runs.at(-1).request, "the set that was not drawn is asked for again").toMatchObject({ mode: "best-sets", k: 2 });
    expect(t.engine.runs).toHaveLength(3);
  });

  describe("a new file in which a copy has moved and nothing else has changed", () => {
    const listing = (...places) => dump([empty("Any Slot"), row("General 1", "Wicker Basket", 610100, 1, 4), ...places], []);
    // two Tarn Signets: one in a bag and one in the bank, and then one in the bank and one in the shared bank
    const BEFORE = () => listing(row("General 1-Slot1", "Tarn Signet +4", 610002), row("Bank1", "Tarn Signet +4", 610002));
    const AFTER = () => listing(row("Bank1", "Tarn Signet +4", 610002), row("SharedBank1", "Tarn Signet +4", 610002));
    const equipWhere = () => $$("#upgrade-equip tbody tr").map((tr) => tr.querySelector(".equip-where")?.textContent ?? null);

    it("keeps every answer, asks for nothing, and says where the copies are now: in Equip now's notes and in Every slot's 'you have it'", async () => {
      const t = await answered({ file: BEFORE(), gear: [], kit: kitOf({ 11: "w80301@4" }) });
      await toggle("upgrade-slots");
      await given(t, 2);
      finishSlots(t.engine.runs[1], { 12: [{ ident: "w80301@4", delta: 300 }] });
      await flush();
      expect(equipWhere()[11]).toBe("in your bags: move to worn");
      expect(slotsDrawn()[12].swaps[0].have).toBe("you have it (in your bank)");
      const log = [...t.engine.log];
      await t.gear.readFile(new File([AFTER()], "inventory.txt"));
      await vi.waitFor(() => expect(equipWhere()[11]).toBe("in your bank: move to worn"), { timeout: 5000, interval: 5 });
      expect(slotsDrawn()[12].swaps[0].have).toBe("you have it (in your shared bank)");
      expect(await quiet(t), "nothing was asked again").toBe(2);
      expect(t.engine.log).toEqual(log);
      expect(slotsDrawn()).toHaveLength(22);
    });
  });
});

// ---- scheduling -----------------------------------------------------------------------------------------------------------------------------------

describe("the requests of the expanders", () => {
  it("are given to the client one at a time: the expander that was opened first is worked out first, an expander's own requests in order, and the other waits its turn", async () => {
    const t = await answered();
    await toggle("upgrade-sets");
    await given(t, 2);
    expect(t.engine.runs[1].request).toMatchObject({ mode: "best-sets", k: 2 });
    await toggle("upgrade-slots");
    expect(stateOf("upgrade-slots")).toBe("Waiting its turn…");
    expect(await quiet(t), "Every slot waits for the sets").toBe(2);
    finishSet(t.engine.runs[1], TWO);
    await given(t, 3);
    expect(t.engine.runs[2].request, "the set of 3 is the sets' own, and comes before the next expander").toMatchObject({ mode: "best-sets", k: 3 });
    expect(await quiet(t)).toBe(3);
    finishSet(t.engine.runs[2], THREE);
    await given(t, 4);
    expect(t.engine.runs[3].request).toMatchObject({ mode: "every-slot" });
    finishSlots(t.engine.runs[3]);
    await flush();
    expect(setsDrawn()).toHaveLength(2);
    expect(slotsDrawn()).toHaveLength(22);
    expect(stateOf("upgrade-slots")).toBe("");
  });

  it("works Every slot out first when it was opened first, and the sets after it", async () => {
    const t = await answered();
    await toggle("upgrade-slots");
    await given(t, 2);
    expect(t.engine.runs[1].request.mode).toBe("every-slot");
    await toggle("upgrade-sets");
    expect(await quiet(t)).toBe(2);
    finishSlots(t.engine.runs[1]);
    await given(t, 3);
    expect(t.engine.runs[2].request).toMatchObject({ mode: "best-sets", k: 2 });
  });

  /** The section with its path running (Equip now drawn, no end yet), the way a visitor can open the expanders before the path has ended. */
  async function pathRunning() {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    return t;
  }

  it("works the expander that was opened first out first, though both were opened while the path ran and the sets come first on the page: Every slot, then Best sets", async () => {
    const t = await pathRunning();
    await toggle("upgrade-slots");
    await toggle("upgrade-sets");
    expect(await quiet(t), "both wait for the path").toBe(1);
    t.engine.runs[0].finish(ended("no-gain", 0));
    await given(t, 2);
    expect(t.engine.runs[1].request.mode, "Every slot was opened first").toBe("every-slot");
    expect(await quiet(t), "and the sets wait for it").toBe(2);
    finishSlots(t.engine.runs[1]);
    await given(t, 3);
    expect(t.engine.runs[2].request).toMatchObject({ mode: "best-sets", k: 2 });
    finishSet(t.engine.runs[2], TWO);
    await given(t, 4);
    expect(t.engine.runs[3].request).toMatchObject({ mode: "best-sets", k: 3 });
  });

  it("and Best sets first, its two sets before Every slot, when it was opened first", async () => {
    const t = await pathRunning();
    await toggle("upgrade-sets");
    await toggle("upgrade-slots");
    t.engine.runs[0].finish(ended("no-gain", 0));
    await given(t, 2);
    expect(t.engine.runs[1].request).toMatchObject({ mode: "best-sets", k: 2 });
    finishSet(t.engine.runs[1], TWO);
    await given(t, 3);
    expect(t.engine.runs[2].request).toMatchObject({ mode: "best-sets", k: 3 });
    finishSet(t.engine.runs[2], THREE);
    await given(t, 4);
    expect(t.engine.runs[3].request.mode).toBe("every-slot");
  });

  it("keeps the order in which they were opened when the answer is worked out again after a change", async () => {
    const t = await pathRunning();
    await toggle("upgrade-slots");
    await toggle("upgrade-sets");
    addByName("corbel cap", "4"); // a change while the path runs: it is stopped, and the path is sent again
    await vi.waitFor(() => expect(t.engine.runs.filter((run) => run.request.mode === "farm-path")).toHaveLength(2), { timeout: 5000, interval: 5 });
    const path = t.engine.runs.at(-1);
    path.onStep(equipStep({ kit: kitOf({ 1: "w80305@4", 11: "w80301@4" }) }));
    path.finish(ended("no-gain", 0));
    await given(t, 3);
    expect(t.engine.runs[2].request, "Every slot was opened first, and still is").toMatchObject({ mode: "every-slot" });
  });

  it("counts an expander that was closed and opened again as the last one opened", async () => {
    const t = await pathRunning();
    await toggle("upgrade-sets");
    await toggle("upgrade-slots");
    await toggle("upgrade-sets"); // closed
    await toggle("upgrade-sets"); // and opened again, after Every slot
    t.engine.runs[0].finish(ended("no-gain", 0));
    await given(t, 2);
    expect(t.engine.runs[1].request.mode).toBe("every-slot");
  });

  // An expander counts as open from the moment its `open` changes, and the page is told by a toggle event a moment later. A slow page can be told of the first of two expanders that
  // were opened one after the other when the second one is open already, and what the page knows then of the second is the number of an earlier opening, or none. The order of the
  // openings is what decides who goes first, so it is the order in which the expanders were opened, whenever the page is told.

  /** Open expanders in one task, as a visitor can when the page is slow to be told: the toggle events come afterwards, one after the other. */
  async function openTogether(...ids) {
    const told = ids.map((id) => new Promise((resolve) => $(`#${id}`).addEventListener("toggle", resolve, { once: true })));
    for (const id of ids) $(`#${id}`).open = true;
    await Promise.all(told);
    await flush();
  }
  /** Close expanders in one task, and wait until the page has been told. */
  async function closeTogether(...ids) {
    const told = ids.map((id) => new Promise((resolve) => $(`#${id}`).addEventListener("toggle", resolve, { once: true })));
    for (const id of ids) $(`#${id}`).open = false;
    await Promise.all(told);
    await flush();
  }

  it("works the expander that was opened first out first when the second was opened before the page was told of the first, whichever it is: Every slot, then Best sets", async () => {
    const t = await answered();
    await openTogether("upgrade-slots", "upgrade-sets");
    await given(t, 2);
    expect(t.engine.runs[1].request.mode, "Every slot was opened first, though the sets come first on the page").toBe("every-slot");
    expect(await quiet(t), "and the sets wait for it").toBe(2);
    finishSlots(t.engine.runs[1]);
    await given(t, 3);
    expect(t.engine.runs[2].request).toMatchObject({ mode: "best-sets", k: 2 });
  });

  it("and Best sets, its two sets, before Every slot when the sets were opened first", async () => {
    const t = await answered();
    await openTogether("upgrade-sets", "upgrade-slots");
    await given(t, 2);
    expect(t.engine.runs[1].request).toMatchObject({ mode: "best-sets", k: 2 });
    finishSet(t.engine.runs[1], TWO);
    await given(t, 3);
    expect(t.engine.runs[2].request).toMatchObject({ mode: "best-sets", k: 3 });
    finishSet(t.engine.runs[2], THREE);
    await given(t, 4);
    expect(t.engine.runs[3].request.mode).toBe("every-slot");
  });

  it("forgets the number of an opening when the expander is closed: one that is opened again and not yet told of is the last one opened, not the first it once was", async () => {
    const t = await pathRunning();
    await toggle("upgrade-sets"); // opened first: it waits, the path runs
    await toggle("upgrade-slots"); // opened second
    await closeTogether("upgrade-sets");
    // the sets are opened again in the very task in which the path ends: the page is told of the opening after the pump has looked at the expanders
    const told = new Promise((resolve) => $("#upgrade-sets").addEventListener("toggle", resolve, { once: true }));
    $("#upgrade-sets").open = true;
    t.engine.runs[0].finish(ended("no-gain", 0));
    await told;
    await flush();
    await given(t, 2);
    expect(t.engine.runs[1].request.mode, "Every slot was opened before the sets were opened again").toBe("every-slot");
    expect(await quiet(t), "and the sets wait for it").toBe(2);
  });

  it("give the client only the last of several changes that come while the new path is ending: the first change ends the set, the paths of the others never begin", async () => {
    const t = await withSets();
    const stops = () => t.engine.log.filter((entry) => entry === "stop").length;
    addByName("corbel cap", "4"); // ends the set (it is taken back), and the path for it is given at once
    await given(t, 3);
    t.engine.autoStop = false; // a long step: that path does not end the moment it is told to
    addByName("fenwick greaves", "4");
    await vi.waitFor(() => expect(stops()).toBe(3), { timeout: 5000, interval: 5 });
    addByName("dunmere helm", "4");
    await vi.waitFor(() => expect(stops()).toBe(4), { timeout: 5000, interval: 5 });
    expect(await quiet(t), "nothing is given while that path ends").toBe(3);
    t.engine.runs[2].finish(ended("stopped", 0)); // the long step ends
    await given(t, 4);
    expect(await quiet(t)).toBe(4);
    expect(t.engine.runs[3].request.mode).toBe("farm-path");
    expect(t.engine.runs[3].request.owned.map(([ident]) => ident)).toEqual(["w80305@4", "w80304@4", "w80308@4", "w80301@4"]);
    expect(t.engine.log.filter((entry) => entry === "withdraw"), "the set was ended once, by the first change").toHaveLength(1);
  });
});

// ---- faults ---------------------------------------------------------------------------------------------------------------------------------------

describe("a fault in an expander", () => {
  /** The section with a path of three steps shown and ended. */
  async function withPath() {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    const path = t.engine.runs[0];
    path.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    path.onStep(pathStep(1, { ident: "w80308@4", gain: 50, kit: kitOf({ 11: "w80301@4", 14: "w80308@4" }) }));
    path.onStep(pathStep(2, { ident: "w80304@4", gain: 40, kit: kitOf({ 0: "w80304@4", 11: "w80301@4", 14: "w80308@4" }) }));
    path.finish(ended("no-gain", 2));
    await flush();
    return t;
  }
  const answerOfPath = () => ({
    equip: textOf("#upgrade-equip"),
    next: textOf("#upgrade-next"),
    then: textOf("#upgrade-then"),
    end: textOf("#upgrade-end"),
    fault: $("#upgrade-fault").hidden,
    stop: $("#upgrade-stop") === null,
  });

  it("says so inside the expander, with Try again, and keeps the answer of the path as it was", async () => {
    const t = await withPath();
    const before = answerOfPath();
    await toggle("upgrade-sets");
    await given(t, 2);
    t.engine.runs[1].fail(failure("worker-failed", "The optimizer stopped working."));
    await flush();
    expect(faultOf("upgrade-sets")).toBe("Couldn't work out your answer. The optimizer stopped working.");
    expect(faultButtons("upgrade-sets")).toEqual(["Try again"]);
    expect(stateOf("upgrade-sets")).toBe("");
    expect(answerOfPath(), "the path's answer is untouched").toEqual(before);
    expect($("#upgrade-fault").hidden, "and so is its own line").toBe(true);
    expect(await quiet(t), "it does not ask again by itself").toBe(2);
  });

  it("asks again with Try again: the request that failed, and nothing more than it", async () => {
    const t = await withPath();
    await toggle("upgrade-slots");
    await given(t, 2);
    t.engine.runs[1].fail(failure("worker-failed", "The optimizer stopped working."));
    await flush();
    $("#upgrade-slots-fault button").click();
    await given(t, 3);
    expect(t.engine.runs[2].request).toEqual(t.engine.runs[1].request);
    expect($("#upgrade-slots-fault").hidden).toBe(true);
    finishSlots(t.engine.runs[2]);
    await flush();
    expect(slotsDrawn()).toHaveLength(22);
    expect(t.engine.runs).toHaveLength(3);
  });

  it("keeps the set that was drawn when the next one fails, and Try again asks for the next one alone", async () => {
    const t = await withPath();
    await toggle("upgrade-sets");
    await given(t, 2);
    finishSet(t.engine.runs[1], TWO);
    await given(t, 3);
    t.engine.runs[2].fail(failure("worker-failed", "The optimizer stopped working."));
    await flush();
    expect(setsDrawn().map((set) => set.k)).toEqual([2]);
    expect(faultOf("upgrade-sets")).toBe("Couldn't work out your answer. The optimizer stopped working.");
    $("#upgrade-sets-fault button").click();
    await given(t, 4);
    expect(t.engine.runs[3].request).toMatchObject({ mode: "best-sets", k: 3 });
    finishSet(t.engine.runs[3], THREE);
    await flush();
    expect(setsDrawn().map((set) => set.k)).toEqual([2, 3]);
  });

  it("sends the focus to the summary when the button that had it goes", async () => {
    const t = await withPath();
    await toggle("upgrade-sets");
    await given(t, 2);
    t.engine.runs[1].fail(failure("worker-failed", "The optimizer stopped working."));
    await flush();
    $("#upgrade-sets-fault button").focus();
    $("#upgrade-sets-fault button").click();
    expect(document.activeElement).toBe($("#upgrade-sets > summary"));
  });

  it("says that the data was updated, with Reload, and tells the page, when the site was released again", async () => {
    const t = await withPath();
    await toggle("upgrade-sets");
    await given(t, 2);
    t.engine.updated = true;
    t.engine.runs[1].fail(failure("engine-load", UPDATED_TEXT));
    await flush();
    expect(faultOf("upgrade-sets")).toBe("Data updated, reload the page to see this section.");
    expect(faultButtons("upgrade-sets")).toEqual(["Reload"]);
    expect(t.onUpdated).toHaveBeenCalledTimes(1);
    $("#upgrade-sets-fault button").click();
    expect(t.reload).toHaveBeenCalledTimes(1);
  });

  it("does not make the path's request look failed: the same gear again, after a fault in an expander, is not sent twice", async () => {
    vi.useFakeTimers();
    const t = mountAnswer();
    addByName("tarn signet", "4");
    await vi.advanceTimersByTimeAsync(600);
    await flush();
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.engine.runs[0].finish(ended("no-gain", 0));
    await flush();
    await toggleFake("upgrade-sets");
    t.engine.runs[1].fail(failure("worker-failed", "The optimizer stopped working."));
    await flush();
    addByName("corbel cap", "4");
    await vi.advanceTimersByTimeAsync(100);
    $$("#upgrade-owned li").find((li) => li.dataset.ident === "w80305@4").querySelector("button").click();
    await vi.advanceTimersByTimeAsync(2000);
    await flush();
    expect(t.engine.runs.filter((run) => run.request.mode === "farm-path")).toHaveLength(1);
  });
});

// ---- voice and focus ------------------------------------------------------------------------------------------------------------------------------

describe("what a visitor who cannot see the page is told", () => {
  it("is one announcement for each expander when its answer is drawn: not for each set, and not before the last", async () => {
    const t = await withSets();
    const before = t.spoken.length;
    finishSet(t.engine.runs[1], TWO);
    await given(t, 3);
    expect(t.spoken.slice(before), "the set of 2 alone says nothing").toEqual([]);
    finishSet(t.engine.runs[2], THREE);
    await flush();
    expect(t.spoken.slice(before)).toEqual(["Best 2 and 3 sets are ready."]);
    await toggle("upgrade-slots");
    await given(t, 4);
    expect(t.spoken.slice(before)).toEqual(["Best 2 and 3 sets are ready."]);
    finishSlots(t.engine.runs[3]);
    await flush();
    expect(t.spoken.slice(before)).toEqual(["Best 2 and 3 sets are ready.", "Every slot is ready."]);
  });

  it("is the fault, once, when an expander cannot be worked out", async () => {
    const t = await withSlots();
    const before = t.spoken.length;
    t.engine.runs[1].fail(failure("worker-failed", "The optimizer stopped working."));
    await flush();
    expect(t.spoken.slice(before)).toEqual(["Every slot: Couldn't work out your answer. The optimizer stopped working."]);
  });

  it("says nothing of its own for a change of the tier mode: what is said is the answer that follows", async () => {
    const t = await answered();
    const before = t.spoken.length;
    $("#upgrade-mode-fixed").click();
    await given(t, 2);
    expect(t.spoken.slice(before)).toEqual([]);
  });

  it("has no live region of its own, with the three expanders open and drawn", async () => {
    const t = await answered();
    await toggle("upgrade-mode");
    await toggle("upgrade-sets");
    await toggle("upgrade-slots");
    await given(t, 2);
    finishSet(t.engine.runs[1], TWO);
    await given(t, 3);
    finishSet(t.engine.runs[2], THREE);
    await given(t, 4);
    finishSlots(t.engine.runs[3]);
    await flush();
    expect(setsDrawn()).toHaveLength(2);
    expect(slotsDrawn()).toHaveLength(22);
    expect($$('#upgrade [role="status"], #upgrade [role="alert"], #upgrade [role="log"], #upgrade [aria-live]')).toHaveLength(0);
  });

  it("keeps the focus on the summary that was opened while its answer is drawn, and does not take it from a visitor who has gone elsewhere", async () => {
    const t = await answered();
    const summary = $("#upgrade-sets > summary");
    summary.focus();
    await toggle("upgrade-sets");
    await given(t, 2);
    expect(document.activeElement).toBe(summary);
    finishSet(t.engine.runs[1], TWO);
    await given(t, 3);
    finishSet(t.engine.runs[2], THREE);
    await flush();
    expect(document.activeElement, "the answer was drawn, and the focus did not move").toBe(summary);
    $("#upgrade-pick").focus();
    await toggle("upgrade-slots");
    await given(t, 4);
    finishSlots(t.engine.runs[3]);
    await flush();
    expect(document.activeElement.id).toBe("upgrade-pick");
  });
});

// ---- what is put in the page ----------------------------------------------------------------------------------------------------------------------

describe("what the expanders put in the page", () => {
  it("is all text: a name that looks like markup is shown as it is, in a set and in a swap", async () => {
    const hostile = { id: 80401, name: "<img src=x onerror=alert(1)>", slots: ["FINGER"], stats: { STR: 5 }, weight10: 10, tier_rule: "drop", evidence: { level: "strict" }, source: { drops: ["<b>Zone</b>"] } };
    const { tableOf } = await import("./upgrade-helpers.mjs");
    const t = await answered({ items: tableOf([hostile]), gear: [["img", "4"]], kit: kitOf({ 11: "w80401@4" }) });
    await toggle("upgrade-sets");
    await toggle("upgrade-slots");
    await given(t, 2);
    finishSet(t.engine.runs[1], { acquired: [addition("w80401@4", "copy", costOf(4, 4))], kit: kitOf({ 11: "w80401@4", 12: "w80401@4" }), gain: 20 });
    await given(t, 3);
    lostSet(t.engine.runs[2]);
    await given(t, 4);
    finishSlots(t.engine.runs[3], { 12: [{ ident: "w80401@4", delta: 5 }] });
    await flush();
    expect(setsDrawn()[0].additions[0]).toMatchObject({ what: "Get another <img src=x onerror=alert(1)> +4", source: "Source: <b>Zone</b>" });
    expect(slotsDrawn()[12].swaps[0].what).toBe("<img src=x onerror=alert(1)> +4");
    expect($$("#upgrade-more img, #upgrade-more b, #upgrade-more script")).toHaveLength(0);
  });

  it("is made of a table with row headers for the places, lists for the additions and the swaps, and a fieldset with a legend for the tier mode", async () => {
    const t = await answered();
    await toggle("upgrade-sets");
    await toggle("upgrade-slots");
    await given(t, 2);
    finishSet(t.engine.runs[1], TWO);
    await given(t, 3);
    finishSet(t.engine.runs[2], THREE);
    await given(t, 4);
    finishSlots(t.engine.runs[3], { 1: [{ ident: "w80305@4", delta: 12 }] });
    await flush();
    expect($("#upgrade-slots-table caption").textContent).toBe("The best swaps for each slot, with the change in kit value");
    expect($$("#upgrade-sets h4").map((h) => h.textContent)).toEqual(["Best set of 2", "Best set of 3"]);
    expect($("#upgrade-mode fieldset legend")).not.toBeNull();
    expect($$("#upgrade-sets ul.steps")).toHaveLength(2);
  });
});
