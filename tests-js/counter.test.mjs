// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// The page counter (Cloudflare Web Analytics, Part M): the page script adds ONE script element for it, and only when the page was opened with no kit link, when the build gave the page a token, and
// through the one Trusted Types policy of the site, which lets exactly that address through for it. Every token here is invented.

import { readFileSync, readdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const STATIC = resolve(HERE, "../pipeline/trioforge/site/static");
const file = (name) => resolve(STATIC, name).replaceAll("\\", "/");
const TOKEN = "0123456789abcdef0123456789abcdef"; // (invented)
const SCRIPT = "https://static.cloudflareinsights.com/beacon.min.js";
const WORKER = "/assets/engine/worker-AAAAAAAA.js";
const PAGE = "/trio/pal-mnk-ber/";
const NONE = { payload: null, source: null, cleared: false };

/** A Trusted Types object that behaves as the browser's does: a name may be made once, and what a policy makes is an object, not a string. */
function fakeTrustedTypes() {
  const names = new Set();
  const made = [];
  return {
    made,
    createPolicy(name, rules) {
      if (names.has(name)) throw new TypeError(`Policy with name "${name}" already exists.`);
      names.add(name);
      made.push({ name, rules });
      return {
        name,
        createScriptURL(input) {
          const value = rules.createScriptURL(input);
          return { trusted: true, value, toString: () => value };
        },
      };
    },
  };
}

function page({ token = TOKEN, kitFragment, name = "trio" } = {}) {
  document.head.replaceChildren();
  document.body.replaceChildren();
  if (token !== null) {
    const meta = document.createElement("meta");
    meta.setAttribute("name", "trioforge-counter");
    meta.setAttribute("content", token);
    document.head.append(meta);
  }
  const main = document.createElement("main");
  main.id = "main";
  main.dataset.page = name;
  document.body.append(main);
  delete document.documentElement.dataset.kitFragment;
  if (kitFragment !== undefined) document.documentElement.dataset.kitFragment = kitFragment;
}

const counters = () => [...document.querySelectorAll("script[data-cf-beacon]")];

let counter;
beforeEach(async () => {
  vi.resetModules();
  window.history.replaceState(null, "", PAGE);
  counter = await import(file("counter.js"));
});
afterEach(() => {
  document.head.replaceChildren();
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

describe("the page counter", () => {
  it("is one script element, from the one address, with the token and the history tracking switched off, made through the policy (a script added by code is async whatever it says, so it says nothing of defer)", () => {
    page();
    const tt = fakeTrustedTypes();
    expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: tt })).toBe(true);
    const [script] = counters();
    expect(counters()).toHaveLength(1);
    expect(script.hasAttribute("defer"), "defer does nothing on a script that code adds").toBe(false);
    // (that it is async as added is shown in a browser: tests-e2e/analytics.spec.mjs; jsdom does not model the flag)
    expect(script.getAttribute("src")).toBe(SCRIPT); // (jsdom keeps what the policy gave: the fake's object stringifies to its value below)
    expect(JSON.parse(script.getAttribute("data-cf-beacon"))).toEqual({ token: TOKEN, spa: false });
    expect(tt.made).toHaveLength(1);
    expect(tt.made[0].name).toBe("trioforge");
  });

  it("is added once: a second call, a repaint or a restored page adds nothing", () => {
    page();
    const tt = fakeTrustedTypes();
    expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: tt })).toBe(true);
    expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: tt })).toBe(false);
    window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: tt })).toBe(false);
    expect(counters()).toHaveLength(1);
  });

  it("is not added when a script for it is in the page already, whoever put it there", async () => {
    page();
    const own = document.createElement("script");
    own.setAttribute("data-cf-beacon", "{}");
    document.body.append(own);
    expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: fakeTrustedTypes() })).toBe(false);
    expect(counters()).toHaveLength(1);
  });

  for (const [what, kit] of [
    ["opened from a kit link (the fragment cleared)", { payload: "AQID", source: "fragment", cleared: true }],
    ["opened from a kit link whose fragment is still in the address", { payload: "AQID", source: "fragment", cleared: false }],
    ["opened from a kit link, with an empty payload (#k alone)", { payload: "", source: "fragment", cleared: true }],
    ["reloaded, the kit living on in the history entry", { payload: "AQID", source: "state", cleared: false }],
    ["reloaded, with a state that holds an empty kit", { payload: "", source: "state", cleared: false }],
  ]) {
    it(`is never added to a page ${what}`, () => {
      page();
      const tt = fakeTrustedTypes();
      expect(counter.addCounter({ document, window, loaded: window.location.href, kit, trustedTypes: tt })).toBe(false);
      expect(counters()).toHaveLength(0);
      expect(tt.made, "no policy is made for it either").toHaveLength(0);
    });
  }

  for (const state of ["cleared", "kept"]) {
    it(`is never added when the page says that it found a kit fragment (data-kit-fragment is ${state}), whatever the result passed in says`, () => {
      page({ kitFragment: state });
      expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: fakeTrustedTypes() })).toBe(false);
      expect(counters()).toHaveLength(0);
    });
  }

  it("is never added while a kit fragment is in the address", () => {
    page();
    window.history.replaceState(null, "", `${PAGE}#k=AQID`);
    expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: fakeTrustedTypes() })).toBe(false);
    window.history.replaceState(null, "", `${PAGE}#k`);
    expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: fakeTrustedTypes() })).toBe(false);
    expect(counters()).toHaveLength(0);
  });

  it("is added to a page whose fragment is the id of an element of the page (the fragment is the page's own), and to none whose fragment is anything else", () => {
    page();
    const target = document.createElement("section");
    target.id = "robust";
    document.body.append(target);
    window.history.replaceState(null, "", `${PAGE}#robust`);
    expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: fakeTrustedTypes() })).toBe(true);
    page();
    window.history.replaceState(null, "", `${PAGE}#robust`); // (no such element: a fragment that the page does not know is not one that is known to be clean)
    expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: fakeTrustedTypes() })).toBe(false);
  });

  it("is never added to the 404 page", () => {
    page({ name: "notfound" });
    expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: fakeTrustedTypes() })).toBe(false);
    expect(counters()).toHaveLength(0);
  });

  for (const [what, token] of [
    ["none in the page", null],
    ["upper case", TOKEN.toUpperCase()],
    ["one short", TOKEN.slice(1)],
    ["one long", TOKEN + "0"],
    ["not hex", "g".repeat(32)],
    ["with a quote in it", TOKEN.slice(0, 30) + '"}'],
    ["empty", ""],
    ["with a space", TOKEN + " "],
    ["with a line end", TOKEN + "\n"],
  ]) {
    it(`is not added when the token is ${what}`, () => {
      page({ token });
      const tt = fakeTrustedTypes();
      expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: tt })).toBe(false);
      expect(counters()).toHaveLength(0);
      expect(tt.made).toHaveLength(0);
    });
  }

  for (const [what, none] of [["none", undefined], ["null", null], ["an object with no createPolicy", {}], ["a createPolicy that is no function", { createPolicy: 5 }]]) {
    it(`works in a browser with no Trusted Types (${what}): the same checks, and the plain address`, () => {
      page();
      expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: none })).toBe(true);
      expect(counters()[0].getAttribute("src")).toBe(SCRIPT);
      expect(counter.addCounter({ document, window, loaded: window.location.href, kit: { payload: "AQID", source: "state", cleared: false }, trustedTypes: none })).toBe(false);
    });
  }

  it("adds a classic script element, not a module: no type attribute, the address only through the policy (the decision of R7 in DECISIONS: change it only with a reason)", () => {
    page();
    const tt = fakeTrustedTypes();
    expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: tt })).toBe(true);
    const [script] = counters();
    expect(script.getAttribute("type"), "a classic script: Cloudflare's own snippet says module, ours does not, and DECISIONS says why").toBeNull();
    expect(script.type).toBe("");
    expect(tt.made).toHaveLength(1);
  });

  it("lets the error of a policy that cannot be made come through: nothing is added", () => {
    page();
    const refusing = {
      createPolicy() {
        throw new TypeError('Policy with name "trioforge" disallowed.');
      },
    };
    expect(() => counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: refusing })).toThrow(/disallowed/);
    expect(counters()).toHaveLength(0);
  });
});

// ---- which address may be counted: one function decides (P4) ----------------------------------------------------------------------------------------------

const PAYLOAD = "AQIDBAUGBwgJCgsMDQ4P"; // (made up)
const ORIGIN = "https://trioforge.test";
/** Every spelling of a kit link that the site's own take does not read, and so counts as a page with no kit: the address of each still holds the payload. */
const KIT_SPELLINGS = [
  `#k=${PAYLOAD}`, "#k", "#K", `#K=${PAYLOAD}`, `#%6B=${PAYLOAD}`, `#%6b=${PAYLOAD}`, `#k%3D${PAYLOAD}`, `#k%3d${PAYLOAD}`, `#x&k=${PAYLOAD}`, `#/k=${PAYLOAD}`, `# k=${PAYLOAD}`, `#%20k=${PAYLOAD}`,
  `#%256B=${PAYLOAD}`, `#x%26k%3D${PAYLOAD}`, `#?k=${PAYLOAD}`, `#k=`, `?k=${PAYLOAD}`, `?K=${PAYLOAD}`, `?x=1&k=${PAYLOAD}`, `?%6B=${PAYLOAD}`, `?%4b=${PAYLOAD}`, "?k", "?x=1&K", `?x=1&k=${PAYLOAD}#main`,
  `?race=OGR#k=${PAYLOAD}`,
];

describe("which address may be counted", () => {
  const withElements = (...ids) => {
    page();
    for (const id of ids) {
      const node = document.createElement("section");
      node.id = id;
      document.body.append(node);
    }
  };

  for (const spelling of KIT_SPELLINGS) {
    it(`never counts the address ${JSON.stringify(spelling)}: it holds a kit`, () => {
      withElements("main", "robust");
      const address = `${ORIGIN}${PAGE}${spelling}`;
      expect(counter.holdsAKit(address)).toBe(true);
      expect(counter.mayBeCounted(address, document)).toBe(false);
      window.history.replaceState(null, "", `${PAGE}${spelling}`);
      const tt = fakeTrustedTypes();
      expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: tt })).toBe(false);
      expect(counters()).toHaveLength(0);
      expect(tt.made, "no policy is made for it either").toHaveLength(0);
    });
  }

  for (const [what, search, hash, ids] of [
    ["no query and no fragment", "", "", []],
    ["the switches of a trio page", "?race=OGR&role=tank&tier=4&buffs=raid", "", []],
    ["a query and the anchor main, which the page has", "?race=OGR", "#main", ["main"]],
    ["a rule of the rules page, which the page has", "", "#weapons.ranged_factor", ["weapons.ranged_factor"]],
    ["the heading of the confidence seals", "", "#seals-h", ["seals-h"]],
    ["the list of the open tests", "", "#open-tests", ["open-tests"]],
    ["a rule id with a percent-encoded character, as an address may be written", "", "#tier.void%5Fmote", ["tier.void_mote"]],
    ["#search, which the home page reads as a command and is no element id (SITE_ANCHORS)", "", "#search", []],
    ["a query that has a word with a k in it, and an anchor of the page", "?role=task", "#robust", ["robust"]],
    ["every switch of a trio page at once", "?race=OGR&role=tank&tier=4&setup=dw&buffs=raid&haste=1&w=h1h2h2&p=nnnnnnnn", "", []],
    ["an empty query (a question mark and nothing after it)", "?", "", []],
  ]) {
    it(`counts ${what}`, () => {
      withElements(...ids);
      const address = `${ORIGIN}${PAGE}${search}${hash}`;
      expect(counter.holdsAKit(address)).toBe(false);
      expect(counter.mayBeCounted(address, document)).toBe(true);
      window.history.replaceState(null, "", `${PAGE}${search}${hash}`);
      expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: fakeTrustedTypes() })).toBe(true);
    });
  }

  for (const hash of ["#nothing-like-this", "#robust", "#MAIN", "#main-1", "#x", "#a=b", "#%E0%A4%A"]) {
    it(`does not count a fragment that is no id of the page and no anchor of the site: ${hash} (it is not known to be clean)`, () => {
      withElements("main");
      const address = `${ORIGIN}${PAGE}${hash}`;
      expect(counter.mayBeCounted(address, document)).toBe(false);
    });
  }

  // ---- the query side has an allowlist as the fragment side has (Q4): a page is counted only when its query is empty or every key of it is one of the site's own switches ----

  /** Spellings of a kit that no part of the site makes or reads (a hand-made link), in a query, and one past the third round of encoding in a fragment: none may be counted. */
  const HAND_MADE = [
    `?k%3D${PAYLOAD}`, `?k%253D${PAYLOAD}`, `?+k=${PAYLOAD}`, `?%20k=${PAYLOAD}`, `?x=1;k=${PAYLOAD}`, `?k[]=${PAYLOAD}`, `?k%00=${PAYLOAD}`, `?\uff4b=${PAYLOAD}`, // (the eight of the review's probe)
    `?kk=${PAYLOAD}`, `?x=k=${PAYLOAD}`, `?%6B%00=${PAYLOAD}`, `?k\t=${PAYLOAD}`, `?race=OGR;k=${PAYLOAD}`, `?race=OGR%3Bk%3D${PAYLOAD}`, `?role=%256B%253D${PAYLOAD}`, `?w=${PAYLOAD}&k`,
    `#k%2525253D${PAYLOAD}`, `#k${encodeURIComponent(encodeURIComponent(encodeURIComponent(encodeURIComponent("=")))) }${PAYLOAD}`, `#%2525256B=${PAYLOAD}`,
    "?utm_source=newsletter", "?race=OGR&utm_medium=x", "?fbclid=abc", "?ev=strict", "?RACE=OGR", "?race[]=OGR", "?%72ace=OGR&x",
  ];

  for (const spelling of HAND_MADE) {
    it(`never counts the hand-made address ${JSON.stringify(spelling)}`, () => {
      withElements("main", "robust");
      expect(counter.mayBeCounted(`${ORIGIN}${PAGE}${spelling}`, document)).toBe(false);
      window.history.replaceState(null, "", `${PAGE}${spelling}`);
      const tt = fakeTrustedTypes();
      expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: tt })).toBe(false);
      expect(tt.made).toHaveLength(0);
    });
  }

  it("holds a kit in the spellings of a query and of a fragment that the probe found, however many times they are encoded", async () => {
    for (const spelling of [`?k%3D${PAYLOAD}`, `?k%253D${PAYLOAD}`, `?x=1;k=${PAYLOAD}`, `?race=OGR;k=${PAYLOAD}`, `?race=OGR%3Bk%3D${PAYLOAD}`, `?+k=${PAYLOAD}`, `?%20k=${PAYLOAD}`, `?w=${PAYLOAD}&k`, `#k%2525253D${PAYLOAD}`, `#%2525256B=${PAYLOAD}`]) {
      expect(counter.holdsAKit(`${ORIGIN}${PAGE}${spelling}`), spelling).toBe(true);
    }
    for (const clean of ["?race=OGR&role=tank", "?role=task", "?setup=dw#robust", `?w=ABCDEF`, "#main"]) expect(counter.holdsAKit(`${ORIGIN}${PAGE}${clean}`), clean).toBe(false);
  });

  it("holds the allowlist of query keys in one place, SITE_QUERY_KEYS, and that list is the switches that the trio page reads and writes: a key the page code starts to use fails this test until it is listed", () => {
    const text = readFileSync(resolve(STATIC, "trio.js"), "utf8");
    const keys = new Set();
    for (const match of text.matchAll(/params\.(?:get|getAll|set)\("([A-Za-z]+)"/g)) keys.add(match[1]);
    if (/params\.(?:get|getAll|set)\(HASTE_PARAM\b/.test(text)) keys.add(text.match(/const HASTE_PARAM = "([a-z]+)";/)[1]);
    for (const match of text.matchAll(/new URLSearchParams\(\{([^}]*)\}\)/g)) for (const named of match[1].matchAll(/\b([a-z]+):/g)) keys.add(named[1]);
    expect([...keys].sort()).toEqual([...counter.SITE_QUERY_KEYS].sort());
    expect(counter.SITE_QUERY_KEYS).toEqual(["race", "role", "tier", "setup", "buffs", "haste", "w", "p"]);
    expect(Object.isFrozen(counter.SITE_QUERY_KEYS)).toBe(true);
    // (the reports link is not one of the page's own addresses: its `page` parameter is in the link of the footer and never in the address that is counted)
  });

  // a value the page code takes for each switch (the shape of it: the table SITE_QUERY_SHAPES is held to trio.js below)
  const VALID = { race: "OGR", role: "castertank", tier: "10", setup: "1h-shield", buffs: "group enchanter", haste: "1", w: "h1h2h2", p: "nnnnnnnn" };
  for (const key of ["race", "role", "tier", "setup", "buffs", "haste", "w", "p"]) {
    it(`counts a page whose query is the switch ${key}, with a value the page takes`, () => {
      withElements("main");
      expect(counter.mayBeCounted(`${ORIGIN}${PAGE}?${key}=${encodeURIComponent(VALID[key])}`, document)).toBe(true);
    });
  }

  // ---- R3: the value of a switch has the shape the page code takes for it; the decoding is capped; an address of a size that no link of the site has is not counted ------------------

  it("does not count a kit code, or anything that is not the shape the page takes, as the value of a switch (?w=<payload>, ?p=<payload>, ?race=<payload>, and the others)", () => {
    withElements("main");
    for (const key of ["race", "role", "tier", "setup", "buffs", "haste", "w", "p"]) {
      for (const value of [PAYLOAD, `${PAYLOAD}${PAYLOAD}`, "x".repeat(100), "A=B", "", " ", "OGR OGR", "%4F%47%52", "<script>"]) {
        const address = `${ORIGIN}${PAGE}?${key}=${encodeURIComponent(value)}`;
        if (VALID[key] === value) continue;
        expect(counter.mayBeCounted(address, document), `${key}=${JSON.stringify(value)}`).toBe(false);
      }
    }
    expect(counter.mayBeCounted(`${ORIGIN}${PAGE}?race=${PAYLOAD}`, document)).toBe(false);
    expect(counter.mayBeCounted(`${ORIGIN}${PAGE}?w=${PAYLOAD}`, document)).toBe(false);
    expect(counter.mayBeCounted(`${ORIGIN}${PAGE}?p=${PAYLOAD}`, document)).toBe(false);
    expect(counter.mayBeCounted(`${ORIGIN}${PAGE}?race=OGR&race=OGR`, document), "a switch given twice, each with a value of the shape: the page decides what to do with it").toBe(true);
  });

  it("holds the shapes in ONE table, SITE_QUERY_SHAPES, whose keys are SITE_QUERY_KEYS, and the table takes every value that trio.js takes for its switch and reads no other (the pin)", () => {
    expect(Object.keys(counter.SITE_QUERY_SHAPES)).toEqual([...counter.SITE_QUERY_KEYS]);
    expect(Object.isFrozen(counter.SITE_QUERY_SHAPES)).toBe(true);
    const shapes = counter.SITE_QUERY_SHAPES;
    const trio = readFileSync(resolve(STATIC, "trio.js"), "utf8");
    const priorities = readFileSync(resolve(STATIC, "priorities.js"), "utf8");
    // what trio.js takes: the codes of the baked page (the WHOLE value of each, whatever characters it has: a code with a digit or a dash that the shape does not take must fail here, not go uncaptured),
    // every code that the pipeline's data module knows (roles and setups from site/data.py, every race code from rules/races.json), the digits of a tier, the characters of w and p
    const baked = readFileSync(resolve(HERE, "../fixtures/site/contract/trio-main.html"), "utf8");
    const values = (pattern, text = baked) => [...text.matchAll(pattern)].map((match) => match[1]);
    const optgroups = values(/<optgroup[^>]*>(.*?)<\/optgroup>/gs).join(""); // (the races: the tiers' options are not in a group)
    const dataModule = readFileSync(resolve(HERE, "../pipeline/trioforge/site/data.py"), "utf8");
    const tuple = (name) => values(/"([^"]+)"/g, dataModule.match(new RegExp(`^${name}(?:: [^=]+)? = \\(([^)]*)\\)`, "m"))[1]);
    const races = JSON.parse(readFileSync(resolve(HERE, "../rules/races.json"), "utf8")).races.map((race) => race.code);
    const known = { race: races, role: tuple("ROLES"), setup: tuple("SETUPS") };
    for (const [key, list] of Object.entries(known)) expect(list.length, `the pipeline knows codes for ${key}`).toBeGreaterThan(3);
    const accepted = {
      race: [...values(/<option value="([^"]+)"/g, optgroups), ...known.race],
      role: [...values(/name="role"[^>]*? value="([^"]+)"/g), ...known.role],
      tier: values(/<option value="([^"]+)"[^>]*data-label="\+/g),
      setup: [...values(/name="setup"[^>]*? value="([^"]+)"/g), ...known.setup],
      buffs: [...values(/name="buffs"[^>]*? value="([^"]+)"/g), "enchanter", "group enchanter"],
      haste: ["1"],
    };
    for (const [key, list] of Object.entries(accepted)) {
      expect(list.length, `the baked page has values for ${key}`).toBeGreaterThan(0);
      for (const value of list) expect(shapes[key].test(value), `${key}=${value}`).toBe(true);
    }
    expect(accepted.race.length, "every race code of the pipeline, and the options of the baked page").toBeGreaterThanOrEqual(16);
    expect(trio).toContain("const POSITIONS = /^[h12]+$/;");
    expect(trio).toMatch(/\/\^\\d\{1,2\}\$\/\.test\(tier\)/);
    expect(priorities).toContain('["0", "Off", "x0"]');
    const stats = [...priorities.matchAll(/^\s*\["[a-z]+", "[A-Za-z ]+"\],?$/gm)].length;
    expect(stats, "the stats of the priorities, one character each").toBeGreaterThan(5);
    for (const length of [1, 3, 6, 12]) expect(shapes.w.test("h12".repeat(length).slice(0, length)), `w of ${length}`).toBe(true);
    expect(shapes.p.test("0lnht".repeat(3).slice(0, stats))).toBe(true);
    expect(shapes.w.test("h1x")).toBe(false);
    expect(shapes.p.test("0lnhtz")).toBe(false);
  });

  it("caps the decoding at eight rounds: an address that is still changing after that is not clean, and one encoded eight times is still read", () => {
    const encode = (text, times) => {
      let out = text;
      for (let i = 0; i < times; i += 1) out = encodeURIComponent(out);
      return out;
    };
    withElements("main", "a:b");
    expect(counter.mayBeCounted(`${ORIGIN}${PAGE}#${encode("a:b", 3)}`, document), "three rounds: an id of the page").toBe(true);
    expect(counter.mayBeCounted(`${ORIGIN}${PAGE}#${encode("a:b", 8)}`, document), "eight rounds: still read").toBe(true);
    expect(counter.mayBeCounted(`${ORIGIN}${PAGE}#${encode("a:b", 9)}`, document), "nine: still changing at the cap").toBe(false);
    for (const times of [9, 20, 200]) {
      expect(counter.holdsAKit(`${ORIGIN}${PAGE}#${encode("a:b", times)}`), `${times} rounds is not known to be clean`).toBe(true);
      expect(counter.holdsAKit(`${ORIGIN}${PAGE}?race=${encode("O=R", times)}`)).toBe(true);
    }
  });

  it("does not spend the time of the page on an address built to be slow: eight rounds and a length limit, whatever the nesting (a 64 KB nest took seconds before)", () => {
    withElements("main");
    const nest = (levels) => "%25".repeat(levels) + "3D";
    for (const levels of [2000, 8000, 32000]) {
      const started = performance.now();
      const held = counter.holdsAKit(`${ORIGIN}${PAGE}#k${nest(levels)}${PAYLOAD}`);
      const counted = counter.mayBeCounted(`${ORIGIN}${PAGE}?race=OGR${nest(levels)}`, document);
      const took = performance.now() - started;
      expect(held, `${levels} levels`).toBe(true);
      expect(counted, `${levels} levels`).toBe(false);
      expect(took, `${levels} levels took ${took} ms`).toBeLessThan(150);
    }
  });

  it("does not count an address whose query and fragment together are longer than 4,096 characters, though every part of it would be clean", () => {
    const longId = "x".repeat(5000);
    withElements("main", longId);
    expect(counter.mayBeCounted(`${ORIGIN}${PAGE}#${longId}`, document)).toBe(false);
    const fits = "y".repeat(4000);
    withElements("main", fits);
    expect(counter.mayBeCounted(`${ORIGIN}${PAGE}#${fits}`, document), "an id of 4,000 characters is within the limit").toBe(true);
    expect(counter.mayBeCounted(`${ORIGIN}${PAGE}?race=OGR#${"y".repeat(4090)}`, document)).toBe(false);
  });

  it("also reads the links that the Python of the site builds, and checks each fragment against the page its path names, where the templates decide it (Q6)", () => {
    const read = (path) => readFileSync(resolve(HERE, "..", path), "utf8");
    const site = "pipeline/trioforge/site";
    // the links of the Python: a literal "/path/#id" (view.py: RACIALS_PAGES = "/sources/#races-box")
    const links = [];
    for (const entry of readdirSync(resolve(HERE, "..", site), { withFileTypes: true })) {
      if (!entry.isFile() || !entry.name.endsWith(".py")) continue;
      for (const match of read(`${site}/${entry.name}`).matchAll(/["'](\/(?:[a-z0-9-]+\/)*)#([A-Za-z][A-Za-z0-9_.-]*)["']/g)) links.push({ path: match[1], id: match[2], file: entry.name });
    }
    expect(links, "the one link of the Python that is known today").toContainEqual({ path: "/sources/", id: "races-box", file: "view.py" });
    // the links of the templates and the page code, with the path they have (none: the page itself)
    const templates = readdirSync(resolve(HERE, "..", `${site}/templates`)).filter((name) => name.endsWith(".j2"));
    const idsOf = (name) => new Set([...read(`${site}/templates/${name}`).matchAll(/\bid="([A-Za-z][A-Za-z0-9_.-]*)"/g)].map((match) => match[1]));
    const everywhere = idsOf("base.html.j2"); // (the frame of every page)
    const rules = idsOf("rules.html.j2");
    for (const rule of JSON.parse(read("rules/rules.json")).rules) rules.add(rule.id); // (the rules page makes an element of each rule: its id is the rule's)
    const pages = { "/": "home.html.j2", "/about/": "about.html.j2", "/sources/": "sources.html.j2", "/changelog/": "changelog.html.j2" };
    const idsOfPath = (path) => (path === "/rules/" ? new Set([...rules, ...everywhere]) : path in pages ? new Set([...idsOf(pages[path]), ...everywhere]) : null);
    for (const name of Object.values(pages)) expect(templates, name).toContain(name);
    for (const { path, id, file } of links) {
      const ids = idsOfPath(path);
      if (ids === null) continue; // (a page that no single template makes, such as a trio page: not decided here)
      expect(ids.has(id), `${file} links to ${path}#${id}, which is no element of that page's template`).toBe(true);
    }
    // the same for the `href="/path/#id"` links of the TEMPLATES (the links of the page code are read by the pin above, for the fragment only, with no path; what is NOT read: a link that Python builds by an
    // f-string or a concatenation, a Jinja href with an expression in it (`/rules/#{{ rule.id }}`, which is safe while every rule id is in the rules set), and a trio page, which no single template decides)
    for (const name of templates) {
      for (const match of read(`${site}/templates/${name}`).matchAll(/href="(\/(?:[a-z0-9-]+\/)*)#([A-Za-z][A-Za-z0-9_.-]*)"/g)) {
        const ids = idsOfPath(match[1]);
        if (ids !== null) expect(ids.has(match[2]), `${name} links to ${match[1]}#${match[2]}, which is no element of that page's template`).toBe(true);
      }
    }
  });

  it("holds an address that cannot be read as a kit, whatever it is, and counts none of them", () => {
    expect(counter.holdsAKit("not an address")).toBe(true);
    expect(counter.holdsAKit(undefined)).toBe(true);
    expect(counter.holdsAKit(null)).toBe(true);
    expect(counter.mayBeCounted("not an address", document)).toBe(false);
  });

  it("knows the anchors of the site from the files of the site: every fragment that a link of a template or of the page code points to is an id of an element of the site, or is in SITE_ANCHORS and no more", () => {
    const read = (path) => readFileSync(resolve(HERE, "..", path), "utf8");
    const files = [];
    const walk = (folder) => {
      for (const entry of readdirSync(resolve(HERE, "..", folder), { withFileTypes: true })) {
        const path = `${folder}/${entry.name}`;
        if (entry.isDirectory()) walk(path);
        else files.push(path);
      }
    };
    walk("pipeline/trioforge/site/templates");
    walk("pipeline/trioforge/site/static");
    const targets = new Set();
    const ids = new Set();
    for (const path of files.filter((file) => /\.(j2|js)$/.test(file))) {
      const text = read(path);
      // (a link to a fragment: href="/rules/#x", href="#main", href: "/rules/#x", SEARCH_HREF = "/#search", SEARCH_HASH = "#search", setAttribute("href", "/#search"))
      for (const match of text.matchAll(/(?:href|HREF|SEARCH_HASH)[^\n]{0,24}?["'](?:\/[a-z/]*)?#([A-Za-z][A-Za-z0-9_.-]*)["']/g)) targets.add(match[1]);
      for (const match of text.matchAll(/\bid="([A-Za-z][A-Za-z0-9_.-]*)"/g)) ids.add(match[1]);
    }
    for (const rule of JSON.parse(read("rules/rules.json")).rules) ids.add(rule.id);
    expect(targets.size).toBeGreaterThan(4);
    expect([...targets].filter((target) => !ids.has(target)).sort()).toEqual([...counter.SITE_ANCHORS].sort());
    expect(counter.SITE_ANCHORS).toEqual(["search"]);
    // and the one that is no id is the one that the code of the home page reads as a command
    expect(read("pipeline/trioforge/site/static/picker.js")).toContain('const SEARCH_HASH = "#search";');
    expect(read("pipeline/trioforge/site/static/notfound.js")).toContain('export const SEARCH_HREF = "/#search";');
    // every one of them is counted, on a page that has the element
    for (const target of targets) {
      withElements(...(counter.SITE_ANCHORS.includes(target) ? [] : [target]));
      expect(counter.mayBeCounted(`${ORIGIN}/rules/#${target}`, document), target).toBe(true);
    }
  });
});

// ---- the history of the tab (P2) ----------------------------------------------------------------------------------------------------------------------

describe("the history of the tab that the page can see", () => {
  const entries = (...urls) => urls.map((url) => ({ url }));
  const withNavigation = (navigation) => {
    Object.defineProperty(window, "navigation", { value: navigation, configurable: true });
  };
  afterEach(() => {
    delete window.navigation;
  });

  for (const url of [`${ORIGIN}/trio/pal-mnk-ber/#k=${PAYLOAD}`, `${ORIGIN}/rules/?k=${PAYLOAD}`, `${ORIGIN}/#K=${PAYLOAD}`, `${ORIGIN}/trio/x/#%6B=${PAYLOAD}`, `${ORIGIN}/trio/x/#k`]) {
    it(`does not add the counter when an entry of the tab's history holds a kit: ${url.slice(ORIGIN.length)}`, () => {
      page();
      withNavigation({ entries: () => entries(`${ORIGIN}/`, url, `${ORIGIN}/rules/`) });
      const tt = fakeTrustedTypes();
      expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: tt })).toBe(false);
      expect(counters()).toHaveLength(0);
      expect(tt.made).toHaveLength(0);
    });
  }

  for (const url of [`${ORIGIN}/trio/x/?k%3D${PAYLOAD}`, `${ORIGIN}/trio/x/?k%253D${PAYLOAD}`, `${ORIGIN}/trio/x/?+k=${PAYLOAD}`, `${ORIGIN}/trio/x/?%20k=${PAYLOAD}`, `${ORIGIN}/trio/x/?x=1;k=${PAYLOAD}`, `${ORIGIN}/trio/x/?k[]=${PAYLOAD}`, `${ORIGIN}/trio/x/?k%00=${PAYLOAD}`, `${ORIGIN}/trio/x/?\uff4b=${PAYLOAD}`, `${ORIGIN}/trio/x/#k%2525253D${PAYLOAD}`, `${ORIGIN}/trio/x/#%2525256B=${PAYLOAD}`, `${ORIGIN}/rules/?utm_source=a`]) {
    it(`does not add the counter when an entry of the history has an address the page would not be counted with: ${url.slice(ORIGIN.length)} (the same function, not the kit test alone)`, () => {
      page();
      withNavigation({ entries: () => entries(`${ORIGIN}/`, url, `${ORIGIN}/trio/pal-mnk-ber/`) });
      const tt = fakeTrustedTypes();
      expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: tt })).toBe(false);
      expect(counters()).toHaveLength(0);
      expect(tt.made).toHaveLength(0);
    });
  }

  it("adds the counter when no entry holds a kit, with other fragments and queries in them", () => {
    page();
    withNavigation({ entries: () => entries(`${ORIGIN}/`, `${ORIGIN}/trio/pal-mnk-ber/?race=OGR#robust`, `${ORIGIN}/rules/#tier.void_mote`) });
    expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: fakeTrustedTypes() })).toBe(true);
  });

  it("does not add it when the list of entries cannot be read, whatever the error", async () => {
    for (const navigation of [
      { entries() { throw new Error("refused"); } },
      { entries: () => { throw new DOMException("not fully active", "InvalidStateError"); } },
      { entries: () => entries("not an address") },
      { entries: () => 5 },
      { entries: () => [undefined] },
    ]) {
      vi.resetModules();
      counter = await import(file("counter.js"));
      page();
      withNavigation(navigation);
      expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: fakeTrustedTypes() }), String(Object.keys(navigation))).toBe(false);
      expect(counters()).toHaveLength(0);
    }
  });

  it("skips an entry that gives no address (one that is not of the same origin: a kit link of this site is never one), and counts as it did where the Navigation API is missing", async () => {
    page();
    withNavigation({ entries: () => [{ url: null }, { url: `${ORIGIN}/` }] });
    expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: fakeTrustedTypes() })).toBe(true);
    for (const none of [undefined, null, {}, { entries: 5 }]) {
      vi.resetModules();
      counter = await import(file("counter.js"));
      page();
      withNavigation(none);
      expect(counter.addCounter({ document, window, loaded: window.location.href, kit: NONE, trustedTypes: fakeTrustedTypes() }), String(none)).toBe(true);
    }
  });
});

describe("the page script", () => {
  const app = readFileSync(resolve(STATIC, "app.js"), "utf8");

  it("adds the counter last, after the page has been started, and takes the kit it was opened with from first.js", () => {
    expect(app).toMatch(/import \{ addCounter \} from "\.\/counter\.js";/);
    const start = app.slice(app.indexOf("function start()"), app.indexOf("if (document.readyState"));
    expect(start).toMatch(/addCounter\(\{[^}]*\bkit\b[^}]*\}\);\s*\}\s*$/); // (the last thing start() does: a page whose script fails before it is not counted)
    expect(start.indexOf("initTrio")).toBeLessThan(start.indexOf("addCounter"));
  });

  it("holds the address of the counter script in one place, the Trusted Types policy, and in no other file of the page script", () => {
    const holders = [];
    for (const name of ["app.js", "first.js", "counter.js", "theme.js", "trio.js", "picker.js", "tt-policy.js", "tt-record.js", "canonical.js", "notfound.js", "boot.js"]) {
      if (readFileSync(resolve(STATIC, name), "utf8").includes("cloudflareinsights")) holders.push(name);
    }
    expect(holders).toEqual(["tt-record.js"]);
  });
});

describe("the policy of the site, with the counter's address in it", () => {
  /** A fresh copy of the module that holds the record (a bundle has one), and of the optimizer's way in over it: the page script and the optimizer's client are two bundles, each with its own. */
  const copy = async () => {
    vi.resetModules();
    return { record: await import(file("tt-record.js")), policy: await import(file("tt-policy.js")) };
  };
  const withPolicy = async () => (await copy()).record;

  it("is made once for the page, whichever bundle of the page asks first (the page script and the optimizer's client each have a copy of the module)", async () => {
    const tt = fakeTrustedTypes();
    const a = await copy();
    const b = await copy();
    expect(a.record).not.toBe(b.record); // (two copies, as two bundles are)
    const counterPolicy = a.record.getCounterPolicy(tt);
    const enginePolicy = b.policy.getAssetPolicy(tt, [WORKER]); // (a second copy asks: it would make a second policy of the same name, which the browser refuses)
    expect(tt.made).toHaveLength(1);
    expect(tt.made[0].name).toBe("trioforge");
    expect(Object.keys(tt.made[0].rules)).toEqual(["createScriptURL"]);
    expect(counterPolicy.scriptURL(SCRIPT)).toMatchObject({ trusted: true, value: SCRIPT });
    expect(enginePolicy.scriptURL(WORKER)).toMatchObject({ trusted: true, value: WORKER });
    const rule = tt.made[0].rules.createScriptURL;
    expect(rule(SCRIPT)).toBe(SCRIPT);
    expect(rule(WORKER)).toBe(WORKER);
    for (const refused of ["https://evil.example/x.js", "https://static.cloudflareinsights.com/other.js", `${SCRIPT}?x=1`, `${SCRIPT}#x`, " " + SCRIPT, "/assets/engine/worker-CCCCCCCC.js", "javascript:1", "", undefined, 5]) {
      expect(() => rule(refused), String(refused)).toThrow(TypeError);
    }
  });

  it("gives the counter its one address and nothing else, and the optimizer its listed paths and nothing else", async () => {
    const tt = fakeTrustedTypes();
    const { record, policy } = await copy();
    const counterPolicy = record.getCounterPolicy(tt);
    const enginePolicy = policy.getAssetPolicy(tt, [WORKER]);
    for (const refused of [WORKER, "/x.js", `${SCRIPT}?x`, "https://static.cloudflareinsights.com/", "http://static.cloudflareinsights.com/beacon.min.js", `${SCRIPT} `, "", undefined, 5, { toString: () => SCRIPT }]) {
      expect(() => counterPolicy.scriptURL(refused), String(refused)).toThrow(TypeError);
    }
    expect(() => enginePolicy.scriptURL(SCRIPT), "the optimizer's way in does not give the counter's address").toThrow(TypeError);
    expect(counterPolicy.name).toBe("trioforge");
  });

  it("lists the optimizer's files by the same pattern as engine/manifest.js: the record (which imports nothing, so the page script can carry it) and the manifest answer alike", async () => {
    const { record } = await copy();
    const { isEnginePath } = await import(file("engine/manifest.js"));
    const hashed = (name, hash, ext) => `/assets/engine/${name}-${hash}.${ext}`;
    const corpus = [
      hashed("client", "AAAAAAAA", "js"), hashed("worker", "A1B2C3D4", "js"), hashed("kitvalue", "0123456789ABCDEF", "js"), hashed("highs", "A".repeat(32), "wasm"),
      hashed("client", "AAAAAAA", "js"), hashed("client", "A".repeat(33), "js"), hashed("client", "aaaaaaaa", "js"), hashed("highs", "AAAAAAAA", "js"), hashed("client", "AAAAAAAA", "wasm"),
      hashed("other", "AAAAAAAA", "js"), "/assets/engine/data/items-0123456789ABCDEF.json", "/assets/engine/client-AAAAAAAA.js?x=1", "/assets/engine/client-AAAAAAAA.js#x", "/assets/engine/../app-AAAAAAAA.js",
      "assets/engine/client-AAAAAAAA.js", "//evil.example" + hashed("client", "AAAAAAAA", "js"), "https://trioforge.test" + hashed("client", "AAAAAAAA", "js"), hashed("client", "AAAAAAAA", "js") + "\n", "", "/", "/assets/app-AAAAAAAA.js",
    ];
    for (const path of corpus) {
      let listed = true;
      try {
        record.getEnginePolicy(fakeTrustedTypes(), [path]);
      } catch (error) {
        listed = false;
        expect(error, path).toBeInstanceOf(TypeError);
      }
      expect(listed, path).toBe(isEnginePath(path));
    }
  });

  it("does not let the counter's address through before the counter asks for it", async () => {
    const tt = fakeTrustedTypes();
    const { policy } = await copy();
    policy.getAssetPolicy(tt, [WORKER]);
    expect(() => tt.made[0].rules.createScriptURL(SCRIPT)).toThrow(TypeError);
  });

  it("works without Trusted Types: the same check, and a plain address back", async () => {
    const { getCounterPolicy } = await withPolicy();
    for (const none of [undefined, null, {}, { createPolicy: 5 }]) {
      const policy = getCounterPolicy(none);
      expect(policy.scriptURL(SCRIPT)).toBe(SCRIPT);
      expect(() => policy.scriptURL("https://evil.example/x.js")).toThrow(TypeError);
    }
  });

  it("cannot be replaced or widened from outside: the review's sequence (a stranger replaces the record, lists a path, enables the counter, redefines the property) changes nothing the optimizer or the counter was given", async () => {
    const KEY = "trioforge.tt-policy"; // (the property of the window that the copies of the module share the record under)
    const tt = fakeTrustedTypes();
    const { record, policy } = await copy();
    record.getCounterPolicy(tt); // (a counted page: the page script asks first)
    const shared = globalThis[KEY];
    // what is under the name is a frozen getter and nothing else: no WeakMap to `set` a record into
    expect(Object.isFrozen(shared)).toBe(true);
    expect(Object.keys(shared)).toEqual(["get"]);
    expect(shared.set).toBeUndefined();
    expect(shared instanceof WeakMap).toBe(false);
    const found = shared.get(tt);
    expect(Object.isFrozen(found)).toBe(true);
    // the three things the probe did: replace the record, redefine or delete the property, change a method of the record
    expect(() => {
      shared.set(tt, { mintEngine: () => "https://static.cloudflareinsights.com/beacon.min.js" });
    }).toThrow(TypeError);
    expect(() => Object.defineProperty(globalThis, KEY, { value: new WeakMap() })).toThrow(TypeError);
    expect(() => {
      globalThis[KEY] = new WeakMap();
    }).toThrow(TypeError);
    expect(() => delete globalThis[KEY]).toThrow(TypeError);
    expect(() => {
      shared.get = () => undefined;
    }).toThrow(TypeError);
    expect(() => {
      found.mintEngine = () => "https://static.cloudflareinsights.com/beacon.min.js";
    }).toThrow(TypeError);
    // enabling the counter is for the one address, and once: another address, none, and a list are refused, and enabling again changes nothing
    for (const wrong of [undefined, "https://evil.example/x.js", "/assets/engine/worker-AAAAAAAA.js", ["https://static.cloudflareinsights.com/beacon.min.js"], { toString: () => "https://static.cloudflareinsights.com/beacon.min.js" }]) {
      expect(() => found.allowCounter(wrong), String(wrong)).toThrow(TypeError);
    }
    const enginePolicy = policy.getAssetPolicy(tt, ["/assets/engine/worker-AAAAAAAA.js"]);
    const minted = enginePolicy.scriptURL("/assets/engine/worker-AAAAAAAA.js");
    expect(minted.value, "the optimizer's worker address mints as itself, not as the counter's").toBe("/assets/engine/worker-AAAAAAAA.js");
    expect(() => enginePolicy.scriptURL("https://static.cloudflareinsights.com/beacon.min.js")).toThrow(TypeError);
    // a page that has not enabled the counter cannot be made to: on another Trusted Types object, nothing mints the counter's address until the counter's own way in asks for it
    const other = fakeTrustedTypes();
    const bare = policy.getAssetPolicy(other, ["/assets/engine/worker-AAAAAAAA.js"]);
    expect(bare.name).toBe("trioforge");
    expect(() => other.made[0].rules.createScriptURL("https://static.cloudflareinsights.com/beacon.min.js")).toThrow(TypeError);
  });

  it("cannot be widened or redirected by a script that changes a built-in AFTER the site's script has loaded: nothing on the minting path goes through a prototype (the review's three probes, and more)", async () => {
    const KEY = "trioforge.tt-policy"; // (the property of the window that the copies of the module share the record under)
    const EVIL = ["https://evil.example/x.js", "data:text/javascript,alert(1)", "/assets/anything.js", "/assets/engine/client-AAAAAAAA.js.evil", "__proto__", "constructor"];
    const tt = fakeTrustedTypes();
    const site = await copy(); // (the site's script: it made the record, with the optimizer's worker listed and the counter enabled)
    site.record.getCounterPolicy(tt);
    site.policy.getAssetPolicy(tt, [WORKER]);
    const later = await copy(); // (the optimizer's client, loaded later: a third copy of the module, which finds the record under the property)
    const rule = tt.made[0].rules.createScriptURL;
    const found = globalThis[KEY].get(tt);
    const refused = (run) => {
      try {
        run();
        return false;
      } catch (error) {
        return error instanceof TypeError;
      }
    };
    /** What a script of the page that has changed a built-in tries, as plain facts (the checks are made after the built-in is put back: the test's own tools use them). */
    const attempt = () => {
      const facts = {};
      for (let i = 0; i < EVIL.length; i += 1) {
        const evil = EVIL[i];
        facts[`list ${evil}`] = refused(() => found.listEngine([evil]));
        facts[`mint ${evil}`] = refused(() => found.mintEngine(evil));
        facts[`rule ${evil}`] = refused(() => rule(evil));
        facts[`has ${evil}`] = found.hasEngine(evil) === false;
        facts[`optimizer lists ${evil}`] = refused(() => later.policy.getAssetPolicy(tt, [evil]));
      }
      facts["the counter's address is still allowed"] = rule(SCRIPT) === SCRIPT;
      facts["the worker's address is still allowed"] = rule(WORKER) === WORKER;
      let minted;
      try {
        minted = String(later.policy.getAssetPolicy(tt, [WORKER]).scriptURL(WORKER).value);
      } catch {
        minted = WORKER; // (a refusal is a denial, not a widening: the built-in the script changed may well break the optimizer's way in)
      }
      facts["the worker mints as itself, never as the counter's address"] = minted === WORKER;
      return facts;
    };
    const FAILS = (facts) => Object.keys(facts).filter((name) => facts[name] !== true);
    /** Replace `object[name]` while `attempt` goes, and put it back whatever happens (with Reflect, which is not among the things changed: Object.defineProperty is one of them). */
    const under = (object, name, replacement) => {
      const own = Reflect.getOwnPropertyDescriptor(object, name);
      Reflect.defineProperty(object, name, { value: replacement, writable: true, configurable: true });
      try {
        return attempt();
      } finally {
        if (own) Reflect.defineProperty(object, name, own);
        else Reflect.deleteProperty(object, name);
      }
    };
    const forged = { mintEngine: () => ({ trusted: true, value: SCRIPT }), listEngine: () => undefined, hasEngine: () => true, allowCounter: () => undefined, mintCounter: () => ({ trusted: true, value: SCRIPT }) };
    const tampers = [
      ["RegExp.prototype.test (probe 1: every pattern matches)", RegExp.prototype, "test", () => true],
      ["RegExp.prototype.exec", RegExp.prototype, "exec", () => ["x"]],
      ["Set.prototype.has (probe 2: every set has everything)", Set.prototype, "has", () => true],
      ["Set.prototype.add", Set.prototype, "add", () => undefined],
      ["WeakMap.prototype.get (probe 3: a later copy is handed a forged record)", WeakMap.prototype, "get", () => forged],
      ["Map.prototype.get", Map.prototype, "get", () => forged],
      ["Array.prototype[Symbol.iterator]", Array.prototype, Symbol.iterator, function* () { yield EVIL[0]; }],
      ["Object.prototype.hasOwnProperty", Object.prototype, "hasOwnProperty", () => false],
      ["Function.prototype.call", Function.prototype, "call", () => true],
      ["Function.prototype.apply", Function.prototype, "apply", () => true],
      ["Object.freeze", Object, "freeze", (value) => value],
      ["Object.create", Object, "create", () => ({})],
      ["Object.defineProperty", Object, "defineProperty", () => undefined],
      ["String.prototype.startsWith", String.prototype, "startsWith", () => true],
      ["String.prototype.charCodeAt", String.prototype, "charCodeAt", () => 65],
      ["String.prototype.indexOf", String.prototype, "indexOf", () => 0],
      ["String.prototype.slice", String.prototype, "slice", () => WORKER],
    ];
    const results = tampers.map(([what, object, name, replacement]) => [what, FAILS(under(object, name, replacement))]);
    // an address of the shape of a key that an object inherits (a plain object, or a set made of keys, would say yes): the list has no prototype
    const keys = ["https://evil.example/x.js", "toString", "constructor", "data:text/javascript,alert(1)", "/assets/anything.js", "/assets/engine/client-AAAAAAAA.js.evil"];
    const saved = keys.map((key) => [key, Reflect.getOwnPropertyDescriptor(Object.prototype, key)]);
    for (const key of keys) Reflect.defineProperty(Object.prototype, key, { value: true, writable: true, configurable: true });
    let polluted;
    try {
      polluted = FAILS(attempt());
    } finally {
      for (const [key, own] of saved) {
        if (own) Reflect.defineProperty(Object.prototype, key, own);
        else Reflect.deleteProperty(Object.prototype, key);
      }
    }
    for (const [what, failed] of results) expect(failed, what).toEqual([]);
    expect(polluted, "Object.prototype carrying the keys of the evil addresses").toEqual([]);
    expect(FAILS(attempt()), "nothing was left changed").toEqual([]);
  });

  it("keeps no map of records, and no lookup on a prototype, on the way to a minted address (the code says it, and the header says what remains)", () => {
    const whole = readFileSync(resolve(STATIC, "tt-record.js"), "utf8");
    const code = whole.replace(/\/\*[\s\S]*?\*\//g, "").split("\n").filter((line) => !line.trimStart().startsWith("//")).join("\n"); // (what runs: no comment, no block of notes)
    for (const forbidden of [/\bnew\s+(?:Set|Map|WeakMap|WeakSet)\b/, /\.test\(/, /\.has\(/, /\.exec\(/, /\b(?:objects|found|made|engine)\.get\(/, /\.indexOf\(/, /\.startsWith\(/, /\bfor\s*\([^)]*\bof\b/, /\.\.\./, /\bENGINE_FILE\b/]) {
      expect(code, String(forbidden)).not.toMatch(forbidden);
    }
    const header = whole.split("\n").filter((line) => line.startsWith("//")).join(" ");
    expect(header).toMatch(/a script that runs BEFORE the site's script/);
    expect(header).toMatch(/pre-empt/);
    expect(header).toMatch(/content security policy|CSP/i);
  });

  it("keeps its one record out of reach of a script that wants to list another address: there is no way to add one", async () => {
    const tt = fakeTrustedTypes();
    const { getCounterPolicy } = await withPolicy();
    getCounterPolicy(tt);
    const shared = Object.getOwnPropertyDescriptor(globalThis, "trioforge.tt-policy");
    expect(shared).toBeDefined();
    expect(shared.enumerable).toBe(false);
    expect(shared.writable).toBe(false);
    const entry = shared.value.get(tt);
    for (const method of Object.values(entry).filter((value) => typeof value === "function")) {
      for (const stranger of ["https://evil.example/x.js", "/assets/app-AAAAAAAA.js"]) {
        try {
          method([stranger]);
          method(stranger);
        } catch {
          /* refusing is the right answer */
        }
        expect(() => tt.made[0].rules.createScriptURL(stranger), stranger).toThrow(TypeError);
      }
    }
  });
});
