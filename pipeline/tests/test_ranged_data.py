"""The site reader holds the bow setup of a bundle to the item table, as it holds the shield setup: a level has the setup for Tank, Melee damage and the Archer when the pool of
that level has a bow for the trio, never for the Shield caster, the Caster tank or the Caster, and the Archer plays the stat stick where the pool has no bow. Every name here is invented."""

from __future__ import annotations

import pytest

from trioforge.site import data

SLUG = "pal-rng-ber"


def bundle_of(**levels):
    """A bundle of a trio with a Ranger and the roles that matter: ``levels`` maps a role to ``(strict, wiki)`` setups."""
    return {
        "trio": ["PAL", "RNG", "BER"],
        "races": [{"code": "HUM"}, {"code": "DEF"}],
        "roles": {role: {"setups": ["dw"], "setups_by_evidence": {"strict": strict, "wiki": wiki}} for role, (strict, wiki) in levels.items()},
    }


def hand_bow(level, **changes):
    record = {
        "id": 71001, "name": "Test Bow", "slots": ["RANGE"], "classes": ["RNG"], "tier_rule": "fixed0", "evidence": {"level": level},
        "weapon": {"skill": "Archery", "dmg": 20, "delay": 40, "bonus": None},
    }
    return {**record, **changes}


def agree(bundle, records):
    file = data._File(SLUG, "engine-l50", bundle)
    data._check_bow_setups(file, bundle, records, SLUG)


ALL_ROLES = {"melee": (["dw"], ["dw", "ranged"]), "tank": (["dw"], ["dw", "ranged"]), "ranged": (["stick"], ["ranged"])}


def test_the_bow_setup_of_a_level_agrees_with_the_bows_of_the_pool_of_that_level():
    agree(bundle_of(**ALL_ROLES), [hand_bow("wiki")])  # a wiki bow: the wiki level has the setup (and the Ranged role has it), the strict level has not
    both = {"melee": (["dw", "ranged"], ["dw", "ranged"]), "ranged": (["ranged"], ["ranged"])}
    agree(bundle_of(**both), [hand_bow("strict")])  # a strict bow is in both pools
    agree(bundle_of(melee=(["dw"], ["dw"]), ranged=(["stick"], ["stick"])), [])  # no bow, no setup, and the Ranged role has the stick
    # what is not in a pool does not count: a hidden bow, a bow only for another class, a deity's bow, a bow that is no good for the best-in-slot lists, a thrown weapon, ammunition
    for other in (
        hand_bow("hidden"), hand_bow("strict", classes=["WIZ"]), hand_bow("strict", deity=["Karana"]),
        hand_bow("strict", evidence={"level": "strict", "codes": ["not-for-bis"]}),
        hand_bow("strict", weapon={"skill": "Throwing", "dmg": 8, "delay": 30, "bonus": None}),
        hand_bow("strict", slots=["AMMO"]), hand_bow("strict", weapon={"skill": "Archery", "dmg": 8, "delay": None, "bonus": None}), hand_bow("strict", weapon=None),
    ):
        agree(bundle_of(melee=(["dw"], ["dw"]), ranged=(["stick"], ["stick"])), [other])
    # a bow that only some races wear may or may not make the setup: the table cannot say which
    agree(bundle_of(melee=(["dw"], ["dw"])), [hand_bow("wiki", races=["DEF"])])
    agree(bundle_of(melee=(["dw"], ["dw", "ranged"])), [hand_bow("wiki", races=["DEF"])])


def test_the_skill_is_read_without_regard_to_case():
    agree(bundle_of(melee=(["dw"], ["dw", "ranged"])), [hand_bow("wiki", weapon={"skill": "archery", "dmg": 20, "delay": 40, "bonus": None})])


def test_a_bundle_that_lacks_the_bow_setup_where_a_bow_of_every_race_is_in_the_pool_is_refused():
    with pytest.raises(data.ResultsError, match=r"engine-l50\.json.*melee.*wiki.*ranged"):
        agree(bundle_of(melee=(["dw"], ["dw"])), [hand_bow("wiki")])
    with pytest.raises(data.ResultsError, match=r"ranged.*strict.*ranged"):
        agree(bundle_of(ranged=(["stick"], ["ranged"])), [hand_bow("strict", races=["ALL"])])
    with pytest.raises(data.ResultsError, match=r"wiki.*ranged"):
        agree(bundle_of(tank=(["dw"], ["dw"])), [hand_bow("wiki", races=["HUM", "DEF"])])  # every race of the bundle


def test_a_bundle_that_lists_the_bow_setup_with_no_bow_in_the_table_is_refused():
    with pytest.raises(data.ResultsError, match=r"melee.*strict.*ranged"):
        agree(bundle_of(melee=(["dw", "ranged"], ["dw", "ranged"])), [hand_bow("wiki")])  # only a wiki bow: the strict pool has none
    with pytest.raises(data.ResultsError, match=r"ranged.*wiki.*ranged"):
        agree(bundle_of(ranged=(["stick"], ["ranged"])), [])


@pytest.mark.parametrize("build", ["shield", "castertank", "caster"])
def test_the_casting_builds_never_have_the_bow_setup(build):
    with pytest.raises(data.ResultsError, match=rf"{build}.*never"):
        agree(bundle_of(**{build: (["stick"], ["stick", "ranged"])}), [hand_bow("wiki")])
    agree(bundle_of(**{build: (["stick"], ["stick"])}), [hand_bow("wiki")])  # a bow in the pool is nothing to the casting builds


@pytest.mark.parametrize("level", ["strict", "wiki"])
@pytest.mark.parametrize("bad", [pytest.param(5, id="a number"), pytest.param({"ranged": 1}, id="an object")])
def test_the_bow_setup_is_looked_for_in_a_list_and_nothing_else(level, bad):
    levels = {"strict": ["dw"], "wiki": ["dw"], level: bad}
    with pytest.raises(data.ResultsError, match=rf"roles\.melee\.setups_by_evidence\.{level}: must be a list"):
        agree(bundle_of(melee=(levels["strict"], levels["wiki"])), [hand_bow("wiki")])
