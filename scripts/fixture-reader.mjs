// A reader of the parity fixtures (python -m trioforge.export.fixtures; the format is described in pipeline/trioforge/export/fixtures.py), shared by the
// engine's tests (tests-js/engine-fixtures.mjs) and by the phone gate (scripts/phone-bench.mjs). It reads files and nothing else: no test framework, and
// nothing of the engine.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { gunzipSync } from "node:zlib";

/** One folder of fixtures: its manifest, and its documents by path (the path without `.gz`, whichever way the file is stored). */
export class FixtureSet {
  constructor(directory, label) {
    this.directory = directory;
    this.label = label;
    this.manifest = JSON.parse(readFileSync(resolve(directory, "manifest.json"), "utf8"));
    if (this.manifest.complete !== true) throw new Error(`${label}: the run that made it did not finish`);
    this.entries = new Map();
    for (const entry of this.manifest.files) this.entries.set(entry.path.endsWith(".gz") ? entry.path.slice(0, -3) : entry.path, entry);
    this.cache = new Map();
  }

  /** The paths of the documents of a kind (`case`, `profiles`, `item-vectors` ...) under a folder, in manifest order. */
  paths(kind, folder = "") {
    const found = [];
    for (const [path, entry] of this.entries) if (entry.kind === kind && path.startsWith(folder)) found.push(path);
    return found;
  }

  has(path) {
    return this.entries.has(path);
  }

  /** The text of the document at a path, as it is stored once the compression is undone (not parsed, and not kept). */
  text(path) {
    const entry = this.entries.get(path);
    if (entry === undefined) throw new Error(`${this.label} has no ${path}`);
    const raw = readFileSync(resolve(this.directory, entry.path));
    return (entry.path.endsWith(".gz") ? gunzipSync(raw) : raw).toString("utf8");
  }

  /** The document at a path, parsed (once). */
  read(path) {
    if (!this.cache.has(path)) this.cache.set(path, JSON.parse(this.text(path)));
    return this.cache.get(path);
  }
}
