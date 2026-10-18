"""Tests for the evidence ladder: zone keys, the hand lists, the alias table and classify().

The ladder is tested on synthetic items and a synthetic context (invented zones, ids and names:
Zorblax and friends), plus the committed hand lists and alias table against the committed client
zone extract and the recorded wiki pages.
"""

import copy
import json
import re
from collections import Counter
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from trioforge.data import evidence as ladder_module
from trioforge.data.evidence import (
    LEVELS,
    NOT_HIDING_CODES,
    NOTE_CODES,
    SEALS,
    ZONE_CLOSED_CODES,
    Context,
    EvidenceError,
    HandLists,
    Quest,
    QuestTable,
    Report,
    classify,
    container_key,
    era_key,
    load_aliases,
    load_hand_lists,
    normalize_era,
    title_key,
    zkey,
)
from trioforge.data.normalize import normalize
from trioforge.sources.eqlwiki import fixture_slug, page_records
from trioforge.sources.itempage import ParsedPage, parse_page

REPO = Path(__file__).resolve().parents[2]
RULES = REPO / "rules"
CLIENT = REPO / "derived" / "client"

ITEM_FIXTURES = [
    "Engineer's Ring",
    "Girdle of Faith",
    "Cloak of Flames",
    "Shield of the Stalwart Seas",
    "Bladestopper",
    "Earthshaker",
    "Wu's Fist of Mastery",
    "Torrid Corruptor",
    "Baton of the Sky",
    "Talisman of Kejaar Kerrath",
    "Skinner's Belt",
    "Imbued Granite Spaulders",
    "Darkwar Mask",
    "Rusty Dagger",
    "Bone Chips",
    "Backpack",
    "Mask of Deception",
    "Dwarven Chain Tunic",
    "Symbol of Marr",
    "Ethereal Mist Chestplate",
]

SOURCE = [{"kind": "url", "ref": "https://example.invalid/patch-notes"}]
PRIVATE = [{"kind": "private-measured", "ref": "maintainer's private observation"}]


def hand_data(**overrides):
    data = {
        "version": "2026-10-14",
        "removed": [{"title": "Mask of Zorblax", "seal": "developer", "source": SOURCE, "date": "2026-05-22"}],
        "research_removals": [{"title": "Wind Zorblax Helm", "seal": "measured", "source": PRIVATE, "date": "2026-10-14"}],
        "unreleased_zones": [
            {"names": ["Rujarkian Hills"], "ids": [3], "seal": "developer", "source": SOURCE, "date": "2026-09-17"}
        ],
        "exists_unflagged_zones": [
            {"names": ["The Arena"], "ids": [77], "seal": "developer", "source": SOURCE, "date": "2026-06-23"},
            {"names": ["Tutorial", "Tutorial Zone"], "ids": [], "seal": "developer", "source": SOURCE, "date": "2026-07-14"},
        ],
        "eql_only_zones": [99, 3],
        "cultural_containers": ["Oggok Forge", "Teir`Dal Forge"],
        "in_era_tags": ["Classic Era", "Temple Era"],
        "out_of_era_tags": ["Kunark Era", "Velious Era"],
    }
    data.update(overrides)
    return data


# Client zone ids of the synthetic world: 1 Zorblax Hollow, 2 Plane of Hate (both flagged), 3 Rujarkian Hills
# (flagged, not released, EQL-only), 99 Lake Blarg (flagged, EQL-only), 77 The Arena and 500 Kael Drakkal
# (not flagged; the Arena exists), 501 Quuxen Hills (not flagged).
ALIASES = {
    "zorblax hollow": [1],
    "plane of hate": [2],
    "rujarkian hills": [3],
    "lake blarg": [99],
    "arena": [77],
    "kael drakkal": [500],
    "quuxen hills": [501],
    "split zone": [500, 2],
}
FLAGGED = {1, 2, 3, 99}


def quest(title, zone, era="Classic Era", giver="Old Zorb", rewards=(), wants=()):
    return Quest(title=title, giver=giver, zone=zone, era=era, rewards=tuple(rewards), wants=tuple(wants))


QUESTS = [
    quest("Zorblax Quest", "Zorblax Hollow"),
    quest("Kunark Quest", "Zorblax Hollow", era="Kunark Era"),
    quest("Far Quest", "Kael Drakkal"),
    quest("Arena Quest", "The Arena", era=None),
    quest("Lost Quest", "Blarg Marsh"),
    quest("Nowhere Quest", None),
    quest("Reward Quest", "Zorblax Hollow", rewards=["Zorblax Blade"]),
    quest("Handin Quest", "Zorblax Hollow", wants=["Zorblax Token"]),
]


def ctx(**overrides):
    base = dict(
        flagged=FLAGGED,
        aliases=ALIASES,
        hand=HandLists.from_data(hand_data()),
        quests=QuestTable(QUESTS),
    )
    base.update(overrides)
    return Context(**base)


def make_item(
    key="w1",
    name="Zorblax Ring",
    *,
    drops=(),
    sold_by=(),
    quests=(),
    crafted=(),
    era_tags=(),
    flags=(),
    deity=None,
    title=None,
):
    return {
        "key": key,
        "name": name,
        "wiki": {"pageid": int(key[1:]), "revid": 1, "title": title or name},
        "slots": ["FINGER"],
        "classes": ["ALL"],
        "races": ["ALL"],
        "deity": deity,
        "flags": list(flags),
        "stats": {"AC": 1},
        "sv": {},
        "sources": {
            "drops": [{"zone": zone, "npcs": list(npcs)} for zone, npcs in drops],
            "sold_by": [{"zone": zone, "npc": npc} for zone, npc in sold_by],
            "quests": list(quests),
            "crafted": [{"container": c, "ingredients": list(i)} for c, i in crafted],
        },
        "era_tags": list(era_tags),
    }


def codes(result):
    return [reason["code"] for reason in result["reasons"]]


def verdict(item, context=None, report=None):
    result = classify(item, context or ctx(), report)
    return result["level"], codes(result)


# ---- the shared normalizations -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Plane of Hate", "plane of hate"),
        ("  The   Plane_of_Hate ", "plane of hate"),
        ("THE PLANE OF HATE", "plane of hate"),
        ("Chardok (Post-Revamp)", "chardok"),
        ("The Hole (Paineel)", "hole"),
        ("Kurn's Tower", "kurn's tower"),
        ("Ｐlane of Ｈate", "plane of hate"),  # NFKC: full-width letters
        ("Plane of Hate", "plane of hate"),  # NFKC: no-break spaces
        ("Kael Drakkel (2)", "kael drakkel"),
        ("The", "the"),
        ("(Raid)", "(raid)"),  # never reduced to nothing
        ("The (Raid)", "(raid)"),
        ("", ""),
    ],
)
def test_zkey(raw, expected):
    assert zkey(raw) == expected


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=60))
def test_zkey_is_idempotent_and_tidy(text):
    once = zkey(text)
    assert zkey(once) == once
    assert once == once.strip() and "  " not in once
    assert title_key(title_key(text)) == title_key(text)


def test_title_key_keeps_the_parenthetical_that_names_the_page():
    assert title_key("Obsidian Shard (Sky)") == "obsidian shard (sky)"
    assert title_key("Obsidian Shard (Sky)") != title_key("Obsidian Shard")
    assert title_key("  The Mask_of  Zorblax ") == "mask of zorblax"
    assert zkey("Obsidian Shard (Sky)", keep_parenthetical=True) == title_key("Obsidian Shard (Sky)")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Kunark Era", "Kunark Era"),
        ("kunark era", "Kunark Era"),
        ("FearHateRevamp Era", "Fearhaterevamp Era"),
        ("  Chardok   Revamp ERA ", "Chardok Revamp Era"),
    ],
)
def test_normalize_era_gives_the_form_the_page_parser_gives(raw, expected):
    assert normalize_era(raw) == expected
    assert era_key(raw) == era_key(expected)


def test_container_key_ignores_case_quote_marks_and_punctuation():
    keys = {container_key(n) for n in ("Teir`Dal Forge", "Teir`dal Forge", "TEIR'DAL FORGE", "Teir’Dal  Forge", "Teir-Dal Forge")}
    assert keys == {"teirdal forge", "teir dal forge"}
    assert container_key("Teir`Dal Forge") == container_key("Teir’dal forge")
    assert container_key("Oggok Forge") != container_key("Forge")


# ---- the hand lists ------------------------------------------------------------------------------


def test_hand_lists_from_valid_data():
    hand = HandLists.from_data(hand_data())
    assert set(hand.removed) == {title_key("Mask of Zorblax")}
    assert set(hand.research_removals) == {title_key("Wind Zorblax Helm")}
    assert hand.unreleased_ids == {3} and hand.unreleased_names == {"rujarkian hills"}
    assert hand.exists_unflagged_ids == {77}
    assert hand.exists_unflagged_names == {"arena", "tutorial", "tutorial zone"}  # the shared zone key
    assert hand.eql_only_ids == {99, 3}
    assert hand.cultural_containers == {container_key("Oggok Forge"), container_key("Teir`Dal Forge")}
    assert hand.in_era == {era_key("Classic Era"), era_key("Temple Era")}
    assert hand.out_of_era == {era_key("Kunark Era"), era_key("Velious Era")}


def problems_of(data):
    with pytest.raises(EvidenceError) as caught:
        HandLists.from_data(data)
    return caught.value.problems


@pytest.mark.parametrize(
    ("edit", "mention"),
    [
        (lambda d: d["removed"].append(dict(d["removed"][0])), "twice"),
        (lambda d: d["removed"][0].update(seal="rumour"), "seal"),
        (lambda d: d["removed"][0].update(date="2026-13-40"), "date"),
        (lambda d: d["removed"][0].update(title="   "), "title"),
        (lambda d: d["removed"][0].update(source=[]), "source"),
        (lambda d: d["removed"][0].update(source=[{"kind": "private-measured", "ref": "I saw it on 2026-08-20"}]), "source"),
        (lambda d: d["removed"][0].update(source=[{"kind": "url", "ref": "http://example.invalid/x"}]), "source"),
        (lambda d: d["removed"][0].update(extra=1), "extra"),
        (lambda d: d.pop("removed"), "removed"),
        (lambda d: d.update(removed={"title": "x"}), "removed"),
        (lambda d: d.update(surprise=[]), "surprise"),
        (lambda d: d["unreleased_zones"][0].update(names=[], ids=[]), "unreleased_zones"),
        (lambda d: d["unreleased_zones"][0].update(ids=[True]), "ids"),
        (lambda d: d["unreleased_zones"][0].update(ids=[-1]), "ids"),
        (lambda d: d.update(eql_only_zones=[99, "100"]), "eql_only_zones"),
        (lambda d: d.update(eql_only_zones=[99, 99]), "eql_only_zones"),
        (lambda d: d.update(in_era_tags=["Classic"]), "in_era_tags"),
        (lambda d: d.update(in_era_tags=["Classic Eras"]), "in_era_tags"),
        (lambda d: d.update(out_of_era_tags=[" Era"]), "out_of_era_tags"),
        (lambda d: d.update(in_era_tags=["Classic Era"], out_of_era_tags=["classic ERA"]), "both"),
        (lambda d: d.update(out_of_era_tags=["Classic Era"]), "both"),
        (lambda d: d.update(cultural_containers=["Oggok Forge", "OGGOK FORGE"]), "cultural_containers"),
        (lambda d: d.update(cultural_containers=[""]), "cultural_containers"),
        (lambda d: d.update(version="soon"), "version"),
    ],
)
def test_bad_hand_lists_are_refused_with_the_problem_named(edit, mention):
    data = copy.deepcopy(hand_data())
    edit(data)
    assert any(mention in problem for problem in problems_of(data)), (mention, problems_of(data))


def test_every_problem_is_listed_not_just_the_first():
    data = hand_data(version="soon", in_era_tags=["Classic"])
    data["removed"][0]["seal"] = "rumour"
    assert len(problems_of(data)) >= 3


def test_duplicate_json_keys_in_a_rules_file_are_refused(tmp_path):
    path = tmp_path / "hand-lists.json"
    path.write_text('{"version": "2026-10-14", "version": "2026-10-15"}', encoding="utf-8")
    with pytest.raises(EvidenceError):
        load_hand_lists(path)
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(EvidenceError):
        load_hand_lists(path)


# ---- the committed hand lists ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_hand():
    return load_hand_lists(RULES / "hand-lists.json")


def real_data(name):
    return json.loads((RULES / name).read_text(encoding="utf-8"))


def test_the_committed_removed_list_is_the_patch_removals_that_have_a_page_with_a_source_and_a_date():
    data = real_data("hand-lists.json")
    titles = [entry["title"] for entry in data["removed"]]
    # "Torc of Veeshan" is not here, no page of the cached pull has that title (see the note in the file)
    assert titles == ["Mask of Deception", "Obsidian Shard (Sky)", "Kedge Backbone"]
    for entry in data["removed"]:
        assert entry["seal"] == "developer" and entry["source"] and entry["date"].startswith("2026-")


def test_the_committed_research_removals_are_wind_etched_armor_and_the_pre_upgrade_sky_rewards():
    titles = {entry["title"] for entry in real_data("hand-lists.json")["research_removals"]}
    assert titles == {
        "Wind Etched Boots of Ro",
        "Wind Etched Bracers of Ro",
        "Wind Etched Gauntlets of Ro",
        "Wind Etched Helm of Ro",
        "Agilmente's Flute of Flight",
        "Sphinx-Hide Mantle",
        "Songweaver's Mantle",
        "Mask of the Songbird",
        "Glowing Pauldrons",
    }


def test_research_removals_cite_only_the_fixed_private_label_and_no_stats():
    text = json.dumps(real_data("hand-lists.json")["research_removals"])
    assert text.count("maintainer's private observation") == 9
    for word in ("slug", "stats", "log", "AC", "STR", "confirmed"):
        assert word not in text


def test_the_committed_zone_lists_and_eql_only_ids():
    data = real_data("hand-lists.json")
    assert data["eql_only_zones"] == [99, 900, 901]
    assert [z["names"] for z in data["unreleased_zones"]] == [["Rujarkian Hills"]]
    assert data["unreleased_zones"][0]["ids"] == [901]
    names = [name for z in data["exists_unflagged_zones"] for name in z["names"]]
    assert "The Arena" in names and "Tutorial" in names


def test_the_committed_container_and_era_lists(real_hand):
    data = real_data("hand-lists.json")
    assert len(data["cultural_containers"]) == 19 == len(real_hand.cultural_containers)  # 14, and 5 seen on recipe pages later
    assert container_key("Teir`dal Forge") in real_hand.cultural_containers  # a spelling the wiki uses
    assert container_key("Forge") not in real_hand.cultural_containers
    assert data["in_era_tags"] == [
        "Classic Era",
        "Fear Era",
        "Hate Era",
        "Paineel Era",
        "Sky Era",
        "Temple Era",
    ]
    assert data["out_of_era_tags"] == [
        "Chardok Era",
        "Chardok Revamp Era",
        "Epicquests Era",
        "Epics Era",
        "Fearhaterevamp Era",
        "Kunark Era",
        "Luclin Era",
        "Velious Era",
    ]
    assert not real_hand.in_era & real_hand.out_of_era


def test_the_committed_hand_lists_name_no_client_binary_and_no_character():
    text = (RULES / "hand-lists.json").read_text(encoding="utf-8")
    for word in ("eq" + "game", ".exe", "0x"):  # written in pieces: the privacy scanner flags the whole word
        assert word not in text


# ---- the shield lists -------------------------------------------------------------------------------------

JUDGMENT = [{"kind": "public-text", "ref": "TrioForge judgment"}]


def shield_entry(key="w9001", name="Zorblax Guard", **changes):
    entry = {
        "key": key,
        "name": name,
        "note": "Off-hand armor with armor class; its icon is shared with items named shield.",
        "seal": "model",
        "source": JUDGMENT,
        "date": "2026-10-14",
    }
    entry.update(changes)
    return entry


def test_hand_lists_without_the_shield_sections_still_load():
    hand = HandLists.from_data(hand_data())
    assert dict(hand.shields) == {} and dict(hand.not_shields) == {}


def test_the_shield_sections_are_read_by_item_key():
    data = hand_data(
        shields=[shield_entry("w1", "Zorblax Guard"), shield_entry("w2", "Quuxen Guard")],
        not_shields=[shield_entry("w3", "Zorblax Webshield")],
    )
    hand = HandLists.from_data(data)
    assert list(hand.shields) == ["w1", "w2"] and list(hand.not_shields) == ["w3"]
    assert hand.shields["w2"]["name"] == "Quuxen Guard" and hand.not_shields["w3"]["seal"] == "model"
    assert dict(HandLists.from_data(hand_data(shields=[], not_shields=[])).shields) == {}


@pytest.mark.parametrize("section", ["shields", "not_shields"])
@pytest.mark.parametrize(
    ("edit", "mention"),
    [
        (lambda e: e.update(key="x1"), "key"),
        (lambda e: e.update(key="W1"), "key"),
        (lambda e: e.update(key="w1 "), "key"),
        (lambda e: e.update(key=1), "key"),
        (lambda e: e.pop("key"), "key"),
        (lambda e: e.update(name="  "), "name"),
        (lambda e: e.pop("name"), "name"),
        (lambda e: e.update(note=""), "note"),
        (lambda e: e.pop("note"), "note"),
        (lambda e: e.update(seal="judgment"), "seal"),  # the seals are the five of the rules file
        (lambda e: e.update(date="2026-02-30"), "date"),
        (lambda e: e.update(source=[]), "source"),
        (lambda e: e.update(source=[{"kind": "url", "ref": "http://example.invalid/x"}]), "source"),
        (lambda e: e.update(extra=1), "extra"),
    ],
)
def test_a_bad_shield_list_entry_is_refused_with_the_problem_named(section, edit, mention):
    data = hand_data(**{section: [shield_entry("w1")]})
    edit(data[section][0])
    found = problems_of(data)
    assert any(problem.startswith(f"{section}[0]") and mention in problem for problem in found), found


@pytest.mark.parametrize("section", ["shields", "not_shields"])
@pytest.mark.parametrize("value", [{}, "w1", None, ["w1"], [["w1"]], 5])
def test_a_shield_section_must_be_a_list_of_objects(section, value):
    assert any(problem.startswith(section) for problem in problems_of(hand_data(**{section: value})))


def test_a_key_listed_twice_in_a_shield_section_is_refused():
    data = hand_data(shields=[shield_entry("w1"), shield_entry("w1", "Quuxen Guard")])
    assert any("twice" in problem and problem.startswith("shields[1]") for problem in problems_of(data))


def test_a_key_in_both_shield_sections_is_refused():
    data = hand_data(shields=[shield_entry("w1")], not_shields=[shield_entry("w1", "Zorblax Webshield")])
    assert any("both" in problem and "w1" in problem for problem in problems_of(data))


def test_every_problem_in_the_shield_sections_is_listed():
    data = hand_data(shields=[shield_entry("x1", seal="judgment")], not_shields=[shield_entry("w2", note="")])
    assert len(problems_of(data)) >= 3


SHIELDS = {  # key -> (name, the icon the note must give as evidence)
    "w52912": ("Life's Guard", 805),
    "w34708": ("Marr's Promise", 805),
    "w549": ("Insignia Protector", 805),
    "w35441": ("Bladestopper", 606),
    "w43872": ("Krup Warrior Guard", 542),
    "w16531": ("Guard of the Marines", 676),
    "w16954": ("Guard of Ik", 676),
    "w34849": ("Devlas Ilkvel", 676),
    "w58561": ("Nisch Mas Ilkvel", 676),
}
NOT_SHIELDS = {  # key -> (name, icon, weight in stone): held items, all TINY like the crystals and orbs
    "w33508": ("Cryosilk Webshield", 973, 0.2),
    "w35255": ("Crystal Webshield", 973, 0.2),
    "w16938": ("Shield of the Devout", 973, 0.5),
}


def test_the_committed_shield_lists_hold_the_nine_shields_and_the_three_held_items(real_hand):
    assert {key: entry["name"] for key, entry in real_hand.shields.items()} == {k: v[0] for k, v in SHIELDS.items()}
    assert {key: entry["name"] for key, entry in real_hand.not_shields.items()} == {k: v[0] for k, v in NOT_SHIELDS.items()}


def test_every_committed_shield_entry_is_a_judgment_with_a_note_that_gives_the_icon_as_evidence(real_hand):
    for section, expected in ((real_hand.shields, SHIELDS), (real_hand.not_shields, NOT_SHIELDS)):
        assert set(section) == set(expected)
        for key, entry in section.items():
            assert entry["seal"] == "model" and entry["source"] == JUDGMENT and entry["date"] == "2026-10-14", key
            assert f"icon {expected[key][1]}" in entry["note"] and "lucy_img_id" in entry["note"], key


@pytest.mark.skipif(not (REPO / "derived" / "catalog.json").is_file(), reason="derived/catalog.json is not built")
def test_the_committed_shield_entries_name_real_items_with_the_stated_properties(real_hand):
    document = json.loads((REPO / "derived" / "catalog.json").read_text(encoding="utf-8"))
    items = {item["key"]: item for item in document["items"]}
    name_rule = re.compile(r"shield|buckler|aegis|bulwark|targe", re.IGNORECASE)  # written out: not the builder's constant
    for key, (name, icon) in SHIELDS.items():
        item = items[key]
        assert item["name"] == name and item["lucy_img_id"] == icon
        assert item["slots"] == ["SECONDARY"] and item["weapon"] is None and item["stats"]["AC"] > 0, name
        assert not name_rule.search(name), name  # the list holds what the name rule cannot catch
    for key, (name, icon, weight) in NOT_SHIELDS.items():
        item = items[key]
        assert item["name"] == name and item["lucy_img_id"] == icon and item["weight"] == weight, name
        assert item["size"] == "TINY" and item["slots"] == ["SECONDARY"] and name_rule.search(name), name  # the name rule would call it a shield


# ---- the alias table -------------------------------------------------------------------------------


def alias_data(**aliases):
    return {"version": "2026-10-14", "aliases": aliases}


def test_aliases_load_to_tuples_of_ids():
    assert load_aliases(alias_data(**{"plane of hate": [76], "commonlands": [21, 22]})) == {
        "plane of hate": (76,),
        "commonlands": (21, 22),
    }


@pytest.mark.parametrize(
    ("aliases", "mention"),
    [
        ({"Plane of Hate": [76]}, "normalized"),
        ({"the plane of hate": [76]}, "normalized"),
        ({"plane of hate": []}, "ids"),
        ({"plane of hate": "76"}, "ids"),
        ({"plane of hate": [76, 76]}, "ids"),
        ({"plane of hate": [True]}, "ids"),
        ({"plane of hate": [-5]}, "ids"),
        ({"": [1]}, "name"),
    ],
)
def test_bad_aliases_are_refused(aliases, mention):
    with pytest.raises(EvidenceError) as caught:
        load_aliases({"version": "2026-10-14", "aliases": aliases})
    assert any(mention in problem for problem in caught.value.problems), caught.value.problems


def test_an_alias_to_an_id_the_client_does_not_have_is_refused():
    with pytest.raises(EvidenceError) as caught:
        load_aliases(alias_data(**{"plane of hate": [76, 9999]}), zone_ids={76})
    assert any("9999" in problem for problem in caught.value.problems)


def test_an_alias_file_without_aliases_is_refused():
    with pytest.raises(EvidenceError):
        load_aliases({"version": "2026-10-14"})
    with pytest.raises(EvidenceError):
        load_aliases([])


@pytest.fixture(scope="module")
def client_zones():
    data = json.loads((CLIENT / "zones.json").read_text(encoding="utf-8"))
    return {zone["id"]: zone for zone in data["zones"]}


@pytest.fixture(scope="module")
def real_aliases(client_zones):
    return load_aliases(RULES / "zone-aliases.json", zone_ids=set(client_zones))


def test_every_committed_alias_key_is_in_the_shared_form_and_points_at_a_real_client_zone(real_aliases, client_zones):
    assert len(real_aliases) > 150
    for key, ids in real_aliases.items():
        assert zkey(key) == key, key
        assert ids and all(i in client_zones for i in ids), key


@pytest.mark.parametrize(
    ("wiki_name", "ids"),
    [
        ("Plane of Hate", (76,)),
        ("The Plane of Hate", (76,)),
        ("The Hole", (39,)),
        ("Lower Guk", (66,)),
        ("Nagafen's Lair", (32,)),
        ("Plane of Sky", (71,)),
        ("Plane of Fear", (72,)),
        ("Najena", (44,)),
        ("Qeynos Hills", (4,)),
        ("Rujarkian Hills", (901,)),
        ("The Arena", (77,)),
        ("Kael Drakkel", (113,)),
        ("Kael Drakkal", (113,)),
        ("East Cabilis", (106,)),
        ("Chardok (Post-Revamp)", (103,)),
    ],
)
def test_wiki_zone_names_map_to_the_expected_client_zones(real_aliases, wiki_name, ids):
    assert real_aliases[zkey(wiki_name)] == ids


def test_the_zone_names_on_the_recorded_pages_are_mapped_or_known_to_be_junk(real_aliases):
    names = set()
    for title in ITEM_FIXTURES:
        path = REPO / "fixtures" / "wiki" / f"{fixture_slug(title)}.json"
        (record,) = page_records(json.loads(path.read_text(encoding="utf-8")))
        parsed = parse_page(record)
        if isinstance(parsed, ParsedPage):
            names |= {drop["zone"] for drop in parsed.drops if drop["zone"]}
            names |= {sold["zone"] for sold in parsed.sold_by if sold["zone"]}
    unmapped = {name for name in names if zkey(name) not in real_aliases}
    assert unmapped == {"Various Zones"}
    assert len(names) > 30


def test_the_flagged_zones_among_the_fixture_names_are_the_ones_the_client_flags(real_aliases, client_zones):
    live = {"Plane of Hate", "Nagafen's Lair", "The Hole", "Lower Guk", "Plane of Sky", "Plane of Fear", "Najena"}
    dead = {"Kael Drakkel", "Kael Drakkal", "East Cabilis", "Rujarkian Hills", "The Arena"}
    for name in live:
        assert any(client_zones[i]["flagged"] for i in real_aliases[zkey(name)]), name
    for name in dead - {"Rujarkian Hills"}:
        assert not any(client_zones[i]["flagged"] for i in real_aliases[zkey(name)]), name
    assert client_zones[901]["flagged"]  # flagged, which is why the hand list says it is not released


def test_committed_hand_list_ids_exist_in_the_client_extract(real_hand, client_zones):
    for zone_id in real_hand.unreleased_ids | real_hand.exists_unflagged_ids | real_hand.eql_only_ids:
        assert zone_id in client_zones, zone_id
    assert real_hand.exists_unflagged_ids <= {i for i, z in client_zones.items() if not z["flagged"]}


# ---- the quest table -------------------------------------------------------------------------------


def test_quests_are_found_by_title_wiki_title_and_reward_and_wants_are_collected():
    table = QuestTable(
        [
            Quest("Zorblax Quest", "Old Zorb", "Zorblax Hollow", "Classic Era", ("Zorblax Blade",), ("Zorblax Ring",), "Zorblax_Quest_Page"),
            Quest("Other Quest", None, None, None, ("Zorblax Blade",), (), None),
        ]
    )
    assert table.by_title["zorblax quest"].giver == "Old Zorb"
    assert table.by_title["zorblax quest page"].title == "Zorblax Quest"
    assert [q.title for q in table.by_reward["zorblax blade"]] == ["Zorblax Quest", "Other Quest"]
    assert table.consumed == {"zorblax ring"}


def test_a_page_with_no_giver_zone_is_a_list_of_quests_and_takes_nothing():
    table = QuestTable(
        [quest("Real Quest", "Zorblax Hollow", wants=["Zorblax Token"]), quest("Popular Quests", None, wants=["Quuxen Token"])]
    )
    assert table.consumed == {"zorblax token"}


def test_the_first_quest_of_a_title_wins():
    table = QuestTable([quest("Same Quest", "Zorblax Hollow"), quest("same quest", "Kael Drakkal")])
    assert table.by_title["same quest"].zone == "Zorblax Hollow"


# ---- the ladder: the cases of the plan --------------------------------------------------------------


def test_a_drop_in_a_flagged_zone_with_a_classic_tag_is_wiki():
    item = make_item(drops=[("Plane of Hate", ["Innoruuk"])], era_tags=["Classic Era"])
    result = classify(item, ctx())
    assert result["level"] == "wiki"
    assert result["reasons"] == [
        {"code": "live-source:Plane of Hate", "seal": "client", "text": result["reasons"][0]["text"]}
    ]
    assert "Plane of Hate" in result["reasons"][0]["text"]


def test_a_drop_in_a_flagged_zone_with_a_kunark_tag_is_disputed():
    item = make_item(drops=[("Plane of Hate", ["Innoruuk"])], era_tags=["Kunark Era"])
    assert verdict(item) == ("disputed", ["live-source:Plane of Hate", "out-of-era-tag-live-zone"])
    reason = [r for r in classify(item, ctx())["reasons"] if r["code"] == "out-of-era-tag-live-zone"][0]
    assert reason["seal"] == "player"


def test_a_drop_only_in_an_unflagged_zone_is_hidden():
    item = make_item(drops=[("Kael Drakkal", ["a dragon"])], era_tags=["Classic Era"])
    result = classify(item, ctx())
    assert result["level"] == "hidden" and codes(result) == ["zones-not-in-eql"]
    assert result["reasons"][0]["seal"] == "client"


def test_the_same_item_seen_in_game_is_strict_with_a_conflict_note():
    item = make_item(drops=[("Kael Drakkal", ["a dragon"])])
    result = classify(item, ctx(seen_keys={"w1"}))
    assert result["level"] == "strict"
    assert codes(result) == ["conflict-note", "seen-in-game"]
    by_code = {r["code"]: r for r in result["reasons"]}
    assert by_code["seen-in-game"]["seal"] == "measured"
    assert "zones-not-in-eql" in by_code["conflict-note"]["text"]


def test_a_removed_name_is_hidden_even_if_seen_or_reported():
    item = make_item(name="Mask of Zorblax", drops=[("Plane of Hate", ["Innoruuk"])])
    result = classify(item, ctx(seen_keys={"w1"}, community_keys={"w1"}, catalog_keys_allowed={"w1"}))
    assert result["level"] == "hidden" and codes(result) == ["removed-by-patch"]
    assert result["reasons"][0]["seal"] == "developer"


def test_a_research_removal_is_hidden_even_if_seen():
    item = make_item(name="Wind Zorblax Helm", drops=[("Plane of Hate", ["Innoruuk"])])
    result = classify(item, ctx(seen_keys={"w1"}))
    assert result["level"] == "hidden" and codes(result) == ["removed-by-research"]
    assert result["reasons"][0]["seal"] == "measured"
    assert "maintainer's private observation" in result["reasons"][0]["text"]


def test_crafted_only_in_a_cultural_container_is_hidden():
    item = make_item(crafted=[("Oggok Forge", ["Iron Bar"])])
    result = classify(item, ctx())
    assert result["level"] == "hidden" and codes(result) == ["cultural-container"]
    assert result["reasons"][0]["seal"] == "player"


def test_crafted_in_a_forge_without_an_out_of_era_ingredient_is_wiki():
    item = make_item(crafted=[("Forge", ["Iron Bar", "Zorblax Pattern"])])
    result = classify(item, ctx())
    assert result["level"] == "wiki" and codes(result) == ["live-source:craft"]
    assert result["reasons"][0]["seal"] == "player"


def test_no_source_at_all_is_hidden():
    result = classify(make_item(), ctx())
    assert result["level"] == "hidden" and codes(result) == ["no-known-source"]
    assert result["reasons"][0]["seal"] == "model"


def test_a_community_report_makes_an_item_strict():
    result = classify(make_item(drops=[("Plane of Hate", ["Innoruuk"])]), ctx(community_keys={"w1"}))
    assert result["level"] == "strict" and codes(result) == ["community-report"]
    assert result["reasons"][0]["seal"] == "player"


# A report counts as strict evidence, but it never outranks the wiki's own word that an item is gone: a banner that says the page was deleted or the item
# does not exist, or the note that it was removed from the game. One report must not be able to put such an item into kits. Only the maintainer's own
# evidence (the seen flags, a listing the owner allows) still does, as it always did.
WIKI_MARKS = [
    ("wiki_banner_delete", "wiki-marked-not-in-eql"),
    ("wiki_banner_does_not_exist", "wiki-marked-not-in-eql"),
    ("wiki_banner_dne", "wiki-marked-not-in-eql"),
    ("removed_note", "wiki-marked-removed"),
]


@pytest.mark.parametrize(("flag", "mark"), WIKI_MARKS)
def test_an_item_the_wiki_marks_as_gone_stays_hidden_when_players_report_it_and_the_reasons_say_both(flag, mark):
    item = make_item(drops=[("Plane of Hate", ["Innoruuk"])], era_tags=["Classic Era"], flags=[flag])  # (a live source: the mark hides the item all the same)
    result = classify(item, ctx(community_keys={"w1"}))
    assert result["level"] == "hidden"
    assert codes(result) == ["community-report-outweighed", mark]
    by_code = {reason["code"]: reason for reason in result["reasons"]}
    assert by_code["community-report-outweighed"]["seal"] == "player" and 0 < len(by_code["community-report-outweighed"]["text"]) <= 200
    assert by_code[mark]["seal"] == "player"
    assert "conflict-note" not in by_code and "community-report" not in by_code  # (it is not kept as strict, so there is nothing to note)


def test_both_wiki_marks_and_a_report_give_both_marks_and_the_outweighed_report():
    item = make_item(flags=["removed_note", "wiki_banner_delete"])
    assert verdict(item, ctx(community_keys={"w1"})) == (
        "hidden",
        ["community-report-outweighed", "wiki-marked-not-in-eql", "wiki-marked-removed"],
    )


def test_a_report_for_another_item_changes_nothing_about_a_marked_item():
    assert verdict(make_item(flags=["wiki_banner_dne"]), ctx(community_keys={"w2"})) == ("hidden", ["wiki-marked-not-in-eql"])


def test_an_outweighed_report_leaves_the_notes_about_the_item_in_place():
    item = make_item(flags=["wiki_banner_delete", "wiki_banner_revamped", "temporary"], deity=["Innoruuk"])
    assert verdict(item, ctx(community_keys={"w1"})) == (
        "hidden",
        ["community-report-outweighed", "not-for-bis", "not-for-default-kits", "wiki-marked-not-in-eql", "wiki-marked-revamped"],
    )


@pytest.mark.parametrize("flags", [["wiki_banner_revamped"], ["temporary"], ["lore"], []])
def test_a_live_item_the_wiki_does_not_mark_as_gone_is_strict_with_a_report(flags):
    """A note on the page ("revamped", "temporary") is no mark: a report still counts as strict evidence."""
    item = make_item(drops=[("Plane of Hate", ["Innoruuk"])], flags=flags)
    result = classify(item, ctx(community_keys={"w1"}))
    assert result["level"] == "strict" and "community-report" in codes(result)
    assert "community-report-outweighed" not in codes(result) and "conflict-note" not in codes(result)


# An item-window screenshot shows that the item is in the game's data, not that anyone can get it. So besides the wiki's marks, the two reasons that say every zone the item
# comes from is closed outweigh a report on their own: ``zone-unreleased`` (the client flags the zone, the developers say it is not open) and ``zones-not-in-eql`` (the client
# does not flag it). The seen flags still beat them; a report still lifts the items that are hidden or disputed for any other reason (by design).
ZONE_CASES = [
    pytest.param("zone-unreleased", [("Rujarkian Hills", ["a warlord"])], "developer", id="every zone is unreleased"),
    pytest.param("zones-not-in-eql", [("Kael Drakkal", ["a dragon"])], "client", id="no zone is flagged by the client"),
    pytest.param("zones-not-in-eql", [("Rujarkian Hills", ["a"]), ("Kael Drakkal", ["b"])], "client", id="an unreleased zone and an unflagged one"),
    pytest.param("zones-not-in-eql", [("Rujarkian Hills", ["a"]), ("Blarg Marsh", ["b"])], "client", id="an unreleased zone and one that has no client id"),
]


@pytest.mark.parametrize(("code", "drops", "seal"), ZONE_CASES)
def test_an_item_whose_zones_are_all_closed_stays_hidden_when_players_report_it_and_the_reasons_say_both(code, drops, seal):
    item = make_item(drops=drops)
    assert verdict(item) == ("hidden", [code])  # (without the report)
    result = classify(item, ctx(community_keys={"w1"}))
    assert result["level"] == "hidden" and codes(result) == ["community-report-outweighed", code]
    by_code = {reason["code"]: reason for reason in result["reasons"]}
    assert by_code[code]["seal"] == seal  # the reason keeps the seal of whoever said the zone is closed
    assert by_code["community-report-outweighed"]["seal"] == "player" and "zone" in by_code["community-report-outweighed"]["text"].lower()
    assert 0 < len(by_code["community-report-outweighed"]["text"]) <= 200
    assert "conflict-note" not in by_code and "community-report" not in by_code


def test_the_text_of_an_outweighed_report_names_what_outweighs_it():
    marked = {r["code"]: r["text"] for r in classify(make_item(flags=["wiki_banner_dne"]), ctx(community_keys={"w1"}))["reasons"]}
    closed = {r["code"]: r["text"] for r in classify(make_item(drops=[("Kael Drakkal", ["a"])]), ctx(community_keys={"w1"}))["reasons"]}
    assert "mark" in marked["community-report-outweighed"] and "zone" not in marked["community-report-outweighed"]
    assert "zone" in closed["community-report-outweighed"] and "mark" not in closed["community-report-outweighed"]


def test_a_mark_and_a_closed_zone_together_give_the_marks_and_the_outweighed_report_as_before():
    item = make_item(drops=[("Kael Drakkal", ["a"])], flags=["wiki_banner_delete"])
    assert verdict(item, ctx(community_keys={"w1"})) == ("hidden", ["community-report-outweighed", "wiki-marked-not-in-eql"])  # (the marks are the only hidden reasons given)


@pytest.mark.parametrize(("code", "drops", "seal"), ZONE_CASES)
def test_the_maintainers_evidence_still_beats_a_closed_zone_and_a_report_beside_it_is_listed_as_before(code, drops, seal):
    item = make_item(drops=drops)
    seen = classify(item, ctx(seen_keys={"w1"}, community_keys={"w1"}))
    assert seen["level"] == "strict" and codes(seen) == ["community-report", "conflict-note", "seen-in-game"]
    assert codes(classify(item, ctx(seen_keys={"w1"}))) == ["conflict-note", "seen-in-game"]
    assert codes(classify(item, ctx(catalog_keys_allowed={"w1"}, community_keys={"w1"}))) == ["community-report", "conflict-note", "eql-catalog"]


LIFTED_BY_DESIGN = [
    pytest.param(make_item(crafted=[("Oggok Forge", [])]), "cultural-container", {}, id="made only in a cultural container"),
    pytest.param(make_item(), "no-known-source", {}, id="no known source"),
    pytest.param(make_item(era_tags=["Kunark Era"]), "out-of-era", {}, id="an era tag that is out of era and no source"),
    pytest.param(make_item(drops=[("Blarg Marsh", ["a frog"])]), "zones-unmapped", {}, id="every zone has no client id"),
    pytest.param(make_item(crafted=[("Forge", ["Velium Bar"])]), "out-of-era-ingredient", {"out_of_era_names": {"velium bar"}}, id="every recipe needs an ingredient that is out of era"),
    pytest.param(make_item(drops=[("Plane of Hate", ["a"])], era_tags=["Kunark Era"]), "out-of-era-tag-live-zone", {}, id="a live source and an era tag that is out of era (disputed)"),
    pytest.param(make_item(drops=[("Plane of Hate", ["a"])], era_tags=["Classic Era", "Kunark Era"]), "conflicting-era-tags", {}, id="a live source and both kinds of era tag (disputed)"),
]


@pytest.mark.parametrize(("item", "reason", "more"), LIFTED_BY_DESIGN)
def test_a_report_still_lifts_an_item_that_is_hidden_or_disputed_for_another_reason(item, reason, more):
    """By design: these are the wiki's signals (a name, a container, a tag, a gap), and a screenshot that shows the item in game answers them."""
    assert reason in codes(classify(item, ctx(**more)))
    result = classify(item, ctx(community_keys={"w1"}, **more))
    assert result["level"] == "strict" and "community-report" in codes(result)
    assert "community-report-outweighed" not in codes(result)


def test_the_text_of_the_ladder_names_the_reasons_that_outweigh_a_report_and_the_ones_it_lifts_and_the_code_does_the_same():
    """Step 5 of the module text says which reasons outweigh a report and which a report lifts, and a reader takes it at its word: the codes it names are the code's. The reasons
    it lifts are the ones ``LIFTED_BY_DESIGN`` shows lifting, none of them outweighs, and a zone with no client id beside a closed zone is the closed zone's reason."""
    text = " ".join((ladder_module.__doc__ or "").split())
    outweigh = re.search(r"``([a-z-]+)`` and ``([a-z-]+)`` outweigh a report from players on their own", text)
    assert outweigh is not None and {outweigh[1], outweigh[2]} == set(ZONE_CLOSED_CODES)
    lifts = re.search(r"a report lifts an item that is hidden or disputed for any other reason \(([^()]*)\)", text)
    assert lifts is not None
    named = set(re.findall(r"``([a-z-]+)``", lifts[1]))
    assert named == {param.values[1] for param in LIFTED_BY_DESIGN}, sorted(named)
    assert not named & set(ZONE_CLOSED_CODES)
    # (the sentence after it: an unmapped zone beside a closed one is the closed zone's reason, and it outweighs)
    mixed = classify(make_item(drops=[("Rujarkian Hills", ["a"]), ("Blarg Marsh", ["b"])]), ctx(community_keys={"w1"}))
    assert codes(mixed) == ["community-report-outweighed", "zones-not-in-eql"]
    assert re.search(r"zone with no client id beside a closed zone gives ``zones-not-in-eql``, which outweighs a report", text) is not None


def test_the_codes_that_outweigh_a_report_are_the_marks_the_closed_zones_and_the_removals():
    """The report of results names what outweighs a report when an item stops being strict because of it. Beside ``community-report-outweighed`` the ladder gives the marks of the
    wiki and the reasons that say every zone is closed (and nothing else that hides); a removal by a patch or by research hides the item first, and records no report at all."""
    from trioforge.data.evidence import REMOVAL_CODES, WIKI_MARK_CODES

    beside: set[str] = set()
    for flag, _ in WIKI_MARKS:
        beside |= set(codes(classify(make_item(flags=[flag]), ctx(community_keys={"w1"}))))
    for param in ZONE_CASES:
        beside |= set(codes(classify(make_item(drops=param.values[1]), ctx(community_keys={"w1"}))))
    assert beside - {"community-report-outweighed"} == set(WIKI_MARK_CODES) | set(ZONE_CLOSED_CODES)
    removed = [codes(classify(make_item(title=title), ctx(community_keys={"w1"}))) for title in ("Mask of Zorblax", "Wind Zorblax Helm")]
    assert removed == [["removed-by-patch"], ["removed-by-research"]]  # (hidden before anything else is looked at: no outweighed report is recorded)
    assert {code for found in removed for code in found} == set(REMOVAL_CODES)


def test_the_codes_that_are_no_reason_to_hide_an_item_are_the_notes_and_the_outweighed_report():
    """The summary of the catalog counts the items hidden for each reason: a note is none, and the record that a report was received and outweighed is none either (the mark or
    the closed zone beside it is the reason). The notes stay the notes the pages word (``NOTE_CODES``)."""
    assert NOT_HIDING_CODES == NOTE_CODES | {"community-report-outweighed"}
    assert NOTE_CODES == {"not-for-bis", "not-for-default-kits", "wiki-marked-revamped"}
    hidden_for = {code for flag in ("wiki_banner_delete", "removed_note") for code in codes(classify(make_item(flags=[flag]), ctx(community_keys={"w1"})))} - NOT_HIDING_CODES
    assert hidden_for == {"wiki-marked-not-in-eql", "wiki-marked-removed"}


def test_the_maintainers_own_evidence_still_beats_the_wikis_mark_and_a_report_beside_it_is_listed_as_before():
    item = make_item(drops=[("Plane of Hate", ["Innoruuk"])], flags=["wiki_banner_delete"])
    seen = classify(item, ctx(seen_keys={"w1"}, community_keys={"w1"}))
    assert seen["level"] == "strict" and codes(seen) == ["community-report", "conflict-note", "seen-in-game"]
    listed = classify(item, ctx(catalog_keys_allowed={"w1"}, community_keys={"w1"}))
    assert listed["level"] == "strict" and codes(listed) == ["community-report", "conflict-note", "eql-catalog"]
    alone = classify(item, ctx(seen_keys={"w1"}))
    assert alone["level"] == "strict" and codes(alone) == ["conflict-note", "seen-in-game"]


def test_a_listing_in_the_allowed_catalog_makes_an_item_strict():
    result = classify(make_item(), ctx(catalog_keys_allowed={"w1"}))
    assert result["level"] == "strict" and codes(result) == ["eql-catalog"]
    assert result["reasons"][0]["seal"] == "player"


def test_the_temporary_flag_adds_not_for_bis_and_keeps_the_level():
    item = make_item(flags=["temporary"], drops=[("Plane of Hate", ["Innoruuk"])])
    result = classify(item, ctx())
    assert result["level"] == "wiki" and "not-for-bis" in codes(result)
    assert {r["code"]: r["seal"] for r in result["reasons"]}["not-for-bis"] == "model"


def test_an_unmapped_zone_is_reported_and_is_no_live_source():
    report = Report()
    item = make_item(drops=[("Blarg Marsh", ["a frog"])])
    result = classify(item, ctx(), report)
    assert result["level"] == "hidden" and codes(result) == ["zones-unmapped"]
    assert report.unmapped_zones == Counter({"Blarg Marsh": 1})


# ---- the ladder: the cases of the addendum -----------------------------------------------------------


def test_every_drop_zone_unreleased_is_hidden_zone_unreleased():
    item = make_item(drops=[("Rujarkian Hills", ["a warlord"])])
    result = classify(item, ctx())
    assert result["level"] == "hidden" and codes(result) == ["zone-unreleased"]
    assert result["reasons"][0]["seal"] == "developer"


def test_an_unreleased_zone_is_found_by_name_even_without_an_alias():
    item = make_item(drops=[("The Rujarkian Hills", ["a warlord"])])
    result = classify(item, ctx())
    assert result["level"] == "hidden" and codes(result) == ["zone-unreleased"]


def test_a_zone_the_hand_list_names_only_by_client_id_is_unreleased_too():
    aliases = dict(ALIASES, **{"rujarkian marsh": [3]})  # another spelling of an unreleased zone's id
    assert verdict(make_item(drops=[("Rujarkian Marsh", [])]), ctx(aliases=aliases)) == ("hidden", ["zone-unreleased"])
    assert verdict(make_item(drops=[("Rujarkian Marsh", []), ("Plane of Hate", [])]), ctx(aliases=aliases))[0] == "wiki"


def test_every_drop_zone_unmapped_is_hidden_zones_unmapped_and_counted_once_per_item():
    report = Report()
    item = make_item(drops=[("Blarg Marsh", ["a"]), ("Blarg Marsh", ["b"]), ("Various Zones", ["c"])])
    result = classify(item, ctx(), report)
    assert result["level"] == "hidden" and codes(result) == ["zones-unmapped"]
    assert report.unmapped_zones == Counter({"Blarg Marsh": 1, "Various Zones": 1})
    assert result["reasons"][0]["seal"] == "model"


def test_a_mix_of_unmapped_and_unflagged_drop_zones_is_zones_not_in_eql():
    item = make_item(drops=[("Blarg Marsh", ["a"]), ("Kael Drakkal", ["b"]), ("Rujarkian Hills", ["c"])])
    assert verdict(item) == ("hidden", ["zones-not-in-eql"])


def test_an_out_of_era_tag_with_no_live_source_is_hidden_out_of_era():
    item = make_item(era_tags=["Kunark Era"], drops=[("Kael Drakkal", ["a dragon"])])
    result = classify(item, ctx())
    assert result["level"] == "hidden" and codes(result) == ["out-of-era", "zones-not-in-eql"]
    assert {r["code"]: r["seal"] for r in result["reasons"]}["out-of-era"] == "player"
    assert verdict(make_item(era_tags=["Velious Era"])) == ("hidden", ["out-of-era"])


def test_every_hidden_reason_has_a_test_above_and_the_codes_are_the_documented_ones():
    hidden = {
        "removed-by-patch",
        "removed-by-research",
        "zone-unreleased",
        "zones-unmapped",
        "zones-not-in-eql",
        "out-of-era",
        "cultural-container",
        "out-of-era-ingredient",
        "no-known-source",
        "wiki-marked-not-in-eql",
        "wiki-marked-removed",
    }
    seen = set()
    for item in (
        make_item(name="Mask of Zorblax"),
        make_item(name="Wind Zorblax Helm"),
        make_item(drops=[("Rujarkian Hills", [])]),
        make_item(drops=[("Blarg Marsh", [])]),
        make_item(drops=[("Kael Drakkal", [])]),
        make_item(era_tags=["Kunark Era"]),
        make_item(crafted=[("Oggok Forge", [])]),
        make_item(crafted=[("Forge", ["Velium Bar"])]),
        make_item(),
        make_item(flags=["wiki_banner_delete"]),
        make_item(flags=["removed_note"]),
    ):
        seen |= set(codes(classify(item, ctx(out_of_era_names={"velium bar"}))))
    assert seen == hidden


def test_a_drop_in_any_flagged_zone_gives_wiki_and_the_unflagged_zones_stay_in_the_sources():
    item = make_item(drops=[("Kael Drakkal", ["a dragon"]), ("Plane of Hate", ["Innoruuk"]), ("Quuxen Hills", ["a"])])
    before = copy.deepcopy(item)
    result = classify(item, ctx())
    assert result["level"] == "wiki" and codes(result) == ["live-source:Plane of Hate"]
    assert item == before  # classify never edits the item: its sources still list all three zones
    assert [d["zone"] for d in item["sources"]["drops"]] == ["Kael Drakkal", "Plane of Hate", "Quuxen Hills"]


def test_a_zone_with_one_live_id_and_one_dead_id_is_live():
    assert verdict(make_item(drops=[("Split Zone", [])])) == ("wiki", ["live-source:Split Zone"])


def test_every_live_drop_zone_gets_a_reason_sorted_by_name():
    item = make_item(drops=[("Zorblax Hollow", []), ("Plane of Hate", [])])
    assert verdict(item) == ("wiki", ["live-source:Plane of Hate", "live-source:Zorblax Hollow"])


def test_no_more_than_five_live_zone_reasons_are_written():
    aliases = dict(ALIASES, **{f"zone {n}": [1] for n in range(8)})
    item = make_item(drops=[(f"Zone {n}", []) for n in range(8)])
    level, found = verdict(item, ctx(aliases=aliases))
    assert level == "wiki" and found == [f"live-source:Zone {n}" for n in range(5)]


def test_the_eql_only_exemption_an_out_of_era_tag_does_not_dispute_a_drop_in_an_eql_only_zone():
    item = make_item(drops=[("Lake Blarg", ["a"])], era_tags=["Kunark Era"])
    assert verdict(item) == ("wiki", ["live-source:Lake Blarg"])


def test_the_eql_only_exemption_holds_when_other_drops_are_in_ordinary_live_zones_too():
    item = make_item(drops=[("Plane of Hate", ["a"]), ("Lake Blarg", ["b"])], era_tags=["Velious Era"])
    assert verdict(item) == ("wiki", ["live-source:Lake Blarg", "live-source:Plane of Hate"])


def test_the_eql_only_exemption_holds_for_conflicting_tags_too():
    item = make_item(drops=[("Plane of Hate", ["a"]), ("Lake Blarg", ["b"])], era_tags=["Classic Era", "Kunark Era"])
    assert verdict(item)[0] == "wiki"


def test_an_unreleased_eql_only_zone_still_exempts_the_era_tag():
    item = make_item(drops=[("Plane of Hate", ["a"]), ("Rujarkian Hills", ["b"])], era_tags=["Kunark Era"])
    assert verdict(item) == ("wiki", ["live-source:Plane of Hate"])


def test_without_an_eql_only_drop_an_out_of_era_tag_disputes_every_live_source():
    for item in (
        make_item(drops=[("Plane of Hate", ["a"]), ("Kael Drakkal", ["b"])], era_tags=["Velious Era"]),
        make_item(sold_by=[("Zorblax Hollow", "Vendor")], era_tags=["Kunark Era"]),
        make_item(crafted=[("Forge", [])], era_tags=["Kunark Era"]),
    ):
        assert verdict(item)[0] == "disputed"


def test_conflicting_era_tags_with_a_live_source_are_disputed_with_both_reasons():
    item = make_item(drops=[("Plane of Hate", ["a"])], era_tags=["Classic Era", "Kunark Era"])
    level, found = verdict(item)
    assert level == "disputed"
    assert found == ["conflicting-era-tags", "live-source:Plane of Hate", "out-of-era-tag-live-zone"]


def test_conflicting_era_tags_without_a_live_source_are_hidden_not_disputed():
    item = make_item(drops=[("Kael Drakkal", ["a"])], era_tags=["Classic Era", "Kunark Era"])
    assert verdict(item) == ("hidden", ["out-of-era", "zones-not-in-eql"])


def test_an_in_era_tag_alone_changes_nothing():
    plain = verdict(make_item(drops=[("Plane of Hate", ["a"])]))
    tagged = verdict(make_item(drops=[("Plane of Hate", ["a"])], era_tags=["Classic Era", "Temple Era"]))
    assert plain == tagged == ("wiki", ["live-source:Plane of Hate"])


def test_unknown_era_names_are_ignored_and_reported():
    report = Report()
    item = make_item(drops=[("Plane of Hate", ["a"])], era_tags=["Zorblaxian Era", "Unknown Era"])
    assert classify(item, ctx(), report)["level"] == "wiki"
    assert report.unknown_eras == Counter({"Zorblaxian Era": 1, "Unknown Era": 1})


def test_era_names_match_without_regard_to_case():
    item = make_item(drops=[("Plane of Hate", ["a"])], era_tags=["kunark era"])
    assert verdict(item)[0] == "disputed"


def test_the_order_of_the_era_tags_never_changes_the_answer():
    tags = ["Classic Era", "Kunark Era", "Zorblaxian Era", "Velious Era"]
    answers = set()
    for order in (tags, tags[::-1], tags[2:] + tags[:2]):
        item = make_item(drops=[("Plane of Hate", ["a"])], era_tags=order)
        answers.add(json.dumps(classify(item, ctx()), sort_keys=False))
    assert len(answers) == 1


def test_vendors_in_a_flagged_zone_are_a_live_source():
    item = make_item(sold_by=[("Zorblax Hollow", "Vendor One"), ("Kael Drakkal", "Vendor Two")])
    result = classify(item, ctx())
    assert result["level"] == "wiki" and codes(result) == ["live-source:vendor"]
    assert result["reasons"][0]["seal"] == "client"


def test_vendors_in_an_exists_unflagged_zone_are_a_live_source():
    item = make_item(sold_by=[("The Arena", "Vendor One")])
    result = classify(item, ctx())
    assert result["level"] == "wiki" and codes(result) == ["live-source:vendor"]
    assert result["reasons"][0]["seal"] == "developer"
    assert verdict(make_item(sold_by=[("Tutorial", "Vendor One")]))[0] == "wiki"  # by name: no client id is known


def test_vendors_with_no_zone_or_in_dead_or_unreleased_zones_are_no_live_source():
    for sold in ([("Kael Drakkal", "V")], [(None, "V")], [("Rujarkian Hills", "V")], [("Blarg Marsh", "V")]):
        assert verdict(make_item(sold_by=sold)) == ("hidden", ["no-known-source"])


def test_drops_in_an_exists_unflagged_zone_are_a_live_source():
    item = make_item(drops=[("The Arena", ["a gladiator"])])
    result = classify(item, ctx())
    assert result["level"] == "wiki" and codes(result) == ["live-source:The Arena"]
    assert result["reasons"][0]["seal"] == "developer"


def test_quest_givers_in_an_exists_unflagged_zone_are_a_live_source():
    result = classify(make_item(quests=["Arena Quest"]), ctx())
    assert result["level"] == "wiki" and codes(result) == ["live-source:quest"]


def test_a_quest_with_a_giver_in_a_flagged_zone_and_an_in_era_page_is_a_live_source():
    assert verdict(make_item(quests=["Zorblax Quest"])) == ("wiki", ["live-source:quest"])
    assert verdict(make_item(quests=["zorblax_quest"])) == ("wiki", ["live-source:quest"])  # the page title's spelling


def test_a_quest_on_an_out_of_era_page_is_no_live_source():
    assert verdict(make_item(quests=["Kunark Quest"])) == ("hidden", ["no-known-source"])


def test_a_quest_with_a_giver_in_a_dead_unmapped_or_unknown_zone_is_no_live_source():
    report = Report()
    for name in ("Far Quest", "Lost Quest", "Nowhere Quest", "No Such Quest"):
        assert verdict(make_item(quests=[name]), report=report) == ("hidden", ["no-known-source"])
    assert report.unmapped_zones == Counter({"Blarg Marsh": 1})


def test_a_quest_page_with_no_era_tag_is_not_out_of_era():
    assert verdict(make_item(quests=["Arena Quest"]))[0] == "wiki"  # era None


def test_an_item_that_a_quest_gives_as_a_reward_has_a_live_source_by_its_name():
    assert verdict(make_item(name="Zorblax Blade")) == ("wiki", ["live-source:quest"])
    assert verdict(make_item(name="Zorblax Blade"), ctx(ambiguous_names={title_key("Zorblax Blade")})) == (
        "hidden",
        ["no-known-source"],
    )


def test_crafting_needs_a_named_container_that_is_not_cultural():
    assert verdict(make_item(crafted=[("Forge", [])])) == ("wiki", ["live-source:craft"])
    assert verdict(make_item(crafted=[("Oggok Forge", []), ("Forge", ["Iron Bar"])])) == ("wiki", ["live-source:craft"])
    assert verdict(make_item(crafted=[(None, ["Iron Bar"])])) == ("hidden", ["no-known-source"])  # container unknown


def test_a_cultural_container_is_found_by_any_spelling_the_wiki_uses():
    for spelling in ("Oggok Forge", "oggok forge", "Teir`Dal Forge", "Teir`dal Forge", "Teir’Dal Forge"):
        assert verdict(make_item(crafted=[(spelling, [])])) == ("hidden", ["cultural-container"]), spelling


def test_a_recipe_with_an_out_of_era_ingredient_is_not_a_live_source():
    context = ctx(out_of_era_names={title_key("Velium Bar")})
    assert verdict(make_item(crafted=[("Forge", ["Iron Bar", "Velium Bar"])]), context) == (
        "hidden",
        ["out-of-era-ingredient"],
    )
    # another recipe without it is enough
    item = make_item(crafted=[("Forge", ["Velium Bar"]), ("Kiln", ["Clay"])])
    assert verdict(item, context) == ("wiki", ["live-source:craft"])


def test_cultural_and_out_of_era_recipes_together_give_both_hidden_reasons():
    context = ctx(out_of_era_names={"velium bar"})
    item = make_item(crafted=[("Oggok Forge", []), ("Forge", ["Velium Bar"])])
    assert verdict(item, context) == ("hidden", ["cultural-container", "out-of-era-ingredient"])


def test_removed_titles_are_matched_by_exact_page_title_after_normalization():
    for title in ("Mask of Zorblax", "mask of zorblax", "  Mask  of_Zorblax ", "MASK OF ZORBLAX"):
        item = make_item(name="Some Other Name", title=title, drops=[("Plane of Hate", ["a"])])
        assert verdict(item) == ("hidden", ["removed-by-patch"]), title


def test_removed_titles_are_never_matched_by_substring_or_by_name():
    for title in ("Mask of Zorblax II", "Greater Mask of Zorblax", "Mask of Zorblaxes", "Mask of", "Zorblax"):
        item = make_item(name=title, drops=[("Plane of Hate", ["a"])])
        assert verdict(item) == ("wiki", ["live-source:Plane of Hate"]), title
    # the name is not the page title: only the title counts
    item = make_item(name="Mask of Zorblax", title="Quuxen Mask", drops=[("Plane of Hate", ["a"])])
    assert verdict(item)[0] == "wiki"


def test_a_removed_title_with_a_parenthetical_does_not_remove_its_namesakes():
    data = hand_data(removed=[{"title": "Obsidian Shard (Sky)", "seal": "developer", "source": SOURCE, "date": "2026-05-29"}])
    context = ctx(hand=HandLists.from_data(data))
    drops = [("Plane of Hate", ["a"])]
    assert verdict(make_item(name="Obsidian Shard (Sky)", drops=drops), context)[0] == "hidden"
    assert verdict(make_item(name="Obsidian Shard", drops=drops), context)[0] == "wiki"
    assert verdict(make_item(name="Obsidian Shard (Fire)", drops=drops), context)[0] == "wiki"


def test_strict_evidence_with_a_clean_wiki_signal_has_no_conflict_note():
    result = classify(make_item(drops=[("Plane of Hate", ["a"])]), ctx(seen_keys={"w1"}))
    assert result["level"] == "strict" and codes(result) == ["seen-in-game"]


@pytest.mark.parametrize(
    "item",
    [
        make_item(drops=[("Plane of Hate", ["a"])], era_tags=["Kunark Era"]),
        make_item(drops=[("Kael Drakkal", ["a"])]),
        make_item(drops=[("Rujarkian Hills", ["a"])]),
        make_item(crafted=[("Oggok Forge", [])]),
    ],
)
def test_strict_evidence_that_the_signals_contradict_keeps_strict_and_adds_a_conflict_note(item):
    result = classify(item, ctx(seen_keys={"w1"}))
    assert result["level"] == "strict" and "conflict-note" in codes(result)


@pytest.mark.parametrize(
    "item",
    [make_item(), make_item(drops=[("Blarg Marsh", ["a"])])],
)
def test_strict_evidence_with_no_source_or_an_unmapped_zone_is_not_a_conflict(item):
    result = classify(item, ctx(seen_keys={"w1"}))
    assert result["level"] == "strict" and codes(result) == ["seen-in-game"]


def test_every_strict_source_is_listed_when_several_apply():
    result = classify(make_item(), ctx(seen_keys={"w1"}, community_keys={"w1"}, catalog_keys_allowed={"w1"}))
    assert result["level"] == "strict" and codes(result) == ["community-report", "eql-catalog", "seen-in-game"]


def test_the_default_context_has_no_strict_evidence_at_all():
    item = make_item(drops=[("Plane of Hate", ["a"])])
    assert classify(item, Context(flagged=FLAGGED, aliases=ALIASES))["level"] == "wiki"


def test_a_quest_item_consumed_on_hand_in_is_not_for_bis():
    result = classify(make_item(name="Zorblax Token", drops=[("Plane of Hate", ["a"])]), ctx())
    assert result["level"] == "wiki" and "not-for-bis" in codes(result)  # "Handin Quest" wants a Zorblax Token
    other = classify(make_item(name="Quuxen Ring", drops=[("Plane of Hate", ["a"])]), ctx())
    assert "not-for-bis" not in codes(other)
    ambiguous = classify(
        make_item(name="Zorblax Token", drops=[("Plane of Hate", ["a"])]), ctx(ambiguous_names={"zorblax token"})
    )
    assert "not-for-bis" not in codes(ambiguous)


def test_a_deity_locked_item_is_not_for_default_kits():
    item = make_item(drops=[("Plane of Hate", ["a"])], deity=["Innoruuk"])
    result = classify(item, ctx())
    assert result["level"] == "wiki"
    assert codes(result) == ["live-source:Plane of Hate", "not-for-default-kits"]
    assert {r["code"]: r["seal"] for r in result["reasons"]}["not-for-default-kits"] == "model"
    assert "not-for-default-kits" not in codes(classify(make_item(drops=[("Plane of Hate", ["a"])]), ctx()))


def test_exclusion_reasons_are_added_to_every_level():
    item = make_item(flags=["temporary"], deity=["Tunare"])
    for context in (ctx(), ctx(seen_keys={"w1"})):
        assert {"not-for-bis", "not-for-default-kits"} <= set(codes(classify(item, context)))


# ---- wiki banners, the removed note and items for nobody ---------------------------------------------


@pytest.mark.parametrize("flag", ["wiki_banner_delete", "wiki_banner_does_not_exist", "wiki_banner_dne"])
def test_a_page_that_says_it_is_deleted_or_does_not_exist_is_hidden_even_with_a_live_source(flag):
    item = make_item(drops=[("Plane of Hate", ["Innoruuk"])], era_tags=["Classic Era"], flags=[flag])
    result = classify(item, ctx())
    assert result["level"] == "hidden" and codes(result) == ["wiki-marked-not-in-eql"]
    assert result["reasons"][0]["seal"] == "player"
    assert 0 < len(result["reasons"][0]["text"]) <= 200


def test_the_banner_reason_is_the_only_hidden_reason_given():
    item = make_item(drops=[("Kael Drakkal", ["a dragon"])], era_tags=["Kunark Era"], flags=["wiki_banner_dne"])
    assert verdict(item) == ("hidden", ["wiki-marked-not-in-eql"])  # not zones-not-in-eql or out-of-era besides
    assert verdict(make_item(flags=["wiki_banner_delete"])) == ("hidden", ["wiki-marked-not-in-eql"])  # nor no-known-source


def test_several_deletion_banners_give_one_reason():
    item = make_item(flags=["wiki_banner_delete", "wiki_banner_dne", "wiki_banner_does_not_exist"])
    assert verdict(item) == ("hidden", ["wiki-marked-not-in-eql"])


def test_the_removed_note_hides_an_item_with_its_own_reason():
    item = make_item(drops=[("Plane of Hate", ["Innoruuk"])], flags=["removed_note"])
    result = classify(item, ctx())
    assert result["level"] == "hidden" and codes(result) == ["wiki-marked-removed"]
    assert result["reasons"][0]["seal"] == "player"
    both = make_item(flags=["removed_note", "wiki_banner_delete"])
    assert verdict(both) == ("hidden", ["wiki-marked-not-in-eql", "wiki-marked-removed"])


def test_a_revamped_banner_only_adds_a_note_and_changes_neither_level_nor_other_reasons():
    plain = make_item(drops=[("Plane of Hate", ["Innoruuk"])])
    revamped = make_item(drops=[("Plane of Hate", ["Innoruuk"])], flags=["wiki_banner_revamped"])
    assert verdict(plain) == ("wiki", ["live-source:Plane of Hate"])
    assert verdict(revamped) == ("wiki", ["live-source:Plane of Hate", "wiki-marked-revamped"])
    assert {r["code"]: r["seal"] for r in classify(revamped, ctx())["reasons"]}["wiki-marked-revamped"] == "player"
    assert verdict(make_item(flags=["wiki_banner_revamped"])) == ("hidden", ["no-known-source", "wiki-marked-revamped"])
    assert verdict(make_item(drops=[("Plane of Hate", [])], era_tags=["Kunark Era"], flags=["wiki_banner_revamped"]))[0] == "disputed"


def test_a_banner_does_not_beat_strict_evidence_which_gets_a_conflict_note():
    item = make_item(drops=[("Plane of Hate", ["Innoruuk"])], flags=["wiki_banner_delete"])
    result = classify(item, ctx(seen_keys={"w1"}))
    assert result["level"] == "strict" and codes(result) == ["conflict-note", "seen-in-game"]
    assert "wiki-marked-not-in-eql" in {r["code"]: r for r in result["reasons"]}["conflict-note"]["text"]
    removed = classify(make_item(flags=["removed_note"]), ctx(seen_keys={"w1"}))  # (the maintainer's evidence beats the note; a report does not: see the tests above)
    assert removed["level"] == "strict" and "wiki-marked-removed" in removed["reasons"][0]["text"] + removed["reasons"][1]["text"]


def test_a_patch_removal_still_wins_over_a_banner():
    item = make_item(name="Mask of Zorblax", flags=["wiki_banner_delete", "wiki_banner_revamped"])
    assert verdict(item) == ("hidden", ["removed-by-patch", "wiki-marked-revamped"])


def test_wiki_flags_are_read_without_regard_to_case():
    assert verdict(make_item(flags=["Wiki_Banner_DELETE"])) == ("hidden", ["wiki-marked-not-in-eql"])
    assert verdict(make_item(flags=["REMOVED_NOTE"])) == ("hidden", ["wiki-marked-removed"])
    assert "not-for-bis" in codes(classify(make_item(flags=["Temporary"]), ctx()))


def test_an_item_for_no_class_or_no_race_is_not_for_bis_at_every_level():
    for field in ("classes", "races"):
        item = make_item(drops=[("Plane of Hate", ["Innoruuk"])])
        item[field] = []
        result = classify(item, ctx())
        assert result["level"] == "wiki" and codes(result) == ["live-source:Plane of Hate", "not-for-bis"], field
        assert {r["code"]: r["seal"] for r in result["reasons"]}["not-for-bis"] == "model"
        assert "not-for-bis" in codes(classify(item, ctx(seen_keys={"w1"})))
    nobody = make_item()
    nobody["classes"] = []
    assert verdict(nobody) == ("hidden", ["no-known-source", "not-for-bis"])
    assert "not-for-bis" not in codes(classify(make_item(), ctx()))  # ["ALL"] is everybody
    assert "not-for-bis" not in codes(classify({"key": "w6", "name": "Zorblax Ring"}, ctx()))  # no list at all


def test_the_not_for_bis_text_says_why():
    nobody = make_item()
    nobody["races"] = []
    text = {r["code"]: r["text"] for r in classify(nobody, ctx())["reasons"]}["not-for-bis"]
    assert "no class or race" in text.lower() and len(text) <= 200


def make_weapon_item(weapon, slots, **kwargs):
    item = make_item(drops=[("Plane of Hate", ["Innoruuk"])], **kwargs)
    item["weapon"] = weapon
    item["slots"] = list(slots)
    return item


@pytest.mark.parametrize(
    "weapon",
    [
        {"skill": "2H Slashing", "dmg": None, "delay": 40, "bonus": None},
        {"skill": "1H Blunt", "dmg": 9, "delay": None, "bonus": None},
        {"skill": "2H Blunt", "dmg": None, "delay": None, "bonus": None},
    ],
)
@pytest.mark.parametrize("slots", [["PRIMARY"], ["PRIMARY", "SECONDARY"], ["SECONDARY"]])
def test_a_hand_weapon_that_cannot_be_scored_is_not_for_bis_at_every_level(weapon, slots):
    item = make_weapon_item(weapon, slots)
    result = classify(item, ctx())
    assert result["level"] == "wiki" and codes(result) == ["live-source:Plane of Hate", "not-for-bis"]
    assert {r["code"]: r["seal"] for r in result["reasons"]}["not-for-bis"] == "model"
    assert "not-for-bis" in codes(classify(item, ctx(seen_keys={"w1"})))  # a strict item stays out of the best-in-slot pools too


@pytest.mark.parametrize(
    ("weapon", "slots"),
    [
        ({"skill": "1H Blunt", "dmg": 9, "delay": 30, "bonus": None}, ["PRIMARY"]),  # complete
        ({"skill": "1H Blunt", "dmg": 0, "delay": 30, "bonus": None}, ["PRIMARY"]),  # a damage of zero is a number
        ({"skill": "Archery", "dmg": 7, "delay": None, "bonus": None}, ["AMMO"]),  # ammo has no delay
        ({"skill": "Archery", "dmg": 5, "delay": None, "bonus": None}, ["RANGE"]),  # not held in a hand
        ({"skill": None, "dmg": 9, "delay": None, "bonus": None}, ["PRIMARY"]),  # no skill
        (None, ["PRIMARY"]),
        ({"skill": "2H Blunt", "dmg": None, "delay": None, "bonus": None}, []),  # worn nowhere
    ],
)
def test_a_complete_weapon_or_one_not_held_in_a_hand_is_not_marked_not_for_bis(weapon, slots):
    result = classify(make_weapon_item(weapon, slots), ctx())
    assert codes(result) == ["live-source:Plane of Hate"]


def test_an_item_with_no_weapon_field_at_all_is_not_marked_not_for_bis():
    item = make_item(drops=[("Plane of Hate", ["Innoruuk"])])
    assert "weapon" not in item and "not-for-bis" not in codes(classify(item, ctx()))


def not_for_bis_text(item, context=None):
    return {r["code"]: r["text"] for r in classify(item, context or ctx())["reasons"]}["not-for-bis"]


def test_the_not_for_bis_text_names_the_weapon_that_cannot_be_scored():
    item = make_weapon_item({"skill": "2H Blunt", "dmg": None, "delay": 40, "bonus": None}, ["PRIMARY"])
    text = not_for_bis_text(item)
    assert text == "A hand weapon that cannot be scored: kept in the catalog, not used for best-in-slot."


def test_the_not_for_bis_text_names_race_none_and_class_none():
    nobody = make_item()
    nobody["races"] = []
    text = not_for_bis_text(nobody)
    assert text == "Open to no class or race (race NONE): kept in the catalog, not used for best-in-slot."
    nobody["races"], nobody["classes"] = ["ALL"], []
    assert "(class NONE)" in not_for_bis_text(nobody) and "race NONE" not in not_for_bis_text(nobody)
    nobody["races"] = []
    assert "(class NONE and race NONE)" in not_for_bis_text(nobody)


def test_the_not_for_bis_text_names_only_the_causes_that_apply():
    assert not_for_bis_text(make_item(flags=["temporary"])) == "Temporary: kept in the catalog, not used for best-in-slot."
    handed_in = not_for_bis_text(make_item(name="Zorblax Token"))  # the quest table has a quest that takes one
    assert handed_in == "Taken by a quest on hand-in: kept in the catalog, not used for best-in-slot."
    both = make_item(flags=["temporary"])
    both["races"] = []
    assert not_for_bis_text(both) == "Temporary, open to no class or race (race NONE): kept in the catalog, not used for best-in-slot."


def test_the_not_for_bis_text_with_every_cause_still_fits():
    item = make_weapon_item({"skill": "2H Blunt", "dmg": None, "delay": 40, "bonus": None}, ["PRIMARY"], flags=["temporary"], name="Zorblax Token")
    item["classes"], item["races"] = [], []
    text = not_for_bis_text(item)
    for part in ("Temporary", "hand-in", "(class NONE and race NONE)", "cannot be scored"):
        assert part in text, part
    assert len(text) <= 200 and text.endswith(": kept in the catalog, not used for best-in-slot.")


# ---- era names (M7) --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("tag", ["FearHateRevamp Era", "Fearhaterevamp Era", "fearhaterevamp era", "Epicquests Era", "Epics Era"])
def test_the_out_of_era_names_are_matched_whatever_their_spelling(tag):
    real = HandLists.from_data(
        hand_data(out_of_era_tags=["Fearhaterevamp Era", "Epicquests Era", "Epics Era"], in_era_tags=["Classic Era"])
    )
    live = make_item(drops=[("Plane of Hate", ["a"])], era_tags=[tag])
    assert verdict(live, ctx(hand=real)) == ("disputed", ["live-source:Plane of Hate", "out-of-era-tag-live-zone"])
    assert verdict(make_item(era_tags=[tag]), ctx(hand=real)) == ("hidden", ["out-of-era"])


def test_hand_list_era_names_may_be_written_as_the_wiki_spells_them():
    hand = HandLists.from_data(hand_data(out_of_era_tags=["FearHateRevamp Era", "ChardokRevamp Era", "kunark era"], in_era_tags=["Classic Era"]))
    assert hand.out_of_era == {era_key("FearHateRevamp Era"), era_key("ChardokRevamp Era"), era_key("Kunark Era")}
    live = make_item(drops=[("Plane of Hate", ["a"])], era_tags=["Fearhaterevamp Era"])
    assert verdict(live, ctx(hand=hand))[0] == "disputed"


def test_unknown_eras_are_reported_by_one_name_whatever_their_spelling():
    report = Report()
    first = make_item(drops=[("Plane of Hate", ["a"])], era_tags=["ZorblaxEra Era"])
    second = make_item(key="w2", drops=[("Plane of Hate", ["a"])], era_tags=["Zorblaxera Era"])
    for item in (first, second):
        classify(item, ctx(), report)
    assert sum(report.unknown_eras.values()) == 2 and len(report.unknown_eras) == 1


# ---- the cultural containers seen on recipe pages ---------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["Vale Forge", "Feir`Dal Forge", "Fier`Dal Forge", "Fier'Dal Forge", "Fier\u2019Dal Forge", "Tier`dal Forge", "Tier`Dal Forge", "Dalnir Forge", "DALNIR FORGE"],
)
def test_the_six_cultural_forges_seen_on_recipe_pages_hide_a_recipe(real_hand, name):
    assert container_key(name) in real_hand.cultural_containers
    context = Context(flagged=FLAGGED, aliases=ALIASES, hand=real_hand)
    assert verdict(make_item(crafted=[(name, ["Iron Bar"])]), context) == ("hidden", ["cultural-container"])


def test_the_committed_container_list_has_a_note_saying_where_the_new_names_come_from():
    data = real_data("hand-lists.json")
    notes = " ".join(data["notes"])
    assert "observed on wiki recipe pages" in notes
    for name in ("Vale Forge", "Feir`Dal Forge", "Fier`Dal Forge", "Tier`dal Forge", "Dalnir Forge"):
        assert name in notes and name in data["cultural_containers"]
    assert "Fier'Dal Forge" in notes  # written there too, and matched through the same key


def test_a_plain_forge_and_the_other_plain_containers_stay_usable(real_hand):
    for name in ("Forge", "Kiln", "Loom", "Oven", "Large Sewing Kit", "Jeweler's Kit", "Sewing Kit", "Fletching Kit", "Dalnir Kiln"):
        assert container_key(name) not in real_hand.cultural_containers, name


# ---- the shape of the answer ----------------------------------------------------------------------------


def test_the_levels_and_seals_are_the_documented_ones():
    assert LEVELS == ("strict", "wiki", "disputed", "hidden")
    assert SEALS == ("client", "developer", "measured", "player", "model")


def test_reasons_are_sorted_by_code_have_three_fields_and_safe_text():
    items = [
        make_item(drops=[("Plane of Hate", ["a"]), ("Zorblax Hollow", ["b"])], era_tags=["Classic Era", "Kunark Era"], flags=["temporary"]),
        make_item(name="Mask of Zorblax", flags=["temporary"], deity=["Tunare"]),
        make_item(drops=[("Kael Drakkal", ["a"])], era_tags=["Velious Era"]),
    ]
    for item in items:
        result = classify(item, ctx(seen_keys={"w1"}) if item is items[2] else ctx())
        assert set(result) == {"level", "reasons"} and result["level"] in LEVELS
        found = codes(result)
        assert found == sorted(found) and len(found) == len(set(found))
        for reason in result["reasons"]:
            assert set(reason) == {"code", "seal", "text"}
            assert reason["seal"] in SEALS
            assert 0 < len(reason["text"]) <= 200
            assert "<" not in reason["text"] and ">" not in reason["text"]


def test_classify_does_not_change_the_item_or_the_context():
    item = make_item(drops=[("Plane of Hate", ["a"])], era_tags=["Kunark Era"], quests=["Zorblax Quest"])
    before = copy.deepcopy(item)
    first = classify(item, ctx())
    assert item == before
    assert classify(item, ctx()) == first


def test_classify_accepts_an_item_with_only_the_fields_the_ladder_reads():
    minimal = {"key": "w5", "name": "Zorblax Ring", "sources": {"drops": [{"zone": "Plane of Hate", "npcs": []}]}}
    assert classify(minimal, ctx())["level"] == "wiki"
    assert classify({"key": "w6", "name": "Zorblax Ring"}, ctx())["level"] == "hidden"


def test_a_zone_name_with_a_parenthetical_or_the_is_found_through_the_shared_key():
    for zone in ("The Plane of Hate", "Plane of Hate (Raid)", "plane_of_hate", " Plane  of Hate "):
        assert verdict(make_item(drops=[(zone, [])]))[0] == "wiki", zone


# ---- properties --------------------------------------------------------------------------------------------

ZONES = st.sampled_from(
    ["Plane of Hate", "Zorblax Hollow", "Kael Drakkal", "Quuxen Hills", "Rujarkian Hills", "The Arena", "Lake Blarg", "Blarg Marsh"]
)
ERAS = st.sampled_from(["Classic Era", "Temple Era", "Kunark Era", "Velious Era", "Zorblaxian Era"])
CRAFTS = st.sampled_from([("Forge", ["Iron Bar"]), ("Oggok Forge", []), (None, []), ("Forge", ["Velium Bar"]), ("Kiln", [])])


@settings(max_examples=300, deadline=None)
@given(
    drops=st.lists(ZONES, max_size=4),
    sold=st.lists(ZONES, max_size=3),
    quests=st.lists(st.sampled_from(["Zorblax Quest", "Kunark Quest", "Far Quest", "Nope"]), max_size=3),
    crafted=st.lists(CRAFTS, max_size=3),
    eras=st.lists(ERAS, max_size=4),
    seen=st.booleans(),
    removed=st.booleans(),
)
def test_the_ladder_invariants(drops, sold, quests, crafted, eras, seen, removed):
    name = "Mask of Zorblax" if removed else "Zorblax Ring"
    item = make_item(
        name=name,
        drops=[(zone, []) for zone in drops],
        sold_by=[(zone, "Vendor") for zone in sold],
        quests=quests,
        crafted=crafted,
        era_tags=eras,
    )
    context = ctx(seen_keys={"w1"} if seen else set(), out_of_era_names={"velium bar"})
    result = classify(item, context)
    found = codes(result)
    assert result["level"] in LEVELS
    assert found == sorted(found)
    if removed:
        assert result["level"] == "hidden"
    elif seen:
        assert result["level"] == "strict"
    else:
        assert result["level"] != "strict"
    live = any(code.startswith("live-source:") for code in found)
    if not removed and not seen:
        assert (result["level"] in ("wiki", "disputed")) == live
    # shuffling the sources never changes the answer
    shuffled = copy.deepcopy(item)
    shuffled["sources"]["drops"].reverse()
    shuffled["sources"]["sold_by"].reverse()
    shuffled["sources"]["crafted"].reverse()
    shuffled["era_tags"].reverse()
    assert classify(shuffled, context) == result


# ---- the recorded pages, with the real hand lists, aliases and client zones -------------------------


@pytest.fixture(scope="module")
def real_context(real_hand, real_aliases, client_zones):
    flagged = {i for i, zone in client_zones.items() if zone["flagged"]}
    return Context(flagged=flagged, aliases=real_aliases, hand=real_hand)


def recorded_item(title):
    path = REPO / "fixtures" / "wiki" / f"{fixture_slug(title)}.json"
    (record,) = page_records(json.loads(path.read_text(encoding="utf-8")))
    parsed = parse_page(record)
    assert isinstance(parsed, ParsedPage), title
    return normalize(parsed)


def recorded_verdict(title, context):
    result = classify(recorded_item(title), context)
    return result["level"], codes(result)


@pytest.mark.parametrize(
    ("title", "level", "found"),
    [
        ("Engineer's Ring", "wiki", ["live-source:Plane of Hate"]),
        ("Imbued Granite Spaulders", "wiki", ["live-source:The Hole"]),  # the name regex used to hide it
        ("Bladestopper", "wiki", ["live-source:Nagafen's Lair"]),
        ("Darkwar Mask", "disputed", ["live-source:Plane of Hate", "out-of-era-tag-live-zone"]),  # Velious tag
        ("Mask of Deception", "hidden", ["removed-by-patch"]),
        ("Girdle of Faith", "wiki", ["live-source:quest"]),  # a class test linked to the page of the Plane of Sky, a live zone (no quest table here)
        ("Wu's Fist of Mastery", "wiki", ["live-source:quest"]),  # the same, for the Monk Test of Fists
    ],
)
def test_recorded_item_pages_get_the_expected_level(real_context, title, level, found):
    assert recorded_verdict(title, real_context) == (level, found)


def test_a_cultural_forge_recipe_hides_the_ogre_bouncer_shield(real_context):
    assert recorded_verdict("Ogre Bouncer Shield", real_context) == ("hidden", ["cultural-container"])


def test_a_plain_forge_recipe_makes_the_banded_belt_wiki(real_context):
    assert recorded_verdict("Banded Belt", real_context) == ("wiki", ["live-source:craft"])


def test_recipes_in_a_potion_bag_a_loom_or_a_sewing_kit_are_live_sources(real_context):
    assert recorded_verdict("10 Dose Greater Null Potion", real_context) == ("wiki", ["live-source:craft"])
    # The cloak's page carries an out-of-era tag, so its live source is disputed rather than wiki.
    item = recorded_item("Crystalline Silk Cloak")
    assert item["era_tags"] and set(item["era_tags"]) <= {"Velious Era", "Kunark Era", "Luclin Era"}
    assert recorded_verdict("Crystalline Silk Cloak", real_context) == (
        "disputed",
        ["live-source:craft", "out-of-era-tag-live-zone"],
    )


def test_a_live_vendor_beats_a_cultural_only_recipe(real_context):
    # Block of Adamantite: made only in the Teir`dal and Oggok forges, but sold by vendors in live zones.
    assert recorded_verdict("Block of Adamantite", real_context) == ("wiki", ["live-source:vendor"])
    item = recorded_item("Block of Adamantite")
    item["sources"]["sold_by"] = []
    result = classify(item, real_context)
    assert (result["level"], codes(result)) == ("hidden", ["cultural-container"])


def test_a_recipe_with_a_skill_and_no_container_is_not_a_live_source(real_context):
    # The item keeps no trace of it (a recipe is kept only if it names a container or an ingredient).
    cloak = recorded_item("Large Patchwork Cloak")
    assert cloak["sources"]["crafted"] == []
    # this page also carries a {{delete}} banner ("not relevent in EQ legends"), which now hides it for its own reason
    assert recorded_verdict("Large Patchwork Cloak", real_context) == ("hidden", ["wiki-marked-not-in-eql"])
    cloak["flags"] = [flag for flag in cloak["flags"] if not flag.startswith("wiki_banner_")]
    result = classify(cloak, real_context)  # without the banner, the skill alone is no source
    assert (result["level"], codes(result)) == ("hidden", ["no-known-source"])
    assert verdict(make_item(crafted=[(None, [])])) == ("hidden", ["no-known-source"])


def test_a_note_that_an_item_is_no_trade_skill_recipe_is_no_source(real_context):
    assert recorded_verdict("Air Tight Box", real_context) == ("hidden", ["no-known-source"])
