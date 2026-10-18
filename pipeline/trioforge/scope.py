"""The scope of a trio: the tiers a run of it is made at.

The grid of 560 trios is precomputed at +0, +4 and +10 (the other eight tiers are solved in the browser), and the milestone trio, PAL/MNK/BER,
at every tier. :func:`default_tiers` says which, for the slug or the classes of a trio.

Two things hold a trio to it. The precompute takes it as the default of ``--tiers``, which is the scope of a run: a run that has all of the tiers it
was asked for is a full one, whichever tiers those are, so that nothing in the results says that a run was short of what the trio is meant to have.
And an indexable build of the site refuses a trio whose shards have other tiers (:func:`trioforge.site.build.check_scope`; a preview takes any), as
the check of a release will. The module is light on purpose: the site generator imports it and does not import the solver.
"""

from __future__ import annotations

from collections.abc import Sequence

from trioforge.classes import CLASS_CODES

__all__ = ["ALL_TIERS", "GRID_TIERS", "MILESTONE_TRIO", "default_tiers", "trio_codes"]

#: the tiers of the game (+0 to +10)
ALL_TIERS: tuple[int, ...] = tuple(range(11))
#: the tiers the grid of trios is precomputed at; the other eight solve in the browser
GRID_TIERS: tuple[int, ...] = (0, 4, 10)
#: the one trio that has every tier (the milestone: it is the page that shows what the browser engine must agree with)
MILESTONE_TRIO: tuple[str, ...] = ("PAL", "MNK", "BER")


def trio_codes(trio: str | Sequence[str]) -> tuple[str, ...]:
    """Three class codes in class-id order from ``"pal-mnk-ber"`` (any case and order) or a sequence of codes.

    Raises ``ValueError`` for anything that is not three different classes. (It reads a trio as :func:`trioforge.precompute.grid.parse_trio`
    does, and a test holds the two together; the precompute's own module cannot be imported here without the solver.)"""
    parts = trio.upper().split("-") if isinstance(trio, str) else [str(code).upper() for code in trio]
    if len(parts) != 3 or len(set(parts)) != 3 or any(code not in CLASS_CODES for code in parts):
        raise ValueError(f"a trio is three different class codes from {' '.join(CLASS_CODES)}, joined by '-': not {trio!r}")
    return tuple(sorted(parts, key=CLASS_CODES.index))


def default_tiers(trio: str | Sequence[str]) -> tuple[int, ...]:
    """The scope of a trio: +0, +4 and +10 for a trio of the grid, and every tier (0 to 10) for the milestone trio, PAL/MNK/BER.

    ``trio`` is the slug or the class codes, in any order and case. Every scope has +4, the tier of the default view."""
    return ALL_TIERS if trio_codes(trio) == MILESTONE_TRIO else GRID_TIERS
