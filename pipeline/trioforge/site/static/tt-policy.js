// The one Trusted Types policy of the site, named "trioforge".
//
// The site's policy header (require-trusted-types-for 'script') makes the browser refuse a plain string wherever it would start a
// script: that includes the address of a Worker. Its trusted-types directive names this policy and no other (no 'default', no second name,
// no duplicates), so that nothing else on the page can make a policy that lets plain strings through. That also means the policy is made
// once per page, by one bundle (the optimizer's client): a second copy of this module in another bundle would be refused as a duplicate.
//
// The page starts exactly one such worker, the optimizer's, and this policy is the only way to get its address past the browser: it hands
// out a trusted address for the paths the build's manifest lists (hashed files under /assets/engine/) and for nothing else. It has no
// rule for markup or for script text, so those stay refused.
//
// A browser without Trusted Types (the API is detected, not assumed) has nothing to refuse, so the same check runs and the
// plain, checked path is returned instead.

import { isEnginePath } from "./engine/manifest.js";

export const POLICY_NAME = "trioforge";

// one policy per Trusted Types object: asking again for the same page adds paths, it does not make a second policy
const made = new WeakMap();

/**
 * The policy for the given paths (each a hashed engine file). Returns `{name, scriptURL(path)}`: `scriptURL` returns a TrustedScriptURL for a
 * listed path (a plain string when the browser has no Trusted Types) and throws a TypeError for any other. Throws a TypeError for a
 * path that is not a hashed engine file, and lets the browser's error through if the browser will not make the policy.
 */
export function getAssetPolicy(trustedTypes, paths) {
  const list = [...paths];
  for (const path of list) {
    if (!isEnginePath(path)) throw new TypeError("The optimizer's files are hashed files under /assets/engine/ and nothing else.");
  }
  const available = typeof trustedTypes === "object" && trustedTypes !== null && typeof trustedTypes.createPolicy === "function";
  let record = available ? made.get(trustedTypes) : undefined;
  if (record === undefined) {
    const allowed = new Set();
    record = { allowed, policy: null };
    if (available) {
      record.policy = trustedTypes.createPolicy(POLICY_NAME, {
        createScriptURL(input) {
          if (typeof input !== "string" || !allowed.has(input)) throw new TypeError("This address is not one of the optimizer's files.");
          return input;
        },
      });
      made.set(trustedTypes, record);
    }
  }
  for (const path of list) record.allowed.add(path);
  const { allowed, policy } = record;
  return {
    name: POLICY_NAME,
    scriptURL(path) {
      if (typeof path !== "string" || !allowed.has(path)) throw new TypeError("This address is not one of the optimizer's files.");
      return policy === null ? path : policy.createScriptURL(path);
    },
  };
}
