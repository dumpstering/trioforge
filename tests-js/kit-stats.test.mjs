// @vitest-environment jsdom
//
// The stats and the why line of the rows of Wear this (p7kit): the page code run in jsdom against the baked page and the data files of the contract fixture. The default view
// has both, from the page; every other view has the stats of its items (from the shard) and no why line, and says so in a note.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it } from "vitest";
import { parseShard } from "../pipeline/trioforge/site/static/shard.js";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract");
const text = (name) => readFileSync(resolve(CONTRACT, name), "utf8");
const dataFile = (name) => JSON.parse(text(`data/${name}.json`));

function mount(env = {}) {
  document.body.innerHTML = text("trio-main.html");
  window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
  const fetch = async (url) => {
    const name = String(url).replace("/data/pal-mnk-ber/", "").replace(".json", "");
    return { ok: true, status: 200, json: async () => structuredClone(dataFile(name)) };
  };
  return initTrio({ document, window, fetch, ...env });
}

const $ = (selector) => document.querySelector(selector);
const rows = () => [...document.querySelectorAll("#kit-body tr")];
const part = (row, name) => row.querySelector(`[data-f="${name}"]`);
const change = (element, value) => {
  element.value = value;
  element.dispatchEvent(new Event("change", { bubbles: true }));
};

/** The stats of every item of a view as the shard file says them: what the page must show. */
function shardStats(name, race, tier, setup) {
  const doc = dataFile(name);
  const row = doc.rows.find((r) => r[0] === race && r[1] === "tank" && r[2] === tier && r[3] === setup);
  const at = doc.stat_tiers.indexOf(tier);
  return doc.kits[row[4]].map((i) => (i < 0 ? null : doc.items[i][7][at]));
}

describe("the baked page", () => {
  it("has the stats and the why line in every row, as text, with no script", () => {
    mount({ document: document });
    const before = rows().map((row) => [part(row, "stats").textContent, part(row, "why").textContent]);
    expect(before.filter(([stats]) => stats !== "")).toHaveLength(21);
    expect(before[0][0]).toMatch(/^AC \+\d+, STA \+\d+, HP \+\d+, Weight \d+\.\d$/);
    expect(before[0][1]).toMatch(/^Lost without it: STA \+\d+: \d+; .*Next best: .*, \d+ less\.$/);
  });
});

const summaries = () => [...document.querySelectorAll("#kit-body .kit-more > summary")];
const panels = () => [...document.querySelectorAll("#kit-body .kit-more")];
/** What a click on a summary does in a browser: the details element opens or closes, and says so. */
const press = (summary) => {
  const panel = summary.parentElement;
  panel.open = !panel.open;
  panel.dispatchEvent(new Event("toggle"));
};

describe("the summaries that open the panels", () => {
  it("are given aria-expanded and a name, closed to begin with, and the page has one button for all of them", () => {
    mount();
    expect(summaries()).toHaveLength(22); // (the empty place's panel is there and out of sight)
    expect(panels().filter((p) => !p.hidden)).toHaveLength(21);
    for (const summary of summaries()) {
      expect(summary.getAttribute("aria-expanded")).toBe("false");
      expect(summary.parentElement.open).toBe(false);
    }
    expect(summaries()[0].getAttribute("aria-label")).toBe("Stats and why for Helm of the Stoneward");
    const all = $("#kit-stats-all");
    expect(all.disabled).toBe(false);
    expect(all.getAttribute("aria-expanded")).toBe("false");
    expect(all.getAttribute("aria-controls")).toBe("kit");
  });

  it("follow their panel, and the all button follows the rows", () => {
    mount();
    const [first] = summaries();
    press(first);
    expect(first.getAttribute("aria-expanded")).toBe("true");
    press(first);
    expect(first.getAttribute("aria-expanded")).toBe("false");
    $("#kit-stats-all").click();
    expect(panels().filter((p) => !p.hidden).every((p) => p.open)).toBe(true);
    expect(summaries().filter((s) => !s.parentElement.hidden).every((s) => s.getAttribute("aria-expanded") === "true")).toBe(true);
    expect($("#kit-stats-all").getAttribute("aria-expanded")).toBe("true");
    press(first);
    expect($("#kit-stats-all").getAttribute("aria-expanded")).toBe("false");
    $("#kit-stats-all").click();
    $("#kit-stats-all").click();
    expect(panels().every((p) => !p.open)).toBe(true);
  });

  it("are inside a details element the page was made with, so that they work without script", () => {
    document.body.innerHTML = text("trio-main.html");
    expect(document.querySelectorAll("#kit-body details.kit-more > summary")).toHaveLength(22);
    expect(document.querySelector("#kit-stats-all").disabled).toBe(true); // (until the code starts, like the Change button)
  });
});

describe("another view", () => {
  let baked;
  beforeEach(() => {
    baked = null;
  });

  it("shows the stats of its items at its tier, no why line and the note", async () => {
    const app = mount();
    baked = rows().map((row) => part(row, "why").textContent);
    expect($("#why-note").hidden).toBe(true);
    change($("#sw-tier"), "0");
    await app.whenIdle();
    const want = shardStats("strict-own", "OGR", 0, "dw");
    rows().forEach((row, index) => {
      expect(part(row, "stats").textContent).toBe(want[index] ?? "");
      expect(part(row, "why").hidden).toBe(true);
      expect(part(row, "why").textContent).toBe("");
    });
    expect($("#why-note").hidden).toBe(false);
    expect(want[0]).not.toBe(text("trio-main.html").match(/data-f="stats">([^<]*)</)[1]); // (the tier is +0: the figures are not the baked +4 ones)
    // the panels keep the state the visitor left them in
    expect(baked.filter(Boolean).length).toBe(21);
  });

  it("is the default view again when the switches go back: the why line and the baked stats are there, the note is not", async () => {
    const app = mount();
    const first = rows().map((row) => [part(row, "stats").textContent, part(row, "why").textContent]);
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect($("#why-note").hidden).toBe(false);
    change($("#sw-tier"), "4");
    await app.whenIdle();
    expect(rows().map((row) => [part(row, "stats").textContent, part(row, "why").textContent])).toEqual(first);
    expect(rows().every((row, index) => first[index][1] === "" || part(row, "why").hidden === false)).toBe(true);
    expect($("#why-note").hidden).toBe(true);
  });

  it("has no why line for another race, another role or another buff set either", async () => {
    const app = mount();
    change($("#sw-race"), "TRL");
    await app.whenIdle();
    expect(rows().every((row) => part(row, "why").hidden)).toBe(true);
    expect($("#why-note").hidden).toBe(false);
    change($("#sw-race"), "OGR");
    await app.whenIdle();
    expect($("#why-note").hidden).toBe(true);
    const group = document.querySelector("#buffs-group");
    group.checked = true;
    group.dispatchEvent(new Event("change", { bubbles: true }));
    await app.whenIdle();
    expect(rows().every((row) => part(row, "why").hidden)).toBe(true);
    expect($("#why-note").hidden).toBe(false);
    expect(part(rows()[0], "stats").textContent).not.toBe("");
  });

  it("keeps the open rows open when the view changes, and hides the button of a place that is left empty", async () => {
    const app = mount();
    const [first] = summaries();
    press(first);
    change($("#sw-tier"), "0");
    await app.whenIdle();
    expect(first.getAttribute("aria-expanded")).toBe("true");
    expect(first.parentElement.open).toBe(true);
    rows().forEach((row, index) => expect(panels()[index].hidden).toBe(part(row, "name").textContent === "Leave empty"));
  });

  it("names the stats of an item of the optimizer's answer from the shards that were loaded, and sends the visitor to the item's page for one that no shard lists", async () => {
    const app = mount();
    change($("#sw-tier"), "4"); // (the page's own view, with its shard loaded)
    await app.whenIdle();
    const strict = parseShard(dataFile("strict-own"));
    const known = strict.items[0];
    const items = new Array(22).fill(null);
    items[0] = { key: known.key, name: known.name, rule: known.rule, arrival: known.arrival, source: known.source, evidence: "strict", deity: [] };
    items[1] = { key: "w4242", name: "Stranger", rule: "drop", arrival: 4, source: "x", evidence: "strict", deity: [] };
    expect(app.drawSolved({ items, tier: 4, hasteAssumed: 0, value: 1, kind: "buffs" })).toBe(true);
    expect(part(rows()[0], "stats").textContent).toBe(known.stats[4]);
    expect(part(rows()[1], "stats").textContent).toBe("Its stats at this tier are on the page of the item.");
    expect(rows().every((row) => part(row, "why").hidden)).toBe(true);
    expect($("#why-note").hidden).toBe(false);
  });
});

describe("the shard reader", () => {
  it("gives an item its stats at each tier of the file, and refuses a file whose stats do not fit its tiers", () => {
    const doc = dataFile("strict-own");
    const shard = parseShard(doc);
    expect(Object.keys(shard.items[0].stats).map(Number)).toEqual(doc.stat_tiers);
    expect(shard.items[0].stats[4]).toBe(doc.items[0][7][doc.stat_tiers.indexOf(4)]);
    const short = structuredClone(doc);
    short.items[0][7].pop();
    expect(() => parseShard(short)).toThrow("bad item");
    const odd = structuredClone(doc);
    odd.stat_tiers = [0, 0, 4];
    expect(() => parseShard(odd)).toThrow("bad stat tiers");
    const plain = structuredClone(doc);
    delete plain.stat_tiers;
    plain.items.forEach((row) => row.pop());
    expect(parseShard(plain).items[0].stats).toBeUndefined();
  });
});
