"""The default race: the one rule, the close list it gives, what a run writes of it and what the site's reader accepts.

The rule (``defaults.race_close_pct``, a judgment) as the code applies it, and as its note says: the default is always a race that can be created when there is one;
the window of the close percent is measured from the best race that can be created; ``close_races`` lists races that can be created and no other, in descending value
(a tie by the display order of the races), the default first, and is empty when the best creatable race stands alone or its value is not above 0.

Every item is invented (``test_precompute.make_item``); the races and classes are public game terms.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from test_precompute import CATALOG, small_world, write_catalog

from trioforge import precompute as pc
from trioforge.precompute import shards
from trioforge.site import data

REPO = Path(__file__).resolve().parents[2]
HAND_WRITTEN = REPO / "fixtures" / "site" / "results"
SLUG = "pal-mnk-ber"
ORDER = ["HUM", "BAR", "ERU", "ELF", "DEF"]  # the display order of the races of these cases


def default(values, legal, order=ORDER, close_pct=1):
    return shards.default_race(values, set(legal), order, close_pct)


def test_values_given_in_another_order_than_the_races_decide_a_tie_by_the_display_order():
    values = {"ERU": 1000.0, "DEF": 999.0, "BAR": 1000.0, "HUM": 989.0}  # (a dictionary in no order of the races; BAR and ERU tie, and HUM is just outside the window)
    choice = default(values, ["HUM", "BAR", "ERU", "DEF"])
    assert choice["race"] == "BAR" and choice["runner_up"] == "ERU" and choice["margin"] == 0
    assert choice["close"] == ["BAR", "ERU", "DEF"]  # in descending value, the tie in the display order (BAR before ERU), the default first
    assert default(dict(reversed(list(values.items()))), ["DEF", "ERU", "BAR", "HUM"]) == choice  # (the order of the arguments does not matter)


def test_the_edge_of_the_window_is_in_and_a_value_below_it_is_out():
    assert default({"HUM": 1000.0, "BAR": 990.0}, ["HUM", "BAR"])["close"] == ["HUM", "BAR"]  # exactly 1 percent under the best: close
    assert default({"HUM": 1000.0, "BAR": 989.99}, ["HUM", "BAR"])["close"] == []  # a hair more: the best stands alone
    assert default({"HUM": 1000.0, "BAR": 989.99}, ["HUM", "BAR"], close_pct=2)["close"] == ["HUM", "BAR"]  # (the window is the rule's)


def test_a_best_race_that_cannot_be_created_is_never_the_default_and_the_window_is_measured_from_the_best_that_can():
    values = {"HUM": 5000.0, "BAR": 400.0, "ERU": 398.0, "ELF": 397.0, "DEF": 300.0}
    choice = default(values, ["BAR", "ERU", "ELF", "DEF"])  # HUM, the best by far, cannot be created
    assert choice["race"] == "BAR" and choice["runner_up"] == "ERU"
    assert choice["margin"] == 2.0  # (against the runner-up that can be created, not against the race that cannot)
    assert choice["close"] == ["BAR", "ERU", "ELF"]  # within 1 percent of 400 (396): the races that can be created only, HUM is never named
    assert "HUM" not in choice["close"]
    far = default({"HUM": 10000.0, "BAR": 100.0}, ["BAR"])  # a creatable race far below the best one, and alone
    assert far == {"race": "BAR", "runner_up": None, "margin": None, "close": []}


def test_a_race_that_cannot_be_created_is_not_close_even_when_its_value_is_the_best():
    choice = default({"HUM": 1000.0, "BAR": 1000.0, "ERU": 999.5}, ["BAR", "ERU"])
    assert choice["race"] == "BAR" and choice["close"] == ["BAR", "ERU"]


@pytest.mark.parametrize("best", [0, 0.0, -5.0])
def test_a_best_value_that_is_not_above_zero_has_no_close_list(best):
    choice = default({"HUM": best, "BAR": best}, ["HUM", "BAR"])
    assert choice["race"] == "HUM" and choice["close"] == []
    assert shards.close_races(["HUM", "BAR"], {"HUM": best, "BAR": best}, 1) == []


def test_no_race_that_can_be_created_gives_no_default():
    assert default({"HUM": 1.0, "BAR": 2.0}, []) is None
    assert default({}, ["HUM"]) is None


def test_the_docstring_and_the_note_of_the_rule_say_what_the_code_does():
    rules = json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))
    (rule,) = [r for r in rules["rules"] if r["id"] == "defaults.race_close_pct"]
    note = rule["notes"].lower()
    assert "can be created" in note and "measured from" in note and "judgment" in note
    doc = shards.default_race.__doc__
    assert "give the same race" not in doc  # (false when the best race overall cannot be created)
    assert "measured from the best race that can be created" in " ".join(doc.split())


# ---- a run writes close_races from the rule ------------------------------------------------------------------------------------------


def run_with_close_pct(tmp_path, close_pct):
    root = tmp_path / "root"
    root.mkdir(parents=True)
    world = small_world(root / "world")
    path = world / "rules" / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    (rule,) = [r for r in rules["rules"] if r["id"] == "defaults.race_close_pct"]
    rule["value"] = close_pct
    path.write_text(json.dumps(rules), encoding="utf-8")
    catalog = write_catalog(root / "catalog.json", CATALOG)
    out = tmp_path / "results"
    pc.run(SLUG, out, catalog=catalog, tables_root=world, processes=1, races=("OGR", "TRL"), roles=("tank",), tiers=(0, 4), robustness=False)
    return json.loads((out / SLUG / "defaults.json").read_text(encoding="utf-8"))


def test_a_run_writes_the_close_races_of_the_rule(tmp_path):
    everything = run_with_close_pct(tmp_path / "wide", 100)  # a window of the whole value: both races that can be created are close
    assert everything["close_races"] == [everything["race"], everything["runner_up_race"]]
    nothing = run_with_close_pct(tmp_path / "narrow", 0)  # no window: only an exact tie is close, and these two do not tie
    assert nothing["close_races"] == [] and nothing["race"] == everything["race"]


# ---- the site's reader ------------------------------------------------------------------------------------------------------------------


def with_close_races(tmp_path, close, **changes):
    folder = tmp_path / "results" / SLUG
    shutil.copytree(HAND_WRITTEN / SLUG, folder)
    path = folder / "defaults.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["close_races"] = close
    document.update(changes)
    path.write_text(json.dumps(document), encoding="utf-8")
    return folder


def test_the_reader_takes_a_close_list_of_races_that_can_be_created_with_the_default_first(tmp_path):
    results = data.load_trio(with_close_races(tmp_path, ["OGR", "TRL"]))
    assert results.defaults.close_races == ("OGR", "TRL") and results.defaults.race == "OGR"
    assert data.load_trio(with_close_races(tmp_path / "none", [])).defaults.close_races == ()


@pytest.mark.parametrize(
    ("close", "why"),
    [
        (["OGR", "TRL", "TRL"], "a race twice"),
        (["TRL", "OGR"], "the default race not first"),
        (["OGR"], "one race alone"),
        (["OGR", "ELF"], "a race that cannot be created"),
        (["OGR", "HUM"], "a race that is not in the results"),
    ],
)
def test_the_reader_refuses_a_close_list_that_is_not_one_the_run_could_have_written(tmp_path, close, why):
    with pytest.raises(data.ResultsError, match=r"defaults\.json: close_races"):
        data.load_trio(with_close_races(tmp_path, close))


def test_the_reader_refuses_a_default_race_that_cannot_be_created(tmp_path):
    folder = with_close_races(tmp_path, [], race="ELF", runner_up_race="OGR")  # the race with the best value of the fixture, which cannot be created
    with pytest.raises(data.ResultsError, match=r"defaults\.json: race: .*cannot be created"):
        data.load_trio(folder)


def test_the_close_percent_of_the_default_race_has_no_default_wherever_the_race_is_picked():
    import inspect

    from trioforge.precompute import seals, shards

    for function in (shards.default_race, shards.defaults_doc, seals.flip_notes):
        assert inspect.signature(function).parameters["close_pct"].default is inspect.Parameter.empty, function.__name__  # (the caller passes the rule: no copy of its value lives here)
