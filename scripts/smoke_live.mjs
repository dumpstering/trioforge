// The smoke check of the live site, weekly and after each deploy:
//
//   node scripts/smoke_live.mjs [--base https://trioforge.pages.dev] [--indexable] [--analytics] [--expect-data data-YYYY-MM-DD[-N]|newest|none] [--releases-dir releases]
//                               [--seed N] [--out DIR] [--headers-file site/_headers] [--trios 5] [--items 5] [--wait 10] [--settle 5] [--pace 0]
//
// Playwright (Chromium) loads 5 pages of trios and 5 pages of items of the site, and the page of an address that does not exist, and checks each:
//
//   * the status: 200 (404 for the address that does not exist, whose page must be the 404 page of the site and carry the policy that page gives itself);
//   * the page is served at its own address: a page that ends at another address (the server sent it, or a script of its own moved it) fails, whatever the place it was
//     sent to answers with, and the main element of a trio page and of an item page must say that it is one (data-page);
//   * the response headers: Content-Security-Policy, X-Content-Type-Options and Referrer-Policy are those of site/_headers (the file the site is built to be
//     deployed with; --headers-file names another, for a build whose policy was made for it), and X-Robots-Tag is the "noindex" of a preview unless --indexable
//     says the site is the real one, when it must not be there. A site built with page counts (--analytics-token) has the two hosts of the counter in its policy, and is checked with --analytics:
//     the policy must then be the committed one plus exactly those two hosts (the script host in script-src, the data host in connect-src), which needs no other file, so the weekly task can say it in
//     its options (the build also writes that policy into its own _headers, but that folder is not kept);
//   * no counting tag in the page as the server sent it, in either mode: no page of this site has a script tag for the page counter (the page script adds it, to a page opened with no kit link), so a
//     page whose HTML holds "cloudflareinsights", "data-cf-beacon" or "beacon.min" has had a tag put into it, which the switch of the Cloudflare dashboard for Web Analytics does at the edge (and a counting
//     site's policy would let it load, on a kit page too). Only the body of the response to the navigation is read, and only when it says it is HTML: the page script's own bundle names the counter's
//     address and is another response, which is never read, so it is told apart by being a sub-resource and not the document;
//   * with --analytics, one trio page is opened with an invented kit fragment (#k=...), and it must make no request to either host of the counter: a page opened from a kit link is never counted;
//   * no console error and no uncaught error of the page, watched for until the page's network has been idle and then --settle seconds more (5 by default), so that an
//     error a page makes some seconds after it loaded is seen too;
//   * the page script ran: the theme button, which the page hides until its script has run, is showing (the page gets --wait seconds for it, 10 by default);
//   * the data release a trio page or an item page names (the data-release of a trio page, else the date of the strip at the top of the page) is the one expected: the
//     release of the newest pointer in releases/ (releases/<tag>.json, the newest by day and then by the number after it) unless --expect-data gives a tag or says none
//     (a page that names only the date matches the release of that day, and the manifest of the optimizer must name the release exactly); the 404 page is not asked,
//     since what it names is not what the data is. The report says where the expectation came from.
//
// The pages are chosen from the site's own lists with a seeded choice: the trios of /engine-manifest.json, and the items of the item table the manifest names that
// have a page (the strict and the wiki ones). The seed is the number of the ISO week (202642 for the 42nd week of 2026) unless --seed gives one, so that a week's
// check can be run again on the same pages and the next week's looks at others. The seed is in the report.
//
// --pace S spaces the requests at least S seconds apart (the real site's check runs the browser's own requests one by one at that pace); --trios and --items give
// the number of pages of each kind. Nothing is written but the stamp and the log: when everything passes, smoke-live.last-run gets the UTC time, in the form the
// release build reads, in the folder of the checks (see checksDir; --out names another); a failure writes no stamp. Every run, whatever its outcome, adds one line
// to smoke-live.log in that folder (the time, ok, failed, refused or error, and the one line the run printed), keeping the last 200: a console that closes at exit
// shows nothing of a task that nobody watched.
//
// Exit codes: 0 everything passed; 1 something failed (a short list of what is printed); 2 not run (bad options, no browser, no headers file).

import { existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, renameSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs as parseCommandLine } from "node:util";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(HERE, "..");

export const DEFAULT_BASE = "https://trioforge.pages.dev";
export const TRIO_COUNT = 5;
export const ITEM_COUNT = 5;
export const STAMP_NAME = "smoke-live";
/** A log keeps this many of its last lines. */
export const LOG_LINES = 200;
const MAX_LOG_TEXT = 400;
const OUTCOMES = ["ok", "failed", "refused", "error", "interrupted"];
/** The variable that names the folder of the stamps, the logs and the reports of the scheduled checks (an absolute path). */
export const CHECKS_ENV = "TRIOFORGE_CHECKS_DIR";
/** An address the site has no file for, and that the 404 page does not move the visitor away from (it moves only the addresses of a trio in another order). */
export const NOTFOUND_PATH = "/no-such-page-smoke-check/";
/** What the 404 page says of itself in a <meta http-equiv="Content-Security-Policy"> element at the top of its head (build.NOTFOUND_POLICY of the site build). */
export const NOTFOUND_POLICY = "script-src 'self'; connect-src 'none'";
export const DEFAULT_WAIT_SECONDS = 10;
export const DEFAULT_SETTLE_SECONDS = 5;
export const MOST_LISTED = 20;
const ITEM_PAGE_LEVELS = ["strict", "wiki"];
const REQUEST_TIMEOUT_MS = 30_000;
const MOST_PACED_REQUESTS = 300; // the requests of a page that its load is given time for, when they are paced
// what the browser itself writes to the console about the status of the document it was sent: the status is checked on its own
const BROWSER_STATUS_NOTE = /^Failed to load resource: the server responded with a status of \d{3}(?: \([^()]*\))?$/;
const IDLE_CAP_MS = 20_000; // the longest a page is waited for to have an idle network (one that polls never has: it is watched from then on)
const RELEASE_TAG = /^data-\d{4}-\d{2}-\d{2}(-\d+)?$/;
const POINTER_NAME = /^(data-(\d{4})-(\d{2})-(\d{2})(?:-(\d+))?)\.json$/;
const SLUG = /^[a-z0-9-]{1,60}$/;

export const USAGE = `usage: node scripts/smoke_live.mjs [--base URL] [--indexable] [--expect-data TAG|newest|none] [--releases-dir DIR] [--seed N] [--out DIR]
                                  [--headers-file FILE] [--trios N] [--items N] [--wait SECONDS] [--settle SECONDS] [--pace SECONDS]
  --base URL           the site (default ${DEFAULT_BASE}); an address with no path
  --indexable          the site is the real one: it must not send X-Robots-Tag noindex (without this it must)
  --analytics          the site is built with page counts: its policy must be the committed one plus exactly the two hosts of the counter (https://static.cloudflareinsights.com in
                       script-src, https://cloudflareinsights.com in connect-src), and without this switch it must be the committed one as it is
  --expect-data TAG|newest|none
                       the data release the manifest and every trio and item page must name, such as data-2026-10-14; newest (the default) is the release of the newest
                       pointer in the releases folder, and nothing is expected when it has none; none expects nothing
  --releases-dir DIR   where the pointers of the releases are, releases/<tag>.json (default: releases of the repository)
  --seed N             the seed of the choice of pages (default: the number of the ISO week, such as 202642)
  --out DIR            where the stamp smoke-live.last-run is written when everything passes (default: the folder of the checks, outside every worktree:
                       $TRIOFORGE_CHECKS_DIR, else ~/.local/state/trioforge/checks)
  --headers-file FILE  the headers the site must send (default: site/_headers)
  --trios N, --items N the number of pages of each kind, 1 to 100 (default ${TRIO_COUNT} and ${ITEM_COUNT}); a check needs at least one of each
  --wait SECONDS       how long a page has to show the theme button (default ${DEFAULT_WAIT_SECONDS})
  --settle SECONDS     how long a page is watched for errors after its network went idle (default ${DEFAULT_SETTLE_SECONDS})
  --pace SECONDS       the least time between two requests (default 0: none)`;

/** The check cannot run as it was asked to (the headers file, the browser, the command line): exit status 2, and no stamp. */
export class UsageError extends Error {}
/** The command line is not one: the usage is printed after the line that says what is wrong with it. */
export class CommandLineError extends UsageError {}
/** A thing the check looked for and did not find in the site: it is a problem of the site, listed, and exit status 1. */
class Problem extends Error {}

// ---- the command line --------------------------------------------------------------------------------------------------------------------

const OPTIONS = {
  base: { type: "string" },
  indexable: { type: "boolean" },
  analytics: { type: "boolean" },
  "expect-data": { type: "string" },
  "releases-dir": { type: "string" },
  seed: { type: "string" },
  out: { type: "string" },
  "headers-file": { type: "string" },
  trios: { type: "string" },
  items: { type: "string" },
  wait: { type: "string" },
  settle: { type: "string" },
  pace: { type: "string" },
  help: { type: "boolean", short: "h" },
};

function number(name, text, { min, max, whole = true }) {
  const value = Number(text);
  if (text.trim() === "" || !Number.isFinite(value) || (whole && !Number.isInteger(value)) || value < min || value > max) {
    throw new CommandLineError(`--${name} must be ${whole ? "a whole number" : "a number"} from ${min} to ${max}`);
  }
  return value;
}

/** The ISO 8601 week of a date as year*100+week (202642 for 2026-10-18), by the UTC calendar: the default seed. */
export function weekSeed(date) {
  const day = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const weekday = day.getUTCDay() || 7; // Monday 1 ... Sunday 7
  day.setUTCDate(day.getUTCDate() + 4 - weekday); // the fourth day of this week (counting from Monday) decides the year
  const yearStart = Date.UTC(day.getUTCFullYear(), 0, 1);
  const week = Math.ceil(((day.getTime() - yearStart) / 86_400_000 + 1) / 7);
  return day.getUTCFullYear() * 100 + week;
}

/**
 * The folder of the stamps, the logs and the reports of the scheduled checks, which lies outside every worktree: the checks run in one checkout and a release is built
 * in a worktree of its own, which reads the stamps from the same place. The rules are those of trioforge.checks_dir (pipeline/trioforge/checks_dir.py), which the Python
 * checks and the release build use, and a test holds the two to give the same folder: $TRIOFORGE_CHECKS_DIR if it is set (an empty value counts as unset; an absolute path
 * by the one rule of isAbsolutePath; a relative one is refused, since two working folders would mean two folders, and so is one in a git work tree), else
 * ~/.local/state/trioforge/checks, on Windows too (never %LOCALAPPDATA%, which a program run from the Claude app writes in a private copy of). `env`, `platform` and `home` are
 * those of the process unless a test gives its own. The work-tree rule is about folders of THIS computer: a path of another kind of platform than the computer's (a Windows
 * path asked by a test on a Linux runner, which is a relative name there and would lie in the checkout) is resolved by the rules of its own platform and is not asked about, unless it is rooted
 * (`/x` on Windows is on the current drive). On Windows no part of the path may end in a dot or a space (`.` and `..` are fine): Windows reads such a name without them, and Python and Node do
 * not agree on the real path of one (a junction written `j.` is the folder `j` to Python and no folder at all to Node). The rule is asked of the path AND of its real path (a junction or a symbolic link into a checkout is refused, and so is a path through one that does not
 * exist yet). `exists` is how a folder is looked for and `real` how its real path is had (the process's own unless a test gives one).
 */
export function checksDir(env = process.env, platform = process.platform, home = os.homedir(), { exists = existsSync, real = realpathSync.native } = {}) {
  const given = (env[CHECKS_ENV] ?? "").trim();
  if (given !== "") {
    if (!isAbsolutePath(given, platform)) {
      throw new UsageError(
        `${CHECKS_ENV} must be an absolute path (it is ${JSON.stringify(given)}; on Windows a drive or a UNC path, elsewhere a path that starts with /): ` +
          "the checks and the release build run in different folders, and must find the same one",
      );
    }
    if ((platform === "win32" || process.platform === "win32") && hasPartEndingInDotOrSpace(given)) {
      // (a path that Windows reads, whatever the platform that was given)
      throw new UsageError(
        `${CHECKS_ENV} must not have a part that ends in a dot or a space (${JSON.stringify(given)}): Windows reads such a name without them, and the checks would not agree on which folder it is`,
      );
    }
    const ownKind = (platform === "win32") === (process.platform === "win32"); // (a Windows path on Windows, any other on any other)
    const written = (platform === "win32" ? path.win32 : path.posix).resolve(given);
    if (!ownKind && path.parse(given).root === "") return written; // (not a path of this computer: C:\x on Linux is a relative name)
    const folder = path.resolve(given); // (the path on this computer)
    if (inAWorkTree(folder, exists) || inAWorkTree(realPathOf(folder, exists, real), exists)) {
      throw new UsageError(`${CHECKS_ENV} must not be inside a git work tree (${JSON.stringify(given)}): a stamp there would be a file of that checkout`);
    }
    return ownKind ? folder : written;
  }
  return path.join(home, ".local", "state", "trioforge", "checks");
}

/** Whether a part of `text` (cut at / and \) ends in a dot or a space, other than the parts . and ..: Windows reads such a name without them (the same rule as trioforge.checks_dir). */
function hasPartEndingInDotOrSpace(text) {
  return text.split(/[\\/]+/).some((part) => part !== "" && part !== "." && part !== ".." && /[. ]$/.test(part));
}

const WINDOWS_ABSOLUTE = /^(?:[A-Za-z]:[\\/]|[\\/]{2}[^\\/]+[\\/]+[^\\/])/; // a drive and a separator, or \\server\share

/**
 * Whether a path is absolute by the one rule of the checks, the same as in Python (trioforge.checks_dir): on Windows a drive and a separator, or a UNC path \\server\share; elsewhere a path
 * that starts with /. A path that has only a root or only a drive is relative to something, and is not absolute. No file is looked at.
 */
export function isAbsolutePath(text, platform = process.platform) {
  return platform === "win32" ? WINDOWS_ABSOLUTE.test(text) : text.startsWith("/");
}

/** The folder with every junction and symbolic link in it followed as far as it exists, the rest (not made yet) kept: where it really is. The folder itself when it cannot be had. */
function realPathOf(folder, exists, real) {
  const rest = [];
  let current = folder;
  for (;;) {
    if (exists(current)) {
      try {
        return path.join(real(current), ...rest.reverse());
      } catch {
        return folder;
      }
    }
    const parent = path.dirname(current);
    if (parent === current) return folder;
    rest.push(path.basename(current));
    current = parent;
  }
}

/** Whether a folder is in a git work tree: it or a folder above it holds a .git (a directory, or the file of a linked worktree). The folder need not be there yet. */
function inAWorkTree(folder, exists = existsSync) {
  for (let current = folder; ; current = path.dirname(current)) {
    if (exists(path.join(current, ".git"))) return true;
    if (path.dirname(current) === current) return false;
  }
}

/** The options of a command line, checked. Raises UsageError for anything that is not an option, a value that makes no sense, or an address with a path. */
export function parseArgs(argv, now = new Date(), env = process.env) {
  let parsed;
  try {
    parsed = parseCommandLine({ args: argv, options: OPTIONS, allowPositionals: false, strict: true });
  } catch (error) {
    throw new CommandLineError(error.message.split("\n")[0]);
  }
  const given = parsed.values;
  let base;
  try {
    const address = new URL(given.base ?? DEFAULT_BASE);
    const plain = ["http:", "https:"].includes(address.protocol) && (address.pathname === "/" || address.pathname === "") && !address.search && !address.hash && !address.username && !address.password;
    if (!plain) throw new Error("not an origin");
    base = address.origin;
  } catch {
    throw new CommandLineError("--base must be an http or https address with no path, such as https://trioforge.pages.dev");
  }
  for (const [name, what] of [["out", "folder"], ["releases-dir", "folder"], ["headers-file", "file"]]) {
    if (given[name] !== undefined && given[name].trim() === "") throw new CommandLineError(`--${name} must name a ${what}`); // (an empty one would be the working folder)
  }
  const expectation = given["expect-data"] ?? "newest";
  if (!["newest", "none"].includes(expectation) && !RELEASE_TAG.test(expectation)) {
    throw new CommandLineError("--expect-data must look like data-2026-10-14 (or data-2026-10-14-2 for a second release of the day), or be newest or none");
  }
  return {
    help: given.help === true,
    base,
    indexable: given.indexable === true,
    analytics: given.analytics === true,
    expectData: RELEASE_TAG.test(expectation) ? expectation : null,
    expectFrom: RELEASE_TAG.test(expectation) ? "tag" : expectation, // "tag" (given), "newest" (the newest pointer, found when the check runs) or "none"
    releasesDir: path.resolve(given["releases-dir"] ?? path.join(ROOT, "releases")),
    seed: given.seed === undefined ? weekSeed(now) : number("seed", given.seed, { min: 0, max: 2 ** 32 - 1 }),
    out: path.resolve(given.out ?? checksDir(env)),
    headersFile: path.resolve(given["headers-file"] ?? path.join(ROOT, "site", "_headers")),
    trios: given.trios === undefined ? TRIO_COUNT : number("trios", given.trios, { min: 1, max: 100 }),
    items: given.items === undefined ? ITEM_COUNT : number("items", given.items, { min: 1, max: 100 }),
    waitMs: Math.round((given.wait === undefined ? DEFAULT_WAIT_SECONDS : number("wait", given.wait, { min: 0.1, max: 300, whole: false })) * 1000),
    settleMs: Math.round((given.settle === undefined ? DEFAULT_SETTLE_SECONDS : number("settle", given.settle, { min: 0, max: 60, whole: false })) * 1000),
    paceSeconds: given.pace === undefined ? 0 : number("pace", given.pace, { min: 0, max: 60, whole: false }),
  };
}

// ---- the release that is expected ------------------------------------------------------------------------------------------------------------

function isCalendarDate(year, month, day) {
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

/**
 * The tag of the newest pointer in a folder of them (`<tag>.json`, the tag a real date `data-YYYY-MM-DD` with an optional `-N`): the latest day, and on a day the highest number
 * after it (none is before 1, and 10 after 9). Null for a folder that is not there or holds none; anything else in the folder (other files, temporary files, a date that is
 * not one, a folder with such a name) is passed over. Raises UsageError for a folder that cannot be read.
 */
export function newestRelease(folder) {
  let entries;
  try {
    entries = readdirSync(folder, { withFileTypes: true });
  } catch (error) {
    if (error?.code === "ENOENT" || error?.code === "ENOTDIR") return null;
    throw new UsageError(`cannot read the folder of the release pointers (${error?.code ?? error?.name ?? "error"})`);
  }
  let best = null;
  for (const entry of entries) {
    const found = entry.isFile() ? POINTER_NAME.exec(entry.name) : null;
    if (found === null || !isCalendarDate(Number(found[2]), Number(found[3]), Number(found[4]))) continue;
    const day = `${found[2]}-${found[3]}-${found[4]}`;
    const number = found[5] === undefined ? 0 : Number(found[5]);
    if (best === null || day > best.day || (day === best.day && number > best.number)) best = { tag: found[1], day, number };
  }
  return best === null ? null : best.tag;
}

// ---- the choice of pages ---------------------------------------------------------------------------------------------------------------------

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

/** At most `size` of the names (all of them when there are no more), chosen with a seeded generator from the names put in order: the same names for the same seed, in whatever order they were listed. The choice is returned in order. */
export function sample(names, size, seed) {
  const pool = [...new Set(names)].sort();
  if (pool.length <= size) return pool;
  const next = generator(seed);
  for (let at = pool.length - 1; at > 0; at -= 1) {
    const other = Math.floor(next() * (at + 1));
    [pool[at], pool[other]] = [pool[other], pool[at]];
  }
  return pool.slice(0, Math.max(0, size)).sort();
}

/** The item pages of an item table of the optimizer: the keys of its strict and wiki items, which are the ones the site gives a page. */
export function itemPageKeys(table) {
  const items = Array.isArray(table?.items) ? table.items : null;
  if (items === null) throw new Problem("the item table has no list of items");
  const keys = [];
  for (const record of items) {
    const key = record?.key ?? (Number.isInteger(record?.id) ? `w${record.id}` : null);
    if (ITEM_PAGE_LEVELS.includes(record?.evidence?.level) && typeof key === "string" && SLUG.test(key)) keys.push(key);
  }
  return keys;
}

/** The trios of the manifest of the optimizer, which is the site's own list of the trios it was built with. */
export function trioSlugs(manifest) {
  const trios = manifest?.trios;
  if (trios === null || typeof trios !== "object" || Array.isArray(trios)) throw new Problem("the manifest has no list of trios");
  return Object.keys(trios).filter((slug) => SLUG.test(slug));
}

// ---- the pace --------------------------------------------------------------------------------------------------------------------------------

/** `await pace()` before each request: the starts are at least `seconds` apart (nothing waits when it is 0). The clock and the sleep can be replaced. */
export function makePacer(seconds, { now = () => performance.now(), sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) } = {}) {
  let next = 0;
  return async () => {
    if (!(seconds > 0)) return;
    const at = now();
    const start = Math.max(at, next);
    next = start + seconds * 1000;
    if (start > at) await sleep(start - at);
  };
}

// ---- the headers -------------------------------------------------------------------------------------------------------------------------

/** The headers a _headers file sets for the paths `/*`, lower-cased names, in a Map. A block is a path pattern line and the indented `Name: value` lines under it. */
export function parseHeaderBlock(text, pattern = "/*") {
  const blocks = new Map();
  let current = null;
  for (const line of text.split(/\r?\n/)) {
    if (line.trim() === "" || line.trim().startsWith("#")) continue;
    const header = /^\s+([A-Za-z][A-Za-z-]*):\s*(.*?)\s*$/.exec(line);
    if (header === null) {
      current = new Map();
      blocks.set(line.trim(), current);
    } else if (current !== null) {
      current.set(header[1].toLowerCase(), header[2]);
    }
  }
  const block = blocks.get(pattern);
  if (block === undefined) throw new UsageError(`the headers file has no block for ${pattern}`);
  return block;
}

/** The two hosts that a site built with page counts adds to the policy: where the counter's script is loaded from (script-src) and where it sends its report (connect-src). */
export const COUNTER_SCRIPT_HOST = "https://static.cloudflareinsights.com";
export const COUNTER_DATA_HOST = "https://cloudflareinsights.com";

/** What no page of the site holds as it is served (in lower case): the host of the counter's script, the attribute that carries its token and the script's name. */
export const COUNTER_MARKERS = Object.freeze(["cloudflareinsights", "data-cf-beacon", "beacon.min"]);
/** The most that the kit link check waits, after it has closed the page, for what the page asks for as it goes. */
const MOST_CLOSE_WAIT_MS = 1000;
/** The least that the kit link check waits after it has sent the page away (the report of a counter at pagehide is a request like any other: it takes a moment to be made). */
const LEAVING_WAIT_MS = 300;
/** The invented kit fragment of the kit link check (a payload of no kit: the page only has to see the shape). */
export const KIT_PROBE_FRAGMENT = "#k=AQIDBAUGBwgJCgsMDQ4P";

/** The first mark of a counting tag in the text of a page, or null (compared in lower case). */
export function countingTagIn(body) {
  const lowered = String(body).toLowerCase();
  return COUNTER_MARKERS.find((marker) => lowered.includes(marker)) ?? null;
}

/** Whether an address is a request to either host of the counter (by its host, not by a word in it). */
export function isCounterRequest(address) {
  try {
    const { hostname } = new URL(address);
    return [COUNTER_SCRIPT_HOST, COUNTER_DATA_HOST].some((host) => new URL(host).hostname === hostname.toLowerCase());
  } catch {
    return false;
  }
}

/**
 * The policy of a site built with page counts, from the policy of the committed file: exactly the two hosts added, the script host to script-src and the data host to connect-src (the build's
 * ANALYTICS_CSP; a test holds the two to the same policy). Raises UsageError when the policy is not the one the hosts can be added to, or names a host already.
 */
function withCounterHosts(policy) {
  const script = "script-src 'self' 'wasm-unsafe-eval'";
  const connect = "connect-src 'self'";
  const once = (part) => policy.split(part).length === 2;
  if (!once(script) || !once(connect) || policy.includes("cloudflare")) {
    throw new UsageError("the headers file's policy is not the policy of the site with no host, which the two hosts of the counter can be added to");
  }
  return policy.replace(script, `${script} ${COUNTER_SCRIPT_HOST}`).replace(connect, `${connect} ${COUNTER_DATA_HOST}`);
}

/**
 * The headers every page must carry: the three that site/_headers sets, as it sets them. With `analytics` (a site built with page counts) the policy is the file's plus exactly the two hosts of
 * the counter (:func:`withCounterHosts`), so the check needs no file but the committed one.
 */
export function expectedHeaders(text, { analytics = false } = {}) {
  const block = parseHeaderBlock(text);
  const wanted = {};
  for (const name of ["content-security-policy", "x-content-type-options", "referrer-policy"]) {
    if (!block.has(name)) throw new UsageError(`the headers file sets no ${name} for /*`);
    wanted[name] = block.get(name);
  }
  if (analytics) wanted["content-security-policy"] = withCounterHosts(wanted["content-security-policy"]);
  return wanted;
}

const squeeze = (text) => String(text).replace(/\s+/g, " ").trim();

/**
 * What is wrong with the headers of a response, as short sentences: the policy, nosniff and the referrer policy must be what the file says, and X-Robots-Tag must say noindex
 * when the site is a preview and must not when it is the real site (`indexable`). The headers are those of Playwright's `response.headers()`, with lower-case names.
 */
export function checkHeaders(headers, expected, { indexable, analytics = false }) {
  const problems = [];
  for (const [name, wanted] of Object.entries(expected)) {
    const got = headers[name];
    if (got === undefined) problems.push(`no ${name} header`);
    else if (squeeze(got).toLowerCase() !== squeeze(wanted).toLowerCase()) {
      problems.push(`${name} is not what site/_headers sets${analytics && name === "content-security-policy" ? " with the two hosts of the counter added to script-src and connect-src" : ""}`);
    }
  }
  const robots = (headers["x-robots-tag"] ?? "").toLowerCase();
  const blocks = /\bnoindex\b|\bnone\b/.test(robots);
  if (!indexable && !blocks) problems.push("no x-robots-tag noindex (a preview must keep search engines out)");
  if (indexable && blocks) problems.push("x-robots-tag keeps search engines out, and the site is meant to be found");
  return problems;
}

// ---- the data release ---------------------------------------------------------------------------------------------------------------------

/** Run in the page: the data release it names. A trio page has it in `data-release`; every page has the date of the data in the strip at the top. */
export function readRelease() {
  const marked = document.querySelector("[data-release]");
  if (marked) return marked.getAttribute("data-release");
  const time = document.querySelector(".data-strip time[datetime], footer time[datetime]");
  return time ? time.getAttribute("datetime") : null;
}

/** Whether what a page names is the release that is expected: the same tag, or (a page that names the date only) the date of the tag. */
export function releaseMatches(named, expected) {
  if (expected === null || expected === undefined) return true;
  if (typeof named !== "string") return false;
  if (named === expected) return true;
  return /^\d{4}-\d{2}-\d{2}$/.test(named) && expected.startsWith(`data-${named}`) && /^(-\d+)?$/.test(expected.slice(`data-${named}`.length));
}

/** Run in the page: what its main element says the page is (data-page: trio, item, notfound, home...), or null. */
export function readPageKind() {
  return document.querySelector("main")?.getAttribute("data-page") ?? null;
}

/**
 * Where a page ended up when that is not the address that was asked for, as a short description (its path when it is on the same site, the whole address when it is not,
 * never more than a line), or null when it is at that address (a fragment is ignored). A page that was sent elsewhere, by the server or by a script of its own, is not the
 * page that was asked for, whatever status the place it was sent to answers with.
 */
export function redirectedTo(asked, got) {
  let wanted;
  let landed;
  try {
    wanted = new URL(asked);
    landed = new URL(got);
  } catch {
    return "an address that cannot be read";
  }
  if (!["http:", "https:"].includes(landed.protocol)) return firstLine(String(got));
  if (wanted.origin === landed.origin && wanted.pathname === landed.pathname && wanted.search === landed.search) return null;
  return firstLine(`${wanted.origin === landed.origin ? "" : landed.origin}${landed.pathname}${landed.search}`);
}

/** Run in the page: the policies that <meta http-equiv="Content-Security-Policy"> elements give, and whether the first is before every stylesheet and script. */
export function readPagePolicies() {
  const metas = [...document.querySelectorAll('meta[http-equiv="Content-Security-Policy" i]')];
  const loaders = [...document.querySelectorAll('link[rel~="stylesheet"], script')];
  const first = metas[0];
  return {
    policies: metas.map((meta) => meta.getAttribute("content")),
    first: first !== undefined && loaders.every((element) => Boolean(first.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING)),
    notfound: document.querySelector("main")?.getAttribute("data-page") === "notfound",
  };
}

// ---- the stamp ---------------------------------------------------------------------------------------------------------------------------------

/** What a stamp holds: the UTC time to the second and a line end, the form that the release build reads (trioforge.precompute.release.scheduled_warnings). */
export function stampText(date) {
  return `${date.toISOString().replace(/\.\d{3}Z$/, "Z")}\n`;
}

/** One line of the log: the UTC time, the outcome (ok, failed, refused, error or interrupted) and the text on a single line, cut to 400 characters. The same line that the Python checks write. */
export function logLine(date, outcome, text) {
  if (!OUTCOMES.includes(outcome)) throw new Error(`an outcome is one of ${OUTCOMES.join(", ")}`);
  let flat = String(text).replace(/[\u0000-\u0020\u007f-\u009f\u2028\u2029]+/g, " ").trim();
  if (flat.length > MAX_LOG_TEXT) flat = `${flat.slice(0, MAX_LOG_TEXT - 3)}...`;
  return `${stampText(date).trimEnd()} ${outcome} ${flat}`.trimEnd();
}

/**
 * Add a line (logLine) to smoke-live.log in `directory`, which keeps its last `keep` lines. A log that cannot be read or written is no failure of the run it is about: nothing is
 * raised and null is returned.
 */
export function appendLog(directory, date, outcome, text, keep = LOG_LINES) {
  const target = path.join(directory, `${STAMP_NAME}.log`);
  const temporary = `${target}.${process.pid}.tmp`;
  try {
    let old = [];
    try {
      old = readFileSync(target, "utf8").split(/\r?\n/);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
    const lines = [...old.filter((line) => line.trim() !== ""), logLine(date, outcome, text)].slice(-keep);
    mkdirSync(directory, { recursive: true });
    try {
      writeFileSync(temporary, `${lines.join("\n")}\n`, "utf8");
      renameSync(temporary, target);
    } finally {
      rmSync(temporary, { force: true });
    }
    return target;
  } catch {
    return null;
  }
}

function writeStamp(directory, date) {
  mkdirSync(directory, { recursive: true });
  const target = path.join(directory, `${STAMP_NAME}.last-run`);
  const temporary = `${target}.${process.pid}.tmp`;
  try {
    writeFileSync(temporary, stampText(date), "utf8");
    renameSync(temporary, target);
  } finally {
    rmSync(temporary, { force: true });
  }
  return target;
}

// ---- the site's own lists ------------------------------------------------------------------------------------------------------------------------

async function getJson(base, pathname, pace) {
  await pace();
  let response;
  try {
    response = await fetch(base + pathname, { redirect: "manual", signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS), headers: { accept: "application/json" } });
  } catch (error) {
    throw new Problem(`${pathname} could not be fetched (${error?.cause?.code ?? error?.name ?? "error"})`);
  }
  if (response.status !== 200) throw new Problem(`${pathname} answered ${response.status}`);
  try {
    return await response.json();
  } catch {
    throw new Problem(`${pathname} is not JSON`);
  }
}

/** The manifest of the optimizer, the trios it lists, and the pages of items of its item table. Raises Problem when the site's own lists cannot be read. */
async function discover(options, pace) {
  const manifest = await getJson(options.base, "/engine-manifest.json", pace);
  const trios = trioSlugs(manifest);
  if (options.trios > 0 && trios.length === 0) throw new Problem("the manifest lists no trio");
  let items = [];
  if (options.items > 0) {
    const itemTable = manifest?.items?.path;
    if (typeof itemTable !== "string" || !itemTable.startsWith("/") || itemTable.startsWith("//")) throw new Problem("the manifest does not say where the item table is");
    items = itemPageKeys(await getJson(options.base, itemTable, pace));
    if (items.length === 0) throw new Problem("the item table lists no item that has a page");
  }
  return { manifest, trios, items };
}

/** Whether a console message is the browser's own note about the status of the document it was sent (which the check reads on its own), and so not an error of the page. */
export function ignoredConsoleMessage(message, url) {
  return message.type() === "error" && message.location()?.url === url && BROWSER_STATUS_NOTE.test(message.text());
}

/** The time a page is given to load: the time of a request, and room for the paced requests of a page (the browser's own are paced too, one at a time). */
export function navigationMs(paceSeconds) {
  return REQUEST_TIMEOUT_MS + MOST_PACED_REQUESTS * paceSeconds * 1000;
}

// ---- one page ------------------------------------------------------------------------------------------------------------------------------------

const firstLine = (text) => String(text).split("\n")[0].slice(0, 200);

/** Load one page in the browser and return what is wrong with it, as sentences that start with what the page is. */
async function checkPage(context, options, expected, target) {
  const problems = [];
  const say = (text) => problems.push(`${target.path}: ${text}`);
  const page = await context.newPage();
  const url = options.base + target.path;
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    if (ignoredConsoleMessage(message, url)) return; // (the browser's own note about the status of the document: the status is checked on its own)
    consoleErrors.push(firstLine(message.text()));
  });
  page.on("pageerror", (error) => pageErrors.push(firstLine(error?.message ?? error)));
  try {
    let response;
    try {
      response = await page.goto(url, { waitUntil: "load", timeout: options.navigationMs });
    } catch (error) {
      say(`could not be loaded (${firstLine(error.message)})`);
      return problems;
    }
    if (response === null) {
      say("gave no response");
      return problems;
    }
    if (response.status() !== target.status) say(`answered ${response.status()}, not ${target.status}`);
    for (const problem of checkHeaders(response.headers(), expected, options)) say(problem);
    // the page as the server sent it: no counting tag in it, in either mode (the document only: what a script of the page holds is another response, and a response that says it is not HTML is not looked at).
    // A page that cannot be read, and a navigation that gives no content type (so that it cannot be told whether it is HTML), are problems and no pass: the check says what it could not do.
    const contentType = response.headers()["content-type"] ?? "";
    if (contentType.trim() === "") {
      say("answered with no content type, so it was not checked for a counting tag (every page of the site says it is HTML)");
    } else if (/html/i.test(contentType)) {
      let body = null;
      try {
        body = typeof response.text === "function" ? await response.text() : null;
      } catch {
        body = null;
      }
      const marker = body === null ? null : countingTagIn(body);
      if (body === null) {
        say("could not be read as the server sent it (the browser gave no body for the navigation), so it was not checked for a counting tag");
      } else if (marker !== null) {
        say(`has a counting tag ("${marker}") in the page as the server sent it: no page of this site carries a script tag for the counter (the page script adds it), so this is a tag that was put in: turn the Web Analytics switch of the Cloudflare dashboard off`);
      }
    }
    try {
      await page.locator("#theme-toggle").waitFor({ state: "visible", timeout: options.waitMs });
    } catch {
      say("the page script did not run (the theme button never showed)");
    }
    // the page is watched until its network has been idle and then for the settle time, so that what it does some seconds after it loaded is seen: the errors are read after that
    await page.waitForLoadState("networkidle", { timeout: IDLE_CAP_MS }).catch(() => {});
    if (options.settleMs > 0) await page.waitForTimeout(options.settleMs);
    // the page that came is the page that was asked for: a redirect (the server's, or the page's own script) ends somewhere else, and what is read there is not this page
    const landed = redirectedTo(url, page.url());
    if (landed !== null) say(`ended at ${landed}, not at its own address (a redirect)`);
    if (landed === null && options.expectData !== null && target.kind !== "notfound") {
      const named = await page.evaluate(readRelease);
      if (!releaseMatches(named, options.expectData)) say(`names ${named === null ? "no data release" : `the data release ${firstLine(named)}`}, not ${options.expectData}`);
    }
    if (landed === null && target.kind === "notfound") {
      const seen = await page.evaluate(readPagePolicies);
      if (!seen.notfound) say("is not the 404 page of the site (its main element is not data-page=notfound)");
      if (seen.policies.length !== 1 || squeeze(seen.policies[0]) !== NOTFOUND_POLICY) say(`does not give itself the policy ${NOTFOUND_POLICY} in one <meta> element`);
      else if (!seen.first) say("gives its own policy after a stylesheet or a script, where it governs nothing that came before");
    } else if (landed === null) {
      const kind = await page.evaluate(readPageKind);
      if (kind !== target.kind) say(`is not ${target.kind === "trio" ? "a trio" : "an item"} page (its main element says ${kind === null ? "nothing" : `data-page=${firstLine(kind)}`})`);
    }
    if (consoleErrors.length > 0) say(`console error: ${consoleErrors[0]}${consoleErrors.length > 1 ? ` (and ${consoleErrors.length - 1} more)` : ""}`);
    if (pageErrors.length > 0) say(`page error: ${pageErrors[0]}${pageErrors.length > 1 ? ` (and ${pageErrors.length - 1} more)` : ""}`);
  } finally {
    await page.close().catch(() => {});
  }
  return problems;
}

/**
 * What a page holds of the counter, read in the page (so it is serialized: nothing outside this function may be used in it): how many script elements it has that are the counter's (the attribute
 * data-cf-beacon, or a source on either host) and the entries of its resource timing that are on either host. `hosts` are the host names of the counter's two hosts.
 */
export function readCounterTraces(hosts) {
  const matches = (address) => {
    try {
      return hosts.includes(new URL(address, document.baseURI).hostname.toLowerCase());
    } catch {
      return false;
    }
  };
  const scripts = [...document.querySelectorAll("script")].filter((script) => script.hasAttribute("data-cf-beacon") || matches(script.src)).length;
  const resources = performance
    .getEntriesByType("resource")
    .map((entry) => entry.name)
    .filter(matches);
  return { scripts, resources };
}

/**
 * With --analytics: open the page of a trio with an invented kit fragment, in a browser context of its own (the pages that were checked before may have put the counter's script in the HTTP cache of
 * theirs, and a script that comes from the cache may not be a request that the browser reports), and return what is wrong, which is any request to either host of the counter (a page opened from a kit
 * link is never counted: not the script, and not its report), however it came to ask (the page script, or a tag that was put into the page), a script element of the counter in the page and an
 * entry of its resource timing on either host. The requests are listened for on the context until the page has been closed (a report is often sent as the page goes).
 */
async function checkKitLink(context, options, target) {
  const problems = [];
  const say = (text) => problems.push(`${target.path} (a kit link): ${text}`);
  const asked = [];
  context.on("request", (request) => {
    if (isCounterRequest(request.url())) asked.push(request.url());
  });
  const page = await context.newPage();
  try {
    try {
      await page.goto(options.base + target.path + KIT_PROBE_FRAGMENT, { waitUntil: "load", timeout: options.navigationMs });
    } catch (error) {
      say(`could not be loaded (${firstLine(error.message)})`);
      return problems;
    }
    try {
      await page.locator("#theme-toggle").waitFor({ state: "visible", timeout: options.waitMs });
    } catch {
      say("the page script did not run, so this check shows nothing (the theme button never showed)");
    }
    await page.waitForLoadState("networkidle", { timeout: IDLE_CAP_MS }).catch(() => {});
    if (options.settleMs > 0) await page.waitForTimeout(options.settleMs);
    let traces = null;
    try {
      traces = await page.evaluate(readCounterTraces, [new URL(COUNTER_SCRIPT_HOST).hostname, new URL(COUNTER_DATA_HOST).hostname]);
    } catch {
      say("could not look in the page for the counter's script and its resource timing, so this check shows less than it should");
    }
    if (traces !== null && traces.scripts > 0) {
      say(`has ${traces.scripts} counter script element${traces.scripts === 1 ? "" : "s"} in the page: a page opened from a kit link is never counted, and no script of the counter may be in it`);
    }
    if (traces !== null && traces.resources.length > 0) {
      say(`resource timing lists ${traces.resources.length} request${traces.resources.length === 1 ? "" : "s"} to the counter's hosts (first: ${new URL(traces.resources[0]).host}) in the page`);
    }
  } finally {
    // The page is sent away before it is closed, and a moment is given: pagehide fires on a navigation (it may not on a close of the target), and a report that a counter sends at pagehide, or as the
    // page becomes hidden, is sent then. The context is listened to until the page has gone.
    try {
      await page.goto("about:blank", { timeout: options.navigationMs });
    } catch (error) {
      say(`could not be sent away to about:blank (${firstLine(error.message)}), so a report that the page sends as it goes may be missed and this check shows less than it should`);
    }
    await new Promise((done) => setTimeout(done, Math.min(Math.max(options.settleMs, LEAVING_WAIT_MS), MOST_CLOSE_WAIT_MS)));
    await page.close().catch(() => {});
  }
  if (asked.length > 0) {
    say(`made ${asked.length} request${asked.length === 1 ? "" : "s"} to the counter's hosts (first: ${new URL(asked[0]).host}): a page opened from a kit link is never counted, and nothing of the counter may be asked for there`);
  }
  return problems;
}

// ---- the run -----------------------------------------------------------------------------------------------------------------------------------

async function launchBrowser() {
  try {
    const { chromium } = await import("@playwright/test");
    return await chromium.launch();
  } catch {
    // (a fixed sentence: Playwright's own line for a browser that is not there names a folder under the user profile, and this goes in the log)
    throw new UsageError("cannot start Chromium; install it with: npx playwright install chromium");
  }
}

const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;

/** The lines to print for a list of problems: how many, then the first MOST_LISTED of them. */
function failure(options, problems) {
  const shown = problems.slice(0, MOST_LISTED).map((problem) => `- ${problem}`);
  if (problems.length > MOST_LISTED) shown.push(`- and ${problems.length - MOST_LISTED} more`);
  if (options.expectFrom === "newest" && options.expectData !== null) {
    shown.push(`  (${options.expectData} is expected because it is the newest pointer in releases/; --expect-data none turns that off)`);
  }
  return [`smoke-live: FAILED, ${plural(problems.length, "problem", "problems")} on ${options.base} (seed ${options.seed})`, ...shown];
}

/** The whole check. Returns `{ code, lines }`: 0 and one line when everything passes (the stamp is written), 1 and a short list when not, and raises UsageError when it cannot run. */
export async function run(options, { now = () => new Date(), launch = launchBrowser } = {}) {
  let expected;
  try {
    expected = expectedHeaders(readFileSync(options.headersFile, "utf8"), { analytics: options.analytics });
  } catch (error) {
    if (error instanceof UsageError) throw error;
    throw new UsageError(`cannot read the headers file ${path.basename(options.headersFile)} (${error.code ?? error.name})`);
  }
  if (options.expectFrom === "newest") options = { ...options, expectData: newestRelease(options.releasesDir) };
  const pace = makePacer(options.paceSeconds);
  let found;
  try {
    found = await discover(options, pace);
  } catch (error) {
    if (!(error instanceof Problem)) throw error;
    return { code: 1, lines: failure(options, [error.message]) };
  }
  const targets = [
    ...sample(found.trios, options.trios, options.seed).map((slug) => ({ kind: "trio", path: `/trio/${slug}/`, status: 200 })),
    ...sample(found.items, options.items, options.seed + 1).map((key) => ({ kind: "item", path: `/item/${key}/`, status: 200 })),
    { kind: "notfound", path: NOTFOUND_PATH, status: 404 },
  ];
  const trioPages = targets.filter((target) => target.kind === "trio").length;
  const itemPages = targets.filter((target) => target.kind === "item").length;
  if (trioPages < 1 || itemPages < 1) {
    // (no browser is started for it: a stamp must not say that trio and item pages were checked when none of one kind was)
    const chose = `${plural(trioPages, "trio page", "trio pages")} and ${plural(itemPages, "item page", "item pages")}`;
    return { code: 1, lines: failure(options, [`the check chose ${chose}; it needs at least one of each, or its stamp would say that pages were checked when they were not`]) };
  }
  options = { ...options, navigationMs: navigationMs(options.paceSeconds) };
  const problems = [];
  if (options.expectData !== null && found.manifest.data_release !== options.expectData) {
    problems.push(`/engine-manifest.json names the data release ${firstLine(found.manifest.data_release ?? "none")}, not ${options.expectData}`);
  }
  const browser = await launch();
  try {
    const newContext = async () => {
      const made = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: "en-US", colorScheme: "light" });
      if (options.paceSeconds > 0) {
        await made.route("**/*", async (route) => {
          await pace();
          await route.continue().catch(() => {});
        });
      }
      return made;
    };
    const context = await newContext();
    for (const target of targets) problems.push(...(await checkPage(context, options, expected, target)));
    if (options.analytics) {
      const fresh = await newContext(); // (the kit link page has a context of its own: nothing the counted pages loaded is in its cache)
      try {
        problems.push(...(await checkKitLink(fresh, options, targets.find((target) => target.kind === "trio"))));
      } finally {
        await fresh.close().catch(() => {});
      }
    }
  } finally {
    await browser.close().catch(() => {});
  }
  if (problems.length > 0) return { code: 1, lines: failure(options, problems) };
  writeStamp(options.out, now());
  const counts = [
    plural(targets.filter((target) => target.kind === "trio").length, "trio", "trios"),
    plural(targets.filter((target) => target.kind === "item").length, "item", "items"),
  ];
  const release = typeof found.manifest.data_release === "string" ? firstLine(found.manifest.data_release) : null;
  const where =
    options.expectFrom !== "newest"
      ? null
      : options.expectData === null
        ? "(no pointer in releases/, so no data release was expected)"
        : "(the newest pointer in releases/)";
  const named = [release, where].some((part) => part !== null) ? `, ${[release, where].filter((part) => part !== null).join(" ")}` : "";
  return { code: 0, lines: [`smoke-live: ok, ${plural(targets.length, "page", "pages")} of ${options.base} (${counts.join(", ")}, 1 not-found page), seed ${options.seed}${named}`] };
}

/** The command: `argv` without the node and the script. Prints its lines through `log`/`error` and returns the exit code. */
export async function main(argv, { log = console.log, error = console.error, now = () => new Date(), env = process.env, launch = launchBrowser } = {}) {
  let options = null;
  // the line of the log goes where the stamp goes; a command line that was not understood has no --out, and its line goes to the folder of the checks
  const record = (outcome, text) => {
    let folder = options?.out ?? null;
    if (folder === null) {
      try {
        folder = checksDir(env);
      } catch {
        folder = null;
      }
    }
    if (folder !== null) appendLog(folder, now(), outcome, text);
  };
  try {
    options = parseArgs(argv, now(), env);
    if (options.help) {
      log(USAGE);
      return 0;
    }
    const result = await run(options, { now, launch });
    for (const line of result.lines) (result.code === 0 ? log : error)(line);
    const first = result.code === 0 ? undefined : result.lines.find((line) => line.startsWith("- "));
    record(result.code === 0 ? "ok" : "failed", `${result.lines[0]}${first === undefined ? "" : `; first: ${first.slice(2)}`}`);
    return result.code;
  } catch (caught) {
    if (!(caught instanceof UsageError)) {
      record("error", `an unexpected fault (${caught?.name ?? "Error"}); run the check by hand to see what it was`); // (the kind only: a message can hold a path of this computer)
      throw caught;
    }
    error(`smoke-live: ${caught.message}`);
    if (caught instanceof CommandLineError) error(USAGE);
    record("refused", caught.message);
    return 2;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const finish = (code) => {
    process.exitCode = code;
    // a browser that will not shut down must not keep the process waiting
    setTimeout(() => process.exit(code), 5_000).unref();
  };
  main(process.argv.slice(2)).then(finish, (caught) => {
    console.error(`smoke-live: failed: ${firstLine(caught?.message ?? caught)}`);
    finish(2);
  });
}
