"""The site generator's only reader of precompute results: ``trioforge.site.data``.

The fixture ``fixtures/site/results/pal-mnk-ber`` is synthetic output in the exact shape the precompute writes (see
``trioforge.precompute.shards``): shards with an item table of rows, totals as rows, ``buff_sets``, ``data_release`` as the text
``data-YYYY-MM-DD``; runner-ups as pairs, one file for each role (with every tier of the run in it) and an index that lists them as a list; ``robust.json``
by role, tier and place; ``defaults.json`` with the view the default answer is taken from. If the precompute's format changes,
``data.py`` and these fixtures are the two things to change; nothing else in the site generator reads a results file, and
``test_site_integration.py`` keeps the fixtures honest by comparing their keys with those of a real run.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import shutil
from pathlib import Path

import pytest

from trioforge.data import races as races_module
from trioforge.model import items as model_items
from trioforge.model import roles as model_roles
from trioforge.model import weapons as model_weapons
from trioforge.precompute import shards as precompute_shards
from trioforge.site import data

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "fixtures" / "site" / "results" / "pal-mnk-ber"
CREDIT = data.Credit(release="data-2026-10-14", license="CC BY-SA 4.0", attribution="Item data adapted from a wiki (CC BY-SA 4.0)")
SHARDS = ("strict-own", "strict-group", "wiki-own", "wiki-group")


@pytest.fixture(scope="module")
def results():
    return data.load_trio(FIXTURE)


@pytest.fixture
def broken(tmp_path):
    """A scratch copy of the fixture directory plus a helper that rewrites one of its files."""
    target = tmp_path / "pal-mnk-ber"
    shutil.copytree(FIXTURE, target)

    def edit(name, change):
        path = target / f"{name}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        change(document)
        path.write_text(json.dumps(document), encoding="utf-8")
        return target

    edit.root = target
    return edit


@pytest.fixture
def broken_runnerup(broken):
    """Rewrite one runner-up file and its index entry (unless told not to), so only the change itself is refused."""

    def edit(name, change, *, reindex=True):
        folder = broken.root / "runnerups"
        document = json.loads((folder / name).read_text(encoding="utf-8"))
        change(document)
        body = json.dumps(document).encode("utf-8")
        (folder / name).write_bytes(body)
        if reindex:
            index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
            entry = next(entry for entry in index["files"] if entry["file"] == name)
            entry.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
            (folder / "index.json").write_text(json.dumps(index), encoding="utf-8")
        return broken.root

    edit.root = broken.root
    return edit


def edit_index(root, change):
    path = root / "runnerups" / "index.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document), encoding="utf-8")


def entry_of(document, name):
    return next(entry for entry in document["files"] if entry["file"] == name)


# ---- the vocabulary matches the model's and the precompute's, so data.py can stay free of their imports -------------------


def test_the_vocabulary_matches_the_model_and_the_precompute():
    assert data.SLOT_INSTANCES == model_items.SLOT_INSTANCES
    assert data.SETUPS == model_weapons.SETUPS
    assert data.ROLES == model_roles.ROLES
    assert data.RACE_CODES == races_module.RACE_CODES
    assert len(data.SLOT_INSTANCES) == 22
    assert data.PLACES == precompute_shards.PLACES and len(data.PLACES) == 22
    assert data.ITEM_KEYS == precompute_shards.ITEM_KEYS
    assert data.TOTALS_KEYS == precompute_shards.TOTALS_KEYS
    assert data.FORMAT_VERSION == precompute_shards.FORMAT
    assert data.SHARD_NAMES == tuple(name.removesuffix(".json") for name in precompute_shards.SHARD_NAMES)
    assert set(data.OTHER_SLOTS) == {"AMMO", "CHARM", "POWERSOURCE"}  # slots of the catalog that no place of a kit has


# ---- reading the fixture -----------------------------------------------------------------------------------------


def test_the_metadata_comes_from_the_results(results):
    meta = results.meta
    assert meta.slug == "pal-mnk-ber"
    assert meta.trio == ("PAL", "MNK", "BER")  # EQ class-id order
    assert meta.level == 50
    assert meta.data_tag == "data-2026-10-14"
    assert meta.data_date == "2026-10-14"  # the date inside the tag
    assert meta.game_patch == "2026-09-22"
    assert meta.rules_version == "2026-11-19"
    assert meta.partial is True  # the fixture holds three races and three tiers, as a narrowed run would write them


def test_all_four_shards_are_read(results):
    assert sorted(results.shards) == [("strict", "group"), ("strict", "own"), ("wiki", "group"), ("wiki", "own")]
    for (evidence, buffs), shard in results.shards.items():
        assert (shard.evidence, shard.buffs) == (evidence, buffs)


def test_the_grid_is_derived_from_the_rows(results):
    shard = results.shards[("strict", "own")]
    assert shard.races == ("OGR", "TRL", "ELF")
    assert shard.roles == ("tank", "melee")
    assert shard.tiers == (0, 4, 10)
    assert shard.setups_for("tank") == ("1h-shield", "2h", "dw")
    assert shard.setups_for("melee") == ("2h", "dw")  # Melee never offers 1H + shield
    assert len(shard.scenarios) == 3 * 5 * 3


def test_a_scenario_has_its_kit_value_and_totals(results):
    shard = results.shards[("strict", "own")]
    scenario = shard.scenario("OGR", "tank", 4, "dw")
    assert (scenario.race, scenario.role, scenario.tier, scenario.setup) == ("OGR", "tank", 4, "dw")
    assert scenario.value == 10720.0
    assert scenario.gain == 7769.5
    assert len(scenario.kit) == 22
    assert scenario.kit[0].name == "Helm of the Stoneward"
    assert scenario.kit[19] is None  # an empty slot is None, not an item
    assert scenario.kit[20].name == "Ferryman's Pike"
    assert scenario.kit[21].name == "Pellbrook Mallet"
    totals = scenario.totals
    assert (totals.ac, totals.hp, totals.mana, totals.end, totals.haste, totals.atk) == (666, 2880, 1236, 3094, 57, 788)
    assert data.SCHOOLS == ("MAGIC", "FIRE", "COLD", "DISEASE", "POISON")
    assert totals.resists == (86, 73, 68, 64, 61)  # in the order of SCHOOLS, whatever the order of the file's columns
    assert totals.regen == (14, 7, 8)
    assert scenario.buffs == ()  # no optional buff is kept up in this view
    assert scenario.haste_assumed == 66  # the weapons were scored at 66% haste


def test_the_optional_buffs_and_the_assumed_haste_are_read_for_every_scenario(results):
    own = results.shards[("strict", "own")]
    assert own.scenario("OGR", "tank", 4, "1h-shield").buffs == ()  # (no optional buff kept up in this view)
    assert own.scenario("OGR", "tank", 4, "1h-shield").haste_assumed == 66
    assert own.scenario("OGR", "tank", 10, "1h-shield").buffs == (20011,)  # (the Tank at +10 keeps one up, a one-element tuple)
    assert own.scenario("OGR", "tank", 10, "1h-shield").haste_assumed == 85
    group = results.shards[("strict", "group")]
    assert group.scenario("OGR", "tank", 4, "dw").buffs == (20001, 20002)
    group = results.shards[("strict", "group")]
    assert group.scenario("TRL", "melee", 10, "2h").buffs == (20001, 20002, 20003)
    assert group.scenario("TRL", "melee", 10, "2h").haste_assumed == 85  # held at the Monk cap
    assert group.scenario("OGR", "tank", 0, "dw").haste_assumed == 70
    assert all(isinstance(i, int) for s in group.scenarios for i in s.buffs)


def test_the_solver_options_and_build_options_are_kept_as_recorded(results):
    shard = results.shards[("wiki", "own")]
    assert shard.solver["canonical"] is True and shard.solver["presolve"] == "off" and shard.solver["time_limit"] is None
    assert shard.solver["kept_first"] == 0
    assert shard.build_options == {"any_rule": "all", "haste_assumed": None}


def test_a_missing_scenario_is_none(results):
    shard = results.shards[("strict", "own")]
    assert shard.scenario("OGR", "melee", 4, "1h-shield") is None
    assert shard.scenario("HUM", "tank", 4, "dw") is None


def test_the_best_setup_is_the_highest_value_with_ties_going_to_the_earlier_setup(results):
    shard = results.shards[("strict", "own")]
    assert shard.best_setup("OGR", "tank", 4) == "dw"
    assert shard.best_setup("OGR", "tank", 10) == "1h-shield"  # (the best setup moves with the tier)
    assert shard.best_setup("OGR", "melee", 4) == "2h"
    assert results.shards[("wiki", "own")].best_setup("OGR", "tank", 4) == "1h-shield"  # (and with the evidence level)
    scenarios = tuple(
        dataclasses.replace(s, value=100.0) if s.role == "tank" else s for s in shard.scenarios
    )
    tied = data.Shard(shard.evidence, shard.buffs, shard.items, scenarios)
    assert tied.best_setup("OGR", "tank", 4) == "1h-shield"  # SETUPS order breaks the tie


def test_text_is_passed_through_untouched(results):
    """The reader never edits a name: escaping is the templates' and the DOM code's job."""
    shard = results.shards[("strict", "own")]
    assert shard.scenario("OGR", "tank", 4, "dw").kit[17].name == "<b>x</b>"
    assert shard.scenario("OGR", "tank", 4, "dw").kit[17].source == 'Plane <i>of</i> Hate & "Fear"'


def test_items_carry_their_rule_arrival_source_evidence_and_deity(results):
    item = results.shards[("strict", "own")].scenario("OGR", "tank", 0, "dw").kit[4]
    assert item.name == "Choker of Seven Pebbles"
    assert (item.tier_rule, item.arrival, item.evidence, item.deity) == ("fixed0", 0, "strict", None)
    assert item.slots == ("NECK",)
    wiki_only = [i for i in results.shards[("wiki", "own")].items if i.evidence == "wiki"]
    assert [i.name for i in wiki_only] == ["Crown of the Vanguard"]
    drop = results.shards[("strict", "own")].scenario("OGR", "tank", 4, "dw").kit[0]
    assert (drop.tier_rule, drop.arrival) == ("drop", 4)  # the highest tier a copy exists at without merging


def test_the_defaults_file(results):
    defaults = results.defaults
    assert (defaults.race, defaults.runner_up) == ("OGR", "TRL")
    assert defaults.margin == 812.5
    assert defaults.flips == ("Iksar, if Iksar AC stacks inside the cap (test B17)",)
    # the view the answer is taken from, and the best weapon setup of the default race in it
    assert (defaults.role, defaults.tier, defaults.evidence, defaults.buffs, defaults.setup) == ("tank", 4, "strict", "own", "dw")
    assert defaults.value == 10720.0 and defaults.strict_empty is False and defaults.robustness == "done"


def test_runner_ups_come_as_one_file_for_each_role_with_every_tier_of_the_run_and_an_index(results):
    runnerups = results.runnerups
    assert [f.name for f in runnerups.files] == ["tank.json", "melee.json"]  # in role order
    assert [(f.role, f.tiers) for f in runnerups.files] == [(role, (0, 4, 10)) for role in ("tank", "melee")]
    assert runnerups.roles() == ("tank", "melee")
    assert runnerups.pairs() == tuple((role, tier) for role in ("tank", "melee") for tier in (0, 4, 10))
    for file in runnerups.files:
        body = (FIXTURE / "runnerups" / file.name).read_bytes()
        assert (file.size, file.sha256) == (len(body), hashlib.sha256(body).hexdigest())
    assert len(runnerups.views) == 3 * 3 * 2  # three races at three tiers in the file of each of the two builds
    assert results.shards[("strict", "own")].tiers == (0, 4, 10)  # the tiers of the run: what the files of the roles hold


def test_a_slot_has_up_to_three_runner_ups_that_need_no_deity_and_at_most_one_that_does(results):
    view = results.runnerups.view("OGR", "tank", 4)
    assert view.setup == "dw"
    assert len(view.slots) == 22
    for swaps in view.slots:
        assert sum(1 for s in swaps if s.item.deity is None) <= 3
        assert sum(1 for s in swaps if s.item.deity is not None) <= 1
    head = view.slots[0]
    # the one that needs a deity comes first, as the precompute writes it: it is kept only when it beats the best of the others
    assert [s.item.name for s in head] == ["Crown of the Tribunal", "Steel Cap of Valor", "Crown of the Vanguard"]
    assert head[0].item.deity == ("The Tribunal",)
    assert head[0].delta == 6.75  # a swap of a locked item can be better than the pick, which no other swap can
    assert all(s.delta < 0 for s in head[1:])  # a swap of an item anyone can wear can only lose value
    assert [s.delta for s in head[1:]] == sorted((s.delta for s in head[1:]), reverse=True)
    chest = view.slots[13]
    assert chest[0].item.name == "Mantle of the Faithful" and chest[0].item.deity == ("The Tribunal", "Rodcet Nife")
    assert chest[0].delta == -9.0 and chest[0].delta > chest[1].delta  # worse than the pick, yet better than the best other swap
    assert results.runnerups.view("HUM", "tank", 4) is None
    assert results.runnerups.view("OGR", "caster", 4) is None


def test_the_badge_wording_for_an_item_that_needs_a_deity():
    from trioforge.site import view

    assert view.deity_text(("The Tribunal",)) == "Needs deity: The Tribunal"
    assert view.deity_text(("The Tribunal", "Rodcet Nife")) == "Needs deity: The Tribunal or Rodcet Nife"
    assert view.deity_text(None) == "" and view.deity_text(()) == ""


def test_robustness_covers_the_default_race_at_tiers_4_and_10(results):
    robust = results.robust
    assert robust.race == "OGR"
    labels = robust.view("tank", 4)
    assert len(labels) == 22 and labels[0] == "robust"  # in the order of the places of a kit
    assert labels[16] == 'depends on the "AC" & mana weight (x2)'
    assert labels[13] == "depends on the Monk curve (test B9)"
    assert robust.view("tank", 0) is None
    assert robust.view("caster", 4) is None


def test_the_seals_say_what_view_they_were_made_for_and_hold_for_that_view_alone(results):
    """The precompute seals each role at the default race with the default evidence level, own buffs and the role's best weapon
    setup. A page that shows another setup, evidence level or buff set must not show those seals as if they were its own."""
    robust = results.robust
    assert robust.sealed("tank", 4) == data.Sealed(setup="dw", evidence="strict", buffs="own")
    assert robust.sealed("tank", 10) == data.Sealed(setup="1h-shield", evidence="strict", buffs="own")  # the Tank's best here
    assert robust.sealed("melee", 4) == data.Sealed(setup="2h", evidence="strict", buffs="own")
    assert robust.sealed("tank", 0) is None and robust.sealed("caster", 4) is None
    labels = robust.view("tank", 4)
    assert robust.labels_for("OGR", "tank", 4, "dw", "strict", "own") == labels
    for race, setup, evidence, buffs in (
        ("TRL", "dw", "strict", "own"),  # another race: the seals are for the default race
        ("OGR", "2h", "strict", "own"),  # another setup
        ("OGR", "1h-shield", "strict", "own"),
        ("OGR", "dw", "wiki", "own"),  # another evidence level
        ("OGR", "dw", "strict", "group"),  # other buffs
    ):
        assert robust.labels_for(race, "tank", 4, setup, evidence, buffs) is None, (race, setup, evidence, buffs)
    assert robust.labels_for("OGR", "tank", 0, "dw", "strict", "own") is None  # a tier with no seals
    assert robust.labels_for("OGR", "caster", 4, "dw", "strict", "own") is None


def test_the_seals_of_a_page_whose_default_answer_is_the_wiki_level_are_for_that_level(tmp_path):
    """While no item is strict the default answer, and so the seals, are made at the wiki level."""
    scratch = tmp_path / "pal-mnk-ber"
    shutil.copytree(FIXTURE, scratch)
    path = scratch / "defaults.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["view"]["evidence"] = "wiki"
    path.write_text(json.dumps(document), encoding="utf-8")
    for name in sorted(p.name for p in (scratch / "runnerups").glob("*.json") if p.name != "index.json"):
        file = scratch / "runnerups" / name
        body = json.loads(file.read_text(encoding="utf-8"))
        body["evidence"] = "wiki"
        file.write_text(json.dumps(body), encoding="utf-8")
    index_path = scratch / "runnerups" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["evidence"] = "wiki"
    for entry in index["files"]:
        raw = (scratch / "runnerups" / entry["file"]).read_bytes()
        entry.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    index_path.write_text(json.dumps(index), encoding="utf-8")
    robust = data.load_trio(scratch).robust
    assert robust.sealed("tank", 4).evidence == "wiki"
    assert robust.labels_for("OGR", "tank", 4, robust.sealed("tank", 4).setup, "strict", "own") is None


def test_rounding_to_three_decimals_happens_in_the_reader(broken):
    def change(document):
        document["scenarios"][0][5] = 10720.123456
        document["scenarios"][0][6] = 1.0004999

    root = broken("strict-own", change)
    scenario = data.load_trio(root).shards[("strict", "own")].scenarios[0]
    assert scenario.value == 10720.123
    assert scenario.gain == 1.0


# ---- what a real run has that a tidy fixture does not -----------------------------------------------------------------------


def test_a_total_may_be_negative(broken):
    """A naked character can have a regeneration below zero, and a cursed item a resist: the totals are signed whole numbers."""
    index = data.TOTALS_KEYS.index("manareg")

    def change(document):
        document["totals"][0][index] = -3
        document["totals"][0][data.TOTALS_KEYS.index("fire")] = -20

    totals = data.load_trio(broken("strict-own", change)).shards[("strict", "own")].scenarios[0].totals
    assert totals.regen[1] == -3 and totals.resists[data.SCHOOLS.index("FIRE")] == -20


def test_an_item_may_list_slots_that_no_place_of_a_kit_has(broken):
    """A thrown weapon fits the range place and the ammo place; the catalog's slots include AMMO, CHARM and POWERSOURCE."""

    def change(document):
        shot = next(row for row in document["items"] if row[1] == "<b>x</b>")  # the item worn in the range place of the default kit
        assert shot[2] == ["RANGE"]
        shot[2] = ["RANGE", "AMMO"]

    shard = data.load_trio(broken("strict-own", change)).shards[("strict", "own")]
    assert shard.scenario("OGR", "tank", 4, "dw").kit[17].slots == ("RANGE", "AMMO")


def test_a_summoned_item_has_no_arrival_tier_and_the_browser_file_says_null(broken):
    def change(document):
        document["items"][0][3] = "spell"
        document["items"][0][4] = None

    shard = data.load_trio(broken("strict-own", change)).shards[("strict", "own")]
    item = shard.items[0]
    assert (item.tier_rule, item.arrival) == ("spell", None)
    row = next(row for row in json.loads(data.site_shard_json(shard, CREDIT))["items"] if row[0] == item.key)
    assert row[2:4] == ["spell", None]


def test_the_default_evidence_can_be_wiki_while_nothing_is_strict(broken):
    """With no seen flags the strict level is empty, and the precompute takes the default answer from the wiki level."""
    root = broken.root
    for name in SHARDS:
        path = root / f"{name}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        if name.startswith("strict"):
            document["flags"] = ["strict pool empty"]
            document["pool"] = 0
        path.write_text(json.dumps(document), encoding="utf-8")

    def wiki(document):
        document["view"]["evidence"] = "wiki"
        document["strict_pool_empty"] = True

    broken("defaults", wiki)
    # the runner-ups are for the default evidence level: they say so, and the reader checks that they agree
    with pytest.raises(data.ResultsError, match=r"runnerups/index\.json: evidence: must be 'wiki'"):
        data.load_trio(root)
    folder = root / "runnerups"
    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    for entry in index["files"]:
        document = json.loads((folder / entry["file"]).read_text(encoding="utf-8"))
        document.update(evidence="wiki", evidence_fallback=True)
        body = json.dumps(document).encode("utf-8")
        (folder / entry["file"]).write_bytes(body)
        entry.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    index.update(evidence="wiki", evidence_fallback=True)
    (folder / "index.json").write_text(json.dumps(index), encoding="utf-8")
    results = data.load_trio(root)
    assert (results.defaults.evidence, results.defaults.strict_empty) == ("wiki", True)


# ---- a shard can have fewer setups than another ------------------------------------------------------------------------------
# The weapon setups follow the solve pool of each evidence level, and the strict pool is a part of the wiki pool: a strict pool
# with no shield the trio can wear has no 1h-shield setup, while the wiki pool, which has one, does. So the shards need not hold
# the same setups: each carries its own, and the reader asks them only for the same races, roles and tiers.


def rewrite(root, name, change):
    """Change one JSON file of a scratch copy of the fixture (a shard, ``defaults``...)."""
    path = root / f"{name}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document), encoding="utf-8")


def drop_setup(document, setup):
    """Take a setup out of a shard document, as a precompute run does for a level whose pool has no shield for the trio."""
    document["scenarios"] = [row for row in document["scenarios"] if row[3] != setup]
    document["setups"] = {role: [s for s in setups if s != setup] for role, setups in document["setups"].items()}


@pytest.fixture
def no_strict_shield(broken, broken_runnerup):
    """The fixture as a run would write it if no shield were in the strict pool: the strict shards have no 1h-shield rows, and
    the Tank, whose best setup that was, has the dual wield in its runner-ups. The wiki shards are as they were."""
    for name in ("strict-own", "strict-group"):
        broken(name, lambda document: drop_setup(document, "1h-shield"))
    broken_runnerup("tank.json", lambda document: [view.__setitem__(2, "dw") for view in document["views"]])
    return broken.root


def test_a_level_whose_pool_has_no_shield_has_fewer_setups_than_the_wiki_level(no_strict_shield):
    results = data.load_trio(no_strict_shield)
    for buffs in ("own", "group"):
        strict, wiki = results.shards[("strict", buffs)], results.shards[("wiki", buffs)]
        assert [strict.setups_for(role) for role in strict.roles] == [("2h", "dw")] * 2
        assert [wiki.setups_for(role) for role in wiki.roles] == [("1h-shield", "2h", "dw"), ("2h", "dw")]
        assert (strict.races, strict.roles, strict.tiers) == (wiki.races, wiki.roles, wiki.tiers)
    strict, wiki = results.shards[("strict", "own")], results.shards[("wiki", "own")]
    assert strict.scenario("OGR", "tank", 4, "1h-shield") is None and wiki.scenario("OGR", "tank", 4, "1h-shield") is not None
    assert (strict.best_setup("OGR", "tank", 4), wiki.best_setup("OGR", "tank", 4)) == ("dw", "1h-shield")  # (the shield is the Tank's best at the wiki level only)
    assert results.defaults.setup == "dw" and results.runnerups.view("OGR", "tank", 4).setup == "dw"


def test_every_shard_carries_its_own_setups_and_none_is_compared_with_another(broken):
    """The reader asks the four shards for the same races, roles and tiers, and nothing about their setups: a shard has the
    setups it has rows for, so the page offers a switch only the setups of the shard it shows."""
    broken("strict-group", lambda document: drop_setup(document, "1h-shield"))  # one buff set of a level lacks the setup ...
    root = broken("wiki-own", lambda document: drop_setup(document, "dw"))  # ... and a wiki shard lacks another
    results = data.load_trio(root)
    seen = {key: [shard.setups_for(role) for role in shard.roles] for key, shard in results.shards.items()}
    assert seen[("strict", "own")] == [("1h-shield", "2h", "dw"), ("2h", "dw")]
    assert seen[("strict", "group")] == [("2h", "dw")] * 2
    assert seen[("wiki", "own")] == [("1h-shield", "2h"), ("2h",)]
    assert seen[("wiki", "group")] == [("1h-shield", "2h", "dw"), ("2h", "dw")]
    assert results.shards[("strict", "group")].best_setup("OGR", "tank", 10) == "dw"  # the best of the shard's own setups (no shield in it)
    assert results.shards[("strict", "own")].best_setup("OGR", "tank", 10) == "1h-shield"
    assert results.shards[("wiki", "own")].best_setup("OGR", "tank", 4) == "1h-shield"  # (no dual wield in this one: the best of the setups it has, and the shield is the best of them)
    assert results.shards[("wiki", "own")].best_setup("OGR", "melee", 4) == "2h" and results.shards[("wiki", "own")].setups_for("tank") == ("1h-shield", "2h")


def test_a_default_answer_with_a_setup_its_own_level_does_not_have_is_refused(no_strict_shield):
    rewrite(no_strict_shield, "defaults", lambda document: document.update(setup="1h-shield"))  # the default view is the strict level's
    with pytest.raises(data.ResultsError, match=r"defaults\.json: setup: must be one of 2h, dw"):
        data.load_trio(no_strict_shield)


def test_the_default_answer_and_the_runner_ups_are_read_against_the_level_of_the_default_view(no_strict_shield, broken_runnerup):
    root = no_strict_shield

    def wiki_tank(document):  # the default view is the wiki level's (as while no item is strict), where a Tank's best setup is the shield
        document["view"].update(role="tank", evidence="wiki")
        document.update(setup="1h-shield", strict_pool_empty=True)

    rewrite(root, "defaults", wiki_tank)
    for role in ("tank", "melee"):
        broken_runnerup(f"{role}.json", lambda document: document.update(evidence="wiki", evidence_fallback=True))
    edit_index(root, lambda document: document.update(evidence="wiki", evidence_fallback=True))
    results = data.load_trio(root)  # the strict level has no 1h-shield, and the answer of the wiki level may have it
    assert (results.defaults.evidence, results.defaults.role, results.defaults.setup) == ("wiki", "tank", "1h-shield")
    broken_runnerup("tank.json", lambda document: [view.__setitem__(2, "1h-shield") for view in document["views"]])
    assert data.load_trio(root).runnerups.view("OGR", "tank", 4).setup == "1h-shield"


# ---- the browser format --------------------------------------------------------------------------------------------


def test_the_browser_shard_is_compact_arrays_the_js_can_index(results):
    shard = results.shards[("strict", "own")]
    document = json.loads(data.site_shard_json(shard, CREDIT))
    assert document["v"] == 1 and document["ev"] == "strict" and document["buffs"] == "own"
    assert set(document) == {"v", "release", "license", "attribution", "ev", "buffs", "items", "kits", "totals", "rows"}
    item = document["items"][0]
    assert len(item) == 7  # key, name, tier rule, arrival, source, evidence, deity text
    assert all(len(kit) == 22 for kit in document["kits"])
    assert all(len(row) == 9 for row in document["rows"])  # ... totals index, assumed haste
    assert all(len(total) == 14 for total in document["totals"])
    row = next(r for r in document["rows"] if r[:4] == ["OGR", "tank", 4, "dw"])
    kit = document["kits"][row[4]]
    assert document["items"][kit[17]][1] == "<b>x</b>"  # still plain data
    assert kit[19] == -1
    assert row[5] == 10720.0 and row[6] == 7769.5 and row[8] == 66
    assert document["totals"][row[7]] == [666, 2880, 1236, 3094, 57, 788, 86, 73, 68, 64, 61, 14, 7, 8]


def test_the_browser_runnerups_are_one_file_for_a_role_with_every_tier_and_every_race(results):
    document = json.loads(data.site_runnerups_json(results.runnerups, "tank", CREDIT))
    assert document["v"] == data.RUNNERUPS_VERSION == 2 and document["role"] == "tank" and document["tiers"] == [0, 4, 10]
    assert set(document) == {"v", "release", "license", "attribution", "role", "tiers", "items", "views"}
    assert [v[:2] for v in document["views"]] == [[tier, race] for tier in (0, 4, 10) for race in ("OGR", "TRL", "ELF")]  # by tier, then the file's races
    tier, race, setup, slots = next(v for v in document["views"] if v[:2] == [4, "OGR"])
    assert setup == "dw" and len(slots) == 22
    assert all(len(pair) == 2 for view in document["views"] for swaps in view[3] for pair in swaps)  # [item index, delta]
    head = slots[0]
    assert [document["items"][i][1] for i, _delta in head] == ["Crown of the Tribunal", "Steel Cap of Valor", "Crown of the Vanguard"]
    assert [delta for _i, delta in head] == [6.75, -12.0, -19.25]
    assert document["items"][head[0][0]][6] == ["The Tribunal"]  # the deity names, as a list
    assert document["items"][head[1][0]][6] == []
    assert all(len(item) == 7 for item in document["items"])
    keys = [item[0] for item in document["items"]]
    assert len(set(keys)) == len(keys)  # one table for the file, and an item that two tiers swap in is in it once
    used = {i for view in document["views"] for swaps in view[3] for i, _delta in swaps}
    assert used == set(range(len(document["items"])))  # numbered by first use, and no item that no view names
    other = json.loads(data.site_runnerups_json(results.runnerups, "melee", CREDIT))
    assert other["role"] == "melee" and other["tiers"] == [0, 4, 10]
    assert next(v for v in other["views"] if v[:2] == [10, "OGR"])[2] == "2h"
    with pytest.raises(ValueError, match="no runner-up file for the caster role"):
        data.site_runnerups_json(results.runnerups, "caster", CREDIT)


def test_the_browser_robust_file(results):
    robust = json.loads(data.site_robust_json(results.robust, CREDIT))
    assert robust["v"] == 2 and robust["race"] == "OGR"  # version 2: each view says what it was sealed for
    assert ["tank", 4] == next(v for v in robust["views"] if v[:2] == ["tank", 4])[:2]
    assert [v[:2] for v in robust["views"]] == [[role, tier] for role in ("tank", "melee") for tier in (4, 10)]
    # [role, tier, setup, evidence, buffs, 22 labels]
    assert [v[2:5] for v in robust["views"]] == [
        ["dw", "strict", "own"], ["1h-shield", "strict", "own"],
        ["2h", "strict", "own"], ["2h", "strict", "own"],
    ]  # fmt: skip
    assert all(len(v) == 6 and len(v[5]) == 22 for v in robust["views"])
    assert robust["views"][0][5] == list(results.robust.view("tank", 4))


def test_the_browser_json_is_deterministic(results):
    shard = results.shards[("wiki", "group")]
    assert data.site_shard_json(shard, CREDIT) == data.site_shard_json(shard, CREDIT)
    assert data.site_shard_json(shard, CREDIT).endswith("\n")


def test_every_browser_file_starts_with_the_release_the_licence_and_the_attribution(results):
    """Every file the browser fetches says which data release it was made from, under which licence and with what attribution:
    the page refuses a file of another release, and a copy of the file anywhere carries its credit with it."""
    documents = [
        json.loads(data.site_shard_json(results.shards[("wiki", "group")], CREDIT)),
        json.loads(data.site_runnerups_json(results.runnerups, "tank", CREDIT)),
        json.loads(data.site_robust_json(results.robust, CREDIT)),
    ]
    for document in documents:
        assert list(document)[:4] == ["v", "release", "license", "attribution"]
        assert (document["release"], document["license"], document["attribution"]) == (CREDIT.release, CREDIT.license, CREDIT.attribution)
    other = data.Credit(release="data-2026-11-01", license="CC BY-SA 4.0", attribution="x")
    assert json.loads(data.site_robust_json(results.robust, other))["release"] == "data-2026-11-01"


# ---- refusing what cannot be trusted -----------------------------------------------------------------------------------


def test_a_missing_file_is_named(broken):
    (broken.root / "wiki-own.json").unlink()
    with pytest.raises(data.ResultsError, match=r"wiki-own\.json"):
        data.load_trio(broken.root)


def test_a_directory_must_hold_a_known_trio_slug(tmp_path):
    other = tmp_path / "pal-pal-ber"
    shutil.copytree(FIXTURE, other)
    with pytest.raises(data.ResultsError, match="pal-pal-ber"):
        data.load_trio(other)
    wrong_order = tmp_path / "ber-mnk-pal"
    shutil.copytree(FIXTURE, wrong_order)
    with pytest.raises(data.ResultsError, match="class-id order"):
        data.load_trio(wrong_order)


@pytest.mark.parametrize(
    ("name", "change", "message"),
    [
        ("strict-own", lambda d: d.update(version=2), "version"),
        ("strict-own", lambda d: d.update(trio="mnk-pal-ber"), "trio"),
        ("strict-own", lambda d: d.update(evidence="wiki"), "evidence"),
        ("strict-own", lambda d: d.update(buffs="group"), "buffs"),  # the set's name is the one the file name says
        ("strict-own", lambda d: d.update(buffs=[[20011]]), "buffs"),  # a list of buff ids is not the name of a set
        ("strict-own", lambda d: d["buff_sets"].append("x"), "buff_sets["),
        ("strict-own", lambda d: d["buff_sets"].__setitem__(0, [1, 1]), "twice"),
        ("strict-own", lambda d: d.pop("buff_sets"), "buff_sets"),
        ("strict-own", lambda d: d.pop("solver"), "solver"),
        ("strict-own", lambda d: d.update(build_options=[]), "build_options"),
        ("strict-own", lambda d: d.update(level="50"), "level"),
        ("strict-own", lambda d: d.update(rules_version="soon"), "rules_version"),
        ("strict-own", lambda d: d.pop("game_patch"), "game_patch"),
        ("strict-own", lambda d: d.update(game_patch="2026-13-40"), "game_patch"),
        ("strict-own", lambda d: d.update(data_release="2026-10-14"), "data_release"),  # it is data-YYYY-MM-DD
        ("strict-own", lambda d: d.update(data_release="data-2026-13-40"), "data_release"),
        ("strict-own", lambda d: d.update(data_release={"tag": "data-2026-10-14"}), "data_release"),  # the old object
        ("strict-own", lambda d: d.update(items_keys=["key", "name"]), "items_keys"),
        ("strict-own", lambda d: d["items"][0].__setitem__(3, "loot"), "tier_rule"),
        ("strict-own", lambda d: d["items"][0].__setitem__(4, 11), "arrival"),
        ("strict-own", lambda d: d["items"][0].__setitem__(4, None), "arrival"),  # only a summoned item has none
        ("strict-own", lambda d: d["items"][0].__setitem__(4, "+0 to +4"), "arrival"),  # a whole tier, not a text
        ("strict-own", lambda d: d["items"][0].__setitem__(2, ["HAT"]), "slots"),
        ("strict-own", lambda d: d["items"][0].__setitem__(6, "hidden"), "evidence"),
        ("strict-own", lambda d: d["items"][0].__setitem__(7, "Karana"), "deity"),
        ("strict-own", lambda d: d["items"][0].__setitem__(1, "a\x00b"), "name"),
        ("strict-own", lambda d: d["items"][0].__setitem__(1, ""), "name"),
        ("strict-own", lambda d: d["items"][0].pop(), "items[0]"),  # a row of seven
        ("strict-own", lambda d: d["items"].append(list(d["items"][0])), "twice"),
        ("strict-own", lambda d: d["kits"][0].pop(), "22"),
        ("strict-own", lambda d: d["kits"][0].__setitem__(0, 999), "range"),
        ("strict-own", lambda d: d["scenarios"][0].__setitem__(0, "HUMAN"), "race"),
        ("strict-own", lambda d: d["scenarios"][0].__setitem__(1, "healer"), "role"),
        ("strict-own", lambda d: d["scenarios"][0].__setitem__(2, 11), "tier"),
        ("strict-own", lambda d: d["scenarios"][0].__setitem__(3, "bow"), "setup"),
        ("strict-own", lambda d: d["scenarios"][0].__setitem__(4, 999), "kit"),
        ("strict-own", lambda d: d["scenarios"][0].__setitem__(5, "lots"), "value"),
        ("strict-own", lambda d: d["scenarios"][0].__setitem__(7, 999), "totals"),
        ("strict-own", lambda d: d["scenarios"][0].__setitem__(8, 999), "buffs"),
        ("strict-own", lambda d: d["scenarios"][0].__setitem__(9, -1), "haste_assumed"),
        ("strict-own", lambda d: d["scenarios"][0].pop(), "scenarios[0]"),
        ("strict-own", lambda d: d["scenarios"].append(list(d["scenarios"][0])), "twice"),
        ("strict-own", lambda d: d["scenarios"].pop(), "missing"),
        ("strict-own", lambda d: d["totals"][0].pop(), "totals[0]"),
        ("strict-own", lambda d: d["totals"][0].__setitem__(4, 1.5), "haste"),
        ("strict-own", lambda d: d["totals"][0].__setitem__(1, "many"), "hp"),
        ("strict-own", lambda d: d.update(totals_keys=list(reversed(d["totals_keys"]))), "totals_keys"),
        ("strict-own", lambda d: d.update(tiers=[0, 4]), "tiers"),  # a shard records the tiers of its run, and its rows must be those
        ("strict-own", lambda d: d.update(tiers=[0, 4, 7, 10]), "tiers"),
        ("strict-own", lambda d: d.update(tiers=[0, 4, 4, 10]), "tiers"),
        ("strict-own", lambda d: d.update(tiers=[10, 4, 0]), "tiers"),
        ("strict-own", lambda d: d.update(tiers=[0, 4, 11]), "tiers"),
        ("strict-own", lambda d: d.update(tiers="0,4,10"), "tiers"),
        ("strict-own", lambda d: d.pop("tiers"), "tiers"),
        ("defaults", lambda d: d.update(race="HUM"), "race"),
        ("defaults", lambda d: d.update(runner_up_race="HUM"), "runner_up_race"),
        ("defaults", lambda d: d.update(runner_up_race=None), "runner_up_race"),  # a lone race that can be created has no runner-up
        ("defaults", lambda d: d.update(runner_up_race=d["race"]), "runner_up_race"),
        ("defaults", lambda d: d.update(runner_up_race="ELF"), "runner_up_race"),  # a race of the grid that the shards say cannot be created is no runner-up either
        ("defaults", lambda d: d.update(close_races=["OGR", "ELF"]), "close_races"),  # nor is it a close race
        ("defaults", lambda d: d["view"].update(role="melee"), "view.role"),  # the page opens on the build the classes open on (a Paladin trio: the Tank), not on any build the grid has
        ("strict-own", lambda d: d["races"][0].update(legal="yes"), "races[0]"),  # a row of the list of races that is not {code, legal} refuses the shard: no race check is skipped for it
        ("strict-own", lambda d: d["races"][1].pop("code"), "races[1]"),
        ("strict-own", lambda d: d["races"][2].update(code=7), "races[2]"),
        ("strict-own", lambda d: d["races"].append("HUM"), "races["),
        ("strict-own", lambda d: d["races"].append({"code": "ZZZ", "legal": True}), "races["),
        ("strict-own", lambda d: d["races"].append(dict(d["races"][0])), "twice"),  # two rows with one race code (the second says the same, or the other thing)
        ("strict-own", lambda d: d["races"].append({**d["races"][0], "legal": not d["races"][0]["legal"]}), "twice"),
        ("strict-own", lambda d: d.update(races="HUM"), "races"),
        ("wiki-group", lambda d: d["races"][0].update(legal=1), "races[0]"),  # whichever shard it is in
        ("defaults", lambda d: d.update(margin="big"), "margin"),
        ("defaults", lambda d: d.update(margin=None), "margin"),
        ("defaults", lambda d: d.update(flip_notes="x"), "flip_notes"),
        ("defaults", lambda d: d["flip_notes"].append(""), "flip_notes[1]"),
        ("defaults", lambda d: d["view"].update(role="healer"), "view.role"),
        ("defaults", lambda d: d["view"].update(tier=7), "view.tier"),
        ("defaults", lambda d: d["view"].update(evidence="hidden"), "view.evidence"),
        ("defaults", lambda d: d["view"].update(buffs="raid"), "view.buffs"),
        ("defaults", lambda d: d.update(view=[]), "view"),
        ("defaults", lambda d: d.update(setup="stick"), "setup"),
        ("defaults", lambda d: d.update(F="lots"), "F"),
        ("defaults", lambda d: d.update(strict_pool_empty="no"), "strict_pool_empty"),
        ("defaults", lambda d: d.update(robustness=7), "robustness"),
        ("defaults", lambda d: d.update(data_release="data-2026-10-20"), "data_release"),  # from another run than the shards
        ("defaults", lambda d: d.update(rules_version="2026-10-20"), "rules_version"),
        ("robust", lambda d: d["roles"]["tank"]["4"].pop("HEAD"), "HEAD"),
        ("robust", lambda d: d["roles"]["tank"]["4"].update(HELM="robust"), "HELM"),
        ("robust", lambda d: d["roles"]["tank"]["4"].update(HEAD=""), "label"),
        ("robust", lambda d: d["roles"].update(healer={}), "healer"),
        ("robust", lambda d: d["roles"]["tank"].update({"7": d["roles"]["tank"]["4"]}), "tier"),
        ("robust", lambda d: d.update(race="HUM"), "race"),
        ("robust", lambda d: d.update(roles=[]), "roles"),
        ("robust", lambda d: d.update(game_patch="2026-09-23"), "game_patch"),
    ],
)
def test_a_bad_value_is_refused_with_the_file_and_field_named(broken, name, change, message):
    root = broken(name, change)
    with pytest.raises(data.ResultsError) as caught:
        data.load_trio(root)
    text = str(caught.value)
    assert f"{name}.json" in text
    assert message in text
    assert "\n" not in text  # one line, as every refusal in this repository


# one entry of tank.json is refused for each of these; the file's index entry is brought up to date first. A view is [tier, race, setup, places].
RUNNERUP_CHANGES = [
    (lambda d: d.update(buffs="group"), "buffs"),
    (lambda d: d.update(evidence="wiki"), "evidence"),
    (lambda d: d.update(role="melee"), "role"),
    (lambda d: d.update(items_keys=["key"]), "items_keys"),
    (lambda d: d["views"][0][3].__setitem__(0, [[0, -1.0]] * 4), "three runner-ups that need no deity"),
    (lambda d: d["views"][0][3].pop(), "22"),
    (lambda d: d["views"][0][3].__setitem__(0, [[999, -1.0]]), "item"),
    (lambda d: d["views"][0][3].__setitem__(0, [[0, 5.0]]), "delta"),  # an item anyone can wear cannot beat the pick
    (lambda d: d["views"][0][3].__setitem__(0, [[0]]), "[item, delta]"),
    (lambda d: d["views"][0][3].__setitem__(0, [{"item": 0, "delta": -1.0}]), "[item, delta]"),
    (lambda d: d["views"].append(list(d["views"][0])), "twice"),
    (lambda d: d["views"][0].__setitem__(1, "HUM"), "race"),
    (lambda d: d["views"][0].__setitem__(2, "stick"), "setup"),
    (lambda d: d["views"][0].pop(), "[tier, race, setup, places]"),
    (lambda d: d["items"].append(list(d["items"][0])), "twice"),
    (lambda d: d.update(data_release="data-2026-10-20"), "data_release"),
    (lambda d: d["views"][0].__setitem__(0, 1.5), "tier"),
    (lambda d: d["views"][0].__setitem__(0, "0"), "tier"),
]


@pytest.mark.parametrize(("change", "message"), RUNNERUP_CHANGES)
def test_a_bad_runner_up_file_is_refused_with_the_file_and_field_named(broken_runnerup, change, message):
    root = broken_runnerup("tank.json", change)
    with pytest.raises(data.ResultsError) as caught:
        data.load_trio(root)
    text = str(caught.value)
    assert "runnerups/tank.json" in text and message in text and "\n" not in text


# The scope of a run is the tiers its shards record. The file of a role holds every tier of it: not one more, not one fewer, none twice.
TIER_CHANGES = [
    (lambda d: d.update(tiers=[0, 4, 7, 10]), r"tiers\[2\]: \+7 is not a tier of the run"),  # a tier outside the scope ...
    (lambda d: d.update(tiers=[0, 4, 10, 11]), r"tiers\[3\]: must be a whole number from 0 to 10"),  # ... or none at all
    (lambda d: d.update(tiers=[0, 10]), r"tiers: has no \+4, a tier of the run"),  # a tier of the scope missing from the file
    (lambda d: d.update(tiers=[]), r"tiers: has no \+0, a tier of the run"),
    (lambda d: d.update(tiers=[0, 4, 4, 10]), r"tiers: lists \+4 twice"),  # a tier twice
    (lambda d: d.update(tiers=[10, 0, 4]), r"tiers: must be in ascending order"),
    (lambda d: d.update(tiers="0,4,10"), r"tiers: must be a list"),
    (lambda d: d.pop("tiers"), r"tiers: is missing"),
    (lambda d: d.update(tiers=[0, 4.5, 10]), r"tiers\[1\]"),
    (lambda d: d["views"].__setitem__(0, [7, *d["views"][0][1:]]), r"views\[0\]\.tier: \+7 is not one of the tiers of the file"),  # a view of a tier outside
    (lambda d: d.update(views=[v for v in d["views"] if v[0] != 4]), r"views: has no view of OGR at \+4"),  # a tier listed, with no views
    (lambda d: d.update(views=[v for v in d["views"] if v[:2] != [4, "TRL"]]), r"views: has no view of TRL at \+4"),  # a race missing at one tier
    (lambda d: d["views"].append(list(d["views"][0])), r"views\[9\]: lists OGR at \+0 twice"),  # a duplicate
    (lambda d: d["views"].__setitem__(1, [0, "OGR", *d["views"][1][2:]]), r"lists OGR at \+0 twice"),
]


@pytest.mark.parametrize(("change", "message"), TIER_CHANGES)
def test_a_runner_up_file_with_a_tier_outside_the_scope_a_missing_tier_or_a_duplicate_one_is_refused(broken_runnerup, change, message):
    root = broken_runnerup("tank.json", change)
    with pytest.raises(data.ResultsError, match=message) as caught:
        data.load_trio(root)
    text = str(caught.value)
    assert text.startswith("pal-mnk-ber/runnerups/tank.json: ") and "\n" not in text


def test_the_scope_is_whatever_tiers_the_shards_record(broken, broken_runnerup):
    """A run of +0 and +10 only (its shards say so) is read with the file of each role holding those two tiers: the scope is the shards' tiers."""
    for name in ("strict-own", "strict-group", "wiki-own", "wiki-group"):
        broken(name, lambda d: d.update(tiers=[0, 10], partial=False, scenarios=[row for row in d["scenarios"] if row[2] != 4]))  # (a run of a scope has all of it)
    broken("defaults", lambda d: d["view"].update(tier=10))
    broken("robust", lambda d: (d.update(tiers=[10]), [by_tier.pop("4") for by_tier in d["roles"].values()]))
    for role in ("tank", "melee"):
        broken_runnerup(f"{role}.json", lambda d: d.update(tiers=[0, 10], views=[v for v in d["views"] if v[0] != 4]))
    edit_index(broken.root, lambda d: [entry.update(tiers=[0, 10]) for entry in d["files"]])
    results = data.load_trio(broken.root)
    assert results.shards[("wiki", "own")].tiers == (0, 10) and not results.meta.partial
    assert [f.tiers for f in results.runnerups.files] == [(0, 10)] * 2 and results.runnerups.view("OGR", "tank", 4) is None
    assert results.runnerups.view("OGR", "tank", 10) is not None
    broken_runnerup("tank.json", lambda d: d.update(tiers=[0, 4, 10]))  # the file of a role with a tier that this run does not have
    with pytest.raises(data.ResultsError, match=r"tank\.json: tiers\[1\]: \+4 is not a tier of the run"):
        data.load_trio(broken.root)


def test_a_shard_that_lost_a_whole_tier_is_refused_by_the_tiers_it_records(broken):
    root = broken("wiki-own", lambda d: d.update(scenarios=[row for row in d["scenarios"] if row[2] != 4]))  # the rows of +4 are gone, the tiers still say +4
    with pytest.raises(data.ResultsError, match=r"wiki-own\.json: tiers: .*\+4") as caught:
        data.load_trio(root)
    assert "\n" not in str(caught.value)


def locked_item(document):
    return next(i for i, row in enumerate(document["items"]) if row[7])


def test_more_than_one_runner_up_that_needs_a_deity_in_a_slot_is_refused(broken_runnerup):
    def change(document):
        i = locked_item(document)
        document["views"][0][3][0] = [[i, -1.0], [i, -2.0]]

    root = broken_runnerup("tank.json", change)
    with pytest.raises(data.ResultsError, match="more than one runner-up that needs a deity"):
        data.load_trio(root)


def test_one_that_needs_a_deity_beside_three_that_do_not_is_fine(broken_runnerup):
    def change(document):
        i = locked_item(document)
        free = [n for n, row in enumerate(document["items"]) if not row[7]][:3]
        view = next(v for v in document["views"] if v[:2] == [4, "OGR"])
        view[3][0] = [[i, 4.5]] + [[n, -1.0 * (k + 1)] for k, n in enumerate(free)]

    root = broken_runnerup("tank.json", change)
    swaps = data.load_trio(root).runnerups.view("OGR", "tank", 4).slots[0]
    assert len(swaps) == 4 and swaps[0].item.deity is not None and swaps[0].delta == 4.5  # better than the pick, and allowed


def test_a_swap_of_an_item_that_needs_no_deity_may_tie_the_pick_but_not_beat_it(broken_runnerup):
    def tie(document):
        free = next(n for n, row in enumerate(document["items"]) if not row[7])
        next(v for v in document["views"] if v[:2] == [4, "OGR"])[3][0] = [[free, 0.0]]

    root = broken_runnerup("tank.json", tie)
    assert data.load_trio(root).runnerups.view("OGR", "tank", 4).slots[0][0].delta == 0.0


def test_the_same_item_must_read_the_same_in_every_runner_up_file(broken_runnerup):
    root = broken_runnerup("tank.json", lambda d: d["items"][0].__setitem__(1, "Another Name"))
    with pytest.raises(data.ResultsError, match="not the same as in another"):
        data.load_trio(root)


def test_the_index_must_match_the_files(broken_runnerup):
    root = broken_runnerup.root
    path = root / "runnerups" / "tank.json"
    original = path.read_bytes()
    path.write_bytes(original + b" ")  # one byte longer than the index says
    with pytest.raises(data.ResultsError, match=r"runnerups/tank\.json: is \d+ bytes, but the index says"):
        data.load_trio(root)
    changed = bytearray(original)
    changed[changed.index(b"T")] ^= 0x01  # the same length, one other byte (a T becomes a U)
    path.write_bytes(bytes(changed))
    with pytest.raises(data.ResultsError, match="sha256 differs from the index"):
        data.load_trio(root)
    path.write_bytes(original)
    assert data.load_trio(root).runnerups.pairs()  # and the untouched folder reads


def test_a_file_the_index_does_not_list_is_refused(broken_runnerup):
    root = broken_runnerup.root
    version = json.loads((root / "runnerups" / "index.json").read_text(encoding="utf-8"))["rules_version"]
    (root / "runnerups" / "extra.json").write_text(json.dumps({"rules_version": version}), encoding="utf-8")  # (a file of this run: one that records no rules version is refused earlier, as old)
    with pytest.raises(data.ResultsError, match=r"runnerups/index\.json: files: extra\.json is in the folder but not in the index"):
        data.load_trio(root)


def test_a_listed_file_that_is_missing_is_refused(broken_runnerup):
    root = broken_runnerup.root
    (root / "runnerups" / "melee.json").unlink()
    with pytest.raises(data.ResultsError, match=r"runnerups/melee\.json: file is missing"):
        data.load_trio(root)


def _bad_name(name):
    return lambda d: entry_of(d, "tank.json").update(file=name)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_bad_name("bad.json"), "is not a runner-up file name"),
        (_bad_name("caster.json"), "is not a runner-up file name"),  # not a role of the run
        (_bad_name("Tank.json"), "is not a runner-up file name"),
        (_bad_name("tank.JSON"), "is not a runner-up file name"),
        (_bad_name("tank-4.json"), "a file of the earlier layout, one for each role and tier"),  # said as it is: run the precompute again
        (_bad_name("tank-04.json"), "is not a runner-up file name"),
        (lambda d: entry_of(d, "tank.json").update(role="melee"), "role"),  # the entry must agree with the file's name
        (lambda d: entry_of(d, "tank.json").pop("role"), "role"),
        (lambda d: entry_of(d, "tank.json").update(tiers=[0, 4]), r"files[0].tiers: has no +10, a tier of the run"),  # the entry lists the scope too
        (lambda d: entry_of(d, "tank.json").update(tiers=[0, 4, 7, 10]), r"files[0].tiers[2]: +7 is not a tier of the run"),
        (lambda d: entry_of(d, "tank.json").update(tiers=[0, 4, 4, 10]), "lists +4 twice"),
        (lambda d: entry_of(d, "tank.json").update(tiers=[0, 4, 10, 11]), "files[0].tiers[3]"),
        (lambda d: entry_of(d, "tank.json").pop("tiers"), "tiers"),
        (lambda d: entry_of(d, "tank.json").update(bytes="big"), "bytes"),
        (lambda d: entry_of(d, "tank.json").update(sha256="ABC"), "sha256"),
        (lambda d: entry_of(d, "tank.json").pop("bytes"), "bytes"),
        (lambda d: d["files"].append(dict(entry_of(d, "tank.json"))), "twice"),
        (lambda d: d["files"].pop(), "files: has no file for the melee role"),  # every role of the run has one
        (lambda d: d.update(files=[]), "no runner-up files"),
        (lambda d: d.update(files={}), "files"),
        (lambda d: d["files"].append("tank.json"), "files[2]"),
        (lambda d: d.update(version=2), "version"),
        (lambda d: d.update(trio="mnk-pal-ber"), "trio"),
        (lambda d: d.update(evidence="wiki"), "evidence"),
        (lambda d: d.update(buffs="group"), "buffs"),
        (lambda d: d.update(data_release="data-2026-10-20"), "data_release"),
    ],
)
def test_a_bad_index_is_refused_with_the_field_named(broken_runnerup, change, message):
    root = broken_runnerup.root
    edit_index(root, change)
    with pytest.raises(data.ResultsError) as caught:
        data.load_trio(root)
    text = str(caught.value)
    assert "runnerups/index.json" in text and message in text and "\n" not in text


def test_a_missing_index_is_refused(broken_runnerup):
    (broken_runnerup.root / "runnerups" / "index.json").unlink()
    with pytest.raises(data.ResultsError, match=r"runnerups/index\.json: file is missing"):
        data.load_trio(broken_runnerup.root)


def test_an_item_in_a_slot_it_does_not_fit_is_refused(broken):
    def change(document):
        chest = next(i for i, row in enumerate(document["items"]) if row[2] == ["CHEST"])
        document["kits"][0][0] = chest  # a chest piece on the head

    root = broken("strict-own", change)
    with pytest.raises(data.ResultsError, match=r"HEAD"):
        data.load_trio(root)


def test_the_any_slots_take_any_item(results):
    scenario = results.shards[("strict", "own")].scenario("OGR", "tank", 4, "dw")
    assert scenario.kit[18].slots == ("FINGER",)  # a ring in an Any slot is fine


def test_the_grid_must_be_complete(broken):
    root = broken("wiki-group", lambda d: d["scenarios"].__delitem__(slice(0, 8)))  # some of one race's rows
    with pytest.raises(data.ResultsError, match="grid") as caught:
        data.load_trio(root)
    assert "wiki-group.json" in str(caught.value) and "missing" in str(caught.value)


def test_every_shard_must_have_the_same_grid(broken):
    root = broken("wiki-group", lambda d: d["scenarios"].__delitem__(slice(0, 15)))  # one whole race (three tiers of five pairs of a build and a setup)
    with pytest.raises(data.ResultsError, match="grid") as caught:
        data.load_trio(root)
    assert "wiki-group.json" in str(caught.value) and "strict-own.json" in str(caught.value)


# The tiers of a trio are one list. The four shards must hold it alike (the reader reads each against the first), and a message says which tiers differ,
# so that a folder that is consistent in every file but one is not left for something else to find.
FIRST_SHARD = SHARDS[0]


@pytest.mark.parametrize("odd", SHARDS)
@pytest.mark.parametrize(("gone", "listed"), [(4, "+0, +10"), (0, "+4, +10"), (10, "+0, +4")])
def test_shards_that_list_other_tiers_than_the_rest_are_refused_whichever_is_the_odd_one_and_the_message_says_which_tiers(broken, odd, gone, listed):
    """The odd shard is consistent in itself (its rows are of the tiers it records) and is of another scope than the rest. The shards are read against the
    first, so when the first is the odd one the second is the one named as differing from it."""
    root = broken(odd, lambda d: d.update(tiers=[t for t in d["tiers"] if t != gone], scenarios=[row for row in d["scenarios"] if row[2] != gone]))
    reader, reference = (SHARDS[1], FIRST_SHARD) if odd == FIRST_SHARD else (odd, FIRST_SHARD)
    mine, there = ("+0, +4, +10", listed) if odd == FIRST_SHARD else (listed, "+0, +4, +10")
    with pytest.raises(data.ResultsError) as caught:
        data.load_trio(root)
    assert str(caught.value) == (
        f"pal-mnk-ber/{reader}.json: the grid (races, roles, tiers) differs from {reference}.json: its tiers are {mine}, and {reference}.json's are {there}"
    )


GRID_DIFFERENCES = [
    (lambda d: d.update(scenarios=[row for row in d["scenarios"] if row[0] != "ELF"]), "its races are OGR TRL, and strict-own.json's are OGR TRL ELF"),
    (lambda d: d.update(scenarios=[row for row in d["scenarios"] if row[1] != "melee"]), "its roles are tank, and strict-own.json's are tank, melee"),
    (  # more than one part differs: each is said, the tiers first
        lambda d: d.update(scenarios=[row for row in d["scenarios"] if row[0] != "ELF" and row[2] != 10], tiers=[0, 4]),
        "its tiers are +0, +4, and strict-own.json's are +0, +4, +10; its races are OGR TRL, and strict-own.json's are OGR TRL ELF",
    ),
]


@pytest.mark.parametrize(("change", "difference"), GRID_DIFFERENCES)
def test_shards_that_differ_in_their_races_or_their_roles_are_told_so_by_name(broken, change, difference):
    root = broken("wiki-group", change)
    with pytest.raises(data.ResultsError) as caught:
        data.load_trio(root)
    assert str(caught.value) == f"pal-mnk-ber/wiki-group.json: the grid (races, roles, tiers) differs from strict-own.json: {difference}"


def test_the_tiers_of_a_trio_are_the_one_list_that_its_files_all_hold(results):
    assert results.tiers == (0, 4, 10)
    assert all(shard.tiers == results.tiers for shard in results.shards.values())
    assert all(file.tiers == results.tiers for file in results.runnerups.files)


def test_the_tiers_of_a_trio_put_together_by_hand_from_files_of_other_tiers_are_an_error_and_never_the_first_shards(results):
    lost = results.shards[("wiki", "own")]
    odd = dataclasses.replace(lost, scenarios=tuple(s for s in lost.scenarios if s.tier != 4))
    mixed = dataclasses.replace(results, shards={**results.shards, ("wiki", "own"): odd})  # (strict-own, the first, is the right one)
    assert next(iter(mixed.shards.values())).tiers == (0, 4, 10)
    with pytest.raises(data.ResultsError, match=r"^pal-mnk-ber/wiki-own\.json: the tiers are \+0, \+10, but strict-own\.json has \+0, \+4, \+10: the files of a trio must all list the same tiers$"):
        mixed.tiers
    short = tuple(dataclasses.replace(file, tiers=(0, 10)) if file.role == "tank" else file for file in results.runnerups.files)
    mixed = dataclasses.replace(results, runnerups=dataclasses.replace(results.runnerups, files=short))
    with pytest.raises(data.ResultsError, match=r"^pal-mnk-ber/runnerups/tank\.json: the tiers are \+0, \+10, but strict-own\.json has \+0, \+4, \+10:"):
        mixed.tiers
    with pytest.raises(data.ResultsError, match="has no shards"):
        dataclasses.replace(results, shards={}).tiers


# robust.json records the tiers its seals are made for, which are some of the tiers of the run (+4 and +10): the file must not name a tier the run does not
# have, name one twice or out of order, or name one that no role has labels for. The writer lists the tiers it has labels for, so none of these is its.
ROBUST_TIER_CHANGES = [
    (lambda d: d.update(tiers=[4, 7, 10]), r"robust\.json: tiers\[1\]: \+7 is not a tier of the run \(\+0, \+4, \+10\)$"),
    (lambda d: d.update(tiers=[4, 10, 11]), r"robust\.json: tiers\[2\]: must be a whole number from 0 to 10$"),
    (lambda d: d.update(tiers=[4, 4, 10]), r"robust\.json: tiers: lists \+4 twice$"),
    (lambda d: d.update(tiers=[10, 4]), r"robust\.json: tiers: must be in ascending order$"),
    (lambda d: d.update(tiers=[0, 4, 10]), r"robust\.json: tiers: lists \+0, but no role has labels at \+0$"),  # a tier of the run, but not one of the seals
    (lambda d: d.update(tiers=[4]), r"robust\.json: roles\.tank\.10: is not a tier of the grid that this file lists in tiers"),  # labels at a tier it does not list
    (lambda d: d.update(tiers=[]), r"robust\.json: roles\.tank\.4: is not a tier of the grid that this file lists in tiers"),
    (lambda d: d.update(tiers="4,10"), r"robust\.json: tiers: must be a list$"),
    (lambda d: d.update(tiers=[4, 10.5]), r"robust\.json: tiers\[1\]"),
    (lambda d: d.pop("tiers"), r"robust\.json: tiers: is missing$"),
]


@pytest.mark.parametrize(("change", "message"), ROBUST_TIER_CHANGES)
def test_robust_json_must_list_tiers_of_the_run_that_it_has_labels_for_and_no_others(broken, change, message):
    root = broken("robust", change)
    with pytest.raises(data.ResultsError, match=message) as caught:
        data.load_trio(root)
    assert str(caught.value).startswith("pal-mnk-ber/robust.json: ") and "\n" not in str(caught.value)


def test_robust_json_lists_some_of_the_tiers_of_the_run_and_that_is_enough(results):
    """The fixture's seals are made for +4 and +10 of a run of +0, +4 and +10: a file that lists a part of the scope is what the writer makes."""
    assert {view.tier for view in results.robust.views} == {4, 10} and results.tiers == (0, 4, 10)


# The format number. Every file of the results carries ``version`` (the writer's shards.FORMAT) and the reader accepts that number alone, for the shards, the
# runner-up files of the new layout (one for each role, every tier in it) and their index alike: a file of the new shape with another stamp is not read.
STAMPS = [0, 2, 99, -1, True, False, "1", None, [1], {"v": 1}]


@pytest.mark.parametrize("stamp", STAMPS)
def test_a_runner_up_file_of_the_new_shape_stamped_with_another_format_number_is_refused(broken_runnerup, stamp):
    root = broken_runnerup("tank.json", lambda d: d.update(version=stamp))
    with pytest.raises(data.ResultsError, match=r"^pal-mnk-ber/runnerups/tank\.json: version: must be 1$"):
        data.load_trio(root)


@pytest.mark.parametrize("stamp", STAMPS)
def test_the_runner_up_index_stamped_with_another_format_number_is_refused(broken_runnerup, stamp):
    edit_index(broken_runnerup.root, lambda d: d.update(version=stamp))
    with pytest.raises(data.ResultsError, match=r"^pal-mnk-ber/runnerups/index\.json: version: must be 1$"):
        data.load_trio(broken_runnerup.root)


def test_a_runner_up_file_or_the_index_without_a_format_number_is_refused(broken_runnerup):
    root = broken_runnerup("tank.json", lambda d: d.pop("version"))
    with pytest.raises(data.ResultsError, match=r"^pal-mnk-ber/runnerups/tank\.json: version: is missing$"):
        data.load_trio(root)
    broken_runnerup("tank.json", lambda d: d.update(version=data.FORMAT_VERSION))
    edit_index(root, lambda d: d.pop("version"))
    with pytest.raises(data.ResultsError, match=r"^pal-mnk-ber/runnerups/index\.json: version: is missing$"):
        data.load_trio(root)


def test_the_files_of_the_fixture_carry_the_number_the_reader_and_the_writer_ask_for(results):
    assert data.FORMAT_VERSION == precompute_shards.FORMAT == 1
    stamped = [FIXTURE / "runnerups" / "index.json", *(FIXTURE / "runnerups" / file.name for file in results.runnerups.files), FIXTURE / "robust.json"]
    assert [json.loads(path.read_text(encoding="utf-8"))["version"] for path in stamped] == [precompute_shards.FORMAT] * len(stamped)


def test_shards_from_different_releases_are_refused(broken):
    root = broken("wiki-own", lambda d: d.update(data_release="data-2026-10-20"))
    with pytest.raises(data.ResultsError, match="data_release"):
        data.load_trio(root)


def test_a_game_patch_that_differs_between_shards_is_refused(broken):
    root = broken("wiki-own", lambda d: d.update(game_patch="2026-09-23"))
    with pytest.raises(data.ResultsError, match="game_patch") as caught:
        data.load_trio(root)
    assert "wiki-own.json" in str(caught.value) and "strict-own.json" in str(caught.value)


def test_json_that_other_readers_would_misread_is_refused(broken):
    path = broken.root / "defaults.json"
    path.write_text('{"version": 1, "version": 1}', encoding="utf-8")
    with pytest.raises(data.ResultsError, match=r"defaults\.json"):
        data.load_trio(broken.root)
    path.write_text('{"version": 1, "margin": NaN}', encoding="utf-8")
    with pytest.raises(data.ResultsError, match=r"defaults\.json"):
        data.load_trio(broken.root)


def test_values_are_finite(broken):
    root = broken("strict-own", lambda d: d["scenarios"][0].__setitem__(5, float("inf")))
    path = root / "strict-own.json"
    path.write_text(path.read_text(encoding="utf-8").replace("Infinity", "1e999"), encoding="utf-8")  # a valid number that overflows
    with pytest.raises(data.ResultsError, match="value"):
        data.load_trio(root)


def test_list_trios_finds_directories_with_shards(tmp_path):
    (tmp_path / "pal-mnk-ber").mkdir()
    (tmp_path / "pal-mnk-ber" / "strict-own.json").write_text("{}", encoding="utf-8")
    (tmp_path / "empty").mkdir()
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    assert data.list_trios(tmp_path) == ["pal-mnk-ber"]
    assert data.list_trios(tmp_path / "missing") == []


def test_every_rounded_number_is_finite(results):
    for shard in results.shards.values():
        for scenario in shard.scenarios:
            assert math.isfinite(scenario.value) and math.isfinite(scenario.gain)
