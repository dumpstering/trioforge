// Two decisions of scripts/preview.mjs, as plain functions so that tests-js/preview.test.mjs can hold them without a build or a browser.

import { resolve } from "node:path";

/** The folder `python -m trioforge.site.build --out site/dist` writes (a release build): no preview or browser test ever builds into it. */
export const RELEASE_DIST = "site/dist";
/** Where `npm run preview` builds when $TRIOFORGE_PREVIEW_DIST does not say otherwise (the browser tests name their own folders in playwright.config.mjs). */
export const DEFAULT_DIST = "site/dist-preview";

/**
 * The folder a preview builds the site into, as an absolute path under `root`. A value that comes to site/dist in any spelling (./site/dist, site/dist/, site/../site/dist, an absolute
 * path) is refused: the build replaces its output folder, and site/dist holds a release build.
 */
export function distFolder(root, env) {
  const folder = resolve(root, env.TRIOFORGE_PREVIEW_DIST ? env.TRIOFORGE_PREVIEW_DIST : DEFAULT_DIST);
  if (folder === resolve(root, RELEASE_DIST)) throw new Error(`a preview never builds into ${RELEASE_DIST}, which holds a release build: name another folder in TRIOFORGE_PREVIEW_DIST`);
  return folder;
}

/**
 * Which results the second preview (the one with the section Effects to exalt, TRIOFORGE_PREVIEW_EXALT=1) is built from.
 *
 *   given                  the results as they are: they have effects.json (and the exalt.json of each trio), as the results of a release do
 *   fixture-with-effects   a copy of the synthetic fixture results with the two files made for them by trioforge.effects.fixtures (the fixture was made before the layer)
 *   refuse                 results that are not the fixture and have no effects files: the files made for the fixture name the fixture's items, which other results do not have
 */
export function exaltResults({ usingFixture, hasEffects }) {
  if (hasEffects) return { use: "given" };
  if (usingFixture) return { use: "fixture-with-effects" };
  return {
    use: "refuse",
    message:
      "the results have no effects.json, which the section Effects to exalt needs, and the files made for the synthetic fixture cannot stand in for them (they name the fixture's items). " +
      "Use results of a precompute run that wrote the effects layer (a release's), or the fixture.",
  };
}
