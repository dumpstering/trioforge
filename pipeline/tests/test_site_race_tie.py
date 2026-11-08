"""Races within the tie band of the best are said to be tied with it, and the page says which racials are not scored.

``view.tied_races`` is the rule (legal races other than the best whose F is within ``TIE_BAND`` of the best's), and the trio page words it:
"Best race for this trio: Ogre, tied with Human and Troll (within 0.5%), judged in ...", with no margin. A trio with no tie reads as it always did.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from site_helpers import parse
from test_site_content import render_trio

from trioforge import rules as rules_module
from trioforge.site import content, data, view

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "fixtures" / "site" / "results" / "pal-mnk-ber"

#: the line of the fixture's best race as the page wrote it before the tie band existed (the fixture has no tie): it must stay byte for byte
UNTIED_LINE = (
    '<p id="best-race" class="best-race"><span class="art art-race-ogre" aria-hidden="true"></span>Best race for this trio: <strong>Ogre</strong> '
    '<span class="margin" data-rules="roles.balanced roles.templates">(+813 over Troll)</span>, judged in the <span id="best-race-view">Balanced view at '
    '<span data-rules="tier.stat_rule">+4</span> with your own buffs</span>.</p>'
)


# ---- the rule ---------------------------------------------------------------------------------------------------------------------


def rows(*pairs):
    """(code, legal, F) rows as ``tied_races`` reads them."""
    return [(code, legal, f) for code, legal, f in pairs]


def test_the_band_is_half_a_percent():
    assert view.TIE_BAND == 0.005


def test_no_race_is_tied_when_the_next_one_is_clearly_behind():
    assert view.tied_races(rows(("OGR", True, 1000.0), ("TRL", True, 900.0)), "OGR") == []
    assert view.tied_races(rows(("OGR", True, 1000.0)), "OGR") == []  # a trio with one legal race


def test_one_tied_race_is_listed_and_the_best_race_is_never_in_its_own_list():
    assert view.tied_races(rows(("OGR", True, 1000.0), ("TRL", True, 997.0), ("HUM", True, 900.0)), "OGR") == ["TRL"]


def test_two_tied_races_come_in_order_of_F_then_race_code():
    found = view.tied_races(rows(("OGR", True, 1000.0), ("TRL", True, 997.0), ("HUM", True, 998.0), ("DWF", True, 600.0)), "OGR")
    assert found == ["HUM", "TRL"]
    equal = view.tied_races(rows(("OGR", True, 1000.0), ("TRL", True, 998.0), ("HUM", True, 998.0), ("BAR", True, 998.0)), "OGR")
    assert equal == ["BAR", "HUM", "TRL"]  # equal F: by race code


def test_the_boundary_is_in_the_band_and_just_outside_is_not():
    best = 1000.0
    edge = best * (1 - view.TIE_BAND)  # 995.0
    assert view.tied_races(rows(("OGR", True, best), ("TRL", True, edge)), "OGR") == ["TRL"]
    assert view.tied_races(rows(("OGR", True, best), ("TRL", True, edge - 0.01)), "OGR") == []


def test_nothing_is_tied_when_the_best_value_is_zero_or_below():
    assert view.tied_races(rows(("OGR", True, 0.0), ("TRL", True, 0.0)), "OGR") == []
    assert view.tied_races(rows(("OGR", True, -10.0), ("TRL", True, -10.0), ("HUM", True, -10.05)), "OGR") == []


def test_a_race_that_cannot_start_the_trio_is_never_listed_however_close_it_is():
    assert view.tied_races(rows(("OGR", True, 1000.0), ("ELF", False, 1000.0), ("TRL", True, 999.0)), "OGR") == ["TRL"]
    assert view.tied_races(rows(("OGR", True, 1000.0), ("ELF", False, 1001.0)), "OGR") == []


def test_names_are_listed_with_commas_and_a_final_and():
    assert view.join_names(["Troll"]) == "Troll"
    assert view.join_names(["Dwarf", "Ogre"]) == "Dwarf and Ogre"
    assert view.join_names(["Dwarf", "Ogre", "Troll"]) == "Dwarf, Ogre and Troll"


# ---- the page ---------------------------------------------------------------------------------------------------------------------


def results_with_tie(*closeness: tuple[str, float]):
    """The fixture, with each race of ``closeness`` (code, share of the best race's F) given every row of the default shard. A race the fixture lacks
    is copied from the Troll's rows."""
    results = data.load_trio(FIXTURE)
    default = results.defaults
    shard = results.shards[(default.evidence, default.buffs)]
    best = max(s.value for s in shard.scenarios if s.race == default.race and s.role == default.role and s.tier == default.tier)
    rest = [s for s in shard.scenarios if s.race not in {code for code, _ in closeness}]
    for code, share in closeness:
        for s in shard.scenarios:
            if s.race == "TRL":
                rest.append(dataclasses.replace(s, race=code, value=best * share))
    shards = {**results.shards, (default.evidence, default.buffs): dataclasses.replace(shard, scenarios=tuple(rest))}
    return dataclasses.replace(results, shards=shards)


def built_page(results):
    book = content.load_rulebook(REPO / "rules" / "rules.json")
    page = view.trio_page(results, book, view.trio_caps(results.meta.trio, results.meta.level, rules_module.load()))
    return page, book


def best_line(results):
    page, book = built_page(results)
    html = render_trio(page, book)
    return page, html, parse(html).by_id("best-race")


def test_the_fixture_has_no_tie_and_its_line_is_byte_for_byte_what_it_was():
    page, html, _ = best_line(data.load_trio(FIXTURE))
    assert page.tied_names == ()
    assert UNTIED_LINE in html


def test_a_page_with_one_tied_race_says_it_is_tied_and_names_no_margin():
    page, html, line = best_line(results_with_tie(("TRL", 0.997)))
    assert page.tied_names == ("Troll",)
    assert line.text() == "Best race for this trio: Ogre, tied with Troll (within 0.5%), judged in the Balanced view at +4 with your own buffs."
    assert "over Troll" not in html and "(+" not in line.text()


def test_a_page_with_two_tied_races_lists_them_with_a_final_and_in_order_of_value():
    results = results_with_tie(("TRL", 0.997), ("HUM", 0.998))
    page, html, line = best_line(results)
    assert page.tied_names == ("Human", "Troll")
    assert line.text() == "Best race for this trio: Ogre, tied with Human and Troll (within 0.5%), judged in the Balanced view at +4 with your own buffs."
    assert line.find("strong").text() == "Ogre"  # the best race stays first and strong
    assert [n for n in line.find_all("span") if "art-race-ogre" in n.classes]  # and keeps its picture


def test_the_tie_span_keeps_the_rules_of_the_margin_so_the_links_still_work():
    _, _, line = best_line(results_with_tie(("TRL", 0.997)))
    span = line.find(cls="margin")
    assert span.text() == "(within 0.5%)" and set(span.get("data-rules").split()) == {"roles.balanced", "roles.templates"}


def test_a_race_just_outside_the_band_is_not_tied():
    page, html, _ = best_line(results_with_tie(("TRL", 0.994)))
    assert page.tied_names == () and "over Troll" in html


def test_an_illegal_race_inside_the_band_is_not_named():
    # the fixture's Wood Elf cannot start the trio: give it every row of the default shard at the best value
    results = results_with_tie(("ELF", 1.0))
    page, html, line = best_line(results)
    assert page.tied_names == () and "Wood Elf" not in line.text()


def test_every_trio_page_says_which_racials_are_not_scored_at_the_start_of_the_expander():
    for results in (data.load_trio(FIXTURE), results_with_tie(("TRL", 0.997))):
        _, html, _ = best_line(results)
        details = parse(html).by_id("race-why")
        first = [c for c in details.children if not isinstance(c, str) and c.tag == "p"][0]
        assert first.text() == "Racial abilities other than the Iksar's natural AC are not scored yet, so races close in value may differ in play."
        assert first.classes == {"note"}


# ---- the race dropdown says the same as the header --------------------------------------------------------------------------------


def dropdown(html):
    """The race picker as (code, text) of each option, as the page bakes it."""
    return [(o.get("value"), o.text()) for o in parse(html).by_id("sw-race").find_all("option")]


def test_the_dropdown_of_a_tied_page_marks_the_best_race_and_every_tied_race_as_tied_for_best():
    page, html, _ = best_line(results_with_tie(("TRL", 0.997), ("HUM", 0.998)))
    labels = dict(dropdown(html))
    assert labels["OGR"] == "Ogre (tied for best)"
    assert labels["TRL"] == "Troll (tied for best)" and labels["HUM"] == "Human (tied for best)"
    assert "best for this trio" not in html
    assert labels["ELF"] == "Wood Elf (needs unlock)"  # the race that cannot start the trio keeps its own label
    assert {o.code for o in page.races if o.tied} == {"TRL", "HUM"}


def test_the_dropdown_of_an_untied_page_marks_only_the_best_race_and_its_markup_is_what_it_was():
    page, html, _ = best_line(data.load_trio(FIXTURE))
    labels = dict(dropdown(html))
    assert labels["OGR"] == "Ogre (best for this trio)" and labels["TRL"] == "Troll" and labels["ELF"] == "Wood Elf (needs unlock)"
    assert "tied for best" not in html and not [o for o in page.races if o.tied]
    assert '<option value="OGR" data-label="Ogre" selected>Ogre (best for this trio)</option>' in html
    assert '<option value="TRL" data-label="Troll">Troll</option>' in html


def test_an_illegal_race_inside_the_band_gets_no_label_in_the_dropdown():
    page, html, _ = best_line(results_with_tie(("ELF", 1.0), ("TRL", 0.999)))
    labels = dict(dropdown(html))
    assert labels["ELF"] == "Wood Elf (needs unlock)"
    assert labels["TRL"] == "Troll (tied for best)" and labels["OGR"] == "Ogre (tied for best)"
    assert not [o for o in page.races if o.code == "ELF" and (o.tied or o.best)]
