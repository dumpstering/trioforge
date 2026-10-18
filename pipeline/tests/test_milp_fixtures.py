"""The model JSON v1 fixtures shared with the JavaScript tests (``fixtures/milp/``, made by ``milp_fixtures.py``).

The browser engine reads the documents this package writes, with a reader of its own (``static/engine/protocol.js``), so the two
readers are held to each other with files both test suites open:

* every model the exporter makes is a fixture, and the committed files are regenerated here and compared, so they cannot go stale;
* the documents written by hand (``cases.json``) are judged here by ``milp_json.validate`` and in ``tests-js/milp-fixtures.test.mjs``
  by the browser reader, and the two must give the same verdict on every one of them.

Every name here is invented.
"""

import json
import math

import milp_fixtures as F
import pytest

from trioforge.export import milp_json as MJ


def committed(name):
    return json.loads((F.FIXTURES / name).read_text(encoding="utf-8"))


def test_the_fixture_folder_holds_the_models_the_answers_and_the_cases_and_nothing_else():
    assert sorted(path.name for path in F.FIXTURES.iterdir()) == ["cases.json", "expected.json", "models"]


def test_the_model_files_are_what_the_exporter_writes_now():
    assert F.read_texts() == F.model_texts()  # the same names and the same text: nothing stale, nothing missing, nothing extra


def test_the_expected_answers_are_what_the_python_solver_finds_now():
    have, now = committed("expected.json"), F.expected()
    assert list(have) == list(now) == list(F.BUILDERS)
    for name, want in now.items():
        assert have[name]["status"] == want["status"] == "optimal", name
        assert have[name]["integer_columns"] == want["integer_columns"], name
        assert math.isclose(have[name]["objective"], want["objective"], rel_tol=1e-9, abs_tol=1e-9), name


def test_the_cases_file_is_what_the_generator_writes_now():
    assert committed("cases.json") == json.loads(json.dumps(F.cases()))


def test_every_fixture_is_a_valid_document_that_reads_back_to_the_same_text():
    texts = F.read_texts()
    assert len(texts) >= 8
    for name, text in texts.items():
        document = MJ.loads(text)
        assert MJ.validate(document) == [], name
        assert MJ.dumps(document) + "\n" == text, name


def test_the_fixtures_have_what_the_browser_reader_has_to_take():
    documents = {name: MJ.loads(text) for name, text in F.read_texts().items()}
    expected = committed("expected.json")
    flat = lambda key: [v for d in documents.values() for v in d[key]]  # noqa: E731
    assert any(not any(d["integrality"]) and d["col_names"] for d in documents.values())  # a linear program: no integer column
    assert any(not d["col_names"] and not d["row_names"] for d in documents.values())  # a model with nothing in it
    assert any(d["buff_cols"] for d in documents.values()) and any(d["item_cols"] for d in documents.values())
    assert any(n.startswith("own.") for d in documents.values() for n in d["row_names"])  # owned items
    assert None in flat("col_ub") and None in flat("row_lb")  # bounds that are not there
    assert {name for name, e in expected.items() if e["integer_columns"] == 0} == {"lp-one-column", "no-columns"}
    assert all(e["integer_columns"] == sum(documents[name]["integrality"]) for name, e in expected.items())


def test_python_takes_the_valid_cases_and_refuses_the_invalid_ones():
    cases = F.cases()
    assert len(cases["valid"]) >= 14 and len(cases["invalid"]) >= 90  # a corpus that shrinks by accident is a finding
    assert not set(cases["valid"]) & set(cases["invalid"])
    for name, document in cases["valid"].items():
        assert MJ.validate(document) == [], name
        assert MJ.loads(json.dumps(document)) == document, name
    for name, document in cases["invalid"].items():
        assert MJ.validate(document), name
        with pytest.raises(ValueError):
            MJ.loads(json.dumps(document))


def test_a_refusal_says_what_is_wrong_and_does_not_echo_the_value():
    for name, document in F.cases()["invalid"].items():
        for line in MJ.validate(document):
            assert isinstance(line, str) and line, name
    fractional = F.cases()["invalid"]["an integer column with a fractional upper bound"]
    assert MJ.validate(fractional) == ["integer column a has an upper bound that is not a whole number"]
