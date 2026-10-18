"""The files of a built site, listed exactly from what the build is given, and the budget of them.

Cloudflare Pages takes a site of at most 20,000 files, and the build holds itself to 15,000 (``build.LIMITS["files"]``). The number is not
extrapolated from a small build: :func:`trioforge.site.build.site_files` lists every path of a site from its inputs (the trios, each with its
roles, its tier scope and its levels, the item pages, the fixed pages and the files of the page code), so the full grid of 560 trios is counted the
way three trios are. The first test builds three trios and holds the list to the files that the build really wrote, path for path; the others
count the full grid, and refuse what the list cannot be made from. A release check calls the function on the trios of the release.

Every name here is invented: the item keys are from w90000 up, above every page of the wiki (the last is below w73000), as the keys of the fixture are,
and test_site_fixture_items.py scans this file for the key of a real item.
"""

from __future__ import annotations

import json
import re
import shutil
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_site_build import need_node, reindex, run_build

from trioforge import precompute as pc
from trioforge.classes import CLASS_CODES
from trioforge.model.roles import roles_for
from trioforge.site import build

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "fixtures" / "site" / "results"
TRIOS = ("pal-mnk-ber", "pal-shd-ber", "clr-shd-ber")  # the trios of a build of three: the fixture's, and two made from it (Wood Elf, the fixture's third race, can start neither)
ROLES = ("balanced", "tank", "melee")
GRID = (0, 4, 10)
#: the keys of the items that get a page in a build of the fixture: its strict and wiki wearables (47 of the 48 records of its item table; the other is hidden)
ITEMS = build.item_page_keys(json.loads((RESULTS / "items.json").read_text(encoding="utf-8")))


def unhashed(path: str) -> str:
    """A published path with the digest of an engine data file made the placeholder the list uses (a digest is known only once the file is made)."""
    return re.sub(r"-[A-Z0-9]{16}\.json$", f"-{build.HASH_PLACEHOLDER}.json", path) if path.startswith(f"{build.ENGINE_DATA_DIR}/") else path


def three_trios(root: Path) -> Path:
    """The results of three trios: the fixture's, and two copies of it named for other trios (as the build of a second trio is tested)."""
    scratch = root / "results"
    shutil.copytree(RESULTS, scratch)
    for slug in TRIOS[1:]:
        folder = scratch / slug
        shutil.copytree(scratch / TRIOS[0], folder)
        codes = [code.upper() for code in slug.split("-")]
        for path in folder.rglob("*.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            if path.name == "engine-l50.json":  # the bundle names its trio as three class codes, twice
                document["trio"] = document["profile_common"]["trio"] = codes
            else:
                document["trio"] = slug
                if "classes" in document:
                    document["classes"] = codes
            path.write_text(json.dumps(document), encoding="utf-8")
        reindex(folder / "runnerups")  # the runner-up files changed, so their index follows
    return scratch


@pytest.fixture(scope="module")
def assets():
    """The files the page code is made of (the stylesheet, the scripts, the optimizer's scripts and WebAssembly): what a build is given besides its results."""
    need_node()
    return build.page_code_files()


@pytest.fixture(scope="module", params=[False, True], ids=["indexable", "noindex"])
def three(request, tmp_path_factory):
    need_node()
    tmp = tmp_path_factory.mktemp("three")
    out = tmp / "dist"
    summary = run_build(out, tmp, results=three_trios(tmp), noindex=request.param)
    names = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    return SimpleNamespace(out=out, summary=summary, names=names, noindex=request.param)


def trio(slug: str, tiers: tuple[int, ...] = GRID) -> build.TrioFiles:
    return build.TrioFiles(slug, ROLES, tiers)


def item_keys(count: int) -> list[str]:
    """The keys of ``count`` items that get a page: w90000 and up, which no page of the wiki has."""
    return [f"w{90000 + n}" for n in range(count)]


# ---- three trios: the list is the files of the build ------------------------------------------------------------------------------------


def test_the_file_list_of_a_build_of_three_trios_is_the_files_the_build_wrote_path_for_path(three, assets):
    listed = build.site_files([trio(slug) for slug in TRIOS], assets=assets, item_pages=ITEMS, noindex=three.noindex)
    assert sorted(listed) == sorted(unhashed(name) for name in three.names)
    assert len(listed) == len(three.names) == three.summary.files  # the count the build reports is the count of the folder
    per_trio = 1 + 4 + len(ROLES) + 1 + 1 + 1  # the page, four shards, a runner-up file for each role, the seals, the bundle and the trio's manifest
    fixed = 6 + 3 + 1 + (0 if three.noindex else 1)  # six pages; _headers, robots.txt and the manifest; the item table; and a sitemap
    assert len(listed) == len(TRIOS) * per_trio + fixed + len(assets) + len(ITEMS) == len(TRIOS) * per_trio + fixed + len(assets) + 47


def test_the_runner_up_files_of_a_trio_are_one_for_each_role_whatever_its_tier_scope(three, assets):
    scopes = [(0, 4, 10), tuple(range(11)), (4,), (0, 10)]
    counts = {len(build.site_files([trio(slug, tiers) for slug in TRIOS], assets=assets, item_pages=ITEMS, noindex=three.noindex)) for tiers in scopes}
    assert counts == {len(three.names)}  # a tier is a row in a file, never a file: the scope of a trio changes no count
    runnerups = [name for name in three.names if "/runnerups/" in name]
    assert runnerups == sorted(f"data/{slug}/runnerups/{role}.json" for slug in TRIOS for role in ROLES)


# ---- the full grid -----------------------------------------------------------------------------------------------------------------------


def full_grid() -> list[build.TrioFiles]:
    """All 560 trios, each with the roles it is offered and the scope a run gives it: +0, +4 and +10, and every tier for the milestone trio."""
    codes = list(combinations(CLASS_CODES, 3))
    assert len(codes) == 560
    return [build.TrioFiles("-".join(code.lower() for code in trio_codes), tuple(roles_for(trio_codes)), pc.default_tiers(trio_codes)) for trio_codes in codes]


def test_the_full_grid_of_560_trios_with_the_milestone_trio_at_every_tier_and_2500_item_pages_is_within_15000_files(assets):
    trios = full_grid()
    milestone = [t for t in trios if t.slug == "pal-mnk-ber"]
    assert len(milestone) == 1 and milestone[0].tiers == tuple(range(11))  # the one trio that has every tier
    assert all(t.tiers == GRID for t in trios if t.slug != "pal-mnk-ber")
    items = item_keys(2500)
    listed = build.site_files(trios, item_pages=items, assets=assets, noindex=False)
    assert len(listed) == len(set(listed))  # no path twice
    assert len(listed) <= build.LIMITS["files"] == 15_000, len(listed)
    assert build.check_file_budget(listed) == len(listed)
    # counted, not guessed: the files of each trio, the item pages, and the files that no trio and no item has
    per_trio = sum(1 + 4 + len(t.roles) + 1 + len(t.levels) + 1 for t in trios)
    assert len(listed) == per_trio + len(items) + len(assets) + 6 + 3 + 1 + 1  # six pages; _headers, robots.txt and the manifest; the item table; a sitemap
    assert 8_000 < len(listed)  # (a count of the real thing: 560 trios of 9, 11 or 12 files each, for one role, three or four, and the item pages)
    assert sum(1 for path in listed if path.startswith("item/")) == 2500


def test_a_site_of_more_than_15000_files_is_refused_with_its_count(assets):
    trios = full_grid()
    listed = build.site_files(trios, item_pages=item_keys(2500), assets=assets)
    assert build.check_file_budget(listed) <= 15_000
    over = build.site_files(trios, item_pages=item_keys(9000), assets=assets)
    with pytest.raises(build.BudgetError, match=rf"{len(over):,} files \(limit 15,000\)"):
        build.check_file_budget(over)


def test_the_item_pages_are_counted_one_for_each_key_and_a_key_twice_is_one_page_too_many(assets):
    base = build.site_files([trio("pal-mnk-ber")], assets=assets)
    with_items = build.site_files([trio("pal-mnk-ber")], item_pages=["w90001", "w90002", "w90003"], assets=assets)
    assert len(with_items) == len(base) + 3 and "item/w90002/index.html" in with_items
    with pytest.raises(build.BuildError, match="item page w90001 twice"):
        build.site_files([trio("pal-mnk-ber")], item_pages=["w90001", "w90002", "w90001"], assets=assets)
    for bad in ("", "../x", "a/b", "W90001", "w 90001", "w90001.html"):
        with pytest.raises(build.BuildError, match="not an item key"):
            build.site_files([trio("pal-mnk-ber")], item_pages=[bad], assets=assets)


# ---- what the list cannot be made from ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trios", "message"),
    [
        ([build.TrioFiles("pal-mnk-ber", (), GRID)], "no role"),
        ([build.TrioFiles("pal-mnk-ber", ("balanced", "balanced"), GRID)], "role balanced twice"),
        ([build.TrioFiles("pal-mnk-ber", ("healer",), GRID)], "not a role"),
        ([build.TrioFiles("pal-mnk-ber", ROLES, ())], "no tier"),
        ([build.TrioFiles("pal-mnk-ber", ROLES, (4, 4))], "ascending"),
        ([build.TrioFiles("pal-mnk-ber", ROLES, (10, 0))], "ascending"),
        ([build.TrioFiles("pal-mnk-ber", ROLES, (0, 11))], "not a tier"),
        ([build.TrioFiles("pal-mnk-ber", ROLES, (0, -1))], "not a tier"),
        ([build.TrioFiles("pal-mnk-ber", ROLES, GRID, ())], "no level"),
        ([build.TrioFiles("pal-mnk-ber", ROLES, GRID, (50, 50))], "level 50 twice"),
        ([build.TrioFiles("pal-mnk-ber", ROLES, GRID, (0,))], "not a level"),
        ([build.TrioFiles("PAL-MNK-BER", ROLES, GRID)], "not the code of a trio"),
        ([build.TrioFiles("pal-mnk", ROLES, GRID)], "not the code of a trio"),
        ([trio("pal-mnk-ber"), trio("pal-mnk-ber")], "trio pal-mnk-ber twice"),
    ],
)
def test_a_trio_that_no_build_could_have_is_refused(trios, message, assets):
    with pytest.raises(build.BuildError, match=message):
        build.site_files(trios, assets=assets)


def test_the_list_needs_the_files_of_the_page_code_and_takes_no_other_than_theirs():
    with pytest.raises(build.BuildError, match="no file of the page code"):
        build.site_files([trio("pal-mnk-ber")], assets=())
    with pytest.raises(build.BuildError, match="not under assets/"):
        build.site_files([trio("pal-mnk-ber")], assets=("data/x.json",))
    with pytest.raises(build.BuildError, match="belongs to the data of a trio"):
        build.site_files([trio("pal-mnk-ber")], assets=("assets/app-AAAAAAAA.js", "assets/engine/data/items-0123456789ABCDEF.json"))
    with pytest.raises(build.BuildError, match="twice"):
        build.site_files([trio("pal-mnk-ber")], assets=("assets/app-AAAAAAAA.js", "assets/app-AAAAAAAA.js"))
