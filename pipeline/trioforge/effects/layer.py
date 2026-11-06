"""What each class needs, and which effects a trio and role should exalt: the scores and the ranked lists.

A **context** (:func:`build_context`) holds what does not depend on the trio: the effect records, the share of each class's late spells each focus touches, what
a class casts (its cast mass and its best spell of each kind) and which classes have a haste buff. :func:`layer` then ranks the effects for a set of classes and a
role::

    {"focus": [...], "click": [...], "carry": [...], "worn": [...], "proc": [...]}

Each option is a dict with ``effect`` (the record's id), ``donor`` (the item key of the best donor), ``others`` (up to three more donor keys), ``score``, ``member``
(the trio class that gains most) and, for a focus, ``type`` (the stacking type: one focus applies for each) and ``losers`` (the families that lost the type) and ``gains`` (what each trio class adds to the score, for the plan).

* **focus**: one for each stacking type (the effect id; the best family and tier wins); among donors within ``near_best`` of the best score the easiest to get wins.
* **click**: only must-equip clicks (they use a click exaltation slot). **carry**: "Any Slot" clicks, which work from the bags and use no slot.
* **worn** and **proc**: as the wiki lists them; a worn effect that is haste is an item stat and is never offered (it cannot be moved).

Scores compare within one trio and role, and roughly across trios (casters score 5 to 10, tank-only trios about 1.5). They are a model: the constants are the
``effects.*`` rules of ``rules/rules.json``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from trioforge.classes import CLASS_CODES
from trioforge.effects import donors as dn
from trioforge.effects import spells as sp
from trioforge.effects.judgment import Judgment
from trioforge.model.roles import CASTER_CLASSES, MELEE_CLASSES, TANK_CLASSES

__all__ = ["Context", "build_context", "cast_mass", "focus_coverage", "focus_gain", "focus_gains", "gain_possible", "layer", "role_weights"]

ROLE_GROUPS = {"tank": TANK_CLASSES, "melee": MELEE_CLASSES, "caster": CASTER_CLASSES}
SLOT_TIER = {"focus": 1, "click": 2, "worn": 3, "proc": 4}  # the tier at which each exaltation slot opens
MAX_OTHERS = 3  # the alternate donors listed for an option


@dataclass
class Context:
    """What the lists need that does not depend on the trio."""

    j: Judgment
    effects: list[dict[str, Any]]
    by_id: dict[str, dict[str, Any]]
    cov: dict[str, dict[str, dict[str, Any]]]
    own_best: dict[str, dict[str, float]]
    own_cats: dict[str, dict[str, int]]
    mass: dict[str, float]
    cat_max: dict[str, float]
    proc_scale: float
    haste_provider: dict[str, bool]
    profiles: dict[str, dict[str, Any]]


# ---- what a class needs --------------------------------------------------------------------------------------------


def cast_mass(late_spells: list[dict[str, Any]], categories: dict[int, str], j: Judgment) -> float:
    """How much a class fights by casting: the weight of its late combat-type spells, ``cast_mass_full`` or more counting as 1."""
    total = sum(j.weight_of(categories[s["id"]]) for s in late_spells if categories[s["id"]] in j.cast_categories)
    return min(1.0, total / j.cast_mass_full)


def focus_coverage(
    effects: list[dict[str, Any]], spells: list[dict[str, Any]], categories: dict[int, str], j: Judgment
) -> dict[str, dict[str, dict[str, Any]]]:
    """For each focus effect and class: the share of the class's late spell kinds the focus touches.

    Per spell kind, the average over the class's late spells (level ``late`` to the cap) of how much of the focus each gets (:func:`~trioforge.effects.spells.focus_weight`:
    1, a loss for a spell above the focus's maximum level, or 0), then the average over the kinds the class has, weighted by the weight of each kind (a healer with
    two instant heals still gets 100 percent of the healing kind). ``n`` counts the spells touched at all and ``of`` all the late spells."""
    late = {c: [s for s in spells if j.late <= s["levels"].get(c, 0) <= j.cap] for c in CLASS_CODES}
    cov: dict[str, dict[str, dict[str, Any]]] = {}
    for effect in effects:
        focus = effect.get("focus")
        if not focus or focus["kind"] == "instrument_mod":
            continue
        row: dict[str, dict[str, Any]] = {}
        for c in CLASS_CODES:
            per: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
            touched = 0
            for spell in late[c]:
                cell = per[categories[spell["id"]]]
                cell[1] += 1
                weight = sp.focus_weight(focus["limits"], spell, spell["levels"][c])
                cell[0] += weight
                touched += weight > 0
            total = sum(j.weight_of(kind) for kind in per)
            hit = sum(j.weight_of(kind) * cell[0] / cell[1] for kind, cell in per.items())
            row[c] = {"share": round(hit / total, 4) if total else 0.0, "n": touched, "of": len(late[c])}
        cov[effect["id"]] = row
    return cov


def build_context(effects: list[dict[str, Any]], book: sp.SpellBook, j: Judgment) -> Context:
    """The context of a set of effect records (:func:`trioforge.effects.donors.build_effects`) and a spell book."""
    spells = book.class_spells()
    categories = {s["id"]: sp.classify_spell(s, j) for s in spells}
    cov = focus_coverage(effects, spells, {i: c["category"] for i, c in categories.items()}, j)
    profiles: dict[str, dict[str, Any]] = {}
    own: dict[str, dict[str, float]] = {}
    own_cats: dict[str, dict[str, int]] = {}
    mass: dict[str, float] = {}
    for c in CLASS_CODES:
        mine = [s for s in spells if 0 < s["levels"].get(c, 0) <= j.cap]
        profiles[c] = sp.class_profile(mine, c, j)
        best: dict[str, float] = {}
        counts: dict[str, int] = {}
        for spell in mine:
            k = categories[spell["id"]]
            counts[k["category"]] = counts.get(k["category"], 0) + 1
            if k["magnitude"]:
                best[k["category"]] = max(best.get(k["category"], 0), k["magnitude"])
        counts["mana_pool"] = 1 if any(s["mana"] > 0 for s in mine) else 0
        own[c], own_cats[c] = best, counts
        late = [s for s in mine if s["levels"][c] >= j.late]
        mass[c] = cast_mass(late, {s["id"]: categories[s["id"]]["category"] for s in late}, j)
    cat_max: dict[str, float] = defaultdict(float)
    for effect in effects:  # (what the click scale is measured against: effects the lists can offer)
        if dn.kind_of(effect) in ("click", "worn") and effect.get("magnitude") and offerable(effect, j):
            cat_max[effect["category"]] = max(cat_max[effect["category"]], effect["magnitude"])
    power = sorted(
        e["magnitude"] * (1 + (e.get("rate_pct") or 0) / 100) * _restricted(e, e["category"], j)  # (the size a proc score is given: restricted targets count a fraction)
        for e in effects
        if dn.kind_of(e) == "proc" and e.get("category") in ("damage", "dot", "lifetap") and e.get("magnitude") and offerable(e, j)
    )
    cut = j.score_shape["proc_full_percentile"]
    proc_scale = power[int(cut * (len(power) - 1))] if power else 1.0  # the 90th percentile of proc damage counts as a full score
    haste = {c: sp.has_haste_buff(spells, c, j) or c in j.haste_classes for c in CLASS_CODES}
    return Context(j, effects, {e["id"]: e for e in effects}, cov, own, own_cats, mass, dict(cat_max), proc_scale, haste, profiles)


def offerable(effect: dict[str, Any], j: Judgment) -> bool:
    """Whether some copy of an effect can be a donor in the lists: it can be worn (it has a slot) and its required level is within the cap."""
    return any(d["eligible"] and not (d["req_level"] and d["req_level"] > j.cap) for d in effect["items"])


# ---- roles ----------------------------------------------------------------------------------------------------------


def role_weights(role: str | None, classes: list[str], j: Judgment) -> dict[str, float]:
    """Class weights for a role (judgment): balanced is equal; a role is 1 for the classes of its group and ``off_role_class`` for the rest."""
    if role in ("balanced", None):
        return {c: 1.0 for c in classes}
    off = j.score_shape["off_role_class"]
    return {c: (1.0 if c in ROLE_GROUPS[role] else off) for c in classes}


def role_rel(role: str | None, classes: list[str], j: Judgment) -> tuple[float, float, float]:
    """``(spell factor, mana weight, melee weight)`` of a role from the rules' templates (their MANA and ATK weights); a balanced role is the mean over the
    templates the trio can play."""
    if role in ("balanced", None):
        names = [r for r in ("tank", "melee", "caster") if any(c in ROLE_GROUPS[r] for c in classes)]
    else:
        names = [role]
    mana = sum(j.templates[n]["MANA"] / 4 for n in names) / len(names)
    attack = sum(j.templates[n]["ATK"] / 3 for n in names) / len(names)
    shape = j.score_shape
    return shape["spell_floor"] + shape["spell_span"] * mana, mana, attack


def own_best(classes: list[str], category: str, own: dict[str, dict[str, float]]) -> float:
    return max((own[c].get(category, 0) for c in classes), default=0)


# ---- scores --------------------------------------------------------------------------------------------------------------


def focus_score(effect: dict[str, Any], cls: str, ctx: Context, mana_rel: float = 1.0) -> float:
    focus = effect["focus"]
    if focus["kind"] == "instrument_mod":
        return 0.5 * (focus["min_pct"] / 10) if cls == "BRD" else 0.0
    share = ctx.cov.get(effect["id"], {}).get(cls, {"share": 0.0})["share"]
    score = ctx.j.focus_value[focus["kind"]] * (effect["magnitude"] or 0) * share * ctx.mass.get(cls, 1.0)
    if focus["kind"] == "mana_preservation":
        score *= mana_rel
    return score


def focus_gains(effect: dict[str, Any], classes: list[str], role: str, ctx: Context) -> dict[str, float]:
    """What each class of the trio adds to the score of a focus in a role, to six decimals; the score of the list is the sum over the classes that can use the item."""
    weights = role_weights(role, classes, ctx.j)
    spell_rel, mana_rel, _ = role_rel(role, classes, ctx.j)
    total = sum(weights.values())
    return {c: round(weights[c] * focus_score(effect, c, ctx, mana_rel) / total * spell_rel, 6) for c in classes}


def focus_gain(effect: dict[str, Any], overlap: list[str], classes: list[str], role: str, ctx: Context) -> float:
    """What a focus is worth when only the classes of ``overlap`` can use the item that carries it: the score of the list, over those classes alone."""
    gains = focus_gains(effect, classes, role, ctx)
    return sum(gains[c] for c in overlap)


def gain_possible(effect: dict[str, Any], kind: str, overlap: list[str], classes: list[str], ctx: Context) -> bool:
    """Whether any class of ``overlap`` can profit from a click, worn effect or proc that is not a focus: a proc needs a melee class (when the trio has one), a
    mana click a class that casts."""
    if kind == "proc":
        melee = [c for c in classes if c in MELEE_CLASSES]
        return any(c in melee for c in overlap) if melee else bool(overlap)
    if effect.get("category") == "mana":
        return any(ctx.mass[c] >= 0.1 for c in overlap)
    return bool(overlap)


def _restricted(effect: dict[str, Any], category: str, j: Judgment) -> float:
    """The fraction of plain damage a Dismiss or Banish counts for: they work on animals, undead or summoned only."""
    if category in ("damage", "lifetap", "dot") and effect.get("spell", {}).get("target") in j.restricted_targets:
        return j.restricted_fraction
    return 1.0


def _click_score(effect: dict[str, Any], donor: dict[str, Any], role: str, classes: list[str], has_mana: bool, haste_cover: bool, ctx: Context) -> float:
    j, shape = ctx.j, ctx.j.score_shape
    category = effect["category"]
    rel = j.relevance_of(category, role, classes, ROLE_GROUPS)
    if category == "mana" and not has_mana:
        return 0.0
    magnitude = effect.get("magnitude")
    if category == "haste":
        # a click haste is a version-1 haste buff: worthless next to a real haste buff class (ENC, SHM, BST, BRD songs)
        return rel * min(1.0, (magnitude or 0) / j.haste_click_full_pct) * (j.haste_cut if haste_cover else 1.0)
    if category in j.gap_categories:
        covered = any(ctx.own_cats[c].get(category) for c in classes)
        return rel * (shape["gap_covered"] if covered else 1.0) * shape["gap_utility"]
    scale = ctx.cat_max.get(category) or 1
    norm = min(1.0, (magnitude or 0) / scale) if magnitude else shape["no_magnitude"]
    if category in j.own_compare or category == "dispel":
        best = own_best(classes, category, ctx.own_best)
        if best and magnitude:
            norm *= shape["own_floor"] + shape["own_span"] * min(1.0, magnitude / best)
    return rel * norm * _restricted(effect, category, j)


def _proc_score(effect: dict[str, Any], melee_rel: float, classes: list[str], haste_cover: bool, ctx: Context) -> float:
    j, shape = ctx.j, ctx.j.score_shape
    category = effect["category"]
    frac = max(shape["proc_melee_floor"], sum(c in MELEE_CLASSES for c in classes) / len(classes))
    magnitude = effect.get("magnitude") or 0
    rate = 1 + (effect.get("rate_pct") or 0) / 100
    if category in ("damage", "lifetap", "dot"):
        value = min(1.0, magnitude * rate / ctx.proc_scale) * _restricted(effect, category, j)
    else:
        value = j.proc_value.get(category, shape["unlisted_proc"])
        if category == "haste" and haste_cover:
            value *= j.haste_cut
    return melee_rel * frac * value


# ---- the lists -------------------------------------------------------------------------------------------------------------


def _by_ease(donor: dict[str, Any]) -> tuple[int, int]:
    return donor["access"], -len(donor["slots"])


def layer(classes: list[str], role: str, ctx: Context, *, top: bool = True) -> dict[str, list[dict[str, Any]]]:
    """The ranked lists of effects for ``classes`` (class codes) and ``role`` (``balanced``, ``tank``, ``melee`` or ``caster``); see the module docstring.

    ``top`` keeps the ``rows_kept`` best of each list. A donor counts only when it can be worn (it has a slot) and one of the classes can use it."""
    j = ctx.j
    weights = role_weights(role, classes, j)
    weight_sum = sum(weights.values())
    spell_rel, mana_rel, melee_rel = role_rel(role, classes, j)
    has_mana = any(ctx.mass[c] >= 0.1 for c in classes)
    haste_cover = any(ctx.haste_provider[c] for c in classes)
    result: dict[str, list[dict[str, Any]]] = {"focus": [], "click": [], "carry": [], "worn": [], "proc": []}

    types: dict[str, list[tuple[float, dict[str, Any], dict[str, Any], str]]] = defaultdict(list)
    for effect in ctx.effects:
        if effect["kind"] != "focus" or "focus" not in effect:
            continue
        per = {c: focus_score(effect, c, ctx, mana_rel) for c in classes}
        for donor in effect["items"]:
            ok = dn.usable_by(donor, classes)
            if not ok or not donor["eligible"]:
                continue
            if donor["req_level"] and donor["req_level"] > j.cap:
                continue  # (a copy nobody at the cap can use is no donor: as for the other kinds)
            score = sum(weights[c] * per[c] for c in ok) / weight_sum  # only classes that may wear the host benefit
            types[sp.focus_type(effect["focus"])].append((score * spell_rel, effect, donor, max(ok, key=lambda c: per[c])))
    for kind, options in types.items():
        best = max(o[0] for o in options)
        if best <= 0:
            continue
        near = [o for o in options if o[0] >= j.near_best * best]
        pick = min(near, key=lambda o: (o[2]["access"], -len(o[2]["slots"]), -o[0]))
        others = sorted((o[2] for o in options if o[1]["id"] == pick[1]["id"] and o[2]["key"] != pick[2]["key"]), key=_by_ease)
        family_best: dict[str, float] = {}
        for o in options:
            family = o[1]["focus"]["family"]
            if family != pick[1]["focus"]["family"] and o[0] > family_best.get(family, 0):
                family_best[family] = o[0]
        option = _option(pick[0], pick[1], pick[2], pick[3], others)
        option["gains"] = {c: g for c, g in focus_gains(pick[1], classes, role, ctx).items() if g > 0}
        option["type"] = kind
        option["losers"] = [family for family, _ in sorted(family_best.items(), key=lambda kv: -kv[1])[:3]]
        result["focus"].append(option)
    result["focus"].sort(key=lambda o: -o["score"])  # (stable: types of an equal score stay in the order their first effect has)

    raw: dict[str, list[tuple[float, dict[str, Any], dict[str, Any], str]]] = {"click": [], "carry": [], "worn": [], "proc": []}
    for effect in ctx.effects:
        kind = dn.kind_of(effect)
        if kind not in ("click", "worn", "proc") or effect.get("category") == "unresolved" or "focus" in effect:
            continue
        if kind == "worn" and effect["category"] == "haste":
            continue  # worn haste is an item stat and cannot be moved
        if kind == "click" and effect.get("mode") == "carry":
            kind = "carry"
        for donor in effect["items"]:
            ok = dn.usable_by(donor, classes)
            if not ok or not donor["eligible"]:  # a potion, poison or scroll cannot be equipped, so it is not a source
                continue
            if donor["req_level"] and donor["req_level"] > j.cap:
                continue
            if kind == "proc":
                score = _proc_score(effect, melee_rel, classes, haste_cover, ctx)
            else:
                score = _click_score(effect, donor, role, classes, has_mana, haste_cover, ctx)
                if donor["instant"] and effect["category"] in j.instant_categories:
                    score *= 1 + j.instant_bonus * spell_rel  # an instant cast skips spell recovery; casters value it
            if score <= 0:
                continue
            member = max(ok, key=lambda c: (c in MELEE_CLASSES if kind == "proc" else 0, weights[c]))
            raw[kind].append((score, effect, donor, member))
    for kind, options in raw.items():
        best_of: dict[str, tuple[float, dict[str, Any], dict[str, Any], str]] = {}
        donors_of: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for option in options:
            donors_of[option[1]["id"]].append(option[2])
            current = best_of.get(option[1]["id"])
            if current is None or (_by_ease(option[2]), -option[0]) < (_by_ease(current[2]), -current[0]):
                best_of[option[1]["id"]] = option
        chosen = [
            _option(o[0], o[1], o[2], o[3], sorted((d for d in donors_of[o[1]["id"]] if d["key"] != o[2]["key"]), key=_by_ease))
            for o in best_of.values()
        ]
        chosen.sort(key=lambda o: (-o["score"], o["effect"]))
        result[kind] = chosen
    if top:
        for kind in result:
            result[kind] = result[kind][: j.rows_kept[kind]]
    return result


def _option(score: float, effect: dict[str, Any], donor: dict[str, Any], member: str, others: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "effect": effect["id"], "name": effect["name"], "donor": donor["key"], "others": [d["key"] for d in others[:MAX_OTHERS]],
        "score": round(score, 3), "member": member,
    }  # fmt: skip
