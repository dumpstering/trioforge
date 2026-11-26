// @vitest-environment jsdom
//
// The part of the priorities control that the page script holds (static/priorities.js): the eight stats and the five steps in their fixed order, the address parameter `p` (one character
// for each stat: 0 l n h t for Off, Low, Normal, High, Top), the words for a choice, and the control itself, drawn by script into the section of the choices. What the chunk of the weights
// makes of a choice (the custom weights of a request) is tested in priority-weights.test.mjs, against the one definition of how weights compose.

import { describe, expect, it, vi } from "vitest";
import { OWN_PRIORITIES, STATS, STEPS, drawPriorities, parsePriorities, sayPriorities } from "../pipeline/trioforge/site/static/priorities.js";

describe("the stats and the steps", () => {
  it("are the eight stats of the brief, in a fixed order, and five steps from Off to Top", () => {
    expect(STATS.map(([id]) => id)).toEqual(["hp", "ac", "mana", "atk", "dex", "haste", "resists", "end"]);
    expect(STATS.map(([, label]) => label)).toEqual(["Hit points", "Armor class", "Mana", "Attack (strength)", "Dexterity", "Haste", "Resists", "Endurance"]);
    expect(STEPS.map(([character]) => character).join("")).toBe("0lnht");
    expect(STEPS.map(([, label]) => label)).toEqual(["Off", "Low", "Normal", "High", "Top"]);
    expect(STEPS.map(([, , times]) => times)).toEqual(["x0", "x0.5", "x1", "x2", "x4"]);
    expect(OWN_PRIORITIES).toBe("nnnnnnnn");
  });
});

describe("the address parameter p", () => {
  it("takes eight characters of 0 l n h t, and returns them as they are", () => {
    for (const text of ["nnnnnnnn", "0lnht0ln", "tttttttt", "00000000", "nhnnnnnn"]) expect(parsePriorities(text)).toBe(text);
  });

  it("ignores a malformed value whole: too short, too long, another character, a capital, a space, an empty one, a number, nothing", () => {
    for (const text of ["", "n", "nnnnnnn", "nnnnnnnnn", "nnnnnnnx", "NNNNNNNN", "nnnn nnn", "n n n n ", "12345678", "nnnnnnn\n", null, undefined, 12345678, ["nnnnnnnn"]]) {
      expect(parsePriorities(text), String(text)).toBeNull();
    }
  });

  it("round-trips: what the control reads is what the address says and what the address says is what the control shows", () => {
    const draw = drawPriorities(document, document.body.appendChild(document.createElement("section")), { onChange: () => {}, onReset: () => {}, onRates: () => {} });
    for (const text of ["0lnht0ln", "tnnnnnnn", "nnnnnnnh"]) {
      draw.sync(text);
      expect(draw.read()).toBe(text);
      expect(parsePriorities(draw.read())).toBe(text);
    }
  });
});

describe("the words for a choice", () => {
  it("say every stat that is not Normal, in the order of the control, and 'all Normal' for none", () => {
    expect(sayPriorities(OWN_PRIORITIES)).toBe("all Normal");
    expect(sayPriorities("nhnnnnnn")).toBe("armor class High");
    expect(sayPriorities("0nntnnnl")).toBe("hit points Off, attack (strength) Top, endurance Low");
  });
});

describe("the control", () => {
  function draw(extra = {}) {
    document.body.innerHTML = '<section class="controls"><div class="control"><label for="x">X</label><select id="x"></select></div></section>';
    const controls = document.querySelector(".controls");
    const calls = { change: vi.fn(), reset: vi.fn(), rates: vi.fn(), warm: vi.fn() };
    const handle = drawPriorities(document, controls, { onChange: calls.change, onReset: calls.reset, onRates: calls.rates, onWarm: calls.warm, ...extra });
    return { controls, calls, handle };
  }

  it("is a fieldset with a legend and, for each stat, a visible label and a select of the five steps with Normal chosen, after the choices it is next to", () => {
    const { controls } = draw();
    const box = controls.querySelector("fieldset#prio");
    expect(box).not.toBeNull();
    expect(box.querySelector("legend").textContent).toBe("Your priorities: how much each stat counts for you");
    expect(controls.lastElementChild).toBe(box);
    const selects = [...box.querySelectorAll("select")];
    expect(selects.map((select) => select.id)).toEqual(STATS.map(([id]) => `prio-${id}`));
    for (const [index, select] of selects.entries()) {
      const label = box.querySelector(`label[for="${select.id}"]`);
      expect(label.textContent, "a visible label").toBe(STATS[index][1]);
      expect([...select.options].map((option) => option.textContent)).toEqual(["Off (x0)", "Low (x0.5)", "Normal (x1)", "High (x2)", "Top (x4)"]);
      expect([...select.options].map((option) => option.value).join("")).toBe("0lnht");
      expect(select.value).toBe("n");
      expect(select.disabled).toBe(false);
    }
    expect(controls.hasAttribute("data-prio"), "the room kept for it is given up").toBe(true);
  });

  it("tells the page what the visitor chose, as the one string of the address: a change of one select is the whole choice", () => {
    const { controls, calls } = draw();
    const select = controls.querySelector("#prio-ac");
    select.value = "t";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    expect(calls.change).toHaveBeenCalledTimes(1);
    expect(calls.change).toHaveBeenCalledWith("ntnnnnnn");
    controls.querySelector("#prio-end").value = "0";
    controls.querySelector("#prio-end").dispatchEvent(new Event("change", { bubbles: true }));
    expect(calls.change).toHaveBeenLastCalledWith("ntnnnnn0");
  });

  it("has a Reset that is switched off while every step is Normal, and tells the page when it is pressed", () => {
    const { controls, calls, handle } = draw();
    const reset = controls.querySelector("#prio-reset");
    expect(reset.textContent).toBe("Reset priorities");
    expect(reset.disabled).toBe(true);
    handle.sync("nnhnnnnn");
    expect(reset.disabled).toBe(false);
    reset.click();
    expect(calls.reset).toHaveBeenCalledTimes(1);
    handle.sync(OWN_PRIORITIES);
    expect(reset.disabled).toBe(true);
  });

  it("puts the focus on the first step when it is asked to, which is where it goes when Reset, which is off then, had it", () => {
    const { controls, handle } = draw();
    handle.focus();
    expect(document.activeElement).toBe(controls.querySelector("#prio-hp"));
  });

  it("puts the focus on the first select that is not disabled, and on the button of the rates when none is: a build that does not weigh hit points does not lose the focus of a Reset", () => {
    const { controls, handle } = draw();
    handle.setCounted([false, true, true, true, true, true, true, true]);
    handle.focus();
    expect(document.activeElement, "hit points are disabled: the next select has the focus").toBe(controls.querySelector("#prio-ac"));
    handle.setCounted([false, false, false, false, true, true, true, true]);
    handle.focus();
    expect(document.activeElement.id).toBe("prio-dex");
    handle.setCounted([false, false, false, false, false, false, false, false]);
    handle.focus();
    expect(document.activeElement, "no select can take it: the button of the rates").toBe(controls.querySelector("#prio-rates-show"));
    handle.setCounted(null);
    handle.focus();
    expect(document.activeElement.id, "the build is not known: the first select, as it was").toBe("prio-hp");
  });

  it("moves no choice of the page itself: it is made without a network, and leaves the choices it sits beside alone", () => {
    const { controls, handle } = draw();
    expect(controls.querySelector("#x")).not.toBeNull();
    expect(controls.querySelectorAll("select")).toHaveLength(1 + STATS.length);
    handle.sync("0lnht0ln");
    expect(controls.querySelector("#x").value).toBe("");
  });

  it("shows a stat that the build does not weigh disabled, at Normal, with a visible note that says so and is the description of the select, and gives it back when the build weighs it", () => {
    const { controls, handle } = draw();
    handle.setCounted([true, true, false, true, true, false, true, true]);
    for (const id of ["mana", "haste"]) {
      const select = controls.querySelector(`#prio-${id}`);
      const note = controls.querySelector(`#prio-${id}-note`);
      expect(select.disabled, id).toBe(true);
      expect(select.value, id).toBe("n");
      expect(note.hidden, id).toBe(false);
      expect(note.textContent).toBe("not counted in this build");
      expect(select.getAttribute("aria-describedby")).toBe(note.id);
    }
    for (const id of ["hp", "ac", "atk", "dex", "resists", "end"]) {
      expect(controls.querySelector(`#prio-${id}`).disabled, id).toBe(false);
      expect(controls.querySelector(`#prio-${id}-note`).hidden, id).toBe(true);
      expect(controls.querySelector(`#prio-${id}`).hasAttribute("aria-describedby"), id).toBe(false);
    }
    handle.setCounted([true, true, true, true, true, true, true, true]);
    expect(controls.querySelector("#prio-mana").disabled).toBe(false);
    expect(controls.querySelector("#prio-mana-note").hidden).toBe(true);
    handle.setCounted([true, true, false, true, true, true, true, true]);
    handle.setCounted(null);
    expect(controls.querySelector("#prio-mana").disabled, "nothing is known of the build yet: nothing is disabled").toBe(false);
  });

  it("does not take a step for a stat that is shown disabled into what it reads: the select is Normal and stays so while a choice is synced", () => {
    const { controls, handle } = draw();
    handle.setCounted([true, true, true, true, true, false, true, true]);
    handle.sync("hnnnnnhn");
    expect(handle.read()).toBe("hnnnnnhn");
    handle.sync("nnnnntnn");
    expect(handle.read(), "the step of a stat that is not counted is Normal").toBe("nnnnnnnn");
    expect(controls.querySelector("#prio-haste").value).toBe("n");
  });

  it("asks the page to read the build when a step is about to be chosen: the first focus in the control, once", () => {
    const { controls, calls } = draw();
    controls.querySelector("#prio-ac").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    controls.querySelector("#prio-hp").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    expect(calls.warm).toHaveBeenCalledTimes(1);
  });

  it("has the button of the rates as a disclosure (collapsed, naming the line it opens), a line that takes no focus, and no live region of its own: the page says what the line says through its own", () => {
    const { controls } = draw();
    const button = controls.querySelector("#prio-rates-show");
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(button.getAttribute("aria-controls")).toBe("prio-rates-text");
    expect(controls.querySelector("#prio-rates-text").hasAttribute("tabindex"), "no focus is moved to the line").toBe(false);
    expect(controls.querySelector("[aria-live], [role=status], [role=alert]")).toBeNull();
  });

  it("offers the rates on request: a button, and a place for the line, which are the page's to fill", () => {
    const { controls, calls } = draw();
    const button = controls.querySelector("#prio-rates-show");
    expect(button.tagName).toBe("BUTTON");
    expect(button.type).toBe("button");
    expect(controls.querySelector("#prio-rates-text").hidden).toBe(true);
    button.click();
    expect(calls.rates).toHaveBeenCalledTimes(1);
  });
});
