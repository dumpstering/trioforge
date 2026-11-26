"""Tests for the crafting lists of an item page, as the wiki really writes them.

A "Player crafted" list on a real page is a list of recipes: a trade skill line, the yield, the
container (an "In ..." line) and the ingredients ("N x [[Name]] - how to get it"). The plainer
outline that test_itempage.py uses (a container, then its ingredients one level deeper) must keep
working too. Every name here is invented.
"""

import json
import time
from pathlib import Path

import pytest

from trioforge.sources.eqlwiki import fixture_slug, page_records
from trioforge.sources.itempage import ParsedPage, parse_page

FIXTURES = Path(__file__).resolve().parents[1].parent / "fixtures" / "wiki"


def template(**params):
    body = "".join(f"|{name}={value}\n" for name, value in params.items())
    return "{{Itempage\n" + body + "}}"


def parse(content):
    return parse_page({"pageid": 7, "ns": 0, "title": "Zorblax Ring", "revid": 70, "content": content})


def fixture(title):
    """The fetch_pages-style record of a recorded page (real eqlwiki text, see fixtures/wiki/README.md)."""
    path = FIXTURES / f"{fixture_slug(title)}.json"
    (record,) = page_records(json.loads(path.read_text(encoding="utf-8")))
    return record


def parsed_fixture(title):
    result = parse_page(fixture(title))
    assert isinstance(result, ParsedPage), result
    return result


def parsed(statsblock="Slot: EAR", **params):
    result = parse(template(itemname="Zorblax Ring", statsblock=statsblock, **params))
    assert isinstance(result, ParsedPage), result
    return result


RECIPE = (
    "\n"
    "* [[Blacksmithing]] (Trivial: 148)\n"
    "** '''Yield: Zorblax Gloves''' x1\n"
    "** In [[Forge|Zorblax Forge]]:\n"
    ":: {{SmIcon|504}} 1 x [[Zorblax Pattern]] - Bought\n"
    ":: {{SmIcon|1032}} 2 x [[Quuxen Rings]] - Crafted\n"
    ":: {{SmIcon|567}} 1 x [[Zorblax Hammer]] - Bought, Returned on Failure, Returned on Success\n"
    "\n"
    "* [[Pottery]] (Trivial: 115/17)\n"
    "** '''Yield: Zorblax Gloves''' x1\n"
    "** In [[Kiln]]:\n"
    "**: {{SmIcon|1036}} 1 x [[Blarg Sheet]] - Bought\n"
    "**: {{SmIcon|858}} 1 x [[Unfired Zorblax]] - Crafted\n"
)


def test_a_real_recipe_list_gives_each_container_with_its_ingredients():
    assert parsed(playercrafted=RECIPE).crafted == [
        {"container": "Zorblax Forge", "ingredients": ["Zorblax Pattern", "Quuxen Rings", "Zorblax Hammer"]},
        {"container": "Kiln", "ingredients": ["Blarg Sheet", "Unfired Zorblax"]},
    ]


def test_the_trade_skill_is_never_a_container_or_an_ingredient():
    flat = json.dumps(parsed(playercrafted=RECIPE).crafted)
    assert "Blacksmithing" not in flat and "Pottery" not in flat and "Yield" not in flat


def test_a_container_given_as_a_label_keeps_the_label_so_a_cultural_forge_shows():
    crafted = "* [[Tailoring]]\n** In [[Sewing Kit|Zorblax Sewing Kit]]:\n:: 1 x [[Quuxen Silk]] - Bought\n"
    assert parsed(playercrafted=crafted).crafted == [
        {"container": "Zorblax Sewing Kit", "ingredients": ["Quuxen Silk"]}
    ]


def test_ingredients_are_named_by_the_page_not_by_the_label():
    crafted = "* [[Tailoring]]\n** In [[Loom]]:\n:: 1 x [[Silk Swatch|Silk Swatches]] - Crafted\n"
    assert parsed(playercrafted=crafted).crafted == [{"container": "Loom", "ingredients": ["Silk Swatch"]}]


@pytest.mark.parametrize(
    "line", ["In [[Loom]] or [[Sewing Kit]]:", "In [[Loom]], [[Sewing Kit]]:", "In: [[Loom]], [[Sewing Kit]]"]
)
def test_several_containers_on_one_line_each_get_the_recipe(line):
    crafted = f"* [[Tailoring]]\n** {line}\n:: 1 x [[Quuxen Silk]] - Bought\n"
    assert parsed(playercrafted=crafted).crafted == [
        {"container": "Loom", "ingredients": ["Quuxen Silk"]},
        {"container": "Sewing Kit", "ingredients": ["Quuxen Silk"]},
    ]


@pytest.mark.parametrize(
    "line",
    [
        "** In [[Zorblax Bag]]:",
        ": In [[Zorblax Bag]]:",
        ":In: [[Zorblax Bag]]",
        "** In: [[Zorblax Bag]]",
        "** In {{SmIcon|836}} [[Zorblax Bag]]:",
        "**    IN   [[Zorblax Bag]]   :",
    ],
)
def test_the_container_line_may_be_written_in_the_ways_the_wiki_does(line):
    crafted = f"* [[Baking]]\n{line}\n:: 1 x [[Quuxen Flour]] - Bought\n"
    assert parsed(playercrafted=crafted).crafted == [{"container": "Zorblax Bag", "ingredients": ["Quuxen Flour"]}]


@pytest.mark.parametrize("prefix", [":: ", "**: ", "::: ", ":*", "*** ", "::*"])
def test_the_ingredient_line_may_be_indented_in_the_ways_the_wiki_does(prefix):
    crafted = f"* [[Baking]]\n** In [[Oven]]:\n{prefix}{{{{SmIcon|9}}}} 3 x [[Quuxen Flour]] - Bought (Yield: x10)\n"
    assert parsed(playercrafted=crafted).crafted == [{"container": "Oven", "ingredients": ["Quuxen Flour"]}]


def test_ingredient_quantities_may_be_written_without_spaces():
    crafted = "* [[Baking]]\n** In [[Oven]]:\n:: 3x [[Quuxen Flour]]\n:: 12 x[[Blarg Salt]]\n"
    assert parsed(playercrafted=crafted).crafted == [
        {"container": "Oven", "ingredients": ["Quuxen Flour", "Blarg Salt"]}
    ]


def test_a_second_container_line_after_ingredients_starts_another_recipe():
    crafted = (
        "* [[Blacksmithing]]\n"
        "** In [[Forge]]:\n:: 1 x [[Ore One]]\n"
        "** In [[Forge|Zorblax Forge]]:\n:: 1 x [[Ore Two]]\n"
    )
    assert parsed(playercrafted=crafted).crafted == [
        {"container": "Forge", "ingredients": ["Ore One"]},
        {"container": "Zorblax Forge", "ingredients": ["Ore Two"]},
    ]


def test_container_lines_in_a_row_are_alternatives_for_the_same_ingredients():
    crafted = "* [[Brewing]]\n** In [[Barrel]]:\n** In [[Cask]]:\n:: 1 x [[Quuxen Hops]]\n"
    assert parsed(playercrafted=crafted).crafted == [
        {"container": "Barrel", "ingredients": ["Quuxen Hops"]},
        {"container": "Cask", "ingredients": ["Quuxen Hops"]},
    ]


def test_a_recipe_with_a_skill_and_nothing_else_is_craftable_in_an_unknown_container():
    assert parsed(playercrafted="\n* [[Skill Tailoring|Tailoring]] (Trivial: 26)\n\n").crafted == [
        {"container": None, "ingredients": []}
    ]
    assert parsed(playercrafted="[[Fletching]]").crafted == [{"container": None, "ingredients": []}]


def test_a_recipe_without_a_container_line_has_no_container():
    crafted = "* [[Alchemy]]\n** [[5 Dose Zorblax Potion]]\n"
    assert parsed(playercrafted=crafted).crafted == [{"container": None, "ingredients": ["5 Dose Zorblax Potion"]}]


@pytest.mark.parametrize(
    "crafted",
    [
        "* Non-Tradeskill (Intermediate Quest Result)",
        "* [[Non-Tradeskill]] (Trivial: No-Fail)",
        "* [[Non-Tradeskill]]\n* Confirmed to NOT work\n* These work (Confirmed in EQ Legends):",
        "* [[Non-Tradeskill]]\n:::*''On Failure Returns: ''[[File]] , [[Zorblax Hammer]]",
        "* [[Non-Tradeskill]]\n'''Note: another site has a different recipe so this page may need correction!'''",
    ],
)
def test_lines_that_are_no_recipe_make_no_recipe(crafted):
    assert parsed(playercrafted=crafted).crafted == []


def test_a_container_that_is_just_the_word_none_is_no_container():
    assert parsed(crafted="None\n* [[Zorblax Ore]]").crafted == [{"container": None, "ingredients": ["Zorblax Ore"]}]
    assert parsed(playercrafted="* [[Baking]]\n** In: None\n:: 1 x [[Quuxen Flour]]\n").crafted == [
        {"container": None, "ingredients": ["Quuxen Flour"]}
    ]


def test_a_non_tradeskill_combine_keeps_its_container_and_ingredients():
    crafted = (
        "* [[Non-Tradeskill]] (Trivial: No-Fail)\n** In [[Zorblax Box]]:\n"
        ":: 1 x [[Quuxen Key]]\n:: 1 x [[Blarg Key]]\n"
    )
    assert parsed(playercrafted=crafted).crafted == [
        {"container": "Zorblax Box", "ingredients": ["Quuxen Key", "Blarg Key"]}
    ]


def test_failure_and_return_lines_are_not_ingredients():
    crafted = (
        "* [[Smithing]]\n** In [[Forge]]:\n:: 1 x [[Ore One]]\n"
        ":::*''On Failure Returns: ''[[Ore One]]\n:: '''Returns [[Bottle]] x4 upon success'''\n"
    )
    assert parsed(playercrafted=crafted).crafted == [{"container": "Forge", "ingredients": ["Ore One"]}]


def test_a_yield_line_with_a_linked_item_is_not_an_ingredient():
    """``Yield: 1 x [[Name]]`` has a quantity and a link, so it read as an ingredient, and before the container line it made a recipe of the item itself with no container."""
    crafted = "* [[Brewing]]\n** Yield: 1 x [[Zorblax Brew]]\n** In [[Brewing Barrel]]:\n:: 2 x [[Water Flask]]\n"
    assert parsed(playercrafted=crafted).crafted == [{"container": "Brewing Barrel", "ingredients": ["Water Flask"]}]
    bold = "'" * 3
    for line in (f"{bold}Yield: 1 x [[Zorblax Brew]]{bold}", "''Yields 1 x [[Zorblax Brew]]''", "yield: 3 x [[Zorblax Brew]]"):
        again = f"* [[Brewing]]\n** {line}\n** In [[Brewing Barrel]]:\n:: 2 x [[Water Flask]]\n"
        assert parsed(playercrafted=again).crafted == [{"container": "Brewing Barrel", "ingredients": ["Water Flask"]}], line


def test_an_on_failure_line_with_a_quantity_after_a_container_is_not_an_ingredient():
    for line in ("On Failure Returns: 1 x [[Zorblax Hammer]]", "''On Failure: ''1 x [[Zorblax Hammer]]", "Returns 1 x [[Zorblax Hammer]] upon success"):
        crafted = f"* [[Smithing]]\n** In [[Forge]]:\n:: 1 x [[Ore One]]\n:: {line}\n"
        assert parsed(playercrafted=crafted).crafted == [{"container": "Forge", "ingredients": ["Ore One"]}], line


def test_a_note_at_the_end_of_an_ingredient_line_does_not_make_it_a_return_or_a_yield():
    crafted = "* [[Smithing]]\n** In [[Forge]]:\n:: 1 x [[Zorblax Hammer]] - Bought, Returned on Failure\n:: 2 x [[Ore One]] (yields well)\n:: 1 x [[Returns Ring]]\n"
    assert parsed(playercrafted=crafted).crafted == [{"container": "Forge", "ingredients": ["Zorblax Hammer", "Ore One", "Returns Ring"]}]


def test_alternative_ingredients_under_one_of_are_all_kept():
    crafted = "* [[Baking]]\n** In [[Oven]]:\n::* One of:\n::: 1 x [[Rice]]\n::: 1 x [[Wheat]]\n"
    assert parsed(playercrafted=crafted).crafted == [{"container": "Oven", "ingredients": ["Rice", "Wheat"]}]


def test_a_combine_sentence_names_the_ingredient_and_the_container():
    crafted = "Combine 10 [[Zorblax Potion]] in a [[Bearskin Bag]]"
    assert parsed(playercrafted=crafted).crafted == [{"container": "Bearskin Bag", "ingredients": ["Zorblax Potion"]}]


def test_a_container_line_without_a_link_gives_the_plain_names():
    crafted = "* [[Baking]]\n** In: Oven or Spit\n:: 1 x [[Quuxen Flour]]\n"
    assert parsed(playercrafted=crafted).crafted == [
        {"container": "Oven", "ingredients": ["Quuxen Flour"]},
        {"container": "Spit", "ingredients": ["Quuxen Flour"]},
    ]


def test_a_word_that_only_starts_with_in_is_not_a_container_line():
    # "Inn" is not "In": the plain outline rules apply to this list.
    assert parsed(crafted="Inn Kit\n* [[Zorblax Ore]]").crafted == [
        {"container": "Inn Kit", "ingredients": ["Zorblax Ore"]}
    ]


def test_the_crafting_section_of_a_page_may_use_the_real_layout_too():
    code = (
        template(itemname="Zorblax Ring", statsblock="Slot: EAR")
        + "\n== Player crafted ==\n* [[Jewelry Making]] (Trivial: 100)\n** In [[Jeweler's Kit]]:\n"
        + ":: 1 x [[Blue Zorblax]] - Dropped\n== See also ==\n* [[Not an ingredient]]\n"
    )
    assert parse(code).crafted == [{"container": "Jeweler's Kit", "ingredients": ["Blue Zorblax"]}]


def test_the_used_in_list_is_still_not_a_recipe():
    recipes = "* [[Blacksmithing]]\n** In [[Forge]]:\n:: 1 x [[Ore One]]\n"
    assert parsed(recipes=recipes).crafted == []


# One line of up to 50,000 characters: a page over 60,000 is skipped before it is read at all.
HUGE_LINES = {
    "digits": lambda: "1" * 50_000,
    "open paren and spaces": lambda: "(" + " " * 50_000 + "x",
    "many containers": lambda: "In " + "[[a]] or " * 5000,
    "quantities": lambda: "1 x " * 12_000,
}


@pytest.mark.parametrize("name", sorted(HUGE_LINES))
def test_a_huge_single_line_of_crafting_text_is_read_in_reasonable_time(name):
    start = time.perf_counter()
    result = parsed(playercrafted="* [[Tailoring]]\n" + HUGE_LINES[name]() + "\n")
    assert time.perf_counter() - start < 5
    for craft in result.crafted:
        assert craft["container"] is None or craft["container"]
        assert all(craft["ingredients"])


def test_links_in_a_row_are_alternatives_but_words_between_links_end_the_list():
    crafted = (
        "* [[Non-Tradeskill]]\n** In [[Pottery Wheel]] located inside the [[Zorblax Jail]] at (-198, 1113):\n"
        ":: 1 x [[Quuxen Clay]]\n"
    )
    assert parsed(playercrafted=crafted).crafted == [{"container": "Pottery Wheel", "ingredients": ["Quuxen Clay"]}]
    crafted = "* [[Non-Tradeskill]]\n** In [[Tome Binder]] Dropped by [[an orc]]:\n:: 1 x [[Quuxen Page]]\n"
    assert parsed(playercrafted=crafted).crafted == [{"container": "Tome Binder", "ingredients": ["Quuxen Page"]}]
    crafted = "* [[Brewing]]\n** In [[Barrel]] and [[Cask]] or [[Keg]]:\n:: 1 x [[Quuxen Hops]]\n"
    assert [c["container"] for c in parsed(playercrafted=crafted).crafted] == ["Barrel", "Cask", "Keg"]


def test_a_combine_sentence_after_a_skill_line_is_that_skills_recipe():
    crafted = "* [[Alchemy]]\nCombine 10 [[Zorblax Potion]] in a [[Bearskin Bag]]\n"
    assert parsed(playercrafted=crafted).crafted == [{"container": "Bearskin Bag", "ingredients": ["Zorblax Potion"]}]


# ---- real pages --------------------------------------------------------------------------------------------
# Recorded from eqlwiki (fixtures/wiki/README.md): the layouts above as they are really written.


def test_banded_belt_is_made_in_a_plain_forge_from_three_ingredients():
    result = parsed_fixture("Banded Belt")
    assert result.crafted == [
        {"container": "Forge", "ingredients": ["Belt Sectional Mold", "Sheet Metal", "Water Flask"]}
    ]


def test_ogre_bouncer_shield_is_made_in_the_oggok_forge_the_label_of_the_forge_link():
    result = parsed_fixture("Ogre Bouncer Shield")
    assert result.crafted == [
        {
            "container": "Oggok Forge",
            "ingredients": ["Blood Temper", "Sheet of Adamantite", "Round Shield Mold", "Smithy Hammer"],
        }
    ]


def test_block_of_adamantite_has_a_recipe_for_each_of_two_cultural_forges():
    result = parsed_fixture("Block of Adamantite")
    assert result.crafted == [
        {"container": "Teir`dal Forge", "ingredients": ["Neriak Nectar", "Large Brick of Adamantite"]},
        {"container": "Oggok Forge", "ingredients": ["Ogre Swill", "Large Brick of Adamantite"]},
    ]
    assert len(result.sold_by) == 4  # the vendor rows beside it are still read


def test_crystalline_silk_cloak_names_three_containers_on_one_colon_line():
    result = parsed_fixture("Crystalline Silk Cloak")
    ingredients = ["Cloak Pattern", "Silver Thread", "Crystalline Silk Swatch"]
    assert result.crafted == [
        {"container": "Deluxe Sewing Kit", "ingredients": ingredients},
        {"container": "Large Sewing Kit", "ingredients": ingredients},
        {"container": "Loom", "ingredients": ingredients},
    ]


def test_large_patchwork_cloak_has_a_skill_and_no_container():
    assert parsed_fixture("Large Patchwork Cloak").crafted == [{"container": None, "ingredients": []}]


def test_a_combine_sentence_on_a_real_page():
    assert parsed_fixture("10 Dose Greater Null Potion").crafted == [
        {"container": "Bearskin Potion Bag", "ingredients": ["Greater Null Potion"]}
    ]


def test_a_non_tradeskill_note_on_a_real_page_is_no_recipe():
    assert parsed_fixture("Air Tight Box").crafted == []


CRAFT_FIXTURES = [
    "Banded Belt",
    "Ogre Bouncer Shield",
    "Block of Adamantite",
    "Crystalline Silk Cloak",
    "Large Patchwork Cloak",
    "10 Dose Greater Null Potion",
    "Air Tight Box",
]


@pytest.mark.parametrize("title", CRAFT_FIXTURES)
def test_no_recorded_recipe_has_a_skill_a_yield_or_a_note_as_container_or_ingredient(title):
    for craft in parsed_fixture(title).crafted:
        names = [craft["container"] or "", *craft["ingredients"]]
        for name in names:
            assert name == name.strip() and "Yield" not in name and "Trivial" not in name
            assert name.casefold() not in {"blacksmithing", "pottery", "tailoring", "alchemy", "non-tradeskill"}
