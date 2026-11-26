"""The robustness seals and the flip notes of a precompute run: the module :mod:`trioforge.solver.robust` put to work.

A page answers with one kit, and the kit rests on judgment weights and on rules that are still open. Two things say how much
the answer depends on them, and both are made here from the solver's robustness variants
(:func:`trioforge.solver.robust.describe_perturbations`), solved exactly and without a time limit:

* the **seal** of a slot (``robust.json``): for the default race, each role and the tiers +4 and +10, whether the item worn in
  a slot is the same under every variant. :func:`seal_hook` is the hook of :func:`trioforge.precompute.run`: it takes a
  :class:`trioforge.precompute.grid.RobustScenario`, solves the scenario and its variants with the module, and answers
  ``{place: "robust" or the label of the variant that changed the pick}`` for the 22 places of a kit. The module works in the 18
  slot groups (a pair such as the ears is one slot, its two items taken as a set); both places of a pair get their group's
  label (:func:`place_labels`). The base of the module's solve must wear the very items the run's kit wears, or the labels
  would describe another kit: a difference stops the run;
* the **flip notes** (``defaults.json``): the page states a best race as an answer, so it also says when an open rule decides it.
  For every race that can be created, the default view (the default role, tier, evidence level and own buffs, over the role's
  weapon setups) is solved again under each variant that is a *rule* (a weight is a judgment call, not a test that can settle
  it). A race that has no such variant keeps its value. Where another race comes out on top, the note names it, the
  alternative and the in-game test: "Iksar, if Iksar AC stacks on top of the cap" (:func:`flip_notes`; a rule that is settled names no test).

Every solve is called with the model alone: no time limit, no HiGHS option.
"""

from __future__ import annotations

import re
import types
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any, NamedTuple

from trioforge.data.races import RACE_NAMES
from trioforge.model.items import ItemVec, at_tier
from trioforge.precompute import grid, shards
from trioforge.solver import solve as solver_solve
from trioforge.solver.haste import solve_scenario
from trioforge.solver.prune import prune

__all__ = [
    "FLIP_TOLERANCE",
    "PHRASES",
    "SealError",
    "Variant",
    "flip_notes",
    "flip_variants",
    "place_labels",
    "seal_hook",
    "solver_scenario",
]

#: how a flip is worded, by the rule it is about (an unknown rule is named by the label of its variant)
PHRASES = {
    "race.iksar_ac_placement": "Iksar AC stacks on top of the cap",
    "monk.bonus_placement": "the Monk worn-weight bonus counts on top of the AC cap",
    "monk.weight_curve": "the Monk worn-weight curve is the other one",
    "mana.wis_bands": "mana from WIS follows the other bands",  # (settled today and listing no alternative; a rules file that lists one gets the variant again, and this is its wording)
    "tier.weapon_damage_pct": "weapon damage grows at the other rate a tier",
}
FLIP_TOLERANCE = 1e-9  # relative: another race is on top only if it is worth more than this above the default race


class SealError(RuntimeError):
    """A seal or a flip check cannot be given (a solve that is not optimal, a base that is not the kit)."""


# ---- the seals -------------------------------------------------------------------------------------------------------


def place_labels(groups: Mapping[str, str]) -> dict[str, str]:
    """The label of each of the 22 places from the label of each slot group: a pair's places share its group's label.

    ``KeyError`` for a group that has no label."""
    return {place: groups[re.sub(r"[0-9]+$", "", place)] for place in shards.PLACES}


def solver_scenario(scenario: grid.RobustScenario) -> Any:
    """The scenario in the form the robustness module wants: the profile, the rules, the pool as a function of the item options
    (the module rebuilds the items for the variant that changes the weapon rate) and the options of the run's models."""
    from trioforge.solver import robust

    return robust.RobustScenario(
        profile=scenario.profile,
        rules=scenario.rules,
        pool=robust.catalog_pool(scenario.pool_items, scenario.tier, scenario.rules),
        setup=scenario.setup,
        tier=scenario.tier,
        buffset=scenario.buffset,
        options=scenario.options if scenario.options is not None else grid.BUILD_OPTIONS,
    )


def seal_hook(scenario: grid.RobustScenario) -> dict[str, str]:
    """The default robustness hook of a run (see the module docstring): ``{place: "robust" or a label}`` for the 22 places."""
    from trioforge.solver import robust

    report = robust.robustness_report(solver_scenario(scenario))
    worn = robust.picks(types.SimpleNamespace(kit=scenario.kit))
    base = {group: tuple(keys) for group, keys in report.picks.items()}
    differ = [group for group in worn if worn[group] != base.get(group)]
    if differ:
        raise SealError(
            f"the base of the robustness solve is not the solved kit; they differ in {', '.join(differ)} "
            f"(kit {', '.join('/'.join(worn[g]) or 'empty' for g in differ)}, base {', '.join('/'.join(base.get(g, ())) or 'empty' for g in differ)})"
        )
    return place_labels(report.labels())


# ---- the flip notes ----------------------------------------------------------------------------------------------------


class Variant(NamedTuple):
    """One rule alternative and the value of the default view under it, for each race that has the variant."""

    label: str
    rule: str
    test: str | None
    values: Mapping[str, float]


def flip_variants(
    ctx: grid.Context, *, role: str, tier: int, evidence: str, setups: Sequence[str], races: Sequence[str],
    solve: Callable[..., Any] | None = None,
) -> list[Variant]:
    """The rule variants of the default view and the best value (over the role's ``setups``) of each race that has them.

    A variant is listed only for the races whose profile it changes
    (:func:`trioforge.solver.robust.describe_perturbations`); the variants come in the order of the first race that has them.
    ``solve`` is the solver (the plain one by default: only the value is wanted, and the value of the tie stage is the same)."""
    from trioforge.solver import robust

    solve = solve or solver_solve.solve
    buffset = ctx.buffsets["own"]
    dicts = ctx.pool_items(evidence)
    pools: dict[tuple, list[ItemVec]] = {}

    def pool(options: Mapping[str, Any]) -> list[ItemVec]:
        key = tuple(sorted(options.items()))
        if key not in pools:
            pools[key] = [at_tier(item, tier, ctx.rules, **options) for item in dicts] if options else ctx.pool(evidence, tier)
        return pools[key]

    found: dict[tuple[str, str], dict[str, Any]] = {}
    for race in races:
        profile = ctx.profile(race, role, "own", evidence)
        for variant in robust.describe_perturbations(profile, ctx.rules):
            if variant.kind != "rule":
                continue
            best: float | None = None
            for setup in setups:
                items = prune(pool(variant.item_options), variant.profile, tier, setup, buffset, ctx.options)
                solution = solve_scenario(variant.profile, items, setup, buffset, ctx.options, solver=solve).solution
                if solution.status != "optimal" or solution.F is None:
                    raise SealError(
                        f"the solve of {RACE_NAMES.get(race, race)} under '{variant.label}' ended {solution.status}, not optimal"
                    )
                best = solution.F if best is None else max(best, solution.F)
            entry = found.setdefault((variant.rule, variant.label), {"test": variant.test, "values": {}})
            entry["values"][race] = best
    return [Variant(label, rule, entry["test"], entry["values"]) for (rule, label), entry in found.items()]


def flip_notes(
    variants: Sequence[Variant], base: Mapping[str, float], default: str, legal: Collection[str],
    order: Sequence[str], close_pct: Any,
) -> list[str]:
    """The notes of the variants that put another race on top, in the order of the variants, each text once.

    ``base`` is the value of each race in the default view, ``default`` the race the page names, ``legal`` the races that can be
    created, ``order`` the display order (it breaks a tie, as for the default race) and ``close_pct`` the rule ``defaults.race_close_pct`` that the pick of the race takes (it
    decides no winner here, and no copy of its value lives in this module). Under a variant a race has the value the
    variant gives it, or its base value if the variant does not touch it. A race that cannot be created never wins, and another
    race is on top only if it is worth more than the default race beyond a float's noise."""
    notes: list[str] = []
    for variant in variants:
        values = {race: variant.values.get(race, value) for race, value in base.items()}
        choice = shards.default_race(values, legal, order, close_pct)
        if choice is None or choice["race"] == default or default not in values:
            continue
        winner = choice["race"]
        if values[winner] <= values[default] + FLIP_TOLERANCE * max(1.0, abs(values[default])):
            continue
        what = PHRASES.get(variant.rule, variant.label)
        note = f"{RACE_NAMES.get(winner, winner)}, if {what}" + (f" (test {variant.test})" if variant.test else "")
        if note not in notes:
            notes.append(note)
    return notes
