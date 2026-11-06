// The scenario modes in the worker: Equip now, the farm path, the best sets and Every slot, for a trio, a level, a scenario (a race, a role, a buff set, an evidence level, a
// weapon setup and perhaps a deity) and the items a visitor owns, and the best kit of a view over its whole pool, worked out from the data the site publishes.
//
//   const scenarios = createScenarioEngine({highs, fetchImpl, baseUrl})
//   await scenarios.equipNow(request, {manifest, now, onProgress})                       -> {status, proven, label, F, value, kit, buffs, hasteAssumed}
//   await scenarios.farmPath(request, {manifest, now, onProgress, onStep, stopped})      -> {stopped, steps, hasteAssumed}; Equip now and each step go to onStep as they come
//   await scenarios.bestSets(request, {manifest, now, onProgress})                       -> {k, acquired, F, value, gain, gainValue, kit, buffs, status, proven, label, baseline, hasteAssumed}
//   await scenarios.everySlot(request, {manifest, now, onProgress})                      -> {rows}; the swaps offered are the candidates and the owned items (an owned item that is no candidate only while a copy is free)
//   await scenarios.bestKit(request, {manifest, now, onProgress})                        -> {status, proven, label, F, value, kit, buffs, hasteAssumed}: the answer of Equip now, over the pool of the view
//   scenarios.stats() / scenarios.close()
//
// `request` is a scenario request of the mode as protocol.js checks it. The data comes from the manifests and from nowhere else: on the first request for a
// trio the engine fetches the manifest of the trio, at an address made from the name of a trio that the main manifest lists (never from the text of the request;
// it has a size limit of its own and the release of the main manifest, manifest.js), then the item table and the bundle of the trio and the level by the paths
// the manifests list (never an address of the request), and
//   * checks the type and the size against the manifest as the body is read (a body that is longer than the manifest says is refused while it is read), and the
//     SHA-256 before a byte is parsed (download.js);
//   * parses it, and reads it with the readers of the format: readItemTable (items.js) and readBundle (profile.js); the bundle must be the trio's and the level's it
//     was asked for, and the table and the bundle must be of one release and one rules version;
//   * keeps it: the item table once, the manifest and the bundle of the last trio (the one request that asks for another trio drops them for the other's).
// A file that is refused is not kept: the next request fetches it again.
//
// The session (solve.js) is made from the bundle for the profile the scenario names (`viewProfile` of bestkit.js, with the evidence level and the deity, and the weights of the
// request when there are any: the sliders, the custom weights and the regen window, composed on the role's own by the one function that the best kit uses too), the weapon setup
// (it must be one of the role's at that evidence level), the bundle's buff set for `buffs` and its Monk bins. It is kept for the next request with the same trio, level, race, role,
// buffs, evidence, setup, deity and weights (and the same bundle), and closed otherwise, so that the solver's model stays where the same columns are used again; weights that
// are the role's own are the same as none, and weights spelled another way that compose the same profile are the same weights (`weightsKey`). The choices and the weights of every
// request are checked against the bundle first, whether a session is kept or not (the key says which session to reuse, not that the weights are ones the bundle has). The owned items
// are records of the item table made into item vectors at their tier (`atTier`, with the bundle's rules), an owned ident that is not in the table is a bad request, and
// one that the trio cannot wear is kept: the builder gives it no column. path.js answers, without the tie stage (`canonical: false`).
//
// The candidates. A request for the farm path, the best sets or Every slot names a tier mode and no candidates: they are made here, from the records of the item table, by
// candidates.js (the records of the scenario's evidence level that the precompute offers and the profile can use, hidden ones never, each at the tier of the mode). The last
// list made is kept, with what it was made from: the SHA-256 of the table and of the bundle, the race, the deity, the evidence level and the tier mode. Every slot offers the
// owned items too (at the tiers they are owned at), as the reference does, and counts their copies: a candidate has no count limit (the swap means getting another copy; an
// ident that is both owned and a candidate counts as a candidate), while an owned item that is not a candidate is a swap for a place only while the visitor owns more of it than
// the kit wears in the other places (path.js, `everySlot`).
//
// The farm path (`createFarmPath` of path.js, a stepper): Equip now goes first, as the step 0, then each step as it is made. The progress {stage: "step", step} is sent when
// the stepper begins a step (its `onBegin`), so that no report names a step that does not begin. Between two steps the engine yields to the event
// loop, a macrotask, so that a message that has arrived is seen, and asks `stopped()`: when it says yes the path is stopped before its next step, and ends with the result
// "stopped". A path that has nothing to add has no Equip now of its own; the engine answers Equip now alone for it, and the path ends "no-gain", or "time" when that Equip now
// did not finish (as a path with an Equip now of its own that did not finish). A fault in a step (a solver that did what an answer cannot be made from, say) ends the path
// with the error; the steps sent before it stand.
//
// Time. The budget of a request is the time its work may take: it is counted from the moment the data is in (the first request for a trio downloads the data inside the
// request, which on a slow link takes longer than the budget, and a download is not a solve). The budget of a farm path is the whole path's: each step may use all that is
// left of it (path.js). The elapsed time of the answer, which the worker works out, is the whole request. While the data is loaded the engine reports progress at least every
// LOADING_BEAT_MS, whether bytes arrive or not: every report gives the page's watchdog a new window, and a download that has stopped is ended by its own stall rule
// (download.js). Every report of a scenario request carries the stage it is in: "loading", "equip-now", "step" (and the number of the step), "best-sets", "every-slot" or "best-kit".
//
// Faults. What is wrong with the visitor's request (a name the bundle does not have, an item the table does not have, a kit that wears what is not owned) is a bad request.
// What is wrong with the data is not the visitor's, and is told as engine-load, with the data dropped so that the next request fetches it again: a bundle whose rules the
// engine cannot use (found when the bundle is loaded, not at the first item), a bundle that no session can be made of, an item that the table writes so that it cannot be
// worked out. What the solver does that an answer cannot be made from (SolverFault) closes the session, and the worker tells it as `solver`.
//
// The weights. Every mode takes the `weights` of the request, `{multipliers?, custom?, regenT?}`, and puts them on the profile of its session with `viewProfile` of bestkit.js: the
// sliders, the custom weights and the regen window are composed on the role's own by weightsOverride, with the mana of the trio, and only when they are not the role's own. A choice
// the bundle does not have (a race, a buff set, a slider group at x1 as at x2, a weight above the largest, a window above the longest) is a bad request; a bundle whose weight rules
// the engine cannot use, found when weights are asked for, is a fault of the data (engine-load, with the bundle dropped), and a request with none does not need them. The
// weapons are paid the haste the kit counts (each answer says it: Equip now's kit, each step's, the set's), whatever the weights say.
//
// The best kit (engine/bestkit.js, the one function that makes the pool of a view, prunes it and solves it, which the shard parity test calls too). The request names no owned item and
// no candidates: the pool is the records of the item table that the precompute solves for the view, each at the tier of the request. Its session is made for the view and closed
// when the answer is made (nothing of it is kept: a slider that moves is another profile, and so another model), and it is answered without the tie stage, as the farm path is. A
// request may name the weapon tier rate, `options: {weaponTierRate: 5 | 10}`, the percent of damage a weapon grows a tier (the rule `tier.weapon_damage_pct` is the default): the items
// of the pool are made with it. The budget counts from the moment the data is in, the pool, the pruning and the model included. Its progress is the stage "best-kit".
//
// The answer of Equip now is `{status, proven, label, F, value, kit, buffs, hasteAssumed}`: `F` the exact value as a reduced "p/q" text and `value` its number, `kit` the 22
// places as idents (null for an empty place; null altogether when no kit was found in time), `buffs` the ids of the optional buffs chosen; the worker adds the time it took.
// The fields of the others are in protocol.js, and the best kit's are Equip now's.

import { BestKitError, bestKit as solveBestKit, viewProfile, weightsKey } from "./bestkit.js";
import { candidatesFor } from "./candidates.js";
import { DATA_FILE, EngineFault, fetchBytes, sameOriginUrl, sha256Hex } from "./download.js";
import { EvaluateError } from "./evaluate.js";
import { ItemError, atTier, checkTierRules, readItemTable } from "./items.js";
import { ManifestError, ManifestReleaseError, fetchTextWithin, parseTrioManifest, trioManifestPath } from "./manifest.js";
import { ModelError, ident } from "./model.js";
import { PathError, bestSets, createFarmPath, equipNow, everySlot } from "./path.js";
import { BundleError, readBundle } from "./profile.js";
import { LABEL_NO_INCUMBENT, LIMITS, LOADING_BEAT_MS, STARTUP_COMPILE_MS, STARTUP_STALL_MS } from "./protocol.js";
import { PruneError } from "./prune.js";
import { ExactnessError, PlacementError, SolveError, SolverFault, closeSession, createSession } from "./solve.js";
import { MAX_DIFFICULTY, TierError, arrivalTier, costToReach } from "./tiers.js";

const defaultNow = () => performance.now();
/** A macrotask: what is already waiting in the event loop (a message from the page, say) is handled before the engine goes on. */
const defaultYield = () => new Promise((resolve) => setTimeout(resolve, 0));

/**
 * The weapon tier rate that the options of a best-kit request name, none when they name none. The protocol has checked the options (an option it does not read, or a rate that is
 * not 5 or 10, is refused there); a request that came another way is held to the same here: an option the engine does not read is a bad request, and so is a rate that is no rate
 * (bestkit.js says that).
 */
function weaponRateOf(options) {
  if (options === undefined) return undefined;
  if (options === null || typeof options !== "object" || Array.isArray(options)) throw new EngineFault("bad-request", "The options of a request are an object.");
  for (const key of Object.keys(options)) {
    if (key !== "weaponTierRate") throw new EngineFault("bad-request", "The request has an option that the optimizer does not read.");
  }
  return options.weaponTierRate;
}

/** The key of an owned ident: everything before the tier (an ident is `key@tier`, a key has no `@`). */
function splitIdent(name) {
  const at = name.lastIndexOf("@");
  return { key: name.slice(0, at), tier: Number(name.slice(at + 1)) };
}

/** The trio of a bundle as the manifest and a request name it: the class codes in lower case, joined by hyphens. */
const trioCode = (bundle) => bundle.trio.map((code) => code.toLowerCase()).join("-");

function fault(message) {
  return new EngineFault("engine-load", message);
}

/**
 * Whether an error is one that the engine's functions raise about what they are given. When the engine gives them nothing but data (the bundle's profile and buff set, a
 * record of the item table) and what the request chose has been checked, such an error is a fault of the data.
 */
const isEngineError = (error) =>
  [SolveError, EvaluateError, PathError, ModelError, TierError, BundleError, ItemError, PruneError].some((type) => error instanceof type);

/**
 * @param {object} options
 *   highs        the loaded solver (what the loader of `highs` gives)
 *   fetchImpl    fetch; the default is the global one
 *   baseUrl      the address the paths of the manifest are made absolute against: the worker's own
 *   now          a clock in milliseconds (the default is performance.now); a request may bring its own, which is then the clock of its time
 *   stallMs      no byte of a download for this long: it is given up (the limits of protocol.js are the defaults)
 *   bodyMs       the time a body that cannot be watched in pieces may take
 *   yieldNow     returns a promise that settles in a macrotask (the default is a timer of 0 ms): the engine waits on it between the steps of a farm path
 */
export function createScenarioEngine({ highs, fetchImpl = (...args) => fetch(...args), baseUrl = import.meta.url, now = defaultNow, stallMs = STARTUP_STALL_MS, bodyMs = STARTUP_COMPILE_MS, yieldNow = defaultYield }) {
  let clock = now;
  let table = null; // {sha256, read}
  let trioFiles = null; // {path, document}: the manifest of the last trio
  let bundle = null; // {sha256, trio, level, document}
  let kept = null; // {key, session}
  let candidates = null; // {key, list}: the last list of candidates made
  const counts = { itemTables: 0, trioManifests: 0, bundles: 0, sessions: 0, sessionsClosed: 0, candidateLists: 0, bestKits: 0 };

  /** Fetch a file of the manifest and check it: the type and size as it is read, then its SHA-256. The bytes of a file that is not the one listed are never returned. */
  async function fetchFile(file, what, onBytes) {
    let bytes;
    try {
      bytes = await fetchBytes(sameOriginUrl(file.path, baseUrl), file.bytes, fetchImpl, (progress) => onBytes(progress.loaded), stallMs, bodyMs, DATA_FILE);
    } catch (error) {
      if (error instanceof EngineFault) throw error;
      throw fault(`The optimizer's ${what} could not be loaded.`); // (a request that failed: what the browser said of it is not for the visitor, and may name an address)
    }
    if ((await sha256Hex(bytes)) !== file.sha256) throw fault(`The optimizer's ${what} is not the one the site lists (its checksum differs).`);
    return bytes;
  }

  /** The text of the bytes as parsed JSON. Called only for bytes that have the SHA-256 of the manifest. */
  function parse(bytes, what) {
    try {
      return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    } catch {
      throw fault(`The optimizer's ${what} could not be read.`);
    }
  }

  /**
   * The manifest of the trio of a request, fetched if it is not the one kept. Its address is made from the name of a trio in the main manifest; a trio the
   * manifest does not list is a bad request, and nothing is fetched. A file that is refused is not kept.
   */
  async function loadTrioManifest(manifest, request) {
    const path = trioManifestPath(manifest, request.trio);
    if (path === undefined) throw new EngineFault("bad-request", "The manifest lists no such trio.");
    if (!manifest.trios.get(request.trio).levels.includes(request.level)) throw new EngineFault("bad-request", "The manifest lists no bundle for this trio and level.");
    if (trioFiles !== null && trioFiles.path === path) return trioFiles.document;
    const what = "The optimizer's list of files for this trio";
    const answer = await fetchTextWithin(fetchImpl, sameOriginUrl(path, baseUrl), { credentials: "same-origin", cache: "no-cache" }, stallMs, LIMITS.maxTrioManifestBytes);
    if (answer.state === "timeout") throw fault(`${what} did not arrive in time.`);
    if (answer.state === "status") throw fault(`${what} could not be loaded (${answer.status}).`);
    if (answer.state === "toolarge") throw fault(`${what} is too large.`);
    if (answer.state !== "ok" || typeof answer.text !== "string") throw fault(`${what} could not be loaded.`);
    let document;
    try {
      document = parseTrioManifest(JSON.parse(answer.text), manifest, request.trio);
    } catch (error) {
      if (error instanceof ManifestReleaseError) throw fault(`${what} is of another release than the optimizer's.`);
      if (error instanceof ManifestError || error instanceof SyntaxError) throw fault(`${what} is not what the site writes.`);
      throw error;
    }
    trioFiles = { path, document };
    counts.trioManifests += 1;
    return document;
  }

  /**
   * The manifest of the trio, the item table and the bundle for the request, fetched if they are not the ones kept. Reports the download as one figure for the files it
   * needs, and, whatever it is waiting for, says so at least every LOADING_BEAT_MS (the last report again, or a bare "loading" before there is a figure).
   */
  async function loadData(manifest, request, onProgress) {
    let last = { phase: "loading", stage: "loading" };
    const say = (progress) => {
      last = progress;
      onProgress(progress);
    };
    const beat = setInterval(() => onProgress(last), LOADING_BEAT_MS);
    try {
      await loadFiles(manifest, request, say);
    } finally {
      clearInterval(beat);
    }
  }

  async function loadFiles(manifest, request, onProgress) {
    const file = (await loadTrioManifest(manifest, request)).bundles.get(request.level);
    if (file === undefined) throw new EngineFault("bad-request", "The manifest lists no bundle for this trio and level.");
    const items = manifest.items;
    const needTable = table === null || table.sha256 !== items.sha256;
    const needBundle = bundle === null || bundle.sha256 !== file.sha256 || bundle.trio !== request.trio || bundle.level !== request.level;
    const total = (needTable ? items.bytes : 0) + (needBundle ? file.bytes : 0);
    let done = 0;
    const report = (loaded) => onProgress({ phase: "loading", stage: "loading", loaded: done + loaded, total });
    if (needTable) {
      const bytes = await fetchFile(items, "item table", report);
      done += items.bytes;
      report(0);
      let read;
      try {
        read = readItemTable(parse(bytes, "item table"));
      } catch (error) {
        if (!(error instanceof ItemError)) throw error;
        throw fault("The item table is not what the site writes.");
      }
      table = { sha256: items.sha256, read };
      counts.itemTables += 1;
    }
    if (needBundle) {
      const bytes = await fetchFile(file, "bundle", report);
      done += file.bytes;
      report(0);
      let document;
      try {
        document = readBundle(parse(bytes, "bundle"));
        checkTierRules(document); // the rules of tiers and of weapons are compiled now: a bundle with rules the engine cannot use is refused here, not at the first item
      } catch (error) {
        if (!(error instanceof BundleError)) throw error;
        throw fault("The trio's bundle is not what the site writes.");
      }
      if (trioCode(document) !== request.trio || document.level !== request.level) throw fault("The bundle is not the one for this trio and level.");
      if (document.data_release !== table.read.dataRelease || document.rules_version !== table.read.rulesVersion) {
        throw fault("The item table and the bundle are not of one data release and rules version.");
      }
      if ((document.inputs ?? null) !== table.read.inputs) throw fault("The item table and the bundle are not made from the same inputs."); // (the build holds them to it too)
      bundle = { sha256: file.sha256, trio: request.trio, level: request.level, document };
      counts.bundles += 1;
    }
  }

  function closeKept() {
    if (kept === null) return;
    closeSession(kept.session);
    kept = null;
    counts.sessionsClosed += 1;
  }

  /** A bundle that was found not to be what the site writes, or that no session can be made of: let go of it, and of the session made of it. */
  function dropBundle() {
    closeKept();
    bundle = null;
    candidates = null;
  }

  /** An item table that was found not to be what the site writes: let go of it, of the bundle that was checked against it and of the session made of that. */
  function dropTable() {
    closeKept();
    table = null;
    bundle = null;
    candidates = null;
  }

  /**
   * The session for the scenario of a request: the one kept if it is for the same scenario and the same weights of the same bundle, else a new one (the old is closed first).
   * Every request is checked by `viewProfile`, as the best kit's is, before a kept session is looked for: a choice the bundle does not have (a race, a role, a buff set, an evidence
   * level, a setup, a deity, a weight) is a bad request, whatever session is kept, and a refusal closes none. The key only says which session to reuse: it leaves out what changes
   * nothing (a slider at x1, a window of null), so a key that matches does not say that the weights are ones the bundle has. What `viewProfile` finds wrong that is no choice (weight
   * rules the engine cannot use, a profile the bundle cannot give) is a fault of the bundle, which is dropped.
   */
  function sessionFor(request) {
    const { race, role, buffs, evidence, setup, deity } = request.scenario;
    const document = bundle.document;
    let profile;
    try {
      profile = viewProfile(document, request.scenario, request.weights);
    } catch (error) {
      if (error instanceof BestKitError) throw new EngineFault("bad-request", error.message);
      if (!isEngineError(error)) throw error;
      dropBundle(); // what is wrong is not the visitor's choice: it is the bundle's own
      throw fault("The trio's bundle is not what the site writes.");
    }
    const key = JSON.stringify([request.trio, request.level, bundle.sha256, race, role, buffs, evidence, setup, deity ?? null, weightsKey(request.weights)]);
    if (kept !== null && kept.key === key) return kept.session;
    closeKept();
    let session;
    try {
      session = createSession({
        highs,
        profile,
        setup,
        buffset: { set: document.buffs[buffs].set, table: document.buff_table },
        monkBins: document.monk_bins === null ? undefined : document.monk_bins,
        options: {},
        now: () => clock(),
      });
    } catch (error) {
      if (!isEngineError(error)) throw error;
      dropBundle(); // what the session is made of is the bundle's own profile, buff set and Monk bins: the choice of the visitor was checked above
      throw fault("The trio's bundle is not what the site writes.");
    }
    kept = { key, session };
    counts.sessions += 1;
    return session;
  }

  /** The owned items of the request as `[item vector, count]` pairs: the record of each in the table, at the tier of its ident. */
  function ownedItems(request) {
    return request.owned.map(([name, count], at) => {
      const { key, tier } = splitIdent(name);
      const record = table.read.records.get(key);
      if (record === undefined) throw new EngineFault("bad-request", `An owned item (entry ${at + 1}) is not in the item table.`);
      try {
        return [atTier(record, tier, bundle.document), count];
      } catch (error) {
        if (!isEngineError(error)) throw error;
        dropTable(); // the tier is one of 0 to 10 (the request was checked), the rules were compiled when the bundle was loaded: it is the record that is wrong
        throw fault("The item table is not what the site writes.");
      }
    });
  }

  /**
   * The kit of an Every slot request as item vectors (null for an empty place): every item of it is in the table and owned, as often as the kit wears it. A kit that wears
   * what the visitor does not own is a bad request.
   */
  function kitItems(request) {
    const owned = new Map(request.owned);
    const worn = new Map();
    return request.kit.map((name, at) => {
      if (name === null) return null;
      const times = (worn.get(name) ?? 0) + 1;
      worn.set(name, times);
      if ((owned.get(name) ?? 0) < times) throw new EngineFault("bad-request", `The kit (place ${at + 1}) wears an item that is not owned, or more of it than is owned.`);
      const { key, tier } = splitIdent(name);
      const record = table.read.records.get(key);
      if (record === undefined) throw new EngineFault("bad-request", `An item of the kit (place ${at + 1}) is not in the item table.`);
      try {
        return atTier(record, tier, bundle.document);
      } catch (error) {
        if (!isEngineError(error)) throw error;
        dropTable();
        throw fault("The item table is not what the site writes.");
      }
    });
  }

  /**
   * The candidates of the request: the records of the item table that the tier mode and the scenario make candidates of (candidates.js), each at the tier of the mode. The
   * last list made is kept, with what it was made from: the table and the bundle (their SHA-256, which stand for the trio and the level too), the race, the deity,
   * the evidence level and the tier mode; a request for the same scenario of the same data takes it again.
   */
  function candidatesOf(request, session) {
    const { race, deity, evidence } = request.scenario;
    const key = JSON.stringify([table.sha256, bundle.sha256, race, deity ?? null, evidence, request.tierMode]);
    if (candidates !== null && candidates.key === key) return candidates.list;
    let list;
    try {
      list = candidatesFor(table.read.records, bundle.document, session.profile, { evidence, tierMode: request.tierMode });
    } catch (error) {
      if (!isEngineError(error)) throw error;
      dropTable(); // the request was checked and the rules were compiled when the bundle was loaded: it is a record that is wrong
      throw fault("The item table is not what the site writes.");
    }
    candidates = { key, list };
    counts.candidateLists += 1;
    return list;
  }

  /**
   * The data for a request, the session of its scenario and its owned items, and what is left of its budget at any moment after (the budget counts from the moment the data was
   * in: what making the session took comes off it). `stage` is the stage of the progress reports from the moment the data is in.
   */
  async function prepare(request, { manifest, now: requestClock, onProgress, stage }) {
    clock = requestClock ?? now;
    await loadData(manifest, request, onProgress);
    const dataIn = clock();
    onProgress({ phase: "building", stage });
    const session = sessionFor(request);
    const owned = ownedItems(request);
    return { session, owned, left: () => Math.max(0, request.budgetMs - (clock() - dataIn)) };
  }

  /**
   * Run `work`; when the solver did what an answer cannot be made from (SolverFault), or a model overstated its kit (ExactnessError, PlacementError), let go of the session:
   * it is not to be trusted with another solve. The error goes on.
   */
  async function guarded(work) {
    try {
      return await work();
    } catch (error) {
      if (error instanceof SolverFault || error instanceof ExactnessError || error instanceof PlacementError) closeKept();
      throw error;
    }
  }

  /** What reaching the tier of an acquired item costs (`costToReach` of tiers.js), counted as the tier mode counts it; null when the mode scores the item below the tier it arrives at. */
  function costOf(item, kind, sourceTier, tierMode) {
    const record = table.read.records.get(item.key);
    const D = tierMode.mode === "arrives" ? tierMode.D : MAX_DIFFICULTY;
    const from = kind === "upgrade" ? sourceTier : arrivalTier(record, D);
    if (from > item.tier) return null;
    const cost = costToReach(record, from, item.tier, { D });
    return { exp: cost.exp, copiesAtArrival: cost.copies_at_arrival, potentials: cost.potentials };
  }

  const identOf = (item) => (item === null ? null : ident(item.key, item.tier));
  const exactText = (value) => (value === null ? null : value.toString());
  const exactNumber = (value) => (value === null ? null : value.toNumber());

  /** The answer of the solver, or of a function that answers like it, as a message carries it: the exact value as a reduced "p/q" text and its number, the kit as idents. */
  function answerBody(answer) {
    return {
      status: answer.status,
      proven: answer.proven,
      label: answer.label,
      F: exactText(answer.F),
      value: exactNumber(answer.F),
      kit: answer.kit === null ? null : answer.kit.map(identOf),
      buffs: [...answer.buffs],
      hasteAssumed: answer.hasteAssumed,
    };
  }

  /** A step of the path as its message carries it (a step that was not found has none of the fields of a step, and the label of a solve that ran out of time with nothing). */
  function stepBody(step, request) {
    if (!step.found) {
      return {
        index: step.index,
        found: false,
        ident: null,
        kind: null,
        sourceTier: null,
        cost: null,
        F: null,
        value: null,
        gain: null,
        gainValue: null,
        kit: null,
        buffs: [],
        hasteAssumed: step.hasteAssumed,
        status: "time_limit",
        proven: false,
        label: LABEL_NO_INCUMBENT,
      };
    }
    return {
      index: step.index,
      found: true,
      ident: identOf(step.item),
      kind: step.kind,
      sourceTier: step.sourceTier,
      cost: costOf(step.item, step.kind, step.sourceTier, request.tierMode),
      F: exactText(step.F),
      value: exactNumber(step.F),
      gain: exactText(step.gain),
      gainValue: exactNumber(step.gain),
      kit: step.solution.kit.map(identOf),
      buffs: [...step.solution.buffs],
      hasteAssumed: step.hasteAssumed,
      status: step.status,
      proven: step.solution.proven,
      label: step.label,
    };
  }

  return {
    /**
     * Answer a request for Equip now (see the head of this file). Rejects with an EngineFault (engine-load, bad-request) or the engine's own error. The solve has the budget of
     * the request, counted from the moment the data is in (what the session took to make comes off it); `startedAt`, the arrival of the request, is for the worker's own count of
     * the elapsed time.
     */
    async equipNow(request, { manifest, now: requestClock, onProgress = () => {} }) {
      const { session, owned, left } = await prepare(request, { manifest, now: requestClock, onProgress, stage: "equip-now" });
      return answerBody(await guarded(() => equipNow(session, owned, { budgetMs: left(), canonical: false })));
    },

    /**
     * Answer a request for a farm path: Equip now and then the steps, each one handed to `onStep` as the body of its message the moment it is made (index 0 is Equip now), and
     * the result `{stopped, steps, hasteAssumed}` when the path has ended. The candidates are made from the tier mode. The budget is the whole path's, counted from the
     * moment the data is in, and each step may use all that is left of it. Between two steps the engine yields to the event loop (`yieldNow`: a macrotask, so that a message that
     * has arrived is seen) and asks `stopped()`: a stop ends the path before its next step. A fault in a step ends the path with that fault; the steps sent before it stand.
     */
    async farmPath(request, { manifest, now: requestClock, onProgress = () => {}, onStep = () => {}, stopped = () => false }) {
      const { session, owned, left } = await prepare(request, { manifest, now: requestClock, onProgress, stage: "equip-now" });
      return guarded(async () => {
        const offered = candidatesOf(request, session);
        // the progress names a step when the stepper begins it, and so never one that does not begin (after a stop, at the limit, after a step that ended the path)
        const onBegin = (number) => onProgress({ phase: "solving", stage: "step", step: number });
        const path = createFarmPath(session, owned, offered, { steps: request.steps, budgetMs: left(), canonical: false, onBegin });
        // Equip now. A path that has nothing to add ends before it has one, and the page has it all the same: it is the answer of Equip now alone.
        const started = path.start();
        const baseline = started ?? equipNow(session, owned, { budgetMs: left(), canonical: false });
        onStep({ index: 0, ...answerBody(baseline) });
        for (;;) {
          await yieldNow();
          if (stopped()) path.stop();
          const step = path.next();
          if (step === null) break;
          onStep(stepBody(step, request));
        }
        const result = path.result();
        // A path with nothing to add ends "no-gain" by itself. But when the Equip now answered for it did not finish, the path ran out of time, as any path whose Equip now
        // did not finish does (path.js ends it "time" itself when it has the Equip now): the page holds the two to each other.
        const why = started === null && baseline.status !== "optimal" ? "time" : result.stopped;
        return { stopped: why, steps: result.steps.length, hasteAssumed: result.hasteAssumed ?? baseline.hasteAssumed };
      });
    },

    /** Answer a request for the best sets: the best kit when up to k additions are made at once (see path.js), as the message carries it. */
    async bestSets(request, { manifest, now: requestClock, onProgress = () => {} }) {
      const { session, owned, left } = await prepare(request, { manifest, now: requestClock, onProgress, stage: "best-sets" });
      return guarded(() => {
        const offered = candidatesOf(request, session);
        const set = bestSets(session, owned, offered, request.k, { budgetMs: left(), canonical: false });
        // a set that was not found in time has no value, no kit and the label of a solve that ran out of time with nothing
        const status = set.kit === null ? "time_limit" : set.status;
        const label = set.kit === null ? LABEL_NO_INCUMBENT : set.label;
        return {
          k: set.k,
          acquired: set.acquired.map((found) => ({ ident: found.ident, kind: found.kind, sourceTier: found.sourceTier, cost: costOf(found.item, found.kind, found.sourceTier, request.tierMode) })),
          ...answerBody({ status, proven: status !== "time_limit", label, F: set.F, kit: set.kit, buffs: set.buffs, hasteAssumed: set.hasteAssumed }),
          gain: exactText(set.gain),
          gainValue: exactNumber(set.gain),
          baseline: { F: exactText(set.baseline.F), value: exactNumber(set.baseline.F) },
        };
      });
    },

    /**
     * Answer a request for Every slot: for each of the 22 places, the swaps that gain the most when one item stands in that place and the rest of the kit stays as it is. The
     * items on offer are the candidates of the tier mode and the items the visitor owns (an owned item at the tier it is owned at), as the reference makes them (`_every_slot` in
     * pipeline/trioforge/export/fixture_cases.py), and their copies are counted. A candidate has no count limit: the swap means getting another copy of it, and an ident that is
     * both owned and a candidate counts as a candidate. An owned item that is not a candidate is a swap for a place only while the visitor's owned count of that ident is
     * greater than the copies the kit wears in its OTHER places, so that the kit after the swap wears it no more often than it is owned (one ring owned once and worn on Finger 1
     * is not a swap for Finger 2). Lore stays as it is. What the profile cannot use is left out by everySlot of path.js. There is no solve: the evaluator values the kit of the
     * request and each swap. Every item of the kit must be in the table and owned, as often as it is worn.
     */
    async everySlot(request, { manifest, now: requestClock, onProgress = () => {} }) {
      const { session, owned } = await prepare(request, { manifest, now: requestClock, onProgress, stage: "every-slot" });
      const kit = kitItems(request);
      return guarded(() => {
        const rows = everySlot(session, kit, candidatesOf(request, session), { buffs: request.buffs, limit: request.limit, owned });
        return {
          rows: rows.map((row) => ({
            place: row.place,
            index: row.index,
            current: identOf(row.current),
            swaps: row.swaps.map((swap) => ({ ident: identOf(swap.item), delta: exactText(swap.delta), deltaValue: exactNumber(swap.delta) })),
          })),
        };
      });
    },

    /**
     * Answer a request for the best kit of a view (see the head of this file): the best kit over the pool of the view at the tier of the request, with the weights of the request.
     * The pool, its pruning, the weights and the solve are those of engine/bestkit.js, on a session made for this request and closed when it is answered. The data is loaded as
     * for every mode; the budget counts from the moment it is in, and what the pool, the pruning and the model take comes off it. Rejects with a bad request for a choice the
     * bundle does not have, with an engine-load fault for data that is not what the site writes (it is dropped), and with the solver's own faults as they are.
     */
    async bestKit(request, { manifest, now: requestClock, onProgress = () => {} }) {
      clock = requestClock ?? now;
      const weaponTierRate = weaponRateOf(request.options);
      await loadData(manifest, request, onProgress);
      const dataIn = clock();
      onProgress({ phase: "building", stage: "best-kit" });
      let found;
      try {
        found = solveBestKit({
          highs,
          records: table.read.records,
          bundle: bundle.document,
          scenario: request.scenario,
          tier: request.tier,
          weights: request.weights,
          weaponTierRate,
          budgetMs: Math.max(0, request.budgetMs - (clock() - dataIn)),
          canonical: false,
          now: () => clock(),
        });
      } catch (error) {
        if (error instanceof BestKitError) throw new EngineFault("bad-request", error.message);
        if (error instanceof SolverFault || error instanceof ExactnessError || error instanceof PlacementError) throw error; // (the worker tells them; the session was closed)
        if (!isEngineError(error)) throw error;
        // the request was checked, and what it chose exists: it is what the data holds that is wrong (a record, or the rules of the bundle)
        if (error instanceof ItemError) {
          dropTable();
          throw fault("The item table is not what the site writes.");
        }
        dropBundle();
        throw fault("The trio's bundle is not what the site writes.");
      }
      counts.bestKits += 1;
      return answerBody(found.answer);
    },

    /** How many item tables, manifests of trios, bundles, sessions and lists of candidates were made, sessions closed and best kits solved, since the engine began (for the tests). */
    stats() {
      return { ...counts };
    },

    /** Let go of the session and the data. */
    close() {
      closeKept();
      table = null;
      trioFiles = null;
      bundle = null;
      candidates = null;
    },
  };
}
