"""A row of "Wear this" shows the worn haste of its item without opening Stats (a chip, "Haste 19%"), and the totals say that only the highest worn haste counts.

The chip is the item's HASTE at the tier shown, the figure the Stats panel of the row says as ``Haste +19%``: both come from the model's ``at_tier``. An item with no haste has no chip.
The browser code draws the chip of a row it paints from the same words (``tests-js/kit-haste.test.mjs``).
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from site_helpers import parse
from test_site_content import render_trio

from trioforge import rules as rules_module
from trioforge.export import browser
from trioforge.model.items import at_tier
from trioforge.model.tables import REPO
from trioforge.site import build, content, data, view

RESULTS = REPO / "fixtures" / "site" / "results"
RULES = REPO / "rules" / "rules.json"
HOOP = "w90008"  # Gold Hoop of Haste: 15 worn haste at +0, one more for each tier
HASTE_SLOT = 3  # the second ear, where the fixture's melee views wear it


class World:
    pass


@pytest.fixture(scope="module")
def world():
    w = World()
    w.results = data.load_trio(RESULTS / "pal-mnk-ber")
    w.table = json.loads((RESULTS / "items.json").read_text(encoding="utf-8"))
    w.records = {browser.record_key(r): r for r in w.table["items"]}
    w.rules = rules_module.load(RULES)
    w.vecs = view.tier_vecs(w.records, w.table["defaults"], w.rules)
    w.book = content.load_rulebook(RULES)
    w.pages = frozenset(build.item_page_keys(w.table))
    return w


def model_haste(world, key, tier):
    return at_tier(browser.item_to_catalog(world.records[key], world.table["defaults"]), tier, world.rules).haste


def page_of(world, results):
    caps = view.trio_caps(results.meta.trio, results.meta.level, world.rules)
    return view.trio_page(results, world.book, caps, world.pages, world.vecs)


def results_wearing_the_hoop(world):
    """The fixture with the Gold Hoop of Haste in the second ear of the default kit (the default view wears no haste item)."""
    results = world.results
    default = results.defaults
    shard = results.shards[(default.evidence, default.buffs)]
    melee = shard.scenario("OGR", "melee", default.tier, "dw")
    hoop = melee.kit[HASTE_SLOT]
    assert hoop is not None and hoop.key == HOOP
    scenarios = []
    for scenario in shard.scenarios:
        if (scenario.race, scenario.role, scenario.tier, scenario.setup) == (default.race, default.role, default.tier, default.setup):
            kit = list(scenario.kit)
            kit[HASTE_SLOT] = hoop
            scenario = dataclasses.replace(scenario, kit=tuple(kit))
        scenarios.append(scenario)
    return dataclasses.replace(results, shards={**results.shards, (default.evidence, default.buffs): dataclasses.replace(shard, scenarios=tuple(scenarios))})


# ---- the words of the chip --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("tier", [0, 1, 4, 7, 10])
def test_the_chip_is_the_haste_of_the_item_at_the_tier_the_model_gives_it(world, tier):
    want = model_haste(world, HOOP, tier)
    assert want == 15 + tier
    vec = world.vecs(HOOP, tier)
    assert view.haste_chip(vec) == f"Haste {want}%"
    assert f"Haste +{want}%" in view.item_stat_text(vec).split(", ")  # the Stats panel says the same figure, with its sign


def test_an_item_with_no_haste_has_no_chip(world):
    for key in ("w90001", "w90007", "w90009"):
        assert view.haste_chip(world.vecs(key, 4)) == ""


def test_a_piece_that_slows_has_no_chip_and_is_not_worn_haste():
    from types import SimpleNamespace

    assert view.haste_chip(SimpleNamespace(haste=-3)) == "" and view.haste_chip(SimpleNamespace(haste=0)) == ""


# ---- the static row ---------------------------------------------------------------------------------------------------------------


def test_a_row_whose_item_has_haste_carries_the_chip_and_the_others_do_not(world):
    page = page_of(world, results_wearing_the_hoop(world))
    assert [row.haste for row in page.rows] == ["" if index != HASTE_SLOT else "Haste 19%" for index in range(22)]
    assert page.rows[HASTE_SLOT].name == "Gold Hoop of Haste"


def test_the_default_view_of_the_fixture_wears_no_haste_and_no_row_has_a_chip(world):
    assert [row.haste for row in page_of(world, world.results).rows] == [""] * 22


def kit_cells(html):
    return [tr.find_all("td")[0] for tr in parse(html).by_id("kit-body").find_all("tr")]


def test_the_chip_is_in_the_name_cell_before_the_stats_toggle_and_only_in_a_row_that_has_haste(world):
    page = page_of(world, results_wearing_the_hoop(world))
    html = render_trio(page, world.book)
    cells = kit_cells(html)
    chip = cells[HASTE_SLOT].find("span", cls="kit-haste")
    assert chip.text() == "Haste 19%" and not chip.has("hidden") and "data-f" not in chip.attrs
    order = [n.tag + ("." + n.get("class") if n.get("class") else "") for n in cells[HASTE_SLOT].children if not isinstance(n, str)]
    assert order == ["span.name", "span.deity", "span.kit-haste", "details.kit-more"]
    for index, cell in enumerate(cells):
        if index != HASTE_SLOT:
            assert not cell.find_all("span", cls="kit-haste"), index  # (a row with no worn haste is made with no chip: the page code gives it one if a view has some)


def test_a_page_given_no_stats_has_no_chip_to_fill(world):
    page = view.trio_page(world.results, world.book, view.trio_caps(world.results.meta.trio, world.results.meta.level, world.rules), world.pages)
    html = render_trio(page, world.book)
    assert "kit-haste" not in html


def test_the_page_has_as_many_chips_as_rows_with_worn_haste_and_the_default_view_of_the_fixture_has_none(world):
    assert render_trio(page_of(world, world.results), world.book).count('class="kit-haste"') == 0
    assert render_trio(page_of(world, results_wearing_the_hoop(world)), world.book).count('class="kit-haste"') == 1


# ---- the note ---------------------------------------------------------------------------------------------------------------------


def test_the_haste_row_of_the_totals_says_that_only_the_highest_worn_haste_counts(world):
    page = page_of(world, world.results)
    html = render_trio(page, world.book)
    rows = parse(html).by_id("totals-body").find_all("tr")
    haste = next(r for r in rows if r.find("th").text() == "Haste")
    assert haste.find("span", cls="row-note").text() == "Only the highest worn haste counts."
    assert html.count("Only the highest worn haste counts.") == 1
    assert [r.find("th").text() for r in rows if r.find_all("span", cls="row-note")] == ["Haste"]


def test_the_note_is_what_the_model_does_with_worn_haste():
    """The model counts the best worn haste and never the sum of several (``formulas.evaluate``: ``best_haste = max(best_haste, entry.haste)``, ``worn_counted = min(best_haste, max(0, cap - spell))``),
    which ``test_formulas.py::test_only_the_best_worn_haste_counts_up_to_the_cap_minus_the_spell`` pins (two items of 20 and 30 count 30), and the browser's evaluator (``evaluate.js``) is held to by parity."""
    assert view.HASTE_NOTE == "Only the highest worn haste counts."
    source = (REPO / "pipeline" / "trioforge" / "model" / "formulas.py").read_text(encoding="utf-8")
    assert "best_haste = max(best_haste, entry.haste)" in source
    assert "worn_counted = min(best_haste, max(_ZERO, p.haste_cap - spell))" in source


# ---- the step of a tier, for the chips of the rows an answer of the optimizer fills --------------------------------------------------


def test_the_page_carries_the_step_of_worn_haste_a_tier_from_the_rule_and_it_is_the_bundles(world):
    """The rows an answer of the optimizer fills have no stats text: the page code makes the chip from the record's haste and this step (``data-haste-tier`` of the main element,
    ``trio.js``), by the one function ``atTier`` calls too (tests-js/kit-haste-answer.test.mjs)."""
    caps = view.trio_caps(world.results.meta.trio, world.results.meta.level, world.rules)
    page = view.trio_page(world.results, world.book, caps, world.pages, world.vecs)
    bundle = json.loads((RESULTS / "pal-mnk-ber" / "engine-l50.json").read_text(encoding="utf-8"))
    top, _, bottom = str(bundle["tier_rules"]["haste_per_tier"]).partition("/")
    assert page.haste_per_tier == caps.haste_per_tier == int(top) // int(bottom or 1) == int(world.rules.get("haste.worn_per_tier"))
    assert f'data-haste-tier="{page.haste_per_tier}"' in render_trio(page, world.book)
