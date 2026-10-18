// Shared by the tests of the Upgrade section (not a test file): the baked page the generator writes for the site fixture, which holds the section, the item table of
// the fixture, and the dumps made from its items. Every name in them is invented (pipeline/tests/test_site_fixture_items.py fails when a real item's key or name is in
// the fixture or its specs). Paths, not URL objects: in the jsdom environment the global URL is jsdom's, which file system calls refuse.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";

const HERE = dirname(fileURLToPath(import.meta.url));
export const ROOT = resolve(HERE, "..");
export const STATIC = resolve(ROOT, "pipeline/trioforge/site/static");

/** The text of the fixture's item table (what the site serves as the item list). */
export const siteTableText = () => readFileSync(resolve(ROOT, "fixtures/site/results/items.json"), "utf8");

/** The fixture's item table as `readItemTable` reads it. */
export const siteTable = () => readItemTable(JSON.parse(siteTableText()));

/** The records of the fixture's item table (plain data, a fresh copy each time, so that a test may change them). */
export const siteRecords = () => JSON.parse(siteTableText()).items;

/** A dump of the fixtures (fixtures/dumps/<name>.txt) with the line ends of the real file (git keeps the fixtures with LF). */
export function dumpText(name) {
  const raw = readFileSync(resolve(ROOT, "fixtures/dumps", `${name}.txt`), "latin1");
  return raw.split("\r\n").join("\n").split("\n").join("\r\n");
}

/** The baked trio page of the contract, in the document; returns the Upgrade section. */
export function mountPage(extra = "") {
  document.body.innerHTML = readFileSync(resolve(ROOT, "fixtures/site/contract/trio-main.html"), "utf8") + extra;
  return document.getElementById("upgrade");
}

/** What the page code does at its start: the controls that are waiting for it are enabled. */
export function wake(root) {
  for (const control of root.querySelectorAll("[data-wake]")) control.disabled = false;
}

export const $ = (selector, within = document) => within.querySelector(selector);
export const $$ = (selector, within = document) => [...within.querySelectorAll(selector)];

/** Type text into an input the way a visitor does: the value changes and the page is told. */
export function type(input, text) {
  input.value = text;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

/** Press a key on an element; returns the event, so that a test can ask whether the page took the key. */
export function press(element, key, init = {}) {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
  element.dispatchEvent(event);
  return event;
}

/** An item table of the format the site serves, made of the given records (the header fields are those of the fixture's table). */
export function tableOf(records) {
  const { items: _items, ...header } = JSON.parse(siteTableText());
  return readItemTable({ ...header, count: records.length, items: records });
}

/** A record of the item table with the fields that every record has; `more` replaces or adds fields. Every name and number is invented. */
export const record = (id, name, more = {}) => ({
  id,
  name,
  slots: ["FINGER"],
  stats: { STR: 5 },
  weight10: 10,
  tier_rule: "drop",
  evidence: { level: "strict" },
  ...more,
});

/** A drop of files on an element, as a browser makes one: the files and their kinds are on the event's data transfer, which says what the drop will do (`effect`). */
export function drop(target, files, { types = ["Files"], type: eventType = "drop", effect = "none" } = {}) {
  const event = new Event(eventType, { bubbles: true, cancelable: true });
  Object.defineProperty(event, "dataTransfer", { value: { files, types, dropEffect: effect } });
  target.dispatchEvent(event);
  return event;
}

/** The visitor chooses files with the file input. */
export function choose(input, files) {
  Object.defineProperty(input, "files", { value: files, configurable: true });
  input.dispatchEvent(new Event("change", { bubbles: true }));
}
