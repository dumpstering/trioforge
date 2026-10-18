// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// What the Upgrade section ends, and how. The client is shared with the sliders of the page, so the section ends only its own requests, each one by taking it back (the signal of the
// request) and never with cancel(), which ends what every part of the page asked for. A request of the section that has not reached the worker (the visitor's question is open, or another
// part of the page has the worker) is taken back: nothing of it was begun and nothing is lost, and a yes loads nothing for it; a path that the worker has is stopped, which keeps the worker; the
// request of an expander that is on the client is taken back, which stops its worker. And a request of the section that comes back cancelled when the section did not cancel it (a cancel of
// another part of the page) is asked for again, once. The client is a stand-in that the test drives.

import { afterEach, describe, expect, it, vi } from "vitest";
import { $ } from "./upgrade-helpers.mjs";
import { addByName, costOf, ended, equipStep, fakeEngine, flush, kitOf, mountAnswer, textOf } from "./upgrade-answer-helpers.mjs";
import { addition, answered, faultButtons, faultOf, finishSet, given, quiet, setsDrawn, stateOf, toggle } from "./upgrade-more-helpers.mjs";

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

const cancelled = () => Object.assign(new Error("The request was cancelled."), { code: "cancelled" });
const foreign = (engine, mode = "best-kit") => {
  const outcome = { settled: false };
  engine.client.runScenario({ mode }, {}).then(
    () => (outcome.settled = true),
    () => (outcome.settled = true),
  );
  return outcome;
};
const faultText = () => textOf("#upgrade-fault .status-text");

describe("a request of the section that has not reached the worker", () => {
  it("is taken back, not stopped, when another part of the page has the worker and a change comes: nothing of it was begun, and the part that has the worker is not touched", async () => {
    const engine = fakeEngine();
    engine.serial = true;
    const other = foreign(engine); // the sliders' request: the worker has it
    const t = mountAnswer({ engine, pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 2); // the section's path waits behind it
    expect(t.engine.runs[1].sent).toBe(false);
    t.setView({ role: "tank" });
    await given(t, 3);
    expect(t.engine.log.slice(2), "the path that waited is taken back, and no worker is told to stop for it").toEqual(["run2", "withdraw", "run3"]);
    expect(t.engine.log.filter((entry) => entry === "stop"), "(the stop before the first path is the one there is nothing to stop for)").toHaveLength(1);
    expect(t.engine.runs[1].withdrawn).toBe(true);
    expect(other.settled, "the request of the other part of the page goes on").toBe(false);
    expect(t.engine.runs[0].settled).toBe(false);
    expect(faultText(), "a request that was taken back is no fault").toBe("");
  });

  it("is taken back while the visitor's question is up, and the question is not touched: the other parts of the page that wait for it go on", async () => {
    const engine = fakeEngine();
    engine.consent = "unknown";
    const other = foreign(engine);
    const t = mountAnswer({ engine, pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 2);
    t.setView({ role: "tank" });
    await given(t, 3);
    expect(t.engine.log).toEqual(["run1", "run2", "withdraw", "run3"]);
    expect(other.settled, "a request of another part of the page that waits for the same question is not cancelled with it").toBe(false);
    expect(t.engine.runs[0].settled).toBe(false);
  });
});

/** Two sets that the optimizer finds for the gear of `answered()`. */
const TWO = {
  acquired: [addition("w80308@4", "new", costOf(4, 4)), addition("w80304@4", "new", costOf(4, 4))],
  kit: kitOf({ 0: "w80304@4", 11: "w80301@4", 14: "w80308@4" }),
  gain: 500,
};

describe("the request of an expander that another part of the page cancelled (G2)", () => {
  it("is asked for again at once: the expander does not hang, it says that it works, the answer is drawn, and the next set goes on", async () => {
    const t = await answered();
    await toggle("upgrade-sets");
    await given(t, 2); // the set of 2: the worker has it
    expect(stateOf("upgrade-sets")).toBe("Working out the best 2 additions…");
    t.engine.runs[1].fail(cancelled()); // another part of the page cancelled it
    await given(t, 3);
    expect(t.engine.runs[2].request, "the same request, asked for again").toEqual(t.engine.runs[1].request);
    expect(faultOf("upgrade-sets"), "the visitor is told of no fault").toBe("");
    expect(stateOf("upgrade-sets"), "it says that it works").toBe("Working out the best 2 additions…");
    finishSet(t.engine.runs[2], TWO);
    await given(t, 4); // the loop of the expanders did not stop: the set of 3 is asked for
    expect(t.engine.runs[3].request).toMatchObject({ mode: "best-sets", k: 3 });
    expect(setsDrawn().map((set) => set.k)).toEqual([2]);
  });

  it("is asked for again when it waited behind a request of another part of the page and a cancel() ended both", async () => {
    const engine = fakeEngine();
    engine.serial = true;
    const t = await answered({ engine });
    foreign(engine); // the worker has a request of another part of the page ...
    await toggle("upgrade-sets");
    await given(t, 3); // ... and the set of 2 waits behind it
    expect(t.engine.runs[2].sent).toBe(false);
    engine.client.cancel(); // a cancel() of the page ends both
    await given(t, 4);
    expect(t.engine.runs[3].request).toEqual(t.engine.runs[2].request);
    expect(t.engine.runs[3].sent, "the other request is gone: the worker has it").toBe(true);
    finishSet(t.engine.runs[3], TWO);
    await flush();
    expect(setsDrawn().map((set) => set.k)).toEqual([2]);
    expect(faultOf("upgrade-sets")).toBe("");
  });

  it("is a fault with Try again when it is cancelled a second time, and Try again asks once more and draws the answer", async () => {
    const t = await answered();
    await toggle("upgrade-sets");
    await given(t, 2);
    t.engine.runs[1].fail(cancelled());
    await given(t, 3);
    t.engine.runs[2].fail(cancelled());
    await flush();
    expect(faultOf("upgrade-sets")).toBe("Couldn't work out your answer. The request was cancelled.");
    expect(faultButtons("upgrade-sets")).toEqual(["Try again"]);
    expect(stateOf("upgrade-sets"), "nothing is said to be working").toBe("");
    expect(await quiet(t, 80), "and nothing is asked for in the meantime").toBe(3);
    $("#upgrade-sets-fault button").click();
    await given(t, 4);
    expect(t.engine.runs[3].request).toEqual(t.engine.runs[1].request);
    finishSet(t.engine.runs[3], TWO);
    await given(t, 5);
    expect(setsDrawn().map((set) => set.k)).toEqual([2]);
    expect(faultOf("upgrade-sets")).toBe("");
  });
});

describe("a request that the visitor's yes has sent", () => {
  it("is stopped, not taken back, when a change comes after the yes: the worker has it now", async () => {
    const engine = fakeEngine();
    engine.consent = "unknown";
    const t = mountAnswer({ engine, pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    expect(t.engine.runs[0].sent).toBe(false);
    engine.agree(); // the visitor said yes: the worker has the request
    expect(t.engine.runs[0].sent).toBe(true);
    addByName("corbel cap", "4");
    await given(t, 2);
    expect(t.engine.log.slice(-2), "told to stop (it ends a moment later), as a path the worker has always was").toEqual(["stop", "run2"]);
    expect(t.engine.runs[0].withdrawn).toBe(false);
  });
});

describe("the request of an expander that the worker has", () => {
  it("is taken back alone when a change comes: a request of another part of the page that waits behind it is not cancelled, and is sent next", async () => {
    const engine = fakeEngine();
    engine.serial = true;
    const t = await answered({ engine });
    await toggle("upgrade-sets");
    await given(t, 2); // the set of 2: the worker has it
    expect(t.engine.runs[1].sent).toBe(true);
    const other = foreign(engine); // the sliders' request (Full raid, say): it waits behind the set
    expect(t.engine.runs[2].sent).toBe(false);
    addByName("corbel cap", "4"); // a change of the gear: the set is old
    await given(t, 4); // the new path
    expect(t.engine.log, "the set is taken back, and the client is never told to cancel what every part of the page asked for").not.toContain("cancel");
    expect(t.engine.runs[1].withdrawn).toBe(true);
    expect(t.engine.runs[2].settled, "the request of the other part goes on").toBe(false);
    expect(t.engine.runs[2].sent, "and the worker is its now").toBe(true);
    expect(other.settled).toBe(false);
    expect(t.engine.runs[3].sent, "the new path waits behind it").toBe(false);
  });
});

describe("a request of the section that the worker has", () => {
  it("is stopped, as before, and the worker is kept: a path is ended before its next step, never withdrawn", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    addByName("corbel cap", "4");
    await given(t, 2);
    expect(t.engine.log).toEqual(["stop", "run1", "stop", "run2"]);
    expect(t.engine.runs[0].withdrawn).toBe(false);
  });

  it("never calls cancel(): the client is the page's, and cancel() ends what every part of it asked for", async () => {
    const engine = fakeEngine();
    const t = mountAnswer({ engine, pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.engine.runs[0].finish(ended("no-gain", 0));
    await flush();
    await toggle("upgrade-sets");
    await given(t, 2);
    addByName("corbel cap", "4"); // a change while the request of an expander is on the client
    await given(t, 3);
    $("#upgrade-clear").click();
    await quiet(t);
    engine.consent = "unknown";
    addByName("fenwick greaves", "4");
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(engine.log).not.toContain("cancel");
    expect(engine.log).toContain("withdraw");
  });
});

describe("a request that comes back cancelled when the section did not cancel it", () => {
  it("is a path that is asked for again, once, when the optimizer was agreed to: another part of the page cancelled it", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    t.engine.runs[0].fail(cancelled());
    await given(t, 2);
    expect(t.engine.runs[1].request).toEqual(t.engine.runs[0].request);
    expect(faultText(), "the visitor is told of nothing: the answer is asked for again").toBe("");
    t.engine.runs[1].fail(cancelled()); // and cancelled again: the section does not go on for ever
    await flush();
    expect(await quiet(t, 80)).toBe(2);
    expect(faultText()).toBe("Couldn't work out your answer. The request was cancelled.");
  });

  it("is not asked for again when the visitor had not agreed to the optimizer: that is the question's answer, and the line says so", async () => {
    const engine = fakeEngine();
    engine.consent = "declined";
    const t = mountAnswer({ engine, pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    t.engine.runs[0].fail(cancelled());
    await flush();
    expect(await quiet(t, 80)).toBe(1);
    expect(faultText()).toBe("The optimizer was not loaded, so there is no answer for your gear yet.");
  });

  it("is a request of an expander that is asked for again, once", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("tarn signet", "4");
    await given(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.engine.runs[0].finish(ended("no-gain", 0));
    await flush();
    await toggle("upgrade-sets");
    await given(t, 2);
    t.engine.runs[1].fail(cancelled());
    await given(t, 3);
    expect(t.engine.runs[2].request).toEqual(t.engine.runs[1].request);
    expect(faultOf("upgrade-sets")).toBe("");
    t.engine.runs[2].fail(cancelled());
    await flush();
    expect(await quiet(t, 80)).toBe(3);
    expect(faultOf("upgrade-sets")).toBe("Couldn't work out your answer. The request was cancelled.");
  });
});
