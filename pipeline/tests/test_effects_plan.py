"""Tests for the exalt plan: effects matched onto the items of a kit under the rules of the wiki's Exaltations page.

The effects, donors and hosts are small and made up here, so each rule has a case of its own; the plan of real kits is in test_effects_files.py."""

import pytest

from trioforge.effects import judgment, plan
from trioforge.effects import spells as sp
from trioforge.effects.layer import Context

J = judgment.default()
CLASSES = ("PAL", "MNK", "BER")


def donor(key, slots, classes=("ALL",), two_hand=False, arrival=4, access=3):
    return {"key": key, "slots": list(slots), "classes": list(classes), "two_hand": two_hand, "arrival": arrival, "access": access, "eligible": True}


def effect(eid, kind, donors, category=None, magnitude=100, focus_kind="spell_haste"):
    record = {"id": eid, "kind": kind, "name": eid, "items": donors, "category": category or ("focus_" + focus_kind if kind == "focus" else "damage"), "magnitude": magnitude}
    if kind == "focus":
        record["focus"] = {"kind": focus_kind, "family": eid, "tier": 2, "spa": 127, "min_pct": magnitude, "max_pct": magnitude, "limits": {}}
    return record


def context(effects, shares=None, classes=CLASSES):
    shares = shares or {c: 1.0 for c in classes}
    cov = {e["id"]: {c: {"share": shares.get(c, 0.0), "n": 1, "of": 1} for c in classes} for e in effects if e["kind"] == "focus"}
    return Context(
        J, effects, {e["id"]: e for e in effects}, cov, {c: {} for c in classes}, {c: {} for c in classes}, {c: 1.0 for c in classes}, {}, 1.0,
        {c: False for c in classes}, {}, sp.SpellBook([], 50),
    )  # fmt: skip


def option(eid, score=1.0, member="PAL"):
    return {"effect": eid, "score": score, "member": member, "donor": "-", "others": []}


def host(slots, classes=("ALL",)):
    return {"slots": list(slots), "classes": list(classes)}


def place(options, kit, hosts, effects, tier=4, classes=CLASSES, role="tank", shares=None):
    return plan.plan_kit(options, kit, hosts, context(effects, shares, classes), classes, role, tier)


def rows(result):
    return {(r["k"], r["e"]): (r["p"], r["h"]) for r in result["rows"]}


def noroom(result):
    return {(r["k"], r["e"]): r["w"] for r in result["noroom"]}


# ---- like item, classes, tier -------------------------------------------------------------------------------------------------


def test_an_effect_is_placed_on_a_like_slot_host_that_a_class_of_the_trio_can_use_with_the_donor():
    e = effect("e1", "focus", [donor("d1", ["CHEST"], ["PAL", "CLR"])])
    hosts = {"head": host(["HEAD"]), "chest": host(["CHEST"], ["PAL", "WAR"])}
    result = place({"focus": [option("e1")]}, [("HEAD", "head"), ("CHEST", "chest")], hosts, [e])
    assert rows(result) == {("focus", "e1"): ("CHEST", "chest")}
    assert result["rows"][0]["d"] == "d1" and result["rows"][0]["c"] == ["PAL"]  # the host's classes narrow to the overlap
    assert result["noroom"] == []


def test_no_host_with_a_class_in_common_is_no_room_for_class():
    e = effect("e1", "focus", [donor("d1", ["CHEST"], ["PAL"])])
    result = place({"focus": [option("e1")]}, [("CHEST", "chest")], {"chest": host(["CHEST"], ["MNK"])}, [e])
    assert noroom(result) == {("focus", "e1"): "class"} and result["rows"] == []


def test_no_like_item_in_the_kit_is_no_room_for_slot():
    e = effect("e1", "focus", [donor("d1", ["CHEST"])])
    result = place({"focus": [option("e1")]}, [("HEAD", "head")], {"head": host(["HEAD"])}, [e])
    assert noroom(result) == {("focus", "e1"): "slot"}


def test_a_class_outside_the_trio_does_not_count_for_the_overlap():
    e = effect("e1", "focus", [donor("d1", ["CHEST"], ["WIZ"])])
    result = place({"focus": [option("e1")]}, [("CHEST", "chest")], {"chest": host(["CHEST"], ["WIZ"])}, [e])
    assert noroom(result) == {("focus", "e1"): "donor"}  # (no copy of the effect the trio can wear: not a matter of slots)
    assert result["rows"] == []


def test_the_fit_rules_in_the_order_they_are_checked():
    d = donor("d", ["CHEST"], ["PAL", "CLR"])
    assert plan._fit(d, host(["CHEST"], ["PAL"]), CLASSES, "CHEST") == (None, ["PAL"])
    assert plan._fit(d, host(["CHEST"], ["ALL"]), CLASSES, "ANY1") == (None, ["PAL"])  # (the trio's classes that the donor allows; where the host is worn does not matter)
    assert plan._fit(d, host(["CHEST"], ["MNK"]), CLASSES, "CHEST") == ("class", [])
    assert plan._fit(d, host(["HEAD"], ["PAL"]), CLASSES, "HEAD") == ("slot", [])
    assert plan._fit(donor("t", ["PRIMARY"], two_hand=True), host(["SECONDARY"]), CLASSES, "SECONDARY") == ("primary", [])  # (the primary rule is checked before the slot)


def test_a_two_hand_or_primary_only_donor_needs_the_host_in_the_primary_hand_itself():
    sword = host(["PRIMARY", "SECONDARY"])  # an item that could go in either hand
    for d in (donor("t", ["PRIMARY"], two_hand=True), donor("p", ["PRIMARY"])):
        assert plan._fit(d, sword, CLASSES, "PRIMARY") == (None, ["PAL", "MNK", "BER"])
        assert plan._fit(d, sword, CLASSES, "SECONDARY") == ("primary", [])
        assert plan._fit(d, sword, CLASSES, "ANY1") == ("primary", [])
    both = donor("w", ["PRIMARY", "SECONDARY"])  # a one-hander's effect is not primary-only: any hand and any Any place will do
    assert plan._fit(both, sword, CLASSES, "ANY1") == (None, ["PAL", "MNK", "BER"])


@pytest.mark.parametrize(("kind", "opens"), [("focus", 1), ("click", 2), ("worn", 3), ("proc", 4)])
def test_the_host_must_have_reached_the_tier_the_socket_opens_at(kind, opens):
    e = effect("e1", kind, [donor("d1", ["CHEST"])])
    hosts = {"chest": host(["CHEST"])}
    below = place({kind: [option("e1")]}, [("CHEST", "chest")], hosts, [e], tier=opens - 1)
    assert noroom(below) == {(kind, "e1"): "tier"} and below["rows"] == []
    at = place({kind: [option("e1")]}, [("CHEST", "chest")], hosts, [e], tier=opens)
    assert rows(at) == {(kind, "e1"): ("CHEST", "chest")}


def test_a_donor_that_arrives_below_the_socket_tier_has_to_be_upgraded():
    quest = effect("q", "click", [donor("dq", ["BACK"], arrival=0)])
    drop = effect("d", "click", [donor("dd", ["BACK"], arrival=4)])
    result = place(
        {"click": [option("q", 2.0), option("d", 1.0)]}, [("BACK", "back1"), ("ANY1", "back2")], {"back1": host(["BACK"]), "back2": host(["BACK"])}, [quest, drop]
    )
    assert {r["e"]: r["u"] for r in result["rows"]} == {"q": 1, "d": 0}


# ---- a 2H or primary-only donor needs a primary host -------------------------------------------------------------------------------


def test_a_two_hand_donor_gets_a_primary_host():
    e = effect("bash", "worn", [donor("2h", ["PRIMARY"], two_hand=True)], category="melee_skill")
    hosts = {"shield": host(["SECONDARY"]), "sword": host(["PRIMARY", "SECONDARY"]), "chest": host(["CHEST"])}
    result = place({"worn": [option("bash")]}, [("SECONDARY", "shield"), ("PRIMARY", "sword"), ("CHEST", "chest")], hosts, [e])
    assert rows(result) == {("worn", "bash"): ("PRIMARY", "sword")}


def test_without_a_primary_host_a_two_hand_donor_is_no_room_for_primary():
    e = effect("bash", "worn", [donor("2h", ["PRIMARY"], two_hand=True)], category="melee_skill")
    hosts = {"shield": host(["SECONDARY"]), "chest": host(["CHEST"])}
    result = place({"worn": [option("bash")]}, [("SECONDARY", "shield"), ("CHEST", "chest")], hosts, [e])
    assert noroom(result) == {("worn", "bash"): "primary"}


def test_a_donor_whose_only_slot_is_primary_needs_a_primary_host_even_when_it_is_not_a_two_hander():
    assert plan.needs_primary(donor("p", ["PRIMARY"])) and plan.needs_primary(donor("t", ["PRIMARY", "SECONDARY"], two_hand=True))
    assert not plan.needs_primary(donor("w", ["PRIMARY", "SECONDARY"]))
    e = effect("proc", "proc", [donor("p", ["PRIMARY"])])
    result = place({"proc": [option("proc")]}, [("SECONDARY", "off")], {"off": host(["SECONDARY"])}, [e])
    assert noroom(result) == {("proc", "proc"): "primary"}


# ---- an item in an Any place hosts like any item of its slot type ------------------------------------------------------------------------


def test_an_item_in_an_any_place_hosts_by_its_own_slot_type():
    shield_effect = effect("sh", "click", [donor("aegis", ["BACK", "SECONDARY"])])
    hosts = {"axe": host(["PRIMARY", "SECONDARY"]), "shield": host(["SECONDARY"])}
    # no shield is worn in a SECONDARY place: the weapon in ANY1 is the only item that can carry a SECONDARY-slot effect
    result = place({"click": [option("sh")]}, [("PRIMARY", "shield"), ("ANY1", "axe")], {"axe": hosts["axe"], "shield": host(["CHEST"])}, [shield_effect])
    assert rows(result) == {("click", "sh"): ("ANY1", "axe")}


def test_a_weapon_in_an_any_place_carries_a_second_exaltation_of_a_weapon_slot_effect():
    bash = [effect("b1", "worn", [donor("t1", ["PRIMARY", "SECONDARY"])]), effect("b2", "worn", [donor("t2", ["PRIMARY", "SECONDARY"])])]
    hosts = {"main": host(["PRIMARY", "SECONDARY"]), "spare": host(["PRIMARY", "SECONDARY"])}
    result = place({"worn": [option("b1", 2.0), option("b2", 1.0)]}, [("PRIMARY", "main"), ("ANY2", "spare")], hosts, bash)
    assert sorted(r["p"] for r in result["rows"]) == ["ANY2", "PRIMARY"] and result["noroom"] == []


def test_a_primary_only_effect_is_not_placed_on_a_weapon_in_an_any_place_or_the_secondary_hand():
    bash = [effect("b1", "worn", [donor("t1", ["PRIMARY"], two_hand=True)]), effect("b2", "worn", [donor("t2", ["PRIMARY"], two_hand=True)])]
    hosts = {"main": host(["PRIMARY", "SECONDARY"]), "spare": host(["PRIMARY", "SECONDARY"]), "off": host(["PRIMARY", "SECONDARY"])}
    result = place({"worn": [option("b1", 2.0), option("b2", 1.0)]}, [("PRIMARY", "main"), ("SECONDARY", "off"), ("ANY2", "spare")], hosts, bash)
    assert rows(result) == {("worn", "b1"): ("PRIMARY", "main")}
    assert noroom(result) == {("worn", "b2"): "taken"}  # the one primary host is taken; the other two weapons cannot take it
    only_secondary = place({"worn": [option("b1")]}, [("SECONDARY", "off"), ("ANY2", "spare")], hosts, bash)
    assert noroom(only_secondary) == {("worn", "b1"): "primary"}


def test_an_item_worn_in_an_any_place_hosts_a_like_slot_effect_by_its_own_catalog_slots():
    e = effect("e1", "focus", [donor("d1", ["FINGER"])])
    result = place({"focus": [option("e1")]}, [("HEAD", "cap"), ("ANY1", "ring")], {"cap": host(["HEAD"]), "ring": host(["FINGER"])}, [e])
    assert rows(result) == {("focus", "e1"): ("ANY1", "ring")}


def test_a_kit_below_the_socket_tier_says_tier_whatever_else_is_wrong_and_a_donorless_option_says_donor():
    e = effect("e1", "proc", [donor("d1", ["PRIMARY"])])
    elsewhere = place({"proc": [option("e1")]}, [("CHEST", "chest")], {"chest": host(["CHEST"])}, [e], tier=3)
    assert noroom(elsewhere) == {("proc", "e1"): "tier"}  # not "slot": no host would help
    nobody = effect("e2", "click", [donor("d2", ["BACK"], ["WIZ"])])
    assert noroom(place({"click": [option("e2")]}, [("BACK", "b")], {"b": host(["BACK"])}, [nobody])) == {("click", "e2"): "donor"}
    assert noroom(place({"click": [option("e2")]}, [("BACK", "b")], {"b": host(["BACK"])}, [nobody], tier=1)) == {("click", "e2"): "tier"}


# ---- one effect of a kind for each host, the best total ------------------------------------------------------------------------------------


def test_no_host_carries_two_effects_of_one_kind():
    a, b = effect("a", "focus", [donor("da", ["CHEST"])]), effect("b", "focus", [donor("db", ["CHEST"])], focus_kind="improved_damage")
    result = place({"focus": [option("a", 2.0), option("b", 1.0)]}, [("CHEST", "chest")], {"chest": host(["CHEST"])}, [a, b])
    assert rows(result) == {("focus", "a"): ("CHEST", "chest")}  # the better one
    assert noroom(result) == {("focus", "b"): "taken"}


def test_effects_of_different_kinds_share_a_host():
    a, b = effect("a", "focus", [donor("da", ["PRIMARY"])]), effect("b", "proc", [donor("db", ["PRIMARY"])])
    result = place({"focus": [option("a")], "proc": [option("b")]}, [("PRIMARY", "sword")], {"sword": host(["PRIMARY"])}, [a, b])
    assert rows(result) == {("focus", "a"): ("PRIMARY", "sword"), ("proc", "b"): ("PRIMARY", "sword")}


def test_the_plan_is_the_placement_of_the_greatest_total_not_a_first_come_first_served_one():
    a = effect("a", "focus", [donor("da", ["CHEST", "HEAD"])])
    b = effect("b", "focus", [donor("db", ["CHEST"])], focus_kind="improved_damage")
    hosts = {"chest": host(["CHEST"]), "head": host(["HEAD"])}
    result = place({"focus": [option("a", 2.0), option("b", 1.0)]}, [("CHEST", "chest"), ("HEAD", "head")], hosts, [a, b])
    assert rows(result) == {("focus", "a"): ("HEAD", "head"), ("focus", "b"): ("CHEST", "chest")}  # a first-come placement would leave b with no room


def test_a_host_that_is_its_own_donor_wins_a_tie():
    e = effect("e1", "focus", [donor("self", ["CHEST"]), donor("other", ["CHEST"])])
    hosts = {"a": host(["CHEST"]), "self": host(["CHEST"])}
    result = place({"focus": [option("e1")]}, [("CHEST", "a"), ("ANY1", "self")], hosts, [e])
    assert rows(result) == {("focus", "e1"): ("ANY1", "self")} and result["rows"][0]["d"] == "self"


def test_rows_come_in_the_order_the_sockets_open_and_the_plan_is_the_same_every_time():
    effects = [effect("p", "proc", [donor("dp", ["PRIMARY"])]), effect("f", "focus", [donor("df", ["CHEST"])]), effect("c", "click", [donor("dc", ["CHEST"])])]
    options = {"proc": [option("p")], "focus": [option("f")], "click": [option("c")]}
    hosts = {"chest": host(["CHEST"]), "sword": host(["PRIMARY"])}
    kit = [("CHEST", "chest"), ("PRIMARY", "sword")]
    first = place(options, kit, hosts, effects)
    assert [r["k"] for r in first["rows"]] == ["focus", "click", "proc"]
    assert place(options, kit, hosts, effects) == first


def test_places_without_a_known_item_and_an_empty_kit_make_an_empty_plan():
    e = effect("e1", "focus", [donor("d1", ["CHEST"])])
    assert place({"focus": [option("e1")]}, [("CHEST", "unknown")], {}, [e]) == {"rows": [], "noroom": [{"k": "focus", "e": "e1", "w": "slot"}]}
    assert place({}, [], {}, []) == {"rows": [], "noroom": []}


# ---- a host has to be useful ----------------------------------------------------------------------------------------------------------------------


def test_a_focus_is_not_put_on_an_item_that_only_a_class_that_gains_nothing_can_wear():
    e = effect("e1", "focus", [donor("d1", ["BACK"])])
    hosts = {"monk_cloak": host(["BACK"], ["MNK"]), "pal_cloak": host(["BACK"], ["PAL"])}
    shares = {"PAL": 0.5}  # only the Paladin casts
    only_monk = place({"focus": [option("e1")]}, [("BACK", "monk_cloak")], hosts, [e], shares=shares)
    assert noroom(only_monk) == {("focus", "e1"): "class"}
    both = place({"focus": [option("e1")]}, [("BACK", "monk_cloak"), ("ANY1", "pal_cloak")], hosts, [e], shares=shares)
    assert rows(both) == {("focus", "e1"): ("ANY1", "pal_cloak")}


def test_a_proc_needs_a_melee_class_among_the_classes_that_can_use_the_host():
    e = effect("p", "proc", [donor("dp", ["PRIMARY"])])
    caster_weapon = host(["PRIMARY"], ["CLR"])
    melee_weapon = host(["PRIMARY"], ["WAR", "CLR"])
    classes = ("CLR", "WAR", "ENC")
    assert noroom(place({"proc": [option("p")]}, [("PRIMARY", "c")], {"c": caster_weapon}, [e], classes=classes)) == {("proc", "p"): "class"}
    assert rows(place({"proc": [option("p")]}, [("PRIMARY", "m")], {"m": melee_weapon}, [e], classes=classes)) == {("proc", "p"): ("PRIMARY", "m")}


def test_a_mana_click_needs_a_class_that_casts():
    e = effect("m", "click", [donor("dm", ["NECK"])], category="mana")
    ctx = context([e], classes=("WAR", "MNK", "BER"))
    ctx.mass.update({"WAR": 0.0, "MNK": 0.0, "BER": 0.0})
    result = plan.plan_kit({"click": [option("m")]}, [("NECK", "n")], {"n": host(["NECK"])}, ctx, ("WAR", "MNK", "BER"), "tank", 4)
    assert noroom(result) == {("click", "m"): "class"}


# ---- the assignment --------------------------------------------------------------------------------------------------------------------------------


def test_the_assignment_gives_the_greatest_total_weight_and_leaves_out_a_row_with_no_weight():
    assert plan._assign([]) == []
    assert plan._assign([[5, 0], [0, 0]]) == [0, None]
    assert plan._assign([[3, 2], [3, 0]]) == [1, 0]  # the first row takes the second column so that the second row has a place
    assert plan._assign([[4, 3, 0], [0, 0, 0], [2, 9, 0]]) == [0, None, 1]
    assert plan._assign([[1], [2]]) == [None, 0]


def test_every_no_room_reason_is_explained():
    assert set(plan.REASONS) == {"donor", "primary", "slot", "class", "tier", "taken"}
    assert all(plan.REASONS.values())
