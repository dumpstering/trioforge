// @vitest-environment jsdom
//
// The gear picker of the Upgrade section: an ARIA list-autocomplete combobox (https://www.w3.org/WAI/ARIA/apg/patterns/combobox/, the "editable combobox with list
// autocomplete" example) over the items of a trio, with a tier select and an Add button. It is run in jsdom against the controls the generator writes into the page. The
// names are those of the site fixture, which are invented.

import { afterEach, describe, expect, it, vi } from "vitest";
import { MAX_OPTIONS, buildIndex, createGearPicker } from "../pipeline/trioforge/site/static/ui/gear-picker.js";
import { $, $$, mountPage, press, type, wake } from "./upgrade-helpers.mjs";

const entry = (key, name, slot = "Head") => ({ key, name, slot });
const ENTRIES = [
  entry("w80113", "Pellbrook Mallet", "Primary or Secondary"),
  entry("w90013", "Pauldrons of the Vanguard", "Shoulders"),
  entry("w8091", "Larkspur Pauldrons", "Shoulders"),
  entry("w90001", "Helm of the Stoneward", "Head"),
  entry("w90002", "Steel Cap of Valor", "Head"),
  entry("w80583", "Orchard Warden's Targe", "Secondary"),
  entry("w90020", "Bracer of the Iron Oath", "Wrist"),
  entry("w90037", "<b>x</b>", "Range"),
];
const names = (found) => found.map((item) => item.name);

// ---- the search --------------------------------------------------------------------------------------------------------------------

describe("the search", () => {
  const index = buildIndex(ENTRIES);

  it("matches the start of the name, then the start of any word of it, whatever the case, and lists the names alphabetically within each kind", () => {
    expect(names(index.search("pauld"))).toEqual(["Pauldrons of the Vanguard", "Larkspur Pauldrons"]); // the name that starts with it first
    expect(names(index.search("PAULDRONS"))).toEqual(["Pauldrons of the Vanguard", "Larkspur Pauldrons"]);
    expect(names(index.search("helm of"))).toEqual(["Helm of the Stoneward"]);
    expect(names(index.search("warden"))).toEqual(["Orchard Warden's Targe"]); // a word in the middle of the name
    expect(names(index.search("stone helm"))).toEqual(["Helm of the Stoneward"]); // every part of the query starts a word, in any order
  });

  it("lists the first names alphabetically for an empty query, and nothing for a query that matches nothing", () => {
    expect(names(index.search(""))).toEqual(names(ENTRIES).slice().sort((a, b) => (a.toLowerCase() < b.toLowerCase() ? -1 : 1)));
    expect(index.search("   ")).toHaveLength(ENTRIES.length);
    expect(index.search("zzz")).toEqual([]);
  });

  it("shows at most 20 options", () => {
    const many = Array.from({ length: 60 }, (_, i) => entry(`w${70000 + i}`, `Amber Ring ${String(i).padStart(2, "0")}`, "Finger"));
    const found = buildIndex(many).search("amber");
    expect(MAX_OPTIONS).toBe(20);
    expect(found).toHaveLength(20);
    expect(found[0].name).toBe("Amber Ring 00");
    expect(buildIndex(many).search("ring", 5)).toHaveLength(5);
    expect(buildIndex(many).search("")).toHaveLength(20);
  });

  it("never reads the query as a pattern: a dot is a dot, and the signs of a pattern match only themselves", () => {
    const odd = buildIndex([entry("w1", "A.C Ring"), entry("w2", "Abc Ring"), entry("w3", "Star* Cloak"), entry("w4", "Plain Cloak")]);
    expect(names(odd.search("a.c"))).toEqual(["A.C Ring"]);
    for (const query of ["(.*", "[a-", "\\", "+", "*", "?", "^", "$", "(", "|", "{1}", "a{", "(?<x>", "\\p{L}"]) {
      expect(() => odd.search(query), query).not.toThrow();
    }
    expect(odd.search(".*")).toEqual([]);
    expect(names(odd.search("star*"))).toEqual(["Star* Cloak"]);
  });

  it("is not thrown by what is not text, or by the names of the members of every object", () => {
    for (const query of [undefined, null, 42, {}, [], ["pauld"]]) expect(index.search(query)).toEqual([]);
    for (const query of ["constructor", "__proto__", "toString", "hasOwnProperty", "prototype"]) expect(index.search(query)).toEqual([]);
  });
});

// ---- the combobox ---------------------------------------------------------------------------------------------------------------------

function mount(entries = ENTRIES, extra = {}) {
  const root = mountPage();
  wake(root);
  const added = [];
  const notes = [];
  const picker = createGearPicker({
    input: $("#upgrade-pick"),
    list: $("#upgrade-list"),
    tier: $("#upgrade-tier"),
    add: $("#upgrade-add"),
    doc: document,
    entries,
    onAdd: (item, tier) => {
      added.push([item.key, tier]);
      return true;
    },
    onNote: (text) => notes.push(text),
    ...extra,
  });
  $("#upgrade-add").disabled = false;
  return { picker, added, notes, input: $("#upgrade-pick"), list: $("#upgrade-list") };
}

const options = () => $$('[role="option"]', $("#upgrade-list"));
const optionNames = () => options().map((o) => o.querySelector(".li-name").textContent);
const active = () => {
  const id = $("#upgrade-pick").getAttribute("aria-activedescendant");
  return id === null ? null : document.getElementById(id);
};

describe("the markup follows the pattern", () => {
  it("starts closed, with the text box named by its label and the list named", () => {
    const { input, list } = mount();
    expect(input.getAttribute("role")).toBe("combobox");
    expect(input.getAttribute("aria-autocomplete")).toBe("list");
    expect(input.getAttribute("aria-expanded")).toBe("false");
    expect(input.getAttribute("aria-controls")).toBe(list.id);
    expect(input.hasAttribute("aria-activedescendant")).toBe(false);
    expect(list.getAttribute("role")).toBe("listbox");
    expect(list.hidden).toBe(true);
    expect(list.getAttribute("aria-label")).toBeTruthy();
    expect($(`label[for="${input.id}"]`).textContent).toBeTruthy();
  });

  it("opens with the options of what is typed, each an option with its name and its slot as text", () => {
    const { input, list } = mount();
    type(input, "pauld");
    expect(list.hidden).toBe(false);
    expect(input.getAttribute("aria-expanded")).toBe("true");
    expect(optionNames()).toEqual(["Pauldrons of the Vanguard", "Larkspur Pauldrons"]);
    const [first] = options();
    expect(first.querySelector(".li-meta").textContent).toBe("Shoulders");
    expect(first.getAttribute("aria-selected")).toBe("false");
    expect(new Set(options().map((o) => o.id)).size).toBe(2); // the options have ids of their own
    expect(active()).toBeNull();
  });

  it("closes when nothing matches, and when the text is emptied it shows nothing until the visitor asks for the list", () => {
    const { input, list } = mount();
    type(input, "pauld");
    expect(options()).toHaveLength(2);
    type(input, "zzz");
    expect(list.hidden).toBe(true);
    expect(input.getAttribute("aria-expanded")).toBe("false");
    expect(options(), "no option of the text before is left in the closed list").toHaveLength(0);
    type(input, "");
    expect(list.hidden).toBe(true);
  });

  it("writes a name as text and never as markup", () => {
    const { input, list } = mount();
    type(input, "<b>x");
    expect(optionNames()).toEqual(["<b>x</b>"]);
    expect(list.querySelector("b")).toBeNull();
    expect(list.innerHTML).toContain("&lt;b&gt;x&lt;/b&gt;");
  });
});

describe("the keyboard, as in the list autocomplete example", () => {
  it("Down Arrow moves the visual focus to the first option and then to the next, while the focus of the page stays in the text box", () => {
    const { input } = mount();
    input.focus();
    type(input, "pauld");
    expect(press(input, "ArrowDown").defaultPrevented).toBe(true);
    expect(active()).toBe(options()[0]);
    expect(active().getAttribute("aria-selected")).toBe("true");
    expect(options()[1].getAttribute("aria-selected")).toBe("false");
    expect(document.activeElement).toBe(input);
    press(input, "ArrowDown");
    expect(active()).toBe(options()[1]);
    expect(options()[0].getAttribute("aria-selected")).toBe("false");
  });

  it("goes round the list: Down Arrow after the last option reaches the first, Up Arrow from the text box the last, and Up Arrow from the first the last", () => {
    const { input } = mount();
    type(input, "pauld");
    press(input, "ArrowDown");
    press(input, "ArrowDown");
    press(input, "ArrowDown");
    expect(active()).toBe(options()[0]);
    press(input, "ArrowUp");
    expect(active()).toBe(options()[1]);
    press(input, "ArrowUp");
    expect(active()).toBe(options()[0]);
    type(input, "pauld"); // typing gives the visual focus back to the text box
    expect(active()).toBeNull();
    press(input, "ArrowUp");
    expect(active()).toBe(options()[1]);
  });

  it("Down Arrow in an empty text box opens the list at its first option", () => {
    const { input, list } = mount();
    input.focus();
    press(input, "ArrowDown");
    expect(list.hidden).toBe(false);
    expect(input.getAttribute("aria-expanded")).toBe("true");
    expect(options()).toHaveLength(ENTRIES.length);
    expect(active()).toBe(options()[0]);
  });

  it("Alt and Down Arrow opens the list without moving the visual focus", () => {
    const { input, list } = mount();
    press(input, "ArrowDown", { altKey: true });
    expect(list.hidden).toBe(false);
    expect(active()).toBeNull();
  });

  it("Enter on the option with the visual focus puts its name in the text box and closes the list, the focus staying in the text box", () => {
    const { input, list, picker } = mount();
    input.focus();
    type(input, "lark");
    press(input, "ArrowDown");
    const event = press(input, "Enter");
    expect(event.defaultPrevented).toBe(true);
    expect(input.value).toBe("Larkspur Pauldrons");
    expect(list.hidden).toBe(true);
    expect(input.getAttribute("aria-expanded")).toBe("false");
    expect(input.hasAttribute("aria-activedescendant")).toBe(false);
    expect(document.activeElement).toBe(input);
    expect(picker.selected()?.key).toBe("w8091");
  });

  it("Escape closes the list and keeps the text; Escape with the list closed clears the text box", () => {
    const { input, list, picker } = mount();
    type(input, "pauld");
    press(input, "ArrowDown");
    press(input, "Escape");
    expect(list.hidden).toBe(true);
    expect(input.value).toBe("pauld");
    expect(input.hasAttribute("aria-activedescendant")).toBe(false);
    press(input, "Escape");
    expect(input.value).toBe("");
    expect(picker.selected()).toBeNull();
  });

  it("Home and End move the caret and are left to the text box; the visual focus returns to it", () => {
    const { input } = mount();
    input.focus();
    type(input, "pauld");
    press(input, "ArrowDown");
    expect(active()).not.toBeNull();
    const home = press(input, "Home");
    expect(home.defaultPrevented).toBe(false);
    expect(active()).toBeNull();
    press(input, "ArrowDown");
    const end = press(input, "End");
    expect(end.defaultPrevented).toBe(false);
    expect(active()).toBeNull();
    expect(document.activeElement).toBe(input);
    for (const key of ["ArrowLeft", "ArrowRight"]) {
      press(input, "ArrowDown");
      expect(press(input, key).defaultPrevented).toBe(false);
      expect(active()).toBeNull();
    }
  });

  it("Tab takes the option with the visual focus and lets the focus go on to the tier", () => {
    const { input, list, picker } = mount();
    type(input, "helm");
    press(input, "ArrowDown");
    const event = press(input, "Tab");
    expect(event.defaultPrevented).toBe(false);
    expect(input.value).toBe("Helm of the Stoneward");
    expect(list.hidden).toBe(true);
    expect(picker.selected()?.key).toBe("w90001");
  });

  it("leaves the keys it does not use alone, and keys pressed with Control or Meta", () => {
    const { input } = mount();
    type(input, "pauld");
    for (const init of [{ key: "a" }, { key: "ArrowDown", ctrlKey: true }, { key: "ArrowDown", metaKey: true }, { key: "Enter", ctrlKey: true }]) {
      expect(press(input, init.key, init).defaultPrevented, JSON.stringify(init)).toBe(false);
    }
    expect(active()).toBeNull();
  });

  it("a click on an option chooses it, and pressing the mouse button on the list does not take the focus from the text box", () => {
    const { input, list, picker } = mount();
    input.focus();
    type(input, "pauld");
    const down = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    options()[1].dispatchEvent(down);
    expect(down.defaultPrevented).toBe(true);
    options()[1].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(input.value).toBe("Larkspur Pauldrons");
    expect(list.hidden).toBe(true);
    expect(document.activeElement).toBe(input);
    expect(picker.selected()?.key).toBe("w8091");
  });

  it("closes when the focus leaves the text box", () => {
    const { input, list } = mount();
    input.focus();
    type(input, "pauld");
    expect(list.hidden).toBe(false);
    $("#upgrade-tier").focus();
    expect(list.hidden).toBe(true);
    expect(input.value).toBe("pauld");
  });
});

describe("adding", () => {
  it("adds the chosen item at the chosen tier, and leaves the text box empty with the focus in it, ready for the next", () => {
    const { input, added, picker } = mount();
    input.focus();
    type(input, "lark");
    press(input, "ArrowDown");
    press(input, "Enter");
    $("#upgrade-tier").value = "4";
    $("#upgrade-add").click();
    expect(added).toEqual([["w8091", 4]]);
    expect(input.value).toBe("");
    expect(picker.selected()).toBeNull();
    expect(document.activeElement).toBe(input);
  });

  it("offers the tiers +0 to +10 and starts at +0", () => {
    mount();
    const select = $("#upgrade-tier");
    expect($$("option", select).map((o) => [o.value, o.textContent])).toEqual(Array.from({ length: 11 }, (_, n) => [String(n), `+${n}`]));
    expect(select.value).toBe("0");
  });

  it("adds at +0 when the tier was not touched", () => {
    const { input, added } = mount();
    type(input, "helm");
    press(input, "ArrowDown");
    press(input, "Enter");
    $("#upgrade-add").click();
    expect(added).toEqual([["w90001", 0]]);
  });

  it("Enter with the list closed and an item chosen adds it, as the button does", () => {
    const { input, added } = mount();
    type(input, "helm");
    press(input, "ArrowDown");
    press(input, "Enter"); // chooses
    expect(added).toEqual([]);
    press(input, "Enter"); // adds
    expect(added).toEqual([["w90001", 0]]);
    expect(input.value).toBe("");
  });

  it("takes a name typed in full, in any case, when only one item has it", () => {
    const { input, added } = mount();
    type(input, "  steel CAP of valor ");
    $("#upgrade-add").click();
    expect(added).toEqual([["w90002", 0]]);
  });

  it("asks for a choice from the list when nothing is chosen or the text is no name, and adds nothing", () => {
    const { input, added, notes } = mount();
    $("#upgrade-add").click();
    type(input, "pauld");
    $("#upgrade-add").click();
    type(input, "zzz");
    $("#upgrade-add").click();
    expect(added).toEqual([]);
    expect(notes).toEqual(Array(3).fill("Choose an item from the list first."));
  });

  it("forgets the choice when the text is changed afterwards", () => {
    const { input, added, notes, picker } = mount();
    type(input, "helm");
    press(input, "ArrowDown");
    press(input, "Enter");
    expect(picker.selected()).not.toBeNull();
    type(input, "helm of the stonewardX");
    expect(picker.selected()).toBeNull();
    $("#upgrade-add").click();
    expect(added).toEqual([]);
    expect(notes).toEqual(["Choose an item from the list first."]);
  });

  it("keeps what was typed when the host refuses the item (a full list, say)", () => {
    const { input, picker } = mount(ENTRIES, { onAdd: () => false });
    type(input, "helm");
    press(input, "ArrowDown");
    press(input, "Enter");
    $("#upgrade-add").click();
    expect(input.value).toBe("Helm of the Stoneward");
    expect(picker.selected()?.key).toBe("w90001");
  });

  it("a name that two items have must be chosen from the list", () => {
    const twins = [entry("w1", "Tarn Signet", "Finger"), entry("w2", "Tarn Signet", "Finger"), entry("w3", "Tarn Hoop", "Ear")];
    const { input, added, notes } = mount(twins);
    type(input, "tarn signet");
    $("#upgrade-add").click();
    expect(added).toEqual([]);
    expect(notes).toEqual(["Choose an item from the list first."]);
    expect(optionNames()).toEqual(["Tarn Signet", "Tarn Signet"]);
    press(input, "ArrowDown");
    press(input, "ArrowDown");
    press(input, "Enter");
    $("#upgrade-add").click();
    expect(added).toEqual([["w2", 0]]);
  });
});

describe("the entries", () => {
  it("are replaced when the item list arrives, and the list in view is made again from the text that is typed", () => {
    const { input, picker, list } = mount([]);
    input.focus();
    type(input, "helm");
    expect(list.hidden).toBe(true);
    picker.setEntries(ENTRIES);
    expect(list.hidden).toBe(false);
    expect(optionNames()).toEqual(["Helm of the Stoneward"]);
  });

  it("do not open a list for a text box that has no focus when the item list arrives", () => {
    const { picker, list } = mount([]);
    type($("#upgrade-pick"), "helm");
    $("#upgrade-pick").blur();
    picker.setEntries(ENTRIES);
    expect(list.hidden).toBe(true);
  });

  it("are not touched by the picker: it reads them and keeps its own index", () => {
    const entries = ENTRIES.slice();
    const frozen = entries.map((e) => Object.freeze({ ...e }));
    const { input } = mount(frozen);
    type(input, "pauld");
    expect(optionNames()).toHaveLength(2);
    expect(entries).toEqual(ENTRIES);
  });
});

describe("taking it down", () => {
  it("destroy() stops the controls from answering", () => {
    const { input, picker, list } = mount();
    picker.destroy();
    type(input, "pauld");
    expect(list.hidden).toBe(true);
    expect(press(input, "ArrowDown").defaultPrevented).toBe(false);
  });

  it("destroy() takes back the count that was about to be said", () => {
    vi.useFakeTimers();
    try {
      const said = [];
      const { input, picker } = mount(ENTRIES, { onMatches: (text) => said.push(text) });
      type(input, "pauld");
      picker.destroy();
      vi.advanceTimersByTime(5000);
      expect(said).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });
});

// ---- quotation marks ---------------------------------------------------------------------------------------------------------------------

describe("quotation marks", () => {
  // the game writes many names with a backtick and the wiki with an apostrophe, and the smart punctuation of a phone turns a typed ' into U+2019
  const MARKED = [entry("w1", "Quillon`s Thimble", "Hands"), entry("w2", "Marrow's Lantern", "Charm"), entry("w3", "Plain Spoon", "Primary")];
  const MARKS = ["'", "`", "’"];
  const index = buildIndex(MARKED);

  it.each(MARKS)("a query with %s finds a name written with a backtick and one written with an apostrophe", (mark) => {
    expect(names(index.search(`quillon${mark}s thimble`))).toEqual(["Quillon`s Thimble"]);
    expect(names(index.search(`marrow${mark}s lantern`))).toEqual(["Marrow's Lantern"]);
    expect(names(index.search(`quillon${mark}s`))).toEqual(["Quillon`s Thimble"]); // the beginning of a name
    expect(names(index.search(`thimble quillon${mark}s`))).toEqual(["Quillon`s Thimble"]); // parts of a name in any order
    expect(names(index.search(`lantern marrow${mark}s`))).toEqual(["Marrow's Lantern"]);
  });

  it("folds every mark that the matcher of the dump folds, in the names and in the query", () => {
    for (const code of [0x60, 0x27, 0x2018, 0x2019, 0x201b, 0x2032, 0xb4, 0xfffd]) {
      const mark = String.fromCharCode(code);
      expect(names(index.search(`marrow${mark}s lantern`)), code.toString(16)).toEqual(["Marrow's Lantern"]);
      const written = buildIndex([entry("w9", `Fennel${mark}s Brooch`, "Neck")]);
      expect(names(written.search("fennel's brooch")), code.toString(16)).toEqual([`Fennel${mark}s Brooch`]);
      expect(written.exact("FENNEL`S  brooch")).toHaveLength(1);
    }
  });

  it("shows the name as the table writes it", () => {
    const { input } = mount(MARKED);
    type(input, "quillon’s");
    expect(optionNames()).toEqual(["Quillon`s Thimble"]);
  });

  it.each(MARKS)("takes a name typed in full with %s as the name of the item: exact() and Add", (mark) => {
    expect(names(index.exact(`QUILLON${mark}S  Thimble`))).toEqual(["Quillon`s Thimble"]);
    const { input, added, notes } = mount(MARKED);
    type(input, `Marrow${mark}s Lantern`);
    $("#upgrade-add").click();
    expect(notes, "no 'choose an item from the list first'").toEqual([]);
    expect(added).toEqual([["w2", 0]]);
    expect(input.value).toBe("");
  });

  it("still finds a name by the parts of it that have no mark, and a mark is no part of a word", () => {
    expect(names(index.search("quillon thimble"))).toEqual(["Quillon`s Thimble"]);
    expect(names(index.search("marrow lantern"))).toEqual(["Marrow's Lantern"]);
    expect(index.search("quillon marrow")).toEqual([]);
  });
});

// ---- how many items match ----------------------------------------------------------------------------------------------------------------

describe("how many items match what is typed", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  function setup(entries = ENTRIES) {
    vi.useFakeTimers();
    const said = [];
    return { ...mount(entries, { onMatches: (text) => said.push(text) }), said };
  }

  it("is said once the visitor has paused for half a second, and not for each key", () => {
    const { input, said } = setup();
    for (const text of ["p", "pa", "pau", "paul", "pauld"]) {
      type(input, text);
      vi.advanceTimersByTime(100);
    }
    expect(said, "while the visitor types").toEqual([]);
    vi.advanceTimersByTime(399);
    expect(said).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(said).toEqual(["2 items match"]);
    vi.advanceTimersByTime(5000);
    expect(said, "once").toEqual(["2 items match"]);
  });

  it("says 'No item matches' for a text that nothing fits, and the singular for one item", () => {
    const { input, said } = setup();
    type(input, "zzz");
    vi.advanceTimersByTime(500);
    type(input, "helm");
    vi.advanceTimersByTime(500);
    expect(said).toEqual(["No item matches", "1 item matches"]);
  });

  it("says how many there are in all when the list shows the first twenty only", () => {
    const many = Array.from({ length: 60 }, (_, i) => entry(`w${70000 + i}`, `Amber Ring ${String(i).padStart(2, "0")}`, "Finger"));
    const { input, said } = setup(many);
    type(input, "amber");
    vi.advanceTimersByTime(500);
    expect(said).toEqual(["60 items match, showing the first 20"]);
    expect(options()).toHaveLength(20);
    type(input, "amber ring 0");
    vi.advanceTimersByTime(500);
    expect(said.at(-1)).toBe("10 items match");
  });

  it("counts what the search finds: the names that begin with the text and those that have it as the beginnings of words", () => {
    const { input, said } = setup();
    type(input, "the");
    vi.advanceTimersByTime(500);
    expect(said).toEqual(["3 items match"]); // Pauldrons of the Vanguard, Helm of the Stoneward, Bracer of the Iron Oath
    expect(optionNames()).toHaveLength(3);
  });

  it("says nothing for an empty text box, and nothing for a text that the visitor chose from the list, cleared or left meanwhile", () => {
    const { input, said } = setup();
    type(input, "pauld");
    type(input, "");
    vi.advanceTimersByTime(1000);
    type(input, "pauld");
    press(input, "ArrowDown");
    press(input, "Enter"); // chosen
    vi.advanceTimersByTime(1000);
    type(input, "helm");
    press(input, "Escape"); // the list is closed
    vi.advanceTimersByTime(1000);
    type(input, "stone");
    input.dispatchEvent(new FocusEvent("blur")); // left
    vi.advanceTimersByTime(1000);
    expect(said).toEqual([]);
  });

  it("is not said for the arrow keys that open the list, which only move around in it", () => {
    const { input, said } = setup();
    press(input, "ArrowDown");
    press(input, "ArrowDown");
    vi.advanceTimersByTime(2000);
    expect(said).toEqual([]);
  });

  it("is said from the text that is in the box when the pause is over, not from the text of the key that began it", () => {
    const { input, said } = setup();
    type(input, "pauld");
    vi.advanceTimersByTime(300);
    type(input, "stone");
    vi.advanceTimersByTime(500);
    expect(said).toEqual(["1 item matches"]);
  });
});

// ---- an input method editor --------------------------------------------------------------------------------------------------------------

describe("an input method editor", () => {
  const KEYS = ["ArrowDown", "ArrowUp", "Enter", "Escape", "Tab", "Home"];

  it.each([
    ["isComposing", { isComposing: true }],
    ["the legacy key code 229 of a key that an editor has taken", { keyCode: 229 }],
  ])("is left alone while it composes (%s): the keys that choose, move and close belong to the composition", (_, init) => {
    const { input, added } = mount();
    type(input, "pauld");
    expect(options()).toHaveLength(2);
    for (const key of KEYS) {
      const event = press(input, key, init);
      expect(event.defaultPrevented, key).toBe(false);
      expect(options(), `${key} leaves the list as it was`).toHaveLength(2);
      expect(active(), key).toBeNull();
      expect(input.getAttribute("aria-expanded"), key).toBe("true");
    }
    expect(input.value).toBe("pauld");
    expect(added).toEqual([]);
  });

  it("acts on the same keys as before once the composition is over", () => {
    const { input } = mount();
    type(input, "pauld");
    press(input, "ArrowDown", { isComposing: true });
    expect(active()).toBeNull();
    press(input, "ArrowDown", { isComposing: false, keyCode: 40 });
    expect(active()).not.toBeNull();
  });
});

// ---- how many items match, when an arrow key asks for a list that is empty -------------------------------------------------------------------------

describe("how many items match, when an arrow key asks for a list that is empty", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  function setup() {
    vi.useFakeTimers();
    const said = [];
    return { ...mount(ENTRIES, { onMatches: (text) => said.push(text) }), said };
  }

  it.each(["ArrowDown", "ArrowUp"])("%s on a text that nothing fits says so at once, and the pause does not say it again", (key) => {
    const { input, said, list } = setup();
    type(input, "zzz");
    vi.advanceTimersByTime(100);
    expect(press(input, key).defaultPrevented).toBe(true);
    expect(said).toEqual(["No item matches"]);
    expect(list.hidden).toBe(true);
    vi.advanceTimersByTime(5000);
    expect(said).toEqual(["No item matches"]);
  });

  it("does not cancel the count when the key finds options to move in: it is said after the pause, once", () => {
    const { input, said } = setup();
    type(input, "pauld");
    press(input, "ArrowDown");
    press(input, "ArrowDown");
    expect(said).toEqual([]);
    vi.advanceTimersByTime(500);
    expect(said).toEqual(["2 items match"]);
  });

  it("says nothing for an arrow key on an empty box, which opens the whole list", () => {
    const { input, said } = setup();
    press(input, "ArrowDown");
    vi.advanceTimersByTime(5000);
    expect(said).toEqual([]);
    expect(options().length).toBeGreaterThan(0);
  });
});
