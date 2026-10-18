"""Shared machinery for the legacy-compatibility tests: a synthetic legacy profile and pool, the legacy objective
written out again in plain floats, an independent enumerator of every legal assignment under the legacy rules, and a
seeded generator of random legacy instances.

The legacy shapes are the old tools' JSON: a profile with ``naked``, ``ac``, ``weights``, explicit ``curves``,
``presets``, ``weapon_setups`` and ``buffs``, and a pool of items with ``id``, ``name``, ``slots``, ``classes``,
``stats``, ``sv``, ``wt``, ``weapon``, ``lore``, ``tier_rule`` and the rest. The objective here is the *gain* over the
naked character with the same buffs, which is what the old exports record. Nothing in this module imports the code
under test (``trioforge.solver.compat``), so a mistake there cannot hide in the oracle. Every name is invented.
"""

from __future__ import annotations

import re
from copy import deepcopy

import numpy as np

ATTRS = ("STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA")
SCHOOLS = ("FIRE", "COLD", "MAGIC", "POISON", "DISEASE")
BODY = (
    "HEAD",
    "FACE",
    "EAR",
    "NECK",
    "SHOULDERS",
    "ARMS",
    "BACK",
    "WRIST",
    "HANDS",
    "FINGER",
    "CHEST",
    "LEGS",
    "FEET",
    "WAIST",
    "RANGE",
)
ARMOR_SLOTS = BODY[:14]  # what the armor rule of the Any places takes (no RANGE)
PLACES = {"EAR": 2, "WRIST": 2, "FINGER": 2, "ANY": 2}
FEATURES = (
    "G",
    "S",
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
) + SCHOOLS
FIX = {name: n for n, name in enumerate(FEATURES)}
FLAT_KEYS = ("HP", "MANA", "END", "WIS", "INT", "CHA", "ATK", "HPREG", "MANAREG", "ENDREG")  # the old linear keys
REGEN = ("HPREG", "MANAREG", "ENDREG")
POST255_DEFAULT = {"STR": 0.25, "DEX": 0.1, "AGI": 0.25, "STA": 0.25}


# ---- legacy shapes --------------------------------------------------------------------------------------------


def legacy_item(
    ident,
    slots,
    *,
    stats=None,
    sv=None,
    wt=1.0,
    weapon=None,
    lore=False,
    classes=("ALL",),
    tier_rule="drop",
    flags=(),
    deity=None,
    required_level=None,
    **extra,
):
    """A pool item in the legacy JSON shape (all keys present, as the old pool files have them)."""
    item = {
        "id": ident,
        "name": extra.pop("name", ident.replace("-", " ").title()),
        "slots": list(slots),
        "classes": list(classes),
        "races": None,
        "deity": deity,
        "stats": dict(stats or {}),
        "sv": dict(sv or {}),
        "wt": wt,
        "weapon": weapon,
        "effects": [],
        "lore": lore,
        "required_level": required_level,
        "source": {"kind": "drop", "label": ""},
        "origin": ["synthetic"],
        "conflicts": [],
        "tier_rule": tier_rule,
        "confirmed": True,
        "flags": list(flags),
    }
    item.update(extra)
    return item


def sword(skill="1H Slashing", dmg=20, delay=30):
    return {"skill": skill, "dmg": dmg, "delay": delay, "ratio": 0.5, "proc": None}


PROFILE = {
    "key": "synthetic",
    "character": "Synthetic Trio",
    "race": "HUM",
    "classes": ["WAR", "CLR", "ENC"],
    "letters": {"WAR": "W", "CLR": "C", "ENC": "E"},
    "level": 50,
    "naked": {"STR": 100, "STA": 90, "AGI": 80, "DEX": 70, "WIS": 60, "INT": 50, "CHA": 40},
    "pool": "data/synthetic-pool.json",
    "mentions": "data/synthetic-mentions.json",
    "ac": {"model": "sheet", "cap": 120, "cap_without_cs": 110, "ret": 0.33, "nongear": 90},
    "haste_cap": 75,
    "monk": False,
    "weapon_weight": 0.2,
    "packrat_pct": 0,
    "buffs": {
        "big": {
            "attrs": {"STR": 40, "WIS": 30, "STA": 25},
            "spell_haste": 30,
            "ac": 0,
            "hp": 200,
            "mana": 0,
            "atk": 20,
            "hpreg": 5,
            "manareg": 0,
            "endreg": 3,
            "sv": {"MAGIC": 30, "FIRE": 10},
            "note": "invented",
        },
        "small": {
            "attrs": {},
            "spell_haste": 0,
            "ac": 0,
            "hp": 0,
            "mana": 0,
            "atk": 0,
            "hpreg": 0,
            "manareg": 0,
            "endreg": 0,
            "sv": {},
            "note": "",
        },
    },
    "weights": {
        "AC": 2,
        "HP": 1,
        "MANA": 1.5,
        "ATK": 1,
        "DEX": 0.2,
        "HASTE": 2,
        "END": 0.3,
        "CHA": 0.1,
        "SV_FIRE": 0.5,
        "SV_COLD": 0.5,
        "SV_MAGIC": 0.5,
        "SV_POISON": 0.5,
        "SV_DISEASE": 0.5,
        "HPREG": 10,
        "MANAREG": 20,
        "ENDREG": 5,
        "STR": 0,
        "STA": 0,
        "AGI": 0,
        "WIS": 0,
        "INT": 0,
        "SV": 0,
    },
    "post255": {},
    "res": {"cap": 60, "cap_per_school": {}, "buffs_count_toward_cap": True},
    "caps": {"HPREG": 10, "MANAREG": 8, "ENDREG": 6},
    "curves": {
        "STA": [
            {"from": "HP", "scale": 5.0, "breaks": [100, 200], "slopes": [1, 0.5, 0], "pools": 2},
            {"from": "END", "scale": 2.0, "breaks": [200], "slopes": [1, 0]},
        ],
        "WIS": {"from": "MANA", "scale": 4.0, "breaks": [100, 150, 200], "slopes": [1, 2.5, 1.25, 0.5], "pools": 2},
        "STR": [
            {"from": "ATK", "scale": 0.5, "breaks": [255], "slopes": [1, 0]},
            {"from": "END", "scale": 2.0, "breaks": [200], "slopes": [1, 0]},
        ],
        "AGI": [{"from": "AC", "scale": 0.25, "breaks": [255], "slopes": [1, 0]}],
        "DEX": {"from": None, "scale": 1, "breaks": [150, 255], "slopes": [1, 0.1, 0]},
    },
    "presets": {"plain": {}, "tanky": {"AC": 5, "HP": 0.5}, "caster": {"MANA": 4, "AC": 1, "HASTE": 0}},
    "weapon_setups": {
        "maul": ["Maul of Tests", None],
        "blade-ward": ["Test Blade", "<shield>"],
        "free": ["<free-1h>", "<held>"],
        "free-two": ["<free-2h>", None],
        "free-free": ["<free>", "<free>"],
        "blade-free": ["Test Blade", "<free>"],
        "free-ward": ["<free>", "Ward of Tests"],
        "twin": ["Test Blade", "Test Blade"],
        "held": [None, "Lamp of Tests"],
    },
    "grid": {
        "presets": ["plain", "tanky"],
        "buffs": ["big", "small"],
        "setups": ["maul", "blade-ward"],
        "headline": "all",
    },
    "artifact": {
        "character_text": "synthetic",
        "preset_keys": {"plain": "pl", "tanky": "tk"},
        "assumptions": [],
        "terms": [],
    },
}


def small_pool():
    """Ten items that exercise the groups, the pairs, Lore, a two-hander, a one-hander, a shield and a held item."""
    return [
        legacy_item("cap-a", ["HEAD"], stats={"AC": 10, "HP": 30, "STA": 20}, wt=2.0),
        legacy_item("cap-b", ["HEAD"], stats={"AC": 6, "WIS": 25, "MANA": 40}, wt=1.5),
        legacy_item("stud-b", ["EAR"], stats={"DEX": 15, "HASTE": 22}),
        legacy_item("stud-c", ["EAR"], stats={"HP": 25, "HPREG": 6}, lore=True),
        legacy_item("band-a", ["FINGER"], stats={"STA": 14, "ENDREG": 4}, sv={"FIRE": 20}),
        legacy_item("plate-a", ["CHEST"], stats={"AC": 22, "STA": 10}, sv={"COLD": 15}, wt=4.0),
        legacy_item(
            "maul-a",
            ["PRIMARY"],
            stats={"STR": 20, "AC": 5},
            weapon=sword("2H Slashing", 30, 40),
            wt=6.0,
            name="Maul of Tests",
        ),
        legacy_item(
            "blade-a",
            ["PRIMARY", "SECONDARY"],
            stats={"DEX": 6, "HP": 10, "HASTE": 12},
            weapon=sword(),
            name="Test Blade",
        ),
        legacy_item("ward-a", ["SECONDARY"], stats={"AC": 12}, sv={"MAGIC": 10}, name="Ward of Tests"),
        legacy_item("lamp-a", ["SECONDARY"], stats={"HP": 20, "MANA": 15}, name="Lamp of Tests"),
    ]


def pool_json(items):
    return {"meta": {"built": "synthetic"}, "items": deepcopy(items)}


# ---- the tier rules, written out again ---------------------------------------------------------------------------


def tier_stat(base, n):
    return base + max(n, base * n // 10) if base > 0 else base


def tier_of(item, tier, quest_tier):
    t = quest_tier if (quest_tier is not None and item.get("tier_rule") == "quest") else tier
    return item["tier_override"] if item.get("tier_override") is not None else t


def view(item, tier, quest_tier=None):
    """(stats without HASTE, resists of the five schools, haste) of an item at a tier, by the old rules."""
    t = tier_of(item, tier, quest_tier)
    stats = {k: tier_stat(v, t) for k, v in item["stats"].items() if v and k != "HASTE"}
    haste = item["stats"].get("HASTE", 0)
    haste = haste + t if haste > 0 else haste
    sv = {k: tier_stat(v, t) for k, v in item["sv"].items() if v and k in SCHOOLS}
    return stats, sv, haste


def norm(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text).lower().replace("'", "")).split())


# ---- the legacy objective, in plain floats -------------------------------------------------------------------------


def pwl(x, breaks, slopes):
    """The old piecewise-linear curve of x (an array): slopes[i] times the part of x inside band i, from 0 up."""
    x = np.asarray(x, dtype=float)
    total = np.zeros_like(x)
    low = 0.0
    for brk, slope in zip(breaks, slopes):
        total += slope * np.clip(x - low, 0.0, brk - low)
        low = float(brk)
    return total + slopes[-1] * np.maximum(x - low, 0.0)


class Oracle:
    """The old objective of a profile under a scenario: ``gain(T, haste)`` is the value of the gear totals ``T`` (a
    float array over :data:`FEATURES`, one row per kit) minus the value of nothing worn."""

    def __init__(self, profile, scenario):
        pf = profile
        w = dict(pf["weights"])
        if scenario.get("preset"):
            w.update(pf["presets"][scenario["preset"]])
        w.update(scenario.get("weights", {}))
        self.w = w
        f = lambda key: float(w.get(key, 0))  # noqa: E731
        buffs = pf["buffs"][scenario["buffs"]] if scenario.get("buffs") else next(iter(pf["buffs"].values()))
        self.base = {a: float(pf["naked"][a] + buffs.get("attrs", {}).get(a, 0)) for a in ATTRS}
        ac = pf.get("ac", {})
        self.ac_cap = float(ac.get("cap", 439))
        self.ret = float(ac.get("ret", 0.33))
        self.sheet = ac.get("model") == "sheet"
        if self.sheet:
            self.mult = float(ac.get("mult", 4 / 3))
            self.nongear = float(ac.get("nongear", 0))
            self.acw_sheet = f("AC") / self.mult
        else:
            self.ac_cap -= float(ac.get("buff_share", 0))
        self.acw = f("AC")
        curves = pf.get("curves", {})
        post = dict(POST255_DEFAULT)
        post.update(pf.get("post255", {}))
        self.stat_terms = [(k, f(k), float(post[k])) for k in ("STR", "DEX", "AGI", "STA") if k not in curves and f(k)]
        capped = pf.get("caps", {})
        self.lin = [(k, f(k)) for k in FLAT_KEYS if k not in curves and f(k) and k not in capped]
        self.sv_w = f("SV")
        res = pf.get("res", {})
        self.res_cap = float(res.get("cap", 150))
        spell = float(buffs.get("spell_haste", 0))
        monk = False
        hc = pf.get("haste_cap")
        hc = float(hc) if hc is not None else (85.0 if monk else 75.0)
        self.haste_w = f("HASTE")
        self.haste_cap = max(0.0, hc - spell)
        self.curve_terms = []
        for attr in ATTRS:
            comps = curves.get(attr)
            for c in [comps] if isinstance(comps, dict) else (comps or []):
                factor = (f(c["from"]) if c.get("from") else f(attr)) * float(c.get("scale", 1))
                self.curve_terms.append(
                    (attr, factor, [float(b) for b in c["breaks"]], [float(s) for s in c["slopes"]])
                )
        sv_buff = buffs.get("sv", {}) if res.get("buffs_count_toward_cap") and any(buffs.get("sv", {}).values()) else {}
        self.sv_school = [(s, f("SV_" + s), self.res_cap, float(sv_buff.get(s, 0))) for s in SCHOOLS if f("SV_" + s)]
        self.capped = [(k, f(k), float(capped[k])) for k in REGEN if k in capped and f(k)]

    def value(self, T, haste):
        """The absolute objective of totals T (shape (kits, features)) and best worn haste per kit."""
        col = lambda name: T[:, FIX[name]]  # noqa: E731
        g, s = col("G"), col("S")
        if self.sheet:
            x = self.mult * (g + s) + self.nongear
            y = self.ac_cap + s
            v = self.acw_sheet * np.where(x <= y, x, y + self.ret * (x - y))
        else:
            eff = np.where(g <= self.ac_cap, g, self.ac_cap + self.ret * (g - self.ac_cap))
            v = self.acw * (eff + s)
        for k, w, rate in self.stat_terms:
            x = self.base[k] + col(k)
            x = np.where(x > 255, 255 + rate * (np.minimum(x, 510) - 255), x)
            v = v + w * x
        for k, w in self.lin:
            v = v + w * col(k)
        if self.sv_w:
            for school in SCHOOLS:
                v = v + self.sv_w * np.minimum(col(school), self.res_cap)
        if self.haste_w:
            v = v + np.where(haste > 0, self.haste_w * np.minimum(haste, self.haste_cap), 0.0)
        for attr, factor, br, sl in self.curve_terms:
            v = v + factor * pwl(self.base[attr] + col(attr), br, sl)
        for school, w, cap, b in self.sv_school:
            v = v + w * np.minimum(col(school) + b, cap)
        for k, w, cap in self.capped:
            v = v + w * np.minimum(col(k), cap)
        return v

    def gain(self, T, haste):
        zero = self.value(np.zeros((1, len(FEATURES))), np.zeros(1))[0]
        return self.value(T, haste) - zero


# ---- the legal assignments, by the old rules ------------------------------------------------------------------------


def is_two_hander(item):
    return str((item.get("weapon") or {}).get("skill", "")).startswith("2H")


def is_shield(item):
    if isinstance(item.get("shield"), bool):
        return item["shield"]
    return not item.get("weapon") and "SECONDARY" in item["slots"] and (item["stats"].get("AC") or 0) > 0


def eligible(profile, pool_items, scenario):
    """The items the old tools would use: class, temporary, deity, required level and the caller's exclusions."""
    trio = set(profile["classes"])
    level = profile.get("level", 50)
    out = []
    for it in pool_items:
        classes = set(it["classes"])
        if "ALL" not in classes and not classes & trio:
            continue
        if not scenario.get("include_temporary") and "temporary" in it.get("flags", ()):
            continue
        want = scenario.get("deity")
        if want and it.get("deity") and norm(want) not in norm(it["deity"]):
            continue
        if it["id"] in set(scenario.get("exclude", ())):
            continue
        if it.get("required_level") is not None and it["required_level"] > level:
            continue
        out.append(it)
    return out


def is_lore(item, lore_unknown):
    return item["lore"] is True or (item["lore"] is None and lore_unknown == "lore")


def hand_groups(profile, items, name):
    """((fixed [(hand, item)], variable [(hand, candidate items)]) of a weapon setup, by the documented token rules."""
    pair = profile["weapon_setups"][name] if name else [None, None]
    by_name = {}
    for it in items:
        by_name.setdefault(norm(it["name"]), it)
    fixed, variable = [], []
    prim, sec = pair

    def named(token):
        if norm(token) not in by_name:
            raise ValueError(f"{token!r} is not among the usable items")
        return by_name[norm(token)]

    if prim is not None and not prim.startswith("<"):
        fixed.append(("PRIMARY", named(prim)))
    if sec is not None and not sec.startswith("<"):
        fixed.append(("SECONDARY", named(sec)))
    if prim == "<free>":
        keep_one_hand = any(h == "SECONDARY" for h, _ in fixed)
        variable.append(
            ("PRIMARY", [i for i in items if "PRIMARY" in i["slots"] and not (keep_one_hand and is_two_hander(i))])
        )
    elif prim == "<free-2h>":
        variable.append(("PRIMARY", [i for i in items if "PRIMARY" in i["slots"] and is_two_hander(i)]))
    elif prim == "<free-1h>":
        variable.append(("PRIMARY", [i for i in items if "PRIMARY" in i["slots"] and not is_two_hander(i)]))
    if sec == "<free>":
        variable.append(("SECONDARY", [i for i in items if "SECONDARY" in i["slots"]]))
    elif sec == "<shield>":
        variable.append(
            (
                "SECONDARY",
                [
                    i
                    for i in items
                    if "SECONDARY" in i["slots"] and not i.get("weapon") and i.get("shield") is not False
                ],
            )
        )
    elif sec == "<held>":
        variable.append(("SECONDARY", [i for i in items if "SECONDARY" in i["slots"] and not i.get("weapon")]))
    return fixed, variable


def any_fits(item, rule):
    if rule == "armor":
        return not item.get("weapon") and any(s in ARMOR_SLOTS for s in item["slots"])
    return bool(item["slots"])


def vector(item, tier, quest_tier, offhand):
    """The feature row of one worn item: its AC goes to the shield column only when it is the off-hand shield."""
    stats, sv, _ = view(item, tier, quest_tier)
    row = np.zeros(len(FEATURES))
    shield_here = offhand and not item.get("weapon") and is_shield(item)
    for key, val in stats.items():
        if key == "AC":
            row[FIX["S" if shield_here else "G"]] += val
        elif key in FIX:
            row[FIX[key]] += val
    for school, val in sv.items():
        row[FIX[school]] += val
    return row


def options(cands, size):
    out = [()]
    out += [(c,) for c in cands]
    if size == 2:
        for i, a in enumerate(cands):
            for b in cands[i:]:
                out.append((a, b))
    return out


def best_gain(profile, pool_items, scenario, limit=400_000, want_kit=False):
    """The best gain over every legal assignment, by brute force under the old rules (``None`` if there are too many).
    With ``want_kit`` the answer is ``(gain, {group: [ids]})`` of one best assignment, fixed hand items included.

    ``scenario`` has the keys of ``from_legacy``'s: preset, buffs, weapons, tier, quest_tier, weights, exclude,
    lore_unknown, any_rule, include_temporary, deity.
    """
    items = eligible(profile, pool_items, scenario)
    tier, quest_tier = scenario.get("tier", 10), scenario.get("quest_tier")
    lore_unknown, rule = scenario.get("lore_unknown", "lore"), scenario.get("any_rule", "all")
    oracle = Oracle(profile, scenario)
    fixed, variable = hand_groups(profile, items, scenario.get("weapons"))

    groups = []  # (name, size, cands, offhand)
    for name in BODY:
        cands = [i for i in items if name in i["slots"]]
        if cands:
            groups.append((name, PLACES.get(name, 1), cands, False))
    anyc = [i for i in items if any_fits(i, rule)]
    if anyc:
        groups.append(("ANY", 2, anyc, False))
    for hand, cands in variable:
        if cands:
            groups.append((hand, 1, cands, hand == "SECONDARY"))

    lore_keys = sorted({i["id"] for i in items if is_lore(i, lore_unknown)})
    lk = {k: n for n, k in enumerate(lore_keys)}
    base_vec = np.zeros(len(FEATURES))
    base_haste = 0.0
    base_lore = np.zeros(len(lore_keys))
    for hand, it in fixed:
        base_vec += vector(it, tier, quest_tier, hand == "SECONDARY")
        base_haste = max(base_haste, view(it, tier, quest_tier)[2])
        if is_lore(it, lore_unknown):
            base_lore[lk[it["id"]]] += 1

    total = 1
    tables = []
    for name, size, cands, offhand in groups:
        opts = options(cands, size)
        total *= len(opts)
        if total > limit:
            return None
        feat = np.zeros((len(opts), len(FEATURES)))
        haste = np.zeros(len(opts))
        lore = np.zeros((len(opts), len(lore_keys)))
        twoh = np.zeros(len(opts), dtype=bool)
        filled = np.zeros(len(opts), dtype=bool)
        for n, opt in enumerate(opts):
            for it in opt:
                feat[n] += vector(it, tier, quest_tier, offhand)
                haste[n] = max(haste[n], view(it, tier, quest_tier)[2])
                if is_lore(it, lore_unknown):
                    lore[n, lk[it["id"]]] += 1
                if name == "PRIMARY" and is_two_hander(it):
                    twoh[n] = True
            filled[n] = bool(opt)
        tables.append((name, feat, haste, lore, twoh, filled))

    if not tables:
        only = float(oracle.gain((base_vec[None, :]), np.array([max(base_haste, 0.0)]))[0])
        return (only, {hand: [it["id"]] for hand, it in fixed}) if want_kit else only
    grids = np.meshgrid(*[np.arange(len(t[1])) for t in tables], indexing="ij")
    idx = [g.reshape(-1) for g in grids]
    n_kits = idx[0].shape[0]
    T = np.tile(base_vec, (n_kits, 1))
    haste = np.full(n_kits, base_haste)
    lore = np.tile(base_lore, (n_kits, 1))
    for (name, feat, h, lo, twoh, filled), ix in zip(tables, idx):
        T += feat[ix]
        haste = np.maximum(haste, h[ix])
        lore += lo[ix]
    ok = np.ones(n_kits, dtype=bool) if not lore_keys else np.all(lore <= 1, axis=1)
    names = [t[0] for t in tables]
    if "PRIMARY" in names and "SECONDARY" in names:
        p, s = names.index("PRIMARY"), names.index("SECONDARY")
        ok &= ~(tables[p][4][idx[p]] & tables[s][5][idx[s]])
    gains = oracle.gain(T[ok], haste[ok])
    if not want_kit:
        return float(gains.max())
    kit_index = np.flatnonzero(ok)[int(np.argmax(gains))]
    kit = {hand: [it["id"]] for hand, it in fixed}
    for (name, *_), table, ix in zip(tables, [opts for opts in [options(g[2], g[1]) for g in groups]], idx):
        kit.setdefault(name, []).extend(it["id"] for it in table[ix[kit_index]])
    return float(gains.max()), kit
