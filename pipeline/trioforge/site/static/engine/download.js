// Fetching a file of the optimizer and checking it, for the worker: the WebAssembly (worker.js) and the data it reads to work out an answer for a visitor's own
// gear (scenario.js). A file is fetched in pieces, so that how far it is can be reported and a body that is longer than the manifest says is refused while it is
// read, not after; its type and its size are checked against what the manifest lists; its SHA-256 is checked before the caller uses a byte of it. Nothing here
// takes an address from anywhere but its caller, which takes it from the manifest.

/** A failure of the engine that has a code of the protocol (engine-load, bad-request ...) and a message for the visitor to read. */
export class EngineFault extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

/** The address of a file of this site: `path` made absolute against `base` (the worker's own address), refused if it is on another origin. */
export function sameOriginUrl(path, base) {
  const url = new URL(path, base);
  if (url.origin !== new URL(base).origin) throw new EngineFault("engine-load", "The optimizer's file is not on this site.");
  return url;
}

/** The SHA-256 of some bytes as 64 lower-case hexadecimal digits. A browser that has no way to compute one (an insecure page) cannot check the file, so it does not run it. */
export async function sha256Hex(bytes) {
  const subtle = globalThis.crypto?.subtle;
  if (subtle === undefined || typeof subtle.digest !== "function") throw new EngineFault("engine-load", "This browser cannot check the optimizer's file, so it will not run it.");
  const digest = new Uint8Array(await subtle.digest("SHA-256", bytes));
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** A script of the site that a dynamic import could not bring in time (see importWithin). */
export class ImportTimeout extends EngineFault {
  constructor(message) {
    super("engine-load", message);
  }
}

/**
 * `work`, the promise of a dynamic `import()`, as it settles, or an ImportTimeout when it has not settled within `ms`. An import has no time limit of its own: one that hangs would leave
 * the page saying that it is working for good. What `work` does after the limit is not looked at, and the import is not stopped (nothing can stop one), only given up. A browser keeps a
 * failed module fetch until the page is reloaded, and joins a second import of the address to the first one still pending, so what a caller offers after this is a Reload, not a Try again.
 * The limit is the one that the body of a download has (`bodyMs`, protocol.js STARTUP_COMPILE_MS).
 */
export function importWithin(work, ms, noun) {
  let timer;
  const late = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new ImportTimeout(`${noun} took too long to load (more than ${Math.round(ms / 1000)} seconds).`)), ms);
  });
  return Promise.race([work, late]).finally(() => clearTimeout(timer));
}

/** What a file is called in a message, and the type it is served with: the WebAssembly, and the data files (the item table and the bundles). */
export const WASM_FILE = Object.freeze({ type: /^application\/wasm\b/i, noun: "The optimizer file", stalled: "The optimizer download stalled" });
export const DATA_FILE = Object.freeze({ type: /^application\/json\b/i, noun: "The optimizer's data file", stalled: "The optimizer's data download stalled" });

/**
 * Fetch the bytes of a file in pieces (so that progress can be reported), checking their type and their size. A download that stalls is
 * given up: if nothing arrives for `stallMs` (the answer, after the request; the first piece, after the answer; each piece, after the one before) the
 * request is aborted and this fails. The wait ends even for a fetch that takes no notice of the abort. A slow download that keeps delivering is never stopped by this, and the page puts no
 * limit of its own on it (it has the visitor's Cancel). A response that cannot be read in pieces is the one exception to watching for a stall,
 * because nothing can be seen of its body until it is whole: once its answer has begun, the body has `bodyMs` (the limit for the rest of the
 * start), not the stall time. A body that grows past `expected` is cancelled at once.
 */
export async function fetchBytes(url, expected, fetchImpl, onProgress, stallMs, bodyMs, kind = WASM_FILE) {
  const controller = new AbortController();
  let timer;
  let giveUp;
  const stalled = new Promise((_, reject) => {
    giveUp = reject;
  });
  stalled.catch(() => {}); // (it is raced below; when it loses nobody else looks at it)
  const arm = (ms, message) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      giveUp(new EngineFault("engine-load", message)); // (first: it is what is said)
      controller.abort();
    }, ms);
  };
  const armStall = () => arm(stallMs, `${kind.stalled}: nothing arrived for ${Math.round(stallMs / 1000)} seconds.`);
  const before = (promise) => Promise.race([promise, stalled]);
  try {
    onProgress({ phase: "loading", loaded: 0, total: expected });
    armStall();
    const response = await before(fetchImpl(url.href, { credentials: "same-origin", signal: controller.signal }));
    armStall(); // the answer has begun: the time that nothing may arrive for is counted from here, not from the request
    if (!response.ok) throw new EngineFault("engine-load", `${kind.noun} could not be loaded (${response.status}).`);
    const type = response.headers.get("content-type") ?? "";
    if (!kind.type.test(type)) throw new EngineFault("engine-load", `${kind.noun} is served with the wrong type.`);

    if (response.body && typeof response.body.getReader === "function") {
      const reader = response.body.getReader();
      const chunks = [];
      let loaded = 0;
      let reported = 0;
      for (;;) {
        const { done, value } = await before(reader.read());
        if (done) break;
        armStall(); // a byte arrived
        loaded += value.byteLength;
        if (loaded > expected) {
          reader.cancel().catch(() => {});
          throw new EngineFault("engine-load", `${kind.noun} is larger than it should be.`);
        }
        chunks.push(value);
        const step = Math.floor((loaded * 50) / expected);
        if (step > reported && loaded < expected) {
          reported = step;
          onProgress({ phase: "loading", loaded, total: expected });
        }
      }
      if (loaded !== expected) throw new EngineFault("engine-load", `${kind.noun} is incomplete (${loaded} of ${expected} bytes).`);
      const bytes = new Uint8Array(loaded);
      let at = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, at);
        at += chunk.byteLength;
      }
      return bytes;
    }
    // The answer has begun but its body cannot be watched piece by piece: a body that is still arriving is not a stall, so the stall time does not apply to it
    arm(bodyMs, `${kind.noun} took too long to arrive (more than ${Math.round(bodyMs / 1000)} seconds).`);
    const bytes = new Uint8Array(await before(response.arrayBuffer()));
    if (bytes.byteLength !== expected) throw new EngineFault("engine-load", `${kind.noun} is incomplete (${bytes.byteLength} of ${expected} bytes).`);
    return bytes;
  } finally {
    clearTimeout(timer);
  }
}
