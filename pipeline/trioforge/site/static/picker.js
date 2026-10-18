// The trio picker on the home page: choose three classes, with the chips or by typing them in the search box, and be taken to the page for that trio, or told that it is coming soon.
//
// The chips and the box say one thing in two ways. What is typed is read for the classes it names (`readQuery`) and the chips show them; a chip that is chosen is written into the box.
// The page of the trio is offered when the build made it (the list is `data-live` on the picker, the same list as the links under it), and a trio that is not built is said to be coming
// soon, in words, with no link. A link to a page of the site pasted into the box is not read for classes: if it is the page of a trio of the build (in any order of the classes) the link
// offered is that page with the query and the fragment of the pasted one, so that a shared kit is not lost, and any other address is told to be opened in the address bar. The status line
// is a live region, so it is replaced only when what it says changes. The picker is hidden in the page until this script runs: a visitor without it has the list of links.
// Written for ES2021 and Safari 15.

import { isSafeTarget, trioAddress } from "./canonical.js";

const WANTED = 3;
/** The most words that are named as no class in the status, and the most letters of one of them (what is typed is never echoed whole). */
const MOST_UNKNOWN = 3;
const LONGEST_WORD = 12;
/** The fragment of the address that asks for the cursor to be put in the search box (the 404 page links to it). */
const SEARCH_HASH = "#search";
/**
 * The most characters of what is typed that are read, and the `maxlength` of the box (home.html.j2; a test holds the two equal). A link to a shared kit has up to 2,048 characters of kit
 * (input/kitlocation.js) and about 150 of address, so it fits; a paste of megabytes is cut, and costs no more than the limit does.
 */
export const MAX_QUERY_LENGTH = 2500;

/** Words that only join the classes in what a visitor types ("paladin and monk") or lie in an address that was pasted ("/trio/pal-mnk-ber/"): they are passed over, and are no mistake. */
const CONNECTORS = ["and", "or", "plus", "the", "trio"];
/** What is typed that is an address and not classes: it has a scheme and two slashes, or two slashes, or it is a path in the folder of the trios. */
const ADDRESS = /^(?:[a-z][a-z0-9+.-]*:\/\/|\/\/|\/trio\/)/i;
const ADDRESS_TEXT = "This is an address, not classes. Open it in the address bar of your browser.";
const TOO_MANY_TEXT = "A trio has three classes: the first three are used.";

/** The words of a query: runs of the letters a to z, in lower case, of the first characters of it that are read. Anything else (spaces, commas, slashes, hyphens, digits, marks, letters of other alphabets) separates words. */
function wordsOf(query) {
  return typeof query === "string" ? query.slice(0, MAX_QUERY_LENGTH).split(/[^A-Za-z]+/).filter(Boolean).map((word) => word.toLowerCase()) : [];
}

/**
 * The classes a query names. `classes` are the classes of the site, `{code, name}` each ("PAL", "Paladin"; "SHD", "Shadow Knight"). A class is named by its code or by its name, in any
 * case, in any order, with anything between the words; a name of two words may be written as two, or as one. Returns the codes in the order they were named, each once (`codes`), the
 * words that name no class (`unknown`) and the unfinished end of the query (`partial`, "" if there is none): the last word when it begins a name or a joining word, or the last two words
 * when the first is the first word of a name of two words and the second begins its second ("shadow k"). `partialClass` says whether that end begins a class (and not a joining word).
 */
export function readQuery(query, classes) {
  const byWord = new Map(); // a code, a name of one word, or a name of two words written as one: "pal", "paladin", "shadowknight"
  const byPair = new Map(); // a name of two words: "shadow knight"
  const secondOf = new Map(); // the first word of a name of two words, and its second: "shadow", "knight"
  const begins = []; // what a word being typed may be the start of, besides a joining word
  for (const { code, name } of Array.isArray(classes) ? classes : []) {
    byWord.set(code.toLowerCase(), code);
    begins.push(code.toLowerCase());
    const parts = wordsOf(name);
    if (parts.length === 1) {
      byWord.set(parts[0], code);
    } else if (parts.length === 2) {
      byPair.set(parts.join(" "), code);
      byWord.set(parts.join(""), code);
      secondOf.set(parts[0], parts[1]);
    }
    if (parts.length > 0) begins.push(parts[0], parts.join(""));
  }
  const words = wordsOf(query);
  const codes = [];
  const unknown = [];
  let partial = "";
  let partialClass = false;
  for (let at = 0; at < words.length; at += 1) {
    const word = words[at];
    const pair = at + 1 < words.length ? byPair.get(word + " " + words[at + 1]) : undefined;
    const code = pair !== undefined ? pair : byWord.get(word);
    const last = at === words.length - 1;
    if (code !== undefined) {
      if (pair !== undefined) at += 1;
      if (!codes.includes(code)) codes.push(code);
    } else if (CONNECTORS.includes(word)) {
      continue;
    } else if (last && begins.some((key) => key.startsWith(word))) {
      partial = word;
      partialClass = true;
    } else if (last && CONNECTORS.some((joiner) => joiner.startsWith(word))) {
      partial = word;
    } else if (at === words.length - 2 && secondOf.has(word) && secondOf.get(word).startsWith(words[at + 1])) {
      partial = word + " " + words[at + 1];
      partialClass = true;
      at += 1;
    } else {
      unknown.push(word);
    }
  }
  return { codes, unknown, partial, partialClass };
}

/** What is said of the words of the query that name no class: at most three, each cut short. */
function unknownText(words) {
  const shown = words.slice(0, MOST_UNKNOWN).map((word) => word.slice(0, LONGEST_WORD));
  return (shown.length === 1 ? "Not a class: " : "Not classes: ") + shown.join(", ") + ".";
}

/**
 * What is typed as an address, or null when it is not one. `{same: true, pathname, search, hash}` for an address of this site (the pieces as the address parser gives them: the query and
 * the fragment are not looked at), `{same: false}` for any other (another site, a scheme that is not a web page's, or an address that cannot be read).
 */
function addressOf(text, win) {
  const typed = text.trim();
  if (!ADDRESS.test(typed)) return null;
  try {
    const url = new URL(typed, win.location.href);
    return url.origin === win.location.origin ? { same: true, pathname: url.pathname, search: url.search, hash: url.hash } : { same: false };
  } catch {
    return { same: false };
  }
}

/**
 * Start the picker of the home page. `options.navigate` is what opens an address (the window's `location.assign` by default) and `options.trioAddress` what makes the address of the
 * page of a trio from a pasted link (canonical.js by default); tests give others, and what the second gives is checked again before it is offered. A page with no picker is left alone, and
 * so is the picker of a page with no search box (the chips alone are the picker then).
 */
export function initPicker(doc, options = {}) {
  const picker = doc.getElementById("picker");
  const status = doc.getElementById("picker-status");
  if (!picker || !status) return;
  const search = doc.getElementById("trio-search");
  const win = doc.defaultView;
  const navigate = options.navigate ?? ((href) => win.location.assign(href));
  const locate = options.trioAddress ?? trioAddress;
  const boxes = [...picker.querySelectorAll('input[type="checkbox"]')];
  const live = new Set((picker.dataset.live ?? "").split(" ").filter(Boolean));
  const built = [...live];
  const nameOf = (box) => doc.querySelector('label[for="' + box.id + '"]').textContent.trim();
  const classes = boxes.map((box) => ({ code: box.value, name: nameOf(box) }));

  // What the status line says now, as a key: the status is a live region, which a screen reader says again whenever it is replaced, so it is replaced only when this changes.
  const keyOf = (href, text, note) => JSON.stringify([href, text, note]);
  let shown = keyOf(null, status.textContent, ""); // (the words the page was written with)
  const say = (text, href, note) => {
    const key = keyOf(href, text, note);
    if (key === shown) return;
    shown = key;
    status.replaceChildren();
    if (href === null) {
      status.append(doc.createTextNode(text + note));
      return;
    }
    const link = doc.createElement("a");
    link.setAttribute("href", href);
    link.textContent = text;
    status.append(link);
    if (note !== "") status.append(doc.createTextNode(note));
  };

  /** Show the state of the chips in the status line. `extra.read` is what the box said, when it is what changed, `extra.target` the address that a pasted link gave, and `extra.address` that the box holds an address that is not the page of a trio. */
  const update = (extra = {}) => {
    const chosen = boxes.filter((box) => box.checked);
    for (const box of boxes) box.disabled = !box.checked && chosen.length >= WANTED;
    if (extra.address === true) {
      say(ADDRESS_TEXT, null, "");
      return;
    }
    const read = extra.read;
    const notes = [];
    if (read !== undefined && (read.codes.length > WANTED || (read.codes.length >= WANTED && read.partialClass))) notes.push(TOO_MANY_TEXT);
    if (read !== undefined && read.unknown.length > 0) notes.push(unknownText(read.unknown));
    const note = notes.length > 0 ? " " + notes.join(" ") : "";
    if (chosen.length < WANTED) {
      const more = WANTED - chosen.length;
      say(more === WANTED ? "Pick three classes." : "Pick " + more + " more class" + (more === 1 ? "." : "es."), null, note);
      return;
    }
    // the boxes are in class-id order, which is the order of a trio's address and name
    const slug = chosen.map((box) => box.value.toLowerCase()).join("-");
    const name = chosen.map(nameOf).join(" / ");
    if (live.has(slug)) say("Open " + name + ": best gear", extra.target ?? "/trio/" + slug + "/", note);
    else say(name + ": coming soon. There is no page for this trio yet.", null, note);
  };

  /** Choose the chips of these codes and no others. */
  const choose = (codes) => {
    for (const box of boxes) box.checked = codes.includes(box.value);
  };

  /** Write what the chips say into the box, in the codes it reads. */
  const writeBox = () => {
    if (search) search.value = boxes.filter((box) => box.checked).map((box) => box.value.toLowerCase()).join(" ");
  };

  for (const box of boxes) {
    box.addEventListener("change", () => {
      update();
      writeBox();
    });
  }
  if (search) {
    search.addEventListener("input", () => {
      const typed = search.value.slice(0, MAX_QUERY_LENGTH);
      const address = addressOf(typed, win);
      if (address !== null) {
        // a link: the page of a trio of the build is offered with the query and the fragment it came with (a shared kit is in them), and nothing else is read for classes
        const target = address.same ? locate(address, built) : null;
        if (target !== null && isSafeTarget(target, built)) {
          choose(target.slice("/trio/".length, "/trio/".length + 11).split("-").map((code) => code.toUpperCase()));
          update({ target });
        } else {
          choose([]);
          update({ address: true });
        }
        return;
      }
      const read = readQuery(typed, classes);
      choose(read.codes.slice(0, WANTED));
      update({ read });
    });
    search.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.isComposing) return;
      const link = status.querySelector("a");
      if (link === null) return;
      event.preventDefault();
      navigate(link.getAttribute("href"));
    });
  }
  picker.hidden = false;
  update();
  writeBox(); // (a browser may have put the chips back as they were before the visitor went away and came back)
  if (search && win && win.location.hash === SEARCH_HASH) search.focus();
}
