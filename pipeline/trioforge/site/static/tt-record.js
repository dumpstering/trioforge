// The record of the one Trusted Types policy of the site, named "trioforge": who may be given a trusted script address, and the one way to make the policy once for the page.
//
// This file imports nothing, because the page script carries it (the page counter, counter.js, asks it for the counter's address) and the page script may import no file that the code loaded on first
// use shares (the build refuses it: check_page_script); tt-policy.js, which the optimizer's client uses, adds the check of the optimizer's own paths against the manifest's patterns.
//
// The site's policy header (require-trusted-types-for 'script') makes the browser refuse a plain string wherever it would start a
// script: that includes the address of a Worker and the address of a script that the page adds. Its trusted-types directive names this policy and no other (no 'default', no second name,
// no duplicates), so that nothing else on the page can make a policy that lets plain strings through.
//
// The policy hands out a trusted address for two things and for nothing else: the paths the build's manifest lists for the optimizer (hashed files under /assets/engine/: the page starts exactly
// one such worker, the optimizer's), and the one address of the page counter's script (counter.js adds it, to a page opened with no kit link, in a build that was given a token for it). It has
// no rule for markup or for script text, so those stay refused.
//
// The page script and the optimizer's client are two bundles, and each carries its own copy of this module; a name may be made once per page, so the policy is made by the copy that is evaluated first
// (the page script's: see "claimed" below) and its record is found by the other under a property of the page's window named "trioforge.tt-policy", by the Trusted Types object it was made on.
//
// WHAT IS GUARANTEED, and what is not. Any script of the page can find the record: two bundles have to, and a named property of the window is the one way they can. So the record is made so that it cannot be CHANGED
// from outside: what is under the name is a frozen object with one function, `get(trustedTypes)` (the records are in a closure, and there is no `set` to replace a record with), on a property that
// is not writable, not configurable and not enumerable (it cannot be redefined or deleted); a record is frozen (a method cannot be put over); the lists that its functions close over cannot be reached; and
// `allowCounter` takes the counter's address, refuses anything else, and enables nothing but the counter's address, whatever is done with it again. What a stranger CAN still do is what the site's own
// code does, and no more: list a path that has the shape of an optimizer file (a hashed file under /assets/engine/, which the manifest may never have named: it mints a trusted address for a file that
// is not there, and does not change what the optimizer was given), and ask for the counter's address to be enabled (which mints the one address that the policy was made to give the counter, for a script that
// already has the whole page).
//
// THE POLICY IS CLAIMED WHEN THIS FILE IS EVALUATED. The page script's module is evaluated as the page is read, and the last statement of this file takes the shared name and makes the record and the policy (on the window's
// `trustedTypes`: every page that runs the page script, in both builds, whether or not the counter or the optimizer will ever ask), so the first act of the site's own code with Trusted Types is the one that takes the policy
// name and the property: nothing that runs after the page script's module can take the policy name, put a hook on the factory's createPolicy that sees a policy made, or plant a record under the property. (Before, the record was
// made at first use, which on a kit page, on a page of a build with no token and on a page the counter refuses is the optimizer's first use, long after any other script.) A browser that will not make the policy (the header's
// trusted-types directive does not list the name) or has no Trusted Types does not stop the page script: the claim says nothing, and the counter or the optimizer gets the browser's error when it asks, as before.
//
// THE OPTIMIZER'S COPY IS EVALUATED LATE (its bundle loads on first use) and finds the record the way that no later script can change: it reads the property with plain property syntax, as the first thing it does, before it
// calls any function of the language (Symbol.for, Object.getOwnPropertyDescriptor, a WeakMap: each of those can be swapped by a script that runs between the page script and the optimizer's chunk, and a swapped one gave the late
// copy another script's record; the record used to be found under a symbol, by Symbol.for). The property is on `window` where the page has one, because a later script cannot shadow or redefine the name `window` (its property
// is not configurable, so a later `let window` is refused), where `globalThis` can be shadowed (`let globalThis = ...` in a later classic script is allowed, and every module after it reads the other object). A value
// under the name that is not the record (a named property of the window, which an element with that id would make, or one inherited) is not taken for it: the claim makes its own, as an own property, and what is read
// afterwards is that one.
//
// NOTHING ON THE WAY TO A MINTED ADDRESS GOES THROUGH A PROTOTYPE that another script can change once this file has loaded: the shape of an optimizer file is checked by comparing characters (an index, a
// length and `===`, no method of a string, no regular expression), the list of the optimizer's paths is an object with no prototype that is asked by key, the records are looked up in a closure by
// `===` (no WeakMap, no Set), and the few functions of the language that are needed are taken once, here, when the file loads. A script that runs AFTER this one and changes RegExp.prototype.test,
// Set.prototype.has, WeakMap.prototype.get, Symbol.for, an array's iterator, Object.prototype or a method of a string, a function or Object changes nothing that the policy hands out (tests-js/counter.test.mjs
// and tests-js/tt-claim.test.mjs replay the reviews' probes and more). So, against a script that runs after this one: nothing outside {a hashed engine path, the counter's address} can be minted by anyone, and the
// record that the page script made, which the counter and the optimizer's copy both use, cannot be replaced.
//
// WHAT A LATER SCRIPT CAN STILL DO is to DENY the optimizer its worker, never to widen what the policy mints: it can replace `window.trustedTypes` with a factory of its own before the optimizer's copy loads (the
// copy then makes a record on that object, whose policy gives back plain strings, which the browser refuses where a Worker would start), and it can change the array iterator that tt-policy.js lists the optimizer's
// paths through (the call then throws). Both leave the page, the counter and the real policy as they were, and neither gets a trusted address for anything but a listed hashed engine path and the counter's one address.
//
// WHAT REMAINS: a script that runs BEFORE the site's script (the head of the page, an extension, anything that is there first) can pre-empt the policy's name (the header allows it once: the site's own
// claim then fails), take the property's name and put its own record under it, or change the built-ins that this file takes when it loads. Nothing in the page can prevent that; the content security policy (script-src
// 'self' and the counter's host, nothing inline) is what limits what such a script can be. And a browser without Trusted Types (the API is detected, not assumed) has nothing to refuse, so the same
// check runs and the plain, checked path is returned instead.

export const POLICY_NAME = "trioforge";

/** The script of the page counter (Cloudflare Web Analytics): the one address outside the site that the policy lets through, and only for the counter's own way in (getCounterPolicy). */
export const COUNTER_SCRIPT = "https://static.cloudflareinsights.com/beacon.min.js";

// What the code below needs of the language, taken once, when the file loads (a later change of Object, or of a prototype, does not reach what is taken here; a call of a function that is held in a
// variable looks nothing up).
const create = Object.create;
const defineProperty = Object.defineProperty;
const freeze = Object.freeze;

/** The hashed files of the optimizer, as engine/manifest.js says them (a test holds the two to the same answers): /assets/engine/, one of these names, a dash, 8 to 32 capital letters or digits, and .js or .wasm. */
const ENGINE_PREFIX = "/assets/engine/";
const ENGINE_NAMES = ["client", "worker", "kitvalue", "highs"];
const ENGINE_KINDS = ["js", "wasm"];

/** The name under which the copies of this module share the record, and the object that holds it (see the header: `window` where there is one, which a later script cannot shadow; `globalThis` in a worker or a test). */
const KEY = "trioforge.tt-policy";
const ROOT = typeof window === "object" && window !== null ? window : globalThis;

/** Whether `text` holds `word` from position `at` (characters compared by index; the positions asked about are always inside the text). */
function holds(text, at, word) {
  if (at + word.length > text.length) return false;
  for (let i = 0; i < word.length; i += 1) {
    if (text[at + i] !== word[i]) return false;
  }
  return true;
}

function isHashCharacter(character) {
  return (character >= "A" && character <= "Z") || (character >= "0" && character <= "9");
}

/** Whether `path` is a hashed file of the optimizer: only the characters of the string are read, by index and length. */
function isEngineFile(path) {
  if (typeof path !== "string" || !holds(path, 0, ENGINE_PREFIX)) return false;
  let at = ENGINE_PREFIX.length;
  let named = false;
  for (let n = 0; n < ENGINE_NAMES.length; n += 1) {
    const name = ENGINE_NAMES[n];
    if (holds(path, at, name) && at + name.length < path.length && path[at + name.length] === "-") {
      at += name.length + 1;
      named = true;
      break;
    }
  }
  if (!named) return false;
  let digits = 0;
  while (at < path.length && isHashCharacter(path[at])) {
    at += 1;
    digits += 1;
  }
  if (digits < 8 || digits > 32 || at >= path.length || path[at] !== ".") return false;
  at += 1;
  for (let n = 0; n < ENGINE_KINDS.length; n += 1) {
    if (holds(path, at, ENGINE_KINDS[n]) && at + ENGINE_KINDS[n].length === path.length) return true;
  }
  return false;
}

/**
 * The records of the page, one for each Trusted Types object: shared by every copy of this module on the page, and made at most once. What is shared is a frozen object with the one function `get`, whose
 * records are in a closure of the copy that made it (that copy makes every record: the copies are the same code); the property is not writable, not configurable and not enumerable. The records are
 * two lists that are scanned by index and compared with `===` (a page has one Trusted Types object: the lists have one entry). A copy that comes late finds the record by the first two lines, which call nothing.
 */
function records() {
  const shared = ROOT[KEY];
  if (typeof shared === "object" && shared !== null && typeof shared.get === "function") return shared;
  const objects = [];
  const found = [];
  const get = (trustedTypes) => {
    for (let i = 0; i < objects.length; i += 1) {
      if (objects[i] === trustedTypes) return found[i];
    }
    const record = makeRecord(trustedTypes);
    objects[objects.length] = trustedTypes;
    found[found.length] = record;
    return record;
  };
  defineProperty(ROOT, KEY, { value: freeze({ get }) });
  return ROOT[KEY];
}

/** A record: the policy made on `trustedTypes` (none for a browser without Trusted Types) and the closures that list and mint. Throws the browser's error when it will not make the policy. */
function makeRecord(trustedTypes) {
  const engine = create(null); // (path -> true: an object with no prototype, so that no key is found that was not put there)
  let counter = false;
  const policy =
    trustedTypes === null
      ? null
      : trustedTypes.createPolicy(POLICY_NAME, {
          createScriptURL(input) {
            if (typeof input === "string" && ((isEngineFile(input) && engine[input] === true) || (counter && input === COUNTER_SCRIPT))) return input;
            throw new TypeError("This address is not one of the site's own script addresses.");
          },
        });
  const mint = (path) => (policy === null ? path : policy.createScriptURL(path));
  return freeze({
    listEngine(paths) {
      for (let i = 0; i < paths.length; i += 1) {
        const path = paths[i];
        if (!isEngineFile(path)) throw new TypeError("The optimizer's files are hashed files under /assets/engine/ and nothing else.");
        engine[path] = true;
      }
    },
    hasEngine: (path) => isEngineFile(path) && engine[path] === true,
    mintEngine(path) {
      if (!isEngineFile(path) || engine[path] !== true) throw new TypeError("This address is not one of the optimizer's files.");
      return mint(path);
    },
    allowCounter(address) {
      if (address !== COUNTER_SCRIPT) throw new TypeError("Only the counter's own address is enabled, and only by its own way in.");
      counter = true;
    },
    mintCounter() {
      if (!counter) throw new TypeError("The counter's address is not listed.");
      return mint(COUNTER_SCRIPT);
    },
  });
}

function recordFor(trustedTypes) {
  const available = typeof trustedTypes === "object" && trustedTypes !== null && typeof trustedTypes.createPolicy === "function";
  if (!available) return makeRecord(null);
  return records().get(trustedTypes);
}

/**
 * The policy for the given paths (each a hashed engine file). Returns `{name, scriptURL(path)}`: `scriptURL` returns a TrustedScriptURL for a
 * listed path (a plain string when the browser has no Trusted Types) and throws a TypeError for any other. Throws a TypeError for a
 * path that is not a hashed engine file, and lets the browser's error through if the browser will not make the policy. (tt-policy.js is the optimizer's way in, which checks the paths against the manifest's own patterns first.)
 */
export function getEnginePolicy(trustedTypes, paths) {
  const record = recordFor(trustedTypes);
  record.listEngine(paths); // (each path is read once and checked: a list that changes as it is read gets no more through)
  return {
    name: POLICY_NAME,
    scriptURL(path) {
      return record.mintEngine(path);
    },
  };
}

/**
 * The counter's way in: `{name, scriptURL(address)}`, which returns a TrustedScriptURL (a plain string when the browser has no Trusted Types) for `COUNTER_SCRIPT` and throws a TypeError for
 * any other string or value. Asking for it lists the address in the policy (the same one policy, whichever copy of this module makes it); the optimizer's way in does not give it out.
 */
export function getCounterPolicy(trustedTypes) {
  const record = recordFor(trustedTypes);
  record.allowCounter(COUNTER_SCRIPT);
  return {
    name: POLICY_NAME,
    scriptURL(address) {
      if (address !== COUNTER_SCRIPT) throw new TypeError("This address is not the counter's script.");
      return record.mintCounter();
    },
  };
}

// The claim (see the header): the record and the policy are made as this file is evaluated. It never throws: a browser that will not make the policy tells the counter or the optimizer when it asks.
try {
  records(); // (the shared name is taken first, whatever the browser has)
  recordFor(ROOT.trustedTypes);
} catch {
  // (nothing is stored: the same call, made again by a caller, makes the same attempt and lets the browser's error through)
}
