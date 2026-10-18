"""The tables of the parity fixtures: random evaluations, profiles, weight compositions, item vectors and tier tables.

These are the families that are lists of exact values rather than cases with a program:

* ``evaluate/``: random kits with the exact breakdown of each (:func:`evaluate_docs`);
* ``profiles/``: the browser bundle of five trio types and the profile of every race, role and buff key (:func:`profile_docs`),
  and compositions of the weight overrides (:func:`weight_docs`);
* ``items/``: the item table and the item at every tier and both weapon rates (:func:`item_docs`), and the tier modes and the
  merge costs (:func:`tier_docs`).
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from itertools import combinations
from typing import Any

import numpy as np

from trioforge.classes import CLASS_CODES
from trioforge.export import brute, browser
from trioforge.export.fixture_cases import (
    FORMAT,
    Inputs,
    Scenario,
    breakdown_json,
    buffset_doc,
    eval_totals_for,
    exact_json,
    kit_json,
)
from trioforge.model import formulas as fm
from trioforge.model import items as item_model
from trioforge.model import roles
from trioforge.model.items import SLOT_INSTANCES, MAX_TIER, at_tier
from trioforge.model.tiers import MAX_DIFFICULTY, MODES, TIER_RULES, cost_to_reach, tier_for_mode
from trioforge.precompute.grid import parse_trio, trio_slug

__all__ = [
    "FEATURES",
    "EVALUATE_COMMON",
    "EVALUATE_COVERAGE",
    "EVALUATE_EXTREMES",
    "EVALUATE_RARE",
    "FIVE_TRIOS",
    "evaluate_docs",
    "item_docs",
    "item_table",
    "profile_docs",
    "sample_records",
    "tier_docs",
    "weight_docs",
]

#: a Monk trio, a mixed WIS/INT mana trio, an all-caster trio, a trio with no mana class and a melee/caster mix
FIVE_TRIOS = tuple(parse_trio(text) for text in ("PAL-MNK-BER", "SHD-CLR-SHM", "WIZ-MAG-ENC", "WAR-ROG-BER", "BRD-RNG-BST"))
PROFILE_RACES = ("HUM", "IKS", "OGR", "ERU", "TRL", "DWF", "HIE", "BAR", "HFL", "GNM", "KER", "FRG", "HEF", "DEF", "ELF")
MANA_STYLES = ("WIS", "INT", "MANA", "MANAREG")
EVALUATE_CHUNK = 1000
ITEM_CHUNK = 1000
STAT_ORDER = (*item_model.STAT_KEYS, *item_model.REGEN_KEYS)
STAT_STYLES = (
    "AC", "STA", "AGI", "DEX", "STR", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG", "SV",
    "HASTE", "LIGHT", "HEAVY",
)  # fmt: skip
#: the regimes of the evaluator that the random kits are made to reach, and that a run checks they do (see evaluate_docs)
EVALUATE_COMMON = (
    "sta>255", "end-average>100", "end-average>201", "dex>255", "wis>100", "wis>200", "wis>255", "int>100", "int>200",
    "int>255", "softcap-binds", "shield-worn", "monk-bonus>0", "monk-bonus=0", "monk-bonus<0", "iksar", "haste-capped",
    "resist-capped", "two-hander", "dual-wield", "buffs-chosen", "mixed-tiers",
)  # fmt: skip
#: the stat totals past the cap of 510, which only a kit of the best items under every buff reaches
EVALUATE_EXTREMES = ("sta>510", "dex>510", "agi>510", "str>510", "wis>510", "int>510")
#: counted when reached, not required: charisma past 510 is reached by one kit in 5,000, and no kit of the public catalog
#: reaches the gear regen cap (the only regen items are two wiki pieces and two hidden ones: 28 points of HP regen at the most
#: against a cap of 30), which the brute-force instances cover instead
EVALUATE_RARE = ("cha>510", "regen-capped")
EVALUATE_COVERAGE = (*EVALUATE_COMMON, *EVALUATE_EXTREMES)


# ---- evaluations --------------------------------------------------------------------------------------------------


def _stat(item: Any, name: str) -> int:
    if name == "SV":
        return sum(item.sv.get(school, 0) for school in fm.SCHOOLS)
    if name == "HASTE":
        return item.haste
    if name == "LIGHT":
        return -item.weight10
    if name == "HEAVY":
        return item.weight10
    return item.stats.get(name, 0)


def _fits(item: Any, group: str, setup: str | None) -> bool:
    return brute.fits(item, group, setup, "all")


def _random_choice(rng: random.Random, buffset: Any, cap: int) -> list[int] | None:
    """Half the time none (the profile's own always-on buffs), else a legal handful of the optional buffs."""
    if buffset is None or not buffset.optional or rng.random() < 0.5:
        return None
    order = [buff.id for buff in buffset.optional]
    rng.shuffle(order)
    chosen: list[int] = []
    for buff_id in order:
        if len(chosen) >= cap:
            break
        if rng.random() < 0.8 and buffset.is_legal([*chosen, buff_id]):
            chosen.append(buff_id)
    return sorted(chosen)


def _greedy_choice(buffset: Any, cap: int) -> list[int] | None:
    """As many of the optional buffs as are legal together, up to ``cap``: the strongest spell haste first (only one can be
    active), then in the order of their ids."""
    if buffset is None or not buffset.optional:
        return None
    chosen: list[int] = []
    for buff in sorted(buffset.optional, key=lambda buff: (-buff.haste, buff.id)):
        if len(chosen) < cap and buffset.is_legal([*chosen, buff.id]):
            chosen.append(buff.id)
    return sorted(chosen)


def evaluation_tags(
    profile: Any, breakdown: fm.Breakdown, kit: Sequence[Any], chosen: Sequence[int] | None, tiers: set[int]
) -> list[str]:
    """Which regimes of the evaluator one evaluation reaches (see :data:`EVALUATE_COVERAGE`)."""
    t = breakdown.totals
    attrs, sheet = t["attributes"], t["sheet"]
    tags = []
    for stat, knees in (("STA", (255, 510)), ("DEX", (255, 510)), ("AGI", (510,)), ("STR", (510,)), ("CHA", (510,))):
        tags += [f"{stat.lower()}>{knee}" for knee in knees if attrs[stat] > knee]
    tags += [f"end-average>{knee}" for knee in (100, 201) if t["end_average"] > knee]
    for stat in ("WIS", "INT"):
        tags += [f"{stat.lower()}>{knee}" for knee in (100, 200, 255, 510) if attrs[stat] > knee]
    if sheet["X"] > sheet["Y"]:
        tags.append("softcap-binds")
    if sheet["shield_ac"] > 0:
        tags.append("shield-worn")
    if profile.monk is not None:
        bonus = sheet["monk_bonus"]
        tags.append("monk-bonus>0" if bonus > 0 else "monk-bonus<0" if bonus < 0 else "monk-bonus=0")
    if profile.iksar_ac:
        tags.append("iksar")
    if t["haste"]["counted"] >= profile.haste_cap:
        tags.append("haste-capped")
    caps = profile.caps
    regen = (("HPREG", "HP"), ("MANAREG", "MANA"), ("ENDREG", "END"))
    if any(t["regen"][key]["gear"] > caps["regen"][family] for key, family in regen):
        tags.append("regen-capped")
    if any(row["gear"] + row["buff"] > caps["resist"] for row in t["resists"].values()):
        tags.append("resist-capped")
    primary, secondary = kit[SLOT_INSTANCES.index("PRIMARY")], kit[SLOT_INSTANCES.index("SECONDARY")]
    if primary is not None and primary.weapon is not None and primary.weapon.two_handed:
        tags.append("two-hander")
    if primary is not None and secondary is not None and primary.weapon is not None and secondary.weapon is not None:
        tags.append("dual-wield")
    if chosen:
        tags.append("buffs-chosen")
    if len(tiers) > 1:
        tags.append("mixed-tiers")
    return tags


class _Maker:
    """Draws kits for one scenario: for each place of a kit, the positions in the scenario's pool of the items that fit it, and
    (made on first use) the value of every stat style of every item, to rank them."""

    def __init__(self, sc: Scenario, inputs: Inputs) -> None:
        self.sc = sc
        self.inputs = inputs
        by_group = {
            group: [position for position, item in enumerate(sc.pool) if _fits(item, group, sc.spec.setup)]
            for group in dict.fromkeys(SLOT_INSTANCES)
        }
        self.places = [by_group[group] for group in SLOT_INSTANCES]
        self._stats: dict[int, np.ndarray] = {}

    def stats(self, tier: int | None = None) -> np.ndarray:
        """The value of every stat style (columns) of every item of the pool (rows) at ``tier`` (the scenario's by default)."""
        tier = self.sc.spec.tier if tier is None else tier
        if tier not in self._stats:
            items = self.sc.pool if tier == self.sc.spec.tier else self.inputs.vecs(self.sc.pool_items, tier)
            self._stats[tier] = np.array([[_stat(item, style) for style in STAT_STYLES] for item in items], dtype=np.int64)
        return self._stats[tier]

    def potential(self, style: int) -> int:
        """What a kit of the best item of a stat style in every place reaches in that style at +10."""
        table = self.stats(MAX_TIER)
        return int(sum(table[options, style].max() for options in self.places if options))


def evaluate_docs(
    inputs: Inputs, scenarios: Sequence[Scenario], count: int, seed: int
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, int]]:
    """``count`` random kits, each valued by the exact evaluator under the profile of a scenario: ``evaluate/profiles.json``
    (the profiles, their buff sets, the Monk bins of each level that has a Monk profile and the records of every item used)
    and ``evaluate/kits-NN.json`` (the kits and their breakdowns). Also the number of evaluations that reach each regime of
    the evaluator.

    A third of the kits (up to ten for each stat style) aim at an extreme: the best item of one stat in every place, all at
    +10, under every buff that can be active together, on the scenarios where that stat can go highest. The others are random:
    items drawn at random, or from the best few of a stat, at the tier of the scenario or at tiers drawn for each item."""
    rng = random.Random(f"{seed}:evaluate")
    order = list(range(len(scenarios)))
    rng.shuffle(order)
    makers: dict[int, _Maker] = {}

    def maker(index: int) -> _Maker:
        if index not in makers:
            makers[index] = _Maker(scenarios[index], inputs)
        return makers[index]

    styles = len(STAT_STYLES)
    aimed = min(count // 3, 10 * styles)
    keys: set[str] = set()
    evaluations: list[dict[str, Any]] = []
    coverage: dict[str, int] = {}
    ranked_by_style: dict[int, list[int]] = {}
    for number in range(count):
        aim = number % styles if number < aimed else None
        if aim is not None:
            if aim not in ranked_by_style:
                ranked_by_style[aim] = sorted(order, key=lambda i: (-maker(i).potential(aim), i))
            index = ranked_by_style[aim][(number // styles) % min(10, len(order))]
        else:
            index = order[number % len(order)]
        sc = scenarios[index]
        spec, profile, buffset = sc.spec, sc.profile, sc.buffset
        style = "top" if aim is not None else rng.choice(("random", "random", "stack", "stack", "stack"))
        theme = aim if aim is not None else rng.randrange(styles)
        mixed = False if aim is not None else rng.random() < 0.3
        fill = 1.0 if aim is not None else rng.choice((0.5, 0.9, 1.0))
        setup = rng.choice((*profile.setups, *profile.setups, "1h-shield", "2h", "dw", "stick", None))
        kit: list[Any] = [None] * len(SLOT_INSTANCES)
        used: set[str] = set()
        two_handed = False
        tiers: set[int] = set()
        for slot, group in enumerate(SLOT_INSTANCES):
            options = maker(index).places[slot]
            if not options or rng.random() > fill or (group == "SECONDARY" and two_handed):
                continue
            column = maker(index).stats(MAX_TIER if aim is not None else None)[options, theme]
            if style == "random":
                position = rng.choice(options)
            else:  # the best items of the stat that are not a second copy of a Lore item
                ranked = [options[n] for n in sorted(range(len(options)), key=lambda n: (-int(column[n]), n))]
                free = [p for p in ranked[: 8 + len(used)] if not (sc.pool[p].lore and sc.pool_items[p]["key"] in used)]
                if not free:
                    continue
                position = free[0] if style == "top" else rng.choice(free[:4])
            record = sc.pool_items[position]
            if sc.pool[position].lore and record["key"] in used:
                continue
            tier = MAX_TIER if aim is not None else rng.randrange(MAX_TIER + 1) if mixed else spec.tier
            item = inputs.vec(record, tier)
            kit[slot] = item
            tiers.add(tier)
            used.add(record["key"])
            keys.add(record["key"])
            two_handed = two_handed or (group == "PRIMARY" and item.weapon is not None and item.weapon.two_handed)
        chosen = _greedy_choice(buffset, 40) if aim is not None else _random_choice(rng, buffset, rng.choice((3, 8, 40)))
        haste = rng.choice((0, 25, 50, int(profile.haste_cap), rng.randint(0, int(profile.haste_cap))))
        totals = eval_totals_for(buffset, chosen) if chosen is not None else None
        breakdown = fm.evaluate(profile, kit, totals, setup=setup, haste_assumed=haste)
        for tag in evaluation_tags(profile.eval_profile, breakdown, kit, chosen, tiers):
            coverage[tag] = coverage.get(tag, 0) + 1
        evaluations.append(
            {
                "profile": index, "setup": setup, "haste": haste, "buffs": chosen, "kit": kit_json(kit),
                "breakdown": breakdown_json(breakdown),
            }
        )  # fmt: skip
    profile_rows = [
        {
            "id": sc.spec.id, "trio": list(sc.spec.trio), "level": sc.spec.level, "race": sc.spec.race, "role": sc.spec.role,
            "tier": sc.spec.tier, "evidence": sc.spec.evidence, "profile": sc.profile.to_dict(),
            "buffset": buffset_doc(sc.buffset),
        }
        for sc in scenarios
    ]  # fmt: skip
    head = {"format": FORMAT, "data_release": inputs.data_release, "rules_version": inputs.rules_version}
    # the Monk bonus is read from the bins (a table the float arithmetic of monk_bonus made), and not every level of these
    # profiles has a bundle among the fixtures: the bins of each level that has a Monk profile are here
    monk_levels = sorted({sc.spec.level for sc in scenarios if sc.profile.monk is not None})
    monk_bins = {str(level): browser.monk_bins(level, inputs.rules) for level in monk_levels}
    docs: list[tuple[str, dict[str, Any]]] = [
        (
            "evaluate/profiles.json",
            {**head, "kind": "evaluate-profiles", "weapon_pct": inputs.weapon_pct, "profiles": profile_rows,
             "monk_bins": monk_bins, "records": inputs.records_for(keys)},
        )
    ]  # fmt: skip
    for start in range(0, len(evaluations), EVALUATE_CHUNK):
        chunk = start // EVALUATE_CHUNK
        kits = {**head, "kind": "evaluate-kits", "chunk": chunk, "evaluations": evaluations[start : start + EVALUATE_CHUNK]}
        docs.append((f"evaluate/kits-{chunk:02d}.json", kits))
    return docs, dict(sorted(coverage.items()))


# ---- profiles and weights ---------------------------------------------------------------------------------------------


def profile_docs(inputs: Inputs, trios: int, races: int | None, *, level_55: bool) -> list[tuple[str, dict[str, Any]]]:
    """The bundle of each trio and the profile of every race, role and buff key, each three ways (with no evidence level, which
    is what a profile with no pool to read is, and at each evidence level of the bundle, whose solve pool decides the weapon
    setups), and a few with a deity.

    Each profile is checked against ``assemble`` of the bundle, which is what the browser does, and against the profile the
    precompute makes (given the solve pool of the evidence level, when there is one). The bundle is made from the catalog of
    ``inputs``, so that its pools and the pools of the check are the same."""
    docs: list[tuple[str, dict[str, Any]]] = []
    jobs = [(codes, inputs.level) for codes in FIVE_TRIOS[:trios]]
    if level_55:
        jobs.append((FIVE_TRIOS[0], 55))
    for codes, level in jobs:
        bundle = browser.bundle(
            codes, level, inputs.tables, inputs.rules, inputs.spells(level), data_release=inputs.data_release,
            catalog=inputs.document,
        )  # fmt: skip
        slug = f"{trio_slug(codes)}-l{level}"
        available = [row["code"] for row in bundle["races"]]
        chosen_races = available if races is None else [code for code in PROFILE_RACES if code in available][:races]
        offered = list(bundle["roles"])
        ways = [{}, *({"evidence": label} for label in bundle["evidence_levels"])]
        entries = []

        def add(race: str, role: str, key: str, **options: Any) -> None:
            label, deity = options.get("evidence"), options.get("deity")
            profile = inputs.profile(codes, level, race, role, key, evidence=label or "strict", deity=deity, pool=label)
            expected = browser.assemble(bundle, race, role, key, **options)
            if profile.to_dict() != expected:
                raise ValueError(
                    f"the bundle of {slug} does not reassemble to the profile of {race} {role} {key} ({options or 'no options'})"
                )
            entries.append({"race": race, "role": role, "buffs": key, "options": options, "profile": expected})

        for race in chosen_races:
            for role in offered:
                for key in browser.BUFF_SETS:
                    for way in ways:
                        add(race, role, key, **way)
        add(chosen_races[-1], offered[-1], "raid", deity="Tunare")
        middle = chosen_races[len(chosen_races) // 2], offered[len(offered) // 2]
        for way in ways[1:]:
            add(*middle, "group+enchanter", deity="Brell Serilis", **way)
        head = {"format": FORMAT, "data_release": inputs.data_release, "rules_version": inputs.rules_version}
        docs.append((f"profiles/{slug}.bundle.json", bundle))
        listing = {
            **head, "kind": "profiles", "bundle": f"{slug}.bundle.json", "trio": list(codes), "level": level, "profiles": entries,
        }  # fmt: skip
        docs.append((f"profiles/{slug}.profiles.json", listing))
    return docs


def weight_docs(inputs: Inputs, count: int, seed: int) -> list[tuple[str, dict[str, Any]]]:
    """``count`` random compositions of the slider positions, custom weights and the regen window over the weights of a
    role, each with what :func:`trioforge.model.roles.weights_override` makes of it."""
    rng = random.Random(f"{seed}:weights")
    trios = list(combinations(CLASS_CODES, 3))
    custom_values = (0, 0.25, 0.5, 1, 1.5, 2.5, 6, 12.75, 100, 1000)
    windows = (None, None, 0, 0.5, 1, 3, 5, 7.5, 12.25, 60)  # 3 is the role's own window
    rows = []
    for _ in range(count):
        trio = rng.choice(trios)
        role = rng.choice(roles.roles_for(trio))
        reachable = bool(fm.pools_for(trio, inputs.level, inputs.tables)["MANA"])
        base = roles.weights_for(trio, role, inputs.rules, mana_reachable=reachable)
        multipliers = {group: rng.choice(roles.MULTIPLIERS) for group in roles.WEIGHT_GROUPS if rng.random() < 0.35}
        names = [*roles.CUSTOM_KEYS, "SV"]
        custom = {key: rng.choice(custom_values) for key in rng.sample(names, rng.choice((0, 0, 1, 2, 4)))}
        window = rng.choice(windows)
        result = roles.weights_override(base, multipliers, custom, window, mana_reachable=reachable)
        rows.append(
            {
                "trio": list(trio), "role": role, "mana_reachable": reachable, "base": base, "multipliers": multipliers,
                "custom": custom, "regen_T": window, "result": result,
            }
        )  # fmt: skip
    head = {"format": FORMAT, "data_release": inputs.data_release, "rules_version": inputs.rules_version}
    return [("profiles/weights.json", {**head, "kind": "weights", "compositions": rows})]


# ---- items and tiers ----------------------------------------------------------------------------------------------------


FEATURES = (
    "weapon-1h", "weapon-2h", "shield", "lore", "owned-only", "match-name", "deity", "weight-unknown", "races", "classes",
    "haste", "regen", "negative", "resists", "weight-zero", "aliases", "tier-rule-spell", "tier-rule-fixed0", "no-stats",
    "any-slot", "two-slots", "weapon-bonus", "weapon-incomplete",
)  # fmt: skip


def _features(record: dict[str, Any]) -> list[str]:
    """What is special about an item record, as names from :data:`FEATURES` (a sample of the table keeps some of each)."""
    stats = record.get("stats", {})
    weapon = record.get("weapon")
    found = []
    if weapon is not None:
        two = str(weapon.get("skill") or "").casefold().startswith("2h")
        found.append("weapon-2h" if two else "weapon-1h")
        if weapon.get("bonus"):
            found.append("weapon-bonus")
        if weapon.get("dmg") is None or weapon.get("delay") is None:
            found.append("weapon-incomplete")
    if record.get("item_type") == "Shield":
        found.append("shield")
    for flag, test in (
        ("lore", record.get("lore")), ("races", "races" in record), ("deity", "deity" in record),
        ("classes", "classes" in record), ("weight-unknown", record["weight10"] is None),
        ("weight-zero", record["weight10"] == 0), ("haste", "HASTE" in stats),
        ("regen", any(k in stats for k in ("HPREG", "MANAREG", "ENDREG"))), ("negative", any(v < 0 for v in stats.values())),
        ("resists", bool(record.get("sv"))), ("owned-only", record.get("owned_only")), ("match-name", "match_name" in record),
        ("aliases", "aliases" in record), ("tier-rule-spell", record["tier_rule"] == "spell"),
        ("tier-rule-fixed0", record["tier_rule"] == "fixed0"), ("no-stats", not stats and not record.get("sv")),
        ("any-slot", "ANY" in record["slots"]), ("two-slots", len(record["slots"]) > 1),
    ):  # fmt: skip
        if test:
            found.append(flag)
    return found


def sample_records(records: Sequence[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """``count`` records of the table, in table order: the first three that have each feature of :data:`FEATURES` (a weapon of
    each hand, a shield, Lore, a hidden item, no weight, a race or deity or class list, haste, a negative stat ...), the first of
    every feature before the second of any, then evenly spaced ones."""
    firsts: dict[str, list[int]] = {feature: [] for feature in FEATURES}
    for position, record in enumerate(records):
        for feature in _features(record):
            if len(firsts[feature]) < 3:
                firsts[feature].append(position)
    chosen: dict[int, None] = {}
    for round_ in range(3):
        for feature in FEATURES:
            if len(chosen) < count and round_ < len(firsts[feature]):
                chosen.setdefault(firsts[feature][round_], None)
    if len(chosen) < count:
        step = max(1, len(records) // max(1, count - len(chosen)))
        for position in range(0, len(records), step):
            if len(chosen) >= count:
                break
            chosen.setdefault(position, None)
    return [records[position] for position in sorted(chosen)]


def _vector(item: Any) -> list[int]:
    stats = [item.stats.get(name, 0) for name in STAT_ORDER]
    return [*stats, *(item.sv.get(name, 0) for name in item_model.SV_KEYS), item.haste, item.weight10]


def _fixed(item: Any) -> dict[str, Any]:
    weapon = item.weapon
    return {
        "name": item.name, "slots": sorted(item.slots), "classes": sorted(item.classes),
        "deity": None if item.deity is None else sorted(item.deity), "lore": item.lore, "is_shield": item.is_shield,
        "races": None if item.races is None else sorted(item.races), "weight_known": item.weight_known,
        "weapon": None if weapon is None else {
            "skill": weapon.skill, "delay": weapon.delay, "bonus": weapon.bonus, "two_handed": weapon.two_handed
        },
    }  # fmt: skip


def item_table(inputs: Inputs, count: int | None) -> dict[str, Any]:
    """The item table as :func:`trioforge.export.browser.items` writes it: every wearable of the catalog, hidden ones flagged
    ``owned_only`` (``count`` None), or the ``count`` records that :func:`sample_records` chooses, with the header of the table
    (``count`` is then the number of records it holds)."""
    table = inputs.table
    if count is None:
        return table
    records = sample_records(table["items"], count)
    return {**table, "count": len(records), "items": records}


def item_docs(inputs: Inputs, count: int | None) -> list[tuple[str, dict[str, Any]]]:
    """The item table (all of it, or ``count`` records) and, for each record, the item ``at_tier`` makes of it at every tier
    from 0 to 10 and both weapon rates, compactly: the parts that do not change with the tier once (``fixed``), then for
    each tier the stats, resists, haste and weight as numbers in a fixed order, and the weapon damage for each rate."""
    table = item_table(inputs, count)
    records = table["items"]
    head = {"format": FORMAT, "data_release": inputs.data_release, "rules_version": inputs.rules_version}
    docs: list[tuple[str, dict[str, Any]]] = [("items/table.json", table)]
    rates = list(item_model.WEAPON_PCTS)
    entries = []
    for record in records:
        catalog = browser.item_to_catalog(record, table["defaults"])
        tiers, damage, fixed = [], {str(rate): [] for rate in rates}, None
        for tier in range(MAX_TIER + 1):
            by_rate = {rate: at_tier(catalog, tier, inputs.rules, weapon_pct=rate) for rate in rates}
            item = by_rate[rates[0]]
            for other in by_rate.values():  # the rate changes weapon damage and nothing else
                if _vector(other) != _vector(item) or _fixed(other) != _fixed(item):
                    raise ValueError(f"{browser.record_key(record)}: the weapon rate changes more than damage at +{tier}")
            fixed = fixed or _fixed(item)
            tiers.append(_vector(item))
            for rate, vec in by_rate.items():
                if vec.weapon is not None:
                    damage[str(rate)].append(vec.weapon.dmg)
        damage = damage if fixed["weapon"] is not None else None
        entries.append({"key": browser.record_key(record), "fixed": fixed, "tiers": tiers, "damage": damage})
    for start in range(0, len(entries), ITEM_CHUNK):
        chunk = start // ITEM_CHUNK
        docs.append(
            (
                f"items/vectors-{chunk:02d}.json",
                {**head, "kind": "item-vectors", "chunk": chunk, "weapon_pcts": rates, "stat_order": list(STAT_ORDER),
                 "sv_order": list(item_model.SV_KEYS), "items": entries[start : start + ITEM_CHUNK]},
            )
        )  # fmt: skip
    docs.append(("items/tiers.json", tier_docs(inputs)))
    return docs


def tier_docs(inputs: Inputs) -> dict[str, Any]:
    """The tier mode of every tier rule, mode, difficulty (0 to 4) and fixed tier, and the merge cost between any two tiers
    for every tier rule and difficulty, as Python gives them."""
    modes = []
    for rule in TIER_RULES:
        for mode in MODES:
            for difficulty in range(MAX_DIFFICULTY + 1):
                for fixed in range(MAX_TIER + 1) if mode == "fixed" else (None,):
                    tier = tier_for_mode(rule, mode, difficulty, fixed)
                    modes.append({"rule": rule, "mode": mode, "D": difficulty, "N": fixed, "tier": tier})
    costs = []
    for rule in TIER_RULES:
        for difficulty in range(MAX_DIFFICULTY + 1):
            for start in range(MAX_TIER + 1):
                for stop in range(start, MAX_TIER + 1):
                    cost = cost_to_reach(rule, start, stop, difficulty)
                    costs.append({"rule": rule, "D": difficulty, "from": start, "to": stop, **cost})
    return {
        "format": FORMAT, "kind": "tiers", "data_release": inputs.data_release, "rules_version": inputs.rules_version,
        "exp_needed": exact_json(inputs.rules.get("tier.exp_needed")), "modes": modes, "costs": costs,
    }  # fmt: skip
