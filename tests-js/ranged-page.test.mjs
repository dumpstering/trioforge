// @vitest-environment jsdom
//
// The page code (trio.js) run in jsdom against the baked page of a trio that has the bow setup and the Ranged role (a Paladin, a Ranger and a Berserker), as the generator
// writes it, and the browser data files it writes for it. Both are committed under fixtures/site/contract-ranged/ and checked against the generator by
// pipeline/tests/test_ranged_site.py (which makes them from a real run of the precompute on an invented catalog), so these tests run on exactly what the Python build
// produces. They hold the controls of the bow setup to the address: the role and the setup are offered, chosen, written to the address and read back from it.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it } from "vitest";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract-ranged");
const SLUG = "pal-rng-ber";
const text = (name) => readFileSync(resolve(CONTRACT, name), "utf8");
const dataFile = (name) => JSON.parse(text(`data/${name}.json`));
const RANGE = 17;
const MAIN = 20;
const OFF = 21;

function scenarioOf(name, race, role, tier, setup) {
  const doc = dataFile(name);
  const row = doc.rows.find((r) => r[0] === race && r[1] === role && r[2] === tier && r[3] === setup);
  if (!row) throw new Error(`no scenario ${race} ${role} ${tier} ${setup} in ${name}`);
  return { row, kit: doc.kits[row[4]].map((i) => (i < 0 ? null : doc.items[i])) };
}

function makeFetch(calls) {
  return async (url) => {
    calls.push(String(url));
    const name = String(url).replace(`/data/${SLUG}/`, "").replace(".json", "");
    return { ok: true, status: 200, json: async () => structuredClone(dataFile(name)) };
  };
}

function mount(search = "") {
  document.body.innerHTML = text("trio-main.html");
  window.history.replaceState(null, "", `/trio/${SLUG}/${search}`);
  const calls = [];
  const app = initTrio({ document, window, fetch: makeFetch(calls) });
  return { app, calls };
}

function choose(selector) {
  const radio = document.querySelector(selector);
  radio.checked = true;
  radio.dispatchEvent(new Event("change", { bubbles: true }));
}

const $ = (selector) => document.querySelector(selector);
const radios = (name) => [...document.querySelectorAll(`input[name="${name}"]`)];
const shown = (name) => radios(name).find((r) => r.checked)?.value;
const offered = (name) => radios(name).filter((r) => !r.hidden && !r.disabled).map((r) => r.value);
const field = (name) => document.querySelector(`[data-f="${name}"]`)?.textContent;
const query = () => new URLSearchParams(window.location.search);

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("the baked page of a trio with a Ranger and a bow", () => {
  it("offers the Ranged role after the others and the bow setup after the others, each for the roles that play it", () => {
    mount();
    expect(radios("role").map((r) => r.value)).toEqual(["tank", "melee", "ranged"]);
    const ranged = $("#role-ranged");
    expect(ranged.dataset.label).toBe("Archer");
    expect(ranged.dataset.setups).toBe("ranged");
    expect(ranged.dataset.hint).toBe("Damage from a bow first: attack, dexterity and haste, then hit points.");
    for (const role of ["tank", "melee"]) expect($(`#role-${role}`).dataset.setups.split(" ").at(-1)).toBe("ranged");
    expect(radios("setup").at(-1).value).toBe("ranged");
    expect($("#setup-ranged").dataset.label).toBe("Bow");
    expect($("#setup-ranged").dataset.phrase).toBe("bow");
  });

  it("has neither the range line nor the note about arrows in its markup, since its first answer is not a bow's", () => {
    mount();
    expect($(".bow-line")).toBeNull();
    expect($(".bow-note")).toBeNull();
    expect($("#weapons").textContent).not.toContain("arrow");
  });
});

describe("choosing the Ranged role", () => {
  it("shows the bow setup, its kit with a bow in the range place and the range line, and writes the role to the address", async () => {
    const { app } = mount();
    choose("#role-ranged");
    await app.whenIdle();
    expect(shown("role")).toBe("ranged");
    expect(offered("setup")).toEqual(["ranged"]);
    expect(shown("setup")).toBe("ranged");
    expect(field("assume-setup")).toBe("bow");
    expect($("#kit caption").textContent).toContain("Bow");
    expect($("#role-hint").textContent).toBe("Damage from a bow first: attack, dexterity and haste, then hit points.");
    const race = $("#sw-race").value;
    const tier = Number($("#sw-tier").value);
    const want = scenarioOf("wiki-own", race, "ranged", tier, "ranged");
    expect(want.kit[RANGE]).not.toBeNull();
    expect(field("w-range")).toBe(want.kit[RANGE][1]);
    expect($(".bow-line").hidden).toBe(false);
    expect($(".bow-note").hidden).toBe(false);
    expect($(".bow-note").textContent).toContain("arrow damage is not counted");
    expect($(".bow-note a").getAttribute("href")).toBe("/rules/#weapons.ranged_factor");
    expect($(".bow-note a").nextElementSibling?.className ?? "").toContain("seal"); // (the link carries the seal of its rule, as every other rule link of the page does)
    expect($(".bow-note a").nextElementSibling.textContent).toBe($("#weapons p.hint a").nextElementSibling.textContent); // (the seal of the weapons rule: the two are held equal by a test of the generator)
    expect(field("w-setup")).toBe("Bow");
    expect(query().get("role")).toBe("ranged");
    expect(query().has("setup")).toBe(false); // the role's only setup is its best, and the best is not a choice
  });

  it("reads the role back from an address", async () => {
    const { app } = mount("?role=ranged");
    await app.whenIdle();
    expect(shown("role")).toBe("ranged");
    expect(shown("setup")).toBe("ranged");
    expect($(".bow-line").hidden).toBe(false);
    expect($(".bow-note").hidden).toBe(false);
  });
});

describe("choosing the bow setup in another role", () => {
  it("writes the setup to the address, shows the bow in the range place and reads the address back", async () => {
    const { app } = mount();
    choose('input[name="setup"][value="ranged"]');
    await app.whenIdle();
    expect(shown("setup")).toBe("ranged");
    expect(query().get("setup")).toBe("ranged");
    const race = $("#sw-race").value;
    const tier = Number($("#sw-tier").value);
    const role = shown("role");
    const want = scenarioOf("wiki-own", race, role, tier, "ranged");
    expect(field("w-range")).toBe(want.kit[RANGE][1]);
    expect(field("w-main")).toBe(want.kit[MAIN] ? want.kit[MAIN][1] : "Empty"); // the hands are the stat sticks of the answer
    expect($(".bow-line").hidden).toBe(false);
    const address = window.location.search;
    // a reload of that address shows the same view
    const again = mount(address);
    await again.app.whenIdle();
    expect(shown("setup")).toBe("ranged");
    expect(shown("role")).toBe(role);
    expect(window.location.search).toBe(address);
  });

  it("lists the setups the role plays as the other setups, the bow's answer being the bow in the range place", async () => {
    const { app } = mount();
    choose("#role-tank");
    await app.whenIdle();
    const lines = [...document.querySelectorAll("#w-others li")].map((li) => li.textContent);
    expect(lines.some((line) => line.startsWith("Bow: "))).toBe(true);
    const race = $("#sw-race").value;
    const tier = Number($("#sw-tier").value);
    const kit = scenarioOf("wiki-own", race, "tank", tier, "ranged").kit;
    const [bow, main, off] = [kit[RANGE], kit[MAIN], kit[OFF]];
    const hands = (main ? main[1] : "nothing") + (off ? " + " + off[1] : "");
    // the bow, then the hands as the other lines give them (the main hand, and the off hand after a plus), then the difference
    expect(lines.find((line) => line.startsWith("Bow: "))?.startsWith(`Bow: ${bow[1]} with ${hands} (`)).toBe(true);
  });

  it("words the line of the bow as the generator baked it", async () => {
    document.body.innerHTML = text("trio-main.html");
    const baked = [...document.querySelectorAll("#w-others li")].map((li) => li.textContent);
    expect(baked.some((line) => line.startsWith("Bow: ") && line.includes(" with "))).toBe(true);
    window.history.replaceState(null, "", `/trio/${SLUG}/`);
    const app = initTrio({ document, window, fetch: makeFetch([]) });
    await app.whenIdle();
    expect([...document.querySelectorAll("#w-others li")].map((li) => li.textContent)).toEqual(baked);
  });

  it("keeps the range line out of sight in a setup that is not the bow", async () => {
    const { app } = mount("?setup=ranged");
    await app.whenIdle();
    expect($(".bow-line").hidden).toBe(false);
    choose('input[name="setup"]:not([value="ranged"]):not([hidden])');
    await app.whenIdle();
    expect(shown("setup")).not.toBe("ranged");
    expect($(".bow-line").hidden).toBe(true);
    expect($(".bow-note").hidden).toBe(true);
  });
});

describe("the rules cited for the Ranged role", () => {
  const notes = () => ["#role-hint", "#best-race-rules", "#runnerups-rules", "#why .kit-line"].map((id) => (id === "#role-hint" ? $(id).parentElement : $(id))); // (the line of "How roles weigh stats" in Why this kit is the fourth)
  const cited = (box) => [...box.querySelectorAll("a")].map((a) => a.getAttribute("href")).filter((href) => href.startsWith("/rules/#roles."));

  it("cites the templates in the four notes of the page for every role, and the Ranged role's rule besides for the Ranged role only", async () => {
    const { app } = mount();
    for (const box of notes()) expect(cited(box)).toContain("/rules/#roles.templates");
    for (const box of notes()) expect(cited(box)).not.toContain("/rules/#roles.ranged_template");
    choose("#role-ranged");
    await app.whenIdle();
    for (const box of notes()) {
      expect(cited(box)).toContain("/rules/#roles.templates"); // (the Ranged template is the Melee template with the factors: both are cited)
      expect(cited(box)).toContain("/rules/#roles.ranged_template");
      expect(cited(box).filter((href) => href === "/rules/#roles.ranged_template")).toHaveLength(1);
    }
    const link = $("#best-race-rules a[href='/rules/#roles.ranged_template']");
    expect(link.textContent).toBe($("#role-ranged").dataset.ruleTitle);
    expect(link.nextElementSibling?.className ?? "").toContain("seal"); // the seal of the rule is beside the link, as it is beside the others
    choose("#role-melee");
    await app.whenIdle();
    for (const box of notes()) expect(cited(box)).not.toContain("/rules/#roles.ranged_template");
  });

  it("cites it from the first paint when the address asks for the Ranged role", async () => {
    const { app } = mount("?role=ranged");
    await app.whenIdle();
    for (const box of notes()) expect(cited(box)).toContain("/rules/#roles.ranged_template");
  });
});

describe("the note of the bow setup on a page with no list of weapon lines", () => {
  // (a page whose weapons section lacks the list the range line goes in: the note stands apart from it, and follows the setup all the same)
  function mountWithoutList(search) {
    document.body.innerHTML = text("trio-main.html");
    $("#weapons dl.pairs").remove();
    window.history.replaceState(null, "", `/trio/${SLUG}/${search}`);
    return initTrio({ document, window, fetch: makeFetch([]) });
  }

  it("is made and shown in the bow setup, and hidden in the others", async () => {
    const app = mountWithoutList("?setup=ranged");
    await app.whenIdle();
    expect(shown("setup")).toBe("ranged");
    expect($(".bow-line")).toBeNull();
    expect($(".bow-note")).not.toBeNull();
    expect($(".bow-note").hidden).toBe(false);
    choose('input[name="setup"]:not([value="ranged"]):not([hidden])');
    await app.whenIdle();
    expect(shown("setup")).not.toBe("ranged");
    expect($(".bow-note").hidden).toBe(true);
    choose('input[name="setup"][value="ranged"]');
    await app.whenIdle();
    expect($(".bow-note").hidden).toBe(false);
    expect(document.querySelectorAll(".bow-note")).toHaveLength(1);
  });
});
