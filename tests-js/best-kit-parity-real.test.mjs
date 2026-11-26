import { execFileSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

// The parity test of the worker's best kit (best-kit-parity.test.mjs) is run on the maintainer's results with TRIOFORGE_RESULTS (and TRIOFORGE_SHARD_SAMPLE=i/n). It used to count a
// difference of a kit or of the optional buffs there and not fail on it, so that a run on real results could not fail on a kit. It fails on any difference of the value, the kit, the
// buffs or the haste, results named by TRIOFORGE_RESULTS or not. These tests run it the way the maintainer does, as a vitest of its own, on a copy of the invented results in which
// four views differ from their shard by one thing each, and on the copy as it was.

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const FIXTURE = fileURLToPath(new URL("../fixtures/site/results-solved/", import.meta.url));
const VITEST = fileURLToPath(new URL("../node_modules/vitest/vitest.mjs", import.meta.url));
const TEST = "tests-js/best-kit-parity.test.mjs";

vi.setConfig({ testTimeout: 180_000 });

let scratch;
beforeAll(() => {
  scratch = mkdtempSync(join(tmpdir(), "best-kit-parity-"));
});
afterAll(() => {
  rmSync(scratch, { recursive: true, force: true });
});

/** Run the parity test as the maintainer does, on the results of a folder: how it ended, and what it printed. */
function parityOn(folder) {
  const env = { ...process.env, TRIOFORGE_RESULTS: folder };
  delete env.TRIOFORGE_SHARD_SAMPLE;
  delete env.TRIOFORGE_SHARD_LINES;
  try {
    const out = execFileSync(process.execPath, [VITEST, "run", TEST, "--reporter=verbose"], { cwd: ROOT, env, encoding: "utf8", stdio: "pipe" });
    return { status: 0, out };
  } catch (error) {
    return { status: error.status ?? 1, out: `${error.stdout ?? ""}${error.stderr ?? ""}` };
  }
}

/** A copy of the invented results in which the first four rows of the wiki shard differ from what the worker finds, each in one thing: a kit, the buffs, the haste, the value. */
function changedCopy(name) {
  const folder = join(scratch, name);
  cpSync(FIXTURE, folder, { recursive: true });
  const path = join(folder, "pal-mnk-ber", "wiki-own.json");
  const shard = JSON.parse(readFileSync(path, "utf8"));
  const kit = [...shard.kits[shard.scenarios[0][4]]];
  const place = kit.findIndex((index) => index >= 0);
  kit[place] = shard.items.findIndex((row, at) => !kit.includes(at));
  shard.kits.push(kit);
  shard.scenarios[0][4] = shard.kits.length - 1;
  shard.buff_sets.push([...shard.buff_sets[shard.scenarios[1][8]], 424242]);
  shard.scenarios[1][8] = shard.buff_sets.length - 1;
  shard.scenarios[2][9] += 1;
  shard.scenarios[3][5] = Math.round((shard.scenarios[3][5] + 0.01) * 100) / 100;
  writeFileSync(path, JSON.stringify(shard));
  return folder;
}

describe("the parity test of the worker's best kit, run on results named by TRIOFORGE_RESULTS", () => {
  it("passes on results that are what the worker finds, and says how many views it held to their shards", () => {
    const { status, out } = parityOn(FIXTURE);
    expect(status, out.slice(-1500)).toBe(0);
    expect(out).toMatch(/best-kit parity: 112 views in 56 chunks, 0 differ/);
  });

  it("fails on a view whose kit differs from its shard, as it fails on a view whose buffs, haste or value differ, and says which", () => {
    const { status, out } = parityOn(changedCopy("changed"));
    expect(status, "a difference in a kit or in the buffs is a failure of the test").not.toBe(0);
    expect(out).toMatch(/kit: 1 place differs/);
    expect(out).toMatch(/buffs: shard \[[^\]]*424242\]/);
    expect(out).toMatch(/haste assumed: shard \d+, engine \d+/);
    expect(out).toMatch(/F: shard \d+(\.\d+)?, engine \d+(\.\d+)?/);
    // one thing for each of the four views, and nothing counted as "other kits of the same value"
    expect(out).not.toMatch(/other kits of the same value/);
  });
});
