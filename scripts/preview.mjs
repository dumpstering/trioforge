// Build the site from a results folder, then serve it the way Cloudflare Pages will, so the real response headers apply:
//
//   node scripts/preview.mjs [RESULTS_FOLDER]        (or: npm run preview -- RESULTS_FOLDER)
//
// The results folder is the argument, else $TRIOFORGE_RESULTS, else the synthetic fixture (fixtures/site/results, built with
// the fixture's own sources manifest). The site goes into site/dist with --noindex (a local preview is never for search
// engines) and `wrangler pages dev` serves it on http://127.0.0.1:8788.
//
// Other variables:
//   TRIOFORGE_PREVIEW_PORT        the port to serve on (default 8788)
//   TRIOFORGE_SOURCES_MANIFEST    a sources manifest other than the default (derived/, or the fixture's for the fixture)
//   TRIOFORGE_PYTHON              the Python that runs the build (default: the one in .venv, else python3 or python)
//
// Playwright's webServer starts this script (playwright.config.mjs). Stopping it stops wrangler and its workerd too.

import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { delimiter, dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURE = join(ROOT, "fixtures", "site");
const DIST = join(ROOT, "site", "dist");
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
const results = given ? resolve(given) : join(FIXTURE, "results");
const usingFixture = relative(join(FIXTURE, "results"), results) === ""; // (relative() ignores the case of a Windows path)
const manifest = process.env.TRIOFORGE_SOURCES_MANIFEST
  ? resolve(process.env.TRIOFORGE_SOURCES_MANIFEST)
  : usingFixture
    ? join(FIXTURE, "sources-manifest.json")
    : null;
if (!existsSync(results)) fail(`the results folder ${results} does not exist`);

function pythonCommand() {
  if (process.env.TRIOFORGE_PYTHON) return process.env.TRIOFORGE_PYTHON;
  const venv = process.platform === "win32" ? join(ROOT, ".venv", "Scripts", "python.exe") : join(ROOT, ".venv", "bin", "python");
  if (existsSync(venv)) return venv;
  return process.platform === "win32" ? "python" : "python3";
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
  ],
  {
    cwd: ROOT,
    stdio: "inherit",
    env: {
      ...process.env,
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
