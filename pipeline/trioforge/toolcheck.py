"""Toolchain check: report tool versions and prove the pinned HiGHS solves a MIP.

Run as ``python -m trioforge.toolcheck`` (with ``pipeline`` on ``sys.path``).
"""

import platform
import sys
from importlib import metadata

import highspy
import numpy as np


def highs_version() -> str:
    """Return the HiGHS *core* version bundled in highspy, as ``MAJOR.MINOR.PATCH``."""
    highs = highspy.Highs()
    return f"{highs.versionMajor()}.{highs.versionMinor()}.{highs.versionPatch()}"


def _ok(status: highspy.HighsStatus, what: str) -> None:
    if status == highspy.HighsStatus.kError:
        raise RuntimeError(f"HiGHS call failed: {what}")


def solve_tiny_mip() -> float:
    """Solve a two-variable integer program and return its optimal objective value.

    maximize x + y  subject to  x + 2y <= 4,  3x + y <= 6,  x, y integer >= 0.

    The LP relaxation optimum is 2.8 (x = 1.6, y = 1.2); the integer optimum is
    2.0, so a correct answer proves that integrality is actually enforced.
    """
    inf = highspy.kHighsInf
    columns = np.array([0, 1], dtype=np.int32)

    highs = highspy.Highs()
    highs.setOptionValue("output_flag", False)

    _ok(highs.addVars(2, np.array([0.0, 0.0]), np.array([inf, inf])), "addVars")
    _ok(highs.changeColsCost(2, columns, np.array([1.0, 1.0])), "changeColsCost")
    integer = np.array([highspy.HighsVarType.kInteger.value] * 2, dtype=np.uint8)
    _ok(highs.changeColsIntegrality(2, columns, integer), "changeColsIntegrality")
    _ok(highs.changeObjectiveSense(highspy.ObjSense.kMaximize), "changeObjectiveSense")

    # Rows are given row-wise: (x + 2y <= 4) then (3x + y <= 6).
    row_lower = np.array([-inf, -inf])
    row_upper = np.array([4.0, 6.0])
    starts = np.array([0, 2], dtype=np.int32)
    indices = np.array([0, 1, 0, 1], dtype=np.int32)
    values = np.array([1.0, 2.0, 3.0, 1.0])
    _ok(highs.addRows(2, row_lower, row_upper, 4, starts, indices, values), "addRows")

    _ok(highs.run(), "run")
    status = highs.getModelStatus()
    if status != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"tiny MIP did not solve to optimality: {highs.modelStatusToString(status)}")
    return float(highs.getInfo().objective_function_value)


def main() -> int:
    print(f"python {platform.python_version()}")
    print(f"numpy {metadata.version('numpy')}")
    print(f"highspy-core {highs_version()}")
    print(f"jinja2 {metadata.version('jinja2')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
