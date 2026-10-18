"""The results of a real precompute run on the invented catalog of the site fixture, for the shard parity test of the browser engine.

``fixtures/site/results`` (the results of the site fixture) is hand-written: its shards hold invented kits and values that no solver
wrote, so the engine cannot be held to them. The shard parity test (``tests-js/shard-parity.test.mjs``) needs shards that the
precompute really solved, and the engine's two files made from the very catalog it solved. They are made here: the invented catalog
of ``engine_fixture.py`` (the items of the fixture's shards, with invented stats) is given to :func:`trioforge.precompute.run`, which
writes its shards, ``defaults.json``, the bundle ``engine-l50.json`` and the item table ``items.json`` as it does for the real
catalog, narrowed to two races, two roles and two tiers so that the browser engine can solve every view of it in a few seconds:

* ``fixtures/site/results-solved/pal-mnk-ber/{strict,wiki}-{own,group}.json``, ``defaults.json`` and ``engine-l50.json``;
* ``fixtures/site/results-solved/items.json``.

The runner-ups, the seals and the chunk files of the run are not kept: the parity test reads none of them. Nothing here is a
real item: ``test_site_fixture_items.py`` scans the whole of ``fixtures/site``, this folder included.

``test_shard_fixture.py`` makes the files again and fails when a committed one differs. After a change to the model, the solver, the
exporter, the rules or the invented catalog, write them again with::

    PYTHONPATH=pipeline .venv/bin/python pipeline/tests/shard_fixture.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from engine_fixture import REPO, SLUG, catalog

RESULTS = REPO / "fixtures" / "site" / "results-solved"
RACES = ["OGR", "IKS"]  # an Ogre (it wears an item that only Ogres and Trolls wear) and an Iksar (the Iksar armor class)
ROLES = ["balanced", "melee"]  # five weapon setups between them
TIERS = [0, 4]
SHARDS = tuple(f"{evidence}-{buffs}.json" for evidence in ("strict", "wiki") for buffs in ("own", "group"))
FILES = ("items.json", *(f"{SLUG}/{name}" for name in (*SHARDS, "defaults.json", "engine-l50.json")))


def texts() -> dict[str, str]:
    """The text of each file of the fixture, by its path under the folder, made by a run of the precompute in a scratch folder.

    The catalog is written as the exporter's own fixture hashes it (sorted keys, compact), so that the fingerprint of the inputs in the
    bundle and the item table is the one of ``engine_fixture.py``."""
    from trioforge import precompute

    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        path = root / "catalog.json"
        path.write_bytes(json.dumps(catalog(), sort_keys=True, separators=(",", ":")).encode("utf-8"))
        summary = precompute.run(
            SLUG, root / "results", catalog=path, processes=1, races=RACES, roles=ROLES, tiers=TIERS, robustness=False
        )
        if summary.violations:
            raise SystemExit("the precompute run on the invented catalog has violations: " + "; ".join(summary.violations))
        return {name: (root / "results" / name).read_bytes().decode("utf-8") for name in FILES}


def write_all() -> None:
    made = texts()
    for name, text in made.items():
        path = RESULTS / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(REPO).as_posix()} ({len(text.encode('utf-8')):,} bytes)")


if __name__ == "__main__":
    sys.exit(write_all())
