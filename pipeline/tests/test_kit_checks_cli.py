"""Tests for the command ``python -m trioforge.checks.kits``: what it prints, what it writes, and when it exits with which code.

The folders are written from invented items (``kits_fixture``): a dirty one, whose kits fail the two gate checks, and a clean one, whose kits do not.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from kits_fixture import base_items, make_results, row

from trioforge.checks import kits as kits_module
from trioforge.checks import named
from trioforge.model.roles import MELEE_CLASSES

PIPELINE = Path(__file__).resolve().parents[1]
CLEAN_KIT = {"CHEST": "Vlorn Tunic", "LEGS": "Vlorn Greaves", "ARMS": "Vlorn Sleeves", "HEAD": "Vlorn Helm", "HANDS": "Vlorn Gloves", "FEET": "Vlorn Boots", "WAIST": "Brawn Belt"}


def dirty_rows():
    return [
        row("balanced", 4, {"FACE": "Glimmer Idol"}),
        row("tank", 0, {"FACE": "Glimmer Idol", "CHEST": "Ombrel Vestment"}, totals={"ac": 390, "fire": 10, "cold": 10, "magic": 10, "poison": 10, "disease": 10}),
        row("tank", 4, {"CHEST": "Ombrel Vestment", "WAIST": "Brawn Belt"}, totals={"ac": 420}, value=None),  # a named case: its value is the evaluator's
        row("tank", 5, CLEAN_KIT, totals={"ac": 420}),
        row("tank", 10, CLEAN_KIT, totals={"ac": 500}, value=None),
        row("melee", 4, {"NECK": "Tidepool Sigil", "WAIST": "Brawn Belt"}),
        row("caster", 4, {"FACE": "Glimmer Idol"}),
    ]


@pytest.fixture
def dirty(tmp_path):
    return make_results(tmp_path / "dirty", base_items(10), {"pal-mnk-enc": dirty_rows(), "war-clr-pal": [row("tank", 4, CLEAN_KIT, totals={"ac": 400})]})


@pytest.fixture
def clean(tmp_path):
    return make_results(tmp_path / "clean", base_items(10), {"pal-mnk-enc": [row("tank", 4, CLEAN_KIT, totals={"ac": 410}, value=None), row("melee", 4, {"WAIST": "Brawn Belt"})]})


def run(capsys, *args):
    code = kits_module.main([str(arg) for arg in args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_it_prints_the_scoreboard_and_exits_0_without_the_gate_flag(dirty, capsys):
    code, out, err = run(capsys, "--results", dirty)
    assert code == 0 and err == ""
    assert out.startswith("TrioForge kit checks: 8 kits of 2 trios")
    for line in ("K1.attr  WIS and INT among the attributes of a non-casting build", "K1.pool  Mana-pool points on a non-casting build", "K2  Pure caster item in a tank, melee or archer kit   [gate]",
                 "K3  Armour for a tank", "K3.robe  A robe as a tank chest   [gate]", "K3.robe_worn  A robe worn anywhere by a tank", "K4  One family everywhere",
                 "K5.bow  A bow in the Range slot", "K6  Strength for melee", "K7  Resists", "K8  Soft cap", "K11  Stamina parked under the knee", "K12  A shield in the tank build", "K9  Named cases", "K10  Exchange rates"):
        assert line in out, line
    assert "Gates (with --gate): K2 FAIL (2 kits); K3.robe FAIL (2 kits)" in out


def test_the_checks_that_are_for_the_scoreboard_only_say_so_in_their_heading(dirty, capsys):
    _, out, _ = run(capsys, "--results", dirty, "--no-named")
    headings = {line.split("  ")[0]: line for line in out.splitlines() if re.match(r"^K\d+(\.\w+)?  ", line)}
    assert {k for k, line in headings.items() if "[scoreboard only]" in line} == {"K1.attr", "K1.pool", "K3.robe_worn", "K4", "K6", "K7", "K8", "K11", "K12"}
    assert {k for k, line in headings.items() if "[gate]" in line} == {"K2", "K3.robe"}


def test_the_scoreboard_says_the_same_to_the_byte_on_a_second_run_and_names_no_path(dirty, capsys):
    first = run(capsys, "--results", dirty)
    second = run(capsys, "--results", dirty)
    assert first == second
    assert str(dirty) not in first[1] and str(dirty.parent) not in first[1]


def test_the_output_does_not_depend_on_the_order_of_a_set_or_a_dictionary(dirty):
    """Python orders the strings of a set by a hash that changes with every run; a tie of pieces, items or trios must be broken by name, not by that order."""
    outputs = []
    for seed in ("1", "2", "3"):
        done = subprocess.run(
            [sys.executable, "-m", "trioforge.checks.kits", "--results", str(dirty)],
            capture_output=True, text=True, timeout=300, check=False, env={**os.environ, "PYTHONPATH": str(PIPELINE), "PYTHONHASHSEED": seed},
        )  # fmt: skip
        assert done.returncode == 0, done.stderr
        outputs.append(done.stdout)
    assert outputs[0] == outputs[1] == outputs[2]
    assert "pieces: Vlorn Boots, Vlorn Gloves, Vlorn Greaves, Vlorn Helm" in outputs[0]  # six pieces at three kits each: the first four by name


def test_a_row_for_each_role_and_tier_shows_pass_fail_and_na(dirty, capsys):
    _, out, _ = run(capsys, "--results", dirty, "--no-named")
    k8 = out[out.index("K8  Soft cap") : out.index("K11  Stamina")]
    lines = [line.split() for line in k8.splitlines() if line.startswith("    tank")]
    # +0: one kit (390, short of 400); +4: two (420 and 400 reach it); +10: one; the +5 kit is "other"
    assert [line[:6] for line in lines] == [["tank", "+0", "1", "0", "1", "0"], ["tank", "+4", "2", "2", "0", "0"], ["tank", "+10", "1", "1", "0", "0"], ["tank", "other", "1", "1", "0", "0"]]
    assert "worst trios: pal-mnk-enc tank +0 -10" in k8


def test_the_tiers_that_not_every_trio_has_are_shown_as_one_row_other(dirty, capsys):
    _, out, _ = run(capsys, "--results", dirty, "--no-named")
    assert re.search(r"^    tank     other\s+1\s", out, re.MULTILINE)  # the +5 kit
    assert not re.search(r"^    \w+\s+\+5\s", out, re.MULTILINE)


def test_a_check_that_applies_to_no_kit_says_so(dirty, capsys):
    _, out, _ = run(capsys, "--results", dirty, "--no-named")
    k5 = out[out.index("K5.bow  A bow") : out.index("K5.windstriker")]
    assert "(applies to no kit of this folder)" in k5  # neither trio has a Ranger


def test_gate_fails_with_exit_1_and_says_which_check(dirty, capsys):
    code, out, err = run(capsys, "--results", dirty, "--gate")
    assert code == 1 and "gate fails for K2, K3.robe" in err
    assert "Gates (with --gate)" in out


def test_gate_passes_with_exit_0_when_the_kits_are_clean(clean, capsys):
    code, out, err = run(capsys, "--results", clean, "--gate")
    assert code == 0 and err == ""
    assert "Gates (with --gate): K2 pass (0 kits); K3.robe pass (0 kits)" in out


def test_json_is_written_whole_and_is_the_same_for_the_same_folder(dirty, tmp_path, capsys):
    one, two = tmp_path / "one.json", tmp_path / "two.json"
    run(capsys, "--results", dirty, "--json", one)
    run(capsys, "--results", dirty, "--json", two)
    assert one.read_bytes() == two.read_bytes()
    document = json.loads(one.read_text(encoding="utf-8"))
    assert document["kits"] == 8 and document["gates"] == {"K2": 2, "K3.robe": 2}
    assert set(document["checks"]) == {check.id for check in kits_module.CHECKS}
    assert document["checks"]["K8"]["by_role"]["tank"]["tiers"]["4"]["pass"] == 2
    assert document["checks"]["K2"]["worst"][0]["trio"] == "pal-mnk-enc"
    assert [c["case"] for c in document["K9"]] == ["PAL/MNK/ENC tank"] * 2 and "expected" not in document
    assert str(dirty) not in one.read_text(encoding="utf-8")


def test_the_named_cases_print_the_kit_place_by_place_with_the_checks(dirty, capsys):
    _, out, _ = run(capsys, "--results", dirty)
    assert re.search(r"== PAL/MNK/ENC tank  tank  \+4   \(race HUM, setup 2h, value \d+\.\d+\)", out)
    block = out[out.index("== PAL/MNK/ENC tank  tank  +4") :]
    assert "   CHEST     Ombrel Vestment" in block and "   WAIST     Brawn Belt" in block
    assert "   K3.robe        fail: Ombrel Vestment" in block and "   K8             pass 20  (sheet AC 420, soft cap 400)" in block
    assert re.search(r"   K10            \+1 of STA \d+\.\d+", block) and "STR" in block and "HASTE" in block  # the exchange rates of the kit
    assert out.count("== ") == 2  # the other named trios are not in the folder, and the +10 kit of this one is not either: +4 and +10 only


def test_the_named_cases_are_those_of_the_brief():
    labels = [label for label, _, _ in named.CASES]
    assert labels[:4] == ["SHD/WIZ/ENC", "WAR/SHM/ENC", "PAL/MNK/ENC tank", "RNG/SHM/CLR"]
    assert named.TIERS == (4, 10)
    assert dict((label, roles) for label, _, roles in named.CASES)["PAL/MNK/ENC tank"] == ("tank",)
    trio = next(trio for label, trio, _ in named.CASES if label.startswith("a Ranger and two melee"))
    assert "RNG" in trio and sum(code in MELEE_CLASSES for code in trio) == 3


def test_no_named_leaves_k9_out(dirty, capsys):
    _, out, _ = run(capsys, "--results", dirty, "--no-named", "--json", dirty.parent / "x.json")
    assert "K9" not in out and "K9" not in json.loads((dirty.parent / "x.json").read_text(encoding="utf-8"))


def test_expected_adds_its_report_to_the_text_and_the_json(dirty, tmp_path, capsys):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([{"trio": ["PAL", "MNK", "ENC"], "role": "tank", "slot": "CHEST", "any_of": ["Vlorn Tunic"], "note": "x"}]), encoding="utf-8")
    code, out, _ = run(capsys, "--results", dirty, "--expected", cases, "--json", tmp_path / "e.json")
    assert code == 0 and "Expected cases" in out and "[disagree]" in out and "agreement 0.0%" in out
    document = json.loads((tmp_path / "e.json").read_text(encoding="utf-8"))
    assert document["expected"]["disagree"] == 1 and document["expected"]["cases"][0]["roles"]["tank"]["worn"] == ["Ombrel Vestment"]


@pytest.mark.parametrize("which", ["folder", "expected", "items", "json"])
def test_an_input_that_cannot_be_read_exits_2_with_one_line_on_stderr(dirty, tmp_path, capsys, which):
    args = ["--results", dirty]
    if which == "folder":
        args = ["--results", tmp_path / "nowhere"]
    elif which == "expected":
        args += ["--expected", tmp_path / "absent.json"]
    elif which == "items":
        (dirty / "items.json").write_text("{", encoding="utf-8")
    else:
        args += ["--json", tmp_path / "no-such-folder" / "out.json"]
    code, out, err = run(capsys, *args)
    assert code == 2 and out == "" and err.startswith("kit checks: ") and err.count("\n") == 1


def test_a_gate_check_that_does_not_apply_does_not_fail(tmp_path, capsys):
    root = make_results(tmp_path / "only-caster", base_items(10), {"pal-mnk-enc": [row("caster", 4, {"FACE": "Glimmer Idol"}), row("balanced", 4, {"FACE": "Glimmer Idol"})]})
    code, out, _ = run(capsys, "--results", root, "--gate")
    assert code == 0 and "K2 pass (0 kits)" in out


def test_the_module_runs_from_the_command_line(dirty):
    done = subprocess.run(
        [sys.executable, "-m", "trioforge.checks.kits", "--results", str(dirty), "--no-named", "--gate"],
        capture_output=True, text=True, timeout=300, check=False, env={**os.environ, "PYTHONPATH": str(PIPELINE)},
    )  # fmt: skip
    assert done.returncode == 1 and done.stdout.startswith("TrioForge kit checks: 8 kits") and "gate fails for K2, K3.robe" in done.stderr
    helped = subprocess.run([sys.executable, "-m", "trioforge.checks.kits", "--help"], capture_output=True, text=True, timeout=120, check=False, env={**os.environ, "PYTHONPATH": str(PIPELINE)})
    assert helped.returncode == 0 and "--results" in helped.stdout and "--gate" in helped.stdout and "--expected" in helped.stdout and "--json" in helped.stdout


# ---- what makes a gate unsafe: results that were not read in full, or were made with other rules --------------------------------------


def one_clean_trio(tmp_path, name="one", **kwargs):
    return make_results(tmp_path / name, base_items(10), {"pal-mnk-enc": [row("tank", 4, CLEAN_KIT, totals={"ac": 410}, value=None)]}, **kwargs)


def test_the_gate_refuses_results_that_yield_no_kit_and_a_run_without_the_gate_warns(tmp_path, capsys):
    root = make_results(tmp_path / "nokits", base_items(10), {"pal-mnk-enc": [row("tank", 4, CLEAN_KIT, race="OGR")]})  # the default race is HUM: no scenario of it
    code, out, err = run(capsys, "--results", root, "--gate", "--no-named")
    assert code == 2 and err.startswith("kit checks: the gate is refused") and "no kit was read" in err and err.count("\n") == 1
    code, out, err = run(capsys, "--results", root, "--no-named")
    assert code == 0 and err == "" and "warning: no kit was read" in out


def test_the_gate_refuses_results_with_a_trio_that_yields_no_kit(tmp_path, capsys):
    root = make_results(
        tmp_path / "onegone", base_items(10), {"pal-mnk-enc": [row("tank", 4, CLEAN_KIT, totals={"ac": 410})], "war-clr-pal": [row("tank", 4, CLEAN_KIT, race="OGR")]}
    )
    code, out, err = run(capsys, "--results", root, "--gate", "--no-named")
    assert code == 2 and "1 of 2 trios yielded no kit" in err and "war-clr-pal" in err
    code, out, err = run(capsys, "--results", root, "--no-named")
    assert code == 0 and "warning: 1 of 2 trios yielded no kit (war-clr-pal)" in out
    assert out.startswith("TrioForge kit checks: 1 kits of 1 trios (of 2 in the folder)")


def test_the_gate_refuses_results_made_with_other_rules_and_a_run_without_the_gate_warns(tmp_path, capsys):
    root = one_clean_trio(tmp_path, rules_version="1999-01-01")
    code, out, err = run(capsys, "--results", root, "--gate", "--no-named")
    assert code == 2 and "rules" in err and "1999-01-01" in err
    code, out, err = run(capsys, "--results", root, "--no-named", "--json", tmp_path / "w.json")
    assert code == 0 and "warning: the results were made with the rules of 1999-01-01" in out
    assert json.loads((tmp_path / "w.json").read_text(encoding="utf-8"))["warnings"] == [line[len("warning: ") :] for line in out.splitlines() if line.startswith("warning: ")]


def test_results_with_nothing_wrong_have_no_warning_and_the_gate_passes(tmp_path, capsys):
    root = one_clean_trio(tmp_path)
    code, out, err = run(capsys, "--results", root, "--gate", "--no-named", "--json", tmp_path / "ok.json")
    assert code == 0 and err == "" and "warning:" not in out
    assert json.loads((tmp_path / "ok.json").read_text(encoding="utf-8"))["warnings"] == []


@pytest.mark.parametrize("gate", [[], ["--gate"]])
def test_a_shard_without_a_total_the_checks_read_is_an_error_with_exit_2(tmp_path, capsys, gate):
    root = one_clean_trio(tmp_path)
    path = root / "pal-mnk-enc" / "wiki-own.json"
    shard = json.loads(path.read_text(encoding="utf-8"))
    at = shard["totals_keys"].index("fire")
    shard["totals_keys"].pop(at)
    shard["totals"] = [[v for n, v in enumerate(vector) if n != at] for vector in shard["totals"]]
    path.write_text(json.dumps(shard), encoding="utf-8")
    code, out, err = run(capsys, "--results", root, "--no-named", *gate)
    assert code == 2 and out == "" and err.startswith("kit checks: ") and "fire" in err and "Traceback" not in err


@pytest.mark.parametrize("gate", [[], ["--gate"]])
def test_a_race_the_tables_do_not_know_is_an_error_with_exit_2(tmp_path, capsys, gate):
    root = make_results(tmp_path / "zzz", base_items(10), {"pal-mnk-enc": [row("melee", 4, CLEAN_KIT, race="ZZZ")]}, race="ZZZ")
    code, out, err = run(capsys, "--results", root, "--no-named", *gate)
    assert code == 2 and out == "" and "ZZZ" in err and err.startswith("kit checks: ")


def test_a_closed_pipe_does_not_hide_a_failed_gate(dirty, clean, monkeypatch):
    class Closed:
        def write(self, text):
            raise BrokenPipeError

        def flush(self):
            raise BrokenPipeError

    monkeypatch.setattr(sys, "stdout", Closed())
    assert kits_module.main(["--results", str(dirty), "--no-named", "--gate"]) == 1  # the gate fails: not 0
    assert kits_module.main(["--results", str(clean), "--no-named", "--gate"]) == 0
    assert kits_module.main(["--results", str(dirty), "--no-named"]) == 0  # no gate was asked for


def test_a_named_kit_whose_value_the_evaluator_does_not_give_stops_the_run(tmp_path, capsys):
    root = make_results(tmp_path / "stale", base_items(10), {"pal-mnk-enc": [row("tank", 4, CLEAN_KIT, totals={"ac": 410}, value=1000.0)]})
    code, out, err = run(capsys, "--results", root)
    assert code == 2 and out == "" and "evaluator" in err and "pal-mnk-enc" in err
    assert run(capsys, "--results", root, "--no-named")[0] == 0  # without the named cases K10 is not asked for


def test_the_exchange_rates_of_the_named_cases_are_printed_and_in_the_json(clean, tmp_path, capsys):
    code, out, _ = run(capsys, "--results", clean, "--json", tmp_path / "k10.json")
    assert code == 0
    assert "K10  Exchange rates   [scoreboard only]" in out
    document = json.loads((tmp_path / "k10.json").read_text(encoding="utf-8"))
    (case,) = document["K9"]
    assert case["case"] == "PAL/MNK/ENC tank" and case["tier"] == 4
    rates = case["K10"]["rates"]
    assert list(rates) == ["STA", "STR", "AGI", "DEX", "WIS", "INT", "CHA", "AC", "HP", "MANA", "FIRE", "COLD", "MAGIC", "POISON", "DISEASE", "HASTE", "ATK"]
    assert rates["STA"] > 0 and case["K10"]["vs_sta"]["STA"] == 1.0 and abs(case["K10"]["value"] - case["value"]) < 0.006
