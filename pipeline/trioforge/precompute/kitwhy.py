"""What each stat of each item is worth in the default kit: the "why" of the rows of "Wear this" (``why`` of ``defaults.json``).

For every item of the kit and every stat it carries, the kit is valued again with that one stat taken from that one item, and the loss is the
kit's value less that value. Both values are :func:`trioforge.model.formulas.evaluate_truthful`: the kit valued at the haste it counts, as the
solver values it, so taking a haste stat off a belt also slows the weapons and the loss says so, and a stat past its cap (a resist over the cap,
worn haste over the cap or under a better piece's, a regen over its cap) loses nothing. The loss is the difference of the two exact values as a
float, not rounded: a test holds it equal to the evaluator's own difference.

The terms of an item, in the order the model lists them: the stats (``AC STR STA AGI DEX WIS INT CHA HP MANA END ATK``), the regens, ``HASTE``,
the five resists the model scores (``CORRUPTION`` is never scored, so it has no term), and ``DAMAGE`` for a weapon (the item without its weapon:
the hand it fills is then empty of damage). A negative stat has a negative loss (taking it away would add value). Terms are sorted by loss, the
largest first, the model's order breaking a tie.

When the loss is 0 the term says why where it can (the third entry): ``resist-cap``, ``regen-cap`` and ``haste-cap`` for a count at its cap,
``haste-covered`` for worn haste that another worn piece gives as much of (worn haste counts the best piece, not the sum), ``ac-softcap`` for armour class past the
softcap. Anything else is ``None``: the view's weights give it no value.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any

from trioforge.model import formulas as fm
from trioforge.model.items import REGEN_KEYS, SLOT_INSTANCES, STAT_KEYS, ItemVec
from trioforge.solver.model import eval_buff_totals

__all__ = ["REASONS", "TERMS", "default_why", "terms_of", "why_places"]

#: the terms of the "why", in the order of the model (a tie in the loss keeps it)
TERMS: tuple[str, ...] = (*STAT_KEYS, *REGEN_KEYS, "HASTE", *fm.SCHOOLS, "DAMAGE")
#: the reasons a loss of 0 is given
REASONS = ("resist-cap", "regen-cap", "haste-cap", "haste-covered", "ac-softcap")
_REGEN_CAP = {"HPREG": "HP", "MANAREG": "MANA", "ENDREG": "END"}


def terms_of(item: ItemVec) -> list[str]:
    """The terms of an item: every stat the model scores that it carries, in :data:`TERMS` order."""
    have = {key for key, amount in item.stats.items() if amount}
    if item.haste:
        have.add("HASTE")
    have.update(school for school in fm.SCHOOLS if item.sv.get(school))
    if item.weapon is not None:
        have.add("DAMAGE")
    return [term for term in TERMS if term in have]


def without(item: ItemVec, term: str) -> ItemVec:
    """``item`` with the one term taken away."""
    if term == "HASTE":
        return dataclasses.replace(item, haste=0)
    if term == "DAMAGE":
        return dataclasses.replace(item, weapon=None)
    if term in fm.SCHOOLS:
        return dataclasses.replace(item, sv={key: amount for key, amount in item.sv.items() if key != term})
    return dataclasses.replace(item, stats={key: amount for key, amount in item.stats.items() if key != term})


def _reason(term: str, item: ItemVec, kit: Sequence[ItemVec | None], index: int, base: fm.Breakdown, profile: fm.EvalProfile) -> str | None:
    """Why a term that is worth nothing is worth nothing, or None."""
    totals = base.totals
    if term in fm.SCHOOLS:
        return "resist-cap" if totals["resists"][term]["gear"] + (totals["resists"][term]["buff"]) >= profile.caps["resist"] else None
    if term in _REGEN_CAP:
        return "regen-cap" if totals["regen"][term]["gear"] >= profile.caps["regen"][_REGEN_CAP[term]] else None
    if term == "HASTE":
        others = [other.haste for place, other in enumerate(kit) if other is not None and place != index]
        if others and max(others) >= item.haste:  # (worn haste counts the best piece: a piece that another matches adds nothing, cap or no cap)
            return "haste-covered"
        return "haste-cap" if totals["haste"]["counted"] >= profile.haste_cap else None
    if term == "AC":
        sheet = totals["sheet"]
        return "ac-softcap" if sheet["X"] > sheet["Y"] else None
    return None


def why_places(
    profile: Any, kit: Sequence[ItemVec | None], buffs: Mapping[str, Any] | None, setup: str | None, procs: Any = None
) -> list[dict[str, Any] | None]:
    """The 22 places of ``kit`` as ``{"key", "loss": [[term, loss, reason], ...]}``, ``None`` for an empty place (an item with no term to lose has an empty list).

    ``profile`` is what :func:`~trioforge.model.formulas.evaluate_truthful` reads (an ``EvalProfile`` or an object that has its fields), ``buffs`` the buff
    totals of the kit's buffs as that function takes them (``None`` for the profile's own), ``setup`` the weapon setup the kit was solved for and ``procs`` the table of
    procs of the run (None: none counts): ``DAMAGE`` then loses the proc of the hand with the swing, as a weapon with no damage swings no proc."""
    if len(kit) != len(SLOT_INSTANCES):
        raise ValueError(f"a kit has one entry for each of the {len(SLOT_INSTANCES)} places, not {len(kit)}")
    compiled = fm.compile_profile(profile)
    base = fm.evaluate_truthful(compiled, kit, buffs, setup=setup, procs=procs)
    places: list[dict[str, Any] | None] = []
    for index, item in enumerate(kit):
        if item is None:
            places.append(None)
            continue
        found = []
        for term in terms_of(item):
            trial = list(kit)
            trial[index] = without(item, term)
            loss = base.F - fm.evaluate_truthful(compiled, trial, buffs, setup=setup, procs=procs).F
            reason = _reason(term, item, kit, index, base, compiled) if loss == 0 else None
            found.append((term, float(loss), reason, loss))
        found.sort(key=lambda entry: -entry[3])  # (stable: the model's order breaks a tie)
        places.append({"key": item.key, "loss": [[term, loss, reason] for term, loss, reason, _ in found]})
    return places


def default_why(ctx: Any, race: str, role: str, tier: int, setup: str, row: Mapping[str, Any]) -> list[dict[str, Any] | None]:
    """The places of the default view of one race (default evidence level, own buffs) from its solved ``row`` (``kit`` item keys, ``buffs`` ids):
    the kit as the solver left it, valued under the profile and the buffs of the solve. ``ctx`` is a :class:`trioforge.precompute.grid.Context`."""
    evidence = ctx.config.default_evidence
    vecs = ctx.vecs(tier)
    kit = [vecs[key] if key is not None else None for key in row["kit"]]
    totals = eval_buff_totals(ctx.buffsets["own"].totals(tuple(row["buffs"])))
    return why_places(ctx.profile(race, role, "own", evidence).eval_profile, kit, totals, setup, ctx.options.procs)
