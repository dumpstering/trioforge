"""Where a donor of an exalt suggestion comes from (branch exalt-source).

An inline line of Wear this says which donor item an effect comes from and how hard it is to get ("Drop", "Quest or crafted"); the reader also needs to see the zone and the creature of the drop, or the
name of the quest, in the words of the Source column of a kit row. A donor may have several sources, and the word names the cheapest kind (``effects/donors.py: access_cost``: vendor, then quest or recipe, then
drop), which is not always the kind the Source column shows (a drop in a live zone comes first there). So the shared effects file (``data/effects.json``) carries, for each donor, ``src``: the list of its
sources, each in the words of the Source column (``precompute.shards.source_texts``), the kind the word names first, then the others, never the same text twice, at most four, the text the Source column
shows always among them, and a count of the ones that did not fit. The site build makes them from the catalog the results were made from, the catalog it already reads and checks for the pictures of the
armor, and checks them against the Source column of the shards it loads. Nothing is baked into the page of a trio.

These tests hold: the first text of every donor is of the kind its word names, the Source column's own text is among them, a donor with none has none, the reader of the data (``check_donor_sources``)
accepts what the build writes and refuses what it does not, the build refuses a donor whose text the shards contradict, a build without the catalog writes the file as it always did, the output of
``source_summary`` (which the release's writer hash covers) is the same as before the wording of one source was shared, and the file stays within its budgets. They use the fixture's invented items; the
tests of real data read the committed catalog.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from site_helpers import parse
from test_site_build import MANIFEST, RESULTS, make_changelog, need_node
from test_site_icons import ARMOR

from trioforge.effects import donors as effect_donors
from trioforge.effects import fixtures, judgment
from trioforge.export import browser
from trioforge.precompute import shards
from trioforge.site import build, data

REPO = Path(__file__).resolve().parents[2]
LONG_ZONE = "A Zone With A Name That Goes On And On Beyond The Limit Of Sixty"
LONG_TEXT = f"{LONG_ZONE} (a fixture sentinel)"
CUT = LONG_TEXT[: shards.SOURCE_LIMIT - 3] + "..."

#: the sources a test gives the donors, by the access cost the donor has in the fixture's effects file (1 vendor, 2 quest or recipe, 3 drop, 4 drop in a raid zone: what the word of a line says), in the shape of the
#: catalog's own (``sources``, and the ``live-source`` reasons of the evidence), with the texts the file must carry for each: written out here (and not asked of the code) so that a change of the wording or the
#: order is seen. A trailing whole number is the count of sources that did not fit. The last of the drops has no source at all.
SPECS = {
    1: [
        ({"sold_by": [{"npc": "a fixture vendor", "zone": "Fixture Market"}], "drops": [{"zone": "Plane of Fear", "npcs": ["a fixture wraith"]}]}, ["live-source:Plane of Fear"],
         ["vendor: Fixture Market", "Plane of Fear (a fixture wraith)"]),
        ({"sold_by": [{"npc": "a fixture vendor", "zone": None}]}, [], ["vendor: a fixture vendor"]),
    ],
    2: [
        ({"quests": ["Rite of Fixtures"], "quest_labels": [{"title": "Rite of Fixtures", "label": "Fixture Rite"}], "drops": [{"zone": "Hollow Vale", "npcs": ["a fixture shade"]}]},
         ["live-source:Hollow Vale"], ["quest: Fixture Rite", "Hollow Vale (a fixture shade)"]),
        ({"quests": ["Rite of Tinkers"], "crafted": [{"container": "Fixture Forge"}]}, [], ["quest: Rite of Tinkers", "crafted: Fixture Forge"]),
        ({"crafted": [{"container": None}], "foraged": [{"zone": "Sunken Meadow"}]}, [], ["crafted", "Foraged in Sunken Meadow"]),
        ({"quests": ["Rite of One", "Rite of Two", "Rite of Three", "Rite of Four", "Rite of Five"], "drops": [{"zone": "Hollow Vale", "npcs": ["a fixture shade"]}]},
         ["live-source:Hollow Vale"], ["quest: Rite of One", "quest: Rite of Two", "quest: Rite of Three", "Hollow Vale (a fixture shade)", 2]),  # (the Source column's text is the 6th: it takes the 4th place)
        ({"quests": ["Rite of Fixtures"]}, [], ["quest: Rite of Fixtures"]),
        ({"quests": ["Rite of Truncation"], "drops": [{"zone": LONG_ZONE, "npcs": ["a fixture sentinel"]}]}, ["live-source:" + LONG_ZONE], ["quest: Rite of Truncation", CUT]),
    ],
    3: [
        ({"drops": [{"zone": "Cabilis East", "npcs": ["a fixture gnoll"]}, {"zone": "Hollow Vale", "npcs": ["a fixture shade"]}]}, ["live-source:Hollow Vale"],
         ["Hollow Vale (a fixture shade)", "Cabilis East (a fixture gnoll)"]),  # (a drop in a live zone comes first, as in the Source column)
        ({"drops": [{"zone": "Plane of Fear", "npcs": []}]}, [], ["Plane of Fear"]),
        ({"drops": [{"zone": f"Zone {n}", "npcs": [f"a fixture {n}"]} for n in ("One", "Two", "Three", "Four")]}, [],
         ["Zone One (a fixture One)", "Zone Two (a fixture Two)", "Zone Three (a fixture Three)", "Zone Four (a fixture Four)"]),
        ({"drops": [{"zone": "Cabilis East", "npcs": ["a fixture gnoll"]}], "foraged": [{"zone": "Sunken Meadow"}]}, ["live-source:foraged"], ["Cabilis East (a fixture gnoll)", "Foraged in Sunken Meadow"]),
        ({}, [], None),
    ],
    4: [
        ({"drops": [{"zone": "Plane of Fear", "npcs": ["a fixture wraith"]}, {"zone": "Plane of Hate", "npcs": []}]}, [], ["Plane of Fear (a fixture wraith)", "Plane of Hate"]),
        ({"drops": [{"zone": "Plane of Sky", "npcs": ["a fixture roc"]}]}, [], ["Plane of Sky (a fixture roc)"]),
    ],
}  # fmt: skip

def kind_of(text: str) -> str:
    """The kind of source a text of the Source column says (by its words)."""
    if text.startswith("quest: "):
        return "quest"
    if text.startswith("vendor: "):
        return "vendor"
    if text.startswith("crafted"):
        return "craft"
    if text.startswith("Foraged in "):
        return "forage"
    return "drop"


def source_of(spec: dict) -> dict:
    return {"drops": [], "sold_by": [], "quests": [], "crafted": [], **spec}


def texts_of(entry: list) -> tuple[list[str], int]:
    """The texts of a donor's entry in the file and the count after them."""
    more = entry[-1] if isinstance(entry[-1], int) else 0
    return [text for text in entry if isinstance(text, str)], more


def access_of(effects: dict) -> dict[str, int]:
    """The cost each donor has in an effects file (the word of its line): the same in every effect that lists it."""
    costs: dict[str, set[int]] = {}
    for row in effects["effects"]:
        for key, cost in row["d"]:
            costs.setdefault(key, set()).add(cost)
    assert all(len(found) == 1 for found in costs.values())
    return {key: next(iter(found)) for key, found in costs.items()}


def write_runnerup(results: Path, name: str, document: dict) -> None:
    """Write a runner-up file of the fixture and make the index of them say what the reader checks of it: its size, its gzipped size and its SHA-256."""
    folder = results / "pal-mnk-ber" / "runnerups"
    raw = json.dumps(document, ensure_ascii=False).encode("utf-8")
    (folder / name).write_bytes(raw)
    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    entry = next(entry for entry in index["files"] if entry["file"] == name)
    entry.update({"bytes": len(raw), "gzip": len(gzip.compress(raw, 9, mtime=0)), "sha256": hashlib.sha256(raw).hexdigest()})
    (folder / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


def retext(results: Path, key: str, text: str, *, shards_too: bool = True) -> None:
    """Make every row of every runner-up file of the fixture, and of every shard unless ``shards_too`` is false, say ``text`` as the Source column of the item ``key``."""
    for name in data.SHARD_NAMES if shards_too else ():
        path = results / "pal-mnk-ber" / f"{name}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        at = document["items_keys"].index("source")
        for row in document["items"]:
            if row[0] == key:
                row[at] = text
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    for path in sorted((results / "pal-mnk-ber" / "runnerups").glob("*.json")):
        if path.name == "index.json":
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        at = document["items_keys"].index("source")
        for row in document["items"]:
            if row[0] == key:
                row[at] = text
        write_runnerup(results, path.name, document)


def shard_keys(results: Path) -> set[str]:
    document = json.loads((results / "pal-mnk-ber" / "strict-own.json").read_text(encoding="utf-8"))
    return {row[0] for row in document["items"]}


def shard_texts(results: Path) -> set[str]:
    """The Source column of every item of the shards of the fixture."""
    found: set[str] = set()
    for name in data.SHARD_NAMES:
        document = json.loads((results / "pal-mnk-ber" / f"{name}.json").read_text(encoding="utf-8"))
        at = document["items_keys"].index("source")
        found |= {row[at] for row in document["items"]}
    return found


def make_results(tmp_path: Path, *, give_sources: bool = True) -> tuple[Path, Path, dict[str, list]]:
    """A copy of the fixture results with the effects layer's files, a catalog of its own that they were made from (the item table and the bundle carry its fingerprint), and, in that catalog, sources for
    the donors taken from :data:`SPECS` by their access cost, and the Source column of the shards made to say what the catalog says. Returns the results, the catalog and what the file must carry, by donor."""
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    fixtures.write_site_fixture(results)
    items_doc = json.loads((results / "items.json").read_text(encoding="utf-8"))
    effects = json.loads((results / "effects.json").read_text(encoding="utf-8"))
    access = access_of(effects)
    catalog = fixtures.site_catalog(items_doc)
    by_key = {item["key"]: item for item in catalog["items"]}
    for item in catalog["items"]:
        item["categories"] = ARMOR.get(item["name"], [])
        item["instrument_mods"] = {}
    wanted: dict[str, list] = {}
    if give_sources:
        taken = {cost: 0 for cost in SPECS}
        for key in sorted(access):
            cost = access[key]
            spec, live, expected = SPECS[cost][taken[cost] % len(SPECS[cost])]
            taken[cost] += 1
            by_key[key]["sources"] = source_of(spec)
            by_key[key]["evidence"] = {"level": "wiki", "reasons": [{"code": code, "seal": "player", "text": "x"} for code in live]}
            wanted[key] = expected
            retext(results, key, shards.source_summary(by_key[key]))  # (the Source column of the shards says what the catalog says: they were made from it)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    stamped = browser.inputs_fingerprint(hashlib.sha256(path.read_bytes()).hexdigest(), items_doc)
    for name in ("items.json", "pal-mnk-ber/engine-l50.json"):
        text = (results / name).read_text(encoding="utf-8")
        assert items_doc["inputs"] in text
        (results / name).write_text(text.replace(items_doc["inputs"], stamped), encoding="utf-8")
    return results, path, wanted


def restamp(results: Path, catalog: Path) -> None:
    """Make the item table and the bundle say that they were made from the catalog as it is now."""
    table = json.loads((results / "items.json").read_text(encoding="utf-8"))
    stamped = browser.inputs_fingerprint(hashlib.sha256(catalog.read_bytes()).hexdigest(), table)
    for name in ("items.json", "pal-mnk-ber/engine-l50.json"):
        text = (results / name).read_text(encoding="utf-8")
        (results / name).write_text(text.replace(table["inputs"], stamped), encoding="utf-8")


def run(tmp_path: Path, results: Path, **options):
    out = tmp_path / "dist"
    build.build(results=results, out=out, noindex=True, sources_manifest=MANIFEST, changelog=make_changelog(tmp_path), **options)
    return out


@pytest.fixture(scope="module")
def sourced(tmp_path_factory):
    need_node()
    tmp = tmp_path_factory.mktemp("exalt-source")
    results, catalog, wanted = make_results(tmp)
    out = run(tmp, results, catalog=catalog, without_item_catalog=False)
    return out, json.loads(catalog.read_text(encoding="utf-8")), wanted, results


@pytest.fixture(scope="module")
def without_catalog(tmp_path_factory):
    need_node()
    tmp = tmp_path_factory.mktemp("exalt-source-without")
    results, _, _ = make_results(tmp)
    return run(tmp, results, without_item_catalog=True)


def effects_of(out: Path) -> dict:
    return json.loads((out / "data" / "effects.json").read_text(encoding="utf-8"))


# ---- what the build writes ---------------------------------------------------------------------------------------------------------------------------


def test_every_donor_carries_the_sources_of_its_item_in_the_words_of_the_source_column_and_a_donor_with_none_carries_none(sourced):
    out, _, wanted, _ = sourced
    effects = effects_of(out)
    assert set(wanted) == set(effects["items"])
    for key, expected in wanted.items():
        if expected is None:
            assert key not in effects["src"], key
        else:
            assert effects["src"][key] == expected, key
    assert any(expected is None for expected in wanted.values()) and any(expected is not None for expected in wanted.values())
    assert set(effects["src"]) < set(effects["items"])


def test_the_first_text_of_every_donor_is_of_the_kind_the_word_of_its_line_names(sourced):
    out, _, _, results = sourced
    effects = effects_of(out)
    access = access_of(json.loads((results / "effects.json").read_text(encoding="utf-8")))
    for key, entry in effects["src"].items():
        texts, _ = texts_of(entry)
        assert kind_of(texts[0]) in build.WORD_KINDS[access[key]], (key, access[key], texts[0])
    assert len(effects["src"]) >= 15 and {access[key] for key in effects["src"]} == {1, 2, 3, 4}  # (a donor of every word there is)


def test_the_text_the_source_column_shows_is_among_them_for_every_donor_even_when_more_than_four_did_not_fit(sourced):
    out, catalog, wanted, _ = sourced
    effects = effects_of(out)
    by_key = {item["key"]: item for item in catalog["items"]}
    for key, entry in effects["src"].items():
        texts, more = texts_of(entry)
        assert shards.source_summary(by_key[key]) in texts, key
        assert len(texts) <= 4 and len(set(texts)) == len(texts), key
        everything = [text for _, text in shards.source_texts(by_key[key])]
        assert len(texts) + more == len(everything) and set(texts) <= set(everything), key  # (the count is of the ones that did not fit)
    five = next(key for key, expected in wanted.items() if expected and expected[-1] == 2)
    assert effects["src"][five][:3] == ["quest: Rite of One", "quest: Rite of Two", "quest: Rite of Three"] and effects["src"][five][3] == "Hollow Vale (a fixture shade)"  # (the 4th place is the Source column's)


def test_the_second_drop_that_is_live_comes_first_among_the_drops_as_in_the_source_column(sourced):
    out, _, wanted, _ = sourced
    key = next(key for key, expected in wanted.items() if expected and expected[0] == "Hollow Vale (a fixture shade)" and "Cabilis East (a fixture gnoll)" in expected)
    assert effects_of(out)["src"][key][:2] == ["Hollow Vale (a fixture shade)", "Cabilis East (a fixture gnoll)"]


def test_the_file_keeps_its_shape_and_its_budgets_with_the_texts_in_it(sourced):
    out, _, _, _ = sourced
    raw = (out / "data" / "effects.json").read_bytes()
    effects = json.loads(raw)
    assert list(effects) == ["v", "release", "license", "attribution", "spells_us", "cap", "late", "mass", "items", "src", "effects"]
    for key, entry in effects["items"].items():
        assert len(entry) == 6, key  # (the entry of a donor is what the matcher reads, as it was: the texts are a table of their own)
    assert len(raw) <= build.LIMITS["effects"] and len(gzip.compress(raw, 9, mtime=0)) <= build.LIMITS["effects_gzip"]


def test_the_page_of_a_trio_says_none_of_the_texts_that_are_not_its_own_source_column(sourced):
    out, _, _, results = sourced
    html = (out / "trio" / "pal-mnk-ber" / "index.html").read_text(encoding="utf-8")
    own = shard_texts(results)  # (the Source column of a kit row is in the page, as it always was)
    texts = [text for entry in effects_of(out)["src"].values() for text in texts_of(entry)[0] if text not in own]
    assert len(texts) >= 8 and not any(text in html for text in texts)
    assert parse(html).find_all("details", id_="exalt")


def test_a_build_without_the_catalog_writes_the_file_as_before_and_says_so(without_catalog):
    effects = effects_of(without_catalog)
    assert "src" not in effects and list(effects) == ["v", "release", "license", "attribution", "spells_us", "cap", "late", "mass", "items", "effects"]


def test_a_build_without_the_catalog_says_that_the_donors_do_not_say_where_they_come_from(tmp_path):
    need_node()
    results, _, _ = make_results(tmp_path)
    made = build.build(results=results, out=tmp_path / "dist", noindex=True, sources_manifest=MANIFEST, changelog=make_changelog(tmp_path), without_item_catalog=True)
    assert made.icon_note and "--no-item-catalog" in made.icon_note and "armor" in made.icon_note  # (what it said)
    assert "where the donors" in made.icon_note  # (and now this)


def test_results_without_the_effects_layer_say_nothing_new_in_the_note_of_a_build_without_the_catalog(tmp_path):
    need_node()
    made = build.build(results=RESULTS, out=tmp_path / "dist", noindex=True, sources_manifest=MANIFEST, changelog=make_changelog(tmp_path), without_item_catalog=True)
    assert made.icon_note and "donors" not in made.icon_note


def test_a_donor_whose_catalog_item_has_no_sources_stops_the_build_with_a_line_that_names_it(tmp_path):
    need_node()
    results, catalog, wanted = make_results(tmp_path)
    key = next(key for key, expected in wanted.items() if expected)
    document = json.loads(catalog.read_text(encoding="utf-8"))
    del next(item for item in document["items"] if item["key"] == key)["sources"]
    catalog.write_text(json.dumps(document), encoding="utf-8")
    restamp(results, catalog)
    with pytest.raises(build.BuildError, match=key) as caught:
        run(tmp_path, results, catalog=catalog, without_item_catalog=False)
    assert len(str(caught.value).splitlines()) == 1


# ---- the build holds the texts to the Source column of the shards -------------------------------------------------------------------------------------


def test_the_build_refuses_a_donor_whose_source_column_in_the_shards_is_not_among_its_texts_and_names_the_item(tmp_path):
    need_node()
    results, catalog, wanted = make_results(tmp_path)
    in_shards = shard_keys(results)
    key = next(key for key, expected in wanted.items() if expected and key in in_shards)
    retext(results, key, "Somewhere Else (a stranger)")
    with pytest.raises(build.BuildError, match=key) as caught:
        run(tmp_path, results, catalog=catalog, without_item_catalog=False)
    assert len(str(caught.value).splitlines()) == 1 and "Somewhere Else (a stranger)" in str(caught.value)


def test_the_build_refuses_it_in_a_runner_up_table_too(tmp_path):
    need_node()
    results, catalog, wanted = make_results(tmp_path)
    document = json.loads((results / "pal-mnk-ber" / "runnerups" / "balanced.json").read_text(encoding="utf-8"))
    key = next(row[0] for row in document["items"] if wanted.get(row[0]))  # (a donor with texts that the runner-ups name)
    retext(results, key, "Somewhere Else (a stranger)", shards_too=False)  # (the shards say what the catalog says; the runner-up tables say another)
    with pytest.raises(build.BuildError, match=key):
        run(tmp_path, results, catalog=catalog, without_item_catalog=False)


def test_the_build_passes_when_every_donor_that_the_shards_show_has_its_source_column_among_its_texts(sourced):
    out, _, wanted, results = sourced  # (the module's build is the proof: it was made, so the check passed)
    donors_in_shards = {key for key, expected in wanted.items() if expected and key in shard_keys(results)}
    assert len(donors_in_shards) >= 3 and effects_of(out)["src"]


def test_the_check_of_the_source_column_in_isolation_says_both_ways():
    items = [type("Row", (), {"key": "w1", "source": "Plane of Hate (Innoruuk)"})(), type("Row", (), {"key": "w2", "source": ""})(), type("Row", (), {"key": "w9", "source": "Elsewhere"})()]
    donors = {"w1", "w2"}
    build.check_source_column({"w1": ["quest: X", "Plane of Hate (Innoruuk)"]}, items, donors)  # (among them; an item with no Source column says nothing; w9 is no donor)
    build.check_source_column({"w1": ["Plane of Hate (Innoruuk)", 3]}, items, donors)  # (the count after the texts is no text)
    with pytest.raises(build.BuildError, match=r"w1.*Plane of Hate \(Innoruuk\)") as caught:
        build.check_source_column({"w1": ["quest: X"]}, items, donors)
    assert len(str(caught.value).splitlines()) == 1
    with pytest.raises(build.BuildError, match="w1"):
        build.check_source_column({}, items, donors)  # (the shards show a text for a donor that has none: the catalog and the shards are of two runs)
    with pytest.raises(build.BuildError, match="w1"):
        build.check_source_column({"w1": [3]}, items, donors)  # (a count is no text)
    build.check_source_column({}, items, {"w2"})  # (w1 is no donor here)


def test_a_malformed_table_of_sources_from_the_catalog_stops_the_build_with_one_line_and_not_a_traceback(tmp_path, monkeypatch):
    need_node()
    results, catalog, _ = make_results(tmp_path)
    monkeypatch.setattr(build, "donor_sources", lambda donors, listed, access=None: {"w80236": ["x" * 61]})
    monkeypatch.setattr(build, "check_source_column", lambda *args, **kwargs: None)  # (the shards' own check is another test: this one is of the file's)
    with pytest.raises(build.BuildError, match="longer than 60") as caught:
        run(tmp_path, results, catalog=catalog, without_item_catalog=False)
    assert len(str(caught.value).splitlines()) == 1


# ---- the function that makes them ---------------------------------------------------------------------------------------------------------------------


def listed_of(*specs) -> dict[str, dict]:
    return {f"w{n}": {"key": f"w{n}", "sources": source_of(spec), "evidence": {"level": "wiki", "reasons": [{"code": c, "seal": "player", "text": "x"} for c in live]}} for n, (spec, live) in enumerate(specs, 1)}


def test_donor_sources_asks_of_the_catalog_only_the_donors_it_is_given_and_leaves_out_the_ones_with_no_text():
    listed = listed_of((SPECS[3][0][0], SPECS[3][0][1]), ({}, []))
    listed["w3"] = {"key": "w3"}  # (no sources: it is no donor, so it is never read)
    assert build.donor_sources(["w1", "w2"], listed) == {"w1": ["Hollow Vale (a fixture shade)", "Cabilis East (a fixture gnoll)"]}
    assert build.donor_sources([], listed) == {}
    with pytest.raises(build.BuildError, match=r"catalog item w3\b"):
        build.donor_sources(["w3"], listed)
    with pytest.raises(build.BuildError, match=r"no item zz\b"):
        build.donor_sources(["zz"], listed)  # (a donor the catalog does not have)


def test_donor_sources_puts_the_kind_the_word_names_first_and_without_a_word_keeps_the_order_of_the_source_column():
    spec = ({"quests": ["Rite of Fixtures"], "drops": [{"zone": "Hollow Vale", "npcs": ["a fixture shade"]}]}, ["live-source:Hollow Vale"])
    listed = listed_of(spec)
    assert build.donor_sources(["w1"], listed, {"w1": 2}) == {"w1": ["quest: Rite of Fixtures", "Hollow Vale (a fixture shade)"]}  # "Quest or crafted"
    assert build.donor_sources(["w1"], listed, {"w1": 3}) == {"w1": ["Hollow Vale (a fixture shade)", "quest: Rite of Fixtures"]}  # "Drop"
    assert build.donor_sources(["w1"], listed, {"w1": 4}) == {"w1": ["Hollow Vale (a fixture shade)", "quest: Rite of Fixtures"]}  # "Raid drop"
    assert build.donor_sources(["w1"], listed) == {"w1": ["Hollow Vale (a fixture shade)", "quest: Rite of Fixtures"]}  # (no word: the Source column's order)
    assert build.donor_sources(["w1"], listed, {"w1": 9}) == {"w1": ["Hollow Vale (a fixture shade)", "quest: Rite of Fixtures"]}  # (no known source: no word)
    vendor = listed_of(({"sold_by": [{"npc": "a fixture vendor", "zone": None}], "drops": [{"zone": "Plane of Fear", "npcs": []}], "foraged": [{"zone": "Sunken Meadow"}]}, []))
    assert build.donor_sources(["w1"], vendor, {"w1": 1}) == {"w1": ["vendor: a fixture vendor", "Plane of Fear", "Foraged in Sunken Meadow"]}


def test_donor_sources_counts_what_did_not_fit_and_never_leaves_out_the_text_of_the_source_column():
    many = ({"drops": [{"zone": f"Zone {n}", "npcs": []} for n in range(1, 8)]}, [])
    assert build.donor_sources(["w1"], listed_of(many), {"w1": 3}) == {"w1": ["Zone 1", "Zone 2", "Zone 3", "Zone 4", 3]}
    live_last = ({"drops": [{"zone": f"Zone {n}", "npcs": []} for n in range(1, 8)]}, ["live-source:Zone 7"])
    assert build.donor_sources(["w1"], listed_of(live_last), {"w1": 3}) == {"w1": ["Zone 7", "Zone 1", "Zone 2", "Zone 3", 3]}
    same = ({"drops": [{"zone": "Zone 1", "npcs": []}, {"zone": "Zone 1", "npcs": []}]}, [])
    assert build.donor_sources(["w1"], listed_of(same), {"w1": 3}) == {"w1": ["Zone 1"]}  # (no text twice, and no count for one that is the same)


def test_the_kinds_the_word_of_a_cost_names_are_those_of_the_function_that_makes_the_cost():
    j = judgment.default()
    cost = lambda sources: effect_donors.access_cost({"sources": source_of(sources)}, j)  # noqa: E731
    assert cost({"sold_by": [{"npc": "a", "zone": None}]}) == 1 and build.WORD_KINDS[1] == ("vendor",)
    assert cost({"quests": ["Q"]}) == 2 and cost({"crafted": [{"container": None}]}) == 2 and build.WORD_KINDS[2] == ("quest", "craft")
    assert cost({"drops": [{"zone": "Cabilis East", "npcs": []}]}) == 3 and build.WORD_KINDS[3] == ("drop",)
    assert cost({"drops": [{"zone": "Plane of Fear", "npcs": []}]}) == 4 and build.WORD_KINDS[4] == ("drop",)
    assert cost({}) == j.access_cost["none"] and j.access_cost["none"] not in build.WORD_KINDS


def committed_catalog() -> dict[str, dict]:
    return {item["key"]: item for item in json.loads((REPO / "derived" / "catalog.json").read_text(encoding="utf-8"))["items"]}


def test_in_the_committed_catalog_the_first_text_of_every_item_is_of_the_kind_the_word_of_its_cost_names_and_the_source_column_is_among_them():
    listed = committed_catalog()
    j = judgment.default()
    access = {}
    for key, item in listed.items():
        try:
            access[key] = effect_donors.access_cost(item, j)  # (the cost the effects file gives a donor: the function that makes it)
        except AttributeError:  # (a drop with no zone: such an item is no donor, the cost cannot be made of it)
            continue
    found = build.donor_sources(sorted(access), listed, access)
    data.check_donor_sources(found, sorted(access))
    assert len(found) > 1000
    sizes: dict[int, int] = {}
    for key, entry in found.items():
        texts, more = texts_of(entry)
        assert shards.source_summary(listed[key]) in texts, key
        if access[key] in build.WORD_KINDS:
            assert kind_of(texts[0]) in build.WORD_KINDS[access[key]], (key, access[key], texts[0])
        else:  # (no word: the cost of an item with no route but foraging; the Source column's own order)
            assert kind_of(texts[0]) == "forage" and texts[0] == shards.source_summary(listed[key]), key
        sizes[len(texts) + more] = sizes.get(len(texts) + more, 0) + 1
    assert max(sizes) >= 5 and sizes[1] > sizes[2] > 0  # (the sources of the items of the release: most have one, some many)


def test_source_texts_is_the_wording_of_each_source_of_an_item_in_the_order_of_the_source_column():
    item = {
        "sources": source_of({"drops": [{"zone": "Zone A", "npcs": ["a one"]}, {"zone": "Zone B", "npcs": []}, {"zone": None, "npcs": []}], "quests": ["Q1", "Q2"], "quest_labels": [{"title": "Q2", "label": "Second"}],
                              "sold_by": [{"npc": "n", "zone": "Z"}], "crafted": [{"container": "Forge"}, {"container": None}], "foraged": [{"zone": "F1"}, {"zone": "F2"}]}),
        "evidence": {"level": "wiki", "reasons": []},
    }
    assert shards.source_texts(item) == [
        ("drop", "Zone A (a one)"), ("drop", "Zone B"), ("drop", "a drop"), ("quest", "quest: Q1"), ("quest", "quest: Second"), ("vendor", "vendor: Z"),
        ("craft", "crafted: Forge"), ("craft", "crafted"), ("forage", "Foraged in F1"), ("forage", "Foraged in F2"),
    ]
    live = {"quest", "F2"}  # (a live kind comes before the drops of no live zone; of the foraged zones a live one comes first)
    assert [text for _, text in shards.source_texts(item, live)] == [
        "quest: Q1", "quest: Second", "Zone A (a one)", "Zone B", "a drop", "vendor: Z", "crafted: Forge", "crafted", "Foraged in F2", "Foraged in F1",
    ]  # fmt: skip
    live_drop = {"Zone B"}
    assert [text for _, text in shards.source_texts(item, live_drop)][:3] == ["Zone B", "Zone A (a one)", "a drop"]
    assert shards.source_texts({"sources": source_of({}), "evidence": {"level": "wiki", "reasons": []}}) == []
    long = {"sources": source_of({"drops": [{"zone": LONG_ZONE, "npcs": ["a fixture sentinel"]}]}), "evidence": {"level": "wiki", "reasons": []}}
    assert shards.source_texts(long) == [("drop", CUT)] and len(CUT) == shards.SOURCE_LIMIT


#: SHA-256 of the lines "key<TAB>text" of source_summary over every item of the committed catalog, made with the function as it was before the wording of one source was shared (facf875), for
#: four sets of live sources: the item's own, none, the kinds only (quest, vendor, craft, foraged: no zone) and the zone of the last drop. The summary is in every shard of a release, and
#: the release's writer hash covers shards.py: what it says for an item must not change.
SUMMARY_DIGESTS = {
    "own": "2d029f8a297ea736d9cd98581cb81a34113af32665bfe8e432891f7314aeab00",
    "none": "9144bd127508d3ddc9cc92009ab6a72fa6c19dbdcbe13bf438bd5ae17dac2ffc",
    "kinds": "bfcedbf50885d6b289cbbc4290b789679f57c32dae55d23dc8d504a79a7918bc",
    "last": "41d3f58f7a603e74db9635ab26e78a8e650f212ed31f1a581934e034dd47f9e3",
}


def live_of(variant: str, item: dict):
    sources = item["sources"]
    if variant == "own":
        return None
    if variant == "none":
        return set()
    if variant == "kinds":
        return {"quest", "vendor", "craft", "foraged"}
    return {sources["drops"][-1]["zone"]} if sources["drops"] else ({sources["foraged"][-1]["zone"]} if sources.get("foraged") else set())


@pytest.mark.parametrize("variant", sorted(SUMMARY_DIGESTS))
def test_source_summary_says_the_same_for_every_item_of_the_committed_catalog_as_before(variant):
    digest = hashlib.sha256()
    for key, item in committed_catalog().items():
        digest.update(f"{key}\t{shards.source_summary(item, live_of(variant, item))}\n".encode())
    assert digest.hexdigest() == SUMMARY_DIGESTS[variant]


@pytest.mark.parametrize("variant", sorted(SUMMARY_DIGESTS))
def test_the_source_column_is_the_first_of_the_texts_of_every_item_of_the_committed_catalog(variant):
    for key, item in committed_catalog().items():
        live = live_of(variant, item)
        found = shards.source_texts(item, live)
        assert (found[0][1] if found else "") == shards.source_summary(item, live), key  # (one rule: the summary is the first of the texts)


# ---- the reader of the data ---------------------------------------------------------------------------------------------------------------------------


def test_the_limits_of_the_table_are_those_of_the_source_column():
    assert data.DONOR_SOURCE_LIMIT == shards.SOURCE_LIMIT and data.DONOR_SOURCES_MOST == 4


def test_the_reader_accepts_what_the_build_writes():
    data.check_donor_sources({}, ["w1"])
    data.check_donor_sources({"w1": ["Plane of Hate (Innoruuk)"], "w2": ["quest: Cleric Test of Courage", "Plane of Hate"], "w3": ["a", "b", "c", "d", 12]}, ["w1", "w2", "w3", "w4"])
    data.check_donor_sources({"w1": ["x" * 60]}, ["w1"])
    data.check_donor_sources({"w1": ["Nektropos Castle (Alexa Everling)", "a <b>tag</b> & \"quotes\", an it's"]}, ["w1"])  # (text is text: the page sets it as text)


@pytest.mark.parametrize(
    ("sources", "message"),
    [
        (["w1"], "mapping"),
        (None, "mapping"),
        ({"w9": ["Plane of Hate"]}, "no donor"),
        ({1: ["Plane of Hate"]}, "no donor"),
        ({"w1": "Plane of Hate"}, "list"),
        ({"w1": None}, "list"),
        ({"w1": []}, "1 to 4"),
        ({"w1": [3]}, "1 to 4"),
        ({"w1": ["a", "b", "c", "d", "e"]}, "1 to 4"),
        ({"w1": ["a", "b", "c", "d", "e", 3]}, "1 to 4"),
        ({"w1": [""]}, "empty"),
        ({"w1": ["   "]}, "empty"),
        ({"w1": [3, "a"]}, "text"),
        ({"w1": ["a", None, "b"]}, "text"),
        ({"w1": [["a"]]}, "text"),
        ({"w1": ["x" * 61]}, "longer"),
        ({"w1": ["a", "x" * 61]}, "longer"),
        ({"w1": ["Plane\nof Hate"]}, "control"),
        ({"w1": ["Plane\x00of Hate"]}, "control"),
        ({"w1": ["Plane of Hate"]}, "control"),
        ({"w1": ["a", "a"]}, "twice"),
        ({"w1": ["a", 0]}, "count"),
        ({"w1": ["a", -2]}, "count"),
        ({"w1": ["a", 1.5]}, "count"),
        ({"w1": ["a", True]}, "count"),
        ({"w1": ["a", 2, 3]}, "text"),
    ],
)
def test_the_reader_refuses_what_the_build_would_not_write(sources, message):
    with pytest.raises(ValueError, match=message):
        data.check_donor_sources(sources, ["w1", "w2"])


def test_the_file_writer_refuses_a_malformed_table_and_writes_none_for_an_empty_one(tmp_path):
    need_node()
    results, _, wanted = make_results(tmp_path)
    key = next(key for key, expected in wanted.items() if expected)
    trio = data.load_trio(results / "pal-mnk-ber")
    items = data.load_items(results, [trio])
    exalt = data.load_exalt(results, [trio], items.document)
    credit = build.credit_of(trio.meta)
    plain = json.loads(data.site_effects_json(exalt, items.document, credit))
    assert "src" not in plain
    assert "src" not in json.loads(data.site_effects_json(exalt, items.document, credit, sources={}))
    written = json.loads(data.site_effects_json(exalt, items.document, credit, sources={key: ["Plane of Hate (Innoruuk)", 2]}))
    assert written["src"] == {key: ["Plane of Hate (Innoruuk)", 2]} and written["items"] == plain["items"] and written["effects"] == plain["effects"]
    with pytest.raises(ValueError, match="no donor"):
        data.site_effects_json(exalt, items.document, credit, sources={"w999999": ["Plane of Hate"]})
    with pytest.raises(ValueError, match="empty"):
        data.site_effects_json(exalt, items.document, credit, sources={key: [""]})
