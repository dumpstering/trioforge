"""Precompute: solve the scenario grid of a trio with the exact solver and write the result files.

::

    python -m trioforge.precompute --trio pal-mnk-ber --out build/results [--seen PATH] [--processes N] [--limit K]
        [--tiers 0,4,10] [--races OGR,TRL] [--roles tank] [--evidence wiki] [--buffs own] [--no-robustness]

:func:`run` is the same thing as a function. **The tiers are the scope of the run** (``--tiers``, default +0, +4 and +10, and every
tier for the milestone trio PAL/MNK/BER: :func:`default_tiers`, in :mod:`trioforge.scope`): the grid of the run is every race, role, weapon setup,
evidence level and buff set at those tiers, the result files record them (``tiers``) and a run that has all of it is **not** partial. It must have
+4, the tier of the default view (the run is refused without it), and an indexable build of the site holds each trio to the scope of a full run of
it, so a run of other tiers makes a preview only. The other four lists
(``--races``, ``--roles``, ``--evidence``, ``--buffs``) narrow the grid for a quick look (a small real run for the site generator, say), and
so does ``--limit``: the result files are then marked ``partial``. It does five things, in order:

1. **Inputs.** The item catalog (``$TRIOFORGE_CATALOG`` or ``derived/catalog.json``), the tables and rules, the spell
   file and, with ``seen_path``, the maintainer's private list of item keys seen in game (merged only into a folder under
   ``build/`` or outside the repository; anything else is refused before a file is read).
2. **Solve chunks.** The grid (:func:`trioforge.precompute.grid.scenarios`) is cut into chunks, one for each view
   (evidence, buffs, role, setup, tier). The weapon setups follow the pool of each evidence level, so a strict pool with no
   shield has no ``1h-shield`` view and the strict shards hold fewer scenarios than the wiki ones (2,970 scenarios, not 3,300,
   for PAL/MNK/BER while no shield is strict). Each chunk solves the races of its view in one worker process, with the pool
   pruned for each set of race-only items a race can wear, a canonical solve for each race, and the checks of
   :func:`trioforge.precompute.grid.solve_chunk`: the objective re-check (the model's value and the evaluator's must agree,
   in both directions) and the **audit**, one race of the chunk, a different one from chunk to chunk, solved again with the
   whole pool and no pruning, which must come out at the same value (``RunSummary.audited``). A chunk file is written
   atomically; a rerun **skips** the chunks whose files are whole and made from the same inputs, and **redoes** a damaged or
   stale one. A failed check (an :class:`~trioforge.solver.solve.ExactnessError`, a solve that is not optimal, an illegal kit,
   a pruned solve worth less than the unpruned one) stops the run with a :class:`PrecomputeError`. Time limits are never set.
   A tie stage that kept the first stage's kit is no failure: it is counted (``RunSummary.kept_first``, a note,
   ``solver.kept_first`` in the shards).
3. **Runner-ups.** For the default assumptions (the default evidence level, own buffs, the role's best setup) the three best
   swaps of items anyone can wear for each of the 22 places, the rest of the kit held fixed, valued exactly, and at most one
   swap of a deity-locked item, badged with its deity and kept only when it beats the best of the three. Every swap is a legal
   kit, and one of an item anyone can wear that beats the kit stops the run: the kit was not the best there is.
4. **The files.** Four shards, the runner-ups in ``runnerups/<role>.json`` (one file for each role, with every tier of the scope in it) with ``runnerups/index.json``,
   ``defaults.json`` and, if the robustness module is there, ``robust.json`` (see :mod:`trioforge.precompute.shards`), the browser
   bundle ``engine-l<level>.json`` of the trio and the item table ``items.json`` of the folder of results (made at the start of the
   run from its own catalog and seen flags: :mod:`trioforge.precompute.engine`; a partial run writes them too), plus
   two kinds of check: the cross-scenario invariants of the design (a better tier is never worse, strict is never above wiki,
   own buffs are never above group buffs, nothing is below the naked character) and the size budget of each shard and each
   runner-up file (200 KB raw, 50 KB gzip). A failed check is listed in ``RunSummary.violations``; the files are still written.
5. **The summary** (:class:`RunSummary`): counts, times and notes.

The files that the engine reads are the same for every run of the inputs: ``items.json`` is shared by the trios of a folder (an
identical one is left alone, another is replaced whole and the run says so), and neither depends on the chunk files, so a rerun
that reuses every chunk writes them again from the inputs of that run. Both carry the fingerprint of those inputs (``inputs``), which
the site build holds a trio and the table to. The files of the trio are replaced first and ``items.json`` after them, so that a write that
fails leaves the table as it was; a table that cannot be made is removed, as a bundle that cannot be made is.

``--limit K`` works the first K chunks (the heavy ones come first) and stops: no result file is written, and the next run
without it finishes the rest from the chunk files. The default evidence level is ``strict``; while no item is strict the
default view falls back to ``wiki`` (``defaults.json`` and ``runnerups.json`` say so) and the shards carry the flag
``strict pool empty``.

The robustness module (:mod:`trioforge.solver.robust`) is put to work by :mod:`trioforge.precompute.seals`: ``robust.json``
holds, for each role at the default race and the tiers +4 and +10, whether each place's pick holds under every variant of the
judgment weights and the open rules, and ``defaults.json`` lists as ``flip_notes`` the rule alternatives that would put another
race on top. ``robustness=False`` (``--no-robustness``) skips both; with the module missing they are skipped with a note (and an
old ``robust.json`` is removed). ``robustness`` may also be a hook, called with a
:class:`~trioforge.precompute.grid.RobustScenario`, that answers ``{place: "robust" or a label}``; the flip notes still come from
the module.
"""

from __future__ import annotations

import hashlib
import importlib
import multiprocessing
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trioforge.model import tables as tables_module
from trioforge.model import weapons as wp
from trioforge.model.roles import ROLES, opening_role, roles_for
from trioforge.oldresults import current_rules_version, stale
from trioforge.precompute import engine, grid, kitwhy, shards
from trioforge.scope import GRID_TIERS, MILESTONE_TRIO, default_tiers
from trioforge.solver.solve import ExactnessError

__all__ = ["GRID_TIERS", "MILESTONE_TRIO", "PrecomputeError", "RunSummary", "default_tiers", "grids", "layout_facts", "run"]

ROBUST_TIERS = (4, 10)  # the tiers the robustness labels are made for
DEFAULT_TIER = 4  # the default view: the trio's opening build (trioforge.model.roles.opening_role), this tier, the evidence level (default_evidence) and own buffs
PROGRESS_SECONDS = 5.0  # the most often a progress line is given


class PrecomputeError(RuntimeError):
    """The run was refused or failed a check. ``trace`` holds the traceback of a failure inside a worker."""

    trace: str = ""


@dataclass
class RunSummary:
    """What a run did. ``scenarios`` and ``chunks`` are those of the grid worked on; ``solved`` counts the scenarios solved in
    this run, ``reused`` the chunks skipped because their files were whole, ``redone`` the chunks redone because their files
    were damaged or stale. ``kept_first`` counts the scenarios (of the chunks made or reused) whose tie stage kept the first
    stage's kit: the kit is the optimum, and which of several equal kits it is was left to the solver. ``audited`` counts
    the chunks (made or reused) that solved one race again without pruning and found the same value. The ``runnerup_*``
    counts are the same for the runner-up chunks. ``tiers`` is the scope of the run. ``partial`` is true when the grid
    was narrowed (races, roles, evidence levels or buff sets: the tiers are the scope and never a narrowing) or the run stopped at
    ``limit``. ``phases`` gives the wall seconds of each phase (``inputs``, ``solve``,
    ``bases``, ``runnerups``, ``seals``, ``flips``, ``why``, ``files``) and ``sizes`` maps a result file to ``(bytes, gzip bytes)``."""

    trio: str
    out_dir: Path
    scenarios: int
    chunks: int
    processes: int = 1
    canonical: bool = True
    partial: bool = False
    tiers: tuple[int, ...] = ()
    solved: int = 0
    kept_first: int = 0
    audited: int = 0
    reused: int = 0
    redone: int = 0
    runnerup_chunks: int = 0
    runnerup_solved: int = 0
    runnerup_reused: int = 0
    elapsed: float = 0.0
    solve_seconds: float = 0.0
    build_seconds: float = 0.0
    runnerup_seconds: float = 0.0
    phases: dict[str, float] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)
    sizes: dict[str, tuple[int, int]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def mean_solve_seconds(self) -> float:
        """The mean time inside the solver for a scenario solved in this run (0 if none was)."""
        return self.solve_seconds / self.solved if self.solved else 0.0


# ---- the scope and the grids -------------------------------------------------------------------------------------------
# (the scope of a trio, ``default_tiers``, is in trioforge.scope: the site build holds a trio to it as well, and does not import the solver)


def grids(
    trio: str | Sequence[str], tables: Any, rules: Any, *, tiers: Sequence[int] | None = None, races: Sequence[str] | None = None,
    roles: Sequence[str] | None = None, evidence: Sequence[str] | None = None, buffs: Sequence[str] | None = None,
    items: Any = None,
) -> tuple[list[grid.Scenario], list[grid.Scenario]]:
    """``(full, plan)``: the grid of the scope of a run, whole, and the grid it works.

    ``tiers`` is the scope (:func:`default_tiers` when None): ``full`` is every race, role, weapon setup, evidence level and buff set at
    those tiers, and ``plan`` is the part of it that ``races``, ``roles``, ``evidence`` and ``buffs`` leave. A run is partial exactly when
    ``plan`` is less than ``full``. ``items`` is what :func:`trioforge.precompute.grid.scenarios` takes (the solve pools, which decide whether
    the shield setup is in the grid of an evidence level). A tier, race, role, evidence level or buff set that does not exist is a ``ValueError``."""
    codes = grid.parse_trio(trio)
    scope = default_tiers(codes) if tiers is None else tuple(tiers)
    full = grid.scenarios(codes, tables, rules, tiers=scope, items=items)
    plan = grid.scenarios(codes, tables, rules, races=races, roles=roles, tiers=scope, evidence=evidence, buffs=buffs, items=items)
    return full, plan


# ---- running tasks -------------------------------------------------------------------------------------------------


def _check_workers_can_start(main: Any) -> None:
    """Refuse worker processes when ``main`` (the ``__main__`` module) is a script that a new interpreter cannot run again.

    A worker is started by running the main program again (``python -m`` is found again by name, a script file by its
    path). A script read from stdin, or whose file is gone, makes the worker die before it has read its settings; the parent
    is then stuck writing them to its pipe, for ever. A session or ``python -c`` has no file to run again, and is fine."""
    path = getattr(main, "__file__", None)
    if main is not None and getattr(main, "__spec__", None) is None and path is not None and not os.path.isfile(path):
        raise PrecomputeError(
            f"worker processes start the main program again, and {path!r} cannot be started: run a script file or "
            "python -m trioforge.precompute, or use processes=1"
        )


class _Pool:
    """Runs tasks in this process (``processes`` 1) or in a pool of spawned worker processes (each builds its own context)."""

    def __init__(self, config: grid.Config, processes: int) -> None:
        self.executor: ProcessPoolExecutor | None = None
        if processes <= 1:
            grid.init_worker(config)
        else:
            self.executor = ProcessPoolExecutor(
                max_workers=processes, mp_context=multiprocessing.get_context("spawn"), initializer=grid.init_worker,
                initargs=(config,),
            )

    def run(self, tasks: Sequence[Mapping[str, Any]], on_result: Callable[[Mapping[str, Any]], None]) -> None:
        """Do ``tasks``; call ``on_result`` for each finished one; raise :class:`PrecomputeError` at the first failure."""
        if not tasks:
            return
        if self.executor is None:
            for task in tasks:
                result = grid.run_task(task)
                _check(result)
                on_result(result)
            return
        futures = [self.executor.submit(grid.run_task, task) for task in tasks]
        try:
            for future in as_completed(futures):
                try:
                    result = future.result()
                except BrokenProcessPool as error:
                    raise PrecomputeError(
                        "a worker process died (out of memory?); the finished chunks are kept, run again to continue"
                    ) from error
                _check(result)
                on_result(result)
        except BaseException:
            for future in futures:
                future.cancel()
            raise

    def close(self) -> None:
        if self.executor is not None:
            self.executor.shutdown(wait=True, cancel_futures=True)

    def abort(self) -> None:
        """Stop the workers now. A chunk file is written all at once, so a worker that is killed leaves no half file."""
        if self.executor is not None:
            for process in list(getattr(self.executor, "_processes", {}).values()):
                process.terminate()
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.executor = None


def _check(result: Mapping[str, Any]) -> None:
    if result["ok"]:
        return
    name, message, where = result["error"], result["message"], result["where"]
    if name == "ExactnessError":
        error = PrecomputeError(f"objective re-check failed ({where}): {message}")
    else:
        error = PrecomputeError(f"{name} ({where}): {message}")
    error.trace = result.get("trace", "")
    raise error


class _Progress:
    """Gives a progress line at most every few seconds, and at the end of a phase."""

    def __init__(self, say: Callable[[str], None]) -> None:
        self.say = say
        self.last = 0.0

    def start(self, what: str, total: int) -> Callable[[], None]:
        done = [0]
        self.last = time.monotonic()

        def step() -> None:
            done[0] += 1
            now = time.monotonic()
            if done[0] == total or now - self.last >= PROGRESS_SECONDS:
                self.last = now
                self.say(f"{what}: {done[0]}/{total}")

        return step


# ---- the robustness module ---------------------------------------------------------------------------------------------


def _find_robustness(option: Callable[..., Any] | bool | None) -> tuple[Callable[..., Any] | None, str]:
    """``(hook, "")`` or ``(None, reason)``. ``option`` is a hook, ``False`` (off) or None (the seals of
    :mod:`trioforge.precompute.seals`, made with trioforge.solver.robust, which a hook needs too for the flip notes)."""
    if option is False:
        return None, "disabled"
    try:
        module = importlib.import_module("trioforge.solver.robust")
    except ModuleNotFoundError as error:
        if error.name != "trioforge.solver.robust":
            raise
        return None, "trioforge.solver.robust is not available"
    if not callable(getattr(module, "robustness_report", None)):
        return None, "trioforge.solver.robust has no robustness_report()"
    if callable(option):
        return option, ""
    from trioforge.precompute import seals

    return seals.seal_hook, ""


# ---- the run --------------------------------------------------------------------------------------------------------


def layout_facts(profile: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """What the result files say once for the whole trio, as the profile of a scenario has it: ``(caps, assumptions)`` (see
    :class:`trioforge.precompute.shards.Layout`). They are the same for every race and role of a trio, and :func:`run` stops if a
    profile has others than the sample the files are written from."""
    regen = profile.caps["regen"]
    caps = {
        "sheet_softcap": profile.effective_softcap, "haste": profile.haste_cap, "resist": profile.caps["resist"],
        "regen": {name: regen[name] for name in ("HP", "MANA", "END")},
    }  # fmt: skip
    return caps, {"aa": dict(profile.aa), "deity": profile.deity}


def _best_setups(
    docs: Mapping[grid.ChunkKey, Mapping[str, Any]], evidence: str, buffs: str, role: str, tier: int, setups: Sequence[str]
) -> dict[str, tuple[float, str, Mapping[str, Any]]]:
    """For each race, the best row of the role's setups at ``tier``: ``(value, setup, row)``; the first setup wins a tie."""
    best: dict[str, tuple[float, str, Mapping[str, Any]]] = {}
    for setup in setups:
        doc = docs.get(grid.ChunkKey(evidence, buffs, role, setup, tier))
        for row in doc["rows"] if doc is not None else ():
            if row["race"] not in best or row["F"] > best[row["race"]][0]:
                best[row["race"]] = (row["F"], setup, row)
    return best


def _chunk_ok(doc: Mapping[str, Any] | None, key: grid.ChunkKey, races: Sequence[str]) -> bool:
    return doc is not None and doc.get("key") == key._asdict() and [row["race"] for row in doc["rows"]] == list(races)


def run(
    trio: str | Sequence[str], out_dir: str | os.PathLike[str], seen_path: str | os.PathLike[str] | None = None,
    processes: int | None = None, *, catalog: str | os.PathLike[str] | None = None, limit: int | None = None,
    canonical: bool = True, races: Sequence[str] | None = None, roles: Sequence[str] | None = None,
    tiers: Sequence[int] | None = None, evidence: Sequence[str] | None = None, buffs: Sequence[str] | None = None,
    tables_root: str | os.PathLike[str] | None = None, robustness: Callable[..., Any] | bool | None = None,
    progress: Callable[[str], None] | None = None, code_hash: str | None = None, procs: bool = True,
) -> RunSummary:
    """Solve the grid of ``trio`` and write the result files under ``<out_dir>/<trio slug>/`` (see the module docstring).

    ``seen_path`` merges the private seen flags (``out_dir`` must then be under ``build/`` or outside the repository).
    ``processes`` is the number of worker processes (1 works in this process; the default leaves one core free).
    ``catalog`` defaults to :func:`trioforge.precompute.grid.find_catalog`. ``limit`` works only the first chunks.
    ``canonical`` False uses the plain solve instead of the tie stage (faster, and not canonical). ``tiers`` is the scope of the run
    (:func:`default_tiers` when None); ``races``, ``roles``, ``evidence`` and ``buffs`` narrow the grid of it (the result files are then
    marked ``partial``). ``robustness`` is a hook, ``False`` or None (look for the module). ``code_hash`` is the hash of the code the chunks are made under for a
    caller that has hashed the source files already (the release build does, once, at its start); None, as for the command line, hashes them now. ``procs`` False
    asks for a run with no weapon procs in the score (a test of something else); by default the run needs ``derived/client/effect-spells.json`` and stops, naming it, without it.
    Raises :class:`PrecomputeError`."""
    from trioforge.data import catalog as catalog_module  # not at the top: a worker process imports this package too

    started = time.perf_counter()
    say = progress or (lambda message: None)
    out = Path(out_dir)
    processes = max(1, processes if processes is not None else (os.cpu_count() or 2) - 1)
    if processes > 1:
        _check_workers_can_start(sys.modules.get("__main__"))
    if seen_path is not None:
        try:
            catalog_module.check_seen_output(out)
        except catalog_module.BuildError as error:
            raise PrecomputeError(str(error)) from error
    try:
        codes = grid.parse_trio(trio)
    except ValueError as error:
        raise PrecomputeError(str(error)) from error
    slug = grid.trio_slug(codes)
    refused = stale(slug, out / slug, current_rules_version(tables_root))
    if refused:  # results of an earlier release (the Balanced build, which no longer exists) or of other rules: they are not resumed, half read or overwritten in part
        raise PrecomputeError(refused + " (or remove this trio's folder first)")
    catalog_path = Path(catalog) if catalog is not None else grid.find_catalog()
    if catalog_path is None or not catalog_path.is_file():
        raise PrecomputeError("the item catalog was not found: build derived/catalog.json or set TRIOFORGE_CATALOG")
    try:
        config, meta = grid.load_inputs(
            codes, catalog_path=catalog_path, seen_path=seen_path, tables_root=tables_root, canonical=canonical, code_hash=code_hash, procs=procs
        )
        tables = tables_module.load(config.tables_root)
        rules = tables.rules
        # the solve pool of each evidence level decides whether that level has the shield setup and the bow setup: a strict pool without a
        # shield must not get a 1h-shield view that is solved with an empty off hand, nor one without a bow a ranged view that has no bow to shoot
        pools = {kind: grid.setup_pool(config, rules, kind) for kind in grid.EVIDENCE}
        full, plan = grids(
            codes, tables, rules, tiers=tiers, races=races, roles=roles, evidence=evidence, buffs=buffs, items=pools
        )  # the grid of the scope, whole, and the part of it this run works: only a narrowing of the rest makes a run partial
    except (OSError, ValueError, catalog_module.BuildError) as error:
        raise PrecomputeError(str(error)) from error
    covered = sorted({s.tier for s in full})
    if DEFAULT_TIER not in covered:  # the default view, the page and the seals are made at it; without it there is no defaults.json to build from
        raise PrecomputeError(
            f"the tiers of the run, {', '.join(f'+{tier}' for tier in covered)}, leave out +{DEFAULT_TIER}, the tier of the default view: "
            "defaults.json and the page are made at it, and no site can be built without them (add it to --tiers)"
        )
    if not plan:
        raise PrecomputeError("the grid is empty")

    try:  # the engine's two files, made first from the inputs of this moment: a fault of theirs costs nothing yet
        engine_texts = engine.make(
            codes, config, meta, tables, catalog_path=catalog_path, seen_path=seen_path, setups=engine.level_setups(plan)
        )
    except (OSError, ValueError, catalog_module.BuildError) as error:
        raise PrecomputeError(str(error)) from error
    chunk_map = grid.chunks(plan)
    order = grid.run_order(chunk_map, roles_for(codes, bow=None))  # (every role a grid can have: whether a pool offers the Ranged role is for the grid to say)
    place_in_run = {key: n for n, key in enumerate(order)}  # where each view stands: it decides which race the view audits
    selected = order if limit is None else order[: max(0, limit)]
    stopped = len(selected) < len(order)
    narrowed = len(plan) != len(full)
    summary = RunSummary(
        trio=slug, out_dir=out / slug, scenarios=len(plan), chunks=len(order), processes=processes, canonical=canonical,
        partial=narrowed or stopped, tiers=tuple(sorted({s.tier for s in full})),
    )
    trio_dir = out / slug
    chunk_dir = trio_dir / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    if meta.pool_sizes["strict"] == 0:
        summary.notes.append("strict pool empty: the strict shards hold naked-plus-buffs kits; the default view uses wiki evidence")
    if meta.unknown_seen:
        summary.notes.append(f"{meta.unknown_seen} seen key(s) are unknown to the catalog and were ignored")

    summary.phases["inputs"] = time.perf_counter() - started
    mark = time.perf_counter()
    pool = _Pool(config, processes)
    clean = False  # set when the work is over without a failure: then the pool is closed, else its workers are stopped
    try:
        # -- the solve chunks
        docs: dict[grid.ChunkKey, Mapping[str, Any]] = {}
        todo = []
        for key in selected:
            doc, state = shards.load_chunk(shards.chunk_path(chunk_dir, key), config.fingerprint)
            if _chunk_ok(doc, key, chunk_map[key]):
                docs[key] = doc
                summary.reused += 1
            else:
                summary.redone += state == "damaged" or doc is not None
                todo.append(key)
        tasks = [
            {
                "kind": "chunk", "key": key, "races": chunk_map[key], "path": str(shards.chunk_path(chunk_dir, key)),
                "audit": place_in_run[key],
            }
            for key in todo
        ]  # fmt: skip
        step = _Progress(say).start(f"solving with {processes} process(es)", len(tasks))

        def solved(result: Mapping[str, Any]) -> None:
            summary.solved += result["scenarios"]
            summary.solve_seconds += result["solve"]
            summary.build_seconds += result["build"]
            step()

        pool.run(tasks, solved)
        summary.phases["solve"] = time.perf_counter() - mark
        if stopped:
            summary.notes.append(f"stopped at --limit {limit}: {len(selected)} of {len(order)} chunks worked, no result file written")
            summary.elapsed = time.perf_counter() - started
            clean = True
            return summary
        for key in todo:
            doc, state = shards.load_chunk(shards.chunk_path(chunk_dir, key), config.fingerprint)
            if not _chunk_ok(doc, key, chunk_map[key]):
                raise PrecomputeError(f"the chunk file of {key} is {state} right after it was written")
            docs[key] = doc

        summary.kept_first = sum(1 for doc in docs.values() for row in doc["rows"] if row.get("tie") == "kept-first")
        summary.audited = sum(1 for doc in docs.values() if doc.get("audit") is not None)

        # -- what the result files need
        mark = time.perf_counter()
        ctx = grid.Context(config)
        plan_roles = [role for role in roles_for(codes, bow=None) if role in {s.role for s in plan}]
        # the setups of each role at each evidence level (the levels can differ: see grid.scenarios), and of the levels
        # together; always in the order of wp.setup_order of the role, which breaks a tie between two setups of equal value
        level_setups = engine.level_setups(plan)
        layout_setups = {
            role: sorted({setup for by_role in level_setups.values() for setup in by_role.get(role, ())}, key=wp.setup_order(role).index)
            for role in plan_roles
        }
        default_setups = level_setups.get(config.default_evidence, {})  # the answer, the runner-ups and the seals are of this level
        # the build the page opens on, and so the default view: decided from the builds that have a setup at the evidence level of the default view, in the whole grid of the
        # scope (not the narrowed one: a narrowed run has the opening build of the trio all the same). The Archer has none where the pool of that level has no bow.
        full_default_setups = engine.level_setups(full).get(config.default_evidence, {})
        opening = opening_role(codes, [role for role in ROLES if full_default_setups.get(role)])
        tier_list = sorted({s.tier for s in plan})
        # the files give the caps and the assumptions once, from one sample profile: that is right only while no race or role has
        # its own (test_the_caps_and_the_assumptions_are_one_set_... says so for the real tables), and the run stops if one has
        def profile_level(role: str) -> str:
            """An evidence level at which the plan has ``role``: the default one when it has it (the Archer has no profile at a level whose pool has no bow)."""
            levels = sorted(kind for kind, by_role in level_setups.items() if by_role.get(role))
            return config.default_evidence if config.default_evidence in levels else levels[0]

        sample = ctx.profile(plan[0].race, plan_roles[0], "own", profile_level(plan_roles[0]))
        caps, assumptions = layout_facts(sample)
        for race, role in sorted({(s.race, s.role) for s in plan}):
            if layout_facts(ctx.profile(race, role, "own", profile_level(role))) != (caps, assumptions):
                raise PrecomputeError(
                    f"the caps and assumptions of the result files are one set for the whole trio, but {race} {role} has other ones than "
                    f"{plan[0].race} {plan_roles[0]}, which they were taken from"
                )
        planned = {s.race for s in plan}  # a narrowed run lists only the races it has rows for
        layout = shards.Layout(
            trio=slug, classes=codes, level=config.level, data_release=meta.data_release, game_patch=meta.game_patch,
            rules_version=meta.rules_version, solver=grid.solver_info(canonical), build_options=grid.build_info(),
            assumptions=assumptions, races=[(code, legal) for code, legal in grid.race_order(codes, tables) if code in planned],
            roles=plan_roles, setups=layout_setups, tiers=tier_list, caps=caps,
            pools=meta.pool_sizes, default_evidence=config.default_evidence,
            expected=dict(Counter((s.evidence, s.buffs) for s in full)),
            item_rows={item["key"]: shards.item_row(item, config.levels[item["key"]], rules) for item in config.items},
            flags=["strict pool empty"] if meta.pool_sizes["strict"] == 0 else [],
        )  # fmt: skip
        try:
            bases = {
                (race, role, buff_set): ctx.empty_value(race, role, buff_set)
                for race, role, buff_set in sorted({(s.race, s.role, s.buffs) for s in plan})
            }
        except (ExactnessError, grid.ScenarioError) as error:
            raise PrecomputeError(f"objective re-check failed for the naked character: {error}") from error
        values = {
            (key.evidence, key.buffs, key.role, key.setup, key.tier, row["race"]): row["F"]
            for key, doc in docs.items() for row in doc["rows"]
        }  # fmt: skip
        summary.violations = shards.check_invariants(values, bases)
        summary.phases["bases"] = time.perf_counter() - mark
        mark = time.perf_counter()

        # -- runner-ups
        ru_docs: dict[tuple[str, int], Mapping[str, Any]] = {}
        ru_tasks = []
        ru_basis: dict[tuple[str, int], str] = {}
        race_at = layout.race_index()
        for role in plan_roles:
            for tier in tier_list:
                best = _best_setups(docs, config.default_evidence, "own", role, tier, default_setups.get(role, ()))
                if not best:
                    continue
                entries = [
                    grid.RunnerupInput(race, setup, tuple(row["kit"]), tuple(row["buffs"]), row["haste"])
                    for race, (_, setup, row) in sorted(best.items(), key=lambda item: race_at[item[0]])
                ]  # fmt: skip
                basis = hashlib.sha256(shards.dumps([list(entry) for entry in entries]).encode()).hexdigest()
                path = shards.runnerup_path(chunk_dir, role, tier)
                doc, _ = shards.load_chunk(path, config.fingerprint)
                summary.runnerup_chunks += 1
                if doc is not None and doc.get("basis") == basis and doc.get("key") == {"role": role, "tier": tier}:
                    ru_docs[(role, tier)] = doc
                    summary.runnerup_reused += 1
                else:
                    ru_basis[(role, tier)] = basis
                    ru_tasks.append({"kind": "runnerups", "role": role, "tier": tier, "entries": entries, "basis": basis, "path": str(path)})
        step = _Progress(say).start("runner-ups", len(ru_tasks))

        def ran(result: Mapping[str, Any]) -> None:
            summary.runnerup_solved += 1
            summary.runnerup_seconds += result["seconds"]
            step()

        pool.run(ru_tasks, ran)
        for task in ru_tasks:
            role, tier = task["role"], task["tier"]
            doc, state = shards.load_chunk(Path(task["path"]), config.fingerprint)
            if doc is None or doc.get("basis") != ru_basis[(role, tier)]:
                raise PrecomputeError(f"the runner-up file of the {role} role at +{tier} is {state} right after it was written")
            ru_docs[(role, tier)] = doc
        summary.phases["runnerups"] = time.perf_counter() - mark
        clean = True
    finally:
        if clean:
            pool.close()
        else:
            pool.abort()

    # -- defaults, robustness and the files
    mark = time.perf_counter()
    close_pct = rules.get("defaults.race_close_pct")
    out_docs: dict[str, Mapping[str, Any]] = {}
    for kind in sorted({s.evidence for s in plan}):
        for buff_set in sorted({s.buffs for s in plan if s.evidence == kind}):
            out_docs[f"{kind}-{buff_set}.json"] = shards.shard_doc(layout, kind, buff_set, docs, bases)
    out_docs.update(shards.runnerup_texts(layout, ru_docs))  # one file for each role (every tier of the scope in it), and an index
    default_best = _best_setups(docs, config.default_evidence, "own", opening, DEFAULT_TIER, default_setups.get(opening, ()))
    flips: list[str] = []
    if default_best:
        per_race = {race: (value, setup) for race, (value, setup, _) in default_best.items()}
        choice = shards.default_race(
            {race: value for race, (value, _) in per_race.items()}, layout.legal_races(), [c for c, _ in layout.races], close_pct
        )
        hook, why = _find_robustness(robustness)
        status = f"skipped: {why}" if hook is None else "skipped: no creation-legal race in the grid"
        if hook is not None and choice is not None:
            say(f"seals: {len(plan_roles) * len(ROBUST_TIERS)} runs at the default race, {choice['race']}")
            sealed = time.perf_counter()
            labels: dict[str, dict[int, Mapping[str, str]]] = {}
            for role in plan_roles:
                for tier in ROBUST_TIERS:
                    best = _best_setups(docs, config.default_evidence, "own", role, tier, default_setups.get(role, ())).get(choice["race"])
                    if best is not None:
                        scenario = grid.robust_scenario(ctx, choice["race"], role, tier, best[1], best[2])
                        try:
                            labels.setdefault(role, {})[tier] = dict(hook(scenario))
                        except Exception as error:
                            raise PrecomputeError(
                                f"the robustness hook failed for {choice['race']} {role} +{tier}: {type(error).__name__}: {error}"
                            ) from error
            summary.phases["seals"] = time.perf_counter() - sealed
            say("flip check: the default view of every race that can be created, under each open rule")
            sealed = time.perf_counter()
            from trioforge.precompute import seals

            try:
                flips = seals.flip_notes(
                    seals.flip_variants(
                        ctx, role=opening, tier=DEFAULT_TIER, evidence=config.default_evidence,
                        setups=default_setups[opening], races=[code for code, ok in layout.races if ok and code in per_race],
                    ),
                    {race: value for race, (value, _) in per_race.items()}, choice["race"], layout.legal_races(), [code for code, _ in layout.races], close_pct,
                )  # fmt: skip
            except Exception as error:
                raise PrecomputeError(f"the flip check of the best race failed: {type(error).__name__}: {error}") from error
            summary.phases["flips"] = time.perf_counter() - sealed
            if labels:
                out_docs["robust.json"] = shards.robust_doc(layout, choice["race"], labels)
                status = "done"
            else:
                status = "skipped: the grid has none of the tiers " + " and ".join(f"+{t}" for t in ROBUST_TIERS)
        if status != "done":
            summary.notes.append(f"robustness {status}")
        why = None
        if choice is not None:  # what each stat of each item of the default kit is worth (the rows of Wear this say it)
            sealed = time.perf_counter()
            _, best_setup, best_row = default_best[choice["race"]]
            try:
                why = kitwhy.default_why(ctx, choice["race"], opening, DEFAULT_TIER, best_setup, best_row)
            except Exception as error:
                raise PrecomputeError(f"the why of the default kit failed: {type(error).__name__}: {error}") from error
            summary.phases["why"] = time.perf_counter() - sealed
        out_docs["defaults.json"] = shards.defaults_doc(
            layout, view={"role": opening, "tier": DEFAULT_TIER, "evidence": config.default_evidence, "buffs": "own"},
            per_race=per_race, strict_empty=meta.pool_sizes["strict"] == 0, robustness=status, flip_notes=flips, why=why, close_pct=close_pct,
        )
    else:
        summary.notes.append(f"defaults skipped: the grid has no {opening} (the opening build), +{DEFAULT_TIER}, {config.default_evidence}, own-buffs view")
    if engine_texts.bundle is not None:
        out_docs[shards.engine_name(config.level)] = engine_texts.bundle
    summary.violations.extend(engine_texts.problems)
    written = shards.write_files(trio_dir, out_docs)  # the files of the trio, all or nothing, the defaults last
    extra_files: list[Path] = []
    # The item table is replaced after them: a write of the trio's files that fails leaves the table as it was, and the build can tell a table and a trio that
    # were made from other inputs (the fingerprint in both). A table that cannot be made takes the old table away, as a bundle that cannot be made takes its own.
    if engine_texts.items is not None:
        items_path, items_state = engine.write_items(out, engine_texts.items)
        extra_files.append(items_path)
        if items_state == "replaced":
            summary.notes.append(
                f"{shards.ITEMS_NAME} was made from other inputs (another catalog or other seen flags) and has been replaced; the files of "
                "the other trios in this folder were made with the earlier one, so run them again to bring them into line"
            )
    elif engine.remove_items(out):
        summary.notes.append(
            f"{shards.ITEMS_NAME} was removed: this run could not make the item table of its own inputs, and the one that stood was made from others"
        )
    summary.files = [*written, *extra_files]
    summary.phases["files"] = time.perf_counter() - mark
    for path in summary.files:
        data = path.read_bytes()
        name = path.relative_to(trio_dir, walk_up=True).as_posix()
        summary.sizes[name] = (len(data), shards.gzip_size(data))
        if path.name in shards.SHARD_NAMES:
            summary.violations.extend(shards.check_budget(path.name, data))
        elif path.parent.name == shards.RUNNERUP_DIR and path.name != "index.json":  # a runner-up file is fetched whole too
            summary.violations.extend(shards.check_budget(name, data))
    if summary.kept_first:
        summary.notes.append(
            f"{summary.kept_first} scenario(s) kept the first-stage kit: the tie stage found only a kit worth less, so the kit "
            "is the optimum, and which of several equal kits it is was left to the solver"
        )
    if summary.reused:
        summary.notes.append(f"{summary.reused} of {len(order)} chunks were already done")
    if summary.redone:
        summary.notes.append(f"{summary.redone} chunk file(s) were damaged or made from other inputs or code, and were redone")
    summary.elapsed = time.perf_counter() - started
    return summary
