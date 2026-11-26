"""Parity fixtures: the cases that hold the browser engine to the Python reference.

``python -m trioforge.export.fixtures --out build/fixtures --seed N`` writes the families below into ``build/fixtures`` (git
ignored); ``--sample`` writes the small sample that is committed under ``fixtures/parity``. The JS tests read these files and
compare what the port computes with what Python computed, under the parity rules of :mod:`trioforge.export.milp_json`: the model
JSON by its ``compare``, objective values within 1e-9 relative, everything exact as ``"p/q"`` strings.

The families
============

==============  ==========================================================================================================
``brute/``      330 small invented instances, each with its exact maximum by enumeration of every legal kit and buff set
                (:mod:`trioforge.export.brute`), the program the builder made and the canonical solve
``matrix/``     a stratified coverage matrix of real scenarios (:mod:`trioforge.export.fixture_plan`): Iksar, a deity,
                every weapon setup, a real shield in the off hand, every buff key, a Monk trio below +10, mixed WIS/INT
                mana, a trio with END only, every role, tiers 0, 4 and 10, composed weights; each at least twice
``upgrade/``    16 Upgrade sessions: Equip now, three farm steps, the best 2 and 3 sets and Every slot, with owned counts,
                duplicates, owned-item tier upgrades, deity-locked owned items and the new-item row; and three invented
                sessions for Every slot
``pmb36/``      the neutral PAL/MNK/BER 36: two builds, tiers 0, 4 and 10, own, group and raid buffs, wiki and strict proxy
``evaluate/``   5,000 random kits with their exact breakdowns, across the profiles of the matrix and pmb36 scenarios
``profiles/``   the browser bundle of five trio types, the profile of every race, role and buff key, and 500 compositions
                of the weight overrides
``items/``      the item table, the item at every tier and both weapon rates (compact), the tier modes and merge costs
==============  ==========================================================================================================

The files
=========

Each file is one JSON document in plain ASCII (the full run writes most of them as gzip files, ``name.json.gz``, which hold the
same text). ``manifest.json`` lists every file with the size and SHA-256 of its **text** (so that it does not depend on the
compression library), the data release, the rules version, the seed, the solver and the coverage counts (``matrix``,
``pmb36`` and ``upgrade``: how many cases carry each tag; ``evaluate``: how many kits reach each regime of the evaluator).
The schema is ``fixtures.schema.json`` beside this module; :func:`validate_document` and :func:`validate_directory` check it
and the rules a schema cannot say. Every exact number is a reduced ``"p/q"`` string (integers too: ``"255/1"``); the plain
JSON numbers of a profile, a model and a weight are read as the decimal they print as.

* ``brute/brute-NNN.json``, ``matrix/matrix-NNN.json``, ``pmb36/pmb36-NNN.json``, ``upgrade/upgrade-NNN.json`` and
  ``upgrade/upgrade-slots-*.json``: a **case**, below
* ``evaluate/profiles.json`` (``evaluate-profiles``): ``profiles`` (``id``, ``trio``, ``level``, ``race``, ``role``, ``tier``,
  ``evidence``, the ``profile`` and its ``buffset``), the ``monk_bins`` of each level that has a Monk profile (by level: the
  block that a bundle of the level holds, from which the evaluator reads the Monk bonus; a level need not have a bundle among the
  fixtures) and the ``records`` of every item the kits use;
  ``evaluate/kits-NN.json`` (``evaluate-kits``): ``evaluations`` of ``profile`` (an index), ``setup``, ``haste`` (the haste
  assumed), ``buffs`` (null: the profile's own always-on buffs; else the ids chosen among the optional ones), the ``kit``
  (``[key, tier]`` for each of the 22 places) and its ``breakdown`` (``F``, ``parts`` and ``totals`` of
  :class:`trioforge.model.formulas.Breakdown`)
* ``profiles/<trio>-l<level>.bundle.json``: the bundle of :func:`trioforge.export.browser.bundle` as it is;
  ``profiles/<trio>-l<level>.profiles.json`` (``profiles``): ``profiles`` of ``race``, ``role``, ``buffs``, ``options``
  (``evidence`` and ``deity`` when given) and the ``profile`` that :func:`trioforge.export.browser.assemble` gives from the
  bundle. Every race, role and buff key is there three ways: with no ``options`` (no evidence level: the ``setups`` of the
  role, those of a profile with no pool to read) and with each evidence level (``{"evidence": "strict"}``, ``{"evidence":
  "wiki"}``: the ``setups_by_evidence`` of that level, those of the profile the precompute makes given the solve pool of the
  level); a few more carry a ``deity``. ``profiles/weights.json`` (``weights``): ``compositions`` of a ``base`` table of weights, the slider
  ``multipliers``, the ``custom`` weights, the ``regen_T`` window, and the ``result`` of ``roles.weights_override``
* ``items/table.json``: the item table of :func:`trioforge.export.browser.items` as it is; ``items/vectors-NN.json``
  (``item-vectors``): for each record the parts of the item that do not change with the tier (``fixed``), then for each tier
  from 0 to 10 the stats in the order ``stat_order``, the resists in ``sv_order``, the worn haste and the weight in tenths of a
  stone (``tiers``), and the weapon damage at both rates (``damage``); ``items/tiers.json`` (``tiers``): the tier of every tier
  rule, mode, difficulty and fixed tier, and the merge cost between any two tiers

A **case** (``kind`` ``case``) holds, in this order:

``inputs``      what the scenario is (trio, level, race, role, buff key, evidence, deity, setup, tier), the profile as
                ``Profile.to_dict()`` (which profile this is: see below), the composed weights when the spec says so,
                the resolved buff set (``set`` and ``table`` as the bundle writes them), and for an Upgrade session the owned
                set (``[ident, count]``), the candidates and the tier mode
``records``     the item-table records of every item the case uses; ``weapon_pct`` says which weapon rate reads them
``solves``      one or more programs: the options, the pool as idents ``key@tier`` (an item read from its record at its
                tier), the pruning that made the pool (the whole input, the options and the idents kept) when the case
                records it, ``haste`` (null for a program at one fixed haste; for a truthful solve, the ``levels`` a kit of
                the scenario can count, rising, and the ``level`` whose program won: the options of the program set
                ``haste_assumed`` and ``haste_floor`` to it, and the kit counts exactly that haste), the model JSON v1 the
                Python builder made, and the result of the canonical solve: the exact value
                ``F``, the value the model reported, the canonical kit (``[key, tier]`` or null for each of 22 places), the
                chosen buffs and the breakdown. The kit is canonical (the tie stage decided it) when ``tie_stage`` is
                ``applied``
``expected``    what only some families have. ``brute``: ``brute_F`` (the exact maximum by enumeration), ``kits`` and
                ``buff_sets`` counted. ``upgrade``: ``steps`` (``item``,
                ``kind`` new, copy or upgrade, ``source_tier``, ``F``, ``gain``, the ``owned`` set after the step, the merge
                ``cost`` or null, and the ``solve`` that made it: ``solves[0]`` is Equip now and ``solves[k]`` step ``k``), why
                the path ``stopped``, ``best_sets`` and ``every_slot``. ``best_sets`` has two entries, for the best 2 and the best 3
                additions made at once (``upgrade.best_sets``): ``k``, ``acquired`` (the idents the kit acquires, in the order
                the reference lists them: each upgrade followed by the copies of its target, then the new items, then the
                copies of owned items; an ident that is acquired more than once is listed once for each), the exact ``F`` of
                the kit, the ``gain`` over Equip now (0 and no ident when no set of additions improves the value) and
                ``haste_assumed``. The program of each is the solve labelled ``best-2`` and ``best-3`` (after the steps),
                built under the owned counts the session started with, ``max_new`` ``k`` and the pruning it records. A best
                set is empty when no set of additions improves the value: its ``F`` is
                Equip now's and its program, which exists, found nothing above that value. It has no program at all when the
                candidates offer no addition (each is a Lore copy of an owned item, say): ``best_sets`` then builds Equip now
                and nothing else, and neither set has a ``best-k`` solve. ``every_slot``: for each of the 22 places the current
                item and the three best swaps with the rest of the kit held fixed, from Equip now's kit over the candidates and
                the owned items under the options of ``solves[0]``, each swapped kit valued at the haste it counts. A candidate has no count (the swap
                gets another copy); an owned item that is not a candidate is a swap for a place only while its owned count
                (``inputs.owned``) is greater than the copies the kit wears in the other places, so none of these gains

**Which profile a case carries.** The profile of a matrix or pmb36 case is made given the solve pool of its evidence level (``make_profile`` with
``items``), which is what ``assemble`` of the bundle gives at that level: its weapon ``setups`` are those the pool offers. A ``wiki`` case has the
wiki pool of the public catalog, which has a shield; a ``strict-proxy`` case (its profile is labelled ``strict``) has the pool of the ``strict``
level, which is empty (the catalog has no strict item: one that has is refused), so it has no shield setup and no bow, and the plan never puts a
strict-proxy scenario on a setup that pool does not offer (a bow, so the Ranged role, is named by the pool alone, and a matrix case of it is a wiki one).
The profile of an upgrade case is made with no pool to read (``make_session``), so its setups are the fallback ones, a shield assumed and no bow,
at either evidence level: it is what ``assemble`` gives with no evidence level. The later parity tests (the ports of the builder and of the
evaluator) take a case's profile from ``case.inputs.profile``, and never assemble it.

**What a solve is compared with.** ``F`` is the exact value of the canonical kit, and the solver accepts that kit only when
its value equals the optimum of the first stage. An engine that solves ``model`` under the options of the Python solver (no
relative gap, an absolute gap of 1e-9, presolve off) therefore reaches ``const + c.x`` equal to ``F`` within 1e-9 relative.
``model_F`` is the value the model reports at the point the canonical solve ended in; when ``tie_stage`` is ``applied``
that is the point of the tie stage, which keeps every kit with ``F >= F* - 1e-7 max(1, |F*|)`` and minimizes a rank, so
``model_F`` is never above ``F`` (to 1e-6) and at most 1e-7 relative under it. It describes the Python run and is not a value
to match: compare an engine's first stage with ``F``, and its canonical kit with ``kit`` (the very kit: two kits of the same value
that share a total rank are told apart by the last stage of ``solve_canonical``, the order of the kits that the head of
``trioforge.solver.solve`` states, and the browser engine runs the same stage).

Invented items (``synthetic`` cases) have keys that start with ``it`` and are never keys of the catalog. Fixtures come only
from the public catalog: a catalog with a strict item is refused, and "strict" in a fixture means the hash proxy of the wiki
level (:func:`trioforge.bench.strict_proxy`): a case with ``evidence`` ``strict-proxy`` is built from the items that proxy picks
and its profile is labelled ``strict``. :func:`public_problems` rejects a fixture that has real strict evidence or names a key
outside the catalog.

Everything is deterministic for a seed: the same seed writes the same bytes (the plan does not depend on the seed except for its
filler and the owned items, and every random choice comes from a ``random.Random`` seeded with text). The sample is
``generate(out, seed, scale="sample")``; a test fails when its data release or rules version differ from the shipped release.
"""

from __future__ import annotations

import argparse
import dataclasses
import gzip
import hashlib
import json
import re
import shutil
import sys
import zlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from trioforge import bench
from trioforge.export import browser, milp_json
from trioforge.export.fixture_cases import (
    FORBIDDEN_REASONS,
    FORMAT,
    FixtureError,
    Inputs,
    brute_case,
    buffset_from_doc,
    make_scenario,
    make_session,
    options_from_json,
    scenario_case,
    slot_cases,
    upgrade_case,
)
from trioforge.export.fixture_plan import (
    RANGED_EVERY,
    REQUIRED_STRATA,
    SAMPLE_SESSIONS,
    SCALES,
    UPGRADE_REQUIRED,
    Scale,
    UpgradeSpec,
    bow_plan,
    brute_plan,
    count_tags,
    matrix_plan,
    pick_cover,
    pmb36_plan,
    procs_brute_plan,
    ranged_brute_plan,
    upgrade_plan,
)
from trioforge.export.fixture_tables import (
    EVALUATE_COMMON,
    EVALUATE_EXTREMES,
    evaluate_docs,
    item_docs,
    profile_docs,
    weight_docs,
)
from trioforge.model import procs as procs_module
from trioforge.model.items import ItemVec, at_tier
from trioforge.model.profile import Profile
from trioforge.model.tables import REPO
from trioforge.model.tables import load as load_tables
from trioforge.precompute import grid
from trioforge.solver.model import Milp, build_milp

__all__ = [
    "DEFAULT_SEED",
    "FAMILIES",
    "FixtureError",
    "SAMPLE_BUDGET",
    "build_solve",
    "check_release",
    "generate",
    "gzip_size",
    "load_items",
    "main",
    "public_problems",
    "read_document",
    "render",
    "shared_inputs",
    "validate_directory",
    "validate_document",
]

DEFAULT_SEED = 20261014
FAMILIES = ("brute", "matrix", "upgrade", "pmb36", "evaluate", "profiles", "items")
MANIFEST = "manifest.json"
NAME = "trioforge-parity-fixtures"
SAMPLE_BUDGET = 2_000_000  # bytes of gzip, summed over the files of the committed sample
SCHEMA = Path(__file__).with_name("fixtures.schema.json")
#: a key of an invented item: never the shape of a catalog key (``w`` and digits, or ``r`` and a name)
INVENTED_KEY = re.compile(r"^it[a-z0-9-]*$")
#: the words of the private flags that no fixture may hold. A word is matched whole (as a code or a name, up to the next character that is no letter, digit, hyphen or
#: underscore), never as a part of another: ``seen-in-game-notes`` is not ``seen-in-game``. Community reports are public and have no word here.
FORBIDDEN_WORDS = ("seen-in-game", "seen_keys", "seen-flags")
PER_LINE = frozenset(
    {"records", "solves", "evaluations", "profiles", "items", "compositions", "modes", "costs", "files", "races", "buff_table", "buff_table_haste"}
)
KIND_OF_DEF = {
    "manifest": "manifest", "case": "case", "evaluate-profiles": "evaluateProfiles", "evaluate-kits": "evaluateKits",
    "profiles": "profiles", "weights": "weights", "item-vectors": "itemVectors", "tiers": "tiers", "bundle": "bundle",
    "item-table": "itemTable",
}  # fmt: skip
RECORD_FIELD = {"case": "records", "evaluate-profiles": "records", "item-table": "items"}  # where a kind keeps item records
RATIONAL = re.compile(r"-?[0-9]+/[1-9][0-9]*")
CLASS_CODE = re.compile(r"[A-Z]{3}")


# ---- text -----------------------------------------------------------------------------------------------------------------


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def render(doc: Mapping[str, Any]) -> str:
    """The canonical text of a document: plain ASCII, the keys of the top level one to a line and the long lists (records,
    solves, evaluations ...) one entry to a line, everything else compact; ``\\n`` line ends, the same bytes for the same data."""
    lines = ["{"]
    last = len(doc) - 1
    for position, (key, value) in enumerate(doc.items()):
        comma = "," if position < last else ""
        if key in PER_LINE and isinstance(value, list) and value:
            lines.append(f" {_dump(key)}: [")
            lines += [f"  {_dump(entry)}{',' if number < len(value) - 1 else ''}" for number, entry in enumerate(value)]
            lines.append(f" ]{comma}")
        elif key in PER_LINE and isinstance(value, dict) and value:
            lines.append(f" {_dump(key)}: {{")
            entries = list(value.items())
            for number, (name, entry) in enumerate(entries):
                lines.append(f"  {_dump(name)}:{_dump(entry)}{',' if number < len(entries) - 1 else ''}")
            lines.append(f" }}{comma}")
        else:
            lines.append(f" {_dump(key)}: {_dump(value)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def read_document(path: str | Path) -> Any:
    """A document from a file, plain or gzip (``.gz``)."""
    data = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        data = gzip.decompress(data)
    return json.loads(data.decode("ascii"))


def _kind_of(path: str, doc: Mapping[str, Any]) -> str:
    if path.startswith("profiles/") and ".bundle." in path:
        return "bundle"
    if path.startswith("items/table."):
        return "item-table"
    return str(doc.get("kind"))


class _Writer:
    """Writes the documents of a run and keeps what the manifest lists."""

    def __init__(self, out: Path, compress: bool) -> None:
        self.out = out
        self.compress = compress
        self.entries: list[dict[str, Any]] = []

    def write(self, path: str, doc: Mapping[str, Any]) -> None:
        data = render(doc).encode("ascii")
        packed = gzip.compress(data, compresslevel=9, mtime=0) if self.compress else data
        name = f"{path}.gz" if self.compress else path
        target = self.out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(packed)
        self.entries.append(
            {"path": name, "kind": _kind_of(path, doc), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )


# ---- the run ------------------------------------------------------------------------------------------------------------


_INPUTS: dict[tuple[Any, ...], Inputs] = {}


def shared_inputs(root: str | Path = REPO, catalog: str | Path | None = None) -> Inputs:
    """The :class:`~trioforge.export.fixture_cases.Inputs` of a repository and catalog, loaded once for a process: the same
    files (by path, size and time of change) give the same object, which holds what the cases share (the tables, the item
    table, the pools)."""
    path = None if catalog is None else Path(catalog).resolve()
    stat = None if path is None else path.stat()
    key = (Path(root).resolve(), path, None if stat is None else (stat.st_size, stat.st_mtime_ns))
    if key not in _INPUTS:
        made = Inputs(Path(root), path)  # a catalog that is refused leaves the cache as it was
        _INPUTS.clear()  # one at a time: they are large
        _INPUTS[key] = made
    return _INPUTS[key]


def _prepare(out: Path) -> None:
    """Make ``out`` ready: a new or empty folder, or one that an earlier run of this command made (its families are removed)."""
    if out.exists() and not out.is_dir():
        raise FixtureError(f"{out} is not a folder")
    if out.is_dir() and any(out.iterdir()):
        marker = out / MANIFEST
        try:
            ours = json.loads(marker.read_text(encoding="ascii")).get("name") == NAME
        except (OSError, ValueError, AttributeError):
            ours = False
        if not ours:
            raise FixtureError(f"{out} has files that are not parity fixtures; use an empty folder")
        for family in FAMILIES:
            shutil.rmtree(out / family, ignore_errors=True)
        marker.unlink()
    out.mkdir(parents=True, exist_ok=True)


def _take(specs: list[Any], count: int | None) -> list[Any]:
    """``count`` of the specs, the ones that ask for a pruning check first, in plan order."""
    if count is None or count >= len(specs):
        return list(specs)
    ranked = sorted(specs, key=lambda spec: (not getattr(spec, "prune_check", False), specs.index(spec)))
    return sorted(ranked[:count], key=specs.index)


def _select_upgrades(specs: list[UpgradeSpec], count: int | None) -> list[UpgradeSpec]:
    if count is None or count >= len(specs):
        return list(specs)
    if count <= 0:
        return []
    if count == 1:
        return [min(specs, key=lambda spec: spec.owned)]  # the smallest session
    return [spec for spec in specs if spec.number in SAMPLE_SESSIONS][:count]


def _check_cover(family: str, counts: Mapping[str, int], required: Iterable[str], copies: int) -> None:
    short = [tag for tag in required if counts.get(tag, 0) < copies]
    if short:
        raise FixtureError(f"the {family} family has fewer than {copies} of: {', '.join(short)}")


def generate(
    out: str | Path, seed: int = DEFAULT_SEED, *, scale: str | Scale = "full", families: Iterable[str] | None = None,
    catalog: str | Path | None = None, root: str | Path = REPO, compress: bool | None = None,
    progress: Callable[[str, int, int], None] | None = None, inputs: Inputs | None = None,
) -> dict[str, Any]:
    """Write the fixtures of the families asked for (all by default) into ``out`` and return the manifest.

    ``scale`` is ``full`` (the real set), ``mini`` (a few of each, for tests) or ``sample`` (the committed sample), or a
    :class:`~trioforge.export.fixture_plan.Scale`. ``catalog`` and ``root`` say where the public catalog and the repository
    with ``derived/`` and ``rules/`` are. ``compress`` overrides whether the files are gzip files (the scale decides by
    default: the committed sample is plain text). ``progress(family, done, total)`` is called after each case. ``inputs``
    is an :class:`~trioforge.export.fixture_cases.Inputs` that is already loaded (it takes the place of ``catalog`` and
    ``root``; by default the one of the last call with the same catalog and root is reused). Raises
    :class:`FixtureError` for a catalog with a strict item, a case whose solve and brute force disagree, a family that misses
    a stratum it must cover, or an ``out`` that holds something else."""
    chosen = SCALES[scale] if isinstance(scale, str) else scale
    wanted = list(FAMILIES) if families is None else list(dict.fromkeys(families))
    unknown = [name for name in wanted if name not in FAMILIES]
    if unknown:
        raise FixtureError(f"unknown families {unknown}; use {', '.join(FAMILIES)}")
    inputs = inputs or shared_inputs(root, catalog)
    target = Path(out)
    _prepare(target)
    target.joinpath(MANIFEST).write_text(json.dumps({"name": NAME, "complete": False}), encoding="ascii")
    writer = _Writer(target, chosen.compress if compress is None else compress)
    report = progress or (lambda family, done, total: None)
    coverage: dict[str, dict[str, int]] = {}
    counts: dict[str, int] = {}
    tables = inputs.tables

    matrix: list[Any] = []
    pmb: list[Any] = []
    bow: list[Any] = []
    if any(name in wanted for name in ("matrix", "evaluate")):
        matrix = list(matrix_plan(seed, tables))
        if chosen.cover is not None:
            matrix = pick_cover(matrix, *chosen.cover)
        if chosen.bow:  # (the scenarios of the bow setup come after the plan and are no part of the cover: the others are what they were)
            bow = bow_plan(seed, tables)
            matrix = [*matrix, *bow]
    if any(name in wanted for name in ("pmb36", "evaluate")):
        pmb = _take(pmb36_plan(tables), chosen.pmb36)

    if "brute" in wanted:
        numbers = brute_plan()[: chosen.brute]
        if chosen.bow:  # the bow instances come after the plain ones (RANGED_BASE and up), which are drawn as they always were, and the instances with a table of procs after them (PROCS_BASE and up)
            numbers = [*numbers, *ranged_brute_plan(chosen.brute), *procs_brute_plan(chosen.brute)]
        for done, number in enumerate(numbers, start=1):
            writer.write(f"brute/brute-{number:03d}.json", brute_case(inputs, seed, number))
            report("brute", done, len(numbers))
        counts["brute"] = len(numbers)

    for family, specs in (("matrix", matrix), ("pmb36", pmb)):
        if family not in wanted:
            continue
        tag_lists = []
        for done, spec in enumerate(specs, start=1):
            doc = scenario_case(inputs, make_scenario(inputs, spec))
            writer.write(f"{family}/{spec.id}.json", doc)
            tag_lists.append(doc["tags"])
            report(family, done, len(specs))
        counts[family] = len(specs)
        coverage[family] = count_tags(tag_lists)

    if "upgrade" in wanted:
        specs = _select_upgrades(upgrade_plan(seed), chosen.upgrade)
        total = len(specs) + 3
        tag_lists = []
        for done, spec in enumerate(specs, start=1):
            doc = upgrade_case(inputs, make_session(inputs, spec, seed))
            writer.write(f"upgrade/{spec.id}.json", doc)
            tag_lists.append(doc["tags"])
            report("upgrade", done, total)
        for done, doc in enumerate(slot_cases(inputs), start=len(specs) + 1):
            writer.write(f"upgrade/{doc['id']}.json", doc)
            tag_lists.append(doc["tags"])
            report("upgrade", done, total)
        counts["upgrade"] = total
        coverage["upgrade"] = count_tags(tag_lists)

    if "evaluate" in wanted:
        bow_ids = {spec.id for spec in bow}
        scenarios = [make_scenario(inputs, spec) for spec in [*matrix, *pmb] if spec.id not in bow_ids]
        extra = [make_scenario(inputs, spec) for spec in bow]
        docs, tags = evaluate_docs(inputs, scenarios, chosen.evaluate, seed, bow_scenarios=extra, bow_count=chosen.evaluate // RANGED_EVERY if extra else 0)
        for path, doc in docs:
            writer.write(path, doc)
        counts["evaluate"] = chosen.evaluate + (chosen.evaluate // RANGED_EVERY if extra else 0)
        coverage["evaluate"] = tags
        report("evaluate", counts["evaluate"], counts["evaluate"])

    if "profiles" in wanted:
        docs = profile_docs(inputs, chosen.profile_trios, chosen.profile_races, level_55=chosen.name == "full")
        docs += weight_docs(inputs, chosen.weights, seed)
        for path, doc in docs:
            writer.write(path, doc)
        counts["profiles"] = sum(1 for path, _ in docs if path.endswith(".profiles.json"))
        report("profiles", counts["profiles"], counts["profiles"])

    if "items" in wanted:
        docs = item_docs(inputs, chosen.items)
        for path, doc in docs:
            writer.write(path, doc)
        counts["items"] = docs[0][1]["count"]
        report("items", counts["items"], counts["items"])

    _check_coverage(chosen, coverage, wanted)
    entries = sorted(writer.entries, key=lambda entry: entry["path"])
    manifest = {
        "format": FORMAT, "kind": "manifest", "name": NAME, "complete": True, "data_release": inputs.data_release,
        "rules_version": inputs.rules_version, "seed": seed, "scale": chosen.name, "level": inputs.level,
        "solver": {key: str(value) for key, value in _solver().items()},
        "families": {
            family: {
                "count": counts[family],
                "files": sum(1 for entry in entries if entry["path"].startswith(f"{family}/")),
                "bytes": sum(entry["bytes"] for entry in entries if entry["path"].startswith(f"{family}/")),
            }
            for family in FAMILIES if family in counts
        },  # fmt: skip
        "coverage": coverage, "files": entries,
    }  # fmt: skip
    problems = validate_document(manifest, name=MANIFEST)
    if problems:
        raise FixtureError("the manifest is not valid: " + "; ".join(problems[:3]))
    target.joinpath(MANIFEST).write_text(render(manifest), encoding="ascii", newline="\n")
    return manifest


def _solver() -> dict[str, Any]:
    info = grid.solver_info(True)
    return {"highs": info["highs"], "revision": info["revision"]}


def _check_coverage(chosen: Scale, coverage: Mapping[str, Mapping[str, int]], wanted: Sequence[str]) -> None:
    """The matrix must have every stratum twice (once at the test scale), the solved kits must wear a real shield twice, the
    upgrade sessions of a run of three or more must show every kind of step and every tier mode, and the random evaluations
    must reach every regime of the evaluator once there are enough of them."""
    if "matrix" in wanted and chosen.cover is not None and chosen.name != "sample":
        _check_cover("matrix", coverage["matrix"], *chosen.cover)  # a test scale keeps one of what it asked for
    elif "matrix" in wanted:
        _check_cover("matrix", coverage["matrix"], (*REQUIRED_STRATA, "shield-worn"), 2)
    if "upgrade" in wanted and (chosen.upgrade is None or chosen.upgrade >= 3):
        _check_cover("upgrade", coverage["upgrade"], UPGRADE_REQUIRED, 1)
    if "evaluate" in wanted and chosen.evaluate >= 100:
        _check_cover("evaluate", coverage["evaluate"], EVALUATE_COMMON, 10 if chosen.evaluate >= 1000 else 1)
    if "evaluate" in wanted and chosen.evaluate >= 1000:
        _check_cover("evaluate", coverage["evaluate"], EVALUATE_EXTREMES, 3)


# ---- reading a case back ----------------------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _rules() -> Any:
    return load_tables().rules


def load_items(case: Mapping[str, Any]) -> dict[str, ItemVec]:
    """Every item a case's pools, kits and owned set name, by ident: the record read with the tier rules at the tier of the
    ident. This is all a port needs besides the profile, the buff set and the options. A case made with other rules than this
    checkout's is refused, because the same record would read as another item."""
    rules = _rules()
    if case["rules_version"] != rules.version:
        raise FixtureError(f"{case['id']} was made with rules {case['rules_version']}, this checkout has {rules.version}")
    records = {browser.record_key(record): record for record in case["records"]}
    found: dict[str, ItemVec] = {}
    for name in _idents(case):
        key, _, tier = name.rpartition("@")
        catalog = browser.item_to_catalog(records[key], browser.ITEM_DEFAULTS)
        found[name] = at_tier(catalog, int(tier), rules, weapon_pct=case["inputs"]["weapon_pct"])
    return found


def _idents(case: Mapping[str, Any]) -> list[str]:
    """The idents a case names in its pools, prunings, kits, owned set and candidates, once each."""
    names: dict[str, None] = {}
    for solve in case["solves"]:
        names.update(dict.fromkeys(solve["pool"]))
        if solve["prune"] is not None:
            names.update(dict.fromkeys(solve["prune"]["input"]))
        names.update(dict.fromkeys(f"{entry[0]}@{entry[1]}" for entry in solve["result"]["kit"] if entry is not None))
    inputs = case["inputs"]
    names.update(dict.fromkeys(name for name, _ in inputs.get("owned", ())))
    names.update(dict.fromkeys(inputs.get("candidates", ())))
    return list(names)


def build_solve(case: Mapping[str, Any], index: int = 0) -> Milp:
    """The program of ``case["solves"][index]`` built again from the case alone (the profile, the buff set, the records, the
    pool and the options). It equals ``solve["model"]`` under the parity rules; a port does the same in JS."""
    items = load_items(case)
    solve = case["solves"][index]
    inputs = case["inputs"]
    options = options_from_json(solve["options"])
    if inputs.get("procs") is not None:  # (a case with a table of weapon procs: the builder counts them)
        options = dataclasses.replace(options, procs=procs_module.from_doc(inputs["procs"], inputs["trio"]))
    return build_milp(
        Profile.from_dict(inputs["profile"]), [items[name] for name in solve["pool"]], inputs["setup"],
        buffset_from_doc(inputs["buffset"]), options,
    )


def gzip_size(path: str | Path) -> int:
    """The bytes the files of a folder come to when gzip files: a plain file as ``gzip.compress`` makes it, a gzip file as it is.
    This is the size the budget of the committed sample is about."""
    total = 0
    for file in sorted(Path(path).rglob("*")):
        if file.is_file():
            data = file.read_bytes()
            total += len(data) if file.suffix == ".gz" else len(gzip.compress(data, compresslevel=9, mtime=0))
    return total


# ---- validation ------------------------------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


_RECORD_PROBLEMS: dict[str, tuple[str, ...]] = {}


def _record_problems(record: Any) -> tuple[str, ...]:
    """What the schema finds wrong with one item record, remembered by the text of the record."""
    text = json.dumps(record, sort_keys=True)
    if text not in _RECORD_PROBLEMS:
        _RECORD_PROBLEMS[text] = tuple(error.message[:160] for error in _validator("record").iter_errors(record))
    return _RECORD_PROBLEMS[text]


@lru_cache(maxsize=None)
def _validator(definition: str) -> Draft202012Validator:
    """The validator of one definition of the schema, made once."""
    return Draft202012Validator({"$ref": f"#/$defs/{definition}", "$defs": _schema()["$defs"]})


def _exact_tree(value: Any, where: str, out: list[str]) -> None:
    """Every leaf of an exact tree is a reduced ``p/q`` string or a class code, never a bare number."""
    if isinstance(value, str):
        if RATIONAL.fullmatch(value):
            try:
                browser.unrat(value)
            except ValueError:
                out.append(f"{where}: {value} is not in lowest terms")
        elif not CLASS_CODE.fullmatch(value):
            out.append(f"{where}: {value!r} is neither a p/q string nor a class code")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _exact_tree(item, f"{where}.{key}", out)
    elif isinstance(value, list):
        for number, item in enumerate(value):
            _exact_tree(item, f"{where}[{number}]", out)
    else:
        out.append(f"{where}: {value!r} is a bare value; exact numbers are p/q strings")


def validate_document(doc: Any, *, name: str = "<document>", kind: str | None = None) -> list[str]:
    """The faults of one fixture document as texts (an empty list: it is valid).

    The schema (``fixtures.schema.json``) is checked first, by the ``kind`` of the document (or the ``kind`` given, for the
    bundle and the item table, which have none). Then the rules a schema cannot say: every exact number is a ``p/q`` string
    in lowest terms, a case's models are valid model JSON, its profile reads back, a result's ``F`` is its breakdown's, every
    kit and swap names an item of the case, and the counts agree."""
    own = doc.get("kind") if isinstance(doc, dict) else None
    if kind is not None and own is not None and own != kind:
        return [f"{name}: the document says it is {own!r}, not {kind!r}"]
    kind = kind or own
    definition = KIND_OF_DEF.get(kind)
    if definition is None:
        return [f"{name}: unknown kind {kind!r}"]
    # the records of a case or a table are checked one by one, once for each different record (a case holds hundreds that
    # another case holds too), and the rest of the document with its records left out
    field = RECORD_FIELD.get(kind)
    records = doc[field] if field and isinstance(doc, dict) and isinstance(doc.get(field), list) else None
    shell = {**doc, field: []} if records is not None else doc
    errors = sorted(_validator(definition).iter_errors(shell), key=lambda error: [str(part) for part in error.absolute_path])
    problems = [f"{name}: {'/'.join(map(str, error.absolute_path)) or '<top>'}: {error.message[:160]}" for error in errors[:8]]
    for number, record in enumerate(records or ()):
        problems += [f"{name}: {field}/{number}: {message}" for message in _record_problems(record)]
        if len(problems) > 8:
            break
    if problems:
        return problems[:8]
    out: list[str] = []
    if kind == "case":
        out += _case_problems(doc, name)
    elif kind == "evaluate-profiles":
        out += _monk_bins_problems(doc, name)
    elif kind == "evaluate-kits":
        for number, evaluation in enumerate(doc["evaluations"]):
            _exact_tree(evaluation["breakdown"], f"{name}: evaluation {number}", out)
            if len(out) > 5:
                break
    elif kind == "item-table" and doc["count"] != len(doc["items"]):
        out.append(f"{name}: count is {doc['count']} but there are {len(doc['items'])} records")
    return out


def _monk_bins_problems(doc: Mapping[str, Any], name: str) -> list[str]:
    """The Monk bins of a list of evaluations are for the levels that have a Monk profile, and every number in them is a
    reduced ``p/q`` string (that they are the bins ``browser.monk_bins`` makes is for the tests: it needs the rules)."""
    out: list[str] = []
    levels = sorted({row["level"] for row in doc["profiles"] if row["profile"]["monk"] is not None})
    if list(doc["monk_bins"]) != [str(level) for level in levels]:
        out.append(f"{name}: monk_bins is for levels {list(doc['monk_bins'])}, the Monk profiles are at {levels}")
    for level, block in doc["monk_bins"].items():
        curves = [block["curve"], *(alternative["curve"] for alternative in block["alternatives"])]
        for number, curve in enumerate(curves):  # the shape is a name, not a number
            numbers = {key: value for key, value in curve.items() if key != "shape"}
            _exact_tree(numbers, f"{name}: monk_bins {level} curve {number}", out)
        _exact_tree(block["bonus"], f"{name}: monk_bins {level} bonus", out)
        for number, alternative in enumerate(block["alternatives"]):
            _exact_tree(alternative["bonus"], f"{name}: monk_bins {level} alternative {number}", out)
    return out[:5]


def _case_problems(case: Mapping[str, Any], name: str) -> list[str]:
    out: list[str] = []
    keys = [browser.record_key(record) for record in case["records"]]
    if len(set(keys)) != len(keys):
        out.append(f"{name}: a record is listed twice")
    known = set(keys)
    try:
        Profile.from_dict(case["inputs"]["profile"])
    except ValueError as error:
        out.append(f"{name}: the profile does not read back: {error}")
    for named in _idents(case):
        if named.rpartition("@")[0] not in known:
            out.append(f"{name}: {named} has no record")
    for number, solve in enumerate(case["solves"]):
        out += [f"{name}: solve {number}: model: {problem}" for problem in milp_json.validate(solve["model"])[:3]]
        result = solve["result"]
        _exact_tree([result["F"], result["breakdown"]], f"{name}: solve {number}", out)
        if result["F"] != result["breakdown"]["F"]:
            out.append(f"{name}: solve {number}: F is not the breakdown's F")
        pool = set(solve["pool"])
        if len(pool) != len(solve["pool"]):
            out.append(f"{name}: solve {number}: the pool names an item twice")
        out += [
            f"{name}: solve {number}: the kit wears {entry[0]}@{entry[1]}, which is not in the pool"
            for entry in result["kit"] if entry is not None and f"{entry[0]}@{entry[1]}" not in pool
        ]  # fmt: skip
        if solve["prune"] is not None:
            kept = set(solve["prune"]["kept"])
            if not kept <= set(solve["prune"]["input"]):
                out.append(f"{name}: solve {number}: the pruning kept an item that was not in its input")
            if kept != pool:
                out.append(f"{name}: solve {number}: the pool is not what the pruning kept")
    expected = case["expected"]
    for step in expected.get("steps", ()):
        if not 1 <= step["solve"] < len(case["solves"]):
            out.append(f"{name}: step {step['index']} names solve {step['solve']}, which does not exist")
        _exact_tree([step["F"], step["gain"]], f"{name}: step {step['index']}", out)
    if "brute_F" in expected:
        _exact_tree(expected["brute_F"], f"{name}: brute_F", out)
    for row in expected.get("every_slot", ()):
        _exact_tree([swap["delta"] for swap in row["swaps"]], f"{name}: {row['place']}", out)
    out += _best_set_problems(case, name)
    return out


def _best_set_problems(case: Mapping[str, Any], name: str) -> list[str]:
    """The best sets of an Upgrade case: the best 2 and the best 3, in that order, with an exact value that is Equip now's plus the
    gain, the haste its program assumed, idents that have records, and the program of each set (labelled ``best-k``, with
    ``max_new`` ``k``): a set that acquires something has one, whose result is the set's; a set that acquires nothing has one
    only if the candidates offered something to acquire, and that program found no value above Equip now's."""
    expected = case["expected"]
    if case["family"] != "upgrade":
        return [f"{name}: best_sets belongs to the upgrade family"] if "best_sets" in expected else []
    sets = expected.get("best_sets")
    if sets is None:
        return [f"{name}: an upgrade case has best_sets"]
    out: list[str] = []
    if [entry["k"] for entry in sets] != [2, 3]:
        out.append(f"{name}: best_sets are for k 2 and 3 in that order, not {[entry['k'] for entry in sets]}")
    keys = {browser.record_key(record) for record in case["records"]}
    equip = case["solves"][0]["result"]["F"]
    programs = {solve["label"]: solve for solve in case["solves"] if solve["label"].startswith("best-")}
    for entry in sets:
        where = f"{name}: best_sets k={entry['k']}"
        _exact_tree([entry["F"], entry["gain"]], where, out)
        out += [
            f"{where}: {acquired} has no record" for acquired in entry["acquired"] if acquired.rpartition("@")[0] not in keys
        ]
        if len(entry["acquired"]) > entry["k"]:
            out.append(f"{where}: acquires {len(entry['acquired'])} items, more than k")
        wanted_haste = (programs.get(f"best-{entry['k']}") or case["solves"][0])["result"]["haste_assumed"]
        if entry["haste_assumed"] != wanted_haste:
            out.append(f"{where}: haste_assumed {entry['haste_assumed']} is not the {wanted_haste} of its program")
        try:
            value, gain, start = browser.unrat(entry["F"]), browser.unrat(entry["gain"]), browser.unrat(equip)
        except ValueError:
            continue  # a number that is not in lowest terms has been reported
        if value - start != gain:
            out.append(f"{where}: gain is not F less the value of Equip now")
        if not entry["acquired"] and gain != 0:
            out.append(f"{where}: a set that acquires nothing has no gain")
        if entry["acquired"] and gain <= 0:
            out.append(f"{where}: a set that acquires something improves the value")
        program = programs.get(f"best-{entry['k']}")
        if entry["acquired"] and program is None:
            out.append(f"{where}: its program, best-{entry['k']}, is not among the solves")
        elif program is not None:
            if program["options"]["max_new"] != entry["k"]:
                out.append(f"{where}: its program was built with max_new {program['options']['max_new']}")
            if entry["acquired"] and program["result"]["F"] != entry["F"]:
                out.append(f"{where}: F is not the result of its program")
            if not entry["acquired"]:
                try:
                    found = browser.unrat(program["result"]["F"])
                except ValueError:
                    continue  # a number that is not in lowest terms has been reported
                if found > start:
                    out.append(f"{where}: it acquires nothing, but its program found a value above Equip now's")
    return out


def _walk_keys(doc: Mapping[str, Any]) -> set[str]:
    """The item keys a document names (records, pools, kits, swaps, owned sets and candidates)."""
    named: set[str] = {browser.record_key(record) for record in doc.get("records", ())}
    kind = doc.get("kind")
    if kind == "case":
        named.update(name.rpartition("@")[0] for name in _idents(doc))
        named.update(step["item"].rpartition("@")[0] for step in doc["expected"].get("steps", ()))
        for entry in doc["expected"].get("best_sets", ()):
            named.update(acquired.rpartition("@")[0] for acquired in entry["acquired"])
        for row in doc["expected"].get("every_slot", ()):
            named.update(swap["item"].rpartition("@")[0] for swap in row["swaps"])
            if row["current"] is not None:
                named.add(row["current"].rpartition("@")[0])
    elif kind == "evaluate-kits":
        named.update(entry[0] for evaluation in doc["evaluations"] for entry in evaluation["kit"] if entry is not None)
    elif kind == "item-vectors":
        named.update(entry["key"] for entry in doc["items"])
    elif "defaults" in doc:
        named.update(browser.record_key(record) for record in doc["items"])
    return named


def public_problems(doc: Mapping[str, Any], catalog_keys: Iterable[str]) -> list[str]:
    """Why a fixture is not public: real strict evidence (a record with the strict level, or a reason that names a sighting),
    a key outside the public catalog (an invented item of a synthetic case must have a key that cannot be one), a word that
    belongs to the private flags, or a ``strict`` profile whose pool is not the hash proxy
    (:func:`trioforge.bench.strict_proxy`). An empty list means the fixture may be committed or served."""
    catalog = set(catalog_keys)
    out: list[str] = []
    words = set(re.findall(r"[a-z0-9_-]+", json.dumps(doc).lower()))
    out += [f"the fixture contains {word!r}, which belongs to the private flags" for word in FORBIDDEN_WORDS if word in words]
    records = list(doc.get("records", ())) + (list(doc["items"]) if "defaults" in doc else [])
    for record in records:
        evidence = record.get("evidence", {})
        if evidence.get("level") == "strict":
            out.append(f"{browser.record_key(record)}: real strict evidence")
        out += [
            f"{browser.record_key(record)}: the reason {code!r} names a sighting"
            for code in evidence.get("codes", ()) if code.split(":")[0] in FORBIDDEN_REASONS
        ]  # fmt: skip
    synthetic = doc.get("synthetic") is True
    named = sorted(_walk_keys(doc))
    for key in named:
        if synthetic:
            if not INVENTED_KEY.fullmatch(key) or key in catalog:
                out.append(f"{key}: an invented item must have a key that cannot be a catalog key (it...)")
        elif key not in catalog:
            out.append(f"{key}: not a key of the public catalog")
    if doc.get("kind") == "case" and not synthetic:
        inputs = doc["inputs"]
        proxy = inputs["evidence"] == "strict-proxy"
        if inputs["profile"]["evidence"] == "strict" and not proxy:
            out.append("the profile is labelled strict but the pool is not the strict proxy")
        if proxy:
            out += _proxy_problems(named)
    return out


def _proxy_problems(keys: Sequence[str]) -> list[str]:
    """The keys that :func:`trioforge.bench.strict_proxy` would not pick."""
    kept = {item["key"] for item in bench.strict_proxy([{"key": key} for key in keys])}
    return [f"{key}: not picked by the strict proxy" for key in keys if key not in kept]


def check_release(manifest: Mapping[str, Any], data_release: str | None, rules_version: str) -> list[str]:
    """Why a manifest (of the committed sample, say) is not for the shipped release: its data release or rules version differ."""
    out = []
    if manifest.get("data_release") != data_release:
        out.append(f"the data release is {manifest.get('data_release')!r}, the catalog is {data_release!r}")
    if manifest.get("rules_version") != rules_version:
        out.append(f"the rules version is {manifest.get('rules_version')!r}, the rules are {rules_version!r}")
    return out


def validate_directory(path: str | Path, catalog_keys: Iterable[str] | None = None) -> list[str]:
    """The faults of a folder of fixtures: the manifest, every file it lists (size, SHA-256, schema, the release fields of the
    manifest and, with ``catalog_keys``, :func:`public_problems`), files it does not list, and the references between files
    (the profile of an evaluation, the bundle of a profile list)."""
    root = Path(path)
    try:
        manifest = read_document(root / MANIFEST)
    except (OSError, ValueError) as error:
        return [f"{MANIFEST}: cannot be read ({type(error).__name__})"]
    problems = validate_document(manifest, name=MANIFEST)
    if problems:
        return problems
    if not manifest["complete"]:
        problems.append(f"{MANIFEST}: the run did not finish")
    catalog = None if catalog_keys is None else set(catalog_keys)
    listed = {entry["path"] for entry in manifest["files"]}
    on_disk = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.suffix in (".json", ".gz")}
    problems += [f"{name}: not listed in the manifest" for name in sorted(on_disk - listed - {MANIFEST})]
    bundles = {entry["path"].removesuffix(".gz") for entry in manifest["files"] if entry["kind"] == "bundle"}
    profile_rows: list[str] = []  # the evidence of each profile of evaluate/profiles.json
    kits: list[tuple[str, dict[str, Any]]] = []
    for entry in manifest["files"]:
        name = entry["path"]
        if name not in on_disk:
            problems.append(f"{name}: listed but missing")
            continue
        raw = (root / name).read_bytes()
        try:
            text = gzip.decompress(raw) if name.endswith(".gz") else raw
        except (OSError, EOFError, zlib.error):
            problems.append(f"{name}: cannot be read as a gzip file")
            continue
        if len(text) != entry["bytes"] or hashlib.sha256(text).hexdigest() != entry["sha256"]:
            problems.append(f"{name}: size or SHA-256 differs from the manifest")
            continue
        doc = json.loads(text.decode("ascii"))
        found = validate_document(doc, name=name, kind=entry["kind"])
        problems += found
        if found:
            continue
        release = (doc["data_release"], doc["rules_version"])
        if release != (manifest["data_release"], manifest["rules_version"]):
            problems.append(f"{name}: the release fields {release} differ from the manifest's")
        if catalog is not None:
            problems += [f"{name}: {problem}" for problem in public_problems(doc, catalog)]
        if entry["kind"] == "evaluate-profiles":
            profile_rows = [row["evidence"] for row in doc["profiles"]]
        elif entry["kind"] == "evaluate-kits":
            kits.append((name, doc))
        elif entry["kind"] == "profiles" and f"profiles/{doc['bundle']}" not in bundles:
            problems.append(f"{name}: its bundle {doc['bundle']} is not among the files")
    for name, doc in kits:
        for evaluation in doc["evaluations"]:
            if evaluation["profile"] >= len(profile_rows):
                problems.append(f"{name}: an evaluation names profile {evaluation['profile']}, which does not exist")
                break
            if profile_rows[evaluation["profile"]] == "strict-proxy":
                bad = _proxy_problems(sorted({kit[0] for kit in evaluation["kit"] if kit is not None}))
                if bad:
                    problems.append(f"{name}: {bad[0]}")
                    break
    return problems


# ---- the command -----------------------------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.export.fixtures",
        description="Write the parity fixtures of the browser engine (build/fixtures), or the small committed sample.",
    )
    parser.add_argument(
        "--out", required=True, type=Path, help="the folder to write into (empty, or an earlier run of this command)"
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"the seed of the random choices (default {DEFAULT_SEED})")
    parser.add_argument("--sample", action="store_true", help="write the small sample that is committed under fixtures/parity")
    parser.add_argument("--scale", choices=sorted(SCALES), help="full (default), mini (a few of each, for tests) or sample")
    parser.add_argument("--families", help=f"a comma-separated subset of {','.join(FAMILIES)}")
    parser.add_argument(
        "--catalog", type=Path,
        help="the catalog file (default: $TRIOFORGE_CATALOG, else derived/catalog.json of --root, else the one of the main checkout of its git)",
    )
    parser.add_argument("--root", type=Path, default=REPO, help="the repository with derived/ and rules/")
    parser.add_argument("--validate", action="store_true", help="check the folder in --out instead of writing it")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command; returns 0, or 2 after a message on stderr if an input is unusable."""
    args = _parser().parse_args(argv)
    try:
        if args.validate:
            inputs = shared_inputs(args.root, args.catalog)
            problems = validate_directory(args.out, inputs.items_by_key)
            try:
                manifest = read_document(args.out / MANIFEST)
            except (OSError, ValueError):
                manifest = None  # (validate_directory has said why it cannot be read)
            if isinstance(manifest, dict):  # the release is checked of a manifest that is an object only: a list, a number or none has no release to check
                problems += check_release(manifest, inputs.data_release, inputs.rules_version)
            for problem in problems[:50]:
                print(problem, file=sys.stderr)
            print(f"{args.out}: {'valid' if not problems else str(len(problems)) + ' problems'}")
            return 1 if problems else 0
        scale = "sample" if args.sample else (args.scale or "full")
        if args.sample and args.scale not in (None, "sample"):
            raise FixtureError("--sample is the sample scale; do not give another --scale")
        families = args.families.split(",") if args.families else None

        def show(family: str, done: int, total: int) -> None:
            if done == total or done % 25 == 0:
                print(f"  {family}: {done}/{total}", file=sys.stderr, flush=True)

        manifest = generate(
            args.out, args.seed, scale=scale, families=families, catalog=args.catalog, root=args.root, progress=show
        )
    except (FixtureError, ValueError, OSError, KeyError) as error:
        print(f"trioforge.export.fixtures: {error}", file=sys.stderr)
        return 2
    stored = sum(p.stat().st_size for p in args.out.rglob("*") if p.is_file())
    lines = [
        f"{name:10} {row['count']:>6} cases {row['files']:>4} files {row['bytes']:>12} bytes"
        for name, row in manifest["families"].items()
    ]
    total = sum(entry["bytes"] for entry in manifest["files"])
    lines.append(f"{'total':10} {len(manifest['files']):>6} files {total:>12} bytes, {stored} on disk")
    lines.append(
        f"data release {manifest['data_release']}, rules {manifest['rules_version']}, seed {manifest['seed']}, "
        f"scale {manifest['scale']}"
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
