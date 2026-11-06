"""The term cases of the exact evaluator: the reference values the JS port is held to, one regime of the formulas at a time.

``python -m trioforge.export.evaluate_terms --out fixtures/evaluate-terms.json`` writes ``fixtures/evaluate-terms.json``, which is
committed (``--check`` says whether the file is current). The random kits of the parity fixtures (``evaluate/``) hold the port to
Python on realistic kits; these cases hold it on the places where a mistake hides: invented profiles and kits that stand just
below, at and just above every knee, softcap, Monk bin and cap of :func:`trioforge.model.formulas.evaluate`, each with the exact
breakdown that Python gives (every exact number a reduced ``"p/q"`` string, as in the parity fixtures). Nothing in the file is
written by hand: the inputs come from this module and the expected values from the Python evaluator.

The document (``kind`` ``evaluate-terms``) holds

``terms``       by tag, what the cases of that tag are about (a case may have several tags)
``profiles``    the distinct profiles as ``Profile.to_dict()``, one to a line; a case names one by its position
``cases``       one to a line: ``id``, ``tags``, ``profile``, ``kit`` (``[place, item]`` for the places that hold an item, the place
                being the position in the 22 places of a kit; an item has the fields the evaluator reads: ``key``, ``stats``, ``sv``,
                ``haste``, ``weight10``, ``weapon`` and ``is_shield``), ``buffs`` (null: the profile's own buffs; else the ids chosen
                among the optional ones of ``buffset``), ``buffset`` (``{"set", "table"}`` as the bundle writes them, or null),
                ``setup``, ``haste`` (the haste the weapon term assumes, a number) and the ``breakdown`` Python gave

The profiles are those of three real trios at the current level (a Monk with a WIS and an INT caster, three casters of both stats,
three melee classes with no mana), changed one field at a time with ``dataclasses.replace`` (which checks the profile again), and
some are written out. The Monk curve, the pools and the softcap are the rules' and the client tables'; the items, the buffs and
every number that stands beside a knee are invented. Item keys start with ``it``, which no catalog key does.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

from trioforge.classes import CLASS_CODES
from trioforge.export.fixture_cases import breakdown_json, buffset_from_doc, eval_totals_for
from trioforge.model import formulas as fm
from trioforge.model.items import SLOT_INSTANCES, ItemVec, WeaponVec
from trioforge.model.profile import Profile, make_profile
from trioforge.model.tables import REPO
from trioforge.model.tables import load as load_tables

__all__ = ["PATH", "TERMS", "build", "main", "render"]

FORMAT = 1
KIND = "evaluate-terms"
PATH = REPO / "fixtures" / "evaluate-terms.json"
ATTRIBUTES = fm.ATTRIBUTES
STEPS = (99, 100, 101, 199, 200, 201, 202, 254, 255, 256, 509, 510, 511)  # the totals beside the knees 100, 200, 201, 255, 510

TERMS = {
    "attributes-alike": "all seven attributes at one total, on both sides of every knee (99 to 511), with every weight on",
    "attributes-rotated": "the seven attributes at different totals, so that each of them stands at every knee in turn",
    "knee-100": "totals of 99, 100 and 101: the first band of WIS and INT (mana) and of the END average",
    "knee-200": "totals of 199, 200 and 201: the second band of WIS and INT (mana)",
    "knee-201": "totals of 200, 201 and 202: the second band of the END average (352.5 at 201)",
    "knee-255": "totals of 254, 255 and 256: the stat knee (STA for HP, DEX past a tenth); the WIS and INT curve does not bend there",
    "knee-510": "totals of 509, 510 and 511: the cap of every stat, and of each stat in the END average",
    "end": "the END average of STR, STA, DEX and AGI (each counted to 510), beside 100 and 201, between whole numbers, below 0",
    "mixed-mana": "WIS and INT pools together: which two pools count flips with the stats, and a tie keeps the trio's order",
    "mana-wis-curve": "two WIS pools (Cleric and Shaman) at WIS 200, 255, 270, 280 and 510: the curve runs at one slope from 200 to 510 (the in-game reading behind mana.wis_bands)",
    "mana-none": "a trio with no mana class has no mana, whatever its items give",
    "bands-default": "a profile with no bands of its own reads the rule's bands for WIS and INT",
    "bands-custom": "a profile with bands of its own (three breaks, four slopes)",
    "pool-order": "HP and END pools that cross and tie: the two largest count, a tie in the order of the trio",
    "softcap": "the sheet armor class with no shield, below, at and above the softcap, for each rate past it",
    "softcap-shield": "the same with a shield in the off hand: it adds to X and to the softcap",
    "shield-not-offhand": "a shield in an Any place and a plain item in the off hand are worn armor class, not the shield",
    "monk": "the Monk bonus beside every bin edge (whole stones of worn weight), on top and inside, and past the table",
    "iksar": "the racial armor class on top of the cap and inside X, with and without a Monk",
    "haste": "spell haste and the best worn haste against the cap: the worn haste counts what room is left",
    "regen": "gear regen up to its cap, buff regen outside it",
    "resists": "gear and buff resists up to the cap, a school's own weight against the general one",
    "weapons": "weapon damage by setup and hand: a listed bonus, none and 0, one hander and two hander, haste assumed",
    "buffs": "buffs chosen among the optional ones: none, one, the best haste of several, a duplicate, an always-on id",
    "decimals": "profile numbers that are not whole: decimals, a pool number that only p/q can write",
    "limits": "the largest numbers held exactly: 22 items at 2^40 in every stat, weights up to 2^53 - 1, a weight in exponent notation",
    "empty": "an empty kit",
    "natural-durability": "the HP pools of a profile with Natural Durability at ranks 0 to 4 (0, 2, 5, 10 and 12 percent of the HP from STA), STA below, at and past the knee and the cap, with flat item HP that the AA does not scale",
}


# ---- the building blocks ------------------------------------------------------------------------------------------------


def _place(name: str, nth: int = 0) -> int:
    """The position in a kit of the ``nth`` place of a slot group."""
    return [index for index, group in enumerate(SLOT_INSTANCES) if group == name][nth]


def _item(
    key: str, *, stats: Mapping[str, int] | None = None, sv: Mapping[str, int] | None = None, haste: int = 0, weight10: int = 10,
    weapon: WeaponVec | None = None, shield: bool = False,
) -> ItemVec:
    """An invented item: a key that starts with ``it``, the fields the evaluator reads, the rest filled in."""
    return ItemVec(
        key=key, name=key, slots=frozenset({"ANY"}), classes=frozenset(CLASS_CODES), deity=None, lore=False,
        stats={name: value for name, value in (stats or {}).items() if value}, sv={k: v for k, v in (sv or {}).items() if v},
        haste=haste, weight10=weight10, weapon=weapon, is_shield=shield, tier=0,
    )  # fmt: skip


def _item_json(item: ItemVec) -> dict[str, Any]:
    weapon = item.weapon
    return {
        "key": item.key, "stats": dict(item.stats), "sv": dict(item.sv), "haste": item.haste, "weight10": item.weight10,
        "weapon": None if weapon is None else {
            "skill": weapon.skill, "dmg": weapon.dmg, "delay": weapon.delay, "bonus": weapon.bonus, "two_handed": weapon.two_handed
        },
        "is_shield": item.is_shield,
    }  # fmt: skip


def _text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


class _Cases:
    """The profiles and cases of a build, each case valued by the Python evaluator as it is added."""

    def __init__(self) -> None:
        self.profiles: list[dict[str, Any]] = []
        self.cases: list[dict[str, Any]] = []
        self._index: dict[str, int] = {}
        self._count: dict[str, int] = {}

    def add(
        self, tags: Sequence[str], profile: Profile, kit: Mapping[int, ItemVec], *, buffs: Sequence[int] | None = None,
        buffset: Mapping[str, Any] | None = None, setup: str | None = None, haste: float = 0,
    ) -> None:
        unknown = [tag for tag in tags if tag not in TERMS]
        if unknown:
            raise ValueError(f"unknown term {unknown[0]!r}")
        document = profile.to_dict()
        text = _text(document)
        if text not in self._index:
            self._index[text] = len(self.profiles)
            self.profiles.append(document)
        places: list[ItemVec | None] = [None] * len(SLOT_INSTANCES)
        for index, item in kit.items():
            places[index] = item
        totals = None if buffs is None else eval_totals_for(buffset_from_doc(buffset), buffs)
        breakdown = fm.evaluate(profile, places, totals, setup=setup, haste_assumed=haste)
        number = self._count[tags[0]] = self._count.get(tags[0], 0) + 1
        self.cases.append(
            {
                "id": f"{tags[0]}-{number:03d}", "tags": list(tags), "profile": self._index[text],
                "kit": [[index, _item_json(item)] for index, item in sorted(kit.items())],
                "buffs": None if buffs is None else list(buffs), "buffset": None if buffs is None else buffset, "setup": setup,
                "haste": haste, "breakdown": breakdown_json(breakdown),
            }
        )  # fmt: skip


def _gear(profile: Profile, **targets: int) -> dict[str, int]:
    """The item stats that bring the attribute totals of ``profile`` to ``targets`` (the others stay where they are)."""
    return {
        stat: total - profile.naked[stat] - profile.buff_totals.get(stat, 0) for stat, total in targets.items()
    }  # fmt: skip


def _weights(**given: float) -> dict[str, float]:
    return dict(given)


def _same(profile: Profile, **changes: Any) -> Profile:
    return dataclasses.replace(profile, **changes)


# ---- the cases ----------------------------------------------------------------------------------------------------------------


def _attribute_cases(out: _Cases, base: Profile) -> None:
    """Every attribute at every total beside a knee: all alike, and then rotated so that each stands at each in turn."""
    knees = {
        "knee-100": (99, 100, 101), "knee-200": (199, 200, 201), "knee-201": (200, 201, 202), "knee-255": (254, 255, 256),
        "knee-510": (509, 510, 511),
    }  # fmt: skip

    def tags_for(totals: Sequence[int], kind: str) -> list[str]:
        found = [knee for knee, around in knees.items() if set(totals) & set(around)]
        return [kind, *found, *(["end"] if kind == "attributes-alike" and totals[0] in (99, 100, 101, 200, 201, 202) else [])]

    for total in (*STEPS, 0, -7):
        targets = dict.fromkeys(ATTRIBUTES, total)
        out.add(
            tags_for([total], "attributes-alike"), base, {_place("CHEST"): _item("itterm-alike", stats=_gear(base, **targets))}
        )
    for turn in range(len(STEPS)):
        targets = {stat: STEPS[(turn + 3 * position) % len(STEPS)] for position, stat in enumerate(ATTRIBUTES)}
        out.add(
            tags_for(list(targets.values()), "attributes-rotated"), base,
            {_place("CHEST"): _item("itterm-rotated", stats=_gear(base, **targets))},
        )  # fmt: skip


def _end_cases(out: _Cases, base: Profile) -> None:
    """The END average: beside 100 and 201, between whole numbers, a stat past its cap, a stat below 0, flat END."""
    weights = _weights(END=1, ENDREG=0, HP=0)
    profile = _same(base, weights=weights)
    fours = [
        (100, 100, 100, 101), (200, 200, 200, 203), (201, 201, 201, 202), (600, 100, 100, 100), (510, 510, 510, 510),
        (700, 700, 700, 700), (-50, 100, 100, 100), (-1000, 100, 100, 100), (90, 110, 130, 200),
    ]  # (STR, STA, DEX, AGI): between whole averages, past the cap of a stat, below 0
    for strength, stamina, dexterity, agility in fours:
        gear = _gear(profile, STR=strength, STA=stamina, DEX=dexterity, AGI=agility)
        tags = ["end"]
        if min(strength, stamina, dexterity, agility) >= 100 and max(strength, stamina, dexterity, agility) <= 101:
            tags.append("knee-100")
        if 200 <= min(strength, stamina, dexterity, agility) and max(strength, stamina, dexterity, agility) <= 203:
            tags.append("knee-201")
        out.add(tags, profile, {_place("CHEST"): _item("itterm-end", stats=gear)})
    flat = _same(base, weights=_weights(END=1), buff_totals={"END": 20})
    gear = {**_gear(flat, STR=150, STA=150, DEX=150, AGI=150), "END": 30}  # flat END from the item and from the buffs
    out.add(["end"], flat, {_place("CHEST"): _item("itterm-end-flat", stats=gear)})
    gear = _gear(profile, STR=511, STA=300, DEX=0, AGI=250)
    out.add(["end"], profile, {_place("CHEST"): _item("itterm-end-big", stats=gear)})


def _mana_cases(out: _Cases, casters: Profile, monk: Profile, melee: Profile, wis_pair: Profile) -> None:
    """WIS and INT pools: the pairs that flip which two of three pools count, a tie, a trio with no mana, the bands."""
    weights = _weights(MANA=1)
    mixed = _same(casters, weights=weights)
    pairs = [
        (150, 120), (150, 210), (210, 150), (255, 255), (300, 100), (100, 300), (510, 511), (511, 510), (-5, 400), (200, 200),
    ]  # (WIS, INT)
    for wis, int_ in pairs:
        gear = _gear(mixed, WIS=wis, INT=int_)
        out.add(["mixed-mana"], mixed, {_place("CHEST"): _item("itterm-mana", stats=gear)})
    two = _same(monk, weights=weights)  # a WIS pool and an INT pool
    for wis, int_ in ((100, 200), (255, 90), (510, 510)):
        out.add(["mixed-mana"], two, {_place("CHEST"): _item("itterm-mana-two", stats=_gear(two, WIS=wis, INT=int_))})
    both = _same(wis_pair, weights=weights)  # two WIS pools: the trio of the in-game reading
    for wis in (200, 255, 270, 280, 510):
        out.add(["mana-wis-curve"], both, {_place("CHEST"): _item("itterm-wis-curve", stats=_gear(both, WIS=wis))})
    flat = _same(mixed, weights=_weights(MANA=1), buff_totals={"MANA": 25})
    gear = {**_gear(flat, WIS=180, INT=240), "MANA": 70}  # flat mana from the item and from the buffs
    out.add(["mixed-mana"], flat, {_place("CHEST"): _item("itterm-mana-flat", stats=gear)})
    bare = _same(melee, weights=_weights(MANA=1, MANAREG=1))
    gear = {"MANA": 500, "MANAREG": 7, "WIS": 200}
    out.add(["mana-none"], bare, {_place("CHEST"): _item("itterm-no-mana", stats=gear)})
    out.add(["mana-none"], bare, {})
    default = _same(mixed, bands=None)
    custom = _same(mixed, bands={"breaks": [50, 150, 300], "slopes": [2, 1.5, 0.75, 0.25]})
    for wis, int_ in ((49, 151), (50, 150), (299, 300)):
        for tag, profile in (("bands-default", default), ("bands-custom", custom)):
            out.add([tag], profile, {_place("CHEST"): _item("itterm-bands", stats=_gear(profile, WIS=wis, INT=int_))})


def _pool_cases(out: _Cases, base: Profile) -> None:
    """Pools that cross (HP at STA' 200, 250 and 300, END at an average of 166 and two thirds) and that tie."""
    pools = {
        "HP": (fm.PoolSpec("WAR", 1000, 6), fm.PoolSpec("CLR", 1500, 4), fm.PoolSpec("ENC", 1200, 5)),
        "MANA": (),
        "END": (
            fm.PoolSpec("WAR", 500, 3), fm.PoolSpec("CLR", 800, 1.5), fm.PoolSpec("ENC", 500, 3), fm.PoolSpec("BER", 600, 2.25)
        ),
    }  # fmt: skip
    profile = _same(base, pools=pools, weights=_weights(HP=1, END=1))
    for stamina in (0, 100, 200, 249, 250, 251, 345, 600):  # STA' 345 is 300: CLR and ENC tie
        gear = _gear(profile, STA=stamina, STR=0, DEX=0, AGI=0)
        out.add(["pool-order"], profile, {_place("CHEST"): _item("itterm-pools", stats=gear)})
    for average in (0, 100, 130, 139, 140, 141, 150, 250):  # the END pools meet at an average of 140
        gear = _gear(profile, STA=average, STR=average, DEX=average, AGI=average)
        out.add(["pool-order"], profile, {_place("CHEST"): _item("itterm-pools-end", stats=gear)})


def _durability_cases(out: _Cases, make: Any) -> None:
    """Natural Durability: the percent is in the ``fac`` of the HP pools of the profile, so the evaluator must give HP from STA with it and flat HP without it.

    ``make(trio, rank)`` is the profile of a trio with the AA at ``rank``. Each rank is valued at STA totals below the knee, at it and past it and past the cap
    (STA' stops at 510), with an item of flat HP in another place; one case has no flat HP, and a trio of three casters has pools that cross.
    """
    melee = ("WAR", "ROG", "BER")
    for rank in range(5):
        profile = _same(make(melee, rank), weights=_weights(HP=1))
        for stamina in (100, 255, 300, 600):
            gear = _gear(profile, STA=stamina, STR=0, DEX=0, AGI=0)
            out.add(
                ["natural-durability"], profile,
                {_place("CHEST"): _item("itnd-sta", stats=gear), _place("FEET"): _item("itnd-hp", stats={"HP": 250})},
            )  # fmt: skip
    profile = _same(make(melee, 4), weights=_weights(HP=1))
    out.add(["natural-durability"], profile, {_place("CHEST"): _item("itnd-sta-only", stats=_gear(profile, STA=300, STR=0, DEX=0, AGI=0))})
    for rank in (0, 4):
        profile = _same(make(("CLR", "SHD", "ENC"), rank), weights=_weights(HP=1))
        for stamina in (200, 300):
            out.add(["natural-durability"], profile, {_place("CHEST"): _item("itnd-casters", stats=_gear(profile, STA=stamina, STR=0, DEX=0, AGI=0))})


def _sheet_cases(out: _Cases, base: Profile) -> None:
    """The sheet armor class: X against the softcap Y, with and without a shield, and the rest of X."""
    plain = _same(
        base, naked=dict.fromkeys(ATTRIBUTES, 0), softcap=(400, 0.33), cs_pct=0, pe_pct=0, defense_cap=0, buff_totals={},
        weights=_weights(AC=6), monk=None, iksar_ac=0,
    )  # X is 4/3 of the worn armor class and nothing else: it meets the softcap of 400 at 300
    for rate in (0.33, 0, 1):
        profile = _same(plain, softcap=(400, rate))
        for worn in (0, 100, 299, 300, 301, 350, 600) if rate == 0.33 else (299, 300, 301, 350):
            out.add(["softcap"], profile, {_place("CHEST"): _item("itterm-armor", stats={"AC": worn})})
    shielded = _same(plain, softcap=(424, 0.33))  # with a shield of 28 the softcap is 452 and X meets it at 311
    def with_shield(worn: int, shield: int) -> dict[int, ItemVec]:
        return {
            _place("CHEST"): _item("itterm-armor", stats={"AC": worn}),
            _place("SECONDARY"): _item("itterm-shield", stats={"AC": shield}, shield=True),
        }

    for worn in (100, 310, 311, 312, 400):
        out.add(["softcap-shield"], shielded, with_shield(worn, 28))
    for rate in (0, 1):
        out.add(["softcap-shield"], _same(shielded, softcap=(424, rate)), with_shield(350, 50))
    on_chest = {_place("CHEST"): _item("itterm-armor", stats={"AC": 350})}
    in_any = _item("itterm-shield-any", stats={"AC": 28}, shield=True)
    out.add(["shield-not-offhand"], shielded, {**on_chest, _place("ANY"): in_any})
    out.add(["shield-not-offhand"], shielded, {**on_chest, _place("SECONDARY"): _item("itterm-offhand", stats={"AC": 28})})
    # the rest of X: the defense skill, the spell armor class, AGI (counted to 510, and below 0), and the softcap's own floor
    rest = _same(
        plain, defense_cap=230, buff_totals={"AC": 275}, softcap=(392, 0.33), cs_pct=10, pe_pct=2, weights=_weights(AC=6, DEX=1)
    )
    for agility in (-40, 0, 400, 510, 600):
        out.add(["softcap"], rest, {_place("CHEST"): _item("itterm-armor", stats={"AC": 280, "AGI": agility})})
    for softcap, cs, pe in ((33, 10, 2), (100, 3, 0), (391, 10, 2), (392, 0, 0), (448, 10, 2)):
        profile = _same(rest, softcap=(softcap, 0.5), cs_pct=cs, pe_pct=pe)  # floor(softcap x (100 + cs + pe) / 100)
        out.add(["softcap"], profile, {_place("CHEST"): _item("itterm-armor", stats={"AC": 250})})


def _monk_cases(out: _Cases, monk: Profile, iksar: int) -> None:
    """The Monk bonus beside every edge of the bins (a bin is a whole stone: ten tenths), on top and inside, and past the table."""
    curve = dict(monk.monk or {})
    soft, hard = curve["softcap_stones"], curve["hardcap_stones"]
    bins = hard + 100  # the table has one bin to each whole stone up to this
    stones = [0, soft, soft + 1, hard - 2, hard - 1, hard, hard + 1, hard + 2, bins, bins + 1, 400]
    tenths = sorted({t for stone in stones for t in (10 * stone - 1, 10 * stone, 10 * stone + 1) if t >= 0})
    on_top = _same(
        monk, weights=_weights(AC=6), cs_pct=0, pe_pct=0, buff_totals={}, naked=dict.fromkeys(ATTRIBUTES, 0), iksar_ac=0
    )  # the armor class term only: the sheet of a kit with 100 worn armor class, and the bonus on top
    for weight in tenths:
        out.add(["monk"], on_top, {_place("CHEST"): _item("itterm-weight", stats={"AC": 100}, weight10=weight)})
    inside = _same(on_top, placement={"monk": "inside", "iksar": "top"})
    for weight in (0, 170, 360, 1360):
        for worn in (100, 300):  # X below the softcap, and above it, where the bonus counts a third as much
            out.add(["monk"], inside, {_place("CHEST"): _item("itterm-weight", stats={"AC": worn}, weight10=weight)})
    alternative = _same(on_top, monk={**curve, "full_until_stones": 34})  # the full bonus up to 34 whole stones
    for weight in (0, 339, 340, 359, 360):
        out.add(["monk"], alternative, {_place("CHEST"): _item("itterm-weight", stats={"AC": 100}, weight10=weight)})
    both = _same(on_top, placement={"monk": "inside", "iksar": "inside"}, iksar_ac=iksar)  # and the racial bonus inside as well
    out.add(["monk"], both, {_place("CHEST"): _item("itterm-weight", stats={"AC": 100}, weight10=500)})


def _iksar_cases(out: _Cases, monk: Profile, melee: Profile, bonus: int) -> None:
    """The racial armor class on top of the cap and inside X, with and without a Monk, below the softcap and above it."""
    for base, label in ((melee, "melee"), (monk, "monk")):
        for iksar in ("top", "inside"):
            profile = _same(
                base, race="IKS", iksar_ac=bonus, placement={"monk": "top", "iksar": iksar}, weights=_weights(AC=6, HP=1),
                softcap=(392, 0.33), cs_pct=10, pe_pct=2,
            )
            for worn in (100, 300) if base is monk else (300,):
                out.add(["iksar"], profile, {_place("CHEST"): _item(f"itterm-{label}", stats={"AC": worn}, weight10=200)})
    placement = {"monk": "inside", "iksar": "inside"}
    both = _same(monk, race="IKS", iksar_ac=bonus, placement=placement, weights=_weights(AC=6), softcap=(392, 0.33))
    out.add(["iksar"], both, {_place("CHEST"): _item("itterm-monk", stats={"AC": 300}, weight10=200)})


def _haste_cases(out: _Cases, melee: Profile, monk: Profile) -> None:
    """Spell haste against the cap, and the best worn haste in what room is left (75, or 85 with a Monk, whose Unbound
    Alacrity adds 10 to the spell haste: with no spell haste and no worn haste a Monk's trio counts 10)."""
    for base in (melee, monk):
        cap = int(base.haste_cap)
        for spell in (0, 60, cap, cap + 5) if base is melee else (0, 45, cap - 11, cap - 1, cap):
            profile = _same(
                base, buff_totals={"HASTE": spell} if spell else {}, spell_haste=spell + base.haste_bonus, weights=_weights(HASTE=2)
            )
            for worn in (0, 10, 30, 100) if base is melee else (0, 30):
                kit = {
                    _place("CHEST"): _item("itterm-haste", haste=worn),
                    _place("HEAD"): _item("itterm-haste-low", haste=min(worn, 7)),  # only the best worn haste counts
                }
                out.add(["haste"], profile, kit)


def _regen_resist_cases(out: _Cases, base: Profile) -> None:
    """Gear regen up to 30, 15 and 15, buff regen outside the caps; gear and buff resists up to 200, a school's own weight."""
    profile = _same(
        base, weights=_weights(HPREG=2, MANAREG=3, ENDREG=5), buff_totals={"HPREG": 4, "MANAREG": 2, "ENDREG": 1}, spell_haste=0
    )
    for hp, mana, end in ((0, 0, 0), (14, 15, 16), (29, 40, 15), (30, 5, 14), (31, 6, 40), (45, 100, 100), (-3, -3, -3)):
        gear = {"HPREG": hp, "MANAREG": mana, "ENDREG": end}
        out.add(["regen"], profile, {_place("CHEST"): _item("itterm-regen", stats=gear)})
    schools = _same(
        base, weights=_weights(SV=0.5, SV_FIRE=1.5, SV_MAGIC=0.25), buff_totals={"SV": {"FIRE": 40, "COLD": 40, "DISEASE": 40}}
    )
    for fire, cold, magic, poison, disease in (
        (0, 0, 0, 0, 0), (100, 159, 199, 200, 201), (159, 160, 161, 150, 5), (300, 1, 2, 3, 4), (-30, -30, -30, -30, -30),
    ):  # fmt: skip
        stats = {"FIRE": fire, "COLD": cold, "MAGIC": magic, "POISON": poison, "DISEASE": disease, "CORRUPTION": 90}
        out.add(["resists"], schools, {_place("CHEST"): _item("itterm-resists", sv=stats)})
    general = _same(base, weights=_weights(SV=0.5))
    out.add(["resists"], general, {_place("CHEST"): _item("itterm-resists", sv={"FIRE": 199, "COLD": 200, "MAGIC": 201})})


def _weapon_cases(out: _Cases, base: Profile) -> None:
    """Weapon damage: each setup against the hands that fill it, with and without a listed bonus, at three assumed hastes."""
    one = WeaponVec("1H Slashing", 20, 30, None, False)
    listed = WeaponVec("1H Piercing", 24, 28, 25, False)
    zero = WeaponVec("1H Blunt", 18, 36, 0, False)
    two = WeaponVec("2H Slashing", 40, 60, None, True)
    two_listed = WeaponVec("2H Blunt", 52, 72, 50, True)
    two_zero = WeaponVec("2H Piercing", 44, 66, 0, True)
    odd = [WeaponVec("1H Slashing", 0, 30, None, False), WeaponVec("1H Slashing", 20, 0, None, False)]
    shield = _item("itterm-shield", stats={"AC": 20}, shield=True)

    def hands(main: WeaponVec | None, off: WeaponVec | ItemVec | None) -> dict[int, ItemVec]:
        kit: dict[int, ItemVec] = {}
        if main is not None:
            kit[_place("PRIMARY")] = _item("itterm-main", weapon=main)
        if isinstance(off, ItemVec):
            kit[_place("SECONDARY")] = off
        elif off is not None:
            kit[_place("SECONDARY")] = _item("itterm-off", weapon=off)
        return kit

    kits = [
        hands(one, shield), hands(listed, shield), hands(zero, one), hands(two, None), hands(two_listed, None), hands(two_zero, None),
        hands(one, one), hands(listed, zero), hands(one, two), hands(two, one),
    ]  # a bonus listed as 0 is no bonus: the hand scores as if none were listed
    profile = _same(base, weights=_weights(DMG=1000), dw_factor=0.8)
    for setup in ("1h-shield", "2h", "dw"):  # a setup scores the hands that fill it and no others
        for kit in kits:
            out.add(["weapons"], profile, kit, setup=setup, haste=25)
    for kit in (hands(None, one), hands(odd[0], one), hands(one, odd[1])):  # no main hand, no damage, no delay
        out.add(["weapons"], profile, kit, setup="dw", haste=25)
    for setup in (None, "stick"):  # and these two score nothing
        for kit in (kits[0], kits[4]):
            out.add(["weapons"], profile, kit, setup=setup, haste=25)
    for haste in (0, 12.5, 100):  # the haste the weapon term assumes, and the share of the second hand
        out.add(["weapons"], profile, hands(listed, one), setup="dw", haste=haste)
        out.add(["weapons"], profile, hands(listed, shield), setup="1h-shield", haste=haste)
        out.add(["weapons"], profile, hands(two_listed, None), setup="2h", haste=haste)
    for dw in (1, 0.5):
        out.add(["weapons"], _same(profile, dw_factor=dw), hands(listed, one), setup="dw", haste=25)
    bow = _item("itterm-bow", weapon=WeaponVec("Archery", 30, 40, None, False))
    ranged = {**hands(one, one), _place("RANGE"): bow, _place("ANY"): _item("itterm-any", weapon=one)}
    for setup in ("dw", "1h-shield"):  # only the primary and the secondary place are weapons
        out.add(["weapons"], profile, ranged, setup=setup, haste=25)


BUFFSET = {
    "set": {
        "always_on": [901, 902, 906], "optional": [903, 904, 905], "conflicts": [], "cliques": [],
        "cardinality": None, "dropped": [],
    },
    "table": {
        "901": {"name": "Invented Aegis", "classes": {"SHM": 10}, "vec": {"AC": 20, "HP": 100}, "source": "own"},
        "902": {"name": "Invented Haste One", "classes": {"SHM": 20}, "vec": {"STR": 10, "HASTE": 15}, "source": "own"},
        "903": {"name": "Invented Haste Two", "classes": {"SHM": 30}, "vec": {"HASTE": 30, "FIRE": 20}, "source": "own"},
        "904": {
            "name": "Invented Haste Three", "classes": {"SHM": 40}, "vec": {"HASTE": 25, "COLD": 15, "ATK": 5}, "source": "own"
        },
        "905": {"name": "Invented Vigor", "classes": {"SHM": 5}, "vec": {"STA": 12, "MANA": 100, "HPREG": 3}, "source": "own"},
        "906": {"name": "Invented Haste Zero", "classes": {"SHM": 1}, "vec": {"HASTE": 10, "INT": 4}, "source": "own"},
    },
}  # fmt: skip


def _buff_cases(out: _Cases, monk: Profile) -> None:
    """Buffs chosen among the optional ones of a small invented set (three always on, two of them with haste, of which only the
    best counts; three to choose from)."""
    totals = eval_totals_for(buffset_from_doc(BUFFSET), [])
    own = {key: value for key, value in totals.items() if key not in ("SV", "HASTE") and value}
    profile = _same(
        monk, weights=_weights(AC=6, HP=1, MANA=1, HASTE=2, HPREG=3, ATK=1), buff_totals={**own, "HASTE": totals["HASTE"]},
        spell_haste=30,
    )  # its own buffs are the always-on ones of the set
    kit = {_place("CHEST"): _item("itterm-buffs", stats={"AC": 90}), _place("HEAD"): _item("itterm-haste", haste=40)}
    for chosen in (None, [], [903], [904], [903, 904], [905, 905], [901, 905], [904, 905, 903], [901, 902, 903, 904, 905, 906]):
        out.add(["buffs"], profile, kit, buffs=chosen, buffset=BUFFSET)


def _decimal_cases(out: _Cases, base: Profile) -> None:
    """Profile numbers that are not whole: decimals in the stats, the sheet, the pools, the weights and the buffs."""
    pools = {
        "HP": (fm.PoolSpec("WAR", Fraction(1, 3), Fraction(7, 3)), fm.PoolSpec("CLR", 1320.5, 4.4)),
        "MANA": (fm.PoolSpec("CLR", 900, Fraction(9, 2), "WIS"), fm.PoolSpec("SHD", 450.25, 4.5, "INT")),
        "END": (fm.PoolSpec("WAR", 900, 4.5), fm.PoolSpec("CLR", Fraction(2, 3), Fraction(13, 4))),
    }  # a pool number that a float cannot carry is written "1/3"
    profile = _same(
        base, naked={"STR": 90.5, "STA": 91.25, "AGI": 79.75, "DEX": 85, "WIS": 100.5, "INT": 99.25, "CHA": 70},
        buff_totals={"AC": 2.5, "STA": 3.25, "HP": 10.5, "HASTE": 12.5}, spell_haste=12.5, softcap=(391.5, 0.125), cs_pct=7.5,
        pe_pct=1.25, defense_cap=230.5, haste_cap=77.5, iksar_ac=34.5, dw_factor=0.65, pools=pools,
        weights=_weights(
            HP=0.015625, MANA=0.1, END=1.1, AC=2.9, ATK=1.7666666666666666, DEX=0.3333333333333333, CHA=0.05, HASTE=1.5
        ),
    )
    for stamina, wis in ((100, 100), (255, 200), (400, 255)):
        stats = {"AC": 301, "STA": stamina, "WIS": wis, "DEX": 200, "ATK": 7}
        out.add(["decimals"], profile, {_place("CHEST"): _item("itterm-decimals", stats=stats, haste=9)}, haste=7.5)


def _limit_cases(out: _Cases, base: Profile) -> None:
    """The largest numbers the port holds exactly: an item's number is held to 2^40 so that the 22 of them add up exactly, a
    weight to what a double holds as a whole number, and a weight may be in exponent notation (read as the decimal it prints as)."""
    big = 2**40
    stats = dict.fromkeys(("STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK", "AC", "HPREG", "MANAREG", "ENDREG"), big)
    resists = dict.fromkeys(fm.SCHOOLS, big)
    weights = _weights(HP=2**53 - 1, MANA=10**15, END=10**15, AC=10**15, ATK=10**15, DEX=10**15, HASTE=10**15, CHA=10**15)
    weights.update(HPREG=10**15, MANAREG=10**15, ENDREG=10**15, SV=10**15, DMG=10**15)
    profile = _same(base, weights=weights, naked=dict.fromkeys(ATTRIBUTES, 10**15))
    sword = WeaponVec("1H Slashing", big, big, big, False)
    for sign in (1, -1):
        kit = {}
        for index in range(len(SLOT_INSTANCES)):
            weapon = sword if SLOT_INSTANCES[index] in ("PRIMARY", "SECONDARY") else None
            kit[index] = _item(
                f"itterm-big-{index}", stats={k: sign * v for k, v in stats.items()}, sv={k: sign * v for k, v in resists.items()},
                haste=sign * big, weight10=sign * big, weapon=weapon, shield=SLOT_INSTANCES[index] == "SECONDARY",
            )  # fmt: skip
        out.add(["limits"], profile, kit, setup="dw", haste=100)
    tiny = _same(base, weights=_weights(HP=1.5e-08, AC=2.5e-07, ATK=1e-05, MANA=0.1, END=3e-07, DEX=1.2345678901234567e-05, DMG=1e-06))
    kit = {_place("CHEST"): _item("itterm-small", stats={"STA": 300, "AC": 250, "WIS": 250, "ATK": 90, "END": 33})}
    out.add(["limits"], tiny, kit, setup="dw", haste=3.3333333333333335)


def _empty_case(out: _Cases, base: Profile) -> None:
    out.add(["empty"], base, {})
    out.add(["empty"], _same(base, weights={}), {_place("CHEST"): _item("itterm-unweighted", stats={"AC": 100, "STA": 50})})


# ---- the document -------------------------------------------------------------------------------------------------------------


def build() -> dict[str, Any]:
    """The document: the same one for the same rules, client tables and code."""
    tables = load_tables()
    rules = tables.rules
    level = rules.get("level.current")

    def make(trio: tuple[str, ...], race: str = "HUM") -> Profile:
        return make_profile(race, trio, level, "balanced", None, None, tables, rules)

    monk = make(("MNK", "SHD", "SHM"))  # a Monk, a WIS pool and an INT pool
    casters = make(("CLR", "SHD", "ENC"))  # three mana pools of both stats
    melee = make(("WAR", "ROG", "BER"))  # no mana class
    wis_pair = make(("CLR", "SHM", "WAR"))  # two WIS pools
    out = _Cases()
    _attribute_cases(out, monk)
    _end_cases(out, monk)
    _mana_cases(out, casters, monk, melee, wis_pair)
    _pool_cases(out, casters)
    _sheet_cases(out, monk)
    iksar = rules.get("race.iksar_ac_bonus", level)
    _monk_cases(out, monk, iksar)
    _iksar_cases(out, monk, melee, iksar)
    _haste_cases(out, melee, monk)
    _regen_resist_cases(out, monk)
    _weapon_cases(out, monk)
    _buff_cases(out, monk)
    _decimal_cases(out, casters)
    _limit_cases(out, monk)
    _empty_case(out, monk)
    _durability_cases(out, lambda trio, rank: make_profile("HUM", trio, level, "balanced", None, {"natural_durability": rank}, tables, rules))
    return {
        "format": FORMAT, "kind": KIND, "rules_version": rules.version, "level": level, "terms": dict(TERMS),
        "profiles": out.profiles, "cases": out.cases,
    }  # fmt: skip


def render(doc: Mapping[str, Any]) -> str:
    """The text of the document: plain ASCII, the keys of the top level one to a line, the profiles and the cases one to a line."""
    lines = ["{"]
    last = len(doc) - 1
    for position, (key, value) in enumerate(doc.items()):
        comma = "," if position < last else ""
        if key in ("profiles", "cases"):
            lines.append(f" {_text(key)}: [")
            lines += [f"  {_text(entry)}{',' if number < len(value) - 1 else ''}" for number, entry in enumerate(value)]
            lines.append(f" ]{comma}")
        else:
            lines.append(f" {_text(key)}: {_text(value)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Write the file (``--out``, the committed one by default), or with ``--check`` say whether it is current (0 or 1)."""
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.export.evaluate_terms",
        description="Write the term cases of the exact evaluator (fixtures/evaluate-terms.json), or check that the file is current.",
    )
    parser.add_argument("--out", type=Path, default=PATH, help=f"the file (default {PATH.relative_to(REPO).as_posix()})")
    parser.add_argument("--check", action="store_true", help="do not write: say whether the file is what the script makes now")
    args = parser.parse_args(argv)
    text = render(build())
    if args.check:
        try:
            current = args.out.read_text(encoding="ascii")
        except (OSError, ValueError) as error:
            print(f"trioforge.export.evaluate_terms: {args.out} cannot be read ({type(error).__name__})", file=sys.stderr)
            return 1
        if current != text:
            print(f"trioforge.export.evaluate_terms: {args.out} differs from what the script makes now", file=sys.stderr)
            return 1
        print(f"{args.out}: current")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="ascii", newline="\n")
    print(f"{args.out}: {len(text)} bytes")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
