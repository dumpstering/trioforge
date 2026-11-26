"""The judgment constants of the effects layer: one place, as rules of ``rules/rules.json`` with the seal ``model``.

Everything in the layer that is a matter of judgment and not of data (the value of one percent of a focus kind, how much a class leans on a kind of spell, how
relevant a click is to a role, the weight of a source, the dispel constant ...) is read from the rules named ``effects.*`` by :meth:`Judgment.from_rules`. The
data parts (spell values, class levels, focus limits and tiers, the lists of donor items) come from the client's spell text and the wiki. Change a number in
``rules/rules.json``, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trioforge import rules as rules_module

__all__ = ["Judgment", "default"]


def _ranged(templates: dict, factors: dict) -> dict:
    """The Ranged template: the Melee template with each weight that ``roles.ranged_template`` names multiplied by its factor (as ``model.roles`` makes it)."""
    return {key: value * factors.get(key, 1) for key, value in templates["melee"].items()}


@dataclass(frozen=True)
class Judgment:
    """The constants, as the rules give them. ``relevance`` and ``dispel_relevance`` are ``(tank, melee, caster)``."""

    cap: int
    late: int
    cast_mass_full: float
    cast_categories: frozenset[str]
    focus_value: dict[str, float]
    spell_weight: dict[str, float]
    relevance: dict[str, tuple[float, float, float]]
    dispel_relevance: tuple[float, float, float]
    gap_categories: frozenset[str]
    own_compare: frozenset[str]
    instant_categories: frozenset[str]
    instant_bonus: float
    proc_value: dict[str, float]
    score_shape: dict[str, float]
    haste_min_pct: float
    haste_cut: float
    haste_click_full_pct: float
    haste_classes: frozenset[str]
    near_best: float
    access_cost: dict[str, int]
    raid_zones: frozenset[str]
    one_off_spas: frozenset[int]
    restricted_targets: frozenset[int]
    restricted_fraction: float
    unverified_names: frozenset[str]
    rows_kept: dict[str, int]
    templates: dict[str, dict[str, float]]
    proc_ppm: dict[str, float]
    proc_dex: float
    proc_landing: float
    proc_own_cut: float
    proc_score_kinds: frozenset[str]
    socket_proc: int

    @classmethod
    def from_rules(cls, rules: Any) -> Judgment:
        """Read the constants from a :class:`trioforge.rules.Rules`."""
        get = rules.get
        haste = get("effects.haste_buff")
        restricted = get("effects.restricted_targets")
        return cls(
            cap=get("level.current"),
            late=get("effects.late_level"),
            cast_mass_full=get("effects.cast_mass_full"),
            cast_categories=frozenset(get("effects.cast_categories")),
            focus_value=get("effects.focus_value"),
            spell_weight=get("effects.spell_weight"),
            relevance={kind: tuple(row) for kind, row in get("effects.click_relevance").items()},
            dispel_relevance=tuple(get("effects.dispel_relevance")),
            gap_categories=frozenset(get("effects.gap_categories")),
            own_compare=frozenset(get("effects.own_compare")),
            instant_categories=frozenset(get("effects.instant_categories")),
            instant_bonus=get("effects.instant_bonus"),
            proc_value=get("effects.proc_value"),
            score_shape=get("effects.score_shape"),
            haste_min_pct=haste["min_pct"],
            haste_cut=haste["cut"],
            haste_click_full_pct=haste["click_full_pct"],
            haste_classes=frozenset(haste["classes"]),
            near_best=get("effects.near_best"),
            access_cost=get("effects.access_cost"),
            raid_zones=frozenset(get("effects.raid_zones")),
            one_off_spas=frozenset(get("effects.one_off_spas")),
            restricted_targets=frozenset(restricted["targets"]),
            restricted_fraction=restricted["fraction"],
            unverified_names=frozenset(get("effects.unverified_names")),
            rows_kept=get("effects.rows_kept"),
            templates={**get("roles.templates"), "ranged": _ranged(get("roles.templates"), get("roles.ranged_template"))},
            proc_ppm=get("effects.proc_per_minute"),
            proc_dex=get("effects.proc_reference_dex"),
            proc_landing=get("effects.proc_landing"),
            proc_own_cut=get("effects.proc_own_cut"),
            proc_score_kinds=frozenset(get("effects.proc_score_kinds")),
            socket_proc=get("tier.socket_open")["proc"],
        )

    def weight_of(self, kind: str) -> float:
        """The weight of a kind of spell in the coverage of a focus (the weight of ``other`` for a kind that is not listed)."""
        return self.spell_weight.get(kind, self.spell_weight["other"])

    def relevance_of(self, kind: str, role: str, classes: tuple[str, ...] | list[str], groups: dict[str, frozenset[str]]) -> float:
        """The relevance of a kind of click to a build, from the column of the build's kind in the rule (tank, melee, caster). ``role`` is one of the builds; a call that names none
        (``None``, or a name that is no build) is refused with a ``ValueError``: there is no mean over the columns to fall back to."""
        table = {"dispel": self.dispel_relevance}.get(kind) or self.relevance.get(kind) or self.relevance["other"]
        # a Ranger is a melee class (the Archer build reads the melee column); a Shield caster is a tank class that casts, so it reads the tank column; a Caster tank is a caster
        index = {"tank": 0, "shield": 0, "melee": 1, "ranged": 1, "castertank": 2, "caster": 2}
        if role not in index:
            raise ValueError(f"the relevance of a click is that of a build, and {role!r} is not one ({', '.join(index)})")
        return table[index[role]]


_default: Judgment | None = None


def default() -> Judgment:
    """The constants of the rules file in the repository (read once)."""
    global _default
    if _default is None:
        _default = Judgment.from_rules(rules_module.load())
    return _default
