"""Toolchain checks: the pinned HiGHS build must solve a tiny MIP exactly."""

import os
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

import trioforge
from trioforge.toolcheck import highs_version, solve_tiny_mip

REPO_ROOT = Path(__file__).resolve().parents[2]

# Exact Python pins. Bumping one is a deliberate act:
# edit requirements.txt and this table together, then refresh requirements.lock.
PINS = {
    "highspy": "1.15.1",
    "numpy": "2.5.3",
    "jinja2": "3.1.6",
    "jsonschema": "4.26.0",
    "mwparserfromhell": "0.7.2",
    "pytest": "9.1.1",
    "hypothesis": "6.168.3",
    "pyyaml": "6.0.3",
}


def test_highs_version_is_major_minor_patch_in_the_1_15_series():
    version = highs_version()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    assert version.startswith("1.15."), version


def test_tiny_mip_returns_the_integer_optimum_not_the_lp_relaxation():
    # maximize x + y  subject to  x + 2y <= 4,  3x + y <= 6,  x, y integer >= 0.
    # The LP relaxation optimum is 2.8 (x = 1.6, y = 1.2); the integer optimum
    # is 2. Asserting "not 2.8" proves integrality is actually enforced.
    result = solve_tiny_mip()
    assert isinstance(result, float)
    assert result == 2.0
    assert result != pytest.approx(2.8)


# ---- package version, command-line output and the pins in requirements.txt ----


def test_package_version():
    assert trioforge.__version__ == "0.0.1"


def test_cli_prints_one_line_per_tool():
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT / "pipeline"))
    proc = subprocess.run(
        [sys.executable, "-m", "trioforge.toolcheck"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    expected = [
        r"python 3\.12\.\d+",
        r"numpy 2\.5\.3",
        r"highspy-core 1\.15\.\d+",
        r"jinja2 3\.1\.6",
    ]
    assert len(lines) == len(expected), lines
    for line, pattern in zip(lines, expected):
        assert re.fullmatch(pattern, line), line


def test_requirements_are_exact_pins_and_match_the_installed_versions():
    text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    parsed = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==(\d+(?:\.\d+)*)", line)
        assert match, f"not an exact == pin: {line!r}"
        parsed[match.group(1).lower()] = match.group(2)
    assert parsed == PINS
    for name, version in PINS.items():
        assert metadata.version(name) == version, name
