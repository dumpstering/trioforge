// The 404 page reads an address that has no file (static/canonical.js). A trio page lives at /trio/<x>-<y>-<z>/ with the classes in the site's own order, and a hand-typed or
// old link can have the classes in any order, in any case, with or without the last slash. `canonicalTrio` and `canonicalUrl` turn those into the one address of the page, and
// refuse everything else. The steps, in this order, are the whole safety of it:
//   1. the path is cut at its slashes and each piece is decoded once (a piece that cannot be decoded is refused; an encoded slash can never act as a separator);
//   2. it is normalised: the slashes at both ends go, and what is left must be letters and hyphens only (checked before the case is folded, so that a look-alike never folds into a letter);
//   3. the trio is looked up in the list of the trios the build made;
//   4. the address is made from the list's own spelling of the trio. Nothing the visitor typed is copied into it but the query and the fragment, which are appended as the browser gave them.

import { describe, expect, it } from "vitest";
import { areaOf, canonicalTrio, canonicalUrl, isSafeTarget, trioAddress, trioPath } from "../pipeline/trioforge/site/static/canonical.js";

/** Five trios, each in the order of the site's classes, and one more that is a real trio but was not built. */
const TRIOS = ["clr-pal-shd", "clr-shd-ber", "mnk-shm-ber", "pal-mnk-ber", "pal-shd-ber"];
const NOT_BUILT = "war-clr-pal";

const permutations = (items) =>
  items.length <= 1 ? [items] : items.flatMap((item, at) => permutations([...items.slice(0, at), ...items.slice(at + 1)]).map((rest) => [item, ...rest]));

/** The same text in four cases. */
const CASES = [
  (text) => text,
  (text) => text.toUpperCase(),
  (text) => text.replace(/(^|-)([a-z])/g, (_, dash, letter) => dash + letter.toUpperCase()),
  (text) => [...text].map((c, at) => (at % 2 ? c : c.toUpperCase())).join(""),
];

const at = (pathname, search = "", hash = "") => ({ pathname, search, hash });

describe("every order of a trio reaches its page", () => {
  it("has six orders for each of the five trios, and all of them are found", () => {
    for (const slug of TRIOS) {
      const orders = permutations(slug.split("-"));
      expect(orders).toHaveLength(6);
      for (const order of orders) {
        expect(canonicalTrio(`/trio/${order.join("-")}/`, TRIOS), `${order.join("-")}`).toBe(slug);
      }
    }
  });

  it("finds it in any case, with the last slash or without it, and with the word trio in any case", () => {
    for (const slug of TRIOS) {
      for (const order of permutations(slug.split("-"))) {
        for (const style of CASES) {
          const typed = style(order.join("-"));
          for (const path of [`/trio/${typed}/`, `/trio/${typed}`, `/${style("trio")}/${typed}/`, `//trio/${typed}//`]) {
            expect(canonicalTrio(path, TRIOS), path).toBe(slug);
          }
        }
      }
    }
  });

  it("makes the address of the page from the list's own spelling of the trio", () => {
    expect(trioPath("pal-mnk-ber")).toBe("/trio/pal-mnk-ber/");
    for (const slug of TRIOS) {
      for (const order of permutations(slug.split("-"))) {
        // (in capitals and without the last slash, the right order is another address as well, so that is a move too)
        expect(canonicalUrl(at(`/Trio/${order.join("-").toUpperCase()}`), TRIOS), order.join("-")).toBe(`/trio/${slug}/`);
      }
    }
  });

  it("does not move a visitor who is on the right address already (a redirect to the same address would load the page again for ever)", () => {
    for (const slug of TRIOS) expect(canonicalUrl(at(`/trio/${slug}/`, "?tier=4", "#k=abc"), TRIOS)).toBeNull();
    // the same trio without its last slash is another address, so that is a move
    expect(canonicalUrl(at("/trio/pal-mnk-ber"), TRIOS)).toBe("/trio/pal-mnk-ber/");
  });

  it("finds an address that is encoded once (a percent sign standing for a letter or a hyphen)", () => {
    expect(canonicalTrio("/trio/pal%2Dmnk%2Dber/", TRIOS)).toBe("pal-mnk-ber");
    expect(canonicalTrio("/%74rio/%42ER-pal-mnk/", TRIOS)).toBe("pal-mnk-ber");
  });
});

describe("a trio the build did not make is never a target", () => {
  it("is not found, in whatever order and case it is typed", () => {
    expect(NOT_BUILT.split("-")).toHaveLength(3);
    for (const order of permutations(NOT_BUILT.split("-"))) {
      for (const style of CASES) expect(canonicalTrio(`/trio/${style(order.join("-"))}/`, TRIOS)).toBeNull();
    }
    expect(canonicalUrl(at("/trio/pal-clr-war/", "?tier=4", "#k=abc"), TRIOS)).toBeNull();
  });

  it("is found only while the list has it, and only the list decides", () => {
    expect(canonicalTrio("/trio/pal-war-clr/", [...TRIOS, NOT_BUILT])).toBe(NOT_BUILT);
    expect(canonicalTrio("/trio/pal-mnk-ber/", [])).toBeNull();
    expect(canonicalTrio("/trio/pal-mnk-ber/", undefined)).toBeNull();
    expect(canonicalTrio("/trio/pal-mnk-ber/", [null, 7, {}, "pal-mnk-ber"])).toBe("pal-mnk-ber");
  });

  it("takes no entry of the list that is not a trio in the shape the build writes (three different codes of three small letters)", () => {
    // each entry is asked for by a path that would find it if it were taken: the same codes, in another order
    for (const [entry, asked] of [
      ["PAL-MNK-BER", "/trio/ber-mnk-pal/"],
      ["Pal-Mnk-Ber", "/trio/ber-mnk-pal/"],
      ["pal-pal-mnk", "/trio/mnk-pal-pal/"],
      ["pal-mnk-ber ", "/trio/ber-mnk-pal/"],
      [" pal-mnk-ber", "/trio/ber-mnk-pal/"],
      ["pal-mnk-ber\n", "/trio/ber-mnk-pal/"],
      ["pal-mnk-ber-war", "/trio/ber-mnk-pal/"],
      ["pal-mnk", "/trio/mnk-pal/"],
      ["pa-mnk-ber", "/trio/ber-mnk-pa/"],
      ["pal_mnk_ber", "/trio/ber_mnk_pal/"],
      ["pal-mnk-be2", "/trio/be2-mnk-pal/"],
      ["", "/trio//"],
      ["-pal-mnk-ber", "/trio/ber-mnk-pal-/"],
      ["pal\uFF0Dmnk-ber", "/trio/ber-mnk\uFF0Dpal/"],
    ]) {
      expect(canonicalTrio(asked, [entry]), `[${JSON.stringify(entry)}]`).toBeNull();
    }
    expect(canonicalTrio("/trio/ber-mnk-pal/", ["pal-mnk-ber"]), "the control: the same asking finds a good entry").toBe("pal-mnk-ber");
  });

  it("does not guess between two entries of the list that are the same trio in two orders", () => {
    expect(canonicalTrio("/trio/ber-mnk-pal/", ["pal-mnk-ber", "mnk-pal-ber"])).toBeNull();
    expect(canonicalTrio("/trio/ber-mnk-pal/", ["pal-mnk-ber", "pal-mnk-ber"])).toBe("pal-mnk-ber"); // (the same entry twice is one trio)
  });

  it("is not fooled by a name that Object.prototype has", () => {
    for (const word of ["constructor", "__proto__", "toString", "hasOwnProperty", "valueOf"]) {
      expect(canonicalTrio(`/trio/${word}/`, TRIOS), word).toBeNull();
      expect(canonicalTrio(`/${word}/pal-mnk-ber/`, TRIOS), word).toBeNull();
    }
  });
});

describe("the query and the fragment go with the visitor", () => {
  const TAILS = [
    ["", ""],
    ["?tier=4", ""],
    ["?race=OGR&role=melee&tier=10&setup=dw&ev=wiki&buffs=group", ""],
    ["", "#k=AAECAwQF"],
    ["?tier=0", `#k=${"A".repeat(2048)}`],
    ["", "#k=-_-_"], // the alphabet of the kit code
    ["?x=//evil.example", "#//evil.example"], // an address in them is only text in them
    ["?next=https://evil.example/&u=%5C%5Cevil", "#https://evil.example"],
    ["?a=%2F%2Fevil.example&b=%25%32%46", "#k=%25%32%46"], // escapes inside them are not touched: not decoded, not encoded again
    ["?q=a b", "#k=a b"],
    ["?", "#"],
    ["?tier=4&tier=10", "#k=1#k=2"],
  ];

  it("appends both exactly as the browser gave them, to the address of the page", () => {
    for (const [search, hash] of TAILS) {
      for (const order of permutations(["pal", "mnk", "ber"])) {
        const target = canonicalUrl(at(`/trio/${order.join("-")}/`, search, hash), TRIOS);
        if (order.join("-") === "pal-mnk-ber") continue;
        expect(target, `${order.join("-")} ${search} ${hash}`).toBe(`/trio/pal-mnk-ber/${search}${hash}`);
        expect(isSafeTarget(target, TRIOS)).toBe(true);
      }
    }
  });

  it("keeps a kit fragment of the longest size the codec reads, byte for byte", () => {
    const hash = `#k=${"Zz09-_".repeat(342)}`;
    expect(hash.length).toBeGreaterThan(2048);
    expect(canonicalUrl(at("/Trio/BER-MNK-PAL", "?tier=4", hash), TRIOS)).toBe(`/trio/pal-mnk-ber/?tier=4${hash}`);
  });

  it("makes no change to a query or a fragment that is not text (it is not asked about them)", () => {
    expect(canonicalUrl({ pathname: "/trio/ber-mnk-pal/" }, TRIOS)).toBe("/trio/pal-mnk-ber/");
    expect(canonicalUrl({ pathname: "/trio/ber-mnk-pal/", search: 5, hash: null }, TRIOS)).toBe("/trio/pal-mnk-ber/");
  });
});

describe("what is not an address of a trio is refused", () => {
  /** [what it is, the path as location.pathname would hold it] */
  const HOSTILE = [
    // another host
    ["a double slash and a host", "//evil.example/"],
    ["a double slash, a host and a trio path", "//evil.example/trio/pal-mnk-ber/"],
    ["a trio path under a host", "//evil.example//trio/pal-mnk-ber/"],
    ["a slash and a backslash and a host", "/\\evil.example"],
    ["a slash, a backslash, a host and a trio path", "/\\evil.example/trio/pal-mnk-ber/"],
    ["two backslashes and a host", "\\\\evil.example/trio/pal-mnk-ber/"],
    ["a backslash in the trio", "/trio/pal\\mnk-ber/"],
    ["a backslash after the trio", "/trio/pal-mnk-ber\\"],
    ["a backslash instead of the second slash", "/trio\\pal-mnk-ber/"],
    ["an address with a scheme and a host", "https://evil.example/trio/pal-mnk-ber/"],
    ["a scheme after a slash", "/https://evil.example/"],
    ["a scheme in the trio", "/trio/https:/evil.example/"],
    ["a scheme-relative address without the slash", "evil.example/trio/pal-mnk-ber/"],
    ["javascript:", "javascript:alert(1)"],
    ["javascript: after a slash", "/javascript:alert(1)"],
    ["javascript: in the trio", "/trio/javascript:alert(1)/"],
    ["javascript: with a trio path after it", "javascript:alert(1)//trio/pal-mnk-ber/"],
    ["data:", "data:text/html,x"],
    ["a protocol-relative address with a trio path", "//trio/evil.example/pal-mnk-ber/"],
    ["an at sign", "/trio/pal-mnk-ber@evil.example/"],
    ["a colon", "/trio/pal-mnk-ber:80/"],
    // encoded once
    ["an encoded slash after the trio", "/trio/pal-mnk-ber%2F/"],
    ["an encoded slash in place of the slash after trio", "/trio%2Fpal-mnk-ber/"],
    ["an encoded slash in place of the first slash", "%2Ftrio/pal-mnk-ber/"],
    ["encoded slashes and a host", "%2F%2Fevil.example"],
    ["encoded slashes and a host after a slash", "/%2F%2Fevil.example/"],
    ["an encoded slash in lower case", "/trio/pal-mnk%2fber/"],
    ["an encoded backslash", "/trio/pal-mnk-ber%5C/"],
    ["an encoded backslash and a host", "/%5Cevil.example"],
    ["an encoded backslash in lower case", "/trio%5cpal-mnk-ber/"],
    ["an encoded colon", "/trio/%6Aavascript%3Aalert(1)/"],
    // encoded twice: decoded once they still hold a percent sign
    ["a double-encoded letter", "/trio/%2570al-mnk-ber/"],
    ["a double-encoded slash", "/trio/pal-mnk-ber%252F/"],
    ["a double-encoded slash and a host", "/%252F%252Fevil.example"],
    ["a double-encoded hyphen", "/trio/pal%252Dmnk%252Dber/"],
    ["a double-encoded backslash", "/trio/pal-mnk-ber%255C/"],
    ["a double-encoded dot", "/trio/%252e%252e/pal-mnk-ber/"],
    ["a triple-encoded letter", "/trio/%252570al-mnk-ber/"],
    ["a doubled percent sign", "/trio/%%70al-mnk-ber/"],
    // dot-segments
    ["a parent segment", "/trio/../trio/pal-mnk-ber/"],
    ["a current segment", "/trio/./pal-mnk-ber/"],
    ["a parent segment encoded", "/trio/%2e%2e/pal-mnk-ber/"],
    ["a parent segment encoded in capitals", "/trio/%2E%2E/pal-mnk-ber/"],
    ["a parent segment and an encoded slash", "/trio/%2E%2E%2Fpal-mnk-ber/"],
    ["a parent segment last", "/trio/pal-mnk-ber/.."],
    ["a current segment last", "/trio/pal-mnk-ber/."],
    ["a parent segment first", "/../trio/pal-mnk-ber/"],
    ["only dots", "/.."],
    ["three dots", "/trio/.../"],
    ["a dot in the trio", "/trio/pal.mnk.ber/"],
    ["a dot after the trio", "/trio/pal-mnk-ber./"],
    ["the page of the trio", "/trio/pal-mnk-ber/index.html"],
    // characters that are not letters and hyphens
    ["an underscore", "/trio/pal_mnk_ber/"],
    ["a space", "/trio/pal mnk ber/"],
    ["an encoded space", "/trio/pal%20mnk%20ber/"],
    ["a plus sign", "/trio/pal+mnk+ber/"],
    ["a digit", "/trio/pal-mnk-be2/"],
    ["a null", "/trio/pal-mnk-ber%00/"],
    ["a line end", "/trio/pal-mnk-ber%0D%0A/"],
    ["a tab", "/trio/pal-mnk%09ber/"],
    ["a control character", "/trio/pal-mnk-ber\u0001/"],
    ["a dollar sign", "/trio/pal-mnk-ber$/"],
    ["a quote", "/trio/pal-mnk-ber'/"],
    ["a tag", "/trio/<pal>-mnk-ber/"],
    ["a question mark that is part of the path", "/trio/pal-mnk-ber?/"],
    ["a hash sign that is part of the path", "/trio/pal-mnk-ber#/"],
    // malformed escapes
    ["a percent sign at the end", "/trio/pal-mnk-ber%/"],
    ["a percent sign and two letters that are not digits", "/trio/%zz/"],
    ["a percent sign and one digit", "/trio/pal-mnk-be%4/"],
    ["a byte sequence that is not UTF-8", "/trio/%E0%A4%A/"],
    ["a lone continuation byte", "/trio/pal-mnk-%80ber/"],
    ["only a percent sign", "%"],
    // shapes that are not the address of a trio
    ["a trio with extra pieces after it", "/trio/pal-mnk-ber/extra/"],
    ["a trio with a piece before it", "/x/trio/pal-mnk-ber/"],
    ["the folder of the trios", "/trio/"],
    ["the folder of the trios without the slash", "/trio"],
    ["the home page", "/"],
    ["nothing", ""],
    ["a slash inside the pieces", "/trio//pal-mnk-ber/"],
    ["another folder", "/item/pal-mnk-ber/"],
    ["the folder of the trios, pluralised", "/trios/pal-mnk-ber/"],
    ["two codes", "/trio/pal-mnk/"],
    ["four codes", "/trio/pal-mnk-ber-war/"],
    ["a doubled hyphen", "/trio/pal--mnk-ber/"],
    ["a hyphen first", "/trio/-pal-mnk-ber/"],
    ["a hyphen last", "/trio/pal-mnk-ber-/"],
    ["a code of four letters", "/trio/palx-mnk-ber/"],
    ["a code of two letters", "/trio/pa-mnk-ber/"],
    ["a class twice", "/trio/pal-pal-mnk/"],
    ["the full names of the classes", "/trio/paladin-monk-berserker/"],
    ["a trio with a name that is not a class", "/trio/pal-mnk-xyz/"],
    // look-alikes: none of them is a letter of the alphabet, whatever folding or normalising would make of it
    ["a fullwidth letter", "/trio/\uFF50al-mnk-ber/"],
    ["fullwidth letters all through", "/trio/\uFF50\uFF41\uFF4C-\uFF4D\uFF4E\uFF4B-\uFF42\uFF45\uFF52/"],
    ["Cyrillic letters", "/trio/\u0440\u0430l-mnk-ber/"],
    ["a Kelvin sign for the k", "/trio/pal-mn\u212A-ber/"],
    ["a Kelvin sign for the k in capitals", "/TRIO/PAL-MN\u212A-BER/"],
    ["a long s", "/trio/pal-\u017Fhd-ber/"],
    ["a dotless i in trio", "/tr\u0131o/pal-mnk-ber/"],
    ["a dotted capital I", "/trio/pal-mnk-\u0130er/"],
    ["a hyphen that is not one (U+2010)", "/trio/pal\u2010mnk\u2010ber/"],
    ["a non-breaking hyphen", "/trio/pal\u2011mnk\u2011ber/"],
    ["a minus sign", "/trio/pal\u2212mnk-ber/"],
    ["an en dash", "/trio/pal\u2013mnk\u2013ber/"],
    ["a fullwidth hyphen", "/trio/pal\uFF0Dmnk-ber/"],
    ["a zero-width space", "/trio/pal-mnk-ber\u200B/"],
    ["a zero-width joiner", "/trio/pal-mn\u200Dk-ber/"],
    ["a right-to-left mark", "/trio/pal-mnk-ber\u200F/"],
    ["a combining mark", "/trio/pal-mnk-ber\u0307/"],
    ["a fullwidth slash", "/trio\uFF0Fpal-mnk-ber/"],
    ["a fraction slash", "/trio\u2044pal-mnk-ber/"],
    ["a division slash", "/trio\u2215pal-mnk-ber/"],
    ["a fullwidth solidus before a host", "/\uFF0Fevil.example/"],
    ["a fullwidth dot", "/trio/pal-mnk-ber\uFF0E/"],
    ["an ideographic full stop", "/trio/pal-mnk-ber\u3002/"],
    ["a backslash look-alike (U+FE68)", "/trio/pal\uFE68mnk-ber/"],
    ["a byte order mark", "/trio/\uFEFFpal-mnk-ber/"],
    ["a non-character", "/trio/pal-mnk-ber\uFFFF/"],
    ["an emoji", "/trio/pal-mnk-ber\u{1F600}/"],
    ["a lone surrogate", "/trio/pal-mnk-ber\uD800/"],
  ];

  it.each(HOSTILE)("refuses %s", (_what, pathname) => {
    expect(canonicalTrio(pathname, TRIOS)).toBeNull();
    expect(canonicalUrl(at(pathname, "?tier=4", "#k=abc"), TRIOS)).toBeNull();
    expect(trioAddress(at(pathname, "?tier=4", "#k=abc"), TRIOS)).toBeNull();
  });

  it("refuses the same look-alikes when the browser has percent-encoded them (as location.pathname holds a non-ASCII letter)", () => {
    const looks = ["\uFF50", "\u0440", "\u212A", "\u017F", "\u0131", "\u0130", "\u2010", "\u2011", "\u2212", "\u2013", "\uFF0D", "\u200B", "\u200D", "\u200F", "\u0307", "\uFF0F", "\u2044", "\u2215", "\uFF0E", "\u3002", "\uFE68", "\uFEFF", "\u{1F600}"];
    for (const look of looks) {
      const typed = encodeURIComponent(look);
      for (const path of [`/trio/${typed}al-mnk-ber/`, `/trio/pal-mnk-ber${typed}/`, `/trio/pal${typed}mnk${typed}ber/`, `/trio${typed}pal-mnk-ber/`, `/${typed}rio/pal-mnk-ber/`]) {
        expect(canonicalTrio(path, TRIOS), path).toBeNull();
      }
    }
  });

  it("answers null and does not throw for what is not text, or is far too long", () => {
    for (const value of [undefined, null, 0, 42, {}, [], ["/trio/pal-mnk-ber/"], true, () => "/trio/pal-mnk-ber/", Symbol("x")]) {
      expect(() => canonicalTrio(value, TRIOS)).not.toThrow();
      expect(canonicalTrio(value, TRIOS)).toBeNull();
      expect(canonicalUrl(value, TRIOS)).toBeNull();
      expect(canonicalUrl({ pathname: value, search: "", hash: "" }, TRIOS)).toBeNull();
    }
    expect(canonicalUrl(undefined, TRIOS)).toBeNull();
    expect(canonicalUrl(null, TRIOS)).toBeNull();
    expect(canonicalTrio(`/trio/${"a".repeat(5000)}/`, TRIOS)).toBeNull();
    expect(canonicalTrio(`/${"%2F".repeat(5000)}`, TRIOS)).toBeNull();
    expect(canonicalTrio(`${"/".repeat(5000)}trio/pal-mnk-ber/`, TRIOS)).toBeNull();
    // the longest an address of ours can be, with a generous amount of slashes at the ends, still works
    expect(canonicalTrio(`${"/".repeat(40)}trio/ber-mnk-pal${"/".repeat(40)}`, TRIOS)).toBe("pal-mnk-ber");
  });

  it("is deterministic and does not remember the last answer", () => {
    for (let round = 0; round < 3; round += 1) {
      expect(canonicalTrio("/trio/ber-mnk-pal/", TRIOS)).toBe("pal-mnk-ber");
      expect(canonicalTrio("//evil.example/", TRIOS)).toBeNull();
    }
  });
});

describe("the address of the page of a trio, for a link that names one", () => {
  it("is the page of the trio and the query and the fragment as given, whatever the order or case of the link", () => {
    for (const slug of TRIOS) {
      for (const order of permutations(slug.split("-"))) {
        expect(trioAddress(at(`/Trio/${order.join("-").toUpperCase()}/`, "?tier=4&role=melee", "#k=AbC_-9"), TRIOS), order.join("-")).toBe(`/trio/${slug}/?tier=4&role=melee#k=AbC_-9`);
      }
    }
  });

  it("answers for the right address as well, which canonicalUrl does not (it would send a visitor to the page that he is on): the kit of a pasted link is kept", () => {
    const here = at("/trio/pal-mnk-ber/", "?tier=4", "#k=abc");
    expect(canonicalUrl(here, TRIOS)).toBeNull();
    expect(trioAddress(here, TRIOS)).toBe("/trio/pal-mnk-ber/?tier=4#k=abc");
    expect(trioAddress(at("/trio/pal-mnk-ber"), TRIOS)).toBe("/trio/pal-mnk-ber/");
  });

  it("keeps a fragment of the longest size the codec reads, byte for byte, and is checked by isSafeTarget", () => {
    const hash = `#k=${"Zz09-_".repeat(342)}`;
    const target = trioAddress(at("/trio/ber-mnk-pal/", "", hash), TRIOS);
    expect(target).toBe(`/trio/pal-mnk-ber/${hash}`);
    expect(isSafeTarget(target, TRIOS)).toBe(true);
  });

  it("is nothing for a trio the build did not make, and does not mind a query or a fragment that is not text", () => {
    expect(trioAddress(at(`/trio/${NOT_BUILT}/`, "?a=b", "#k=1"), TRIOS)).toBeNull();
    expect(trioAddress({ pathname: "/trio/ber-mnk-pal/", search: 5, hash: null }, TRIOS)).toBe("/trio/pal-mnk-ber/");
    for (const value of [undefined, null, 0, "text", []]) expect(trioAddress(value, TRIOS)).toBeNull();
  });
});

describe("the order of the steps", () => {
  it("decodes once: what is still encoded after that is refused, and what one decoding makes of it is not looked at again", () => {
    // %2570 is %70 after one decoding, and %70 is a "p" after a second: a second decoding would find the trio
    expect(decodeURIComponent(decodeURIComponent("%2570al")), "this is what a second decoding would do").toBe("pal");
    expect(canonicalTrio("/trio/%2570al-mnk-ber/", TRIOS)).toBeNull();
    expect(canonicalTrio("/trio/%70al-mnk-ber/", TRIOS)).toBe("pal-mnk-ber"); // (once is allowed)
    // %252F is %2F after one decoding, a slash after a second
    expect(canonicalTrio("/trio%252Fpal-mnk-ber/", TRIOS)).toBeNull();
  });

  it("cuts the path at its slashes before it decodes: an encoded slash does not make two pieces out of one", () => {
    // decoded first and cut after, "/trio%2Fpal-mnk-ber/" would read as /trio/pal-mnk-ber/ and "/%2e%2e%2Ftrio/pal-mnk-ber/" as /../trio/...
    expect(decodeURIComponent("/trio%2Fpal-mnk-ber/")).toBe("/trio/pal-mnk-ber/");
    expect(canonicalTrio("/trio%2Fpal-mnk-ber/", TRIOS)).toBeNull();
    expect(canonicalTrio("/trio%2fpal-mnk-ber/", TRIOS)).toBeNull();
    expect(canonicalTrio("%2Ftrio%2Fpal-mnk-ber%2F", TRIOS)).toBeNull();
  });

  it("checks the letters before it folds the case: a character that folds into a letter is not a letter", () => {
    expect("\u212A".toLowerCase(), "this is what folding first would do").toBe("k");
    expect(canonicalTrio("/trio/pal-mn\u212A-ber/", TRIOS)).toBeNull();
    expect(canonicalTrio("/trio/pal-mnk-ber/", TRIOS)).toBe("pal-mnk-ber");
  });

  it("looks the trio up in the list: a well-formed trio the list does not have is not made into an address", () => {
    expect(canonicalUrl(at("/trio/ber-mnk-war/"), TRIOS)).toBeNull();
    expect(canonicalUrl(at("/trio/ber-mnk-war/"), [...TRIOS, "war-mnk-ber"])).toBe("/trio/war-mnk-ber/");
  });
});

describe("the check of an address before the page goes to it", () => {
  it("accepts the page of a built trio, with a query and a fragment", () => {
    expect(isSafeTarget("/trio/pal-mnk-ber/", TRIOS)).toBe(true);
    expect(isSafeTarget("/trio/pal-mnk-ber/?tier=4", TRIOS)).toBe(true);
    expect(isSafeTarget("/trio/pal-mnk-ber/#k=abc", TRIOS)).toBe(true);
    expect(isSafeTarget("/trio/pal-mnk-ber/?tier=4#k=abc", TRIOS)).toBe(true);
    expect(isSafeTarget("/trio/pal-mnk-ber/?x=//evil.example#//evil.example", TRIOS)).toBe(true);
  });

  it.each([
    ["a host", "//evil.example/trio/pal-mnk-ber/"],
    ["a scheme", "https://evil.example/trio/pal-mnk-ber/"],
    ["javascript:", "javascript:alert(1)"],
    ["a backslash", "/\\evil.example"],
    ["a backslash after the first slash of the trio", "/trio\\pal-mnk-ber/"],
    ["no leading slash", "trio/pal-mnk-ber/"],
    ["another order", "/trio/ber-mnk-pal/"],
    ["a trio the build did not make", `/trio/${NOT_BUILT}/`],
    ["no last slash", "/trio/pal-mnk-ber"],
    ["a piece after the trio", "/trio/pal-mnk-ber/x"],
    ["a dot-segment", "/trio/../trio/pal-mnk-ber/"],
    ["another folder", "/item/pal-mnk-ber/"],
    ["a line end after the trio", "/trio/pal-mnk-ber/\n"],
    ["a space before the query", "/trio/pal-mnk-ber/ ?x"],
    ["upper case", "/TRIO/PAL-MNK-BER/"],
    ["nothing", ""],
    ["a query alone", "?trio=pal-mnk-ber"],
  ])("refuses %s", (_what, target) => {
    expect(isSafeTarget(target, TRIOS)).toBe(false);
  });

  it("refuses what is not text", () => {
    for (const value of [undefined, null, 0, {}, []]) expect(isSafeTarget(value, TRIOS)).toBe(false);
  });
});

describe("which part of the site an address is in", () => {
  it("names the folder of the trios and the folder of the items, in any case and encoded once, and nothing else", () => {
    expect(areaOf("/item/w123/")).toBe("item");
    expect(areaOf("/ITEM/W123")).toBe("item");
    expect(areaOf("/item/")).toBe("item");
    expect(areaOf("/%69tem/x/")).toBe("item");
    expect(areaOf("/trio/nothing-here/")).toBe("trio");
    expect(areaOf("/Trio")).toBe("trio");
    expect(areaOf("//trio/x")).toBe("trio");
    for (const other of ["/", "", "/rules/", "/items/x/", "/it%2Fem/", "/item%2Fx/", "/%252Fitem/", "/item//w1/", "/trio//x/", "/\u212Atem/", "/it\u0435m/", "/data/item/", "item/x", undefined, null, 5]) {
      expect(areaOf(other), String(other)).toBeNull();
    }
  });
});

describe("whatever the visitor types, the answer is nothing or a page of ours", () => {
  /** A small deterministic generator (the same strings on every run). */
  function generator(seed) {
    let state = seed >>> 0;
    return () => {
      state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
      return state / 2 ** 32;
    };
  }

  const PIECES = [
    "/", "/", "/", "\\", "%", "%2", "%2F", "%2f", "%5C", "%25", "%252F", "%2e", "%2E", ".", "..", "-", "-", "trio", "TRIO", "Trio", "pal", "mnk", "ber", "BER", "shd", "clr", "war", "item",
    "x", ":", "@", "?", "#", " ", "%20", "%00", "\u212A", "\uFF50", "\u0440", "\u2010", "\u200B", "https:", "http:", "//", "javascript:", "evil.example", "%E0%A4%A", "%zz",
    "pal-mnk-ber", "ber-mnk-pal", "/trio/", "/trio/ber-", "-pal-mnk", "\n", "\t",
  ];

  it("returns null or the address of a built trio followed by the query and the fragment unchanged, for 30,000 made-up addresses", () => {
    const next = generator(20261018);
    const choose = (list) => list[Math.floor(next() * list.length)];
    const allowed = new RegExp(`^/trio/(?:${TRIOS.join("|")})/\\?q=1#k=abc$`);
    /** An address of a trio typed by a visitor: a built trio, in some order, in some case, with or without the last slash. */
    const typed = () => `/${choose(["trio", "TRIO", "Trio"])}/${choose(CASES)(choose(TRIOS.flatMap((slug) => permutations(slug.split("-")))).join("-"))}${choose(["/", "", "//"])}`;
    /** The same with a piece of the hostile alphabet put in, a character taken out or a character replaced. */
    function spoil(path) {
      const spot = Math.floor(next() * (path.length + 1));
      const kind = Math.floor(next() * 3);
      if (kind === 0) return path.slice(0, spot) + choose(PIECES) + path.slice(spot);
      if (kind === 1) return path.slice(0, spot) + path.slice(spot + 1);
      return path.slice(0, spot) + choose(PIECES) + path.slice(spot + 1);
    }
    let moved = 0;
    for (let round = 0; round < 30_000; round += 1) {
      let pathname;
      if (round % 2 === 0) {
        const count = 1 + Math.floor(next() * 12);
        pathname = next() < 0.7 ? "/" : "";
        for (let n = 0; n < count; n += 1) pathname += choose(PIECES);
      } else {
        pathname = typed();
        for (let n = Math.floor(next() * 3); n > 0; n -= 1) pathname = spoil(pathname);
      }
      const target = canonicalUrl(at(pathname, "?q=1", "#k=abc"), TRIOS);
      if (target === null) continue;
      moved += 1;
      expect(target, JSON.stringify(pathname)).toMatch(allowed);
      expect(isSafeTarget(target, TRIOS), pathname).toBe(true);
      expect(target.startsWith("//") || target.startsWith("/\\"), pathname).toBe(false);
      // an independent reading of what was accepted: no encoded slash or backslash, and, decoded as a whole, the word trio and a trio of letters between slashes
      expect(pathname, "no encoded slash or backslash").not.toMatch(/%2f|%5c/i);
      expect(decodeURIComponent(pathname), pathname).toMatch(/^\/*[Tt][Rr][Ii][Oo]\/(?:[A-Za-z]{3}-){2}[A-Za-z]{3}\/*$/);
    }
    expect(moved, "the generator reaches addresses that are accepted too, or this test would pass by refusing everything").toBeGreaterThan(20);
  });
});
