"""Parse one eqlwiki item page into plain Python data.

An item page is wikitext with one ``{{Itempage ...}}`` template. :func:`parse_page` takes a
page record (the shape :func:`trioforge.sources.eqlwiki.fetch_pages` yields) and returns either a
:class:`ParsedPage` or a :class:`Skip` that says why the page is not an item:

====================== ===================================================================
``missing``            the wiki has no such page
``namespace``          the page is not in the main namespace (``ns`` is not 0)
``empty``              the page text is blank
``redirect``           the text starts with ``#REDIRECT``
``no-itempage-template`` no Itempage template (a disambiguation page, another template, ...)
``empty-statsblock``   the template has no ``statsblock``, or it is blank: no zero-stat items
``too-large``          the text is over :data:`MAX_PAGE_CHARS` characters (60,000)
``too-complex``        more than :data:`MAX_UNMATCHED` (10) openers (``{{``, ``[``, a tag, a ``<`` that
                       could open one) are never closed, all kinds added together: see
                       :func:`unmatched_openers`;
                       or the wikitext parser gave up on the page (``RecursionError``, a parser error)
====================== ===================================================================

The last two exist because the tokenizer (mwparserfromhell) rescans the rest of the text from every
opener that is never closed: a few KB of ``<br `` or ``{{a|`` repeated takes seconds to minutes.
A page like that is vandalism, not an item, and is skipped before it is parsed. :func:`parse_page`
never raises: whatever the parser cannot take is a ``too-complex`` skip. (The longest page of the
cached pull is under 26,000 characters and has two unclosed openers.)

A parameter written twice in the template is read from its **last** occurrence, as MediaWiki shows
it, with the warning ``duplicate-param``. Names are compared with ASCII-only case folding.

Nothing here interprets the statsblock; that is :mod:`trioforge.data.normalize`. This module
only reads the page's *structure*, and what leaves it is text, never markup to be trusted:

* every string is decoded from HTML entities exactly once (``&amp;lt;`` becomes the text
  ``&lt;``), so the next stage must not decode again;
* links become names (see below), external links keep only their anchor text, never the
  URL, and a ``[javascript:...]`` or ``[data:...]`` link keeps only its anchor text too;
* ``<`` and ``>`` are *not* removed here (``itemname = Ring<script>`` stays as typed). The
  normalizer's ``sanitize_text`` does that for everything it writes.

Names from links: the label if there is one, else the target with its ``#fragment`` and its
parenthetical disambiguator removed (``Innoruuk_(God)`` is ``Innoruuk``). A *quest* is the other way
round: it is stored by its link **target**, because that is the title the quest is looked up by, with its
parenthesis kept ("Runnyeye Warbeads (Kaladim Rogue)" and "(Rivervale)" are different quests) and its
``#fragment`` dropped, and the label of the link, which names one test among the many that a page holds,
is kept apart for display (``ParsedPage.quest_labels``).

The template's parameters read here are ``itemname``, ``statsblock``, ``notes``,
``lucy_img_ID``, ``focus_effect``, and the source lists:

* ``dropsfrom``: a top-level line (a link or plain text) is a zone; ``*`` lines under it are
  its NPCs; a line with commas and no bullets is several zones, and the NPCs under such a line
  belong to every one of them. ``{{VeliousGray|...}}``-style wrapper templates are unwrapped, also
  inside HTML tags; ``{{Loc|zone|(x, y)}}`` is a place on a map and is dropped. A line with no link
  names a zone only if it can be a name: prose, a code or a map position (a digit, a sentence mark,
  markup or more than 8 words, in the line or in any comma-separated part of it) names nothing
  (:func:`_is_prose`). A list in which the zones are written as bullets is read as it is here (one
  entry with no zone); :func:`trioforge.data.normalize.promote_bullet_zones` makes the bullets that
  are known zones zones. Some lines are notes, not zones: ``None``, ``N O T _ C L A S S I C``,
  ``Located in the following locations:`` are skipped, ``ITEM REMOVED FROM GAME`` skips the line and
  adds the page flag ``removed_note``, and a line that is only a parenthesis, ``(ToV East mobs)``,
  becomes an entry of the ``notes`` list of the zone (or zones) before it;
* ``soldby``: ``{{ItemWhereRow | zone | vendor | | coordinates}}`` rows (also ``ItemWhereRowVel``;
  every vendor and every zone of a row is kept), or lines laid out like ``dropsfrom``. Each entry is
  ``{"zone", "npc"}``;
* ``relatedquests``: one quest per link or line (see above for the link target and the label);
* ``foraged``: the zones the item can be foraged in, one or more to a line whatever the bullets'
  depth, read with the same care as a zone line (a link gives its zone, a line of prose none);
* a crafting parameter (any name containing ``craft``). ``recipes`` is not that: it lists what the
  item is *used in*. The list is read in one of two layouts. The wiki writes recipes: a trade
  skill line (``* [[Blacksmithing]] (Trivial: 148)``), a yield, a container line (``** In
  [[Forge|Zorblax Forge]]:``, also ``In: ...``, ``In [[A]] or [[B]]:``) and the ingredients
  (``:: {{SmIcon|504}} 1 x [[Name]] - Bought``); each container gets the recipe's ingredients, and a
  recipe with only a skill has no container. A plainer outline (a container line, its ingredients one
  level deeper) is read too: the outermost lines are containers.

If a source parameter is absent or blank, the page section of the same meaning is used instead:
"Sold by", "Related quests" or "Player crafted".

**Page flags.** Banner templates on the page itself (not inside the Itempage template, a comment or
``<nowiki>``) give ``ParsedPage.page_flags``, sorted: ``{{Delete}}`` is ``wiki_banner_delete``,
``{{:Does Not Exist}}`` is ``wiki_banner_does_not_exist``, ``{{DNE}}`` is ``wiki_banner_dne`` and
``{{revamped}}`` is ``wiki_banner_revamped``; the drop-list note ``ITEM REMOVED FROM GAME`` gives
``removed_note``. The normalizer turns them into item flags and the evidence ladder reads those.
Categories are the ``[[Category:...]]`` links wherever they stand, inside a template's parameters too
(some pages end the template after their categories), and never in a comment or ``<nowiki>``.

Each warning is ``{"code", "field"}``: a short code and the name of the thing it is about,
never text from the page.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

import mwparserfromhell
from mwparserfromhell.parser import ParserError
from mwparserfromhell.nodes import (
    Argument,
    Comment,
    ExternalLink,
    Heading,
    HTMLEntity,
    Tag,
    Template,
    Text,
    Wikilink,
)

__all__ = [
    "MAX_PAGE_CHARS",
    "MAX_UNMATCHED",
    "SKIP_REASONS",
    "ParsedPage",
    "Skip",
    "first_link_parts",
    "first_link_target",
    "link_target",
    "parse_page",
    "plain_text",
    "unmatched_openers",
]

SKIP_REASONS = (
    "missing",
    "namespace",
    "empty",
    "redirect",
    "no-itempage-template",
    "empty-statsblock",
    "too-large",
    "too-complex",
)

MAX_PAGE_CHARS = 60_000  # the longest item page of the cached pull is under 26,000
MAX_UNMATCHED = 10  # unclosed openers, all kinds added together, that a page may have (the real maximum is 2)
MAX_NOTES = 10  # notes kept on one drop zone


@dataclass(frozen=True)
class Skip:
    """A page that is not an item, and why (one of SKIP_REASONS)."""

    pageid: int | None
    title: str | None
    reason: str


@dataclass(frozen=True)
class ParsedPage:
    """The structure of one item page. See the module docstring for each field's meaning."""

    pageid: int
    revid: int | None
    title: str
    name: str
    statsblock_lines: list[str]
    notes_lore: str | None
    drops: list[dict]  # {"zone": str | None, "npcs": [str]} and, when the page has some, "notes": [str]
    sold_by: list[dict]  # {"zone": str | None, "npc": str}
    quests: list[str]  # the targets of the quest links: the titles a quest is looked up by
    crafted: list[dict]  # {"container": str | None, "ingredients": [str]}
    categories: list[str]
    era_tags: list[str]
    lucy_img_id: int | None
    focus_effects: list[str] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)  # {"code": str, "field": str}
    page_flags: list[str] = field(default_factory=list)  # wiki_banner_* and removed_note, sorted
    foraged: list[str] = field(default_factory=list)  # zones the item can be foraged in
    quest_labels: list[dict] = field(default_factory=list)  # {"title": link target, "label": the link's own text}


# ---- small text helpers --------------------------------------------------------------------

# Every pattern here runs on wiki text that anyone could have vandalised into 2 MB of repeated
# openers, so none may rescan the rest of the text from each opener: the unbounded ones are bounded.
_REDIRECT = re.compile(r"\s*#\s*redirect\b", re.IGNORECASE | re.ASCII)
_LINE_BREAK = re.compile(r"<br\b[^>]{0,200}>|\r\n|\r|\n", re.IGNORECASE | re.ASCII)  # <br>, <br/>, <br clear="all">
_PARENTHETICAL = re.compile(r"\s*\([^()]*\)\s*$")
# A namespace prefix may be written with spaces or underscores around the colon (MediaWiki ignores both),
# and a link that starts with a colon, [[:Category:X]], is a plain link to the page, not a namespaced one.
_NAMESPACED = re.compile(r"[\s_]*(?:file|image|media|category)[\s_]*:", re.IGNORECASE | re.ASCII)
_CATEGORY_TITLE = re.compile(r"[\s_]*category[\s_]*:(.*)$", re.IGNORECASE | re.ASCII | re.DOTALL)
# [javascript:...] and [data:...] are not links to the parser (unknown scheme), so they would stay
# as text with the URL in it. Reduce them to their anchor text, before the text is parsed and again after its
# entities are decoded (javascript&#58; is the same link).
_SCRIPT_LINK = re.compile(
    r"(?<!\[)\[\s{0,20}(?:javascript|data|vbscript)\s{0,20}:[^\s\]]{0,300}(?:\s+([^\]]{0,200}))?\]", re.IGNORECASE | re.ASCII
)
_ERA_KEY = re.compile(r"(\S.*) era")
_NOTE_ONLY = re.compile(r"'{0,5}\s*\(([^()]*)\)\s*'{0,5}")  # a line that is only a parenthesis (no parenthesis inside)
_DIGITS = re.compile(r"[0-9]{1,15}")


# A "<" that could open a tag but does not: either a letter, "/" or "!" follows and no complete, short tag
# comes of it, or something else that is not a space follows ("<1x>", "<$x>", "<<x>") and a ">" is near. The
# tokenizer reads both as the start of a tag and rescans for its end. A "<" before a space, a digit with no ">"
# near, or at the end of the text ("a < b", "<3", "x <= 5") opens nothing and is fast, so it is not counted.
_BAD_ANGLE = re.compile(r"<(?:(?=[A-Za-z/!])(?![A-Za-z/!][^<>]{0,200}>)|(?=[^\s>A-Za-z/!])(?=[^>]{0,200}>))")
_BRACES = re.compile(r"\{\{|\}\}")
_SQUARE = re.compile(r"[\[\]]")
_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]*)[^<>]{0,200}?(/?)>")
_VOID_TAGS = frozenset({"br", "hr", "wbr", "img", "meta", "link", "input"})
# Tags whose end tag is optional in HTML: a page that leaves a dozen <li> open is ordinary wikitext, not an attack.
# The tokenizer reads li, dt, dd, th, td and tr as "single" tags (linear time); <p> and <option> it rescans from, so
# their unclosed openers count once there are more than MAX_UNCLOSED_SLOW of them (500 take 0.02 s, 8,000 take 5 s).
_OPTIONAL_END_TAGS = frozenset({"li", "p", "td", "tr", "th", "dd", "dt", "option"})
_SLOW_OPTIONAL_TAGS = frozenset({"p", "option"})
MAX_UNCLOSED_SLOW = 500


_ASCII_LOWER = {code: code + 32 for code in range(ord("A"), ord("Z") + 1)}


def _ascii_lower(text: str) -> str:
    """``text`` with only the ASCII capitals made small, so that names are never matched through Unicode
    case folding (the dotless i, the Turkish capital I with a dot and the long s fold onto ASCII letters)."""
    return text.translate(_ASCII_LOWER)


def unmatched_openers(text: str) -> int:
    """How many openers in ``text`` are never closed, all kinds added together.

    The kinds are ``{{`` (closed by ``}}``), ``[`` (by ``]``), HTML tags (``<span>`` by ``</span>``;
    void tags such as ``<br>`` open nothing, and neither do the tags whose end tag HTML makes optional:
    ``li p td tr th dd dt option``) and a ``<`` that could open a tag but starts no complete one (not a lone
    ``<`` before a space, as in ``a < b``). A page with one typo is fine; a page with more than
    :data:`MAX_UNMATCHED` unclosed openers of any kinds is not an item page. It is one linear pass per kind.
    The exception to the exception: more than :data:`MAX_UNCLOSED_SLOW` unclosed ``<p>`` or ``<option>`` together
    count (the tokenizer is quadratic on them).
    """
    total = len(_BAD_ANGLE.findall(text))
    for pattern, opener in ((_BRACES, "{{"), (_SQUARE, "[")):
        depth = 0
        for match in pattern.finditer(text):
            if match.group() == opener:
                depth += 1
            elif depth:
                depth -= 1
        total += depth
    open_tags: dict[str, int] = {}
    for match in _TAG.finditer(text):
        closing, name, self_closing = match.group(1), _ascii_lower(match.group(2)), match.group(3)
        if closing:
            if open_tags.get(name):
                open_tags[name] -= 1
        elif not self_closing and name not in _VOID_TAGS:
            open_tags[name] = open_tags.get(name, 0) + 1
    slow = sum(count for name, count in open_tags.items() if name in _SLOW_OPTIONAL_TAGS)
    counted = sum(count for name, count in open_tags.items() if name not in _OPTIONAL_END_TAGS)
    return total + counted + (slow if slow > MAX_UNCLOSED_SLOW else 0)


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_comments(text: str) -> str:
    """``text`` without its ``<!-- ... -->`` comments (an unterminated one stays as typed), in one pass."""
    if "<!--" not in text:
        return text
    kept = []
    position = 0
    while True:
        start = text.find("<!--", position)
        if start < 0:
            break
        end = text.find("-->", start + 4)
        if end < 0:
            break
        kept.append(text[position:start])
        position = end + 3
    kept.append(text[position:])
    return "".join(kept)


def _neutralize(text: str) -> str:
    return _SCRIPT_LINK.sub(lambda match: match.group(1) or "", text)


def _template_key(name: Any) -> str:
    """A template name reduced for comparison: no comments, no ``Template:``, one space, ASCII-lowercased."""
    text = _ascii_lower(re.sub(r"[\s_]+", " ", _strip_comments(str(name))).strip())
    return re.sub(r"^template\s*:\s*", "", text)


def _param_key(name: Any) -> str:
    """A parameter name reduced for comparison: no spaces or underscores, ASCII-lowercased."""
    return _ascii_lower(re.sub(r"[\s_]+", "", _strip_comments(str(name))))


def _warn(code: str, where: str) -> dict:
    return {"code": code, "field": where}


# Tags whose text is the text: presentation, lists and tables. Anything else (script, style,
# meta, iframe, ...) is left as typed, for the sanitizer to defuse, rather than interpreted.
_TRANSPARENT_TAGS = frozenset(
    "span b i u s strike em strong small big sub sup font center code tt abbr cite q mark blockquote "
    "onlyinclude noinclude includeonly".split()
)
_BLOCK_TAGS = frozenset("p div li ul ol dl dt dd table tr td th tbody thead tfoot caption hr".split())
_DROPPED_TAGS = frozenset({"ref", "references"})


def _namespaced(title: Any, *, unescape: bool = True) -> bool:
    """True if a link title is a File:, Image:, Media: or Category: page (which names nothing), judged from the
    title as written: a leading colon, ``[[:File:X.png]]``, makes it a plain link, and the parser would drop that
    colon from the flattened text."""
    text = str(title)
    return _NAMESPACED.match(html.unescape(text) if unescape else text) is not None


def _flatten_node(node: Any) -> str:
    """Text of one node, with entities left as typed (they are decoded once, at the end)."""
    if isinstance(node, Text):
        return node.value
    if isinstance(node, HTMLEntity):
        return str(node)
    if isinstance(node, Wikilink):
        if _namespaced(node.title):
            return ""
        label = _flatten(node.text) if node.text is not None else ""
        return label if label.strip() else _flatten(node.title)
    if isinstance(node, ExternalLink):
        # Only an anchor text survives; a bare URL, a link without anchor and the URL itself never do.
        return _flatten(node.title) if node.brackets and node.title is not None else ""
    if isinstance(node, Tag):
        tag = str(node.tag).strip().casefold()
        if tag == "br":
            return " "
        if tag == "nowiki":
            return str(node.contents) if node.contents is not None else ""
        if tag in _DROPPED_TAGS:
            return ""
        if tag in _TRANSPARENT_TAGS or tag in _BLOCK_TAGS:
            inner = _flatten(node.contents) if node.contents is not None else ""
            return f" {inner} " if tag in _BLOCK_TAGS else inner
        return str(node)
    if isinstance(node, Heading):
        return f" {_flatten(node.title)} "
    return ""  # comments, templates, {{{arguments}}}


def _flatten(code: Any) -> str:
    if code is None:
        return ""
    return "".join(_flatten_node(node) for node in code.nodes)


def plain_text(wikitext: Any, *, unescape: bool = True) -> str:
    """Wikitext as plain text on one line.

    Links give their label (or target), external links only their anchor text, comments and
    templates vanish, presentational tags are unwrapped, other tags stay as typed. With
    ``unescape`` (the default) HTML entities are decoded, once; pass ``unescape=False`` for text
    that has been decoded already, so that it is not decoded a second time. A ``[javascript:...]``
    link is reduced to its anchor text, before parsing and again after decoding (decode first, then
    neutralize: ``javascript&#58;`` is the same link).
    """
    code = mwparserfromhell.parse(_neutralize(str(wikitext)))
    text = _flatten(code)
    return _collapse(_neutralize(html.unescape(text) if unescape else text))


# ---- names from links ----------------------------------------------------------------------


def link_target(raw_title: Any, *, keep_parens: bool = False, unescape: bool = True) -> str:
    """A link target as a name: no namespace colon, ``#fragment`` or underscores, and (unless
    ``keep_parens``) no trailing parenthetical disambiguator.

    ``unescape=False`` is for a target that has been decoded already (see :func:`plain_text`).
    """
    title = plain_text(raw_title, unescape=unescape).lstrip(":")
    title = _collapse(title.split("#", 1)[0].replace("_", " "))
    if not keep_parens:
        stripped = _PARENTHETICAL.sub("", title)
        title = stripped or title
    return title


def first_link_target(wikitext: Any, *, keep_parens: bool = False, unescape: bool = True) -> str | None:
    """The target of the first link in ``wikitext`` that names something (not a File: or Category:
    link), as :func:`link_target` gives it, or None if there is no such link."""
    for link in mwparserfromhell.parse(_neutralize(str(wikitext))).filter_wikilinks():
        if _namespaced(link.title, unescape=unescape):
            continue
        target = link_target(link.title, keep_parens=keep_parens, unescape=unescape)
        if target:
            return target
    return None


def first_link_parts(wikitext: Any, *, unescape: bool = True) -> tuple[str, str, str] | None:
    """``(target, label, target with its parenthetical)`` of the first link in ``wikitext`` that names
    something, or None. The label is the link's own text, "" when it has none; the targets are as
    :func:`link_target` gives them."""
    for link in mwparserfromhell.parse(_neutralize(str(wikitext))).filter_wikilinks():
        if _namespaced(link.title, unescape=unescape):
            continue
        target = link_target(link.title, unescape=unescape)
        if target:
            label = plain_text(link.text, unescape=unescape) if link.text is not None else ""
            return target, label, link_target(link.title, keep_parens=True, unescape=unescape)
    return None


def _link_name(link: Wikilink, *, keep_parens: bool) -> str:
    if _namespaced(link.title):
        return ""  # a File: or Category: link names nothing
    label = plain_text(link.text) if link.text is not None else ""
    return label or link_target(link.title, keep_parens=keep_parens)


def _names(content: str, *, keep_parens: bool = False, split_commas: bool = False, zone_like: bool = False) -> list[str]:
    """The names in one line of a source list.

    If the line holds links, the names are the links' (text next to a link, such as "(female)",
    is a note and is dropped); an external link gives its anchor text. A line with no link is
    one name, or, with ``split_commas``, one name per comma-separated part. With ``zone_like`` (the line is
    to name zones) a line with no link whose text, or any comma-separated part of it, reads like prose, a code
    or a map position names nothing (:func:`_is_prose`); the notes a zone line may hold stay, for the caller.
    """
    code = mwparserfromhell.parse(_neutralize(content))
    names: list[str] = []
    loose: list[Any] = []
    for node in code.nodes:
        if isinstance(node, Wikilink):
            name = _link_name(node, keep_parens=keep_parens)
            if name:
                names.append(name)
        elif isinstance(node, ExternalLink):
            anchor = plain_text(node.title) if node.brackets and node.title is not None else ""
            if anchor:
                names.append(anchor)
        elif not isinstance(node, (Comment, Template, Argument)):
            loose.append(node)
    if names:
        return names
    text = _collapse(_neutralize(html.unescape("".join(_flatten_node(node) for node in loose))))
    if not text:
        return []
    parts = [part for part in (_collapse(piece) for piece in text.split(",")) if part] if split_commas else [text]
    if zone_like and not all(_is_zone_note(part) or not _is_prose(part) for part in parts):
        return []
    return parts


# ---- source lists --------------------------------------------------------------------------


_DROPPED_TEMPLATES = frozenset({"loc"})  # templates of a source list whose parameters are not names


def _unwrap(code: Any, rows: list[tuple[str, str]]) -> tuple[str, bool]:
    """Render ``code`` with templates unwrapped: a row template is collected into ``rows``, any other
    keeps its unnamed parameters. Returns the text and whether it met a template."""
    parts: list[str] = []
    met = False
    for node in code.nodes:
        if isinstance(node, Comment):
            continue
        if isinstance(node, Tag) and node.contents is not None:
            inner, inner_met = _unwrap(node.contents, rows)  # a wrapper or a row inside <span>...</span> too
            if inner_met:
                met = True
                node.contents = inner
            parts.append(str(node))
            continue
        if isinstance(node, Template):
            met = True
            key = _template_key(node.name)
            if key.startswith("itemwhererow"):
                cells = [str(param.value) for param in node.params if not param.showkey]
                if len(cells) >= 2:
                    rows.append((cells[0], cells[1]))
                continue
            if key in _DROPPED_TEMPLATES:
                continue  # a place on a map: {{Loc|Zone|(x, y)}} names nothing
            for param in node.params:
                if not param.showkey:
                    parts.append(_unwrap(param.value, rows)[0])
                    parts.append(" ")
            continue
        parts.append(str(node))
    return "".join(parts), met


def _source_lines(wikitext: str) -> tuple[list[tuple[int, str]], list[tuple[str, str]]]:
    """A source list as ``(depth, content)`` lines plus its ItemWhereRow rows ``(zone, vendor)``.

    Depth is the number of bullet marks, 0 for a plain line and -1 for a ``== heading ==``.
    """
    rows: list[tuple[str, str]] = []
    text = wikitext
    for _ in range(4):  # a wrapper inside a tag inside a wrapper surfaces on the next pass
        text, met = _unwrap(mwparserfromhell.parse(_neutralize(text)), rows)
        if not met:
            break
    lines: list[tuple[int, str]] = []
    for piece in _LINE_BREAK.split(text):
        piece = _collapse(piece)  # also keeps the patterns below from rescanning a long run of spaces
        if not piece:
            continue
        bullets = re.match(r"([*#]+)\s*(.*)$", piece)
        heading = re.match(r"(=+)\s*(.*?)\s*=+$", piece)
        if bullets:
            lines.append((len(bullets.group(1)), bullets.group(2)))
        elif heading:
            lines.append((-1, heading.group(2)))
        else:
            lines.append((0, piece))
    return lines, rows


def _unique(items: list) -> list:
    seen: set = set()
    result = []
    for item in items:
        key = repr(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


# Lines of a drop list that are notes, not zones, as _note_key writes them. "ITEM REMOVED FROM GAME" is
# the one that matters: the page says the item is gone.
_REMOVED_NOTE = "itemremovedfromgame"
_ZONE_NOTES = frozenset({"none", "locatedinthefollowinglocations", "notclassic"})


def _note_key(text: str) -> str:
    """A note line reduced for comparison: ASCII-lowercased, letters and digits only ("N O T _ C L A S S I C")."""
    return re.sub(r"[^a-z0-9]+", "", _ascii_lower(text))


def _is_zone_note(text: str) -> bool:
    return _note_key(text) in _ZONE_NOTES or _note_key(text) == _REMOVED_NOTE


# A line of a zone list that has no link is a zone name only if it can be one. These are the signs of text that is
# not: a digit (a map position, a count, a date), a sentence mark, markup, a code, or too many words. Prose that
# happens to look like a name ("Confirmed Drop Zones") is not told apart; it stays a name and is reported unmapped.
_PROSE_CHARS = re.compile(r"[0-9.;:!?\"<>+_]")
MAX_ZONE_WORDS = 8


def _is_prose(text: str) -> bool:
    """True for text that cannot be a zone name: it has a digit or a sentence mark, markup or a code character,
    more than :data:`MAX_ZONE_WORDS` words, or no letter at all."""
    return len(text.split()) > MAX_ZONE_WORDS or _PROSE_CHARS.search(text) is not None or not any(c.isalpha() for c in text)


def _zone_names(content: str) -> tuple[list[str], bool]:
    """The zones one line of a zone list names (links; or plain names, which prose is not), and whether
    the line says "ITEM REMOVED FROM GAME". The other notes of a drop list name nothing."""
    zones: list[str] = []
    removed = False
    for name in _names(content, split_commas=True, zone_like=True):
        key = _note_key(name)
        if key == _REMOVED_NOTE:
            removed = True
        elif key not in _ZONE_NOTES:
            zones.append(name)
    return zones, removed


def _parse_drops(wikitext: str) -> tuple[list[dict], bool]:
    """The drop zones with their NPCs, and whether the list says the item was removed from the game."""
    lines, _ = _source_lines(wikitext)
    drops: list[dict] = []
    current: list[dict] = []  # the entries of the last zone line: its NPCs belong to every one of them
    removed = False
    for depth, content in lines:
        note = _NOTE_ONLY.fullmatch(content)
        if note:  # "(ToV East mobs)": a note on the zone or zones before it
            text_of_note = plain_text(note.group(1))
            if text_of_note:
                for entry in current:
                    entry.setdefault("notes", []).append(text_of_note)
            continue
        if depth <= 0:
            zones, says_removed = _zone_names(content)
            removed = removed or says_removed
            if zones:
                current = [{"zone": zone, "npcs": []} for zone in zones]
                drops.extend(current)
        else:
            npcs = _names(content)
            if not npcs:
                continue
            if not current:
                current = [{"zone": None, "npcs": []}]
                drops.extend(current)
            for entry in current:
                entry["npcs"].extend(npcs)
    for drop in drops:
        drop["npcs"] = _unique(drop["npcs"])
        if "notes" in drop:
            drop["notes"] = _unique(drop["notes"])[:MAX_NOTES]
    return drops, removed


def _parse_sold_by(wikitext: str) -> list[dict]:
    """The vendors with their zones: every vendor and every zone of a row, and the vendors under a
    zone line for every zone of that line."""
    lines, rows = _source_lines(wikitext)
    sold: list[dict] = []
    for zone_cell, vendor_cell in rows:
        zones: list[str | None] = _zone_names(zone_cell)[0] or [None]
        for zone in zones:
            sold.extend({"zone": zone, "npc": vendor} for vendor in _names(vendor_cell))
    groups: list[tuple[list[str | None], list[str]]] = [([None], [])]  # (the zones of a zone line, its vendors)
    for depth, content in lines:
        if depth <= 0:
            named = _zone_names(content)[0]
            if named:
                groups.append((named, []))
        else:
            groups[-1][1].extend(_names(content))
    for zones_of_line, vendors in groups:
        for zone in zones_of_line:
            sold.extend({"zone": zone, "npc": vendor} for vendor in vendors)
    return _unique(sold)


def _quest_entries(content: str) -> list[tuple[str, str]]:
    """``(name, label)`` for each quest in one line of a related-quests list.

    A link gives the **target** (page title: its parenthetical kept, its ``#fragment`` and underscores dropped),
    which is what a quest is looked up by, and the label of the link, "" if it has none, says nothing new or the
    link points into the page itself (then the label is the name). An external link gives its anchor text; a line
    with no link is one name. Text next to a link is a note and is dropped.
    """
    code = mwparserfromhell.parse(_neutralize(content))
    entries: list[tuple[str, str]] = []
    loose: list[Any] = []
    for node in code.nodes:
        if isinstance(node, Wikilink):
            if _namespaced(node.title):
                continue
            # "[[#Part|label]]" points into the page itself: no title (link_target would read "#Part" as a list item)
            target = "" if str(node.title).lstrip().startswith("#") else link_target(node.title, keep_parens=True)
            label = plain_text(node.text) if node.text is not None else ""
            if target:
                entries.append((target, "" if label == target else label))
            elif label:
                entries.append((label, ""))
        elif isinstance(node, ExternalLink):
            anchor = plain_text(node.title) if node.brackets and node.title is not None else ""
            if anchor:
                entries.append((anchor, ""))
        elif not isinstance(node, (Comment, Template, Argument)):
            loose.append(node)
    if entries:
        return entries
    text = _collapse(_neutralize(html.unescape("".join(_flatten_node(node) for node in loose))))
    return [(text, "")] if text else []


def _parse_quests(wikitext: str) -> tuple[list[str], list[dict]]:
    """The quests of a related-quests list: their link targets, and the labels of the links that have one
    (``{"title": target, "label": label}``, in order, a target listed once however many labels it has)."""
    lines, _ = _source_lines(wikitext)
    entries = [entry for _, content in lines for entry in _quest_entries(content)]
    names = _unique([name for name, _ in entries])
    labels = _unique([{"title": name, "label": label} for name, label in entries if label])
    return names, labels


def _parse_foraged(wikitext: str) -> list[str]:
    """The zones a foraged list names, one or more to a line, whatever the depth of its bullets."""
    lines, _ = _source_lines(wikitext)
    return _unique([zone for depth, content in lines if depth >= 0 for zone in _zone_names(content)[0]])


# ---- crafting -------------------------------------------------------------------------------

# The trade skills a recipe is filed under (the first link of its skill line). A name that is not here
# is not a skill, so a plain outline's "[[Forge]]" stays a container.
_TRADE_SKILLS = frozenset(
    {
        "alchemy",
        "baking",
        "blacksmithing",
        "brewing",
        "fishing",
        "fletching",
        "jewelcrafting",
        "jewelry making",
        "make poison",
        "poison making",
        "pottery",
        "research",
        "smithing",
        "spell research",
        "tailoring",
        "tinkering",
    }
)
_NO_CONTAINER_NAMES = frozenset({"none", "n/a", "na", "unknown", "?"})
# Linear-time patterns: each is anchored, or cannot restart inside a run it has already read.
_IN_LINE = re.compile(r"[\s:*#;]*in\b\s*:?(.*)", re.IGNORECASE | re.DOTALL)
_COMBINE_LINE = re.compile(r"[\s:*#;]*combine\b", re.IGNORECASE)
_NON_TRADESKILL = re.compile(r"[\s:*#;\[]*non[- ]?tradeskill\b", re.IGNORECASE)
_QUANTITY = re.compile(r"(?<![\w.])\d+\s*x\s*(?=\[\[)", re.IGNORECASE)
_TRIVIAL = re.compile(r"\(\s{0,20}trivial\b", re.IGNORECASE)
_YIELD = re.compile(r"\byields?\b", re.IGNORECASE)
_RETURNS = re.compile(r"\b(?:on failure|returns?)\b", re.IGNORECASE)
_CONTAINER_SPLIT = re.compile(r"\s*,\s*|\s+or\s+", re.IGNORECASE)
_CONTAINER_SEPARATORS = re.compile(r"\b(?:or|and)\b|[\s,;:/&|]+", re.IGNORECASE)  # what may sit between containers


def _links(content: str) -> list[Wikilink]:
    """The links in ``content`` that name something (not File: or Category: links), in order."""
    code = mwparserfromhell.parse(_neutralize(content))
    return [link for link in code.filter_wikilinks() if not _namespaced(link.title)]


def _first_link_name(content: str) -> str:
    """The label (else the target) of the first link of ``content``, or the empty string."""
    links = _links(content)
    return _link_name(links[0], keep_parens=True) if links else ""


def _skill_name(content: str) -> str:
    """The first link of a skill line as a bare lower-case name: ``[[Skill Tailoring|Tailoring]]`` is ``tailoring``."""
    name = _first_link_name(content).casefold().lstrip(":")
    return name[len("skill ") :] if name.startswith("skill ") else name


def _craft_kind(content: str) -> str:
    """What one line of a crafting list is.

    ``container`` (an "In ..." line), ``combine`` (a "Combine [[A]] in a [[B]]" sentence), ``ingredient``
    ("N x [[Name]]"), ``skill`` (a trade skill, or a "(Trivial: N)" line), ``other-skill`` (a
    "Non-Tradeskill" line: a recipe with no trade skill), ``yield`` (a yield or a failure / return
    note) or ``generic`` (anything else).
    """
    if _IN_LINE.match(content):
        return "container"
    if _COMBINE_LINE.match(content):
        return "combine"
    if _QUANTITY.search(content):
        return "ingredient"
    if _NON_TRADESKILL.match(content):
        return "other-skill"
    if _TRIVIAL.search(content) or _skill_name(content) in _TRADE_SKILLS:
        return "skill"
    if _YIELD.search(content) or _RETURNS.search(content):
        return "yield"
    return "generic"


def _container_names(rest: str) -> list[str]:
    """The containers an "In ..." line names: its links' labels (else targets), else its plain words.

    Links in a row, separated only by commas or "or" / "and", are alternatives. Words between two links
    end the list: in "In [[Tome Binder]] Dropped by [[an orc]]:" the second link is not a container.
    """
    names: list[str] = []
    for node in mwparserfromhell.parse(_neutralize(rest)).nodes:
        if isinstance(node, Wikilink):
            if not _namespaced(node.title):
                names.append(_link_name(node, keep_parens=True))
        elif names and isinstance(node, Text) and _CONTAINER_SEPARATORS.sub("", node.value).strip():
            break
    if not names:
        text = plain_text(rest).strip(" :;")
        names = [piece for piece in (_collapse(part) for part in _CONTAINER_SPLIT.split(text)) if piece]
    return [name for name in names if name and name.casefold() not in _NO_CONTAINER_NAMES]


def _ingredient_name(content: str) -> str:
    """The page named by the first link after the quantity of an ingredient line (its target, not its label)."""
    quantity = _QUANTITY.search(content)
    links = _links(content[quantity.end() :] if quantity else content)
    return link_target(links[0].title, keep_parens=True) if links else ""


def _parse_crafted(wikitext: str) -> list[dict]:
    """The recipes of a crafting list as ``{"container", "ingredients"}`` entries, in order.

    Pages use one of two layouts (see the module docstring); a list with no recipe line at all is read
    as the plain outline.
    """
    lines, _ = _source_lines(wikitext)
    kinds = [(depth, content, _craft_kind(content)) for depth, content in lines if content]
    if any(kind != "generic" for _, _, kind in kinds):
        return _parse_crafted_recipes(kinds)
    return _parse_crafted_outline(wikitext)


def _parse_crafted_recipes(kinds: list[tuple[int, str, str]]) -> list[dict]:
    crafted: list[dict] = []
    current: dict | None = None
    skill_depth = 1  # the depth of the skill line of the current recipe: its ingredients are deeper than that

    def start(skill: bool = False) -> dict:
        return {"containers": [], "ingredients": [], "skill": skill}

    def flush() -> None:
        if current is None:
            return
        if current["containers"]:
            crafted.extend({"container": name, "ingredients": list(current["ingredients"])} for name in current["containers"])
        elif current["ingredients"]:
            crafted.append({"container": None, "ingredients": list(current["ingredients"])})
        elif current["skill"]:
            crafted.append({"container": None, "ingredients": []})  # made with a skill, no container written

    for depth, content, kind in kinds:
        if kind in ("skill", "other-skill"):
            flush()
            current = start(skill=kind == "skill")
            skill_depth = max(depth, 1)  # a plain skill line still has its ingredients two bullets down
        elif kind == "container":
            names = _container_names(_IN_LINE.match(content).group(1))
            if not names:
                continue
            if current is None or current["ingredients"]:
                flush()
                current = start()
            current["containers"].extend(names)
        elif kind == "combine":
            links = _links(content)
            if len(links) >= 2:
                if current is None or current["containers"] or current["ingredients"]:
                    flush()
                    current = start()
                current["skill"] = False  # the sentence says how it is made: no skill-only recipe
                current["containers"].append(_link_name(links[-1], keep_parens=True))
                current["ingredients"].extend(link_target(link.title, keep_parens=True) for link in links[:-1])
                flush()
                current = None
        elif kind == "ingredient" or (kind == "generic" and depth > skill_depth and "[[" in content):
            name = _ingredient_name(content) if kind == "ingredient" else _first_link_name(content)
            if name:
                if current is None:
                    current = start()
                current["ingredients"].append(name)
    flush()
    for entry in crafted:
        entry["ingredients"] = _unique(entry["ingredients"])
    return _unique(crafted)


def _parse_crafted_outline(wikitext: str) -> list[dict]:
    """A plain outline: container lines at the outermost level, their ingredients one level deeper.

    A ``== heading ==`` line counts as the outermost level only when the bullets under the headings all have
    one level (``=== Forge ===`` then ``* Ore``): then each heading is a container. When the bullets have
    two levels, the first level is the containers and a heading above them is only a title, so one
    subheading never demotes the level-1 bullets to ingredients.
    """
    lines, _ = _source_lines(wikitext)
    named = [(depth, content) for depth, content in lines if content]
    if not named:
        return []
    bullet_levels = {depth for depth, _ in named if depth > 0}
    headings_title_only = len(bullet_levels) > 1
    if headings_title_only:
        named = [(depth, content) for depth, content in named if depth >= 0]
    outermost = min(depth for depth, _ in named)
    crafted: list[dict] = []
    current: list[dict] = []  # the entries of the last container line: its ingredients belong to each of them
    for depth, content in named:
        if depth <= outermost:
            current = []
            for container in _names(content, keep_parens=True):
                if container.casefold() in _NO_CONTAINER_NAMES:
                    continue  # "None" names no container: what follows has none
                entry = {"container": container, "ingredients": []}
                crafted.append(entry)
                current.append(entry)
        else:
            ingredients = _names(content)
            if not ingredients:
                continue
            if not current:
                entry = {"container": None, "ingredients": []}
                crafted.append(entry)
                current = [entry]
            for entry in current:
                entry["ingredients"].extend(ingredients)
    for entry in crafted:
        entry["ingredients"] = _unique(entry["ingredients"])
    return crafted


def _parse_name_list(wikitext: str) -> list[str]:
    lines, _ = _source_lines(wikitext)
    return _unique([name for _, content in lines for name in _names(content)])


# ---- the statsblock -------------------------------------------------------------------------


MAX_PARSER_WARNINGS = 50  # of one kind: a page of 400,000 templates must not make 400,000 warnings


def _prune(code: Any, warnings: list[dict]) -> None:
    """Remove comments and templates from ``code`` and unwrap ``<nowiki>``, in one pass and in place.

    A template is removed whole, its inner templates with it, and counted once. Templates inside a
    tag, a link or a heading are found too. The work is linear in the size of the text.
    """
    kept = []
    for node in code.nodes:
        if isinstance(node, Comment):
            continue
        if isinstance(node, Template):
            if len(warnings) < MAX_PARSER_WARNINGS:
                warnings.append(_warn("nested-template", "statsblock"))
            continue
        if isinstance(node, Tag):
            if str(node.tag).strip().casefold() == "nowiki":
                kept.append(Text(str(node.contents) if node.contents is not None else ""))
                continue
            if node.contents is not None:
                _prune(node.contents, warnings)
        elif isinstance(node, Wikilink):
            _prune(node.title, warnings)
            if node.text is not None:
                _prune(node.text, warnings)
        elif isinstance(node, ExternalLink):
            _prune(node.url, warnings)
            if node.title is not None:
                _prune(node.title, warnings)
        elif isinstance(node, Heading):
            _prune(node.title, warnings)
        kept.append(node)
    code.nodes[:] = kept


def _statsblock_lines(value: Any, warnings: list[dict]) -> list[str]:
    """The statsblock's lines: comments and nested templates removed, nowiki unwrapped, split
    on ``<br>`` (any case, attributes or slash) and newlines, decoded once, stripped."""
    code = mwparserfromhell.parse(str(value))
    _prune(code, warnings)
    lines = [html.unescape(piece).strip() for piece in _LINE_BREAK.split(str(code))]
    return [line for line in lines if line]


# ---- sections, categories, eras ------------------------------------------------------------

_SECTION_PARAMS = {"sold by": "soldby", "related quests": "relatedquests", "player crafted": "crafted"}


def _sections(code: Any) -> dict[str, str]:
    """The text of the "Sold by", "Related quests" and "Player crafted" sections, by the name of
    the parameter each stands for. A section runs to the next heading of its own rank or higher."""
    found: dict[str, str] = {}
    nodes = code.nodes
    index = 0
    while index < len(nodes):
        node = nodes[index]
        index += 1
        if not isinstance(node, Heading):
            continue
        key = _SECTION_PARAMS.get(_ascii_lower(_collapse(plain_text(node.title))))
        if key is None or key in found:
            continue
        body = []
        while index < len(nodes):
            following = nodes[index]
            if isinstance(following, Heading) and following.level <= node.level:
                break
            body.append(str(following))
            index += 1
        found[key] = "".join(body)
    return found


def _categories(code: Any) -> list[str]:
    """The page's categories in document order, once each: ``[[Category:X]]`` links wherever they stand, inside a
    template's parameters too (some pages end the template after their categories). A comment and ``<nowiki>``
    are not parsed as links, and ``[[:Category:X]]`` is a plain link, not a category."""
    names: list[str] = []
    seen: set[str] = set()
    for link in code.ifilter_wikilinks():
        match = _CATEGORY_TITLE.match(str(link.title))
        if match:
            name = _collapse(html.unescape(match.group(1)).replace("_", " "))
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _era_name(text: str) -> str:
    """``FearHateRevamp`` stays as written, ``classic`` becomes ``Classic``: each word starts with a capital."""
    return " ".join(word[:1].upper() + word[1:] for word in text.split())


def _era_tags(code: Any, categories: list[str]) -> list[str]:
    """The era tags ("Kunark Era"), in the spelling the page uses and sorted; one per tag whatever its spelling.

    A category or a template whose name ends in " Era" is a tag. Two spellings of one tag (compared with
    ASCII-lowercased keys) give the one that sorts first, so the answer never depends on hash order.
    """
    names = [_collapse(category) for category in categories]
    names += [_collapse(_strip_comments(str(template.name)).replace("_", " ")) for template in code.filter_templates()]
    spellings: dict[str, set[str]] = {}
    for name in names:
        name = re.sub(r"^template\s*:\s*", "", name, flags=re.IGNORECASE | re.ASCII)
        key = _ascii_lower(name)
        match = _ERA_KEY.fullmatch(key)
        if match:
            display = _era_name(name[: len(match.group(1))]) + " Era"
            spellings.setdefault(_ascii_lower(display), set()).add(display)
    return sorted(min(found) for found in spellings.values())


# ---- the page -------------------------------------------------------------------------------

_PARAM_FIELDS = {
    "itemname": "itemname",
    "statsblock": "statsblock",
    "notes": "notes",
    "dropsfrom": "dropsfrom",
    "soldby": "soldby",
    "relatedquests": "relatedquests",
    "foraged": "foraged",
    "lucyimgid": "lucy_img_id",
    "focuseffect": "focus_effect",
}


def _blank(value: Any) -> bool:
    return not _strip_comments(str(value)).strip()


def _notes_lore(notes: Any) -> str | None:
    for template in mwparserfromhell.parse(str(notes)).filter_templates():
        if _template_key(template.name) != "item lore":
            continue
        if not template.params:
            return None
        first = template.params[0]
        # "{{Item Lore|a = b}}" reads "a " as a name; the author meant the text "a = b".
        text = str(first.value) if not first.showkey or _param_key(first.name) == "1" else str(first)
        return plain_text(text) or None
    return None


_BANNERS = {
    "delete": "wiki_banner_delete",
    "does not exist": "wiki_banner_does_not_exist",
    "dne": "wiki_banner_dne",
    "revamped": "wiki_banner_revamped",
}


def _banner_flags(code: Any) -> list[str]:
    """The ``wiki_banner_*`` flags of the banner templates on the page itself, sorted.

    Templates at the top level or inside tags count; those inside another template's parameters (the
    Itempage template's, say), a comment or ``<nowiki>`` do not.
    """
    found: set[str] = set()

    def walk(nodes: Any) -> None:
        for node in nodes:
            if isinstance(node, Template):
                flag = _BANNERS.get(_template_key(node.name).lstrip(":").strip())
                if flag:
                    found.add(flag)
            elif isinstance(node, Tag):
                if _ascii_lower(str(node.tag).strip()) not in ("nowiki", "pre") and node.contents is not None:
                    walk(node.contents.nodes)

    walk(code.nodes)
    return sorted(found)


def parse_page(page: dict) -> ParsedPage | Skip:
    """Parse one page record (``pageid``, ``ns``, ``title``, ``revid``, ``content``, ``missing``).

    Never raises for any page text: a page that is not an item comes back as a :class:`Skip`, and a page
    that the wikitext parser cannot take (``RecursionError``, a parser error) as ``Skip("too-complex")``.
    """
    try:
        return _parse_page(page)
    except (RecursionError, ParserError):
        return Skip(page.get("pageid"), page.get("title"), "too-complex")


def _parse_page(page: dict) -> ParsedPage | Skip:
    pageid = page.get("pageid")
    title = page.get("title")

    def skip(reason: str) -> Skip:
        return Skip(pageid, title, reason)

    if page.get("missing"):
        return skip("missing")
    namespace = page.get("ns")
    if namespace is not None and namespace != 0:
        return skip("namespace")
    content = page.get("content")
    if not isinstance(content, str) or not content.strip():
        return skip("empty")
    if _REDIRECT.match(content):
        return skip("redirect")
    if len(content) > MAX_PAGE_CHARS:
        return skip("too-large")
    if unmatched_openers(content) > MAX_UNMATCHED:
        return skip("too-complex")

    code = mwparserfromhell.parse(content)
    itempages = [t for t in code.filter_templates() if _template_key(t.name) == "itempage"]
    if not itempages:
        return skip("no-itempage-template")
    warnings: list[dict] = []
    if len(itempages) > 1:
        warnings.append(_warn("multiple-itempage", "itempage"))

    params: dict[str, Any] = {}  # reduced name -> Wikicode; the last of a repeated name wins, as MediaWiki shows it
    for param in itempages[0].params:
        if not param.showkey:
            continue
        key = _param_key(param.name)
        if key in params and key in _PARAM_FIELDS:
            warnings.append(_warn("duplicate-param", _PARAM_FIELDS[key]))
        params[key] = param.value

    lines = _statsblock_lines(params["statsblock"], warnings) if "statsblock" in params else []
    if not lines:
        return skip("empty-statsblock")

    name = plain_text(params["itemname"]) if "itemname" in params else ""
    name = name or (title if isinstance(title, str) else "")

    lucy = None
    if "lucyimgid" in params:
        text = _strip_comments(str(params["lucyimgid"])).strip()
        if _DIGITS.fullmatch(text):
            lucy = int(text)
        elif text:
            warnings.append(_warn("bad-lucy-id", "lucy_img_id"))

    sections = _sections(code)

    def source(key: str) -> str:
        """The text of a source parameter if it is not blank, else the page section of that meaning."""
        if key in params and not _blank(params[key]):
            return str(params[key])
        return sections.get(key, "")

    crafting_keys = sorted(key for key in params if "craft" in key)
    crafting_text = "\n".join(str(params[key]) for key in crafting_keys if not _blank(params[key]))
    categories = _categories(code)
    drops, removed_note = _parse_drops(source("dropsfrom"))
    quests, quest_labels = _parse_quests(source("relatedquests"))
    page_flags = sorted({*_banner_flags(code), *(["removed_note"] if removed_note else [])})
    return ParsedPage(
        pageid=pageid,
        revid=page.get("revid"),
        title=title if isinstance(title, str) else "",
        name=name,
        statsblock_lines=lines,
        notes_lore=_notes_lore(params["notes"]) if "notes" in params else None,
        drops=drops,
        sold_by=_parse_sold_by(source("soldby")),
        quests=quests,
        crafted=_parse_crafted(crafting_text or sections.get("crafted", "")),
        categories=categories,
        era_tags=_era_tags(code, categories),
        lucy_img_id=lucy,
        focus_effects=_parse_name_list(source("focuseffect")) if "focuseffect" in params else [],
        warnings=warnings,
        page_flags=page_flags,
        foraged=_parse_foraged(source("foraged")),
        quest_labels=quest_labels,
    )
