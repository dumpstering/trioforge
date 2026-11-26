"""The results the shard parity test holds the browser engine to are what the precompute writes of the invented catalog.

``fixtures/site/results-solved`` is the output of a narrow run of the real precompute on the invented catalog of the site fixture
(``shard_fixture.py`` makes it): shards that the solver wrote, with the browser's bundle and item table made from the very catalog it
solved. These tests make the files again and fail when a committed one differs, so that the fixture cannot fall behind the model, the
solver, the exporter or the rules, and check that the folder is what the parity test reads: the grid it promises is the grid the shards
hold, and its engine files are those of the site fixture's.
"""

from __future__ import annotations

import json

import pytest
from engine_fixture import RESULTS as SITE_RESULTS
from engine_fixture import SLUG
from shard_fixture import FILES, RACES, RESULTS, ROLES, SHARDS, TIERS, texts

from trioforge.model import weapons


@pytest.fixture(scope="module")
def made():
    return texts()


def test_the_committed_results_are_what_the_precompute_writes_of_the_invented_catalog(made):
    assert set(made) == set(FILES)
    for name, text in made.items():
        path = RESULTS / name
        assert path.is_file(), f"{name} is missing; run pipeline/tests/shard_fixture.py"
        assert path.read_bytes().decode("utf-8") == text, f"{name} is stale; run pipeline/tests/shard_fixture.py"
        assert b"\r" not in path.read_bytes()


def test_the_folder_holds_these_files_and_no_other():
    found = {path.relative_to(RESULTS).as_posix() for path in RESULTS.rglob("*") if path.is_file()}
    assert found == set(FILES)


def test_the_shards_hold_the_whole_narrow_grid_and_were_solved_with_the_tie_stage():
    for name in SHARDS:
        shard = json.loads((RESULTS / SLUG / name).read_text(encoding="utf-8"))
        evidence, buffs = name.removesuffix(".json").split("-")
        assert (shard["evidence"], shard["buffs"]) == (evidence, buffs)
        assert shard["solver"]["canonical"] is True and shard["partial"] is True
        assert [race["code"] for race in shard["races"]] == RACES and shard["roles"] == ROLES and shard["tiers"] == TIERS
        pairs = sum(len(setups) for setups in shard["setups"].values())
        assert pairs >= 4 and set(shard["setups"]) == set(ROLES)
        assert all(setup in weapons.SETUPS for setups in shard["setups"].values() for setup in setups)
        assert len(shard["scenarios"]) == len(RACES) * pairs * len(TIERS), name
        assert {(row[0], row[2], row[3]) for row in shard["scenarios"] if row[1] == "tank"} == {
            (race, tier, setup) for race in RACES for tier in TIERS for setup in shard["setups"]["tank"]
        }


def test_the_default_view_is_there_and_the_answer_names_two_races():
    defaults = json.loads((RESULTS / SLUG / "defaults.json").read_text(encoding="utf-8"))
    assert defaults["view"] == {"role": "tank", "tier": 4, "evidence": "strict", "buffs": "own"}
    assert sorted(row["race"] for row in defaults["races"]) == sorted(RACES) and {defaults["race"], defaults["runner_up_race"]} == set(RACES)


def test_the_engine_files_are_those_of_the_site_fixtures_engine_data():
    """Both folders hold the exporter's output for the same invented catalog: the bundle byte for byte, the item table as data (the
    catalog is read from a file here, in sorted keys, so the order of the stats of a record can differ)."""
    bundle = (RESULTS / SLUG / "engine-l50.json").read_bytes()
    assert bundle == (SITE_RESULTS / SLUG / "engine-l50.json").read_bytes()
    assert json.loads((RESULTS / "items.json").read_text(encoding="utf-8")) == json.loads(
        (SITE_RESULTS / "items.json").read_text(encoding="utf-8")
    )
