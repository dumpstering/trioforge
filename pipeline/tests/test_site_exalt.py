"""The section Effects to exalt on the site side: the reader of the effects files, the files and the page the build writes, the budgets and the guard on its chunk (p7fx2)."""

from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path

import pytest
from site_helpers import extract_main, parse
from test_site_build import RESULTS, need_node, read, run_build

from trioforge.effects import files as effects_files
from trioforge.effects import fixtures
from trioforge.effects import plan
from trioforge.precompute import release
from trioforge.precompute.assemble import ReleaseRefused
from trioforge.site import build, data

REPO = Path(__file__).resolve().parents[2]


def exalt_results(tmp_path: Path) -> Path:
    """A copy of the fixture results with the two files of the effects layer, made by the code that makes them for a release (fixtures/site/results has none)."""
    target = tmp_path / "results"
    shutil.copytree(RESULTS, target)
    fixtures.write_site_fixture(target)
    return target


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    need_node()
    tmp = tmp_path_factory.mktemp("exalt-site")
    out = tmp / "dist"
    run_build(out, tmp, noindex=True, results=exalt_results(tmp))
    return out


@pytest.fixture(scope="module")
def without(tmp_path_factory):
    """The same site built from the results as the fixture has them, with no effects files (a release made before the layer)."""
    need_node()
    tmp = tmp_path_factory.mktemp("exalt-without")
    out = tmp / "dist"
    run_build(out, tmp, noindex=True)
    return out


def gz(raw: bytes) -> int:
    return len(gzip.compress(raw, 9, mtime=0))


def copy_results(tmp_path: Path) -> Path:
    return exalt_results(tmp_path)


def load(results: Path):
    trio = data.load_trio(results / "pal-mnk-ber")
    items = data.load_items(results, [trio])
    return trio, items


def edit(path: Path, change) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document), encoding="utf-8")


# ---- the page and the files the build writes --------------------------------------------------------------------------------------------------------


def test_the_trio_page_has_the_section_closed_with_the_addresses_of_its_two_files(built):
    page = parse((built / "trio/pal-mnk-ber/index.html").read_text(encoding="utf-8"))
    (section,) = page.find_all("details", id_="exalt")
    assert section.get("data-effects") == "/data/effects.json" and section.get("data-exalt") == "/data/pal-mnk-ber/exalt.json"
    assert not section.has("open")
    assert "Exalt plan: effects to move onto this kit" in section.find_all("summary")[0].text() and "planning aid" in section.text()
    assert page.find_all("div", id_="exalt-body") and page.find_all("p", id_="exalt-status")[0].has("hidden")


def test_the_section_shell_costs_the_page_less_than_three_kilobytes_gzipped(built, without):
    with_section = (built / "trio/pal-mnk-ber/index.html").read_bytes()
    plain = (without / "trio/pal-mnk-ber/index.html").read_bytes()
    assert gz(with_section) - gz(plain) <= 3 * 1024
    assert len(with_section) - len(plain) < 1500  # (the shell is a few hundred bytes)


def test_the_page_names_neither_file_in_a_script_or_a_link_and_loads_nothing_of_the_section_by_itself(built):
    html = (built / "trio/pal-mnk-ber/index.html").read_text(encoding="utf-8")
    assert html.count("/data/effects.json") == 1 and html.count("/data/pal-mnk-ber/exalt.json") == 1  # (only the two attributes of the section)
    assert "<link" not in html.split('id="exalt"')[1].split("</details>")[0]
    assert not any(tag.get("src", "").find("exalt") >= 0 for tag in parse(html).find_all("script"))


def test_the_published_files_carry_the_release_the_licence_the_attribution_and_what_the_page_needs(built):
    shared = json.loads((built / "data/effects.json").read_text(encoding="utf-8"))
    trio = json.loads((built / "data/pal-mnk-ber/exalt.json").read_text(encoding="utf-8"))
    for document in (shared, trio):
        assert list(document)[:4] == ["v", "release", "license", "attribution"]
        assert document["release"] == "data-2026-10-14" and document["license"] == "CC BY-SA 4.0"
    assert shared["late"] == 30 and shared["cap"] == 50 and set(shared["mass"]) >= {"PAL", "MNK", "BER"}
    donors = {key for row in shared["effects"] for key, _ in row["d"]}
    assert set(shared["items"]) == donors
    for key, (name, page, slots, classes, two_hand, arrival) in shared["items"].items():
        assert isinstance(name, str) and page in (0, 1) and slots and classes and two_hand in (0, 1) and arrival in (0, 4, None), key
    assert shared["items"]["w80524"][4] == 1  # (the fixture's two-hand weapon)
    hosts = {row["h"] for entry in trio["roles"].values() for row in entry["plan"]}
    assert set(trio["names"]) == hosts and trio["trio"] == "pal-mnk-ber" and trio["race"] == "OGR" and trio["tier"] == 4


def test_the_published_files_are_within_the_budgets_and_the_build_says_so(built):
    for name, raw_limit, gz_limit in (("data/effects.json", build.LIMITS["effects"], build.LIMITS["effects_gzip"]), ("data/pal-mnk-ber/exalt.json", None, build.LIMITS["exalt_gzip"])):
        raw = (built / name).read_bytes()
        assert gz(raw) <= gz_limit and (raw_limit is None or len(raw) <= raw_limit)


def test_a_build_without_the_effects_files_has_no_section_and_no_file_for_it(without):
    page = (without / "trio/pal-mnk-ber/index.html").read_text(encoding="utf-8")
    assert 'id="exalt"' not in page and "exalt-body" not in page
    assert not (without / "data/effects.json").exists() and not (without / "data/pal-mnk-ber/exalt.json").exists()
    assert sorted(p.name for p in (without / "data/pal-mnk-ber").glob("*.json")) == ["robust.json", "strict-group.json", "strict-own.json", "wiki-group.json", "wiki-own.json"]


def test_the_build_lists_the_two_files_among_the_files_of_the_site_exactly(built):
    written = sorted(p.relative_to(built).as_posix() for p in built.rglob("*") if p.is_file())
    assert "data/effects.json" in written and "data/pal-mnk-ber/exalt.json" in written
    names = build.site_files([build.TrioFiles("pal-mnk-ber", ("balanced", "tank", "melee"), (0, 4, 10), (50,), True)], assets=["assets/app-AAAAAAAA.js"], noindex=True)
    assert "data/effects.json" in names and "data/pal-mnk-ber/exalt.json" in names and len(names) == len(set(names))
    plain = build.site_files([build.TrioFiles("pal-mnk-ber", ("balanced", "tank", "melee"), (0, 4, 10), (50,))], assets=["assets/app-AAAAAAAA.js"], noindex=True)
    assert len(names) == len(plain) + 2
    slugs = ("pal-mnk-ber", "war-clr-pal")
    two = build.site_files([build.TrioFiles(s, ("balanced",), (0, 4, 10), (50,), True) for s in slugs], assets=["assets/app-AAAAAAAA.js"], noindex=True)
    none = build.site_files([build.TrioFiles(s, ("balanced",), (0, 4, 10), (50,)) for s in slugs], assets=["assets/app-AAAAAAAA.js"], noindex=True)
    assert two.count("data/effects.json") == 1 and len(two) == len(none) + 3  # (the shared file once, and a file for each trio)


def test_the_release_check_counts_the_files_of_the_effects_layer():
    facts = [release.TrioFacts(slug, (0, 4, 10), ("balanced",), (50,), "data-2026-10-14", "2026-10-13", "2026-09-22", 50) for slug in ("pal-mnk-ber", "war-clr-pal")]
    names = ["assets/app-AAAAAAAA.js"]
    base = release.check_file_count(facts, {}, assets=names)
    assert release.check_file_count(facts, {}, assets=names, exalt={"pal-mnk-ber"}) == base + 2  # (its file, and the shared one)
    assert release.check_file_count(facts, {}, assets=names, exalt={"pal-mnk-ber", "war-clr-pal"}) == base + 3


def test_the_sources_page_names_the_spell_text_and_says_that_item_effects_are_wiki_data(built):
    text = parse((built / "sources/index.html").read_text(encoding="utf-8")).text()
    assert "spells_us.txt" in text and "Effects to exalt" in text
    assert "effects that items carry" in text and "same credit and licence" in text


# ---- the reader ------------------------------------------------------------------------------------------------------------------------------------------


def test_the_reader_reads_the_fixture_and_a_trio_without_a_file_has_none(tmp_path):
    results = copy_results(tmp_path)
    trio, items = load(results)
    exalt = data.load_exalt(results, [trio], items.document)
    assert exalt is not None and exalt.has("pal-mnk-ber") and not exalt.has("war-clr-pal")
    (results / "pal-mnk-ber" / "exalt.json").unlink()
    assert not data.load_exalt(results, [trio], items.document).has("pal-mnk-ber")
    (results / "effects.json").unlink()
    assert data.load_exalt(results, [trio], items.document) is None


def test_a_trio_file_without_the_shared_file_is_refused(tmp_path):
    results = copy_results(tmp_path)
    trio, items = load(results)
    (results / "effects.json").unlink()
    with pytest.raises(data.ResultsError, match="exalt.json: is there, but effects.json is not"):
        data.load_exalt(results, [trio], items.document)


@pytest.mark.parametrize(
    ("which", "change", "message"),
    [
        ("effects.json", lambda d: d.update(version=2), "version"),
        ("effects.json", lambda d: d.update(data_release="data-2020-01-01"), "not from one run"),
        ("effects.json", lambda d: d["effects"][0].update(k="stun"), r"effects\[0\]|effects e000"),
        ("effects.json", lambda d: d["effects"][0].update(id="x1"), "new id"),
        ("effects.json", lambda d: d["effects"][0]["d"].append(["w999999", 1]), "item table has"),
        ("effects.json", lambda d: d["effects"][0].update(x=["made-up"]), "must be one of"),
        ("effects.json", lambda d: d["mass"].update(PAL=2), "from 0 to 1"),
        ("effects.json", lambda d: d["effects"].append(dict(d["effects"][0])), "new id"),
        ("pal-mnk-ber/exalt.json", lambda d: d.update(trio="war-clr-pal"), "trio"),
        ("pal-mnk-ber/exalt.json", lambda d: d.update(race="HUM"), "race"),
        ("pal-mnk-ber/exalt.json", lambda d: d.update(tier=10), "tier"),
        ("pal-mnk-ber/exalt.json", lambda d: d.update(data_release="data-2020-01-01"), "not from one run"),
        ("pal-mnk-ber/exalt.json", lambda d: d.update(classes=["PAL", "MNK", "WAR"]), "classes"),
        ("pal-mnk-ber/exalt.json", lambda d: d["roles"].update(healer=d["roles"]["tank"]), "a role the page does not offer"),
        ("pal-mnk-ber/exalt.json", lambda d: d["roles"]["tank"]["plan"][0].update(h="w999999"), "item table"),
        ("pal-mnk-ber/exalt.json", lambda d: d["roles"]["tank"]["plan"][0].update(p="NOSE"), "must be one of"),
        ("pal-mnk-ber/exalt.json", lambda d: d["roles"]["tank"]["plan"][0].update(e="e999"), "effect of the shared file"),
        ("pal-mnk-ber/exalt.json", lambda d: d["roles"]["tank"]["noroom"][0].update(w="because"), "must be one of"),
        ("pal-mnk-ber/exalt.json", lambda d: d["roles"]["tank"]["focus"][0].update(e=d["roles"]["tank"]["click"][0]["e"]), "listed as focus"),
        ("pal-mnk-ber/exalt.json", lambda d: d["roles"]["tank"]["click"][0].update(d="w999999"), "item table"),
    ],
)
def test_the_reader_refuses_a_file_that_is_not_what_the_layer_writes(tmp_path, which, change, message):
    results = copy_results(tmp_path)
    edit(results / which, change)
    trio = data.load_trio(results / "pal-mnk-ber")
    items = data.load_items(results, [trio])
    with pytest.raises(data.ResultsError, match=message):
        data.load_exalt(results, [trio], items.document)


# ---- the release holds the effects files to the site's reader (p7exalt) ------------------------------------------------------------------------------------


def reader_check(results: Path) -> None:
    """What the release does with the staged folder: the site's own reader on each trio it loads, then the verdict."""
    check = release.ExaltReaderCheck(results)
    check(data.load_trio(results / "pal-mnk-ber"))
    check.result()


def test_the_release_check_passes_the_files_the_layer_writes(tmp_path):
    results = copy_results(tmp_path)
    reader_check(results)
    assert effects_files.check_release(results, ["pal-mnk-ber"]) == 1


def test_a_trio_row_whose_donor_is_a_donor_of_another_effect_passes_the_files_check_and_is_refused_by_the_release(tmp_path):
    results = copy_results(tmp_path)
    shared = json.loads((results / "effects.json").read_text(encoding="utf-8"))
    row = json.loads((results / "pal-mnk-ber" / "exalt.json").read_text(encoding="utf-8"))["roles"]["tank"]["click"][0]
    own = {key for key, _ in next(e for e in shared["effects"] if e["id"] == row["e"])["d"]}
    foreign = next(key for e in shared["effects"] if e["id"] != row["e"] for key, _ in e["d"] if key not in own)
    edit(results / "pal-mnk-ber" / "exalt.json", lambda d: d["roles"]["tank"]["click"][0].update(d=foreign))
    assert effects_files.check_release(results, ["pal-mnk-ber"]) == 1  # (the hand copy of the reader's rules does not see it)
    with pytest.raises(ReleaseRefused, match=rf"pal-mnk-ber/exalt\.json.*{foreign}.*no donor of that effect"):
        reader_check(results)


def test_a_list_row_of_the_wrong_kind_passes_the_files_check_and_is_refused_by_the_release(tmp_path):
    results = copy_results(tmp_path)
    edit(results / "pal-mnk-ber" / "exalt.json", lambda d: d["roles"]["tank"]["focus"][0].update(e=d["roles"]["tank"]["click"][0]["e"]))
    assert effects_files.check_release(results, ["pal-mnk-ber"]) == 1
    with pytest.raises(ReleaseRefused, match=r"pal-mnk-ber/exalt\.json.*listed as focus"):
        reader_check(results)


def test_a_shared_file_of_another_run_than_the_item_table_is_refused_by_the_release_and_a_trio_without_a_file_still_checks_it(tmp_path):
    results = copy_results(tmp_path)
    (results / "pal-mnk-ber" / "exalt.json").unlink()  # (no trio file at all: the shared file is read all the same)
    edit(results / "effects.json", lambda d: d.update(data_release="data-2020-01-01"))
    assert effects_files.check_release(results, ["pal-mnk-ber"]) == 0
    with pytest.raises(ReleaseRefused, match=r"effects\.json.*not from one run"):
        reader_check(results)


def test_a_release_without_effects_files_passes_the_reader_check(tmp_path):
    results = copy_results(tmp_path)
    (results / "pal-mnk-ber" / "exalt.json").unlink()
    (results / "effects.json").unlink()
    reader_check(results)


def test_an_unreadable_item_table_is_refused_by_the_reader_check_with_a_message_of_its_own(tmp_path):
    results = copy_results(tmp_path)
    (results / "items.json").unlink()
    with pytest.raises(ReleaseRefused, match=r"the site's reader cannot read the item table: .*items\.json"):
        reader_check(results)


def test_an_item_table_that_is_not_json_is_refused_by_the_reader_check_with_a_message_of_its_own(tmp_path):
    results = copy_results(tmp_path)
    (results / "items.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ReleaseRefused, match=r"the site's reader cannot read the item table: .*items\.json"):
        reader_check(results)


@pytest.mark.parametrize(
    ("change", "kind"),
    [
        (lambda d: [], "TypeError"),  # (a list, not a mapping)
        (lambda d: {k: v for k, v in d.items() if k != "items"}, "KeyError"),
        (lambda d: dict(d, items=[{"name": "no key"}]), "KeyError"),
        (lambda d: dict(d, items=[7]), r"(TypeError|AttributeError|KeyError)"),
    ],
)
def test_an_item_table_of_the_wrong_shape_is_refused_by_the_reader_check_and_does_not_crash_it(tmp_path, change, kind):
    results = copy_results(tmp_path)
    path = results / "items.json"
    path.write_text(json.dumps(change(json.loads(path.read_text(encoding="utf-8")))), encoding="utf-8")
    with pytest.raises(ReleaseRefused, match=rf"the site's reader refuses the effects files: malformed .*\({kind}: "):
        reader_check(results)


def test_the_reader_check_keeps_the_first_refusal(tmp_path):
    results = copy_results(tmp_path)
    (results / "items.json").write_text("{not json", encoding="utf-8")
    check = release.ExaltReaderCheck(results)
    trio = data.load_trio(results / "pal-mnk-ber")
    check(trio)
    first = check.error
    (results / "items.json").write_text("[]", encoding="utf-8")
    check(trio)
    assert check.error == first and first
    with pytest.raises(ReleaseRefused, match="cannot read the item table"):
        check.result()


def noise(count: int) -> list[str]:
    """Text that does not compress: a file made of it is over its gzip budget when it is long enough."""
    import random

    rng = random.Random(7)
    return ["".join(rng.choices("abcdefghijklmnopqrstuvwxyz", k=40)) for _ in range(count)]


def test_the_reader_holds_the_files_to_their_budgets(tmp_path):
    results = copy_results(tmp_path)
    trio, items = load(results)
    original = json.loads((results / "effects.json").read_text(encoding="utf-8"))
    (results / "effects.json").write_text(json.dumps(dict(original, padding=noise(7000))), encoding="utf-8")
    with pytest.raises(data.ResultsError, match="over its budget"):
        data.load_exalt(results, [trio], items.document)
    (results / "effects.json").write_text(json.dumps(original), encoding="utf-8")
    edit(results / "pal-mnk-ber" / "exalt.json", lambda d: d.update(padding=noise(2500)))
    with pytest.raises(data.ResultsError, match="over its budget"):
        data.load_exalt(results, [trio], items.document)


# ---- the numbers the two sides share ---------------------------------------------------------------------------------------------------------------------


def test_the_constants_of_the_site_are_the_ones_of_the_effects_layer():
    assert data.EXALT_NO_ROOM == tuple(plan.REASONS) and data.PLAN_KINDS == tuple(plan.KINDS)
    assert data.EFFECT_KINDS == ("focus", "click", "carry", "worn", "proc") == tuple(effects_files.LISTS)
    assert data.EXALT_SHARED_RAW == effects_files.SHARED_RAW_LIMIT == build.LIMITS["effects"]
    assert data.EXALT_SHARED_GZIP == effects_files.SHARED_GZIP_LIMIT == build.LIMITS["effects_gzip"]
    assert data.EXALT_TRIO_GZIP == effects_files.TRIO_GZIP_LIMIT == build.LIMITS["exalt_gzip"]
    assert data.EFFECTS_NAME == effects_files.EFFECTS_FILE and data.EXALT_NAME == effects_files.TRIO_FILE
    assert data.EXALT_VERSION == effects_files.VERSION
    from trioforge.effects import donors  # the reasons a row is unverified are written by the layer's own donors module

    source = (REPO / "pipeline" / "trioforge" / "effects" / "donors.py").read_text(encoding="utf-8") + (REPO / "rules" / "rules.json").read_text(encoding="utf-8")
    for reason in data.EXALT_UNVERIFIED:
        assert f'"{reason}"' in source, reason
    assert donors


def test_the_javascript_has_the_words_for_every_reason_and_every_mark_the_files_can_give():
    source = (REPO / "pipeline" / "trioforge" / "site" / "static" / "ui" / "exalt.js").read_text(encoding="utf-8")
    for reason in (*data.EXALT_UNVERIFIED, *data.EXALT_NO_ROOM):
        assert f"{reason}:" in source, reason


# ---- the chunk of the section is a chunk of its own ----------------------------------------------------------------------------------------------------------


def metafile(page_inputs, chunk_inputs):
    return {
        "outputs": {
            "assets/app-X.js": {"entryPoint": "app.js", "inputs": {f"static/{name}": {} for name in page_inputs}, "imports": []},
            "assets/exalt-X.js": {"inputs": {f"static/{name}": {} for name in chunk_inputs}, "imports": []},
        }
    }


def test_the_build_refuses_a_page_script_that_holds_the_code_of_the_section_and_a_build_without_it():
    build.check_exalt_chunk(metafile(["trio.js"], ["ui/exalt.js", "ui/exalt-plan.js"]))
    with pytest.raises(build.BuildError, match="holds ui/exalt.js"):
        build.check_exalt_chunk(metafile(["trio.js", "ui/exalt.js"], ["ui/exalt-plan.js"]))
    with pytest.raises(build.BuildError, match="holds ui/exalt-plan.js"):
        build.check_exalt_chunk(metafile(["trio.js", "ui/exalt-plan.js"], ["ui/exalt.js"]))
    with pytest.raises(build.BuildError, match="no output but the page script holds ui/exalt.js"):
        build.check_exalt_chunk(metafile(["trio.js"], ["ui/exalt-plan.js"]))


def test_the_real_bundle_has_the_section_in_a_chunk_that_no_page_loads_by_itself(built):
    html = (built / "trio/pal-mnk-ber/index.html").read_text(encoding="utf-8")
    chunks = sorted(p.name for p in (built / "assets").glob("exalt-*.js"))
    assert len(chunks) == 1 and chunks[0] not in html
    assert "exalt-plan" not in "".join(p.name for p in (built / "assets").iterdir())  # (the matcher is inside the chunk, not a file of its own)


# ---- the contract of the browser tests of the section -----------------------------------------------------------------------------------------------------------
# tests-js/exalt.test.mjs runs the page code against these committed files, as tests-js/trio.test.mjs does against fixtures/site/contract: the baked page of the fixture with the
# effects layer, and the two files the build publishes for it. Regenerate them with
#     TRIOFORGE_UPDATE_CONTRACT=1 python -m pytest pipeline/tests/test_site_exalt.py -k contract

CONTRACT = REPO / "fixtures" / "site" / "contract-exalt"


def test_the_committed_contract_of_the_section_is_what_the_build_writes(built):
    import os

    files = {
        "trio-main.html": extract_main(read(built, "trio/pal-mnk-ber/index.html")),
        "data/effects.json": read(built, "data/effects.json"),
        "data/exalt.json": read(built, "data/pal-mnk-ber/exalt.json"),
    }
    if os.environ.get("TRIOFORGE_UPDATE_CONTRACT") == "1":
        for name, text in files.items():
            (CONTRACT / name).parent.mkdir(parents=True, exist_ok=True)
            (CONTRACT / name).write_text(text, encoding="utf-8", newline="\n")
    for name, text in files.items():
        assert (CONTRACT / name).is_file(), f"{name} is missing; run with TRIOFORGE_UPDATE_CONTRACT=1"
        assert (CONTRACT / name).read_text(encoding="utf-8") == text, f"{name} is stale; run with TRIOFORGE_UPDATE_CONTRACT=1"
    assert {p.relative_to(CONTRACT).as_posix() for p in CONTRACT.rglob("*") if p.is_file()} == set(files)


# ---- the fix round of part 2 ---------------------------------------------------------------------------------------------------------------------------


def swap_kind(row):
    row["k"] = "worn" if row["k"] != "worn" else "click"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["roles"]["tank"]["plan"][0].update(d="w90001"), "no donor of that effect"),  # (an item of the item table that the shipped effects file does not list as a donor)
        (lambda d: d["roles"]["tank"]["click"][0].update(d="w90001"), "no donor of that effect"),
        (lambda d: d["roles"]["tank"]["focus"][0].update(o=["w90001"]), "no donor of that effect"),
        (lambda d: swap_kind(d["roles"]["tank"]["noroom"][0]), "kind of the effect"),
    ],
)
def test_the_reader_holds_the_donors_and_the_kind_of_a_row_to_the_shipped_effects_file(tmp_path, change, message):
    results = exalt_results(tmp_path)
    assert (json.loads((results / "effects.json").read_text(encoding="utf-8"))["effects"]), "the fixture has effects"
    edit(results / "pal-mnk-ber" / "exalt.json", change)
    trio = data.load_trio(results / "pal-mnk-ber")
    items = data.load_items(results, [trio])
    with pytest.raises(data.ResultsError, match=message):
        data.load_exalt(results, [trio], items.document)


def test_a_role_the_page_offers_may_have_no_entry_and_the_page_says_so(tmp_path):
    """The layer writes a role only when it has a kit for it, so a missing role is a role with nothing to exalt: the reader takes the file, and the page code says
    "no effect plan for the ... role" (tests-js/exalt.test.mjs)."""
    results = exalt_results(tmp_path)
    edit(results / "pal-mnk-ber" / "exalt.json", lambda d: d["roles"].pop("melee"))
    trio = data.load_trio(results / "pal-mnk-ber")
    items = data.load_items(results, [trio])
    exalt = data.load_exalt(results, [trio], items.document)
    assert set(exalt.trios["pal-mnk-ber"]["roles"]) == {"balanced", "tank"}
    page_code = (REPO / "pipeline" / "trioforge" / "site" / "static" / "ui" / "exalt.js").read_text(encoding="utf-8")
    assert "This site has no effect plan for the" in page_code


def test_one_answer_says_which_trios_ship_the_file_of_the_effects_layer_and_the_build_and_the_release_count_use_it(tmp_path):
    slugs = ["pal-mnk-ber", "war-clr-pal"]
    results = exalt_results(tmp_path)
    assert data.exalt_slugs(results, slugs) == {"pal-mnk-ber"}  # (a trio of the list with no file of its own ships none)
    # a layer with the shared file and no file of a trio: no trio ships one
    (results / "pal-mnk-ber" / "exalt.json").unlink()
    assert data.exalt_slugs(results, slugs) == frozenset()
    # a trio file with no shared file is refused, by the reader and by the answer
    again = exalt_results(tmp_path / "again")
    (again / "effects.json").unlink()
    with pytest.raises(data.ResultsError, match="is there, but effects.json is not"):
        data.exalt_slugs(again, slugs)
    # the release counts what the build would write: the shared file once, a file for each trio that has one, nothing for a layer with no trio file
    facts = [release.TrioFacts(slug, (0, 4, 10), ("balanced",), (50,), "data-2026-10-14", "2026-10-13", "2026-09-22", 50) for slug in slugs]
    base = release.check_file_count(facts, {}, assets=["assets/app-AAAAAAAA.js"])
    assert release.check_file_count(facts, {}, assets=["assets/app-AAAAAAAA.js"], exalt=data.exalt_slugs(results, slugs)) == base
    full = exalt_results(tmp_path / "full")
    assert release.check_file_count(facts, {}, assets=["assets/app-AAAAAAAA.js"], exalt=data.exalt_slugs(full, slugs)) == base + 2


def test_a_partial_layer_makes_the_files_the_release_counted(tmp_path):
    """The count of the release gate is the number of files of the site that the build writes, for a layer that only some trios have."""
    need_node()
    results = exalt_results(tmp_path)
    second = results / "pal-shd-ber"
    shutil.copytree(results / "pal-mnk-ber", second)
    (second / "exalt.json").unlink()
    for path in second.rglob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "engine-l50.json":
            document["trio"] = document["profile_common"]["trio"] = ["PAL", "SHD", "BER"]
        else:
            document["trio"] = "pal-shd-ber"
        path.write_text(json.dumps(document), encoding="utf-8")
    index = json.loads((second / "runnerups" / "index.json").read_text(encoding="utf-8"))
    for entry in index["files"]:
        body = (second / "runnerups" / entry["file"]).read_bytes()
        entry.update(bytes=len(body), sha256=__import__("hashlib").sha256(body).hexdigest())
    (second / "runnerups" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    out = tmp_path / "dist"
    run_build(out, tmp_path, noindex=True, results=results)
    assert (out / "data/effects.json").is_file() and (out / "data/pal-mnk-ber/exalt.json").is_file() and not (out / "data/pal-shd-ber/exalt.json").exists()
    listed = build.site_files(
        [build.TrioFiles(slug, ("balanced", "tank", "melee"), (0, 4, 10), (50,), slug in data.exalt_slugs(results, ["pal-mnk-ber", "pal-shd-ber"])) for slug in ("pal-mnk-ber", "pal-shd-ber")],
        assets=["assets/app-AAAAAAAA.js"],
        noindex=True,
    )
    assert "data/effects.json" in listed and "data/pal-mnk-ber/exalt.json" in listed and "data/pal-shd-ber/exalt.json" not in listed
