"""The inputs of the pages other than the trio page: the rules file, the sources manifest, the racial abilities and the changelog.

Nothing here writes HTML. Each loader returns plain data the templates loop over, and every piece of text stays text:
the changelog's Markdown is read by a small reader that knows headings, bullets, paragraphs, ``**bold**``, ``code`` and
``[text](https://link)``, and nothing else, so a ``<script>`` in a changelog line is shown as the characters it is.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from trioforge import rules as rules_module
from trioforge.data.jsonio import JsonFileError, load_strict

__all__ = [
    "ChangelogBlock",
    "Manifest",
    "PRIVATE_LABEL",
    "RacePageRef",
    "Racial",
    "Racials",
    "RuleBook",
    "RuleView",
    "SEALS",
    "SEALS_TO_EXPLAIN",
    "eqlt_item_url",
    "load_changelog",
    "load_manifest",
    "load_racials",
    "load_rulebook",
    "parse_markdown",
    "wiki_url",
]

#: the five confidence seals: key in rules.json -> (label, what it means)
SEALS: dict[str, tuple[str, str]] = {
    "client": ("Client file", "read from a text file that ships with the game client"),
    "developer": ("Developer", "a developer statement or patch note"),
    "measured": ("Measured", "our own in-game test or a reproduced stat window"),
    "player": ("Player reports", "several independent players"),
    "model": ("Model", "our or EQEmu's formula, or a judgment constant"),
}
#: the markers whose words say least to a reader who is new here: each carries a title that says what it means, and the trio page has a line (its key) that says both. The words of the other three
#: (a file of the client, a measurement, what players report) say what they are.
SEALS_TO_EXPLAIN = ("developer", "model")
PRIVATE_LABEL = "Maintainer's private observation"

_GROUP_TITLES = {
    "level": "Level",
    "naked": "Naked stats",
    "hp": "Hit points",
    "mana": "Mana",
    "end": "Endurance",
    "ac": "Armour class",
    "stats": "Stats",
    "haste": "Haste",
    "regen": "Regeneration",
    "resist": "Resists",
    "tier": "Tiers",
    "monk": "Monk",
    "packrat": "Packrat",
    "race": "Races",
    "buffs": "Buffs",
    "roles": "Roles",
    "weapons": "Weapons",
}


class ContentError(ValueError):
    """An input of a page cannot be used. One line, naming the file."""


# ---- the rules ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceView:
    text: str
    href: str | None


@dataclass(frozen=True)
class AlternativeView:
    value: str
    seal: str
    seal_label: str
    sources: tuple[SourceView, ...]


@dataclass(frozen=True)
class RuleView:
    id: str
    title: str
    value: str
    unit: str
    seal: str  # the key: client, developer, measured, player, model
    seal_label: str
    sources: tuple[SourceView, ...]
    date: str
    status: str  # active, open or superseded
    test: str | None  # the in-game test that settles an open rule: "B4"
    notes: str | None
    alternatives: tuple[AlternativeView, ...]
    levels: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class RuleGroup:
    key: str
    title: str
    rules: tuple[RuleView, ...]


@dataclass(frozen=True)
class RuleBook:
    version: str
    groups: tuple[RuleGroup, ...]
    by_id: dict[str, RuleView]

    def get(self, rule_id: str) -> RuleView:
        try:
            return self.by_id[rule_id]
        except KeyError:
            raise ContentError(f"rules.json has no rule {rule_id!r}") from None

    @property
    def open_rules(self) -> tuple[RuleView, ...]:
        """The rules waiting for an in-game test, in the order of the tests (B1, B4, B5 ...)."""
        waiting = [rule for group in self.groups for rule in group.rules if rule.status == "open"]
        return tuple(sorted(waiting, key=lambda rule: (int((rule.test or "B0")[1:]), rule.id)))


def format_value(value: Any) -> str:
    """A rule's value as text: plain for a number or a word, compact JSON for a curve, a list or a table."""
    if value is None:
        return "not known yet"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _sources(entries: list[dict[str, str]]) -> tuple[SourceView, ...]:
    shown = []
    for entry in entries:
        kind, ref = entry["kind"], entry["ref"]
        if kind == "url":
            shown.append(SourceView(ref, ref))
        elif kind == "client-file":
            shown.append(SourceView(f"Client file: {ref}", None))
        elif kind == "private-measured":
            shown.append(SourceView(f"{PRIVATE_LABEL} (measured)", None))
        elif kind == "private-player":
            shown.append(SourceView(f"{PRIVATE_LABEL} (player reports)", None))
        else:
            shown.append(SourceView(ref, None))
    return tuple(shown)


def load_rulebook(path: str | Path) -> RuleBook:
    """Validate the rules file with the rules loader, then read it for display. Private sources show their label only."""
    path = Path(path)
    try:
        rules_module.load(path)
    except (rules_module.RulesError, OSError) as error:
        raise ContentError(f"{path.name}: {str(error).splitlines()[0]}") from None
    document = json.loads(path.read_text(encoding="utf-8"))
    order: list[str] = []
    grouped: dict[str, list[RuleView]] = {}
    by_id: dict[str, RuleView] = {}
    for rule in document["rules"]:
        if rule["status"] == "superseded":
            continue
        view = RuleView(
            id=rule["id"],
            title=rule["title"],
            value=format_value(rule["value"]),
            unit=rule["unit"],
            seal=rule["seal"],
            seal_label=SEALS[rule["seal"]][0],
            sources=_sources(rule["source"]),
            date=rule["date"],
            status=rule["status"],
            test=rule.get("test"),
            notes=rule.get("notes"),
            alternatives=tuple(
                AlternativeView(format_value(alt["value"]), alt["seal"], SEALS[alt["seal"]][0], _sources(alt["source"]))
                for alt in rule.get("alternatives", [])
            ),
            levels=tuple((level, format_value(value)) for level, value in rule.get("levels", {}).items()),
        )
        key = rule["id"].split(".")[0]
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(view)
        by_id[view.id] = view
    groups = tuple(RuleGroup(key, _GROUP_TITLES.get(key, key.replace("_", " ").title()), tuple(grouped[key])) for key in order)
    return RuleBook(document["version"], groups, by_id)


# ---- the sources manifest ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Manifest:
    """The catalog builder's ``sources-manifest.json``: which wiki page and revision each item key came from."""

    attribution: str
    license: str
    inputs: tuple[tuple[str, str], ...]  # (file or address, date)
    items: dict[str, tuple[str, int]]  # key -> (page title, revision id)
    eqlt: dict[str, tuple[str, str]] = field(default_factory=dict)  # key -> (item name, slug of its page at EQ Legends Tools); empty when the catalog was built without that source


def load_manifest(path: str | Path) -> Manifest:
    path = Path(path)
    try:
        document = load_strict(path)
    except FileNotFoundError:
        raise ContentError(
            f"{path.name} was not found at {path}: build the catalog first (it writes the file) or give --sources-manifest"
        ) from None
    except (JsonFileError, OSError) as error:
        raise ContentError(f"{path.name}: {error}") from None
    try:
        items = {key: (entry["title"], entry["revid"]) for key, entry in document["items"].items()}
        for title, revid in items.values():
            if not isinstance(title, str) or not title or type(revid) is not int or revid < 0:
                raise TypeError
        inputs = tuple((record["file"], record["date"]) for record in document["provenance"]["inputs"])
        eqlt = {key: (entry["title"], entry["slug"]) for key, entry in document.get("eqlegendstools", {}).items()}
        for key, (name, slug) in eqlt.items():
            if not isinstance(name, str) or not name or not isinstance(slug, str) or not EQLT_SLUG.fullmatch(slug):
                raise TypeError
        return Manifest(document["attribution"], document["license"], inputs, items, eqlt)
    except (KeyError, TypeError, AttributeError):
        raise ContentError(f"{path.name}: not a sources manifest (items with a title and a revision, provenance, attribution)") from None


# ---- the racial abilities ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RacePageRef:
    """A race page of the wiki that the racials were read from: the race, the page title, the revision and that revision's address."""

    race: str
    title: str
    revid: int
    url: str


@dataclass(frozen=True)
class Racial:
    """One racial ability of a race as its wiki page words it: the name, the page's first sentence about it (or the name when the page says no more), and where it was read."""

    race: str
    name: str
    description: str
    source: str
    revid: int


@dataclass(frozen=True)
class Racials:
    """``derived/racials.json``: the race pages read and the racial abilities of each race. Nothing of it is scored."""

    license: str
    attribution: str
    input: str  # the address of the category the pages were pulled from
    date: str  # the day the pages were fetched
    pages: tuple[RacePageRef, ...]
    rows: tuple[Racial, ...]

    def of(self, race: str) -> tuple[Racial, ...]:
        """The racials of a race in the page's order (none for a race with no page, or a page that lists none)."""
        return tuple(row for row in self.rows if row.race == race)

    def page(self, race: str) -> RacePageRef | None:
        return next((page for page in self.pages if page.race == race), None)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_racials(path: str | Path) -> Racials:
    """Read ``derived/racials.json`` (:mod:`trioforge.sources.racials` writes it) and check it is what the writer makes: the licence, the pages, and a row that comes from the page of its race."""
    from trioforge.data import races as races_module

    path = Path(path)
    try:
        document = load_strict(path)
    except FileNotFoundError:
        raise ContentError(
            f"{path.name} was not found at {path}: write it with python -m trioforge.sources.racials, or give --racials"
        ) from None
    except (JsonFileError, OSError) as error:
        raise ContentError(f"{path.name}: {error}") from None

    def bad(what: str) -> ContentError:
        return ContentError(f"{path.name}: not a file of racial abilities ({what})")

    if not isinstance(document, dict) or not all(key in document for key in ("provenance", "license", "attribution", "pages", "racials")):
        raise bad("provenance, licence, attribution, pages and racials are needed")
    if document["license"] != "CC BY-SA 4.0":
        raise bad("the licence must be CC BY-SA 4.0")
    if not _text(document["attribution"]):
        raise bad("the attribution is empty")
    inputs = document["provenance"].get("inputs") if isinstance(document["provenance"], dict) else None
    if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], dict) or not _text(inputs[0].get("date")) or not _text(inputs[0].get("file")):
        raise bad("provenance must name the pull it was read from, with its date")
    if not isinstance(document["pages"], list) or not isinstance(document["racials"], list):
        raise bad("pages and racials must be lists")
    pages: dict[str, RacePageRef] = {}
    for entry in document["pages"]:
        if not isinstance(entry, dict) or set(entry) != {"race", "title", "revid", "url"}:
            raise bad("a page is a race, a title, a revision and an address")
        race, title, revid, url = entry["race"], entry["title"], entry["revid"], entry["url"]
        if not isinstance(race, str) or race not in races_module.RACE_NAMES or race in pages or not _text(title) or type(revid) is not int or revid < 0:  # (a race is looked up as a key: a list cannot be one)
            raise bad(f"page of {race!r}")
        if url != wiki_url(title, revid):
            raise bad(f"the address of the page of {race} is not that of its revision")
        pages[race] = RacePageRef(race, title, revid, url)
    rows: list[Racial] = []
    seen: set[tuple[str, str]] = set()
    for entry in document["racials"]:
        if not isinstance(entry, dict) or set(entry) != {"race", "name", "description", "source", "revid"}:
            raise bad("a racial is a race, a name, a description, a source and a revision")
        race, name, description = entry["race"], entry["name"], entry["description"]
        page = pages.get(race) if isinstance(race, str) else None
        if page is None or not _text(name) or not _text(description) or (race, name) in seen:
            raise bad(f"racial {name!r} of {race!r}")
        if entry["source"] != page.url or entry["revid"] != page.revid:
            raise bad(f"racial {name!r} of {race} does not come from the page of its race")
        seen.add((race, name))
        rows.append(Racial(race, name, description, entry["source"], entry["revid"]))
    return Racials(document["license"], document["attribution"], inputs[0]["file"], inputs[0]["date"], tuple(pages.values()), tuple(rows))


#: the slug of a page of an item at EQ Legends Tools (small letters, digits and hyphens)
EQLT_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,95}")
EQLT_NAME = "EQ Legends Tools"
EQLT_SITE = "https://eqlegendstools.com/"


def eqlt_item_url(slug: str) -> str:
    """The address of the page of an item at EQ Legends Tools."""
    if not EQLT_SLUG.fullmatch(slug):
        raise ValueError("not the slug of a page at EQ Legends Tools")
    return f"{EQLT_SITE}items/{slug}/"


def wiki_url(title: str, revid: int) -> str:
    """The address of one revision of a wiki page."""
    return f"https://eqlwiki.com/index.php?title={quote(title.replace(' ', '_'), safe='')}&oldid={revid}"


# ---- the changelog -----------------------------------------------------------------------------------------------------------

_INLINE = re.compile(r"(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\(https?://[^)\s]+\))")


@dataclass(frozen=True)
class Segment:
    kind: str  # text, strong, code or link
    text: str
    href: str | None = None


@dataclass(frozen=True)
class ChangelogBlock:
    kind: str  # h2, h3, p or ul
    segments: tuple[Segment, ...] = ()
    items: tuple[tuple[Segment, ...], ...] = ()


def _inline(text: str) -> tuple[Segment, ...]:
    segments = []
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("**"):
            segments.append(Segment("strong", part[2:-2]))
        elif part.startswith("`"):
            segments.append(Segment("code", part[1:-1]))
        elif part.startswith("["):
            label, _, rest = part[1:].partition("](")
            segments.append(Segment("link", label, rest[:-1]))
        else:
            segments.append(Segment("text", part))
    return tuple(segments)


def parse_markdown(text: str) -> tuple[ChangelogBlock, ...]:
    """The changelog's Markdown as blocks. The first ``#`` heading is the page title and is left to the template."""
    blocks: list[ChangelogBlock] = []
    paragraph: list[str] = []
    bullets: list[list[str]] = []

    def flush() -> None:
        if paragraph:
            blocks.append(ChangelogBlock("p", segments=_inline(" ".join(paragraph))))
            paragraph.clear()
        if bullets:
            blocks.append(ChangelogBlock("ul", items=tuple(_inline(" ".join(item)) for item in bullets)))
            bullets.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush()
        elif stripped.startswith("# "):
            flush()  # the title
        elif stripped.startswith("## ") or stripped.startswith("### "):
            flush()
            level = "h2" if stripped.startswith("## ") else "h3"
            blocks.append(ChangelogBlock(level, segments=_inline(stripped.lstrip("#").strip())))
        elif stripped.startswith(("- ", "* ")):
            if paragraph:
                flush()
            bullets.append([stripped[2:].strip()])
        elif bullets and line.startswith((" ", "\t")):
            bullets[-1].append(stripped)  # a wrapped bullet
        else:
            if bullets:
                flush()
            paragraph.append(stripped)
    flush()
    return tuple(blocks)


def load_changelog(path: str | Path) -> tuple[ChangelogBlock, ...] | None:
    """The changelog as blocks, or None when the file does not exist yet."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return parse_markdown(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        raise ContentError(f"{path.name}: cannot be read as UTF-8 text") from None
