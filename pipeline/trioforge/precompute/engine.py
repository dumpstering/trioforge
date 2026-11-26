"""The browser engine's data files of a precompute run: the bundle of the trio and the item table.

A run writes ``<trio>/engine-l<level>.json`` (:func:`trioforge.export.browser.bundle`) and ``<results>/items.json``
(:func:`trioforge.export.browser.items`) with its other result files (see :mod:`trioforge.precompute.shards` for the format). They are
made here from the inputs the run solves with, so that their evidence levels are the shards' own:

* the **catalog document** the run was given (``catalog_path``, never the default one when another was passed), read once more at the
  start of the run and checked against what the run read for itself: the usable items of the trio and their evidence levels, seen
  flags merged, must be exactly the run's (``Config.items`` and ``Config.levels``), or the catalog or the flags changed between the
  two readings and the run stops. The run can take hours, so the texts are made at the start, from the inputs of that moment;
* the **private seen flags** (``seen_path``), merged the way the run merges them: a seen item is strict unless a patch or a research
  removal hides it. They reach the item table (every item's level) and the pools the weapon setups of each evidence level are read
  from. Nothing in either file says that a flag was merged.

Both files carry the **fingerprint of the inputs** of the run (:func:`trioforge.export.browser.inputs_fingerprint`): the SHA-256 of the catalog
file the run read and of the key and evidence level of every item of the item table, the flags merged. The build refuses a folder in which a trio's
bundle and ``items.json`` do not share one, and says which trio to run again. It is made of what the published table says, never of the flags
themselves (a digest of the list of flags could be tried against guesses about flags that change no level), and with no table there is none: a
bundle is then written without one, and the build refuses it.

The weapon setups of the bundle are checked against the grid of the run (the setups of each role and level the run solves): the
shards and the bundle must agree, or the run stops before it has solved anything. A file that cannot be made is not a stop but a
**violation** (the exporter refuses a pool that makes the setups depend on the race, a buff with a part that is not a whole number, an
item the tier rules cannot read): the shards are still the run's result, and the missing file is listed with the other violations. (An
item of the trio's own pool that cannot be read fails the solves, as it always did, with the scenario it failed in.)

The item table is one file for the results folder. :func:`write_items` leaves a byte-identical file alone and replaces another one whole; the run writes
it after the files of the trio (so that a write of those that fails leaves the table as it was), and a table that cannot be made is removed
(:func:`remove_items`), as a bundle that cannot be made is: no stale file stands beside new ones.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trioforge.model import weapons as wp
from trioforge.precompute import grid, shards
from trioforge.sources.client_tables import commit_files

__all__ = ["EngineError", "EngineTexts", "level_setups", "make", "remove_items", "write_items"]


class EngineError(ValueError):
    """The engine files cannot be made consistently with the run: the run is stopped."""


@dataclass(frozen=True)
class EngineTexts:
    """The text of the two files. ``bundle`` or ``items`` is None when that file could not be made, and ``problems`` says why (one line
    each)."""

    bundle: str | None
    items: str | None
    problems: tuple[str, ...] = ()


def level_setups(plan: Sequence[grid.Scenario]) -> dict[str, dict[str, list[str]]]:
    """The weapon setups of each role at each evidence level that a plan of scenarios solves, in the order of ``wp.setup_order`` of the role (which breaks a tie)."""
    found: dict[str, dict[str, set[str]]] = {}
    for scenario in plan:
        found.setdefault(scenario.evidence, {}).setdefault(scenario.role, set()).add(scenario.setup)
    return {
        kind: {role: sorted(setups, key=wp.setup_order(role).index) for role, setups in by_role.items()} for kind, by_role in found.items()
    }


def make(
    codes: Sequence[str], config: grid.Config, meta: grid.Meta, tables: Any, *, catalog_path: str | Path,
    seen_path: str | Path | None, setups: Mapping[str, Mapping[str, Sequence[str]]],
) -> EngineTexts:
    """The text of the bundle and of the item table of a run (see the module docstring). ``setups`` are the weapon setups of each
    role at each level that the grid of the run solves (:func:`level_setups`). ``EngineError`` (a ``ValueError``) when the catalog
    or the seen flags are not the ones the run read, or when the bundle's setups differ from the grid's; other ``ValueError`` s and
    ``OSError`` s are those of reading the inputs."""
    from trioforge.data import catalog as catalog_module  # not at the top: a worker process imports this package too
    from trioforge.data.jsonio import MAX_FILE_BYTES, JsonFileError, loads_strict
    from trioforge.export import browser

    path = Path(catalog_path)
    data = path.read_bytes()  # read once: the fingerprint is of the bytes the document was parsed from
    if len(data) > MAX_FILE_BYTES:
        raise EngineError(f"{path.name}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MiB")
    try:
        document = loads_strict(data.decode("utf-8"), path.name)
    except UnicodeDecodeError:
        raise EngineError(f"{path.name}: not valid UTF-8") from None
    except JsonFileError as error:
        raise EngineError(str(error)) from None
    catalog_sha256 = hashlib.sha256(data).hexdigest()
    seen = catalog_module.load_seen_keys(seen_path) if seen_path is not None else frozenset()
    selection = grid.select_items(document["items"], codes, seen)
    if selection.items != list(config.items) or selection.levels != config.levels:
        raise EngineError(
            "the catalog or the seen flags changed while the run was starting: the items of the trio and their evidence levels "
            "are not the ones the run read first; run again"
        )
    problems: list[str] = []
    table: str | None = None
    inputs: str | None = None
    try:  # the table first: the fingerprint of the inputs is made of it
        listing = browser.items(document, tables.rules, seen=seen)
        inputs = browser.inputs_fingerprint(catalog_sha256, listing)
        table = browser.render_items(browser.with_inputs(listing, inputs))
    except ValueError as error:
        problems.append(f"the item table was not written ({shards.ITEMS_NAME}): {error}")
    text: str | None = None
    try:
        made = browser.bundle(
            codes, config.level, tables, tables.rules, config.spells, data_release=meta.data_release, catalog=document, seen=seen, procs=config.procs
        )
    except ValueError as error:
        problems.append(f"the browser bundle was not written ({shards.engine_name(config.level)}): {error}")
    except RuntimeError as error:  # the exporter's own check that its profiles reassemble: a fault of the code
        raise EngineError(f"the browser bundle does not reassemble to the profiles of the run: {error}") from error
    else:
        _check_setups(made, setups)
        text = browser.render_bundle(made if inputs is None else browser.with_inputs(made, inputs))
    return EngineTexts(text, table, tuple(problems))


def _check_setups(made: Mapping[str, Any], setups: Mapping[str, Mapping[str, Sequence[str]]]) -> None:
    """The bundle lists, for each role and evidence level, the setups the grid of the run solves for it."""
    for kind, by_role in setups.items():
        for role, solved in by_role.items():
            listed = made["roles"][role]["setups_by_evidence"][kind]
            if list(listed) != list(solved):
                raise EngineError(
                    f"the weapon setups of the {role} role at the {kind} evidence level are {' '.join(solved)} in the grid of the run "
                    f"and {' '.join(listed)} in the browser bundle: the shards and the bundle would not describe one pool"
                )


def remove_items(out_dir: str | Path) -> bool:
    """Take ``items.json`` out of ``out_dir`` (a run that could not make the table of its own inputs leaves no table of other inputs standing, as a
    bundle that cannot be made is not left either). Returns whether there was one."""
    path = Path(out_dir) / shards.ITEMS_NAME
    if not path.is_file():
        return False
    path.unlink()
    return True


def write_items(out_dir: str | Path, text: str) -> tuple[Path, str]:
    """Put the item table ``text`` in ``out_dir`` as ``items.json``: all or nothing. Returns ``(path, state)``: ``"new"`` when
    there was none, ``"same"`` when the file there was byte for byte this one (it is not written again) and ``"replaced"`` when it
    was another one (made from other inputs)."""
    folder = Path(out_dir)
    path = folder / shards.ITEMS_NAME
    state = "new"
    if path.is_file():
        state = "same" if path.read_bytes() == text.encode("utf-8") else "replaced"
    if state != "same":
        commit_files(folder, {shards.ITEMS_NAME: text}, last=shards.ITEMS_NAME)
    return path, state
