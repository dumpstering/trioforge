// The browser tests ask the site about its trios through tests-e2e/trios.mjs, so that they run unchanged on one trio (the fixture), on a few, and on the whole grid of 560, and on a grid
// whose every trio is built (where there is none left to be "coming soon"). The helpers are plain functions, so they are tested here without a browser: how many trios the classes make, the
// first trio that is not built (or none), the classes the home page offers, and the sample of trios that the tests that load every order of a trio run on: at most five, the same on every run.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { SAMPLE_SIZE, builtTrios, chipCodes, firstUnbuilt, sample, trioCount } from "../tests-e2e/trios.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const HOME = readFileSync(resolve(HERE, "../fixtures/site/contract/home-main.html"), "utf8");

const CODES = ["WAR", "CLR", "PAL", "RNG", "SHD", "DRU", "MNK", "BRD", "ROG", "SHM", "NEC", "WIZ", "MAG", "ENC", "BST", "BER"];

/** Every trio of some classes, as the codes of their pages (in the order of the classes). */
function every(codes) {
  const slugs = [];
  for (const [i, a] of codes.entries()) for (const [j, b] of codes.slice(i + 1).entries()) for (const c of codes.slice(i + j + 2)) slugs.push([a, b, c].map((code) => code.toLowerCase()).join("-"));
  return slugs;
}

/** What the browser tests are given to ask the site with: `request.get` answers with the files of a made-up site. */
const site = (files) => ({
  get: async (path) => {
    if (!(path in files)) throw new Error(`no file ${path} in the made-up site`);
    return { json: async () => JSON.parse(files[path]), text: async () => files[path] };
  },
});

describe("how many trios some classes make", () => {
  it("is the number of ways to choose three of them", () => {
    expect(trioCount(16)).toBe(560);
    expect(trioCount(4)).toBe(4);
    expect(trioCount(3)).toBe(1);
    expect(trioCount(5)).toBe(10);
    expect(trioCount(2)).toBe(0);
    expect(trioCount(0)).toBe(0);
  });
});

describe("the first trio that is not built", () => {
  it("is the first of the classes in their order when none is built", () => {
    expect(firstUnbuilt(CODES, [])).toBe("war-clr-pal");
    expect(firstUnbuilt(["PAL", "SHD", "MNK", "BER"], [])).toBe("pal-shd-mnk");
  });

  it("skips the trios that are built, in the order of the classes", () => {
    expect(firstUnbuilt(CODES, ["war-clr-pal", "war-clr-rng"])).toBe("war-clr-shd");
    expect(firstUnbuilt(CODES, ["pal-mnk-ber"])).toBe("war-clr-pal");
    const all = every(CODES);
    expect(all).toHaveLength(560);
    expect(firstUnbuilt(CODES, all.slice(0, 559))).toBe(all[559]);
    expect(firstUnbuilt(CODES, all.slice(1))).toBe(all[0]);
  });

  it("is none when every trio of the classes is built, and says so with null, whatever the number of classes", () => {
    expect(firstUnbuilt(CODES, every(CODES))).toBeNull();
    expect(firstUnbuilt(["PAL", "SHD", "MNK", "BER"], every(["PAL", "SHD", "MNK", "BER"]))).toBeNull();
    expect(firstUnbuilt(["PAL", "MNK", "BER"], ["pal-mnk-ber"])).toBeNull();
    expect(firstUnbuilt(["PAL", "MNK"], [])).toBeNull(); // (two classes make no trio: there is none to be unbuilt)
    expect(firstUnbuilt(CODES, [...every(CODES), "pal-mnk-ber"])).toBeNull(); // (a trio twice, or one the classes do not make, changes nothing)
  });
});

describe("the sample of trios that the tests which load every order of a trio run on", () => {
  const grid = every(CODES);

  it("is at most five, whatever the number of trios", () => {
    expect(SAMPLE_SIZE).toBe(5);
    expect(sample(grid)).toHaveLength(5);
    expect(sample(grid.slice(0, 14))).toHaveLength(5);
    expect(sample(grid.slice(0, 6))).toHaveLength(5);
    expect(sample(grid.slice(0, 5))).toHaveLength(5);
  });

  it("is every trio when there are five or fewer", () => {
    expect(sample(["pal-mnk-ber"])).toEqual(["pal-mnk-ber"]);
    expect(sample(["pal-shd-ber", "clr-pal-shd"])).toEqual(["clr-pal-shd", "pal-shd-ber"]);
    expect(sample(grid.slice(0, 5))).toEqual(grid.slice(0, 5).sort()); // (in the order of the codes: that is the order a sample is always in)
    expect(sample([])).toEqual([]);
  });

  it("holds distinct trios of the site, in order, and is the same on every run and whatever order the trios are given in", () => {
    const first = sample(grid);
    expect(new Set(first).size).toBe(5);
    expect(first.every((slug) => grid.includes(slug))).toBe(true);
    expect(first).toEqual([...first].sort());
    expect(sample(grid)).toEqual(first);
    expect(sample([...grid].reverse())).toEqual(first);
    expect(sample([...grid].sort(() => 0.5 - Math.sin(grid.length)))).toEqual(first);
  });

  it("takes a different sample with a different seed, and is not the first five of the list", () => {
    expect(sample(grid, 5, 1)).not.toEqual(sample(grid, 5, 2));
    const firstFive = grid.slice(0, 5);
    expect(sample(grid).filter((slug) => firstFive.includes(slug))).not.toHaveLength(5);
    expect(sample(grid, 3)).toHaveLength(3);
    expect(sample(grid, 0)).toEqual([]);
  });

  it("is spread over the list: the seeded sample of many sizes of grid does not stay at its beginning", () => {
    const at = sample(grid).map((slug) => grid.indexOf(slug));
    expect(Math.max(...at)).toBeGreaterThan(grid.length / 4);
  });
});

describe("what the site says of its own trios and classes", () => {
  it("lists the trios of the optimizer's manifest, in order", async () => {
    const manifest = JSON.stringify({ trios: { "pal-shd-ber": [50], "clr-pal-shd": [50], "pal-mnk-ber": [50] } });
    expect(await builtTrios(site({ "/engine-manifest.json": manifest }))).toEqual(["clr-pal-shd", "pal-mnk-ber", "pal-shd-ber"]);
  });

  it("lists the classes the home page offers as chips, in the order of the page (the contract page of the build has sixteen)", async () => {
    expect(await chipCodes(site({ "/": HOME }))).toEqual(CODES);
    const four = '<input type="checkbox" id="class-PAL" value="PAL"><input type="checkbox" id="class-SHD" value="SHD"><input type="checkbox" id="class-BER" value="BER"><input id="trio-search" type="search">';
    expect(await chipCodes(site({ "/": four }))).toEqual(["PAL", "SHD", "BER"]);
    expect(await chipCodes(site({ "/": "<p>no chips</p>" }))).toEqual([]);
  });
});
