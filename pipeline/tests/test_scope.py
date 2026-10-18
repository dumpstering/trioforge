"""The scope of a trio: the tiers a run of it is made at (``trioforge.scope``).

The grid of 560 trios is precomputed at +0, +4 and +10 (the other eight tiers are solved in the browser), and the milestone trio, PAL/MNK/BER, at every
tier. The precompute takes that as the default of ``--tiers``, and an indexable build of the site holds each trio to it. The module is one both can
import, so it has to be light: it may not pull in the solver, and it has to read a trio the way the precompute does.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from trioforge import precompute as pc
from trioforge import scope
from trioforge.precompute import grid

REPO = Path(__file__).resolve().parents[2]
MILESTONE_WRITTEN = ["pal-mnk-ber", "PAL-MNK-BER", "ber-pal-mnk", "Ber-Mnk-Pal", ("PAL", "MNK", "BER"), ["ber", "mnk", "pal"], ("MNK", "BER", "PAL")]
GRID_WRITTEN = ["war-clr-wiz", "WIZ-CLR-WAR", "pal-shd-ber", ("pal", "shd", "ber"), "pal-mnk-shm", "ber-mnk-clr"]
NOT_A_TRIO = ["", "pal-mnk", "pal-pal-ber", "xxx-yyy-zzz", "pal-mnk-ber-war", "palmnkber", ("PAL", "MNK"), ("PAL", "MNK", "BER", "WAR"), ("PAL", "PAL", "BER")]


def test_the_milestone_trio_has_every_tier_in_any_way_it_is_written():
    assert scope.MILESTONE_TRIO == ("PAL", "MNK", "BER")
    for written in MILESTONE_WRITTEN:
        assert scope.default_tiers(written) == tuple(range(11)) == scope.ALL_TIERS, written


def test_every_other_trio_has_tiers_0_4_10():
    assert scope.GRID_TIERS == (0, 4, 10)
    for written in GRID_WRITTEN:
        assert scope.default_tiers(written) == (0, 4, 10), written


@pytest.mark.parametrize("written", NOT_A_TRIO, ids=repr)
def test_what_is_not_a_trio_has_no_scope_and_the_precompute_agrees(written):
    with pytest.raises(ValueError):
        scope.default_tiers(written)
    with pytest.raises(ValueError):
        grid.parse_trio(written)  # the precompute refuses the same things


def test_the_precompute_and_the_site_build_have_one_scope_and_not_two_copies_of_it():
    assert pc.default_tiers is scope.default_tiers
    assert pc.GRID_TIERS is scope.GRID_TIERS and pc.MILESTONE_TRIO is scope.MILESTONE_TRIO
    assert scope.ALL_TIERS == grid.TIERS  # the tiers of the game, as the grid has them
    for written in (*MILESTONE_WRITTEN, *GRID_WRITTEN):
        assert scope.default_tiers(written) == (grid.TIERS if grid.parse_trio(written) == scope.MILESTONE_TRIO else (0, 4, 10)), written


def test_the_module_pulls_in_nothing_heavy_so_that_the_site_build_may_import_it():
    code = (
        "import sys; import trioforge.scope; "
        "print(sorted(name for name in ('highspy', 'numpy', 'trioforge.solver', 'trioforge.model', 'trioforge.precompute') if name in sys.modules))"
    )
    env = dict(os.environ, PYTHONPATH=str(REPO / "pipeline"))
    done = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"
