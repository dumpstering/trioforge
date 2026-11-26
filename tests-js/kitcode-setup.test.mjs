import { describe, expect, it } from "vitest";
import { ALPHABET, KIT_ERRORS, KitError, SETUP_CODES, encodeKit } from "../pipeline/trioforge/site/static/input/kitcode.js";
import { decodeKit } from "../pipeline/trioforge/site/static/input/kitdecode.js";

// The optional setup marker of a kit link. A link made from a kit with no marker is what it always was (version 1, the same text for the same kit, read to the same kit); a link made
// from a kit made for the Bow setup is version 2: the fields of version 1 and then one number, the code of the setup, 1 for "ranged". A reader that gets a marker it does not know reads
// the kit with no marker, so that a link of a later version still opens (and is valued as an old link is). Every item and name here is invented.

const KIT = { v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: [[0, 90001, 4], [17, 90038, 4], [20, 80923, 4]] };
// the links of the version-1 writer, as they were before the marker existed
const OLD_LINK = "AdgDCTIDAJG_BQQRtr8FBBSb-AQE";
const OLD_EMPTY = "AdgDCTIA";
const items = new Map([["w90001", { name: "a" }], ["w90038", { name: "b" }], ["w80923", { name: "c" }]]);

function toFragment(bytes) {
  let text = "";
  let i = 0;
  for (; i + 2 < bytes.length; i += 3) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
    text += ALPHABET[n >> 18] + ALPHABET[(n >> 12) & 63] + ALPHABET[(n >> 6) & 63] + ALPHABET[n & 63];
  }
  if (bytes.length - i === 1) text += ALPHABET[(bytes[i] << 16) >> 18] + ALPHABET[((bytes[i] << 16) >> 12) & 63];
  else if (bytes.length - i === 2) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8);
    text += ALPHABET[n >> 18] + ALPHABET[(n >> 12) & 63] + ALPHABET[(n >> 6) & 63];
  }
  return text;
}
const bytesOfLink = (link) => {
  const index = new Map([...ALPHABET].map((c, n) => [c, n]));
  const out = [];
  let held = 0;
  let bits = 0;
  for (const char of link) {
    held = (held << 6) | index.get(char);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push((held >> bits) & 255);
      held &= (1 << bits) - 1;
    }
  }
  return out;
};

describe("a kit with no marker", () => {
  it("is written as it always was, whether the marker is absent, undefined or null", () => {
    expect(encodeKit(KIT)).toBe(OLD_LINK);
    expect(encodeKit({ ...KIT, setup: undefined })).toBe(OLD_LINK);
    expect(encodeKit({ ...KIT, setup: null })).toBe(OLD_LINK);
    expect(encodeKit({ ...KIT, slots: [] })).toBe(OLD_EMPTY);
  });
  it("is read as it always was: the kit has no setup at all, not even a key", () => {
    const { kit, errors, unknown } = decodeKit(OLD_LINK, items);
    expect(errors).toEqual([]);
    expect(unknown).toEqual([]);
    expect(Object.keys(kit).sort()).toEqual(["level", "race", "slots", "trio", "v"]);
    expect(kit.slots.map((s) => [s.slotIndex, s.pageId, s.tier])).toEqual(KIT.slots);
    expect(encodeKit(kit)).toBe(OLD_LINK);
  });
});

describe("a kit made for the Bow setup", () => {
  const link = encodeKit({ ...KIT, setup: "ranged" });
  it("is version 2: the bytes of version 1 and then the code of the setup", () => {
    expect(SETUP_CODES).toEqual(["ranged"]);
    const old = bytesOfLink(OLD_LINK);
    const bytes = bytesOfLink(link);
    expect(bytes[0]).toBe(2);
    expect(bytes.slice(1, old.length)).toEqual(old.slice(1));
    expect(bytes.slice(old.length)).toEqual([1]);
    expect(link).toBe(toFragment([2, ...old.slice(1), 1]));
    expect(link).not.toBe(OLD_LINK);
  });
  it("round-trips: the same kit and the same marker, and the link is the one spelling of it", () => {
    const { kit, errors } = decodeKit(link, items);
    expect(errors).toEqual([]);
    expect(kit.setup).toBe("ranged");
    expect(kit).toMatchObject({ v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50 });
    expect(kit.slots.map((s) => [s.slotIndex, s.pageId, s.tier])).toEqual(KIT.slots);
    expect(encodeKit(kit)).toBe(link);
  });
  it("is the same kit as the old link names, place by place, so only the marker tells them apart", () => {
    const a = decodeKit(OLD_LINK, items).kit;
    const b = decodeKit(link, items).kit;
    expect({ ...b, setup: undefined }).toEqual({ ...a, setup: undefined });
  });
  it("needs the marker's number and nothing after it", () => {
    const old = bytesOfLink(OLD_LINK);
    const cut = decodeKit(toFragment([2, ...old.slice(1)]), items);
    expect(cut.kit).toBeNull();
    expect(cut.errors).toEqual([KIT_ERRORS.truncated]);
    const long = decodeKit(toFragment([2, ...old.slice(1), 1, 0]), items);
    expect(long.kit).toBeNull();
    expect(long.errors).toEqual([KIT_ERRORS.trailing]);
    const overlong = decodeKit(toFragment([2, ...old.slice(1), 0x81, 0x00]), items);
    expect(overlong.errors).toEqual([KIT_ERRORS.overlong]);
  });
});

describe("a marker that the reader does not know", () => {
  it("is read as no marker: the kit opens, with no setup, and is the kit of an old link", () => {
    const old = bytesOfLink(OLD_LINK);
    for (const code of [0, 2, 9, 127, 300]) {
      const bytes = code < 128 ? [2, ...old.slice(1), code] : [2, ...old.slice(1), (code % 128) | 128, Math.floor(code / 128)];
      const { kit, errors } = decodeKit(toFragment(bytes), items);
      expect(errors, String(code)).toEqual([]);
      expect(Object.keys(kit).sort(), String(code)).toEqual(["level", "race", "slots", "trio", "v"]);
    }
  });
});

describe("writing a marker", () => {
  it("is for a setup the table has and no other", () => {
    for (const setup of ["dw", "2h", "1h-shield", "stick", "RANGED", "", 1, true, {}]) {
      expect(() => encodeKit({ ...KIT, setup }), String(setup)).toThrow(KitError);
    }
    try {
      encodeKit({ ...KIT, setup: "dw" });
    } catch (error) {
      expect(error.message).toBe(KIT_ERRORS.setup);
    }
  });
  it("leaves the kit's own version at 1: the version of the kit is not the version of its link", () => {
    expect(() => encodeKit({ ...KIT, v: 2, setup: "ranged" })).toThrow(KitError);
  });
});
