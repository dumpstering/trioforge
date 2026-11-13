"""Which picture an item gets: the one function that says it (:func:`icon_name`).

The pictures are the icons of ``static/art/manifest.json`` (``art.py`` holds the rest of what the pages know of them); this module knows only which of them an item is, from what the catalog
says of it, and never touches a file. The pages, the data files and the browser all take the answer from here: a rule written twice would be two rules. Its one guide is that a wrong picture is
worse than a general one, and a general one (the picture of the item's place, drawn only where the item's own places agree: ``art.item_icon``) is worse than none where even that would be a guess.

* **What the name says.** The name says what an item *is* by its head word: the last word of a part of the name before an ``of``, a ``with``, a ``from``, a comma or a parenthesis, and a part
  after a comma is read as well (``Crookstinger, Axe of Pain`` is an axe). A word is a run of letters of any alphabet, never a piece of a longer word (the ``axe`` of ``Saxen`` and the ``staff``
  of ``Falstaff`` are not words). A head word is **an object the art has a picture of** (:data:`OBJECT_WORDS`: a sword, an axe, a hammer, a mace, a dagger, a staff, a wand, a spear, a bow, a
  fist, a book, an orb, an instrument), or **an object it has none of** (:data:`DENIED_WORDS`: a halberd, a scythe, a whip, a claw, a rod, a stick, a shovel, a censer ...), or something the lists do not
  know (a name of its own: Windstriker, Aldryn).
* **A weapon** (its skill is one of :data:`WEAPON_SKILLS`; the catalog wrote two skills badly and they give no weapon picture) gets the picture of the object its name says, **whatever its skill**
  (an Orb of Tishan is an orb though its skill is one-handed blunt; the Warstaff of Hope's Demise is a staff though its skill is piercing): a sword, an axe or a hammer is the one-handed or the
  two-handed picture as the skill's hands say, and two different objects say neither. A name that says an object the art has no picture of gives **no picture**, and so does one of two objects. A name
  that says nothing known gets the picture the skill gives (a one-handed slashing weapon is a sword, a one-handed blunt one a mace, a two-handed slashing one a two-handed sword, a two-handed blunt one a
  hammer, a piercing one a dagger, a two-handed piercing one a spear, hand to hand a fist, a thrown weapon the thrown picture, archery a bow).
* **Something held that is no weapon** (it fits a hand or the range place) is a wand, a book, an orb or an instrument where its head word says so, an instrument where the catalog gives it instrument
  modifiers, and a shield where the catalog says its type is a shield (never by name: the catalog vetoes some, and the shield of a weapon too is the catalog's word). Two of these say none. The words of
  weapons (sword, axe ...) say nothing of a thing that is no weapon.
* **A piece of armor** (it fits exactly one of the head, chest, arms, legs, feet and hands, and nothing else) gets that part in the material of the catalog's ``Fashion: Plate``, ``Leather``, ``Chain`` or
  ``Cloth`` category, which is an *appearance* and not a material: so the picture is given only when the name does not contradict it (a name that says a material, ``chain``, ``mail``, ``plate``,
  ``leather``, ``hide``, ``silk``, ``cloth``, ``scale`` ..., must say that one alone) and its head word is a shape the picture of that part in that material shows (:data:`ARMOR_SHAPES`: a crown is
  not the hood of the cloth head). The other fashion categories (those of one era or class) are not read, and none or two of the four give none.
* **The things held** (an item that fits the main hand, the off hand or the range, and has no picture by what is above) are told by the head word as well: an idol, a stone, a horn, a lantern, a cup, a
  scroll, a rod, a whip, a claw, a pick, a polearm, a charm or a fishing pole (:data:`HELD_WORDS`; ``fishing pole`` and ``fishing rod`` are two words that beat the rod, ``horn mouthpiece`` is a horn, and
  a flute's mouthpiece is nothing; a ``bo stick`` and a ``walking stick`` are staves, and so is a ``bo`` that is a two-handed blunt weapon; every other stick and a bokken, a tanto bo, a wakizashi bo, an eye and a
  seal are nothing: the review of 2026-11-13 took them out of the rod, the stone and the charm as guesses). They are for the held only: a ring named ``... Seal``, an earring named ``... Stone`` and a neck piece named ``Talisman`` are worn and keep what they had. They give a
  picture only where the rule above gave none (a weapon whose word it knew, an orb, a club, a scepter that is a mace by its skill, or a thing the catalog says is a shield keeps the one it has), with one
  exception, which is the maintainer's: an instrument whose head word is horn is a horn, and every other instrument keeps the instrument. A word that the lists do not name is nothing (a ball, a lightstone, a
  bowl, a deity, a lariat, a partisan, a crook: no picture says it).
* **Anything else**, and anything that these do not say plainly, gets none of its own. What a row of the kit and the page of the item then draw is ``art.row_icon`` and ``art.item_icon``: a worn place's own
  picture, and in a held place the pouch (the fallback of a held row, never an item's own picture).

The item is a mapping with the keys of an item of the item table (``name``, ``slots``, ``weapon``, ``item_type``) and, from the catalog, ``categories`` and ``instrument_mods``; a key that
is missing is read as nothing said.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["ALL_ICONS", "ARMOR_SHAPES", "DENIED_WORDS", "HELD_PHRASES", "HELD_WORDS", "OBJECT_WORDS", "head_words", "icon_name"]

#: the places that hold an item in a hand or at range: what a book, an orb, an instrument and a shield are looked for in
HELD_SLOTS = frozenset({"PRIMARY", "SECONDARY", "RANGE"})

#: the places of armor that have a picture of each material, and the stem of that picture's name
ARMOR_PARTS: dict[str, str] = {"HEAD": "helm", "CHEST": "chest", "ARMS": "arms", "LEGS": "legs", "FEET": "feet", "HANDS": "hands"}
#: the fashion categories of the catalog that say a material, and the material (the others, "Fashion: Velious Plate 2" and the like, say a look of one era and are not read)
MATERIALS: dict[str, str] = {"Fashion: Plate": "plate", "Fashion: Leather": "leather", "Fashion: Chain": "chain", "Fashion: Cloth": "cloth"}


def _words(text: str) -> frozenset[str]:
    """The words of a text of words separated by spaces, and their plurals (an ``s`` after a word that does not end in one)."""
    singles = text.split()
    return frozenset(singles) | frozenset(word + "s" for word in singles if not word.endswith("s"))


#: the objects the art has a picture of, and the head words that name each (whole words; the compounds that exist in the catalog are listed, since a word is never read inside another)
OBJECT_WORDS: dict[str, frozenset[str]] = {
    "sword": _words(
        "sword warsword longsword shortsword broadsword greatsword bastardsword claymore claidhmore zweihander flamberge katana wakizashi tachi koshigatana scimitar cutlass falchion saber sabre tulwar kilij rapier gladius"
    ),
    "axe": _words("axe battleaxe greataxe waraxe handaxe hatchet tomahawk"),  # (a poleaxe is a polearm: HELD_WORDS)
    "hammer": _words("hammer warhammer battlehammer sledgehammer maul mallet sledgemallet sledge gavel"),
    "mace": _words("mace"),
    "dagger": _words("dagger dirk stiletto knife skean tanto crysknife"),
    "staff": _words("staff warstaff wardstaff runestaff quarterstaff stave") | {"staves"},
    "wand": _words("wand"),
    "spear": _words("spear lance pike trident harpoon yari"),
    "bow": _words("bow longbow shortbow"),
    "fist": _words("fist knuckles knuckledusters dusters"),
    "book": _words("book tome encyclopedia grimoire spellbook codex"),
    "orb": _words("orb"),
    "instrument": _words("flute piccolo lute drum tambourine mandolin trumpet"),
}
_OBJECT_OF: dict[str, str] = {word: kind for kind, words in OBJECT_WORDS.items() for word in words}
#: the words of a book that name it wherever they stand in the head part ("Encyclopedia Necrotheurgia" has another word last)
BOOK_PHRASE_WORDS = frozenset({"encyclopedia", "grimoire", "codex", "spellbook"})

#: the head words that name an object the art has NO picture of: such a name gets no picture at all (not the skill's, which would be another object: a scythe is not a two-handed sword)
#: (a held thing of these gets the picture of :data:`HELD_WORDS` where there is one, whatever its skill; a word that is here and not there has none, and a thing that is not held keeps this answer)
DENIED_WORDS: frozenset[str] = _words(
    "halberd scythe naginata voulge glaive poleaxe partisan ahlspiess whip lash lariat kusarigama claw talon pick pickaxe bo bokken stick rod baton cane pole branch twig crook shovel spade broom wrench saw "
    "chisel poker fork fishingpole fishingrod torch censer stein sprinkler bowl fetish totem toy eye crossbow shield buckler webshield battleshield aegis tonfa jutte sai"
)

#: the thirteen pictures of the held things, and the head words that give each (whole words, as the head word of a part of a name; the plural of each is a word too): the maintainer's lists of 2026-11-13, narrowed
#: where a word would be a guess (see the module). A key is the end of the picture's name (``icon-idol``). An orb keeps the orb and a pike the spear: no word of these is a word of :data:`OBJECT_WORDS`.
HELD_WORDS: dict[str, frozenset[str]] = {
    "idol": _words("totem idol doll statue statuette figurine effigy fetish"),
    "stone": _words("stone gem crystal globe pearl shard rock jewel"),  # (an eye is no stone: the review of 2026-11-13)
    "horn": _words("horn"),
    "lantern": _words("torch lantern candle lamp brazier"),
    "cup": _words("stein mug chalice cup goblet flask vial bottle flagon tankard"),
    "scroll": _words("scroll writ parchment note letter map"),
    "rod": _words("rod baton cane scepter sceptre"),  # (a stick, a bo and a bokken are no rods: the review of 2026-11-13; a stick is a staff only as a phrase, HELD_PHRASES)
    "whip": _words("whip lash scourge"),
    "claw": _words("claw talon"),
    "pick": _words("pick pickaxe mattock"),
    "polearm": _words("halberd scythe naginata voulge glaive poleaxe polearm bardiche"),
    "charm": _words("brooch talisman charm amulet medal medallion symbol sigil emblem token badge"),  # (a seal is no charm: the review of 2026-11-13)
    "fishing-pole": _words("fishingpole fishingrod"),
}
_HELD_OF: dict[str, str] = {word: kind for kind, words in HELD_WORDS.items() for word in words}
#: the last two words of a part of a name that give a picture (its full name) where neither word alone would: a fishing pole is no rod, a flute's mouthpiece is no horn, and a bo stick and a walking stick are
#: staves where a stick alone is nothing
HELD_PHRASES: dict[tuple[str, str], str] = {
    **{("fishing", word): "icon-fishing-pole" for word in ("pole", "poles", "rod", "rods")},
    **{("horn", word): "icon-horn" for word in ("mouthpiece", "mouthpieces")},
    **{("bo", word): "icon-staff" for word in ("stick", "sticks")},
    **{("walking", word): "icon-staff" for word in ("stick", "sticks")},
}
#: the last two words that are nothing, whatever the last word alone would say: a tanto bo and a wakizashi bo are small swords of one hand
HELD_NOTHING: frozenset[tuple[str, str]] = frozenset({("tanto", "bo"), ("wakizashi", "bo")})

#: the kinds of object that a thing held in a hand is told by its name to be, when it is no weapon (the words of a weapon say nothing of it)
HELD_KINDS = frozenset({"wand", "book", "orb", "instrument"})

#: for each skill of a weapon, the picture it has when its name says nothing known (a skill that is not here, the catalog wrote two badly, gives no weapon picture)
WEAPON_SKILLS: dict[str, str] = {
    "1H Slashing": "icon-sword-1h",
    "2H Slashing": "icon-sword-2h",
    "1H Blunt": "icon-mace",
    "2H Blunt": "icon-hammer-2h",
    "Piercing": "icon-dagger",
    "1H Piercing": "icon-dagger",
    "2H Piercing": "icon-spear",
    "Hand to Hand": "icon-fist",
    "Throwing": "icon-throwing",
    "Throwingv1": "icon-throwing",
    "Throwingv2": "icon-throwing",
    "Archery": "icon-bow",
}

#: the picture of each object (a sword, an axe and a hammer are one-handed or two-handed as the skill says)
_PICTURE: dict[str, str | tuple[str, str]] = {
    "sword": ("icon-sword-1h", "icon-sword-2h"),
    "axe": ("icon-axe-1h", "icon-axe-2h"),
    "hammer": ("icon-hammer-1h", "icon-hammer-2h"),
    "mace": "icon-mace",
    "dagger": "icon-dagger",
    "staff": "icon-staff",
    "wand": "icon-wand",
    "spear": "icon-spear",
    "bow": "icon-bow",
    "fist": "icon-fist",
    "book": "icon-book",
    "orb": "icon-orb",
    "instrument": "icon-instrument",
    "shield": "icon-shield",
}

#: the words of a name that say a material (whole words); "scale" is a material that none of the four pictures shows, so a name that says it is given no picture of the four
MATERIAL_WORDS: dict[str, frozenset[str]] = {
    "chain": _words("chain chainmail mail ringmail"),
    "plate": _words("plate platemail"),
    "leather": _words("leather hide") | {"hides"},
    "cloth": _words("cloth silk linen cotton wool robe"),
    "scale": _words("scale scaled") | {"scales"},
}

#: for each part of armor and material, the head words of the shapes that its picture shows (the hood of the cloth head shows a hood and a cowl, and no crown, circlet, helm or mask; the cloth chest is a
#: robe or a tunic, and no breastplate). A head word that is not here gets the picture of the place, not the picture of the material.
ARMOR_SHAPES: dict[str, dict[str, frozenset[str]]] = {
    "HEAD": {
        "cloth": _words("hood cowl cap hat"),
        "leather": _words("cap skullcap helm helmet coif hood hat"),
        "chain": _words("coif cowl hood cap helm helmet"),
        "plate": _words("helm helmet barbute skullhelm headguard greathelm"),
    },
    "CHEST": {
        "cloth": _words("robe tunic shirt vest coat armor"),
        "leather": _words("tunic jerkin vest shirt coat armor suit skin apron"),
        "chain": _words("mail chainmail ringmail hauberk tunic coat shirt vest armor tabard"),
        "plate": _words("breastplate chestplate cuirass armor plate platemail"),
    },
    "ARMS": {material: _words("sleeve vambrace armplate armguard guard bracer") | {"sleeves"} for material in ("cloth", "leather", "chain", "plate")},
    "LEGS": {material: _words("legging legplate legguard pant greave pantaloon breeches chausses") | {"pants", "trousers"} for material in ("cloth", "leather", "chain", "plate")},
    "FEET": {material: _words("boot shoe slipper") for material in ("cloth", "leather", "chain", "plate")},
    "HANDS": {material: _words("glove gauntlet mitten") for material in ("cloth", "leather", "chain", "plate")},
}


def _object_pictures() -> Iterable[str]:
    for picture in _PICTURE.values():
        yield from (picture,) if isinstance(picture, str) else picture


#: every picture the rule can give (the manifest's icons are held to this list by a test, and every one is reachable)
ALL_ICONS: frozenset[str] = frozenset(
    {*WEAPON_SKILLS.values(), *_object_pictures()}
    | {f"icon-{part}-{material}" for part in ARMOR_PARTS.values() for material in MATERIALS.values()}
    | {f"icon-{kind}" for kind in HELD_WORDS}
)

_LETTERS = re.compile(r"[^\W\d_]+")
_PARENTHESIS = re.compile(r"\([^)]*\)")
#: the words that end the part of a name that says what the item is ("Staff of the Seer", "Tome with Silver Runes")
_PREPOSITIONS = frozenset({"of", "with", "from", "for", "in", "on", "to"})


def _parts(name: Any) -> list[list[str]]:
    """The parts of a name (it is cut at its commas, a parenthesis is no part of it) as lists of words, each cut where its first ``of`` or the like begins."""
    if not isinstance(name, str):
        return []
    parts = []
    for text in _PARENTHESIS.sub(" ", name.lower()).split(","):
        words = _LETTERS.findall(text)
        for at, word in enumerate(words):
            if word in _PREPOSITIONS:
                words = words[:at]
                break
        if words:
            parts.append(words)
    return parts


def head_words(name: Any) -> list[str]:
    """The head word of each part of a name (the last word of the part), for the tools that look at the words of the real names."""
    return [words[-1] for words in _parts(name)]


def _slots(item: Mapping[str, Any]) -> frozenset[str]:
    slots = item.get("slots")
    return frozenset(slot for slot in slots if isinstance(slot, str)) if isinstance(slots, (list, tuple)) else frozenset()


def _picture(kind: str, skill: str | None) -> str:
    picture = _PICTURE[kind]
    if isinstance(picture, str):
        return picture
    return picture[1] if isinstance(skill, str) and skill.startswith("2H") else picture[0]


def _says(name: Any) -> tuple[set[str], bool]:
    """The objects a name says (by the head word of each of its parts) and whether it says one the art has no picture of."""
    kinds: set[str] = set()
    denied = False
    for words in _parts(name):
        head = words[-1]
        if head in _OBJECT_OF:
            kinds.add(_OBJECT_OF[head])
        elif head in DENIED_WORDS:
            denied = True
        if BOOK_PHRASE_WORDS.intersection(words):
            kinds.add("book")
    return kinds, denied


def _armor_icon(item: Mapping[str, Any], slots: frozenset[str]) -> str | None:
    parts = slots & set(ARMOR_PARTS)
    categories = item.get("categories")
    materials = {MATERIALS[c] for c in categories if isinstance(c, str) and c in MATERIALS} if isinstance(categories, (list, tuple)) else set()
    if len(parts) != 1 or len(slots) != 1 or len(materials) != 1:
        return None
    part, material = next(iter(parts)), next(iter(materials))
    parts_of_name = _parts(item.get("name"))
    said = {kind for words in parts_of_name for word in words for kind, group in MATERIAL_WORDS.items() if word in group}
    if said and said != {material}:
        return None  # the name says another material (or two, or one of the four pictures' none): the fashion category is a look, and the name does not agree with it
    if not parts_of_name or parts_of_name[0][-1] not in ARMOR_SHAPES[part][material]:
        return None  # the picture of the material does not show this shape
    return f"icon-{ARMOR_PARTS[part]}-{material}"


def _held_picture(name: Any, skill: str | None) -> str | None:
    """The one picture that the name says of a held thing (``icon-idol``), or None: the head word of each part of the name, or the last two words of it where they are a phrase of :data:`HELD_PHRASES`
    (a phrase of :data:`HELD_NOTHING` says nothing), and a ``bo`` that is a two-handed blunt weapon is a staff; two pictures say neither."""
    pictures = set()
    for words in _parts(name):
        pair = (words[-2], words[-1]) if len(words) > 1 else None
        if pair in HELD_NOTHING:
            continue
        picture = HELD_PHRASES.get(pair) if pair is not None else None
        if picture is None and words[-1] in ("bo", "bos") and skill == "2H Blunt":
            picture = "icon-staff"
        if picture is None and words[-1] in _HELD_OF:
            picture = f"icon-{_HELD_OF[words[-1]]}"
        if picture is not None:
            pictures.add(picture)
    return next(iter(pictures)) if len(pictures) == 1 else None


def icon_name(item: Mapping[str, Any]) -> str | None:
    """The name of the picture of the item (``icon-sword-2h``: an icon of ``manifest.json``), or None when nothing says plainly which it is (see the module).

    The rule of what an item is (:func:`_base_icon_name`) comes first; a held item that it gave no picture is looked at again for the thirteen pictures of the held things (:data:`HELD_WORDS`), and an
    instrument whose head word is horn is the horn. Nothing that is not held is looked at again, and no picture that the first rule gave is taken away from a weapon, an orb or a shield."""
    name = _base_icon_name(item)
    if not _slots(item) & HELD_SLOTS:
        return name
    weapon = item.get("weapon")
    skill = weapon.get("skill") if isinstance(weapon, Mapping) else None
    picture = _held_picture(item.get("name"), skill if isinstance(skill, str) else None)
    if picture is None:
        return name
    if name is None or (name == "icon-instrument" and picture == "icon-horn"):
        return picture
    return name


def _base_icon_name(item: Mapping[str, Any]) -> str | None:
    """What the rule says of an item before the pictures of the held things: a weapon by its name and its skill, a held thing that is no weapon, a piece of armor (see the module)."""
    slots = _slots(item)
    weapon = item.get("weapon")
    skill = weapon.get("skill") if isinstance(weapon, Mapping) else None
    skill = skill if isinstance(skill, str) and skill in WEAPON_SKILLS else None
    if skill is None and not slots & HELD_SLOTS:
        return _armor_icon(item, slots)
    kinds, denied = _says(item.get("name"))
    if skill is None:
        kinds &= HELD_KINDS  # (the words of a weapon, and the objects the art lacks, say nothing of a thing that is no weapon)
        denied = False
    mods = item.get("instrument_mods")
    if isinstance(mods, Mapping) and mods:
        kinds.add("instrument")
    if str(item.get("item_type") or "").lower() == "shield":
        kinds.add("shield")
    if kinds:
        return _picture(next(iter(kinds)), skill) if len(kinds) == 1 else None
    if denied:
        return None
    if skill is not None:
        return WEAPON_SKILLS[skill]
    return _armor_icon(item, slots)
