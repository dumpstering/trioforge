"""Random legacy instances for the compatibility tests: a profile, a pool and a scenario in the old JSON shapes,
small enough that ``compat_helpers.best_gain`` can brute-force them. Every name is invented."""

from __future__ import annotations

from copy import deepcopy

from compat_helpers import (
    ATTRS,
    BODY,
    POST255_DEFAULT,
    REGEN,
    SCHOOLS,
    best_gain,
    legacy_item,
    sword,
)

TRIOS = (["WAR", "CLR", "ENC"], ["PAL", "SHM", "BRD"], ["MNK", "ROG", "WIZ"], ["SHD", "DRU", "BST"])
SETUP_MENU = ("maul", "blade-ward", "free", "free-two", "free-free", "blade-free", "free-ward", "twin", "held")
ALL_SETUPS = {
    "maul": ["Maul of Tests", None],
    "blade-ward": ["Test Blade", "<shield>"],
    "free": ["<free-1h>", "<held>"],
    "free-two": ["<free-2h>", None],
    "free-free": ["<free>", "<free>"],
    "blade-free": ["Test Blade", "<free>"],
    "free-ward": ["<free>", "Ward of Tests"],
    "twin": ["Test Blade", "Test Blade"],
    "held": [None, "Lamp of Tests"],
}
SPECIAL = {  # the items the weapon setups of the random profiles name
    "maul-a": legacy_item(
        "maul-a",
        ["PRIMARY"],
        stats={"STR": 18, "AC": 6, "HP": 20},
        weapon=sword("2H Slashing", 30, 40),
        wt=6.0,
        name="Maul of Tests",
    ),
    "blade-a": legacy_item(
        "blade-a", ["PRIMARY", "SECONDARY"], stats={"DEX": 9, "HASTE": 18}, weapon=sword(), name="Test Blade"
    ),
    "ward-a": legacy_item("ward-a", ["SECONDARY"], stats={"AC": 14, "STA": 6}, sv={"MAGIC": 12}, name="Ward of Tests"),
    "lamp-a": legacy_item("lamp-a", ["SECONDARY"], stats={"HP": 25, "MANA": 20}, name="Lamp of Tests"),
}
STAT_NAMES = (
    "AC",
    "HP",
    "MANA",
    "END",
    "STR",
    "STA",
    "AGI",
    "DEX",
    "WIS",
    "INT",
    "CHA",
    "ATK",
    "HPREG",
    "MANAREG",
    "ENDREG",
)


def _stats(rng):
    out = {}
    for key in rng.sample(STAT_NAMES, rng.randint(1, 4)):
        if key == "AC":
            out[key] = rng.randint(2, 30)
        elif key in ("HP", "MANA"):
            out[key] = rng.randint(10, 120)
        elif key == "END":
            out[key] = rng.randint(5, 60)
        elif key == "ATK":
            out[key] = rng.randint(2, 30)
        elif key in REGEN:
            out[key] = rng.randint(1, 12)
        else:
            out[key] = rng.randint(3, 45) if rng.random() > 0.08 else -rng.randint(1, 15)
    if rng.random() < 0.2:
        out["HASTE"] = rng.randint(5, 45)
    return out


def _curve(rng, froms):
    parts = []
    for _ in range(rng.choice((1, 1, 2))):
        count = rng.randint(1, 3)
        breaks = sorted(rng.sample(range(30, 300, 5), count))
        slopes = [round(rng.choice((0, 0.5, 1, 1.25, 2.5)), 3) for _ in range(count + 1)]
        parts.append(
            {
                "from": rng.choice(froms),
                "scale": round(rng.uniform(0.2, 6), 3),
                "breaks": breaks,
                "slopes": slopes,
                "pools": 1,
            }
        )
    return parts if len(parts) > 1 or rng.random() < 0.5 else parts[0]


def _named(setups):
    return {tok for pair in setups.values() for tok in pair if tok and not tok.startswith("<")}


def random_case(rng, limit=60_000):
    """(profile, pool, scenario) of a random legacy instance. The scenario names a setup of the profile (or none), a
    tier and the other options of ``from_legacy``; the pool is shrunk until the brute force is small enough."""
    profile = {
        "key": "synthetic",
        "classes": list(rng.choice(TRIOS)),
        "level": 50,
        "naked": {a: rng.randint(40, 150) for a in ATTRS},
    }
    if rng.random() < 0.5:
        profile["ac"] = {
            "model": "sheet",
            "cap": rng.randint(60, 200),
            "cap_without_cs": 50,
            "ret": rng.choice((0.0, 0.33, 0.5, 1.0)),
            "nongear": rng.randint(0, 120),
        }
        if rng.random() < 0.4:
            profile["ac"]["mult"] = rng.choice((1.0, 1.25))
    else:
        profile["ac"] = {
            "cap": rng.randint(40, 160),
            "cap_without_cs": 40,
            "ret": rng.choice((0.0, 0.33, 1.0)),
            "buff_share": rng.choice((0, 0, 15)),
        }
    profile["haste_cap"] = rng.choice((None, 75, 60))
    profile["monk"] = False
    curves = {}
    for attr in rng.sample(ATTRS, rng.randint(0, 5)):
        curves[attr] = _curve(rng, ["HP", "MANA", "END", "ATK", "AC"] + [None])
    profile["curves"] = curves
    weights = {}
    for key in ("AC", "HP", "MANA", "ATK", "HASTE", "END", "CHA", "HPREG", "MANAREG", "ENDREG"):
        if rng.random() < 0.75:
            weights[key] = round(rng.uniform(0.05, 4.0), 3)
    for attr in ("STR", "STA", "AGI", "DEX", "WIS", "INT"):
        parts = curves.get(attr)
        parts = [parts] if isinstance(parts, dict) else (parts or [])
        if attr not in curves or any(c["from"] is None for c in parts):
            if rng.random() < 0.6:
                weights[attr] = round(rng.uniform(0.05, 2.0), 3)
    sum_form = rng.random() < 0.3
    if sum_form:
        weights["SV"] = round(rng.uniform(0.05, 1.5), 3)
    else:
        for school in rng.sample(SCHOOLS, rng.randint(0, 5)):
            weights["SV_" + school] = round(rng.uniform(0.05, 1.5), 3)
    profile["weights"] = weights
    profile["post255"] = {
        k: rng.choice((0.0, 0.1, 0.25, 0.5)) for k in rng.sample(list(POST255_DEFAULT), rng.randint(0, 4))
    }
    profile["res"] = {
        "cap": rng.randint(30, 120),
        "cap_per_school": {},
        "buffs_count_toward_cap": (not sum_form) and rng.random() < 0.6,
    }
    profile["caps"] = {k: rng.randint(3, 25) for k in rng.sample(REGEN, rng.randint(0, 3))}
    profile["buffs"] = {
        "a": {
            "attrs": {a: rng.randint(5, 60) for a in rng.sample(ATTRS, rng.randint(0, 4))},
            "spell_haste": rng.choice((0, 25, 40, 90)),
            "hp": rng.choice((0, 150)),
            "atk": rng.choice((0, 30)),
            "hpreg": rng.choice((0, 4)),
            "sv": {s: rng.randint(5, 50) for s in rng.sample(SCHOOLS, rng.randint(0, 2))},
        },
        "b": {},
    }
    profile["presets"] = {
        "x": {},
        "y": {k: round(rng.uniform(0.0, 4.0), 3) for k in rng.sample(("AC", "HP", "MANA", "HASTE", "END"), 2)},
    }
    profile["weapon_setups"] = {n: ALL_SETUPS[n] for n in rng.sample(SETUP_MENU, rng.randint(2, 4))}
    needed = _named(profile["weapon_setups"])

    items = []
    for g in rng.sample(("HEAD", "EAR", "FINGER", "CHEST", "NECK", "ARMS", "WRIST"), rng.randint(3, 4)):
        for _ in range(rng.randint(2, 3)):
            slots = [g] + ([rng.choice(BODY)] if rng.random() < 0.1 else [])
            items.append(
                legacy_item(
                    f"it{len(items):02d}",
                    slots,
                    stats=_stats(rng),
                    sv={s: rng.randint(5, 40) for s in rng.sample(SCHOOLS, rng.randint(0, 2))},
                    wt=rng.choice((None, 0.5, 1.0, 2.5, 9.0)),
                    lore=rng.choice((False, False, False, True, None)),
                    tier_rule=rng.choice(("drop", "drop", "quest")),
                )
            )
    for _ in range(rng.randint(0, 2)):
        items.append(
            legacy_item(
                f"it{len(items):02d}",
                [rng.choice(("AMMO", "RANGE", "CHARM"))],
                stats=_stats(rng),
                lore=rng.choice((False, True)),
            )
        )
    chosen = set(rng.sample(list(SPECIAL), rng.randint(2, 4)))
    chosen |= {key for key, item in SPECIAL.items() if item["name"] in needed}
    for key in SPECIAL:
        if key in chosen:
            items.append(deepcopy(SPECIAL[key]))
    if rng.random() < 0.4:
        items.append(legacy_item("held-b", ["SECONDARY", "NECK"], stats=_stats(rng), lore=rng.choice((False, True))))
    if rng.random() < 0.4:
        items.append(
            legacy_item("blade-b", ["PRIMARY"], stats=_stats(rng), weapon=sword("1H Blunt", 12, 24), lore=True)
        )
    if rng.random() < 0.3:
        items.append(
            legacy_item(
                "ward-b",
                ["SECONDARY"],
                stats={**_stats(rng), "AC": rng.randint(3, 25)},
                shield=rng.choice((True, False)),
            )
        )
    scenario = {
        "preset": rng.choice((None, "x", "y")),
        "buffs": rng.choice(("a", "b")),
        "weapons": rng.choice((None, *profile["weapon_setups"])),
        "tier": rng.choice((0, 4, 10)),
        "quest_tier": rng.choice((None, None, 6)),
        "lore_unknown": rng.choice(("lore", "nonlore")),
        "any_rule": rng.choice(("all", "armor")),
    }
    while best_gain(profile, items, scenario, limit) is None and len(items) > 6:
        victims = [i for i in items if i["name"] not in needed]
        items.remove(rng.choice(victims))
    return profile, items, scenario
