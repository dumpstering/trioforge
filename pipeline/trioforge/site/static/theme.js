// Light, dark or the system's choice. The page follows the system on a first visit (the stylesheet does that by itself);
// the theme button overrides it, and the override is remembered in local storage when the browser allows that.

export const THEME_KEY = "trioforge-theme";
const CHOICES = ["light", "dark"];
const NEXT = { auto: "light", light: "dark", dark: "auto" };

/** `window.localStorage`, or null when the browser refuses to hand it over (blocked storage throws on access). */
export function getStorage(win) {
  try {
    return win.localStorage ?? null;
  } catch {
    return null;
  }
}

export function readTheme(storage) {
  try {
    const value = storage ? storage.getItem(THEME_KEY) : null;
    return CHOICES.includes(value) ? value : null;
  } catch {
    return null;
  }
}

function writeTheme(storage, theme) {
  try {
    if (!storage) return;
    if (theme) storage.setItem(THEME_KEY, theme);
    else storage.removeItem(THEME_KEY);
  } catch {
    // blocked storage: the choice lasts until the page is closed
  }
}

export function applyTheme(doc, theme) {
  const root = doc.documentElement;
  if (theme) root.setAttribute("data-theme", theme);
  else root.removeAttribute("data-theme");
}

/** Put a remembered choice on the page. With nothing remembered the page is left alone, so the system setting rules. */
export function applyStoredTheme(doc, storage) {
  const stored = readTheme(storage);
  if (stored) applyTheme(doc, stored);
}

export function currentTheme(doc) {
  const value = doc.documentElement.getAttribute("data-theme");
  return CHOICES.includes(value) ? value : "auto";
}

/** Show the theme button (it is hidden in the page until this runs) and make it cycle auto, light, dark. */
export function bindThemeToggle(doc, storage) {
  const button = doc.getElementById("theme-toggle");
  if (!button) return;
  applyStoredTheme(doc, storage);
  const show = () => {
    button.textContent = "Theme: " + currentTheme(doc);
  };
  show();
  button.hidden = false;
  button.addEventListener("click", () => {
    const next = NEXT[currentTheme(doc)];
    const theme = next === "auto" ? null : next;
    applyTheme(doc, theme);
    writeTheme(storage, theme);
    show();
  });
}
