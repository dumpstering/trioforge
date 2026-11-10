// The one script every page loads (as a module, after the page has been read).
// (first.js comes first: it takes a shared kit out of the address before the modules below are evaluated)
import { kit } from "./first.js";
import { initPicker } from "./picker.js";
import { bindThemeToggle, getStorage } from "./theme.js";
import { initTrio } from "./trio.js";

/**
 * The skip link is an in-page anchor, and following one makes a history entry with no state: a reload of that entry would have lost a shared kit, which `history.state` keeps for
 * one entry only. So the page moves to the content itself and moves the focus there, and the address does not change. A click that opens the link somewhere else is left alone.
 */
function keepHistory(doc) {
  const link = doc.querySelector(".skip-link");
  const main = doc.getElementById("main");
  if (!link || !main) return;
  link.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (typeof main.scrollIntoView === "function") main.scrollIntoView();
    main.focus();
  });
}

function start() {
  bindThemeToggle(document, getStorage(window));
  keepHistory(document);
  const page = document.getElementById("main")?.dataset.page;
  if (page === "trio") initTrio({ document, window, fetch: window.fetch.bind(window), kit, exaltAhead: true });
  if (page === "home") initPicker(document);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
else start();
