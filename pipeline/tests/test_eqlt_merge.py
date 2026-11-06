"""EQ Legends Tools in the catalog (p7nek): the tooltip overrides the wiki's copy, an item the wiki lacks is added, and the build records it.

The wiki pages here are invented in the shape of the real ones (an ``Itempage`` template); the tooltips are the saved pages under
``fixtures/eqlegendstools`` and small pages made in the tests.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from trioforge.data import eqlt_merge
from trioforge.data.catalog import parse_and_normalize
from trioforge.data.normalize import validate_item
from trioforge.sources import eqlegendstools as eqlt

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "eqlegendstools"
CHECKMATE = eqlt.parse_item_page((FIXTURES / "item-checkmate.html").read_text(encoding="utf-8"), "checkmate")

WIKI_CHECKMATE = """{{Classic Era}}
<onlyinclude>{{Itempage
|itemname = Checkmate
|lucy_img_ID = 619
|notes = super rare and low drop rate
|statsblock =
Attunable<br>
Slot: EAR<br>
AC: 6<br>
WIS: +8  INT: +5  CHA: +5  MANA: +10  Mana Regen: +2<br>
SV MAGIC: +5  SV FIRE: +5<br>
Size: TINY WT: 0.1<br>
Class: WAR MNK ROG BER<br>
Race: ALL<br>
|focus_effect = Improved Damage III
|dropsfrom =

[[Nektropos Castle]]

* [[The Game Master]]

|relatedquests =

* [[The Betrayer]]

}}</onlyinclude>
{{Revamped}}
[[Category:Ear]]
"""


def wiki_item(pageid=73036, title="Checkmate", content=WIKI_CHECKMATE):
    kind, item = parse_and_normalize({"pageid": pageid, "ns": 0, "title": title, "revid": 199709, "timestamp": "2026-10-20T00:00:00Z", "content": content})
    assert kind == "item"
    return item


def tooltip(lines, name="Checkmate", slug="checkmate", flags="Attunable", drops=None):
    drops = drops if drops is not None else [{"zone": "Nektropos Castle", "npcs": ["The Game Master"]}]
    return eqlt.EqltItem(slug=slug, name=name, lines=list(lines), flags_text=flags, drops=drops, upgrade_level=0)


# ---- precedence over a wiki copy ----------------------------------------------------------------------------------------


def test_the_tooltip_overrides_the_wiki_copy_and_the_item_keeps_its_wiki_identity_and_its_other_sources():
    wiki = wiki_item()
    assert wiki["stats"]["WIS"] == 8 and wiki["stats"]["MANA"] == 10  # the wiki says 8 and 10; the site says 5 and 5
    items, report = eqlt_merge.merge_eqlegendstools([wiki], [CHECKMATE])
    (merged,) = items
    validate_item(merged)
    assert merged["stats"] == {"AC": 6, "WIS": 5, "INT": 5, "CHA": 5, "MANA": 5, "MANAREG": 2}
    assert merged["key"] == wiki["key"] == "w73036" and merged["wiki"] == wiki["wiki"] and merged["name"] == "Checkmate"
    assert merged["sources"]["quests"] == ["The Betrayer"]  # what a tooltip does not carry stays the wiki's
    assert merged["lucy_img_id"] == 619 and merged["era_tags"] == wiki["era_tags"] and merged["categories"] == wiki["categories"]
    assert "wiki_banner_revamped" in merged["flags"] and "attunable" in merged["flags"]  # the banner belongs to the page, the flag to the tooltip
    assert merged["origin"] == {"source": "eqlegendstools", "slug": "checkmate", "overrides_wiki": True}
    assert report["overridden"] == [{"key": "w73036", "name": "Checkmate", "slug": "checkmate"}] and report["added"] == []


def test_the_report_lists_every_field_where_the_two_disagree():
    _, report = eqlt_merge.merge_eqlegendstools([wiki_item()], [CHECKMATE])
    found = {(d["field"], json.dumps(d["wiki"]), json.dumps(d["eqlt"])) for d in report["disagreements"]}
    assert found == {("stats.WIS", "8", "5"), ("stats.MANA", "10", "5")}


def test_a_tooltip_that_agrees_with_the_wiki_makes_no_disagreement():
    agree = tooltip(["Slot: EAR", "AC: 6", "WIS: +8 INT: +5 CHA: +5 MANA: +10 Mana Regen: +2", "SV MAGIC: +5 SV FIRE: +5", "Focus Effect: Improved Damage III", "WT: 0.1 Size: TINY", "Class: WAR MNK ROG BER"])
    _, report = eqlt_merge.merge_eqlegendstools([wiki_item()], [agree])
    assert report["disagreements"] == []


def test_the_drop_list_is_the_tooltips_and_a_stat_the_tooltip_omits_is_gone():
    wiki = wiki_item()
    page = tooltip(["Slot: EAR", "AC: 6", "Class: WAR MNK ROG BER"], drops=[{"zone": "Nektropos Castle", "npcs": ["A Different Mob"]}])
    (merged,), report = eqlt_merge.merge_eqlegendstools([wiki], [page])
    assert merged["sources"]["drops"] == [{"zone": "Nektropos Castle", "npcs": ["A Different Mob"]}]
    assert merged["stats"] == {"AC": 6} and merged["sv"] == {} and merged["effects"] == []  # (a tooltip lists every stat the item has)
    fields = {d["field"] for d in report["disagreements"]}
    assert {"stats.WIS", "stats.INT", "sv.MAGIC", "effects", "drops"} <= fields


def test_the_wiki_copy_given_is_not_changed():
    wiki = wiki_item()
    before = copy.deepcopy(wiki)
    eqlt_merge.merge_eqlegendstools([wiki], [CHECKMATE])
    assert wiki == before


def test_the_match_ignores_case_apostrophes_and_spacing():
    wiki = wiki_item(title="Gambler's Gambit", content=WIKI_CHECKMATE.replace("itemname = Checkmate", "itemname = Gambler's Gambit"))
    page = tooltip(["Slot: EAR", "Class: ALL"], name="Gamblers  Gambit", slug="gamblers-gambit")
    (merged,), report = eqlt_merge.merge_eqlegendstools([wiki], [page])
    assert merged["key"] == "w73036" and merged["name"] == "Gambler's Gambit" and report["added"] == []


# ---- unknown fields stay unknown -----------------------------------------------------------------------------------------------


def test_a_field_the_tooltip_leaves_out_keeps_the_wiki_value_and_the_report_says_so():
    wiki = wiki_item()
    page = tooltip(["Slot: EAR", "AC: 6", "Class: WAR MNK ROG BER"])  # no weight, no size, no race, no deity
    (merged,), report = eqlt_merge.merge_eqlegendstools([wiki], [page])
    assert merged["weight"] == 0.1 and merged["size"] == "TINY" and merged["races"] == ["ALL"]
    (unknown,) = report["left_unknown"]
    assert {"weight", "size", "races", "deity"} <= set(unknown["fields"])


def test_a_new_item_with_no_weight_has_none_not_zero():
    (added,), _ = eqlt_merge.merge_eqlegendstools([], [tooltip(["Slot: EAR", "Class: ALL"])])
    assert added["weight"] is None and added["size"] is None and added["stats"] == {}


# ---- an item the wiki lacks ----------------------------------------------------------------------------------------------------


def test_an_item_the_wiki_lacks_is_added_with_a_key_of_its_own_and_no_wiki_page():
    other = wiki_item(pageid=5, title="Plain Ring", content=WIKI_CHECKMATE.replace("itemname = Checkmate", "itemname = Plain Ring"))
    items, report = eqlt_merge.merge_eqlegendstools([other], [CHECKMATE])
    assert [item["key"] for item in items] == ["w5", "rlt-checkmate"]
    added = items[1]
    validate_item(added)
    assert added["wiki"] is None and added["origin"] == {"source": "eqlegendstools", "slug": "checkmate", "overrides_wiki": False}
    assert report["added"] == [{"key": "rlt-checkmate", "name": "Checkmate", "slug": "checkmate", "slots": ["EAR"]}] and report["overridden"] == []


def test_two_pages_for_one_wiki_item_are_a_conflict():
    twin = tooltip(["Slot: EAR", "Class: ALL"], slug="checkmate-2")
    with pytest.raises(ValueError, match="both the wiki item w73036"):
        eqlt_merge.merge_eqlegendstools([wiki_item()], [CHECKMATE, twin])


def test_a_slug_given_twice_is_one_page():
    items, report = eqlt_merge.merge_eqlegendstools([], [CHECKMATE, CHECKMATE])
    assert len(items) == 1 and report["pages"] == 1


def test_a_key_is_a_valid_catalog_key_for_the_longest_slug():
    slug = "a" * 96
    assert len(eqlt_merge.eqlt_key(slug)) == 100
    (added,), _ = eqlt_merge.merge_eqlegendstools([], [tooltip(["Slot: EAR", "Class: ALL"], slug=slug)])
    validate_item(added)


# ---- p7nekfix: what a tooltip does not show stays the wiki's, and what cannot be solved honestly is not guessed ------------------------------------------


def test_a_page_with_no_flags_line_keeps_the_wiki_flags_and_lists_flags_as_unknown():
    wiki = wiki_item(content=WIKI_CHECKMATE.replace("Attunable<br>", "Lore Equipped, No Trade<br>"))
    assert {"lore", "no_trade"} <= set(wiki["flags"])
    page = tooltip(["Slot: EAR", "AC: 6", "Class: WAR MNK ROG BER"], flags=None)
    (merged,), report = eqlt_merge.merge_eqlegendstools([wiki], [page])
    assert set(merged["flags"]) == set(wiki["flags"]) and "lore" in merged["flags"]  # Lore is never silently dropped
    assert "flags" in report["left_unknown"][0]["fields"]


def test_a_page_with_a_flags_line_replaces_the_wiki_flags_and_keeps_the_banner_flags():
    wiki = wiki_item(content=WIKI_CHECKMATE.replace("Attunable<br>", "Lore Equipped, No Trade<br>"))
    page = tooltip(["Slot: EAR", "AC: 6", "Class: WAR MNK ROG BER"], flags="Attunable")
    (merged,), report = eqlt_merge.merge_eqlegendstools([wiki], [page])
    assert "lore" not in merged["flags"] and "attunable" in merged["flags"] and "wiki_banner_revamped" in merged["flags"]
    assert not report["left_unknown"] or "flags" not in report["left_unknown"][0]["fields"]


def test_a_new_item_whose_tooltip_has_no_class_line_is_skipped_with_a_warning_not_given_all_classes():
    no_class = tooltip(["Slot: EAR", "AC: 6"], name="Classless Ring", slug="classless-ring")
    no_slot = tooltip(["Class: ALL", "AC: 6"], name="Slotless Ring", slug="slotless-ring")
    whole = tooltip(["Slot: EAR", "Class: ALL"], name="Whole Ring", slug="whole-ring")
    items, report = eqlt_merge.merge_eqlegendstools([], [no_class, no_slot, whole])
    assert [item["key"] for item in items] == ["rlt-whole-ring"]
    assert report["skipped"] == [
        {"slug": "classless-ring", "name": "Classless Ring", "missing": ["class"]},
        {"slug": "slotless-ring", "name": "Slotless Ring", "missing": ["slot"]},
    ]
    assert report["pages"] == 3 and [a["slug"] for a in report["added"]] == ["whole-ring"]


def test_an_item_the_wiki_has_is_not_skipped_for_a_missing_class_line_it_keeps_the_wiki_classes():
    page = tooltip(["Slot: EAR", "AC: 6"])
    (merged,), report = eqlt_merge.merge_eqlegendstools([wiki_item()], [page])
    assert merged["classes"] == ["WAR", "MNK", "ROG", "BER"] and report["skipped"] == []


WIKI_BLADE = """{{Classic Era}}
<onlyinclude>{{Itempage
|itemname = Checkmate
|statsblock =
Slot: PRIMARY<br>
Skill: Piercing  Atk Delay: 20<br>
DMG: 11<br>
BACKSTAB: 13<br>
Dmg Bon: 10<br>
Size: SMALL WT: 3.5<br>
Class: ROG<br>
|dropsfrom =

[[Nektropos Castle]]

* [[The Game Master]]

}}</onlyinclude>
"""


def test_a_weapon_is_merged_field_by_field_a_field_the_tooltip_omits_keeps_the_wiki_value_and_is_unknown():
    wiki = wiki_item(content=WIKI_BLADE)
    assert wiki["weapon"] == {"skill": "Piercing", "dmg": 11, "delay": 20, "bonus": 10, "backstab": 13}
    page = tooltip(["Slot: PRIMARY", "Skill: 1H Piercing Atk Delay: 22", "DMG: 12", "Class: ROG"])  # no bonus, no backstab
    (merged,), report = eqlt_merge.merge_eqlegendstools([wiki], [page])
    assert merged["weapon"] == {"skill": "1H Piercing", "dmg": 12, "delay": 22, "bonus": 10, "backstab": 13}
    assert {"weapon.bonus", "weapon.backstab"} <= set(report["left_unknown"][0]["fields"])
    assert "weapon.dmg" not in report["left_unknown"][0]["fields"]
    assert {"weapon.skill", "weapon.dmg", "weapon.delay"} <= {d["field"] for d in report["disagreements"]}
    validate_item(merged)


def test_a_tooltip_with_no_weapon_fields_keeps_the_wiki_weapon_and_says_so():
    wiki = wiki_item(content=WIKI_BLADE)
    page = tooltip(["Slot: PRIMARY", "Class: ROG"])
    (merged,), report = eqlt_merge.merge_eqlegendstools([wiki], [page])
    assert merged["weapon"] == wiki["weapon"] and "weapon" in report["left_unknown"][0]["fields"]


def test_a_name_on_two_wiki_pages_is_a_build_error_that_names_the_item():
    one, two = wiki_item(pageid=1), wiki_item(pageid=2)
    with pytest.raises(ValueError, match=r"Checkmate.*w1.*w2"):
        eqlt_merge.merge_eqlegendstools([one, two], [CHECKMATE])


# ---- p7latent: what a tooltip that shows no weapon, an unreadable flags line or a warning-bearing skipped page means ---------------------------------------


def test_a_tooltip_that_states_a_non_weapon_type_and_shows_no_weapon_drops_the_wiki_weapon():
    wiki = wiki_item(content=WIKI_BLADE)  # (the wiki page wrongly presents the item as a weapon)
    assert wiki["weapon"] is not None
    page = tooltip(["Slot: PRIMARY", "Type: Shield", "Class: ROG"])
    (merged,), report = eqlt_merge.merge_eqlegendstools([wiki], [page])
    validate_item(merged)
    assert merged["item_type"] == "Shield" and merged["weapon"] is None
    assert "weapon" not in report["left_unknown"][0]["fields"]  # (the page said what the item is: nothing is unknown about the weapon)
    assert {"key": merged["key"], "name": merged["name"], "field": "weapon", "wiki": wiki["weapon"], "eqlt": None} in report["disagreements"]


def test_a_tooltip_that_states_a_weapon_type_or_no_type_and_shows_no_weapon_keeps_the_wiki_weapon_as_unknown():
    wiki = wiki_item(content=WIKI_BLADE)
    for lines in (["Slot: PRIMARY", "Type: 1H Piercing", "Class: ROG"], ["Slot: PRIMARY", "Type: Weapon", "Class: ROG"], ["Slot: PRIMARY", "Class: ROG"],
                  ["Slot: PRIMARY", "Type: Hand-to-Hand", "Class: ROG"], ["Slot: PRIMARY", "Type: Two-Handed Blunt", "Class: ROG"], ["Slot: PRIMARY", "Type: 2-H Slashing", "Class: ROG"], ["Slot: PRIMARY", "Type: Bows", "Class: ROG"]):
        (merged,), report = eqlt_merge.merge_eqlegendstools([wiki], [tooltip(lines)])
        assert merged["weapon"] == wiki["weapon"], lines
        assert "weapon" in report["left_unknown"][0]["fields"], lines


def test_a_flags_line_the_parser_cannot_read_keeps_the_wiki_flags_and_lists_flags_as_unknown():
    wiki = wiki_item(content=WIKI_CHECKMATE.replace("Attunable<br>", "Lore Equipped, Magic Item<br>"))
    assert {"lore", "magic"} <= set(wiki["flags"])
    for text in ("Sparkly Shiny", "???"):
        page = tooltip(["Slot: EAR", "AC: 6", "Class: WAR MNK ROG BER"], flags=text)
        (merged,), report = eqlt_merge.merge_eqlegendstools([wiki], [page])
        assert {"lore", "magic"} <= set(merged["flags"]), text
        assert "flags" in report["left_unknown"][0]["fields"], text


def test_a_flags_line_that_says_none_replaces_the_wiki_flags_but_keeps_the_banner_flags():
    wiki = wiki_item(content=WIKI_CHECKMATE.replace("Attunable<br>", "Lore Equipped, Magic Item<br>"))
    for text in ("None", "No flags"):
        page = tooltip(["Slot: EAR", "AC: 6", "Class: WAR MNK ROG BER"], flags=text)
        (merged,), report = eqlt_merge.merge_eqlegendstools([wiki], [page])
        assert merged["flags"] == ["wiki_banner_revamped"], text
        assert not report["left_unknown"] or "flags" not in report["left_unknown"][0]["fields"], text


def test_a_skipped_new_page_still_reports_its_parse_warnings():
    page = tooltip(["Slot: EAR", "AC: 6", "Zorp: 99 blah"], name="Warned Ring", slug="warned-ring")  # (no Class line: skipped; an unreadable line: a warning)
    assert eqlt_merge.build_item(page)["parse_warnings"]
    items, report = eqlt_merge.merge_eqlegendstools([], [page])
    assert items == [] and report["skipped"] == [{"slug": "warned-ring", "name": "Warned Ring", "missing": ["class"]}]
    assert [w["slug"] for w in report["parse_warnings"]] == ["warned-ring"] and report["parse_warnings"][0]["warnings"]
