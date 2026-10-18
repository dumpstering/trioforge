// The parity fixtures as the engine's parity tests read them (python -m trioforge.export.fixtures; the format is described in
// pipeline/trioforge/export/fixtures.py). Two sets:
//
//   SAMPLE  the committed sample, fixtures/parity: plain files, always there; the tests run on it everywhere.
//   FULL    the full set, build/fixtures (git ignores it): gzip files, made with the command below. When it is absent the tests that
//           want it are skipped and say so; with TRIOFORGE_FULL_FIXTURES=1 (CI sets it) its absence is a failure instead.
//
// Nothing here uses the engine, and nothing here is read by the site.

import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "vitest";
import { FixtureSet } from "../scripts/fixture-reader.mjs";

// (the reader itself is in scripts/fixture-reader.mjs, which the phone gate shares; it is exported from here as well)
export { FixtureSet };

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/** How the full set is made (the seed is the one CI uses). */
export const MAKE_FULL = "PYTHONPATH=pipeline python -m trioforge.export.fixtures --out build/fixtures --seed 20261014";
/** The environment variable that says the full set must be there. */
export const FULL_REQUIRED = process.env.TRIOFORGE_FULL_FIXTURES === "1";

export const SAMPLE = new FixtureSet(resolve(ROOT, "fixtures/parity"), "the committed sample");

const FULL_DIRECTORY = resolve(ROOT, "build/fixtures");
/** Why there is no full set (it has not been made, or its run did not finish), or null when there is one. */
let missing = null;
function openFull() {
  if (!existsSync(resolve(FULL_DIRECTORY, "manifest.json"))) {
    missing = "build/fixtures/manifest.json is absent";
    return null;
  }
  try {
    return new FixtureSet(FULL_DIRECTORY, "the full set");
  } catch (error) {
    missing = `build/fixtures cannot be used (${error.message})`;
    return null;
  }
}
/** The full set, or null when there is none. */
export const FULL = openFull();

/**
 * A group of tests on the full set; `body` gets the set. Without the set the group is one skipped test whose name says why, and with
 * TRIOFORGE_FULL_FIXTURES=1 it is one failing test instead.
 */
export function describeFull(name, body) {
  if (FULL !== null) return describe(name, () => body(FULL));
  if (FULL_REQUIRED) {
    return describe(name, () => {
      it("needs the full fixture set, which TRIOFORGE_FULL_FIXTURES=1 says must be there", () => {
        throw new Error(`${missing}; make the full set with: ${MAKE_FULL}`);
      });
    });
  }
  return it.skip(`${name} [skipped: ${missing}; make the full set with: ${MAKE_FULL}]`, () => {});
}
