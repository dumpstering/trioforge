// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// The Share button of Equip now: it builds the link of the kit Equip now shows (the trio page's own address and `#k=` and the codec's canonical text of the kit), copies it on the
// visitor's click, shows it in a read-only field when the browser will not copy, leaves out and says what cannot be in a link, and never puts the owned list in it. The answer is the
// one of the other tests of the section (a stand-in for the optimizer's client, a table of invented items). Every name is invented.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { encodeKit } from "../pipeline/trioforge/site/static/input/kitcode.js";
import { decodeKit } from "../pipeline/trioforge/site/static/input/kitdecode.js";
import { $, $$, STATIC } from "./upgrade-helpers.mjs";
import { VIEW, addByName, equipStep, flush, kitOf, mountAnswer, table } from "./upgrade-answer-helpers.mjs";

afterEach(() => {
  vi.useRealTimers();
  delete window.navigator.clipboard;
  window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
  document.body.innerHTML = "";
});

const TABLE = table();
const BASE = "https://trioforge.test/trio/pal-mnk-ber/";
const sent = (t, count) => vi.waitFor(() => expect(t.engine.runs).toHaveLength(count), { timeout: 5000, interval: 5 });

/** The clipboard of the browser: `writeText` copies, or refuses (the way a browser without the permission does), or the browser has none. */
function clipboard(how = "copies") {
  if (how === "none") return null;
  const writeText = vi.fn(async () => {
    if (how === "refuses") throw new DOMException("not allowed", "NotAllowedError");
    if (how === "throws") throw new TypeError("no document focus");
  });
  Object.defineProperty(window.navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
}

/** The section with the gear of the first test item and Equip now drawn as `places` says: `{index: ident}`. */
async function withEquipNow(places = { 11: "w80301@4", 4: "w80303@0", 15: "w80306@0" }, options = {}) {
  const t = mountAnswer({ pauseMs: 0, ...options });
  addByName("tarn signet", "4");
  await sent(t, 1);
  const run = t.engine.runs[0];
  run.onStep(equipStep({ kit: kitOf(places) }));
  await flush();
  return { ...t, run };
}

const button = () => $("#upgrade-share-button");
const payloadOf = (link) => link.slice(link.indexOf("#k=") + 3);
const slotsOf = (link) => decodeKit(payloadOf(link), TABLE.records).kit.slots.map(({ slotIndex, pageId, tier }) => [slotIndex, pageId, tier]);

describe("the Share button of Equip now", () => {
  it("is in Equip now once it shows a kit, with the words that say what the link holds, and not before", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    expect(button()).not.toBeNull();
    expect(button().closest("#upgrade-equip")).not.toBeNull();
    expect(button().closest("[hidden]")).not.toBeNull(); // (Equip now is not drawn yet)
    addByName("tarn signet", "4");
    await sent(t, 1);
    expect(button().closest("[hidden]")).not.toBeNull(); // (a request is on its way, and no answer yet)
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    await flush();
    expect(button().closest("[hidden]")).toBeNull();
    expect(button().textContent).toBe("Share this kit");
    expect(button().tagName).toBe("BUTTON");
    expect(button().type).toBe("button");
    expect($("#upgrade-share-words").textContent).toBe("This link lists the items in this kit.");
    expect(button().getAttribute("aria-describedby")).toBe("upgrade-share-words");
  });

  it("is not there when Equip now found no kit, or a kit with nothing in it", async () => {
    const none = await withEquipNow({});
    expect(button().closest("[hidden]")).not.toBeNull();
    none.run.onStep(equipStep({ kit: null, status: "time_limit", proven: false, label: "not found in time" }));
    await flush();
    expect(button().closest("[hidden]")).not.toBeNull();
  });

  it("copies the link of the kit Equip now shows, on the click: the trio page's address, #k= and the canonical text of the kit", async () => {
    const writeText = clipboard();
    const t = await withEquipNow();
    expect(writeText, "nothing is copied until the visitor asks").not.toHaveBeenCalled();
    button().click();
    await flush();
    expect(writeText).toHaveBeenCalledTimes(1);
    const link = writeText.mock.calls[0][0];
    const payload = encodeKit({ v: 1, trio: "pal-mnk-ber", race: VIEW.race, level: 50, slots: [[4, 80303, 0], [11, 80301, 4], [15, 80306, 0]] });
    expect(link).toBe(`${BASE}#k=${payload}`);
    // the round trip: what the link names is the kit, place by place, and the text is the canonical one
    const decoded = decodeKit(payloadOf(link), TABLE.records);
    expect(decoded.errors).toEqual([]);
    expect(decoded.kit).toMatchObject({ v: 1, trio: "pal-mnk-ber", race: VIEW.race, level: 50 });
    expect(decoded.kit.slots.map((slot) => [slot.slotIndex, slot.key, slot.tier])).toEqual([[4, "w80303", 0], [11, "w80301", 4], [15, "w80306", 0]]);
    expect(encodeKit(decoded.kit)).toBe(payloadOf(link));
    expect(t.spoken.at(-1)).toMatch(/^Link copied\./);
    expect($("#upgrade-share-result").textContent).toMatch(/^Link copied/);
    expect($("#upgrade-share-field").hidden).toBe(true);
  });

  it("names the race of the answer that was asked for, not the one the page shows now", async () => {
    const writeText = clipboard();
    const t = await withEquipNow();
    t.setView({ race: "TRL" }); // (the page shows another race now, and the answer on the page is still for the first)
    button().click();
    await flush();
    expect(decodeKit(payloadOf(writeText.mock.calls[0][0]), TABLE.records).kit.race).toBe(VIEW.race);
  });

  it("makes a link of the page's own address: no query, no fragment of the page's", async () => {
    window.history.replaceState(null, "", "/trio/pal-mnk-ber/?race=OGR&role=tank#robust");
    const writeText = clipboard();
    await withEquipNow();
    button().click();
    await flush();
    expect(writeText.mock.calls[0][0].startsWith(`${BASE}#k=`)).toBe(true);
  });

  it("never holds the owned list: the same kit gives the same link whatever else is owned", async () => {
    const writeText = clipboard();
    const t = await withEquipNow();
    button().click();
    await flush();
    const first = writeText.mock.calls[0][0];
    for (const name of ["corbel cap", "dunmere helm", "fenwick greaves"]) addByName(name, "0");
    await sent(t, 2); // (the new gear sends a new request; Equip now of the old answer is gone with it)
    t.engine.runs[1].onStep(equipStep({ kit: kitOf({ 11: "w80301@4", 4: "w80303@0", 15: "w80306@0" }) }));
    await flush();
    button().click();
    await flush();
    expect(writeText.mock.calls.at(-1)[0]).toBe(first);
    // and nothing in it but the places of the kit: the payload is the 12 bytes of the header and the three triples, in base64url
    expect(payloadOf(first)).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(slotsOf(first)).toHaveLength(3);
    expect(first.length).toBeLessThan(BASE.length + 3 + 40);
  });

  it("copes with a kit worn twice: two places, one item", async () => {
    const writeText = clipboard();
    await withEquipNow({ 11: "w80301@4", 12: "w80301@4" });
    button().click();
    await flush();
    expect(slotsOf(writeText.mock.calls[0][0])).toEqual([[11, 80301, 4], [12, 80301, 4]]);
  });

  it("keeps the focus on the button", async () => {
    clipboard();
    await withEquipNow();
    button().focus();
    button().click();
    await flush();
    expect(document.activeElement).toBe(button());
  });

  it("says the result through the page's live region and has no live region of its own", async () => {
    clipboard();
    const t = await withEquipNow();
    const before = t.spoken.length;
    button().click();
    await flush();
    expect(t.spoken.length).toBe(before + 1);
    expect($$('#upgrade-share [role="status"], #upgrade-share [role="alert"], #upgrade-share [aria-live]')).toHaveLength(0);
  });
});

describe("when the browser will not copy", () => {
  for (const how of ["refuses", "throws", "none"]) {
    it(`shows the link in a read-only field, selected, with the words to copy it from there: the clipboard ${how}`, async () => {
      const writeText = clipboard(how);
      const t = await withEquipNow();
      button().focus();
      button().click();
      await flush();
      const field = $("#upgrade-share-link");
      expect($("#upgrade-share-field").hidden).toBe(false);
      expect(field.readOnly).toBe(true);
      expect(field.type).toBe("text");
      expect(field.value.startsWith(`${BASE}#k=`)).toBe(true);
      expect(slotsOf(field.value)).toEqual([[4, 80303, 0], [11, 80301, 4], [15, 80306, 0]]);
      expect(field.selectionStart).toBe(0);
      expect(field.selectionEnd).toBe(field.value.length);
      expect($('label[for="upgrade-share-link"]').textContent).toBe("Copy the link from here");
      expect($("#upgrade-share-result").textContent).toMatch(/would not copy/);
      expect(t.spoken.at(-1)).toMatch(/would not copy/);
      expect(document.activeElement, "the focus stays on the button").toBe(button());
      if (writeText) expect(writeText).toHaveBeenCalledTimes(1);
    });
  }

  it("hides the field again when the next click copies", async () => {
    const t = await withEquipNow();
    clipboard("refuses");
    button().click();
    await flush();
    expect($("#upgrade-share-field").hidden).toBe(false);
    clipboard("copies");
    button().click();
    await flush();
    expect($("#upgrade-share-field").hidden).toBe(true);
    expect(t.spoken.at(-1)).toMatch(/^Link copied\./);
  });
});

describe("what cannot be in a link", () => {
  it("is an item whose key is not w and a number: it is left out, and the visitor is told how many", async () => {
    const writeText = clipboard();
    const t = await withEquipNow({ 11: "w80301@4", 4: "q77@2", 16: "w012@0", 5: "w2147483648@1", 14: "w80308@0" });
    button().click();
    await flush();
    expect(slotsOf(writeText.mock.calls[0][0])).toEqual([[11, 80301, 4], [14, 80308, 0]]);
    expect($("#upgrade-share-left").textContent).toBe("3 items of this kit cannot be shared");
    expect(t.spoken.at(-1)).toMatch(/3 items of this kit cannot be shared/);
  });

  it("says it for one item in the singular", async () => {
    clipboard();
    await withEquipNow({ 11: "w80301@4", 4: "q77@2" });
    button().click();
    await flush();
    expect($("#upgrade-share-left").textContent).toBe("1 item of this kit cannot be shared");
  });

  it("says nothing when every item can", async () => {
    clipboard();
    await withEquipNow();
    button().click();
    await flush();
    expect($("#upgrade-share-left").hidden).toBe(true);
  });

  it("copies nothing when no item can be in a link, and says so", async () => {
    const writeText = clipboard();
    const t = await withEquipNow({ 4: "q77@2" });
    button().click();
    await flush();
    expect(writeText).not.toHaveBeenCalled();
    expect($("#upgrade-share-result").textContent).toBe("Nothing in this kit can be shared.");
    expect(t.spoken.at(-1)).toMatch(/Nothing in this kit can be shared/);
  });
});

describe("a new answer", () => {
  it("clears what the last click said and shows: the result, the field and the note", async () => {
    clipboard("refuses");
    const t = await withEquipNow({ 11: "w80301@4", 4: "q77@2" });
    button().click();
    await flush();
    expect($("#upgrade-share-field").hidden).toBe(false);
    addByName("corbel cap", "0");
    await sent(t, 2);
    expect($("#upgrade-share-field").hidden).toBe(true);
    expect($("#upgrade-share-result").hidden).toBe(true);
    expect($("#upgrade-share-left").hidden).toBe(true);
    expect(button().closest("[hidden]")).not.toBeNull();
  });

  it("is not told that the link was copied by a copy that finished after the answer changed", async () => {
    let finish;
    const writeText = vi.fn(() => new Promise((resolve) => (finish = resolve)));
    Object.defineProperty(window.navigator, "clipboard", { value: { writeText }, configurable: true });
    const t = await withEquipNow();
    button().click();
    addByName("corbel cap", "0");
    await sent(t, 2);
    const spoken = t.spoken.length;
    finish();
    await flush();
    expect(t.spoken.length).toBe(spoken);
    expect($("#upgrade-share-result").hidden).toBe(true);
  });
});

describe("the code of the Share button", () => {
  const source = () => readFileSync(resolve(STATIC, "ui/share.js"), "utf8");

  it("has no way to turn text into markup, a pattern or an address, stores nothing, sends nothing, and uses nothing that Safari 15 lacks", () => {
    const forbidden = [
      /\bRegExp\b/, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|createContextualFragment|DOMParser|srcdoc/, /\beval\s*\(|new\s+Function|setTimeout\(\s*["'`]/,
      /localStorage|sessionStorage|indexedDB|document\.cookie|navigator\.sendBeacon|sendBeacon|XMLHttpRequest|WebSocket|\bfetch\s*\(/,
      /createObjectURL|new\s+Blob|FileReader|window\.open|\.href\s*=|location\.(?:assign|replace)|\bsetAttribute\(\s*["'](?:href|src|on)/,
      /Object\.hasOwn\b|\.at\(|\bfindLast\b|structuredClone|toSorted|toReversed|\.with\(/,
    ];
    for (const pattern of forbidden) expect(source(), String(pattern)).not.toMatch(pattern);
  });

  it("does not import the modules the page script imports, nor the optimizer's client", () => {
    expect(source()).not.toMatch(/from\s+["']\.\.\/(?:format|trio|first|app|theme)\.js["']/);
    expect(source()).not.toMatch(/from\s+["']\.\.\/engine\/client\.js["']/);
  });

  it("selects the link with a range and not with select(), which takes the focus to the field in some browsers", () => {
    expect(source()).not.toMatch(/\.select\(\)/);
    expect(source()).toMatch(/\.setSelectionRange\(0, /);
  });

  it("writes to the clipboard in one place, and that place is the click of the button", () => {
    expect(source().match(/writeText\(/g)).toHaveLength(1);
    const writes = source().indexOf("writeText(");
    const click = source().lastIndexOf('addEventListener("click"', writes);
    expect(click, "the write is after the listener of the click").toBeGreaterThan(-1);
  });
});

describe("the Share button of Equip now, for the Bow setup", () => {
  const BOW_PLACES = { 11: "w80301@4", 4: "w80303@0", 15: "w80306@0", 17: "w80307@0" };
  async function shared(setup, places = BOW_PLACES) {
    const writeText = clipboard();
    const t = mountAnswer({ pauseMs: 0 });
    t.setView({ setup }); // (the page shows this weapon setup when Equip now is asked for)
    addByName("tarn signet", "4");
    await sent(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf(places) }));
    await flush();
    button().click();
    await flush();
    return payloadOf(writeText.mock.calls[0][0]);
  }

  it("carries the marker of the Bow setup in the link of a kit that Equip now made for it", async () => {
    const payload = await shared("ranged");
    const decoded = decodeKit(payload, TABLE.records);
    expect(decoded.errors).toEqual([]);
    expect(decoded.kit.setup).toBe("ranged");
    expect(payload).toBe(encodeKit({ v: 1, trio: "pal-mnk-ber", race: VIEW.race, level: 50, slots: decoded.kit.slots.map((s) => [s.slotIndex, s.pageId, s.tier]), setup: "ranged" }));
  });

  it("carries none for any other setup: the link is the old link, byte for byte", async () => {
    for (const setup of ["dw", "2h", "1h-shield", "stick"]) {
      const payload = await shared(setup, { 11: "w80301@4", 4: "w80303@0", 15: "w80306@0" });
      expect(payload, setup).toBe(encodeKit({ v: 1, trio: "pal-mnk-ber", race: VIEW.race, level: 50, slots: [[4, 80303, 0], [11, 80301, 4], [15, 80306, 0]] }));
      expect(decodeKit(payload, TABLE.records).kit.setup, setup).toBeUndefined();
      document.body.replaceChildren();
    }
  });
});
