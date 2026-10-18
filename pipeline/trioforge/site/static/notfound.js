// The script of the 404 page. The page is the site's answer to every address it has no file for, so it is the same page for all of them, and this script is what makes it useful:
//
//   * an address of a trio in another order, in capitals, or without the last slash is moved to the page of the trio with location.replace, keeping the query and the fragment (canonical.js
//     decides where, and only to a page of the build). The fragment of a kit link is not touched: this page does not run the code that takes it out of the address (first.js), so it is
//     still in the address when the page of the trio opens, and that page takes it out. For the same reason the page has no analytics beacon, which would see the address;
//   * an address of an item that has no page, or of a trio that leads nowhere, is told so, with a link to the search on the home page;
//   * the theme button works, as it does on every page.
//
// It is a bundle of its own (the build refuses one that holds the code of the page script, see build.py), loaded by this page and by no other, and it asks for nothing: the list of the trios
// of the build is in the page (`data-trios` on <main>). Written for ES2021 and Safari 15.

import { areaOf, canonicalUrl, isSafeTarget } from "./canonical.js";
import { bindThemeToggle, getStorage } from "./theme.js";

/** Where the search is: the home page, which puts the cursor in its search box for this address. */
export const SEARCH_HREF = "/#search";

/** What is said before and after the link, for the part of the site the address was in. */
const HINTS = {
  item: ["There is no page for this item. Not every item has one. ", ", then open the item from its kit."],
  trio: ["There is no page for this trio at this address. It may not be built yet, or the address may have a mistake in it. ", "."],
};

/** Say what a visitor can do from here, for an address of the part of the site it was in. The address itself is never put into the page. */
function showHint(doc, area) {
  const hint = doc.getElementById("notfound-hint");
  if (!hint || !Object.prototype.hasOwnProperty.call(HINTS, area)) return;
  const [before, after] = HINTS[area];
  const link = doc.createElement("a");
  link.setAttribute("href", SEARCH_HREF);
  link.textContent = "Search for a trio";
  hint.replaceChildren(doc.createTextNode(before), link, doc.createTextNode(after));
  hint.hidden = false;
}

/** Tell a visitor who is being moved that they are: the words "not found" would be wrong for as long as the next page takes to come. */
function showMove(main) {
  const heading = main.querySelector("h1");
  if (heading) heading.textContent = "Taking you to the right page";
  const lead = main.querySelector(".lead");
  if (lead) lead.hidden = true;
}

/**
 * Start the 404 page. `env.document`, `env.window` and `env.location` stand in for the page's own, and `env.canonicalUrl` for the function that decides where to go (tests give them; the
 * address it gives is checked again before the page goes there, whatever made it). Returns null on a page that is not the 404 page, else `{ target }`: the address the visitor is being
 * moved to, or null when the page stays.
 */
export function initNotFound(env = {}) {
  const doc = env.document ?? document;
  const win = env.window ?? window;
  const location = env.location ?? win.location;
  const main = doc.getElementById("main");
  if (!main || main.dataset.page !== "notfound") return null;
  bindThemeToggle(doc, getStorage(win)); // (first: a visitor who is being moved waits for the next page with the button that every page has, and it works)
  const trios = (main.dataset.trios ?? "").split(" ").filter(Boolean);
  const target = (env.canonicalUrl ?? canonicalUrl)(location, trios);
  if (target !== null && isSafeTarget(target, trios)) {
    showMove(main);
    location.replace(target);
    return { target };
  }
  showHint(doc, areaOf(location.pathname));
  return { target: null };
}

function start() {
  initNotFound();
}

if (typeof document === "object" && document !== null) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
}
