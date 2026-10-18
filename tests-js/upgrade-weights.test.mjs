// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// The weights of the view in the requests of the Upgrade section. The page gives the section the view it shows, and the view has the weights the visitor set with the sliders
// (`weights`: the table of slider positions by group that a request carries, or nothing for the role's own): every request of the section, the path, a best sets request and an Every
// slot request, has them, and a change of the sliders is a change of the view that makes a new path. The client is a stand-in that the test drives.

import { afterEach, describe, expect, it, vi } from "vitest";
import { VIEW, addByName, ended, equipStep, flush, kitOf, mountAnswer } from "./upgrade-answer-helpers.mjs";
import { finishSet, finishSlots, given, quiet, toggle } from "./upgrade-more-helpers.mjs";

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

const AC2 = { multipliers: { AC: 2 } };
const SV_HALF_REGEN_DOUBLE = { multipliers: { SV: 0.5, regen: 2 } };

/** The section with the view's weights set and one item of gear, its path answered and ended, so that the expanders can be opened. */
async function ready(weights) {
  const t = mountAnswer({ pauseMs: 0 });
  if (weights !== undefined) t.setView({ weights });
  addByName("tarn signet", "4");
  await given(t, 1);
  const run = t.engine.runs[0];
  run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
  run.finish(ended("no-gain", 0));
  await flush();
  return { ...t, run };
}

describe("the path", () => {
  it("is asked for with the weights of the view, and with none when the view has none", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    expect(t.engine.runs[0].request).not.toHaveProperty("weights");
    expect(t.engine.runs[0].request.scenario).toEqual({ race: VIEW.race, role: VIEW.role, buffs: VIEW.buffs, evidence: VIEW.evidence, setup: VIEW.setup });
    t.setView({ weights: AC2 });
    await given(t, 2);
    expect(t.engine.runs[1].request.weights).toEqual(AC2);
    expect(t.engine.runs[1].request.mode).toBe("farm-path");
    t.setView({ weights: SV_HALF_REGEN_DOUBLE });
    await given(t, 3);
    expect(t.engine.runs[2].request.weights).toEqual(SV_HALF_REGEN_DOUBLE);
    t.setView({ weights: null });
    await given(t, 4);
    expect(t.engine.runs[3].request).not.toHaveProperty("weights"); // (the role's own again)
  });

  it("is not asked for again when the view comes back with the same weights, and is when only the weights differ", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    t.setView({ weights: AC2 });
    addByName("tarn signet", "4");
    await given(t, 1);
    t.setView({ weights: { multipliers: { AC: 2 } } }); // (a table of the same positions: no change)
    expect(await quiet(t, 80)).toBe(1);
    t.setView({ weights: { multipliers: { AC: 0.5 } } });
    await given(t, 2);
    expect(t.engine.runs[1].request.weights).toEqual({ multipliers: { AC: 0.5 } });
  });

  it("holds a copy of the weights: what the view gave is not the request's to change", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    const given_ = { multipliers: { AC: 2 } };
    t.setView({ weights: given_ });
    addByName("tarn signet", "4");
    await given(t, 1);
    expect(t.engine.runs[0].request.weights).toEqual(AC2);
    expect(t.engine.runs[0].request.weights).not.toBe(given_);
    expect(t.engine.runs[0].request.weights.multipliers).not.toBe(given_.multipliers);
  });
});

describe("the expanders", () => {
  it("ask for the best sets with the weights the path was asked for with", async () => {
    const t = await ready(AC2);
    await toggle("upgrade-sets");
    await given(t, 2);
    expect(t.engine.runs[1].request).toMatchObject({ mode: "best-sets", k: 2, weights: AC2 });
    finishSet(t.engine.runs[1], { kit: kitOf({ 11: "w80301@4" }) });
    await flush();
    await given(t, 3);
    expect(t.engine.runs[2].request).toMatchObject({ mode: "best-sets", k: 3, weights: AC2 });
  });

  it("ask for every slot with the weights the path was asked for with", async () => {
    const t = await ready(SV_HALF_REGEN_DOUBLE);
    await toggle("upgrade-slots");
    await given(t, 2);
    expect(t.engine.runs[1].request).toMatchObject({ mode: "every-slot", weights: SV_HALF_REGEN_DOUBLE });
    finishSlots(t.engine.runs[1], {});
    await flush();
  });

  it("ask with none when the view has none", async () => {
    const t = await ready();
    await toggle("upgrade-sets");
    await given(t, 2);
    expect(t.engine.runs[1].request).not.toHaveProperty("weights");
  });
});
