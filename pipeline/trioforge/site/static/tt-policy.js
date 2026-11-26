// The one Trusted Types policy of the site, named "trioforge": the optimizer's way in.
//
// The site's policy header (require-trusted-types-for 'script') makes the browser refuse a plain string wherever it would start a
// script: that includes the address of a Worker. Its trusted-types directive names this policy and no other (no 'default', no second name,
// no duplicates), so that nothing else on the page can make a policy that lets plain strings through. That also means the policy is made
// once per page, by the page script's copy of tt-record.js as the page script loads; the optimizer's client carries another copy, which finds the record of the page's
// one policy under a named property of the window (see there). This file is the optimizer's: it checks the paths it lists against the manifest's own patterns first
// (it reads the list through the array iterator, which a script that runs later can change: that can only make this call throw, and so deny the optimizer its worker; tt-record.js says what a later script can and cannot do).
//
// The page starts exactly one such worker, the optimizer's, and this policy is the only way to get its address past the browser: it hands
// out a trusted address for the paths the build's manifest lists (hashed files under /assets/engine/) and for nothing else. It has no
// rule for markup or for script text, so those stay refused.
//
// A browser without Trusted Types (the API is detected, not assumed) has nothing to refuse, so the same check runs and the
// plain, checked path is returned instead.

import { isEnginePath } from "./engine/manifest.js";
import { POLICY_NAME, getEnginePolicy } from "./tt-record.js";

export { POLICY_NAME };

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
  return getEnginePolicy(trustedTypes, list);
}
