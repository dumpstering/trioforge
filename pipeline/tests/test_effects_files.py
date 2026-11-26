"""Tests for the files of the effects layer: the derived spell file, the shared ``effects.json``, the per-trio ``exalt.json``, their budgets, the release allowlist
and the writer the release build calls."""

import gzip
import json
import shutil
from dataclasses import replace
from itertools import combinations
from pathlib import Path

import pytest

from trioforge.classes import CLASS_CODES
from trioforge.data import jsonio
from trioforge.effects import derive, files, judgment, plan
from trioforge.effects import spells as sp
from trioforge.model.roles import roles_for
from trioforge.precompute import assemble, release
from trioforge.rules import load as load_rules
from trioforge.sources import client_tables as ct

REPO = Path(__file__).resolve().parents[2]
J = judgment.default()
PLACES = ["HEAD", "FACE", "EAR1", "EAR2", "NECK", "SHOULDERS", "ARMS", "BACK", "WRIST1", "WRIST2", "HANDS", "FINGER1", "FINGER2", "CHEST", "LEGS", "FEET", "WAIST", "RANGE", "ANY1", "ANY2", "PRIMARY", "SECONDARY"]  # fmt: skip


@pytest.fixture(scope="module")
def catalog():
    return json.loads((REPO / "derived" / "catalog.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def built(catalog):
    return files.build(catalog, sp.SpellBook.load(), J, load_rules().version)  # (the rules version of the checkout: the site's reader refuses files of another)


def pseudo_kit(built, classes):
    """A kit of real catalog items that the classes can wear: the first item (by key) of the slot of each place; an Any place takes a second item of the slot of the
    place before it. Representative of a kit in shape (22 distinct items of the right slots, real classes and slots), not in value."""
    items = sorted((key, rec) for key, rec in built.items.items() if rec["slots"])
    chosen: dict[str, list[str]] = {}
    for key, rec in items:
        if not any("ALL" in rec["classes"] or c in rec["classes"] for c in classes):
            continue
        for slot in rec["slots"]:
            chosen.setdefault(slot, []).append(key)
    kit, used = [], set()
    for place in PLACES:
        slot = place.rstrip("12")
        if slot == "ANY":
            slot = "BACK" if place == "ANY1" else "FINGER"
        for key in chosen.get(slot, []):
            if key not in used:
                used.add(key)
                kit.append((place, key))
                break
    return kit


# ---- the derived spell file --------------------------------------------------------------------------------------------------------------------------


CLASS_ORDER = "WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER".split()


def spell_line(spell_id, name, classes, effects, *, good=1, target=5, cast_ms=2000, mana=10, width=174):
    fields = ["0"] * width
    fields[0], fields[1], fields[8], fields[14], fields[28], fields[30] = str(spell_id), name, str(cast_ms), str(mana), str(good), str(target)
    for position in range(16):
        fields[36 + position] = "255"
    for code, level in classes.items():
        fields[36 + CLASS_ORDER.index(code)] = str(level)
    fields[-1] = effects
    return "^".join(fields)


def write_spells(path, *lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(line + "\r\n" for line in lines).encode("utf-8"))
    return path


@pytest.fixture
def small_files(monkeypatch):
    for name in dict(ct.MINIMUM_ROWS):
        monkeypatch.setitem(ct.MINIMUM_ROWS, name, 1)


def test_the_derived_spells_are_the_class_spells_to_the_cap_and_the_spells_the_wiki_names(tmp_path, small_files):
    path = write_spells(
        tmp_path / "spells_us.txt",
        spell_line(1, "Nuke", {"WIZ": 40}, "1|0|-200|0|100|0"),
        spell_line(2, "Too High", {"WIZ": 60}, "1|0|-9|0|100|0"),
        spell_line(3, "Firestrike", {}, "1|0|-300|0|100|0"),  # no class gets it, but an item's effect is called this
        spell_line(4, "Nobody", {}, "1|0|-1|0|100|0"),
    )
    rows = derive.read_rows(path, {"Firestrike"})
    assert [r["name"] for r in rows] == ["", "Firestrike"]  # only a spell that an item effect names keeps its name
    nuke = rows[0]
    assert nuke["lv"] == {"WIZ": 40} and nuke["fx"] == [[1, 0, -200, 0, 100, 0]] and (nuke["cast_ms"], nuke["mana"], nuke["tgt"], nuke["ben"]) == (2000, 10, 5, 1)


def test_the_derived_reader_refuses_what_the_spell_reader_refuses(tmp_path, small_files):
    dup = write_spells(tmp_path / "a.txt", spell_line(1, "A", {"WIZ": 1}, "1|0|-1|0|100|0"), spell_line(1, "B", {"WIZ": 1}, "1|0|-1|0|100|0"))
    with pytest.raises(ValueError, match="repeated|twice|again|duplicate|already"):
        derive.read_rows(dup, set())
    short = write_spells(tmp_path / "b.txt", spell_line(1, "A", {"WIZ": 1}, "1|0|-1|0|100|0", width=100))
    with pytest.raises(ValueError, match="columns"):
        derive.read_rows(short, set())


def test_effect_names_come_from_wiki_items_only_and_apply_the_aliases():
    catalog = {"items": [
        {"evidence": {"level": "wiki"}, "effects": [{"name": "Complete Healing"}, {"name": "Stun"}]},
        {"evidence": {"level": "hidden"}, "effects": [{"name": "Secret"}]},
    ]}  # fmt: skip
    assert derive.effect_names(catalog) == {"Complete Heal", "Stun"}


def test_generate_writes_the_file_and_keeps_the_date_the_manifest_has_for_the_same_client_file(tmp_path, small_files):
    client, out = tmp_path / "client", tmp_path / "out"
    write_spells(client / "spells_us.txt", spell_line(1, "Nuke", {"WIZ": 40}, "1|0|-200|0|100|0"))
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"items": []}), encoding="utf-8")
    digest = ct.input_record(client, "spells_us.txt")["sha256"]
    out.mkdir()
    (out / "manifest.json").write_text(
        ct.render_json({"generated": "2026-10-14", "inputs": [{"file": "spells_us.txt", "sha256": digest, "date": "2026-10-13"}], "outputs": []}), encoding="utf-8"
    )
    assert derive.generate(client, out, catalog, "2026-10-24") == "effect-spells.json: 1 spells"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["inputs"][0]["date"] == "2026-10-13"  # a copy of the file has a date of its own; the manifest keeps its
    assert [o["file"] for o in manifest["outputs"]] == ["effect-spells.json"]
    book = sp.SpellBook.load(out / "effect-spells.json")
    assert book.source_sha256 == digest and [r["id"] for r in book.rows] == [1] and book.by_name == {}


def test_generate_records_the_effect_names_of_the_catalog_it_was_derived_for(tmp_path, small_files):
    """E3: a spell is kept by name only when an item of the catalog calls it by that name, so a file knows which names it was made for. The names (aliases applied, sorted) are in the file."""
    client, out = tmp_path / "client", tmp_path / "out"
    write_spells(client / "spells_us.txt", spell_line(1, "Nuke", {"WIZ": 40}, "1|0|-200|0|100|0"))
    catalog = tmp_path / "catalog.json"
    items = [{"evidence": {"level": "wiki"}, "effects": [{"name": "Nuke"}, {"name": "Complete Healing"}]}, {"evidence": {"level": "hidden"}, "effects": [{"name": "Secret"}]}]
    catalog.write_text(json.dumps({"items": items}), encoding="utf-8")
    out.mkdir()
    derive.generate(client, out, catalog, "2026-10-24")
    assert json.loads((out / "effect-spells.json").read_text(encoding="utf-8"))["catalog_names"] == ["Complete Heal", "Nuke"]
    assert sp.SpellBook.load(out / "effect-spells.json").derived_for == frozenset({"Complete Heal", "Nuke"})


def test_a_book_made_for_some_names_refuses_a_catalog_that_names_another(tmp_path):
    book = sp.SpellBook([], 50, None, ["Ember Brand", "Stun"])
    book.check_names({"Stun"})  # (a name fewer is no stale file: the spells of the book are enough for it)
    book.check_names(set())
    with pytest.raises(ValueError, match=r"2 effect names.*Gale Brand.*Ice Brand.*derive") as raised:
        book.check_names({"Stun", "Gale Brand", "Ice Brand"})
    assert "Stun" not in str(raised.value).split("derive")[0]  # (only the names that are new are said)
    sp.SpellBook([], 50).check_names({"Stun"})  # (a file made before the record says nothing of its names: nothing is refused for it, and the next derive writes the record)


def test_the_committed_spell_file_passes_the_check_of_the_catalog_names_with_or_without_the_record(catalog):
    """The committed file was derived (2026-10-24) before the record was written, so it has none and nothing can be refused for it; a derive that writes the record must be for the catalog it is
    committed with (the day the file is derived again, this holds it to that)."""
    book = sp.SpellBook.load()
    book.check_names(derive.effect_names(catalog))
    assert book.derived_for is None or derive.effect_names(catalog) <= book.derived_for


def test_write_effects_refuses_a_catalog_with_an_effect_the_spell_file_was_not_derived_for(results, tmp_path, catalog):
    root = tmp_path / "root"
    (root / "rules").mkdir(parents=True)
    (root / "derived" / "client").mkdir(parents=True)
    shutil.copy(REPO / "rules" / "rules.json", root / "rules" / "rules.json")
    spells = json.loads((REPO / "derived" / "client" / "effect-spells.json").read_text(encoding="utf-8"))
    spells["catalog_names"] = sorted(derive.effect_names(catalog))  # (a file that was derived for this catalog: the record the derive writes)
    (root / "derived" / "client" / "effect-spells.json").write_text(json.dumps(spells), encoding="utf-8")
    newer = json.loads(json.dumps(catalog))
    wiki = next(item for item in newer["items"] if item["evidence"]["level"] == "wiki" and item["effects"])
    wiki["effects"] = [*wiki["effects"], {"kind": "proc", "name": "Brand Newer Than The File", "raw": "Effect: Brand Newer Than The File (Combat)"}]
    with pytest.raises(assemble.ReleaseRefused, match=r"Brand Newer Than The File.*derive"):
        release.write_effects(results, ["pal-mnk-ber"], newer, root, print)
    assert not (results / "effects.json").exists()


def test_the_committed_spell_file_is_made_from_the_client_file_the_manifest_names():
    manifest = json.loads((REPO / "derived" / "client" / "manifest.json").read_text(encoding="utf-8"))
    recorded = next(i["sha256"] for i in manifest["inputs"] if i["file"] == "spells_us.txt")
    assert sp.SpellBook.load().source_sha256 == recorded
    assert any(o["file"] == derive.FILE and o["inputs"] == ["spells_us.txt"] for o in manifest["outputs"])


# ---- the shared file and the trio file --------------------------------------------------------------------------------------------------------------------


def test_the_shared_file_lists_each_effect_once_with_its_donors_easiest_first(built):
    shared = files.shared_document(built)
    ids = [e["id"] for e in shared["effects"]]
    assert ids == sorted(ids) and len(ids) == len(set(ids))
    assert shared["version"] == 1 and shared["license"] == "CC BY-SA 4.0" and "eqlwiki" in shared["attribution"] and len(shared["spells_us"]) == 64
    assert set(shared["mass"]) == set(CLASS_CODES) and all(0 <= m <= 1 for m in shared["mass"].values()) and shared["mass"]["WIZ"] == 1.0 and shared["mass"]["WAR"] == 0.0
    pillage = next(e for e in shared["effects"] if e["n"] == "Pillage Enchantment")
    assert (pillage["k"], pillage["c"], pillage["m"], pillage["u"]) == ("click", "dispel", 4, "buffs")
    carry = next(e for e in shared["effects"] if e["n"] == "Levitate" and e["k"] == "carry")
    assert carry["d"] and all(isinstance(access, int) for _, access in carry["d"])
    for effect in shared["effects"]:
        assert set(effect["x"]) <= {"ambiguous", "equip", "inferred", "description"}
    assert next(e for e in shared["effects"] if e["n"] == "Ykesha")["x"] == ["description"]


def _ineligible(effect):
    return {**effect, "items": [{**d, "eligible": False} for d in effect["items"]]}


def test_an_effect_whose_donors_are_none_of_them_in_the_item_table_is_not_in_the_shared_file(built):
    # data-2026-10-27: e183 and e186 (AMMO-only mount clicks) were written with an empty donor list
    shared = files.shared_document(built)
    assert all(row["d"] for row in shared["effects"])
    skipped = [e for e in built.effects if not any(d["eligible"] for d in e["items"])]
    assert skipped, "the catalog has effects with no wearable donor (the mounts); the test would prove nothing without them"
    assert not {e["id"] for e in skipped} & {row["id"] for row in shared["effects"]}
    template = next(e for e in built.effects if any(d["eligible"] for d in e["items"]) and e.get("category") != "unresolved" and e["kind"] != "focus")
    extra = {**_ineligible(template), "id": "e999"}
    more = replace(built, effects=[*built.effects, extra])
    assert "e999" not in {row["id"] for row in files.shared_document(more)["effects"]}


def test_no_trio_file_names_an_effect_that_the_shared_file_skipped(built):
    template = next(e for e in built.effects if e["kind"] == "click" and e.get("category") not in ("unresolved", None) and any(d["eligible"] for d in e["items"]))
    extra = {**_ineligible(template), "id": "e999"}
    ctx = replace(built.ctx, effects=[*built.ctx.effects, extra], by_id={**built.ctx.by_id, "e999": extra})
    more = replace(built, effects=[*built.effects, extra], ctx=ctx)
    shared_ids = {row["id"] for row in files.shared_document(more)["effects"]}
    skipped = {e["id"] for e in more.effects if not any(d["eligible"] for d in e["items"])}  # (the mounts of the catalog, and the effect made here)
    assert "e999" in skipped and len(skipped) > 1 and not skipped & shared_ids
    for classes in (["PAL", "MNK", "BER"], ["WAR", "CLR", "PAL"], ["WIZ", "MAG", "ENC"]):
        kit = pseudo_kit(more, classes)
        doc = files.trio_document(more, "-".join(c.lower() for c in classes), "OGR", 4, {role: kit for role in roles_for(classes)})
        named = {row["e"] for entry in doc["roles"].values() for part in ("focus", "click", "carry", "worn", "proc", "plan", "noroom") for row in entry[part]}
        assert named and not named & skipped
        assert named <= shared_ids


def test_the_shared_file_has_no_unresolved_effect_and_no_fingerprint_and_no_evidence_level(built):
    text = jsonio.render(files.shared_document(built), per_line=("effects",))
    assert "unresolved" not in text and "fingerprint" not in text and "seen-in-game" not in text and '"wiki"' not in text and '"strict"' not in text


def test_a_trio_file_has_the_offered_roles_only_and_item_keys_only(built):
    kit = pseudo_kit(built, ["PAL", "MNK", "BER"])
    doc = files.trio_document(built, "pal-mnk-ber", "OGR", 4, {"tank": kit, "caster": kit})
    assert list(doc["roles"]) == ["tank"]  # a caster build is not offered to a trio of PAL, MNK and BER, and melee had no kit
    entry = doc["roles"]["tank"]
    assert set(entry) == {"focus", "click", "carry", "worn", "proc", "plan", "noroom"}
    for name in ("focus", "click", "carry", "worn", "proc"):
        for row in entry[name]:
            assert set(row) >= {"e", "d", "o", "s", "m"} and row["d"] in built.items
    assert all(set(r) == {"k", "e", "d", "p", "h", "c", "u"} for r in entry["plan"])
    assert all(row["g"] and set(row["g"]) <= {"PAL", "MNK", "BER"} for row in entry["focus"])  # what each class adds to a focus
    assert all(set(r) == {"k", "e", "w"} and r["w"] in plan.REASONS for r in entry["noroom"])
    assert {r["h"] for r in entry["plan"]} <= {key for _, key in kit}


def test_one_focus_for_each_type_in_a_plan_and_one_effect_of_a_kind_for_each_host(built):
    for slug in ("pal-mnk-ber", "clr-shd-shm", "wiz-mag-enc", "brd-nec-dru"):
        classes = [c.upper() for c in slug.split("-")]
        kit = pseudo_kit(built, classes)
        doc = files.trio_document(built, slug, "OGR", 4, {role: kit for role in roles_for(classes)})
        for role, entry in doc["roles"].items():
            types = [row["t"] for row in entry["focus"]]
            assert len(types) == len(set(types))
            placed = [(r["k"], r["h"], r["p"]) for r in entry["plan"]]
            assert len(placed) == len(set(placed))
            type_of = {row["e"]: row["t"] for row in entry["focus"]}
            placed_types = [type_of[r["e"]] for r in entry["plan"] if r["k"] == "focus"]
            assert len(placed_types) == len(set(placed_types))  # one focus of each stacking type is placed


def test_a_plan_follows_the_rules_for_real_items(built, catalog):
    by_key = {item["key"]: item for item in catalog["items"]}
    for slug in ("pal-mnk-ber", "clr-shd-shm", "wiz-mag-enc"):
        classes = [c.upper() for c in slug.split("-")]
        kit = pseudo_kit(built, classes)
        doc = files.trio_document(built, slug, "OGR", 4, {role: kit for role in roles_for(classes)})
        for entry in doc["roles"].values():
            assert entry["plan"]
            for row in entry["plan"]:
                donor, host = by_key[row["d"]], by_key[row["h"]]
                assert set(donor["slots"]) & set(host["slots"])  # a like item
                assert row["c"] and all(c in classes and ("ALL" in donor["classes"] or c in donor["classes"]) and ("ALL" in host["classes"] or c in host["classes"]) for c in row["c"])
                if (donor.get("weapon") or {}).get("skill", "").startswith("2H") or donor["slots"] == ["PRIMARY"]:
                    assert "PRIMARY" in host["slots"] and row["p"] == "PRIMARY"  # the item sits in the primary hand itself


def test_the_trio_files_stay_under_the_budget_for_roles_full_of_rows(built):
    sample = [combo for combo in combinations(CLASS_CODES, 3) if len(roles_for(list(combo))) == 4][::12]  # trios with all four builds (Tank, Shield caster, Melee damage, Caster)
    assert len(sample) >= 5
    worst = 0
    for combo in sample:
        kit = pseudo_kit(built, list(combo))
        doc = files.trio_document(built, "-".join(c.lower() for c in combo), "OGR", 4, {role: kit for role in roles_for(list(combo))})
        packed = files.gzip_size(jsonio.render(doc).encode("utf-8"))
        worst = max(worst, packed)
        assert packed <= files.TRIO_GZIP_LIMIT
    assert worst < files.TRIO_GZIP_LIMIT // 2  # (a wide margin: the file is built from a few dozen short rows for each role)


def test_the_shared_file_is_within_its_budget(built):
    data = jsonio.render(files.shared_document(built), per_line=("effects",)).encode("utf-8")
    assert len(data) <= files.SHARED_RAW_LIMIT and files.gzip_size(data) <= files.SHARED_GZIP_LIMIT


# ---- the kits of the results ---------------------------------------------------------------------------------------------------------------------------------------


def test_default_kits_read_the_solved_kit_of_each_role_for_the_default_race_at_the_default_tier():
    race, tier, kits = files.default_kits(REPO / "fixtures" / "site" / "results" / "pal-mnk-ber")
    assert race == "OGR" and tier == 4 and set(kits) == {"tank", "melee"}
    for kit in kits.values():
        assert kit and all(place in PLACES for place, _ in kit) and len({place for place, _ in kit}) == len(kit)
    shard = json.loads((REPO / "fixtures" / "site" / "results" / "pal-mnk-ber" / "strict-own.json").read_text(encoding="utf-8"))
    best = max((r for r in shard["scenarios"] if r[0] == "OGR" and r[1] == "tank" and r[2] == 4), key=lambda r: r[5])
    keys = [row[0] for row in shard["items"]]
    assert kits["tank"] == [(place, keys[i]) for place, i in zip(shard["places"], shard["kits"][best[4]], strict=True) if i >= 0]


def test_the_kit_of_the_opening_build_is_in_the_setup_defaults_json_names(tmp_path):
    """E5: the shards keep the value of a row to two decimals and ``defaults.json`` the exact one, so two setups worth the same to the cent may be told apart differently. The opening build's
    setup is the file's own (``setup``), and the kit read is the row of that setup; the other builds, for which the file says nothing, keep the best of the rounded values."""
    folder = tmp_path / "pal-mnk-ber"
    shutil.copytree(REPO / "fixtures" / "site" / "results" / "pal-mnk-ber", folder)
    shard = json.loads((folder / "strict-own.json").read_text(encoding="utf-8"))
    rows = {r[3]: r for r in shard["scenarios"] if r[0] == "OGR" and r[1] == "tank" and r[2] == 4}
    assert set(rows) == {"1h-shield", "2h", "dw"} and max(rows.values(), key=lambda r: r[5])[3] == "dw"
    defaults = json.loads((folder / "defaults.json").read_text(encoding="utf-8"))
    assert defaults["view"]["role"] == "tank" and defaults["setup"] == "dw"
    keys = [row[0] for row in shard["items"]]

    def kit(row):
        return [(place, keys[i]) for place, i in zip(shard["places"], shard["kits"][row[4]], strict=True) if i >= 0]

    assert files.default_kits(folder)[2]["tank"] == kit(rows["dw"])
    defaults["setup"] = "2h"  # (the exact values put the two-hander first: the rounded ones are not the arbiter)
    (folder / "defaults.json").write_text(json.dumps(defaults), encoding="utf-8")
    kits = files.default_kits(folder)[2]
    assert kits["tank"] == kit(rows["2h"]) and kits["tank"] != kit(rows["dw"])
    best_melee = max((r for r in shard["scenarios"] if r[0] == "OGR" and r[1] == "melee" and r[2] == 4), key=lambda r: r[5])
    assert kits["melee"] == kit(best_melee)  # (not the opening build: the best of the rows, as before)
    defaults["setup"] = "ranged"  # (a setup the shard has no row for at that race and tier: the best row stands, and the file is not trusted over the rows)
    (folder / "defaults.json").write_text(json.dumps(defaults), encoding="utf-8")
    assert files.default_kits(folder)[2]["tank"] == kit(rows["dw"])


def test_a_trio_with_no_default_race_has_no_kits(tmp_path):
    folder = tmp_path / "pal-mnk-ber"
    shutil.copytree(REPO / "fixtures" / "site" / "results" / "pal-mnk-ber", folder)
    defaults = json.loads((folder / "defaults.json").read_text(encoding="utf-8"))
    defaults["race"] = None
    (folder / "defaults.json").write_text(json.dumps(defaults), encoding="utf-8")
    assert files.default_kits(folder) is None


# ---- the writer and the check ----------------------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def results(tmp_path):
    """Two trios of the fixture results (the fixture's items are made up, so their keys are not in the catalog) and an item table."""
    root = tmp_path / "results"
    for slug in ("pal-mnk-ber", "clr-shd-shm"):
        shutil.copytree(REPO / "fixtures" / "site" / "results" / "pal-mnk-ber", root / slug, ignore=shutil.ignore_patterns("runnerups"))
    shutil.copy(REPO / "fixtures" / "site" / "results" / "items.json", root / "items.json")
    return root


def test_the_writer_makes_the_shared_file_and_one_file_for_each_trio_with_a_default_race(results, built):
    sizes = files.write_release(results, ["pal-mnk-ber", "clr-shd-shm", "war-clr-pal"], built)
    assert sorted(sizes) == ["clr-shd-shm/exalt.json", "effects.json", "pal-mnk-ber/exalt.json"]  # war-clr-pal has no results folder
    doc = json.loads((results / "pal-mnk-ber" / "exalt.json").read_text(encoding="utf-8"))
    assert doc["trio"] == "pal-mnk-ber" and doc["race"] == "OGR" and doc["data_release"] == built.data_release
    assert files.check_release(results, ["pal-mnk-ber", "clr-shd-shm"]) == 2


def test_the_files_are_the_same_bytes_every_time(results, built):
    files.write_release(results, ["pal-mnk-ber"], built)
    first = [(results / name).read_bytes() for name in ("effects.json", "pal-mnk-ber/exalt.json")]
    files.write_release(results, ["pal-mnk-ber"], built)
    assert first == [(results / name).read_bytes() for name in ("effects.json", "pal-mnk-ber/exalt.json")]


def test_an_old_file_of_a_trio_with_no_default_race_is_removed(results, built):
    files.write_release(results, ["pal-mnk-ber"], built)
    defaults = json.loads((results / "pal-mnk-ber" / "defaults.json").read_text(encoding="utf-8"))
    defaults["race"] = None
    (results / "pal-mnk-ber" / "defaults.json").write_text(json.dumps(defaults), encoding="utf-8")
    files.write_release(results, ["pal-mnk-ber"], built)
    assert not (results / "pal-mnk-ber" / "exalt.json").exists()


def test_a_release_without_effects_files_passes_the_check(results):
    assert files.check_release(results, ["pal-mnk-ber", "clr-shd-shm"]) == 0


def test_the_check_refuses_a_trio_file_without_the_shared_file(results, built):
    files.write_release(results, ["pal-mnk-ber"], built)
    (results / "effects.json").unlink()
    with pytest.raises(files.EffectsError, match="effects.json is not"):
        files.check_release(results, ["pal-mnk-ber"])


def test_the_check_refuses_a_trio_file_over_its_budget(results, built):
    files.write_release(results, ["pal-mnk-ber"], built)
    path = results / "pal-mnk-ber" / "exalt.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    import random

    rng = random.Random(7)
    doc["roles"]["tank"]["noroom"] = [{"k": "focus", "e": "e000", "w": "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(40))} for _ in range(900)]
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert len(gzip.compress(path.read_bytes())) > files.TRIO_GZIP_LIMIT
    with pytest.raises(files.EffectsError, match="over the 20,480-byte budget"):
        files.check_release(results, ["pal-mnk-ber"])


def test_the_check_refuses_an_effect_the_shared_file_lacks_and_a_trio_made_for_another_release(results, built):
    files.write_release(results, ["pal-mnk-ber"], built)
    path = results / "pal-mnk-ber" / "exalt.json"
    good = json.loads(path.read_text(encoding="utf-8"))
    bad = json.loads(path.read_text(encoding="utf-8"))
    bad["roles"]["tank"]["focus"].append({"e": "e999", "d": "x", "o": [], "s": 1, "m": "PAL"})
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(files.EffectsError, match="effect e999"):
        files.check_release(results, ["pal-mnk-ber"])
    good["data_release"] = "data-1999-01-01"
    path.write_text(json.dumps(good), encoding="utf-8")
    with pytest.raises(files.EffectsError, match="another data release"):
        files.check_release(results, ["pal-mnk-ber"])


def test_the_check_refuses_a_host_the_item_table_lacks(results, built, catalog):
    kit = pseudo_kit(built, ["PAL", "MNK", "BER"])
    doc = files.trio_document(built, "pal-mnk-ber", "OGR", 4, {"tank": kit})
    (results / "pal-mnk-ber").mkdir(exist_ok=True)
    (results / "pal-mnk-ber" / "exalt.json").write_text(jsonio.render(doc), encoding="utf-8")
    (results / "effects.json").write_text(jsonio.render(files.shared_document(built), per_line=("effects",)), encoding="utf-8")
    keys = {key for _, key in kit}
    assert files.check_release(results, ["pal-mnk-ber"], keys | set(built.items)) == 1
    with pytest.raises(files.EffectsError, match="not in the item table"):
        files.check_release(results, ["pal-mnk-ber"], {"w1"})


def test_the_shared_file_over_its_budget_is_refused(results):
    (results / "effects.json").write_text(json.dumps({"version": 1, "pad": "x" * (files.SHARED_RAW_LIMIT + 1)}), encoding="utf-8")
    with pytest.raises(files.EffectsError, match="effects.json is"):
        files.check_release(results, [])


# ---- the release folder and the release build ------------------------------------------------------------------------------------------------------------------


def test_the_release_allowlist_has_the_two_files_and_still_refuses_others():
    assert assemble.EFFECTS_FILE == files.EFFECTS_FILE and assemble.EXALT_FILE == files.TRIO_FILE
    assert assemble.is_release_file("effects.json") and assemble.is_release_file("pal-mnk-ber/exalt.json")
    assert not assemble.is_release_file("pal-mnk-ber/effects.json") and not assemble.is_release_file("exalt.json") and not assemble.is_release_file("pal-mnk-ber/exalt.js")


def test_the_stage_carries_the_effects_files_when_there_are_any_and_works_without_them(results, built, tmp_path):
    plain = assemble.stage(results, ["pal-mnk-ber"], tmp_path / "plain")
    assert not (tmp_path / "plain" / "effects.json").exists() and plain.files == len(list((tmp_path / "plain").rglob("*.json")))
    files.write_release(results, ["pal-mnk-ber"], built)
    full = assemble.stage(results, ["pal-mnk-ber"], tmp_path / "full")
    assert (tmp_path / "full" / "effects.json").is_file() and (tmp_path / "full" / "pal-mnk-ber" / "exalt.json").is_file() and full.files == plain.files + 2
    assert assemble.check_clean(tmp_path / "full") == full.files


def test_the_effects_code_is_covered_by_the_code_hash_of_the_release():
    from trioforge.precompute import grid

    root = Path(assemble.__file__).resolve().parents[1]
    covered = set(assemble.WRITER_FILES) | {path.relative_to(root).as_posix() for path in grid.code_files()}  # (the weapon procs are made from the effects code: it is the code of the chunks now)
    for name in ("effects/__init__.py", "effects/derive.py", "effects/donors.py", "effects/files.py", "effects/judgment.py", "effects/layer.py", "effects/plan.py", "effects/score.py", "effects/spells.py"):
        assert name in covered
    assert not {name for name in assemble.WRITER_FILES if name.startswith("effects/")}  # (a file is in one of the two lists, not both)


def test_write_effects_does_nothing_without_the_spell_file_and_writes_with_it(results, tmp_path, catalog):
    root = tmp_path / "root"
    (root / "rules").mkdir(parents=True)
    shutil.copy(REPO / "rules" / "rules.json", root / "rules" / "rules.json")
    said: list[str] = []
    assert release.write_effects(results, ["pal-mnk-ber"], catalog, root, said.append) is False
    assert not (results / "effects.json").exists() and said == []
    (root / "derived" / "client").mkdir(parents=True)
    shutil.copy(REPO / "derived" / "client" / "effect-spells.json", root / "derived" / "client" / "effect-spells.json")
    assert release.write_effects(results, ["pal-mnk-ber"], catalog, root, said.append) is True
    assert (results / "effects.json").is_file() and (results / "pal-mnk-ber" / "exalt.json").is_file() and "effects:" in said[0]


def test_write_effects_refuses_a_spell_file_that_is_not_one(results, tmp_path, catalog):
    root = tmp_path / "root"
    (root / "rules").mkdir(parents=True)
    (root / "derived" / "client").mkdir(parents=True)
    shutil.copy(REPO / "rules" / "rules.json", root / "rules" / "rules.json")
    (root / "derived" / "client" / "effect-spells.json").write_text('{"nothing": 1}', encoding="utf-8")
    with pytest.raises(assemble.ReleaseRefused, match="effects files cannot be made"):
        release.write_effects(results, ["pal-mnk-ber"], catalog, root, print)


def test_the_site_reader_reads_results_with_and_without_the_effects_files(tmp_path, built):
    from trioforge.site import data

    folder = tmp_path / "pal-mnk-ber"
    shutil.copytree(REPO / "fixtures" / "site" / "results" / "pal-mnk-ber", folder)
    without = data.load_trio(folder)
    files.write_release(tmp_path, ["pal-mnk-ber"], built)
    assert (folder / "exalt.json").is_file()
    with_files = data.load_trio(folder)
    assert with_files.meta == without.meta and data.list_trios(tmp_path) == ["pal-mnk-ber"]


# ---- the fix round: stale files, malformed files, Any places (review findings 11, 12 and the Any-slot check) ------------------------------------------------


def test_an_old_exalt_file_in_a_folder_without_defaults_is_removed(results, built):
    files.write_release(results, ["pal-mnk-ber", "clr-shd-shm"], built)
    (results / "clr-shd-shm" / "defaults.json").unlink()  # the trio was built again and did not get as far as its defaults
    assert (results / "clr-shd-shm" / "exalt.json").is_file()
    sizes = files.write_release(results, ["pal-mnk-ber", "clr-shd-shm"], built)
    assert not (results / "clr-shd-shm" / "exalt.json").exists() and (results / "pal-mnk-ber" / "exalt.json").is_file()
    assert sorted(sizes) == ["effects.json", "pal-mnk-ber/exalt.json"]


def test_a_trio_with_no_folder_at_all_is_left_alone(results, built):
    assert sorted(files.write_release(results, ["war-clr-pal"], built)) == ["effects.json"]


def test_remove_release_takes_away_the_shared_file_and_the_files_of_the_trios_it_is_given_and_nothing_else(results, built):
    files.write_release(results, ["pal-mnk-ber", "clr-shd-shm"], built)
    assert files.remove_release(results, ["pal-mnk-ber", "war-clr-pal"]) == ["effects.json", "pal-mnk-ber/exalt.json"]
    assert (results / "clr-shd-shm" / "exalt.json").is_file() and (results / "items.json").is_file() and (results / "pal-mnk-ber" / "defaults.json").is_file()
    assert files.remove_release(results, ["pal-mnk-ber"]) == []


def test_a_build_without_the_layer_after_a_run_with_it_does_not_stage_the_old_files(results, built, tmp_path, catalog):
    files.write_release(results, ["pal-mnk-ber", "clr-shd-shm"], built)
    root = tmp_path / "root"
    (root / "rules").mkdir(parents=True)
    shutil.copy(REPO / "rules" / "rules.json", root / "rules" / "rules.json")  # a checkout that has no derived/client/effect-spells.json
    assert release.write_effects(results, ["pal-mnk-ber", "clr-shd-shm"], catalog, root, print) is False
    assert not (results / "effects.json").exists() and not (results / "pal-mnk-ber" / "exalt.json").exists()
    staged = assemble.stage(results, ["pal-mnk-ber", "clr-shd-shm"], tmp_path / "stage")
    assert not any(path.name in ("effects.json", "exalt.json") for path in (tmp_path / "stage").rglob("*.json"))
    assert files.check_release(tmp_path / "stage", ["pal-mnk-ber", "clr-shd-shm"]) == 0 and staged.files > 0


def test_a_build_with_the_layer_replaces_what_an_old_run_left(results, built, tmp_path, catalog):
    files.write_release(results, ["pal-mnk-ber"], built)
    (results / "pal-mnk-ber" / "exalt.json").write_text("old", encoding="utf-8")
    root = tmp_path / "root"
    (root / "rules").mkdir(parents=True)
    (root / "derived" / "client").mkdir(parents=True)
    shutil.copy(REPO / "rules" / "rules.json", root / "rules" / "rules.json")
    shutil.copy(REPO / "derived" / "client" / "effect-spells.json", root / "derived" / "client" / "effect-spells.json")
    assert release.write_effects(results, ["pal-mnk-ber"], catalog, root, print) is True
    assert json.loads((results / "pal-mnk-ber" / "exalt.json").read_text(encoding="utf-8"))["trio"] == "pal-mnk-ber"


MALFORMED_SHARED = [
    pytest.param("3", id="a-number"),
    pytest.param("[]", id="a-list"),
    pytest.param('{"version": 1}', id="no-effects"),
    pytest.param('{"version": 1, "effects": 4}', id="effects-not-a-list"),
    pytest.param('{"version": 1, "effects": [3]}', id="an-effect-not-an-object"),
    pytest.param('{"version": 1, "effects": [{"id": "e1"}]}', id="an-effect-without-donors"),
    pytest.param('{"version": 1, "effects": [{"id": "e1", "d": [3]}]}', id="donors-not-pairs"),
    pytest.param('{"version": 1, "effects": [{"id": 1, "d": []}]}', id="id-not-text"),
]


@pytest.mark.parametrize("text", MALFORMED_SHARED)
def test_a_malformed_shared_file_is_refused_by_name(results, built, text):
    files.write_release(results, ["pal-mnk-ber"], built)
    (results / "effects.json").write_text(text, encoding="utf-8")
    with pytest.raises(files.EffectsError, match="effects.json"):
        files.check_release(results, ["pal-mnk-ber"])


def broken(mutate):
    def make(doc):
        mutate(doc)
        return doc

    return make


MALFORMED_TRIO = [
    pytest.param(lambda doc: 3, id="a-number"),
    pytest.param(lambda doc: [], id="a-list"),
    pytest.param(lambda doc: {k: v for k, v in doc.items() if k != "roles"}, id="no-roles"),
    pytest.param(lambda doc: {**doc, "roles": []}, id="roles-a-list"),
    pytest.param(lambda doc: {**doc, "classes": 3}, id="classes-not-a-list"),
    pytest.param(lambda doc: {**doc, "classes": ["XXX", "YYY", "ZZZ"]}, id="classes-not-classes"),
    pytest.param(lambda doc: {**doc, "roles": {"tank": 3}}, id="a-role-not-an-object"),
    pytest.param(lambda doc: {**doc, "roles": {"tank": {"focus": []}}}, id="a-role-without-lists"),
    pytest.param(lambda doc: {**doc, "roles": {"tank": {**doc["roles"]["tank"], "plan": [3]}}}, id="a-plan-row-a-number"),
    pytest.param(lambda doc: {**doc, "roles": {"tank": {**doc["roles"]["tank"], "plan": [{"k": "focus"}]}}}, id="a-plan-row-without-keys"),
    pytest.param(lambda doc: {**doc, "roles": {"tank": {**doc["roles"]["tank"], "noroom": [{"k": "focus", "e": 4}]}}}, id="an-effect-not-text"),
    pytest.param(lambda doc: {**doc, "roles": {"tank": {**doc["roles"]["tank"], "focus": [{"e": "e000", "d": "x"}]}}}, id="a-row-without-other-donors"),
    pytest.param(lambda doc: {**doc, "roles": {"tank": {**doc["roles"]["tank"], "click": [{"e": "e000", "d": "x", "o": 4}]}}}, id="other-donors-not-a-list"),
]


@pytest.mark.parametrize("mutate", MALFORMED_TRIO)
def test_a_malformed_trio_file_is_refused_by_name(results, built, mutate):
    files.write_release(results, ["pal-mnk-ber"], built)
    path = results / "pal-mnk-ber" / "exalt.json"
    path.write_text(json.dumps(mutate(json.loads(path.read_text(encoding="utf-8")))), encoding="utf-8")
    with pytest.raises(files.EffectsError, match="pal-mnk-ber/exalt.json"):
        files.check_release(results, ["pal-mnk-ber"])


def test_an_item_worn_in_an_any_place_of_a_real_kit_hosts_by_its_own_catalog_slots(built, catalog):
    by_key = {item["key"]: item for item in catalog["items"]}
    hosted = 0
    for slug in ("pal-mnk-ber", "clr-shd-shm", "wiz-mag-enc", "brd-nec-dru"):
        classes = [c.upper() for c in slug.split("-")]
        kit = pseudo_kit(built, classes)
        any_items = {key: place for place, key in kit if place.startswith("ANY")}
        assert len(any_items) == 2
        doc = files.trio_document(built, slug, "OGR", 4, {role: kit for role in roles_for(classes)})
        for entry in doc["roles"].values():
            for row in entry["plan"]:
                if row["h"] in any_items:
                    assert row["p"] == any_items[row["h"]]
                    assert set(by_key[row["h"]]["slots"]) & set(by_key[row["d"]]["slots"])  # a like item by the catalog's slots, not by the Any place
                    hosted += 1
    assert hosted > 0  # an Any place does host


def test_the_check_refuses_a_shared_file_whose_donors_the_item_table_lacks(results, built):
    # data-2026-10-27: e183 listed AMMO-only mounts, the item table (wearables only) lacked them, and only the site's reader noticed
    files.write_release(results, ["pal-mnk-ber"], built)  # (a trio file beside the shared file)
    shared = files.shared_document(built)
    row = next(e for e in shared["effects"] if e["d"])
    keys = {key for e in shared["effects"] for key, _ in e["d"]}
    path = results / "effects.json"
    path.write_text(jsonio.render(shared, per_line=("effects",)), encoding="utf-8")
    hosts = {r["h"] for entry in json.loads((results / "pal-mnk-ber" / "exalt.json").read_text(encoding="utf-8"))["roles"].values() for r in entry["plan"]}
    assert files.check_release(results, ["pal-mnk-ber"], keys | hosts) == 1  # (an item table that has every donor passes)
    assert files.check_release(results, ["pal-mnk-ber"]) == 1  # (and with no item table there is nothing to hold the donors to)
    row["d"].append(["w60320", 3])
    path.write_text(jsonio.render(shared, per_line=("effects",)), encoding="utf-8")
    with pytest.raises(files.EffectsError, match=rf"effect {row['id']}.*w60320.*item table"):
        files.check_release(results, [], keys)  # (whether or not the release has trio files)
    with pytest.raises(files.EffectsError, match=r"w60320"):
        files.check_release(results, ["pal-mnk-ber"], keys | hosts)


def test_the_real_shared_file_has_an_f_on_every_focus_row_and_the_check_refuses_a_focus_row_without_one(results, built):
    shared = files.shared_document(built)
    focus_rows = [e for e in shared["effects"] if e["k"] == "focus"]
    assert focus_rows and all(isinstance(e.get("f"), dict) for e in focus_rows)
    path = results / "effects.json"
    del focus_rows[0]["f"]
    path.write_text(jsonio.render(shared, per_line=("effects",)), encoding="utf-8")
    with pytest.raises(files.EffectsError, match=rf"effect {focus_rows[0]['id']}.*focus.*\bf\b"):
        files.check_release(results, [])


def test_the_check_refuses_a_trio_row_whose_best_or_other_donor_or_plan_donor_the_item_table_lacks(results, built):
    # data-2026-10-27: 16 trio files named the AMMO mounts as donors; the check looked at hosts only.
    # check_release refuses a shared-file donor the table lacks before it reads a trio file, so the trio check is called on its own here: a donor the shared file lists and the table lacks.
    kit = pseudo_kit(built, ["PAL", "MNK", "BER"])
    doc = files.trio_document(built, "pal-mnk-ber", "OGR", 4, {"tank": kit})
    shared = files.shared_document(built)
    ids = {e["id"] for e in shared["effects"]}
    known = {key for e in shared["effects"] for key, _ in e["d"]}
    everything = set(built.items) | known
    name = "pal-mnk-ber/exalt.json"
    effect = shared["effects"][0]["id"]

    def check(document, wanted):
        files._check_trio(document, "pal-mnk-ber", name, shared, ids, known, wanted)

    entry = doc["roles"]["tank"]
    used = {r["d"] for part in files.LISTS for r in entry[part]} | {k for part in files.LISTS for r in entry[part] for k in r["o"]} | {r["d"] for r in entry["plan"]}
    spare = sorted(known - used)
    assert len(spare) >= 3 and entry["plan"]
    check(doc, everything)
    host, anchor = entry["plan"][0]["h"], min(used)
    for where, make in (
        ("best", lambda document, key: document["roles"]["tank"]["click"].append({"e": effect, "d": key, "o": [], "s": 1, "m": "PAL"})),
        ("other", lambda document, key: document["roles"]["tank"]["click"].append({"e": effect, "d": anchor, "o": [key], "s": 1, "m": "PAL"})),
        ("plan", lambda document, key: document["roles"]["tank"]["plan"].append({"k": "click", "e": effect, "d": key, "h": host, "p": "HEAD", "c": [], "u": 0})),
    ):
        key = spare[0]
        changed = json.loads(json.dumps(doc))
        make(changed, key)
        check(changed, everything)  # (with the donor in the table the row is fine)
        with pytest.raises(files.EffectsError, match=rf"{name}: donor {key} is not in the item table"):
            check(changed, everything - {key})
        spare.pop(0)  # (each case has a donor of its own, so that the message can come from that row alone)


def test_every_donor_of_the_real_shared_file_is_a_wearable_of_the_item_table(built, catalog):
    from trioforge.precompute import grid

    slots = {item["key"]: set(item["slots"]) for item in catalog["items"]}
    donors = {key for e in files.shared_document(built)["effects"] for key, _ in e["d"]}
    assert donors and all(grid.WEARABLE_SLOTS & slots[key] for key in donors)
    assert any(item["slots"] == ["AMMO"] and item["effects"] for item in catalog["items"])  # (the catalog has AMMO-only items with effects, none of them a donor)
