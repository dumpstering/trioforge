// What the page script does before anything else: it takes a shared kit out of the address.
//
// A module is evaluated in the order it is imported, and app.js imports this one first, so the address is clean (and the payload is in the history entry) before the code of any other
// module of the page script has run, and before the page script adds a script that is not ours (the page counter, counter.js, which it adds only to a page opened with no kit link). A kit link
// is `#k=<payload>`; the payload goes into `history.state`, which survives a reload, and the fragment is removed from the address (input/kitlocation.js has the details). The payload
// is not looked at here: the code of the Upgrade section decodes it, once the item table is in.
//
// One place keeps whether the fragment could be cleared, for the page counter (counter.js; the navigation entry of the page keeps the address it was loaded with, fragment
// included, whatever is done here, so a page that was opened from a kit link is not counted at all): `document.documentElement.dataset.kitFragment`, that is the attribute
// `data-kit-fragment` of the <html> element. It is "cleared" when the page was opened with a kit fragment and it was taken out of the address, "kept" when it was found and is
// still in the address (the browser refused to rewrite it), and absent when the address had no kit fragment (a page opened by a reload has the payload from its history entry,
// and an address with no fragment in it: nothing was in the address to report). `kit` is the result of the take, `{payload, source, cleared}`, which the page code is given.
//
// A second kit link opened in the tab that shows a kit (pasted into the address bar: it differs from the page's address in the fragment only) does not load the page again: the
// browser fires `popstate` (Chrome and Firefox do, for a fragment) and then `hashchange`, and nothing more. `followKitLinks` takes the kit out of the address as the first take did, at the
// first of the two (so that a script of the page that listens later, such as a counter that follows the history, finds the address already clean: for popstate and hashchange only, not for the Navigation
// API's navigate and currententrychange events, which a browser fires before popstate, nor for pagehide, and not at all where the browser refuses replaceState, when the kit stays in the address until the page
// loads again; a script that is running cannot be unloaded, and docs/DECISIONS.md, Part P, says so), says whether it could in the same
// attribute, and loads the page again, which shows the kit of the new link (the same link opened twice shows its kit twice). Any other fragment is not ours.

import { takeKitFromLocation } from "./input/kitlocation.js";

/**
 * The address the document was LOADED with, as it was before anything of the page script ran (this is the first statement of this module; the module that is evaluated before it, input/kitlocation.js, which this one imports, only defines constants and functions, and the page script has no other module that runs earlier): the page counter (counter.js) judges it as well as
 * the current address, because the page code rewrites the address at start-up (trio.js keeps only the page's own switches when one is malformed) and what is left may look clean. It is a constant of
 * this module: no script that runs later can write it. `null` where there is no location (it is then not counted).
 */
export const loadedAddress = typeof location === "object" && location !== null && typeof location.href === "string" ? location.href : null;

export const kit = takeKitFromLocation();

/** Say whether the fragment of a take could be cleared, in the attribute `data-kit-fragment` of the document element (only for a take that found a fragment). */
function note(taken, doc) {
  if (taken.source === "fragment" && typeof doc === "object" && doc !== null) doc.documentElement.dataset.kitFragment = taken.cleared ? "cleared" : "kept";
}

note(kit, typeof document === "object" ? document : null);

/**
 * Listen for a kit link opened in this page. `env.window` is the window to listen on (the page's own by default), `env.reload` what loads the page again (the window's own
 * `location.reload` by default). Returns the function that stops listening.
 */
export function followKitLinks({ window: win = globalThis.window, reload } = {}) {
  const again = typeof reload === "function" ? reload : () => win.location.reload();
  let kept = null; // the address of a kit fragment that could not be cleared and that the page has been loaded again for: the second event of the pair (popstate, then hashchange) is the same link
  const onChange = () => {
    if (kept !== null && win.location.href === kept) return;
    const taken = takeKitFromLocation({ location: win.location, history: win.history });
    if (taken.source !== "fragment") return;
    note(taken, win.document);
    kept = taken.cleared ? null : win.location.href;
    again();
  };
  win.addEventListener("hashchange", onChange);
  win.addEventListener("popstate", onChange);
  return () => {
    win.removeEventListener("hashchange", onChange);
    win.removeEventListener("popstate", onChange);
  };
}

if (typeof window === "object" && window !== null && typeof window.addEventListener === "function") followKitLinks();
