import { execFile } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import http from "node:http";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { JSDOM } from "jsdom";
import { afterAll, afterEach, describe, expect, it } from "vitest";
import {
  CHECKS_ENV,
  DEFAULT_BASE,
  DEFAULT_SETTLE_SECONDS,
  LOG_LINES,
  ITEM_COUNT,
  NOTFOUND_PATH,
  NOTFOUND_POLICY,
  STAMP_NAME,
  TRIO_COUNT,
  USAGE,
  UsageError,
  appendLog,
  checkHeaders,
  checksDir,
  expectedHeaders,
  ignoredConsoleMessage,
  isAbsolutePath,
  itemPageKeys,
  logLine,
  main,
  makePacer,
  navigationMs,
  newestRelease,
  parseArgs,
  parseHeaderBlock,
  readPageKind,
  readPagePolicies,
  readRelease,
  redirectedTo,
  releaseMatches,
  run as runCheck,
  sample,
  stampText,
  trioSlugs,
  weekSeed,
} from "../scripts/smoke_live.mjs";

// The smoke check of the live site (scripts/smoke_live.mjs) loads pages in Chromium; that is held in tests-e2e/smoke-live.spec.mjs, against a preview served by wrangler and against
// stand-ins that fail each check in turn. What is held here needs no browser: the command line, the seeded choice of pages, the pace, the headers, the data release, the stamp, and the
// ways the site's own lists can be unreadable (which end the check before a browser is started).

// no test of this file writes into the real folder of the checks, which a run without --out would: the folder is a scratch one
process.env.TRIOFORGE_CHECKS_DIR = mkdtempSync(join(tmpdir(), "smoke-live-checks-folder-"));
afterAll(() => rmSync(process.env.TRIOFORGE_CHECKS_DIR, { recursive: true, force: true }));

const HERE = fileURLToPath(new URL(".", import.meta.url));
const HEADERS_FILE = resolve(HERE, "..", "site", "_headers");
const SCRIPT = resolve(HERE, "..", "scripts", "smoke_live.mjs");

const GOOD_HEADERS = `
/*
  Content-Security-Policy: default-src 'self'; script-src 'self'
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  X-Robots-Tag: noindex

/assets/*
  Cache-Control: public, max-age=31536000, immutable
`;
const EXPECTED = { "content-security-policy": "default-src 'self'; script-src 'self'", "x-content-type-options": "nosniff", "referrer-policy": "no-referrer" };
const RESPONSE = { ...EXPECTED, "x-robots-tag": "noindex", "content-type": "text/html" };

// ---- the command line -----------------------------------------------------------------------------------------------------------------

describe("parseArgs", () => {
  const now = new Date("2026-10-18T10:00:03Z");

  it("checks the live site, 5 trio pages and 5 item pages, as a preview, with the seed of the week, when it is given nothing", () => {
    const folder = join(tmpdir(), "a-folder-of-the-checks"); // (outside every work tree)
    const options = parseArgs([], now, { TRIOFORGE_CHECKS_DIR: folder });
    expect(DEFAULT_BASE).toBe("https://trioforge.pages.dev");
    expect(options).toMatchObject({ base: "https://trioforge.pages.dev", indexable: false, expectData: null, seed: 202642, trios: 5, items: 5, paceSeconds: 0, help: false });
    expect([TRIO_COUNT, ITEM_COUNT]).toEqual([5, 5]);
    expect(options.out).toBe(folder); // (the folder of the checks, outside every worktree: not the build folder of this one)
    expect(options.headersFile).toBe(HEADERS_FILE);
    expect(options.waitMs).toBe(10_000);
  });

  it("takes every option, in the form --name value and in the form --name=value", () => {
    const options = parseArgs(
      ["--base", "http://127.0.0.1:8799", "--indexable", "--expect-data=data-2026-10-14-2", "--seed", "7", "--out", "scratch", "--headers-file=h.txt", "--trios", "2", "--items=3", "--wait", "1.5", "--pace", "0.5"],
      now,
    );
    expect(options).toMatchObject({ base: "http://127.0.0.1:8799", indexable: true, expectData: "data-2026-10-14-2", seed: 7, trios: 2, items: 3, waitMs: 1500, paceSeconds: 0.5 });
    expect(options.out).toBe(resolve("scratch"));
    expect(options.headersFile).toBe(resolve("h.txt"));
  });

  it("reads --help", () => {
    expect(parseArgs(["--help"], now).help).toBe(true);
    expect(parseArgs(["-h"], now).help).toBe(true);
    expect(USAGE).toContain("--expect-data");
    expect(USAGE).toContain("--indexable");
  });

  it("takes the address of the site with a trailing slash, in any case of its host, and keeps only its origin", () => {
    expect(parseArgs(["--base", "https://Example.Invalid/"], now).base).toBe("https://example.invalid");
    expect(parseArgs(["--base", "https://example.invalid:8443"], now).base).toBe("https://example.invalid:8443");
  });

  it.each([
    ["not an address", ["--base", "trioforge.pages.dev"]],
    ["a path", ["--base", "https://example.invalid/site/"]],
    ["a query", ["--base", "https://example.invalid/?a=1"]],
    ["a fragment", ["--base", "https://example.invalid/#x"]],
    ["credentials", ["--base", "https://user:secret@example.invalid/"]],
    ["another protocol", ["--base", "ftp://example.invalid/"]],
    ["a script address", ["--base", "javascript:alert(1)"]],
  ])("refuses a --base that is %s", (_, argv) => {
    expect(() => parseArgs(argv, now)).toThrow(UsageError);
    expect(() => parseArgs(argv, now)).toThrow(/--base/);
  });

  it.each([
    ["a name that is not a release", ["--expect-data", "2026-10-14"]],
    ["a release with letters", ["--expect-data", "data-2026-10-xx"]],
    ["a release with text after it", ["--expect-data", "data-2026-10-14; rm"]],
    ["a seed that is not a number", ["--seed", "week"]],
    ["a fractional seed", ["--seed", "1.5"]],
    ["a negative seed", ["--seed", "-3"]],
    ["a number of trios that is not a number", ["--trios", "many"]],
    ["a negative number of items", ["--items", "-1"]],
    ["too many pages", ["--trios", "1000"]],
    ["a wait of zero", ["--wait", "0"]],
    ["a pace that is not a number", ["--pace", "fast"]],
    ["an option that does not exist", ["--no-such-option"]],
    ["a stray word", ["extra"]],
    ["an option with no value", ["--base"]],
  ])("refuses %s", (_, argv) => {
    expect(() => parseArgs(argv, now)).toThrow(UsageError);
  });

  it("expects the data release of the newest pointer in releases/, unless it is told another or none", () => {
    expect(parseArgs([], now)).toMatchObject({ expectData: null, expectFrom: "newest", releasesDir: resolve(HERE, "..", "releases") });
    expect(parseArgs(["--expect-data", "newest"], now)).toMatchObject({ expectData: null, expectFrom: "newest" });
    expect(parseArgs(["--expect-data=none"], now)).toMatchObject({ expectData: null, expectFrom: "none" });
    expect(parseArgs(["--expect-data", "data-2026-10-14-2"], now)).toMatchObject({ expectData: "data-2026-10-14-2", expectFrom: "tag" });
    expect(parseArgs(["--releases-dir", "pointers"], now).releasesDir).toBe(resolve("pointers"));
    expect(USAGE).toContain("--releases-dir");
    expect(USAGE).toMatch(/--expect-data TAG\|newest\|none/);
  });

  it.each(["--trios", "--items"])("refuses %s 0: a check that loads no trio page or no item page would leave a stamp that says it did (G2)", (option) => {
    const kind = option === "--trios" ? "trios" : "items";
    for (const argv of [[option, "0"], [`${option}=0`]]) {
      expect(() => parseArgs(argv, now)).toThrow(UsageError);
      expect(() => parseArgs(argv, now)).toThrow(new RegExp(`--${kind} must be a whole number from 1 to 100`));
    }
    expect(parseArgs([option, "1"], now)[kind]).toBe(1);
  });

  it.each(["--out", "--releases-dir", "--headers-file"])("refuses an empty %s, which would be the working folder (G9)", (option) => {
    for (const value of ["", "   "]) {
      expect(() => parseArgs([`${option}=${value}`], now)).toThrow(UsageError);
      expect(() => parseArgs([`${option}=${value}`], now)).toThrow(new RegExp(`${option} must name a ${option === "--headers-file" ? "file" : "folder"}`));
    }
    expect(() => parseArgs([option, ""], now)).toThrow(UsageError);
  });

  it("watches a page for errors for 5 seconds after its network went idle, and --settle says another time", () => {
    expect(DEFAULT_SETTLE_SECONDS).toBe(5);
    expect(parseArgs([], now).settleMs).toBe(5000);
    expect(parseArgs(["--settle", "0.3"], now).settleMs).toBe(300);
    expect(parseArgs(["--settle=0"], now).settleMs).toBe(0);
    expect(parseArgs(["--settle", "60"], now).settleMs).toBe(60_000);
    expect(USAGE).toContain("--settle");
  });

  it.each(["-1", "61", "soon", "", "1e999"])("refuses a --settle of %j", (value) => {
    // (in the form --settle=-1: node's parser takes a word that starts with a dash after --settle for an option, and says so, which is a refusal too)
    expect(() => parseArgs([`--settle=${value}`], now)).toThrow(UsageError);
    expect(() => parseArgs([`--settle=${value}`], now)).toThrow(/--settle must be a number from 0 to 60/);
  });
});

describe("checksDir", () => {
  const home = join("home", "someone"); // an invented home folder
  const absolute = { win32: "C:\\stamps", linux: "/stamps", darwin: "/stamps" }; // an absolute path of each kind of platform
  const folder = join(tmpdir(), "a-folder-of-the-checks"); // (outside every work tree: a folder in one is refused)
  const standard = join(home, ".local", "state", "trioforge", "checks");

  it("is named by TRIOFORGE_CHECKS_DIR, on any platform", () => {
    expect(CHECKS_ENV).toBe("TRIOFORGE_CHECKS_DIR");
    for (const platform of ["win32", "linux", "darwin"]) {
      expect(checksDir({ TRIOFORGE_CHECKS_DIR: absolute[platform], LOCALAPPDATA: "x" }, platform, home)).toBe(resolve(absolute[platform]));
    }
  });

  it("takes no account of white space round the name", () => {
    for (const platform of ["win32", "linux"]) expect(checksDir({ TRIOFORGE_CHECKS_DIR: `  ${absolute[platform]}\n` }, platform, home)).toBe(resolve(absolute[platform]));
  });

  it.each(["", "  ", "\n", "\t "])("counts an empty or blank variable (%j) as unset", (value) => {
    for (const platform of ["win32", "linux", "darwin"]) expect(checksDir({ TRIOFORGE_CHECKS_DIR: value }, platform, home)).toBe(standard);
  });

  it.each(["win32", "linux", "darwin"])("refuses a folder that is not given whole, on %s: %s", (platform) => {
    for (const value of ["checks", "./checks", "../checks", "build/checks", "~/checks"]) {
      expect(() => checksDir({ TRIOFORGE_CHECKS_DIR: value }, platform, home)).toThrow(/TRIOFORGE_CHECKS_DIR/);
      expect(() => checksDir({ TRIOFORGE_CHECKS_DIR: value }, platform, home)).toThrow(UsageError);
    }
  });

  it.each(["win32", "linux", "darwin", "freebsd14"])("is under the state folder of the home of the user on %s, Windows included and never the local app data (R2)", (platform) => {
    expect(checksDir({}, platform, home)).toBe(standard);
    expect(checksDir({ LOCALAPPDATA: "AppData-Local" }, platform, home)).toBe(standard);
  });

  it("reads the environment, the platform and the home of the process when it is given none", () => {
    const saved = process.env[CHECKS_ENV];
    delete process.env[CHECKS_ENV];
    try {
      const real = checksDir();
      expect(real.endsWith(join(".local", "state", "trioforge", "checks"))).toBe(true);
      process.env[CHECKS_ENV] = folder;
      expect(checksDir()).toBe(folder);
    } finally {
      if (saved === undefined) delete process.env[CHECKS_ENV];
      else process.env[CHECKS_ENV] = saved;
    }
  });

  describe("a folder in a git work tree", () => {
    const made = [];
    const places = () => {
      const base = mkdtempSync(join(tmpdir(), "smoke-live-worktrees-"));
      made.push(base);
      mkdirSync(join(base, "plain"));
      mkdirSync(join(base, "repo", ".git"), { recursive: true });
      mkdirSync(join(base, "linked"));
      writeFileSync(join(base, "linked", ".git"), "gitdir: elsewhere\n"); // (a worktree that was added with `git worktree add`: its .git is a file)
      return { plain: join(base, "plain"), repo: join(base, "repo"), linked: join(base, "linked") };
    };
    afterAll(() => {
      for (const base of made) rmSync(base, { recursive: true, force: true });
    });

    it("is refused, however deep and whether or not it is there yet (R7)", () => {
      const { repo, linked, plain } = places();
      for (const root of [repo, linked]) {
        for (const inner of [root, join(root, "build"), join(root, "build", "checks"), join(root, "not", "yet", "made")]) {
          expect(() => checksDir({ TRIOFORGE_CHECKS_DIR: inner }, process.platform, home)).toThrow(/TRIOFORGE_CHECKS_DIR .*git work tree/);
          expect(() => checksDir({ TRIOFORGE_CHECKS_DIR: inner }, process.platform, home)).toThrow(UsageError);
        }
      }
      expect(checksDir({ TRIOFORGE_CHECKS_DIR: join(plain, "checks") }, process.platform, home)).toBe(join(plain, "checks"));
    });

    it("is not asked of the default folder, since the home of a user can be a repository itself", () => {
      const { repo } = places();
      expect(checksDir({}, process.platform, repo)).toBe(join(repo, ".local", "state", "trioforge", "checks"));
    });
  });
});

describe("isAbsolutePath", () => {
  // (value, absolute on Windows, absolute elsewhere): the same table as the Python test of the same rule
  const table = [
    ["/TrioForge/checks", false, true],
    ["/", false, true],
    ["C:\\TrioForge\\checks", true, false],
    ["C:/TrioForge/checks", true, false],
    ["c:\\x", true, false],
    ["Z:/", true, false],
    ["C:checks", false, false],
    ["C:", false, false],
    ["\\TrioForge\\checks", false, false],
    ["\\\\server\\share\\checks", true, false],
    ["//server/share/checks", true, true],
    ["\\\\server\\share", true, false],
    ["\\\\server", false, false],
    ["\\\\server\\", false, false],
    ["//server", false, true],
    ["relative", false, false],
    ["./checks", false, false],
    ["../checks", false, false],
    ["~/checks", false, false],
    ["build\\checks", false, false],
    ["", false, false],
  ];

  it.each(table)("is decided by one rule for each kind of platform: %j", (value, windows, elsewhere) => {
    expect(isAbsolutePath(value, "win32")).toBe(windows);
    for (const platform of ["linux", "darwin", "freebsd14"]) expect(isAbsolutePath(value, platform)).toBe(elsewhere);
  });
});

describe("weekSeed", () => {
  it.each([
    ["2026-10-18T10:00:03Z", 202642], // a Sunday: the last day of the 42nd week
    ["2026-10-19T00:00:00Z", 202643], // the Monday after
    ["2026-01-01T12:00:00Z", 202601],
    ["2027-01-01T12:00:00Z", 202653], // a Friday: still the 53rd week of 2026
    ["2024-12-30T12:00:00Z", 202501], // a Monday: the first week of 2025
    ["2026-12-31T23:59:59Z", 202653],
  ])("is the ISO week of %s", (when, seed) => {
    expect(weekSeed(new Date(when))).toBe(seed);
  });
});

// ---- the seeded choice -----------------------------------------------------------------------------------------------------------------

describe("sample", () => {
  const names = Array.from({ length: 560 }, (_, at) => `trio-${String(at).padStart(3, "0")}`);

  it("chooses the same names for the same seed, whatever the order of the list", () => {
    const first = sample(names, 5, 202642);
    expect(sample([...names].reverse(), 5, 202642)).toEqual(first);
    expect(sample([...names.slice(200), ...names.slice(0, 200)], 5, 202642)).toEqual(first);
  });

  it("chooses other names for another seed (they are not the first five of the list)", () => {
    const seen = new Set();
    for (const seed of [1, 2, 3, 202642, 202643, 99]) seen.add(sample(names, 5, seed).join());
    expect(seen.size).toBeGreaterThan(4);
    expect(sample(names, 5, 202642)).not.toEqual(names.slice(0, 5));
  });

  it("gives the number asked for, each name once, all of them from the list, in order", () => {
    const chosen = sample(names, 5, 20261018);
    expect(chosen).toHaveLength(5);
    expect(new Set(chosen).size).toBe(5);
    expect(chosen.every((name) => names.includes(name))).toBe(true);
    expect(chosen).toEqual([...chosen].sort());
  });

  it("gives every name, in order, when the list is no longer than the number asked for", () => {
    expect(sample(["c", "a", "b"], 5, 1)).toEqual(["a", "b", "c"]);
    expect(sample(["a", "b", "c", "d", "e"], 5, 1)).toEqual(["a", "b", "c", "d", "e"]);
    expect(sample([], 5, 1)).toEqual([]);
  });

  it("gives nothing when none is asked for, and names a repeated name once", () => {
    expect(sample(names, 0, 1)).toEqual([]);
    expect(sample(["a", "a", "b"], 5, 1)).toEqual(["a", "b"]);
  });

  it("does not change the list it is given", () => {
    const copy = [...names];
    sample(copy, 5, 3);
    expect(copy).toEqual(names);
  });
});

describe("the site's own lists", () => {
  it("lists the trios of the manifest of the optimizer by their slugs", () => {
    expect(trioSlugs({ trios: { "pal-mnk-ber": [50], "war-clr-pal": [50] } }).sort()).toEqual(["pal-mnk-ber", "war-clr-pal"]);
  });

  it("leaves out a slug that could not be a path of the site", () => {
    expect(trioSlugs({ trios: { "pal-mnk-ber": [50], "../etc": [50], "a b": [1], "": [1], "x/y": [1] } })).toEqual(["pal-mnk-ber"]);
  });

  it.each([[null], [{}], [{ trios: [] }], [{ trios: "pal-mnk-ber" }], [{ trios: null }]])("refuses a manifest with no list of trios: %j", (manifest) => {
    expect(() => trioSlugs(manifest)).toThrow(/no list of trios/);
  });

  it("lists the items that get a page: those of the strict and the wiki level, by their key or else by w and the page id", () => {
    const table = {
      items: [
        { id: 112, evidence: { level: "strict" } },
        { id: 113, key: "w113", evidence: { level: "wiki" } },
        { id: 114, evidence: { level: "hidden" } },
        { id: 115, evidence: { level: "disputed" } },
        { key: "r-research", evidence: { level: "wiki" } },
        { id: 116 },
        { key: "bad key!", evidence: { level: "wiki" } },
        null,
        "text",
      ],
    };
    expect(itemPageKeys(table)).toEqual(["w112", "w113", "r-research"]);
  });

  it.each([[null], [{}], [{ items: "no" }], [[]]])("refuses an item table with no list of items: %j", (table) => {
    expect(() => itemPageKeys(table)).toThrow(/no list of items/);
  });
});

// ---- the pace ----------------------------------------------------------------------------------------------------------------------------

describe("makePacer", () => {
  function fakeTime() {
    const time = { now: 0, sleeps: [] };
    return { time, now: () => time.now, sleep: async (ms) => (time.sleeps.push(ms), (time.now += ms)) };
  }

  it("starts requests the pace apart, in the order they ask", async () => {
    const { time, now, sleep } = fakeTime();
    const pace = makePacer(1, { now, sleep });
    const starts = [];
    for (let at = 0; at < 4; at += 1) {
      await pace();
      starts.push(time.now);
    }
    expect(starts).toEqual([0, 1000, 2000, 3000]);
  });

  it("does not wait for a request that comes later than the pace", async () => {
    const { time, now, sleep } = fakeTime();
    const pace = makePacer(1, { now, sleep });
    await pace();
    time.now = 5000;
    await pace();
    expect(time.sleeps).toEqual([]);
    await pace();
    expect(time.sleeps).toEqual([1000]);
  });

  it("gives each of several requests that ask at once a turn of its own", async () => {
    const sleeps = [];
    const pace = makePacer(2, { now: () => 0, sleep: async (ms) => void sleeps.push(ms) });
    await Promise.all([pace(), pace(), pace()]);
    expect(sleeps).toEqual([2000, 4000]);
  });

  it("waits for nothing when there is no pace", async () => {
    const { time, now, sleep } = fakeTime();
    const pace = makePacer(0, { now, sleep });
    for (let at = 0; at < 5; at += 1) await pace();
    expect(time.sleeps).toEqual([]);
  });
});

// ---- the headers -------------------------------------------------------------------------------------------------------------------------

describe("the headers a response must carry", () => {
  it("reads the block of the paths /* of a _headers file, with the names in lower case", () => {
    const block = parseHeaderBlock(GOOD_HEADERS);
    expect([...block.keys()]).toEqual(["content-security-policy", "x-content-type-options", "referrer-policy", "x-robots-tag"]);
    expect(block.get("referrer-policy")).toBe("no-referrer");
    expect(parseHeaderBlock(GOOD_HEADERS, "/assets/*").get("cache-control")).toContain("immutable");
  });

  it("takes the three headers the site sets and leaves the robots tag to the --indexable flag", () => {
    expect(expectedHeaders(GOOD_HEADERS)).toEqual(EXPECTED);
  });

  it.each([
    ["no block for /*", "/assets/*\n  Cache-Control: x\n"],
    ["no policy", "/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n"],
    ["no nosniff", "/*\n  Content-Security-Policy: a\n  Referrer-Policy: no-referrer\n"],
    ["no referrer policy", "/*\n  Content-Security-Policy: a\n  X-Content-Type-Options: nosniff\n"],
    ["nothing", ""],
  ])("refuses a headers file with %s", (_, text) => {
    expect(() => expectedHeaders(text)).toThrow(UsageError);
  });

  it("reads the real site/_headers: it sets all three", () => {
    const wanted = expectedHeaders(readFileSync(HEADERS_FILE, "utf8"));
    expect(wanted["content-security-policy"]).toContain("default-src 'self'");
    expect(wanted["x-content-type-options"]).toBe("nosniff");
    expect(wanted["referrer-policy"]).toBe("no-referrer");
  });

  it("passes the headers of the file, with the robots tag of a preview", () => {
    expect(checkHeaders(RESPONSE, EXPECTED, { indexable: false })).toEqual([]);
  });

  it("passes headers whose value differs in the case of its letters and in its white space", () => {
    const sent = { ...RESPONSE, "content-security-policy": "default-src  'self';\n script-src 'self'", "x-content-type-options": "NoSniff" };
    expect(checkHeaders(sent, EXPECTED, { indexable: false })).toEqual([]);
  });

  it.each(["content-security-policy", "x-content-type-options", "referrer-policy"])("names a missing %s", (name) => {
    const { [name]: _, ...rest } = RESPONSE;
    expect(checkHeaders(rest, EXPECTED, { indexable: false })).toEqual([`no ${name} header`]);
  });

  it.each([
    ["content-security-policy", "default-src 'self'; script-src 'self' 'unsafe-inline'"],
    ["content-security-policy", ""],
    ["x-content-type-options", "none"],
    ["referrer-policy", "origin"],
  ])("names a %s that is not the file's: %j", (name, value) => {
    expect(checkHeaders({ ...RESPONSE, [name]: value }, EXPECTED, { indexable: false })).toEqual([`${name} is not what site/_headers sets`]);
  });

  it("does not print the policy it found", () => {
    const [problem] = checkHeaders({ ...RESPONSE, "content-security-policy": "default-src evil.invalid" }, EXPECTED, { indexable: false });
    expect(problem).not.toContain("evil.invalid");
  });

  it("wants noindex from a preview, and says so when it is missing or says something else", () => {
    const { "x-robots-tag": _, ...without } = RESPONSE;
    expect(checkHeaders(without, EXPECTED, { indexable: false })).toEqual(["no x-robots-tag noindex (a preview must keep search engines out)"]);
    expect(checkHeaders({ ...RESPONSE, "x-robots-tag": "all" }, EXPECTED, { indexable: false })).toHaveLength(1);
    expect(checkHeaders({ ...RESPONSE, "x-robots-tag": "NOINDEX, nofollow" }, EXPECTED, { indexable: false })).toEqual([]);
    expect(checkHeaders({ ...RESPONSE, "x-robots-tag": "none" }, EXPECTED, { indexable: false })).toEqual([]);
  });

  it("wants no noindex from the real site, and says so when it is there", () => {
    const { "x-robots-tag": _, ...without } = RESPONSE;
    expect(checkHeaders(without, EXPECTED, { indexable: true })).toEqual([]);
    expect(checkHeaders({ ...RESPONSE, "x-robots-tag": "all" }, EXPECTED, { indexable: true })).toEqual([]);
    expect(checkHeaders(RESPONSE, EXPECTED, { indexable: true })).toEqual(["x-robots-tag keeps search engines out, and the site is meant to be found"]);
    expect(checkHeaders({ ...RESPONSE, "x-robots-tag": "none" }, EXPECTED, { indexable: true })).toHaveLength(1);
  });

  it("lists every problem of a response, not only the first", () => {
    const problems = checkHeaders({ "content-type": "text/html" }, EXPECTED, { indexable: false });
    expect(problems).toHaveLength(4);
  });
});

// ---- the data release a page names ------------------------------------------------------------------------------------------------------

describe("the data release", () => {
  it.each([
    ["data-2026-10-14", "data-2026-10-14", true],
    ["data-2026-10-14", "data-2026-10-15", false],
    ["data-2026-10-14-2", "data-2026-10-14-2", true],
    ["data-2026-10-14", "data-2026-10-14-2", false], // (the page names the first release of the day, and the second is expected)
    ["data-2026-10-14-2", "data-2026-10-14", false],
    ["2026-10-14", "data-2026-10-14", true], // (a page that names only the date)
    ["2026-10-14", "data-2026-10-14-2", true], // (a date is the release of that day, whichever it was)
    ["2026-10-14", "data-2026-10-15", false],
    ["2026-10-14", "data-2026-10-140", false],
    [null, "data-2026-10-14", false],
    [undefined, "data-2026-10-14", false],
    ["", "data-2026-10-14", false],
    [5, "data-2026-10-14", false],
    ["data-2026-10-14", null, true], // (nothing is expected)
    [null, null, true],
  ])("a page that names %j matches what is expected, %j: %s", (named, expected, matches) => {
    expect(releaseMatches(named, expected)).toBe(matches);
  });

  describe("as the page names it", () => {
    let previous;

    function load(html) {
      const dom = new JSDOM(html);
      previous ??= { document: globalThis.document, Node: globalThis.Node };
      globalThis.document = dom.window.document;
      globalThis.Node = dom.window.Node;
    }

    afterEach(() => {
      if (previous === undefined) return;
      globalThis.document = previous.document;
      globalThis.Node = previous.Node;
      previous = undefined;
    });

    it("is the data-release of a trio page", () => {
      load('<main data-page="trio" data-release="data-2026-10-14-2"></main><p class="data-strip">Data: <time datetime="2026-10-14">2026-10-14</time></p>');
      expect(readRelease()).toBe("data-2026-10-14-2");
    });

    it("is the date of the strip at the top of any other page", () => {
      load('<header><p class="wrap data-strip">Data: <time datetime="2026-10-14">2026-10-14</time> &middot; Game patch: <time datetime="2026-09-22">2026-09-22</time></p></header><main></main>');
      expect(readRelease()).toBe("2026-10-14");
    });

    it("is the date of a time in the footer when the strip is not there", () => {
      load('<main></main><footer><time datetime="2026-10-14">2026-10-14</time></footer>');
      expect(readRelease()).toBe("2026-10-14");
    });

    it("is nothing for a page that names no release", () => {
      load("<main><p>nothing</p></main>");
      expect(readRelease()).toBeNull();
    });

    it("reads the policy a page gives itself, once, and whether it is before every stylesheet and script", () => {
      load(
        '<html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' +
          NOTFOUND_POLICY +
          '"><link rel="stylesheet" href="/a.css"><script src="/boot.js"></script></head><body><main data-page="notfound"></main><script type="module" src="/app.js"></script></body></html>',
      );
      expect(readPagePolicies()).toEqual({ policies: [NOTFOUND_POLICY], first: true, notfound: true });
    });

    it("sees a policy that comes after a script", () => {
      load('<html><head><script src="/boot.js"></script><meta http-equiv="content-security-policy" content="x"></head><body><main data-page="trio"></main></body></html>');
      expect(readPagePolicies()).toEqual({ policies: ["x"], first: false, notfound: false });
    });

    it("sees a policy that comes after an inline script or a stylesheet", () => {
      load('<html><head><script>1</script><meta http-equiv="Content-Security-Policy" content="x"></head><body></body></html>');
      expect(readPagePolicies().first).toBe(false);
      load('<html><head><link rel="stylesheet" href="/a.css"><meta http-equiv="Content-Security-Policy" content="x"></head><body></body></html>');
      expect(readPagePolicies().first).toBe(false);
    });

    it("sees no policy, and two", () => {
      load("<html><head></head><body><main></main></body></html>");
      expect(readPagePolicies()).toEqual({ policies: [], first: false, notfound: false });
      load('<html><head><meta http-equiv="Content-Security-Policy" content="a"><meta http-equiv="Content-Security-Policy" content="b"></head><body></body></html>');
      expect(readPagePolicies().policies).toEqual(["a", "b"]);
    });
  });

  it("is the policy that the 404 page of the site gives itself", () => {
    expect(NOTFOUND_POLICY).toBe("script-src 'self'; connect-src 'none'");
    expect(NOTFOUND_PATH).toMatch(/^\/[a-z-]+\/$/);
  });
});

// ---- the page that came ------------------------------------------------------------------------------------------------------------------

describe("redirectedTo", () => {
  const asked = "https://site.example/trio/pal-mnk-ber/";

  it("is nothing for the address that was asked for, whatever fragment the page has put on it", () => {
    expect(redirectedTo(asked, asked)).toBeNull();
    expect(redirectedTo(asked, `${asked}#top`)).toBeNull();
    expect(redirectedTo("http://127.0.0.1:8799/item/w9001/", "http://127.0.0.1:8799/item/w9001/")).toBeNull();
  });

  it("says where a page on the same site went, by its path", () => {
    expect(redirectedTo(asked, "https://site.example/")).toBe("/");
    expect(redirectedTo(asked, "https://site.example/trio/pal-mnk-ber")).toBe("/trio/pal-mnk-ber"); // (the slash is part of the address)
    expect(redirectedTo(asked, "https://site.example/trio/pal-mnk-ber/?x=1")).toBe("/trio/pal-mnk-ber/?x=1");
    expect(redirectedTo(asked, "https://site.example/trio/other/#top")).toBe("/trio/other/");
  });

  it("says where a page on another site went, by the whole address, and no more of it than a line holds", () => {
    expect(redirectedTo(asked, "https://elsewhere.example/trio/pal-mnk-ber/")).toBe("https://elsewhere.example/trio/pal-mnk-ber/");
    expect(redirectedTo(asked, "http://site.example/trio/pal-mnk-ber/")).toBe("http://site.example/trio/pal-mnk-ber/");
    expect(redirectedTo(asked, `https://elsewhere.example/${"a".repeat(500)}`).length).toBeLessThanOrEqual(200);
  });

  it("says that a page that is not at an address at all went somewhere", () => {
    expect(redirectedTo(asked, "about:blank")).toBe("about:blank");
    expect(redirectedTo(asked, "")).not.toBeNull();
    expect(redirectedTo(asked, undefined)).not.toBeNull();
  });
});

describe("newestRelease", () => {
  let folder;
  const pointers = (...names) => {
    folder = mkdtempSync(join(tmpdir(), "smoke-live-pointers-"));
    for (const name of names) writeFileSync(join(folder, name), "{}");
    return folder;
  };
  afterEach(() => {
    if (folder !== undefined) rmSync(folder, { recursive: true, force: true });
    folder = undefined;
  });

  it("is nothing when there is no folder, or nothing in it", () => {
    expect(newestRelease(join(tmpdir(), "smoke-live-no-such-folder-of-pointers"))).toBeNull();
    expect(newestRelease(pointers())).toBeNull();
  });

  it("is the tag of the pointer of the latest day", () => {
    expect(newestRelease(pointers("data-2026-10-14.json", "data-2026-10-17.json", "data-2026-09-30.json"))).toBe("data-2026-10-17");
  });

  it("puts the second release of a day after the first, and the tenth after the ninth", () => {
    expect(newestRelease(pointers("data-2026-10-14.json", "data-2026-10-14-2.json"))).toBe("data-2026-10-14-2");
    rmSync(folder, { recursive: true, force: true });
    expect(newestRelease(pointers("data-2026-10-14-9.json", "data-2026-10-14-10.json", "data-2026-10-14-2.json"))).toBe("data-2026-10-14-10");
    rmSync(folder, { recursive: true, force: true });
    expect(newestRelease(pointers("data-2026-10-14-3.json", "data-2026-10-15.json"))).toBe("data-2026-10-15");
  });

  it("takes no notice of what is not a pointer: other files, temporary files, a date that is not one, a folder with the name of a pointer", () => {
    const where = pointers("data-2026-10-14.json", "README.md", "notes.json", "data-2026-10-20.json.tmp", ".data-2026-10-21.json.123.tmp", "data-2026-13-45.json", "data-2026-02-30.json", "data-2026-10-22.JSON");
    mkdirSync(join(where, "data-2026-10-25.json"));
    expect(newestRelease(where)).toBe("data-2026-10-14");
  });
});

describe("ignoredConsoleMessage", () => {
  const url = "https://site.example/trio/pal-mnk-ber/";
  const message = (text, at = url, type = "error") => ({ type: () => type, text: () => text, location: () => ({ url: at }) });
  const note = "Failed to load resource: the server responded with a status of 404 ()";

  it("is the note the browser makes of the status of the document it was sent, which the check reads on its own", () => {
    expect(ignoredConsoleMessage(message(note), url)).toBe(true);
    expect(ignoredConsoleMessage(message("Failed to load resource: the server responded with a status of 500 (Internal Server Error)"), url)).toBe(true);
  });

  it("is not a message of the page itself that happens to say something about a status (G10)", () => {
    expect(ignoredConsoleMessage(message("backend failed: status of 500"), url)).toBe(false);
    expect(ignoredConsoleMessage(message("Error: the sync stopped with a status of 503 and lost your data"), url)).toBe(false);
    expect(ignoredConsoleMessage(message(`${note} and then the page broke`), url)).toBe(false);
  });

  it("is not the note about any other address than the document's: a file the page asked for is an error of the page", () => {
    expect(ignoredConsoleMessage(message(note, "https://site.example/assets/app.js"), url)).toBe(false);
    expect(ignoredConsoleMessage(message(note, "https://elsewhere.example/trio/pal-mnk-ber/"), url)).toBe(false);
  });

  it("is nothing else when the message is not an error at all", () => {
    expect(ignoredConsoleMessage(message("ok", url, "log"), url)).toBe(false);
  });
});

describe("navigationMs", () => {
  it("is the time of a request when nothing is paced", () => {
    expect(navigationMs(0)).toBe(30_000);
  });

  it("leaves room for the paced requests of a page: at least 200 of them, not 40 (G11)", () => {
    expect(navigationMs(1) - navigationMs(0)).toBeGreaterThanOrEqual(200 * 1000);
    expect(navigationMs(0.5) - navigationMs(0)).toBeGreaterThanOrEqual(200 * 500);
  });
});

describe("readPageKind", () => {
  let previous;
  function load(html) {
    const dom = new JSDOM(html);
    previous ??= globalThis.document;
    globalThis.document = dom.window.document;
  }
  afterEach(() => {
    if (previous === undefined) return;
    globalThis.document = previous;
    previous = undefined;
  });

  it("is what the main element says the page is", () => {
    load('<body><main id="main" class="wrap trio" data-page="trio"></main></body>');
    expect(readPageKind()).toBe("trio");
    load('<body><main data-page="item"></main></body>');
    expect(readPageKind()).toBe("item");
  });

  it("is nothing for a page whose main element says nothing, or that has none", () => {
    load("<body><main></main></body>");
    expect(readPageKind()).toBeNull();
    load('<body><div data-page="trio"></div></body>');
    expect(readPageKind()).toBeNull();
  });
});

// ---- the stamp -------------------------------------------------------------------------------------------------------------------------

describe("stampText", () => {
  it("is the UTC time to the second, with a Z and a line end, as the release build reads it", () => {
    expect(stampText(new Date("2026-10-18T10:00:03.987Z"))).toBe("2026-10-18T10:00:03Z\n");
    expect(stampText(new Date("2026-10-18T12:00:00+02:00"))).toBe("2026-10-18T10:00:00Z\n");
    expect(STAMP_NAME).toBe("smoke-live");
  });
});

// ---- the log: a trace of every run, for a task that has no window -------------------------------------------------------------------------

describe("logLine", () => {
  const when = new Date("2026-10-18T10:00:03.456Z");

  it("is the UTC time, the outcome and the text on one line", () => {
    expect(logLine(when, "ok", "smoke-live: ok, 7 pages")).toBe("2026-10-18T10:00:03Z ok smoke-live: ok, 7 pages");
    expect(logLine(new Date("2026-10-18T12:00:03+02:00"), "refused", "no headers file")).toBe("2026-10-18T10:00:03Z refused no headers file");
  });

  it("has no line break, and is cut to a line", () => {
    const line = logLine(when, "error", `first\r\nsecond\tthird\u2028fourth ${"x".repeat(1000)}`);
    expect(line.startsWith("2026-10-18T10:00:03Z error first second third fourth x")).toBe(true);
    expect(line).not.toMatch(/[\u0000-\u001f\u007f\u0085\u2028\u2029]/);
    expect(line.endsWith("...")).toBe(true);
    expect(line.length).toBeLessThanOrEqual(440);
  });

  it.each(["ok", "failed", "refused", "error", "interrupted"])("says the outcome %s", (outcome) => {
    expect(logLine(when, outcome, "text").split(" ")[1]).toBe(outcome);
  });

  it.each(["", "OK", "maybe", "ok text"])("refuses the outcome %j", (outcome) => {
    expect(() => logLine(when, outcome, "text")).toThrow();
  });
});

describe("appendLog", () => {
  const folders = [];
  const scratch = () => {
    const folder = mkdtempSync(join(tmpdir(), "smoke-live-log-"));
    folders.push(folder);
    return folder;
  };
  afterAll(() => {
    for (const folder of folders) rmSync(folder, { recursive: true, force: true });
  });
  const at = (seconds) => new Date(Date.UTC(2026, 9, 18, 10, 0, seconds));

  it("makes the folder and the file, and adds a line for each run", () => {
    const folder = join(scratch(), "not", "there", "yet");
    const target = appendLog(folder, at(3), "ok", "first");
    expect(target).toBe(join(folder, "smoke-live.log"));
    appendLog(folder, at(4), "failed", "second");
    expect(readFileSync(target, "utf8")).toBe("2026-10-18T10:00:03Z ok first\n2026-10-18T10:00:04Z failed second\n");
  });

  it("keeps its last 200 lines", () => {
    const folder = scratch();
    for (let number = 0; number < 205; number += 1) appendLog(folder, at(number), "ok", `run ${number}`);
    const lines = readFileSync(join(folder, "smoke-live.log"), "utf8").trimEnd().split("\n");
    expect(LOG_LINES).toBe(200);
    expect(lines).toHaveLength(200);
    expect(lines[0]).toMatch(/ ok run 5$/);
    expect(lines.at(-1)).toMatch(/ ok run 204$/);
  });

  it("cuts a longer log at the next line, and drops its blank lines", () => {
    const folder = scratch();
    writeFileSync(join(folder, "smoke-live.log"), Array.from({ length: 300 }, (_, number) => `2026-01-01T00:00:00Z ok old ${number}\n\n`).join(""));
    appendLog(folder, at(3), "ok", "new");
    const lines = readFileSync(join(folder, "smoke-live.log"), "utf8").trimEnd().split("\n");
    expect(lines).toHaveLength(200);
    expect(lines[0]).toMatch(/old 101$/);
    expect(lines.at(-1)).toBe("2026-10-18T10:00:03Z ok new");
    expect(lines).not.toContain("");
  });

  it("is no failure when the log cannot be written", () => {
    const folder = scratch();
    mkdirSync(join(folder, "smoke-live.log")); // (a folder where the file should be)
    expect(appendLog(folder, at(3), "ok", "line")).toBeNull();
    writeFileSync(join(folder, "a-file"), "not a folder");
    expect(appendLog(join(folder, "a-file", "inside"), at(3), "ok", "line")).toBeNull();
  });
});

// ---- the command, as far as it goes without a browser ------------------------------------------------------------------------------------

describe("main, before a browser is needed", () => {
  const folders = [];
  const servers = [];
  const scratch = () => {
    const folder = mkdtempSync(join(tmpdir(), "smoke-live-"));
    folders.push(folder);
    return folder;
  };

  async function site(answers, seen = []) {
    const server = http.createServer((request, response) => {
      seen.push({ url: request.url, at: performance.now() });
      const answer = answers[request.url];
      if (answer === undefined) {
        response.writeHead(404, { "content-type": "text/plain" });
        response.end("no such file");
        return;
      }
      response.writeHead(answer.status ?? 200, { "content-type": answer.type ?? "application/json" });
      response.end(typeof answer.body === "string" ? answer.body : JSON.stringify(answer.body));
    });
    await new Promise((done) => server.listen(0, "127.0.0.1", done));
    servers.push(server);
    return `http://127.0.0.1:${server.address().port}`;
  }

  async function run(argv) {
    const lines = { out: [], err: [] };
    const code = await main(argv, { log: (line) => lines.out.push(line), error: (line) => lines.err.push(line), now: () => new Date("2026-10-18T10:00:03Z") });
    return { code, ...lines };
  }

  afterEach(async () => {
    await Promise.all(servers.splice(0).map((server) => new Promise((done) => server.close(done))));
  });
  afterAll(() => {
    for (const folder of folders) rmSync(folder, { recursive: true, force: true });
  });

  it("prints the usage and succeeds for --help", async () => {
    const result = await run(["--help"]);
    expect(result).toEqual({ code: 0, out: [USAGE], err: [] });
  });

  it("ends with status 2, one line and the usage for an option that does not exist, and starts nothing", async () => {
    const result = await run(["--no-such-option"]);
    expect(result.code).toBe(2);
    expect(result.err[0]).toMatch(/^smoke-live: /);
    expect(result.err).toContain(USAGE);
    expect(result.out).toEqual([]);
  });

  it("ends with status 2 when the headers file cannot be read, or sets no policy", async () => {
    const folder = scratch();
    const missing = await run(["--headers-file", join(folder, "none.txt"), "--out", folder]);
    expect(missing.code).toBe(2);
    expect(missing.err).toHaveLength(1);
    expect(missing.err[0]).toMatch(/^smoke-live: cannot read the headers file none\.txt/);
    writeFileSync(join(folder, "empty.txt"), "/*\n  X-Robots-Tag: noindex\n", "utf8");
    const bare = await run(["--headers-file", join(folder, "empty.txt"), "--out", folder]);
    expect(bare.code).toBe(2);
    expect(bare.err).toHaveLength(1);
    expect(bare.err[0]).toMatch(/^smoke-live: the headers file sets no content-security-policy/);
    expect(existsSync(join(folder, "smoke-live.last-run"))).toBe(false);
  });

  it.each([
    ["answers 500", { "/engine-manifest.json": { status: 500, body: "oops", type: "text/plain" } }, "/engine-manifest.json answered 500"],
    ["answers 404", {}, "/engine-manifest.json answered 404"],
    ["is HTML", { "/engine-manifest.json": { body: "<html>Maintenance</html>", type: "text/html" } }, "/engine-manifest.json is not JSON"],
    ["lists no trios", { "/engine-manifest.json": { body: { trios: {}, items: { path: "/items.json" } } } }, "the manifest lists no trio"],
    ["has no list of trios", { "/engine-manifest.json": { body: { items: { path: "/items.json" } } } }, "the manifest has no list of trios"],
    ["does not say where the item table is", { "/engine-manifest.json": { body: { trios: { "pal-mnk-ber": [50] } } } }, "the manifest does not say where the item table is"],
    [
      "names an item table that is not there",
      { "/engine-manifest.json": { body: { trios: { "pal-mnk-ber": [50] }, items: { path: "/items.json" } } } },
      "/items.json answered 404",
    ],
    [
      "names an item table that is not JSON",
      { "/engine-manifest.json": { body: { trios: { "pal-mnk-ber": [50] }, items: { path: "/items.json" } } }, "/items.json": { body: "x", type: "text/html" } },
      "/items.json is not JSON",
    ],
    [
      "has an item table with no item that has a page",
      {
        "/engine-manifest.json": { body: { trios: { "pal-mnk-ber": [50] }, items: { path: "/items.json" } } },
        "/items.json": { body: { items: [{ id: 1, evidence: { level: "hidden" } }] } },
      },
      "the item table lists no item that has a page",
    ],
  ])("fails with a short list, and writes no stamp, when the manifest %s", async (_, answers, problem) => {
    const base = await site(answers);
    const folder = scratch();
    const result = await run(["--base", base, "--out", folder]);
    expect(result.code).toBe(1);
    expect(result.out).toEqual([]);
    expect(result.err[0]).toBe(`smoke-live: FAILED, 1 problem on ${base} (seed 202642)`);
    expect(result.err[1]).toBe(`- ${problem}`);
    expect(result.err).toHaveLength(2);
    expect(existsSync(join(folder, "smoke-live.last-run"))).toBe(false);
  });

  it("fails, with the same short list, when nothing answers at the address", async () => {
    const closed = await site({});
    const server = servers.pop();
    await new Promise((done) => server.close(done));
    const folder = scratch();
    const result = await run(["--base", closed, "--out", folder]);
    expect(result.code).toBe(1);
    expect(result.err[1]).toMatch(/^- \/engine-manifest\.json could not be fetched/);
    expect(existsSync(join(folder, "smoke-live.last-run"))).toBe(false);
  });

  it("asks for the manifest and then for the item table, and for nothing else, a pace apart", async () => {
    const seen = [];
    const base = await site({ "/engine-manifest.json": { body: { trios: { "pal-mnk-ber": [50] }, items: { path: "/items.json" } } } }, seen);
    const result = await run(["--base", base, "--out", scratch(), "--pace", "0.6"]);
    expect(result.code).toBe(1);
    expect(seen.map((request) => request.url)).toEqual(["/engine-manifest.json", "/items.json"]);
    // the pace is a floor, which a busy machine only makes higher; the first request may reach the server a moment after it was begun and the second on a connection that is open, so the
    // gap that is asked for is half of it
    expect(seen[1].at - seen[0].at).toBeGreaterThanOrEqual(300);
  });

  it("fails, before a browser is started and with no stamp, when it chose no trio page or no item page, and says how many it chose (G2)", async () => {
    const items = { items: [1, 2, 3].map((id) => ({ id, evidence: { level: "strict" } })) };
    const base = await site({ "/engine-manifest.json": { body: { trios: { "pal-mnk-ber": [50] }, items: { path: "/items.json" } } }, "/items.json": { body: items } });
    const folder = scratch();
    for (const [trios, itemCount, chose] of [
      [0, 0, "0 trio pages and 0 item pages"],
      [0, 3, "0 trio pages and 3 item pages"],
      [2, 0, "1 trio page and 0 item pages"],
    ]) {
      const options = { ...parseArgs(["--base", base, "--out", folder], new Date("2026-10-18T10:00:03Z")), trios, items: itemCount };
      const result = await runCheck(options, { now: () => new Date("2026-10-18T10:00:03Z") });
      expect(result.code).toBe(1);
      expect(result.lines).toEqual([
        `smoke-live: FAILED, 1 problem on ${base} (seed 202642)`,
        `- the check chose ${chose}; it needs at least one of each, or its stamp would say that pages were checked when they were not`,
      ]);
      expect(existsSync(join(folder, "smoke-live.last-run"))).toBe(false);
    }
  });

  /** A browser that loads nothing and records the time every page was given to load: enough for the run to go through its pages. */
  function fakeBrowser() {
    const gotos = [];
    let current = "";
    const page = {
      on() {},
      async goto(url, options) {
        gotos.push({ url, timeout: options?.timeout });
        current = url;
        return { status: () => 200, headers: () => ({}), request: () => ({ redirectedFrom: () => null }) };
      },
      locator: () => ({ waitFor: async () => {} }),
      waitForLoadState: async () => {},
      waitForTimeout: async () => {},
      evaluate: async (fn) => {
        if (fn.name === "readPageKind") return current.includes("/trio/") ? "trio" : current.includes("/item/") ? "item" : "notfound";
        if (fn.name === "readPagePolicies") return { policies: [NOTFOUND_POLICY], first: true, notfound: true };
        return null;
      },
      url: () => current,
      close: async () => {},
    };
    const context = { newPage: async () => page, route: async () => {} };
    const browser = { newContext: async () => context, close: async () => {} };
    return { gotos, launch: async () => browser };
  }

  it.each([0, 0.5, 2])("gives every page the time that navigationMs says for a pace of %s, and never the time of one request (R13)", async (pace) => {
    const items = { items: [{ id: 1, evidence: { level: "strict" } }] };
    const base = await site({ "/engine-manifest.json": { body: { trios: { "pal-mnk-ber": [50] }, items: { path: "/items.json" } } }, "/items.json": { body: items } });
    const browser = fakeBrowser();
    const options = parseArgs(["--base", base, "--out", scratch(), "--trios", "1", "--items", "1", "--pace", String(pace), "--settle", "0"], new Date("2026-10-18T10:00:03Z"));
    await runCheck(options, { now: () => new Date("2026-10-18T10:00:03Z"), launch: browser.launch });
    expect(browser.gotos.map((visit) => new URL(visit.url).pathname)).toEqual(["/trio/pal-mnk-ber/", "/item/w1/", NOTFOUND_PATH]);
    for (const visit of browser.gotos) expect(visit.timeout).toBe(navigationMs(pace));
    if (pace > 0) expect(navigationMs(pace)).toBeGreaterThan(navigationMs(0)); // (a paced page is given more than the time of one request, or the test could not tell the use from the constant)
  });

  describe("the log of the run", () => {
    const logOf = (folder) => readFileSync(join(folder, "smoke-live.log"), "utf8").trimEnd().split("\n");

    it("says refused, with the reason, when the headers file cannot be read, and writes no stamp", async () => {
      const folder = scratch();
      const result = await run(["--headers-file", join(folder, "none.txt"), "--out", folder]);
      expect(result.code).toBe(2);
      expect(logOf(folder)).toEqual(["2026-10-18T10:00:03Z refused cannot read the headers file none.txt (ENOENT)"]);
      expect(existsSync(join(folder, "smoke-live.last-run"))).toBe(false);
    });

    it("says failed, with the header and the first problem, when the site fails the check, and adds a line for each run", async () => {
      const base = await site({ "/engine-manifest.json": { status: 500, body: "oops", type: "text/plain" } });
      const folder = scratch();
      await run(["--base", base, "--out", folder]);
      expect(logOf(folder)).toEqual([`2026-10-18T10:00:03Z failed smoke-live: FAILED, 1 problem on ${base} (seed 202642); first: /engine-manifest.json answered 500`]);
      await run(["--base", base, "--out", folder]);
      expect(logOf(folder)).toHaveLength(2);
    });

    it("says refused, in the log of the checks folder, for a command line that is wrong", async () => {
      const folder = process.env.TRIOFORGE_CHECKS_DIR;
      rmSync(join(folder, "smoke-live.log"), { force: true });
      const result = await run(["--settle=soon", "--out", scratch()]);
      expect(result.code).toBe(2);
      expect(logOf(folder)).toEqual(["2026-10-18T10:00:03Z refused --settle must be a number from 0 to 60"]);
    });

    it("writes nothing for --help", async () => {
      const folder = process.env.TRIOFORGE_CHECKS_DIR;
      rmSync(join(folder, "smoke-live.log"), { force: true });
      await run(["--help"]);
      expect(existsSync(join(folder, "smoke-live.log"))).toBe(false);
    });

    it("changes nothing in the outcome when the log cannot be written", async () => {
      const folder = scratch();
      mkdirSync(join(folder, "smoke-live.log"));
      const result = await run(["--headers-file", join(folder, "none.txt"), "--out", folder]);
      expect(result.code).toBe(2);
      expect(result.err[0]).toMatch(/^smoke-live: cannot read the headers file none\.txt/);
    });
  });

  it("logs only the kind of an unexpected fault, never its message, which can hold a path of this computer (R11)", async () => {
    const items = { items: [{ id: 1, evidence: { level: "strict" } }] };
    const base = await site({ "/engine-manifest.json": { body: { trios: { "pal-mnk-ber": [50] }, items: { path: "/items.json" } } }, "/items.json": { body: items } });
    const folder = scratch();
    const secret = join(folder, "private", "file.txt");
    const launch = async () => {
      throw new Error(`EACCES: permission denied, open '${secret}'`);
    };
    await expect(main(["--base", base, "--out", folder], { log: () => {}, error: () => {}, now: () => new Date("2026-10-18T10:00:03Z"), launch })).rejects.toThrow(/EACCES/);
    const log = readFileSync(join(folder, "smoke-live.log"), "utf8");
    expect(log).toBe("2026-10-18T10:00:03Z error an unexpected fault (Error); run the check by hand to see what it was\n");
    expect(log).not.toContain(secret);
  });

  describe("run as a command", () => {
    async function command(args, env = {}) {
      try {
        const { stdout, stderr } = await promisify(execFile)(process.execPath, [SCRIPT, ...args], { timeout: 60_000, env: { ...process.env, ...env } });
        return { code: 0, stdout, stderr };
      } catch (error) {
        return { code: error.code, stdout: error.stdout, stderr: error.stderr };
      }
    }

    it("prints the usage and exits 0 for --help", async () => {
      const result = await command(["--help"]);
      expect(result.code).toBe(0);
      expect(result.stdout.trim()).toBe(USAGE);
      expect(result.stderr).toBe("");
    }, 60_000);

    it("exits 2 with the usage on standard error for an option that does not exist", async () => {
      const result = await command(["--no-such-option"]);
      expect(result.code).toBe(2);
      expect(result.stdout).toBe("");
      expect(result.stderr).toContain("smoke-live: ");
      expect(result.stderr).toContain("usage: node scripts/smoke_live.mjs");
    }, 60_000);

    it("says, when the browser cannot be started, a fixed sentence with no path of this computer, on the screen and in the log (R11)", async () => {
      const items = { items: [{ id: 1, evidence: { level: "strict" } }] };
      const base = await site({ "/engine-manifest.json": { body: { trios: { "pal-mnk-ber": [50] }, items: { path: "/items.json" } } }, "/items.json": { body: items } });
      const folder = scratch();
      const noBrowsers = scratch(); // (a folder with no browser in it: Playwright then says where it looked for one)
      const result = await command(["--base", base, "--out", folder], { PLAYWRIGHT_BROWSERS_PATH: noBrowsers });
      expect(result.code).toBe(2);
      const log = readFileSync(join(folder, "smoke-live.log"), "utf8");
      expect(log.trim()).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z refused cannot start Chromium; install it with: npx playwright install chromium$/);
      for (const text of [result.stderr, log]) {
        expect(text).not.toContain(noBrowsers);
        expect(text).not.toMatch(/ms-playwright|Executable|[A-Za-z]:[\\/]|[\\/]Users[\\/]/i);
      }
      expect(result.stderr).toContain("smoke-live: cannot start Chromium; install it with: npx playwright install chromium");
    }, 60_000);

    it("exits 1 with the list on standard error, and nothing on standard output, when the site cannot be read, and leaves no stamp", async () => {
      const base = await site({ "/engine-manifest.json": { status: 503, body: "busy", type: "text/plain" } });
      const folder = scratch();
      const result = await command(["--base", base, "--out", folder]);
      expect(result.code).toBe(1);
      expect(result.stdout).toBe("");
      expect(result.stderr.split(/\r?\n/).filter(Boolean)).toEqual([expect.stringMatching(/^smoke-live: FAILED, 1 problem on http:\/\/127\.0\.0\.1:\d+ \(seed \d{6}\)$/), "- /engine-manifest.json answered 503"]);
      expect(existsSync(join(folder, "smoke-live.last-run"))).toBe(false);
    }, 60_000);
  });
});
