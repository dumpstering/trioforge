// What the browser tests ask of the site about its trios, so that they run unchanged on one trio (the fixture), on a few, on the whole grid of 560, and on a grid whose every trio is built
// (where there is none left to be "coming soon"): the trios the build made (from the optimizer's own list, not from the page that is being tested), the classes the home page offers, the first
// trio that is not built (or none), and the sample of trios that the tests that load every order of a trio run on. The functions are plain (tests-js/e2e-trios.test.mjs tests them), and
// `request` is Playwright's own.

/** The most trios that a test which loads each of six orders of a trio is run on: six loads of a trio page for each of 560 trios would not end in any time limit. */
export const SAMPLE_SIZE = 5;
/** The seed of the sample: it is the same on every run (a failure can be run again), and it does not depend on the order in which the trios are listed. */
export const SAMPLE_SEED = 20261018;

/** The slugs of the trios the site was built with, in order. */
export async function builtTrios(request) {
  const manifest = await (await request.get("/engine-manifest.json")).json();
  return Object.keys(manifest.trios).sort();
}

/** The codes of the classes the home page offers as chips, in the order of the page. */
export async function chipCodes(request) {
  const html = await (await request.get("/")).text();
  return [...html.matchAll(/<input type="checkbox" id="class-[A-Z]+" value="([A-Z]+)">/g)].map((found) => found[1]);
}

/** How many trios some classes make: the ways to choose three of them. */
export function trioCount(classes) {
  return classes < 3 ? 0 : (classes * (classes - 1) * (classes - 2)) / 6;
}

/** The first trio, in the order of the classes, that is not among the built ones (the slug of its page), or null when every trio the classes make is built. */
export function firstUnbuilt(codes, built) {
  const have = new Set(built);
  for (const [i, a] of codes.entries()) {
    for (const [j, b] of codes.slice(i + 1).entries()) {
      for (const c of codes.slice(i + j + 2)) {
        const slug = [a, b, c].map((code) => code.toLowerCase()).join("-");
        if (!have.has(slug)) return slug;
      }
    }
  }
  return null;
}

/** A small deterministic generator of numbers in [0, 1): the same numbers for the same seed (mulberry32). */
function generator(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let mixed = Math.imul(state ^ (state >>> 15), state | 1);
    mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 2 ** 32;
  };
}

/**
 * At most `size` of the trios (every one when there are no more), chosen with a seeded generator from the trios put in order: the same trios on every run, and whatever order they were
 * listed in. The sample is returned in order.
 */
export function sample(trios, size = SAMPLE_SIZE, seed = SAMPLE_SEED) {
  const pool = [...trios].sort();
  if (pool.length <= size) return pool;
  const next = generator(seed);
  for (let at = pool.length - 1; at > 0; at -= 1) {
    const other = Math.floor(next() * (at + 1));
    [pool[at], pool[other]] = [pool[other], pool[at]];
  }
  return pool.slice(0, Math.max(0, size)).sort();
}
