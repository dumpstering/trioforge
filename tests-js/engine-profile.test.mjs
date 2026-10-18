import { describe, expect, it } from "vitest";
import { BundleError, assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { FULL, SAMPLE, describeFull } from "./engine-fixtures.mjs";
import { expectWithin, stopwatch } from "./timing.mjs";

// The browser reads a trio's bundle and puts a profile together from it: assembleProfile is a port of assemble() in
// pipeline/trioforge/export/browser.py, held to Profile.to_dict() as Python wrote it for every race, role, buff key and evidence level
// the fixtures export (and the fallback with no evidence level), and held to refuse every bundle that is not what the exporter writes.

const BUNDLE = "profiles/pal-mnk-ber-l50.bundle.json";
const GOOD = { race: "HUM", role: "balanced", buffs: "own" };
const clone = (value) => JSON.parse(JSON.stringify(value));
const sampleBundle = () => clone(SAMPLE.read(BUNDLE));

/** Whether a value and everything inside it cannot be changed. */
function isDeepFrozen(root) {
  const stack = [root];
  const seen = new Set();
  while (stack.length > 0) {
    const node = stack.pop();
    if (node === null || typeof node !== "object" || seen.has(node)) continue;
    seen.add(node);
    if (!Object.isFrozen(node)) return false;
    for (const value of Array.isArray(node) ? node : Object.values(node)) stack.push(value);
  }
  return true;
}

/** An object with the key as an own property, whatever the key is (assigning `__proto__` would change the prototype). */
function withKey(target, key, value) {
  Object.defineProperty(target, key, { value, enumerable: true, configurable: true, writable: true });
  return target;
}

/** The same data with objects that have no prototype (what a reviver or a hand-made parser might make). */
function withoutPrototypes(value) {
  if (Array.isArray(value)) return value.map(withoutPrototypes);
  if (value !== null && typeof value === "object") {
    const copy = Object.create(null);
    for (const [key, item] of Object.entries(value)) copy[key] = withoutPrototypes(item);
    return copy;
  }
  return value;
}

// ---- parity with Python ------------------------------------------------------------------------------------------------------

function parityTests(set) {
  const listings = set.paths("profiles");

  it("lists at least the sample's trio", () => {
    expect(listings).toContain("profiles/pal-mnk-ber-l50.profiles.json");
  });

  for (const path of listings) {
    const slug = path.slice("profiles/".length, -".profiles.json".length);

    it(`${slug}: every profile equals Profile.to_dict(), as assemble() of Python gives it`, () => {
      const listing = set.read(path);
      const bundle = readBundle(set.read(`profiles/${listing.bundle}`));
      expect(listing.profiles.length).toBeGreaterThan(100);
      for (const entry of listing.profiles) {
        const choices = { race: entry.race, role: entry.role, buffs: entry.buffs, ...entry.options };
        const got = assembleProfile(bundle, choices);
        expect(got, JSON.stringify(choices)).toEqual(entry.profile);
      }
    });

    it(`${slug}: lists every race, role and buff key with no evidence level and at each one`, () => {
      const listing = set.read(path);
      const bundle = set.read(`profiles/${listing.bundle}`);
      const levels = bundle.evidence_levels;
      expect(levels).toEqual(["strict", "wiki"]);
      const found = new Set();
      for (const entry of listing.profiles) {
        const way = JSON.stringify([entry.race, entry.role, entry.buffs, entry.options]);
        expect(found.has(way), way).toBe(false);
        found.add(way);
      }
      const races = bundle.races.map((row) => row.code);
      for (const race of races) {
        for (const role of Object.keys(bundle.roles)) {
          for (const buffs of Object.keys(bundle.buffs)) {
            for (const options of [{}, ...levels.map((evidence) => ({ evidence }))]) {
              expect(found.has(JSON.stringify([race, role, buffs, options])), `${race} ${role} ${buffs} ${JSON.stringify(options)}`).toBe(true);
            }
          }
        }
      }
      expect([...found].filter((way) => way.includes('"deity"')).length).toBeGreaterThanOrEqual(3);
    });

    it(`${slug}: the setups of a profile are those of its evidence level, and with none those of the role`, () => {
      const listing = set.read(path);
      const raw = set.read(`profiles/${listing.bundle}`);
      const bundle = readBundle(raw);
      let different = 0;
      for (const role of Object.keys(raw.roles)) {
        const row = raw.roles[role];
        const none = assembleProfile(bundle, { race: "HUM", role, buffs: "own" });
        expect(none.setups).toEqual(row.setups);
        expect(none.evidence).toBe(raw.profile_common.evidence);
        for (const evidence of raw.evidence_levels) {
          const at = assembleProfile(bundle, { race: "HUM", role, buffs: "own", evidence });
          expect(at.setups).toEqual(row.setups_by_evidence[evidence]);
          expect(at.evidence).toBe(evidence);
          different += JSON.stringify(at.setups) !== JSON.stringify(none.setups);
        }
      }
      expect(different).toBeGreaterThan(0); // the public catalog has no strict shield: strict lacks the setup the fallback has
    });
  }
}

describe("the committed sample", () => parityTests(SAMPLE));
describeFull("the full set", (full) => {
  parityTests(full);

  it("is for the release of the sample", () => {
    expect(full.manifest.data_release).toBe(SAMPLE.manifest.data_release);
    expect(full.manifest.rules_version).toBe(SAMPLE.manifest.rules_version);
    expect(full.manifest.scale).toBe("full");
  });

  it("has the bundles of the five trio types and the level 55 one", () => {
    expect(full.paths("profiles").map((path) => path.slice("profiles/".length, -".profiles.json".length)).sort()).toEqual([
      "clr-shd-shm-l50", "pal-mnk-ber-l50", "pal-mnk-ber-l55", "rng-brd-bst-l50", "war-rog-ber-l50", "wiz-mag-enc-l50",
    ]);
  });
});

// ---- what the port gives -------------------------------------------------------------------------------------------------------

describe("the profile", () => {
  const raw = SAMPLE.read(BUNDLE);
  const bundle = readBundle(raw);

  it("is in the field order of Profile.to_dict(), 25 fields", () => {
    const profile = assembleProfile(bundle, GOOD);
    expect(Object.keys(profile)).toEqual([
      "format", "race", "trio", "level", "role", "evidence", "aa", "naked", "buff_totals", "spell_haste", "haste_cap", "softcap", "cs_pct",
      "pe_pct", "defense_cap", "monk", "iksar_ac", "placement", "pools", "caps", "bands", "dw_factor", "weights", "setups", "deity",
    ]);
    expect(profile.race).toBe("HUM");
    expect(profile.role).toBe("balanced");
    expect(profile.deity).toBeNull();
  });

  it("is deep-frozen, and so are its parts", () => {
    const profile = assembleProfile(bundle, { ...GOOD, evidence: "wiki", deity: "Tunare" });
    expect(isDeepFrozen(profile)).toBe(true);
    for (const attempt of [
      () => {
        profile.level = 1;
      },
      () => {
        profile.weights.AC = 1;
      },
      () => {
        profile.setups.push("stick");
      },
      () => {
        profile.pools.HP[0].base = 1;
      },
      () => {
        delete profile.aa;
      },
    ]) {
      expect(attempt).toThrow(TypeError);
    }
    expect(profile.deity).toBe("Tunare");
    expect(profile.evidence).toBe("wiki");
  });

  it("is a copy: changing the bundle it was made from afterwards changes nothing in it", () => {
    const mine = clone(raw);
    const profile = assembleProfile(mine, GOOD);
    const before = JSON.stringify(profile);
    mine.profile_common.aa.combat_stability = 99;
    mine.roles.balanced.weights.AC = 99;
    mine.races[0].naked.STR = 99;
    mine.roles.balanced.setups.push("stick");
    expect(JSON.stringify(profile)).toBe(before);
    expect(Object.isFrozen(mine)).toBe(false); // the bundle it was given is left as it was
    expect(Object.isFrozen(mine.races[0].naked)).toBe(false);
  });

  it("is the same for a bundle that is given raw each time and one that was read once", () => {
    const again = assembleProfile(clone(raw), { ...GOOD, evidence: "strict" });
    expect(again).toEqual(assembleProfile(bundle, { ...GOOD, evidence: "strict" }));
  });

  it("takes the first of the race, role and buff key lists and the last (no case is special)", () => {
    const races = raw.races.map((row) => row.code);
    for (const race of [races[0], races[races.length - 1], "IKS"]) {
      for (const role of Object.keys(raw.roles)) {
        for (const buffs of Object.keys(raw.buffs)) {
          const profile = assembleProfile(bundle, { race, role, buffs });
          expect(profile.race).toBe(race);
          expect(profile.role).toBe(role);
          expect(profile.buff_totals).toEqual(raw.buffs[buffs].buff_totals);
          expect(profile.spell_haste).toBe(raw.buffs[buffs].spell_haste);
          expect(profile.weights).toEqual(raw.roles[role].weights);
          expect(profile.naked).toEqual(raw.races.find((row) => row.code === race).naked);
        }
      }
    }
  });

  it("is made from a bundle whose objects have no prototype just the same", () => {
    const bare = withoutPrototypes(raw);
    expect(assembleProfile(bare, { ...GOOD, evidence: "wiki" })).toEqual(assembleProfile(bundle, { ...GOOD, evidence: "wiki" }));
  });

  it("is made from a bundle that is frozen already", () => {
    const frozen = clone(raw);
    const freeze = (node) => {
      if (node !== null && typeof node === "object") Object.values(node).forEach(freeze);
      return Object.freeze(node);
    };
    expect(assembleProfile(freeze(frozen), GOOD)).toEqual(assembleProfile(bundle, GOOD));
  });
});

describe("the choices", () => {
  const bundle = readBundle(SAMPLE.read(BUNDLE));

  it("throw BundleError for a race, a role or a buff key the bundle does not have", () => {
    const bad = [
      { ...GOOD, race: "XXX" }, { ...GOOD, race: "hum" }, { ...GOOD, race: "" }, { ...GOOD, race: " HUM" },
      { ...GOOD, role: "wizard" }, { ...GOOD, role: "caster" }, { ...GOOD, role: "BALANCED" }, { ...GOOD, role: "" },
      { ...GOOD, buffs: "solo" }, { ...GOOD, buffs: "Own" }, { ...GOOD, buffs: "group+Enchanter" }, { ...GOOD, buffs: "" },
    ];
    for (const choices of bad) expect(() => assembleProfile(bundle, choices), JSON.stringify(choices)).toThrow(BundleError);
  });

  it("throw BundleError for an evidence level the bundle does not have", () => {
    for (const evidence of ["gold", "Strict", "", " wiki", "strict,wiki", 1, true, {}, []]) {
      expect(() => assembleProfile(bundle, { ...GOOD, evidence }), JSON.stringify(evidence)).toThrow(BundleError);
    }
    // no level at all is the fallback, and so is null
    expect(assembleProfile(bundle, { ...GOOD, evidence: undefined })).toEqual(assembleProfile(bundle, GOOD));
    expect(assembleProfile(bundle, { ...GOOD, evidence: null })).toEqual(assembleProfile(bundle, GOOD));
  });

  it("throw BundleError for a name that only an object has (not a race, not a role, not a buff key)", () => {
    for (const name of ["__proto__", "constructor", "prototype", "toString", "hasOwnProperty", "valueOf", "length", "0"]) {
      expect(() => assembleProfile(bundle, { ...GOOD, race: name }), name).toThrow(BundleError);
      expect(() => assembleProfile(bundle, { ...GOOD, role: name }), name).toThrow(BundleError);
      expect(() => assembleProfile(bundle, { ...GOOD, buffs: name }), name).toThrow(BundleError);
      expect(() => assembleProfile(bundle, { ...GOOD, evidence: name }), name).toThrow(BundleError);
    }
  });

  it("throw BundleError for a choice that is missing or not text", () => {
    for (const key of ["race", "role", "buffs"]) {
      expect(() => assembleProfile(bundle, { ...GOOD, [key]: undefined }), key).toThrow(BundleError);
      for (const bad of [null, 5, true, {}, [], ["HUM"], Symbol("x")]) {
        expect(() => assembleProfile(bundle, { ...GOOD, [key]: bad }), `${key} ${String(typeof bad)}`).toThrow(BundleError);
      }
    }
    for (const bad of [undefined, null, "HUM", 5, [GOOD]]) expect(() => assembleProfile(bundle, bad), String(bad)).toThrow(BundleError);
  });

  it("throw BundleError for a choice there is none of (a misspelt evidence would be ignored, and the profile look right)", () => {
    expect(assembleProfile(bundle, { ...GOOD, evidence: "strict" }).evidence).toBe("strict");
    for (const key of ["evidnce", "Evidence", "evidence ", "buff", "Race", "roles", "deities", "level", "trio", "setup", "options", "evidence_level"]) {
      const choices = withKey({ ...GOOD }, key, "strict");
      expect(() => assembleProfile(bundle, choices), JSON.stringify(key)).toThrow(BundleError);
      expect(() => assembleProfile(bundle, choices), JSON.stringify(key)).toThrow(/choice/);
    }
    expect(() => assembleProfile(bundle, { ...GOOD, evidnce: "strict" })).toThrow(/evidnce/);
    expect(() => assembleProfile(bundle, { ...GOOD, evidence: "strict", extra: 1 })).toThrow(/extra/); // a right choice does not excuse a wrong one
    expect(() => assembleProfile(bundle, withKey({ ...GOOD }, "__proto__", "strict"))).toThrow(BundleError);
    expect(() => assembleProfile(bundle, { ...GOOD, [`evil\n${"x".repeat(100)}`]: 1 })).toThrow(/\(\?\)/); // a key that is long is not echoed back
  });

  it("take a deity that is a name, and refuse one that is blank or not text (as Python does)", () => {
    for (const deity of ["Tunare", "Brell Serilis", "x", "﻿", "​", "a b"]) {
      expect(assembleProfile(bundle, { ...GOOD, deity }).deity, deity).toBe(deity);
    }
    // str.strip() in Python takes these for blank: they are refused
    const blank = [
      "", " ", "\t", "\n", "\r", "\u000b", "\u000c", "\u001c", "\u001d", "\u001e", "\u001f", "\u0085", " ", " ",
      " ", " ", " ", " ", " ", " ", " ", " ", " ", " ", " ", " ", " ",
      " ", " ", "　", " \t　 ",
    ];
    for (const deity of blank) expect(() => assembleProfile(bundle, { ...GOOD, deity }), JSON.stringify(deity)).toThrow(BundleError);
    for (const deity of [5, true, {}, [], ["Tunare"], Symbol("x")]) {
      expect(() => assembleProfile(bundle, { ...GOOD, deity }), String(typeof deity)).toThrow(BundleError);
    }
    expect(assembleProfile(bundle, { ...GOOD, deity: null }).deity).toBeNull();
    expect(assembleProfile(bundle, { ...GOOD, deity: undefined }).deity).toBeNull();
  });
});

// ---- bundles that are not what the exporter writes -----------------------------------------------------------------------------

describe("a malformed bundle", () => {
  // a bundle of the sample, changed in place by `change` (what it returns is not used), is refused by both functions; `reason` is
  // a pattern that the message must match, where the kind of fault is what the test is about
  const refused = (name, change, reason = /./) =>
    it(name, () => {
      const bundle = sampleBundle();
      change(bundle);
      expect(() => assembleProfile(bundle, GOOD)).toThrow(BundleError);
      expect(() => readBundle(bundle)).toThrow(reason);
      expect(() => readBundle(bundle)).toThrow(BundleError);
    });

  describe("that is not a document", () => {
    for (const [name, value] of [["null", null], ["a list", []], ["a string", "bundle"], ["a number", 1], ["undefined", undefined], ["a function", () => 1]]) {
      it(`is ${name}`, () => {
        expect(() => assembleProfile(value, GOOD)).toThrow(BundleError);
        expect(() => readBundle(value)).toThrow(BundleError);
      });
    }
  });

  describe("with a field missing", () => {
    for (const key of Object.keys(sampleBundle())) {
      refused(`has no ${key}`, (bundle) => {
        delete bundle[key];
      });
    }
    for (const key of Object.keys(sampleBundle().profile_common)) {
      refused(`has no profile_common.${key}`, (bundle) => {
        delete bundle.profile_common[key];
      });
    }
    refused("has a race with no naked table", (bundle) => {
      delete bundle.races[0].naked;
    });
    refused("has a race with no code", (bundle) => {
      delete bundle.races[3].code;
    });
    refused("has a race with no iksar_ac", (bundle) => {
      delete bundle.races[1].iksar_ac;
    });
    refused("has a role with no weights", (bundle) => {
      delete bundle.roles.tank.weights;
    });
    refused("has a role with no setups", (bundle) => {
      delete bundle.roles.melee.setups;
    });
    refused("has a role with no setups_by_evidence (a bundle made before the field was added)", (bundle) => {
      for (const role of Object.values(bundle.roles)) delete role.setups_by_evidence;
    });
    refused("has a role with no setups at one evidence level", (bundle) => {
      delete bundle.roles.balanced.setups_by_evidence.wiki;
    });
    refused("has a buff set with no totals", (bundle) => {
      delete bundle.buffs.raid.buff_totals;
    });
    refused("has a buff set with no spell_haste", (bundle) => {
      delete bundle.buffs.own.spell_haste;
    });
    refused("has a buff set with no set", (bundle) => {
      delete bundle.buffs.group.set;
    });
    refused("has a constants block with no attributes", (bundle) => {
      delete bundle.constants.attributes;
    });
    refused("has a constants block with no weapon_setups", (bundle) => {
      delete bundle.constants.weapon_setups;
    });
    refused("has a race with a naked table that lacks an attribute", (bundle) => {
      delete bundle.races[0].naked.WIS;
    });
  });

  describe("with a field that the exporter does not write", () => {
    refused("at the top", (bundle) => {
      bundle.notes = { list: [1, 2.5, "text", null, true] };
    }, "bundle has a field (notes) that it should not have");
    refused("at the top, a plain number", (bundle) => {
      bundle.extra = 1;
    }, "(extra)");
    refused("in a race (the first)", (bundle) => {
      bundle.races[0].population = 3;
    }, "bundle.races[0] has a field (population)");
    refused("in a race (the fourth)", (bundle) => {
      bundle.races[3].note = "x";
    }, "bundle.races[3] has a field (note)");
    refused("in a role", (bundle) => {
      bundle.roles.melee.note = "x";
    }, "bundle.roles.melee has a field (note)");
    refused("in every role", (bundle) => {
      for (const role of Object.values(bundle.roles)) role.rank = 1;
    }, "has a field (rank) that it should not have");
    refused("in a buff set", (bundle) => {
      bundle.buffs.group.cost = 0;
    }, "bundle.buffs.group has a field (cost)");
    refused("in the last buff set", (bundle) => {
      bundle.buffs.raid.label = "raid";
    }, "bundle.buffs.raid has a field (label)");
    refused("in an HP pool", (bundle) => {
      bundle.profile_common.pools.HP[1].extra = 1;
    }, "pools.HP[1] has a field (extra)");
    refused("in an END pool", (bundle) => {
      bundle.profile_common.pools.END[0].extra = 1;
    }, "pools.END[0] has a field (extra)");
    refused("in a mana pool", (bundle) => {
      bundle.profile_common.pools.MANA[0].extra = 1;
    }, "pools.MANA[0] has a field (extra)");
    refused("as a stat of an HP pool (only a mana pool has one)", (bundle) => {
      bundle.profile_common.pools.HP[0].stat = "WIS";
    }, "pools.HP[0] has a field (stat)");
    refused("as a stat of an END pool", (bundle) => {
      bundle.profile_common.pools.END[2].stat = "INT";
    }, "pools.END[2] has a field (stat)");
    refused("as a mana pool with no stat (the exporter names the stat of every one)", (bundle) => {
      delete bundle.profile_common.pools.MANA[0].stat;
    }, "pools.MANA[0] has no stat");
    it("does not touch the fields that the exporter writes: the sample reads, and so does every bundle of the full set", () => {
      expect(readBundle(sampleBundle())).toBeDefined();
      const rows = readBundle(sampleBundle());
      expect(Object.keys(rows.races[0])).toEqual(["code", "name", "legal", "naked", "iksar_ac"]);
      expect(Object.keys(rows.roles.tank)).toEqual(["weights", "setups", "setups_by_evidence"]);
      expect(Object.keys(rows.buffs.own)).toEqual(["buff_totals", "spell_haste", "set"]);
      expect(rows.profile_common.pools.MANA[0]).toEqual({ cls: "PAL", base: 900, fac: 4.5, stat: "WIS" });
      if (FULL !== null) {
        for (const path of FULL.paths("profiles").filter((p) => p.endsWith(".bundle.json"))) expect(readBundle(FULL.read(path)), path).toBeDefined();
      }
    });
  });

  describe("with a field of the wrong type", () => {
    const wrong = [
      ["level is text", (b) => (b.level = "50")], ["level is zero", (b) => (b.level = 0)], ["level is not whole", (b) => (b.level = 50.5)],
      ["trio is text", (b) => (b.trio = "PAL-MNK-BER")], ["trio has two classes", (b) => (b.trio = ["PAL", "MNK"])],
      ["trio has a repeated class", (b) => (b.trio = ["PAL", "PAL", "BER"])], ["trio has a number", (b) => (b.trio = ["PAL", "MNK", 3])],
      ["trio is not class codes", (b) => (b.trio = ["pal", "mnk", "ber"])],
      ["data_release is a number", (b) => (b.data_release = 20261014)], ["rules_version is null", (b) => (b.rules_version = null)],
      ["rules_version is empty", (b) => (b.rules_version = "")],
      ["evidence_levels is text", (b) => (b.evidence_levels = "strict")], ["evidence_levels is empty", (b) => (b.evidence_levels = [])],
      ["evidence_levels repeats one", (b) => (b.evidence_levels = ["strict", "strict"])],
      ["races is an object", (b) => (b.races = {})], ["races is empty", (b) => (b.races = [])], ["a race is a string", (b) => (b.races[2] = "HUM")],
      ["a race code is a number", (b) => (b.races[0].code = 7)], ["a race code repeats", (b) => (b.races[1].code = b.races[0].code)],
      ["a race code is empty", (b) => (b.races[0].code = "")], ["a race name is a number", (b) => (b.races[0].name = 7)],
      ["legal is text", (b) => (b.races[0].legal = "yes")],
      ["naked is a list", (b) => (b.races[0].naked = [1, 2, 3])], ["a naked attribute is text", (b) => (b.races[0].naked.STR = "105")],
      ["a naked attribute is null", (b) => (b.races[0].naked.STR = null)], ["naked has an attribute too many", (b) => (b.races[0].naked.LUCK = 5)],
      ["iksar_ac is text", (b) => (b.races[0].iksar_ac = "0")],
      ["roles is a list", (b) => (b.roles = [])], ["roles is empty", (b) => (b.roles = {})], ["a role is not one of the four", (b) => (b.roles.wizard = b.roles.tank)],
      ["a role is null", (b) => (b.roles.tank = null)],
      ["weights is a list", (b) => (b.roles.balanced.weights = [])], ["a weight is text", (b) => (b.roles.balanced.weights.AC = "3.75")],
      ["a weight is negative", (b) => (b.roles.balanced.weights.AC = -1)], ["a weight is null", (b) => (b.roles.balanced.weights.AC = null)],
      ["a weight is true", (b) => (b.roles.balanced.weights.AC = true)], ["a weight has a name no weight has", (b) => (b.roles.balanced.weights.LUCK = 1)],
      ["setups is text", (b) => (b.roles.balanced.setups = "2h")], ["setups holds a number", (b) => (b.roles.balanced.setups = ["2h", 4])],
      ["setups names a setup there is none of", (b) => (b.roles.balanced.setups = ["2h", "bow"])],
      ["setups repeats one", (b) => (b.roles.balanced.setups = ["2h", "2h"])],
      ["setups_by_evidence is a list", (b) => (b.roles.balanced.setups_by_evidence = [])],
      ["setups_by_evidence has a level too many", (b) => (b.roles.balanced.setups_by_evidence.gold = ["2h"])],
      ["setups_by_evidence holds text", (b) => (b.roles.balanced.setups_by_evidence.wiki = "2h")],
      ["setups_by_evidence names a setup there is none of", (b) => (b.roles.balanced.setups_by_evidence.wiki = ["bow"])],
      ["buffs is a list", (b) => (b.buffs = [])], ["buffs is empty", (b) => (b.buffs = {})], ["a buff set is a number", (b) => (b.buffs.own = 3)],
      ["buff_totals is a list", (b) => (b.buffs.own.buff_totals = [])], ["a buff total is text", (b) => (b.buffs.own.buff_totals.AC = "160")],
      ["a buff total has a name there is none of", (b) => (b.buffs.own.buff_totals.LUCK = 1)],
      ["the SV total is a number", (b) => (b.buffs.own.buff_totals.SV = 20)], ["the SV total has a school there is none of", (b) => (b.buffs.own.buff_totals.SV.ACID = 20)],
      ["spell_haste is null", (b) => (b.buffs.own.spell_haste = null)], ["spell_haste is negative", (b) => (b.buffs.own.spell_haste = -5)],
      ["the buff set is a list", (b) => (b.buffs.own.set = [])], ["the buff set lacks a part", (b) => delete b.buffs.own.set.cliques],
      ["the buff set holds text for a list", (b) => (b.buffs.own.set.always_on = "19")],
      ["profile_common is a list", (b) => (b.profile_common = [])], ["profile_common has a field too many", (b) => (b.profile_common.race = "HUM")],
      ["profile_common.format is 2", (b) => (b.profile_common.format = 2)], ["profile_common.trio is not the trio", (b) => (b.profile_common.trio = ["PAL", "MNK", "WAR"])],
      ["profile_common.level is not the level", (b) => (b.profile_common.level = 51)],
      ["profile_common.evidence is not a level", (b) => (b.profile_common.evidence = "gold")],
      ["aa is a list", (b) => (b.profile_common.aa = [3, true])], ["aa has a rank of text", (b) => (b.profile_common.aa.combat_stability = "3")],
      ["aa has a negative rank", (b) => (b.profile_common.aa.combat_stability = -1)],
      ["aa has an enhancement of text", (b) => (b.profile_common.aa.physical_enhancement = "yes")],
      ["haste_cap is text", (b) => (b.profile_common.haste_cap = "85")], ["cs_pct is null", (b) => (b.profile_common.cs_pct = null)],
      ["softcap has three numbers", (b) => (b.profile_common.softcap = [392, 0.33, 1])], ["softcap is a number", (b) => (b.profile_common.softcap = 392)],
      ["monk is a number", (b) => (b.profile_common.monk = 5)], ["monk holds text", (b) => (b.profile_common.monk.full_bonus_ac = "73")],
      ["placement is text", (b) => (b.profile_common.placement = "top")], ["placement holds a place there is none of", (b) => (b.profile_common.placement.monk = "beside")],
      ["pools is a list", (b) => (b.profile_common.pools = [])], ["pools lacks a family", (b) => delete b.profile_common.pools.END],
      ["a pool family is an object", (b) => (b.profile_common.pools.HP = {})], ["a pool has no class", (b) => delete b.profile_common.pools.HP[0].cls],
      ["a pool has a base of text", (b) => (b.profile_common.pools.HP[0].base = "1440")],
      ["a pool has a fac of null", (b) => (b.profile_common.pools.HP[0].fac = null)],
      ["caps is a list", (b) => (b.profile_common.caps = [])], ["caps lacks the resist cap", (b) => delete b.profile_common.caps.resist],
      ["caps regen lacks a family", (b) => delete b.profile_common.caps.regen.MANA], ["a regen cap is text", (b) => (b.profile_common.caps.regen.HP = "30")],
      ["bands is a number", (b) => (b.profile_common.bands = 1)], ["bands lacks the slopes", (b) => delete b.profile_common.bands.slopes],
      ["dw_factor is text", (b) => (b.profile_common.dw_factor = "0.8")],
      ["deity is a number", (b) => (b.profile_common.deity = 5)], ["deity is blank", (b) => (b.profile_common.deity = "  ")],
      ["constants is a list", (b) => (b.constants = [])], ["constants.attributes holds a number", (b) => (b.constants.attributes = ["STR", 5])],
      ["constants.weapon_setups is empty", (b) => (b.constants.weapon_setups = [])],
      ["tier_rules is null", (b) => (b.tier_rules = null)], ["weapon_rules is a list", (b) => (b.weapon_rules = [])],
      ["weight_groups is text", (b) => (b.weight_groups = "groups")], ["regen_ratios is a number", (b) => (b.regen_ratios = 3)],
      ["monk_bins is a list", (b) => (b.monk_bins = [])], ["buff_table is a list", (b) => (b.buff_table = [])],
    ];
    for (const [name, change] of wrong) {
      refused(name, (bundle) => {
        change(bundle);
      });
    }
  });

  describe("with an empty list of setups", () => {
    refused("for a role", (bundle) => {
      bundle.roles.balanced.setups = [];
    }, /roles\.balanced\.setups must not be empty/);
    refused("for a role at an evidence level", (bundle) => {
      bundle.roles.tank.setups_by_evidence.strict = [];
    }, /roles\.tank\.setups_by_evidence\.strict must not be empty/);
    refused("for every role at every level", (bundle) => {
      for (const role of Object.values(bundle.roles)) {
        role.setups = [];
        for (const level of Object.keys(role.setups_by_evidence)) role.setups_by_evidence[level] = [];
      }
    }, /must not be empty/);
  });

  describe("with an unknown name where the bundle names one", () => {
    refused("the evidence of profile_common is not a level of the bundle", (bundle) => {
      bundle.profile_common.evidence = "silver";
    });
    refused("an evidence level that has no setups", (bundle) => {
      bundle.evidence_levels = ["strict", "wiki", "silver"];
    });
    refused("an evidence level that the roles do not have", (bundle) => {
      bundle.evidence_levels = ["strict"];
    });
  });

  describe("with a key that could poison a lookup", () => {
    for (const key of ["__proto__", "constructor", "prototype"]) {
      refused(`${key} at the top`, (bundle) => withKey(bundle, key, 1), /poison/);
      refused(`${key} in profile_common`, (bundle) => withKey(bundle.profile_common, key, {}), /poison/);
      refused(`${key} among the weights`, (bundle) => withKey(bundle.roles.balanced.weights, key, 1), /poison/);
      refused(`${key} for a role`, (bundle) => withKey(bundle.roles, key, bundle.roles.balanced), /poison/);
      refused(`${key} in a race`, (bundle) => withKey(bundle.races[0], key, "HUM"), /poison/);
      refused(`${key} among the buff keys`, (bundle) => withKey(bundle.buffs, key, bundle.buffs.own), /poison/);
      refused(`${key} among the buff ids`, (bundle) => withKey(bundle.buff_table, key, { name: "x" }), /poison/);
      refused(`${key} deep in the constants`, (bundle) => withKey(bundle.constants.softcap_rows.PAL, key, 1), /poison/);
      refused(`${key} in the item rules`, (bundle) => withKey(bundle.tier_rules.arrival, key, "0/1"), /poison/);
      refused(`${key} among the setups by evidence`, (bundle) => withKey(bundle.roles.tank.setups_by_evidence, key, ["2h"]), /poison/);
      refused(`${key} as a key in a nested list`, (bundle) => {
        bundle.buffs.own.set.conflicts.push([withKey({}, key, 1)]);
      }, /poison/);
    }
  });

  describe("with a name that could poison a lookup in a list of names", () => {
    // the names of these lists become the keys of objects downstream (weightsOverride writes out[key]; out["__proto__"] = 1 drops the weight)
    for (const name of ["__proto__", "constructor", "prototype"]) {
      for (const [where, put] of [
        ["the attributes", (b) => (b.constants.attributes = [...b.constants.attributes, name])],
        ["the schools", (b) => (b.constants.schools = [...b.constants.schools, name])],
        ["the weight keys", (b) => (b.constants.weight_keys = [...b.constants.weight_keys, name])],
        ["the buff total keys", (b) => (b.constants.buff_total_keys = [...b.constants.buff_total_keys, name])],
        ["the weapon setups", (b) => (b.constants.weapon_setups = [...b.constants.weapon_setups, name])],
        ["the evidence levels", (b) => (b.evidence_levels = [...b.evidence_levels, name])],
        ["the only weight key", (b) => (b.constants.weight_keys = [name])],
      ]) {
        refused(`${name} among ${where}`, (bundle) => put(bundle), /poison/);
      }
      refused(`${name} among the setups of a role`, (bundle) => {
        bundle.roles.balanced.setups = [...bundle.roles.balanced.setups, name];
      });
      refused(`${name} among the setups of a role at an evidence level`, (bundle) => {
        bundle.roles.tank.setups_by_evidence.strict = [name];
      });
    }
  });

  describe("with a number that is not finite or not exact", () => {
    for (const [name, value] of [["NaN", NaN], ["Infinity", Infinity], ["-Infinity", -Infinity], ["a whole number past 2^53", 2 ** 60], ["1e300", 1e300], ["-1e300", -1e300]]) {
      refused(`${name} in profile_common`, (bundle) => {
        bundle.profile_common.cs_pct = value;
      }, /finite|exactly/);
      refused(`${name} among the weights`, (bundle) => {
        bundle.roles.tank.weights.HP = value;
      }, /finite|exactly/);
      refused(`${name} among the naked attributes`, (bundle) => {
        bundle.races[0].naked.STR = value;
      }, /finite|exactly/);
      refused(`${name} among the buff totals`, (bundle) => {
        bundle.buffs.own.buff_totals.AC = value;
      }, /finite|exactly/);
      refused(`${name} in the level`, (bundle) => {
        bundle.level = value;
      }, /finite|exactly/);
      refused(`${name} anywhere else (an extra block)`, (bundle) => {
        bundle.notes = { list: [1, 2, value] };
      }, /finite|exactly/);
    }
  });

  describe("with a buff in the table that is not whole numbers", () => {
    // The always-on buffs of a set are added up here in exact numbers, and in Python as floats (0.1 + 0.2 is 0.30000000000000004): the two agree for
    // whole numbers, which is all the client files give, so the table takes whole numbers and nothing else.
    const first = (bundle) => Object.values(bundle.buff_table)[0];
    for (const [name, value] of [["a fraction", 12.5], ["a tenth", 0.1], ["a tiny fraction", 1e-7], ["a negative fraction", -0.5], ["a fraction next to a whole number", 2.0000001]]) {
      refused(`has ${name} in a component`, (bundle) => {
        first(bundle).vec.STR = value;
      }, /bundle\.buff_table\.[0-9]+\.vec\.STR must be a whole number/);
    }
    for (const [name, value] of [["text", "5"], ["null", null], ["true", true], ["a list", [5]], ["an object", { value: 5 }]]) {
      refused(`has ${name} in a component`, (bundle) => {
        first(bundle).vec.HP = value;
      }, /bundle\.buff_table\.[0-9]+\.vec\.HP must be a whole number/);
    }
    refused("has a component that no buff has", (bundle) => {
      first(bundle).vec.LUCK = 5;
    }, /vec has a component \(LUCK\) that there is none of/);
    refused("has an entry with no vec", (bundle) => {
      delete first(bundle).vec;
    }, /\.vec must be an object/);
    refused("has an entry whose vec is a list", (bundle) => {
      first(bundle).vec = [5, 3];
    }, /\.vec must be an object/);
    refused("has an entry that is a number", (bundle) => {
      bundle.buff_table["999999"] = 3;
    }, /bundle\.buff_table\.999999 must be an object/);
    refused("has an entry that is null", (bundle) => {
      bundle.buff_table["999999"] = null;
    }, /bundle\.buff_table\.999999 must be an object/);
    it("takes the table as the exporter writes it: whole numbers, positive and negative, by the components of the bundle", () => {
      const bundle = sampleBundle();
      const entries = Object.values(bundle.buff_table);
      const components = new Set(bundle.constants.buff_components);
      expect(entries.length).toBeGreaterThan(20);
      for (const entry of entries) {
        for (const [component, amount] of Object.entries(entry.vec)) {
          expect(components.has(component), component).toBe(true);
          expect(Number.isInteger(amount), `${component} ${amount}`).toBe(true);
        }
      }
      expect(entries.some((entry) => Object.values(entry.vec).some((amount) => amount < 0))).toBe(true);
      expect(() => readBundle(bundle)).not.toThrow();
    });
  });

  describe("with a rational that is not a reduced p/q", () => {
    const places = [
      ["regen_ratios.ticks_per_minute", (b, text) => (b.regen_ratios.ticks_per_minute = text)],
      ["regen_ratios.match", (b, text) => (b.regen_ratios.match = text)],
      ["constants.stat_knee", (b, text) => (b.constants.stat_knee = text)],
      ["constants.sheet.item_mult", (b, text) => (b.constants.sheet.item_mult = text)],
      ["constants.softcap_rows.PAL.cap", (b, text) => (b.constants.softcap_rows.PAL.cap = text)],
      ["constants.slot_groups[0][1]", (b, text) => (b.constants.slot_groups[0][1] = text)],
      ["tier_rules.max_tier", (b, text) => (b.tier_rules.max_tier = text)],
      ["tier_rules.arrival.quest", (b, text) => (b.tier_rules.arrival.quest = text)],
      ["weapon_rules.damage_pct_choices[1]", (b, text) => (b.weapon_rules.damage_pct_choices[1] = text)],
      ["weight_groups.multipliers[0]", (b, text) => (b.weight_groups.multipliers[0] = text)],
      ["weight_groups.custom_max", (b, text) => (b.weight_groups.custom_max = text)],
      ["monk_bins.bonus[3]", (b, text) => (b.monk_bins.bonus[3] = text)],
      ["monk_bins.curve.softcap_stones", (b, text) => (b.monk_bins.curve.softcap_stones = text)],
    ];
    for (const [where, put] of places) {
      for (const [what, text] of [["a zero denominator", "5/0"], ["0/0", "0/0"], ["not in lowest terms", "4/6"], ["a plus sign", "+1/2"], ["a decimal", "1.5/2"], ["a negative denominator", "1/-2"], ["a double slash", "1//2"], ["a leading zero", "01/2"]]) {
        refused(`${what} at ${where}`, (bundle) => put(bundle, text), /reduced rational p\/q/);
      }
      refused(`a bare number at ${where}`, (bundle) => put(bundle, 5), /bare number/);
      refused(`a float at ${where}`, (bundle) => put(bundle, 0.5), /bare number/);
    }
    it("leaves the text of a rule that is not a number alone", () => {
      const bundle = sampleBundle();
      bundle.tier_rules.exp_needed = "2^N - 1";
      bundle.weapon_rules.label = "Weapon damage per tier";
      expect(assembleProfile(bundle, GOOD).race).toBe("HUM");
    });
  });

  describe("of another version", () => {
    for (const version of [0, 2, 1.5, "1", null, true, [1], {}, -1, 1e9]) {
      refused(`says ${JSON.stringify(version)}`, (bundle) => {
        bundle.version = version;
      }, /bundle\.version is another version/);
    }
    it("says which version this reader takes", () => {
      const bundle = sampleBundle();
      bundle.version = 2;
      expect(() => assembleProfile(bundle, GOOD)).toThrow(/version/);
    });
    refused("has no version", (bundle) => {
      delete bundle.version;
    }, /bundle\.version is missing/);
  });

  describe("that is not plain data", () => {
    class Odd {
      constructor() {
        this.x = 1;
      }
    }
    refused("holds an undefined", (bundle) => {
      bundle.races[0].legal = undefined;
    });
    refused("holds a function", (bundle) => {
      bundle.races[0].name = () => "Human";
    });
    refused("holds a BigInt", (bundle) => {
      bundle.level = 50n;
    });
    refused("holds a symbol", (bundle) => {
      bundle.races[0].name = Symbol("Human");
    });
    refused("holds a date", (bundle) => {
      bundle.notes = new Date(0);
    });
    refused("holds a map", (bundle) => {
      bundle.notes = new Map([["a", 1]]);
    });
    refused("holds an object of a class", (bundle) => {
      bundle.notes = new Odd();
    });
    refused("holds a getter", (bundle) => {
      Object.defineProperty(bundle.profile_common, "cs_pct", { get: () => 10, enumerable: true, configurable: true });
    });
    refused("holds a property that is not enumerable", (bundle) => {
      Object.defineProperty(bundle, "hidden", { value: 1, enumerable: false });
    });
    refused("has a symbol for a key", (bundle) => {
      bundle[Symbol("key")] = 1;
    });
    refused("holds a list with a hole", (bundle) => {
      // eslint-disable-next-line no-sparse-arrays
      bundle.notes = [1, , 3];
    });
    refused("holds a typed array", (bundle) => {
      bundle.notes = new Uint8Array(4);
    });
    refused("loops back on itself", (bundle) => {
      bundle.constants.again = bundle.constants;
    });
    refused("is nested without end", (bundle) => {
      let deep = {};
      for (let i = 0; i < 100_000; i += 1) deep = { deeper: deep };
      bundle.notes = deep;
    });
    refused("is nested in lists without end", (bundle) => {
      let deep = [];
      for (let i = 0; i < 100_000; i += 1) deep = [deep];
      bundle.notes = deep;
    });
    refused("is huge", (bundle) => {
      bundle.notes = new Array(300_000).fill(1);
    });
    refused("holds a text that is huge", (bundle) => {
      bundle.notes = "x".repeat(2_000_000);
    });
  });

  it("is refused with a message that says where, and without the content of the bundle", () => {
    const bundle = sampleBundle();
    bundle.roles.balanced.setups = [];
    let caught;
    try {
      assembleProfile(bundle, GOOD);
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(BundleError);
    expect(caught).toBeInstanceOf(Error);
    expect(caught.name).toBe("BundleError");
    expect(caught.message).toMatch(/roles\.balanced\.setups/);
    // a key the bundle holds is not echoed back whole when it is odd
    const odd = sampleBundle();
    withKey(odd.roles, `evil-${"x".repeat(500)}\u0000`, odd.roles.balanced);
    let oddError;
    try {
      readBundle(odd);
    } catch (error) {
      oddError = error;
    }
    expect(oddError).toBeInstanceOf(BundleError);
    expect(oddError.message.length).toBeLessThan(300);
    expect(oddError.message).not.toContain("\u0000");
  });

  it("refuses a bundle with an extra block however plain it is (a bundle that the exporter would not write is a BundleError)", () => {
    const bundle = sampleBundle();
    bundle.notes = { list: [1, 2.5, "text", null, true], nested: { a: { b: {} } } };
    expect(() => readBundle(bundle)).toThrow(BundleError);
    expect(() => assembleProfile(bundle, GOOD)).toThrow(/notes/);
  });
});

// ---- reading a bundle -----------------------------------------------------------------------------------------------------

describe("reading a bundle", () => {
  it("gives a deep-frozen copy that equals the bundle", () => {
    const raw = sampleBundle();
    const read = readBundle(raw);
    expect(read).toEqual(raw);
    expect(read).not.toBe(raw);
    expect(isDeepFrozen(read)).toBe(true);
    expect(Object.isFrozen(raw)).toBe(false);
  });

  it("gives the same object back for a bundle it has read", () => {
    const read = readBundle(sampleBundle());
    expect(readBundle(read)).toBe(read);
  });

  it("does not trust a frozen object that it did not make", () => {
    const raw = sampleBundle();
    const frozen = Object.freeze(raw);
    const read = readBundle(frozen);
    expect(read).not.toBe(frozen);
    const again = Object.freeze(sampleBundle());
    again.races[0].naked.STR = "oops"; // a frozen top object with a part that is still open
    expect(() => readBundle(again)).toThrow(BundleError);
  });

  it("copies every part, so changing the original afterwards changes nothing", () => {
    const raw = sampleBundle();
    const read = readBundle(raw);
    const before = JSON.stringify(read);
    raw.roles.balanced.setups.push("stick");
    raw.constants.attributes.length = 0;
    raw.races.length = 0;
    expect(JSON.stringify(read)).toBe(before);
  });

  it("reads the six bundles of the full set (when it is there) and the sample", () => {
    expect(readBundle(SAMPLE.read(BUNDLE)).trio).toEqual(["PAL", "MNK", "BER"]);
    if (FULL !== null) {
      for (const path of FULL.paths("profiles").filter((p) => p.endsWith(".profiles.json"))) {
        const listing = FULL.read(path);
        const read = readBundle(FULL.read(`profiles/${listing.bundle}`));
        expect(read.trio).toEqual(listing.trio);
        expect(read.level).toBe(listing.level);
      }
    }
  });
});

// ---- the cost of reading a bundle ----------------------------------------------------------------------------------------------

describe("the cost of reading a bundle", () => {
  // Every exact number of a bundle is a "p/q" text, and reading one costs a reduction (Euclid's algorithm on BigInts, about the square of its
  // digits). A bundle of 400 texts of 4,096 digits (3.3 MB) used to stall the reader for 24 s; now a text is held to 64 digits, a bundle to
  // 2,500 texts, and the answer, a bundle or a refusal, comes in well under a second whatever a document within the limits holds.
  const SECOND = 1000;
  const SAMPLE_TEXTS = 385; // the p/q texts of the bundle of the sample, of which 137 are the bins of the Monk curve

  /** Consecutive Fibonacci numbers are the worst case for Euclid's algorithm: a text of that many digits that is in lowest terms. */
  function fibonacciText(digits) {
    let a = 1n;
    let b = 1n;
    while (b.toString().length < digits) [a, b] = [b, a + b];
    return `${b}/${a}`;
  }

  /** The time a read takes, and what became of it. With `load`, the time is a Timing: it has the load factors measured around the read (some 100 ms more when the machine is idle). */
  function timed(raw, { load = false } = {}) {
    const watch = load ? stopwatch() : null;
    const started = performance.now();
    let outcome;
    try {
      outcome = { read: readBundle(raw) };
    } catch (error) {
      outcome = { error };
    }
    const ms = performance.now() - started;
    return { ...outcome, ms: watch === null ? ms : watch.stop(ms) };
  }

  /** The sample with the bins of the Monk curve replaced by the given list. */
  function withBins(bins) {
    const raw = sampleBundle();
    raw.monk_bins.bonus = bins;
    return raw;
  }

  it("refuses 400 texts of 4,096 digits at once (a bundle of 3.3 MB that took 24 s)", () => {
    const text = fibonacciText(4096);
    const raw = withBins(new Array(400).fill(text));
    expect(JSON.stringify(raw).length).toBeGreaterThan(3_000_000);
    const { error, ms } = timed(raw, { load: true });
    expect(error).toBeInstanceOf(BundleError);
    expect(error.message).toMatch(/reduced rational p\/q/);
    expectWithin(ms, SECOND, "400 texts of 4,096 digits are refused");
  });

  it("refuses a text of 65 digits in the numerator or in the denominator, and reads a bundle of texts of 64", () => {
    const longest = fibonacciText(64);
    expect(timed(withBins(new Array(100).fill(longest))).read).toBeDefined();
    const [p, q] = longest.split("/");
    for (const text of [`1${p}/${q}`, `${p}/1${q}`, `${"1".padEnd(65, "0")}/7`, `1/${"7".repeat(65)}`]) {
      const { error, read } = timed(withBins([text]));
      expect(read, text.slice(0, 20)).toBeUndefined();
      expect(error).toBeInstanceOf(BundleError);
    }
  });

  it("refuses a pool number of 4,096 digits at once, and reads one of 64", () => {
    const refused = sampleBundle();
    refused.profile_common.pools.HP[0].base = fibonacciText(4096);
    const { error, ms } = timed(refused, { load: true });
    expect(error).toBeInstanceOf(BundleError);
    expect(error.message).toMatch(/pools\.HP\[0\]\.base/);
    expectWithin(ms, SECOND, "a pool number of 4,096 digits is refused");
    const taken = sampleBundle();
    taken.profile_common.pools.HP[0].base = fibonacciText(64);
    expect(readBundle(taken).profile_common.pools.HP[0].base).toBe(taken.profile_common.pools.HP[0].base);
  });

  it("reads the most texts it takes, each of the most digits (the worst case it takes), in well under a second", () => {
    const raw = withBins(new Array(2000).fill(fibonacciText(64))); // 2,000 + 248 of the sample: 2,248 of the 2,500
    const { read, error, ms } = timed(raw, { load: true });
    expect(error).toBeUndefined();
    expect(read.monk_bins.bonus).toHaveLength(2000);
    expectWithin(ms, SECOND, "the most texts it takes, each of the most digits, are read"); // about 0.1 s on the machine this was measured on
  });

  it("refuses more texts than that, and a document of 90,000 of them (the most a document may hold) at once", () => {
    const over = timed(withBins(new Array(2400).fill("1/3"))); // 248 + 2,400 = 2,648 texts
    expect(over.error).toBeInstanceOf(BundleError);
    expect(over.error.message).toMatch(/at most 2500/);
    expect(over.error.message).toMatch(/monk_bins\.bonus/);
    const most = timed(withBins(new Array(90_000).fill(fibonacciText(64))), { load: true });
    expect(most.error).toBeInstanceOf(BundleError);
    expect(most.error.message).toMatch(/at most 2500/);
    expectWithin(most.ms, SECOND, "90,000 texts of 64 digits are refused");
    const shorts = timed(withBins(new Array(90_000).fill("1/2")), { load: true });
    expect(shorts.error).toBeInstanceOf(BundleError);
    expectWithin(shorts.ms, SECOND, "90,000 short texts are refused");
  });

  it("counts the pool numbers among the texts", () => {
    const raw = withBins(new Array(2500 - (SAMPLE_TEXTS - 137)).fill("1/3")); // exactly 2,500 texts
    expect(timed(raw).read).toBeDefined();
    raw.profile_common.pools.HP[0].base = "1/3"; // and one more, in a pool
    const { error } = timed(raw);
    expect(error).toBeInstanceOf(BundleError);
    expect(error.message).toMatch(/at most 2500/);
  });

  it("refuses a document of texts that are as long as a text may be and made of digits and slashes, at once", () => {
    const long = `${"1".repeat(9_998)}/1`;
    const { error, ms } = timed(withBins(new Array(90_000).fill(long)), { load: true });
    expect(error).toBeInstanceOf(BundleError);
    expectWithin(ms, SECOND, "90,000 texts as long as a text may be are refused");
  });

  it("refuses a text of an exact block that begins like a number too long to be one, wherever it ends; it leaves other texts alone", () => {
    const raw = sampleBundle();
    raw.tier_rules.note = `${"1".repeat(100)}/${"1".repeat(50)} apples`;
    expect(timed(raw).error).toBeInstanceOf(BundleError);
    const plain = sampleBundle();
    plain.tier_rules.note = `${"a".repeat(300)}/${"1".repeat(300)}`;
    plain.weapon_rules.note = "2/3 of a stone, or 1/2 of that";
    expect(timed(plain).read).toBeDefined();
  });
});

describe("the fingerprint of the inputs", () => {
  // The precompute writes, in the bundle of each trio and in the item table of the folder, a fingerprint of what they were made from (the catalog and the evidence
  // level of every item once the flags are merged); the build holds the two to each other, and so does the worker. A bundle without one (the exporter's own,
  // written by the command) is a bundle all the same.
  const FINGERPRINT = "fedcba9876543210".repeat(4);

  it("is an optional top-level field of the bundle: 64 lower-case hexadecimal digits, kept in the bundle that is read, and nothing of it in the profiles", () => {
    expect(readBundle(sampleBundle()).inputs).toBeUndefined();
    const raw = sampleBundle();
    raw.inputs = FINGERPRINT;
    const read = readBundle(raw);
    expect(read.inputs).toBe(FINGERPRINT);
    expect(Object.isFrozen(read)).toBe(true);
    expect(Object.keys(assembleProfile(read, GOOD))).not.toContain("inputs");
    expect(assembleProfile(read, GOOD)).toEqual(assembleProfile(readBundle(sampleBundle()), GOOD));
  });

  it("is refused when it is anything else", () => {
    for (const inputs of ["", FINGERPRINT.toUpperCase(), FINGERPRINT.slice(1), `${FINGERPRINT}0`, `g${FINGERPRINT.slice(1)}`, 5, null, true, [FINGERPRINT], { sha: FINGERPRINT }]) {
      const raw = sampleBundle();
      raw.inputs = inputs;
      expect(() => readBundle(raw), JSON.stringify(inputs)).toThrow(BundleError);
    }
  });
});
