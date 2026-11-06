"""The exalt plan: the recommended effects matched onto the items of a kit.

An item has one focus socket at +1, one click socket at +2, one worn socket at +3 and one proc socket at +4. An effect moves from its **donor** item onto a **host**
item of the kit (moves are free and reversible), under the rules of the wiki's Exaltations page:

* the host is a **like item**: it shares a slot with the donor. Where an item is worn does not matter: an item in an Any place hosts like any item of its own
  slot type (players put a weapon in an Any place to carry a second bash exaltation);
* a 2H or primary-only donor needs a **primary host**: an item that can be worn in the primary hand;
* one of the trio's classes can use both items (the host's classes narrow to this overlap), and a class that gains from the effect is among them;
* both items have reached the tier the socket opens at: the host is at the tier of the kit, and a donor that arrives below it has to be upgraded (``upgrade``);
* a host carries one effect of a kind, and the plan places one focus of each stacking type (:func:`trioforge.effects.layer.layer` offers one).

Within a kind the plan is the placement of the greatest total score (an assignment, solved exactly); a tie goes to the host that a class which gains most can use, and
to a host that is its own donor. An effect with no host goes to the **no room** list with the reason (:data:`REASONS`). "Any Slot" clicks are carried and are not placed.

The same rules run in the browser for a kit of the visitor's own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from trioforge.effects.donors import usable_by
from trioforge.effects import layer
from trioforge.effects.layer import SLOT_TIER, Context

__all__ = ["KINDS", "REASONS", "plan_kit"]

KINDS = ("focus", "click", "worn", "proc")  # the kinds that need a socket, in the order the sockets open
#: why an effect has no host, in the order the checks run (a later reason means the effect got further)
REASONS = {
    "donor": "no copy of the effect can be worn by a class of the trio",
    "primary": "needs the item in the primary hand (a 2H or primary-only donor) and the kit has none that the effect can use",
    "slot": "no item in the kit shares a slot with the donor",
    "class": "no class of the trio that gains from the effect can use both the donor and a like item of the kit",
    "tier": "the kit is below the tier the socket opens at",
    "taken": "every host that can carry it already carries a better effect of its kind",
}
_STEP = ("primary", "slot", "class")  # the rules a donor and a host are held to, in the order they are checked
_SCALE = 1_000_000  # an assignment weight is the score to six decimals, then two bonus points
_BONUS_MEMBER, _BONUS_OWN = 1, 1


def needs_primary(donor: Mapping[str, Any]) -> bool:
    """A donor that only fits the primary hand: a 2H weapon or an item whose one slot is PRIMARY."""
    return bool(donor.get("two_hand")) or list(donor["slots"]) == ["PRIMARY"]


def _fit(donor: Mapping[str, Any], host: Mapping[str, Any], classes: Sequence[str], place: str) -> tuple[str | None, list[str]]:
    """``(None, overlap)`` when the donor's effect can sit on the host, else ``(the first rule it breaks, [])``. ``host`` has ``classes`` and ``slots``; ``place`` is
    where the host is worn in the kit: a 2H or primary-only donor needs the host in the primary hand itself (``PRIMARY``), not in the secondary hand or an Any place.
    Every other rule goes by the host's own slots, wherever it is worn."""
    if needs_primary(donor) and not (place == "PRIMARY" and "PRIMARY" in host["slots"]):
        return "primary", []
    if not set(donor["slots"]) & set(host["slots"]):
        return "slot", []
    both = [c for c in classes if ("ALL" in donor["classes"] or c in donor["classes"]) and ("ALL" in host["classes"] or c in host["classes"])]
    if not both:
        return "class", []
    return None, both


def _assign(weights: list[list[int]]) -> list[int | None]:
    """The columns that give the greatest total weight, one for each row (``None`` for a row left out: its weight there is 0). Hungarian method, integers."""
    rows = len(weights)
    if not rows:
        return []
    cols = len(weights[0]) + rows  # a dummy column for each row, so that every row has a place
    inf = float("inf")
    cost = [[-(weights[i][j]) if j < len(weights[0]) else 0 for j in range(cols)] for i in range(rows)]
    u, v = [0] * (rows + 1), [0] * (cols + 1)
    owner, way = [0] * (cols + 1), [0] * (cols + 1)
    for i in range(1, rows + 1):
        owner[0] = i
        j0 = 0
        minimum = [inf] * (cols + 1)
        used = [False] * (cols + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = owner[j0], inf, 0
            for j in range(1, cols + 1):
                if not used[j]:
                    current = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if current < minimum[j]:
                        minimum[j], way[j] = current, j0
                    if minimum[j] < delta:
                        delta, j1 = minimum[j], j
            for j in range(cols + 1):
                if used[j]:
                    u[owner[j]] += delta
                    v[j] -= delta
                else:
                    minimum[j] -= delta
            j0 = j1
            if owner[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            owner[j0] = owner[j1]
            j0 = j1
    answer: list[int | None] = [None] * rows
    for j in range(1, cols + 1):
        if owner[j] and j - 1 < len(weights[0]) and weights[owner[j] - 1][j - 1] > 0:
            answer[owner[j] - 1] = j - 1
    return answer


def plan_kit(
    options: Mapping[str, Sequence[Mapping[str, Any]]],
    kit: Sequence[tuple[str, str]],
    hosts: Mapping[str, Mapping[str, Any]],
    ctx: Context,
    classes: Sequence[str],
    role: str,
    tier: int,
) -> dict[str, list[dict[str, Any]]]:
    """Place the ``options`` of a role (:func:`trioforge.effects.layer.layer`) on the items of ``kit``.

    ``kit`` is ``(place, item key)`` for each filled place; ``hosts`` maps an item key to its ``classes`` and ``slots``; ``tier`` is the tier of the kit. Returns
    ``{"rows": [...], "noroom": [...]}``: a row is ``{"k": kind, "e": effect id, "d": donor key, "p": place, "h": host key, "c": overlapping classes,
    "u": 1 if the donor has to be upgraded to the socket's tier}``; a no-room entry is ``{"k", "e", "w": reason}``. Rows are in the order of the sockets and, in a kind,
    of the score.

    A host is useful only if a class that gains from the effect can use both items (a focus that helps the Paladin is not placed on an item only the Monk can wear): a
    focus counts for its score times the share of its gain that the overlapping classes keep (:func:`trioforge.effects.layer.focus_gain`), any other effect for its
    score, and an effect that no overlapping class can profit from (:func:`trioforge.effects.layer.gain_possible`) breaks the ``class`` rule."""
    rows: list[dict[str, Any]] = []
    noroom: list[dict[str, Any]] = []
    classes = list(classes)
    places = [(place, key) for place, key in kit if key in hosts]
    for kind in KINDS:
        entries = list(options.get(kind, ()))
        if not entries:
            continue
        needs = SLOT_TIER[kind]
        if tier < needs:  # the kit's items have not reached the tier the socket opens at: nothing of this kind can be placed
            noroom.extend({"k": kind, "e": option["effect"], "w": "tier"} for option in entries)
            continue
        cells: list[list[dict[str, Any] | None]] = []
        failed: list[int] = []
        for option in entries:
            effect = ctx.by_id[option["effect"]]
            donors = sorted((d for d in effect["items"] if d["eligible"] and usable_by(d, classes)), key=lambda d: (d["access"], -len(d["slots"])))
            gains = layer.focus_gains(effect, classes, role, ctx) if kind == "focus" else {}
            if not donors:
                cells.append([None] * len(places))
                failed.append(-2)
                continue
            deepest = -1
            line: list[dict[str, Any] | None] = []
            for place, key in places:
                best: dict[str, Any] | None = None
                for donor in donors:
                    step, overlap = _fit(donor, hosts[key], classes, place)
                    if step is None:
                        if kind == "focus":
                            gain, full = sum(gains[c] for c in overlap), sum(gains[c] for c in usable_by(donor, classes))
                            step = None if gain > 0 else "class"
                            value = option["score"] * gain / full if gain > 0 else 0.0
                        else:
                            value = option["score"]
                            step = None if layer.gain_possible(effect, kind, overlap, classes, ctx) else "class"
                    if step is not None:
                        deepest = max(deepest, _STEP.index(step))
                        continue
                    bonus = (_BONUS_MEMBER if option["member"] in overlap else 0) + (_BONUS_OWN if donor["key"] == key else 0)
                    weight = round(value * _SCALE) * 100 + 1 + bonus
                    if best is None or weight > best["weight"]:  # (the donors are in order of ease: the first of the best weight stays)
                        best = {"weight": weight, "donor": donor, "overlap": overlap}
                line.append(best)
            cells.append(line)
            failed.append(deepest)
        chosen = _assign([[cell["weight"] if cell else 0 for cell in line] for line in cells]) if places else [None] * len(entries)
        for option, line, column, deepest in zip(entries, cells, chosen, failed, strict=True):
            if column is None:
                if deepest == -2:
                    reason = "donor"
                elif any(cell is not None for cell in line):
                    reason = "taken"
                else:
                    reason = _STEP[deepest] if deepest >= 0 else "slot"
                noroom.append({"k": kind, "e": option["effect"], "w": reason})
                continue
            place, key = places[column]
            cell = line[column]
            assert cell is not None
            donor = cell["donor"]
            rows.append({
                "k": kind, "e": option["effect"], "d": donor["key"], "p": place, "h": key, "c": cell["overlap"],
                "u": 1 if donor["arrival"] is not None and donor["arrival"] < needs else 0,
            })  # fmt: skip
    return {"rows": rows, "noroom": noroom}
