// The address of a trio page, read back from whatever a visitor typed or an old link says.
//
// The page of a trio is /trio/<x>-<y>-<z>/ with the classes in the site's own order (pal-mnk-ber), and that is the one address the site has a file for. A hand-typed or old address with the
// classes in another order, in capitals, or without the last slash is answered with the 404 page, and the script of that page (notfound.js) asks this file where it should go instead.
// The answer is the address of a page of the build, made from the build's own spelling of the trio, or nothing: no address is ever made out of what was typed. The steps, in this order:
//
//   1. the path is cut at its slashes, and each piece is decoded once (a piece that cannot be decoded is refused, and an encoded slash can never take the place of a separator, since
//      the cutting is done before it is decoded);
//   2. it is normalised: the slashes at both ends go, and each piece that is left must be letters and hyphens only, which is checked before the case is folded (a character that folds
//      into a letter, such as the Kelvin sign, is not a letter), so that dot-segments, backslashes, encoded slashes, escapes left over from a second encoding and look-alikes are all refused;
//   3. the trio is looked up in the list of the trios the build made (an address in any order finds the same trio), and a trio the list does not have is refused;
//   4. only then is the address made: /trio/<slug>/ from the list, and the query and the fragment of the page as the browser gave them.
//
// Nothing here touches the page or the window; notfound.js passes in the pieces of `location`. Written for ES2021 and Safari 15.

/** The longest address that is looked at: ours are 18 characters, and the slashes that a hand-typed one may have at its ends are cut. */
const MAX_PATH_LENGTH = 200;
const PIECE = /^[A-Za-z-]+$/;
const CODE = /^[a-z]{3}$/;
const LETTERS = /^[A-Za-z]+$/;
const ADDRESS = /^\/trio\/([a-z]{3}-[a-z]{3}-[a-z]{3})\/$/;

/** The address of the page of a trio. */
export function trioPath(slug) {
  return "/trio/" + slug + "/";
}

/**
 * The trios of the build by the letters they are made of: a Map from the codes put in order of the alphabet to the slug in the order of the site's classes. An entry that is not a trio
 * in the shape the build writes (three different codes of three small letters) is left out, and so is a trio that two entries spell differently (it is not guessed between them).
 */
function indexOf(trios) {
  const index = new Map();
  const ambiguous = new Set();
  if (trios === null || typeof trios !== "object" || typeof trios[Symbol.iterator] !== "function") return index;
  for (const slug of trios) {
    if (typeof slug !== "string") continue;
    const codes = slug.split("-");
    if (codes.length !== 3 || !codes.every((code) => CODE.test(code)) || new Set(codes).size !== 3) continue;
    const key = [...codes].sort().join("-");
    if (ambiguous.has(key)) continue;
    if (index.has(key) && index.get(key) !== slug) {
      index.delete(key);
      ambiguous.add(key);
    } else {
      index.set(key, slug);
    }
  }
  return index;
}

/** The pieces of a path, each decoded once, without the slashes at the two ends; null for a path that cannot be read that way. */
function piecesOf(pathname) {
  if (typeof pathname !== "string" || pathname.length === 0 || pathname.length > MAX_PATH_LENGTH || pathname.charAt(0) !== "/") return null;
  const decoded = [];
  for (const piece of pathname.split("/")) {
    try {
      decoded.push(decodeURIComponent(piece));
    } catch {
      return null; // a percent sign that is not an escape, or bytes that are not UTF-8
    }
  }
  let start = 0;
  let end = decoded.length;
  while (start < end && decoded[start] === "") start += 1;
  while (end > start && decoded[end - 1] === "") end -= 1;
  const inner = decoded.slice(start, end);
  return inner.some((piece) => piece === "") ? null : inner; // (an empty piece inside is a doubled slash)
}

/**
 * The trio an address names, as the build spells it, or null. `pathname` is the path of the address as `location.pathname` holds it; `trios` the slugs of the build.
 * "/Trio/BER-MNK-PAL" with "pal-mnk-ber" in the list gives "pal-mnk-ber".
 */
export function canonicalTrio(pathname, trios) {
  const pieces = piecesOf(pathname);
  if (pieces === null || pieces.length !== 2 || !pieces.every((piece) => PIECE.test(piece))) return null;
  if (pieces[0].toLowerCase() !== "trio") return null;
  const codes = pieces[1].toLowerCase().split("-");
  if (codes.length !== 3 || !codes.every((code) => CODE.test(code))) return null;
  return indexOf(trios).get([...codes].sort().join("-")) ?? null;
}

/** The page of the trio that `location` names and where to go for it, `{path, target}` (the target is the path and then the query and the fragment as the browser gave them), or null. */
function locate(location, trios) {
  if (location === null || typeof location !== "object") return null;
  const slug = canonicalTrio(location.pathname, trios);
  if (slug === null) return null;
  const search = typeof location.search === "string" ? location.search : "";
  const hash = typeof location.hash === "string" ? location.hash : "";
  return { path: trioPath(slug), target: trioPath(slug) + search + hash };
}

/**
 * The address of the page of the trio that `location` names, followed by the query and the fragment as the browser gave them, or null when it does not name a trio of the build. It
 * answers for the page's own address as well (a link in the search box of the home page is offered whatever order it was written in), which canonicalUrl does not.
 */
export function trioAddress(location, trios) {
  const found = locate(location, trios);
  return found === null ? null : found.target;
}

/**
 * Where the page at `location` should go, or null: the address of the page of the trio, followed by the query and the fragment as the browser gave them. Null for an address that is not
 * a trio of the build, and for the address of the page itself (going there would load the page again for ever).
 */
export function canonicalUrl(location, trios) {
  const found = locate(location, trios);
  return found === null || location.pathname === found.path ? null : found.target;
}

/** Whether `target` is an address that the 404 page may send a visitor to: the page of a trio of the build, with a query and a fragment. A last check, on what canonicalUrl made. */
export function isSafeTarget(target, trios) {
  if (typeof target !== "string") return false;
  const cut = target.search(/[?#]/);
  const found = ADDRESS.exec(cut === -1 ? target : target.slice(0, cut));
  return found !== null && new Set(indexOf(trios).values()).has(found[1]);
}

/** Which part of the site an address is in, for a visitor who is lost: "trio", "item" or null for the rest. Only the first piece is read, decoded once, in letters. */
export function areaOf(pathname) {
  const pieces = piecesOf(pathname);
  if (pieces === null || pieces.length === 0 || !LETTERS.test(pieces[0])) return null;
  const first = pieces[0].toLowerCase();
  return first === "trio" || first === "item" ? first : null;
}
