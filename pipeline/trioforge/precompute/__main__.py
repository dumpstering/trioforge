"""``python -m trioforge.precompute``: solve the scenario grid of a trio and write the result files.

``--tiers`` (a comma-separated list) is the **scope** of the run: the tiers that are precomputed. The default is +0, +4 and +10 and, for the
milestone trio pal-mnk-ber, every tier (0 to 10); the other eight tiers of a trio of the grid are solved in the browser. The scope must have
tier 4, the tier of the default view (a run without it is refused), and an indexable site is built only from the scope above: a run of other
tiers makes a preview. A run that has all of its scope is a full grid, not a partial one. ``--races``, ``--roles``, ``--evidence`` and
``--buffs`` (comma-separated lists) narrow the grid for a quick look or a test, and so does ``--limit``: the result files are then marked
``partial``, and are good for nothing but a look (a site built from them has only those races and roles, and an indexable build refuses them).
``--no-robustness`` leaves out ``robust.json`` and the flip notes of ``defaults.json``.

Exit status: 0 done, 1 done but a check failed (an invariant of the design, or a shard over its size budget: the files are
written and the violations are listed), 2 refused or failed
(one line on stderr, nothing assembled). A rerun continues from the chunk files, so a failure or an interrupt loses little.
With ``TRIOFORGE_DEBUG`` set, the traceback of a failure inside a worker is printed as well.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from trioforge.model.tables import REPO
from trioforge.precompute import PrecomputeError, RunSummary, run
from trioforge.precompute.shards import SHARD_GZIP_LIMIT, SHARD_RAW_LIMIT

__all__ = ["main"]


def _list(convert):
    """An argparse type for a comma-separated list: ``convert`` is applied to each word."""

    def parse(text: str) -> list:
        words = [word.strip() for word in text.split(",") if word.strip()]
        if not words:
            raise argparse.ArgumentTypeError("needs at least one value, such as OGR,TRL")
        try:
            return [convert(word) for word in words]
        except ValueError:
            raise argparse.ArgumentTypeError(f"cannot read {text!r}") from None

    return parse


def _whole(word: str) -> int:
    try:
        return int(word)
    except ValueError:
        raise ValueError(word) from None


def _positive(text: str) -> int:
    try:
        number = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _print_summary(summary: RunSummary) -> None:
    kind = "partial run" if summary.partial else "full grid"
    tiers = f", tiers {', '.join(f'+{tier}' for tier in summary.tiers)}" if summary.tiers else ""
    print(f"{summary.trio}: {summary.scenarios} scenarios in {summary.chunks} chunks ({kind}{tiers}, {summary.processes} process(es))")
    print(
        f"  chunks: {summary.solved} scenarios solved, {summary.reused} chunks reused, {summary.redone} redone, "
        f"{summary.audited} audited against an unpruned solve; "
        f"runner-up chunks: {summary.runnerup_chunks} ({summary.runnerup_solved} made, {summary.runnerup_reused} reused)"
    )
    print(
        f"  wall time {summary.elapsed:.1f} s; mean solve {summary.mean_solve_seconds:.3f} s "
        f"(solve {summary.solve_seconds:.1f} s, build {summary.build_seconds:.1f} s, runner-ups {summary.runnerup_seconds:.1f} s "
        f"in the workers); solver {'canonical' if summary.canonical else 'plain'}"
    )
    if summary.phases:
        print("  phases: " + ", ".join(f"{name} {seconds:.1f} s" for name, seconds in summary.phases.items()))
    for name, (raw, packed) in sorted(summary.sizes.items()):
        if not name.startswith("runnerups/"):
            print(f"  {name}: {raw:,} bytes, {packed:,} gzip")
    pieces = {name: size for name, size in summary.sizes.items() if name.startswith("runnerups/") and name != "runnerups/index.json"}
    if pieces:
        largest = max(pieces, key=lambda name: pieces[name][0])
        print(
            f"  runnerups/: {len(pieces)} files (one for each role, every tier in it), {sum(raw for raw, _ in pieces.values()):,} bytes "
            f"({sum(packed for _, packed in pieces.values()):,} gzip), the largest {largest.removeprefix('runnerups/')} with "
            f"{pieces[largest][0]:,} bytes ({pieces[largest][1]:,} gzip; the budget of a file is {SHARD_RAW_LIMIT:,} and {SHARD_GZIP_LIMIT:,})"
        )
    for note in summary.notes:
        print(f"  note: {note}")
    for violation in summary.violations:
        print(f"  VIOLATION: {violation}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.precompute",
        description="Solve the scenario grid of a trio (race x role x tier x evidence x buffs x weapon setup) and write the "
        "shards, runner-ups and defaults.",
    )
    parser.add_argument("--trio", required=True, help="the three classes joined by '-', e.g. pal-mnk-ber")
    parser.add_argument("--out", type=Path, default=REPO / "build" / "results", help="output folder (default build/results)")
    parser.add_argument("--seen", type=Path, help="private seen-flags file: merged into evidence; --out must be under build/")
    parser.add_argument("--processes", type=_positive, help="worker processes (default: all cores but one)")
    parser.add_argument("--limit", type=int, help="work only the first K chunks and stop (a partial run; no result files)")
    parser.add_argument("--catalog", type=Path, help="the item catalog (default $TRIOFORGE_CATALOG, then derived/catalog.json)")
    parser.add_argument("--plain", action="store_true", help="plain solves, no tie stage: faster, kits are not canonical")
    parser.add_argument("--races", type=_list(str.upper), help="narrow the grid to these races, e.g. OGR,TRL (a partial run)")
    parser.add_argument("--roles", type=_list(str.lower), help="narrow the grid to these roles, e.g. balanced,melee (a partial run)")
    parser.add_argument(
        "--tiers", type=_list(_whole),
        help="the scope of the run, the tiers to precompute, e.g. 0,4,10 (default: 0,4,10; every tier, 0 to 10, for pal-mnk-ber); it must "
        "include 4, and only the default scope makes a site that is not a preview. A run that has all of its scope is not partial",
    )
    parser.add_argument("--evidence", type=_list(str.lower), help="narrow the grid to these evidence levels: strict, wiki (a partial run)")
    parser.add_argument("--buffs", type=_list(str.lower), help="narrow the grid to these buff sets: own, group (a partial run)")
    parser.add_argument(
        "--no-robustness", "--no-robust", dest="robustness", action="store_false",
        help="leave out robust.json and the flip notes (the robustness solves take a few minutes)",
    )
    args = parser.parse_args(argv)
    try:
        summary = run(
            args.trio, args.out, seen_path=args.seen, processes=args.processes, catalog=args.catalog, limit=args.limit,
            canonical=not args.plain, races=args.races, roles=args.roles, tiers=args.tiers, evidence=args.evidence,
            buffs=args.buffs, robustness=None if args.robustness else False, progress=lambda message: print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True),
        )
    except PrecomputeError as error:
        print(f"error: {' '.join(str(error).split())}", file=sys.stderr)
        if error.trace and os.environ.get("TRIOFORGE_DEBUG"):
            print(error.trace, file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f"error: {' '.join(str(error).split())}", file=sys.stderr)
        return 2
    _print_summary(summary)
    return 1 if summary.violations else 0


if __name__ == "__main__":
    sys.exit(main())
