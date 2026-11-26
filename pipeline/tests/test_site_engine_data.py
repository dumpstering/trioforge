"""The site generator reads the two files the browser's engine needs: the bundle of a trio and the item table.

``trioforge.site.data`` is the only reader of the precompute's results, so it is the one that checks them: the bundle
``<trio>/engine-l<level>.json`` against the shards of the trio (the format number, the trio and the level, the release and the rules
version, a reassembly of its profiles by the exporter's own reader, the weapon setups of each role and level) and the item table
``items.json`` of the folder of results against every trio in it (the format number, the release and the rules version, the records,
and for every item a shard or a runner-up file shows, its name, slots, tier rule, deity and evidence level). A file that is missing
or does not agree is a refusal that names the file and the field, in one line.

Both files also carry the fingerprint of the inputs of the run (``inputs``): the build refuses a folder in which a trio's bundle and ``items.json``
do not share one, and says which trio to run again; it holds the bundle's weapon setups to the levels of the table; and it holds both files to the
limits of the browser's own readers (``items.js``, ``profile.js``: the number of deities, the length of a text, a stat the model knows, the depth of a
bundle ...), which the build then also runs on every file it publishes (``test_site_build.py``).

The files read are those of the synthetic fixture (``fixtures/site/results``; ``engine_fixture.py`` makes them).
"""

from __future__ import annotations

import copy
import dataclasses
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from trioforge.export import browser
from trioforge.precompute import shards
from trioforge.site import data

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "fixtures" / "site" / "results"
SLUG = "pal-mnk-ber"
BUNDLE = f"{SLUG}/engine-l50.json"


@pytest.fixture(scope="module")
def results():
    return data.load_trio(RESULTS / SLUG)


@pytest.fixture(scope="module")
def table(results):
    return data.load_items(RESULTS, [results])


@pytest.fixture
def scratch(tmp_path):
    """A copy of the folder of results, and a helper that rewrites one of its JSON files (a path under the folder)."""
    root = tmp_path / "results"
    shutil.copytree(RESULTS, root)

    def edit(name, change):
        path = root / name
        document = json.loads(path.read_text(encoding="utf-8"))
        change(document)
        path.write_text(json.dumps(document), encoding="utf-8")

    def load():
        return data.load_items(root, [data.load_trio(root / SLUG)])

    return SimpleNamespace(root=root, edit=edit, load=load)


def record(document, key):
    return next(r for r in document["items"] if (r.get("key") or f"w{r['id']}") == key)


# ---- what is read -------------------------------------------------------------------------------------------------------------


def test_the_vocabulary_of_the_two_files_is_the_precomputes():
    assert data.ENGINE_VERSION == browser.FORMAT == 1
    assert data.engine_name(50) == shards.engine_name(50) == "engine-l50.json"
    assert data.ITEMS_NAME == shards.ITEMS_NAME == "items.json"


def test_the_bundle_of_a_trio_is_read_with_its_text_and_its_document(results):
    bundle = results.bundle
    assert bundle.name == "engine-l50.json"
    assert bundle.raw == (RESULTS / SLUG / "engine-l50.json").read_bytes()
    assert bundle.document["trio"] == ["PAL", "MNK", "BER"] and bundle.document["level"] == results.meta.level == 50
    assert bundle.document["data_release"] == results.meta.data_tag and bundle.document["rules_version"] == results.meta.rules_version
    assert [name for name in bundle.document if name != "inputs"] == list(browser.BUNDLE_FIELDS)  # and the fingerprint of the inputs, after the rules version
    assert list(bundle.document)[:4] == ["version", "data_release", "rules_version", "inputs"]


def test_the_item_table_is_read_with_its_text_and_its_document(table, results):
    assert table.name == "items.json"
    assert table.raw == (RESULTS / "items.json").read_bytes()
    assert table.document["count"] == len(table.document["items"]) > 40
    assert table.document["data_release"] == results.meta.data_tag
    assert [name for name in table.document if name != "inputs"] == list(browser.ITEM_TABLE_FIELDS)
    assert list(table.document)[:4] == ["version", "data_release", "rules_version", "inputs"]


def test_every_item_the_shards_show_is_in_the_table_with_the_level_the_shards_give_it(table, results):
    by_key = {browser.record_key(r): r for r in table.document["items"]}
    shown = data.used_items(results)
    assert len(shown) > 40
    for item in shown:
        assert by_key[item.key]["evidence"]["level"] == item.evidence, item.key
    levels = {r["evidence"]["level"] for r in table.document["items"]}
    assert levels == {"strict", "wiki", "hidden"}  # an item the shards never show may be hidden or one the trio cannot wear


def test_a_table_written_again_with_other_spacing_is_the_same_table_and_keeps_the_text_it_was_written_in(scratch):
    scratch.edit("items.json", lambda d: None)  # the document, written again by json.dumps
    got = scratch.load()
    assert got.document == json.loads((RESULTS / "items.json").read_text(encoding="utf-8"))
    assert got.raw == (scratch.root / "items.json").read_bytes() != (RESULTS / "items.json").read_bytes()


# ---- the bundle ----------------------------------------------------------------------------------------------------------------

BUNDLE_CHANGES = [
    (lambda d: d.update(version=2), "version"),
    (lambda d: d.update(version=True), "version"),
    (lambda d: d.update(trio=["PAL", "MNK", "SHD"]), "trio"),
    (lambda d: d.update(level=55), "level"),
    (lambda d: d.update(data_release="data-2026-10-20"), "data_release"),
    (lambda d: d.update(data_release=None), "data_release"),
    (lambda d: d.update(rules_version="2026-10-20"), "rules_version"),
    (lambda d: d.update(partial=False), "partial"),  # a field a bundle has none of
    (lambda d: d.pop("constants"), "constants"),
    (lambda d: d.update(evidence_levels=["strict"]), "evidence_levels"),
    (lambda d: d["constants"].update(stat_knee=255), "stat_knee"),  # a bare number where every exact number is a p/q text
    (lambda d: d["constants"].update(stat_knee="510/2"), "stat_knee"),  # a ratio not in lowest terms
    (lambda d: d["tier_rules"].update(max_tier="10/0"), "max_tier"),
    (lambda d: d.update(races=[r for r in d["races"] if r["code"] != "OGR"]), "OGR"),  # a race the shards have rows for
    (lambda d: d["roles"].pop("melee"), "melee"),
    (lambda d: d["roles"]["tank"].update(setups_by_evidence={"strict": ["2h"], "wiki": ["1h-shield", "2h", "dw"]}), "setups"),
    (lambda d: d["roles"]["melee"]["setups_by_evidence"].update(wiki=["2h"]), "setups"),
    (lambda d: d["roles"]["tank"]["setups_by_evidence"].pop("wiki"), "tank"),
    (lambda d: d["buffs"].pop("raid"), "buffs"),
    (lambda d: d["profile_common"].pop("pools"), "reassemble"),
    (lambda d: d["races"][0].pop("naked"), "reassemble"),
    (lambda d: d["buffs"]["own"].pop("buff_totals"), "reassemble"),
]


@pytest.mark.parametrize(("change", "message"), BUNDLE_CHANGES)
def test_a_bundle_that_does_not_agree_with_the_shards_is_refused_with_the_file_and_the_field_named(scratch, change, message):
    scratch.edit(BUNDLE, change)
    with pytest.raises(data.ResultsError) as caught:
        scratch.load()
    text = str(caught.value)
    assert "engine-l50.json" in text and message in text
    assert "\n" not in text  # one line, as every refusal in this repository


#: what a level of ``setups_by_evidence`` may hold and still not be a list of names. A number cannot be iterated; a text and an object can, as their
#: letters and their keys, so a reader that iterates what it is given takes them for a list (an object with the setups for keys even passes the
#: comparison with the shards)
NOT_A_LIST_OF_SETUPS = [
    pytest.param(5, "must be a list", id="a whole number"),
    pytest.param(1.5, "must be a list", id="a number with a fraction"),
    pytest.param(True, "must be a list", id="true"),
    pytest.param("2h", "must be a list", id="a text"),
    pytest.param("", "must be a list", id="an empty text"),
    pytest.param({"1h-shield": 1, "2h": 1, "dw": 1}, "must be a list", id="an object with the setups for keys"),
    pytest.param([["2h"]], "[0]: must be text", id="a list of lists"),
    pytest.param(["1h-shield", "2h", "dw", None], "[3]: must be text", id="a list with a null in it"),
]


@pytest.mark.parametrize("level", ["strict", "wiki"])
@pytest.mark.parametrize(("value", "message"), NOT_A_LIST_OF_SETUPS)
def test_a_bundle_whose_setups_at_a_level_are_not_a_list_of_names_is_refused_as_that(scratch, level, value, message):
    scratch.edit(BUNDLE, lambda d: d["roles"]["tank"]["setups_by_evidence"].update({level: value}))
    with pytest.raises(data.ResultsError) as caught:
        scratch.load()
    text = str(caught.value)
    assert text.startswith(f"{SLUG}/engine-l50.json: roles.tank.setups_by_evidence.{level}") and message in text
    assert "\n" not in text


def test_a_bundle_that_is_missing_or_unreadable_is_named(scratch):
    path = scratch.root / BUNDLE
    path.write_text("[1, 2", encoding="utf-8")
    with pytest.raises(data.ResultsError, match=r"engine-l50\.json"):
        scratch.load()
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(data.ResultsError, match=r"engine-l50\.json records no rules_version"):  # (a bundle that is no object records no version: refused as old, with the file named, before it is read)
        scratch.load()
    path.unlink()
    with pytest.raises(data.ResultsError, match=r"engine-l50\.json.*missing"):
        scratch.load()


def test_a_bundle_of_another_level_is_not_the_one_a_trio_reads(scratch):
    (scratch.root / BUNDLE).rename(scratch.root / SLUG / "engine-l55.json")
    with pytest.raises(data.ResultsError, match=r"engine-l50\.json.*missing"):
        scratch.load()


def test_the_bundle_is_checked_by_the_exporters_own_reader_for_every_evidence_level_and_corner(scratch, monkeypatch):
    seen = []
    real = browser.assemble

    def spy(document, race, role, buffs, **options):
        seen.append((race, role, buffs, options.get("evidence")))
        return real(document, race, role, buffs, **options)

    monkeypatch.setattr(browser, "assemble", spy)
    scratch.load()
    assert {evidence for *_, evidence in seen} == {None, "strict", "wiki"}
    assert {race for race, *_ in seen} >= {"HUM", "DEF"} and {buffs for _, _, buffs, _ in seen} == {"own", "raid"}
    assert {role for _, role, *_ in seen} == {"tank", "melee"}


# ---- the item table ------------------------------------------------------------------------------------------------------------

TABLE_CHANGES = [
    (lambda d: d.update(version=2), "version"),
    (lambda d: d.update(version=True), "version"),
    (lambda d: d.update(data_release="data-2026-10-20"), "data_release"),
    (lambda d: d.update(data_release=None), "data_release"),
    (lambda d: d.update(rules_version="2026-10-20"), "rules_version"),
    (lambda d: d.update(count=7), "count"),
    (lambda d: d.update(count="many"), "count"),
    (lambda d: d["defaults"].update(lore=True), "defaults"),
    (lambda d: d["defaults"].pop("owned_only"), "defaults"),
    (lambda d: d.update(extra=1), "extra"),
    (lambda d: d.pop("defaults"), "defaults"),
    (lambda d: d.update(items={}), "items"),
    (lambda d: d["items"].append("an item"), "items["),
    (lambda d: d["items"][0].update(price=5), "price"),  # a field a record has none of
    (lambda d: d["items"][0].pop("name"), "name"),
    (lambda d: d["items"][0].update(name=""), "name"),
    (lambda d: d["items"][0].update(name="a\x00b"), "name"),
    (lambda d: d["items"][0].update(slots=["HAT"]), "slots"),
    (lambda d: d["items"][0].update(slots=[]), "slots"),
    (lambda d: d["items"][0].update(tier_rule="loot"), "tier_rule"),
    (lambda d: d["items"][0].update(evidence={"level": "legend"}), "evidence"),
    (lambda d: d["items"][0].update(evidence="strict"), "evidence"),
    (lambda d: d["items"][0].update(id="546"), "id"),
    (lambda d: d["items"][0].update(key="Item 546"), "key"),
    (lambda d: d["items"][0].update(stats={"AC": "many"}), "stats"),
    (lambda d: d["items"][0].update(weight10=1.5), "weight10"),
    (lambda d: d["items"][0].update(owned_only=False), "owned_only"),  # a flag that is there only when it is true
    (lambda d: d["items"].append(copy.deepcopy(d["items"][0])), "twice"),
]


@pytest.mark.parametrize(("change", "message"), TABLE_CHANGES)
def test_an_item_table_that_is_not_what_the_precompute_writes_is_refused_with_the_file_and_the_field_named(scratch, change, message):
    scratch.edit("items.json", change)
    with pytest.raises(data.ResultsError) as caught:
        scratch.load()
    text = str(caught.value)
    assert text.startswith("items.json") and message in text
    assert "\n" not in text


def test_an_item_table_that_is_missing_or_unreadable_is_named(scratch):
    path = scratch.root / "items.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(data.ResultsError, match=r"^items\.json"):
        scratch.load()
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(data.ResultsError, match=r"^items\.json.*object"):
        scratch.load()
    path.unlink()
    with pytest.raises(data.ResultsError, match=r"^items\.json.*missing"):
        scratch.load()


AGREEMENT_CHANGES = [
    (lambda d: record(d, "w90001")["evidence"].update(level="wiki"), "w90001", "evidence"),
    (lambda d: record(d, "w90003")["evidence"].update(level="strict"), "w90003", "evidence"),
    (lambda d: record(d, "w90001").update(name="Helm of the Stonewall"), "w90001", "name"),
    (lambda d: record(d, "w90001").update(slots=["FACE"]), "w90001", "slots"),
    (lambda d: record(d, "w90001").update(tier_rule="fixed0"), "w90001", "tier_rule"),
    (lambda d: record(d, "w90004").pop("deity"), "w90004", "deity"),
    (lambda d: record(d, "w90001").update(deity=["Karana"]), "w90001", "deity"),
    (lambda d: d["items"].remove(record(d, "w90001")) or d.update(count=d["count"] - 1), "w90001", "no record"),
]


@pytest.mark.parametrize(("change", "key", "message"), AGREEMENT_CHANGES)
def test_a_table_that_does_not_describe_the_items_the_shards_show_the_way_they_do_is_refused(scratch, change, key, message):
    scratch.edit("items.json", change)
    with pytest.raises(data.ResultsError) as caught:
        scratch.load()
    text = str(caught.value)
    assert text.startswith("items.json") and key in text and message in text and SLUG in text
    assert "not from one run" in text or "no record" in text


def test_an_item_the_shards_never_show_may_differ_from_everything_else(scratch):
    scratch.edit("items.json", lambda d: record(d, "w90040").update(name="Cap of the Archwizard"))
    assert scratch.load().document["count"] > 40


def test_a_table_is_checked_against_every_trio_of_the_folder(scratch):
    """The table is one for the folder, so a second trio's items are held to it as well: a trio of another release is refused."""
    first = data.load_trio(scratch.root / SLUG)
    other = dataclasses.replace(first, meta=dataclasses.replace(first.meta, slug="pal-shd-ber", data_tag="data-2026-10-20"))
    with pytest.raises(data.ResultsError, match=r"items\.json.*data_release"):
        data.load_items(scratch.root, [first, other])
    assert data.load_items(scratch.root, [first, first]).document["count"] > 40  # the same trio twice is no cause for complaint


# ---- the real item table ------------------------------------------------------------------------------------------------------


def test_the_reader_takes_every_record_the_exporter_writes_for_the_real_catalog_with_and_without_seen_flags():
    from trioforge.data.jsonio import loads_strict
    from trioforge.model.tables import load

    catalog = loads_strict((REPO / "derived" / "catalog.json").read_text(encoding="utf-8"), "catalog.json")
    rules = load().rules
    seen = {item["key"] for item in catalog["items"][::7]}  # a seventh of the catalog, hidden items among them
    for flags in ((), seen):
        table = browser.items(catalog, rules, seen=flags)
        file = data._File("", "items", table)
        keys = [data._record(file, record, f"items[{n}]") for n, record in enumerate(table["items"])]
        assert len(set(keys)) == len(keys) == table["count"] > 6000
    assert any(record.get("owned_only") for record in table["items"]) and any(r["evidence"]["level"] == "strict" for r in table["items"])


# ---- the fingerprint of the inputs --------------------------------------------------------------------------------------------


def test_the_two_files_of_the_fixture_carry_one_fingerprint(results, table):
    assert results.bundle.document["inputs"] == table.document["inputs"]
    assert len(table.document["inputs"]) == 64


@pytest.mark.parametrize("name", [BUNDLE, "items.json"])
def test_a_file_made_before_the_precompute_wrote_a_fingerprint_is_refused_with_the_advice_to_run_it_again(scratch, name):
    scratch.edit(name, lambda d: d.pop("inputs"))
    with pytest.raises(data.ResultsError) as caught:
        scratch.load()
    text = str(caught.value)
    assert name.split("/")[-1] in text and "inputs" in text and "run the precompute again" in text and "\n" not in text


@pytest.mark.parametrize("bad", ["", "AB" * 32, "ab" * 31, "ab" * 33, "gg" * 32, 5, None, ["ab" * 32]])
@pytest.mark.parametrize("name", [BUNDLE, "items.json"])
def test_a_fingerprint_that_is_not_a_sha256_is_refused(scratch, name, bad):
    scratch.edit(name, lambda d: d.update(inputs=bad))
    with pytest.raises(data.ResultsError, match=r"inputs.*SHA-256"):
        scratch.load()


@pytest.mark.parametrize("name", [BUNDLE, "items.json"])
def test_a_bundle_and_a_table_made_from_other_inputs_are_refused_and_the_trio_to_run_again_is_named(scratch, name):
    scratch.edit(name, lambda d: d.update(inputs="0" * 64))
    with pytest.raises(data.ResultsError) as caught:
        scratch.load()
    text = str(caught.value)
    assert SLUG in text and "items.json" in text and "other inputs" in text and f"run the precompute again for {SLUG}" in text
    assert "\n" not in text and "0" * 64 not in text  # it does not quote the file


def test_every_trio_that_was_made_from_other_inputs_is_named(scratch):
    first = data.load_trio(scratch.root / SLUG)
    stale_bundle = dataclasses.replace(first.bundle, document={**first.bundle.document, "inputs": "0" * 64})
    other = dataclasses.replace(first, meta=dataclasses.replace(first.meta, slug="pal-shd-ber"), bundle=stale_bundle)
    third = dataclasses.replace(first, meta=dataclasses.replace(first.meta, slug="war-rog-ber"), bundle=stale_bundle)
    with pytest.raises(data.ResultsError) as caught:
        data.load_items(scratch.root, [first, other, third])
    text = str(caught.value)
    assert "pal-shd-ber" in text and "war-rog-ber" in text and SLUG not in text  # the one that matches is not
    assert "run the precompute again for pal-shd-ber" in text and "run the precompute again for war-rog-ber" in text


# ---- the weapon setups of the bundle and the levels of the table -----------------------------------------------------------------


def strict_shields(document):
    return [r for r in document["items"] if "SECONDARY" in r["slots"] and str(r.get("item_type", "")).lower() == "shield" and r["evidence"]["level"] == "strict"]


def test_a_bundle_that_lists_the_shield_setup_at_a_level_where_the_table_has_no_shield_is_refused(scratch):
    assert strict_shields(json.loads((scratch.root / "items.json").read_text(encoding="utf-8")))  # the fixture has one at the strict level
    assert "1h-shield" in json.loads((scratch.root / BUNDLE).read_text(encoding="utf-8"))["roles"]["tank"]["setups_by_evidence"]["strict"]

    def demote(document):
        for r in strict_shields(document):
            r["evidence"]["level"] = "wiki"

    scratch.edit("items.json", demote)
    with pytest.raises(data.ResultsError) as caught:
        scratch.load()
    text = str(caught.value)
    assert BUNDLE in text and "1h-shield" in text and "strict" in text and "items.json" in text and f"run the precompute again for {SLUG}" in text


def hand_bundle(*, strict, wiki):
    """A bundle with the one role that matters: its setups with a shield assumed, and its setups at each level."""
    return {
        "trio": ["PAL", "MNK", "BER"],
        "races": [{"code": "HUM"}, {"code": "DEF"}],
        "roles": {"tank": {"setups": ["1h-shield", "dw"], "setups_by_evidence": {"strict": strict, "wiki": wiki}}},
    }


def hand_shield(level, **changes):
    return {"id": 70001, "name": "Test Shield", "slots": ["SECONDARY"], "item_type": "Shield", "tier_rule": "fixed0", "evidence": {"level": level}, **changes}


def shields_agree(bundle, records):
    file = data._File(SLUG, "engine-l50", bundle)
    data._check_shield_setups(file, bundle, records, SLUG)


def test_the_shield_setup_of_a_level_agrees_with_the_shields_of_the_pool_of_that_level():
    shields_agree(hand_bundle(strict=["dw"], wiki=["1h-shield", "dw"]), [hand_shield("wiki")])  # a wiki shield: the wiki level has the setup, the strict does not
    shields_agree(hand_bundle(strict=["1h-shield", "dw"], wiki=["1h-shield", "dw"]), [hand_shield("strict")])  # a strict shield is in both pools
    shields_agree(hand_bundle(strict=["dw"], wiki=["dw"]), [])  # no shield, no setup
    # what is not in a pool does not count: a hidden shield, a shield only for another class, a deity's shield, a shield that is no good for the best-in-slot lists
    for other in (
        hand_shield("hidden"), hand_shield("strict", classes=["WIZ"]), hand_shield("strict", deity=["Karana"]),
        hand_shield("strict", evidence={"level": "strict", "codes": ["not-for-bis"]}),
    ):  # fmt: skip
        shields_agree(hand_bundle(strict=["dw"], wiki=["dw"]), [other])
    # a shield that only some races wear may or may not make the setup (the exporter refuses such a pool for a bundle): the table cannot say which
    shields_agree(hand_bundle(strict=["dw"], wiki=["dw"]), [hand_shield("wiki", races=["DEF"])])
    shields_agree(hand_bundle(strict=["dw"], wiki=["1h-shield", "dw"]), [hand_shield("wiki", races=["DEF"])])


def test_a_bundle_that_has_no_shield_setup_where_a_shield_of_every_race_is_in_the_pool_is_refused():
    with pytest.raises(data.ResultsError, match=r"engine-l50\.json.*tank.*wiki.*1h-shield"):
        shields_agree(hand_bundle(strict=["dw"], wiki=["dw"]), [hand_shield("wiki")])
    with pytest.raises(data.ResultsError, match=r"strict.*1h-shield"):
        shields_agree(hand_bundle(strict=["dw"], wiki=["1h-shield", "dw"]), [hand_shield("strict", races=["ALL"])])
    with pytest.raises(data.ResultsError, match=r"wiki.*1h-shield"):
        shields_agree(hand_bundle(strict=["dw"], wiki=["dw"]), [hand_shield("wiki", races=["HUM", "DEF"])])  # every race of the bundle


def test_a_bundle_that_lists_the_shield_setup_with_no_shield_at_all_in_the_table_is_refused():
    with pytest.raises(data.ResultsError, match=r"tank.*strict.*1h-shield"):
        shields_agree(hand_bundle(strict=["1h-shield", "dw"], wiki=["1h-shield", "dw"]), [hand_shield("wiki")])  # only a wiki shield: the strict pool has none
    with pytest.raises(data.ResultsError, match=r"tank.*wiki.*1h-shield"):
        shields_agree(hand_bundle(strict=["dw"], wiki=["1h-shield", "dw"]), [])


@pytest.mark.parametrize("level", ["strict", "wiki"])
@pytest.mark.parametrize(
    "bad", [pytest.param(5, id="a number"), pytest.param("1h-shield", id="a text"), pytest.param({"1h-shield": 1}, id="an object")]
)
def test_the_shield_setup_is_looked_for_in_a_list_and_nothing_else(level, bad):
    """``"1h-shield" in x`` is true of a text that holds it and of an object that has it for a key, and a TypeError for a number."""
    levels = {"strict": ["dw"], "wiki": ["dw"], level: bad}
    with pytest.raises(data.ResultsError, match=rf"engine-l50\.json: roles\.tank\.setups_by_evidence\.{level}: must be a list"):
        shields_agree(hand_bundle(**levels), [hand_shield("wiki")])


# ---- the keys of the items, and a page that names one item -------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["w07", "w0", "w00123", "w1234567890123456", "W7", "w-7"])
def test_a_key_with_a_zero_in_front_of_the_page_id_is_not_a_key(scratch, key):
    scratch.edit("items.json", lambda d: record(d, "w90001").update(key=key))
    with pytest.raises(data.ResultsError, match=r"^items\.json.*key"):
        scratch.load()


def test_two_records_of_one_page_are_refused_whatever_keys_they_have(scratch):
    def second(document):
        copy_of = copy.deepcopy(record(document, "w90003"))
        copy_of["key"] = "rsame-page"
        document["items"].append(copy_of)
        document["count"] += 1

    scratch.edit("items.json", second)
    with pytest.raises(data.ResultsError, match=r"^items\.json.*(page|twice)"):
        scratch.load()


# ---- the limits of a record: the browser's reader refuses what this one does not, and the build runs that one on everything it publishes ----------


def one_record(change):
    return change


SIX_WAYS = {
    "17 deities": lambda r: r.update(deity=[f"God {n}" for n in range(17)]),
    "17 races": lambda r: r.update(races=[f"R{n:02d}" for n in range(17)]),
    "an item type of 41 characters": lambda r: r.update(item_type="x" * 41, item_type_source=None),
    "a name with a line separator": lambda r: r.update(name="Cap of the\u2028Stoneward"),
    "41 reason codes": lambda r: r["evidence"].update(codes=[f"code-{n}" for n in range(41)]),
    "a stat the model does not know": lambda r: r.update(stats={**r.get("stats", {}), "FOO": 3}),
}


@pytest.mark.parametrize("name", list(SIX_WAYS))
def test_one_record_mutated_six_ways_is_refused_each_with_the_file_and_the_record_named(scratch, name):
    scratch.edit("items.json", lambda d: SIX_WAYS[name](record(d, "w90001")))
    with pytest.raises(data.ResultsError) as caught:
        scratch.load()
    text = str(caught.value)
    assert text.startswith("items.json") and "w90001" in text and "\n" not in text, text


MORE_LIMITS = {
    "65 aliases": lambda r: r.update(aliases=[f"A {n}" for n in range(65)]),
    "18 classes": lambda r: r.update(classes=[f"C{n:02d}" for n in range(18)]),
    "an empty list of deities": lambda r: r.update(deity=[]),
    "a name with a paragraph separator": lambda r: r.update(name="Cap\u2029"),
    "a name with a next-line character": lambda r: r.update(name="Cap\u0085x"),
    "an alias with a control character": lambda r: r.update(aliases=["a\u0007b"]),
    "a reason code of 81 characters": lambda r: r["evidence"].update(codes=["c" * 81]),
    "a resist the model does not know": lambda r: r.update(sv={"PHYSICAL": 3}),
    "a stat name in small letters": lambda r: r.update(stats={"ac": 3}),
    "an item type source of 41 characters": lambda r: r.update(item_type="Shield", item_type_source="x" * 41),
    "a stat of a thousand million and one": lambda r: r.update(stats={"AC": 1_000_000_001}),
}


@pytest.mark.parametrize("name", list(MORE_LIMITS))
def test_the_other_limits_of_a_record_are_held_to_as_well(scratch, name):
    scratch.edit("items.json", lambda d: MORE_LIMITS[name](record(d, "w90001")))
    with pytest.raises(data.ResultsError, match=r"^items\.json.*w90001"):
        scratch.load()


GOOD_LIMITS = {
    "16 deities": lambda r: r.update(deity=[f"God {n}" for n in range(16)]),
    "16 races": lambda r: r.update(races=[f"R{n:02d}" for n in range(16)]),
    "17 classes": lambda r: r.update(classes=[f"C{n:02d}" for n in range(17)]),
    "64 aliases": lambda r: r.update(aliases=[f"A {n}" for n in range(64)]),
    "an item type of 40 characters": lambda r: r.update(item_type="x" * 40, item_type_source="y" * 40),
    "40 reason codes of 80 characters": lambda r: r["evidence"].update(codes=[f"{n:02d}" + "c" * 78 for n in range(40)]),
    "every stat and every resist the model knows": lambda r: r.update(
        stats={name: 1 for name in "AC STR STA AGI DEX WIS INT CHA HP MANA END ATK HPREG MANAREG ENDREG HASTE".split()},
        sv={name: 1 for name in "FIRE COLD MAGIC POISON DISEASE CORRUPTION".split()},
    ),
    "a name with accents": lambda r: r.update(name="Cap of the \u00c9lan"),
}


@pytest.mark.parametrize("name", list(GOOD_LIMITS))
def test_a_record_at_the_limits_is_taken(scratch, name):
    scratch.edit("items.json", lambda d: GOOD_LIMITS[name](record(d, "w90040")))  # an item no shard shows
    assert scratch.load().document["count"] > 40


SOURCE_SHAPES = {
    "a source that is not an object": lambda r: r.update(source="The Hole"),
    "a source with nothing in it": lambda r: r.update(source={}),
    "a part the exporter does not write": lambda r: r.update(source={"price": 5}),
    "a list that is empty": lambda r: r.update(source={"drops": []}),
    "a list longer than the exporter makes it": lambda r: r.update(source={"drops": ["A", "B", "C", "D"]}),
    "a place twice": lambda r: r.update(source={"sold": ["A", "A"]}),
    "a place that is no text": lambda r: r.update(source={"quests": [5]}),
    "a place with a line separator": lambda r: r.update(source={"drops": ["a\u2028b"]}),
    "a place of 201 characters": lambda r: r.update(source={"drops": ["x" * 201]}),
    "crafted that is not a count": lambda r: r.update(source={"crafted": 0}),
    "crafted that is no number": lambda r: r.update(source={"crafted": "2"}),
    "more that counts a list that is not full": lambda r: r.update(source={"drops": ["A"], "more": {"drops": 2}}),
    "more with a count that is not whole": lambda r: r.update(source={"drops": ["A", "B", "C"], "more": {"drops": 1.5}}),
    "more of a kind that is not counted": lambda r: r.update(source={"crafted": 1, "more": {"crafted": 1}}),
    "more with nothing in it": lambda r: r.update(source={"drops": ["A", "B", "C"], "more": {}}),
}


@pytest.mark.parametrize("name", list(SOURCE_SHAPES))
def test_the_source_of_an_item_is_held_to_the_shape_the_exporter_writes(scratch, name):
    scratch.edit("items.json", lambda d: SOURCE_SHAPES[name](record(d, "w90040")))
    with pytest.raises(data.ResultsError, match=r"^items\.json.*w90040.*source"):
        scratch.load()


def test_the_sources_the_exporter_writes_are_taken(scratch):
    shapes = [
        {"drops": ["The Hole"]},
        {"drops": ["A", "B", "C"], "more": {"drops": 4}},
        {"sold": ["A", "B"], "forage": ["C"], "quests": ["Q1", "Q2"], "more": {"quests": 3}, "crafted": 2},
    ]
    for shape in shapes:
        scratch.edit("items.json", lambda d, shape=shape: record(d, "w90040").update(source=shape))
        assert scratch.load().document["count"] > 40


# ---- the limits of a bundle ----------------------------------------------------------------------------------------------------


def deep(levels):
    node = "x"
    for _ in range(levels):
        node = [node]
    return node


BUNDLE_LIMIT_CHANGES = {
    "a list nested 17 deep": (lambda d: d["tier_rules"].update(note=deep(16)), "deep"),
    "a text of 10,001 characters": (lambda d: d["tier_rules"].update(note="x" * 10_001), "text"),
    "2,501 exact numbers": (lambda d: d["constants"].update(note=["1/1"] * 2_501), "exact"),
    "an exact number of 65 digits": (lambda d: d["tier_rules"].update(note="1" * 65 + "/1"), "digits"),
    "an exact number with a denominator of 65 digits": (lambda d: d["tier_rules"].update(note="1/1" + "0" * 64), "digits"),
    "a whole number a double does not hold": (lambda d: d["profile_common"].update(level=2**60), "exactly"),
    "a key that could poison a lookup": (lambda d: d["tier_rules"].update(note=json.loads('{"__proto__": 1}')), "poison"),
    "a list of more than a hundred thousand parts": (lambda d: d["tier_rules"].update(note=[0] * 100_001), "long"),
}


@pytest.mark.parametrize("name", list(BUNDLE_LIMIT_CHANGES))
def test_a_bundle_over_a_limit_of_the_browsers_reader_is_refused_with_the_file_named(scratch, name):
    change, message = BUNDLE_LIMIT_CHANGES[name]
    scratch.edit(BUNDLE, change)
    with pytest.raises(data.ResultsError) as caught:
        scratch.load()
    text = str(caught.value)
    assert "engine-l50.json" in text and message in text and "\n" not in text, text


GOOD_BUNDLE_LIMITS = {
    "a list nested 15 deep": lambda d: d["tier_rules"].update(note=deep(13)),
    "a text of 10,000 characters": lambda d: d["tier_rules"].update(note="x" * 10_000),
    "an exact number of 64 digits a part": lambda d: d["tier_rules"].update(note="9" * 64 + "/1" + "0" * 63),
}


@pytest.mark.parametrize("name", list(GOOD_BUNDLE_LIMITS))
def test_a_bundle_at_the_limits_is_taken(scratch, name):
    scratch.edit(BUNDLE, GOOD_BUNDLE_LIMITS[name])
    assert scratch.load().document["count"] > 40


# ---- one place for each number --------------------------------------------------------------------------------------------------


def node_json(script: str) -> dict:
    done = subprocess.run(["node", "--input-type=module"], input=script, capture_output=True, text=True, check=False, cwd=REPO)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_limits_and_the_vocabularies_are_those_of_the_browsers_readers():
    """The same numbers are written in items.js and profile.js and here; a change of one that the others did not follow is a build that passes what the worker
    then refuses, or the other way round."""
    engine = REPO / "pipeline" / "trioforge" / "site" / "static" / "engine"
    script = (
        f"import {{ RECORD_LIMITS, STAT_KEYS, REGEN_KEYS, SV_KEYS }} from {json.dumps((engine / 'items.js').as_uri())};"
        f"import {{ BUNDLE_LIMITS }} from {json.dumps((engine / 'profile.js').as_uri())};"
        "console.log(JSON.stringify({ record: RECORD_LIMITS, bundle: BUNDLE_LIMITS, stats: [...STAT_KEYS, ...REGEN_KEYS, 'HASTE'], resists: [...SV_KEYS] }));"
    )
    seen = node_json(script)
    assert seen["record"] == data.RECORD_LIMITS
    assert seen["bundle"] == data.BUNDLE_LIMITS
    assert sorted(seen["stats"]) == sorted(data.STAT_NAMES) and sorted(seen["resists"]) == sorted(data.SV_NAMES)
    assert seen["record"]["slots"] == len(data.ITEM_SLOTS)
