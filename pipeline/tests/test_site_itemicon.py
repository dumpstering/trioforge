"""Which picture an item gets (``trioforge.site.itemicon``): the one function that says it, tried by hand-written cases.

The rule is the maintainer's: a plain head word of the name says what an item is, and it says it whatever the skill (an Orb of Tishan is an orb though its skill is one-handed blunt); the skill
only gives the picture of a weapon whose name says nothing about what it is; a head word that names an object the art has no picture of (a halberd, a whip) gives no picture at all; a shield,
an instrument and a book are also told by the catalog; a piece of armor gets the picture of its part in the material of its fashion category, unless the name contradicts the category or names a shape
the picture does not show; and an item that nothing says plainly about gets none of its own (a row then draws the picture of its worn place, and a held place none). A name is read word by word,
never inside a word: the staff of Falstaff is not a staff.

The thirteen pictures of the held things (an idol, a stone, a horn, a lantern, a cup, a scroll, a rod, a whip, a claw, a pick, a polearm, a charm, a fishing pole) are given by the head word to a held item (it
fits the main hand, the off hand or the range) that has no picture of its own by the rest of the rule, and to nothing else: a ring named "... Seal" and a neck piece named "Talisman" are worn and keep what they
had, and a weapon whose word the rule already knew (a club, a shard, a stone it throws) keeps the picture it had. An item that none of these pictures fits is drawn with the pouch on a held row (art.py).
"""

from __future__ import annotations

import pytest

from trioforge.site import itemicon
from trioforge.site.itemicon import icon_name


def weapon(name: str, skill: str, slots=("PRIMARY", "SECONDARY")) -> dict:
    return {"name": name, "slots": list(slots), "weapon": {"skill": skill, "dmg": 10, "delay": 30, "bonus": None}}


#: the head words the maintainer named for each of the thirteen pictures of the held things (2026-11-13), as the test knows them, without the five the review took out the same day (bo, bokken, stick, eye, seal:
#: they were guesses, and are tested below to give nothing)
HELD_WORDS_OF_THE_BRIEF = {
    "icon-idol": ["totem", "idol", "doll", "statue", "statuette", "figurine", "effigy", "fetish"],
    "icon-stone": ["stone", "gem", "crystal", "globe", "pearl", "shard", "rock", "jewel"],
    "icon-horn": ["horn"],
    "icon-lantern": ["torch", "lantern", "candle", "lamp", "brazier"],
    "icon-cup": ["stein", "mug", "chalice", "cup", "goblet", "flask", "vial", "bottle", "flagon", "tankard"],
    "icon-scroll": ["scroll", "writ", "parchment", "note", "letter", "map"],
    "icon-rod": ["rod", "baton", "cane"],
    "icon-whip": ["whip", "lash", "scourge"],
    "icon-claw": ["claw", "claws", "talon", "talons"],
    "icon-pick": ["pick", "pickaxe", "mattock"],
    "icon-polearm": ["halberd", "scythe", "naginata", "voulge", "glaive", "poleaxe", "polearm", "bardiche"],
    "icon-charm": ["brooch", "talisman", "charm", "amulet", "medal", "medallion", "symbol", "sigil", "emblem", "token", "badge"],
    "icon-fishing-pole": ["fishingpole", "fishingrod"],
}


@pytest.mark.parametrize(
    ("name", "skill", "want"),
    [
        # one-handed slashing: a sword, or an axe where the name says axe
        ("Rusty Blade", "1H Slashing", "icon-sword-1h"),
        ("Fine Steel Scimitar", "1H Slashing", "icon-sword-1h"),
        ("Orc Hand Axe", "1H Slashing", "icon-axe-1h"),
        ("Battleaxe of the Hollow", "1H Slashing", "icon-axe-1h"),
        # two-handed slashing
        ("Great Sword of the Vale", "2H Slashing", "icon-sword-2h"),
        ("Greatsword", "2H Slashing", "icon-sword-2h"),
        ("Two Handed Battle Axe", "2H Slashing", "icon-axe-2h"),
        ("Greataxe", "2H Slashing", "icon-axe-2h"),
        # one-handed blunt: a mace unless the name says hammer, staff or wand
        ("Iron Club", "1H Blunt", "icon-mace"),
        ("Morning Star", "1H Blunt", "icon-mace"),
        ("Bronze Mace", "1H Blunt", "icon-mace"),
        ("Dwarven Warhammer", "1H Blunt", "icon-hammer-1h"),
        ("Smith's Mallet", "1H Blunt", "icon-hammer-1h"),
        ("Oaken Staff", "1H Blunt", "icon-staff"),
        ("Runestaff of Embers", "1H Blunt", "icon-staff"),
        ("Wand of Sparks", "1H Blunt", "icon-wand"),
        # two-handed blunt: a hammer unless the name says staff
        ("Bone Cudgel", "2H Blunt", "icon-hammer-2h"),
        ("Great Maul", "2H Blunt", "icon-hammer-2h"),
        ("Sledgehammer", "2H Blunt", "icon-hammer-2h"),
        ("Staff of the Seer", "2H Blunt", "icon-staff"),
        ("Warstaff", "2H Blunt", "icon-staff"),
        # piercing: a dagger, or a spear where the name says so, and a two-handed one is a spear
        ("Steel Dagger", "Piercing", "icon-dagger"),
        ("Boar Spear", "Piercing", "icon-spear"),
        ("Fisher's Harpoon", "Piercing", "icon-spear"),
        ("Pike of the Guard", "1H Piercing", "icon-spear"),
        ("Knife", "1H Piercing", "icon-dagger"),
        ("Jousting Lance", "2H Piercing", "icon-spear"),
        ("Odd Looking Spike", "2H Piercing", "icon-spear"),
        # the rest of the skills
        ("Iron Knuckles", "Hand to Hand", "icon-fist"),
        ("Forged Shuriken", "Throwingv1", "icon-throwing"),
        ("Velium Dart", "Throwingv2", "icon-throwing"),
        ("Short Bow", "Archery", "icon-bow"),
    ],
)
def test_a_weapon_gets_the_picture_of_its_kind(name, skill, want):
    assert icon_name(weapon(name, skill)) == want


@pytest.mark.parametrize(
    ("name", "skill", "want"),
    [
        ("Orb of Tishan", "1H Blunt", "icon-orb"),
        ("Tome of Rage", "1H Slashing", "icon-book"),
        ("Black Tome with Silver Runes", "1H Blunt", "icon-book"),
        ("Encyclopedia Necrotheurgia", "1H Blunt", "icon-book"),
        ("Seer Lore Book", "2H Blunt", "icon-book"),
        ("Warstaff of Hope's Demise", "1H Piercing", "icon-staff"),
        ("Short Staff", "Piercing", "icon-staff"),
        ("Wand of Fire", "1H Slashing", "icon-wand"),
        ("Silver Wand", "Piercing", "icon-wand"),
        ("Forged Throwing Spear", "Throwingv2", "icon-spear"),
        ("Velium Throwing Axe", "Throwing", "icon-axe-1h"),
        ("Black Rock Maul of Crushing", "2H Slashing", "icon-hammer-2h"),
        ("Bronze Battle Axe", "2H Blunt", "icon-axe-2h"),
        ("Rusty Axe", "1H Blunt", "icon-axe-1h"),
        ("Short Sword", "2H Blunt", "icon-sword-2h"),
        ("Fine Rapier", "Piercing", "icon-sword-1h"),
        ("Odd Looking Dagger", "2H Piercing", "icon-dagger"),
        ("Throwing Knife", "Throwingv2", "icon-dagger"),
        ("Bronze Mace", "2H Blunt", "icon-mace"),
        ("Hammer of the Ancients", "1H Slashing", "icon-hammer-1h"),
        ("Lute of the Gypsy Princess", "1H Blunt", "icon-instrument"),
        ("Iron Fist", "1H Blunt", "icon-fist"),
        ("Short Bow of the Fallen", "1H Piercing", "icon-bow"),
    ],
)
def test_a_plain_head_word_beats_the_skill(name, skill, want):
    assert icon_name(weapon(name, skill)) == want


@pytest.mark.parametrize("skill", ["1H Slashing", "2H Slashing", "1H Blunt", "2H Blunt", "Piercing", "1H Piercing", "2H Piercing", "Hand to Hand", "Throwing", "Archery"])
@pytest.mark.parametrize(
    "name",
    ["Shovel of the Harvest", "Holy Censer", "Rusty Crossbow", "Fine Steel Tonfa", "Bronze Jutte", "Cracked Branch", "Giant's Broom", "Herbalist's Spade", "Teir`Dal Sai", "Shimmering Partisan", "Shrieking Ahlspiess"],
)
def test_a_head_word_that_names_an_object_the_art_has_no_picture_of_gives_no_picture(name, skill):
    assert icon_name(weapon(name, skill)) is None  # (not the skill's: a shovel is not a sword; the objects the art has since drawn, a whip or a halberd, are in the test of the held pictures below)


@pytest.mark.parametrize("skill", ["1H Slashing", "2H Slashing", "1H Blunt", "2H Blunt", "Piercing", "1H Piercing", "2H Piercing", "Hand to Hand", "Throwing", "Archery"])
@pytest.mark.parametrize(
    ("name", "want"),
    [
        ("Rusty Halberd", "icon-polearm"), ("Rusty Scythe", "icon-polearm"), ("Fine Naginata", "icon-polearm"), ("Odd Voulge", "icon-polearm"), ("Glaive of Dawn", "icon-polearm"),
        ("Barbed Leather Whip", "icon-whip"), ("Sharp Claws", "icon-claw"), ("Rusty Claw", "icon-claw"), ("Mining Pick", "icon-pick"),
        ("Rod of Faith", "icon-rod"),
        ("Fighting Baton", "icon-rod"), ("Cane of Harmony", "icon-rod"), ("Slaver's Lash", "icon-whip"), ("Stormfeather Talons", "icon-claw"), ("Repurposed Pickaxe", "icon-pick"),
        ("Cast Iron Stein", "icon-cup"), ("Shaded Torch", "icon-lantern"), ("Bone Totem", "icon-idol"), ("Paebala Fetish", "icon-idol"), ("Tuuak's Fishing Pole", "icon-fishing-pole"),
    ],
)
def test_a_weapon_whose_head_word_was_an_object_the_art_had_no_picture_of_has_the_new_picture_whatever_its_skill(name, want, skill):
    assert icon_name(weapon(name, skill)) == want


def test_a_word_of_the_name_is_read_whole_and_never_inside_another_word():
    assert icon_name(weapon("Saxen Blade", "1H Slashing")) == "icon-sword-1h"  # axe in Saxen
    assert icon_name(weapon("Falstaff's Rod", "1H Blunt")) == "icon-rod"  # (a rod, and no staff in Falstaff)
    assert icon_name(weapon("Falstaff's Club", "1H Blunt")) == "icon-mace"
    assert icon_name(weapon("Wanderer's Club", "1H Blunt")) == "icon-mace"  # wand in Wanderer
    assert icon_name(weapon("Hammerfall Cudgel", "2H Blunt")) == "icon-hammer-2h"
    assert icon_name(weapon("Spiked Club", "1H Blunt")) == "icon-mace"  # pike in Spiked
    assert icon_name(weapon("Spikes of Rage", "Piercing")) == "icon-dagger"  # pike in Spikes
    assert icon_name(weapon("Balanced Blade", "Piercing")) == "icon-dagger"  # lance in Balanced
    assert icon_name(weapon("Flaxen Blade", "1H Slashing")) == "icon-sword-1h"  # axe in Flaxen
    assert icon_name(weapon("Taxer's Mace", "1H Blunt")) == "icon-mace"
    assert icon_name(weapon("Ax`s Blade", "1H Slashing")) == "icon-sword-1h"  # (no such word)
    assert icon_name(weapon("Berserker's Axe", "1H Slashing")) == "icon-axe-1h"  # the apostrophe ends a word, and the axe is what the item is
    assert icon_name(weapon("Éaxe", "1H Slashing")) == "icon-sword-1h"  # a letter with an accent is a letter: Éaxe is one word, and not an axe
    assert icon_name(weapon("Blade of Ñaxe", "1H Slashing")) == "icon-sword-1h"
    assert icon_name(weapon("Ñandú Axe", "1H Slashing")) == "icon-axe-1h"


def test_a_name_says_the_kind_by_what_the_item_is_not_by_any_word_in_it():
    assert icon_name(weapon("Axe-Handled Blade", "1H Slashing")) == "icon-sword-1h"  # a blade with an axe's handle is a blade
    assert icon_name(weapon("Blade of the Axe Lord", "1H Slashing")) == "icon-sword-1h"
    assert icon_name(weapon("Axe of the Frost", "2H Slashing")) == "icon-axe-2h"  # (what comes after the of describes it)
    assert icon_name(weapon("Staff of the Wand", "1H Blunt")) == "icon-staff"
    assert icon_name(weapon("Wand Staff", "1H Blunt")) == "icon-staff"  # the last word is the head
    assert icon_name(weapon("Spear of the Dagger", "Piercing")) == "icon-spear"
    assert icon_name(weapon("Dagger of the Spear", "Piercing")) == "icon-dagger"
    assert icon_name(weapon("Short Staff (Lesser)", "1H Blunt")) == "icon-staff"  # a parenthesis is no part of the name
    assert icon_name(weapon("Staff of Elemental Mastery: Air", "2H Blunt")) == "icon-staff"
    assert icon_name(weapon("", "1H Blunt")) == "icon-mace" and icon_name(weapon("Of the Axe", "1H Slashing")) == "icon-sword-1h"  # no head word, no kind


def test_a_kind_after_a_comma_counts_and_two_kinds_say_neither():
    assert icon_name(weapon("Hammer, Rusty", "1H Blunt")) == "icon-hammer-1h"
    assert icon_name(weapon("Crookstinger, Axe of Pain", "1H Slashing")) == "icon-axe-1h"  # "X, Axe of Y" is an axe
    assert icon_name(weapon("Talisen, Bow of the Trailblazer", "Archery")) == "icon-bow"
    assert icon_name(weapon("Aldryn, Blade of the Ocean", "1H Slashing")) == "icon-sword-1h"  # nothing said: the skill's
    assert icon_name(weapon("Axe, Hammer of Doom", "1H Slashing")) is None  # two kinds
    assert icon_name(weapon("Rusty Whip, Axe of Pain", "1H Slashing")) == "icon-axe-1h"  # a kind outweighs a word the art has no picture of


def test_a_head_word_that_says_nothing_leaves_the_skills_own_picture_and_a_bad_skill_leaves_none():
    for name in ("Windstriker", "Aldryn", "Frostreaver", "Bone Razor", "The Reaver of Souls"):
        assert icon_name(weapon(name, "1H Slashing")) == "icon-sword-1h", name
    assert icon_name(weapon("Windstriker", "1H Blunt")) == "icon-mace"
    for skill in ("1H Slash", "1H Slashing /", "None", "", "Fishing", None):
        assert icon_name(weapon("Rusty Blade", skill)) is None, skill  # (a skill the data wrote badly is never guessed at)
        assert icon_name(weapon("Rusty Sword", skill)) is None, skill


def test_a_shield_is_what_the_catalog_says_and_never_what_the_name_says():
    assert icon_name({"name": "Oaken Targe", "slots": ["SECONDARY"], "item_type": "Shield"}) == "icon-shield"
    assert icon_name({"name": "Shield of the Devout", "slots": ["SECONDARY"], "item_type": None}) is None
    assert icon_name({"name": "Shield of the Devout", "slots": ["SECONDARY"]}) is None
    assert icon_name({**weapon("Spiked Buckler", "1H Blunt"), "item_type": "Shield"}) == "icon-shield"  # the catalog's word holds for a weapon too


def test_an_instrument_is_told_by_the_catalog_or_plainly_by_the_name_and_only_where_it_is_held():
    assert icon_name({"name": "Battered Thing", "slots": ["SECONDARY"], "instrument_mods": {"Brass": 15}}) == "icon-instrument"
    assert icon_name({"name": "Crude Wooden Flute", "slots": ["PRIMARY", "SECONDARY"]}) == "icon-instrument"
    assert icon_name({"name": "Nostrolo Tambourine", "slots": ["SECONDARY"]}) == "icon-instrument"
    assert icon_name({"name": "Lute of Souls", "slots": ["RANGE"]}) == "icon-instrument"
    assert icon_name({"name": "Flute Ring", "slots": ["FINGER"]}) is None  # not held
    for part in ("Fine Lute Tuners", "Flute Mouthpiece", "Unfinished Lute Neck", "Unfinished Lute Body"):
        assert icon_name({"name": part, "slots": ["SECONDARY"]}) is None, part  # the part of an instrument is not the instrument: its head word is another
    assert icon_name({"name": "Selo`s Drums of the March", "slots": ["PRIMARY", "SECONDARY"]}) == "icon-instrument"
    assert icon_name({"name": "Fluted Mace", "slots": ["PRIMARY"]}) is None  # flute is not fluted
    assert icon_name({"name": "Plain Thing", "slots": ["SECONDARY"], "instrument_mods": {}}) is None


def test_a_book_a_wand_and_an_orb_are_told_plainly_by_the_name_where_they_are_held_with_a_skill_or_without():
    assert icon_name({"name": "Book of Tactics", "slots": ["RANGE"]}) == "icon-book"
    assert icon_name({"name": "Gnoll Hide Tome", "slots": ["PRIMARY"]}) == "icon-book"
    assert icon_name({"name": "Encyclopedia Necrotheurgia", "slots": ["PRIMARY", "SECONDARY"]}) == "icon-book"
    assert icon_name({"name": "Orb of Draconic Energy", "slots": ["SECONDARY"]}) == "icon-orb"
    assert icon_name({"name": "Orb of Mastery", "slots": ["PRIMARY", "SECONDARY"]}) == "icon-orb"
    assert icon_name({"name": "Wand of Frost Bolts", "slots": ["PRIMARY", "SECONDARY"]}) == "icon-wand"  # a wand that is not a weapon of the catalog is a wand all the same
    assert icon_name({"name": "Orb Ring", "slots": ["FINGER"]}) is None
    assert icon_name({"name": "Forbidden Relic", "slots": ["SECONDARY"]}) is None  # orb in forbidden
    assert icon_name({"name": "Bookmark", "slots": ["RANGE"]}) is None
    assert icon_name({"name": "Book of Songs", "slots": ["SECONDARY"], "instrument_mods": {"String": 9}}) is None  # the catalog says an instrument and the name a book: neither
    assert icon_name({"name": "Orb Gauntlets", "slots": ["SECONDARY"]}) is None  # the head word is gauntlets
    assert icon_name({"name": "Black Tome with Silver Runes", "slots": ["PRIMARY"]}) == "icon-book"
    assert icon_name({"name": "Summoned: Orb of Exploration", "slots": ["PRIMARY", "SECONDARY"]}) == "icon-orb"
    assert icon_name({"name": "Globe of Fear", "slots": ["RANGE"]}) == "icon-stone"  # a globe is a stone of the art (the thirteen pictures of the held things, below); an orb stays an orb
    assert icon_name({"name": "Crystal Orb Shield", "slots": ["SECONDARY"], "item_type": "Shield"}) == "icon-shield"  # the catalog's shield outranks a word of the name


def test_a_sword_that_is_no_weapon_of_the_catalog_gets_no_weapon_picture():
    assert icon_name({"name": "Sword of Ceremony", "slots": ["PRIMARY"]}) is None  # (only a weapon's skill makes it the weapon the art shows)
    assert icon_name({"name": "Staff of Rightful Rule", "slots": ["PRIMARY", "SECONDARY"]}) is None


#: a name of each part that the picture of each material shows
SHOWN = {
    "HEAD": {"cloth": "Silk Hood", "leather": "Leather Cap", "chain": "Chain Coif", "plate": "Plate Helm"},
    "CHEST": {"cloth": "Silk Robe", "leather": "Leather Tunic", "chain": "Chain Mail", "plate": "Plate Breastplate"},
    "ARMS": {"cloth": "Silk Sleeves", "leather": "Leather Sleeves", "chain": "Chain Sleeves", "plate": "Plate Vambraces"},
    "LEGS": {"cloth": "Silk Leggings", "leather": "Leather Leggings", "chain": "Chain Leggings", "plate": "Plate Greaves"},
    "FEET": {"cloth": "Silk Slippers", "leather": "Leather Boots", "chain": "Chain Boots", "plate": "Plate Boots"},
    "HANDS": {"cloth": "Silk Gloves", "leather": "Leather Gloves", "chain": "Chain Gloves", "plate": "Plate Gauntlets"},
}


@pytest.mark.parametrize("part", ["HEAD", "CHEST", "ARMS", "LEGS", "FEET", "HANDS"])
@pytest.mark.parametrize(("category", "material"), [("Fashion: Plate", "plate"), ("Fashion: Leather", "leather"), ("Fashion: Chain", "chain"), ("Fashion: Cloth", "cloth")])
def test_a_piece_of_armor_gets_its_part_in_the_material_of_its_fashion_category(part, category, material):
    stem = {"HEAD": "helm", "CHEST": "chest", "ARMS": "arms", "LEGS": "legs", "FEET": "feet", "HANDS": "hands"}[part]
    plain = SHOWN[part][material].split(" ", 1)[1]  # the name without its material word says nothing against the category
    for name in (SHOWN[part][material], plain, f"{plain} of the Vale"):
        assert icon_name({"name": name, "slots": [part], "categories": ["Quest Items", category, part.title()]}) == f"icon-{stem}-{material}", name


@pytest.mark.parametrize(
    ("name", "slot", "category", "want"),
    [
        # the reviewer's examples: the name says a material that the category does not
        ("Ry`Gorr Chain Coif", "HEAD", "Fashion: Plate", None),
        ("Ry`Gorr Chain Coif", "HEAD", "Fashion: Chain", "icon-helm-chain"),
        ("Teir`Dal Chain Coif", "HEAD", "Fashion: Leather", None),
        ("Midnight Sea Mail Leggings", "LEGS", "Fashion: Leather", None),
        ("Midnight Sea Mail Leggings", "LEGS", "Fashion: Chain", "icon-legs-chain"),
        ("Eroded Leather Gloves", "HANDS", "Fashion: Plate", None),
        ("Eroded Leather Gloves", "HANDS", "Fashion: Leather", "icon-hands-leather"),
        ("Ice Silk Sleeves", "ARMS", "Fashion: Leather", None),
        ("Ice Silk Sleeves", "ARMS", "Fashion: Cloth", "icon-arms-cloth"),
        ("Studded Leather Tunic", "CHEST", "Fashion: Leather", "icon-chest-leather"),
        ("Leather and Silk Boots", "FEET", "Fashion: Leather", None),  # two materials say neither
        ("Scaled Knight's Helm", "HEAD", "Fashion: Leather", None),  # scale is a material the four pictures do not show
        ("Hide Boots", "FEET", "Fashion: Leather", "icon-feet-leather"),
        ("Hide Boots", "FEET", "Fashion: Cloth", None),
        ("Platemail Gauntlets", "HANDS", "Fashion: Chain", None),
        # a shape the picture of the material does not show
        ("Breastplate of Distraction", "CHEST", "Fashion: Cloth", None),
        ("Breastplate of Distraction", "CHEST", "Fashion: Plate", "icon-chest-plate"),
        ("White Dragon Helm", "HEAD", "Fashion: Cloth", None),
        ("Crown of Leaves", "HEAD", "Fashion: Cloth", None),
        ("Jeweled Circlet", "HEAD", "Fashion: Cloth", None),
        ("Gold Tiara", "HEAD", "Fashion: Cloth", None),
        ("Flower Headband", "HEAD", "Fashion: Cloth", None),
        ("Flower of the Vale", "HEAD", "Fashion: Cloth", None),
        ("Sacred Mask", "HEAD", "Fashion: Cloth", None),
        ("Fine Helmet", "HEAD", "Fashion: Cloth", None),
        ("Fine Coif", "HEAD", "Fashion: Cloth", None),
        ("Hooded Cowl", "HEAD", "Fashion: Cloth", "icon-helm-cloth"),
        ("Golden Crown", "HEAD", "Fashion: Plate", None),
        ("Tunic of the Fallen", "CHEST", "Fashion: Plate", None),
        ("Leather Kilt", "LEGS", "Fashion: Leather", None),
        ("Bone Fists", "HANDS", "Fashion: Plate", None),
        ("Wraps of the Fist", "HANDS", "Fashion: Leather", None),
        ("Wrist Skullcap", "ARMS", "Fashion: Leather", None),
        ("Sandals of Wind", "FEET", "Fashion: Leather", None),
    ],
)
def test_armor_is_given_a_picture_only_when_the_name_does_not_contradict_the_category(name, slot, category, want):
    assert icon_name({"name": name, "slots": [slot], "categories": [category]}) == want


def test_armor_that_the_catalog_does_not_say_the_material_of_gets_none():
    base = {"name": "Plate Breastplate", "slots": ["CHEST"]}
    assert icon_name(base) is None  # no categories at all (the item table alone has none)
    assert icon_name({**base, "categories": []}) is None
    assert icon_name({**base, "categories": ["Fashion: Velious Plate 2"]}) is None  # only the four fashion categories are read
    assert icon_name({**base, "categories": ["Fashion: Cloth", "Fashion: Plate"]}) is None  # two materials: neither
    assert icon_name({**base, "categories": ["Fashion: Plate", "Fashion: Plate"]}) == "icon-chest-plate"
    assert icon_name({"name": "Silver Chains", "slots": ["SHOULDERS", "ARMS", "BACK", "CHEST", "LEGS"], "categories": ["Fashion: Chain"]}) is None  # many parts: no one part
    assert icon_name({"name": "Gem Ring", "slots": ["FINGER"], "categories": ["Fashion: Plate"]}) is None  # not a part that has a picture of its material
    assert icon_name({"name": "Cloak", "slots": ["BACK"], "categories": ["Fashion: Leather"]}) is None


def test_a_weapon_outranks_the_held_words_and_the_armor_rule():
    both = {"name": "Gauntlets of Axes", "slots": ["HANDS", "PRIMARY"], "categories": ["Fashion: Leather"], "weapon": {"skill": "Hand to Hand"}}
    assert icon_name(both) == "icon-fist"
    held_armor = {"name": "Gauntlets of the Orb", "slots": ["HANDS", "PRIMARY"], "categories": ["Fashion: Leather"]}
    assert icon_name(held_armor) is None  # (it fits a hand and the hands: no one part, and no word that says what it is held as)
    assert icon_name({"name": "Sparring Orb", "slots": ["HANDS", "PRIMARY"], "categories": ["Fashion: Leather"]}) == "icon-orb"  # (held: what the name says plainly comes before the material)


def test_what_nothing_says_plainly_gets_none_and_a_record_with_little_in_it_does_not_break_the_rule():
    for item in ({}, {"name": "x"}, {"name": None, "slots": None}, {"name": "Ring", "slots": ["FINGER"]}, {"name": "Charm", "slots": ["CHARM"]}, {"name": "Arrows", "slots": ["AMMO"]},
                 {"name": "Wand", "slots": ["FACE"], "weapon": None}, {"name": "Plate Helm", "slots": ["HEAD"], "categories": "Fashion: Plate"}):
        assert icon_name(item) is None, item
    for weapon_record in ({}, "1H Blunt", {"skill": None}):  # (a weapon record that says nothing: the word that says it, held, is enough)
        assert icon_name({"name": "Wand", "slots": ["PRIMARY"], "weapon": weapon_record}) == "icon-wand"


def test_every_name_the_rule_can_give_is_listed():
    held = ["sword-1h", "sword-2h", "axe-1h", "axe-2h", "dagger", "spear", "mace", "hammer-1h", "hammer-2h", "staff", "wand", "fist", "throwing", "shield", "orb", "book", "instrument"]
    armor = [f"{part}-{material}" for part in ("helm", "chest", "arms", "legs", "feet", "hands") for material in ("cloth", "leather", "chain", "plate")]
    things = ["idol", "stone", "horn", "lantern", "cup", "scroll", "rod", "whip", "claw", "pick", "polearm", "charm", "fishing-pole"]  # (the thirteen pictures of the held things)
    assert sorted(itemicon.ALL_ICONS) == sorted(f"icon-{name}" for name in [*held, "bow", *things, *armor])  # (the pouch is not here: no rule gives an item a pouch, a held row falls back to it)


def test_every_name_the_rule_can_give_is_reached_by_some_name():
    """The list is not a promise the rule cannot keep: each of its icons comes out of a name the rule is given (and the three lists of words are disjoint)."""
    reached = set()
    for objects in itemicon.OBJECT_WORDS.values():
        assert not objects & itemicon.DENIED_WORDS
    for kind, words in itemicon.OBJECT_WORDS.items():
        word = sorted(words)[0]
        for skill in ("1H Slashing", "2H Slashing", "1H Blunt"):
            reached.add(icon_name(weapon(f"Old {word.title()}", skill)))
    for skill in itemicon.WEAPON_SKILLS:
        reached.add(icon_name(weapon("Windstriker", skill)))
    for part, materials in SHOWN.items():
        for material, name in materials.items():
            reached.add(icon_name({"name": name, "slots": [part], "categories": [f"Fashion: {material.title()}"]}))
    reached.add(icon_name({"name": "Oaken Targe", "slots": ["SECONDARY"], "item_type": "Shield"}))
    for words in HELD_WORDS_OF_THE_BRIEF.values():
        reached.add(icon_name({"name": f"Old {words[0].title()}", "slots": ["SECONDARY"]}))
    assert itemicon.ALL_ICONS <= reached, sorted(itemicon.ALL_ICONS - reached)


# ---- the thirteen pictures of the held things (the maintainer's brief of 2026-11-13) --------------------------------------------------------------------


def held(name: str, slots=("SECONDARY",), **more) -> dict:
    """An item that is held and has no weapon skill (a doll, a stone, a torch)."""
    return {"name": name, "slots": list(slots), **more}


@pytest.mark.parametrize(("picture", "word"), [(picture, word) for picture, words in HELD_WORDS_OF_THE_BRIEF.items() for word in words])
@pytest.mark.parametrize("slots", [("PRIMARY",), ("SECONDARY",), ("RANGE",), ("PRIMARY", "SECONDARY"), ("PRIMARY", "RANGE", "SECONDARY")])
def test_every_head_word_of_the_brief_gives_its_picture_to_a_held_item_that_has_none(picture, word, slots):
    assert icon_name(held(f"Old {word.title()}", slots)) == picture
    assert icon_name(held(f"{word.title()} of the Vale", slots)) == picture  # (what comes after the of describes it)
    assert icon_name(held(f"Something, {word.title()} of Old", slots)) == picture  # (a kind after a comma counts)
    assert icon_name(held(f"Old {word.title()}" + ("" if word.endswith("s") else "s"), slots)) == picture  # (and the plural)


REAL_NAMES = [
    ("Idol of Karana", "icon-idol"), ("Hexed Kerran Doll", "icon-idol"), ("Bone Totem", "icon-idol"), ("Bronze Statue of Bathezid", "icon-idol"), ("Paebala Fetish", "icon-idol"),
    ("Frosted Gem", "icon-stone"), ("Quartz Crystal", "icon-stone"), ("Globe of Darkness", "icon-stone"), ("Summoned: Shard of the Core", "icon-stone"),
    ("Alluring Horn", "icon-horn"), ("A Worn Candle", "icon-lantern"), ("Violet Flame Lantern", "icon-lantern"), ("Shaded Torch", "icon-lantern"),
    ("Cast Iron Stein", "icon-cup"), ("Doogle's Signature Souvenir Mug", "icon-cup"), ("Chalice of Kings", "icon-cup"), ("Vial of Clear Mana", "icon-cup"),
    ("Prophecy Scroll", "icon-scroll"), ("Writ of Dragonkind", "icon-scroll"),
    ("Rod of Identification", "icon-rod"), ("Fighting Baton", "icon-rod"), ("Cane of Harmony", "icon-rod"), ("Carved Walking Stick", "icon-staff"), ("Bo Stick", "icon-staff"),
    ("Slaver's Lash", "icon-whip"), ("Barbed Leather Whip", "icon-whip"), ("Bladed Thulian Claws", "icon-claw"), ("Stormfeather Talons", "icon-claw"),
    ("Mining Pick", "icon-pick"), ("Repurposed Pickaxe", "icon-pick"), ("Bronze Naginata", "icon-polearm"), ("Glaive of Marltek", "icon-polearm"), ("Rusty Scythe", "icon-polearm"), ("Footman's Voulge", "icon-polearm"),
    ("Soldier's Brooch of the Virtuous", "icon-charm"), ("Bone Talisman", "icon-charm"), ("Tuuak's Fishing Pole", "icon-fishing-pole"), ("Kerran Fishingpole", "icon-fishing-pole"),
]


@pytest.mark.parametrize(("name", "want"), REAL_NAMES)
def test_the_items_of_the_release_that_the_brief_meant_get_their_picture(name, want):
    assert icon_name(held(name)) == want
    assert icon_name(held(name, ("PRIMARY", "RANGE", "SECONDARY"))) == want


@pytest.mark.parametrize(
    ("name", "slots", "want"),
    [
        # a head word says what the item is; any other word of the name does not
        ("Stone Hammer", ("PRIMARY",), None),  # (not a weapon of the catalog: the words of weapons say nothing of it, and stone is not its head word)
        ("Stone Idol Hammer", ("PRIMARY",), None),
        ("Eye Patch", ("SECONDARY",), None),
        ("Crystal Ball", ("RANGE",), None),  # the head word is ball: no picture says it (an orb is an orb; a ball is not)
        ("Idol Stand", ("SECONDARY",), None),
        ("Totem Pole", ("SECONDARY",), None),
        ("Torch Holder", ("SECONDARY",), None),
        ("Stein Rack", ("SECONDARY",), None),
        ("Seal Skin", ("SECONDARY",), None),
        ("Horn Polish", ("SECONDARY",), None),
        ("Pick Handle", ("PRIMARY",), None),
        ("Whip Cord", ("PRIMARY",), None),
        ("Claw Sharpener", ("PRIMARY",), None),
        ("Scroll Case", ("SECONDARY",), None),
        ("Chalice Case", ("PRIMARY", "SECONDARY"), None),
        ("Lightstone", ("PRIMARY", "SECONDARY"), None),  # lightstone is one word of its own: not a lantern, and not a stone
        ("Thunderstone", ("RANGE",), None),
        ("Lockpicks", ("PRIMARY",), None),
        ("Toothpick", ("PRIMARY",), None),
        ("Bowl of Watery Protection", ("PRIMARY",), None),  # a bowl is not a cup
        ("Small Protection Deity", ("PRIMARY", "SECONDARY", "RANGE"), None),
        ("Gnoll Hide Lariat", ("PRIMARY", "SECONDARY"), None),  # a lariat is not a whip
        ("Poison Wind Censer", ("PRIMARY",), None),
        ("Mosscovered Branch", ("PRIMARY",), None),
        ("A Shovel", ("PRIMARY", "SECONDARY"), None),
        ("Snapped Pole", ("PRIMARY",), None),  # a pole of no fishing
        ("Shimmering Partisan", ("PRIMARY", "SECONDARY"), None),
        ("Crook", ("PRIMARY",), None),
        # the same words in the head: the picture
        ("Crystal", ("RANGE",), "icon-stone"),
        ("Brooch", ("RANGE",), "icon-charm"),
        ("Eye of Newt", ("SECONDARY",), None),  # an eye is no stone (the review took the word out: an eyeball is not a crystal ball)
        ("Seal", ("RANGE",), None),  # a seal is no charm (the review took the word out)
        ("Hand Torch", ("PRIMARY", "SECONDARY"), "icon-lantern"),
    ],
)
def test_a_picture_of_the_held_things_is_given_by_the_head_word_and_never_by_another_word_of_the_name(name, slots, want):
    assert icon_name(held(name, slots)) == want


def test_a_weapon_keeps_the_picture_the_rule_gave_it_before_and_only_what_had_none_gets_a_new_one():
    """"Stone Hammer" is a hammer; a head word the rule already knew keeps its picture; a word it did not know (a club, a scepter, a shard) keeps the skill's picture, as before, so that no weapon loses the one it had."""
    assert icon_name(weapon("Stone Hammer", "1H Blunt")) == "icon-hammer-1h"
    assert icon_name(weapon("Idol Staff", "2H Blunt")) == "icon-staff"
    assert icon_name(weapon("Axe of the Idol", "2H Slashing")) == "icon-axe-2h"
    assert icon_name(weapon("Crookstinger, Axe of Pain", "1H Slashing")) == "icon-axe-1h"
    assert icon_name(weapon("Rusty Whip, Axe of Pain", "1H Slashing")) == "icon-axe-1h"  # (a kind outweighs a word the art has no picture of: as before)
    assert icon_name(weapon("Orb of Tishan", "1H Blunt")) == "icon-orb"  # (orb keeps the orb)
    assert icon_name(weapon("Crystal Orb", "1H Blunt")) == "icon-orb"
    assert icon_name(weapon("Iron Club", "1H Blunt")) == "icon-mace" and icon_name(weapon("Warclub", "2H Blunt")) == "icon-hammer-2h"  # (a club keeps what it has)
    assert icon_name(weapon("Skipping Stone", "Throwing")) == "icon-throwing"  # (a stone that is thrown: its skill's picture, as it had)
    assert icon_name(weapon("Shard of Pain", "1H Slashing")) == "icon-sword-1h"
    assert icon_name(weapon("Gharn's Rock of Smashing", "1H Blunt")) == "icon-mace"
    assert icon_name(weapon("Scepter of Mastery", "1H Blunt")) == "icon-mace" and icon_name(weapon("Delgin's Sceptre", "1H Blunt")) == "icon-mace"
    assert icon_name(weapon("Nevederia's Horn", "Piercing")) == "icon-dagger"  # (a weapon that is a horn keeps its skill's picture: only an instrument is a horn)
    assert icon_name(weapon("Stronghorn's Horn", "1H Blunt")) == "icon-mace"
    assert icon_name(weapon("Idol, Scroll of Doom", "1H Blunt")) == "icon-mace"  # (two of the new kinds say neither, and the weapon has what the skill gave it)
    assert icon_name(held("Idol, Scroll of Doom")) is None  # two of the new kinds say neither


def test_a_scepter_is_a_rod_only_where_the_rule_gave_it_no_picture_before():
    assert icon_name(held("Gleaming Crystal Scepter", ("PRIMARY", "SECONDARY"))) == "icon-rod"
    assert icon_name(held("Sceptre of Doom", ("PRIMARY",))) == "icon-rod"
    assert icon_name(weapon("Gem-Encrusted Scepter", "1H Blunt")) == "icon-mace"
    assert icon_name(weapon("Scepter of the Forlorn", "1H Blunt")) == "icon-mace"
    assert icon_name(held("Scepter", ("FINGER",))) is None  # (worn)


def test_a_fishing_pole_is_the_two_words_and_beats_the_rod_and_a_pole_alone_is_nothing():
    for name in ("Fishing Pole", "Rickety Fishing Pole", "Aglthin's Fishing Pole", "Kerran Fishingpole", "Fishing Rod", "Fishing Rod of the Deep", "Fishingrod", "Grey Wood Fishing Pole"):
        assert icon_name(held(name, ("PRIMARY",))) == "icon-fishing-pole", name
        assert icon_name(weapon(name, "1H Blunt", ("PRIMARY", "SECONDARY"))) == "icon-fishing-pole", name
    for name in ("Rod of Faith", "Fisherman's Rod", "Rod of Fishing", "Iron Rod"):
        assert icon_name(held(name, ("PRIMARY",))) == "icon-rod", name
    for name in ("Snapped Pole", "Pole", "Tent Pole", "Fishing Net", "Fishing Hook", "Fishing Bait"):
        assert icon_name(held(name, ("PRIMARY",))) is None, name


def test_a_horn_is_the_horn_even_where_the_catalog_says_instrument_and_the_other_instruments_keep_theirs():
    mods = {"Brass": 12}
    for name in ("Horn", "Denon's Horn of Disaster", "Immaculate Shell Horn", "Conch Shell Horn", "Verlekarnorm's Horn of Disaster"):
        assert icon_name(held(name, ("PRIMARY", "SECONDARY"), instrument_mods=mods)) == "icon-horn", name  # (the catalog says instrument and the name says horn: the horn)
        assert icon_name(held(name, ("PRIMARY", "SECONDARY"))) == "icon-horn", name
    for name in ("Crude Wooden Flute", "Lute of the Gypsy Princess", "Hand Drum", "Mystical Lute", "Nostrolo Tambourine"):
        assert icon_name(held(name, ("PRIMARY", "SECONDARY"), instrument_mods=mods)) == "icon-instrument", name
    assert icon_name(held("Scorpion Pincer", ("SECONDARY",), instrument_mods=mods)) == "icon-instrument"  # (an instrument that is no horn)
    assert icon_name(held("Battered Thing", ("SECONDARY",), instrument_mods=mods)) == "icon-instrument"
    assert icon_name(held("Horn Mouthpiece", ("SECONDARY",))) == "icon-horn"
    assert icon_name(held("Flute Mouthpiece", ("SECONDARY",))) is None  # a flute's mouthpiece is no horn and no instrument
    assert icon_name(held("Brass Mouthpiece", ("SECONDARY",))) is None
    assert icon_name(held("Trumpet Valves", ("SECONDARY",))) is None
    assert icon_name(held("Horn", ("FINGER",), instrument_mods=mods)) is None  # (worn: nothing)


def test_an_orb_stays_an_orb_and_the_words_of_a_stone_make_a_stone():
    for name in ("Orb of Draconic Energy", "Crystalline Orb", "Orb of Mastery", "Crystal Orb"):
        assert icon_name(held(name)) == "icon-orb", name
    for name in ("Stone of Morid", "Glowing Black Stone", "Hate Crystal", "Pulsating Gem", "Globe of Fear", "Black Pearl", "Frozen Rock", "Jeweled Jewel"):
        assert icon_name(held(name)) == "icon-stone", name
    assert icon_name(held("Crystal Orb Shield", item_type="Shield")) == "icon-shield"  # (the catalog's shield outranks the name, as before)
    assert icon_name(held("Spiked Stone", item_type="Shield")) == "icon-shield"


@pytest.mark.parametrize("slots", [("FINGER",), ("NECK",), ("EAR",), ("WRIST",), ("FACE",), ("HEAD",), ("WAIST",), ("BACK",), ("SHOULDERS",), ("CHEST",), ("NECK", "WRIST"), ("EAR", "FINGER"), ("AMMO",), ("CHARM",), ("POWERSOURCE",), ()])
@pytest.mark.parametrize("name", [f"Old {word.title()}" for words in HELD_WORDS_OF_THE_BRIEF.values() for word in words] + ["Gypsy Seal", "Stone Earring", "Talisman of the Wise", "Idol Ring", "Eye of the Sphinx", "Brooch of Valor", "Fishing Pole"])
def test_a_worn_only_item_keeps_exactly_what_it_shows_today_whatever_its_name_says(name, slots):
    """A ring named "... Seal", an earring named "... Stone" and a neck piece named "Talisman" are worn, not held: none of the new pictures, and nothing else changed for them."""
    assert icon_name({"name": name, "slots": list(slots)}) is None
    assert icon_name({"name": name, "slots": list(slots), "categories": ["Fashion: Plate"]}) is None


def test_a_worn_only_item_keeps_the_picture_the_rule_gave_it_before_and_an_item_of_both_places_gets_the_held_picture():
    assert icon_name({"name": "Plate Helm", "slots": ["HEAD"], "categories": ["Fashion: Plate"]}) == "icon-helm-plate"
    assert icon_name({"name": "Rusty Whip", "slots": ["WAIST"], "weapon": {"skill": "1H Slashing"}}) is None  # (a weapon that is worn: as before, the word is denied)
    assert icon_name({"name": "Rusty Axe", "slots": ["WAIST"], "weapon": {"skill": "1H Slashing"}}) == "icon-axe-1h"
    assert icon_name({"name": "Cat Eye Seal", "slots": ["FINGER"], "categories": ["Fashion: Leather"]}) is None
    assert icon_name(held("Gem of Rage", ("NECK", "RANGE"))) == "icon-stone"  # (it fits the range: a held item, so it has the picture of its name)
    assert icon_name(held("Pulsating Gem", ("AMMO", "NECK", "PRIMARY", "SECONDARY"))) == "icon-stone"
    assert icon_name(held("Idol of Woven Grass", ("NECK", "SECONDARY"))) == "icon-idol"
    assert icon_name({"name": "Tsiraka's Claws", "slots": ["HANDS", "PRIMARY"], "weapon": {"skill": "Piercing"}}) == "icon-claw"


def test_the_words_of_the_brief_are_the_words_the_rule_knows_and_the_lists_do_not_overlap():
    known = itemicon.HELD_WORDS
    assert set(known) == {picture.removeprefix("icon-") for picture in HELD_WORDS_OF_THE_BRIEF}
    for picture, words in HELD_WORDS_OF_THE_BRIEF.items():
        for word in words:
            assert word in known[picture.removeprefix("icon-")], (picture, word)
    seen: dict[str, str] = {}
    for kind, words in known.items():
        for word in words:
            assert word not in seen, f"{word} is in {seen[word]} and in {kind}"
            seen[word] = kind
    assert not set(seen) & {word for words in itemicon.OBJECT_WORDS.values() for word in words}  # (a word of the new pictures is none of the old objects: orb keeps orb, pike stays a spear)
    assert {"pike", "orb", "club", "lightstone", "bowl", "ball", "deity", "lariat", "partisan"}.isdisjoint(seen)


# ---- the review of 2026-11-13: the guesses are out --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("skill", [None, "1H Blunt", "2H Blunt"])
@pytest.mark.parametrize("name", ["Bo Stick", "Adamantite Bo Stick", "Bamboo Bo Stick", "Greenwood Bo Stick", "Ton Po's Bo Stick of Understanding", "Carved Walking Stick", "Journeyman's Walking Stick", "Walking Stick"])
def test_a_bo_stick_and_a_walking_stick_are_staves_as_phrases(name, skill):
    item = held(name, ("PRIMARY", "SECONDARY")) if skill is None else weapon(name, skill)
    assert icon_name(item) == "icon-staff", (name, skill)


@pytest.mark.parametrize("skill", [None, "1H Blunt", "2H Blunt", "1H Slashing"])
@pytest.mark.parametrize("name", ["Brawl Stick", "Carved Velium Brawl Stick", "Exquisite Velium Brawl Stick", "Blam Stick", "Broken Blam Stick", "Master Wu's Trance Stick", "Stick", "Wooden Stick", "Bamboo Bokken", "Runed Bokken", "Bokken"])
def test_any_other_stick_and_a_bokken_have_no_picture(name, skill):
    item = held(name, ("PRIMARY", "SECONDARY")) if skill is None else weapon(name, skill)
    assert icon_name(item) is None, (name, skill)  # (a held row of it shows the pouch)


def test_a_bo_is_a_staff_only_as_a_two_handed_blunt_weapon_and_a_tanto_or_a_wakizashi_bo_is_nothing():
    assert icon_name(weapon("Bo", "2H Blunt")) == "icon-staff" and icon_name(weapon("Bamboo Bo", "2H Blunt")) == "icon-staff"
    for skill in ("1H Blunt", "1H Slashing", "2H Slashing", "Piercing", "Hand to Hand"):
        assert icon_name(weapon("Bamboo Bo", skill)) is None, skill
    for name in ("Bamboo Tanto Bo", "Reinforced Bamboo Tanto Bo", "Bamboo Wakizashi Bo", "Reinforced Bamboo Wakizashi Bo", "Tanto Bo", "Wakizashi Bo"):
        for skill in ("1H Blunt", "2H Blunt"):
            assert icon_name(weapon(name, skill)) is None, (name, skill)
    assert icon_name(held("Bamboo Bo", ("PRIMARY", "SECONDARY"))) is None  # (no skill, no weapon: not a staff)
    assert icon_name({"name": "Bamboo Bo", "slots": ["WAIST"], "weapon": {"skill": "2H Blunt"}}) is None  # (not held: as it was, a denied word)


def test_an_eye_a_seal_and_the_other_words_the_review_took_out_give_nothing_and_a_brooch_and_a_talisman_still_give_the_charm():
    for name in ("Eye of Kor", "Batling Eye", "Nevederia's Left Eye", "Fire Beetle Eye", "Seal of Thoridain", "Crushbone Seal"):
        assert icon_name(held(name)) is None, name
        assert icon_name(held(name, ("RANGE",))) is None, name
    assert icon_name(weapon("Eye of the Rigtorgn", "1H Blunt")) is None  # (a denied word, and no longer a stone: the pouch)
    for name in ("Soldier's Brooch of the Virtuous", "Bone Talisman", "Talisman of Benevolence"):
        assert icon_name(held(name, ("RANGE",))) == "icon-charm", name
    known = {word for words in itemicon.HELD_WORDS.values() for word in words}
    assert known.isdisjoint({"bo", "bokken", "stick", "sticks", "eye", "eyes", "seal", "seals"})
    assert itemicon.HELD_PHRASES[("bo", "stick")] == "icon-staff" and itemicon.HELD_PHRASES[("walking", "stick")] == "icon-staff"
