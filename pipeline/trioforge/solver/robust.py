"""Robustness perturbations: which picks survive a change of a judgment constant or of an open rule.

A page answers with one kit, and the kit rests on weights that are judgment calls and on rules that are still open
(``status: open`` in ``rules/rules.json``, each with the in-game test that will settle it). The robustness seal
re-solves the scenario under a fixed list of variants and tells, for every slot, whether the pick holds.

The variants (:func:`perturbations`)
====================================

* **Weights.** Each key weight group (``trioforge.model.roles.WEIGHT_GROUPS``) at x0.5 and x2, in this order: ``AC``;
  ``MANA``; ``ATK+HASTE`` (``ATK``, ``HASTE`` and ``DMG``, which the rule ``weapons.damage_weight`` defines as a
  multiple of the ATK weight); ``SV`` (the five schools); ``regen`` (``HPREG``, ``MANAREG``, ``ENDREG``). Labels read
  ``"AC x0.5"``, ``"ATK+HASTE x2"`` ... These are the two slider positions of the site that change a weight, and
  :func:`trioforge.model.roles.weights_override` with one group at x0.5 or x2 gives exactly the weights of the variant.
* **Open rules.** The alternative that the rules file lists for each of them, as it lists it:

  ========================================  ===================================  ======================
  label                                     what changes                         rule, test
  ========================================  ===================================  ======================
  ``WIS band 0.654``                        ``Profile.bands`` (WIS and INT)      ``mana.wis_bands``, B4
  ``Monk curve full until 34``              ``Profile.monk``                     ``monk.weight_curve``, B9
  ``Monk placement inside``                 ``Profile.placement["monk"]``        ``monk.bonus_placement``, B9
  ``Iksar placement inside``                ``Profile.placement["iksar"]``       ``race.iksar_ac_placement``, B17
  ``Weapon damage +10%``                    the items (``at_tier(weapon_pct=)``) ``tier.weapon_damage_pct``, B5
  ========================================  ===================================  ======================

  The numbers in the labels are the alternative's own. The Iksar rule lists no alternative of its own; it has the same
  two readings as the Monk bonus, so it takes the Monk rule's alternative placement unless the rules file gives it one.
  The weapon rate changes the item views, not the profile, so its profile is the base profile and its
  :attr:`Perturbation.item_options` carry ``{"weapon_pct": 10}``.

A variant is listed only if it can change the answer: a weight group needs a weight above zero (the mana group also a
mana pool), the band needs a mana pool with a mana weight, the Monk variants a Monk and an armor class weight, the Iksar
variant an Iksar and an armor class weight, the weapon variant a damage weight and a setup that scores damage (not the
stick). A variant that the profile already is at is left out.

The seal (:func:`robustness`)
=============================

``robustness(scenario)`` solves the base scenario and every variant with ``solve_canonical`` and compares the items worn
in each slot group (a pair such as the ears is one slot: its two items as a set). A slot that no variant changes is
``"robust"``; any other reads as the label of a variant that changed it. When several did, a rule beats a weight
(only a rule has a test that can settle it), and within each kind the variant order above decides. Every solve must end
optimal: a time limit or an infeasible model raises :class:`RobustnessError`, because a guess would show as "robust".
:func:`robustness_report` returns the whole picture (every variant's solution and every label that flipped each slot).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from trioforge.model.buffs import BuffSet
from trioforge.model.items import SLOT_GROUPS, SLOT_INSTANCES, ItemVec, at_tier
from trioforge.model.profile import Profile
from trioforge.model.roles import MULTIPLIERS, WEIGHT_GROUPS
from trioforge.solver.model import BuildOptions, build_milp
from trioforge.solver.prune import prune
from trioforge.solver.solve import Solution, solve_canonical

__all__ = [
    "FACTORS",
    "INSIDE_PLACEMENT",
    "ROBUST",
    "TOP_PLACEMENT",
    "WEIGHT_GROUPS",
    "Perturbation",
    "RobustReport",
    "RobustScenario",
    "RobustnessError",
    "catalog_pool",
    "describe_perturbations",
    "perturbations",
    "picks",
    "robustness",
    "robustness_report",
]

ROBUST = "robust"
#: the slider positions that change a weight: the discrete multipliers of the site's reweight sliders without x1
FACTORS = tuple(position for position in MULTIPLIERS if position != 1)
# WEIGHT_GROUPS, the weight groups in the order of the variants, is defined once, in trioforge.model.roles, where the
# composed weight override that the site's sliders use lives too; it is re-exported here.
#: the texts of the two placements in ``monk.bonus_placement`` (the ones ``make_profile`` reads)
TOP_PLACEMENT = "on top of the capped sheet AC"
INSIDE_PLACEMENT = "inside X before the cap"
_PLACEMENTS = {TOP_PLACEMENT: "top", INSIDE_PLACEMENT: "inside"}
GROUP_NAMES = tuple(name for name, _ in SLOT_GROUPS)


class RobustnessError(RuntimeError):
    """A solve of the robustness run did not end optimal, so the seal cannot be given."""


@dataclass(frozen=True)
class Perturbation:
    """One variant of a scenario.

    ``kind`` is ``"weight"`` or ``"rule"``. ``profile`` is the variant's profile (the base profile for the weapon rate).
    ``item_options`` are keyword arguments for :func:`trioforge.model.items.at_tier` (``{"weapon_pct": 10}`` or empty).
    ``rule`` is the id of the rules-file rule that is switched (None for a weight) and ``test`` the in-game test that
    settles it (None for a weight).
    """

    label: str
    kind: str
    profile: Profile
    item_options: Mapping[str, Any]
    rule: str | None
    test: str | None


# ---- the list of variants ---------------------------------------------------------------------------------------


def _placement(text: Any, rule: str) -> str:
    for prefix, place in _PLACEMENTS.items():
        if isinstance(text, str) and text.startswith(prefix):
            return place
    raise ValueError(f"an alternative of {rule} reads {text!r}; the model has only the placements {list(_PLACEMENTS)}")


def _present(weights: Mapping[str, Any], keys: Sequence[str]) -> list[str]:
    """The keys of a weight group that the profile weighs (they exist in its weights)."""
    return [key for key in keys if key in weights]


def _band_label(value: Mapping[str, Any]) -> str:
    """``WIS band 0.654``: the slope of the band that starts at 200 (else the last slope above zero)."""
    breaks, slopes = list(value["breaks"]), list(value["slopes"])
    if 200 in breaks:
        slope = slopes[breaks.index(200) + 1]
    else:
        slope = next((s for s in reversed(slopes) if s), slopes[-1])
    return f"WIS band {slope:g}"


def describe_perturbations(profile: Profile, rules: Any, *, setup: str | None = None) -> list[Perturbation]:
    """The variants of ``profile`` (see the module docstring), as :class:`Perturbation` records.

    ``rules`` is the rules object whose alternatives are tried (:meth:`trioforge.rules.Rules.alternatives`). ``setup``
    is the scenario's weapon setup: ``"stick"`` leaves out the weapon variant (it scores no damage); None means
    unknown, and the weapon variant is then listed if any of the profile's setups scores damage.
    """
    weights = profile.weights
    out: list[Perturbation] = []

    for group, keys in WEIGHT_GROUPS.items():
        present = _present(weights, keys)
        if not any(weights[key] > 0 for key in present) or (group == "MANA" and not profile.pools["MANA"]):
            continue
        for factor in FACTORS:
            scaled = {key: (value * factor if key in present else value) for key, value in weights.items()}
            variant = dataclasses.replace(profile, weights=scaled)
            out.append(Perturbation(f"{group} x{factor:g}", "weight", variant, {}, None, None))

    def add(label: str, variant: Profile, rule: str, item_options: Mapping[str, Any] | None = None) -> None:
        if variant != profile or item_options:
            out.append(Perturbation(label, "rule", variant, dict(item_options or {}), rule, rules.settled_by(rule)))

    armor = weights.get("AC", 0) > 0
    if profile.pools["MANA"] and weights.get("MANA", 0) > 0:
        for alternative in rules.alternatives("mana.wis_bands"):
            value = alternative["value"]
            add(_band_label(value), dataclasses.replace(profile, bands=value), "mana.wis_bands")
    if profile.monk is not None and armor:
        for alternative in rules.alternatives("monk.weight_curve"):
            value = alternative["value"]
            until = value.get("full_until_stones")
            label = "Monk curve alternative" if until is None else f"Monk curve full until {until}"
            add(label, dataclasses.replace(profile, monk={**profile.monk, **value}), "monk.weight_curve")
        for alternative in rules.alternatives("monk.bonus_placement"):
            place = _placement(alternative["value"], "monk.bonus_placement")
            add(
                f"Monk placement {place}",
                dataclasses.replace(profile, placement={**profile.placement, "monk": place}),
                "monk.bonus_placement",
            )
    if profile.iksar_ac and armor:
        source = "race.iksar_ac_placement" if rules.alternatives("race.iksar_ac_placement") else "monk.bonus_placement"
        for alternative in rules.alternatives(source):
            place = _placement(alternative["value"], source)
            add(
                f"Iksar placement {place}",
                dataclasses.replace(profile, placement={**profile.placement, "iksar": place}),
                "race.iksar_ac_placement",
            )
    scores_damage = any(s != "stick" for s in profile.setups) if setup is None else setup != "stick"
    if weights.get("DMG", 0) > 0 and scores_damage:
        current = rules.get("tier.weapon_damage_pct", profile.level)
        for alternative in rules.alternatives("tier.weapon_damage_pct"):
            percent = alternative["value"]
            if percent != current:
                add(f"Weapon damage +{percent}%", profile, "tier.weapon_damage_pct", {"weapon_pct": percent})
    return out


def perturbations(profile: Profile, rules: Any) -> list[tuple[str, Profile]]:
    """The variants of ``profile`` as ``(label, profile)`` pairs, in their fixed order. :func:`describe_perturbations`
    gives the records, which also say what a variant does to the items and which test settles it."""
    return [(p.label, p.profile) for p in describe_perturbations(profile, rules)]


# ---- the seal ---------------------------------------------------------------------------------------------------


def catalog_pool(items: Sequence[dict[str, Any]], tier: int, rules: Any) -> Callable[..., list[ItemVec]]:
    """A ``pool`` for :class:`RobustScenario`: the catalog ``items`` at ``tier``; keywords go on to ``at_tier``."""

    def pool(**item_options: Any) -> list[ItemVec]:
        return [at_tier(item, tier, rules, **item_options) for item in items]

    return pool


@dataclass(frozen=True)
class RobustScenario:
    """What a robustness run needs. ``pool(**item_options)`` returns the item pool at the scenario's tier (the options
    are those of a variant, empty for the base). ``prune`` applies exact dominance pruning before each solve;
    ``options`` and ``buffset`` are the ones given to ``build_milp``."""

    profile: Profile
    rules: Any
    pool: Callable[..., Sequence[ItemVec]]
    setup: str | None
    tier: int = 0
    buffset: BuffSet | None = None
    options: BuildOptions | None = None
    prune: bool = True


@dataclass(frozen=True)
class RobustReport:
    """``base`` is the solution of the scenario and ``runs`` the solution of each variant, in the order of
    :func:`describe_perturbations`. ``picks`` holds the base kit's item keys per slot group; ``flips`` the labels of
    every variant that changed the slot (rules first, then weights)."""

    base: Solution
    runs: tuple[tuple[Perturbation, Solution], ...]
    picks: Mapping[str, tuple[str, ...]]
    flips: Mapping[str, tuple[str, ...]]

    def labels(self) -> dict[str, str]:
        """``{slot group: "robust" or the label that changed it}``, in the order of the slot groups."""
        return {group: (self.flips[group][0] if self.flips[group] else ROBUST) for group in GROUP_NAMES}


def picks(solution: Solution) -> dict[str, tuple[str, ...]]:
    """The item keys worn in each slot group of the solution's kit, sorted (a pair as the set of its two items)."""
    worn: dict[str, list[str]] = {group: [] for group in GROUP_NAMES}
    for place, item in zip(SLOT_INSTANCES, solution.kit or ()):
        if item is not None:
            worn[place].append(item.key)
    return {group: tuple(sorted(keys)) for group, keys in worn.items()}


def _solve(
    scenario: RobustScenario, profile: Profile, item_options: Mapping[str, Any], solver: Callable[..., Solution],
    time_limit: float | None, what: str,
) -> Solution:
    items = list(scenario.pool(**item_options))
    if scenario.prune:
        items = prune(items, profile, scenario.tier, scenario.setup, scenario.buffset, scenario.options)
    milp = build_milp(profile, items, scenario.setup, scenario.buffset, scenario.options)
    solution = solver(milp, time_limit=time_limit)
    if solution.status != "optimal":
        raise RobustnessError(f"the solve for {what} ended {solution.status}, not optimal: the robustness is not known")
    return solution


def robustness_report(
    scenario: RobustScenario, *, solver: Callable[..., Solution] = solve_canonical, time_limit: float | None = None
) -> RobustReport:
    """Solve the scenario and every variant (see the module docstring). ``solver(milp, time_limit=...)`` is
    ``solve_canonical`` unless a test or a caller passes another; ``time_limit`` is given to every solve. Raises
    :class:`RobustnessError` when a solve does not end optimal."""
    described = describe_perturbations(scenario.profile, scenario.rules, setup=scenario.setup)
    base = _solve(scenario, scenario.profile, {}, solver, time_limit, "the base scenario")
    base_picks = picks(base)
    runs = tuple(
        (variant, _solve(scenario, variant.profile, variant.item_options, solver, time_limit, variant.label))
        for variant in described
    )
    flips: dict[str, list[str]] = {group: [] for group in GROUP_NAMES}
    for variant, solution in sorted(runs, key=lambda run: run[0].kind != "rule"):  # stable: rules first
        other = picks(solution)
        for group in GROUP_NAMES:
            if other[group] != base_picks[group]:
                flips[group].append(variant.label)
    return RobustReport(base, runs, base_picks, {group: tuple(labels) for group, labels in flips.items()})


def robustness(
    scenario: RobustScenario, *, solver: Callable[..., Solution] = solve_canonical, time_limit: float | None = None
) -> dict[str, str]:
    """``{slot group: "robust" or the label of the variant that changed the pick}`` for a scenario; see the module
    docstring and :func:`robustness_report`."""
    return robustness_report(scenario, solver=solver, time_limit=time_limit).labels()
