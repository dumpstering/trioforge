// Runs in the head, before the page paints, so a remembered theme does not flash the wrong colours first.
import { applyStoredTheme, getStorage } from "./theme.js";

applyStoredTheme(document, getStorage(window));

// A trio page keeps room in its choices for the control of the priorities, which the page script draws there. If that script has not drawn it in a few seconds (it failed, or the browser does not run it)
// the room is given up: the stylesheet takes the mark away with the gap. (A script that is only slow draws the control when it comes, in the room the page has.)
setTimeout(() => document.documentElement.setAttribute("data-prio-off", ""), 6000);
