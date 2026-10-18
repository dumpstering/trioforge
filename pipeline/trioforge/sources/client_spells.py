"""Beneficial spell effects from the client's spell file (``spells_us.txt``).

``spells_us.txt`` holds one spell per line, ``^`` separated. The columns that matter here (counting
from zero):

=========  ===========================================================================================
column     meaning
=========  ===========================================================================================
0          spell id
1          name
11, 12     duration formula and its cap, in ticks of six seconds
28         beneficial flag: 0 detrimental, 1 beneficial, 2 beneficial for the group only
30         target type, kept as the client writes it
36 to 51   the level at which each class gets the spell, in class-id order (WAR CLR PAL RNG SHD DRU
           MNK BRD ROG SHM NEC WIZ MAG ENC BST BER); 255 means the class cannot use it
last       the effect slots: ``slot|spa|base|limit|formula|max``, one group per slot, joined by ``$``
=========  ===========================================================================================

The effect slots are read from the **last** column, not from a fixed number, because the client has
added a column in the middle of this file before (patches leave the first 52 columns and the last one
where they are). A row that has fewer than 173 columns, or that holds no effect slots anywhere in
the file, is refused as a layout this reader does not know, and so is a file whose rows do not all
have the same number of columns.

:func:`read_beneficial` turns the file into the beneficial spells a character of a given level can
use, one record per spell::

    {"id", "name", "classes": {code: level}, "target", "duration_ticks", "permanent",
     "effects": [{"slot", "spa", "name", "base", "limit", "formula", "max", "value"}],
     "stacking": [{"slot", "spa", "kind", "base", "limit", "max"}]}

* A spell is kept when it is beneficial (flag 1, or flag 2 for a spell that can only be cast on the
  caster's group, such as a bard song), at least one class gets it at or below ``level``, it lasts
  (an instant spell is not a buff), and at least one effect has a stat-type SPA (an effect id, see
  :data:`STAT_SPA`). ``classes`` lists only the classes that get it at or below ``level``.
* ``value`` is the effect's number for a caster of ``level``: the client's formula applied to ``base``
  and clamped to ``max`` (:func:`formula_value`). A formula this module does not know gives ``None``,
  and is counted in ``unknown_formulas``.
* ``duration_ticks`` is the duration at ``level`` (formula, then cap); ``None`` with ``permanent``
  true for a permanent spell.
* SPA 148 and 149 are stacking commands; they go to ``stacking`` (``kind`` is the SPA as text, ``"148"``
  or ``"149"``), with the raw ``base``, ``limit`` and ``max`` (the threshold of the command: ``max`` is
  kept, not only the base), and never to ``effects``. Limit SPAs (they
  restrict which spells a focus applies to) stay in ``effects`` with the name ``"LIMIT"`` and no
  value. Blank slots (SPA 254) and the spacer (SPA 10 with base 0) are dropped.

Reading **fails closed**, like the tables in :mod:`trioforge.sources.client_tables`: only blank lines
and lines that start with ``#`` are skipped, any other line that is not a spell row raises
:class:`ValueError` naming the line number and never its text, the file must be plain ASCII (a byte
order mark is dropped), a repeated spell id is an error, and so is a value out of range (a class
level above 255, a beneficial flag that is not 0, 1 or 2, a negative number where none is possible).
The columns that decide whether a spell is kept (id, class levels, beneficial flag) are checked on
every row; those that describe a kept spell (duration, target, effects) only on the rows that get
that far, because the client's file holds rows nobody can cast with odd values in them.

The command line writes ``spells-l50.json`` and ``spells-l55.json`` and adds ``spells_us.txt`` to
``manifest.json``::

    python -m trioforge.sources.client_spells --client-dir DIR --out derived/client

It refuses a level that has fewer than ``MINIMUM_ROWS["spells"]`` kept spells, makes both texts before it
writes anything, and writes all or nothing, the manifest last
(:func:`trioforge.sources.client_tables.commit_files`). The game file is read as text and never copied.
"""

import argparse
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import trioforge
from trioforge.classes import CLASS_CODES
from trioforge.sources import client_tables as tables

__all__ = [
    "CLASS_CODES",
    "GENERATOR",
    "LEVELS",
    "LIMIT_SPA",
    "SPELLS_FILE",
    "STAT_SPA",
    "duration_ticks",
    "formula_value",
    "generate",
    "main",
    "read_beneficial",
]

SPELLS_FILE = "spells_us.txt"
GENERATOR = f"trioforge.sources.client_spells {trioforge.__version__}"
LEVELS = (50, 55)

# 0-based columns
ID, NAME, DURATION_FORMULA, DURATION_CAP, BENEFICIAL, TARGET, FIRST_CLASS_LEVEL = 0, 1, 11, 12, 28, 30, 36
MIN_FIELDS = 173  # the effect column is the last one, so the width may grow
LARGEST_BENEFICIAL_FLAG = 2  # 0 detrimental, 1 beneficial, 2 beneficial for the group only
LARGEST_CLASS_LEVEL = 255  # 255 means the class cannot use the spell

STACKING_SPA = (148, 149)

# Effect ids (SPAs) of the stat-type effects the planner reads, and what they are called.
STAT_SPA = {
    0: "HP_regen", 1: "AC", 2: "ATK", 3: "runspeed", 4: "STR", 5: "DEX", 6: "AGI", 7: "STA", 8: "INT", 9: "WIS",
    10: "CHA", 11: "haste", 15: "mana_regen", 46: "FR", 47: "CR", 48: "PR", 49: "DR", 50: "MR", 55: "rune",
    59: "DS", 69: "maxHP", 79: "instant_HP", 85: "proc", 97: "maxMana", 98: "haste_v2", 100: "HoT", 111: "all_resists",
    119: "haste_v3", 120: "heal_mod", 124: "spell_dmg", 127: "spell_haste", 161: "spell_mitig", 162: "melee_mitig",
    168: "melee_mitig2", 169: "crit", 171: "crip_blow", 172: "avoid", 173: "riposte", 174: "dodge", 175: "parry",
    176: "dual_wield", 177: "double_attack", 180: "spell_resist_chance", 181: "fearless", 182: "slow_v2",
    183: "skill_check", 184: "hit_chance", 185: "dmg_mod", 186: "dmg_mod_skill", 188: "block", 189: "end_regen",
    190: "maxEnd", 191: "end_cost", 192: "hate", 193: "skill_attack", 216: "accuracy", 220: "skill_dmg_bonus",
    262: "stat_cap", 266: "extra_attack", 273: "dot_crit", 294: "spell_crit", 323: "def_proc", 337: "exp_bonus",
    363: "max_buff", 367: "add_proc",
}

# Effect ids that only limit which spells or items a focus applies to.
LIMIT_SPA = frozenset(
    {134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 311, 385, 348, 411, 414, 415, 416, 412, 413, 403, 404, 460, 486,
     479, 480, 497, 498, 499, 500, 501, 502}
)

_WHOLE = re.compile(r"-?[0-9]+")
_DECIMAL = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
_SPELL_ID = re.compile(r"[0-9]{1,12}")


def formula_value(base: int | float, formula: int, maximum: int | float, level: int) -> tuple[int | float | None, bool]:
    """The number an effect has for a caster of ``level``: ``(value, formula_known)``.

    The client states an effect as a ``base``, a ``formula`` that grows it with the caster's level and a
    ``maximum`` that stops the growth. A ``maximum`` below the ``base`` makes the effect shrink instead
    (``sign`` -1); a negative ``base`` keeps the value negative. An unknown ``formula`` gives
    ``(None, False)``.
    """
    ub = abs(base)
    sign = -1 if (maximum != 0 and maximum < base) else 1
    lvl = level
    f = formula
    if f in (0, 100):
        r = ub
    elif f in (60, 70):
        r = ub // 100
    elif f == 101:
        r = sign * (ub + lvl // 2)
    elif f == 102:
        r = sign * (ub + lvl)
    elif f == 103:
        r = sign * (ub + 2 * lvl)
    elif f == 104:
        r = sign * (ub + 3 * lvl)
    elif f == 105:
        r = sign * (ub + 4 * lvl)
    elif f == 107:
        r = sign * (ub + lvl // 2)
    elif f == 108:
        r = sign * (ub + lvl // 3)
    elif f == 109:
        r = sign * (ub + lvl // 4)
    elif f == 110:
        r = ub + lvl // 5
    elif f == 111:
        r = sign * (ub + 6 * (lvl - 16))
    elif f == 112:
        r = sign * (ub + 8 * (lvl - 24))
    elif f == 113:
        r = sign * (ub + 10 * (lvl - 34))
    elif f == 114:
        r = sign * (ub + 15 * (lvl - 44))
    elif f == 115:
        r = ub + (7 * (lvl - 15) if lvl > 15 else 0)
    elif f == 116:
        r = ub + (10 * (lvl - 24) if lvl > 24 else 0)
    elif f == 117:
        r = ub + (12 * (lvl - 34) if lvl > 34 else 0)
    elif f == 118:
        r = ub + (20 * (lvl - 44) if lvl > 44 else 0)
    elif f == 119:
        r = ub + lvl // 8
    elif f in (120, 121):
        r = ub + lvl // 3
    elif 124 <= f <= 132:
        multiplier = {124: 1, 125: 2, 126: 3, 127: 4, 128: 5, 129: 10, 130: 15, 131: 20, 132: 25}[f]
        r = ub + (sign * multiplier * (lvl - 50) if lvl > 50 else 0)
    elif f == 139:
        r = ub + ((lvl - 30) // 2 if lvl > 30 else 0)
    elif f == 140:
        r = ub + (lvl - 30 if lvl > 30 else 0)
    elif f == 141:
        r = ub + ((3 * lvl - 90) // 2 if lvl > 30 else 0)
    elif f == 142:
        r = ub + (2 * lvl - 60 if lvl > 30 else 0)
    elif f == 143:
        r = ub + (3 * lvl) // 4
    elif 0 < f < 100:
        r = ub + lvl * f
    elif 2000 <= f <= 2650:
        r = ub * (lvl * (f - 2000) + 1)
    else:
        return None, False
    if maximum != 0:
        if sign == 1 and r > maximum:
            r = maximum
        if sign == -1 and r < maximum:
            r = maximum
    if base < 0 and r > 0:
        r = -r
    return r, True


def duration_ticks(formula: int, cap: int, level: int) -> tuple[int | None, bool]:
    """A spell's duration for a caster of ``level``: ``(ticks, permanent)``.

    A tick is six seconds. The duration formula gives a length from the level and the ``cap`` stops it
    (a cap of 0 means no cap). Formulas 50 and 51 are permanent: ``(None, True)``. An unknown formula
    lasts as long as its cap.
    """
    f = formula
    if f == 0:
        ticks = 0
    elif f == 1:
        ticks = -(-level // 2)
    elif f == 2:
        ticks = -(-level * 6 // 10)
    elif f == 3:
        ticks = level * 30
    elif f == 4:
        ticks = 50 if cap == 0 else cap
    elif f == 5:
        ticks = 2
    elif f == 6:
        ticks = -(-level // 2) + 2
    elif f == 7:
        ticks = level
    elif f == 8:
        ticks = level + 10
    elif f == 9:
        ticks = 2 * level + 10
    elif f == 10:
        ticks = 3 * level + 10
    elif f == 11:
        ticks = 30 * (level + 3)
    elif f == 12:
        ticks = max(1, level // 4)
    elif f == 13:
        ticks = 4 * level + 10
    elif f == 14:
        ticks = 5 * level + 10
    elif f == 15:
        ticks = 5 * level + 50
    elif f in (50, 51):
        return None, True
    elif f == 3600:
        ticks = 3600
    else:
        ticks = cap
    if cap and ticks > cap:
        ticks = cap
    return ticks, False


# ---- reading --------------------------------------------------------------------------------


def _number(path: Path, number: int, text: str, what: str) -> int | float:
    """A finite number, whole or with a decimal point, of either sign."""
    if _WHOLE.fullmatch(text) is not None:
        if len(text) > 40:
            raise tables.problem(path, number, f"{what} is out of range")
        return int(text)
    if _DECIMAL.fullmatch(text) is None:
        raise tables.problem(path, number, f"{what} is not a number")
    value = float(text)
    if not math.isfinite(value):
        raise tables.problem(path, number, f"{what} is out of range")
    return value


def _effect_groups(
    path: Path, number: int, text: str
) -> list[tuple[int, int, int | float, int | float, int, int | float]]:
    """The ``slot|spa|base|limit|formula|max`` groups of an effect column, blank and spacer slots dropped."""
    groups = []
    for group in text.split("$"):
        parts = group.split("|")
        if len(parts) < 6:
            continue  # an empty column, or the "0" a spell without effects has
        if len(parts) > 6:
            raise tables.problem(path, number, "an effect slot has more than six values")
        slot = tables.whole(path, number, parts[0], "effect slot")
        spa = tables.whole(path, number, parts[1], "effect id")
        base = _number(path, number, parts[2], "effect base")
        limit = _number(path, number, parts[3], "effect limit")
        formula = tables.whole(path, number, parts[4], "effect formula")
        maximum = _number(path, number, parts[5], "effect max")
        if spa == 254 or (spa == 10 and base == 0):
            continue
        groups.append((slot, spa, base, limit, formula, maximum))
    return groups


def read_beneficial(path: str | os.PathLike[str], level: int) -> dict[str, Any]:
    """The beneficial spells a character of ``level`` can use, with their effect values at that level.

    Returns ``{"level", "unknown_formulas": {formula: count}, "spells": [...]}``; the spells are sorted by
    id and described in the module docstring, and ``unknown_formulas`` keys are text so the result
    round-trips through JSON. Raises :class:`ValueError`, naming the line and never its text, for anything
    the module docstring lists, and when the file has no spell rows or no spell row has effect slots in its
    last column (the layout changed).
    """
    if type(level) is not int or not 1 <= level <= 254:
        raise ValueError(f"level must be a whole number from 1 to 254, not {level!r}")
    source = Path(path)
    spells = []
    unknown: Counter[int] = Counter()
    first_line: dict[int, int] = {}
    rows = rows_with_effects = 0
    width = None
    for number, text in tables.read_lines(source):
        if not text.strip() or text.startswith("#"):
            continue
        fields = text.split("^")
        if _SPELL_ID.fullmatch(fields[ID]) is None:
            raise tables.problem(source, number, "the first column is not a spell id")
        if len(fields) < MIN_FIELDS:
            raise tables.problem(source, number, f"expected at least {MIN_FIELDS} columns, found {len(fields)}")
        if width is None:
            width = len(fields)
        elif len(fields) != width:
            raise tables.problem(source, number, f"expected {width} columns like the first row, found {len(fields)}")
        tables.remember(source, number, first_line, int(fields[ID]), "spell id")
        rows += 1
        if "|" in fields[-1]:
            rows_with_effects += 1
        classes = {}
        for position, code in enumerate(CLASS_CODES):
            column = fields[FIRST_CLASS_LEVEL + position]
            at = tables.whole(source, number, column, f"{code} level", high=LARGEST_CLASS_LEVEL)
            if 0 < at <= level:
                classes[code] = at
        beneficial = tables.whole(source, number, fields[BENEFICIAL], "beneficial flag", high=LARGEST_BENEFICIAL_FLAG)
        if not classes or beneficial == 0:
            continue
        ticks, permanent = duration_ticks(
            tables.whole(source, number, fields[DURATION_FORMULA], "duration formula"),
            tables.whole(source, number, fields[DURATION_CAP], "duration cap"),
            level,
        )
        if not permanent and ticks == 0:
            continue  # instant: not a buff
        effects: list[dict[str, Any]] = []
        stacking: list[dict[str, Any]] = []
        unknown_here: Counter[int] = Counter()
        for slot, spa, base, limit, formula, maximum in _effect_groups(source, number, fields[-1]):
            if spa in STACKING_SPA:
                stacking.append({"slot": slot, "spa": spa, "kind": str(spa), "base": base, "limit": limit, "max": maximum})
                continue
            name = "LIMIT" if spa in LIMIT_SPA else STAT_SPA.get(spa, f"SPA{spa}")
            effect = {
                "slot": slot,
                "spa": spa,
                "name": name,
                "base": base,
                "limit": limit,
                "formula": formula,
                "max": maximum,
                "value": None,
            }
            if spa not in LIMIT_SPA:
                effect["value"], known = formula_value(base, formula, maximum, level)
                if not known:
                    unknown_here[formula] += 1
            effects.append(effect)
        if not any(effect["spa"] in STAT_SPA for effect in effects):
            continue
        unknown.update(unknown_here)
        spells.append(
            {
                "id": int(fields[ID]),
                "name": fields[NAME],
                "classes": classes,
                "target": tables.whole(source, number, fields[TARGET], "target"),
                "duration_ticks": ticks,
                "permanent": permanent,
                "effects": effects,
                "stacking": stacking,
            }
        )
    tables.enough_rows(source, rows)
    if rows >= 100 and rows_with_effects == 0:
        raise ValueError(f"{source.name}: no spell row has effect slots in its last column; has the layout changed?")
    spells.sort(key=lambda spell: spell["id"])
    return {
        "level": level,
        "unknown_formulas": {str(formula): unknown[formula] for formula in sorted(unknown)},
        "spells": spells,
    }


# ---- the command line -----------------------------------------------------------------------


def generate(client_dir: str | os.PathLike[str], out_dir: str | os.PathLike[str], generated: str) -> list[str]:
    """Read ``spells_us.txt`` once per level, write ``spells-l<level>.json`` and update the manifest.

    The old manifest is read and checked first, both levels are read and checked and every text is made
    before the first file is written, and the files are then put in place all or nothing, the manifest
    last. A level with fewer kept spells than ``MINIMUM_ROWS["spells"]`` is refused.
    """
    root = Path(client_dir)
    if not (root / SPELLS_FILE).is_file():
        raise tables.MissingInput(f"missing input file: {SPELLS_FILE}")
    out = Path(out_dir)
    known = tables.read_manifest(out)
    record, results = tables.read_checked(
        root, SPELLS_FILE, lambda path: [read_beneficial(path, level) for level in LEVELS]
    )
    floor = tables.MINIMUM_ROWS["spells"]
    for result in results:
        if len(result["spells"]) < floor:
            raise ValueError(
                f"{SPELLS_FILE}: only {len(result['spells'])} beneficial spells at level {result['level']}, "
                f"fewer than the {floor} a whole file has"
            )
    texts = {}
    outputs = []
    summary = []
    for result in results:
        name = f"spells-l{result['level']}.json"
        texts[name] = tables.render_json({"provenance": tables.provenance([record], generated, GENERATOR), **result})
        outputs.append({"file": name, "inputs": [SPELLS_FILE], "generated": generated})
        summary.append(f"{name}: {len(result['spells'])} spells, unknown formulas {result['unknown_formulas']}")
    texts[tables.MANIFEST_FILE] = tables.render_json(tables.merge_manifest(known, [record], outputs, generated))
    tables.commit_files(out, texts)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.sources.client_spells",
        description="Write the client's beneficial spell effects at levels 50 and 55 as derived JSON.",
    )
    parser.add_argument(
        "--client-dir",
        type=Path,
        help=f"install folder (default: ${tables.ENV_CLIENT_DIR}, else the stock folder under %%PUBLIC%%)",
    )
    parser.add_argument("--out", type=Path, default=Path("derived/client"), help="output folder")
    parser.add_argument("--date", type=tables.iso_date, help="generation date, YYYY-MM-DD (default: today in UTC)")
    args = parser.parse_args(argv)
    client_dir = tables.resolve_client_dir(args.client_dir)
    if client_dir is None:
        print(f"error: no client folder: pass --client-dir or set {tables.ENV_CLIENT_DIR}", file=sys.stderr)
        return 2
    generated = args.date or tables.today_utc()
    try:
        summary = generate(client_dir, args.out, generated)
    except (OSError, ValueError) as exc:
        print(f"error: {tables.one_line(exc)}", file=sys.stderr)
        return 2
    print("\n".join(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
