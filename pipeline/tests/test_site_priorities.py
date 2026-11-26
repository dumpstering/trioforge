"""The trio page after the priorities work (branch priorities): the markup that the work may not grow, and the three readers' reports it answers in words.

The control itself is drawn by script, into room that the stylesheet keeps (static/priorities.js, static/site.css), so the markup of the page holds nothing for it; the largest trio page of a release
has some 170 bytes under its limit, which no change may raise (``build.LIMITS["trio_html"]``). The words changed here:

* the two group labels of the race picker read as selectable (the second was read as "not allowed");
* wherever the page words the armor class softcap it says that armor class past the cap still counts, at a reduced rate, and never that it stops: the Cap cell of Sheet AC, the line under the
  kit that explains "Lost without it", and the reason of a stat that is worth nothing past the softcap.

The browser tests (tests-e2e/priorities.spec.mjs, tests-js/priorities-page.test.mjs) cover the control.
"""

from __future__ import annotations

import re
from pathlib import Path

from test_site_build import PAGES, page, site  # noqa: F401  (site: the build of the fixture, indexable and with an owner, once for this module as well)

from trioforge.site import build, view

REPO = Path(__file__).resolve().parents[2]

#: the size of the markup of the fixture's trio page before the priorities work (the indexable build of 90c8f01 by this module's own fixture: 55,947 bytes)
MARKUP_BEFORE = 55_947 + 1_024  # (Part T put words in the page, which this check is not about: the stance note and the two haste notes of T8 and T10, less than a kilobyte together)


def test_the_trio_page_is_no_larger_than_it_was_before_the_priorities_control(site):  # noqa: F811
    """The control is script and stylesheet, and the changed words are paid for in the same markup (the literal characters for four entities, a shorter sentence), so the page does not grow."""
    out, _ = site
    size = len((out / PAGES["trio"]).read_bytes())
    assert size <= MARKUP_BEFORE, f"the trio page is {size - MARKUP_BEFORE} bytes larger than before"
    assert size <= build.LIMITS["trio_html"]


def test_the_trio_page_holds_no_markup_of_the_priorities_control(site):  # noqa: F811
    """The control is drawn by the page script (static/priorities.js); its room is kept by the stylesheet. Nothing of it is in the markup."""
    out, _ = site
    html = page(out, PAGES["trio"])
    assert html.find_all("fieldset", id_="prio") == [] and html.find_all("button", id_="prio-reset") == []
    assert not [node for node in html.iter() if (node.get("id") or "").startswith("prio")]


def test_the_two_group_labels_of_the_race_picker_both_read_as_selectable(site):  # noqa: F811
    out, _ = site
    html = page(out, PAGES["trio"])
    labels = [group.get("label") for group in html.by_id("sw-race").find_all("optgroup")]
    assert labels == ["Available at character creation", "Selectable after an unlock"]
    for label in labels:
        assert not re.search(r"\b(needs|requires|not allowed|cannot)\b", label, re.I), label


def test_the_softcap_cell_of_sheet_ac_says_that_armor_class_past_it_counts_at_a_reduced_rate(site):  # noqa: F811
    out, _ = site
    html = page(out, PAGES["trio"])
    row = next(r for r in html.by_id("totals-body").find_all("tr") if r.find("th").text() == "Sheet AC")
    cap = row.find_all("td")[1].text()
    assert cap.startswith("439 softcap, reduced rate past it"), cap
    for word in ("stops", "no more", "nothing past", "not counted"):
        assert word not in cap


def test_the_line_under_the_kit_keeps_the_softcap_out_of_the_stats_that_lose_nothing_past_a_cap(site):  # noqa: F811
    out, _ = site
    html = page(out, PAGES["trio"])
    line = html.by_id("kit-stats-rules").text()
    assert "A stat past a cap loses nothing, but armor class past its softcap still counts, at a reduced rate." in line
    assert "so a stat past a cap loses nothing" not in line  # (the sentence that said it of every cap)
    assert "Each item's stats are at the tier shown." in line  # (and the sentences that were there are)


def test_the_reason_a_stat_is_worth_nothing_past_the_armor_class_softcap_is_true_of_the_case_it_is_shown_in():
    """The precompute gives the reason only for a loss of exactly 0 with the sheet past its cap, under "Worth nothing here". The sheet past the cap counts at a reduced rate (said where the cap is), so the
    reason cannot say that the rate is what makes it count for nothing: it says that the stat is past the softcap and that it adds nothing at the role's weights, which is what a loss of 0 is."""
    reason = view.WHY_REASON_TEXT["ac-softcap"]
    assert "softcap" in reason and "adds nothing" in reason
    assert "reduced rate" not in reason and "stops" not in reason
    # and the other three reasons, which are hard caps (or a worn haste another piece matches), say what they said
    assert view.WHY_REASON_TEXT["resist-cap"] == "past the resist cap" and view.WHY_REASON_TEXT["haste-cap"] == "past the haste cap"


def test_the_room_kept_for_the_control_is_given_up_by_the_boot_script_when_the_page_script_does_not_draw_it(site):  # noqa: F811
    """The stylesheet keeps the control's room until the page script marks the section (data-prio); the boot script, which is not the page script, marks the page after a few seconds, and the
    stylesheet takes the gap away with the mark. Without it a page whose script failed would keep a blank gap of some 14 to 25 rem."""
    out, _ = site
    boot = next((out / "assets").glob("boot-*.js")).read_text(encoding="utf-8")
    assert "data-prio-off" in boot and "setTimeout" in boot
    css = (REPO / "pipeline" / "trioforge" / "site" / "static" / "site.css").read_text(encoding="utf-8")
    assert re.search(r"html\[data-prio-off\] \.controls:not\(\[data-prio\]\)::after \{\s*display: none;", css)
    assert ".controls:not([data-prio])::after" in css


def test_a_disabled_select_and_a_disabled_reset_look_disabled_in_the_stylesheet():
    css = (REPO / "pipeline" / "trioforge" / "site" / "static" / "site.css").read_text(encoding="utf-8")
    assert re.search(r"\.prio select:disabled,\s*\.prio-foot \.btn-quiet:disabled \{\s*opacity: 0\.55;", css)
    assert re.search(r"\.prio-foot \.btn-quiet:disabled \{\s*border-style: dashed;", css)


def test_no_text_of_the_trio_page_words_the_softcap_as_a_stop(site):  # noqa: F811
    """Every sentence of the trio page that says armor class and a cap together says that it still counts: no 'stops', no 'no more', no 'worth nothing' for armor class past its cap."""
    out, _ = site
    text = page(out, PAGES["trio"]).find("main").text()
    for sentence in re.split(r"(?<=[.;])\s+", text):
        if re.search(r"soft ?cap", sentence, re.I):
            assert not re.search(r"\b(stops?|no more|worth nothing|nothing past|ignored)\b", sentence, re.I), sentence
