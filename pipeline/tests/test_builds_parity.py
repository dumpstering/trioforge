"""The parity fixtures and the builds: what the plan and the sample must still cover after the builds and the spell-haste rule.

* the strata the plan guarantees include the Caster tank, the Archer and the profiles with the haste of the spells in them (the rule ``haste.assume_spell`` is false, so no
  default profile has it: the scenarios of the stratum are built with it on, as the Enchanter and belt tests are);
* the evaluations reach "haste-capped" again, as a regime that must be reached;
* the committed sample shows all of that in its manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trioforge.export import fixture_plan, fixture_tables
from trioforge.export.fixture_plan import MINI_STRATA, REQUIRED_STRATA, matrix_plan
from trioforge.model.tables import load as load_tables

REPO = Path(__file__).resolve().parents[2]
TABLES = load_tables()
PARITY = REPO / "fixtures" / "parity"


def test_the_required_strata_name_every_build_and_the_spell_haste_profiles():
    assert {f"role:{role}" for role in ("tank", "shield", "melee", "ranged", "castertank", "caster")} <= set(REQUIRED_STRATA)
    assert "spell-haste" in REQUIRED_STRATA and "spell-haste" in MINI_STRATA


@pytest.mark.parametrize("seed", [1, 2, 20261014])
def test_the_plan_has_two_scenarios_of_each_of_the_new_strata_for_every_seed(seed):
    counts = fixture_plan.tag_counts(matrix_plan(seed, TABLES))
    for stratum in ("role:castertank", "role:ranged", "spell-haste"):
        assert counts.get(stratum, 0) >= 2, stratum


def test_haste_capped_is_a_regime_the_evaluations_must_reach_again_and_is_no_longer_rare():
    assert "haste-capped" in fixture_tables.EVALUATE_COMMON and "haste-capped" in fixture_tables.EVALUATE_COVERAGE
    assert "haste-capped" not in fixture_tables.EVALUATE_RARE


def test_a_scenario_of_the_spell_haste_stratum_has_the_haste_of_the_spells_in_its_profile_and_its_buff_set_and_the_same_spec_without_it_has_none(inputs_real):
    from trioforge.export.fixture_cases import make_scenario

    plain = [spec for spec in matrix_plan(1, TABLES) if "spell-haste" not in spec.tags and spec.buffs in ("raid", "group+enchanter")][0]
    hasty = [spec for spec in matrix_plan(1, TABLES) if "spell-haste" in spec.tags][0]
    with_it = make_scenario(inputs_real, hasty)
    without = make_scenario(inputs_real, fixture_plan.ScenarioSpec(**{**hasty.__dict__, "spell_haste": False, "tags": ()}))
    assert with_it.profile.spell_haste > without.profile.spell_haste
    assert max(buff.haste for buff in with_it.buffset.optional) > 0 and max((buff.haste for buff in without.buffset.optional), default=0) == 0
    assert plain.spell_haste is False


@pytest.fixture(scope="module")
def inputs_real():
    from trioforge.export import fixtures

    return fixtures.shared_inputs()


def test_the_committed_sample_shows_haste_capped_evaluations_and_castertank_and_ranged_scenarios():
    manifest = json.loads((PARITY / "manifest.json").read_text(encoding="utf-8"))
    coverage = manifest["coverage"]
    assert coverage["evaluate"].get("haste-capped", 0) >= 1
    assert coverage["matrix"].get("role:castertank", 0) >= 2 and coverage["matrix"].get("role:ranged", 0) >= 2
    assert coverage["matrix"].get("spell-haste", 0) >= 2
