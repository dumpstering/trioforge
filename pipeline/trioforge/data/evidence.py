"""The evidence ladder: how sure we are that an item exists in EQL, and why.

:func:`classify` gives each catalog item one of four levels and the reasons for it. A reason is
``{"code", "seal", "text"}``: a short code, the seal that says where the claim comes from (``client``,
``developer``, ``measured``, ``player`` or ``model``, as on every rule) and one plain sentence.

======== ==============================================================================================
strict   seen in game (the maintainer's private flags, never in a committed build), reported by
         players (``rules/community-seen.json``) or listed by an EQL-specific catalog (only with its
         owner's permission). Never overrides a patch or research removal. When the wiki signals
         disagree, the item stays strict and gets a ``conflict-note``; a report from players alone
         does not override the wiki's own word that the item is gone, nor the word of the developers
         or the client that every zone it comes from is closed (below).
wiki     a source in a live zone and no conflict (below). Strict items are wiki items by definition.
disputed a live source, but the wiki's era tag is out of era (the tags follow Project 1999, not EQL),
         or the page carries both an in-era and an out-of-era tag. Out by default; shown on item pages.
hidden   not in EQL, as far as the wiki and the client say. Each reason says why.
======== ==============================================================================================

The order of the checks:

1. ``removed`` (a patch note says the item no longer drops) and ``research_removals`` (replaced or
   removed, from the maintainer's private research) hide an item whatever else is known. Both lists
   match the **exact wiki page title** after normalization (:func:`title_key`), never a substring.
2. Strict evidence (above).
3. **What the wiki page itself says.** A banner of ``{{Delete}}``, ``{{:Does Not Exist}}`` or ``{{DNE}}`` (the
   item flags ``wiki_banner_delete``, ``wiki_banner_does_not_exist``, ``wiki_banner_dne``) hides the item with
   the reason ``wiki-marked-not-in-eql``, and the drop-list note ``ITEM REMOVED FROM GAME`` (``removed_note``)
   with ``wiki-marked-removed`` (both sealed ``player``: they are the wiki's word); these are the only hidden
   reasons given, however many live sources the page lists, because the page says they are stale. The
   maintainer's own evidence (the seen flags, a listing the owner allows) outranks them: the item stays strict,
   with a ``conflict-note``, and a report from players beside that evidence is listed as before. **A report from
   players alone does not**: one report must not put an item the wiki says is gone into kits. An item that the
   page marks and players report stays hidden, and its reasons are the marks and ``community-report-outweighed``
   (a report was received, and the wiki's word outweighs it); it gets no ``conflict-note``. A patch or research
   removal is checked first, as before.
4. A **live source**: a drop in a live zone; a foraged zone that is live (``live-source:foraged``: the
   ``foraged`` list goes through the same zone gate as the drops, the EQL-only exemption included); a quest
   whose giver stands in a live zone and whose page is not out of era; a vendor in a live zone; a recipe in
   a named container that is not cultural, with no out-of-era ingredient; or, when the item has no other live
   source, a quest link to the page of a live zone with a label that names the test (``live-source:quest`` again,
   see **Quests**). A zone is live when the client
   flags it and it is not on the "unreleased" list, or when the "exists but unflagged" list names it. With a
   live source: an out-of-era tag (or both kinds of tag) makes it ``disputed``, unless one of its drops or
   foraging zones (of any status), or one of the live zones of its quest links when they are its live source, is
   in an EQL-only zone, where era tags mean nothing; otherwise it is ``wiki``.
5. No live source: every reason that applies is given. The zones of the drops, of the foraging and of the quest
   links that name a test (see **Quests**) are judged together: ``zone-unreleased`` (every one is unreleased),
   ``zones-unmapped`` (every one has no client id; a quest-link zone is never unmapped, as a target that is no
   zone is no link) and ``zones-not-in-eql`` (any other mix of dead zones: an unmapped drop zone beside an
   unreleased quest-link zone gives this one). Their texts name only the kinds of zone the item has: ``drop``,
   ``foraging`` and ``quest`` ("Every drop or quest zone is flagged but not yet released."). Besides them:
   ``out-of-era`` (an out-of-era tag), ``cultural-container`` (recipes only in cultural containers),
   ``out-of-era-ingredient`` (every other recipe needs an out-of-era ingredient). If none applies,
   ``no-known-source``. **``zone-unreleased`` and ``zones-not-in-eql`` outweigh a report from players on their own**, as
   the wiki's marks do (a screenshot of the item window shows that the item is in the game's data, not that anyone can
   get it): an item with either stays hidden when players report it, with ``community-report-outweighed`` among its
   reasons and no ``conflict-note``. The seen flags still override them; a report lifts an item that is hidden or
   disputed for any other reason (``cultural-container``, ``no-known-source``, ``out-of-era``, ``out-of-era-ingredient``,
   ``out-of-era-tag-live-zone``, ``conflicting-era-tags`` and ``zones-unmapped``). A zone with no client id beside a
   closed zone gives ``zones-not-in-eql``, which outweighs a report: only an item whose every zone has no client id is
   ``zones-unmapped``.
6. Notes added at every level; the item stays in the catalog: ``not-for-bis`` (a temporary item, one a quest
   takes on hand-in, one whose class list or race list is empty because its page says ``Class: NONE`` or
   ``Race: NONE``, or leaves the line blank, or writes words that are no code: nobody may use or wear it, and the text
   says which of the three the page shows, ``class NONE``, ``class left blank`` or ``class not understood``, or a hand weapon that names a skill but has no damage or no delay,
   see :func:`trioforge.data.normalize.weapon_incomplete`: the model could not score it and would read it as a
   non-weapon; the text of the reason names the causes that apply, such as ``race NONE``), ``not-for-default-kits``
   (a deity-locked item), ``wiki-marked-revamped`` (the page carries ``{{revamped}}``: its stats or
   sources may have changed since it was written; it changes nothing else) and ``source-eql-tools`` (the item has an ``origin`` from EQ Legends Tools: its stats and drops
   are read from that site's page, see :mod:`trioforge.data.eqlt_merge`; it changes nothing else).

**Zones.** Wiki zone names reach client ids only through the hand-kept alias table
(``rules/zone-aliases.json``), keyed by :func:`zkey`; a name with no entry is *unmapped*, is reported
and is no live source. **Eras.** Era tags are normalized to ``<Name> Era``; the lists in
``rules/hand-lists.json`` say which are in era and which are out. A tag in neither list is ignored and
reported. Era names are compared as casefolded keys, so ``FearHateRevamp Era`` (the spelling the page uses)
and ``Fearhaterevamp Era`` are one tag, and a hand list may write them either way. **Quests.** A quest is
found by the **target** of the item page's quest link (``sources.quests``: the page title), then by the label of
that link (``sources.quest_labels``) for the few quests whose title is the label, or because it names the item
as a reward (when no other page has the item's name). A target that finds no quest in the table but is the page of
a zone (an alias, resolved as a drop zone is, with no qualifier in parentheses) puts a quest in that zone when the link
has a label that names the test, as the Plane of Sky class tests are linked (``Plane of Sky`` with the label
``Paladin Test of Sacrifice``). A bare link says nothing about a quest; a label that is a zone's name is a place
(``Neriak Third Gate``); and a label that is the title of a quest in the table leaves the decision to that quest, so a
quest the table rejects is never replaced by its zone. This is read only when the item has no other live source: a
quest link can mean "used in this quest" as well as "rewarded by it", and a component that drops in the zone and is
handed in to the quest is no reward. The zone then goes through the same gate as a drop zone: a live one gives
``live-source:quest``, worded as what the page says (it links the item to a quest in that zone, with the label) and not
as a reward, and one that is not live joins the dead-zone reasons. The quest has no page, so no era, of its own, and
the item's own era tags judge it as they judge a drop, with the exemption of an EQL-only zone, which only a live zone
gives. A target that is no zone is a quest the table lacks: it finds nothing and is not reported as an unmapped
zone, and a title with a qualifier in parentheses is a quest page, not a zone page. The item's own name is never read
as a zone.

The module reads two hand-written rules files, validates them in full (every problem is listed in one
:class:`EvidenceError`) and never changes an item. ``rules/hand-lists.json`` also holds two lists that are not
about evidence: ``shields`` and ``not_shields``, the items that the catalog builder must (or must not) type as
shields although their pages and names do not say so. They are read here, with the other hand lists, and used by
:mod:`trioforge.data.catalog`.
"""

from __future__ import annotations

import datetime
import functools
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from trioforge.data.jsonio import JsonFileError, load_strict
from trioforge.data.normalize import weapon_incomplete
from trioforge.rules import SCHEMA_PATH as RULES_SCHEMA_PATH

__all__ = [
    "ALIASES_PATH",
    "CONFLICT_CODES",
    "HAND_LISTS_PATH",
    "LEVELS",
    "NOTE_CODES",
    "NOT_HIDING_CODES",
    "REMOVAL_CODES",
    "SEALS",
    "WIKI_GONE_FLAGS",
    "WIKI_MARK_CODES",
    "ZONE_CLOSED_CODES",
    "Context",
    "EvidenceError",
    "HandLists",
    "Quest",
    "QuestTable",
    "Report",
    "ambiguous_names",
    "classify",
    "container_key",
    "era_key",
    "is_known_zone",
    "load_aliases",
    "load_hand_lists",
    "normalize_era",
    "out_of_era_names",
    "title_key",
    "zkey",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
HAND_LISTS_PATH = REPO_ROOT / "rules" / "hand-lists.json"
ALIASES_PATH = REPO_ROOT / "rules" / "zone-aliases.json"

LEVELS = ("strict", "wiki", "disputed", "hidden")
SEALS = ("client", "developer", "measured", "player", "model")

MAX_LIVE_ZONE_REASONS = 5  # live-source reasons written for the zones of one item
MAX_TEXT = 200

# Reasons that say the wiki signals contradict strict evidence. "no-known-source" and "zones-unmapped"
# are missing evidence, not contradictions, so they are not here.
CONFLICT_CODES = frozenset(
    {
        "out-of-era-tag-live-zone",
        "conflicting-era-tags",
        "zones-not-in-eql",
        "zone-unreleased",
        "out-of-era",
        "cultural-container",
        "out-of-era-ingredient",
        "wiki-marked-not-in-eql",
        "wiki-marked-removed",
    }
)

# Reasons that are notes on an item, not the reason for its level: they are left out of the counts of hidden items.
NOTE_CODES = frozenset({"not-for-bis", "not-for-default-kits", "source-eql-tools", "wiki-marked-revamped"})

# The reasons that are no reason to hide an item: the notes, and the record that a report from players was received and outweighed (the mark or the closed zone beside it is the
# reason). The summary of the catalog counts the items hidden for each reason that is not one of these; ``NOTE_CODES`` stays the notes the pages word.
NOT_HIDING_CODES = NOTE_CODES | {"community-report-outweighed"}

# The reasons that say every zone an item comes from is closed: the developers say they are not open (``zone-unreleased``), or the client does not flag them
# (``zones-not-in-eql``). With the wiki's marks they outweigh a report from players.
ZONE_CLOSED_CODES = frozenset({"zone-unreleased", "zones-not-in-eql"})

# The rest of what outweighs a report from players: the reasons the wiki page itself gives for hiding an item (step 3), and the removals that hide it before anything else is looked at
# (step 1: a patch note, the maintainer's research). The report of results (:mod:`trioforge.reports.results_diff`) names them when an item stops being strict because of one.
WIKI_MARK_CODES = frozenset({"wiki-marked-not-in-eql", "wiki-marked-removed"})
REMOVAL_CODES = frozenset({"removed-by-patch", "removed-by-research"})

# Item flags (see trioforge.data.normalize.FLAGS) that the wiki page sets.
WIKI_GONE_FLAGS = frozenset({"wiki_banner_delete", "wiki_banner_does_not_exist", "wiki_banner_dne"})


class EvidenceError(ValueError):
    """A rules file is invalid. ``problems`` lists every defect found."""

    def __init__(self, problems: list[str], source: str = "<memory>") -> None:
        self.problems = list(problems)
        self.source = source
        count = len(self.problems)
        head = f"invalid rules file {source}: {count} problem{'s' if count != 1 else ''}"
        super().__init__("\n".join([head, *(f"  - {problem}" for problem in self.problems)]))


# ---- the shared normalizations --------------------------------------------------------------------

_SPACES = re.compile(r"\s+")
_PARENTHETICAL = re.compile(r"\s*\([^()]*\)\s*$")
_QUOTE_MARKS = "`'‘’‛′´�"  # apostrophes, backticks, the acute accent, a lost quote
_NOT_WORD = re.compile(r"[\W_]+")


def zkey(text: str, *, keep_parenthetical: bool = False) -> str:
    """The one normalization of a zone name: NFKC, casefold, underscores to spaces, one space between
    words, no leading "the ", no trailing parenthetical ("Chardok (Post-Revamp)" is "chardok").

    It is used for alias keys and for every lookup. A name is never reduced to nothing (a name that is
    only a parenthetical keeps it), and the result is a fixed point: ``zkey(zkey(x)) == zkey(x)``.
    With ``keep_parenthetical`` the trailing parenthetical stays, for names of pages, where it is what
    tells two pages apart ("Obsidian Shard (Sky)").
    """
    current = _SPACES.sub(" ", unicodedata.normalize("NFKC", text).casefold().replace("_", " ")).strip()
    while True:
        reduced = current[4:].strip() if current.startswith("the ") else current
        if not keep_parenthetical:
            reduced = _PARENTHETICAL.sub("", reduced).strip() or reduced
        if reduced == current:
            return current
        current = reduced


def title_key(text: str) -> str:
    """:func:`zkey` for the title or name of a page or item: the parenthetical is kept."""
    return zkey(text, keep_parenthetical=True)


def container_key(text: str) -> str:
    """A tradeskill container name for comparison: NFKC, casefold, no apostrophes or backticks, other
    punctuation as a space ("Teir`Dal Forge", "Teir`dal Forge" and "TEIR'DAL FORGE" are one container)."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _SPACES.sub(" ", _NOT_WORD.sub(" ", "".join(c for c in folded if c not in _QUOTE_MARKS))).strip()


def era_key(tag: str) -> str:
    """An era tag for comparison: casefolded, one space between words."""
    return _SPACES.sub(" ", unicodedata.normalize("NFKC", tag).casefold()).strip()


def normalize_era(tag: str) -> str:
    """An era tag in one fixed spelling, for reports: each word capitalized ("FearHateRevamp Era" is
    "Fearhaterevamp Era"). Items keep the spelling their page uses, and tags are compared by :func:`era_key`."""
    return " ".join(word.capitalize() for word in era_key(tag).split())


# ---- reading the hand-written files ---------------------------------------------------------------

_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ITEM_KEY = re.compile(r"(?:w[0-9]{1,15}|r[a-z0-9][a-z0-9-]{0,99})")  # the pattern of the item schema's key


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _whole(value: Any) -> bool:
    return type(value) is int and value >= 0  # a bool is an int to Python, and 75.0 is not a whole number


@functools.lru_cache(maxsize=1)
def _source_validator() -> Draft202012Validator:
    """The rules schema's source_entry: a public URL, a shipped client text file, a public statement, or
    the one fixed label for the maintainer's private observations (never a count, value or date)."""
    schema = json.loads(RULES_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(
        {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/source_entry"}
    )


def _source_problems(where: str, sources: Any) -> list[str]:
    if not isinstance(sources, list) or not sources:
        return [f"{where}.source: a non-empty list of sources is required"]
    problems = []
    for index, entry in enumerate(sources):
        errors = sorted(_source_validator().iter_errors(entry), key=lambda error: list(error.path))
        problems.extend(f"{where}.source[{index}]: {error.message[:120]}" for error in errors[:1])
    return problems


def _entry_problems(section: str, index: int, entry: Any, allowed: set[str]) -> list[str]:
    where = f"{section}[{index}]"
    if not isinstance(entry, dict):
        return [f"{where}: must be an object"]
    problems = [f"{where}: unknown key {key!r}" for key in entry if key not in allowed]
    missing = sorted(allowed - set(entry))
    problems += [f"{where}: missing {key!r}" for key in missing]
    if entry.get("seal") not in SEALS:
        problems.append(f"{where}: seal must be one of {', '.join(SEALS)}")
    if not _valid_date(entry.get("date")):
        problems.append(f"{where}: date must be a calendar date, YYYY-MM-DD")
    if "source" in entry:
        problems.extend(_source_problems(where, entry["source"]))
    return problems


def _titled_section(data: dict, section: str, problems: list[str]) -> dict[str, dict]:
    """The entries of a list of removed pages, by :func:`title_key`; every problem goes to ``problems``."""
    found: dict[str, dict] = {}
    entries = data.get(section)
    if not isinstance(entries, list):
        problems.append(f"{section}: must be a list")
        return found
    for index, entry in enumerate(entries):
        problems.extend(_entry_problems(section, index, entry, {"title", "seal", "source", "date"}))
        if not isinstance(entry, dict):
            continue
        title = entry.get("title")
        if not _text(title):
            problems.append(f"{section}[{index}]: title must be non-blank text")
            continue
        key = title_key(title)
        if key in found:
            problems.append(f"{section}[{index}]: title listed twice ({title!r})")
        else:
            found[key] = entry
    return found


def _zone_section(data: dict, section: str, problems: list[str]) -> tuple[frozenset[str], frozenset[int]]:
    names: set[str] = set()
    ids: set[int] = set()
    entries = data.get(section)
    if not isinstance(entries, list):
        problems.append(f"{section}: must be a list")
        return frozenset(), frozenset()
    for index, entry in enumerate(entries):
        where = f"{section}[{index}]"
        problems.extend(_entry_problems(section, index, entry, {"names", "ids", "seal", "source", "date"}))
        if not isinstance(entry, dict):
            continue
        entry_names, entry_ids = entry.get("names"), entry.get("ids")
        if not isinstance(entry_names, list) or not all(_text(name) for name in entry_names):
            problems.append(f"{where}: names must be a list of non-blank text")
            entry_names = []
        if not isinstance(entry_ids, list) or not all(_whole(i) for i in entry_ids) or len(set(entry_ids)) != len(entry_ids):
            problems.append(f"{where}: ids must be a list of distinct whole numbers (client zone ids)")
            entry_ids = []
        if not entry_names and not entry_ids:
            problems.append(f"{where}: {section} needs at least one name or id")
        names.update(zkey(name) for name in entry_names)
        ids.update(entry_ids)
    return frozenset(names), frozenset(ids)


def _text_list(data: dict, section: str, problems: list[str]) -> list[str]:
    values = data.get(section)
    if not isinstance(values, list) or not values or not all(_text(value) for value in values):
        problems.append(f"{section}: must be a non-empty list of non-blank text")
        return []
    return list(values)


def _keyed_section(data: dict, section: str, problems: list[str]) -> dict[str, dict]:
    """The entries of a list of items picked by catalog key, by key: ``{key, name, note, seal, source, date}``.

    The name is for the reader (the builder counts an entry whose name is not the item's as stale); the note says
    why the maintainer judged as the list does. Every problem goes to ``problems``.
    """
    found: dict[str, dict] = {}
    entries = data.get(section)
    if not isinstance(entries, list):
        problems.append(f"{section}: must be a list")
        return found
    for index, entry in enumerate(entries):
        problems.extend(_entry_problems(section, index, entry, {"key", "name", "note", "seal", "source", "date"}))
        if not isinstance(entry, dict):
            continue
        where = f"{section}[{index}]"
        for field_name in ("name", "note"):
            if field_name in entry and not _text(entry[field_name]):
                problems.append(f"{where}: {field_name} must be non-blank text")
        key = entry.get("key")
        if "key" in entry and (not isinstance(key, str) or _ITEM_KEY.fullmatch(key) is None):
            problems.append(f"{where}: key must be a catalog item key such as 'w1234'")
        elif isinstance(key, str):
            if key in found:
                problems.append(f"{where}: key listed twice ({key!r})")
            else:
                found[key] = entry
    return found


@dataclass(frozen=True)
class HandLists:
    """The hand-kept lists of ``rules/hand-lists.json``, ready for lookup (see :meth:`from_data`).

    ``removed`` and ``research_removals`` map :func:`title_key` of a page title to its entry. The zone
    lists hold wiki spellings (:func:`zkey`) and client ids. ``cultural_containers`` holds
    :func:`container_key` values; ``in_era`` and ``out_of_era`` hold :func:`era_key` values (the lists may
    write an era in any case). ``shields`` and ``not_shields`` map an item key (``"w52912"``) to its entry; both
    sections are optional in the file (absent means empty).
    """

    removed: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    research_removals: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    unreleased_names: frozenset[str] = frozenset()
    unreleased_ids: frozenset[int] = frozenset()
    exists_unflagged_names: frozenset[str] = frozenset()
    exists_unflagged_ids: frozenset[int] = frozenset()
    exists_unflagged_by_name: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)  # zkey -> the entry (its seal and source)
    exists_unflagged_by_id: Mapping[int, Mapping[str, Any]] = field(default_factory=dict)
    eql_only_ids: frozenset[int] = frozenset()
    cultural_containers: frozenset[str] = frozenset()
    in_era: frozenset[str] = frozenset()
    out_of_era: frozenset[str] = frozenset()
    shields: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    not_shields: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_data(cls, data: Any, source: str = "<memory>") -> HandLists:
        """Validate the parsed file and build the lists; :class:`EvidenceError` lists every problem."""
        if not isinstance(data, dict):
            raise EvidenceError(["the file must hold one JSON object"], source)
        problems: list[str] = []
        allowed = {
            "version", "notes", "removed", "research_removals", "unreleased_zones", "exists_unflagged_zones",
            "eql_only_zones", "cultural_containers", "in_era_tags", "out_of_era_tags", "shields", "not_shields",
        }  # fmt: skip
        problems += [f"unknown key {key!r}" for key in data if key not in allowed]
        for key in sorted(allowed - {"notes", "shields", "not_shields"} - set(data)):
            problems.append(f"{key}: missing")
        if "version" in data and not _valid_date(data["version"]):
            problems.append("version: must be a calendar date, YYYY-MM-DD")
        removed = _titled_section(data, "removed", problems) if "removed" in data else {}
        research = _titled_section(data, "research_removals", problems) if "research_removals" in data else {}
        unreleased_names, unreleased_ids = (
            _zone_section(data, "unreleased_zones", problems) if "unreleased_zones" in data else (frozenset(), frozenset())
        )
        exists_names, exists_ids = (
            _zone_section(data, "exists_unflagged_zones", problems)
            if "exists_unflagged_zones" in data
            else (frozenset(), frozenset())
        )
        by_name: dict[str, Mapping[str, Any]] = {}
        by_id: dict[int, Mapping[str, Any]] = {}
        for entry in data.get("exists_unflagged_zones") or ():
            if isinstance(entry, dict) and not problems:
                for name in entry.get("names") or ():
                    by_name.setdefault(zkey(name), entry)
                for zone_id in entry.get("ids") or ():
                    by_id.setdefault(zone_id, entry)
        eql_only = data.get("eql_only_zones")
        if "eql_only_zones" in data and (
            not isinstance(eql_only, list) or not all(_whole(i) for i in eql_only) or len(set(eql_only)) != len(eql_only)
        ):
            problems.append("eql_only_zones: must be a list of distinct whole numbers (client zone ids)")
            eql_only = []
        containers: dict[str, str] = {}
        if "cultural_containers" in data:
            for name in _text_list(data, "cultural_containers", problems):
                key = container_key(name)
                if not key:
                    problems.append(f"cultural_containers: {name!r} has no letters or digits")
                elif key in containers:
                    problems.append(f"cultural_containers: {name!r} repeats {containers[key]!r}")
                else:
                    containers[key] = name
        eras: dict[str, set[str]] = {}
        for section in ("in_era_tags", "out_of_era_tags"):
            eras[section] = set()
            if section not in data:
                continue
            for tag in _text_list(data, section, problems):
                if not era_key(tag).endswith(" era") or not era_key(tag)[: -len(" era")].strip():
                    problems.append(f"{section}: {tag!r} must be an era name ending in 'Era', such as 'Kunark Era'")
                elif era_key(tag) in eras[section]:
                    problems.append(f"{section}: {tag!r} is listed twice")
                else:
                    eras[section].add(era_key(tag))
        for tag in sorted(eras["in_era_tags"] & eras["out_of_era_tags"]):
            problems.append(f"{tag!r} is in both in_era_tags and out_of_era_tags")
        shields = _keyed_section(data, "shields", problems) if "shields" in data else {}
        not_shields = _keyed_section(data, "not_shields", problems) if "not_shields" in data else {}
        for key in sorted(set(shields) & set(not_shields)):
            problems.append(f"{key!r} is in both shields and not_shields")
        if problems:
            raise EvidenceError(problems, source)
        return cls(
            removed=removed,
            research_removals=research,
            unreleased_names=unreleased_names,
            unreleased_ids=unreleased_ids,
            exists_unflagged_names=exists_names,
            exists_unflagged_ids=exists_ids,
            exists_unflagged_by_name=by_name,
            exists_unflagged_by_id=by_id,
            eql_only_ids=frozenset(eql_only or ()),
            cultural_containers=frozenset(containers),
            in_era=frozenset(eras["in_era_tags"]),
            out_of_era=frozenset(eras["out_of_era_tags"]),
            shields=shields,
            not_shields=not_shields,
        )


def load_hand_lists(path: str | Path = HAND_LISTS_PATH) -> HandLists:
    """Read and validate ``rules/hand-lists.json`` (or another file of the same shape)."""
    source = Path(path)
    try:
        data = load_strict(source)
    except JsonFileError as error:
        raise EvidenceError([str(error)], source.name) from error
    return HandLists.from_data(data, source.name)


def load_aliases(
    source: str | Path | Mapping[str, Any] = ALIASES_PATH, zone_ids: Iterable[int] | None = None
) -> dict[str, tuple[int, ...]]:
    """The alias table ``{zkey(wiki zone name): (client ids,)}`` from ``rules/zone-aliases.json``.

    Every key must already be in :func:`zkey` form, every value a non-empty list of distinct client ids,
    and, when ``zone_ids`` is given, each id must be one the client has. All problems are listed at once.
    """
    name = "<memory>"
    if isinstance(source, (str, Path)):
        path = Path(source)
        name = path.name
        try:
            data: Any = load_strict(path)
        except JsonFileError as error:
            raise EvidenceError([str(error)], name) from error
    else:
        data = source
    if not isinstance(data, dict):
        raise EvidenceError(["the file must hold one JSON object"], name)
    problems = [f"unknown key {key!r}" for key in data if key not in {"version", "seal", "sources", "notes", "aliases"}]
    if not _valid_date(data.get("version")):
        problems.append("version: must be a calendar date, YYYY-MM-DD")
    if "seal" in data and data["seal"] not in SEALS:
        problems.append(f"seal: must be one of {', '.join(SEALS)}")
    if "sources" in data:
        problems.extend(_source_problems("file", data["sources"]))
    aliases = data.get("aliases")
    if not isinstance(aliases, dict) or not aliases:
        raise EvidenceError([*problems, "aliases: must be a non-empty object"], name)
    known = None if zone_ids is None else set(zone_ids)
    result: dict[str, tuple[int, ...]] = {}
    for key, ids in aliases.items():
        if not _text(key):
            problems.append("aliases: a zone name is blank")
            continue
        if zkey(key) != key:
            problems.append(f"aliases: {key!r} is not normalized (expected {zkey(key)!r})")
        if not isinstance(ids, list) or not ids or not all(_whole(i) for i in ids) or len(set(ids)) != len(ids):
            problems.append(f"aliases: {key!r} needs a non-empty list of distinct client zone ids")
            continue
        if known is not None:
            problems.extend(f"aliases: {key!r} names client zone id {i}, which the client does not have" for i in ids if i not in known)
        result[key] = tuple(ids)
    if problems:
        raise EvidenceError(problems, name)
    return result


# ---- quests ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Quest:
    """One quest from ``derived/quests.json``: its title, giver, the giver's zone and the page's era tag."""

    title: str
    giver: str | None
    zone: str | None
    era: str | None
    rewards: tuple[str, ...] = ()
    wants: tuple[str, ...] = ()
    wiki_title: str | None = None


class QuestTable:
    """Quests by title (also by page title), by the items they give, and the items they take.

    ``by_title`` and ``by_reward`` are keyed by :func:`title_key`; the first quest of a title wins.
    ``consumed`` holds the keys of the items a quest takes on hand-in. Only a quest whose giver stands in a
    known zone counts: EQL Tools' file also holds list pages that "want" hundreds of items.
    """

    def __init__(self, quests: Iterable[Quest] = ()) -> None:
        self.by_title: dict[str, Quest] = {}
        rewards: dict[str, list[Quest]] = {}
        consumed: set[str] = set()
        for quest in quests:
            for title in (quest.title, quest.wiki_title):
                if title:
                    self.by_title.setdefault(title_key(title), quest)
            for reward in dict.fromkeys(title_key(name) for name in quest.rewards):
                rewards.setdefault(reward, []).append(quest)
            if quest.zone:  # a page with no giver zone is a list of quests ("Popular Quests by Level"), not a quest
                consumed.update(title_key(name) for name in quest.wants)
        self.by_reward: dict[str, tuple[Quest, ...]] = {key: tuple(found) for key, found in rewards.items()}
        self.consumed: frozenset[str] = frozenset(consumed)

    def __len__(self) -> int:
        return len({id(quest) for quest in self.by_title.values()})

    @classmethod
    def from_data(cls, data: Any, source: str = "<memory>") -> QuestTable:
        """Build the table from the parsed ``derived/quests.json``; :class:`EvidenceError` lists problems."""
        if not isinstance(data, dict) or not isinstance(data.get("quests"), list):
            raise EvidenceError(["the file must hold an object with a 'quests' list"], source)
        problems: list[str] = []
        quests = []
        for index, entry in enumerate(data["quests"]):
            where = f"quests[{index}]"
            if not isinstance(entry, dict) or not _text(entry.get("title")):
                problems.append(f"{where}: needs a title")
                continue
            found = []
            for key in ("giver", "zone", "era", "wiki_title"):
                if entry.get(key) is not None and not _text(entry.get(key)):
                    found.append(f"{where}: {key} must be text or null")
            for key in ("rewards", "wants"):
                if not isinstance(entry.get(key), list) or not all(_text(name) for name in entry[key]):
                    found.append(f"{where}: {key} must be a list of text")
            if found:
                problems.extend(found)
                continue
            quests.append(
                Quest(
                    title=entry["title"],
                    giver=entry.get("giver"),
                    zone=entry.get("zone"),
                    era=entry.get("era"),
                    rewards=tuple(entry["rewards"]),
                    wants=tuple(entry["wants"]),
                    wiki_title=entry.get("wiki_title"),
                )
            )
        if problems:
            raise EvidenceError(problems[:50], source)
        return cls(quests)


# ---- the context and the report ---------------------------------------------------------------------


@dataclass(frozen=True)
class Context:
    """Everything :func:`classify` needs besides the item.

    * ``flagged``: the client zone ids the client flags (``derived/client/zones.json``).
    * ``aliases``: :func:`zkey` of a wiki zone name to client ids (:func:`load_aliases`).
    * ``hand``: the hand-kept lists; ``quests``: the quest table.
    * ``seen_keys``: item keys seen in game. **Empty in every committed build**: it is filled only by the
      CI build and by a private local preview, which write outside ``derived/``.
    * ``community_keys``: item keys reported by players (``rules/community-seen.json``). A report is strict
      evidence, except for an item that the wiki page marks as gone (:func:`classify`).
    * ``catalog_keys_allowed``: item keys listed by EQ Legends Tools; empty unless its owner has agreed.
    * ``out_of_era_names``: :func:`title_key` of the items that are out of era (see
      :func:`out_of_era_names`), so a recipe that needs one is not a live source.
    * ``ambiguous_names``: :func:`title_key` of names that more than one page has; such a name never
      finds a quest by reward or by hand-in.
    """

    flagged: frozenset[int] = frozenset()
    aliases: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    hand: HandLists = field(default_factory=HandLists)
    quests: QuestTable = field(default_factory=QuestTable)
    seen_keys: frozenset[str] = frozenset()
    community_keys: frozenset[str] = frozenset()
    catalog_keys_allowed: frozenset[str] = frozenset()
    out_of_era_names: frozenset[str] = frozenset()
    ambiguous_names: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "flagged", frozenset(int(i) for i in self.flagged))
        set_(self, "aliases", {zkey(key): tuple(int(i) for i in ids) for key, ids in dict(self.aliases).items()})
        for name in ("seen_keys", "community_keys", "catalog_keys_allowed", "out_of_era_names", "ambiguous_names"):
            set_(self, name, frozenset(getattr(self, name)))


@dataclass
class Report:
    """What :func:`classify` noticed besides the answer, for the build summary.

    ``unmapped_zones`` counts the zone names with no alias (once per item), ``unknown_eras`` the era tags in
    neither era list.
    """

    unmapped_zones: Counter = field(default_factory=Counter)
    unknown_eras: Counter = field(default_factory=Counter)


def out_of_era_names(items: Iterable[Mapping[str, Any]], hand: HandLists) -> frozenset[str]:
    """The names (:func:`title_key`) of catalog items that are out of era: every page of the name has an
    out-of-era tag and no in-era tag. A recipe that needs one of them has an out-of-era ingredient."""
    flags: dict[str, list[bool]] = {}
    for item in items:
        tags = {era_key(tag) for tag in item.get("era_tags") or ()}
        out_only = bool(tags & hand.out_of_era) and not tags & hand.in_era
        for name in _names_of(item):
            flags.setdefault(name, []).append(out_only)
    return frozenset(name for name, found in flags.items() if all(found))


def ambiguous_names(items: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """The names (:func:`title_key`) that more than one item has: "Bone Chips" is nine different pages."""
    owners: dict[str, set[str]] = {}
    for item in items:
        for name in _names_of(item):
            owners.setdefault(name, set()).add(item["key"])
    return frozenset(name for name, keys in owners.items() if len(keys) > 1)


def _names_of(item: Mapping[str, Any]) -> set[str]:
    names = {title_key(item["name"])} if item.get("name") else set()
    title = (item.get("wiki") or {}).get("title")
    if title:
        names.add(title_key(title))
    return names


# ---- the ladder -------------------------------------------------------------------------------------


def _reason(code: str, seal: str, text: str) -> dict[str, str]:
    return {"code": code, "seal": seal, "text": text[:MAX_TEXT].rstrip()}


def _empty_list(item: Mapping[str, Any], list_field: str, warned_field: str) -> str | None:
    """Why the class list or race list of an item is empty, in the words the note uses, or None when it is not empty: ``"NONE"`` when the page says NONE (or when nothing
    says otherwise), ``"left blank"`` when the line has nothing after it, ``"not understood"`` when it has words that no code is. The lists are empty in all three
    cases (nobody may use or wear the item), but the page shows different things, and the note says what the page shows: the reader's warnings tell them apart
    (``no-classes`` for a stated NONE, ``unknown-code`` and ``bad-value`` for words that are no code, ``bad-value`` alone for a blank line)."""
    if item.get(list_field) != []:
        return None
    warned = {(w.get("code"), w.get("field")) for w in item.get("parse_warnings") or () if isinstance(w, Mapping)}
    if ("no-classes", warned_field) in warned:
        return "NONE"
    if ("unknown-code", warned_field) in warned:
        return "not understood"
    if ("bad-value", warned_field) in warned:
        return "left blank"
    return "NONE"


def _not_for_bis_text(
    *, temporary: bool, handed_in: bool, no_class: str | bool | None, no_race: str | bool | None, unscorable: bool
) -> str:
    """Why an item is not for best-in-slot, naming only the causes that apply (at least one must). ``no_class`` and ``no_race`` are falsy when the list is not empty,
    else what the page shows (:func:`_empty_list`; ``True`` is ``"NONE"``)."""
    causes = []
    if temporary:
        causes.append("temporary")
    if handed_in:
        causes.append("taken by a quest on hand-in")
    if no_class or no_race:
        named = " and ".join(
            f"{kind} {'NONE' if how is True else how}" for kind, how in (("class", no_class), ("race", no_race)) if how
        )
        causes.append(f"open to no class or race ({named})")
    if unscorable:
        causes.append("a hand weapon that cannot be scored")
    text = ", ".join(causes)
    return f"{text[:1].upper()}{text[1:]}: kept in the catalog, not used for best-in-slot."


def _zone_status(name: str, ctx: Context) -> tuple[str, tuple[int, ...]]:
    """``(status, client ids)`` of a wiki zone name: ``live`` (the client flags it), ``exists`` (the hand
    list says it exists although unflagged), ``unreleased``, ``unflagged`` or ``unmapped``."""
    key = zkey(name)
    hand = ctx.hand
    ids = ctx.aliases.get(key)
    if key in hand.unreleased_names:
        return "unreleased", ids or ()
    if key in hand.exists_unflagged_names:
        return "exists", ids or ()
    if ids is None:
        return "unmapped", ()
    if any(i in hand.exists_unflagged_ids for i in ids):
        return "exists", ids
    if any(i in ctx.flagged and i not in hand.unreleased_ids for i in ids):
        return "live", ids
    if any(i in hand.unreleased_ids for i in ids):
        return "unreleased", ids
    return "unflagged", ids


def is_known_zone(name: str, ctx: Context) -> bool:
    """True if ``name`` is a zone the build knows by name: an alias, or a zone of the hand lists (whatever its
    status). Used to find zones written as bullets, where a name that is no zone is a creature."""
    return _zone_status(name, ctx)[0] != "unmapped"


def _exists_entry(name: str, ctx: Context) -> Mapping[str, Any] | None:
    """The hand-list entry (``exists_unflagged_zones``) that makes ``name`` a zone that exists although the client does not flag it: by name first, else by client id."""
    hand = ctx.hand
    key = zkey(name)
    if key in hand.exists_unflagged_by_name:
        return hand.exists_unflagged_by_name[key]
    for zone_id in ctx.aliases.get(key) or ():
        if zone_id in hand.exists_unflagged_by_id:
            return hand.exists_unflagged_by_id[zone_id]
    return None


def _zone_entries(zones: Iterable[tuple[str, str]], ctx: Context) -> list[Mapping[str, Any]]:
    return [entry for zone, status in zones if status == "exists" and (entry := _exists_entry(zone, ctx)) is not None]


def _zone_seal(zones: Iterable[tuple[str, str]], ctx: Context) -> str:
    """The seal of a live source in the zones ``(name, status)``: ``client`` if the client flags one of them; else the strongest seal of the hand-list entries
    that make them exist (an entry sealed ``player`` is the players' word, not the developers')."""
    zones = list(zones)
    if any(status == "live" for _, status in zones):
        return "client"
    entries = _zone_entries(zones, ctx)
    return min((entry["seal"] for entry in entries), key=SEALS.index, default="developer")


def _zone_source_note(zones: Iterable[tuple[str, str]], ctx: Context) -> str:
    """`` Source: <address>.`` for a live source that rests on an exists-unflagged entry that is not the developers' (the developers' entries read as they always did)."""
    zones = list(zones)
    if _zone_seal(zones, ctx) in ("client", "developer"):
        return ""
    refs = sorted(
        {
            source["ref"]
            for entry in _zone_entries(zones, ctx)
            if entry["seal"] != "developer"
            for source in entry.get("source") or ()
            if isinstance(source, Mapping) and source.get("kind") == "url" and isinstance(source.get("ref"), str)
        }
    )
    return f" Source: {', '.join(refs)}." if refs else ""


def _found_quests(item: Mapping[str, Any], ctx: Context) -> list[Quest]:
    found: dict[int, Quest] = {}
    sources = item.get("sources") or {}
    # a quest is looked up by the target of its link (the page title); the label of the link, which is how the page
    # names one test among many, is a second chance for the few quests whose title is that label
    names = [*(sources.get("quests") or ()), *(entry.get("label") for entry in sources.get("quest_labels") or () if isinstance(entry, Mapping))]
    for name in names:
        if not isinstance(name, str):
            continue
        quest = ctx.quests.by_title.get(title_key(name))
        if quest is not None:
            found.setdefault(id(quest), quest)
    name_key = title_key(item["name"]) if item.get("name") else ""
    if name_key and name_key not in ctx.ambiguous_names:
        for quest in ctx.quests.by_reward.get(name_key, ()):
            found.setdefault(id(quest), quest)
    return list(found.values())


def _names_a_test(label: str, ctx: Context) -> bool:
    """True if the label of a quest link names a test: it is not blank, not a zone's name (a place such as
    ``Neriak Third Gate``) and not the title of a quest in the table (that quest decides, see :func:`_found_quests`)."""
    return bool(label.strip()) and title_key(label) not in ctx.quests.by_title and _zone_status(label, ctx)[0] == "unmapped"


def _quest_zone_links(item: Mapping[str, Any], ctx: Context) -> list[tuple[str, str, tuple[int, ...], str]]:
    """``(zone name, status, client ids, label)`` for each zone whose page is the **target** of a quest link that names a test.

    The Plane of Sky class tests are linked this way: the target is the zone (``Plane of Sky``) and the label of the link
    names the test (``Paladin Test of Sacrifice``), which puts a quest in that zone. A link counts only when
    ``sources.quest_labels`` holds a label for that target that names a test (:func:`_names_a_test`): a bare link says
    nothing about a quest, a label that is a zone's name is a place, and a label that is the title of a quest in the
    table leaves the decision to that quest, so a quest the table rejects is never replaced by the zone next to it.

    The target is a zone the alias table or the hand lists know, resolved as a drop zone is, but it is not the title of a
    quest in the table (that quest is found by :func:`_found_quests`) and has no qualifier in parentheses: ``Zorblax
    Hollow (Quest)`` is a quest page, not a zone page, although :func:`zkey` would drop the qualifier. A target that is no
    zone finds nothing and is no unmapped zone, since most targets are quest titles the table lacks. The item's own name is
    never read as a zone. A zone is listed once, under the first spelling of its targets and with the first of its labels,
    both in sorted order, so the answer does not depend on the order of the item's lists. :func:`_signals` reads the links
    only when the item has no other live source.
    """
    sources = item.get("sources") or {}
    labels: dict[str, set[str]] = {}  # the labels of the links, by the key of the target they belong to
    for entry in sources.get("quest_labels") or ():
        if isinstance(entry, Mapping) and isinstance(entry.get("title"), str) and isinstance(entry.get("label"), str):
            labels.setdefault(title_key(entry["title"]), set()).add(entry["label"])
    links: dict[str, tuple[str, str, tuple[int, ...], str]] = {}
    for name in sorted(target for target in sources.get("quests") or () if isinstance(target, str)):
        key = title_key(name)
        if key in ctx.quests.by_title or key != zkey(name):
            continue  # the title of a quest in the table, or of a quest page that has a qualifier in parentheses
        status, ids = _zone_status(name, ctx)
        if status == "unmapped":
            continue  # most targets are quest titles the table lacks: nothing found, and no unmapped zone to report
        tests = sorted(label for label in labels.get(key, ()) if _names_a_test(label, ctx))
        if tests:
            links.setdefault(zkey(name), (name, status, ids, tests[0]))
    return list(links.values())


def _signals(item: Mapping[str, Any], ctx: Context, report: Report | None) -> tuple[str, dict[str, dict[str, str]]]:
    """The level the wiki and client signals give (``wiki``, ``disputed`` or ``hidden``) and their reasons."""
    hand = ctx.hand
    sources = item.get("sources") or {}
    reasons: dict[str, dict[str, str]] = {}
    unmapped: set[str] = set()

    # -- zones of the drops, vendors, quest givers and quest links
    drop_status: dict[str, str] = {}
    eql_only = False
    for drop in sources.get("drops") or ():
        zone = drop.get("zone")
        if zone:
            status, ids = _zone_status(zone, ctx)
            drop_status[zone] = status
            eql_only = eql_only or any(i in hand.eql_only_ids for i in ids)
            if status == "unmapped":
                unmapped.add(zone)
    live_zones = sorted(zone for zone, status in drop_status.items() if status in ("live", "exists"))
    for zone in live_zones[:MAX_LIVE_ZONE_REASONS]:
        pair = [(zone, drop_status[zone])]
        seal = _zone_seal(pair, ctx)
        how = "a zone the client marks as part of EQL" if drop_status[zone] == "live" else "a zone that exists in EQL although the client does not flag it"
        reasons[f"live-source:{zone}"] = _reason(f"live-source:{zone}", seal, f"Drops in {zone}, {how}." + _zone_source_note(pair, ctx))

    # foraged zones go through the same gate as the drop zones (a live one is a source; the EQL-only exemption applies)
    foraged_status: dict[str, str] = {}
    for entry in sources.get("foraged") or ():
        zone = entry.get("zone") if isinstance(entry, Mapping) else None
        if zone:
            status, ids = _zone_status(zone, ctx)
            foraged_status[zone] = status
            eql_only = eql_only or any(i in hand.eql_only_ids for i in ids)
            if status == "unmapped":
                unmapped.add(zone)
    if {"live", "exists"} & set(foraged_status.values()):
        reasons["live-source:foraged"] = _reason(
            "live-source:foraged",
            _zone_seal(foraged_status.items(), ctx),
            "Foraged in a zone that is part of EQL." + _zone_source_note(foraged_status.items(), ctx),
        )

    vendor_status = []
    for sold in sources.get("sold_by") or ():
        zone = sold.get("zone")
        if zone:
            status, _ = _zone_status(zone, ctx)
            vendor_status.append((zone, status))
            if status == "unmapped":
                unmapped.add(zone)
    if {"live", "exists"} & {status for _, status in vendor_status}:
        reasons["live-source:vendor"] = _reason(
            "live-source:vendor",
            _zone_seal(vendor_status, ctx),
            "Sold by a vendor in a zone that is part of EQL." + _zone_source_note(vendor_status, ctx),
        )

    quest_status = []
    for quest in _found_quests(item, ctx):
        if quest.zone:
            status, _ = _zone_status(quest.zone, ctx)
            if status == "unmapped":
                unmapped.add(quest.zone)
            if status in ("live", "exists") and era_key(quest.era or "") not in hand.out_of_era:
                quest_status.append((quest.zone, status))
    if quest_status:
        reasons["live-source:quest"] = _reason(
            "live-source:quest",
            _zone_seal(quest_status, ctx),
            "A quest gives it, and the quest giver stands in a zone that is part of EQL." + _zone_source_note(quest_status, ctx),
        )

    # -- recipes
    cultural = out_of_era_ingredient = live_craft = False
    for recipe in sources.get("crafted") or ():
        container = recipe.get("container")
        if not container:
            continue  # the container is not written down: neither a live source nor a cultural one
        if container_key(container) in hand.cultural_containers:
            cultural = True
        elif any(title_key(name) in ctx.out_of_era_names for name in recipe.get("ingredients") or ()):
            out_of_era_ingredient = True
        else:
            live_craft = True
    if live_craft:
        reasons["live-source:craft"] = _reason(
            "live-source:craft", "player", "Player-crafted in a container that is not cultural, from ingredients that are not out of era."
        )

    # -- quest links to the page of a zone that name a test, read only when nothing else is live: a quest link can mean
    # "used in this quest" as well as "rewarded by it" (a component that drops in the zone and is handed in to the quest is
    # no reward). The link puts the quest in that zone, which goes through the same gate as a drop zone; only a live zone can
    # leave the era tags out of it (below), as the link must be the live source. As the quest has no page (so no era) of its
    # own, the item's own era tags judge it below, EQL-only exemption included.
    link_status: dict[str, str] = {}
    if not any(code.startswith("live-source:") for code in reasons):
        live_links = []
        for zone, status, ids, label in _quest_zone_links(item, ctx):
            link_status[zone] = status
            if status in ("live", "exists"):
                eql_only = eql_only or any(i in hand.eql_only_ids for i in ids)
                live_links.append((status != "live", zone, label, status))  # a live zone is named before one that only exists
        if live_links:
            _, zone, label, _ = min(live_links)
            linked = [(name, status) for _, name, _, status in live_links]
            reasons["live-source:quest"] = _reason(
                "live-source:quest",
                _zone_seal(linked, ctx),
                f"The item page links it to a quest in {zone} ({label}), a zone that is part of EQL." + _zone_source_note(linked, ctx),
            )

    # -- era tags
    tags = sorted({normalize_era(tag) for tag in item.get("era_tags") or () if isinstance(tag, str) and tag.strip()})
    in_tags = [tag for tag in tags if era_key(tag) in hand.in_era]
    out_tags = [tag for tag in tags if era_key(tag) in hand.out_of_era]
    if report is not None:
        for tag in tags:
            if era_key(tag) not in hand.in_era and era_key(tag) not in hand.out_of_era:
                report.unknown_eras[tag] += 1
        report.unmapped_zones.update(unmapped)

    live = any(code.startswith("live-source:") for code in reasons)
    if live:
        if out_tags and not eql_only:
            reasons["out-of-era-tag-live-zone"] = _reason(
                "out-of-era-tag-live-zone", "player", "A live source exists, but the wiki's era tag is out of era."
            )
            if in_tags:
                reasons["conflicting-era-tags"] = _reason(
                    "conflicting-era-tags", "player", "The wiki tags both an in-era and an out-of-era period."
                )
            return "disputed", reasons
        return "wiki", reasons

    statuses = [*drop_status.values(), *foraged_status.values(), *link_status.values()]
    kinds = [kind for kind, found in (("drop", drop_status), ("foraging", foraged_status), ("quest", link_status)) if found]
    where = " or ".join([", ".join(kinds[:-1]), kinds[-1]] if len(kinds) > 1 else kinds)  # "drop", "drop or quest", "drop, foraging or quest"
    if statuses and all(status == "unreleased" for status in statuses):
        reasons["zone-unreleased"] = _reason("zone-unreleased", "developer", f"Every {where} zone is flagged but not yet released.")
    elif statuses and all(status == "unmapped" for status in statuses):
        reasons["zones-unmapped"] = _reason("zones-unmapped", "model", f"No {where} zone could be matched to a client zone.")
    elif statuses:
        reasons["zones-not-in-eql"] = _reason("zones-not-in-eql", "client", f"No {where} zone is part of EQL: the client does not flag them.")
    if out_tags:
        reasons["out-of-era"] = _reason("out-of-era", "player", "The wiki's era tag is out of era and no live source was found.")
    if cultural:
        reasons["cultural-container"] = _reason(
            "cultural-container", "player", "Made only in cultural tradeskill containers, which players report EQL does not have."
        )
    if out_of_era_ingredient:
        reasons["out-of-era-ingredient"] = _reason(
            "out-of-era-ingredient", "player", "Every recipe in a usable container needs an ingredient that is out of era."
        )
    if not reasons:
        reasons["no-known-source"] = _reason("no-known-source", "model", "No source that the pipeline can check as live.")
    return "hidden", reasons


def _flags_of(item: Mapping[str, Any]) -> frozenset[str]:
    """The item's flags, ASCII-lowercased."""
    return frozenset(
        flag.translate(_ASCII_LOWER) for flag in (item.get("flags") or ()) if isinstance(flag, str)
    )


_ASCII_LOWER = {code: code + 32 for code in range(ord("A"), ord("Z") + 1)}


def _wiki_marked(flags: frozenset[str]) -> dict[str, dict[str, str]]:
    """The reasons that the wiki page itself gives for hiding the item (empty if it gives none)."""
    reasons: dict[str, dict[str, str]] = {}
    if flags & WIKI_GONE_FLAGS:
        reasons["wiki-marked-not-in-eql"] = _reason(
            "wiki-marked-not-in-eql", "player", "The wiki page carries a banner that says it was deleted or does not exist in EQL."
        )
    if "removed_note" in flags:
        reasons["wiki-marked-removed"] = _reason(
            "wiki-marked-removed", "player", "The wiki page says the item was removed from the game."
        )
    return reasons


def classify(item: Mapping[str, Any], ctx: Context, report: Report | None = None) -> dict[str, Any]:
    """The evidence for one catalog item: ``{"level": ..., "reasons": [{"code", "seal", "text"}, ...]}``.

    ``item`` is a catalog item (the shape :func:`trioforge.data.normalize.normalize` returns; only ``key``,
    ``name`` and the fields read here are needed). It is never changed. Reasons are sorted by code, so the
    answer does not depend on the order of the item's lists or on hash order. ``report`` (optional) collects
    unmapped zone names and unknown era tags.
    """
    hand = ctx.hand
    key = item["key"]
    name = item.get("name") or ""
    title = (item.get("wiki") or {}).get("title") or name
    flags = _flags_of(item)
    reasons: dict[str, dict[str, str]]

    removal = hand.removed.get(title_key(title))
    research = hand.research_removals.get(title_key(title))
    if removal is not None or research is not None:
        level = "hidden"
        reasons = {}
        if removal is not None:
            reasons["removed-by-patch"] = _reason(
                "removed-by-patch", "developer", f"A patch note ({removal['date']}) says this item no longer drops."
            )
        if research is not None:
            reasons["removed-by-research"] = _reason(
                "removed-by-research", "measured", "Removed or replaced in EQL, from the maintainer's private observation."
            )
    else:
        signal_level, signal_reasons = _signals(item, ctx, report)
        marked = _wiki_marked(flags)
        strict: dict[str, dict[str, str]] = {}
        if key in ctx.seen_keys:
            strict["seen-in-game"] = _reason("seen-in-game", "measured", "Seen in game.")
        if key in ctx.catalog_keys_allowed:
            strict["eql-catalog"] = _reason("eql-catalog", "player", "Listed in the EQ Legends Tools catalog.")
        reported = key in ctx.community_keys
        closed = bool(ZONE_CLOSED_CODES & signal_reasons.keys())  # every zone the item comes from is closed: unreleased, or not part of EQL by the client's flags
        if reported and (strict or not (marked or closed)):
            # A report is strict evidence, but it never overrides the wiki's own word that the item is gone, nor the word of the developers or the client that every zone it
            # comes from is closed (a screenshot of the item window shows that the item is in the game's data, not that anyone can get it). Of the evidence that does
            # override them (the maintainer's seen flags, a listing the owner allows), a report beside it is listed as ever; on its own it is outweighed (below).
            strict["community-report"] = _reason("community-report", "player", "Reported as seen in game by players.")
        if strict:
            level, reasons = "strict", strict
            conflicts = sorted(code for code in (*signal_reasons, *marked) if code in CONFLICT_CODES)
            if conflicts:
                reasons["conflict-note"] = _reason(
                    "conflict-note", "model", f"Kept as strict although other signals disagree ({', '.join(conflicts)})."
                )
        elif marked:
            level, reasons = "hidden", marked  # the page says the item is gone: its sources are stale, so they are not listed
            if reported:
                reasons["community-report-outweighed"] = _reason(
                    "community-report-outweighed", "player", "Players reported the item, but the wiki's own mark says it is gone, and that outweighs a report."
                )
        else:
            level, reasons = signal_level, signal_reasons
            if reported and closed:
                reasons["community-report-outweighed"] = _reason(
                    "community-report-outweighed", "player", "Players reported the item, but every zone it comes from is unreleased or not part of EQL, and that outweighs a report."
                )

    name_key = title_key(name) if name else ""
    causes = {
        "temporary": "temporary" in flags,
        "handed_in": name_key in ctx.quests.consumed and name_key not in ctx.ambiguous_names,
        "no_class": _empty_list(item, "classes", "class"),  # the page says Class: NONE, or leaves the line blank
        "no_race": _empty_list(item, "races", "race"),  # the page says Race: NONE, or leaves the line blank
        "unscorable": weapon_incomplete(item.get("weapon"), item.get("slots") or ()),
    }
    if any(causes.values()):
        reasons["not-for-bis"] = _reason("not-for-bis", "model", _not_for_bis_text(**causes))
    if item.get("deity"):
        reasons["not-for-default-kits"] = _reason(
            "not-for-default-kits", "model", "Deity-locked: left out of default kits, offered as a runner-up."
        )
    if (item.get("origin") or {}).get("source") == "eqlegendstools":
        reasons["source-eql-tools"] = _reason(
            "source-eql-tools",
            "player",
            "Stats and drop sources are read from the EQ Legends Tools page of the item, the source of truth for it.",
        )
    if "wiki_banner_revamped" in flags:
        reasons["wiki-marked-revamped"] = _reason(
            "wiki-marked-revamped", "player", "The wiki page is marked as revamped: its stats or sources may have changed."
        )
    return {"level": level, "reasons": [reasons[code] for code in sorted(reasons)]}
