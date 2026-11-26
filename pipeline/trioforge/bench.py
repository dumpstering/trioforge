"""The Phase 2 benchmark: the presolve gate, the cost of the real formulation and the precompute scope.

``python -m trioforge.bench --sample N --out reports/bench-<date>.json`` runs, on the real catalog and in parallel:

1. **The presolve gate** (:func:`presolve_gate`): ``N`` scenarios drawn uniformly from the whole grid are solved with
   presolve off (the project's setting) and on; an objective that differs by more than 1e-9 relative is a *mismatch*,
   and presolve may be switched on only when there are none. A presolve run that does not end optimal is *guarded*
   (the production rule re-solves it with presolve off). The same runs give the speed-up that presolve would bring.
2. **The benchmark** (:func:`run`): a stratified coverage sample, at least 40 trios of every role-set type with Monk
   trios, trios that mix WIS and INT mana and all-casters, three races, tiers 0, 4 and 10, own buffs and the common
   group buffs, every role and every weapon setup. Each scenario is prepared (profile, pruning, build) and solved twice:
   ``solve`` and ``solve_canonical`` (the first solve and the tie stage). Times, nodes, columns, rows and binaries are
   recorded. A uniform sample of the whole grid (all tiers and races) checks the extrapolation.
3. **The extrapolation** (:func:`extrapolate`): the CPU hours of the whole grid (11 tiers x 2 evidence levels x 2 buff
   sets x every race, trio, role and setup), with and without the canonical stage, with the wiki-first and presolve cuts
   where they apply, and for the scope of tiers 0, 4 and 10 alone. :func:`decide_scope` applies the project's rule: all
   eleven tiers unless the grid needs more than 300 CPU hours after the cuts.
4. **The browser proxy**: twenty models, at evenly spaced quantiles of the solve time, are written as MPS files and
   timed with the pinned highs-js by ``scripts/bench-highs.mjs`` (a desktop number; a mid-range phone is about 4x slower).

The evidence levels. The public catalog has no *strict* items (they come from private seen flags that are merged at build
time), so the wiki level is what is measured. A strict solve is stood in for by a **proxy**: a fixed 44 percent of the
wiki items (:func:`strict_proxy`), which is a subset of the wiki level like the real strict level. Its cost ratio to the
wiki level scales the strict share of the grid. The *wiki-first* cut (a strict solve is skipped when the wiki kit already
uses only strict items) cannot be measured without strict items; its share, 74 percent, was measured on the previous
model and is a parameter of the extrapolation.

Nothing private is read or written: the catalog is the public wiki catalog and the reports carry timings and counts only
(:func:`assert_public` refuses a path into a user profile anywhere in the data).
"""

from __future__ import annotations

import argparse
import bisect
import dataclasses
import datetime
import gzip
import hashlib
import importlib.metadata
import itertools
import json
import math
import multiprocessing
import os
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import highspy

from trioforge.classes import CLASS_CODES
from trioforge.model import formulas as fm
from trioforge.model import weapons as wp
from trioforge.model.buffs import BuffSet, buffsets
from trioforge.model.items import ItemVec, at_tier
from trioforge.model.profile import Profile, make_profile
from trioforge.model.roles import CASTER_CLASSES, TANK_CLASSES, roles_for
from trioforge.model.tables import REPO, Tables, load
from trioforge.solver import _highs
from trioforge.solver.model import BINARY_KINDS, Milp, build_milp
from trioforge.solver.prune import prune
from trioforge.solver.solve import solve, solve_canonical

__all__ = [
    "BENCH_RACES",
    "BENCH_TIERS",
    "BUFF_SETS",
    "CPU_BUDGET_HOURS",
    "EVIDENCE_LEVELS",
    "GRID_CELLS",
    "LEVEL",
    "SPEC_SCENARIOS",
    "Context",
    "Inputs",
    "Scenario",
    "aggregate",
    "assert_public",
    "bench_summary",
    "calibration",
    "canonical_interval",
    "compare_solutions",
    "coverage_sample",
    "decide_scope",
    "export_models",
    "extrapolate",
    "find_catalog",
    "grid_shapes",
    "interpolate_tiers",
    "main",
    "notes_for",
    "paired_ratio",
    "percentile",
    "pick_trios",
    "presolve_gate",
    "quantile_picks",
    "random_sample",
    "render_markdown",
    "role_set_type",
    "run",
    "run_highs_js",
    "seconds_of",
    "strict_proxy",
    "stratum_of",
    "summarize",
    "tier_seconds",
    "uniform_hours",
    "wiki_costs",
    "write_reports",
]

LEVEL = 50
TIERS = tuple(range(11))
BENCH_RACES = ("ERU", "HUM", "OGR")  # low, middle and high physical stats
BENCH_TIERS = (0, 4, 10)
BUFF_SETS = ("own", "group")  # the trio's own long buffs; those plus the 13 common group buffs
EVIDENCE_LEVELS = ("wiki", "strict-proxy")
GRID_CELLS = len(TIERS) * len(EVIDENCE_LEVELS) * len(BUFF_SETS)  # 44 cells of tier, evidence level and buff set
SPEC_SCENARIOS = 2_825_460  # the specification's own sizing of the run (15 races x 4,281 role-setups x 44), kept as the scale the hours are compared to the spec at: it is the document's figure, not a count of
# this grid (which is counted from the catalog on every run and reported as ``scenarios``: now 16 races and the builds' setups), so a sixteenth race does not change it
CPU_BUDGET_HOURS = 300.0  # above this after the cuts, only tiers 0, 4 and 10 are precomputed (the project's rule)
STRICT_SHARE = 0.44  # the strict proxy keeps this share of the wiki items
WIKI_FIRST_SKIP = 0.74  # share of strict solves that the wiki-first cut skips (measured on the previous model)
GATE_TOLERANCE = 1e-9  # two objectives agree when they differ by no more than this, relative
FIELDS = ("prep", "solve", "canon")  # the seconds of a scenario: build the model, solve, solve + tie stage


# ---- statistics ----------------------------------------------------------------------------------------------------


def percentile(values: Sequence[float], q: float) -> float:
    """The ``q``-th percentile (0 to 100) of ``values`` by linear interpolation between the two nearest ranks."""
    if not values:
        raise ValueError("a percentile needs at least one value")
    if not 0 <= q <= 100:
        raise ValueError(f"q is a percentage from 0 to 100, not {q!r}")
    xs = sorted(values)
    position = (len(xs) - 1) * q / 100
    low, high = math.floor(position), math.ceil(position)
    return float(xs[low] + (xs[high] - xs[low]) * (position - low))


def summarize(values: Sequence[float]) -> dict[str, float]:
    """Count, mean, median, 95th percentile, maximum and sum of ``values`` (just ``{"n": 0}`` for none)."""
    if not values:
        return {"n": 0}
    return {
        "n": len(values), "mean": float(sum(values) / len(values)), "p50": percentile(values, 50),
        "p95": percentile(values, 95), "max": float(max(values)), "sum": float(sum(values)),
    }  # fmt: skip


def quantile_picks(values: Sequence[float], k: int) -> list[int]:
    """Indices into ``values`` of ``k`` entries at evenly spaced quantile midpoints ((i + 0.5)/k) of the sorted values.

    With fewer than ``k`` values every index is returned. The picks are what the browser proxy times: they span the
    distribution, so their median and tail say something about the whole.
    """
    n = len(values)
    if n == 0 or k <= 0:
        return []
    order = sorted(range(n), key=lambda i: (values[i], i))
    if n <= k:
        return sorted(order)
    return [order[min(n - 1, int((i + 0.5) * n / k))] for i in range(k)]


# ---- scenarios, strata and the grid --------------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Scenario:
    """One cell of the grid: a race, a trio, a role with one of its weapon setups, a tier, an evidence level
    (``wiki`` or ``strict-proxy``) and a buff set (``own`` or ``group``), at level 50."""

    race: str
    trio: tuple[str, str, str]
    role: str
    setup: str
    tier: int
    evidence: str
    buffs: str

    @property
    def key(self) -> str:
        return f"{self.race} {'/'.join(self.trio)} {self.role} {self.setup} +{self.tier} {self.evidence} {self.buffs}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "trio": list(self.trio)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Scenario:
        """A scenario from a dict that has its fields (a measured record has more, which are ignored)."""
        names = ("race", "trio", "role", "setup", "tier", "evidence", "buffs")
        return cls(**{**{name: data[name] for name in names}, "trio": tuple(data["trio"])})


def role_set_type(trio: Sequence[str]) -> str:
    """The templates a trio can play, joined by ``+``: ``caster``, ``melee``, ``tank+melee``, ``melee+caster`` or
    ``tank+melee+caster`` (a tank class is always a melee class too, so ``tank`` is never alone)."""
    members = set(trio)
    names = []
    if members & TANK_CLASSES:
        names.append("tank")
    if members - CASTER_CLASSES:  # every class that does not cast has the Offensive stance
        names.append("melee")
    if members & CASTER_CLASSES:
        names.append("caster")
    return "+".join(names)


def stratum_of(trio: Sequence[str], tables: Tables) -> str:
    """``<role-set type>|monk or plain|sel or std``: ``sel`` for the 180 trios with three mana pools that mix WIS and INT,
    where which two pools count depends on the gear (selection binaries); ``std`` for the rest."""
    pools = fm.pools_for(trio, LEVEL, tables)["MANA"]
    selects = len(pools) == 3 and len({pool.stat for pool in pools}) > 1
    return f"{role_set_type(trio)}|{'monk' if 'MNK' in trio else 'plain'}|{'sel' if selects else 'std'}"


def all_trios() -> list[tuple[str, str, str]]:
    return list(itertools.combinations(CLASS_CODES, 3))  # type: ignore[arg-type]


def shape_list(tables: Tables) -> list[tuple[tuple[str, str, str], str, str]]:
    """Every ``(trio, role, setup)`` of the grid, in a fixed order."""
    return [
        (trio, role, setup)
        for trio in all_trios()
        for role in roles_for(trio)
        for setup in wp.setups_for(trio, role, tables, level=LEVEL)
    ]


def race_codes(tables: Tables) -> list[str]:
    return [entry["code"] for entry in tables.races["races"]]


def grid_shapes(tables: Tables, races: int | None = None) -> dict[str, int]:
    """``{stratum: number of (race, trio, role, setup) combinations}``; one cell of tier, evidence and buff set each.

    ``races`` is the number of races (all of them when None); the full grid has these combinations in each of the
    :data:`GRID_CELLS` cells."""
    count = len(tables.races["races"]) if races is None else races
    shapes: dict[str, int] = defaultdict(int)
    for trio, _, _ in shape_list(tables):
        shapes[stratum_of(trio, tables)] += count
    return dict(sorted(shapes.items()))


# ---- the samples ---------------------------------------------------------------------------------------------------


def pick_trios(
    tables: Tables, n: int = 60, seed: int = 1, *, min_monk: int = 10, min_mixed: int = 10, min_caster: int = 5
) -> list[tuple[str, str, str]]:
    """About ``n`` trios, sorted: one of every stratum first (when ``n`` allows), then random ones of the rest, then
    enough Monk trios (``min_monk``), trios with the mixed WIS/INT pools (``min_mixed``) and all-casters
    (``min_caster``) to meet those minimums. Deterministic for a seed; may return more than ``n`` to meet a minimum."""
    rng = random.Random(seed)
    trios = all_trios()
    strata = {trio: stratum_of(trio, tables) for trio in trios}
    cells = sorted(set(strata.values()))
    if n < len(cells):
        chosen = rng.sample(trios, n)
    else:
        chosen = [rng.choice([t for t in trios if strata[t] == cell]) for cell in cells]
        rest = [t for t in trios if t not in chosen]
        rng.shuffle(rest)
        chosen += rest[: max(0, n - len(chosen))]
    for wanted, need in (
        (lambda t: "MNK" in t, min_monk),
        (lambda t: strata[t].endswith("|sel"), min_mixed),
        (lambda t: role_set_type(t) == "caster", min_caster),
    ):
        spare = [t for t in trios if t not in chosen and wanted(t)]
        rng.shuffle(spare)
        while sum(wanted(t) for t in chosen) < need and spare:
            chosen.append(spare.pop())
    return sorted(chosen)


def coverage_sample(
    tables: Tables, trios: Iterable[tuple[str, str, str]], *, races: Sequence[str] = BENCH_RACES,
    tiers: Sequence[int] = BENCH_TIERS, buffs: Sequence[str] = BUFF_SETS, evidence: str = "wiki",
) -> list[Scenario]:
    """Every role and weapon setup of every trio, in each race, tier and buff set given."""
    sample = []
    for trio in trios:
        for race in races:
            for tier in tiers:
                for buff in buffs:
                    for role in roles_for(trio):
                        for setup in wp.setups_for(trio, role, tables, level=LEVEL):
                            sample.append(Scenario(race, tuple(trio), role, setup, tier, evidence, buff))  # type: ignore[arg-type]
    return sample


def random_sample(
    tables: Tables, n: int, seed: int, evidences: Sequence[str] = EVIDENCE_LEVELS, tiers: Sequence[int] = TIERS
) -> list[Scenario]:
    """``n`` scenarios drawn uniformly from the whole grid: a (trio, role, setup) of the grid, then a race, a tier, an
    evidence level and a buff set, each uniformly."""
    rng = random.Random(seed)
    shapes, races = shape_list(tables), race_codes(tables)
    sample = []
    for _ in range(n):
        trio, role, setup = shapes[rng.randrange(len(shapes))]
        sample.append(
            Scenario(rng.choice(races), trio, role, setup, rng.choice(tiers), rng.choice(evidences), rng.choice(BUFF_SETS))
        )
    return sample


# ---- the inputs ----------------------------------------------------------------------------------------------------


def wiki_wearables(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The wiki level of the catalog that can be worn: strict items are wiki items by definition; temporary items and
    hand-in items (reason ``not-for-bis``) are not candidates."""
    return [
        item
        for item in items
        if item["evidence"]["level"] in ("strict", "wiki")
        and item["slots"]
        and not any(reason["code"] == "not-for-bis" for reason in item["evidence"]["reasons"])
    ]


def strict_proxy(items: Sequence[dict[str, Any]], share: float = STRICT_SHARE) -> list[dict[str, Any]]:
    """A stand-in for the strict level: a fixed ``share`` of the items, picked by a hash of the item key (so the same
    items in every process and every run), and a subset of ``items`` as the strict level is of the wiki level."""
    cut = int(share * 256)
    return [item for item in items if hashlib.sha1(item["key"].encode("utf-8"), usedforsecurity=False).digest()[0] < cut]


def find_catalog() -> Path | None:
    """The catalog file: ``$TRIOFORGE_CATALOG``, ``derived/catalog.json`` of this checkout, or of the main checkout when
    this is a worktree (the built data stays in the main one)."""
    candidates = []
    if os.environ.get("TRIOFORGE_CATALOG"):
        candidates.append(Path(os.environ["TRIOFORGE_CATALOG"]))
    candidates.append(REPO / "derived" / "catalog.json")
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=REPO, capture_output=True, text=True,
            timeout=30, check=True,
        ).stdout.strip()
        candidates.append(Path(common).parent / "derived" / "catalog.json")
    except (OSError, subprocess.SubprocessError):
        pass
    return next((path for path in candidates if path.is_file()), None)


@dataclass(frozen=True)
class Inputs:
    """What a benchmark needs: the model tables (with the rules), the level-50 spell file and the raw catalog items of the
    wiki level. ``version`` and ``counts`` describe the catalog for the report."""

    tables: Tables
    spells: Mapping[str, Any]
    items: tuple[dict[str, Any], ...]
    version: str | None = None
    counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def rules(self) -> Any:
        return self.tables.rules

    @classmethod
    def from_items(
        cls, items: Sequence[dict[str, Any]], tables: Tables | None = None, version: str | None = None,
        counts: Mapping[str, int] | None = None,
    ) -> Inputs:
        tables = tables or load()
        spells = json.loads((REPO / "derived" / "client" / f"spells-l{LEVEL}.json").read_text(encoding="utf-8"))
        return cls(tables, spells, tuple(items), version, dict(counts or {"wiki_wearables": len(items)}))

    @classmethod
    def load(cls, catalog_path: str | os.PathLike[str]) -> Inputs:
        document = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        wanted = wiki_wearables(document["items"])
        counts = {"catalog_items": len(document["items"]), "wiki_wearables": len(wanted)}
        return cls.from_items(wanted, version=document.get("version"), counts=counts)


# ---- one scenario --------------------------------------------------------------------------------------------------


@dataclass
class Prepared:
    scenario: Scenario
    profile: Profile
    buffset: BuffSet
    pool_size: int
    kept: list[ItemVec]
    milp: Milp
    seconds: dict[str, float]


def _step(seconds: dict[str, float], name: str, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call ``function`` and record two clocks in ``seconds``: ``t_<name>``, the wall time, and ``c_<name>``, the CPU time
    of this process (user and system; one tick of the clock is 1/64 s on Windows). On a machine that other work shares,
    the wall time includes the waits for a core; the CPU time does not, and it is what a CPU-hour is made of."""
    wall, cpu = time.perf_counter(), time.process_time()
    result = function(*args, **kwargs)
    seconds[f"t_{name}"] = time.perf_counter() - wall
    seconds[f"c_{name}"] = time.process_time() - cpu
    return result


def seconds_of(record: Mapping[str, Any], stage: str, clock: str = "c") -> float:
    """The seconds a measured record took for ``prep`` (profile, prune and build), ``solve`` or ``canon`` on a clock:
    ``c`` for the CPU time (the default, what a CPU hour is made of) or ``t`` for the wall time."""
    if stage == "prep":
        return record[f"{clock}_profile"] + record[f"{clock}_prune"] + record[f"{clock}_build"]
    return record[f"{clock}_{stage}"]


class Context:
    """The state one process keeps while it works through scenarios: the item views by evidence level and tier, and the
    resolved buff sets by trio and kind. Both are built on first use and kept."""

    def __init__(self, inputs: Inputs):
        self.inputs = inputs
        self.tables = inputs.tables
        self.rules = inputs.rules
        self.raw = {"wiki": list(inputs.items), "strict-proxy": strict_proxy(inputs.items)}
        self._views: dict[tuple[str, int], list[ItemVec]] = {}
        self._buffsets: dict[tuple[tuple[str, ...], str], BuffSet] = {}
        self.buff_seconds: dict[tuple[tuple[str, ...], str], dict[str, float]] = {}

    def view(self, evidence: str, tier: int) -> list[ItemVec]:
        key = (evidence, tier)
        if key not in self._views:
            self._views[key] = [at_tier(item, tier, self.rules) for item in self.raw[evidence]]
        return self._views[key]

    def buffset(self, trio: tuple[str, ...], kind: str) -> BuffSet:
        key = (tuple(trio), kind)
        if key not in self._buffsets:
            if kind not in BUFF_SETS:
                raise ValueError(f"unknown buff set {kind!r}")
            seconds: dict[str, float] = {}

            def build() -> BuffSet:
                return buffsets(trio, LEVEL, self.inputs.spells, self.rules, (kind,))[kind]

            self._buffsets[key] = _step(seconds, "buffs", build)
            self.buff_seconds[key] = seconds
        return self._buffsets[key]

    def prepare(self, scenario: Scenario) -> Prepared:
        """Profile, pruned pool and built model of a scenario, with the seconds each step took."""
        if scenario.evidence not in self.raw:
            raise ValueError(f"unknown evidence level {scenario.evidence!r}")
        fresh = (tuple(scenario.trio), scenario.buffs) not in self._buffsets
        buffset = self.buffset(scenario.trio, scenario.buffs)
        pool = self.view(scenario.evidence, scenario.tier)
        seconds: dict[str, float] = {}
        profile = _step(
            seconds, "profile", make_profile, scenario.race, scenario.trio, LEVEL, scenario.role, buffset, None,
            self.tables, self.rules, evidence="strict" if scenario.evidence == "strict-proxy" else "wiki",
        )
        if scenario.setup not in profile.setups:
            raise ValueError(f"setup {scenario.setup!r} is not one of the setups of {profile!r}: {profile.setups}")
        kept = _step(seconds, "prune", prune, pool, profile, scenario.tier, scenario.setup, buffset)
        milp = _step(seconds, "build", build_milp, profile, kept, scenario.setup, buffset)
        if fresh:  # the buff set was resolved for this scenario: a one-time cost of the (trio, buff set), kept apart
            seconds.update(self.buff_seconds[(tuple(scenario.trio), scenario.buffs)])
        return Prepared(scenario, profile, buffset, len(pool), kept, milp, seconds)

    def measure(self, scenario: Scenario, *, time_limit: float | None = 300.0, canonical: bool = True) -> dict[str, Any]:
        """Prepare and solve one scenario; every measurement goes into the returned record. A scenario that raises is
        recorded with its ``error`` and without measurements, so one failure does not stop a run."""
        record: dict[str, Any] = {
            "key": scenario.key, **scenario.to_dict(), "stratum": stratum_of(scenario.trio, self.tables), "error": None,
        }
        try:
            prepared = self.prepare(scenario)
            milp = prepared.milp
            solution = _step(record, "solve", solve, milp, time_limit=time_limit)
            record.update(
                prepared.seconds, status_solve=solution.status, nodes_solve=solution.nodes,
                F_solve=solution.F, model_F=solution.model_F, gap=solution.gap, n_pool=prepared.pool_size,
                n_kept=len(prepared.kept), cols=milp.num_cols, rows=milp.num_rows, item_cols=milp.info["items"],
                binaries=dict(milp.info["binaries"]), pools=dict(milp.info["pools"]),
                buffs_optional=len(prepared.buffset.optional),
            )
            if canonical:
                second = _step(record, "canon", solve_canonical, milp, time_limit=time_limit)
                record.update(
                    status_canon=second.status, nodes_canon=second.nodes, F_canon=second.F, canonical=second.canonical
                )
        except Exception as exc:  # noqa: BLE001 - a benchmark records a failing scenario and goes on
            record["error"] = _error_text(exc)
        return record

    def gate_one(self, scenario: Scenario, *, canonical: bool, time_limit: float | None) -> dict[str, Any]:
        """One scenario of the presolve gate: the same model solved with presolve off and on (and, if asked, the
        canonical solve with each)."""
        record: dict[str, Any] = {
            "key": scenario.key, **scenario.to_dict(), "stratum": stratum_of(scenario.trio, self.tables), "error": None,
        }
        try:
            milp = self.prepare(scenario).milp
            off = _step(record, "off", solve, milp, time_limit=time_limit)
            on = _step(record, "on", solve, milp, time_limit=time_limit, highs_options={"presolve": "on"})
            record.update(
                status_off=off.status, status_on=on.status, F_off=off.F, F_on=on.F, nodes_off=off.nodes,
                nodes_on=on.nodes, verdict=compare_solutions(off.status, off.F, on.status, on.F),
                rel_diff=_rel_diff(off.F, on.F), same_items=_same(_items(off), _items(on)), same_kit=_same(_keys(off), _keys(on)),
                cols=milp.num_cols,
            )
            if canonical:
                off_c = _step(record, "canon_off", solve_canonical, milp, time_limit=time_limit)
                on_c = _step(
                    record, "canon_on", solve_canonical, milp, time_limit=time_limit, highs_options={"presolve": "on"}
                )
                record.update(
                    status_canon_off=off_c.status, status_canon_on=on_c.status, F_canon_off=off_c.F, F_canon_on=on_c.F,
                    verdict_canon=compare_solutions(off_c.status, off_c.F, on_c.status, on_c.F),
                    same_items_canon=_same(_items(off_c), _items(on_c)), same_kit_canon=_same(_keys(off_c), _keys(on_c)),
                )
        except Exception as exc:  # noqa: BLE001
            record["error"] = _error_text(exc)
        return record


def _error_text(exc: BaseException) -> str:
    """``Type: message`` of an exception, cut to 200 characters, with any local path in the message hidden."""
    text = f"{type(exc).__name__}: {exc}"
    return _PATH_TEXT.sub("<path>", text)[:200]


def _keys(solution: Any) -> tuple[str | None, ...] | None:
    return None if solution.kit is None else tuple(item.key if item else None for item in solution.kit)


def _items(solution: Any) -> tuple[str, ...] | None:
    keys = _keys(solution)
    return None if keys is None else tuple(sorted(key for key in keys if key))


def _same(a: Any, b: Any) -> bool:
    """Whether two kits (or their item lists) agree: two kits that are both missing (a solve that found none) do not."""
    return a is not None and a == b


def _rel_diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else abs(a - b) / max(1.0, abs(a), abs(b))


def compare_solutions(
    off_status: str, off_value: float | None, on_status: str, on_value: float | None, rel: float = GATE_TOLERANCE
) -> str:
    """How a presolve-on solve relates to the presolve-off solve of the same model:

    * ``ok``: both optimal, objectives within ``rel`` (relative to the larger of 1 and the values);
    * ``mismatch``: both optimal, objectives further apart. This is what blocks presolve;
    * ``guarded``: presolve off is optimal and presolve on is not (a time limit, an infeasible answer): the production
      rule re-solves with presolve off, so the answer is right, but the run was wasted;
    * ``unverified``: presolve off was not optimal, so there is nothing to compare with.
    """
    if off_status != "optimal":
        return "unverified"
    if on_status != "optimal" or on_value is None or off_value is None:
        return "guarded"
    return "ok" if abs(off_value - on_value) <= rel * max(1.0, abs(off_value), abs(on_value)) else "mismatch"


def gate_passed(gate: Mapping[str, Any] | None) -> bool:
    """The one test of the presolve gate, used by the exit code, the Result bullet and the decision. It passes when no scenario mismatched in either stage (the plain solve
    and the canonical tie stage), none raised an error, and at least one was compared (a run in which every presolve-off solve timed out, or with no scenario, has verified nothing).
    Guarded runs (presolve on did not end optimal) do not fail it: the production rule re-solves them with presolve off."""
    if not gate:
        return False
    canonical = gate.get("canonical") or {}
    return gate.get("n_mismatch") == 0 and gate.get("errors") == 0 and canonical.get("mismatches", 0) == 0 and (gate.get("compared") or 0) > 0


# ---- running many scenarios ----------------------------------------------------------------------------------------

_CONTEXT: Context | None = None


def _init_worker(catalog: str) -> None:
    global _CONTEXT
    _CONTEXT = Context(Inputs.load(catalog))


def _work(job: tuple[str, list[tuple[int, dict[str, Any]]], dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    kind, indexed, options = job
    assert _CONTEXT is not None
    out = []
    for index, data in indexed:
        scenario = Scenario.from_dict(data)
        if kind == "measure":
            out.append((index, _CONTEXT.measure(scenario, **options)))
        else:
            out.append((index, _CONTEXT.gate_one(scenario, **options)))
    return out


def _jobs(sample: Sequence[Scenario], kind: str, options: dict[str, Any], chunk: int | None) -> list[Any]:
    """Jobs for the workers: scenarios of one (trio, tier, buff set, evidence) together when ``chunk`` is None (they share
    their buff sets and item views), else in runs of ``chunk``."""
    indexed = [(i, s.to_dict()) for i, s in enumerate(sample)]
    if chunk is None:
        groups: dict[Any, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        for (i, data), s in zip(indexed, sample):
            groups[(s.trio, s.tier, s.buffs, s.evidence)].append((i, data))
        return [(kind, group, options) for group in groups.values()]
    return [(kind, indexed[i : i + chunk], options) for i in range(0, len(indexed), chunk)]


def _map(
    sample: Sequence[Scenario], kind: str, options: dict[str, Any], *, inputs: Inputs | None, catalog: str | None,
    workers: int, chunk: int | None, progress: Callable[[int, int, float], None] | None,
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    results: list[dict[str, Any] | None] = [None] * len(sample)
    if workers <= 1 or len(sample) <= 1:
        ctx = Context(inputs if inputs is not None else Inputs.load(catalog))  # type: ignore[arg-type]
        for i, scenario in enumerate(sample):
            work = ctx.measure if kind == "measure" else ctx.gate_one
            results[i] = work(scenario, **options)
            if progress:
                progress(i + 1, len(sample), time.perf_counter() - started)
        return results  # type: ignore[return-value]
    if catalog is None:
        raise ValueError("a run with several workers needs the path of a catalog file (the workers load it themselves)")
    done = 0
    context = multiprocessing.get_context("spawn")
    with context.Pool(workers, initializer=_init_worker, initargs=(catalog,)) as pool:
        for part in pool.imap_unordered(_work, _jobs(sample, kind, options, chunk)):
            for index, record in part:
                results[index] = record
            done += len(part)
            if progress:
                progress(done, len(sample), time.perf_counter() - started)
    return results  # type: ignore[return-value]


def run(
    sample: Sequence[Scenario], *, inputs: Inputs | None = None, catalog: str | None = None, workers: int = 1,
    time_limit: float | None = 300.0, canonical: bool = True, progress: Callable[[int, int, float], None] | None = None,
    chunk: int | None = None,
) -> list[dict[str, Any]]:
    """Measure every scenario of ``sample`` (see :meth:`Context.measure`); the records come back in the order of the
    sample. With one worker the run is in this process on ``inputs``; with more, ``catalog`` is the path of the catalog
    file that each worker process loads."""
    options = {"time_limit": time_limit, "canonical": canonical}
    return _map(sample, "measure", options, inputs=inputs, catalog=catalog, workers=workers, chunk=chunk, progress=progress)


def presolve_gate(
    n: int = 5000, seed: int = 0, *, inputs: Inputs | None = None, catalog: str | None = None, workers: int = 1,
    canonical_every: int = 0, time_limit: float | None = 300.0, progress: Callable[[int, int, float], None] | None = None,
) -> dict[str, Any]:
    """Solve ``n`` scenarios drawn uniformly from the grid with presolve off and on and compare the objectives.

    Every ``canonical_every``-th scenario (0 for none) also runs the canonical solve with each setting. Returns the
    verdict counts, the mismatches in full, the speed-up of presolve (total off time over total on time) and the
    agreement of the kits. Presolve may be enabled only if ``n_mismatch`` is 0 on the full 5,000.
    """
    tables = inputs.tables if inputs is not None else load()
    sample = random_sample(tables, n, seed)
    records_in = _map(
        sample, "gate", {"canonical": False, "time_limit": time_limit}, inputs=inputs, catalog=catalog,
        workers=workers, chunk=4, progress=progress,
    ) if not canonical_every else _gate_with_canonical(
        sample, canonical_every, time_limit, inputs, catalog, workers, progress
    )
    records = [r for r in records_in if r is not None]
    ok = [r for r in records if r["error"] is None]
    verdicts = defaultdict(int)
    for record in ok:
        verdicts[record["verdict"]] += 1
    diffs = [r["rel_diff"] for r in ok if r.get("rel_diff") is not None]
    solver = highspy.Highs()
    both = [r for r in ok if r["verdict"] in ("ok", "mismatch")]
    ran_canon = [r for r in ok if "c_canon_off" in r]
    canon = [r for r in ran_canon if r["verdict_canon"] in ("ok", "mismatch")]  # (a guarded or unverified run has no second answer to compare with: it counts nowhere)

    def speedup(rows: Sequence[Mapping[str, Any]], off: str, on: str, clock: str) -> float | None:
        return _ratio(sum(r[f"{clock}_{off}"] for r in rows), sum(r[f"{clock}_{on}"] for r in rows))

    gate: dict[str, Any] = {
        "n": len(records), "seed": seed, "n_ok": verdicts["ok"], "n_mismatch": verdicts["mismatch"],
        "guarded": verdicts["guarded"], "unverified": verdicts["unverified"], "errors": len(records) - len(ok),
        "error_messages": sorted({r["error"] for r in records if r["error"]})[:5],
        "mismatches": [_gate_row(r) for r in ok if r["verdict"] == "mismatch"],
        "max_rel_diff": max(diffs, default=0.0), "tolerance": GATE_TOLERANCE,
        "same_items": sum(r["same_items"] for r in both), "same_kit": sum(r["same_kit"] for r in both),
        "compared": len(both),
        "time_off": summarize([r["c_off"] for r in both]), "time_on": summarize([r["c_on"] for r in both]),
        "speedup": {"solve": speedup(both, "off", "on", "c"), "canon": speedup(canon, "canon_off", "canon_on", "c")},
        "wall_speedup": {"solve": speedup(both, "off", "on", "t"), "canon": speedup(canon, "canon_off", "canon_on", "t")},
        "canonical": {
            "n": len(canon), "left_out": len(ran_canon) - len(canon), "mismatches": sum(r["verdict_canon"] == "mismatch" for r in canon),
            "same_items": sum(r["same_items_canon"] for r in canon), "same_kit": sum(r["same_kit_canon"] for r in canon),
            "time_off": summarize([r["c_canon_off"] for r in canon]),
            "time_on": summarize([r["c_canon_on"] for r in canon]),
        },
        "highs": {"version": ".".join(map(str, (solver.versionMajor(), solver.versionMinor(), solver.versionPatch()))),
                  "githash": solver.githash()},
        "options": dict(_highs.OPTIONS), "tested": {"presolve": "on"},
    }  # fmt: skip
    return gate


def _gate_with_canonical(
    sample: Sequence[Scenario], every: int, time_limit: float | None, inputs: Inputs | None, catalog: str | None,
    workers: int, progress: Callable[[int, int, float], None] | None,
) -> list[dict[str, Any]]:
    """The gate with the canonical comparison on every ``every``-th scenario: two runs merged in the order of the sample."""
    marked = [s for i, s in enumerate(sample) if i % every == 0]
    plain = [s for i, s in enumerate(sample) if i % every != 0]
    first = _map(marked, "gate", {"canonical": True, "time_limit": time_limit}, inputs=inputs, catalog=catalog,
                 workers=workers, chunk=2, progress=progress)  # fmt: skip
    second = _map(plain, "gate", {"canonical": False, "time_limit": time_limit}, inputs=inputs, catalog=catalog,
                  workers=workers, chunk=4, progress=progress)  # fmt: skip
    a, b = iter(first), iter(second)
    return [next(a) if i % every == 0 else next(b) for i in range(len(sample))]


def _gate_row(record: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("key", "status_off", "status_on", "F_off", "F_on", "rel_diff", "same_items", "same_kit")
    return {k: record[k] for k in keys}


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0 else None


# ---- the extrapolation ---------------------------------------------------------------------------------------------


def interpolate_tiers(costs: Mapping[int, float], tiers: Iterable[int] = TIERS) -> dict[int, float]:
    """A cost for each of ``tiers`` from the costs at some measured tiers: linear between two measured tiers and the
    nearest measured value outside them."""
    known = sorted(costs)
    if not known:
        raise ValueError("no measured tier to interpolate from")
    out: dict[int, float] = {}
    for t in tiers:
        if t <= known[0]:
            out[t] = float(costs[known[0]])
        elif t >= known[-1]:
            out[t] = float(costs[known[-1]])
        else:
            hi = bisect.bisect_left(known, t)
            lo_t, hi_t = known[hi - 1], known[hi]
            share = (t - lo_t) / (hi_t - lo_t)
            out[t] = float(costs[lo_t] + (costs[hi_t] - costs[lo_t]) * share)
    return out


Cells = Mapping[str, Mapping[tuple[int, str], tuple[int, float, float, float]]]


def aggregate(records: Iterable[Mapping[str, Any]]) -> tuple[Cells, dict[str, str]]:
    """The measured records of a coverage sample as the cells that :func:`wiki_costs` takes: for each trio and each
    ``(tier, buff set)`` the count and the sums of the prep, solve and canonical CPU seconds, plus each trio's stratum.
    Records with an error or without the canonical solve are left out."""
    cells: dict[str, dict[tuple[int, str], list[float]]] = defaultdict(dict)
    strata: dict[str, str] = {}
    for r in records:
        if not _measured(r):
            continue
        trio = "/".join(r["trio"])
        strata[trio] = r["stratum"]
        cell = cells[trio].setdefault((r["tier"], r["buffs"]), [0, 0.0, 0.0, 0.0])
        cell[0] += 1
        cell[1] += seconds_of(r, "prep")
        cell[2] += seconds_of(r, "solve")
        cell[3] += seconds_of(r, "canon")
    return {t: {k: tuple(v) for k, v in c.items()} for t, c in cells.items()}, strata  # type: ignore[return-value]


def _parents(stratum: str) -> list[str]:
    """``type|monk|sel`` -> itself, ``type|monk``, ``type`` and ``""`` (everything)."""
    parts = stratum.split("|")
    return ["|".join(parts[:k]) for k in range(len(parts), -1, -1)]


def wiki_costs(
    cells: Cells, strata: Mapping[str, str], shapes: Mapping[str, int], tiers: Iterable[int] = TIERS
) -> dict[str, dict[int, float]]:
    """Mean seconds per scenario of the grid at the wiki evidence level, by field (``prep``, ``solve``, ``canon``) and tier.

    For each measured tier and buff set, the mean of each sampled stratum is weighted by that stratum's share of the grid
    (``shapes``); a stratum with no sampled trio takes the mean of its parent (same type and Monk flag, then same type,
    then everything sampled). The two buff sets count equally, and tiers between the measured ones are interpolated.
    """
    measured = sorted({tier for per_trio in cells.values() for tier, _ in per_trio})
    if not measured:
        raise ValueError("no measured cells")
    out: dict[str, dict[int, float]] = {name: {} for name in FIELDS}
    for tier in measured:
        for slot, name in enumerate(FIELDS):
            per_buff = []
            for buff in BUFF_SETS:
                sums: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
                for trio, per in cells.items():
                    cell = per.get((tier, buff))
                    if cell is None:
                        continue
                    for parent in _parents(strata[trio]):
                        sums[parent][0] += cell[0]
                        sums[parent][1] += cell[1 + slot]
                total, weight = 0.0, 0
                for stratum, shape in shapes.items():
                    chain = next((p for p in _parents(stratum) if p in sums), None)
                    if chain is None:
                        raise ValueError(f"nothing measured at tier {tier} with the {buff} buff set")
                    count, seconds = sums[chain]
                    total += shape * seconds / count
                    weight += shape
                per_buff.append(total / weight)
            out[name][tier] = sum(per_buff) / len(per_buff)
    return {name: interpolate_tiers(costs, tiers) for name, costs in out.items()}


def extrapolate(
    costs: Mapping[str, Mapping[int, float]], ratio: Mapping[str, float], shapes: Mapping[str, int], *,
    skip_strict: float = WIKI_FIRST_SKIP, presolve: Mapping[str, float] | None = None,
    spec_total: int = SPEC_SCENARIOS,
) -> dict[str, Any]:
    """CPU hours of the whole grid from per-scenario costs.

    ``costs[field][tier]`` are the wiki-level seconds per scenario (``prep``, ``solve`` and ``canon``, which includes the
    first solve); ``ratio[field]`` is the cost of a strict scenario relative to a wiki one; ``shapes`` are the grid's
    (race, trio, role, setup) combinations by stratum. Each combination occurs once in each of the 11 tiers x 2 buff sets
    x 2 evidence levels (a cell). The result's ``tiers`` holds, for ``all`` eleven tiers and for the ``three`` of 0, 4 and
    10, and for each stage (``solve``: prep + the first solve; ``canon``: prep + the solve and the tie stage), the CPU
    hours under the cuts ``none``; ``wiki-first`` (a share ``skip_strict`` of the strict solves is skipped); and
    ``wiki-first+presolve`` (also each solve stage divided by the speed-up ``presolve[stage]``, only when that is above 1,
    else None). Hours are for this code's own grid; ``spec_tiers`` has them scaled to ``spec_total`` scenarios.
    """
    combos = sum(shapes.values())
    scenarios = combos * GRID_CELLS
    scale = spec_total / scenarios

    def hours(tiers: Sequence[int], stage: str, cut: str) -> float | None:
        divisor = 1.0
        if cut == "wiki-first+presolve":
            gain = (presolve or {}).get(stage)
            if gain is None or gain <= 1.0:
                return None
            divisor = gain
        skip = 0.0 if cut == "none" else skip_strict
        seconds = 0.0
        for tier in tiers:
            wiki = costs["prep"][tier] + costs[stage][tier] / divisor
            strict = ratio["prep"] * costs["prep"][tier] + ratio[stage] * costs[stage][tier] / divisor
            seconds += combos * len(BUFF_SETS) * (wiki + strict * (1.0 - skip))
        return seconds / 3600

    out: dict[str, Any] = {"scenarios": scenarios, "scale": scale, "combinations": combos, "tiers": {}, "spec_tiers": {}}
    for scope, tiers in (("all", TIERS), ("three", BENCH_TIERS)):
        out["tiers"][scope] = {
            stage: {cut: hours(tiers, stage, cut) for cut in ("none", "wiki-first", "wiki-first+presolve")}
            for stage in ("solve", "canon")
        }
        out["spec_tiers"][scope] = {
            stage: {cut: (None if h is None else h * scale) for cut, h in cuts.items()}
            for stage, cuts in out["tiers"][scope].items()
        }
    mean = {name: sum(costs[name][t] for t in TIERS) / len(TIERS) for name in FIELDS}
    out["prep_share"] = {stage: mean["prep"] / (mean["prep"] + mean[stage]) for stage in ("solve", "canon")}
    return out


def canonical_interval(
    cells: Cells, strata: Mapping[str, str], shapes: Mapping[str, int], ratio: Mapping[str, float], *,
    n_boot: int = 500, seed: int = 0, skip_strict: float = WIKI_FIRST_SKIP, level: float = 0.95,
) -> tuple[float, float, float]:
    """The headline number with a confidence interval: CPU hours of the whole grid (scaled to the 2,825,460 scenarios the run is sized for),
    canonical stage, wiki-first cut, no presolve. The interval is a bootstrap over trios, resampled within each stratum.
    It covers the sampling of trios only (not the strict ratio or the wiki-first share)."""

    def headline(sample_cells: Cells, sample_strata: Mapping[str, str]) -> float:
        costs = wiki_costs(sample_cells, sample_strata, shapes)
        out = extrapolate(costs, ratio, shapes, skip_strict=skip_strict)
        return out["spec_tiers"]["all"]["canon"]["wiki-first"]

    point = headline(cells, strata)
    rng = random.Random(seed)
    by_stratum: dict[str, list[str]] = defaultdict(list)
    for trio in sorted(cells):
        by_stratum[strata[trio]].append(trio)
    replicates = []
    for _ in range(n_boot):
        boot_cells: dict[str, Any] = {}
        boot_strata: dict[str, str] = {}
        for stratum, trios in by_stratum.items():
            for n, trio in enumerate(rng.choices(trios, k=len(trios))):
                boot_cells[f"{trio}#{n}"] = cells[trio]
                boot_strata[f"{trio}#{n}"] = stratum
        replicates.append(headline(boot_cells, boot_strata))
    tail = (1 - level) / 2 * 100
    return point, percentile(replicates, tail), percentile(replicates, 100 - tail)


def decide_scope(
    all_tiers: float, three_tiers: float, threshold: float = CPU_BUDGET_HOURS, basis: str = "after the cuts"
) -> dict[str, Any]:
    """The precompute scope rule: all eleven tiers unless the grid needs more than ``threshold`` CPU
    hours after the cuts, then tiers 0, 4 and 10 are precomputed and the others solve in the browser. ``basis`` says in
    words which stage and cuts the hours are for."""
    scope = "all" if all_tiers <= threshold else "0/4/10"
    if scope == "all":
        text = (
            f"All 11 tiers are precomputed: the full grid needs {all_tiers:.0f} CPU hours {basis}, "
            f"within the {threshold:.0f} hour budget."
        )
    else:
        text = (
            f"Tiers +0, +4 and +10 are precomputed and the other tiers solve in the browser: the full grid needs "
            f"{all_tiers:.0f} CPU hours {basis}, above the {threshold:.0f} hour budget; tiers 0/4/10 alone need "
            f"{three_tiers:.0f}" + (", which is above the budget too." if three_tiers > threshold else ".")
        )
    return {
        "scope": scope, "threshold": threshold, "all_tiers_cpu_h": all_tiers, "three_tiers_cpu_h": three_tiers,
        "basis": basis, "text": text,
    }  # fmt: skip


# ---- reports -------------------------------------------------------------------------------------------------------

_PATH_TEXT = re.compile(r"[A-Za-z]:[\\/][^\s'\"]*|/(?:Users|home|root)/[^\s'\"]*")
_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?!/)|(^|[\s\"'(=])/(Users|home|root)/|\\Users\\")


def assert_public(value: Any, where: str = "report") -> None:
    """Raise ``ValueError`` if a string anywhere in ``value`` is a path into a drive or a user profile."""
    if isinstance(value, str):
        if _PATH.search(value):
            raise ValueError(f"{where} holds a local path ({value[:20]!r}...); reports carry no paths")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            assert_public(str(key), where)
            assert_public(item, f"{where}.{key}")
    elif isinstance(value, (list, tuple)):
        for n, item in enumerate(value):
            assert_public(item, f"{where}[{n}]")


def _fmt(x: Any, digits: int = 2) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:,.{digits}f}"
    return f"{x:,}" if isinstance(x, int) else str(x)


def _row(label: str, s: Mapping[str, Any], digits: int = 3) -> str:
    """One row of a seconds table: count, mean, median, p95, maximum."""
    return (
        f"| {label} | {s['n']:,} | {s['mean']:.{digits}f} | {s['p50']:.{digits}f} | {s['p95']:.{digits}f} | "
        f"{s['max']:.{digits}f} |"
    )


def _presolve_bullet(gate: Mapping[str, Any]) -> str:
    speed = gate.get("speedup", {}).get("solve")
    failed = not gate_passed(gate)
    head = f"The gate {'fails' if failed else 'passes'} on {gate.get('n')} scenarios"
    if failed:
        return (
            f"- **Presolve.** {head} ({gate.get('n_mismatch')} mismatches, {(gate.get('canonical') or {}).get('mismatches', 0)} in the tie stage, "
            f"{gate.get('errors')} errors, {gate.get('compared', 0)} compared): it stays off."
        )
    if speed is not None and speed <= 1:
        return (
            f"- **Presolve.** {head} (0 mismatches), but presolve runs at {_fmt(speed)}x the speed of presolve off on "
            "this formulation, so it stays off."
        )
    return (
        f"- **Presolve.** {head} (0 mismatches) and runs at {_fmt(speed)}x the speed of presolve off; it may be "
        "switched on once the 5,000-scenario gate passes."
    )


def _decides_bullet(result: Mapping[str, Any]) -> str | None:
    """What the tie stage costs in the decision: the same grid without it, against the budget."""
    decision, ex = result.get("decision", {}), result.get("extrapolation", {})
    tiers, cut = ex.get("spec_tiers"), decision.get("cuts")
    if not tiers or not cut or decision.get("threshold") is None:
        return None
    without = tiers["all"]["solve"].get(cut)
    if without is None:
        return None
    verdict = "within" if without <= decision["threshold"] else "above"
    return (
        f"- **What decides it.** The tie stage is most of the cost; the first solve alone would need {without:.0f} CPU "
        f"hours for all tiers under the same cuts, {verdict} the {decision['threshold']:.0f} hour budget."
    )


def _gate_text(gate: Mapping[str, Any]) -> str:
    speed = gate.get("speedup", {})
    tie = f", with the tie stage {_fmt(speed.get('canon'))}x" if speed.get("canon") is not None else ""
    return (
        f"{gate.get('n')} scenarios drawn uniformly from the grid (all tiers, races, trios, roles and setups, both buff "
        f"sets, wiki and strict-proxy pools), each solved with presolve off and with presolve on. **Objective "
        f"mismatches: {gate.get('n_mismatch')}** (a difference above {gate.get('tolerance', 1e-9):g} relative; the "
        f"largest seen is {gate.get('max_rel_diff', 0):.1e}), of {gate.get('compared')} scenarios whose two solves both ended optimal. Presolve-on runs that did not end optimal (to be "
        f"re-solved with presolve off): {gate.get('guarded')}. Errors: {gate.get('errors')}. Speed-up of presolve (time "
        f"off over time on; below 1 is slower): solve {_fmt(speed.get('solve'))}x{tie}."
    )


def _phone_bullet(js: Mapping[str, Any]) -> str:
    phone_median = js.get("phone_median_ms", 4 * js.get("median_ms", 0))
    phone_p95 = js.get("phone_p95_ms", 4 * js.get("p95_ms", 0))
    verdict = "within the budget." if phone_median < 1000 and phone_p95 < 5000 else "**over the budget.**"
    return (
        f"- **Phone budget** (median under 1 s, p95 under 5 s). highs-js on the desktop: median "
        f"{_fmt(js.get('median_ms'), 0)} ms, p95 {_fmt(js.get('p95_ms'), 0)} ms; at 4x slower (a mid-range phone) "
        f"{_fmt(phone_median, 0)} and {_fmt(phone_p95, 0)} ms: {verdict}"
    )


def _timing_section(result: Mapping[str, Any]) -> list[str]:
    bench, uniform = result.get("bench", {}), result.get("uniform", {})
    out = [
        "## Per-solve times (CPU seconds)", "",
        f"Coverage sample: {result.get('sample', {}).get('trios', '?')} trios, {bench['n']:,} scenarios. *Solve* is "
        "`solve`; *solve + tie stage* is `solve_canonical` (the first solve again, then the tie stage).", "",
        "| | n | mean | p50 | p95 | max |", "|---|---|---|---|---|---|",
    ]  # fmt: skip
    rows = (("solve", "solve"), ("solve + tie stage", "canon"), ("profile + prune + build", "prep"),
            ("prune", "prune"), ("build", "build"))  # fmt: skip
    out += [_row(label, bench[key]) for label, key in rows if bench.get(key, {}).get("n")]
    if uniform.get("wiki", {}).get("n"):
        out += [
            "", f"Uniform sample of the grid (wiki pools, {uniform['wiki']['n']:,} scenarios, all tiers and races):", "",
            "| | n | mean | p50 | p95 | max |", "|---|---|---|---|---|---|",
        ]  # fmt: skip
        out += [_row(label, uniform["wiki"][key]) for label, key in rows[:3]]
    out += ["", "## Model size and search", "", "| | mean | p50 | p95 | max |", "|---|---|---|---|---|"]
    sizes = (("items in the pool", "pool"), ("items kept by pruning", "kept"), ("columns", "cols"), ("rows", "rows"),
             ("item columns", "item_cols"), ("binaries", "binaries_total"),
             ("optional buffs", "optional_buffs"), ("nodes, solve", "nodes_solve"), ("nodes, tie stage", "nodes_canon"))  # fmt: skip
    for label, key in sizes:
        s = bench.get(key, {})
        if s.get("n"):
            out.append(f"| {label} | {s['mean']:.1f} | {s['p50']:.0f} | {s['p95']:.0f} | {s['max']:.0f} |")
    kinds = {k: v for k, v in bench.get("binaries", {}).items() if v.get("n")}
    if kinds:
        out += ["", "Mean binaries by kind: " + ", ".join(f"{k} {v['mean']:.1f}" for k, v in kinds.items()) + "."]
    by = bench.get("by", {})
    if by.get("tier"):
        out += [
            "", "## By tier, buff set and role-set type (CPU seconds)", "",
            "*monk*: the trio has a Monk. *mixed_mana sel*: three mana pools that mix WIS and INT (selection "
            "binaries); *std*: every other trio.", "",
            "| group | n | solve, mean | tie stage, mean | tie stage, p95 | columns |", "|---|---|---|---|---|---|",
        ]  # fmt: skip
        for part in ("tier", "buffs", "monk", "mixed_mana", "type"):
            for name, g in by.get(part, {}).items():
                out.append(
                    f"| {part} {name} | {g['n']:,} | {g['solve']['mean']:.2f} | {g['canon']['mean']:.2f} | "
                    f"{g['canon']['p95']:.2f} | {g['cols_mean']:.0f} |"
                )
    return [*out, ""]


def _hours_section(result: Mapping[str, Any]) -> list[str]:
    ex, decision = result.get("extrapolation", {}), result.get("decision", {})
    tiers = ex.get("spec_tiers") or ex.get("tiers")
    out = [
        "## CPU hours for the whole grid", "",
        "The grid is 11 tiers x 2 evidence levels x 2 buff sets x every race, trio, role and setup: "
        f"{result.get('grid', {}).get('scenarios', 0):,} scenarios by this code, scaled here to the 2,825,460 the run is sized for. "
        "Under *wiki-first*, 74 percent of strict solves are skipped (measured on the previous model).", "",
        "| scope | stage | no cuts | wiki-first | wiki-first + presolve |", "|---|---|---|---|---|",
    ]  # fmt: skip
    for scope, name in (("all", "all 11 tiers"), ("three", "tiers 0/4/10")):
        for stage, label in (("canon", "solve + tie stage (production)"), ("solve", "solve only")):
            row = tiers[scope][stage]
            out.append(
                f"| {name} | {label} | {_fmt(row.get('none'), 0)} | {_fmt(row.get('wiki-first'), 0)} | "
                f"{_fmt(row.get('wiki-first+presolve'), 0)} |"
            )
    out.append("")
    head = ex.get("headline_canonical_wiki_first")
    if head:
        out.append(
            f"All tiers, tie stage, wiki-first: {head['cpu_h']:.0f} CPU hours (95 percent interval {head['low']:.0f} to "
            f"{head['high']:.0f}, bootstrap over trios)."
        )
    check = result.get("uniform", {}).get("cpu_h")
    if check:
        out.append(
            f"Check from the uniform sample alone (no strata, no interpolation): {check['canon_none']:.0f} CPU hours "
            f"without cuts, {check['canon_wiki_first']:.0f} with wiki-first."
        )
    cal = result.get("calibration")
    if cal:
        wall_cal = cal.get("wall_slowdown", {}).get("canon")
        out.append(
            f"Measured alone afterwards, the same {cal['n']} scenarios took {1 / cal['slowdown']['canon']:.2f}x the CPU "
            f"time and {'n/a' if not wall_cal else format(1 / wall_cal, '.2f')}x the wall time of the run with "
            f"{cal.get('workers')} workers (tie-stage solves); the hours above are for the loaded machine."
        )
    if decision.get("wall_hours"):
        wall = decision["wall_hours"]
        out.append(
            f"Wall time for the decided figure: {wall['80_vcpu']:.1f} h on 80 vCPUs, {wall['pc_workers']:.0f} h on this PC."
        )
    return [*out, ""]


def render_markdown(result: Mapping[str, Any]) -> str:
    """The short report: the result in three lines, then the gate, the per-solve statistics, the model sizes, the CPU
    hours, the browser proxy and the notes. Parts that the result does not have are left out."""
    env, gate, decision = result.get("environment", {}), result.get("gate", {}), result.get("decision", {})
    bench, js = result.get("bench", {}), result.get("highs_js", {})
    out = [f"# Phase 2 benchmark ({result.get('date', '')})", ""]
    wall = (bench.get("wall_over_cpu") or {}).get("canon")
    shared = f" Wall time on this shared machine was {wall:.2f}x the CPU time." if wall else ""
    wearables = (env.get("catalog") or {}).get("wiki_wearables")
    catalog = f" Catalog {env.get('catalog_version')}: {wearables:,} wiki-level wearable items." if wearables else ""
    out += [
        f"highspy {env.get('highspy', '?')} (HiGHS {env.get('highs_version', '?')}, revision "
        f"{env.get('highs_githash', '?')}), Python {env.get('python', '?')}, {env.get('workers', '?')} worker processes "
        f"on {env.get('threads', '?')} threads, next to other work. All times are CPU seconds of one process (user "
        "plus system) in native HiGHS with the project's determinism options (presolve off), unless a line says "
        f"otherwise.{shared} CPU hours are hours of one thread while every other thread is busy too.{catalog}", "",
    ]  # fmt: skip
    out += ["## Result", ""]
    if decision:
        out.append(f"- **Precompute scope.** {decision['text']}")
        decides = _decides_bullet(result)
        if decides:
            out.append(decides)
    if gate:
        out.append(_presolve_bullet(gate))
    if js and not js.get("skipped"):
        out.append(_phone_bullet(js))
    out.append("")
    if gate:
        out += ["## Presolve gate", "", _gate_text(gate), ""]
        canon = gate.get("canonical", {})
        if canon.get("n"):
            out += [
                f"On the {canon['n']} scenarios that also ran the canonical solve: {canon.get('mismatches')} objective "
                f"mismatches; the same items were worn in {canon.get('same_items')} and the same kit (every item in the "
                f"same place) in {canon.get('same_kit')}. Equal value with an item in another place is a tie that the "
                "canonical stage does not break (see the notes).", "",
            ]  # fmt: skip
    if bench.get("n"):
        out += _timing_section(result)
    if (result.get("extrapolation") or {}).get("spec_tiers") or (result.get("extrapolation") or {}).get("tiers"):
        out += _hours_section(result)
    if js:
        out += ["## Browser timing proxy (highs-js, Node, desktop)", ""]
        if js.get("skipped"):
            out.append(f"Not run: {js.get('reason', 'skipped')}.")
        else:
            read = js.get("total_median_ms", 0) - js.get("median_ms", 0)
            diff = js.get("max_rel_objective_diff")
            out.append(
                f"{js.get('models')} models at evenly spaced quantiles of the native solve time, pinned highs-js "
                f"{js.get('highs', {}).get('version')}, {js.get('reps')} repeats each. Solve time of the best repeat "
                f"(the time without interference): median {_fmt(js.get('median_ms'), 0)} ms, p95 "
                f"{_fmt(js.get('p95_ms'), 0)} ms, max {_fmt(js.get('max_ms'), 0)} ms. Median of the repeats: median "
                f"{_fmt(js.get('typical_median_ms'), 0)} ms, p95 {_fmt(js.get('typical_p95_ms'), 0)} ms; CPU time: "
                f"median {_fmt(js.get('cpu_median_ms'), 0)} ms, p95 {_fmt(js.get('cpu_p95_ms'), 0)} ms. Reading the "
                f"model adds a median of {_fmt(read, 0)} ms. All optimal: {js.get('all_optimal')}; largest objective "
                f"difference to native HiGHS {'n/a' if diff is None else format(diff, '.1e')}."
            )
        out.append("")
    notes = result.get("notes")
    if notes:
        out += ["## Notes", "", *[f"- {note}" for note in notes], ""]
    return "\n".join(out) + "\n"


def environment(workers: int, inputs: Inputs | None) -> dict[str, Any]:
    solver = highspy.Highs()
    return {
        "python": platform.python_version(), "highspy": importlib.metadata.version("highspy"),
        "highs_version": ".".join(map(str, (solver.versionMajor(), solver.versionMinor(), solver.versionPatch()))),
        "highs_githash": solver.githash(), "platform": platform.system(), "machine": platform.machine(),
        "threads": os.cpu_count(), "workers": workers,
        "catalog_version": inputs.version if inputs else None, "catalog": dict(inputs.counts) if inputs else {},
    }  # fmt: skip


def write_reports(result: Mapping[str, Any], out: Path) -> None:
    assert_public(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=1, sort_keys=True, default=_json_default) + "\n"
    out.write_text(text, encoding="utf-8", newline="\n")
    out.with_suffix(".md").write_text(render_markdown(result), encoding="utf-8", newline="\n")


def _json_default(value: Any) -> Any:
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError(f"cannot write {type(value).__name__} as JSON")


# ---- summaries, the model export and the browser proxy -------------------------------------------------------------


def _group(records: Sequence[Mapping[str, Any]], key: Callable[[Mapping[str, Any]], Any]) -> dict[str, dict[str, Any]]:
    """Per-group statistics: count, solve and canonical seconds (mean, p50, p95, max), mean nodes and columns."""
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(key(record))].append(record)
    out = {}
    for name, rows in sorted(groups.items()):
        out[name] = {
            "n": len(rows),
            "solve": {k: v for k, v in summarize([seconds_of(r, "solve") for r in rows]).items() if k != "sum"},
            "canon": {k: v for k, v in summarize([seconds_of(r, "canon") for r in rows]).items() if k != "sum"},
            "prep_mean": statistics.fmean(seconds_of(r, "prep") for r in rows),
            "nodes_solve_mean": statistics.fmean(r["nodes_solve"] for r in rows),
            "cols_mean": statistics.fmean(r["cols"] for r in rows),
        }
    return out


def bench_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The statistics of a measured sample: per solve (mean, median, p95, max) for the first solve and for the solve with
    the tie stage, the build steps, nodes, model size and binaries, and the same by group."""
    ok = [r for r in records if _measured(r)]
    seconds = {
        "solve": [r["c_solve"] for r in ok], "canon": [r["c_canon"] for r in ok],
        "profile": [r["c_profile"] for r in ok], "prune": [r["c_prune"] for r in ok], "build": [r["c_build"] for r in ok],
        "prep": [seconds_of(r, "prep") for r in ok],
    }  # fmt: skip
    wall = {stage: [seconds_of(r, stage, "t") for r in ok] for stage in ("solve", "canon", "prep")}
    solve_sum, canon_sum = sum(seconds["solve"]), sum(seconds["canon"])
    kinds = BINARY_KINDS
    out: dict[str, Any] = {
        "n": len(records), "errors": len(records) - len(ok),
        "error_messages": sorted({r["error"] for r in records if r.get("error")})[:5],
        **{name: summarize(values) for name, values in seconds.items()},
        "wall": {name: summarize(values) for name, values in wall.items()},
        "wall_over_cpu": {stage: _ratio(sum(wall[stage]), sum(seconds[stage])) for stage in wall},
        "tie_stage_over_solve": _ratio(canon_sum - solve_sum, solve_sum),
        "nodes_solve": summarize([r["nodes_solve"] for r in ok]), "nodes_canon": summarize([r["nodes_canon"] for r in ok]),
        "cols": summarize([r["cols"] for r in ok]), "rows": summarize([r["rows"] for r in ok]),
        "item_cols": summarize([r["item_cols"] for r in ok]), "pool": summarize([r["n_pool"] for r in ok]),
        "kept": summarize([r["n_kept"] for r in ok]), "optional_buffs": summarize([r["buffs_optional"] for r in ok]),
        "binaries": {kind: summarize([r["binaries"][kind] for r in ok]) for kind in kinds},
        "binaries_total": summarize([sum(r["binaries"].values()) for r in ok]),
        "not_optimal": sum(r["status_solve"] != "optimal" or r["status_canon"] != "optimal" for r in ok),
        "canonical_stage_ran": sum(bool(r["canonical"]) for r in ok),
        "selection_pools": sum(r["pools"].get("MANA") == "select" for r in ok),
        "buff_resolution": summarize([r["c_buffs"] for r in ok if "c_buffs" in r]),
    }  # fmt: skip
    keys: tuple[tuple[str, Callable[[Mapping[str, Any]], Any]], ...] = (
        ("type", lambda r: r["stratum"].split("|")[0]), ("monk", lambda r: r["stratum"].split("|")[1]),
        ("mixed_mana", lambda r: r["stratum"].split("|")[2]), ("tier", lambda r: r["tier"]),
        ("buffs", lambda r: r["buffs"]), ("setup", lambda r: r["setup"]), ("role", lambda r: r["role"]),
        ("race", lambda r: r["race"]), ("stratum", lambda r: r["stratum"]),
    )  # fmt: skip
    out["by"] = {name: _group(ok, key) for name, key in keys}
    return out


def export_models(ctx: Context, records: Sequence[Mapping[str, Any]], count: int, out_dir: Path) -> list[dict[str, Any]]:
    """Write ``count`` of the measured models as MPS files, picked at evenly spaced quantiles of the solve time, and a
    ``manifest.json`` that says what each should solve to. Returns the manifest entries."""
    usable = [r for r in records if not r.get("error") and r.get("status_solve") == "optimal" and "model_F" in r]
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.mps"):
        old.unlink()
    manifest = []
    for rank, index in enumerate(quantile_picks([r["c_solve"] for r in usable], count), 1):
        record = usable[index]
        scenario = Scenario.from_dict(record)
        milp = ctx.prepare(scenario).milp
        name = f"{rank:02d}-{'-'.join(scenario.trio)}-{scenario.role}-{scenario.setup}-t{scenario.tier}-{scenario.buffs}.mps"
        _highs.write_mps(milp, out_dir / name)
        manifest.append(
            {
                "file": name, "key": scenario.key, "cols": milp.num_cols, "rows": milp.num_rows,
                "integers": int(milp.integrality.sum()), "objective": record["model_F"],
                "python_cpu_s": record["c_solve"], "python_wall_s": record["t_solve"], "python_nodes": record["nodes_solve"],
            }
        )
    document = {"highs": highspy.Highs().githash(), "options": dict(_highs.OPTIONS), "models": manifest}
    (out_dir / "manifest.json").write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8", newline="\n")
    return manifest


def run_highs_js(mps_dir: Path, reps: int = 3, timeout: float = 3600.0) -> dict[str, Any]:
    """Time the exported models with the pinned highs-js in Node (``scripts/bench-highs.mjs``); the script's own JSON is
    returned, or ``{"skipped": True, "reason": ...}`` when Node or the package is not there."""
    node = shutil.which("node")
    if node is None:
        return {"skipped": True, "reason": "node is not installed"}
    out_json = mps_dir / "highs-js.json"
    out_json.unlink(missing_ok=True)
    command = [node, str(REPO / "scripts" / "bench-highs.mjs"), str(mps_dir), "--json", str(out_json), "--reps", str(reps)]
    try:
        proc = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return {"skipped": True, "reason": "node did not finish"}
    if proc.returncode != 0 or not out_json.is_file():
        return {"skipped": True, "reason": f"scripts/bench-highs.mjs exited {proc.returncode} (is highs installed? npm ci)"}
    return json.loads(out_json.read_text(encoding="utf-8"))


# ---- the command line ----------------------------------------------------------------------------------------------


def _progress(label: str) -> Callable[[int, int, float], None]:
    state = {"last": 0.0}

    def report(done: int, total: int, elapsed: float) -> None:
        if done == total or elapsed - state["last"] >= 20:
            state["last"] = elapsed
            eta = elapsed * (total - done) / done if done else 0.0
            print(f"[{label}] {done}/{total} in {elapsed:6.0f}s, about {eta:5.0f}s to go", file=sys.stderr, flush=True)

    return report


def _total(rows: Iterable[Mapping[str, Any]], field_: str, clock: str = "c") -> float:
    """The summed seconds of ``prep`` (profile, prune, build), ``solve`` or ``canon`` over measured records."""
    return sum(seconds_of(r, field_, clock) for r in rows)


def _measured(record: Mapping[str, Any]) -> bool:
    """Whether a record has all its measurements (no error, and the tie-stage solve ran)."""
    return not record.get("error") and "c_canon" in record


def paired_ratio(wiki: Sequence[Mapping[str, Any]], strict: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """The cost of a strict-proxy scenario relative to its wiki twin, by field: the ratio of the sums over the pairs in
    which both were measured."""
    pairs = [(w, s) for w, s in zip(wiki, strict, strict=True) if _measured(w) and _measured(s)]
    if not pairs:
        raise ValueError("no pair of wiki and strict-proxy measurements")
    return {f: _total((s for _, s in pairs), f) / _total((w for w, _ in pairs), f) for f in FIELDS}


def calibration(parallel: Sequence[Mapping[str, Any]], alone: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """How much slower scenarios ran in the parallel benchmark than alone: for the same scenarios measured both ways, the
    ratio of the total seconds by field. ``slowdown`` is for the CPU time (the load makes a core slower by sharing it
    with another thread and its caches with other processes), ``wall_slowdown`` for the wall time (which also holds
    the waits for a free core)."""
    pairs = [(p, a) for p, a in zip(parallel, alone, strict=True) if _measured(p) and _measured(a)]
    if not pairs:
        raise ValueError("no scenario was measured both ways")

    def ratios(clock: str) -> dict[str, float]:
        return {f: _total((p for p, _ in pairs), f, clock) / _total((a for _, a in pairs), f, clock) for f in FIELDS}

    return {"n": len(pairs), "slowdown": ratios("c"), "wall_slowdown": ratios("t")}


def uniform_hours(
    wiki: Sequence[Mapping[str, Any]], strict: Sequence[Mapping[str, Any]], stage: str, skip: float,
    spec_total: int = SPEC_SCENARIOS,
) -> float:
    """CPU hours of the whole grid from a uniform sample alone: the mean total of a wiki scenario and of a strict one,
    for half the grid each, the strict half cut by the wiki-first share ``skip``. No strata, no interpolation."""

    def mean_total(rows: Sequence[Mapping[str, Any]]) -> float:
        good = [r for r in rows if _measured(r)]
        return (_total(good, "prep") + _total(good, stage)) / len(good)

    return spec_total / 2 * (mean_total(wiki) + (1 - skip) * mean_total(strict)) / 3600


def tier_seconds(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, float]]:
    """Mean prep, solve and canonical seconds per tier of the measured records."""
    out = {}
    for tier in sorted({r["tier"] for r in records}):
        rows = [r for r in records if r["tier"] == tier and _measured(r)]
        if rows:
            out[str(tier)] = {f: _total(rows, f) / len(rows) for f in FIELDS} | {"n": len(rows)}
    return out


def _count(text: str) -> int:
    """An argument that is a number of scenarios: a whole number, not below zero (a negative sample draws none, and a gate of none verifies nothing)."""
    try:
        number = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if number < 0:
        raise argparse.ArgumentTypeError(f"{number} is below zero")
    return number


def build_parser() -> argparse.ArgumentParser:
    today = datetime.date.today().isoformat()
    parser = argparse.ArgumentParser(prog="python -m trioforge.bench", description=(__doc__ or "").split("\n")[0])
    add = parser.add_argument
    add("--catalog", help="the catalog file (default: $TRIOFORGE_CATALOG, else derived/catalog.json)")
    add("--out", default=f"reports/bench-{today}.json", help="the JSON report; a .md is written beside it")
    add("--sample", type=_count, default=500, help="scenarios of the presolve gate (default 500; the CI gate uses 5000)")
    add("--gate-only", action="store_true", help="run only the presolve gate; the exit code is 1 on a mismatch (in either stage), an error or a gate that compared nothing")
    add("--render", metavar="JSON", help="rewrite the notes and the markdown beside an existing JSON report, and exit")
    add("--canonical-every", type=int, default=5, help="the gate compares the canonical solve on every N-th scenario")
    add("--bench-trios", type=int, default=60, help="trios of the coverage sample (the coverage rules need 40 or more)")
    add("--races", default=",".join(BENCH_RACES), help="races of the coverage sample")
    add("--tiers", default=",".join(map(str, BENCH_TIERS)), help="tiers of the coverage sample")
    add("--max-scenarios", type=int, default=0, help="keep only this many coverage scenarios (0: all of them)")
    add("--calibrate", type=int, default=60, help="coverage scenarios re-measured alone, to see the load's slowdown")
    add("--uniform", type=int, default=3000, help="scenarios of the uniform check sample, each also as strict proxy")
    add("--mps", type=int, default=20, help="models to export for the browser proxy")
    add("--mps-dir", default="reports/bench-mps")
    add("--no-node", action="store_true", help="do not time the exported models with highs-js")
    add("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 4), help="worker processes (default: threads - 4)")
    add("--time-limit", type=float, default=300.0, help="seconds allowed to each solve")
    add("--seed", type=int, default=1)
    add("--skip-strict", type=float, default=WIKI_FIRST_SKIP, help="share of strict solves that wiki-first skips")
    return parser


def replace_evidence(scenario: Scenario, evidence: str) -> Scenario:
    return dataclasses.replace(scenario, evidence=evidence)


def _driver_notes(bench: Mapping[str, Any], shapes: Mapping[str, int]) -> list[str]:
    """Where the time of a production scenario goes: preparation, the first solve, the tie stage, and the trios whose
    three mana pools mix WIS and INT (selection binaries)."""
    out = []
    prep, solve_, canon = (bench.get(k, {}).get("mean") for k in ("prep", "solve", "canon"))
    if prep is not None and solve_ is not None and canon is not None:
        total = prep + canon
        out.append(
            f"Where the time goes (mean CPU seconds per production scenario, {total:.2f}): preparing the model "
            f"{prep:.2f} ({prep / total:.0%}), the first solve {solve_:.2f} ({solve_ / total:.0%}), the tie stage "
            f"{canon - solve_:.2f} ({(canon - solve_) / total:.0%})."
        )
    by_stratum = bench.get("by", {}).get("stratum", {})
    if by_stratum and shapes and set(shapes) <= set(by_stratum):  # the grid's own weights, not the sample's
        parts = {"sel": [0.0, 0.0], "std": [0.0, 0.0]}  # the combinations and the tie-stage seconds of each kind
        for stratum, count in shapes.items():
            kind = stratum.rsplit("|", 1)[1]
            parts[kind][0] += count
            parts[kind][1] += count * by_stratum[stratum]["canon"]["mean"]
        total_count, total_time = parts["sel"][0] + parts["std"][0], parts["sel"][1] + parts["std"][1]
        if parts["sel"][0] and parts["std"][0]:
            out.append(
                f"The trios with three mana pools that mix WIS and INT (selection binaries) are "
                f"{parts['sel'][0] / total_count:.0%} of the grid and {parts['sel'][1] / total_time:.0%} of its time with "
                f"the tie stage: {parts['sel'][1] / parts['sel'][0]:.2f} CPU seconds a scenario against "
                f"{parts['std'][1] / parts['std'][0]:.2f}."
            )
    return out


def notes_for(result: Mapping[str, Any]) -> list[str]:
    """The caveats of a report, with the numbers of this run."""
    ex, gate = result.get("extrapolation", {}), result.get("gate", {})
    ratio = ex.get("strict_to_wiki_ratio", {})
    out = [
        f"Strict level: the public catalog has no strict items, so a strict solve is stood in for by a fixed "
        f"{STRICT_SHARE:.0%} of the wiki items. Against its wiki twin it costs {ratio.get('prep', 0):.2f}x to prepare, "
        f"{ratio.get('solve', 0):.2f}x to solve and {ratio.get('canon', 0):.2f}x with the tie stage. The 74 percent of "
        "strict solves that wiki-first skips was measured on the previous model; it cannot be measured without strict items.",
        "Sampling: the coverage sample has three races and tiers 0, 4 and 10; the other eight tiers are interpolated. "
        "The uniform sample (all 16 races, all 11 tiers) is the check. The interval covers the choice of trios only, and "
        "treats a stratum with a single sampled trio as exact.",
    ]  # fmt: skip
    out += _driver_notes(result.get("bench", {}), result.get("grid", {}).get("by_stratum", {}))
    canon = gate.get("canonical", {})
    if canon.get("n") and gate.get("compared"):
        out.append(
            f"Ties: between presolve off and on, the same items were worn in {gate['same_items']} of {gate['compared']} "
            f"plain solves and {canon['same_items']} of {canon['n']} solves with the tie stage, but every item in the "
            f"same place in only {gate['same_kit']} and {canon['same_kit']}. An item that fits a slot and the Any slots "
            "can swap places with equal value and equal rank sum (a chest piece in the chest or in an Any slot), so the "
            "tie stage does not fix the places; the kits agree up to that."
        )
    out.append(
        "Clock: times are the CPU time of the process, whose tick is 1/64 s; one short step reads coarsely, and sums "
        "over thousands of scenarios do not. Other work shared the machine while the workers ran."
    )
    prep_share = ex.get("prep_share", {}).get("canon")
    if prep_share is not None:
        out.append(
            f"Not measured: the build-once cut. Preparing a model is {prep_share:.0%} of a production scenario "
            "(preparation plus the solve and tie stage), which is the most that cut could save."
        )
    uniform = result.get("uniform", {}).get("wiki", {})
    if uniform.get("prep", {}).get("n") and uniform.get("canon", {}).get("n"):
        per_solve = uniform["prep"]["mean"] + uniform["canon"]["mean"]
        out.append(
            f"The robustness seal (about 55,000 extra solves) would add about "
            f"{55_000 * per_solve / 3600:.0f} CPU hours at the mean cost of a production scenario."
        )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.render:  # no measurement: the report text again from the numbers in an earlier report
        path = Path(args.render)
        document = json.loads(path.read_text(encoding="utf-8"))
        document["notes"] = notes_for(document)
        write_reports(document, path)
        print(f"wrote {path.with_suffix('.md')}", file=sys.stderr)
        return 0
    found = args.catalog or find_catalog()
    if found is None:
        print("no catalog: build derived/catalog.json or set TRIOFORGE_CATALOG", file=sys.stderr)
        return 2
    catalog = str(found)
    inputs = Inputs.load(catalog)
    ctx = Context(inputs)
    tables = inputs.tables
    workers = max(1, args.workers)
    started = time.perf_counter()
    result: dict[str, Any] = {"date": datetime.date.today().isoformat(), "environment": environment(workers, inputs)}
    common = {"inputs": inputs, "catalog": catalog, "workers": workers, "time_limit": args.time_limit}
    seconds: dict[str, float] = {}

    # 1. the presolve gate
    gate: dict[str, Any] = {}
    if args.sample:
        mark = time.perf_counter()
        gate = presolve_gate(
            args.sample, args.seed, canonical_every=args.canonical_every, progress=_progress("gate"), **common
        )
        seconds["gate"] = time.perf_counter() - mark
    result["gate"] = gate
    if args.gate_only:
        write_reports(result, Path(args.out))
        passed = gate_passed(gate)
        print(f"presolve gate: {'passed' if passed else 'FAILED'}", file=sys.stderr)
        return 0 if passed else 1

    # 2. the coverage sample
    mark = time.perf_counter()
    races = [r for r in args.races.split(",") if r]
    tiers = [int(t) for t in args.tiers.split(",") if t]
    minimums = {} if args.bench_trios >= 40 else {"min_monk": 0, "min_mixed": 0, "min_caster": 0}
    trios = pick_trios(tables, args.bench_trios, args.seed, **minimums)
    coverage = coverage_sample(tables, trios, races=races, tiers=tiers)
    if args.max_scenarios and args.max_scenarios < len(coverage):
        keep = sorted(random.Random(args.seed).sample(range(len(coverage)), args.max_scenarios))
        coverage = [coverage[i] for i in keep]
    records = run(coverage, progress=_progress("bench"), **common)
    seconds["bench"] = time.perf_counter() - mark
    result["bench"] = bench_summary(records)
    by_type = Counter(role_set_type(t) for t in trios)
    result["sample"] = {
        "trios": len(trios), "races": races, "tiers": tiers, "scenarios": len(coverage),
        "monk_trios": sum("MNK" in t for t in trios),
        "mixed_mana_trios": sum(stratum_of(t, tables).endswith("|sel") for t in trios),
        "all_caster_trios": by_type["caster"], "trios_by_type": dict(sorted(by_type.items())),
        "trios_by_stratum": dict(sorted(Counter(stratum_of(t, tables) for t in trios).items())),
        "population_by_stratum": dict(sorted(Counter(stratum_of(t, tables) for t in all_trios()).items())),
    }  # fmt: skip

    # 3. the uniform check sample, each scenario run at the wiki level and as its strict-proxy twin
    shapes = grid_shapes(tables)
    result["grid"] = {
        "combinations_per_cell": sum(shapes.values()), "cells": GRID_CELLS,
        "scenarios": sum(shapes.values()) * GRID_CELLS, "spec_scenarios": SPEC_SCENARIOS, "by_stratum": shapes,
    }  # fmt: skip
    wiki_rows: list[dict[str, Any]] = []
    strict_rows: list[dict[str, Any]] = []
    twins: list[Scenario] = []
    if args.uniform:
        mark = time.perf_counter()
        twins = random_sample(tables, args.uniform, args.seed + 100, evidences=("wiki",))
        both = twins + [replace_evidence(s, "strict-proxy") for s in twins]
        done = run(both, progress=_progress("uniform"), chunk=8, **common)
        wiki_rows, strict_rows = done[: len(twins)], done[len(twins) :]
        seconds["uniform"] = time.perf_counter() - mark

    if args.calibrate:  # the pool is idle now: measure some of the same scenarios alone
        mark = time.perf_counter()
        measured = [r for r in records if _measured(r)]
        picks = sorted(random.Random(args.seed).sample(range(len(measured)), min(args.calibrate, len(measured))))
        chosen = [measured[i] for i in picks]
        alone = [ctx.measure(Scenario.from_dict(r), time_limit=args.time_limit) for r in chosen]
        result["calibration"] = {**calibration(chosen, alone), "workers": workers}
        seconds["calibration"] = time.perf_counter() - mark

    # 4. the extrapolation and the decision
    cells, strata = aggregate(records)
    ratio = paired_ratio(wiki_rows, strict_rows) if args.uniform else dict.fromkeys(FIELDS, STRICT_SHARE)
    costs = wiki_costs(cells, strata, shapes)
    gate_ok = gate_passed(gate)
    presolve = {k: v for k, v in gate["speedup"].items() if v is not None} if gate_ok else None
    extrap = extrapolate(costs, ratio, shapes, skip_strict=args.skip_strict, presolve=presolve)
    point, low, high = canonical_interval(cells, strata, shapes, ratio, skip_strict=args.skip_strict, seed=args.seed)
    extrap.update(
        wiki_costs_seconds={f: {str(t): v for t, v in c.items()} for f, c in costs.items()},
        strict_to_wiki_ratio=ratio, measured_tier_seconds=tier_seconds(records), skip_strict=args.skip_strict,
        headline_canonical_wiki_first={"cpu_h": point, "low": low, "high": high, "level": 0.95, "resamples": 500},
    )
    if args.uniform:  # the check: the same hours from the uniform sample alone, with no strata and no interpolation
        result["uniform"] = {
            "n": len(twins),
            "cpu_h": {
                f"{stage}_{cut}": uniform_hours(wiki_rows, strict_rows, stage, 0.0 if cut == "none" else args.skip_strict)
                for stage in ("solve", "canon") for cut in ("none", "wiki_first")
            },
            "wiki": bench_summary(wiki_rows), "strict_proxy": bench_summary(strict_rows),
            "wiki_tier_seconds": tier_seconds(wiki_rows),
        }  # fmt: skip
    result["extrapolation"] = extrap
    spec = extrap["spec_tiers"]
    cut = "wiki-first+presolve" if spec["all"]["canon"]["wiki-first+presolve"] is not None else "wiki-first"
    basis = "with the tie stage and the wiki-first cut" + (" and presolve" if cut.endswith("presolve") else "")
    decision = decide_scope(spec["all"]["canon"][cut], spec["three"]["canon"][cut], basis=basis)
    decision.update(
        stage="canon", cuts=cut, without_presolve=spec["all"]["canon"]["wiki-first"], no_cuts=spec["all"]["canon"]["none"],
        wall_hours={"80_vcpu": decision["all_tiers_cpu_h"] / 80, "pc_workers": decision["all_tiers_cpu_h"] / workers},
    )
    result["decision"] = decision

    # 5. the browser proxy
    mps_dir = Path(args.mps_dir)
    manifest = export_models(ctx, records, args.mps, mps_dir) if args.mps else []
    if args.no_node or not manifest:
        js: dict[str, Any] = {"skipped": True, "reason": "not requested" if args.no_node else "no models exported"}
    else:
        js = run_highs_js(mps_dir)
    js["models_exported"] = len(manifest)
    result["highs_js"] = js
    seconds["total"] = time.perf_counter() - started
    result["seconds"] = seconds
    result["notes"] = notes_for(result)

    out = Path(args.out)
    write_reports(result, out)
    with gzip.open(out.with_name(out.stem + "-records.jsonl.gz"), "wt", encoding="utf-8", newline="\n") as handle:
        for record in [*records, *wiki_rows, *strict_rows]:
            handle.write(json.dumps(record, sort_keys=True, default=_json_default) + "\n")
    print(f"wrote {out} and {out.with_suffix('.md')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
