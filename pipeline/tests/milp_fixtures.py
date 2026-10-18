"""The model JSON v1 fixtures that the Python and the JavaScript tests share (``fixtures/milp/``).

* ``models/<name>.json``: models made by the exporter (:func:`trioforge.export.milp_json.to_json`) from the builder's output, each
  in its canonical text. They are small, and cover what the browser reader has to take: integer and continuous columns, columns and
  rows with no bound, item, buff and owned-item columns, the monk and haste binaries, a model with no integer column (a plain linear
  program, which HiGHS reports with -1 nodes) and a model with no column at all.
* ``expected.json``: what the Python solver finds for each of them, the constant included. The JavaScript tests solve the same
  documents with the real engine and hold the answer to this one.
* ``cases.json``: documents written by hand for both readers to judge. ``valid`` ones both take, ``invalid`` ones both refuse. The
  Python reader is ``milp_json.validate``, the JavaScript one is ``validateRequest`` (``static/engine/protocol.js``). ``limits`` are the
  sizes the Python reader holds a document to (``milp_json.MAX_*``): the JavaScript tests check that its own limits are the same numbers.

The files are committed and a test (``test_milp_fixtures.py``) regenerates them in memory and compares, so none of them can go stale;
a change of the exporter shows as a difference until ``python pipeline/tests/milp_fixtures.py`` has written them again. Every name
here is invented.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FIXTURES = REPO / "fixtures" / "milp"
if __name__ == "__main__":  # run as a script: the test helpers and the package are found beside it
    sys.path[:0] = [str(HERE), str(REPO / "pipeline")]

import solver_helpers as H  # noqa: E402
import upgrade_helpers as U  # noqa: E402
from trioforge.export import milp_json as MJ  # noqa: E402
from trioforge.solver._highs import solve_milp  # noqa: E402
from trioforge.solver.model import build_milp  # noqa: E402

__all__ = ["FIXTURES", "cases", "expected", "model_texts", "read_texts", "write"]


# ---- the models of the exporter ---------------------------------------------------------------------------------------------


def _instance(seed: int):
    return H.random_instance(random.Random(seed))


def _small(seed: int):
    inst = _instance(seed)
    return build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst))


def _owned(seed: int, pool: str | None = None):
    inst, caps, news, ups, max_new = U.ownership_case(seed) if pool is None else U.ownership_case(seed, pool=pool)
    return build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst, caps, news, ups, max_new))


def _empty_pool(seed: int):
    """No item to choose from and no optional buff: what is left is a linear program of one column (or nothing at all)."""
    inst = _instance(seed)
    return build_milp(inst.profile, [], inst.setup, inst.buffset, U.options_of(inst))


#: name -> builder. The seeds were picked for what they contain (see the module docstring), not at random.
BUILDERS = {
    "mip-buffs": lambda: _small(3),
    "mip-selection-ordering-haste": lambda: _small(8),
    "mip-buffs-haste": lambda: _small(14),
    "mip-owned-monk": lambda: _owned(5),
    "mip-owned-buffs-haste": lambda: _owned(9),
    "mip-prunable-pool": lambda: _owned(4, "prunable"),
    "lp-one-column": lambda: _empty_pool(1),
    "no-columns": lambda: _empty_pool(10),
}


def model_texts() -> dict[str, str]:
    """name -> the canonical text of the model, as the file holds it (with the line end)."""
    return {name: MJ.to_json(build()) + "\n" for name, build in BUILDERS.items()}


def expected() -> dict[str, dict[str, object]]:
    """name -> what the Python solver finds: its status and the objective with the model's constant (``null`` when it has none)."""
    found: dict[str, dict[str, object]] = {}
    for name, build in BUILDERS.items():
        milp = build()
        if milp.num_cols == 0:  # nothing to solve: the answer is the constant (the browser engine answers it without a solver, too)
            found[name] = {"status": "optimal", "objective": float(milp.const), "integer_columns": 0}
            continue
        result = solve_milp(milp)
        objective = None if result.objective is None else float(milp.const + result.objective)
        found[name] = {"status": result.status, "objective": objective, "integer_columns": int(sum(int(v) for v in milp.integrality))}
    return found


# ---- the documents written by hand ----------------------------------------------------------------------------------------


def tiny() -> dict:
    """Three columns (the first an integer one, the last with no bound at all), two rows, one item column, one buff column."""
    return {
        "version": 1,
        "sense": "max",
        "const": 1.5,
        "col_names": ["a", "b", "c"],
        "col_lb": [0.0, 0.0, None],
        "col_ub": [1.0, 4.0, None],
        "integrality": [1, 0, 0],
        "c": [3.0, 1.0, -1.0],
        "row_names": ["cap", "link"],
        "row_lb": [None, 0.0],
        "row_ub": [5.0, 0.0],
        "A": {"start": [0, 2, 4], "index": [0, 1, 1, 2], "value": [2.0, 1.0, 1.0, -1.0]},
        "item_cols": [[0, "HEAD", "it01", 4]],
        "buff_cols": [[2, 100]],
        "info": {"cols": 3, "rows": 2},
    }


def _changed(**fields) -> dict:
    document = tiny()
    for key, value in fields.items():
        document[key] = value
    return document


def _edit(mutate) -> dict:
    document = tiny()
    mutate(document)
    return document


def _without(key: str) -> dict:
    document = tiny()
    del document[key]
    return document


def _levels(count: int) -> dict:
    """An info with `count` containers on its one path, the info itself being the first."""
    value: object = 0
    for _ in range(count - 1):
        value = [value]
    return {"k": value}


def _valid() -> dict[str, object]:
    empty_rows = _edit(lambda d: d.update(row_names=[], row_lb=[], row_ub=[], A={"start": [0], "index": [], "value": []}))
    nothing = {
        "version": 1, "sense": "max", "const": 7.0, "col_names": [], "col_lb": [], "col_ub": [], "integrality": [], "c": [],
        "row_names": [], "row_lb": [], "row_ub": [], "A": {"start": [0], "index": [], "value": []},
        "item_cols": [], "buff_cols": [], "info": {},
    }  # fmt: skip
    return {
        "a small model": tiny(),
        "a minimisation": _changed(sense="min"),
        "no rows": empty_rows,
        "no columns and no rows": nothing,
        "a row with no entry": _edit(lambda d: d["A"].update(start=[0, 2, 2], index=[0, 1], value=[2.0, 1.0])),
        "no bound at all": _changed(col_lb=[None, None, None], col_ub=[None, None, None], row_lb=[None, None], row_ub=[None, None]),
        "an integer column with no bound": _edit(lambda d: d.update(col_lb=[None, 0.0, None], col_ub=[None, 4.0, None])),
        "whole-number bounds written with a point on an integer column": _edit(lambda d: d.update(col_lb=[-3.0, 0.0, None], col_ub=[7.0, 4.0, None])),
        "a bound that is not whole on a continuous column": _edit(lambda d: d.update(col_lb=[0.0, 0.125, -2.5], col_ub=[1.0, 2.5, 0.75])),
        "equal bounds": _edit(lambda d: d.update(col_lb=[1.0, 2.5, 0.0], col_ub=[1.0, 2.5, 0.0])),
        "the first and the last tier of an item": _changed(item_cols=[[0, "HEAD", "it01", 0], [1, "NECK", "it02", 10]]),
        "buff ids that are zero or negative": _changed(buff_cols=[[0, 0], [2, -1]]),
        "no item and no buff column": _changed(item_cols=[], buff_cols=[]),
        "an info with nested data": _changed(info={"a": {"b": [1, 2.5, "text", None, True]}, "n": 0}),
        "negative and large numbers": _edit(lambda d: d.update(const=-1.0e9, c=[-3.5, 1.0e12, 2.0e-9])),
        # labels are any text: names, the group and key of an item column, the keys and texts of the info
        "names and keys that look like addresses, with odd characters and any length": _edit(
            lambda d: d.update(
                col_names=["slot:head", "a/b", "x" * 161], row_names=["https://x.example/y", "line\u2028sep\u0001"], item_cols=[[0, "slot:HEAD", "a/b\\c", 4]]
            )
        ),
        "names that are the keys of an object": _changed(col_names=["__proto__", "constructor", "prototype"]),
        "an info with keys and texts of any kind": _changed(
            info={"worker_count": 1, "PAL MNK": 2, "trio": "PAL/MNK/BER", "": "an empty key", "url": "https://x.example/y", "long": "x" * 500}
        ),
        "an info nested to the depth limit": _changed(info=_levels(MJ.MAX_INFO_DEPTH)),
        "buff ids at the edge of what a double holds": _changed(buff_cols=[[0, 2**53 - 1], [2, -(2**53 - 1)]]),
        # a whole number that a double does not hold exactly, where a float may stand: both readers take the nearest double
        "whole numbers beyond a safe integer where a float may stand": _edit(lambda d: d.update(const=2**60, c=[3.0, 10**18, -1.0])),
        "bounds that differ by one beyond 2^53, which is the same double": _edit(lambda d: d.update(col_lb=[0.0, 2**53 + 1, None], col_ub=[1.0, 2**53, None])),
    }


def _invalid() -> dict[str, object]:
    def a(change) -> dict:
        document = tiny()
        change(document["A"])
        return document

    cases: dict[str, object] = {
        "null": None,
        "a list": [],
        "a number": 1,
        "text": "model",
        "an empty object": {},
        "an unknown field": _changed(extra=1),
        "version 2": _changed(version=2),
        "a version in text": _changed(version="1"),
        "a version that is true": _changed(version=True),
        "a version that is not whole": _changed(version=1.5),
        "a sense in capitals": _changed(sense="MAX"),
        "a sense that is not one": _changed(sense="up"),
        "a sense that is null": _changed(sense=None),
        "a constant in text": _changed(const="1.5"),
        "a constant that is null": _changed(const=None),
        "a constant that is true": _changed(const=True),
        # names
        "column names that are not a list": _changed(col_names="abc"),
        "a column name that is a number": _changed(col_names=["a", 5, "c"]),
        "a column name that is empty": _changed(col_names=["a", "", "c"]),
        "a column name used twice": _changed(col_names=["a", "b", "a"]),
        "column names of the wrong length": _changed(col_names=["a", "b"]),
        "a row name that is a number": _changed(row_names=["cap", 5]),
        "a row name that is empty": _changed(row_names=["cap", ""]),
        "a row name used twice": _changed(row_names=["cap", "cap"]),
        "row names of the wrong length": _changed(row_names=["cap"]),
        # bounds
        "column lower bounds of the wrong length": _changed(col_lb=[0.0, 0.0]),
        "column upper bounds of the wrong length": _changed(col_ub=[1.0, 4.0, None, None]),
        "a column bound in text": _changed(col_ub=[1.0, "4", None]),
        "a column bound that is true": _changed(col_ub=[1.0, True, None]),
        "a column lower bound above its upper bound": _changed(col_lb=[0.0, 5.0, None], col_ub=[1.0, 4.0, None]),
        "row lower bounds of the wrong length": _changed(row_lb=[None]),
        "row upper bounds of the wrong length": _changed(row_ub=[5.0, 0.0, 1.0]),
        "a row bound in text": _changed(row_lb=[None, "0"]),
        "a row lower bound above its upper bound": _changed(row_lb=[6.0, 0.0], row_ub=[5.0, 0.0]),
        "column bounds that are not a list": _changed(col_lb=0.0),
        # integrality and objective
        "an integrality flag of 2": _changed(integrality=[2, 0, 0]),
        "an integrality flag below 0": _changed(integrality=[-1, 0, 0]),
        "an integrality flag that is true": _changed(integrality=[True, False, False]),
        "an integrality flag that is not whole": _changed(integrality=[1.5, 0, 0]),
        "an integrality flag in text": _changed(integrality=["1", 0, 0]),
        "integrality of the wrong length": _changed(integrality=[1, 0]),
        "integrality that is not a list": _changed(integrality=1),
        "costs of the wrong length": _changed(c=[3.0, 1.0]),
        "a cost in text": _changed(c=[3.0, "1", -1.0]),
        "a cost that is null": _changed(c=[3.0, None, -1.0]),
        # the matrix
        "no matrix": _changed(A=None),
        "a matrix that is a list": _changed(A=[]),
        "a matrix with no start": _edit(lambda d: d["A"].pop("start")),
        "a matrix with an unknown field": a(lambda m: m.update(extra=[])),
        "a matrix start of the wrong length": a(lambda m: m.update(start=[0, 2])),
        "a matrix start that does not begin at 0": a(lambda m: m.update(start=[1, 2, 4])),
        "a matrix start that goes down": a(lambda m: m.update(start=[0, 3, 2])),
        "a matrix start that does not end at the number of entries": a(lambda m: m.update(start=[0, 2, 3])),
        "a matrix start that is not whole": a(lambda m: m.update(start=[0, 2.5, 4])),
        "indices and values of different lengths": a(lambda m: m.update(value=[2.0, 1.0, 1.0])),
        "a column index that does not exist": a(lambda m: m.update(index=[0, 1, 1, 3])),
        "a negative column index": a(lambda m: m.update(index=[-1, 1, 1, 2])),
        "a column index that is not whole": a(lambda m: m.update(index=[0, 1.5, 1, 2])),
        "column indices of a row that do not rise": a(lambda m: m.update(index=[1, 0, 1, 2])),
        "the same column twice in a row": a(lambda m: m.update(index=[1, 1, 1, 2])),
        "a coefficient in text": a(lambda m: m.update(value=[2.0, "1", 1.0, -1.0])),
        "a coefficient that is null": a(lambda m: m.update(value=[2.0, None, 1.0, -1.0])),
        # the item and buff columns
        "item columns that are not a list": _changed(item_cols={}),
        "an item column of three fields": _changed(item_cols=[[0, "HEAD", "it01"]]),
        "an item column of five fields": _changed(item_cols=[[0, "HEAD", "it01", 4, 9]]),
        "an item column that does not exist": _changed(item_cols=[[3, "HEAD", "it01", 4]]),
        "an item column below 0": _changed(item_cols=[[-1, "HEAD", "it01", 4]]),
        "an item column named twice": _changed(item_cols=[[0, "HEAD", "it01", 4], [0, "NECK", "it02", 4]]),
        "an item group that is not text": _changed(item_cols=[[0, 5, "it01", 4]]),
        "an item key that is not text": _changed(item_cols=[[0, "HEAD", None, 4]]),
        "a tier above 10": _changed(item_cols=[[0, "HEAD", "it01", 11]]),
        "a tier below 0": _changed(item_cols=[[0, "HEAD", "it01", -1]]),
        "a tier that is not whole": _changed(item_cols=[[0, "HEAD", "it01", 1.5]]),
        "a tier in text": _changed(item_cols=[[0, "HEAD", "it01", "4"]]),
        "buff columns that are not a list": _changed(buff_cols="none"),
        "a buff column of three fields": _changed(buff_cols=[[2, 100, 1]]),
        "a buff column of one field": _changed(buff_cols=[[2]]),
        "a buff column that does not exist": _changed(buff_cols=[[3, 100]]),
        "a buff column named twice": _changed(buff_cols=[[2, 100], [2, 101]]),
        "a buff id that is not whole": _changed(buff_cols=[[2, 1.5]]),
        "a buff id in text": _changed(buff_cols=[[2, "100"]]),
        # the info
        "an info that is null": _changed(info=None),
        "an info that is a list": _changed(info=[]),
        "an info that is text": _changed(info="built"),
        "an info key that could poison a lookup (__proto__)": _changed(info={"__proto__": 1}),
        "an info key that could poison a lookup (constructor)": _changed(info={"constructor": 1}),
        "an info key that could poison a lookup (prototype)": _changed(info={"prototype": 1}),
        "an info key that could poison a lookup, nested": _changed(info={"a": [{"b": {"__proto__": 1}}]}),
        "an info nested beyond the depth limit": _changed(info=_levels(MJ.MAX_INFO_DEPTH + 1)),
        # a buff id is an identifier: a whole number that a double holds exactly, 2**53 - 1 at most in size
        "a buff id of 2^60": _changed(buff_cols=[[2, 2**60]]),
        "a buff id of 2^53": _changed(buff_cols=[[2, 2**53]]),
        "a buff id of minus 2^53": _changed(buff_cols=[[2, -(2**53)]]),
        "a lower bound above the upper one beyond 2^53, by more than a double tells apart": _changed(col_lb=[0.0, 2**53 + 2, None], col_ub=[1.0, 2**53, None]),
        # an integer column with a bound that is not a whole number: refused, never rounded
        "an integer column with a fractional lower bound": _changed(col_lb=[0.5, 0.0, None]),
        "an integer column with a fractional upper bound": _changed(col_ub=[2.5, 4.0, None]),
        "an integer column with a tiny fractional lower bound": _changed(col_lb=[1e-9, 0.0, None], col_ub=[3.0, 4.0, None]),
        "an integer column with a negative fractional lower bound": _changed(col_lb=[-0.1, 0.0, None]),
        "an integer column with a fractional upper bound just under a whole number": _changed(col_ub=[1.9999999999, 4.0, None]),
    }
    for key in ("version", "sense", "const", "col_names", "col_lb", "col_ub", "integrality", "c", "row_names", "row_lb", "row_ub", "A",
                "item_cols", "buff_cols", "info"):  # fmt: skip
        cases[f"no {key}"] = _without(key)
    return cases


def _limits() -> dict[str, object]:
    """The sizes a document is held to (``milp_json.MAX_*``), which the browser reader has to hold it to as well."""
    return {
        "columns": MJ.MAX_COLUMNS,
        "rows": MJ.MAX_ROWS,
        "nonzeros": MJ.MAX_NONZEROS,
        "info_depth": MJ.MAX_INFO_DEPTH,
        "info_nodes": MJ.MAX_INFO_NODES,
        "safe_integer": MJ.MAX_SAFE_INTEGER,
    }


def cases() -> dict[str, dict[str, object]]:
    """The documents written by hand: ``valid`` (both readers take them) and ``invalid`` (both refuse them), by their names, and the ``limits``."""
    return {"valid": _valid(), "invalid": _invalid(), "limits": _limits()}


# ---- the files ----------------------------------------------------------------------------------------------------------------


def _json(value: object) -> str:
    return json.dumps(value, indent=1, ensure_ascii=True, allow_nan=False) + "\n"


def _cases_json(grouped: dict[str, dict[str, object]]) -> str:
    """The cases, one document to a line (the documents are small and there are many)."""
    lines = []
    for group, documents in grouped.items():
        body = ",\n".join(
            f"  {json.dumps(name)}: {json.dumps(document, separators=(',', ':'), ensure_ascii=True, allow_nan=False)}"
            for name, document in documents.items()
        )
        lines.append(f" {json.dumps(group)}: {{\n{body}\n }}")
    return "{\n" + ",\n".join(lines) + "\n}\n"


def read_texts(folder: Path = FIXTURES) -> dict[str, str]:
    """name -> text of the model files under ``folder``, line ends normalised."""
    models = folder / "models"
    return {path.stem: path.read_text(encoding="utf-8").replace("\r\n", "\n") for path in sorted(models.glob("*.json"))}


def write(folder: Path = FIXTURES) -> None:
    """Write every fixture file under ``folder``, replacing the model files that are there."""
    models = folder / "models"
    models.mkdir(parents=True, exist_ok=True)
    for stale in models.glob("*.json"):
        stale.unlink()
    for name, text in model_texts().items():
        (models / f"{name}.json").write_text(text, encoding="utf-8", newline="\n")
    (folder / "expected.json").write_text(_json(expected()), encoding="utf-8", newline="\n")
    (folder / "cases.json").write_text(_cases_json(cases()), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write()
    print(f"wrote {len(BUILDERS)} models, expected.json and cases.json under {FIXTURES}")
