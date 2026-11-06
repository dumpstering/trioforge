"""Tests for the effects of the catalog's items as records: the wiki's effect text, click modes, source cost, and the donors of an effect."""

from trioforge.effects import donors as dn
from trioforge.effects import judgment
from trioforge.effects import spells as sp

J = judgment.default()


def test_parse_raw_levels_cooldown_rate():
    r = dn.parse_raw("Effect: Firestrike (Clicky, Must Equip, Casting Time: Instant, Cooldown: 120 seconds) at Level 49")
    assert r["cast_level"] == 49 and r["cooldown_s"] == 120 and r["req_level"] is None
    r = dn.parse_raw("Effect: Spirit Strike (Combat, Rate +50%) at Level 35")
    assert r["rate_pct"] == 50 and r["cast_level"] == 35
    r = dn.parse_raw("Effect: Allure of Death (Any Slot/Can Equip, Casting Time: Instant) req. level 20")
    assert r["req_level"] == 20 and r["cast_level"] is None
    r = dn.parse_raw("Effect: Levitation (Any Slot, Casting Time: 4.0)")
    assert r["cast_time_s"] == 4.0


def test_parse_raw_reads_a_reduced_proc_rate_with_its_sign():
    assert dn.parse_raw("Effect: Supernova (Combat, Rate -75%, Req Level 45)")["rate_pct"] == -75
    assert dn.parse_raw("Effect: Supernova (Combat, Rate -75%) at Level 45")["rate_pct"] == -75
    assert dn.parse_raw("Effect: Spirit Strike (Combat, Rate +50%) at Level 35")["rate_pct"] == 50


def test_click_mode_any_slot_is_carry():
    assert dn.click_mode("Effect: Levitation (Any Slot, Casting Time: 4.0)") == ("carry", False)
    assert dn.click_mode("Effect: Blaze (Any Slot/Can Equip, Casting Time: Instant) at Level 35") == ("carry", False)


def test_click_mode_must_equip_is_exalt():
    assert dn.click_mode("Effect: Earthquake (Must Equip, Casting Time: Instant) at Level 49") == ("exalt", False)
    assert dn.click_mode("Effect: Firestrike (Clicky, Must Equip, Casting Time: Instant, Cooldown: 120 seconds)") == ("exalt", False)


def test_click_mode_unspecified_and_can_equip_are_exalt_flagged():
    assert dn.click_mode("Effect: Word of Healing (Charge Clicky, Casting Time: Instant)") == ("exalt", True)
    assert dn.click_mode("Effect: Lower Element I (Clicky, Can Equip, Casting Time: Instant) at Level 20") == ("exalt", True)


def source(drops=(), sold=(), quests=(), crafted=()):
    return {"sources": {"drops": [{"zone": z, "npcs": []} for z in drops], "sold_by": [{"zone": "X", "npc": "n"} for _ in sold], "quests": list(quests), "crafted": list(crafted)}}


def test_access_cost_order():
    cost = lambda **kw: dn.access_cost(source(**kw), J)  # noqa: E731
    vendor, craft, quest = cost(sold=[1]), cost(crafted=["x"]), cost(quests=["q"])
    common, raid, nothing = cost(drops=["Lower Guk"]), cost(drops=["Plane of Hate"]), cost()
    assert vendor < quest <= craft < common < raid < nothing
    assert cost(drops=["Nagafen's Lair"]) == raid  # a raid zone by name


def test_usable_by_trio():
    assert dn.usable_by({"classes": ["ALL"]}, ["PAL", "MNK", "BER"]) == ["PAL", "MNK", "BER"]
    assert dn.usable_by({"classes": ["CLR", "PAL"]}, ["PAL", "MNK", "BER"]) == ["PAL"]
    assert dn.usable_by({"classes": ["WIZ"]}, ["PAL", "MNK", "BER"]) == []


# ---- the records ------------------------------------------------------------------------------------------------------------------


def fx(spa, base=0, limit=0, formula=100, maximum=0):
    return [1, spa, base, limit, formula, maximum]


def row(sid, name, effects, ben=0, tgt=5, dur=(0, 0), lv=None):
    return {"id": sid, "name": name, "cast_ms": 0, "mana": 0, "dur": list(dur), "ben": ben, "res": 0, "tgt": tgt, "lv": lv or {}, "fx": effects}


def item(key, effects, slots=("PRIMARY",), classes=("ALL",), skill=None, tier_rule="drop", drops=("Lower Guk",)):
    return {
        "key": key, "name": f"Item {key}", "slots": list(slots), "classes": list(classes), "tier_rule": tier_rule, "weapon": {"skill": skill} if skill else None,
        "effects": [{"kind": kind, "name": name, "raw": raw} for kind, name, raw in effects], "evidence": {"level": "wiki"},
        "sources": {"drops": [{"zone": z, "npcs": []} for z in drops], "sold_by": [], "quests": [], "crafted": []},
    }  # fmt: skip


def book(*rows):
    return sp.SpellBook(list(rows), 50)


def test_the_cooldown_cast_time_and_required_level_stay_with_each_item_of_a_group():
    # finding 3 of the review: the text of one copy used to speak for the whole group
    spells = book(row(1, "Firestrike", [fx(0, -300)]))
    a = item("a", [("click", "Firestrike", "Effect: Firestrike (Must Equip, Casting Time: Instant, Cooldown: 120 seconds) at Level 49")])
    b = item("b", [("click", "Firestrike", "Effect: Firestrike (Must Equip, Casting Time: 3.0, Cooldown: 600 seconds) at Level 49 req. level 55")])
    effects, misses = dn.build_effects([a, b], spells, J)
    assert misses == [] and len(effects) == 1
    donors = {d["key"]: d for d in effects[0]["items"]}
    assert (donors["a"]["cooldown_s"], donors["a"]["cast_time_s"], donors["a"]["instant"], donors["a"]["req_level"]) == (120, 0.0, True, None)
    assert (donors["b"]["cooldown_s"], donors["b"]["cast_time_s"], donors["b"]["instant"], donors["b"]["req_level"]) == (600, 3.0, False, 55)


def test_clicks_that_differ_in_mode_or_cast_level_are_separate_effects_and_ids_are_in_order():
    spells = book(row(1, "Levitate", [fx(57, 1)], ben=1, dur=(3, 10)))
    a = item("a", [("click", "Levitate", "Effect: Levitate (Any Slot, Casting Time: 4.0)")])
    b = item("b", [("click", "Levitate", "Effect: Levitate (Must Equip, Casting Time: 4.0)")])
    c = item("c", [("click", "Levitate", "Effect: Levitate (Must Equip, Casting Time: 4.0) at Level 10")])
    effects, _ = dn.build_effects([a, b, c], spells, J)
    assert [e["id"] for e in effects] == ["e000", "e001", "e002"]
    assert sorted(((e.get("mode"), e["cast_level"] or 0) for e in effects)) == [("carry", 0), ("exalt", 0), ("exalt", 10)]


def test_an_item_with_no_slot_is_a_donor_row_that_is_not_eligible():
    spells = book(row(1, "Ice Comet", [fx(0, -800)]))
    scroll = item("s", [("click", "Ice Comet", "Effect: Ice Comet (Must Equip, Casting Time: Instant)")], slots=())
    effects, _ = dn.build_effects([scroll], spells, J)
    assert effects[0]["items"][0]["eligible"] is False


def test_a_name_with_no_spell_is_a_miss_and_an_alias_is_found():
    spells = book(row(1, "Complete Heal", [fx(0, 7000)], ben=1))
    a = item("a", [("click", "Complete Healing", "Effect: Complete Healing (Must Equip, Casting Time: Instant)"), ("click", "Cazic Gate", "Effect: Cazic Gate (Must Equip)")])
    effects, misses = dn.build_effects([a], spells, J)
    assert misses == [{"kind": "click", "name": "Cazic Gate"}]
    assert {e["name"]: e["category"] for e in effects} == {"Complete Healing": "heal", "Cazic Gate": "unresolved"}


def test_an_offensive_effect_with_no_trigger_wording_on_a_weapon_is_an_inferred_proc_and_unverified():
    spells = book(row(1, "Stun", [fx(21, 2000)]))
    weapon = item("w", [("other", "Stun", "Effect: Stun")], slots=("PRIMARY",))
    ring = item("r", [("other", "Stun", "Effect: Stun (Must Equip)")], slots=("FINGER",))
    effects, _ = dn.build_effects([weapon, ring], spells, J)
    by_item = {e["items"][0]["key"]: e for e in effects}
    assert by_item["w"].get("kind_inferred") == "proc" and "inferred" in by_item["w"]["unverified"] and dn.kind_of(by_item["w"]) == "proc"
    assert "kind_inferred" not in by_item["r"] and dn.kind_of(by_item["r"]) == "click"


def test_unverified_reasons_ambiguous_names_equip_wording_and_ykesha():
    spells = book(row(1, "Rampage", [fx(0, -5)]), row(2, "Rampage", [fx(0, -9)]), row(3, "Ykesha", [fx(0, -75), fx(21, 1000, 500)]))
    a = item("a", [("proc", "Rampage", "Effect: Rampage (Combat, Rate +10%)"), ("click", "Rampage", "Effect: Rampage (Charge Clicky, Casting Time: Instant)")])
    y = item("y", [("proc", "Ykesha", "Effect: Ykesha (Combat, Rate +10%)")])
    effects, _ = dn.build_effects([a, y], spells, J)
    reasons = {(e["kind"], e["name"]): e["unverified"] for e in effects}
    assert reasons[("proc", "Rampage")] == ["ambiguous"]
    assert reasons[("click", "Rampage")] == ["ambiguous", "equip"]
    assert reasons[("proc", "Ykesha")] == ["description"]
    ykesha = next(e for e in effects if e["name"] == "Ykesha")
    assert ykesha["category"] == "damage" and ykesha["magnitude"] == 75  # stays a small damage proc, as the spell data says


def test_a_focus_record_has_its_family_tier_and_limits():
    haste = row(1, "Spell Haste II", [fx(127, 15), fx(134, 44, 5)], ben=1)
    effects, _ = dn.build_effects([item("f", [("focus", "Spell Haste II", "Effect: Spell Haste II (Worn)")], slots=("CHEST",))], book(haste), J)
    focus = effects[0]["focus"]
    assert (focus["family"], focus["tier"], focus["kind"]) == ("Spell Haste", 2, "spell_haste")
    assert focus["limits"]["max_level"] == 44 and effects[0]["category"] == "focus_spell_haste"


def test_a_donor_knows_its_arrival_tier_and_whether_it_is_a_two_hander():
    spells = book(row(1, "Ignite", [fx(0, -40)]))
    two = item("t", [("proc", "Ignite", "Effect: Ignite (Combat)")], skill="2H Slashing", tier_rule="drop")
    quest = item("q", [("proc", "Ignite", "Effect: Ignite (Combat)")], tier_rule="fixed0", drops=())
    donors = {d["key"]: d for d in dn.build_effects([two, quest], spells, J)[0][0]["items"]}
    assert donors["t"]["two_hand"] is True and donors["t"]["arrival"] == 4
    assert donors["q"]["two_hand"] is False and donors["q"]["arrival"] == 0


def test_the_real_catalog_gives_the_effects_the_analysis_found():
    import json
    from pathlib import Path

    catalog = json.loads((Path(__file__).resolve().parents[2] / "derived" / "catalog.json").read_text(encoding="utf-8"))
    pool = [i for i in catalog["items"] if i["evidence"]["level"] == "wiki"]
    effects, misses = dn.build_effects(pool, sp.SpellBook.load(), J)
    # 9 misses on the catalog of 2026-10-14, 17 on the one of 2026-10-27: the 8 more are effects whose name is no spell of the client, from items that came or changed in that data. New items: Schemer's
    # Guise (Illusion: Half Dark Elf), Signet Ring of Lord Everling and The Unbreakable Word (Mana Preservation III), Doll's Fang (Lifedraw), Gamblers Gambit (Supernova). Changed items: Unfinished Brass
    # Trumpet (Brass Resonance 1, a focus the item did not have), Alluring Horn (Brass Resonance 9) and Unicorn Horn (Wind Resonance 12), which now name a focus where they gave an instrument mod, and
    # Packmaster's Lash, whose proc is now "Choking" and was "Choke"
    assert 400 <= len(effects) <= 450 and len(misses) <= 17
    by_name = {(e["kind"], e["name"]): e for e in effects}
    assert by_name[("click", "Pillage Enchantment")]["category"] == "dispel" and by_name[("click", "Pillage Enchantment")]["magnitude"] == 4
    assert by_name[("proc", "Ykesha")]["unverified"] == ["description"]
    assert by_name[("focus", "Spell Haste II")]["focus"]["limits"]["max_level"] == 44


# ---- the fix round ---------------------------------------------------------------------------------------------------------------


def test_a_click_is_one_record_whatever_the_wording_of_each_copy_and_the_unclear_wording_is_a_mark_on_the_copy():
    # review finding 7: the verification flag was part of the key, so one effect became two records and could take two click sockets
    spells = book(row(1, "Levitate", [fx(57, 1)], ben=1, dur=(3, 10)))
    clear = item("clear", [("click", "Levitate", "Effect: Levitate (Must Equip, Casting Time: 4.0)")], slots=("BACK",))
    vague = item("vague", [("click", "Levitate", "Effect: Levitate (Clicky, Can Equip, Casting Time: 4.0)")], slots=("FEET",))
    effects, _ = dn.build_effects([clear, vague], spells, J)
    assert len(effects) == 1 and effects[0]["mode"] == "exalt"
    assert {d["key"]: d["mode_flag"] for d in effects[0]["items"]} == {"clear": False, "vague": True}
    assert effects[0]["unverified"] == ["equip"]  # unverified as soon as one copy is unclear
    assert dn.build_effects([clear], spells, J)[0][0]["unverified"] == []


def test_a_carry_click_and_an_exalt_click_are_still_two_records():
    spells = book(row(1, "Levitate", [fx(57, 1)], ben=1, dur=(3, 10)))
    a = item("a", [("click", "Levitate", "Effect: Levitate (Any Slot, Casting Time: 4.0)")])
    b = item("b", [("click", "Levitate", "Effect: Levitate (Must Equip, Casting Time: 4.0)")])
    assert sorted(e["mode"] for e in dn.build_effects([a, b], spells, J)[0]) == ["carry", "exalt"]


def test_an_unlabelled_offensive_effect_is_told_apart_copy_by_copy_so_that_a_record_never_mixes_kinds():
    # review finding 8: the inference "a weapon copy is a proc" was applied to the whole record
    spells = book(row(1, "Zap", [fx(0, -300)]))
    sword = item("sword", [("other", "Zap", "Effect: Zap")], slots=("PRIMARY",))
    bow = item("bow", [("other", "Zap", "Effect: Zap")], slots=("RANGE",))
    cloak = item("cloak", [("other", "Zap", "Effect: Zap (Must Equip)")], slots=("BACK",))
    effects, _ = dn.build_effects([sword, bow, cloak], spells, J)
    assert len(effects) == 2 and [e["id"] for e in effects] == ["e000", "e001"]
    click, proc = effects
    assert dn.kind_of(click) == "click" and [d["key"] for d in click["items"]] == ["cloak"] and click["unverified"] == []
    assert dn.kind_of(proc) == "proc" and proc.get("kind_inferred") == "proc" and sorted(d["key"] for d in proc["items"]) == ["bow", "sword"]
    assert proc["unverified"] == ["inferred"] and "mode" not in proc


def test_an_unlabelled_offensive_effect_on_weapons_only_is_one_proc_record_and_on_other_items_only_one_click_record():
    spells = book(row(1, "Zap", [fx(0, -300)]))
    assert [dn.kind_of(e) for e in dn.build_effects([item("w", [("other", "Zap", "Effect: Zap")], slots=("PRIMARY",))], spells, J)[0]] == ["proc"]
    assert [dn.kind_of(e) for e in dn.build_effects([item("c", [("other", "Zap", "Effect: Zap")], slots=("BACK",))], spells, J)[0]] == ["click"]


def test_a_recast_time_is_not_a_cast_time():
    # review finding 9
    assert dn.parse_raw("Effect: Zap (Must Equip, Recast Time: 30, Casting Time: 3.0)")["cast_time_s"] == 3.0
    assert dn.parse_raw("Effect: Zap (Must Equip, Recast Time: 30)")["cast_time_s"] is None
    assert dn.parse_raw("Effect: Zap (Must Equip, recast time: instant)")["cast_time_s"] is None
    assert dn.parse_raw("Effect: Zap (Cast Time: 2.5)")["cast_time_s"] == 2.5


def test_an_item_with_no_slot_list_is_an_item_with_no_slot_and_does_not_stop_the_build():
    # review finding 10: set(None) raised
    spells = book(row(1, "Zap", [fx(0, -300)]))
    nowhere = item("n", [("other", "Zap", "Effect: Zap")], slots=())
    nowhere["slots"] = None
    effects, _ = dn.build_effects([nowhere, item("c", [("other", "Zap", "Effect: Zap")], slots=("BACK",))], spells, J)
    donors = {d["key"]: d for e in effects for d in e["items"]}
    assert donors["n"]["slots"] == [] and donors["n"]["eligible"] is False and donors["c"]["eligible"] is True


# ---- a donor is eligible only where the item table has the item -----------------------------------------------------------------------------------


def test_an_ammo_only_item_with_a_click_is_a_donor_row_that_is_not_eligible_and_never_reaches_the_shared_document():
    # data-2026-10-27: mounts that sit in the ammo slot (Black Drum, Brown Rope Bridle) listed as donors the item table (wearables only) does not have
    from trioforge.effects import files, layer
    from trioforge.precompute import grid

    spells = book(row(1, "Summon Horse", [fx(0, 1)], ben=1))
    mount = item("w60125", [("click", "Summon Horse", "Effect: Summon Horse (Must Equip, Casting Time: Instant)")], slots=("AMMO",))
    belt = item("w1", [("click", "Summon Horse", "Effect: Summon Horse (Must Equip, Casting Time: Instant)")], slots=("WAIST",))
    effects, _ = dn.build_effects([mount, belt], spells, J)
    assert len(effects) == 1
    assert {d["key"]: d["eligible"] for d in effects[0]["items"]} == {"w60125": False, "w1": True}  # (the ammo row is kept)
    assert "AMMO" not in grid.WEARABLE_SLOTS
    catalog_items = {i["key"]: {"classes": i["classes"], "slots": i["slots"], "name": i["name"]} for i in (mount, belt)}
    built = files.Built(J, effects, [], layer.build_context(effects, spells, J), catalog_items, "data-x", "r", "CC BY-SA 4.0", "a", "0" * 64)
    shared = files.shared_document(built)
    assert [e["d"] for e in shared["effects"]] == [[["w1", dn.access_cost(belt, J)]]]


def test_a_donor_is_eligible_by_the_same_slots_as_an_item_of_the_item_table():
    # one predicate: the donor rule and the item table's rule are the same constant, so they cannot drift apart
    from trioforge.precompute import grid

    spells = book(row(1, "Summon Horse", [fx(0, 1)], ben=1))
    for slot in sorted(grid.WEARABLE_SLOTS | {"AMMO", "CHARM", "POWERSOURCE"}):
        carrier = item("k", [("click", "Summon Horse", "Effect: Summon Horse (Must Equip, Casting Time: Instant)")], slots=(slot,))
        donor = dn.build_effects([carrier], spells, J)[0][0]["items"][0]
        assert donor["eligible"] is bool(grid.WEARABLE_SLOTS & {slot}), slot
    mixed = item("k", [("click", "Summon Horse", "Effect: Summon Horse (Must Equip, Casting Time: Instant)")], slots=("AMMO", "FEET"))
    assert dn.build_effects([mixed], spells, J)[0][0]["items"][0]["eligible"] is True  # (one wearable slot is enough, as in the item table)


# ---- an effect labelled focus that has no focus effect is not a focus row ---------------------------------------------------------------------------


def test_an_effect_labelled_focus_with_no_focus_effect_stays_a_record_but_reaches_no_shared_row_and_no_list():
    # data-2026-10-27: "Focus Effect: See Invisible" (Scaredy Cap) was a shared row of kind focus with no "f", which the site's reader refuses
    from trioforge.effects import files, layer

    spells = book(row(1, "See Invisible", [fx(13, 1)], ben=1, dur=(3, 10)))
    cap = item("w60256", [("focus", "See Invisible", "Effect: See Invisible (Worn)")], slots=("HEAD",))
    effects, _ = dn.build_effects([cap], spells, J)
    assert len(effects) == 1 and effects[0]["kind"] == "focus" and "focus" not in effects[0]
    assert effects[0]["note"] == "labelled focus but has no focus effect id" and effects[0]["items"][0]["key"] == "w60256"  # (the analysis still sees it)
    ctx = layer.build_context(effects, spells, J)
    built = files.Built(J, effects, [], ctx, {"w60256": {"classes": ["ALL"], "slots": ["HEAD"], "name": "Scaredy Cap"}}, "data-x", "r", "CC BY-SA 4.0", "a", "0" * 64)
    assert files.shared_document(built)["effects"] == []
    for classes in (["PAL", "MNK", "BER"], ["CLR", "SHD", "SHM"]):
        for role in ("balanced", "tank", "melee", "caster"):
            assert not any(option["effect"] == effects[0]["id"] for options in layer.layer(classes, role, ctx).values() for option in options)


def test_a_list_of_a_trio_never_names_an_ammo_only_donor():
    # data-2026-10-27: 16 trio files named Black Drum (Summon Drogmor) and Brown Rope Bridle (Summon Horse) in their click lists
    from trioforge.effects import layer

    spells = book(row(1, "Summon Horse", [fx(57, 1)], ben=1, dur=(3, 10)))
    text = "Effect: Summon Horse (Must Equip, Casting Time: Instant)"
    mount = item("w60125", [("click", "Summon Horse", text)], slots=("AMMO",))
    belt = item("w1", [("click", "Summon Horse", text)], slots=("WAIST",), drops=("Plane of Hate",))
    effects, _ = dn.build_effects([mount, belt], spells, J)
    ctx = layer.build_context(effects, spells, J)
    named = []
    for classes in (["PAL", "MNK", "BER"], ["CLR", "SHD", "SHM"], ["WIZ", "ENC", "MAG"]):
        for role in ("balanced", "tank", "melee", "caster"):
            for options in layer.layer(classes, role, ctx, top=False).values():
                for option in options:
                    named.extend([option["donor"], *option["others"]])
    assert "w60125" not in named and "w1" in named  # (the belt is offered, so the test is not empty)
