"""The weapon procs in the program: the builder, the truthful solve and the pruning against a brute force over every legal kit (stage 1b of the builds, fix round 2).

The tables are made by ``score.proc_table`` from invented effect records (the Lore flags and the donors are the records', never a hand-set count of copies). The brute force values every
legal kit with the evaluator without procs and adds the proc part of its own: the rule "one physical copy supplies one hand", and the Lore rule "a Lore item the kit wears is no donor",
written out again here, by enumeration of the donor copies (``proc_part``), and not by :meth:`trioforge.model.procs.ProcTable.best`; the program's optimum, the evaluator's value of every kit and the pruned pool's optimum must all be that.
Items, effects and classes are invented.
"""

import itertools
import random
from fractions import Fraction

import pytest
from solver_helpers import Instance, Space, kit_from_groups, make_item, make_profile
from test_procs_value import J, damage, sitem, world

from trioforge.effects import score
from trioforge.model import formulas as fm
from trioforge.model.items import SLOT_INSTANCES, WeaponVec
from trioforge.solver._highs import solve_milp
from trioforge.solver.haste import solve_scenario
from trioforge.solver.model import BuildOptions, build_milp
from trioforge.solver.prune import prune

TRIO = ("WAR", "SHM", "ENC")
BOTH = ("PRIMARY", "SECONDARY")
REL = 1e-9
SOCKET = 4
PRIMARY_AT, SECONDARY_AT = SLOT_INSTANCES.index("PRIMARY"), SLOT_INSTANCES.index("SECONDARY")


def weapon(delay, dmg, bonus=None, two=False):
    return WeaponVec("2H Slashing" if two else "1H Slashing", dmg, delay, bonus, two)


def blade(key, dmg=20, delay=30, bonus=None, tier=4, classes=TRIO, lore=False, stats=None, two=False, slots=None):
    return make_item(
        key, slots or (("PRIMARY",) if two else BOTH), weapon=weapon(delay, dmg, bonus, two), classes=classes, tier=tier, lore=lore, stats=stats or {}
    )


def shield(key, ac=30, tier=4):
    return make_item(key, ("SECONDARY",), stats={"AC": ac}, shield=True, tier=tier)


class Made:
    """A table made from invented records, with what the brute force needs to value it again: the donors as written, the Lore keys and the value of each effect by name."""

    def __init__(self, effects, donors, lore):
        self.effects, self.donors, self.lore = dict(effects), list(donors), frozenset(lore)  # {name: damage}; [(name, key, slots, classes)]
        by_key: dict[str, dict] = {}
        for name, key, slots, classes in self.donors:
            if key in by_key:
                by_key[key]["effects"].append({"kind": "proc", "name": name, "raw": f"Effect: {name} (Combat)"})
            else:
                by_key[key] = sitem(key, list(slots), "proc", name, classes=tuple(classes))
        rows = [damage(100 + n, name, amount) for n, (name, amount) in enumerate(self.effects.items())]
        found, ctx, book = world(list(by_key.values()), rows)
        self.table = score.proc_table(found, ctx, book, J, TRIO, lore=self.lore)
        self.value = {effect.name: effect.value for effect in self.table.effects}


def make_table(effects, donors, lore=()):
    return Made(effects, donors, lore)


def donor(name, key, slots=BOTH, classes=TRIO):
    return (name, key, tuple(slots), tuple(classes))


def instance(items, setup, *, weights=None, haste=0, dw=Fraction(1, 2), any_rule="explicit", **profile_changes):
    profile = make_profile(TRIO, "HUM", weights or {"DMG": 100, "HP": 1}, dw_factor=dw, **profile_changes)
    return Instance(label="procs", profile=profile, items=list(items), setup=setup, buffset=None, haste_assumed=haste, any_rule=any_rule)


# ---- the rule, written out again: enumerate the copies --------------------------------------------------------------------------------------------------------


def hosts(made, spec, item, hand):
    """Whether the donor ``spec`` can be hosted by ``item`` in ``hand`` (slot in common, a class of the trio on both, a primary-only donor in the primary hand itself)."""
    _, _, slots, classes = spec
    if slots == ("PRIMARY",) and not (hand == "PRIMARY" and "PRIMARY" in item.slots):
        return False
    return bool(set(slots) & set(item.slots)) and any(c in classes and c in item.classes for c in TRIO)


def copies_of(made, key):
    return 1 if key in made.lore else 2


def units(made, item, hand, name, worn=frozenset()):
    """The physical copies, ``(item key, copy number)``, that can supply ``name`` to ``item`` in ``hand``: the item's own when it carries the effect, else those of the donors it can
    host from the socket tier on, leaving out a Lore donor that the kit wears (``worn``: the keys of the Lore items the kit wears anywhere)."""
    carriers = [spec for spec in made.donors if spec[0] == name]
    if any(spec[1] == item.key for spec in carriers):
        keys = {item.key}
    elif item.tier >= SOCKET:
        keys = {spec[1] for spec in carriers if hosts(made, spec, item, hand) and not (spec[1] in made.lore and spec[1] in worn)}
    else:
        keys = set()
    return {(key, n) for key in keys for n in range(copies_of(made, key))}


def proc_part(made, inst, primary, secondary, worn=frozenset()):
    """The proc index of the two hands (before the weight): the best pair of effects, each hand one or none, for which distinct copies can supply the hands."""
    profile = fm.compile_profile(inst.profile)
    names = [None, *made.effects]
    swing = {
        hand: item is not None and item.weapon is not None and fm.weapon_index(item.weapon, hand, inst.setup, 0, profile.dw_factor, profile.ranged_factor) > 0
        for hand, item in (("PRIMARY", primary), ("SECONDARY", secondary))
    }
    best = Fraction(0)
    factor = profile.dw_factor
    for first, second in itertools.product(names, names):
        main = units(made, primary, "PRIMARY", first, worn) if first and swing["PRIMARY"] else set()
        off = units(made, secondary, "SECONDARY", second, worn) if second and swing["SECONDARY"] else set()
        if (first and not main) or (second and not off):
            continue
        if first and second and not any(a != b for a in main for b in off):
            continue
        total = (made.value[first] if first else 0) + (factor * made.value[second] if second else 0)
        best = max(best, Fraction(total) / 600)
    return best


def kit_value(made, inst, kit, truthful=False):
    primary, secondary = kit[PRIMARY_AT], kit[SECONDARY_AT]
    if truthful:
        base = fm.evaluate_truthful(inst.profile, kit, None, setup=inst.setup).F
    else:
        base = fm.evaluate(inst.profile, kit, None, setup=inst.setup, haste_assumed=inst.haste_assumed).F
    worn = frozenset(item.key for item in kit if item is not None and item.key in made.lore)
    return base + fm.compile_profile(inst.profile).weights.get("DMG", 0) * proc_part(made, inst, primary, secondary, worn)


def brute(made, inst, truthful=False):
    """The best value over every legal kit by the rule above; the evaluator with the table must give every kit that very value."""
    space = Space(inst)
    best = None
    for combo in space.kits:
        kit = space.kit_of(combo)
        value = kit_value(made, inst, kit, truthful)
        if truthful:
            seen = fm.evaluate_truthful(inst.profile, kit, None, setup=inst.setup, procs=made.table).F
        else:
            seen = fm.evaluate(inst.profile, kit, None, setup=inst.setup, haste_assumed=inst.haste_assumed, procs=made.table).F
        assert seen == value, (inst.setup, [None if i is None else (i.key, i.tier) for i in (kit[PRIMARY_AT], kit[SECONDARY_AT])], seen, value)
        best = value if best is None or value > best else best
    return best


def milp_value(made, inst, pool=None):
    milp = build_milp(inst.profile, inst.items if pool is None else pool, inst.setup, None, BuildOptions(any_rule=inst.any_rule, haste_assumed=inst.haste_assumed, procs=made.table))
    res = solve_milp(milp)
    assert res.status == "optimal"
    return milp, res, milp.const + res.objective


def agree(made, inst):
    best = brute(made, inst)
    milp, res, value = milp_value(made, inst)
    assert abs(value - float(best)) <= REL * max(1.0, abs(float(best))), (value, float(best))
    decoded = milp.decode(res.x)
    worn = {group: decoded.groups.get(group, []) for group in decoded.groups}
    exact = kit_value(made, inst, kit_from_groups(worn))
    assert abs(float(exact) - float(best)) <= REL * max(1.0, abs(float(best)))
    return milp, best


# ---- the one-hand setups: a constant on a column -----------------------------------------------------------------------------------------------------------


def test_in_a_one_hand_setup_a_hosted_proc_decides_the_weapon_and_the_program_has_no_binary_for_it():
    # an axe that swings a little better, and an old hammer that is the donor of a strong proc: at +4 the axe can host it, so the plain swing decides
    made = make_table({"strong": 600}, [donor("strong", "hammer")])
    items = [blade("axe", dmg=24), blade("club", dmg=20), blade("hammer", dmg=10)]
    inst = instance(items, "1h-shield")
    milp, best = agree(made, inst)
    assert milp.info["binaries"].get("proc", 0) == 0
    decoded = milp.decode(solve_milp(milp).x)
    assert [i.key for i in decoded.groups["PRIMARY"]] == ["axe"]  # every weapon hosts it: the better swing wins


def test_below_the_socket_tier_the_natives_decide_and_a_donor_elsewhere_is_worth_nothing():
    made = make_table({"strong": 600}, [donor("strong", "hammer")])
    items = [blade("axe", dmg=24, tier=3), blade("hammer", dmg=10, tier=3)]
    inst = instance(items, "1h-shield")
    milp, best = agree(made, inst)
    decoded = milp.decode(solve_milp(milp).x)
    assert [i.key for i in decoded.groups["PRIMARY"]] == ["hammer"]  # +3: the hammer's own proc (855/600 of an index) beats the axe's better swing


def test_a_two_hander_in_the_two_hand_setup_counts_the_best_proc_it_can_host():
    made = make_table({"rake": 500}, [donor("rake", "pike", slots=("PRIMARY",))])
    items = [blade("maul", dmg=40, delay=40, two=True), blade("pike", dmg=30, delay=40, two=True), blade("axe", dmg=24)]
    agree(made, instance(items, "2h"))


def test_a_weapon_the_kit_wears_in_an_any_place_counts_no_proc_in_the_program_either():
    made = make_table({"rake": 600}, [donor("rake", "club")])
    items = [blade("axe", dmg=30), blade("club", dmg=10), blade("sword", dmg=12)]
    for setup in ("1h-shield", "dw"):
        agree(made, instance(items, setup, any_rule="all"))  # (a weapon is a stat stick in an Any place: the kits the brute force counts include them)


def test_the_stick_and_a_hand_item_that_is_no_weapon_add_nothing():
    made = make_table({"rake": 500}, [donor("rake", "axe")])
    items = [blade("axe", dmg=24), blade("club", dmg=20), make_item("orb", BOTH, stats={"HP": 3}, classes=TRIO, tier=4)]
    inst = instance(items, "stick")
    milp, best = agree(made, inst)
    assert float(best) == float(fm.evaluate(inst.profile, kit_from_groups({"PRIMARY": [items[2]], "SECONDARY": [items[2]]}), None, setup="stick", procs=made.table).F)  # two orbs, for their stat, and no swing or proc


def test_the_bow_setup_adds_nothing_to_the_program_whatever_the_table_says():
    bow = make_item("bow", ("RANGE",), weapon=WeaponVec("Archery", 30, 30, None, False), classes=TRIO, tier=4)
    made = make_table({"rake": 500}, [donor("rake", "bow", slots=("RANGE",)), donor("rake", "axe")])
    inst = instance([bow, blade("axe", dmg=24)], "ranged")
    options = dict(any_rule="explicit", haste_assumed=0)
    with_table = build_milp(inst.profile, inst.items, "ranged", None, BuildOptions(procs=made.table, **options))
    without = build_milp(inst.profile, inst.items, "ranged", None, BuildOptions(**options))
    assert (with_table.c == without.c).all() and with_table.const == without.const and with_table.num_rows == without.num_rows  # the hands are sticks and the bow scores no proc


# ---- two hands: the binaries and rows of the dual-wield program ----------------------------------------------------------------------------------------------


def test_a_lore_proc_that_both_hands_want_is_taken_by_one_and_the_program_says_so():
    made = make_table({"rare": 600, "common": 200}, [donor("rare", "relic"), donor("common", "club")], lore={"relic"})
    items = [blade("relic", dmg=10, lore=True), blade("axe", dmg=20), blade("sword", dmg=20), blade("club", dmg=10)]
    milp, best = agree(made, instance(items, "dw"))
    assert milp.info["binaries"]["proc"] > 0
    assert any(name.startswith("proc.host") for name in milp.row_names)
    assert "proc.copies[relic]" in milp.row_names  # the one copy supplies one hand: a row for the Lore item the hands take a proc from
    assert any(name.startswith("proc.worn") for name in milp.row_names)  # and the copy the kit wears is no donor: the relic is in the pool, so its flags and its columns are at most one


def test_with_a_donor_that_can_be_had_twice_both_hands_take_the_proc_and_there_is_no_row_for_it():
    made = make_table({"rare": 600, "common": 200}, [donor("rare", "relic"), donor("common", "club")], lore={"club"})
    items = [blade("axe", dmg=20), blade("sword", dmg=20), blade("club", dmg=10, lore=True)]
    milp, _ = agree(made, instance(items, "dw"))
    assert not any(name.startswith("proc.copies") for name in milp.row_names)  # a plain donor is two copies, and the best proc of every column can never be blocked: it is the only candidate


def test_below_the_socket_tier_dual_wield_has_constants_and_no_binary():
    made = make_table({"rare": 600, "common": 200}, [donor("rare", "axe"), donor("common", "sword")])
    items = [blade("axe", dmg=20, tier=3), blade("sword", dmg=20, tier=3), blade("plain", dmg=30, tier=3)]
    milp, _ = agree(made, instance(items, "dw"))
    assert milp.info["binaries"].get("proc", 0) == 0


def test_a_pool_with_one_item_at_the_socket_tier_has_the_binaries_for_every_column_and_the_copies_of_a_lore_item_at_a_lower_tier_count():
    made = make_table({"rare": 600}, [donor("rare", "relic")], lore={"relic"})  # only the Lore relic carries it, and it is below the socket tier
    items = [blade("relic", dmg=10, tier=3, lore=True), blade("axe", dmg=20, tier=4)]
    milp, best = agree(made, instance(items, "dw"))
    assert milp.info["binaries"]["proc"] > 0


def test_a_two_hander_has_no_place_in_the_dual_wield_pool_and_adds_no_binary():
    made = make_table({"rake": 500, "rare": 300}, [donor("rake", "maul", slots=("PRIMARY",)), donor("rare", "axe")])
    maul = blade("maul", dmg=60, delay=40, two=True)
    items = [maul, blade("axe", dmg=20), blade("sword", dmg=20)]
    milp, _ = agree(made, instance(items, "dw"))
    assert all(item.key != "maul" for _, _, item in milp.item_cols)  # (the donor is no hand item of this pool, and the rake is hosted by a one-hander in the primary hand)
    assert not any("maul" in name for name in milp.names)


# ---- the truthful solve: the swing is paid the haste the kit counts and the proc is not ------------------------------------------------------------------------------


@pytest.mark.parametrize("setup", ["1h-shield", "dw"])
def test_the_truthful_optimum_is_the_best_value_at_the_haste_each_kit_counts(setup):
    made = make_table({"rare": 600, "common": 200}, [donor("rare", "relic"), donor("common", "club")], lore={"relic"})
    belt = make_item("belt", ("WAIST",), stats={"HP": 5}, haste=30, tier=4)
    items = [blade("relic", dmg=10, lore=True), blade("axe", dmg=20), blade("sword", dmg=24), blade("club", dmg=10), belt, shield("buckler")]
    inst = instance(items, setup, buff_totals={"HASTE": 15})
    best = brute(made, inst, truthful=True)
    found = solve_scenario(inst.profile, inst.items, setup, None, BuildOptions(any_rule="explicit", procs=made.table)).solution
    assert found.status == "optimal" and abs(found.F - float(best)) <= REL * max(1.0, abs(float(best)))
    assert found.breakdown.totals["procs"]["PRIMARY"] is not None  # the evaluator's answer carries what each hand counts


# ---- random instances ---------------------------------------------------------------------------------------------------------------------------------------


def random_case(rng, setup, tiers):
    keys = [f"w{n}" for n in range(rng.randint(3, 6))]
    items = []
    for key in keys:
        two = setup == "2h"
        items.append(
            blade(
                key, dmg=rng.randint(8, 40), delay=rng.choice((20, 30, 40)), bonus=rng.choice((None, 5)), tier=rng.choice(tiers), lore=rng.random() < 0.35,
                classes=rng.choice((TRIO, ("WAR", "SHM"), ("ENC",), ("WAR",))), two=two, stats={"HP": rng.randint(0, 5)},
            )
        )
    if setup == "1h-shield":
        items.append(shield("buck", rng.randint(5, 40), tiers[0]))
    pool = {item.key: item for item in items}
    external = {f"far-{c}": (rng.choice((BOTH, ("PRIMARY",), ("SECONDARY",))), rng.choice((TRIO, ("WAR",), ("SHM", "ENC"), ("ENC",))), rng.random() < 0.4) for c in "abc"}
    if setup == "2h":
        external = {key: (("PRIMARY",), classes, lore) for key, (_, classes, lore) in external.items()}
    names = {f"p{n}": rng.choice((200, 400, 400, 600, 800)) for n in range(rng.randint(2, 5))}
    donors, seen = [], set()
    for name in names:
        for _ in range(rng.randint(1, 3)):
            key = rng.choice([*keys, *external])
            if (name, key) in seen:
                continue
            seen.add((name, key))
            slots, classes = (tuple(pool[key].slots), tuple(pool[key].classes)) if key in pool else external[key][:2]
            donors.append((name, key, tuple(slots), tuple(sorted(classes))))
    lore = {key for key, item in pool.items() if item.lore} | {key for key, (_, _, is_lore) in external.items() if is_lore}
    return items, Made(names, donors, lore)


@pytest.mark.parametrize("setup", ["1h-shield", "2h", "dw"])
@pytest.mark.parametrize("tiers", [(3,), (4,), (3, 4)], ids=["+3", "+4", "mixed"])
def test_random_pools_the_program_is_the_best_kit_by_the_rule_and_the_evaluator_agrees_on_every_kit(setup, tiers):
    rng = random.Random(f"{setup}-{tiers}")
    for _ in range(25):
        items, made = random_case(rng, setup, tiers)
        inst = instance(
            items, setup, weights={"DMG": rng.choice((50, 100, 400)), "HP": 1}, haste=rng.choice((0, 30, 60)), dw=rng.choice((Fraction(1, 2), Fraction(4, 5), 1))
        )
        agree(made, inst)


@pytest.mark.parametrize("setup", ["1h-shield", "2h", "dw"])
@pytest.mark.parametrize("tiers", [(3,), (4,), (3, 4)], ids=["+3", "+4", "mixed"])
def test_random_pools_the_pruned_pool_is_worth_exactly_what_the_whole_pool_is(setup, tiers):
    rng = random.Random(f"prune-{setup}-{tiers}")
    for _ in range(30):
        items, made = random_case(rng, setup, tiers)
        inst = instance(items, setup, weights={"DMG": rng.choice((50, 100, 400)), "HP": 1}, haste=rng.choice((0, 30)))
        options = BuildOptions(any_rule="explicit", haste_assumed=inst.haste_assumed, procs=made.table)
        kept = prune(items, inst.profile, tiers[0] if len(tiers) == 1 else None, setup, None, options)
        _, _, whole = milp_value(made, inst)
        _, _, pruned = milp_value(made, inst, kept)
        assert abs(whole - pruned) <= REL * max(1.0, abs(whole)), (setup, tiers, [i.key for i in items], [i.key for i in kept])


def test_an_item_that_hosts_a_better_proc_is_never_dropped_by_one_that_only_swings_better():
    made = make_table({"rake": 600}, [donor("rake", "pike", classes=("SHM",))])
    swings = blade("swings", dmg=30, classes=("WAR",))  # the better swing, but the donor's classes do not overlap with it
    hosts_it = blade("hosts", dmg=10, classes=("SHM",))
    options = BuildOptions(any_rule="explicit", haste_assumed=0, procs=made.table)
    for setup in ("1h-shield", "dw"):
        inst = instance([swings, hosts_it], setup)
        kept = prune([swings, hosts_it], inst.profile, 4, setup, None, options)
        assert {i.key for i in kept} == {"swings", "hosts"}
    # and without the table the better swing drops the other, so it is the proc that keeps it
    plain = prune([swings, hosts_it], instance([swings, hosts_it], "1h-shield").profile, 4, "1h-shield", None, BuildOptions(any_rule="explicit", haste_assumed=0))
    assert {i.key for i in plain} == {"swings"}


def test_in_dual_wield_an_item_is_dropped_only_by_one_that_can_be_supplied_every_proc_it_can_from_every_source_it_has():
    made = make_table({"a": 600, "b": 400}, [donor("a", "far", classes=("WAR",)), donor("b", "far-b")])
    wide = blade("wide", dmg=30, classes=TRIO)  # hosts both, from the same sources
    narrow = blade("narrow", dmg=20, classes=("WAR",))  # hosts both too, from the same sources, with a worse swing: dropped
    other = blade("other", dmg=15, classes=("ENC",))  # hosts b only: the wide one hosts everything it does
    options = BuildOptions(any_rule="explicit", haste_assumed=0, procs=made.table)
    kept = prune([wide, narrow, other], instance([wide, narrow, other], "dw").profile, 4, "dw", None, options)
    assert [i.key for i in kept] == ["wide"]
    only = blade("only", dmg=40, classes=("ENC",))  # the better swing, hosts b only: it cannot drop the narrow one, which hosts a
    kept = prune([only, narrow], instance([only, narrow], "dw").profile, 4, "dw", None, options)
    assert {i.key for i in kept} == {"only", "narrow"}


def test_in_dual_wield_an_item_with_fewer_sources_of_a_proc_does_not_drop_one_with_more():
    # the proc has two donors, a Lore one that only the warrior can use and a plain one that the shaman and the enchanter can: a blade of the warrior alone has the one source, a blade of everyone two. Two
    # blades of the warrior alone would have to share one copy, two blades of everyone would not, so the better swing of the first must not drop the second
    made = make_table({"rare": 600}, [donor("rare", "x", classes=("WAR",)), donor("rare", "w", classes=("SHM", "ENC"))], lore={"x"})
    few = blade("few", dmg=30, classes=("WAR",))
    many = blade("many", dmg=20, classes=TRIO)
    options = BuildOptions(any_rule="explicit", haste_assumed=0, procs=made.table)
    kept = prune([few, many], instance([few, many], "dw").profile, 4, "dw", None, options)
    assert {i.key for i in kept} == {"few", "many"}


# ---- the rows are what holds the answer ------------------------------------------------------------------------------------------------------------------


def test_without_the_copies_row_the_program_overstates_a_lore_proc(monkeypatch):
    """The brute force sees a missing row: a builder that left the copies row out values the Lore proc in both hands."""
    from trioforge.solver import model as solver_model

    made = make_table({"rare": 600}, [donor("rare", "relic")], lore={"relic"})
    inst = instance([blade("axe", dmg=20), blade("sword", dmg=20)], "dw")
    agree(made, inst)  # (the program is right as it stands)
    real = solver_model._Builder._row

    def skip(self, name, terms, lb, ub):
        if not name.startswith("proc.copies"):
            real(self, name, terms, lb, ub)

    monkeypatch.setattr(solver_model._Builder, "_row", skip)
    with pytest.raises(AssertionError):
        agree(made, inst)


def test_without_the_host_row_the_program_counts_a_proc_that_no_item_in_the_hand_can_host(monkeypatch):
    from trioforge.solver import model as solver_model

    made = make_table({"far": 600}, [donor("far", "pike", classes=("SHM",))], lore={"pike"})  # (a Lore donor: the hosted proc has a binary and its host row; with no Lore source it is a constant on the column)
    host = blade("host", dmg=10, classes=("WAR", "SHM"))
    plain = blade("plain", dmg=30, classes=("WAR",))  # the better swing, and a weapon that cannot host the proc
    inst = instance([host, plain], "dw")
    agree(made, inst)
    real = solver_model._Builder._row

    def skip(self, name, terms, lb, ub):
        if not name.startswith("proc.host"):
            real(self, name, terms, lb, ub)

    monkeypatch.setattr(solver_model._Builder, "_row", skip)
    with pytest.raises(AssertionError):
        agree(made, inst)
