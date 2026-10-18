"""Tests for model JSON v1: ``trioforge.export.milp_json``.

The browser engine builds the same MILP as the Python builder and is held to it by a parity test, so the model has a plain
data form both sides can write and read: the columns and rows in the builder's exact order with their names, the matrix in
compressed row form, the bounds with ``null`` for an infinite one, and the columns that carry items and buffs. This module
turns a :class:`trioforge.solver.model.Milp` into that document (``to_dict``), into its canonical text (``to_json``) and back
(``loads``), checks a document's structure (``validate``) and compares two documents by the parity rules (``compare``):

* column names, integrality and the row set are identical, in identical order;
* coefficients and bounds agree within ``|a - b| <= 1e-12 * max(1, |a|, |b|)``, and an infinite bound agrees only with an
  infinite one (``null`` is never within a tolerance of a number).

Every name here is invented.
"""

import copy
import json
import math
import random
from pathlib import Path

import numpy as np
import pytest

import solver_helpers as H
import upgrade_helpers as U
from solver_helpers import make_item
from trioforge.export import milp_json as MJ
from trioforge.solver._highs import run_arrays
from trioforge.solver.model import BuildOptions, build_milp

KEYS = [
    "version", "sense", "const", "col_names", "col_lb", "col_ub", "integrality", "c", "row_names", "row_lb", "row_ub", "A",
    "item_cols", "buff_cols", "info",
]
TRIO = ("PAL", "MNK", "BER")


def small_model(seed=3):
    inst = H.random_instance(random.Random(seed))
    return build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst))


def owned_model(seed=5):
    inst, caps, news, ups, max_new = U.ownership_case(seed)
    return build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst, caps, news, ups, max_new))


def prunable_model(seed):
    inst, caps, news, ups, max_new = U.ownership_case(seed, pool="prunable")
    return build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst, caps, news, ups, max_new))


def doc(milp):
    return MJ.to_dict(milp)


def problems(document):
    return MJ.validate(document)


# ---- the document ------------------------------------------------------------------------------------------------------------


def test_the_document_has_the_fields_of_the_plan_in_the_order_of_the_plan():
    document = doc(small_model())
    assert list(document) == KEYS
    assert document["version"] == 1 and document["sense"] == "max"
    assert list(document["A"]) == ["start", "index", "value"]
    assert isinstance(document["const"], float) and isinstance(document["info"], dict)


def test_the_arrays_are_the_models_in_the_builders_order():
    milp = small_model()
    document = doc(milp)
    assert document["col_names"] == milp.names and document["row_names"] == milp.row_names
    assert document["integrality"] == [int(v) for v in milp.integrality] and set(document["integrality"]) <= {0, 1}
    assert document["c"] == [float(v) for v in milp.c] and document["const"] == milp.const
    assert document["A"]["start"] == milp.A.start.tolist() and document["A"]["index"] == milp.A.index.tolist()
    assert document["A"]["value"] == milp.A.value.tolist()
    assert document["item_cols"] == [[col, group, item.key, item.tier] for col, group, item in milp.item_cols]
    assert document["buff_cols"] == [[col, bid] for col, bid in sorted(milp.buff_cols.items())]
    assert len(document["col_lb"]) == len(document["col_ub"]) == len(document["c"]) == milp.num_cols
    assert len(document["row_lb"]) == len(document["row_ub"]) == len(document["row_names"]) == milp.num_rows


def test_an_infinite_bound_is_null_and_a_finite_one_is_a_number():
    saw_free_column = saw_open_row = False
    for seed in range(10):
        milp = small_model(seed)
        document = doc(milp)
        for key, array in (("col_lb", milp.col_lb), ("col_ub", milp.col_ub), ("row_lb", milp.row_lb), ("row_ub", milp.row_ub)):
            want = [None if math.isinf(v) else float(v) for v in array]
            assert document[key] == want, (seed, key)
        saw_free_column |= None in document["col_lb"] or None in document["col_ub"]
        saw_open_row |= None in document["row_lb"] or None in document["row_ub"]
    assert saw_free_column and saw_open_row


def test_the_info_is_plain_data_and_carries_the_counts():
    milp = small_model()
    info = doc(milp)["info"]
    assert info["rows"] == milp.num_rows and info["cols"] == milp.num_cols and info["haste_assumed"] == milp.haste_assumed
    assert json.loads(json.dumps(info)) == info  # nothing in it but JSON data
    assert list(info) == sorted(info)  # the same order whatever the order the builder filled it in


def test_the_options_of_the_owned_items_show_in_the_rows_and_columns_of_the_document():
    document = doc(owned_model())
    assert any(name.startswith("own.") for name in document["row_names"]) or any(n == "new.limit" for n in document["row_names"])
    assert problems(document) == []


# ---- the text --------------------------------------------------------------------------------------------------------------


def test_to_json_is_the_canonical_text_that_reads_back_to_the_document_and_writes_back_to_the_same_text():
    for seed in range(8):
        milp = small_model(seed)
        text = MJ.to_json(milp)
        assert isinstance(text, str) and text.isascii() and "\n" not in text and ": " not in text and ", " not in text
        assert MJ.loads(text) == doc(milp), seed
        assert MJ.dumps(MJ.loads(text)) == text, seed
        assert MJ.to_json(milp) == text and MJ.to_json(small_model(seed)) == text, seed  # the same on every build
        json.loads(text, parse_constant=lambda name: pytest.fail(name))  # no NaN or Infinity anywhere


def test_the_text_does_not_depend_on_the_order_of_the_pool_or_the_owned_mapping():
    inst, caps, news, ups, max_new = U.ownership_case(7)
    texts = set()
    for order in range(3):
        items = list(inst.items)
        random.Random(order).shuffle(items)
        owned = dict(sorted(caps.items(), reverse=bool(order % 2)))
        milp = build_milp(inst.profile, items, inst.setup, inst.buffset, U.options_of(inst, owned, news, ups, max_new))
        texts.add(MJ.to_json(milp))
    assert len(texts) == 1


def test_a_negative_zero_is_written_as_zero_so_the_text_is_stable():
    milp = small_model()
    milp.c[0] = -0.0
    milp.col_lb[0] = -0.0
    document = doc(milp)
    assert document["c"][0] == 0.0 and math.copysign(1.0, document["c"][0]) == 1.0
    assert math.copysign(1.0, document["col_lb"][0]) == 1.0
    back = json.loads(MJ.to_json(milp))
    assert math.copysign(1.0, back["c"][0]) == 1.0 and math.copysign(1.0, back["col_lb"][0]) == 1.0


def test_a_model_with_a_value_that_is_not_a_finite_number_is_refused_not_written():
    for where in ("c", "A", "const"):
        milp = small_model()
        if where == "c":
            milp.c[0] = math.nan
        elif where == "A":
            milp.A.value[0] = math.inf
        else:
            milp.const = math.inf
        with pytest.raises(ValueError):
            MJ.to_dict(milp)


def test_the_model_of_the_document_solves_to_the_optimum_of_the_model():
    for seed in range(6):
        milp = small_model(seed)
        document = MJ.loads(MJ.to_json(milp))
        inf = math.inf
        res = run_arrays(
            np.array(document["c"]), np.array(document["A"]["start"], dtype=np.int32), np.array(document["A"]["index"], dtype=np.int32),
            np.array(document["A"]["value"]), np.array([-inf if v is None else v for v in document["row_lb"]]),
            np.array([inf if v is None else v for v in document["row_ub"]]), np.array([-inf if v is None else v for v in document["col_lb"]]),
            np.array([inf if v is None else v for v in document["col_ub"]]), np.array(document["integrality"], dtype=np.int8),
        )
        from trioforge.solver._highs import solve_milp

        want = solve_milp(milp)
        assert res.status == want.status == "optimal"
        assert abs((document["const"] + res.objective) - (milp.const + want.objective)) <= 1e-9 * max(1.0, abs(milp.const))


# ---- reading text strictly ------------------------------------------------------------------------------------------------


def test_loads_refuses_text_that_is_not_a_model():
    good = MJ.to_json(small_model())
    document = json.loads(good)
    cases = {
        "not json": "{",
        "an array": "[]",
        "a number": "1",
        "a duplicate key": good.replace('{"version":1,', '{"version":1,"version":1,', 1),
        "NaN": good.replace('"const":', '"const":NaN,"x":', 1),
        "Infinity": good.replace('"const":', '"const":Infinity,"x":', 1),
        "another version": json.dumps({**document, "version": 2}),
        "no version": json.dumps({k: v for k, v in document.items() if k != "version"}),
        "a missing field": json.dumps({k: v for k, v in document.items() if k != "row_names"}),
        "an unknown field": json.dumps({**document, "extra": 1}),
        "short names": json.dumps({**document, "col_names": document["col_names"][:-1]}),
    }
    for label, text in cases.items():
        with pytest.raises(ValueError):
            MJ.loads(text)
        assert label


def test_validate_reports_each_structural_fault():
    base = doc(small_model())

    def broken(mutate):
        document = copy.deepcopy(base)
        mutate(document)
        return MJ.validate(document)

    assert MJ.validate(base) == []
    assert broken(lambda d: d["col_lb"].pop())
    assert broken(lambda d: d["row_ub"].append(1.0))
    assert broken(lambda d: d["A"]["start"].__setitem__(0, 1))
    assert broken(lambda d: d["A"]["start"].__setitem__(1, d["A"]["start"][-1] + 1))  # not monotone
    assert broken(lambda d: d["A"]["index"].__setitem__(0, len(d["col_names"])))  # a column that does not exist
    assert broken(lambda d: d["A"]["value"].pop())
    assert broken(lambda d: d["col_names"].__setitem__(1, d["col_names"][0]))  # a name twice
    assert broken(lambda d: d["row_names"].__setitem__(1, d["row_names"][0]))
    assert broken(lambda d: d["col_lb"].__setitem__(0, 5.0) or d["col_ub"].__setitem__(0, 1.0))  # lb above ub
    assert broken(lambda d: d["integrality"].__setitem__(0, 2))
    assert broken(lambda d: d["item_cols"].append([len(d["col_names"]), "HEAD", "x", 0]))  # a column that does not exist
    assert broken(lambda d: d["buff_cols"].append([0, 1.5]))
    assert broken(lambda d: d.__setitem__("sense", "up"))
    assert not broken(lambda d: d.__setitem__("sense", "min"))  # a minimization is a model too


# ---- what the reader of the browser takes, and what it cannot -----------------------------------------------------------------
#
# The browser's reader (static/engine/protocol.js) takes exactly the documents this module takes, except for the two things it cannot see in
# a parsed document (a number written as 1.0, a key written twice). The tests below are about what the two used to disagree on;
# tests-js/engine-worker.test.mjs and tests-js/milp-fixtures.test.mjs judge the same documents, and fixtures/milp/cases.json holds them.


def wide(columns=0, rows=0):
    """A valid document of the given size, with nothing in it."""
    return {
        "version": 1, "sense": "max", "const": 0.0,
        "col_names": [f"c{i}" for i in range(columns)], "col_lb": [None] * columns, "col_ub": [None] * columns,
        "integrality": [0] * columns, "c": [0.0] * columns,
        "row_names": [f"r{i}" for i in range(rows)], "row_lb": [None] * rows, "row_ub": [None] * rows,
        "A": {"start": [0] * (rows + 1), "index": [], "value": []},
        "item_cols": [], "buff_cols": [], "info": {},
    }  # fmt: skip


def with_info(info):
    document = doc(small_model())
    document["info"] = info
    return document


def levels(count):
    """An info with `count` containers on its one path, the info itself being the first."""
    value = 0
    for _ in range(count - 1):
        value = [value]
    return {"k": value}


def test_a_name_a_key_or_a_text_of_the_info_is_any_text_whatever_it_looks_like():
    """Names, the group and key of an item column and the info are labels: nothing in the engine reads them as anything else."""
    document = doc(small_model())
    texts = ["slot:head", "a/b", "c\\d", "https://x.example/y", "x" * 161, "x" * 3000, "a\u0001b", "line sep", "ïnside \U0001f600"]
    for column, text in enumerate(texts[: len(document["col_names"])]):
        document["col_names"][column] = text
    document["row_names"][0] = "slot:row/0"
    document["item_cols"] = [[0, "slot:HEAD", "a/b", 4]]
    document["info"] = {"worker_count": 1, "PAL MNK": 2, "trio": "PAL/MNK/BER", "": "an empty key", "url": "https://x.example/y", "long": "x" * 500}
    assert MJ.validate(document) == []
    assert MJ.loads(json.dumps(document)) == document


def test_a_buff_id_is_a_whole_number_that_a_double_holds_exactly_so_that_the_browser_reads_the_same_number():
    base = doc(small_model())

    def with_ids(*ids):
        document = copy.deepcopy(base)
        document["buff_cols"] = [[column, buff_id] for column, buff_id in enumerate(ids)]
        return document

    safe = 2**53 - 1
    for ids in [(safe,), (-safe,), (safe, -safe, 0, -1), (0,)]:
        assert MJ.validate(with_ids(*ids)) == [], ids
    for ids in [(2**53,), (-(2**53),), (2**60,), (2**60 + 1,), (10**400,), (0, 2**53)]:
        faults = MJ.validate(with_ids(*ids))
        assert faults and all(isinstance(line, str) for line in faults), ids
        with pytest.raises(ValueError):
            MJ.loads(json.dumps(with_ids(*ids)))


def test_bounds_are_compared_as_the_doubles_they_are_read_as_so_that_the_browser_agrees():
    """A whole number beyond 2**53 is read by the browser, and by the solver, as the nearest double: two bounds that differ by one in such a number
    are the same bound, not a lower bound above an upper one. A real inversion is refused at any size."""
    for low_key, high_key, cols, rows in (("col_lb", "col_ub", 1, 0), ("row_lb", "row_ub", 0, 1)):
        for low, high, taken in [(2**53 + 1, 2**53, True), (2**60 + 1, 2**60, True), (-(2**53), -(2**53) - 1, True), (2**53 + 2, 2**53, False), (3, 2, False), (2**60 + 2**10, 2**60, False)]:
            document = wide(columns=cols, rows=rows)
            document[low_key] = [low]
            document[high_key] = [high]
            assert (MJ.validate(document) == []) is taken, (low_key, low, high)


def test_a_number_too_big_for_a_double_is_refused_and_is_not_a_crash():
    """`int` has no limit and `float` has one: 10**400 once raised OverflowError out of validate. The browser reads such a number as Infinity."""
    base = doc(small_model())
    big = "1" + "0" * 400
    places = [("const",), ("c", 0), ("col_lb", 0), ("col_ub", 0), ("row_lb", 0), ("row_ub", 0), ("A", "value", 0)]
    for place in places:
        for sign in ("", "-"):
            document = copy.deepcopy(base)
            node = document
            for step in place[:-1]:
                node = node[step]
            node[place[-1]] = "@@big@@"
            text = json.dumps(document).replace('"@@big@@"', sign + big)
            with pytest.raises(ValueError):
                MJ.loads(text)
            assert MJ.validate(json.loads(text)), (place, sign)  # a list of faults, not an exception
    # a whole number that a double does hold (below 1.8e308) is a number like another, and the browser reads it as the same double
    document = copy.deepcopy(base)
    document["const"] = 10**300
    assert MJ.validate(document) == []


def test_the_info_is_plain_data_without_a_number_that_is_not_finite_and_without_the_keys_that_could_poison_a_lookup_in_the_browser():
    assert MJ.validate(with_info({"a": {"b": [1, 2.5, "text", None, True, {"c": []}]}, "n": 0})) == []
    assert MJ.validate(with_info({"big": 2**60, "float": 1e300})) == []  # (the browser reads a number as a double, and so does the solver)
    for key in ("__proto__", "constructor", "prototype"):
        assert MJ.validate(with_info({key: 1})), key
        assert MJ.validate(with_info({"a": [{"b": {key: 1}}]})), key
        assert MJ.validate(with_info({"x" + key: 1})) == [], key  # the key is refused, not any text that contains it
    for number in (float("inf"), float("-inf"), float("nan"), 10**400, -(10**400)):
        assert MJ.validate(with_info({"a": number})), number
        assert MJ.validate(with_info({"a": [number]})), number
    assert MJ.validate(with_info({1: "a number for a key"}))
    assert MJ.validate(with_info({"a": {1, 2}})) and MJ.validate(with_info({"a": b"bytes"})) and MJ.validate(with_info({"a": object()}))
    # text that holds a number too big for a double reads as infinity, which is not data
    text = json.dumps(with_info({"x": 0})).replace('"x": 0', '"x": 1e999')
    assert "1e999" in text
    with pytest.raises(ValueError):
        MJ.loads(text)


def test_the_info_has_at_most_eight_levels_and_a_hundred_thousand_values_as_in_the_browser():
    assert (MJ.MAX_INFO_DEPTH, MJ.MAX_INFO_NODES) == (8, 100_000)
    assert MJ.validate(with_info(levels(8))) == []
    assert MJ.validate(with_info(levels(9)))
    assert MJ.validate(with_info(levels(500)))  # (no recursion error however deep: the walk keeps its own stack)
    assert MJ.validate(with_info({"k": [0] * (MJ.MAX_INFO_NODES - 2)})) == []  # the info, the list and the values: exactly the limit
    assert MJ.validate(with_info({"k": [0] * (MJ.MAX_INFO_NODES - 1)}))


def test_the_size_limits_of_the_browser_are_the_limits_of_the_document():
    assert (MJ.MAX_COLUMNS, MJ.MAX_ROWS, MJ.MAX_NONZEROS) == (50_000, 50_000, 1_000_000)
    assert MJ.validate(wide(columns=MJ.MAX_COLUMNS)) == []
    assert MJ.validate(wide(columns=MJ.MAX_COLUMNS + 1))
    assert MJ.validate(wide(rows=MJ.MAX_ROWS)) == []
    assert MJ.validate(wide(rows=MJ.MAX_ROWS + 1))
    # the entries of the matrix: a row names each column once, so a thousand rows of a thousand columns hold a million
    columns, rows = 1000, MJ.MAX_NONZEROS // 1000
    document = wide(columns=columns, rows=rows)
    document["A"] = {"start": [r * columns for r in range(rows + 1)], "index": list(range(columns)) * rows, "value": [1.0] * (columns * rows)}
    assert MJ.validate(document) == []
    document["row_names"].append("one more")
    document["row_lb"].append(None)
    document["row_ub"].append(None)
    document["A"]["start"].append(document["A"]["start"][-1] + 1)
    document["A"]["index"].append(0)
    document["A"]["value"].append(1.0)
    assert MJ.validate(document)


def test_loads_turns_a_document_nested_too_deeply_for_the_reader_into_a_value_error():
    depth = 100_000
    with pytest.raises(ValueError):
        MJ.loads("[" * depth + "]" * depth)
    with pytest.raises(ValueError):
        MJ.loads('{"version":1,"info":' + "[" * depth + "]" * depth + "}")


def test_an_integer_column_with_a_bound_that_is_not_a_whole_number_is_refused_and_not_rounded():
    """The solver gives wrong answers, labelled optimal, for such a column (a bound of 2.5 on a yes/no column, say), so the
    document is refused with a message that names the column; it is never rounded, which would only move the error."""
    base = doc(small_model())
    integer = base["integrality"].index(1)
    name = base["col_names"][integer]
    for key, value in (("col_lb", 0.5), ("col_lb", -0.1), ("col_ub", 2.25), ("col_ub", 1e-9), ("col_ub", 1.9999999999)):
        document = copy.deepcopy(base)
        document["col_lb"][integer] = -5.0 if key == "col_ub" else document["col_lb"][integer]
        document["col_ub"][integer] = 7.0 if key == "col_lb" else document["col_ub"][integer]
        document[key][integer] = value
        found = MJ.validate(document)
        assert found, (key, value)
        assert any(name in p and "whole number" in p for p in found), found
        with pytest.raises(ValueError, match="whole number"):
            MJ.dumps(document)
        with pytest.raises(ValueError, match="whole number"):
            MJ.loads(json.dumps(document))
    # whole numbers are fine however they are written, and so is no bound at all
    for key, value in (("col_lb", 0.0), ("col_lb", -3.0), ("col_ub", 7.0), ("col_ub", 1e15), ("col_ub", None), ("col_lb", None)):
        document = copy.deepcopy(base)
        document[key][integer] = value
        assert MJ.validate(document) == [], (key, value)
    # a column that is not an integer column may have any bound
    free = base["integrality"].index(0)
    document = copy.deepcopy(base)
    document["col_lb"][free], document["col_ub"][free] = 0.125, 2.5
    assert MJ.validate(document) == []
    # the writer refuses a model that has one, instead of writing a document that no reader would take
    for key in ("col_lb", "col_ub"):
        milp = small_model()
        getattr(milp, key)[integer] = 0.5 if key == "col_lb" else 2.5
        with pytest.raises(ValueError, match="whole number"):
            MJ.to_dict(milp)
        with pytest.raises(ValueError, match="whole number"):
            MJ.to_json(milp)


# ---- compare ------------------------------------------------------------------------------------------------------------------


def models():
    return [doc(small_model(seed)) for seed in range(6)] + [doc(owned_model(seed)) for seed in range(4)]


def test_equal_documents_and_equal_texts_have_nothing_to_report_and_the_arguments_may_be_either():
    for document in models():
        assert MJ.compare(document, copy.deepcopy(document)) == []
        text = MJ.dumps(document)
        assert MJ.compare(text, document) == MJ.compare(document, text) == MJ.compare(text, text) == []


def pick(document, key=None):
    """A nonzero coefficient of the matrix: ``(row index, column index, value, position)``."""
    A = document["A"]
    for r in range(len(document["row_names"])):
        for k in range(A["start"][r], A["start"][r + 1]):
            if A["value"][k] != 0 and (key is None or abs(A["value"][k]) > key):
                return r, A["index"][k], A["value"][k], k
    raise AssertionError("no coefficient")


def test_a_coefficient_agrees_within_a_tolerance_of_1e_12_relative_and_not_beyond():
    for document in models()[:4]:
        r, col, value, k = pick(document, 0.99)
        scale = max(1.0, abs(value))
        near, far = copy.deepcopy(document), copy.deepcopy(document)
        near["A"]["value"][k] = value + 0.5e-12 * scale
        far["A"]["value"][k] = value + 2e-12 * scale
        assert MJ.compare(document, near) == []
        report = MJ.compare(document, far)
        assert len(report) == 1 and report[0].startswith("coefficient differs: ")
        assert f"row {document['row_names'][r]}" in report[0] and f"column {document['col_names'][col]}" in report[0]
        coarse = copy.deepcopy(document)
        coarse["A"]["value"][k] = value * (1 + 1e-11)
        assert MJ.compare(document, coarse)  # 1e-11 of the value is beyond the tolerance for a value of 1 and more


def test_the_tolerance_is_relative_for_large_values_and_absolute_for_small_ones():
    document = doc(small_model())
    r, col, value, k = pick(document)
    big, small = copy.deepcopy(document), copy.deepcopy(document)
    big["A"]["value"][k] = value
    big["row_ub"][r] = 1e9
    twin = copy.deepcopy(big)
    twin["row_ub"][r] = 1e9 + 1e-4  # 1e-13 relative to 1e9: within
    assert MJ.compare(big, twin) == []
    twin["row_ub"][r] = 1e9 + 1e-1  # 1e-10 relative: beyond
    assert any("row upper bound differs" in line for line in MJ.compare(big, twin))
    small["c"][0] = 1e-14
    other = copy.deepcopy(small)
    other["c"][0] = 0.0
    assert MJ.compare(small, other) == []  # 1e-14 is within 1e-12 of 0 (the scale is at least 1)


def test_a_stored_zero_and_a_missing_entry_are_the_same_coefficient():
    document = doc(small_model())
    r, col, value, k = pick(document)
    zero = copy.deepcopy(document)
    zero["A"]["value"][k] = 0.0
    dropped = copy.deepcopy(document)
    start, index, values = dropped["A"]["start"], dropped["A"]["index"], dropped["A"]["value"]
    del index[k], values[k]
    for row in range(r + 1, len(start)):
        start[row] -= 1
    assert MJ.compare(zero, dropped) == []
    assert MJ.compare(document, dropped) and MJ.compare(document, zero)


def test_a_null_bound_is_never_within_a_tolerance_of_a_number():
    document = doc(small_model())
    free_column = next(i for i, v in enumerate(document["col_ub"]) if v is None)
    open_row = next(i for i, v in enumerate(document["row_lb"]) if v is None)
    low_of_column = document["col_lb"][free_column]
    high_of_row = document["row_ub"][open_row]
    for key, at, name_key, text, numbers in (
        ("col_ub", free_column, "col_names", "column upper bound differs", [(low_of_column or 0.0) + shift for shift in (0.0, 1e300)]),
        ("row_lb", open_row, "row_names", "row lower bound differs", [(high_of_row or 0.0) - shift for shift in (0.0, 1e300)]),
    ):
        for number in numbers:
            other = copy.deepcopy(document)
            other[key][at] = number
            report = MJ.compare(document, other)
            assert len(report) == 1 and report[0].startswith(text) and document[name_key][at] in report[0], (key, number)
            assert "unbounded" in report[0] and MJ.compare(other, document)


def test_a_changed_bound_integrality_objective_or_constant_is_named():
    document = doc(small_model())
    col = next(i for i, v in enumerate(document["col_ub"]) if v is not None and v >= 2)
    for key, label in (("col_lb", "column lower bound differs"), ("col_ub", "column upper bound differs"), ("c", "objective coefficient differs")):
        other = copy.deepcopy(document)
        other[key][col] = (other[key][col] or 0.0) + 1.0
        report = MJ.compare(document, other)
        assert len(report) == 1 and report[0].startswith(label) and document["col_names"][col] in report[0], key
    flipped = copy.deepcopy(document)
    flipped["integrality"][col] = 1 - flipped["integrality"][col]
    assert MJ.compare(document, flipped) == [f"integrality differs: {document['col_names'][col]}"]
    moved = copy.deepcopy(document)
    moved["const"] += 1.0
    assert MJ.compare(document, moved)[0].startswith("constant differs")
    sense = copy.deepcopy(document)
    sense["sense"] = "min"
    assert MJ.compare(document, sense)[0].startswith("sense differs")
    version = copy.deepcopy(document)
    version["version"] = 2
    assert MJ.compare(document, version) == ["version differs: 1 vs 2"]


def test_a_reordered_column_is_reported_once_as_an_order_change_and_not_as_a_flood_of_differences():
    document = doc(small_model())
    swapped = copy.deepcopy(document)
    for key in ("col_names", "col_lb", "col_ub", "integrality", "c"):
        swapped[key][2], swapped[key][3] = swapped[key][3], swapped[key][2]
    remap = {2: 3, 3: 2}  # the matrix follows the columns: rename the indices 2 and 3 and keep each row sorted
    A, start = swapped["A"], document["A"]["start"]
    rows = [sorted((remap.get(i, i), v) for i, v in zip(document["A"]["index"][a:b], document["A"]["value"][a:b])) for a, b in zip(start, start[1:])]
    A["index"] = [i for row in rows for i, _ in row]
    A["value"] = [v for row in rows for _, v in row]
    swapped["item_cols"] = [[remap.get(col, col), *rest] for col, *rest in swapped["item_cols"]]
    swapped["buff_cols"] = [[remap.get(col, col), bid] for col, bid in swapped["buff_cols"]]
    report = MJ.compare(document, swapped)
    assert report[0].startswith("column order changed: first difference at position 2")
    assert document["col_names"][2] in report[0] and document["col_names"][3] in report[0]
    assert len(report) == 1  # the order, and nothing about the values that are the same by name


def test_a_missing_row_an_extra_row_and_a_reordered_row_are_named():
    document = doc(small_model())
    names = document["row_names"]
    gone = copy.deepcopy(document)
    r = 3
    start, index, values = gone["A"]["start"], gone["A"]["index"], gone["A"]["value"]
    lo, hi = start[r], start[r + 1]
    del index[lo:hi], values[lo:hi]
    for row in range(r + 1, len(start)):
        start[row] -= hi - lo
    del start[r]
    for key in ("row_names", "row_lb", "row_ub"):
        del gone[key][r]
    assert MJ.compare(document, gone) == [f"missing row: {names[r]}"]
    assert MJ.compare(gone, document) == [f"extra row: {names[r]}"]
    swapped = copy.deepcopy(document)
    for key in ("row_names", "row_lb", "row_ub"):
        swapped[key][0], swapped[key][1] = swapped[key][1], swapped[key][0]
    # the matrix rows move with their names
    start, index, values = swapped["A"]["start"], swapped["A"]["index"], swapped["A"]["value"]
    rows = [(index[start[i]:start[i + 1]], values[start[i]:start[i + 1]]) for i in range(len(names))]
    rows[0], rows[1] = rows[1], rows[0]
    swapped["A"] = {"start": [0], "index": [], "value": []}
    for ix, vs in rows:
        swapped["A"]["index"] += ix
        swapped["A"]["value"] += vs
        swapped["A"]["start"].append(len(swapped["A"]["index"]))
    report = MJ.compare(document, swapped)
    assert report == [f"row order changed: first difference at position 0 ({names[0]} vs {names[1]})"]


def test_the_first_differing_row_comes_first_and_a_long_report_is_cut():
    document = doc(small_model())
    other = copy.deepcopy(document)
    rows = [r for r, v in enumerate(document["row_ub"]) if v is not None][:6:2]
    for r in reversed(rows):
        other["row_ub"][r] += 1.0
    report = MJ.compare(document, other)
    assert [line.split(": ")[1].split(" ")[0] for line in report] == [document["row_names"][r] for r in rows]  # row order
    wide = next(d for d in (doc(prunable_model(seed)) for seed in range(60)) if len(d["c"]) > 120)
    wrecked = copy.deepcopy(wide)
    wrecked["c"] = [v + 1.0 for v in wrecked["c"]]
    assert len(wide["c"]) > 100
    long_report = MJ.compare(wide, wrecked)
    assert len(long_report) == 101 and long_report[-1] == f"... and {len(wide['c']) - 100} more"


def test_the_item_and_buff_columns_are_compared_by_the_names_of_their_columns():
    document = next(d for d in models() if d["item_cols"] and d["buff_cols"])
    other = copy.deepcopy(document)
    other["item_cols"][0][3] += 1  # another tier on the same column
    assert MJ.compare(document, other)[0].startswith("item columns differ")
    other = copy.deepcopy(document)
    other["buff_cols"][0][1] += 1000
    assert MJ.compare(document, other)[0].startswith("buff columns differ")
    other = copy.deepcopy(document)
    other["item_cols"].reverse()
    assert MJ.compare(document, other)[0].startswith("item columns differ") or len(document["item_cols"]) == 1


def test_an_invalid_document_is_reported_not_compared():
    document = doc(small_model())
    broken = copy.deepcopy(document)
    broken["col_lb"].pop()
    report = MJ.compare(document, broken)
    assert report and all(line.startswith("invalid model b: ") for line in report)
    assert MJ.compare(broken, document)[0].startswith("invalid model a: ")


def test_models_that_differ_by_one_option_differ_in_the_rows_that_option_makes():
    inst, caps, news, ups, max_new = U.ownership_case(9)
    plain = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst))
    owned = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst, caps, news, ups, max_new))
    extra = set(owned.row_names) - set(plain.row_names)
    assert extra and all(name.startswith(("own.", "new.")) for name in extra)
    report = MJ.compare(doc(plain), doc(owned))
    assert {line.split(": ", 1)[1] for line in report if line.startswith("extra row")} == extra
    assert MJ.compare(doc(owned), doc(owned)) == []


# ---- the package ---------------------------------------------------------------------------------------------------------------


def test_the_export_package_is_one_line():
    path = Path(MJ.__file__).with_name("__init__.py")
    assert path.read_bytes().replace(b"\r\n", b"\n") == b'"""Exports for the browser engine."""\n'


# ---- the real catalog ---------------------------------------------------------------------------------------------------------


@H.slow
def test_the_model_json_of_a_real_best_one_addition_step_is_valid_reads_back_and_is_small_enough(capsys):
    import gzip
    import time

    from trioforge import upgrade as UP
    from trioforge.solver.prune import prune

    profile, buffset, owned, candidates, _ = U.real_session()
    ledger = UP._Owned(owned)
    session = BuildOptions(haste_assumed=UP.session_haste(profile, owned, candidates, "dw", buffset))
    plan = UP._Plan(ledger, candidates)
    pool = list(plan.pool.values())
    kept = prune(pool, profile, None, "dw", buffset, plan.options(session, pool, 1), owned=frozenset(plan.caps))
    milp = build_milp(profile, kept, "dw", buffset, plan.options(session, kept, 1))
    started = time.perf_counter()
    text = MJ.to_json(milp)
    wrote = time.perf_counter() - started
    started = time.perf_counter()
    document = MJ.loads(text)
    read = time.perf_counter() - started
    assert MJ.validate(document) == [] and MJ.compare(document, MJ.to_dict(milp)) == [] and MJ.dumps(document) == text
    assert any(name == "new.limit" for name in document["row_names"]) and any(n.startswith("own.") for n in document["row_names"])
    assert len(document["row_names"]) == len(set(document["row_names"])) == milp.num_rows
    with capsys.disabled():
        print(
            f"\nmodel JSON of a Best-1 step: {milp.num_cols} columns, {milp.num_rows} rows, {len(document['A']['value'])} entries; "
            f"{len(text) / 1e6:.2f} MB, {len(gzip.compress(text.encode(), 6)) / 1e6:.2f} MB gzip; write {wrote:.2f}s read {read:.2f}s"
        )
