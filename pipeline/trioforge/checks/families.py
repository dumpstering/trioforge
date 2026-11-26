"""What the item table says about armour and about sets, read from the table alone.

**Armour classes** (:func:`armour_classes`). The catalog has no armour type: a robe, a tunic and a breastplate differ only by the classes that may wear them. So
"the heaviest armour" is read from those class lists, of the **pool** alone (the items a solve pool holds: level strict or wiki, no deity lock, not marked not-for-bis; a hidden
or disputed item is worn by no kit, and what it lists says nothing of what one can wear). A **generic set** is a list of at least three classes that at least ``min_items`` items
of the pool hold in *each* of the six armour slots (chest, legs, arms, head, hands, feet); ``ALL`` is every class. They nest: every class, every class but the four cloth casters,
the classes that wear chain or plate, the classes that wear plate; the cloth casters have a list of their own. The **reach** of a class is the number of generic sets it is in. The
**heavy** classes are those of the greatest reach (none when every class has the same reach: the table then has no armour weights). The **cloth** classes are
those that are outside the largest generic set that is not every class. A **robe** (:func:`is_robe`) is a piece of casters: it lists a cloth class, every class it lists is a
caster class of the model (so a piece that a Monk, a Rogue or a Beastlord also wears, a strap of cloth, leather and chain wearers, is none), and it lists no heavy class.

**Set stems** (:func:`stem_of`, :func:`set_stems`). A set of armour is named by what its pieces share: ``Vlorn Cap``, ``Vlorn Boots`` ... share the stem
``vlorn``; ``Crown of the Zindrel`` and ``Ring of the Zindrel`` share ``of zindrel``. A name that has ``of`` takes what follows the last ``of``, without a leading
article; any other name takes all its words but the last; a name of one word has no stem. A stem is a **set** when at least ``min_items`` items of the pool
(evidence level strict or wiki, no deity lock) carry it, in at least ``min_slots`` different slot groups.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from trioforge.checks.results import WEARABLE_SLOTS, ItemTable
from trioforge.classes import CLASS_CODES
from trioforge.model.roles import CASTER_CLASSES

__all__ = [
    "ARMOUR_SLOTS",
    "MIN_SET_CLASSES",
    "MIN_SET_ITEMS",
    "MIN_SET_SLOTS",
    "MIN_STEM_ITEMS",
    "ArmourClasses",
    "armour_classes",
    "is_robe",
    "set_stems",
    "stem_of",
]

#: the six armour slots, the ones a class's armour weight decides
ARMOUR_SLOTS = ("CHEST", "LEGS", "ARMS", "HEAD", "HANDS", "FEET")
MIN_SET_ITEMS = 3  # items of the pool that hold one list of classes, in each armour slot, for the list to be a generic set (2 to 4 give the same heavy and cloth classes)
MIN_SET_CLASSES = 3  # classes a list must hold to be generic: a list of one or two classes is the armour of a class, a quest piece
MIN_SET_SLOTS = 4  # different slot groups a stem must be found in to be a set
MIN_STEM_ITEMS = 3  # different items that must carry it
_ALL = frozenset(CLASS_CODES)
_ARTICLE = re.compile(r"^(?:the|a|an)\s+")
_PARENTHESIS = re.compile(r"\s*\([^)]*\)\s*$")


@dataclass(frozen=True)
class ArmourClasses:
    """The generic sets of the pool, the classes of the greatest reach (``heavy``), the classes of cloth only (``cloth``) and the classes that cast (``casters``)."""

    sets: tuple[frozenset[str], ...]
    heavy: frozenset[str]
    cloth: frozenset[str]
    casters: frozenset[str] = frozenset(CASTER_CLASSES)


def armour_classes(table: ItemTable, *, min_items: int = MIN_SET_ITEMS) -> ArmourClasses:
    """The armour classes of an item table (see the module docstring)."""
    counts = {slot: Counter() for slot in ARMOUR_SLOTS}
    for record in table.pool("wiki"):  # the pool, not the table: a hidden or disputed item is worn by no kit, and its class list says nothing of what one can wear
        classes = _ALL if record.classes is None else record.classes
        for slot in ARMOUR_SLOTS:
            if slot in record.slots:
                counts[slot][frozenset(classes)] += 1
    generic = sorted(
        (
            s
            for s in set().union(*counts.values())
            if len(s) >= MIN_SET_CLASSES and all(counts[slot][s] >= min_items for slot in ARMOUR_SLOTS)
        ),
        key=lambda s: (len(s), sorted(s)),
    )
    reach = {code: sum(code in s for s in generic) for code in CLASS_CODES}
    heavy = frozenset(code for code, n in reach.items() if n == max(reach.values())) if len(set(reach.values())) > 1 else frozenset()
    smaller = [s for s in generic if s != _ALL]
    cloth = _ALL - max(smaller, key=len) if smaller else frozenset()
    return ArmourClasses(tuple(generic), heavy, cloth)


def is_robe(classes: frozenset[str] | None, armour: ArmourClasses) -> bool:
    """Whether an item whose classes are ``classes`` (None: every class) is a robe: a piece of casters. It lists a cloth class, every class it lists casts (a Monk, a Rogue or a
    Beastlord that can wear it makes it a piece of leather or chain, which the cloth casters share), and it lists no heavy class."""
    return classes is not None and bool(classes & armour.cloth) and classes <= armour.casters and not classes & armour.heavy


def stem_of(name: str) -> str | None:
    """The stem of an item name (see the module docstring), in lower case, or None for a name of one word."""
    text = " ".join(_PARENTHESIS.sub("", name).casefold().split())
    if " of " in text:
        rest = _ARTICLE.sub("", text.rsplit(" of ", 1)[1]).strip()
        return f"of {rest}" if rest else None
    words = text.split()
    return " ".join(words[:-1]) if len(words) >= 2 else None


def set_stems(table: ItemTable, *, min_slots: int = MIN_SET_SLOTS, min_items: int = MIN_STEM_ITEMS) -> Mapping[str, str]:
    """``{item key: stem}`` for every item of the pool that carries a stem that is a set (see the module docstring)."""
    carried: dict[str, list] = {}
    for record in table.pool("wiki"):
        stem = stem_of(record.name)
        if stem is not None:
            carried.setdefault(stem, []).append(record)
    found: dict[str, str] = {}
    for stem, records in carried.items():
        slots = set().union(*(r.slots & WEARABLE_SLOTS for r in records))
        if len({r.key for r in records}) >= min_items and len(slots) >= min_slots:
            found.update({r.key: stem for r in records})
    return found
