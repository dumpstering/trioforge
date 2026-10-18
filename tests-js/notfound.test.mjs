// @vitest-environment jsdom
//
// The script of the 404 page (static/notfound.js) run in jsdom against the baked page the generator writes (fixtures/site/contract/notfound-main.html, which
// pipeline/tests/test_site_build.py checks against the generator). The page is served for every address the site has no file for, and its script does two things: it takes a
// hand-typed or old address of a trio to the page of that trio (keeping the query and the fragment), and it tells a visitor who is lost where to look. A fake `location` stands in for
// the window's, so that the address the page goes to can be read: jsdom cannot navigate.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { initNotFound } from "../pipeline/trioforge/site/static/notfound.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract");
const text = (name) => readFileSync(resolve(CONTRACT, name), "utf8");

const TRIOS = ["clr-pal-shd", "clr-shd-ber", "mnk-shm-ber", "pal-mnk-ber", "pal-shd-ber"];
const permutations = (items) =>
  items.length <= 1 ? [items] : items.flatMap((item, at) => permutations([...items.slice(0, at), ...items.slice(at + 1)]).map((rest) => [item, ...rest]));

/** The address the page is served at: what `location` holds, and a `replace` that records where it is asked to go. */
function place(pathname, search = "", hash = "") {
  return { pathname, search, hash, replace: vi.fn() };
}

/** Mount the baked page (with the theme button the frame has) and give it the list of trios the build made, as the build writes it. */
function mount(trios = TRIOS) {
  document.body.innerHTML = `<button type="button" id="theme-toggle" class="theme-toggle" hidden>Theme</button>${text("notfound-main.html")}`;
  const main = document.getElementById("main");
  if (trios === null) main.removeAttribute("data-trios");
  else main.dataset.trios = trios.join(" ");
}

function run(location, trios = TRIOS) {
  mount(trios);
  return initNotFound({ document, window, location });
}

const hint = () => document.getElementById("notfound-hint");

beforeEach(() => {
  document.documentElement.removeAttribute("data-theme");
  window.localStorage.clear();
});

describe("the baked page", () => {
  it("is the page that the frame and the generator write: a heading, a way home, the list of the trios the build made and a place for a hint", () => {
    mount();
    const main = document.getElementById("main");
    expect(main.dataset.page).toBe("notfound");
    expect(main.querySelector("h1").textContent).toBe("Page not found");
    expect([...main.querySelectorAll("a")][0].getAttribute("href")).toBe("/");
    expect(hint().hidden, "the hint is out of sight until the script has something to say").toBe(true);
    expect(hint().textContent).toBe("");
    expect(hint().querySelector("a"), "no link in the page until the script adds one").toBeNull();
  });
});

describe("an address of a trio in another order, case or form", () => {
  it("goes to the page of the trio and keeps the query and the fragment", () => {
    const location = place("/Trio/BER-MNK-PAL", "?race=OGR&tier=4", "#k=AAECAwQF");
    const result = run(location);
    expect(location.replace).toHaveBeenCalledTimes(1);
    expect(location.replace).toHaveBeenCalledWith("/trio/pal-mnk-ber/?race=OGR&tier=4#k=AAECAwQF");
    expect(result.target).toBe("/trio/pal-mnk-ber/?race=OGR&tier=4#k=AAECAwQF");
  });

  it("is told so on the page while the move is made, and the words 'not found' are not left on it", () => {
    run(place("/trio/ber-pal-mnk/"));
    const main = document.getElementById("main");
    expect(main.querySelector("h1").textContent).toBe("Taking you to the right page");
    expect(main.textContent).not.toMatch(/not found/i);
    expect(main.querySelector(".lead").hidden, "the sentence that says there is nothing here is out of sight").toBe(true);
    expect(hint().hidden).toBe(true);
  });

  it("has the theme button working while the visitor waits for the page they are moved to", () => {
    const location = place("/trio/ber-mnk-pal/");
    run(location);
    expect(location.replace).toHaveBeenCalledTimes(1);
    const button = document.getElementById("theme-toggle");
    expect(button.hidden, "the button is shown").toBe(false);
    expect(button.textContent).toBe("Theme: auto");
    button.click();
    expect(button.textContent).toBe("Theme: light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("reaches every one of the six orders of each of five trios, with the query and the fragment, and no other address", () => {
    for (const slug of TRIOS) {
      for (const order of permutations(slug.split("-"))) {
        const location = place(`/trio/${order.join("-")}${order.join("-") === slug ? "" : "/"}`, "?role=melee", "#k=abc");
        run(location);
        expect(location.replace, order.join("-")).toHaveBeenCalledTimes(1);
        expect(location.replace.mock.calls[0], order.join("-")).toEqual([`/trio/${slug}/?role=melee#k=abc`]);
      }
    }
  });

  it("is moved once only, and is not moved at all when it is on the right address already", () => {
    const right = place("/trio/pal-mnk-ber/", "?tier=4", "#k=abc");
    const result = run(right);
    expect(right.replace).not.toHaveBeenCalled();
    expect(result.target).toBeNull();
    expect(document.getElementById("main").querySelector("h1").textContent).toBe("Page not found");
  });

  it("needs no request, no storage and no other script: it reads the address and the list in the page", () => {
    const fetchSpy = vi.fn();
    const beacon = vi.fn();
    window.fetch = fetchSpy;
    Object.defineProperty(window.navigator, "sendBeacon", { value: beacon, configurable: true });
    run(place("/trio/ber-pal-mnk/", "", "#k=abc"));
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(beacon).not.toHaveBeenCalled();
    expect(window.localStorage.length, "nothing is stored").toBe(0);
    expect(document.querySelectorAll("script, iframe, img, link, object, embed")).toHaveLength(0);
  });
});

describe("an address that is not a trio of the build", () => {
  const STAYS = [
    ["a page that does not exist", "/no/such/page/"],
    ["a trio that was not built", "/trio/war-clr-pal/"],
    ["a trio that was not built, in another order", "/trio/pal-war-clr"],
    ["a trio page with something after it", "/trio/pal-mnk-ber/no-such-page"],
    ["a host", "//evil.example/trio/pal-mnk-ber/"],
    ["a backslash", "/\\evil.example"],
    ["an encoded slash", "/trio%2Fpal-mnk-ber/"],
    ["a double-encoded letter", "/trio/%2570al-mnk-ber/"],
    ["a dot-segment", "/trio/../trio/pal-mnk-ber/"],
    ["a look-alike", "/trio/pal-mn\u212A-ber/"],
    ["a script address", "javascript:alert(1)"],
  ];

  it.each(STAYS)("%s stays where it is, on the 404 page, with the theme button working", (_what, pathname) => {
    const location = place(pathname, "?tier=4", "#k=abc");
    const result = run(location);
    expect(location.replace).not.toHaveBeenCalled();
    expect(result.target).toBeNull();
    expect(document.getElementById("main").querySelector("h1").textContent).toBe("Page not found");
    const button = document.getElementById("theme-toggle");
    expect(button.hidden).toBe(false);
    expect(button.textContent).toBe("Theme: auto");
    button.click();
    expect(button.textContent).toBe("Theme: light");
  });

  it("is not moved when the page has no list of trios, or the list is empty or has nothing in the form of a trio", () => {
    for (const trios of [null, [], [""], ["not-a-trio"], ["PAL-MNK-BER"]]) {
      const location = place("/trio/ber-mnk-pal/");
      run(location, trios);
      expect(location.replace, JSON.stringify(trios)).not.toHaveBeenCalled();
    }
  });

  it("checks the address once more before it goes there, whatever made the address", () => {
    for (const made of ["https://evil.example/", "//evil.example/trio/pal-mnk-ber/", "/\\evil.example", "javascript:alert(1)", "/trio/war-clr-pal/", "/trio/pal-mnk-ber", "trio/pal-mnk-ber/", "", 5, undefined]) {
      const location = place("/trio/ber-mnk-pal/", "?tier=4", "#k=abc");
      mount();
      const result = initNotFound({ document, window, location, canonicalUrl: () => made });
      expect(location.replace, String(made)).not.toHaveBeenCalled();
      expect(result.target).toBeNull();
      expect(document.getElementById("main").querySelector("h1").textContent).toBe("Page not found");
    }
    // the control: an address of the page of a trio of the list is gone to
    const location = place("/trio/ber-mnk-pal/");
    mount();
    initNotFound({ document, window, location, canonicalUrl: () => "/trio/pal-mnk-ber/?a=b#c" });
    expect(location.replace).toHaveBeenCalledWith("/trio/pal-mnk-ber/?a=b#c");
  });

  it("does nothing on a page that is not the 404 page", () => {
    document.body.innerHTML = '<main id="main" data-page="home"></main>';
    const location = place("/trio/ber-mnk-pal/");
    expect(initNotFound({ document, window, location })).toBeNull();
    document.body.innerHTML = "";
    expect(initNotFound({ document, window, location })).toBeNull();
    expect(location.replace).not.toHaveBeenCalled();
  });
});

describe("a visitor who is lost is told where to look", () => {
  it("is sent to the search on the home page from an item that has no page, without the address being repeated on the page", () => {
    const location = place("/item/w123/", "", "");
    run(location);
    expect(location.replace).not.toHaveBeenCalled();
    expect(hint().hidden).toBe(false);
    expect(hint().textContent).toMatch(/no page for this item/i);
    const links = hint().querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe("/#search");
    expect(links[0].textContent).toBe("Search for a trio");
    expect(document.getElementById("main").textContent).not.toContain("w123"); // what was typed is not copied into the page
  });

  it("says something else, and offers the same search, for a trio address that leads nowhere", () => {
    for (const pathname of ["/trio/war-clr-pal/", "/trio/nothing-here/", "/TRIO/%2570al/", "/trio/pal-mnk-ber/extra"]) {
      run(place(pathname));
      expect(hint().hidden, pathname).toBe(false);
      expect(hint().textContent, pathname).toMatch(/no page for this trio|not built/i);
      expect(hint().querySelector("a").getAttribute("href"), pathname).toBe("/#search");
    }
  });

  it("says nothing for any other address", () => {
    for (const pathname of ["/no/such/page/", "/assets/app-00000000.js", "/data/pal-mnk-ber/none.json", "/", "/rules/x/", "/items/w1/", "/it%2Fem/w1/"]) {
      run(place(pathname));
      expect(hint().hidden, pathname).toBe(true);
      expect(hint().textContent, pathname).toBe("");
    }
  });

  it("words the hint with the text of the page and not with markup: the address is never read into it", () => {
    const evil = "/item/<img src=x onerror=alert(1)>/";
    run(place(evil));
    expect(hint().querySelector("img")).toBeNull();
    expect(document.getElementById("main").innerHTML).not.toContain("onerror");
  });
});
