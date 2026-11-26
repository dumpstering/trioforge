"""The EQ Legends Tools source (p7nek): the pages of a zone and of its items, fetched politely and read as tooltips.

Nothing here touches the network: the fetch runs on a fake transport, clock and sleep, and the pages are saved copies under
``fixtures/eqlegendstools`` (the zone page of Nektropos Castle, and the item pages of Checkmate and Worn Great Blade).
"""

from __future__ import annotations

import gzip
import json
import urllib.parse
from datetime import date
from pathlib import Path

import pytest

from trioforge.data.normalize import validate_item
from trioforge.sources import eqlegendstools as eqlt
from trioforge.sources.http import FetchError, PoliteClient

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "eqlegendstools"
ZONE = (FIXTURES / "zone-nektropos-castle.html").read_text(encoding="utf-8")
CHECKMATE = (FIXTURES / "item-checkmate.html").read_text(encoding="utf-8")
BLADE = (FIXTURES / "item-worn-great-blade.html").read_text(encoding="utf-8")


# ---- the addresses: the only door a request goes through -------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://eqlegendstools.com/zones/nektropos-castle/",
        "https://eqlegendstools.com/items/checkmate/",
        "https://eqlegendstools.com/items/the-unbreakable-word/",
    ],
)
def test_a_zone_page_and_an_item_page_are_allowed(url):
    assert eqlt.allowed_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://eqlegendstools.com/api/items/",  # robots.txt disallows /api/
        "https://eqlegendstools.com/api/",
        "https://eqlegendstools.com/scripts/app.js",  # ... and /scripts/
        "https://eqlegendstools.com/robots.txt",
        "https://eqlegendstools.com/",
        "https://eqlegendstools.com/items/",
        "https://eqlegendstools.com/zones/",
        "https://eqlegendstools.com/items/checkmate",  # (the trailing slash is part of the address)
        "https://eqlegendstools.com/items/checkmate/?x=1",
        "https://eqlegendstools.com/items/checkmate/#top",
        "https://eqlegendstools.com/items/Checkmate/",
        "https://eqlegendstools.com/items/../api/",
        "https://eqlegendstools.com/items/a/b/",
        "https://eqlegendstools.com/char-sheet/",
        "http://eqlegendstools.com/items/checkmate/",
        "https://www.eqlegendstools.com/items/checkmate/",
        "https://eqlegendstools.com:8443/items/checkmate/",
        "https://user@eqlegendstools.com/items/checkmate/",
        "https://eqlegendstools.com.evil.test/items/checkmate/",
        "https://eqlwiki.com/api.php",
        "ftp://eqlegendstools.com/items/checkmate/",
        "",
    ],
)
def test_nothing_else_is_allowed(url):
    assert not eqlt.allowed_url(url)


def test_the_client_refuses_an_address_the_caller_does_not_allow_and_sends_nothing():
    sent = []
    client = PoliteClient("ua", transport=lambda url, headers: sent.append(url) or (200, {}, b"x"), honour_robots=False)
    with pytest.raises(FetchError, match="address not allowed"):
        eqlt._get(client, "https://eqlegendstools.com/api/items/")
    assert sent == []


def test_a_redirect_is_refused_and_not_retried():
    sent = []

    def transport(url, headers):
        sent.append(url)
        return 302, {"Location": "https://eqlegendstools.com/api/"}, b""

    client = PoliteClient("ua", transport=transport, sleep=lambda s: None, honour_robots=False)
    with pytest.raises(FetchError, match="redirect refused"):
        eqlt._get(client, "https://eqlegendstools.com/items/checkmate/")
    assert sent == ["https://eqlegendstools.com/items/checkmate/"]


# ---- the zone page --------------------------------------------------------------------------------------------------------


def test_the_zone_page_lists_46_items_once_each_in_its_own_order():
    slugs = eqlt.zone_item_slugs(ZONE)
    assert len(slugs) == 46 == len(set(slugs))
    assert slugs[:3] == ["dark-ironbound-tome", "the-unbreakable-word", "worn-great-blade"]
    assert "checkmate" in slugs and "pyrosilk-robe" in slugs
    assert all(eqlt.allowed_url(eqlt.item_url(slug)) for slug in slugs)  # (a link is never followed to a path the site disallows)


def test_a_link_to_another_path_on_the_zone_page_is_not_an_item():
    page = '<a href="/items/ok-one/">a</a><a href="/api/items/x/">b</a><a href="/scripts/x/">c</a><a href="https://elsewhere.test/items/y/">d</a>'
    assert eqlt.zone_item_slugs(page) == ["ok-one"]


# ---- an item page: the tooltip --------------------------------------------------------------------------------------------


def test_checkmate_gives_the_tooltip_the_flags_and_where_it_drops():
    item = eqlt.parse_item_page(CHECKMATE, "checkmate")
    assert item.name == "Checkmate" and item.flags_text == "Attunable" and item.upgrade_level == 0
    assert item.lines == [
        "Slot: EAR",
        "AC: 6 MANA: +5",
        "INT: +5 WIS: +5 CHA: +5",
        "SV MAGIC: +5 SV FIRE: +5",
        "Mana Regen: +2",
        "Focus Effect: Improved Damage III",
        "WT: 0.1 Size: TINY",
        "Class: WAR MNK ROG BER",
    ]
    assert item.drops == [{"zone": "Nektropos Castle", "npcs": ["The Game Master"]}]
    assert item.categories == ["Focus Effect Item", "BiS Gear Item"]


def test_checkmate_is_the_same_shape_of_item_as_a_wiki_item():
    built = eqlt.parse_item_page(CHECKMATE, "checkmate")
    from trioforge.data.eqlt_merge import build_item

    item = build_item(built)
    validate_item(item)
    assert item["slots"] == ["EAR"] and item["classes"] == ["WAR", "MNK", "ROG", "BER"]
    assert item["stats"] == {"AC": 6, "WIS": 5, "INT": 5, "CHA": 5, "MANA": 5, "MANAREG": 2}
    assert item["sv"] == {"FIRE": 5, "MAGIC": 5} and item["flags"] == ["attunable"]
    assert item["weight"] == 0.1 and item["size"] == "TINY"
    assert [(e["kind"], e["name"]) for e in item["effects"]] == [("focus", "Improved Damage III")]
    assert item["sources"]["drops"] == [{"zone": "Nektropos Castle", "npcs": ["The Game Master"]}]
    assert item["parse_warnings"] == [] and item["tier_rule"] == "drop"
    assert item["key"] == "rlt-checkmate" and item["wiki"] is None
    assert item["origin"] == {"source": "eqlegendstools", "slug": "checkmate", "overrides_wiki": False}


def test_a_weapon_has_its_weapon_fields_and_its_two_flags():
    built = eqlt.parse_item_page(BLADE, "worn-great-blade")
    assert built.flags_text == "Lore Equipped, No Trade"  # (the site separates flags with a middle dot; the statsblock with commas)
    assert built.drops == [{"zone": "Nektropos Castle", "npcs": ["C'Rate"]}]
    from trioforge.data.eqlt_merge import build_item

    item = build_item(built)
    validate_item(item)
    assert item["slots"] == ["PRIMARY"] and item["flags"] == ["lore", "no_trade"]
    assert item["weapon"] == {"skill": "2H Slashing", "dmg": 30, "delay": 45, "bonus": 30}
    assert item["stats"] == {"END": 50, "STR": 10, "STA": 10} and item["weight"] == 4.0 and item["size"] == "LARGE"
    assert item["classes"] == ["WAR", "PAL", "SHD", "BER"] and item["parse_warnings"] == []


# ---- what the page leaves out stays unknown ---------------------------------------------------------------------------------


def page_with(lines, flags="", note="Item stats shown at upgrade level 0."):
    items = "".join(f"<li>{line}</li>" for line in lines)
    return (
        '<html><body><main><aside class="tooltip-card"><p class="tooltip-title">Plain Ring</p>'
        f'<p class="tooltip-flags">{flags}</p><ul class="tooltip-lines">{items}</ul>'
        f'<p id="itemUpgradeNote" class="tooltip-upgrade-note">{note}</p></aside></main></body></html>'
    )


def test_a_page_with_no_weight_size_stats_or_level_makes_no_zeros():
    from trioforge.data.eqlt_merge import build_item, stated_fields

    parsed = eqlt.parse_item_page(page_with(["Slot: FINGER", "Class: ALL"]), "plain-ring")
    item = build_item(parsed)
    assert item["weight"] is None and item["size"] is None  # not 0, not MEDIUM
    assert item["stats"] == {} and item["sv"] == {} and item["weapon"] is None
    assert item["required_level"] is None and item["recommended_level"] is None and item["item_type"] is None
    assert item["flags"] == [] and item["sources"]["drops"] == [] and item["tier_rule"] == "fixed0"
    assert stated_fields(parsed) == {"slot", "class"}  # no race, no deity, no type: the page does not show them


def test_a_stat_the_page_shows_as_unknown_is_not_stored_as_zero():
    from trioforge.data.eqlt_merge import build_item

    parsed = eqlt.parse_item_page(page_with(["Slot: FINGER", "AC: ?", "HP: unknown", "WT: ? Size: ?", "Class: ALL"]), "plain-ring")
    item = build_item(parsed)
    assert item["stats"] == {} and item["weight"] is None and item["size"] is None
    assert item["parse_warnings"]  # (the statsblock parser says it could not read them; it does not make a number)


GAMBIT_LINES = ["Slot: PRIMARY", "Skill: 1H Piercing Atk Delay: 20", "DMG: 11 Dmg Bonus: 10", "Effect: Supernova (Combat) at Level 45", "Proc Rate: -75%", "WT: 3.5 Size: SMALL", "Class: ROG"]


def test_a_proc_rate_line_goes_into_the_effect_as_the_wiki_writes_it_and_is_no_unparsed_line():
    from trioforge.data.eqlt_merge import build_item
    from trioforge.effects.donors import parse_raw

    item = build_item(eqlt.parse_item_page(page_with(GAMBIT_LINES), "gamblers-gambit"))
    (effect,) = item["effects"]
    assert (effect["kind"], effect["name"]) == ("proc", "Supernova") and "Rate -75%" in effect["raw"]
    assert not any(w["code"] == "unparsed-line" for w in item["parse_warnings"])
    info = parse_raw(effect["raw"])
    assert info["rate_pct"] == -75 and info["cast_level"] == 45  # (the tooltip's "at Level 45" is a cast level, as on every other tooltip)


def test_a_proc_rate_line_with_no_effect_before_it_is_left_alone_and_a_plus_rate_reads_as_the_wiki_s_plus_rate():
    from trioforge.data.eqlt_merge import build_item
    from trioforge.effects.donors import parse_raw

    alone = build_item(eqlt.parse_item_page(page_with(["Slot: PRIMARY", "Proc Rate: -75%", "Class: ROG"]), "x"))
    assert alone["effects"] == [] and any(w["code"] == "unparsed-line" for w in alone["parse_warnings"])
    plus = build_item(eqlt.parse_item_page(page_with(["Slot: PRIMARY", "Effect: Spirit Strike (Combat) at Level 35", "Proc Rate: +50%", "Class: ROG"]), "y"))
    assert parse_raw(plus["effects"][0]["raw"])["rate_pct"] == 50


def test_a_proc_rate_line_after_an_effect_with_no_bracket_is_read_into_the_same_rate_field():
    from trioforge.data.eqlt_merge import build_item
    from trioforge.effects.donors import parse_raw

    for effect in ("Effect: Frostbite", "Effect: Frostbite at Level 45"):
        item = build_item(eqlt.parse_item_page(page_with(["Slot: PRIMARY", effect, "Proc Rate: -75%", "Class: ROG"]), "z"))
        (found,) = item["effects"]
        assert found["name"] == "Frostbite" and parse_raw(found["raw"])["rate_pct"] == -75, effect
        assert not any(w["code"] == "unparsed-line" for w in item["parse_warnings"]), effect
    unsigned = build_item(eqlt.parse_item_page(page_with(["Slot: PRIMARY", "Effect: Frostbite", "Proc Rate: 50%", "Class: ROG"]), "z"))
    assert parse_raw(unsigned["effects"][0]["raw"])["rate_pct"] == 50


def test_a_proc_rate_line_that_cannot_be_folded_is_never_dropped_silently():
    from trioforge.data.eqlt_merge import build_item

    above = build_item(eqlt.parse_item_page(page_with(["Slot: PRIMARY", "Proc Rate: -75%", "Effect: Frostbite (Combat)", "Class: ROG"]), "z"))
    assert any(w["code"] == "unparsed-line" for w in above["parse_warnings"])  # (the rate line stays a line the parser warns about)


def test_an_item_page_that_shows_another_upgrade_level_is_refused():
    with pytest.raises(eqlt.ParseError, match="upgrade level 3"):
        eqlt.parse_item_page(page_with(["Slot: EAR"], note="Item stats shown at upgrade level 3."), "x")


@pytest.mark.parametrize("page", ["", "<html></html>", "<p>not an item</p>", '<aside class="tooltip-card"></aside>'])
def test_a_page_with_no_tooltip_or_no_name_is_refused(page):
    with pytest.raises(eqlt.ParseError):
        eqlt.parse_item_page(page, "x")


def test_a_script_in_a_page_is_not_read_as_a_tooltip_line():
    page = page_with(["Slot: EAR", "Class: ALL"]).replace("<ul", '<script>document.write("<li>Slot: HEAD</li>")</script><ul')
    assert eqlt.parse_item_page(page, "x").lines == ["Slot: EAR", "Class: ALL"]


def test_the_drop_line_without_a_link_still_gives_the_zone_and_the_creature():
    item = eqlt.parse_item_page(page_with(["Slot: EAR", "Drops From: Some Zone: A Mob, Another Mob"]), "x")
    assert item.drops == [{"zone": "Some Zone", "npcs": ["A Mob", "Another Mob"]}]


# ---- the fetch: pacing, the allow-list, the cache ---------------------------------------------------------------------------


class Site:
    """A fake transport that answers the zone page and the item pages from the fixtures, and keeps the time of each request."""

    def __init__(self):
        self.now = 0.0
        self.calls: list[tuple[float, str]] = []
        self.pages = {eqlt.zone_url("nektropos-castle"): ZONE}
        for slug in eqlt.zone_item_slugs(ZONE):
            self.pages[eqlt.item_url(slug)] = CHECKMATE.replace("Checkmate", slug.title()) if slug != "worn-great-blade" else BLADE

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def __call__(self, url, headers):
        self.calls.append((self.now, url))
        assert headers["User-Agent"] == eqlt.USER_AGENT
        return 200, {}, gzip.compress(self.pages[url].encode("utf-8"))


def fetch(tmp_path, site=None, **kwargs):
    site = site or Site()
    client = PoliteClient(eqlt.USER_AGENT, transport=site, clock=site.clock, sleep=site.sleep, honour_robots=False)
    manifest = eqlt.run_fetch(client, tmp_path / "2026-10-25", date(2026, 10, 25), say=lambda text: None, **kwargs)
    return site, manifest


def test_the_fetch_asks_for_the_zone_and_each_item_once_a_second_and_nothing_else(tmp_path):
    site, manifest = fetch(tmp_path)
    assert manifest["items"] == 46 and len(site.calls) == 47
    assert all(eqlt.allowed_url(url) for _, url in site.calls)
    assert site.calls[0][1] == "https://eqlegendstools.com/zones/nektropos-castle/"
    starts = [start for start, _ in site.calls]
    assert all(later - earlier >= 1.0 for earlier, later in zip(starts, starts[1:]))  # at most one request a second
    paths = {urllib.parse.urlsplit(url).path.split("/")[1] for _, url in site.calls}
    assert paths == {"zones", "items"}


def test_the_user_agent_names_the_project_and_its_about_page():
    assert "TrioForge" in eqlt.USER_AGENT and "(+https://trioforge.pages.dev/about/;" in eqlt.USER_AGENT and "1 request/s" in eqlt.USER_AGENT


def test_a_rerun_of_the_same_folder_fetches_nothing_it_has(tmp_path):
    first, _ = fetch(tmp_path)
    second = Site()
    _, manifest = fetch(tmp_path, second)
    assert second.calls == [] and manifest["items"] == 46
    refreshed = Site()
    fetch(tmp_path, refreshed, refresh=True)
    assert len(refreshed.calls) == 47


def test_a_fetch_that_stopped_halfway_asks_only_for_what_is_missing(tmp_path):
    site, _ = fetch(tmp_path)
    raw = tmp_path / "2026-10-25" / "raw"
    (raw / "item-checkmate.html").unlink()
    (tmp_path / "2026-10-25" / "manifest.json").unlink()
    again = Site()
    fetch(tmp_path, again)
    assert [url for _, url in again.calls] == ["https://eqlegendstools.com/items/checkmate/"]


def test_the_manifest_is_written_last_and_names_the_pages(tmp_path):
    _, manifest = fetch(tmp_path)
    on_disk = json.loads((tmp_path / "2026-10-25" / "manifest.json").read_text(encoding="ascii"))
    assert on_disk == manifest and manifest["date"] == "2026-10-25" and list(manifest["zones"]) == ["nektropos-castle"]
    assert len(manifest["sha256"]) == 64


def test_a_zone_page_that_lists_no_item_is_an_error(tmp_path):
    site = Site()
    site.pages[eqlt.zone_url("nektropos-castle")] = "<html>no items</html>"
    with pytest.raises(FetchError, match="lists no items"):
        fetch(tmp_path, site)


def test_a_finished_fetch_reads_back_as_46_items(tmp_path):
    fetch(tmp_path)
    snapshot = eqlt.read_snapshot(tmp_path / "2026-10-25")
    assert len(snapshot.items) == 46 and snapshot.date == "2026-10-25" and snapshot.zones["nektropos-castle"][0] == "dark-ironbound-tome"


def test_pages_changed_after_the_manifest_was_written_are_refused(tmp_path):
    fetch(tmp_path)
    path = tmp_path / "2026-10-25" / "raw" / "item-checkmate.html"
    path.write_text(path.read_text(encoding="utf-8").replace("WIS: +5", "WIS: +8"), encoding="utf-8")
    with pytest.raises(eqlt.ParseError, match="not the ones the manifest"):
        eqlt.read_snapshot(tmp_path / "2026-10-25")


def test_a_page_sent_with_crlf_line_ends_reads_back_whole_and_a_rerun_gives_the_same_manifest(tmp_path):
    site = Site()
    site.pages[eqlt.item_url("checkmate")] = CHECKMATE.replace("\n", "\r\n")
    assert "\r\n" in site.pages[eqlt.item_url("checkmate")]
    _, manifest = fetch(tmp_path, site)
    snapshot = eqlt.read_snapshot(tmp_path / "2026-10-25")  # (the file is read back with its line ends made LF: the hash must have been made from the same text)
    assert snapshot.sha256 == manifest["sha256"] and len(snapshot.items) == 46
    _, again = fetch(tmp_path, Site())  # (the cached page is read, not fetched: the same text, the same hash)
    assert again["sha256"] == manifest["sha256"]


def test_an_unfinished_fetch_is_refused(tmp_path):
    fetch(tmp_path)
    (tmp_path / "2026-10-25" / "manifest.json").unlink()
    with pytest.raises(eqlt.ParseError, match="manifest.json"):
        eqlt.read_snapshot(tmp_path / "2026-10-25")


def test_the_command_fetches_into_the_folder_and_says_done(tmp_path, capsys, monkeypatch):
    site = Site()
    client = PoliteClient(eqlt.USER_AGENT, transport=site, clock=site.clock, sleep=site.sleep, honour_robots=False)
    monkeypatch.setattr(eqlt, "LOCK_PATH", tmp_path / "lock")
    assert eqlt.main(["fetch", "--out", str(tmp_path / "2026-10-25")], client=client, today=date(2026, 10, 25)) == 0
    assert "done: 46 items" in capsys.readouterr().out and len(site.calls) == 47


def test_the_command_exits_2_when_the_site_stops_answering(tmp_path, capsys, monkeypatch):
    client = PoliteClient(eqlt.USER_AGENT, transport=lambda url, headers: (404, {}, b""), sleep=lambda s: None, honour_robots=False)
    monkeypatch.setattr(eqlt, "LOCK_PATH", tmp_path / "lock")
    assert eqlt.main(["fetch", "--out", str(tmp_path / "x")], client=client) == 2
    assert "error:" in capsys.readouterr().err


# ---- the weekly sources check never asks this site -------------------------------------------------------------------------


def test_the_scheduled_check_does_not_import_or_name_this_source():
    script = (Path(__file__).resolve().parents[2] / "scripts" / "sources_check.py").read_text(encoding="utf-8").lower()
    assert "eqlegendstools" not in script  # (test_sources_check holds the same line: that script asks the wiki and EQL Tools and no one else)


# ---- the normal pipeline fetch picks the source up --------------------------------------------------------------------------


def test_the_wiki_fetch_runs_this_fetch_after_it_when_asked_and_not_otherwise(tmp_path, monkeypatch):
    from trioforge.sources import eqlwiki

    calls = []
    monkeypatch.setattr(eqlwiki, "run_fetch", lambda *args, **kwargs: calls.append("wiki"))
    monkeypatch.setattr(eqlwiki, "LOCK_PATH", tmp_path / "wiki.lock")
    monkeypatch.setattr(eqlt, "main", lambda argv, **kwargs: calls.append(("eqlegendstools", argv)) or 0)
    assert eqlwiki.main(["fetch", "--out", str(tmp_path / "w")], client=object(), today=date(2026, 10, 25)) == 0
    assert calls == ["wiki"]
    assert eqlwiki.main(["fetch", "--out", str(tmp_path / "w"), "--eqlegendstools-out", str(tmp_path / "e")], client=object(), today=date(2026, 10, 25)) == 0
    assert calls[1:] == ["wiki", ("eqlegendstools", ["fetch", "--out", str(tmp_path / "e")])]


# ---- the fix round: a page that cannot be trusted stops the fetch ------------------------------------------------------------


def test_a_page_without_the_upgrade_level_note_is_refused_and_the_error_names_the_page():
    page = page_with(["Slot: EAR", "Class: ALL"]).replace('<p id="itemUpgradeNote" class="tooltip-upgrade-note">Item stats shown at upgrade level 0.</p>', "")
    with pytest.raises(eqlt.ParseError, match=r"plain-ring.*upgrade level"):
        eqlt.parse_item_page(page, "plain-ring")


def test_a_note_that_names_no_level_is_refused():
    with pytest.raises(eqlt.ParseError, match="upgrade level"):
        eqlt.parse_item_page(page_with(["Slot: EAR"], note="Item stats shown."), "x")


def test_the_upgrade_note_of_level_zero_is_accepted_and_another_level_names_the_page():
    assert eqlt.parse_item_page(page_with(["Slot: EAR"]), "x").upgrade_level == 0
    with pytest.raises(eqlt.ParseError, match=r"x.*level 2"):
        eqlt.parse_item_page(page_with(["Slot: EAR"], note="Item stats shown at upgrade level 2."), "x")


def test_a_zone_page_with_no_item_link_is_not_written_to_the_cache(tmp_path):
    site = Site()
    site.pages[eqlt.zone_url("nektropos-castle")] = "<html>no items</html>"
    with pytest.raises(FetchError, match="lists no items"):
        fetch(tmp_path, site)
    assert not (tmp_path / "2026-10-25" / "raw" / "zone-nektropos-castle.html").exists()
    assert not (tmp_path / "2026-10-25" / "manifest.json").exists()


def test_an_item_page_that_cannot_be_read_stops_the_fetch_before_it_is_cached_and_no_manifest_is_written(tmp_path):
    site = Site()
    site.pages[eqlt.item_url("checkmate")] = "<html><body>maintenance</body></html>"
    with pytest.raises(eqlt.ParseError, match="checkmate"):
        fetch(tmp_path, site)
    folder = tmp_path / "2026-10-25"
    assert not (folder / "manifest.json").exists() and not (folder / "raw" / "item-checkmate.html").exists()


def test_the_command_exits_2_for_a_page_that_cannot_be_read(tmp_path, capsys, monkeypatch):
    site = Site()
    site.pages[eqlt.item_url("checkmate")] = "<html></html>"
    client = PoliteClient(eqlt.USER_AGENT, transport=site, clock=site.clock, sleep=site.sleep, honour_robots=False)
    monkeypatch.setattr(eqlt, "LOCK_PATH", tmp_path / "lock")
    assert eqlt.main(["fetch", "--out", str(tmp_path / "2026-10-25")], client=client) == 2
    assert "checkmate" in capsys.readouterr().err and not (tmp_path / "2026-10-25" / "manifest.json").exists()
