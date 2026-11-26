"""The kit checks and the builds: which check is about which build, K12, the expected cases of a build that is gone, and reading the results of the earlier roles.

Kits are written by hand from invented items (``kits_fixture``). A results folder made before the builds (one with a Balanced kit) is still read by the checker, so that the
release before the builds can stand beside the one after it; its Balanced kits take only the checks that apply to every build.
"""

from __future__ import annotations

import json

import pytest
from kits_fixture import base_items, make_results, row

from trioforge import rules as rules_module
from trioforge.checks import kits as kits_module
from trioforge.checks import named
from trioforge.checks.expected import check_case, check_expected
from trioforge.checks.kits import CHECKS, FAIL, GATES, NA, PASS, ROLE_ORDER, SCOREBOARD_ONLY, Context, Scoreboard
from trioforge.checks.results import Results, ResultsError
from trioforge.model import roles

ALL = ("tank", "shield", "melee", "ranged", "castertank", "caster")
TRIO = "pal-mnk-enc"  # a tank class, a Monk and an Enchanter: offered Tank, Shield caster (a tank class and a spell class) and Melee damage; not Caster tank (a tank class), not Caster (one spell class and melee classes) and not Archer (no Ranger)
KIT = {"FACE": "Glimmer Idol", "WAIST": "Brawn Belt", "CHEST": "Ombrel Vestment", "HEAD": "Vlorn Helm"}


@pytest.fixture(scope="module")
def rules():
    return rules_module.load()


@pytest.fixture
def folder(tmp_path, rules):
    count = iter(range(100))

    def make(rows, trio=TRIO, **kwargs):
        root = make_results(tmp_path / f"results-{next(count)}", base_items(), {trio: rows}, **kwargs)
        results = Results(root, rules=rules)
        return results, Context(results, min_set_items=2)

    return make


def by_role(folder, rows, trio=TRIO, **kwargs):
    results, context = folder(rows, trio=trio, **kwargs)
    return {(kit.role, kit.tier): context.evaluate(kit) for kit in results.kits(trio)}, results, context


def test_the_checks_name_the_builds_they_are_about():
    roles_of = {check.id: check.roles for check in CHECKS}
    assert roles_of["K1.attr"] == roles_of["K1.pool"] == roles_of["K2"] == ("tank", "melee", "ranged")
    for check_id in ("K3", "K3.CHEST", "K3.robe", "K3.robe_worn", "K8", "K11"):
        assert roles_of[check_id] == ("tank", "shield"), check_id
    assert roles_of["K5.bow"] == roles_of["K5.windstriker"] == ("melee", "ranged")
    assert roles_of["K6"] == ("melee",)
    assert roles_of["K7"] is None  # every build
    assert roles_of["K12"] == ("tank",)
    assert "K12" in SCOREBOARD_ONLY and "K12" not in GATES
    assert set(ALL) <= set(ROLE_ORDER) and ROLE_ORDER[0] == "balanced"  # (the earlier release's build is read, and shown first)
    assert set(ROLE_ORDER) - set(ALL) == {"balanced"}
    assert [check.id for check in CHECKS][-1] == "K12"
    assert set(roles.ROLES) == set(ALL)
    # K9 (the named cases) and K10 (their exchange rates) are for every build: the cases take each build a trio is offered, and are not a check that names builds
    assert "K9" not in roles_of and "K10" not in roles_of
    assert all(roles is None for label, trio, roles in named.CASES if label != "PAL/MNK/ENC tank")  # (a named case lists every build of its trio, but for the one that is about the Tank)
    assert set(named.ROLES) == set(ALL) and named.NA_REASON == "results made with other rules"


@pytest.mark.parametrize("role", ALL)
def test_each_check_is_applicable_only_to_the_builds_it_names(folder, role):
    trio = "war-rng-clr" if role in ("tank", "shield", "melee", "ranged") else "wiz-mag-enc"  # (a trio that is offered the build)
    assert role in roles.roles_for(tuple(code.upper() for code in trio.split("-")), bow=None)
    setup = {"shield": "stick", "castertank": "stick", "caster": "stick", "tank": "1h-shield"}.get(role, "2h")  # (the Tank has the shield setup here: K12 is n.a. for a level that has none)
    out, _, _ = by_role(folder, [row(role, 4, KIT, setup=setup, totals={"ac": 500})], trio=trio)
    outcome = out[(role, 4)]
    for check in CHECKS:
        if check.id.startswith("K4") or check.id in ("K5.bow", "K5.windstriker"):
            continue  # (K4 is not a build check; K5 asks for a Ranger too)
        applies = check.roles is None or role in check.roles
        got = outcome[check.id].status
        if check.id.startswith("K3.") and check.id not in ("K3.robe", "K3.robe_worn"):
            continue  # (an armour slot with no piece to wear is n.a. for any build)
        if check.id == "K6":
            continue  # (the strength of melee: n.a. also when the pool has none to give)
        assert (got != NA) == applies or (got == NA and not applies), (role, check.id, got)
        if not applies:
            assert got == NA, (role, check.id)


def test_k12_is_the_share_of_tank_kits_whose_best_setup_is_one_hand_and_a_shield(folder):
    out, _, _ = by_role(
        folder,
        [row("tank", 4, KIT, setup="1h-shield"), row("tank", 10, KIT, setup="dw"), row("melee", 4, KIT, setup="1h-shield"), row("shield", 4, KIT, setup="1h-shield")],
    )
    assert out[("tank", 4)]["K12"].status == PASS and out[("tank", 4)]["K12"].value == 1
    assert out[("tank", 10)]["K12"].status == FAIL and out[("tank", 10)]["K12"].detail == {"setup": "dw"}
    assert out[("melee", 4)]["K12"].status == NA and out[("shield", 4)]["K12"].status == NA  # (only the tank build: the others have no choice to make)
    results, context = folder([row("tank", 4, KIT, setup="1h-shield"), row("tank", 10, KIT, setup="dw")])
    board = Scoreboard(context)
    for kit in results.all_kits():
        board.add(kit)
    document = board.document()["checks"]["K12"]
    assert document["scoreboard_only"] and not document["gate"]
    assert document["by_role"]["tank"]["all"]["pass"] == 1 and document["by_role"]["tank"]["all"]["fail"] == 1  # a share of one half


def test_the_shield_caster_takes_the_armour_checks_and_the_stamina_check_of_a_tank(folder):
    kit = {"CHEST": "Ombrel Vestment", "HEAD": "Vlorn Helm", "EAR1": "Moonstud"}
    out, _, _ = by_role(folder, [row("shield", 4, kit, setup="1h-shield", totals={"ac": 100}), row("caster", 4, kit, setup="stick", totals={"ac": 100})])
    shield, caster = out[("shield", 4)], out[("caster", 4)]
    assert shield["K3"].status == FAIL and shield["K3.robe"].status == FAIL and shield["K8"].status == FAIL and shield["K11"].status in (PASS, FAIL)
    for check_id in ("K3", "K3.robe", "K3.robe_worn", "K8", "K11", "K12", "K2", "K1.pool"):
        assert caster[check_id].status == NA, check_id
    assert shield["K2"].status == NA and shield["K1.attr"].status == NA  # the Shield caster casts: no pure-caster item is a fault there
    assert caster["K7"].status != NA and shield["K7"].status != NA


def test_the_archer_takes_the_non_casting_checks_and_the_bow_checks(folder):
    results, context = folder([row("ranged", 4, {"RANGE": "Fenwick Longbow", "FACE": "Glimmer Idol"}, setup="ranged")], trio="rng-clr-shm")
    (kit,) = [k for k in results.kits("rng-clr-shm") if k.role == "ranged"]
    out = context.evaluate(kit)
    assert out["K2"].status == FAIL and out["K2"].detail["items"] == ["Glimmer Idol"]
    assert out["K5.bow"].status == PASS and out["K1.attr"].status != NA
    assert out["K3"].status == NA and out["K8"].status == NA and out["K12"].status == NA


# ---- the expected cases ------------------------------------------------------------------------------------------------------


def case(**fields):
    return {"trio": TRIO, "slot": "CHEST", "any_of": ["Ombrel Vestment"], **fields}


def test_a_case_for_the_balanced_build_is_not_applicable_even_when_the_folder_has_a_balanced_kit(folder):
    results, _ = folder([row("tank", 4, {"CHEST": "Ombrel Vestment"}), row("balanced", 4, {"CHEST": "Ombrel Vestment"})])
    for fields in ({"role": "balanced"}, {"role": "Balanced"}):
        report = check_case(case(**fields), 1, results)
        assert report["status"] == "na" and "no longer exists" in report["reason"], fields
    assert check_case(case(role="tank"), 1, results)["status"] == "agree"
    report = check_expected([case(role="balanced"), case(role="tank")], results)
    assert (report["agree"], report["disagree"], report["na"]) == (1, 0, 1)


@pytest.mark.parametrize("role", ["castertank", "caster", "ranged"])
def test_a_case_for_a_build_the_trio_is_not_offered_is_not_applicable_never_agree_or_disagree(folder, role):
    assert role not in roles.roles_for(("PAL", "MNK", "ENC"), bow=None)  # (a tank class, a Monk and one spell class: Tank, Shield caster, Melee damage)
    results, _ = folder([row("tank", 4, {"CHEST": "Ombrel Vestment"}), row(role, 4, {"CHEST": "Ombrel Vestment"})])  # (a folder that has a kit of that build all the same)
    report = check_case(case(role=role), 1, results)
    assert report["status"] == "na" and "not offered" in report["reason"]
    assert check_case(case(role="shield"), 1, results)["status"] == "na"  # (offered, and the folder has no kit of it: n.a. too, as before)


@pytest.mark.parametrize("role", ["tank", "melee", "caster"])
def test_a_case_for_tank_melee_or_caster_still_matches_those_ids(folder, role):
    trio = "pal-mnk-enc" if role != "caster" else "wiz-enc-mag"
    results, _ = folder([row(role, 4, {"CHEST": "Ombrel Vestment"})], trio=trio)
    report = check_case({"trio": trio, "role": role, "slot": "CHEST", "any_of": ["Ombrel Vestment"]}, 1, results)
    assert report["status"] == "agree" and report["roles_holding"] == [role]


def test_a_case_for_any_looks_at_every_kit_of_the_folder(folder):
    results, _ = folder([row("balanced", 4, {"CHEST": "Ombrel Vestment"}), row("tank", 4, {"CHEST": "Vlorn Tunic"})])
    report = check_case(case(role="any"), 1, results)
    assert report["status"] == "agree" and report["roles_holding"] == ["balanced"] and report["roles_failing"] == ["tank"]  # (the folder of the earlier release reads as it did)


# ---- results of the earlier roles are still read -------------------------------------------------------------------------------


def test_the_checker_reads_a_folder_of_the_earlier_roles_and_gives_its_balanced_kits_the_checks_of_every_build(folder):
    rows = [row("balanced", 4, KIT), row("tank", 4, KIT), row("melee", 4, KIT), row("caster", 4, KIT), row("balanced", 10, KIT)]
    results, context = folder(rows)
    board = Scoreboard(context)
    for kit in results.all_kits():
        board.add(kit)
    document = board.document()
    assert document["roles"] == ["balanced", "tank", "melee", "caster"]  # the earlier release's build first, then the builds in their order
    (balanced_kit,) = [kit for kit in results.kits(TRIO) if kit.role == "balanced" and kit.tier == 4]
    balanced = context.evaluate(balanced_kit)
    applicable = {check_id for check_id, outcome in balanced.items() if outcome.status != NA}
    assert applicable == {"K7"}  # the one check that applies to every build
    assert set(board.gates()) == {"K2", "K3.robe"}


def test_the_named_cases_leave_out_the_kits_of_a_build_that_no_longer_exists(folder):
    results, context = folder([row("balanced", 4, KIT, value=1000.0), row("tank", 4, KIT, value=None)], trio="pal-mnk-enc")
    cases = named.named_cases(results, context)
    assert [entry["role"] for entry in cases] == ["tank"]  # (a kit of Balanced has no weights to value it by, and no exchange rates)


def test_the_expected_file_of_the_work_order_still_loads_and_n_a_is_counted_apart(folder, tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([case(role="balanced"), case(role="any")]), encoding="utf-8")
    results, _ = folder([row("tank", 4, {"CHEST": "Ombrel Vestment"})])
    from trioforge.checks.expected import load_cases

    report = check_expected(load_cases(path), results)
    assert report["na"] == 1 and report["agree"] == 1 and report["agreement"] == 1.0


# ---- the rules version: results of the rules before the builds are not read as these ---------------------------------------------

RULES_BEFORE_THE_BUILDS = "2026-10-13"


def test_results_that_record_the_rules_before_the_builds_are_reported_as_made_with_other_rules(tmp_path, rules):
    assert rules.version != RULES_BEFORE_THE_BUILDS  # (the rules file was given a new version when the templates changed)
    earlier = Results(make_results(tmp_path / "earlier", base_items(), {TRIO: [row("tank", 4, KIT)]}, rules_version=RULES_BEFORE_THE_BUILDS), rules=rules)
    assert earlier.rules_mismatch() == (RULES_BEFORE_THE_BUILDS, rules.version)
    current = Results(make_results(tmp_path / "current", base_items(), {TRIO: [row("tank", 4, KIT)]}), rules=rules)
    assert current.rules_mismatch() is None


def old_style_folder(tmp_path):
    """A results folder as the release before the builds wrote it: the rules version of that release, a Balanced kit and a Tank kit, each with the value that release's templates gave
    (which the evaluator of this checkout does not give)."""
    rows = [row("balanced", 4, KIT, value=1000.0), row("tank", 4, KIT, value=1000.0), row("balanced", 10, KIT, value=1100.0), row("tank", 10, KIT, value=1100.0)]
    return make_results(tmp_path / "old", base_items(), {TRIO: rows}, rules_version=RULES_BEFORE_THE_BUILDS)


def test_a_default_run_on_an_old_folder_gives_k9_and_k10_as_not_applicable_with_one_warning_and_runs_the_rest(tmp_path, capsys):
    root = old_style_folder(tmp_path)
    code = kits_module.main(["--results", str(root), "--json", str(tmp_path / "old.json")])  # (the named cases are on: no --no-named)
    out = capsys.readouterr().out
    assert code == 0  # as for a normal run
    assert out.count("warning: the results were made with the rules of 2026-10-13") == 1 and out.count("warning:") == 1
    assert "n.a.: results made with other rules" in out and "K9  Named cases" in out and "K10  Exchange rates" in out
    document = json.loads((tmp_path / "old.json").read_text(encoding="utf-8"))
    assert document["K9"] == [] and document["K9_na"] == "results made with other rules"
    assert document["kits"] == 4 and document["roles"] == ["balanced", "tank"]  # (the rest of the checker ran: the kits of the old build were counted)


def test_the_gate_still_refuses_an_old_folder(tmp_path, capsys):
    code = kits_module.main(["--results", str(old_style_folder(tmp_path)), "--gate"])
    err = capsys.readouterr().err
    assert code == 2 and "2026-10-13" in err


def test_a_folder_of_the_current_rules_with_a_kit_whose_value_the_evaluator_does_not_give_still_stops_the_named_cases(tmp_path, capsys):
    rows = [row("tank", 4, KIT, value=1000.0)]
    root = make_results(tmp_path / "wrong", base_items(), {TRIO: rows})  # the current rules version, and a value that is nobody's
    code = kits_module.main(["--results", str(root)])
    assert code == 2 and "the evaluator values the kit" in capsys.readouterr().err


ENCHANTER_HASTE_ID = 172  # a buff of the Enchanter's own line that is a haste and nothing else: it is in the own buffs of the trio only where spell haste is assumed


def with_a_buff(root, spell_id):
    """The folder with the optional buff ``spell_id`` named by the shard of the trio (the kits of the fixture name none)."""
    path = root / TRIO / "wiki-own.json"
    shard = json.loads(path.read_text(encoding="utf-8"))
    shard["buff_sets"] = [[spell_id]]
    path.write_text(json.dumps(shard), encoding="utf-8")
    return root


def test_a_buff_a_shard_names_that_is_not_in_the_own_buffs_of_the_trio_is_refused_for_results_of_the_current_rules(tmp_path, rules):
    root = with_a_buff(make_results(tmp_path / "now", base_items(), {TRIO: [row("tank", 4, KIT, value=None)]}), ENCHANTER_HASTE_ID)
    results = Results(root, rules=rules)
    context = Context(results, min_set_items=2)
    (kit,) = [k for k in results.kits(TRIO) if k.role == "tank"]
    assert results.rules_mismatch() is None and kit.buff_ids == (ENCHANTER_HASTE_ID,)
    with pytest.raises(ResultsError, match=r"the buff 172 that its shard names is not one of the own buffs of the trio"):
        context.buff_totals(kit)


def test_the_same_buff_is_found_in_the_other_flavour_of_the_own_buffs_for_results_of_other_rules(tmp_path, rules):
    root = with_a_buff(make_results(tmp_path / "before", base_items(), {TRIO: [row("tank", 4, KIT, value=1000.0)]}, rules_version=RULES_BEFORE_THE_BUILDS), ENCHANTER_HASTE_ID)
    results = Results(root, rules=rules)
    context = Context(results, min_set_items=2)
    (kit,) = [k for k in results.kits(TRIO) if k.role == "tank"]
    assert results.rules_mismatch() == (RULES_BEFORE_THE_BUILDS, rules.version)
    assert context.buff_totals(kit)["haste"] == 60  # (the earlier rules counted the spell haste: the fallback finds the buff that this checkout leaves out)


# ---- the named cases and the expected cases for the new builds -------------------------------------------------------------------------------------------


def test_the_named_cases_and_their_exchange_rates_take_every_build_a_named_trio_is_offered(folder):
    named_trio = "shd-wiz-enc"  # the first named case: every build of it
    offered = [role for role in roles.roles_for(("SHD", "WIZ", "ENC")) if role in ALL]
    assert offered == ["tank", "shield", "melee", "caster"]
    rows = [row(role, tier, KIT, setup="stick" if role in ("shield", "caster") else "2h", value=None) for role in offered for tier in (4, 10)]
    results, context = folder(rows, trio=named_trio)
    entries = [entry for entry in named.named_cases(results, context) if entry["trio"] == named_trio]
    assert {(entry["role"], entry["tier"]) for entry in entries} == {(role, tier) for role in offered for tier in (4, 10)}
    for entry in entries:
        assert set(entry["K10"]["rates"]) and entry["K10"]["value"] > 0, entry["role"]  # (an exchange rate for each term, for every build)
        assert set(entry["checks"]) >= {"K7", "K8", "K11", "K12"}


NEW_BUILD_CASES = [
    ("shield", "pal-mnk-enc", "CHEST", "Vlorn Tunic", "Ombrel Vestment", "stick"),
    ("castertank", "wiz-mag-enc", "CHEST", "Ombrel Vestment", "Vlorn Tunic", "stick"),
    ("ranged", "rng-clr-shm", "RANGE", "Fenwick Longbow", "Dimble Charm", "ranged"),
]


@pytest.mark.parametrize(("role", "trio", "slot", "worn", "other", "setup"), NEW_BUILD_CASES, ids=[case[0] for case in NEW_BUILD_CASES])
def test_a_case_for_a_new_build_agrees_with_the_kit_that_wears_the_item_and_disagrees_with_the_kit_that_does_not(folder, role, trio, slot, worn, other, setup):
    assert role in roles.roles_for(tuple(code.upper() for code in trio.split("-")), bow=None)  # (the trio is offered the build)
    results, _ = folder([row(role, 4, {slot: worn}, setup=setup)], trio=trio)
    agree = check_case({"trio": trio, "role": role, "slot": slot, "any_of": [worn]}, 1, results)
    assert agree["status"] == "agree" and agree["roles_holding"] == [role] and agree["roles_failing"] == []
    disagree = check_case({"trio": trio, "role": role, "slot": slot, "any_of": [other]}, 1, results)
    assert disagree["status"] == "disagree" and disagree["roles_failing"] == [role] and disagree["roles_holding"] == []
    none_of = check_case({"trio": trio, "role": role, "slot": slot, "none_of": [other]}, 1, results)  # (the same kit does not wear the other item)
    assert none_of["status"] == "agree"


# ---- fix round 2: the rules of every file, K12 where there is no shield setup, and a case with a build that is not one -------------------------------


def restamp(path, version):
    document = json.loads(path.read_text(encoding="utf-8"))
    document["rules_version"] = version
    path.write_text(json.dumps(document), encoding="utf-8")


def mixed_rules(tmp_path, file="wiki-own.json"):
    """Two trios, ``items.json`` at the checkout's rules, and one file of the second trio that records the rules before the builds."""
    root = make_results(tmp_path / "mixed", base_items(), {TRIO: [row("tank", 4, KIT)], "war-clr-pal": [row("tank", 4, KIT)]})
    restamp(root / "war-clr-pal" / file, RULES_BEFORE_THE_BUILDS)
    return root


@pytest.mark.parametrize("file", ["wiki-own.json", "defaults.json"])
def test_a_folder_whose_items_say_the_rules_of_today_but_a_trio_file_records_others_is_of_other_rules(tmp_path, rules, capsys, file):
    root = mixed_rules(tmp_path, file)
    results = Results(root, rules=rules)
    assert results.release["rules_version"] == rules.version  # (the table says today's rules: only a trio file says otherwise)
    assert results.rules_mismatch() == (RULES_BEFORE_THE_BUILDS, rules.version)
    assert Context(results, min_set_items=2).other_rules is True
    code = kits_module.main(["--results", str(root), "--gate", "--no-named"])
    err = capsys.readouterr().err
    assert code == 2 and "the gate is refused" in err and RULES_BEFORE_THE_BUILDS in err
    code = kits_module.main(["--results", str(root), "--json", str(tmp_path / "out.json")])
    out = capsys.readouterr().out
    assert code == 0 and f"made with the rules of {RULES_BEFORE_THE_BUILDS}" in out
    document = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert document["K9"] == [] and document["K9_na"] == named.NA_REASON  # (K9 and K10 are n.a. for results of other rules)


def test_a_folder_whose_files_all_record_the_rules_of_today_is_not_of_other_rules(tmp_path, rules):
    root = make_results(tmp_path / "same", base_items(), {TRIO: [row("tank", 4, KIT)], "war-clr-pal": [row("tank", 4, KIT)]})
    assert Results(root, rules=rules).rules_mismatch() is None


def test_a_trio_file_with_no_rules_version_is_of_other_rules_for_the_checker_too(tmp_path, rules):
    root = make_results(tmp_path / "bare", base_items(), {TRIO: [row("tank", 4, KIT)]})
    path = root / TRIO / "wiki-own.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    del document["rules_version"]
    path.write_text(json.dumps(document), encoding="utf-8")
    assert Results(root, rules=rules).rules_mismatch() == ("none", rules.version)


def test_k12_is_not_applicable_to_a_tank_kit_whose_evidence_level_has_no_shield_setup(folder):
    # the setups this level has for the Tank are the two-hander and the dual wield: no one-hander and shield to choose, so the kit's setup is no fault of the build
    out, _, _ = by_role(folder, [row("tank", 4, KIT, setup="2h"), row("tank", 10, KIT, setup="dw")])
    assert out[("tank", 4)]["K12"].status == NA and out[("tank", 10)]["K12"].status == NA
    out, _, _ = by_role(folder, [row("tank", 4, KIT, setup="2h"), row("tank", 4, KIT, setup="1h-shield", value=1.0), row("tank", 10, KIT, setup="dw")])
    assert out[("tank", 4)]["K12"].status == FAIL and out[("tank", 4)]["K12"].detail == {"setup": "2h"}  # (this level has the shield setup, and the kit does not use it)
    assert out[("tank", 10)]["K12"].status == FAIL  # (the level is what counts, not the tier: it has the shield setup, and +10 does not use it)


@pytest.mark.parametrize("role", ["tnak", "Shield caster", "healer", "", "balance"])
def test_a_case_with_a_role_that_is_no_build_is_invalid_and_never_drops_out_as_not_applicable(folder, role):
    results, _ = folder([row("tank", 4, {"CHEST": "Ombrel Vestment"})])
    report = check_case(case(role=role), 1, results)
    assert report["status"] == "invalid" and "role" in report["reason"] and "tank" in report["reason"]
    assert check_expected([case(role=role)], results)["invalid"] == 1


def test_the_roles_of_the_rules_any_and_the_removed_build_are_still_roles_of_a_case(folder):
    results, _ = folder([row("tank", 4, {"CHEST": "Ombrel Vestment"})])
    for role, status in (("tank", "agree"), ("Tank", "agree"), ("any", "agree"), ("balanced", "na"), ("ranged", "na"), ("castertank", "na")):
        assert check_case(case(role=role), 1, results)["status"] == status, role


def test_the_named_cases_count_the_distinct_pieces_of_a_set_as_the_scoreboard_does(folder):
    """K4 of a named case is the number of distinct items of a set that the kit wears: one piece worn in two places is one piece (Part L, L4)."""
    trio = "shd-wiz-enc"  # the first named case
    rows = [
        row("tank", 4, {"HEAD": "Vlorn Helm", "ANY1": "Vlorn Helm"}, setup="2h", value=None),  # one piece, worn twice: no set
        row("melee", 4, {"HEAD": "Vlorn Helm", "FEET": "Vlorn Boots", "ANY1": "Vlorn Helm"}, setup="2h", value=None),  # two pieces, one of them twice
    ]
    results, context = folder(rows, trio=trio)
    entries = {entry["role"]: entry for entry in named.named_cases(results, context) if entry["trio"] == trio and entry["tier"] == 4}
    assert entries["tank"]["K4"] == {} and entries["melee"]["K4"] == {"vlorn": 2}
    board = Scoreboard(context)
    for kit in results.all_kits():
        board.add(kit)
    assert [(top["stem"], top["kits"]) for top in board.top_stems()] == [("vlorn", 1)]  # (the scoreboard counts the same pieces)
