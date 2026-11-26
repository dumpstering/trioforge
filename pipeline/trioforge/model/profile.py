"""The profile generator: one scenario's constants, in one frozen record.

``make_profile(race, trio, level, role, buffset, aa, tables, rules)`` turns a scenario into a :class:`Profile`: all
that the model needs to know about the character that is not an item. The builder (``trioforge.solver``) turns the
profile and an item pool into rows, and the evaluator (:func:`trioforge.model.formulas.evaluate`) reads the same
profile by attribute, so a profile is accepted by the oracle exactly as it is (:attr:`Profile.eval_profile`).

The fields
==========

=============  =========================================================================================================
field          what it is
=============  =========================================================================================================
race, trio,    the scenario: a race code, three class codes in the caller's order, the level and the role
level, role    (:data:`~trioforge.model.roles.ROLES`)
evidence, aa   the two inputs that are not model rows (below)
naked          race base plus the three class modifiers, uncapped (:func:`~trioforge.model.formulas.naked`)
buff_totals    the totals of the buffs that are **always on**, in the evaluator's shape (:func:`eval_buffs`); the
               buffs the solver chooses among (``BuffSet.optional``) are not in it
spell_haste    the best spell haste **on offer**, always-on or optional, plus ``haste_bonus``: the haste the weapon
               term assumes (:func:`~trioforge.model.weapons.haste_assumed`). It is at least ``buff_totals["HASTE"]``
haste_bonus    the flat haste of Unbound Alacrity: 10 for a trio with a Monk, else 0 (``haste.unbound_alacrity``). The
               evaluator adds it to the buff haste, so it stacks with the spell haste and the best worn haste and is
               cut by ``haste_cap``; the field comes last, after ``deity``, with a default of 0
haste_cap      the cap of the level (:func:`~trioforge.model.formulas.haste_cap_at`: 75 at level 50, 85 for levels 51 to 59, 100 from 60) and, with a Monk in
               the trio, the 10 of Unbound Alacrity on top of it (``haste.cap_pct``, ``haste.cap_pct_with_monk``)
softcap        ``(cap, rate past it)`` of the trio at the level, from the client table (``ac.softcap.past_cap_rate``): the cap is
               the larger of the best class cap and ``ac.softcap.base_floor`` (350), and the rate the best class rate, which may be another
               class's, and at least ``ac.softcap.rate_floor`` (0.3): the client's own calculation
cs_pct,        percent added to the softcap by Combat Stability and Physical Enhancement; the softcap the sheet uses is
pe_pct         :attr:`Profile.effective_softcap`, ``floor(cap x (100 + cs + pe) / 100)``
nd_pct         percent that Natural Durability adds to the HP that comes from STA (``hp.natural_durability_pct``); it is already in
               the ``fac`` of every HP pool of ``pools`` (below) and is recorded so that the window (which floors) and a reader can
               see it; the field comes last, after ``haste_bonus``, with a default of 0
defense_cap    the best Defense skill cap of the trio at the level
monk           the Monk worn-weight curve (``monk.weight_curve``) when the trio has a Monk, else None
iksar_ac       the racial armor class: ``race.iksar_ac_bonus`` for an Iksar, else 0
placement      ``{"monk": ..., "iksar": ...}``, each ``"top"`` (on top of the capped sheet armor class) or ``"inside"``
               (added into X before the cap), read from ``monk.bonus_placement`` and ``race.iksar_ac_placement``
pools          ``{"HP": ..., "MANA": ..., "END": ...}``, each a tuple of :class:`~trioforge.model.formulas.PoolSpec`
               (class, base, factor and, for mana, the stat), one for each class that has such a pool, in trio order. The factor
               of an HP pool is the client's ``hp_fac`` times ``1 + nd_pct / 100`` (the base and the constant 5 are not scaled)
caps           ``{"regen": {"HP", "MANA", "END"}, "resist": n}`` (``regen.gear_caps``, ``resist.cap``)
bands          the WIS/INT conversion bands (``mana.wis_bands``)
dw_factor      the share of the off hand that counts under dual wield (``weapons.dual_wield_factor``: its value for a
               trio with a Monk or for a trio without one)
ranged_factor  the multiplier of the damage per delay of a bow in the range place under the ``ranged`` setup (no damage bonus is added)
               (``weapons.ranged_factor``); the field comes last, after ``nd_pct``, with a default of 1
stance         None, or ``{"swing_factor", "agi_share"}``: the Berserker stance of the Melee damage build of a trio with a Berserker (``stance.berserker``): the
               swing of the hands is multiplied by ``swing_factor`` after the haste cap, and agility counts ``agi_share`` (0) in mitigation and evasion; the field
               comes last, after ``ranged_factor``, with a default of None
weights        the role's weights (:func:`~trioforge.model.roles.weights_for`)
setups         the weapon setups of the role (:func:`~trioforge.model.weapons.setups_for`); the ``1h-shield`` setup is
               there when the pool given to :func:`make_profile` holds a shield some class of the trio can wear (with no
               pool a shield is assumed), and the ``ranged`` setup when it holds a bow some class of the trio can equip (with
               no pool there is none)
deity          None: items locked to a deity are left out. A name admits that deity's items
=============  =========================================================================================================

Numbers are kept in one canonical form (a whole number is an ``int``, anything else a ``float``) and mappings are
read-only and sorted, so two profiles that are equal have one JSON text and one hash.

Inputs that are not MILP rows
=============================

Two choices of the scenario are recorded in the profile and in :meth:`Profile.to_json`, so a solve can be
reproduced from its profile alone.

* **The AA defaults** change the constants ``cs_pct`` and ``pe_pct`` and the factor of the HP pools. ``aa`` is ``None`` (the
  defaults: Combat Stability 3 of 3, Natural Durability 4 of 4, and Physical Enhancement when the trio has a melee class or the rule
  ``ac.softcap.pe_for_caster_only_trios`` is true, which it is not until test B10) or a mapping with any of
  ``combat_stability`` (a rank from 0 to the top rank of the rule), ``natural_durability`` (the same, rule
  ``hp.natural_durability_pct``) and ``physical_enhancement`` (a bool). The profile's ``aa`` lists the three choices as made.
  Natural Durability is the one AA that reaches the HP pools: the percent of the rank goes on the ``fac`` of each HP pool,
  ``fac x (100 + nd_pct) / 100``, so that the evaluator, the builder and the browser's engine read the AA without a rule of
  their own (they all read ``pools``); ``nd_pct`` only records it.
* **The evidence level** (``"strict"``, the default, or ``"wiki"``) changes only the item pool given to the builder.
  The profile carries it as a label.

The pool-selection data
=======================

The best two of a family's pools count (HP, mana and END each). Whether the *pair* can change decides whether the
builder needs selection binaries. :func:`fixed_pools` answers it exactly for a box of reachable inputs, and
:meth:`Profile.pool_choice` for the profile's own pools over the widest box, every input from 0 up to what a
510-capped stat can reach: the pair of classes that always counts, or ``None`` where the builder must select. A
narrower box (the reachable range of the item pool) can fix a pair that the widest box cannot.

Buffs
=====

``make_profile`` takes the resolved :class:`~trioforge.model.buffs.BuffSet` (or None for no buffs). When the slot
limit binds, no buff is always on and ``buff_totals`` is empty: the solver then chooses every buff, and the totals of
its choice go to the evaluator through ``evaluate(profile, kit, eval_buffs(buffset.totals(chosen)))``.
"""

from __future__ import annotations

import functools
import itertools
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from trioforge.model import formulas, weapons
from trioforge.model.buffs import BuffSet
from trioforge.model.formulas import (
    ATTRIBUTES,
    POOLS_COUNTED,
    SCHOOLS,
    STAT_CAP,
    EvalProfile,
    PoolSpec,
    compile_profile,
    conv_end,
    conv_mana,
    effective_sta,
    fr,
    monk_curve,
    naked,
    pools_for,
)
from trioforge.model.roles import MELEE_CLASSES, ROLES, check_trio, roles_for, weights_for

__all__ = [
    "AA_CHOICES",
    "EVIDENCE_LEVELS",
    "FORMAT",
    "Profile",
    "eval_buffs",
    "fixed_pools",
    "haste_caps",
    "make_profile",
    "placements",
]

FORMAT = 1  # the version of the JSON shape
EVIDENCE_LEVELS = ("strict", "wiki")
AA_CHOICES = ("combat_stability", "natural_durability", "physical_enhancement")
FAMILIES = ("HP", "MANA", "END")
#: what ``haste.unbound_alacrity`` must say for this model: the haste it adds to a trio with a Monk (its cap is
#: ``haste.cap_pct_with_monk``, which already holds the other 10)
UNBOUND_ALACRITY_TEXT = "adds 10 haste and raises the cap by 10"
UNBOUND_ALACRITY_HASTE = 10
#: what ``haste.cap_pct`` and ``haste.cap_pct_with_monk`` must say for this model (:func:`~trioforge.model.formulas.haste_cap_at` implements them)
HASTE_CAP_TEXT = "max(level, 30) + 25 up to level 50 (75 at level 50), 85 for levels 51 to 59, 100 from level 60"
HASTE_CAP_MONK_TEXT = "the cap of the level plus the 10 that Unbound Alacrity adds (85 at level 50)"
_PLACEMENT_TEXT = {"on top of the capped sheet AC": "top", "inside X before the cap": "inside"}
_INPUTS = ("HP", "END", "WIS", "INT")  # the names of the pool inputs a range can be given for


# ---- numbers and containers ---------------------------------------------------------------------------


def _num(value: Any, name: str) -> int | float:
    """A finite number in its canonical form: a whole number is an int, any other a float. Never a bool."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)):
        raise ValueError(f"{name} must be a number, not {value!r}")
    if isinstance(value, Fraction):
        return int(value) if value.denominator == 1 else float(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number, not {value!r}")
        return int(value) if value.is_integer() else value
    return value


def _canon(value: Any, name: str) -> Any:
    """``value`` with every number in canonical form, mappings sorted and read-only, lists as tuples."""
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError(f"{name} has a key that is not text")
        return MappingProxyType({key: _canon(value[key], f"{name} {key}") for key in sorted(value)})
    if isinstance(value, (list, tuple)):
        return tuple(_canon(item, name) for item in value)
    if isinstance(value, (str, type(None))):
        return value
    return _num(value, name)


def _mapping(name: str, value: Any, keys: Sequence[str] | None = None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping, not {type(value).__name__}")
    if keys is not None and set(value) != set(keys):
        missing, extra = sorted(set(keys) - set(value)), sorted(set(value) - set(keys))
        raise ValueError(f"{name} must have exactly {', '.join(keys)} (missing {missing}, unexpected {extra})")
    return value


def _thaw(value: Any) -> Any:
    """Plain JSON data from a canonical value (the pool specs of ``pools`` are handled by the caller)."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _jnum(value: Fraction) -> int | float | str:
    """A pool number for JSON: an int, a float that reads back as the same fraction, else ``"p/q"``."""
    if value.denominator == 1:
        return int(value)
    approx = float(value)
    return approx if fr(approx) == value else f"{value.numerator}/{value.denominator}"


def _spec(entry: Any) -> PoolSpec:
    if isinstance(entry, PoolSpec):
        spec = entry
    elif isinstance(entry, Mapping):
        names = set(entry)
        if not {"cls", "base", "fac"} <= names or names - {"cls", "base", "fac", "stat"}:
            raise ValueError(f"a pool entry names cls, base and fac (and stat for mana), not {sorted(names)}")
        try:
            spec = PoolSpec(entry["cls"], entry["base"], entry["fac"], entry.get("stat"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"pool entry {dict(entry)!r}: {exc}") from exc
    else:
        raise ValueError(f"a pool entry is a PoolSpec or an object, not {type(entry).__name__}")
    if not isinstance(spec.cls, str) or not spec.cls:
        raise ValueError(f"a pool needs a class name, not {spec.cls!r}")
    return spec


def _spec_json(spec: PoolSpec) -> dict[str, Any]:
    entry: dict[str, Any] = {"cls": spec.cls, "base": _jnum(spec.base), "fac": _jnum(spec.fac)}
    if spec.stat is not None:
        entry["stat"] = spec.stat
    return entry


# ---- the buff totals ----------------------------------------------------------------------------------


def eval_buffs(totals: Mapping[str, Any]) -> dict[str, Any]:
    """Buff totals in the evaluator's shape: ``BuffSet.totals(...)`` read as ``evaluate`` and a profile take them.

    The buff engine writes ``sv`` and ``haste`` in lower case; the evaluator reads ``SV`` and ``HASTE``. A total of
    0 is left out (a missing key is 0 to the evaluator), so equal totals have one form. The evaluator's own shape
    passes through unchanged. Raises ``ValueError`` for an unknown key or school, a value that is not a number and
    a key given in both spellings.
    """
    if not isinstance(totals, Mapping):
        raise ValueError(f"buff totals must be a mapping, not {type(totals).__name__}")
    result: dict[str, Any] = {}
    seen: set[str] = set()
    for key, value in totals.items():
        name = {"sv": "SV", "haste": "HASTE"}.get(key, key)
        if name in seen:
            raise ValueError(f"buff total {name!r} is given twice (in both spellings)")
        seen.add(name)
        if name == "SV":
            _mapping("buff total SV", value)
            bad = sorted(set(value) - set(SCHOOLS))
            if bad:
                raise ValueError(f"unknown resist school {bad[0]!r} in the buff totals (use {' '.join(SCHOOLS)})")
            schools = {school: _num(amount, f"buff total SV {school}") for school, amount in value.items()}
            if any(schools.values()):
                result["SV"] = {school: amount for school, amount in schools.items() if amount != 0}
        elif name in formulas.BUFF_KEYS:
            amount = _num(value, f"buff total {name}")
            if amount != 0:
                result[name] = amount
        else:
            raise ValueError(f"unknown buff total {key!r} (use {' '.join(sorted(formulas.BUFF_KEYS))})")
    return result


# ---- the pool-selection data ----------------------------------------------------------------------------


def _span(name: Any, span: Any) -> tuple[Fraction, Fraction]:
    """A range ``(lowest, highest)`` of a pool input as exact fractions; it must run from 0 up."""
    try:
        low, high = (fr(end) for end in span)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"the range of {name!r} is (lowest, highest), not {span!r}") from exc
    if not 0 <= low <= high:
        raise ValueError(f"the range of {name!r} must run from 0 up, not {span!r}")
    return low, high


def _never_below(a: PoolSpec, b: PoolSpec, box: Mapping[str | None, tuple[Fraction, Fraction]]) -> bool:
    """Whether pool ``a`` is at least pool ``b`` at every point of the box. Exact."""
    (a_lo, a_hi), (b_lo, b_hi) = box[a.stat], box[b.stat]
    if a.stat == b.stat:  # one input: the difference is linear, so its ends decide
        return all(a.base + a.fac * u >= b.base + b.fac * u for u in (a_lo, a_hi))
    # two inputs that vary on their own: the worst case is a at its lowest and b at its highest
    return a.base + min(a.fac * a_lo, a.fac * a_hi) >= b.base + max(b.fac * b_lo, b.fac * b_hi)


def fixed_pools(
    pools: Sequence[PoolSpec], ranges: Mapping[str | None, Sequence[Any]], *, count: int = POOLS_COUNTED
) -> tuple[str, ...] | None:
    """The classes whose pools are the ``count`` largest at **every** point of the box ``ranges``, or None.

    ``pools`` are the pools of one family (:class:`~trioforge.model.formulas.PoolSpec`: ``base + fac x u`` of a
    converted input ``u``). ``ranges`` gives each input's ``(lowest, highest)`` in converted units, by input: the stat
    of a mana pool (``"WIS"`` or ``"INT"``) or ``None`` for the single input of HP and END pools. The answer is the
    first set of ``count`` pools, in trio order, that is never below any other pool anywhere in the box (equal pools
    are interchangeable); None means the pair can change, so the builder must select (it adds selection binaries). A
    family with no more than ``count`` pools has all of them. Raises ``ValueError`` for a range that does not run
    from 0 up, or that is missing for the input of a pool.
    """
    specs = tuple(_spec(pool) for pool in pools)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError(f"count must be a whole number of at least 1, not {count!r}")
    box = {key: _span(key, span) for key, span in ranges.items()}
    if len(specs) <= count:
        return tuple(spec.cls for spec in specs)
    for spec in specs:
        if spec.stat not in box:
            raise ValueError(f"no range given for the input {spec.stat!r} of the pool of {spec.cls}")
    for chosen in itertools.combinations(range(len(specs)), count):
        others = [specs[k] for k in range(len(specs)) if k not in chosen]
        if all(_never_below(specs[i], other, box) for i in chosen for other in others):
            return tuple(specs[i].cls for i in chosen)
    return None


# ---- the record -------------------------------------------------------------------------------------------


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r} in one object (parsers keep only the last)")
        result[key] = value
    return result


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a JSON number (use a finite number)")


@dataclass(frozen=True)
class Profile:
    """One scenario's constants (see the module docstring for every field).

    Build one with :func:`make_profile`; ``dataclasses.replace`` makes a variant, which is checked again. A profile is
    frozen and hashable, its mappings are read-only, and it reads back from :meth:`to_json` as an equal profile.
    Everything the evaluator needs is checked on construction by compiling it (:attr:`eval_profile`), so a ``Profile``
    that exists can be evaluated.
    """

    race: str
    trio: tuple[str, ...]
    level: int
    role: str
    evidence: str
    aa: Mapping[str, Any]
    naked: Mapping[str, Any]
    buff_totals: Mapping[str, Any]
    spell_haste: Any
    haste_cap: Any
    softcap: tuple[Any, Any]
    cs_pct: Any
    pe_pct: Any
    defense_cap: Any
    monk: Mapping[str, Any] | None
    iksar_ac: Any
    placement: Mapping[str, str]
    pools: Mapping[str, tuple[PoolSpec, ...]]
    caps: Mapping[str, Any]
    bands: Mapping[str, Any] | None
    dw_factor: Any
    weights: Mapping[str, Any]
    setups: tuple[str, ...]
    deity: str | None = None
    haste_bonus: Any = 0
    nd_pct: Any = 0
    ranged_factor: Any = 1
    stance: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        def put(name: str, value: Any) -> None:
            object.__setattr__(self, name, value)

        if not isinstance(self.race, str) or not self.race.strip():
            raise ValueError(f"race must be non-blank text, not {self.race!r}")
        put("trio", check_trio(self.trio))
        if type(self.level) is not int or self.level < 1:
            raise ValueError(f"level must be a whole number of at least 1, not {self.level!r}")
        if self.role not in ROLES:
            raise ValueError(f"role must be one of {', '.join(ROLES)}, not {self.role!r}")
        if self.evidence not in EVIDENCE_LEVELS:
            raise ValueError(f"evidence must be one of {', '.join(EVIDENCE_LEVELS)}, not {self.evidence!r}")
        aa = _mapping("aa", self.aa, AA_CHOICES)
        rank, durability, enhancement = aa["combat_stability"], aa["natural_durability"], aa["physical_enhancement"]
        if type(rank) is not int or rank < 0 or type(durability) is not int or durability < 0 or type(enhancement) is not bool:
            raise ValueError(
                "aa is a rank from 0 for combat_stability and for natural_durability and true or false for "
                f"physical_enhancement: {dict(aa)!r}"
            )
        put("aa", MappingProxyType({"combat_stability": rank, "natural_durability": durability, "physical_enhancement": enhancement}))
        _mapping("naked", self.naked, ATTRIBUTES)
        put("naked", _canon(self.naked, "naked"))
        put("buff_totals", _canon(eval_buffs(self.buff_totals), "buff_totals"))
        put("spell_haste", _num(self.spell_haste, "spell_haste"))
        if self.spell_haste < 0 or self.spell_haste < self.buff_totals.get("HASTE", 0):
            raise ValueError(
                f"spell_haste must be at least 0 and at least the haste of the always-on buffs, not {self.spell_haste!r}"
            )
        for name in ("haste_cap", "cs_pct", "pe_pct", "defense_cap", "iksar_ac", "dw_factor", "haste_bonus", "nd_pct", "ranged_factor"):
            put(name, _num(getattr(self, name), name))
        if self.haste_bonus < 0:
            raise ValueError(f"haste_bonus must be at least 0, not {self.haste_bonus!r}")
        if self.nd_pct < 0:
            raise ValueError(f"nd_pct must be at least 0, not {self.nd_pct!r}")
        if self.ranged_factor < 0:
            raise ValueError(f"ranged_factor must be at least 0, not {self.ranged_factor!r}")
        if self.stance is not None:
            stance = _mapping("stance", self.stance, ("agi_share", "swing_factor"))
            put("stance", _canon(stance, "stance"))
            if not (self.stance["swing_factor"] > 0 and 0 <= self.stance["agi_share"] <= 1):
                raise ValueError(f"stance is a swing_factor above 0 and an agi_share from 0 to 1, not {dict(stance)!r}")
        if not isinstance(self.softcap, (list, tuple)) or len(self.softcap) != 2:
            raise ValueError(f"softcap is (cap, rate past it), not {self.softcap!r}")
        put("softcap", (_num(self.softcap[0], "softcap"), _num(self.softcap[1], "softcap")))
        put("monk", None if self.monk is None else _canon(_mapping("monk", self.monk), "monk"))
        put("placement", _canon(_mapping("placement", self.placement), "placement"))
        pools = _mapping("pools", self.pools, FAMILIES)
        for family in FAMILIES:
            if isinstance(pools[family], (str, Mapping)) or not isinstance(pools[family], Sequence):
                raise ValueError(f"the {family} pool entry must be a list of pools")
        put("pools", MappingProxyType({family: tuple(_spec(entry) for entry in pools[family]) for family in sorted(pools)}))
        caps = _mapping("caps", self.caps, ("regen", "resist"))
        _mapping("caps regen", caps["regen"], ("HP", "MANA", "END"))
        put("caps", _canon(caps, "caps"))
        put("bands", None if self.bands is None else _canon(_mapping("bands", self.bands, ("breaks", "slopes")), "bands"))
        put("weights", _canon(_mapping("weights", self.weights), "weights"))
        setups = tuple(self.setups) if isinstance(self.setups, (list, tuple)) else None
        if setups is None or len(set(setups)) != len(setups) or not set(setups) <= set(weapons.SETUPS):
            raise ValueError(f"setups are different names from {', '.join(weapons.SETUPS)}, not {self.setups!r}")
        put("setups", setups)
        if self.deity is not None and (not isinstance(self.deity, str) or not self.deity.strip()):
            raise ValueError(f"deity is None or a name, not {self.deity!r}")
        try:
            self.eval_profile  # noqa: B018 - compiles the profile now: whatever the evaluator refuses is refused here
        except (KeyError, TypeError, AttributeError) as exc:  # a shape the checks above did not name
            raise ValueError(f"the evaluator cannot read this profile: {exc!r}") from exc

    def __repr__(self) -> str:
        return f"Profile({self.race} {'/'.join(self.trio)} level {self.level} {self.role})"

    # -- what the evaluator and the builder read ----------------------------------------------------------

    @functools.cached_property
    def eval_profile(self) -> EvalProfile:
        """This profile as the evaluator's own record (normalized to exact fractions). Pass it to ``evaluate``
        in a loop to skip the conversion."""
        return compile_profile(self)

    @property
    def spell_ac(self) -> Any:
        """The spell armor class of the always-on buffs."""
        return self.buff_totals.get("AC", 0)

    @property
    def effective_softcap(self) -> int:
        """The softcap the sheet uses: ``floor(cap x (100 + cs_pct + pe_pct) / 100)``, before any shield."""
        return math.floor(fr(self.softcap[0]) * (100 + fr(self.cs_pct) + fr(self.pe_pct)) / 100)

    def pool_choice(self, ranges: Mapping[str, Sequence[Any]] | None = None) -> dict[str, tuple[str, ...] | None]:
        """For each family, the pair of classes whose pools always count, or None where the builder must select.

        ``ranges`` gives some inputs' reachable ``(lowest, highest)`` in converted units (``"HP"``: effective STA;
        ``"END"``: the converted average; ``"WIS"`` and ``"INT"``: the converted stat); an input left out runs over its
        widest span, 0 up to what a stat at 510 converts to. See :func:`fixed_pools`.
        """
        given = dict(ranges or {})
        unknown = sorted(set(given) - set(_INPUTS))
        if unknown:
            raise ValueError(f"unknown input range {unknown[0]!r} (use {', '.join(_INPUTS)})")
        wide = conv_mana(STAT_CAP, self.bands)
        box = {"HP": (0, effective_sta(STAT_CAP)), "END": (0, conv_end(STAT_CAP)), "WIS": (0, wide), "INT": (0, wide)}
        box.update({name: _span(name, span) for name, span in given.items()})
        return {
            "HP": fixed_pools(self.pools["HP"], {None: box["HP"]}),
            "MANA": fixed_pools(self.pools["MANA"], {"WIS": box["WIS"], "INT": box["INT"]}),
            "END": fixed_pools(self.pools["END"], {None: box["END"]}),
        }

    # -- JSON, equality, hash -------------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON data: a ``format`` number, then every field in field order (pools as objects)."""
        data: dict[str, Any] = {"format": FORMAT}
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name == "pools":
                data["pools"] = {family: [_spec_json(spec) for spec in value[family]] for family in value}
            else:
                data[item.name] = _thaw(value)
        return data

    def to_json(self, indent: int | None = None) -> str:
        """The profile as JSON text. Equal profiles give one text; ``indent`` pretty-prints it."""
        if indent is None:
            return self._text
        return json.dumps(self.to_dict(), indent=indent)

    @functools.cached_property
    def _text(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Profile:
        """The profile of :meth:`to_dict` data. Strict: a missing or unknown key or another format is refused."""
        if not isinstance(data, Mapping):
            raise ValueError(f"a profile is a JSON object, not {type(data).__name__}")
        names = [item.name for item in fields(cls)]
        missing, unknown = sorted({"format", *names} - set(data)), sorted(set(data) - {"format", *names})
        if missing or unknown:
            raise ValueError(
                f"a profile has exactly the keys format, {', '.join(names)} (missing {missing}, unexpected {unknown})"
            )
        if data["format"] != FORMAT:
            raise ValueError(f"unsupported profile format {data['format']!r} (this reader knows format {FORMAT})")
        return cls(**{name: data[name] for name in names})

    @classmethod
    def from_json(cls, text: str) -> Profile:
        """The profile of :meth:`to_json` text. Refuses duplicate keys, NaN and Infinity as well as bad profiles."""
        return cls.from_dict(json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant))

    def __hash__(self) -> int:
        return hash(self._text)


# ---- the generator -------------------------------------------------------------------------------------------


def _placement(rules: Any, rule_id: str, level: int) -> str:
    text = rules.get(rule_id, level)
    if isinstance(text, str):
        for prefix, place in _PLACEMENT_TEXT.items():
            if text.startswith(prefix):
                return place
    raise ValueError(f"{rule_id} is {text!r}, but this model implements only {' and '.join(map(repr, _PLACEMENT_TEXT))}")


def placements(rules: Any, level: int) -> dict[str, str]:
    """Where the rules put the Monk worn-weight bonus and the Iksar racial armor class at ``level``: ``{"monk": ..., "iksar": ...}``, each ``"top"`` or ``"inside"``. What
    :func:`make_profile` gives a profile, and what a profile built by hand (the exporter's brute-force module) takes when it is given none."""
    return {
        "monk": _placement(rules, "monk.bonus_placement", level),
        "iksar": _placement(rules, "race.iksar_ac_placement", level),
    }


def _unbound_alacrity(rules: Any, level: int, codes: Sequence[str]) -> int:
    """The flat haste of Unbound Alacrity for a trio: 10 with a Monk, else 0. Refuses a rule that says anything else."""
    text = rules.get("haste.unbound_alacrity", level)
    if text != UNBOUND_ALACRITY_TEXT:
        raise ValueError(
            f"haste.unbound_alacrity is {text!r}, but this model implements only {UNBOUND_ALACRITY_TEXT!r}"
        )
    return UNBOUND_ALACRITY_HASTE if "MNK" in codes else 0


def _stance(rules: Any, level: int, codes: Sequence[str], role: str) -> dict[str, Any] | None:
    """The stance of a build: the Berserker stance (``stance.berserker``) for a build the rule lists, in a trio that has a Berserker; else None. Refuses a rule of another shape."""
    value = rules.get("stance.berserker", level)
    ok = isinstance(value, Mapping) and set(value) == {"swing_factor", "agi_counts", "builds"}
    if ok:
        factor, counts, builds = value["swing_factor"], value["agi_counts"], value["builds"]
        ok = (
            isinstance(factor, (int, float)) and not isinstance(factor, bool) and factor > 0 and isinstance(counts, bool)
            and isinstance(builds, list) and all(isinstance(build, str) and build in ROLES for build in builds)
        )  # fmt: skip
    if not ok:
        raise ValueError(
            f"stance.berserker is {value!r}, but this model implements only {{swing_factor: a number above 0, agi_counts: true or false, builds: a list of builds}}"
        )
    if "BER" not in codes or role not in value["builds"]:
        return None
    return {"swing_factor": value["swing_factor"], "agi_share": 1 if value["agi_counts"] else 0}


def _haste_cap(rules: Any, level: int, codes: Sequence[str]) -> int:
    """The haste cap of a trio at a level: the cap of the level, and with a Monk the haste Unbound Alacrity adds on top. Refuses a rule that says anything else than the texts it implements."""
    for rule_id, expected in (("haste.cap_pct", HASTE_CAP_TEXT), ("haste.cap_pct_with_monk", HASTE_CAP_MONK_TEXT)):
        text = rules.get(rule_id, level)
        if text != expected:
            raise ValueError(f"{rule_id} is {text!r}, but this model implements only {expected!r}")
    return formulas.haste_cap_at(level) + (UNBOUND_ALACRITY_HASTE if "MNK" in codes else 0)


def haste_caps(rules: Any, level: int) -> tuple[int, int]:
    """The haste cap at ``level`` of a trio with no Monk and of a trio with one (the 10 that Unbound Alacrity adds, :data:`UNBOUND_ALACRITY_HASTE`): the numbers
    :func:`make_profile` puts in a profile's ``haste_cap``, read by the same function, so that the exporter's constants cannot differ from the profile's."""
    return _haste_cap(rules, level, ()), _haste_cap(rules, level, ("MNK",))


def _rank(given: Mapping[str, Any], name: str, steps: Mapping[str, Any]) -> int:
    """The rank of the AA ``name`` in ``given`` (the top rank of ``steps``, the rule's ranks, when it is not given)."""
    top = max(int(rank) for rank in steps)
    rank = given.get(name, top)
    if type(rank) is not int or not 0 <= rank <= top:
        raise ValueError(f"aa: {name} is a whole number from 0 to {top}, not {rank!r}")
    return rank


def _aa(aa: Any, melee: bool, rules: Any, level: int) -> tuple[dict[str, Any], int | float, int | float, int | float]:
    """The AA state, ``cs_pct``, ``pe_pct`` and ``nd_pct`` of the choices ``aa`` (None: the defaults)."""
    steps = rules.get("ac.softcap.combat_stability_pct", level)  # rank -> the percent at that rank
    durability = rules.get("hp.natural_durability_pct", level)  # rank -> the percent of the HP from STA at that rank
    if aa is None:
        given: Mapping[str, Any] = {}
    elif isinstance(aa, Mapping):
        given = aa
    else:
        raise ValueError(f"aa is None or a mapping of {' and '.join(AA_CHOICES)}, not {aa!r}")
    unknown = sorted(set(given) - set(AA_CHOICES))
    if unknown:
        raise ValueError(f"aa has no choice {unknown[0]!r} (use {' and '.join(AA_CHOICES)})")
    rank = _rank(given, "combat_stability", steps)
    nd_rank = _rank(given, "natural_durability", durability)
    enhancement = given.get("physical_enhancement", melee or bool(rules.get("ac.softcap.pe_for_caster_only_trios", level)))
    if type(enhancement) is not bool:
        raise ValueError(f"aa: physical_enhancement is true or false, not {enhancement!r}")
    cs_pct = steps[str(rank)] if rank else 0
    nd_pct = durability[str(nd_rank)] if nd_rank else 0
    pe_pct = rules.get("ac.softcap.physical_enhancement_pct", level) if enhancement else 0
    return {"combat_stability": rank, "natural_durability": nd_rank, "physical_enhancement": enhancement}, cs_pct, pe_pct, nd_pct


def make_profile(
    race: str,
    trio: Sequence[str],
    level: int,
    role: str,
    buffset: BuffSet | None,
    aa: Mapping[str, Any] | None,
    tables: Any,
    rules: Any = None,
    *,
    evidence: str = "strict",
    deity: str | None = None,
    items: Iterable[Any] | None = None,
) -> Profile:
    """The :class:`Profile` of a scenario.

    ``buffset`` is the resolved buff set (``trioforge.model.buffs.resolve``) or None for no buffs; ``aa`` the AA
    choices or None for the defaults; ``tables`` the :class:`~trioforge.model.tables.Tables`; ``rules`` the rules
    (``tables.rules`` when None; another ``Rules`` object tries an alternative value). ``evidence`` and ``deity`` are
    recorded in the profile. ``items`` is the item pool the profile will be solved with, or None: only its shields and bows that
    the race can wear are read, to decide whether the ``1h-shield`` and ``ranged`` setups exist
    (:func:`~trioforge.model.weapons.shield_available`, :func:`~trioforge.model.weapons.bow_available`); the pool is not stored. Raises ``ValueError`` for a race, trio, level or role the tables or the role rules do not
    have, for AA choices or an evidence level that do not exist, and for a rule value this model does not implement.
    """
    rules = tables.rules if rules is None else rules
    codes = check_trio(trio)
    if type(level) is not int or level < 1:
        raise ValueError(f"level must be a whole number of at least 1, not {level!r}")
    raised = rules.get("ac.shield.offhand_raises_cap", level)
    if raised is not True:  # the sheet model (formulas.sheet_ac) adds the off-hand shield to the softcap
        raise ValueError(
            f"ac.shield.offhand_raises_cap is {raised!r}, but this model implements only a shield that raises the softcap"
        )
    absent = [code for code in codes if (code, level) not in tables.basedata or (code, level) not in tables.softcap]
    if absent:
        raise ValueError(f"the client tables have no level {level} row for {' '.join(absent)}")
    # only a shield or a bow the race can wear makes the shield or the bow setup: an item whose races exclude this one is not eligible
    wearable = None if items is None else [i for i in items if getattr(i, "races", None) is None or race in i.races]
    bow = wearable is not None and weapons.bow_available(codes, wearable, tables=tables, level=level)  # (with no pool there is no bow: it is never assumed)
    offered = roles_for(codes, bow=bow)  # (the Ranged role plays the bow and nothing else: a pool with no bow for the trio does not offer it)
    if role not in offered:
        raise ValueError(f"role {role!r} is not offered to {' '.join(codes)}; its roles are {', '.join(offered)}")

    pools = pools_for(codes, level, tables)
    aa_state, cs_pct, pe_pct, nd_pct = _aa(aa, bool(MELEE_CLASSES & set(codes)), rules, level)
    if nd_pct:  # Natural Durability: its percent goes on the factor of the HP that comes from STA, in every HP pool (the base and the 5 are not scaled)
        pools["HP"] = tuple(PoolSpec(spec.cls, spec.base, spec.fac * (100 + fr(nd_pct)) / 100) for spec in pools["HP"])
    softcap = (
        max(rules.get("ac.softcap.base_floor", level), *(tables.softcap[(code, level)][0] for code in codes)),
        max(rules.get("ac.softcap.rate_floor", level), *(tables.softcap[(code, level)][1] for code in codes)),
    )
    defense = [tables.skillcap[(code, "Defense", level)] for code in codes if (code, "Defense", level) in tables.skillcap]
    if not defense:
        raise ValueError(f"the client tables have no Defense skill cap at level {level} for {' '.join(codes)}")

    if buffset is None:
        totals, spell_haste = {}, 0
    elif isinstance(buffset, BuffSet):
        totals = eval_buffs(buffset.totals(()))
        spell_haste = max((buff.haste for buff in (*buffset.always_on, *buffset.optional)), default=0)
    else:
        raise ValueError(f"buffset is a BuffSet or None, not {type(buffset).__name__}")
    haste_bonus = _unbound_alacrity(rules, level, codes)
    haste_cap = _haste_cap(rules, level, codes)
    spell_haste += haste_bonus  # the weapon term assumes it too

    return Profile(
        race=race,
        trio=codes,
        level=level,
        role=role,
        evidence=evidence,
        aa=aa_state,
        naked=naked(race, codes, tables),
        buff_totals=totals,
        spell_haste=spell_haste,
        haste_cap=haste_cap,
        softcap=softcap,
        cs_pct=cs_pct,
        pe_pct=pe_pct,
        defense_cap=max(defense),
        monk=monk_curve(rules, level) if "MNK" in codes else None,
        iksar_ac=rules.get("race.iksar_ac_bonus", level) if race == "IKS" else 0,
        placement=placements(rules, level),
        pools=pools,
        caps={"regen": rules.get("regen.gear_caps", level), "resist": rules.get("resist.cap", level)},
        bands=rules.get("mana.wis_bands", level),
        dw_factor=weapons.dual_wield_factor_for(codes, rules, level),
        weights=weights_for(codes, role, rules, mana_reachable=bool(pools["MANA"])),
        setups=tuple(weapons.setups_for(codes, role, tables, level=level, items=wearable)),
        deity=deity,
        haste_bonus=haste_bonus,
        nd_pct=nd_pct,
        ranged_factor=rules.get("weapons.ranged_factor", level),
        stance=_stance(rules, level, codes, role),
    )
