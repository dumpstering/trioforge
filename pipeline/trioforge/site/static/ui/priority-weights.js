// What a choice of priorities means for the optimizer, and how the exchange rates of a kit are worded: the code the chunk of the weights uses (ui/weights.js), and no other.
//
//   customOf(own, priorities)       -> {weight name: number}: the custom weights of a request for a choice of priorities
//   countedOf(own)                  -> [boolean] for each stat of the control: whether the build weighs it at all
//   normalizeOf(own, priorities)    -> the choice with the step of every stat the build does not weigh made Normal
//   allOff(own, priorities)         -> whether every stat of the control is Off or not weighed by the build
//   ratesText({rates, exact, ...})  -> the line of the exchange rates under the control
//
// A choice is a character for each of the eight stats of the control (0 l n h t: Off, Low, Normal, High, Top, in the order of priorities.js), and a step multiplies the weight that the role gives
// the stat by 0, 0.5, 1, 2 or 4. The product is sent as a custom weight, and as nothing else: the weights that follow a stat (the weapon damage follows attack, the regeneration of each of hit
// points, mana and endurance follows its resource, and mana is 0 for a trio with no mana pool) follow it by the one definition of how weights compose, `weights_override` in
// pipeline/trioforge/model/roles.py and its port static/engine/weights.js, which the engine applies to the request. A stat left Normal sets nothing, so a choice of all Normal is the role's own
// weights to the last digit. Nothing here knows how weights compose, and nothing here may: tests-js/priority-weights.test.mjs holds it to that definition.
//
// A stat the build does not weigh (a role whose weight for it is 0: haste for a caster, mana for a trio with no mana pool) is not a choice: its step is never sent (a weight of 0 times any step
// is the 0 the role has), never makes a request of its own and is Normal in the address; the control shows it disabled. Charisma is no stat of the control and keeps the build's own weight under
// every choice, so a choice that turns every stat of the control Off leaves a build that only weighs charisma, which is nothing to optimise (`allOff`).
//
// A weight of a request has at most six significant digits (engine/protocol.js: WEIGHT_DIGITS), so a product that has more (a role's weight that is the mean of three, times four) is rounded
// to six, which moves a weight by less than a millionth of itself.

/** The multiplier of each step, by the character of the address (priorities.js has the same characters in the same order; a test holds the two equal). */
export const STEP_MULTIPLIERS = Object.freeze({ 0: 0, l: 0.5, n: 1, h: 2, t: 4 });
/** The weights each stat of the control sets, by the id of the stat in the order of the control: the resists are the five schools, each with its own weight (the schools of a role are equal; they need not be). */
export const WEIGHTS_OF = Object.freeze({
  hp: ["HP"],
  ac: ["AC"],
  mana: ["MANA"],
  atk: ["ATK"],
  dex: ["DEX"],
  haste: ["HASTE"],
  resists: ["SV_FIRE", "SV_COLD", "SV_MAGIC", "SV_POISON", "SV_DISEASE"],
  end: ["END"],
});
const IDS = Object.keys(WEIGHTS_OF);
const DIGITS = 6;

/** Whether the role gives a stat of the control a weight: some weight the stat sets is above 0. */
const weighed = (own, id) => WEIGHTS_OF[id].some((name) => own[name] > 0);

/** For each stat of the control, in its order: whether the build (the role's own weights `own`) weighs it. */
export function countedOf(own) {
  return IDS.map((id) => weighed(own, id));
}

/** The choice with every stat the build does not weigh made Normal, and every other character as it was. */
export function normalizeOf(own, priorities) {
  return [...priorities].map((character, index) => (weighed(own, IDS[index]) ? character : "n")).join("");
}

/** Whether every stat of the control is Off or not weighed by the build: nothing is left to weigh but charisma, and there is no kit to work out. */
export function allOff(own, priorities) {
  return IDS.every((id, index) => !weighed(own, id) || priorities[index] === "0");
}

/** The custom weights of a request for `priorities`, from the role's own weights `own` (a table by name, as the bundle has it): a weight for each stat that is not Normal, and only for a weight the role has (one of 0 has nothing to scale). */
export function customOf(own, priorities) {
  const custom = {};
  IDS.forEach((id, index) => {
    const step = STEP_MULTIPLIERS[priorities[index]];
    if (step === undefined || step === 1) return;
    for (const name of WEIGHTS_OF[id]) {
      if (Object.hasOwn(own, name) && own[name] > 0) custom[name] = Number((own[name] * step).toPrecision(DIGITS));
    }
  });
  return custom;
}

/** A rate to one decimal under ten and as a whole number from ten; "under 0.1" for what is more than nothing and less than that. */
function figure(value) {
  if (!(value > 0)) return "0";
  if (value >= 10) return String(Math.round(value));
  const tenths = Math.round(value * 10) / 10;
  return tenths === 0 ? "under 0.1" : String(tenths);
}

/**
 * Where the mana of the trio comes from, in a sentence: the stats (WIS, INT) of the mana pools of its classes and how many pools count (`counted`, the bundle's `pools_counted`: the largest ones
 * count). Said once, after the rates; "" when no pool has a mana stat.
 */
export function manaSource(pools, counted = 2) {
  const stats = pools.filter((stat) => stat === "WIS" || stat === "INT");
  const named = ["WIS", "INT"].filter((stat) => stats.includes(stat));
  if (stats.length === 0) return "";
  const have = Math.min(stats.length, counted);
  if (named.length === 1) return `Mana here comes from ${named[0]} (${have} pool${have === 1 ? "" : "s"}).`;
  return stats.length <= counted ? `Mana here comes from ${named.join(" and ")} (1 pool each).` : `Mana here comes from ${named.join(" and ")} (the ${counted === 2 ? "two" : counted} largest of ${stats.length} pools count).`;
}

/**
 * The line of the exchange rates: what one more point of each stat is worth on the kit shown. `rates` are those of `ratesOfKit` (engine/kitvalue.js). `casting` are the stats the trio's mana pools
 * use (WIS, INT, one or both, or none), `mana` and `haste` whether the build weighs maximum mana and haste at all (a stat it does not is left out), `pools` the stats of the trio's mana pools (the sentence of `manaSource` follows the rates when the build weighs mana), and `steps` whether any priority is set: the unit
 * is then the points of this build's score and not hit points, because with a step set no stat is the unit (one hit point is worth what the step makes it). Not relative to stamina: that would hide the
 * scale, and the same kit would read as the same figures under any choice.
 */
export function ratesText({ rates, exact, casting = ["WIS", "INT"], mana = true, haste = true, steps = false, pools = [], counted = 2 }) {
  const parts = [`stamina ${figure(rates.STA)}`, `strength ${figure(rates.STR)}`];
  for (const stat of ["WIS", "INT"]) if (casting.includes(stat)) parts.push(`${stat} ${figure(rates[stat])}`);
  parts.push(`armor class ${figure(rates.AC)}`, `dexterity ${figure(rates.DEX)}`);
  if (haste) parts.push(`haste ${figure(rates.HASTE)}`);
  if (mana) parts.push(`maximum mana ${figure(rates.MANA)}`);
  parts.push(`endurance ${figure(rates.END)}`, `one resist ${figure(rates.resist)}`);
  const unit = steps ? "points of this build's score" : "hit points of kit value";
  return (
    `A point more on this kit is worth about: ${parts.join(", ")} (${unit}).` +
    (haste ? " Haste counts the best single piece, so its figure is for one more point on that piece." : "") +
    (mana && pools.length > 0 ? ` ${manaSource(pools, counted)}` : "") +
    (exact ? "" : " The best buffs were not searched out completely, so these are rough.")
  );
}
