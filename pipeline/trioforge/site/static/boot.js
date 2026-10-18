// Runs in the head, before the page paints, so a remembered theme does not flash the wrong colours first.
import { applyStoredTheme, getStorage } from "./theme.js";

applyStoredTheme(document, getStorage(window));
