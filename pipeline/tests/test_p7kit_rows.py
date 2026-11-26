"""The rows of "Wear this" (p7kit): the stats of an item at the tier of the model, the why line, the next best item, and the data that carries them.

``trioforge.site.view`` words the stats from ``at_tier`` (the numbers the solver used) and the why line from ``defaults.json``'s ``why`` and the runner-ups; the
shard carries the stats of every item at each tier of the shard so that the page can show any view. The kit-value side (``kitwhy``) is in ``test_p7kit.py``.
"""

from __future__ import annotations

import dataclasses
import json
import shutil

import pytest

from trioforge import rules as rules_module
from trioforge.export import browser
from trioforge.model.items import at_tier
from trioforge.model.tables import REPO
from trioforge.site import build, content, data, view

RESULTS = REPO / "fixtures" / "site" / "results"
RULES = REPO / "rules" / "rules.json"
MINUS = "−"


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
    w.caps = view.trio_caps(w.results.meta.trio, w.results.meta.level, w.rules)
    w.pages = frozenset(build.item_page_keys(w.table))
    w.page = view.trio_page(w.results, w.book, w.caps, w.pages, w.vecs)
    return w


def model_vec(world, key, tier):
    """The item as the model has it at the tier, made again here from the record (not through view.tier_vecs)."""
    return at_tier(browser.item_to_catalog(world.records[key], world.table["defaults"]), tier, world.rules)


def read_stats(text):
    """The stats line of a row as numbers: ``{"AC": 42, ...}``, the damage as ``(dmg, delay)``, ``bonus`` and the weight in tenths."""
    found = {}
    for part in text.split(", "):
        if part.startswith("Damage "):
            dmg, delay = part.removeprefix("Damage ").split(" ")[0].split("/")
            found["Damage"] = (int(dmg.replace(",", "")), int(delay.replace(",", "")))
            if "(damage bonus " in part:
                found["bonus"] = int(part.split("(damage bonus ")[1].rstrip(")").replace(MINUS, "-").replace(",", ""))
        elif part.startswith("Weight "):
            found["Weight"] = round(float(part.removeprefix("Weight ")) * 10)
        else:
            name, _, amount = part.rpartition(" ")
            found[name] = int(amount.rstrip("%").replace(MINUS, "-").replace("+", "").replace(",", ""))
    return found


def model_numbers(vec):
    names = {"MANA": "Mana", "HPREG": "HP regen", "MANAREG": "Mana regen", "ENDREG": "End regen", "END": "End"}
    school = {"MAGIC": "MR", "FIRE": "FR", "COLD": "CR", "DISEASE": "DR", "POISON": "PR"}
    want = {names.get(key, key): amount for key, amount in vec.stats.items()}
    want.update({school[key]: amount for key, amount in vec.sv.items()})
    if vec.haste:
        want["Haste"] = vec.haste
    if vec.weapon is not None:
        want["Damage"] = (vec.weapon.dmg, vec.weapon.delay)
        if vec.weapon.bonus is not None:
            want["bonus"] = vec.weapon.bonus
    if vec.weight_known:
        want["Weight"] = vec.weight10
    return want


# ---- the stats of a row ----------------------------------------------------------------------------------------------------------------


def test_the_stats_of_a_row_are_the_models_at_the_tier_for_an_armour_piece_and_a_weapon(world):
    d = world.results.defaults
    scenario = world.results.shards[(d.evidence, d.buffs)].scenario(d.race, d.role, d.tier, d.setup)
    checked = {"armour": 0, "weapon": 0}
    for row, item in zip(world.page.rows, scenario.kit):
        if item is None:
            assert row.stats == "" and row.why == ""
            continue
        vec = model_vec(world, item.key, d.tier)
        assert read_stats(row.stats) == model_numbers(vec), (item.key, row.stats)
        checked["weapon" if vec.weapon is not None else "armour"] += 1
    assert checked["armour"] >= 15 and checked["weapon"] >= 2
    helm = next(row for row in world.page.rows if row.name == "Helm of the Stoneward")  # the tier's number, not the base item's
    assert read_stats(helm.stats)["AC"] > world.records["w90001"]["stats"]["AC"]


def test_a_negative_stat_is_shown_with_its_sign_at_the_value_the_model_gives_it(world):
    record = {
        "key": "rnegative", "name": "Anchor Mail", "slots": ["CHEST"], "stats": {"AC": 30, "AGI": -6, "STA": 10}, "weight10": 120, "tier_rule": "drop",
        "evidence": {"level": "strict"}, "source": {},
    }
    vecs = view.tier_vecs({"rnegative": record}, world.table["defaults"], world.rules)
    for tier in (0, 1, 4):  # (T6: a negative stat shrinks toward zero with the tier, -6 to -5 and -2, and is gone at +6: the tiers shown are those where it is still there)
        want = at_tier(browser.item_to_catalog(record, world.table["defaults"]), tier, world.rules)
        text = view.item_stat_text(vecs("rnegative", tier))
        got = read_stats(text)
        assert got["AGI"] == want.stats["AGI"] < 0 and f"AGI {MINUS}{-want.stats['AGI']}" in text
        assert got["AC"] == want.stats["AC"] and got["STA"] == want.stats["STA"] and got["Weight"] == want.weight10


def weapon_record(key, dmg, delay, bonus):
    return {
        "key": key, "name": "Blade", "slots": ["PRIMARY"], "weight10": 30, "tier_rule": "drop", "evidence": {"level": "strict"}, "source": {},
        "weapon": {"skill": "1H Slashing", "dmg": dmg, "delay": delay, "bonus": bonus},
    }


def test_a_weapon_is_damage_over_delay_and_its_listed_bonus_when_it_has_one(world):
    records = {"rblade": weapon_record("rblade", 20, 42, 28), "rdirk": weapon_record("rdirk", 5, 20, None)}
    vecs = view.tier_vecs(records, world.table["defaults"], world.rules)
    tiered = vecs("rblade", 3)
    assert tiered.weapon.dmg > 20 and f"Damage {tiered.weapon.dmg}/42 (damage bonus 28)" in view.item_stat_text(tiered)
    plain = view.item_stat_text(vecs("rdirk", 0))
    assert "Damage 5/20" in plain and "damage bonus" not in plain


# ---- the why line --------------------------------------------------------------------------------------------------------------------------


class Vec:
    """An item as the why line reads it: the figures of its stats."""

    def __init__(self, stats=None, sv=None, haste=0, weapon=None):
        self.stats, self.sv, self.haste, self.weapon = stats or {}, sv or {}, haste, weapon


def swap(name, delta, deity=None):
    return data.Swap(data.Item("w1", name, ("HEAD",), "drop", 4, "x", "strict", deity), delta)


def place(*terms):
    return data.WhyPlace("w90001", tuple(data.WhyTerm(*term) for term in terms))


def test_the_why_names_the_three_largest_losses_the_stats_worth_nothing_and_why():
    vec = Vec({"STA": 18, "HP": 40, "AC": 25, "DEX": 3, "ATK": 9}, {"MAGIC": 10})
    text = view.why_text(
        place(("STA", 214.4, None), ("HP", 120.5, None), ("AC", 61.2, None), ("DEX", 3.0, None), ("MAGIC", 0.0, "resist-cap"), ("ATK", 0.0, None)), vec, [swap("Steel Cap", -35.4)]
    )
    assert text.startswith("Lost without it: STA +18: 214; HP +40: 121; AC +25: 61.")  # three, the largest first, rounded half up as every figure is
    assert "DEX" not in text.split("Worth nothing")[0]
    assert "MR +10 (past the resist cap)" in text and "ATK +9 (not valued in this view)" in text
    assert text.endswith("Next best: Steel Cap, 35 less.")


def test_a_stat_past_its_cap_shows_nothing_lost_and_the_reason():
    text = view.why_text(place(("HASTE", 0.0, "haste-cap"), ("FIRE", 0.0, "resist-cap")), Vec(haste=30, sv={"FIRE": 40}), [])
    assert "Lost without it" not in text
    assert text.startswith("Worth nothing here: Haste +30% (past the haste cap); FR +40 (past the resist cap).")
    assert text.endswith("No close alternative.")


def test_the_next_best_item_is_the_runner_up_for_the_slot(world):
    d = world.results.defaults
    runners = world.results.runnerups.view(d.race, d.role, d.tier)
    assert runners is not None and runners.setup == d.setup
    checked = 0
    for index, row in enumerate(world.page.rows):
        if row.empty:
            continue
        better = next((s for s in runners.slots[index] if s.item.deity is None), None)
        if better is None:
            assert row.why.endswith("No close alternative."), row.name
            continue
        shown = view.display_int(better.delta)
        want = f"Next best: {better.item.name}, {view.fmt_int(abs(shown))} less." if shown < 0 else f"Next best: {better.item.name}, worth the same."
        assert row.why.endswith(want), (row.name, row.why)
        checked += 1
    assert checked >= 10


def test_a_runner_up_that_needs_a_deity_is_not_the_next_best_item():
    locked, plain = swap("Locked Crown", 4.0, ("Karana",)), swap("Plain Cap", -2.0)
    assert view.why_text(place(("HP", 10.0, None)), Vec({"HP": 5}), [locked, plain]).endswith("Next best: Plain Cap, 2 less.")
    assert view.why_text(place(("HP", 10.0, None)), Vec({"HP": 5}), [locked]).endswith("No close alternative.")
    assert view.why_text(place(("HP", 10.0, None)), Vec({"HP": 5}), [swap("Twin", -0.2)]).endswith("Next best: Twin, worth the same.")


def test_a_negative_term_says_what_it_costs():
    text = view.why_text(place(("AC", 40.0, None), ("AGI", -12.4, None)), Vec({"AGI": -6, "AC": 20}), [])
    assert f"Costs: AGI {MINUS}6 takes 12 off." in text and text.startswith("Lost without it: AC +20: 40.")


def test_a_loss_that_rounds_to_nothing_says_under_one_and_not_a_figure_of_zero():
    """E7: every figure of the page is a whole number, so a loss of 0.3 would read "HP +40: 0", which says the stat is worth nothing when it is worth a little."""
    vec = Vec({"STA": 18, "HP": 40, "AGI": -2, "AC": 20})
    text = view.why_text(place(("STA", 214.4, None), ("HP", 0.3, None), ("AC", 0.49, None), ("AGI", -0.2, None)), vec, [])
    assert "HP +40: under 1" in text and "AC +20: under 1" in text and ": 0;" not in text and ": 0." not in text
    assert f"Costs: AGI {MINUS}2 takes under 1 off." in text and " takes 0 off" not in text
    assert text.startswith("Lost without it: STA +18: 214; HP +40: under 1; AC +20: under 1.")
    assert "AC +20: 1" in view.why_text(place(("AC", 0.5, None)), vec, [])  # (half rounds up, as every figure of the page does: a figure of 1)


def test_rows_have_no_stats_and_no_why_when_the_page_is_given_no_figures_or_the_results_have_no_why(world):
    results = world.results
    bare = view.trio_page(results, world.book, world.caps, world.pages)
    assert not bare.kit_stats and all(row.stats == "" and row.why == "" for row in bare.rows)
    old = data.TrioResults(results.meta, results.shards, results.runnerups, results.robust, dataclasses.replace(results.defaults, why=None), results.bundle)
    page = view.trio_page(old, world.book, world.caps, world.pages, world.vecs)
    assert page.kit_stats and not page.kit_why
    assert all(row.stats for row in page.rows if not row.empty) and all(row.why == "" for row in page.rows)


# ---- the data: the reader, and the shard that carries the stats of any view ------------------------------------------------------------------


def edit_defaults(folder, change):
    path = folder / "pal-mnk-ber" / "defaults.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(json.dumps(doc), encoding="utf-8")


def reverse_places(doc):
    doc["why"]["places"].reverse()


def short_places(doc):
    doc["why"]["places"] = doc["why"]["places"][:5]


def set_first(term):
    def change(doc):
        doc["why"]["places"][0]["loss"][0] = term

    return change


def put_first(term):
    def change(doc):
        doc["why"]["places"][0]["loss"].insert(0, term)

    return change


def test_the_reader_takes_results_with_no_why_and_refuses_a_why_that_is_not_well_formed(tmp_path):
    base = tmp_path / "none"
    shutil.copytree(RESULTS, base)
    edit_defaults(base, lambda doc: doc.pop("why"))
    assert data.load_trio(base / "pal-mnk-ber").defaults.why is None
    cases = [
        (short_places, "must have 22 places"),
        (set_first(["STA", 5.0, "resist-cap"]), "reason for a loss that is not 0"),
        (set_first(["LUCK", 5.0, None]), "must be one of"),
        (put_first(["INT", 1.0, None]), "out of order"),
    ]
    for n, (change, message) in enumerate(cases):
        folder = tmp_path / f"case{n}"
        shutil.copytree(RESULTS, folder)
        edit_defaults(folder, change)
        with pytest.raises(data.ResultsError, match=message):
            data.load_trio(folder / "pal-mnk-ber")


def test_the_build_refuses_a_why_that_is_not_of_the_kit_of_the_default_answer(tmp_path):
    folder = tmp_path / "mixed"
    shutil.copytree(RESULTS, folder)
    edit_defaults(folder, reverse_places)
    results = data.load_trio(folder / "pal-mnk-ber")  # (well formed: 22 places, in order, each a stat the item carries or not: the reader cannot know the kit)
    with pytest.raises(build.BuildError, match=r"pal-mnk-ber: defaults.json: why.places\[\d+\] is for w\d+, but the default kit wears .* there: the files are not from one run"):
        build.check_defaults(results)
    build.check_defaults(data.load_trio(RESULTS / "pal-mnk-ber"))  # (the fixture's own why is of its kit)


def test_every_item_of_a_shard_carries_its_stats_at_each_tier_of_the_shard_as_the_row_says_them(world):
    credit = data.Credit("data-2026-10-14", "CC BY-SA 4.0", "x")
    for shard in world.results.shards.values():
        document = json.loads(data.site_shard_json(shard, credit, lambda key, tier: view.item_stat_text(world.vecs(key, tier))))
        assert document["stat_tiers"] == list(shard.tiers) and document["items"]
        for row in document["items"]:
            assert len(row) == 8 and len(row[7]) == len(shard.tiers)
            for tier, text in zip(shard.tiers, row[7]):
                assert read_stats(text) == model_numbers(model_vec(world, row[0], tier))
    plain = json.loads(data.site_shard_json(shard, credit))
    assert "stat_tiers" not in plain and all(len(row) == 7 for row in plain["items"])  # (a shard made without the figures is the shard it was)


def test_the_terms_and_reasons_of_the_reader_are_those_of_the_module_that_writes_them():
    from trioforge.precompute import kitwhy

    assert tuple(data.WHY_TERMS) == tuple(term for term in kitwhy.TERMS if term != "CORRUPTION")
    assert set(data.WHY_REASONS) == set(kitwhy.REASONS) == set(view.WHY_REASON_TEXT)
