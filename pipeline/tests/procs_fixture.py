"""The fixture of the browser's port of the table of procs: tables, items and what Python's :class:`trioforge.model.procs.ProcTable` answers for them.

``fixtures/procs/table.json`` is made by this file (``python pipeline/tests/procs_fixture.py``; a test holds the committed file to what this makes). It holds seeded random tables (invented effects and
donors, some of them Lore items, some for the primary hand only), and for each, random items at random tiers with the answers Python gives for each hand (``every``, ``candidates``
and ``sources`` of every effect) and for random pairs of hands with the Lore items a kit may wear (``best``). The browser's port (``static/engine/procs.js``) must give them all, entry for
entry; the values are reduced ``"p/q"`` texts.
"""

from __future__ import annotations

import json
import random
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

from trioforge.model import procs as procs_module
from trioforge.model.items import ItemVec

REPO = Path(__file__).resolve().parents[2]
PATH = REPO / "fixtures" / "procs" / "table.json"
SEED = "trioforge-procs-fixture"
TABLES = 10
TRIOS = (("WAR", "SHM", "ENC"), ("PAL", "MNK", "BER"), ("CLR", "DRU", "WIZ"))
SLOT_SETS = (("PRIMARY", "SECONDARY"), ("PRIMARY",), ("SECONDARY",), ("PRIMARY", "SECONDARY", "ANY"), ("RANGE",), ("HEAD",))
ALL_CLASSES = ("WAR", "PAL", "SHD", "RNG", "MNK", "BER", "ROG", "BRD", "CLR", "DRU", "SHM", "NEC", "WIZ", "MAG", "ENC")


def _text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _entry(entry: Any) -> list[Any] | None:
    return None if entry is None else [entry.effect, entry.name, entry.donor, entry.mode, _text(Fraction(entry.value))]


def _item(rng: random.Random, key: str, trio: tuple[str, ...]) -> dict[str, Any]:
    classes = sorted(rng.sample(ALL_CLASSES, rng.randint(1, 5)) if rng.random() < 0.8 else ALL_CLASSES)
    if rng.random() < 0.7:
        classes = sorted({*classes, rng.choice(trio)})
    return {"key": key, "slots": sorted(rng.choice(SLOT_SETS)), "classes": classes, "tier": rng.choice((0, 3, 4, 4, 5, 10))}


def _vec(spec: dict[str, Any]) -> ItemVec:
    return ItemVec(
        key=spec["key"], name=spec["key"], slots=frozenset(spec["slots"]), classes=frozenset(spec["classes"]), deity=None, lore=False,
        stats={}, sv={}, haste=0, weight10=0, weapon=None, is_shield=False, tier=spec["tier"],
    )


def _table(rng: random.Random, number: int) -> dict[str, Any]:
    trio = TRIOS[number % len(TRIOS)]
    keys = [f"it{n:02d}" for n in range(rng.randint(5, 7))]
    items = [_item(rng, key, trio) for key in keys]
    effects = [
        procs_module.ProcEffect(f"e{n}", f"Effect {n}", Fraction(rng.randint(40, 900)) / rng.choice((1, 1, 3, 7, 12))) for n in range(rng.randint(2, 5))
    ]
    donors = []
    for effect in effects:
        for spec in rng.sample(items, rng.randint(1, 3)):
            usable = frozenset(c for c in trio if c in spec["classes"])
            if usable:
                donors.append(procs_module.ProcDonor(effect.id, spec["key"], frozenset(spec["slots"]), usable, rng.random() < 0.25, rng.random() < 0.4))
    # a donor of an item is one item: the flags of an item are the same for all its effects
    lore = {d.key: d.lore for d in donors}
    donors = [procs_module.ProcDonor(d.effect, d.key, d.slots, d.classes, d.primary_only, lore[d.key]) for d in donors]
    kept = {d.effect for d in donors}
    table = procs_module.ProcTable(trio, 4, tuple(e for e in effects if e.id in kept), tuple(donors))
    answers = []
    for spec in items:
        item = _vec(spec)
        row: dict[str, Any] = {"item": spec}
        for hand in ("PRIMARY", "SECONDARY"):
            row[hand] = {
                "every": [_entry(e) for e in table.every(item, hand)],
                "candidates": [_entry(e) for e in table.candidates(item, hand)],
                "sources": {e.id: list(table.sources(item, hand, e.id)) for e in table.effects},
            }
        answers.append(row)
    lore_keys = sorted(table.lore_keys)
    pairs = []
    for _ in range(24):
        first, second = rng.choice(items), rng.choice(items)
        factor = rng.choice((Fraction(1, 2), Fraction(4, 5), Fraction(1), Fraction(3, 10)))
        worn = sorted(rng.sample(lore_keys, rng.randint(0, len(lore_keys)))) if lore_keys and rng.random() < 0.6 else []
        second = second if rng.random() < 0.9 else None  # (a hand that swings nothing)
        main, off = table.best(_vec(first), None if second is None else _vec(second), factor, frozenset(worn))
        pairs.append({"primary": first, "secondary": second, "factor": _text(factor), "worn": worn, "best": [_entry(main), _entry(off)]})
    return {"trio": list(trio), "procs": procs_module.to_doc(table), "items": answers, "pairs": pairs}


def document() -> dict[str, Any]:
    rng = random.Random(SEED)
    return {"kind": "procs", "tables": [_table(rng, number) for number in range(TABLES)]}


def text() -> str:
    return json.dumps(document(), indent=1, ensure_ascii=False) + "\n"


def write_all() -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(text(), encoding="utf-8", newline="\n")
    print(f"wrote {PATH.relative_to(REPO).as_posix()} ({len(text().encode('utf-8')):,} bytes)")


if __name__ == "__main__":
    sys.exit(write_all())
