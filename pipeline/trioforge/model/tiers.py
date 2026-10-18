"""The tier rules of the Upgrade tab: the tier a candidate is scored at, and what reaching a tier costs (spec 5.8).

**Where an item arrives** (:func:`arrival_tier`). The catalog says how an item gets its tier (``tier_rule``):

* ``drop``: it arrives at the difficulty of the instance, +0 to +4 (``D``; no fresh drop has been seen above +4);
* ``fixed0``: a quest reward, a crafted item or a vendor item arrives at +0;
* ``spell``: a summoned item arrives at the rank of its spell; no rank is known yet, so it counts as +0 and the page labels
  it so.

**Which tier a candidate is scored at** (:func:`tier_for_mode`), by the visitor's tier mode:

* ``ready4``: +4 for every item. It is what the item is worth once the visitor has brought it there (the default);
* ``arrives``: the arrival tier above, with ``D`` from 0 to 4;
* ``fixed``: +``N`` for every item, ``N`` from 0 to 10.

**What reaching a tier costs** (:func:`cost_to_reach`). Tier ``N`` needs ``2^N - 1`` experience in all; an item at tier ``M``
holds ``2^M - 1``. A copy that arrives at +k gives ``2^k``. So going from ``from_tier`` to ``to_tier`` needs
``2^to - 2^from`` experience, and ``copies_at_arrival`` arriving copies (at least) supply it. +4 from +0 is one D4 copy (16
experience for the 15 needed) or 15 copies that arrive at +0; +10 from +4 is 63 D4 copies (1,008 experience, exactly), and
+10 from +0 is 64 (1,023 experience, which 63 copies fall short of). ``potentials`` is how many Void-touched Potentials would
do it alone: each gives one tier. Motes give 1 to 10 experience up to their grade cap and are not counted here.

The constants are those of ``rules/rules.json`` (``tier.max_fresh_drop``, ``tier.exp_needed``), which the tests compare.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "MAX_DIFFICULTY",
    "MAX_TIER",
    "MODES",
    "READY_TIER",
    "TIER_RULES",
    "arrival_tier",
    "cost_to_reach",
    "tier_for_mode",
]

TIER_RULES = ("drop", "fixed0", "spell")
MODES = ("ready4", "arrives", "fixed")
MAX_TIER = 10
MAX_DIFFICULTY = 4  # tier.max_fresh_drop
READY_TIER = 4  # the tier of the mode "ready4"


def _whole(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be a whole number from {low} to {high}, not {value!r}")
    if not low <= value <= high:
        raise ValueError(f"{name} must be a whole number from {low} to {high}, not {value}")
    return value


def _rule(item: Any) -> str:
    """The tier rule of a catalog record, of an object with a ``tier_rule``, or the rule itself."""
    if isinstance(item, str):
        rule = item
    elif isinstance(item, Mapping):
        rule = item.get("tier_rule")
    else:
        rule = getattr(item, "tier_rule", None)
    if rule not in TIER_RULES:
        raise ValueError(f"the tier rule is one of {', '.join(TIER_RULES)}, not {rule!r}")
    return rule


def arrival_tier(item: Any, D: int = MAX_DIFFICULTY) -> int:
    """The tier an item arrives at: +``D`` for a ``drop``, +0 for ``fixed0`` and ``spell`` (no rank is known yet)."""
    rule = _rule(item)
    difficulty = _whole(D, "D", 0, MAX_DIFFICULTY)
    return difficulty if rule == "drop" else 0


def tier_for_mode(item: Any, mode: str, D: int = MAX_DIFFICULTY, N: int | None = None) -> int:
    """The tier a candidate is scored at under a tier mode (see the module docstring).

    ``item`` is a catalog record (or anything with a ``tier_rule``, or the rule). ``D`` is the instance difficulty, 0 to 4,
    checked in every mode; ``N`` is the tier of ``fixed`` mode, 0 to 10, required there. Raises ``ValueError`` for an
    unknown mode or tier rule and a number out of range, ``TypeError`` for a number that is not a whole number."""
    rule = _rule(item)
    difficulty = _whole(D, "D", 0, MAX_DIFFICULTY)
    if mode not in MODES:
        raise ValueError(f"the tier mode is one of {', '.join(MODES)}, not {mode!r}")
    if mode == "ready4":
        return READY_TIER
    if mode == "arrives":
        return difficulty if rule == "drop" else 0
    if N is None:
        raise ValueError("the fixed tier mode needs N, the tier (0 to 10)")
    return _whole(N, "N", 0, MAX_TIER)


def cost_to_reach(item: Any, from_tier: int, to_tier: int, D: int = MAX_DIFFICULTY) -> dict[str, int]:
    """What it takes to bring an item from ``from_tier`` to ``to_tier``: ``{exp, copies_at_arrival, potentials}``.

    ``exp`` is ``2^to - 2^from``; ``copies_at_arrival`` the fewest copies that arrive at the item's arrival tier
    (:func:`arrival_tier`, with ``D``) whose experience adds up to it; ``potentials`` the Void-touched Potentials that would
    do it alone, ``to - from``. A tier already reached costs nothing; a lower one is a ``ValueError``, as is a tier outside
    0 to 10 or a difficulty outside 0 to 4 (a tier that is not a whole number is a ``TypeError``)."""
    arrives = arrival_tier(item, D)
    start = _whole(from_tier, "from_tier", 0, MAX_TIER)
    stop = _whole(to_tier, "to_tier", 0, MAX_TIER)
    if stop < start:
        raise ValueError(f"an item cannot be brought down from +{start} to +{stop}")
    need = 2**stop - 2**start
    per_copy = 2**arrives
    return {"exp": need, "copies_at_arrival": -(-need // per_copy), "potentials": stop - start}
