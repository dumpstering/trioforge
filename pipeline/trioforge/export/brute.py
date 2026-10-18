"""Small random instances and an independent brute force, for the ``brute/`` family of the parity fixtures.

The browser engine builds the same program as :func:`trioforge.solver.model.build_milp` and a parity test holds it to
the exact maximum of small pools, so the maximum has to come from something that shares nothing with the builder. This
module lists **every legal kit and every legal buff set** of a small pool and values them with the exact evaluator
(:func:`trioforge.model.formulas.evaluate`). A float evaluator in numpy ranks the (kit, buff set) pairs quickly, and the
exact evaluator then values every pair that is within a hair of the best, so the answer is exact and the float code can
only make the search slower, never wrong.

The legality rules (which item fits which group, Lore, the hand rules of each setup, the two-hander rule) are written
out here again and share no line with the builder. The instances (:func:`random_instance`) and the enumerator
(:class:`Space`) are the ones the solver tests use (``pipeline/tests/solver_helpers.py``), written out once more because
the tests are not part of the package: a test holds the two copies to each other (the same seed gives the same instance
and the same exact maximum), so a change to one that is not made to the other is reported. Every name here is invented;
item keys are plain labels (``it00``), never keys of the catalog.

An instance carries a real :class:`~trioforge.model.profile.Profile` (labelled ``balanced``, evidence ``wiki``, with
placeholder AA choices: the instance gives the percents the choices would have made), so a fixture can store it as
``Profile.to_dict()`` and the browser can read it as it reads any other profile.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from fractions import Fraction
from functools import lru_cache
from typing import Any

import numpy as np

from trioforge.classes import CLASS_CODES
from trioforge.model import formulas as fm
from trioforge.model.buffs import COMPONENTS, Buff, BuffSet
from trioforge.model.formulas import evaluate
from trioforge.model.items import SLOT_GROUPS, SLOT_INSTANCES, ItemVec, WeaponVec
from trioforge.model.profile import Profile
from trioforge.model.tables import Tables, load

__all__ = [
    "Instance",
    "Space",
    "TRIO_MENU",
    "item_record",
    "kit_from_groups",
    "random_instance",
]

GROUP_SIZE = dict(SLOT_GROUPS)
MODEL_SLOTS = tuple(name for name, _ in SLOT_GROUPS if name != "ANY")
HANDS = ("PRIMARY", "SECONDARY")
ATTRS = ("STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA")
FLAT = ("HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG")
SCHOOLS = fm.SCHOOLS
SETUP_NAMES = ("1h-shield", "2h", "dw", "stick")
KIT_LIMIT = 3000  # the most (kit) combinations a random instance may have before the generator drops items
PLACEMENT_CHOICES = ("top", "inside")

# (race, trio): a trio with no mana class and a Monk, a mixed WIS/INT trio, a Monk trio whose END pools switch, a
# mixed trio of another shape, and the Berserker with two of the 900-pool classes.
TRIO_MENU = (
    ("HUM", ("WAR", "MNK", "ROG")),
    ("ERU", ("CLR", "WIZ", "ENC")),
    ("OGR", ("PAL", "MNK", "BER")),
    ("DEF", ("SHD", "CLR", "SHM")),
    ("TRL", ("BER", "WAR", "ROG")),
)
STAT_MENU = ("AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG")
WEIGHT_MENU = ("HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", "CHA", "HPREG", "MANAREG", "ENDREG", "DMG", "SV")


@lru_cache(maxsize=1)
def tables() -> Tables:
    """The model tables of this checkout (read once)."""
    return load()


# ---- small builders ------------------------------------------------------------------------------------------


def make_item(
    key, slots, *, stats=None, sv=None, haste=0, weight10=0, lore=False, weapon=None, shield=False, classes=None,
    deity=None, tier=0,
):
    """An ItemVec with invented contents."""
    return ItemVec(
        key=key, name=key, slots=frozenset(slots), classes=frozenset(classes or CLASS_CODES),
        deity=None if deity is None else frozenset(deity), lore=lore,
        stats={k: v for k, v in (stats or {}).items() if v}, sv={k: v for k, v in (sv or {}).items() if v},
        haste=haste, weight10=weight10, weapon=weapon, is_shield=shield, tier=tier,
    )


def make_buff(bid, *, haste=0, **components):
    """A Buff that carries only the given components (names of ``COMPONENTS``), nothing else."""
    vec = [0] * len(COMPONENTS)
    for name, amount in components.items():
        vec[COMPONENTS.index(name)] = amount
    vec[COMPONENTS.index("HASTE")] = haste
    return Buff(
        id=bid, name=f"buff-{bid}", classes=(), target=6, duration_ticks=None, permanent=True, effects=(),
        commands=(), vec=tuple(vec), illusion=False, source="synthetic",
    )


def edge_cover(pairs):
    """Cliques that together contain every pair, grown greedily (like the buff engine's cover)."""
    rivals = {}
    for a, b in pairs:
        rivals.setdefault(a, set()).add(b)
        rivals.setdefault(b, set()).add(a)
    covered, cliques = set(), []
    for a, b in sorted(pairs):
        if (a, b) in covered:
            continue
        clique = [a, b]
        for c in sorted(rivals[a] & rivals[b]):
            if all(c in rivals[m] for m in clique):
                clique.append(c)
        clique.sort()
        covered.update(itertools.combinations(clique, 2))
        cliques.append(tuple(clique))
    return tuple(cliques)


def make_buffset(always=(), optional=(), conflicts=(), cardinality=None, cliques=None):
    """A BuffSet written out by hand: ``conflicts`` are pairs of ids of ``optional`` buffs; the cliques default to the
    pairs themselves (``cliques=()`` leaves the pairs to the builder)."""
    pairs = tuple(sorted(tuple(sorted(pair)) for pair in conflicts))
    return BuffSet(
        always_on=tuple(sorted(always, key=lambda b: b.id)), optional=tuple(sorted(optional, key=lambda b: b.id)),
        conflicts=pairs, conflict_reasons=tuple((pair, ("test",)) for pair in pairs),
        cliques=tuple(cliques) if cliques is not None else pairs, cardinality=cardinality, dropped=(),
    )


def eval_totals(buffset, chosen=()):
    """The totals of the always-on buffs plus ``chosen`` in the shape ``evaluate`` reads (written out again here)."""
    if buffset is None:
        return {}
    t = buffset.totals(chosen)
    out = {k: v for k, v in t.items() if k not in ("sv", "haste")}
    out["SV"] = dict(t["sv"])
    out["HASTE"] = t["haste"]
    return out


def kit_from_groups(groups):
    """The 22-place kit of ``{group: [items]}``: each group fills its places in the order given."""
    kit = [None] * len(SLOT_INSTANCES)
    cursor = dict.fromkeys(GROUP_SIZE, 0)
    for group, placed in groups.items():
        for item in placed:
            index = [i for i, name in enumerate(SLOT_INSTANCES) if name == group][cursor[group]]
            cursor[group] += 1
            kit[index] = item
    return kit


# ---- legality, written out again ------------------------------------------------------------------------------


def is_weapon(item):
    return item.weapon is not None and item.weapon.dmg > 0 and item.weapon.delay > 0


def hand_ok(item, group, setup):
    if group == "SECONDARY" and item.weapon is not None and item.weapon.two_handed:
        return False  # a two-hander needs both hands: never in the off hand, whatever the setup
    if setup in (None, "stick"):
        return True
    if setup == "1h-shield":
        return item.is_shield if group == "SECONDARY" else is_weapon(item) and not item.weapon.two_handed
    if setup == "2h":
        return group == "PRIMARY" and is_weapon(item) and item.weapon.two_handed
    if setup == "dw":
        return is_weapon(item) and not item.weapon.two_handed
    raise ValueError(setup)


def fits(item, group, setup, any_rule="all"):
    """Whether ``item`` can stand in ``group`` under ``setup``."""
    if group == "ANY":
        return "ANY" in item.slots or (any_rule == "all" and any(s in MODEL_SLOTS for s in item.slots))
    if group not in item.slots:
        return False
    return hand_ok(item, group, setup) if group in HANDS else True


def candidates(items, group, setup, any_rule="all"):
    return [it for it in items if fits(it, group, setup, any_rule)]


def group_options(cands, size):
    """Every way to fill a group of ``size`` places from ``cands``: tuples of items (an empty place is allowed)."""
    options = [()]
    options += [(c,) for c in cands]
    if size == 2:
        for i, a in enumerate(cands):
            for b in cands[i:]:
                if a is b and a.lore:
                    continue
                options.append((a, b))
    return options


# ---- instances ------------------------------------------------------------------------------------------------


@dataclass
class Instance:
    """One small instance: a profile, the pool, the setup, the buff set and the assumed haste.

    ``trio``, ``race`` and ``level`` repeat what the profile says, for the caller's convenience."""

    label: str
    profile: Profile
    items: list
    setup: str | None
    buffset: BuffSet | None
    haste_assumed: int
    any_rule: str = "all"
    trio: tuple[str, ...] = ()
    race: str = ""
    level: int = 50
    notes: dict = field(default_factory=dict)

    def options_kwargs(self):
        return {"any_rule": self.any_rule, "haste_assumed": self.haste_assumed}


def best_softcap(trio, level=50):
    return max((tables().softcap[(c, level)] for c in trio), key=lambda t: t[0])


def make_profile(trio, race, weights, *, level=50, buff_totals=None, spell_haste=None, setup=None, **changes) -> Profile:
    """A profile of a real trio from the client tables with the given weights (the fields of
    :class:`~trioforge.model.formulas.EvalProfile` that are not given take the values below; ``changes`` overrides
    them). ``setup`` becomes the profile's one weapon setup."""
    cap, rate = best_softcap(trio, level)
    totals = buff_totals or {}
    base: dict[str, Any] = dict(
        level=level, naked=fm.naked(race, trio, tables()), weights=weights, pools=fm.pools_for(trio, level, tables()),
        buff_totals=totals, haste_cap=85 if "MNK" in trio else 75, softcap=(cap, rate),
        monk=fm.monk_curve(tables().rules, level) if "MNK" in trio else None, cs_pct=0, pe_pct=0, defense_cap=0,
        iksar_ac=0, placement={"monk": "top", "iksar": "top"}, bands=None, dw_factor=1,
    )
    base.update(changes)
    caps = {"regen": dict(fm.STANDARD_CAPS["regen"]), "resist": fm.STANDARD_CAPS["resist"]}
    return Profile(
        race=race, trio=tuple(trio), level=base.pop("level"), role="balanced", evidence="wiki",
        aa={"combat_stability": 0, "physical_enhancement": False},  # a placeholder: the percents are given below
        spell_haste=totals.get("HASTE", 0) if spell_haste is None else spell_haste, caps=caps,
        setups=() if setup is None else (setup,), deity=None, **base,
    )


# ---- random instances -----------------------------------------------------------------------------------------


def option_product(items, setup, any_rule):
    """The number of combinations of options over the groups (an upper bound of the legal kits)."""
    total = 1
    for g, size in SLOT_GROUPS:
        cands = candidates(items, g, setup, any_rule)
        if cands:
            total *= len(group_options(cands, size))
    return total


def _stat_value(rng, key, power=1.0):
    """A random item stat; ``power`` scales attributes and armor class so that the knees at 100, 201, 255 and 510
    and the softcap are crossed by some instances and not by others."""
    if key == "AC":
        return int((rng.randint(1, 90) if rng.random() < 0.6 else rng.randint(91, 170)) * power)
    if key in ("HP", "MANA"):
        return rng.randint(10, 220)
    if key == "END":
        return rng.randint(10, 150)
    if key == "ATK":
        return rng.randint(1, 40)
    if key in ("HPREG", "MANAREG", "ENDREG"):
        return rng.randint(1, 25)
    roll = rng.random()
    if roll < 0.10:
        return -rng.randint(1, 25) if roll < 0.08 or power == 1.0 else -rng.randint(60, int(150 * power))
    return int((rng.randint(1, 25) if roll < 0.62 else rng.randint(26, 90)) * power)


def _weapon(rng, two_handed):
    delay = rng.choice((20, 25, 30, 36, 40, 50, 60))
    bonus = rng.choice((None, None, rng.randint(3, 25)))
    skill = "2H Slashing" if two_handed else rng.choice(("1H Slashing", "1H Blunt", "Piercing"))
    return WeaponVec(skill, rng.randint(6, 45) + (10 if two_handed else 0), delay, bonus, two_handed)


def random_item(rng, key, group, monk, power=1.0):
    slots = {group}
    if rng.random() < 0.12:
        slots.add(rng.choice(MODEL_SLOTS))
    stats = {}
    for stat in rng.sample(STAT_MENU, rng.randint(1, 4)):
        stats[stat] = _stat_value(rng, stat, power)
    sv = {}
    if rng.random() < 0.35:
        for school in rng.sample(SCHOOLS, rng.randint(1, 3)):
            sv[school] = rng.randint(5, 110)
    haste = rng.randint(5, 45) if rng.random() < 0.25 else 0
    weight10 = rng.randint(0, 400) if monk else rng.randint(0, 120)
    weapon, shield = None, False
    if group in HANDS:
        kind = rng.choice(("one", "one", "two", "shield", "held")) if group == "PRIMARY" else rng.choice(
            ("one", "shield", "shield", "held")
        )
        if kind == "one":
            weapon, slots = _weapon(rng, False), {"PRIMARY", "SECONDARY"}
        elif kind == "two":
            weapon, slots = _weapon(rng, True), {"PRIMARY"}
        elif kind == "shield":
            shield, slots = True, {"SECONDARY"}
            stats["AC"] = rng.randint(5, 60)
        else:
            slots = {group}
        if weapon is not None and rng.random() < 0.5:
            stats.pop("AC", None)
    return make_item(
        key, slots, stats=stats, sv=sv, haste=haste, weight10=weight10, lore=rng.random() < 0.2, weapon=weapon,
        shield=shield,
    )


def random_buffs(rng, haste_cap, spell_haste_const, force_haste=False):
    """(always-on buffs, optional buffs, conflicts, cardinality) written by hand; optional haste buffs conflict.

    With ``force_haste`` at least two optional buffs carry a spell haste (and exclude each other)."""
    components = list(STAT_MENU) + list(SCHOOLS)

    def vec(big_sv=False):
        out = {}
        for name in rng.sample(components, rng.randint(1, 4)):
            if name in SCHOOLS:
                out[name] = rng.randint(30, 130) if big_sv else rng.randint(5, 60)
            elif name in ("HP", "MANA"):
                out[name] = rng.randint(20, 300)
            elif name == "AC":
                out[name] = rng.randint(5, 45)
            else:
                out[name] = rng.randint(2, 40)
        return out

    always = []
    if rng.random() < 0.5:
        always.append(make_buff(900, haste=spell_haste_const, **vec()))
    optional = []
    count = rng.randint(3, 6) if force_haste else rng.randint(0, 6)
    for i in range(count):
        haste = rng.randint(10, 60) if (rng.random() < 0.25 or (force_haste and i < 2)) else 0
        optional.append(make_buff(100 + i, haste=haste, **vec(big_sv=rng.random() < 0.4)))
    conflicts = set()
    for a, b in itertools.combinations([o.id for o in optional], 2):
        if rng.random() < 0.3:
            conflicts.add((a, b))
    if len(optional) >= 3 and rng.random() < 0.4:  # a group of three that exclude each other
        conflicts |= set(itertools.combinations(sorted(o.id for o in rng.sample(optional, 3)), 3 - 1))
    hasty = [o.id for o in optional if o.haste > 0]
    conflicts |= set(itertools.combinations(hasty, 2))
    cardinality = rng.randint(0, max(1, len(optional))) if optional and rng.random() < 0.5 else None
    return always, optional, conflicts, cardinality


def random_pools(rng, trio):
    """Synthetic pool tables whose lines cross inside the reachable ranges: the best two change with the gear."""

    def line(base_hi, fac_lo, fac_hi):
        return rng.randint(0, base_hi), round(rng.uniform(fac_lo, fac_hi), 2)

    hp = tuple(fm.PoolSpec(c, *line(500, 1.0, 5.0)) for c in trio)
    end = tuple(fm.PoolSpec(c, *line(800, 0.5, 5.0)) for c in trio)
    mana = tuple(fm.PoolSpec(c, *line(1500, 1.0, 5.0), rng.choice(("WIS", "INT"))) for c in rng.sample(trio, rng.choice((1, 2, 3))))
    return {"HP": hp, "MANA": mana, "END": end}


def random_instance(rng, *, trio_index=None, with_buffs=None, any_rule=None, monk_curve=None, setup=None, haste_buffs=False):
    """One small random instance: 4 to 6 groups of 2 to 4 items, a real trio, random weights, optional buffs."""
    race, trio = rng.choice(TRIO_MENU) if trio_index is None else TRIO_MENU[trio_index]
    monk = "MNK" in trio
    level = 55 if rng.random() < 0.2 else 50
    if any_rule is None:
        any_rule = "all" if rng.random() < 0.3 else "explicit"
    menu = ["HEAD", "NECK", "CHEST", "LEGS", "ARMS", "EAR", "FINGER", "WRIST", "PRIMARY", "SECONDARY", "HANDS"]
    if any_rule == "all":
        groups, per_group = rng.sample(menu, rng.randint(2, 3)), (2, 2)
    else:
        groups, per_group = rng.sample(menu, rng.randint(4, 6)), (2, 4)
    power = rng.choice((1.0, 1.0, 2.0, 3.5))
    items = []
    for g in groups:
        for _ in range(rng.randint(*per_group)):
            items.append(random_item(rng, f"it{len(items):02d}", g, monk, power))
    if any_rule == "explicit":
        for _ in range(rng.randint(0, 3)):
            items.append(make_item(
                f"it{len(items):02d}", {"ANY"} | ({rng.choice(groups)} if rng.random() < 0.4 else set()),
                stats={rng.choice(STAT_MENU): rng.randint(5, 60)}, weight10=rng.randint(0, 200),
                lore=rng.random() < 0.3,
            ))
    if setup is None:
        setup = rng.choice(SETUP_NAMES + (None,)) if set(groups) & set(HANDS) else rng.choice(("stick", None))
    while option_product(items, setup, any_rule) > KIT_LIMIT and len(items) > 2:
        # too many kits for a brute force: drop an item from the group with the most options
        counts = {g: len(group_options(candidates(items, g, setup, any_rule), size)) for g, size in SLOT_GROUPS}
        worst = max(counts, key=lambda g: counts[g])
        victims = [i for i in items if fits(i, worst, setup, any_rule)]
        items.remove(rng.choice(victims))

    # weights
    weights = {}
    for key in rng.sample(WEIGHT_MENU, rng.randint(4, len(WEIGHT_MENU))):
        weights[key] = round(rng.uniform(0.01, 5.0), 3)
    if rng.random() < 0.5:  # the damage weight will be hundreds of HP per index point: let a weapon choice matter
        weights["DMG"] = round(rng.uniform(50.0, 600.0), 2)
    if rng.random() < 0.3:
        for school in rng.sample(SCHOOLS, 2):
            weights[f"SV_{school}"] = round(rng.uniform(0.01, 3.0), 3)
    haste_cap = 85 if monk else 75
    spell_const = rng.choice((0, 0, 0, 20, haste_cap - 5, haste_cap + 6, 40))

    want_buffs = (rng.random() < 0.6 if with_buffs is None else with_buffs) or haste_buffs
    buffset = None
    if want_buffs:
        always, optional, conflicts, card = random_buffs(rng, haste_cap, spell_const, force_haste=haste_buffs)
        buffset = make_buffset(always, optional, conflicts, card, cliques=edge_cover(sorted(conflicts)))
        buff_totals = eval_totals(buffset, ())
        offered = max([b.haste for b in (*buffset.always_on, *buffset.optional)], default=0)
    else:
        buff_totals = {"HASTE": spell_const} if spell_const else {}
        offered = spell_const
    curve_kind = monk_curve if monk_curve is not None else rng.choice(("stand_in", "full_until_34"))
    profile_args = dict(
        level=level, buff_totals=buff_totals, spell_haste=max(offered, buff_totals.get("HASTE", 0)), setup=setup,
        cs_pct=rng.choice((0, 3, 5, 10)), pe_pct=rng.choice((0, 2)),
        defense_cap=rng.choice((0, 150, 230)), iksar_ac=rng.choice((0, 0, 35)),
        placement={"monk": rng.choice(PLACEMENT_CHOICES), "iksar": rng.choice(PLACEMENT_CHOICES)},
        dw_factor=rng.choice((Fraction(4, 5), Fraction(1, 2), 1)),
        bands=rng.choice((None, None, {"breaks": [100, 200, 510], "slopes": [1, 2.5, 0.654, 0]})),
    )
    if monk:
        profile_args["monk"] = fm.monk_curve(tables().rules, level, full_until=34 if curve_kind == "full_until_34" else None)
    synthetic = rng.random() < 0.3
    if synthetic:
        profile_args["pools"] = random_pools(rng, trio)
    profile = make_profile(trio, race, weights, **profile_args)
    # scale the weights so the empty kit is worth well under 2,000
    empty = evaluate(profile, [None] * 22, eval_totals(buffset, ()) if buffset else None, setup=setup, haste_assumed=0).F
    if empty > 1200:
        factor = Fraction(1200) / empty
        weights = {k: float(round(Fraction(str(v)) * factor, 5)) or 0.00001 for k, v in weights.items()}
        profile = make_profile(trio, race, weights, **profile_args)
    return Instance(
        label=f"{'/'.join(trio)} L{level} {setup} {any_rule}{' synthetic-pools' if synthetic else ''}", profile=profile,
        items=items, setup=setup, buffset=buffset, haste_assumed=rng.choice((0, 25, 50, haste_cap)), any_rule=any_rule,
        trio=tuple(trio), race=race, level=level,
    )


# ---- the space of kits ----------------------------------------------------------------------------------------


class Space:
    """Every legal kit of an instance (and every legal buff set), with float values for all of them at once."""

    def __init__(self, inst: Instance):
        self.inst = inst
        self.p = fm.compile_profile(inst.profile)
        self.group_names = []
        self.options = []
        for g, size in SLOT_GROUPS:
            cands = candidates(inst.items, g, inst.setup, inst.any_rule)
            if cands:
                self.group_names.append(g)
                self.options.append(group_options(cands, size))
        self.kits = self._enumerate()
        self._features()
        buffset = inst.buffset
        self.buff_sets = list(buffset.iter_legal()) if buffset is not None else [()]

    # -- enumeration
    def _enumerate(self):
        kits = []
        lore_of = [[frozenset(i.key for i in opt if i.lore) for opt in opts] for opts in self.options]
        twoh_of = [
            [any(is_weapon(i) and i.weapon.two_handed for i in opt) for opt in opts] if g == "PRIMARY" else None
            for g, opts in zip(self.group_names, self.options)
        ]
        has_secondary = "SECONDARY" in self.group_names
        sec_index = self.group_names.index("SECONDARY") if has_secondary else None
        prim_index = self.group_names.index("PRIMARY") if "PRIMARY" in self.group_names else None
        for combo in itertools.product(*[range(len(o)) for o in self.options]):
            lore = set()
            ok = True
            for gi, oi in enumerate(combo):
                keys = lore_of[gi][oi]
                if keys & lore:
                    ok = False
                    break
                lore |= keys
            if not ok:
                continue
            if prim_index is not None and sec_index is not None and twoh_of[prim_index][combo[prim_index]]:
                if self.options[sec_index][combo[sec_index]]:
                    continue
            kits.append(combo)
        return np.array(kits, dtype=np.int64).reshape(len(kits), len(self.group_names))

    def groups_of(self, combo):
        return {g: list(self.options[gi][combo[gi]]) for gi, g in enumerate(self.group_names)}

    def kit_of(self, combo):
        return kit_from_groups(self.groups_of(combo))

    # -- features of every option, summed over the kits
    def _features(self):
        p, inst = self.p, self.inst
        names = list(ATTRS) + list(FLAT) + ["ACW", "ACS", "W10", "HASTE", "WEAPON"] + [f"SV_{s}" for s in SCHOOLS]
        self.feat = {n: np.zeros(len(self.kits)) for n in names}
        for gi, g in enumerate(self.group_names):
            table = {n: np.zeros(len(self.options[gi])) for n in names}
            for oi, opt in enumerate(self.options[gi]):
                for item in opt:
                    for key, value in item.stats.items():
                        if key == "AC":
                            table["ACS" if (g == "SECONDARY" and item.is_shield) else "ACW"][oi] += value
                        else:
                            table[key][oi] += value
                    for school, value in item.sv.items():
                        if school in SCHOOLS:
                            table[f"SV_{school}"][oi] += value
                    table["W10"][oi] += item.weight10
                    table["HASTE"][oi] = max(table["HASTE"][oi], item.haste)
                    if g in HANDS and item.weapon is not None:
                        table["WEAPON"][oi] += float(
                            fm.weapon_index(item.weapon, g, inst.setup, inst.haste_assumed, p.dw_factor)
                        )
            idx = self.kits[:, gi]
            for n in names:
                if n == "HASTE":
                    self.feat[n] = np.maximum(self.feat[n], table[n][idx])
                else:
                    self.feat[n] += table[n][idx]
        top = int(self.feat["W10"].max()) // 10 + 2 if len(self.kits) else 2
        self.monk_table = (
            np.array([fm.monk_bonus(p.level, 10 * k, p.monk) for k in range(top + 1)], dtype=float)
            if p.monk is not None
            else None
        )

    # -- values
    def values(self, chosen=()):
        """F (float) of every kit for the buff set ``chosen`` (ids of the optional buffs)."""
        p, f = self.p, self.feat
        b = eval_totals(self.inst.buffset, chosen) if self.inst.buffset is not None else dict(p.buff_totals)
        b.setdefault("SV", {})
        w = {k: float(v) for k, v in p.weights.items()}
        W = lambda k: w.get(k, 0.0)  # noqa: E731
        T = {a: float(p.naked[a]) + float(b.get(a, 0)) + f[a] for a in ATTRS}
        total = np.zeros(len(self.kits))

        def pwl(x, breaks, slopes):
            out, low = np.zeros_like(x), 0.0
            for brk, slope in zip(breaks, slopes):
                out += float(slope) * np.clip(np.minimum(x, float(brk)) - low, 0, None)
                low = float(brk)
            return out + float(slopes[-1]) * np.clip(x - low, 0, None)

        def top2(values):
            stack = np.sort(np.stack(values), axis=0)
            return stack[-2:].sum(axis=0) if len(values) >= 2 else stack.sum(axis=0)

        # HP
        s = pwl(T["STA"], (255, 510), (1, 0.5, 0))
        hp = top2([5 + float(q.base) + float(q.fac) * s for q in p.pools["HP"]])
        total += W("HP") * (hp + f["HP"] + float(b.get("HP", 0)))
        # MANA
        if p.pools["MANA"]:
            breaks, slopes = fm.MANA_BANDS if p.bands is None else (p.bands["breaks"], p.bands["slopes"])
            conv = {st: pwl(T[st], breaks, slopes) for st in ("WIS", "INT")}
            mana = top2([float(q.base) + float(q.fac) * conv[q.stat] for q in p.pools["MANA"]])
            total += W("MANA") * (mana + f["MANA"] + float(b.get("MANA", 0)))
        # END
        average = (np.minimum(T["STR"], 510) + np.minimum(T["STA"], 510) + np.minimum(T["DEX"], 510)
                   + np.minimum(T["AGI"], 510)) / 4
        c = pwl(average, (100, 201), (1, 2.5, 1.25))
        end = top2([float(q.base) + float(q.fac) * c for q in p.pools["END"]])
        total += W("END") * (end + f["END"] + float(b.get("END", 0)))
        # AC
        monk = self.monk_table[np.minimum((f["W10"] // 10).astype(int), len(self.monk_table) - 1)] if self.monk_table is not None else 0.0
        iksar = float(p.iksar_ac)
        inside = (monk if p.placement["monk"] == "inside" else 0.0) + (iksar if p.placement["iksar"] == "inside" else 0.0)
        cap, rate = float(p.softcap[0]), float(p.softcap[1])
        x = (4 / 3) * (f["ACW"] + f["ACS"]) + float(p.defense_cap) / 3 + float(b.get("AC", 0)) / 4 + np.minimum(T["AGI"], 510) / 20 + inside
        y = math.floor(cap * (100 + float(p.cs_pct) + float(p.pe_pct)) / 100) + f["ACS"]
        sheet = np.minimum(x, rate * x + (1 - rate) * y)
        per_point = W("AC") / (4 / 3)
        total += per_point * sheet
        total += per_point * (monk if p.placement["monk"] == "top" else 0.0)
        total += per_point * (iksar if p.placement["iksar"] == "top" else 0.0)
        total += W("AC") * 0.2222 * np.clip(T["AGI"], 0, 510)
        # ATK, DEX, CHA
        total += W("ATK") * (0.666667 * np.clip(T["STR"], 0, 510) + f["ATK"] + float(b.get("ATK", 0)))
        total += W("DEX") * pwl(T["DEX"], (255, 510), (1, 0.1, 0))
        total += W("CHA") * np.clip(T["CHA"], 0, 510)
        # HASTE
        spell, hc = float(b.get("HASTE", 0)), float(p.haste_cap)
        worn = np.minimum(f["HASTE"], max(0.0, hc - spell))
        total += W("HASTE") * (min(spell, hc) + worn)
        # REGEN
        for key, cap_key in (("HPREG", "HP"), ("MANAREG", "MANA"), ("ENDREG", "END")):
            total += W(key) * (np.minimum(f[key], float(p.caps["regen"][cap_key])) + float(b.get(key, 0)))
        # RESISTS
        for school in SCHOOLS:
            weight = w[f"SV_{school}"] if f"SV_{school}" in w else W("SV")
            total += weight * np.minimum(f[f"SV_{school}"] + float(b["SV"].get(school, 0)), float(p.caps["resist"]))
        total += W("DMG") * f["WEAPON"]
        return total

    # -- the exact maximum
    def exact(self, combo, chosen):
        return evaluate(
            self.inst.profile, self.kit_of(combo), eval_totals(self.inst.buffset, chosen) if self.inst.buffset else None,
            setup=self.inst.setup, haste_assumed=self.inst.haste_assumed,
        ).F

    def best(self):
        """(exact maximum F as a Fraction, the (kit, buff set) pairs that reach it within 1e-9 relative)."""
        grid = np.stack([self.values(chosen) for chosen in self.buff_sets])
        top = grid.max()
        near = np.argwhere(grid >= top - 1e-7 * max(1.0, abs(top)))
        near = near[np.argsort(-grid[near[:, 0], near[:, 1]], kind="stable")]
        best, pairs = None, []
        for bi, ki in near[:400]:
            value = self.exact(tuple(self.kits[ki]), self.buff_sets[bi])
            if best is None or value > best:
                best, pairs = value, [(tuple(self.kits[ki]), self.buff_sets[bi])]
            elif value == best:
                pairs.append((tuple(self.kits[ki]), self.buff_sets[bi]))
        return best, pairs, float(top)


# ---- the item table record of an invented item ------------------------------------------------------------------


def item_record(item: ItemVec) -> dict[str, Any]:
    """The record of the item table (``trioforge.export.browser.items``) of an invented item at tier 0.

    The tier rules read it back as the same item (``at_tier(item_to_catalog(record), 0, rules)`` equals ``item``): worn haste
    is the stat ``HASTE``, a shield is an off-hand item whose type is ``Shield``, a two-hander is a weapon whose skill
    starts with ``2H``. An item at another tier is refused: the record holds base numbers."""
    if item.tier != 0 or not item.weight_known:
        raise ValueError(f"{item.key}: only an invented item at tier 0 with a known weight has a record")
    stats = {name: value for name, value in sorted(item.stats.items())}
    if item.haste:
        stats["HASTE"] = item.haste
    record: dict[str, Any] = {"id": None, "key": item.key, "name": item.name, "slots": sorted(item.slots)}
    if item.classes != frozenset(CLASS_CODES):
        record["classes"] = sorted(item.classes)
    if item.races is not None:
        record["races"] = sorted(item.races)
    if item.deity is not None:
        record["deity"] = sorted(item.deity)
    if item.lore:
        record["lore"] = True
    if stats:
        record["stats"] = stats
    if item.sv:
        record["sv"] = dict(sorted(item.sv.items()))
    record["weight10"] = item.weight10
    if item.weapon is not None:
        record["weapon"] = {
            "skill": item.weapon.skill, "dmg": item.weapon.dmg, "delay": item.weapon.delay, "bonus": item.weapon.bonus,
        }
    if item.is_shield:
        record["item_type"] = "Shield"
        record["item_type_source"] = None
    record["tier_rule"] = "drop"
    record["evidence"] = {"level": "wiki"}
    return record
