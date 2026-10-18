"""Tests for the evidence ladder's side of the second parser review (2026-10-14).

A quest is found by the target of its link (the label is only a second chance), and a foraged zone goes through the
zone gate like a drop zone. The last sections are a later change: a quest link whose target is the page of a zone, with
a label that names the test, puts the quest in that zone. The world is synthetic: invented zones, ids and names
(Zorblax and friends).
"""

from trioforge.data.evidence import (
    Context,
    HandLists,
    Quest,
    QuestTable,
    Report,
    classify,
    is_known_zone,
)

SOURCE = [{"kind": "url", "ref": "https://example.invalid/patch-notes"}]

HAND = HandLists.from_data(
    {
        "version": "2026-10-14",
        "removed": [],
        "research_removals": [],
        "unreleased_zones": [{"names": ["Rujarkian Hills"], "ids": [3], "seal": "developer", "source": SOURCE, "date": "2026-09-17"}],
        "exists_unflagged_zones": [{"names": ["The Arena"], "ids": [77], "seal": "developer", "source": SOURCE, "date": "2026-06-23"}],
        "eql_only_zones": [99, 3],
        "cultural_containers": ["Oggok Forge"],
        "in_era_tags": ["Classic Era"],
        "out_of_era_tags": ["Kunark Era"],
    }
)
ALIASES = {
    "zorblax hollow": [1],
    "plane of hate": [2],
    "rujarkian hills": [3],
    "lake blarg": [99],
    "arena": [77],
    "kael drakkal": [500],
    "quuxen hills": [501],
}
FLAGGED = {1, 2, 3, 99}


def quest(title, zone, era="Classic Era", wiki_title=None):
    return Quest(title=title, giver="Old Zorb", zone=zone, era=era, wiki_title=wiki_title)


def ctx(quests=()):
    return Context(flagged=FLAGGED, aliases=ALIASES, hand=HAND, quests=QuestTable(quests))


def make_item(key="w1", name="Zorblax Ring", *, drops=(), sold_by=(), quests=(), quest_labels=(), crafted=(), foraged=(), era_tags=(), flags=()):
    sources = {"drops": list(drops), "sold_by": list(sold_by), "quests": list(quests), "crafted": list(crafted)}
    if quest_labels:
        sources["quest_labels"] = list(quest_labels)
    if foraged:
        sources["foraged"] = [{"zone": zone} for zone in foraged]
    return {
        "key": key,
        "name": name,
        "wiki": {"pageid": int(key[1:]), "revid": 1, "title": name},
        "slots": ["EAR"],
        "classes": ["ALL"],
        "races": ["ALL"],
        "deity": None,
        "flags": list(flags),
        "sources": sources,
        "era_tags": list(era_tags),
    }


def verdict(item, context=None, report=None):
    result = classify(item, context or ctx(), report)
    return result["level"], [reason["code"] for reason in result["reasons"]]


# ---- 1: quests are found by the target of their link --------------------------------------------------------------------


def test_a_quest_is_found_by_the_target_of_its_link_not_by_the_label():
    quests = [quest("Zorblax Tests", "Zorblax Hollow")]
    item = make_item(quests=["Zorblax Tests"], quest_labels=[{"title": "Zorblax Tests", "label": "Zorblax Test of Courage"}])
    assert verdict(item, ctx(quests)) == ("wiki", ["live-source:quest"])


def test_a_quest_is_found_by_the_wiki_title_the_quest_table_gives_it():
    quests = [quest("Test of Courage", "Zorblax Hollow", wiki_title="Zorblax Tests")]
    assert verdict(make_item(quests=["Zorblax Tests"]), ctx(quests)) == ("wiki", ["live-source:quest"])


def test_a_label_that_is_the_title_of_a_quest_is_a_second_chance_when_the_target_names_no_quest():
    quests = [quest("Tribunal Initiate", "Zorblax Hollow")]
    item = make_item(quests=["Tribunal Symbol Quests"], quest_labels=[{"title": "Tribunal Symbol Quests", "label": "Tribunal Initiate"}])
    assert verdict(item, ctx(quests)) == ("wiki", ["live-source:quest"])


def test_a_target_and_a_label_that_name_no_quest_find_nothing():
    quests = [quest("Zorblax Tests", "Zorblax Hollow")]
    item = make_item(quests=["Plane of Sky"], quest_labels=[{"title": "Plane of Sky", "label": "Bard Test of Tone"}])
    assert verdict(item, ctx(quests)) == ("hidden", ["no-known-source"])


def test_a_quest_found_by_target_still_obeys_the_quest_zone_and_era_gates():
    far = [quest("Far Tests", "Kael Drakkal")]
    assert verdict(make_item(quests=["Far Tests"]), ctx(far)) == ("hidden", ["no-known-source"])
    late = [quest("Late Tests", "Zorblax Hollow", era="Kunark Era")]
    assert verdict(make_item(quests=["Late Tests"]), ctx(late)) == ("hidden", ["no-known-source"])


def test_the_label_of_one_quest_page_does_not_hide_the_target_of_another():
    quests = [quest("Zorblax Tests", "Zorblax Hollow")]
    item = make_item(quests=["Zorblax Tests"], quest_labels=[{"title": "Zorblax Tests", "label": "Nothing Quest"}])
    assert verdict(item, ctx(quests)) == ("wiki", ["live-source:quest"])


# ---- 4: a foraged zone goes through the zone gate like a drop zone -----------------------------------------------------


def test_a_foraged_zone_that_the_client_flags_is_a_live_source():
    result = classify(make_item(foraged=["Zorblax Hollow"]), ctx())
    assert result["level"] == "wiki"
    (reason,) = result["reasons"]
    assert (reason["code"], reason["seal"]) == ("live-source:foraged", "client")


def test_a_foraged_zone_that_exists_although_the_client_does_not_flag_it_is_live_with_the_developers_seal():
    result = classify(make_item(foraged=["The Arena"]), ctx())
    assert result["level"] == "wiki" and result["reasons"][0]["seal"] == "developer"


def test_foraged_zones_the_client_does_not_flag_hide_the_item_with_the_zone_reason_for_drops():
    assert verdict(make_item(foraged=["Kael Drakkal", "Quuxen Hills"])) == ("hidden", ["zones-not-in-eql"])
    assert verdict(make_item(foraged=["Rujarkian Hills"])) == ("hidden", ["zone-unreleased"])


def test_foraged_zones_that_are_unmapped_are_reported_once_and_are_no_live_source():
    report = Report()
    assert verdict(make_item(foraged=["Blarg Marsh", "Blarg Marsh"]), report=report) == ("hidden", ["zones-unmapped"])
    assert report.unmapped_zones == {"Blarg Marsh": 1}


def test_one_live_foraged_zone_is_enough_among_dead_ones():
    assert verdict(make_item(foraged=["Kael Drakkal", "Zorblax Hollow", "Blarg Marsh"])) == ("wiki", ["live-source:foraged"])


def test_foraged_and_dropped_zones_are_judged_together():
    dead_drop = [{"zone": "Kael Drakkal", "npcs": []}]
    assert verdict(make_item(drops=dead_drop, foraged=["Zorblax Hollow"])) == ("wiki", ["live-source:foraged"])
    live_drop = [{"zone": "Zorblax Hollow", "npcs": []}]
    assert verdict(make_item(drops=live_drop, foraged=["Kael Drakkal"])) == ("wiki", ["live-source:Zorblax Hollow"])
    assert verdict(make_item(drops=dead_drop, foraged=["Quuxen Hills"])) == ("hidden", ["zones-not-in-eql"])
    assert verdict(make_item(drops=[{"zone": "Blarg Marsh", "npcs": []}], foraged=["Kael Drakkal"])) == ("hidden", ["zones-not-in-eql"])


def test_a_foraged_item_with_an_out_of_era_tag_is_disputed_unless_the_zone_exists_only_in_eql():
    tags = ["Kunark Era"]
    assert verdict(make_item(foraged=["Zorblax Hollow"], era_tags=tags)) == ("disputed", ["live-source:foraged", "out-of-era-tag-live-zone"])
    assert verdict(make_item(foraged=["Lake Blarg"], era_tags=tags)) == ("wiki", ["live-source:foraged"])
    assert verdict(make_item(foraged=["Zorblax Hollow", "Lake Blarg"], era_tags=tags)) == ("wiki", ["live-source:foraged"])


def test_an_item_with_no_foraged_zone_is_graded_as_before():
    assert verdict(make_item(drops=[{"zone": "Kael Drakkal", "npcs": []}])) == ("hidden", ["zones-not-in-eql"])
    assert verdict(make_item()) == ("hidden", ["no-known-source"])


# ---- 3: the predicate the build uses to find zones written as bullets ----------------------------------------------------


def test_a_zone_is_known_when_it_is_an_alias_or_a_hand_listed_zone():
    context = ctx()
    for name in ("Zorblax Hollow", "the zorblax hollow", "The Arena", "Rujarkian Hills", "Kael Drakkal", "Zorblax Hollow (Upper)"):
        assert is_known_zone(name, context), name
    for name in ("a rat", "Blarg Marsh", "", "Smithy Rrarrgin"):
        assert not is_known_zone(name, context), name


# ---- a quest link whose target is the page of a zone, not of a quest ------------------------------------------------------


def zone_link(zone, label="Zorblax Test of Courage"):
    """The quest fields of an item whose page links a test to the page of a zone: the target is the zone, the label the test."""
    return {"quests": [zone], "quest_labels": [{"title": zone, "label": label}]}


def only_reason(result):
    (reason,) = result["reasons"]
    return reason


def test_a_quest_link_to_the_page_of_a_live_zone_is_a_live_quest_source_in_that_zone():
    result = classify(make_item(**zone_link("Zorblax Hollow")), ctx())  # no quest of the table has that title
    assert result["level"] == "wiki"
    reason = only_reason(result)
    assert (reason["code"], reason["seal"]) == ("live-source:quest", "client")
    assert "Zorblax Hollow" in reason["text"]
    assert verdict(make_item(**zone_link("the_zorblax_hollow"))) == ("wiki", ["live-source:quest"])  # the page title's spelling


def test_a_quest_link_to_a_zone_that_exists_although_the_client_does_not_flag_it_has_the_developers_seal():
    result = classify(make_item(**zone_link("The Arena")), ctx())
    assert result["level"] == "wiki" and [(r["code"], r["seal"]) for r in result["reasons"]] == [("live-source:quest", "developer")]


def test_a_quest_link_to_the_page_of_a_zone_that_is_not_live_gives_the_zone_reasons_of_a_drop():
    unreleased = classify(make_item(**zone_link("Rujarkian Hills")), ctx())
    assert unreleased["level"] == "hidden"
    reason = only_reason(unreleased)
    assert reason["code"] == "zone-unreleased" and "quest" in reason["text"]
    unflagged = classify(make_item(**zone_link("Kael Drakkal")), ctx())
    assert unflagged["level"] == "hidden"
    reason = only_reason(unflagged)
    assert reason["code"] == "zones-not-in-eql" and "quest" in reason["text"]


def test_the_zone_of_a_quest_link_is_judged_with_the_drop_and_foraging_zones_when_none_is_live():
    unreleased_drop = [{"zone": "Rujarkian Hills", "npcs": []}]
    dead_drop = [{"zone": "Kael Drakkal", "npcs": []}]
    unmapped_drop = [{"zone": "Blarg Marsh", "npcs": []}]
    assert verdict(make_item(drops=unreleased_drop, **zone_link("Rujarkian Hills"))) == ("hidden", ["zone-unreleased"])
    assert verdict(make_item(foraged=["Rujarkian Hills"], **zone_link("Rujarkian Hills"))) == ("hidden", ["zone-unreleased"])
    assert verdict(make_item(drops=dead_drop, **zone_link("Rujarkian Hills"))) == ("hidden", ["zones-not-in-eql"])
    assert verdict(make_item(drops=unmapped_drop, **zone_link("Rujarkian Hills"))) == ("hidden", ["zones-not-in-eql"])
    assert verdict(make_item(drops=unmapped_drop, **zone_link("Zorblax Tests"))) == ("hidden", ["zones-unmapped"])  # no zone: nothing found


def test_a_target_that_is_neither_a_quest_nor_a_known_zone_finds_nothing_and_is_no_unmapped_zone():
    report = Report()
    assert verdict(make_item(**zone_link("Blarg Marsh")), report=report) == ("hidden", ["no-known-source"])  # looks like a zone, has no alias
    assert verdict(make_item(**zone_link("Zorblax Tests")), report=report) == ("hidden", ["no-known-source"])  # a quest title the table lacks
    assert not report.unmapped_zones


def test_a_target_that_is_a_quest_title_in_the_table_keeps_the_path_of_its_quest():
    # the title is also the page of a live zone, but the giver's zone decides, and so does the page's era
    assert verdict(make_item(**zone_link("Zorblax Hollow")), ctx([quest("Zorblax Hollow", "Kael Drakkal")])) == ("hidden", ["no-known-source"])
    late = [quest("Zorblax Hollow", "Zorblax Hollow", era="Kunark Era")]
    assert verdict(make_item(**zone_link("Zorblax Hollow")), ctx(late)) == ("hidden", ["no-known-source"])
    # a quest title adds no zone to the dead-zone reasons, and a live giver on the title of a dead zone's page is a quest like any other
    assert verdict(make_item(**zone_link("Kael Drakkal")), ctx([quest("Kael Drakkal", "Quuxen Hills")])) == ("hidden", ["no-known-source"])
    result = classify(make_item(**zone_link("Kael Drakkal")), ctx([quest("Kael Drakkal", "Zorblax Hollow")]))
    assert result["level"] == "wiki" and "quest giver" in only_reason(result)["text"]


def test_a_zone_linked_quest_has_no_page_of_its_own_so_the_items_era_tags_judge_it_like_a_drop():
    link = zone_link("Zorblax Hollow")
    assert verdict(make_item(era_tags=["Classic Era"], **link)) == ("wiki", ["live-source:quest"])
    assert verdict(make_item(era_tags=["Kunark Era"], **link)) == ("disputed", ["live-source:quest", "out-of-era-tag-live-zone"])
    both = ["conflicting-era-tags", "live-source:quest", "out-of-era-tag-live-zone"]
    assert verdict(make_item(era_tags=["Kunark Era", "Classic Era"], **link)) == ("disputed", both)


def test_a_quest_link_to_a_zone_that_exists_only_in_eql_leaves_the_era_tag_out_of_it():
    assert verdict(make_item(era_tags=["Kunark Era"], **zone_link("Lake Blarg"))) == ("wiki", ["live-source:quest"])  # as for a drop there


def test_a_label_or_an_item_name_that_is_a_zone_is_no_zone_link():
    labelled = make_item(quests=["Zorblax Tests"], quest_labels=[{"title": "Zorblax Tests", "label": "Zorblax Hollow"}])
    assert verdict(labelled) == ("hidden", ["no-known-source"])
    assert verdict(make_item(name="Zorblax Hollow")) == ("hidden", ["no-known-source"])  # a reward named like a zone


def test_a_zone_link_adds_nothing_to_an_item_that_has_another_live_source():
    # the link may mean "used in this quest" (the wind runes drop in the Plane of Sky and are handed in to its tests): it is a source only when nothing else is
    others = {
        "drop": {"drops": [{"zone": "Zorblax Hollow", "npcs": ["a rat"]}]},
        "vendor": {"sold_by": [{"zone": "Zorblax Hollow", "npc": "Old Zorb"}]},
        "foraging": {"foraged": ["Zorblax Hollow"]},
        "craft": {"crafted": [{"container": "Brew Barrel", "ingredients": ["Zorblax Hops"]}]},
    }
    for kind, sources in others.items():
        old = classify(make_item(**sources), ctx())
        assert old["level"] == "wiki", kind
        for zone in ("Zorblax Hollow", "The Arena", "Lake Blarg"):
            assert classify(make_item(**sources, **zone_link(zone)), ctx()) == old, (kind, zone)
    quests = [quest("Zorblax Tests", "Zorblax Hollow")]  # a quest of the table is such a source too
    old = classify(make_item(quests=["Zorblax Tests"]), ctx(quests))
    labelled = make_item(quests=["Zorblax Tests", "Zorblax Hollow"], quest_labels=zone_link("Zorblax Hollow")["quest_labels"])
    assert classify(labelled, ctx(quests)) == old
    # and the zone of the link does not change how the era tags judge the other source
    drop = {"drops": [{"zone": "Zorblax Hollow", "npcs": ["a rat"]}], "era_tags": ["Kunark Era"]}
    assert verdict(make_item(**drop, **zone_link("Lake Blarg"))) == ("disputed", ["live-source:Zorblax Hollow", "out-of-era-tag-live-zone"])


def test_a_source_that_is_not_live_does_not_stop_a_zone_link():
    dead_drop = [{"zone": "Kael Drakkal", "npcs": []}]
    assert verdict(make_item(drops=dead_drop, **zone_link("Zorblax Hollow"))) == ("wiki", ["live-source:quest"])
    late = [quest("Late Tests", "Zorblax Hollow", era="Kunark Era")]  # a quest on an out-of-era page is no live source
    labelled = make_item(quests=["Late Tests", "Zorblax Hollow"], quest_labels=zone_link("Zorblax Hollow")["quest_labels"])
    assert verdict(labelled, ctx(late)) == ("wiki", ["live-source:quest"])


def test_a_quest_of_the_table_and_a_zone_link_make_one_quest_reason_with_the_text_of_the_quest():
    item = make_item(quests=["Zorblax Tests", "Zorblax Hollow"], quest_labels=zone_link("Zorblax Hollow")["quest_labels"])
    result = classify(item, ctx([quest("Zorblax Tests", "Zorblax Hollow")]))
    assert result["level"] == "wiki" and "quest giver" in only_reason(result)["text"]


def test_several_zone_links_make_one_quest_reason_that_names_a_live_zone():
    zones = ["The Arena", "Kael Drakkal", "Zorblax Hollow", "zorblax_hollow"]
    item = make_item(quests=zones, quest_labels=[{"title": zone, "label": "Zorblax Test of Courage"} for zone in zones])
    result = classify(item, ctx())
    reason = only_reason(result)
    assert (result["level"], reason["code"], reason["seal"]) == ("wiki", "live-source:quest", "client")
    assert "Zorblax Hollow" in reason["text"] and "Arena" not in reason["text"] and "Kael" not in reason["text"]


# ---- the review of the zone links: what counts as one, and what the reasons say -------------------------------------------


def test_a_zone_link_counts_only_with_a_label_that_names_a_test():
    assert verdict(make_item(quests=["Zorblax Hollow"])) == ("hidden", ["no-known-source"])  # a bare link says nothing about a quest
    assert verdict(make_item(quests=["Kael Drakkal"])) == ("hidden", ["no-known-source"])  # and joins no dead-zone reason
    for label in ("Zorblax Hollow", "the_zorblax_hollow", "Zorblax Hollow (Upper)", "Lake Blarg"):  # a zone's name is a place, not a test
        assert verdict(make_item(**zone_link("Zorblax Hollow", label))) == ("hidden", ["no-known-source"]), label
    other_link = {"quests": ["Zorblax Hollow"], "quest_labels": [{"title": "Plane of Hate", "label": "Zorblax Test of Courage"}]}
    assert verdict(make_item(**other_link)) == ("hidden", ["no-known-source"])  # the label belongs to another link
    labels = [{"title": "Zorblax Hollow", "label": "Zorblax Hollow"}, {"title": "Zorblax Hollow", "label": "Zorblax Test of Courage"}]
    assert verdict(make_item(quests=["Zorblax Hollow"], quest_labels=labels)) == ("wiki", ["live-source:quest"])  # one label that names a test is enough


def test_a_rejected_quest_of_the_table_is_never_replaced_by_the_zone_next_to_it():
    # "The Sword of Nobility" is in the table, but its page is out of era; the link to the zone beside it has no label
    sword = [quest("The Sword of Nobility", "Zorblax Hollow", era="Kunark Era")]
    assert verdict(make_item(quests=["The Sword of Nobility", "Zorblax Hollow"]), ctx(sword)) == ("hidden", ["no-known-source"])
    # a label that names a quest of the table leaves the decision to that quest, whatever the zone says
    for rejected in (quest("Zorblax Test of Courage", "Zorblax Hollow", era="Kunark Era"), quest("Zorblax Test of Courage", "Kael Drakkal")):
        assert verdict(make_item(**zone_link("Zorblax Hollow")), ctx([rejected])) == ("hidden", ["no-known-source"])
    result = classify(make_item(**zone_link("Zorblax Hollow")), ctx([quest("Zorblax Test of Courage", "Zorblax Hollow")]))
    assert result["level"] == "wiki" and "quest giver" in only_reason(result)["text"]


def test_the_reason_of_a_zone_link_says_what_the_page_links_and_not_that_a_quest_gives_the_item():
    text = only_reason(classify(make_item(**zone_link("Zorblax Hollow")), ctx()))["text"]
    assert text == "The item page links it to a quest in Zorblax Hollow (Zorblax Test of Courage), a zone that is part of EQL."
    labels = [{"title": "Zorblax Hollow", "label": "Zorblax Test of Wisdom"}, {"title": "Zorblax Hollow", "label": "Zorblax Test of Courage"}]
    first = only_reason(classify(make_item(quests=["Zorblax Hollow"], quest_labels=labels), ctx()))["text"]
    assert first == text  # several labels: the first in sorted order, whatever the order of the page


def test_only_a_live_linked_zone_can_leave_the_era_tag_out_of_it():
    # Rujarkian Hills exists only in EQL but is not released: its link is no source, so it cannot be why the tag is ignored
    zones = ["Zorblax Hollow", "Rujarkian Hills"]
    links = {"quests": zones, "quest_labels": [{"title": zone, "label": "Zorblax Test of Courage"} for zone in zones]}
    assert verdict(make_item(era_tags=["Kunark Era"], **links)) == ("disputed", ["live-source:quest", "out-of-era-tag-live-zone"])


def test_a_target_with_a_qualifier_in_parentheses_is_a_quest_page_not_a_zone_page():
    report = Report()
    assert verdict(make_item(**zone_link("Zorblax Hollow (Quest)")), report=report) == ("hidden", ["no-known-source"])
    assert verdict(make_item(**zone_link("Kael Drakkal (Quest)")), report=report) == ("hidden", ["no-known-source"])  # and joins no dead-zone reason
    assert not report.unmapped_zones


def dead_zone_text(item, code):
    return next(reason["text"] for reason in classify(item, ctx())["reasons"] if reason["code"] == code)


def test_the_dead_zone_reasons_name_only_the_kinds_of_zone_the_item_has():
    drops, link = [{"zone": "Rujarkian Hills", "npcs": []}], zone_link("Rujarkian Hills")
    unreleased = "Every {} zone is flagged but not yet released."
    assert dead_zone_text(make_item(drops=drops), "zone-unreleased") == unreleased.format("drop")
    assert dead_zone_text(make_item(foraged=["Rujarkian Hills"]), "zone-unreleased") == unreleased.format("foraging")
    assert dead_zone_text(make_item(**link), "zone-unreleased") == unreleased.format("quest")
    assert dead_zone_text(make_item(drops=drops, foraged=["Rujarkian Hills"]), "zone-unreleased") == unreleased.format("drop or foraging")
    assert dead_zone_text(make_item(drops=drops, **link), "zone-unreleased") == unreleased.format("drop or quest")
    assert dead_zone_text(make_item(foraged=["Rujarkian Hills"], **link), "zone-unreleased") == unreleased.format("foraging or quest")
    assert dead_zone_text(make_item(drops=drops, foraged=["Rujarkian Hills"], **link), "zone-unreleased") == unreleased.format("drop, foraging or quest")
    not_in_eql = "No {} zone is part of EQL: the client does not flag them."
    assert dead_zone_text(make_item(**zone_link("Kael Drakkal")), "zones-not-in-eql") == not_in_eql.format("quest")
    mixed = make_item(drops=[{"zone": "Blarg Marsh", "npcs": []}], **link)  # an unmapped drop zone beside an unreleased quest zone
    assert dead_zone_text(mixed, "zones-not-in-eql") == not_in_eql.format("drop or quest")
    unmapped = "No {} zone could be matched to a client zone."
    assert dead_zone_text(make_item(drops=[{"zone": "Blarg Marsh", "npcs": []}]), "zones-unmapped") == unmapped.format("drop")
    assert dead_zone_text(make_item(foraged=["Blarg Marsh"]), "zones-unmapped") == unmapped.format("foraging")
