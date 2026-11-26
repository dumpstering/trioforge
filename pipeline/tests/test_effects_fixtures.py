"""The plan fixtures the browser's matcher is held to (effects/fixtures.py, fixtures/effects/plan-parity.json)."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from trioforge.effects import fixtures, judgment, layer, plan
from trioforge.effects import spells as sp

REPO = Path(__file__).resolve().parents[2]
COMMITTED = REPO / "fixtures" / "effects" / "plan-parity.json"


@pytest.fixture(scope="module")
def catalog():
    return json.loads((REPO / "derived" / "catalog.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def text(catalog):
    return fixtures.plan_fixture_text(catalog)


def test_the_committed_fixture_is_what_the_code_makes_and_is_the_same_every_time(catalog, text):
    assert COMMITTED.read_text(encoding="utf-8") == text
    assert fixtures.plan_fixture_text(catalog) == text  # (seeded: a second run is the same bytes)


def test_the_fixture_holds_what_the_browser_has_and_every_case_is_the_plan_python_makes(text):
    doc = json.loads(text)
    assert doc["version"] == fixtures.VERSION
    assert doc["constants"]["places"] == list(fixtures.PLACES) and len(fixtures.PLACES) == 22
    assert doc["constants"]["slot_tier"] == layer.SLOT_TIER and doc["constants"]["kinds"] == list(plan.KINDS) and doc["constants"]["reasons"] == list(plan.REASONS)
    assert len(doc["cases"]) >= 100 and len({case["lists"].split("/")[0] for case in doc["cases"]}) >= 20
    for case in doc["cases"]:
        assert len(case["kit"]) == 22
        assert set(case) == {"lists", "tier", "kit", "plan", "noroom"}
        assert {r["k"] for r in case["plan"]} <= set(plan.KINDS) and {r["w"] for r in case["noroom"]} <= set(plan.REASONS)
        for row in case["plan"]:
            assert row["h"] in case["kit"] and row["h"] in doc["items"] and row["d"] in doc["items"]
    assert {w for case in doc["cases"] for w in (r["w"] for r in case["noroom"])} == set(plan.REASONS) - {"donor"}  # ("donor": no copy a class can wear; the lists never offer such an effect)


def test_a_case_rebuilt_from_the_fixture_alone_gives_the_expected_rows(catalog):
    """The rows in the file are the ones plan_kit gives for the kit of the case with the real context (a check of the exporter, not only of the file)."""
    from trioforge.effects import files

    built = files.build(catalog, sp.SpellBook.load(), judgment.default(), "x")
    doc = fixtures.build_fixture(catalog, built)
    case = doc["cases"][7]
    list_ = doc["lists"][case["lists"]]
    options = layer.layer(list_["classes"], list_["role"], built.ctx)
    kit = [(place, key) for place, key in zip(fixtures.PLACES, case["kit"], strict=True) if key is not None]
    placed = plan.plan_kit(options, kit, built.items, built.ctx, list_["classes"], list_["role"], case["tier"])
    assert placed["rows"] == case["plan"] and placed["noroom"] == case["noroom"]


# ---- the fix round of part 2 ---------------------------------------------------------------------------------------------------------------------------


def test_the_site_fixture_is_not_written_into_the_canonical_fixture_results(capsys):
    canonical = REPO / "fixtures" / "site" / "results"
    before = sorted(p.name for p in canonical.rglob("*") if p.is_file())
    with pytest.raises(SystemExit):
        fixtures.main(["--site", str(canonical)])
    with pytest.raises(SystemExit):
        fixtures.main(["--site", str(canonical / ".." / "results")])
    assert "effects.json" not in before and sorted(p.name for p in canonical.rglob("*") if p.is_file()) == before


def test_the_check_compares_bytes_so_a_file_with_other_line_ends_is_not_up_to_date(tmp_path, catalog, text):
    out = tmp_path / "plan-parity.json"
    out.write_bytes(text.encode("utf-8"))
    assert fixtures.main(["--out", str(out), "--check"]) == 0
    out.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    assert fixtures.main(["--out", str(out), "--check"]) == 1


def test_the_rules_version_the_plans_are_built_with_is_a_label_and_changes_no_plan(catalog):
    """The fixtures are built with the label "fixture"; the rules version only goes into the documents (the constants of the judgment come from rules.json), so the plans are the same under any."""
    from trioforge.effects import files

    j = judgment.default()
    one = files.build(catalog, sp.SpellBook.load(), j, "fixture")
    other = files.build(catalog, sp.SpellBook.load(), j, "2026-10-13")
    kit = fixtures.random_kit(random.Random(3), one.items, ["PAL", "MNK", "BER"])
    kits = {role: kit for role in ("tank", "melee")}
    a = files.trio_document(one, "pal-mnk-ber", "OGR", 4, kits)
    b = files.trio_document(other, "pal-mnk-ber", "OGR", 4, kits)
    assert a["rules_version"] == "fixture" and b["rules_version"] == "2026-10-13"
    assert {k: v for k, v in a.items() if k != "rules_version"} == {k: v for k, v in b.items() if k != "rules_version"}
    assert files.shared_document(one)["effects"] == files.shared_document(other)["effects"]
    assert a["roles"]["tank"]["plan"]  # (and the plans are not empty ones)
