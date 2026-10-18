// The browser engine's own readers, run on the data files that the site build is about to publish (site/build.py, check_engine_data). The build reads the item table
// and the bundles with its own reader (site/data.py) and holds them to the limits of the engine's; this script is the other half: it asks the engine itself.
//
//   * the item table: readItemTable (items.js), and then atTier at every tier from 0 to 10 for every record, under the rules of the first bundle that is read;
//   * each bundle: readBundle (profile.js), the compilation of its tier and weapon rules (checkTierRules), and assembleProfile for every race, role, buff set and
//     evidence level that the bundle lists. The tier and weapon rules of all the bundles must be the same: the item table is worked out under one set.
//
// It reads one JSON document from the standard input, `{items: {name, text}, bundles: [{name, text}]}` (the names are those of the results: `items.json`,
// `pal-mnk-ber/engine-l50.json`; the texts are the files as they will be published), and writes one JSON document to the standard output,
// `{problems: [{file, record, message}], more, checked: {records, tiers, bundles, profiles}}`: a refusal names the file and, when it is about one, the record
// (an item key, or the race, role, buff set and evidence level of a profile). It exits with a status other than 0 only if it cannot do its work. It reads nothing else and
// writes nothing.

import { readFileSync } from "node:fs";
import { atTier, checkTierRules, readItemTable } from "./static/engine/items.js";
import { assembleProfile, readBundle } from "./static/engine/profile.js";

const MAX_TIER = 10;
const MAX_PROBLEMS = 20;

const input = JSON.parse(readFileSync(0, "utf8"));
const problems = [];
let more = 0;
const checked = { records: 0, tiers: MAX_TIER + 1, bundles: 0, profiles: 0 };

const note = (file, record, message) => {
  if (problems.length < MAX_PROBLEMS) problems.push({ file, record, message });
  else more += 1;
};
/** What an error says, on one line and not too long: a message of the engine names the part, never the file. */
const said = (error) => String(error?.message ?? error).replace(/\s+/g, " ").slice(0, 300);

let rules = null; // the first bundle that was read: the item table is worked out under its tier and weapon rules
let rulesText = null;

for (const { name, text } of input.bundles) {
  let bundle;
  try {
    bundle = readBundle(JSON.parse(text));
  } catch (error) {
    note(name, null, said(error));
    continue;
  }
  try {
    checkTierRules(bundle);
  } catch (error) {
    note(name, null, `the tier or weapon rules cannot be used: ${said(error)}`);
    continue;
  }
  const mine = JSON.stringify([bundle.tier_rules, bundle.weapon_rules]);
  if (rules === null) {
    rules = bundle;
    rulesText = mine;
  } else if (mine !== rulesText) {
    note(name, null, "has tier or weapon rules that differ from the first bundle's: the item table is worked out under one set");
    continue;
  }
  checked.bundles += 1;
  for (const race of bundle.races) {
    for (const role of Object.keys(bundle.roles)) {
      for (const buffs of Object.keys(bundle.buffs)) {
        for (const evidence of bundle.evidence_levels) {
          checked.profiles += 1;
          try {
            assembleProfile(bundle, { race: race.code, role, buffs, evidence });
          } catch (error) {
            note(name, `${race.code} ${role} ${buffs} ${evidence}`, said(error));
          }
        }
      }
    }
  }
}

let table = null;
try {
  const document = JSON.parse(input.items.text);
  try {
    table = readItemTable(document);
  } catch (error) {
    // the reader counts the records (record 12 is the twelfth); the build names the item
    const found = /record (\d+)/.exec(String(error?.message));
    const raw = found === null || !Array.isArray(document?.items) ? undefined : document.items[Number(found[1]) - 1];
    const key = raw !== null && typeof raw === "object" ? (raw.key ?? (typeof raw.id === "number" ? `w${raw.id}` : null)) : null;
    note(input.items.name, typeof key === "string" ? key : null, said(error));
  }
} catch (error) {
  note(input.items.name, null, said(error));
}
if (table !== null && rules === null) {
  note(input.items.name, null, "cannot be worked out at any tier: no bundle could be read, and the rules of the tiers are in the bundles");
}
if (table !== null && rules !== null) {
  for (const [key, record] of table.records) {
    checked.records += 1;
    for (let tier = 0; tier <= MAX_TIER; tier += 1) {
      try {
        atTier(record, tier, rules);
      } catch (error) {
        note(input.items.name, key, `at +${tier}: ${said(error)}`);
        break; // the first tier that fails is the one that is told
      }
    }
  }
}

process.stdout.write(`${JSON.stringify({ problems, more, checked })}\n`);
