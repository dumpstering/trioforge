// @vitest-environment jsdom
//
// The folded line of the assumptions on the trio page (details#assumes, branch layout-polish): its summary says the choices in a few words, and says that one is not the default without being
// opened. The page code (static/trio.js) is run in jsdom against the baked page the generator writes and the data files of the fixture (fixtures/site/contract/), as trio.test.mjs does.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it } from "vitest";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract");
const text = (name) => readFileSync(resolve(CONTRACT, name), "utf8");
const dataFile = (name) => JSON.parse(text(`data/${name}.json`));
const $ = (selector) => document.querySelector(selector);

function mount() {
  document.body.innerHTML = text("trio-main.html");
  window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
  const fetch = async (url) => ({ ok: true, status: 200, json: async () => structuredClone(dataFile(String(url).replace("/data/pal-mnk-ber/", "").replace(".json", ""))) });
  return initTrio({ document, window, fetch });
}

const change = (element, value) => {
  if (value !== undefined) element.value = value;
  element.dispatchEvent(new Event("change", { bubbles: true }));
};

function choose(selector) {
  const radio = $(selector);
  radio.checked = true;
  radio.dispatchEvent(new Event("change", { bubbles: true }));
}

const line = () => $("#assumes > summary").textContent.replace(/\s+/g, " ").trim();
const lead = () => $('#assumes > summary [data-f="a-lead"]').textContent;

describe("the folded line of the assumptions", () => {
  let app;
  beforeEach(() => {
    app = mount();
  });

  it("is closed, says the weapons and the buffs of the page, and is not marked as changed", () => {
    expect($("#assumes").open).toBe(false);
    expect(line()).toBe(`Assumptions: ${$('#view-summary [data-f="s-assumes"]').textContent}`);
    expect(line()).toContain("dual wield");
    expect(line()).toContain("your own buffs");
    expect(lead()).toBe("Assumptions");
    expect($("#assumes").hasAttribute("data-changed")).toBe(false);
  });

  it("follows the buffs, and says so in its first word when they are not the page's", async () => {
    choose("#buffs-group");
    await app.whenIdle();
    expect(line()).toContain("common group buffs");
    expect(lead()).toBe("Assumptions changed");
    expect($("#assumes").hasAttribute("data-changed")).toBe(true);
    choose("#buffs-own");
    await app.whenIdle();
    expect(line()).toContain("your own buffs");
    expect(lead()).toBe("Assumptions");
    expect($("#assumes").hasAttribute("data-changed")).toBe(false);
  });

  it("says a weapon setup that is not the role's best as changed, and the best again as not", async () => {
    choose("#setup-2h");
    await app.whenIdle();
    expect(line()).toContain("two-hander");
    expect(lead()).toBe("Assumptions changed");
    choose("#setup-dw"); // the best setup of the balanced role in the fixture
    await app.whenIdle();
    expect(line()).toContain("dual wield");
    expect(lead()).toBe("Assumptions");
  });

  it("is not changed by the race or the tier, which are no assumption", async () => {
    change($("#sw-tier"), "10");
    await app.whenIdle();
    change($("#sw-race"), "TRL");
    await app.whenIdle();
    expect(lead()).toBe("Assumptions");
    expect($("#assumes").hasAttribute("data-changed")).toBe(false);
  });

  it("is made again for the line of a phone as well: both say the same words", async () => {
    choose("#buffs-raid");
    await app.whenIdle();
    const phone = $('#view-summary [data-f="s-assumes"]').textContent;
    expect(phone).toContain("full raid buffs");
    expect(line()).toBe(`${lead()}: ${phone}`);
  });
});
