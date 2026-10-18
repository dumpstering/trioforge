// The Share button: a link to a kit, copied when the visitor asks.
//
//   createShare({doc, win, announce, id, build}) -> {node, show(on), reset()}
//   slotsOfIdents(idents)                         -> {slots: [[slotIndex, pageId, tier]], left}
//
// `build()` gives the kit to share, `{kit: {v: 1, trio, race, level, slots}, left}` (`left` how many items of it have no place in a link), or null when there is none. The link is the
// address of the page (its own address: the origin and the path, with no query and no fragment of the page's) and `#k=` and the canonical text of the kit (input/kitcode.js,
// encodeKit); it lists the items of the kit, each with its place and its tier, and nothing else: not what the visitor owns, not how many, not where it is, not a value, not a word.
// The words beside the button say so ("This link lists the items in this kit.").
//
// The link is copied on the click of the button and at no other time. When the browser has no clipboard or refuses it, the link is shown in a read-only text field, selected, with
// "Copy the link from here"; the focus stays on the button either way. An item whose key is not "w" and a page number (the number the codec holds) cannot be in a link: it is left out,
// and the visitor is told how many. What is said is said once through the page's live region (`announce`; the control has none of its own).
//
// `id` is the prefix of the ids of the parts: <id>-button, <id>-words, <id>-result, <id>-left, <id>-field, <id>-link. A new answer (`show(false)`, `reset()`) clears what the last click
// said, and a copy that finishes after that is not told.

import { encodeKit, pageIdFromKey } from "../input/kitcode.js";

const WORDS = "This link lists the items in this kit.";
const NO_KIT = "There is no kit to share yet.";
const NOTHING = "Nothing in this kit can be shared.";
const CANNOT = "This kit cannot be shared.";
const COPIED = "Link copied.";
const REFUSED = "The browser would not copy the link.";
const plural = (n, one, many) => (n === 1 ? one : many);

/** The places of a kit of idents ("w112@4", null for a place left empty) as a link holds them, and how many items have a key that is not a page number or a tier that is not a number. */
export function slotsOfIdents(idents) {
  const slots = [];
  let left = 0;
  idents.forEach((ident, slotIndex) => {
    if (ident === null) return;
    const at = ident.lastIndexOf("@");
    const pageId = pageIdFromKey(ident.slice(0, at));
    const tier = Number(ident.slice(at + 1));
    if (pageId === null || !Number.isInteger(tier)) left += 1;
    else slots.push([slotIndex, pageId, tier]);
  });
  return { slots, left };
}

/** The address of the page itself: its origin and its path. */
function addressOf(win) {
  const url = new URL(win.location.href);
  return url.origin + url.pathname;
}

export function createShare({ doc, win, announce, id, build }) {
  const make = (tag, attributes = {}, text) => {
    const node = doc.createElement(tag);
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const button = make("button", { type: "button", id: `${id}-button`, class: "btn-quiet", "aria-describedby": `${id}-words` }, "Share this kit");
  const words = make("span", { id: `${id}-words`, class: "note" }, WORDS);
  const result = make("p", { id: `${id}-result`, class: "note" });
  const leftNote = make("p", { id: `${id}-left`, class: "note" });
  const input = make("input", { type: "text", id: `${id}-link`, class: "share-link", spellcheck: "false", autocomplete: "off" });
  input.readOnly = true;
  const label = make("label", { for: `${id}-link` }, "Copy the link from here");
  const field = make("div", { id: `${id}-field`, class: "share-field" }, undefined);
  field.append(label, input);
  const node = make("div", { id, class: "share" });
  node.append(button, doc.createTextNode(" "), words, result, leftNote, field);
  for (const part of [node, result, leftNote, field]) part.hidden = true;

  let token = 0; // the number of the last click or clearing: a copy that finishes under an older one is of no interest any more

  const say = (text) => {
    if (typeof announce === "function") announce(text);
  };
  const tell = (text) => {
    result.textContent = text;
    result.hidden = text === "";
  };
  const setLeft = (count) => {
    leftNote.textContent = count > 0 ? `${count} ${plural(count, "item", "items")} of this kit cannot be shared` : "";
    leftNote.hidden = count === 0;
  };
  const hideField = () => {
    field.hidden = true;
    input.value = "";
  };
  /** Clear what the last click said and showed. */
  function clear() {
    token += 1;
    tell("");
    setLeft(0);
    hideField();
  }

  function finish(mine, copiedOk, link, leftText) {
    if (mine !== token) return;
    const also = leftText === "" ? "" : ` ${leftText}.`;
    if (copiedOk) {
      hideField();
      tell(COPIED);
      say(COPIED + also);
      return;
    }
    field.hidden = false;
    input.value = link;
    input.setSelectionRange(0, input.value.length); // (the text is selected, and the focus stays on the button: select() would take it to the field in some browsers)
    tell(REFUSED);
    say(`${REFUSED} Copy it from the box under the button.${also}`);
  }

  button.addEventListener("click", () => {
    clear();
    const mine = token;
    const built = build();
    if (built === null || built === undefined) {
      tell(NO_KIT);
      say(NO_KIT);
      return;
    }
    setLeft(built.left);
    const leftText = built.left > 0 ? leftNote.textContent : "";
    const also = leftText === "" ? "" : ` ${leftText}.`;
    if (built.kit.slots.length === 0) {
      tell(NOTHING);
      say(NOTHING + also);
      return;
    }
    let link;
    try {
      link = `${addressOf(win)}#k=${encodeKit(built.kit)}`;
    } catch {
      tell(CANNOT);
      say(CANNOT + also);
      return;
    }
    // the clipboard is written here, on the click, and nowhere else
    const clipboard = win.navigator ? win.navigator.clipboard : undefined;
    let copying;
    try {
      copying = clipboard && typeof clipboard.writeText === "function" ? Promise.resolve(clipboard.writeText(link)) : Promise.reject(new Error("no clipboard"));
    } catch (error) {
      copying = Promise.reject(error);
    }
    copying.then(
      () => finish(mine, true, link, leftText),
      () => finish(mine, false, link, leftText),
    );
  });

  return {
    node,
    /** Show the control (a kit to share is there) or hide it, clearing what the last click said. */
    show(on) {
      clear();
      node.hidden = !on;
    },
    reset: clear,
  };
}
