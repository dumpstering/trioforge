// The profile of a view, made from the bundle for the choices of a request and its weights: the one function of the optimizer's worker (scenario.js, bestkit.js) and of the evaluator
// in the page (kitvalue.js, for the order of motes). It lives in a file of its own so that the evaluator does not carry the solver that bestkit.js imports.
//
//   viewProfile(bundle, scenario, weights) -> the profile of a view: the bundle's for the choices, with the weights of a request composed on the role's own (every mode)
//   weightsAreOwn(weights)                 -> whether the weights of a request are the role's own (none, or all sliders at x1, no custom weight and no regen window)
//   BestKitError                           -> the visitor's choices that the bundle does not have (a race, a role, a buff set, a setup, a weight): not a fault of the data
//
// See bestkit.js for what a view is and how the weights are composed.

import { ChoiceError, assembleProfile } from "./profile.js";
import { WeightsError, weightsOverride } from "./weights.js";

/** A choice of the visitor that the data does not have, or weights the bundle's rules refuse. */
export class BestKitError extends Error {
  constructor(message) {
    super(message);
    this.name = "BestKitError";
  }
}

/** Whether the weights of a request are the role's own: none, or every slider at x1, no custom weight and no regen window. */
export function weightsAreOwn(weights) {
  if (weights === undefined || weights === null) return true;
  const { multipliers, custom, regenT } = weights;
  if (multipliers !== undefined && multipliers !== null && Object.values(multipliers).some((position) => position !== 1)) return false;
  if (custom !== undefined && custom !== null && Object.keys(custom).length > 0) return false;
  return regenT === undefined || regenT === null;
}

/**
 * The profile of a view: the bundle's for the choices (a race, a role, a buff set, an evidence level, perhaps a deity, and a weapon setup the role plays at the level), with the
 * weights of a request composed on the role's own when they are not the role's own. The one function for every mode of the worker. A BestKitError for a choice the bundle does not
 * have (the choices are checked first, and `assembleProfile` says so with a ChoiceError) and for weights its rules refuse (a slider group there is not, at x1 as at x2). Whatever
 * else goes wrong is not the asker's: it is an error of the bundle itself (rules of weights the engine cannot use, a profile it cannot give for choices it has).
 */
export function viewProfile(bundle, scenario, weights) {
  const { race, role, buffs, evidence, deity } = scenario;
  if (typeof evidence !== "string") throw new BestKitError("The scenario names no evidence level."); // (assembleProfile alone would take none, and the pool would be another)
  let profile;
  try {
    profile = assembleProfile(bundle, { race, role, buffs, evidence, deity });
  } catch (error) {
    if (error instanceof ChoiceError) throw new BestKitError(error.message); // (a BundleError that is not a choice is the bundle's own fault, and goes on as it is)
    throw error;
  }
  if (!profile.setups.includes(scenario.setup)) throw new BestKitError("This weapon setup is not one of the role's setups at this evidence level.");
  if (weights === undefined || weights === null) return profile;
  let composed;
  try {
    composed = weightsOverride(bundle, profile.weights, {
      multipliers: weights.multipliers,
      custom: weights.custom,
      regenT: weights.regenT,
      manaReachable: profile.pools.MANA.length > 0,
    });
  } catch (error) {
    if (error instanceof WeightsError) throw new BestKitError(error.message);
    throw error;
  }
  return weightsAreOwn(weights) ? profile : Object.freeze({ ...profile, weights: composed });
}
