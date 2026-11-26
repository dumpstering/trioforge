"""The races that the data says are close to the best are named as close, and the page says which racials are not scored.

The rule is the precompute's (``defaults.race_close_pct``: the creation-legal races whose value is within that percent of the best's, the default first), and ``close_races`` of the
defaults file is its answer. The trio page words that list and judges nothing of its own: "Races for this trio, close: Ogre, Human, Troll (within 1%), judged in ...", with no margin.
A trio whose best race stands alone reads as it always did.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from site_helpers import parse
from test_site_content import render_trio

from trioforge import rules as rules_module
from trioforge.site import content, data, view

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "fixtures" / "site" / "results" / "pal-mnk-ber"

#: the line of the fixture's best race as the page wrote it before the close races existed (the fixture has none): it must stay byte for byte
ALONE_LINE = (
    '<p id="best-race" class="best-race"><span class="art art-race-ogre" aria-hidden="true"></span>Best race for this trio: <strong>Ogre</strong> '
    '<span class="margin" data-rules="roles.templates">(+813 over Troll)</span>, judged in the <span id="best-race-view">Tank view at '
    '<span data-rules="tier.stat_rule">+4</span> with your own buffs</span>.</p>'
)


# ---- the page ---------------------------------------------------------------------------------------------------------------------


def results_with_close(*closeness: tuple[str, float]):
    """The fixture, with each race of ``closeness`` (code, share of the best race's F) given every row of the default shard, and the defaults file saying those races are close: the data's
    list is the default race first, then the others by value (a race the fixture lacks is copied from the Troll's rows)."""
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
    legal = {o.code for o in view.race_options([code for code, _ in closeness], trio=results.meta.trio, best=default.race) if o.legal}  # (the data's list holds races that can start the trio)
    ordered = [code for code, _ in sorted(closeness, key=lambda pair: (-pair[1], pair[0])) if code in legal]
    close = (default.race, *ordered) if ordered else ()
    return dataclasses.replace(results, shards=shards, defaults=dataclasses.replace(default, close_races=close))


def built_page(results):
    book = content.load_rulebook(REPO / "rules" / "rules.json")
    page = view.trio_page(results, book, view.trio_caps(results.meta.trio, results.meta.level, rules_module.load()))
    return page, book


def best_line(results):
    page, book = built_page(results)
    html = render_trio(page, book)
    return page, html, parse(html).by_id("best-race")


def test_the_fixture_has_no_close_race_and_its_line_is_byte_for_byte_what_it_was():
    page, html, _ = best_line(data.load_trio(FIXTURE))
    assert page.close_names == ()
    assert ALONE_LINE in html


def test_a_page_with_one_close_race_says_close_and_names_both_with_no_margin():
    page, html, line = best_line(results_with_close(("TRL", 0.997)))
    assert page.close_names == ("Ogre", "Troll") and page.close_pct == "1%"
    assert line.text() == "Races for this trio, close: Ogre, Troll (within 1%), judged in the Tank view at +4 with your own buffs."
    assert "over Troll" not in html and "(+" not in line.text() and "Best race for this trio" not in line.text()


def test_a_page_with_two_close_races_lists_the_data_list_in_its_order_default_first():
    results = results_with_close(("TRL", 0.997), ("HUM", 0.998))
    page, html, line = best_line(results)
    assert page.close_names == ("Ogre", "Human", "Troll")
    assert line.text() == "Races for this trio, close: Ogre, Human, Troll (within 1%), judged in the Tank view at +4 with your own buffs."
    assert [n.text() for n in line.find_all("strong")] == ["Ogre", "Human", "Troll"]  # the default race stays first and strong
    assert [n for n in line.find_all("span") if "art-race-ogre" in n.classes]  # and keeps its picture


def test_the_close_span_keeps_the_rules_of_the_margin_and_links_the_rule_that_decides_it():
    _, _, line = best_line(results_with_close(("TRL", 0.997)))
    span = line.find(cls="margin")
    assert span.text() == "(within 1%)" and set(span.get("data-rules").split()) == {"roles.templates", "defaults.race_close_pct"}


def test_the_page_names_what_the_data_lists_and_judges_nothing_itself():
    """A race whose value is within the old band of the best but is not on the data's list is not named; one on the list is, whatever its value."""
    results = results_with_close(("TRL", 0.997))
    results = dataclasses.replace(results, defaults=dataclasses.replace(results.defaults, close_races=()))
    page, html, _ = best_line(results)
    assert page.close_names == () and "over Troll" in html
    listed = dataclasses.replace(results, defaults=dataclasses.replace(results.defaults, close_races=("OGR", "TRL")))
    page, _, line = best_line(listed)
    assert page.close_names == ("Ogre", "Troll") and "close: Ogre, Troll" in line.text()


def test_every_trio_page_says_which_racials_are_not_scored_at_the_start_of_the_expander():
    for results in (data.load_trio(FIXTURE), results_with_close(("TRL", 0.997))):
        _, html, _ = best_line(results)
        details = parse(html).by_id("race-why")
        first = [c for c in details.children if not isinstance(c, str) and c.tag == "p"][0]
        assert first.text() == "Racial abilities other than the Iksar's natural AC are not scored yet, so races close in value may differ in play."
        assert first.classes == {"note"}


# ---- the race dropdown says the same as the header --------------------------------------------------------------------------------


def dropdown(html):
    """The race picker as (code, text) of each option, as the page bakes it."""
    return [(o.get("value"), o.text()) for o in parse(html).by_id("sw-race").find_all("option")]


def test_the_dropdown_of_a_page_with_close_races_marks_the_default_race_and_every_close_race_as_close():
    page, html, _ = best_line(results_with_close(("TRL", 0.997), ("HUM", 0.998)))
    labels = dict(dropdown(html))
    assert labels["OGR"] == "Ogre (close for this trio)"
    assert labels["TRL"] == "Troll (close for this trio)" and labels["HUM"] == "Human (close for this trio)"
    assert "best for this trio" not in html
    assert labels["ELF"] == "Wood Elf (needs unlock)"  # the race that cannot start the trio keeps its own label
    assert {o.code for o in page.races if o.close} == {"OGR", "TRL", "HUM"}


def test_the_dropdown_of_a_page_with_a_lone_best_race_marks_only_it_and_its_markup_is_what_it_was():
    page, html, _ = best_line(data.load_trio(FIXTURE))
    labels = dict(dropdown(html))
    assert labels["OGR"] == "Ogre (best for this trio)" and labels["TRL"] == "Troll" and labels["ELF"] == "Wood Elf (needs unlock)"
    assert "close for this trio" not in html and not [o for o in page.races if o.close]
    assert '<option value="OGR" data-label="Ogre" selected>Ogre (best for this trio)</option>' in html
    assert '<option value="TRL" data-label="Troll">Troll</option>' in html
