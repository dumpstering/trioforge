// The page counter (Cloudflare Web Analytics): a script that the page script adds, and nothing else does.
//
// The build gives a page the token as inert data, a <meta name="trioforge-counter" content="TOKEN"> in the head (no script of any kind is in the HTML), and only in a build that was given a token. The
// page script calls `addCounter` last, once the page has been started, and it adds ONE script element for the counter, through the site's one Trusted Types policy (tt-record.js lets exactly that
// address through for it), when ALL of these hold:
//
//   * the page was opened with no kit link: `kit` (the result of first.js's take) has no payload and no source, so the address had no kit fragment and the history entry holds no kit (a reload of a
//     page that was opened from a kit link finds its kit in `history.state`, and is a kit page still: it is not counted), and `data-kit-fragment` is not set.
//     The navigation entry of the Performance API keeps the address a document was loaded with, whatever the page script does to the address, so a page that was opened from a kit link cannot be
//     counted without the kit going with it: it is not counted at all, and the counter script is not loaded there;
//   * the address the document was LOADED with may be counted, and so may the current one (`loaded`, which first.js keeps in a constant before anything else runs and app.js hands to `addCounter`; with
//     no copy the page is not counted). The page code rewrites the address at start-up (trio.js keeps only the page's own switches when one is malformed, with history.replaceState), so a link such as
//     `/trio/x/?race=zzz&utm_source=x`, or one with a kit spelled `?k=<payload>`, looks clean by the time the counter is added: only the loaded address shows what was opened. The navigation entry of the
//     Performance API, where there is one, is a second witness (it keeps the address a document was loaded with, whatever the page script does to the address). The address is judged by
//     `mayBeCounted`, ONE function: no spelling of a kit in its fragment or its query (`holdsAKit`: the fragment and the query, percent-decoded until they stop changing (at most eight rounds: one that is still changing after that, and an address whose query and fragment
//     are longer than 4,096 characters, are not known to be clean) and lower-cased, are not `k` and have no `k=` in them, and no part of the query between `&` or `;` is named k), AND the query is empty or every key of it is one of the site's own switches
//     (SITE_QUERY_KEYS), each with a value of the shape the page takes for it (SITE_QUERY_SHAPES: a kit code is no value of a switch), AND the fragment is empty, the id of an element of the page, or one of the anchors of the site that are no element ids (SITE_ANCHORS). A fragment that the page does not
//     know, and a query with anything in it that is not the site's own, is not known to be clean, so the page is not counted. That includes a link that another site added a parameter to (utm_source
//     and the like): such a page is not counted (the About page says so);
//   * no entry of the tab's history that the page can see is one the page would not be counted with (`navigation.entries()` where the Navigation API exists: a kit page whose script did not run, or
//     whose fragment could not be cleared, stays in the session history with its kit in the entry's address, and a clean page that the visitor goes on to would otherwise be counted with that entry
//     within the reach of a script). An entry is held to the same function (`entryMayStay`), but for the fragment: the ids of ANOTHER page are not known here, so its fragment is only held to holding
//     no kit. Where the API does not exist (Firefox, Safari) this cannot be asked, and the behaviour is as it was without it: a stated limit (docs/DECISIONS.md, Part P);
//   * the page is not the 404 page (which does not run the page script at all, and has no token in it);
//   * the page carries a token, and it is 32 lower-case hex characters;
//   * the counter was not added to this page before (a restored page, a hashchange or a repaint adds nothing).
//
// A page whose script fails before this point is not counted either: nothing here runs. The script is given the setting `"spa": false`, which keeps it from following the history of the
// page (a kit link pasted into an open page is taken out of the address by first.js, at popstate already, and the page is loaded again to show it).

import { COUNTER_SCRIPT, getCounterPolicy } from "./tt-record.js";

/** The name of the <meta> element the build puts the token in. */
export const COUNTER_META = "trioforge-counter";

/**
 * The fragments that the site links to and that are no id of an element: the home page reads `#search` as a command (picker.js, SEARCH_HASH; notfound.js links to it) and puts the cursor in the search
 * box. Every other fragment of a link of the site is the id of an element of a page (the rules page has the id of each rule; a test reads the templates and the page code and holds this list to it).
 */
export const SITE_ANCHORS = Object.freeze(["search"]);

/**
 * The query keys that the site's own pages write and read, in ONE place: the switches of a trio page (trio.js: race, role, tier, setup, buffs, haste for the haste of the spells, w for the sliders and p
 * for the priorities). A page is counted only with an empty query or a query that has these keys and no other; a test reads trio.js and holds this list to the keys it uses. (`ev`, which addresses
 * written before there was one evidence level carry, is read by nothing and is not here: such an address is not counted.)
 */
export const SITE_QUERY_KEYS = Object.freeze(["race", "role", "tier", "setup", "buffs", "haste", "w", "p"]);

/**
 * The shape of the value of each of those keys, the one the page code takes for it (trio.js parseQuery: a race is the three capitals of a race code, a role and a weapon setup are words of lower-case letters,
 * digits and dashes, a tier is one or two digits, the buffs are a word or two (`group enchanter` is the older spelling with a plus read as a space), the haste is `1`, the sliders `w` are the characters
 * of POSITIONS and the priorities `p` the characters of the steps of priorities.js). A value of another shape is no value the site writes, whatever it holds: a kit code in `?w=` is one, so the page is not
 * counted. A test holds this table to trio.js and the baked page. The keys of SITE_QUERY_KEYS are the keys of this table.
 */
export const SITE_QUERY_SHAPES = Object.freeze({
  race: /^[A-Z]{3}$/,
  role: /^[a-z]{1,16}$/,
  tier: /^\d{1,2}$/,
  setup: /^[a-z0-9]{1,8}(?:-[a-z0-9]{1,8})?$/,
  buffs: /^[a-z]{1,16}(?: [a-z]{1,16})?$/,
  haste: /^1$/,
  // (these two are built from text: written as literals, the minified script reads `w:/` and `p:/`, which the release check for a path of the maintainer's computer takes for a drive letter)
  w: new RegExp("^[h12]{1,32}$"),
  p: new RegExp("^[0lnht]{1,16}$"),
});

/** The most rounds of percent-decoding that are made, and the most text (query and fragment together) that is looked at: no link of the site comes near either. */
const MOST_ROUNDS = 8;
const MOST_ADDRESS_TEXT = 4096;

const TOKEN = /^[0-9a-f]{32}$/;
let added = false;

/** The token the build gave the page, or null when there is none or it is not 32 lower-case hex characters. */
export function counterToken(doc) {
  const meta = doc.querySelector(`meta[name="${COUNTER_META}"]`);
  const value = meta === null ? null : meta.getAttribute("content");
  return typeof value === "string" && TOKEN.test(value) ? value : null;
}

/**
 * `text` percent-decoded until it stops changing, at most MOST_ROUNDS times (an encoding eight levels deep is read); text that is not valid percent-encoding is kept as it is. `null` when it is still
 * changing after the last round: something that nests deeper than any link does is not known to be clean (and an input that nests for thousands of levels does not cost thousands of rounds).
 */
function decoded(text) {
  let current = text;
  for (let round = 0; round <= MOST_ROUNDS; round += 1) {
    let next;
    try {
      next = decodeURIComponent(current);
    } catch {
      return current;
    }
    if (next === current) return current;
    current = next;
  }
  return null;
}

/**
 * Whether an address holds a kit in any spelling: its fragment, percent-decoded (however many times it is encoded) and lower-cased, is `k` or has `k=` anywhere in it (`#k=P`, `#K=P`, `#%6B=P`, `#k%3DP`,
 * `#x&k=P`, `#/k=P`, `# k=P`, `#k%2525253DP`), or its query, decoded the same way, has a part between `&` or `;` that is `k` or begins with `k=` (`?k=P`, `?K=P`, `?%6B=P`, `?k%3DP`, `?x=1;k=P`, `?+k=P`),
 * or a query parameter is named k in any case. An address that cannot be read (not text, not an address) is taken to hold one: nothing is counted that is not known to be clean.
 * The site's own take (input/kitlocation.js) reads `#k=` and `#k` only; the other spellings show no kit to a visitor, and the payload in them is a kit code all the same.
 */
export function holdsAKit(address) {
  let parsed;
  try {
    parsed = new URL(String(address));
  } catch {
    return true;
  }
  if (parsed.search.length + parsed.hash.length > MOST_ADDRESS_TEXT) return true; // (longer than any link of the site: not looked at, and not counted)
  const hashText = decoded(parsed.hash.slice(1));
  const searchText = decoded(parsed.search.slice(1));
  if (hashText === null || searchText === null) return true; // (still changing after the last round of decoding)
  const hash = hashText.toLowerCase();
  if (hash === "k" || hash.includes("k=")) return true;
  for (const part of searchText.split(/[&;]/)) {
    const name = part.replaceAll("+", " ").trim().toLowerCase();
    if (name === "k" || name.startsWith("k=")) return true;
  }
  for (const key of parsed.searchParams.keys()) {
    const spelled = decoded(key);
    if (spelled === null || spelled.trim().toLowerCase() === "k") return true;
  }
  return false;
}

/**
 * Whether the query of an address is empty or has only the site's own keys (SITE_QUERY_KEYS: exactly as spelled, in lower case, once decoded as a query is), each with a value of the shape that the page
 * code takes for it (SITE_QUERY_SHAPES: words, digits and letters, never an `=`, `&`, `;` or `%`: a value that has one is a second parameter, or a kit code, spelled inside the first).
 */
function queryIsTheSites(parsed) {
  if (parsed.search === "" || parsed.search === "?") return true;
  for (const [key, value] of parsed.searchParams) {
    if (!SITE_QUERY_KEYS.includes(key) || !SITE_QUERY_SHAPES[key].test(value)) return false;
  }
  return true;
}

/**
 * Whether the address of this page may be counted (`doc` is the page's own document): no kit in any spelling (`holdsAKit`), a query that is empty or has only the site's own keys (SITE_QUERY_KEYS), and
 * a fragment that is empty, the id of an element of the page (the site's own anchors, which are in the page when the counter is added: the page is parsed by then) or one of SITE_ANCHORS. Anything else
 * is not known to be clean.
 */
export function mayBeCounted(address, doc) {
  if (holdsAKit(address)) return false;
  const parsed = new URL(String(address));
  if (!queryIsTheSites(parsed)) return false;
  const fragment = decoded(parsed.hash.slice(1));
  if (fragment === null) return false;
  if (fragment === "") return true;
  return SITE_ANCHORS.includes(fragment) || doc.getElementById(fragment) !== null;
}

/** The Performance API's navigation entry is the second witness of the loaded address, where the browser has one: false when the address it holds may not be counted (no entry, or none that can be read, is no objection). */
function navigationEntryMayBeCounted(win, doc) {
  try {
    const entries = win.performance.getEntriesByType("navigation");
    const name = Array.isArray(entries) && entries.length > 0 ? entries[0].name : null;
    return typeof name !== "string" || mayBeCounted(name, doc);
  } catch {
    return true;
  }
}

/** Whether an entry of the tab's history may stay (`mayBeCounted`, but for the fragment: the ids of another page are not the ones of this document, so an entry's fragment is only held to holding no kit). */
function entryMayStay(address) {
  if (holdsAKit(address)) return false;
  return queryIsTheSites(new URL(String(address)));
}

/** Whether an entry of the tab's history that the page can see is one the page would not be counted with (false where the Navigation API does not exist). An error of any kind says yes: nothing is added on a guess. */
function historyHoldsAKit(win) {
  try {
    const navigation = win.navigation;
    if (navigation === undefined || navigation === null || typeof navigation.entries !== "function") return false;
    const entries = navigation.entries();
    if (!Array.isArray(entries)) return true;
    return entries.some((entry) => entry.url !== null && !entryMayStay(entry.url)); // (an entry with no address is not of this origin: a kit link of this site is never one)
  } catch {
    return true;
  }
}

/**
 * Add the counter to the page when all the conditions in the header hold. `env.document` and `env.window` are the page's own, `env.kit` the result of first.js's take, `env.trustedTypes` the window's
 * (`window.trustedTypes`; none in a browser without it). Returns whether it was added; throws the browser's error when the policy cannot be made (and adds nothing).
 */
export function addCounter({ document: doc, window: win, kit, loaded, trustedTypes }) {
  if (added) return false;
  const main = doc.getElementById("main");
  if (main !== null && main.dataset.page === "notfound") return false;
  const token = counterToken(doc);
  if (token === null) return false;
  if (kit === undefined || kit === null || kit.payload !== null || kit.source !== null) return false;
  if (doc.documentElement.dataset.kitFragment !== undefined || !mayBeCounted(win.location.href, doc)) return false;
  if (typeof loaded !== "string" || loaded === "" || !mayBeCounted(loaded, doc)) return false; // (the address as it was when the page was opened: see the header)
  if (!navigationEntryMayBeCounted(win, doc)) return false;
  if (historyHoldsAKit(win)) return false;
  if (doc.querySelector("script[data-cf-beacon]") !== null) return false;
  const policy = getCounterPolicy(trustedTypes);
  const script = doc.createElement("script"); // (a classic script, not a module: docs/DECISIONS.md, R7 says why, and what to change if the real script needs the module form)
  script.setAttribute("data-cf-beacon", JSON.stringify({ token, spa: false }));
  script.src = policy.scriptURL(COUNTER_SCRIPT);
  added = true;
  (doc.body ?? doc.documentElement).append(script);
  return true;
}
