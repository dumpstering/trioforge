"""The scenario grid, the pool of a trio and the work of one chunk.

The grid
========

A scenario is ``(race, role, tier, evidence, buffs, setup)`` for one trio at the current level. :func:`scenarios` lists
them in a fixed order: evidence (``strict``, ``wiki``), buffs (``own``, ``group``), the roles the trio is offered
(:func:`trioforge.model.roles.roles_for`), each role's weapon setups
(:func:`trioforge.model.weapons.setups_for`), tiers 0 to 10 and the playable races. A combination a role does not play
(Melee with a shield, say) is never in the list, so it can never be offered.

The weapon setups follow the solve pool of each evidence level: the shield setup is in the grid of a level only when the
pool of that level has a shield that a class of the trio can wear (:func:`shield_pool`). The strict pool is a part of the
wiki pool, so the wiki level can have the setup where the strict level has not (a strict pool that is empty, or holds no
shield, as it does until such a shield has been seen in game), and a strict view is never solved with an empty off hand.
For PAL/MNK/BER with a shield in both pools that is 15 races x 8 role-setup pairs x 11 tiers x 2 evidence x 2 buffs = 5,280
scenarios; with no shield in the strict pool the strict level has 6 pairs, not 8, and the grid 4,620.

A **chunk** is the work of one view: all the races of one ``(evidence, buffs, role, setup, tier)``. The pool and the weapon
setup are the same for every race of a view, but the pruning is not quite: it leaves out an item that the race of the profile
cannot wear, and an item that only some races wear can drop another item that the others have to keep. So a chunk prunes
once for each **set of race-only items a race can wear** (:func:`solve_chunk`): the races that wear the same ones share a pool.

The pool
========

:func:`select_items` takes the catalog's items and keeps, for one trio, the wearable ones that can be in a best-in-slot
kit: evidence level ``strict`` or ``wiki``, not temporary or taken by a quest on hand-in (``not-for-bis``), listing a slot
the model has, and wearable by a class of the trio. Deity-locked items stay in the list (flagged by their ``deity``)
because runner-ups show them with a badge; the solve pools leave them out (:meth:`Context.pool`). The strict level is the
catalog's own plus the private seen flags: a seen item is strict unless a patch or research removal hides it (the same
rule as :func:`trioforge.data.evidence.classify`).

The work of a chunk
===================

:class:`Context` is built once per process: the tables, the two resolved buff sets (the trio's own buffs; own plus the
13 group buffs), the item vectors at each tier. :func:`solve_chunk` builds a profile, a model and a canonical solve for
each race and **checks every answer** before it is kept: the kit must be legal (:func:`check_kit`: slots, classes, races,
deity, Lore, the hand rules of the setup, a two-hander with an empty off hand) and its value, recomputed by the exact
evaluator from the item keys, must be the solver's value, and **the model's own objective for the kit must be that value too,
in both directions** within the solver's exactness tolerance (the solver itself refuses only a model that overstates a kit,
so a model that understated its optimum would pass without this). A failure is an
:class:`~trioforge.solver.solve.ExactnessError` or a :class:`ScenarioError`, and the run stops. Time limits are never used:
every solve is called with the model alone. The builder options of every model and of the pruning are one object
(:data:`BUILD_OPTIONS`); it and the solver settings are recorded in the shards (:func:`build_info`, :func:`solver_info`) and
in the fingerprint of the chunk files, so a change of either redoes the chunks.

Pruning is trusted only as far as it is checked, and two checks look for a loss of value. Each chunk **audits one race**,
chosen by a rotation that visits every race over the chunks of a run (:func:`audit_race`): the race is solved again with the
whole pool, no pruning, and must come out at the very value the pruned solve found. And :func:`runnerup_chunk` values every
swap of an item that anyone can wear, which can never beat the best kit: a swap that does is a **violation** and stops the
run (an item the pruning wrongly dropped, say, is such a swap).

The tie stage may keep the first stage's kit (``Solution.tie_stage`` is ``"kept-first"``: the second stage's kit was worth
less by the exact evaluator, so the proven optimum stands). That is no failure: the row says so (``"tie"``), the shard counts
such rows in ``solver.kept_first`` and the run lists the count in its notes. A canonical run whose solver reports no tie stage
at all is refused.

A **profile** is made with the solve pool of its evidence level (``make_profile(items=...)``), so that its weapon setups follow
the pool: the shield setup is there only if the pool has a shield the race can wear. The model leaves out an item whose race
list excludes the race, and so do the runner-ups and :func:`check_kit`.

:func:`runnerup_chunk` computes the runner-ups of a view: for every one of the 22 places of the kit, the items that could
stand there instead, **the rest of the kit held fixed**, each swap valued by the exact evaluator
(:func:`trioforge.model.formulas.evaluate`). A place keeps the three best swaps of items that anyone can wear and at most
one swap of a deity-locked item, which is kept only when it beats the best of the three. The candidates come from the whole
pool of the default evidence level plus its deity-locked items, never from the pruned pool: pruning is exact only for the
optimum.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import re
import subprocess
import time
import traceback
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import highspy

from trioforge.classes import CLASS_CODES
from trioforge.data import races as races_module
from trioforge.data.jsonio import load_strict
from trioforge.model import formulas as fm
from trioforge.model import tables as tables_module
from trioforge.model import weapons as wp
from trioforge.model.buffs import group_preset, own_buffs, resolve
from trioforge.model.items import SLOT_GROUPS, SLOT_INSTANCES, ItemVec, at_tier
from trioforge.model.profile import make_profile
from trioforge.model.roles import roles_for
from trioforge.precompute import shards
from trioforge.solver import _highs
from trioforge.solver import solve as solver_solve
from trioforge.solver.model import BuildOptions, build_milp, eval_buff_totals
from trioforge.solver.prune import prune
from trioforge.solver.solve import ExactnessError

__all__ = [
    "BUFFS",
    "BUILD_OPTIONS",
    "EVIDENCE",
    "TIERS",
    "ChunkKey",
    "Config",
    "Context",
    "Meta",
    "RobustScenario",
    "RunnerupInput",
    "Scenario",
    "ScenarioError",
    "Selection",
    "audit_race",
    "check_kit",
    "chunk_key",
    "code_files",
    "chunks",
    "build_info",
    "creation_legal",
    "find_catalog",
    "init_worker",
    "load_inputs",
    "parse_trio",
    "pool_dicts",
    "race_order",
    "robust_scenario",
    "run_order",
    "run_task",
    "runnerup_chunk",
    "scenarios",
    "select_items",
    "shield_pool",
    "solve_chunk",
    "solver_info",
    "totals_vector",
    "trio_slug",
]

EVIDENCE = ("strict", "wiki")
BUFFS = ("own", "group")
TIERS = tuple(range(11))
CODE_VERSION = 1  # bump when the format of a chunk changes: every finished chunk is then redone
#: the source whose content decides what a chunk holds (the model, the solver, this module and what they read: the buff engine
#: reads ``LIMIT_SPA`` from the client spells, the tables the race table): a change in any of it redoes the chunks, so a fixed
#: solver never serves answers of the old one. Line endings do not count. A test follows the imports of these files and fails
#: for a module that is neither here nor explained there.
CODE_DIRS = ("model", "solver")
CODE_FILES = ("rules.py", "classes.py", "precompute/grid.py", "sources/client_spells.py", "data/races.py")
#: the builder options of every model of a run (and of its pruning); the shards record them
BUILD_OPTIONS = BuildOptions()

#: the slots of an item that the model has a place for (``ANY`` is a place, never a slot of an item)
WEARABLE_SLOTS = frozenset(name for name, _ in SLOT_GROUPS)
HANDS = ("PRIMARY", "SECONDARY")
SECONDARY_INDEX = SLOT_INSTANCES.index("SECONDARY")
REMOVAL_CODES = frozenset({"removed-by-patch", "removed-by-research"})
RUNNER_UPS = 3  # swaps kept for each place among the items that anyone can wear
DEITY_RUNNER_UPS = 1  # and the locked swaps kept besides them
EXACT_TOLERANCE = 1e-9  # relative: the re-check of a kit's value


class ScenarioError(RuntimeError):
    """A scenario's answer failed a check (not optimal, an illegal kit, a tie stage that did not finish)."""


# ---- trios and races ---------------------------------------------------------------------------------------------------


def parse_trio(trio: str | Iterable[str]) -> tuple[str, ...]:
    """Three class codes in class-id order from ``"pal-mnk-ber"`` (any case and order) or a sequence of codes.

    Raises ``ValueError`` for anything that is not three different classes."""
    parts = trio.upper().split("-") if isinstance(trio, str) else [str(code).upper() for code in trio]
    if len(parts) != 3 or len(set(parts)) != 3 or any(code not in CLASS_CODES for code in parts):
        raise ValueError(f"a trio is three different class codes from {' '.join(CLASS_CODES)}, joined by '-': not {trio!r}")
    return tuple(sorted(parts, key=CLASS_CODES.index))


def trio_slug(trio: Sequence[str]) -> str:
    """``"pal-mnk-ber"`` for ``("PAL", "MNK", "BER")``: the folder, the page and the URL of a trio."""
    return "-".join(code.lower() for code in trio)


def creation_legal(race: str, trio: Sequence[str], tables: Any) -> bool:
    """Whether ``race`` can start a character of ``trio``: a race limits only the first class, so one class of the trio
    must be among the race's primaries. A disputed primary (Kerran Druid) does not count."""
    primaries = races_module.legal_primaries(race, data=tables.races)
    return any(code in primaries for code in trio)


def race_order(trio: Sequence[str], tables: Any) -> list[tuple[str, bool]]:
    """``[(race, creation_legal)]`` of the playable races: the legal ones first, each group in the table's order."""
    codes = [entry["code"] for entry in tables.races["races"] if entry["active"]]
    legal = [(code, True) for code in codes if creation_legal(code, trio, tables)]
    return legal + [(code, False) for code in codes if not creation_legal(code, trio, tables)]


# ---- the grid ---------------------------------------------------------------------------------------------------------


class Scenario(NamedTuple):
    race: str
    role: str
    tier: int
    evidence: str
    buffs: str
    setup: str


class ChunkKey(NamedTuple):
    """One view: every race of it is solved in one chunk."""

    evidence: str
    buffs: str
    role: str
    setup: str
    tier: int


def chunk_key(scenario: Scenario) -> ChunkKey:
    return ChunkKey(scenario.evidence, scenario.buffs, scenario.role, scenario.setup, scenario.tier)


def _pick(name: str, wanted: Iterable[Any] | None, allowed: Sequence[Any]) -> list[Any]:
    """The members of ``allowed`` named in ``wanted``, in the order of ``allowed``; ``ValueError`` for an unknown one."""
    if wanted is None:
        return list(allowed)
    wanted = list(wanted)
    for value in wanted:
        if value not in allowed or isinstance(value, bool):
            raise ValueError(f"unknown {name} {value!r}; use one of {', '.join(map(str, allowed))}")
    return [value for value in allowed if value in wanted]


def scenarios(
    trio: Sequence[str], tables: Any, rules: Any, *, races: Iterable[str] | None = None, roles: Iterable[str] | None = None,
    tiers: Iterable[int] | None = None, evidence: Iterable[str] | None = None, buffs: Iterable[str] | None = None,
    items: Iterable[ItemVec] | Mapping[str, Iterable[ItemVec]] | None = None,
) -> list[Scenario]:
    """Every scenario of ``trio`` at the current level, in the fixed order of the module docstring.

    The keyword arguments narrow the grid (a test or a quick look); a value that does not exist, or a role the trio is
    not offered, is a ``ValueError``. The order does not depend on the order of the arguments. ``items`` are the solve
    pools, as item vectors, that decide whether the shield setup is in the grid: it is there only if the pool has a shield
    that a class of the trio can wear (:func:`trioforge.model.weapons.shield_available`). A mapping gives the pool of
    each evidence level (``{"strict": [...], "wiki": [...]}``; a level that is asked for and has no entry is a
    ``ValueError``), a list gives one pool to every level, and None assumes a shield, which is the grid of the design
    (5,280 scenarios for PAL/MNK/BER)."""
    codes = parse_trio(trio)
    level = rules.get("level.current")
    all_races = [entry["code"] for entry in tables.races["races"] if entry["active"]]
    chosen_races = _pick("race", races, all_races)
    chosen_roles = _pick("role", roles, roles_for(codes))
    chosen_tiers = _pick("tier", tiers, TIERS)
    chosen_evidence = _pick("evidence level", evidence, EVIDENCE)
    chosen_buffs = _pick("buff set", buffs, BUFFS)
    given = items if items is None or isinstance(items, Mapping) else list(items)  # a list is made once: items may be a generator

    def pool_of(kind: str) -> list[ItemVec] | None:
        if given is None:
            return None
        if isinstance(given, Mapping):
            if kind not in given:
                raise ValueError(f"no item pool is given for the {kind} evidence level; give one for each level asked for")
            return list(given[kind])
        return given

    plan = []
    for kind in chosen_evidence:
        pool = pool_of(kind)
        for buff_set in chosen_buffs:
            for role in chosen_roles:
                for setup in wp.setups_for(codes, role, tables, level=level, items=pool):
                    for tier in chosen_tiers:
                        plan.extend(Scenario(race, role, tier, kind, buff_set, setup) for race in chosen_races)
    return plan


def chunks(plan: Iterable[Scenario]) -> dict[ChunkKey, list[str]]:
    """The scenarios grouped by view: ``{chunk key: [races]}`` in the order the views first appear."""
    grouped: dict[ChunkKey, list[str]] = {}
    for scenario in plan:
        grouped.setdefault(chunk_key(scenario), []).append(scenario.race)
    return grouped


def run_order(keys: Iterable[ChunkKey], roles: Sequence[str]) -> list[ChunkKey]:
    """The order the chunks are worked in: the heavy ones first (wiki evidence, low tiers, group buffs), so that the
    processes stay busy to the end. A fixed order, so that ``--limit`` always takes the same chunks."""
    def weight(key: ChunkKey) -> tuple:
        return (key.evidence != "wiki", key.tier, key.buffs != "group", roles.index(key.role), key.setup)

    return sorted(keys, key=weight)


# ---- the catalog ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Selection:
    """The items a trio can use: ``items`` (catalog dicts sorted by key, deity-locked ones included), ``levels``
    (item key to its effective evidence level, ``strict`` or ``wiki``) and the count of seen keys the catalog lacks."""

    items: list[dict[str, Any]]
    levels: dict[str, str]
    unknown_seen: int = 0


def _effective_level(item: Mapping[str, Any], seen: frozenset[str]) -> str:
    level = item["evidence"]["level"]
    if level == "strict":
        return level
    if item["key"] in seen and not any(reason["code"] in REMOVAL_CODES for reason in item["evidence"]["reasons"]):
        return "strict"  # a sighting beats the wiki signals, never a patch or research removal
    return level


def select_items(items: Iterable[Mapping[str, Any]], trio: Sequence[str], seen: Iterable[str] = ()) -> Selection:
    """The usable items of ``trio`` (see the module docstring); ``seen`` is the private list of item keys seen in game."""
    seen = frozenset(seen)
    codes = set(parse_trio(trio))
    catalog = list(items)
    chosen: list[dict[str, Any]] = []
    levels: dict[str, str] = {}
    for item in catalog:
        level = _effective_level(item, seen)
        if level not in ("strict", "wiki"):
            continue
        if any(reason["code"] == "not-for-bis" for reason in item["evidence"]["reasons"]):
            continue
        if not WEARABLE_SLOTS & set(item["slots"]):
            continue
        if "ALL" not in item["classes"] and not codes & set(item["classes"]):
            continue
        chosen.append(dict(item))
        levels[item["key"]] = level
    chosen.sort(key=lambda item: item["key"])
    known = {item["key"] for item in catalog}
    return Selection(chosen, levels, len(seen - known))


def pool_dicts(selection: Selection, evidence: str) -> list[dict[str, Any]]:
    """The catalog dicts of the solve pool of an evidence level: ``strict`` is the strict items, ``wiki`` the strict and
    the wiki items; deity-locked items are never in a solve pool."""
    wanted = ("strict",) if evidence == "strict" else ("strict", "wiki")
    return [item for item in selection.items if selection.levels[item["key"]] in wanted and item["deity"] is None]


def shield_pool(config: Config, rules: Any, evidence: str = "wiki") -> list[ItemVec]:
    """The shields of the solve pool of an evidence level as item vectors at +0: what :func:`scenarios` needs to know to
    decide whether the level has the shield setup. ``strict`` is the strict items; ``wiki`` (the default) the strict and the
    wiki items, the largest pool. No deity-locked item is in a solve pool. Only items typed as a shield are read, so an
    item that is no shield, whatever else is wrong with it, is left for the workers to report."""
    if evidence not in EVIDENCE:
        raise ValueError(f"unknown evidence level {evidence!r}; use one of {', '.join(EVIDENCE)}")
    wanted = ("strict",) if evidence == "strict" else ("strict", "wiki")
    return [
        at_tier(item, 0, rules)
        for item in config.items
        if item["deity"] is None and config.levels[item["key"]] in wanted and (item.get("item_type") or "").lower() == "shield"
    ]


def find_catalog() -> Path | None:
    """The catalog file: ``$TRIOFORGE_CATALOG``, else ``derived/catalog.json`` of this checkout, else the one of the main
    checkout (a worktree keeps the built data there); None when none exists."""
    candidates = []
    if os.environ.get("TRIOFORGE_CATALOG"):
        candidates.append(Path(os.environ["TRIOFORGE_CATALOG"]))
    candidates.append(tables_module.REPO / "derived" / "catalog.json")
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=tables_module.REPO, capture_output=True,
            text=True, timeout=30, check=True,
        ).stdout.strip()
        candidates.append(Path(common).parent / "derived" / "catalog.json")
    except (OSError, subprocess.SubprocessError):
        pass
    return next((path for path in candidates if path.is_file()), None)


# ---- what the shards record about how the answers were made ---------------------------------------------------------


def solver_info(canonical: bool) -> dict[str, Any]:
    """The solver settings of a run as the shards record them: the HiGHS options of :mod:`trioforge.solver._highs` that can
    change an answer (presolve, the gaps and tolerances, threads, the random seed), no time limit, whether ties were resolved
    by the tie stage (``canonical``) and the HiGHS version and source revision."""
    options = {name: value for name, value in _highs.OPTIONS.items() if name != "output_flag"}
    engine = highspy.Highs()
    return {"canonical": canonical, **options, "time_limit": None, "highs": engine.version(), "revision": engine.githash()}


def build_info() -> dict[str, Any]:
    """The builder options of a run as the shards record them: ``any_rule``, which items fit the Any places, and
    ``haste_assumed``, null while the haste of the weapon index is worked out for each scenario (its value is in the row).
    The other options of :class:`~trioforge.solver.model.BuildOptions` (the test hook, the legacy objective and the owned-item
    options of the Upgrade tab) never apply to a shard and are not recorded; :data:`BUILD_OPTIONS` sets none of them."""
    assert BUILD_OPTIONS.mutation is None and BUILD_OPTIONS.legacy is None
    options = dataclasses.asdict(BUILD_OPTIONS)
    return {name: options[name] for name in ("any_rule", "haste_assumed")}


# ---- the inputs of a run -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """Everything a worker process needs, in one picklable record (the tables are read again in each process).

    ``items`` are the catalog dicts of the trio's :class:`Selection`, ``levels`` their effective evidence levels,
    ``spells`` the beneficial-spell file of the level, ``canonical`` whether ties are resolved by the second stage,
    ``fingerprint`` the hash of everything a result depends on, and ``default_evidence`` the evidence level of the default
    view: ``strict``, or ``wiki`` while the strict pool is empty."""

    trio: tuple[str, ...]
    level: int
    tables_root: str
    items: tuple[dict[str, Any], ...]
    levels: dict[str, str]
    spells: dict[str, Any]
    canonical: bool
    fingerprint: str
    default_evidence: str


@dataclass(frozen=True)
class Meta:
    """What the parent keeps for the files: the data release, the game patch date, the rules version, pool sizes."""

    data_release: str
    game_patch: str
    rules_version: str
    pool_sizes: dict[str, int]
    unknown_seen: int
    seen_count: int


def code_files() -> list[Path]:
    """The source files named by :data:`CODE_DIRS` and :data:`CODE_FILES`, in the fixed order they are hashed in."""
    root = Path(__file__).resolve().parents[1]
    return sorted(path for name in CODE_DIRS for path in (root / name).glob("*.py")) + [root / name for name in CODE_FILES]


def _code_hash() -> str:
    """The SHA-256 of the source files of :func:`code_files` (names and contents, line endings aside)."""
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in code_files():
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_inputs(
    trio: Sequence[str], *, catalog_path: str | os.PathLike[str], seen_path: str | os.PathLike[str] | None = None,
    tables_root: str | os.PathLike[str] | None = None, canonical: bool = True, code_hash: str | None = None,
) -> tuple[Config, Meta]:
    """Read the catalog, the tables' hashes and the spell file; return the :class:`Config` and :class:`Meta` of a run.

    ``code_hash`` is the hash of the code the chunks are made under (:func:`_code_hash`), for a caller that has hashed the source files already: the release build
    hashes them once, at its start, and every worker takes that value, so that a chunk is never stamped with a hash of files that were changed after the code that
    made it was loaded. None hashes the files now.

    Raises ``ValueError`` for a catalog that is not in the builder's form or a ``code_hash`` that is not a SHA-256, ``OSError`` for a file that cannot be read and
    :class:`trioforge.data.catalog.BuildError` for a bad seen-flags file."""
    from trioforge.data import catalog as catalog_module  # imported here: the module is heavy and only the parent needs it

    if code_hash is not None and not (isinstance(code_hash, str) and re.fullmatch(r"[0-9a-f]{64}", code_hash)):
        raise ValueError("the code hash must be a SHA-256, 64 lower-case hexadecimal digits")

    codes = parse_trio(trio)
    root = Path(tables_root) if tables_root is not None else tables_module.REPO
    tables = tables_module.load(root)
    rules = tables.rules
    level = rules.get("level.current")
    path = Path(catalog_path)
    document = load_strict(path)
    if not isinstance(document, dict) or not isinstance(document.get("items"), list) or not isinstance(document.get("version"), str):
        raise ValueError(f"{path.name}: not a catalog (an object with a version and a list of items)")
    for item in document["items"]:
        if not isinstance(item, dict) or "evidence" not in item or "key" not in item:
            raise ValueError(f"{path.name}: an item has no key or no evidence level (is this the catalog the builder writes?)")
    seen = catalog_module.load_seen_keys(seen_path) if seen_path is not None else frozenset()
    selection = select_items(document["items"], codes, seen)
    spells = load_strict(root / "derived" / "client" / f"spells-l{level}.json")
    strict_empty = not pool_dicts(selection, "strict")
    manifest = load_strict(root / "derived" / "client" / "manifest.json")
    dates = [entry["date"] for entry in manifest.get("inputs", []) if isinstance(entry.get("date"), str)]
    inputs = {
        "format": CODE_VERSION, "code": _code_hash() if code_hash is None else code_hash, "totals": list(shards.TOTALS_KEYS), "trio": codes, "level": level,
        "canonical": canonical,
        "catalog": _file_sha256(path),
        "seen": hashlib.sha256("\n".join(sorted(seen)).encode()).hexdigest() if seen_path is not None else None,
        "files": {
            name: _file_sha256(root / name)
            for name in ("rules/rules.json", "rules/races.json", "derived/client/basedata.json",
                         "derived/client/acmitigation.json", "derived/client/skillcaps.json",
                         f"derived/client/spells-l{level}.json")
        },  # fmt: skip
        "solver": solver_info(canonical), "build": build_info(),
    }
    fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()
    config = Config(
        trio=codes, level=level, tables_root=str(root), items=tuple(selection.items), levels=dict(selection.levels),
        spells=spells, canonical=canonical, fingerprint=fingerprint, default_evidence="wiki" if strict_empty else "strict",
    )
    meta = Meta(
        data_release=f"data-{document['version']}", game_patch=max(dates, default=""), rules_version=rules.version,
        pool_sizes={kind: len(pool_dicts(selection, kind)) for kind in EVIDENCE}, unknown_seen=selection.unknown_seen,
        seen_count=len(seen),
    )
    return config, meta


# ---- checking an answer --------------------------------------------------------------------------------------------


def check_kit(
    kit: Sequence[ItemVec | None], setup: str | None, trio: Sequence[str], deity: str | None = None, race: str | None = None
) -> list[str]:
    """The faults of a kit as texts; an empty list is a legal kit.

    A kit has one entry for each of the 22 places. Every worn item must list its place (an Any place takes every item that
    fits some slot), be wearable by a class of the trio and, when the ``race`` of the wearer is given, by that race (an item
    that lists no races is for every race; an empty list is for none), and not be locked to a deity the wearer lacks; the hand
    places must follow the setup; a Lore item may be worn once; a two-hander leaves the off hand empty."""
    if len(kit) != len(SLOT_INSTANCES):
        return [f"a kit has {len(SLOT_INSTANCES)} places, not {len(kit)}"]
    problems = []
    classes = set(trio)
    lore: set[str] = set()
    for place, item in zip(SLOT_INSTANCES, kit):
        if item is None:
            continue
        if not item.classes & classes:
            problems.append(f"{item.key}: no class of the trio can wear it")
        if race is not None and item.races is not None and race not in item.races:
            problems.append(f"{item.key}: the {race} race cannot wear it")
        if item.deity is not None and (deity is None or deity not in item.deity):
            problems.append(f"{item.key}: locked to a deity ({', '.join(sorted(item.deity))})")
        if place == "ANY":
            fits = "ANY" in item.slots or bool(WEARABLE_SLOTS & item.slots)
        else:
            fits = place in item.slots
        if not fits:
            problems.append(f"{item.key}: does not fit {place}")
        elif place in HANDS and setup is not None and not wp.allowed_in_hand(item, place.lower(), setup):
            problems.append(f"{item.key}: the {setup} setup does not allow it in {place}")
        if item.lore:
            if item.key in lore:
                problems.append(f"{item.key}: a Lore item worn twice")
            lore.add(item.key)
    primary = kit[SLOT_INSTANCES.index("PRIMARY")]
    if primary is not None and primary.weapon is not None and primary.weapon.two_handed and kit[SECONDARY_INDEX] is not None:
        problems.append(f"{primary.key}: a two-hander with something in the off hand")
    return problems


def totals_vector(
    trio: Sequence[str], level: int, tables: Any, bands: Any, kit: Sequence[ItemVec | None], buff_totals: Mapping[str, Any],
    breakdown: fm.Breakdown,
) -> list[int]:
    """The totals of a kit as whole numbers, in the order of :data:`trioforge.precompute.shards.TOTALS_KEYS`: sheet AC, then HP, mana and END as the game's stat
    window prints them (:func:`trioforge.model.formulas.stat_window`), then the haste counted, ATK, the five resists and the
    three regens as the objective counts them, each with its fraction dropped."""
    gear = {key: sum(item.stats.get(key, 0) for item in kit if item is not None) for key in ("HP", "MANA", "END")}
    buff = {key: buff_totals.get(key, 0) for key in ("HP", "MANA", "END")}
    window = fm.stat_window(trio, level, breakdown.totals["attributes"], gear, buff, tables, bands)
    t = breakdown.totals
    values = [
        t["sheet"]["total"], window["HP"], window["MANA"], window["END"], t["haste"]["counted"], t["atk"],
        *(t["resists"][school]["counted"] for school in fm.SCHOOLS),
        *(t["regen"][kind]["counted"] for kind in ("HPREG", "MANAREG", "ENDREG")),
    ]  # fmt: skip
    assert len(values) == len(shards.TOTALS_KEYS)
    return [math.floor(value) for value in values]


# ---- the context of a process -------------------------------------------------------------------------------------


class RunnerupInput(NamedTuple):
    """The kit of one race at the default assumptions, from which its runner-ups are swapped."""

    race: str
    setup: str
    kit: tuple[str | None, ...]
    buffs: tuple[int, ...]
    haste: int


class Context:
    """Tables, buff sets and item vectors of one process (built from a :class:`Config`)."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.trio = config.trio
        self.tables = tables_module.load(config.tables_root)
        self.rules = self.tables.rules
        own = own_buffs(self.trio, config.level, config.spells, self.rules)
        self.buffsets = {
            "own": resolve(own, self.rules),
            "group": resolve([*own, *group_preset(config.spells)], self.rules),
        }
        self._vecs: dict[int, dict[str, ItemVec]] = {}
        self._profiles: dict[tuple[str, str, str, str], Any] = {}

    def vecs(self, tier: int) -> dict[str, ItemVec]:
        """Every item of the trio at ``tier``, by key (deity-locked ones included)."""
        if tier not in self._vecs:
            self._vecs[tier] = {item["key"]: at_tier(item, tier, self.rules) for item in self.config.items}
        return self._vecs[tier]

    def pool(self, evidence: str, tier: int) -> list[ItemVec]:
        """The solve pool of an evidence level at ``tier``, sorted by key (no deity-locked item)."""
        wanted = ("strict",) if evidence == "strict" else ("strict", "wiki")
        vecs = self.vecs(tier)
        return [vecs[i["key"]] for i in self.config.items if self.config.levels[i["key"]] in wanted and i["deity"] is None]

    def pool_items(self, evidence: str) -> list[dict[str, Any]]:
        """The catalog items behind :meth:`pool`: a caller that builds them again under another rule, as a robustness variant
        does, needs the items and not the vectors."""
        wanted = ("strict",) if evidence == "strict" else ("strict", "wiki")
        return [i for i in self.config.items if self.config.levels[i["key"]] in wanted and i["deity"] is None]

    def candidates(self, evidence: str, tier: int) -> list[ItemVec]:
        """The runner-up candidates: the solve pool of ``evidence`` and its deity-locked items."""
        wanted = ("strict",) if evidence == "strict" else ("strict", "wiki")
        vecs = self.vecs(tier)
        return [vecs[i["key"]] for i in self.config.items if self.config.levels[i["key"]] in wanted]

    def profile(self, race: str, role: str, buffs: str, evidence: str) -> Any:
        """The profile of a race in a role, made once. It is given the solve pool of its evidence level, so that its weapon
        setups follow the pool: the shield setup is there only if the pool has a shield this race can wear. (Whether an item
        is a shield, its classes and its races do not change with the tier, so the pool is read at +0.)"""
        key = (race, role, buffs, evidence)
        if key not in self._profiles:
            self._profiles[key] = make_profile(
                race, self.trio, self.config.level, role, self.buffsets[buffs], None, self.tables, evidence=evidence,
                items=self.pool(evidence, 0),
            )
        return self._profiles[key]

    def empty_value(self, race: str, role: str, buffs: str) -> float:
        """The value of the naked character with its best buffs: the solve of an empty pool (the base of a gain)."""
        profile = self.profile(race, role, buffs, "wiki")
        solution = solver_solve.solve(build_milp(profile, [], None, self.buffsets[buffs], BUILD_OPTIONS))
        if solution.status != "optimal" or solution.F is None:
            raise ScenarioError(f"the empty kit of {race} {role} {buffs} did not solve to optimality")
        return solution.F


# ---- the work of one chunk -----------------------------------------------------------------------------------------


def _where(key: ChunkKey, race: str | None = None) -> str:
    text = f"{key.evidence} evidence, {key.buffs} buffs, {key.role} role, {key.setup} setup, +{key.tier}"
    return f"{text}, {race}" if race else text


def _solve_one(ctx: Context, key: ChunkKey, race: str, pruned: list[ItemVec]) -> tuple[dict[str, Any], float, float]:
    buffset = ctx.buffsets[key.buffs]
    profile = ctx.profile(race, key.role, key.buffs, key.evidence)
    started = time.perf_counter()
    milp = build_milp(profile, pruned, key.setup, buffset, BUILD_OPTIONS)
    built = time.perf_counter()
    solve = solver_solve.solve_canonical if ctx.config.canonical else solver_solve.solve
    solution = solve(milp)
    solved = time.perf_counter()
    if solution.status != "optimal":
        raise ScenarioError(f"the solver ended with status {solution.status!r}, not optimal (no time limit is set)")
    if ctx.config.canonical and solution.tie_stage not in ("applied", "kept-first"):
        raise ScenarioError(f"the solver did not run the tie stage (tie_stage is {solution.tie_stage!r}), so the kit is not canonical")
    # "kept-first" is no error: the tie stage's kit was worth less than the first stage's by the exact evaluator, so the
    # first stage's kit stands. It is the optimum; which of several equal kits it is was left to the solver (and is counted)
    kit = list(solution.kit)
    problems = check_kit(kit, key.setup, ctx.trio, race=race)
    if problems:
        raise ScenarioError("the kit is not legal: " + "; ".join(problems))
    vecs = ctx.vecs(key.tier)
    rebuilt = [vecs[item.key] if item is not None else None for item in kit]  # again, by key and tier
    totals = eval_buff_totals(buffset.totals(solution.buffs))
    exact = fm.evaluate(profile.eval_profile, rebuilt, totals, setup=key.setup, haste_assumed=milp.haste_assumed)
    value = float(exact.F)
    if abs(value - solution.F) > EXACT_TOLERANCE * max(1.0, abs(value)):
        raise ExactnessError(f"the solver's value {solution.F!r} and the evaluator's value {value!r} of the kit differ")
    # The model's own objective for the kit must be the evaluator's value, on whichever side it errs. The solver refuses only a
    # model that overstates its kit: it has to allow an objective below the value in general (a solve cut short, or the tie
    # stage, which minimizes a rank and leaves the continuous columns anywhere in its band). Here every solve ran to its end,
    # and the tie stage's band is 1e-7 relative, so an objective that falls short by more than the tolerance means that
    # the model is not exact, and the kit may not be the best there is.
    limit = solver_solve.EXACTNESS_TOLERANCE * max(1.0, abs(value))
    if solution.model_F is None or abs(solution.model_F - value) > limit:
        raise ExactnessError(
            f"the model's objective {solution.model_F!r} and the evaluator's value {value!r} of its kit differ by more than "
            f"{solver_solve.EXACTNESS_TOLERANCE:g} relative"
        )
    row = {
        "race": race, "F": solution.F, "kit": [item.key if item is not None else None for item in kit],
        "buffs": list(solution.buffs), "haste": milp.haste_assumed,
        "totals": totals_vector(ctx.trio, ctx.config.level, ctx.tables, profile.bands, kit, totals, exact),
        "nodes": solution.nodes, "tie": solution.tie_stage,
    }  # fmt: skip
    return row, built - started, solved - built


def _rotation(key: ChunkKey) -> int:
    """A number that depends on the view alone and is spread evenly over the views: where :func:`solve_chunk` starts when it
    is not told which race to audit."""
    return int.from_bytes(hashlib.sha256(repr(tuple(key)).encode()).digest()[:4], "big")


def audit_race(ctx: Context, key: ChunkKey, race: str, pool: Sequence[ItemVec], expected: float) -> dict[str, Any]:
    """Solve one race of a view again with the whole ``pool`` (no pruning) and require the value ``expected`` that the pruned
    solve found.

    The plain solver is enough: only the value is wanted, and the tie stage does not change it. A pruning that dropped an
    item some best kit needs makes the whole pool worth more than the pruned one, and a value that differs the other way means
    the two models disagree: either way it is a :class:`ScenarioError` and the run stops. Returns ``{"race", "F"}``, which
    the chunk keeps."""
    profile = ctx.profile(race, key.role, key.buffs, key.evidence)
    milp = build_milp(profile, pool, key.setup, ctx.buffsets[key.buffs], BUILD_OPTIONS)
    solution = solver_solve.solve(milp)
    if solution.status != "optimal" or solution.F is None:
        raise ScenarioError(f"the unpruned solve of {race} ended with status {solution.status!r}, not optimal (no time limit is set)")
    if abs(solution.F - expected) > EXACT_TOLERANCE * max(1.0, abs(expected)):
        raise ScenarioError(
            f"the unpruned solve of {race} is worth {solution.F!r} but the pruned solve found {expected!r}: "
            "the pruning changed the optimum"
        )
    return {"race": race, "F": solution.F}


def solve_chunk(ctx: Context, key: ChunkKey, races: Sequence[str], audit: int | None = None) -> dict[str, Any]:
    """Solve every race of one view and return the chunk document (without its fingerprint and checksum).

    Each race gets its own profile, model and canonical solve, on a pruned pool. The pruning depends on the race in one way:
    it leaves out the items the race cannot wear, and such an item can have dropped another that the other races need. So the
    pool is pruned once for each set of race-only items (items with a race list) that a race can wear, with the first race that
    has that set; the races that wear the same ones share the result.

    One race is then solved again without pruning (:func:`audit_race`): ``races[audit % len(races)]``, where ``audit`` is
    the place of the view in the run (the races rotate from view to view, so every race is audited many times over a run);
    without it, a number made from the view. The chunk keeps ``audit`` as ``{"race", "F"}``, or None for an empty pool."""
    started = time.perf_counter()
    pool = ctx.pool(key.evidence, key.tier)
    race_only = [item for item in pool if item.races is not None]
    pruned_pools: dict[frozenset[str], list[ItemVec]] = {}

    def pruned_for(race: str) -> list[ItemVec]:
        if not pool:
            return []
        wearable = frozenset(item.key for item in race_only if race in item.races)
        if wearable not in pruned_pools:
            profile = ctx.profile(race, key.role, key.buffs, key.evidence)
            pruned_pools[wearable] = prune(pool, profile, key.tier, key.setup, ctx.buffsets[key.buffs], BUILD_OPTIONS)
        return pruned_pools[wearable]

    rows, build_time, solve_time = [], 0.0, 0.0
    for race in races:
        try:
            row, built, solved = _solve_one(ctx, key, race, pruned_for(race))
        except Exception as error:
            error.add_note(f"at {_where(key, race)}")
            raise
        rows.append(row)
        build_time += built
        solve_time += solved
    audited = None
    if pool:
        race = races[(_rotation(key) if audit is None else audit) % len(races)]
        try:
            audited = audit_race(ctx, key, race, pool, next(row["F"] for row in rows if row["race"] == race))
        except Exception as error:
            error.add_note(f"at {_where(key, race)}")
            raise
    return {
        "format": 1, "kind": "scenarios", "key": key._asdict(), "pool": len(pool),
        "pruned": max(map(len, pruned_pools.values()), default=0), "audit": audited, "rows": rows,
        "timing": {
            "seconds": time.perf_counter() - started, "build": build_time, "solve": solve_time, "scenarios": len(rows),
            "kept_first": sum(row["tie"] == "kept-first" for row in rows),
        },
    }  # fmt: skip


# ---- runner-ups ----------------------------------------------------------------------------------------------------


def _fits(item: ItemVec, place: str, setup: str) -> bool:
    if place == "ANY":
        return "ANY" in item.slots or bool(WEARABLE_SLOTS & item.slots)
    if place not in item.slots:
        return False
    return wp.allowed_in_hand(item, place.lower(), setup) if place in HANDS else True


def runnerup_chunk(ctx: Context, role: str, tier: int, entries: Sequence[RunnerupInput]) -> dict[str, Any]:
    """The runner-ups of one ``(role, tier)``: for each race of ``entries`` and each place, the best swaps (see below).

    A swap puts one candidate in one place of the kit and nothing else changes (the buffs and the assumed haste are those
    of the solved kit). Its delta is the exact value of the swapped kit minus the exact value of the kit, so it is
    at most 0 for every item of the solve pool (the kit is the best there is) and may be positive for a deity-locked item.
    A candidate is skipped when the swapped kit is not a legal one (:func:`check_kit` is asked of every trial kit: a Lore item
    already worn elsewhere, a two-hander beside an off-hand item, in either hand, a hand the setup does not allow ...), or
    when the race cannot wear the item (its race list leaves the race out, as the model does). A swap of an item anyone can
    wear that is worth more than the kit (beyond the float tolerance) is no swap to list but a violation: the solved kit was
    not the best there is. The document lists them in ``violations`` (empty for a kit that is the best); :func:`run_task`
    stops the run on one. Ties go to the smaller key.

    Each place keeps the :data:`RUNNER_UPS` best swaps of items that anyone can wear, and besides them at most
    :data:`DEITY_RUNNER_UPS` swap of an item locked to a deity: the best such swap, and only when its delta is above that of
    the best plain swap (or there is no plain swap to compare with). The entries are in order of delta, so a locked swap
    that is kept comes first; the file badges it with the deity named in its item row."""
    evidence = ctx.config.default_evidence
    vecs = ctx.vecs(tier)
    candidates = ctx.candidates(evidence, tier)
    buffset = ctx.buffsets["own"]
    views = []
    violations: list[str] = []
    for entry in entries:
        profile = ctx.profile(entry.race, role, "own", evidence)
        ep = profile.eval_profile
        totals = eval_buff_totals(buffset.totals(entry.buffs))
        kit = [vecs[k] if k is not None else None for k in entry.kit]

        def value(trial: list[ItemVec | None]) -> Any:
            return fm.evaluate(ep, trial, totals, setup=entry.setup, haste_assumed=entry.haste).F

        base = value(kit)
        beaten = EXACT_TOLERANCE * max(1.0, abs(float(base)))  # the most a swap of an item anyone can wear may be worth
        wearable = [c for c in candidates if c.races is None or entry.race in c.races]  # the model leaves out the others too
        by_place = {place: [c for c in wearable if _fits(c, place, entry.setup)] for place in dict.fromkeys(SLOT_INSTANCES)}
        places = []
        for index, place in enumerate(SLOT_INSTANCES):
            current = kit[index]
            options = []
            for cand in by_place[place]:
                if current is not None and cand.key == current.key:
                    continue
                trial = list(kit)
                trial[index] = cand
                # Every swap is a kit the wearer could put on. check_kit decides it all: a Lore item twice, a two-hander beside
                # an off-hand item (in either hand: the stick setup lets any item into any hand), a hand the setup does not
                # allow. An item locked to a deity is judged for a wearer of that deity.
                locks = sorted(cand.deity) if cand.deity else []
                if check_kit(trial, entry.setup, ctx.trio, deity=locks[0] if locks else None, race=entry.race):
                    continue
                options.append((value(trial) - base, cand.key, cand.deity is not None))
            options.sort(key=lambda option: (-option[0], option[1]))
            better = next((option for option in options if not option[2] and option[0] > beaten), None)
            if better is not None:
                # The kit is the best there is, so no swap of an item of the solve pool can beat it: one that does means the
                # solve (or the pruning before it) lost an item. The run stops on it (run_task); nothing may be built on it.
                violations.append(
                    f"the solved kit of {entry.race} ({role}, +{tier}, {entry.setup}) is not the best there is: the swap of "
                    f"{shards.PLACES[index]} to {better[1]} beats the kit by {float(better[0])!r}"
                )
            plain = [option for option in options if not option[2]][:RUNNER_UPS]
            locked = [option for option in options if option[2]][:DEITY_RUNNER_UPS]
            kept = [*plain, *(option for option in locked if not plain or option[0] > plain[0][0])]
            kept.sort(key=lambda option: (-option[0], option[1]))
            places.append([[key, _delta(delta)] for delta, key, _ in kept])
        views.append({"race": entry.race, "setup": entry.setup, "places": places})
    return {"format": 1, "kind": "runnerups", "key": {"role": role, "tier": tier}, "views": views, "violations": violations}


def _delta(delta: Any) -> float:
    value = round(float(delta), 4)
    return 0.0 if value == 0 else value  # never "-0.0"


# ---- the work of a process ----------------------------------------------------------------------------------------

_CONTEXT: Context | None = None


def init_worker(config: Config) -> None:
    """Build the process-wide :class:`Context` (the initializer of every worker process and of an in-process run)."""
    global _CONTEXT
    _CONTEXT = Context(config)


def run_task(task: Mapping[str, Any]) -> dict[str, Any]:
    """Do one task and return a small record; never raises (a failure comes back as ``{"ok": False, ...}``).

    A ``chunk`` task solves one view (``audit``, when it has one, says which race of it is solved again without pruning) and
    writes its chunk file; a ``runnerups`` task computes the runner-ups of one ``(role, tier)`` and writes its chunk file,
    unless a swap beat a kit (see :func:`runnerup_chunk`), which is a failure. Chunk files are written atomically
    (:mod:`trioforge.precompute.shards`)."""
    ctx = _CONTEXT
    kind = task["kind"]
    try:
        if ctx is None:
            raise RuntimeError("the worker has no context (init_worker was not called)")
        if kind == "chunk":
            doc = solve_chunk(ctx, task["key"], task["races"], audit=task.get("audit"))
            shards.write_chunk(Path(task["path"]), doc, ctx.config.fingerprint)
            return {"ok": True, "kind": kind, "path": task["path"], **doc["timing"]}
        started = time.perf_counter()
        doc = runnerup_chunk(ctx, task["role"], task["tier"], task["entries"])
        violations = doc.pop("violations")
        if violations:  # a swap of an item anyone can wear beat the kit: it was not the best there is, and the run stops
            more = f" (and {len(violations) - 3} more)" if len(violations) > 3 else ""
            raise ScenarioError("; ".join(violations[:3]) + more)
        doc["basis"] = task["basis"]
        shards.write_chunk(Path(task["path"]), doc, ctx.config.fingerprint)
        return {"ok": True, "kind": kind, "path": task["path"], "seconds": time.perf_counter() - started}
    except Exception as error:  # noqa: BLE001 - a worker reports; the parent decides
        if kind == "chunk":
            where = "; ".join(getattr(error, "__notes__", [])) or _where(task["key"])
        else:
            where = f"the runner-ups of the {task['role']} role at +{task['tier']}"
        return {
            "ok": False, "kind": kind, "error": type(error).__name__, "message": str(error), "where": where,
            "trace": traceback.format_exc(limit=-6),
        }  # fmt: skip


# ---- the seam for the robustness module ------------------------------------------------------------------------------


class RobustScenario(NamedTuple):
    """What the robustness hook is called with: one default view of one race, its solved kit and everything needed to solve
    the view again under changed weights or rules (``items`` is the whole solve pool at ``tier``, not the pruned one, and
    ``pool_items`` the catalog items it is made from, for a variant that changes how an item is built)."""

    race: str
    role: str
    tier: int
    setup: str
    trio: tuple[str, ...]
    level: int
    evidence: str
    buffs: str
    profile: Any
    buffset: Any
    items: list[ItemVec]
    pool_items: tuple[dict[str, Any], ...]
    chosen_buffs: tuple[int, ...]
    kit: tuple[ItemVec | None, ...]
    tables: Any
    rules: Any


def robust_scenario(ctx: Context, race: str, role: str, tier: int, setup: str, row: Mapping[str, Any]) -> RobustScenario:
    """The :class:`RobustScenario` of a solved row of the default view (default evidence, own buffs)."""
    evidence = ctx.config.default_evidence
    vecs = ctx.vecs(tier)
    return RobustScenario(
        race=race, role=role, tier=tier, setup=setup, trio=ctx.trio, level=ctx.config.level, evidence=evidence, buffs="own",
        profile=ctx.profile(race, role, "own", evidence), buffset=ctx.buffsets["own"], items=ctx.pool(evidence, tier),
        pool_items=tuple(ctx.pool_items(evidence)), chosen_buffs=tuple(row["buffs"]), kit=tuple(vecs[k] if k is not None else None for k in row["kit"]),
        tables=ctx.tables, rules=ctx.rules,
    )  # fmt: skip
