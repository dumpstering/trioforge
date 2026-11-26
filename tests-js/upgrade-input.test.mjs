// @vitest-environment jsdom
//
// The input of the Upgrade section: the gear a visitor has, read from the file that /outputfile inventory writes or added by name, as a list of what is owned at which tier,
// how many, and where. `createGearInput(root, {items, trio, doc, win})` works on the section the generator writes into the trio page (the contract copy of it) and on the item table
// (readItemTable's result). The dumps are made from the invented items of the site fixture (fixtures/dumps/site-*.txt); the tables of the tests that need a name two items
// share are made here, with invented names too.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LIMITS as DUMP, ERRORS, parseDump } from "../pipeline/trioforge/site/static/input/dump.js";
import { LIMITS, validateRequest } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { createGearInput } from "../pipeline/trioforge/site/static/ui/upgrade-input.js";
import { crlf, dump, empty, keyRow, row } from "./dump-helpers.mjs";
import { $, $$, STATIC, choose, drop, dumpText, mountPage, press, record, siteTable, tableOf, type, wake } from "./upgrade-helpers.mjs";

// the parser never rejects, so a test that wants a read to reject makes it (once) through this wrapper, which otherwise is the parser
vi.mock("../pipeline/trioforge/site/static/input/dump.js", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, parseDump: vi.fn((...args) => actual.parseDump(...args)) };
});

/** Wait for something that happens after a read or a download, with room for a busy machine. */
const waitFor = (check) => vi.waitFor(check, { timeout: 5000, interval: 20 });
const TRIO = ["PAL", "MNK", "BER"];
const SECRET = "ZQ-secret-name-7731";
const file = (text, name = `${SECRET}.txt`) => new File([text], name);
const siteFile = (name) => file(dumpText(name));

/** The section with the controls awake, a live region for the announcements, and the gear input made on a table (the fixture's by default). */
function mount({ table = siteTable(), trio = TRIO, announce } = {}) {
  const root = mountPage('<p id="announce" class="sr-only" role="status" aria-live="polite"></p>');
  wake(root);
  const said = [];
  const options = { items: table, trio, doc: document, win: window };
  if (announce !== false) options.announce = (text) => said.push(text);
  const gear = createGearInput(root, options);
  return { root, gear, said };
}

/** Add an item by name the way a visitor does: type, choose the first option with the keys, pick the tier, press Add. */
function addByName(name, tier = "0") {
  const input = $("#upgrade-pick");
  type(input, name);
  press(input, "ArrowDown");
  press(input, "Enter");
  $("#upgrade-tier").value = tier;
  $("#upgrade-add").click();
}

const rows = () => $$("#upgrade-owned > li");
const rowOf = (li) => ({
  ident: li.dataset.ident,
  name: li.querySelector(".owned-name").textContent,
  tier: li.querySelector(".owned-tier").textContent,
  count: li.querySelector(".owned-count")?.textContent ?? null,
  where: li.querySelector(".owned-where").textContent,
});
const note = () => $("#upgrade-note");
const noteText = () => (note().hidden ? "" : note().textContent);
const banner = () => $("#upgrade-banner");
const place = (location, count = 1) => ({ location, count });

/** What the site dump gives, by the order of the names: the key, the tier, the count and where each is. */
const SITE_SMALL = [
  { key: "w80631", tier: 4, count: 1, locations: [place("worn")] }, // Band of Quiet Lanterns
  { key: "w90020", tier: 0, count: 1, locations: [place("worn")] }, // Bracer of the Iron Oath
  { key: "w90029", tier: 4, count: 1, locations: [place("worn")] }, // Breastplate of Warding
  { key: "w90011", tier: 0, count: 1, locations: [place("worn")] }, // Choker of the Deep
  { key: "w90023", tier: 1, count: 1, locations: [place("sharedbank")] }, // Gauntlets of Endless Wrath
  { key: "w90001", tier: 4, count: 2, locations: [place("worn"), place("bank")] }, // Helm of the Stoneward, worn and a spare in the bank
  { key: "w8091", tier: 4, count: 1, locations: [place("bag")] }, // Larkspur Pauldrons
  { key: "w90006", tier: 0, count: 1, locations: [place("keyring")] }, // Mask of the Weary
  { key: "w80113", tier: 3, count: 1, locations: [place("worn")] }, // Pellbrook Mallet
  { key: "w90007", tier: 2, count: 2, locations: [place("worn", 2)] }, // Rune-etched Earring, one in each ear
  { key: "w80923", tier: 0, count: 1, locations: [place("bag")] }, // Tinker's Awl
  { key: "w90014", tier: 1, count: 1, locations: [place("worn")] }, // Vambraces of Might
];

// two items that share the name a dump row has: the match name "Tarn Signet" (the second is "Tarn Signet (Marsh)" on its page)
const TWINS = [
  record(80301, "Tarn Signet", { stats: { STR: 7, ATK: 9 } }),
  record(80302, "Tarn Signet (Marsh)", { match_name: "Tarn Signet", stats: { HP: 60, STA: 8 } }),
  record(80303, "Quillmark Bracer", { slots: ["WRIST"], stats: { AC: 10 } }),
];
const twinsDump = (extra = []) =>
  dump(
    [
      empty("Any Slot"),
      row("Fingers", "Tarn Signet +2", 610001),
      row("Fingers", "Quillmark Bracer", 610003),
      row("General 1", "Wicker Basket", 610100, 1, 2),
      row("General 1-Slot1", "Tarn Signet +2", 610001),
      empty("General 1-Slot2"),
      ...extra,
    ],
    [],
  );

// ---- the controls the gear input finds and wakes ------------------------------------------------------------------------------------------------

describe("the section", () => {
  it("has its controls and, for a browser without script, the note that it needs JavaScript", () => {
    const root = mountPage();
    for (const id of ["upgrade-file", "upgrade-drop", "upgrade-pick", "upgrade-list", "upgrade-tier", "upgrade-add", "upgrade-owned", "upgrade-owned-h", "upgrade-clear"]) {
      expect(document.getElementById(id), id).not.toBeNull();
    }
    expect(root.querySelector("noscript").textContent).toContain("needs JavaScript");
    expect(root.textContent).toMatch(/read in this browser and is never uploaded/);
    expect($("#upgrade-add").disabled).toBe(true); // until there is an item list to add from
  });

  it("enables Add once the item list is in, and shows an empty list of the gear", () => {
    mount();
    expect($("#upgrade-add").disabled).toBe(false);
    expect(rows()).toHaveLength(0);
    expect($("#upgrade-empty").hidden).toBe(false);
    expect($("#upgrade-clear").hidden).toBe(true);
    expect($("#upgrade-count").textContent).toBe("");
  });
});

// ---- the dump -------------------------------------------------------------------------------------------------------------------------------------

describe("a dump of the site fixture", () => {
  it("fills the list with the right keys, tiers, counts and locations", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-small"));
    expect(gear.owned()).toEqual(SITE_SMALL);
  });

  it("shows each row with its name, tier, count and where it is, and a way to remove it", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-small"));
    const shown = rows().map(rowOf);
    expect(shown).toHaveLength(12);
    expect(shown[0]).toEqual({ ident: "w80631@4", name: "Band of Quiet Lanterns", tier: "+4", count: null, where: "worn" });
    expect(shown[5]).toEqual({ ident: "w90001@4", name: "Helm of the Stoneward", tier: "+4", count: "2 copies", where: "worn, in the bank" });
    expect(shown[6].where).toBe("in a bag");
    expect(shown[4].where).toBe("in the shared bank");
    expect(shown[7].where).toBe("on the key ring");
    expect(shown[9]).toEqual({ ident: "w90007@2", name: "Rune-etched Earring", tier: "+2", count: "2 copies", where: "worn ×2" });
    const remove = rows()[5].querySelector("button");
    expect(remove.textContent).toBe("Remove");
    expect(remove.getAttribute("aria-label")).toBe("Remove Helm of the Stoneward +4");
    expect($("#upgrade-count").textContent).toBe("(12)");
    expect($("#upgrade-empty").hidden).toBe(true);
    expect($("#upgrade-clear").hidden).toBe(false);
    expect($("#upgrade-owned").getAttribute("aria-labelledby")).toBe("upgrade-owned-h");
  });

  it("reads the same through the file input and through a drop on the drop zone", async () => {
    const viaInput = mount();
    choose($("#upgrade-file"), [siteFile("site-small")]);
    await waitFor(() => expect(viaInput.gear.owned()).toEqual(SITE_SMALL));
    const viaDrop = mount();
    const event = drop($("#upgrade-drop"), [siteFile("site-small")]);
    expect(event.defaultPrevented).toBe(true); // the browser would otherwise open the file instead of the page
    await waitFor(() => expect(viaDrop.gear.owned()).toEqual(SITE_SMALL));
  });

  it("takes a drop anywhere on the section, and leaves a drag of anything but files alone", async () => {
    const { gear, root } = mount();
    const text = drop(root, [], { types: ["text/plain"] });
    expect(text.defaultPrevented).toBe(false);
    for (const type of ["dragenter", "dragover"]) expect(drop($("#upgrade-pick"), [], { types: ["Files"], type }).defaultPrevented).toBe(true);
    drop($("#upgrade-pick"), [siteFile("site-small")]);
    await waitFor(() => expect(gear.owned()).toHaveLength(12));
  });

  it("marks the drop zone while files are over it, and not after they leave or drop", () => {
    mount();
    const zone = $("#upgrade-drop");
    drop(zone, [], { type: "dragenter" });
    expect(zone.classList.contains("is-over")).toBe(true);
    drop(zone, [], { type: "dragleave" });
    expect(zone.classList.contains("is-over")).toBe(false);
    drop(zone, [], { type: "dragenter" });
    drop(zone, [], { type: "dragenter" });
    drop(zone, [], { type: "dragleave" });
    expect(zone.classList.contains("is-over")).toBe(true); // it entered a child, then left it, and is over the zone still
    drop(zone, [siteFile("site-small")]);
    expect(zone.classList.contains("is-over")).toBe(false);
  });

  it("empties the file input after a choice, so that the same file can be chosen again", async () => {
    const { gear } = mount();
    const input = $("#upgrade-file");
    const set = vi.fn();
    Object.defineProperty(input, "value", { get: () => "", set, configurable: true });
    choose(input, [siteFile("site-small")]);
    await waitFor(() => expect(gear.owned()).toHaveLength(12));
    expect(set).toHaveBeenCalledWith("");
  });

  it("replaces what an earlier file gave and keeps what was added by name", async () => {
    const { gear } = mount();
    addByName("crown of the vanguard", "3");
    await gear.readFile(siteFile("site-small"));
    expect(gear.owned()).toHaveLength(13);
    await gear.readFile(siteFile("site-mixed"));
    expect(gear.owned().map((e) => e.key)).toEqual(["w90029", "w90011", "w90003", "w90001", "w80923"]);
    expect(gear.owned().find((e) => e.key === "w90003")).toEqual({ key: "w90003", tier: 3, count: 1, locations: [] }); // the one added by name has no place
  });

  it("does not count a bag as an item that the catalog does not know", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-small"));
    expect($("#upgrade-unknown").textContent).not.toContain("Wicker Basket");
    expect($("#upgrade-unknown summary").textContent).toBe("Not in the catalog (1)");
    expect(gear.owned()).toHaveLength(12);
  });
});

// ---- what it says about a file it read --------------------------------------------------------------------------------------------------------

describe("what the visitor is told", () => {
  it("announces a read once, in the page's live region: how many items, how many need a choice, how many are not in the catalog", async () => {
    const { gear, said } = mount();
    await gear.readFile(siteFile("site-small"));
    expect(said).toEqual(["12 items read, 1 not in the catalog."]);
    await gear.readFile(siteFile("site-mixed"));
    expect(said.at(-1)).toBe("4 items read, 2 need a choice, 3 not in the catalog.");
    expect(said).toHaveLength(2); // one for each file, not one for each row
  });

  it("uses the live region of the page when it is given no function of its own", async () => {
    const { gear } = mount({ announce: false });
    await gear.readFile(siteFile("site-small"));
    expect($("#announce").textContent).toBe("12 items read, 1 not in the catalog.");
  });

  it("shows a banner that does not stand in the way: a plain element that says how many items need a choice and how many are not in the catalog", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-mixed"));
    expect(banner().hidden).toBe(false);
    expect(banner().hasAttribute("role")).toBe(false); // the page has two live regions, #status and #announce: this is not a third
    expect(banner().hasAttribute("aria-live")).toBe(false);
    expect($$('#upgrade [role="status"], #upgrade [role="alert"], #upgrade [role="log"], #upgrade [aria-live]')).toHaveLength(0);
    expect($("#upgrade-banner-text").textContent).toBe("2 items need a choice. 3 items are not in the catalog.");
    expect(gear.owned()).toHaveLength(4); // the rows that matched are in the list meanwhile
  });

  it("says it in the singular too, and has no banner when there is nothing to say", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-small"));
    expect($("#upgrade-banner-text").textContent).toBe("1 item is not in the catalog.");
    await gear.readFile(file(dump([row("Head", "Helm of the Stoneward +4", 1)], [])));
    expect(banner().hidden).toBe(true);
    expect($("#upgrade-banner-text").textContent).toBe("");
  });

  it("lists what is not in the catalog, as text, and does not score it", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-mixed"));
    const names = $$("#upgrade-unknown li").map((li) => li.textContent);
    expect(names).toEqual(["Tin Flask ×20", "Dented Thimble ×3", "Cracked Whistle"]);
    expect($("#upgrade-unknown summary").textContent).toBe("Not in the catalog (3)");
    expect(gear.owned().map((e) => e.key)).not.toContain("Tin Flask");
    expect(rows().map((li) => li.querySelector(".owned-name").textContent)).not.toContain("Tin Flask");
  });

  it("lists the notes of the parser about a file in an expander, in the parser's own words", async () => {
    const { gear } = mount();
    const cut = dumpText("site-small").split("\r\n\r\nKeyRing")[0] + "\r\n"; // no key ring section, and the rows stop before the last shared bank
    await gear.readFile(file(cut));
    const items = $$("#upgrade-warnings li").map((li) => li.textContent);
    expect(items).toEqual(["The file has no KeyRing section and its rows stop before SharedBank6, so the file may be cut off; re-run /outputfile inventory."]);
    expect($("#upgrade-warnings summary").textContent).toBe("Notes about the file (1)");
    expect($("#upgrade-warnings").hidden).toBe(false);
    await gear.readFile(siteFile("site-small"));
    expect($("#upgrade-warnings").hidden).toBe(true);
  });

  it("marks an item that no class of the trio can wear, and still keeps it", async () => {
    const { gear } = mount();
    await gear.readFile(file(dump([row("Head", "Cap of the Archmage", 1), row("Neck", "Choker of the Deep", 2)], [])));
    const [archmage] = rows().filter((li) => li.dataset.ident === "w90040@0");
    expect(archmage.querySelector(".owned-note").textContent).toBe("not for this trio's classes");
    expect(rows().filter((li) => li.querySelector(".owned-note"))).toHaveLength(1);
    expect(gear.owned().map((e) => e.key).sort()).toEqual(["w90011", "w90040"]);
  });
});

// ---- the errors of the parser ---------------------------------------------------------------------------------------------------------------------

describe("a file the parser refuses", () => {
  const cutOff = dumpText("site-small").slice(0, 400).replace(/\r\n[^\r\n]*$/, "") + "\r\nHead\tHelm of the"; // ends in the middle of a row

  it.each([
    ["one that looks cut off", cutOff, ERRORS.cutOff],
    ["an empty one", "", ERRORS.empty],
    ["one that is no dump", "Hello\r\nWorld\r\n", ERRORS.notADump],
    ["one that holds no inventory row", crlf(["Location\tName\tID\tCount\tSlots", ""]), ERRORS.noRows],
  ])("says what the parser says of %s, and nothing of the file", async (_, text, message) => {
    const { gear, said } = mount();
    await gear.readFile(file(text));
    expect(noteText()).toBe(message);
    expect(said).toEqual([message]);
    expect(gear.owned()).toEqual([]);
  });

  it("says what the parser says of a file over 1 MiB, without reading it", async () => {
    const { gear } = mount();
    await gear.readFile(new File([new Uint8Array(DUMP.maxBytes + 1)], `${SECRET}.txt`));
    expect(noteText()).toBe(ERRORS.tooLarge);
  });

  it("keeps what an earlier file gave when a later file is refused, and takes the note away at the next good file", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-small"));
    await gear.readFile(file("not a dump"));
    expect(noteText()).toBe(ERRORS.notADump);
    expect(gear.owned()).toEqual(SITE_SMALL);
    await gear.readFile(siteFile("site-small"));
    expect(noteText()).toBe("");
    expect(note().hidden).toBe(true);
  });

  it("does not take more than one file at a time", async () => {
    const { gear, said } = mount();
    drop($("#upgrade-drop"), [siteFile("site-small"), siteFile("site-mixed")]);
    await Promise.resolve();
    expect(noteText()).toBe("Drop one file at a time.");
    expect(said).toEqual(["Drop one file at a time."]);
    expect(gear.owned()).toEqual([]);
    choose($("#upgrade-file"), []);
    drop($("#upgrade-drop"), []); // nothing to read in a drop of no files
    expect(gear.owned()).toEqual([]);
  });
});

// ---- the file name ----------------------------------------------------------------------------------------------------------------------------------

describe("the name of the file", () => {
  it("is never looked at, shown, announced or kept, whether the file is read or refused", async () => {
    const { gear, said } = mount();
    let touched = false;
    const guarded = (text) => {
      const f = file(text);
      Object.defineProperty(f, "name", { get() { touched = true; return SECRET; } });
      return f;
    };
    await gear.readFile(guarded(dumpText("site-small")));
    await gear.readFile(guarded(dumpText("site-mixed")));
    await gear.readFile(guarded("not a dump"));
    choose($("#upgrade-file"), [guarded(dumpText("site-small"))]);
    await waitFor(() => expect(said.length).toBe(4));
    drop($("#upgrade-drop"), [guarded(dumpText("site-small"))]);
    await waitFor(() => expect(said.length).toBe(5));
    expect(touched).toBe(false);
    expect(document.documentElement.outerHTML).not.toContain("ZQ-secret");
    expect(said.join("\n")).not.toContain("ZQ-secret");
    expect($("#upgrade-file").value).toBe("");
  });
});

// ---- what needs a choice -----------------------------------------------------------------------------------------------------------------------------

describe("a row that more than one item could be", () => {
  it("is left out of the list, listed with a Choose control for each item it could be, and does not hold up the rest", async () => {
    const { gear, said } = mount({ table: tableOf([...TWINS]) });
    await gear.readFile(file(twinsDump()));
    expect(gear.owned()).toEqual([{ key: "w80303", tier: 0, count: 1, locations: [place("worn")] }]); // the one that matched is in
    expect(said).toEqual(["1 item read, 1 needs a choice."]);
    expect($("#upgrade-banner-text").textContent).toBe("1 item needs a choice.");
    const groups = $$("#upgrade-banner .choice");
    expect(groups).toHaveLength(1); // the two rows are one item: the same name and the same ID in the file
    expect(groups[0].querySelector(".choice-name").textContent).toBe('"Tarn Signet" could be one of 2 items:');
    const options = $$(".choice-options li", groups[0]);
    expect(options.map((li) => li.querySelector(".choice-desc").textContent)).toEqual([
      "Tarn Signet · Finger · ATK 9, STR 7 · w80301",
      "Tarn Signet (Marsh) · Finger · HP 60, STA 8 · w80302",
    ]);
    for (const li of options) {
      const button = li.querySelector("button");
      expect(button.textContent).toBe("Choose");
      const names = button.getAttribute("aria-labelledby").split(" ").map((id) => document.getElementById(id).textContent);
      expect(names[0]).toBe("Choose"); // the name of the button starts with the words on it, and goes on with what it chooses
      expect(names[1]).toContain(li.querySelector(".choice-desc").textContent);
    }
  });

  it("is added when one of the items is chosen: with the tier, the count and the places of every row it stands for", async () => {
    const { gear, said } = mount({ table: tableOf([...TWINS]) });
    await gear.readFile(file(twinsDump()));
    $$(".choice-options button")[1].click();
    expect(gear.owned()).toEqual([
      { key: "w80303", tier: 0, count: 1, locations: [place("worn")] },
      { key: "w80302", tier: 2, count: 2, locations: [place("worn"), place("bag")] },
    ]);
    expect(banner().hidden).toBe(true);
    expect(said.at(-1)).toBe("Chose Tarn Signet (Marsh).");
    expect(rows().map(rowOf).at(-1)).toEqual({ ident: "w80302@2", name: "Tarn Signet (Marsh)", tier: "+2", count: "2 copies", where: "worn, in a bag" });
  });

  it("moves the focus to the next choice, or to the list when there is none left", async () => {
    const { gear } = mount({ table: tableOf([...TWINS, record(80304, "Dusk Loop", { match_name: "Quillmark Bracer" })]) });
    await gear.readFile(file(twinsDump()));
    expect($$("#upgrade-banner .choice")).toHaveLength(2); // Tarn Signet and Quillmark Bracer
    const first = $$(".choice-options button")[0];
    first.focus();
    first.click();
    expect(document.activeElement.textContent).toBe("Choose");
    expect(document.activeElement.closest(".choice")).toBe($$("#upgrade-banner .choice")[0]);
    document.activeElement.click();
    expect(banner().hidden).toBe(true);
    expect(document.activeElement).toBe($("#upgrade-owned-h"));
    expect(gear.owned()).toHaveLength(2);
  });

  it("goes back to needing a choice when the row it was chosen for is removed", async () => {
    const { gear } = mount({ table: tableOf([...TWINS]) });
    await gear.readFile(file(twinsDump()));
    $$(".choice-options button")[0].click();
    expect(gear.owned().map((e) => e.key)).toContain("w80301");
    rows().find((li) => li.dataset.ident === "w80301@2").querySelector("button").click();
    expect(gear.owned().map((e) => e.key)).toEqual(["w80303"]);
    expect($("#upgrade-banner-text").textContent).toBe("1 item needs a choice.");
  });

  it("comes back when the same choice is made again after the row was removed", async () => {
    const { gear } = mount({ table: tableOf([...TWINS]) });
    await gear.readFile(file(twinsDump()));
    $$(".choice-options button")[0].click();
    rows().find((li) => li.dataset.ident === "w80301@2").querySelector("button").click();
    expect(gear.owned().map((e) => e.key)).toEqual(["w80303"]);
    $$(".choice-options button")[0].click(); // the same one again
    expect(gear.owned().find((e) => e.key === "w80301")).toEqual({ key: "w80301", tier: 2, count: 2, locations: [place("worn"), place("bag")] });
    expect(banner().hidden).toBe(true);
  });

  it("offers a name that is close to an item's, and never picks it without the visitor (the site fixture)", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-mixed"));
    const groups = $$("#upgrade-banner .choice");
    expect(groups.map((g) => g.querySelector(".choice-name").textContent)).toEqual(['"Millrace pavise" is close to this item:', '"larkspur pauldrons" is close to this item:']);
    expect($$(".choice-desc", groups[0]).map((e) => e.textContent)).toEqual(["Millrace Pavise · Secondary · AC 19, STR 6 · w80869"]);
    expect(gear.owned().map((e) => e.key)).toEqual(["w90029", "w90011", "w90001", "w80923"]); // nothing of the two was added
    $$(".choice-options button").forEach((button) => button.click());
    expect(gear.owned().map((e) => e.key)).toEqual(["w90029", "w90011", "w90001", "w8091", "w80869", "w80923"]);
    expect(gear.owned().find((e) => e.key === "w8091")).toEqual({ key: "w8091", tier: 4, count: 1, locations: [place("bag")] });
  });

  it("is a group of its own for each ID in the file, so that two items that have a name can be told apart", async () => {
    const { gear } = mount({ table: tableOf([...TWINS]) });
    const text = dump([empty("Any Slot"), row("Fingers", "Tarn Signet", 610001), row("Fingers", "Tarn Signet", 610002)], []);
    await gear.readFile(file(text));
    expect($$("#upgrade-banner .choice")).toHaveLength(2);
    expect($("#upgrade-banner-text").textContent).toBe("2 items need a choice.");
    const buttons = $$(".choice-options button");
    buttons[0].click(); // the first ID is the first twin
    $$(".choice-options button")[1].click(); // the second ID: the second twin
    expect(gear.owned().map((e) => e.key)).toEqual(["w80301", "w80302"]);
  });

  it("shows at most 50 groups, says how many more there are, and picks none of them", async () => {
    const same = Array.from({ length: 120 }, (_, i) => row("Fingers", "Tarn Signet", 620000 + i));
    const { gear } = mount({ table: tableOf([...TWINS]) });
    const text = dump([empty("Any Slot"), ...same.slice(0, 2)], same.slice(2).map((r, i) => keyRow("Equipment", "Tarn Signet", 620002 + i)));
    await gear.readFile(file(text));
    expect($("#upgrade-banner-text").textContent).toBe("120 items need a choice.");
    expect($$("#upgrade-banner .choice")).toHaveLength(50);
    expect($("#upgrade-banner").textContent).toContain("70 more are not shown");
    expect(gear.owned()).toEqual([]);
  });

  it("shows at most 50 of the items a name could be, says how many more there are, and picks none of them", async () => {
    const ring = (count) => tableOf(Array.from({ length: count }, (_, i) => record(81000 + i, `Moss Ring ${i}`, { match_name: "Moss Ring" })));
    const text = dump([empty("Any Slot"), row("Fingers", "Moss Ring", 630001)], []);
    const { gear } = mount({ table: ring(60) });
    await gear.readFile(file(text));
    const group = $("#upgrade-banner .choice");
    expect($$("button", group)).toHaveLength(50);
    expect($(".choice-more", group).textContent).toBe("10 more are not shown.");
    expect(gear.owned()).toEqual([]);

    const one = mount({ table: ring(51) });
    await one.gear.readFile(file(text));
    expect($(".choice-more", $("#upgrade-banner .choice")).textContent).toBe("1 more is not shown.");

    const fifty = mount({ table: ring(50) });
    await fifty.gear.readFile(file(text));
    expect($$("button", $("#upgrade-banner .choice"))).toHaveLength(50);
    expect($(".choice-more", $("#upgrade-banner .choice")), "nothing is left out, nothing is said").toBeNull();
  });

  it("keeps the other rows of the item when one of them is removed, and asks for a choice again only when every row of it is gone", async () => {
    const { gear, said } = mount({ table: tableOf([...TWINS]) });
    await gear.readFile(file(dump([empty("Any Slot"), row("Fingers", "Tarn Signet +2", 610001), row("Bank1", "Tarn Signet +4", 610001)], [])));
    expect(gear.owned()).toEqual([]);
    $$(".choice-options button")[0].click(); // Tarn Signet: +2 worn and +4 in the bank
    expect(rows().map((li) => li.dataset.ident)).toEqual(["w80301@2", "w80301@4"]);

    rows()[0].querySelector("button").click(); // Remove the +2
    expect(rows().map((li) => li.dataset.ident), "the +4 row stays").toEqual(["w80301@4"]);
    expect(banner().hidden, "and nothing asks for a choice again").toBe(true);
    expect(said.at(-1), "so that is all that is said").toBe("Removed Tarn Signet +2.");
    expect(document.activeElement, "the focus goes to the row that takes its place, as for any row").toBe(rows()[0].querySelector("button"));
    expect(gear.owned()).toEqual([{ key: "w80301", tier: 4, count: 1, locations: [place("bank")] }]);

    rows()[0].querySelector("button").click(); // Remove the last row of the item
    expect(rows()).toHaveLength(0);
    expect(banner().hidden).toBe(false);
    expect($("#upgrade-banner-text").textContent).toBe("1 item needs a choice.");
    expect(said.at(-1), "the banner is not a live region: the choice that is asked for again is said through the page's").toBe("Removed Tarn Signet +4. 1 item needs a choice.");
    expect(document.activeElement, "no row is left: the heading").toBe($("#upgrade-owned-h"));

    $$(".choice-options button")[0].click(); // choosing again brings both back
    expect(rows().map((li) => li.dataset.ident)).toEqual(["w80301@2", "w80301@4"]);
  });

  it("keeps the choices when a file is read again, for the rows it still has, and Clear drops them", async () => {
    const { gear, said } = mount({ table: tableOf([...TWINS]) });
    await gear.readFile(file(twinsDump()));
    $$(".choice-options button")[1].click(); // Tarn Signet (Marsh)
    expect(gear.owned().map((e) => e.key)).toEqual(["w80303", "w80302"]);

    await gear.readFile(file(twinsDump())); // the same file again, say after a session in the game
    expect(banner().hidden, "nothing is asked again").toBe(true);
    expect(gear.owned().map((e) => e.key)).toEqual(["w80303", "w80302"]);
    expect(said.at(-1)).toBe("2 items read.");

    // a file with the same row and another item of the same name: the first is kept, the second is asked
    const more = dump([empty("Any Slot"), row("Fingers", "Tarn Signet +2", 610001), row("Fingers", "Tarn Signet +1", 610002)], []);
    await gear.readFile(file(more));
    expect($("#upgrade-banner-text").textContent).toBe("1 item needs a choice.");
    expect(gear.owned().map((e) => [e.key, e.tier])).toEqual([["w80302", 2]]);

    $("#upgrade-clear").click();
    await gear.readFile(file(twinsDump()));
    expect($("#upgrade-banner-text").textContent, "after Clear the choice is asked again").toBe("1 item needs a choice.");
    expect(gear.owned().map((e) => e.key)).toEqual(["w80303"]);
  });
});

// ---- the picker, in the list --------------------------------------------------------------------------------------------------------------------

describe("adding by name", () => {
  it("adds an item at the chosen tier, with no place", () => {
    const { gear, said } = mount();
    addByName("lark", "4");
    expect(gear.owned()).toEqual([{ key: "w8091", tier: 4, count: 1, locations: [] }]);
    expect(rows().map(rowOf)).toEqual([{ ident: "w8091@4", name: "Larkspur Pauldrons", tier: "+4", count: null, where: "added by hand" }]);
    expect(said).toEqual(["Added Larkspur Pauldrons +4."]);
  });

  it("adds the same item again to its count, and the same item at another tier as another row", () => {
    const { gear, said } = mount();
    addByName("lark", "4");
    addByName("lark", "4");
    addByName("lark", "6");
    expect(gear.owned()).toEqual([
      { key: "w8091", tier: 4, count: 2, locations: [] },
      { key: "w8091", tier: 6, count: 1, locations: [] },
    ]);
    expect(said).toEqual(["Added Larkspur Pauldrons +4.", "Added Larkspur Pauldrons +4, now 2 copies.", "Added Larkspur Pauldrons +6."]);
  });

  it("adds to what a file gave, and does not give a place to the copy that was added", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-small"));
    addByName("larkspur pauldrons", "4");
    expect(gear.owned().find((e) => e.key === "w8091")).toEqual({ key: "w8091", tier: 4, count: 2, locations: [place("bag")] });
  });

  it("offers only what a class of the trio can wear, hidden items too, and does not look at races or deities", () => {
    mount();
    const offered = (text) => {
      type($("#upgrade-pick"), text);
      return $$('#upgrade-list [role="option"] .li-name').map((n) => n.textContent);
    };
    expect(offered("cap of the arch")).toEqual([]); // a Wizard's cap
    expect(offered("relic")).toEqual(["Relic Helm of the Elders"]); // an item that only a player may own: hidden from the answers, not from the list
    expect(offered("sabatons")).toEqual(["Sabatons of Might"]); // for two races
    expect(offered("crown of the tri")).toEqual(["Crown of the Tribunal"]); // for one deity
    type($("#upgrade-pick"), "");
    press($("#upgrade-pick"), "ArrowDown");
    expect($$('#upgrade-list [role="option"]')).toHaveLength(20);
  });

  it("filters by the classes it is given", () => {
    mount({ trio: ["WIZ", "MNK", "BER"] });
    type($("#upgrade-pick"), "cap of the arch");
    expect($$('#upgrade-list [role="option"] .li-name').map((n) => n.textContent)).toEqual(["Cap of the Archmage"]);
  });

  it("writes a name as text, never as markup, in the list and in the options", () => {
    const { gear } = mount();
    addByName("<b>x</b>", "1");
    expect(gear.owned()).toHaveLength(1);
    expect($("#upgrade-owned b")).toBeNull();
    expect($("#upgrade-owned .owned-name").textContent).toBe("<b>x</b>");
    expect($("#upgrade-owned").innerHTML).toContain("&lt;b&gt;x&lt;/b&gt;");
    expect($("#upgrade-owned button").getAttribute("aria-label")).toBe("Remove <b>x</b> +1");
  });

  it("copes with names that are members of every object", () => {
    const names = ["constructor", "__proto__", "toString", "hasOwnProperty"];
    const table = tableOf(names.map((name, i) => record(81000 + i, name)));
    const { gear } = mount({ table });
    for (const name of names) addByName(name);
    expect(gear.owned().map((e) => e.key)).toEqual(["w81001", "w81000", "w81003", "w81002"]); // by name: __proto__, constructor, hasOwnProperty, toString
    expect(rows().map((li) => li.querySelector(".owned-name").textContent)).toEqual(["__proto__", "constructor", "hasOwnProperty", "toString"]);
    expect({}.polluted).toBeUndefined();
  });

  it("does not add more than the protocol takes of one item at one tier, and says so", () => {
    const { gear, said } = mount();
    for (let i = 0; i < LIMITS.maxOwnedCount; i += 1) addByName("lark", "4");
    expect(gear.owned()[0].count).toBe(LIMITS.maxOwnedCount);
    addByName("lark", "4");
    expect(gear.owned()[0].count).toBe(LIMITS.maxOwnedCount);
    expect(noteText()).toBe("You can have at most 99 copies of one item at one tier.");
    expect(said.at(-1)).toBe(noteText());
    expect($("#upgrade-pick").value).toBe("Larkspur Pauldrons"); // what was typed is kept
  });
});

// ---- removing and clearing -------------------------------------------------------------------------------------------------------------------------

describe("taking things out", () => {
  it("removes a row, and the focus stays in the list: on the Remove button of the row that takes its place", async () => {
    const { gear, said } = mount();
    await gear.readFile(siteFile("site-small"));
    const third = rows()[2].querySelector("button");
    third.focus();
    third.click();
    expect(gear.owned()).toHaveLength(11);
    expect(gear.owned().map((e) => e.key)).not.toContain("w90029");
    expect(document.activeElement.tagName).toBe("BUTTON");
    expect(document.activeElement.getAttribute("aria-label")).toBe("Remove Choker of the Deep +0"); // the next row has the place now
    expect(said.at(-1)).toBe("Removed Breastplate of Warding +4.");
  });

  it("puts the focus on the row before when the last row is removed, and on the heading when no row is left", async () => {
    const { gear } = mount();
    await gear.readFile(file(dump([row("Head", "Helm of the Stoneward +4", 1), row("Neck", "Choker of the Deep", 2)], [])));
    const last = rows()[1].querySelector("button");
    last.focus();
    last.click();
    expect(document.activeElement).toBe(rows()[0].querySelector("button"));
    rows()[0].querySelector("button").click();
    expect(gear.owned()).toEqual([]);
    expect(document.activeElement).toBe($("#upgrade-owned-h"));
    expect($("#upgrade-empty").hidden).toBe(false);
  });

  it("keeps a removed row out when the choices are made afterwards, and when the same row is added by name", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-mixed"));
    rows().find((li) => li.dataset.ident === "w90001@4").querySelector("button").click();
    $$(".choice-options button")[0].click();
    expect(gear.owned().map((e) => e.key)).not.toContain("w90001");
    type($("#upgrade-pick"), "helm of the stoneward");
    $("#upgrade-add").click();
    expect(gear.owned().find((e) => e.key === "w90001")).toEqual({ key: "w90001", tier: 0, count: 1, locations: [] });
  });

  it("Clear empties the section: the list, the choices, what is not in the catalog, the notes", async () => {
    const { gear, said } = mount();
    await gear.readFile(siteFile("site-mixed"));
    addByName("lark", "4");
    await gear.readFile(file("not a dump"));
    expect(noteText()).not.toBe("");
    $("#upgrade-clear").click();
    expect(gear.owned()).toEqual([]);
    expect(gear.toOwnedPairs()).toEqual([]);
    expect(rows()).toHaveLength(0);
    expect(banner().hidden).toBe(true);
    expect(note().hidden).toBe(true);
    expect($("#upgrade-warnings").hidden).toBe(true);
    expect($("#upgrade-empty").hidden).toBe(false);
    expect($("#upgrade-clear").hidden).toBe(true);
    expect($("#upgrade-pick").value).toBe("");
    expect(document.activeElement).toBe($("#upgrade-owned-h"));
    expect(said.at(-1)).toBe("Cleared your gear.");
  });
});

// ---- the interface for the answers -------------------------------------------------------------------------------------------------------------------

describe("what the answers read", () => {
  it("owned() gives copies, so that what a caller does with them changes nothing", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-small"));
    const first = gear.owned();
    first[0].count = 50;
    first[5].locations.push(place("cursor"));
    first.pop();
    expect(gear.owned()).toEqual(SITE_SMALL);
  });

  it("toOwnedPairs() gives the idents and counts of the protocol, which the protocol takes", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-small"));
    const pairs = gear.toOwnedPairs();
    expect(pairs).toEqual(SITE_SMALL.map((e) => [`${e.key}@${e.tier}`, e.count]));
    expect(pairs[5]).toEqual(["w90001@4", 2]);
    const request = {
      v: 1, kind: "scenario", trio: "pal-mnk-ber", level: 50, mode: "equip-now",
      scenario: { race: "OGR", role: "tank", buffs: "own", evidence: "strict", setup: "dw" },
      owned: pairs, budgetMs: 5000,
    }; // fmt: skip
    expect(validateRequest(request).owned).toEqual(pairs);
  });

  it("does not take a count past what the protocol takes: 99 is used, and it is said", async () => {
    const { gear, said } = mount();
    const bag = [row("General 1", "Wicker Basket", 1, 1, 2), row("General 1-Slot1", "Pellbrook Mallet", 520006, 250), empty("General 1-Slot2")];
    await gear.readFile(file(dump([empty("Any Slot"), ...bag], [])));
    expect(gear.owned()).toEqual([{ key: "w80113", tier: 0, count: LIMITS.maxOwnedCount, locations: [place("bag", LIMITS.maxOwnedCount)] }]);
    expect(gear.toOwnedPairs()).toEqual([["w80113@0", 99]]);
    expect($("#upgrade-limits").hidden).toBe(false);
    expect($("#upgrade-limits").textContent).toBe("1 item has more than 99 copies: 99 are used.");
    expect(said.at(-1)).toBe("1 item read. 1 item has more than 99 copies: 99 are used.");
    await gear.readFile(siteFile("site-small"));
    expect($("#upgrade-limits").hidden).toBe(true);
  });

  it("does not take more entries than the protocol takes: the first 1,000 are used, and it is said", async () => {
    const many = Array.from({ length: LIMITS.maxOwnedEntries + 200 }, (_, i) => record(100000 + i, `Testgem ${String(i).padStart(4, "0")}`));
    const { gear, said } = mount({ table: tableOf(many) });
    const keyRows = many.map((r, i) => keyRow("Equipment", r.name, 900000 + i));
    await gear.readFile(file(dump([empty("Any Slot")], keyRows)));
    expect(gear.owned()).toHaveLength(LIMITS.maxOwnedEntries);
    expect(gear.toOwnedPairs()).toHaveLength(LIMITS.maxOwnedEntries);
    expect(new Set(gear.toOwnedPairs().map(([ident]) => ident)).size).toBe(LIMITS.maxOwnedEntries);
    expect(gear.owned().map((e) => e.key)).toContain("w100000"); // the first in the file
    expect(gear.owned().map((e) => e.key)).not.toContain(`w${100000 + LIMITS.maxOwnedEntries}`);
    expect($("#upgrade-limits").textContent).toBe("The optimizer takes at most 1,000 different items: 200 were left out.");
    expect(said.at(-1)).toBe("1,000 items read. The optimizer takes at most 1,000 different items: 200 were left out.");
    expect(rows()).toHaveLength(LIMITS.maxOwnedEntries);
  });

  it("does not add a thousand-and-first item by name, and says so, but adds a copy of one that is there", async () => {
    const many = Array.from({ length: LIMITS.maxOwnedEntries + 5 }, (_, i) => record(100000 + i, `Testgem ${String(i).padStart(4, "0")}`));
    const { gear } = mount({ table: tableOf(many) });
    await gear.readFile(file(dump([empty("Any Slot")], many.slice(0, LIMITS.maxOwnedEntries).map((r, i) => keyRow("Equipment", r.name, 900000 + i)))));
    expect(gear.owned()).toHaveLength(LIMITS.maxOwnedEntries);
    type($("#upgrade-pick"), "Testgem 1004");
    $("#upgrade-add").click();
    expect(gear.owned()).toHaveLength(LIMITS.maxOwnedEntries);
    expect(noteText()).toBe("The list holds at most 1,000 different items. Remove one to add another.");
    type($("#upgrade-pick"), "Testgem 0003");
    $("#upgrade-add").click();
    expect(gear.owned().find((e) => e.key === "w100003").count).toBe(2);
  });

  it("tells its listeners when the list changes, once for each change, and not when nothing changed", async () => {
    const { gear } = mount();
    let calls = 0;
    const off = gear.onChange(() => (calls += 1));
    await gear.readFile(siteFile("site-small"));
    expect(calls).toBe(1);
    await gear.readFile(siteFile("site-small")); // the same file again: the same list
    expect(calls).toBe(1);
    addByName("lark", "4");
    expect(calls).toBe(2);
    rows()[0].querySelector("button").click();
    expect(calls).toBe(3);
    $("#upgrade-clear").click();
    expect(calls).toBe(4);
    off();
    await gear.readFile(siteFile("site-small"));
    expect(calls).toBe(4);
  });

  it("is not stopped by a listener that throws", async () => {
    const { gear } = mount();
    const seen = [];
    gear.onChange(() => {
      throw new Error("a bug of a listener");
    });
    gear.onChange(() => seen.push(1));
    await gear.readFile(siteFile("site-small"));
    expect(seen).toEqual([1]);
    expect(gear.owned()).toHaveLength(12);
  });

  it("clear() empties it from outside too", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-small"));
    const calls = [];
    gear.onChange(() => calls.push("changed"));
    gear.clear();
    expect(gear.owned()).toEqual([]);
    expect(calls).toEqual(["changed"]);
  });
});

describe("a file that is read in vain", () => {
  /** A file the parser can start on and whose read ends when the test says (in a failure). */
  const lateFile = () => {
    let fail;
    const read = new Promise((_, reject) => (fail = reject));
    return { file: { size: 100, name: "x.txt", slice: () => ({ arrayBuffer: () => read }) }, fail: () => fail(new Error("the read failed")) };
  };
  const later = () => new Promise((resolve) => setTimeout(resolve, 30));

  it("says nothing when its read fails after the visitor cleared the list or gave another file", async () => {
    const { gear, said } = mount();
    const first = lateFile();
    gear.takeFiles([first.file]);
    gear.clear(); // the visitor does not want it any more
    said.length = 0;
    first.fail();
    await later();
    expect(said).toEqual([]);
    expect(noteText()).toBe("");

    const second = lateFile();
    gear.takeFiles([second.file]);
    await gear.readFile(siteFile("site-small")); // another file
    said.length = 0;
    second.fail();
    await later();
    expect(said).toEqual([]);
    expect(noteText()).toBe("");
    expect(gear.owned()).toEqual(SITE_SMALL);
  });

  it("says nothing when the read itself rejects after it was passed by, and still says so when the visitor is waiting for it", async () => {
    const { gear, said } = mount();
    let reject;
    parseDump.mockImplementationOnce(() => new Promise((_, rejecting) => (reject = rejecting)));
    gear.takeFiles([siteFile("site-small")]);
    gear.clear();
    said.length = 0;
    reject(new Error("late"));
    await later();
    expect(said).toEqual([]);
    expect(noteText()).toBe("");

    parseDump.mockImplementationOnce(() => Promise.reject(new Error("now")));
    gear.takeFiles([siteFile("site-small")]);
    await waitFor(() => expect(noteText()).toBe(ERRORS.internal));
    expect(said.at(-1)).toBe(ERRORS.internal);
  });
});

describe("what a file leaves behind", () => {
  it("can be cleared whenever a file was read, even if it gave no rows and only notes about the file", async () => {
    const { gear } = mount();
    expect($("#upgrade-clear").hidden).toBe(true);
    await gear.readFile(file(dump([empty("Any Slot")]))); // no rows, and the notes of a file that may be cut off
    expect(gear.owned()).toEqual([]);
    expect($("#upgrade-warnings").hidden).toBe(false);
    expect($("#upgrade-clear").hidden).toBe(false);
    $("#upgrade-clear").click();
    expect($("#upgrade-warnings").hidden).toBe(true);
    expect($("#upgrade-clear").hidden).toBe(true);
  });

  it("is still not offered a Clear before anything was read or added, or after a file was refused", async () => {
    const { gear } = mount();
    expect($("#upgrade-clear").hidden).toBe(true);
    await gear.readFile(file("this is not an inventory dump\r\n"));
    expect(noteText()).not.toBe("");
    expect($("#upgrade-clear").hidden).toBe(true);
  });
});

describe("how many items match what is typed", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("is said through the page's live region when the visitor pauses, once and not for each key", () => {
    vi.useFakeTimers();
    const { said } = mount();
    const input = $("#upgrade-pick");
    type(input, "l");
    vi.advanceTimersByTime(300);
    type(input, "la");
    vi.advanceTimersByTime(300);
    type(input, "lark");
    expect(said, "not while the visitor types").toEqual([]);
    vi.advanceTimersByTime(499);
    expect(said).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(said).toEqual(["1 item matches"]);
    type(input, "zzz");
    vi.advanceTimersByTime(500);
    expect(said).toEqual(["1 item matches", "No item matches"]);
  });
});

// ---- hostile input -------------------------------------------------------------------------------------------------------------------------------

describe("a hostile file", () => {
  it("is read for what it is: names with the words of every object are names that are not in the catalog", async () => {
    const { gear } = mount();
    const bag = [row("General 1", "Wicker Basket", 1, 1, 5)];
    const names = ["constructor", "toString", "hasOwnProperty", "valueOf", "prototype"];
    names.forEach((name, i) => bag.push(row(`General 1-Slot${i + 1}`, name, 700 + i)));
    await gear.readFile(file(dump([empty("Any Slot"), ...bag], [])));
    expect($$("#upgrade-unknown li").map((li) => li.textContent)).toEqual(names);
    expect(gear.owned()).toEqual([]);
    expect({}.polluted).toBeUndefined();
  });

  it("cannot make a name into markup: what the file calls an item is text where it is shown", async () => {
    const { gear } = mount();
    await gear.readFile(file(dump([row("Head", "Helm of the Stoneward +4", 1), row("Neck", "Alert(1) <b>", 2)], [])));
    expect($("#upgrade-unknown li")).toBeNull(); // (the parser skips a name with a character that no item name has)
    expect(gear.owned()).toHaveLength(1);
    expect(document.querySelectorAll("#upgrade b, #upgrade img, #upgrade script, #upgrade a")).toHaveLength(0);
  });

  it("is bounded by the parser first: a file past a limit gets the parser's refusal and changes nothing", async () => {
    const { gear } = mount();
    await gear.readFile(siteFile("site-small"));
    const lines = Array.from({ length: DUMP.maxLines + 5 }, (_, i) => row("Fingers", `Tarn Signet ${i}`, i + 1));
    await gear.readFile(file(dump(lines, [])));
    expect(noteText()).toBe(ERRORS.tooManyLines);
    expect(gear.owned()).toEqual(SITE_SMALL);
  });
});

// ---- the source -----------------------------------------------------------------------------------------------------------------------------------

describe("the code of the section", () => {
  const sources = ["ui/gear-picker.js", "ui/upgrade-input.js"].map((name) => [name, readFileSync(resolve(STATIC, name), "utf8")]);

  it.each(sources)("%s has no way to turn text into markup, a pattern or an address, stores nothing, and uses nothing that Safari 15 lacks", (_, source) => {
    const forbidden = [
      /\bRegExp\b/, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|createContextualFragment|DOMParser|srcdoc/, /\beval\s*\(|new\s+Function|setTimeout\(\s*["'`]/,
      /localStorage|sessionStorage|indexedDB|document\.cookie|navigator\.sendBeacon|XMLHttpRequest|WebSocket/,
      /createObjectURL|new\s+Blob|FileReader|window\.open|\.href\s*=|location\.(?:assign|replace)|\bsetAttribute\(\s*["'](?:href|src|on)/,
      /Object\.hasOwn\b|\.at\(|\bfindLast\b|structuredClone/,
    ];
    for (const pattern of forbidden) expect(source, String(pattern)).not.toMatch(pattern);
  });
});
