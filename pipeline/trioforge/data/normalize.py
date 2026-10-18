"""Turn a parsed item page into a catalog item: stats, slots, classes, effects, sources.

``normalize(parsed_page)`` returns a plain dict that validates against
``schema/catalog-item.schema.json``. It never raises for any page text; whatever it cannot
read becomes a *warning* (``{"code", "field"}``: a short code and the name of the thing, never
text from the page) and the page's other data is kept.

**Wiki text is hostile input.** Every string written into the item goes through
:func:`sanitize_text` first, so no ``<`` or ``>``, no control, zero-width or bidi character, no
unassigned or private-use code point, no lone surrogate, no URL (``scheme://...``, ``www....``: text in
``<nowiki>`` reaches the fields as typed) and no string over 200 characters can reach the catalog. Quotes and
``=`` are kept (real names have apostrophes); the site escapes on output.

The order for a statsblock line is: NFKC (a non-breaking space becomes a space) -> parse ->
sanitize what is stored. The parser (``trioforge.sources.itempage``) has already decoded HTML
entities, once, so nothing here decodes them again. Key names are matched with ASCII-only case
folding (the dotless i, the Turkish capital I with a dot and the long s are never a key letter).

What a statsblock line may hold, case-insensitively and with any spacing:

* flags: ``Lore Equipped, No Trade``, ``MAGIC ITEM  LORE ITEM  NO DROP`` and the others in
  :data:`FLAGS`; an unknown flag word is a warning. ``NODROP``, ``NORENT`` and ``Attuneable`` are
  flags too. The flags that begin ``wiki_banner_`` and ``removed_note`` come from the page, not from
  the statsblock (``ParsedPage.page_flags``);
* ``Slot:`` (plural and variant spellings are mapped; ``AUG`` is not wearable, warning) and, on a
  line of its own, slot words with no ``Slot:`` (``Wrist``); ``Type:``; ``Class:`` / ``Race:``
  (``ALL``, ``ALL except A B``, codes, ``NONE`` for nobody; ``VAH`` is the Vah Shir, which the
  catalog calls ``KER``, Kerran) and ``Deity:``. A class, race or deity list that wraps onto the next
  line continues there, if that line holds nothing but codes (or deity names); a line of deity names
  alone, and ``Deity Name`` with no colon, are deity lists. The misspelt keys ``Diety:``, ``Dieties:``
  and ``Deities:`` are read. Deity names are matched whole after links are stripped, and ``-``, ``/``
  and ``,`` separate them (``Cazic-Thule``, ``[[The Tribunal]] / [[Rallos Zek]]``);
* the stats ``AC STR STA AGI DEX WIS INT CHA HP MANA END ATK HASTE`` (also ``Charisma``, ``ENDUR``,
  ``Attack``...), ``HP Regen`` / ``Mana Regen`` / ``End Regen``, ``SV <school>`` (also ``SV.Cold:``,
  ``SV: Disease 4``, ``SV FIRE +5`` and ``MR FR CR DR PR``) and ``Resist All``. A key may have no
  colon when a number follows (``STR +10``, ``AC 4``), a stat word may have a period for its colon when a
  number follows (``HP. +3``), and a link around a key is dropped (``[[Haste]]: +41%``). Any other
  ``Word:`` ends the value before it, so ``HP: +125 ENDUR: +100`` is
  two stats. ``+5``, ``+ 5``, ``5``, ``-3``, ``1,250`` are all numbers, bounded to seven digits (more
  is ``out-of-range``); the number a value starts with is taken and text after it is a ``trailing-text``
  warning; a decimal in an integer field, or a value out of range, is dropped with a warning; zero is
  omitted;
* ``Skill:`` + ``Atk Delay:`` + ``DMG:`` (also ``Base Dmg:``) + ``DMG Bonus:`` for a weapon (an instrument skill
  such as ``Brass Instruments`` is a skill too; a spell school such as ``Abjuration`` is a spell scroll,
  not a weapon), ``BACKSTAB:`` (``weapon.backstab``) and ``Fire DMG:``, ``Cold DMG:`` and the other
  elements (``weapon.elemental``, ``{"type", "value"}``), ``Size:``, ``WT:``, ``Capacity:`` for a bag,
  ``Required level of 45.``, ``Recommended level of 30.`` and ``Rec Level: 4``;
* ``Charges: N``, alone or after the flags (``EXPENDABLE  Charges: 10``): the item's ``charges``,
  wherever the line stands, even between the lines of an effect (it does not end the effect's block). An
  effect has ``charges`` only when its own line says so (``Effect: [[X]] (Any Slot) Charges: 5``); no
  neighbouring line gives it any;
* ``Effect:`` / ``Focus Effect:`` lines (also ``Click Effect:``, ``Worn Effect:``, ``Proc Effect:``,
  ``Combat Effect:``, ``Consumable Effect:`` and a line that starts with a link and a bracket,
  ``[[X]] (Worn)``). The name is the link target (no ``#fragment``, no parenthetical; the link label
  when the target is a generic page such as ``Pet Guide``); ``(Worn)`` makes a worn effect,
  ``(Combat ...)`` a proc, ``(Any Slot ...)``, ``(Must Equip)`` or a casting time a click. Lines that
  follow an effect (casting time, required level, cooldown) belong to it; ``Required Level``
  there, or in the effect's own line, is the effect's ``required_level``, not the item's; a line of its own
  that follows no effect sets the item's.

The item has the fields of the plan (key, name, wiki, slots, classes, races, deity, flags, stats, sv,
weight, size, weapon, effects, required_level, recommended_level, sources, era_tags, tier_rule,
parse_warnings) and a few more that the real pages need: ``item_type`` (``Type: Shield``, or
``Skill: Shield``) with ``item_type_source``, ``container_capacity`` (a bag's ``Capacity``),
``instrument_mods`` (``Wind Resonance: 12`` gives ``{"Wind": 12}``), ``categories``, ``lucy_img_id``,
``charges`` (only when the page states them) and ``parse_warnings_overflow``. ``sources.sold_by`` entries are
``{"zone", "npc"}``, because the evidence ladder needs the vendor's zone; a drop entry may have ``notes``.
``sources.quests`` are the targets of the quest links (what a quest is looked up by) and ``sources.quest_labels``,
present only when some link has a label of its own, are ``{"title", "label"}`` for display; ``sources.foraged``
(present only when the page lists some) are ``{"zone"}`` entries. Known and not stored: ``Size Capacity``,
``Weight Reduction``, a bow's ``Range`` and ``Bane DMG``.

``item_type_source`` says where ``item_type`` came from, and is ``None`` when there is no type. Here it is
``"statsblock"`` or ``None``: the page either states a type or does not. The catalog builder
(``trioforge.data.catalog``) fills in the other two values, ``"name"`` and ``"hand-list"``, for shields that
the page does not call shields.

**Class and race lists.** A statsblock with no ``Class:`` or no ``Race:`` line is read as all classes or all
races, and says nothing. ``Class: NONE`` and ``Race: NONE`` (any case) are different: the page states them, the list
is empty, which means that nobody may use or wear the item, and the warning is ``no-classes`` (field ``class`` or
``race``). The evidence ladder marks such an item ``not-for-bis`` and says which list it is.

**A hand weapon that cannot be scored.** An item that fits a hand (``PRIMARY`` or ``SECONDARY``) and whose weapon
names a skill but has no damage or no delay (:func:`weapon_incomplete`) gets the warning ``weapon-incomplete``
(field ``weapon``). The model reads such an item as no weapon at all, so an unscored two-hander could be placed in the
off hand; the evidence ladder marks it ``not-for-bis``. Ammunition (no delay by nature), bows and an item worn
nowhere are not hand weapons.
"""

from __future__ import annotations

import functools
import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from trioforge.sources.itempage import ParsedPage, first_link_parts, plain_text

__all__ = [
    "CLASS_CODES",
    "DEITIES",
    "EFFECT_KINDS",
    "ELEMENTS",
    "FLAGS",
    "GENERIC_EFFECT_TARGETS",
    "ITEM_TYPE_SOURCES",
    "RACE_ALIASES",
    "RACE_CODES",
    "SCHEMA_PATH",
    "SIZES",
    "SLOTS",
    "SPELL_SCHOOLS",
    "STAT_KEYS",
    "SV_KEYS",
    "TIER_RULES",
    "WARNING_CODES",
    "normalize",
    "promote_bullet_zones",
    "sanitize_text",
    "validate_item",
    "weapon_incomplete",
]

# ---- the vocabulary ------------------------------------------------------------------------

SLOTS = (
    "HEAD FACE EAR NECK SHOULDERS ARMS BACK WRIST HANDS FINGER CHEST LEGS FEET WAIST RANGE AMMO "
    "PRIMARY SECONDARY CHARM POWERSOURCE"
).split()
CLASS_CODES = "WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER".split()
RACE_CODES = "HUM BAR ERU ELF HIE DEF HEF DWF TRL OGR HFL GNM IKS KER FRG".split()
RACE_ALIASES = {"VAH": "KER"}  # the wiki writes the Vah Shir as VAH; the catalog's code for them is KER (Kerran)
STAT_KEYS = "AC STR STA AGI DEX WIS INT CHA HP MANA END ATK HASTE HPREG MANAREG ENDREG".split()
SV_KEYS = "FIRE COLD MAGIC POISON DISEASE CORRUPTION".split()
RESIST_ALL_KEYS = "FIRE COLD MAGIC POISON DISEASE".split()  # "Resist All" is the five, not corruption
ELEMENTS = "Fire Cold Magic Poison Disease Corruption".split()  # for "Fire DMG: 4"
SPELL_SCHOOLS = frozenset({"abjuration", "alteration", "conjuration", "divination", "evocation"})  # a scroll's skill
FLAGS = (
    "lore no_trade no_drop magic temporary attunable heirloom placeable no_rent expendable quest "
    "ornament summoned removed_note wiki_banner_delete wiki_banner_does_not_exist wiki_banner_dne "
    "wiki_banner_revamped"
).split()
SIZES = "TINY SMALL MEDIUM LARGE GIANT".split()
EFFECT_KINDS = "focus click worn proc spell other".split()
TIER_RULES = "drop fixed0 spell".split()
ITEM_TYPE_SOURCES = ("statsblock", "name", "hand-list")  # where item_type came from; see the module docstring
HAND_SLOTS = ("PRIMARY", "SECONDARY")  # where a weapon is held
DEITIES = (
    "Agnostic",
    "Bertoxxulous",
    "Brell Serilis",
    "Bristlebane",
    "Cazic Thule",
    "Erollisi Marr",
    "Innoruuk",
    "Karana",
    "Mithaniel Marr",
    "Prexus",
    "Quellious",
    "Rallos Zek",
    "Rodcet Nife",
    "Solusek Ro",
    "The Tribunal",
    "Tunare",
    "Veeshan",
)
# Pages that many effects link to under another name ("[[Pet Guide|Minion of Air]]"): the label is the effect.
GENERIC_EFFECT_TARGETS = frozenset({"pet guide", "pets", "spell guide", "spells", "spell", "disciplines", "skills"})

WARNING_CODES = (
    # from the page parser
    "multiple-itempage duplicate-param nested-template bad-lucy-id "
    # from the statsblock
    "unparsed-line bad-value non-integer out-of-range duplicate-key unknown-slot augment-slot "
    "unknown-code unknown-deity unknown-flag unknown-sv empty-value list-truncated line-limit "
    "unknown-warning trailing-text no-classes orphan-continuation weapon-incomplete"
).split()

MAX_TEXT = 200  # characters in any stored display string
MAX_WARNINGS = 20  # per item; the rest are counted in parse_warnings_overflow
MAX_LINES = 500  # statsblock lines read per item
MAX_LINE_CHARS = 5000  # characters read of one line: far above any real line, a guard against a 2 MB one
MAX_EFFECTS = 100
MAX_INSTRUMENT_MODS = 10
MAX_ERA_TAGS = 20
MAX_DIGITS = 7  # digits in any number: more is out of range, and is never turned into an int
LIST_LIMITS = {
    "drops": 500,
    "npcs": 1000,
    "sold_by": 2000,
    "quests": 500,
    "quest_labels": 500,
    "foraged": 200,
    "crafted": 200,
    "ingredients": 200,
    "categories": 200,
    "notes": 10,
}

# ---- sanitize_text -------------------------------------------------------------------------

_WHITESPACE = re.compile(r"\s+")
_DROPPED_CATEGORIES = frozenset({"Zl", "Zp", "Cf", "Cs", "Co", "Cn"})  # line and paragraph separators, format, surrogate, private use, unassigned
# A URL is never stored: "scheme://..." up to the next space (the scheme may be missing or one letter long, so that
# no "://" survives), and a bare "www." host. Text inside <nowiki> reaches the stored fields as typed.
_URL_IN_TEXT = re.compile(r"(?:[A-Za-z][A-Za-z0-9+.\-]{0,30})?://\S*|(?<![A-Za-z0-9])www\.\S*", re.ASCII | re.IGNORECASE)


def _strip_once(text: str) -> str:
    kept = []
    for char in unicodedata.normalize("NFKC", text):
        category = unicodedata.category(char)
        if category in _DROPPED_CATEGORIES or char in "<>":
            continue
        if category == "Cc":
            if char.isspace():
                kept.append(" ")
            continue
        kept.append(char)
    return _URL_IN_TEXT.sub(" ", "".join(kept))


def sanitize_text(text: str | None) -> str | None:
    """Make wiki text safe to store: NFKC, no control / format / surrogate / private-use / unassigned /
    line-separator character, no ``<`` or ``>``, no URL (``scheme://...``, ``www....``), one space between
    words, at most 200 characters.

    A tab or newline becomes a space; every other dropped character vanishes (so a zero-width space
    or a bidi override leaves no trace). NFKC runs again after the removals and the two steps repeat
    until nothing changes (at most three times), so that the answer is a fixed point: sanitizing it
    again changes nothing. ``None`` passes through. The result can be empty.
    """
    if text is None:
        return None
    current = text
    for _ in range(3):
        cleaned = unicodedata.normalize("NFKC", _strip_once(current))
        if cleaned == current:
            break
        current = cleaned
    return _WHITESPACE.sub(" ", current).strip()[:MAX_TEXT].rstrip()


# ---- warnings ------------------------------------------------------------------------------

_FIELD = re.compile(r"[a-z][a-z0-9_]{0,31}")


class _Warnings:
    """Up to MAX_WARNINGS ``{"code", "field"}`` entries and a count of the rest."""

    def __init__(self) -> None:
        self.items: list[dict] = []
        self.overflow = 0

    def add(self, code: str, where: str) -> None:
        if code not in WARNING_CODES:
            code = "unknown-warning"
        if not _FIELD.fullmatch(where):
            where = "unknown"
        if len(self.items) < MAX_WARNINGS:
            self.items.append({"code": code, "field": where})
        else:
            self.overflow += 1


# ---- the keys of a statsblock line ----------------------------------------------------------
# Every pattern is ASCII-only and case-insensitive: the dotless i, the capital I with a dot, the long s and
# the Kelvin sign match their ASCII look-alikes under Unicode folding and must not.

_ASCII = re.ASCII | re.IGNORECASE


def _lower(text: str) -> str:
    return text.translate({code: code + 32 for code in range(ord("A"), ord("Z") + 1)})


def _upper(text: str) -> str:
    return text.translate({code: code - 32 for code in range(ord("a"), ord("z") + 1)})


_STAT_ALIASES = {
    "AC": "AC",
    "STR": "STR",
    "STRENGTH": "STR",
    "STA": "STA",
    "STAMINA": "STA",
    "AGI": "AGI",
    "AGILITY": "AGI",
    "DEX": "DEX",
    "DEXTERITY": "DEX",
    "WIS": "WIS",
    "WISDOM": "WIS",
    "INT": "INT",
    "INTELLIGENCE": "INT",
    "CHA": "CHA",
    "CHARISMA": "CHA",
    "HP": "HP",
    "MANA": "MANA",
    "END": "END",
    "ENDUR": "END",
    "ENDURANCE": "END",
    "ATK": "ATK",
    "ATTACK": "ATK",
    "HASTE": "HASTE",
    "HP REGEN": "HPREG",
    "HPREGEN": "HPREG",
    "MANA REGEN": "MANAREG",
    "MANAREGEN": "MANAREG",
    "MP REGEN": "MANAREG",
    "END REGEN": "ENDREG",
    "ENDREGEN": "ENDREG",
    "ENDURANCE REGEN": "ENDREG",
    "ENDUR REGEN": "ENDREG",
}
_SV_ABBREVIATIONS = {"MR": "MAGIC", "FR": "FIRE", "CR": "COLD", "DR": "DISEASE", "PR": "POISON"}
_OTHER_KEYS = {
    "SLOT": "slot",
    "TYPE": "type",
    "CLASS": "class",
    "RACE": "race",
    "DEITY": "deity",
    "DIETY": "deity",
    "DEITIES": "deity",
    "DIETIES": "deity",
    "SIZE": "size",
    "WT": "weight",
    "WEIGHT": "weight",
    "SKILL": "skill",
    "ATK DELAY": "delay",
    "ATTACK DELAY": "delay",
    "DELAY": "delay",
    "DMG": "dmg",
    "DAMAGE": "dmg",
    "BASE DMG": "dmg",  # "Base Dmg: 9" is the damage of a weapon
    "BASE DAMAGE": "dmg",
    "DMG BONUS": "bonus",
    "DMG BON": "bonus",
    "DAMAGE BONUS": "bonus",
    "BASE DMG": "dmg",  # "Base Dmg: 9" is the weapon's damage, the same number "DMG: 9" gives
    "BASE DAMAGE": "dmg",
    "BACKSTAB": "backstab",
    "BANE DMG": "ignored",  # "Bane DMG: Gnoll +4": known, not stored
    "BANE DAMAGE": "ignored",
    "CAPACITY": "capacity",
    "SIZE CAPACITY": "ignored",
    "WEIGHT REDUCTION": "ignored",
    "RANGE": "ignored",  # a bow's range: ranged damage is not modelled
    "RESIST ALL": "resist_all",
    "ALL RESISTS": "resist_all",
    "REQUIRED LEVEL": "required_level",
    "RECOMMENDED LEVEL": "recommended_level",
    "REC LEVEL": "recommended_level",
    "CHARGES": "charges",
    "CHARGE": "charges",
}
_ELEMENT_KEY = re.compile(r"(FIRE|COLD|MAGIC|POISON|DISEASE|CORRUPTION) (?:DMG|DAMAGE)")

# A key is a word that ends in a colon. The multi-word keys come first, longest first, so that
# "Atk Delay:" is one key and not "Delay:" behind a stray "Atk"; any other single word before a colon is a
# key too (an unknown one), because it ends the value before it ("HP: +125 ENDUR: +100" is two stats).
# A stat abbreviation followed by a number needs no colon ("STR +10", "SV FIRE +5").
_MULTI_WORD_KEYS = sorted(
    (key for key in {*_STAT_ALIASES, *_OTHER_KEYS} if " " in key), key=len, reverse=True
)
_KEY_WORDS = (
    r"(?:FIRE|COLD|MAGIC|POISON|DISEASE|CORRUPTION)\s+(?:DMG|DAMAGE)|"
    + "|".join(key.replace(" ", r"\s+") for key in _MULTI_WORD_KEYS)
    + r"|SV[\s.]*[A-Za-z]+|(?!(?:javascript|data|vbscript|https?|ftp|mailto|file|about)\s*:)[A-Za-z][A-Za-z']*"
)  # a URL scheme before a colon is the start of a value, not a key
_BARE_STATS = (
    r"STR|STA|AGI|DEX|WIS|INT|CHA|AC|HP|MANA|END|ATK|MR|FR|CR|DR|PR"
    r"|SV[\s.]*(?:FIRE|COLD|MAGIC|POISON|DISEASE|CORRUPTION)"
)
# "HP. +3 MANA +3": a stat word followed by a period and a number reads as if the period were the colon. Only the
# stat words (a period after any other word ends a sentence), and only with a number after the period.
_DOTTED_STATS = r"STR|STA|AGI|DEX|WIS|INT|CHA|AC|HP|MANA|END|ATK|HASTE|MR|FR|CR|DR|PR"
_BOUNDARY = re.compile(
    r"(?<![A-Za-z0-9'`])(?:(?P<colon>" + _KEY_WORDS + r")\s*:|(?P<bare>" + _BARE_STATS + r")(?=\s+[+-]?\s*[0-9])"
    r"|(?P<dotted>" + _DOTTED_STATS + r")\.(?=\s*[+-]?\s*[0-9]))",
    _ASCII,
)

_EFFECT_LINE = re.compile(
    r"\s*(focus effect|click effect|worn effect|proc effect|combat effect|consumable effect|effect|spell)\s*:\s*(.*)",
    _ASCII,
)
# "[[Grim Aura]] (Worn)": an effect with no "Effect:" label
_UNLABELLED_EFFECT = re.compile(
    r"\s*\[\[[^\[\]]{1,200}\]\]\s*\([^()]{0,200}\b(?:worn|combat|any slot|must equip|can equip|casting time)\b[^()]{0,200}\)",
    _ASCII,
)
_CONTINUATION = re.compile(
    r"\s*(casting time|cast time|required level|recommended level|cooldown|recast delay|recast time|recast"
    r"|reuse time|level)\s*:",
    _ASCII,
)
# A line that is only "Charges: N" (or "Unlimited") is the item's, wherever it stands; next to an effect it does
# not end that effect's block (the lines after it, "Cooldown: 600 seconds", still belong to the effect).
_CHARGES_ONLY = re.compile(r"\s*charges?\s*:[^:]*", _ASCII)
# the continuation words that mean nothing without an effect before them (Required/Recommended Level and
# Charges are item-level keys too)
_ORPHAN = re.compile(r"\s*(casting time|cast time|cooldown|recast delay|recast time|recast|reuse time|level)\s*:", _ASCII)
_CHARGES_RE = re.compile(r"\bcharges?\b\s*:?\s*([0-9]{1,6})\b|\b([0-9]{1,6})\s+charges?\b", _ASCII)
_REQUIRED_LEVEL_RE = re.compile(r"\brequired\s+level\b\s*:?\s*([0-9]{1,3})\b", _ASCII)
_RESONANCE_LINE = re.compile(r"([A-Za-z]{2,20}) resonance\s*:?\s*([+-]?[0-9]{1,4})", _ASCII)
_BONUS_LEVEL = re.compile(r"\s*@\s*lvl?\.?\s*[0-9]+\s*$", _ASCII)  # "34 @ lvl 50": the bonus at a level
_LEVEL_SENTENCE = re.compile(r"(required|recommended) level(?: of)?\s*:?\s*([0-9]+)\s*\.?", _ASCII)
_DEITY_WORD = re.compile(r"\b(?:deity|diety|deities|dieties)\b", _ASCII)
_DEITY_NO_COLON = re.compile(r"(?:deity|diety|deities|dieties)\b\s*(.+)", _ASCII)
_EFFECT_PREFIX = re.compile(r"effect\s*:\s*", _ASCII)

_MINUS = str.maketrans({"−": "-", "–": "-", "‒": "-"})  # unicode minus and dashes
# the number a value starts with: a sign, digits with commas between them, a decimal part
_NUMBER = re.compile(r"([+-]?)\s*([0-9]+(?:,[0-9]+)*)(?:\.([0-9]+))?")
_THOUSANDS = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+")
_HARMLESS_TAIL = re.compile(r"[\s.,;:!?]*")
_STAT_RANGE = (-1000, 10000)

_SLOT_ALIASES = {
    **{slot: slot for slot in SLOTS},
    "EARS": "EAR",
    "SHOULDER": "SHOULDERS",
    "ARM": "ARMS",
    "WRISTS": "WRIST",
    "HAND": "HANDS",
    "FINGERS": "FINGER",
    "LEG": "LEGS",
    "FOOT": "FEET",
    "RANGED": "RANGE",
}

_FLAG_PHRASES = {
    "LORE EQUIPPED": "lore",
    "LORE ITEM": "lore",
    "LORE": "lore",
    "NO TRADE": "no_trade",
    "NO DROP": "no_drop",
    "NODROP": "no_drop",
    "MAGIC ITEM": "magic",
    "MAGIC": "magic",
    "TEMPORARY": "temporary",
    "ATTUNABLE": "attunable",
    "ATTUNEABLE": "attunable",
    "HEIRLOOM": "heirloom",
    "PLACEABLE": "placeable",
    "NO RENT": "no_rent",
    "NORENT": "no_rent",
    "EXPENDABLE": "expendable",
    "QUEST ITEM": "quest",
    "QUEST": "quest",
    "ORNAMENT": "ornament",
    "SUMMONED": "summoned",
}
_FLAG = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(sorted((p.replace(" ", r"\s+") for p in _FLAG_PHRASES), key=len, reverse=True))
    + r")(?![A-Za-z0-9])",
    _ASCII,
)
_SEPARATORS = re.compile(r"[\s,;/]+")
_DEITY_SEPARATORS = re.compile(r"[\s,;/\-]+")
_WORD = re.compile(r"[^\s,;/]+")
_LINK_LABEL = re.compile(r"\[\[([^\[\]|]{1,200})\|[^\[\]]{0,200}\]\]")
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]{1,30}://\S*", re.ASCII)
_SCHEME_PREFIX = re.compile(r"^\s*[A-Za-z][A-Za-z0-9+.\-]{1,30}:\s*", re.ASCII)


def _field_name(key: str) -> str:
    return key.lower().replace(" ", "_")


def _display_text(value: str) -> str:
    """A display value (a skill, a type) as plain text: links and tags lose their markup, an external link
    keeps only its anchor text, and no URL and no ``scheme:`` prefix survives (``javascript:alert(1)``
    becomes ``alert(1)``). The value has been decoded already, so it is neutralized as it stands."""
    text = plain_text(value, unescape=False)
    text = _URL.sub(" ", text)
    text = _SCHEME_PREFIX.sub("", text, count=1)
    return sanitize_text(text) or ""


def _charges(text: str) -> int | None:
    match = _CHARGES_RE.search(text)
    return int(match.group(1) or match.group(2)) if match else None


def _required_level(text: str) -> int | None:
    match = _REQUIRED_LEVEL_RE.search(text)
    return int(match.group(1)) if match else None


# ---- code lists (Class:, Race:) -------------------------------------------------------------


class _CodeList:
    """A ``Class:`` or ``Race:`` list: who may use the item. Read from the key's line and from the lines
    that wrap after it; ``render()`` gives the codes in universe order, ``["ALL"]`` for everyone."""

    def __init__(self, universe: list[str], where: str) -> None:
        self.universe = universe
        self.where = where
        self.everyone = False
        self.excluding = False
        self.none = False
        self.codes: set[str] = set()

    def read(self, value: str, w: _Warnings) -> None:
        words = [word for word in _SEPARATORS.split(_upper(value)) if word]
        if words == ["NONE"]:
            self.none = True
            w.add("no-classes", self.where)
            return
        for position, word in enumerate(words):
            if self.where == "race":
                word = RACE_ALIASES.get(word, word)
            if word == "ALL" and position == 0:
                self.everyone = True
            elif word == "EXCEPT" and self.everyone and not self.excluding:
                self.excluding = True
            elif word in self.universe:
                self.codes.add(word)
            else:
                w.add("unknown-code", self.where)
        if self.everyone and self.excluding and not self.codes:
            w.add("bad-value", self.where)  # "ALL except" with nothing after it
        elif not self.everyone and not self.codes:
            w.add("bad-value", self.where)

    def only_codes(self, text: str) -> list[str] | None:
        """The codes of a line that holds nothing but codes of this universe, else None."""
        words = [word for word in _SEPARATORS.split(_upper(text)) if word]
        if self.where == "race":
            words = [RACE_ALIASES.get(word, word) for word in words]
        return words if words and all(word in self.universe for word in words) else None

    def extend(self, codes: list[str]) -> bool:
        if self.none or (self.everyone and not self.excluding):
            return False  # nothing to add to "NONE" or to "ALL"
        self.codes.update(codes)
        return True

    def render(self) -> list[str]:
        if self.none:
            return []
        everyone = set(self.universe)
        chosen = everyone - self.codes if self.everyone and self.excluding else everyone if self.everyone else self.codes
        if chosen == everyone:
            return ["ALL"]
        return [code for code in self.universe if code in chosen]


# ---- parsing one statsblock -----------------------------------------------------------------


class _Block:
    """What the statsblock lines say, collected as they are read."""

    def __init__(self, warnings: _Warnings) -> None:
        self.w = warnings
        self.slots: set[str] = set()
        self.augment = False
        self.class_list: _CodeList | None = None
        self.race_list: _CodeList | None = None
        self.deity: list[str] | None = None
        self.flags: set[str] = set()
        self.stats: dict[str, int] = {}
        self.sv: dict[str, int] = {}
        self.resist_all = 0
        self.weight: float | None = None
        self.size: str | None = None
        self.item_type: str | None = None
        self.skill: str | None = None
        self.delay: int | None = None
        self.dmg: int | None = None
        self.bonus: int | None = None
        self.backstab: int | None = None
        self.elemental: dict | None = None
        self.capacity: int | None = None
        self.charges: int | None = None
        self.required_level: int | None = None
        self.recommended_level: int | None = None
        self.instrument_mods: dict[str, int] = {}
        self.effects: list[dict] = []
        self.last_effect: dict | None = None
        self.context: str | None = None  # "class", "race" or "deity" while a wrapped list may continue
        self.seen: set[str] = set()

    @property
    def classes(self) -> list[str] | None:
        return self.class_list.render() if self.class_list is not None else None

    @property
    def races(self) -> list[str] | None:
        return self.race_list.render() if self.race_list is not None else None

    # -- numbers --

    def number(self, value: str, where: str, *, integer: bool = True, lo: float, hi: float, percent: bool = False):
        """The number ``value`` starts with, or None (with a warning) if it is not a clean one in range.

        Text after the number is a ``trailing-text`` warning and the number is kept (``5 apples``, ``30 / 25``);
        a number followed at once by a letter or digit (``0x10``, ``1e3``, ``1,25``) is a ``bad-value``. A
        number of more than seven digits is ``out-of-range`` and is never converted.
        """
        text = value.translate(_MINUS).strip()
        match = _NUMBER.match(text)
        if not match:
            self.w.add("bad-value", where)
            return None
        sign, whole, fraction = match.groups()
        after = text[match.end() :]
        if ("," in whole and not _THOUSANDS.fullmatch(whole)) or after[:1].isalnum() or after[:1] == "_":
            self.w.add("bad-value", where)
            return None
        digits = whole.replace(",", "")
        if len(digits) > MAX_DIGITS or (fraction is not None and len(fraction) > MAX_DIGITS):
            self.w.add("out-of-range", where)
            return None
        if integer and fraction is not None:
            self.w.add("non-integer", where)
            return None
        number = (-1 if sign == "-" else 1) * (float(f"{digits}.{fraction}") if fraction is not None else int(digits))
        if not integer:
            number = float(number)
        if not lo <= number <= hi:
            self.w.add("out-of-range", where)
            return None
        rest = after.lstrip()
        if percent and rest.startswith("%"):
            rest = rest[1:]
        if not _HARMLESS_TAIL.fullmatch(rest):
            self.w.add("trailing-text", where)
        return number

    def once(self, key: str) -> bool:
        """True the first time a key is seen on this page; later ones are warned about and ignored."""
        if key in self.seen:
            self.w.add("duplicate-key", _field_name(key))
            return False
        self.seen.add(key)
        return True

    # -- a line --

    def line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        labelled = _EFFECT_LINE.fullmatch(line)
        if labelled or _UNLABELLED_EFFECT.match(line):
            self.context = None
            if labelled:
                self.effect(labelled.group(1), labelled.group(2))
            else:
                self.effect("effect", line)
            return
        if self.last_effect is not None and _CONTINUATION.match(line):
            self.context = None
            self.continuation(line)
            return
        if self.last_effect is not None and _CHARGES_ONLY.fullmatch(line):
            self.context = None
            self.segment("CHARGES", line.split(":", 1)[1].strip())  # the item's, and the effect's block goes on
            return
        self.last_effect = None
        context, self.context = self.context, None
        sentence = _LEVEL_SENTENCE.fullmatch(line)
        if sentence:
            self.level(f"{sentence.group(1).lower()}_level", sentence.group(2))
            return
        if _ORPHAN.match(line):
            self.continuation(line)  # no effect before it: a warning, never an error
            return
        resonance = _RESONANCE_LINE.fullmatch(line)
        if resonance:
            self.resonance(resonance.group(1).capitalize(), resonance.group(2))
            return
        source = _LINK_LABEL.sub(r"[[\1]]", line) if _DEITY_WORD.search(line) else line  # [[Rallos Zek|Rallos]] is the god Rallos Zek
        text = plain_text(source, unescape=False)  # a link around a key, [[Haste]]: +41%, is dropped
        matches = list(_BOUNDARY.finditer(text))
        if not matches:
            if not self.bare_line(text, context):
                self.w.add("unparsed-line", "statsblock")
            return
        head = text[: matches[0].start()].strip()
        if head and not self.flag_line(head):
            # words before the first key that are no flags: prose that happens to hold a stat word
            # ("VALUE TO VENDOR with CHA : 68"), not a statsblock line, so none of it is read
            self.w.add("unparsed-line", "statsblock")
            return
        unparsed = False
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            key = re.sub(r"[\s.]+", " ", match.group("colon") or match.group("bare") or match.group("dotted")).strip().upper()
            if not self.segment(key, text[match.end() : end].strip()):
                unparsed = True
        if unparsed:
            self.w.add("unparsed-line", "statsblock")  # one warning for the line, however many parts were unknown

    def segment(self, key: str, value: str) -> bool:
        """Read one ``key: value``. False if the key is not one this module knows."""
        if key == "SV":
            return self.sv_after_key(value)
        if key.startswith("SV "):
            self.sv_value(key[3:].strip(), value)
        elif key in _SV_ABBREVIATIONS:
            self.sv_value(_SV_ABBREVIATIONS[key], value)
        elif key in _STAT_ALIASES:
            self.stat(_STAT_ALIASES[key], value)
        elif _ELEMENT_KEY.fullmatch(key):
            self.do_elemental(key.split()[0].capitalize(), value)
        elif key in _OTHER_KEYS:
            getattr(self, "do_" + _OTHER_KEYS[key])(value)
        else:
            return False
        return True

    def bare_line(self, text: str, context: str | None) -> bool:
        """A line with no key: flags, the rest of a wrapped list, slot words alone, deity names alone."""
        if self.flag_line(text):
            return True
        if context in ("class", "race"):
            code_list = self.class_list if context == "class" else self.race_list
            codes = code_list.only_codes(text) if code_list is not None else None
            if codes is not None and code_list.extend(codes):
                self.context = context
                return True
        if context == "deity":
            names = self.only_deities(text)
            if names is not None:
                self.deity = list(dict.fromkeys([*(self.deity or []), *names]))
                self.context = "deity"
                return True
        slots = self.only_slots(text)
        if slots is not None:
            self.slots.update(slots)
            return True
        named = _DEITY_NO_COLON.fullmatch(text)
        if named:  # "Deity Prexus"
            self.do_deity(named.group(1))
            return True
        names = self.only_deities(text)
        if names is not None:  # a line of deity names and nothing else
            self.do_deity(text)
            return True
        return False

    # -- statsblock keys --

    def stat(self, stat: str, value: str) -> None:
        if not self.once(stat):
            return
        number = self.number(value, _field_name(stat), lo=_STAT_RANGE[0], hi=_STAT_RANGE[1], percent=stat == "HASTE")
        if number:
            self.stats[stat] = number

    def sv_after_key(self, value: str) -> bool:
        """``SV: Disease 4``: the school is the first word of the value."""
        match = re.match(r"\s*([A-Za-z]+)\s*(.*)", value, re.ASCII)
        if not match:
            self.w.add("unknown-sv", "sv")
            return True
        self.sv_value(_upper(match.group(1)), match.group(2))
        return True

    def sv_value(self, school: str, value: str) -> None:
        school = _upper(school)
        school = {"CORRUPT": "CORRUPTION"}.get(school, school)
        if school not in SV_KEYS:
            self.w.add("unknown-sv", "sv")
            return
        if not self.once("SV " + school):
            return
        number = self.number(value, "sv", lo=_STAT_RANGE[0], hi=_STAT_RANGE[1])
        if number:
            self.sv[school] = number

    def do_resist_all(self, value: str) -> None:
        number = self.number(value, "resist_all", lo=_STAT_RANGE[0], hi=_STAT_RANGE[1])
        if number:
            self.resist_all += number

    def do_ignored(self, value: str) -> None:  # Size Capacity, Weight Reduction, Range: known, not stored
        return

    def only_slots(self, text: str) -> list[str] | None:
        """The slots of a line that holds nothing but slot words (``Wrist``), else None."""
        words = [word for word in _SEPARATORS.split(_upper(text).replace("POWER SOURCE", "POWERSOURCE")) if word]
        if words and all(word in _SLOT_ALIASES for word in words):
            return [_SLOT_ALIASES[word] for word in words]
        return None

    def do_slot(self, value: str) -> None:
        if not self.once("SLOT"):
            return
        for word in _SEPARATORS.split(_upper(value).replace("POWER SOURCE", "POWERSOURCE")):
            if not word:
                continue
            if word in ("AUG", "AUGMENT", "AUGMENTATION"):
                self.augment = True
                self.w.add("augment-slot", "slot")
            elif word in _SLOT_ALIASES:
                self.slots.add(_SLOT_ALIASES[word])
            else:
                self.w.add("unknown-slot", "slot")

    def do_type(self, value: str) -> None:
        if self.once("TYPE"):
            self.item_type = self.display(value, "type")

    def do_class(self, value: str) -> None:
        if self.once("CLASS"):
            self.class_list = _CodeList(CLASS_CODES, "class")
            self.class_list.read(value, self.w)
            self.context = "class"

    def do_race(self, value: str) -> None:
        if self.once("RACE"):
            self.race_list = _CodeList(RACE_CODES, "race")
            self.race_list.read(value, self.w)
            self.context = "race"

    def deity_names(self, value: str) -> tuple[list[str], int]:
        """The deities in ``value`` (greedy match of the longest known name; links stripped; ``-`` ``/`` and
        ``,`` separate) and the number of words that are no deity."""
        value = _LINK_LABEL.sub(r"[[\1]]", value)  # [[Rallos Zek|Rallos]] names the god by its target
        words = [word for word in _DEITY_SEPARATORS.split(plain_text(value, unescape=False)) if word]
        known = {_lower(name): name for name in DEITIES}
        found: list[str] = []
        unknown = 0
        index = 0
        while index < len(words):
            for length in (3, 2, 1):  # the longest known name that starts here
                chunk = words[index : index + length]
                name = known.get(_lower(" ".join(chunk))) if len(chunk) == length else None
                if name:
                    if name not in found:
                        found.append(name)
                    index += length
                    break
            else:
                if _upper(words[index]) != "ALL":
                    unknown += 1
                index += 1
        return found, unknown

    def only_deities(self, text: str) -> list[str] | None:
        """The deities of a line that holds nothing but deity names, else None."""
        found, unknown = self.deity_names(text)
        return found if found and not unknown else None

    def do_deity(self, value: str) -> None:
        if not self.once("DEITY"):
            return
        found, unknown = self.deity_names(value)
        for _ in range(unknown):
            self.w.add("unknown-deity", "deity")
        self.deity = found or None
        self.context = "deity"

    def do_size(self, value: str) -> None:
        if not self.once("SIZE"):
            return
        size = _upper(value.strip())
        if size in SIZES:
            self.size = size
        else:
            self.w.add("bad-value", "size")

    def do_weight(self, value: str) -> None:
        if self.once("WT"):
            self.weight = self.number(value, "weight", integer=False, lo=0, hi=500)

    def do_skill(self, value: str) -> None:
        if self.once("SKILL"):
            self.skill = self.display(value, "skill")

    def do_delay(self, value: str) -> None:
        if self.once("DELAY"):
            self.delay = self.number(value, "delay", lo=1, hi=999)

    def do_dmg(self, value: str) -> None:
        if self.once("DMG"):
            self.dmg = self.number(value, "dmg", lo=_STAT_RANGE[0], hi=_STAT_RANGE[1])

    def do_bonus(self, value: str) -> None:
        if self.once("BONUS"):
            self.bonus = self.number(_BONUS_LEVEL.sub("", value), "bonus", lo=_STAT_RANGE[0], hi=_STAT_RANGE[1])

    def do_backstab(self, value: str) -> None:
        if self.once("BACKSTAB"):
            number = self.number(value, "backstab", lo=0, hi=_STAT_RANGE[1])
            if number:  # zero is omitted, like every other stat
                self.backstab = number

    def do_elemental(self, element: str, value: str) -> None:
        if not self.once("ELEMENTAL"):
            return
        number = self.number(value, "elemental", lo=_STAT_RANGE[0], hi=_STAT_RANGE[1])
        if number:
            self.elemental = {"type": element, "value": number}

    def do_charges(self, value: str) -> None:
        if re.fullmatch(r"\s*unlimited\s*\.?\s*", value, _ASCII):
            return  # "Unlimited" says nothing worth keeping
        if not self.once("CHARGES"):
            return
        number = self.number(value, "charges", lo=0, hi=999999)
        if number is not None:
            self.charges = number

    def resonance(self, kind: str, value: str) -> None:
        """``Wind Resonance: 12``: a bard instrument's modifier for one family of instruments."""
        if not self.once("RESONANCE " + kind.upper()):
            return
        if len(self.instrument_mods) >= MAX_INSTRUMENT_MODS:
            self.w.add("list-truncated", "instrument_mods")
            return
        number = self.number(value, "resonance", lo=-1000, hi=1000)
        if number:
            self.instrument_mods[kind] = number

    def do_capacity(self, value: str) -> None:
        if self.once("CAPACITY"):
            self.capacity = self.number(value, "capacity", lo=0, hi=1000)

    def do_required_level(self, value: str) -> None:
        self.level("required_level", value)

    def do_recommended_level(self, value: str) -> None:
        self.level("recommended_level", value)

    def level(self, which: str, value: str) -> None:
        if not self.once(which.upper()):
            return
        number = self.number(value, which, lo=1, hi=255)
        if number:
            setattr(self, which, number)

    def display(self, value: str, where: str) -> str | None:
        text = _display_text(value)
        if not text:
            self.w.add("empty-value", where)
            return None
        return text

    # -- flags --

    def flag_line(self, text: str) -> bool:
        """Read ``text`` as a list of flags. False (nothing recorded) unless it starts with a known one."""
        if not _FLAG.match(text):
            return False
        position = 0
        while position < len(text):
            separator = _SEPARATORS.match(text, position)
            if separator:
                position = separator.end()
                continue
            flag = _FLAG.match(text, position)
            if flag:
                self.flags.add(_FLAG_PHRASES[_upper(_WHITESPACE.sub(" ", flag.group(1)))])
                position = flag.end()
            else:
                word = _WORD.match(text, position)
                self.w.add("unknown-flag", "flags")
                position = word.end() if word else position + 1
        return True

    # -- effects --

    def effect(self, label: str, value: str) -> None:
        label = _lower(label)
        text = plain_text(value, unescape=False)
        parts = first_link_parts(value, unescape=False)
        if parts:
            target, link_label, target_with_parens = parts
            name = link_label if link_label and _lower(target) in GENERIC_EFFECT_TARGETS else target
        else:
            target_with_parens = ""
            name = re.sub(r"\s+at level \d+$", "", re.split(r"\s*\(", text, maxsplit=1)[0], flags=_ASCII)
        name = _EFFECT_PREFIX.sub("", name, count=1)  # "[[Effect: Flamesong]]": the author linked the label too
        if not name:
            self.w.add("bad-value", "effect")
            self.last_effect = None
            return
        info = _lower(" ".join(re.findall(r"\(([^()]*)\)", text + " " + target_with_parens)))
        if label == "focus effect":
            kind = "focus"
        elif label == "spell":
            kind = "spell"
        elif label in ("click effect", "consumable effect"):
            kind = "click"
        elif label == "worn effect":
            kind = "worn"
        elif label in ("proc effect", "combat effect"):
            kind = "proc"
        elif re.search(r"\bworn\b", info):
            kind = "worn"
        elif re.search(r"\bcombat\b", info):
            kind = "proc"
        elif re.search(r"any slot|must equip|can equip|casting time|\bclick\b", info):
            kind = "click"
        else:
            kind = "other"
        heading = " ".join(word.capitalize() for word in label.split())
        entry = {"kind": kind, "name": name, "raw": f"{heading}: {text}"}
        charges = _charges(text)  # only what the effect's own line says; a Charges line of its own is the item's
        if charges is not None:
            entry["charges"] = charges
        required = _required_level(text)
        if required is not None:
            entry["required_level"] = required
        if len(self.effects) < MAX_EFFECTS:
            self.effects.append(entry)
            self.last_effect = entry
        else:
            self.w.add("list-truncated", "effects")
            self.last_effect = None

    def continuation(self, line: str) -> None:
        """A casting time, required level or cooldown line after an effect (a "Charges" mentioned in it is the
        effect's). With no effect to belong to it is an ``orphan-continuation`` warning."""
        if self.last_effect is None:
            self.w.add("orphan-continuation", "statsblock")
            return
        text = plain_text(line, unescape=False)
        self.last_effect["raw"] += "; " + text
        charges = _charges(text)
        if charges is not None:
            self.last_effect["charges"] = charges
        required = _required_level(text)
        if required is not None:
            self.last_effect["required_level"] = required


# ---- the item -------------------------------------------------------------------------------


def _clean_list(values: list, limit_key: str, item: str, w: _Warnings) -> list[str]:
    """Sanitized, non-empty, in order, at most the limit for ``limit_key``."""
    cleaned = []
    for value in values:
        text = sanitize_text(value)
        if text:
            cleaned.append(text)
        else:
            w.add("empty-value", item)
    return _limit(cleaned, limit_key, w)


def _limit(items: list, limit_key: str, w: _Warnings) -> list:
    limit = LIST_LIMITS[limit_key]
    if len(items) > limit:
        w.add("list-truncated", limit_key)
        return items[:limit]
    return items


def _unique(items: list) -> list:
    seen: set = set()
    result = []
    for item in items:
        marker = json.dumps(item, sort_keys=True)
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result


def _sources(page: ParsedPage, w: _Warnings) -> dict:
    drops = []
    for drop in page.drops:
        zone = sanitize_text(drop.get("zone"))
        if drop.get("zone") is not None and not zone:
            w.add("empty-value", "zone")
            zone = None  # a zone that sanitizes to nothing is dropped, never stored as ""
        npcs = _clean_list(list(drop.get("npcs", [])), "npcs", "npc", w)
        if zone is None and not npcs:
            continue
        entry = {"zone": zone, "npcs": npcs}
        notes = _unique(_clean_list(list(drop.get("notes", [])), "notes", "note", w))
        if notes:
            entry["notes"] = notes
        drops.append(entry)
    sold_by = []
    for row in page.sold_by:
        npc = sanitize_text(row.get("npc"))
        zone = sanitize_text(row.get("zone"))
        if not npc:
            w.add("empty-value", "npc")
            continue
        sold_by.append({"zone": zone or None, "npc": npc})
    crafted = []
    for recipe in page.crafted:
        container = sanitize_text(recipe.get("container"))
        ingredients = _clean_list(list(recipe.get("ingredients", [])), "ingredients", "ingredient", w)
        if container or ingredients:
            crafted.append({"container": container or None, "ingredients": ingredients})
    quest_labels = []
    for entry in page.quest_labels:
        title, label = sanitize_text(entry.get("title")), sanitize_text(entry.get("label"))
        if title and label:
            quest_labels.append({"title": title, "label": label})
        elif title:
            w.add("empty-value", "quest")  # the label said nothing that can be stored: the title is still a quest
    foraged = []
    for zone_name in page.foraged:
        zone = sanitize_text(zone_name)
        if zone:
            foraged.append({"zone": zone})
        else:
            w.add("empty-value", "zone")
    sources = {
        "drops": _limit(drops, "drops", w),
        "sold_by": _limit(_unique(sold_by), "sold_by", w),
        "quests": _limit(_unique(_clean_list(list(page.quests), "quests", "quest", w)), "quests", w),
    }
    if quest_labels:
        sources["quest_labels"] = _limit(_unique(quest_labels), "quest_labels", w)
    sources["crafted"] = _limit(crafted, "crafted", w)
    if foraged:
        sources["foraged"] = _limit(_unique(foraged), "foraged", w)
    return sources


def _tier_rule(name: str, flags: set[str], sources: dict) -> str:
    has_drops = bool(sources["drops"])
    has_other = bool(sources["quests"] or sources["sold_by"] or sources["crafted"] or sources.get("foraged"))
    lowered = {_lower(flag) for flag in flags}
    summoned = bool({"temporary", "summoned"} & lowered) or bool(re.match(r"summoned\b", name, _ASCII))
    if summoned and not has_drops and not has_other:
        return "spell"
    return "drop" if has_drops else "fixed0"


def weapon_incomplete(weapon: Mapping[str, Any] | None, slots: Iterable[str]) -> bool:
    """True for a hand weapon that cannot be scored: it fits a hand slot, names a skill and lacks a damage or a delay.

    ``weapon`` is the item's ``weapon`` field (or None) and ``slots`` its slots. The model builds a weapon only from
    a damage and a delay, so such an item would count as no weapon, and an unscored two-hander could end up in the off
    hand. Ammunition has no delay by nature, a bow is not held in a hand and a weapon dict with no skill says nothing
    about the item being a weapon; none of them is incomplete. A damage of zero is a number.
    """
    return (
        weapon is not None
        and weapon.get("skill") is not None
        and (weapon.get("dmg") is None or weapon.get("delay") is None)
        and any(slot in HAND_SLOTS for slot in slots)
    )


def normalize(page: ParsedPage) -> dict:
    """The catalog item for a parsed page. See the module docstring and the schema."""
    if not isinstance(page.pageid, int) or page.pageid < 1:
        raise ValueError("a catalog item needs the wiki page id")
    w = _Warnings()
    for warning in page.warnings:
        w.add(str(warning.get("code")), str(warning.get("field")))

    block = _Block(w)
    lines = [_WHITESPACE.sub(" ", unicodedata.normalize("NFKC", raw)).strip() for raw in page.statsblock_lines]
    lines = [line for line in lines if line]
    if len(lines) > MAX_LINES:
        w.add("line-limit", "statsblock")
        lines = lines[:MAX_LINES]
    for line in lines:
        if len(line) > MAX_LINE_CHARS:
            w.add("line-limit", "statsblock")
            line = line[:MAX_LINE_CHARS]
        block.line(line)

    key = f"w{page.pageid}"
    name = sanitize_text(page.name) or sanitize_text(page.title) or ""
    if not name:
        w.add("empty-value", "name")
        name = key
    flags = set(block.flags) | {flag for flag in page.page_flags if flag in FLAGS}
    sources = _sources(page, w)

    stats = {stat: block.stats[stat] for stat in STAT_KEYS if stat in block.stats}
    sv = dict(block.sv)
    if block.resist_all:
        for school in RESIST_ALL_KEYS:
            sv[school] = sv.get(school, 0) + block.resist_all
    sv = {school: sv[school] for school in SV_KEYS if sv.get(school)}

    item_type, skill = block.item_type, block.skill
    if skill and block.dmg is None and block.delay is None and block.bonus is None:
        if _lower(skill) == "shield":
            item_type, skill = item_type or "Shield", None  # "Skill: Shield" is a shield, not a weapon
        elif _lower(skill) in SPELL_SCHOOLS:
            skill = None  # "Skill: Abjuration" is a spell scroll, not a weapon
    weapon = None
    if any(value is not None for value in (skill, block.delay, block.dmg, block.bonus, block.backstab, block.elemental)):
        weapon = {"skill": skill, "dmg": block.dmg, "delay": block.delay, "bonus": block.bonus}
        if block.backstab is not None:
            weapon["backstab"] = block.backstab
        if block.elemental is not None:
            weapon["elemental"] = block.elemental

    effects = []
    for effect in block.effects:  # sanitized once; the focus effects of the page come after, checked against these
        effect_name = sanitize_text(effect["name"])
        if not effect_name:
            w.add("empty-value", "effect")
            continue
        entry = {"kind": effect["kind"], "name": effect_name, "raw": sanitize_text(effect["raw"]) or effect_name}
        for optional in ("charges", "required_level"):
            if optional in effect:
                entry[optional] = effect[optional]
        effects.append(entry)
    focus_names = {entry["name"] for entry in effects if entry["kind"] == "focus"}
    for focus in page.focus_effects:
        focus_name = sanitize_text(focus)
        if not focus_name:
            w.add("empty-value", "effect")
        elif focus_name not in focus_names:
            if len(effects) >= MAX_EFFECTS:
                w.add("list-truncated", "effects")
                break
            focus_names.add(focus_name)
            effects.append({"kind": "focus", "name": focus_name, "raw": sanitize_text(f"Focus Effect: {focus_name}") or focus_name})

    slots = [] if block.augment else [slot for slot in SLOTS if slot in block.slots]
    if weapon_incomplete(weapon, slots):
        w.add("weapon-incomplete", "weapon")

    categories = _limit(_unique(_clean_list(list(page.categories), "categories", "category", w)), "categories", w)
    era_spellings: dict[str, str] = {}
    for tag in page.era_tags:
        text = sanitize_text(tag)
        if not text:
            w.add("empty-value", "era_tag")
        elif text.endswith(" Era"):
            marker = _lower(text)
            era_spellings[marker] = min(text, era_spellings.get(marker, text))
        else:
            w.add("bad-value", "era_tag")
    era_tags = [era_spellings[marker] for marker in sorted(era_spellings)]
    if len(era_tags) > MAX_ERA_TAGS:
        w.add("list-truncated", "era_tags")
        era_tags = era_tags[:MAX_ERA_TAGS]

    item = {
        "key": key,
        "name": name,
        "wiki": {"pageid": page.pageid, "revid": page.revid, "title": sanitize_text(page.title) or name},
        "slots": slots,
        "classes": block.classes if block.classes is not None else ["ALL"],
        "races": block.races if block.races is not None else ["ALL"],
        "deity": block.deity,
        "flags": [flag for flag in FLAGS if flag in flags],
        "stats": stats,
        "sv": sv,
        "weight": block.weight,
        "size": block.size,
        "item_type": item_type,
        "item_type_source": "statsblock" if item_type else None,
        "weapon": weapon,
        "container_capacity": block.capacity,
        "instrument_mods": dict(sorted(block.instrument_mods.items())),
        "effects": effects,
        "required_level": block.required_level,
        "recommended_level": block.recommended_level,
        "sources": sources,
        "categories": categories,
        "era_tags": era_tags,
        "lucy_img_id": page.lucy_img_id,
        "tier_rule": _tier_rule(name, flags, sources),
        "parse_warnings": w.items,
        "parse_warnings_overflow": w.overflow,
    }
    if block.charges is not None:
        item["charges"] = block.charges
    return item


def promote_bullet_zones(drops: list[dict], is_zone: Callable[[str], bool]) -> list[dict]:
    """The drops of an item whose page writes its zones as bullets, with those zones made zones.

    A drop list with no zone line (no line of its own, no link above the bullets) comes out of the parser as one
    entry with no zone, and every bullet in it is a creature. Where such a list has bullets that name a zone the
    build knows (``is_zone``, the alias table: ``* [[Plane of Sky]]``, or ``* Warrens`` over ``** [[a creature]]``), each
    of them is a zone and the bullets after it, up to the next one, are its creatures; creatures before the first
    zone stay without a zone. A list that has a zone line, or no bullet that is a zone, is returned as it is. The
    argument is not changed.
    """
    if not drops or any(drop.get("zone") for drop in drops):
        return drops
    result: list[dict] = []
    for drop in drops:
        creatures = drop.get("npcs") or []
        if not any(is_zone(name) for name in creatures):
            result.append(drop)
            continue
        groups = [{"zone": None, "npcs": []}]  # the creatures before the first zone bullet
        for name in creatures:
            if is_zone(name):
                groups.append({"zone": name, "npcs": []})
            else:
                groups[-1]["npcs"].append(name)
        made = [group for group in groups if group["zone"] is not None or group["npcs"]]
        if drop.get("notes") and made:
            made[-1]["notes"] = list(drop["notes"])
        result.extend(made)
    return result[: LIST_LIMITS["drops"]]


# ---- the schema ----------------------------------------------------------------------------

SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "catalog-item.schema.json"


@functools.lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_item(item: dict) -> None:
    """Raise ``jsonschema.ValidationError`` if ``item`` is not a valid catalog item."""
    _validator().validate(item)
