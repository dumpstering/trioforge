// The page's side of the kit link: `takeKitFromLocation`, which the page script runs first. It lives in a module of its own (input/kitlocation.js) so that the first load
// carries this function and not the codec; its tests were part of kitcode.test.mjs and are moved here as they were (the codec is used only to show that what is taken can be
// decoded, and to read the limit of a payload from the one place that defines it).

import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KIT_ERRORS } from "../pipeline/trioforge/site/static/input/kitcode.js";
import { decodeKit } from "../pipeline/trioforge/site/static/input/kitdecode.js";
import { takeKitFromLocation } from "../pipeline/trioforge/site/static/input/kitlocation.js";

const MODULE_URL = new URL("../pipeline/trioforge/site/static/input/kitlocation.js", import.meta.url);

// ---- helpers copied from kitcode.test.mjs: the format, written a second time ----

// Canonical unsigned LEB128.
function leb(value) {
  const out = [];
  let rest = BigInt(value);
  do {
    let byte = Number(rest & 0x7fn);
    rest >>= 7n;
    if (rest > 0n) byte |= 0x80;
    out.push(byte);
  } while (rest > 0n);
  return out;
}

// A number in a field list is written as a canonical varint; an array is written as the raw bytes it holds.
function bytesOf(version, ...fields) {
  const out = [version];
  for (const field of fields) {
    if (Array.isArray(field)) out.push(...field);
    else out.push(...leb(field));
  }
  return out;
}
const toFragment = (bytes) => Buffer.from(bytes).toString("base64url");
const fragOf = (version, ...fields) => toFragment(bytesOf(version, ...fields));

const itemsOf = (ids) => new Map(ids.map((id) => [`w${id}`, { name: `Test item ${id}`, id }]));

// pal-mnk-ber (472), Ogre (9), level 50, then fields.
const HEAD = [472, 9, 50];
const GOOD = "AdgDCTIDAHAEAru2BAAV_____wcK"; // slots [0, 112, 4], [2, 72507, 0], [21, 2147483647, 10]
const GOOD_ITEMS = itemsOf([112, 72507, 2147483647]);

// ---- takeKitFromLocation ----

// A page's location and history, reduced to what the function uses. The URL rules are the real ones (URL).
function makeWindow(href, initialState = null) {
  let url = new URL(href);
  let state = initialState;
  const log = { replaceState: [], navigation: [] };
  const location = {
    get href() { return url.href; },
    get hash() { return url.hash; },
    get search() { return url.search; },
    get pathname() { return url.pathname; },
    assign: (target) => log.navigation.push(["assign", target]),
    replace: (target) => log.navigation.push(["replace", target]),
    reload: () => log.navigation.push(["reload"]),
  };
  const history = {
    get state() { return state; },
    replaceState(next, title, target) {
      log.replaceState.push({ state: next, title, url: target });
      const resolved = new URL(target, url);
      if (resolved.origin !== url.origin) throw new Error("SecurityError: replaceState across origins");
      state = structuredClone(next);
      url = resolved;
    },
  };
  return { location, history, log };
}
// What a reload does: the same URL and the same history entry state, a fresh page.
const reloaded = (win) => makeWindow(win.location.href, structuredClone(win.history.state));

const BASE = "https://example.test/trio/pal-mnk-ber/?race=OGR&tier=4";
const NONE = { payload: null, source: null, cleared: false };

describe("takeKitFromLocation", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("moves the #k= payload into history.state and clears the fragment, with one replaceState", () => {
    const win = makeWindow(`${BASE}#k=${GOOD}`);
    const taken = takeKitFromLocation(win);
    expect(taken).toEqual({ payload: GOOD, source: "fragment", cleared: true });
    expect(win.log.replaceState).toHaveLength(1);
    expect(win.log.replaceState[0].state).toEqual({ k: GOOD });
    expect(win.log.replaceState[0].url).toBe(BASE); // absolute; the path and the query stay
    expect(win.location.hash).toBe("");
    expect(win.location.href).toBe(BASE);
    expect(win.history.state).toEqual({ k: GOOD });
    expect(win.log.navigation).toEqual([]);
  });

  it("leaves nothing of the kit in the URL for a script that runs afterwards (the analytics beacon)", () => {
    const win = makeWindow(`${BASE}#k=${GOOD}`);
    takeKitFromLocation(win);
    const beaconSees = win.location.href;
    expect(beaconSees).not.toContain("#");
    expect(beaconSees).not.toContain("k=");
    expect(beaconSees).not.toContain(GOOD);
  });

  it("hands over a payload that decodes", () => {
    const win = makeWindow(`${BASE}#k=${GOOD}`);
    const { payload } = takeKitFromLocation(win);
    expect(decodeKit(payload, GOOD_ITEMS).errors).toEqual([]);
  });

  it("keeps the kit through a reload: the fragment is gone, history.state brings it back", () => {
    const first = makeWindow(`${BASE}#k=${GOOD}`);
    takeKitFromLocation(first);
    const second = reloaded(first);
    expect(second.location.hash).toBe("");
    const taken = takeKitFromLocation(second);
    expect(taken).toEqual({ payload: GOOD, source: "state", cleared: false });
    expect(second.log.replaceState).toEqual([]); // nothing to clear the second time
    expect(decodeKit(taken.payload, GOOD_ITEMS).errors).toEqual([]);
    // and again after another reload
    expect(takeKitFromLocation(reloaded(second)).payload).toBe(GOOD);
  });

  it("calling it twice on one page asks replaceState once", () => {
    const win = makeWindow(`${BASE}#k=${GOOD}`);
    takeKitFromLocation(win);
    expect(takeKitFromLocation(win)).toEqual({ payload: GOOD, source: "state", cleared: false });
    expect(win.log.replaceState).toHaveLength(1);
  });

  it("a new #k= link pasted into the open page replaces the stored kit", () => {
    const win = makeWindow(`${BASE}#k=${GOOD}`);
    takeKitFromLocation(win);
    const other = fragOf(1, ...HEAD, 0);
    const next = makeWindow(`${BASE}#k=${other}`, win.history.state);
    expect(takeKitFromLocation(next)).toEqual({ payload: other, source: "fragment", cleared: true });
    expect(next.history.state).toEqual({ k: other });
  });

  it("runs the same checks on what history.state brings back", () => {
    const tampered = [
      [fragOf(9, ...HEAD, 0), KIT_ERRORS.version],
      [fragOf(1, ...HEAD, 1, 0, 112, 99), KIT_ERRORS.tier],
      [`${GOOD}x`, KIT_ERRORS.length],
      [`${GOOD}\n`, KIT_ERRORS.alphabet],
    ];
    for (const [payload, message] of tampered) {
      const taken = takeKitFromLocation(makeWindow(BASE, { k: payload }));
      expect(taken).toEqual({ payload, source: "state", cleared: false });
      expect(decodeKit(taken.payload, GOOD_ITEMS).errors).toEqual([message]);
    }
  });

  it("finds no kit when the own k is not text", () => {
    for (const value of [42, null, undefined, {}, [], ["x"], true, 10n, Symbol("k"), () => GOOD, { toString: () => GOOD }]) {
      expect(takeKitFromLocation(makeWindow(BASE, { k: value }))).toEqual(NONE);
    }
  });

  it("an own k that is the empty string is still a kit link, an unreadable one", () => {
    const taken = takeKitFromLocation(makeWindow(BASE, { k: "" }));
    expect(taken).toEqual({ payload: "", source: "state", cleared: false });
    expect(decodeKit(taken.payload, GOOD_ITEMS).errors).toEqual([KIT_ERRORS.empty]);
  });

  it("finds no kit in a state that has no own k", () => {
    const inherited = Object.create({ k: GOOD });
    const arrayWithK = Object.assign([], { k: GOOD });
    for (const state of [null, undefined, "k", 42, true, [], [GOOD], arrayWithK, {}, { other: GOOD }, { K: GOOD }, inherited]) {
      expect(takeKitFromLocation(makeWindow(BASE, state))).toEqual(NONE);
    }
  });

  it("does not read a getter on the state, and finds no kit there", () => {
    let called = false;
    const state = { get k() { called = true; return GOOD; } };
    expect(takeKitFromLocation(makeWindow(BASE, state))).toEqual(NONE);
    expect(called).toBe(false);
  });

  it("keeps at most 2,049 characters, so a huge fragment never fills history.state", () => {
    const win = makeWindow(`${BASE}#k=${"A".repeat(1_000_000)}`);
    const taken = takeKitFromLocation(win);
    expect(taken.source).toBe("fragment");
    expect(taken.cleared).toBe(true);
    expect(taken.payload).toHaveLength(2049);
    expect(win.history.state.k).toHaveLength(2049);
    expect(decodeKit(taken.payload, GOOD_ITEMS).errors).toEqual([KIT_ERRORS.tooLong]);
    const stored = takeKitFromLocation(reloaded(win));
    expect(stored.payload).toHaveLength(2049);
    const oversizedState = takeKitFromLocation(makeWindow(BASE, { k: "A".repeat(5_000_000) }));
    expect(oversizedState.payload).toHaveLength(2049);
  });

  it("keeps the path and the query whatever they look like, because it rebuilds the URL from href", () => {
    for (const base of [
      "https://example.test/",
      "https://example.test/trio/pal-mnk-ber/",
      "https://example.test//other.example/x?y=1",
      "https://example.test/a%20b/?q=%23",
      "https://example.test:8788/trio/pal-mnk-ber/?race=OGR&role=balanced&tier=4",
    ]) {
      const win = makeWindow(`${base}#k=${GOOD}`);
      const taken = takeKitFromLocation(win);
      expect(taken.cleared).toBe(true);
      expect(win.location.href).toBe(new URL(base).href);
      expect(win.location.hash).toBe("");
    }
  });

  describe("the rest of history.state", () => {
    // Takes a kit link on a page whose history.state starts as `state`; returns what replaceState was given.
    function takeWithState(state) {
      const win = makeWindow(`${BASE}#k=${GOOD}`, state);
      const taken = takeKitFromLocation(win);
      expect(taken).toEqual({ payload: GOOD, source: "fragment", cleared: true });
      expect(win.log.replaceState).toHaveLength(1);
      return { win, written: win.log.replaceState[0].state };
    }

    it("stays when the state is a plain object: the page's other keys are kept and only k is set", () => {
      const state = { scroll: 120, panel: "gear", nested: { list: [1, 2] } };
      const { win, written } = takeWithState(state);
      expect(written).toEqual({ scroll: 120, panel: "gear", nested: { list: [1, 2] }, k: GOOD });
      expect(win.history.state).toEqual(written);
      expect(state).toEqual({ scroll: 120, panel: "gear", nested: { list: [1, 2] } }); // the old object is left as it was
      expect(written).not.toBe(state);
    });

    it("replaces an older k and keeps the rest", () => {
      const { written } = takeWithState({ k: "OLDLINK", other: 1 });
      expect(written).toEqual({ k: GOOD, other: 1 });
    });

    it("replaces a k that is not text", () => {
      const { written } = takeWithState({ k: 42, other: 1 });
      expect(written).toEqual({ k: GOOD, other: 1 });
    });

    it("counts an object without a prototype as plain, and an empty one too", () => {
      const bare = Object.create(null);
      bare.panel = "gear";
      expect(takeWithState(bare).written).toEqual({ panel: "gear", k: GOOD });
      expect(takeWithState({}).written).toEqual({ k: GOOD });
    });

    it("is just { k } when the state is not a plain object", () => {
      class Panel {
        constructor() {
          this.open = true;
        }
      }
      const stamped = new Date(0);
      stamped.extra = 1;
      const states = [
        null, undefined, "text", 42, true, [], [1, 2], Object.assign([], { extra: 1 }), stamped, new Map([["a", 1]]),
        new Set([1]), new Panel(), new Uint8Array(3), Object.assign(Object.create({ inherited: 1 }), { own: 2 }), /re/,
      ];
      for (const state of states) {
        const { written } = takeWithState(state);
        expect(Object.keys(written)).toEqual(["k"]);
        expect(written.k).toBe(GOOD);
      }
    });

    it("does not let an own __proto__ key of the old state change a prototype", () => {
      const state = JSON.parse('{"__proto__": {"polluted": true}, "keep": 1}');
      expect(Object.getPrototypeOf(state)).toBe(Object.prototype); // the parser made it an ordinary own key
      const { written } = takeWithState(state);
      expect(Object.getPrototypeOf(written)).toBe(Object.prototype);
      expect(written.polluted).toBeUndefined();
      expect({}.polluted).toBeUndefined();
      expect(written.keep).toBe(1);
      expect(written.k).toBe(GOOD);
    });

    it("keeps the other keys across a reload, and the kit with them", () => {
      const first = makeWindow(`${BASE}#k=${GOOD}`, { scroll: 120 });
      takeKitFromLocation(first);
      const taken = takeKitFromLocation(reloaded(first));
      expect(taken).toEqual({ payload: GOOD, source: "state", cleared: false });
      expect(reloaded(first).history.state).toEqual({ scroll: 120, k: GOOD });
    });

    it("still clears the fragment, with just { k }, when history.state cannot be read", () => {
      const win = makeWindow(`${BASE}#k=${GOOD}`);
      Object.defineProperty(win.history, "state", {
        get() {
          throw new Error("SecurityError");
        },
      });
      expect(takeKitFromLocation(win)).toEqual({ payload: GOOD, source: "fragment", cleared: true });
      expect(win.log.replaceState[0].state).toEqual({ k: GOOD });
      expect(win.location.hash).toBe("");
    });
  });

  describe("the forms a fragment can take", () => {
    const kitForms = [
      ["#k=", ""],
      ["#k", ""],
      ["#k=!!!", "!!!"],
      [`#k=${GOOD}&k=zzzz`, `${GOOD}&k=zzzz`],
      [`#k=${GOOD}#k=${GOOD}`, `${GOOD}#k=${GOOD}`],
      [`#k=${GOOD}%`, `${GOOD}%`],
    ];
    for (const [hash, payload] of kitForms) {
      it(`${hash.length > 40 ? `${hash.slice(0, 40)}...` : hash} is a kit link: one replaceState, the fragment gone, and the decode (not this function) says whether it can be read`, () => {
        const win = makeWindow(`${BASE}${hash}`);
        const taken = takeKitFromLocation(win);
        expect(taken).toEqual({ payload, source: "fragment", cleared: true });
        expect(win.log.replaceState).toHaveLength(1);
        expect(win.location.hash).toBe("");
        expect(win.history.state).toEqual({ k: payload });
        expect(win.log.navigation).toEqual([]);
        const decoded = decodeKit(taken.payload, GOOD_ITEMS);
        expect(decoded.kit).toBeNull();
        expect(decoded.errors).toHaveLength(1);
      });
    }

    it("garbage with characters the URL parser escapes still ends in a failed decode", () => {
      const win = makeWindow(`${BASE}#k=garbage!@#<>"\``);
      const taken = takeKitFromLocation(win);
      expect(taken.source).toBe("fragment");
      expect(win.location.hash).toBe("");
      expect(decodeKit(taken.payload, GOOD_ITEMS).errors).toHaveLength(1);
    });

    const ignoredForms = [
      "",
      "#",
      "#section",
      "#main",
      `#a=1&k=${GOOD}`,
      `#K=${GOOD}`,
      `#key=${GOOD}`,
      `#kit=${GOOD}`,
      "#k2",
      `#k%3D${GOOD}`,
      `# k=${GOOD}`,
      `#!k=${GOOD}`,
      `#/k=${GOOD}`,
      `#x#k=${GOOD}`,
      `#section&#k=${GOOD}`,
      `#?#k=${GOOD}`,
    ];
    for (const hash of ignoredForms) {
      it(`${JSON.stringify(hash.length > 40 ? `${hash.slice(0, 40)}...` : hash)} is not a kit link: left alone`, () => {
        const win = makeWindow(`${BASE}${hash}`);
        const href = win.location.href;
        expect(takeKitFromLocation(win)).toEqual(NONE);
        expect(win.log.replaceState).toEqual([]);
        expect(win.location.href).toBe(href);
        expect(win.history.state).toBeNull();
      });
    }

    it("no form causes navigation or a request", () => {
      const fetchSpy = vi.fn();
      vi.stubGlobal("fetch", fetchSpy);
      for (const hash of [...kitForms.map(([h]) => h), ...ignoredForms]) {
        const win = makeWindow(`${BASE}${hash}`);
        takeKitFromLocation(win);
        takeKitFromLocation(reloaded(win));
        expect(win.log.navigation).toEqual([]);
      }
      expect(fetchSpy).not.toHaveBeenCalled();
    });
  });

  it("reports that the fragment is still there when replaceState throws, and does not throw itself", () => {
    const win = makeWindow(`${BASE}#k=${GOOD}`);
    win.history.replaceState = () => {
      throw new Error("blocked");
    };
    const taken = takeKitFromLocation(win);
    expect(taken).toEqual({ payload: GOOD, source: "fragment", cleared: false });
    expect(win.location.hash).toBe(`#k=${GOOD}`);
  });

  it("reports that the fragment is still there when replaceState does nothing", () => {
    const win = makeWindow(`${BASE}#k=${GOOD}`);
    win.history.replaceState = () => {};
    expect(takeKitFromLocation(win)).toEqual({ payload: GOOD, source: "fragment", cleared: false });
  });

  it("works with a location and no history (the fragment cannot be cleared)", () => {
    const win = makeWindow(`${BASE}#k=${GOOD}`);
    expect(takeKitFromLocation({ location: win.location })).toEqual({ payload: GOOD, source: "fragment", cleared: false });
  });

  it("does not throw when history.state does", () => {
    const win = makeWindow(BASE);
    Object.defineProperty(win.history, "state", { get() { throw new Error("SecurityError"); } });
    expect(takeKitFromLocation(win)).toEqual(NONE);
  });

  it("does nothing, and does not throw, with no location or history at all", () => {
    expect(takeKitFromLocation()).toEqual(NONE);
    expect(takeKitFromLocation({})).toEqual(NONE);
    expect(takeKitFromLocation(null)).toEqual(NONE);
    expect(takeKitFromLocation({ location: null, history: null })).toEqual(NONE);
    expect(takeKitFromLocation({ location: { hash: 5 }, history: {} })).toEqual(NONE);
  });

  it("uses the page's own location and history when none are passed", () => {
    const win = makeWindow(`${BASE}#k=${GOOD}`);
    vi.stubGlobal("location", win.location);
    vi.stubGlobal("history", win.history);
    expect(takeKitFromLocation()).toEqual({ payload: GOOD, source: "fragment", cleared: true });
    expect(win.log.replaceState).toHaveLength(1);
    expect(takeKitFromLocation()).toEqual({ payload: GOOD, source: "state", cleared: false });
  });
});

// ---- what this module adds to the moved tests: its constants and its source ----

describe("the constants", () => {
  it("name the state key and the longest payload, and the longest agrees with the codec's", async () => {
    const location = await import("../pipeline/trioforge/site/static/input/kitlocation.js");
    const codec = await import("../pipeline/trioforge/site/static/input/kitcode.js");
    expect(location.STATE_KEY).toBe("k");
    expect(location.MAX_FRAGMENT_LENGTH).toBe(2048);
    expect(location.MAX_FRAGMENT_LENGTH).toBe(codec.MAX_FRAGMENT_LENGTH); // (this file may not import the codec, so the number is written in both places)
  });
});

describe("the module source", () => {
  const source = readFileSync(MODULE_URL, "utf8");
  // Comments out, so a sentence in a comment cannot trip a check. (The module holds no "//" inside a string.)
  const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");

  it("imports nothing, so that the page script carries this function and not the codec", () => {
    expect(code).not.toMatch(/\bimport\b|\brequire\b|\bexport\s+\*|\bexport\s*\{[^}]*\}\s*from\b/);
  });

  it("uses no regular expression, no percent-decoding, no evaluation and nothing that makes markup", () => {
    expect(code).not.toMatch(/RegExp|\.exec\(|\.match\(|\.matchAll\(|\.search\(|\.replace\(|\.replaceAll\(|\.test\(|\.split\(\s*\//);
    expect(code).not.toMatch(/decodeURI|decodeURIComponent|unescape|\beval\b|new\s+Function|innerHTML|outerHTML|insertAdjacentHTML|document\.write/);
  });

  it("starts no request and no navigation, and reads no storage", () => {
    expect(code).not.toMatch(/\bfetch\b|XMLHttpRequest|sendBeacon|location\.(assign|replace|reload|href\s*=)|window\.open|WebSocket|Worker|localStorage|sessionStorage|indexedDB/);
  });

  it("uses nothing that Safari 15.0 lacks", () => {
    expect(code).not.toMatch(/Object\.hasOwn\b|\.findLast\(|\.findLastIndex\(|\.at\(|structuredClone\(/);
  });

  it("exports ES module names only, with no side effect at import", () => {
    expect(code).not.toMatch(/export\s+default/);
    expect(source).toMatch(/^export /m);
  });

  it("is small: the first load carries it, so a function added here is a function every page pays for", () => {
    expect(code.replace(/\s+/g, " ").length).toBeLessThan(2600);
  });
});
