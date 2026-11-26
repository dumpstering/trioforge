"""The cases of the parity fixtures: one scenario, one Upgrade session or one brute-force instance, with the Python outputs.

A **case** (``kind`` ``case``) is a JSON document that holds what a port needs to build the same program and what Python
made of it, and nothing else. :mod:`trioforge.export.fixtures` describes the format; this module makes the documents.

* The shared state of a run is an :class:`Inputs`: the tables, the catalog (refused if it holds a strict item that the private
  flags made; a strict item that community reports alone made is public, and the ladder is asked again about it without the
  reports), the item table, the resolved buff sets and the pools of a trio. Nothing is read from anywhere else.
* :func:`make_scenario` and :func:`scenario_case` make a case of the ``matrix`` or ``pmb36`` family: a profile (with the
  weights composed when the spec says so), the pool at one tier, the pruning, the built model and the canonical solve.
* :func:`upgrade_case` makes a case of the ``upgrade`` family: Equip now and the first steps of the farm path, the best 2 and 3
  sets, each with the program that was built (it records what ``trioforge.upgrade`` passes to the builder and the pruning, so
  the case holds exactly what the reference did) and the Every-slot swaps.
* :func:`brute_case` makes a case of the ``brute`` family: a small invented instance, its exact maximum by enumeration and
  the program and solve.

Every item a case uses is a **record** of the item table (``browser.items``), or for an invented item the record that
:func:`trioforge.export.brute.item_record` writes; a pool is a list of idents ``key@tier``. A case checks, before it is
written, that every record read back with the tier rules gives the item the builder was given.
"""

from __future__ import annotations

import contextlib
import dataclasses
import inspect
import random
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from trioforge import bench, upgrade
from trioforge.data.jsonio import load_strict
from trioforge.export import brute, browser, milp_json
from trioforge.export.fixture_plan import PROCS_BASE, RANGED_BASE, BuffKeys, ScenarioSpec, UpgradeSpec
from trioforge.model import formulas as fm
from trioforge.model import procs as procs_module
from trioforge.model import roles
from trioforge.model.buffs import COMPONENTS, Buff, BuffSet, Dropped, buffsets
from trioforge.model.items import SLOT_INSTANCES, ItemVec, at_tier
from trioforge.model.profile import Profile, make_profile
from trioforge.model.tables import REPO
from trioforge.model.tables import load as load_tables
from trioforge.model.tiers import arrival_tier, cost_to_reach
from trioforge.precompute import grid
from trioforge.solver.haste import HasteSolve, solve_scenario
from trioforge.solver.model import BuildOptions, build_milp, eval_buff_totals, ident
from trioforge.solver.prune import prune
from trioforge.solver.solve import Solution, solve_canonical

__all__ = [
    "FORBIDDEN_REASONS",
    "FORMAT",
    "FixtureError",
    "Inputs",
    "Scenario",
    "Session",
    "breakdown_json",
    "brute_case",
    "buffset_doc",
    "buffset_from_doc",
    "eval_totals_for",
    "exact_json",
    "idents",
    "kit_json",
    "make_scenario",
    "make_session",
    "options_from_json",
    "options_json",
    "scenario_case",
    "slot_cases",
    "upgrade_case",
]

FORMAT = 1
SECONDARY_INDEX = SLOT_INSTANCES.index("SECONDARY")
PRIMARY_INDEX = SLOT_INSTANCES.index("PRIMARY")
#: the reason of a sighting of the maintainer's, the one a fixture must never name. (A community report is public: its reasons, ``community-report`` and
#: ``community-report-outweighed``, are not here, and every check against this list matches the whole code, never a part of one.)
FORBIDDEN_REASONS = ("seen-in-game",)
OWNED_TIERS = (0, 0, 0, 2, 4, 4, 6)
OWNED_COUNTS = (1, 1, 1, 2)
BEST_SET_SIZES = (2, 3)  # the sizes of the best sets an Upgrade case records (the tab shows the best 2 and 3 behind an expander)
TRUTHFUL_EVERY = 4  # every fourth brute-force instance is a truthful one (the weapon term is paid the haste each kit counts)
REL = 1e-9  # the brute force and the solver must agree this closely, relative


class FixtureError(ValueError):
    """The fixtures cannot be made from these inputs (a catalog with strict items, a solver that disagrees with a brute
    force, a record that does not read back as the item it stands for ...). The message says which."""


# ---- JSON forms ---------------------------------------------------------------------------------------------------


def exact_json(value: Any) -> Any:
    """``value`` with every number turned into a reduced ``"p/q"`` string; text, flags and null stay, a tuple is a list."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float, Fraction)):
        return browser.rat(value)
    if isinstance(value, Mapping):
        return {str(key): exact_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [exact_json(item) for item in value]
    raise TypeError(f"cannot write {type(value).__name__} as an exact value")


def breakdown_json(breakdown: fm.Breakdown) -> dict[str, Any]:
    """A :class:`~trioforge.model.formulas.Breakdown` with every number as a ``"p/q"`` string (the classes whose pools
    count stay lists of class codes)."""
    totals = dict(breakdown.totals)
    counted = totals.get("procs")
    if counted is not None:  # (what each hand counts: the value of its proc, 0 for none, and the index and the part the procs add: names and donors are not exact numbers, and the program says the rest)
        totals["procs"] = {
            hand: 0 if counted[hand] is None else counted[hand].value for hand in ("PRIMARY", "SECONDARY")
        } | {"index": counted["index"], "part": counted["part"]}
    return {"F": browser.rat(breakdown.F), "parts": exact_json(breakdown.parts), "totals": exact_json(totals)}


def kit_json(kit: Sequence[ItemVec | None]) -> list[list[Any] | None]:
    """A kit of 22 places as ``[key, tier]`` or null for an empty place."""
    if len(kit) != len(SLOT_INSTANCES):
        raise FixtureError(f"a kit has {len(SLOT_INSTANCES)} places, not {len(kit)}")
    return [None if item is None else [item.key, item.tier] for item in kit]


def options_json(options: BuildOptions) -> dict[str, Any]:
    """The builder options that can differ between cases (never the test hook or the legacy objective)."""
    if options.mutation is not None or options.legacy is not None:
        raise FixtureError("a fixture is made with the production builder: no mutation and no legacy objective")
    return {
        "any_rule": options.any_rule, "haste_assumed": options.haste_assumed, "haste_floor": options.haste_floor,
        "haste_exact": options.haste_exact,
        "owned_caps": dict(options.owned_caps or {}), "new_keys": sorted(options.new_keys), "max_new": options.max_new, "upgrades": dict(options.upgrades or {}),
    }  # fmt: skip


def options_from_json(doc: Mapping[str, Any]) -> BuildOptions:
    return BuildOptions(
        any_rule=doc["any_rule"], haste_assumed=doc["haste_assumed"], haste_floor=doc["haste_floor"], haste_exact=doc["haste_exact"],
        owned_caps=doc["owned_caps"] or None,
        new_keys=frozenset(doc["new_keys"]), max_new=doc["max_new"], upgrades=doc["upgrades"] or None,
    )


def buff_entry(buff: Buff) -> dict[str, Any]:
    """A buff as the bundle's ``buff_table`` writes it."""
    entry: dict[str, Any] = {
        "name": buff.name,
        "classes": dict(buff.classes),
        "vec": {name: amount for name, amount in zip(COMPONENTS, buff.vec, strict=True) if amount},
        "source": buff.source,
    }
    if buff.illusion:
        entry["illusion"] = True
    return entry


def buffset_doc(buffset: BuffSet | None) -> dict[str, Any] | None:
    """A resolved buff set as ``{"set", "table"}``: the set as the bundle writes it (``buffs[key]["set"]``) and the entries
    of its buffs (``buff_table``), or null for no buffs."""
    if buffset is None:
        return None
    table = {str(buff.id): buff_entry(buff) for buff in sorted((*buffset.always_on, *buffset.optional), key=lambda b: b.id)}
    return {
        "set": {
            "always_on": [buff.id for buff in buffset.always_on],
            "optional": [buff.id for buff in buffset.optional],
            "conflicts": [[a, b, list(reasons)] for (a, b), reasons in buffset.conflict_reasons],
            "cliques": [list(clique) for clique in buffset.cliques],
            "cardinality": buffset.cardinality,
            "dropped": [[d.id, d.name, d.reason, d.by] for d in buffset.dropped],
        },
        "table": table,
    }


def buffset_from_doc(doc: Mapping[str, Any] | None) -> BuffSet | None:
    """The buff set of :func:`buffset_doc` (what a reader of a case does)."""
    if doc is None:
        return None
    table, listed = doc["table"], doc["set"]

    def buff(buff_id: int) -> Buff:
        entry = table[str(buff_id)]
        vec = [0] * len(COMPONENTS)
        for name, amount in entry["vec"].items():
            vec[COMPONENTS.index(name)] = amount
        return Buff(
            id=buff_id, name=entry["name"], classes=tuple(entry["classes"].items()), target=6, duration_ticks=None,
            permanent=True, effects=(), commands=(), vec=tuple(vec), illusion=bool(entry.get("illusion", False)),
            source=entry["source"],
        )

    return BuffSet(
        always_on=tuple(buff(i) for i in listed["always_on"]), optional=tuple(buff(i) for i in listed["optional"]),
        conflicts=tuple((a, b) for a, b, _ in listed["conflicts"]),
        conflict_reasons=tuple(((a, b), tuple(why)) for a, b, why in listed["conflicts"]),
        cliques=tuple(tuple(c) for c in listed["cliques"]), cardinality=listed["cardinality"],
        dropped=tuple(Dropped(*d) for d in listed["dropped"]),
    )


def idents(items: Iterable[ItemVec]) -> list[str]:
    return [ident(item.key, item.tier) for item in items]


# ---- the shared state of a run -------------------------------------------------------------------------------------------


def _code(reason: Mapping[str, Any]) -> str:
    return str(reason.get("code", "")).split(":")[0]


def _names_a_sighting(reason: Mapping[str, Any]) -> bool:
    return _code(reason) in FORBIDDEN_REASONS


def _by_community_alone(evidence: Mapping[str, Any]) -> bool:
    """Whether an item is strict because players reported it and for no other reason: its reasons have ``community-report`` and neither the maintainer's sighting nor a listing
    of the EQ Legends Tools catalog. Community reports are public (``rules/community-seen.json``), and the guard of the fixtures is about the private flags."""
    codes = {_code(reason) for reason in evidence.get("reasons", ()) if isinstance(reason, Mapping)}
    return evidence.get("level") == "strict" and "community-report" in codes and not codes & {"seen-in-game", "eql-catalog"}


def _ladder_without_reports(root: Path, items: Sequence[Mapping[str, Any]]) -> Any:
    """The context the catalog builder gives the ladder, without the reports of players, a seen flag or a listing: the rules, the client data and the quests of the checkout, and the
    items of the catalog (for the names that are out of era and the names two pages share). :class:`FixtureError` where a file cannot be read."""
    from trioforge.data import catalog as catalog_module
    from trioforge.data import evidence as ladder

    try:
        client = catalog_module.check_client(root / "derived" / "client")
        hand = ladder.load_hand_lists(root / "rules" / "hand-lists.json")
        aliases = ladder.load_aliases(root / "rules" / "zone-aliases.json", zone_ids=client.ids)
        quests = ladder.QuestTable.from_data(load_strict(root / "derived" / "quests.json"), "quests.json")
    except (OSError, ValueError, catalog_module.BuildError) as error:
        raise FixtureError(f"the ladder cannot be asked again about the items that reports made strict: {type(error).__name__}") from error
    return ladder.Context(
        flagged=client.flagged, aliases=aliases, hand=hand, quests=quests, out_of_era_names=ladder.out_of_era_names(items, hand), ambiguous_names=ladder.ambiguous_names(items)
    )


class Inputs:
    """The tables, the catalog and everything derived from them that the cases share.

    ``catalog_path`` defaults to the catalog of ``root`` (:func:`trioforge.precompute.grid.find_catalog`: ``$TRIOFORGE_CATALOG``, else ``derived/catalog.json`` of
    ``root``, this checkout by default, else the one of the main checkout of a worktree). A catalog with a
    strict item, or with an item whose reasons name a sighting, is refused: the fixtures come from the public catalog only,
    and "strict" in a fixture means the hash proxy of :func:`trioforge.bench.strict_proxy`. The one exception is a strict item
    that players' reports alone made (the first accepted report makes one): community reports are public, but the strict record
    of such an item holds the report and a conflict-note and none of the signals the report lifted it over, so the ladder is asked
    again about it without the reports (:func:`_ladder_without_reports`, from the files of ``root``), and what it answers is the
    evidence of the item here, whichever level that is: wiki, disputed or hidden. It is what the catalog without the report has,
    and the fixtures do not change for the report."""

    def __init__(self, root: Path = REPO, catalog_path: Path | None = None) -> None:
        self.root = Path(root)
        self.tables = load_tables(self.root)
        self.rules = self.tables.rules
        path = catalog_path if catalog_path is not None else grid.find_catalog(self.root)
        if path is None:
            raise FixtureError("no catalog found; build one or pass --catalog")
        document = load_strict(path)
        if not isinstance(document, dict) or not isinstance(document.get("items"), list):
            raise FixtureError(f"{Path(path).name}: not a catalog (an object with a list of items)")
        for item in document["items"]:
            if not isinstance(item, dict) or not isinstance(item.get("evidence"), dict) or "key" not in item:
                raise FixtureError(
                    f"{Path(path).name}: an item has no key or no evidence level (is this the catalog the builder writes?)"
                )
        by_reports = [item for item in document["items"] if _by_community_alone(item["evidence"])]
        if by_reports:
            from trioforge.data.evidence import classify

            context = _ladder_without_reports(self.root, document["items"])
            for item in by_reports:
                item["evidence"] = classify(item, context)
        strict = [item["key"] for item in document["items"] if item["evidence"].get("level") == "strict"]
        seen = [
            item["key"] for item in document["items"]
            if any(_names_a_sighting(reason) for reason in item["evidence"].get("reasons", ()))
        ]  # fmt: skip
        if strict or seen:
            raise FixtureError(
                f"the catalog has {len(strict)} strict items and {len(seen)} with a sighting among their reasons: the fixtures "
                "come only from the public catalog (strict is the hash proxy of the wiki level)"
            )
        self.document = document
        self.version = document.get("version")
        self.data_release = f"data-{self.version}" if isinstance(self.version, str) else None
        self.rules_version = self.rules.version
        self.level = self.rules.get("level.current")
        self.items_by_key = {item["key"]: item for item in document["items"]}
        self.table = browser.items(document, self.rules)
        self.defaults = self.table["defaults"]
        self.records = {browser.record_key(record): record for record in self.table["items"]}
        self.position = {key: number for number, key in enumerate(self.records)}
        self.weapon_pct = self.rules.get("tier.weapon_damage_pct")
        self._spells: dict[int, Any] = {}
        self._buffsets: dict[tuple[tuple[str, ...], int, bool | None], dict[str, BuffSet]] = {}
        self._selection: dict[tuple[str, ...], grid.Selection] = {}
        self._pools: dict[tuple[tuple[str, ...], str, bool], list[dict[str, Any]]] = {}
        self._solve_pools: dict[tuple[tuple[str, ...], str], list[ItemVec]] = {}
        self._vecs: dict[tuple[str, int], ItemVec] = {}
        self._profiles: dict[tuple[Any, ...], Profile] = {}

    def spells(self, level: int) -> Any:
        if level not in self._spells:
            self._spells[level] = load_strict(self.root / "derived" / "client" / f"spells-l{level}.json")
        return self._spells[level]

    def buffsets(self, codes: Sequence[str], level: int, spell_haste: bool | None = None) -> dict[str, BuffSet]:
        """The four buff sets of a trio at a level, written as :func:`trioforge.export.browser.bundle` writes them. ``spell_haste`` None follows the rule ``haste.assume_spell``
        (no spell haste in them while it is false); True gives the sets the haste of the spells, which only the scenarios of the stratum ``spell-haste`` ask for."""
        key = (tuple(codes), level, spell_haste)
        if key not in self._buffsets:
            self._buffsets[key] = buffsets(codes, level, self.spells(level), self.rules, BuffKeys, spell_haste=spell_haste)
            assert tuple(self._buffsets[key]) == BuffKeys
        return self._buffsets[key]

    def selection(self, codes: Sequence[str]) -> grid.Selection:
        key = tuple(codes)
        if key not in self._selection:
            self._selection[key] = grid.select_items(self.document["items"], codes)
        return self._selection[key]

    def pool(self, codes: Sequence[str], evidence: str, *, with_deity: bool = False) -> list[dict[str, Any]]:
        """The catalog items of the solve pool of a trio at an evidence level (``wiki`` or ``strict-proxy``), by key. With
        ``with_deity`` the deity-locked items stand in it too, for a profile that has a deity."""
        key = (tuple(codes), evidence, with_deity)
        if key not in self._pools:
            selection = self.selection(codes)
            items = list(selection.items) if with_deity else grid.pool_dicts(selection, "wiki")
            if evidence == "strict-proxy":
                items = bench.strict_proxy(items)
            elif evidence != "wiki":
                raise FixtureError(f"unknown evidence level {evidence!r} (use wiki or strict-proxy)")
            self._pools[key] = items
        return self._pools[key]

    def vec(self, item: Mapping[str, Any], tier: int) -> ItemVec:
        key = (item["key"], tier)
        if key not in self._vecs:
            self._vecs[key] = at_tier(dict(item), tier, self.rules)
        return self._vecs[key]

    def vecs(self, items: Iterable[Mapping[str, Any]], tier: int) -> list[ItemVec]:
        return [self.vec(item, tier) for item in items]

    def solve_pool(self, codes: Sequence[str], label: str) -> list[ItemVec]:
        """The solve pool of a trio at an evidence level of the bundle (``strict`` or ``wiki``) as item vectors at +0: what
        :func:`trioforge.export.browser.bundle` reads the weapon setups of that level from (the pool of
        :func:`trioforge.precompute.grid.pool_dicts`, no deity-locked item in it)."""
        key = (tuple(codes), label)
        if key not in self._solve_pools:
            self._solve_pools[key] = [at_tier(item, 0, self.rules) for item in grid.pool_dicts(self.selection(codes), label)]
        return self._solve_pools[key]

    def profile(
        self, codes: Sequence[str], level: int, race: str, role: str, buffs: str, *, evidence: str, deity: str | None,
        pool: str | None = None, spell_haste: bool | None = None,
    ) -> Profile:
        """The profile of a scenario (``evidence`` is its label, ``strict`` or ``wiki``). With ``pool`` (an evidence level of
        the bundle) it is made as the precompute makes it, given the solve pool of that level, so that its weapon setups follow
        the pool: this is the profile that ``assemble`` of the bundle gives at that evidence level. Without one there is no pool
        to read and a shield is assumed: the profile that ``assemble`` gives with no evidence level. ``buffs`` may be the key of a twin of a buff set of the bundle
        (``group+haste``): the set with the haste of the spells in it, whatever the rule says."""
        key = (tuple(codes), level, race, role, buffs, evidence, deity, pool, spell_haste)
        if key not in self._profiles:
            twin = buffs.endswith(browser.HASTE_SUFFIX)
            self._profiles[key] = make_profile(
                race, codes, level, role, self.buffsets(codes, level, True if twin else spell_haste)[buffs.removesuffix(browser.HASTE_SUFFIX)], None, self.tables, self.rules,
                evidence=evidence, deity=deity, items=None if pool is None else self.solve_pool(codes, pool),
            )
        return self._profiles[key]

    def records_for(self, keys: Iterable[str]) -> list[dict[str, Any]]:
        """The item-table records of some keys, once each, in the order of the table."""
        wanted = sorted(set(keys), key=self.position.__getitem__)
        return [self.records[key] for key in wanted]

    def check_records(
        self, items: Iterable[ItemVec], records: Mapping[str, Mapping[str, Any]], *, weapon_pct: int | None = None
    ) -> None:
        """Read each record back with the tier rules and require the item the builder was given."""
        defaults = self.defaults
        for item in items:
            record = records.get(item.key)
            if record is None:
                raise FixtureError(f"no record for {item.key}")
            got = at_tier(browser.item_to_catalog(record, defaults), item.tier, self.rules, weapon_pct=weapon_pct)
            if got != item:
                raise FixtureError(f"the record of {item.key} does not read back as the item at +{item.tier}")


# ---- solve records ------------------------------------------------------------------------------------------------------


def result_json(milp: Any, solution: Solution) -> dict[str, Any]:
    """What a solve returned, for the case: the status (always ``optimal``), whether the tie stage decided the kit, the
    assumed haste, the value the model reported, the exact value, the canonical kit, the chosen buffs and the breakdown."""
    if solution.status != "optimal" or solution.breakdown is None or solution.kit is None:
        raise FixtureError(f"the solver ended with status {solution.status!r}, not optimal")
    if solution.tie_stage not in ("applied", "kept-first"):
        raise FixtureError(f"the solve did not run the tie stage (tie_stage is {solution.tie_stage!r})")
    return {
        "status": "optimal", "tie_stage": solution.tie_stage, "haste_assumed": milp.haste_assumed,
        "model_F": solution.model_F, "F": browser.rat(solution.breakdown.F), "kit": kit_json(solution.kit),
        "buffs": list(solution.buffs), "breakdown": breakdown_json(solution.breakdown),
    }  # fmt: skip


def haste_doc(found: HasteSolve) -> dict[str, Any]:
    """How a truthful solve chose its program: the hastes a kit of the scenario can count (rising) and the level whose program the
    kit came from. A kit that counts more than its program assumed is refused: the fixtures hold programs whose model value is the
    kit's own."""
    if found.level != found.haste:
        raise FixtureError(f"the kit counts {found.haste}% but its program assumed {found.level}%")
    return {"levels": list(found.levels), "level": found.level}


def solve_doc(
    label: str, milp: Any, solution: Solution, options: BuildOptions, pool: Sequence[ItemVec], prune_doc: dict[str, Any] | None,
    haste: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A solve of a case: the options and the model are the program's own (the truthful solve's winning level has them set
    to its haste), ``haste`` says which levels the scenario has and which level won (None: one program at a fixed haste)."""
    return {
        "label": label, "options": options_json(options), "pool": idents(pool), "prune": prune_doc, "haste": haste,
        "model": milp_json.to_dict(milp), "result": result_json(milp, solution),
    }  # fmt: skip


def prune_doc(
    items: Sequence[ItemVec], kept: Sequence[ItemVec], tier: int | None, options: BuildOptions, owned: Iterable[str]
) -> dict[str, Any]:
    """The pruning of a pool: the idents that went in, the idents that stayed and what was given to :func:`prune`."""
    return {
        "tier": tier, "options": options_json(options), "owned": sorted(owned), "input": idents(items), "kept": idents(kept),
    }  # fmt: skip


def outcome_tags(kit: Sequence[ItemVec | None], breakdown: fm.Breakdown, tie_stage: str | None) -> list[str]:
    """Tags of what the solved kit turned out to be."""
    tags = [f"tie:{tie_stage}"] if tie_stage else []
    secondary, primary = kit[SECONDARY_INDEX], kit[PRIMARY_INDEX]
    if secondary is not None and secondary.is_shield:
        tags.append("shield-worn")
    if primary is not None and primary.weapon is not None and primary.weapon.two_handed:
        tags.append("two-hander-worn")
    if (
        primary is not None and secondary is not None and primary.weapon is not None and secondary.weapon is not None
    ):
        tags.append("dual-wield-worn")
    sheet = breakdown.totals["sheet"]
    if sheet["X"] > sheet["Y"]:
        tags.append("softcap-binds")
    return tags


# ---- scenarios (matrix and pmb36) ---------------------------------------------------------------------------------------


@dataclass
class Scenario:
    """A scenario ready to prune, build and solve: nothing here has been solved."""

    spec: ScenarioSpec
    profile: Profile
    buffset: BuffSet
    weights: dict[str, Any] | None
    pool: list[ItemVec]
    pool_items: list[dict[str, Any]]
    options: BuildOptions


def make_scenario(inputs: Inputs, spec: ScenarioSpec) -> Scenario:
    """The profile, the buff set and the pool of a scenario spec (see :class:`~trioforge.export.fixture_plan.ScenarioSpec`)."""
    label = "strict" if spec.evidence == "strict-proxy" else "wiki"
    # (the profile is the one the precompute makes for the evidence level, given its solve pool, which is what assemble of the bundle gives at that level; the bow
    # setup is named by the pool alone)
    haste = True if spec.spell_haste else None  # (the stratum spell-haste: the buff sets carry the haste of the spells whatever the rule says)
    profile = inputs.profile(
        spec.trio, spec.level, spec.race, spec.role, spec.buffs, evidence=label, deity=spec.deity, pool=label, spell_haste=haste
    )
    if spec.setup not in profile.setups:
        plays = ", ".join(profile.setups)
        raise FixtureError(f"{spec.id}: the setup {spec.setup} is not one the {spec.role} role plays ({plays})")
    weights = None
    if spec.multipliers or spec.custom or spec.regen_T is not None:
        base = dict(profile.weights)
        reachable = bool(profile.pools["MANA"])
        composed = roles.weights_override(
            base, dict(spec.multipliers), dict(spec.custom), spec.regen_T, mana_reachable=reachable
        )
        weights = {
            "multipliers": dict(spec.multipliers), "custom": dict(spec.custom), "regen_T": spec.regen_T,
            "mana_reachable": reachable, "base": base, "result": composed,
        }  # fmt: skip
        profile = dataclasses.replace(profile, weights=composed)
    items = inputs.pool(spec.trio, spec.evidence, with_deity=spec.deity is not None)
    return Scenario(
        spec, profile, inputs.buffsets(spec.trio, spec.level, haste)[spec.buffs], weights, inputs.vecs(items, spec.tier), items,
        BuildOptions(),
    )


def _case_header(inputs: Inputs, family: str, case_id: str, label: str, tags: Sequence[str], synthetic: bool) -> dict[str, Any]:
    return {
        "format": FORMAT, "kind": "case", "family": family, "id": case_id, "label": label, "tags": sorted(set(tags)),
        "data_release": inputs.data_release, "rules_version": inputs.rules_version, "synthetic": synthetic,
    }  # fmt: skip


def scenario_case(inputs: Inputs, scenario: Scenario) -> dict[str, Any]:
    """Prune, build and solve a scenario and write its case."""
    spec, profile, buffset, options = scenario.spec, scenario.profile, scenario.buffset, scenario.options
    kept = prune(scenario.pool, profile, spec.tier, spec.setup, buffset, options)
    found = solve_scenario(profile, kept, spec.setup, buffset, options)
    milp, solution = found.milp, found.solution
    key_set = {item.key for item in scenario.pool} if spec.prune_check else {item.key for item in kept}
    records = inputs.records_for(key_set)
    by_key = {browser.record_key(record): record for record in records}
    inputs.check_records(scenario.pool if spec.prune_check else kept, by_key)
    pruning = prune_doc(scenario.pool, kept, spec.tier, options, ()) if spec.prune_check else None
    solve = solve_doc("solve", milp, solution, milp.options, kept, pruning, haste_doc(found))
    label = (
        f"{'/'.join(spec.trio)} {spec.race} {spec.role} {spec.setup} +{spec.tier} {spec.buffs} {spec.evidence}"
        f"{f' L{spec.level}' if spec.level != 50 else ''}{f' deity {spec.deity}' if spec.deity else ''}"
    )
    outcome = outcome_tags(solution.kit, solution.breakdown, solution.tie_stage)
    doc = _case_header(inputs, spec.family, spec.id, label, [*spec.tags, *outcome], False)
    doc["inputs"] = {
        "trio": list(spec.trio), "level": spec.level, "race": spec.race, "role": spec.role, "buffs": spec.buffs,
        "evidence": spec.evidence, "deity": spec.deity, "setup": spec.setup, "tier": spec.tier,
        "weapon_pct": inputs.weapon_pct, "profile": profile.to_dict(), "weights": _json_weights(scenario.weights),
        "buffset": buffset_doc(buffset), "note": spec.note,
    }  # fmt: skip
    doc["records"] = records
    doc["solves"] = [solve]
    doc["expected"] = {}
    return doc


def _json_weights(weights: dict[str, Any] | None) -> dict[str, Any] | None:
    if weights is None:
        return None
    return {**weights, "base": dict(weights["base"]), "result": dict(weights["result"])}


# ---- brute-force instances ----------------------------------------------------------------------------------------------


def brute_seed(seed: int, number: int) -> str:
    """The text a brute-force instance is drawn from (``random.Random`` seeds a text the same way on every machine)."""
    return f"{seed}:brute:{number}"


def brute_instance(seed: int, number: int) -> brute.Instance:
    """The instance of a number: a real trio of the menu in turn, optional haste buffs on every eighth."""
    rng = random.Random(brute_seed(seed, number))
    if number >= PROCS_BASE:  # an instance with a table of procs: numbered after the bow ones
        return brute.procs_instance(rng, trio_index=(number - PROCS_BASE) % len(brute.TRIO_MENU))
    if number >= RANGED_BASE:  # a bow instance: numbered after the plain ones, which are drawn as they always were
        n = number - RANGED_BASE
        return brute.ranged_instance(rng, trio_index=n % len(brute.TRIO_MENU), truthful=n % 2 == 1)
    if number % TRUTHFUL_EVERY == TRUTHFUL_EVERY - 1:  # some instances are for the truthful solve (weapons and haste in the pool)
        return brute.truthful_instance(rng, trio_index=number % len(brute.TRIO_MENU))
    return brute.random_instance(rng, trio_index=number % len(brute.TRIO_MENU), haste_buffs=number % 8 == 5)


def brute_case(inputs: Inputs, seed: int, number: int) -> dict[str, Any]:
    """An invented instance, its exact maximum by enumeration and the program and solve (they must agree)."""
    inst = brute_instance(seed, number)
    space = brute.Space(inst)
    best, _, _ = space.best()
    options = BuildOptions(**inst.options_kwargs())
    found = None
    if inst.haste_assumed is None:  # a truthful instance: the weapon term is paid the haste each kit counts
        found = solve_scenario(inst.profile, inst.items, inst.setup, inst.buffset, options)
        milp, solution, options = found.milp, found.solution, found.milp.options
    else:
        milp = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, options)
        solution = solve_canonical(milp)
    value = solution.breakdown.F if solution.breakdown is not None else None
    if value is None or abs(float(value - best)) > REL * max(1.0, abs(float(best))):
        raise FixtureError(f"brute-{number:03d}: the solver's value {value} is not the brute force's {best}")
    records = {item.key: brute.item_record(item) for item in inst.items}
    inputs.check_records(inst.items, records)
    case_id = f"brute-{number:03d}"
    tags = [f"setup:{inst.setup}", f"any-rule:{inst.any_rule}", f"trio:{'-'.join(inst.trio)}", f"level:{inst.level}"]
    if found is not None:
        tags.append("truthful-haste")
    if inst.buffset is not None:
        tags.append("buffs")
    if "synthetic-pools" in inst.label:
        tags.append("synthetic-pools")
    if inst.procs is not None:
        tags.append("procs")
    doc = _case_header(inputs, "brute", case_id, inst.label, tags, True)
    doc["inputs"] = {
        "trio": list(inst.trio), "level": inst.level, "race": inst.race, "role": "melee", "buffs": None,
        "evidence": "synthetic", "deity": None, "setup": inst.setup, "tier": 0, "weapon_pct": inputs.weapon_pct,
        "profile": inst.profile.to_dict(), "weights": None, "buffset": buffset_doc(inst.buffset),
        "seed": brute_seed(seed, number), "note": "an invented instance: its items are not in the catalog",
    }  # fmt: skip
    if inst.procs is not None:
        doc["inputs"]["procs"] = procs_module.to_doc(inst.procs)  # (the table the builder, the pruning and the evaluator were given: the browser reads the same)
    doc["records"] = [records[key] for key in sorted(records)]
    doc["solves"] = [solve_doc("solve", milp, solution, options, inst.items, None, None if found is None else haste_doc(found))]
    doc["expected"] = {"brute_F": browser.rat(best), "kits": int(len(space.kits)), "buff_sets": len(space.buff_sets)}
    return doc


# ---- upgrade sessions -----------------------------------------------------------------------------------------------------


@dataclass
class Session:
    """The inputs of an Upgrade case: everything :func:`upgrade_case` needs besides the numbers it makes."""

    case_id: str
    label: str
    tags: list[str]
    synthetic: bool
    header: dict[str, Any]  # the fields of ``inputs`` that describe the scenario
    profile: Profile
    buffset: BuffSet | None
    setup: str
    owned: dict[ItemVec, int]
    candidates: list[ItemVec]
    records: dict[str, dict[str, Any]]
    tier_mode: dict[str, Any] | None
    steps: int
    note: str
    options: BuildOptions = dataclasses.field(default_factory=BuildOptions)


class _Recorder:
    """Records what :mod:`trioforge.upgrade` hands to the pruning and to the truthful solve, so a case holds exactly what the
    reference did without a second copy of its loop. A ``"build"`` event is a solve: its arguments are those of
    :func:`~trioforge.solver.haste.solve_scenario` and its result the :class:`~trioforge.solver.haste.HasteSolve`."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any], Any]] = []
        self.solutions: list[Solution] = []

    @contextlib.contextmanager
    def active(self) -> Iterator[None]:
        real_solve, real_prune = upgrade.solve_scenario, upgrade.prune
        solve_sig, prune_sig = inspect.signature(real_solve), inspect.signature(real_prune)

        def solved(*args: Any, **kwargs: Any) -> HasteSolve:
            found = real_solve(*args, **kwargs)
            self.events.append(("build", dict(solve_sig.bind(*args, **kwargs).arguments), found))
            self.solutions.append(found.solution)
            return found

        def pruned(*args: Any, **kwargs: Any) -> Any:
            kept = real_prune(*args, **kwargs)
            self.events.append(("prune", dict(prune_sig.bind(*args, **kwargs).arguments), kept))
            return kept

        upgrade.solve_scenario, upgrade.prune = solved, pruned
        try:
            yield
        finally:
            upgrade.solve_scenario, upgrade.prune = real_solve, real_prune

    def take(self) -> list[tuple[str, dict[str, Any], Any]]:
        events, self.events = self.events, []
        return events

    def take_solutions(self) -> list[Solution]:
        solutions, self.solutions = self.solutions, []
        return solutions


def _owned_ledger(owned: Mapping[ItemVec, int]) -> list[list[Any]]:
    counted = ((ident(item.key, item.tier), count) for item, count in owned.items() if count)
    return [[name, count] for name, count in sorted(counted)]


def make_session(inputs: Inputs, spec: UpgradeSpec, seed: int) -> Session:
    """The owned set, the candidates and the profile of an Upgrade spec. The seed picks the owned items."""
    rng = random.Random(f"{seed}:upgrade:{spec.number}")
    label = "strict" if spec.evidence == "strict-proxy" else "wiki"
    profile = inputs.profile(spec.trio, inputs.level, spec.race, spec.role, spec.buffs, evidence=label, deity=spec.deity)
    if spec.setup not in profile.setups:
        raise FixtureError(f"{spec.id}: the setup {spec.setup} is not one the {spec.role} role plays")
    pool = inputs.pool(spec.trio, spec.evidence)
    owned: dict[ItemVec, int] = {}
    for record in rng.sample(pool, spec.owned):
        tier = rng.choice(OWNED_TIERS)
        owned[inputs.vec(record, tier)] = rng.choice(OWNED_COUNTS)
    if spec.locked:  # deity-locked items the visitor owns: the profile's deity admits them, or nothing does
        locked_pool = [item for item in inputs.pool(spec.trio, spec.evidence, with_deity=True) if item["deity"] is not None]
        mine = [item for item in locked_pool if spec.deity is not None and spec.deity in item["deity"]]
        others = [item for item in locked_pool if item not in mine]
        if spec.deity is not None:
            picks = rng.sample(mine, min(spec.locked, len(mine)))
            picks += rng.sample(others, 1) if others else []  # and one that the deity does not admit
        else:
            picks = rng.sample(others, spec.locked)
        for record in picks:
            owned[inputs.vec(record, 4)] = 1
    owned_keys = {item.key for item in owned}
    offered = pool if spec.focus == "all" else [item for item in pool if item["key"] in owned_keys]
    candidates = upgrade.scored_candidates(offered, spec.mode, inputs.rules, spec.D, spec.N)
    needed = owned_keys | {item.key for item in candidates}
    records = {key: inputs.records[key] for key in needed}
    inputs.check_records([*owned, *candidates], records)
    header = {
        "trio": list(spec.trio), "level": inputs.level, "race": spec.race, "role": spec.role, "buffs": spec.buffs,
        "evidence": spec.evidence, "deity": spec.deity, "setup": spec.setup,
    }  # fmt: skip
    mode = {"mode": spec.mode, "D": spec.D, "N": spec.N}
    text = f"{'/'.join(spec.trio)} {spec.race} {spec.role} {spec.setup} {spec.buffs} {spec.evidence}, {spec.mode}"
    return Session(
        spec.id, text, list(spec.tags), False, header, profile, inputs.buffsets(spec.trio, inputs.level)[spec.buffs], spec.setup,
        owned, candidates, records, mode, spec.steps, spec.note,
    )


Event = tuple[str, dict[str, Any], Any]  # what the recorder keeps of a call: "build" or "prune", its arguments, its result


def _best_set_events(events: Sequence[Event]) -> tuple[Event, Event | None, Event | None]:
    """The events of one ``best_sets`` call: the build of Equip now, the pruning of the set and the build of the set. The pruning
    is the last one between the two builds (a pruning before Equip now's own build is Equip now's, and one after the set's build
    is not the set's); it is None when the set's pool was not pruned, and the last two are None when the candidates offered
    nothing to acquire and only Equip now was built."""
    builds = [at for at, event in enumerate(events) if event[0] == "build"]
    if not 1 <= len(builds) <= 2:
        raise FixtureError(f"the best set built {len(builds)} programs, not one or two")
    if len(builds) == 1:
        return events[builds[0]], None, None
    between = events[builds[0] + 1 : builds[1]]
    return events[builds[0]], next((event for event in reversed(between) if event[0] == "prune"), None), events[builds[1]]


def _best_set(
    session: Session, k: int, equip_milp: Any, recorder: _Recorder
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The best set of ``k`` additions the reference makes for a session: the entry of ``expected.best_sets`` and the solve of
    the program it built (None when the candidates offered nothing to acquire, and so no program was built). The reference
    works out Equip now again for the gain; that program is checked against the one the case holds."""
    with recorder.active():
        best = upgrade.best_sets(
            session.profile, session.owned, session.candidates, k, session.setup, session.buffset, session.options
        )
    events = recorder.take()
    recorder.take_solutions()
    equip_event, prune_event, build_event = _best_set_events(events)
    first_diff = milp_json.compare(milp_json.to_dict(equip_milp), milp_json.to_dict(equip_event[2].milp))
    if first_diff:
        raise FixtureError(f"Equip now inside the best {k} set is not Equip now: {first_diff[0]}")
    entry = {
        "k": k, "acquired": [ident(a.item.key, a.item.tier) for a in best.acquisitions], "F": browser.rat(best.F),
        "gain": browser.rat(best.gain), "haste_assumed": best.haste_assumed,
    }  # fmt: skip
    if build_event is None:
        return entry, None
    pruning = None
    if prune_event is not None:
        _, prune_args, kept = prune_event
        pruning = prune_doc(prune_args["items"], kept, prune_args["tier"], prune_args["options"], prune_args["owned"])
    _, build_args, found = build_event
    return entry, solve_doc(f"best-{k}", found.milp, found.solution, found.milp.options, build_args["items"], pruning, haste_doc(found))


def upgrade_case(inputs: Inputs, session: Session) -> dict[str, Any]:
    """Equip now, the first steps of the farm path, the best 2 and 3 sets and Every slot for a session, each with the program
    the reference built."""
    profile, buffset, setup = session.profile, session.buffset, session.setup
    base = session.options
    recorder = _Recorder()
    with recorder.active():
        equip = upgrade.equip_now(profile, session.owned, setup, buffset, base)
    (_, equip_args, equip_found), *rest = recorder.take()
    if rest:
        raise FixtureError("Equip now built more than one program")
    equip_milp = equip_found.milp
    with recorder.active():
        steps = upgrade.farm_path(profile, session.owned, session.candidates, setup, buffset, session.steps, base)
    events = recorder.take()
    builds = [event for event in events if event[0] == "build"]
    if len(builds) < 1 + len(steps):
        raise FixtureError(f"the farm path made {len(steps)} steps but built {len(builds)} programs")
    first_diff = milp_json.compare(milp_json.to_dict(equip_milp), milp_json.to_dict(builds[0][2].milp))
    if first_diff:
        raise FixtureError(f"Equip now inside the farm path is not Equip now: {first_diff[0]}")

    solves = [solve_doc("equip-now", equip_milp, equip, equip_milp.options, equip_args["items"], None, haste_doc(equip_found))]
    # the events are: the build of Equip now, then for each step the pruning and the build
    position = 1
    step_docs = []
    for number, step in enumerate(steps, start=1):
        prune_event = None
        while events[position][0] != "build":
            if events[position][0] == "prune":
                prune_event = events[position]
            position += 1
        _, build_args, found = events[position]
        position += 1
        while position < len(events) and events[position][0] == "build":  # (R14: a step whose first equal addition is not the one the solve gave has a second solve, of that addition alone: the step is made from that one)
            _, build_args, found = events[position]
            position += 1
        milp = found.milp
        pruning = None
        if prune_event is not None:
            _, prune_args, kept = prune_event
            pruning = prune_doc(prune_args["items"], kept, prune_args["tier"], prune_args["options"], prune_args["owned"])
        solves.append(solve_doc(f"step-{number}", milp, step.solution, milp.options, build_args["items"], pruning, haste_doc(found)))
        record = session.records[step.item.key]
        step_docs.append({
            "index": step.index, "item": ident(step.item.key, step.item.tier), "kind": step.kind,
            "source_tier": step.source_tier, "F": browser.rat(step.F), "gain": browser.rat(step.gain),
            "haste_assumed": step.haste_assumed, "owned": [[name, count] for name, count in step.owned],
            "cost": _cost(record, step, session), "solve": number,
        })  # fmt: skip
    best_entries = []
    for k in BEST_SET_SIZES:
        entry, program = _best_set(session, k, equip_milp, recorder)
        best_entries.append(entry)
        if program is not None:
            solves.append(program)
    every = _every_slot(session, equip, base)
    keys = {item.key for item in session.owned} | {item.key for item in session.candidates}
    # the records in the order of the item table; the keys of an invented session are not in it, and go in key order
    records = [session.records[key] for key in sorted(keys, key=lambda k: (inputs.position.get(k, len(inputs.position)), k))]
    doc = _case_header(
        inputs, "upgrade", session.case_id, session.label,
        [*session.tags, *(f"step:{step.kind}" for step in steps), *outcome_tags(equip.kit, equip.breakdown, equip.tie_stage)],
        session.synthetic,
    )  # fmt: skip
    doc["inputs"] = {
        **session.header, "tier": None, "weapon_pct": inputs.weapon_pct, "profile": profile.to_dict(), "weights": None,
        "buffset": buffset_doc(buffset), "owned": _owned_ledger(session.owned),
        "candidates": sorted(idents(session.candidates)), "tier_mode": session.tier_mode, "steps": session.steps,
        "note": session.note,
    }  # fmt: skip
    doc["records"] = records
    doc["solves"] = solves
    doc["expected"] = {
        "equip_now": 0, "steps": step_docs,
        "stopped": "limit" if len(steps) == session.steps else "no-gain", "best_sets": best_entries, "every_slot": every,
    }  # fmt: skip
    return doc


def _cost(record: Mapping[str, Any], step: upgrade.Step, session: Session) -> dict[str, Any] | None:
    """What it costs to bring the step's item to its tier: from the owned copy it is made from (an upgrade), else from the
    tier it arrives at; null when the tier mode scores it below the tier it arrives at."""
    if session.tier_mode is None:
        return None
    D = session.tier_mode["D"]
    start = step.source_tier if step.kind == "upgrade" else arrival_tier(record, D)
    if start > step.item.tier:
        return None
    return {"from": start, "to": step.item.tier, "D": D, **cost_to_reach(record, start, step.item.tier, D)}


def _every_slot(session: Session, equip: Solution, options: BuildOptions) -> list[dict[str, Any]]:
    """Every slot from Equip now's kit: the candidates of the tier mode (no count) and the owned items, an owned item that is not a
    candidate only while the visitor owns more copies of it than the kit wears in the other places (see ``upgrade.every_slot``)."""
    rows = upgrade.every_slot(
        session.profile, equip, session.candidates, session.setup, session.buffset, options, limit=3, owned=session.owned
    )
    return [
        {
            "place": row.place, "index": row.index,
            "current": None if row.current is None else ident(row.current.key, row.current.tier),
            "swaps": [{"item": ident(swap.item.key, swap.item.tier), "delta": browser.rat(swap.delta)} for swap in row.swaps],
        }
        for row in rows
    ]  # fmt: skip


# ---- hand-built every-slot cases ------------------------------------------------------------------------------------------


def _invented(*items: ItemVec) -> dict[str, dict[str, Any]]:
    return {item.key: brute.item_record(item) for item in items}


def _slot_session(
    case_id: str, label: str, tags: Sequence[str], profile: Profile, setup: str, owned: dict[ItemVec, int],
    candidates: list[ItemVec], steps: int,
) -> Session:
    records = _invented(*owned, *candidates)
    header = {
        "trio": list(profile.trio), "level": profile.level, "race": profile.race, "role": "melee", "buffs": None,
        "evidence": "synthetic", "deity": None, "setup": setup,
    }  # fmt: skip
    return Session(
        case_id, label, ["synthetic-slots", *tags], True, header, profile, None, setup, owned, candidates, records, None, steps,
        "an invented session that pins how Every slot values and offers a swap (the Any places take only items that list them)",
        BuildOptions(any_rule="explicit"),
    )


def slot_cases(inputs: Inputs) -> list[dict[str, Any]]:
    """Three small invented sessions for Every slot: a swap past the armor class softcap (its exact value is not the linear
    estimate), a two-hander that is not offered over a worn off hand, and the same in the two-hand setup."""
    make = brute.make_item
    trio = ("PAL", "MNK", "BER")
    softcap = brute.make_profile(trio, "OGR", {"AC": 6}, softcap=(60, 0.25), setup="stick")
    chest = make("it-chest", {"CHEST"}, stats={"AC": 30})
    helm = make("it-helm", {"HEAD"}, stats={"AC": 20})
    chest_plus = make("it-chest-plus", {"CHEST"}, stats={"AC": 40})
    cloak = make("it-cloak", {"BACK"}, stats={"AC": 4})
    cases = [
        _slot_session(
            "upgrade-slots-softcap", "a swap past the armor class softcap", ["swap:softcap"], softcap, "stick",
            {chest: 1, helm: 1}, [chest_plus, cloak], 2,
        )
    ]
    hp = brute.make_profile(trio, "OGR", {"HP": 1}, setup="stick")
    sword = make("it-sword", {"PRIMARY"}, stats={"HP": 10}, weapon=_one_hand())
    guard = make("it-guard", {"SECONDARY"}, stats={"AC": 5, "HP": 4}, shield=True)
    axe = make("it-axe", {"PRIMARY"}, stats={"HP": 90}, weapon=_two_hand())
    cases.append(
        _slot_session(
            "upgrade-slots-twohand", "a two-hander is not offered over a worn off hand, though a farm step may take it",
            ["swap:two-hander"], hp, "stick", {sword: 1, guard: 1}, [axe], 2,
        )
    )
    hp2 = brute.make_profile(trio, "OGR", {"HP": 1}, setup="2h")
    axe_two = make("it-axe-two", {"PRIMARY"}, stats={"HP": 95}, weapon=_two_hand())
    cases.append(
        _slot_session(
            "upgrade-slots-twohand-2h", "the two-hand setup offers only another two-hander", ["swap:two-hander"], hp2, "2h",
            {axe: 1}, [sword, guard, axe_two], 2,
        )
    )
    for session in cases:
        inputs.check_records([*session.owned, *session.candidates], session.records)
    return [upgrade_case(inputs, session) for session in cases]


def _one_hand() -> Any:
    from trioforge.model.items import WeaponVec

    return WeaponVec("1H Slashing", 20, 30, None, False)


def _two_hand() -> Any:
    from trioforge.model.items import WeaponVec

    return WeaponVec("2H Slashing", 40, 60, None, True)


def eval_totals_for(buffset: BuffSet | None, chosen: Iterable[int]) -> dict[str, Any] | None:
    """The buff totals ``evaluate`` reads for a buff set and a choice among its optional buffs (None: the profile's own)."""
    return None if buffset is None else eval_buff_totals(buffset.totals(tuple(chosen)))
