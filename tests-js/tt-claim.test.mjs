// @vitest-environment jsdom
//
// The site's Trusted Types policy is claimed when the page script's module is evaluated (Part R, R2). The record and the policy ("trioforge") used to be made at FIRST USE: the counter's call on a counted
// page, the optimizer's on any other, which on a kit page, on every page of a build with no token and on every page that is not counted is long after any other script. A script that ran in between
// could take the policy name, hook the factory's createPolicy, or plant the symbol under which the two bundles share the record. tt-record.js now makes the record and the policy at the end of its own
// evaluation (the page script's first act with Trusted Types), on every page and in both builds, so that what runs after it can take nothing; the one case that remains is a script that runs BEFORE the page
// script (the header of tt-record.js says so). This file is a file of its own because the record is made once per global object: here the page's Trusted Types object is in place before the module loads,
// as a browser has it. Every address here is invented.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { beforeAll, describe, expect, it, vi } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const STATIC = resolve(HERE, "../pipeline/trioforge/site/static");
const file = (name) => resolve(STATIC, name).replaceAll("\\", "/");
const KEY = "trioforge.tt-policy"; // (the property of the window under which the copies of tt-record.js share the record: a string, not a symbol, so that finding it calls nothing)
const WORKER = "/assets/engine/worker-ABCDEFGH.js";
const SCRIPT = "https://static.cloudflareinsights.com/beacon.min.js";
const EVIL = "https://evil.example/x.js";

class Minted {
  constructor(value) {
    this.value = value;
  }
  toString() {
    return this.value;
  }
}

/** A Trusted Types object like the browser's: a factory whose createPolicy is on a PROTOTYPE, a name made once, and the callback's result wrapped (the input is a string by then). */
function makeTrustedTypes() {
  const names = new Set();
  const created = [];
  class Factory {}
  Factory.prototype.createPolicy = function (name, rules) {
    if (names.has(name)) throw new TypeError(`Policy with name "${name}" already exists.`);
    names.add(name);
    created.push(name);
    return { name, createScriptURL: (input) => new Minted(String(rules.createScriptURL(String(input)))) };
  };
  return { trustedTypes: new Factory(), Factory, created };
}

/** Change `object[name]` while `run` goes (with Reflect, which none of these changes), and put it back. */
function under(object, name, replacement, run) {
  const own = Reflect.getOwnPropertyDescriptor(object, name);
  Reflect.defineProperty(object, name, { value: replacement, writable: true, configurable: true });
  try {
    return run();
  } finally {
    if (own) Reflect.defineProperty(object, name, own);
    else Reflect.deleteProperty(object, name);
  }
}

describe("the policy claimed at the page script's load", () => {
  const world = makeTrustedTypes();
  let record;
  let later;

  beforeAll(async () => {
    globalThis.trustedTypes = world.trustedTypes; // (the page's own, there before any script of the site)
    record = await import(file("tt-record.js")); // (the page script's module: it claims the policy as it is evaluated)
    vi.resetModules();
    later = await import(file("tt-policy.js")); // (the optimizer's bundle, another copy, loaded on first use)
  });

  it("has made the policy, once, before anything asked for it: on a page with no counter and no optimizer", () => {
    expect(world.created).toEqual(["trioforge"]);
    expect(Object.getOwnPropertyDescriptor(globalThis, KEY)).toMatchObject({ enumerable: false, writable: false, configurable: false });
    expect(typeof record.getCounterPolicy).toBe("function");
  });

  it("lets a script that runs after it take nothing: the name is taken (the review's lazy-name probe)", () => {
    expect(() => world.trustedTypes.createPolicy("trioforge", { createScriptURL: (input) => input })).toThrow(TypeError);
    const policy = later.getAssetPolicy(world.trustedTypes, [WORKER]); // (the optimizer, later: it finds the record, and gets its worker)
    expect(String(policy.scriptURL(WORKER).value)).toBe(WORKER);
    expect(() => policy.scriptURL(EVIL)).toThrow(TypeError);
  });

  it("lets a script that hooks createPolicy after it see nothing made under the site's name (the lazy-hook probe)", () => {
    let seen = 0;
    const real = world.Factory.prototype.createPolicy;
    under(world.Factory.prototype, "createPolicy", function (...args) {
      seen += 1;
      return real.apply(this, args);
    }, () => {
      const policy = later.getAssetPolicy(world.trustedTypes, [WORKER]);
      expect(String(policy.scriptURL(WORKER).value)).toBe(WORKER);
      record.getCounterPolicy(world.trustedTypes);
    });
    expect(seen, "no policy was made after the claim, so the hook was never called").toBe(0);
  });

  it("lets a script that plants the property after it plant nothing, and the optimizer is handed the real record (the lazy-symbol probe)", () => {
    const fake = Object.freeze({ listEngine() {}, hasEngine: () => true, mintEngine: (path) => path, allowCounter() {}, mintCounter: () => "x" });
    expect(() => Object.defineProperty(globalThis, KEY, { value: Object.freeze({ get: () => fake }) })).toThrow(TypeError);
    expect(globalThis[KEY].get(world.trustedTypes)).not.toBe(fake);
    const policy = later.getAssetPolicy(world.trustedTypes, [WORKER]);
    expect(policy.scriptURL(WORKER)).toBeInstanceOf(Minted); // (made by the site's own policy, not handed back as a plain string by a stranger's record)
    expect(() => policy.scriptURL(EVIL)).toThrow(TypeError);
  });

  it("lets a setter planted on the arrays' index 0 after it do no more than it could before: the optimizer still lists its worker and mints it (the array-setter probe)", () => {
    Reflect.defineProperty(Array.prototype, "0", { configurable: true, get: () => undefined, set() {} });
    try {
      const policy = later.getAssetPolicy(world.trustedTypes, [WORKER]);
      expect(String(policy.scriptURL(WORKER).value)).toBe(WORKER);
      expect(() => policy.scriptURL(EVIL)).toThrow(TypeError);
    } finally {
      Reflect.deleteProperty(Array.prototype, "0");
    }
  });

  it("lets a script that swaps Symbol.for after it hand the optimizer's late copy nothing: the late copy finds the record with no call of a function of the language (the review's symbol-for probe)", async () => {
    const real = globalThis[KEY].get(world.trustedTypes); // (any script can find the real record: conceded)
    real.allowCounter(SCRIPT); // (conceded: any script can enable the counter's address)
    let asked = 0;
    const forged = Object.freeze({
      listEngine() {},
      hasEngine: () => true,
      mintEngine: () => {
        asked += 1;
        return real.mintCounter(); // (the optimizer's worker address would become the counter's script, minted by the site's own policy)
      },
      allowCounter() {},
      mintCounter: () => real.mintCounter(),
    });
    const mine = Symbol("stranger");
    Reflect.defineProperty(globalThis, mine, { value: Object.freeze({ get: () => forged }), configurable: true });
    const realFor = Symbol.for;
    let loaded;
    vi.resetModules();
    Reflect.defineProperty(Symbol, "for", { value: (key) => (key === KEY ? mine : realFor(key)), writable: true, configurable: true });
    try {
      loaded = await import(file("tt-policy.js")); // (the optimizer's copy, loaded on first use, after the swap)
    } finally {
      Reflect.defineProperty(Symbol, "for", { value: realFor, writable: true, configurable: true });
    }
    try {
      const policy = loaded.getAssetPolicy(world.trustedTypes, [WORKER]);
      const got = policy.scriptURL(WORKER);
      expect(got, "made by the site's own policy").toBeInstanceOf(Minted);
      expect(String(got.value), "the worker's address, not the counter's").toBe(WORKER);
      expect(asked, "the stranger's record was never asked").toBe(0);
      expect(() => policy.scriptURL(EVIL)).toThrow(TypeError);
      expect(world.created).toEqual(["trioforge"]);
    } finally {
      Reflect.deleteProperty(globalThis, mine);
    }
  });

  it("lets a script that swaps the functions the old lookup called (Object.getOwnPropertyDescriptor, Symbol.for) before the optimizer's copy loads change nothing: the late copy is handed the real record", async () => {
    for (const [object, name, value] of [[Object, "getOwnPropertyDescriptor", () => undefined], [Symbol, "for", () => { throw new Error("stranger"); }]]) {
      const own = Reflect.getOwnPropertyDescriptor(object, name);
      let loaded;
      vi.resetModules();
      Reflect.defineProperty(object, name, { value, writable: true, configurable: true });
      try {
        loaded = await import(file("tt-policy.js"));
      } finally {
        Reflect.defineProperty(object, name, own);
      }
      const policy = loaded.getAssetPolicy(world.trustedTypes, [WORKER]);
      expect(policy.scriptURL(WORKER), name).toBeInstanceOf(Minted);
      expect(String(policy.scriptURL(WORKER).value), name).toBe(WORKER);
      expect(() => policy.scriptURL(EVIL), name).toThrow(TypeError);
    }
    expect(world.created).toEqual(["trioforge"]);
  });

  it("lets a script that replaces the page's Trusted Types object before the optimizer loads deny the optimizer its worker and nothing more: a plain address, which the browser refuses at a Worker (the review's replace-trustedTypes probe)", async () => {
    const fake = { createPolicy: (name, rules) => ({ createScriptURL: (input) => String(rules.createScriptURL(String(input))) }) };
    const saved = Reflect.getOwnPropertyDescriptor(globalThis, "trustedTypes");
    let loaded;
    vi.resetModules();
    Reflect.defineProperty(globalThis, "trustedTypes", { value: fake, writable: true, configurable: true });
    try {
      loaded = await import(file("tt-policy.js")); // (its own claim now meets the stranger's object: that is all it can make a record on)
    } finally {
      Reflect.defineProperty(globalThis, "trustedTypes", saved);
    }
    const policy = loaded.getAssetPolicy(fake, [WORKER]);
    const got = policy.scriptURL(WORKER);
    expect(got, "a plain string: not a trusted value").not.toBeInstanceOf(Minted);
    expect(typeof got).toBe("string");
    expect(() => policy.scriptURL(EVIL)).toThrow(TypeError);
    expect(() => policy.scriptURL(SCRIPT), "the counter's address is not the optimizer's to be given").toThrow(TypeError);
    const real = loaded.getAssetPolicy(world.trustedTypes, [WORKER]); // (the page's own object still has the one record and the one policy)
    expect(real.scriptURL(WORKER)).toBeInstanceOf(Minted);
    expect(world.created).toEqual(["trioforge"]);
  });

  it("lets a script that swaps the array iterator deny the optimizer's way in (tt-policy.js reads its list through it) and mint nothing: the record's own way in does not use it", () => {
    const own = Reflect.getOwnPropertyDescriptor(Array.prototype, Symbol.iterator);
    Reflect.defineProperty(Array.prototype, Symbol.iterator, {
      value: function* () {
        yield EVIL;
      },
      writable: true,
      configurable: true,
    });
    try {
      expect(() => later.getAssetPolicy(world.trustedTypes, [WORKER])).toThrow(TypeError);
      const direct = record.getEnginePolicy(world.trustedTypes, [WORKER]);
      expect(String(direct.scriptURL(WORKER).value)).toBe(WORKER);
      expect(() => direct.scriptURL(EVIL)).toThrow(TypeError);
    } finally {
      Reflect.defineProperty(Array.prototype, Symbol.iterator, own);
    }
  });

  it("gives the counter its address, and the optimizer its worker, and nothing else, after all of that", () => {
    const counter = record.getCounterPolicy(world.trustedTypes);
    expect(String(counter.scriptURL(SCRIPT).value)).toBe(SCRIPT);
    expect(() => counter.scriptURL(EVIL)).toThrow(TypeError);
    const optimizer = later.getAssetPolicy(world.trustedTypes, [WORKER]);
    expect(() => optimizer.scriptURL(SCRIPT), "the optimizer's way in does not give the counter's address, though the counter has been enabled by its own").toThrow(TypeError);
    expect(world.created).toEqual(["trioforge"]);
  });
});

describe("a page whose browser cannot make the policy, or has no Trusted Types", () => {
  it("does not throw as the page script's module is evaluated, and says what is wrong when the counter or the optimizer asks", async () => {
    vi.resetModules();
    const saved = Object.getOwnPropertyDescriptor(globalThis, "trustedTypes");
    try {
      globalThis.trustedTypes = {
        createPolicy() {
          throw new TypeError('Policy with name "trioforge" disallowed.');
        },
      };
      const record = await import(file("tt-record.js")); // (the claim fails: the page script must still load)
      expect(() => record.getCounterPolicy(globalThis.trustedTypes)).toThrow(/disallowed/);
      for (const none of [undefined, null, {}, { createPolicy: 5 }]) {
        globalThis.trustedTypes = none;
        vi.resetModules();
        const again = await import(file("tt-record.js")); // (no Trusted Types: nothing to claim, nothing thrown)
        expect(again.getCounterPolicy(none).scriptURL(SCRIPT)).toBe(SCRIPT);
      }
    } finally {
      if (saved) Object.defineProperty(globalThis, "trustedTypes", saved);
      else delete globalThis.trustedTypes;
    }
  });
});

describe("where the record is kept: the name `window`, and a value under the name that is not a record", () => {
  const source = readFileSync(resolve(STATIC, "tt-record.js"), "utf8").replace(/^export /gm, ""); // (as a classic script: its `export`s dropped)
  /** A fresh global object (a context of its own, in which `window` is the global object, as on a page), with `trustedTypes` on it and `before` run in it. */
  function page(trustedTypes, before) {
    const context = vm.createContext({});
    vm.runInContext("this.window = this;", context);
    context.trustedTypes = trustedTypes;
    if (before) vm.runInContext(before, context);
    return context;
  }
  /** A copy of the module, evaluated in `context` (as a bundle is): its functions. */
  const load = (context) => vm.runInContext(`(function () {
${source}
return { getCounterPolicy, getEnginePolicy };
})()`, context);
  const own = (context, where) =>
    vm.runInContext(`(function () { var d = Object.getOwnPropertyDescriptor(${where}, "${KEY}"); return d === undefined ? null : { writable: d.writable, configurable: d.configurable, enumerable: d.enumerable, get: typeof d.value.get }; })()`, context);

  it("keeps it on `window`, which a later script cannot shadow, and not on `globalThis`, which a later classic script can (`let globalThis = ...`): a copy that loads after the shadow finds the record", () => {
    const world = makeTrustedTypes();
    const context = page(world.trustedTypes);
    load(context); // (the page script's copy: it claims)
    expect(own(context, "window")).toEqual({ writable: false, configurable: false, enumerable: false, get: "function" });
    expect(world.created).toEqual(["trioforge"]);
    vm.runInContext("let globalThis = { trustedTypes: undefined };", context); // (a later script: every module evaluated after it reads `globalThis` as the stranger's object)
    expect(vm.runInContext("globalThis === this", context), "the shadow is in place").toBe(false);
    expect(vm.runInContext('Object.getOwnPropertyDescriptor(globalThis, "trioforge.tt-policy")', context), "the stranger's object holds no record").toBeUndefined();
    const late = load(context); // (the optimizer's copy, after the shadow)
    const policy = late.getEnginePolicy(world.trustedTypes, [WORKER]);
    expect(String(policy.scriptURL(WORKER).value)).toBe(WORKER);
    expect(world.created, "the late copy found the record that was there and made nothing").toEqual(["trioforge"]);
  });

  it("does not take a value under the name that is not a record for one (an element with that id is a named property of the window, and an object can be inherited): the claim makes its own, as an own property", () => {
    for (const planted of ["{ get: 5 }", "{}", '"x"', "null", "42"]) {
      const world = makeTrustedTypes();
      const context = page(world.trustedTypes, `Object.defineProperty(Object.prototype, "${KEY}", { value: ${planted}, configurable: true });`);
      const api = load(context);
      expect(own(context, "window"), planted).toEqual({ writable: false, configurable: false, enumerable: false, get: "function" });
      expect(world.created, planted).toEqual(["trioforge"]);
      expect(String(api.getCounterPolicy(world.trustedTypes).scriptURL(SCRIPT).value), planted).toBe(SCRIPT);
    }
  });
});
