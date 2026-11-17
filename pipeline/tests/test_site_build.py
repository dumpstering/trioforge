"""The static site generator: pages, assets, headers, budgets and the contract with the browser code.

Everything renders the synthetic fixture ``fixtures/site/results/pal-mnk-ber`` (see ``test_site_data.py``) with the real
``rules/rules.json`` and ``rules/races.json``. The tests that bundle the JavaScript need Node and ``npm ci`` (esbuild);
without them they skip, unless ``TRIOFORGE_REQUIRE_NODE=1`` is set, which turns the skip into a failure.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import gzip
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlparse

import pytest
from site_helpers import extract_main, parse

from trioforge import rules as rules_module
from trioforge.classes import CLASS_CODES, CLASS_NAMES
from trioforge.site import build, data
from trioforge.site import view as view_module

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "fixtures" / "site" / "results"
MANIFEST = REPO / "fixtures" / "site" / "sources-manifest.json"
CONTRACT = REPO / "fixtures" / "site" / "contract"
STATIC = REPO / "pipeline" / "trioforge" / "site" / "static"
TEMPLATES = REPO / "pipeline" / "trioforge" / "site" / "templates"
SITE_URL = "https://trioforge.pages.dev"
OWNER = "example-owner"  # the GitHub account of the report links: an indexable build must be given one (--owner)
#: the fixture is a sample of the milestone trio at three tiers, and an indexable build holds a trio to the tiers of a full run of it (every tier, for this
#: trio): the builds of the fixture say which scope it stands for. The command line has no such option, so a build from the command line has the default.
FIXTURE_SCOPES = {"pal-mnk-ber": (0, 4, 10)}

SLOT_LABELS = [
    "Head", "Face", "Ear 1", "Ear 2", "Neck", "Shoulders", "Arms", "Back", "Wrist 1", "Wrist 2", "Hands", "Finger 1",
    "Finger 2", "Chest", "Legs", "Feet", "Waist", "Range", "Any slot 1", "Any slot 2", "Main hand", "Off hand",
]  # fmt: skip
DISCLAIMER = (
    "TrioForge is a fan project, not affiliated with or endorsed by Daybreak Game Company. "
    "EverQuest is a registered trademark of Daybreak Game Company LLC."
)
ATTRIBUTION = (
    "Item data adapted from eqlwiki.com (CC BY-SA 4.0) by the eqlwiki contributors; "
    "quest giver data compiled by EQL Tools (CC BY-SA 4.0) from eqlwiki; "
    "changes: parsed, normalized, filtered, tier-scaled"
)
LICENCE_SENTENCE = (
    "The site's data is licensed CC BY-SA 4.0, except the game facts read from Daybreak Game Company's files, "
    "which are Daybreak's and fall outside that licence. The code is licensed MIT."
)
#: the names under assets/ (relative to it): the page code and the stylesheet, the optimizer's files in assets/engine/ (the
#: WebAssembly carries the first 16 hex digits of the SHA-256 of its content, the scripts and the stylesheet esbuild's hash) and its data
#: files in assets/engine/data/ (the item table and the bundles, with the first 16 hex digits of their SHA-256)
HASHED_ASSET = (
    r"(?:(?:site|app|boot|notfound|upgrade-input|shared-kit|weights|exalt|chunk)-[A-Z0-9]{8}\.(?:css|js)|[a-z0-9]+(?:-[a-z0-9]+)*-[A-Z0-9]{8}\.png|engine/(?:client|worker|kitvalue)-[A-Z0-9]{8}\.js|engine/highs-[A-Z0-9]{16}\.wasm"
    r"|engine/data/(?:items|[a-z]{3}-[a-z]{3}-[a-z]{3}-l[0-9]{1,3})-[A-Z0-9]{16}\.json)"
)
#: the optimizer's list of files: one fixed address, outside /assets/, so that it is asked for again on every visit
MANIFEST_FILE = "engine-manifest.json"
#: the list of the bundles of each trio: a file of its own for each trio, at a fixed address beside the main list (outside /assets/ too)
TRIO_MANIFEST_DIR = "engine-trios"
CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'; img-src 'self' data:; "
    "style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'; "
    "require-trusted-types-for 'script'; trusted-types trioforge"
)


def node_ready() -> bool:
    return shutil.which("node") is not None and (REPO / "node_modules" / "esbuild" / "bin" / "esbuild").exists()


def need_node():
    if not node_ready():
        message = "Node and esbuild are needed (run `npm ci --ignore-scripts`)"
        if os.environ.get("TRIOFORGE_REQUIRE_NODE") == "1":
            pytest.fail(message)
        pytest.skip(message)


def make_changelog(tmp_path: Path) -> Path:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(
        "# Changelog\n\n"
        "## Unreleased\n\n"
        "- First **milestone** preview: the `pal-mnk-ber` page.\n"
        "- See [the rules](https://example.org/rules) for the details.\n"
        "- <script>alert(1)</script> and <b>bold</b> stay text.\n\n"
        "## Earlier\n\n"
        "A paragraph of plain words.\n",
        encoding="utf-8",
    )
    return path


def complete_copy(results: Path, tmp_path: Path) -> Path:
    """A copy of the results as a complete run would have written them. The fixture holds three races and three tiers and says so
    (``partial``), and an indexable build refuses results like that; its rows are what they are, and only that flag is turned off."""
    target = Path(tempfile.mkdtemp(dir=tmp_path)) / "results"
    shutil.copytree(results, target)
    for path in [p for name in data.SHARD_NAMES for p in target.glob(f"*/{name}.json")]:  # the four shards of each trio
        document = json.loads(path.read_text(encoding="utf-8"))
        document["partial"] = False
        path.write_text(json.dumps(document), encoding="utf-8")
    return target


def run_build(out: Path, tmp_path: Path, **overrides):
    """Build the site from the fixture, indexable and with an owner unless told otherwise (the indexable build is made from a copy
    of the results that says it is complete)."""
    options = dict(
        results=RESULTS,
        out=out,
        noindex=False,
        site_url=SITE_URL,
        sources_manifest=MANIFEST,
        changelog=make_changelog(tmp_path),
        owner=OWNER,
        scopes=FIXTURE_SCOPES,
    )
    options.update(overrides)
    if not options["noindex"]:
        options["results"] = complete_copy(options["results"], tmp_path)
    return build.build(**options)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    need_node()
    tmp = tmp_path_factory.mktemp("site")
    out = tmp / "dist"
    summary = run_build(out, tmp)
    return out, summary


@pytest.fixture(scope="module")
def site_noindex(tmp_path_factory):
    need_node()
    tmp = tmp_path_factory.mktemp("site-noindex")
    out = tmp / "dist"
    run_build(out, tmp, noindex=True)
    return out


@pytest.fixture(scope="module")
def results():
    return data.load_trio(RESULTS / "pal-mnk-ber")


def read(out: Path, name: str) -> str:
    return (out / name).read_text(encoding="utf-8")


def reindex(folder: Path) -> None:
    """Bring the index of a runner-up folder up to date with the files in it (after a test has edited some)."""
    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    for entry in index["files"]:
        body = (folder / entry["file"]).read_bytes()
        entry.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    (folder / "index.json").write_text(json.dumps(index), encoding="utf-8")


def page(out: Path, name: str):
    return parse(read(out, name))


PAGES = {
    "home": "index.html",
    "trio": "trio/pal-mnk-ber/index.html",
    "rules": "rules/index.html",
    "sources": "sources/index.html",
    "about": "about/index.html",
    "changelog": "changelog/index.html",
}
NOT_FOUND = "404.html"  # the page Pages serves, with a 404, for an address it has no file for


# ---- what the build writes --------------------------------------------------------------------------------------------


def test_the_build_writes_the_pages_the_data_the_assets_and_the_headers(site):
    out, _ = site
    for name in PAGES.values():
        assert (out / name).is_file(), name
    assert (out / NOT_FOUND).is_file()  # at the top level: that is what makes Pages answer an unknown path with a 404
    for evidence in ("strict", "wiki"):
        for buffs in ("own", "group"):
            assert (out / "data" / "pal-mnk-ber" / f"{evidence}-{buffs}.json").is_file()
    for role in ("balanced", "tank", "melee"):
        assert (out / "data" / "pal-mnk-ber" / "runnerups" / f"{role}.json").is_file()  # a file for each role, with every tier of the run in it
    assert sorted(p.name for p in (out / "data" / "pal-mnk-ber" / "runnerups").iterdir()) == ["balanced.json", "melee.json", "tank.json"]  # and none for a tier
    assert not (out / "data" / "pal-mnk-ber" / "runnerups.json").exists()  # the single file of the earlier format
    assert not (out / "data" / "pal-mnk-ber" / "runnerups" / "index.json").exists()  # the index is checked, not served
    assert (out / "data" / "pal-mnk-ber" / "robust.json").is_file()
    assert (out / "_headers").is_file()
    assert (out / "robots.txt").is_file()
    assets = sorted(p.name for p in (out / "assets").iterdir())
    assert any(re.fullmatch(r"site-[A-Z0-9]{8}\.css", a) for a in assets), assets
    assert any(re.fullmatch(r"app-[A-Z0-9]{8}\.js", a) for a in assets), assets
    assert any(re.fullmatch(r"boot-[A-Z0-9]{8}\.js", a) for a in assets), assets


def test_the_data_files_are_the_browser_format_of_the_results(site, results):
    out, _ = site
    shard = results.shards[("wiki", "group")]
    credit = build.credit_of(results.meta)
    table = json.loads((RESULTS / "items.json").read_text(encoding="utf-8"))  # (the shard carries the stats of its items at each of its tiers: the build makes them from the item table)
    vecs = view_module.tier_vecs({r.get("key") or f"w{r['id']}": r for r in table["items"]}, table["defaults"], rules_module.load())
    icons = build.item_icons(table, {})  # (the pictures of the items: the rule on the fixture's records, built without the item catalog)
    assert read(out, "data/pal-mnk-ber/wiki-group.json") == data.site_shard_json(shard, credit, lambda key, tier: view_module.item_stat_text(vecs(key, tier)), icons)
    for role in results.runnerups.roles():
        assert read(out, f"data/pal-mnk-ber/runnerups/{role}.json") == data.site_runnerups_json(results.runnerups, role, credit)
    assert read(out, "data/pal-mnk-ber/robust.json") == data.site_robust_json(results.robust, credit)


def test_a_build_is_reproducible(site, tmp_path):
    out, _ = site
    second = tmp_path / "again"
    run_build(second, tmp_path)
    first_files = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
    assert first_files == sorted(p.relative_to(second) for p in second.rglob("*") if p.is_file())
    for relative in first_files:
        assert (out / relative).read_bytes() == (second / relative).read_bytes(), relative


def test_a_rebuild_replaces_the_old_output_and_refuses_a_directory_that_is_not_a_build(site, tmp_path):
    out, _ = site
    stale = tmp_path / "stale"
    run_build(stale, tmp_path)
    (stale / "old-page.html").write_text("old", encoding="utf-8")
    run_build(stale, tmp_path)
    assert not (stale / "old-page.html").exists()
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(build.BuildError, match="not a TrioForge build"):
        run_build(precious, tmp_path)
    assert (precious / "notes.txt").read_text(encoding="utf-8") == "keep me"


# ---- the page for an address that leads nowhere --------------------------------------------------------------------------------
# Without a top-level 404.html, Cloudflare Pages treats the site as a single-page app and answers every unknown path with the
# home page and a 200, so a data file that is missing arrives as a web page that does not parse. With one, it answers 404.


def test_the_build_writes_a_404_page_with_the_frame_of_the_other_pages(site):
    out, summary = site
    assert NOT_FOUND in summary.pages
    html = page(out, NOT_FOUND)
    about = page(out, PAGES["about"])
    for part in ("header", "footer"):  # the same words in the same frame: the logo, the five links, the data strip, the notices
        assert html.find(part).text() == about.find(part).text(), part
    assert html.find("html").get("lang") == "en"
    assert html.find("title").text() == "Page not found · TrioForge"
    assert html.find("title").text() not in {page(out, name).find("title").text() for name in PAGES.values()}
    assert html.find("meta", name="description").get("content")
    first = next(n for n in html.find("body").iter() if n.tag in ("a", "button", "input", "select", "summary"))
    assert first.tag == "a" and first.get("href") == "#main" and "skip-link" in first.classes
    main = html.find("main")
    assert main.get("id") == "main" and main.get("tabindex") == "-1" and main.get("data-page") == "notfound"
    assert [h.text() for h in html.find_all("h1")] == ["Page not found"]
    levels = [int(h.tag[1]) for h in html.iter() if re.fullmatch(r"h[1-6]", h.tag)]
    assert levels[0] == 1 and all(b - a <= 1 for a, b in zip(levels, levels[1:])), levels
    assert [a for a in html.find("nav").find_all("a") if a.has("aria-current")] == []  # no page of the menu is the current one


def test_the_404_page_leads_back_to_the_home_page_and_the_live_trios_and_is_no_page_of_the_site(site):
    out, _ = site
    html = page(out, NOT_FOUND)
    hrefs = [a.get("href") for a in html.find("main").find_all("a")]
    assert hrefs[0] == "/" and "/trio/pal-mnk-ber/" in hrefs
    for href in hrefs:
        assert (out / (href.lstrip("/") + "index.html")).is_file(), href  # each way back leads somewhere
    # the page is shown at whatever address was asked for, so it names no address of its own
    assert html.find_all("link", rel="canonical") == []
    assert "404" not in read(out, "sitemap.xml")
    assert "404" not in read(out, "robots.txt")


# ---- the trio page: the baked answer -----------------------------------------------------------------------------------


def test_the_trio_page_bakes_the_default_kit_without_javascript(site, results):
    out, _ = site
    html = page(out, PAGES["trio"])
    scenario = results.shards[("strict", "own")].scenario("OGR", "balanced", 4, "dw")
    body = html.by_id("kit-body")
    rows = body.find_all("tr")
    assert len(rows) == 22
    for number, (row, label, item) in enumerate(zip(rows, SLOT_LABELS, scenario.kit)):
        assert row.find("th").text() == label
        assert row.find("th").get("scope") == "row"
        cells = row.find_all("td")
        assert len(cells) == 4  # (name, tier, arrival, source: no seal column)
        if item is None:
            assert cells[0].text(skip_hidden=True) == "Leave empty"  # (the panel of the stats is there and out of sight)
        else:
            assert cells[0].find(data_f="name").text() == item.name, number
            assert cells[1].text() == "+4"
            assert cells[2].find(data_f="arrival").text() == f"+{item.arrival}"
            assert cells[3].find(data_f="source").text() == item.source
    assert rows[0].find(data_f="name").text() == "Helm of the Stoneward"
    assert rows[4].find(data_f="name").text() == "Choker of the Deep"
    assert rows[17].find(data_f="name").text() == "<b>x</b>"
    assert rows[19].find("td").text(skip_hidden=True) == "Leave empty"
    assert rows[20].find(data_f="name").text() == "Ferryman's Pike"
    assert rows[21].find(data_f="name").text() == "Pellbrook Mallet"
    # the long name is in the page whole
    assert "Vambraces of the Unyielding Stonewarden of the Frozen Deepwatch Citadel Expedition" in rows[6].text()


def test_a_quest_item_shows_what_reaching_the_shown_tier_costs(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    reach = [r.find(data_f="reach").text() for r in html.by_id("kit-body").find_all("tr")]
    arrival = [r.find(data_f="arrival").text() for r in html.by_id("kit-body").find_all("tr")]
    assert arrival[0] == "+4" and reach[0] == ""  # a D4 drop arrives at the shown tier
    # at +4 this default kit has only drops; the helper that words the cost is exercised directly
    from trioforge.site import view

    assert view.reach_text(0, 4) == "16 copies to reach +4"
    assert view.reach_text(4, 10) == "64 copies to reach +10"  # 2^6 copies: the worked example of the tier rules
    assert view.reach_text(0, 10) == "1,024 copies to reach +10"
    assert view.reach_text(4, 4) == "" and view.reach_text(4, 0) == ""


def test_the_header_says_the_best_race_and_the_margin(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    h1 = html.find("h1")
    assert h1.text() == "Paladin / Monk / Berserker: best gear (level 50)"
    best = html.by_id("best-race").text()
    # 812.5 rounds half up; the headline goes on to name its view (the test of the margin has the whole sentence)
    assert best.startswith("Best race for this trio: Ogre (+813 over Troll)")
    note = html.by_id("best-race-note").text()
    assert "Iksar, if Iksar AC stacks inside the cap (test B17)" in note


def test_the_data_date_and_game_patch_are_on_every_page(site):
    out, _ = site
    for name in PAGES.values():
        strip = page(out, name).find(cls="data-strip").text()
        assert "Data: 2026-10-14" in strip, name
        assert "Game patch: 2026-09-22" in strip, name


def test_the_switches_are_native_labelled_controls_with_only_offered_options(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    race = html.by_id("sw-race")
    assert race.tag == "select"
    assert html.find("label", **{"for": "sw-race"}).text() == "Race"
    groups = race.find_all("optgroup")
    assert [g.get("label") for g in groups] == ["Available at character creation", "Needs a race or primary unlock"]
    legal = [o.get("value") for o in groups[0].find_all("option")]
    assert legal[0] == "OGR" and sorted(legal) == ["OGR", "TRL"]
    assert [o.get("value") for o in groups[1].find_all("option")] == ["ELF"]  # Wood Elf cannot start Paladin/Monk/Berserker
    assert "needs unlock" in groups[1].find("option").text()
    assert race.find("option", selected=True).get("value") == "OGR"
    assert "best" in race.find("option", value="OGR").text()
    roles = html.by_id("sw-role")
    assert roles.tag == "fieldset" and roles.find("legend").text() == "Role"
    radios = roles.find_all("input", type="radio")
    assert [r.get("value") for r in radios] == ["balanced", "tank", "melee"]
    assert radios[0].has("checked") and not radios[1].has("checked")
    for radio in radios:
        assert html.find("label", **{"for": radio.get("id")}).text() in ("Balanced", "Tank", "Melee")
    tier = html.by_id("sw-tier")
    assert [o.get("value") for o in tier.find_all("option")] == ["0", "4", "10"]
    assert tier.find("option", selected=True).get("value") == "4"
    assert tier.find("option", value="10").text() == "+10 (endgame)"


def test_a_role_never_offers_a_setup_it_has_no_scenario_for(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    offered = {r.get("value"): r.get("data-setups").split() for r in html.by_id("sw-role").find_all("input")}
    assert offered == {
        "balanced": ["1h-shield", "2h", "dw"],
        "tank": ["1h-shield", "2h", "dw"],
        "melee": ["2h", "dw"],
    }
    setups = {r.get("value"): r for r in html.find_all("input", name="setup")}
    assert sorted(setups) == ["1h-shield", "2h", "dw"]  # no "stick" radio: no role of this trio has it
    assert setups["dw"].has("checked")
    # the Balanced role (the default) shows its three; a hidden radio is also disabled so it cannot be reached
    assert not any(r.has("hidden") for r in setups.values())


def results_without_a_strict_shield(tmp_path: Path) -> Path:
    """The fixture's results as a run writes them when the strict pool has no shield the trio can wear: the strict shards have
    no 1h-shield rows, and the Tank, whose best setup that was, has the dual wield in its runner-ups. The wiki shards are as they
    were, so the wiki level still offers the shield setup."""
    scratch = tmp_path / "results"
    shutil.copytree(RESULTS, scratch)
    folder = scratch / "pal-mnk-ber"
    for name in ("strict-own", "strict-group"):
        path = folder / f"{name}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["scenarios"] = [row for row in document["scenarios"] if row[3] != "1h-shield"]
        document["setups"] = {role: [s for s in setups if s != "1h-shield"] for role, setups in document["setups"].items()}
        path.write_text(json.dumps(document), encoding="utf-8")
    path = folder / "runnerups" / "tank.json"  # (a view is [tier, race, setup, places])
    document = json.loads(path.read_text(encoding="utf-8"))
    for view in document["views"]:
        view[2] = "dw"
    path.write_text(json.dumps(document), encoding="utf-8")
    reindex(folder / "runnerups")
    return scratch


def test_a_setup_that_only_the_other_evidence_level_has_is_a_hidden_choice_not_a_missing_one(tmp_path):
    """The page is baked from the default level (here strict, which has no shield) and the page code shows the choices of
    whatever level is picked next, so the choice for the shield setup must be in the page, hidden, and the data files must not
    offer it for the strict level."""
    need_node()
    scratch = results_without_a_strict_shield(tmp_path)
    out = tmp_path / "dist"
    run_build(out, tmp_path, results=scratch)
    html = page(out, PAGES["trio"])
    assert html.find_all("input", name="ev") == []
    offered = {r.get("value"): r.get("data-setups").split() for r in html.by_id("sw-role").find_all("input")}
    assert offered == {"balanced": ["2h", "dw"], "tank": ["2h", "dw"], "melee": ["2h", "dw"]}  # what the default level has
    setups = {r.get("value"): r for r in html.find_all("input", name="setup")}
    assert sorted(setups) == ["1h-shield", "2h", "dw"]  # the wiki level has the setup, so the page has a choice for it ...
    shield = setups["1h-shield"]
    assert shield.has("hidden") and shield.has("disabled") and shield.parent.has("hidden")  # ... that is hidden and cannot be reached
    assert not shield.has("checked") and setups["dw"].has("checked") and not setups["dw"].has("hidden")
    assert [li.text() for li in html.by_id("w-others").find_all("li")][0].startswith("Two-hander: ")  # no shield line among the others
    assert not any(li.text().startswith("1H + shield") for li in html.by_id("w-others").find_all("li"))
    strict = json.loads(read(out, "data/pal-mnk-ber/strict-own.json"))
    wiki = json.loads(read(out, "data/pal-mnk-ber/wiki-own.json"))
    assert {row[3] for row in strict["rows"]} == {"2h", "dw"} and {row[3] for row in wiki["rows"]} == {"1h-shield", "2h", "dw"}


def test_the_label_of_a_setup_the_baked_level_lacks_goes_with_its_radio_button(tmp_path):
    """A choice that is out of the page is out whole: the radio button, its label and the box around both. The label sits in the box
    that carries the ``hidden`` attribute, and the stylesheet's ``[hidden]`` rule beats the ``display`` of the box and of the label,
    so no label is drawn without its control (tests-e2e/trio.spec.mjs looks at the same in a browser, with axe)."""
    need_node()
    scratch = results_without_a_strict_shield(tmp_path)
    out = tmp_path / "dist"
    run_build(out, tmp_path, results=scratch)
    html = page(out, PAGES["trio"])
    radios = html.find_all("input", name="setup")
    assert [r.get("value") for r in radios if r.has("hidden")] == ["1h-shield"]
    for radio in radios:
        box = radio.parent
        label = html.find("label", **{"for": radio.get("id")})
        assert "opt" in box.classes and label.parent is box, radio.get("id")  # one box holds the control and its label, and nothing else
        assert [c.tag for c in box.children if hasattr(c, "tag")] == ["input", "label"], radio.get("id")
        assert box.has("hidden") == radio.has("hidden"), radio.get("id")
        assert radio.has("disabled") or not radio.has("hidden"), radio.get("id")  # (the page code enables the others when it starts)
    shield = html.by_id("setup-1h-shield")
    assert html.find("label", **{"for": "setup-1h-shield"}) in shield.parent.children and shield.parent.has("hidden")
    # the box is drawn as inline-block and the label as inline-flex, which would show a hidden box: the [hidden] rule wins with !important
    assert "display: none !important" in rule_body(css_text(), "[hidden]")


def test_the_assumes_line_names_the_buffs_weapons_and_weights_each_with_a_change_control_and_says_nothing_of_evidence(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    summaries = [d.find("summary").text() for d in html.find_all("details", cls="assume")]
    assert summaries == [
        "Buffs: your own buffs change",
        "Weapons: dual wield, scored at 66% haste change",
        "Weights: role's own change",
    ]
    assert [i.get("value") for i in html.find_all("input", name="buffs")] == ["own", "group", "raid"]
    assert html.find_all("input", name="ev") == [] and not html.find_all("details", id_="assume-evidence")
    for details in html.find_all("details", cls="assume"):
        assert details.find("fieldset").find("legend").text() in ("Buffs", "Weapons", "Weights")
        assert not details.has("open")  # collapsed: one answer first


def test_alternatives_sit_behind_collapsed_expanders(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    main = html.find("main")
    expanders = main.find_all("details")
    assert expanders and not any(d.has("open") for d in expanders)
    ids = [d.get("id") for d in expanders if d.get("id")]
    assert {"runnerups", "robust", "other-setups"} <= set(ids)
    # the answer comes first: "Wear this" is the first section after the switches
    headings = [h.text() for h in main.find_all("h2")]
    assert headings.index("Wear this") < headings.index("Why this kit")
    assert main.find_all("table")[0].get("id") == "kit"


def test_why_this_kit_shows_totals_against_caps_with_seals_and_rules(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    why = html.by_id("totals-body")
    text = {r.find("th").text(): [c.text() for c in r.find_all("td")] for r in why.find_all("tr")}
    assert text["Sheet AC"][0] == "666"
    assert "439" in text["Sheet AC"][1]  # the softcap with Combat Stability and Physical Enhancement
    assert text["Haste"][0] == "57%" and "85" in text["Haste"][1]  # a Monk in the trio raises the cap to 85
    assert text["Magic resist"][0] == "86" and "200" in text["Magic resist"][1]
    assert text["Hit points"][0] == "2,880"
    links = [a.get("href") for a in why.find_all("a")]
    assert "/rules/#haste.cap_pct_with_monk" in links
    assert "/rules/#resist.cap" in links
    for seal in why.find_all(cls="seal"):
        assert seal.text() != ""
    assert html.by_id("kit-value").text() == "10,720"


def test_the_weapons_block_carries_the_model_seal(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    block = html.by_id("weapons")
    assert block.find(data_f="w-setup").text() == "Dual wield"
    assert block.find(data_f="w-main").text() == "Ferryman's Pike"
    assert block.find(data_f="w-off").text() == "Pellbrook Mallet"
    seal = block.find(cls="seal")
    assert seal.text() == "Model"
    assert block.find("a").get("href") == "/rules/#weapons.damage_weight"
    others = html.by_id("w-others").find_all("li")
    assert [li.text() for li in others] == [
        "1H + shield: Tinker's Awl + Orchard Warden's Targe (−140)",
        "Two-hander: Gristmill Maul (−85)",  # -85.5 rounds half up
    ]


def test_runner_ups_and_the_robust_core_are_baked_for_the_default_view(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    body = html.by_id("runnerups-body")
    rows = body.find_all("tr")
    assert len(rows) == 22
    filled = [r for r in rows if r.find_all("li")]
    assert filled
    assert any("Crown of the Tribunal" in r.text() and "Needs deity: The Tribunal" in r.text() for r in rows)
    chest = rows[13].text()
    assert "Mantle of the Faithful" in chest and "Needs deity: The Tribunal or Rodcet Nife" in chest
    head = rows[0].find_all("li")
    assert head[0].find(data_f="r-deity").text() == "Needs deity: The Tribunal"  # it is kept only if it beats the others: first
    assert head[0].find(data_f="r-name").text() == "Crown of the Tribunal" and head[0].find(data_f="r-delta").text() == "+7"
    assert [li.find(data_f="r-delta").text() for li in head[1:]] == ["−12", "−19"]  # the others can only lose value
    assert not head[1].find_all(data_f="r-deity") and rows[13].find_all("li")[0].find(data_f="r-delta").text() == "−9"
    assert html.by_id("runnerups").get("data-files").split() == ["balanced", "tank", "melee"]  # the file of each role holds every tier
    assert "default assumptions" in html.by_id("runnerups").find("p").text()
    robust = html.by_id("robust-summary").text()
    assert robust == "20 of 22 picks hold in every check. The other 2 depend on an assumption:"
    items = [li.text() for li in html.by_id("robust-list").find_all("li")]
    assert any(i.startswith("Waist: Riverstone Buckle Strap") and 'depends on the "AC" & mana weight (x2)' in i for i in items)


def test_every_trio_item_name_is_html_escaped_everywhere(site):
    out, _ = site
    for name in list(PAGES.values()):
        raw = read(out, name)
        assert "<b>x</b>" not in raw, name
        assert "<i>of</i>" not in raw, name
    raw = read(out, PAGES["trio"])
    assert "&lt;b&gt;x&lt;/b&gt;" in raw
    html = parse(raw)
    assert html.find_all("b") == [] and html.find_all("i") == []
    sources = read(out, PAGES["sources"])
    assert "<b>x</b>" not in sources and "&lt;b&gt;x&lt;/b&gt;" in sources


# ---- hygiene: scripts, styles, sources ---------------------------------------------------------------------------------------


def all_html(out: Path):
    for path in sorted(out.rglob("*.html")):
        yield path.relative_to(out).as_posix(), parse(path.read_text(encoding="utf-8"))


def test_no_inline_scripts_styles_event_handlers_or_javascript_urls(site):
    out, _ = site
    seen = 0
    for name, html in all_html(out):
        seen += 1
        for script in html.find_all("script"):
            assert script.has("src"), f"{name}: inline <script>"
            assert not script.children, f"{name}: <script src> with a body"
            assert script.get("type") in (None, "module"), f"{name}: unexpected script type"
        assert html.find_all("style") == [], f"{name}: <style>"
        for node in html.iter():
            assert "style" not in node.attrs, f"{name}: style attribute on {node!r}"
            for attr, value in node.attrs.items():
                assert not attr.startswith("on"), f"{name}: event handler {attr} on {node!r}"
                assert not (value or "").strip().lower().startswith("javascript:"), f"{name}: javascript: URL"
        for node in html.find_all("a") + html.find_all("link"):
            assert not (node.get("href") or "").lower().startswith("javascript:")
    pages = len(build.item_page_keys(json.loads((RESULTS / "items.json").read_text(encoding="utf-8"))))
    assert seen == len(PAGES) + 1 + pages  # the pages, 404.html and the page of each item (these are held to the same rules)


def test_every_script_stylesheet_and_image_is_same_origin(site):
    out, _ = site
    for name, html in all_html(out):
        for node in html.find_all("script"):
            assert node.get("src").startswith("/assets/"), (name, node)
        for node in html.find_all("link"):
            if node.get("rel") == "canonical":  # an address for search engines, not something the page loads
                continue
            href = node.get("href")
            assert href.startswith("/") or href.startswith("data:"), (name, node)
        assert html.find_all("img") == [] and html.find_all("iframe") == [] and html.find_all("object") == []
        assert html.find_all("form") == [], name  # form-action is 'none'
        for node in html.find_all("a"):
            href = node.get("href")
            if re.match(r"https?://", href):
                assert "noopener" in (node.get("rel") or ""), f"{name}: external link without rel=noopener: {href}"
    raw = "".join(read(out, n) for n in PAGES.values())
    assert "cloudflareinsights" not in raw and "googletagmanager" not in raw
    css = next((out / "assets").glob("site-*.css")).read_text(encoding="utf-8")
    assert "@import" not in css and "@font-face" not in css
    # the stylesheet loads nothing but the pictures of the theme: PNGs that esbuild copied beside it under a hash of their content (no address, no other kind of file)
    loaded = re.findall(r"url\(([^)]*)\)", css)
    assert loaded, "the theme's pictures are not in the stylesheet"
    for target in loaded:
        named = re.fullmatch(r'"\./([a-z0-9-]+-[A-Z0-9]{8}\.png)"', target)
        assert named and (out / "assets" / named.group(1)).is_file(), f"the stylesheet loads {target}"


def test_the_javascript_has_no_string_to_dom_sinks(site):
    out, _ = site
    sinks = re.compile(
        r"innerHTML|outerHTML|insertAdjacentHTML|document\s*\.\s*write|createContextualFragment|\beval\s*\(|"
        r"new\s+Function|setAttribute\(\s*[\"']on|srcdoc|DOMParser|execScript|importScripts|\.setTimeout\(\s*[\"']"
    )
    for path in sorted(STATIC.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        assert not sinks.search(text), f"{path.name}: {sinks.search(text).group(0)}"
    for path in sorted((out / "assets").glob("*.js")):
        text = path.read_text(encoding="utf-8")
        assert not sinks.search(text), f"{path.name}: {sinks.search(text).group(0)}"


def test_the_static_files_the_plan_names_exist():
    assert {f.name for f in STATIC.iterdir()} >= {"site.css", "app.js", "trio.js", "theme.js", "boot.js"}


# ---- the canonical link, noindex and the headers ---------------------------------------------------------------------------------


def test_every_page_has_a_unique_title_a_description_and_a_canonical_link(site):
    out, _ = site
    titles = []
    for key, name in PAGES.items():
        html = page(out, name)
        titles.append(html.find("title").text())
        canonical = html.find("link", rel="canonical").get("href")
        expected = SITE_URL + ("/" if name == "index.html" else "/" + name.removesuffix("index.html"))
        assert canonical == expected, key
        assert html.find("meta", name="description").get("content"), key
        assert html.find("html").get("lang") == "en"
    assert len(set(titles)) == len(titles)
    trio = page(out, PAGES["trio"])
    assert trio.find("title").text() == "Paladin / Monk / Berserker best gear, level 50 · TrioForge"
    description = trio.find("meta", name="description").get("content")
    assert "Ferryman's Pike" in description and len(description) <= 240


def test_an_indexable_build_has_a_sitemap_and_allows_robots(site):
    out, _ = site
    sitemap = read(out, "sitemap.xml")
    for path in ("", "trio/pal-mnk-ber/", "rules/", "sources/", "about/", "changelog/"):
        assert f"<loc>{SITE_URL}/{path}</loc>" in sitemap
    robots = read(out, "robots.txt")
    assert "Allow: /" in robots and f"Sitemap: {SITE_URL}/sitemap.xml" in robots and "Disallow: /\n" not in robots
    for _name, html in all_html(out):
        assert html.find_all("meta", name="robots") == []
    assert "noindex" not in read(out, "_headers")


def test_a_noindex_build_says_so_in_the_page_the_headers_and_robots(site_noindex):
    out = site_noindex
    for _name, html in all_html(out):
        assert html.find("meta", name="robots").get("content") == "noindex"
    headers = read(out, "_headers")
    assert "  X-Robots-Tag: noindex\n" in headers
    assert "Disallow: /" in read(out, "robots.txt")
    assert not (out / "sitemap.xml").exists()


ASSET_CACHE = "public, max-age=31536000, immutable"  # a year, and the file never changes under its name


def header_blocks(text: str) -> dict[str, dict[str, str]]:
    """The blocks of a ``_headers`` file as ``{path pattern: {header: value}}``, in file order. A header line is indented."""
    blocks: dict[str, dict[str, str]] = {}
    current = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):  # a blank line or a comment
            continue
        if line.startswith("  "):
            assert current is not None, f"a header before any path pattern: {line}"
            name, _, value = line.strip().partition(": ")
            assert name not in blocks[current], f"{name} twice under {current}"
            blocks[current][name] = value
        else:
            assert line not in blocks, f"{line} twice"
            current = line
            blocks[current] = {}
    return blocks


def test_the_headers_file_is_exactly_the_plans(site):
    out, _ = site
    text = read(out, "_headers")
    lines = text.splitlines()
    assert lines[0] == "/*"
    headers = header_blocks(text)["/*"]  # what every path gets; the block for /assets/* is checked below
    assert headers["Content-Security-Policy"] == CSP
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert sorted(headers) == [
        "Content-Security-Policy", "Permissions-Policy", "Referrer-Policy", "X-Content-Type-Options",
    ]  # fmt: skip
    features = [part.strip() for part in headers["Permissions-Policy"].split(",")]
    assert all(re.fullmatch(r"[a-z-]+=\(\)", f) for f in features), features  # every feature off
    assert {"camera=()", "microphone=()", "midi=()", "geolocation=()", "payment=()", "usb=()"} <= set(features)
    committed = (REPO / "site" / "_headers").read_text(encoding="utf-8")
    assert text == committed  # the build copies the committed file untouched


#: every feature the Permissions-Policy header switches off, in the order the header lists them (alphabetical). The site uses none of
#: them. Left out on purpose: clipboard-write, web-share and fullscreen-style features a share or copy button of a later phase may need
#: (fullscreen is off already), and cross-origin-isolated, which a solver that runs threads in the browser may need.
POLICY_FEATURES = [
    "accelerometer", "attribution-reporting", "autoplay", "bluetooth", "browsing-topics", "camera", "captured-surface-control",
    "clipboard-read", "compute-pressure", "digital-credentials-get", "display-capture", "encrypted-media", "fullscreen", "gamepad",
    "geolocation", "gyroscope", "hid", "identity-credentials-get", "idle-detection", "interest-cohort", "join-ad-interest-group",
    "keyboard-map", "local-fonts", "magnetometer", "microphone", "midi", "otp-credentials", "payment", "picture-in-picture",
    "private-aggregation", "private-state-token-issuance", "private-state-token-redemption", "publickey-credentials-create",
    "publickey-credentials-get", "run-ad-auction", "screen-wake-lock", "serial", "shared-storage", "shared-storage-select-url",
    "storage-access", "sync-xhr", "usb", "window-management", "xr-spatial-tracking",
]  # fmt: skip


def test_the_permissions_policy_switches_off_the_whole_current_list_in_one_short_enough_line(site):
    out, _ = site
    lines = [line for line in read(out, "_headers").splitlines() if line.strip().startswith("Permissions-Policy:")]
    assert len(lines) == 1  # one header, so that no later line can undo an earlier one
    names = [part.strip().removesuffix("=()") for part in lines[0].split(": ", 1)[1].split(",")]
    assert names == POLICY_FEATURES
    assert names == sorted(set(names))  # alphabetical, each once
    # the advertising interfaces a visitor's browser may offer a page (Topics, attribution reporting, the old cohort id) are off
    assert {"browsing-topics", "attribution-reporting", "interest-cohort", "join-ad-interest-group", "run-ad-auction", "shared-storage"} <= set(names)
    assert len(lines[0]) <= 2000, f"{len(lines[0])} characters: Cloudflare Pages reads at most 2,000 of a line of _headers"


def test_only_the_content_hashed_assets_are_cached_for_a_year(site):
    """The pages and the data files keep the host's default (the browser asks again on every visit, so a new release shows at
    once); the stylesheet and the scripts have a hash of their content in their names, so a copy never goes stale."""
    out, _ = site
    blocks = header_blocks(read(out, "_headers"))
    assert list(blocks) == ["/*", "/assets/*"]
    assert blocks["/assets/*"] == {"Cache-Control": ASSET_CACHE}
    assert build.ASSET_CACHE == ASSET_CACHE
    assert "Cache-Control" not in blocks["/*"]
    # every file under /assets/, in every sub-folder, has a hash of its content in its name: the year-long rule covers all of them
    found = sorted(p.relative_to(out / "assets").as_posix() for p in (out / "assets").rglob("*") if p.is_file())
    assert found and all(re.fullmatch(HASHED_ASSET, name) for name in found), found  # no name without a hash
    assert not [p for p in (out / "assets").rglob("*") if p.is_dir() and not any(q.is_file() for q in p.rglob("*"))]  # no empty folder


def rules_for(blocks: dict, path: str) -> dict:
    """The headers a host gives one path: every block whose pattern matches it (a pattern ends in * for "anything after this")."""
    given: dict = {}
    for pattern, headers in blocks.items():
        if pattern == path or (pattern.endswith("*") and path.startswith(pattern[:-1])):
            given.update(headers)
    return given


def test_the_manifest_is_outside_the_folder_that_is_cached_for_a_year(site):
    """The manifest is the one file of the optimizer whose name is the same in every release, so it must not sit under the rule for
    hashed files: a visitor would keep an old list of files for a year. It is at one fixed address and asked for again on every visit."""
    out, _ = site
    assert build.MANIFEST_FILE == MANIFEST_FILE
    assert (out / MANIFEST_FILE).is_file() and not (out / "assets" / "manifest.json").exists()
    blocks = header_blocks(read(out, "_headers"))
    assert "Cache-Control" not in rules_for(blocks, "/" + MANIFEST_FILE)
    assert rules_for(blocks, "/assets/engine/worker-BBBBBBBB.js") == {**blocks["/*"], "Cache-Control": ASSET_CACHE}  # the control: hashed files
    # the manifest names every other address of the optimizer, and those are the files that are kept
    manifest = engine_manifest(out)
    assert all(rules_for(blocks, manifest[role]["path"])["Cache-Control"] == ASSET_CACHE for role in ("client", "worker", "wasm"))


def test_the_noindex_header_goes_to_every_path_and_not_only_to_what_the_last_block_matches(site_noindex):
    text = read(site_noindex, "_headers")
    blocks = header_blocks(text)
    assert list(blocks) == ["/*", "/assets/*"]
    assert blocks["/*"].pop("X-Robots-Tag") == "noindex" and "X-Robots-Tag" not in blocks["/assets/*"]
    assert blocks["/assets/*"] == {"Cache-Control": ASSET_CACHE}
    committed = header_blocks((REPO / "site" / "_headers").read_text(encoding="utf-8"))
    assert blocks == committed  # the committed file, and that one header in the first block, nothing else


def test_the_csp_header_matches_what_the_pages_do():
    """No script-src host, no inline allowance, trusted types required: the policy this site is built for, nothing looser."""
    assert "unsafe-inline" not in CSP and "unsafe-eval" not in CSP.replace("wasm-unsafe-eval", "")
    assert build.CSP == CSP


def test_the_csp_names_the_one_trusted_types_policy_the_code_creates_and_no_other(site):
    """`require-trusted-types-for` only makes the browser refuse a plain string; without a `trusted-types` directive any script could still
    create a second policy, or a pass-through `default` one, and walk plain strings past it. The directive names the one policy of
    static/tt-policy.js: no other name, no wildcard, no `default`, no duplicates."""
    directives = dict(part.strip().split(" ", 1) for part in build.CSP.split(";") if part.strip())
    assert directives["require-trusted-types-for"] == "'script'"
    policy = re.search(r'POLICY_NAME = "([a-z]+)"', (STATIC / "tt-policy.js").read_text(encoding="utf-8")).group(1)
    assert directives["trusted-types"] == policy == "trioforge"
    assert not {"'allow-duplicates'", "*", "default", "'none'"} & set(directives["trusted-types"].split())
    out, _ = site
    blocks = header_blocks(read(out, "_headers"))
    assert blocks["/*"]["Content-Security-Policy"] == build.CSP
    # the policy is made in one place, the optimizer's client: a second bundle that made it would be refused as a duplicate
    for name in sorted(p.relative_to(out).as_posix() for p in (out / "assets").rglob("*.js")):
        made = "createPolicy" in read(out, name)
        assert made == name.startswith("assets/engine/client-"), name


# ---- the Jinja environment ------------------------------------------------------------------------------------------------------


def test_the_jinja_environment_escapes_and_refuses_undefined_values():
    env = build.make_env()
    assert env.autoescape is True
    assert env.from_string("{{ x }}").render(x="<b>x</b>") == "&lt;b&gt;x&lt;/b&gt;"
    assert env.from_string("<a title='{{ x }}'>").render(x="' onclick='1") == "<a title='&#39; onclick=&#39;1'>"
    import jinja2

    with pytest.raises(jinja2.UndefinedError):
        env.from_string("{{ missing }}").render()
    with pytest.raises(jinja2.UndefinedError):
        env.from_string("{{ x.missing }}").render(x={})


def test_no_template_turns_escaping_off():
    names = sorted(p.name for p in TEMPLATES.iterdir())
    assert names == [f"{n}.html.j2" for n in ("about", "base", "changelog", "home", "item", "notfound", "rules", "sources", "trio", "upgrade")]
    for path in TEMPLATES.iterdir():
        text = path.read_text(encoding="utf-8")
        assert "|safe" not in text and "| safe" not in text, path.name
        assert "autoescape" not in text and "Markup" not in text, path.name
        assert not re.search(r"<script(?![^>]*\bsrc=)", text), f"{path.name}: inline script"
        assert not re.search(r"\sstyle=|<style|\son[a-z]+=", text), f"{path.name}: inline style or handler"


# ---- the footer, the disclaimer and the name -----------------------------------------------------------------------------------


def test_every_page_carries_the_disclaimer_the_attribution_and_a_report_link(site):
    out, _ = site
    for key, name in PAGES.items():
        footer = page(out, name).find("footer")
        text = footer.text()
        assert DISCLAIMER in text, key
        assert ATTRIBUTION in text, key
        hrefs = [a.get("href") for a in footer.find_all("a")]
        assert "https://creativecommons.org/licenses/by-sa/4.0/legalcode" in hrefs
        assert "https://eqlwiki.com/" in hrefs
        report = next(h for h in hrefs if "/issues/new" in h)
        assert report.startswith(f"https://github.com/{OWNER}/trioforge/issues/new?")
    trio_report = next(a.get("href") for a in page(out, PAGES["trio"]).find("footer").find_all("a") if "/issues/new" in a.get("href"))
    query = parse_qs(urlparse(trio_report).query)
    assert query["template"] == ["wrong-item.yml"]
    assert query["page"] == [f"{SITE_URL}/trio/pal-mnk-ber/?race=OGR&role=balanced&tier=4&setup=dw&buffs=own"]  # with the view
    assert "Paladin / Monk / Berserker" in query["title"][0]
    assert parse_qs(urlparse(next(a.get("href") for a in page(out, PAGES["rules"]).find("footer").find_all("a") if "/issues/new" in a.get("href"))).query)["template"] == ["rule-correction.yml"]


def report_query(out, name):
    """The query of the link in the footer of a page that reports a problem with it."""
    footer = page(out, name).find("footer")
    link = footer.by_id("report-link")
    assert link.get("href") in [a.get("href") for a in footer.find_all("a")] and link.text() == "Report a problem with this page"
    return parse_qs(urlparse(link.get("href")).query)


def test_the_report_link_of_the_trio_page_carries_the_view_it_opens_on(site):
    out, _ = site
    query = report_query(out, PAGES["trio"])
    assert query["template"] == ["wrong-item.yml"]
    address = urlparse(query["page"][0])
    assert f"{address.scheme}://{address.netloc}{address.path}" == f"{SITE_URL}/trio/pal-mnk-ber/"  # the trio is in the address
    # race, role, tier, weapons and buffs, all of them (the weapons even where they are the role's best), in this order; no evidence: wiki is the one level
    assert parse_qsl(address.query) == [("race", "OGR"), ("role", "balanced"), ("tier", "4"), ("setup", "dw"), ("buffs", "own")]
    assert "Paladin / Monk / Berserker" in query["title"][0]


def test_the_report_link_of_every_other_page_uses_the_general_form_and_names_no_view(site):
    out, _ = site
    for key in ("home", "sources", "about", "changelog"):
        query = report_query(out, PAGES[key])
        assert query["template"] == ["page-problem.yml"], key  # not the form about a wrong item
        assert query["page"] == [SITE_URL + "/" + PAGES[key].removesuffix("index.html")], key  # the page itself, nothing about a view
    assert report_query(out, NOT_FOUND)["template"] == ["page-problem.yml"]
    assert report_query(out, PAGES["rules"])["template"] == ["rule-correction.yml"]  # a rule has a form of its own
    for template in ("page-problem.yml", "wrong-item.yml", "rule-correction.yml"):
        assert (REPO / ".github" / "ISSUE_TEMPLATE" / template).is_file(), f"the link names {template}, which does not exist"


def test_the_disclaimer_and_attribution_match_the_repository_notices():
    notice = (REPO / "NOTICE.md").read_text(encoding="utf-8")
    licence = (REPO / "LICENSE-DATA").read_text(encoding="utf-8")
    assert DISCLAIMER in notice
    assert ATTRIBUTION in licence
    assert build.DISCLAIMER == DISCLAIMER and build.ATTRIBUTION == ATTRIBUTION


def test_the_site_name_and_logo_do_not_use_the_games_name(site):
    out, _ = site
    for key, name in PAGES.items():
        html = page(out, name)
        header = html.find("header", cls="site-header")
        assert "everquest" not in header.text().lower(), key
        assert header.find(cls="brand").text() == "TrioForge"
        assert "everquest" not in html.find("title").text().lower(), key
        for icon in html.find_all("link", rel="icon"):
            assert "everquest" not in icon.get("href").lower()


# ---- accessibility ----------------------------------------------------------------------------------------------------------------


def test_every_page_has_a_skip_link_landmarks_and_one_h1(site):
    out, _ = site
    for key, name in PAGES.items():
        html = page(out, name)
        body = html.find("body")
        first = next(n for n in body.iter() if n.tag in ("a", "button", "input", "select", "summary"))
        assert first.tag == "a" and first.get("href") == "#main" and "skip-link" in first.classes, key
        assert html.find("main").get("id") == "main" and html.find("main").get("tabindex") == "-1"
        assert len(html.find_all("h1")) == 1, key
        assert html.find("header", cls="site-header") and html.find("footer")
        assert html.find("nav").get("aria-label"), key
        ids = [n.get("id") for n in html.iter() if n.has("id")]
        assert len(ids) == len(set(ids)), (key, [i for i in ids if ids.count(i) > 1])
        heading_levels = [int(h.tag[1]) for h in html.iter() if re.fullmatch(r"h[1-6]", h.tag)]
        assert heading_levels[0] == 1
        assert all(b - a <= 1 for a, b in zip(heading_levels, heading_levels[1:])), (key, heading_levels)


def test_tables_have_captions_and_scoped_headers(site):
    out, _ = site
    for key, name in PAGES.items():
        for table in page(out, name).find_all("table"):
            assert table.find("caption") is not None, (key, table)
            for th in table.find_all("th"):
                assert th.get("scope") in ("col", "row"), (key, th)


def test_every_control_has_a_label_and_the_decorative_icons_are_hidden(site):
    out, _ = site
    for key, name in PAGES.items():
        html = page(out, name)
        labels = {label.get("for") for label in html.find_all("label") if label.has("for")}
        for control in html.find_all("input") + html.find_all("select"):
            assert control.get("id") in labels, (key, control)
        for fieldset in html.find_all("fieldset"):
            assert fieldset.find("legend") is not None
        for svg in html.find_all("svg"):
            if svg.parent.tag != "body":  # the sprite itself is hidden as a whole
                assert svg.get("aria-hidden") == "true", (key, svg)
        for button in html.find_all("button"):
            assert button.get("type") == "button" and button.text() != ""


def test_seals_are_icon_plus_text_never_colour_alone(site):
    out, _ = site
    for key, name in PAGES.items():
        for seal in page(out, name).find_all(cls="seal"):
            assert seal.text(skip_hidden=False) != "", (key, seal)
            assert seal.find("svg") is not None, (key, seal)


def test_the_status_message_region_is_a_polite_live_region(site):
    out, _ = site
    status = page(out, PAGES["trio"]).by_id("status")
    assert status.get("role") == "status" and status.get("aria-live") == "polite"
    assert page(out, PAGES["trio"]).find("noscript") is not None


def luminance(hex_colour: str) -> float:
    value = hex_colour.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def token_blocks(css: str) -> dict[str, dict[str, str]]:
    """The custom-property blocks of site.css: light (:root, also what a light toggle gives), dark by system, dark by toggle."""
    def block(selector: str) -> dict[str, str]:
        match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert match, f"no block for {selector}"
        return dict(re.findall(r"(--[a-z-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", match.group(1)))

    return {
        "light": block(":root"),
        "dark-system": block(':root:not([data-theme="light"])'),
        "dark-toggle": block(':root[data-theme="dark"]'),
    }


TEXT_PAIRS = [
    ("--text", "--bg"), ("--text", "--surface"), ("--muted", "--bg"), ("--muted", "--surface"), ("--muted", "--tint"),
    ("--accent", "--bg"), ("--accent", "--surface"), ("--accent", "--tint"), ("--on-accent", "--accent-fill"),
    ("--text", "--tint"),
]  # fmt: skip
UI_PAIRS = [("--control", "--surface"), ("--control", "--bg"), ("--focus", "--bg"), ("--focus", "--surface")]


@pytest.mark.parametrize("theme", ["light", "dark-system", "dark-toggle"])
def test_colour_contrast_meets_wcag_aa_in_every_theme(theme):
    css = (STATIC / "site.css").read_text(encoding="utf-8")
    tokens = token_blocks(css)[theme]
    for foreground, background in TEXT_PAIRS:
        ratio = contrast(tokens[foreground], tokens[background])
        assert ratio >= 4.5, f"{theme}: {foreground} on {background} is {ratio:.2f}:1"
    for foreground, background in UI_PAIRS:
        ratio = contrast(tokens[foreground], tokens[background])
        assert ratio >= 3.0, f"{theme}: {foreground} on {background} is {ratio:.2f}:1"


def test_the_two_dark_blocks_agree_and_the_two_themes_define_the_same_tokens():
    tokens = token_blocks((STATIC / "site.css").read_text(encoding="utf-8"))
    assert tokens["dark-system"] == tokens["dark-toggle"]
    assert set(tokens["light"]) == set(tokens["dark-toggle"])


def test_the_stylesheet_shows_focus_respects_reduced_motion_and_wraps_long_names():
    css = (STATIC / "site.css").read_text(encoding="utf-8")
    assert ":focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css and "transition: none" in css.replace("!important", "")
    assert "prefers-color-scheme: dark" in css
    assert "overflow-wrap: anywhere" in css
    assert "[hidden]" in css
    assert not re.search(r"outline:\s*(none|0)\b", css)
    # system fonts only: the stacks of the theme (Verdana, and a serif for the headings) end in a generic family, and the page loads no font
    families = re.findall(r"font-family:\s*([^;]+);", css)
    assert families and all(re.search(r"(?:sans-serif|serif|monospace)\s*$", family.strip()) for family in families), families
    assert "@font-face" not in css and "fonts.googleapis" not in css


def test_no_text_container_is_set_not_to_wrap_and_the_tables_stack_under_600_px():
    """A bare `tbody th` with white-space: nowrap once made the sources table 750 px wide on a phone; keep nowrap to the
    short cells (slot names, the tier, seals, figures) and let everything else wrap."""
    css = (STATIC / "site.css").read_text(encoding="utf-8")
    selectors = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        if re.search(r"white-space:\s*nowrap", match.group(2)):
            selectors += [part.strip() for part in match.group(1).split(",")]
    generic = {"th", "td", "tbody th", "thead th", "table", "a", "li", "p", "dd", "dt", "body", "main", "code", "h1", "h2", "h3"}
    assert generic.isdisjoint(selectors), sorted(generic & set(selectors))
    assert "@media (max-width: 37.5rem)" in css  # stacked cards under 600 px


def test_the_boot_script_is_a_classic_script_and_the_app_a_module(site):
    out, _ = site
    boot = next((out / "assets").glob("boot-*.js")).read_text(encoding="utf-8")
    app = next((out / "assets").glob("app-*.js")).read_text(encoding="utf-8")
    assert not re.search(r"\b(import|export)\b", boot), "boot.js runs as a classic script in the head"
    assert len(boot) < 1500
    trio = page(out, PAGES["trio"])
    scripts = trio.find_all("script")
    assert [(s.get("src").split("-")[0], s.get("type")) for s in scripts] == [("/assets/boot", None), ("/assets/app", "module")]
    head, body = trio.find("head"), trio.find("body")
    assert scripts[0] in head.children and scripts[1] in body.children  # the boot script blocks the first paint, the app does not
    assert "trioforge-theme" in boot and "trioforge-theme" in app  # one key, in both
    assert "history.replaceState" in app.replace(" ", "") or "replaceState" in app


def test_every_internal_link_and_fragment_resolves(site):
    """A link check over the built site: each local link reaches a page or file, each #fragment an id."""
    out, _ = site
    pages = {name: parse(read(out, name)) for name in PAGES.values()}
    ids = {name: {n.get("id") for n in html.iter() if n.has("id")} for name, html in pages.items()}
    checked = 0
    for name, html in pages.items():
        for link in html.find_all("a") + html.find_all("link"):
            href = link.get("href")
            if not href.startswith("/"):
                continue
            path, _, fragment = href.partition("#")
            target = (path.lstrip("/") + "index.html") if path.endswith("/") or not path else path.lstrip("/")
            assert (out / target).is_file(), f"{name}: {href} leads nowhere"
            if fragment:
                assert fragment in ids[target], f"{name}: {href} has no such id"
            checked += 1
    assert checked > 60


def test_a_second_trio_gets_its_own_page_and_the_home_page_lists_both(tmp_path):
    need_node()
    scratch = tmp_path / "results"
    shutil.copytree(RESULTS, scratch)
    second = scratch / "pal-shd-ber"  # Wood Elf cannot start any of these either, so the fixture's default race still holds
    shutil.copytree(scratch / "pal-mnk-ber", second)
    for path in second.rglob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "engine-l50.json":  # the bundle names its trio as three class codes, twice
            document["trio"] = document["profile_common"]["trio"] = ["PAL", "SHD", "BER"]
        else:
            document["trio"] = "pal-shd-ber"
        path.write_text(json.dumps(document), encoding="utf-8")
    reindex(second / "runnerups")  # the runner-up files changed, so their index follows
    out = tmp_path / "dist"
    run_build(out, tmp_path, results=scratch)
    assert (out / "trio" / "pal-shd-ber" / "index.html").is_file()
    assert (out / "data" / "pal-shd-ber" / "strict-own.json").is_file()
    home = page(out, PAGES["home"])
    assert [a.get("href") for a in home.by_id("live-trios").find_all("a")] == ["/trio/pal-mnk-ber/", "/trio/pal-shd-ber/"]
    assert home.by_id("picker").get("data-live") == "pal-mnk-ber pal-shd-ber"
    second_page = page(out, "trio/pal-shd-ber/index.html")
    assert second_page.find("h1").text() == "Paladin / Shadow Knight / Berserker: best gear (level 50)"
    assert second_page.by_id("totals-body").find_all("tr")[4].find("td").text() == "57%"
    assert "75%" in second_page.by_id("totals-body").find_all("tr")[4].text()  # no Monk: the haste cap is 75, not 85
    assert "/trio/pal-shd-ber/" in read(out, "sitemap.xml")


def test_a_headers_file_with_another_policy_is_refused():
    text = (REPO / "site" / "_headers").read_text(encoding="utf-8")
    loose = text.replace("script-src 'self'", "script-src 'self' https://cdn.example")
    with pytest.raises(build.BuildError, match="Content-Security-Policy"):
        build.render_headers(loose, noindex=False)
    with pytest.raises(build.BuildError, match="path pattern"):
        build.render_headers("/page\n  X-Test: 1\n", noindex=False)
    assert build.render_headers(text, noindex=False) == text
    first, rest = text.split("\n\n", 1)  # the noindex header is for every path: it goes into the first block, not to the file's end
    assert build.render_headers(text, noindex=True) == first + "\n  X-Robots-Tag: noindex\n\n" + rest
    alone = first + "\n"  # a file with that block alone gets the line at its end
    assert build.render_headers(alone, noindex=True) == alone + "  X-Robots-Tag: noindex\n"


def test_a_comment_in_the_headers_file_is_neither_a_block_nor_a_header():
    text = (REPO / "site" / "_headers").read_text(encoding="utf-8")
    first, rest = text.split("\n\n", 1)
    commented = first + "\n  # a note inside the first block\n\n# the files under /assets/ have a hash in their names\n" + rest
    rendered = build.render_headers(commented, noindex=True)
    blocks = header_blocks(rendered)
    assert list(blocks) == ["/*", "/assets/*"] and blocks["/assets/*"] == {"Cache-Control": ASSET_CACHE}
    assert blocks["/*"].pop("X-Robots-Tag") == "noindex" and blocks["/*"] == header_blocks(text)["/*"]
    assert "# a note inside the first block" in rendered  # comments are kept as they were written


def test_a_headers_file_that_would_cache_the_pages_or_the_data_is_refused():
    text = (REPO / "site" / "_headers").read_text(encoding="utf-8")
    first, rest = text.split("\n\n", 1)
    for cache in (ASSET_CACHE, "public, max-age=60"):  # on every path, the pages and the data would go stale
        everywhere = first + f"\n  Cache-Control: {cache}\n\n" + rest
        with pytest.raises(build.BuildError, match="Cache-Control"):
            build.render_headers(everywhere, noindex=False)
    with pytest.raises(build.BuildError, match="Cache-Control"):  # the assets get the one value the site is built for
        build.render_headers(text.replace("max-age=31536000", "max-age=60"), noindex=False)
    with pytest.raises(build.BuildError, match="Cache-Control"):  # a rule for another folder that sets one
        build.render_headers(text + "\n/data/*\n  Cache-Control: public, max-age=31536000\n", noindex=False)
    with pytest.raises(build.BuildError, match="Content-Security-Policy"):  # the policy must protect every path, not just the assets
        build.render_headers("/*\n  X-Test: 1\n\n/assets/*\n" + "  " + first.splitlines()[1].strip() + "\n", noindex=False)


def test_the_site_address_decides_the_canonical_links_and_the_sitemap(tmp_path):
    need_node()
    out = tmp_path / "dist"
    run_build(out, tmp_path, site_url="https://example.org/preview/")
    assert page(out, PAGES["rules"]).find("link", rel="canonical").get("href") == "https://example.org/preview/rules/"
    assert "<loc>https://example.org/preview/trio/pal-mnk-ber/</loc>" in read(out, "sitemap.xml")
    assert "Sitemap: https://example.org/preview/sitemap.xml" in read(out, "robots.txt")


def test_the_site_address_of_the_command_line_loses_every_trailing_slash(tmp_path, capsys):
    need_node()
    out = tmp_path / "dist"
    code = build.main(
        [
            "--results", str(complete_copy(RESULTS, tmp_path)), "--out", str(out), "--site-url", "https://example.org/preview//",
            "--owner", OWNER, "--sources-manifest", str(MANIFEST), "--changelog", str(make_changelog(tmp_path)),
        ],
        scopes=FIXTURE_SCOPES,
    )  # fmt: skip
    assert code == 0, capsys.readouterr().err
    assert page(out, PAGES["rules"]).find("link", rel="canonical").get("href") == "https://example.org/preview/rules/"
    assert "<loc>https://example.org/preview/</loc>" in read(out, "sitemap.xml")
    assert "<loc>https://example.org/preview//" not in read(out, "sitemap.xml")
    assert "Sitemap: https://example.org/preview/sitemap.xml\n" in read(out, "robots.txt")
    report = report_query(out, PAGES["trio"])
    assert report["page"][0].startswith("https://example.org/preview/trio/pal-mnk-ber/?"), report["page"]


def test_the_sitemap_gives_the_data_date_as_the_date_of_every_page(site, results):
    out, _ = site
    entries = re.findall(r"<url><loc>([^<]*)</loc><lastmod>([^<]*)</lastmod></url>", read(out, "sitemap.xml"))
    assert len(entries) == 6 and {date for _, date in entries} == {results.meta.data_date} == {"2026-10-14"}


@pytest.mark.parametrize("not_a_date", ["2026-02-30", "2026-13-01", "20261014", "2026-10-14\n", "2026-1-4", "yesterday", "", " 2026-10-14", "２０２６-10-14"])
def test_a_data_date_that_is_not_a_calendar_date_is_not_put_into_the_sitemap(tmp_path, monkeypatch, not_a_date):
    """The reader has looked at the date already; the build looks again at the one thing it writes for a crawler to read."""
    import dataclasses

    real = data.load_trio

    def reads_another_date(folder):
        results = real(folder)
        return dataclasses.replace(results, meta=dataclasses.replace(results.meta, data_date=not_a_date))

    monkeypatch.setattr(data, "load_trio", reads_another_date)
    with pytest.raises(build.BuildError, match="data date"):
        run_build(tmp_path / "dist", tmp_path)  # (stops before the page code is bundled, so this needs no Node)
    assert not (tmp_path / "dist").exists()


def test_a_runner_up_view_for_another_setup_than_the_roles_best_is_not_baked_in(tmp_path):
    """Runner-ups are for the role's best setup. If a file says otherwise, the page says they are not available."""
    need_node()
    scratch = tmp_path / "results"
    shutil.copytree(RESULTS, scratch)
    folder = scratch / "pal-mnk-ber" / "runnerups"
    target = folder / "balanced.json"
    document = json.loads(target.read_text(encoding="utf-8"))
    next(v for v in document["views"] if v[:2] == [4, "OGR"])[2] = "2h"
    target.write_text(json.dumps(document), encoding="utf-8")
    reindex(folder)
    out = tmp_path / "dist"
    run_build(out, tmp_path, results=scratch)
    html = page(out, PAGES["trio"])
    assert not html.by_id("runnerups-na").has("hidden") and html.by_id("runnerups-table").has("hidden")


# ---- the other pages ----------------------------------------------------------------------------------------------------------------


def test_the_rules_page_lists_every_rule_with_its_seal_source_and_open_test(site):
    out, _ = site
    html = page(out, PAGES["rules"])
    rules = json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))["rules"]
    for rule in rules:
        node = html.by_id(rule["id"])
        assert rule["title"] in node.text()
        assert {"client": "Client file", "developer": "Developer", "measured": "Measured", "player": "Player reports", "model": "Model"}[rule["seal"]] in node.text()
    legend = html.by_id("seal-legend").text()
    for label in ("Client file", "Developer", "Measured", "Player reports", "Model"):
        assert label in legend
    cap = html.by_id("haste.cap_pct")
    assert "75" in cap.text() and "Player reports" in cap.text()
    assert "Maintainer's private observation" in html.by_id("naked.cap").text()
    raw = read(out, PAGES["rules"])
    assert "private-measured" not in raw and "private-player" not in raw
    open_tests = html.by_id("open-tests").find_all("a")
    expected = sorted(r["id"] for r in rules if r["status"] == "open")
    assert sorted(a.get("href").removeprefix("#") for a in open_tests) == expected
    assert any(a.text().startswith("B1") for a in open_tests)
    assert not any(a.text().startswith("B4") for a in open_tests)  # B4 was done: mana.wis_bands is settled
    assert "https://github.com/EQEmu/Server" in [a.get("href") for a in html.by_id("hp.sta_curve").find_all("a")]


def test_the_rules_page_shows_alternatives_for_open_rules(site):
    out, _ = site
    node = page(out, PAGES["rules"]).by_id("monk.weight_curve")
    assert "Open" in node.text() and "B9" in node.text()
    assert "34" in node.text()  # the alternative value


def test_the_rules_page_shows_the_settled_mana_curve_with_its_source_and_no_open_test(site):
    out, _ = site
    node = page(out, PAGES["rules"]).by_id("mana.wis_bands")
    text = node.text()
    assert "Measured" in text and "Maintainer's private observation" in text and "2026-10-27" in text
    assert "1.25" in text and "0.654" not in text  # the value; the flatter reading is ruled out and not listed
    assert "Open" not in text and "B4" not in text
    assert "https://github.com/EQEmu/Server" in [a.get("href") for a in node.find_all("a")]


#: the note the site says wherever it explains tiers or says that an item is shown at its tier (rules page, item pages, trio page)
TIER_PROGRESS_NOTE = "An item's stats and weight change gradually as it progresses toward its next tier. Each item is shown exactly at its tier."


def test_the_rules_page_shows_the_weight_rule_as_settled_by_in_game_readings_with_no_public_page_as_its_source(site):
    out, _ = site
    html = page(out, PAGES["rules"])
    node = html.by_id("tier.weight_pct")
    text = node.text()
    assert "Measured" in text and "Maintainer's private observation" in text and "2026-11-09" in text
    assert "Value: 9" in text and "percent of the base weight per tier" in text
    assert "Player reports" not in text and "Open" not in text
    assert node.find_all("a") == []  # no address is a source of it any more
    assert "xm2514" not in node.text() and "eqlwiki.com" not in node.text()
    assert "progress toward the next tier" in text.lower() and "The rounding of the last tenth of a stone is not settled." in text
    # the other rules that cite the two public pages keep them
    hrefs = [a.get("href") for a in html.by_id("tier.weapon_damage_pct").find_all("a")]
    assert "https://eqlwiki.com/index.php/Item_Upgrade_System" in hrefs
    # the rule's own anchor still works from the item and trio pages
    assert html.by_id("tier.weight_floor").find_all("a")


def test_the_rules_page_says_that_stats_and_weight_change_between_tiers_and_that_items_are_shown_at_a_tier(site):
    out, _ = site
    html = page(out, PAGES["rules"])
    note = html.by_id("tier-progress")
    assert note.text() == TIER_PROGRESS_NOTE
    section = next(s for s in html.find_all("section") if s.get("aria-labelledby") == "group-tier")
    assert note in section.find_all("p")  # under the heading of the tiers, with the rules that are about them
    assert [n for n in html.iter() if n.tag == "p" and n.text() == TIER_PROGRESS_NOTE] == [note]  # said once on the page


def test_the_trio_page_says_it_under_the_stats_of_the_kit(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    line = html.by_id("kit-stats-rules").text()
    assert "Each item's stats are at the tier shown." in line and TIER_PROGRESS_NOTE in line


def wiki_link(row):
    """The link to the wiki revision in a row of the table of revisions (the title of the row is a link to the page of the item as well, so it is not the first link)."""
    return next(a for a in row.find_all("a") if a.get("href").startswith("https://eqlwiki.com/"))


def test_the_sources_page_credits_the_wiki_and_lists_the_revisions_of_the_items_shown(site, results):
    out, _ = site
    html = page(out, PAGES["sources"])
    text = html.find("main").text()
    assert ATTRIBUTION in text
    assert "quest giver data compiled by EQL Tools" in text  # the catalog's own attribution line
    assert "Data: 2026-10-14" in html.find(cls="data-strip").text()
    table = html.by_id("revisions")
    rows = table.find("tbody").find_all("tr")
    titles = [r.find("th").text() for r in rows]
    assert titles == sorted(titles, key=str.lower)
    assert "Copperleaf Sash" in titles and "<b>x</b>" in titles
    assert "Fennick's Spoon" not in titles and "Ledgerkeeper's Tin" not in titles  # in the manifest, not on any page
    sash = next(r for r in rows if r.find("th").text() == "Copperleaf Sash")
    assert wiki_link(sash).get("href") == "https://eqlwiki.com/index.php?title=Copperleaf_Sash&oldid=200102"
    assert sash.find_all("td")[0].text() == "200102"
    hostile = next(r for r in rows if r.find("th").text() == "<b>x</b>")
    assert wiki_link(hostile).get("href").startswith("https://eqlwiki.com/index.php?title=%3Cb%3Ex%3C%2Fb%3E&oldid=")
    shown = {i.key for s in results.shards.values() for i in s.items} | {i.key for i in results.runnerups.items}
    assert len(rows) == len(shown)


def test_the_sources_page_names_the_licences_and_the_client_file_exception(site):
    out, _ = site
    text = page(out, PAGES["sources"]).find("main").text()
    assert "CC BY-SA 4.0" in text and "MIT" in text
    assert "fall outside" in text  # the game facts are Daybreak's and outside the data licence
    assert "EQEmu" in text


def test_a_shown_item_missing_from_the_manifest_stops_the_build(tmp_path):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    del manifest["items"]["w8091"]
    broken = tmp_path / "manifest.json"
    broken.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(build.BuildError, match="w8091"):
        run_build(tmp_path / "dist", tmp_path, sources_manifest=broken)


def test_the_about_page_has_the_disclaimer_privacy_and_contact(site):
    out, _ = site
    html = page(out, PAGES["about"])
    headings = [h.text() for h in html.find("main").find_all("h2")]
    assert headings == ["What this is", "A fan project", "Privacy", "Contact"]
    text = html.find("main").text()
    assert DISCLAIMER in text
    assert "no analytics" in text.lower() and "cookies" in text.lower()
    assert "local storage" in text.lower()
    assert any(f"github.com/{OWNER}/trioforge/issues" in a.get("href") for a in html.find("main").find_all("a"))


def test_the_changelog_page_renders_markdown_safely(site):
    out, _ = site
    html = page(out, PAGES["changelog"])
    main = html.find("main")
    assert [h.text() for h in main.find_all("h2")] == ["Unreleased", "Earlier"]
    items = [li.text() for li in main.find_all("li")]
    assert items[0] == "First milestone preview: the pal-mnk-ber page."
    assert main.find("strong").text() == "milestone" and main.find("code").text() == "pal-mnk-ber"
    link = main.find("a", href="https://example.org/rules")
    assert link.text() == "the rules" and "noopener" in link.get("rel")
    raw = read(out, PAGES["changelog"])
    assert "<script>alert(1)</script>" not in raw and "&lt;script&gt;alert(1)&lt;/script&gt;" in raw
    assert main.find_all("b") == []


def test_a_missing_changelog_gives_an_honest_empty_page(tmp_path):
    need_node()
    out = tmp_path / "dist"
    run_build(out, tmp_path, changelog=tmp_path / "nope.md")
    assert "No releases yet" in page(out, PAGES["changelog"]).find("main").text()


def test_the_home_page_has_a_picker_where_only_the_live_trio_opens(site):
    out, _ = site
    html = page(out, PAGES["home"])
    live = html.by_id("live-trios")
    assert [(a.get("href"), a.text()) for a in live.find_all("a")] == [
        ("/trio/pal-mnk-ber/", "Paladin / Monk / Berserker: best gear (level 50)")
    ]
    assert "coming soon" in html.find("main").text().lower()
    picker = html.by_id("picker")
    boxes = picker.find_all("input", type="checkbox")
    assert [b.get("value") for b in boxes] == list(CLASS_CODES)  # EQ class-id order
    assert [html.find("label", **{"for": b.get("id")}).text() for b in boxes] == list(CLASS_NAMES.values())
    assert picker.has("hidden")  # without JavaScript the picker is not offered
    assert picker.get("data-live") == "pal-mnk-ber"
    assert html.by_id("picker-status").get("role") == "status"


# ---- budgets ---------------------------------------------------------------------------------------------------------------------------


def gz(data_bytes: bytes) -> int:
    return len(gzip.compress(data_bytes, 9, mtime=0))


def test_the_page_budgets_hold(site):
    out, summary = site
    trio_html = (out / PAGES["trio"]).read_bytes()
    assert len(trio_html) <= build.LIMITS["trio_html"] == 66 * 1024, len(trio_html)
    trio = page(out, PAGES["trio"])
    scripts = [out / s.get("src").lstrip("/") for s in trio.find_all("script")]
    sheets = [out / s.get("href").lstrip("/") for s in trio.find_all("link", rel="stylesheet")]
    assert scripts and sheets
    first_load_js = sum(gz(p.read_bytes()) for p in scripts)
    assert first_load_js <= 30 * 1024, first_load_js
    # the script is two budgets: what the page loads by itself, and what it loads on first use (the chunks of the Upgrade section: each has a budget of its own, and all of them one)
    first_load_raw = sum(p.stat().st_size for p in scripts)
    assert first_load_raw <= 100 * 1024, first_load_raw
    lazy = [p for p in (out / "assets").glob("*.js") if p not in scripts and not p.name.startswith("notfound-")]  # (the script of the 404 page is the first load of that page, not code loaded on first use)
    assert {p.name.split("-")[0] for p in lazy} == {"upgrade", "shared", "weights", "exalt", "chunk"}  # (the section's, the panel of a shared kit, the sliders', the effects', and what they share: how many chunks esbuild makes of that is its own)
    for chunk in lazy:
        assert chunk.stat().st_size <= 100 * 1024, chunk.name
        assert gz(chunk.read_bytes()) <= 40 * 1024, chunk.name
    assert sum(p.stat().st_size for p in lazy) <= 250 * 1024, lazy
    for shard in (out / "data" / "pal-mnk-ber").glob("*-*.json"):
        assert shard.stat().st_size <= 200 * 1024, shard.name  # a shard may be 200 KB raw ...
        assert gz(shard.read_bytes()) <= 50 * 1024, shard.name  # ... and 50 KB gzipped
    first_load = gz(trio_html) + first_load_js + sum(gz(p.read_bytes()) for p in sheets)
    assert first_load <= 60 * 1024, first_load  # a trio page's first load, WebAssembly excluded
    assert summary.sizes["trio_html"] == len(trio_html)
    assert summary.sizes["first_load_js_gzip"] == first_load_js
    assert summary.sizes["first_load_js"] == first_load_raw
    assert summary.sizes["first_load_gzip"] == first_load
    largest = max(gz(p.read_bytes()) for p in (out / "data" / "pal-mnk-ber").glob("*-*.json"))
    assert summary.sizes["largest_shard_gzip"] == largest
    runnerups = sorted((out / "data" / "pal-mnk-ber" / "runnerups").glob("*.json"))
    assert [p.name for p in runnerups] == ["balanced.json", "melee.json", "tank.json"]  # one for each role, every tier in it
    for path in runnerups:
        assert path.stat().st_size <= 200 * 1024 and gz(path.read_bytes()) <= 50 * 1024, path.name  # the budget of a shard holds for it too
    assert summary.sizes["largest_runnerup"] == max(p.stat().st_size for p in runnerups)
    assert summary.sizes["largest_runnerup_gzip"] == max(gz(p.read_bytes()) for p in runnerups)
    assert summary.sizes["first_view_gzip"] == first_load + largest  # the weight of a first switch, the shard counted gzipped


def test_the_section_get_these_first_is_a_closed_summary_and_an_empty_container_directly_below_wear_this(site):
    # the trio page has little room under its size limit: the section is a summary and an empty container, which the page script fills (static/trio.js: paintCommon).
    # It is below the answer, never above it: docs/DECISIONS.md says "Wear this" and its first row are on the first screen of a phone.
    out, _ = site
    html = read(out, PAGES["trio"])
    block = '<details class="expander" id="common"><summary>Get these first</summary><div id="common-body"></div></details>'
    assert html.count(block) == 1
    assert len(block.encode("utf-8")) < 250
    start = html.index(block)
    answer = html.index('<section class="answer" aria-labelledby="wear-h">')
    assert answer < start and html.rindex("<section", 0, start) == answer  # the last section that opens before it is Wear this ...
    assert html[:start].rstrip().endswith("</section>")  # ... and it has closed, with nothing between it and the block
    assert html[start + len(block) :].lstrip().startswith('<section class="why"')  # and Why this kit follows it


def test_the_budget_check_reports_each_limit_that_is_broken():
    noise = random.Random(7)
    files = {
        "trio/pal-mnk-ber/index.html": b"x" * (67 * 1024),
        "assets/app-AAAAAAAA.js": noise.randbytes(40 * 1024),  # incompressible: 40 KB gzip on the first load
        "assets/other-BBBBBBBB.js": noise.randbytes(70 * 1024),  # 110 KB of JavaScript in all
        "data/pal-mnk-ber/strict-own.json": b"{" + b" " * (201 * 1024) + b"}",  # over 200 KB raw (but tiny gzipped)
        "data/pal-mnk-ber/wiki-own.json": noise.randbytes(60 * 1024),  # within 200 KB raw, over 50 KB gzipped
    }
    with pytest.raises(build.BudgetError) as caught:
        build.check_budgets(
            files,
            trio_pages=["trio/pal-mnk-ber/index.html"],
            first_load_assets={"trio/pal-mnk-ber/index.html": ["assets/app-AAAAAAAA.js"]},
        )
    message = str(caught.value)
    for part in ("trio page HTML", "first-load JS", "code loaded on first use", "shard data/pal-mnk-ber/strict-own.json is 201.0 KB (limit 200 KB)",
                 "shard data/pal-mnk-ber/wiki-own.json is 60.0 KB gzip (limit 50 KB)"):
        assert part in message, message
    assert "strict-own.json is" in message and message.count("shard ") == 2  # the small-gzip one is only over the raw limit


def test_a_shard_of_200_kb_raw_and_50_kb_gzip_is_within_budget():
    html = b"<html></html>"
    shard = random.Random(3).randbytes(50 * 1024 - 100)  # incompressible: its gzip is about its size
    files = {
        "trio/pal-mnk-ber/index.html": html,
        "assets/app-AAAAAAAA.js": b"let a=1;",
        "data/pal-mnk-ber/strict-own.json": shard,
        "data/pal-mnk-ber/runnerups/balanced.json": b"[1,-2.5]\n" * (20 * 1024),  # a runner-up file holds every tier and is held to the budget of a shard
    }
    sizes = build.check_budgets(
        files,
        trio_pages=["trio/pal-mnk-ber/index.html"],
        first_load_assets={"trio/pal-mnk-ber/index.html": ["assets/app-AAAAAAAA.js"]},
    )
    assert sizes["largest_shard"] == len(shard) and 49 * 1024 < sizes["largest_shard_gzip"] <= 50 * 1024
    assert sizes["first_view_gzip"] == sizes["first_load_gzip"] + sizes["largest_shard_gzip"]
    assert sizes["largest_runnerup"] == 9 * 20 * 1024 and sizes["largest_runnerup_gzip"] < 2 * 1024


def test_the_budget_check_passes_small_files():
    files = {
        "trio/pal-mnk-ber/index.html": b"<html></html>",
        "assets/app-AAAAAAAA.js": b"let a=1;",
        "assets/site-AAAAAAAA.css": b"a{}",
        "data/pal-mnk-ber/strict-own.json": b"{}",
    }
    sizes = build.check_budgets(
        files,
        trio_pages=["trio/pal-mnk-ber/index.html"],
        first_load_assets={"trio/pal-mnk-ber/index.html": ["assets/app-AAAAAAAA.js", "assets/site-AAAAAAAA.css"]},
    )
    assert sizes["trio_html"] == len(files["trio/pal-mnk-ber/index.html"])
    assert sizes["largest_runnerup"] == sizes["largest_runnerup_gzip"] == 0  # (none here)


def test_a_runner_up_file_over_the_budget_of_a_shard_is_refused_naming_the_file():
    noise = random.Random(5)
    files = {
        "trio/pal-mnk-ber/index.html": b"<html></html>",
        "assets/app-AAAAAAAA.js": b"let a=1;",
        "data/pal-mnk-ber/runnerups/index.json": noise.randbytes(80 * 1024),  # the index lists the files, and the page never fetches it
        "data/pal-mnk-ber/runnerups/balanced.json": b"{" + b" " * (201 * 1024) + b"}",  # 201 KB raw, almost nothing gzipped
        "data/pal-mnk-ber/runnerups/tank.json": noise.randbytes(60 * 1024),  # within 200 KB raw, 60 KB gzipped
        "data/pal-mnk-ber/runnerups/melee.json": b"[1]\n" * 1000,
    }
    with pytest.raises(build.BudgetError) as caught:
        build.check_budgets(
            files,
            trio_pages=["trio/pal-mnk-ber/index.html"],
            first_load_assets={"trio/pal-mnk-ber/index.html": ["assets/app-AAAAAAAA.js"]},
        )
    message = str(caught.value)
    assert "runner-up file data/pal-mnk-ber/runnerups/balanced.json is 201.0 KB (limit 200 KB)" in message
    assert "runner-up file data/pal-mnk-ber/runnerups/tank.json is 60.0 KB gzip (limit 50 KB)" in message
    assert "melee.json" not in message and "index.json" not in message  # the others are within it


def test_a_site_of_more_files_than_the_budget_is_refused_with_the_count():
    files = {"trio/pal-mnk-ber/index.html": b"<html></html>", "assets/app-AAAAAAAA.js": b"let a=1;"}
    kwargs = dict(trio_pages=["trio/pal-mnk-ber/index.html"], first_load_assets={"trio/pal-mnk-ber/index.html": ["assets/app-AAAAAAAA.js"]})
    files.update({f"item/w{90000 + n}/index.html": b"" for n in range(build.LIMITS["files"] - 2)})  # (keys above every page of the wiki)
    assert len(files) == build.LIMITS["files"] == 15_000
    assert build.check_budgets(files, **kwargs)["files"] == 15_000  # at the limit is within it
    files[f"item/w{90000 + build.LIMITS['files']}/index.html"] = b""
    with pytest.raises(build.BudgetError, match=r"15,001 files \(limit 15,000\)"):
        build.check_budgets(files, **kwargs)


def test_the_build_counts_the_files_it_wrote(site):
    out, summary = site
    assert summary.files == sum(1 for p in out.rglob("*") if p.is_file())  # (the marker beside the folder is not one of them)
    assert summary.sizes["files"] == summary.files


# ---- the budget of the script is two: what the page loads by itself, and what it loads on first use -----------------------------------------------------
# The page script and the boot script are the first load; the chunks under assets/ that no page loads by itself, the code of the Upgrade section and of a shared kit, are loaded on
# first use. One budget of 100 KB for all of them left the section no room as it grew, and one budget for all the chunks together would be spent by the first that came: the first
# load keeps its limits (30 KB gzip; 100 KB raw), each chunk of the code loaded on first use (its script and the styles esbuild writes beside it) has 100 KB raw and 40 KB gzip of
# its own, and all of them together 250 KB raw.

LAZY_NAME = "assets/upgrade-input-CCCCCCCC.js"
FIRST_LOAD = ["assets/app-AAAAAAAA.js", "assets/boot-BBBBBBBB.js"]
BOOT = b"let b=2;"


def script_budgets(extra: dict[str, bytes]) -> dict[str, int]:
    """check_budgets on made-up files: a page, the page script and the boot script (the first load), and the files given."""
    files = {PAGE: b"<html></html>", FIRST_LOAD[0]: b"let a=1;", FIRST_LOAD[1]: BOOT, **extra}
    return build.check_budgets(files, trio_pages=[PAGE], first_load_assets={PAGE: FIRST_LOAD})


def compressible(size: int) -> bytes:
    """Script of exactly this many bytes that compresses to almost nothing."""
    return (b"let a=1;\n" * (size // 9 + 1))[:size]


def test_the_script_has_a_budget_for_the_first_load_and_others_for_the_code_loaded_on_first_use():
    assert (build.LIMITS["first_load_js"], build.LIMITS["first_load_js_gzip"]) == (100 * 1024, 30 * 1024)
    assert (build.LIMITS["lazy_chunk_js"], build.LIMITS["lazy_chunk_js_gzip"]) == (100 * 1024, 40 * 1024)  # each chunk
    assert build.LIMITS["lazy_total_js"] == 250 * 1024  # and all of them together (raw)
    assert "total_js" not in build.LIMITS  # one budget for both is what there was
    assert "lazy_js" not in build.LIMITS and "lazy_js_gzip" not in build.LIMITS  # (there was one budget for all the lazy code: it is a budget for each chunk now)


def test_the_code_loaded_on_first_use_does_not_eat_into_the_first_load_or_the_other_way_round():
    first = compressible(60 * 1024)  # 60 KB of page script
    lazy = compressible(99 * 1024)  # 99 KB of the section's code: 159 KB of script in all, each part within its own budget
    sizes = script_budgets({FIRST_LOAD[0]: first, LAZY_NAME: lazy})
    assert sizes["first_load_js"] == len(first) + len(BOOT)
    assert sizes["lazy_js"] == len(lazy) and sizes["lazy_js_gzip"] == gz(lazy)
    assert sizes["lazy_chunk_js"] == len(lazy) and sizes["lazy_chunk_js_gzip"] == gz(lazy) and sizes["lazy_chunks"] == 1
    assert sizes["total_js"] == len(first) + len(BOOT) + len(lazy)  # the total is reported, and is no budget


def test_the_sizes_of_the_code_loaded_on_first_use_are_reported_in_all_and_for_the_largest_chunk():
    wide = compressible(70 * 1024)  # the largest by far raw, and almost nothing gzipped
    dense = incompressible(20 * 1024, seed=51)  # the largest gzipped, and small raw
    small = compressible(10 * 1024)
    sizes = script_budgets({LAZY_NAME: wide, "assets/shared-kit-DDDDDDDD.js": dense, "assets/chunk-EEEEEEEE.js": small})
    assert sizes["lazy_js"] == len(wide) + len(dense) + len(small) and sizes["lazy_js_gzip"] == gz(wide) + gz(dense) + gz(small)  # in all: the sum of the chunks
    assert sizes["lazy_chunk_js"] == len(wide) and sizes["lazy_chunk_js_gzip"] == gz(dense)  # and the largest of them (each of the two is the largest of its own kind)
    assert sizes["lazy_chunks"] == 3


def test_a_chunk_loaded_on_first_use_is_held_to_100_kb_raw():
    over = compressible(100 * 1024 + 1)  # compressible: only the raw limit is broken
    with pytest.raises(build.BudgetError) as caught:
        script_budgets({LAZY_NAME: over})
    message = str(caught.value)
    assert f"the chunk {LAZY_NAME} of the code loaded on first use is {len(over) / 1024:.1f} KB raw (limit 100 KB for a chunk)" in message, message
    assert "gzip" not in message and "first-load" not in message and "in all" not in message, message
    script_budgets({LAZY_NAME: over[: 100 * 1024]})  # to the byte: within the budget


def test_a_chunk_loaded_on_first_use_is_held_to_40_kb_gzip():
    noise = random.Random(22).randbytes(45 * 1024)  # incompressible: 45 KB gzip, well within 100 KB raw
    with pytest.raises(build.BudgetError) as caught:
        script_budgets({LAZY_NAME: noise})
    message = str(caught.value)
    assert f"the chunk {LAZY_NAME} of the code loaded on first use is {gz(noise) / 1024:.1f} KB gzip (limit 40 KB for a chunk)" in message, message
    assert "KB raw" not in message and "first-load" not in message, message
    script_budgets({LAZY_NAME: random.Random(23).randbytes(39 * 1024)})  # within the budget


def test_each_chunk_that_no_page_loads_by_itself_has_a_budget_of_its_own_and_is_named_when_it_is_over():
    big = compressible(90 * 1024)
    other = "assets/shared-kit-DDDDDDDD.js"
    sizes = script_budgets({LAZY_NAME: big, other: big})  # 180 KB in all, each within 100 KB: allowed (one budget of 100 KB for both refused it)
    assert sizes["lazy_js"] == 180 * 1024 and sizes["lazy_chunks"] == 2
    with pytest.raises(build.BudgetError) as caught:  # the chunk that is over is named, and the one that is not is not
        script_budgets({LAZY_NAME: big, other: compressible(101 * 1024)})
    message = str(caught.value)
    assert f"the chunk {other} of the code loaded on first use is 101.0 KB raw (limit 100 KB for a chunk)" in message and LAZY_NAME not in message, message
    with pytest.raises(build.BudgetError) as both:  # two chunks over say both
        script_budgets({LAZY_NAME: compressible(101 * 1024), other: compressible(102 * 1024)})
    assert f"the chunk {LAZY_NAME} " in str(both.value) and f"the chunk {other} " in str(both.value), str(both.value)
    script_budgets({"assets/engine/worker-EEEEEEEE.js": big * 3})  # the optimizer's own folder has budgets of its own


def test_all_the_code_loaded_on_first_use_is_held_to_250_kb_raw():
    part = compressible(90 * 1024)
    with pytest.raises(build.BudgetError) as caught:  # three chunks of 90 KB: each within its own budget, 270 KB between them
        script_budgets({LAZY_NAME: part, "assets/shared-kit-DDDDDDDD.js": part, "assets/chunk-EEEEEEEE.js": part})
    message = str(caught.value)
    assert "the code loaded on first use is 270.0 KB raw in all its chunks (limit 250 KB)" in message, message
    assert "the chunk " not in message and "gzip" not in message and "first-load" not in message, message  # (no chunk is over its own budget)


def test_the_total_of_the_code_loaded_on_first_use_is_held_to_the_byte():
    limit = build.LIMITS["lazy_total_js"]
    files = {LAZY_NAME: compressible(100 * 1024), "assets/shared-kit-DDDDDDDD.js": compressible(100 * 1024), "assets/chunk-EEEEEEEE.js": compressible(limit - 200 * 1024)}
    assert script_budgets(files)["lazy_js"] == limit
    files["assets/chunk-EEEEEEEE.js"] = compressible(limit - 200 * 1024 + 1)
    with pytest.raises(build.BudgetError, match=r"the code loaded on first use is 250\.0 KB raw in all its chunks \(limit 250 KB\)"):
        script_budgets(files)
    files["assets/chunk-EEEEEEEE.js"] = compressible(limit - 200 * 1024)
    with pytest.raises(build.BudgetError, match="in all its chunks"):
        script_budgets({**files, "assets/chunk-EEEEEEEE.css": compressible(1)})  # (the styles beside a chunk count in the total as well: one byte more)


def test_the_first_load_keeps_its_own_limits_whatever_the_chunks_weigh():
    over_raw = compressible(101 * 1024)
    with pytest.raises(build.BudgetError) as caught:
        script_budgets({FIRST_LOAD[0]: over_raw})
    message = str(caught.value)
    assert f"first-load JS of {PAGE} is {(len(over_raw) + len(BOOT)) / 1024:.1f} KB raw (limit 100 KB)" in message, message
    assert "code loaded on first use" not in message, message
    noise = random.Random(24).randbytes(31 * 1024)
    with pytest.raises(build.BudgetError, match=r"first-load JS of .* KB gzip \(limit 30 KB\)"):
        script_budgets({FIRST_LOAD[0]: noise})
    with pytest.raises(build.BudgetError) as both:  # a build that breaks both says both
        script_budgets({FIRST_LOAD[0]: noise, LAZY_NAME: over_raw})
    assert "first-load JS" in str(both.value) and "code loaded on first use" in str(both.value)


def incompressible(gzip_size: int, seed: int) -> bytes:
    """Noise that the build measures as exactly `gzip_size` bytes of gzip: it is cut where its gzip is as long as that."""
    noise = random.Random(seed).randbytes(gzip_size + 64)
    for length in range(len(noise), 0, -1):
        measured = gz(noise[:length])
        if measured <= gzip_size:
            assert measured == gzip_size, f"no cut of this noise has a gzip of exactly {gzip_size} bytes"
            return noise[:length]
    raise AssertionError("the noise is empty")


# each of the four limits is held to the byte: what is exactly at it is within the budget, one byte more is not (the first load's raw size and its gzip, the raw size and the gzip of
# what is loaded on first use)


def test_the_raw_size_of_the_first_load_is_held_to_the_byte():
    limit = build.LIMITS["first_load_js"]
    at = compressible(limit - len(BOOT))  # the page script and the boot script are the limit, to the byte
    assert script_budgets({FIRST_LOAD[0]: at})["first_load_js"] == limit
    with pytest.raises(build.BudgetError, match=r"first-load JS of \S+ is 100\.0 KB raw \(limit 100 KB\)"):
        script_budgets({FIRST_LOAD[0]: compressible(len(at) + 1)})


def test_the_gzip_of_the_first_load_is_held_to_the_byte():
    limit = build.LIMITS["first_load_js_gzip"]
    wanted = limit - gz(BOOT)  # the gzip of the page script and of the boot script, added, is the limit
    at = incompressible(wanted, seed=41)
    assert script_budgets({FIRST_LOAD[0]: at})["first_load_js_gzip"] == limit
    with pytest.raises(build.BudgetError, match=r"first-load JS of \S+ is 30\.0 KB gzip \(limit 30 KB\)"):
        script_budgets({FIRST_LOAD[0]: incompressible(wanted + 1, seed=41)})


def test_the_raw_size_of_a_chunk_loaded_on_first_use_is_held_to_the_byte():
    limit = build.LIMITS["lazy_chunk_js"]
    at = compressible(limit)
    assert script_budgets({LAZY_NAME: at})["lazy_chunk_js"] == limit
    with pytest.raises(build.BudgetError, match=rf"the chunk {re.escape(LAZY_NAME)} of the code loaded on first use is 100\.0 KB raw \(limit 100 KB for a chunk\)"):
        script_budgets({LAZY_NAME: compressible(limit + 1)})


def test_the_gzip_of_a_chunk_loaded_on_first_use_is_held_to_the_byte():
    limit = build.LIMITS["lazy_chunk_js_gzip"]
    at = incompressible(limit, seed=42)
    assert script_budgets({LAZY_NAME: at})["lazy_chunk_js_gzip"] == limit
    with pytest.raises(build.BudgetError, match=rf"the chunk {re.escape(LAZY_NAME)} of the code loaded on first use is 40\.0 KB gzip \(limit 40 KB for a chunk\)"):
        script_budgets({LAZY_NAME: incompressible(limit + 1, seed=42)})


# the script that the build writes is the first load, the code loaded on first use, and the optimizer's client and worker: nothing else, and what esbuild emits for the chunk beside
# its script (its styles) is counted with it


CHUNK_CSS = "assets/upgrade-input-CCCCCCCC.css"


@pytest.mark.parametrize(
    "name",
    [
        "stray-AAAAAAAA.js",  # at the root of the site
        "other/stray-AAAAAAAA.js",  # in a folder of the site
        "assets/deep/inner-AAAAAAAA.js",  # below assets/, outside the optimizer's folder
        "assets/engine/shared-AAAAAAAA.js",  # the optimizer's folder, but not its client or its worker
        "assets/engine/data/inner-AAAAAAAA.js",  # and not its data
        "assets/module-AAAAAAAA.mjs",  # a script of another kind of name
    ],
)
def test_script_that_no_budget_counts_is_refused_and_named(name):
    with pytest.raises(build.BudgetError) as caught:
        script_budgets({name: b"let c=3;"})
    message = str(caught.value)
    assert "no budget counts" in message and name in message, message


def test_the_scripts_the_budgets_count_are_all_there_is_and_pass():
    engine = {"assets/engine/client-DDDDDDDD.js": b"let c=1;", "assets/engine/worker-EEEEEEEE.js": b"let w=2;", "assets/engine/highs-0123456789ABCDEF.wasm": b"asm"}
    sizes = script_budgets({LAZY_NAME: compressible(60 * 1024), **engine})
    assert sizes["total_js"] == len(b"let a=1;") + len(BOOT) + 60 * 1024  # the first load and the code loaded on first use: the optimizer's scripts have budgets of their own


def test_a_script_that_no_budget_counts_is_named_together_with_a_budget_that_is_broken():
    with pytest.raises(build.BudgetError) as caught:
        script_budgets({"stray.js": b"let c=3;", LAZY_NAME: compressible(101 * 1024)})
    message = str(caught.value)
    assert "stray.js" in message and f"the chunk {LAZY_NAME} of the code loaded on first use is" in message, message


def test_the_styles_of_a_chunk_count_against_the_budget_of_the_chunk():
    limit = build.LIMITS["lazy_chunk_js"]
    script = compressible(60 * 1024)
    styles = compressible(limit - len(script))  # the script and the styles of the chunk are the limit, to the byte
    sizes = script_budgets({LAZY_NAME: script, CHUNK_CSS: styles})
    assert sizes["lazy_js"] == limit and sizes["lazy_js_gzip"] == gz(script) + gz(styles)
    assert sizes["lazy_chunk_js"] == limit and sizes["lazy_chunk_js_gzip"] == gz(script) + gz(styles) and sizes["lazy_chunks"] == 1  # (one chunk: the script and the styles beside it)
    with pytest.raises(build.BudgetError, match=rf"the chunk {re.escape(LAZY_NAME)} of the code loaded on first use is 100\.0 KB raw \(limit 100 KB for a chunk\)"):
        script_budgets({LAZY_NAME: script, CHUNK_CSS: compressible(len(styles) + 1)})
    with pytest.raises(build.BudgetError, match=rf"the chunk {re.escape(LAZY_NAME)} of the code loaded on first use is 40\.0 KB gzip \(limit 40 KB for a chunk\)"):
        script_budgets({LAZY_NAME: incompressible(20 * 1024, seed=43), CHUNK_CSS: incompressible(20 * 1024 + 1, seed=44)})
    script_budgets({LAZY_NAME: incompressible(20 * 1024, seed=43), CHUNK_CSS: incompressible(20 * 1024, seed=44)})  # to the byte


def test_styles_that_no_script_of_the_same_name_goes_with_are_a_chunk_of_their_own():
    sizes = script_budgets({LAZY_NAME: compressible(60 * 1024), "assets/other-DDDDDDDD.css": compressible(60 * 1024)})  # 120 KB in all, 60 KB each: not one chunk of 120 KB
    assert sizes["lazy_chunks"] == 2 and sizes["lazy_chunk_js"] == 60 * 1024 and sizes["lazy_js"] == 120 * 1024


def test_the_stylesheet_that_a_page_loads_is_not_counted_with_the_first_use():
    files = {PAGE: b"<html></html>", FIRST_LOAD[0]: b"let a=1;", FIRST_LOAD[1]: BOOT, "assets/site-FFFFFFFF.css": compressible(120 * 1024)}
    sizes = build.check_budgets(files, trio_pages=[PAGE], first_load_assets={PAGE: [*FIRST_LOAD, "assets/site-FFFFFFFF.css"]})
    assert sizes["lazy_js"] == 0 and sizes["lazy_js_gzip"] == 0


# ---- refusing inconsistent inputs -------------------------------------------------------------------------------------------------------


def test_results_made_with_other_rules_stop_the_build(tmp_path):
    other = tmp_path / "rules.json"
    document = json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))
    document["version"] = "2026-10-20"
    other.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(build.BuildError, match="rules version"):
        run_build(tmp_path / "dist", tmp_path, rules=other)


def test_a_default_race_that_is_not_the_best_legal_race_stops_the_build(tmp_path):
    scratch = tmp_path / "results"
    shutil.copytree(RESULTS, scratch)
    path = scratch / "pal-mnk-ber" / "defaults.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document.update(race="TRL", runner_up_race="OGR")
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(build.BuildError, match="default race"):
        run_build(tmp_path / "dist", tmp_path, results=scratch)


def test_the_default_race_may_not_be_a_race_that_cannot_start_the_trio(tmp_path):
    scratch = tmp_path / "results"
    shutil.copytree(RESULTS, scratch)
    path = scratch / "pal-mnk-ber" / "defaults.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document.update(race="ELF", runner_up_race="OGR")  # Wood Elf has the highest value in the fixture but cannot start it
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(build.BuildError, match="creation"):
        run_build(tmp_path / "dist", tmp_path, results=scratch)


def test_a_wrong_margin_stops_the_build(tmp_path):
    scratch = tmp_path / "results"
    shutil.copytree(RESULTS, scratch)
    path = scratch / "pal-mnk-ber" / "defaults.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["margin"] = 5.0
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(build.BuildError, match="margin"):
        run_build(tmp_path / "dist", tmp_path, results=scratch)


def test_the_margin_is_checked_against_the_rows_to_the_precision_they_are_written_at(tmp_path):
    """The rows hold F to two decimals and so does the margin, each rounded from the exact value: they can differ by 0.015."""
    for margin, ok in ((812.5, True), (812.51, True), (812.49, True), (812.52, False), (812.48, False)):
        scratch = tmp_path / f"results-{margin}"
        shutil.copytree(RESULTS, scratch)
        path = scratch / "pal-mnk-ber" / "defaults.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["margin"] = margin
        path.write_text(json.dumps(document), encoding="utf-8")
        if ok:
            build.check_defaults(data.load_trio(scratch / "pal-mnk-ber"))
        else:
            with pytest.raises(build.BuildError, match="margin"):
                build.check_defaults(data.load_trio(scratch / "pal-mnk-ber"))


def test_a_default_setup_that_is_not_the_best_of_the_default_race_stops_the_build(tmp_path):
    scratch = tmp_path / "results"
    shutil.copytree(RESULTS, scratch)
    path = scratch / "pal-mnk-ber" / "defaults.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document.update(setup="2h")  # the best setup of the Ogre is dual wield
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(build.BuildError, match="setup"):
        build.check_defaults(data.load_trio(scratch / "pal-mnk-ber"))
    document.update(setup="dw", F=9999.0)  # and its value is the one the rows give it
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(build.BuildError, match="value"):
        build.check_defaults(data.load_trio(scratch / "pal-mnk-ber"))


def edited_copy(tmp_path: Path, name: str, change) -> data.TrioResults:
    """The fixture's results with one file edited (``change`` gets the document and changes it in place), read again."""
    scratch = tmp_path / "results"
    if not scratch.exists():
        shutil.copytree(RESULTS, scratch)
    path = scratch / "pal-mnk-ber" / f"{name}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document), encoding="utf-8")
    return data.load_trio(scratch / "pal-mnk-ber")


def set_value(setup: str, value: float):
    """An edit of ``strict-own.json`` (the shard of the default view) that sets the F of the Ogre's row for ``setup`` at the default role and tier."""

    def change(document):
        for row in document["scenarios"]:
            if row[:4] == ["OGR", "balanced", 4, setup]:
                row[5] = value

    return change


def test_the_default_setup_is_the_best_of_the_default_race_exactly_with_no_slack_for_rounding(tmp_path):
    """The rows and the answer hold F rounded to two decimals from the same exact number, and rounding keeps the order, so the setup the
    precompute chose (the best by the exact F) has the highest rounded F too: a setup worth one cent less in the rows is not the best, and
    a tie of the rounded values is no error (the exact values decide a tie, and the rows cannot tell)."""
    pristine = data.load_trio(RESULTS / "pal-mnk-ber")
    best = pristine.shards[("strict", "own")].scenario("OGR", "balanced", 4, "dw").value
    assert best == pristine.defaults.value == 10720.0 and pristine.defaults.setup == "dw"
    build.check_defaults(pristine)
    ahead = edited_copy(tmp_path / "one-cent-ahead", "strict-own", set_value("2h", best + 0.01))  # the margin still holds to 0.01: only the setup is wrong
    with pytest.raises(build.BuildError, match="default setup dw"):
        build.check_defaults(ahead)
    tied = edited_copy(tmp_path / "tied", "strict-own", set_value("2h", best))
    build.check_defaults(tied)
    behind = edited_copy(tmp_path / "behind", "strict-own", set_value("2h", best - 0.01))
    build.check_defaults(behind)


def test_a_default_view_that_the_results_cannot_answer_is_a_build_error_not_an_assert_or_a_key_error():
    """``check_defaults`` is handed results that may be wrong in ways the reader has not looked at (it is called with whatever it is given),
    and says what is wrong in a BuildError that names the trio, whatever Python flags are on."""
    import ast
    import dataclasses
    import inspect

    results = data.load_trio(RESULTS / "pal-mnk-ber")
    shard = results.shards[("strict", "own")]
    slug = results.meta.slug

    def refused(changed: data.TrioResults, match: str):
        with pytest.raises(build.BuildError, match=match) as caught:
            build.check_defaults(changed)
        assert str(caught.value).startswith(slug), str(caught.value)

    with_defaults = lambda **changes: dataclasses.replace(results, defaults=dataclasses.replace(results.defaults, **changes))  # noqa: E731
    refused(dataclasses.replace(results, shards={k: v for k, v in results.shards.items() if k != ("strict", "own")}), "strict-own")
    refused(with_defaults(race="NOP"), "default race NOP")
    refused(with_defaults(runner_up="NOP"), "runner-up race NOP")
    refused(with_defaults(role="healer"), "healer")
    refused(with_defaults(tier=7), r"\+7")
    refused(with_defaults(setup="stick"), "default setup stick")
    refused(dataclasses.replace(results, meta=dataclasses.replace(results.meta, trio=("PAL", "MNK", "ZZZ"))), "tables of races and classes")
    # a row missing from the default view's shard (a reader that has checked the grid never lets this by)
    holey = dataclasses.replace(shard, scenarios=tuple(s for s in shard.scenarios if (s.race, s.role, s.tier, s.setup) != ("TRL", "balanced", 4, "2h")))
    refused(dataclasses.replace(results, shards={**results.shards, ("strict", "own"): holey}), "TRL balanced \\+4 2h")
    # a role with no setup at all in the shard
    bare = dataclasses.replace(shard, scenarios=tuple(s for s in shard.scenarios if s.role != "balanced"))
    refused(dataclasses.replace(results, shards={**results.shards, ("strict", "own"): bare}), "balanced")
    # and not an assert: it would be gone under `python -O`
    tree = ast.parse(inspect.getsource(build.check_defaults))
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]


def retarget(scratch: Path, **changes) -> dict:
    """Point defaults.json of a scratch copy at another view (role, tier, evidence, buffs) and bring the race, the runner-up, the
    margin, the setup and the value up to date with the rows of that view, as the precompute would write them. When the evidence
    level changes, the runner-up files say so too (they are made for the level of the default answer)."""
    from trioforge.site import view as site_view

    folder = scratch / "pal-mnk-ber"
    path = folder / "defaults.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["view"].update({key: value for key, value in changes.items() if key in ("role", "tier", "evidence", "buffs")})
    results = data.load_trio(RESULTS / "pal-mnk-ber")  # the pristine fixture, for its rows
    shown = document["view"]
    shard = results.shards[(shown["evidence"], shown["buffs"])]
    legal = {o.code: o.legal for o in site_view.race_options(shard.races, trio=results.meta.trio, best=shard.races[0])}
    best = {
        race: max(
            (shard.scenario(race, shown["role"], shown["tier"], setup) for setup in shard.setups_for(shown["role"])),
            key=lambda s: (s.value, -data.SETUPS.index(s.setup)),
        )
        for race in shard.races
    }
    ranked = sorted((race for race in shard.races if legal[race]), key=lambda race: -best[race].value)
    document.update(
        race=ranked[0], runner_up_race=ranked[1], margin=round(best[ranked[0]].value - best[ranked[1]].value, 2),
        F=round(best[ranked[0]].value, 2), setup=best[ranked[0]].setup, strict_pool_empty=changes.get("strict_pool_empty", False),
    )  # fmt: skip
    document.pop("why", None)  # (the why is of the kit of the view the fixture was made for: a precompute would write another for this view, and this helper cannot)
    path.write_text(json.dumps(document), encoding="utf-8")
    if "evidence" in changes:
        runnerups = folder / "runnerups"
        for file in runnerups.glob("*.json"):
            doc = json.loads(file.read_text(encoding="utf-8"))
            doc.update(evidence=changes["evidence"], evidence_fallback=changes["evidence"] != "strict")
            file.write_text(json.dumps(doc), encoding="utf-8")
        reindex(runnerups)
        index = json.loads((runnerups / "index.json").read_text(encoding="utf-8"))
        index.update(evidence=changes["evidence"], evidence_fallback=changes["evidence"] != "strict")
        (runnerups / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return {"race": ranked[0], "runner_up": ranked[1], "setup": best[ranked[0]].setup, "scenario": best[ranked[0]]}


def test_the_baked_answer_is_the_view_that_defaults_json_names_not_a_fixed_one(tmp_path):
    need_node()
    scratch = tmp_path / "results"
    shutil.copytree(RESULTS, scratch)
    expected = retarget(scratch, role="tank", tier=10)
    assert expected["setup"] == "1h-shield"
    out = tmp_path / "dist"
    run_build(out, tmp_path, results=scratch)
    html = page(out, PAGES["trio"])
    assert html.by_id("sw-tier").find("option", selected=True).get("value") == "10"
    assert [r.get("value") for r in html.by_id("sw-role").find_all("input") if r.has("checked")] == ["tank"]
    assert [r.get("value") for r in html.find_all("input", name="setup") if r.has("checked")] == ["1h-shield"]
    assert html.by_id("sw-race").find("option", selected=True).get("value") == expected["race"]
    caption = html.by_id("kit-caption").text()
    assert caption == "For Ogre · Tank · +10 · 1H + shield", caption
    names = [row.find(data_f="name").text() for row in html.by_id("kit-body").find_all("tr")]
    assert names == [item.name if item else "Leave empty" for item in expected["scenario"].kit]
    assert html.by_id("kit-value").text() == f"{view_module.display_int(expected['scenario'].value):,}"


def test_whatever_level_the_answer_is_made_from_the_page_has_no_evidence_wording_picker_note_or_seal_column(tmp_path):
    """Wiki is the one evidence level (the decision of 2026-10-19): no picker, no note, no "none yet", no Seal column, and no evidence in the headline, the line of the switches or the
    notes under the runner-ups, for a page made from the wiki level (the shards of a release) as for one made from the strict level."""
    need_node()
    scratch = tmp_path / "results"
    shutil.copytree(RESULTS, scratch)
    expected = retarget(scratch, evidence="wiki", strict_pool_empty=True)
    out = tmp_path / "dist"
    run_build(out, tmp_path, results=scratch)
    plain = tmp_path / "plain"
    run_build(plain, tmp_path)
    for built in (out, plain):
        html = page(built, PAGES["trio"])
        text = html.find("main").text(skip_hidden=False)
        assert html.find_all("input", name="ev") == [] and html.find_all("p", id_="evidence-note") == [] and not html.find_all("details", id_="assume-evidence")
        assert [th.text() for th in html.by_id("kit").find("thead").find_all("th")] == ["Slot", "Item", "Tier", "Arrives at", "Source"]
        assert not html.by_id("kit-body").find_all(data_f="seal") and not html.by_id("kit-body").find_all(data_f="seal-icon")
        for word in ("(none yet)", "seen in game", "Seen in game", "strict evidence", "wiki evidence", "items the wiki lists"):
            assert word not in text, word
        assert html.by_id("best-race-view").text() == "Balanced view at +4 with your own buffs"
        assert "evidence" not in html.by_id("view-summary").text().lower()
        assert "evidence" not in html.by_id("runnerups").find("p").text().lower() and "evidence" not in html.by_id("runnerups-na").text().lower()
    names = [row.find(data_f="name").text() for row in page(out, PAGES["trio"]).by_id("kit-body").find_all("tr")]
    assert names == [item.name if item else "Leave empty" for item in expected["scenario"].kit]
    assert not page(out, PAGES["trio"]).by_id("runnerups-table").has("hidden")


def test_a_build_from_a_partial_run_says_so(tmp_path, capsys):
    need_node()
    summary = run_build(tmp_path / "dist", tmp_path, noindex=True)  # a partial run can only make a preview (see below)
    assert summary.partial == ("pal-mnk-ber",)  # the fixture holds three races and three tiers
    changelog = make_changelog(tmp_path)
    code = build.main(["--results", str(RESULTS), "--out", str(tmp_path / "again"), "--noindex", "--sources-manifest", str(MANIFEST), "--changelog", str(changelog)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "warning: pal-mnk-ber was built from a partial precompute run" in printed


def test_an_empty_results_folder_is_refused(tmp_path):
    (tmp_path / "results").mkdir()
    with pytest.raises(build.BuildError, match="no results"):
        run_build(tmp_path / "dist", tmp_path, results=tmp_path / "results")


# ---- every figure follows a rule, and the page links that rule with its seal ---------------------------------------------------------------------
# The seal of a rule says how far to trust it, so a number on the page has to say which rules it comes from. An element that holds figures
# names them (data-rules); the page links each of those rules, and the link is followed by the seal.

RULES_JSON = json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))["rules"]
RULE_IDS = {rule["id"] for rule in RULES_JSON}
SEAL_RANK = ["client", "developer", "measured", "player", "model"]  # strongest first
#: a figure: a whole or decimal number with a sign, thousands commas or a percent sign, not part of a word (B17, 1H, x2, w9001)
FIGURE = re.compile(r"(?<![A-Za-z0-9_])[+−-]?\d+(?:,\d{3})*(?:\.\d+)?%?(?![A-Za-z0-9_])")


def text_nodes(node):
    for child in node.children:
        if isinstance(child, str):
            yield child, node
        elif child.tag not in ("script", "style"):
            yield from text_nodes(child)


def links_a_rule(node) -> bool:
    """Is the text of this node the text of a link to a rule?"""
    return any(a.tag == "a" and (a.get("href") or "").startswith("/rules/#") for a in [node, *node.ancestors()])


def not_a_figure(node) -> str | None:
    """Why the digits of a text are not a figure of the model, or None when they are one."""
    for n in [node, *node.ancestors()]:
        if n.get("data-f") in ("name", "source", "r-name", "w-main", "w-off"):
            return "an item's name or its source, as the data has it"
        if n.tag in ("option", "label", "legend"):
            return "the label of a switch"
        if n.tag == "th" and n.get("scope") == "row":
            return "a place of the kit (Ear 1, Finger 2)"
        if n.tag == "time":
            return "a date: how old the data is"
        if n.get("data-n") == "count":
            return "a count of things on the page itself (picks that hold, notes not shown)"
        if n.tag == "ul" and n.parent is not None and n.parent.tag == "dd" and any(a.get("id") == "race-gets" for a in n.ancestors()) and not links_a_rule(node):
            return "a racial ability as the wiki words it (+5 Magic Resist, Sense Heading (50)): the page says it is not scored, so it is the wiki's figure and not the model's; a figure that is the text of a rule's link is still checked"
        if n.get("id") == "race-credit":
            return "the name of the licence in the credit line under the section on the races (CC BY-SA 4.0), which the footer holds too"
    return None


def column_header(cell):
    """The header of the column a table cell is in (a table says the rules of a column's figures once, in the header, and not in each row), or None."""
    elements = lambda parent: [c for c in parent.children if isinstance(c, type(parent))]  # noqa: E731
    table = next((a for a in cell.ancestors() if a.tag == "table"), None)
    heads = table.find_all("thead") if table is not None else []
    if not heads:
        return None
    index = elements(cell.parent).index(cell)
    headers = elements(heads[0].find("tr"))
    return headers[index] if index < len(headers) else None


def rules_of(node) -> set[str]:
    """The rules a figure follows: those its nearest element that names some lists, the header of its column, or the rule of the link it is the text of."""
    for n in [node, *node.ancestors()]:
        if n.get("data-rules"):
            return set(n.get("data-rules").split())
        if n.tag == "a" and (n.get("href") or "").startswith("/rules/#"):
            return {n.get("href").removeprefix("/rules/#")}
        if n.tag == "td" and (header := column_header(n)) is not None and header.get("data-rules"):
            return set(header.get("data-rules").split())
    return set()


def followed_by_a_seal(link) -> bool:
    """A seal comes after the link: right after it, or after the other links of its group ("(a, b, c) Model")."""
    siblings = link.parent.children
    for sibling in siblings[siblings.index(link) + 1 :]:
        if isinstance(sibling, str):
            if re.search(r"[A-Za-z0-9]", sibling):  # words, and not the commas and brackets between the links
                return False
            continue
        if "seal" in sibling.classes:
            return True
        if sibling.tag != "a":
            return False
    return False


def links_to_rule(html, rule_id: str):
    return [a for a in html.find_all("a") if a.get("href") == f"/rules/#{rule_id}"]


def test_every_figure_on_the_trio_page_follows_a_rule_that_the_page_links_with_its_seal(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    uncovered, used, seen = [], set(), 0
    for scope in (html.find("header"), html.find("main")):  # the footer holds licence names (CC BY-SA 4.0), which are not figures
        for text, node in text_nodes(scope):
            for found in FIGURE.finditer(text):
                if not_a_figure(node):
                    continue
                seen += 1
                ids = rules_of(node)
                if not ids:
                    uncovered.append(f"{found.group(0)!r} in <{node.tag} {node.attrs}> '{text.strip()[:50]}'")
                used |= ids
    assert seen > 100, seen  # the walk really found the figures of the page: the kit, the totals, the deltas
    assert not uncovered, "figures that name no rule:\n" + "\n".join(uncovered)
    for rule_id in sorted(used):
        assert rule_id in RULE_IDS, f"{rule_id} is no rule"
        assert any(followed_by_a_seal(a) for a in links_to_rule(html, rule_id)), f"the page links {rule_id} with no seal after the link"


def test_the_walk_over_the_page_finds_a_figure_that_names_no_rule():
    """The check above is only worth something if it can fail: a page with a bare number is caught."""
    bare = parse('<main><p>Kit value <strong>10,720</strong></p><p data-rules="roles.templates">+813</p><p data-n="count">+2 more</p></main>')
    found = [(text, rules_of(node), not_a_figure(node)) for text, node in text_nodes(bare) if FIGURE.search(text)]
    assert found == [("10,720", set(), None), ("+813", {"roles.templates"}, None), ("+2 more", set(), "a count of things on the page itself (picks that hold, notes not shown)")]
    assert [m.group(0) for m in FIGURE.finditer("Ear 1, B17, 1H + shield, x2, w9001, +4, −140, 57%, 1,024 copies, 0.5")] == [
        "1", "+4", "−140", "57%", "1,024", "0.5"
    ]


def test_the_margin_names_the_scoring_rules_and_the_view_it_is_the_best_of(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    best = html.by_id("best-race")
    # the headline names its view itself, so that the claim is never read without it; the figure of the margin is in it
    assert best.text() == "Best race for this trio: Ogre (+813 over Troll), judged in the Balanced view at +4 with your own buffs."
    assert set(html.find(cls="margin").get("data-rules").split()) == {"roles.balanced", "roles.templates"}
    assert html.by_id("best-race-view").text() == "Balanced view at +4 with your own buffs"
    # the rules it is judged by wait in a closed expander under it: a phone shows the answer first, whatever the notes say
    why = html.by_id("race-why")
    assert why.tag == "details" and not why.has("open") and why.parent is best.parent
    assert why.find("summary").text() == "How the best race was judged, and what could change it"
    rules = html.by_id("best-race-rules")
    assert rules.parent is why and rules.text().startswith("How the score works:")
    assert [a.get("href") for a in rules.find_all("a")] == ["/rules/#roles.balanced", "/rules/#roles.templates"]
    assert [s.text() for s in rules.find_all(cls="seal")] == ["Model", "Model"]
    note = html.by_id("best-race-note")  # what could change it, in the same expander
    assert note.parent is why and note.text().startswith("Could change if an open test goes the other way:")


def test_the_runner_up_notes_name_the_weights_among_the_default_assumptions(site):
    """The sliders change what a kit is scored by, so the default assumptions the runner-ups were made for include the role's own weights."""
    out, _ = site
    html = page(out, PAGES["trio"])
    for words in (html.by_id("runnerups").find("p").text(), html.by_id("runnerups-na").text()):
        assert "the role's best weapon setup and the role's own weights" in words, words


#: what a row says again in every row of its table is a thing for the stylesheet or for the header of the column, not for the row
REPEATED_IN_EVERY_ROW = ("data-label", "data-rules")


def test_a_table_of_the_trio_page_does_not_say_the_same_thing_in_every_row(site):
    """The label a narrow window puts before a fact, and the rules the figures of a column follow, are said once (in the stylesheet, in the header of the column, on the table). The grid of a
    whole trio has longer names and kits than any fixture, and the page has to stay inside its size."""
    out, _ = site
    html = page(out, PAGES["trio"])
    for table_id in ("kit", "totals", "runnerups-table"):
        rows = html.by_id(table_id).find("tbody").find_all("tr")
        assert len(rows) >= 14, table_id
        seen: dict[tuple[str, str], int] = {}
        for row in rows:
            for pair in {(name, node.get(name)) for node in [row, *row.iter()] for name in REPEATED_IN_EVERY_ROW if node.get(name)}:
                seen[pair] = seen.get(pair, 0) + 1
        repeated = {pair: count for pair, count in seen.items() if count >= len(rows) // 2}
        assert not repeated, f"{table_id}: said again in {len(rows)} rows: {repeated}"


def test_the_markup_of_the_trio_page_stays_small():
    """A guard on the size of the page (not a budget: the build holds the page to its own): the contract copy of the page, with the invented items of the fixture, was 49.8 KB with the label
    and the rules said again in every row, and the real page is a good 10 KB bigger. It stays under what the headers and the stylesheet's labels leave. (44 KB until p7kit put the stats and
    the why line of the 22 rows in the page: 5.8 KB more in the fixture, some 7 KB in a real page.)"""
    contract = (REPO / "fixtures" / "site" / "contract" / "trio-main.html").read_bytes()
    assert len(contract) <= 52_000, len(contract)


def test_the_flip_notes_are_three_at_most_and_say_how_many_more():
    from trioforge.site import view

    notes = ["A (test B1)", "B (test B2)", "C (test B3)", "D (test B4)", "E (test B5)"]
    assert view.flip_text(notes[:3]) == "A (test B1); B (test B2); C (test B3)"
    assert view.flip_text(notes) == "A (test B1); B (test B2); C (test B3)" and view.flips_more(notes) == 2
    assert view.flips_more(notes[:3]) == 0 and view.flips_more([]) == 0 and view.flip_text([]) == ""


def test_the_level_links_to_its_rule_with_a_seal_on_every_page_and_the_dates_are_dates(site):
    out, _ = site
    for key, name in [*PAGES.items(), ("404", NOT_FOUND)]:
        strip = page(out, name).find(cls="data-strip")
        link = next(a for a in strip.find_all("a"))
        assert link.get("href") == "/rules/#level.current" and link.text() == "Level 50", key
        assert followed_by_a_seal(link) and strip.find(cls="seal").text() == "Developer", key
        assert [t.get("datetime") for t in strip.find_all("time")] == ["2026-10-14", "2026-09-22"], key


def test_the_tier_cells_the_arrival_cells_and_the_copies_follow_the_tier_rules(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    # the headers of the columns name the rules of the figures under them (said once, and not in each of the 22 rows)
    heads = {th.text(): th for th in html.by_id("kit").find("thead").find_all("th")}
    assert heads["Tier"].get("data-rules") == "tier.stat_rule"
    assert set(heads["Arrives at"].get("data-rules").split()) == {"tier.arrival", "tier.exp_needed"}
    row = html.by_id("kit-body").find_all("tr")[0]
    assert not [node for node in [row, *row.iter()] if node.get("data-rules")], "a row names no rules of its own: its column's header does"
    assert rules_of(row.find(data_f="tier")) == {"tier.stat_rule"}
    assert rules_of(row.find(data_f="arrival")) == rules_of(row.find(data_f="reach")) == {"tier.arrival", "tier.exp_needed"}
    line = html.by_id("kit-rules")
    assert [a.get("href") for a in line.find_all("a")] == ["/rules/#tier.stat_rule", "/rules/#tier.arrival", "/rules/#tier.exp_needed"]
    assert [s.text() for s in line.find_all(cls="seal")] == ["Player reports", "Developer", "Player reports"]
    assert html.find("caption", id_="kit-caption").find(data_f="v-tier").get("data-rules") == "tier.stat_rule"


def test_the_haste_the_weapons_are_scored_at_follows_the_haste_rules(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    assert set(html.find(data_f="assume-haste").get("data-rules").split()) == {"haste.cap_pct_with_monk", "haste.worn_per_tier"}
    line = html.by_id("weapons-haste")
    assert line.text().startswith("Scored at 66% haste")
    assert [a.get("href") for a in line.find_all("a")] == ["/rules/#haste.cap_pct_with_monk", "/rules/#haste.worn_per_tier"]
    assert [s.text() for s in line.find_all(cls="seal")] == ["Player reports", "Player reports"]


def test_the_runner_up_deltas_and_the_gaps_between_setups_follow_the_scoring_rules(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    assert set(html.by_id("runnerups-body").get("data-rules").split()) == {"roles.templates", "roles.balanced"}  # (once, on the body of the table: the swaps of every row are under it)
    assert not html.find(cls="swaps").get("data-rules")
    assert set(html.by_id("w-others").get("data-rules").split()) == {"roles.templates", "roles.balanced"}
    note = html.by_id("runnerups-rules")
    assert [a.get("href") for a in note.find_all("a")] == ["/rules/#roles.balanced", "/rules/#roles.templates"]
    assert all(followed_by_a_seal(a) for a in note.find_all("a"))


def test_the_assumes_line_states_the_aa_defaults_and_no_deity(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    aa = html.by_id("assume-aa")
    assert aa.text() == "AA: Combat Stability 3, Physical Enhancement Model; no deity"  # the seal of the weaker of the two rules after them
    assert [s.text() for s in aa.find_all(cls="seal")] == ["Model"]
    assert [a.get("href") for a in aa.find_all("a")] == ["/rules/#ac.softcap.combat_stability_pct", "/rules/#ac.softcap.physical_enhancement_pct"]
    assert aa.parent.tag == "details" and aa.parent.get("id") == "assumes" and aa.parent.get("class") == "assumes"  # (the AA line is inside the folded line of the assumptions, which has the lead in its summary)
    assert aa.parent.find("summary").find(data_f="a-lead").text() == "Assumptions"
    from trioforge.site import view

    assert view.aa_text(3, True) == "Combat Stability 3, Physical Enhancement"
    assert view.aa_text(3, False) == "Combat Stability 3, no Physical Enhancement"  # a trio of casters only (until test B10)
    assert view.aa_text(0, False) == "no Combat Stability, no Physical Enhancement"


def test_the_softcap_carries_the_seal_of_its_weakest_input_rule_and_links_all_three(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    row = next(r for r in html.by_id("totals-body").find_all("tr") if r.find("th").text() == "Sheet AC")
    cap = row.find_all("td")[1]
    assert cap.text().startswith("439 softcap")
    assert [a.get("href") for a in cap.find_all("a")] == [
        "/rules/#ac.softcap.past_cap_rate",  # the client's table of caps, a client file
        "/rules/#ac.softcap.combat_stability_pct",  # Combat Stability and Physical Enhancement raise it by percentages that are the model's
        "/rules/#ac.softcap.physical_enhancement_pct",
    ]
    assert [s.text() for s in cap.find_all(cls="seal")] == ["Model"]  # the weakest of Client file, Model and Model


def test_the_weakest_of_several_rules_is_the_one_a_number_made_from_all_of_them_carries(site):
    from trioforge.site import content, view

    book = content.load_rulebook(REPO / "rules" / "rules.json")
    refs = [view.rule_ref(book, rule_id) for rule_id in ("ac.softcap.past_cap_rate", "ac.softcap.combat_stability_pct", "haste.cap_pct", "level.current")]
    assert [r.seal for r in refs] == ["client", "model", "player", "developer"]
    assert view.weakest(refs).seal == "model" and view.weakest(refs[:1]).seal == "client"
    assert view.weakest([refs[0], refs[3], refs[2]]).seal == "player"
    assert view.weakest(sorted(refs, key=lambda r: SEAL_RANK.index(r.seal), reverse=True)).seal == "model"


# ---- one attribution text -------------------------------------------------------------------------------------------------------------------------
# The footer, the sources page, LICENSE-DATA and every data file credit the same sources in the same words: the wiki the items come from and
# EQL Tools, whose quest data gives the zones of the quest items.


def test_the_attribution_pieces_put_back_together_are_the_attribution_and_link_the_sources_and_the_licence():
    parts = build.attribution_parts()
    assert "".join(text for text, _ in parts) == ATTRIBUTION
    assert [(text, address) for text, address in parts if address] == [
        ("eqlwiki.com", "https://eqlwiki.com/"),
        ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/legalcode"),
        ("EQL Tools", "https://eqltools.com/sources"),
        ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/legalcode"),
    ]
    assert build.attribution_parts("no names here") == (("no names here", None),)


def test_every_footer_credits_the_wiki_and_eql_tools_in_the_one_text_with_links(site):
    out, _ = site
    for key, name in [*PAGES.items(), ("404", NOT_FOUND)]:
        footer = page(out, name).find("footer")
        assert ATTRIBUTION in footer.text(), key
        links = {a.text(): a.get("href") for a in footer.find_all("a")}
        assert links["EQL Tools"] == "https://eqltools.com/sources" and links["eqlwiki.com"] == "https://eqlwiki.com/", key
        assert "https://creativecommons.org/licenses/by-sa/4.0/legalcode" in links.values(), key
        assert LICENCE_SENTENCE in footer.text(), key


def test_the_sources_page_carries_the_same_attribution_once_and_not_a_second_one(site):
    out, _ = site
    main = page(out, PAGES["sources"]).find("main").text()
    assert main.count(ATTRIBUTION) == 1
    assert main.count("Item data adapted from") == 1  # the catalog's own line is no second wording of the credit
    assert LICENCE_SENTENCE in main
    credit = next(li for li in page(out, PAGES["sources"]).find("main").find_all("li") if li.find("strong") and li.find("strong").text() == "EQL Tools")
    assert "CC BY-SA 4.0" in credit.text() and "quest" in credit.text()


def test_license_data_has_the_attribution_and_the_licence_sentence_of_the_site():
    licence = (REPO / "LICENSE-DATA").read_text(encoding="utf-8")
    assert ATTRIBUTION in licence  # one line, as the site prints it
    assert LICENCE_SENTENCE in licence
    assert "https://eqltools.com/sources" in licence and "https://eqlwiki.com/" in licence  # the addresses of the two sources
    assert build.ATTRIBUTION == ATTRIBUTION and build.LICENCE_SENTENCE == LICENCE_SENTENCE


def test_every_data_file_carries_the_release_the_licence_and_the_attribution(site):
    out, _ = site
    files = sorted((out / "data").rglob("*.json"))
    assert len(files) == 4 + 3 + 1 + 1  # four shards, three runner-up files (one for each role, every tier in it), the robust file, the list of the pictures of the items
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert list(document)[:4] == ["v", "release", "license", "attribution"], path.name
        assert document["release"] == "data-2026-10-14" and document["license"] == "CC BY-SA 4.0", path.name
        assert document["attribution"] == ATTRIBUTION, path.name


# ---- the pixel art in the pages ---------------------------------------------------------------------------------------------------------------


#: the sprites that move on their own, and the one that moves only while its link is hovered or has the focus (the mail)
MOVING = ("art-torch", "art-coin", "art-dwarf")


def test_the_art_in_the_pages_is_decoration_and_at_most_three_things_move_on_any_page(site):
    out, _ = site
    for name in [*PAGES.values(), NOT_FOUND]:
        html = page(out, name)
        arts = [node for node in html.find_all("span") if "art" in node.classes]
        assert arts, name  # the brand has its emblem and torches on every page
        for node in arts:
            assert node.get("aria-hidden") == "true" and node.text(skip_hidden=False) == "" and node.get("style") is None, (name, node)
        moving = [node for node in arts if node.classes & set(MOVING)]
        assert len(moving) <= 3, (name, [sorted(node.classes) for node in moving])
        assert html.find_all("img") == [] and all(node.get("style") is None for node in html.iter()), name  # style-src 'self': no style attribute anywhere
    trio, home = page(out, PAGES["trio"]), page(out, PAGES["home"])
    assert len([n for n in trio.find_all("span") if n.classes & set(MOVING)]) == 3  # two torches and the coin
    assert [sorted(n.classes) for n in trio.find_all("span") if "art-mail" in n.classes] == [["art", "art-mail"]]  # the mail rests until the link is hovered
    assert len([n for n in home.find_all("span") if n.classes & set(MOVING)]) == 3  # two torches and the dwarf, which is there because the other trios are not ready
    assert page(out, PAGES["about"]).find_all("span", cls="art-dwarf") == []  # a page that is not unfinished has no dwarf under construction


def test_the_rows_of_the_kit_have_the_icon_of_their_item_or_their_place_and_the_roles_their_crest(site):
    out, _ = site
    trio = page(out, PAGES["trio"])
    rows = trio.by_id("kit").find_all("tr")
    icons = {row.find("th").text(skip_hidden=False): [sorted(n.classes) for n in row.find("th").find_all("span")] for row in rows if row.find("th")}
    assert icons["Head"] == [["art", "art-icon-helm"]] and icons["Wrist 2"] == [["art", "art-icon-wrist"]]
    assert icons["Arms"] == [["art", "art-icon-arms"]] and icons["Back"] == [["art", "art-icon-back"]]
    # the weapons of the fixture's default kit have a picture of their own (a pike, by its head word, in the main hand, a mallet in the off hand), and the hands one of their place
    assert icons["Main hand"] == [["art", "art-icon-spear"]] and icons["Off hand"] == [["art", "art-icon-hammer-1h"]] and icons["Hands"] == [["art", "art-icon-hands-leather"]]
    assert icons["Range"] == [["art", "art-icon-pouch"]]  # (a filled row of the range of an item with no picture of its own: the pouch)
    assert icons["Any slot 1"] == [["art", "art-icon-ring"]]  # (a ring in an any row: what its page heading has, the place's picture, and not the pouch: it fits no held place)
    assert icons["Any slot 2"] == []  # (an empty held row: none, as it was)
    crests = {radio.get("value"): [sorted(n.classes) for n in trio.find("label", **{"for": radio.get("id")}).find_all("span")] for radio in trio.find_all("input", type="radio") if radio.get("name") == "role"}
    assert crests["tank"] == [["art", "art-crest-tank"]] and crests["melee"] == [["art", "art-crest-damage"]] and crests["balanced"] == [] and crests.get("caster", []) == []


def test_the_404_page_has_the_treetop_village_in_a_frame_with_a_caption_as_decoration_and_keeps_its_text_and_links(site):
    out, _ = site
    html = page(out, NOT_FOUND)
    frames = html.find_all("figure", cls="shot")
    assert [sorted(f.classes) for f in frames] == [["shot", "shot-treetop-village"], ["shot", "shot-hyenamen"]]  # the hyena-men joined in the second art round
    for frame, name, caption in zip(frames, ["treetop-village", "hyenamen"], ["You fell off the platform.", "The locals have not seen this page either."]):
        picture = frame.find_all("span", cls=f"art-{name}")
        assert len(picture) == 1 and picture[0].get("aria-hidden") == "true" and picture[0].text(skip_hidden=False) == "" and not picture[0].has("style")
        assert frame.find("figcaption").text() == caption
    assert not html.find_all("span", cls="art-lost")  # the lost picture is gone
    assert html.find("h1").text() == "Page not found"
    assert "There is nothing at this address." in html.find(cls="lead").text()
    assert [a.get("href") for a in html.find("main").find_all("a")][0] == "/"


def test_the_footer_has_its_four_badges_and_the_line_about_daybreak_and_no_line_about_800_by_600(site):
    out, _ = site
    for name in [*PAGES.values(), NOT_FOUND]:
        footer = page(out, name).find("footer")
        badges = [(n.classes - {"badge"}, n.text(skip_hidden=False)) for n in footer.find_all("span") + footer.find_all("a") if "badge" in n.classes]
        assert sorted(text for _, text in badges) == ["Best in Slot", "Data: eqlwiki CC BY-SA", "Latest changes", "TrioForge"], name  # (the third was "Made with Notepad", a label with no link: it leads to the changelog now)
        assert footer.find_all(cls="not-affiliated")[0].text() == "This site is not affiliated with Daybreak Games"
        assert "800" not in footer.text(skip_hidden=False)
    data_badge = page(out, PAGES["home"]).find("footer").find_all("a", cls="badge")[0]
    assert data_badge.get("href") == "/sources/"  # the data badge leads to the page of the sources
    assert page(out, PAGES["home"]).find("footer").find_all("a", cls="badge")[1].get("href") == "/changelog/"  # and the third to the changelog


def test_the_icon_of_every_page_is_the_emblem_as_a_png_address(site):
    out, _ = site
    for name in [*PAGES.values(), NOT_FOUND]:
        links = [n for n in page(out, name).find("head").find_all("link") if n.get("rel") == "icon"]
        assert [n.get("href") for n in links] == [build.FAVICON], name
    assert build.FAVICON.startswith("data:image/png;base64,")


def test_the_art_of_the_site_stays_under_215_kb_and_the_build_refuses_more(site):
    out, summary = site
    total = sum(p.stat().st_size for p in (out / "assets").glob("*.png"))
    assert 0 < total <= build.LIMITS["art"] == 215 * 1024  # (was 120 KB: the set pieces raised it to 200, the icons of the items to 210 and the held things to 215, DECISIONS.md; what a phone fetches stays under 120 KB, tests-e2e/art-phone.spec.mjs)
    assert summary.sizes["art"] == total
    page_name = "trio/pal-mnk-ber/index.html"
    files = {page_name: b"<html></html>", "assets/app-AAAAAAAA.js": b"let a=1;", "assets/boot-BBBBBBBB.js": b"let b=2;", "assets/tile-AAAAAAAA.png": b"x" * build.LIMITS["art"]}
    kwargs = dict(trio_pages=[page_name], first_load_assets={page_name: ["assets/app-AAAAAAAA.js", "assets/boot-BBBBBBBB.js"]})
    assert build.check_budgets(files, **kwargs)["art"] == 215 * 1024  # at the limit is within it
    files["assets/coin-BBBBBBBB.png"] = b"x"
    with pytest.raises(build.BudgetError, match=r"the art is 215\.0 KB in all \(limit 215 KB\)"):
        build.check_budgets(files, **kwargs)


# ---- the fold of the switches, the status on the page, and forced colours -----------------------------------------------------------------------------


def css_text() -> str:
    return (STATIC / "site.css").read_text(encoding="utf-8")


def rule_body(css: str, selector: str) -> str:
    """The declarations of the first rule whose selector is exactly this one."""
    found = re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert found, f"no rule for {selector}"
    return found.group(1)


def media_block(css: str, query: str) -> str:
    """The text between the braces of the first @media block with this query."""
    start = css.index(f"@media {query}")
    depth, i = 0, css.index("{", start)
    begin = i + 1
    while True:
        depth += css[i] == "{"
        depth -= css[i] == "}"
        if depth == 0:
            return css[begin:i]
        i += 1


def test_the_switches_sit_in_one_panel_behind_a_line_that_says_what_is_shown(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    bar, panel = html.by_id("view-bar"), html.by_id("switches")
    assert not bar.has("hidden")  # in the page from the first paint (a stylesheet rule shows it where the page code will run)
    button = html.by_id("switches-toggle")
    assert button.tag == "button" and button.get("type") == "button" and button.text() == "Change" and button.parent is bar
    assert button.has("disabled")  # the page code enables it: until then there is nothing to open
    assert button.get("aria-expanded") == "false" and button.get("aria-controls") == "switches"
    assert "Change" in button.get("aria-label")  # the accessible name starts with the words on the button
    assert panel.find("section", cls="controls") and panel.find("details", cls="assumes") and not panel.has("data-open")  # (the assumptions are one folded details element now)
    order = [n.get("id") for n in html.find("main").iter() if n.get("id") in ("view-bar", "switches", "status", "wear-h")]
    assert order == ["view-bar", "switches", "status", "wear-h"]  # what is shown, the switches, the messages, the answer
    assert html.by_id("view-summary").text() == "Showing Ogre · Balanced · +4 dual wield, your own buffs"
    for ident in ("sw-race", "sw-tier", "sw-role", "assume-buffs", "assume-weapons"):
        assert panel.by_id(ident)  # all of them are inside the panel that folds


def test_the_stylesheet_folds_the_panel_on_a_narrow_screen_only_and_shows_the_line_there_only():
    css = css_text()
    assert "display: none" in rule_body(css, ".view-bar")  # wide: the switches are there, the line is not
    narrow = media_block(css, "(max-width: 37.5rem)")
    # the line is shown only where the page code will run (without it there is nothing to open), and from the first paint, so that the
    # answer does not move down when the code starts; the button keeps its room while it is disabled
    scripted = media_block(narrow, "(scripting: enabled)")
    assert "display: flex" in rule_body(scripted, ".view-bar")
    # a browser that does not know that media query (an older phone) would never show it: the page code marks the line when it starts
    assert "display: flex" in rule_body(narrow, ".view-bar[data-ready]")
    assert "display" not in rule_body(narrow, ".view-bar")  # its box is the same either way; the two rules above only show it
    assert "visibility: hidden" in rule_body(css, ".btn-change:disabled")
    assert "display: none" in rule_body(narrow, ".switches:not([data-open])")
    assert ".switches" not in css.replace(narrow, "")  # nothing outside the narrow block touches the panel


def test_the_status_is_on_the_page_and_out_of_sight_when_it_has_nothing_to_say(site):
    out, _ = site
    status = page(out, PAGES["trio"]).by_id("status")
    assert status.get("role") == "status" and status.get("aria-live") == "polite"
    assert "quiet" in status.classes and status.children == []
    css = css_text()
    assert not re.search(r"\.status:empty\s*\{[^}]*display:\s*none", css)  # display: none would take it out of the accessibility tree
    quiet = rule_body(css, ".status.quiet")
    assert "clip: rect(0, 0, 0, 0)" in quiet and "position: absolute" in quiet
    assert "display" not in quiet and "visibility" not in quiet and "hidden" not in quiet.replace("overflow: hidden", "")


def test_the_answer_heading_can_take_the_focus_and_the_expanders_say_that_their_content_is_coming(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    assert html.by_id("wear-h").get("tabindex") == "-1" and html.by_id("wear-h").tag == "h2"
    for name in ("runnerups", "robust"):
        note = html.by_id(f"{name}-loading")
        assert note.has("hidden") and note.text().startswith("Loading the ") and note.parent is html.by_id(name)


def test_forced_colours_draw_a_chosen_radio_button_apart_from_an_unchosen_one():
    """In forced colours gradients and shadows are dropped and backgrounds repainted, so the dot of a chosen radio button (a gradient)
    vanished. A chosen one is a thick ring of the highlight colour, an unchosen one a thin ring: they differ by more than a colour."""
    block = media_block(css_text(), "(forced-colors: active)")
    chosen = rule_body(block, ".opt input:checked + label::before")
    plain = rule_body(block, ".opt label::before")
    assert re.search(r"border:\s*0\.\d+rem solid Highlight", chosen) and "background: Canvas" in chosen
    assert "border: 2px solid ButtonText" in plain and "background: Canvas" in plain
    assert not re.search(r"var\(--|#[0-9a-fA-F]{3,8}\b|gradient", block)  # system colours only, and no gradient to be dropped
    assert "outline: 2px solid Highlight" in block  # the chosen role and chip keep their outline


# ---- without the page code, and the names of the radio buttons ------------------------------------------------------------------------------------


def switch_controls(main):
    """The controls of the race, role, tier, weapon and buffs switches."""
    return [n for n in main.iter() if n.get("id") in ("sw-race", "sw-tier") or (n.tag == "input" and n.get("name") in ("role", "setup", "buffs"))]


def test_without_the_page_code_the_switches_are_disabled_and_the_note_that_says_why_comes_before_them(site):
    out, _ = site
    main = page(out, PAGES["trio"]).find("main")
    controls = switch_controls(main)
    assert len(controls) >= 10  # two selects and the radio buttons of the role, weapons and buffs choices
    # the page code enables them: without it a switch would do nothing, so it says so by being disabled
    assert [n.get("id") for n in controls if not n.has("disabled")] == []
    order = [n.tag if n.tag == "noscript" else n.get("id") for n in main.iter() if (n.tag == "noscript" and n.parent is main) or n.get("id") in ("view-bar", "switches")]
    assert order == ["noscript", "view-bar", "switches"]  # the note is read before the switches it is about
    assert main.find("noscript").text() == "The race, role and tier switches need JavaScript. This page shows the best kit for the default view."


def test_the_label_of_a_weapon_setup_is_one_run_of_text_so_that_the_space_before_its_note_survives(site):
    """A label is a flex box, which drops the white space at the start of each of its items: a space written at the start of the
    note "(best for this role)" was never drawn. Text and note are one item, with the space between them inside it."""
    out, _ = site
    html = page(out, PAGES["trio"])
    setups = html.by_id("assume-weapons").find_all("input", name="setup")
    assert len(setups) >= 2
    for setup in setups:
        label = html.find("label", **{"for": setup.get("id")})
        assert len(label.children) == 1 and label.children[0].tag == "span" and "opt-text" in label.children[0].classes, label.children
        run = label.children[0]
        assert run.raw_text() == setup.get("data-label")
        assert run.find("span", cls="best-flag").raw_text() == " (best for this role)"
    chosen = next(s for s in setups if s.has("checked"))
    assert html.find("label", **{"for": chosen.get("id")}).text() == f"{chosen.get('data-label')} (best for this role)"


def test_the_check_mark_of_the_chosen_role_is_decoration_that_names_nothing():
    """The mark is text the stylesheet adds, and a browser puts such text into the accessible name of the radio button ("✓ Balanced").
    Its alternative text is empty, so it is drawn and never read; a browser that does not know that syntax keeps the declaration before."""
    body = rule_body(css_text(), ".seg-item input:checked + label::before")
    plain, with_alternative = '"\\2713\\00a0";', '"\\2713\\00a0" / "";'
    assert f"content: {plain}" in body and f"content: {with_alternative}" in body
    assert body.index(f"content: {plain}") < body.index(f"content: {with_alternative}")


# ---- the owner of the report links ----------------------------------------------------------------------------------------------------------
# The report links and the contact text point at the project's GitHub issues. Until the project has its own public account they must
# not point at anyone's: "OWNER" is a real account of someone else. An indexable build is given the owner (--owner); a preview needs none,
# and then no page links to a repository at all.


def repository_links(out: Path) -> list[tuple[str, str]]:
    """(page, address) of every link to the project's own repository."""
    return [
        (name, a.get("href"))
        for name, html in all_html(out)
        for a in html.find_all("a")
        if a.get("href").startswith("https://github.com/") and "/trioforge/" in a.get("href")
    ]


def test_an_indexable_build_needs_an_explicit_owner(tmp_path):
    need_node()
    ready = complete_copy(RESULTS, tmp_path)
    with pytest.raises(build.BuildError, match=r"--owner"):
        build.build(results=ready, out=tmp_path / "dist", noindex=False, sources_manifest=MANIFEST, changelog=make_changelog(tmp_path))
    assert not (tmp_path / "dist").exists()  # nothing was written
    done = build.build(
        results=ready, out=tmp_path / "dist", noindex=False, sources_manifest=MANIFEST, changelog=make_changelog(tmp_path), owner=OWNER,
        scopes=FIXTURE_SCOPES,
    )
    assert done.pages


@pytest.mark.parametrize("owner", ["OWNER", "owner", "Owner"])
@pytest.mark.parametrize("noindex", [False, True])
def test_the_placeholder_owner_is_refused_in_every_build(tmp_path, owner, noindex):
    need_node()
    ready = complete_copy(RESULTS, tmp_path)
    with pytest.raises(build.BuildError, match="placeholder"):
        build.build(
            results=ready, out=tmp_path / "dist", noindex=noindex, sources_manifest=MANIFEST, changelog=make_changelog(tmp_path), owner=owner
        )
    assert not (tmp_path / "dist").exists()


@pytest.mark.parametrize(
    "owner", ["", " ", "a b", "-x", "x-", "x--y", "a" * 40, "x/y", "x.y", "x_y", "ünï", "x@y", "x\ny", "https://github.com/x"]
)
def test_an_owner_must_be_the_name_of_a_github_account(tmp_path, owner):
    ready = complete_copy(RESULTS, tmp_path)
    with pytest.raises(build.BuildError, match="owner"):
        build.build(
            results=ready, out=tmp_path / "dist", noindex=True, sources_manifest=MANIFEST, changelog=make_changelog(tmp_path), owner=owner
        )


@pytest.mark.parametrize("owner", ["a", "A1", "trio-forge", "a" * 39, "0x"])
def test_the_names_of_github_accounts_are_accepted(owner):
    assert build.check_owner(owner, noindex=False) == owner


def test_a_preview_without_an_owner_links_to_no_repository_and_says_when_reports_open(tmp_path):
    need_node()
    out = tmp_path / "dist"
    run_build(out, tmp_path, noindex=True, owner=None)
    assert repository_links(out) == []
    for path in sorted(p for p in out.rglob("*") if p.is_file() and p.suffix in (".html", ".json", ".txt", ".xml", "")):
        assert "OWNER" not in path.read_text(encoding="utf-8", errors="ignore"), path.name
    for name in [*PAGES.values(), NOT_FOUND]:
        footer = page(out, name).find("footer")
        assert "Reports open when the project is public" in footer.text(), name
        assert "Report a problem with this page" not in [a.text() for a in footer.find_all("a")], name
    assert "Reports open when the project is public" in page(out, PAGES["about"]).find("main").text()


def test_the_owner_given_is_the_account_of_every_report_link_and_the_contact_link(site):
    out, _ = site
    links = repository_links(out)
    assert links and all(address.startswith(f"https://github.com/{OWNER}/trioforge/issues") for _, address in links)
    assert {name for name, _ in links} >= {*PAGES.values()}  # a footer link on every page, and the contact link of the about page
    assert not any("OWNER" in read(out, name) for name in [*PAGES.values(), NOT_FOUND])


def test_the_command_line_takes_the_owner_and_refuses_an_indexable_build_without_one(tmp_path):
    need_node()
    ready = complete_copy(RESULTS, tmp_path)
    changelog = make_changelog(tmp_path)
    common = ["--results", str(ready), "--sources-manifest", str(MANIFEST), "--changelog", str(changelog)]
    assert build.main([*common, "--out", str(tmp_path / "a"), "--owner", OWNER], scopes=FIXTURE_SCOPES) == 0
    assert build.main([*common, "--out", str(tmp_path / "b"), "--noindex"]) == 0
    assert build.main([*common, "--out", str(tmp_path / "c")]) == 2  # indexable, no owner
    assert not (tmp_path / "c").exists()


def test_the_committed_issue_chooser_names_no_account_that_is_not_the_projects():
    """The chooser's link to the security policy would point at the placeholder account, so it waits for the owner."""
    config = (REPO / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(encoding="utf-8")
    assert "OWNER" not in config and "github.com" not in config


# ---- builds from partial results --------------------------------------------------------------------------------------------------------------
# A narrowed precompute run (a few races, roles or tiers) can only make a preview: an indexable build refuses it, and a preview says so
# on every page.


def test_an_indexable_build_refuses_partial_results(tmp_path):
    need_node()
    with pytest.raises(build.BuildError, match="partial"):
        build.build(
            results=RESULTS, out=tmp_path / "dist", noindex=False, sources_manifest=MANIFEST, changelog=make_changelog(tmp_path), owner=OWNER
        )
    assert not (tmp_path / "dist").exists()


def test_the_refusal_names_the_trio_and_what_to_do(tmp_path):
    with pytest.raises(build.BuildError) as caught:
        build.build(
            results=RESULTS, out=tmp_path / "dist", noindex=False, sources_manifest=MANIFEST, changelog=make_changelog(tmp_path), owner=OWNER
        )
    message = str(caught.value)
    assert "pal-mnk-ber" in message and "--noindex" in message and "\n" not in message  # one line


def test_a_preview_may_be_built_from_partial_results_and_says_so_on_every_page(tmp_path):
    need_node()
    out = tmp_path / "dist"
    summary = run_build(out, tmp_path, noindex=True, results=RESULTS)
    assert summary.partial == ("pal-mnk-ber",)
    for name in [*PAGES.values(), NOT_FOUND]:
        html = page(out, name)
        banner = html.find_all(cls="preview-banner")
        assert len(banner) == 1, name
        assert banner[0].text().startswith("Preview: partial data"), name
        assert banner[0].parent.tag == "header", name  # in the frame of the page, above the answer


def test_complete_results_make_pages_with_no_banner(site):
    out, summary = site
    assert summary.partial == ()
    for name in [*PAGES.values(), NOT_FOUND]:
        assert page(out, name).find_all(cls="preview-banner") == [], name


# ---- an indexable build holds a trio to the tiers of a full run of it ---------------------------------------------------------------------------
# The tiers a run was asked for are its scope, so a run of any tiers is a full one and reads as complete. What a site publishes does not rest on that:
# an indexable build refuses a trio whose shards have other tiers than a full run of it has (+0, +4 and +10, or every tier for the milestone trio),
# and a preview takes any scope. The fixture is a sample of the milestone trio at three tiers, so its indexable builds say which scope it stands for.

EVERY_TIER = "+0, +1, +2, +3, +4, +5, +6, +7, +8, +9, +10"
FULL_RUNS = [
    ("pal-mnk-ber", tuple(range(11))),
    ("ber-mnk-pal", tuple(range(11))),  # (the slug in any order: it is the trio that has the scope)
    ("pal-shd-ber", (0, 4, 10)),
    ("pal-shd-ber", (10, 0, 4)),  # (the tiers in any order: they are a set)
    ("war-clr-wiz", (0, 4, 10)),
]
SHORT_RUNS = [
    ("pal-mnk-ber", (0, 4), EVERY_TIER),  # the milestone trio with two tiers ...
    ("pal-mnk-ber", (0, 4, 10), EVERY_TIER),  # ... or with the three of the grid
    ("pal-mnk-ber", (4,), EVERY_TIER),
    ("pal-mnk-ber", tuple(range(1, 11)), EVERY_TIER),  # or with every tier but +0
    ("pal-shd-ber", (0, 4), "+0, +4, +10"),  # a trio of the grid with no +10 ...
    ("pal-shd-ber", (0, 10), "+0, +4, +10"),  # ... or no +4
    ("pal-shd-ber", (4,), "+0, +4, +10"),
    ("pal-shd-ber", tuple(range(11)), "+0, +4, +10"),  # or with more tiers than a full run of it has
    ("war-clr-wiz", (), "+0, +4, +10"),
]


@pytest.mark.parametrize(("slug", "tiers"), FULL_RUNS)
def test_a_trio_with_the_tiers_of_a_full_run_of_it_passes_the_check(slug, tiers):
    assert build.check_scope(slug, tiers) is None
    assert build.check_scope(slug, list(tiers)) is None


@pytest.mark.parametrize(("slug", "tiers", "needs"), SHORT_RUNS)
def test_a_trio_with_other_tiers_than_a_full_run_of_it_is_refused_and_the_message_says_both(slug, tiers, needs):
    with pytest.raises(build.BuildError) as caught:
        build.check_scope(slug, tiers)
    message = str(caught.value)
    have = ", ".join(f"+{tier}" for tier in tiers) or "none"
    assert message.startswith(f"{slug}: its shards have the tiers {have}, but an indexable build needs {needs} for this trio"), message
    assert "--noindex" in message and "precompute" in message and "\n" not in message  # one line, with the way out


def test_the_scope_may_be_named_by_the_caller_for_a_sample():
    assert build.check_scope("pal-mnk-ber", (0, 4, 10), (0, 4, 10)) is None
    with pytest.raises(build.BuildError, match=r"the tiers \+0, \+4, but an indexable build needs \+0, \+4, \+10 for this trio"):
        build.check_scope("pal-mnk-ber", (0, 4), (0, 4, 10))


def test_the_scopes_of_the_results_are_checked_trio_by_trio_against_those_named_or_the_default(results):
    with pytest.raises(build.BuildError, match=r"pal-mnk-ber: its shards have the tiers \+0, \+4, \+10, but an indexable build needs " + re.escape(EVERY_TIER)):
        build.check_scopes([results])
    assert build.check_scopes([results], FIXTURE_SCOPES) is None
    assert build.check_scopes([results], {"pal-mnk-ber": (0, 4, 10)}) is None
    with pytest.raises(build.BuildError, match=r"pal-shd-ber is not a trio of the results"):  # a scope named for a trio that is not there is a mistake, not a pass
        build.check_scopes([results], {**FIXTURE_SCOPES, "pal-shd-ber": (0, 4, 10)})


def test_an_indexable_build_refuses_a_trio_with_other_tiers_than_a_full_run_of_it_and_a_preview_takes_any(tmp_path):
    need_node()
    ready = complete_copy(RESULTS, tmp_path)  # (the flag of a partial run is off: this is about the tiers)
    arguments = dict(sources_manifest=MANIFEST, changelog=make_changelog(tmp_path), owner=OWNER)
    with pytest.raises(build.BuildError) as caught:
        build.build(results=ready, out=tmp_path / "dist", noindex=False, **arguments)
    message = str(caught.value)
    assert message.startswith("pal-mnk-ber: its shards have the tiers +0, +4, +10, but an indexable build needs " + EVERY_TIER), message
    assert "--noindex" in message and "\n" not in message
    assert not (tmp_path / "dist").exists()  # nothing was written
    preview = build.build(results=ready, out=tmp_path / "preview", noindex=True, **arguments)  # a preview takes the scope it has
    assert "trio/pal-mnk-ber/index.html" in preview.pages
    sample = build.build(results=ready, out=tmp_path / "sample", noindex=False, scopes=FIXTURE_SCOPES, **arguments)  # and a sample that says which scope it stands for
    assert sample.pages


def test_the_command_line_has_no_way_to_name_a_scope_and_refuses_an_indexable_build_of_other_tiers_in_one_line(tmp_path, capsys):
    need_node()
    ready = complete_copy(RESULTS, tmp_path)
    common = ["--results", str(ready), "--sources-manifest", str(MANIFEST), "--changelog", str(make_changelog(tmp_path))]
    assert build.main([*common, "--out", str(tmp_path / "a"), "--owner", OWNER]) == 2
    error = capsys.readouterr().err
    assert error.startswith("trioforge.site.build: pal-mnk-ber: its shards have the tiers +0, +4, +10, but ") and len(error.splitlines()) == 1, error
    assert not (tmp_path / "a").exists()
    assert build.main([*common, "--out", str(tmp_path / "b"), "--noindex"]) == 0  # a preview is made from the same results
    with pytest.raises(SystemExit):  # (an option for it would be a way past the check from the workflow that deploys)
        build.main([*common, "--out", str(tmp_path / "c"), "--owner", OWNER, "--scope", "pal-mnk-ber=0,4,10"])


def test_the_scope_check_reads_the_one_list_of_tiers_of_a_trio_and_cannot_pass_files_that_list_different_ones(results):
    """Not the first shard's tiers: here the first shard is right, and the one after it is not. The reader refuses such a folder before any check is made
    (test_site_data); a trio put together by hand is refused by the check as well, and with the same words."""
    lost = results.shards[("wiki", "own")]
    odd = dataclasses.replace(lost, scenarios=tuple(s for s in lost.scenarios if s.tier != 10))
    mixed = dataclasses.replace(results, shards={**results.shards, ("wiki", "own"): odd})
    assert next(iter(mixed.shards.values())).tiers == (0, 4, 10)  # (what the check used to read)
    with pytest.raises(build.BuildError, match=r"^pal-mnk-ber/wiki-own\.json: the tiers are \+0, \+4, but strict-own\.json has \+0, \+4, \+10"):
        build.check_scopes([mixed], FIXTURE_SCOPES)
    with pytest.raises(build.BuildError, match=r"^pal-mnk-ber/wiki-own\.json: the tiers are \+0, \+4, but strict-own\.json has"):
        build.check_scopes([mixed], {"pal-mnk-ber": (0, 4)})  # the scope named for a sample is the first shard's, and still not the files'
    assert build.check_scopes([results], FIXTURE_SCOPES) is None


def test_a_folder_whose_shards_list_different_tiers_is_refused_by_every_build_and_nothing_is_written(tmp_path):
    need_node()
    ready = complete_copy(RESULTS, tmp_path)
    path = ready / "pal-mnk-ber" / "wiki-group.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["scenarios"] = [row for row in document["scenarios"] if row[2] != 10]
    document["tiers"] = [0, 4]
    path.write_text(json.dumps(document), encoding="utf-8")
    arguments = dict(sources_manifest=MANIFEST, changelog=make_changelog(tmp_path), owner=OWNER)
    for noindex in (False, True):  # a preview is held to it as well: the tiers of a trio are one list whatever the build is for
        with pytest.raises(data.ResultsError) as caught:
            build.build(results=ready, out=tmp_path / f"dist-{noindex}", noindex=noindex, scopes=FIXTURE_SCOPES, **arguments)
        assert str(caught.value) == (
            "pal-mnk-ber/wiki-group.json: the grid (races, roles, tiers) differs from strict-own.json: its tiers are +0, +4, and strict-own.json's are +0, +4, +10"
        )
        assert not (tmp_path / f"dist-{noindex}").exists()
    common = ["--results", str(ready), "--sources-manifest", str(MANIFEST), "--changelog", str(make_changelog(tmp_path))]
    assert build.main([*common, "--out", str(tmp_path / "cli"), "--noindex"]) == 2  # one line on stderr, as every refusal
    assert not (tmp_path / "cli").exists()


# ---- the marker of a build folder ------------------------------------------------------------------------------------------------------------


def test_the_marker_of_a_build_folder_sits_beside_it_and_is_not_deployed(site):
    out, _ = site
    assert not (out / ".trioforge-build").exists()  # the folder is what Pages serves, so nothing of ours is in it
    assert (out.parent / "dist.trioforge-build").is_file()
    assert [p.name for p in out.iterdir() if p.name.startswith(".")] == []


def test_a_folder_an_earlier_build_made_with_its_marker_inside_is_still_replaced(tmp_path):
    need_node()
    out = tmp_path / "dist"
    out.mkdir()
    (out / ".trioforge-build").write_text("A TrioForge build output. Every build replaces this folder.\n", encoding="utf-8")
    (out / "old.html").write_text("old", encoding="utf-8")
    run_build(out, tmp_path)
    assert not (out / "old.html").exists() and not (out / ".trioforge-build").exists()
    assert (out.parent / "dist.trioforge-build").is_file()


def test_a_folder_that_holds_something_else_is_still_not_replaced(tmp_path):
    need_node()
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(build.BuildError, match="not a TrioForge build"):
        run_build(precious, tmp_path)
    assert (precious / "notes.txt").read_text(encoding="utf-8") == "keep me"
    assert not (tmp_path / "precious.trioforge-build").exists()


# ---- the output folder is replaced whole or not at all -----------------------------------------------------------------------------------
# The files are written into a folder beside the output folder, and that folder takes the old one's place when it is whole. A build that
# stops part way leaves the old output as it was (or none), nothing of its own beside it, and no folder that the next build would refuse.

OLD_SITE = {"index.html": b"<p>old</p>", "assets/old.js": b"old", "data/x/old.json": b"{}"}
NEW_SITE = {"index.html": b"<p>new</p>", "assets/a.js": b"1", "assets/b.js": b"2", "z.txt": b"3"}


def folder_listing(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def beside(out: Path) -> list[str]:
    """What is in the folder of the output folder: the output folder, its marker, and nothing else should be."""
    return sorted(p.name for p in out.parent.iterdir())


def fail_on_the_nth_write(monkeypatch, n: int):
    real = Path.write_bytes
    calls: list[str] = []

    def flaky(self, data):
        calls.append(self.name)
        if len(calls) == n:
            raise OSError(28, "No space left on device")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", flaky)
    return calls


def test_a_build_that_stops_part_way_leaves_no_output_and_nothing_the_next_build_refuses(tmp_path, monkeypatch):
    out = tmp_path / "dist"
    fail_on_the_nth_write(monkeypatch, 3)
    with pytest.raises(OSError, match="No space"):
        build._write(out, NEW_SITE)
    monkeypatch.undo()
    assert beside(out) == []  # no half-written folder, no folder of the build's own, and no marker for a folder that is not there
    build._write(out, NEW_SITE)  # and the next build into the same place is not refused
    assert folder_listing(out) == sorted(NEW_SITE) and beside(out) == ["dist", "dist.trioforge-build"]


def test_a_build_that_stops_part_way_leaves_the_old_output_as_it_was(tmp_path, monkeypatch):
    out = tmp_path / "dist"
    build._write(out, OLD_SITE)
    calls = fail_on_the_nth_write(monkeypatch, 3)
    with pytest.raises(OSError, match="No space"):
        build._write(out, NEW_SITE)
    assert len(calls) == 3
    monkeypatch.undo()
    assert folder_listing(out) == sorted(OLD_SITE) and (out / "index.html").read_bytes() == b"<p>old</p>"
    assert beside(out) == ["dist", "dist.trioforge-build"]
    build._write(out, NEW_SITE)
    assert folder_listing(out) == sorted(NEW_SITE) and beside(out) == ["dist", "dist.trioforge-build"]


def test_a_new_output_takes_the_old_ones_place_whole(tmp_path):
    out = tmp_path / "nested" / "site" / "dist"  # (folders above it that are not there yet are made)
    build._write(out, OLD_SITE)
    build._write(out, NEW_SITE)
    assert folder_listing(out) == sorted(NEW_SITE)
    assert (out.parent / "dist.trioforge-build").is_file() and beside(out) == ["dist", "dist.trioforge-build"]
    empty = tmp_path / "empty"
    empty.mkdir()
    build._write(empty, NEW_SITE)  # an empty folder is replaced too
    assert folder_listing(empty) == sorted(NEW_SITE)


def test_a_folder_that_cannot_be_swapped_in_leaves_the_old_output_and_says_so(tmp_path, monkeypatch):
    """On Windows a folder that a program has open cannot be renamed: the old output is put back and the error is a build error."""
    out = tmp_path / "dist"
    build._write(out, OLD_SITE)
    real = os.replace

    def refuse_the_new_folder(source, target):
        if str(source).endswith(build.TEMP_SUFFIX) and ".old" not in Path(source).name:
            raise PermissionError(13, "Access is denied")
        return real(source, target)

    monkeypatch.setattr(os, "replace", refuse_the_new_folder)
    with pytest.raises(build.BuildError, match="could not put the new build in the place of"):
        build._write(out, NEW_SITE)
    monkeypatch.undo()
    assert folder_listing(out) == sorted(OLD_SITE) and beside(out) == ["dist", "dist.trioforge-build"]


def test_a_folder_that_cannot_be_moved_aside_is_left_as_it_is_and_the_new_build_is_removed(tmp_path, monkeypatch):
    out = tmp_path / "dist"
    build._write(out, OLD_SITE)
    real = os.replace

    def refuse_the_old_folder(source, target):
        if Path(source) == out:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(source, target)

    monkeypatch.setattr(os, "replace", refuse_the_old_folder)
    with pytest.raises(build.BuildError, match="being used by another process"):
        build._write(out, NEW_SITE)
    monkeypatch.undo()
    assert folder_listing(out) == sorted(OLD_SITE) and beside(out) == ["dist", "dist.trioforge-build"]


def test_a_marker_that_a_failed_build_made_for_an_empty_folder_is_taken_away_again(tmp_path, monkeypatch):
    """An empty folder is replaced without a marker, and a build writes the marker before the swap. If the swap then fails, the marker
    must not stay to vouch for whatever the folder's owner puts there next."""
    out = tmp_path / "dist"
    out.mkdir()  # an empty folder of the user's: no marker beside it
    real = os.replace

    def refuse_the_old_folder(source, target):
        if Path(source) == out:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(source, target)

    monkeypatch.setattr(os, "replace", refuse_the_old_folder)
    with pytest.raises(build.BuildError, match="being used by another process"):
        build._write(out, NEW_SITE)
    monkeypatch.undo()
    assert beside(out) == ["dist"] and list(out.iterdir()) == []  # no marker, and no folder of the build's own
    (out / "notes.txt").write_text("keep me", encoding="utf-8")  # the owner puts something there afterwards
    with pytest.raises(build.BuildError, match="not a TrioForge build output"):
        build._write(out, NEW_SITE)
    assert (out / "notes.txt").read_text(encoding="utf-8") == "keep me" and beside(out) == ["dist"]


def test_a_marker_that_was_there_before_stays_when_a_build_fails(tmp_path, monkeypatch):
    out = tmp_path / "dist"
    marker = build.marker_path(out)
    marker.write_text("left by an earlier build", encoding="utf-8")  # the folder is gone and its marker is not
    real = os.replace

    def refuse_the_new_folder(source, target):
        if str(source).endswith(build.TEMP_SUFFIX) and ".old" not in Path(source).name:
            raise PermissionError(13, "Access is denied")
        return real(source, target)

    monkeypatch.setattr(os, "replace", refuse_the_new_folder)
    with pytest.raises(build.BuildError, match="could not put the new build in the place of"):
        build._write(out, NEW_SITE)
    monkeypatch.undo()
    assert beside(out) == [marker.name]  # the marker was there before the build, so it is not the build's to remove
    build._write(out, NEW_SITE)
    assert folder_listing(out) == sorted(NEW_SITE) and beside(out) == ["dist", "dist.trioforge-build"]


def test_an_old_build_that_cannot_be_put_back_is_named_in_the_error_and_not_lost(tmp_path, monkeypatch):
    out = tmp_path / "dist"
    build._write(out, OLD_SITE)
    real = os.replace

    def refuse_both_moves_in(source, target):
        if Path(target) == out:
            raise PermissionError(13, "Access is denied")
        return real(source, target)

    monkeypatch.setattr(os, "replace", refuse_both_moves_in)
    with pytest.raises(build.BuildError, match=r"could not be put back: it is in .*\.old\.trioforge-tmp") as caught:
        build._write(out, NEW_SITE)
    monkeypatch.undo()
    aside = Path(str(caught.value).rsplit("it is in ", 1)[1])
    assert folder_listing(aside) == sorted(OLD_SITE)  # the old output is where the error says
    assert not out.exists()


def is_the_new_folder(path) -> bool:
    """Whether ``path`` is the folder a build writes its files into (and not the one that holds the old output meanwhile)."""
    return str(path).endswith(build.TEMP_SUFFIX) and ".old" not in Path(path).name


@pytest.mark.parametrize("when", ["as the new folder is moved in", "just after the old folder was moved aside"])
def test_an_interruption_of_the_swap_puts_the_old_output_back_and_is_raised_as_it_was(tmp_path, monkeypatch, when):
    """The old output is out of its place from the rename to the next one. It is put back from wherever the interruption comes, even from
    just after the rename has happened, when the code has not yet had the time to note it."""
    out = tmp_path / "dist"
    build._write(out, OLD_SITE)
    real = os.replace
    interruption = KeyboardInterrupt("stop")

    def interrupted(source, target):
        if when == "as the new folder is moved in" and is_the_new_folder(source):
            raise interruption
        real(source, target)
        if when == "just after the old folder was moved aside" and Path(source) == out:
            raise interruption

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(KeyboardInterrupt) as caught:
        build._write(out, NEW_SITE)
    monkeypatch.undo()
    assert caught.value is interruption  # not wrapped in anything
    assert folder_listing(out) == sorted(OLD_SITE) and (out / "index.html").read_bytes() == b"<p>old</p>"
    assert beside(out) == ["dist", "dist.trioforge-build"]  # the old output and its marker; no folder of the build's own, new or old
    build._write(out, NEW_SITE)  # and the next build into the same place goes through
    assert folder_listing(out) == sorted(NEW_SITE) and beside(out) == ["dist", "dist.trioforge-build"]


def test_an_error_that_is_not_an_os_error_in_the_swap_puts_the_old_output_back_and_is_raised_as_it_was(tmp_path, monkeypatch):
    out = tmp_path / "dist"
    build._write(out, OLD_SITE)
    real = os.replace
    failure = RuntimeError("not a file system error")

    def fails(source, target):
        if is_the_new_folder(source):
            raise failure
        return real(source, target)

    monkeypatch.setattr(os, "replace", fails)
    with pytest.raises(RuntimeError) as caught:
        build._write(out, NEW_SITE)
    monkeypatch.undo()
    assert caught.value is failure
    assert folder_listing(out) == sorted(OLD_SITE) and beside(out) == ["dist", "dist.trioforge-build"]


def test_an_old_build_that_cannot_be_put_back_after_an_interruption_is_named_in_the_error(tmp_path, monkeypatch):
    out = tmp_path / "dist"
    build._write(out, OLD_SITE)
    real = os.replace

    def interrupted_and_stuck(source, target):
        if Path(target) == out:
            if is_the_new_folder(source):
                raise KeyboardInterrupt("stop")
            raise PermissionError(13, "Access is denied")  # the old folder going back
        return real(source, target)

    monkeypatch.setattr(os, "replace", interrupted_and_stuck)
    with pytest.raises((build.BuildError, KeyboardInterrupt)) as caught:  # (a KeyboardInterrupt would end the whole test run)
        build._write(out, NEW_SITE)
    monkeypatch.undo()
    assert isinstance(caught.value, build.BuildError) and "could not be put back" in str(caught.value), repr(caught.value)
    aside = Path(str(caught.value).rsplit("it is in ", 1)[1])
    assert aside.name.endswith(".old" + build.TEMP_SUFFIX) and folder_listing(aside) == sorted(OLD_SITE)  # the old output is where the error says
    assert not out.exists()


def test_an_old_output_that_cannot_be_removed_is_named_on_stderr_and_the_build_still_succeeds(tmp_path, monkeypatch, capsys):
    """After the swap the old output is only left over (on Windows a read-only file in it is enough to keep it): the new build is in
    place and complete, so the build does not fail, but it says which folder is in the way instead of leaving it there unmentioned."""
    out = tmp_path / "dist"
    build._write(out, OLD_SITE)
    real = shutil.rmtree

    def refuse_the_old_folder(path, ignore_errors=False, **options):
        if ".old" in Path(path).name:
            if ignore_errors:
                return  # (what the real function does with an error it is told to ignore)
            raise PermissionError(13, "Access is denied", str(path))
        return real(path, ignore_errors=ignore_errors, **options)

    monkeypatch.setattr(shutil, "rmtree", refuse_the_old_folder)
    build._write(out, NEW_SITE)  # returns, and the new output is in place
    monkeypatch.undo()
    assert folder_listing(out) == sorted(NEW_SITE) and (out / "index.html").read_bytes() == b"<p>new</p>"
    left = sorted(p for p in tmp_path.iterdir() if p.name.endswith(".old" + build.TEMP_SUFFIX))
    assert len(left) == 1 and folder_listing(left[0]) == sorted(OLD_SITE)
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 1, lines
    assert str(left[0]) in lines[0] and "can be deleted" in lines[0] and "Access is denied" in lines[0]


def test_an_old_output_that_is_removed_leaves_nothing_beside_the_new_one_and_says_nothing(tmp_path, capsys):
    out = tmp_path / "dist"
    build._write(out, OLD_SITE)
    build._write(out, NEW_SITE)
    assert beside(out) == ["dist", "dist.trioforge-build"]
    assert capsys.readouterr().err == ""


def make_link(kind: str, link: Path, target: Path) -> None:
    """A link at ``link`` to ``target``, of a kind this machine can make (a test skips where it cannot: Windows lets only some accounts
    make symbolic links, and only Windows has junctions)."""
    if kind == "junction":
        if sys.platform != "win32":
            pytest.skip("junctions exist only on Windows")
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True, check=False)
        if made.returncode != 0:
            pytest.skip(f"cannot make a junction here: {made.stdout.strip()} {made.stderr.strip()}")
        return
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"cannot make a symbolic link here: {error}")


@pytest.mark.parametrize("kind", ["symlink to a folder", "symlink to a file", "junction"])
@pytest.mark.parametrize("where", ["at the top", "deep inside"])
def test_a_link_inside_the_output_is_refused_with_a_build_error_and_nothing_is_touched(tmp_path, kind, where):
    out = tmp_path / "dist"
    build._write(out, OLD_SITE)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    holder = out if where == "at the top" else out / "data" / "x"
    make_link(kind, holder / "link", outside / "keep.txt" if kind == "symlink to a file" else outside)
    before = sorted(p.name for p in out.parent.iterdir())
    with pytest.raises(build.BuildError, match=r"holds a link \(.*link\)"):
        build._write(out, NEW_SITE)
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (out / "index.html").read_bytes() == b"<p>old</p>"
    assert sorted(p.name for p in out.parent.iterdir()) == before  # the build made nothing beside the output folder either


@pytest.mark.parametrize("kind", ["symlink to a folder", "junction"])
def test_an_output_folder_that_is_itself_a_link_is_refused_and_the_folder_it_points_to_is_not_touched(tmp_path, kind):
    real = tmp_path / "real"
    build._write(real, OLD_SITE)
    out = tmp_path / "dist"
    make_link(kind, out, real)
    with pytest.raises(build.BuildError, match="is a link"):
        build._write(out, NEW_SITE)
    assert folder_listing(real) == sorted(OLD_SITE)
    assert not any(p.name.endswith(build.TEMP_SUFFIX) for p in tmp_path.iterdir())


def test_the_walk_for_links_goes_in_the_order_of_the_names_and_does_not_follow_a_link(tmp_path, monkeypatch):
    """Where the machine cannot make a symbolic link, the walk is looked at with two paths that are said to be links."""
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "plain.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b" / "inner").mkdir(parents=True)
    (tmp_path / "b" / "inner" / "deep-link").write_text("x", encoding="utf-8")
    (tmp_path / "c-link").mkdir()
    (tmp_path / "c-link" / "under-the-link").write_text("x", encoding="utf-8")
    assert build._first_link(tmp_path) is None
    real = os.path.islink
    said = {str(tmp_path / "c-link"), str(tmp_path / "b" / "inner" / "deep-link")}
    monkeypatch.setattr(os.path, "islink", lambda path: str(path) in said or real(path))
    assert build._first_link(tmp_path) == tmp_path / "b" / "inner" / "deep-link"
    said.discard(str(tmp_path / "b" / "inner" / "deep-link"))
    assert build._first_link(tmp_path) == tmp_path / "c-link"
    said.add(str(tmp_path / "c-link" / "under-the-link"))
    assert build._first_link(tmp_path) == tmp_path / "c-link"  # a link is reported and not entered


def test_a_marker_that_is_a_link_is_refused(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    out = tmp_path / "dist"
    make_link("symlink to a file", build.marker_path(out), outside)
    with pytest.raises(build.BuildError, match="is a link"):
        build._write(out, NEW_SITE)
    assert outside.read_text(encoding="utf-8") == "keep" and not out.exists()


@pytest.mark.parametrize("old_output", [False, True], ids=["no output folder yet", "an old output beside it"])
def test_a_marker_that_is_a_junction_is_refused_and_nothing_is_deleted(tmp_path, old_output):
    """A junction is a folder that stands for another one, so it is no marker file: the build neither writes into it nor removes it,
    and does not touch the folder it points to or the output folder beside it. (Junctions exist only on Windows: elsewhere this skips.)"""
    out = tmp_path / "dist"
    marker = build.marker_path(out)
    if old_output:
        build._write(out, OLD_SITE)
        marker.unlink()  # the marker file of that build gives its place to the junction
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    make_link("junction", marker, outside)
    before = beside(out)
    with pytest.raises(build.BuildError, match="is a link"):
        build._write(out, NEW_SITE)
    assert os.path.isjunction(marker) and folder_listing(outside) == ["keep.txt"]  # the junction is still there, with what it points to
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert beside(out) == before  # and the build made nothing beside the output folder
    if old_output:
        assert folder_listing(out) == sorted(OLD_SITE) and (out / "index.html").read_bytes() == b"<p>old</p>"
    else:
        assert not out.exists()


# A relative output folder is made absolute (without following a link) before anything is named after it: the folder beside it, the
# marker and the old output's place all take the folder's name, and "." has none.


def preview_arguments(tmp_path: Path) -> list[str]:
    """The command line of a preview build of the fixture, with every path absolute (a test that changes folder does not lean on the one
    it started in)."""
    return ["--results", str(RESULTS), "--noindex", "--sources-manifest", str(MANIFEST), "--changelog", str(make_changelog(tmp_path))]


def test_the_current_folder_given_as_the_output_folder_replaces_it_or_is_refused_with_a_build_error(tmp_path, monkeypatch):
    here = tmp_path / "here"
    here.mkdir()
    monkeypatch.chdir(here)
    before = beside(here)
    if sys.platform == "win32":  # the folder a program is working in cannot be moved there
        with pytest.raises(build.BuildError, match="could not put the new build in the place of"):
            build._write(Path("."), NEW_SITE)
        assert list(here.iterdir()) == [] and beside(here) == before  # nothing left: no marker, no folder of the build's own
    else:
        build._write(Path("."), NEW_SITE)
        assert folder_listing(here) == sorted(NEW_SITE) and (tmp_path / "here.trioforge-build").is_file()


def test_a_relative_output_folder_is_replaced_where_it_is_named(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    build._write(Path("dist"), OLD_SITE)
    build._write(Path("dist"), NEW_SITE)
    assert folder_listing(work / "dist") == sorted(NEW_SITE) and beside(work / "dist") == ["dist", "dist.trioforge-build"]


def test_the_command_line_with_the_current_folder_as_the_output_never_ends_in_a_traceback(tmp_path, monkeypatch, capsys):
    need_node()
    here = tmp_path / "here"
    here.mkdir()
    arguments = [*preview_arguments(tmp_path), "--out", "."]
    monkeypatch.chdir(here)
    before = beside(here)
    code = build.main(arguments)  # (a traceback would come out of main as an exception)
    captured = capsys.readouterr()
    if sys.platform == "win32":  # the folder a program is working in cannot be moved there
        assert code == 2
        assert len(captured.err.splitlines()) == 1 and captured.err.startswith("trioforge.site.build: "), captured.err
        assert list(here.iterdir()) == [] and beside(here) == before
    else:
        assert code == 0, captured.err
        assert (here / "index.html").is_file() and (tmp_path / "here.trioforge-build").is_file()


def test_the_command_line_builds_a_relative_output_folder_into_the_folder_it_is_run_from(tmp_path, monkeypatch, capsys):
    need_node()
    work = tmp_path / "work"
    work.mkdir()
    arguments = [*preview_arguments(tmp_path), "--out", "dist"]
    monkeypatch.chdir(work)
    code = build.main(arguments)
    assert code == 0, capsys.readouterr().err
    assert (work / "dist" / "index.html").is_file()
    assert sorted(p.name for p in work.iterdir()) == ["dist", "dist.trioforge-build"]


# ---- helper functions the pages and the JS agree on -------------------------------------------------------------------------------------


def test_number_formatting_matches_what_the_browser_code_does():
    from trioforge.site import view

    assert view.display_int(812.5) == 813 and view.display_int(-2.5) == -2 and view.display_int(0.4999) == 0
    assert view.display_int(10720.0004) == 10720
    assert view.fmt_int(1234567) == "1,234,567" and view.fmt_int(-1234) == "−1,234" and view.fmt_int(0) == "0"
    assert view.fmt_signed(7770) == "+7,770" and view.fmt_signed(-86) == "−86" and view.fmt_signed(0) == "0"
    assert view.tier_label(4) == "+4"


def test_a_summoned_item_arrives_at_its_spell_rank_and_has_no_copies_to_count():
    from trioforge.site import view

    assert view.arrival_label(4) == "+4" and view.arrival_label(0) == "+0" and view.arrival_label(None) == "spell rank"
    assert view.reach_text(None, 10) == "" and view.reach_text(None, 0) == ""
    assert view.reach_text(0, 4) == "16 copies to reach +4"  # a number still counts as before


def test_races_are_ordered_legal_first_with_the_best_race_on_top():
    from trioforge.site import view

    ordered = view.race_options(["ELF", "TRL", "OGR"], trio=("PAL", "MNK", "BER"), best="OGR")
    assert [(o.code, o.legal, o.best) for o in ordered] == [("OGR", True, True), ("TRL", True, False), ("ELF", False, False)]
    assert ordered[0].name == "Ogre" and ordered[2].name == "Wood Elf"
    everyone = view.race_options(list(data.RACE_CODES), trio=("PAL", "MNK", "BER"), best="OGR")
    assert [o.code for o in everyone if not o.legal] == ["DEF", "ELF"]  # Dark Elf, Wood Elf: no Paladin, Monk or Berserker; alphabetical
    assert len(everyone) == 15
    assert everyone[0].code == "OGR"


def test_the_command_line_builds_and_reports_sizes(tmp_path):
    need_node()
    out = tmp_path / "dist"
    changelog = make_changelog(tmp_path)
    env = dict(os.environ, PYTHONPATH=str(REPO / "pipeline"))
    done = subprocess.run(
        [sys.executable, "-m", "trioforge.site.build", "--results", str(RESULTS), "--out", str(out), "--noindex",
         "--sources-manifest", str(MANIFEST), "--changelog", str(changelog), "--no-item-catalog"],
        capture_output=True, text=True, env=env, cwd=REPO, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert "trio page HTML" in done.stdout and "first-load JS" in done.stdout
    assert (out / "trio" / "pal-mnk-ber" / "index.html").is_file()
    failed = subprocess.run(
        [sys.executable, "-m", "trioforge.site.build", "--results", str(tmp_path / "missing"), "--out", str(tmp_path / "x")],
        capture_output=True, text=True, env=env, cwd=REPO, check=False,
    )  # fmt: skip
    assert failed.returncode == 2
    assert len(failed.stderr.strip().splitlines()) == 1 and "no results" in failed.stderr


# ---- the contract with the browser tests ---------------------------------------------------------------------------------------------------
# tests-js/trio.test.mjs, picker.test.mjs and notfound.test.mjs run the real page code against these committed files. They are what this build writes for the
# fixture; if a template or the data format changes, regenerate them with
#     TRIOFORGE_UPDATE_CONTRACT=1 python -m pytest pipeline/tests/test_site_build.py -k contract
# and the JavaScript tests then show whether the page code still agrees.


def contract_files(out: Path) -> dict[str, str]:
    files = {
        "trio-main.html": extract_main(read(out, PAGES["trio"])),
        "home-main.html": extract_main(read(out, PAGES["home"])),
        "notfound-main.html": extract_main(read(out, NOT_FOUND)),
        "trio-report-link.txt": page(out, PAGES["trio"]).by_id("report-link").get("href") + "\n",
    }
    for name in ("strict-own", "strict-group", "wiki-own", "wiki-group", "robust"):
        files[f"data/{name}.json"] = read(out, f"data/pal-mnk-ber/{name}.json")
    for path in sorted((out / "data" / "pal-mnk-ber" / "runnerups").glob("*.json")):
        files[f"data/runnerups/{path.name}"] = path.read_text(encoding="utf-8")
    return files


def test_the_committed_contract_files_are_what_the_build_writes(site):
    out, _ = site
    files = contract_files(out)
    if os.environ.get("TRIOFORGE_UPDATE_CONTRACT") == "1":
        for name, text in files.items():
            target = CONTRACT / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
    for name, text in files.items():
        committed = CONTRACT / name
        assert committed.is_file(), f"{name} is missing; run with TRIOFORGE_UPDATE_CONTRACT=1"
        assert committed.read_text(encoding="utf-8") == text, f"{name} is stale; run with TRIOFORGE_UPDATE_CONTRACT=1"
    expected = {p.relative_to(CONTRACT).as_posix() for p in CONTRACT.rglob("*") if p.is_file()}
    assert expected == set(files), "an unexpected file in fixtures/site/contract"


# ---- what DECISIONS says about the site ----------------------------------------------------------------------------------------------------------


def test_decisions_records_the_budget_of_a_data_file_the_build_enforces_and_why_race_and_tier_are_selects():
    text = (REPO / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    budget = f"{build.LIMITS['shard'] // 1024} KB raw and {build.LIMITS['shard_gzip'] // 1024} KB gzip"
    assert budget in text, f"no decision line says that a data file may be {budget} (build.LIMITS refuses a larger one)"
    # the review asked for radio groups everywhere; two of the switches have too many options for that, and the line says so
    assert "Race and Tier are native selects" in text and "15 options" in text and "11 options" in text
    assert "Permissions-Policy" in text and "Change button" in text  # the other two choices of this review: the header, and the phone


def test_decisions_records_the_limit_on_the_number_of_files_and_the_layout_of_the_runner_ups_the_build_enforces():
    text = " ".join((REPO / "docs" / "DECISIONS.md").read_text(encoding="utf-8").split())
    assert f"more than {build.LIMITS['files']:,} files" in text, "no decision line says that the build refuses a site of more than the limit of files"
    assert "One runner-up file for each role" in text and "runnerups/<role>.json" in text and "`--tiers` is the scope" in text


def test_decisions_records_the_budgets_of_the_engine_data_files_the_build_enforces():
    text = " ".join((REPO / "docs" / "DECISIONS.md").read_text(encoding="utf-8").split())
    limits = build.LIMITS
    budgets = (
        f"a bundle {limits['engine_bundle'] // 1024} KB raw, the item table {limits['engine_items'] // 1024 // 1024} MB raw "
        f"and {limits['engine_items_gzip'] // 1024} KB gzip"
    )
    assert budgets in text, f"no decision line says that the engine's data files may be {budgets} (build.LIMITS refuses larger ones)"


def test_decisions_records_the_two_budgets_of_the_script_the_build_enforces():
    text = " ".join((REPO / "docs" / "DECISIONS.md").read_text(encoding="utf-8").split())
    limits = build.LIMITS
    first = f"{limits['first_load_js_gzip'] // 1024} KB gzip and, raw, the {limits['first_load_js'] // 1024} KB that the total had"
    lazy = f"{limits['lazy_chunk_js'] // 1024} KB raw and {limits['lazy_chunk_js_gzip'] // 1024} KB gzip of its own"
    total = f"{limits['lazy_total_js'] // 1024} KB raw in all"
    assert first in text, f"no decision line says that the first load keeps {first} (build.LIMITS refuses more)"
    assert lazy in text, f"no decision line says that each chunk of the code loaded on first use has {lazy} (build.LIMITS refuses more)"
    assert total in text and "each chunk" in text, f"no decision line says that all the chunks of the code loaded on first use have {total} (build.LIMITS refuses more)"
    assert "Before and after" in text and "the chunk" in text  # and with the numbers of the chunk before and after


def test_the_rules_loader_still_accepts_the_repository_rules():
    assert rules_module.load().version == "2026-10-13"


# ---- the optimizer's files: client, worker, WebAssembly and the manifest ----------------------------------------------------------------
# The engine is not on any page's first load. The client and the worker are bundled as modules next to the page code (under
# assets/engine/, so the page budgets that count assets/*.js do not count them), the solver's WebAssembly is copied under a hash of its
# content, and engine-manifest.json names all three with their sizes and lists the trios and levels a request may name; the bundles of a trio are
# listed in the manifest of the trio (engine-trios/<trio>.json), so that the main one does not grow with the number of trios.

ENGINE_DIR = "assets/engine"
SINKS = re.compile(
    r"innerHTML|outerHTML|insertAdjacentHTML|document\s*\.\s*write|createContextualFragment|\beval\s*\(|new\s+Function|"
    r"setAttribute\(\s*[\"']on|srcdoc|DOMParser|execScript|importScripts|\bset(?:Timeout|Interval)\(\s*[\"'`]|"
    r"createObjectURL|new\s+Blob"
)  # fmt: skip


def engine_manifest(out: Path) -> dict:
    return json.loads(read(out, MANIFEST_FILE))


#: the SHA-256 of the made-up WebAssembly of engine_assets(): the first 16 digits are the ones in its name
WASM_SHA256 = "0123456789abcdef" + "0" * 48
#: the SHA-256 of the made-up evaluator of a shared kit of engine_assets() (its name carries a hash of its own, esbuild's, and not these digits)
KITVALUE_SHA256 = "c0ffee0123456789" + "3" * 48
KITVALUE_PATH = "/assets/engine/kitvalue-CCCCCCCC.js"


def engine_assets(
    client: str = "/assets/engine/client-AAAAAAAA.js", worker: str = "/assets/engine/worker-BBBBBBBB.js", kitvalue: str = KITVALUE_PATH, kitvalue_sha256: str | None = KITVALUE_SHA256
) -> build.EngineAssets:
    return build.EngineAssets(
        highs="1.15.3",
        client=build.EngineFile(client, 10, 5),
        worker=build.EngineFile(worker, 20, 8),
        wasm=build.EngineFile("/assets/engine/highs-0123456789ABCDEF.wasm", 3000, 1200, sha256=WASM_SHA256),
        kitvalue=build.EngineFile(kitvalue, 60, 25, sha256=kitvalue_sha256),
    )


#: the SHA-256 of the made-up data files of engine_data(): the first 16 digits are the ones in their names
ITEMS_SHA256 = "89abcdef01234567" + "1" * 48
BUNDLE_SHA256 = "fedcba9876543210" + "2" * 48
ITEMS_PATH = "/assets/engine/data/items-89ABCDEF01234567.json"


def data_file(path: str, digest: str | None, size: int = 4000, packed: int = 900) -> build.EngineFile:
    return build.EngineFile(path, size, packed, sha256=digest)


RELEASE = {"data_release": "data-2026-10-14", "rules_version": "2026-10-13"}


def engine_data(trios: dict | None = None, *, items: build.EngineFile | None = None, **release: str) -> build.EngineData:
    """The data files of a made-up engine: an item table and, for each trio and each of its levels, a bundle named for them."""
    listed = {"pal-mnk-ber": [50]} if trios is None else trios
    bundles = {
        slug: {level: data_file(f"/assets/engine/data/{slug}-l{level}-FEDCBA9876543210.json", BUNDLE_SHA256, 3000, 800) for level in levels}
        for slug, levels in listed.items()
    }
    return build.EngineData(items=items or data_file(ITEMS_PATH, ITEMS_SHA256), bundles=bundles, **{**RELEASE, **release})


def trio_manifest(out: Path, slug: str) -> dict:
    return json.loads(read(out, f"{TRIO_MANIFEST_DIR}/{slug}.json"))


def test_the_manifest_lists_the_hashed_engine_files_with_their_sizes(site):
    out, _ = site
    manifest = engine_manifest(out)
    assert set(manifest) == {"version", "highs", "data_release", "rules_version", "client", "worker", "wasm", "kitvalue", "items", "trios"}
    assert manifest["version"] == 2
    package = json.loads((REPO / "node_modules" / "highs" / "package.json").read_text(encoding="utf-8"))
    pinned = json.loads((REPO / "package.json").read_text(encoding="utf-8"))["dependencies"]["highs"]
    assert manifest["highs"] == package["version"] == pinned  # the pinned solver is the one that was bundled
    for role, name, suffix in (("client", "client", "js"), ("worker", "worker", "js"), ("wasm", "highs", "wasm"), ("kitvalue", "kitvalue", "js")):
        entry = manifest[role]
        assert set(entry) == {"path", "bytes", "gzip"} | ({"sha256"} if role in ("wasm", "kitvalue") else set()), role  # the client and the worker are not checked by a digest
        assert re.fullmatch(rf"/{ENGINE_DIR}/{name}-[A-Z0-9]{{8,32}}\.{suffix}", entry["path"]), entry["path"]
        content = (out / entry["path"].lstrip("/")).read_bytes()
        assert entry["bytes"] == len(content), role
        assert entry["gzip"] == gz(content), role
    files = sorted(p.name for p in (out / ENGINE_DIR).iterdir() if p.is_file())
    assert files == sorted(Path(manifest[role]["path"]).name for role in ("client", "worker", "wasm", "kitvalue")), files  # nothing unlisted


def test_the_webassembly_is_the_solver_package_file_copied_under_a_hash_of_its_content(site):
    out, _ = site
    path = engine_manifest(out)["wasm"]["path"]
    source = (REPO / "node_modules" / "highs" / "build" / "highs.wasm").read_bytes()
    assert (out / path.lstrip("/")).read_bytes() == source
    assert path == f"/{ENGINE_DIR}/highs-{hashlib.sha256(source).hexdigest().upper()[:16]}.wasm"
    assert source[:4] == b"\x00asm"
    # the worker checks the file it downloads against this digest before it compiles it
    digest = engine_manifest(out)["wasm"]["sha256"]
    assert digest == hashlib.sha256(source).hexdigest() and re.fullmatch(r"[0-9a-f]{64}", digest)
    assert path.endswith(f"highs-{digest[:16].upper()}.wasm")  # the name and the digest say the same


def test_the_manifest_lists_each_trio_with_its_levels_and_nothing_else_of_it(site, results):
    out, _ = site
    manifest = engine_manifest(out)
    assert manifest["trios"] == {results.meta.slug: [results.meta.level]}  # the bundles are in the manifest of the trio
    assert manifest["data_release"] == results.meta.data_tag and manifest["rules_version"] == results.meta.rules_version


def test_each_trio_has_a_manifest_of_its_own_with_a_bundle_for_each_level_of_the_trio_and_for_no_other(site, results):
    out, _ = site
    main = engine_manifest(out)
    slug = results.meta.slug
    document = trio_manifest(out, slug)
    assert set(document) == {"version", "data_release", "rules_version", "trio", "bundles"}
    assert document["version"] == 1 and document["trio"] == slug
    assert (document["data_release"], document["rules_version"]) == (main["data_release"], main["rules_version"])  # the worker checks it
    assert list(document["bundles"]) == [str(level) for level in main["trios"][slug]] == [str(results.meta.level)]
    for entry in document["bundles"].values():
        assert set(entry) == {"path", "bytes", "gzip", "sha256"}
    folder = sorted(p.name for p in (out / TRIO_MANIFEST_DIR).iterdir())
    assert folder == [f"{slug}.json"]  # a manifest for each trio of the main manifest, and no other file
    text = read(out, f"{TRIO_MANIFEST_DIR}/{slug}.json")
    assert text == json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"  # canonical, so that a build is reproducible


def test_the_manifest_of_a_trio_is_outside_assets_and_so_has_the_caching_of_the_main_manifest(site):
    out, _ = site
    headers = (out / "_headers").read_text(encoding="utf-8")
    blocks = build._header_blocks(headers)
    for name in (MANIFEST_FILE, f"{TRIO_MANIFEST_DIR}/pal-mnk-ber.json"):
        matching = [pattern for pattern, _ in blocks if fnmatch.fnmatchcase("/" + name, pattern)]
        assert matching == ["/*"], (name, matching)  # only the rule for every path, which sets no Cache-Control
    cached = [pattern for pattern, lines in blocks if any(header.lower() == "cache-control" for _, header, _ in lines)]
    assert cached == [build.ASSET_PATTERN] and not fnmatch.fnmatchcase("/" + MANIFEST_FILE, build.ASSET_PATTERN)
    assert not fnmatch.fnmatchcase(f"/{TRIO_MANIFEST_DIR}/pal-mnk-ber.json", build.ASSET_PATTERN)


def test_the_item_table_and_the_bundles_are_published_as_the_results_hold_them_under_hashed_names(site, results):
    out, _ = site
    manifest = engine_manifest(out)
    table = (RESULTS / "items.json").read_bytes()
    digest = hashlib.sha256(table).hexdigest()
    assert manifest["items"] == {"path": f"/{ENGINE_DIR}/data/items-{digest.upper()[:16]}.json", "bytes": len(table), "gzip": gz(table), "sha256": digest}
    assert (out / manifest["items"]["path"].lstrip("/")).read_bytes() == table
    bundle = (RESULTS / results.meta.slug / "engine-l50.json").read_bytes()
    digest = hashlib.sha256(bundle).hexdigest()
    listed = trio_manifest(out, results.meta.slug)["bundles"]["50"]
    assert listed == {"path": f"/{ENGINE_DIR}/data/{results.meta.slug}-l50-{digest.upper()[:16]}.json", "bytes": len(bundle), "gzip": gz(bundle), "sha256": digest}
    assert (out / listed["path"].lstrip("/")).read_bytes() == bundle
    published = sorted(p.name for p in (out / ENGINE_DIR / "data").iterdir())
    assert published == sorted([Path(manifest["items"]["path"]).name, Path(listed["path"]).name])  # nothing unlisted, nothing else in the folder
    assert not (out / "data" / "items.json").exists() and not list((out / "data").rglob("engine-l*"))  # the results' own names are not served


def test_the_same_bytes_have_the_same_name_and_other_bytes_another(tmp_path):
    need_node()
    other = tmp_path / "other"
    shutil.copytree(RESULTS, other)
    path = other / "items.json"
    path.write_text(json.dumps(json.loads(path.read_text(encoding="utf-8"))), encoding="utf-8")  # the same table, written with other spacing
    first, second = tmp_path / "first", tmp_path / "second"
    run_build(first, tmp_path, noindex=True)
    run_build(second, tmp_path, noindex=True, results=other)
    a, b = engine_manifest(first)["items"], engine_manifest(second)["items"]
    assert a["path"] != b["path"] and a["sha256"] != b["sha256"] and a["bytes"] != b["bytes"]
    assert (second / b["path"].lstrip("/")).read_bytes() == path.read_bytes()
    assert engine_manifest(first)["trios"] == engine_manifest(second)["trios"]  # the bundle was not touched
    assert read(first, f"{TRIO_MANIFEST_DIR}/pal-mnk-ber.json") == read(second, f"{TRIO_MANIFEST_DIR}/pal-mnk-ber.json")


def test_the_manifest_is_canonical_json_with_the_trios_in_order():
    raw = build.render_manifest(engine_assets(), engine_data({"pal-shd-ber": [55, 50], "pal-mnk-ber": [50]}))
    text = raw.decode("utf-8")
    assert text.endswith("}\n") and "\n" not in text[:-1]
    document = json.loads(text)
    assert text == json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    assert list(document["trios"]) == ["pal-mnk-ber", "pal-shd-ber"]
    assert document["trios"] == {"pal-mnk-ber": [50], "pal-shd-ber": [50, 55]}  # the levels, sorted, once each; nothing of the bundles
    assert (document["data_release"], document["rules_version"]) == (RELEASE["data_release"], RELEASE["rules_version"])
    assert document["items"] == {"path": ITEMS_PATH, "bytes": 4000, "gzip": 900, "sha256": ITEMS_SHA256}
    assert document["version"] == 2
    assert document["worker"] == {"path": "/assets/engine/worker-BBBBBBBB.js", "bytes": 20, "gzip": 8}
    assert document["wasm"] == {"path": "/assets/engine/highs-0123456789ABCDEF.wasm", "bytes": 3000, "gzip": 1200, "sha256": WASM_SHA256}


def test_the_manifest_of_a_trio_is_canonical_json_with_the_bundles_by_level():
    data_files = engine_data({"pal-shd-ber": [55, 50], "pal-mnk-ber": [50]})
    raw = build.render_trio_manifest("pal-shd-ber", data_files)
    text = raw.decode("utf-8")
    assert text.endswith("}\n") and "\n" not in text[:-1]
    document = json.loads(text)
    assert text == json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    assert document["version"] == 1 and document["trio"] == "pal-shd-ber"
    assert (document["data_release"], document["rules_version"]) == (RELEASE["data_release"], RELEASE["rules_version"])
    assert list(document["bundles"]) == ["50", "55"]  # sorted by level, each once
    assert document["bundles"]["55"] == {"path": "/assets/engine/data/pal-shd-ber-l55-FEDCBA9876543210.json", "bytes": 3000, "gzip": 800, "sha256": BUNDLE_SHA256}
    assert build.trio_manifest_name("pal-shd-ber") == "engine-trios/pal-shd-ber.json"


@pytest.mark.parametrize(
    "trios",
    [{}, {"pal-mnk-ber": []}, {"Pal-Mnk-Ber": [50]}, {"pal-mnk": [50]}, {"../x": [50]}, {"pal-mnk-ber": [0]}, {"pal-mnk-ber": [50.5]}, {"pal-mnk-ber": ["50"]}],
)
def test_the_manifest_refuses_trios_that_the_browser_would_not_read(trios):
    with pytest.raises(build.BuildError, match="trio"):
        build.render_manifest(engine_assets(), engine_data(trios))


@pytest.mark.parametrize("slug", ["", "Pal-Mnk-Ber", "pal-mnk", "../x", "pal-mnk-ber/../x", "pal-mnk-ber.json", "constructor"])
def test_the_manifest_of_a_trio_is_written_only_for_a_trio_code(slug):
    data_files = engine_data({"pal-mnk-ber": [50]})
    with pytest.raises(build.BuildError, match="trio"):
        build.render_trio_manifest(slug, data_files)
    with pytest.raises(build.BuildError, match="trio"):
        build.trio_manifest_name(slug)


@pytest.mark.parametrize(
    "release",
    [
        {"data_release": ""}, {"data_release": "2026-10-14"}, {"data_release": "data-2026-10-14\n"}, {"data_release": None},
        {"rules_version": ""}, {"rules_version": "latest"}, {"rules_version": "2026-10-13 "}, {"rules_version": None},
    ],
)  # fmt: skip
def test_the_manifests_refuse_a_release_the_browser_would_not_read(release):
    with pytest.raises(build.BuildError, match="release|rules version"):
        build.render_manifest(engine_assets(), engine_data(**release))
    with pytest.raises(build.BuildError, match="release|rules version"):
        build.render_trio_manifest("pal-mnk-ber", engine_data(**release))


@pytest.mark.parametrize("levels", [[0], [101], [50.5], ["50"], [True], list(range(10, 100, 10))])
def test_the_manifests_refuse_levels_the_browser_would_not_read(levels):
    for render in (lambda d: build.render_manifest(engine_assets(), d), lambda d: build.render_trio_manifest("pal-mnk-ber", d)):
        with pytest.raises(build.BuildError, match="level"):
            render(engine_data({"pal-mnk-ber": levels}))


@pytest.mark.parametrize(
    "bad",
    ["/assets/engine/worker.js", "https://evil.example/worker-BBBBBBBB.js", "/assets/worker-BBBBBBBB.js", "/assets/engine/../worker-BBBBBBBB.js"],
)
def test_the_manifest_refuses_a_path_the_browser_would_not_load(bad):
    with pytest.raises(build.BuildError, match="engine file"):
        build.render_manifest(engine_assets(worker=bad), engine_data())


@pytest.mark.parametrize(
    "digest",
    [None, "", "0123456789ABCDEF" + "0" * 48, "0123456789abcdef" + "0" * 47, "0123456789abcdef" + "0" * 49, "g123456789abcdef" + "0" * 48, "fedcba9876543210" + "0" * 48],
    ids=["none", "empty", "capitals", "too short", "too long", "not hex", "not the one in the name"],
)
def test_the_manifest_refuses_a_webassembly_without_the_digest_the_worker_checks_it_by(digest):
    assets = engine_assets()
    wasm = build.EngineFile(assets.wasm.path, assets.wasm.bytes, assets.wasm.gzip, sha256=digest)
    bad = build.EngineAssets(highs=assets.highs, client=assets.client, worker=assets.worker, wasm=wasm, kitvalue=assets.kitvalue)
    with pytest.raises(build.BuildError, match="SHA-256"):
        build.render_manifest(bad, engine_data())


def test_the_files_that_are_checked_have_a_digest_in_the_manifest_and_the_two_scripts_of_the_optimizer_have_none():
    """The worker checks what it downloads by a digest: the WebAssembly, the item table and the bundles. The page checks the evaluator of a
    shared kit before it runs it. The browser loads the client and the worker from their hashed names, which nothing can check."""
    document = json.loads(build.render_manifest(engine_assets(), engine_data()))
    assert "sha256" not in document["client"] and "sha256" not in document["worker"]
    assert document["wasm"]["sha256"] == WASM_SHA256 and document["items"]["sha256"] == ITEMS_SHA256
    assert document["kitvalue"] == {"path": KITVALUE_PATH, "bytes": 60, "gzip": 25, "sha256": KITVALUE_SHA256}
    assert json.loads(build.render_trio_manifest("pal-mnk-ber", engine_data()))["bundles"]["50"]["sha256"] == BUNDLE_SHA256


@pytest.mark.parametrize(
    "bad",
    [
        "/assets/engine/kitvalue.js",
        "https://evil.example/assets/engine/kitvalue-CCCCCCCC.js",
        "/assets/kitvalue-CCCCCCCC.js",
        "/assets/engine/../kitvalue-CCCCCCCC.js",
        "/assets/engine/kitvalue-CCCCCCCC.js?x=1",
        "/assets/engine/kitvalue-cccccccc.js",
        "/assets/engine/client-CCCCCCCC.js",
        "/assets/engine/kitvalue-CCCCCCCC.wasm",
    ],
)
def test_the_manifest_refuses_an_evaluator_of_a_shared_kit_the_browser_would_not_load(bad):
    with pytest.raises(build.BuildError, match="engine file"):
        build.render_manifest(engine_assets(kitvalue=bad), engine_data())


@pytest.mark.parametrize(
    "digest",
    [None, "", "C0FFEE0123456789" + "3" * 48, "c0ffee0123456789" + "3" * 47, "c0ffee0123456789" + "3" * 49, "g0ffee0123456789" + "3" * 48],
    ids=["none", "empty", "capitals", "too short", "too long", "not hex"],
)
def test_the_manifest_refuses_an_evaluator_of_a_shared_kit_without_the_digest_the_page_checks_it_by(digest):
    with pytest.raises(build.BuildError, match="SHA-256"):
        build.render_manifest(engine_assets(kitvalue_sha256=digest), engine_data())


def test_the_evaluator_of_a_shared_kit_is_a_script_of_its_own_with_the_digest_of_its_file(site):
    """The page loads it for a kit link and nothing else loads it: it is a bundle of its own, listed with the SHA-256 of the bytes that are published, and the optimizer's
    client and worker do not carry it."""
    out, _ = site
    entry = engine_manifest(out)["kitvalue"]
    content = (out / entry["path"].lstrip("/")).read_bytes()
    assert entry["sha256"] == hashlib.sha256(content).hexdigest() and entry["bytes"] == len(content) and entry["gzip"] == gz(content)
    assert re.fullmatch(rf"/{ENGINE_DIR}/kitvalue-[A-Z0-9]{{8}}\.js", entry["path"]), entry["path"]
    text = content.decode("utf-8")
    assert not SINKS.search(text), SINKS.search(text).group(0)
    assert not re.search(r"""(?:\bfrom|\bimport)\s*["']node:""", text)
    assert "searchLimit is the most calls to the evaluator" in text  # (a message of kitvalue.js, which nothing else has)
    manifest = engine_manifest(out)
    for role in ("client", "worker"):
        other = (out / manifest[role]["path"].lstrip("/")).read_text(encoding="utf-8")
        assert "searchLimit is the most calls to the evaluator" not in other, f"the {role} carries the evaluator of a shared kit"
        assert "read from the kit" not in other
    # it imports nothing: the page loads one file for it (a script that imported another would be a second request for the visitor)
    assert not re.search(r"""(?m)^\s*import[\s{*"']""", text)


def test_the_optimizers_client_is_what_it_was_without_the_evaluator_of_a_shared_kit(site):
    """The client is loaded when the visitor says yes to the optimizer; it does not grow by what a kit link needs. It exported the evaluator before, and was 34,575 bytes
    gzipped for it, 18,768 without."""
    out, _ = site
    entry = engine_manifest(out)["client"]
    assert entry["gzip"] < 22 * 1024, entry
    client_source = (STATIC / "engine" / "client.js").read_text(encoding="utf-8")
    assert 'from "./kitvalue.js"' not in client_source


@pytest.mark.parametrize(
    "path",
    [
        "/assets/engine/data/items.json",
        "/assets/engine/data/items-89abcdef01234567.json",
        "/assets/engine/data/items-89ABCDEF0123456.json",
        "/assets/engine/data/items-89ABCDEF01234567.js",
        "/assets/engine/data/../items-89ABCDEF01234567.json",
        "/assets/data/items-89ABCDEF01234567.json",
        "https://evil.example/assets/engine/data/items-89ABCDEF01234567.json",
        "/assets/engine/data/items-89ABCDEF01234567.json?x=1",
        "/assets/engine/data/items-0000000000000000.json",  # a well-formed name that is not the one the digest gives
    ],
)
def test_the_manifest_refuses_an_item_table_the_browser_would_not_load_or_that_does_not_carry_its_digest(path):
    with pytest.raises(build.BuildError, match="items"):
        build.render_manifest(engine_assets(), engine_data(items=data_file(path, ITEMS_SHA256)))


@pytest.mark.parametrize("digest", [None, "", "89ABCDEF01234567" + "1" * 48, "89abcdef01234567" + "1" * 47, "g9abcdef01234567" + "1" * 48])
def test_the_manifest_refuses_a_data_file_without_the_digest_the_worker_checks_it_by(digest):
    with pytest.raises(build.BuildError, match="SHA-256"):
        build.render_manifest(engine_assets(), engine_data(items=data_file(ITEMS_PATH, digest)))
    bundles = {"pal-mnk-ber": {50: data_file("/assets/engine/data/pal-mnk-ber-l50-FEDCBA9876543210.json", digest)}}
    with pytest.raises(build.BuildError, match="SHA-256"):
        build.render_trio_manifest("pal-mnk-ber", build.EngineData(data_file(ITEMS_PATH, ITEMS_SHA256), bundles, **RELEASE))


@pytest.mark.parametrize(
    "path",
    [
        "/assets/engine/data/pal-shd-ber-l50-FEDCBA9876543210.json",  # another trio's
        "/assets/engine/data/pal-mnk-ber-l55-FEDCBA9876543210.json",  # another level's
        "/assets/engine/data/pal-mnk-ber-l50-fedcba9876543210.json",
        "/assets/engine/data/pal-mnk-ber-FEDCBA9876543210.json",
        "/assets/engine/data/pal-mnk-ber-l50-FEDCBA987654321.json",
        "/assets/engine/pal-mnk-ber-l50-FEDCBA9876543210.json",
        "/assets/engine/data/../pal-mnk-ber-l50-FEDCBA9876543210.json",
        "/assets/engine/data/pal-mnk-ber-l50-0000000000000000.json",  # not the name the digest gives
        "/assets/engine/data/pal-mnk-ber-l050-FEDCBA9876543210.json",  # the level with a zero in front
    ],
)
def test_the_manifest_of_a_trio_refuses_a_bundle_that_does_not_name_its_trio_its_level_and_its_digest(path):
    bundles = {"pal-mnk-ber": {50: data_file(path, BUNDLE_SHA256)}}
    with pytest.raises(build.BuildError, match="bundle"):
        build.render_trio_manifest("pal-mnk-ber", build.EngineData(data_file(ITEMS_PATH, ITEMS_SHA256), bundles, **RELEASE))


def test_the_engine_bundles_are_modules_without_string_sinks_and_without_static_node_imports(site):
    out, _ = site
    manifest = engine_manifest(out)
    for role in ("client", "worker", "kitvalue"):
        text = (out / manifest[role]["path"].lstrip("/")).read_text(encoding="utf-8")
        assert not SINKS.search(text), f"{role}: {SINKS.search(text).group(0)}"
        assert not re.search(r"""(?:\bfrom|\bimport)\s*["']node:""", text), f"{role} imports a Node module"
    worker = (out / manifest["worker"]["path"].lstrip("/")).read_text(encoding="utf-8")
    client = (out / manifest["client"]["path"].lstrip("/")).read_text(encoding="utf-8")
    assert not re.search(r"https?://", client), "the client names a site"
    # the solver's own text mentions one address, in the help of a message about the LP file format; nothing fetches it
    assert re.findall(r"""https?://[^\s"')]+""", worker) == ["http://web.mit.edu/lpsolve/doc/CPLEX-format.htm"]
    # the solver's own loader asks for a Node module only when it finds itself in Node; that import is left as it is (external)
    assert re.findall(r"""import\(\s*["']node:[a-z]+["']\s*\)""", worker) == ['import("node:module")']
    assert "instantiateWasm" in worker
    assert "trioforge" in client and "createScriptURL" in client
    assert "instantiateWasm" not in client  # the solver is only in the worker's file


def test_the_pages_do_not_load_the_engine(site):
    out, _ = site
    manifest = engine_manifest(out)
    for name, _html in all_html(out):
        text = read(out, name)
        for role in ("client", "worker", "wasm", "kitvalue"):
            assert manifest[role]["path"] not in text, f"{name} loads the optimizer on first view"
        assert "manifest.json" not in text


def test_the_engine_files_are_outside_the_default_page_budget_and_have_their_own():
    noise = random.Random(11)
    files = {
        "trio/pal-mnk-ber/index.html": b"<html></html>",
        "assets/app-AAAAAAAA.js": b"let a=1;",
        "assets/engine/client-AAAAAAAA.js": noise.randbytes(20 * 1024),
        "assets/engine/worker-BBBBBBBB.js": noise.randbytes(100 * 1024),
        "assets/engine/highs-0123456789ABCDEF.wasm": bytes(3_600_000),
    }
    sizes = build.check_budgets(
        files, trio_pages=["trio/pal-mnk-ber/index.html"], first_load_assets={"trio/pal-mnk-ber/index.html": ["assets/app-AAAAAAAA.js"]}
    )
    assert sizes["total_js"] == len(files["assets/app-AAAAAAAA.js"])  # the lazy engine is not JavaScript on a default page
    assert sizes["engine_js_gzip"] == gz(files["assets/engine/client-AAAAAAAA.js"]) + gz(files["assets/engine/worker-BBBBBBBB.js"])
    assert sizes["engine_wasm"] == 3_600_000


def kitvalue_budgets(content: bytes) -> dict[str, int]:
    files = {PAGE: b"<html></html>", "assets/app-AAAAAAAA.js": b"let a=1;", "assets/engine/kitvalue-CCCCCCCC.js": content}
    return build.check_budgets(files, trio_pages=[PAGE], first_load_assets={PAGE: ["assets/app-AAAAAAAA.js"]})


def test_the_evaluator_of_a_shared_kit_has_a_budget_of_its_own_and_is_not_in_the_optimizers():
    limits = (build.LIMITS["engine_kitvalue"], build.LIMITS["engine_kitvalue_gzip"])
    assert limits == (80 * 1024, 28 * 1024)
    noise = random.Random(14)
    files = {
        "trio/pal-mnk-ber/index.html": b"<html></html>",
        "assets/app-AAAAAAAA.js": b"let a=1;",
        "assets/engine/client-AAAAAAAA.js": noise.randbytes(20 * 1024),
        "assets/engine/worker-BBBBBBBB.js": noise.randbytes(100 * 1024),
        "assets/engine/kitvalue-CCCCCCCC.js": noise.randbytes(27 * 1024),
    }
    sizes = build.check_budgets(files, trio_pages=["trio/pal-mnk-ber/index.html"], first_load_assets={"trio/pal-mnk-ber/index.html": ["assets/app-AAAAAAAA.js"]})
    assert sizes["engine_kitvalue"] == 27 * 1024 and sizes["engine_kitvalue_gzip"] == gz(files["assets/engine/kitvalue-CCCCCCCC.js"])
    assert sizes["engine_js_gzip"] == gz(files["assets/engine/client-AAAAAAAA.js"]) + gz(files["assets/engine/worker-BBBBBBBB.js"])  # (the optimizer's two scripts: not this one)
    assert sizes["total_js"] == len(files["assets/app-AAAAAAAA.js"])  # and it is not JavaScript of a page


def test_the_raw_size_of_the_evaluator_of_a_shared_kit_is_held_to_the_byte():
    limit = build.LIMITS["engine_kitvalue"]
    assert kitvalue_budgets(compressible(limit))["engine_kitvalue"] == limit
    with pytest.raises(build.BudgetError, match=r"the evaluator of a shared kit is 80\.0 KB raw \(limit 80 KB\)") as caught:
        kitvalue_budgets(compressible(limit + 1))
    assert "gzip" not in str(caught.value) and "engine JS" not in str(caught.value)


def test_the_gzip_size_of_the_evaluator_of_a_shared_kit_is_held_to_the_byte():
    limit = build.LIMITS["engine_kitvalue_gzip"]
    assert kitvalue_budgets(incompressible(limit, seed=51))["engine_kitvalue_gzip"] == limit
    with pytest.raises(build.BudgetError, match=r"the evaluator of a shared kit is 28\.0 KB gzip \(limit 28 KB\)"):
        kitvalue_budgets(incompressible(limit + 1, seed=51))


def test_the_engine_budget_reports_what_is_broken():
    noise = random.Random(12)
    files = {
        "trio/pal-mnk-ber/index.html": b"<html></html>",
        "assets/app-AAAAAAAA.js": b"let a=1;",
        "assets/engine/client-AAAAAAAA.js": noise.randbytes(100 * 1024),
        "assets/engine/worker-BBBBBBBB.js": noise.randbytes(100 * 1024),  # 200 KB of incompressible JavaScript in all
        "assets/engine/highs-0123456789ABCDEF.wasm": bytes(5 * 1024 * 1024),
    }
    with pytest.raises(build.BudgetError) as caught:
        build.check_budgets(
            files, trio_pages=["trio/pal-mnk-ber/index.html"], first_load_assets={"trio/pal-mnk-ber/index.html": ["assets/app-AAAAAAAA.js"]}
        )
    message = str(caught.value)
    assert "engine JS" in message and "engine WebAssembly" in message, message
    assert "code loaded on first use" not in message and "first-load" not in message  # the page budgets are not what broke


DATA_ITEMS = "assets/engine/data/items-89ABCDEF01234567.json"
DATA_BUNDLE = "assets/engine/data/pal-mnk-ber-l50-FEDCBA9876543210.json"
PAGE = "trio/pal-mnk-ber/index.html"


def data_budget(files: dict[str, bytes]) -> dict[str, int]:
    """check_budgets on made-up files: a page, a script, and the data files given."""
    files = {PAGE: b"<html></html>", "assets/app-AAAAAAAA.js": b"let a=1;", **files}
    return build.check_budgets(files, trio_pages=[PAGE], first_load_assets={PAGE: ["assets/app-AAAAAAAA.js"]})


def test_the_data_files_of_the_engine_are_outside_the_page_budgets_and_have_their_own():
    noise = random.Random(13)
    files = {DATA_ITEMS: noise.randbytes(400 * 1024), DATA_BUNDLE: b" " * (64 * 1024)}  # as big as they may be, the bundle to the byte
    sizes = data_budget(files)
    assert sizes["total_js"] == len(b"let a=1;")  # they are not JavaScript on a page
    assert sizes["engine_items"] == 400 * 1024 and sizes["engine_items_gzip"] == gz(files[DATA_ITEMS])
    assert sizes["engine_bundle"] == 64 * 1024
    assert (build.LIMITS["engine_bundle"], build.LIMITS["engine_items"], build.LIMITS["engine_items_gzip"]) == (64 * 1024, 4 * 1024 * 1024, 512 * 1024)
    assert data_budget({})["engine_items"] == 0  # a build without the files has nothing to measure (the build itself will not be without them)


def test_a_bundle_over_64_kb_is_refused_and_the_error_names_the_file():
    with pytest.raises(build.BudgetError) as caught:
        data_budget({DATA_ITEMS: b"{}", DATA_BUNDLE: b" " * (64 * 1024 + 1)})
    message = str(caught.value)
    assert DATA_BUNDLE in message and "64 KB" in message and DATA_ITEMS not in message and "engine JS" not in message


def test_an_item_table_over_4_mb_raw_is_refused_though_it_gzips_small_and_the_error_names_the_file():
    with pytest.raises(build.BudgetError) as caught:
        data_budget({DATA_ITEMS: b" " * (4 * 1024 * 1024 + 1)})
    message = str(caught.value)
    assert DATA_ITEMS in message and "4 MB" in message and "gzip" not in message


def test_an_item_table_over_512_kb_gzip_is_refused_though_it_is_small_raw_and_the_error_names_the_file():
    noise = random.Random(14)
    table = noise.randbytes(560 * 1024)  # incompressible, and well under 4 MB
    assert gz(table) > 512 * 1024
    with pytest.raises(build.BudgetError) as caught:
        data_budget({DATA_ITEMS: table})
    message = str(caught.value)
    assert DATA_ITEMS in message and "512 KB gzip" in message and "4 MB" not in message


def test_a_build_refuses_a_data_file_over_its_budget_and_names_it(tmp_path, monkeypatch):
    need_node()
    monkeypatch.setitem(build.LIMITS, "engine_bundle", 1000)  # the synthetic bundle is about 21 KB
    with pytest.raises(build.BudgetError, match=r"assets/engine/data/pal-mnk-ber-l50-[A-Z0-9]{16}\.json"):
        run_build(tmp_path / "dist", tmp_path)
    assert not (tmp_path / "dist").exists()  # nothing was written


@pytest.mark.parametrize(
    ("name", "message"),
    [("items.json", r"^items\.json: file is missing"), ("pal-mnk-ber/engine-l50.json", r"pal-mnk-ber/engine-l50\.json: file is missing")],
)
def test_a_build_without_the_item_table_or_without_the_bundle_is_refused_naming_the_file(tmp_path, capsys, name, message):
    root = tmp_path / "results"
    shutil.copytree(RESULTS, root)
    (root / name).unlink()
    with pytest.raises(data.ResultsError, match=message):
        build.build(results=root, out=tmp_path / "dist", noindex=True, sources_manifest=MANIFEST, changelog=make_changelog(tmp_path))
    assert not (tmp_path / "dist").exists()
    code = build.main(["--results", str(root), "--out", str(tmp_path / "dist"), "--noindex", "--sources-manifest", str(MANIFEST), "--changelog", str(make_changelog(tmp_path))])
    assert code == 2 and re.search(message.removeprefix("^"), capsys.readouterr().err)


def test_the_command_line_reports_the_sizes_of_the_data_files(tmp_path):
    need_node()
    env = dict(os.environ, PYTHONPATH=str(REPO / "pipeline"))
    done = subprocess.run(
        [sys.executable, "-m", "trioforge.site.build", "--results", str(RESULTS), "--out", str(tmp_path / "dist"), "--noindex",
         "--sources-manifest", str(MANIFEST), "--changelog", str(make_changelog(tmp_path)), "--no-item-catalog"],
        capture_output=True, text=True, env=env, cwd=REPO, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert re.search(r"optimizer data \(loaded on request\): item table [0-9.]+ KB raw, [0-9.]+ KB gzip .*largest bundle [0-9.]+ KB raw", done.stdout), done.stdout


def test_a_missing_solver_package_stops_the_build(tmp_path, monkeypatch):
    need_node()
    monkeypatch.setattr(build, "HIGHS_WASM", tmp_path / "missing" / "highs.wasm")
    with pytest.raises(build.BuildError, match="npm ci"):
        run_build(tmp_path / "dist", tmp_path)


def test_the_command_line_reports_the_engine_sizes(tmp_path):
    need_node()
    env = dict(os.environ, PYTHONPATH=str(REPO / "pipeline"))
    done = subprocess.run(
        [sys.executable, "-m", "trioforge.site.build", "--results", str(RESULTS), "--out", str(tmp_path / "dist"), "--noindex",
         "--sources-manifest", str(MANIFEST), "--changelog", str(make_changelog(tmp_path)), "--no-item-catalog"],
        capture_output=True, text=True, env=env, cwd=REPO, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert re.search(r"optimizer \(loaded on request\): worker .* KB gzip, client .* KB gzip, WebAssembly [0-9.]+ MB", done.stdout), done.stdout
    assert re.search(r"evaluator of a shared kit \(loaded for a kit link\): [0-9.]+ KB raw \(limit 80 KB\), [0-9.]+ KB gzip \(limit 28 KB\)", done.stdout), done.stdout


def test_the_browser_code_asks_for_the_manifest_where_the_build_puts_it(site):
    """The two sides share no code, only a format and an address: run the real reader (static/engine/manifest.js) in Node."""
    need_node()
    out, _ = site
    manifest_js = (STATIC / "engine" / "manifest.js").as_uri()
    script = f"import {{ MANIFEST_PATH }} from {json.dumps(manifest_js)}; console.log(MANIFEST_PATH);"
    done = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False, cwd=REPO)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "/" + MANIFEST_FILE
    assert (out / done.stdout.strip().lstrip("/")).is_file()


def test_the_browser_code_reads_the_manifest_the_build_writes_and_works_out_the_same_size(site):
    """The two sides share no code, only a format: run the real reader (static/engine/manifest.js) on the real file in Node."""
    need_node()
    out, _ = site
    manifest_js = (STATIC / "engine" / "manifest.js").as_uri()
    written = out / MANIFEST_FILE
    slug = next(iter(engine_manifest(out)["trios"]))
    trio_file = out / build.trio_manifest_name(slug)
    script = (
        "import { readFileSync } from 'node:fs';"
        f"import {{ parseManifest, parseTrioManifest, downloadMegabytes }} from {json.dumps(manifest_js)};"
        f"const m = parseManifest(JSON.parse(readFileSync({json.dumps(str(written))}, 'utf8')));"
        f"const trio = parseTrioManifest(JSON.parse(readFileSync({json.dumps(str(trio_file))}, 'utf8')), m, {json.dumps(slug)});"
        "const bundle = [...trio.bundles.values()][0];"
        "console.log(JSON.stringify({ trios: [...m.trios.keys()], levels: [...m.trios.values()].map((t) => [...t.levels]), mb: downloadMegabytes(m),"
        " mbScenario: downloadMegabytes(m, { bundle }), mbAsked: downloadMegabytes(m, { bundle: null }) }));"
    )
    seen = node_json(script)
    manifest = engine_manifest(out)
    assert seen["trios"] == list(manifest["trios"]) and seen["levels"] == list(manifest["trios"].values())
    # the figure the visitor is asked about is what is downloaded: the gzip sizes of the worker and the WebAssembly, rounded up to a tenth
    # of a million bytes (not the sizes they have once unpacked, which are about three times as big)...
    base = manifest["worker"]["gzip"] + manifest["wasm"]["gzip"]
    assert seen["mb"] == -(-base // 100_000) / 10
    assert seen["mb"] < (manifest["worker"]["bytes"] + manifest["wasm"]["bytes"]) / 1_000_000 / 2
    # ... and for a scenario the item table and the bundle of the trio as well, the sizes the two manifests list
    bundle = next(iter(trio_manifest(out, slug)["bundles"].values()))
    assert seen["mbScenario"] == -(-(base + manifest["items"]["gzip"] + bundle["gzip"]) // 100_000) / 10
    assert seen["mbAsked"] == -(-(base + manifest["items"]["gzip"]) // 100_000) / 10  # (a question asked before any request names no trio)


def node_json(script: str) -> object:
    """Run a script of Node (an ES module, with the output as one line of JSON) in the repository and return what it printed."""
    # the script goes in by the standard input: the command line of a program on Windows is limited to 32,767 characters, and a script
    # that holds the manifests of 560 trios is longer
    done = subprocess.run(["node", "--input-type=module"], input=script, capture_output=True, text=True, check=False, cwd=REPO)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_browser_code_reads_the_manifests_as_the_build_lists_them(site):
    """The reader of the main manifest takes the item table and the levels as listed, and the reader of a trio's manifest takes each bundle (path,
    sizes, SHA-256) exactly as listed after the release of the main one, and nothing the build did not list."""
    need_node()
    out, _ = site
    manifest_js = (STATIC / "engine" / "manifest.js").as_uri()
    main = out / MANIFEST_FILE
    script = (
        "import { readFileSync } from 'node:fs';"
        f"import {{ parseManifest, parseTrioManifest, trioManifestPath }} from {json.dumps(manifest_js)};"
        f"const m = parseManifest(JSON.parse(readFileSync({json.dumps(str(main))}, 'utf8')));"
        "const trios = {};"
        "for (const [code, t] of m.trios) {"
        f"  const path = trioManifestPath(m, code); const text = readFileSync({json.dumps(str(out))} + path, 'utf8');"
        "  const parsed = parseTrioManifest(JSON.parse(text), m, code);"
        "  trios[code] = { path, levels: t.levels, bundles: Object.fromEntries(parsed.bundles), release: [parsed.dataRelease, parsed.rulesVersion] };"
        "}"
        "console.log(JSON.stringify({ items: m.items, release: [m.dataRelease, m.rulesVersion], trios }));"
    )
    seen = node_json(script)
    manifest = engine_manifest(out)
    assert seen["items"] == manifest["items"]
    assert seen["release"] == [manifest["data_release"], manifest["rules_version"]]
    assert list(seen["trios"]) == list(manifest["trios"])
    for slug, trio in seen["trios"].items():
        document = trio_manifest(out, slug)
        assert trio["path"] == "/" + build.trio_manifest_name(slug)
        assert trio["levels"] == manifest["trios"][slug]
        assert trio["bundles"] == {level: entry for level, entry in document["bundles"].items()}
        assert trio["release"] == seen["release"]
    for entry in [manifest["items"], *(file for slug in manifest["trios"] for file in trio_manifest(out, slug)["bundles"].values())]:
        assert set(entry) == {"path", "bytes", "gzip", "sha256"}
        assert (out / entry["path"].lstrip("/")).is_file()


def test_the_browser_code_holds_the_data_files_to_the_budgets_the_build_holds_them_to():
    """Two sides, two copies of one limit: a file the build lets through must be a file the reader of the manifest lets through, and no more."""
    need_node()
    manifest_js = (STATIC / "engine" / "manifest.js").as_uri()
    seen = node_json(f"import {{ DATA_LIMITS }} from {json.dumps(manifest_js)}; console.log(JSON.stringify(DATA_LIMITS));")
    assert seen == {"bundle": build.LIMITS["engine_bundle"], "items": build.LIMITS["engine_items"]}


def test_the_browser_code_holds_the_manifests_to_the_limits_the_build_holds_them_to():
    """The page and the worker refuse a manifest over a size (protocol.js LIMITS) and a list of trios or levels over a count (manifest.js
    MANIFEST_LIMITS). The build checks the same numbers, so a manifest that every optimizer would refuse is a build that fails. The numbers
    are written in two places; this holds them to each other."""
    need_node()
    manifest_js, protocol_js = ((STATIC / "engine" / name).as_uri() for name in ("manifest.js", "protocol.js"))
    script = (
        f"import {{ MANIFEST_LIMITS }} from {json.dumps(manifest_js)}; import {{ LIMITS }} from {json.dumps(protocol_js)};"
        "console.log(JSON.stringify({ manifest: LIMITS.maxManifestBytes, trio: LIMITS.maxTrioManifestBytes, trios: MANIFEST_LIMITS.trios, levels: MANIFEST_LIMITS.levels, level: MANIFEST_LIMITS.level }));"
    )
    seen = node_json(script)
    assert seen == {
        "manifest": build.LIMITS["manifest"], "trio": build.LIMITS["trio_manifest"],
        "trios": build.MANIFEST_MAX_TRIOS, "levels": build.MANIFEST_MAX_LEVELS, "level": build.MANIFEST_MAX_LEVEL,
    }  # fmt: skip
    assert build.LIMITS["trio_manifest"] < build.LIMITS["manifest"]


# ---- the size of the manifests -------------------------------------------------------------------------------------------------------------
# The first layout listed the bundles of every trio in the main manifest, about 218 bytes a trio: 560 trios at one level are 122 KB, over the 64 KB
# that the page and the worker accept, and a full build passed while every optimizer refused its manifest. Now the main manifest lists the levels of
# each trio and each trio has a manifest of its own, so the main one grows by some 24 bytes a trio.


def invented_trios(count: int) -> list[str]:
    """``count`` trio codes that no class list has, in a form the browser reads (three groups of three letters)."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    codes = []
    for n in range(count):
        a, b, c = n // 676 % 26, n // 26 % 26, n % 26
        codes.append(f"{letters[a]}{letters[b]}{letters[c]}-{letters[c]}{letters[a]}{letters[b]}-{letters[b]}{letters[c]}{letters[a]}")
    assert len(set(codes)) == count
    return codes


def test_the_manifests_of_560_invented_trios_at_two_levels_are_within_the_limits_of_the_browser():
    codes = invented_trios(560)
    data_files = engine_data({code: [50, 55] for code in codes})
    main = build.render_manifest(engine_assets(), data_files)
    trios = {code: build.render_trio_manifest(code, data_files) for code in codes}
    assert len(main) <= build.LIMITS["manifest"], len(main)
    assert len(main) < build.LIMITS["manifest"] // 2  # and with room to spare: the first layout needed 245 KB for this many trios at two levels
    assert max(len(raw) for raw in trios.values()) <= build.LIMITS["trio_manifest"]
    files = {build.MANIFEST_FILE: main, **{build.trio_manifest_name(code): raw for code, raw in trios.items()}}
    build.check_manifest_sizes(files)  # the check of the build accepts them
    document = json.loads(main)
    assert len(document["trios"]) == 560 and all(levels == [50, 55] for levels in document["trios"].values())
    # a trio manifest of a trio with all the levels it may list is within its own limit as well
    full = engine_data({"abc-def-ghi": [10, 20, 30, 40, 50, 60, 70, 80]})
    assert len(build.render_trio_manifest("abc-def-ghi", full)) < build.LIMITS["trio_manifest"] // 2


def test_the_browser_reads_the_manifests_of_560_invented_trios_the_build_wrote():
    need_node()
    codes = invented_trios(560)
    data_files = engine_data({code: [50, 55] for code in codes})
    main = build.render_manifest(engine_assets(), data_files).decode("utf-8")
    trios = {code: build.render_trio_manifest(code, data_files).decode("utf-8") for code in codes}
    manifest_js = (STATIC / "engine" / "manifest.js").as_uri()
    script = (
        f"import {{ parseManifest, parseTrioManifest }} from {json.dumps(manifest_js)};"
        f"const m = parseManifest(JSON.parse({json.dumps(main)}));"
        f"const trios = {json.dumps(trios)};"
        "let bundles = 0;"
        "for (const code of m.trios.keys()) bundles += parseTrioManifest(JSON.parse(trios[code]), m, code).bundles.size;"
        "console.log(JSON.stringify({ trios: m.trios.size, bundles }));"
    )
    assert node_json(script) == {"trios": 560, "bundles": 1120}


def test_a_manifest_over_the_limit_of_the_browser_is_refused_naming_the_file():
    codes = invented_trios(30)
    data_files = engine_data({code: [50] for code in codes})
    files = {build.MANIFEST_FILE: build.render_manifest(engine_assets(), data_files)}
    files.update({build.trio_manifest_name(code): build.render_trio_manifest(code, data_files) for code in codes})
    build.check_manifest_sizes(files)
    # one byte over the limit of the main manifest
    over = dict(files)
    over[build.MANIFEST_FILE] = files[build.MANIFEST_FILE] + b" " * (build.LIMITS["manifest"] - len(files[build.MANIFEST_FILE]) + 1)
    with pytest.raises(build.BuildError, match=r"engine-manifest\.json.*limit") as error:
        build.check_manifest_sizes(over)
    assert "engine-trios" not in str(error.value)  # only the file that is over is named
    # one byte over the limit of a trio's
    name = build.trio_manifest_name(codes[7])
    over = dict(files)
    over[name] = files[name] + b" " * (build.LIMITS["trio_manifest"] - len(files[name]) + 1)
    with pytest.raises(build.BuildError, match=re.escape(name) + ".*limit"):
        build.check_manifest_sizes(over)
    # exactly the limit is accepted
    exact = dict(files)
    exact[name] = files[name][:-1] + b" " * (build.LIMITS["trio_manifest"] - len(files[name])) + b"\n"
    assert len(exact[name]) == build.LIMITS["trio_manifest"]
    build.check_manifest_sizes(exact)
    # and every manifest over its limit is named, not only the first
    both = dict(over)
    both[build.MANIFEST_FILE] = files[build.MANIFEST_FILE] + b" " * build.LIMITS["manifest"]
    with pytest.raises(build.BuildError) as error:
        build.check_manifest_sizes(both)
    assert build.MANIFEST_FILE in str(error.value) and name in str(error.value)


def test_a_build_whose_manifests_are_over_the_limits_fails_and_names_the_file(tmp_path, monkeypatch):
    need_node()
    monkeypatch.setitem(build.LIMITS, "trio_manifest", 100)
    with pytest.raises(build.BuildError, match=r"engine-trios/pal-mnk-ber\.json.*limit"):
        run_build(tmp_path / "dist", tmp_path, noindex=True)
    assert not (tmp_path / "dist").exists()
    monkeypatch.setitem(build.LIMITS, "trio_manifest", 8 * 1024)
    monkeypatch.setitem(build.LIMITS, "manifest", 100)
    with pytest.raises(build.BuildError, match=r"engine-manifest\.json.*limit"):
        run_build(tmp_path / "dist", tmp_path, noindex=True)


def test_a_build_reports_the_code_loaded_on_first_use_in_all_and_for_its_largest_chunk(tmp_path, capsys):
    need_node()
    code = build.main(
        [
            "--results", str(RESULTS), "--out", str(tmp_path / "dist"), "--noindex", "--sources-manifest", str(MANIFEST),
            "--changelog", str(make_changelog(tmp_path)),
        ]
    )  # fmt: skip
    assert code == 0
    report = capsys.readouterr().out
    assert re.search(
        r"code loaded on first use \([0-9]+ chunks\): [0-9.]+ KB raw in all \(limit 250 KB\); the largest chunk [0-9.]+ KB raw \(limit 100 KB\), [0-9.]+ KB gzip \(limit 40 KB\)", report
    ), report


def test_a_build_reports_the_sizes_of_the_manifests(tmp_path, capsys):
    need_node()
    out = tmp_path / "dist"
    code = build.main(
        [
            "--results", str(RESULTS), "--out", str(out), "--noindex", "--sources-manifest", str(MANIFEST),
            "--changelog", str(make_changelog(tmp_path)),
        ]
    )  # fmt: skip
    assert code == 0
    report = capsys.readouterr().out
    assert re.search(r"manifests \(loaded on request\): engine-manifest\.json [0-9.]+ KB \(limit 64 KB\), largest trio manifest [0-9]+ bytes \(limit 8 KB\)", report), report



# ---- the engine's own readers run on what the build publishes ---------------------------------------------------------------------------------
# data.py holds the two data files to the limits of the browser's readers, and the build runs those readers themselves (static/engine/items.js and
# profile.js, in Node, by check_engine_data.mjs) on the item table and the bundles it is about to publish: the item table with readItemTable and then
# atTier at every tier of every record, each bundle with readBundle, the compilation of its tier and weapon rules and assembleProfile for every race, role,
# buff set and evidence level it lists. Whatever data.py lets through that the worker would refuse stops the build, with the file and the record named.


def engine_files(change_table=None, change_bundle=None, *, slug="pal-mnk-ber"):
    """The item table and the trio of the fixture as the build holds them, with a change made to the document of either, written out again (the build's
    own reader, data.py, is not asked: this is what the engine's readers say on their own)."""
    results = data.load_trio(RESULTS / slug)
    table = data.load_items(RESULTS, [results])

    def rewritten(file, change):
        document = json.loads(json.dumps(file.document))
        if change is not None:
            change(document)
        return dataclasses.replace(file, raw=json.dumps(document).encode("utf-8"), document=document)

    return rewritten(table, change_table), dataclasses.replace(results, bundle=rewritten(results.bundle, change_bundle))


def record_of(document, key):
    return next(r for r in document["items"] if (r.get("key") or f"w{r['id']}") == key)


def test_the_engines_readers_take_the_fixture_and_the_build_says_what_they_went_through():
    need_node()
    table, results = engine_files()
    report = build.check_engine_data(table, [results])
    assert report["records"] == table.document["count"] == 48
    assert report["bundles"] == 1
    bundle = results.bundle.document
    assert report["profiles"] == len(bundle["races"]) * len(bundle["roles"]) * len(bundle["buffs"]) * len(bundle["evidence_levels"])
    assert report["tiers"] == 11  # atTier at +0 to +10 for every record


SIX_WAYS = {
    "17 deities": lambda r: r.update(deity=[f"God {n}" for n in range(17)]),
    "17 races": lambda r: r.update(races=[f"R{n:02d}" for n in range(17)]),
    "an item type of 41 characters": lambda r: r.update(item_type="x" * 41, item_type_source=None),
    "a name with a line separator": lambda r: r.update(name="Cap of the\u2028Stoneward"),
    "41 reason codes": lambda r: r["evidence"].update(codes=[f"code-{n}" for n in range(41)]),
    "a stat the model does not know": lambda r: r.update(stats={**r.get("stats", {}), "FOO": 3}),
}


@pytest.mark.parametrize("name", list(SIX_WAYS))
def test_the_engines_own_reader_refuses_a_record_that_data_py_might_let_through_and_names_the_file_and_the_record(name):
    need_node()
    table, results = engine_files(lambda d: SIX_WAYS[name](record_of(d, "w90001")))
    with pytest.raises(build.BuildError) as caught:
        build.check_engine_data(table, [results])
    text = str(caught.value)
    assert text.startswith("items.json") or "items.json" in text
    assert "w90001" in text and "\n" not in text, text


@pytest.mark.parametrize("name", list(SIX_WAYS))
def test_the_build_refuses_one_record_mutated_six_ways_and_names_the_file_and_the_record(tmp_path, capsys, name):
    need_node()
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    path = results / "items.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    SIX_WAYS[name](record_of(document, "w90001"))
    path.write_text(json.dumps(document), encoding="utf-8")
    code = build.main(
        [
            "--results", str(results), "--out", str(tmp_path / "dist"), "--noindex", "--sources-manifest", str(MANIFEST),
            "--changelog", str(make_changelog(tmp_path)),
        ]
    )  # fmt: skip
    assert code == 2
    refusal = capsys.readouterr().err.strip()
    assert "items.json" in refusal and "w90001" in refusal and "\n" not in refusal, refusal
    assert not (tmp_path / "dist").exists()


def test_a_resist_that_the_model_does_not_know_is_refused_by_the_engines_reader_with_the_record_named():
    need_node()
    table, results = engine_files(lambda d: record_of(d, "w90001").update(sv={"AC": 3}))  # a stat's name where a school's goes
    with pytest.raises(build.BuildError, match=r"items\.json.*w90001"):
        build.check_engine_data(table, [results])


def test_a_bundle_whose_tier_rules_the_engine_cannot_use_is_refused_with_the_file_named():
    need_node()
    for change in (lambda d: d["tier_rules"].update(stat_rule="base + n"), lambda d: d["weapon_rules"].update(damage_rule="dmg")):
        table, results = engine_files(change_bundle=change)
        with pytest.raises(build.BuildError) as caught:
            build.check_engine_data(table, [results])
        text = str(caught.value)
        assert "pal-mnk-ber/engine-l50.json" in text and "rules" in text and "\n" not in text, text


def test_a_bundle_that_is_not_what_the_engines_reader_takes_is_refused_with_the_file_named():
    need_node()
    table, results = engine_files(change_bundle=lambda d: d["roles"]["balanced"].update(setups=[]))
    with pytest.raises(build.BuildError, match=r"pal-mnk-ber/engine-l50\.json"):
        build.check_engine_data(table, [results])


def test_bundles_with_other_tier_rules_are_refused_because_the_item_table_is_worked_out_under_one_set():
    need_node()
    table, first = engine_files()
    other = dataclasses.replace(first, meta=dataclasses.replace(first.meta, slug="pal-shd-ber"))
    document = json.loads(json.dumps(first.bundle.document))
    document["tier_rules"]["haste_per_tier"] = "2/1"
    other = dataclasses.replace(other, bundle=dataclasses.replace(first.bundle, raw=json.dumps(document).encode("utf-8"), document=document))
    with pytest.raises(build.BuildError, match=r"pal-shd-ber/engine-l50\.json.*rules.*differ"):
        build.check_engine_data(table, [first, other])


def test_the_check_is_part_of_the_build_and_runs_on_the_files_it_publishes(tmp_path, monkeypatch):
    need_node()
    seen = []
    real = build.check_engine_data

    def spy(items, trios):
        seen.append((items.raw, [trio.bundle.raw for trio in trios]))
        return real(items, trios)

    monkeypatch.setattr(build, "check_engine_data", spy)
    out = tmp_path / "dist"
    run_build(out, tmp_path, noindex=True)
    assert len(seen) == 1
    manifest = engine_manifest(out)
    assert seen[0][0] == (out / manifest["items"]["path"].lstrip("/")).read_bytes()
    assert seen[0][1] == [(out / trio_manifest(out, "pal-mnk-ber")["bundles"]["50"]["path"].lstrip("/")).read_bytes()]


def test_a_bundle_that_data_py_takes_and_the_engine_refuses_stops_the_build_before_anything_is_written(tmp_path):
    """The tier rules are a text and a few exact numbers as far as data.py can tell; the engine compiles them."""
    need_node()
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    path = results / "pal-mnk-ber" / "engine-l50.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["tier_rules"]["stat_rule"] = "base + n"
    path.write_text(json.dumps(document), encoding="utf-8")
    data.load_items(results, [data.load_trio(results / "pal-mnk-ber")])  # (data.py takes it)
    with pytest.raises(build.BuildError, match=r"pal-mnk-ber/engine-l50\.json.*rules"):
        run_build(tmp_path / "dist", tmp_path, noindex=True, results=results)
    assert not (tmp_path / "dist").exists()


def test_the_command_line_reports_what_the_engines_readers_went_through(tmp_path, capsys):
    need_node()
    code = build.main(
        [
            "--results", str(RESULTS), "--out", str(tmp_path / "dist"), "--noindex", "--sources-manifest", str(MANIFEST),
            "--changelog", str(make_changelog(tmp_path)),
        ]
    )  # fmt: skip
    assert code == 0
    report = capsys.readouterr().out
    assert re.search(r"engine data checked with the engine's own readers: 48 item records at \d+ tiers, 1 bundle with \d+ profiles", report), report


# ---- the Upgrade section ------------------------------------------------------------------------------------------------------------------------
# The last section of a trio page: the gear the visitor has, read from a file of /outputfile inventory or typed in. Its controls are in the page,
# switched off until the page code enables them, so that a first focus or click can wake the code of the section (static/ui/upgrade-input.js and
# gear-picker.js), which is a chunk of its own that no page loads by itself.


def upgrade_section(out: Path):
    main = page(out, PAGES["trio"]).find("main")
    return main, main.by_id("upgrade")


def element_children(node):
    return [child for child in node.children if not isinstance(child, str)]


def test_the_upgrade_section_closes_the_trio_page_and_says_where_the_file_goes(site):
    out, _ = site
    main, section = upgrade_section(out)
    assert section.tag == "section" and section.parent is main
    assert element_children(main)[-1] is section  # after the weapons section and the expanders, at the end of main
    order = [n.get("id") for n in main.iter() if n.get("id") in ("weapons", "runnerups", "robust", "upgrade")]
    assert order == ["weapons", "runnerups", "robust", "upgrade"]
    heading = section.by_id("upgrade-h")
    assert heading.tag == "h2" and heading.text() == "Upgrade from the gear you have"
    assert section.get("aria-labelledby") == "upgrade-h"
    assert heading.get("tabindex") == "-1"  # the focus goes here when a retry has worked and its button is gone
    assert "read in this browser and is never uploaded" in section.text()
    assert section.get("data-trio") == "pal-mnk-ber"  # the classes of the trio, which the item picker is filtered by
    assert "needs JavaScript" in section.find("noscript").text()


def test_the_upgrade_section_says_the_level_of_the_page_and_keeps_an_empty_place_for_the_answer_under_the_list_of_the_gear(site):
    out, _ = site
    main, section = upgrade_section(out)
    level = re.search(r"level (\d+)", main.find("h1").text())
    assert level is not None and section.get("data-level") == level.group(1)  # the level a request to the optimizer names: the page's own
    results = section.by_id("upgrade-results")
    assert results.tag == "div" and results.children == [] and set(results.attrs) == {"id"}  # empty: the code of the section makes the answer, from text
    siblings = element_children(section)
    box = section.by_id("upgrade-motes-open").parent  # the box that opens Spend your motes (the panel is made under it by the code of the section)
    assert siblings[siblings.index(section.by_id("upgrade-owned")) + 1] is results and siblings[-2] is results and siblings[-1] is box  # directly under the list of the gear, then the box, at the end


def test_every_control_of_the_upgrade_section_has_a_label_and_waits_for_the_page_code(site):
    out, _ = site
    _, section = upgrade_section(out)
    controls = {n.get("id"): n for n in section.iter() if n.tag in ("input", "select", "button")}
    assert list(controls) == ["upgrade-file", "upgrade-pick", "upgrade-tier", "upgrade-add", "upgrade-clear", "upgrade-motes-open"]
    for ident in ("upgrade-file", "upgrade-pick", "upgrade-tier", "upgrade-motes-open"):
        assert section.find("label", **{"for": ident}).text(), ident  # a visible label for each field
        assert controls[ident].has("disabled") and controls[ident].has("data-wake"), ident  # the page code enables these, and a focus on one wakes the section
    assert controls["upgrade-motes-open"].get("type") == "checkbox" and not controls["upgrade-motes-open"].has("checked")  # the box that opens Spend your motes: off
    assert section.find("label", **{"for": "upgrade-motes-open"}).text() == "Spend motes"
    assert controls["upgrade-add"].has("disabled") and not controls["upgrade-add"].has("data-wake")  # the section enables it when the item list is in
    assert controls["upgrade-clear"].has("hidden") and controls["upgrade-clear"].text() == "Clear"
    assert controls["upgrade-clear"].get("aria-label") == "Clear all gear"  # the name starts with the word on the button
    assert controls["upgrade-clear"].parent is section.by_id("upgrade-owned-h").parent  # in the row of the heading, where it is found without scrolling a long list
    assert section.find_all("form") == [] and section.find_all("a") == []


def test_the_drop_zone_is_the_label_of_the_file_input_and_follows_it(site):
    out, _ = site
    _, section = upgrade_section(out)
    file_input = section.by_id("upgrade-file")
    drop = section.find("label", **{"for": "upgrade-file"})
    assert file_input.get("type") == "file" and not file_input.has("multiple") and not file_input.has("accept")
    assert drop.get("id") == "upgrade-drop" and "dropzone" in drop.classes and "inventory file" in drop.text()
    siblings = element_children(file_input.parent)
    assert siblings.index(drop) == siblings.index(file_input) + 1  # the label follows its input, so that the stylesheet can draw the focus on it
    assert section.by_id(file_input.get("aria-describedby")).tag == "p"
    assert "/outputfile inventory" in section.by_id("upgrade-file-help").text()


def test_the_item_picker_is_marked_up_as_the_aria_list_autocomplete_combobox(site):
    out, _ = site
    _, section = upgrade_section(out)
    combo = section.by_id("upgrade-pick")
    assert combo.tag == "input" and combo.get("type") == "text" and combo.get("role") == "combobox"
    assert combo.get("aria-autocomplete") == "list" and combo.get("aria-expanded") == "false" and combo.get("aria-controls") == "upgrade-list"
    assert combo.get("autocomplete") == "off" and combo.get("maxlength") == "100"
    assert not combo.has("aria-activedescendant")  # set only while an option has the visual focus
    listbox = section.by_id("upgrade-list")
    assert listbox.tag == "ul" and listbox.get("role") == "listbox" and listbox.has("hidden") and listbox.get("aria-label")
    assert listbox.children == []  # the options come with the item list
    tier = section.by_id("upgrade-tier")
    options = [(o.get("value"), o.text()) for o in tier.find_all("option")]
    assert options == [(str(n), f"+{n}") for n in range(11)]  # +0 to +10, and +0 is the first and so the default
    assert not [o for o in tier.find_all("option") if o.has("selected")]
    assert section.by_id("upgrade-add").text() == "Add"


def test_the_list_of_the_gear_is_named_by_its_heading_and_empty_until_the_code_fills_it(site):
    out, _ = site
    _, section = upgrade_section(out)
    heading = section.by_id("upgrade-owned-h")
    assert heading.tag == "h3" and heading.get("tabindex") == "-1" and heading.text() == "Your gear"
    owned = section.by_id("upgrade-owned")
    assert owned.tag == "ul" and owned.get("aria-labelledby") == "upgrade-owned-h" and owned.children == []
    assert section.by_id("upgrade-empty").text().startswith("Nothing yet")
    load = section.by_id("upgrade-load")
    assert load.get("role") is None and load.get("aria-live") is None  # not a live region: the page has two (#status and #announce), and what the section shows is said through the second
    assert "quiet" in load.classes and load.children == []
    assert section.by_id("upgrade-feedback").children == []  # the notes, the banner and the warnings are made when there is something to say


def test_the_upgrade_section_adds_no_live_region_to_the_trio_page(site):
    out, _ = site
    main = page(out, PAGES["trio"]).find("main")
    live = [n.get("id") for n in main.iter() if n.get("role") in ("status", "alert", "log") or n.get("aria-live") is not None]
    assert live == ["status", "announce"], live  # one voice for what the section says: the page's #announce


def test_the_item_picker_asks_a_keyboard_not_to_correct_what_is_typed(site):
    out, _ = site
    _, section = upgrade_section(out)
    combo = section.by_id("upgrade-pick")
    assert combo.get("autocorrect") == "off" and combo.get("spellcheck") == "false" and combo.get("autocomplete") == "off"  # item names are not words of a dictionary


def test_no_page_loads_the_code_of_the_upgrade_section_by_itself(site):
    out, _ = site
    for name, html in all_html(out):
        scripts = [(s.get("src").split("-")[0], s.get("type")) for s in html.find_all("script")]
        allowed = ("/assets/boot", "/assets/notfound") if name == NOT_FOUND else ("/assets/boot", "/assets/app")  # (the 404 page has a script of its own in place of the page script)
        assert all(src in allowed for src, _ in scripts), (name, scripts)  # no script tag for the section's code
        assert "upgrade-input" not in read(out, name) and "gear-picker" not in read(out, name), name
    app = next((out / "assets").glob("app-*.js")).read_text(encoding="utf-8")
    assert "createGearInput" not in app and "createGearPicker" not in app  # it is not in the page script, which only knows where to import it from


def test_the_stylesheet_draws_the_focus_of_the_file_input_on_its_drop_zone_and_the_open_list_over_the_page():
    css = css_text()
    assert "opacity: 0" in rule_body(css, ".dz-input") and "position: absolute" in rule_body(css, ".dz-input")
    assert "outline: 3px solid var(--focus)" in rule_body(css, ".dz-input:focus-visible + .dropzone")
    listbox = rule_body(css, ".listbox")
    assert "position: absolute" in listbox and "overflow-y: auto" in listbox and "max-height" in listbox
    assert "outline: 2px solid var(--focus)" in rule_body(css, '.listbox li[aria-selected="true"]')  # the option with the visual focus is drawn apart
    assert "outline: 2px solid Highlight" in rule_body(media_block(css, "(forced-colors: active)"), '.listbox li[aria-selected="true"]')


# ---- the code of the Upgrade section is a chunk of its own ------------------------------------------------------------------------------------------
# The page script (app.js) imports the section's code by a dynamic import the first time the section is used, so that the page's first load does not carry the parser, the
# matcher, the readers of the item table and the picker. esbuild splits the chunk off (--splitting); the budget of the first load counts the page script and the stylesheet
# only, so the build refuses a split that would make the page script import a chunk at once (the budget would then say less than the page loads).


def test_the_page_script_loads_the_upgrade_chunk_by_a_dynamic_import_and_imports_nothing_at_once(site):
    out, _ = site
    chunks = sorted((out / "assets").glob("upgrade-input-*.js"))
    assert len(chunks) == 1 and re.fullmatch(r"upgrade-input-[A-Z0-9]{8}\.js", chunks[0].name), chunks
    app = next((out / "assets").glob("app-*.js")).read_text(encoding="utf-8")
    assert f'import("./{chunks[0].name}")' in app
    assert not re.search(r"""(?<![\w$.])import\s*[{*"'\w$]""", app), "the page script imports something at once"
    # no chunk shared by the page script and the section: the files under assets/ are the page's, its stylesheet, the section's, the code of a shared kit (a chunk of its own, which the
    # section loads by a dynamic import), the sliders' (a chunk of its own as well) and the modules that those share (the chunks that esbuild makes of them), and the optimizer's folder
    names = sorted({p.name.split("-")[0] for p in (out / "assets").iterdir() if p.is_file() and p.suffix != ".png"})  # (the pictures of the theme are PNGs beside the stylesheet)
    assert names == ["app", "boot", "chunk", "exalt", "notfound", "shared", "site", "upgrade", "weights"]  # (notfound: the 404 page's own script, a bundle that shares nothing with the page script)
    chunk = chunks[0].read_text(encoding="utf-8")
    assert "initUpgrade" in chunk and "createGearInput" in chunk and "createGearInput" not in app


def test_what_the_section_adds_is_counted_apart_from_the_first_load(site):
    out, summary = site
    lazy = [p.read_bytes() for p in sorted((out / "assets").glob("*.js")) if p.name.split("-")[0] in ("upgrade", "shared", "weights", "exalt", "chunk")]
    assert len(lazy) == len(list((out / "assets").glob("*.js"))) - 3  # (every script but the page script, the boot script and the 404 page's own script is loaded on first use)
    assert summary.sizes["lazy_js"] == sum(len(c) for c in lazy) and summary.sizes["lazy_js_gzip"] == sum(gz(c) for c in lazy)  # (all the code loaded on first use: the sum of its chunks)
    app = next((out / "assets").glob("app-*.js")).read_bytes()
    boot = next((out / "assets").glob("boot-*.js")).read_bytes()
    notfound = next((out / "assets").glob("notfound-*.js")).read_bytes()
    assert summary.sizes["first_load_js_gzip"] == gz(app) + gz(boot)  # the first load is the page script and the boot script, as before
    assert summary.sizes["first_load_js"] == len(app) + len(boot)  # the first load's raw size is the two that the page loads by itself
    assert summary.sizes["total_js"] == len(app) + len(boot) + len(notfound) + sum(len(c) for c in lazy)  # the total of all of them (the 404 page's script too) is reported, and is no budget


#: the files of the code of the Upgrade section, by the names esbuild's metafile gives its inputs (relative to the folder it runs in, static/)
LAZY_INPUTS = ["ui/upgrade-input.js", "ui/gear-picker.js", "input/dump.js", "input/match.js", "ui/remember.js", "ui/share.js", "input/kitcode.js"]
#: the files of the code of a shared kit (the panel and the decoder of the link): a chunk of its own, which the section loads by a dynamic import when a kit link is opened
KIT_INPUTS = ["ui/shared-kit.js", "input/kitdecode.js"]
#: the files the page script holds: the one that takes a kit link out of the address first, and the function it calls (the codec of the link is the section's)
PAGE_INPUTS = ["first.js", "input/kitlocation.js"]


def shaped_metafile(page_inputs, chunk_inputs, taking=tuple(PAGE_INPUTS), kit_inputs=tuple(KIT_INPUTS)):
    """A metafile like esbuild's for a page script that loads a chunk by a dynamic import, which loads another the same way: the inputs that each output was made of (the page script
    holds ``taking`` besides ``page_inputs``; the chunk of the section ``chunk_inputs``; the chunk of a shared kit ``kit_inputs``)."""
    lazy = {"path": "upgrade-input-CCCCCCCC.js", "kind": "dynamic-import"}
    kit = {"path": "shared-kit-EEEEEEEE.js", "kind": "dynamic-import"}
    made = lambda names: {name: {"bytesInOutput": 10} for name in names}  # noqa: E731
    outputs = {"app-AAAAAAAA.js": {"entryPoint": "app.js", "imports": [lazy], "inputs": made([*page_inputs, *taking])}, "site-DDDDDDDD.css": {"imports": [], "inputs": made(["site.css"])}}
    if chunk_inputs is not None:
        outputs["upgrade-input-CCCCCCCC.js"] = {"entryPoint": "ui/upgrade-input.js", "imports": [kit], "inputs": made(chunk_inputs)}
    if kit_inputs is not None:
        outputs["shared-kit-EEEEEEEE.js"] = {"entryPoint": "ui/shared-kit.js", "imports": [], "inputs": made(kit_inputs)}
    return {"outputs": outputs}


@pytest.mark.parametrize("name", [*LAZY_INPUTS, *KIT_INPUTS])
def test_a_page_script_that_holds_the_code_of_the_upgrade_section_is_refused(name):
    # a static import of the code makes esbuild inline it in the page script with no import statement at all: the check of the imports passes, and the first load is not what it says
    meta = shaped_metafile(["app.js", "trio.js", name], LAZY_INPUTS)
    with pytest.raises(build.BuildError, match=rf"page script.*{re.escape(name)}"):
        build.check_page_script(meta)
    long_form = shaped_metafile(["app.js", f"pipeline/trioforge/site/static/{name}"], LAZY_INPUTS)  # (a path that is not relative to static/ is the same file)
    with pytest.raises(build.BuildError, match="page script"):
        build.check_page_script(long_form)


def test_a_build_in_which_no_other_output_holds_the_code_of_the_upgrade_section_is_refused():
    build.check_page_script(shaped_metafile(["app.js", "trio.js"], LAZY_INPUTS))
    with pytest.raises(build.BuildError, match="Upgrade section"):
        build.check_page_script(shaped_metafile(["app.js", "trio.js"], None))  # not in the page script, and not anywhere: it was left out of the build
    for missing in LAZY_INPUTS:
        with pytest.raises(build.BuildError, match=re.escape(missing)):
            build.check_page_script(shaped_metafile(["app.js"], [name for name in LAZY_INPUTS if name != missing]))
    for missing in KIT_INPUTS:
        with pytest.raises(build.BuildError, match=re.escape(missing)):
            build.check_page_script(shaped_metafile(["app.js"], LAZY_INPUTS, kit_inputs=[name for name in KIT_INPUTS if name != missing]))
    with pytest.raises(build.BuildError, match=re.escape(KIT_INPUTS[0])):
        build.check_page_script(shaped_metafile(["app.js"], LAZY_INPUTS, kit_inputs=None))  # no chunk for a shared kit at all


@pytest.mark.parametrize("name", KIT_INPUTS)
def test_a_chunk_of_the_section_that_holds_the_code_of_a_shared_kit_is_refused(name):
    """The panel and the decoder of a kit link are loaded only when a kit link is opened; a static import of either from the section puts it in the section's chunk, which every
    visitor of the section loads."""
    others = [other for other in KIT_INPUTS if other != name]
    with pytest.raises(build.BuildError, match=rf"holds {re.escape(name)}.*shared kit"):
        build.check_page_script(shaped_metafile(["app.js", "trio.js"], [*LAZY_INPUTS, name], kit_inputs=others))
    with pytest.raises(build.BuildError, match=rf"holds {re.escape(name)}.*shared kit"):
        build.check_page_script(shaped_metafile(["app.js", "trio.js"], [*LAZY_INPUTS, name]))  # (the chunk of the kit has it as well: it is the section's chunk that may not)
    build.check_page_script(shaped_metafile(["app.js", "trio.js"], LAZY_INPUTS))


def tiny_bundle(tmp_path, page_source, *, static_kit=False):
    """Bundle a tiny page script and a tiny copy of the files of the Upgrade section with the options of the build; returns the metafile. The section loads the code of a shared kit
    (the panel, which imports the decoder and the module that Share is made of) by a dynamic import, or, with ``static_kit``, by a static one."""
    loads_kit = 'import "./shared-kit.js";\n' if static_kit else ""
    files = {
        "app.js": page_source,
        "first.js": 'import "./input/kitlocation.js";\nglobalThis.first = 5;\n',
        "input/kitlocation.js": "globalThis.take = 6;\n",
        "ui/upgrade-input.js": f'import "./gear-picker.js";\nimport "../input/dump.js";\nimport "../input/match.js";\nimport "./remember.js";\nimport "./share.js";\n{loads_kit}import "../input/kitcode.js";\nglobalThis.section = 1;\nglobalThis.kit = () => import("./shared-kit.js");\n',
        "ui/gear-picker.js": "globalThis.picker = 2;\n",
        "input/dump.js": "globalThis.dump = 3;\n",
        "input/match.js": "globalThis.match = 4;\n",
        "ui/remember.js": 'import "../input/kitcode.js";\nglobalThis.remember = 7;\n',
        "ui/share.js": 'import "../input/kitcode.js";\nglobalThis.share = 8;\n',
        "ui/shared-kit.js": 'import "../input/kitdecode.js";\nimport "./share.js";\nglobalThis.shared = 9;\n',
        "input/kitdecode.js": 'import "./kitcode.js";\nglobalThis.decode = 11;\n',
        "input/kitcode.js": "globalThis.codec = 10;\n",
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    node, esbuild = shutil.which("node"), build.REPO_ROOT / "node_modules" / "esbuild" / "bin" / "esbuild"
    if node is None or not esbuild.is_file():
        pytest.skip("Node and esbuild are needed")
    done = subprocess.run(
        [node, str(esbuild), "--bundle", "--format=esm", "--splitting", f"--metafile={tmp_path / 'meta.json'}", f"--outdir={tmp_path / 'out'}", "--log-level=warning", "app.js"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))


def test_a_real_bundle_with_a_static_import_of_the_code_of_the_upgrade_section_is_refused_and_one_with_a_dynamic_import_is_not(tmp_path):
    static = tiny_bundle(tmp_path / "static", 'import "./first.js";\nimport "./ui/upgrade-input.js";\nglobalThis.page = 1;\n')
    pages = [info for info in static["outputs"].values() if str(info.get("entryPoint", "")).endswith("app.js")]
    assert len(pages) == 1 and any(name.endswith("ui/upgrade-input.js") for name in pages[0]["inputs"])  # (esbuild put the code in the page script, with no import statement of it)
    with pytest.raises(build.BuildError, match="page script"):
        build.check_page_script(static)
    lazy = tiny_bundle(tmp_path / "lazy", 'import "./first.js";\nglobalThis.wake = () => import("./ui/upgrade-input.js");\n')
    build.check_page_script(lazy)


@pytest.mark.parametrize("name", PAGE_INPUTS)
def test_a_page_script_without_the_files_that_take_a_kit_link_out_of_the_address_is_refused(name):
    # first.js is the first import of the page script and calls the function of input/kitlocation.js: a build in which either is missing leaves the fragment to the other scripts of the page
    with pytest.raises(build.BuildError, match=rf"page script.*does not hold {re.escape(name)}"):
        build.check_page_script(shaped_metafile(["app.js", "trio.js"], LAZY_INPUTS, taking=[other for other in PAGE_INPUTS if other != name]))
    build.check_page_script(shaped_metafile(["app.js", "trio.js"], LAZY_INPUTS))
    long_form = shaped_metafile(["app.js"], LAZY_INPUTS, taking=[f"pipeline/trioforge/site/static/{other}" for other in PAGE_INPUTS])  # (a path that is not relative to static/ is the same file)
    build.check_page_script(long_form)


def test_a_real_bundle_in_which_the_section_loads_the_code_of_a_shared_kit_by_a_dynamic_import_is_accepted_and_one_with_a_static_import_is_refused(tmp_path):
    lazy = tiny_bundle(tmp_path / "lazy", 'import "./first.js";\nglobalThis.wake = () => import("./ui/upgrade-input.js");\n')
    held = {Path(output).name.split("-")[0]: sorted(info["inputs"]) for output, info in lazy["outputs"].items()}
    assert "shared" in held and "upgrade" in held and "chunk" in held, held  # (the panel, the section, and what the two share: a chunk of esbuild's)
    assert "input/kitdecode.js" in held["shared"] and "ui/shared-kit.js" in held["shared"]
    assert not {"ui/shared-kit.js", "input/kitdecode.js"} & set(held["upgrade"])
    build.check_page_script(lazy)
    static = tiny_bundle(tmp_path / "static", 'import "./first.js";\nglobalThis.wake = () => import("./ui/upgrade-input.js");\n', static_kit=True)
    with pytest.raises(build.BuildError, match=r"holds ui/shared-kit\.js.*shared kit"):
        build.check_page_script(static)


def test_a_chunk_of_the_section_that_imports_the_chunk_of_a_shared_kit_at_once_is_refused_directly_or_through_another():
    """A static import of the panel from the section, with the dynamic import kept as well, leaves the panel in a chunk of its own that the section's chunk imports at once; and a
    chunk that both import can hold the decoder as well."""
    meta = shaped_metafile(["app.js", "trio.js"], LAZY_INPUTS)
    meta["outputs"]["upgrade-input-CCCCCCCC.js"]["imports"] = [{"path": "shared-kit-EEEEEEEE.js", "kind": "import-statement"}]
    with pytest.raises(build.BuildError, match=r"imports shared-kit-EEEEEEEE\.js at once, which holds ui/shared-kit\.js.*shared kit"):
        build.check_page_script(meta)
    through = shaped_metafile(["app.js", "trio.js"], LAZY_INPUTS, kit_inputs=["ui/shared-kit.js"])
    through["outputs"]["chunk-FFFFFFFF.js"] = {"imports": [], "inputs": {"input/kitdecode.js": {"bytesInOutput": 10}}}
    through["outputs"]["upgrade-input-CCCCCCCC.js"]["imports"] = [{"path": "chunk-FFFFFFFF.js", "kind": "import-statement"}]
    with pytest.raises(build.BuildError, match=r"imports chunk-FFFFFFFF\.js at once, which holds input/kitdecode\.js.*shared kit"):
        build.check_page_script(through)
    fine = shaped_metafile(["app.js", "trio.js"], LAZY_INPUTS)
    fine["outputs"]["upgrade-input-CCCCCCCC.js"]["imports"] = [{"path": "shared-kit-EEEEEEEE.js", "kind": "dynamic-import"}]
    build.check_page_script(fine)  # (a dynamic import is the way)


def test_a_real_bundle_whose_page_script_never_imports_the_take_is_refused(tmp_path):
    lazy_only = tiny_bundle(tmp_path / "forgotten", 'globalThis.wake = () => import("./ui/upgrade-input.js");\n')
    with pytest.raises(build.BuildError, match=r"does not hold first\.js"):
        build.check_page_script(lazy_only)


def lazy_code(out: Path) -> str:
    """All the code the page loads on first use: the section's chunk, the chunk of a shared kit and the chunk that the two share."""
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted((out / "assets").glob("*.js")) if p.name.split("-")[0] in ("upgrade", "shared", "chunk"))


def test_the_code_of_a_shared_kit_is_a_chunk_of_its_own_that_the_section_loads_by_a_dynamic_import(site):
    out, _ = site
    assets = out / "assets"
    kit, section, app = (next(assets.glob(pattern)).read_text(encoding="utf-8") for pattern in ("shared-kit-*.js", "upgrade-input-*.js", "app-*.js"))
    name = next(assets.glob("shared-kit-*.js")).name
    assert re.fullmatch(r"shared-kit-[A-Z0-9]{8}\.js", name)
    # what the panel says is in its chunk and not in the section's, whose visitors mostly never open a kit link
    for piece in ("A kit shared with you", "This kit link could not be read", "Unknown item", "read from the kit"):
        assert piece in kit and piece not in section and piece not in app, piece
    assert f'import("./{name}")' in section, "the section loads it by a dynamic import"
    assert name not in app and not re.search(r"""import\s*["']\./shared-kit""", section)
    # the section keeps its Remember; Share is made of a module that the panel uses as well (its own Share button), so it is in the chunk that the two share, and not in the panel's
    assert "Remember my gear" in section and "Share this kit" in lazy_code(out) and "Share this kit" not in kit and "Share this kit" not in app


def test_the_chunk_of_a_shared_kit_holds_the_panel_and_the_decoder_and_the_chunk_of_the_section_holds_neither(site, tmp_path):
    """What each output of esbuild's account holds, from the build itself."""
    need_node()
    meta: dict = {}
    build.bundle_assets(keep_metafile=meta)
    held = {Path(output).name: set(info.get("inputs", {})) for output, info in meta["outputs"].items() if output.endswith(".js")}
    named = lambda wanted: next(inputs for output, inputs in held.items() if output.startswith(wanted))  # noqa: E731
    kit = {name.split("static/")[-1] for name in named("shared-kit-")}
    section = {name.split("static/")[-1] for name in named("upgrade-input-")}
    assert {"ui/shared-kit.js", "input/kitdecode.js"} <= kit
    assert not {"ui/shared-kit.js", "input/kitdecode.js"} & section
    assert "ui/upgrade-input.js" in section and "ui/upgrade-input.js" not in kit
    upgrade_imports = next(info["imports"] for output, info in meta["outputs"].items() if Path(output).name.startswith("upgrade-input-"))
    assert [one["kind"] for one in upgrade_imports if Path(one["path"]).name.startswith("shared-kit-")] == ["dynamic-import"]  # (and by no import statement)


def test_the_page_script_of_the_real_build_takes_a_kit_link_out_of_the_address_and_does_not_carry_its_codec(site):
    out, _ = site
    app = next((out / "assets").glob("app-*.js")).read_text(encoding="utf-8")
    chunk = lazy_code(out)
    # the take is in the page script (it names its state key and the fragment it looks for), the codec (its messages, its tables) is in the code of the section and only there
    assert "kitFragment" in app and '"#k="' in app
    # and it is the first code of the page script (a module is evaluated in the order it is imported, and first.js is the first import): before the theme's and the trio page's
    assert app.index('"#k="') < app.index("trioforge-theme") < app.index("load this view; try again")
    for piece in ("not canonical base64url", "unknown trio code", "impossible length"):
        assert piece in chunk and piece not in app, piece
    assert "decodeKit" not in app and "encodeKit" not in app
    assert "Remember my gear on this device" in chunk and "Remember my gear on this device" not in app
    assert "A kit shared with you" in chunk and "A kit shared with you" not in app
    assert "Share this kit" in chunk and "Share this kit" not in app


def test_a_page_script_that_imports_a_chunk_at_once_is_refused():
    shared = {"path": "chunk-BBBBBBBB.js", "kind": "import-statement"}
    meta = {"outputs": {"app-AAAAAAAA.js": {"entryPoint": "app.js", "imports": [shared]}, "chunk-BBBBBBBB.js": {"imports": []}}}
    with pytest.raises(build.BuildError, match=r"chunk-BBBBBBBB\.js"):
        build.check_page_script(meta)
    lazy = {"path": "upgrade-input-CCCCCCCC.js", "kind": "dynamic-import"}
    held = {name: {"bytesInOutput": 10} for name in LAZY_INPUTS}  # (the code of the section, which the chunk holds)
    kit = {name: {"bytesInOutput": 10} for name in KIT_INPUTS}  # (the code of a shared kit, which a chunk of its own holds)
    taken = {name: {"bytesInOutput": 10} for name in PAGE_INPUTS}  # (what the page script holds)
    fine = {"outputs": {"app-AAAAAAAA.js": {"entryPoint": "app.js", "imports": [lazy], "inputs": taken}, "upgrade-input-CCCCCCCC.js": {"imports": [shared], "inputs": held}, "shared-kit-EEEEEEEE.js": {"imports": [], "inputs": kit}, "site-DDDDDDDD.css": {"imports": []}}}
    build.check_page_script(fine)  # (what the chunk itself imports is its own business)
    with pytest.raises(build.BuildError, match="page script"):
        build.check_page_script({"outputs": {"site-DDDDDDDD.css": {"imports": []}}})  # no page script at all: the metafile is not what was asked for
