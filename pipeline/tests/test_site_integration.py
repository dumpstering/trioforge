"""The precompute and the site generator, end to end: a tiny real run, and the site built from what it wrote.

The site generator was written against fixtures (``fixtures/site/results``) while the precompute was written against the plan;
these tests are where the two meet. The first compares the keys of the fixtures with the keys a real run writes, so that a
change to the files can no longer leave the fixtures behind. The others run the real solver on a small grid (two races, the
Tank build, the tiers the page needs) and build the whole site from the result files: the invented catalog of
``test_precompute.py`` with and without seen flags (so that the default answer comes from the strict level and from the wiki
level), and, when the catalog is built, the real catalog.

The tests that bundle the JavaScript need Node and ``npm ci --ignore-scripts`` (esbuild); without them they skip, unless
``TRIOFORGE_REQUIRE_NODE=1`` is set.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

import pytest
from site_helpers import parse
from solver_helpers import slow
from test_precompute import CATALOG, SLUG, expand, make_item, read, small_world, write_catalog, write_seen

from trioforge import precompute as pc
from trioforge.model.roles import roles_for
from trioforge.precompute import grid, shards
from trioforge.site import build, data

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures" / "site" / "results" / SLUG
GRID = dict(races=("OGR", "TRL"), roles=("tank",), tiers=(0, 4, 10))  # the page needs +4, the seals +4 and +10
# a strict level that wears things, and holds an item that needs a deity (the crown), so that the runner-ups have a badge to show
SEEN = {"w9001", "w9002", "w9003", "w9006", "w9007", "w9009", "w9011", "w9012", "w9014", "w9015", "w9021"}


def need_node() -> None:
    if shutil.which("node") is None or not (REPO / "node_modules" / "esbuild" / "bin" / "esbuild").exists():
        message = "Node and esbuild are needed (run `npm ci --ignore-scripts`)"
        if os.environ.get("TRIOFORGE_REQUIRE_NODE") == "1":
            pytest.fail(message)
        pytest.skip(message)


def manifest_for(path: Path, items: list[dict]) -> Path:
    """A sources manifest that names every item of an invented catalog (the build refuses an item it cannot credit)."""
    document = {
        "provenance": {"inputs": [{"file": "derived/client/zones.json", "sha256": "0" * 64, "date": "2026-10-13"}], "generator": "test", "generated": "2030-01-02"},
        "license": "CC BY-SA 4.0", "attribution": "Item data adapted from eqlwiki.com (CC BY-SA 4.0) by the eqlwiki contributors",
        "items": {item["key"]: {"title": item["name"], "revid": 1} for item in items},
    }  # fmt: skip
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def changelog(path: Path) -> Path:
    path.write_text("# Changelog\n\n## Unreleased\n\n- A test.\n", encoding="utf-8")
    return path


def site_from(results: Path, tmp_path: Path, manifest: Path, name: str = "dist"):
    out = tmp_path / name
    summary = build.build(results=results, out=out, noindex=True, sources_manifest=manifest, changelog=changelog(tmp_path / f"{name}.md"))
    return out, summary


# ---- the fixtures have the keys of a real run -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    """One tiny real run with seen flags (so that the strict level wears items): its result files, folder and catalog."""
    root = tmp_path_factory.mktemp("real")
    catalog = write_catalog(root / "catalog.json")
    out = root / "out"
    pc.run(SLUG, out, seen_path=write_seen(root / "seen.json", SEEN), catalog=catalog, processes=1, **GRID)
    return root, out / SLUG, catalog


def keys_of(path: Path) -> list[str]:
    return list(json.loads(path.read_text(encoding="utf-8")))


def test_the_fixtures_have_the_keys_a_real_run_writes_in_the_same_order(real):
    _, folder, _ = real
    for name in (*shards.SHARD_NAMES, "defaults.json", "robust.json", "runnerups/index.json", "runnerups/tank.json"):
        assert keys_of(FIXTURES / name) == keys_of(folder / name), name
    for name in shards.SHARD_NAMES:
        fixture, run = (json.loads((root / name).read_text(encoding="utf-8")) for root in (FIXTURES, folder))
        for nested in ("solver", "build_options", "assumptions", "caps"):
            assert list(fixture[nested]) == list(run[nested]), (name, nested)
        assert fixture["items_keys"] == run["items_keys"] and fixture["totals_keys"] == run["totals_keys"]
        assert fixture["places"] == run["places"] and list(fixture["races"][0]) == list(run["races"][0])
        assert len(fixture["scenarios"][0]) == len(run["scenarios"][0]) == 10
        assert all(len(row) == len(shards.ITEM_KEYS) for row in fixture["items"])
        assert all(len(row) == len(shards.TOTALS_KEYS) for row in fixture["totals"]) and all(len(k) == 22 for k in fixture["kits"])
    fixture, run = (json.loads((root / "defaults.json").read_text(encoding="utf-8")) for root in (FIXTURES, folder))
    assert list(fixture["view"]) == list(run["view"]) and list(fixture["races"][0]) == list(run["races"][0])
    fixture, run = (json.loads((root / "robust.json").read_text(encoding="utf-8")) for root in (FIXTURES, folder))
    role = next(iter(run["roles"]))
    assert list(fixture["roles"]["tank"]["4"]) == list(run["roles"][role]["4"]) == list(shards.PLACES)
    fixture, run = (json.loads((root / "runnerups" / "index.json").read_text(encoding="utf-8")) for root in (FIXTURES, folder))
    assert list(fixture["files"][0]) == list(run["files"][0])
    fixture, run = (json.loads((root / "runnerups" / "tank.json").read_text(encoding="utf-8")) for root in (FIXTURES, folder))
    assert fixture["places"] == run["places"] and fixture["items_keys"] == run["items_keys"]
    assert fixture["tiers"] == run["tiers"] == [0, 4, 10]  # the tiers of the run, every one of them in the file of the role
    assert len(fixture["views"][0]) == len(run["views"][0]) == 4 and len(fixture["views"][0][3]) == len(run["views"][0][3]) == 22
    assert all(len(swap) == 2 for view in fixture["views"] for place in view[3] for swap in place)


def test_the_reader_reads_every_file_a_real_run_writes(real):
    _, folder, _ = real
    results = data.load_trio(folder)
    assert results.meta.slug == SLUG and results.meta.partial is True and results.meta.data_tag == "data-2030-01-02"
    assert sorted(results.shards) == [("strict", "group"), ("strict", "own"), ("wiki", "group"), ("wiki", "own")]
    assert results.defaults.evidence == "strict" and results.defaults.strict_empty is False and results.defaults.robustness == "done"
    assert results.robust.race == results.defaults.race and results.robust.view("tank", 4) and results.robust.view("tank", 10)
    assert results.robust.view("tank", 0) is None  # the seals are for +4 and +10
    assert results.runnerups.pairs() == (("tank", 0), ("tank", 4), ("tank", 10))
    wiki = read(folder / "wiki-own.json")
    scenario = results.shards[("wiki", "own")].scenario("OGR", "tank", 4, "dw")
    row = expand(wiki)[("OGR", "tank", 4, "dw")]
    assert [item.key if item else None for item in scenario.kit] == row["kit"] and scenario.value == pytest.approx(row["F"], abs=0.0006)
    assert scenario.totals.ac == row["totals"]["ac"] and scenario.totals.resists[1] == row["totals"]["fire"]  # MAGIC FIRE COLD ...
    assert scenario.totals.regen == (row["totals"]["hpreg"], row["totals"]["manareg"], row["totals"]["endreg"])
    assert scenario.haste_assumed == row["haste"] and scenario.buffs == tuple(row["buffs"])


# ---- the site built from a real run -------------------------------------------------------------------------------------------


def test_the_site_built_from_a_tiny_run_bakes_the_kit_the_precompute_solved(real, tmp_path):
    need_node()
    root, folder, catalog = real
    manifest = manifest_for(tmp_path / "manifest.json", CATALOG)
    out, summary = site_from(folder.parent, tmp_path, manifest)
    assert summary.partial == (SLUG,)
    html = parse((out / "trio" / SLUG / "index.html").read_text(encoding="utf-8"))
    defaults = read(folder / "defaults.json")
    rows = expand(read(folder / "strict-own.json"))
    wanted = rows[(defaults["race"], "tank", 4, defaults["setup"])]["kit"]
    names = {item["key"]: item["name"] for item in CATALOG}
    baked = [row.find(data_f="name").text() for row in html.by_id("kit-body").find_all("tr")]
    assert baked == [names[key] if key else "Leave empty" for key in wanted]
    assert any(name != "Leave empty" for name in baked)
    assert html.by_id("sw-race").find("option", selected=True).get("value") == defaults["race"]
    best = html.by_id("best-race").text()
    assert best.startswith("Best race for this trio: ") and f"(+{round(defaults['margin'])} over " in best
    assert html.find_all("input", name="ev") == [] and html.find_all("p", id_="evidence-note") == []  # no evidence picker, no note: wiki is the one level
    # the runner-ups were solved for the same default answer, and one of them needs a deity (a badge, first in its slot)
    runnerups = html.by_id("runnerups-body").find_all("tr")
    assert len(runnerups) == 22 and any(r.find_all("li") for r in runnerups)
    assert any("Needs deity" in r.text() for r in runnerups)
    # the seals are baked for the default race, and every file the page fetches is written and valid JSON
    summary_text = html.by_id("robust-summary").text()
    assert re.fullmatch(r"All 22 picks hold in every check\.|\d+ of 22 picks hold in every check\. The other \d+ depends? on an assumption:", summary_text), summary_text
    for name, version in (("strict-own", 1), ("strict-group", 1), ("wiki-own", 1), ("wiki-group", 1), ("robust", 2)):
        assert json.loads((out / "data" / SLUG / f"{name}.json").read_text(encoding="utf-8"))["v"] == version  # robust: 2 names the sealed view
    assert sorted(p.name for p in (out / "data" / SLUG / "runnerups").iterdir()) == ["tank.json"]  # a file for the role, and the three tiers are in it
    assert json.loads((out / "data" / SLUG / "runnerups" / "tank.json").read_text(encoding="utf-8"))["tiers"] == [0, 4, 10]


def test_with_no_seen_flags_the_site_is_built_from_the_wiki_level_and_says_nothing_of_it(tmp_path):
    need_node()
    catalog = write_catalog(tmp_path / "catalog.json")
    out = tmp_path / "out"
    pc.run(SLUG, out, catalog=catalog, processes=1, **GRID)
    folder = out / SLUG
    defaults = read(folder / "defaults.json")
    assert defaults["strict_pool_empty"] is True and defaults["view"]["evidence"] == "wiki"
    site, _ = site_from(out, tmp_path, manifest_for(tmp_path / "manifest.json", CATALOG))
    html = parse((site / "trio" / SLUG / "index.html").read_text(encoding="utf-8"))
    names = {item["key"]: item["name"] for item in CATALOG}
    wanted = expand(read(folder / "wiki-own.json"))[(defaults["race"], "tank", 4, defaults["setup"])]["kit"]
    baked = [row.find(data_f="name").text() for row in html.by_id("kit-body").find_all("tr")]
    assert baked == [names[key] if key else "Leave empty" for key in wanted] and any(name != "Leave empty" for name in baked)
    assert html.find_all("input", name="ev") == [] and html.find_all("p", id_="evidence-note") == []  # no evidence picker, no note: wiki is the one level
    assert not html.find_all("details", id_="assume-evidence")
    runnerups = html.by_id("runnerups-body").find_all("tr")
    assert any(r.find_all("li") for r in runnerups) and not html.by_id("runnerups-table").has("hidden")
    # the strict level holds the naked character, which the page shows if it is asked for
    strict = json.loads((site / "data" / SLUG / "strict-own.json").read_text(encoding="utf-8"))
    assert strict["items"] == [] and strict["kits"] == [[-1] * 22]


def test_with_nothing_seen_the_strict_level_has_no_shield_setup_and_the_wiki_page_offers_it(tmp_path):
    """The strict pool is empty, so it has no shield: the strict shards have no 1h-shield rows, however many scenarios the
    wiki level has for it. The page is baked from the wiki level, so it offers the setup, and the strict data does not."""
    need_node()
    out = tmp_path / "out"
    pc.run(SLUG, out, catalog=write_catalog(tmp_path / "catalog.json"), processes=1, **GRID)
    folder = out / SLUG
    for buffs in ("own", "group"):
        assert read(folder / f"strict-{buffs}.json")["setups"] == {"tank": ["2h", "dw"]}
        assert read(folder / f"wiki-{buffs}.json")["setups"] == {"tank": ["1h-shield", "2h", "dw"]}
    site, _ = site_from(out, tmp_path, manifest_for(tmp_path / "manifest.json", CATALOG))
    html = parse((site / "trio" / SLUG / "index.html").read_text(encoding="utf-8"))
    assert html.find_all("input", name="ev") == []
    assert html.by_id("role-tank").get("data-setups") == "1h-shield 2h dw"  # what the wiki level offers the default role
    radios = {r.get("value"): r for r in html.find_all("input", name="setup")}
    assert sorted(radios) == ["1h-shield", "2h", "dw"] and not any(r.has("hidden") for r in radios.values())
    rows = {name: json.loads((site / "data" / SLUG / f"{name}.json").read_text(encoding="utf-8"))["rows"] for name in ("strict-own", "wiki-own")}
    assert {row[3] for row in rows["strict-own"]} == {"2h", "dw"} and {row[3] for row in rows["wiki-own"]} == {"1h-shield", "2h", "dw"}


def test_a_strict_level_with_items_but_no_shield_does_not_offer_the_shield_setup_in_the_page_baked_from_it(tmp_path):
    """A seen helm, chest and sword: strict items, and no shield among them. The answer is strict, so the page is baked from a
    level with two setups, and the wiki level's third is a hidden choice."""
    need_node()
    out = tmp_path / "out"
    seen = write_seen(tmp_path / "seen.json", {"w9001", "w9006", "w9011"})
    pc.run(SLUG, out, seen_path=seen, catalog=write_catalog(tmp_path / "catalog.json"), processes=1, **GRID)
    folder = out / SLUG
    assert read(folder / "strict-own.json")["pool"] == 3 and read(folder / "strict-own.json")["setups"] == {"tank": ["2h", "dw"]}
    assert read(folder / "wiki-own.json")["setups"] == {"tank": ["1h-shield", "2h", "dw"]}
    defaults = read(folder / "defaults.json")
    assert defaults["view"]["evidence"] == "strict" and defaults["setup"] in ("2h", "dw")
    site, _ = site_from(out, tmp_path, manifest_for(tmp_path / "manifest.json", CATALOG))
    html = parse((site / "trio" / SLUG / "index.html").read_text(encoding="utf-8"))
    assert html.find_all("input", name="ev") == []
    assert html.by_id("role-tank").get("data-setups") == "2h dw"
    radios = {r.get("value"): r for r in html.find_all("input", name="setup")}
    assert sorted(radios) == ["1h-shield", "2h", "dw"]
    assert radios["1h-shield"].has("hidden") and radios["1h-shield"].has("disabled")  # there, for the wiki level, and out of reach
    assert [name for name, r in radios.items() if r.has("checked")] == [defaults["setup"]]
    rows = {name: json.loads((site / "data" / SLUG / f"{name}.json").read_text(encoding="utf-8"))["rows"] for name in ("strict-own", "wiki-own")}
    assert "1h-shield" not in {row[3] for row in rows["strict-own"]} and "1h-shield" in {row[3] for row in rows["wiki-own"]}


def test_a_race_that_cannot_wear_an_item_does_not_get_it_on_the_page(tmp_path):
    """An item for one race, the shield only that race can wear, a total below zero: shapes only a real run has."""
    need_node()
    zulu = make_item("w9027", "Test Zulu Greaves", ["LEGS"], stats={"AC": 99, "STA": 99}, weight=1.0, races=["TRL"])
    ammo = make_item("w9031", "Test Thrown Axe", ["RANGE", "AMMO"], stats={"STR": 40, "ATK": 60}, weight=0.5)
    items = [*CATALOG, zulu, ammo]
    catalog = write_catalog(tmp_path / "catalog.json", items)
    out = tmp_path / "out"
    pc.run(SLUG, out, catalog=catalog, processes=1, **GRID)
    site, _ = site_from(out, tmp_path, manifest_for(tmp_path / "manifest.json", items))
    shard = json.loads((site / "data" / SLUG / "wiki-own.json").read_text(encoding="utf-8"))
    by_key = {row[0]: n for n, row in enumerate(shard["items"])}
    legs = 14  # the legs place of a kit
    kits = {(row[0], row[2], row[3]): shard["kits"][row[4]] for row in shard["rows"]}
    assert kits[("TRL", 4, "dw")][legs] == by_key["w9027"]  # the Troll wears it
    assert by_key["w9027"] not in kits[("OGR", 4, "dw")]  # the Ogre does not
    assert by_key["w9031"] in kits[("OGR", 4, "dw")]  # an item that also fits the ammo place is worn in the range place, and reads


# ---- a run that is the whole of its scope ----------------------------------------------------------------------------------------

GRID_TRIO = "pal-shd-ber"  # a trio of the grid: a full run of it has the tiers +0, +4 and +10


def small_run(root, trio, **options):
    """A run that narrows nothing (every role and setup, both evidence levels and buff sets) in a world of two races."""
    catalog = write_catalog(root / "catalog.json")
    out = root / "out"
    return out, pc.run(trio, out, catalog=catalog, processes=1, tables_root=small_world(root / "world"), **options)


@pytest.fixture(scope="module")
def whole(tmp_path_factory):
    """A run of a trio of the grid that is given no tiers: it has the default scope, +0, +4 and +10."""
    return small_run(tmp_path_factory.mktemp("whole"), GRID_TRIO)


@pytest.fixture(scope="module")
def short(tmp_path_factory):
    """The milestone trio asked for +0 and +4: a full run of what it was asked for, not of what a full run of this trio has (all eleven tiers)."""
    return small_run(tmp_path_factory.mktemp("short"), SLUG, tiers=(0, 4))


def test_a_run_of_the_default_scope_that_narrows_nothing_builds_an_indexable_site_whose_tier_switch_offers_those_tiers_only(whole, tmp_path):
    need_node()
    out, summary = whole
    assert summary.partial is False and summary.tiers == (0, 4, 10) and not summary.violations
    results = data.load_trio(out / GRID_TRIO)
    assert results.meta.partial is False
    assert all(shard.tiers == (0, 4, 10) for shard in results.shards.values())
    roles = tuple(roles_for(("PAL", "SHD", "BER")))
    assert [(f.role, f.tiers) for f in results.runnerups.files] == [(role, (0, 4, 10)) for role in roles]
    manifest = manifest_for(tmp_path / "manifest.json", CATALOG)
    site = tmp_path / "dist"
    built = build.build(
        results=out, out=site, noindex=False, owner="example-owner", sources_manifest=manifest, changelog=changelog(tmp_path / "changelog.md")
    )  # an indexable build, told no scope: it refuses a partial run and a trio with other tiers than a full run of it, and this one is neither
    assert built.partial == ()
    html = parse((site / "trio" / GRID_TRIO / "index.html").read_text(encoding="utf-8"))
    options = html.by_id("sw-tier").find_all("option")
    assert [(o.get("value"), o.text()) for o in options] == [("0", "+0"), ("4", "+4"), ("10", "+10 (endgame)")]  # the tiers the shards have
    assert [o.get("value") for o in options if o.has("selected")] == ["4"]
    assert html.by_id("runnerups").get("data-files").split() == list(roles)
    folder = site / "data" / GRID_TRIO / "runnerups"
    assert sorted(p.name for p in folder.iterdir()) == sorted(f"{role}.json" for role in roles)  # a file for each role, and none for a tier
    for path in folder.iterdir():
        assert json.loads(path.read_text(encoding="utf-8"))["tiers"] == [0, 4, 10]
    assert (site / "sitemap.xml").is_file()
    assert built.files == sum(1 for p in site.rglob("*") if p.is_file())


def test_a_run_of_the_milestone_trio_at_two_tiers_is_full_and_loads_but_only_a_preview_is_built_from_it(short, tmp_path):
    need_node()
    out, summary = short
    assert summary.partial is False and summary.tiers == (0, 4)  # a full run of the tiers it was asked for ...
    assert data.load_trio(out / SLUG).meta.partial is False  # ... that the reader takes as complete
    manifest = manifest_for(tmp_path / "manifest.json", CATALOG)
    arguments = dict(sources_manifest=manifest, changelog=changelog(tmp_path / "changelog.md"))
    with pytest.raises(build.BuildError) as caught:  # but not what a full run of this trio has, and an indexable site is not made from it
        build.build(results=out, out=tmp_path / "dist", noindex=False, owner="example-owner", **arguments)
    assert str(caught.value).startswith(f"{SLUG}: its shards have the tiers +0, +4, but an indexable build needs +0, +1, +2, +3, +4, +5, +6, +7, +8, +9, +10 for this trio")
    assert not (tmp_path / "dist").exists()
    preview = build.build(results=out, out=tmp_path / "preview", noindex=True, **arguments)  # a preview takes any scope
    assert preview.partial == ()
    html = parse((tmp_path / "preview" / "trio" / SLUG / "index.html").read_text(encoding="utf-8"))
    assert [o.get("value") for o in html.by_id("sw-tier").find_all("option")] == ["0", "4"]


# ---- the real catalog -----------------------------------------------------------------------------------------------------------


@slow  # about 40 s on a quiet machine: the real solver on the real catalog, with the seals and the flip check
def test_a_small_run_on_the_real_catalog_builds_into_a_site(tmp_path):
    need_node()
    catalog = grid.find_catalog()
    if catalog is None:
        pytest.skip("derived/catalog.json is not built")
    started = time.perf_counter()
    out = tmp_path / "results"
    summary = pc.run(
        SLUG, out, catalog=catalog, processes=min(8, os.cpu_count() or 2), races=("OGR", "TRL"), roles=("tank",), tiers=(4,)
    )
    assert summary.partial and not summary.violations and "done" == read(out / SLUG / "defaults.json")["robustness"]
    defaults = read(out / SLUG / "defaults.json")
    assert defaults["strict_pool_empty"] is True and defaults["view"]["evidence"] == "wiki"  # no seen flags: nothing is strict
    site = tmp_path / "dist"
    result = build.build(results=out, out=site, noindex=True, changelog=changelog(tmp_path / "changelog.md"))
    html = parse((site / "trio" / SLUG / "index.html").read_text(encoding="utf-8"))
    wiki = read(out / SLUG / "wiki-own.json")
    keys = {row[0]: row[1] for row in wiki["items"]}
    wanted = expand(wiki)[(defaults["race"], "tank", 4, defaults["setup"])]["kit"]
    baked = [row.find(data_f="name").text() for row in html.by_id("kit-body").find_all("tr")]
    assert baked == [keys[key] if key else "Leave empty" for key in wanted]
    assert result.partial == (SLUG,) and result.sizes["trio_html"] < build.LIMITS["trio_html"]
    assert not html.find_all("p", id_="evidence-note")
    print(f"the small real run and the site build took {time.perf_counter() - started:.0f} s")
