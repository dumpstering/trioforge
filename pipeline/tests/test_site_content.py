"""The other inputs of the pages (rules, sources manifest, changelog), the page wording helpers, and the agreement between
the Python wording and the browser code's constants."""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from trioforge import rules as rules_module
from trioforge.site import content, data, view

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "pipeline" / "trioforge" / "site" / "static"
MANIFEST = REPO / "fixtures" / "site" / "sources-manifest.json"


# ---- the changelog reader -----------------------------------------------------------------------------------------------


def test_the_reader_knows_headings_bullets_paragraphs_and_three_inline_forms():
    blocks = content.parse_markdown(
        "# Title is the page's own\n\n## One\n\n- a **bold** word\n- `code` and [a link](https://example.org/x)\n  that wraps\n\n"
        "Plain paragraph\nover two lines.\n\n### Small\n"
    )
    assert [b.kind for b in blocks] == ["h2", "ul", "p", "h3"]
    assert [s.text for s in blocks[0].segments] == ["One"]
    first, second = blocks[1].items
    assert [(s.kind, s.text) for s in first] == [("text", "a "), ("strong", "bold"), ("text", " word")]
    assert [(s.kind, s.text, s.href) for s in second] == [
        ("code", "code", None),
        ("text", " and ", None),
        ("link", "a link", "https://example.org/x"),
        ("text", " that wraps", None),
    ]
    assert blocks[2].segments[0].text == "Plain paragraph over two lines."


def test_markup_and_unsafe_links_stay_plain_text():
    blocks = content.parse_markdown("- <script>alert(1)</script> and [x](javascript:alert(1)) and [y](//evil.example)\n")
    text = "".join(s.text for s in blocks[0].items[0])
    assert all(s.kind == "text" for s in blocks[0].items[0])  # nothing was turned into a link or a tag
    assert "<script>alert(1)</script>" in text and "[x](javascript:alert(1))" in text and "[y](//evil.example)" in text


def test_a_missing_changelog_is_none_and_the_repositorys_has_an_unreleased_section():
    assert content.load_changelog(REPO / "docs" / "no-such-file.md") is None
    blocks = content.load_changelog(REPO / "docs" / "CHANGELOG.md")
    assert blocks is not None
    assert [b.kind for b in blocks][0] == "h2" and blocks[0].segments[0].text == "Unreleased"
    assert any(b.kind == "ul" and b.items for b in blocks)


# ---- the rules -----------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def book():
    return content.load_rulebook(REPO / "rules" / "rules.json")


def test_rules_are_grouped_by_their_first_word_in_file_order(book):
    keys = [g.key for g in book.groups]
    assert keys[:4] == ["level", "naked", "hp", "mana"]
    assert len(keys) == len(set(keys))
    assert book.get("haste.cap_pct").seal_label == "Player reports"
    assert book.get("hp.sta_curve").value == '{"breaks": [255, 510], "slopes": [1, 0.5, 0]}'
    with pytest.raises(content.ContentError, match="no.such"):
        book.get("no.such")


def test_the_open_tests_are_listed_in_test_order(book):
    numbers = [int(rule.test[1:]) for rule in book.open_rules]
    assert numbers == sorted(numbers) and numbers[0] == 1
    assert {r.id for r in book.open_rules} == {
        rule["id"] for rule in json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))["rules"] if rule["status"] == "open"
    }


def test_private_sources_show_only_their_fixed_label(book):
    texts = [s.text for s in book.get("naked.cap").sources]
    assert texts == ["Maintainer's private observation (measured)"]
    assert all(s.href is None for s in book.get("naked.cap").sources)
    assert [s.text for s in book.get("mana.stat_by_class").sources] == ["Client file: eqstr_us.txt"]


def test_values_are_shown_plainly():
    f = content.format_value
    assert f(75) == "75" and f(0.654) == "0.654" and f("none") == "none" and f(True) == "yes" and f(False) == "no"
    assert f(None) == "not known yet"
    assert f({"breaks": [1, 2], "slopes": [0, 1, 2]}) == '{"breaks": [1, 2], "slopes": [0, 1, 2]}'


def test_a_superseded_rule_is_left_out(tmp_path):
    document = json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))
    old = dict(document["rules"][0], id="level.old", title="Old level cap", status="superseded")
    document["rules"].append(old)
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    book = content.load_rulebook(path)
    assert "level.old" not in book.by_id
    assert all("level.old" != r.id for g in book.groups for r in g.rules)


def test_an_invalid_rules_file_is_refused_in_one_line(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text('{"version": "2026-10-13", "rules": []}', encoding="utf-8")
    with pytest.raises(content.ContentError) as caught:
        content.load_rulebook(path)
    assert "\n" not in str(caught.value) and "rules.json" in str(caught.value)


# ---- the sources manifest ---------------------------------------------------------------------------------------------------


def test_the_manifest_is_read_and_its_links_are_built():
    manifest = content.load_manifest(MANIFEST)
    assert manifest.license == "CC BY-SA 4.0"
    assert manifest.items["w80158"] == ("Copperleaf Sash", 200102)
    assert ("derived/client/zones.json", "2026-09-22") in manifest.inputs
    assert content.wiki_url("Copperleaf Sash", 200102) == "https://eqlwiki.com/index.php?title=Copperleaf_Sash&oldid=200102"
    assert content.wiki_url("Fennick's Spoon", 5) == "https://eqlwiki.com/index.php?title=Fennick%27s_Spoon&oldid=5"


def test_a_missing_manifest_says_how_to_make_one(tmp_path):
    with pytest.raises(content.ContentError) as caught:
        content.load_manifest(tmp_path / "sources-manifest.json")
    assert "--sources-manifest" in str(caught.value) and "\n" not in str(caught.value)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.pop("items"),
        lambda d: d["items"].update(w1={"title": "", "revid": 1}),
        lambda d: d["items"].update(w1={"title": "x", "revid": "1"}),
        lambda d: d.pop("attribution"),
        lambda d: d["provenance"].pop("inputs"),
    ],
)
def test_a_manifest_of_the_wrong_shape_is_refused(tmp_path, change):
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    change(document)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(content.ContentError, match="manifest.json"):
        content.load_manifest(path)


# ---- the caps the page shows ----------------------------------------------------------------------------------------------------


def test_the_caps_come_from_the_model_for_the_trio():
    rules = rules_module.load()
    monk = view.trio_caps(("PAL", "MNK", "BER"), 50, rules)
    assert (monk.softcap, monk.haste, monk.resist, monk.regen, monk.haste_rule) == (439, 85, 200, (30, 15, 15), "haste.cap_pct_with_monk")
    plain = view.trio_caps(("PAL", "SHD", "BER"), 50, rules)
    assert (plain.haste, plain.haste_rule) == (75, "haste.cap_pct")


# ---- the browser code says what the pages say ---------------------------------------------------------------------------------------------


def test_the_browser_code_orders_setups_like_the_data():
    source = (STATIC / "shard.js").read_text(encoding="utf-8")
    listed = re.search(r"export const SETUP_ORDER = \[([^\]]*)\]", source)
    assert listed is not None
    assert tuple(re.findall(r'"([^"]+)"', listed.group(1))) == data.SETUPS


def js_string(source: str, name: str) -> str:
    """The value of ``const <name> = "..."`` in a JavaScript file, with its unicode escapes decoded."""
    match = re.search(rf'const {name} = "([^"]*)"', source)
    assert match is not None, name
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda g: chr(int(g.group(1), 16)), match.group(1))


def test_the_browser_code_words_item_seals_and_empty_slots_like_the_pages():
    source = (STATIC / "format.js").read_text(encoding="utf-8")
    for evidence, (label, icon) in view.ITEM_SEALS.items():
        assert re.search(rf'{evidence}: \["{re.escape(label)}", "{icon}"\]', source), evidence
    assert js_string(source, "EMPTY_NAME") == view.EMPTY_NAME
    assert js_string(source, "DASH") == view.DASH == "—"
    assert js_string(source, "EN_DASH") == view.EN_DASH == "–"
    assert js_string(source, "MINUS") == view.MINUS == "−"
    assert view.deity_text(("A", "B")) == "Needs deity: A or B"
    assert 'names.length > 0 ? "Needs deity: " + names.join(" or ") : ""' in source
    assert '" copies to reach "' in source


def test_the_section_words_the_weapon_setups_of_a_shared_kit_like_the_pages():
    """The panel of a shared kit says the kit's weapon setup in the page's words, and has the words for a setup the page has no switch for (a trio without a caster has no stat stick)."""
    source = (STATIC / "ui" / "shared-kit.js").read_text(encoding="utf-8")
    listed = re.search(r"const SETUP_WORDS = new Map\(\[(.*?)\]\);", source, re.DOTALL)
    assert listed is not None
    words = dict(re.findall(r'\["([^"]+)", "([^"]+)"\]', listed.group(1)))
    assert words == view.SETUP_PHRASES


def render_trio(page, book):
    """The trio page rendered with the context the build gives every page (the values that do not matter here are placeholders)."""
    from types import SimpleNamespace

    from trioforge.site import build

    return build.make_env().get_template("trio.html.j2").render(
        page_title="t", page_description="d", canonical="https://x/", noindex=False, favicon="data:,",
        assets=SimpleNamespace(css="/a.css", boot="/b.js", app="/c.js"), nav=[],
        meta=SimpleNamespace(data_date="2026-10-14", game_patch="2026-09-22", level=50),
        disclaimer="x", attribution="y", attribution_parts=(("y", None),), licence_sentence="z",
        level_rule=view.rule_ref(book, "level.current"), partial=False, reports_not_open="n", report_url="https://x/", page=page,
    )  # fmt: skip


def test_every_hook_the_browser_code_writes_is_in_the_generated_page():
    """The browser code skips an element it cannot find, so a renamed hook would fail silently: check them here."""
    from types import SimpleNamespace

    from site_helpers import parse

    from trioforge.site import build

    results = data.load_trio(REPO / "fixtures" / "site" / "results" / "pal-mnk-ber")
    book = content.load_rulebook(REPO / "rules" / "rules.json")
    page = view.trio_page(results, book, view.trio_caps(results.meta.trio, results.meta.level, rules_module.load()))
    html = render_trio(page, book)
    root = parse(html)
    source = (STATIC / "trio.js").read_text(encoding="utf-8")
    hooks = set(re.findall(r'(?:setField|field)\([^,]+,\s*"([a-z-]+)"', source)) | set(re.findall(r'"(t-[a-z]+)"', source))
    names = {node.get("data-f") for node in root.iter() if node.has("data-f")}
    # r-name, r-delta and r-deity are made by the code inside each runner-up list item
    assert sorted(h for h in hooks if h not in names and not h.startswith("r-")) == []
    assert {"v-race", "v-role", "v-tier", "v-setup", "assume-buffs", "assume-setup", "assume-haste", "assume-ev", "t-ac", "t-endreg"} <= hooks
    ids = {node.get("id") for node in root.iter() if node.has("id")}
    looked_up = set(re.findall(r"#([a-z][a-z0-9-]*)", source)) | {"runnerups", "robust", "runnerups-na", "robust-na"}
    assert sorted(looked_up - ids) == []
    for name in ("role", "setup", "buffs", "ev"):
        assert root.find_all("input", name=name), name


def test_a_kit_item_that_needs_a_deity_carries_the_badge_in_the_page(tmp_path):
    """Kits leave deity-locked items out, but the table shows the badge if one ever appears in a view."""
    from types import SimpleNamespace

    from site_helpers import parse

    from trioforge.site import build

    results = data.load_trio(REPO / "fixtures" / "site" / "results" / "pal-mnk-ber")
    book = content.load_rulebook(REPO / "rules" / "rules.json")
    scenario = results.shards[("strict", "own")].scenario("OGR", "balanced", 4, "dw")
    locked = dataclasses.replace(scenario.kit[0], deity=("The Tribunal", "Rodcet Nife"))
    rows = view.kit_rows(dataclasses.replace(scenario, kit=(locked, *scenario.kit[1:])))
    assert rows[0].deity == "Needs deity: The Tribunal or Rodcet Nife" and rows[1].deity == ""
    page = view.trio_page(results, book, view.trio_caps(results.meta.trio, results.meta.level, rules_module.load()))
    html = render_trio(dataclasses.replace(page, rows=rows), book)
    badges = [n for n in parse(html).by_id("kit-body").find_all(data_f="deity")]
    assert [b.text() for b in badges if not b.has("hidden")] == ["Needs deity: The Tribunal or Rodcet Nife"]
    assert len(badges) == 22

