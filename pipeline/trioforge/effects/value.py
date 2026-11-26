"""The value of a proc, written once: the solver's table (:mod:`trioforge.effects.score`) and the lists of effects to exalt (:mod:`trioforge.effects.layer`) both call it (:func:`effect_value`, for every
proc record, damage or not; below it is the damage part of it).

A damage proc (``damage``, ``lifetap`` or ``dot``) is **two parts** at most (:func:`trioforge.effects.spells.classify_spell` keeps them apart): the one-time part (the direct hit of a
spell: SPA 79, or the whole of an instant spell) and the lasting part (the damage of each tick for every tick: a total over the duration, or the number of one tick for a permanent
spell). Each part carries the share that lands (``effects.proc_landing``) and the share of a restricted target (``effects.restricted_targets``, a Dismiss or a Banish):

* the one-time part is worth ``procs a minute x part x landing x restricted``: it comes with every proc;
* the lasting part is worth the same, held to one copy up at a time: at most ``part x landing x restricted / duration in minutes`` (a duration is ``duration_ticks`` of six seconds). The
  lasting part of a permanent spell (the unit ``hp_per_tick``: a number for each tick, with no end) is not damage a proc: one copy is up for ever once a proc has started it, so it is that number
  every tick of a minute (ten) x landing x restricted, whatever the rate.

A record that has no parts (a hand-made view of ``{category, magnitude}``) is read as it always was: a ``dot`` is a lasting part, any other category a one-time part.
"""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from typing import Any

from trioforge.effects import spells as sp
from trioforge.effects.derive import ALIASES
from trioforge.effects.judgment import Judgment

__all__ = [
    "DAMAGE_KINDS", "candidate_views", "covered", "damage_parts", "damage_record_value", "damage_value", "effect_value", "fr", "proc_per_minute", "record_view", "restricted_share", "view_value",
]  # fmt: skip

DAMAGE_KINDS = ("damage", "lifetap", "dot")

TICK_SECONDS = 6
MINUTE_SECONDS = 60


def fr(number: Any) -> Fraction:
    """A rule or a spell number as the decimal it was written as (a float read as its shortest text)."""
    return number if isinstance(number, Fraction) else Fraction(str(number))


def proc_per_minute(j: Judgment, rate_pct: Any = None) -> Fraction:
    """Procs a minute of a proc effect with the Rate line ``rate_pct`` (None or 0: no line): ``(D / dex_divisor + base) x (1 + rate / 100)`` at the reference DEX, and never below 0 (a line of -100 percent or
    under is a proc that never fires; the Rate lines of the catalog are within +-75 percent, so none is)."""
    base = fr(j.proc_dex) / fr(j.proc_ppm["dex_divisor"]) + fr(j.proc_ppm["base"])
    return max(Fraction(0), base * (1 + fr(rate_pct or 0) / 100))


def restricted_share(target: Any, j: Judgment) -> Fraction:
    """The share of plain damage that a spell of this target counts for: a Dismiss or Banish works on animals, undead or summoned only."""
    return fr(j.restricted_fraction) if target in j.restricted_targets else Fraction(1)


def record_view(effect: dict[str, Any]) -> dict[str, Any]:
    """An effect record as the valuation reads it: its category, its size and its two parts, and the duration and the target of its spell."""
    spell = effect.get("spell") or {}
    view = {"category": effect["category"], "magnitude": effect.get("magnitude"), "duration_ticks": spell.get("duration_ticks"), "target": spell.get("target"), "unit": effect.get("unit")}
    for part in ("once", "lasting"):
        if part in effect:
            view[part] = effect[part]
    return view


def damage_parts(view: dict[str, Any]) -> tuple[Any, Any]:
    """``(one-time part, lasting part)`` of a damage view: the parts it names, else (a view with none) the whole magnitude as the part its category says."""
    if "once" in view or "lasting" in view:
        return view.get("once") or 0, view.get("lasting") or 0
    magnitude = view.get("magnitude") or 0
    return (0, magnitude) if view["category"] == "dot" else (magnitude, 0)


def damage_value(view: dict[str, Any], ppm: Fraction, j: Judgment, *, restricted: bool = True) -> Fraction:
    """What a damage view is worth a minute at ``ppm`` procs a minute (see the module docstring). ``restricted`` False leaves the share of a restricted target out (the share is a
    factor of both parts and of the cap alike, so the value without it times the share is the value with it)."""
    landing = fr(j.proc_landing)
    share = restricted_share(view.get("target"), j) if restricted else Fraction(1)
    once, lasting = damage_parts(view)
    ticks = view.get("duration_ticks") or 0
    ppm = max(ppm, Fraction(0))  # (a rate below 0 is no proc: the one-time part and a part with an end are 0 as well)
    value = ppm * fr(once) * landing * share
    if lasting and view.get("unit") == "hp_per_tick":
        # the lasting part of a spell with no end is a number for each tick: one copy is up for ever once a proc has started it, so it does that every tick of a minute (ten), whatever the rate, but only
        # if a proc ever fires (a rate of 0 or below starts none)
        if ppm > 0:
            value += fr(lasting) * Fraction(MINUTE_SECONDS, TICK_SECONDS) * landing * share
    elif lasting:
        part = ppm * fr(lasting) * landing * share
        if ticks:
            part = min(part, fr(lasting) * landing * share * MINUTE_SECONDS / (ticks * TICK_SECONDS))  # one copy up at a time: at most the lasting part of a duration, with its shares
        value += part
    return value


# ---- the value of a proc record: one function for the table of the solver and for the lists ---------------------------------------------------------------------


def covered(category: str, magnitude: Any, classes: Sequence[str], ctx: Any) -> bool:
    """Whether a class of the trio has a spell of ``category`` at least as strong as the proc's (any spell of the kind when the proc has no number to compare)."""
    for c in classes:
        if not ctx.own_cats[c].get(category):
            continue
        best = ctx.own_best[c].get(category)
        if not magnitude or best is None or best >= magnitude:
            return True
    return False


def view_value(view: dict[str, Any], ppm: Fraction, ctx: Any, j: Judgment, classes: Sequence[str]) -> Fraction:
    """``ppm x D_eff`` of a spell seen as ``{category, magnitude, duration_ticks, target}``: a damage proc is :func:`damage_value`; every other kind is its share of a full proc
    (``ctx.proc_scale``, the size of a full proc a minute at the rate of one) with the cut of a trio that has a spell of its own (the cut of a haste buff for a haste proc).
    ``ctx`` is read for the scale, the haste providers and the spells the classes have (:class:`trioforge.effects.layer.Context`)."""
    category = view["category"]
    if category in DAMAGE_KINDS:
        return damage_value(view, ppm, j)
    if category == "unresolved":
        return Fraction(0)
    share = fr(j.proc_value.get(category, j.score_shape["unlisted_proc"]))
    size = share * fr(ctx.proc_scale) * fr(j.proc_landing)
    if category == "haste":
        if any(ctx.haste_provider[c] for c in classes):
            size *= fr(j.haste_cut)
    elif covered(category, view.get("magnitude"), classes, ctx):
        size *= fr(j.proc_own_cut)
    return ppm * size


def candidate_views(effect: dict[str, Any], book: sp.SpellBook, j: Judgment) -> list[dict[str, Any]]:
    """The spells an ambiguous record may be, as views: the same-named spells of the client that the pick chooses among, for a caster of the cast level."""
    rows = book.by_name.get(ALIASES.get(effect["name"], effect["name"]), [])
    level = min(effect.get("cast_level") or j.cap, j.cap)
    spells = [sp.spell_from_row(row, level) for row in rows]
    views = []
    for spell in sp.pick_pool(spells, "proc") if spells else []:
        views.append({**sp.classify_spell(spell, j), "duration_ticks": spell["duration_ticks"], "target": spell["target"]})
    return views


def effect_value(effect: dict[str, Any], ctx: Any, book: sp.SpellBook, j: Judgment, classes: Sequence[str]) -> Fraction:
    """The value of a proc effect record for a trio (``classes``): procs a minute times the damage-equivalent of one; 0 for a record whose marks the rule does not let count, and for a record
    marked ambiguous whose name matches no spell, else the smallest value over the spells it may be (the record's own view for a record that is not ambiguous). **The one function:** the table
    of the solver (:func:`trioforge.effects.score.proc_table`) and every list of effects to exalt (:func:`trioforge.effects.layer.layer`) value a record with it, and the scale of a full proc is
    measured over it (:func:`damage_record_value`)."""
    marks = set(effect.get("unverified") or ())
    if marks - j.proc_score_kinds:
        return Fraction(0)
    ppm = proc_per_minute(j, effect.get("rate_pct"))
    if "ambiguous" in marks:
        views = candidate_views(effect, book, j)
        if not views:  # the name matches no spell of the book: such a record counts 0, and never falls back on the record's own view
            return Fraction(0)
        return min(view_value(view, ppm, ctx, j, classes) for view in views)
    return view_value(record_view(effect), ppm, ctx, j, classes)


def damage_record_value(effect: dict[str, Any], book: sp.SpellBook, j: Judgment) -> Fraction:
    """:func:`effect_value` of a record of a damage kind, over the spells it may be **that are damage**, which needs no scale: it is what the scale of a full proc (``ctx.proc_scale``) is
    measured over, and the scale cannot be measured over a value that is read from it. For a record that is not ambiguous it is :func:`effect_value`'s own, for any trio."""
    marks = set(effect.get("unverified") or ())
    if marks - j.proc_score_kinds:
        return Fraction(0)
    ppm = proc_per_minute(j, effect.get("rate_pct"))
    if "ambiguous" not in marks:
        return damage_value(record_view(effect), ppm, j)
    values = [damage_value(view, ppm, j) for view in candidate_views(effect, book, j) if view["category"] in DAMAGE_KINDS]
    return min(values) if values else Fraction(0)
