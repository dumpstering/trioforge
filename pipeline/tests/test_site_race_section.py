"""What each race gets you: the section of "How the best race was judged" (race-explain).

For the races the page names (the best race and the ones tied with it, or the best race and the runner-up) the section says, from the results and the rules and never from
hand-typed numbers: the race's value and its gap to the best, what its best kit's totals change against the best race's, its starting stats against the best race's, and its racial
abilities as the wiki words them, each said to be scored or not. Only the Iksar's natural AC is scored.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from site_helpers import parse
from test_site_build import need_node, read, run_build
from test_site_content import render_trio
from test_site_race_tie import UNTIED_LINE, results_with_tie

from trioforge import rules as rules_module
from trioforge.site import build, content, data, view

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "fixtures" / "site" / "results" / "pal-mnk-ber"
RULES = REPO / "rules" / "rules.json"
RACIALS = REPO / "derived" / "racials.json"
MINUS = "−"


@pytest.fixture(scope="module")
def racials():
    return content.load_racials(RACIALS)


@pytest.fixture(scope="module")
def book():
    return content.load_rulebook(RULES)


def make_page(results, book, racials):
    return view.trio_page(results, book, view.trio_caps(results.meta.trio, results.meta.level, rules_module.load()), racials=racials)


def render(results, book, racials):
    page = make_page(results, book, racials)
    html = render_trio(page, book)
    return page, html, parse(html)


def with_totals(results, race, **changes):
    """The results with the totals of every scenario of ``race`` in the default shard changed (field names and their new values)."""
    default = results.defaults
    shard = results.shards[(default.evidence, default.buffs)]
    scenarios = [
        dataclasses.replace(s, totals=dataclasses.replace(s.totals, **changes)) if s.race == race else s for s in shard.scenarios
    ]
    shards = {**results.shards, (default.evidence, default.buffs): dataclasses.replace(shard, scenarios=tuple(scenarios))}
    return dataclasses.replace(results, shards=shards)


def totals_of(results, race):
    default = results.defaults
    shard = results.shards[(default.evidence, default.buffs)]
    return shard.scenario(race, default.role, default.tier, shard.best_setup(race, default.role, default.tier)).totals


def facts(card_node):
    """The dl of a card as ``{term: Node of its definition}``."""
    dl = card_node.find("dl")
    terms = [n for n in dl.children if not isinstance(n, str) and n.tag == "dt"]
    definitions = [n for n in dl.children if not isinstance(n, str) and n.tag == "dd"]
    assert len(terms) == len(definitions)
    return {t.text(): d for t, d in zip(terms, definitions, strict=True)}


def card_nodes(doc):
    """The cards: the items of the list of the section (the racials of a card are a list of their own inside it)."""
    cards = doc.by_id("race-gets").find("ul", cls="race-cards")
    return [n for n in cards.children if not isinstance(n, str) and n.tag == "li"]


def racial_items(card_node):
    return facts(card_node)["Racial abilities"].find_all("li")


def totals(**changes):
    base = dict(ac=100, hp=1000, mana=500, end=300, haste=50, atk=200, resists=(10, 10, 10, 10, 10), regen=(5, 5, 5))
    return data.Totals(**{**base, **changes})


# ---- the words of the numbers ------------------------------------------------------------------------------------------------------


def test_a_percent_is_whole_hundredths_with_the_pages_minus_and_rounded_half_up():
    assert view.fmt_percent(-812.5, 10720.0) == f"{MINUS}7.58%"
    assert view.fmt_percent(5.0, 1000.0) == "+0.50%"
    assert view.fmt_percent(0.0, 1000.0) == "0.00%"
    assert view.fmt_percent(-0.0001, 1000.0) == "0.00%"  # a gap that rounds to nothing has no sign
    assert view.fmt_percent(-1.0, 1000.0) == f"{MINUS}0.10%"
    assert view.fmt_percent(-12345.0, 10000.0) == f"{MINUS}123.45%"


def test_the_gap_of_a_value_rounds_its_size_half_up_so_it_reads_as_the_margin_does():
    # the margin of the fixture (812.5) is said as +813; the gap of the runner-up to the best is the same size and says 813 too
    assert view.gap_text(-812.5, 10720.0) == f"{MINUS}813 ({MINUS}7.58%)"
    assert view.gap_text(3.0, 1000.0) == "+3 (+0.30%)"
    assert view.gap_text(0.0, 1000.0) == "the same"
    assert view.gap_text(-0.2, 100000.0) == "the same"  # rounds to nothing in both numbers


def test_a_gap_against_a_best_value_that_is_zero_or_less_has_no_percent():
    assert view.gap_text(-5.0, 0.0) == f"{MINUS}5"
    assert view.gap_text(-5.0, -10.0) == f"{MINUS}5"


def test_the_differences_of_totals_are_the_largest_first_the_zero_ones_left_out_and_at_most_five_with_a_count_of_the_rest():
    best = totals()
    assert view.totals_diff_text(totals(ac=112, hp=960, mana=618), best) == f"+118 mana, {MINUS}40 HP, +12 AC"
    seven = totals(ac=101, hp=1002, mana=503, end=304, haste=55, atk=206, resists=(10, 17, 10, 10, 10))
    assert view.totals_diff_text(seven, best) == "+7 fire resist, +6 attack, +5% haste, +4 endurance, +3 mana, and 2 more"
    assert view.totals_diff_text(totals(ac=101, hp=1002, mana=503, end=304, haste=55, atk=206), best) == "+6 attack, +5% haste, +4 endurance, +3 mana, +2 HP, and 1 more"
    assert view.totals_diff_text(best, best) == "no change"


def test_equal_differences_keep_the_order_of_the_totals_table():
    other = totals(ac=110, hp=990, mana=510, regen=(5, 15, 5))
    assert view.totals_diff_text(other, totals()) == f"+10 AC, {MINUS}10 HP, +10 mana, +10 mana regen"


def test_every_total_has_its_word():
    zero = data.Totals(ac=0, hp=0, mana=0, end=0, haste=0, atk=0, resists=(0, 0, 0, 0, 0), regen=(0, 0, 0))
    seen = []
    for index in range(14):
        v = [0] * 14
        v[index] = 1
        other = data.Totals(ac=v[0], hp=v[1], mana=v[2], end=v[3], haste=v[4], atk=v[5], resists=tuple(v[6:11]), regen=tuple(v[11:14]))
        seen.append(view.totals_diff_text(other, zero))
    assert seen == [
        "+1 AC", "+1 HP", "+1 mana", "+1 endurance", "+1% haste", "+1 attack", "+1 magic resist", "+1 fire resist", "+1 cold resist", "+1 disease resist",
        "+1 poison resist", "+1 HP regen", "+1 mana regen", "+1 endurance regen",
    ]  # fmt: skip


def test_the_starting_stats_differ_largest_first_and_in_the_order_of_the_stats_on_a_tie():
    assert view.base_diff_text("TRL", "OGR") == f"{MINUS}22 STR, {MINUS}13 STA, +13 AGI, {MINUS}8 INT, {MINUS}7 WIS, +5 DEX, +3 CHA"
    assert view.base_diff_text("HUM", "OGR") == f"{MINUS}55 STR, {MINUS}52 STA, +38 CHA, +15 INT, +8 WIS, +5 AGI, +5 DEX"
    assert view.base_diff_text("OGR", "OGR") == "no change"


# ---- a page whose best race is not tied --------------------------------------------------------------------------------------------


def test_an_untied_page_compares_the_runner_up_with_the_best_race(book, racials):
    page, _, doc = render(data.load_trio(FIXTURE), book, racials)
    assert [(c.code, c.name, c.tag) for c in page.race_cards] == [("OGR", "Ogre", "best race"), ("TRL", "Troll", "runner-up")]
    ogre, troll = card_nodes(doc)
    assert ogre.find("p").text() == "Ogre best race"
    assert troll.find("p").text() == "Troll runner-up"
    assert list(facts(ogre)) == ["Value", "Racial abilities"]
    assert list(facts(troll)) == ["Value", "Against Ogre", KIT, "Base stats", "Racial abilities"]


def test_the_values_and_the_gap_come_from_the_default_shard_at_each_races_best_setup(book, racials):
    _, html, doc = render(data.load_trio(FIXTURE), book, racials)
    ogre, troll = card_nodes(doc)
    assert facts(ogre)["Value"].text() == "10,720"
    assert facts(troll)["Value"].text() == "9,908"  # 9,907.5, its best setup (dual wield), rounded half up as every figure of the page is
    assert facts(troll)["Against Ogre"].text() == f"{MINUS}813 ({MINUS}7.58%)"
    assert "+813 over Troll" in html  # (the margin of the line above: the gap is the same size)


def test_the_kit_totals_and_the_starting_stats_are_the_races_minus_the_best_races(book, racials):
    _, _, doc = render(data.load_trio(FIXTURE), book, racials)
    troll = card_nodes(doc)[1]
    assert facts(troll)[KIT].text() == f"{MINUS}80 HP, {MINUS}40 attack, {MINUS}10 AC"
    assert facts(troll)["Base stats"].text() == f"{MINUS}22 STR, {MINUS}13 STA, +13 AGI, {MINUS}8 INT, {MINUS}7 WIS, +5 DEX, +3 CHA"


def test_the_totals_come_from_the_scenarios_so_a_changed_scenario_changes_the_words(book, racials):
    results = data.load_trio(FIXTURE)
    ogre = totals_of(results, "OGR")
    changed = with_totals(results, "TRL", ac=ogre.ac + 12, hp=ogre.hp - 40, mana=ogre.mana + 118, atk=ogre.atk, end=ogre.end)
    _, _, doc = render(changed, book, racials)
    assert facts(card_nodes(doc)[1])[KIT].text() == f"+118 mana, {MINUS}40 HP, +12 AC"
    same = with_totals(results, "TRL", **{f.name: getattr(ogre, f.name) for f in dataclasses.fields(ogre)})
    _, _, doc = render(same, book, racials)
    assert facts(card_nodes(doc)[1])[KIT].text() == "no change"


def test_the_scenario_diffed_is_the_races_best_setup_and_not_a_setup_that_scores_less(book, racials):
    results = data.load_trio(FIXTURE)
    default = results.defaults
    shard = results.shards[(default.evidence, default.buffs)]
    worse = next(s for s in shard.setups_for(default.role) if s != shard.best_setup("TRL", default.role, default.tier))
    scenarios = tuple(
        dataclasses.replace(s, totals=dataclasses.replace(s.totals, mana=9999)) if (s.race, s.role, s.tier, s.setup) == ("TRL", default.role, default.tier, worse) else s
        for s in shard.scenarios
    )
    changed = dataclasses.replace(results, shards={**results.shards, (default.evidence, default.buffs): dataclasses.replace(shard, scenarios=scenarios)})
    _, _, doc = render(changed, book, racials)
    assert "mana" not in facts(card_nodes(doc)[1])[KIT].text()


def with_setup_value(results, race, setup, value):
    """The results with the value of one setup of a race changed in the default view (so that it is the race's best setup, or not)."""
    default = results.defaults
    shard = results.shards[(default.evidence, default.buffs)]
    scenarios = tuple(
        dataclasses.replace(s, value=value) if (s.race, s.role, s.tier, s.setup) == (race, default.role, default.tier, setup) else s for s in shard.scenarios
    )
    return dataclasses.replace(results, shards={**results.shards, (default.evidence, default.buffs): dataclasses.replace(shard, scenarios=scenarios)})


def test_the_totals_term_says_each_race_is_judged_on_its_own_best_kit_with_the_real_best_races_name(book, racials):
    _, _, doc = render(results_with_tie(("TRL", 0.997), ("HUM", 0.998)), book, racials)
    for card in card_nodes(doc)[1:]:
        assert list(facts(card))[2] == KIT
        assert "Kit totals" not in card.text()


def test_a_race_whose_best_setup_is_not_the_best_races_names_both_setups_in_its_card(book, racials):
    results = with_setup_value(data.load_trio(FIXTURE), "TRL", "2h", 9910.0)  # Troll is best on a two-hander (9,910), Ogre on dual wield
    page, _, doc = render(results, book, racials)
    troll = card_nodes(doc)[1]
    assert list(facts(troll)) == ["Value", "Against Ogre", KIT, "Weapons", "Base stats", "Racial abilities"]
    assert facts(troll)["Weapons"].text() == "Troll: two-hander; Ogre: dual wield"
    assert facts(troll)["Value"].text() == "9,910"  # (the value is that best setup's)
    assert page.race_cards[1].weapons == "Troll: two-hander; Ogre: dual wield"


def test_a_race_on_the_same_setup_as_the_best_race_has_no_weapons_row(book, racials):
    _, _, doc = render(data.load_trio(FIXTURE), book, racials)
    assert "Weapons" not in facts(card_nodes(doc)[1])
    assert "Weapons" not in facts(card_nodes(doc)[0])  # (the best race is the one the others are named against)


# ---- a page with tied races --------------------------------------------------------------------------------------------------------


def test_a_tied_page_has_the_best_race_and_every_tied_race_in_order_of_value(book, racials):
    page, _, doc = render(results_with_tie(("TRL", 0.997), ("HUM", 0.998)), book, racials)
    assert [(c.code, c.tag) for c in page.race_cards] == [("OGR", "best race"), ("HUM", "tied with Ogre"), ("TRL", "tied with Ogre")]
    assert [n.find("p").text() for n in card_nodes(doc)] == ["Ogre best race", "Human tied with Ogre", "Troll tied with Ogre"]
    human = card_nodes(doc)[1]
    assert facts(human)["Value"].text() == "10,699"
    assert facts(human)["Against Ogre"].text() == f"{MINUS}21 ({MINUS}0.20%)"
    assert facts(human)["Racial abilities"].text() == "none listed on the wiki page"  # the Human page says "None"


def test_a_race_that_cannot_start_the_trio_is_not_named_even_when_it_is_the_closest(book, racials):
    page, _, _ = render(results_with_tie(("ELF", 1.0), ("TRL", 0.999)), book, racials)
    assert [c.code for c in page.race_cards] == ["OGR", "TRL"]


VIEW = "Balanced view at +4 with your own buffs"  # the words of #best-race-view on the fixture page
KIT = "Its best kit against Ogre's best kit"  # the term of the totals: each race is judged on its own best kit, so the totals compare kits and not only races
OWN_KITS = "Each race is judged with its own best kit, so the differences include item choices as well as the race."


def test_the_intro_of_a_tied_page_names_the_view_it_describes_in_the_words_of_the_best_race_line(book, racials):
    _, _, doc = render(results_with_tie(("TRL", 0.997)), book, racials)
    assert doc.by_id("best-race-view").text() == VIEW
    assert doc.by_id("race-gets-intro").text() == (
        f"In the {VIEW}, these races are within 0.5% of the best, so the page calls them tied. This section describes that view; the switches do not change it. "
        f"Each is compared with Ogre. {OWN_KITS} Values are in hit-point equivalents."
    )


def test_the_intro_of_an_untied_page_names_the_view_it_describes_too(book, racials):
    _, _, doc = render(data.load_trio(FIXTURE), book, racials)
    assert doc.by_id("race-gets-intro").text() == (
        f"In the {VIEW}, the runner-up is compared with the best race, Ogre. This section describes that view; the switches do not change it. {OWN_KITS} Values are in hit-point equivalents."
    )


def test_the_view_of_the_section_follows_the_view_the_page_was_built_for(book, racials):
    """The words are the page's own (role, tier and buffs of the default view), not a fixed text: another default view says another view."""
    results = data.load_trio(FIXTURE)
    other = dataclasses.replace(results, defaults=dataclasses.replace(results.defaults, role="tank", tier=10))
    page, _, doc = render(other, book, racials)
    assert doc.by_id("best-race-view").text() == "Tank view at +10 with your own buffs"
    assert "In the Tank view at +10 with your own buffs, " in doc.by_id("race-gets-intro").text()


def test_no_card_says_it_is_best_in_this_view_since_a_change_of_the_switches_makes_that_false(book, racials):
    _, _, doc = render(results_with_tie(("TRL", 0.997)), book, racials)
    assert "in this view" not in doc.by_id("race-gets").text()
    assert [n.find("p").text() for n in card_nodes(doc)] == ["Ogre best race", "Troll tied with Ogre"]


# ---- the racial abilities, said as scored or not -----------------------------------------------------------------------------------


def test_every_ogre_racial_says_it_is_not_scored_with_the_wikis_words(book, racials):
    _, _, doc = render(data.load_trio(FIXTURE), book, racials)
    assert [li.text() for li in racial_items(card_nodes(doc)[0])] == [
        "Increased Consumption Rate (not scored): Barbarians, Halflings, Ogres, and Trolls all consume food and drink slightly faster than other races.",
        "Infravision (not scored): Slightly improved night vision, not as good as the Dark Elf's Ultravision.",
        "Frontal Stun Immunity (not scored): Ogres cannot be stunned from the front, which gives them a great advantage over other races.",
        "Slam (not scored)",  # the wiki's Ogre page says no more of it, and nothing more is made up
    ]


def test_the_iksar_armour_class_is_the_one_racial_that_says_it_is_scored_and_with_the_rules_number(book, racials):
    _, _, doc = render(results_with_tie(("IKS", 0.999)), book, racials)
    iksar = next(n for n in card_nodes(doc) if n.find("p").text().startswith("Iksar"))
    items = racial_items(iksar)
    scored = [li for li in items if "(not scored)" not in li.text()]
    assert [li.text() for li in scored] == [
        "Increased Armor Class (scored, +35 AC Developer)",  # (the wiki's "+15 AC" sentence is not shown beside the rule's number: it says another figure with no word of why)
    ]
    link = scored[0].find("a")
    assert link.get("href") == "/rules/#race.iksar_ac_bonus" and link.text() == "scored, +35 AC"
    assert scored[0].find(cls="seal").text() == "Developer"  # (the page links a rule with its seal after the link, as it does for every figure)
    assert len(items) == 7 and len([li for li in items if "(not scored)" in li.text()]) == 6


def test_the_number_of_the_scored_racial_is_the_rules_and_not_the_pages(book, racials):
    page = make_page(results_with_tie(("IKS", 0.999)), book, racials)
    rule = book.get("race.iksar_ac_bonus")
    scored = [r for c in page.race_cards for r in c.racials if r.scored]
    assert [(r.name, r.scored_text) for r in scored] == [("Increased Armor Class", f"+{rule.value} {rule.unit}")]
    assert scored[0].rule is not None and scored[0].rule.id == "race.iksar_ac_bonus"


def test_the_page_refuses_to_call_a_racial_scored_that_the_racials_file_does_not_have(book, racials):
    stripped = dataclasses.replace(racials, rows=tuple(r for r in racials.rows if not (r.race == "IKS" and r.name == "Increased Armor Class")))
    with pytest.raises(ValueError, match="Increased Armor Class"):
        make_page(results_with_tie(("IKS", 0.999)), book, stripped)
    make_page(data.load_trio(FIXTURE), book, stripped)  # (a page that does not name the Iksar does not need it)


def test_nothing_in_the_section_says_a_racial_changes_the_ranking(book, racials):
    _, _, doc = render(results_with_tie(("TRL", 0.997), ("IKS", 0.998)), book, racials)
    text = doc.by_id("race-gets").text().casefold()
    for phrase in ("changes the ranking", "moves the ranking", "ranks higher", "counts toward", "adds to the value", "is worth more"):
        assert phrase not in text


# ---- where the section is, and the line it leaves alone ----------------------------------------------------------------------------


def test_the_section_is_in_the_expander_after_the_scoring_notes_and_before_what_could_change_it(book, racials):
    _, _, doc = render(results_with_tie(("TRL", 0.997)), book, racials)
    details = doc.by_id("race-why")
    assert [n.get("id") for n in details.children if not isinstance(n, str) and n.get("id")] == ["best-race-unscored", "best-race-rules", "race-gets", "best-race-note"]
    first = [n for n in details.children if not isinstance(n, str) and n.tag == "p"][0]
    assert first.text() == "Racial abilities other than the Iksar's natural AC are not scored yet, so races close in value may differ in play."  # the sentence stays as it was


def test_the_best_race_line_of_an_untied_page_is_byte_for_byte_what_it_was(book, racials):
    _, html, _ = render(data.load_trio(FIXTURE), book, racials)
    assert UNTIED_LINE in html


def test_the_best_race_line_of_a_tied_page_is_what_it_was_too(book, racials):
    _, _, doc = render(results_with_tie(("TRL", 0.997), ("HUM", 0.998)), book, racials)
    assert doc.by_id("best-race").text() == "Best race for this trio: Ogre, tied with Human and Troll (within 0.5%), judged in the Balanced view at +4 with your own buffs."


def test_a_page_given_no_racials_has_no_section_and_is_the_page_it_was(book):
    page, html, doc = render(data.load_trio(FIXTURE), book, None)
    assert page.race_cards == () and "race-gets" not in html
    assert [n.get("id") for n in doc.by_id("race-why").children if not isinstance(n, str) and n.get("id")] == ["best-race-unscored", "best-race-rules", "best-race-note"]


def test_the_credit_line_names_the_wiki_and_the_licence_and_links_the_pages_used(book, racials):
    _, _, doc = render(data.load_trio(FIXTURE), book, racials)
    credit = doc.by_id("race-credit")
    assert credit.text() == "Racial abilities: eqlwiki, CC BY-SA 4.0 (pages and revisions)"
    assert [a.get("href") for a in credit.find_all("a")] == ["https://eqlwiki.com/", "https://creativecommons.org/licenses/by-sa/4.0/legalcode", "/sources/#races-box"]
    assert all(a.get("rel") == "noopener noreferrer" for a in credit.find_all("a")[:2])


def test_the_section_names_the_rules_its_figures_follow_and_links_the_rule_of_the_starting_stats_with_its_seal(book, racials):
    page, _, doc = render(data.load_trio(FIXTURE), book, racials)
    section = doc.by_id("race-gets")
    named = section.get("data-rules").split()
    assert named[:2] == ["roles.balanced", "roles.templates"] and named[-1] == "naked.rule"  # the margin's rules, the totals' rules and the rule of the starting stats
    assert set(named[2:-1]) == {row.rule.id for row in page.totals} and len(named) == len(set(named))
    assert [r.id for r in page.race_rules] == named
    link = section.find("a", href="/rules/#naked.rule")
    assert link.text() == "Naked stat formula" and link.parent.find(cls="seal").text() == "Player reports"


def test_a_page_with_no_section_names_no_rules_for_it(book):
    page, _, _ = render(data.load_trio(FIXTURE), book, None)
    assert page.race_rules == () and page.naked_rule is None


def test_the_licence_link_is_the_one_the_build_uses():
    assert (view.RACIALS_LICENCE_NAME, view.RACIALS_LICENCE_URL) == (build.LICENCE_NAME, build.LICENCE_URL)
    assert view.RACIALS_SITE == dict(build.ATTRIBUTION_LINKS)["eqlwiki.com"]


def test_the_section_is_a_description_list_with_real_terms_and_no_table_to_scroll(book, racials):
    _, _, doc = render(results_with_tie(("TRL", 0.997)), book, racials)
    assert not doc.by_id("race-gets").find_all("table")
    for card in card_nodes(doc):
        assert all(n.tag in ("dt", "dd") for n in card.find("dl").children if not isinstance(n, str))


# ---- the built page ----------------------------------------------------------------------------------------------------------------


def test_the_built_fixture_page_has_the_section_and_stays_inside_its_size(tmp_path):
    need_node()
    run_build(tmp_path / "dist", tmp_path, noindex=True)
    html = read(tmp_path / "dist", "trio/pal-mnk-ber/index.html")
    doc = parse(html)
    assert len(card_nodes(doc)) == 2
    assert len(html.encode("utf-8")) <= build.LIMITS["trio_html"]


def test_the_scored_racial_shows_no_sentence_of_the_wiki_but_the_file_keeps_it(book, racials):
    page = make_page(results_with_tie(("IKS", 0.999)), book, racials)
    scored = next(r for c in page.race_cards for r in c.racials if r.scored)
    assert scored.text == ""
    assert next(r for r in racials.of("IKS") if r.name == "Increased Armor Class").description.startswith("Iksar start with a +15 AC bonus")  # derived/racials.json is as it was
    _, html, _ = render(results_with_tie(("IKS", 0.999)), book, racials)
    assert "+15 AC" not in html


# ---- a long list of ties is capped, and a sentence the section has said is not said again ------------------------------------------

#: eight races tied with the best one (all within 0.5% of it, all able to start the trio), the closest first: Human, High Elf, Barbarian, Erudite, Dwarf, Halfling, Half Elf, Iksar
EIGHT = (("HUM", 0.999), ("HIE", 0.9985), ("BAR", 0.998), ("ERU", 0.9975), ("DWF", 0.9965), ("HFL", 0.996), ("HEF", 0.9955), ("IKS", 0.9952))


def test_a_page_with_eight_tied_races_shows_the_best_race_and_the_five_closest_and_says_how_many_are_not_shown(book, racials):
    page, _, doc = render(results_with_tie(*EIGHT), book, racials)
    assert [c.name for c in page.race_cards] == ["Ogre", "Human", "High Elf", "Barbarian", "Erudite", "Dwarf"]
    assert len(card_nodes(doc)) == view.MAX_RACE_CARDS == 6
    more = doc.by_id("race-more")
    assert more.text() == "3 more tied races are not shown; the Race control picks them."
    assert more.parent is doc.by_id("race-gets")


def test_the_best_race_line_still_names_all_eight_tied_races(book, racials):
    page, _, doc = render(results_with_tie(*EIGHT), book, racials)
    assert page.tied_names == ("Human", "High Elf", "Barbarian", "Erudite", "Dwarf", "Halfling", "Half Elf", "Iksar")
    assert doc.by_id("best-race").text() == (
        "Best race for this trio: Ogre, tied with Human, High Elf, Barbarian, Erudite, Dwarf, Halfling, Half Elf and Iksar (within 0.5%), "
        "judged in the Balanced view at +4 with your own buffs."
    )


@pytest.mark.parametrize(("shown", "line"), [(5, None), (6, "1 more tied race is not shown; the Race control picks it."), (7, "2 more tied races are not shown; the Race control picks them.")])
def test_the_line_about_races_not_shown_is_there_only_when_some_are_left_out_and_counts_them(book, racials, shown, line):
    page, _, doc = render(results_with_tie(*EIGHT[:shown]), book, racials)
    if line is None:
        assert page.race_more == "" and "race-more" not in render_trio(page, book)
    else:
        assert doc.by_id("race-more").text() == line
    assert len(page.race_cards) == min(shown, 5) + 1


def sentences(doc):
    """Each racial of the section as (index of its card, its name, the sentence after its label or None)."""
    found = []
    for index, card in enumerate(card_nodes(doc)):
        for li in racial_items(card):
            _, colon, rest = li.text().partition("): ")
            found.append((index, li.find("dfn").text(), rest if colon else None))
    return found


def test_a_racial_sentence_is_printed_only_on_its_first_appearance_in_the_section(book, racials):
    _, _, doc = render(results_with_tie(("TRL", 0.997), ("HUM", 0.998)), book, racials)
    found = sentences(doc)
    printed = [(name, text) for _, name, text in found if text]
    assert len(printed) == len(set(printed))  # no sentence twice
    ogre = [(name, text) for index, name, text in found if index == 0]
    assert ("Infravision", "Slightly improved night vision, not as good as the Dark Elf's Ultravision.") in ogre  # the first card (the best race) has it
    troll = card_nodes(doc)[2]
    texts = [li.text() for li in racial_items(troll)]
    assert "Infravision (not scored)" in texts and "Increased Consumption Rate (not scored)" in texts  # said above, so the name and its label only
    assert "Increased HP Regeneration (not scored): Both Iksar and Trolls have higher HP regeneration rates (per tick)" in texts  # first appearance: printed


def test_every_racial_of_every_card_still_says_whether_it_is_scored(book, racials):
    _, _, doc = render(results_with_tie(("TRL", 0.997), ("HUM", 0.998), ("IKS", 0.9975)), book, racials)
    for card in card_nodes(doc):
        for li in racial_items(card):
            assert "(not scored)" in li.text() or "(scored," in li.text(), li.text()


def test_the_same_name_with_another_sentence_is_printed_again(book, racials):
    other = dataclasses.replace(
        racials, rows=tuple(dataclasses.replace(r, description="Troll night vision, a little different.") if (r.race, r.name) == ("TRL", "Infravision") else r for r in racials.rows)
    )
    _, _, doc = render(results_with_tie(("TRL", 0.997)), book, other)
    found = [(index, text) for index, name, text in sentences(doc) if name == "Infravision"]
    assert found == [(0, "Slightly improved night vision, not as good as the Dark Elf's Ultravision."), (1, "Troll night vision, a little different.")]


# ---- SCORED_RACIALS is held to what the model applies --------------------------------------------------------------------------------


def race_profiles():
    """The profile of every race for one trio and role, as ``make_profile`` makes it (the one place the model reads a race)."""
    from dataclasses import fields

    from trioforge.data import races as races_module
    from trioforge.model.profile import make_profile

    tables = view._tables()
    profiles = {code: make_profile(code, ("PAL", "MNK", "BER"), 50, "balanced", None, None, tables, tables.rules) for code in races_module.RACE_NAMES}
    return profiles, [f.name for f in fields(profiles["HUM"])]


#: what a profile may differ in from race to race without a racial ability being scored: the name of the race, and the starting stats (the table of base stats, shown in the section as "Base stats")
NOT_A_RACIAL = ("race", "naked")


def test_the_racial_the_model_applies_is_the_one_the_page_calls_scored():
    """``view.SCORED_RACIALS`` says which racial the page labels "scored". The model's profile of a race is the same for every race but the name, the starting stats and the racial armour class, so a
    racial the model starts to apply (a resist, a regen, a skill) makes a field of the profile differ, and this test fails until the table says so."""
    profiles, names = race_profiles()
    base = profiles["HUM"]
    applied = {}
    for code, profile in profiles.items():
        for name in names:
            if name not in NOT_A_RACIAL and getattr(profile, name) != getattr(base, name):
                applied.setdefault(name, set()).add(code)
    assert set(applied) == {"iksar_ac"}, f"the model applies a racial term the page does not know of: {sorted(set(applied) - {'iksar_ac'})}; say it in view.SCORED_RACIALS (and in the racial's own row)"
    scored_races = {code for code, _ in view.SCORED_RACIALS}
    assert applied["iksar_ac"] == scored_races == {"IKS"}


def test_the_scored_racial_is_the_one_the_rule_of_the_armour_class_bonus_names(book):
    """The racial of ``SCORED_RACIALS`` is scored by the rule ``race.iksar_ac_bonus`` and the profile's ``iksar_ac`` is that rule's number: the page's "+35 AC" is the model's."""
    profiles, _ = race_profiles()
    assert view.SCORED_RACIALS == {("IKS", "Increased Armor Class"): "race.iksar_ac_bonus"}
    assert int(profiles["IKS"].iksar_ac) == int(book.get("race.iksar_ac_bonus").value)
    assert all(profiles[code].iksar_ac == 0 for code in profiles if code != "IKS")


def test_the_check_would_catch_a_racial_the_model_started_to_apply(monkeypatch):
    """The check is only worth something if it can fail: a profile of one race that differs in a field of the profile is found."""
    import dataclasses

    profiles, names = race_profiles()
    profiles["DWF"] = dataclasses.replace(profiles["DWF"], caps={**profiles["DWF"].caps, "resist": profiles["DWF"].caps["resist"] + 5})
    base = profiles["HUM"]
    differing = {name for code, profile in profiles.items() for name in names if name not in NOT_A_RACIAL and getattr(profile, name) != getattr(base, name)}
    assert differing == {"iksar_ac", "caps"}


def test_the_check_fails_when_the_table_and_the_model_disagree_either_way(monkeypatch):
    """A table that forgets the Iksar's armour class, and one that claims a racial the model does not apply, both fail the check above."""
    monkeypatch.setattr(view, "SCORED_RACIALS", {})
    with pytest.raises(AssertionError):
        test_the_racial_the_model_applies_is_the_one_the_page_calls_scored()
    monkeypatch.setattr(view, "SCORED_RACIALS", {("IKS", "Increased Armor Class"): "race.iksar_ac_bonus", ("DWF", "Infravision"): "race.iksar_ac_bonus"})
    with pytest.raises(AssertionError):
        test_the_racial_the_model_applies_is_the_one_the_page_calls_scored()
