// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// "Remember my gear on this device": an unchecked box in the Upgrade section. Checked, the owned list is kept on the device as {v: 1, entries: [[page id, tier, count]]} (at most 500
// entries) and saved at every change; unchecked, the copy is erased. On a page with remembered gear the list is filled again through the same checks as any input (the item list,
// the protocol's limits, the keys), what the catalog no longer has is dropped and said, and a line offers Forget. Every call to the storage is guarded: it may be missing, full or
// blocked, and the section works the same without it. The storage here is a stand-in that notes its calls and can fail; the gear input is the real one, on the fixture's table of
// invented items. Every name is invented.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LIMITS } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { createGearInput } from "../pipeline/trioforge/site/static/ui/upgrade-input.js";
import { createRemember } from "../pipeline/trioforge/site/static/ui/remember.js";
import { table as itemsTable } from "./upgrade-answer-helpers.mjs";
import { $, $$, STATIC, dumpText, mountPage, press, record, siteTable, tableOf, type, wake } from "./upgrade-helpers.mjs";

const KEY = "trioforge-gear";
const TRIO = ["PAL", "MNK", "BER"];
const SECRET = "ZQ-secret-name-7731.txt";

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

/** A storage that notes its calls; `fail` names the calls that throw, as a blocked or a full one does. */
function storageOf({ initial = {}, fail = [] } = {}) {
  const data = new Map(Object.entries(initial));
  const calls = [];
  const storage = {
    data,
    calls,
    fail: new Set(fail),
    getItem(key) {
      calls.push(["get", key]);
      if (storage.fail.has("get")) throw new DOMException("blocked", "SecurityError");
      return data.has(key) ? data.get(key) : null;
    },
    setItem(key, value) {
      calls.push(["set", key]);
      if (storage.fail.has("set")) throw new DOMException("full", "QuotaExceededError");
      data.set(key, String(value));
    },
    removeItem(key) {
      calls.push(["remove", key]);
      if (storage.fail.has("remove")) throw new DOMException("blocked", "SecurityError");
      data.delete(key);
    },
  };
  return storage;
}
const writes = (storage) => storage.calls.filter(([what]) => what !== "get");
const kept = (storage) => (storage.data.has(KEY) ? JSON.parse(storage.data.get(KEY)) : null);
const stored = (entries, v = 1) => JSON.stringify({ v, entries });

/** The section with the gear input made on a table (the fixture's by default) and the box made on it; `spoken` is what the box says through the page's live region. */
function mount({ table = itemsTable(), storage = storageOf(), text = null, remembering = true } = {}) {
  const root = mountPage('<p id="announce" class="sr-only" role="status" aria-live="polite"></p>');
  wake(root);
  const said = [];
  const spoken = [];
  const gear = createGearInput(root, { items: table, trio: TRIO, doc: document, win: window, announce: (text) => said.push(text) });
  const remember = remembering ? createRemember(root, { gear, records: table.records, storage, key: KEY, stored: text, announce: (line) => spoken.push(line), doc: document }) : null;
  return { root, gear, remember, storage, said, spoken };
}

const box = () => $("#upgrade-remember-box");
const note = () => $("#upgrade-remember-note");
const noteText = () => (note().hidden ? "" : note().textContent.replace(/\s+/g, " ").trim());
const forget = () => $("#upgrade-forget");
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
/** Add an item by name the way a visitor does. */
function addByName(name, tier = "0") {
  const input = $("#upgrade-pick");
  type(input, name);
  press(input, "ArrowDown");
  press(input, "Enter");
  $("#upgrade-tier").value = tier;
  $("#upgrade-add").click();
}
const check = (on) => {
  box().checked = on;
  box().dispatchEvent(new Event("change", { bubbles: true }));
};
/** What the list holds as the box keeps it: [page id, tier, count]. */
const triples = (gear) => gear.owned().map((entry) => [Number(entry.key.slice(1)), entry.tier, entry.count]);
const file = (text, name = SECRET) => new File([text], name);

// ---- the box ---------------------------------------------------------------------------------------------------------------------------------------

describe("the box", () => {
  it("is in the Upgrade section, a check box with the words Remember my gear on this device, unchecked, and it touches the device not at all until it is used", () => {
    const { root, storage } = mount();
    expect(box().closest("#upgrade")).toBe(root);
    expect(box().type).toBe("checkbox");
    expect(box().checked).toBe(false);
    expect($('label[for="upgrade-remember-box"]').textContent).toBe("Remember my gear on this device");
    expect(storage.calls).toEqual([]);
    expect(note().hidden).toBe(true);
    expect(forget()).toBeNull();
  });

  it("says what is kept and where: the items, their tiers and how many, in this browser, and nothing is sent", () => {
    mount();
    const help = $("#upgrade-remember-help").textContent;
    expect(box().getAttribute("aria-describedby")).toContain("upgrade-remember-help");
    expect(help).toMatch(/items, their tiers and how many/);
    expect(help).toMatch(/this browser/);
    expect(help).toMatch(/nothing is sent/i);
  });

  it("is between the list of the gear and the results, and has no live region of its own", () => {
    mount();
    const block = $("#upgrade-remember");
    expect(block.previousElementSibling).toBe($("#upgrade-owned"));
    expect(block.nextElementSibling).toBe($("#upgrade-results"));
    expect($$('#upgrade-remember [role="status"], #upgrade-remember [role="alert"], #upgrade-remember [aria-live]')).toHaveLength(0);
  });
});

// ---- keeping ---------------------------------------------------------------------------------------------------------------------------------------

describe("checked", () => {
  it("keeps the owned list as {v: 1, entries: [[page id, tier, count]]}, and says so once", () => {
    const { gear, storage, spoken } = mount();
    addByName("tarn signet", "4");
    addByName("tarn signet", "4");
    addByName("corbel cap", "0");
    expect(storage.calls).toEqual([]); // (nothing is kept until it is asked)
    check(true);
    expect(kept(storage)).toEqual({ v: 1, entries: [[80305, 0, 1], [80301, 4, 2]] });
    expect(Object.keys(kept(storage)).sort()).toEqual(["entries", "v"]);
    expect(triples(gear)).toEqual(kept(storage).entries);
    expect(noteText()).toBe("Your gear is remembered on this device.");
    expect(spoken).toEqual(["Your gear is remembered on this device."]);
  });

  it("saves at every change: an item added, one removed, a file read, and Clear", async () => {
    const { gear, storage, spoken } = mount({ table: siteTable() });
    check(true);
    expect(storage.data.has(KEY), "an empty list is not kept: there is nothing to remember").toBe(false);
    expect(noteText()).toBe("Your gear will be remembered on this device as you add it.");
    addByName("stud of the fallen", "4");
    expect(kept(storage).entries).toEqual([[90009, 4, 1]]);
    addByName("crown of the vanguard", "0");
    expect(kept(storage).entries).toEqual([[90003, 0, 1], [90009, 4, 1]]);
    $("#upgrade-owned li button").click(); // (Remove, on the first row)
    expect(kept(storage).entries).toEqual([[90009, 4, 1]]);
    await gear.readFile(file(dumpText("site-small")));
    expect(kept(storage).entries).toEqual(triples(gear));
    expect(kept(storage).entries).toHaveLength(13); // (the 12 of the file and the one added by name)
    $("#upgrade-clear").click();
    expect(storage.data.has(KEY)).toBe(false);
    expect(box().checked, "the visitor's choice stays").toBe(true);
    addByName("crown of the vanguard", "0");
    expect(kept(storage).entries).toEqual([[90003, 0, 1]]);
    // routine saves are not announced
    expect(spoken).toEqual(["Your gear will be remembered on this device as you add it."]);
  });

  it("keeps nothing but the triples: no place, no file name, no name of an item", async () => {
    const { gear, storage } = mount({ table: siteTable() });
    check(true);
    await gear.readFile(file(dumpText("site-small"), "Zorbwick-faketown-inventory.txt"));
    const text = storage.data.get(KEY);
    expect(JSON.parse(text)).toEqual({ v: 1, entries: triples(gear) });
    for (const piece of ["Zorbwick", "faketown", "inventory", "bank", "worn", "bag", "keyring", "Helm", "Stoneward", "locations", "name"]) expect(text, piece).not.toContain(piece);
    expect(Object.keys(JSON.parse(text))).toEqual(["v", "entries"]);
    expect(JSON.parse(text).entries.every((entry) => entry.length === 3 && entry.every(Number.isInteger))).toBe(true);
  });

  it("keeps at most 500 entries, and says how many were left out", () => {
    const records = Array.from({ length: 640 }, (_, i) => record(70000 + i, `Quillfeather Charm Number ${i}`, { slots: ["EAR"] }));
    const { gear, storage, spoken } = mount({ table: tableOf(records) });
    gear.restore(records.slice(0, 600).map((one) => [`w${one.id}`, 0, 1]));
    expect(gear.owned()).toHaveLength(600);
    check(true);
    expect(kept(storage).entries).toHaveLength(500);
    expect(kept(storage).entries).toEqual(triples(gear).slice(0, 500));
    expect(noteText()).toBe("Only 500 items can be remembered: 100 were left out.");
    expect(spoken.at(-1)).toBe("Only 500 items can be remembered: 100 were left out.");
    gear.restore(records.slice(600, 610).map((one) => [`w${one.id}`, 0, 1]));
    expect(noteText()).toBe("Only 500 items can be remembered: 110 were left out.");
    expect(spoken.at(-1)).toBe("Only 500 items can be remembered: 110 were left out.");
    expect(spoken.filter((line) => line.startsWith("Only 500")).length, "said when the number changes, not at every save").toBe(2);
  });

  it("says one item was left out in the singular, and an item with a key that is not a page number cannot be kept", () => {
    const records = [
      ...Array.from({ length: 501 }, (_, i) => record(70000 + i, `Quillfeather Charm Number ${i}`, { slots: ["EAR"] })),
      record(60001, "Marsh Token", { slots: ["EAR"], key: "rmarsh-token" }),
    ];
    const { gear, storage } = mount({ table: tableOf(records) });
    gear.restore([...records.slice(0, 501).map((one) => [`w${one.id}`, 0, 1]), ["rmarsh-token", 0, 1]]);
    check(true);
    expect(kept(storage).entries).toHaveLength(500);
    expect(noteText()).toMatch(/Only 500 items can be remembered: 1 was left out\./);
    expect(noteText()).toMatch(/1 item could not be remembered: its key is not a page number\./);
    expect(storage.data.get(KEY)).not.toContain("marsh");
    expect(kept(storage).entries.every(([id]) => id >= 70000)).toBe(true);
  });
});

describe("unchecked", () => {
  it("erases the copy on the device, says so, and leaves the list as it is", () => {
    const { gear, storage, spoken } = mount();
    addByName("tarn signet", "4");
    check(true);
    check(false);
    expect(storage.data.has(KEY)).toBe(false);
    expect(noteText()).toBe("Your remembered gear was erased from this device.");
    expect(spoken.at(-1)).toBe("Your remembered gear was erased from this device.");
    expect(gear.owned()).toHaveLength(1);
    addByName("corbel cap", "0");
    expect(storage.data.has(KEY), "and it is not kept again").toBe(false);
  });

  it("keeps the focus on the box, checked or unchecked", () => {
    mount();
    box().focus();
    check(true);
    expect(document.activeElement).toBe(box());
    check(false);
    expect(document.activeElement).toBe(box());
  });
});

// ---- a device that fails ---------------------------------------------------------------------------------------------------------------------------

describe("a device that cannot be written", () => {
  it("is told once, the section works as before, and the box stays as the visitor set it", () => {
    const storage = storageOf({ fail: ["set"] });
    const { gear, spoken } = mount({ storage });
    addByName("tarn signet", "4");
    check(true);
    const words = "Couldn't remember your gear: this browser would not store it. The rest of the section works as before.";
    expect(noteText()).toBe(words);
    expect(spoken).toEqual([words]);
    addByName("corbel cap", "0");
    addByName("dunmere helm", "0");
    expect(gear.owned()).toHaveLength(3);
    expect(spoken, "said once, not at every change").toEqual([words]);
    expect(box().checked).toBe(true);
  });

  it("says that it is remembered again when the device takes a write after it refused one", () => {
    const storage = storageOf({ fail: ["set"] });
    const { spoken } = mount({ storage });
    addByName("tarn signet", "4");
    check(true);
    storage.fail.delete("set");
    addByName("corbel cap", "0");
    expect(kept(storage).entries).toHaveLength(2);
    expect(noteText()).toBe("Your gear is remembered on this device.");
    expect(spoken.at(-1)).toBe("Your gear is remembered on this device.");
  });

  it("is a missing storage too: the same words, and nothing else changes", () => {
    const { gear, spoken } = mount({ storage: null });
    addByName("tarn signet", "4");
    check(true);
    expect(noteText()).toMatch(/^Couldn't remember your gear/);
    expect(spoken).toHaveLength(1);
    expect(gear.owned()).toHaveLength(1);
  });

  it("cannot be erased: the section says so", () => {
    const storage = storageOf({ fail: ["remove"] });
    const { gear } = mount({ storage });
    addByName("tarn signet", "4");
    check(true);
    check(false);
    expect(noteText()).toBe("Couldn't erase your remembered gear: this browser would not let the page change its storage.");
    expect(gear.owned()).toHaveLength(1);
  });

  it("throws at no call: a storage that throws from every method is a storage that cannot be used", () => {
    const storage = storageOf({ fail: ["get", "set", "remove"] });
    const { gear } = mount({ storage, text: stored([[80301, 4, 1]]) });
    expect(() => {
      addByName("tarn signet", "4");
      check(true);
      check(false);
      $("#upgrade-clear").click();
    }).not.toThrow();
    expect(gear.owned()).toHaveLength(0);
  });
});

// ---- restoring -------------------------------------------------------------------------------------------------------------------------------------

describe("remembered gear", () => {
  const TEXT = stored([[80301, 4, 2], [80305, 0, 1], [80304, 4, 1]]);

  it("fills the list, checks the box, says how many were restored and that there are no places for them, and offers Forget", () => {
    const { gear, storage, spoken } = mount({ text: TEXT, storage: storageOf({ initial: { [KEY]: TEXT } }) });
    expect(triples(gear)).toEqual([[80305, 0, 1], [80304, 4, 1], [80301, 4, 2]]); // (by name: Corbel Cap, Dunmere Helm, Tarn Signet)
    expect(gear.owned().every((entry) => entry.locations.length === 0)).toBe(true);
    expect(box().checked).toBe(true);
    const line = "Restored 3 items from this device. Restored gear has no places, so Equip now gives no location notes for it.";
    expect(noteText()).toBe(`${line} Forget`);
    expect(spoken).toEqual([line]);
    expect(forget().tagName).toBe("BUTTON");
    expect(forget().textContent).toBe("Forget");
    expect(kept(storage)).toEqual({ v: 1, entries: triples(gear) }); // (kept as it is now)
  });

  it("says one item in the singular", () => {
    mount({ text: stored([[80301, 4, 1]]), storage: storageOf({ initial: { [KEY]: stored([[80301, 4, 1]]) } }) });
    expect(noteText()).toMatch(/^Restored 1 item from this device\./);
  });

  it("goes through the same checks as any input: the item list, the limits of the protocol, the keys", () => {
    const text = stored([[80301, 4, 150], [80305, 11, 1], [80305, 0, 0], [80306, -1, 1], [0, 0, 1], [2147483648, 0, 1], [1.5, 0, 1], ["80301", 0, 1], [80308, 0], [80308, 0, 1, 9], null, "x", [80304, 0, 3]]);
    const { gear, spoken } = mount({ text, storage: storageOf({ initial: { [KEY]: text } }) });
    expect(gear.owned().map((entry) => [entry.key, entry.tier, entry.count])).toEqual([["w80304", 0, 3], ["w80301", 4, LIMITS.maxOwnedCount]]);
    expect(spoken[0]).toMatch(/11 remembered entries were not valid and were dropped\./);
    expect($("#upgrade-limits").textContent).toMatch(/1 item has more than 99 copies: 99 are used\./);
  });

  it("drops what the catalog no longer has, says how many, and keeps the rest, on the device too", () => {
    const text = stored([[80301, 4, 1], [99991, 0, 1], [99992, 3, 2], [80305, 0, 1]]);
    const { gear, storage, spoken } = mount({ text, storage: storageOf({ initial: { [KEY]: text } }) });
    expect(gear.owned().map((entry) => entry.key).sort()).toEqual(["w80301", "w80305"]);
    expect(spoken[0]).toContain("2 remembered items are no longer in the catalog.");
    expect(noteText()).toContain("2 remembered items are no longer in the catalog.");
    expect(kept(storage).entries).toEqual(triples(gear));
    expect(JSON.stringify(kept(storage))).not.toContain("99991");
  });

  it("says one item in the singular too", () => {
    const text = stored([[80301, 4, 1], [99991, 0, 1]]);
    const { spoken } = mount({ text, storage: storageOf({ initial: { [KEY]: text } }) });
    expect(spoken[0]).toContain("1 remembered item is no longer in the catalog.");
  });

  it("restores nothing and erases the copy when the catalog has none of it, and the box is not checked", () => {
    const text = stored([[99991, 0, 1], [99992, 3, 2]]);
    const { gear, storage, spoken } = mount({ text, storage: storageOf({ initial: { [KEY]: text } }) });
    expect(gear.owned()).toHaveLength(0);
    expect(box().checked).toBe(false);
    expect(storage.data.has(KEY)).toBe(false);
    expect(spoken).toEqual(["2 remembered items are no longer in the catalog."]);
    expect(forget()).toBeNull();
  });

  it("ignores and erases what another version of the site stored, and says so once", () => {
    for (const version of [0, 2, 99, "1", null]) {
      document.body.innerHTML = "";
      const text = JSON.stringify({ v: version, entries: [[80301, 4, 1]] });
      const { gear, storage, spoken } = mount({ text, storage: storageOf({ initial: { [KEY]: text } }) });
      expect(gear.owned(), String(version)).toHaveLength(0);
      expect(storage.data.has(KEY), String(version)).toBe(false);
      expect(spoken, String(version)).toEqual(["Gear remembered by another version of this site was ignored and erased."]);
      expect(box().checked).toBe(false);
    }
  });

  it("erases and says so what cannot be read at all, once", () => {
    for (const text of ["not json", "[]", "null", "42", '"x"', "{}", '{"v":1}', '{"v":1,"entries":"x"}', '{"v":1,"entries":{"0":[80301,4,1]}}', ""]) {
      document.body.innerHTML = "";
      const { gear, storage, spoken } = mount({ text, storage: storageOf({ initial: { [KEY]: text } }) });
      expect(gear.owned(), text).toHaveLength(0);
      expect(storage.data.has(KEY), text).toBe(false);
      expect(spoken, text).toHaveLength(1);
      expect(spoken[0], text).toMatch(/could not be read, so it was erased\.$|another version/);
    }
  });

  it("takes no more than 500 entries from what was stored", () => {
    const records = Array.from({ length: 640 }, (_, i) => record(70000 + i, `Quillfeather Charm Number ${i}`, { slots: ["EAR"] }));
    const text = stored(records.slice(0, 600).map((one) => [one.id, 0, 1]));
    const { gear } = mount({ table: tableOf(records), text, storage: storageOf({ initial: { [KEY]: text } }) });
    expect(gear.owned()).toHaveLength(500);
  });

  it("is forgotten with Forget: the copy is erased, the box is unchecked, the list is cleared, and the focus goes to the box", () => {
    const { gear, storage, spoken } = mount({ text: TEXT, storage: storageOf({ initial: { [KEY]: TEXT } }) });
    forget().focus();
    forget().click();
    expect(storage.data.has(KEY)).toBe(false);
    expect(box().checked).toBe(false);
    expect(gear.owned()).toHaveLength(0);
    expect(noteText()).toBe("Forgot your gear: the list is empty and nothing is remembered on this device.");
    expect(spoken.at(-1)).toBe("Forgot your gear: the list is empty and nothing is remembered on this device.");
    expect(forget()).toBeNull();
    expect(document.activeElement).toBe(box());
    addByName("tarn signet", "4");
    expect(storage.data.has(KEY), "and nothing is kept again").toBe(false);
  });

  it("is forgotten by unchecking the box as well, and Forget goes", () => {
    const { storage } = mount({ text: TEXT, storage: storageOf({ initial: { [KEY]: TEXT } }) });
    check(false);
    expect(storage.data.has(KEY)).toBe(false);
    expect(forget()).toBeNull();
    expect(noteText()).toBe("Your remembered gear was erased from this device.");
  });

  it("goes on being kept after it was restored: a change saves, with the box checked", () => {
    const { storage } = mount({ text: TEXT, storage: storageOf({ initial: { [KEY]: TEXT } }) });
    addByName("fenwick greaves", "0");
    expect(kept(storage).entries).toHaveLength(4);
    expect(kept(storage).entries).toContainEqual([80308, 0, 1]);
  });

  it("is said once: one announcement for the whole restore, and none of the list's own for the entries put back", () => {
    const text = stored([[80301, 4, 1], [99991, 0, 1], ["bad"]]);
    const { spoken, said } = mount({ text, storage: storageOf({ initial: { [KEY]: text } }) });
    expect(spoken).toHaveLength(1);
    expect(spoken[0]).toBe(
      "Restored 1 item from this device. 1 remembered item is no longer in the catalog. 1 remembered entry was not valid and was dropped. Restored gear has no places, so Equip now gives no location notes for it.",
    );
    expect(said).toEqual([]);
  });
});

// ---- remembered gear and a file read after it ----------------------------------------------------------------------------------------------------------------
// What a page restores is the list of an earlier visit, as the file that made it was: the next file the visitor reads replaces it, as it would replace the file read before. What the
// visitor added by hand stays added by hand. (The first version put the remembered entries with the hand-added ones, so the file came on top of them and every count was doubled, and
// the doubled list was kept.)

describe("remembered gear and a file that is read after it", () => {
  const SMALL = () => file(dumpText("site-small"));
  /** The list as its rows show it: key, tier, count. */
  const counts = (gear) => gear.owned().map((entry) => [entry.key, entry.tier, entry.count]);
  const wheres = () => $$("#upgrade-owned > li").map((li) => [li.querySelector(".owned-name").textContent, li.querySelector(".owned-where").textContent]);
  /** A later visit: the page makes the section again, and the box finds what the earlier visit left on the device. */
  function visit(storage) {
    document.body.innerHTML = "";
    return mount({ table: siteTable(), storage, text: storage.data.has(KEY) ? storage.data.get(KEY) : null });
  }

  it("is replaced by the file, as the file read before it would be: nothing is counted twice, and what is kept is the list of the file", async () => {
    const storage = storageOf();
    const first = mount({ table: siteTable(), storage });
    check(true);
    await first.gear.readFile(SMALL());
    const alone = counts(first.gear);
    expect(alone).toHaveLength(12);
    expect(alone.find(([key, tier]) => key === "w90001" && tier === 4)[2], "the Helm of the Stoneward is in the file twice").toBe(2);
    const saved = kept(storage);
    const second = visit(storage);
    expect(counts(second.gear), "restored").toEqual(alone);
    await second.gear.readFile(SMALL());
    expect(counts(second.gear), "read after the restore: no count is doubled").toEqual(alone);
    expect(kept(storage), "and what the device keeps is the list of the file").toEqual(saved);
    await second.gear.readFile(SMALL());
    expect(counts(second.gear), "read again").toEqual(alone);
    expect(kept(storage)).toEqual(saved);
    const third = visit(storage);
    expect(counts(third.gear), "and the visit after it restores the same list").toEqual(alone);
  });

  it("is replaced as a whole: what the file does not have is gone, and the places of the file are shown", async () => {
    const storage = storageOf({ initial: { [KEY]: stored([[90009, 4, 3], [90001, 4, 1], [90007, 2, 1]]) } });
    const { gear } = mount({ table: siteTable(), storage, text: storage.data.get(KEY) });
    expect(counts(gear).find(([key]) => key === "w90009")).toEqual(["w90009", 4, 3]);
    await gear.readFile(SMALL());
    expect(counts(gear).some(([key]) => key === "w90009"), "the Stud of the Fallen was not in the file").toBe(false);
    expect(counts(gear).find(([key, tier]) => key === "w90001" && tier === 4)[2]).toBe(2);
    expect(counts(gear).find(([key, tier]) => key === "w90007" && tier === 2)[2], "the Earring is in the file twice, and was remembered once").toBe(2);
    expect(wheres().find(([name]) => name === "Helm of the Stoneward")[1]).toBe("worn, in the bank");
  });

  it("leaves what the visitor added by hand: only the remembered layer is replaced", async () => {
    const storage = storageOf({ initial: { [KEY]: stored([[90009, 4, 3], [90001, 4, 1]]) } });
    const { gear } = mount({ table: siteTable(), storage, text: storage.data.get(KEY) });
    addByName("crown of the vanguard", "0"); // by hand
    addByName("helm of the stoneward", "4"); // by hand, and the same item as a remembered one
    expect(counts(gear).find(([key, tier]) => key === "w90001" && tier === 4)[2], "restored once, added once").toBe(2);
    await gear.readFile(SMALL());
    expect(counts(gear).find(([key]) => key === "w90003"), "the Crown stays").toEqual(["w90003", 0, 1]);
    expect(counts(gear).some(([key]) => key === "w90009"), "the remembered Stud is replaced").toBe(false);
    expect(counts(gear).find(([key, tier]) => key === "w90001" && tier === 4)[2], "the Helm: the hand's one and the file's two").toBe(3);
    expect(wheres().find(([name]) => name === "Crown of the Vanguard")[1]).toBe("added by hand");
  });

  it("stays when the file is refused: nothing was read, so nothing is replaced", async () => {
    const storage = storageOf({ initial: { [KEY]: stored([[90009, 4, 3], [90001, 4, 1]]) } });
    const { gear } = mount({ table: siteTable(), storage, text: storage.data.get(KEY) });
    const before = counts(gear);
    const answer = await gear.readFile(file("this is not an inventory at all"));
    expect(answer.ok).toBe(false);
    expect(counts(gear)).toEqual(before);
    expect(kept(storage).entries).toHaveLength(2);
  });

  it("is taken out by Remove, one item at a time, and the file read later does not bring back what was taken out of the layer", async () => {
    const storage = storageOf({ initial: { [KEY]: stored([[90009, 4, 3], [90001, 4, 1]]) } });
    const { gear } = mount({ table: siteTable(), storage, text: storage.data.get(KEY) });
    const row = [...$$("#upgrade-owned > li")].find((li) => li.querySelector(".owned-name").textContent === "Stud of the Fallen");
    row.querySelector("button").click();
    expect(counts(gear)).toEqual([["w90001", 4, 1]]);
    expect(kept(storage).entries).toEqual([[90001, 4, 1]]);
    await gear.readFile(SMALL());
    expect(counts(gear).some(([key]) => key === "w90009")).toBe(false);
  });

  it("is emptied by Clear: the file read after it is the whole list", async () => {
    const storage = storageOf({ initial: { [KEY]: stored([[90009, 4, 3], [90001, 4, 1]]) } });
    const { gear } = mount({ table: siteTable(), storage, text: storage.data.get(KEY) });
    $("#upgrade-clear").click();
    expect(counts(gear)).toEqual([]);
    await gear.readFile(SMALL());
    expect(counts(gear)).toHaveLength(12);
    expect(counts(gear).find(([key, tier]) => key === "w90001" && tier === 4)[2]).toBe(2);
  });

  it("goes on being counted as the sum of what was restored and what was added by hand, until a file replaces the restored part", () => {
    const storage = storageOf({ initial: { [KEY]: stored([[90009, 4, 2]]) } });
    const { gear } = mount({ table: siteTable(), storage, text: storage.data.get(KEY) });
    addByName("stud of the fallen", "4");
    expect(counts(gear)).toEqual([["w90009", 4, 3]]);
    expect(kept(storage).entries).toEqual([[90009, 4, 3]]);
  });
});

describe("the words for where an item is", () => {
  const wheres = () => $$("#upgrade-owned > li").map((li) => [li.querySelector(".owned-name").textContent, li.querySelector(".owned-where").textContent]);

  it("say remembered for an item that was restored, and not added by hand: the visitor did not add it", () => {
    const storage = storageOf({ initial: { [KEY]: stored([[90009, 4, 1], [90001, 0, 2]]) } });
    mount({ table: siteTable(), storage, text: storage.data.get(KEY) });
    expect(wheres()).toEqual([["Helm of the Stoneward", "remembered"], ["Stud of the Fallen", "remembered"]]);
  });

  it("say added by hand for an item the visitor added, and both for one that is both", () => {
    const storage = storageOf({ initial: { [KEY]: stored([[90009, 4, 1]]) } });
    mount({ table: siteTable(), storage, text: storage.data.get(KEY) });
    addByName("stud of the fallen", "4");
    addByName("crown of the vanguard", "0");
    expect(wheres()).toEqual([["Crown of the Vanguard", "added by hand"], ["Stud of the Fallen", "remembered, added by hand"]]);
  });

  it("are the places of the file for an item that came from a file, as before", async () => {
    const { gear } = mount({ table: siteTable() });
    await gear.readFile(file(dumpText("site-small")));
    expect(wheres().find(([name]) => name === "Rune-etched Earring")[1]).toBe("worn ×2");
    expect(wheres().every(([, where]) => where !== "remembered" && where !== "added by hand")).toBe(true);
  });
});

// ---- another tab erases the copy ---------------------------------------------------------------------------------------------------------------------------
// The device is shared by every tab of the site. A tab that has the box checked writes the list at every change, so when another tab erased the copy (Forget, the box unchecked) it
// would write it again with the next change, and the erase would be undone. A tab hears about an erase in another tab (the storage event of the key, or of the whole storage cleared),
// sets itself off, unchecks the box and says so; its list stays as it is.

describe("a copy that another tab erases", () => {
  const erased = (init = { key: KEY, oldValue: "{}", newValue: null }) => window.dispatchEvent(new StorageEvent("storage", init));
  const WORDS = "Your remembered gear was erased from this device in another tab, so this page no longer remembers it.";
  const FIRST = stored([[80301, 4, 2]]);

  it("is not written again by this tab: the box is unchecked, a line says so (aloud too), and a change of the list afterwards touches nothing", () => {
    const storage = storageOf({ initial: { [KEY]: FIRST } });
    const { gear, spoken } = mount({ text: FIRST, storage });
    expect(box().checked).toBe(true);
    storage.data.delete(KEY); // (what the other tab did)
    erased();
    const calls = storage.calls.length; // (the event itself reads the key, to see whether it holds this tab's own late write; that is held by the tests below)
    expect(box().checked).toBe(false);
    expect(noteText()).toBe(WORDS);
    expect(spoken.at(-1)).toBe(WORDS);
    expect(forget(), "and there is nothing to forget").toBeNull();
    expect(gear.owned(), "the list stays as it is").toHaveLength(1);
    addByName("corbel cap", "0");
    expect(gear.owned()).toHaveLength(2);
    expect(storage.data.has(KEY), "the erase is not undone").toBe(false);
    expect(storage.calls.slice(calls), "and the device is not touched at all").toEqual([]);
  });

  it("does so when the whole storage was cleared in the other tab (the event has no key)", () => {
    const storage = storageOf({ initial: { [KEY]: FIRST } });
    const { spoken } = mount({ text: FIRST, storage });
    storage.data.clear();
    erased({ key: null, oldValue: null, newValue: null });
    expect(box().checked).toBe(false);
    expect(spoken.at(-1)).toBe(WORDS);
    addByName("corbel cap", "0");
    expect(storage.data.has(KEY)).toBe(false);
  });

  it("does not move the focus", () => {
    const { storage } = mount({ text: FIRST, storage: storageOf({ initial: { [KEY]: FIRST } }) });
    $("#upgrade-pick").focus();
    storage.data.delete(KEY);
    erased();
    expect(document.activeElement).toBe($("#upgrade-pick"));
  });

  it("leaves a write of the copy by another tab, and a change of some other key, alone", () => {
    const storage = storageOf({ initial: { [KEY]: FIRST } });
    const { gear, spoken } = mount({ text: FIRST, storage });
    const said = spoken.length;
    erased({ key: KEY, oldValue: FIRST, newValue: stored([[80301, 4, 3]]) });
    erased({ key: "trioforge-theme", oldValue: "dark", newValue: null });
    expect(box().checked).toBe(true);
    expect(spoken).toHaveLength(said);
    addByName("corbel cap", "0");
    expect(kept(storage).entries).toHaveLength(2); // (it goes on remembering)
    expect(gear.owned()).toHaveLength(2);
  });

  it("says nothing when the box was not checked: there was nothing to set off", () => {
    const { spoken } = mount({ storage: storageOf() });
    erased();
    expect(box().checked).toBe(false);
    expect(spoken).toEqual([]);
    expect(note().hidden).toBe(true);
  });

  it("can be switched on again by the visitor, and then it keeps the list as before", () => {
    const storage = storageOf({ initial: { [KEY]: FIRST } });
    mount({ text: FIRST, storage });
    storage.data.delete(KEY);
    erased();
    check(true);
    expect(kept(storage).entries).toEqual([[80301, 4, 2]]);
    expect(noteText()).toBe("Your gear is remembered on this device.");
  });

  it("hears only the page's own window, and only once for each box", () => {
    const storage = storageOf({ initial: { [KEY]: FIRST } });
    const { spoken } = mount({ text: FIRST, storage });
    storage.data.delete(KEY);
    erased();
    erased();
    expect(spoken.filter((line) => line === WORDS)).toHaveLength(1);
  });

  // The erase of the other tab and the event that tells this tab of it are two things, and a task of this tab can run between them: a change of the list that was queued here writes the
  // copy again (the box is still checked), and the tab that the event then sets off leaves its own late write on the device, so the erase is undone after all. A tab that hears an erase
  // therefore takes the key out again when it holds exactly the text this tab wrote last. A copy that another tab wrote is not this tab's to take.

  it("takes out its own late write: the other tab erased the copy, a change here wrote it again before the event was handled, and the key is gone after the event", () => {
    const storage = storageOf({ initial: { [KEY]: FIRST } });
    const { gear, spoken } = mount({ text: FIRST, storage });
    storage.data.delete(KEY); // (what the other tab did)
    addByName("corbel cap", "0"); // (a change here that ran before the event was handled: the box is still checked, so the list is written)
    expect(kept(storage).entries, "the key holds this tab's list again").toEqual(triples(gear));
    const calls = storage.calls.length;
    erased();
    expect(storage.data.has(KEY), "the erase stands").toBe(false);
    expect(storage.calls.slice(calls), "one read of the key, and the removal of the text that is this tab's own").toEqual([["get", KEY], ["remove", KEY]]);
    expect(box().checked).toBe(false);
    expect(noteText()).toBe(WORDS);
    expect(spoken.at(-1)).toBe(WORDS);
    expect(gear.owned(), "the list stays as it is").toHaveLength(2);
    addByName("dunmere helm", "0");
    expect(gear.owned()).toHaveLength(3);
    expect(storage.data.has(KEY), "and it is not written again").toBe(false);
  });

  it("does so when the whole storage was cleared in the other tab (the event has no key) and this tab's late write came after it", () => {
    const storage = storageOf({ initial: { [KEY]: FIRST } });
    const { spoken } = mount({ text: FIRST, storage });
    storage.data.clear();
    addByName("corbel cap", "0");
    expect(storage.data.has(KEY)).toBe(true);
    erased({ key: null, oldValue: null, newValue: null });
    expect(storage.data.has(KEY), "the clear stands").toBe(false);
    expect(box().checked).toBe(false);
    expect(spoken.at(-1)).toBe(WORDS);
  });

  it("takes out the last write and not an earlier one: the text it compares is the one this tab wrote last, however many times it wrote", () => {
    const storage = storageOf({ initial: { [KEY]: FIRST } });
    mount({ text: FIRST, storage });
    addByName("corbel cap", "0");
    addByName("dunmere helm", "0");
    storage.data.delete(KEY);
    addByName("fenwick greaves", "0"); // (the late write)
    expect(kept(storage).entries).toHaveLength(4);
    erased();
    expect(storage.data.has(KEY)).toBe(false);
  });

  it.each([
    ["this tab had written the copy", true],
    ["this tab had written nothing: its list was empty, and an empty list is not kept", false],
  ])("leaves a copy that another tab wrote after the erase, and is set off all the same: %s", (_, wrote) => {
    const theirs = stored([[80305, 0, 1]]);
    const storage = storageOf(wrote ? { initial: { [KEY]: FIRST } } : {});
    const { spoken } = mount({ text: wrote ? FIRST : null, storage });
    if (!wrote) check(true);
    expect(box().checked).toBe(true);
    storage.data.set(KEY, theirs); // (the other tab erased the copy and then wrote its own, before this tab handled the event of the erase)
    const calls = storage.calls.length;
    erased();
    expect(storage.data.get(KEY), "the copy of the other tab stays").toBe(theirs);
    expect(storage.calls.slice(calls).filter(([what]) => what !== "get"), "and nothing is written or removed").toEqual([]);
    expect(box().checked).toBe(false);
    expect(noteText()).toBe(WORDS);
    expect(spoken.at(-1)).toBe(WORDS);
    addByName("corbel cap", "0");
    expect(storage.data.get(KEY), "this tab writes no more").toBe(theirs);
  });

  it("takes nothing out when the key is not there at the event: the usual erase is one read of the key and no removal", () => {
    const storage = storageOf({ initial: { [KEY]: FIRST } });
    mount({ text: FIRST, storage });
    storage.data.delete(KEY);
    const calls = storage.calls.length;
    erased();
    expect(storage.calls.slice(calls)).toEqual([["get", KEY]]);
  });

  it("is set off all the same when the key cannot be read at the event or cannot be taken out: nothing is thrown, and the line says so", () => {
    for (const failing of ["get", "remove"]) {
      document.body.innerHTML = "";
      const storage = storageOf({ initial: { [KEY]: FIRST } });
      const { spoken } = mount({ text: FIRST, storage });
      storage.data.delete(KEY);
      addByName("corbel cap", "0"); // (this tab's late write)
      storage.fail.add(failing);
      expect(() => erased(), failing).not.toThrow();
      expect(box().checked, failing).toBe(false);
      expect(noteText(), failing).toBe(WORDS);
      expect(spoken.at(-1), failing).toBe(WORDS);
    }
  });
});

// ---- the code ----------------------------------------------------------------------------------------------------------------------------------------

describe("the code of the box", () => {
  const source = () => readFileSync(resolve(STATIC, "ui/remember.js"), "utf8");

  it("has no way to turn text into markup, a pattern or an address, sends nothing, and uses nothing that Safari 15 lacks", () => {
    const forbidden = [
      /\bRegExp\b/, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|createContextualFragment|DOMParser|srcdoc/, /\beval\s*\(|new\s+Function|setTimeout\(\s*["'`]/,
      /document\.cookie|navigator\.sendBeacon|sendBeacon|XMLHttpRequest|WebSocket|\bfetch\s*\(/, /createObjectURL|new\s+Blob|FileReader|window\.open|\.href\s*=|location\./,
      /Object\.hasOwn\b|\.at\(|\bfindLast\b|structuredClone|toSorted|toReversed|\.with\(/,
    ];
    for (const pattern of forbidden) expect(source(), String(pattern)).not.toMatch(pattern);
  });

  it("reaches the device through the storage it is given and nowhere else, and calls it in a try", () => {
    expect(source()).not.toMatch(/localStorage|sessionStorage|indexedDB/);
    const code = source().replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    const calls = [...code.matchAll(/\bstorage\??\.(getItem|setItem|removeItem)\(/g)];
    expect(calls.length).toBeGreaterThanOrEqual(2);
    expect(code.match(/\btry \{/g).length, "each call to the device has a try of its own").toBeGreaterThanOrEqual(calls.length);
  });

  it("does not import the modules the page script imports", () => {
    expect(source()).not.toMatch(/from\s+["']\.\.\/(?:format|trio|first|app|theme)\.js["']/);
  });
});
