"""Read the precompute's results. This is the only module of the site generator that opens a results file.

The files read are the ones :mod:`trioforge.precompute.shards` writes (``build/results/<trio>/``, ``<trio>`` being the class
codes in EQ class-id order, such as ``pal-mnk-ber``); the **format is documented there**, once, and this module reads exactly
that. If the format changes, ``shards.py``, this file and the fixtures in ``fixtures/site/results`` are the three things to
change, and ``pipeline/tests/test_site_integration.py`` fails until the fixtures have the keys a real run writes. Everything else
works on the model below, and the browser never sees a results file: it fetches the compact files :func:`site_shard_json`,
:func:`site_runnerups_json` and :func:`site_robust_json` write from the model.

What this reader asks of the files, on top of the format:

* **One run.** Every file names ``data_release``, ``game_patch`` and ``rules_version``; they must be the same in all of them.
  The four shards must hold the same races, roles and tiers, and each grid must be complete: every race x role x tier x (the
  role's setups) has exactly one scenario, so a combination the page offers always has an answer, and a combination with none
  is never offered. **The tiers are the scope of the run** (+0, +4 and +10 for most trios, every tier for the milestone trio): a
  shard records them (``tiers``), the reader holds its rows to the record, and the tiers of the four shards are the tiers the page
  offers and the ones every runner-up file must hold. The reader takes the scope it is given: that it is the scope of a full run of the
  trio is asked of an indexable build (:func:`trioforge.site.build.check_scope`), since a run of any tiers is a full one. The setups are
  each shard's own, as its rows have them (they follow the item pool of the evidence level,
  so the wiki shards can have one the strict shards have not: the shield setup, while the strict pool has no shield a class of
  the trio can wear), and no shard is compared with another for them. A narrowed run (``partial``) is read as it is; the
  grid is the one in the rows.
* **The default answer** comes from ``defaults.json``: the ``view`` (role, tier, evidence level, buffs), the race, its best
  ``setup`` and the runner-up race and margin. The evidence level of the view is ``strict``, or ``wiki`` while no item is strict
  (``strict_pool_empty``); the runner-ups are made for that level, and their files must say so. The ``setup`` of the answer and
  of every runner-up view is one that level has for the role.
* **Items.** A summoned item has no arrival tier (``null``) and every other has one; an item may list slots that no place of a
  kit has (``AMMO``); an item worn in a place must list its group. A swap of an item anyone can wear never beats the kit; a swap
  of an item that needs a deity may. Each slot lists up to three swaps of the first kind and at most one of the second.
* **Totals** are signed whole numbers (a naked character can have a regeneration below zero).
* **The runner-up folder** has an index that lists every file in the folder, with the size and the SHA-256 of its bytes, and
  every listed file must match; a missing, extra or changed file stops the build. There is **one file for each role of the run**
  (``runnerups/<role>.json``), and it holds a view of every race at every tier of the scope: its ``tiers`` must be those of the shards
  (a tier outside them, a tier of them missing and a tier twice are each refused), each view is of one of them, and no view is twice.
  A folder of the earlier layout, a file for each role and tier, is refused and says to run the precompute again. Every results file
  carries ``version`` (the writer's format number, 1) and the reader accepts that number alone, the runner-up files and their index included.
* **One list of tiers.** The four shards hold the same tiers (a message says which differ), the runner-up index and the file of each role hold
  those, and ``robust.json`` lists some of them, the tiers its seals are made for, each once and in order and each with labels. A trio's
  :attr:`TrioResults.tiers` is that one list; it is what the build asks for, and a trio put together by hand from files of other tiers has none.
* **The engine's two files.** The bundle of the trio (``engine-l<level>.json``, read by :func:`load_trio` beside the shards) must have
  the exporter's format number and fields, name the trio, the level, the ``data_release`` and the ``rules_version`` of the shards, hold
  only reduced ``p/q`` texts for its exact numbers, reassemble to profiles with the exporter's own reader
  (:func:`trioforge.export.browser.assemble`, for the first and the last race, role and buff set at each evidence level) and list, for
  every role and evidence level of the shards, the weapon setups the shards have. The item table (``items.json`` of the folder of
  results, read by :func:`load_items` for all the trios at once) must have the format number, the release and the rules version of
  the shards, the exporter's defaults and well-formed records, and describe every item that a shard or a runner-up file shows (name,
  slots, tier rule, deity, evidence level) as that file does. Both are kept as they were written (:class:`BrowserFile`): the build
  publishes those bytes. Both carry the **fingerprint of the inputs** of the run that made them (``inputs``): a trio whose bundle does
  not share it with ``items.json`` was made from another catalog or other seen flags than the table, and the build says which trio to
  run again; the weapon setups of the bundle are held to the evidence levels of the table (the shield setup needs a shield in the pool
  of its level). And both are held to the limits of the browser's own readers (``items.js`` and ``profile.js``: how many deities,
  races and reason codes a record has, how long a text is, a stat the model knows, the shape of the source of an item, the depth and
  the number of exact numbers of a bundle ...; :data:`RECORD_LIMITS` and :data:`BUNDLE_LIMITS` are the numbers, and a test holds them
  to the readers'), which the build then runs on everything it publishes.

The model
=========

:class:`TrioResults` = :class:`Meta` + four :class:`Shard` + :class:`RunnerUps` + :class:`Robust` + :class:`Defaults`.
A :class:`Shard` is a tuple of :class:`Scenario` (race, role, tier, setup, a 22-place ``kit`` of :class:`Item` or ``None``,
the value ``F``, the ``gain`` over the naked character, :class:`Totals`, the ``buffs`` (the optional buff ids chosen) and
the ``haste_assumed`` the weapons were scored at) with lookups by (race, role, tier, setup). Values are kept to three decimals,
which is all any page shows.

Everything is checked as it is read, and a problem raises :class:`ResultsError` with one line naming the file and the field.
Text (an item's name, a source, a label) is passed through untouched: escaping is the templates' and the DOM code's job.
"""

from __future__ import annotations

import datetime
import gzip
import hashlib
import math
import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from trioforge.classes import CLASS_CODES
from trioforge.data.jsonio import JsonFileError, loads_strict, render

__all__ = [
    "BUFFS",
    "BUNDLE_LIMITS",
    "BrowserFile",
    "Credit",
    "EFFECTS_NAME",
    "EXALT_NAME",
    "Exalt",
    "exalt_slugs",
    "Defaults",
    "ENGINE_VERSION",
    "EVIDENCE",
    "ITEMS_NAME",
    "ITEM_KEYS",
    "Item",
    "KEY_PATTERN",
    "Meta",
    "OTHER_SLOTS",
    "PLACES",
    "RACE_CODES",
    "RECORD_LIMITS",
    "ROLES",
    "ResultsError",
    "Robust",
    "RobustView",
    "RUNNERUPS_VERSION",
    "RunnerUpView",
    "RunnerUps",
    "SCHOOLS",
    "SETUPS",
    "STAT_NAMES",
    "SV_NAMES",
    "SLOT_INSTANCES",
    "Scenario",
    "Sealed",
    "Shard",
    "Swap",
    "TOTALS_KEYS",
    "Totals",
    "TrioResults",
    "WHY_REASONS",
    "WHY_TERMS",
    "Why",
    "WhyPlace",
    "WhyTerm",
    "engine_name",
    "list_trios",
    "load_exalt",
    "load_items",
    "load_trio",
    "site_effects_json",
    "site_exalt_json",
    "site_robust_json",
    "site_runnerups_json",
    "site_shard_json",
]

# ---- the vocabulary (equal to the model's and the precompute's; a test says so) ----------------------------------------

#: the group of each place of a kit, in kit order (22 places)
SLOT_INSTANCES: tuple[str, ...] = tuple(
    "HEAD FACE EAR EAR NECK SHOULDERS ARMS BACK WRIST WRIST HANDS FINGER FINGER CHEST LEGS FEET WAIST RANGE ANY ANY "
    "PRIMARY SECONDARY".split()
)
SLOT_GROUPS = frozenset(SLOT_INSTANCES)
#: slots a catalog item may list that no place of a kit has (a thrown weapon fits the range place and the ammo place)
OTHER_SLOTS = ("AMMO", "CHARM", "POWERSOURCE")
ITEM_SLOTS = (SLOT_GROUPS - {"ANY"}) | set(OTHER_SLOTS)
ROLES = ("balanced", "tank", "melee", "caster")
SETUPS = ("1h-shield", "2h", "dw", "stick")
RACE_CODES = tuple("HUM BAR ERU ELF HIE DEF HEF DWF TRL OGR HFL GNM IKS KER FRG".split())
SCHOOLS = ("MAGIC", "FIRE", "COLD", "DISEASE", "POISON")
EVIDENCE = ("strict", "wiki")
BUFFS = ("own", "group")
TIER_RULES = ("drop", "fixed0", "spell")
MAX_TIER = 10
MAX_HASTE = 1000
MAX_TOTAL = 10_000_000  # a total is a signed whole number below this in size
KIT_SIZE = len(SLOT_INSTANCES)
MAX_FREE_SWAPS = 3  # runner-ups per slot that need no deity
MAX_LOCKED_SWAPS = 1  # and the most that need one
BEAT_TOLERANCE = 1e-9  # a swap of an item anyone can wear is worth no more than the kit, give or take a float's noise


def _places() -> tuple[str, ...]:
    """The 22 place names of a kit: the group name, with a number when the group has two places (``EAR1``, ``EAR2``)."""
    seen: dict[str, int] = {}
    names = []
    for group in SLOT_INSTANCES:
        seen[group] = seen.get(group, 0) + 1
        names.append(f"{group}{seen[group]}" if SLOT_INSTANCES.count(group) > 1 else group)
    return tuple(names)


PLACES = _places()
ITEM_KEYS = ("key", "name", "slots", "tier_rule", "arrival", "source", "evidence", "deity")
#: the columns of a totals row; the model's :class:`Totals` orders its resists by :data:`SCHOOLS` instead
TOTALS_KEYS = (
    "ac", "hp", "mana", "end", "haste", "atk", "fire", "cold", "magic", "poison", "disease", "hpreg", "manareg", "endreg",
)  # fmt: skip

SHARD_NAMES = tuple(f"{evidence}-{buffs}" for evidence in EVIDENCE for buffs in BUFFS)
FORMAT_VERSION = 1
ENGINE_VERSION = 1  # the format number of the bundle and of the item table (export.browser.FORMAT)
ITEMS_NAME = "items.json"  # the item table, in the folder of results
BROWSER_VERSION = 1  # the browser's shard files
RUNNERUPS_VERSION = 2  # the browser's runner-up file: version 2 is the file of a role with every tier of the run in it (version 1 was one for a role and a tier)
ROBUST_VERSION = 2  # the browser's robust file: version 2 says, for each view, what it was sealed for
#: the terms of the why of a kit row (precompute/kitwhy.py: TERMS, REASONS; a test holds them equal)
WHY_TERMS = (
    "AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG", "HASTE",
    "FIRE", "COLD", "MAGIC", "POISON", "DISEASE", "DAMAGE",
)  # fmt: skip
WHY_REASONS = ("resist-cap", "regen-cap", "haste-cap", "haste-covered", "ac-softcap")

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?![\s\S])")
_RELEASE = re.compile(r"data-([0-9]{4}-[0-9]{2}-[0-9]{2})(?![\s\S])")
_SHA256 = re.compile(r"[0-9a-f]{64}(?![\s\S])")
_RUNNERUP_NAME = re.compile(r"([a-z]+)\.json(?![\s\S])")
_OLD_RUNNERUP_NAME = re.compile(r"[a-z]+-(?:0|[1-9][0-9]?)\.json(?![\s\S])")  # the file of a role and a tier, as an earlier precompute wrote it
#: the one pattern of an item key, for the reader of the results, the build's list of the pages of the items and the page code that links them (static/trio.js has it as ITEM_KEY; a test says
#: so): a wiki page id with no zero in front (w07 is not another way of writing w7), or an ``r`` and the key of an item that has no page on the wiki, 101 characters at most
KEY_PATTERN = r"(?:w[1-9][0-9]{0,14}|r[a-z0-9][a-z0-9-]{0,99})"
_KEY = re.compile(KEY_PATTERN + r"(?![\s\S])")  # (the end of the text is asked for as "nothing follows", which a newline at the end does not satisfy)
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")  # control characters, and the line and paragraph separators
MAX_TEXT = 300


class ResultsError(ValueError):
    """A results file cannot be used. One line: the file, the field, what is wrong. Never the file's content at length."""


# ---- the model --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Credit:
    """What every file of the browser format says about itself: the data release it was made from, its licence, and the
    attribution that licence asks for. A file without them is a file nobody can credit, so the writers require one."""

    release: str  # the data release tag, "data-2026-10-14"
    license: str  # "CC BY-SA 4.0"
    attribution: str


@dataclass(frozen=True)
class Meta:
    """What identifies the results: the trio, the level and the data release, the same in every file of the trio.

    ``partial`` is true when the run was narrowed (a few races or roles, say; the tiers of a run are its scope, not a narrowing): such results are good for a look only."""

    slug: str  # "pal-mnk-ber"
    trio: tuple[str, str, str]  # ("PAL", "MNK", "BER"), EQ class-id order
    level: int
    data_tag: str  # "data-2026-10-14"
    data_date: str  # "2026-10-14", the date inside the tag
    game_patch: str  # the date of the game patch the data was read at
    rules_version: str  # the version of rules.json the numbers were computed with
    partial: bool = False


@dataclass(frozen=True)
class Item:
    """One wearable. ``arrival`` is the highest tier at which a copy exists without merging (a drop: 4; a quest reward: 0),
    or None for a summoned item, whose tier is its spell rank."""

    key: str
    name: str
    slots: tuple[str, ...]
    tier_rule: str
    arrival: int | None
    source: str
    evidence: str  # "strict": seen in game; "wiki": listed by the wiki only
    deity: tuple[str, ...] | None


@dataclass(frozen=True)
class Totals:
    """What a kit adds up to. ``resists`` follows :data:`SCHOOLS`; ``regen`` is (HP, mana, endurance) a tick. All are signed."""

    ac: int
    hp: int
    mana: int
    end: int
    haste: int
    atk: int
    resists: tuple[int, int, int, int, int]
    regen: tuple[int, int, int]


@dataclass(frozen=True)
class Scenario:
    race: str
    role: str
    tier: int
    setup: str
    kit: tuple[Item | None, ...]  # 22 places in SLOT_INSTANCES order; None is an empty place
    value: float  # F, the value of the whole character in HP-equivalents
    gain: float  # what the gear adds over the naked character
    totals: Totals
    buffs: tuple[int, ...]  # the optional buffs (spell ids) the solution keeps up
    haste_assumed: int  # the haste, in percent, the weapons were scored at


@dataclass(frozen=True)
class Shard:
    """The scenarios of one (evidence, buffs) pair, with lookups. Build one with its scenarios; the index is derived."""

    evidence: str
    buffs: str  # the buff set: "own" or "group"
    items: tuple[Item, ...]
    scenarios: tuple[Scenario, ...]
    solver: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)  # as the precompute recorded it
    build_options: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    races: tuple[str, ...] = field(init=False, repr=False, compare=False)  # in file order
    roles: tuple[str, ...] = field(init=False, repr=False, compare=False)  # in ROLES order
    tiers: tuple[int, ...] = field(init=False, repr=False, compare=False)  # ascending
    _index: dict[tuple[str, str, int, str], Scenario] = field(init=False, repr=False, compare=False)
    _setups: dict[str, tuple[str, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        index = {(s.race, s.role, s.tier, s.setup): s for s in self.scenarios}
        races = tuple(dict.fromkeys(s.race for s in self.scenarios))
        roles = tuple(role for role in ROLES if any(s.role == role for s in self.scenarios))
        tiers = tuple(sorted({s.tier for s in self.scenarios}))
        setups = {
            role: tuple(setup for setup in SETUPS if any(s.role == role and s.setup == setup for s in self.scenarios))
            for role in roles
        }
        for name, value in (("_index", index), ("races", races), ("roles", roles), ("tiers", tiers), ("_setups", setups)):
            object.__setattr__(self, name, value)

    def scenario(self, race: str, role: str, tier: int, setup: str) -> Scenario | None:
        return self._index.get((race, role, tier, setup))

    def setups_for(self, role: str) -> tuple[str, ...]:
        """The setups this role has scenarios for, in :data:`SETUPS` order. A setup not listed is never offered."""
        return self._setups.get(role, ())

    def best_setup(self, race: str, role: str, tier: int) -> str:
        """The role's best setup at this race and tier: the highest value, the earlier setup on a tie."""
        candidates = [self._index[(race, role, tier, setup)] for setup in self.setups_for(role)]
        return max(candidates, key=lambda s: (s.value, -SETUPS.index(s.setup))).setup


@dataclass(frozen=True)
class Swap:
    """A runner-up for one slot: the item, and what the kit's value changes by. Never above zero for an item anyone can wear;
    an item that needs a deity can be better than the kit's pick."""

    item: Item
    delta: float


@dataclass(frozen=True)
class RunnerUpView:
    race: str
    role: str
    tier: int
    setup: str
    slots: tuple[tuple[Swap, ...], ...]  # 22 places: up to three that need no deity, one that does, best swap first


@dataclass(frozen=True)
class RunnerUpFile:
    """One runner-up file as the index lists it: a role's, with every race at every tier of the run (``tiers``, ascending)."""

    role: str
    tiers: tuple[int, ...]
    name: str  # "balanced.json"
    size: int
    sha256: str


@dataclass(frozen=True)
class RunnerUps:
    """Runner-ups for the default assumptions (the default evidence level, own buffs, the role's best setup)."""

    items: tuple[Item, ...]  # every item any runner-up names, once each
    views: tuple[RunnerUpView, ...]
    files: tuple[RunnerUpFile, ...]
    _index: dict[tuple[str, str, int], RunnerUpView] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_index", {(v.race, v.role, v.tier): v for v in self.views})

    def view(self, race: str, role: str, tier: int) -> RunnerUpView | None:
        return self._index.get((race, role, tier))

    def roles(self) -> tuple[str, ...]:
        """The roles that have a file (the file of a role holds every tier), in role order."""
        return tuple(f.role for f in self.files)

    def pairs(self) -> tuple[tuple[str, int], ...]:
        """The (role, tier) pairs that have views, in role order and then tier order."""
        return tuple((f.role, tier) for f in self.files for tier in f.tiers)


@dataclass(frozen=True)
class Sealed:
    """The view one set of seals was made for: the weapon setup, the evidence level and the buffs (the race is the
    robust file's own). The seals describe the kit of that view and of no other."""

    setup: str
    evidence: str
    buffs: str


@dataclass(frozen=True)
class RobustView:
    role: str
    tier: int
    sealed: Sealed
    labels: tuple[str, ...]  # 22 places: "robust" or the reason a pick depends on an assumption


@dataclass(frozen=True)
class Robust:
    """Which picks hold under every perturbation, for the default race: 22 labels per (role, tier), each set made for the
    view it names (:class:`Sealed`)."""

    race: str
    views: tuple[RobustView, ...]
    _index: dict[tuple[str, int], RobustView] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_index", {(v.role, v.tier): v for v in self.views})

    def view(self, role: str, tier: int) -> tuple[str, ...] | None:
        """The 22 labels ("robust" or the reason a pick depends on an assumption), or None if not computed."""
        found = self._index.get((role, tier))
        return found.labels if found is not None else None

    def sealed(self, role: str, tier: int) -> Sealed | None:
        """The view the seals of this role and tier were made for, or None if none were made."""
        found = self._index.get((role, tier))
        return found.sealed if found is not None else None

    def labels_for(self, race: str, role: str, tier: int, setup: str, evidence: str, buffs: str) -> tuple[str, ...] | None:
        """The labels, but only for the view they were made for: the same race, role, tier, weapon setup, evidence level and
        buffs. For any other view the answer is None, because the seals describe another kit."""
        found = self._index.get((role, tier))
        if found is None or race != self.race or found.sealed != Sealed(setup, evidence, buffs):
            return None
        return found.labels


@dataclass(frozen=True)
class WhyTerm:
    """What one stat of an item is worth in the default kit: ``loss``, the value the kit loses when that stat alone is taken from the item (0 past a cap, below 0 for a
    negative stat), and ``reason``, why a loss of 0 is 0 (one of :data:`WHY_REASONS`) or None."""

    stat: str
    loss: float
    reason: str | None


@dataclass(frozen=True)
class WhyPlace:
    key: str  # the item the default kit wears in this place
    terms: tuple[WhyTerm, ...]  # largest loss first


@dataclass(frozen=True)
class Why:
    """The why of the default kit, ``places`` the 22 places of the kit (None for an empty place)."""

    places: tuple[WhyPlace | None, ...]


@dataclass(frozen=True)
class Defaults:
    """The default answer: the best race the trio can start as in the default view, the next one and the gap between them.

    The view is ``role``, ``tier``, ``evidence`` (``strict``, or ``wiki`` while no item is strict: ``strict_empty``) and
    ``buffs``; ``setup`` is the best weapon setup of the race in it and ``value`` its F. ``flips`` are the notes of the open
    rules that would put another race on top, ``robustness`` says whether the seals were made (``done`` or ``skipped: why``)."""

    race: str
    runner_up: str
    margin: float
    flips: tuple[str, ...]  # what could change the answer, as short notes
    role: str
    tier: int
    evidence: str
    buffs: str
    setup: str
    value: float
    strict_empty: bool
    robustness: str
    why: Why | None = None  # what each stat of the default kit is worth (precompute/kitwhy.py); None for results made before it, whose rows then say no why


@dataclass(frozen=True)
class BrowserFile:
    """A file that the optimizer's worker reads, as the precompute wrote it: ``raw`` is its bytes (the build publishes exactly those) and
    ``document`` what they say, which this module has checked."""

    name: str  # "engine-l50.json", "items.json"
    raw: bytes = field(repr=False)
    document: dict[str, Any] = field(repr=False, compare=False)


@dataclass(frozen=True)
class TrioResults:
    meta: Meta
    shards: dict[tuple[str, str], Shard]
    runnerups: RunnerUps
    robust: Robust
    defaults: Defaults
    bundle: BrowserFile

    @property
    def tiers(self) -> tuple[int, ...]:
        """The tiers of the run, its scope: the one list that the four shards and the runner-up file of each role all hold.

        The reader refuses a folder whose files list other tiers (:func:`load_trio`). An object put together by hand is held to it here, so that whatever
        asks for the tiers of a trio (the check of an indexable build, say) gets one list or a :class:`ResultsError`, and never the first shard's."""
        if not self.shards:
            raise ResultsError(f"{self.meta.slug}: has no shards, so it has no tiers")
        held = [(f"{evidence}-{buffs}.json", shard.tiers) for (evidence, buffs), shard in self.shards.items()]
        held += [(f"runnerups/{file.name}", file.tiers) for file in self.runnerups.files]
        first_name, first = held[0]
        for name, tiers in held[1:]:
            if tiers != first:
                raise ResultsError(
                    f"{self.meta.slug}/{name}: the tiers are {_plus(tiers) or 'none'}, but {first_name} has {_plus(first) or 'none'}: "
                    "the files of a trio must all list the same tiers"
                )
        return first


# ---- finding and reading files --------------------------------------------------------------------------------------------


def list_trios(results_dir: str | Path) -> list[str]:
    """The folders of ``results_dir`` that hold shards, sorted. A missing folder has none."""
    root = Path(results_dir)
    if not root.is_dir():
        return []
    return sorted(
        child.name
        for child in root.iterdir()
        if child.is_dir() and any((child / f"{name}.json").is_file() for name in SHARD_NAMES)
    )


def parse_slug(slug: str) -> tuple[str, str, str]:
    """``"pal-mnk-ber"`` -> ``("PAL", "MNK", "BER")``; the codes must be three different classes in class-id order."""
    parts = slug.split("-")
    codes = tuple(part.upper() for part in parts)
    if len(codes) != 3 or any(code not in CLASS_CODES for code in codes) or slug != slug.lower():
        raise ResultsError(f"{slug}: not the folder name of a trio (three class codes joined by '-', such as pal-mnk-ber)")
    order = [CLASS_CODES.index(code) for code in codes]
    if order != sorted(set(order)):
        raise ResultsError(f"{slug}: the classes must be three different codes in class-id order (pal-mnk-ber, not ber-pal-mnk)")
    return codes  # type: ignore[return-value]


class _File:
    """One file being read, so that every complaint names it."""

    def __init__(self, slug: str, name: str, document: Any, raw: bytes = b"") -> None:
        self.label = f"{slug}/{name}.json" if slug else f"{name}.json"
        self.name = name
        self.document = document
        self.raw = raw

    def fail(self, where: str, problem: str) -> NoReturn:
        raise ResultsError(f"{self.label}: {where + ': ' if where else ''}{problem}")

    # typed accessors; each returns the value or fails naming `where`

    def mapping(self, value: Any, where: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            self.fail(where, "must be an object")
        return value

    def sequence(self, value: Any, where: str) -> list[Any]:
        if not isinstance(value, list):
            self.fail(where, "must be a list")
        return value

    def field(self, obj: Mapping[str, Any], key: str, where: str) -> Any:
        if key not in obj:
            self.fail(f"{where}.{key}" if where else key, "is missing")
        return obj[key]

    def text(self, value: Any, where: str, *, empty: bool = False, limit: int | None = None) -> str:
        if not isinstance(value, str):
            self.fail(where, "must be text")
        if _CONTROL.search(value):
            self.fail(where, "has a control character")
        if not value and not empty:
            self.fail(where, "must not be empty")
        most = MAX_TEXT if limit is None else limit
        if len(value) > most:
            self.fail(where, f"is longer than {most} characters")
        return value

    def whole(self, value: Any, where: str, low: int, high: int | None = None) -> int:
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int) or value < low or (high is not None and value > high):
            span = f"from {low} to {high}" if high is not None else f"at least {low}"
            self.fail(where, f"must be a whole number {span}")
        return value

    def number(self, value: Any, where: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            self.fail(where, "must be a finite number")
        return round(float(value), 3)

    def flag(self, value: Any, where: str) -> bool:
        if not isinstance(value, bool):
            self.fail(where, "must be true or false")
        return value

    def choice(self, value: Any, where: str, allowed: Sequence[Any]) -> Any:
        if value not in allowed or isinstance(value, bool):
            self.fail(where, f"must be one of {', '.join(map(str, allowed))}")
        return value

    def date(self, value: Any, where: str) -> str:
        if not isinstance(value, str) or not _DATE.match(value):
            self.fail(where, "must be a calendar date, YYYY-MM-DD")
        try:
            datetime.date.fromisoformat(value)
        except ValueError:
            self.fail(where, "must be a calendar date, YYYY-MM-DD")
        return value


def _read(directory: Path, name: str, *, expect: tuple[int, str] | None = None, folder: bool = True) -> _File:
    """Read ``<directory>/<name>.json`` strictly. ``expect`` is the (size, sha256) an index promises for it. ``folder`` False is a file of
    the folder of results itself, which complaints name without a folder (``items.json``)."""
    slug = directory.name if folder else ""
    path = directory / f"{name}.json"
    label = f"{slug}/{name}.json" if slug else f"{name}.json"
    if not path.is_file():
        raise ResultsError(f"{label}: file is missing")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ResultsError(f"{label}: cannot be read ({type(error).__name__})") from None
    if expect is not None:
        size, digest = expect
        if len(raw) != size:
            raise ResultsError(f"{label}: is {len(raw)} bytes, but the index says {size}")
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ResultsError(f"{label}: its sha256 differs from the index")
    try:
        document = loads_strict(raw.decode("utf-8"), path.name)
    except UnicodeDecodeError:
        raise ResultsError(f"{label}: not valid UTF-8") from None
    except JsonFileError as error:
        message = str(error).removeprefix(f"{path.name}: ").replace("\n", " ")
        raise ResultsError(f"{label}: {message}") from None
    return _File(slug, name, document, raw)


def _header(file: _File, slug: str, *, evidence: str | None = None, buffs: str | None = None, why: str = "") -> dict[str, Any]:
    """The object a file is, with its version and trio checked, and the evidence level and buff set it must name (a shard's own
    name for them, or the default answer's for a runner-up file: ``why`` says whose)."""
    doc = file.mapping(file.document, "")
    if file.field(doc, "version", "") != FORMAT_VERSION or isinstance(doc["version"], bool):
        file.fail("version", f"must be {FORMAT_VERSION}")
    if file.field(doc, "trio", "") != slug:
        file.fail("trio", f"must be {slug!r}, the name of the folder")
    if evidence is not None and doc.get("evidence") != evidence:
        file.fail("evidence", f"must be {evidence!r}{why}")
    if buffs is not None and doc.get("buffs") != buffs:
        file.fail("buffs", f"must be {buffs!r}{why}")
    return doc


def _release(file: _File, doc: Mapping[str, Any]) -> tuple[str, str, str]:
    """``(tag, date, game patch)``: the data release is the text ``data-YYYY-MM-DD`` and the date is the one inside it."""
    tag = file.text(file.field(doc, "data_release", ""), "data_release")
    match = _RELEASE.match(tag)
    if match is None:
        file.fail("data_release", "must look like data-2026-10-14, the data release as a date")
    date = file.date(match.group(1), "data_release")
    patch = file.date(file.field(doc, "game_patch", ""), "game_patch")
    return tag, date, patch


def _same_run(file: _File, doc: Mapping[str, Any], release: tuple[str, str, str], rules_version: str) -> None:
    """A file of the folder that is not a shard comes from the same run as the shards."""
    tag, _, patch = _release(file, doc)
    for what, got, want in (
        ("data_release", tag, release[0]),
        ("game_patch", patch, release[2]),
        ("rules_version", file.date(file.field(doc, "rules_version", ""), "rules_version"), rules_version),
    ):
        if got != want:
            file.fail(what, f"is {got!r}, but the shards say {want!r}: the files are not from one run")


def _item(file: _File, raw: Any, where: str) -> Item:
    row = file.sequence(raw, where)
    if len(row) != len(ITEM_KEYS):
        file.fail(where, f"must be a row of {len(ITEM_KEYS)} values: {', '.join(ITEM_KEYS)}")
    obj = dict(zip(ITEM_KEYS, row))
    key = file.text(obj["key"], f"{where}.key")
    if not _KEY.match(key):
        file.fail(f"{where}.key", "must look like w123 (a wiki page id)")
    slots = file.sequence(obj["slots"], f"{where}.slots")
    if not slots or any(slot not in ITEM_SLOTS for slot in slots):
        file.fail(f"{where}.slots", f"must be a list of slots from {' '.join(sorted(ITEM_SLOTS))}")
    raw_deity = obj["deity"]
    deity: tuple[str, ...] | None = None
    if raw_deity is not None:
        if not isinstance(raw_deity, list) or not raw_deity:
            file.fail(f"{where}.deity", "must be null or a list of deity names")
        deity = tuple(file.text(name, f"{where}.deity[{n}]") for n, name in enumerate(raw_deity))
    rule = file.choice(obj["tier_rule"], f"{where}.tier_rule", TIER_RULES)
    arrival: int | None = None
    if rule == "spell":  # a summoned item arrives at its spell rank: there is no tier to count copies from
        if obj["arrival"] is not None:
            file.fail(f"{where}.arrival", "must be null for a summoned item")
    else:
        arrival = file.whole(obj["arrival"], f"{where}.arrival", 0, MAX_TIER)
    return Item(
        key=key,
        name=file.text(obj["name"], f"{where}.name"),
        slots=tuple(slots),
        tier_rule=rule,
        arrival=arrival,
        source=file.text(obj["source"], f"{where}.source", empty=True),
        evidence=file.choice(obj["evidence"], f"{where}.evidence", EVIDENCE),
        deity=deity,
    )


def _items(file: _File, doc: Mapping[str, Any], where: str = "items") -> tuple[Item, ...]:
    """The item table: rows of :data:`ITEM_KEYS`, named by the file's own ``items_keys``."""
    if tuple(file.sequence(file.field(doc, "items_keys", ""), "items_keys")) != ITEM_KEYS:
        file.fail("items_keys", f"must be {list(ITEM_KEYS)}")
    items = tuple(_item(file, entry, f"{where}[{n}]") for n, entry in enumerate(file.sequence(file.field(doc, where, ""), where)))
    keys = [item.key for item in items]
    if len(set(keys)) != len(keys):
        file.fail(where, "lists an item key twice")
    return items


def _kit(file: _File, raw: Any, where: str, items: tuple[Item, ...]) -> tuple[int, ...]:
    entries = file.sequence(raw, where)
    if len(entries) != KIT_SIZE:
        file.fail(where, f"must have {KIT_SIZE} entries, one for each place of a kit")
    kit = []
    for place, entry in enumerate(entries):
        index = file.whole(entry, f"{where}[{place}]", -1)
        if index >= len(items):
            file.fail(f"{where}[{place}]", f"is out of range: there are {len(items)} items")
        group = SLOT_INSTANCES[place]
        if index >= 0 and group != "ANY" and group not in items[index].slots:
            file.fail(
                f"{where}[{place}]",
                f"item {items[index].key} (slots {' '.join(items[index].slots)}) cannot be worn in {group}",
            )
        kit.append(index)
    return tuple(kit)


def _buff_lists(file: _File, raw: Any) -> list[tuple[int, ...]]:
    """The deduplicated lists of optional buff ids (spell ids) the scenarios point into."""
    if not isinstance(raw, list):
        file.fail("buff_sets", "must be a list of lists of optional buff ids")
    lists = []
    for n, entry in enumerate(raw):
        ids = file.sequence(entry, f"buff_sets[{n}]")
        numbers = tuple(file.whole(buff_id, f"buff_sets[{n}][{k}]", 0) for k, buff_id in enumerate(ids))
        if len(set(numbers)) != len(numbers):
            file.fail(f"buff_sets[{n}]", "lists a buff twice")
        lists.append(numbers)
    return lists


def _totals(file: _File, doc: Mapping[str, Any]) -> list[Totals]:
    """The distinct totals: rows of whole numbers in the order of the file's own ``totals_keys`` (:data:`TOTALS_KEYS`)."""
    if tuple(file.sequence(file.field(doc, "totals_keys", ""), "totals_keys")) != TOTALS_KEYS:
        file.fail("totals_keys", f"must be {list(TOTALS_KEYS)}")
    out = []
    for n, raw in enumerate(file.sequence(file.field(doc, "totals", ""), "totals")):
        where = f"totals[{n}]"
        row = file.sequence(raw, where)
        if len(row) != len(TOTALS_KEYS):
            file.fail(where, f"must be a row of {len(TOTALS_KEYS)} whole numbers: {', '.join(TOTALS_KEYS)}")
        value = {
            key: file.whole(cell, f"{where}.{key}", 0 if key == "haste" else -MAX_TOTAL, MAX_HASTE if key == "haste" else MAX_TOTAL)
            for key, cell in zip(TOTALS_KEYS, row)
        }  # fmt: skip
        out.append(
            Totals(
                ac=value["ac"], hp=value["hp"], mana=value["mana"], end=value["end"], haste=value["haste"], atk=value["atk"],
                resists=tuple(value[school.lower()] for school in SCHOOLS),  # type: ignore[arg-type]
                regen=(value["hpreg"], value["manareg"], value["endreg"]),
            )
        )  # fmt: skip
    return out


def _shard(directory: Path, name: str, slug: str) -> tuple[Shard, dict[str, Any]]:
    evidence, buffs = name.split("-")
    file = _read(directory, name)
    doc = _header(file, slug, evidence=evidence, buffs=buffs, why=", as the file name says")
    level = file.whole(file.field(doc, "level", ""), "level", 1, 99)
    release = _release(file, doc)
    rules_version = file.date(file.field(doc, "rules_version", ""), "rules_version")
    solver = dict(file.mapping(file.field(doc, "solver", ""), "solver"))
    build_options = dict(file.mapping(file.field(doc, "build_options", ""), "build_options"))
    partial = file.flag(file.field(doc, "partial", ""), "partial")
    items = _items(file, doc)
    kits = [
        _kit(file, raw, f"kits[{n}]", items) for n, raw in enumerate(file.sequence(file.field(doc, "kits", ""), "kits"))
    ]
    buff_lists = _buff_lists(file, file.field(doc, "buff_sets", ""))
    totals = _totals(file, doc)
    scenarios: list[Scenario] = []
    seen: set[tuple[str, str, int, str]] = set()
    for n, raw in enumerate(file.sequence(file.field(doc, "scenarios", ""), "scenarios")):
        where = f"scenarios[{n}]"
        row = file.sequence(raw, where)
        if len(row) != 10:
            file.fail(where, "must be [race, role, tier, setup, kit, F, gain, totals, buffs, haste_assumed]")
        race = file.choice(row[0], f"{where}.race", RACE_CODES)
        role = file.choice(row[1], f"{where}.role", ROLES)
        tier = file.whole(row[2], f"{where}.tier", 0, MAX_TIER)
        setup = file.choice(row[3], f"{where}.setup", SETUPS)
        kit_index = file.whole(row[4], f"{where}.kit", 0)
        if kit_index >= len(kits):
            file.fail(f"{where}.kit", f"{kit_index} is not a kit: there are {len(kits)}")
        value = file.number(row[5], f"{where}.value")
        gain = file.number(row[6], f"{where}.gain")
        totals_index = file.whole(row[7], f"{where}.totals", 0)
        if totals_index >= len(totals):
            file.fail(f"{where}.totals", f"{totals_index} is not in totals: there are {len(totals)}")
        buffs_index = file.whole(row[8], f"{where}.buffs", 0)
        if buffs_index >= len(buff_lists):
            file.fail(f"{where}.buffs", f"{buffs_index} is not in buff_sets: there are {len(buff_lists)}")
        haste_assumed = file.whole(row[9], f"{where}.haste_assumed", 0, MAX_HASTE)
        key = (race, role, tier, setup)
        if key in seen:
            file.fail(where, f"{race} {role} +{tier} {setup} appears twice")
        seen.add(key)
        kit = tuple(items[i] if i >= 0 else None for i in kits[kit_index])
        scenarios.append(
            Scenario(race, role, tier, setup, kit, value, gain, totals[totals_index], buff_lists[buffs_index], haste_assumed)
        )
    shard = Shard(evidence, buffs, items, tuple(scenarios), solver, build_options)
    _check_grid(file, shard)
    recorded = [file.whole(tier, f"tiers[{n}]", 0, MAX_TIER) for n, tier in enumerate(file.sequence(file.field(doc, "tiers", ""), "tiers"))]
    if recorded != list(shard.tiers):  # the scope the run was given is what its rows must be of: a shard that lost the rows of a tier is no shard of it
        file.fail("tiers", f"records {_plus(recorded) or 'none'}, but its rows are of {_plus(shard.tiers)}")
    return shard, {"level": level, "release": release, "rules_version": rules_version, "partial": partial}


def _plus(tiers: Iterable[int]) -> str:
    """Tiers as a reader says them: ``+0, +4, +10``."""
    return ", ".join(f"+{tier}" for tier in tiers)


def _grid(shard: Shard) -> tuple[Any, ...]:
    """What every shard must hold alike: the races, the roles and the tiers. The setups are each shard's own."""
    return (frozenset(shard.races), shard.roles, shard.tiers)


def _grid_difference(shard: Shard, first: Shard, first_name: str) -> str:
    """Which of the races, the roles and the tiers ``shard`` holds otherwise than ``first`` (the shard it is read against), with both lists."""
    parts = []
    if shard.tiers != first.tiers:
        parts.append(f"its tiers are {_plus(shard.tiers) or 'none'}, and {first_name}.json's are {_plus(first.tiers) or 'none'}")
    if frozenset(shard.races) != frozenset(first.races):
        parts.append(f"its races are {' '.join(shard.races) or 'none'}, and {first_name}.json's are {' '.join(first.races) or 'none'}")
    if shard.roles != first.roles:
        parts.append(f"its roles are {', '.join(shard.roles) or 'none'}, and {first_name}.json's are {', '.join(first.roles) or 'none'}")
    return "; ".join(parts)



def _check_grid(file: _File, shard: Shard) -> None:
    """Every race x role x tier x (the role's setups) has a scenario: no combination the page offers is without an answer."""
    if not shard.scenarios:
        file.fail("scenarios", "is empty")
    for race in shard.races:
        for role in shard.roles:
            for tier in shard.tiers:
                for setup in shard.setups_for(role):
                    if shard.scenario(race, role, tier, setup) is None:
                        file.fail("", f"the grid is incomplete: missing {race} {role} +{tier} {setup}")


def _swaps(file: _File, raw: Any, where: str, items: tuple[Item, ...]) -> tuple[Swap, ...]:
    entries = file.sequence(raw, where)
    swaps = []
    for k, row in enumerate(entries):
        if not isinstance(row, list) or len(row) != 2:
            file.fail(f"{where}[{k}]", "must be [item, delta]")
        index = file.whole(row[0], f"{where}[{k}].item", 0)
        if index >= len(items):
            file.fail(f"{where}[{k}].item", f"{index} is not in items: there are {len(items)}")
        delta = file.number(row[1], f"{where}[{k}].delta")
        if delta > BEAT_TOLERANCE and items[index].deity is None:
            file.fail(f"{where}[{k}].delta", "must be zero or negative: only a swap of an item that needs a deity can beat the pick")
        swaps.append(Swap(items[index], delta))
    free = sum(1 for swap in swaps if swap.item.deity is None)
    if free > MAX_FREE_SWAPS:
        file.fail(where, f"has more than three runner-ups that need no deity ({free})")
    if len(swaps) - free > MAX_LOCKED_SWAPS:
        file.fail(where, f"has more than one runner-up that needs a deity ({len(swaps) - free})")
    return tuple(swaps)


def _tier_list(file: _File, raw: Any, where: str, scope: tuple[int, ...], *, complete: bool = True) -> tuple[int, ...]:
    """The tiers a runner-up file (or the index's entry for it) lists, which must be the scope of the run, ``scope`` (the tiers of the shards):
    a tier outside it, a tier of it that is missing and a tier listed twice are each refused, and so are tiers out of order. With ``complete`` off
    (the seals of ``robust.json``, which are made for some of the tiers) a tier of the scope may be missing, and the rest is asked as before."""
    tiers = [file.whole(tier, f"{where}[{n}]", 0, MAX_TIER) for n, tier in enumerate(file.sequence(raw, where))]
    for n, tier in enumerate(tiers):
        if tier not in scope:
            file.fail(f"{where}[{n}]", f"+{tier} is not a tier of the run ({_plus(scope)})")
    for tier in dict.fromkeys(tiers):
        if tiers.count(tier) > 1:
            file.fail(where, f"lists +{tier} twice")
    for tier in scope if complete else ():
        if tier not in tiers:
            file.fail(where, f"has no +{tier}, a tier of the run ({_plus(scope)})")
    if tiers != sorted(tiers):
        file.fail(where, "must be in ascending order")
    return tuple(tiers)


def _runnerup_file(
    file: _File, slug: str, role: str, grid: Shard, evidence: str, run: tuple[tuple[str, str, str], str]
) -> tuple[tuple[int, ...], tuple[Item, ...], list[RunnerUpView]]:
    doc = _header(file, slug, evidence=evidence, buffs="own", why=": the runner-ups are for the default answer's evidence level and own buffs")
    _same_run(file, doc, *run)
    if file.field(doc, "role", "") != role:
        file.fail("role", f"must be {role!r}, as the file name says")
    tiers = _tier_list(file, file.field(doc, "tiers", ""), "tiers", grid.tiers)
    items = _items(file, doc)
    views = []
    seen: set[tuple[int, str]] = set()
    for n, raw in enumerate(file.sequence(file.field(doc, "views", ""), "views")):
        where = f"views[{n}]"
        row = file.sequence(raw, where)
        if len(row) != 4:
            file.fail(where, "must be [tier, race, setup, places]")
        tier = file.whole(row[0], f"{where}.tier", 0, MAX_TIER)
        if tier not in tiers:
            file.fail(f"{where}.tier", f"+{tier} is not one of the tiers of the file ({_plus(tiers)})")
        race = file.choice(row[1], f"{where}.race", grid.races)
        setup = file.choice(row[2], f"{where}.setup", grid.setups_for(role))
        if (tier, race) in seen:
            file.fail(where, f"lists {race} at +{tier} twice")
        seen.add((tier, race))
        places_raw = file.sequence(row[3], f"{where}.places")
        if len(places_raw) != KIT_SIZE:
            file.fail(f"{where}.places", f"must have {KIT_SIZE} entries, one for each place of a kit")
        slots = tuple(_swaps(file, swaps_raw, f"{where}.places[{place}]", items) for place, swaps_raw in enumerate(places_raw))
        views.append(RunnerUpView(race, role, tier, setup, slots))
    for tier in tiers:
        for race in grid.races:
            if (tier, race) not in seen:
                file.fail("views", f"has no view of {race} at +{tier}")
    return tiers, items, views


def _runnerups(directory: Path, slug: str, grid: Shard, evidence: str, run: tuple[tuple[str, str, str], str]) -> RunnerUps:
    """The runner-ups; ``grid`` is the shard of the default answer's evidence level with own buffs, which they were made from. The tiers of the
    run, the scope, are that shard's (the four shards have the same)."""
    index = _read(directory, "runnerups/index")
    doc = _header(index, slug, evidence=evidence, buffs="own", why=": the runner-ups are for the default answer's evidence level and own buffs")
    _same_run(index, doc, *run)
    listed = index.sequence(index.field(doc, "files", ""), "files")
    if not listed:
        index.fail("files", "is empty: there are no runner-up files")
    folder = directory / "runnerups"
    names = []
    entries = []
    for n, raw in enumerate(listed):
        where = f"files[{n}]"
        entry = index.mapping(raw, where)
        name = index.field(entry, "file", where)
        match = _RUNNERUP_NAME.fullmatch(name) if isinstance(name, str) else None
        if match is None or match.group(1) not in grid.roles:
            if isinstance(name, str) and _OLD_RUNNERUP_NAME.fullmatch(name):
                index.fail(f"{where}.file", f"{name} is a file of the earlier layout, one for each role and tier: run the precompute again")
            index.fail(f"{where}.file", "is not a runner-up file name: <role>.json for a role of the grid")
        if name in names:
            index.fail(where, f"lists {name} twice")
        names.append(name)
        entries.append((name, match.group(1), entry, where))
    for role in grid.roles:
        if not any(entry_role == role for _, entry_role, _, _ in entries):
            index.fail("files", f"has no file for the {role} role")
    for present in sorted(p.name for p in folder.glob("*.json") if p.name != "index.json"):
        if present not in names:
            index.fail("files", f"{present} is in the folder but not in the index")
    files: list[RunnerUpFile] = []
    items_by_key: dict[str, Item] = {}
    views: list[RunnerUpView] = []
    for name, role, entry, where in entries:
        if index.field(entry, "role", where) != role:
            index.fail(f"{where}.role", f"must be {role!r}, as the file name says")
        tiers = _tier_list(index, index.field(entry, "tiers", where), f"{where}.tiers", grid.tiers)
        size = index.whole(index.field(entry, "bytes", where), f"{where}.bytes", 0)
        digest = index.field(entry, "sha256", where)
        if not isinstance(digest, str) or not _SHA256.match(digest):
            index.fail(f"{where}.sha256", "must be 64 lower-case hexadecimal digits")
        file = _read(directory, f"runnerups/{name.removesuffix('.json')}", expect=(size, digest))
        _, items, file_views = _runnerup_file(file, slug, role, grid, evidence, run)
        for item in items:
            if items_by_key.setdefault(item.key, item) != item:
                file.fail("items", f"item {item.key} is not the same as in another runner-up file")
        views.extend(file_views)
        files.append(RunnerUpFile(role, tiers, name, size, digest))
    files.sort(key=lambda f: ROLES.index(f.role))
    return RunnerUps(tuple(items_by_key[key] for key in sorted(items_by_key)), tuple(views), tuple(files))


def _robust(
    directory: Path, slug: str, shards: Mapping[tuple[str, str], Shard], defaults: Defaults, run: tuple[tuple[str, str, str], str]
) -> Robust:
    """The seals. The precompute makes them for the default race at the default evidence level with the default buffs and, for
    each role and tier, the role's best weapon setup there; ``sealed`` says so for every view, so that the page shows them for
    that view alone.

    The sealed view is taken from the rows here (the best setup is the one with the highest value, the earlier on a tie) and not
    from the file: robust.json does not record it yet. When the precompute writes the view it sealed, this is the one place to
    read it instead. The two can differ only if two setups of a role are worth the same to the two decimals the rows keep."""
    grid = shards[(EVIDENCE[0], BUFFS[0])]
    level = shards[(defaults.evidence, defaults.buffs)]
    file = _read(directory, "robust")
    doc = _header(file, slug)
    _same_run(file, doc, *run)
    race = file.choice(file.field(doc, "race", ""), "race", grid.races)
    tiers = _tier_list(file, file.field(doc, "tiers", ""), "tiers", grid.tiers, complete=False)  # some of the tiers of the run: those of the seals
    views = []
    for role, by_tier_raw in file.mapping(file.field(doc, "roles", ""), "roles").items():
        file.choice(role, f"roles.{role}", grid.roles)
        by_tier = file.mapping(by_tier_raw, f"roles.{role}")
        for tier_text, labels_raw in by_tier.items():
            where = f"roles.{role}.{tier_text}"
            tier = int(tier_text) if tier_text.isdigit() else -1
            if tier not in grid.tiers or tier not in tiers:
                file.fail(where, f"is not a tier of the grid that this file lists in tiers ({_plus(tiers) or 'none'})")
            labels_map = file.mapping(labels_raw, where)
            extra = sorted(set(labels_map) - set(PLACES))
            if extra:
                file.fail(f"{where}.{extra[0]}", "is not a place of a kit")
            labels = tuple(file.text(file.field(labels_map, place, where), f"{where}.{place} label") for place in PLACES)
            sealed = Sealed(level.best_setup(race, role, tier), defaults.evidence, defaults.buffs)
            views.append(RobustView(role, tier, sealed, labels))
    for tier in tiers:
        if not any(view.tier == tier for view in views):
            file.fail("tiers", f"lists +{tier}, but no role has labels at +{tier}")
    views.sort(key=lambda view: (ROLES.index(view.role), view.tier))
    return Robust(race, tuple(views))


def _defaults(directory: Path, slug: str, shards: Mapping[tuple[str, str], Shard], run: tuple[tuple[str, str, str], str]) -> Defaults:
    file = _read(directory, "defaults")
    doc = _header(file, slug)
    _same_run(file, doc, *run)
    grid = shards[(EVIDENCE[0], BUFFS[0])]  # the races, roles and tiers are those of every shard
    view = file.mapping(file.field(doc, "view", ""), "view")
    role = file.choice(file.field(view, "role", "view"), "view.role", grid.roles)
    tier = file.choice(file.field(view, "tier", "view"), "view.tier", grid.tiers)
    evidence = file.choice(file.field(view, "evidence", "view"), "view.evidence", EVIDENCE)
    buffs = file.choice(file.field(view, "buffs", "view"), "view.buffs", BUFFS)
    level = shards[(evidence, buffs)]  # the answer is a kit of this shard, so its setup is one this shard has for the role
    strict_empty = file.flag(file.field(doc, "strict_pool_empty", ""), "strict_pool_empty")
    race = file.choice(file.field(doc, "race", ""), "race", grid.races)
    runner_up = file.field(doc, "runner_up_race", "")
    if runner_up is None:
        file.fail("runner_up_race", "is null: the page names a runner-up, so the run needs two races that can be created")
    runner_up = file.choice(runner_up, "runner_up_race", grid.races)
    if runner_up == race:
        file.fail("runner_up_race", "must be a different race from race")
    margin = file.number(file.field(doc, "margin", ""), "margin")
    if margin < 0:
        file.fail("margin", "must not be negative")
    setup = file.choice(file.field(doc, "setup", ""), "setup", level.setups_for(role))
    value = file.number(file.field(doc, "F", ""), "F")
    flips_raw = file.sequence(file.field(doc, "flip_notes", ""), "flip_notes")
    flips = tuple(file.text(note, f"flip_notes[{n}]") for n, note in enumerate(flips_raw))
    robustness = file.text(file.field(doc, "robustness", ""), "robustness")
    why = _why(file, doc["why"]) if "why" in doc else None
    return Defaults(race, runner_up, margin, flips, role, tier, evidence, buffs, setup, value, strict_empty, robustness, why)


def _why(file: _File, raw: Any) -> Why:
    """``why`` of ``defaults.json``: 22 places, each null or ``{"key", "loss": [[term, loss, reason]...]}`` (the loss of a stat is a finite number, the largest first)."""
    body = file.mapping(raw, "why")
    places = file.sequence(file.field(body, "places", "why"), "why.places")
    if len(places) != KIT_SIZE:
        file.fail("why.places", f"must have {KIT_SIZE} places, not {len(places)}")
    out: list[WhyPlace | None] = []
    for n, entry in enumerate(places):
        where = f"why.places[{n}]"
        if entry is None:
            out.append(None)
            continue
        place = file.mapping(entry, where)
        key = file.text(file.field(place, "key", where), f"{where}.key", limit=MAX_TEXT)
        if _KEY.fullmatch(key) is None:
            file.fail(f"{where}.key", "must be an item key")
        terms: list[WhyTerm] = []
        for m, raw_term in enumerate(file.sequence(file.field(place, "loss", where), f"{where}.loss")):
            at = f"{where}.loss[{m}]"
            row = file.sequence(raw_term, at)
            if len(row) != 3:
                file.fail(at, "must be [term, loss, reason]")
            stat = file.choice(row[0], f"{at}[0]", WHY_TERMS)
            loss = file.number(row[1], f"{at}[1]")
            reason = None if row[2] is None else file.choice(row[2], f"{at}[2]", WHY_REASONS)
            if reason is not None and loss != 0:
                file.fail(at, "gives a reason for a loss that is not 0")
            if terms and loss > terms[-1].loss:
                file.fail(at, "is out of order: the largest loss comes first")
            if any(term.stat == stat for term in terms):
                file.fail(at, f"lists {stat} twice")
            terms.append(WhyTerm(stat, loss, reason))
        out.append(WhyPlace(key, tuple(terms)))
    return Why(tuple(out))


# ---- the engine's files: the bundle of a trio and the item table of the folder of results ----------------------------------------


def engine_name(level: int) -> str:
    """The file name of the bundle at a character level: ``engine-l50.json``."""
    return f"engine-l{int(level)}.json"


def _browser() -> Any:
    """The exporter's module, whose reader the bundle is checked with (imported when first needed: it reads the model and the solver)."""
    from trioforge.export import browser

    return browser


_RATIONAL_LIKE = re.compile(r"[0-9+./-]+(?![\s\S])")
RECORD_FIELDS = (
    "id", "key", "name", "match_name", "aliases", "slots", "classes", "races", "deity", "lore", "stats", "sv", "weight10", "weapon",
    "item_type", "item_type_source", "tier_rule", "evidence", "owned_only", "source",
)  # fmt: skip
LEVELS = ("strict", "wiki", "disputed", "hidden")  # the evidence levels of the catalog
MAX_AMOUNT = 1_000_000_000  # a stat, a resist, a weight or a damage in a record is a whole number within this size
#: the stats and the resists a record may name: the ones the browser's ``atTier`` reads (items.js STAT_KEYS, REGEN_KEYS and HASTE; SV_KEYS)
STAT_NAMES = frozenset({"AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG", "HASTE"})
SV_NAMES = frozenset({"FIRE", "COLD", "MAGIC", "POISON", "DISEASE", "CORRUPTION"})
#: what a record may hold: the same numbers as ``RECORD_LIMITS`` of items.js (a test holds them to each other)
RECORD_LIMITS = {
    "text": MAX_TEXT, "statName": 24, "aliases": 64, "classes": 17, "races": 16, "deity": 16, "itemType": 40, "codes": 40, "codeText": 80,
    "sourceText": 200, "slots": len(ITEM_SLOTS), "records": 200_000,
}  # fmt: skip
MAX_RECORDS = RECORD_LIMITS["records"]
#: what a bundle may hold: the same numbers as ``BUNDLE_LIMITS`` of profile.js (a test holds them to each other)
BUNDLE_LIMITS = {"maxDepth": 16, "maxNodes": 100_000, "maxText": 10_000, "maxRationals": 2_500, "maxDigits": 64}
_FORBIDDEN_KEYS = frozenset({"__proto__", "constructor", "prototype"})  # keys that could poison a lookup of the browser's reader
_SAFE_INTEGER = 2**53 - 1


def _say(value: Any) -> str:
    """A value the file holds, short enough to put in a complaint."""
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _exact(file: _File, root: Any, where: str, counted: list[int]) -> None:
    """Every exact number of a block of the bundle is a reduced ``p/q`` text: no bare number, and a text of digits and signs with a slash
    in it must be one (the exporter's :func:`~trioforge.export.browser.unrat` is the reader), of at most 64 digits a part; ``counted`` is the number
    of them so far in the bundle, which may hold only :data:`BUNDLE_LIMITS` ``maxRationals`` (each costs the browser a reduction)."""
    unrat = _browser().unrat
    stack = [(root, where)]
    while stack:
        node, path = stack.pop()
        if isinstance(node, bool) or node is None:
            continue
        if isinstance(node, (int, float)):
            file.fail(path, "is a bare number, where every exact number is a reduced p/q text")
        if isinstance(node, str):
            if "/" in node and _RATIONAL_LIKE.match(node):
                try:
                    unrat(node)
                except ValueError:
                    file.fail(path, "is not a reduced rational p/q (a zero denominator, not in lowest terms, or a stray sign or point)")
                if any(len(part.lstrip("+-")) > BUNDLE_LIMITS["maxDigits"] for part in node.split("/")):
                    file.fail(path, f"has a part of more than {BUNDLE_LIMITS['maxDigits']} digits")
                counted[0] += 1
                if counted[0] > BUNDLE_LIMITS["maxRationals"]:
                    file.fail(path, f"is one exact number too many: a bundle holds at most {BUNDLE_LIMITS['maxRationals']}")
        elif isinstance(node, list):
            stack.extend((item, f"{path}[{n}]") for n, item in enumerate(node))
        elif isinstance(node, dict):
            stack.extend((item, f"{path}.{key}") for key, item in node.items())


def _shape(file: _File, root: Any) -> None:
    """The limits the browser's reader holds a whole bundle to (profile.js ``readBundle``): the depth of its nesting, the number of its parts, the length
    of a text, a whole number a double holds exactly, and no key that could poison a lookup."""
    stack: list[tuple[Any, int, str]] = [(root, 0, "")]
    nodes = 0
    while stack:
        node, depth, path = stack.pop()
        nodes += 1
        if nodes > BUNDLE_LIMITS["maxNodes"]:
            file.fail("", "is a document that is too large")
        if isinstance(node, str):
            if len(node) > BUNDLE_LIMITS["maxText"]:
                file.fail(path, "is a text that is too long")
        elif isinstance(node, bool) or node is None:
            continue
        elif isinstance(node, int):
            if abs(node) > _SAFE_INTEGER:
                file.fail(path, "is a whole number a double cannot hold exactly")
        elif isinstance(node, float):
            if not math.isfinite(node):
                file.fail(path, "is a number that is not finite")
        elif isinstance(node, (list, dict)):
            if depth >= BUNDLE_LIMITS["maxDepth"]:
                file.fail(path, "is nested too deeply")
            if isinstance(node, list):
                if len(node) > BUNDLE_LIMITS["maxNodes"]:
                    file.fail(path, "is a list that is too long")
                stack.extend((item, depth + 1, f"{path}[{n}]") for n, item in enumerate(node))
            else:
                for key in node:
                    if key in _FORBIDDEN_KEYS:
                        file.fail(path, "has a key that could poison a lookup")
                stack.extend((item, depth + 1, f"{path}.{key}") for key, item in node.items())


def _engine_header(file: _File, doc: Any, fields: Sequence[str], meta: Meta, *, what: str) -> dict[str, Any]:
    """The checks the bundle and the item table share: an object of exactly the exporter's fields (and the fingerprint of the inputs, which the
    precompute adds), its format number, the release and the rules version of the shards, and the fingerprint itself."""
    doc = file.mapping(doc, "")
    version = file.field(doc, "version", "")
    if isinstance(version, bool) or version != ENGINE_VERSION:
        file.fail("version", f"must be {ENGINE_VERSION}")
    for name in fields:
        if name not in doc:
            file.fail(name, "is missing")
    for name in doc:
        if name not in fields and name != "inputs":
            file.fail(name, f"is not a field of {what}")
    for name, want in (("data_release", meta.data_tag), ("rules_version", meta.rules_version)):
        got = doc[name]
        if got != want:
            file.fail(name, f"is {_say(got)}, but {meta.slug} says {_say(want)}: the files are not from one run")
    if "inputs" not in doc:
        file.fail("inputs", "is missing: the file was made before the precompute wrote a fingerprint of its inputs; run the precompute again")
    if not isinstance(doc["inputs"], str) or not _SHA256.fullmatch(doc["inputs"]):
        file.fail("inputs", "must be a SHA-256, 64 lower-case hexadecimal digits")
    return doc


def _bundle(directory: Path, meta: Meta, shards: Mapping[tuple[str, str], Shard]) -> BrowserFile:
    """The bundle of the trio at the level of its shards (see the module docstring)."""
    browser = _browser()
    name = engine_name(meta.level)
    file = _read(directory, name.removesuffix(".json"))
    doc = _engine_header(file, file.document, browser.BUNDLE_FIELDS, meta, what="a bundle")
    _shape(file, doc)
    if doc["trio"] != list(meta.trio):
        file.fail("trio", f"must be {list(meta.trio)}, the trio of the folder")
    if isinstance(doc["level"], bool) or doc["level"] != meta.level:
        file.fail("level", f"must be {meta.level}, the level of the shards")
    if doc["evidence_levels"] != list(EVIDENCE):
        file.fail("evidence_levels", f"must be {list(EVIDENCE)}")
    if list(file.mapping(doc["buffs"], "buffs")) != list(browser.BUFF_SETS):
        file.fail("buffs", f"must be the buff sets {', '.join(browser.BUFF_SETS)}, in this order")
    counted = [0]
    for block in browser.EXACT_BLOCKS:
        _exact(file, doc[block], block, counted)
    # the races, roles and weapon setups of the shards are in it
    rows = file.sequence(doc["races"], "races")
    races = [row["code"] for row in rows if isinstance(row, dict) and isinstance(row.get("code"), str)]
    roles = file.mapping(doc["roles"], "roles")
    for shard in shards.values():
        for race in shard.races:
            if race not in races:
                file.fail("races", f"has no {race}, which the shards have rows for")
        for role in shard.roles:
            if role not in roles:
                file.fail("roles", f"has no {role} role, which the shards have rows for")
            by_level = roles[role].get("setups_by_evidence") if isinstance(roles[role], dict) else None
            listed = by_level.get(shard.evidence) if isinstance(by_level, dict) else None
            if listed is None:
                file.fail(f"roles.{role}.setups_by_evidence", f"has no list for the {shard.evidence} evidence level")
            where = f"roles.{role}.setups_by_evidence.{shard.evidence}"
            listed = file.sequence(listed, where)  # a text and an object can be iterated and a number cannot: only a list is a list of names
            for n, setup in enumerate(listed):
                file.text(setup, f"{where}[{n}]")
            if not set(shard.setups_for(role)) <= set(listed):  # the run itself holds the two lists equal; a reader needs the shards' in the bundle
                file.fail(
                    where,
                    f"is {listed} but the {shard.evidence} shards have {list(shard.setups_for(role))} for it: "
                    "the item pools of the bundle and of the shards differ",
                )
    # the exporter's reader puts profiles together from it: the first and the last race, role and buff set, with and without a level
    for race in {races[0], races[-1]}:
        for role in {next(iter(roles)), list(roles)[-1]}:
            for buffs in {browser.BUFF_SETS[0], browser.BUFF_SETS[-1]}:
                for evidence in (None, *EVIDENCE):
                    try:
                        made = browser.assemble(doc, race, role, buffs, **({} if evidence is None else {"evidence": evidence}))
                    except (ValueError, KeyError, TypeError, AttributeError) as error:
                        file.fail("", f"does not reassemble to the profile of {race} {role} {buffs} ({type(error).__name__})")
                    if made["trio"] != list(meta.trio) or made["level"] != meta.level:
                        file.fail("", f"reassembles to a profile of another trio or level than {meta.slug} at level {meta.level}")
    return BrowserFile(name, file.raw, doc)


def _names(file: _File, record: Mapping[str, Any], where: str, name: str, *, least: int = 0) -> list[Any]:
    """A list of texts of a record that may hold only so many (:data:`RECORD_LIMITS` has the number for ``name``)."""
    most = RECORD_LIMITS[name]
    names = file.sequence(record[name], f"{where}.{name}")
    if len(names) > most or len(names) < least:
        file.fail(f"{where}.{name}", f"must be a list of {'1 to ' if least else 'up to '}{most} names")
    for n, entry in enumerate(names):
        file.text(entry, f"{where}.{name}[{n}]")
    return names


def _source(file: _File, source: Any, where: str) -> None:
    """The source of an item as the exporter writes it (items.js ``checkSource``): lists of one to the most it keeps of the zones it drops in, is sold
    in and is foraged in and of its quests, none twice, texts of at most 200 characters; a count of recipes; and in ``more`` how many places did not fit
    in a list that is full."""
    places = _browser().SOURCE_PLACES
    where = f"{where}.source"
    source = file.mapping(source, where)
    if not source:
        file.fail(where, "has nothing in it")
    for key in source:
        if key not in places and key not in ("crafted", "more"):
            file.fail(where, "has a part that is not allowed")
    for kind, most in places.items():
        if kind not in source:
            continue
        names = file.sequence(source[kind], f"{where}.{kind}")
        if not 1 <= len(names) <= most:
            file.fail(f"{where}.{kind}", f"must be a list of 1 to {most} places")
        for n, entry in enumerate(names):
            file.text(entry, f"{where}.{kind}[{n}]", limit=RECORD_LIMITS["sourceText"])
        if len(set(names)) != len(names):
            file.fail(f"{where}.{kind}", "names a place twice")
    if "crafted" in source:
        file.whole(source["crafted"], f"{where}.crafted", 1, MAX_AMOUNT)
    if "more" in source:
        more = file.mapping(source["more"], f"{where}.more")
        if not more:
            file.fail(f"{where}.more", "has nothing in it")
        for kind, extra in more.items():
            if kind not in places or kind not in source or len(source[kind]) != places[kind]:
                file.fail(f"{where}.more", "counts only the places that did not fit in a full list")
            file.whole(extra, f"{where}.more.{kind}", 1, MAX_AMOUNT)


def _record(file: _File, raw: Any, where: str) -> str:
    """One record of the item table, checked; returns its item key. The record is held to the limits of the browser's reader (:data:`RECORD_LIMITS`)."""
    record = file.mapping(raw, where)
    for name in record:
        if name not in RECORD_FIELDS:
            file.fail(f"{where}.{name}", "is not a field of an item record")
    page = file.field(record, "id", where)
    if page is not None:
        file.whole(page, f"{where}.id", 1)
    key = record.get("key")
    if key is None:
        if page is None:
            file.fail(where, "has neither a key nor a page id")
        key = f"w{page}"
    key = file.text(key, f"{where}.key")
    if not _KEY.match(key):
        file.fail(f"{where}.key", "must look like w123 (a wiki page id with no zero in front)")
    where = f"{where} {key}"  # from here a complaint names the item
    file.text(file.field(record, "name", where), f"{where}.name")
    if "match_name" in record:
        file.text(record["match_name"], f"{where}.match_name")
    for name in ("aliases", "classes", "races"):
        if name in record:
            _names(file, record, where, name)
    if "deity" in record:
        _names(file, record, where, "deity", least=1)
    slots = file.sequence(file.field(record, "slots", where), f"{where}.slots")
    if not slots or len(slots) > RECORD_LIMITS["slots"] or any(slot not in ITEM_SLOTS for slot in slots):
        file.fail(f"{where}.slots", f"must be a list of up to {RECORD_LIMITS['slots']} slots from {' '.join(sorted(ITEM_SLOTS))}")
    if "lore" in record and record["lore"] is not True:
        file.fail(f"{where}.lore", "is there only when it is true")
    for name, known in (("stats", STAT_NAMES), ("sv", SV_NAMES)):
        if name in record:
            for stat, amount in file.mapping(record[name], f"{where}.{name}").items():
                file.text(stat, f"{where}.{name} key", limit=RECORD_LIMITS["statName"])
                if stat not in known:
                    file.fail(f"{where}.{name}", "names a " + ("stat" if name == "stats" else "resist") + " the model does not know")
                file.whole(amount, f"{where}.{name}.{stat}", -MAX_AMOUNT, MAX_AMOUNT)
    weight = file.field(record, "weight10", where)
    if weight is not None:
        file.whole(weight, f"{where}.weight10", 0, MAX_AMOUNT)
    if "weapon" in record:
        weapon = file.mapping(record["weapon"], f"{where}.weapon")
        if list(weapon) != ["skill", "dmg", "delay", "bonus"]:
            file.fail(f"{where}.weapon", "must have skill, dmg, delay and bonus")
        if weapon["skill"] is not None:
            file.text(weapon["skill"], f"{where}.weapon.skill")
        for name in ("dmg", "delay", "bonus"):
            if weapon[name] is not None:
                file.whole(weapon[name], f"{where}.weapon.{name}", -MAX_AMOUNT, MAX_AMOUNT)
    if "item_type" in record:
        file.text(record["item_type"], f"{where}.item_type", limit=RECORD_LIMITS["itemType"])
        if record.get("item_type_source") is not None:
            file.text(record["item_type_source"], f"{where}.item_type_source", limit=RECORD_LIMITS["itemType"])
    elif "item_type_source" in record:
        file.fail(f"{where}.item_type_source", "is there only with an item type")
    file.choice(file.field(record, "tier_rule", where), f"{where}.tier_rule", TIER_RULES)
    evidence = file.mapping(file.field(record, "evidence", where), f"{where}.evidence")
    level = file.choice(file.field(evidence, "level", f"{where}.evidence"), f"{where}.evidence.level", LEVELS)
    for name in evidence:
        if name not in ("level", "codes"):
            file.fail(f"{where}.evidence.{name}", "is not a field of an evidence block")
    if "codes" in evidence:
        codes = file.sequence(evidence["codes"], f"{where}.evidence.codes")
        if len(codes) > RECORD_LIMITS["codes"]:
            file.fail(f"{where}.evidence.codes", f"must be a list of up to {RECORD_LIMITS['codes']} codes")
        for n, code in enumerate(codes):
            file.text(code, f"{where}.evidence.codes[{n}]", limit=RECORD_LIMITS["codeText"])
    if "owned_only" in record and record["owned_only"] is not True:
        file.fail(f"{where}.owned_only", "is there only when it is true")
    if ("owned_only" in record) != (level == "hidden"):
        file.fail(f"{where}.owned_only", "must be true for a hidden item and for no other")
    if "source" in record:
        _source(file, record["source"], where)
    return key


def _admits(classes: Sequence[str] | None, trio: set[str]) -> bool:
    return classes is None or "ALL" in classes or bool(trio & set(classes))


def _check_shield_setups(file: _File, bundle: Mapping[str, Any], records: Iterable[Mapping[str, Any]], slug: str) -> None:
    """The ``1h-shield`` setup of a bundle is the one setup that the item pool decides (``weapons.setups_for``): a role that could play it has it at an
    evidence level if the pool of that level (the strict items, and for the wiki level the wiki items too; no deity's item, none that is no good for the
    best-in-slot lists, none that the trio cannot wear) holds a shield. Held to the table: a level that lists the setup needs a shield in its pool, and a level
    where the pool has a shield that every race of the bundle can wear needs the setup (a shield that only some races wear may or may not make it: the
    exporter refuses a pool in which that makes the setups depend on the race, and the table cannot say which way it went)."""
    trio = set(bundle["trio"])
    races = {row["code"] for row in bundle["races"]}
    shields = []
    for record in records:
        if "SECONDARY" not in record["slots"] or str(record.get("item_type") or "").lower() != "shield":
            continue
        evidence = record["evidence"]
        if record.get("deity") is not None or "not-for-bis" in evidence.get("codes", ()) or not _admits(record.get("classes"), trio):
            continue
        record_races = record.get("races")
        everyone = record_races is None or any(str(code).upper() == "ALL" for code in record_races) or races <= set(record_races)
        shields.append((evidence["level"], everyone))
    for level, pool in (("strict", ("strict",)), ("wiki", ("strict", "wiki"))):
        some = any(found in pool for found, _ in shields)
        every = any(found in pool and everyone for found, everyone in shields)
        for role, row in bundle["roles"].items():
            if "1h-shield" not in row["setups"]:
                continue
            where = f"roles.{role}.setups_by_evidence.{level}"
            listed = "1h-shield" in file.sequence(row["setups_by_evidence"][level], where)  # "in" is true of a text that holds it and of an object that has it
            if listed and not some:
                file.fail(
                    where,
                    f"lists 1h-shield, but items.json has no shield for the trio in the {level} pool: the files are not from one run: "
                    f"run the precompute again for {slug}",
                )
            if not listed and every:
                file.fail(
                    where,
                    f"lacks 1h-shield, but items.json has a shield in the {level} pool that every race can wear: the files are not from one run: "
                    f"run the precompute again for {slug}",
                )


def load_items(results_dir: str | Path, trios: Sequence[TrioResults]) -> BrowserFile:
    """Read and check the item table of a folder of results against every trio in it (see the module docstring)."""
    browser = _browser()
    file = _read(Path(results_dir), ITEMS_NAME.removesuffix(".json"), folder=False)
    doc = file.mapping(file.document, "")
    if not trios:
        file.fail("", "cannot be checked against no trio")
    if not isinstance(doc.get("data_release"), str) or not _RELEASE.fullmatch(doc["data_release"]):
        file.fail("data_release", "must look like data-2026-10-14, the data release as a date")
    for trio in trios:
        doc = _engine_header(file, doc, browser.ITEM_TABLE_FIELDS, trio.meta, what="the item table")
    stale = [trio.meta.slug for trio in trios if trio.bundle.document["inputs"] != doc["inputs"]]
    if stale:
        file.fail(
            "inputs",
            "; ".join(
                f"{slug} was made from other inputs than items.json (another catalog, or other seen flags merged into the levels): "
                f"run the precompute again for {slug}"
                for slug in dict.fromkeys(stale)
            ),
        )
    if doc["defaults"] != browser.ITEM_DEFAULTS:
        file.fail("defaults", "must be the defaults the exporter writes (what an absent field of a record means)")
    records = file.sequence(doc["items"], "items")
    if len(records) > MAX_RECORDS:
        file.fail("items", f"has more than {MAX_RECORDS} records")
    by_key: dict[str, dict[str, Any]] = {}
    pages: set[int] = set()
    for n, raw in enumerate(records):
        key = _record(file, raw, f"items[{n}]")
        if key in by_key:
            file.fail(f"items[{n}]", f"lists the item {key} twice")
        by_key[key] = raw
        page = raw.get("id")
        if page is not None:
            if page in pages:
                file.fail(f"items[{n}] {key}", f"lists the page {page} twice: a page names one item")
            pages.add(page)
    count = file.whole(doc["count"], "count", 0)
    if count != len(records):
        file.fail("count", f"is {count}, but there are {len(records)} records")
    for trio in trios:
        bundle_file = _File(trio.meta.slug, engine_name(trio.meta.level).removesuffix(".json"), trio.bundle.document, trio.bundle.raw)
        _check_shield_setups(bundle_file, trio.bundle.document, records, trio.meta.slug)
    for trio in trios:
        for item in used_items(trio):
            found = by_key.get(item.key)
            if found is None:
                file.fail("items", f"has no record of {item.key}, which {trio.meta.slug} shows")
            theirs = {
                "name": (found["name"], item.name),
                "slots": (list(found["slots"]), list(item.slots)),
                "tier_rule": (found["tier_rule"], item.tier_rule),
                "deity": (found.get("deity"), None if item.deity is None else list(item.deity)),
                "evidence": (found["evidence"]["level"], item.evidence),
            }
            for field_name, (here, there) in theirs.items():
                if here != there:
                    file.fail(
                        f"items.{item.key}",
                        f"the {field_name} is {_say(here)} here and {_say(there)} in {trio.meta.slug}: the files are not from one run",
                    )
    return BrowserFile(ITEMS_NAME, file.raw, doc)


def load_trio(directory: str | Path) -> TrioResults:
    """Read and check all the results of one trio. The folder's name is the trio (``pal-mnk-ber``)."""
    folder = Path(directory)
    slug = folder.name
    trio = parse_slug(slug)
    shards: dict[tuple[str, str], Shard] = {}
    metas: dict[str, dict[str, Any]] = {}
    for name in SHARD_NAMES:
        shard, meta = _shard(folder, name, slug)
        shards[(shard.evidence, shard.buffs)] = shard
        metas[name] = meta
    first_name = SHARD_NAMES[0]
    first = shards[(EVIDENCE[0], BUFFS[0])]
    for name in SHARD_NAMES[1:]:
        shard = shards[tuple(name.split("-"))]  # type: ignore[index]
        for what, got, want in (
            ("data_release", metas[name]["release"][0], metas[first_name]["release"][0]),
            ("game_patch", metas[name]["release"][2], metas[first_name]["release"][2]),
            ("level", metas[name]["level"], metas[first_name]["level"]),
            ("rules_version", metas[name]["rules_version"], metas[first_name]["rules_version"]),
        ):
            if got != want:
                raise ResultsError(f"{slug}/{name}.json: {what} differs from {first_name}.json")
        if _grid(shard) != _grid(first):
            raise ResultsError(
                f"{slug}/{name}.json: the grid (races, roles, tiers) differs from {first_name}.json: {_grid_difference(shard, first, first_name)}"
            )
    tag, date, patch = metas[first_name]["release"]
    rules_version = metas[first_name]["rules_version"]
    run = ((tag, date, patch), rules_version)
    partial = any(meta["partial"] for meta in metas.values())
    meta = Meta(slug, trio, metas[first_name]["level"], tag, date, patch, rules_version, partial)
    defaults = _defaults(folder, slug, shards, run)
    return TrioResults(
        meta=meta,
        shards=shards,
        runnerups=_runnerups(folder, slug, shards[(defaults.evidence, "own")], defaults.evidence, run),
        robust=_robust(folder, slug, shards, defaults, run),
        defaults=defaults,
        bundle=_bundle(folder, meta, shards),
    )


# ---- the effects to exalt (the two files of the effects layer, when the results have them) -----------------------------------------------------------


#: the shared file of the effects layer (in the folder of results, beside ``items.json``) and the file of each trio (in its folder); a release made before the layer has neither
EFFECTS_NAME = "effects.json"
EXALT_NAME = "exalt.json"
EXALT_VERSION = 1
EFFECT_KINDS = ("focus", "click", "carry", "worn", "proc")
PLAN_KINDS = ("focus", "click", "worn", "proc")
#: why a row is marked unverified, and why an effect has no host in a plan (effects/files.py and effects/plan.py; a test holds them equal)
EXALT_UNVERIFIED = ("ambiguous", "equip", "inferred", "description")
EXALT_NO_ROOM = ("donor", "primary", "slot", "class", "tier", "taken")
#: the budgets of the two files (effects/files.py: SHARED_RAW_LIMIT, SHARED_GZIP_LIMIT, TRIO_GZIP_LIMIT; a test holds them equal)
EXALT_SHARED_RAW = 200 * 1024
EXALT_SHARED_GZIP = 50 * 1024
EXALT_TRIO_GZIP = 20 * 1024
EXALT_MAX_EFFECTS = 2000
EXALT_NAME_LIMIT = 160
_EFFECT_ID = re.compile(r"e[0-9]{3,5}(?![\s\S])")


@dataclass(frozen=True)
class Exalt:
    """The effects layer of a folder of results, read and checked: the shared document and the document of each trio that has one (``trios``: slug to document)."""

    effects: dict[str, Any] = field(repr=False)
    trios: dict[str, dict[str, Any]] = field(repr=False)

    def has(self, slug: str) -> bool:
        return slug in self.trios


def _gzip_len(raw: bytes) -> int:
    return len(gzip.compress(raw, 9, mtime=0))


def _record_key_of(record: Mapping[str, Any]) -> str:
    return record.get("key") or f"w{record['id']}"


def _effect_rows(file: _File, doc: Mapping[str, Any], records: Mapping[str, Any]) -> None:
    """Check the effect rows of the shared file."""
    rows = file.sequence(file.field(doc, "effects", ""), "effects")
    if len(rows) > EXALT_MAX_EFFECTS:
        file.fail("effects", f"has more than {EXALT_MAX_EFFECTS} effects")
    found: set[str] = set()
    for n, raw in enumerate(rows):
        where = f"effects[{n}]"
        row = file.mapping(raw, where)
        effect = file.text(file.field(row, "id", where), f"{where}.id", limit=8)
        if not _EFFECT_ID.match(effect) or effect in found:
            file.fail(f"{where}.id", "must be a new id like e012")
        found.add(effect)
        where = f"effects {effect}"
        file.text(file.field(row, "n", where), f"{where}.n", limit=EXALT_NAME_LIMIT)
        kind = file.choice(file.field(row, "k", where), f"{where}.k", EFFECT_KINDS)
        file.text(file.field(row, "c", where), f"{where}.c", limit=40)
        for name in ("m", "q", "r"):
            if row.get(name) is not None:
                file.number(row[name], f"{where}.{name}")
        if row.get("u") is not None:
            file.text(row["u"], f"{where}.u", limit=20)
        for reason in file.sequence(file.field(row, "x", where), f"{where}.x"):
            file.choice(reason, f"{where}.x", EXALT_UNVERIFIED)
        for pair in file.sequence(file.field(row, "d", where), f"{where}.d"):
            donor = file.sequence(pair, f"{where}.d")
            if len(donor) != 2 or not isinstance(donor[0], str) or donor[0] not in records:
                file.fail(f"{where}.d", "must list [item key, access cost] of items that the item table has")
            file.whole(donor[1], f"{where}.d cost", 0, 99)
        if kind == "focus":
            focus = file.mapping(file.field(row, "f", where), f"{where}.f")
            for name in ("fam", "kind", "type", "lim"):
                file.text(file.field(focus, name, f"{where}.f"), f"{where}.f.{name}", limit=400)
            for name in ("lo", "hi", "pen"):
                file.number(file.field(focus, name, f"{where}.f"), f"{where}.f.{name}")
            for name in ("tier", "max"):
                if focus.get(name) is not None:
                    file.whole(focus[name], f"{where}.f.{name}", 0, 999)
            for cls, share in file.mapping(file.field(focus, "cov", f"{where}.f"), f"{where}.f.cov").items():
                if cls not in CLASS_CODES:
                    file.fail(f"{where}.f.cov", f"names {cls!r}, which is not a class")
                file.whole(share, f"{where}.f.cov.{cls}", 0, 100)
        elif "f" in row:
            file.fail(f"{where}.f", "is there for a focus only")


def _shared_exalt(results: Path, items_doc: Mapping[str, Any], records: Mapping[str, Any]) -> dict[str, Any] | None:
    if not (results / EFFECTS_NAME).is_file():
        return None
    file = _read(results, EFFECTS_NAME.removesuffix(".json"), folder=False)
    if len(file.raw) > EXALT_SHARED_RAW or _gzip_len(file.raw) > EXALT_SHARED_GZIP:
        file.fail("", f"is over its budget of {EXALT_SHARED_RAW // 1024} KB raw and {EXALT_SHARED_GZIP // 1024} KB gzipped")
    doc = file.mapping(file.document, "")
    if file.field(doc, "version", "") != EXALT_VERSION or isinstance(doc["version"], bool):
        file.fail("version", f"must be {EXALT_VERSION}")
    if file.field(doc, "data_release", "") != items_doc["data_release"]:
        file.fail("data_release", f"is {doc['data_release']!r}, but items.json says {items_doc['data_release']!r}: the files are not from one run")
    file.date(file.field(doc, "rules_version", ""), "rules_version")
    file.text(file.field(doc, "license", ""), "license", limit=40)
    file.text(file.field(doc, "attribution", ""), "attribution", limit=1000)
    if doc.get("spells_us") is not None and not _SHA256.match(str(doc["spells_us"])):
        file.fail("spells_us", "must be the SHA-256 of the client's spell text")
    file.whole(file.field(doc, "cap", ""), "cap", 1, 100)
    for cls, mass in file.mapping(file.field(doc, "mass", ""), "mass").items():
        if cls not in CLASS_CODES or isinstance(mass, bool) or not isinstance(mass, (int, float)) or not 0 <= mass <= 1:
            file.fail("mass", "must give each class a number from 0 to 1")
    _effect_rows(file, doc, records)
    return doc


def _trio_exalt(
    results: Path, trio: TrioResults, shared: Mapping[str, Any], records: Mapping[str, Any], rows: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any] | None:
    # (the donors an effect has in the shipped effects.json: the names, slots and classes the page shows and matches with are those of that file's items, and no other item is one)
    donors = {effect: {key for key, _ in row["d"]} for effect, row in rows.items()}
    slug = trio.meta.slug
    folder = results / slug
    if not (folder / EXALT_NAME).is_file():
        return None
    file = _read(folder, EXALT_NAME.removesuffix(".json"))
    if _gzip_len(file.raw) > EXALT_TRIO_GZIP:
        file.fail("", f"is over its budget of {EXALT_TRIO_GZIP // 1024} KB gzipped")
    doc = file.mapping(file.document, "")
    if file.field(doc, "version", "") != EXALT_VERSION or isinstance(doc["version"], bool):
        file.fail("version", f"must be {EXALT_VERSION}")
    if file.field(doc, "trio", "") != slug:
        file.fail("trio", f"must be {slug!r}, the name of the folder")
    if file.field(doc, "data_release", "") != shared["data_release"] or doc["data_release"] != trio.meta.data_tag:
        file.fail("data_release", f"is {doc['data_release']!r}, but the shards say {trio.meta.data_tag!r}: the files are not from one run")
    if list(file.sequence(file.field(doc, "classes", ""), "classes")) != list(trio.meta.trio):
        file.fail("classes", f"must be {list(trio.meta.trio)}")
    if file.field(doc, "race", "") != trio.defaults.race or file.field(doc, "tier", "") != trio.defaults.tier:
        file.fail("race", "and tier must be the race and the tier of the default answer (the plan is made for that kit)")
    offered = set(next(iter(trio.shards.values())).roles)
    for role, entry in file.mapping(file.field(doc, "roles", ""), "roles").items():
        where = f"roles.{role}"
        if role not in offered:
            file.fail(where, "is a role the page does not offer")
        body = file.mapping(entry, where)
        for kind in EFFECT_KINDS:
            for n, row in enumerate(file.sequence(file.field(body, kind, where), f"{where}.{kind}")):
                at = f"{where}.{kind}[{n}]"
                row = file.mapping(row, at)
                if file.field(row, "e", at) not in rows or rows[row["e"]]["k"] != kind:
                    file.fail(f"{at}.e", f"must be an effect of the shared file that is listed as {kind}")
                for key in [file.field(row, "d", at), *file.sequence(file.field(row, "o", at), f"{at}.o")]:
                    if key not in records:
                        file.fail(f"{at}.d", "names an item the item table does not have")
                    if key not in donors[row["e"]]:
                        file.fail(f"{at}.d", f"names {key}, which is no donor of that effect in {EFFECTS_NAME}")
                file.number(file.field(row, "s", at), f"{at}.s")
                if file.field(row, "m", at) not in CLASS_CODES:
                    file.fail(f"{at}.m", "must be a class")
                if kind == "focus":
                    file.text(file.field(row, "t", at), f"{at}.t", limit=20)
                    for family in file.sequence(file.field(row, "l", at), f"{at}.l"):
                        file.text(family, f"{at}.l", limit=EXALT_NAME_LIMIT)
                    for cls, gain in file.mapping(file.field(row, "g", at), f"{at}.g").items():
                        if cls not in CLASS_CODES:
                            file.fail(f"{at}.g", "must name classes")
                        file.number(gain, f"{at}.g.{cls}")
        for n, row in enumerate(file.sequence(file.field(body, "plan", where), f"{where}.plan")):
            at = f"{where}.plan[{n}]"
            row = file.mapping(row, at)
            kind = file.choice(file.field(row, "k", at), f"{at}.k", PLAN_KINDS)
            if file.field(row, "e", at) not in rows or rows[row["e"]]["k"] != kind:
                file.fail(f"{at}.e", "must be an effect of the shared file, of the kind the row says")
            if file.field(row, "d", at) not in records or file.field(row, "h", at) not in records:
                file.fail(f"{at}.h", "names an item the item table does not have")
            if row["d"] not in donors[row["e"]]:
                file.fail(f"{at}.d", f"names {row['d']}, which is no donor of that effect in {EFFECTS_NAME}")
            file.choice(file.field(row, "p", at), f"{at}.p", PLACES)
            for cls in file.sequence(file.field(row, "c", at), f"{at}.c"):
                if cls not in CLASS_CODES:
                    file.fail(f"{at}.c", "must name classes")
            file.choice(file.field(row, "u", at), f"{at}.u", (0, 1))
        for n, row in enumerate(file.sequence(file.field(body, "noroom", where), f"{where}.noroom")):
            at = f"{where}.noroom[{n}]"
            row = file.mapping(row, at)
            if file.field(row, "e", at) not in rows:
                file.fail(f"{at}.e", "must be an effect of the shared file")
            if file.choice(file.field(row, "k", at), f"{at}.k", PLAN_KINDS) != rows[row["e"]]["k"]:
                file.fail(f"{at}.k", "must be the kind of the effect in the shared file")
            file.choice(file.field(row, "w", at), f"{at}.w", EXALT_NO_ROOM)
    return doc


def load_exalt(results_dir: str | Path, trios: Sequence[TrioResults], items_doc: Mapping[str, Any]) -> Exalt | None:
    """Read and check the files of the effects layer in a folder of results (the format is in :mod:`trioforge.effects.files`), or ``None`` when it has none.

    The shared file ``effects.json`` and the ``exalt.json`` of a trio are each optional, but a trio file without the shared one is refused, and a file must come from the
    run of the item table, name only effects, items and classes that exist, and be within its budget. A trio without a file has no section on its page."""
    results = Path(results_dir)
    records = {_record_key_of(record): record for record in items_doc["items"]}
    present = exalt_slugs(results, [trio.meta.slug for trio in trios])  # (raises for a trio file with no shared file)
    shared = _shared_exalt(results, items_doc, records)
    if shared is None:
        return None
    rows = {row["id"]: row for row in shared["effects"]}
    found: dict[str, dict[str, Any]] = {}
    for trio in trios:
        if trio.meta.slug in present:
            found[trio.meta.slug] = _trio_exalt(results, trio, shared, records, rows)
    return Exalt(shared, found)


def exalt_slugs(results_dir: str | Path, slugs: Sequence[str]) -> frozenset[str]:
    """The trios of ``slugs`` that have the file of the effects layer in a folder of results, which is the one answer to "does this trio ship an ``exalt.json``" (the site build, the files it lists
    and the release's count of them all use it): the trio's own file counts only with the shared ``effects.json`` beside the items, and a trio file with no shared file is refused."""
    results = Path(results_dir)
    present = [slug for slug in slugs if (results / slug / EXALT_NAME).is_file()]
    if not (results / EFFECTS_NAME).is_file():
        if present:
            raise ResultsError(f"{present[0]}/{EXALT_NAME}: is there, but {EFFECTS_NAME} is not")
        return frozenset()
    return frozenset(present)


def site_effects_json(exalt: Exalt, items_doc: Mapping[str, Any], credit: Credit, with_page: Collection[str] = (), late: int = 30) -> str:
    """The shared file as the browser fetches it: the effects, and what the page needs to say and to match their donors (``items``: for every donor, ``[name, 1 if the item has a page
    of its own else 0, its slots, its classes, 1 if it is a two-hand weapon, the tier it arrives at]``, the slots and classes as words in a text, ``ALL`` for every class), and ``late``, the
    first spell level that counts as late (the coverage of a focus is the share of the spells of a class from this level up that it touches)."""
    shared = exalt.effects
    records = {_record_key_of(record): record for record in items_doc["items"]}
    every = items_doc["defaults"]["classes"]
    donors = sorted({key for row in shared["effects"] for key, _ in row["d"]})
    items: dict[str, list[Any]] = {}
    for key in donors:
        record = records[key]
        skill = (record.get("weapon") or {}).get("skill") or ""
        rule = record["tier_rule"]
        items[key] = [
            record["name"], 1 if key in with_page else 0, " ".join(record["slots"]), " ".join(record.get("classes", every)),
            1 if skill.startswith("2H") else 0, 4 if rule == "drop" else (0 if rule == "fixed0" else None),
        ]  # fmt: skip
    document = {
        "v": BROWSER_VERSION,
        **_credited(credit),
        "spells_us": shared.get("spells_us"),
        "cap": shared["cap"],
        "late": late,
        "mass": shared["mass"],
        "items": items,
        "effects": shared["effects"],
    }
    return render(document, per_line=("items", "effects"))


def site_exalt_json(exalt: Exalt, slug: str, items_doc: Mapping[str, Any], credit: Credit) -> str:
    """The file of a trio as the browser fetches it: the roles as the results have them, and ``names``, the name of each item the plans put an effect on (the kit of the default view, which
    the page does not have the keys of until a switch is used)."""
    doc = exalt.trios[slug]
    names = {_record_key_of(record): record["name"] for record in items_doc["items"]}
    hosts = sorted({row["h"] for entry in doc["roles"].values() for row in entry["plan"]})
    document = {
        "v": BROWSER_VERSION,
        **_credited(credit),
        "trio": slug,
        "classes": doc["classes"],
        "race": doc["race"],
        "tier": doc["tier"],
        "names": {key: names[key] for key in hosts},
        "roles": doc["roles"],
    }
    return render(document, per_line=("names", "roles"))


# ---- the browser format ----------------------------------------------------------------------------------------------------------
#
# Compact, positional and versioned ("v"), so the page code can index it without a schema. Every file starts with the same four
# keys: "v", "release" (the data release it was made from: the page refuses a file of another release), "license" and "attribution".
#   shard      {"v", ..., "ev", "buffs" (the set: own or group), "stat_tiers" (the tiers of the shard; only with the stats),
#               "items": [[key, name, tier rule, arrival (a tier, or null for a
#               summoned item), source, evidence, [deity names], [stats at each of stat_tiers: the text of a row of Wear this]]...], "kits": [[22 item indexes]...],
#               "totals": [[ac, hp, mana, end, haste, atk, 5 resists, 3 regen]...],
#               "rows": [[race, role, tier, setup, kit, F, gain, totals, haste assumed]...]}
#              (the optional buff ids and the solver's options are not sent: no page uses them)
#   runner-ups {"v": 2, ..., "role", "tiers": [tier...], "items": [item...], "views": [[tier, race, setup, [22 lists of [item, delta]]]...]}
#              one file for each role, with every tier of the run in it and one table of items, fetched the first time a view of that
#              role has its runner-ups opened (the page reads the tier from it)
#   robust     {"v": 2, ..., "race", "views": [[role, tier, setup, evidence, buffs, [22 labels]]...]}
#              each view is sealed for one weapon setup, evidence level and buff set (and the race): the page shows the labels for
#              exactly that view


def _item_row(item: Item) -> list[Any]:
    return [item.key, item.name, item.tier_rule, item.arrival, item.source, item.evidence, list(item.deity or ())]


def _totals_row(totals: Totals) -> list[int]:
    return [totals.ac, totals.hp, totals.mana, totals.end, totals.haste, totals.atk, *totals.resists, *totals.regen]


def _credited(credit: Credit) -> dict[str, Any]:
    """The first keys of every browser file (see the format above)."""
    return {"release": credit.release, "license": credit.license, "attribution": credit.attribution}


def site_shard_json(shard: Shard, credit: Credit, lines: Callable[[str, int], str] | None = None) -> str:
    """The shard as the browser fetches it. Kits and totals are deduplicated, items numbered by first use.

    ``lines`` (an item key and a tier to the stats of that item at that tier, as a row of Wear this says them) adds ``stat_tiers`` (the tiers of the shard) and, as the last
    entry of each item, its stats at each of them, so that the page can show the stats of any view the shard answers."""
    item_index: dict[str, int] = {}
    items: list[Item] = []
    kit_index: dict[tuple[int, ...], int] = {}
    kits: list[list[int]] = []
    totals_index: dict[Totals, int] = {}
    totals: list[Totals] = []
    rows: list[list[Any]] = []
    for scenario in shard.scenarios:
        kit = []
        for item in scenario.kit:
            if item is None:
                kit.append(-1)
                continue
            if item.key not in item_index:
                item_index[item.key] = len(items)
                items.append(item)
            kit.append(item_index[item.key])
        kit_key = tuple(kit)
        if kit_key not in kit_index:
            kit_index[kit_key] = len(kits)
            kits.append(kit)
        if scenario.totals not in totals_index:
            totals_index[scenario.totals] = len(totals)
            totals.append(scenario.totals)
        rows.append(
            [scenario.race, scenario.role, scenario.tier, scenario.setup, kit_index[kit_key], scenario.value,
             scenario.gain, totals_index[scenario.totals], scenario.haste_assumed]
        )  # fmt: skip
    document = {
        "v": BROWSER_VERSION,
        **_credited(credit),
        "ev": shard.evidence,
        "buffs": shard.buffs,
        **({} if lines is None else {"stat_tiers": list(shard.tiers)}),
        "items": [_item_row(item) + ([] if lines is None else [[lines(item.key, tier) for tier in shard.tiers]]) for item in items],
        "kits": kits,
        "totals": [_totals_row(t) for t in totals],
        "rows": rows,
    }
    return render(document, per_line=("items", "kits", "totals", "rows"))


def site_runnerups_json(runnerups: RunnerUps, role: str, credit: Credit) -> str:
    """The runner-ups of one role, for every race at every tier of the run, as the browser fetches them: one file, one table of items."""
    found = next((file for file in runnerups.files if file.role == role), None)
    if found is None:
        raise ValueError(f"no runner-up file for the {role} role")
    item_index: dict[str, int] = {}
    items: list[Item] = []
    views = []
    for view in runnerups.views:
        if view.role != role:
            continue
        slots = []
        for swaps in view.slots:
            row = []
            for swap in swaps:
                if swap.item.key not in item_index:
                    item_index[swap.item.key] = len(items)
                    items.append(swap.item)
                row.append([item_index[swap.item.key], swap.delta])
            slots.append(row)
        views.append([view.tier, view.race, view.setup, slots])
    document = {
        "v": RUNNERUPS_VERSION,
        **_credited(credit),
        "role": role,
        "tiers": list(found.tiers),
        "items": [_item_row(item) for item in items],
        "views": views,
    }
    return render(document, per_line=("items", "views"))


def site_robust_json(robust: Robust, credit: Credit) -> str:
    document = {
        "v": ROBUST_VERSION,
        **_credited(credit),
        "race": robust.race,
        "views": [
            [v.role, v.tier, v.sealed.setup, v.sealed.evidence, v.sealed.buffs, list(v.labels)] for v in robust.views
        ],
    }
    return render(document, per_line=("views",))


def used_items(results: TrioResults) -> list[Item]:
    """Every item the site shows for this trio (any shard, any runner-up), once each, sorted by key."""
    seen: dict[str, Item] = {}
    pools: Iterable[Iterable[Item]] = [*(shard.items for shard in results.shards.values()), results.runnerups.items]
    for pool in pools:
        for item in pool:
            seen.setdefault(item.key, item)
    return [seen[key] for key in sorted(seen)]
