"""Read the items of a zone from EQ Legends Tools (eqlegendstools.com): fetch the pages, parse the tooltips.

The maintainers decided on 2026-10-25 that the zone page https://eqlegendstools.com/zones/nektropos-castle/ is the source of
truth for every item it lists (46 of them): for those items its tooltip overrides the wiki's copy, and every other item keeps
its source. This module is the whole of that source:

* ``fetch`` reads the zone page, collects its ``/items/<slug>/`` links and fetches each item page::

      python -m trioforge.sources.eqlegendstools fetch --out sources/eqlegendstools/2026-10-25 [--refresh]

  into ``raw/zone-<slug>.html`` and ``raw/item-<slug>.html`` (the pages as the site sent them) and ``manifest.json``,
  written last, so its presence means the run finished. **A page already in the folder is not fetched again** (a rerun
  of the same folder asks for nothing it has; ``--refresh`` asks for everything), as the wiki path's ``--resume`` does.
  ``python -m trioforge.sources.eqlwiki fetch --eqlegendstools-out DIR`` runs the same fetch after the wiki's, so that
  the normal pipeline fetch picks it up.
* :func:`parse_item_page` reads the tooltip block of an item page: the same tooltip text the wiki's statsblock holds
  (``Slot: EAR | AC: 6 MANA: +5 | ...``), then ``Drops From: <zone> : <creature>`` and ``Item stats shown at upgrade level 0``.
  Its lines go to the statsblock parser of :mod:`trioforge.data.normalize` (through :class:`ParsedPage`, as a wiki page's do), so
  an item has the same shape as a wiki item (slots, stats, classes, races, effects, weapon fields, drops).
  A field the page leaves out stays unknown: the parser never makes up a zero.
* :func:`load_items` reads a finished fetch and returns the catalog items.

**Politeness.** One request a second at most (the shared :class:`trioforge.sources.http.PoliteClient`), one fetch at a time
(:class:`trioforge.sources.eqlwiki.FetchLock`, a lock file of its own), the user agent names the project and its about page,
and only ``https://eqlegendstools.com/zones/<slug>/`` and ``https://eqlegendstools.com/items/<slug>/`` are ever asked for:
the site's robots.txt disallows ``/api/``, ``/scripts/`` and the rest, and :func:`allowed_url` is the only door a request
goes through (the client refuses any other address, and a redirect is never followed).

The scheduled sources check (``scripts/sources_check.py``) never asks this site: a test holds that script to the two hosts it
has always asked, and this module is not imported there.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from trioforge.sources.itempage import ParsedPage

from .eqlwiki import REPO_ROOT, FetchLock, _atomic_write, _json_bytes, _Refusal
from .http import FetchError, PoliteClient

__all__ = [
    "HOST",
    "LOCK_PATH",
    "SOURCE_ID",
    "SOURCE_NAME",
    "USER_AGENT",
    "ZONES",
    "EqltItem",
    "ParseError",
    "Snapshot",
    "allowed_url",
    "item_url",
    "load_items",
    "main",
    "parse_item_page",
    "read_snapshot",
    "run_fetch",
    "to_parsed_page",
    "zone_item_slugs",
    "zone_url",
]

HOST = "eqlegendstools.com"
SOURCE_NAME = "EQ Legends Tools"
SOURCE_ID = "eqlegendstools"  # the value of ``origin.source`` in the catalog
ZONES = ("nektropos-castle",)  # the zone pages that are the source of truth for the items they list
LOCK_PATH = REPO_ROOT / "sources" / ".eqlegendstools.lock"  # a lock of its own: this is another host than the wiki's

# The user agent names the project and the page of its site that says who runs it (as the weekly checks' does).
USER_AGENT = "TrioForge-extractor/0.1 (+https://trioforge.pages.dev/about/; non-commercial fan project; 1 request/s)"

_SLUG = r"[a-z0-9][a-z0-9-]{0,95}"  # (96 at most: the catalog key is "rlt-" and the slug, 100 at most)
_ALLOWED_PATH = re.compile(rf"/(?:zones|items)/{_SLUG}/")
_ITEM_LINK = re.compile(rf"""href=["']/items/({_SLUG})/["']""")
_SLUG_ONLY = re.compile(_SLUG)
MAX_PAGE_CHARS = 2_000_000  # the zone page is 145 KB and an item page 61 KB; a page over this is not one of theirs
MAX_ITEMS_PER_ZONE = 500
_BACKSTAB = re.compile(r"\bBackstab\s+dmg\s*:", re.IGNORECASE)  # this site writes "Backstab Dmg: 13"; the statsblock parser reads "BACKSTAB: 13"
_PROC_RATE = re.compile(r"proc rate\s*:\s*([+-]?\d{1,4})\s*%", re.IGNORECASE)  # this site writes a proc's rate on a line of its own
_EFFECT_LINE = re.compile(r"[a-z ]*effect\s*:", re.IGNORECASE)
_STAT_LEVEL_NOTE = re.compile(r"item stats shown at upgrade level\s+(\d+)", re.IGNORECASE)


class ParseError(ValueError):
    """A page cannot be read as the page of an item. One line; it never holds the page's text."""


# ---- addresses: the only door a request goes through ----------------------------------------------------------------


def allowed_url(url: str) -> bool:
    """True only for ``https://eqlegendstools.com/zones/<slug>/`` and ``https://eqlegendstools.com/items/<slug>/``.

    No other scheme, host, port, user name, query, fragment or path (``/api/``, ``/scripts/`` and the rest are disallowed
    by the site's robots.txt) is ever asked for.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.hostname == HOST
        and parts.netloc == HOST  # no user name, no port
        and port is None
        and not parts.query
        and not parts.fragment
        and _ALLOWED_PATH.fullmatch(parts.path) is not None
    )


def zone_url(slug: str) -> str:
    if not _SLUG_ONLY.fullmatch(slug):
        raise ValueError("a zone slug is small letters, digits and hyphens")
    return f"https://{HOST}/zones/{slug}/"


def item_url(slug: str) -> str:
    if not _SLUG_ONLY.fullmatch(slug):
        raise ValueError("an item slug is small letters, digits and hyphens")
    return f"https://{HOST}/items/{slug}/"


def _get(client: PoliteClient, url: str) -> str:
    return client.get_text(url, allowed_url)


# ---- the zone page ---------------------------------------------------------------------------------------------------


def zone_item_slugs(page: str) -> list[str]:
    """The ``/items/<slug>/`` links of a zone page, each once, in the order the page gives them."""
    if len(page) > MAX_PAGE_CHARS:
        raise ParseError("the zone page is too large")
    slugs = list(dict.fromkeys(_ITEM_LINK.findall(page)))
    if len(slugs) > MAX_ITEMS_PER_ZONE:
        raise ParseError("the zone page lists too many items")
    return slugs


# ---- the item page ---------------------------------------------------------------------------------------------------


@dataclass
class EqltItem:
    """What one item page says, before the statsblock parser reads it.

    ``lines`` are the tooltip lines the statsblock parser reads (flags first, as the wiki's statsblock has them, then
    ``Slot: ...`` and the rest); the drop source is kept apart, because the wiki's statsblock does not hold it.
    ``upgrade_level`` is the level the stats are shown at (0 is the base item). ``categories`` are the page's own labels
    (``Focus Effect Item, BiS Gear Item``).
    """

    slug: str
    name: str
    lines: list[str]
    flags_text: str | None = None
    drops: list[dict] = field(default_factory=list)  # {"zone": str, "npcs": [str]}
    upgrade_level: int | None = None
    categories: list[str] = field(default_factory=list)


def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
    for name, value in attrs:
        if name == "class" and value:
            return set(value.split())
    return set()


def _attr(attrs: list[tuple[str, str | None]], wanted: str) -> str | None:
    for name, value in attrs:
        if name == wanted:
            return value
    return None


class _ItemReader(HTMLParser):
    """Collects the first ``aside.tooltip-card`` of an item page: title, flags, lines (with the zone link of a drop line) and the upgrade note."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_card = False
        self.card_depth = 0
        self.title: list[str] = []
        self.flags: list[str] = []
        self.note: list[str] = []
        self.lines: list[list[str]] = []
        self.zone_links: list[list[str]] = []  # per line: the text of its source-zone-link
        self.eyebrow: list[str] = []
        self.h1: list[str] = []
        self._target: list[str] | None = None
        self._target_tag = ""
        self._line_index = -1
        self._in_line = False
        self._zone_link: list[str] | None = None
        self._done = False
        self._in_script = 0
        self._after_zone_link: dict[int, list[str]] = {}
        self._seen_zone_link_in_line = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = _classes(attrs)
        if tag in ("script", "style"):
            self._in_script += 1
            return
        if tag == "p" and "eyebrow" in classes and not self.eyebrow:
            self._target, self._target_tag = self.eyebrow, "p"
        elif tag == "h1" and not self.h1:
            self._target, self._target_tag = self.h1, "h1"
        if self._done:
            return
        if tag == "aside" and "tooltip-card" in classes and not self.in_card:
            self.in_card, self.card_depth = True, 1
            return
        if not self.in_card:
            return
        if tag == "aside":
            self.card_depth += 1
        if tag == "p" and "tooltip-title" in classes:
            self._target, self._target_tag = self.title, "p"
        elif tag == "p" and "tooltip-flags" in classes:
            self._target, self._target_tag = self.flags, "p"
        elif tag == "p" and _attr(attrs, "id") == "itemUpgradeNote":
            self._target, self._target_tag = self.note, "p"
        elif tag == "li":
            self.lines.append([])
            self.zone_links.append([])
            self._after_zone_link[len(self.lines) - 1] = []
            self._line_index, self._in_line = len(self.lines) - 1, True
            self._seen_zone_link_in_line = False
        elif tag == "a" and self._in_line and "source-zone-link" in classes:
            self._zone_link = self.zone_links[self._line_index]
        elif tag == "br" and self._in_line:
            self.lines[self._line_index].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._in_script = max(0, self._in_script - 1)
            return
        if tag == self._target_tag and self._target is not None:
            self._target, self._target_tag = None, ""
        if not self.in_card or self._done:
            return
        if tag == "aside":
            self.card_depth -= 1
            if self.card_depth <= 0:
                self.in_card, self._done = False, True
        elif tag == "li":
            self._in_line = False
        elif tag == "a" and self._zone_link is not None:
            self._zone_link = None
            self._seen_zone_link_in_line = True

    def handle_data(self, data: str) -> None:
        if self._in_script:
            return
        if self._target is not None:
            self._target.append(data)
        if self.in_card and not self._done and self._in_line:
            self.lines[self._line_index].append(data)
            if self._zone_link is not None:
                self._zone_link.append(data)
            elif self._seen_zone_link_in_line:
                self._after_zone_link[self._line_index].append(data)


def _text(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", "".join(parts))).strip()


def _split_names(text: str) -> list[str]:
    """The creatures of a drop line: ``The Game Master`` is one; several are separated by commas, a semicolon or ``and``... only where the site separates them with ``,``."""
    return [name for name in (part.strip() for part in text.split(",")) if name]


def _fold_proc_rate(lines: list[str], rate: str) -> bool:
    """Put a ``Proc Rate: -75%`` line of this site into the effect line before it, as the wiki writes a proc's rate: ``Effect: X (Combat, Rate -75%) at Level 45``.

    The statsblock parser reads the rate from the effect's own line only; a line of its own is an unparsed line. An unsigned rate is a rate above the base one, as the
    wiki's ``Rate +50%``. An effect line with no bracket gets ``(Rate N%)``. False (the line stays as it is, and the parser warns) if no effect line comes before it or its brackets are broken.
    """
    signed = rate if rate[0] in "+-" else "+" + rate
    for index in range(len(lines) - 1, -1, -1):
        if _EFFECT_LINE.match(lines[index]):
            has_open, has_close = "(" in lines[index], ")" in lines[index]
            if not has_open and not has_close:  # an effect with no bracket at all: the rate gets one of its own (it adds no kind, and the parser reads the name before it)
                lines[index] = f"{lines[index].rstrip()} (Rate {signed}%)"
                return True
            if not (has_open and has_close) or lines[index].index("(") > lines[index].index(")"):
                return False
            before, _, after = lines[index].partition(")")
            lines[index] = f"{before}, Rate {signed}%){after}"
            return True
    return False


def parse_item_page(page: str, slug: str) -> EqltItem:
    """Read the tooltip of an item page. :class:`ParseError` if the page has no tooltip card, no name, or shows another upgrade level than 0."""
    if not _SLUG_ONLY.fullmatch(slug):
        raise ParseError("not an item slug")
    if len(page) > MAX_PAGE_CHARS:
        raise ParseError("the item page is too large")
    reader = _ItemReader()
    try:
        reader.feed(page)
        reader.close()
    except (AssertionError, ValueError, RecursionError):
        raise ParseError("the item page cannot be read as HTML") from None
    if not reader._done and not reader.lines:
        raise ParseError(f"item {slug}: the page has no tooltip block")
    name = _text(reader.title) or _text(reader.h1)
    if not name:
        raise ParseError(f"item {slug}: the tooltip has no item name")
    lines: list[str] = []
    drops: list[dict] = []
    for index, parts in enumerate(reader.lines):
        text = _text(parts)
        if not text:
            continue
        lowered = text.lower()
        if lowered.startswith("drops from"):
            zone = _text(reader.zone_links[index])
            after = _text(reader._after_zone_link[index]).lstrip(":").strip()
            if not zone:  # no link: "Drops From: Zone : Creature" as plain text
                body = text.split(":", 1)[1] if ":" in text else ""
                zone, _, after = (piece.strip() for piece in body.partition(":"))
            drops.append({"zone": zone or None, "npcs": _split_names(after)})
        elif lowered.startswith("farming speed"):
            continue  # the site's own advice, not a fact of the item
        elif lowered.startswith("note:"):
            continue  # a long acquisition note (a quest's steps): prose, not a field
        elif re.fullmatch(r"charges:\s*infinite", lowered):
            continue  # no number to store: the effect keeps no charge count, and none is made up
        elif (rate := _PROC_RATE.fullmatch(text)) is not None and _fold_proc_rate(lines, rate.group(1)):
            continue  # (it is now part of the effect's own line, as the wiki writes it)
        else:
            lines.append(_BACKSTAB.sub("BACKSTAB:", text))
    level_match = _STAT_LEVEL_NOTE.search(_text(reader.note))
    if level_match is None:  # a page that does not say which level its stats are shown at cannot be taken for the base item
        raise ParseError(f"item {slug}: the page has no note 'Item stats shown at upgrade level N'")
    upgrade_level = int(level_match.group(1))
    if upgrade_level != 0:
        raise ParseError(f"item {slug}: the stats are shown at upgrade level {upgrade_level}, not the base item")
    flags_text = _text(reader.flags).replace(" · ", ", ") or None  # (this site separates the flags with a middle dot; the statsblock with commas)
    categories = [c for c in (part.strip() for part in _text(reader.eyebrow).split(",")) if c]
    return EqltItem(
        slug=slug,
        name=name,
        lines=lines,
        flags_text=flags_text,
        drops=drops,
        upgrade_level=upgrade_level,
        categories=categories,
    )


def to_parsed_page(item: EqltItem) -> ParsedPage:
    """The :class:`ParsedPage` the statsblock parser reads: the page's flags line and its tooltip lines as the statsblock, the drop source as the drops.

    The page id is 1 and the title the item's name: :func:`trioforge.data.catalog.merge_eqlegendstools` replaces the key and the
    ``wiki`` field, which belong to the wiki and which an item of this site does not have.
    """
    statsblock = ([item.flags_text] if item.flags_text else []) + list(item.lines)
    return ParsedPage(
        pageid=1,
        revid=None,
        title=item.name,
        name=item.name,
        statsblock_lines=statsblock,
        notes_lore=None,
        drops=[{"zone": d["zone"], "npcs": list(d["npcs"])} for d in item.drops],
        sold_by=[],
        quests=[],
        crafted=[],
        categories=[],
        era_tags=[],
        lucy_img_id=None,
    )


# ---- fetching --------------------------------------------------------------------------------------------------------


def _raw_zone(raw: Path, zone: str) -> Path:
    return raw / f"zone-{zone}.html"


def _raw_item(raw: Path, slug: str) -> Path:
    return raw / f"item-{slug}.html"


def _pages_digest(pages: dict[str, str]) -> str:
    """The hash of the item pages, made from their text with the line ends normalised. A file read back as text has them LF whatever the site sent, so the hash of a fetch and
    the hash of its reading must be of the same text, or a page sent with CRLF would fail the check on its first reading."""
    digest = hashlib.sha256()
    for slug in sorted(pages):
        text = pages[slug].replace("\r\n", "\n").replace("\r", "\n")
        digest.update(slug.encode("ascii") + b"\0" + text.encode("utf-8") + b"\0")
    return digest.hexdigest()


def _read_cached(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return text or None


def run_fetch(
    client: PoliteClient,
    out: Path,
    today: date,
    *,
    zones: Sequence[str] = ZONES,
    refresh: bool = False,
    say=print,
) -> dict:
    """Fetch the zone pages and the item pages they list into ``out`` (see the module docstring). Returns the manifest.

    A page that is already in ``out/raw`` is read, not fetched, unless ``refresh``. The manifest is removed first and written last.
    """
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").unlink(missing_ok=True)
    requests = 0
    slugs_by_zone: dict[str, list[str]] = {}
    pages: dict[str, str] = {}
    for zone in zones:
        path = _raw_zone(raw, zone)
        text = None if refresh else _read_cached(path)
        fresh = text is None
        if fresh:
            text = _get(client, zone_url(zone))
            requests += 1
        slugs = zone_item_slugs(text)
        if not slugs:  # checked before anything is written: a page that lists nothing is not kept
            raise FetchError(zone_url(zone), None, "the zone page lists no items")
        if fresh:
            _atomic_write(path, text.encode("utf-8"))
        slugs_by_zone[zone] = slugs
    wanted = list(dict.fromkeys(slug for slugs in slugs_by_zone.values() for slug in slugs))
    for number, slug in enumerate(wanted, 1):
        path = _raw_item(raw, slug)
        text = None if refresh else _read_cached(path)
        if text is None:
            text = _get(client, item_url(slug))
            requests += 1
            parse_item_page(text, slug)  # a page that cannot be read stops the run here: it is not cached and the manifest ("the run finished") is not written
            _atomic_write(path, text.encode("utf-8"))
        pages[slug] = text
        if number % 10 == 0:
            say(f"item pages {number}/{len(wanted)}")
    manifest = {
        "date": out.name if re.fullmatch(r"\d{4}-\d{2}-\d{2}", out.name) else today.isoformat(),
        "site": f"https://{HOST}/",
        "zones": {zone: slugs for zone, slugs in slugs_by_zone.items()},
        "items": len(wanted),
        "sha256": _pages_digest(pages),
    }
    _atomic_write(out / "manifest.json", _json_bytes(manifest, indent=1))
    say(f"done: {len(wanted)} items from {len(zones)} zone page(s), {requests} request(s) made, in {out}")
    return manifest


# ---- reading a finished fetch ---------------------------------------------------------------------------------------


@dataclass
class Snapshot:
    """A finished fetch, read: the parsed pages in the order the zone page lists them."""

    date: str
    sha256: str
    zones: dict[str, list[str]]
    items: list[EqltItem]


def read_snapshot(directory: str | Path) -> Snapshot:
    """Read a finished fetch. :class:`ParseError` if it is not whole or a page cannot be read; the message is one line."""
    root = Path(directory)
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ParseError("manifest.json of the EQ Legends Tools fetch is missing or unreadable (is the fetch finished?)") from None
    if not isinstance(manifest, dict) or not isinstance(manifest.get("zones"), dict) or not isinstance(manifest.get("date"), str):
        raise ParseError("manifest.json of the EQ Legends Tools fetch is not in the form the fetcher writes")
    raw = root / "raw"
    items: list[EqltItem] = []
    seen: set[str] = set()
    pages: dict[str, str] = {}
    zones: dict[str, list[str]] = {}
    for zone, slugs in manifest["zones"].items():
        if not isinstance(zone, str) or not _SLUG_ONLY.fullmatch(zone) or not isinstance(slugs, list):
            raise ParseError("manifest.json lists a zone it should not")
        zone_page = _read_cached(_raw_zone(raw, zone))
        if zone_page is None or zone_item_slugs(zone_page) != slugs:
            raise ParseError(f"raw/zone-{zone}.html is missing or does not list the items the manifest says")
        zones[zone] = list(slugs)
        for slug in slugs:
            if not isinstance(slug, str) or not _SLUG_ONLY.fullmatch(slug):
                raise ParseError("manifest.json lists an item it should not")
            if slug in seen:
                continue
            seen.add(slug)
            page = _read_cached(_raw_item(raw, slug))
            if page is None:
                raise ParseError(f"raw/item-{slug}.html is missing; fetch again")
            pages[slug] = page
    if _pages_digest(pages) != manifest.get("sha256"):
        raise ParseError("the cached pages are not the ones the manifest was written for; fetch again with --refresh")
    for slug in dict.fromkeys(s for slugs in zones.values() for s in slugs):
        items.append(parse_item_page(pages[slug], slug))
    return Snapshot(date=manifest["date"], sha256=manifest["sha256"], zones=zones, items=items)


def load_items(directory: str | Path) -> list[EqltItem]:
    """The parsed items of a finished fetch (see :func:`read_snapshot`)."""
    return read_snapshot(directory).items


# ---- command line ---------------------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.sources.eqlegendstools",
        description="Fetch the items of a zone from eqlegendstools.com, politely (one request a second).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="fetch the zone page and the pages of the items it lists")
    fetch.add_argument("--out", required=True, type=Path, help="e.g. sources/eqlegendstools/2026-10-25")
    fetch.add_argument("--refresh", action="store_true", help="ask for every page again instead of reading the ones already in --out")
    return parser


def main(argv: Sequence[str] | None = None, *, client: PoliteClient | None = None, today: date | None = None) -> int:
    """The command line. Returns the exit code: 0 done, 2 failed (run it again: the pages already saved are not fetched twice), 130 Ctrl-C."""
    args = _parser().parse_args(argv)
    client = client or PoliteClient(USER_AGENT)
    today = today or datetime.now(timezone.utc).date()
    try:
        with FetchLock(LOCK_PATH):
            run_fetch(client, args.out, today, refresh=args.refresh)
    except FetchError as error:
        print(f"error: {error}", file=sys.stderr)
        print("Nothing was lost: run the same command again; the pages already saved are not fetched twice.", file=sys.stderr)
        return 2
    except (ParseError, OSError, _Refusal) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted: run the same command again to continue.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
