"""Tests for the PC release build on a tiny real world: two trios of the invented catalog, solved for real.

The world is small on purpose: the invented catalog of ``test_precompute.py`` (about 25 items, every name and number invented), a copy of the tables in
which only the Ogre and the Troll are playable, and two trios that play the Melee damage build alone. The scope is the real one (+0, +4 and +10), the
solver is the real one, and the catalog has no strict item: wiki is the one evidence level of a release. What is held:

* **resumption**: a trio that is finished is not run again; an interrupted one resumes from its chunk files, and no chunk whose inputs did not change is
  made again (a kill by its process id included); a changed input makes the chunks again;
* **the grid**: a missing trio, a partial one and one at another scope are each refused, and nothing is packed;
* **each release check** refuses on a fault injected into a copy of the results: the invariants, the bundles against the public catalog, the
  pruning spot check against the unpruned optimum; a catalog with a strict item is refused before any hour is spent;
* **the build**: the asset, the pointer, the report; what the asset holds and what no output holds; a refusal at any step leaves nothing behind.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from release_helpers import FakeGit, change_sources, edit, load
from test_precompute import TOOLS_INPUT, small_world, write_catalog
from test_privacy_helpers import commit, gitenv, make_repo, privacy_files, write_key_file  # noqa: F401 (gitenv is a fixture)
from test_privacy_helpers import git as run_git
from test_release_assemble import make_junction
from test_site_build import reindex

from trioforge.data.jsonio import load_strict
from trioforge.effects import files as effects_files
from trioforge.precompute import assemble, release, shards
from trioforge.precompute.assemble import ReleaseRefused

REPO = Path(__file__).resolve().parents[2]
PIPELINE = REPO / "pipeline"
TRIOS = ("brd-bst-ber", "brd-rog-ber")  # the Melee damage build alone
CHUNKS = 24  # the chunks of each: strict (2 setups: 2h and dw) and wiki (2 setups: the Melee damage build never takes a shield) x buff sets (2) x tiers (3)
TAG = "data-2026-10-17"
ASSETS = tuple(f"assets/part-{n:08X}.js" for n in range(14))


def no_check(*args, **kwargs):
    return {"bundles": 0, "profiles": 0, "records": 0, "tiers": 11}


def pass_parity(folder, sample, files):
    return 0, "ok\n"


def make_world(directory: Path) -> SimpleNamespace:
    """A world: tables, catalog, privacy lists and key, and empty build/, releases/ and reports/ folders."""
    root = directory
    small_world(root)
    catalog = write_catalog(root / "derived" / "catalog.json")
    privacy_files(root)
    key = write_key_file(root / "keys")
    for name in ("build", "releases", "reports"):
        (root / name).mkdir()
    return world_at(root)


def world_at(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        root=root, catalog=root / "derived" / "catalog.json", key=root / "keys" / "privacy.key", results=root / "build" / "results"
    )


def spec_for(world, slug: str, **over) -> release.TrioSpec:
    values = dict(results=str(world.results), catalog=str(world.catalog), tables_root=str(world.root))
    values.update(over)
    return release.TrioSpec(slug, **values)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    made = make_world(tmp_path_factory.mktemp("world"))
    made.outcomes = release.precompute_grid([spec_for(made, slug) for slug in TRIOS], processes=2, say=lambda message: None)
    return made


def clone(world, tmp_path, name: str = "w") -> SimpleNamespace:
    """A copy of the world, with its results and chunk files."""
    shutil.copytree(world.root, tmp_path / name)
    return world_at(tmp_path / name)


def shipped(world, tmp_path) -> Path:
    """The files of a release as a folder to hold the checks to: a copy of the results without their chunk files."""
    folder = tmp_path / "release-files"
    shutil.copytree(world.results, folder, ignore=shutil.ignore_patterns("chunks"))
    return folder


def chunk_files(world, slug: str) -> dict[str, tuple[bytes, int]]:
    folder = world.results / slug / "chunks"
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(folder.glob("s-*.json"))}


def files_under(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) if root.exists() else []


# ---- the pool, the marker, and resumption ------------------------------------------------------------------------------------------------------


def test_the_grid_is_run_in_a_pool_of_processes_and_every_trio_has_its_files(world):
    assert [o.slug for o in world.outcomes] == list(TRIOS)  # in the order of the specs, whichever finished first
    for outcome in world.outcomes:
        assert outcome.status == "done" and outcome.violations == [] and outcome.chunks == CHUNKS and outcome.scenarios == CHUNKS * 2
        folder = world.results / outcome.slug
        assert {p.name for p in folder.glob("*.json")} == {"strict-own.json", "strict-group.json", "wiki-own.json", "wiki-group.json", "defaults.json", "robust.json", "engine-l50.json"}
        assert (folder / "runnerups" / "melee.json").is_file() and (folder / "chunks" / release.MARKER).is_file()
    assert (world.results / "items.json").is_file()


def test_the_item_table_is_the_one_every_run_would_write(world):
    for outcome in world.outcomes:
        assert not [n for n in outcome.notes if "replaced" in n or "other inputs" in n]


def test_a_finished_trio_is_not_run_again(world, tmp_path):
    copy = clone(world, tmp_path)
    before = {p: p.stat().st_mtime_ns for p in (copy.results / TRIOS[0]).rglob("*") if p.is_file()}
    outcome = release.run_trio(spec_for(copy, TRIOS[0]))
    assert outcome.status == "resumed" and outcome.solved == 0 and outcome.redone == 0 and outcome.reused == outcome.chunks == CHUNKS
    assert {p: p.stat().st_mtime_ns for p in (copy.results / TRIOS[0]).rglob("*") if p.is_file()} == before  # not a file was written


def test_the_file_of_the_effects_layer_beside_the_results_does_not_make_a_finished_trio_run_again(world, tmp_path):
    """E6: ``exalt.json`` is written after the marker (it is made from the shipped kits, by every build, resumed trios included), so the marker's digests of the result files leave it out: a trio
    that finished is resumed with the file in its folder, and the marker stays what it was. The file is no staleness risk: a build writes it again for every trio, the shards it is made from are
    in the digests, and one altered by hand is replaced."""
    copy = clone(world, tmp_path)
    marker = copy.results / TRIOS[0] / "chunks" / release.MARKER
    before = marker.read_bytes()
    (copy.results / TRIOS[0] / effects_files.TRIO_FILE).write_text('{"version": 1}', encoding="utf-8")
    assert effects_files.TRIO_FILE not in release._result_digests(copy.results / TRIOS[0])
    outcome = release.run_trio(spec_for(copy, TRIOS[0]))
    assert outcome.status == "resumed" and outcome.solved == 0 and outcome.redone == 0
    assert marker.read_bytes() == before
    (copy.results / TRIOS[0] / effects_files.TRIO_FILE).unlink()  # (the stand-in has no headers: a made-again trio would refuse it)
    with (copy.results / TRIOS[0] / "robust.json").open("a", encoding="utf-8") as handle:
        handle.write(chr(10))  # (a result file that changed is still caught: the trio is made again)
    again = release.run_trio(spec_for(copy, TRIOS[0]))
    assert again.status == "done", again.error


def test_an_interrupted_trio_resumes_from_its_finished_chunks_and_makes_no_chunk_again(world, tmp_path):
    scratch = make_world(tmp_path / "scratch")
    first = release.run_trio(spec_for(scratch, TRIOS[0], limit=7))
    assert first.status == "limited"
    before = chunk_files(scratch, TRIOS[0])
    assert len(before) == 7 and not (scratch.results / TRIOS[0] / "defaults.json").exists()  # no result file, no marker
    assert not (scratch.results / TRIOS[0] / "chunks" / release.MARKER).exists()
    second = release.run_trio(spec_for(scratch, TRIOS[0]))
    assert second.status == "done" and second.reused == 7 and second.redone == 0 and second.chunks == CHUNKS
    after = chunk_files(scratch, TRIOS[0])
    assert len(after) == CHUNKS and all(after[name] == before[name] for name in before)  # the seven are the very files (bytes and time) of the first run


def test_the_result_files_of_a_resumed_trio_are_those_of_a_run_that_was_not_interrupted(world, tmp_path):
    scratch = make_world(tmp_path / "scratch")
    release.run_trio(spec_for(scratch, TRIOS[0], limit=11))
    release.run_trio(spec_for(scratch, TRIOS[0]))
    found = 0
    for path in sorted((world.results / TRIOS[0]).rglob("*")):
        relative = path.relative_to(world.results / TRIOS[0])
        if path.is_file() and relative.parts[0] != "chunks":
            found += 1
            assert (scratch.results / TRIOS[0] / relative).read_bytes() == path.read_bytes(), relative.as_posix()
    assert found == 9  # four shards, the defaults, the seals, the bundle, the runner-ups of the role and their index


def test_the_leftovers_of_a_write_that_was_cut_short_are_cleared_before_a_trio_is_run(world, tmp_path):
    scratch = make_world(tmp_path / "scratch")
    release.run_trio(spec_for(scratch, TRIOS[0], limit=3))
    folder = scratch.results / TRIOS[0]
    leftovers = [folder / "chunks" / ".s-wiki-own-melee-dw-t04.json.ab12.tmp", folder / ".defaults.json.cd34.tmp"]
    (folder / "runnerups").mkdir()
    leftovers.append(folder / "runnerups" / ".melee.json.ef56.tmp")
    for path in leftovers:
        path.write_text("{", encoding="utf-8")
    outcome = release.run_trio(spec_for(scratch, TRIOS[0]))
    assert outcome.status == "done" and not any(p.exists() for p in leftovers)
    assemble.stage(scratch.results, [TRIOS[0]], tmp_path / "stage")  # (a release would have refused the one in the trio's folder)


def test_a_kill_in_the_middle_of_a_run_leaves_no_half_chunk_and_the_next_run_makes_no_chunk_again(tmp_path):
    """A child process runs a whole trio (all 15 races, so that it takes a while); it is killed by its process id once some chunks are done."""
    scratch = make_world(tmp_path / "scratch")
    spec = spec_for(scratch, TRIOS[0], tables_root=None)  # (the real tables: 15 races)
    code = "import json, sys; from trioforge.precompute import release; release.run_trio(release.TrioSpec(**json.loads(sys.argv[1])))"
    environment = {**os.environ, "PYTHONPATH": str(PIPELINE), "PYTHONUTF8": "1"}
    process = subprocess.Popen([sys.executable, "-c", code, json.dumps(asdict(spec))], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    folder = scratch.results / TRIOS[0] / "chunks"
    try:
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline and process.poll() is None and len(list(folder.glob("s-*.json"))) < 6:
            time.sleep(0.05)
        process.kill()  # (a process this test started, by its handle)
    finally:
        process.wait(timeout=60)
    before = chunk_files(scratch, TRIOS[0])
    assert len(before) >= 6
    for name in before:  # a chunk has its final name only when it is whole: each one is read back whole and made from these inputs
        text = (folder / name).read_text(encoding="utf-8")
        document, state = shards.load_chunk(folder / name, json.loads(text)["fingerprint"])
        assert state == "ok" and document is not None, name
    outcome = release.run_trio(spec)
    assert outcome.status == "done" and outcome.reused >= len(before) and outcome.redone == 0
    after = chunk_files(scratch, TRIOS[0])
    assert all(after[name] == before[name] for name in before)  # no chunk that was whole before the kill was made again
    assert not list(folder.glob("*.tmp")) and not list((scratch.results / TRIOS[0]).glob("*.tmp"))


def test_a_changed_input_makes_the_chunks_again_and_an_unchanged_one_makes_none(world, tmp_path):
    copy = clone(world, tmp_path)
    document = json.loads(copy.catalog.read_text(encoding="utf-8"))
    document["items"][0]["stats"]["STA"] = document["items"][0]["stats"].get("STA", 0) + 1  # one stat of one item
    copy.catalog.write_text(json.dumps(document), encoding="utf-8")
    outcome = release.run_trio(spec_for(copy, TRIOS[0]))
    assert outcome.status == "done" and outcome.reused == 0 and outcome.redone == CHUNKS  # every chunk of the trio was made from the old catalog
    again = release.run_trio(spec_for(copy, TRIOS[0]))
    assert again.status == "resumed" and again.solved == 0


def test_a_result_file_that_was_changed_after_the_trio_finished_is_made_again_from_the_chunks(world, tmp_path):
    copy = clone(world, tmp_path)
    target = copy.results / TRIOS[0] / "wiki-own.json"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    outcome = release.run_trio(spec_for(copy, TRIOS[0]))
    assert outcome.status == "done" and outcome.reused == CHUNKS and outcome.solved == 0  # the marker was not trusted, the chunks were
    assert target.read_bytes() == (world.results / TRIOS[0] / "wiki-own.json").read_bytes()


def test_a_scope_other_than_the_one_the_marker_was_made_for_is_not_resumed_but_its_chunks_are_kept(world, tmp_path):
    copy = clone(world, tmp_path)
    outcome = release.run_trio(spec_for(copy, TRIOS[0], tiers=(0, 4)))
    assert outcome.status == "done" and outcome.chunks == CHUNKS * 2 // 3 and outcome.reused == CHUNKS * 2 // 3 and outcome.solved == 0  # (a chunk is one view: the scope is not part of it)
    marker = json.loads((copy.results / TRIOS[0] / "chunks" / release.MARKER).read_text(encoding="utf-8"))
    assert marker["tiers"] == [0, 4]


def test_a_run_that_is_narrowed_leaves_no_marker(world, tmp_path):
    scratch = make_world(tmp_path / "scratch")
    outcome = release.run_trio(spec_for(scratch, TRIOS[0], narrow={"races": ["OGR"], "roles": ["melee"]}, tables_root=None))
    assert outcome.status == "partial" and not (scratch.results / TRIOS[0] / "chunks" / release.MARKER).exists()


def test_a_trio_that_fails_is_reported_and_the_others_still_run(world, tmp_path):
    scratch = make_world(tmp_path / "scratch")
    specs = [spec_for(scratch, TRIOS[0], limit=2), spec_for(scratch, "brd-xxx-ber"), spec_for(scratch, TRIOS[1], limit=2)]
    outcomes = release.precompute_grid(specs, processes=1, say=lambda message: None)
    assert [o.status for o in outcomes] == ["limited", "failed", "limited"] and "trio" in outcomes[1].error


def test_an_input_nothing_can_run_without_stops_the_whole_precompute(world, tmp_path):
    scratch = make_world(tmp_path / "scratch")
    with pytest.raises(ReleaseRefused, match="catalog"):
        release.precompute_grid([spec_for(scratch, TRIOS[0], catalog=str(tmp_path / "no-such-catalog.json"))], processes=1, say=lambda message: None)


def test_a_precompute_prints_counts_and_never_an_item(world, tmp_path):
    scratch = make_world(tmp_path / "scratch")
    lines: list[str] = []
    release.precompute_grid([spec_for(scratch, TRIOS[0], limit=2)], processes=1, say=lines.append)
    text = "\n".join(lines)
    assert "1/1" in text and "w9" not in text


# ---- the grid: a missing, a partial and a wrong-scope trio -----------------------------------------------------------------------------------------


def test_every_trio_of_the_grid_present_complete_and_at_its_scope_passes(world, tmp_path):
    facts = release.check_grid(shipped(world, tmp_path), TRIOS)
    assert [f.slug for f in facts] == list(TRIOS)
    for fact in facts:
        assert fact.tiers == (0, 4, 10) and fact.roles == ("melee",) and fact.levels == (50,) and fact.data_tag == "data-2030-01-02" and fact.level == 50
        assert fact.chunks == CHUNKS  # the views the parity suite draws its sample from


def test_a_missing_trio_is_refused_by_name(world, tmp_path):
    folder = shipped(world, tmp_path)
    with pytest.raises(ReleaseRefused, match=r"missing.*clr-dru-enc|clr-dru-enc.*missing"):
        release.check_grid(folder, [*TRIOS, "clr-dru-enc"])
    shutil.rmtree(folder / TRIOS[1])
    with pytest.raises(ReleaseRefused, match=TRIOS[1]):
        release.check_grid(folder, TRIOS)


def test_a_trio_with_a_result_file_gone_is_missing_too(world, tmp_path):
    folder = shipped(world, tmp_path)
    (folder / TRIOS[0] / "wiki-group.json").unlink()
    with pytest.raises(ReleaseRefused, match=rf"{TRIOS[0]}.*(missing|wiki-group)"):
        release.check_grid(folder, TRIOS)


def test_many_missing_trios_are_counted_and_the_first_few_named(world, tmp_path):
    with pytest.raises(ReleaseRefused, match=r"558 trios") as raised:
        release.check_grid(shipped(world, tmp_path), assemble.grid_trios())
    assert "war-clr-pal" in str(raised.value) and "more" in str(raised.value)


def test_a_partial_trio_is_refused(world, tmp_path):
    folder = shipped(world, tmp_path)
    partial = make_world(tmp_path / "partial")
    release.run_trio(spec_for(partial, TRIOS[0], narrow={"races": ["OGR", "TRL"], "roles": ["melee"]}, tables_root=None))
    shutil.rmtree(folder / TRIOS[0])
    shutil.copytree(partial.results / TRIOS[0], folder / TRIOS[0], ignore=shutil.ignore_patterns("chunks"))
    # (the narrowed run is a run of the real tables with two of their fifteen races: its files say so)
    with pytest.raises(ReleaseRefused, match=rf"{TRIOS[0]}.*partial"):
        release.check_grid(folder, TRIOS)


def test_a_trio_at_another_scope_than_a_full_run_of_it_is_refused(world, tmp_path):
    folder = shipped(world, tmp_path)
    other = make_world(tmp_path / "other")
    release.run_trio(spec_for(other, TRIOS[0], tiers=(0, 4)))
    shutil.rmtree(folder / TRIOS[0])
    shutil.copytree(other.results / TRIOS[0], folder / TRIOS[0], ignore=shutil.ignore_patterns("chunks"))
    with pytest.raises(ReleaseRefused, match=rf"{TRIOS[0]}.*needs \+0, \+4, \+10"):
        release.check_grid(folder, TRIOS)


def test_the_scope_of_a_trio_can_be_named_for_a_sample(world, tmp_path):
    folder = shipped(world, tmp_path)
    release.check_grid(folder, TRIOS, scopes={TRIOS[0]: (0, 4, 10)})
    with pytest.raises(ReleaseRefused, match=TRIOS[0]):
        release.check_grid(folder, TRIOS, scopes={TRIOS[0]: (0, 4)})


def test_a_file_the_site_build_cannot_read_is_refused_with_its_name(world, tmp_path):
    folder = shipped(world, tmp_path)
    edit(folder / TRIOS[0] / "defaults.json", lambda d: d.pop("race"))
    with pytest.raises(ReleaseRefused, match=rf"{TRIOS[0]}.*defaults\.json"):
        release.check_grid(folder, TRIOS)


def test_trios_of_other_data_than_each_other_are_refused(world, tmp_path):
    folder = shipped(world, tmp_path)
    for name in ("strict-own", "strict-group", "wiki-own", "wiki-group", "defaults", "robust", "runnerups/melee", "runnerups/index", "engine-l50"):
        edit(folder / TRIOS[1] / f"{name}.json", lambda d: d.update(data_release="data-2030-01-03"))
    reindex(folder / TRIOS[1] / "runnerups")
    with pytest.raises(ReleaseRefused, match=r"one data release") as raised:
        release.check_grid(folder, TRIOS)
    assert TRIOS[0] in str(raised.value) and TRIOS[1] in str(raised.value) and "data-2030-01-03" in str(raised.value)


def test_trios_made_with_other_rules_or_for_another_level_are_not_one_release_either():
    one = release.TrioFacts("a-b-c", (0, 4, 10), ("melee",), (50,), "data-2030-01-02", "2026-10-13", "2026-09-22", 50)
    release.check_consistent([one, one])
    for change in ({"rules_version": "2026-10-14"}, {"game_patch": "2026-09-23"}, {"level": 55}, {"data_tag": "data-2030-01-03"}):
        other = release.TrioFacts(**{**asdict(one), "slug": "d-e-f", **change})
        with pytest.raises(ReleaseRefused, match="one data release|one run|differ"):
            release.check_consistent([one, other])


# ---- the invariants ------------------------------------------------------------------------------------------------------------------------------


def set_value(folder: Path, name: str, race: str, tier: int, value: float, *, slug: str = TRIOS[0], role: str = "melee", setup: str = "dw") -> None:
    """Give one row of a shard another value, and the gain that keeps the naked character's value what it was."""

    def change(document):
        row = next(r for r in document["scenarios"] if r[:4] == [race, role, tier, setup])
        row[6] = round(row[6] + (value - row[5]), 2)
        row[5] = value

    edit(folder / slug / f"{name}.json", change)


def value_of(folder: Path, name: str, race: str, tier: int, *, slug: str = TRIOS[0], role: str = "melee", setup: str = "dw") -> float:
    return next(r for r in load(folder / slug / f"{name}.json")["scenarios"] if r[:4] == [race, role, tier, setup])[5]


def test_the_invariants_hold_on_what_the_solver_made(world, tmp_path):
    assert release.check_invariants(shipped(world, tmp_path), TRIOS) == len(TRIOS)


def test_a_tier_that_is_worth_less_than_the_one_below_refuses_the_release(world, tmp_path):
    folder = shipped(world, tmp_path)
    set_value(folder, "wiki-own", "OGR", 10, value_of(folder, "wiki-own", "OGR", 4) - 5.0)
    with pytest.raises(ReleaseRefused, match="falls with the tier") as raised:
        release.check_invariants(folder, TRIOS)
    assert TRIOS[0] in str(raised.value)


def test_a_value_below_the_naked_character_refuses_the_release(world, tmp_path):
    folder = shipped(world, tmp_path)
    document = load(folder / TRIOS[0] / "wiki-own.json")
    row = next(r for r in document["scenarios"] if r[:4] == ["OGR", "melee", 4, "dw"])
    set_value(folder, "wiki-own", "OGR", 4, round(row[5] - row[6] - 10.0, 2))  # ten under the naked value
    with pytest.raises(ReleaseRefused, match="below the empty kit|falls with the tier"):
        release.check_invariants(folder, TRIOS)


def test_strict_may_never_be_worth_more_than_wiki(world, tmp_path):
    folder = shipped(world, tmp_path)
    set_value(folder, "strict-own", "OGR", 4, value_of(folder, "wiki-own", "OGR", 4) + 5.0)
    with pytest.raises(ReleaseRefused, match="strict above wiki"):
        release.check_invariants(folder, TRIOS)


def test_own_buffs_may_never_be_worth_more_than_group_buffs(world, tmp_path):
    folder = shipped(world, tmp_path)
    set_value(folder, "wiki-own", "TRL", 0, value_of(folder, "wiki-group", "TRL", 0) + 5.0)
    with pytest.raises(ReleaseRefused, match="own above group"):
        release.check_invariants(folder, TRIOS)


def test_the_value_of_the_naked_character_is_one_number_for_a_race_role_and_buff_set(world, tmp_path):
    folder = shipped(world, tmp_path)

    def change(document):
        document["scenarios"][0][6] += 50.0  # the gain: F less the naked value, which is one number for the race, the role and the buffs

    edit(folder / TRIOS[0] / "wiki-group.json", change)
    with pytest.raises(ReleaseRefused, match="naked"):
        release.check_invariants(folder, TRIOS)


def test_a_violation_the_run_itself_found_refuses_the_release(world, tmp_path):
    outcomes = [release.TrioOutcome(slug=TRIOS[0], status="done", violations=["wiki-own.json is 210,000 bytes raw, over the 200,000-byte budget"])]
    with pytest.raises(ReleaseRefused, match=rf"{TRIOS[0]}.*over the 200,000-byte budget"):
        release.check_invariants(shipped(world, tmp_path), TRIOS, outcomes)


def test_a_rounding_unit_of_a_shard_is_no_violation_and_more_than_one_is(world, tmp_path):
    folder = shipped(world, tmp_path)
    for buffs in ("own", "group"):  # (the strict shards of a release hold the naked-plus-buffs kits: bring them up to wiki's values, so that only the rounding is tried)
        for tier in (0, 4, 10):
            set_value(folder, f"strict-{buffs}", "OGR", tier, value_of(folder, f"wiki-{buffs}", "OGR", tier))
    wiki = value_of(folder, "wiki-own", "OGR", 4)
    set_value(folder, "strict-own", "OGR", 4, wiki)  # equal ...
    set_value(folder, "wiki-own", "OGR", 4, round(wiki - 0.01, 2))  # ... and a hundredth the other way: two roundings of the same value
    release.check_invariants(folder, TRIOS)
    set_value(folder, "wiki-own", "OGR", 4, round(wiki - 0.05, 2))
    with pytest.raises(ReleaseRefused, match="strict above wiki"):
        release.check_invariants(folder, TRIOS)


# ---- the bundles against the public catalog -----------------------------------------------------------------------------------------------------


def test_every_bundle_is_the_one_exported_from_the_catalog_and_follows_the_shard_headers(world, tmp_path):
    folder = shipped(world, tmp_path)
    assert release.check_bundles(folder, TRIOS, catalog=world.catalog, tables_root=world.root) == len(TRIOS)


def test_wiki_is_the_one_evidence_level_of_a_release_the_strict_shards_hold_no_pool_and_the_melee_build_has_no_shield_at_either(world):
    bundle = load(world.results / TRIOS[0] / "engine-l50.json")
    shard = load(world.results / TRIOS[0] / "strict-own.json")
    assert shard["flags"] == ["strict pool empty"] and shard["pool"] == 0
    setups = bundle["roles"]["melee"]["setups_by_evidence"]
    assert setups["strict"] == setups["wiki"] == shard["setups"]["melee"] == ["2h", "dw"]  # (Melee damage never takes one hand and a shield: a pool cannot add it)


def test_a_bundle_whose_strict_setups_are_not_the_shard_headers_is_refused(world, tmp_path):
    folder = shipped(world, tmp_path)
    edit(folder / TRIOS[0] / "strict-own.json", lambda d: d["setups"].update(melee=[*d["setups"]["melee"], "1h-shield"]))
    with pytest.raises(ReleaseRefused, match=rf"{TRIOS[0]}.*strict") as raised:
        release.check_bundles(folder, TRIOS, catalog=world.catalog, tables_root=world.root)
    assert "melee" in str(raised.value) and "strict-own.json" in str(raised.value)


def test_a_bundle_that_is_not_what_the_exporter_writes_from_that_catalog_is_refused(world, tmp_path):
    folder = shipped(world, tmp_path)
    edit(folder / TRIOS[1] / "engine-l50.json", lambda b: b["constants"].update(hp_pool_constant="1/1"))
    with pytest.raises(ReleaseRefused, match=TRIOS[1]) as raised:
        release.check_bundles(folder, TRIOS, catalog=world.catalog, tables_root=world.root)
    assert "exporter" in str(raised.value)


def test_an_item_whose_level_in_the_release_is_not_the_one_in_that_catalog_is_refused(world, tmp_path):
    folder = shipped(world, tmp_path)

    def change(table):
        for record in table["items"]:
            if record.get("key") == "w9014" or record["id"] == 9014:
                record["evidence"] = {"level": "strict"}

    edit(folder / "items.json", change)
    with pytest.raises(ReleaseRefused, match=r"w9014.*level"):
        release.check_bundles(folder, TRIOS, catalog=world.catalog, tables_root=world.root)


# ---- a catalog with a strict item is refused: wiki is the one evidence level ------------------------------------------------------------------------


def with_a_strict_item(path: Path, count: int = 1) -> list[str]:
    """Make the first ``count`` items of a catalog strict, as a community report would; the keys of them."""
    document = json.loads(path.read_text(encoding="utf-8"))
    for item in document["items"][:count]:
        item["evidence"]["level"] = "strict"
    path.write_text(json.dumps(document), encoding="utf-8")
    return [item["key"] for item in document["items"][:count]]


def test_the_guard_passes_a_catalog_whose_items_are_wiki_disputed_or_hidden_and_refuses_one_strict_item(world):
    document = json.loads(world.catalog.read_text(encoding="utf-8"))
    release.check_no_strict_item(document)  # the catalog of the world: every item is a wiki item
    document["items"][0]["evidence"]["level"] = "disputed"
    document["items"][1]["evidence"]["level"] = "hidden"
    release.check_no_strict_item(document)
    document["items"][2]["evidence"]["level"] = "strict"
    with pytest.raises(ReleaseRefused, match=r"1 strict item.*rules/community-seen\.json") as raised:
        release.check_no_strict_item(document)
    assert document["items"][2]["key"] not in str(raised.value)  # (it names the list of reports, never an item)


def test_the_guard_refuses_a_catalog_whose_items_it_cannot_read_and_counts_an_item_whose_evidence_is_not_a_mapping_as_not_strict():
    for document in ({}, {"items": {"a": {"evidence": {"level": "strict"}}}}, {"items": None}):
        with pytest.raises(ReleaseRefused, match=r"no list of items"):
            release.check_no_strict_item(document)
    release.check_no_strict_item({"items": [{"key": "a", "evidence": "strict"}, "not an item"]})


def test_a_release_is_not_built_from_a_catalog_with_a_strict_item_and_the_refusal_comes_before_the_hours(world, tmp_path):
    copy = clone(world, tmp_path)
    keys = with_a_strict_item(copy.catalog, 3)
    calls: list[str] = []
    with pytest.raises(ReleaseRefused, match=r"3 strict items.*wiki is the one evidence level.*rules/community-seen\.json") as raised:
        build(world, tmp_path, runner=lambda spec: calls.append(spec.slug))
    assert calls == [] and not any(key in str(raised.value) for key in keys)
    nothing_left(copy.root)


# ---- the source of the items of a hand-listed zone (p7nekfix) -----------------------------------------------------------------------------------

ZONE_PAGE = "https://eqlegendstools.com/zones/nektropos-castle/"


def hand_lists_file(rules: Path, source: str | None = ZONE_PAGE) -> None:
    """Write a ``rules/hand-lists.json`` whose exists-unflagged zones are one the developers' notes settle and one that rests on ``source``."""
    rules.mkdir(parents=True, exist_ok=True)
    zones = [{"names": ["The Arena"], "ids": [77], "seal": "developer", "source": [{"kind": "url", "ref": "https://eqlwiki.com/index.php?title=Patch_Notes"}], "date": "2026-06-23"}]
    if source:
        zones.append({"names": ["Nektropos Castle"], "ids": [28], "seal": "player", "source": [{"kind": "url", "ref": source}], "date": "2026-10-25"})
    (rules / "hand-lists.json").write_text(json.dumps({"version": "2026-10-14", "exists_unflagged_zones": zones}), encoding="utf-8")


def provenance_of(*files: str) -> dict:
    return {"version": "2030-01-02", "provenance": {"inputs": [{"file": name, "sha256": "00" * 32, "date": "2026-10-27"} for name in files]}}


def test_a_hand_listed_zone_of_eql_legends_tools_needs_that_source_in_the_catalog(tmp_path):
    rules = tmp_path / "rules"
    hand_lists_file(rules)
    release.check_eqlegendstools_source(rules, provenance_of("derived/client/zones.json", ZONE_PAGE))  # built with the source: passes
    for document in (provenance_of("derived/client/zones.json"), provenance_of(), {"version": "x"}):  # built without it: stops, and says why
        with pytest.raises(ReleaseRefused, match=r"Nektropos Castle.*eqlegendstools.*--eqlegendstools.*build the catalog again"):
            release.check_eqlegendstools_source(rules, document)


def test_the_source_of_a_hand_listed_zone_is_compared_in_one_form_on_both_sides(tmp_path):
    rules = tmp_path / "rules"
    no_slash = ZONE_PAGE.rstrip("/")
    for written, recorded in (
        (ZONE_PAGE, no_slash),  # (a trailing slash on one side only)
        (no_slash, ZONE_PAGE),
        ("https://EQLegendsTools.com/zones/nektropos-castle/", ZONE_PAGE),  # (host case)
        ("HTTPS://eqlegendstools.com/zones/nektropos-castle/", ZONE_PAGE),  # (scheme case)
        ("http://eqlegendstools.com/zones/nektropos-castle/", ZONE_PAGE),  # (scheme)
        ("https://www.eqlegendstools.com/zones/nektropos-castle/", ZONE_PAGE),  # (www)
        (ZONE_PAGE, "https://EQLEGENDSTOOLS.com/zones/nektropos-castle"),
    ):
        hand_lists_file(rules, source=written)
        release.check_eqlegendstools_source(rules, provenance_of("derived/client/zones.json", recorded))
    for written in ("http://eqlegendstools.com/zones/nektropos-castle", "https://www.EQLegendsTools.com/zones/nektropos-castle/",
                    "https://eqlegendstools.com:8443/zones/nektropos-castle", "https://eqlegendstools.com./zones/nektropos-castle"):
        hand_lists_file(rules, source=written)  # (an equivalent form of the site's address still asks for the site's page in the catalog)
        with pytest.raises(ReleaseRefused, match=r"Nektropos Castle.*--eqlegendstools"):
            release.check_eqlegendstools_source(rules, provenance_of("derived/client/zones.json"))
    hand_lists_file(rules)
    for other in ("https://eqlegendstools.com.example.invalid/zones/nektropos-castle/", "https://eqlegendstools.com/zones/other-zone/", "https://eqlwiki.com/zones/nektropos-castle/"):
        with pytest.raises(ReleaseRefused, match=r"Nektropos Castle.*--eqlegendstools"):
            release.check_eqlegendstools_source(rules, provenance_of(other))


def test_a_catalog_that_names_no_page_of_eql_legends_tools_is_refused_whatever_the_hand_lists_say(tmp_path):
    """The items of the zone pages of EQ Legends Tools are the site's, not the wiki's: a catalog built without ``--eqlegendstools`` has the wiki's copy of them, and a release is not built from it,
    with a hand-listed zone of the site or without one (the hand list used to be the only thing that asked)."""
    nothing_named = (provenance_of(), provenance_of("derived/client/zones.json", "https://eqlwiki.com/index.php?title=Category:Items"), {"version": "x"}, {"provenance": {"inputs": "none"}},
                     provenance_of("https://eqlegendstools.com.example.invalid/zones/nektropos-castle/", "https://eqlwiki.com/zones/nektropos-castle/"))  # fmt: skip
    release.check_eqlegendstools_source(tmp_path / "no-hand-lists", provenance_of("derived/client/zones.json", ZONE_PAGE))  # (a catalog that names a page of the site is as it was)
    for document in nothing_named:
        with pytest.raises(ReleaseRefused, match=r"names no EQ Legends Tools page.*--eqlegendstools.*build the catalog again"):
            release.check_eqlegendstools_source(tmp_path / "no-hand-lists", document)  # no hand-lists file at all
        hand_lists_file(tmp_path / "only-developers", source=None)
        with pytest.raises(ReleaseRefused, match=r"names no EQ Legends Tools page.*--eqlegendstools.*build the catalog again"):
            release.check_eqlegendstools_source(tmp_path / "only-developers", document)  # only a zone of the developers' notes
    hand_lists_file(tmp_path / "listed")
    with pytest.raises(ReleaseRefused, match=r"Nektropos Castle.*eqlegendstools.*--eqlegendstools.*build the catalog again"):  # a hand-listed zone of the site keeps its own refusal
        release.check_eqlegendstools_source(tmp_path / "listed", provenance_of())


def test_no_hand_listed_zone_of_that_source_asks_nothing_more_of_a_catalog_that_names_the_site(tmp_path):
    named = provenance_of("derived/client/zones.json", ZONE_PAGE)  # (a catalog that names no page of the site is refused whatever the hand lists say: the test before this one)
    release.check_eqlegendstools_source(tmp_path / "rules", named)  # no hand-lists file at all
    hand_lists_file(tmp_path / "rules", source=None)  # only a zone of the developers' notes
    release.check_eqlegendstools_source(tmp_path / "rules", named)


def without_the_tools_page(copy) -> None:
    """The catalog of a copy of the world as if it had been built without ``--eqlegendstools``: its provenance names no page of the site (the catalogs of the world name one, as the committed one does)."""
    document = json.loads(copy.catalog.read_text(encoding="utf-8"))
    document["provenance"] = {"inputs": [record for record in document["provenance"]["inputs"] if "eqlegendstools" not in record["file"]]}
    copy.catalog.write_text(json.dumps(document), encoding="utf-8")


def test_a_catalog_built_without_the_eql_legends_tools_source_is_refused_before_any_hour_is_spent(world, tmp_path):
    copy = clone(world, tmp_path)
    hand_lists_file(copy.root / "rules")
    without_the_tools_page(copy)  # (the world's catalog names the page: this one is the catalog of a build without the option)
    calls: list[str] = []
    with pytest.raises(ReleaseRefused, match=r"Nektropos Castle.*eqlegendstools"):
        build(world, tmp_path, runner=lambda spec: calls.append(spec.slug))
    assert calls == []
    nothing_left(copy.root)


def test_a_catalog_built_without_the_eql_legends_tools_source_is_refused_before_any_hour_is_spent_with_no_hand_listed_zone_too(world, tmp_path):
    copy = clone(world, tmp_path, "no-entry")  # (no hand-lists entry of the site: the refusal no longer rests on one)
    without_the_tools_page(copy)
    calls: list[str] = []
    with pytest.raises(ReleaseRefused, match=r"names no EQ Legends Tools page.*--eqlegendstools"):
        build(world, tmp_path, name="no-entry", runner=lambda spec: calls.append(spec.slug))
    assert calls == []
    nothing_left(copy.root)


# ---- the pruning spot check -----------------------------------------------------------------------------------------------------------------------


def spot(world, folder, **over):
    return release.check_pruning(folder, TRIOS, catalog=world.catalog, tables_root=world.root, **{"seed": 7, **over})


def test_one_random_scenario_of_each_trio_is_as_good_as_the_unpruned_optimum(world, tmp_path):
    checked = spot(world, shipped(world, tmp_path))
    assert [c.slug for c in checked] == list(TRIOS)
    for one in checked:
        assert abs(one.solved - one.shipped) <= release.SPOT_TOLERANCE and one.view["race"] in ("OGR", "TRL")


def test_the_same_seed_picks_the_same_scenarios_and_other_seeds_pick_others(world, tmp_path):
    folder = shipped(world, tmp_path)
    picks = {seed: [tuple(c.view.values()) for c in spot(world, folder, seed=seed)] for seed in (7, 8, 9)}
    assert picks[7] == [tuple(c.view.values()) for c in spot(world, folder, seed=7)]  # the same seed, the same scenarios
    assert picks[8] != picks[7] or picks[9] != picks[7]  # (each trio has 144 rows to draw from)


def test_a_value_the_unpruned_optimum_does_not_confirm_refuses_the_release(world, tmp_path):
    folder = shipped(world, tmp_path)

    def seven_more(document):
        for row in document["scenarios"]:
            row[5] = round(row[5] + 7.0, 2)

    for name in ("strict-own", "strict-group", "wiki-own", "wiki-group"):
        edit(folder / TRIOS[0] / f"{name}.json", seven_more)
    with pytest.raises(ReleaseRefused, match=r"pruning") as raised:
        spot(world, folder, seed=3)
    assert TRIOS[0] in str(raised.value) and "unpruned" in str(raised.value)


def test_the_spot_check_draws_only_from_shards_that_have_a_pool(world, tmp_path):
    """E4: a shard with no item in its pool (the strict one of a release) has nothing pruned, so a draw there could never show a pruning loss: the draw leaves such shards out."""
    folder = shipped(world, tmp_path)
    drawn = lambda: {release._spot_draw(folder, TRIOS[0], seed)[0] for seed in range(60)}  # noqa: E731
    assert not json.loads((folder / TRIOS[0] / "strict-own.json").read_text(encoding="utf-8"))["items"]  # (the strict pool of this world is empty, as a release's is)
    assert drawn() == {"wiki"}
    wide = json.loads((folder / TRIOS[0] / "wiki-own.json").read_text(encoding="utf-8"))["items"]
    edit(folder / TRIOS[0] / "strict-own.json", lambda document: document.update(items=wide))  # (a strict shard that has a pool is drawn from)
    assert drawn() == {"strict", "wiki"}
    for name in ("strict-own", "strict-group", "wiki-own", "wiki-group"):
        edit(folder / TRIOS[0] / f"{name}.json", lambda document: document.update(items=[]))
    assert release._spot_draw(folder, TRIOS[0], 1)[0] in ("strict", "wiki")  # (no shard has a pool: the check still has a scenario to solve)


def test_the_spot_check_runs_in_a_pool_too(world, tmp_path):
    assert len(spot(world, shipped(world, tmp_path), seed=5, processes=2)) == 2


# ---- the build ----------------------------------------------------------------------------------------------------------------------------------


def build(world, tmp_path, *, tag: str = TAG, name: str = "w", **over):
    """A release built in a copy of the world (the trios are finished there, so the precompute is resumed), with the steps that need Node left to stand-ins."""
    if not (tmp_path / name).exists():
        clone(world, tmp_path, name)
    copy = world_at(tmp_path / name)
    lines: list[str] = []
    options = dict(
        tag=tag, root=copy.root, privacy_key=copy.key, processes=1, trios=TRIOS, trial=False, whole_grid=TRIOS, git=FakeGit(), say=lines.append,
        bundle_reader=no_check, assets=ASSETS, parity_runner=pass_parity, seed=1,
    )  # (whole_grid: the two trios of this world are the whole grid of its releases; git: the copy of the world is no work tree)
    options.update(over)
    return copy, release.build_release(**options), lines


def nothing_left(root: Path, tag: str = TAG) -> None:
    """After a refusal: none of the three outputs, no asset and no staging folder."""
    assert files_under(root / "releases") == [] and files_under(root / "reports") == []
    folder = root / "build" / "release"
    assert not folder.exists() or list(folder.iterdir()) == []


def test_a_release_is_built_packed_and_written_up(world, tmp_path):
    copy, result, lines = build(world, tmp_path)
    asset = copy.root / "build" / "release" / f"{TAG}.tar.gz"
    assert result.asset == asset and asset.is_file() and result.asset_sha256 == hashlib.sha256(asset.read_bytes()).hexdigest()
    pointer = assemble.read_pointer(copy.root / "releases" / f"{TAG}.json")
    assert pointer["asset_sha256"] == result.asset_sha256 and pointer["release"] == TAG
    assert files_under(copy.root / "reports") == [f"results-diff-{TAG}.md"]  # (the full diff names items: it stays in build/reports/, away from the asset)
    assert files_under(copy.root / "releases") == [f"{TAG}.json"]
    assert sorted(p.name for p in (copy.root / "build" / "release").iterdir()) == [f"{TAG}.tar.gz"]  # no staging folder, no temporary file, nothing else named for the tag
    assert result.trios == 2 and result.trial is False and result.pointer == copy.root / "releases" / f"{TAG}.json"
    text = "\n".join(lines)
    assert "privacy scan" in text and "0 findings" in text and TAG in text


def test_the_build_refuses_effects_files_that_the_files_check_passes_and_the_sites_reader_refuses(world, tmp_path, monkeypatch):
    copy = clone(world, tmp_path)
    (copy.results / "effects.json").write_text(json.dumps({"version": 1, "data_release": "data-1999-01-01", "effects": []}), encoding="utf-8")
    monkeypatch.setattr(release, "write_effects", lambda *args, **kwargs: True)  # (the world has no spell file to make the files from: the shared file above stands in for them)
    with pytest.raises(ReleaseRefused, match=r"site's reader.*effects\.json.*not from one run"):
        build(world, tmp_path)
    nothing_left(copy.root)


# ---- the community entries of the release --------------------------------------------------------------------------------------------------------
#
# release.json records the entries of rules/community-seen.json as the committed file holds them, read once at the start; the public catalog must have been built from that very
# file (its provenance records the SHA-256 of it), or the entries and the evidence of the items would not describe the same state.

COMMUNITY_REPORT = {"key": "w9004", "kind": "seen", "issue": 5, "date": "2026-10-14", "check": "item-window-screenshot"}
COMMUNITY_RETRACTION = {"key": "w9006", "issue": 7, "date": "2026-10-15", "reason": "rejected"}


def community_file(rules: Path, **document) -> str:
    """Write ``rules/community-seen.json`` in a folder and give the SHA-256 of what was written."""
    rules.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"version": "2026-10-15", "reports": [COMMUNITY_REPORT], "retracted": [COMMUNITY_RETRACTION], **document})
    (rules / "community-seen.json").write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def catalog_built_from(digest: str | None) -> dict:
    """The part of a public catalog that says what it was built from: the record of the list of reports, if there was one."""
    inputs = [{"file": "rules/community-seen.json", "sha256": digest, "date": "2026-10-15"}] if digest else []
    return {"version": "2030-01-02", "provenance": {"inputs": [*inputs, TOOLS_INPUT]}}  # (and the page of EQ Legends Tools that every release catalog names)


def test_with_no_file_and_a_catalog_that_was_built_with_none_the_release_has_no_entries(tmp_path):
    assert release.read_community(tmp_path / "rules", catalog_built_from(None)) == {"reports": [], "retracted": []}


def test_the_entries_are_those_of_the_file_when_the_catalog_was_built_from_it(tmp_path):
    digest = community_file(tmp_path / "rules")
    assert release.read_community(tmp_path / "rules", catalog_built_from(digest)) == {"reports": [COMMUNITY_REPORT], "retracted": [COMMUNITY_RETRACTION]}


def test_a_file_the_catalog_was_not_built_from_is_refused_and_so_is_a_catalog_built_from_a_file_that_is_not_there(tmp_path):
    digest = community_file(tmp_path / "rules")
    twice = catalog_built_from(digest)
    twice["provenance"]["inputs"] = twice["provenance"]["inputs"] * 2
    with pytest.raises(ReleaseRefused, match=r"community-seen\.json.*build the catalog again"):
        release.read_community(tmp_path / "rules", twice)  # a catalog that records the list twice is not one the builder wrote
    with pytest.raises(ReleaseRefused, match=r"community-seen\.json.*build the catalog again"):
        release.read_community(tmp_path / "rules", catalog_built_from(None))  # the catalog knows no file
    with pytest.raises(ReleaseRefused, match=r"community-seen\.json.*build the catalog again"):
        release.read_community(tmp_path / "rules", catalog_built_from("00" * 32))  # another file
    community_file(tmp_path / "rules", reports=[])  # the file changed after the catalog was built
    with pytest.raises(ReleaseRefused, match=r"community-seen\.json.*build the catalog again"):
        release.read_community(tmp_path / "rules", catalog_built_from(digest))
    (tmp_path / "rules" / "community-seen.json").unlink()
    with pytest.raises(ReleaseRefused, match=r"community-seen\.json.*not in the checkout"):
        release.read_community(tmp_path / "rules", catalog_built_from(digest))


@pytest.mark.parametrize(
    "document",
    [{"extra": 1}, {"reports": [{**COMMUNITY_REPORT, "note": "Zorblax Sentinel"}]}, {"reports": [{**COMMUNITY_REPORT, "date": "2999-01-01"}]}, {"retracted": [{**COMMUNITY_RETRACTION, "issue": 5}]}],
    ids=["a field that is not allowed", "free text in a report", "a day after today", "an issue in both lists"],
)
def test_a_file_that_is_not_of_the_form_refuses_the_release_without_repeating_it(tmp_path, document):
    digest = community_file(tmp_path / "rules", **document)
    with pytest.raises(ReleaseRefused, match=r"community-seen\.json") as raised:
        release.read_community(tmp_path / "rules", catalog_built_from(digest))
    assert "zorblax" not in str(raised.value).lower() and "\n" not in str(raised.value)


def test_a_file_of_the_old_form_refuses_the_release_with_the_line_that_says_how_to_convert_it(tmp_path):
    (tmp_path / "rules").mkdir()
    text = json.dumps({"version": "2026-10-14", "reports": [{"key": "w9004", "issue": "https://example.invalid/issues/1"}]})
    (tmp_path / "rules" / "community-seen.json").write_text(text, encoding="utf-8")
    with pytest.raises(ReleaseRefused, match="old form.*convert"):
        release.read_community(tmp_path / "rules", catalog_built_from(hashlib.sha256(text.encode("utf-8")).hexdigest()))


def test_release_json_says_that_a_checkout_with_no_file_has_no_entries(world, tmp_path):
    _, result, _ = build(world, tmp_path)
    with tarfile.open(result.asset, "r:gz") as archive:
        inside = json.loads(archive.extractfile("release.json").read())
    assert inside["community"] == {"reports": [], "retracted": []}


def finished(spec):
    """A stand-in for the solving: the results of the world are whole, and the build only has to find them (a change of the catalog's provenance would make the chunks again)."""
    return release.TrioOutcome(slug=spec.slug, status="resumed", chunks=CHUNKS, scenarios=CHUNKS * 2)


def test_release_json_records_the_entries_of_the_committed_file_that_the_catalog_was_built_from(world, tmp_path, monkeypatch):
    copy = clone(world, tmp_path)
    digest = community_file(copy.root / "rules")
    catalog = json.loads(copy.catalog.read_text(encoding="utf-8"))
    catalog["provenance"] = catalog_built_from(digest)["provenance"]
    copy.catalog.write_text(json.dumps(catalog), encoding="utf-8")
    # (the bundles of the world were made from the catalog as it was: their hash of the inputs says so, and these two checks would make the trios again)
    monkeypatch.setattr(release, "check_bundles", lambda *args, **kwargs: None)
    monkeypatch.setattr(release, "check_pruning", lambda *args, **kwargs: [])
    _, result, _ = build(world, tmp_path, runner=finished)
    with tarfile.open(result.asset, "r:gz") as archive:
        inside = json.loads(archive.extractfile("release.json").read())
    assert inside["community"] == {"reports": [COMMUNITY_REPORT], "retracted": [COMMUNITY_RETRACTION]}
    assert list(inside)[list(inside).index("evidence") + 1] == "community"
    pointer = (copy.root / "releases" / f"{TAG}.json").read_text(encoding="utf-8")
    assert "community" not in pointer and "w9004" not in pointer  # (the pointer is what git keeps: no entry)


def test_a_catalog_not_built_from_the_file_of_the_checkout_refuses_the_build_before_any_hour_is_spent(world, tmp_path):
    copy = clone(world, tmp_path)
    community_file(copy.root / "rules")  # (the catalog of the world knows no file)
    calls: list[str] = []

    def spy(spec):
        calls.append(spec.slug)
        return finished(spec)

    with pytest.raises(ReleaseRefused, match=r"community-seen\.json"):
        build(world, tmp_path, runner=spy)
    assert calls == []
    nothing_left(copy.root)


def test_a_release_built_in_a_worktree_of_its_own_reads_the_stamps_of_the_checks_folder_and_not_the_build_folder_of_that_worktree(world, tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
    fresh = (now - timedelta(days=2)).isoformat().replace("+00:00", "Z") + "\n"
    stamps = tmp_path / "stamps"  # (the folder of the checks, which are run from another checkout)
    monkeypatch.setenv("TRIOFORGE_CHECKS_DIR", str(stamps))
    stamps.mkdir()
    for name in release.SCHEDULED_CHECKS:
        (stamps / f"{name}.last-run").write_text(fresh, encoding="utf-8")
    _, result, _ = build(world, tmp_path, now=now)
    assert not [warning for warning in result.warnings if "scheduled check" in warning], result.warnings  # (the worktree has no stamp of its own, and none is wanted)
    # the other way: no stamp in the folder, and fresh ones in the worktree's own build/checks (where the checks left them before): they do not count
    for stamp in stamps.iterdir():
        stamp.unlink()
    other = clone(world, tmp_path, "other")
    (other.root / "build" / "checks").mkdir(parents=True, exist_ok=True)
    for name in release.SCHEDULED_CHECKS:
        (other.root / "build" / "checks" / f"{name}.last-run").write_text(fresh, encoding="utf-8")
    _, result, _ = build(world, tmp_path, name="other", now=now)
    warned = [warning for warning in result.warnings if "scheduled check" in warning]
    assert len(warned) == len(release.SCHEDULED_CHECKS) and all(any(name in warning for warning in warned) for name in release.SCHEDULED_CHECKS)


def test_a_folder_of_the_checks_that_is_not_absolute_refuses_the_build_before_anything_is_made(world, tmp_path, monkeypatch):
    monkeypatch.setenv("TRIOFORGE_CHECKS_DIR", "relative/folder")
    with pytest.raises(ReleaseRefused, match="TRIOFORGE_CHECKS_DIR must be an absolute path"):
        build(world, tmp_path)
    nothing_left(world_at(tmp_path / "w").root)


def test_what_the_asset_holds(world, tmp_path):
    copy, result, _ = build(world, tmp_path)
    with tarfile.open(result.asset, "r:gz") as archive:
        names = archive.getnames()
        inside = json.loads(archive.extractfile("release.json").read())
        text = {name: archive.extractfile(name).read().decode("utf-8") for name in names}
    assert names == sorted(names) and "release.json" in names and "items.json" in names
    assert all(assemble.is_release_file(name) for name in names)
    assert not [n for n in names if "chunk" in n or "seen" in n or "catalog" in n or n.endswith(".tmp")]
    assert inside["trios"] == {slug: [0, 4, 10] for slug in sorted(TRIOS)} and inside["trial"] is False and inside["release"] == TAG
    assert inside["catalog_date"] == "2030-01-02" and inside["catalog_sha256"] == hashlib.sha256(copy.catalog.read_bytes()).hexdigest()
    assert inside["code_hash"] == assemble.code_hash() and inside["level"] == 50 and inside["rules_version"]
    assert inside["evidence"]["w9014"] == "wiki" and inside["evidence"]["w9004"] == "wiki" and inside["rules"]["level.current"]["value"] == 50
    assert "strict" not in set(inside["evidence"].values())  # (wiki is the one evidence level of a release)
    assert inside["solver"]["canonical"] is True and "highs" in inside["solver"]
    assert all("fingerprint" not in body.lower() and "seen-in-game" not in body for body in text.values())


def test_the_evidence_map_is_in_the_asset_and_never_in_the_pointer_or_the_report(world, tmp_path):
    copy, result, _ = build(world, tmp_path)
    pointer = (copy.root / "releases" / f"{TAG}.json").read_text(encoding="utf-8")
    assert "evidence" not in pointer and "w9014" not in pointer and TRIOS[0] not in pointer
    assert list(assemble.read_pointer(copy.root / "releases" / f"{TAG}.json")) == list(assemble.POINTER_KEYS)


def test_no_chunk_fingerprint_reaches_a_published_file_or_the_screen(world, tmp_path):
    copy, result, lines = build(world, tmp_path)
    fingerprints = {json.loads(p.read_text(encoding="utf-8"))["fingerprint"] for p in (copy.results / TRIOS[0] / "chunks").glob("s-*.json")}
    published = [result.asset.read_bytes()]
    with tarfile.open(result.asset, "r:gz") as archive:
        published += [archive.extractfile(m).read() for m in archive.getmembers()]
    published += [p.read_bytes() for p in (copy.root / "releases").glob("*")] + [p.read_bytes() for p in (copy.root / "reports").glob("*")]
    published.append("\n".join(lines).encode("utf-8"))
    assert fingerprints
    for blob in published:
        for secret in fingerprints:
            assert secret.encode() not in blob
    assert "seen-in-game" not in "\n".join(lines)


def test_a_second_release_is_compared_with_the_first_and_with_nothing_changed_has_nothing_to_report(world, tmp_path):
    copy, first, _ = build(world, tmp_path, tag="data-2026-10-10")
    _, second, lines = build(world, tmp_path, tag="data-2026-10-17")
    assert second.previous == "data-2026-10-10" and second.changes == 0 and second.solver_diffs == 0
    report = json.loads((copy.root / "build" / "reports" / "results-diff-data-2026-10-17.json").read_text(encoding="utf-8"))
    assert report["previous"] == "data-2026-10-10" and report["changes"] == []
    assert "no change" in (copy.root / "reports" / "results-diff-data-2026-10-17.md").read_text(encoding="utf-8").lower()
    assert first.asset_sha256 != second.asset_sha256  # (the snapshot id is new for each release)


def test_a_first_release_has_a_report_that_says_so(world, tmp_path):
    copy, result, _ = build(world, tmp_path)
    assert result.previous is None
    assert "first release" in (copy.root / "reports" / f"results-diff-{TAG}.md").read_text(encoding="utf-8").lower()


def test_a_build_after_an_interruption_resumes_from_the_finished_trios_and_chunks(world, tmp_path):
    copy = clone(world, tmp_path)
    folder = copy.results / TRIOS[1]
    for path in list(folder.iterdir()):  # as after a kill between the last chunk and the result files: chunks only
        if path.name != "chunks":
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    (folder / "chunks" / release.MARKER).unlink()
    _, result, lines = build(world, tmp_path)
    by_slug = {o.slug: o for o in result.outcomes}
    assert by_slug[TRIOS[0]].status == "resumed" and by_slug[TRIOS[1]].status == "done" and by_slug[TRIOS[1]].reused == CHUNKS and by_slug[TRIOS[1]].solved == 0
    assert any("resumed" in line for line in lines)


def test_a_trial_build_of_some_trios_writes_no_pointer_and_says_so(world, tmp_path):
    copy, result, lines = build(world, tmp_path, trios=[TRIOS[0]], trial=True)
    assert result.trial is True and result.pointer is None and files_under(copy.root / "releases") == []
    assert files_under(copy.root / "reports") == []  # (a trial's reports are in build/trial: see below)
    with tarfile.open(result.asset, "r:gz") as archive:
        assert json.loads(archive.extractfile("release.json").read())["trial"] is True
    assert any("trial" in line.lower() and "no pointer" in line.lower() for line in lines)


def test_the_default_grid_is_the_560_trios_and_a_trio_that_is_not_there_is_refused(world, tmp_path):
    copy = clone(world, tmp_path)

    def quick(spec):  # a stand-in for the hours of solving: every trio is "done", and the files are those of the two that exist
        return release.TrioOutcome(slug=spec.slug, status="done", chunks=CHUNKS, scenarios=CHUNKS * 2)

    with pytest.raises(ReleaseRefused, match=r"558 trios"):
        release.build_release(
            tag=TAG, root=copy.root, privacy_key=copy.key, processes=1, say=lambda m: None, runner=quick, git=FakeGit(), bundle_reader=no_check, assets=ASSETS,
            parity_runner=pass_parity,
        )
    nothing_left(copy.root)


def test_the_search_console_name_given_to_the_release_build_is_counted_in_the_exact_files_of_its_site(world, tmp_path, monkeypatch):
    """The option of release-build.py (--google-verification, else $TRIOFORGE_GOOGLE_VERIFICATION, as the site build takes it) reaches the exact count: one file more at the root, and the same count as the
    build's own list of files with that name in it."""
    seen = []
    real = release.check_file_count

    def spy(*args, **kwargs):
        count = real(*args, **kwargs)
        seen.append((kwargs.get("verification"), count))
        return count

    monkeypatch.setattr(release, "check_file_count", spy)
    name = "google0123456789abcdef.html"  # (invented)
    _copy, plain, _lines = build(world, tmp_path, name="plain")
    _copy, named, _lines = build(world, tmp_path, name="named", verification=name)
    assert [verification for verification, _count in seen] == [None, name]
    assert named.site_files == plain.site_files + 1 == seen[1][1]
    monkeypatch.setenv("TRIOFORGE_GOOGLE_VERIFICATION", name)
    _copy, from_environment, _lines = build(world, tmp_path, name="environment")
    assert from_environment.site_files == plain.site_files + 1, "no option: the environment, as the site build does"


@pytest.mark.parametrize("check", ["check_grid", "check_invariants", "check_bundles", "check_pruning", "check_file_count", "privacy_gate"])
def test_a_check_that_refuses_stops_the_build_before_packing_and_leaves_nothing(world, tmp_path, monkeypatch, check):
    def refuse(*args, **kwargs):
        raise ReleaseRefused(f"injected fault in {check}")

    monkeypatch.setattr(release, check, refuse)
    with pytest.raises(ReleaseRefused, match=f"injected fault in {check}"):
        build(world, tmp_path)
    nothing_left(tmp_path / "w")


def test_the_bundle_reader_and_the_parity_suite_are_checks_too(world, tmp_path):
    def reader(*args, **kwargs):
        raise ReleaseRefused("the browser's reader refused a bundle")

    with pytest.raises(ReleaseRefused, match="reader refused"):
        build(world, tmp_path, bundle_reader=reader)
    nothing_left(tmp_path / "w")
    with pytest.raises(ReleaseRefused, match="parity suite"):
        build(world, tmp_path, name="w2", parity_runner=lambda folder, sample, files: (1, "FAIL shard-parity\n"))
    nothing_left(tmp_path / "w2")


def test_a_trio_that_goes_missing_is_refused_and_nothing_is_packed(world, tmp_path):
    def loses_one(spec):
        outcome = release.run_trio(spec)
        if spec.slug == TRIOS[1]:
            shutil.rmtree(Path(spec.results) / spec.slug)
        return outcome

    with pytest.raises(ReleaseRefused, match=TRIOS[1]):
        build(world, tmp_path, runner=loses_one)
    nothing_left(tmp_path / "w")


def test_a_partial_trio_and_a_trio_at_the_wrong_scope_stop_the_build(world, tmp_path):
    def partial(spec):
        if spec.slug == TRIOS[0]:
            spec = release.TrioSpec(**{**asdict(spec), "narrow": {"races": ["OGR"]}})
        return release.run_trio(spec)

    def wrong_scope(spec):
        if spec.slug == TRIOS[0]:
            spec = release.TrioSpec(**{**asdict(spec), "tiers": (0, 4)})
        return release.run_trio(spec)

    with pytest.raises(ReleaseRefused, match=rf"{TRIOS[0]}.*partial"):
        build(world, tmp_path, name="a", runner=partial)
    nothing_left(tmp_path / "a")
    with pytest.raises(ReleaseRefused, match=rf"{TRIOS[0]}.*needs \+0, \+4, \+10"):
        build(world, tmp_path, name="b", runner=wrong_scope)
    nothing_left(tmp_path / "b")


def test_a_failed_trio_stops_the_build_and_is_named(world, tmp_path):
    def fails(spec):
        if spec.slug == TRIOS[1]:
            return release.TrioOutcome(slug=spec.slug, status="failed", error="ExactnessError: the value of the kit differs")
        return release.run_trio(spec)

    with pytest.raises(ReleaseRefused, match=rf"{TRIOS[1]}.*ExactnessError"):
        build(world, tmp_path, runner=fails)
    nothing_left(tmp_path / "w")


def test_a_name_of_the_denylist_in_the_release_stops_the_build_at_the_scan(world, tmp_path):
    def plants(spec):
        outcome = release.run_trio(spec)
        if spec.slug == TRIOS[0]:
            edit(Path(spec.results) / spec.slug / "defaults.json", lambda d: d.update(flip_notes=["the Zorblax cap"]))
        return outcome

    with pytest.raises(ReleaseRefused, match=r"privacy scan.*1 finding") as raised:
        build(world, tmp_path, runner=plants)
    assert "zorblax" not in str(raised.value).lower()
    nothing_left(tmp_path / "w")


def test_the_build_is_refused_up_front_for_a_bad_tag_a_spent_tag_and_a_missing_input(world, tmp_path):
    copy = clone(world, tmp_path)
    calls: list[str] = []

    def spy(spec):
        calls.append(spec.slug)
        return release.run_trio(spec)

    with pytest.raises(ReleaseRefused, match="tag"):
        build(world, tmp_path, tag="data-2026-10-17\n", runner=spy)
    (copy.root / "releases" / f"{TAG}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ReleaseRefused, match="already"):
        build(world, tmp_path, runner=spy)
    (copy.root / "releases" / f"{TAG}.json").unlink()
    report = copy.root / "reports" / f"results-diff-{TAG}.md"
    report.write_text("x", encoding="utf-8")
    tracking = FakeGit()
    tracking.tracked_paths.add(report)  # (a report that is tracked by git is not the build's to remove; one that is not tracked, with no pointer, is cleared)
    with pytest.raises(ReleaseRefused, match="already"):
        build(world, tmp_path, runner=spy, git=tracking)
    report.unlink()
    copy.key.unlink()
    with pytest.raises(ReleaseRefused, match="key"):
        build(world, tmp_path, runner=spy)
    assert calls == []  # nothing was solved for any of them: the hours are not spent on an input that was bad from the start


def test_a_bundle_and_an_item_table_made_from_other_inputs_are_refused(world, tmp_path):
    folder = shipped(world, tmp_path)
    edit(folder / TRIOS[0] / "engine-l50.json", lambda b: b.update(inputs="00" * 32))
    with pytest.raises(ReleaseRefused, match=rf"{TRIOS[0]}.*same inputs"):
        release.check_bundles(folder, TRIOS, catalog=world.catalog, tables_root=world.root)


def test_a_marker_that_is_not_whole_is_no_marker_and_the_trio_is_run_from_its_chunks(world, tmp_path):
    copy = clone(world, tmp_path)
    marker = copy.results / TRIOS[0] / "chunks" / release.MARKER
    for broken in ("{", "[]", json.dumps({"format": 1}), json.dumps({**json.loads(marker.read_text(encoding="utf-8")), "outcome": {"chunks": CHUNKS}})):
        marker.write_text(broken, encoding="utf-8")
        outcome = release.run_trio(spec_for(copy, TRIOS[0]))
        assert outcome.status == "done" and outcome.reused == CHUNKS and outcome.solved == 0, broken
    assert release.run_trio(spec_for(copy, TRIOS[0])).status == "resumed"


def test_a_new_game_patch_makes_the_files_again_from_the_chunks(world, tmp_path):
    """The patch date is in the headers of every file but not in the fingerprint of the chunks: a finished trio must not be taken as it is."""
    copy = clone(world, tmp_path)
    path = copy.root / "derived" / "client" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for entry in manifest["inputs"]:
        entry["date"] = "2030-02-03"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    outcome = release.run_trio(spec_for(copy, TRIOS[0]))
    assert outcome.status == "done" and outcome.reused == CHUNKS and outcome.solved == 0
    assert json.loads((copy.results / TRIOS[0] / "wiki-own.json").read_text(encoding="utf-8"))["game_patch"] == "2030-02-03"


def test_a_trial_is_not_compared_with_a_release_unless_it_is_asked_to_be(world, tmp_path):
    build(world, tmp_path, tag="data-2026-10-10")
    _, trial, _ = build(world, tmp_path, tag="data-2026-10-17", trios=[TRIOS[0]], trial=True)
    assert trial.previous is None


# ---- the code that writes the files -----------------------------------------------------------------------------------------------------------


def test_a_changed_writer_makes_the_files_again_from_the_chunks_and_solves_nothing(world, tmp_path, monkeypatch):
    """After a fix to the code that writes defaults.json a finished trio must not keep the old file: its files are written again, from the chunks it has."""
    copy = clone(world, tmp_path)
    real = shards.defaults_doc
    monkeypatch.setattr(shards, "defaults_doc", lambda *args, **kwargs: {**real(*args, **kwargs), "fixed_by": "the new writer"})
    change_sources(monkeypatch, "precompute/shards.py")
    before = chunk_files(copy, TRIOS[0])
    outcome = release.run_trio(spec_for(copy, TRIOS[0]))
    assert outcome.status == "done" and outcome.chunks == outcome.reused == CHUNKS and outcome.solved == 0 and outcome.redone == 0
    assert load(copy.results / TRIOS[0] / "defaults.json")["fixed_by"] == "the new writer"
    assert chunk_files(copy, TRIOS[0]) == before  # not a chunk was written
    assert load(copy.results / TRIOS[0] / "chunks" / release.MARKER)["writer"] == assemble.writer_hash()
    assert release.run_trio(spec_for(copy, TRIOS[0])).status == "resumed"  # and with the same writer code the trio is left alone again


@pytest.mark.parametrize("name", ["precompute/__init__.py", "precompute/seals.py", "precompute/engine.py", "export/browser.py", "data/jsonio.py", "scope.py"])
def test_a_change_in_any_file_that_writes_a_trio_is_seen_by_a_finished_trio(world, tmp_path, monkeypatch, name):
    copy = clone(world, tmp_path)
    change_sources(monkeypatch, name)
    outcome = release.run_trio(spec_for(copy, TRIOS[0]))
    assert outcome.status == "done" and outcome.reused == CHUNKS and outcome.solved == 0


def test_the_marker_holds_the_hash_of_the_writer_code(world):
    marker = load(world.results / TRIOS[0] / "chunks" / release.MARKER)
    assert marker["writer"] == assemble.writer_hash() and re.fullmatch(r"[0-9a-f]{64}", marker["writer"])


def test_a_marker_from_before_the_writers_were_hashed_is_no_marker(world, tmp_path):
    copy = clone(world, tmp_path)
    path = copy.results / TRIOS[0] / "chunks" / release.MARKER
    marker = load(path)
    del marker["writer"]
    path.write_text(json.dumps(marker), encoding="utf-8")
    outcome = release.run_trio(spec_for(copy, TRIOS[0]))
    assert outcome.status == "done" and outcome.reused == CHUNKS and outcome.solved == 0


def test_the_release_json_carries_the_code_hash_that_covers_the_writers(world, tmp_path, monkeypatch):
    change_sources(monkeypatch, "precompute/shards.py")
    changed = assemble.code_hash()
    monkeypatch.undo()
    assert changed != assemble.code_hash()
    _, result, _ = build(world, tmp_path)
    with tarfile.open(result.asset, "r:gz") as archive:
        assert json.loads(archive.extractfile("release.json").read())["code_hash"] == assemble.code_hash()
    assert assemble.read_pointer(result.pointer)["code_hash"] == assemble.code_hash()


# ---- what is committed names no item whose evidence changed ------------------------------------------------------------------------------------


def results_diff_json(root: Path, tag: str = TAG) -> dict:
    return json.loads((root / "build" / "reports" / f"results-diff-{tag}.json").read_text(encoding="utf-8"))


def test_the_full_diff_stays_in_the_build_folder_and_only_the_markdown_goes_to_reports(world, tmp_path):
    copy, result, _ = build(world, tmp_path)
    assert files_under(copy.root / "reports") == [f"results-diff-{TAG}.md"]
    assert results_diff_json(copy.root)["release"] == TAG
    assert result.reports == (copy.root / "reports" / f"results-diff-{TAG}.md", copy.root / "build" / "reports" / f"results-diff-{TAG}.json")


def test_no_text_that_is_committed_names_an_item_whose_evidence_changed(world, tmp_path):
    """The full diff, which stays in build/, names the items whose evidence moved (here the wiki goes back on two of them); what git keeps says how many, never which."""
    copy, _, _ = build(world, tmp_path, tag="data-2026-10-10")
    document = json.loads(copy.catalog.read_text(encoding="utf-8"))
    for item in document["items"]:
        if item["key"] in {"w9004", "w9005"}:
            item["evidence"]["level"] = "disputed"
    copy.catalog.write_text(json.dumps(document), encoding="utf-8")
    _, second, _ = build(world, tmp_path, tag="data-2026-10-17")
    full = results_diff_json(copy.root, "data-2026-10-17")
    changed = {change["key"] for change in full["changes"] if change["kind"] == "item" and change.get("evidence")}
    assert {"w9004", "w9005"} <= changed and second.changes > 0  # (the diff saw them: the JSON for the maintainer says which)
    committed = [*(copy.root / "reports").glob("*"), *(copy.root / "releases").glob("*")]
    assert committed
    for path in committed:
        text = path.read_text(encoding="utf-8")
        assert not any(key in text for key in changed), path.name


# ---- a path of this computer in what is published -----------------------------------------------------------------------------------------------


def test_a_previous_release_whose_asset_is_gone_is_warned_at_the_start_and_leaves_no_path_in_the_reports(world, tmp_path):
    copy, first, _ = build(world, tmp_path, tag="data-2026-10-10")
    first.asset.unlink()  # the pointer stays in releases/, the asset is not in the build folder
    elsewhere = tmp_path / "tf-build"  # a build folder the rule of the keyed scan against build paths knows nothing of
    shutil.copytree(copy.root / "build", elsewhere)
    _, second, lines = build(world, tmp_path, tag="data-2026-10-17", build_dir=elsewhere)
    assert second.previous is None and any("data-2026-10-10" in warning for warning in second.warnings)
    asked = [n for n, line in enumerate(lines) if "data-2026-10-10" in line and "warning" in line.lower()]
    started = [n for n, line in enumerate(lines) if line.startswith(("catalog", "trios", "precompute"))]
    assert asked and started and asked[0] < started[0]  # said at the start, where it is already known
    said = "\n".join(line for line in lines if line.startswith("warning"))
    texts = [(copy.root / "reports" / "results-diff-data-2026-10-17.md").read_text(encoding="utf-8"), said, "\n".join(second.warnings)]
    texts.append((elsewhere / "reports" / "results-diff-data-2026-10-17.json").read_text(encoding="utf-8"))
    for text in texts:  # (the screen names the asset where it is: that is for the maintainer; what is published, and what is said as a warning, names no place)
        assert str(tmp_path) not in text and str(tmp_path).replace("\\", "/") not in text and not re.search(r"[A-Za-z]:[\\/]", text)
    assert "data-2026-10-10" in texts[0]


def test_a_path_in_a_published_text_stops_the_build_before_the_keyed_scan(world, tmp_path, monkeypatch):
    def plants(spec):
        outcome = release.run_trio(spec)
        if spec.slug == TRIOS[0]:
            edit(Path(spec.results) / spec.slug / "defaults.json", lambda d: d.update(flip_notes=["made at D:\\tf-build\\results"]))
        return outcome

    scanned = []
    real = release.PrivacyScanner.scan
    monkeypatch.setattr(release.PrivacyScanner, "scan", lambda self, *args, **kwargs: (scanned.append(1), real(self, *args, **kwargs))[1])
    with pytest.raises(ReleaseRefused, match=rf"absolute path.*{TRIOS[0]}/defaults\.json"):
        build(world, tmp_path, runner=plants)
    assert scanned == []
    nothing_left(tmp_path / "w")


# ---- what a hard kill leaves behind ------------------------------------------------------------------------------------------------------------


def test_what_a_hard_kill_leaves_in_the_build_folder_does_not_block_the_next_build(world, tmp_path):
    copy = clone(world, tmp_path)
    folder = copy.root / "build" / "release"
    (folder / f"{TAG}.stage" / TRIOS[0]).mkdir(parents=True)
    (folder / f"{TAG}.stage" / TRIOS[0] / "wiki-own.json").write_text("{}", encoding="utf-8")
    (folder / f"{TAG}.bundles").mkdir()
    (folder / f"{TAG}.bundles" / "half.json").write_text("{", encoding="utf-8")
    (folder / f"{TAG}.tar.gz.tmp").write_bytes(b"half an asset")
    other = folder / "data-2026-10-03.stage"
    other.mkdir()
    (other / "keep.txt").write_text("not of this tag", encoding="utf-8")
    (folder / "notes.txt").write_text("not ours", encoding="utf-8")
    _, result, _ = build(world, tmp_path)
    assert result.asset.is_file()
    assert sorted(p.name for p in folder.iterdir()) == sorted([f"{TAG}.tar.gz", "data-2026-10-03.stage", "notes.txt"])  # only those, by exact name
    assert (other / "keep.txt").read_text(encoding="utf-8") == "not of this tag"


def test_the_scratch_folder_of_the_bundle_check_has_the_name_of_the_tag_and_goes_when_the_check_is_done(world, tmp_path, monkeypatch):
    seen_names = []
    real = release.check_bundles

    def spy(folder, trios, **kwargs):
        seen_names.append(kwargs.get("scratch"))
        return real(folder, trios, **kwargs)

    monkeypatch.setattr(release, "check_bundles", spy)
    copy, _, _ = build(world, tmp_path)
    assert seen_names == [copy.root / "build" / "release" / f"{TAG}.bundles"] and not seen_names[0].exists()


def test_a_scratch_folder_the_bundle_check_is_given_is_made_empty_first_and_removed_after(world, tmp_path):
    folder = shipped(world, tmp_path)
    scratch = tmp_path / "scratch.bundles"  # (beside the release folder, and named for a bundle check: the only kind of folder that is made empty)
    scratch.mkdir()
    (scratch / "left-from-a-kill.json").write_text("{", encoding="utf-8")
    release.check_bundles(folder, TRIOS, catalog=world.catalog, tables_root=world.root, scratch=scratch)
    assert not scratch.exists()


# ---- a trial ------------------------------------------------------------------------------------------------------------------------------------


def test_a_trial_writes_under_build_trial_and_nothing_in_reports_or_releases_and_uses_up_no_tag(world, tmp_path):
    copy, result, lines = build(world, tmp_path, trios=[TRIOS[0]], trial=True)
    folder = copy.root / "build" / "trial"
    assert files_under(copy.root / "reports") == [] and files_under(copy.root / "releases") == []
    assert sorted(p.name for p in folder.iterdir()) == [f"{TAG}.results-diff.json", f"{TAG}.results-diff.md", f"{TAG}.tar.gz"]
    assert not (copy.root / "build" / "release").exists() or list((copy.root / "build" / "release").iterdir()) == []
    assert result.asset == folder / f"{TAG}.tar.gz" and result.pointer is None and result.reports == (folder / f"{TAG}.results-diff.md", folder / f"{TAG}.results-diff.json")
    assert (folder / f"{TAG}.results-diff.md").read_text(encoding="utf-8").splitlines()[0].startswith("# TRIAL")
    assert json.loads((folder / f"{TAG}.results-diff.json").read_text(encoding="utf-8"))["trial"] is True
    build(world, tmp_path, trios=[TRIOS[0]], trial=True)  # a second trial of the same tag is no trouble: it replaces the first
    _, real, _ = build(world, tmp_path)  # and the tag is not used up
    assert real.pointer is not None and real.pointer.is_file() and files_under(copy.root / "reports") == [f"results-diff-{TAG}.md"]


def test_a_trial_is_headed_trial_on_the_screen_too(world, tmp_path):
    _, _, lines = build(world, tmp_path, trios=[TRIOS[0]], trial=True)
    assert any("TRIAL" in line for line in lines)


# ---- a release is the whole grid ----------------------------------------------------------------------------------------------------------------------


def test_some_trios_are_a_release_only_if_they_are_the_grid_and_otherwise_a_trial(world, tmp_path):
    calls = []

    def spy(spec):
        calls.append(spec.slug)
        return release.run_trio(spec)

    with pytest.raises(ReleaseRefused, match=r"whole grid|trial") as raised:
        build(world, tmp_path, trios=[TRIOS[0]], trial=False, runner=spy)
    assert "2 trios" in str(raised.value) or "1 of" in str(raised.value) or TRIOS[1] in str(raised.value)
    assert calls == []  # up front: no hour is spent for a build that could not be a release
    nothing_left(tmp_path / "w")
    _, result, _ = build(world, tmp_path, trios=list(reversed(TRIOS)), trial=False)  # the same trios in another order are the grid
    assert result.pointer is not None


# ---- the sample of the parity suite -------------------------------------------------------------------------------------------------------------


def test_the_parity_sample_is_drawn_from_the_snapshot_id_bounded_and_recorded_in_release_json(world, tmp_path):
    seen = []

    def recording(folder, sample, files):
        seen.append(sample)
        return 0, "ok\n"

    copy, result, lines = build(world, tmp_path, parity_runner=recording)
    with tarfile.open(result.asset, "r:gz") as archive:
        document = json.loads(archive.extractfile("release.json").read())
    limit = CHUNKS // release.PARITY_MIN_CHUNKS  # (the trios of the world have CHUNKS chunks each)
    assert seen == [document["parity_sample"]] == [release.parity_sample(document["snapshot_id"], limit)]
    assert document["parity_sample"].endswith(f"/{limit}")
    assert any("parity" in line and document["parity_sample"] in line for line in lines)


def test_a_stride_that_leaves_a_trio_with_too_few_chunks_is_refused_before_any_check_and_a_stride_that_is_no_number_before_the_hours(world, tmp_path):
    with pytest.raises(ReleaseRefused, match=r"stride") as raised:
        build(world, tmp_path, parity_stride=CHUNKS + 7)
    assert str(CHUNKS + 7) in str(raised.value) and str(CHUNKS) in str(raised.value)  # (what is allowed: the smallest trio has CHUNKS chunks)
    nothing_left(tmp_path / "w")
    calls = []
    for bad in (0, -2, 2.5, "7"):
        with pytest.raises(ReleaseRefused, match="stride"):
            build(world, tmp_path, parity_stride=bad, runner=lambda spec: calls.append(spec.slug))
    assert calls == []  # (the hours are not spent on a stride that was no number from the start)


def test_a_smaller_stride_is_a_bigger_sample_and_is_allowed(world, tmp_path):
    seen = []
    _, result, _ = build(world, tmp_path, parity_stride=3, parity_runner=lambda folder, sample, files: (seen.append(sample), (0, "ok\n"))[1])
    assert seen[0].endswith("/3") and int(seen[0].split("/")[0]) < 3


def test_a_stride_no_trio_could_allow_is_refused_before_the_hours_and_one_the_smallest_trio_cannot_allow_after_them(world, tmp_path):
    calls = []
    for gross in (999_999, 1_000):  # more than any trio has chunks: no release could be held to that sample
        with pytest.raises(ReleaseRefused, match=r"stride.*(at most|largest|ceiling)") as raised:
            build(world, tmp_path, parity_stride=gross, runner=lambda spec: calls.append(spec.slug))
        assert str(gross) in str(raised.value)
    assert calls == []
    nothing_left(tmp_path / "w")
    with pytest.raises(ReleaseRefused, match=r"stride") as raised:  # fewer than the ceiling, more than the smallest trio (CHUNKS chunks) allows
        build(world, tmp_path, parity_stride=100)
    assert "100" in str(raised.value) and str(CHUNKS) in str(raised.value)
    nothing_left(tmp_path / "w")


# ---- the code is hashed once, at the start ----------------------------------------------------------------------------------------------------------
#
# A worker runs the code it imported, and a module it imports later is read from the disk as it is then: a merge into the checkout in the middle of the hours
# would make chunks under a hash of code that did not make them. The parent hashes the code once, before the pool starts, every worker uses those values, and the
# build is refused if the files are not what they were when it ends.


def test_the_inputs_are_loaded_with_the_hash_of_the_code_they_are_given_and_with_the_hash_of_the_disk_when_none_is(world):
    from trioforge.precompute import grid

    codes = grid.parse_trio(TRIOS[0])
    args = dict(catalog_path=world.catalog, tables_root=world.root)
    disk, _ = grid.load_inputs(codes, **args)
    same, _ = grid.load_inputs(codes, code_hash=grid._code_hash(), **args)
    other, _ = grid.load_inputs(codes, code_hash="11" * 32, **args)
    assert same.fingerprint == disk.fingerprint and other.fingerprint != disk.fingerprint
    for bad in ("", "11" * 31, "XY" * 32, 5):
        with pytest.raises(ValueError, match="code hash"):
            grid.load_inputs(codes, code_hash=bad, **args)


def test_a_run_takes_the_hash_of_the_chunks_from_its_caller(world, tmp_path):
    scratch = make_world(tmp_path / "scratch")
    release.run_trio(release.TrioSpec(**{**asdict(spec_for(scratch, TRIOS[0], limit=2)), "chunk_code": "11" * 32}))
    (first, *_) = sorted((scratch.results / TRIOS[0] / "chunks").glob("s-*.json"))
    from trioforge.precompute import grid

    expected, _ = grid.load_inputs(grid.parse_trio(TRIOS[0]), catalog_path=scratch.catalog, tables_root=scratch.root, code_hash="11" * 32)
    assert load(first)["fingerprint"] == expected.fingerprint


def test_the_workers_of_a_pool_use_the_hashes_of_the_parent_and_never_hash_the_disk(tmp_path):
    """Processes that are spawned cannot be spied on, so the parent gives them hashes that no disk has, and the files must carry those."""
    from trioforge.precompute import grid

    scratch = make_world(tmp_path / "scratch")
    fake = ("11" * 32, "22" * 32)
    specs = [spec_for(scratch, slug) for slug in TRIOS]
    outcomes = release.precompute_grid(specs, processes=2, say=lambda message: None, hashes=fake, check_workers=False)  # (these hashes are no disk's: see the next tests)
    assert [o.status for o in outcomes] == ["done", "done"]
    expected, _ = grid.load_inputs(grid.parse_trio(TRIOS[0]), catalog_path=scratch.catalog, tables_root=scratch.root, code_hash=fake[0])
    for slug in TRIOS:
        marker = load(scratch.results / slug / "chunks" / release.MARKER)
        assert marker["writer"] == fake[1]
        assert {load(p)["fingerprint"] for p in (scratch.results / slug / "chunks").glob("s-*.json")} == {
            grid.load_inputs(grid.parse_trio(slug), catalog_path=scratch.catalog, tables_root=scratch.root, code_hash=fake[0])[0].fingerprint
        }
    assert expected.fingerprint != grid.load_inputs(grid.parse_trio(TRIOS[0]), catalog_path=scratch.catalog, tables_root=scratch.root)[0].fingerprint


def test_the_build_hashes_the_code_once_before_the_pool_and_a_worker_never_hashes_the_disk(world, tmp_path, monkeypatch):
    from trioforge.precompute import grid

    inside: list[str] = []
    calls: list[str] = []
    real_chunks, real_writers = grid._code_hash, assemble.writer_hash

    def chunk_hash():
        calls.append("chunks")
        assert not inside, "a worker hashed the code of the chunks from the disk"
        return real_chunks()

    def writer_hash():
        calls.append("writers")
        assert not inside, "a worker hashed the code that writes the files from the disk"
        return real_writers()

    monkeypatch.setattr(grid, "_code_hash", chunk_hash)
    monkeypatch.setattr(assemble, "writer_hash", writer_hash)

    def runner(spec):
        inside.append(spec.slug)
        try:
            assert spec.chunk_code == real_chunks() and spec.writer_code == real_writers()  # (what the parent hashed: the code has not changed)
            return release.run_trio(spec)
        finally:
            inside.pop()

    _, result, _ = build(world, tmp_path, runner=runner)
    # the parent hashes the code at the start, before any worker, then after the precompute and again before it packs: three times, and nobody else ever does
    # (not a worker, not the item table, not the pruning check, not the release document)
    assert calls == ["chunks", "writers"] * 3 and result.pointer is not None
    with tarfile.open(result.asset, "r:gz") as archive:
        document = json.loads(archive.extractfile("release.json").read())
    assert document["code_hash"] == assemble.combine_code_hashes(real_chunks(), real_writers())


@pytest.mark.parametrize("name", ["model/profile.py", "precompute/shards.py"], ids=["the code of the chunks", "the code that writes the files"])
def test_a_build_whose_code_changes_while_the_trios_are_made_is_refused_and_nothing_is_packed(world, tmp_path, monkeypatch, name):
    calls = []

    def changes_the_code(spec):
        calls.append(spec.slug)
        if len(calls) == 1:  # a merge into the checkout, in the middle of the hours
            change_sources(monkeypatch, name)
        return release.run_trio(spec)

    with pytest.raises(ReleaseRefused, match=r"code changed while the build ran.*again") as raised:
        build(world, tmp_path, runner=changes_the_code)
    assert "chunks" in str(raised.value) or "files" in str(raised.value)
    assert calls == list(TRIOS)  # (the build was refused after the precompute, not during it)
    nothing_left(tmp_path / "w")
    assert (tmp_path / "w" / "build" / "results" / TRIOS[0] / "chunks").is_dir()  # the chunks stay


@pytest.mark.parametrize("name", ["model/profile.py", "precompute/shards.py"], ids=["the code of the chunks", "the code that writes the files"])
def test_a_build_whose_code_changes_during_the_checks_is_refused_before_it_packs(world, tmp_path, monkeypatch, name):
    def changes_the_code(folder, sample, files):
        change_sources(monkeypatch, name)
        return 0, "ok\n"

    with pytest.raises(ReleaseRefused, match=r"code changed while the build ran.*again"):
        build(world, tmp_path, parity_runner=changes_the_code)
    nothing_left(tmp_path / "w")


def test_a_build_whose_code_did_not_change_is_not_refused_for_it(world, tmp_path):
    _, result, _ = build(world, tmp_path)
    assert result.pointer is not None and result.asset.is_file()


def test_the_parity_suite_runs_in_the_number_of_processes_asked_for_and_the_build_says_so(world, tmp_path):
    parts = []

    def recording(folder, sample, files, part=None):
        parts.append(part)
        return 0, "ok\n"

    _, _, lines = build(world, tmp_path, parity_runner=recording, parity_processes=3)
    assert sorted(part for part in parts if part) == ["0/3", "1/3", "2/3"] and parts.count(None) == 1
    assert [line for line in lines if "parity" in line and "3 processes" in line]


def test_a_number_of_parity_processes_that_is_wrong_is_refused_before_the_first_hour_is_spent(world, tmp_path):
    calls = []
    for bad in (0, -2, 1.5, True):
        with pytest.raises(ReleaseRefused, match="parity processes"):
            build(world, tmp_path, parity_processes=bad, runner=lambda spec: calls.append(spec.slug))
    assert calls == []


# ---- the chunks of a trio, as the parity suite numbers them ---------------------------------------------------------------------------------------


def test_a_bundle_of_another_level_does_not_make_the_views_of_a_trio_count_twice(world, tmp_path):
    folder = shipped(world, tmp_path)
    for slug in TRIOS:
        shutil.copyfile(folder / slug / "engine-l50.json", folder / slug / "engine-l55.json")  # a bundle of a level that no shard is of
        edit(folder / slug / "engine-l55.json", lambda bundle: bundle.update(level=55))
    facts = release.check_grid(folder, TRIOS)
    assert [f.levels for f in facts] == [(50, 55), (50, 55)]
    assert [f.chunks for f in facts] == [CHUNKS, CHUNKS]  # the views of the four shards, each counted once, at its own level
    assert release.parity_stride_limit(facts) == CHUNKS


# ---- the scratch folder of the bundle check is one the build made -------------------------------------------------------------------------------------


def test_the_scratch_folder_is_only_ever_one_named_for_a_check_beside_the_release_folder(world, tmp_path):
    folder = shipped(world, tmp_path)
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "keep.txt").write_text("keep", encoding="utf-8")
    other = tmp_path / "elsewhere"
    other.mkdir()
    for bad in (precious, tmp_path, folder, folder.parent / "precious", other / "x.bundles", folder / "x.bundles"):
        with pytest.raises(ReleaseRefused, match="scratch"):
            release.check_bundles(folder, TRIOS, catalog=world.catalog, tables_root=world.root, scratch=bad)
    assert (precious / "keep.txt").read_text(encoding="utf-8") == "keep" and folder.is_dir() and tmp_path.is_dir() and other.is_dir()


# ---- nothing but the asset is named for the tag in the release folder ----------------------------------------------------------------------------------


def test_nothing_but_the_asset_starts_with_the_tag_in_the_release_folder_and_the_full_diff_is_in_build_reports(world, tmp_path):
    copy, result, _ = build(world, tmp_path)
    folder = copy.root / "build" / "release"
    assert [p.name for p in folder.iterdir() if p.name.startswith(f"{TAG}.")] == [f"{TAG}.tar.gz"]  # (an upload of build/release/<tag>.* publishes the asset alone)
    assert result.reports[1] == copy.root / "build" / "reports" / f"results-diff-{TAG}.json" and result.reports[1].is_file()


# ---- the checkout and the inputs do not change during the build -------------------------------------------------------------------------------------
#
# check_code_unchanged covers the two code hashes. A late process pool imports release.py again, load_inputs reads the rules and the catalog again for each trio,
# and the parity suite runs JavaScript: the state of the work tree is recorded at the start (HEAD, a digest of the status, a digest of the diff) and checked again
# after the precompute and just before packing, and the rules and the catalog are read once.


@pytest.mark.parametrize("what", ["head", "status", "diff"])
def test_a_checkout_that_changes_while_the_trios_are_made_refuses_the_release(world, tmp_path, what):
    git = FakeGit()

    def runner(spec):
        setattr(git, what, "changed")  # a commit, an edit, a new file
        return release.run_trio(spec)

    with pytest.raises(ReleaseRefused, match=r"code changed while the build ran.*again") as raised:
        build(world, tmp_path, git=git, runner=runner)
    assert "checkout" in str(raised.value)
    nothing_left(tmp_path / "w")


@pytest.mark.parametrize("what", ["head", "status", "diff"])
def test_a_checkout_that_changes_during_the_checks_refuses_the_release_before_it_packs(world, tmp_path, what):
    git = FakeGit()

    def changes_the_checkout(folder, sample, files):
        setattr(git, what, "changed")
        return 0, "ok\n"

    with pytest.raises(ReleaseRefused, match=r"code changed while the build ran.*again") as raised:
        build(world, tmp_path, git=git, parity_runner=changes_the_checkout)
    assert "checkout" in str(raised.value)
    nothing_left(tmp_path / "w")


def test_the_state_of_the_checkout_is_asked_at_the_start_after_the_precompute_and_before_packing(world, tmp_path):
    git = FakeGit()
    asked: list[str] = []
    real = git.state
    git.state = lambda: (asked.append("state"), real())[1]  # type: ignore[method-assign]

    def runner(spec):
        asked.append("trio")
        return release.run_trio(spec)

    build(world, tmp_path, git=git, runner=runner)
    assert asked == ["state", "trio", "trio", "state", "state"]


def test_a_root_that_is_not_a_git_worktree_is_refused_before_anything_is_done(world, tmp_path, gitenv):
    calls: list[str] = []
    with pytest.raises(ReleaseRefused, match="git worktree"):
        build(world, tmp_path, git=None, runner=lambda spec: calls.append(spec.slug))
    assert calls == []
    nothing_left(tmp_path / "w")


def test_the_build_runs_to_the_end_in_a_real_git_worktree_and_leaves_its_state_as_it_found_it(world, tmp_path, gitenv):
    copy = clone(world, tmp_path)
    make_repo(copy.root)
    (copy.root / ".gitignore").write_text("build/\n", encoding="utf-8")
    run_git(copy.root, "add", ".gitignore")
    commit(copy.root, "the start")
    git = release.Git(copy.root)
    before = git.state()
    _, result, _ = build(world, tmp_path, git=git)
    assert result.pointer is not None and result.pointer.is_file()
    after = git.state()
    assert after[0] == before[0] and after[2] == before[2]  # (the report and the pointer are new files; nothing tracked changed)


def test_the_rules_and_the_catalog_are_read_once_at_the_start(world, tmp_path, monkeypatch):
    count: list[int] = []
    real = release._rules_snapshot
    monkeypatch.setattr(release, "_rules_snapshot", lambda root: (count.append(1), real(root))[1])
    _, result, _ = build(world, tmp_path)
    assert count == [1] and result.pointer is not None


@pytest.mark.parametrize("target", ["rules", "catalog"])
def test_rules_or_a_catalog_edited_while_the_build_runs_refuse_the_release(world, tmp_path, target):
    """The rules and the catalog are read again for each trio: release.json would record the new ones, and the results were made with the old."""
    copy = clone(world, tmp_path)
    calls: list[str] = []

    def runner(spec):
        calls.append(spec.slug)
        if len(calls) == 1:
            if target == "rules":

                def change_a_rule(document):
                    for rule in document["rules"]:
                        if rule["id"] == "packrat.pct_per_rank":  # (a rule the solver never reads: the chunks are good, the release.json would not be)
                            rule["value"] += 1

                edit(copy.root / "rules" / "rules.json", change_a_rule)
            else:
                document = json.loads(copy.catalog.read_text(encoding="utf-8"))
                document["items"][0]["stats"]["STA"] = document["items"][0]["stats"].get("STA", 0) + 1
                copy.catalog.write_text(json.dumps(document), encoding="utf-8")
        return release.run_trio(spec)

    with pytest.raises(ReleaseRefused, match=r"code changed while the build ran.*again") as raised:
        build(world, tmp_path, runner=runner)
    assert "rules" in str(raised.value) or "catalog" in str(raised.value)
    nothing_left(tmp_path / "w")


# ---- a worker that starts after a change ---------------------------------------------------------------------------------------------------------------


def test_the_modules_a_worker_imports_are_every_module_of_the_two_hashed_lists():
    from trioforge.precompute import grid

    names = release.hashed_modules()
    assert {"trioforge.model.profile", "trioforge.solver.solve", "trioforge.precompute.grid", "trioforge.rules", "trioforge.precompute", "trioforge.precompute.shards",
            "trioforge.precompute.seals", "trioforge.precompute.engine", "trioforge.export.browser", "trioforge.data.jsonio", "trioforge.scope"} <= set(names)
    assert len(names) == len(set(names)) == len(grid.code_files()) + len(assemble.writer_files())
    import importlib

    for name in names:
        importlib.import_module(name)


def test_a_worker_whose_code_is_the_code_of_the_parent_runs_its_trio(world, tmp_path, monkeypatch):
    monkeypatch.setitem(release._WORKER, "state", "unchecked")
    release._init_worker(*release._hashes())
    assert release._WORKER["state"] == "ok"
    copy = clone(world, tmp_path)
    assert release.run_trio(spec_for(copy, TRIOS[0])).status == "resumed"


@pytest.mark.parametrize("which", [0, 1], ids=["the code of the chunks", "the code that writes the files"])
def test_a_worker_whose_code_is_not_the_code_of_the_parent_refuses_its_trio(world, tmp_path, monkeypatch, which):
    monkeypatch.setitem(release._WORKER, "state", "unchecked")
    hashes = list(release._hashes())
    hashes[which] = "11" * 32  # the parent hashed other code than the disk holds: the worker started after a change
    release._init_worker(*hashes)
    assert release._WORKER["state"] == "mismatch"
    outcome = release.run_trio(spec_for(clone(world, tmp_path), TRIOS[0]))
    assert outcome.status == "failed" and "code" in outcome.error and "disk" in outcome.error


def test_the_workers_of_a_pool_that_find_other_code_than_the_parent_hashed_refuse_every_trio_and_the_build_refuses(tmp_path):
    scratch = make_world(tmp_path / "scratch")
    fake = ("11" * 32, "22" * 32)  # (no disk holds these: every worker starts after a change)
    outcomes = release.precompute_grid([spec_for(scratch, slug) for slug in TRIOS], processes=2, say=lambda message: None, hashes=fake)
    assert [o.status for o in outcomes] == ["failed", "failed"] and all("disk" in o.error for o in outcomes)
    assert not any((scratch.results / slug / "chunks" / release.MARKER).exists() for slug in TRIOS)


# ---- what a stopped or failed run leaves behind --------------------------------------------------------------------------------------------------------


def test_an_asset_with_no_pointer_is_from_a_run_that_did_not_finish_and_is_removed_at_the_start(world, tmp_path, monkeypatch):
    copy = clone(world, tmp_path)
    leftover = copy.root / "build" / "release" / f"{TAG}.tar.gz"
    leftover.parent.mkdir(parents=True, exist_ok=True)
    leftover.write_bytes(b"an asset that was renamed into place before the run was killed")

    def refuse(*args, **kwargs):
        raise ReleaseRefused("injected fault in check_grid")

    monkeypatch.setattr(release, "check_grid", refuse)
    with pytest.raises(ReleaseRefused, match="injected fault"):
        build(world, tmp_path)
    assert not leftover.exists()  # (a retry that is refused leaves nothing that looks like a release)


def test_an_untracked_report_with_no_pointer_is_removed_and_a_tracked_one_is_refused_with_its_reason(world, tmp_path):
    copy = clone(world, tmp_path)
    report = copy.root / "reports" / f"results-diff-{TAG}.md"
    report.write_text("a report of a run that was killed after it wrote it\n", encoding="utf-8")
    _, result, _ = build(world, tmp_path)
    assert result.pointer is not None and "killed" not in report.read_text(encoding="utf-8")  # (removed, and the build wrote its own)
    other = "data-2026-10-20"
    tracked = copy.root / "reports" / f"results-diff-{other}.md"
    tracked.write_text("a report that is tracked by git\n", encoding="utf-8")
    git = FakeGit()
    git.tracked_paths.add(tracked)
    with pytest.raises(ReleaseRefused, match=r"tracked by git.*no pointer") as raised:
        build(world, tmp_path, tag=other, git=git)
    assert f"results-diff-{other}.md" in str(raised.value) and tracked.read_text(encoding="utf-8") == "a report that is tracked by git\n"


def a_killed_run_of_the_tag(root: Path) -> SimpleNamespace:
    """The folders of a build and what a run of ``TAG`` that was killed left in them: the report that was written before the end, the asset that was renamed into place, and
    the temporary files of the pointer's write and of the report's write (``temporary`` is a list of the two paths)."""
    for part in ("releases", "reports", "build/release"):
        (root / part).mkdir(parents=True, exist_ok=True)
    report, asset = root / "reports" / f"results-diff-{TAG}.md", root / "build" / "release" / f"{TAG}.tar.gz"
    temporary = [root / "releases" / f".{TAG}.json.k3x9q1.tmp", root / "reports" / f".results-diff-{TAG}.md.k3x9q1.tmp"]
    for path in (report, *temporary):
        path.write_text("{}", encoding="utf-8")
    asset.write_bytes(b"an asset")
    return SimpleNamespace(report=report, asset=asset, temporary=temporary, out_dir=root / "build" / "release")


def test_a_report_that_is_tracked_by_git_is_not_removed_when_git_cannot_say_whether_it_is(tmp_path, gitenv):
    repo = make_repo(tmp_path / "repo")
    report = repo / "reports" / f"results-diff-{TAG}.md"
    report.parent.mkdir()
    report.write_text("a report that is tracked by git\n", encoding="utf-8")
    run_git(repo, "add", "reports")
    commit(repo, "a report")
    git = release.Git(repo)
    (repo / ".git" / "index").write_bytes(b"not an index")  # git can no longer answer
    with pytest.raises(ReleaseRefused, match="could not be asked whether"):
        release.clear_unfinished(repo, repo / "build" / "release", TAG, git)
    assert report.read_text(encoding="utf-8") == "a report that is tracked by git\n"


@pytest.mark.parametrize("which", [0, 1], ids=["the pointer's", "the report's"])
def test_the_temporary_file_of_a_write_that_was_cut_short_is_refused_like_the_report_when_it_is_tracked_by_git_and_nothing_is_removed(tmp_path, which):
    left = a_killed_run_of_the_tag(tmp_path / "root")
    tracked = left.temporary[which]
    git = FakeGit()
    git.tracked_paths.add(tracked)
    with pytest.raises(ReleaseRefused, match=r"tracked by git") as raised:
        release.clear_unfinished(tmp_path / "root", left.out_dir, TAG, git)
    assert f"{tracked.parent.name}/{tracked.name}" in str(raised.value)
    assert all(path.is_file() for path in (tracked, left.report, left.asset, *left.temporary))  # (a refusal removes nothing: every decision comes before the first removal)


def test_a_build_stops_at_the_start_for_a_temporary_file_that_is_tracked_by_git(world, tmp_path):
    copy = clone(world, tmp_path)
    left = a_killed_run_of_the_tag(copy.root)
    git = FakeGit()
    git.tracked_paths.add(left.temporary[0])
    calls: list[str] = []

    def spy(spec):
        calls.append(spec.slug)
        return release.run_trio(spec)

    with pytest.raises(ReleaseRefused, match=r"tracked by git"):
        build(world, tmp_path, git=git, runner=spy)
    assert calls == [] and left.temporary[0].is_file() and left.report.is_file()


def test_a_real_git_refuses_a_temporary_file_that_is_committed_and_the_build_may_remove_one_that_is_not(tmp_path, gitenv):
    repo = make_repo(tmp_path / "repo")
    left = a_killed_run_of_the_tag(repo)
    run_git(repo, "add", "releases")
    commit(repo, "a temporary file that was committed by a git add -A")
    git = release.Git(repo)
    with pytest.raises(ReleaseRefused, match=r"tracked by git"):
        release.clear_unfinished(repo, left.out_dir, TAG, git)
    assert left.temporary[0].is_file() and left.temporary[1].is_file() and left.report.is_file()
    run_git(repo, "rm", "-q", "-f", "--", f"releases/{left.temporary[0].name}")  # (no longer tracked: git's own word that it is not)
    removed = release.clear_unfinished(repo, left.out_dir, TAG, git)
    assert not any(path.exists() for path in (left.report, left.asset, *left.temporary))
    assert f"reports/{left.temporary[1].name}" in removed


def test_a_pointer_that_exists_still_uses_up_the_tag_whatever_else_is_there(world, tmp_path):
    copy = clone(world, tmp_path)
    (copy.root / "releases" / f"{TAG}.json").write_text("{}", encoding="utf-8")
    (copy.root / "reports" / f"results-diff-{TAG}.md").write_text("x", encoding="utf-8")
    with pytest.raises(ReleaseRefused, match="already"):
        build(world, tmp_path)
    assert (copy.root / "reports" / f"results-diff-{TAG}.md").exists()  # (nothing was removed for a tag that is used)


def test_the_full_diff_of_the_first_round_is_removed_by_its_exact_name_and_a_neighbour_is_not(world, tmp_path):
    copy = clone(world, tmp_path)
    folder = copy.root / "build" / "release"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{TAG}.results-diff.json").write_text("{}", encoding="utf-8")  # (where an upload of build/release/<tag>.* would take it)
    (folder / f"{TAG}-2.results-diff.json").write_text("{}", encoding="utf-8")  # (another tag's)
    build(world, tmp_path)
    assert sorted(p.name for p in folder.iterdir()) == [f"{TAG}-2.results-diff.json", f"{TAG}.tar.gz"]


def test_an_error_after_the_asset_is_renamed_and_before_the_pointer_is_written_removes_the_asset(world, tmp_path, monkeypatch):
    real = assemble._sha256_of

    def fails_on_the_asset(path):
        if str(path).endswith(".tar.gz"):
            raise OSError("the disk failed")
        return real(path)

    monkeypatch.setattr(assemble, "_sha256_of", fails_on_the_asset)
    with pytest.raises(OSError, match="disk failed"):
        build(world, tmp_path)
    assert not (tmp_path / "w" / "build" / "release" / f"{TAG}.tar.gz").exists()
    nothing_left(tmp_path / "w")


@pytest.mark.parametrize("failing", ["every line", "the last lines"])
def test_a_failure_to_print_is_not_a_failure_of_the_build(world, tmp_path, failing):
    def broken(line):
        if failing == "every line" or line.startswith(("asset:", "results diff:", "TRIAL build:")):
            raise BrokenPipeError(32, "Broken pipe")

    copy, result, _ = build(world, tmp_path, say=broken)
    assert result.pointer is not None and result.pointer.is_file() and result.asset.is_file()


# ---- the places a private file is written ------------------------------------------------------------------------------------------------------------------


def test_a_junction_on_the_way_to_a_private_output_refuses_the_build_before_anything_is_written(world, tmp_path):
    copy = clone(world, tmp_path)
    (copy.root / ".git").mkdir()  # (a work tree of git, for the check)
    make_junction(copy.root / "build" / "reports", copy.root / "reports")  # the full diff would land in the tracked folder
    calls: list[str] = []
    with pytest.raises(ReleaseRefused, match="link|junction"):
        build(world, tmp_path, runner=lambda spec: calls.append(spec.slug))
    assert calls == [] and files_under(copy.root / "reports") == []


def test_a_gitignore_that_ignores_the_catalog_names_only_does_not_make_the_private_outputs_safe(world, tmp_path, gitenv):
    copy = clone(world, tmp_path)
    make_repo(copy.root)
    (copy.root / ".gitignore").write_text("catalog.json\ncatalog-summary.json\ncatalog-warnings.json\nsources-manifest.json\n", encoding="utf-8")
    run_git(copy.root, "add", ".gitignore")
    commit(copy.root, "an ignore rule that is too narrow")
    calls: list[str] = []
    with pytest.raises(ReleaseRefused, match="ignore") as raised:
        build(world, tmp_path, git=release.Git(copy.root), runner=lambda spec: calls.append(spec.slug))
    assert "results-diff" in str(raised.value)
    assert calls == []


def test_the_paths_the_build_checks_before_it_writes_a_private_file_are_the_files_and_their_temporary_names(world, tmp_path):
    git = FakeGit()
    build(world, tmp_path, git=git)
    asked = {Path(path).name for kind, path in git.asked if kind == "ignored"}
    assert f"results-diff-{TAG}.json" in asked
    assert any(name.startswith(".") and name.endswith(".tmp") for name in asked)  # (a temporary file of the same folder: a narrower rule may miss it)


def test_a_trial_checks_its_folder_too(world, tmp_path):
    git = FakeGit()
    build(world, tmp_path, git=git, trios=[TRIOS[0]], trial=True)
    asked = {Path(path).name for kind, path in git.asked if kind == "ignored"}
    assert f"{TAG}.results-diff.md" in asked and f"{TAG}.results-diff.json" in asked and f"{TAG}.tar.gz" in asked


def test_a_build_folder_that_git_ignores_only_in_part_is_refused_at_the_start_and_not_after_the_hours(world, tmp_path, gitenv):
    copy = clone(world, tmp_path)
    make_repo(copy.root)
    # the full diff and the results are ignored, so every check made at the start passes; the folder of the release is not
    (copy.root / ".gitignore").write_text("build/reports/\nbuild/results/\n", encoding="utf-8")
    run_git(copy.root, "add", ".gitignore")
    commit(copy.root, "rules that ignore the full diff and the results, and not the build folder")
    calls: list[str] = []

    def spy(spec):
        calls.append(spec.slug)
        return release.run_trio(spec)

    with pytest.raises(ReleaseRefused, match=r"the build folder build is not ignored by git as a whole"):
        build(world, tmp_path, git=release.Git(copy.root), runner=spy)
    assert calls == []  # (nothing was solved or written: the hours were not spent)
    nothing_left(copy.root)


def test_a_private_output_in_a_place_git_does_not_ignore_refuses_the_build_before_anything_is_written(world, tmp_path):
    copy = clone(world, tmp_path)
    git = FakeGit()
    git.unignored.append(copy.root / "build" / "reports")  # (the full diff would be written to a place that git does not ignore)
    calls: list[str] = []
    with pytest.raises(ReleaseRefused, match="ignore") as raised:
        build(world, tmp_path, git=git, runner=lambda spec: calls.append(spec.slug))
    assert "results-diff" in str(raised.value) and calls == []
    assert files_under(copy.root / "reports") == []


def test_a_junction_made_in_the_middle_of_the_build_is_found_before_the_outputs_are_written(world, tmp_path, gitenv):
    copy = clone(world, tmp_path)
    make_repo(copy.root)
    (copy.root / ".gitignore").write_text("build/\n", encoding="utf-8")
    run_git(copy.root, "add", ".gitignore")
    commit(copy.root, "the start")

    def makes_a_junction(folder, sample, files):
        make_junction(copy.root / "build" / "reports", copy.root / "reports")  # (after the first look at the places, before the outputs; git ignores build/)
        return 0, "ok\n"

    with pytest.raises(ReleaseRefused, match="link|junction"):
        build(world, tmp_path, git=release.Git(copy.root), parity_runner=makes_a_junction)
    assert files_under(copy.root / "reports") == [] and files_under(copy.root / "releases") == []
    nothing_left(copy.root)


def test_the_temporary_files_of_a_write_that_was_cut_short_are_cleared_from_the_tracked_folders_for_this_tag_only(world, tmp_path):
    """A kill between the temporary file of the pointer (or of the report) and its rename leaves a file in releases/ or reports/ that a `git add -A` would commit."""
    copy = clone(world, tmp_path)
    mine = [copy.root / "releases" / f".{TAG}.json.k3x9q1.tmp", copy.root / "reports" / f".results-diff-{TAG}.md.k3x9q1.tmp"]
    others = [copy.root / "releases" / ".data-2026-10-20.json.k3x9q1.tmp", copy.root / "reports" / ".results-diff-data-2026-10-20.md.k3x9q1.tmp"]
    for path in [*mine, *others]:
        path.write_text("{}", encoding="utf-8")
    _, result, lines = build(world, tmp_path)
    assert result.pointer is not None
    assert not any(path.exists() for path in mine) and all(path.exists() for path in others)
    assert any("cleared" in line and f".{TAG}.json.k3x9q1.tmp" in line for line in lines)


def test_a_release_in_which_an_item_has_two_rows_is_refused_by_the_build_before_anything_is_packed(world, tmp_path):
    """The check is part of the build, between the check of the grid and the invariants: one shard shows another source for an item than the rest."""
    changed = []  # (the key of the item whose row is changed: the first the shard shows; which items the kits wear moves with the solver)

    def two_rows(spec):
        outcome = release.run_trio(spec)
        if spec.slug == TRIOS[0]:
            def change(document):
                row = document["items"][0]
                changed.append(row[0])
                row[5] = "Quest in Another Zone"

            edit(Path(spec.results) / spec.slug / "wiki-group.json", change)
        return outcome

    with pytest.raises(ReleaseRefused, match=r"row in one shard") as raised:
        build(world, tmp_path, runner=two_rows)
    assert changed and changed[0] in str(raised.value)
    assert "Another Zone" not in str(raised.value)
    nothing_left(tmp_path / "w")
