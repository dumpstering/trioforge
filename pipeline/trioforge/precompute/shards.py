"""The files a precompute run writes, and how they are made.

A run keeps its work in **chunk files** and, when every chunk is done, assembles the **result files** from them. Nothing
here solves anything; it only describes, stores, checks and arranges what the solver produced.

Chunk files
===========

``<trio>/chunks/s-<evidence>-<buffs>-<role>-<setup>-t<tier>.json`` holds the solved races of one view, and
``r-<role>-t<tier>.json`` the runner-ups of one role at one tier (the chunks of a role are put into one result file, below). A chunk file is one line of JSON that ends with its own
SHA-256 (over the rest of the line) and carries the **fingerprint** of the inputs it was made from (the catalog, the seen
flags, the rules and tables, the solver options). It is written to a temporary file and renamed, so a reader sees a whole
file or none. :func:`load_chunk` reports ``ok``, ``missing`` or ``damaged`` (unreadable, cut short, edited, or made from
other inputs), and a damaged chunk is redone.

Result files (``<trio>/``)
==========================

``<evidence>-<buffs>.json`` (the **shard**), one for each of ``strict``/``wiki`` and ``own``/``group``:

=============  ===============================================================================================
``version``    the format number (1)
``trio``       the slug (``pal-mnk-ber``); ``classes`` the codes in class order
``evidence``,  the two choices of this file; ``level`` the character level
``buffs``
``data_release``, ``game_patch``, ``rules_version``   where the data comes from (the catalog's date as ``data-YYYY-MM-DD``,
               the date of the newest client file, the version of ``rules.json``)
``solver``     how every answer was made: ``canonical`` (ties resolved by the tie stage), the HiGHS options that can change an
               answer (``presolve``, ``mip_rel_gap``, ``mip_abs_gap``, ``threads``, ``random_seed``, the two feasibility
               tolerances), ``time_limit`` (null: never set), the HiGHS version and source ``revision`` and ``kept_first``, the
               number of rows of this file whose tie stage kept the first-stage kit (the optimum, with the choice among
               equal kits left to the solver; 0 when every row is canonical)
``build_options``  the builder options of every model: ``any_rule`` (``all``: an Any place takes every item that has a slot)
               and ``haste_assumed`` (null: the weapon index's haste is worked out for each scenario, see the rows)
``assumptions``  the profile choices that are not model rows: ``aa`` (Combat Stability rank and Physical Enhancement, the
               defaults) and ``deity`` (null: items locked to a deity are left out of every precomputed kit). These and ``caps``
               are the same for every race and role of the trio (:func:`trioforge.precompute.layout_facts`; the run stops if not)
``flags``      ``["strict pool empty"]`` while no item is strict; ``partial`` is true when the file does not hold every
               scenario of the grid of the run's **scope** (every race, role, setup, evidence level and buff set at the tiers
               asked for, see ``tiers``): a run that narrows only its tiers is not partial, since the tiers it was asked for are
               its scope, and one that narrows races, roles, evidence levels or buff sets, or stops at ``--limit``, is;
               ``pool`` is the number of items in this evidence level's pool
``races``      the races the run covers (every playable race in a full run, only the races of a narrowed run: the races that have
               rows) in display order, ``{"code", "legal"}``: the creation-legal ones first
``roles``, ``setups``, ``tiers``   what the file's scenarios cover (``setups`` by role). ``tiers`` is the **scope** of the run
               (+0, +4 and +10 for a trio of the grid, every tier for the milestone trio; see
               :func:`trioforge.scope.default_tiers`; always with +4, the tier of the default view): the tiers the shards, the
               runner-up files and the seals hold, and the ones the page offers. The reader holds the rows of a shard to it, and the
               runner-up files; an indexable build of the site holds the trio to the scope of a full run of it. The setups follow the
               solve pool of the file's evidence level: a level whose pool has no shield that a class of the trio can wear has no
               ``1h-shield``, so the strict files can list fewer setups than the wiki files. Each file carries its own list of
               setups, made from the rows it holds, and the reader compares none of them with another file's
``caps``       ``sheet_softcap``, ``haste``, ``resist`` and ``regen`` caps of the trio
``places``     the 22 place names a kit lists, in kit order (``EAR1``, ``EAR2``, ``FINGER1`` ...)
``items``      rows of ``items_keys``: ``key name slots tier_rule arrival source evidence deity``; ``arrival`` is a whole tier
               (4 for a drop, 0 for a quest, vendor or crafted item) or null for a summoned item: the highest tier at which a
               copy exists without merging (see :func:`arrival_tier`); only items some kit
               wears, sorted by key. ``evidence`` is the item's level (``strict`` or ``wiki``) and ``deity`` is null for
               every item of a shard (deity-locked items are never worn in a precomputed kit)
``kits``       the distinct kits: 22 indexes into ``items``, -1 for an empty place
``totals``     the distinct total vectors, in the order of ``totals_keys``
``buff_sets``  the distinct lists of the **optional** buffs the solver chose (spell ids, sorted): the buffs that are always on
               for the scenario's buff set are not listed, they follow from the buff set itself
``scenarios``  ``[race, role, tier, setup, kit, F, gain, totals, buffs, haste]``: ``kit``, ``totals`` and ``buffs`` index
               ``kits``, ``totals`` and ``buff_sets``; ``F`` is the value of the kit (HP-equivalents) and ``gain`` is ``F``
               minus the value of the naked character with its best buffs (both have two decimals); ``haste`` is the haste
               percent the weapon index was taken at (``haste_assumed``, a constant of the scenario). With the kit, the buffs
               and ``haste`` a reader can value the kit again and get ``F``. All items of a kit are at the scenario's tier.
=============  ===============================================================================================

``engine-l<level>.json`` is the **browser bundle** of the trio at the character level of the run (``engine-l50.json``): what the
browser's engine reads to rebuild any profile and to run the formulas, in the format of :func:`trioforge.export.browser.bundle`
(which documents it). It is made at the start of the run from the run's own inputs: the catalog document the run was given, and
the private seen flags it was given, merged into the pools the weapon setups of each evidence level are read from, so that its
``roles[role]["setups_by_evidence"]`` are the setups the shards have (the run stops if they differ). A pool for which a bundle cannot be made
(a shield that only some races may wear makes the setups depend on the race) is a violation of the run, and no bundle is written.
``data_release`` and ``rules_version`` are the shards' own.

``items.json`` is the **item table**, one file for the whole results folder and not for a trio (``<results>/items.json``, beside the
trio folders): every wearable of the catalog, in the format of :func:`trioforge.export.browser.items`, with the evidence levels of the
run (the catalog's own and the seen flags merged, as the pools are). Every run of every trio writes it from the same kind of inputs; a
run that finds a byte-identical file leaves it, and one that finds another replaces it whole (all or nothing) and says so in its notes,
since the files of the trios made before may then have levels that differ from the table's. Neither file says that a flag was merged.

Both files carry ``inputs``, after ``rules_version``: the **fingerprint of the inputs** of the run (:func:`trioforge.export.browser.inputs_fingerprint`),
the SHA-256 of the catalog file the run read and of the key and evidence level of every item of the table, the flags merged. It is made of what the
published table says and never of the flags (a digest of the list of flags could be tried against guesses about flags that change no level). The site
build refuses a folder in which a trio's bundle and ``items.json`` do not share one, and says which trio to run again. A run replaces the files of its trio
first (all or nothing, the defaults last) and ``items.json`` after them, so that a write that fails leaves the table as it was; a table that cannot be made
is removed, as a bundle that cannot be made is, and the run lists it among its violations.

``runnerups/<role>.json``, **one file for each role, holding every tier of the run's scope**, so that the page fetches the file
of the role once, when the runner-ups first open, and reads the tier from it (the header of a shard with ``role``, ``tiers``,
``evidence``, ``buffs`` and ``evidence_fallback``, then ``places``, ``items_keys``, ``items`` and ``views``): the swaps of the
**default assumptions** (the default evidence level, own buffs, the role's best setup) for each race at each tier. A view is
``[tier, race, setup, places]``, one for each tier in ascending order and, within it, each race in display order; ``tiers``
is the tiers of the shards, each of them has a view for every race of the run, and no tier is in the file twice. ``places``
holds, for each of the 22 places, the three best ``[item, delta]`` swaps of items that anyone can wear and, besides
them, at most one swap of an item
locked to a deity, kept only when its delta is above the best of the three (or there is none to compare with): the item is an
index into ``items``, whose row names the deity (``deity`` is null for every other item), and the delta is the exact change of
the value when only that place changes (at most 0 for an item of the solve pool, since the kit is the best there is; above 0
for a locked item that is better than the kit's pick). The entries of a place are in order of delta, so a locked swap comes
first. The candidates are the whole pool of the default evidence level and its deity-locked items, not the pruned pool; the
buffs and the assumed haste are those of the solved kit. ``items`` is one table for the file and lists only the items its entries
point at, whatever the tier. The file is held to the budget of a shard (200 KB raw and 50 KB gzip: :func:`check_budget`), which
the file of the 11 tiers of the milestone trio, the largest there is, has to keep.
``runnerups/index.json`` has the same header and ``files``, one ``{file, role, tiers, bytes, gzip, sha256}`` for each file in
order of role (``tiers`` is the same list as the file's own, ``bytes`` and ``sha256`` are those of the file as written, ``gzip`` its
size at level 9). The old single ``runnerups.json`` and the files of an earlier layout, one for each role and tier
(``<role>-<tier>.json``), are no longer written, and a run removes them.

``defaults.json``: the ``view`` (role, tier, evidence, buffs) the default answer is taken from, ``strict_pool_empty``, the
default ``race`` (the creation-legal race with the highest total value in that view; a race that cannot be created never
wins), ``runner_up_race``, the ``margin`` between them, its ``F`` and best ``setup``, the value of every race
(``races``), the ``flip_notes`` of the robustness solves and ``robustness`` (``done`` or ``skipped: <why>``). A flip note
says that an open rule, switched to its alternative, would put another race on top of the default view:
``"Iksar, if Iksar AC stacks inside the cap (test B17)"`` (the race, the alternative, the in-game test that settles the rule); the
list is empty when no alternative flips the best race, and while the robustness is skipped (see :mod:`trioforge.precompute.seals`).

``robust.json``: ``race`` (the default race), ``tiers`` (the sealed tiers, +4 and +10 where the grid has them) and
``roles``, ``{role: {tier: {place: label}}}``: for each role at the default race (its best setup), whether the item worn in a
place holds under every variant of the judgment weights and the open rules. The label is ``robust``, or the label of the variant
that changed the pick (``AC x2``, ``Monk placement inside``; a rule's variant is named before a weight's, as it has an in-game
test). A pair of places (the ears, the wrists, the fingers, the Any places) is one slot to the module, so its two places carry the
same label. The file is written only when the robustness module is there and not switched off.

The text is JSON with no spaces; the top-level keys sit on lines of their own. The same inputs give the same bytes.

The reader: the contract with the site generator
================================================

:mod:`trioforge.site.data` is the **only** reader of these files, and it reads exactly the format above (the fixtures in
``fixtures/site/results/pal-mnk-ber`` are in it, and ``pipeline/tests/test_site_integration.py`` fails if their keys fall
behind those of a real run). Where the site was first written against other shapes, one side was changed, as follows.

=====================  =====================================  ==========================================================
what                   the file says                          changed
=====================  =====================================  ==========================================================
buff set and its ids   ``buffs`` is the name (``own`` or      the reader (the site took the list of ids for ``buffs``
                       ``group``) in every file that has one;  and the name for ``buff_set``)
                       ``buff_sets`` is the list of id lists
data release           ``data_release`` is the text           the reader (the site took an object with the tag, the
                       ``data-YYYY-MM-DD``, ``game_patch``     date and the patch)
                       is a field of its own
items, totals          rows named by ``items_keys`` and       the reader (the site took objects; rows keep a shard
                       ``totals_keys``, signed whole numbers   within its size budget); totals may be negative
arrival                a whole tier, or null for a summoned   **the writer** (it wrote the words "+0 to +4"; the site
                       item (:func:`arrival_tier`)             counts copies from a tier)
runner-ups             a swap is ``[item, delta]``, a view     the reader (the site took objects)
                       ``[tier, race, setup, places]``; the
                       delta of an item anyone can wear is at
                       most 0, that of an item that needs a
                       deity has any sign, and that swap comes
                       first
runner-up index        ``files`` is a list of ``{file, role,   the reader (the site took an object by file name)
                       tiers, bytes, gzip, sha256}``
runner-up evidence     the header names the evidence level of  the reader (the site took ``strict`` for granted);
                       the default answer: ``wiki`` while no   the page now bakes the answer of the default view
                       item is strict (``evidence_fallback``)  and says so
robust.json            ``roles``: ``{role: {tier: {place:      the reader (the site took a list of views with 22
                       label}}}``                              labels)
defaults.json          ``view``, ``runner_up_race``,           the reader (the site took ``runner_up`` and ``flips``
                       ``flip_notes``, ``setup``, ``F``        and fixed the view at Balanced, +4, strict, own buffs)
=====================  =====================================  ==========================================================

The two engine files are read there too, and checked against the shards: the bundle's format number, trio, level, ``data_release`` and
``rules_version``, a reassembly of its profiles and the weapon setups of each role and level; the item table's format number, release and
rules version, its records and, for every item a shard or a runner-up file shows, the name, slots, tier rule, deity and evidence level. Both are
held to the limits of the browser's own readers, to the fingerprint of their inputs (one for the folder) and to each other (the shield setup of a level
needs a shield in the table's pool of that level); and the build runs the browser's readers on what it publishes.

On top of the format the reader asks that every file come from one run (the same ``data_release``, ``game_patch`` and
``rules_version``), that the grid be complete, that the default race, its runner-up, the margin, the setup and the value agree
with the rows of the default view, and that each runner-up file and the index agree with the sizes and hashes the index lists;
see the docstring of :mod:`trioforge.site.data`. A file of a narrowed run (``partial``) is read as it is.

Size budget
===========

A shard is fetched whole when a view is switched, and the file of a role's runner-ups when the runner-ups first open, so each of
the four shards and each runner-up file is held to **200 KB raw and 50 KB gzip** (a KB is 1,000 bytes; gzip at level 9):
:func:`check_budget` measures it, and a run lists a file over either limit among its violations (the files are still written). The
totals stay inside the shard. The limits were set from the first real run of PAL/MNK/BER, where a wiki shard was about 165 KB raw
and 37 KB gzip: rows 73 KB, totals 53 to 61 KB, kits 21 to 27 KB. A runner-up file holds a view for every race at every tier of
the scope; the milestone trio's, with eleven tiers, is the largest, and the run says how large (``RunSummary.sizes``).
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trioforge.model.items import SLOT_GROUPS
from trioforge.sources.client_tables import commit_files

__all__ = [
    "FORMAT",
    "ITEM_KEYS",
    "PLACES",
    "SHARD_GZIP_LIMIT",
    "SHARD_NAMES",
    "SHARD_RAW_LIMIT",
    "TOTALS_KEYS",
    "ENGINE_PREFIX",
    "ITEMS_NAME",
    "LEGACY_NAMES",
    "Layout",
    "RUNNERUP_DIR",
    "arrival_tier",
    "check_budget",
    "check_invariants",
    "chunk_path",
    "default_race",
    "defaults_doc",
    "dumps",
    "engine_name",
    "gzip_size",
    "item_row",
    "load_chunk",
    "render",
    "robust_doc",
    "runnerup_doc",
    "runnerup_name",
    "runnerup_path",
    "runnerup_texts",
    "shard_doc",
    "source_summary",
    "write_chunk",
    "write_files",
]

FORMAT = 1
PLACES: tuple[str, ...] = tuple(
    name if size == 1 else f"{name}{n}" for name, size in SLOT_GROUPS for n in range(1, size + 1)
)  # HEAD FACE EAR1 EAR2 NECK ... ANY1 ANY2 PRIMARY SECONDARY
ITEM_KEYS = ("key", "name", "slots", "tier_rule", "arrival", "source", "evidence", "deity")
TOTALS_KEYS = (
    "ac", "hp", "mana", "end", "haste", "atk", "fire", "cold", "magic", "poison", "disease", "hpreg", "manareg", "endreg",
)  # fmt: skip
SHARD_NAMES = tuple(f"{evidence}-{buffs}.json" for evidence in ("strict", "wiki") for buffs in ("own", "group"))
KB = 1000  # bytes
SHARD_RAW_LIMIT = 200 * KB  # the most a shard file may hold
SHARD_GZIP_LIMIT = 50 * KB  # the most it may hold gzipped
OUTPUT_NAMES = (*SHARD_NAMES, "robust.json", "defaults.json")  # the files of the trio's folder (and runnerups/, below)
RUNNERUP_DIR = "runnerups"  # the sub-folder of the runner-up files and their index
LEGACY_NAMES = ("runnerups.json",)  # result files of an earlier layout: a run removes them
ENGINE_PREFIX = "engine-l"  # the bundle of a trio and level: engine-l50.json
ITEMS_NAME = "items.json"  # the item table, one for the folder of results
SOURCE_LIMIT = 60  # characters of a source summary
PER_LINE = ("items", "kits", "totals", "buff_sets", "scenarios", "views", "files")  # lists that get one line per entry
INVARIANT_TOLERANCE = 1e-9  # relative, for the cross-scenario checks
INVARIANT_LIMIT = 20  # violations listed


def engine_name(level: int) -> str:
    """The file name of the browser bundle at a character level: ``engine-l50.json``."""
    return f"{ENGINE_PREFIX}{int(level)}.json"


def dumps(value: Any) -> str:
    """Compact strict JSON (no spaces, no NaN), the same text for the same value."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def render(doc: Mapping[str, Any]) -> str:
    """The text of a result file: the top-level keys on lines of their own, the big tables with one entry a line."""
    lines = ["{"]
    last = len(doc) - 1
    for position, (key, value) in enumerate(doc.items()):
        comma = "," if position < last else ""
        if key in PER_LINE and isinstance(value, list) and value:
            lines.append(f"{dumps(key)}:[")
            lines.extend(f"{dumps(entry)}{',' if n < len(value) - 1 else ''}" for n, entry in enumerate(value))
            lines.append(f"]{comma}")
        else:
            lines.append(f"{dumps(key)}:{dumps(value)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


# ---- small texts of an item ----------------------------------------------------------------------------------------


def source_summary(item: Mapping[str, Any], live: Sequence[str] | set[str] | None = None) -> str:
    """A short text for where an item comes from, at most 60 characters.

    ``live`` is the set of live sources (zone names, and the kinds ``quest``, ``vendor``, ``craft`` and ``foraged``); when it is
    None the item's own ``live-source:`` evidence reasons give it. A drop in a live zone comes first, then a live quest, vendor,
    recipe or foraging; with no live source known the order is drops, quests, vendors, recipes, foraging.

    ``sources.quests`` holds the targets of the quest links (page titles); a quest is shown by the label its link had when the
    catalog has one for the title (``sources.quest_labels``), else by the title. ``sources.foraged`` (optional) lists the zones
    an item can be foraged in; the text names the first of them that is live, else the first."""
    if live is None:
        live = {r["code"][len("live-source:"):] for r in item["evidence"]["reasons"] if r["code"].startswith("live-source:")}
    live = set(live)
    sources = item["sources"]
    drops, quests, vendors, crafted = sources["drops"], sources["quests"], sources["sold_by"], sources["crafted"]
    foraged = [entry["zone"] for entry in sources.get("foraged") or ()]
    labels: dict[str, str] = {}
    for entry in sources.get("quest_labels") or ():
        labels.setdefault(entry["title"], entry["label"])

    def drop_text(drop: Mapping[str, Any]) -> str:
        zone = drop["zone"] or "a drop"
        return f"{zone} ({drop['npcs'][0]})" if drop["npcs"] else zone

    def vendor_text() -> str:
        return f"vendor: {vendors[0]['zone'] or vendors[0]['npc']}"

    def craft_text() -> str:
        return f"crafted: {crafted[0]['container']}" if crafted[0]["container"] else "crafted"

    def quest_text() -> str:
        return f"quest: {labels.get(quests[0], quests[0])}"

    def forage_text() -> str:
        return f"Foraged in {next((zone for zone in foraged if zone in live), foraged[0])}"

    text = ""
    live_drops = [drop for drop in drops if drop["zone"] in live]
    if live_drops:
        text = drop_text(live_drops[0])
    elif quests and "quest" in live:
        text = quest_text()
    elif vendors and "vendor" in live:
        text = vendor_text()
    elif crafted and "craft" in live:
        text = craft_text()
    elif foraged and "foraged" in live:
        text = forage_text()
    elif drops:
        text = drop_text(drops[0])
    elif quests:
        text = quest_text()
    elif vendors:
        text = vendor_text()
    elif crafted:
        text = craft_text()
    elif foraged:
        text = forage_text()
    return text if len(text) <= SOURCE_LIMIT else text[: SOURCE_LIMIT - 3] + "..."


def arrival_tier(tier_rule: str, rules: Any) -> int | None:
    """The highest tier at which a copy of an item exists without merging, from where it comes: a drop at the highest fresh
    drop (``tier.max_fresh_drop``; a drop shows up at the instance difficulty, +0 up to that), a quest, vendor or crafted item
    at +0, and None for a summoned item (its tier is its spell rank, so there is no tier to count copies from). The site counts
    the copies of a higher tier from this number: a copy at +k is worth 2^k of the 2^N needed."""
    if tier_rule == "drop":
        return int(rules.get("tier.max_fresh_drop"))
    if tier_rule == "fixed0":
        return 0
    return None


def item_row(item: Mapping[str, Any], level: str, rules: Any) -> list[Any]:
    """The row of an item in the ``items`` table (:data:`ITEM_KEYS`); ``level`` is its effective evidence level."""
    return [
        item["key"], item["name"], list(item["slots"]), item["tier_rule"], arrival_tier(item["tier_rule"], rules),
        source_summary(item), level, None if item["deity"] is None else list(item["deity"]),
    ]  # fmt: skip


# ---- chunk files ---------------------------------------------------------------------------------------------------


def chunk_path(directory: Path, key: Any) -> Path:
    """The file of a solve chunk (``key`` has ``evidence buffs role setup tier``)."""
    return directory / f"s-{key.evidence}-{key.buffs}-{key.role}-{key.setup}-t{key.tier:02d}.json"


def runnerup_path(directory: Path, role: str, tier: int) -> Path:
    return directory / f"r-{role}-t{tier:02d}.json"


def _digest(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(dumps(body).encode("utf-8")).hexdigest()


def write_chunk(path: Path, doc: Mapping[str, Any], fingerprint: str) -> None:
    """Write a chunk document with its fingerprint and checksum, all or nothing."""
    body = {"fingerprint": fingerprint, **doc}
    commit_files(path.parent, {path.name: dumps({**body, "sha256": _digest(body)}) + "\n"}, last=path.name)


def load_chunk(path: Path, fingerprint: str) -> tuple[dict[str, Any] | None, str]:
    """``(document, "ok")`` for a whole chunk file made from these inputs, else ``(None, "missing")`` or
    ``(None, "damaged")`` (unreadable, cut short, edited, or made from other inputs)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "missing"
    except (OSError, UnicodeDecodeError):
        return None, "damaged"
    try:
        doc = json.loads(text)
    except ValueError:
        return None, "damaged"
    claimed = doc.pop("sha256", None) if isinstance(doc, dict) else None
    if not isinstance(claimed, str) or _digest(doc) != claimed or doc.get("fingerprint") != fingerprint:
        return None, "damaged"
    return doc, "ok"


# ---- what the result files are made from -----------------------------------------------------------------------


@dataclass
class Layout:
    """What the result files share. ``solver`` and ``build_options`` are the records of how the answers were made (see the
    module docstring), as are ``assumptions``; ``races`` is ``[(code, creation_legal)]`` in display order, of the races that were
    run; ``roles``, ``setups`` (by role) and ``tiers`` are those of the grid that was run (``setups`` are those of all the evidence
    levels together, in the order of :data:`trioforge.model.weapons.SETUPS`; a shard lists those it has rows for; ``tiers`` is the
    run's scope); ``expected`` is the number of scenarios of the **full grid of the scope** for each ``(evidence, buffs)`` (every
    race, role and setup at the tiers asked for): a shard with fewer is partial; ``item_rows`` maps an item key to its table row."""

    trio: str
    classes: tuple[str, ...]
    level: int
    data_release: str
    game_patch: str
    rules_version: str
    solver: dict[str, Any]
    build_options: dict[str, Any]
    assumptions: dict[str, Any]
    races: list[tuple[str, bool]]
    roles: list[str]
    setups: dict[str, list[str]]
    tiers: list[int]
    caps: dict[str, Any]
    pools: dict[str, int]
    default_evidence: str
    expected: dict[tuple[str, str], int]
    item_rows: dict[str, list[Any]]
    flags: list[str] = field(default_factory=list)

    def header(self) -> dict[str, Any]:
        return {
            "version": FORMAT, "trio": self.trio, "classes": list(self.classes), "level": self.level,
            "data_release": self.data_release, "game_patch": self.game_patch, "rules_version": self.rules_version,
        }  # fmt: skip

    def race_index(self) -> dict[str, int]:
        return {code: n for n, (code, _) in enumerate(self.races)}

    def legal_races(self) -> tuple[str, ...]:
        """The races that can be created at character creation, **sorted**. A set of them would be handed out in the order of the
        string hashes of the process, which is another one for every process, and whatever came to depend on that order would write
        another file on another run (tests/test_precompute_determinism.py runs the flip notes under several hash seeds)."""
        return tuple(sorted(code for code, ok in self.races if ok))


def _rounded(value: float) -> float:
    number = round(value, 2)
    return 0.0 if number == 0 else number  # never "-0.0"


def _item_table(layout: Layout, keys: set[str]) -> tuple[list[list[Any]], dict[str, int]]:
    ordered = sorted(keys)
    return [layout.item_rows[key] for key in ordered], {key: n for n, key in enumerate(ordered)}


def shard_doc(
    layout: Layout, evidence: str, buffs: str, results: Mapping[Any, Mapping[str, Any]],
    bases: Mapping[tuple[str, str, str], float],
) -> dict[str, Any]:
    """The shard of ``(evidence, buffs)`` from the chunk documents ``results`` (``{chunk key: document}``).

    ``bases`` is the value of the naked character, by ``(race, role, buffs)``, for the gain."""
    race_at = layout.race_index()
    role_at = {role: n for n, role in enumerate(layout.roles)}
    rows = []
    for key, doc in results.items():
        if key.evidence == evidence and key.buffs == buffs:
            rows.extend((race_at[r["race"]], role_at[key.role], key.tier, layout.setups[key.role].index(key.setup), key, r) for r in doc["rows"])
    rows.sort(key=lambda row: row[:4])
    kept_first = sum(1 for *_, row in rows if row.get("tie") == "kept-first")
    played = {(key.role, key.setup) for _, _, _, _, key, _ in rows}  # a level can have fewer setups than another (the strict pool has no shield)
    worn = {k for *_, row in rows for k in row["kit"] if k is not None}
    items, item_at = _item_table(layout, worn)
    kits: dict[tuple[int, ...], int] = {}
    totals: dict[tuple[int, ...], int] = {}
    buff_sets: dict[tuple[int, ...], int] = {}
    scenarios = []
    for _, _, _, _, key, row in rows:
        kit = tuple(item_at[k] if k is not None else -1 for k in row["kit"])
        total = tuple(row["totals"])
        gain = row["F"] - bases[(row["race"], key.role, buffs)]
        scenarios.append([
            row["race"], key.role, key.tier, key.setup, kits.setdefault(kit, len(kits)), _rounded(row["F"]), _rounded(gain),
            totals.setdefault(total, len(totals)), buff_sets.setdefault(tuple(row["buffs"]), len(buff_sets)), row["haste"],
        ])  # fmt: skip
    return {
        **layout.header(), "evidence": evidence, "buffs": buffs, "solver": {**layout.solver, "kept_first": kept_first},
        "build_options": dict(layout.build_options), "assumptions": dict(layout.assumptions), "flags": list(layout.flags), "partial": len(rows) != layout.expected[(evidence, buffs)], "pool": layout.pools[evidence],
        "races": [{"code": code, "legal": legal} for code, legal in layout.races], "roles": list(layout.roles),
        "setups": {role: [s for s in layout.setups[role] if (role, s) in played] for role in layout.roles}, "tiers": list(layout.tiers),
        "caps": layout.caps, "places": list(PLACES), "items_keys": list(ITEM_KEYS), "items": items,
        "kits": [list(kit) for kit in kits], "totals_keys": list(TOTALS_KEYS), "totals": [list(t) for t in totals],
        "buff_sets": [list(ids) for ids in buff_sets], "scenarios": scenarios,
    }  # fmt: skip


def runnerup_name(role: str) -> str:
    """The name of a role's runner-up file, relative to the folder of the trio: ``runnerups/balanced.json``."""
    return f"{RUNNERUP_DIR}/{role}.json"


def _runnerup_header(layout: Layout) -> dict[str, Any]:
    return {
        **layout.header(), "evidence": layout.default_evidence, "buffs": "own",
        "evidence_fallback": layout.default_evidence != "strict",
    }  # fmt: skip


def runnerup_doc(layout: Layout, role: str, chunk_docs: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    """The runner-up file of one ``role`` from its runner-up chunk documents by tier (``{tier: document}``): every tier of the run in one file,
    with one item table. The tiers of ``chunk_docs`` are those of the run (:attr:`Layout.tiers`): a role with a tier fewer or more is a ``ValueError``,
    since the file would not be the file of the run's scope."""
    if sorted(chunk_docs) != list(layout.tiers):
        raise ValueError(
            f"the runner-ups of the {role} role are for the tiers {sorted(chunk_docs)}, and the scope of the run is {list(layout.tiers)}: "
            "the file of a role holds every tier of the run, and no other"
        )
    race_at = layout.race_index()
    entries = [
        (tier, view) for tier in layout.tiers for view in sorted(chunk_docs[tier]["views"], key=lambda view: race_at[view["race"]])
    ]  # fmt: skip
    keys = {key for _, view in entries for place in view["places"] for key, _ in place}
    items, item_at = _item_table(layout, keys)
    rows = [
        [tier, view["race"], view["setup"], [[[item_at[key], _rounded(delta)] for key, delta in place] for place in view["places"]]]
        for tier, view in entries
    ]  # fmt: skip
    return {
        **_runnerup_header(layout), "role": role, "tiers": list(layout.tiers), "places": list(PLACES), "items_keys": list(ITEM_KEYS),
        "items": items, "views": rows,
    }  # fmt: skip


def runnerup_texts(layout: Layout, chunk_docs: Mapping[tuple[str, int], Mapping[str, Any]]) -> dict[str, str]:
    """The runner-up files and their index, as ``{name: text}`` (names from :func:`runnerup_name`, then ``runnerups/index.json``), from the
    runner-up chunk documents ``{(role, tier): document}``: one file for each role, with every tier of the run in it.

    The index lists each file with the size and SHA-256 of the text as it will be written (UTF-8, ``render``'s own newlines), in order of
    role. No documents give no texts, not even an index."""
    role_at = {role: n for n, role in enumerate(layout.roles)}
    by_role: dict[str, dict[int, Mapping[str, Any]]] = {}
    for (role, tier), doc in chunk_docs.items():
        by_role.setdefault(role, {})[tier] = doc
    texts: dict[str, str] = {}
    files = []
    for role in sorted(by_role, key=lambda role: role_at[role]):
        text = render(runnerup_doc(layout, role, by_role[role]))
        data = text.encode("utf-8")
        texts[runnerup_name(role)] = text
        files.append({
            "file": f"{role}.json", "role": role, "tiers": list(layout.tiers), "bytes": len(data), "gzip": gzip_size(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })  # fmt: skip
    if files:
        texts[f"{RUNNERUP_DIR}/index.json"] = render({**_runnerup_header(layout), "files": files})
    return texts


def default_race(values: Mapping[str, float], legal: Collection[str], order: Sequence[str]) -> dict[str, Any] | None:
    """The default race: the creation-legal race with the highest value, the runner-up and the margin.

    ``values`` is the value of each race, ``legal`` the creation-legal ones (only asked about, never listed: pass
    :meth:`Layout.legal_races`) and ``order`` the display order, which decides a tie. A race that cannot be created never wins,
    whatever its value. None when no legal race has a value; the runner-up and the margin are None when only one does."""
    ranked = sorted((race for race in order if race in legal and race in values), key=lambda race: (-values[race], order.index(race)))
    if not ranked:
        return None
    if len(ranked) == 1:
        return {"race": ranked[0], "runner_up": None, "margin": None}
    return {"race": ranked[0], "runner_up": ranked[1], "margin": values[ranked[0]] - values[ranked[1]]}


def defaults_doc(
    layout: Layout, *, view: Mapping[str, Any], per_race: Mapping[str, tuple[float, str]], strict_empty: bool,
    robustness: str, flip_notes: Sequence[str] = (),
) -> dict[str, Any]:
    """``defaults.json``: ``per_race`` maps a race to its value and best setup in the default view."""
    order = [code for code, _ in layout.races]
    choice = default_race({race: value for race, (value, _) in per_race.items()}, layout.legal_races(), order)
    doc = {
        **layout.header(), "view": dict(view), "strict_pool_empty": strict_empty,
        "race": choice["race"] if choice else None, "runner_up_race": choice["runner_up"] if choice else None,
        "margin": None if not choice or choice["margin"] is None else _rounded(choice["margin"]),
        "F": _rounded(per_race[choice["race"]][0]) if choice else None,
        "setup": per_race[choice["race"]][1] if choice else None,
        "races": [
            {"race": code, "legal": ok, "F": _rounded(per_race[code][0]), "setup": per_race[code][1]}
            for code, ok in layout.races if code in per_race
        ],
        "flip_notes": list(flip_notes), "robustness": robustness,
    }  # fmt: skip
    return doc


def robust_doc(layout: Layout, race: str, labels: Mapping[str, Mapping[int, Mapping[str, str]]]) -> dict[str, Any]:
    """``robust.json``: ``labels[role][tier]`` maps a place to ``robust`` or a label, at the default race."""
    tiers = sorted({tier for by_tier in labels.values() for tier in by_tier})
    return {
        **layout.header(), "race": race, "tiers": tiers,
        "roles": {role: {str(tier): dict(by_tier[tier]) for tier in sorted(by_tier)} for role, by_tier in labels.items()},
    }  # fmt: skip


# ---- the size budget ---------------------------------------------------------------------------------------------


def gzip_size(data: bytes) -> int:
    """The bytes of ``data`` gzipped at level 9."""
    return len(gzip.compress(data, 9, mtime=0))


def check_budget(name: str, data: bytes) -> list[str]:
    """The ways a shard file of the text ``data`` is over its budget (see the module docstring); empty when it fits.

    Each text starts with ``name``, so a caller can list them as violations."""
    problems = []
    raw = len(data)
    if raw > SHARD_RAW_LIMIT:
        problems.append(f"{name} is {raw:,} bytes raw, over the {SHARD_RAW_LIMIT:,}-byte budget")
    packed = gzip_size(data)
    if packed > SHARD_GZIP_LIMIT:
        problems.append(f"{name} is {packed:,} bytes gzip, over the {SHARD_GZIP_LIMIT:,}-byte budget")
    return problems


# ---- invariants ------------------------------------------------------------------------------------------------


def check_invariants(
    values: Mapping[tuple[str, str, str, str, int, str], float], bases: Mapping[tuple[str, str, str], float], *, slack: float = 0.0
) -> list[str]:
    """The violations of what must hold across scenarios (a list of texts; empty is good).

    ``values`` maps ``(evidence, buffs, role, setup, tier, race)`` to the value of the best kit and ``bases`` maps
    ``(race, role, buffs)`` to the naked character's value. The best kit is never worth less than:

    * the same scenario one tier lower (every item only grows, and gets lighter);
    * the same scenario with strict evidence instead of wiki (the strict pool is part of the wiki pool);
    * the same scenario with own buffs instead of group buffs (the group set offers every own buff);
    * the empty kit (it is always allowed).

    A shortfall of a few float units is no violation. ``slack`` is an absolute amount more that a value may fall short by: the check of a release
    reads the values of the shards, which keep two decimals (a value and the same value from another solve can round a hundredth apart), and gives
    the slack of that rounding."""
    problems: list[str] = []

    def short(low: float, high: float) -> bool:
        return low < high - INVARIANT_TOLERANCE * max(1.0, abs(high)) - slack

    def add(text: str) -> None:
        if len(problems) < INVARIANT_LIMIT:
            problems.append(text)

    by_tier: dict[tuple, list[tuple[int, float]]] = {}
    for key, value in sorted(values.items()):
        evidence, buffs, role, setup, tier, race = key
        by_tier.setdefault((evidence, buffs, role, setup, race), []).append((tier, value))
        if (race, role, buffs) in bases and short(value, bases[(race, role, buffs)]):
            add(f"below the empty kit: {key} is worth {value!r}, the naked character {bases[(race, role, buffs)]!r}")
        if evidence == "strict" and ("wiki", buffs, role, setup, tier, race) in values:
            wiki = values[("wiki", buffs, role, setup, tier, race)]
            if short(wiki, value):
                add(f"strict above wiki: {key} is worth {value!r}, with wiki evidence {wiki!r}")
        if buffs == "own" and (evidence, "group", role, setup, tier, race) in values:
            group = values[(evidence, "group", role, setup, tier, race)]
            if short(group, value):
                add(f"own above group buffs: {key} is worth {value!r}, with group buffs {group!r}")
    for key, series in by_tier.items():
        for (lower, low_value), (upper, high_value) in zip(series, series[1:]):
            if short(high_value, low_value):
                add(f"value falls with the tier: {key} is worth {low_value!r} at +{lower} and {high_value!r} at +{upper}")
    return problems


# ---- writing -------------------------------------------------------------------------------------------------


def write_files(directory: Path, docs: Mapping[str, Mapping[str, Any] | str]) -> list[Path]:
    """Write the result files ``docs`` (``{file name: document or text}``) into ``directory``, and remove the result files of
    an earlier run that this one does not write. Returns the paths written, in the order of ``docs``.

    A name may start with ``runnerups/``. That folder is written first, all or nothing with its ``index.json`` last, then the
    files of the folder of the trio, all or nothing with ``defaults.json`` last. Removed afterwards: a shard, ``robust.json``
    or ``defaults.json`` that is not in ``docs``, the old ``runnerups.json``, and the runner-up files that are not in
    ``docs`` (the folder too when it is left empty). A bundle of the engine (``engine-l<level>.json``) of another level than the
    one written is a stale result file too."""
    folders: dict[str, dict[str, str]] = {"": {}}
    for name, doc in docs.items():
        folder, _, leaf = name.rpartition("/")
        folders.setdefault(folder, {})[leaf] = doc if isinstance(doc, str) else render(doc)
    for folder, texts in folders.items():
        if folder:
            (directory / folder).mkdir(parents=True, exist_ok=True)
            commit_files(directory / folder, texts, last="index.json")
    commit_files(directory, folders[""], last="defaults.json")
    for name in (*OUTPUT_NAMES, *LEGACY_NAMES):
        if name not in docs:
            (directory / name).unlink(missing_ok=True)
    for path in directory.glob(f"{ENGINE_PREFIX}*.json"):
        if path.name not in docs:
            path.unlink()
    runnerups = directory / RUNNERUP_DIR
    if runnerups.is_dir():
        for path in runnerups.glob("*.json"):
            if f"{RUNNERUP_DIR}/{path.name}" not in docs:
                path.unlink()
        if not any(runnerups.iterdir()):
            runnerups.rmdir()
    return [directory / name for name in docs]
