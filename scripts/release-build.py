"""Build a data release on the maintainer's PC.

::

    python scripts/release-build.py --tag data-YYYY-MM-DD[-N] --privacy-key <private key file> --processes 20

It builds from the public catalog (``derived/catalog.json``), which must have no strict item: wiki is the one evidence level, and a catalog with a strict item (a
community report in ``rules/community-seen.json`` made it strict) is refused before the first hour is spent. So is a catalog built without ``--eqlegendstools`` when ``rules/hand-lists.json`` takes the items of a zone from that site (its provenance must name the zone page). It precomputes every trio of the grid at its default scope
(a pool of worker processes; chunk files and fingerprints stay in ``build/results/``), checks the release (every trio present, none partial, each at its scope; the
parity suite; a pruning spot check of one random scenario of each trio against the unpruned optimum; the invariants; every bundle against the catalog and through the
browser's own reader; the exact number of the files of the site), runs the **keyed** privacy scan over everything that ships, packs one ``tar.gz`` into
``build/release/``, and writes ``releases/<tag>.json`` (the pointer to commit) and ``reports/results-diff-<tag>.md`` (what changed since the last release, and why)
into the working tree, uncommitted. The full diff, which names items, is ``build/reports/results-diff-<tag>.json``,
away from the asset: it is not for git, and an upload of ``build/release/<tag>.tar.gz`` cannot take it. The build prints counts, the places of what it wrote, and warnings; never an item.

A run that is stopped (Ctrl-C, a crash, the computer switched off) is run again with the same command: trios that are finished are skipped, and chunk files made
from the same inputs are kept. A failed check, a missing, partial or wrong-scope trio, or a finding of the privacy scan stops the build before packing and leaves
no output. ``--trios a,b`` builds some trios only, as a trial: it writes no pointer, nothing in ``releases/`` or ``reports/``, and uses up no tag (its asset and its
two reports are in ``build/trial/``, and both reports are headed TRIAL). A release is the whole grid. What the build starts from is recorded once, at the start: the
hash of the code, the HEAD of the checkout with a digest of its status and one of its diff, the rules and the catalog. Run the build from a git worktree of its own, at the
commit to release; it is refused (at the end of the precompute and again before it packs) if any of them changed while it ran, and a worker that starts after a change
refuses its trios. A run that did not end leaves nothing that looks like a release: the next build of the tag takes away its asset, its full diff of the first round and
its Markdown report (a report, or the temporary file of a write that was cut short, that is tracked by git is refused, with the reason, and so is a git that cannot say whether
one is), and an error between the packing and the pointer takes the asset away. Every private file is checked, before it is written, for a link or junction on the way and
against ``git check-ignore`` for the path itself, and the build folder must be ignored as a whole (or lie outside the work tree). Exit status: 0 built (a standard output
that closes after the build, such as a pipe whose reader has gone, or that is not there at all, as under pythonw, is no failure: the build is finished, and a warning goes to
standard error; a line that the encoding of the console cannot write is written with ``?`` for the characters it cannot, and silences nothing), 2 refused or failed (one line
on standard error; ``TRIOFORGE_DEBUG`` adds the traceback), 130 interrupted.

The private key is given here by its path and read at run time; nothing is copied from it, and no output carries it.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline"))  # (a worker process started by the pool runs this file again, and needs the same)

from trioforge.precompute import assemble, release  # noqa: E402
from trioforge.precompute.assemble import ReleaseRefused  # noqa: E402


def _encodable(stream: object, text: str) -> str:
    """``text`` as the encoding of ``stream`` can write it, with ``?`` for each character it cannot (``errors="replace"``): a console in an old code page loses a
    character of a line, not the lines after it. A stream with no encoding, or one that is not known, gets the text as it is."""
    encoding = getattr(stream, "encoding", None)
    if not isinstance(encoding, str):
        return text
    try:
        return text.encode(encoding, "replace").decode(encoding, "replace")
    except (LookupError, ValueError):
        return text


class _Lines:
    """The lines the command prints. A standard output that closes (a pipe whose reader has gone), or that is not there at all (``sys.stdout`` is None, as under
    pythonw), stops the printing and nothing else: the build goes on, and its outputs are written whether or not anyone is reading. A line that the encoding of the
    console cannot write is no closed pipe: it is written with ``?`` for the characters it cannot (:func:`_encodable`)."""

    def __init__(self) -> None:
        self.closed = False

    def say(self, text: str) -> None:
        if self.closed:
            return
        stream = sys.stdout
        if stream is None:
            self.closed = True
            return
        try:
            print(_encodable(stream, text), file=stream, flush=True)
        except (OSError, ValueError):  # (a BrokenPipeError is an OSError; a closed file is a ValueError)
            self.closed = True

    def warn(self, text: str) -> None:
        try:
            print(text, file=sys.stderr, flush=True)
        except (OSError, ValueError):
            pass


class _Usage(Exception):
    """A wrong argument: the message is one line."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise _Usage(message)


def _positive(text: str) -> int:
    try:
        number = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _tag(text: str) -> str:
    try:
        return assemble.check_tag(text)
    except ReleaseRefused as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _trios(text: str) -> tuple[str, ...]:
    found = tuple(word.strip() for word in text.split(",") if word.strip())
    if not found:
        raise argparse.ArgumentTypeError("needs at least one trio, such as pal-mnk-ber")
    for slug in found:
        if not assemble.is_trio_slug(slug):
            raise argparse.ArgumentTypeError(f"{slug!r} is not a trio (three class codes in class order, joined by '-', such as pal-mnk-ber)")
    return found




def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="release-build.py", description=__doc__.split("\n\n")[0], allow_abbrev=False)
    parser.add_argument("--tag", required=True, type=_tag, help="the release tag: data-YYYY-MM-DD, and -N after it for a second release of a day")
    parser.add_argument("--privacy-key", required=True, type=Path, help="the private key file of the privacy scan (64 hex digits)")
    parser.add_argument(
        "--processes", type=_positive, default=max(1, (os.cpu_count() or 2) - 4), help="worker processes, one trio each (default: all cores but four)"
    )
    parser.add_argument("--trios", type=_trios, help="build only these trios (comma-separated slugs): a trial, which writes no pointer")
    parser.add_argument("--catalog", type=Path, help="the public catalog (default: derived/catalog.json)")
    parser.add_argument("--previous", default="auto", help="the release to compare with: auto (the newest older one whose asset is in build/release/), none, or an asset or folder")
    parser.add_argument(
        "--parity-stride", type=_positive,
        help="the stride n of the sample of the shard parity: one chunk in n is solved again by the browser engine, from an offset drawn from the snapshot id of the "
        "release (default and largest allowed: the smallest trio's number of chunks, so that every trio has chunks in the sample; a smaller n is a bigger sample)",
    )  # fmt: skip
    parser.add_argument(
        "--parity-processes", type=_positive, default=max(1, min(12, (os.cpu_count() or 2) // 2)),
        help="Node processes the shard parity is divided between, each doing its part of all the work, side by side (default: half the cores, at most 12; 1 is one process)",
    )  # fmt: skip
    parser.add_argument("--build-dir", type=Path, help="the build folder (default: build/); it must be git-ignored, or outside every repository")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _Usage as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    lines = _Lines()
    try:
        result = release.build_release(
            tag=args.tag, root=REPO, privacy_key=args.privacy_key.resolve(), processes=args.processes, trios=args.trios,
            trial=args.trios is not None, catalog=args.catalog.resolve() if args.catalog else None, build_dir=args.build_dir.resolve() if args.build_dir else None,
            previous=args.previous, parity_stride=args.parity_stride, parity_processes=args.parity_processes, say=lines.say,
        )  # fmt: skip
    except ReleaseRefused as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted: the chunks and the trios that are finished are kept; run it again with the same command to continue", file=sys.stderr)
        return 130
    except Exception as error:  # noqa: BLE001 - the last stop: say the kind, and the traceback only when asked
        print(f"error: {type(error).__name__}: {' '.join(str(error).split())}", file=sys.stderr)
        if os.environ.get("TRIOFORGE_DEBUG"):
            traceback.print_exc()
        return 2
    lines.say(f"built {result.tag}: {result.trios} trios, {result.site_files:,} files in the site, {result.changes} changes since {result.previous or 'nothing'}")
    lines.say(f"asset: {result.asset}")
    lines.say(f"sha256: {result.asset_sha256}")
    if result.pointer is not None:
        lines.say(f"pointer: {result.pointer} (commit it)")
        lines.say(f"report: {result.reports[0]} (commit it with the pointer)")
        lines.say(f"full diff: {result.reports[1]} (it names items: it is not for git)")
    else:
        lines.say("TRIAL build: no pointer was written, nothing is in releases/ or reports/, and this is no release")
        lines.say(f"reports: {result.reports[0]} and {result.reports[1]}")
    for warning in result.warnings:
        lines.warn(f"warning: {warning}")
    if result.solver_diffs:
        lines.warn(
            f"SOLVER DIFF: {result.solver_diffs} change(s) with the same inputs and another answer: a bug until it is explained "
            f"(read the results-diff report {result.reports[0]}, and the full diff in the build folder, before tagging)"
        )
    if lines.closed:
        lines.warn(
            "warning: standard output was closed, so part of what the build says was not printed; the release is built and its outputs are written "
            f"(asset {result.asset}, sha256 {result.asset_sha256}" + (f", pointer {result.pointer}" if result.pointer is not None else "") + ")"
        )
    return 0


def _flush_stdout() -> None:
    """Flush standard output at the very end, after the build, where a failure to do so must not change the exit status."""
    stream = sys.stdout
    if stream is None:  # no standard output at all (pythonw): there is nothing to flush, and nothing for the interpreter to flush at exit
        return
    try:
        stream.flush()
    except (OSError, ValueError):  # the reader of the pipe has gone: point standard output at the null device, or the interpreter fails when it flushes it at exit
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), stream.fileno())
        except (OSError, ValueError, AttributeError):
            pass


if __name__ == "__main__":
    status = main()
    _flush_stdout()
    sys.exit(status)
