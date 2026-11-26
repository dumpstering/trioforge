"""The Lore rule of the procs: a Lore item that is worn anywhere in the kit is not a donor for a hand it is not in.

A Lore item is one physical copy. The copy a kit wears (in a hand, an Any place or any other place) is the one it wears: it cannot also be moved onto another item as a donor. Its own proc,
when a hand wears it, still counts there (a native proc is the copy that is worn). The rule is held by the table (:meth:`~trioforge.model.procs.ProcTable.sources`, ``candidates`` and ``best``),
by the evaluator (:func:`trioforge.model.formulas.evaluate` gives the table the Lore items the kit wears), by the builder's program (it must give the evaluator's value for the kit it chooses) and
by the pruning (a Lore donor is never dropped for another item and drops none).
"""

from fractions import Fraction

from solver_helpers import kit_from_groups
from trioforge.solver.model import BuildOptions
from test_procs_model import DMG, SWING_ONE_HAND, blade, donor, effect, hands, profile, table, worth  # noqa: F401  (``profile`` is a fixture)

HALF = Fraction(1, 2)
ALL = frozenset({"relic", "gem"})


def lore_table():
    """The effect "rare" (900) carried by the Lore relic and by the plain club, "good" (500) by the Lore gem and "poor" (100) by the plain rag."""
    return table(
        [effect("rare", 900), effect("good", 500), effect("poor", 100)],
        [donor("rare", "relic", lore=True), donor("rare", "club"), donor("good", "gem", lore=True), donor("poor", "rag")],
    )


# ---- the table ------------------------------------------------------------------------------------------------------------------


def test_a_lore_donor_that_is_worn_is_not_a_source_for_a_hand_it_is_not_in():
    t = lore_table()
    host = blade("axe")
    assert t.sources(host, "PRIMARY", "e-rare") == ("club", "relic")
    assert t.sources(host, "PRIMARY", "e-rare", frozenset({"relic"})) == ("club",)  # relic is worn somewhere: its copy is not free
    assert t.sources(host, "PRIMARY", "e-rare", frozenset({"club"})) == ("club", "relic")  # the rule names Lore items: a plain donor has a second copy


def test_a_native_proc_is_the_copy_that_is_worn_whatever_is_worn():
    t = lore_table()
    assert t.sources(blade("relic"), "PRIMARY", "e-rare", frozenset({"relic"})) == ("relic",)


def test_the_candidates_of_a_hand_run_to_the_first_proc_that_nothing_can_block_and_hold_every_blockable_one_before_it():
    t = lore_table()
    assert [entry.effect for entry in t.candidates(blade("axe"), "PRIMARY")] == ["e-rare"]  # rare has a plain donor (the club): nothing blocks it, and nothing after it is needed
    two_lore = table(
        [effect("rare", 900), effect("good", 500), effect("poor", 100)], [donor("rare", "relic", lore=True), donor("good", "gem", lore=True), donor("poor", "rag")]
    )
    assert [entry.effect for entry in two_lore.candidates(blade("axe"), "PRIMARY")] == ["e-rare", "e-good", "e-poor"]  # the first two can be blocked by a worn copy, the third cannot
    plain = table([effect("rare", 900), effect("poor", 100)], [donor("rare", "club"), donor("poor", "rag")])
    assert [entry.effect for entry in plain.candidates(blade("axe"), "PRIMARY")] == ["e-rare"]
    only_lore = table([effect("rare", 900), effect("poor", 100)], [donor("rare", "relic", lore=True), donor("poor", "rag")])
    assert [entry.effect for entry in only_lore.candidates(blade("axe"), "PRIMARY")] == ["e-rare", "e-poor"]


# ---- the best pair of hands -----------------------------------------------------------------------------------------------------


def test_a_hand_counts_a_proc_from_a_lore_donor_that_is_not_worn_and_the_next_proc_when_the_donor_is_worn_somewhere():
    t = table([effect("rare", 900), effect("poor", 100)], [donor("rare", "relic", lore=True), donor("poor", "rag")])
    main, off = t.best(blade("axe"), None, HALF)
    assert main is not None and (main.effect, main.donor, main.mode) == ("e-rare", "relic", "h") and off is None
    main, off = t.best(blade("axe"), None, HALF, frozenset({"relic"}))  # the kit wears the relic in an Any place, which swings nothing
    assert main is not None and (main.effect, main.donor) == ("e-poor", "rag")
    alone = table([effect("rare", 900)], [donor("rare", "relic", lore=True)])
    main, off = alone.best(blade("axe"), None, HALF, frozenset({"relic"}))
    assert main is None and off is None


def test_the_lore_item_worn_in_the_other_hand_counts_its_own_proc_and_is_no_donor_for_the_first():
    alone = table([effect("rare", 900)], [donor("rare", "relic", lore=True)])
    main, off = alone.best(blade("axe"), blade("relic", tier=3), HALF)  # (the hands are worn: no list of the kit is needed)
    assert main is None  # (it was the donor of the main hand while the rule allowed it)
    assert off is not None and (off.donor, off.mode) == ("relic", "n")
    main, off = alone.best(blade("relic"), blade("axe"), HALF)
    assert main is not None and (main.donor, main.mode) == ("relic", "n") and off is None


def test_two_lore_donors_that_are_not_worn_supply_two_hands_and_one_that_is_worn_supplies_none():
    t = table([effect("rare", 900), effect("good", 500)], [donor("rare", "relic", lore=True), donor("good", "gem", lore=True)])
    main, off = t.best(blade("axe"), blade("sword"), HALF)
    assert (main.effect, off.effect) == ("e-rare", "e-good")
    main, off = t.best(blade("axe"), blade("sword"), HALF, frozenset({"relic"}))
    assert (main.effect, off) == ("e-good", None)


def test_the_best_pair_is_found_when_the_blocked_best_makes_the_other_donor_the_only_one():
    # relic (rare) and gem (rare, a second Lore donor of the same proc) supply the same proc; with the relic worn the gem is the only source of both hands, and one copy supplies one hand
    t = table([effect("rare", 900)], [donor("rare", "relic", lore=True), donor("rare", "gem", lore=True)])
    main, off = t.best(blade("axe"), blade("sword"), HALF)
    assert main is not None and off is not None and main.donor != off.donor
    main, off = t.best(blade("axe"), blade("sword"), HALF, frozenset({"relic"}))
    assert main is not None and main.donor == "gem" and off is None


# ---- the evaluator ----------------------------------------------------------------------------------------------------------------


def test_the_evaluator_gives_the_table_the_lore_items_the_kit_wears_in_any_place(profile):
    t = table([effect("rare", 900)], [donor("rare", "relic", lore=True)])
    swing = DMG * SWING_ONE_HAND
    kit = hands(blade("axe"))
    assert worth(profile, kit, "1h-shield", t).parts["WEAPON"] == swing + DMG * Fraction(900, 600)
    kit_with_relic_in_the_bag = kit_from_groups({"PRIMARY": [blade("axe")], "ANY": [blade("relic", slots=("ANY",), lore=True)]})
    assert worth(profile, kit_with_relic_in_the_bag, "1h-shield", t).parts["WEAPON"] == swing  # (the relic in an Any place scores no swing and cannot be a donor)
    in_the_hand = hands(blade("relic", lore=True))
    assert worth(profile, in_the_hand, "1h-shield", t).parts["WEAPON"] == swing + DMG * Fraction(900, 600)  # (worn in the hand it counts natively)


# ---- the program ----------------------------------------------------------------------------------------------------------------


def program_pool(hp):
    """A two-hander that hosts the proc and a Lore relic that carries it and can also be worn in an Any place for ``hp`` hit points."""
    from test_procs_milp import blade as milp_blade

    maul = milp_blade("maul", dmg=60, delay=40, two=True, classes=("WAR", "SHM", "ENC"))
    relic = milp_blade("relic", dmg=10, lore=True, stats={"HP": hp}, slots=("PRIMARY", "SECONDARY", "ANY"))
    return [maul, relic]


def test_the_program_wears_a_lore_donor_in_an_any_place_only_when_its_stats_are_worth_more_than_its_proc_on_the_two_hander():
    from test_procs_milp import agree, instance, make_table

    made = make_table({"rare": 600}, [("rare", "relic", ("PRIMARY", "SECONDARY", "ANY"), ("WAR", "SHM", "ENC"))], lore={"relic"})
    for hp, worn in ((50, False), (500, True)):
        milp, best = agree(made, instance(program_pool(hp), "2h", any_rule="all"))
        assert milp.info["binaries"]["proc"] > 0
        assert any(name.startswith("proc.worn") for name in milp.row_names)
        decoded = milp.decode(__import__("trioforge.solver._highs", fromlist=["solve_milp"]).solve_milp(milp).x)
        wears_relic = any(item.key == "relic" for items in decoded.groups.values() for item in items)
        assert wears_relic is worn, (hp, decoded.groups)


def test_the_program_agrees_with_the_evaluator_when_a_lore_donor_is_worn_in_the_off_hand_of_a_dual_wield_pool():
    from test_procs_milp import agree, blade as milp_blade, instance, make_table

    made = make_table({"rare": 600, "good": 400}, [("rare", "relic", ("PRIMARY", "SECONDARY"), ("WAR", "SHM", "ENC")), ("good", "gem", ("PRIMARY", "SECONDARY"), ("WAR", "SHM", "ENC"))], lore={"relic", "gem"})
    items = [milp_blade("axe", dmg=20), milp_blade("sword", dmg=20), milp_blade("relic", dmg=10, lore=True), milp_blade("gem", dmg=10, lore=True)]
    agree(made, instance(items, "dw"))


def test_a_lore_donor_is_never_dropped_for_another_item_and_drops_none():
    from test_procs_milp import blade as milp_blade, instance, make_table

    from trioforge.solver.prune import prune

    made = make_table({"rare": 600}, [("rare", "relic", ("PRIMARY", "SECONDARY", "ANY"), ("WAR", "SHM", "ENC"))], lore={"relic"})
    options = BuildOptions(any_rule="all", haste_assumed=0, procs=made.table)
    slots = ("PRIMARY", "SECONDARY", "ANY")
    # a better item that can take the relic's proc from it is at least as good as the relic in every dimension but the Lore ones: the relic stays, since a kit that wears it has no donor
    better = milp_blade("better", dmg=30, stats={"HP": 100}, slots=slots)
    relic = milp_blade("relic", dmg=10, lore=True, stats={"HP": 10}, slots=slots)
    inst = instance([better, relic], "1h-shield", any_rule="all")
    kept = prune(inst.items, inst.profile, 4, "1h-shield", None, options)
    assert {item.key for item in kept} == {"better", "relic"}
    # and the relic, better than a plain item in every way, does not drop it: a kit that wears the plain one leaves the relic's copy free for the proc
    strong = milp_blade("relic", dmg=30, lore=True, stats={"HP": 100}, slots=slots)
    weak = milp_blade("weak", dmg=5, stats={}, slots=slots)
    inst = instance([strong, weak], "1h-shield", any_rule="all")
    kept = prune(inst.items, inst.profile, 4, "1h-shield", None, options)
    assert {item.key for item in kept} == {"relic", "weak"}
    # with no Lore donor the same pools are pruned as they were: the better item drops the relic, and the strong item the weak one
    plain = make_table({"rare": 600}, [("rare", "relic", ("PRIMARY", "SECONDARY", "ANY"), ("WAR", "SHM", "ENC"))])
    options = BuildOptions(any_rule="all", haste_assumed=0, procs=plain.table)
    kept = prune([better, milp_blade("relic", dmg=10, stats={"HP": 10}, slots=slots)], inst.profile, 4, "1h-shield", None, options)
    assert {item.key for item in kept} == {"better"}


def test_the_donor_a_single_swinging_hand_records_is_never_a_lore_item_the_kit_wears():
    """F3: with one hand swinging, the entry kept the donor of the list of every proc (the smallest key) whatever the kit wore: a Lore item worn elsewhere could be named as the donor."""
    t = table([effect("rare", 900), effect("poor", 100)], [donor("rare", "arc", lore=True), donor("rare", "club"), donor("poor", "rag")])
    main, off = t.best(blade("axe"), None, HALF)
    assert (main.effect, main.donor, main.mode) == ("e-rare", "arc", "h") and off is None  # (nothing worn: the smallest key supplies it, as before)
    for worn in (frozenset({"arc"}), frozenset({"arc", "other"})):
        main, off = t.best(blade("axe"), None, HALF, worn)
        assert (main.effect, main.donor, main.mode) == ("e-rare", "club", "h") and main.donor not in worn and off is None
        main, off = t.best(None, blade("axe"), HALF, worn)  # the off hand alone
        assert main is None and (off.effect, off.donor, off.mode) == ("e-rare", "club", "h") and off.donor not in worn
    only_lore = table([effect("rare", 900), effect("poor", 100)], [donor("rare", "arc", lore=True), donor("poor", "rag")])
    main, off = only_lore.best(blade("axe"), None, HALF, frozenset({"arc"}))
    assert (main.effect, main.donor) == ("e-poor", "rag")  # (the proc whose only source is worn is not counted at all, and the next one is)
    native = table([effect("rare", 900)], [donor("rare", "arc", lore=True)])
    main, off = native.best(blade("arc"), None, HALF, frozenset({"arc"}))
    assert (main.donor, main.mode) == ("arc", "n")  # (a native proc is the copy that is worn)
