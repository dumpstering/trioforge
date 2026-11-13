"""The engine data of the synthetic site fixture is what ``engine_fixture.py`` makes of it.

The fixture's shards are written by hand, but the bundle of the trio, the item table and the Equip now answers that the browser tests
hold the engine to cannot be: they are made from an invented catalog with the exporter's functions and Python's reference
(:func:`trioforge.upgrade.equip_now`). These tests make them again and fail when a committed file differs, so that the fixture cannot
fall behind the exporter, the rules or the reference, and check that what the fixture holds is within the budgets of the build.
"""

from __future__ import annotations

import json
from collections import Counter
from fractions import Fraction
from pathlib import Path

import pytest
from engine_fixture import (
    BEST_KIT,
    BEST_KIT_CASES,
    CASES,
    EQUIP_NOW,
    KIT_ONLY,
    KIT_VALUES,
    MOTE_ORDERS,
    PATH_STEPS,
    RESULTS,
    SLOT_LIMIT,
    TIER_MODES,
    TRIO_FOLDER,
    UPGRADE_VIEW,
    UPGRADE_VIEW_OWNED,
    VIEW_BUFFS,
    VIEW_ROLES,
    WEAPON_RATE,
    WEAPON_RATE_CASES,
    WEIGHTED,
    WEIGHTED_PER_SCENARIO,
    WEIGHTED_SEED,
    answers,
    best_kit_answers,
    best_kit_text,
    draw_weights,
    equip_now_text,
    kit_values,
    kit_values_text,
    mote_orders,
    mote_orders_text,
    texts,
    upgrade_view_answers,
    upgrade_view_text,
    weapon_rate_answers,
    weapon_rate_text,
    weighted_answers,
    weighted_text,
)

from trioforge.export import browser
from trioforge.site import build, data

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def made():
    return texts()


def test_the_committed_bundle_and_item_table_are_what_the_exporter_makes_of_the_invented_catalog(made):
    assert set(made) == {TRIO_FOLDER / "engine-l50.json", RESULTS / "items.json"}
    for path, text in made.items():
        assert path.is_file(), f"{path.name} is missing; run pipeline/tests/engine_fixture.py"
        assert path.read_text(encoding="utf-8") == text, f"{path.name} is stale; run pipeline/tests/engine_fixture.py"
        assert path.read_bytes().endswith(b"}\n") and b"\r" not in path.read_bytes()


def test_the_committed_equip_now_answers_are_what_the_reference_gives():
    assert EQUIP_NOW.is_file(), "fixtures/site/equip-now.json is missing; run pipeline/tests/engine_fixture.py"
    assert EQUIP_NOW.read_text(encoding="utf-8") == equip_now_text(), "equip-now.json is stale; run pipeline/tests/engine_fixture.py"


def test_the_committed_kit_values_are_what_the_reference_gives():
    assert KIT_VALUES.is_file(), "fixtures/site/kit-values.json is missing; run pipeline/tests/engine_fixture.py"
    assert KIT_VALUES.read_text(encoding="utf-8") == kit_values_text(), "kit-values.json is stale; run pipeline/tests/engine_fixture.py"


def test_the_committed_mote_orders_are_what_the_reference_gives():
    assert MOTE_ORDERS.is_file(), "fixtures/site/mote-orders.json is missing; run pipeline/tests/engine_fixture.py"
    assert MOTE_ORDERS.read_text(encoding="utf-8") == mote_orders_text(), "mote-orders.json is stale; run pipeline/tests/engine_fixture.py"


def test_the_mote_orders_cover_every_ending_the_limit_the_weights_mixed_tiers_and_the_runs():
    document = json.loads(MOTE_ORDERS.read_text(encoding="utf-8"))
    cases = document["cases"]
    assert {case["ending"] for case in cases} == {"top", "motes", "no-gain"}  # (a kit at the top, a limit, nothing that is left gains)
    assert any("weights" in case for case in cases) and any(case["motes"] is None for case in cases) and any(case["motes"] is not None for case in cases)
    assert any(step["motes"] > 1 for case in cases for step in case["steps"]), "a run of more than one mote"
    assert any(case["ending"] == "motes" and case["nextRun"] is not None for case in cases), "a run that does not fit the motes left"
    assert any(case["ending"] == "motes" and case["nextRun"] is None for case in cases) and all(case["nextRun"] is None for case in cases if case["ending"] != "motes")
    assert document["extra"], "the invented items the runs are made of (records of the item table, which the page's table of the fixture does not have)"
    for case in cases:
        assert len(case["kit"]) == 22
        steps = case["steps"]
        assert [step["index"] for step in steps] == list(range(1, len(steps) + 1))
        spent = 0
        for step in steps:
            spent += step["motes"]
            assert step["to"] - step["from"] == step["motes"] >= 1 and step["spent"] == spent  # a run of k is one line and spends k motes
        assert case["spent"] == spent and (case["motes"] is None or spent <= case["motes"])
        assert (case["ending"] == "motes") == (case["motes"] is not None and case["left"] > 0 and (spent == case["motes"] or case["nextRun"] is not None))
        assert (case["ending"] == "top") == (case["left"] == 0)
        tiers = [int(ident.rsplit("@", 1)[1]) if ident else None for ident in case["kit"]]
        assert case["left"] == sum(10 - t for t in tiers if t is not None) - spent  # every mote is one whole tier of one item
        if case["nextRun"] is not None:
            assert case["motes"] - spent < case["nextRun"]  # it did not fit
        before = Fraction(case["start"])
        for step in steps:
            after = Fraction(step["F"])
            assert Fraction(step["gain"]) == after - before > 0
            assert all(Fraction(amount) != 0 for _, amount in step["moved"])
            before = after
    assert len({tuple(int(i.rsplit("@", 1)[1]) for i in case["kit"] if i) for case in cases}) > 3  # (kits of different tiers, not one tier everywhere)


def test_the_kit_values_are_those_of_the_equip_now_kits_under_the_views_that_keep_them_the_best_arrangement_of_their_items():
    document = json.loads(KIT_VALUES.read_text(encoding="utf-8"))
    equip_now = json.loads(EQUIP_NOW.read_text(encoding="utf-8"))
    first = document["kits"][: len(equip_now["cases"])]
    assert [kit["kit"] for kit in first] == [case["kit"] for case in equip_now["cases"]]  # (the kits of Equip now, place for place, and then the small ones)
    assert [(kit["race"], kit["setup"]) for kit in first] == [(case["scenario"]["race"], case["scenario"]["setup"]) for case in equip_now["cases"]]
    assert len(document["kits"]) == len(equip_now["cases"]) + len(KIT_ONLY)
    seen = set()
    for row in document["values"]:
        assert 0 <= row["kit"] < len(document["kits"]) and row["role"] in VIEW_ROLES and row["buffs"] in VIEW_BUFFS
        assert (row["kit"], row["role"], row["buffs"]) not in seen
        seen.add((row["kit"], row["role"], row["buffs"]))
        numerator, denominator = (int(part) for part in row["F"].split("/"))
        assert abs(numerator / denominator - row["value"]) < 1e-9 and row["hasteAssumed"] >= 0
    for index in range(len(equip_now["cases"])):
        assert len({buffs for kit, _, buffs in seen if kit == index}) >= 3  # the buff sets the engine tests vary: at least three of the four
    assert {kit for kit, _, _ in seen} == set(range(len(document["kits"])))  # and every kit has a view
    # a shared kit is worth what it is as the answer it came from: valued at the haste it counts, the same kit under the same view is worth the same
    first = next(row for row in document["values"] if (row["kit"], row["role"], row["buffs"]) == (0, "balanced", "own"))
    assert first["hasteAssumed"] == equip_now["cases"][0]["hasteAssumed"] and first["value"] == equip_now["cases"][0]["value"]


def test_the_fixture_is_read_by_the_sites_reader_and_within_the_budgets_of_the_build(made):
    results = data.load_trio(TRIO_FOLDER)
    table = data.load_items(RESULTS, [results])
    assert results.bundle.raw == made[TRIO_FOLDER / "engine-l50.json"].encode("utf-8")
    assert table.raw == made[RESULTS / "items.json"].encode("utf-8")
    assert len(results.bundle.raw) <= build.LIMITS["engine_bundle"] and len(table.raw) <= build.LIMITS["engine_items"]
    assert results.bundle.document["data_release"] == table.document["data_release"] == results.meta.data_tag == "data-2026-10-14"


def test_every_item_a_scenario_owns_is_in_the_table_and_one_of_them_is_a_cap_the_trio_cannot_wear(made):
    table = json.loads(made[RESULTS / "items.json"])
    records = {browser.record_key(record): record for record in table["items"]}
    unwearable = {"w90040"}  # a cap for wizards
    owned = {key for case in CASES for key, _, _ in case["owned"]}
    assert owned <= set(records)
    assert unwearable <= owned and records["w90041"].get("owned_only") and "w90042" not in records  # hidden, and an ammunition: no place of a kit


def test_each_case_is_a_scenario_the_bundle_offers_and_its_answer_wears_only_what_is_owned():
    bundle = json.loads((TRIO_FOLDER / "engine-l50.json").read_text(encoding="utf-8"))
    for case, answer in zip(CASES, answers()["cases"], strict=True):
        scenario = case["scenario"]
        assert scenario == answer["scenario"]
        assert scenario["setup"] in bundle["roles"][scenario["role"]]["setups_by_evidence"][scenario["evidence"]], case["name"]
        assert scenario["buffs"] in bundle["buffs"] and scenario["race"] in [row["code"] for row in bundle["races"]]
        owned = Counter({f"{key}@{tier}": count for key, tier, count in case["owned"]})
        worn = Counter(ident for ident in answer["kit"] if ident is not None)
        assert len(answer["kit"]) == 22 and worn and all(owned[ident] >= times for ident, times in worn.items()), case["name"]
        assert "w90040@4" not in worn  # a cap the trio cannot wear is owned and not worn
        assert answer["hasteAssumed"] >= 0 and answer["value"] > 0 and "/" in answer["F"]
    assert len({case["scenario"]["race"] for case in CASES}) == 3  # three races, three roles, three buff sets


@pytest.fixture(scope="module")
def best_kit():
    return best_kit_answers()


def test_the_committed_best_kit_answers_are_what_the_reference_gives(best_kit):
    assert BEST_KIT.is_file(), "fixtures/site/best-kit.json is missing; run pipeline/tests/engine_fixture.py"
    assert BEST_KIT.read_text(encoding="utf-8") == best_kit_text(best_kit), "best-kit.json is stale; run pipeline/tests/engine_fixture.py"
    assert BEST_KIT.read_bytes().endswith(b"}\n") and b"\r" not in BEST_KIT.read_bytes()


def test_each_best_kit_view_is_one_the_bundle_offers_and_its_kit_wears_only_the_pool_of_its_tier(best_kit):
    bundle = json.loads((TRIO_FOLDER / "engine-l50.json").read_text(encoding="utf-8"))
    table = json.loads((RESULTS / "items.json").read_text(encoding="utf-8"))
    records = {browser.record_key(record): record for record in table["items"]}
    assert [row["name"] for row in best_kit["cases"]] == [case["name"] for case in BEST_KIT_CASES]
    for row in best_kit["cases"]:
        scenario, tier = row["scenario"], row["tier"]
        assert scenario["setup"] in bundle["roles"][scenario["role"]]["setups_by_evidence"][scenario["evidence"]], row["name"]
        assert scenario["buffs"] in bundle["buffs"] and scenario["race"] in [entry["code"] for entry in bundle["races"]], row["name"]
        assert 0 <= tier <= 10, row["name"]
        levels = {"strict"} if scenario["evidence"] == "strict" else {"strict", "wiki"}
        for answer in (row, row.get("own")):
            if answer is None:
                continue
            assert len(answer["kit"]) == 22 and answer["hasteAssumed"] >= 0 and answer["value"] > 0 and "/" in answer["F"], row["name"]
            for ident in {ident for ident in answer["kit"] if ident is not None}:
                key, at = ident.split("@")
                record = records[key]
                assert int(at) == tier, f"{row['name']}: {ident} is not at the tier of the view"
                assert record["evidence"]["level"] in levels and "not-for-bis" not in record["evidence"].get("codes", []), f"{row['name']}: {key} is not in the pool"
                assert not record.get("owned_only"), f"{row['name']}: {key} is hidden"
                assert "deity" not in record or scenario.get("deity") in record["deity"], f"{row['name']}: {key} is locked to another deity"


def test_the_best_kit_views_cover_the_sliders_the_buff_sets_a_deity_and_an_answer_that_moves(best_kit):
    cases = best_kit["cases"]
    weighted = [row for row in cases if "weights" in row]
    assert len(weighted) >= 10 and len(weighted) < len(cases)  # and a few at the role's own weights
    assert {row["scenario"]["buffs"] for row in cases} == {"own", "group", "group+enchanter", "raid"}
    assert any("deity" in row["scenario"] for row in cases) and {row["tier"] for row in cases} >= {0, 4}
    groups = {group: factor for row in weighted for group, factor in row["weights"].get("multipliers", {}).items()}
    assert set(groups) == {"AC", "MANA", "ATK+HASTE", "SV", "regen"}
    assert {factor for row in weighted for factor in row["weights"].get("multipliers", {}).values()} == {0.5, 2}
    assert any("custom" in row["weights"] for row in weighted) and any("regenT" in row["weights"] for row in weighted)
    # a weight that is not the role's own moves the answer: the value always, and for most of them the kit, and for one the buffs
    assert all(row["value"] != row["own"]["value"] for row in weighted)
    assert sum(row["kit"] != row["own"]["kit"] for row in weighted) >= 8
    assert any(row["kit"] == row["own"]["kit"] for row in weighted) and any(row["buffs"] != row["own"]["buffs"] for row in weighted)
    # the answer at the role's own weights is the shard-like one: a view without weights has no `own`
    assert all("own" not in row for row in cases if "weights" not in row)


# ---- the Upgrade modes under weights, and the weapon tier rate --------------------------------------------------------------------------
#
# fixtures/site/weighted.json: each Equip now scenario of the fixture with weights drawn from a fixed seed, and the answers of Python's reference (upgrade.equip_now, farm_path,
# best_sets and every_slot) for a profile whose weights are roles.weights_override's. fixtures/site/weapon-rate.json: best kits of whole-pool views at the weapon tier rate 5 and 10.


@pytest.fixture(scope="module")
def weighted():
    return weighted_answers()


def _legal_weight_number(value):
    """The rule the protocol holds a weight to: zero, or at least 0.000001 in size and of at most 6 significant digits."""
    return value == 0 or (abs(value) >= 1e-6 and float(f"{value:.6g}") == value)


def _exact(text):
    numerator, denominator = (int(part) for part in text.split("/"))
    return Fraction(numerator, denominator)


def test_the_committed_weighted_answers_are_what_the_reference_gives(weighted):
    assert WEIGHTED.is_file(), "fixtures/site/weighted.json is missing; run pipeline/tests/engine_fixture.py"
    assert WEIGHTED.read_text(encoding="utf-8") == weighted_text(weighted), "weighted.json is stale; run pipeline/tests/engine_fixture.py"
    assert WEIGHTED.read_bytes().endswith(b"}\n") and b"\r" not in WEIGHTED.read_bytes()


def test_the_weights_of_a_weighted_case_are_a_function_of_its_seed_and_are_numbers_the_protocol_takes(weighted):
    cases = weighted["cases"]
    assert len(cases) == len(CASES) * WEIGHTED_PER_SCENARIO
    assert len({case["seed"] for case in cases}) == len(cases)
    for case in cases:
        assert case["seed"].startswith(f"{WEIGHTED_SEED}:")
        assert draw_weights(case["seed"]) == case["weights"] == draw_weights(case["seed"])  # (a draw has no state but its seed)
        weights = case["weights"]
        assert set(weights) <= {"multipliers", "custom", "regenT"} and weights["multipliers"], case["name"]
        numbers = [*weights["multipliers"].values(), *weights.get("custom", {}).values(), *([weights["regenT"]] if "regenT" in weights else [])]
        assert all(_legal_weight_number(number) for number in numbers), case["name"]
        assert set(weights["multipliers"].values()) <= {0.5, 2}


def test_the_weighted_cases_cover_each_scenario_each_tier_mode_a_custom_weight_and_a_regen_window(weighted):
    cases = weighted["cases"]
    assert [case["scenario"] for case in cases[::WEIGHTED_PER_SCENARIO]] == [case["scenario"] for case in CASES]
    assert {json.dumps(case["tierMode"], sort_keys=True) for case in cases} == {json.dumps(mode, sort_keys=True) for mode in TIER_MODES}
    assert any("custom" in case["weights"] for case in cases) and any("regenT" in case["weights"] for case in cases)
    assert {group for case in cases for group in case["weights"]["multipliers"]} == {"AC", "MANA", "ATK+HASTE", "SV", "regen"}
    assert {factor for case in cases for factor in case["weights"]["multipliers"].values()} == {0.5, 2}


def test_the_weights_move_the_answer_of_every_mode_from_the_roles_own(weighted):
    own = json.loads(EQUIP_NOW.read_text(encoding="utf-8"))["cases"]
    for number, case in enumerate(weighted["cases"]):
        base = own[number // WEIGHTED_PER_SCENARIO]
        assert case["scenario"] == base["scenario"] and case["owned"] == base["owned"], case["name"]
        assert case["equipNow"]["F"] != base["F"], f"{case['name']}: the weights did not move the value of Equip now"
    assert sum(case["equipNow"]["kit"] != own[n // WEIGHTED_PER_SCENARIO]["kit"] for n, case in enumerate(weighted["cases"])) >= 2  # and some of them the kit


def test_each_weighted_answer_wears_only_what_is_owned_or_acquired_and_its_values_add_up(weighted):
    for case in weighted["cases"]:
        name = case["name"]
        owned = Counter({ident: count for ident, count in case["owned"]})
        equip = case["equipNow"]
        worn = Counter(ident for ident in equip["kit"] if ident is not None)
        assert len(equip["kit"]) == 22 and worn and all(owned[ident] >= times for ident, times in worn.items()), name
        assert equip["value"] > 0 and abs(float(_exact(equip["F"])) - equip["value"]) < 1e-9 * equip["value"], name

        path = case["farmPath"]
        assert path["steps"] == PATH_STEPS and path["stopped"] in ("limit", "no-gain") and 1 <= len(path["path"]) <= PATH_STEPS, name
        assert (path["stopped"] == "limit") == (len(path["path"]) == PATH_STEPS), name
        before = _exact(path["start"]["F"])
        for step in path["path"]:
            assert step["kind"] in ("new", "copy", "upgrade") and (step["sourceTier"] is not None) == (step["kind"] == "upgrade"), name
            assert _exact(step["F"]) - before == _exact(step["gain"]) > 0, f"{name}: a step gains exactly its value less the value before"
            before = _exact(step["F"])
        assert path["start"]["kit"] is not None and equip["hasteAssumed"] >= 0 and all(step["hasteAssumed"] >= 0 for step in path["path"]), name

        sets = case["bestSets"]
        assert [entry["k"] for entry in sets] == [2, 3], name
        for entry in sets:
            assert _exact(entry["baseline"]["F"]) == _exact(path["start"]["F"]), f"{name}: the baseline of a set is Equip now"
            assert _exact(entry["F"]) - _exact(entry["baseline"]["F"]) == _exact(entry["gain"]), name
            assert entry["hasteAssumed"] >= 0 and len(entry["acquired"]) <= entry["k"], name
            if not entry["acquired"]:
                assert entry["hasteAssumed"] == equip["hasteAssumed"], name  # nothing to add: Equip now's kit stands
            assert bool(entry["acquired"]) == (_exact(entry["gain"]) > 0), name
            if len(path["path"]) >= entry["k"]:  # the best k sets are never worth less than the first k steps (one candidate for a key)
                assert _exact(entry["F"]) >= _exact(path["path"][entry["k"] - 1]["F"]), name

        slots = case["everySlot"]
        assert slots["kit"] == equip["kit"] and slots["buffs"] == equip["buffs"] and slots["limit"] == SLOT_LIMIT, name
        assert [row["index"] for row in slots["rows"]] == list(range(22)), name
        for row in slots["rows"]:
            assert len(row["swaps"]) <= SLOT_LIMIT and row["current"] == equip["kit"][row["index"]], name
            deltas = [_exact(swap["delta"]) for swap in row["swaps"]]
            assert deltas == sorted(deltas, reverse=True), f"{name}: best gain first"
    assert any(case["bestSets"][0]["acquired"] for case in weighted["cases"]) and any(case["farmPath"]["path"] for case in weighted["cases"])
    assert any(row["swaps"] for case in weighted["cases"] for row in case["everySlot"]["rows"])


@pytest.fixture(scope="module")
def weapon_rate():
    return weapon_rate_answers()


def test_the_committed_weapon_rate_answers_are_what_the_reference_gives(weapon_rate):
    assert WEAPON_RATE.is_file(), "fixtures/site/weapon-rate.json is missing; run pipeline/tests/engine_fixture.py"
    assert WEAPON_RATE.read_text(encoding="utf-8") == weapon_rate_text(weapon_rate), "weapon-rate.json is stale; run pipeline/tests/engine_fixture.py"
    assert WEAPON_RATE.read_bytes().endswith(b"}\n") and b"\r" not in WEAPON_RATE.read_bytes()


def test_the_rules_own_weapon_rate_is_10_and_the_answer_without_a_rate_is_the_answer_at_10(weapon_rate):
    from trioforge.model.tables import load

    assert load().rules.get("tier.weapon_damage_pct") == 10
    for row in weapon_rate["cases"]:
        assert set(row["rates"]) == {"5", "10"} and row["rules"] == row["rates"]["10"], row["name"]


def test_the_weapon_rate_moves_the_answer_where_a_weapon_has_grown_and_nowhere_else(weapon_rate):
    cases = weapon_rate["cases"]
    assert [row["name"] for row in cases] == [case["name"] for case in WEAPON_RATE_CASES]
    for row in cases:
        if row["tier"] == 0:
            assert row["rates"]["5"] == row["rates"]["10"], f"{row['name']}: a weapon that has not grown does not read the rate"
    above = [row for row in cases if row["tier"] > 0]
    assert len(above) >= 5 and {row["tier"] for row in above} >= {4, 10}
    assert sum(row["rates"]["5"]["F"] != row["rates"]["10"]["F"] for row in above) >= 4  # the value moves
    assert any(row["rates"]["5"]["kit"] != row["rates"]["10"]["kit"] for row in above)  # and a kit moves
    assert {row["scenario"]["setup"] for row in above} >= {"2h", "dw", "1h-shield"} and any("weights" in row for row in cases)
    for row in cases:
        for answer in row["rates"].values():
            assert len(answer["kit"]) == 22 and answer["hasteAssumed"] >= 0 and answer["value"] > 0, row["name"]
            assert {ident.split("@")[1] for ident in answer["kit"] if ident is not None} <= {str(row["tier"])}, row["name"]


def test_the_committed_upgrade_view_is_what_the_reference_gives():
    document = upgrade_view_answers()
    assert UPGRADE_VIEW.is_file(), "fixtures/site/upgrade-view.json is missing; run pipeline/tests/engine_fixture.py"
    assert UPGRADE_VIEW.read_text(encoding="utf-8") == upgrade_view_text(document), "upgrade-view.json is stale; run pipeline/tests/engine_fixture.py"
    assert UPGRADE_VIEW.read_bytes().endswith(b"}\n") and b"\r" not in UPGRADE_VIEW.read_bytes()
    # the path gains something at every step, and the gear is the whole owned list
    steps = document["path"]
    assert len(steps) == 3 and all(step["gainValue"] > 0 for step in steps)
    assert len(document["owned"]) == len(UPGRADE_VIEW_OWNED)
