/**
 * The page's side of a kit link: takes a shared kit out of the page's address, before any other script can read it. This is the one piece of the kit link that the first load
 * carries; the codec (input/kitcode.js: the format, the tables, encodeKit; input/kitdecode.js: decodeKit) is code of the Upgrade section and is loaded with it, so this file imports nothing and the build refuses
 * a page script that holds the codec (pipeline/trioforge/site/build.py, check_page_script).
 *
 * The page flow, from the page script's side (the rest of it is in the header of input/kitcode.js):
 *   1. The page script runs `takeKitFromLocation()` first. A `#k=` payload goes into `history.state` (which survives a reload) and the fragment is removed from the address.
 *   2. The result is kept in one place for the analytics of a later phase: the page script writes `document.documentElement.dataset.kitFragment` ("cleared" when the fragment was
 *      taken out of the address before any other script ran, "kept" when it is still there; absent when the address had no kit fragment). See app.js.
 *   3. The page hands the payload to the code of the Upgrade section, which decodes it once the item table is in.
 */

/** The key of the payload in `history.state`. */
export const STATE_KEY = "k";
/** The longest payload the codec reads (input/kitcode.js has the same number: this file imports nothing, and a test holds the two equal). */
export const MAX_FRAGMENT_LENGTH = 2048;

const HASH_PREFIX = "#k=";
const HASH_BARE = "#k";

// ---- the page's address ----

function hashOf(location) {
  try {
    const hash = location === undefined || location === null ? "" : location.hash;
    return typeof hash === "string" ? hash : "";
  } catch {
    return "";
  }
}

// "#k=..." and the bare "#k" are kit links; every other fragment belongs to someone else.
const isKitHash = (hash) => hash === HASH_BARE || hash.startsWith(HASH_PREFIX);

// An ordinary object: one with no prototype, or whose prototype has none (Object.prototype, of any realm).
// An array, a Date, a Map or an instance of a class is not.
function isPlainObject(value) {
  if (value === null || typeof value !== "object") return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === null || Object.getPrototypeOf(prototype) === null;
}

// The state to store with a kit: the page's other keys stay when its current history.state is a plain object
// (a shallow copy; own keys only, and an own "__proto__" stays an ordinary key), and k is set. Any other
// state, or one that cannot be read, is replaced by { k }.
function stateWith(history, payload) {
  let current = null;
  try {
    current = history.state;
  } catch {
    current = null;
  }
  return isPlainObject(current) ? { ...current, [STATE_KEY]: payload } : { [STATE_KEY]: payload };
}

// One replaceState call keeps the payload in history.state and drops the fragment from the URL (the path and
// the query stay: the URL is rebuilt from href, which is absolute). True only if the fragment is really gone.
function storeAndClear(location, history, payload) {
  try {
    const href = location.href;
    if (typeof href !== "string" || history === undefined || history === null || typeof history.replaceState !== "function") {
      return false;
    }
    const cut = href.indexOf("#");
    history.replaceState(stateWith(history, payload), "", cut === -1 ? href : href.slice(0, cut));
    return !isKitHash(hashOf(location));
  } catch {
    return false;
  }
}

// The payload a reload finds in history.state, or null. Only an own data property named k that holds text counts:
// an inherited k, a getter, or any other kind of value is not a kit link, so the page just shows its default.
function storedPayload(history) {
  try {
    const state = history === undefined || history === null ? null : history.state;
    if (state === null || typeof state !== "object" || Array.isArray(state)) return null;
    const own = Object.getOwnPropertyDescriptor(state, STATE_KEY);
    if (own === undefined || typeof own.value !== "string") return null;
    return own.value.slice(0, MAX_FRAGMENT_LENGTH + 1);
  } catch {
    return null;
  }
}

/**
 * Takes a shared kit out of the page's address. Run it first in the page module, so the URL is clean
 * before any other script (the analytics beacon) can read it. Never throws, navigates or requests anything.
 *
 * - A `#k=` fragment: the payload goes into `history.state` and the fragment is removed, in one
 *   `history.replaceState`. The state keeps its other keys when it is a plain object (otherwise it
 *   becomes `{k: payload}`). At most 2,049 characters of the payload are kept; the decode then calls
 *   an over-long payload too long. The payload is NOT checked here: `decodeKit` does that, once the
 *   item table has loaded. `#k` alone is a kit link with an empty payload.
 * - No kit fragment but a payload in `history.state` (a reload): the text under its own `k` is returned
 *   again. A state without such text (no `k`, an inherited one, a getter, a number, an object...) holds no kit.
 * - Anything else, including every other fragment, is left alone.
 *
 * @param {{location?: Location, history?: History}} [env] defaults to the page's own `location` and `history`
 * @returns {{payload: string | null, source: "fragment" | "state" | null, cleared: boolean}} `cleared` is true
 *   when a kit fragment was found and is now gone from the URL. Source "fragment" with `cleared` false
 *   means it is still in the URL.
 */
export function takeKitFromLocation(env) {
  const hasEnv = env !== undefined && env !== null;
  const location = hasEnv && env.location !== undefined ? env.location : globalThis.location;
  const history = hasEnv && env.history !== undefined ? env.history : globalThis.history;
  const hash = hashOf(location);
  if (isKitHash(hash)) {
    const payload = hash.slice(HASH_PREFIX.length, HASH_PREFIX.length + MAX_FRAGMENT_LENGTH + 1);
    return { payload, source: "fragment", cleared: storeAndClear(location, history, payload) };
  }
  const stored = storedPayload(history);
  if (stored !== null) return { payload: stored, source: "state", cleared: false };
  return { payload: null, source: null, cleared: false };
}
