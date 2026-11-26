// The page's side of the solver worker.
//
//   const engine = getEngineClient();      // the page's one client (createEngineClient makes another, for tests)
//   const result = await engine.solve({ v: 1, kind: "model", model, budgetMs: 10000 }, { onProgress });
//   const answer = await engine.runScenario({ v: 1, kind: "scenario", mode: "farm-path", ... }, { onStep, onProgress });   // any of the four modes
//   engine.stop();     // end every farm path not finished (the one in flight, and each one that waits its turn), before the next step the worker begins after it has seen the stop: each still resolves, "stopped"
//   engine.cancel();   // stop the worker at once and fail the request
//
// What it takes care of:
//   * the request is checked (protocol.js) before anything else happens, and a request carries no address;
//   * consent, on every browser, at the first use in a session: "Load the optimizer (about N MB)", N from the build's manifests: the worker and the
//     WebAssembly and, for a scenario, the item table and the bundle of the trio (the manifest of the trio is read before the question, a few hundred
//     bytes). A data-saver setting, a slow connection or little memory only add a line of warning to the question. Declining keeps the precomputed
//     answers: nothing is downloaded, and the request fails with the code `declined` until the visitor asks for the optimizer again
//     (askConsent), so that a slider moved ten times does not ask ten times. A yes with no request waiting (askConsent on its own) loads
//     nothing and leaves no panel behind; the first request loads the optimizer;
//   * every download is under the loading panel, with its progress and a Cancel, whether a question came before it (or a yes remembered in the
//     session did instead). After a start that failed, the yes no longer starts a download by itself: the next request asks the question
//     again, and says that the optimizer did not load last time;
//   * if a release comes while the optimizer is starting (the worker's manifest lists another WebAssembly than the page's), nothing is tried again:
//     the page shows "The optimizer was updated. Reload the page to use it." with a Reload button, and every request fails at once until it is
//     reloaded. A compiled module that was kept is dropped then, so that it is never run under a newer manifest. The same notice is shown, in place
//     of an error, when a scenario's data cannot be loaded (a file of an earlier release is gone) or the manifest of its trio is of another release than
//     the manifest in hand, and the manifest read again is not the one the page began with;
//   * the worker is started once, from the manifest's path, through the Trusted Types policy of tt-policy.js, and reused. The compiled
//     WebAssembly module it hands back is kept, so a worker that had to be stopped is replaced without a new download;
//   * requests run one at a time, in the order they were made;
//   * starting the optimizer has limits (protocol.js: STARTUP_STALL_MS, STARTUP_COMPILE_MS): the worker aborts a download in which no byte arrives
//     for 20 seconds, and the request for the list of files has the same limit. A download that keeps delivering is never cut off, however long it
//     takes: the page puts no limit of its own on it. Once the last byte is in, checking the file, compiling it and starting the solver may take
//     a minute. The loading panel has a Cancel button: while the optimizer is being downloaded it takes the visitor's yes back;
//   * the watchdog stops a worker that does not answer, but only once the request's whole budget plus five seconds have passed since its last sign
//     of life (the post of the request, a report of progress, or a step of a farm path): it is there for a hang, not for a slow solve and not for a slow download, in which
//     the worker reports as it goes (a download that stops is ended by the stall rule of the download). cancel() stops the worker at once (a solve cannot be
//     interrupted from outside); stop() asks every farm path that is not finished (in flight, or waiting its turn) to end before the next step the worker begins after it
//     has seen the stop, and does not stop the worker.
//   * every message from the worker is checked (a farm path as a whole too: the steps in order, what each gains and wears), and a worker that sends one that is not right is
//     dropped.
//
// Errors are EngineError objects with a `code`: bad-request, unsupported, unavailable, declined, cancelled, busy, watchdog, worker-failed,
// protocol, engine-load, not-implemented, not-ready, bad-model, solver, internal.
//
// A scenario request (protocol.js: equip-now, farm-path, best-sets or every-slot) goes to the worker like a model, behind the same question and the same loading panel: the data it
// needs (the item table and the bundle of the trio) is fetched by the worker, after it is ready, from the paths of the manifest. The question's figure is the same for every
// mode. `runScenario(request, {onStep, onProgress})` runs one and resolves to its final result; for a farm path `onStep` gets the message of each step as it comes (index 0 is Equip
// now, then 1 to 8), and the final result is `{kind: "scenario", mode, stopped, steps, hasteAssumed, elapsedMs}`. `stop()` asks the worker to end every farm path that is not
// finished before the next step it begins after it has seen the stop (the step being worked out is finished and handed over; in a browser that can be one step later than the step
// the page was looking at when it asked, since the worker looks between two steps and the message may be delivered after it has looked). A farm path that still waits its turn
// (behind a model request, or behind another path) is marked, and its stop is sent right after its request, so that it ends after its Equip now. A request that is not a farm path
// is never stopped. `solve()` runs any request too (a farm path's steps are then not handed to anyone).
//
// `runScenario(request, {replaceWaiting: true})` is for a caller that asks again at every change of a control (the sliders of the trio page): a best-kit request made with it takes the place of
// the best-kit requests that have not reached the worker (each is rejected as `cancelled`: the ones that wait for their turn, and the one the client has begun for, which still waits for the
// visitor's answer to the question or for the worker to start), and the one that runs finishes, its answer the caller's to drop when it is old. Only requests of the best kit are replaced, and
// only a request of the best kit does it; a request of another mode, or made without the option, leaves the queue as it was.
//
// `runScenario(request, {signal})` takes one request back: when the AbortSignal fires, a request that waits is taken out of the queue and rejected as `cancelled`, and one that the worker is
// working on is rejected the same way and the worker is stopped (a solve cannot be interrupted from outside; the next request starts a worker again from the module the client kept, with no
// download). It never touches another request, and it never stops a worker that is not working on that request. This is how a part of a page ends what it asked for: `cancel()` ends what every part
// asked for, and is for the page (the visitor's Cancel on the loading panel, the end of the client). `onSent()` is called once, when the worker has the request: a request that has not been
// sent only waits, and a caller that no longer wants it can take it back at no cost. A part of a page that is told `cancelled` for a request it did not take back (its own signal did not fire)
// has been cancelled by another part, and asks again; the error of the Cancel button of the loading panel carries `byVisitor: true`, since the visitor asked for that one and nobody asks again.

import { getAssetPolicy } from "../tt-policy.js";
import {
  ManifestError,
  ManifestReleaseError,
  MANIFEST_PATH,
  downloadMegabytes,
  fetchTextWithin,
  parseManifest,
  parseTrioManifest,
  trioManifestPath,
} from "./manifest.js";
import {
  BEST_KIT,
  FARM_PATH,
  LIMITS,
  PROTOCOL_VERSION,
  ProtocolError,
  LIVENESS_TIMEOUT_MS,
  SCENARIO_MODES,
  STARTUP_COMPILE_MS,
  STARTUP_FIRST_SIGN_MS,
  STARTUP_STALL_MS,
  WATCHDOG_GRACE_MS,
  checkAgainstManifest,
  createPathWatch,
  validateFromWorker,
  validateRequest,
} from "./protocol.js";

/**
 * Scenario requests (a trio, a level, owned items: the page does not build a model) are answered by the worker with the JavaScript model builder. The worker answers all
 * four modes; a scenario request of a mode that is not listed here would fail at once with not-implemented, before the visitor is asked to download several megabytes and before
 * anything is downloaded (protocol.js refuses a request of any other mode before that, as a bad request).
 */
const SCENARIO_MODES_READY = new Set(SCENARIO_MODES);

/** Requests waiting behind the one that runs. A page that fires one per movement of a slider should cancel or wait; this keeps a mistake from piling up. */
const MAX_WAITING = 64;

export class EngineError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "EngineError";
    this.code = code;
  }
}

/** A message without the fields that belong to the protocol (version, type, id): what is left is for the caller. */
function withoutEnvelope(message) {
  const rest = { ...message };
  delete rest.v;
  delete rest.type;
  delete rest.id;
  return rest;
}

function toEngineError(error) {
  if (error instanceof EngineError) return error;
  if (error instanceof ProtocolError) return new EngineError(error.code, error.detail);
  if (error instanceof ManifestError) return new EngineError("unavailable", "The optimizer's list of files could not be read.");
  return new EngineError("internal", "Something went wrong in the optimizer.");
}

// ---- what the browser says about itself ----------------------------------------------------------------------------------------------

const SLOW_CONNECTIONS = new Set(["slow-2g", "2g", "3g"]);

/** Reasons to warn before a download of several megabytes: data saver on, a slow connection, little memory. Only some browsers say. */
export function environmentWarnings(nav) {
  const reasons = [];
  try {
    if (typeof nav !== "object" || nav === null) return reasons;
    const connection = nav.connection ?? nav.mozConnection ?? nav.webkitConnection;
    if (connection && connection.saveData === true) reasons.push("Data Saver is on");
    if (connection && typeof connection.effectiveType === "string" && SLOW_CONNECTIONS.has(connection.effectiveType)) reasons.push("the connection looks slow");
    if (typeof nav.deviceMemory === "number" && nav.deviceMemory < 4) reasons.push("this device reports little memory");
  } catch {
    // a browser that throws when asked has told us nothing
  }
  return reasons;
}

function warningLine(reasons) {
  const list = reasons.length > 1 ? `${reasons.slice(0, -1).join(", ")} and ${reasons[reasons.length - 1]}` : reasons[0];
  return `Heads up: ${list}. The download and the answers may be slower than usual.`;
}

// ---- the session's memory of a yes ---------------------------------------------------------------------------------------------------

const CONSENT_KEY = "trioforge-engine-consent";

function sessionStorageOf(win) {
  try {
    return win.sessionStorage ?? null;
  } catch {
    return null; // blocked storage throws when it is asked for
  }
}

function consentWasGiven(storage) {
  try {
    return storage ? storage.getItem(CONSENT_KEY) === "1" : false;
  } catch {
    return false;
  }
}

function forgetConsent(storage) {
  try {
    if (storage) storage.removeItem(CONSENT_KEY);
  } catch {
    // blocked storage: nothing was written, so nothing is left to take back
  }
}

function rememberConsent(storage) {
  try {
    if (storage) storage.setItem(CONSENT_KEY, "1");
  } catch {
    // blocked storage: the question is asked again in the next session
  }
}

// ---- the question on the page ------------------------------------------------------------------------------------------------------

/** What the notice says when a release came while the optimizer was starting; it is also the message of the error that the requests after it get. */
const UPDATED_TEXT = "The optimizer was updated. Reload the page to use it.";

/**
 * The question as the page shows it: a small panel, built from text nodes only, that asks, then shows the download's progress, and is
 * removed when the optimizer is ready (or the answer is no). Keyboard focus goes to the question itself and never to a button: a key that
 * the visitor pressed for something else (a second Enter in the field that started the request, a held key that repeats) must not be able to
 * say yes to a download of several megabytes. The visitor gets to the buttons with Tab or the pointer. Escape says no while the question is
 * open; its handler comes off the panel once the question is answered, so that Escape does nothing during the download (Cancel is the way out
 * of that), and focus goes back to where it was when the panel is closed.
 *
 * The same panel is shown for a download that no question came before (a yes given earlier in the session): the loading state alone, with
 * its progress and its Cancel, and without taking the focus from what the visitor is doing. And it is the notice that the page must be reloaded
 * after a release, with a Reload button, which stays until the page is reloaded. A page can pass its own `consent` object with the same
 * methods, or a `mount` element to put this panel in.
 */
function createConsentPanel({ document: doc, mount, onCancel, onReload }) {
  let panel = null;
  let status = null;
  let bar = null;
  let previousFocus = null;
  let kind = null; // what the panel shows: "question", "loading" or "updated"

  const element = (tag, className, text) => {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  /** The empty panel, in the page. */
  function open() {
    panel = element("div", "engine-consent");
    panel.setAttribute("role", "group");
    panel.setAttribute("tabindex", "-1"); // the focus can be put here by script and by a click, and it is not a stop of its own in the tab order
    (mount ?? doc.getElementById("main") ?? doc.body).append(panel);
  }

  /** Take the panel away. The notice that the page must be reloaded stays, unless this is the end of the client (`final`). */
  function close(final = false) {
    if (panel === null) return;
    if (kind === "updated" && final !== true) return;
    const active = doc.activeElement;
    const focusWasHere = !active || active === doc.body || panel.contains(active);
    panel.remove();
    panel = status = bar = kind = null;
    if (focusWasHere && previousFocus && previousFocus !== doc.body && doc.contains(previousFocus) && typeof previousFocus.focus === "function") previousFocus.focus();
    previousFocus = null;
  }

  function showLoading({ focus }) {
    panel.replaceChildren();
    kind = "loading";
    // the title it was named by and the text it was described by are gone (a pointer at what is not there is an error); a label of its own keeps the group named
    panel.removeAttribute("aria-labelledby");
    panel.removeAttribute("aria-describedby");
    panel.setAttribute("aria-label", "Optimizer download");
    status = element("p", "", "Loading the optimizer…");
    status.setAttribute("role", "status");
    bar = element("progress");
    bar.setAttribute("aria-label", "Loading the optimizer");
    // a way out of a download that is slow or stuck: the visitor keeps the precomputed answers
    const cancel = element("button", "", "Cancel");
    cancel.setAttribute("type", "button");
    cancel.setAttribute("data-action", "cancel");
    cancel.addEventListener("click", () => onCancel?.());
    const actions = element("div", "engine-consent-actions");
    actions.append(cancel);
    panel.append(status, bar, actions);
    if (focus) panel.focus(); // the button that was pressed is gone: a visitor at the keyboard stays in the panel, one Tab from Cancel
  }

  function ask({ megabytes, warnings, failedLastTime }) {
    return new Promise((resolve) => {
      close(true); // (never two panels)
      previousFocus = doc.activeElement;
      open();
      kind = "question";
      panel.setAttribute("aria-labelledby", "engine-consent-title");
      panel.setAttribute("aria-describedby", "engine-consent-text");
      const title = element("h3", "", "Load the optimizer?");
      title.id = "engine-consent-title";
      const text = element("p", "", "Working out an answer for your own gear needs the optimizer. It downloads once and runs on this device. Nothing about your gear leaves this page.");
      text.id = "engine-consent-text";
      panel.append(title, text);
      if (failedLastTime === true) panel.append(element("p", "engine-consent-warning", "The optimizer did not load last time."));
      if (warnings.length > 0) panel.append(element("p", "engine-consent-warning", warningLine(warnings)));
      const accept = element("button", "", `Load the optimizer (about ${megabytes.toFixed(1)} MB)`);
      const decline = element("button", "", "Not now");
      for (const button of [accept, decline]) button.setAttribute("type", "button");
      accept.setAttribute("data-action", "accept");
      decline.setAttribute("data-action", "decline");
      const actions = element("div", "engine-consent-actions");
      actions.append(accept, decline);
      panel.append(actions);
      let answered = false;
      const onKey = (event) => {
        if (event.key === "Escape") answer(false);
      };
      const answer = (yes) => {
        if (answered) return;
        answered = true;
        panel.removeEventListener("keydown", onKey);
        if (yes) showLoading({ focus: true });
        else close();
        resolve(yes);
      };
      accept.addEventListener("click", () => answer(true));
      decline.addEventListener("click", () => answer(false));
      panel.addEventListener("keydown", onKey);
      panel.focus(); // the question, not the button that says yes (see above)
    });
  }

  /** The panel of a download that no question came before: loading, with its progress and its Cancel, and the focus left where it was. */
  function loading() {
    if (panel !== null) return;
    previousFocus = null;
    open();
    showLoading({ focus: false });
  }

  /** The notice that a release came while the optimizer was starting, with a button that reloads the page. It replaces whatever the panel showed. */
  function updated() {
    if (kind === "updated") return;
    close(true);
    previousFocus = null;
    open();
    kind = "updated";
    panel.setAttribute("aria-label", "Optimizer update");
    status = element("p", "", UPDATED_TEXT);
    status.setAttribute("role", "status");
    const reload = element("button", "", "Reload");
    reload.setAttribute("type", "button");
    reload.setAttribute("data-action", "reload");
    reload.addEventListener("click", () => onReload?.());
    const actions = element("div", "engine-consent-actions");
    actions.append(reload);
    panel.append(status, actions);
  }

  /** What the panel says for each part of the first answer. Only the loading has a figure; for the rest the bar shows that something is going on. */
  const PHASE_TEXT = {
    compiling: ["Getting the optimizer ready…", "Getting the optimizer ready"],
    starting: ["Getting the optimizer ready…", "Getting the optimizer ready"],
    building: ["Setting up the problem…", "Setting up the problem"],
    solving: ["Looking for the best answer…", "Looking for the best answer"],
  };

  function progress(report) {
    if (panel === null || bar === null) return;
    if (report.phase === "loading" && report.total > 0) {
      bar.max = report.total;
      bar.value = report.loaded;
      bar.setAttribute("aria-label", "Loading the optimizer");
      status.textContent = `Loading the optimizer… ${Math.floor((report.loaded * 100) / report.total)}%`;
    } else if (Object.prototype.hasOwnProperty.call(PHASE_TEXT, report.phase)) {
      const [line, label] = PHASE_TEXT[report.phase];
      bar.removeAttribute("value"); // no figure for this part: the bar shows that something is going on
      bar.setAttribute("aria-label", label);
      if (status.textContent !== line) status.textContent = line; // (a live region: say it once, not at every report of the solver)
    }
  }

  return { ask, loading, progress, updated, close };
}

// ---- the client --------------------------------------------------------------------------------------------------------------------

/**
 * @param {object} [options] all optional; the page's own objects are the defaults.
 *   window, document, navigator, fetch      the page's (they can be replaced in tests)
 *   createWorker(url)                       makes the worker; the default is `new Worker(url, {type: "module", name})`
 *   trustedTypes                            the Trusted Types object (null for none); the default is the window's
 *   storage                                 where a yes is remembered for the session; the default is sessionStorage
 *   consent                                 {ask(info) -> Promise<boolean>, loading?(), progress?(report), updated?(), close?(final)}; the default is the panel
 *                                           above. `info` is {megabytes, warnings, failedLastTime}. `loading()` is called when a download starts, whether a
 *                                           question came before it or not; `updated()` when a release came and the page has to be reloaded.
 *   mount                                   the element the default panel goes in
 *   reload                                  what the Reload button of the notice that the page has to be reloaded does; the default reloads the page
 */
export function createEngineClient(options = {}) {
  const win = options.window ?? globalThis;
  const doc = options.document ?? win.document;
  const fetchFn = options.fetch ?? ((...args) => win.fetch(...args));
  const nav = options.navigator ?? win.navigator;
  const trustedTypes = options.trustedTypes !== undefined ? options.trustedTypes : win.trustedTypes;
  const storage = options.storage !== undefined ? options.storage : sessionStorageOf(win);
  const reloadPage = options.reload ?? (() => win.location.reload());
  const ui = options.consent ?? createConsentPanel({ document: doc, mount: options.mount, onCancel: () => cancelFromPanel(), onReload: () => reloadPage() });
  const injectedWorker = options.createWorker !== undefined;
  const makeWorker = options.createWorker ?? ((url) => new win.Worker(url, { type: "module", name: "trioforge-engine" }));
  // looked up when used, so that a test's fake timers apply
  const setTimer = (fn, ms) => globalThis.setTimeout(fn, ms);
  const clearTimer = (id) => globalThis.clearTimeout(id);

  let consent = consentWasGiven(storage) ? "granted" : "unknown";
  let consentPending = null;
  let manifest = null;
  let manifestText = null; // the text it was read from: a manifest read again is the same release if it is the same text (the build writes canonical JSON)
  let manifestPending = null;
  let worker = null;
  let keptModule = null;
  let queue = [];
  let current = null;
  let pumping = false;
  let nextId = 1;
  let failedLastTime = false; // did the last start fail? Then the next question says so.
  let updated = false; // did a release come while a worker was starting? Then nothing is started again until the page is reloaded.
  const stats = { spawns: 0, solves: 0 };

  /** Close the panel (`final`: for good, the notice that the page must be reloaded too). */
  const closeUi = (final = false) => {
    try {
      ui.close?.(final);
    } catch {
      // a question that cannot be closed is not a reason to stop
    }
  };

  /** Ask the page's panel for its panel of a download (`loading`) or for its notice that the page must be reloaded (`updated`), if it has one. */
  const showUi = (method) => {
    try {
      ui[method]?.();
    } catch {
      // the panel is not part of the protocol
    }
  };

  function supported() {
    if (injectedWorker) return true;
    return typeof win.Worker === "function" && (typeof win.WebAssembly === "object" || typeof WebAssembly === "object");
  }

  // ---- the manifest ----

  function loadManifest() {
    if (manifest !== null) return Promise.resolve(manifest);
    manifestPending ??= (async () => {
      const unavailable = (why) => new EngineError("unavailable", `The optimizer is not available on this page (${why}).`);
      // within a time limit: a connection that stalls ends in "unavailable", not in a request that waits for ever. `no-cache` makes the browser ask
      // the server whether its copy is current, whatever caching headers the host sends: the file keeps its name from one release to the next.
      const answer = await fetchTextWithin(fetchFn, MANIFEST_PATH, { credentials: "same-origin", cache: "no-cache" }, STARTUP_STALL_MS);
      if (answer.state === "timeout") throw unavailable("its list of files did not arrive in time");
      if (answer.state === "failed") throw unavailable("its list of files could not be loaded");
      if (answer.state === "status") throw unavailable(`its list of files answered ${answer.status}`);
      // any other state is a failure too, and the text beside it (if there is one) is not looked at
      if (answer.state !== "ok") throw unavailable("its list of files could not be read");
      const text = answer.text;
      if (typeof text !== "string" || text.length > LIMITS.maxManifestBytes) throw unavailable("its list of files is not what was expected");
      try {
        manifest = parseManifest(JSON.parse(text));
      } catch {
        throw unavailable("its list of files is not what was expected");
      }
      manifestText = text;
      return manifest;
    })().finally(() => {
      manifestPending = null;
    });
    return manifestPending;
  }

  /**
   * Whether the site has been released again since the manifest in hand was read: the main manifest is read once more (the browser is asked whether its
   * copy is current), and it is another release if it is another text that is a manifest of the site, or any JSON object that names another release (a text
   * `data_release` that is not ours: a newer format of the manifest, which this strict reader refuses, still says which release it is of). A manifest that cannot be
   * read again says nothing (false), and neither does text that is not JSON.
   */
  async function newerRelease() {
    const answer = await fetchTextWithin(fetchFn, MANIFEST_PATH, { credentials: "same-origin", cache: "no-cache" }, STARTUP_STALL_MS, LIMITS.maxManifestBytes);
    if (!(answer.state === "ok" && typeof answer.text === "string" && manifestText !== null && answer.text !== manifestText)) return false;
    let found;
    try {
      found = JSON.parse(answer.text);
    } catch {
      return false; // (the page of an error of the host, or half a file, is no release)
    }
    if (found !== null && typeof found === "object" && !Array.isArray(found) && typeof found.data_release === "string" && found.data_release !== manifest?.dataRelease) return true;
    try {
      parseManifest(found); // (another text of the same release is one only when it is a list of files)
    } catch {
      return false;
    }
    return true;
  }

  /**
   * A release came while the page was open and no worker is the first to know it: the same end as releaseLanded, for a request that has no worker yet.
   * Whatever worker there is (an idle one) is stopped, a module that was kept is dropped, every request fails at once from now on, and the notice shows.
   */
  function releaseNoticed() {
    updated = true;
    keptModule = null;
    if (worker !== null) drop(worker, new EngineError("engine-load", UPDATED_TEXT));
    showUi("updated");
  }

  /**
   * The manifest of the trio of a scenario request, for the bundle's place in the question's size. It is at /engine-trios/<trio>.json, an address made from the
   * name of a trio that the manifest in hand lists. When it cannot be had (it is gone, too large, not what the site writes, or of another release than the
   * manifest in hand) the page looks at whether the site was released again since: if it was, the request ends in the notice that the page has to be
   * reloaded; if not, in `unavailable`.
   */
  async function loadTrioManifest(forManifest, request) {
    const path = trioManifestPath(forManifest, request.trio);
    if (path === undefined) throw new EngineError("bad-request", "The manifest does not list this trio.");
    const unavailable = (why) => new EngineError("unavailable", `The optimizer is not available on this page (its list of files for this trio ${why}).`);
    let failure = null;
    let document = null;
    const answer = await fetchTextWithin(fetchFn, path, { credentials: "same-origin", cache: "no-cache" }, STARTUP_STALL_MS, LIMITS.maxTrioManifestBytes);
    if (answer.state === "timeout") failure = unavailable("did not arrive in time");
    else if (answer.state === "status") failure = unavailable(`answered ${answer.status}`);
    else if (answer.state === "toolarge") failure = unavailable("is too large");
    else if (answer.state !== "ok" || typeof answer.text !== "string") failure = unavailable("could not be loaded");
    else {
      try {
        document = parseTrioManifest(JSON.parse(answer.text), forManifest, request.trio);
      } catch (error) {
        failure = unavailable(error instanceof ManifestReleaseError ? "is of another release than the optimizer's list of files" : "is not what was expected");
      }
    }
    if (failure === null) return document;
    if (await newerRelease()) {
      releaseNoticed();
      throw new EngineError("engine-load", UPDATED_TEXT);
    }
    throw failure;
  }

  // ---- consent ----

  function askOnce(forManifest, data) {
    consentPending ??= (async () => {
      let answer = false;
      try {
        answer = (await ui.ask({ megabytes: downloadMegabytes(forManifest, data), warnings: environmentWarnings(nav), failedLastTime })) === true;
      } catch {
        answer = false;
      }
      failedLastTime = false; // (it was said once, to the visitor who has answered)
      consent = answer ? "granted" : "declined";
      if (answer) rememberConsent(storage);
      return answer;
    })().finally(() => {
      consentPending = null;
    });
    return consentPending;
  }

  async function requireConsent(forManifest, data) {
    if (consent === "granted") return;
    if (consent === "declined") throw new EngineError("declined", "The optimizer was not loaded: the visitor chose to keep the precomputed answers.");
    if (!(await askOnce(forManifest, data))) throw new EngineError("declined", "The optimizer was not loaded: the visitor chose to keep the precomputed answers.");
  }

  // ---- the worker ----

  function report(job, progress) {
    try {
      ui.progress?.(progress);
    } catch {
      // the question's progress bar is not part of the protocol
    }
    try {
      job.onProgress?.(progress);
    } catch {
      // a bug in the page's callback must not break the worker's protocol
    }
  }

  /**
   * A start that failed (not one that was cancelled, and not one that met a release, which has its own end): the visitor's yes no longer starts a
   * download by itself, here or after a reload. The next request asks the question again, and says that the optimizer did not load last time.
   */
  function startFailed() {
    consent = "unknown";
    forgetConsent(storage);
    failedLastTime = true;
  }

  /** Stop a worker, and fail whatever was waiting for it with `error`. Safe to call twice. */
  function drop(record, error) {
    if (record.dead) return;
    const failedToStart = record.state === "starting" && error.code !== "cancelled" && !updated;
    record.dead = true;
    record.state = "dead";
    clearTimer(record.startupTimer);
    record.pingWaiter?.(false);
    if (worker === record) worker = null;
    record.handle.onmessage = null;
    record.handle.onmessageerror = null;
    record.handle.onerror = null;
    try {
      record.handle.terminate();
    } catch {
      // a worker that cannot be stopped is gone all the same, as far as the page is concerned
    }
    if (failedToStart) startFailed();
    record.rejectReady(error);
    if (current !== null && current.record === record) current.fail(error);
  }

  /**
   * A release came between the page's read of the manifest and the worker's: the worker lists, and loads, another WebAssembly than the one this page
   * described to the visitor (or, given the kept module, it read a newer manifest than the one the module was made under). Nothing is tried again:
   * the module that was kept is dropped, so that it is not paired with a newer manifest, every later request fails at once, and the page shows a
   * notice with a button that reloads it. A reload reads the new manifest and starts as the first visit did.
   */
  function releaseLanded(record) {
    updated = true;
    keptModule = null;
    drop(record, new EngineError("engine-load", UPDATED_TEXT));
    showUi("updated");
  }

  function onMessage(record, data) {
    if (record.dead || record !== worker) return; // a worker that was dropped does not speak again
    const job = current !== null && current.record === record ? current : null;
    // what is in flight: the request's kind and mode, what it owned and asked, and (for a farm path) the watch that holds the steps to their order and their sums
    const expectation = job === null
      ? {}
      : {
          id: job.id,
          kind: job.request.kind,
          mode: job.request.mode,
          owned: job.request.owned,
          columns: job.request.model?.c.length,
          steps: job.request.steps,
          k: job.request.k,
          limit: job.request.limit,
          tierMode: job.request.tierMode,
          kit: job.request.kit,
          tier: job.request.tier, // (a best kit wears only items of this tier)
          path: job.pathWatch,
        };
    let message;
    try {
      message = validateFromWorker(data, expectation);
    } catch (error) {
      drop(record, toEngineError(error));
      return;
    }
    if (record.awaitingSign) {
      // the first thing the worker says is its sign of life: the limit for one is over, and the ones that follow (armStartLimit) take its place
      record.awaitingSign = false;
      clearTimer(record.startupTimer);
      record.startupTimer = null;
    }
    if (message.type === "ready") {
      if (record.state !== "starting") return drop(record, new EngineError("protocol", "The optimizer said it was ready twice."));
      // The worker read the manifest for itself, and says which WebAssembly that manifest lists (the file it checked and loaded, or the file the module it
      // was given was made from). If a release came between its read and ours, that is another file than the one this page described to the visitor:
      // its SHA-256 has to be the one in the manifest this page holds. A worker that does not say is not trusted.
      if (message.wasm === undefined) return drop(record, new EngineError("protocol", "The optimizer did not say which file it was made from."));
      if (message.wasm !== record.expectedWasm) return releaseLanded(record);
      record.state = "ready";
      clearTimer(record.startupTimer);
      if (message.module !== undefined) keptModule = message.module;
      record.resolveReady(record);
    } else if (message.type === "pong") {
      if (record.pingWaiter === null) return drop(record, new EngineError("protocol", "The optimizer answered a question that was not asked."));
      record.pingWaiter(true);
    } else if (message.type === "progress") {
      if (record.state === "starting" && downloadIsOver(message)) armStartLimit(record);
      if (job !== null) job.watch(); // a sign of life of the request: the watchdog's window starts again
      const target = job ?? (record.state === "starting" ? startingJob(record) : null);
      if (target !== null) report(target, withoutEnvelope(message));
    } else if (message.type === "step") {
      // a step of a farm path is a sign of life of the request, as a report of progress is, and goes to the caller of runScenario
      if (job === null) return drop(record, new EngineError("protocol", "The optimizer sent a step of a request that was not asked."));
      job.watch();
      try {
        job.onStep?.(withoutEnvelope(message));
      } catch {
        // a bug in the page's callback must not break the worker's protocol
      }
    } else if (message.type === "result") {
      if (job === null) return drop(record, new EngineError("protocol", "The optimizer answered a request that was not asked."));
      clearTimer(job.timer);
      job.finish.resolve(withoutEnvelope(message));
    } else if (message.id === undefined) {
      // an error that no request asked for: the worker could not start. A module that a worker was given and could not start from is not kept: the
      // next worker downloads a fresh one (a cancelled request is not this: the worker is dropped by the page, with no message of its own)
      if (record.fromKept && record.state === "starting") keptModule = null;
      drop(record, new EngineError(message.code, message.message));
    } else {
      clearTimer(job.timer);
      const failure = new EngineError(message.code, message.message);
      // The data of a scenario could not be loaded, or the manifest of its trio is of another release than the worker's manifest: after a release, that is
      // what a worker that is older than the site sees (its files are gone, or the manifest of the trio is the new one's). The page looks at whether the
      // site was released again, and if so tells the visitor to reload instead of showing an error.
      if (message.code === "engine-load" && job.request.kind === "scenario") settleLoadFailure(record, job, failure);
      else job.finish.reject(failure);
      // an error the worker reports with a request means the request failed and the worker is fine, except `internal`: that came out of the
      // WebAssembly itself (an abort when the memory ran out, say), and an instance that aborted is not used again
      if (message.code === "internal") drop(record, failure);
    }
  }

  /**
   * The request the report of a worker that is still starting is for: the one the worker was started for, or, when that one was given up (replaced by a newer request, say, which
   * waits for the same worker), the one now in front of the queue.
   */
  function startingJob(record) {
    const started = record.startedFor;
    if (started !== null && started !== undefined && !started.settled) return started;
    return queue.find((job) => !job.settled) ?? null;
  }

  /** End a request whose data failed to load: with the notice that the page has to be reloaded if the site was released again, else with the worker's error. */
  async function settleLoadFailure(record, job, failure) {
    let newer = false;
    try {
      newer = await newerRelease();
    } catch {
      newer = false; // (a look that fails says nothing)
    }
    if (newer && !record.dead) releaseLanded(record);
    else job.finish.reject(failure);
  }

  /**
   * The limit for what is left of a start once the download is over: checking the file, compiling it and starting the solver, a minute. Armed once
   * per worker (when the last byte is in, or at the start for a worker that has no download) and cleared when the worker is ready or dropped.
   */
  function armStartLimit(record) {
    if (record.startupTimer !== null || record.dead || record.state !== "starting") return;
    record.startupTimer = setTimer(
      () => drop(record, new EngineError("engine-load", "The optimizer took too long to start. Try again, or keep the precomputed answers.")),
      STARTUP_COMPILE_MS,
    );
  }

  /** Whether a progress report of a starting worker says that the last byte of the download is in (or that the start is further on than that). */
  function downloadIsOver(report) {
    return report.phase === "compiling" || report.phase === "starting" || (report.phase === "loading" && report.loaded === report.total);
  }

  function spawn(forManifest, job) {
    let url;
    try {
      url = getAssetPolicy(trustedTypes, [forManifest.worker.path]).scriptURL(forManifest.worker.path);
    } catch {
      throw new EngineError("unsupported", "This browser would not let the optimizer start.");
    }
    let handle;
    try {
      handle = makeWorker(url);
    } catch {
      throw new EngineError("unsupported", "The optimizer could not be started in this browser.");
    }
    const record = {
      handle,
      dead: false,
      state: "starting",
      startedFor: job,
      expectedWasm: forManifest.wasm.sha256,
      fromKept: false,
      startupTimer: null,
      awaitingSign: false, // a worker that downloads has said nothing yet: the limit for its first sign is running
      used: false, // has it been given a request? (a worker that has just said it is ready is not asked whether it is there)
      pingWaiter: null, // (alive) => void, while the page waits for the answer to a ping
      ready: null,
      resolveReady: null,
      rejectReady: null,
    };
    record.ready = new Promise((resolve, reject) => {
      record.resolveReady = resolve;
      record.rejectReady = reject;
    });
    record.ready.catch(() => {});
    worker = record;
    stats.spawns += 1;
    handle.onmessage = (event) => onMessage(record, event?.data);
    handle.onmessageerror = () => drop(record, new EngineError("protocol", "The optimizer sent a message that could not be read."));
    handle.onerror = (event) => {
      try {
        event?.preventDefault?.();
      } catch {
        // nothing to prevent
      }
      drop(record, new EngineError("worker-failed", "The optimizer stopped working."));
    };
    const init = { v: PROTOCOL_VERSION, type: "init" };
    if (keptModule !== null) init.module = keptModule;
    record.fromKept = init.module !== undefined;
    try {
      handle.postMessage(init);
    } catch {
      // a browser that will not copy the compiled module to a worker: start the worker without it, and stop keeping it
      keptModule = null;
      record.fromKept = false;
      try {
        handle.postMessage({ v: PROTOCOL_VERSION, type: "init" });
      } catch {
        drop(record, new EngineError("worker-failed", "The optimizer could not be started."));
      }
    }
    // A worker that is given a compiled module has no download to do: its start has the limit for the rest of a start from the beginning. One that
    // downloads has none of the page's until the last byte is in (see armStartLimit): a stalled download is given up earlier, by the worker itself.
    if (record.fromKept) armStartLimit(record);
    else if (!record.dead) {
      showUi("loading"); // a download is always under the loading panel, whether a question came before it or not
      // and a worker that never says anything (its script did not run, and it raised no error) is given up too, after the time its own limits could take
      record.awaitingSign = true;
      record.startupTimer = setTimer(() => drop(record, new EngineError("engine-load", "The optimizer took too long to start. Try again, or keep the precomputed answers.")), STARTUP_FIRST_SIGN_MS);
    }
    return record.ready;
  }

  function startWorker(forManifest, job) {
    if (worker !== null && !worker.dead) return worker.ready;
    return spawn(forManifest, job);
  }

  /**
   * Whether an idle worker that has worked before is still there. A worker that was stopped without a word raises no error event, so a request
   * posted to it would wait for the watchdog (its budget plus five seconds). This is a question that an idle worker answers at once; one that does not
   * answer within LIVENESS_TIMEOUT_MS is dropped here.
   */
  function checkAlive(record) {
    return new Promise((resolve) => {
      if (record.dead) {
        resolve(false);
        return;
      }
      let timer = null;
      const settle = (alive) => {
        clearTimer(timer);
        record.pingWaiter = null;
        resolve(alive);
      };
      record.pingWaiter = settle;
      timer = setTimer(() => {
        drop(record, new EngineError("worker-failed", "The optimizer had stopped and was replaced."));
        settle(false);
      }, LIVENESS_TIMEOUT_MS);
      try {
        record.handle.postMessage({ v: PROTOCOL_VERSION, type: "ping" });
      } catch {
        drop(record, new EngineError("worker-failed", "The optimizer could not be reached and was replaced."));
        settle(false);
      }
    });
  }

  /**
   * Post the request to the worker and return the promise that settles when the worker has answered it, or when the request is given up
   * (`job.finished`, which exists from the moment the job is made, so that whatever stops a request, a worker that is dropped or a request that is
   * cancelled, can complete it, and the pump never waits for an answer that cannot come).
   */
  function dispatch(record, job) {
    if (record.dead) {
      // dropped between its ready message and this request: there is nobody to send it to, and nothing would ever answer
      job.finish.reject(new EngineError("worker-failed", "The optimizer stopped before the request could be sent."));
      return job.finished;
    }
    job.record = record;
    record.used = true;
    stats.solves += 1;
    // The watchdog: the budget and the grace after the post of the request, and again after each report of progress of the request (the first Equip now
    // downloads its data inside the request, which on a slow link takes longer than that, and a worker that keeps reporting is not a hang).
    job.watch = () => {
      if (job.settled) return;
      clearTimer(job.timer);
      job.timer = setTimer(() => {
        const error = new EngineError("watchdog", "The optimizer stopped answering and was stopped.");
        drop(record, error);
        job.fail(error);
      }, job.request.budgetMs + WATCHDOG_GRACE_MS);
    };
    job.watch();
    try {
      record.handle.postMessage({ v: PROTOCOL_VERSION, type: "solve", id: job.id, request: job.request });
    } catch {
      drop(record, new EngineError("worker-failed", "The request could not be sent to the optimizer."));
    }
    if (!record.dead) {
      try {
        job.onSent?.();
      } catch {
        // a bug in the page's callback must not break the worker's protocol
      }
    }
    if (job.stopRequested) sendStop(job); // (a stop asked for while the request was waiting for the worker)
    return job.finished;
  }

  /** Post the stop of a farm path to the worker that has its request, once. A worker that cannot be reached with it is dropped. */
  function sendStop(job) {
    const record = job.record;
    if (job.stopSent || record === null || record.dead) return;
    job.stopSent = true;
    try {
      record.handle.postMessage({ v: PROTOCOL_VERSION, type: "stop", id: job.id });
    } catch {
      drop(record, new EngineError("worker-failed", "The stop could not be sent to the optimizer."));
    }
  }

  // ---- requests, one at a time ----

  function makeJob(request, { onProgress, onStep, onSent }, resolve, reject) {
    let finishResolve;
    let finishReject;
    const finished = new Promise((resolveFinished, rejectFinished) => {
      finishResolve = resolveFinished;
      finishReject = rejectFinished;
    });
    finished.catch(() => {}); // (a request that is given up before anyone waits for its answer is not an unhandled rejection)
    const job = {
      id: nextId,
      request,
      onProgress,
      onStep,
      onSent,
      release() {}, // (replaced when a signal is listened to: it stops listening when the request is over)
      pathWatch: request.kind === "scenario" && request.mode === FARM_PATH ? createPathWatch(request) : undefined,
      stopRequested: false,
      stopSent: false,
      settled: false,
      record: null,
      finished,
      finish: { resolve: finishResolve, reject: finishReject },
      timer: null,
      watch() {}, // (replaced when the request is posted: the watchdog)
      succeed(value) {
        if (job.settled) return;
        job.settled = true;
        clearTimer(job.timer);
        job.release();
        resolve(value);
      },
      fail(error) {
        if (!job.settled) {
          job.settled = true;
          clearTimer(job.timer);
          job.release();
          reject(error);
        }
        // Always, also for a request that was given up already (cancelled, say): the pump may still be waiting for the answer to it, and a worker that
        // is dropped now will never give one.
        job.finish.reject(error);
      },
    };
    nextId += 1;
    return job;
  }

  const stillWanted = (job) => {
    if (job.settled) throw new EngineError("cancelled", "The request was cancelled.");
  };

  async function run(job) {
    // After every wait the request is looked at again: it may have been cancelled meanwhile (a cancel can come in the middle of any of them, the
    // question to an idle worker included), and a request that is not wanted any more is not to go on to the next step, least of all to the worker.
    const wanted = async (waiting) => {
      const value = await waiting;
      stillWanted(job);
      return value;
    };
    if (updated) {
      showUi("updated");
      throw new EngineError("engine-load", UPDATED_TEXT);
    }
    const known = await wanted(loadManifest());
    checkAgainstManifest(job.request, known);
    if (job.request.kind === "scenario" && !SCENARIO_MODES_READY.has(job.request.mode)) {
      throw new EngineError("not-implemented", "Scenario requests are not available in the optimizer yet.");
    }
    // The size of the question counts the data of a scenario: the item table (in the manifest) and the bundle of the trio (in the manifest of the trio,
    // read here, only when there is a question to ask).
    let data;
    if (job.request.kind === "scenario" && consent === "unknown") {
      data = { bundle: (await wanted(loadTrioManifest(known, job.request))).bundles.get(job.request.level) };
    }
    await wanted(requireConsent(known, data));
    let record = await wanted(startWorker(known, job));
    if (record.used && !(await wanted(checkAlive(record)))) {
      // it had been stopped without a word: it is dropped, and the request goes to a new worker (from the kept module, so nothing is downloaded)
      record = await wanted(startWorker(known, job));
    }
    return dispatch(record, job);
  }

  async function pump() {
    if (pumping) return;
    pumping = true;
    try {
      while (queue.length > 0) {
        const job = queue.shift();
        if (job.settled) continue;
        current = job;
        try {
          job.succeed(await run(job));
        } catch (error) {
          job.fail(toEngineError(error));
        } finally {
          clearTimer(job.timer);
          current = null;
        }
        if (consentPending === null) closeUi(); // a panel left in its loading state by a request that ended early goes away
      }
    } finally {
      pumping = false;
    }
  }

  // ---- the interface ----

  const isBestKit = (request) => request.kind === "scenario" && request.mode === BEST_KIT;

  function submit(request, callbacks, { scenario, replaceWaiting = false }) {
    return new Promise((resolve, reject) => {
      let clean;
      try {
        clean = validateRequest(request);
        if (scenario && clean.kind !== "scenario") throw new EngineError("bad-request", "runScenario takes a scenario request.");
        if (!supported()) throw new EngineError("unsupported", "This browser cannot run the optimizer.");
      } catch (error) {
        reject(toEngineError(error));
        return;
      }
      const { signal } = callbacks;
      if (signal?.aborted) {
        reject(new EngineError("cancelled", "The request was withdrawn."));
        return;
      }
      // a newer best kit takes the place of the best kits that have not reached the worker (a request that failed the checks above replaced nothing): the ones that wait, and the one the
      // client has begun for, which waits for the visitor's answer or for the worker to start; the one the worker has runs on, and is not in the queue. A request that is refused as busy
      // replaces nothing: the queue is looked at as it would be without the ones it would replace, and they are not destroyed for a request that is not taken.
      const replacing = replaceWaiting && isBestKit(clean);
      const kept = replacing ? queue.filter((job) => !isBestKit(job.request)) : queue;
      if (kept.length >= MAX_WAITING) {
        reject(new EngineError("busy", "Too many requests are waiting for the optimizer."));
        return;
      }
      if (replacing) {
        const replaced = queue.filter((job) => isBestKit(job.request));
        if (current !== null && !current.settled && isBestKit(current.request) && current.record === null) replaced.push(current);
        queue = kept;
        for (const job of replaced) job.fail(new EngineError("cancelled", "The request was replaced by a newer one."));
      }
      const job = makeJob(clean, callbacks, resolve, reject);
      if (signal) {
        const onAbort = () => withdraw(job);
        signal.addEventListener("abort", onAbort, { once: true });
        job.release = () => signal.removeEventListener("abort", onAbort);
      }
      queue.push(job);
      pump().catch(() => {});
    });
  }

  /** Run a request (a model, or a scenario of any mode) and resolve to its result; `onProgress` gets the reports of progress. */
  function solve(request, { onProgress } = {}) {
    return submit(request, { onProgress }, { scenario: false });
  }

  /**
   * Run a scenario request of any of the four modes and resolve to its final result. `onProgress` gets the reports of progress (each carries its `stage`), and `onStep` the message of
   * each step of a farm path as it comes: index 0 is Equip now, then 1 to 8. A fault in a step rejects the request; the steps that came before it were handed to `onStep`.
   * With `replaceWaiting` a best-kit request takes the place of the best-kit requests that have not reached the worker, and with `signal` a request can be taken back, alone (see the
   * head of this file); `onSent` says when the worker has the request.
   */
  function runScenario(request, { onStep, onProgress, onSent, signal, replaceWaiting } = {}) {
    return submit(request, { onProgress, onStep, onSent, signal }, { scenario: true, replaceWaiting: replaceWaiting === true });
  }

  /**
   * Ask the worker to end every farm path that is not finished: the one in flight, and each one that still waits its turn (behind a model request, or behind another path).
   * A path ends before the next step the worker begins after it has seen the stop: the step being worked out when the stop arrives is finished and handed to `onStep` first,
   * and the request then resolves with its final result, whose `stopped` is "stopped" (or the reason the path ended for, when it had ended already). The worker looks for a stop
   * between two steps, after it yields to the event loop; in a browser a stop that is sent from the callback of a step may be delivered after that yield, so the path can end one
   * step later than where the page asked (a test that delivers its messages as microtasks sees it end exactly there). A path that waits is marked, and the stop is sent right
   * after its request when its turn comes: the worker has it before it has begun to load the data, and sees it at its first look, which is after Equip now, so the path ends there
   * with the step 0 and no other. It does nothing when there is no farm path to stop, and it is not a way to end any other request, in flight or waiting: that is cancel().
   */
  function stop() {
    for (const job of current === null ? queue : [current, ...queue]) {
      if (job.settled || job.request.kind !== "scenario" || job.request.mode !== FARM_PATH) continue;
      job.stopRequested = true;
      sendStop(job); // (a job that no worker has yet only waits for dispatch(), which posts its stop right after its request)
    }
  }

  /**
   * Take one request back (its signal fired). A request that waits leaves the queue and is rejected as cancelled. The request the client is on is rejected the same way, and the work it
   * was doing stops: the worker is stopped if the request was given to it (a solve cannot be interrupted from outside), and is left alone if the request had not reached it (a worker that is
   * starting for it goes on, for the next request). No other request is touched, and a request that is over is not either.
   */
  function withdraw(job) {
    if (job.settled) return;
    const error = new EngineError("cancelled", "The request was withdrawn.");
    queue = queue.filter((other) => other !== job);
    job.fail(error);
    if (current === job && worker !== null && job.record === worker) drop(worker, error);
  }

  /** Every request that is not over is cancelled. `byVisitor` is for the Cancel button of the panel: the error then says that the visitor asked for it. */
  function cancel(byVisitor = false) {
    const error = () => {
      const made = new EngineError("cancelled", "The request was cancelled.");
      if (byVisitor === true) made.byVisitor = true;
      return made;
    };
    const jobs = current === null ? queue : [current, ...queue];
    queue = [];
    for (const job of jobs) job.fail(error());
    // a solve cannot be interrupted from outside, so the worker that is busy with it, or starting for it, is stopped; one that is idle is not
    if (worker !== null && current !== null && (current.record === worker || (worker.state === "starting" && worker.startedFor === current))) {
      drop(worker, error());
    }
  }

  /**
   * The Cancel button of the loading panel. While the optimizer is still being downloaded and started it takes the visitor's yes back: the
   * precomputed answers stay, nothing more is downloaded until they ask for the optimizer again, and a reload asks again. Once the
   * optimizer is ready (the panel is still up for the first answer) it only cancels the request.
   */
  function cancelFromPanel() {
    const loading = current !== null && (worker === null || worker.state === "starting");
    if (loading) {
      consent = "declined";
      forgetConsent(storage);
    }
    cancel(true);
  }

  async function askConsent() {
    if (updated) {
      showUi("updated");
      return false;
    }
    if (consent === "granted") return true;
    const answer = await askOnce(await loadManifest(), { bundle: null }); // (the item table is counted, no bundle: no trio is known)
    // With no request waiting, a yes has nothing to load yet: the download starts, under its own panel, at the first request. The panel that the
    // yes turned into the loading panel has nothing to show, so it goes away.
    if (current === null && queue.length === 0) closeUi();
    return answer;
  }

  return {
    solve,
    runScenario,
    stop,
    cancel: () => cancel(),
    askConsent,
    consentState: () => consent,
    stats: () => ({ spawns: stats.spawns, solves: stats.solves, moduleKept: keptModule !== null, updated }),
    dispose() {
      cancel();
      if (worker !== null) drop(worker, new EngineError("cancelled", "The optimizer was shut down.")); // an idle worker too
      closeUi(true);
    },
  };
}

let shared = null;

/**
 * The page's one client. The optimizer is a worker with several megabytes of memory and one question to ask, so the parts of a page that use
 * it (the Upgrade tab, the sliders) share this client instead of making one each. `options` count only for the call that makes it.
 */
export function getEngineClient(options) {
  shared ??= createEngineClient(options);
  return shared;
}

/** Stop the shared client (its worker and the requests waiting for it) so that the next call of getEngineClient makes a new one. For tests. */
export function forgetEngineClient() {
  shared?.dispose();
  shared = null;
}
