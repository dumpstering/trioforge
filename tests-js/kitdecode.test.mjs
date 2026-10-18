// The decoding half of the kit link codec (input/kitdecode.js). The codec was one module (input/kitcode.js); a visitor who only opens a link to the page never writes one, and the Upgrade
// section's code (which writes them for Share and Remember) never reads one, so the reading half moved to the module of its own that only the panel of a shared kit imports (a chunk of
// its own in the build, loaded when a kit link is opened). The format, the tables and the encoder are kitcode.js's, and its own tests (kitcode.test.mjs, kitcode-fuzz.test.mjs) hold the
// two halves to each other and to the format; this holds the split.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import * as codec from "../pipeline/trioforge/site/static/input/kitcode.js";
import { decodeKit } from "../pipeline/trioforge/site/static/input/kitdecode.js";

const STATIC = new URL("../pipeline/trioforge/site/static/input/", import.meta.url);
const sourceOf = (name) => readFileSync(new URL(name, STATIC), "utf8");
const strip = (source) => source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");

const KIT = { v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: [[0, 90001, 4], [20, 80524, 4]] };
const ITEMS = new Map([["w90001", { name: "x" }]]);

describe("the split of the codec", () => {
  it("has the reading half in kitdecode.js: decodeKit reads what encodeKit writes", () => {
    const decoded = decodeKit(codec.encodeKit(KIT), ITEMS);
    expect(decoded.errors).toEqual([]);
    expect(decoded.kit.slots.map((slot) => [slot.slotIndex, slot.pageId, slot.tier])).toEqual(KIT.slots);
    expect(decoded.unknown).toEqual([20]);
  });

  it("leaves kitcode.js the format, the tables, the messages and the writing half: it has no decoder", () => {
    expect(typeof codec.encodeKit).toBe("function");
    expect(codec.decodeKit).toBeUndefined();
    for (const name of ["KIT_ERRORS", "KitError", "DEFAULT_TABLES", "TRIO_CODES", "RACE_CODES", "SLOT_ORDER", "pageIdFromKey", "keyFromPageId", "MAX_FRAGMENT_LENGTH", "MAX_PAGE_ID", "MAX_TIER"]) {
      expect(codec[name], name).toBeDefined();
    }
    const code = strip(sourceOf("kitcode.js"));
    for (const decoding of ["fromBase64Url", "readVarint", "parseLink", "decodeKit", "INDEX_OF"]) expect(code, decoding).not.toContain(decoding);
  });

  it("imports kitcode.js and nothing else: the page loads one more file for it, not a tree", () => {
    const code = strip(sourceOf("kitdecode.js"));
    const imports = [...code.matchAll(/\bimport\b[^;]*?from\s*["']([^"']+)["']/g)].map((match) => match[1]);
    expect(imports).toEqual(["./kitcode.js"]);
    expect(code).not.toMatch(/\brequire\b|\bprocess\b|\bBuffer\b|\batob\b|\bbtoa\b|import\s*\(/);
  });

  it("is held to the codec's rules: no percent-decoding, no evaluation, no markup, no regular expression, no request", () => {
    const code = strip(sourceOf("kitdecode.js"));
    expect(code).not.toMatch(/decodeURI|decodeURIComponent|unescape|\beval\b|new\s+Function|innerHTML|outerHTML|insertAdjacentHTML|document\.write/);
    expect(code).not.toMatch(/RegExp|\.exec\(|\.match\(|\.matchAll\(|\.search\(|\.replace\(|\.replaceAll\(|\.test\(|\.split\(\s*\//);
    expect(code).not.toMatch(/\bfetch\b|XMLHttpRequest|sendBeacon|location\.(assign|replace|reload|href\s*=)|window\.open|WebSocket|Worker/);
    expect(code).not.toMatch(/export\s+default/);
    expect(sourceOf("kitdecode.js")).toMatch(/^export /m);
  });

  it("never throws: a link it cannot read is a list of errors and no kit", () => {
    for (const text of ["", "!!!", "A", "AAAA", "A".repeat(2049), codec.encodeKit(KIT).slice(0, -3), `${codec.encodeKit(KIT)}A`, 5, null, undefined, {}]) {
      const result = decodeKit(text, ITEMS);
      expect(result.kit, String(text)).toBeNull();
      expect(result.errors, String(text)).toHaveLength(1);
      expect(Object.values(codec.KIT_ERRORS)).toContain(result.errors[0]);
    }
  });
});
