// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// A kit that came in a link: the page code takes it out of the address, the code of the Upgrade section (loaded at the start for it) fetches the item list, decodes the kit and
// shows it at the top of the answer area, before "Wear this", with the page's own words and a placeholder for every item the list does not have; and it works out the kit's value
// with the engine's evaluator, in the page: the bundle of the trio is fetched by the manifest's path and SHA-256, the optimizer is not asked for (no worker, no download, no question).
// The value is the kit's own under the role, buffs and evidence level the page shows: the weapon setup is read from the kit's hands and the haste is the model's rule for the kit's items,
// so neither follows the page's weapon switch or tier switch, and the numbers are those Python's reference gives (fixtures/site/kit-values.json). Run against the contract copy of the
// trio page, the page code, the real code of the section and the fake site of the engine tests, whose item table and bundle are the fixture's. Every name is invented.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as pause } from "node:timers/promises";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadKitBundle, valueOfKit } from "../pipeline/trioforge/site/static/engine/kitvalue.js";
import { STARTUP_COMPILE_MS, STARTUP_STALL_MS } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { displayInt, fmtInt } from "../pipeline/trioforge/site/static/format.js";
import { encodeKit } from "../pipeline/trioforge/site/static/input/kitcode.js";
import { decodeKit } from "../pipeline/trioforge/site/static/input/kitdecode.js";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";
import * as sectionCode from "../pipeline/trioforge/site/static/ui/upgrade-input.js";
import { BUNDLE_BYTES, ITEMS_BYTES, makeSite, sha256, siteFetch } from "./engine-site-fixture.mjs";
import { $, $$, mountPage } from "./upgrade-helpers.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract");
const MAIN = "/engine-manifest.json";
/** The evaluator's own script, as the manifest lists it: the page fetches it, checks its SHA-256 and only then imports it (a stand-in does here: the test gives the module). */
const KITVALUE_PATH = "/assets/engine/kitvalue-AAAAAAAA.js";
const KITVALUE_BYTES = new TextEncoder().encode("export const evaluator = true;\n");
const script = (bytes) => new Response(bytes, { status: 200, headers: { "content-type": "text/javascript; charset=utf-8" } });
const BUNDLE = JSON.parse(BUNDLE_BYTES.toString("utf8"));
const TABLE_JSON = JSON.parse(ITEMS_BYTES.toString("utf8"));
const RECORDS = readItemTable(structuredClone(TABLE_JSON)).records;
const NAMES = new Map(TABLE_JSON.items.map((item) => [item.id, item.name]));
const KIT_VALUES = JSON.parse(readFileSync(resolve(HERE, "../fixtures/site/kit-values.json"), "utf8"));
/** A kit of the fixture as a link carries it: [place, page id, tier] for each place that holds an item. */
const slotsOfKit = (kit) => kit.kit.flatMap((ident, slot) => (ident === null ? [] : [[slot, Number(ident.slice(1, ident.indexOf("@"))), Number(ident.slice(ident.indexOf("@") + 1))]]));
/** What the page writes for the value that Python's reference gave. */
const written = (row) => fmtInt(displayInt(row.value));

// the Equip now kit of the first scenario the Python reference solved, for an Ogre: [place, page id, tier]
const KIT_SLOTS = [[0, 90001, 4], [1, 90006, 4], [2, 90007, 4], [3, 90009, 4], [4, 90011, 4], [5, 90013, 4], [6, 90014, 4], [10, 90023, 4], [13, 90029, 10], [14, 90030, 4], [20, 80923, 4], [21, 80113, 0]];
const kitOf = (over = {}) => ({ v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: KIT_SLOTS, ...over });
const link = (over) => encodeKit(kitOf(over));
const fromLink = (payload, source = "fragment") => ({ payload, source, cleared: source === "fragment" });

const dataFile = (name) => JSON.parse(readFileSync(resolve(CONTRACT, `data/${name}.json`), "utf8"));
/** The shards of the page (what a switch fetches) are asked for by a path of the page; the engine's files are the fake site's. */
const serveShards = (url) => {
  if (!String(url).startsWith("/data/pal-mnk-ber/")) return undefined;
  const name = String(url).replace("/data/pal-mnk-ber/", "").replace(".json", "");
  return new Response(JSON.stringify(dataFile(name)), { status: 200, headers: { "content-type": "application/json" } });
};

afterEach(() => {
  vi.restoreAllMocks();
  delete window.navigator.clipboard;
  window.localStorage.clear();
  window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
  document.body.replaceChildren();
});

/** The page code on the contract page with a kit that came in the address. `delay(path)` may give a promise that a request waits for; `serve` answers for a path instead. */
function open(kit, { ev, made = makeSite(), delay, serve, loadEngine = async () => ({ valueOfKit, loadKitBundle }), release, evaluator = KITVALUE_BYTES, listed = true, loadShared, env } = {}) {
  mountPage();
  if (ev !== undefined) document.getElementById("main").dataset.ev = ev; // (the one evidence level the page is made from: there is no switch for it)
  if (release !== undefined) document.getElementById("main").dataset.release = release;
  if (listed) made.manifestJson.kitvalue = { path: KITVALUE_PATH, bytes: KITVALUE_BYTES.length, gzip: 20, sha256: sha256(KITVALUE_BYTES) };
  if (!made.files.has(MAIN)) made.files.set(MAIN, new TextEncoder().encode(JSON.stringify(made.manifestJson))); // (the fake site of the engine tests serves the data files and the manifests of the trios)
  const served = (url) => (new URL(url, "https://trioforge.test").pathname === KITVALUE_PATH ? script(evaluator) : undefined);
  const net = siteFetch(made, { serve: (url, init) => serve?.(String(url), init) ?? served(String(url)) ?? serveShards(url) });
  const fetchImpl = delay
    ? async (url, init) => {
        const wait = delay(String(url).startsWith("/") ? String(url) : new URL(url).pathname);
        if (wait) await wait;
        return net.fetchImpl(url, init);
      }
    : net.fetchImpl;
  const reload = vi.fn();
  const engine = vi.fn(loadEngine); // (the client file of the manifest, which has the evaluator: here the evaluator itself, without the optimizer)
  // the code of the panel is loaded by the section, by a dynamic import: a test may give another (a counting one, one that fails or waits), and `env` adds to what the section is started with (its limits of time)
  const loadUpgrade =
    loadShared === undefined && env === undefined ? undefined : async () => ({ initUpgrade: (root, given) => sectionCode.initUpgrade(root, { ...given, ...(loadShared === undefined ? {} : { loadShared }), ...env }) });
  const app = initTrio({ document, window, fetch: fetchImpl, reload, loadEngine: engine, kit, ...(loadUpgrade === undefined ? {} : { loadUpgrade }) });
  return { app, net, made, reload, engine };
}

/** Until the kit is drawn and its value, or the reason for none, is there. */
const WORKING = ["Loading the shared kit…", "Working out its value…"];
/** What the page and the section say when the code of the panel could not be had, or could not make the panel. */
const CODE_FAILED = "Couldn't load the shared kit. Reload the page to try again.";
/** What the panel says when the import of the evaluator ran past its time. */
const VALUE_RELOAD = "The value could not be worked out here. Reload the page to try again.";
async function settled(app) {
  await vi.waitFor(() => expect($("#shared-kit")).not.toBeNull(), { timeout: 5000, interval: 10 });
  await app.whenIdle();
  await vi.waitFor(() => expect(WORKING).not.toContain(text("#shared-kit-state")), { timeout: 5000, interval: 10 });
  await app.whenIdle();
}
const said = () => text("#shared-kit-state .status-text");
const text = (selector) => ($(selector)?.textContent ?? "").replace(/\s+/g, " ").trim();
const rows = () => $$("#shared-kit-table tbody tr").map((tr) => [tr.querySelector("th").textContent, tr.querySelector("td").textContent.replace(/\s+/g, " ").trim()]);
const asked = (net) => net.asked.map((url) => (String(url).startsWith("/") ? String(url) : new URL(url).pathname));

/** The number in the panel's value line ("Kit value 16,267 for ..." or "Kit value at least 16,267 for ..."), as the page wrote it. */
const numberShown = () => /^Kit value (?:at least )?([\d,]+) for/.exec(text("#shared-kit-value"))?.[1] ?? null;
const choose = (selector) => {
  const radio = $(selector);
  radio.checked = true;
  radio.dispatchEvent(new Event("change", { bubbles: true }));
};
/** The page shows the view of a row of the reference (the role and the buffs; the evidence level is the one the page was opened with, `open(..., { ev: kit.evidence })`), and the panel has worked the kit out again for it. */
async function showView(app, row, kit) {
  choose(`input[name="role"][value="${row.role}"]`);
  choose(`input[name="buffs"][value="${row.buffs}"]`);
  await app.whenIdle();
  expect(app.valueView()).toEqual({ role: row.role, buffs: row.buffs, evidence: kit.evidence });
}

describe("a kit that came in a link", () => {
  it("is shown at the top of the answer area, before Wear this, under the heading A kit shared with you, and says that it is a shared kit", async () => {
    const { app } = open(fromLink(link()));
    await settled(app);
    const panel = $("#shared-kit");
    expect(panel.tagName).toBe("SECTION");
    expect($("#shared-kit-h").textContent).toBe("A kit shared with you");
    expect($("#shared-kit-h").tagName).toBe("H2");
    expect(panel.getAttribute("aria-labelledby")).toBe("shared-kit-h");
    expect(panel.nextElementSibling, "right before the answer area").toBe($("section.answer"));
    expect(panel.compareDocumentPosition($("#wear-h")) & Node.DOCUMENT_POSITION_FOLLOWING, "and so before Wear this").toBeTruthy();
    expect(text("#shared-kit-lead")).toMatch(/shared kit/i);
  });

  it("is shown for a payload that a reload kept in the history entry too", async () => {
    const { app } = open(fromLink(link(), "state"));
    await settled(app);
    expect(text("#shared-kit-h")).toBe("A kit shared with you");
    expect(rows()).toHaveLength(22);
  });

  it("is not shown when there is no kit link", async () => {
    const { app } = open({ payload: null, source: null, cleared: false });
    await app.whenIdle();
    expect($("#shared-kit")).toBeNull();
  });

  it("is drawn in the page's words: the places of the kit table, the item names with their tiers, and the page's words for a place left empty", async () => {
    const { app } = open(fromLink(link()));
    await settled(app);
    const places = $$("#kit-body tr th").map((th) => th.textContent);
    const drawn = rows();
    expect(drawn).toHaveLength(22);
    expect(drawn.map(([place]) => place)).toEqual(places);
    const want = new Map(KIT_SLOTS.map(([slotIndex, id, tier]) => [slotIndex, `${NAMES.get(id)} +${tier}`]));
    drawn.forEach(([, item], slotIndex) => expect(item, places[slotIndex]).toBe(want.get(slotIndex) ?? "Leave empty"));
    expect($("#shared-kit-table caption").textContent).toMatch(/shared kit/i);
    expect($$("#shared-kit-table th[scope]").length).toBeGreaterThan(22);
  });

  it("shows a placeholder, with the page id and the tier, for an item that the item list does not have, and does not count it", async () => {
    const { app } = open(fromLink(link({ slots: [...KIT_SLOTS, [11, 12345, 3]] })));
    await settled(app);
    expect(rows()[11][1]).toBe("Unknown item (w12345) +3");
    expect($$("#shared-kit-table tbody tr")[11].querySelector(".muted")).not.toBeNull();
    expect(text("#shared-kit-value")).toMatch(/Excludes 1 unknown item\.$/);
    const withUnknown = numberShown();
    document.body.replaceChildren();
    const alone = open(fromLink(link()));
    await settled(alone.app);
    expect(withUnknown, "the value of the other items").toBe(numberShown());
    for (const count of [2, 3]) {
      document.body.replaceChildren();
      const again = open(fromLink(link({ slots: [...KIT_SLOTS, [11, 12345, 3], [12, 12346, 0], [15, 12347, 1]].slice(0, KIT_SLOTS.length + count) })));
      await settled(again.app);
      expect(text("#shared-kit-value")).toMatch(new RegExp(`Excludes ${count} unknown items\\.$`));
    }
  });

  it("is drawn as text: a name with markup in it is shown as it is written", async () => {
    const hostile = structuredClone(TABLE_JSON);
    hostile.items.find((item) => item.id === 90001).name = 'Helm <img src="x" onerror="alert(1)"> of <b>Shadows</b>';
    const { app } = open(fromLink(link()), { made: makeSite({ items: new TextEncoder().encode(JSON.stringify(hostile)) }) });
    await settled(app);
    expect(rows()[0][1]).toBe('Helm <img src="x" onerror="alert(1)"> of <b>Shadows</b> +4');
    expect($$("#shared-kit img, #shared-kit b, #shared-kit script, #shared-kit a")).toHaveLength(0);
  });

  it("does not move the focus", async () => {
    const { app } = open(fromLink(link()));
    $("#sw-race").focus();
    await settled(app);
    expect(document.activeElement).toBe($("#sw-race"));
  });
});

describe("the value of a shared kit", () => {
  // the rows of the reference that the page's switches can show: the page offers the buffs own and group, every role, and both evidence levels; it has no deity, so the kit of a follower is left
  const KITS = KIT_VALUES.kits;
  const reachable = KIT_VALUES.values.filter((row) => ["own", "group"].includes(row.buffs) && KITS[row.kit].deity === null);
  const SETUP_WORDS = { dw: "dual wield", "1h-shield": "1H + shield", "2h": "two-hander", stick: "stat stick" };
  const ROLE_WORDS = { balanced: "Balanced", tank: "Tank", melee: "Melee" };
  const RACE_WORDS = { OGR: "Ogre", TRL: "Troll", IKS: "IKS", HUM: "HUM" }; // (the contract copy of the page lists three races; the page shows the code of one it does not list)
  const BUFF_WORDS = { own: "your own buffs", group: "common group buffs" };
  const sentence = (kit, row) =>
    `Kit value ${written(row)} for ${RACE_WORDS[kit.race]}, ${ROLE_WORDS[row.role]}, ${BUFF_WORDS[row.buffs]}. Weapons: ${SETUP_WORDS[kit.setup]}, read from the kit's hands, at ${row.hasteAssumed}% haste.`;

  it.each(reachable.map((row) => [`${KITS[row.kit].name} / ${row.role} / ${row.buffs}`, row]))(
    "is what Python's reference says for the kit, under the role, buffs and evidence level the page shows, and says the setup of the kit's hands and the haste: %s",
    async (_, row) => {
      const kit = KITS[row.kit];
      const { app } = open(fromLink(link({ race: kit.race, slots: slotsOfKit(kit) })), { ev: kit.evidence });
      await settled(app);
      await showView(app, row, kit);
      await vi.waitFor(() => expect(text("#shared-kit-value")).toBe(sentence(kit, row)), { timeout: 5000, interval: 10 });
    },
  );

  it("is the kit's own whatever weapon setup the page shows and whatever tier it shows, which move the haste the page's own answer is scored at", async () => {
    const kit = KITS[0];
    const row = KIT_VALUES.values.find((one) => one.kit === 0 && one.role === "balanced" && one.buffs === "own");
    const { app } = open(fromLink(link({ race: kit.race, slots: slotsOfKit(kit) })), { ev: kit.evidence });
    await settled(app);
    await showView(app, row, kit);
    await vi.waitFor(() => expect(text("#shared-kit-value")).toBe(sentence(kit, row)), { timeout: 5000, interval: 10 });
    const hastes = new Set([text('[data-f="assume-haste"]')]);
    for (const setup of ["2h", "dw", "1h-shield"]) {
      const radio = $(`input[name="setup"][value="${setup}"]`);
      if (radio === null || radio.disabled) continue;
      choose(`input[name="setup"][value="${setup}"]`);
      await app.whenIdle();
      hastes.add(text('[data-f="assume-haste"]'));
      expect(text("#shared-kit-value"), `the page shows ${setup}`).toBe(sentence(kit, row));
    }
    for (const tier of [...$("#sw-tier").options].map((option) => option.value)) {
      $("#sw-tier").value = tier;
      $("#sw-tier").dispatchEvent(new Event("change", { bubbles: true }));
      await app.whenIdle();
      hastes.add(text('[data-f="assume-haste"]'));
      expect(text("#shared-kit-value"), `the page shows tier ${tier}`).toBe(sentence(kit, row));
    }
    expect(hastes.size, "the haste of the page's own answer did move").toBeGreaterThan(1);
  });

  it("is worked out for the race of the kit, not the race the page shows", async () => {
    const kit = KITS[0];
    const { app } = open(fromLink(link({ race: "TRL", slots: slotsOfKit(kit) })), { ev: "wiki" });
    await settled(app);
    await vi.waitFor(() => expect(text("#shared-kit-value")).toMatch(/^Kit value [\d,]+ for Troll, Balanced, your own buffs\./), { timeout: 5000, interval: 10 });
    const asTroll = numberShown();
    document.body.replaceChildren();
    const again = open(fromLink(link({ race: "OGR", slots: slotsOfKit(kit) })), { ev: "wiki" });
    await settled(again.app);
    await vi.waitFor(() => expect(text("#shared-kit-value")).toMatch(/^Kit value [\d,]+ for Ogre/), { timeout: 5000, interval: 10 });
    expect(numberShown(), "an Ogre and a Troll are different characters").not.toBe(asTroll);
  });

  it("changes with the role switch, and with the buffs, and each is the reference's number for that view", async () => {
    const kit = KITS[0];
    const rowOf = (role, buffs) => KIT_VALUES.values.find((one) => one.kit === 0 && one.role === role && one.buffs === buffs);
    const { app } = open(fromLink(link({ race: kit.race, slots: slotsOfKit(kit) })), { ev: kit.evidence });
    await settled(app);
    const seen = [];
    for (const [role, buffs] of [["balanced", "own"], ["melee", "own"], ["melee", "group"], ["balanced", "group"]]) {
      await showView(app, rowOf(role, buffs), kit);
      await vi.waitFor(() => expect(text("#shared-kit-value")).toBe(sentence(kit, rowOf(role, buffs))), { timeout: 5000, interval: 10 });
      seen.push(numberShown());
    }
    expect(new Set(seen).size).toBe(4);
  });

  it("says that the value is at least what it says when the search for the best buffs ran out of its calls", async () => {
    const kit = KITS[0];
    const row = KIT_VALUES.values.find((one) => one.kit === 0 && one.role === "balanced" && one.buffs === "own");
    const lowerBound = async () => ({ valueOfKit: (args) => ({ ...valueOfKit(args), exact: false }), loadKitBundle });
    const { app } = open(fromLink(link({ race: kit.race, slots: slotsOfKit(kit) })), { loadEngine: lowerBound, ev: kit.evidence });
    const aloud = [];
    new MutationObserver(() => aloud.push($("#announce").textContent)).observe($("#announce"), { childList: true, characterData: true, subtree: true });
    await settled(app);
    await showView(app, row, kit);
    await vi.waitFor(
      () =>
        expect(text("#shared-kit-value")).toBe(
          `Kit value at least ${written(row)} for Ogre, Balanced, your own buffs. Weapons: dual wield, read from the kit's hands, at ${row.hasteAssumed}% haste. The best buffs were not searched out completely, so the kit may be worth more.`,
        ),
      { timeout: 5000, interval: 10 },
    );
    expect(aloud.filter((line) => line.startsWith("A kit shared with you")), "said once, as a lower bound").toHaveLength(1);
    expect(aloud.find((line) => line.startsWith("A kit shared with you"))).toMatch(/^A kit shared with you\. Kit value at least [\d,]+\.$/);
  });

  it("words a stat stick without a haste: no weapon damage is scored, so there is nothing to say of it", async () => {
    const kit = KITS[0];
    const stick = async () => ({ valueOfKit: (args) => ({ ...valueOfKit(args), setup: "stick", hasteAssumed: 77 }), loadKitBundle });
    const { app } = open(fromLink(link({ race: kit.race, slots: slotsOfKit(kit) })), { loadEngine: stick });
    await settled(app);
    expect(text("#shared-kit-value")).toMatch(/^Kit value [\d,]+ for Ogre, Balanced, your own buffs\. Weapons: stat stick, read from the kit's hands\.$/);
  });

  it("leaves out an item that cannot be worn where the link puts it, says so in its row and in the value, and counts the others", async () => {
    const slots = KIT_SLOTS.map((slot) => (slot[0] === 6 ? [6, 90027, 4] : slot)); // (a ring in the Arms place)
    const { app } = open(fromLink(link({ slots })));
    await settled(app);
    expect(rows()[6][1]).toMatch(/^Signet of the Forgotten Court \+4/);
    expect($$("#shared-kit-table tbody tr")[6].querySelector(".owned-meta").textContent).toMatch(/does not fit this place/);
    expect(text("#shared-kit-value")).toMatch(/1 item cannot be worn where the link puts it and is not counted\.$/);
    const withRing = numberShown();
    document.body.replaceChildren();
    const without = open(fromLink(link({ slots: KIT_SLOTS.filter((slot) => slot[0] !== 6) })));
    await settled(without.app);
    expect(withRing, "the ring in the wrong place counts for nothing").toBe(numberShown());
  });

  it("says why an item in a hand is not counted: a two-hander takes both hands", async () => {
    const slots = [[0, 90001, 4], [20, 80524, 4], [21, 80113, 0]]; // a two-hander in the main hand, a one-hander in the off hand
    const { app } = open(fromLink(link({ slots })));
    await settled(app);
    expect($$("#shared-kit-table tbody tr")[21].querySelector(".owned-meta").textContent).toBe("Not counted: a two-hander takes both hands");
    expect(text("#shared-kit-value")).toMatch(/Weapons: two-hander, read from the kit's hands, at \d+% haste\. 1 item cannot be worn where the link puts it and is not counted\.$/);
  });

  it("asks nothing of the optimizer: no worker, no consent question and no download of it; the bundle of the trio comes by the path the manifests name, once", async () => {
    const { app, net, made, engine } = open(fromLink(link()));
    await settled(app);
    choose('input[name="role"][value="melee"]');
    await app.whenIdle();
    choose('input[name="role"][value="tank"]');
    await app.whenIdle();
    const paths = asked(net);
    expect(paths.filter((path) => path === made.bundlePath)).toHaveLength(1);
    expect(paths.filter((path) => path === made.trioPath)).toHaveLength(1);
    expect(paths.filter((path) => /\/assets\/engine\/(worker|highs)-/.test(path))).toEqual([]);
    expect(engine).toHaveBeenCalledTimes(1);
    expect(engine.mock.calls[0][0], "the evaluator, by the path the manifest lists for it").toBe(`https://trioforge.test${KITVALUE_PATH}`);
    expect(paths.filter((path) => path === KITVALUE_PATH), "fetched once, to be checked").toHaveLength(1);
    expect(paths.filter((path) => /\/assets\/engine\/(client|worker|highs)-/.test(path)), "and the optimizer's client is not asked for at all").toEqual([]);
    expect($(".engine-consent")).toBeNull();
  });

  it("is said once through the page's live region with the heading: A kit shared with you. Kit value N.", async () => {
    const { app } = open(fromLink(link()));
    const said = [];
    new MutationObserver(() => said.push($("#announce").textContent)).observe($("#announce"), { childList: true, characterData: true, subtree: true });
    await settled(app);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(said.filter((line) => line.startsWith("A kit shared with you"))).toEqual([`A kit shared with you. Kit value ${numberShown()}.`]);
    expect($$('#shared-kit [role="status"], #shared-kit [role="alert"], #shared-kit [aria-live]')).toHaveLength(0);
  });

  it("says that it could not be worked out, with a Try again, when the evaluator cannot be loaded, and works it out when the retry does", async () => {
    let fail = true;
    const { app, engine } = open(fromLink(link()), { loadEngine: async () => (fail ? Promise.reject(new Error("chunk")) : { valueOfKit, loadKitBundle }) });
    await settled(app);
    expect(rows()).toHaveLength(22); // (the kit is there whatever the value does)
    expect(text("#shared-kit-state")).toMatch(/^The value could not be worked out here\./);
    expect($("#shared-kit-value").hidden).toBe(true);
    fail = false;
    $("#shared-kit-state button").click();
    await vi.waitFor(() => expect(text("#shared-kit-value")).toContain("Kit value"), { timeout: 5000, interval: 10 });
    expect(engine).toHaveBeenCalledTimes(2);
    expect($("#shared-kit-state").hidden).toBe(true);
  });

  it("checks the evaluator against the SHA-256 the manifest lists before it runs it: another script is not run, and the value says it could not be worked out", async () => {
    const { app, engine } = open(fromLink(link()), { evaluator: new TextEncoder().encode("export const evaluator = false;\n") });
    await settled(app);
    expect(engine).not.toHaveBeenCalled();
    expect(text("#shared-kit-state")).toMatch(/^The value could not be worked out here\./);
    expect($("#shared-kit-value").hidden).toBe(true);
    expect(rows()).toHaveLength(22);
  });

  it("does not run an evaluator that is not served as a script, or that is longer than the manifest says", async () => {
    for (const serve of [
      (url) => (url.endsWith(KITVALUE_PATH) ? new Response(KITVALUE_BYTES, { status: 200, headers: { "content-type": "text/html" } }) : undefined),
      (url) => (url.endsWith(KITVALUE_PATH) ? script(new TextEncoder().encode("export const evaluator = true;\n// and more\n")) : undefined),
      (url) => (url.endsWith(KITVALUE_PATH) ? new Response("no", { status: 404 }) : undefined),
    ]) {
      document.body.replaceChildren();
      const { app, engine } = open(fromLink(link()), { serve });
      await settled(app);
      expect(engine).not.toHaveBeenCalled();
      expect(text("#shared-kit-state")).toMatch(/^The value could not be worked out here\./);
    }
  });

  it("says so when the manifest lists no evaluator, and asks for no script", async () => {
    const { app, engine, net } = open(fromLink(link()), { listed: false });
    await settled(app);
    expect(engine).not.toHaveBeenCalled();
    expect(text("#shared-kit-state")).toMatch(/^The value could not be worked out here\./);
    expect(asked(net).filter((path) => /\/assets\/engine\/[a-z]+-[A-Z0-9]{8}\.(js|wasm)$/.test(path)), "no script of the engine").toEqual([]);
    expect(rows()).toHaveLength(22);
  });

  it("says the same when the bundle of the trio cannot be fetched", async () => {
    const made = makeSite();
    const { app } = open(fromLink(link()), { made, serve: (url) => (url.endsWith(new URL(made.bundlePath, "https://trioforge.test").pathname) ? new Response("no", { status: 500 }) : undefined) });
    await settled(app);
    expect(text("#shared-kit-state")).toMatch(/^The value could not be worked out here\./);
    expect(rows()).toHaveLength(22);
  });
});

describe("the code of the panel of a shared kit", () => {
  const panelCode = () => import("../pipeline/trioforge/site/static/ui/shared-kit.js");

  it("is loaded for a kit link, once, and the panel is made of it; a page with no kit link does not load it", async () => {
    const loadShared = vi.fn(panelCode);
    const { app } = open(fromLink(link()), { loadShared });
    await settled(app);
    expect(loadShared).toHaveBeenCalledTimes(1);
    expect($("#shared-kit")).not.toBeNull();
    expect(rows()).toHaveLength(22);
    document.body.replaceChildren();
    const none = vi.fn(panelCode);
    const plain = open({ payload: null, source: null, cleared: false }, { loadShared: none });
    $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true })); // (the section is used: its code loads, the panel's does not)
    await plain.app.whenIdle();
    await vi.waitFor(() => expect(plain.app.upgrade?.gear).toBeTruthy(), { timeout: 5000, interval: 10 });
    expect(none).not.toHaveBeenCalled();
    expect($("#shared-kit")).toBeNull();
  });

  it("is waited for: the panel comes when its code does, and then loads the kit as it does when the code is there at once", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const { app, net, made } = open(fromLink(link()), { loadShared: () => gate.then(panelCode) });
    await vi.waitFor(() => expect(asked(net)).toContain(made.itemsPath), { timeout: 5000, interval: 10 }); // (the item list is fetched while the panel's code is on its way)
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect($("#shared-kit"), "the item list is in, and the panel's code is not").toBeNull();
    release();
    await settled(app);
    expect(rows()).toHaveLength(22);
    expect(text("#shared-kit-value")).toMatch(/^Kit value [\d,]+ for /);
  });

  it("is loaded again by nothing when the item list is tried again: the panel is made once", async () => {
    const made = makeSite();
    let fail = true;
    const loadShared = vi.fn(panelCode);
    const { app } = open(fromLink(link()), { made, loadShared, serve: (url) => (fail && url.endsWith(new URL(made.itemsPath, "https://trioforge.test").pathname) ? new Response("no", { status: 500 }) : undefined) });
    await vi.waitFor(() => expect(text("#shared-kit-state")).toMatch(/^Couldn't load the item list/), { timeout: 5000, interval: 10 });
    fail = false;
    $("#shared-kit-state button").click();
    await settled(app);
    await vi.waitFor(() => expect(rows()).toHaveLength(22), { timeout: 5000, interval: 10 });
    expect(loadShared).toHaveBeenCalledTimes(1);
    expect($$("#shared-kit")).toHaveLength(1);
  });

  it("that cannot be had is said at the top of the page and near the section's controls, each with a Reload; the section goes on working without the kit", async () => {
    const { app, reload } = open(fromLink(link()), { loadShared: () => Promise.reject(new Error("chunk")) });
    await app.whenIdle();
    await vi.waitFor(() => expect(text("#status .status-text")).toBe("Couldn't load the shared kit. Reload the page to try again."), { timeout: 5000, interval: 10 });
    await vi.waitFor(() => expect(text("#upgrade-load .status-text")).toBe("Couldn't load the shared kit. Reload the page to try again."), { timeout: 5000, interval: 10 });
    expect($("#shared-kit"), "no panel without its code").toBeNull();
    expect(text("#status button")).toBe("Reload");
    expect(text("#upgrade-load button")).toBe("Reload");
    $("#status button").click();
    expect(reload).toHaveBeenCalledTimes(1);
    // the section is in all the same: its list takes an item
    expect($("#upgrade-add").disabled).toBe(false);
    expect(app.upgrade.gear).not.toBeNull();
  });

  // A chunk that loads is not yet a panel: the module may lack createSharedKit, the call may throw, or it may give back nothing. A visitor who opened a kit link must be told, as they are
  // when the chunk could not be had (the page's status at the top, where the kit would be, and the section's line, each with a Reload, once), and not be left with a page that says nothing.
  it.each([
    ["has no createSharedKit", () => Promise.resolve({ somethingElse: true })],
    ["is no module at all", () => Promise.resolve(undefined)],
    ["throws from createSharedKit", () => Promise.resolve({ createSharedKit: () => { throw new Error("no panel"); } })],
    ["gives back no panel", () => Promise.resolve({ createSharedKit: () => undefined })],
  ])("that loads but %s is said like code that cannot be had: at the top of the page and near the section's controls, once, each with a Reload", async (_, loadShared) => {
    const { app, reload } = open(fromLink(link()), { loadShared });
    const status = vi.spyOn(app, "setStatus");
    await app.whenIdle();
    expect(text("#status .status-text")).toBe(CODE_FAILED);
    expect(text("#upgrade-load .status-text")).toBe(CODE_FAILED);
    expect($("#shared-kit"), "no panel was made").toBeNull();
    expect(text("#status button")).toBe("Reload");
    expect(text("#upgrade-load button")).toBe("Reload");
    expect(status.mock.calls.filter(([words]) => words === CODE_FAILED), "the page was told once").toHaveLength(1);
    $("#upgrade-load button").click();
    expect(reload).toHaveBeenCalledTimes(1);
    // the section is in all the same
    expect($("#upgrade-add").disabled).toBe(false);
    expect(app.upgrade.gear).not.toBeNull();
  });

  it("that makes its panel says nothing of the kind: no line, no Reload, and the page's status is empty", async () => {
    const { app } = open(fromLink(link()), { loadShared: panelCode });
    await settled(app);
    expect($("#shared-kit")).not.toBeNull();
    expect(text("#upgrade-load .status-text")).toBe("");
    expect($("#upgrade-load button")).toBeNull();
    expect($("#status .status-text")).toBeNull();
  });
});

// A dynamic import has no time limit of its own, and a browser keeps a failed module fetch until the page is reloaded. The panel's import of the evaluator, and the section's import of the
// chunk of the panel itself, have the time that the body of a download has (bodyMs: 60 s unless the section is given another), and past it they fail, with a Reload. The timeouts of the
// page are a fake clock here, moved by the test; the real clock is used to wait for the work that is not timed (a fetch, a digest, a module).
describe("an import that never settles", () => {
  afterEach(() => vi.useRealTimers());
  const fakeClock = () => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  const never = () => new Promise(() => {});
  const panelCode = () => import("../pipeline/trioforge/site/static/ui/shared-kit.js");
  /** A promise that the test settles: `[promise, settle]`. */
  const gate = () => {
    let settle;
    return [new Promise((resolve) => (settle = resolve)), (value) => settle(value)];
  };
  /** Wait (by the real clock) until something that real work does has happened. */
  async function until(check, what) {
    const start = performance.now();
    while (!check()) {
      if (performance.now() - start > 2000) throw new Error(`did not happen: ${what}`);
      await pause(5);
    }
  }
  const itemListIsIn = () => $("#upgrade-add")?.disabled === false;

  it("of the evaluator is given up at the time limit of a body: the value could not be worked out, with a Reload, and the panel does not say Working for good", async () => {
    fakeClock();
    const { engine, reload } = open(fromLink(link()), { loadEngine: never });
    await until(() => engine.mock.calls.length === 1, "the evaluator is imported (its script is fetched and checked first)");
    expect(said()).toBe("Working out its value…");
    await vi.advanceTimersByTimeAsync(STARTUP_STALL_MS * 2); // (the stall time is not the limit of an import)
    expect(said()).toBe("Working out its value…");
    await vi.advanceTimersByTimeAsync(STARTUP_COMPILE_MS - STARTUP_STALL_MS * 2 - 1);
    expect(said(), "a moment before the limit").toBe("Working out its value…");
    expect($("#shared-kit-state button")).toBeNull();
    await vi.advanceTimersByTimeAsync(1);
    await until(() => said() === VALUE_RELOAD, "the panel says that the value could not be worked out, and offers a Reload");
    expect(text("#shared-kit-state button")).toBe("Reload");
    expect($("#shared-kit-value").hidden).toBe(true);
    expect(rows(), "the kit is there whatever the value does").toHaveLength(22);
    expect($("#announce").textContent).toBe(`A kit shared with you. ${VALUE_RELOAD}`);
    $("#shared-kit-state button").click();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("of the evaluator that settles after the limit changes nothing: the panel stays as it said, with its Reload", async () => {
    fakeClock();
    const [late, settle] = gate();
    const { engine } = open(fromLink(link()), { loadEngine: () => late });
    await until(() => engine.mock.calls.length === 1, "the evaluator is imported");
    await vi.advanceTimersByTimeAsync(STARTUP_COMPILE_MS);
    await until(() => said() === VALUE_RELOAD, "the panel gave up");
    settle({ valueOfKit, loadKitBundle });
    await pause(50);
    expect(said()).toBe(VALUE_RELOAD);
    expect($("#shared-kit-value").hidden).toBe(true);
    expect(text("#shared-kit-state button")).toBe("Reload");
  });

  it("of the evaluator that settles in time is not touched by the limit: the value is drawn, and the time that runs out afterwards says nothing", async () => {
    fakeClock();
    const [early, settle] = gate();
    const { engine } = open(fromLink(link()), { loadEngine: () => early });
    await until(() => engine.mock.calls.length === 1, "the evaluator is imported");
    await vi.advanceTimersByTimeAsync(STARTUP_COMPILE_MS - 1000);
    expect(said()).toBe("Working out its value…");
    settle({ valueOfKit, loadKitBundle });
    await until(() => numberShown() !== null, "the value is drawn");
    expect($("#shared-kit-state").hidden).toBe(true);
    await vi.advanceTimersByTimeAsync(STARTUP_COMPILE_MS * 2);
    expect($("#shared-kit-state").hidden, "and the limit that passes afterwards says nothing").toBe(true);
    expect(text("#shared-kit-value")).toMatch(/^Kit value [\d,]+ for /);
  });

  it("of the panel's own chunk is given up at the time limit of a body: the section's line and the page's status say so, once, each with a Reload, and the section works on", async () => {
    fakeClock();
    const { app, reload } = open(fromLink(link()), { loadShared: never, env: { stallMs: 5000, bodyMs: 9000 } });
    const status = vi.spyOn(app, "setStatus");
    await until(itemListIsIn, "the item list is in, and the section can be used");
    await vi.advanceTimersByTimeAsync(8999); // (more than the stall time, and a moment before the limit)
    expect(text("#upgrade-load button"), "nothing is offered yet").toBe("");
    expect(text("#status .status-text"), "nothing is said yet").toBe("");
    await vi.advanceTimersByTimeAsync(1);
    await until(() => text("#upgrade-load .status-text") === CODE_FAILED, "the section says that the panel's code could not be had");
    expect(text("#status .status-text")).toBe(CODE_FAILED);
    expect(text("#upgrade-load button")).toBe("Reload");
    expect(text("#status button")).toBe("Reload");
    expect(status.mock.calls.filter(([words]) => words === CODE_FAILED), "the page was told once").toHaveLength(1);
    expect($("#shared-kit"), "no panel").toBeNull();
    $("#upgrade-load button").click();
    expect(reload).toHaveBeenCalledTimes(1);
    expect(app.upgrade.gear, "the section is in all the same").not.toBeNull();
    await app.whenIdle();
  });

  it("of the panel's own chunk is given up at 60 s when the section is given no limit of its own", async () => {
    fakeClock();
    const { app } = open(fromLink(link()), { loadShared: never });
    await until(itemListIsIn, "the item list is in");
    await vi.advanceTimersByTimeAsync(STARTUP_COMPILE_MS - 1);
    expect(text("#upgrade-load button")).toBe("");
    await vi.advanceTimersByTimeAsync(1);
    await until(() => text("#upgrade-load .status-text") === CODE_FAILED, "the section gave up");
    await app.whenIdle();
  });

  it("of the panel's own chunk that arrives after the limit makes no panel: the section has said that it could not, and says nothing more", async () => {
    fakeClock();
    const [late, settle] = gate();
    const { app } = open(fromLink(link()), { loadShared: () => late, env: { bodyMs: 9000 } });
    await until(itemListIsIn, "the item list is in");
    await vi.advanceTimersByTimeAsync(9000);
    await until(() => text("#upgrade-load .status-text") === CODE_FAILED, "the section gave up");
    settle(await panelCode());
    await pause(50);
    expect($("#shared-kit"), "the panel is not made after the page said it could not be").toBeNull();
    expect(text("#upgrade-load .status-text")).toBe(CODE_FAILED);
    await app.whenIdle();
  });

  it("of the panel's own chunk that arrives in time is not touched by the limit: the kit is shown, and the time that runs out afterwards says nothing", async () => {
    fakeClock();
    const [early, settle] = gate();
    const { app } = open(fromLink(link()), { loadShared: () => early, env: { stallMs: 5000, bodyMs: 9000 } });
    await until(itemListIsIn, "the item list is in");
    await vi.advanceTimersByTimeAsync(8000);
    settle(await panelCode());
    await until(() => numberShown() !== null, "the kit is shown with its value");
    await app.whenIdle();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(text("#upgrade-load .status-text"), "the limit that passes afterwards says nothing").toBe("");
    expect($("#upgrade-load button")).toBeNull();
    expect($("#status .status-text")).toBeNull();
    expect(rows()).toHaveLength(22);
  });
});

describe("a link that is not for this page", () => {
  it("of another trio than the page's is said plainly: the kit is drawn, its value is not worked out and it is not offered for sharing", async () => {
    const { app } = open(fromLink(link({ trio: "clr-shd-enc" })));
    await settled(app);
    expect(text("#shared-kit-state")).toBe("This kit is for the trio CLR/SHD/ENC, and this page is for PAL/MNK/BER, so its value is not worked out here.");
    expect(rows()).toHaveLength(22);
    expect($("#shared-kit-value").hidden).toBe(true);
    expect($("#shared-kit-share").hidden).toBe(true);
  });

  it("of another trio or another level stays without a value when the page's view changes afterwards", async () => {
    for (const over of [{ trio: "clr-shd-enc" }, { level: 55 }]) {
      document.body.replaceChildren();
      const { app, net, made } = open(fromLink(link(over)));
      await settled(app);
      const first = text("#shared-kit-state");
      choose('input[name="role"][value="tank"]');
      await app.whenIdle();
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(app.valueView().role, "the page's view did change").toBe("tank");
      expect($("#shared-kit-value").hidden, JSON.stringify(over)).toBe(true);
      expect(text("#shared-kit-state")).toBe(first);
      expect(asked(net).filter((path) => path === made.bundlePath), "and the bundle was not even asked for").toEqual([]);
    }
  });

  it("of another level than the bundle's is said plainly in the same way", async () => {
    const { app } = open(fromLink(link({ level: 55 })));
    await settled(app);
    expect(text("#shared-kit-state")).toBe("This kit is for level 55, and this page is for level 50, so its value is not worked out here.");
    expect($("#shared-kit-value").hidden).toBe(true);
    expect($("#shared-kit-share").hidden).toBe(true);
  });
});

describe("a link that cannot be read", () => {
  const BAD = ["!!!", "A", "AAAA", encodeKit(kitOf()).slice(0, -3), `${encodeKit(kitOf())}A`, "A".repeat(2049), ""];

  it.each(BAD.map((payload) => [payload.slice(0, 12) || "(empty)", payload]))("says This kit link could not be read, and shows no kit: %s", async (_, payload) => {
    const { app } = open(fromLink(payload));
    await settled(app);
    expect($("#shared-kit-h").textContent).toBe("A kit shared with you");
    expect(text("#shared-kit-state")).toBe("This kit link could not be read");
    expect($("#shared-kit-table").hidden).toBe(true);
    expect($("#shared-kit-value").hidden).toBe(true);
    expect($("#shared-kit-share").hidden).toBe(true);
  });

  it("says it only after the decode has failed: while the item list is on its way the panel says that it is loading", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const made = makeSite();
    const { app } = open(fromLink("!!!"), { made, delay: (path) => (path === made.itemsPath ? gate : undefined) });
    await vi.waitFor(() => expect(text("#shared-kit-state")).toBe("Loading the shared kit…"), { timeout: 5000, interval: 10 });
    expect(text("#shared-kit")).not.toContain("could not be read");
    release();
    await settled(app);
    expect(text("#shared-kit-state")).toBe("This kit link could not be read");
  });

  it("says it through the page's live region, once", async () => {
    const { app } = open(fromLink("!!!"));
    await settled(app);
    await vi.waitFor(() => expect($("#announce").textContent).toBe("A kit shared with you. This kit link could not be read."), { timeout: 5000, interval: 10 });
  });
});

describe("the shared kit's own Share", () => {
  it("copies a link that is the canonical text of the decoded kit, with its placeholders, on the click", async () => {
    const slots = [...KIT_SLOTS, [11, 12345, 3]];
    const writeText = vi.fn(async () => {});
    Object.defineProperty(window.navigator, "clipboard", { value: { writeText }, configurable: true });
    const { app } = open(fromLink(link({ slots })));
    await settled(app);
    expect(writeText).not.toHaveBeenCalled();
    expect($("#shared-kit-share-words").textContent).toBe("This link lists the items in this kit.");
    $("#shared-kit-share-button").click();
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledTimes(1), { timeout: 5000, interval: 10 });
    const copied = writeText.mock.calls[0][0];
    expect(copied).toBe(`https://trioforge.test/trio/pal-mnk-ber/#k=${link({ slots })}`);
    const again = decodeKit(copied.slice(copied.indexOf("#k=") + 3), RECORDS);
    expect(again.unknown).toEqual([11]); // (the placeholder travels with its page id and tier, so that the next page can know the item)
    expect(again.kit.slots.map((slot) => [slot.slotIndex, slot.pageId, slot.tier])).toEqual([...slots].sort((a, b) => a[0] - b[0]));
  });
});

describe("when the item list cannot be had", () => {
  it("says so in the panel, with a Try again that loads it, and the kit appears when it does", async () => {
    const made = makeSite();
    let fail = true;
    const { app } = open(fromLink(link()), { made, serve: (url) => (fail && url.endsWith(new URL(made.itemsPath, "https://trioforge.test").pathname) ? new Response("no", { status: 500 }) : undefined) });
    await vi.waitFor(() => expect(text("#shared-kit-state")).toMatch(/^Couldn't load the item list, so the shared kit cannot be shown\./), { timeout: 5000, interval: 10 });
    expect($("#shared-kit-table").hidden).toBe(true);
    fail = false;
    $("#shared-kit-state button").click();
    await settled(app);
    await vi.waitFor(() => expect(rows()).toHaveLength(22), { timeout: 5000, interval: 10 });
    expect(text("#shared-kit-value")).toContain("Kit value");
  });

  it("says that the data was updated, with a Reload, when the release of the data is not the page's", async () => {
    const { app, reload } = open(fromLink(link()), { release: "data-2000-01-01" });
    await vi.waitFor(() => expect(said()).toBe("Data updated, reload the page to see this kit."), { timeout: 5000, interval: 10 });
    await app.whenIdle();
    expect($("#shared-kit-table").hidden).toBe(true);
    $("#shared-kit-state button").click();
    expect(reload).toHaveBeenCalledTimes(1);
  });
});

describe("what a shared kit is not", () => {
  it("sent anywhere: every request is for this site, and none has the kit in it", async () => {
    const payload = link();
    const { app, net } = open(fromLink(payload));
    await settled(app);
    for (const url of net.asked) {
      expect(String(url).includes(payload), url).toBe(false);
      expect(String(url).includes("k="), url).toBe(false);
      if (!String(url).startsWith("/")) expect(new URL(url).origin).toBe("https://trioforge.test");
    }
  });

  it("kept: nothing is written to the device, and the history entry is as the page script left it", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    window.history.replaceState({ k: "kept" }, "", "/trio/pal-mnk-ber/");
    const { app } = open(fromLink(link(), "state"));
    await settled(app);
    expect(setItem).not.toHaveBeenCalled();
    expect(window.history.state).toEqual({ k: "kept" });
    expect(window.localStorage.length).toBe(0);
    expect(window.location.hash).toBe("");
  });
});
