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
    choose("#setup-dw"); // the best setup of the tank role in the fixture
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

describe("the Berserker stance in the assumptions (T8)", () => {
  let app;
  beforeEach(() => {
    app = mount();
  });

  it("says nothing of it on a build that plays none, and the words of the stance on the build that does", async () => {
    expect($("#stance-note").hidden).toBe(true);
    expect($('[data-f="assume-stance"]').textContent).toBe("");
    expect(line()).not.toContain("Berserker");
    choose("#role-melee");
    await app.whenIdle();
    expect($("#stance-note").hidden).toBe(false);
    expect($("#stance-note").textContent).toContain("The Berserker stance is on: the weapons swing 2.1 times as fast, applied after the haste cap and on top of whatever haste counts");
    expect($("#stance-note").textContent).not.toContain("full value");
    expect($('[data-f="assume-stance"]').textContent).toBe(", Berserker stance");
    expect($("#assume-weapons > summary").textContent.replace(/\s+/g, " ")).toContain("Berserker stance, scored at");
    expect(line()).toContain(", Berserker stance, ");
    expect($('#view-summary [data-f="s-assumes"]').textContent).toBe(line().replace("Assumptions: ", ""));
    choose("#role-tank");
    await app.whenIdle();
    expect($("#stance-note").hidden).toBe(true);
    expect($('[data-f="assume-stance"]').textContent).toBe("");
    expect(line()).not.toContain("Berserker");
  });
});


describe("the stance note follows the setup (R11)", () => {
  it("shows the note of the hands for a setup of the hands and the note of a bow for the bow, and neither for a build that plays no stance", async () => {
    const app = mount();
    choose("#role-melee");
    await app.whenIdle();
    expect($("#stance-note").hidden).toBe(false);
    expect($("#stance-note-bow").hidden).toBe(true);
    expect($("#stance-note-bow").textContent).toContain("not a bow's shot");
    app.paintAssumptions({ ...app.displayed, setup: "ranged" });
    expect($("#stance-note").hidden).toBe(true);
    expect($("#stance-note-bow").hidden).toBe(false);
    app.paintAssumptions({ ...app.displayed, setup: "dw" });
    expect($("#stance-note").hidden).toBe(false);
    expect($("#stance-note-bow").hidden).toBe(true);
    choose("#role-tank");
    await app.whenIdle();
    expect($("#stance-note").hidden).toBe(true);
    expect($("#stance-note-bow").hidden).toBe(true);
    app.paintAssumptions({ ...app.displayed, setup: "ranged" });
    expect($("#stance-note-bow").hidden).toBe(true);
  });
});

describe("the notes about haste (T10)", () => {
  let app;
  beforeEach(() => {
    app = mount();
  });
  const row = () => $('[data-f="haste-note"]').textContent;
  const box = () => $("#haste-spell-note").textContent;

  it("say both answers beside the haste figure and the box, with the numbers of the trio's spell, and follow the buffs", async () => {
    const baked = { row: row(), box: box() };
    expect(baked.row).toBe(
      'Only the highest worn haste counts. With no haste spell it counts in full, up to 75%. With Valor of Marr (25% haste) only 50 points of worn haste count (75 minus 25), so a smaller haste item reaches the cap and its slot goes to stats. Unbound Alacrity adds a flat 10 on top. Tick "I have a haste spell" to see that kit.',
    );
    expect(baked.box).toBe(
      "Valor of Marr gives 25% haste, so worn haste counts only up to 50 points: a smaller haste item is enough, and its slot goes to stats. Unbound Alacrity adds a flat 10 on top. Without a spell the best worn haste counts in full, up to 75%. Tick the box to see that kit.", // (R12: the box note of a Monk trio says the flat 10 as the row note does)
    );
    expect($("#haste-spell-note").hidden).toBe(false);
    choose("#buffs-group");
    await app.whenIdle();
    expect(row()).toContain("With Alacrity (40% haste) only 35 points of worn haste count (75 minus 40)");
    expect(box()).toContain("Alacrity gives 40% haste, so worn haste counts only up to 35 points");
    $("#buffs-ench").checked = true;
    $("#buffs-ench").dispatchEvent(new Event("change", { bubbles: true }));
    await app.whenIdle();
    expect(row()).toContain("With Swift Like the Wind (60% haste) only 15 points of worn haste count (75 minus 60)");
    choose("#buffs-own");
    await app.whenIdle();
    expect(row()).toBe(baked.row); // the words of the code are the words of the baked page
    expect(box()).toBe(baked.box);
  });
});
