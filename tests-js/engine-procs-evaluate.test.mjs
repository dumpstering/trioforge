// The weapon term with a table of procs (engine/evaluate.js, procs.js): what pipeline/tests/test_procs_model.py and test_procs_lore.py hold the Python evaluator to, on the items of the fixture
// trio. A proc adds DMG x its value / 600 to the weapon part of the hand that swings it, with no haste factor; a Lore item that the kit wears anywhere is no donor for a hand it is not in.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { SLOT_INSTANCES, evaluate, evaluateTruthful } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { atTier } from "../pipeline/trioforge/site/static/engine/items.js";
import { readProcs } from "../pipeline/trioforge/site/static/engine/procs.js";
import { assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const RESULTS = resolve(HERE, "../fixtures/site/results");
const bundle = readBundle(JSON.parse(readFileSync(resolve(RESULTS, "pal-mnk-ber/engine-l50.json"), "utf8")));
const records = new Map(JSON.parse(readFileSync(resolve(RESULTS, "items.json"), "utf8")).items.map((record) => [record.key ?? `w${record.id}`, record]));
const profile = assembleProfile(bundle, { race: "OGR", role: "tank", buffs: "own", evidence: "wiki" });
const TRIO = ["PAL", "MNK", "BER"];
const PRIMARY = SLOT_INSTANCES.indexOf("PRIMARY");
const SECONDARY = SLOT_INSTANCES.indexOf("SECONDARY");
const ANY = SLOT_INSTANCES.indexOf("ANY");
const item = (key, tier = 4) => atTier(records.get(key), tier, bundle);
const kitOf = (placed) => SLOT_INSTANCES.map((_, place) => placed[place] ?? null);

const doc = (donors, effects = [["e0", "Ember Brand", "900/1"]]) => ({ socket_tier: 4, effects, donors });
const BOTH = ["PRIMARY", "SECONDARY"];
const donor = (key, lore, effect = "e0") => [effect, key, BOTH, TRIO, 0, lore ? 1 : 0];
const DMG = profile.weights.DMG;
const BINS = bundle.monk_bins;
const worth = (value) => new Rational(BigInt(value.split("/")[0]), BigInt(value.split("/")[1] ?? "1"));
const procPart = (value, share = Rational.parse("1/1")) => Rational.fromNumber(DMG).mul(worth(value)).mul(share).div(new Rational(600n));

describe("the weapon term with procs", () => {
  const host = item("w80988"); // a one-hander at the socket tier
  const base = evaluate(profile, kitOf({ [PRIMARY]: host }), null, { setup: "1h-shield", monkBins: BINS });

  it("adds DMG x the proc a hand counts over 600 to the part WEAPON of the hand that swings it, and says which proc in the totals", () => {
    const table = readProcs(doc([donor("w80988", false)]), TRIO);
    const found = evaluate(profile, kitOf({ [PRIMARY]: host }), null, { setup: "1h-shield", monkBins: BINS, procs: table });
    expect(found.breakdown.parts.WEAPON.sub(base.breakdown.parts.WEAPON).toString()).toBe(procPart("900/1").toString());
    expect(found.F.sub(base.F).toString()).toBe(procPart("900/1").toString());
    const counted = found.breakdown.totals.procs;
    expect(counted.PRIMARY).toMatchObject({ effect: "e0", donor: "w80988", mode: "n" });
    expect(counted.SECONDARY).toBeNull();
    expect(counted.part.toString()).toBe(procPart("900/1").toString());
    expect(base.breakdown.totals.procs).toBeUndefined(); // (no table: what it was)
  });

  it("is what it was for a build whose damage weight is 0 and for the stick: no proc", () => {
    const table = readProcs(doc([donor("w80988", false)]), TRIO);
    const stick = evaluate(profile, kitOf({ [PRIMARY]: host }), null, { setup: "stick", monkBins: BINS, procs: table });
    expect(stick.F.toString()).toBe(evaluate(profile, kitOf({ [PRIMARY]: host }), null, { setup: "stick", monkBins: BINS }).F.toString());
    expect(stick.breakdown.totals.procs.PRIMARY).toBeNull();
  });

  it("has no haste factor: the truthful value scales the swing's share of WEAPON with the haste and leaves the proc's share as it is", () => {
    const table = readProcs(doc([donor("w80988", false)]), TRIO);
    const gear = item("w90008"); // a hoop of haste
    const kit = kitOf({ [PRIMARY]: host, 2: gear });
    const plain = evaluateTruthful(profile, kit, null, { setup: "1h-shield", monkBins: BINS });
    const withProc = evaluateTruthful(profile, kit, null, { setup: "1h-shield", monkBins: BINS, procs: table });
    expect(withProc.F.sub(plain.F).toString()).toBe(procPart("900/1").toString());
    const counted = withProc.breakdown.totals.haste.counted;
    expect(counted.sign()).toBeGreaterThan(0);
    // the same value as the evaluator at the haste the kit counts
    const again = evaluate(profile, kit, null, { setup: "1h-shield", monkBins: BINS, procs: table, hasteAssumed: counted });
    expect(again.F.toString()).toBe(withProc.F.toString());
  });

  it("counts a proc from a Lore donor the kit does not wear, and none when the kit wears it in an Any place: its copy is the one that is worn", () => {
    const table = readProcs(doc([donor("w80113", true)]), TRIO);
    const relic = item("w80113");
    const alone = evaluate(profile, kitOf({ [PRIMARY]: host }), null, { setup: "1h-shield", monkBins: BINS, procs: table });
    expect(alone.breakdown.totals.procs.PRIMARY).toMatchObject({ effect: "e0", donor: "w80113", mode: "h" });
    expect(alone.F.sub(base.F).toString()).toBe(procPart("900/1").toString());
    const bag = evaluate(profile, kitOf({ [PRIMARY]: host, [ANY]: relic }), null, { setup: "1h-shield", monkBins: BINS, procs: table });
    expect(bag.breakdown.totals.procs.PRIMARY).toBeNull();
    const plainDonor = readProcs(doc([donor("w80113", false)]), TRIO);
    const kept = evaluate(profile, kitOf({ [PRIMARY]: host, [ANY]: relic }), null, { setup: "1h-shield", monkBins: BINS, procs: plainDonor });
    expect(kept.breakdown.totals.procs.PRIMARY).toMatchObject({ donor: "w80113", mode: "h" }); // (a plain item has a second copy)
  });

  it("counts the proc of a Lore item in the hand that wears it, and the off hand by the dual-wield factor", () => {
    const table = readProcs(doc([donor("w80113", true)]), TRIO);
    const relic = item("w80113");
    const found = evaluate(profile, kitOf({ [PRIMARY]: host, [SECONDARY]: relic }), null, { setup: "dw", monkBins: BINS, procs: table });
    const counted = found.breakdown.totals.procs;
    expect(counted.PRIMARY).toBeNull(); // (the relic is worn in the off hand: no donor for the main hand)
    expect(counted.SECONDARY).toMatchObject({ donor: "w80113", mode: "n" });
    expect(counted.part.toString()).toBe(procPart("900/1", profile.dw_factor === undefined ? Rational.parse("1/2") : Rational.fromNumber(Number(profile.dw_factor))).toString());
  });
});
