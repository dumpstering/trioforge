// What the page script does before anything else: it takes a shared kit out of the address.
//
// A module is evaluated in the order it is imported, and app.js imports this one first, so the address is clean (and the payload is in the history entry) before the code of any other
// module of the page script has run, and long before a script that is not ours (the analytics beacon of a later phase is deferred after the page script) can read it. A kit link
// is `#k=<payload>`; the payload goes into `history.state`, which survives a reload, and the fragment is removed from the address (input/kitlocation.js has the details). The payload
// is not looked at here: the code of the Upgrade section decodes it, once the item table is in.
//
// One place keeps whether the fragment could be cleared, for the analytics of a later phase (the navigation entry of the page keeps the address it was loaded with, fragment
// included, whatever is done here, so a page that was opened from a kit link must not report it): `document.documentElement.dataset.kitFragment`, that is the attribute
// `data-kit-fragment` of the <html> element. It is "cleared" when the page was opened with a kit fragment and it was taken out of the address, "kept" when it was found and is
// still in the address (the browser refused to rewrite it), and absent when the address had no kit fragment (a page opened by a reload has the payload from its history entry,
// and an address with no fragment in it: nothing was in the address to report). `kit` is the result of the take, `{payload, source, cleared}`, which the page code is given.
//
// A second kit link opened in the tab that shows a kit (pasted into the address bar: it differs from the page's address in the fragment only) does not load the page again: the
// browser fires `hashchange` and nothing more. `followKitLinks` takes the kit out of the address as the first take did, says whether it could in the same attribute, and loads the page
// again, which shows the kit of the new link (the same link opened twice shows its kit twice). Any other fragment is not ours.

import { takeKitFromLocation } from "./input/kitlocation.js";

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
  const onChange = () => {
    const taken = takeKitFromLocation({ location: win.location, history: win.history });
    if (taken.source !== "fragment") return;
    note(taken, win.document);
    again();
  };
  win.addEventListener("hashchange", onChange);
  return () => win.removeEventListener("hashchange", onChange);
}

if (typeof window === "object" && window !== null && typeof window.addEventListener === "function") followKitLinks();
