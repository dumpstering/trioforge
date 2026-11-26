"""The table of procs in the bundle: the browser's evaluator, model and pruning read the same table the precompute solved with.

``procs`` of a bundle is null for a trio with no proc worth anything, else ``{"socket_tier", "effects", "donors"}`` with the values as reduced ``"p/q"`` texts, the effects by id and the donors
by effect and key, so that the text is the same every time. :func:`trioforge.model.procs.to_doc` writes it and :func:`trioforge.model.procs.from_doc` is the Python reader the browser's port is
held to.
"""

import json
from fractions import Fraction
from pathlib import Path

import pytest
from test_procs_model import blade, donor, effect, table

from trioforge.export import browser
from trioforge.model import procs as procs_module
from trioforge.model.tables import load as load_tables

TRIO = ("PAL", "MNK", "BER")
REPO = Path(__file__).resolve().parents[2]


def sample():
    return table(
        [effect("rare", 900), effect("good", Fraction(1, 3))],
        [donor("rare", "relic", lore=True), donor("rare", "club"), donor("good", "gem", slots=("PRIMARY",), primary_only=True, classes=("WAR", "SHM"))],
        trio=("WAR", "SHM", "ENC"),
        socket=4,
    )


def test_the_document_of_a_table_has_the_values_as_reduced_texts_and_the_donors_in_order():
    doc = procs_module.to_doc(sample())
    assert doc["socket_tier"] == 4
    assert doc["effects"] == [["e-good", "Good", "1/3"], ["e-rare", "Rare", "900/1"]]
    assert doc["donors"] == [
        ["e-good", "gem", ["PRIMARY"], ["SHM", "WAR"], 1, 0],
        ["e-rare", "club", ["PRIMARY", "SECONDARY"], ["ENC", "SHM", "WAR"], 0, 0],
        ["e-rare", "relic", ["PRIMARY", "SECONDARY"], ["ENC", "SHM", "WAR"], 0, 1],
    ]
    assert json.loads(json.dumps(doc)) == doc


def test_the_python_reader_gives_the_table_back_and_the_same_answers():
    original = sample()
    doc = procs_module.to_doc(original)
    again = procs_module.from_doc(doc, ("WAR", "SHM", "ENC"))
    assert again == original
    assert procs_module.to_doc(again) == doc
    for hand in ("PRIMARY", "SECONDARY"):
        assert again.candidates(blade("axe"), hand) == original.candidates(blade("axe"), hand)
    assert again.best(blade("axe"), blade("sword"), Fraction(1, 2)) == original.best(blade("axe"), blade("sword"), Fraction(1, 2))


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(socket_tier=True),
        lambda d: d["effects"][0].__setitem__(2, "0.5"),
        lambda d: d["effects"][0].__setitem__(2, "2/4"),
        lambda d: d["effects"][0].__setitem__(2, "0/1"),
        lambda d: d["donors"][0].__setitem__(0, "e-none"),
        lambda d: d["donors"][0].__setitem__(4, 2),
        lambda d: d["donors"][0].__setitem__(2, "PRIMARY"),
        lambda d: d["effects"].append(d["effects"][0]),
        lambda d: d.update(extra=1),
        lambda d: d.update(effects="e0"),  # (H7: a block whose effects or donors is not a list is no empty table)
        lambda d: d.update(effects={}),
        lambda d: d.update(donors=None),
        lambda d: d.update(donors="w1"),
    ],
)
def test_a_document_that_is_not_what_to_doc_writes_is_refused(change):
    doc = procs_module.to_doc(sample())
    change(doc)
    with pytest.raises(ValueError):
        procs_module.from_doc(doc, ("WAR", "SHM", "ENC"))


def test_a_bundle_carries_the_table_of_its_trio_or_null():
    tables = load_tables()
    spells = json.loads((REPO / "derived" / "client" / "spells-l50.json").read_text(encoding="utf-8"))
    plain = browser.bundle(TRIO, 50, tables, tables.rules, spells, data_release="data-2030-01-02")
    assert plain["procs"] is None
    made = table([effect("rare", 900)], [donor("rare", "relic", classes=TRIO, lore=True)], trio=TRIO)
    with_procs = browser.bundle(TRIO, 50, tables, tables.rules, spells, data_release="data-2030-01-02", procs=made)
    assert with_procs["procs"] == procs_module.to_doc(made)
    assert list(with_procs) == list(browser.BUNDLE_FIELDS) and "procs" in browser.BUNDLE_FIELDS
    assert {key: value for key, value in with_procs.items() if key != "procs"} == {key: value for key, value in plain.items() if key != "procs"}
    with pytest.raises(ValueError, match="procs"):
        browser.bundle(TRIO, 50, tables, tables.rules, spells, procs=table([effect("rare", 900)], [donor("rare", "relic", classes=TRIO)], trio=("WAR", "SHM", "ENC")))


def test_python_reads_a_value_of_any_length_where_the_browser_reads_at_most_sixty_four_digits_in_a_part():
    """H8: the one place the browser's reader (engine/rational.js, MAX_DIGITS) is stricter than this one: a part of a value of more than 64 digits. The exporter writes none (the longest in the full set has
    6 and 13), so the difference is a document that no build makes; tests-js/engine-procs.test.mjs holds the browser's side."""
    doc = procs_module.to_doc(sample())
    doc["effects"][0][2] = "1" + "0" * 69 + "/1"
    assert procs_module.from_doc(doc, ("WAR", "SHM", "ENC")).effects[0].value == 10**69
