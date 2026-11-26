"""The opening build through a real precompute run, and what the site reader makes of the folder.

The function that picks the opening build (``roles.opening_role``) is tested over all 560 trios in test_builds.py. Here a run of the precompute on a small invented
pool (two races, a few tiers) shows that the build in ``defaults.json`` is the one the function names for the builds that have a setup at the evidence level of the
default view, also when that is not the first build the trio is offered, and that a Ranger whose strict pool has no bow does not open on the Archer.

Every item is invented (``test_precompute.make_item``); the classes are public game terms.
"""

from __future__ import annotations

import json

import pytest
from test_precompute import CATALOG, make_item, small_world, weapon, write_catalog, write_seen

from trioforge import precompute as pc
from trioforge.model.roles import opening_role, roles_for
from trioforge.model.weapons import setup_order
from trioforge.site import data

BOW = make_item("w9101", "Test Bow Alpha", ["RANGE"], classes=["RNG"], weapon=weapon("Archery", 12, 40), weight=3.0)  # a wiki item: seen in no game here
SHIELD_FOR_ALL = make_item("w9201", "Test Shield Omega", ["SECONDARY"], stats={"AC": 5, "STA": 3}, item_type="Shield", weight=2.0)  # a shield every class can wear: the casting builds have both setups
SEEN = {"w9001", "w9003", "w9006", "w9011", "w9013"}  # strict by their seen flag: a helm, a ring, a chest and two weapons; no bow among them
TIERS = (0, 4)


def run(tmp_path, trio, *, items=CATALOG, seen=None, **options):
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    catalog = write_catalog(root / "catalog.json", items)
    out = tmp_path / "results"
    seen_path = write_seen(root / "seen.json", seen) if seen is not None else None
    summary = pc.run("-".join(trio).lower(), out, seen_path=seen_path, catalog=catalog, tables_root=small_world(root / "world"), processes=1, tiers=TIERS, **options)
    assert not summary.violations, summary.violations
    return out / "-".join(trio).lower(), summary


def defaults_of(folder):
    return json.loads((folder / "defaults.json").read_text(encoding="utf-8"))


def test_a_ranger_with_no_tank_class_whose_strict_pool_has_no_bow_does_not_open_on_the_archer(tmp_path):
    """The strict pool (the default view's level, as it is not empty) has no bow and the wiki pool has one: the Archer has setups at the wiki level only, so the opening
    build is decided from the builds that have a setup at the strict level, the Archer rule is skipped, and the next rule gives the Melee damage build."""
    trio = ("RNG", "BRD", "ROG")
    assert roles_for(trio, bow=True)[:1] == ["melee"] and "ranged" in roles_for(trio, bow=True)
    folder, summary = run(tmp_path, trio, items=[*CATALOG, BOW], seen=SEEN, robustness=False)
    assert (folder / "defaults.json").is_file(), summary.notes  # (it was not written when the run opened on the Archer, which has no setup at the strict level)
    defaults = defaults_of(folder)
    assert defaults["view"]["evidence"] == "strict" and defaults["strict_pool_empty"] is False
    assert defaults["view"]["role"] == "melee"
    assert not any("defaults skipped" in note for note in summary.notes)


def test_a_ranger_whose_default_level_has_a_bow_opens_on_the_archer(tmp_path):
    folder, _ = run(tmp_path, ("RNG", "BRD", "ROG"), items=[*CATALOG, BOW], seen=SEEN | {"w9101"}, robustness=False)
    assert defaults_of(folder)["view"]["role"] == "ranged"


OPENINGS = [
    (("CLR", "SHD", "ENC"), "shield", "tank"),  # a tank class and two spell classes: the Shield caster, though the Tank is offered first
    (("SHM", "NEC", "WIZ"), "caster", "castertank"),  # no tank class, three spell classes, a pet class: the Caster, though the Caster tank is offered first (a Shaman is a class an Ogre or a Troll can be)
]


@pytest.fixture(scope="module", params=OPENINGS, ids=lambda case: "-".join(case[0]).lower())
def opening_case(request, tmp_path_factory):
    trio, opening, first = request.param
    folder, summary = run(tmp_path_factory.mktemp("opening"), trio, items=[*CATALOG, SHIELD_FOR_ALL])
    return trio, opening, first, folder, summary


def test_the_default_view_of_a_run_is_the_opening_build_when_it_is_not_the_first_offered(opening_case):
    trio, opening, first, folder, _ = opening_case
    assert roles_for(trio)[0] == first and opening in roles_for(trio) and opening != first
    assert opening_role(trio, roles_for(trio)) == opening
    assert defaults_of(folder)["view"]["role"] == opening


def test_the_site_reads_the_folder_of_such_a_run_and_opens_on_its_build(opening_case):
    trio, opening, _, folder, _ = opening_case
    results = data.load_trio(folder)
    assert results.defaults.role == opening
    assert opening in results.shards[(results.defaults.evidence, "own")].roles
    assert results.shards[(results.defaults.evidence, "own")].best_setup(results.defaults.race, opening, results.defaults.tier) == results.defaults.setup


def test_a_run_lists_the_setups_of_each_build_in_its_own_order(opening_case):
    """The shard lists the setups of a build in the order that breaks a tie, which the checker and the reader both follow: the Caster's stick comes first."""
    trio, _, _, folder, _ = opening_case
    shard = json.loads((folder / "wiki-own.json").read_text(encoding="utf-8"))
    for role, setups in shard["setups"].items():
        assert setups == sorted(setups, key=setup_order(role).index), role
    assert all(len(setups) == 2 for role, setups in shard["setups"].items() if role in ("shield", "castertank", "caster"))  # (both setups: the pool has a shield for every class)
    shown = data.load_trio(folder).shards[("wiki", "own")]
    for role in shown.roles:
        assert shown.setups_for(role) == tuple(shard["setups"][role]), role
    if "caster" in shard["setups"]:
        assert shard["setups"]["caster"] == ["stick", "1h-shield"]
        assert shard["setups"].get("castertank", ["1h-shield", "stick"]) == ["1h-shield", "stick"]
