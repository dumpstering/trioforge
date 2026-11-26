"""What a weapon proc is worth in the score, and the table of procs of a trio that the solver and the evaluator read.

A proc is worth ``value = procs a minute x damage-equivalent of one proc`` (the unit of :mod:`trioforge.model.procs`, which turns it into a weapon index). Both factors are
rules of ``rules/rules.json`` with the seal ``model``, read through :class:`trioforge.effects.judgment.Judgment`:

* **Procs a minute** (``effects.proc_per_minute``): ``(D / 170 + 1/2) x (1 + rate / 100)`` with ``D`` the fixed reference DEX (``effects.proc_reference_dex``, so the weapon
  term stays linear in the items) and ``rate`` the Rate line of the item's effect (0 when it lists none). **The Rate factor lives here and nowhere else.**
* **Damage-equivalent of one proc**, ``D_eff``:

  - damage, lifetap and damage over time: **two parts** (:mod:`trioforge.effects.value`, the one function the lists of :mod:`trioforge.effects.layer` call too): the one-time part (a
    direct hit) is its size times the share that lands (``effects.proc_landing``) and, for a Dismiss or Banish (a restricted target), the share of the rule
    ``effects.restricted_targets``; the lasting part (a poison, a bleed) is the same, but one copy is up at a time, so its ``value`` is held to ``part x landing x restricted /
    duration in minutes`` (a duration is ``duration_ticks`` of six seconds): the cap carries the same shares as the damage it caps, so a dot that lands 85 times in 100 cannot be worth
    more than its own uptime, and the direct hit of a poisoned weapon is not capped by the poison's duration;
  - every other kind: its share of a full proc, the rule ``effects.proc_value`` (``effects.score_shape`` ``unlisted_proc`` for a kind that is not listed), times the size of a full proc
    (``Context.proc_scale``, the 90th percentile damage proc of the layer: it is measured over the size a damage proc is given (:func:`trioforge.effects.value.damage_value` over the value of one proc with no Rate line and no cap: its magnitude times ``1 + rate / 100`` where nothing lasts), so **it already holds
    the Rate lines of the reference procs**, and the Rate line of the proc being valued is applied once, in the rate, as for every other proc) and the share that lands, times ``effects.proc_own_cut`` when a class of the trio has a spell of the same
    kind at least as strong, and a haste proc times the ``cut`` of ``effects.haste_buff`` when the trio has a haste buff (and not the own cut);
  - a record whose name matches no spell counts 0.
* **Unverified records** (``effects.proc_score_kinds``): a record with a mark that the rule does not list counts 0 (``inferred``, ``description``), one marked ``ambiguous`` counts the
  **smaller** of its candidate spells (the spells of its name that :func:`trioforge.effects.spells.pick_pool` chooses among), one with no mark counts in full.

"Best" always means the largest **value**, never the largest damage: a smaller spell with a Rate line can be the larger proc.

:func:`proc_table` makes the table of a trio from the effect records of the catalog: the effects worth something, their donors (an item that carries the effect, can be worn
(it has a slot of a kit), can be worn by a class of the trio and needs no level above the cap) with the Lore flag of each. The table depends on the trio
and not on the build: the build's weapon weight (its weapon factor included) multiplies the index the table gives.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from fractions import Fraction
from typing import Any

from trioforge.effects import donors as dn
from trioforge.effects import spells as sp
from trioforge.effects.derive import ALIASES
from trioforge.effects.judgment import Judgment
from trioforge.effects.layer import Context
from trioforge.effects.plan import needs_primary
from trioforge.effects.value import DAMAGE_KINDS, candidate_views, covered, damage_value, effect_value, fr, proc_per_minute, record_view, view_value
from trioforge.model.procs import ProcDonor, ProcEffect, ProcTable

__all__ = ["effect_value", "effect_values", "proc_per_minute", "proc_table"]  # (effect_value and proc_per_minute are those of :mod:`trioforge.effects.value`)

_fr = fr  # (the name of the decimal reader the tests and the callers of this module use)


_covered = covered  # (the names the tests and the callers of this module use: the functions are those of :mod:`trioforge.effects.value`)
_view_value = view_value
_candidate_views = candidate_views


def effect_values(effects: Iterable[dict[str, Any]], ctx: Context, book: sp.SpellBook, j: Judgment, classes: Sequence[str]) -> dict[str, Fraction]:
    """``{effect id: value}`` of the proc records (:func:`trioforge.effects.donors.kind_of`) that are worth something."""
    values = {}
    for effect in effects:
        if dn.kind_of(effect) == "proc":
            value = effect_value(effect, ctx, book, j, classes)
            if value > 0:
                values[effect["id"]] = value
    return values


def proc_table(
    effects: Iterable[dict[str, Any]], ctx: Context, book: sp.SpellBook, j: Judgment, classes: Sequence[str], lore: Collection[str] = frozenset()
) -> ProcTable | None:
    """The table of procs of a trio of ``classes`` from the effect records of the catalog, or None when no proc is worth anything to it.

    A donor of a record is an item copy that can be worn (``eligible``), that a class of the trio can use and whose proc needs no level above the cap, as the lists of
    :func:`trioforge.effects.layer.layer` hold donors. ``lore`` are the keys of the Lore items: a donor says whether its item is Lore (one physical copy; any other item can be
    had twice), and the table derives from that which hands can be supplied together (:mod:`trioforge.model.procs`)."""
    trio = tuple(classes)
    values = []
    donors = []
    for effect in effects:
        if dn.kind_of(effect) != "proc":
            continue
        value = effect_value(effect, ctx, book, j, trio)
        if value <= 0:
            continue
        carriers = [
            d for d in effect["items"]
            if d["eligible"] and dn.usable_by(d, trio) and not (d["req_level"] and d["req_level"] > j.cap)
        ]  # fmt: skip
        if not carriers:
            continue
        values.append(ProcEffect(effect["id"], effect["name"], value))
        for d in carriers:
            usable = frozenset(c for c in trio if "ALL" in d["classes"] or c in d["classes"])
            donors.append(ProcDonor(effect["id"], d["key"], frozenset(d["slots"]), usable, needs_primary(d), d["key"] in lore))
    return ProcTable(trio, j.socket_proc, tuple(values), tuple(donors)) if values else None
