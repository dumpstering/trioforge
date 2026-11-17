// @vitest-environment jsdom
//
// The picker on the home page (static/picker.js) run in jsdom against the baked page the generator writes (fixtures/site/contract/home-main.html, which
// pipeline/tests/test_site_build.py checks against the generator). A visitor chooses three classes with the chips or types them in the search box, in any order and in any case, with
// the codes ("pal mnk ber") or the full names ("paladin monk berserker", "shadow knight"), and is offered the page of the trio, or told plainly that it is coming soon. The chips and the
// box are two ways to say one thing: what one says the other shows. (The first tests of the chips alone are in trio.test.mjs, from before the box.)

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MAX_QUERY_LENGTH, initPicker, readQuery } from "../pipeline/trioforge/site/static/picker.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract");
const text = (name) => readFileSync(resolve(CONTRACT, name), "utf8");

const CLASSES = [
  ["WAR", "Warrior"], ["CLR", "Cleric"], ["PAL", "Paladin"], ["RNG", "Ranger"], ["SHD", "Shadow Knight"], ["DRU", "Druid"], ["MNK", "Monk"], ["BRD", "Bard"],
  ["ROG", "Rogue"], ["SHM", "Shaman"], ["NEC", "Necromancer"], ["WIZ", "Wizard"], ["MAG", "Magician"], ["ENC", "Enchanter"], ["BST", "Beastlord"], ["BER", "Berserker"],
].map(([code, name]) => ({ code, name })); // prettier-ignore

const permutations = (items) =>
  items.length <= 1 ? [items] : items.flatMap((item, at) => permutations([...items.slice(0, at), ...items.slice(at + 1)]).map((rest) => [item, ...rest]));

/** The trios the build made, as the picker is given them: one of the five is the milestone's. */
const LIVE = ["clr-pal-shd", "clr-shd-ber", "mnk-shm-ber", "pal-mnk-ber", "pal-shd-ber"];

let navigate;

function mount(live = LIVE) {
  document.body.innerHTML = text("home-main.html");
  document.getElementById("picker").dataset.live = live.join(" ");
  navigate = vi.fn();
  window.history.replaceState(null, "", "/");
  return initPicker(document, { navigate });
}

const search = () => document.getElementById("trio-search");
const status = () => document.getElementById("picker-status");
const link = () => status().querySelector("a");
const chosen = () => [...document.querySelectorAll('#picker input[type="checkbox"]')].filter((box) => box.checked).map((box) => box.value);
const disabled = () => [...document.querySelectorAll('#picker input[type="checkbox"]')].filter((box) => box.disabled).length;
const say = () => status().textContent;

function type(value) {
  search().value = value;
  search().dispatchEvent(new Event("input", { bubbles: true }));
}

function click(code) {
  const box = document.querySelector(`#picker input[value="${code}"]`);
  box.checked = !box.checked;
  box.dispatchEvent(new Event("change", { bubbles: true }));
}

function press(key) {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
  search().dispatchEvent(event);
  return event;
}

describe("the classes in a query", () => {
  const read = (query) => readQuery(query, CLASSES);

  it("takes the codes, in the order they are typed, in any case", () => {
    expect(read("pal mnk ber").codes).toEqual(["PAL", "MNK", "BER"]);
    expect(read("BER Pal mNk").codes).toEqual(["BER", "PAL", "MNK"]);
    expect(read("  ber   pal\tmnk \n").codes).toEqual(["BER", "PAL", "MNK"]);
  });

  it("takes the full names, in any case", () => {
    expect(read("paladin monk berserker").codes).toEqual(["PAL", "MNK", "BER"]);
    expect(read("BERSERKER Paladin MONK").codes).toEqual(["BER", "PAL", "MNK"]);
    for (const { code, name } of CLASSES) expect(read(name).codes, name).toEqual([code]);
    for (const { code, name } of CLASSES) expect(read(name.toUpperCase()).codes, name).toEqual([code]);
    for (const { code } of CLASSES) expect(read(code.toLowerCase()).codes, code).toEqual([code]);
  });

  it("takes a name of two words however it is spaced, and in the middle of others", () => {
    for (const typed of ["shadow knight", "Shadow Knight", "SHADOW  KNIGHT", "shadowknight", "Shadow-Knight", "shadow_knight", "shadow, knight"]) {
      expect(read(typed).codes, typed).toEqual(["SHD"]);
    }
    expect(read("monk shadow knight berserker").codes).toEqual(["MNK", "SHD", "BER"]);
    expect(read("Shadow Knight, Monk / Paladin").codes).toEqual(["SHD", "MNK", "PAL"]);
  });

  it("takes any of the separators a visitor or a link has: spaces, commas, slashes, hyphens, plus signs", () => {
    for (const typed of ["pal,mnk,ber", "pal/mnk/ber", "pal-mnk-ber", "pal+mnk+ber", "pal ; mnk | ber", "Paladin / Monk / Berserker", "(pal) [mnk] {ber}"]) {
      expect(read(typed).codes, typed).toEqual(["PAL", "MNK", "BER"]);
    }
    expect(read("/trio/pal-mnk-ber/")).toMatchObject({ codes: ["PAL", "MNK", "BER"], unknown: [] }); // (the address of a trio page, pasted)
  });

  it("passes over the words that only join the classes: and, or, plus, the, trio", () => {
    expect(read("pal and mnk, or ber")).toEqual({ codes: ["PAL", "MNK", "BER"], unknown: [], partial: "", partialClass: false });
    expect(read("The trio: Paladin plus Monk plus Berserker")).toEqual({ codes: ["PAL", "MNK", "BER"], unknown: [], partial: "", partialClass: false });
    expect(read("shadow knight and cleric")).toMatchObject({ codes: ["SHD", "CLR"], unknown: [] });
    expect(read("and or plus the trio")).toEqual({ codes: [], unknown: [], partial: "", partialClass: false });
    expect(read("pal an")).toMatchObject({ codes: ["PAL"], unknown: [], partial: "an", partialClass: false }); // (the start of "and" is not a mistake either, and not the start of a class)
    expect(read("pal mnk ber andy")).toMatchObject({ unknown: ["andy"] });
    expect(read("pal xan")).toMatchObject({ codes: ["PAL"], unknown: ["xan"], partial: "" });
  });

  it("counts a class once however often it is named", () => {
    expect(read("pal pal mnk paladin").codes).toEqual(["PAL", "MNK"]);
  });

  it("names the words that are not a class, and does not take them for one", () => {
    expect(read("pal mnk berr")).toMatchObject({ codes: ["PAL", "MNK"], unknown: ["berr"], partial: "" });
    expect(read("xyz pal")).toMatchObject({ codes: ["PAL"], unknown: ["xyz"] });
    expect(read("knight").unknown).toEqual(["knight"]); // (half of a name is not the start of it)
    expect(read("pal 7 mnk").codes).toEqual(["PAL", "MNK"]); // (a number is a separator)
  });

  it("does not call the word still being typed a mistake: the last word that begins a name is a start", () => {
    expect(read("pal mnk bers")).toMatchObject({ codes: ["PAL", "MNK"], unknown: [], partial: "bers" });
    expect(read("pal mnk b")).toMatchObject({ codes: ["PAL", "MNK"], unknown: [], partial: "b" });
    expect(read("shadow")).toMatchObject({ codes: [], unknown: [], partial: "shadow" });
    expect(read("pal sh")).toMatchObject({ codes: ["PAL"], unknown: [], partial: "sh" });
    expect(read("bers pal")).toMatchObject({ codes: ["PAL"], unknown: ["bers"] }); // (a start that is not last is a word that was finished)
    expect(read("pal mnk ber").partial).toBe(""); // (a whole code is a class, not a start)
  });

  it("says nothing for an empty query, whatever it is made of", () => {
    for (const empty of ["", "   ", "\n", "123", "--", "/", undefined, null, 5, {}]) {
      expect(readQuery(empty, CLASSES), String(empty)).toEqual({ codes: [], unknown: [], partial: "", partialClass: false });
    }
  });

  it("finds more than three when there are more, and leaves the choice of three to the page", () => {
    expect(read("pal mnk ber war cleric").codes).toEqual(["PAL", "MNK", "BER", "WAR", "CLR"]);
  });

  it("knows only the classes it is given", () => {
    expect(readQuery("pal mnk", [{ code: "PAL", name: "Paladin" }]).codes).toEqual(["PAL"]);
    expect(readQuery("pal", []).codes).toEqual([]);
  });

  it("is not fooled by letters that only look like a class", () => {
    for (const typed of ["\uFF50\uFF41\uFF4C", "\u0440al", "pa\u200Bl", "\u212Aing"]) {
      expect(read(typed).codes, typed).toEqual([]);
    }
  });
});

describe("the picker on the page the generator writes", () => {
  beforeEach(() => mount());

  it("is offered once the script runs, with the box empty and nothing chosen", () => {
    expect(document.getElementById("picker").hidden).toBe(false);
    expect(search().value).toBe("");
    expect(chosen()).toEqual([]);
    expect(say()).toBe(""); // (nothing is said while no class is chosen: the heading of the picker says to pick three)
  });

  it("has the chips the classes of the site are, in the order of the site's classes, named as the search reads them", () => {
    const boxes = [...document.querySelectorAll('#picker input[type="checkbox"]')];
    expect(boxes.map((box) => box.value)).toEqual(CLASSES.map((one) => one.code));
    expect(boxes.map((box) => document.querySelector(`label[for="${box.id}"]`).textContent)).toEqual(CLASSES.map((one) => one.name));
  });

  it("opens a trio the build made from the chips in every order of choosing them", () => {
    for (const order of permutations(["PAL", "MNK", "BER"])) {
      mount();
      for (const code of order) click(code);
      expect(link().getAttribute("href"), order.join(" ")).toBe("/trio/pal-mnk-ber/");
      expect(link().textContent).toBe("Open Paladin / Monk / Berserker: best gear");
      expect(chosen()).toEqual(["PAL", "MNK", "BER"]);
    }
  });

  it("opens each of the five trios the build made from the chips, in any order, and no other", () => {
    for (const slug of LIVE) {
      for (const order of permutations(slug.toUpperCase().split("-"))) {
        mount();
        for (const code of order) click(code);
        expect(link().getAttribute("href"), `${slug} ${order.join(" ")}`).toBe(`/trio/${slug}/`);
      }
    }
  });

  it("opens the trio from the box in every order, with the codes and with the names, in any case", () => {
    for (const order of permutations(["pal", "mnk", "ber"])) {
      for (const typed of [order.join(" "), order.join(" ").toUpperCase(), order.map((c) => ({ pal: "Paladin", mnk: "Monk", ber: "Berserker" })[c]).join(" ")]) {
        mount();
        type(typed);
        expect(link().getAttribute("href"), typed).toBe("/trio/pal-mnk-ber/");
        expect(chosen(), typed).toEqual(["PAL", "MNK", "BER"]);
        expect(search().value, "what is typed is left as it is").toBe(typed);
      }
    }
  });

  it("opens each of the five trios from the box, however the classes are named and in whatever order", () => {
    for (const slug of LIVE) {
      for (const order of permutations(slug.split("-"))) {
        mount();
        type(order.join(" "));
        expect(link().getAttribute("href"), `${slug} ${order.join(" ")}`).toBe(`/trio/${slug}/`);
      }
    }
  });

  it("takes a name of two words from the box", () => {
    type("Berserker, shadow knight and Cleric");
    expect(chosen()).toEqual(["CLR", "SHD", "BER"]);
    expect(link().getAttribute("href")).toBe("/trio/clr-shd-ber/");
    type("clr shadowknight ber");
    expect(link().getAttribute("href")).toBe("/trio/clr-shd-ber/");
  });

  it("says that a trio that is not built is coming soon, plainly, and offers no link to it", () => {
    type("pal mnk rog");
    expect(link()).toBeNull();
    expect(say()).toBe("Paladin / Monk / Rogue: coming soon. There is no page for this trio yet.");
    mount();
    for (const code of ["ROG", "MNK", "PAL"]) click(code);
    expect(link()).toBeNull();
    expect(say()).toBe("Paladin / Monk / Rogue: coming soon. There is no page for this trio yet.");
  });

  it("says how many classes are still to pick, from the box as from the chips", () => {
    type("pal");
    expect(say()).toBe("Pick 2 more classes.");
    expect(chosen()).toEqual(["PAL"]);
    type("pal mnk");
    expect(say()).toBe("Pick 1 more class.");
    type("");
    expect(say()).toBe(""); // (nothing is said while no class is chosen: the heading of the picker says to pick three)
    expect(chosen()).toEqual([]);
  });

  it("names a word that is no class, and goes on with the ones that are", () => {
    type("pal mnk xyz");
    expect(chosen()).toEqual(["PAL", "MNK"]);
    expect(say()).toBe("Pick 1 more class. Not a class: xyz.");
    type("pal xyz abc");
    expect(say()).toBe("Pick 2 more classes. Not classes: xyz, abc.");
    type("pal mnk ber xyz");
    expect(link().getAttribute("href")).toBe("/trio/pal-mnk-ber/"); // the three are named, so they are offered
    expect(say()).toContain("Not a class: xyz.");
  });

  it("does not call the word still being typed a mistake", () => {
    type("pal mnk bers");
    expect(say()).toBe("Pick 1 more class.");
    type("pal mnk berserker");
    expect(link().getAttribute("href")).toBe("/trio/pal-mnk-ber/");
  });

  it("uses the first three when more are named, and says so", () => {
    type("pal mnk ber war cleric");
    expect(chosen()).toEqual(["PAL", "MNK", "BER"]);
    expect(link().getAttribute("href")).toBe("/trio/pal-mnk-ber/");
    expect(say()).toContain("A trio has three classes: the first three are used.");
    type("pal mnk ber");
    expect(say()).not.toContain("A trio has three classes");
  });

  it("stops at three chips, whichever way they were chosen, and gives the choice back when the box is edited", () => {
    type("pal mnk ber");
    expect(disabled()).toBe(13);
    type("pal mnk");
    expect(disabled()).toBe(0);
    type("");
    for (const code of ["WAR", "CLR", "PAL"]) click(code);
    expect(disabled()).toBe(13);
    type("");
    expect(disabled()).toBe(0);
    expect(chosen()).toEqual([]);
  });

  it("writes the choice of the chips into the box, in the codes the box reads, so that the two say one thing", () => {
    click("PAL");
    expect(search().value).toBe("pal");
    click("MNK");
    expect(search().value).toBe("pal mnk");
    click("BER");
    expect(search().value).toBe("pal mnk ber");
    click("PAL");
    expect(search().value).toBe("mnk ber");
    expect(say()).toBe("Pick 1 more class.");
    // and what was typed is read again from the box, not from what the chips were
    type("war clr pal");
    expect(chosen()).toEqual(["WAR", "CLR", "PAL"]);
  });

  it("opens the page from the box with the Enter key when there is one to open, and does nothing otherwise", () => {
    type("ber mnk pal");
    const event = press("Enter");
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/trio/pal-mnk-ber/");
    expect(event.defaultPrevented).toBe(true);
    navigate.mockClear();
    type("pal mnk rog");
    press("Enter");
    type("pal");
    press("Enter");
    type("");
    press("Enter");
    press("a");
    press("Escape");
    expect(navigate).not.toHaveBeenCalled();
  });

  it("puts the cursor in the box when the address asks for the search, and not otherwise", () => {
    window.history.replaceState(null, "", "/#search");
    document.body.innerHTML = text("home-main.html");
    initPicker(document, { navigate });
    expect(document.activeElement).toBe(search());
    window.history.replaceState(null, "", "/#k=abc");
    document.body.innerHTML = text("home-main.html");
    initPicker(document, { navigate });
    expect(document.activeElement).not.toBe(search());
    window.history.replaceState(null, "", "/#searching");
    document.body.innerHTML = text("home-main.html");
    initPicker(document, { navigate });
    expect(document.activeElement).not.toBe(search());
  });

  it("puts nothing of what is typed into the page but as text", () => {
    type("<img src=x onerror=alert(1)> pal <b>mnk</b>");
    expect(document.querySelector("#picker img, #picker b")).toBeNull();
    expect(status().innerHTML).not.toContain("<img");
    expect(say()).toContain("Not classes:");
    expect(say().length, "a long word is cut").toBeLessThan(200);
    type("x".repeat(5000));
    expect(say().length).toBeLessThan(200);
    expect(link()).toBeNull();
  });

  it("offers a link to a built trio only: the data of the page decides which, and nothing the box says", () => {
    mount(["pal-mnk-ber"]);
    type("pal shd ber");
    expect(link()).toBeNull();
    expect(say()).toContain("coming soon");
    type("pal mnk ber");
    expect(link().getAttribute("href")).toBe("/trio/pal-mnk-ber/");
    mount([]);
    type("pal mnk ber");
    expect(link()).toBeNull();
  });
});

describe("a page the picker was not written for", () => {
  it("works with the chips alone when the page has no search box", () => {
    document.body.innerHTML = text("home-main.html");
    document.getElementById("trio-search").closest(".control").remove();
    initPicker(document, { navigate: vi.fn() });
    for (const code of ["BER", "PAL", "MNK"]) click(code);
    expect(link().getAttribute("href")).toBe("/trio/pal-mnk-ber/");
  });

  it("does nothing on a page that has no picker", () => {
    document.body.innerHTML = "<main></main>";
    expect(() => initPicker(document, { navigate: vi.fn() })).not.toThrow();
    document.body.innerHTML = '<div id="picker"></div>';
    expect(() => initPicker(document)).not.toThrow();
  });
});

describe("the name of two words, while it is being typed", () => {
  const read = (query) => readQuery(query, CLASSES);

  it("is no mistake until it is finished: its first word, and its first word with the start of its second, are unfinished when they end the query", () => {
    for (const typed of ["shadow", "shadow k", "shadow kn", "shadow kni", "shadow knig", "shadow knigh"]) {
      expect(read(`pal mnk ${typed}`), typed).toMatchObject({ codes: ["PAL", "MNK"], unknown: [], partial: typed, partialClass: true });
    }
  });

  it("is finished when the whole name is typed, in two words or in one", () => {
    expect(read("pal mnk shadow knight")).toMatchObject({ codes: ["PAL", "MNK", "SHD"], unknown: [], partial: "", partialClass: false });
    expect(read("pal mnk shadowknight")).toMatchObject({ codes: ["PAL", "MNK", "SHD"], unknown: [], partial: "" });
    expect(read("shadowk")).toMatchObject({ codes: [], unknown: [], partial: "shadowk", partialClass: true });
  });

  it("is a mistake when the second word is not the start of the name, or when more words follow", () => {
    expect(read("pal mnk shadow x")).toMatchObject({ unknown: ["shadow", "x"], partial: "", partialClass: false });
    expect(read("shadow k pal")).toMatchObject({ codes: ["PAL"], unknown: ["shadow", "k"] });
    expect(read("shadow knightly")).toMatchObject({ unknown: ["shadow", "knightly"] });
    expect(read("knight shadow")).toMatchObject({ unknown: ["knight"], partial: "shadow", partialClass: true });
    expect(read("shadow and k")).toMatchObject({ unknown: ["shadow", "k"] });
  });

  it("is no mistake in the picker either: the status does not name its words", () => {
    mount();
    for (const typed of ["pal mnk shadow", "pal mnk shadow k", "pal mnk shadow kn", "pal mnk shadow knigh"]) {
      type(typed);
      expect(say(), typed).toBe("Pick 1 more class.");
    }
    type("pal mnk shadow x");
    expect(say()).toBe("Pick 1 more class. Not classes: shadow, x.");
  });
});

describe("a word after three full classes that begins a class", () => {
  beforeEach(() => mount());

  it("says that the first three are used, as a fourth code does, and the link is still the trio of the first three", () => {
    for (const typed of ["pal mnk ber war", "pal mnk ber shadow", "pal mnk ber shadow k", "pal mnk ber shadow knigh", "pal mnk ber sha", "pal mnk ber s"]) {
      mount();
      type(typed);
      expect(link().getAttribute("href"), typed).toBe("/trio/pal-mnk-ber/");
      expect(say(), typed).toContain("A trio has three classes: the first three are used.");
      expect(chosen(), typed).toEqual(["PAL", "MNK", "BER"]);
    }
  });

  it("says nothing of the kind for a word that begins no class, for a joining word, for a finished extra word that is no class, or while a class is still to pick", () => {
    for (const typed of ["pal mnk ber an", "pal mnk ber and", "pal mnk ber the trio", "pal mnk ber or pl"]) {
      mount();
      type(typed);
      expect(say(), typed).toBe("Open Paladin / Monk / Berserker: best gear");
    }
    mount();
    type("pal mnk ber xyz");
    expect(say()).toBe("Open Paladin / Monk / Berserker: best gear Not a class: xyz.");
    mount();
    type("pal mnk sha");
    expect(say()).toBe("Pick 1 more class.");
  });

  it("is read when Enter is pressed as it is shown: the trio of the first three", () => {
    type("pal mnk ber shadow");
    press("Enter");
    expect(navigate).toHaveBeenCalledWith("/trio/pal-mnk-ber/");
  });
});

describe("an address pasted into the box", () => {
  beforeEach(() => mount());
  const here = (path) => window.location.origin + path;
  /** A kit link as the page's Share button makes one: the longest payload the codec reads. */
  const KIT = "AbC_-9".repeat(341) + "Ab";

  it("goes to the page of the trio with its query and its fragment kept, whatever the order of the classes in it: the kit is not lost", () => {
    for (const path of ["/trio/ber-mnk-pal/", "/trio/pal-mnk-ber/", "/Trio/BER-Mnk-Pal", "/trio/mnk-ber-pal"]) {
      type(here(`${path}?tier=4#k=AAECAwQF`));
      expect(link().getAttribute("href"), path).toBe("/trio/pal-mnk-ber/?tier=4#k=AAECAwQF");
      expect(link().textContent).toBe("Open Paladin / Monk / Berserker: best gear");
      expect(chosen(), path).toEqual(["PAL", "MNK", "BER"]);
      expect(say(), "no word of the address is named").not.toMatch(/Not class|localhost|trioforge|http/i);
    }
  });

  it("keeps a kit of the longest size the codec reads, and the box takes the whole link", () => {
    expect(KIT).toHaveLength(2048);
    const address = here(`/trio/ber-mnk-pal/?race=OGR&role=balanced&tier=10#k=${KIT}`);
    expect(address.length).toBeLessThanOrEqual(MAX_QUERY_LENGTH);
    type(address);
    expect(link().getAttribute("href")).toBe(`/trio/pal-mnk-ber/?race=OGR&role=balanced&tier=10#k=${KIT}`);
  });

  it("takes a path alone, a link with spaces round it, and a link written in capitals", () => {
    type("/trio/BER-MNK-PAL/?x=1#k=Q");
    expect(link().getAttribute("href")).toBe("/trio/pal-mnk-ber/?x=1#k=Q");
    type("  \n" + here("/trio/ber-mnk-pal/#k=Q") + "  ");
    expect(link().getAttribute("href")).toBe("/trio/pal-mnk-ber/#k=Q");
    type(window.location.origin.toUpperCase() + "/TRIO/BER-MNK-PAL/");
    expect(link().getAttribute("href")).toBe("/trio/pal-mnk-ber/");
  });

  it("is opened with Enter, with the fragment", () => {
    type(here("/trio/ber-mnk-pal/?tier=4#k=AAECAwQF"));
    press("Enter");
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/trio/pal-mnk-ber/?tier=4#k=AAECAwQF");
  });

  it("says to open it in the address bar when it is the address of another site, whatever it names", () => {
    for (const typed of [
      "https://example.org/trio/pal-mnk-ber/?tier=4#k=AAECAwQF",
      "http://example.org/",
      "//example.org/trio/pal-mnk-ber/",
      window.location.origin + ".example.org/trio/pal-mnk-ber/",
      `https://${window.location.host}@example.org/trio/pal-mnk-ber/`,
      "ftp://example.org/trio/pal-mnk-ber/",
      "javascript://example.org/%0Aalert(1)",
      "data://text/plain,pal-mnk-ber",
      "file:///trio/pal-mnk-ber/",
    ]) {
      mount();
      click("WAR");
      type(typed);
      expect(link(), typed).toBeNull();
      expect(say(), typed).toBe("This is an address, not classes. Open it in the address bar of your browser.");
      expect(chosen(), "an address chooses no class").toEqual([]);
      press("Enter");
    }
    expect(navigate).not.toHaveBeenCalled();
  });

  it("says the same of an address of this site that is not the page of a trio of the build", () => {
    for (const path of ["/rules/", "/item/w123/", "/trio/war-clr-pal/?x=1#k=Q", "/trio/", "/trio/pal-mnk-ber/extra/", "/trio/pal-mnk-ber%2Fx/"]) {
      mount();
      type(here(path));
      expect(link(), path).toBeNull();
      expect(say(), path).toBe("This is an address, not classes. Open it in the address bar of your browser.");
    }
  });

  it("is not an address when it only begins like a path: classes typed with slashes are still classes", () => {
    for (const typed of ["/pal/mnk/ber", "pal/mnk/ber", "/ pal mnk ber", "javascript:alert(1) pal mnk ber", "trio/ber-mnk-pal"]) {
      mount();
      type(typed);
      expect(link().getAttribute("href"), typed).toBe("/trio/pal-mnk-ber/");
    }
  });

  it("checks the address once more before it offers it, whatever made the address", () => {
    for (const made of ["https://example.org/", "//example.org/trio/pal-mnk-ber/", "javascript:alert(1)", "/trio/war-clr-pal/", "/trio/pal-mnk-ber", "trio/pal-mnk-ber/", "", 5, undefined]) {
      document.body.innerHTML = text("home-main.html");
      document.getElementById("picker").dataset.live = LIVE.join(" ");
      navigate = vi.fn();
      initPicker(document, { navigate, trioAddress: () => made });
      type(here("/trio/ber-mnk-pal/?tier=4#k=abc"));
      expect(link(), String(made)).toBeNull();
      expect(say(), String(made)).toBe("This is an address, not classes. Open it in the address bar of your browser.");
    }
    // the control: an address of the page of a trio of the list is offered, and the chips follow it
    document.body.innerHTML = text("home-main.html");
    document.getElementById("picker").dataset.live = LIVE.join(" ");
    initPicker(document, { navigate: vi.fn(), trioAddress: () => "/trio/pal-mnk-ber/?a=b#c" });
    type(here("/trio/ber-mnk-pal/"));
    expect(link().getAttribute("href")).toBe("/trio/pal-mnk-ber/?a=b#c");
    expect(chosen()).toEqual(["PAL", "MNK", "BER"]);
  });

  it("goes back to reading classes when the address is taken out of the box", () => {
    type("https://example.org/");
    expect(say()).toMatch(/address bar/);
    type("pal mnk");
    expect(say()).toBe("Pick 1 more class.");
    expect(chosen()).toEqual(["PAL", "MNK"]);
    type("");
    expect(say()).toBe(""); // (nothing is said while no class is chosen: the heading of the picker says to pick three)
  });

  it("names a link to a trio that the build made with the same words as the chips do", () => {
    type(here("/trio/clr-shd-ber/?tier=0"));
    expect(link().getAttribute("href")).toBe("/trio/clr-shd-ber/?tier=0");
    expect(link().textContent).toBe("Open Cleric / Shadow Knight / Berserker: best gear");
    expect(chosen()).toEqual(["CLR", "SHD", "BER"]);
  });
});

describe("the status line, which a screen reader says again whenever it is replaced", () => {
  /** Count the changes made to the status line since the last look (the observer's records, taken at once). */
  function watchStatus() {
    const observer = new MutationObserver(() => {});
    observer.observe(status(), { childList: true, characterData: true, subtree: true, attributes: true });
    return () => observer.takeRecords().length;
  }

  it("is left as the page wrote it when the picker starts", () => {
    document.body.innerHTML = text("home-main.html");
    const changes = watchStatus();
    initPicker(document, { navigate: vi.fn() });
    expect(changes()).toBe(0);
  });

  it("is not touched while what it says stays the same: a word still being typed, a space, a capital, a class named another way", () => {
    mount();
    const changes = watchStatus();
    for (const typed of ["s", "sh", "sha", "shad", "shadow", "shadow ", "shadow k", "shadow kn", ""]) {
      type(typed);
      expect(changes(), JSON.stringify(typed)).toBe(0);
    }
    type("pal");
    expect(changes(), "the words change").toBeGreaterThan(0);
    for (const typed of ["pal ", "PAL", "paladin", " paladin "]) {
      type(typed);
      expect(changes(), JSON.stringify(typed)).toBe(0);
    }
  });

  it("is replaced when its words change or its link changes, and only then", () => {
    mount();
    const changes = watchStatus();
    type("pal mnk");
    expect(changes()).toBeGreaterThan(0); // "Pick 1 more class."
    type("pal mnk ber");
    expect(changes(), "the link").toBeGreaterThan(0);
    type("ber pal mnk");
    expect(changes(), "the same link").toBe(0);
    type("pal mnk ber ");
    expect(changes()).toBe(0);
    type("pal mnk ber war");
    expect(changes(), "a note").toBeGreaterThan(0);
    type("pal mnk ber war cleric");
    expect(changes(), "the same note and the same link").toBe(0);
    type("clr shd ber");
    expect(changes(), "another link").toBeGreaterThan(0);
  });

  it("is the same through the chips: a chip that changes nothing it says leaves it alone", () => {
    mount();
    const changes = watchStatus();
    click("PAL");
    expect(changes()).toBeGreaterThan(0);
    click("PAL");
    expect(changes(), "back to the first words").toBeGreaterThan(0);
    click("WAR");
    click("WAR");
    changes();
    type("sha");
    expect(changes()).toBe(0);
  });
});

describe("the length of what is typed", () => {
  it("is limited by the box to a number that is more than the longest link to a shared kit, and little more", () => {
    mount();
    expect(Number(search().getAttribute("maxlength"))).toBe(MAX_QUERY_LENGTH);
    const longest = `https://trioforge.pages.dev/trio/pal-mnk-ber/?race=OGR&role=balanced&tier=10&setup=1h-shield&ev=strict&buffs=group#k=${"A".repeat(2049)}`;
    expect(MAX_QUERY_LENGTH).toBeGreaterThanOrEqual(longest.length);
    expect(MAX_QUERY_LENGTH).toBeLessThanOrEqual(4096);
  });

  it("is read no further than that by the picker, however much is given it", () => {
    expect(readQuery(`${"x".repeat(MAX_QUERY_LENGTH)} pal mnk ber`, CLASSES).codes).toEqual([]);
    expect(readQuery(`pal mnk ber ${"x ".repeat(MAX_QUERY_LENGTH)}`, CLASSES).unknown.length).toBeLessThanOrEqual(MAX_QUERY_LENGTH / 2);
    expect(readQuery("pal ".repeat(500_000), CLASSES)).toMatchObject({ codes: ["PAL"], unknown: [] });
    mount();
    search().value = "x ".repeat(500_000); // (what a paste that the box would have cut could be, put in by a script)
    search().dispatchEvent(new Event("input", { bubbles: true }));
    expect(say().length).toBeLessThan(200);
    search().value = `https://example.org/${"a".repeat(500_000)}`;
    search().dispatchEvent(new Event("input", { bubbles: true }));
    expect(say()).toMatch(/address bar/);
  });
});
