"""The PC release build: precompute every trio of the grid, check the release, scan it, pack it and write it up.

The maintainer runs it from ``scripts/release-build.py``; :func:`build_release` is the same thing as a function. It prints counts and nothing else, and does
this in order:

0. **The code is hashed once**, at the start, before the pool: :func:`build_release` takes the hash of the code the chunks are made under and the hash of the code
   that writes the files, every worker uses those two values (in :class:`TrioSpec`) and never hashes the disk, and :func:`check_code_unchanged` refuses the release
   if a hashed file is not what it was, after the precompute and again just before the asset is packed (a worker runs the code it imported, and a module it
   imports later is read from the disk as it is then: a merge into the checkout in the middle of the hours would stamp chunks with the hash of code that did not
   make them). The same check covers the rest of the checkout and the inputs: the build root must be a git worktree (:class:`Git`), its HEAD, the digest of its
   status and the digest of its diff are recorded at the start, and the rules and the catalog are read once (:class:`Start`). A pool worker that starts after a
   change imports the code of the two lists and hashes it first (:func:`_init_worker`) and refuses its trios if the hashes are not the parent's. Run the build from
   a worktree of its own, at the commit to release.
1. **Before any hour is spent**, the tag, the seen-flags file, the privacy key and denylist, the previous release and the outputs are checked: a release tag is
   used once, and the key is tried on a folder before the scan that needs it comes at the end. What a build of this tag that was killed left in the build
   folder is taken away (:func:`clear_leftovers`, by exact name), the seen flags are copied once into ``build/`` and every later step reads the copy
   (:func:`snapshot_seen`: flags made again during the hours cannot mix two states), and what is already known to be amiss (the asset of the previous release is
   not there, a scheduled check is stale) is said at once as a warning. A tag with no pointer has nothing that is finished: what a run of it that did not end
   left and that looks like a release (its asset, its full diff of the first round, its Markdown report if git does not track it) is taken away too
   (:func:`clear_unfinished`; a report or a temporary file of a cut-short write that is tracked by git is refused, with the reason, and so is a git that cannot say
   whether one is: a decision to delete fails closed, :meth:`Git.tracked`), and every private file (the catalog with the flags merged among them) is checked against
   the path itself before it is written (:func:`check_private_output`: no link or junction on the way, and ``git check-ignore`` says it is ignored). The build folder
   must be ignored as a whole, or lie outside the work tree, before the first private file is written (:func:`check_build_folder`): a folder that ``.gitignore`` covers
   in part would show files in the status of the checkout during the hours, and the check at the end would refuse the release after them. The entries of the committed
   list of reports (``rules/community-seen.json``) are read once, with the reader of the catalog builder, and ``release.json`` records them (:func:`read_community`):
   the public catalog must have been built from that very file, or the entries and the evidence of the items would not describe the same state.
2. **The catalog with the seen flags merged** is built into ``build/catalog-with-seen/`` (:func:`build_seen_catalog`) and must come from the same inputs as the
   public ``derived/catalog.json`` (:func:`check_seen_catalog`). It never leaves ``build/``; it stands for the release's own catalog in the checks below.
3. **The precompute of the grid** (:func:`precompute_grid`): every trio of the grid at its default scope (:mod:`trioforge.scope`), one trio at a time in a
   worker process, a pool of them (``--processes``) with the heaviest trios first. A trio is the unit of the pool because the robustness seals and the flip
   check of :func:`trioforge.precompute.run` work in one process, and trios side by side keep every core busy through them. The item table is written once, by
   the parent, before any worker starts.
4. **Resumption.** A run that is stopped (killed, out of memory, switched off) is run again with the same command. A chunk file that is whole and was made
   from the same inputs (the catalog, the seen flags, the rules and tables, the code, the solver options: the fingerprint of the chunks) is kept; one made from
   other inputs is made again, which is what :func:`trioforge.precompute.run` does. A trio that finished is not even opened: ``chunks/complete.json`` holds the
   fingerprint, the scope and the digest of each result file, and a trio whose files are all as they were left under the same inputs is skipped
   (:func:`run_trio`). The leftovers of a write that was cut short are cleared first.
5. **The release folder** is staged (:func:`trioforge.precompute.assemble.stage`: links to the files of the results, never the chunks) so that every check
   reads exactly the files that ship.
6. **The checks**, each of which refuses the release with a message that says what and where:

   * :func:`check_grid`: every trio of the grid present, none partial, each at its default scope, each readable by the site build; a release is the whole
     grid (a build of some trios is a trial);
   * :func:`check_item_rows`: an item has the same row in every shard of every trio (the report of the changes compares one row for an item);
   * :func:`check_invariants`: the invariants of the design hold in the shipped shards (and no run reported a violation);
   * :func:`check_bundles`: every bundle is the one the exporter writes from the catalog with the seen flags merged, and its strict setups are the shard
     headers';
   * the browser's own reader of the bundles (:func:`check_bundle_reader`), the exact count of the files of the site (:func:`check_file_count`),
     a pruning spot check (:func:`check_pruning`: one random scenario of each trio solved again with the whole pool) and the parity suite
     (:func:`check_parity`: the engine against the reference, and against a sample of the shards and the defaults of every trio; the offset of the sample is drawn
     from the snapshot id, its stride is bounded so that every trio has chunks in it, and it is recorded in ``release.json``).

7. **``release.json``** is written into the folder, the report of what changed since the last release is made (:mod:`trioforge.reports.results_diff`), and the
   texts that are published are read: first for any path of this computer (:func:`check_no_local_paths`, whatever the build folder is called), then by the
   **keyed privacy scan** (:class:`PrivacyScanner`), which reads every file of the release and the text of the pointer and of the Markdown report: a finding
   refuses the release. The scan labels a file by its place in the release, so the build folder it stands in is no finding.
8. **The asset** is packed, held to the manifest of what was scanned, and ``releases/<tag>.json`` and ``reports/results-diff-<tag>.md`` are written, all or
   none, the pointer last; from the packing to the pointer is one transaction, and an error anywhere in it takes the asset away. The full diff, which names items and so tells which items the maintainer has seen, is written to ``build/reports/results-diff-<tag>.json``,
   away from the asset (an upload of what is named for the tag, ``build/release/<tag>.*``, cannot publish it), and is not published. A trial build (some trios only) writes no pointer, nothing in ``releases/`` or ``reports/``, and uses up no tag: its asset and its two
   reports are in ``build/trial/``, and both reports are headed TRIAL.

A refusal at any step leaves no output and no staging folder. Chunk files and fingerprints stay in ``build/``; the snapshot id is drawn when the release is
staged.
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import importlib
import io
import json
import multiprocessing
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from trioforge import community as community_module
from trioforge import precompute
from trioforge.data import catalog as catalog_module
from trioforge.data.jsonio import MAX_FILE_BYTES, JsonFileError, load_strict, loads_strict, render
from trioforge.export import browser
from trioforge.model import tables as tables_module
from trioforge.model import weapons as wp
from trioforge.model.roles import roles_for
from trioforge.precompute import assemble, engine, grid, shards
from trioforge.precompute.assemble import ReleaseRefused
from trioforge.privacy import scan as privacy_scan
from trioforge.reports import results_diff
from trioforge.scope import MILESTONE_TRIO, default_tiers
from trioforge.site import build, data
from trioforge.solver import solve as solver_solve
from trioforge.solver.model import build_milp
from trioforge.sources.client_tables import commit_files

__all__ = [
    "MARKER",
    "PARITY_FILES",
    "PARITY_MIN_CHUNKS",
    "SCHEDULED_CHECKS",
    "SEEN_SNAPSHOT",
    "SPOT_TOLERANCE",
    "Git",
    "PrivacyScanner",
    "ReleaseRefused",
    "ReleaseResult",
    "ScanReport",
    "SpotResult",
    "Start",
    "TrioFacts",
    "TrioOutcome",
    "TrioSpec",
    "build_release",
    "build_seen_catalog",
    "check_build_folder",
    "check_bundle_reader",
    "check_bundles",
    "check_code_unchanged",
    "check_consistent",
    "check_file_count",
    "check_grid",
    "check_invariants",
    "check_item_rows",
    "check_no_local_paths",
    "check_parity",
    "check_private_output",
    "check_pruning",
    "check_seen_catalog",
    "choose_parity_sample",
    "clear_leftovers",
    "clear_unfinished",
    "hashed_modules",
    "parity_sample",
    "parity_stride_ceiling",
    "parity_stride_limit",
    "precompute_grid",
    "privacy_gate",
    "read_community",
    "resolve_previous",
    "run_trio",
    "scheduled_warnings",
    "snapshot_seen",
    "work_tree_of",
    "write_item_table",
    "write_outputs",
]

#: the code, the Node files and the JavaScript tests of the checkout this module is in (the world a build reads may be another folder: ``root``)
CODE_ROOT = tables_module.REPO
MARKER = "complete.json"  # in a trio's chunks/ folder: the trio is finished, for these inputs, and these are its files
MARKER_FORMAT = 1
SPOT_TOLERANCE = 0.0101  # a shard keeps F to two decimals: the unpruned optimum, rounded the same way, may be a hundredth away
INVARIANT_SLACK = 0.0201  # the invariants are read from values of two decimals, and the naked value from the difference of two of them
PARITY_FILES = ("tests-js/parity-fixtures.test.mjs", "tests-js/engine-solve-parity.test.mjs", "tests-js/shard-parity.test.mjs")
PARITY_MIN_CHUNKS = 1  # the chunks of the sample of the shard parity that every trio has at least: the stride is no more than the smallest trio has chunks
SEEN_SNAPSHOT = "seen-flags-snapshot.json"  # in the build folder: the copy of the seen flags that the hours of a build read
SCHEDULED_CHECKS = ("sources-check", "smoke-live")  # the weekly checks of the PC: each leaves <build>/checks/<name>.last-run, an ISO time
STAMP_DAYS = 10
PROGRESS_SECONDS = 30.0
SAMPLE = re.compile(r"([0-9]{1,6})/([1-9][0-9]{0,5})")
LIST_LIMIT = 5  # the trios or findings a refusal names before it says how many more there are


def _more(names: Sequence[str], limit: int = LIST_LIMIT) -> str:
    shown = ", ".join(names[:limit])
    return shown + (f", and {len(names) - limit} more" if len(names) > limit else "")


# ---- one trio -------------------------------------------------------------------------------------------------------------------------------------


@dataclass
class TrioSpec:
    """What a worker needs to run one trio: paths as text (a spec is sent to a worker process), the scope (``tiers``; None is the default scope of the trio)
    and, for a test, a narrowing of the grid (``narrow``: the ``races``, ``roles``, ``evidence`` and ``buffs`` that :func:`trioforge.precompute.run` takes) or
    a ``limit`` of chunks. A run with a narrowing or a limit is not a full run: it leaves no marker. ``chunk_code`` and ``writer_code`` are the hashes of the code that
    the parent took at the start of the build: a worker runs the code it imported, and a module it imports later is read from the disk as it is then, so a worker that
    hashed the disk would stamp its files with the hash of code that did not make them."""

    slug: str
    results: str
    catalog: str
    seen: str | None = None
    tables_root: str | None = None
    tiers: tuple[int, ...] | None = None
    narrow: dict[str, list] = field(default_factory=dict)
    limit: int | None = None
    robustness: Any = None
    canonical: bool = True
    chunk_code: str | None = None  # the hash of the code the chunks are made under, and that of the code that writes the files: hashed once by the parent, at the
    writer_code: str | None = None  # start of the build, and used by every worker, which never hashes the disk (None: the run hashes it now, as a command does)


@dataclass
class TrioOutcome:
    """What a run of one trio did. ``status``: ``done``, ``resumed`` (a finished trio left as it was), ``limited`` and ``partial`` (a test's runs) or ``failed``
    (``error`` says why). The counts are those of :class:`trioforge.precompute.RunSummary`; a resumed trio reports the chunks it has, all of them reused."""

    slug: str
    status: str
    error: str = ""
    scenarios: int = 0
    chunks: int = 0
    solved: int = 0
    reused: int = 0
    redone: int = 0
    audited: int = 0
    kept_first: int = 0
    runnerup_chunks: int = 0
    runnerup_reused: int = 0
    seconds: float = 0.0
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


_COUNTS = ("scenarios", "chunks", "audited", "kept_first", "runnerup_chunks")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _result_digests(trio_dir: Path) -> dict[str, str]:
    """``{relative name: sha256}`` of every result file of a trio (its folder without the chunks)."""
    found: dict[str, str] = {}
    for here, dirs, files in os.walk(trio_dir):
        if Path(here) == trio_dir:
            dirs[:] = [name for name in dirs if name != "chunks"]
        for name in files:
            path = Path(here, name)
            found[path.relative_to(trio_dir).as_posix()] = _sha256(path)
    return dict(sorted(found.items()))


def _clear_leftovers(trio_dir: Path) -> None:
    """Take away the temporary files that a write cut short leaves (``.name.XXXX.tmp``): nothing else writes in a trio's folder while it is run."""
    for folder in (trio_dir, trio_dir / "chunks", trio_dir / shards.RUNNERUP_DIR):
        if folder.is_dir():
            for path in folder.glob(".*.tmp"):
                path.unlink(missing_ok=True)


def _read_marker(trio_dir: Path) -> dict[str, Any] | None:
    path = trio_dir / "chunks" / MARKER
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(marker, dict) or marker.get("format") != MARKER_FORMAT:
        return None
    done = marker.get("outcome")
    ok = (
        isinstance(marker.get("fingerprint"), str) and isinstance(marker.get("release"), list) and isinstance(marker.get("writer"), str)
        and isinstance(marker.get("tiers"), list) and isinstance(marker.get("files"), dict)
        and isinstance(done, dict) and all(isinstance(done.get(name), int) for name in _COUNTS)
        and isinstance(done.get("violations"), list) and isinstance(done.get("notes"), list)
    )  # fmt: skip
    return marker if ok else None  # (a marker that is not whole is no marker: the trio is run, from its chunks)


_WORKER = {"state": "unchecked", "problem": ""}  # "unchecked" (this process was not started by the pool of a build), "ok", or "mismatch" (and what the problem is)


def _hashes() -> tuple[str, str]:
    """The hash of the code the chunks are made under and the hash of the code that writes the files, from the disk now."""
    return grid._code_hash(), assemble.writer_hash()


def hashed_modules() -> list[str]:
    """The modules of the two lists of source files that the code hashes cover, by dotted name (the ``__init__`` of a package is the package)."""
    root = Path(assemble.__file__).resolve().parents[1]
    names = []
    for path in [*grid.code_files(), *assemble.writer_files()]:
        parts = path.resolve().relative_to(root).with_suffix("").parts
        names.append(".".join(("trioforge", *(parts[:-1] if parts[-1] == "__init__" else parts))))
    return names


def _init_worker(chunk_code: str, writer_code: str) -> None:
    """Run once in each worker process of the pool, when it starts: import every module of the two lists of hashed files, then hash the files. A worker that
    starts after the code was changed (a respawn after a crash, a module imported late) would run the changed code under the hashes of the start, and a later
    run that put the code back would reuse the chunks it made. A worker whose hashes are not the parent's refuses its trios, so the build is refused."""
    problem = ""
    try:
        for name in hashed_modules():
            importlib.import_module(name)
        now = _hashes()
    except Exception as error:  # noqa: BLE001 - a module that cannot be imported is code that is not what the parent ran
        problem = f"a module of the code could not be imported by a worker ({type(error).__name__}): the code on the disk is not the code the build began with"
        now = ("", "")
    if not problem and now != (chunk_code, writer_code):
        which = [name for name, here, there in (("the code of the chunks", now[0], chunk_code), ("the code that writes the files", now[1], writer_code)) if here != there]
        problem = f"the code on the disk is not the code the build began with ({' and '.join(which)}): a worker started after a change"
    _WORKER["state"], _WORKER["problem"] = ("mismatch", problem) if problem else ("ok", "")


def run_trio(spec: TrioSpec) -> TrioOutcome:
    """Run one trio at its scope, or leave it as it is when it is finished. Never raises for a fault of the trio: the outcome says ``failed``."""
    started = time.perf_counter()
    if _WORKER["state"] == "mismatch":
        return TrioOutcome(slug=spec.slug, status="failed", error=_WORKER["problem"], seconds=0.0)
    try:
        return _run_trio(spec, started)
    except Exception as error:  # noqa: BLE001 - a worker reports; the parent decides
        return TrioOutcome(slug=spec.slug, status="failed", error=f"{type(error).__name__}: {' '.join(str(error).split())}", seconds=time.perf_counter() - started)


def _run_trio(spec: TrioSpec, started: float) -> TrioOutcome:
    codes = grid.parse_trio(spec.slug)
    slug = grid.trio_slug(codes)
    tiers = tuple(spec.tiers) if spec.tiers is not None else default_tiers(codes)
    full = not spec.narrow and spec.limit is None
    trio_dir = Path(spec.results) / slug
    chunk_code = spec.chunk_code if spec.chunk_code is not None else grid._code_hash()  # (a build gives both: only a run on its own hashes the disk)
    writer = spec.writer_code if spec.writer_code is not None else assemble.writer_hash()  # (the code that writes the files)
    config, meta = grid.load_inputs(
        codes, catalog_path=spec.catalog, seen_path=spec.seen, tables_root=spec.tables_root, canonical=spec.canonical, code_hash=chunk_code
    )  # (the fingerprint of the chunks holds the code that decides the solves)
    headers = [meta.data_release, meta.game_patch, meta.rules_version]  # (what the headers of the files say; the fingerprint of the chunks does not hold the patch date)
    _clear_leftovers(trio_dir)
    marker = _read_marker(trio_dir) if full else None
    if (
        marker is not None and marker.get("fingerprint") == config.fingerprint and marker.get("release") == headers and marker.get("writer") == writer
        and marker.get("tiers") == list(tiers) and marker.get("files") == _result_digests(trio_dir)
    ):  # fmt: skip
        done = marker["outcome"]
        return TrioOutcome(
            slug=slug, status="resumed", reused=done["chunks"], violations=list(done["violations"]), notes=list(done["notes"]),
            **{name: done[name] for name in _COUNTS}, seconds=time.perf_counter() - started,
        )  # fmt: skip
    summary = precompute.run(
        slug, spec.results, seen_path=spec.seen, processes=1, catalog=spec.catalog, limit=spec.limit, canonical=spec.canonical, tiers=tiers,
        tables_root=spec.tables_root, robustness=spec.robustness, code_hash=chunk_code, **{name: list(values) for name, values in spec.narrow.items()},
    )  # fmt: skip
    status = "limited" if spec.limit is not None else "partial" if summary.partial else "done"
    outcome = TrioOutcome(
        slug=slug, status=status, scenarios=summary.scenarios, chunks=summary.chunks, solved=summary.solved, reused=summary.reused, redone=summary.redone,
        audited=summary.audited, kept_first=summary.kept_first, runnerup_chunks=summary.runnerup_chunks, runnerup_reused=summary.runnerup_reused,
        seconds=time.perf_counter() - started, violations=list(summary.violations), notes=list(summary.notes),
    )  # fmt: skip
    if status == "done":
        text = shards.dumps(
            {
                "format": MARKER_FORMAT, "fingerprint": config.fingerprint, "release": headers, "writer": writer, "tiers": list(tiers),
                "files": _result_digests(trio_dir),
                "outcome": {**{name: getattr(outcome, name) for name in _COUNTS}, "violations": outcome.violations, "notes": outcome.notes},
            }
        )  # fmt: skip
        commit_files(trio_dir / "chunks", {MARKER: text + "\n"}, last=MARKER)
    return outcome


# ---- the grid --------------------------------------------------------------------------------------------------------------------------------------


def write_item_table(
    results: str | os.PathLike[str], *, catalog: str | os.PathLike[str], seen: str | os.PathLike[str] | None, tables_root: str | os.PathLike[str] | None,
    chunk_code: str | None = None,
) -> str:
    """Write ``items.json`` of the folder of results before any worker starts, so that no two workers ever write it. It is made as every run makes it
    (:func:`trioforge.precompute.engine.make`: it depends on the catalog, the flags and the rules, not on the trio); the runs then find it as they would write it
    and leave it. Returns ``new``, ``same`` or ``replaced``."""
    out = Path(results)
    if seen is not None:
        try:
            catalog_module.check_seen_output(out)
        except catalog_module.BuildError as error:
            raise ReleaseRefused(str(error)) from None
    out.mkdir(parents=True, exist_ok=True)
    try:
        config, meta = grid.load_inputs(MILESTONE_TRIO, catalog_path=catalog, seen_path=seen, tables_root=tables_root, code_hash=chunk_code)
        texts = engine.make(MILESTONE_TRIO, config, meta, tables_module.load(config.tables_root), catalog_path=catalog, seen_path=seen, setups={})
    except (OSError, ValueError, JsonFileError, catalog_module.BuildError) as error:
        raise ReleaseRefused(f"the catalog cannot be read for the item table: {' '.join(str(error).split())}") from None
    if texts.items is None:
        raise ReleaseRefused("the item table cannot be made: " + "; ".join(texts.problems))
    return engine.write_items(out, texts.items)[1]


def _weight(spec: TrioSpec) -> int:
    """A guess at how long a trio takes, only to run the heavy ones first: its roles times its tiers."""
    try:
        codes = grid.parse_trio(spec.slug)
    except ValueError:
        return 0  # (the run of it says what is wrong)
    return len(roles_for(codes)) * len(spec.tiers if spec.tiers is not None else default_tiers(codes))


def _run_pool(
    specs: Sequence[TrioSpec], runner: Callable[[TrioSpec], TrioOutcome], processes: int, on_outcome: Callable[[int, TrioOutcome], None],
    initargs: tuple[str, str] | None = None,
) -> None:
    """Run ``runner`` over the specs in a pool of worker processes, or in this process when there is one worker; call ``on_outcome(index, outcome)`` as each ends.
    With ``initargs`` (the two hashes of the start) each worker checks its code against them when it starts (:func:`_init_worker`)."""
    if processes <= 1 or len(specs) <= 1:
        for index, spec in enumerate(specs):
            on_outcome(index, runner(spec))
        return
    try:
        precompute._check_workers_can_start(sys.modules.get("__main__"))
    except precompute.PrecomputeError as error:
        raise ReleaseRefused(str(error)) from None
    options = {"initializer": _init_worker, "initargs": initargs} if initargs is not None else {}
    executor = ProcessPoolExecutor(max_workers=min(processes, len(specs)), mp_context=multiprocessing.get_context("spawn"), **options)
    futures = {executor.submit(runner, spec): index for index, spec in enumerate(specs)}
    try:
        for future in as_completed(futures):
            try:
                outcome = future.result()
            except BrokenProcessPool:
                raise ReleaseRefused("a worker process died (out of memory?); the finished chunks are kept: run the same command again to continue") from None
            on_outcome(futures[future], outcome)
    except BaseException:
        for future in futures:
            future.cancel()
        for process in list(getattr(executor, "_processes", {}).values()):  # stop the workers now: a chunk file is written whole or not at all
            process.terminate()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    executor.shutdown(wait=True)


def _clock(seconds: float) -> str:
    seconds = int(max(0, seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def precompute_grid(
    specs: Sequence[TrioSpec], *, processes: int = 1, say: Callable[[str], None] = print, runner: Callable[[TrioSpec], TrioOutcome] | None = None,
    hashes: tuple[str, str] | None = None, check_workers: bool = True,
) -> list[TrioOutcome]:
    """Run the trios of ``specs`` (see the module docstring) and return their outcomes in the order of the specs. A trio that fails does not stop the others
    (its outcome says ``failed``); a catalog or flags that cannot be read stop everything. Prints, at most every half minute, how many trios are done and a
    guess at the time left from the pace so far (counts only). The code is hashed here, once, before the pool starts, for every spec that does not carry its hashes
    (``hashes`` is ``(code of the chunks, code that writes the files)``, for a caller that has them), and every worker uses those and, when it starts, checks that
    the code on the disk is the code they describe (``check_workers`` False leaves that out, for a caller that gives hashes that no disk has)."""
    specs = list(specs)
    if not specs:
        return []
    if any(spec.chunk_code is None or spec.writer_code is None for spec in specs):
        chunk_code, writer_code = hashes if hashes is not None else (grid._code_hash(), assemble.writer_hash())
        specs = [replace(spec, chunk_code=spec.chunk_code or chunk_code, writer_code=spec.writer_code or writer_code) for spec in specs]
    first = specs[0]
    write_item_table(first.results, catalog=first.catalog, seen=first.seen, tables_root=first.tables_root, chunk_code=first.chunk_code)
    run = runner or run_trio
    weights = [_weight(spec) for spec in specs]
    order = sorted(range(len(specs)), key=lambda index: (-weights[index], specs[index].slug))
    outcomes: dict[int, TrioOutcome] = {}
    started = time.monotonic()
    last = [started]
    active = [0.0, 0]  # seconds and weight of the trios that were really run, for the pace

    def on_outcome(index: int, outcome: TrioOutcome) -> None:
        outcomes[index] = outcome
        if outcome.status in ("done", "partial", "limited"):
            active[0] += outcome.seconds
            active[1] += weights[index]
        now = time.monotonic()
        if len(outcomes) == len(specs) or now - last[0] >= PROGRESS_SECONDS:
            last[0] = now
            left = sum(weights[i] for i in range(len(specs)) if i not in outcomes)
            guess = f", about {_clock(left * active[0] / active[1] / max(1, processes))} to go at this pace" if active[1] and left else ""
            resumed = sum(1 for o in outcomes.values() if o.status == "resumed")
            failed = sum(1 for o in outcomes.values() if o.status == "failed")
            say(f"trios {len(outcomes)}/{len(specs)} ({resumed} resumed{f', {failed} failed' if failed else ''}), {_clock(now - started)} elapsed{guess}")

    initargs = (first.chunk_code, first.writer_code) if check_workers and first.chunk_code is not None and first.writer_code is not None else None
    _run_pool([specs[i] for i in order], run, processes, lambda position, outcome: on_outcome(order[position], outcome), initargs=initargs)
    return [outcomes[index] for index in range(len(specs))]


# ---- what a check reads ----------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TrioFacts:
    """What the other checks need of a trio they have read: its scope, roles and levels, and the run it is of."""

    slug: str
    tiers: tuple[int, ...]
    roles: tuple[str, ...]
    levels: tuple[int, ...]
    data_tag: str
    rules_version: str
    game_patch: str
    level: int
    chunks: int = 0  # the views the trio has in its four shards, each shard counted once (as the parity suite numbers them): what its sample is drawn from


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _incomplete(folder: Path, slug: str) -> list[str]:
    """The files a trio's folder lacks (all of them when there is no folder)."""
    base = folder / slug
    if not base.is_dir():
        return ["folder"]
    lacking = [name for name in (*shards.SHARD_NAMES, "defaults.json", "robust.json", f"{shards.RUNNERUP_DIR}/index.json") if not (base / name).is_file()]
    if not list(base.glob(f"{shards.ENGINE_PREFIX}*.json")):
        lacking.append(f"{shards.ENGINE_PREFIX}<level>.json")
    return lacking


def check_consistent(facts: Sequence[TrioFacts]) -> None:
    """Every trio of a release is of one data release, one rules version, one game patch and one level: :class:`ReleaseRefused` names the first two that differ."""
    if not facts:
        return
    first = facts[0]
    for other in facts[1:]:
        for name in ("data_tag", "rules_version", "game_patch", "level"):
            if getattr(other, name) != getattr(first, name):
                raise ReleaseRefused(
                    f"the trios are not of one data release and one run: {first.slug} has {name} {getattr(first, name)} and {other.slug} has {getattr(other, name)}"
                )


def check_grid(folder: str | os.PathLike[str], trios: Sequence[str], *, scopes: Mapping[str, Sequence[int]] | None = None) -> list[TrioFacts]:
    """Every trio of ``trios`` is in ``folder``, complete, not partial, at its default scope (``scopes`` names another for a sample), and read by the site build.

    Refused, by name: a trio with no folder or a file missing (``missing``), a trio made by a narrowed run (``partial``), a trio whose shards have other tiers than a full
    run of it (:func:`trioforge.site.build.check_scope`) and any file the site build's own reader (:func:`trioforge.site.data.load_trio`) cannot read.
    Returns the facts of each trio, in order."""
    base = Path(folder)
    trios = list(dict.fromkeys(trios))
    gaps = {slug: _incomplete(base, slug) for slug in trios}
    missing = [slug if gap == ["folder"] else f"{slug} (no {', no '.join(gap)})" for slug, gap in gaps.items() if gap]
    if missing:
        raise ReleaseRefused(f"{len(missing)} trio{'s' if len(missing) != 1 else ''} of the grid {'are' if len(missing) != 1 else 'is'} missing: {_more(missing)}")
    partial: list[str] = []
    chunk_counts: dict[str, int] = {}
    for slug in trios:
        documents = [_json(base / slug / name) for name in shards.SHARD_NAMES]
        if any(document.get("partial") for document in documents):
            partial.append(slug)
        chunk_counts[slug] = sum(len({(row[1], row[3], row[2]) for row in document["scenarios"]}) for document in documents)  # role, setup and tier of a row
    if partial:
        raise ReleaseRefused(
            f"{_more(partial)}: partial, made by a run of some of the races, roles, evidence levels or buff sets "
            f"({len(partial)} trio{'s' if len(partial) != 1 else ''} of the grid)"
        )
    found: list[TrioFacts] = []
    for slug in trios:
        tiers = _json(base / slug / "wiki-own.json").get("tiers", [])
        try:
            build.check_scope(slug, tiers, (scopes or {}).get(slug))
            trio = data.load_trio(base / slug)
            build.check_scopes([trio], {slug: scopes[slug]} if scopes and slug in scopes else None)
            build.check_defaults(trio)
        except (data.ResultsError, build.BuildError) as error:
            what = "cannot be read by the site build" if isinstance(error, data.ResultsError) else "is refused by the site build"
            raise ReleaseRefused(f"{slug} {what}: {error}") from None
        meta = trio.meta
        levels = tuple(sorted(int(path.name.removeprefix(shards.ENGINE_PREFIX).removesuffix(".json")) for path in (base / slug).glob(f"{shards.ENGINE_PREFIX}*.json")))
        found.append(
            TrioFacts(
                slug, trio.tiers, tuple(trio.shards[("wiki", "own")].roles), levels, meta.data_tag, meta.rules_version, meta.game_patch, meta.level,
                chunk_counts[slug],  # (each shard at its own level, as the parity suite numbers them: a bundle of another level adds none)
            )
        )
    check_consistent(found)
    return found


def check_item_rows(folder: str | os.PathLike[str], trios: Sequence[str]) -> int:
    """Every shard and every trio of a release shows an item with the same row (its name, slots, tier rule, arrival, source text and evidence level): the row is
    made from the item, the rules and the flags alone, so a row that differs is a release made of two runs, or made wrong. A report of the changes between releases
    compares one row for an item, so it is held to be the only one. Returns the number of items."""
    base = Path(folder)
    first: dict[str, tuple[list[Any], str]] = {}
    differing: dict[str, str] = {}
    for slug in trios:
        for name in shards.SHARD_NAMES:
            for row in _json(base / slug / name)["items"]:
                if not isinstance(row, list) or not row or not isinstance(row[0], str):
                    raise ReleaseRefused(f"{slug}/{name} has an item that is not a row of the item table")
                known = first.setdefault(row[0], (row, f"{slug}/{name}"))
                if known[0] != row and row[0] not in differing:
                    differing[row[0]] = f"{row[0]} ({known[1]} and {slug}/{name})"
    if differing:
        raise ReleaseRefused(
            f"{len(differing)} item(s) have a row in one shard that is not their row in another, as if the release were made of two runs: {_more(list(differing.values()), 3)}"
        )
    return len(first)


def check_invariants(folder: str | os.PathLike[str], trios: Sequence[str], outcomes: Iterable[TrioOutcome] = ()) -> int:
    """The invariants of the design hold in the shipped shards (:func:`trioforge.precompute.shards.check_invariants`, read from values of two decimals, so with the
    slack of that rounding) and the naked character's value is one number for each race, role and buff set; no run of a trio reported a violation either.
    Returns the number of trios checked."""
    base = Path(folder)
    problems = [f"{outcome.slug}: {violation}" for outcome in outcomes for violation in outcome.violations]
    for slug in trios:
        values: dict[tuple[str, str, str, str, int, str], float] = {}
        naked: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for name in shards.SHARD_NAMES:
            evidence, buffs = name.removesuffix(".json").split("-")
            for race, role, tier, setup, _kit, value, gain, *_ in _json(base / slug / name)["scenarios"]:
                values[(evidence, buffs, role, setup, tier, race)] = value
                naked[(race, role, buffs)].append(round(value - gain, 2))
        bases: dict[tuple[str, str, str], float] = {}
        for key, found in naked.items():
            if max(found) - min(found) > INVARIANT_SLACK:
                problems.append(f"{slug}: the naked character's value is not one number for {key[0]} {key[1]} with {key[2]} buffs: {min(found)} to {max(found)}")
            bases[key] = sum(found) / len(found)
        problems += [f"{slug}: {text}" for text in shards.check_invariants(values, bases, slack=INVARIANT_SLACK)]
    if problems:
        raise ReleaseRefused(f"the invariants of the design do not hold ({len(problems)}): " + _more(problems, 3))
    return len(list(trios))


COMMUNITY_INPUT = "rules/community-seen.json"  # how the provenance of the public catalog names the list of reports it was built from


def read_community(rules: str | os.PathLike[str], public_document: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The community entries of a release: ``{"reports", "retracted"}`` as ``rules/community-seen.json`` of the checkout holds them, read once and held to the form of the file
    (the reader of the catalog builder, with the day after which an entry is refused being today). ``release.json`` records them, and the report of the release lists what was
    added and retracted from them.

    They are the entries of the release only if the public catalog was built from this very file: its provenance records the SHA-256 of the list of reports it was built from,
    and a file the catalog does not record, another file, or a file that is not there while the catalog records one is refused (the evidence of the items would rest on
    other entries than the ones recorded). No file, and a catalog that records none, is a release without entries. :class:`ReleaseRefused` with one line that never repeats
    what the file said.
    """
    path = Path(rules) / "community-seen.json"
    inputs = (public_document.get("provenance") or {}).get("inputs") or ()
    recorded = [record.get("sha256") for record in inputs if isinstance(record, Mapping) and record.get("file") == COMMUNITY_INPUT]
    if not path.exists():
        if recorded:
            raise ReleaseRefused(
                f"the public catalog was built from {COMMUNITY_INPUT}, which is not in the checkout: restore the file, or build the catalog again without it"
            )
        return {"reports": [], "retracted": []}
    try:
        data = path.read_bytes()
        document = community_module.check_document(loads_strict(data.decode("utf-8"), path.name), today=community_module.today_utc())
    except (OSError, UnicodeDecodeError):
        raise ReleaseRefused(f"{COMMUNITY_INPUT} cannot be read") from None
    except (JsonFileError, community_module.CommunityError) as error:
        raise ReleaseRefused(" ".join(str(error).split())) from None
    if recorded != [hashlib.sha256(data).hexdigest()]:
        raise ReleaseRefused(
            f"{COMMUNITY_INPUT} of the checkout is not the file the public catalog was built from (its provenance does not record this one): build the catalog again"
        )
    return {"reports": document["reports"], "retracted": document["retracted"]}


def check_seen_catalog(public: str | os.PathLike[str], merged: str | os.PathLike[str]) -> None:
    """The catalog with the seen flags merged is of the same snapshot as the public one, made from the same inputs, and lists the same items: it may differ in the
    evidence of the items and in nothing else that this looks at. :class:`ReleaseRefused` otherwise."""
    try:
        one, other = load_strict(public), load_strict(merged)
    except (OSError, JsonFileError) as error:
        raise ReleaseRefused(f"a catalog cannot be read: {error}") from None
    if one.get("version") != other.get("version"):
        raise ReleaseRefused(
            f"the catalog with the seen flags merged is of the snapshot {other.get('version')} and the public catalog of {one.get('version')}: build both from one fetch"
        )
    if (one.get("provenance") or {}).get("inputs") != (other.get("provenance") or {}).get("inputs"):
        raise ReleaseRefused("the catalog with the seen flags merged and the public catalog were not made from the same inputs (wiki fetch, client files, quests, rules)")
    if [item["key"] for item in one["items"]] != [item["key"] for item in other["items"]]:
        raise ReleaseRefused("the catalog with the seen flags merged and the public catalog do not list the same items")


@contextlib.contextmanager
def _scratch_folder(beside: Path, name: Path | None) -> Iterator[Path]:
    """An empty folder for a check to work in: the folder ``name`` (made empty first, and removed after: so it must be a ``*.bundles`` folder beside ``beside``, the
    folder that is checked, and nothing else), or a temporary one beside ``beside``."""
    if name is None:
        with tempfile.TemporaryDirectory(prefix="bundles-", dir=beside) as folder:
            yield Path(folder)
        return
    scratch = Path(name)
    if not scratch.name.endswith(".bundles") or scratch.name == ".bundles" or scratch.parent.resolve() != Path(beside).resolve():
        raise ReleaseRefused(
            f"the scratch folder {scratch.name!r} is not a folder named *.bundles beside the release folder: a build passes <folder>/<tag>.bundles and nothing else, "
            "because what is at the name is removed"
        )
    _remove_leftover(scratch)
    scratch.mkdir(parents=True)
    try:
        yield scratch
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _remove_leftover(path: Path) -> None:
    """Take away what a killed build left at this exact name (a folder, a file, or nothing). A link is refused, not followed."""
    if not os.path.lexists(path):
        return
    if assemble._is_link(path):
        raise ReleaseRefused(f"{path.name} is a link, and a build does not remove a link: take it away")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def clear_leftovers(folder: str | os.PathLike[str], tag: str) -> list[str]:
    """At the start of a build of ``tag``: take away what a build of the same tag that was killed left in its output ``folder``, and nothing else (the staging
    folder, the scratch folder of the bundle check and the temporary file of the asset, each by its exact name, which holds the tag). Returns the names removed."""
    removed = []
    for name in (f"{tag}.stage", f"{tag}.bundles", f"{tag}.tar.gz.tmp"):
        path = Path(folder) / name
        if os.path.lexists(path):
            _remove_leftover(path)
            removed.append(name)
    return removed


def clear_unfinished(base: str | os.PathLike[str], out_dir: str | os.PathLike[str], tag: str, git: Any, *, trial: bool = False) -> list[str]:
    """At the start of a build of ``tag``, which has no pointer ``releases/<tag>.json``: take away what a run of the same tag that did not finish left behind, by
    exact names. An asset ``<out_dir>/<tag>.tar.gz`` with no pointer was renamed into place before the run ended: it looks publishable, and is not. A Markdown
    report ``reports/results-diff-<tag>.md`` that git does not track was written before the end, and would make every retry refuse the tag; one that is tracked by git is
    refused, with the reason (a trial writes no report there). The full diff of the first round, ``<out_dir>/<tag>.results-diff.json``, was beside the asset where
    an upload of ``<tag>.*`` would take it. The temporary files of a write of the pointer or of the report that was cut short (``releases/.<tag>.json.*.tmp``,
    ``reports/.results-diff-<tag>.md.*.tmp``) are in tracked folders, where a ``git add -A`` would take them; one that is tracked by git is refused like the report.
    Every decision comes before the first removal, and fails closed: a refusal (a file that is tracked by git, or a git that cannot say whether it is: :meth:`Git.tracked`)
    leaves everything as it was found. Returns the names removed."""
    report = Path(base) / "reports" / f"results-diff-{tag}.md"
    temporary: list[Path] = []
    if not trial:
        for folder, pattern in (("reports", f".results-diff-{tag}.md.*.tmp"), ("releases", f".{tag}.json.*.tmp")):
            temporary += sorted((Path(base) / folder).glob(pattern))
    if not trial and os.path.lexists(report) and git.tracked(report):
        raise ReleaseRefused(
            f"reports/results-diff-{tag}.md already exists, is tracked by git, and has no pointer releases/{tag}.json: it is the report of a release that was never "
            "finished, or of a tag used without its pointer. Take it out with git (git rm) or use another tag; the build does not remove a file that is tracked by git"
        )
    for path in temporary:
        if git.tracked(path):
            raise ReleaseRefused(
                f"{path.parent.name}/{path.name} is tracked by git, and is named like the temporary file of a write of {tag} that was cut short: the build does not remove a file "
                "that is tracked by git. Take it out with git (git rm) and run the build again"
            )
    removed = []
    if not trial and os.path.lexists(report):
        _remove_leftover(report)
        removed.append(f"reports/results-diff-{tag}.md")
    for name in (f"{tag}.tar.gz", f"{tag}.results-diff.json", *((f"{tag}.results-diff.md",) if trial else ())):
        path = Path(out_dir) / name
        if os.path.lexists(path):
            _remove_leftover(path)
            removed.append(name)
    for path in temporary:
        _remove_leftover(path)
        removed.append(f"{path.parent.name}/{path.name}")
    return removed


def check_bundles(
    folder: str | os.PathLike[str], trios: Sequence[str], *, seen_catalog: str | os.PathLike[str], tables_root: str | os.PathLike[str] | None = None,
    scratch: str | os.PathLike[str] | None = None,
) -> int:
    """Every bundle of the release is what the exporter writes from the catalog with the seen flags merged, and its weapon setups follow the shard headers.

    The exporter is run as its command does (:func:`trioforge.export.browser.main` with ``--catalog``) for all the trios, into a scratch folder beside the release, and
    each bundle it writes must equal the shipped one but for the ``inputs`` field the precompute added. A bundle exported from the public catalog has no strict item
    and so no strict shield: its strict setups would differ from the shards'. The evidence level of every item in ``items.json`` must be the catalog's. Returns the
    number of bundles. The exporter works in ``scratch`` (a folder of the exact name given, made empty first and removed after, so that a build that is killed can
    find and clear it) or in a temporary folder beside the release."""
    base = Path(folder)
    trios = list(trios)
    problems: list[str] = []
    try:
        merged = load_strict(seen_catalog)
    except (OSError, JsonFileError) as error:
        raise ReleaseRefused(f"the catalog with the seen flags merged cannot be read: {error}") from None
    with _scratch_folder(base.parent, Path(scratch) if scratch is not None else None) as made:
        argv = ["--out", str(made), "--catalog", str(seen_catalog)]
        if tables_root is not None:
            argv += ["--root", str(tables_root)]
        for slug in trios:
            argv += ["--trio", slug]
        errors = io.StringIO()
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                status = browser.main(argv)
        except (RuntimeError, ValueError, KeyError, TypeError) as error:  # (a fault of the exporter's own checks: its profiles do not reassemble, say)
            raise ReleaseRefused(f"the exporter failed on the catalog with the flags merged: {type(error).__name__}: {' '.join(str(error).split())}") from None
        if status != 0:
            raise ReleaseRefused(f"the exporter refused the catalog with the flags merged: {' '.join(errors.getvalue().split())}")
        table_inputs = load_strict(base / assemble.ITEMS_FILE).get(browser.INPUTS_FIELD)
        for slug in trios:
            problems += _bundle_problems(base, slug, made / "bundles", table_inputs)
    wearable = {item["key"]: item["evidence"]["level"] for item in merged["items"] if grid.WEARABLE_SLOTS & set(item["slots"])}
    shipped_levels = assemble.evidence_map(load_strict(base / assemble.ITEMS_FILE))
    for key in sorted(set(wearable) | set(shipped_levels)):
        if wearable.get(key) != shipped_levels.get(key):
            problems.append(f"{key}: its evidence level in items.json is {shipped_levels.get(key)} and {wearable.get(key)} in the catalog with the flags merged")
    if problems:
        raise ReleaseRefused(f"{len(problems)} bundle problem(s): " + _more(problems, 3))
    return len(trios)


def _setups(bundle: Mapping[str, Any], role: str, evidence: str) -> list[str]:
    return list(bundle.get("roles", {}).get(role, {}).get("setups_by_evidence", {}).get(evidence, []))


def _bundle_problems(base: Path, slug: str, exported: Path, table_inputs: Any) -> list[str]:
    found: list[str] = []
    bundles = sorted((base / slug).glob(f"{shards.ENGINE_PREFIX}*.json"))
    for path in bundles:
        shipped = loads_strict(path.read_text(encoding="utf-8"), path.name)
        if shipped.pop(browser.INPUTS_FIELD, None) != table_inputs or table_inputs is None:
            found.append(f"{slug}: the bundle and items.json were not made from the same inputs (another catalog, or other seen flags): make {slug} again")
        for evidence in ("strict", "wiki"):
            for buffs in ("own", "group"):
                header = _json(base / slug / f"{evidence}-{buffs}.json")["setups"]
                for role, setups in header.items():
                    listed = shipped["roles"].get(role, {}).get("setups_by_evidence", {}).get(evidence)
                    if listed != setups:
                        found.append(f"{slug}: the {evidence} setups of the {role} role are {' '.join(setups)} in {evidence}-{buffs}.json and {' '.join(listed or [])} in the bundle")
        made = exported / path.name.replace(shards.ENGINE_PREFIX, f"{slug}-l", 1)
        if not made.is_file():
            found.append(f"{slug}: the exporter wrote no bundle for {path.name}")
            continue
        expected = loads_strict(made.read_text(encoding="utf-8"), made.name)
        if browser.render_bundle(shipped) != made.read_text(encoding="utf-8"):
            detail = [
                f"the {evidence} setups of the {role} role are {' '.join(row['setups_by_evidence'][evidence])} in the release and {' '.join(_setups(expected, role, evidence))} in the export"
                for role, row in shipped["roles"].items() for evidence in ("strict", "wiki")
                if row["setups_by_evidence"][evidence] != _setups(expected, role, evidence)
            ]  # fmt: skip
            found.append(f"{slug}: the bundle is not the one the exporter writes from the catalog with the flags merged" + (f" ({detail[0]})" if detail else ""))
    return found


def check_bundle_reader(folder: str | os.PathLike[str], trios: Sequence[str], *, batch: int = 40) -> dict[str, int]:
    """Run the browser's own reader on the bundle of every trio, in Node (:func:`trioforge.site.build.check_engine_data`: ``readBundle``, the tier and weapon rules, and
    ``assembleProfile`` for every race, role, buff set and evidence level of each), together with the item table. A bundle it refuses (too many exact numbers, a field
    it does not know, a forbidden name ...) refuses the release: without this it would surface on a visitor's page. Returns the counts it went through."""
    base = Path(folder)
    raw = (base / assemble.ITEMS_FILE).read_bytes()
    table = data.BrowserFile(assemble.ITEMS_FILE, raw, {})
    totals = {"records": 0, "tiers": 0, "bundles": 0, "profiles": 0}
    trios = list(trios)
    for start in range(0, len(trios), batch):
        sent = []
        for slug in trios[start : start + batch]:
            paths = sorted((base / slug).glob(f"{shards.ENGINE_PREFIX}*.json"))
            if not paths:
                raise ReleaseRefused(f"{slug} has no bundle ({shards.ENGINE_PREFIX}<level>.json) for the browser to read")
            sent += [SimpleNamespace(meta=SimpleNamespace(slug=slug), bundle=data.BrowserFile(path.name, path.read_bytes(), {})) for path in paths]
        try:
            counts = build.check_engine_data(table, sent)  # type: ignore[arg-type]
        except build.BuildError as error:
            raise ReleaseRefused(f"the browser's own reader refuses a bundle of the release: {error}") from None
        totals["records"], totals["tiers"] = counts["records"], counts["tiers"]
        totals["bundles"] += counts["bundles"]
        totals["profiles"] += counts["profiles"]
    return totals


def check_file_count(facts: Sequence[TrioFacts], evidence: Mapping[str, str], *, assets: Sequence[str] | None = None) -> int:
    """The exact number of the files of the site this release would make (:func:`trioforge.site.build.site_files`: the trios with their roles, scopes and levels, an
    item page for each strict or wiki item of the evidence map, the fixed pages and the page code) is at most the budget (15,000). ``assets`` are the names of the page
    code; None bundles it, as a build does (it needs Node and esbuild). Returns the count."""
    try:
        names = tuple(assets) if assets is not None else build.page_code_files()
        pages = sorted(key for key, level in evidence.items() if level in ("strict", "wiki"))
        listed = build.site_files([build.TrioFiles(f.slug, f.roles, f.tiers, f.levels) for f in facts], assets=names, item_pages=pages, noindex=False)
        return build.check_file_budget(listed)
    except build.BudgetError as error:
        raise ReleaseRefused(str(error)) from None
    except build.BuildError as error:
        raise ReleaseRefused(f"the files of the site cannot be listed: {error}") from None


@dataclass(frozen=True)
class SpotResult:
    """The pruning spot check of one trio: the scenario drawn, its value in the shard, the unpruned optimum, and whether they agree."""

    slug: str
    view: dict[str, Any]
    shipped: float
    solved: float
    ok: bool
    message: str = ""


def _spot_task(spec: Mapping[str, Any]) -> SpotResult:
    slug = spec["slug"]
    rows: list[tuple[str, str, str, str, int, str, float]] = []
    for name in shards.SHARD_NAMES:
        evidence, buffs = name.removesuffix(".json").split("-")
        rows += [(evidence, buffs, r[0], r[1], r[2], r[3], r[5]) for r in _json(Path(spec["folder"]) / slug / name)["scenarios"]]
    evidence, buffs, race, role, tier, setup, shipped = random.Random(f"{spec['seed']}/{slug}").choice(rows)
    view = {"evidence": evidence, "buffs": buffs, "race": race, "role": role, "tier": tier, "setup": setup}
    try:
        codes = grid.parse_trio(slug)
        config, _ = grid.load_inputs(
            codes, catalog_path=spec["catalog"], seen_path=spec["seen"], tables_root=spec["tables_root"], canonical=True, code_hash=spec.get("chunk_code")
        )
        context = grid.Context(config)
        profile = context.profile(race, role, buffs, evidence)
        solution = solver_solve.solve(build_milp(profile, context.pool(evidence, tier), setup, context.buffsets[buffs], grid.BUILD_OPTIONS))
    except Exception as error:  # noqa: BLE001
        return SpotResult(slug, view, shipped, float("nan"), False, f"the unpruned solve failed: {type(error).__name__}: {' '.join(str(error).split())}")
    if solution.status != "optimal" or solution.F is None:
        return SpotResult(slug, view, shipped, float("nan"), False, f"the unpruned solve ended {solution.status}, not optimal")
    solved = round(float(solution.F), 2)
    ok = abs(solved - shipped) <= SPOT_TOLERANCE
    return SpotResult(slug, view, shipped, solved, ok, "" if ok else f"the shard has {shipped} and the unpruned optimum is {solved}")


def _map(function: Callable[[Any], Any], items: Sequence[Any], processes: int) -> list[Any]:
    if processes <= 1 or len(items) <= 1:
        return [function(item) for item in items]
    results: dict[int, Any] = {}
    with ProcessPoolExecutor(max_workers=min(processes, len(items)), mp_context=multiprocessing.get_context("spawn")) as executor:
        futures = {executor.submit(function, item): index for index, item in enumerate(items)}
        try:
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        except BrokenProcessPool:
            raise ReleaseRefused("a worker process died during the pruning spot check") from None
    return [results[index] for index in range(len(items))]


def check_pruning(
    folder: str | os.PathLike[str], trios: Sequence[str], *, catalog: str | os.PathLike[str], seen: str | os.PathLike[str] | None,
    tables_root: str | os.PathLike[str] | None = None, seed: int | None = None, processes: int = 1, chunk_code: str | None = None,
) -> list[SpotResult]:
    """One random scenario of each trio (drawn from the rows of its shipped shards, from ``seed``, which a run chooses at random) is solved again with the **whole**
    pool and no pruning; its value, rounded as a shard keeps it, must be the shard's (to a hundredth). Refused if any trio's is not. Returns the results."""
    seed = secrets.randbits(32) if seed is None else seed
    specs = [
        {
            "slug": slug, "folder": str(folder), "catalog": str(catalog), "seen": None if seen is None else str(seen),
            "tables_root": None if tables_root is None else str(tables_root), "seed": seed, "chunk_code": chunk_code,
        }
        for slug in trios
    ]  # fmt: skip
    results = _map(_spot_task, specs, processes)
    bad = [r for r in results if not r.ok]
    if bad:
        names = [f"{r.slug} ({r.view['race']} {r.view['role']} +{r.view['tier']} {r.view['setup']}, {r.view['evidence']}, {r.view['buffs']} buffs): {r.message}" for r in bad]
        raise ReleaseRefused(f"the pruning spot check failed for {len(bad)} trio(s), the pruned optimum of a shard against the unpruned one (seed {seed}): " + _more(names, 3))
    return results


def _check_sample(sample: str) -> str:
    found = SAMPLE.fullmatch(sample) if isinstance(sample, str) else None
    if found is None or int(found.group(1)) >= int(found.group(2)):
        raise ReleaseRefused(f"the parity sample {sample!r} is not i/n (the chunks i, i+n, i+2n ...), with i from 0 to n-1, such as 3/36")
    return sample


def _vitest(folder: Path, sample: str, files: Sequence[str]) -> tuple[int, str]:
    node = shutil.which("node")
    entry = CODE_ROOT / "node_modules" / "vitest" / "vitest.mjs"
    if node is None or not entry.is_file():
        raise OSError("Node and vitest are needed (run `npm ci --ignore-scripts`)")
    environment = {**os.environ, "TRIOFORGE_RESULTS": str(folder), "TRIOFORGE_SHARD_SAMPLE": sample, "NODE_OPTIONS": "--max-old-space-size=16384"}
    done = subprocess.run(
        [node, str(entry), "run", *files, "--reporter=dot"], cwd=CODE_ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    return done.returncode, done.stdout + done.stderr


def check_parity(
    folder: str | os.PathLike[str], *, sample: str, files: Sequence[str] = PARITY_FILES, runner: Callable[[Path, str, Sequence[str]], tuple[int, str]] | None = None
) -> None:
    """Run the parity suite: the tests that hold the browser engine to the Python reference (the fixtures, and the engine's solves) and the shard parity on ``folder``
    (the release), on the sample ``sample`` of its chunks (:func:`choose_parity_sample` makes it) and on the ``defaults.json`` of every trio, which the sample does not
    leave out. ``runner(folder, sample, files)`` returns ``(exit status, output)``; the default starts Node. A failure refuses the release and shows the end of the
    output."""
    _check_sample(sample)
    try:
        status, output = (runner or _vitest)(Path(folder), sample, tuple(files))
    except OSError as error:
        raise ReleaseRefused(f"the parity suite could not be run: {error}") from None
    if status != 0:
        tail = "\n".join(output.strip().splitlines()[-15:])
        raise ReleaseRefused(f"the parity suite failed (exit status {status}); the end of its output:\n{tail}")


GIT_TIMEOUT = 600.0


def work_tree_of(path: str | os.PathLike[str]) -> Path | None:
    """The work tree of git that a path is in: the nearest folder, the path itself included, that has a ``.git`` (a folder, or the file of a linked worktree);
    None for a path that is in no work tree, which git cannot commit."""
    here = Path(os.path.abspath(path))
    for candidate in (here, *here.parents):
        if os.path.lexists(candidate / ".git"):
            return candidate
    return None


class Git:
    """What the release build asks git about its work tree: the state of the checkout, whether a path is tracked, and whether it is ignored. The build root must
    be a git worktree. (A test passes a stand-in with the same three methods.)"""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        done = self._run("rev-parse", "--is-inside-work-tree")
        if done is None or done.returncode != 0 or done.stdout.strip() != b"true":
            raise ReleaseRefused(
                f"{self.root.name} is not a git worktree (or git does not trust it: see safe.directory): a release is built in a git worktree of its own, at the "
                "commit to release (git worktree add), so that git can say whether the checkout changed while the build ran"
            )

    def _run(self, *args: str) -> subprocess.CompletedProcess[bytes] | None:
        exe = shutil.which("git")
        if exe is None:
            raise ReleaseRefused("git was not found: a release build asks it whether the checkout changed while it ran")
        environment = {name: value for name, value in os.environ.items() if name not in catalog_module._GIT_LOCATION_VARIABLES}
        environment["GIT_OPTIONAL_LOCKS"] = "0"  # (looking at the status must not take the lock of the index from the maintainer's own git)
        try:
            return subprocess.run(
                [exe, "-C", str(self.root), *args], capture_output=True, stdin=subprocess.DEVNULL, env=environment, timeout=GIT_TIMEOUT, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _need(self, *args: str) -> bytes:
        done = self._run(*args)
        if done is None or done.returncode != 0:
            raise ReleaseRefused(f"git could not say `git {' '.join(args)}` for the build root: the state of the checkout cannot be recorded")
        return done.stdout

    def state(self) -> tuple[str, str, str]:
        """``(HEAD, a digest of git status --porcelain=v1 --untracked-files=all, a digest of git diff HEAD --binary)``: a commit, an edit of a tracked file and a new
        file each change it."""
        head = self._need("rev-parse", "HEAD").strip().decode("ascii", "replace")
        status = self._need("status", "--porcelain=v1", "--untracked-files=all")
        diff = self._need("diff", "HEAD", "--binary", "--no-ext-diff", "--no-color")
        return head, hashlib.sha256(status).hexdigest(), hashlib.sha256(diff).hexdigest()

    def tracked(self, path: str | os.PathLike[str]) -> bool:
        """Whether the file is tracked by git. Only git's own answer counts: ``git ls-files --error-unmatch`` ends with status 0 for a file that is tracked and with status 1
        ("did not match any file known to git") for one that is not. Anything else is no answer and raises :class:`ReleaseRefused`: git did not start, did not answer in
        time, stopped with another status (a damaged index, say), or the path is not in the work tree. The answer decides whether the build may delete a file, and a file
        that is tracked by git is not the build's to remove."""
        where = Path(os.path.abspath(path))
        try:
            relative = where.relative_to(os.path.abspath(self.root)).as_posix()
        except ValueError:
            raise ReleaseRefused(f"git could not be asked whether {where.name} is tracked: it is not in the work tree {self.root.name}") from None
        done = self._run("ls-files", "--error-unmatch", "--", relative)
        if done is not None and done.returncode in (0, 1):
            return done.returncode == 0
        how = "git did not run or did not answer in time" if done is None else f"git stopped with status {done.returncode}"
        raise ReleaseRefused(
            f"git could not be asked whether {relative} is tracked ({how}): a file that is tracked by git is not the build's to remove, so the build stops here and does not "
            "guess. Fix the checkout (git status says what is wrong) and run the build again"
        )

    def ignored(self, path: str | os.PathLike[str]) -> bool:
        """Whether git says that it ignores the path itself (as written: ``git check-ignore``); a path in no work tree counts, as git cannot commit it."""
        tree = work_tree_of(path)
        if tree is None:
            return True
        relative = Path(os.path.abspath(path)).relative_to(tree).as_posix()
        return catalog_module._git_ignores(str(tree), [relative])


def check_private_output(path: str | os.PathLike[str], git: Any) -> None:
    """Refuse a place for a private file (the seen flags, the full diff, a trial's files, and the temporary file each is written through) that git could commit.
    :func:`trioforge.data.catalog.check_seen_output` asks about four file names of the catalog; this asks about the path itself: no link or junction on the way
    inside its work tree (a link from ``build/reports`` to the tracked ``reports/`` would carry the file there), and ``git check-ignore`` must say the path is
    ignored (a rule for the names of the catalog alone would leave it out). A path in no work tree passes."""
    written = Path(os.path.abspath(path))
    for place in dict.fromkeys((written, Path(os.path.realpath(written)))):  # (the path as written, and where it really is)
        tree = work_tree_of(place)
        if tree is not None:
            walk = tree
            for part in place.relative_to(tree).parts:
                walk = walk / part
                if os.path.lexists(walk) and assemble._is_link(walk):
                    raise ReleaseRefused(
                        f"{walk.name} is a link or a junction on the way to {place.name}: a private file written through it could land in a folder that "
                        "is tracked by git, so the build will not write there"
                    )
        if not git.ignored(place):
            where = f" (as the path {place.relative_to(tree).as_posix()})" if tree is not None else ""
            raise ReleaseRefused(f"git does not say that {place.name} is ignored{where}: a private file that git does not ignore could be committed")


#: a name that no rule of a ``.gitignore`` is written for: :func:`check_build_folder` asks ``git check-ignore`` about a path of this name in the build folder
BUILD_PROBE = "ignore-probe"


def check_build_folder(folder: str | os.PathLike[str], git: Any) -> None:
    """Refuse, at the start, a build folder that git does not ignore as a whole. The private files are each checked against their own path
    (:func:`check_private_output`), but the rest of what the build writes there (the chunks, the staging folder, the asset) is not, and a folder that the rules of
    ``.gitignore`` cover only in part shows files in the status of the checkout as the hours go by: the check at the end (:func:`check_code_unchanged`) would refuse the
    release after them. So a path inside the folder, which no rule for a part of it covers (:data:`BUILD_PROBE`), must be ignored as well, in the folder as written and where
    it really is. A folder outside every work tree passes, as git cannot commit what is in it."""
    written = Path(os.path.abspath(folder))
    for place in dict.fromkeys((written, Path(os.path.realpath(written)))):  # (the folder as written, and where it really is)
        probe = place / BUILD_PROBE
        if not git.ignored(probe):
            tree = work_tree_of(place)
            where = f", as the path {probe.relative_to(tree).as_posix()}" if tree is not None else ""
            raise ReleaseRefused(
                f"the build folder {place.name} is not ignored by git as a whole (git does not say that {BUILD_PROBE} in it is ignored{where}): the files of the build that no rule "
                "covers would show in the status of the checkout as the hours go by, and the check at the end would refuse the release. Ignore the whole folder (build/ in "
                ".gitignore), or give --build-dir a folder outside the work tree"
            )


@dataclass(frozen=True)
class Start:
    """What was true when the build began and must be true when it ends: the two code hashes, the state of the checkout (:meth:`Git.state`), the rules (as
    ``release.json`` keeps them) and the SHA-256 of the file of the rules and of the public catalog (what the check at the end compares). ``release.json`` is written
    from these values, never from a new reading."""

    chunk_code: str
    writer_code: str
    checkout: tuple[str, str, str]
    rules: Mapping[str, Mapping[str, Any]]
    rules_sha256: str
    catalog_sha256: str


def check_code_unchanged(start: Start, *, git: Any, tables: Path, public: Path) -> None:
    """Refuse the release if the code, the checkout or the inputs are not what they were when the build began. The hashes of the code were taken once, at the
    start, and every worker used them; the state of the checkout (HEAD, status, diff) was recorded then too, and the rules and the catalog were read then. If any of
    them changed since, what was made after the change was made by code or from inputs that the record of the start does not describe, and ``release.json`` would
    describe things that made none of its files. Nothing is packed and no pointer is written; the chunks stay, under the hashes of the start, and the build is run
    again (from a worktree of its own, at the commit to release)."""
    chunk_now, writer_now = _hashes()
    changed = []
    if chunk_now != start.chunk_code:
        changed.append("the code of the chunks: the model, the solver and what they read")
    if writer_now != start.writer_code:
        changed.append("the code that writes the files of a trio")
    if tuple(git.state()) != tuple(start.checkout):
        changed.append("the checkout of the repository: its HEAD, its status or its diff")
    if _sha256(tables / "rules" / "rules.json") != start.rules_sha256 or _sha256(public) != start.catalog_sha256:
        changed.append("the rules or the catalog the release is made from")
    if changed:
        raise ReleaseRefused(
            f"the code changed while the build ran ({' and '.join(changed)}), so what was made since was made by code or from inputs that the record of the start does "
            "not describe. Nothing is packed and no pointer is written; the chunks stay, and the build is to be run again, from a worktree of its own at the commit to release"
        )


def parity_sample(snapshot_id: str, stride: int) -> str:
    """The sample of the parity suite for a release, ``i/n``: the chunks i, i+n, i+2n ... with n = ``stride``, and the offset i drawn from the snapshot id (new for
    each release, and anyone who has the release can see how it was drawn)."""
    digest = hashlib.sha256(f"parity-sample {snapshot_id}".encode("ascii")).digest()
    return f"{int.from_bytes(digest[:8], 'big') % stride}/{stride}"


def parity_stride_ceiling() -> int:
    """The largest stride any release could be held to, known before a single trio is solved: no trio has more chunks than every role, every weapon setup, the three
    tiers of the scope and the four shards give, and the smallest trio has no more than that. A larger stride is refused at the start."""
    return len(data.ROLES) * len(wp.SETUPS) * len(default_tiers(("WAR", "CLR", "PAL"))) * len(shards.SHARD_NAMES)


def parity_stride_limit(facts: Sequence[TrioFacts]) -> int:
    """The largest stride that leaves every trio at least :data:`PARITY_MIN_CHUNKS` chunks in the sample. The chunks of the folder are numbered trio by trio, so a
    trio is a run of consecutive numbers and a stride no longer than the run cannot miss it."""
    return max(1, min((f.chunks for f in facts), default=1) // PARITY_MIN_CHUNKS)


def choose_parity_sample(facts: Sequence[TrioFacts], snapshot_id: str, *, stride: int | None = None) -> str:
    """The sample of the parity suite of this release: the stride asked for (none: the largest that is allowed, which is the lightest sample) and the offset drawn
    from the snapshot id. :class:`ReleaseRefused` for a stride that is not a whole number of at least 1, or that would leave a trio too few chunks in the sample."""
    limit = parity_stride_limit(facts)
    stride = limit if stride is None else stride
    if type(stride) is not int or stride < 1:
        raise ReleaseRefused(f"the parity stride must be a whole number of at least 1, not {stride!r}")
    if stride > limit:
        smallest = min(facts, key=lambda f: f.chunks)
        raise ReleaseRefused(
            f"the parity stride {stride} would leave {smallest.slug}, which has {smallest.chunks} chunks, with fewer than {PARITY_MIN_CHUNKS} of them in the sample: "
            f"the largest stride allowed is {limit}"
        )
    return parity_sample(snapshot_id, stride)


# ---- the stamps of the scheduled checks ---------------------------------------------------------------------------------------------------------------


def scheduled_warnings(
    stamps: str | os.PathLike[str], now: datetime.datetime | None = None, *, names: Sequence[str] = SCHEDULED_CHECKS, days: int = STAMP_DAYS
) -> list[str]:
    """A warning (never a refusal) for each scheduled check of the PC whose last-run stamp, ``<stamps>/<name>.last-run`` (an ISO time), is older than ``days`` days or
    is missing or unreadable."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    found: list[str] = []
    for name in names:
        try:
            first = (Path(stamps) / f"{name}.last-run").read_text(encoding="utf-8").strip().splitlines()[0]
            when = datetime.datetime.fromisoformat(first)
        except (OSError, ValueError, IndexError):
            found.append(f"the scheduled check {name} has no stamp of a run that can be read (it never ran, or its stamp is damaged)")
            continue
        when = when if when.tzinfo is not None else when.replace(tzinfo=datetime.timezone.utc)
        age = now - when
        if age > datetime.timedelta(days=days):
            found.append(f"the scheduled check {name} last ran {age.days} days ago (more than {days} days)")
    return found


# ---- the previous release and the outputs ----------------------------------------------------------------------------------------------------------------


def _tag_order(tag: str) -> tuple[str, int]:
    """The order of release tags: by date, and on one day by the serial number (a tag with none is the first of its day)."""
    rest = tag.removeprefix("data-")
    return rest[:10], int(rest[11:]) if rest[11:] else -1


def resolve_previous(root: str | os.PathLike[str], build_dir: str | os.PathLike[str], tag: str, previous: str) -> tuple[Path | None, str | None]:
    """The release to compare with: ``(path of its asset, note)``. ``previous`` is ``auto`` (the newest release older than ``tag`` that has a pointer in
    ``releases/``; its asset must be in ``<build>/release/`` and be the file its pointer names), ``none``, or the path of an asset or a folder. The note says why
    there is nothing to compare when a release exists whose asset is not at hand: it names the tag and never a place (it is published in the report)."""
    if previous == "none":
        return None, None
    if previous != "auto":
        path = Path(previous)
        if not path.exists():
            raise ReleaseRefused(f"the previous release {previous} is not there")
        return path, None
    older = []
    for path in sorted((Path(root) / "releases").glob("*.json")):
        try:
            assemble.check_tag(path.stem)
        except ReleaseRefused:
            continue
        if _tag_order(path.stem) < _tag_order(tag):
            older.append(path)
    if not older:
        return None, None
    newest = max(older, key=lambda path: _tag_order(path.stem))
    pointer = assemble.read_pointer(newest)
    asset = Path(build_dir) / "release" / f"{newest.stem}.tar.gz"
    if not asset.is_file():
        return None, f"the release {newest.stem} has a pointer in releases/, but its asset is not in the build folder, so this report is compared with nothing"
    if _sha256(asset) != pointer["asset_sha256"]:
        raise ReleaseRefused(f"the asset of {newest.stem} at {asset} differs from the sha256 its pointer names")
    return asset, None


def write_outputs(root: str | os.PathLike[str], texts: Mapping[str, str], *, last: str, replace: Collection[str] = ()) -> None:
    """Write the outputs ``texts`` (``{path: text}``, a path relative to ``root`` or absolute) all or none: none may exist already unless it is in ``replace``,
    the folder of ``last`` is written after the others and ``last`` after the files beside it, and a failure takes away what was written."""
    base = Path(root)
    paths = {name: base / name for name in texts}  # (an absolute name stays what it is)
    for name, path in paths.items():
        if name not in replace and path.exists():
            raise ReleaseRefused(f"{name} already exists: a release is written once")
    folders: dict[Path, dict[str, str]] = defaultdict(dict)
    for name, text in texts.items():
        folders[paths[name].parent][paths[name].name] = text
    last_path = paths[last]
    written: list[Path] = []
    try:
        for folder in sorted(folders, key=lambda folder: folder == last_path.parent):  # the folder of the last file is written last
            commit_files(folder, folders[folder], last=last_path.name if folder == last_path.parent else "")
            written += [folder / leaf for leaf in folders[folder]]
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise


# ---- the keyed privacy scan --------------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScanReport:
    files: int
    findings: list[privacy_scan.Finding]


class PrivacyScanner:
    """The privacy scanner of the repository (:mod:`trioforge.privacy.scan`) set up with a key file and the lists of a ``privacy/`` folder, to scan a release folder.

    It fails closed: a key that is missing, is not 64 hex digits or does not fit the denylist, and a denylist that is missing, damaged or empty, refuse the release (the
    environment is never asked for a key). Files are labelled by their place in the release (``pal-mnk-ber/wiki-own.json``), so that the ``build`` folder the release
    is staged in is no finding of the rule against build paths, and so that a label can be printed: it holds no name. ``phrases_catalog`` is the public catalog whose
    item, zone and NPC names the scan knows, as it does in the repository."""

    def __init__(self, key_file: str | os.PathLike[str], privacy_dir: str | os.PathLike[str], *, phrases_catalog: str | os.PathLike[str] | None = None) -> None:
        folder = Path(privacy_dir)
        try:
            key = privacy_scan._find_key(str(key_file), {}, None)  # (the file given: never the environment, never a default place)
            if key is None:
                raise ReleaseRefused("the privacy key is missing")
            if not (folder / "denylist.hmac").is_file():
                raise ReleaseRefused(f"the denylist {folder.name}/denylist.hmac is missing")
            deny, check = privacy_scan._read_digest_file(str(folder / "denylist.hmac"), "denylist")
            if check is None:
                raise ReleaseRefused(
                    f"the denylist {folder.name}/denylist.hmac has no key-check line, so a key that does not belong to it could not be told from the right one"
                )
            if check != privacy_scan.digest(key, privacy_scan.KEY_CHECK_TEXT)[:16]:
                raise ReleaseRefused("the privacy key does not match the denylist")
            if not deny:
                raise ReleaseRefused(f"the denylist {folder.name}/denylist.hmac has no digests")
            allow = privacy_scan._read_digest_file(str(folder / "allow.hmac"), "allow list")[0] if (folder / "allow.hmac").is_file() else set()
            line_allow = privacy_scan.load_line_allow(str(folder / "allowlist-lines.txt")) if (folder / "allowlist-lines.txt").is_file() else set()
            phrases = privacy_scan.load_catalog_phrases(str(phrases_catalog)) if phrases_catalog is not None and Path(phrases_catalog).is_file() else set()
        except privacy_scan.ScanError as error:
            raise ReleaseRefused(f"the privacy scan cannot be set up: {getattr(error, 'message', str(error))}") from None
        except OSError as error:
            raise ReleaseRefused(f"the privacy scan cannot be set up: {error}") from None
        self._key, self._deny, self._allow, self._line_allow = key, deny, allow, line_allow
        self._masker = privacy_scan.PhraseMasker(phrases) if phrases else None

    def scan(self, folder: str | os.PathLike[str] | None, extra: Mapping[str, bytes] | None = None) -> ScanReport:
        """Scan every file under ``folder`` (None: no folder) and the ``extra`` texts (``{label: bytes}``, the pointer and the report that are about to be written)."""
        base = Path(folder) if folder is not None else Path(".")
        names = assemble._walk(base) if folder is not None else []
        stats: dict[str, int] = {}

        def reader(label: str):
            return open(base / label, "rb")

        try:
            found = privacy_scan.scan_paths(names, self._key, self._deny, self._allow, reader, self._masker, line_allow=self._line_allow, stats=stats)
            for label, content in (extra or {}).items():
                found += privacy_scan.scan_bytes(label, content, self._key, self._deny, self._allow, self._masker, line_allow=self._line_allow)
        except privacy_scan.FileReadError as error:
            raise ReleaseRefused(f"the privacy scan cannot read {error.path}") from None
        except privacy_scan.ScanError as error:
            raise ReleaseRefused(f"the privacy scan could not finish: {getattr(error, 'message', str(error))}") from None
        return ScanReport(stats.get("files", len(names)), sorted(set(found)))


#: a drive letter and a slash, a share (with backslashes, as written or as JSON writes them, or with slashes: no ':' or word character before them, so that a web
#: address passes), a home, system or mount folder of a computer, a file URL (with one slash or more)
_LOCAL_PATH = re.compile(
    rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"
    rb"|\\{2,4}[A-Za-z0-9_.$-]+\\"
    rb"|(?<![A-Za-z0-9_.:/-])/(?:[A-Za-z]/)?(?:Users|home|tmp|var|mnt|private|etc|root|opt|usr|Volumes|srv|media|Library|Applications)/"
    rb"|(?<![:\w])//[A-Za-z0-9_.$-]+/"
    rb"|(?<![A-Za-z0-9])(?i:file):/+"
)


def check_no_local_paths(folder: str | os.PathLike[str] | None, extra: Mapping[str, bytes] | None = None) -> None:
    """Refuse a release if any text that is published holds an absolute path of the computer it was made on, or a drive letter, whatever the build folder is called
    (the keyed scan has a rule against build paths, which sees only the folder named ``build``). It reads every file of ``folder`` and the ``extra`` texts
    (``{label: bytes}``, the pointer and the report). The message names the file and the line of each, and never the path."""
    found: list[str] = []

    def look(label: str, data: bytes) -> None:
        match = _LOCAL_PATH.search(data)
        if match is not None:
            line = data.count(b"\n", 0, match.start()) + 1
            found.append(f"{label}:{line}")

    if folder is not None:
        base = Path(folder)
        for name in assemble._walk(base):
            look(name, (base / name).read_bytes())
    for label, data in (extra or {}).items():
        look(label, data)
    if found:
        raise ReleaseRefused(
            f"{len(found)} published file(s) hold an absolute path of this computer, or a drive letter, and it must not leave it: {_more(found, 5)}"
        )


def privacy_gate(scanner: PrivacyScanner, folder: str | os.PathLike[str] | None, extra: Mapping[str, bytes] | None = None) -> int:
    """Scan a release folder (and the texts to be written beside it): first, with no key, for a path of this computer (:func:`check_no_local_paths`); then with the
    keyed scanner. A finding refuses the release. The message gives the label, the line and column, the rule and the short tag of each finding, never what was
    matched. Returns the number of files scanned."""
    check_no_local_paths(folder, extra)
    report = scanner.scan(folder, extra)
    if report.findings:
        shown = [f"{f.path}:{f.line}:{f.col}: {f.rule} [{f.tag}]" for f in report.findings]
        raise ReleaseRefused(f"the privacy scan found {len(report.findings)} finding(s) in the release ({report.files} files): {_more(shown, 10)}")
    return report.files


# ---- the catalog with the seen flags merged ------------------------------------------------------------------------------------------------------------------


def build_seen_catalog(
    *, wiki: str | os.PathLike[str], client: str | os.PathLike[str], seen: str | os.PathLike[str], out: str | os.PathLike[str], quests: str | os.PathLike[str],
    rules_dir: str | os.PathLike[str], generated: str | None = None, workers: int | None = None,
) -> None:
    """Build the catalog with the maintainer's seen flags merged into ``out`` (``build/catalog-with-seen``) from the fetch ``wiki`` and the client extract
    (:func:`trioforge.data.catalog.build_catalog`, which refuses an output folder that git would commit)."""
    try:
        catalog_module.build_catalog(
            wiki, client, out, seen_path=seen, quests_path=quests, rules_dir=rules_dir, generated=generated, workers=workers
        )
    except (catalog_module.BuildError, OSError, ValueError) as error:
        raise ReleaseRefused(f"the catalog with the seen flags merged cannot be built: {' '.join(str(error).split())}") from None


# ---- the build ---------------------------------------------------------------------------------------------------------------------------------------------


@dataclass
class ReleaseResult:
    """What a build made. ``pointer`` is None for a trial build; ``changes`` and ``solver_diffs`` are those of the report."""

    tag: str
    asset: Path
    asset_sha256: str
    pointer: Path | None
    reports: tuple[Path, Path]
    trios: int
    files: int
    site_files: int
    changes: int
    solver_diffs: int
    previous: str | None
    warnings: list[str]
    trial: bool
    outcomes: list[TrioOutcome]


def _read_strict_once(path: Path) -> tuple[Any, str]:
    """A strict JSON file and the SHA-256 of the very bytes it was parsed from: the file is read once, so the two cannot be of two states of it."""
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise JsonFileError(f"{path.name}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MiB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise JsonFileError(f"{path.name}: not valid UTF-8") from None
    return loads_strict(text, path.name), hashlib.sha256(data).hexdigest()


def _rules_snapshot(tables_root: Path) -> dict[str, dict[str, Any]]:
    """The rules as ``release.json`` keeps them: the value and the levels of each (the status is a note about a rule, and no pick reads it)."""
    document = load_strict(tables_root / "rules" / "rules.json")
    return {rule["id"]: {name: rule[name] for name in ("value", "levels") if name in rule} for rule in document["rules"]}


def snapshot_seen(seen: str | os.PathLike[str], target: str | os.PathLike[str]) -> Path:
    """Copy the seen-flags file to ``target`` (in the build folder, which git ignores and nothing ships) and check the copy. Every worker, check and step of a build
    reads the copy and never the file again, so that flags made again during the hours cannot mix two states of them in one release."""
    try:
        raw = Path(seen).read_bytes()
    except OSError as error:
        raise ReleaseRefused(f"the seen-flags file cannot be read: {error.strerror or type(error).__name__}") from None
    copy = Path(target)
    try:
        catalog_module.check_seen_output(copy.parent)  # (the flags are private: the copy goes where git would never commit it)
    except catalog_module.BuildError as error:
        raise ReleaseRefused(str(error)) from None
    copy.parent.mkdir(parents=True, exist_ok=True)
    temporary = copy.with_name(copy.name + ".tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, copy)
    try:
        catalog_module.load_seen_keys(copy)
    except (catalog_module.BuildError, OSError) as error:
        copy.unlink(missing_ok=True)
        raise ReleaseRefused(f"the seen-flags file cannot be used: {' '.join(str(error).split())}") from None
    return copy


def build_release(
    *, tag: str, root: str | os.PathLike[str], seen: str | os.PathLike[str], privacy_key: str | os.PathLike[str], processes: int = 1,
    trios: Sequence[str] | None = None, trial: bool | None = None, catalog: str | os.PathLike[str] | None = None,
    tables_root: str | os.PathLike[str] | None = None, build_dir: str | os.PathLike[str] | None = None, wiki: str | os.PathLike[str] | None = None,
    client: str | os.PathLike[str] | None = None, previous: str = "auto", parity_stride: int | None = None, say: Callable[[str], None] = print,
    now: datetime.datetime | None = None, seed: int | None = None, make_seen_catalog: Callable[[Path], None] | None = None,
    runner: Callable[[TrioSpec], TrioOutcome] | None = None, bundle_reader: Callable[..., dict[str, int]] | None = None,
    assets: Sequence[str] | None = None, parity_runner: Callable[[Path, str, Sequence[str]], tuple[int, str]] | None = None, robustness: Any = None,
    whole_grid: Sequence[str] | None = None, git: Any = None,
) -> ReleaseResult:
    """Build a release (see the module docstring). ``root`` is the folder with ``derived/``, ``rules/``, ``privacy/``, ``releases/``, ``reports/`` and ``build/``
    (the checkout, in a real run, and it must be a git worktree: ``git`` is the :class:`Git` of it, or a stand-in in a test). ``trios`` is the grid of the release
    (None: all 560); a release is the whole grid, and a build of some trios is a ``trial`` that writes no pointer, nothing in ``releases/`` or ``reports/`` and uses up
    no tag. ``parity_stride`` is the stride of the sample of the parity suite (None: the largest that is allowed). ``whole_grid`` and the keyword arguments from
    ``make_seen_catalog`` on stand in for the grid and for the slow and external steps in the tests. A failure to say something (a closed pipe) is no failure of the
    build. Raises :class:`ReleaseRefused`."""

    def tell(text: str) -> None:
        try:
            say(text)
        except (OSError, ValueError):  # a closed pipe or file: the build goes on, and a failure to say so is no failure of it
            pass

    tag = assemble.check_tag(tag)
    base = Path(root)
    tables = Path(tables_root) if tables_root is not None else base
    public = Path(catalog) if catalog is not None else base / "derived" / "catalog.json"
    build_path = Path(build_dir) if build_dir is not None else base / "build"
    wanted = tuple(dict.fromkeys(trios)) if trios is not None else assemble.grid_trios()
    for slug in wanted:
        if not assemble.is_trio_slug(slug):
            raise ReleaseRefused(f"{slug!r} is not a trio (three class codes in class order, joined by '-', such as pal-mnk-ber)")
    if not wanted:
        raise ReleaseRefused("there is no trio to build")
    is_trial = (trios is not None) if trial is None else trial
    the_grid = tuple(whole_grid) if whole_grid is not None else assemble.grid_trios()
    if not is_trial and set(wanted) != set(the_grid):
        lacking = [slug for slug in the_grid if slug not in wanted]
        raise ReleaseRefused(
            f"a release is the whole grid ({len(the_grid)} trios), and this build has {len(wanted)}" + (f", without {_more(lacking, 3)}" if lacking else "")
            + "; a build of some trios is a trial (--trios), which makes no release"
        )
    if parity_stride is not None:
        if type(parity_stride) is not int or parity_stride < 1:
            raise ReleaseRefused(f"the parity stride must be a whole number of at least 1, not {parity_stride!r}")
        if parity_stride > parity_stride_ceiling():
            raise ReleaseRefused(
                f"the parity stride {parity_stride} is more than any trio has chunks (at most {parity_stride_ceiling()}): the sample could leave a trio out, "
                "and no release could be held to it"
            )
    git = git if git is not None else Git(base)  # (the build root must be a git worktree: it is refused before anything else is done)
    clock = now or datetime.datetime.now(datetime.timezone.utc)
    results, seen_out = build_path / "results", build_path / "catalog-with-seen"
    out_dir = build_path / ("trial" if is_trial else "release")  # (a trial is kept away from the folder of the releases, and from the tracked folders)
    staging, scratch, asset = out_dir / f"{tag}.stage", out_dir / f"{tag}.bundles", out_dir / f"{tag}.tar.gz"
    # the full diff names items, and so tells which the maintainer has seen: it stays in the build folder, and not beside the asset, so that an upload of what is
    # named for the tag (build/release/<tag>.*) cannot publish it
    json_path = out_dir / f"{tag}.results-diff.json" if is_trial else build_path / "reports" / f"results-diff-{tag}.json"
    pointer_name, md_name = f"releases/{tag}.json", f"reports/results-diff-{tag}.md"
    md_path = out_dir / f"{tag}.results-diff.md" if is_trial else base / md_name
    started = time.monotonic()
    warnings: list[str] = []

    def warn(text: str) -> None:
        warnings.append(text)
        tell(f"warning: {text}")

    # the files the build writes that must never be committed: the copy of the seen flags, the full diff, the catalog with the flags merged, and for a trial everything
    # it writes (each through a temporary file of the same folder). Each is checked before it is written, here and again before the outputs of the end.
    def private_outputs() -> list[Path]:
        names = [build_path / SEEN_SNAPSHOT, build_path / f"{SEEN_SNAPSHOT}.tmp", json_path, json_path.with_name(f".{json_path.name}.x.tmp")]
        for name in catalog_module.OUTPUT_FILES:
            names += [seen_out / name, seen_out / f".{name}.x.tmp"]
        if is_trial:  # (everything a trial writes is in the trial folder, and none of it is for git)
            names += [md_path, md_path.with_name(f".{md_path.name}.x.tmp"), asset, asset.with_name(asset.name + ".tmp"), staging, scratch]
        return names

    # 1. what can be found out before any hour is spent
    if not is_trial and (base / pointer_name).exists():  # (a trial writes nowhere a tag is kept, so it uses none up)
        raise ReleaseRefused(f"{pointer_name} already exists: a release tag is used once (use {tag}-2 for another release of the day)")
    gone = clear_unfinished(base, out_dir, tag, git, trial=is_trial)  # (no pointer: what is left of this tag is from a run that did not end)
    if gone:
        tell(f"cleared what an unfinished run of {tag} left behind (no pointer was written for it): {', '.join(gone)}")
    removed = clear_leftovers(out_dir, tag)
    if removed:
        tell(f"cleared what an earlier build of {tag} left in the build folder: {', '.join(removed)}")
    for path in private_outputs():
        check_private_output(path, git)
    check_build_folder(build_path, git)  # (the rest of the folder, which the checks of the private files do not reach: before the first of them is written)
    snapshot = snapshot_seen(seen, build_path / SEEN_SNAPSHOT)
    scanner = PrivacyScanner(privacy_key, base / "privacy", phrases_catalog=public)
    try:
        public_document, catalog_digest = _read_strict_once(public)  # (read once, here: release.json is written from these, and the checks at the end compare the file with them)
    except (OSError, JsonFileError) as error:
        raise ReleaseRefused(f"the public catalog cannot be read: {error}") from None
    community_entries = read_community(base / "rules", public_document)  # (read once, here, with the catalog: release.json records these entries)
    previous_path, note = (None, None) if is_trial and previous == "auto" else resolve_previous(base, build_path, tag, previous)  # (a trial is no release to compare)
    if note:
        warn(note)
    for stale in scheduled_warnings(build_path / "checks", clock):
        warn(stale)
    maker = make_seen_catalog
    if maker is None:
        wiki_dir = Path(wiki) if wiki is not None else base / "sources" / "eqlwiki" / str(public_document.get("version"))
        if not (wiki_dir / "manifest.json").is_file():
            raise ReleaseRefused(f"the wiki fetch of the catalog's snapshot is not at {wiki_dir}: fetch it, or name the folder with --wiki")
        client_dir = Path(client) if client is not None else base / "derived" / "client"
        generated = (public_document.get("provenance") or {}).get("generated")

        def maker(out: Path) -> None:
            build_seen_catalog(
                wiki=wiki_dir, client=client_dir, seen=snapshot, out=out, quests=base / "derived" / "quests.json", rules_dir=base / "rules", generated=generated
            )

    tell(
        f"TRIAL build {tag}: {len(wanted)} trio(s), {processes} process(es); no pointer will be written, and nothing goes to releases/ or reports/"
        if is_trial
        else f"release {tag}: {len(wanted)} trio(s), {processes} process(es)"
    )

    # 2. what the build starts from is recorded once, here, before the pool: the hashes of the code, the state of the checkout, the rules and the catalog. Then the
    # catalog with the flags merged, and 3. the precompute.
    rules_file = tables / "rules" / "rules.json"
    rules_digest = _sha256(rules_file)
    begun = Start(*_hashes(), git.state(), _rules_snapshot(tables), rules_digest, catalog_digest)
    if _sha256(rules_file) != rules_digest:
        raise ReleaseRefused("the rules changed while they were read: run the build again when nothing is writing in the checkout")
    try:
        catalog_module.check_seen_output(seen_out)
        catalog_module.check_seen_output(results)
    except catalog_module.BuildError as error:
        raise ReleaseRefused(str(error)) from None
    maker(seen_out)
    check_seen_catalog(public, seen_out / "catalog.json")
    tell(f"catalog: {len(public_document['items'])} items, snapshot {public_document['version']}, and the same with the private flags merged in build/")
    specs = [
        TrioSpec(slug, str(results), str(public), str(snapshot), str(tables), robustness=robustness, chunk_code=begun.chunk_code, writer_code=begun.writer_code)
        for slug in wanted
    ]
    outcomes = precompute_grid(specs, processes=processes, say=tell, runner=runner)
    failed = [f"{o.slug}: {o.error}" for o in outcomes if o.status == "failed"]
    if failed:
        raise ReleaseRefused(f"{len(failed)} trio(s) failed (the others are kept: run the same command again after the fault is fixed): {_more(failed, 3)}")
    tell(
        f"precompute: {len(outcomes)} trios ({sum(o.status == 'resumed' for o in outcomes)} resumed), {sum(o.chunks for o in outcomes)} chunks "
        f"({sum(o.reused for o in outcomes)} reused, {sum(o.redone for o in outcomes)} redone), {sum(o.scenarios for o in outcomes)} scenarios"
    )
    check_code_unchanged(begun, git=git, tables=tables, public=public)

    # 4. the release folder and its checks
    snapshot_id = assemble.new_snapshot_id()  # (random for each release; the sample of the parity suite is drawn from it)
    stage_report = assemble.stage(results, wanted, staging)
    try:
        tell(f"staged: {stage_report.files} files ({stage_report.linked} linked, {stage_report.copied} copied)")
        facts = check_grid(staging, wanted)
        tell(f"check: {len(facts)} trios present, complete, none partial, each at its scope")
        sample = choose_parity_sample(facts, snapshot_id, stride=parity_stride)
        rows = check_item_rows(staging, wanted)
        tell(f"check: {rows} items, each with the same row in every shard and trio")
        check_invariants(staging, wanted, outcomes)
        tell("check: the invariants of the design hold")
        check_bundles(staging, wanted, seen_catalog=seen_out / "catalog.json", tables_root=tables, scratch=scratch)
        tell(f"check: {len(wanted)} bundles are the ones the exporter writes from the catalog with the flags merged")
        counts = (bundle_reader or check_bundle_reader)(staging, wanted)
        tell(f"check: the browser's reader read {counts['bundles']} bundles ({counts['profiles']} profiles)")
        evidence = assemble.evidence_map(load_strict(staging / assemble.ITEMS_FILE))
        site_files = check_file_count(facts, evidence, assets=assets)
        tell(f"check: {site_files:,} files in the site (limit {build.LIMITS['files']:,})")
        spots = check_pruning(staging, wanted, catalog=public, seen=snapshot, tables_root=tables, seed=seed, processes=processes, chunk_code=begun.chunk_code)
        tell(f"check: {len(spots)} scenarios against the unpruned optimum")
        check_parity(staging, sample=sample, runner=parity_runner)
        tell(f"check: the parity suite passed (sample {sample}, and the defaults of every trio)")

        # 5. release.json, the report, the scan (from the values read at the start)
        spec_one = facts[0]
        document = assemble.release_document(
            tag=tag, catalog_date=public_document["version"], catalog_sha256=begun.catalog_sha256, rules_version=spec_one.rules_version, rules=begun.rules,
            code_hash=assemble.combine_code_hashes(begun.chunk_code, begun.writer_code), solver=grid.solver_info(True), build_options=grid.build_info(),
            level=spec_one.level, game_patch=spec_one.game_patch, trios={f.slug: list(f.tiers) for f in facts}, evidence=evidence, community=community_entries,
            snapshot_id=snapshot_id, trial=is_trial, parity_sample=sample,
        )  # fmt: skip
        assemble.write_release_json(staging, document)
        assemble.check_clean(staging)
        wanted_files = assemble.manifest(staging)
        report = results_diff.diff(previous_path, staging)
        report.note = note
        md_text, json_text = report.markdown(), report.json_text()
        scanned = privacy_gate(scanner, staging, {md_name: md_text.encode("utf-8")})  # (the full diff is not published: it is not scanned)
        tell(f"privacy scan: {scanned} files, 0 findings")

        # 6. the asset and the outputs: from the packing to the pointer one transaction, which leaves no asset behind if it does not end
        check_code_unchanged(begun, git=git, tables=tables, public=public)  # (again, just before it is packed: the checks, the scan and the report took their time too)
        for path in private_outputs():
            check_private_output(path, git)
        try:
            digest = assemble.pack(staging, asset)
            assemble.verify_asset(asset, wanted_files)
            texts = {str(md_path): md_text, str(json_path): json_text}
            replaceable = {str(json_path)} | ({str(md_path)} if is_trial else set())  # (the build folder is for what can be made again)
            last = str(json_path)
            if not is_trial:
                pointer_text = render(assemble.pointer_document(document, digest))
                privacy_gate(scanner, None, {pointer_name: pointer_text.encode("utf-8")})  # (the pointer holds the digest of the asset, known only now)
                texts[str(base / pointer_name)] = pointer_text
                last = str(base / pointer_name)
            write_outputs(base, texts, last=last, replace=replaceable)
        except BaseException:
            asset.unlink(missing_ok=True)
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    tell(f"asset: {asset} ({asset.stat().st_size:,} bytes, sha256 {digest})")
    if is_trial:
        tell("TRIAL build: no pointer written, and nothing in releases/ or reports/; the asset and the reports are in build/trial/")
    tell(f"results diff: {report.summary['changes']} changes ({report.summary['solver_diffs']} solver diffs), {time.monotonic() - started:.0f} s in all")
    return ReleaseResult(
        tag=tag, asset=asset, asset_sha256=digest, pointer=None if is_trial else base / pointer_name, reports=(md_path, json_path), trios=len(wanted),
        files=stage_report.files, site_files=site_files, changes=report.summary["changes"], solver_diffs=report.summary["solver_diffs"],
        previous=report.previous, warnings=warnings, trial=is_trial, outcomes=outcomes,
    )  # fmt: skip
