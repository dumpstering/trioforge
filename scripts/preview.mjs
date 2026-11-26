// Build the site from a results folder, then serve it the way Cloudflare Pages will, so the real response headers apply:
//
//   node scripts/preview.mjs [RESULTS_FOLDER]        (or: npm run preview -- RESULTS_FOLDER)
//
// The results folder is the argument, else $TRIOFORGE_RESULTS, else the synthetic fixture (fixtures/site/results, built with
// the fixture's own sources manifest). The site goes into site/dist-preview with --noindex (a local preview is never for search
// engines) and `wrangler pages dev` serves it on http://127.0.0.1:8788. It never builds into site/dist, which holds only what
// `python -m trioforge.site.build --out site/dist` writes (a release build): the folders of a preview are all other ones.
//
// Other variables:
//   TRIOFORGE_PREVIEW_PORT        the port to serve on (default 8788)
//   TRIOFORGE_SOURCES_MANIFEST    a sources manifest other than the default (derived/, or the fixture's for the fixture)
//   TRIOFORGE_PYTHON              the Python that runs the build (default: the one in .venv, else python3 or python)
//   TRIOFORGE_NO_ITEM_CATALOG=1   build without the item catalog (--no-item-catalog), for results that were not made from derived/catalog.json (the fixture is always built so)
//   TRIOFORGE_PREVIEW_DIST        the folder the site is built into (default site/dist-preview), so that two previews can run side by side
//   TRIOFORGE_PREVIEW_ANALYTICS_TOKEN   a token (32 lower-case hex characters) makes the preview a build with page counts, as `--analytics-token` does (the browser tests' third server, with an invented one; the
//                                 beacon is then answered by the test, never fetched). The build settings of a release ($TRIOFORGE_ANALYTICS_TOKEN, $TRIOFORGE_GOOGLE_VERIFICATION) are never passed on to a preview.
//   TRIOFORGE_PREVIEW_EXALT=1     for the section Effects to exalt of a trio page, which needs the two files of the effects layer (effects.json and the exalt.json of each trio):
//                                 results that have them (a release's do) are built as they are; the fixture results, made before the layer, are copied under build/ and given
//                                 the files by the code that makes them for a release (scripts/preview-plan.mjs says which); other results without them are refused
//
// Playwright's webServer starts this script (playwright.config.mjs). Stopping it stops wrangler and its workerd too.

import { spawn, spawnSync } from "node:child_process";
import { cpSync, existsSync, rmSync } from "node:fs";
import { delimiter, dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { buildSettings, distFolder, exaltResults } from "./preview-plan.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURE = join(ROOT, "fixtures", "site");
function chooseDist() {
  try {
    return distFolder(ROOT, process.env);
  } catch (error) {
    return fail(error.message);
  }
}
const DIST = chooseDist();
// wrangler wants a compatibility date; this is a static site, so the value changes nothing except the warning it prints without one
const COMPATIBILITY_DATE = "2026-09-26";

function fail(message) {
  console.error(`preview: ${message}`);
  process.exit(2);
}

const args = process.argv.slice(2);
if (args.includes("-h") || args.includes("--help")) {
  console.log("usage: node scripts/preview.mjs [RESULTS_FOLDER]   (see the comment at the top of the script)");
  process.exit(0);
}
if (args.length > 1) fail("expected at most one argument: the results folder");

const port = Number(process.env.TRIOFORGE_PREVIEW_PORT ?? 8788);
if (!Number.isInteger(port) || port < 1 || port > 65535) fail("TRIOFORGE_PREVIEW_PORT must be a port number");

const given = args[0] ?? process.env.TRIOFORGE_RESULTS;
const chosen = given ? resolve(given) : join(FIXTURE, "results");
const usingFixture = relative(join(FIXTURE, "results"), chosen) === ""; // (relative() ignores the case of a Windows path)
const manifest = process.env.TRIOFORGE_SOURCES_MANIFEST
  ? resolve(process.env.TRIOFORGE_SOURCES_MANIFEST)
  : usingFixture
    ? join(FIXTURE, "sources-manifest.json")
    : null;
if (!existsSync(chosen)) fail(`the results folder ${chosen} does not exist`);

function pythonCommand() {
  if (process.env.TRIOFORGE_PYTHON) return process.env.TRIOFORGE_PYTHON;
  const venv = process.platform === "win32" ? join(ROOT, ".venv", "Scripts", "python.exe") : join(ROOT, ".venv", "bin", "python");
  if (existsSync(venv)) return venv;
  return process.platform === "win32" ? "python" : "python3";
}

const pythonEnv = { ...process.env, PYTHONPATH: [join(ROOT, "pipeline"), process.env.PYTHONPATH].filter(Boolean).join(delimiter), PYTHONUTF8: "1" };

/** A copy of the results (in build/, which git ignores) with the two files of the effects layer in it, for a preview of the section Effects to exalt. */
function withEffects(source) {
  const copy = join(ROOT, "build", "preview-results-exalt");
  rmSync(copy, { recursive: true, force: true });
  cpSync(source, copy, { recursive: true });
  const made = spawnSync(pythonCommand(), ["-m", "trioforge.effects.fixtures", "--site", copy], { cwd: ROOT, stdio: "inherit", env: pythonEnv });
  if (made.error || made.status !== 0) fail("could not make the effects files of the preview");
  return copy;
}

function exaltPreviewResults() {
  const plan = exaltResults({ usingFixture, hasEffects: existsSync(join(chosen, "effects.json")) });
  if (plan.use === "refuse") fail(plan.message);
  return plan.use === "given" ? chosen : withEffects(chosen);
}

const results = process.env.TRIOFORGE_PREVIEW_EXALT === "1" ? exaltPreviewResults() : chosen;

let settings;
try {
  settings = buildSettings(process.env);
} catch (error) {
  fail(error.message);
}

// 1. build (the generator is run as a module, so the package folder goes on the path)
const build = spawnSync(
  pythonCommand(),
  [
    "-m",
    "trioforge.site.build",
    "--results",
    results,
    "--out",
    DIST,
    "--noindex",
    ...(manifest ? ["--sources-manifest", manifest] : []),
    // the pictures of the armor and the instruments are made from the catalog the results were made from, and the build stops when derived/catalog.json is not it: the synthetic fixture was not made
    // from it, so its previews are built without (and say so); real results are built as a release is, with the catalog
    ...(usingFixture || process.env.TRIOFORGE_NO_ITEM_CATALOG === "1" ? ["--no-item-catalog"] : []),
    ...settings.args,
  ],
  {
    cwd: ROOT,
    stdio: "inherit",
    env: {
      ...settings.env,
      PYTHONPATH: [join(ROOT, "pipeline"), process.env.PYTHONPATH].filter(Boolean).join(delimiter),
      PYTHONUTF8: "1",
    },
  },
);
if (build.error) fail(`could not run the build: ${build.error.message}`);
if (build.status !== 0) fail(`the site build failed (exit status ${build.status})`);

// 2. serve
const wrangler = join(ROOT, "node_modules", "wrangler", "bin", "wrangler.js");
if (!existsSync(wrangler)) fail("wrangler is not installed: run `npm ci --ignore-scripts`");
const server = spawn(
  process.execPath,
  [wrangler, "pages", "dev", DIST, "--ip", "127.0.0.1", "--port", String(port), "--compatibility-date", COMPATIBILITY_DATE],
  { cwd: ROOT, stdio: "inherit", env: { ...process.env, WRANGLER_SEND_METRICS: "false" } },
);
console.log(`preview: serving ${DIST} on http://127.0.0.1:${port}/ (results: ${results})`);

function stop() {
  if (server.exitCode !== null || server.signalCode !== null || server.pid === undefined) return;
  // wrangler starts workerd under itself; on Windows a plain kill would leave it running
  if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(server.pid), "/T", "/F"], { stdio: "ignore" });
  else server.kill("SIGTERM");
}

for (const signal of ["SIGINT", "SIGTERM", "SIGBREAK", "SIGHUP"]) {
  process.on(signal, () => {
    stop();
    process.exit(0);
  });
}
process.on("exit", stop);
server.on("error", (error) => fail(`could not start wrangler: ${error.message}`));
server.on("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
