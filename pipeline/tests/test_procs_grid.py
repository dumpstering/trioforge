"""The procs in a precompute run: the table made from the catalog, the rows of the chunks, the shards and the kit-value check (stage 1b of the builds).

The world is the invented one of ``test_precompute`` with two proc weapons, whose spells are invented rows added to a copy of the client's spell file. Every name is invented.
"""

import copy
import json
import shutil
from fractions import Fraction

import pytest
from test_precompute import CATALOG, SLUG, TRIO, small_world, write_catalog, write_seen

from trioforge import precompute as pc
from trioforge.model import formulas as fm
from trioforge.model import procs as procs_module
from trioforge.model.items import SLOT_INSTANCES
from trioforge.precompute import grid
from trioforge.solver.model import eval_buff_totals

EMBER = {"id": 19991, "name": "Ember Brand", "cast_ms": 0, "mana": 0, "dur": [0, 0], "ben": 0, "res": 1, "tgt": 5, "sk": 0, "lv": {}, "fx": [[1, 0, -300, 0, 100, 0]]}
GALE = {"id": 19992, "name": "Gale Brand", "cast_ms": 0, "mana": 0, "dur": [0, 0], "ben": 0, "res": 1, "tgt": 5, "sk": 0, "lv": {}, "fx": [[1, 0, -500, 0, 100, 0]]}
PPM = Fraction(57, 34)
LANDING = Fraction(17, 20)


def with_effect(item, name):
    item = copy.deepcopy(item)
    item["effects"] = [{"kind": "proc", "name": name, "raw": f"Effect: {name} (Combat)"}]
    return item


def procs_catalog():
    """The invented catalog with a proc on the one-handed sword and on the two-hander."""
    items = [with_effect(i, "Ember Brand") if i["key"] == "w9011" else with_effect(i, "Gale Brand") if i["key"] == "w9013" else i for i in CATALOG]
    return items


def world(root):
    """A ``tables_root`` whose spell file has the two invented proc spells, and the catalog written beside it."""
    small_world(root / "world")
    path = root / "world" / "derived" / "client" / "effect-spells.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["spells"] = [*document["spells"], EMBER, GALE]
    document["catalog_names"] = ["Ember Brand", "Gale Brand"]  # (the record of a derive for this world's catalog: the effects of its items)
    path.write_text(json.dumps(document), encoding="utf-8")
    return root / "world", write_catalog(root / "catalog.json", procs_catalog())


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    root = tmp_path_factory.mktemp("procs")
    tables, catalog = world(root)
    config, meta = grid.load_inputs(grid.parse_trio(SLUG), catalog_path=catalog, tables_root=tables)
    return root, tables, catalog, config, meta


def test_the_table_of_the_trio_is_made_from_the_public_catalog_and_the_spell_file(made):
    _, _, _, config, _ = made
    table = config.procs
    assert {e.name: e.value for e in table.effects} == {"Ember Brand": PPM * 300 * LANDING, "Gale Brand": PPM * 500 * LANDING}
    assert {(d.key, d.primary_only) for d in table.donors} == {("w9011", False), ("w9013", True)}
    assert table.socket_tier == 4 and table.trio == TRIO


def test_no_proc_means_no_table_and_the_seen_flags_do_not_change_what_a_proc_counts(made, tmp_path):
    root, tables, catalog, config, _ = made
    plain = write_catalog(tmp_path / "plain.json", CATALOG)
    assert grid.load_inputs(grid.parse_trio(SLUG), catalog_path=plain, tables_root=tables)[0].procs is None
    seen = write_seen(tmp_path / "seen.json", {"w9011", "w9012", "w9013"})
    flagged, _ = grid.load_inputs(grid.parse_trio(SLUG), catalog_path=catalog, tables_root=tables, seen_path=seen)
    assert flagged.procs == config.procs  # a sighting is a flag on an item, never a fact about an effect


def test_a_run_refuses_a_catalog_that_names_an_effect_the_spell_file_was_not_derived_for(made, tmp_path):
    """E3: a catalog refreshed without deriving the spell file again would leave its new effect names unresolved, worth 0 as procs, with no warning: the run stops and says which."""
    root, tables, catalog, config, _ = made
    newer = [with_effect(i, "Brand Newer Than The File") if i["key"] == "w9012" else i for i in procs_catalog()]
    path = write_catalog(tmp_path / "newer.json", newer)
    with pytest.raises(ValueError, match=r"Brand Newer Than The File.*trioforge\.effects\.derive"):
        grid.load_inputs(grid.parse_trio(SLUG), catalog_path=path, tables_root=tables)
    with pytest.raises(ValueError, match=r"effect names"):
        grid.load_inputs(grid.parse_trio(SLUG), catalog_path=path, tables_root=tables, procs=True)
    assert grid.load_inputs(grid.parse_trio(SLUG), catalog_path=path, tables_root=tables, procs=False)[0].procs is None  # (a run with no procs reads no spell file)


def test_the_fingerprint_follows_the_spell_file_the_procs_are_made_from(made, tmp_path):
    root, tables, catalog, config, _ = made
    other = tmp_path / "world"
    shutil.copytree(tables, other)
    path = other / "derived" / "client" / "effect-spells.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["spells"][-1]["fx"] = [[1, 0, -501, 0, 100, 0]]
    path.write_text(json.dumps(document), encoding="utf-8")
    changed, _ = grid.load_inputs(grid.parse_trio(SLUG), catalog_path=catalog, tables_root=other)
    assert changed.fingerprint != config.fingerprint


def solved(made, role, setup, tier, race="OGR"):
    _, _, _, config, _ = made
    ctx = grid.Context(config)
    doc = grid.solve_chunk(ctx, grid.ChunkKey("wiki", "own", role, setup, tier), [race], audit=0)
    return ctx, doc["rows"][0], doc


def kit_value(ctx, row, role, setup, tier):
    profile = ctx.profile(row["race"], role, "own", "wiki")
    vecs = ctx.vecs(tier)
    kit = [vecs[k] if k is not None else None for k in row["kit"]]
    totals = eval_buff_totals(ctx.buffsets["own"].totals(tuple(row["buffs"])))
    return fm.evaluate(profile.eval_profile, kit, totals, setup=setup, haste_assumed=row["haste"], procs=ctx.options.procs)


def test_a_row_says_which_proc_each_hand_counts_where_it_comes_from_and_the_kit_value_check_reproduces_it(made):
    ctx, row, _ = solved(made, "melee", "2h", 4)
    assert row["procs"] == [["P", "Gale Brand", "w9013", "n", 712.5]]  # the two-hander's own proc is the best there is: native, worth 57/34 x 500 x 17/20
    breakdown = kit_value(ctx, row, "melee", "2h", 4)
    assert float(breakdown.F) == pytest.approx(row["F"], rel=1e-9)
    assert breakdown.totals["procs"]["part"] > 0
    counted = breakdown.totals["procs"]
    assert [procs_module.record(counted[h], h) for h in ("PRIMARY", "SECONDARY") if counted[h]] == row["procs"]  # the record is the kit-value check's own answer: one function names the donor


def test_the_why_of_a_kit_takes_the_proc_with_the_damage_of_the_weapon(made):
    from trioforge.precompute import kitwhy

    ctx, row, _ = solved(made, "melee", "2h", 4)
    profile = ctx.profile(row["race"], "melee", "own", "wiki").eval_profile
    vecs = ctx.vecs(4)
    kit = [vecs[k] if k is not None else None for k in row["kit"]]
    totals = eval_buff_totals(ctx.buffsets["own"].totals(tuple(row["buffs"])))
    primary = SLOT_INSTANCES.index("PRIMARY")

    def damage(procs):
        places = kitwhy.why_places(profile, kit, totals, "2h", procs)
        return next(loss for term, loss, _ in places[primary]["loss"] if term == "DAMAGE")

    with_procs, without = damage(ctx.options.procs), damage(None)
    assert with_procs > without > 0  # taking the weapon's damage away takes its proc too


def test_in_dual_wield_at_the_socket_tier_the_main_hand_hosts_the_best_proc_and_the_off_hand_its_own(made):
    ctx, row, _ = solved(made, "melee", "dw", 4)
    # the two-hander's proc fits the primary hand only, so the off hand takes the sword's own
    assert [entry[:2] for entry in row["procs"]] == [["P", "Gale Brand"], ["S", "Ember Brand"]] and row["procs"][0][2:] == ["w9013", "h", 712.5] and row["procs"][1][4] == 427.5
    assert float(kit_value(ctx, row, "melee", "dw", 4).F) == pytest.approx(row["F"], rel=1e-9)


def test_below_the_socket_tier_only_the_native_counts(made):
    ctx, row, _ = solved(made, "melee", "dw", 0)
    assert all(entry[3] == "n" for entry in row["procs"])
    assert float(kit_value(ctx, row, "melee", "dw", 0).F) == pytest.approx(row["F"], rel=1e-9)


def test_a_build_with_no_weapon_weight_has_no_procs_in_its_rows(made):
    _, tables, catalog, _, _ = made
    config, _ = grid.load_inputs(grid.parse_trio("clr-shd-shm"), catalog_path=catalog, tables_root=tables)
    assert config.procs is not None  # the trio has procs to count, and the Shield caster scores no weapon: its weapons are chosen for stats
    ctx = grid.Context(config)
    doc = grid.solve_chunk(ctx, grid.ChunkKey("wiki", "own", "shield", "stick", 4), ["OGR"], audit=0)
    assert "procs" not in doc["rows"][0]


def test_the_shard_lists_the_procs_once_each_and_the_scenarios_point_at_them(made, tmp_path):
    root, tables, catalog, config, _ = made
    out = tmp_path / "out"
    pc.run(SLUG, out, catalog=catalog, tables_root=tables, processes=1, races=("OGR",), roles=("melee",), tiers=(0, 4), robustness=False)
    shard = json.loads((out / SLUG / "wiki-own.json").read_text(encoding="utf-8"))
    table = shard["procs"]
    assert set(table) == {"rows", "at"} and len(table["at"]) == len(shard["scenarios"])
    assert all(i == -1 or 0 <= i < len(table["rows"]) for i in table["at"]) and len({json.dumps(r) for r in table["rows"]}) == len(table["rows"])
    for row in table["rows"]:
        assert all(len(entry) == 5 and entry[0] in "PS" and entry[3] in "nh" and entry[4] > 0 for entry in row)
    # the reader of the site takes the shard as it is
    from trioforge.site import data

    read, _ = data._shard(out / SLUG, "wiki-own", SLUG)  # the reader takes the shard with the key in it: it ignores a key it does not know
    assert len(read.scenarios) == len(shard["scenarios"])
    assert len(shard["scenarios"][0]) == 10  # the rows themselves keep their shape
    assert list(shard).index("procs") == list(shard).index("scenarios") + 1


def test_a_whole_tiny_run_with_procs_writes_every_file_the_seals_and_the_runner_ups_included(made, tmp_path):
    root, tables, catalog, config, _ = made
    out = tmp_path / "out"
    summary = pc.run(SLUG, out, catalog=catalog, tables_root=tables, processes=1, races=("OGR", "TRL"), roles=("tank",), tiers=(0, 4, 10))
    assert not summary.violations
    folder = out / SLUG
    for name in ("defaults.json", "robust.json", "wiki-own.json", "strict-own.json", "runnerups/tank.json"):
        assert (folder / name).is_file(), name
    from trioforge.site import data

    assert data.load_trio(folder).meta.partial is True  # (the run was narrowed to two races and one build) and the reader takes all of it
    shard = json.loads((folder / "wiki-own.json").read_text(encoding="utf-8"))
    assert shard["procs"]["rows"]


def test_a_run_whose_spell_file_is_missing_stops_and_names_the_file_unless_it_says_it_wants_no_procs(made, tmp_path):
    root, tables, catalog, config, _ = made
    other = tmp_path / "bare"
    shutil.copytree(tables, other)
    (other / "derived" / "client" / "effect-spells.json").unlink()
    with pytest.raises(FileNotFoundError, match=r"effect-spells\.json"):
        grid.load_inputs(grid.parse_trio(SLUG), catalog_path=catalog, tables_root=other)
    with pytest.raises(pc.PrecomputeError, match=r"effect-spells\.json"):
        pc.run(SLUG, tmp_path / "out", catalog=catalog, tables_root=other, processes=1, races=("OGR",), roles=("tank",), tiers=(4,), robustness=False)
    bare, _ = grid.load_inputs(grid.parse_trio(SLUG), catalog_path=catalog, tables_root=other, procs=False)  # (a test that wants no procs says so)
    assert bare.procs is None and bare.fingerprint != config.fingerprint


def test_a_release_run_of_a_trio_whose_spell_file_is_missing_fails_with_the_file_named(made, tmp_path):
    from trioforge.precompute import release

    _, tables, catalog, _, _ = made
    other = tmp_path / "bare"
    shutil.copytree(tables, other)
    (other / "derived" / "client" / "effect-spells.json").unlink()
    spec = release.TrioSpec(slug=SLUG, results=str(tmp_path / "out"), catalog=str(catalog), tables_root=str(other), narrow={"races": ["OGR"], "roles": ["tank"]}, tiers=(4,))
    outcome = release.run_trio(spec)
    assert outcome.status == "failed" and "effect-spells.json" in outcome.error, outcome
