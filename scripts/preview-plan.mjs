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

/** The two variables that give the site build its optional settings (page counts, the Search Console file): a preview never inherits them from the shell, so that the setting a release is built with cannot reach a browser test. */
export const BUILD_SETTING_VARIABLES = ["TRIOFORGE_ANALYTICS_TOKEN", "TRIOFORGE_GOOGLE_VERIFICATION"];
/** The variable that makes a preview a build with page counts (the third server of the browser tests), and the shape of a token. */
export const PREVIEW_ANALYTICS_VARIABLE = "TRIOFORGE_PREVIEW_ANALYTICS_TOKEN";
const TOKEN = /^[0-9a-f]{32}$/;

/**
 * What a preview gives the site build: the arguments to add to its command line (`--analytics-token <token>` when $TRIOFORGE_PREVIEW_ANALYTICS_TOKEN is set, and only then; a value that is not 32 lower-case hex
 * characters is refused, without repeating it) and the environment it runs in, which is the given one without the variables of the build's own settings (BUILD_SETTING_VARIABLES).
 */
export function buildSettings(env) {
  const token = env[PREVIEW_ANALYTICS_VARIABLE];
  if (token !== undefined && token !== "" && !TOKEN.test(token)) throw new Error(`${PREVIEW_ANALYTICS_VARIABLE} must be 32 lower-case hex characters`);
  const clean = { ...env };
  for (const name of BUILD_SETTING_VARIABLES) delete clean[name];
  return { args: token ? ["--analytics-token", token] : [], env: clean };
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
