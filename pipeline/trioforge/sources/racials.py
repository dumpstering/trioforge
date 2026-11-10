"""Racial abilities from the race pages of eqlwiki, reduced to what the trio page names.

The race pages of eqlwiki (https://eqlwiki.com/, licensed CC BY-SA 4.0 by the eqlwiki contributors) are fetched with the item fetcher, which takes any category::

    python -m trioforge.sources.eqlwiki fetch --category "Category:Character Races" --out sources/eqlwiki/races/2026-11-08

(The snapshot is filed in ``sources/eqlwiki/races/<date>``, not in ``sources/eqlwiki/<date>`` beside the pulls of items: the tests of the catalog take the last
``sources/eqlwiki/*/manifest.json`` for the pull of items, and a race snapshot there would be taken for one.) This module reads such a snapshot and writes
``derived/racials.json``::

    python -m trioforge.sources.racials --wiki sources/eqlwiki/races/2026-11-08 --out derived/racials.json

``racials.json`` is ``{"provenance", "license", "attribution", "pages", "racials", "skipped"}``:

* ``pages`` are the race pages read, ``{"race", "title", "revid", "url"}``, in the order of the race codes of :mod:`trioforge.data.races` (the revision named is the
  one the text was read from; ``url`` is that revision's address);
* ``racials`` are ``{"race", "name", "description", "source", "revid"}``, a row for each name of the page's "Racial(s):" list, in the page's order. ``description`` is the
  first sentence of the page's own section of that name (the section runs to the next heading; a sentence ends at a full stop, an exclamation mark or a question mark
  before a capital letter or a figure, and one that ends in a colon, which introduces a table, loses it), or the name itself when the page has no section of that name:
  nothing is written that the page does not say;
* ``skipped`` are the pages that give no row, ``{"title", "reason"}``: a race the rules have no code for (the page says Half Dark Elf, and the rules have no such race), or a
  page that is not a race page (``missing``, ``redirect``, ``empty``, ``namespace``, ``too-large``, ``too-complex``, ``duplicate``), or a page with no list of racials at all
  (``no-racial-list``: no "Racial(s):" line, or nothing after its label; a page whose list says ``None``, as the Human page does, is a race with no racials and keeps its page);

Racial abilities are **not scored**: nothing in the solve, the rules or the results reads this file. The site reads it to say, next to a race, what the race has.

Every string is passed through the catalog's ``sanitize_text``: the source is wiki text, which is hostile input. The output is written all or nothing; an error leaves
any old file as it was and ends the command with exit status 2.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mwparserfromhell
from mwparserfromhell.nodes import Heading
from mwparserfromhell.parser import ParserError

import trioforge
from trioforge.data import catalog
from trioforge.data import races as races_module
from trioforge.data.jsonio import render
from trioforge.data.normalize import sanitize_text
from trioforge.site.content import wiki_url
from trioforge.sources.client_tables import commit_files, iso_date, one_line, today_utc
from trioforge.sources.itempage import MAX_PAGE_CHARS, MAX_UNMATCHED, plain_text, unmatched_openers

__all__ = ["ATTRIBUTION", "CATEGORY", "GENERATOR", "LICENSE", "RacePage", "Skip", "main", "parse_page", "race_code", "read_racials", "write_racials"]

CATEGORY = "Category:Character Races"
LICENSE = "CC BY-SA 4.0"
GENERATOR = f"trioforge.sources.racials {trioforge.__version__}"
ATTRIBUTION = (
    "Racial abilities adapted from the race pages of eqlwiki.com (https://eqlwiki.com/) by the eqlwiki contributors, licensed CC BY-SA 4.0; "
    "changes: parsed from each page's Racial(s) list, each name given the first sentence of the page's section of that name where there is one, strings sanitized."
)
INPUT_URL = "https://eqlwiki.com/index.php?title=" + CATEGORY.replace(" ", "_")

#: the wiki's title for a race that the rules name differently (the rules say Kerran; the page is Kerra). Other titles match the rules' names with the case,
#: spaces and hyphens ignored (Half-Elf is Half Elf).
TITLE_ALIASES = {"kerra": "KER"}

_REDIRECT = re.compile(r"\s*#redirect", re.IGNORECASE)
_RACIAL_LINE = re.compile(r"^[^\n]*?Racial\(s\):([^\n]*)$", re.MULTILINE)
_LABEL_END = re.compile(r"^(?:\s|'''|</b>)+", re.IGNORECASE)
_PARAGRAPHS = re.compile(r"\n[ \t]*\n")
_NOT_PROSE = ("{|", "{{", "*", "#", ":", ";", "|", "!")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_TRAILING_FIGURE = re.compile(r"\s*\([^)]*\)\s*$")
_NAME_SEPARATORS = re.compile(r"[^a-z]+")
_OPEN, _CLOSE = "[({", "])}"


@dataclass(frozen=True)
class Skip:
    """A page that gives no racials, and why (see the module description)."""

    pageid: Any
    title: Any
    reason: str


@dataclass
class RacePage:
    """One race page read: the race code, the title and revision it was read from, and its rows (``{"race", "name", "description", "source", "revid"}``)."""

    code: str
    title: str
    revid: int
    rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def url(self) -> str:
        return wiki_url(self.title, self.revid)


def _squash(text: str) -> str:
    return _NAME_SEPARATORS.sub("", text.casefold())


_CODES = {_squash(name): code for code, name in races_module.RACE_NAMES.items()}


def race_code(title: str) -> str | None:
    """The race code of a wiki page title (``Half-Elf`` is ``HEF``, ``Kerra`` is ``KER``), or None for a race the rules have no code for."""
    key = _squash(title)
    return TITLE_ALIASES.get(key) or _CODES.get(key)


def _split(text: str) -> list[str]:
    """The comma-separated parts of a list, a comma inside a link, a bracket or a template not counting."""
    parts, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char in _OPEN:
            depth += 1
        elif char in _CLOSE:
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def _clean(text: str) -> str:
    return sanitize_text(plain_text(text)) or ""


def _names(content: str) -> list[str] | None:
    """The names of the page's "Racial(s):" list, once each, in order. A list that says ``None`` (the Human page) is ``[]``: the race has no racial. A page with no such line, or a line with
    nothing after its label, has no list at all: ``None``, which is a page to skip and not a race with no racials."""
    found = _RACIAL_LINE.search(content)
    if found is None:
        return None
    names: list[str] = []
    says_none = False
    for part in _split(_LABEL_END.sub("", found.group(1))):
        name = _clean(part)
        if name.casefold() == "none":
            says_none = True
        elif name and name not in names:
            names.append(name)
    return names if names or says_none else None


def _heading_key(text: str) -> str:
    return " ".join(plain_text(text).casefold().split())


def _sections(code: mwparserfromhell.wikicode.Wikicode) -> dict[str, str]:
    """The wikitext under each heading, by the heading's name (case and spacing ignored): up to the next heading of its own rank or higher. The first section of a name wins."""
    found: dict[str, str] = {}
    nodes = code.nodes
    index = 0
    while index < len(nodes):
        node = nodes[index]
        index += 1
        if not isinstance(node, Heading):
            continue
        body = []
        while index < len(nodes):
            following = nodes[index]
            if isinstance(following, Heading) and following.level <= node.level:
                break
            body.append(str(following))
            index += 1
        found.setdefault(_heading_key(str(node.title)), "".join(body))
    return found


def _first_sentence(body: str) -> str:
    """The first sentence of the first paragraph of prose in a section: not a table, a list or a template."""
    for paragraph in _PARAGRAPHS.split(body.strip("\n")):
        paragraph = paragraph.strip()
        if not paragraph or paragraph.startswith(_NOT_PROSE):
            continue
        sentence = _SENTENCE_END.split(" ".join(plain_text(paragraph).split()), 1)[0].rstrip(":").rstrip()
        return sanitize_text(sentence) or ""
    return ""


def parse_page(record: dict) -> RacePage | Skip:
    """Parse one page record (``pageid``, ``ns``, ``title``, ``revid``, ``content``, ``missing``), as the fetcher saves it. Never raises for any page text."""
    try:
        return _parse(record)
    except (RecursionError, ParserError):
        return Skip(record.get("pageid"), record.get("title"), "too-complex")


def _parse(record: dict) -> RacePage | Skip:
    pageid, title = record.get("pageid"), record.get("title")

    def skip(reason: str) -> Skip:
        return Skip(pageid, title, reason)

    if record.get("missing"):
        return skip("missing")
    if record.get("ns") not in (None, 0):
        return skip("namespace")
    content = record.get("content")
    if not isinstance(content, str) or not content.strip():
        return skip("empty")
    if _REDIRECT.match(content):
        return skip("redirect")
    if len(content) > MAX_PAGE_CHARS:
        return skip("too-large")
    if unmatched_openers(content) > MAX_UNMATCHED:
        return skip("too-complex")
    revid = record.get("revid")
    code = race_code(title) if isinstance(title, str) else None
    if code is None or not isinstance(title, str):
        return skip("no-race-code")
    if type(revid) is not int or revid < 0:
        return skip("missing")
    names = _names(content)
    if names is None:
        return skip("no-racial-list")
    sections = _sections(mwparserfromhell.parse(content))
    source = wiki_url(title, revid)
    rows = []
    for name in names:
        body = sections.get(_heading_key(_TRAILING_FIGURE.sub("", name)))
        rows.append(
            {
                "race": code,
                "name": name,
                "description": (_first_sentence(body) if body is not None else "") or name,
                "source": source,
                "revid": revid,
            }
        )
    return RacePage(code, title, revid, rows)


def read_racials(wiki_dir: str | Path) -> dict[str, Any]:
    """The pages, racials and skipped pages of a finished fetch of ``Category:Character Races``, with the snapshot's ``date`` and ``sha256``.

    Raises :class:`ValueError` (one line) if the fetch is not whole, is of another category, or has no race page.
    """
    try:
        snapshot = catalog.read_wiki(wiki_dir)
    except catalog.BuildError as error:
        raise ValueError(one_line(error)) from error
    if snapshot.category != CATEGORY:
        raise ValueError(f"the fetch is of {snapshot.category}, not {CATEGORY}")
    found: dict[str, RacePage] = {}
    skipped: list[dict[str, str]] = []
    for record in snapshot.pages:
        result = parse_page(record)
        if isinstance(result, RacePage) and result.code in found:
            result = Skip(record.get("pageid"), record.get("title"), "duplicate")
        if isinstance(result, Skip):
            skipped.append({"title": _clean(str(result.title)), "reason": result.reason})
        else:
            found[result.code] = result
    if not found:
        raise ValueError(f"no race page in the fetch of {CATEGORY}")
    ordered = [found[code] for code in races_module.RACE_CODES if code in found]
    return {
        "date": snapshot.date,
        "sha256": snapshot.sha256,
        "pages": [{"race": page.code, "title": page.title, "revid": page.revid, "url": page.url} for page in ordered],
        "racials": [row for page in ordered for row in page.rows],
        "skipped": sorted(skipped, key=lambda entry: (entry["title"].casefold(), entry["reason"])),
    }


def write_racials(wiki_dir: str | Path, out: str | Path, generated: str) -> dict[str, Any]:
    """Read the snapshot and write ``out`` (``derived/racials.json``) all or nothing; returns the document."""
    read = read_racials(wiki_dir)
    document = {
        "provenance": {
            "inputs": [{"file": INPUT_URL, "sha256": read["sha256"], "date": read["date"]}],
            "generator": GENERATOR,
            "generated": generated,
        },
        "license": LICENSE,
        "attribution": ATTRIBUTION,
        "pages": read["pages"],
        "racials": read["racials"],
        "skipped": read["skipped"],
    }
    target = Path(out)
    commit_files(target.parent, {target.name: render(document, per_line=("pages", "racials", "skipped"))}, last=target.name)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.sources.racials",
        description="Reduce a fetch of the race pages of eqlwiki to derived/racials.json (the racial abilities of each race).",
    )
    parser.add_argument("--wiki", required=True, type=Path, help="a finished fetch of Category:Character Races, e.g. sources/eqlwiki/races/2026-11-08")
    parser.add_argument("--out", type=Path, default=Path("derived/racials.json"), help="output file")
    parser.add_argument("--date", type=iso_date, help="generation date, YYYY-MM-DD (default: today in UTC)")
    args = parser.parse_args(argv)
    try:
        document = write_racials(args.wiki, args.out, args.date or today_utc())
    except (OSError, ValueError) as error:
        print(f"error: {one_line(error)}", file=sys.stderr)
        return 2
    print(
        f"{args.out.name}: {len(document['pages'])} race pages, {len(document['racials'])} racials, "
        f"{len(document['skipped'])} page(s) skipped"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
