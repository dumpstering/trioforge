"""The precompute after an independent review of its correctness: the pool of each race, legal runner-ups, the optimality
checks, the fingerprint of the chunks, one run for every result file and the loose ends.

Every name, item and number here is invented. The helpers (the invented catalog, ``independent``, ``expand`` ...) are those of
``test_precompute.py``; the tiny run (two races, Balanced, +0 and +4) is its ``tiny`` fixture.
"""

import ast
import dataclasses
from pathlib import Path

import pytest
from test_precompute import (  # noqa: F401 - tiny and fresh are fixtures
    CATALOG,
    SLUG,
    TABLES,
    TINY,
    TINY_CHUNKS,
    TRIO,
    context_of,
    expand,
    fresh,
    independent,
    make_item,
    read,
    runnerup_docs,
    tiny,
    weapon,
    write_catalog,
)

from trioforge import precompute as pc
from trioforge.model import weapons as wp
from trioforge.model.items import SLOT_INSTANCES
from trioforge.precompute import grid
from trioforge.solver import solve as solve_module

LEGS = SLOT_INSTANCES.index("LEGS")
PRIMARY, SECONDARY = SLOT_INSTANCES.index("PRIMARY"), SLOT_INSTANCES.index("SECONDARY")


# ---- the pool of a race (item 1) ----------------------------------------------------------------------------------------


def test_each_race_is_pruned_for_itself_so_greaves_only_a_troll_wears_cannot_empty_the_legs_of_an_ogre(tmp_path):
    """The Troll greaves beat the plain ones in every dimension, so the pruning of a Troll drops the plain greaves. A chunk
    that pruned once, with the first race, left the Ogre, who cannot wear the Troll greaves, with nothing in the legs place."""
    zulu = make_item("w9027", "Test Zulu Greaves", ["LEGS"], stats={"AC": 99, "STA": 99}, weight=1.0, races=["TRL"])
    plain = make_item("w9028", "Test Plain Greaves", ["LEGS"], stats={"AC": 10, "STA": 5}, weight=2.0)
    items = [*CATALOG, zulu, plain]
    out = tmp_path / "out"
    pc.run(SLUG, out, catalog=write_catalog(tmp_path / "catalog.json", items), processes=1, **TINY)
    rows = expand(read(out / SLUG / "wiki-own.json"))
    assert rows[("TRL", "balanced", 4, "dw")]["kit"][LEGS] == "w9027"
    assert rows[("OGR", "balanced", 4, "dw")]["kit"][LEGS] == "w9028"  # not an empty place
    for (race, role, tier, setup), row in rows.items():
        full, *_ = independent(items, tier, race, role, setup, "own", "wiki", pruned=False)
        assert row["F"] == pytest.approx(full.F, rel=1e-9, abs=0.006), (race, tier, setup)


def test_races_that_wear_the_same_race_only_items_share_one_pruned_pool(tmp_path, monkeypatch):
    zulu = make_item("w9027", "Test Zulu Greaves", ["LEGS"], stats={"AC": 99, "STA": 99}, weight=1.0, races=["TRL"])
    duo = make_item("w9029", "Test Duo Greaves", ["LEGS"], stats={"AC": 50}, weight=1.0, races=["OGR", "IKS"])
    ctx = context_of(tmp_path, [*CATALOG, zulu, duo])
    pruned_for = []
    real = grid.prune

    def spy(pool, profile, *args, **kwargs):
        pruned_for.append(profile.race)
        return real(pool, profile, *args, **kwargs)

    monkeypatch.setattr(grid, "prune", spy)
    doc = grid.solve_chunk(ctx, grid.ChunkKey("wiki", "own", "balanced", "dw", 4), ["HUM", "TRL", "OGR", "IKS", "BAR"])
    # Human and Barbarian wear neither item, Ogre and Iksar the same one: three pools, made with the first race of each set
    assert pruned_for == ["HUM", "TRL", "OGR"]
    assert [row["race"] for row in doc["rows"]] == ["HUM", "TRL", "OGR", "IKS", "BAR"]
    assert doc["pruned"] <= doc["pool"]


# ---- runner-ups that are legal kits (item 2) ----------------------------------------------------------------------------


CASTER_TRIO = ("PAL", "MNK", "CLR")  # a caster in the trio: Balanced is offered the stick setup, in which any item stands in any hand


def test_runner_ups_under_the_stick_setup_never_offer_an_off_hand_item_beside_a_two_hander(tmp_path):
    staff = make_item(
        "w9030", "Test Big Staff", ["PRIMARY"], stats={"STA": 60, "WIS": 60, "AC": 30}, weight=4.0, weapon=weapon("2H Blunt", 20, 40)
    )
    orb = make_item("w9031", "Test Off Orb", ["SECONDARY"], stats={"STA": 5, "WIS": 5})
    config, _ = grid.load_inputs(CASTER_TRIO, catalog_path=write_catalog(tmp_path / "catalog.json", [*CATALOG, staff, orb]))
    ctx = grid.Context(config)
    assert "stick" in wp.setups_for(CASTER_TRIO, "balanced", ctx.tables, level=50)
    row = grid.solve_chunk(ctx, grid.ChunkKey("wiki", "own", "balanced", "stick", 4), ["OGR"])["rows"][0]
    assert row["kit"][PRIMARY] == "w9030" and row["kit"][SECONDARY] is None  # the staff takes both hands
    entry = grid.RunnerupInput("OGR", "stick", tuple(row["kit"]), tuple(row["buffs"]), row["haste"])
    places = grid.runnerup_chunk(ctx, "balanced", 4, [entry])["views"][0]["places"]
    assert places[SECONDARY] == []  # nothing can stand beside the two-hander
    vecs = ctx.vecs(4)
    kit = [vecs[key] if key else None for key in row["kit"]]
    offered = 0
    for index, swaps in enumerate(places):
        for key, _ in swaps:
            trial = list(kit)
            trial[index] = vecs[key]
            locked = sorted(vecs[key].deity or ())
            assert grid.check_kit(trial, "stick", CASTER_TRIO, deity=locked[0] if locked else None, race="OGR") == [], (index, key)
            offered += 1
    assert offered  # there were swaps to look at


def test_every_swap_a_run_offers_is_a_legal_kit(tiny):
    ctx = grid.Context(grid.load_inputs(TRIO, catalog_path=tiny.catalog)[0])
    rows = expand(read(tiny.dir / "wiki-own.json"))
    for (role, tier), doc in runnerup_docs(tiny.dir).items():
        vecs = ctx.vecs(tier)
        for race, setup, places in doc["views"]:
            kit = [vecs[key] if key else None for key in rows[(race, role, tier, setup)]["kit"]]
            for index, swaps in enumerate(places):
                for item, _ in swaps:
                    key = doc["items"][item][0]
                    trial = list(kit)
                    trial[index] = vecs[key]
                    locked = sorted(vecs[key].deity or ())
                    assert grid.check_kit(trial, setup, TRIO, deity=locked[0] if locked else None, race=race) == []


# ---- a real optimality check (item 3) -----------------------------------------------------------------------------------


@pytest.mark.parametrize("factor", [1 + 1e-4, 1 - 1e-4], ids=["overstated", "understated"])
def test_a_model_objective_that_differs_from_the_evaluators_value_in_either_direction_stops_the_run(tmp_path, monkeypatch, factor):
    real = solve_module.solve_canonical

    def skewed(milp, time_limit=None):
        solution = real(milp, time_limit)
        return dataclasses.replace(solution, model_F=solution.F * factor)

    monkeypatch.setattr(solve_module, "solve_canonical", skewed)
    with pytest.raises(pc.PrecomputeError, match="objective re-check") as caught:
        pc.run(SLUG, tmp_path / "out", catalog=write_catalog(tmp_path / "catalog.json"), processes=1, **TINY)
    assert "model" in str(caught.value) and "balanced role" in str(caught.value)


def test_a_model_objective_within_the_exactness_tolerance_is_no_error(tmp_path, monkeypatch):
    real = solve_module.solve_canonical

    def close(milp, time_limit=None):
        solution = real(milp, time_limit)
        return dataclasses.replace(solution, model_F=solution.F * (1 + solve_module.EXACTNESS_TOLERANCE / 10))

    monkeypatch.setattr(solve_module, "solve_canonical", close)
    summary = pc.run(SLUG, tmp_path / "out", catalog=write_catalog(tmp_path / "catalog.json"), processes=1, **TINY)
    assert summary.solved == 40 and not summary.violations


def test_a_plain_swap_that_beats_the_kit_is_a_violation_that_stops_the_run(tiny, tmp_path):
    config, _ = grid.load_inputs(TRIO, catalog_path=tiny.catalog)
    ctx = grid.Context(config)
    row = expand(read(tiny.dir / "wiki-own.json"))[("OGR", "balanced", 4, "dw")]
    head = SLOT_INSTANCES.index("HEAD")
    assert row["kit"][head] is not None
    kit = list(row["kit"])
    kit[head] = None  # a kit that is not the best there is: the helm it lacks is a swap of an item anyone can wear that beats it
    entry = grid.RunnerupInput("OGR", "dw", tuple(kit), tuple(row["buffs"]), row["haste"])
    doc = grid.runnerup_chunk(ctx, "balanced", 4, [entry])
    named = [text for text in doc["violations"] if "HEAD" in text]
    assert len(named) == 1 and "beats the kit" in named[0] and row["kit"][head] in named[0] and "OGR" in named[0]
    # the run stops on it, and writes nothing for the runner-ups of that role and tier
    grid.init_worker(config)
    path = tmp_path / "r.json"
    result = grid.run_task({"kind": "runnerups", "role": "balanced", "tier": 4, "entries": [entry], "basis": "x", "path": str(path)})
    assert result["ok"] is False and result["error"] == "ScenarioError" and "beats the kit" in result["message"]
    assert not path.exists()
    # the kit the solver found has none, though a swap of an item that needs a deity may beat it
    honest = grid.RunnerupInput("OGR", "dw", tuple(row["kit"]), tuple(row["buffs"]), row["haste"])
    doc = grid.runnerup_chunk(ctx, "balanced", 4, [honest])
    assert doc["violations"] == []
    assert any(delta > 0 for swaps in doc["views"][0]["places"] for _, delta in swaps)  # a locked item that beats the pick


def test_each_chunk_audits_one_race_against_an_unpruned_solve_and_the_races_rotate(tiny):
    docs = [read(path) for path in sorted((tiny.dir / "chunks").glob("s-*.json"))]
    assert len(docs) == TINY_CHUNKS
    audited = [doc["audit"] for doc in docs if doc["audit"] is not None]
    assert len(audited) == 12  # the wiki chunks; the strict pool is empty, so there is nothing to prune and nothing to audit
    assert {doc["audit"] for doc in docs if doc["pool"] == 0} == {None}
    assert {entry["race"] for entry in audited} == {"OGR", "TRL"}  # the audited race changes from chunk to chunk
    for doc in docs:
        if doc["audit"] is not None:
            row = next(row for row in doc["rows"] if row["race"] == doc["audit"]["race"])
            assert doc["audit"]["F"] == pytest.approx(row["F"], rel=1e-9)  # the same value from the pool without pruning
    assert tiny.summary.audited == 12


def lossy_prune(monkeypatch):
    """A pruning that loses the chest piece every best kit wears, for the run to catch."""
    real = grid.prune

    def lossy(pool, *args, **kwargs):
        return [item for item in real(pool, *args, **kwargs) if item.key != "w9006"]

    monkeypatch.setattr(grid, "prune", lossy)


def test_a_deliberately_broken_prune_is_caught_by_the_run(tmp_path, monkeypatch, tiny):
    assert "w9006" in expand(read(tiny.dir / "wiki-own.json"))[("OGR", "balanced", 4, "dw")]["kit"]  # the piece the break loses
    lossy_prune(monkeypatch)
    with pytest.raises(pc.PrecomputeError) as caught:
        pc.run(SLUG, tmp_path / "out", catalog=tiny.catalog, processes=1, **TINY)
    message = str(caught.value)
    assert "unpruned" in message and "wiki evidence" in message  # which chunk, and what was compared
    assert not list((tmp_path / "out" / SLUG).glob("*.json"))


def test_the_runner_ups_catch_a_broken_prune_even_when_the_audit_is_off(tmp_path, monkeypatch, tiny):
    lossy_prune(monkeypatch)
    monkeypatch.setattr(grid, "audit_race", lambda *args, **kwargs: None)
    with pytest.raises(pc.PrecomputeError, match="beats the kit"):
        pc.run(SLUG, tmp_path / "out", catalog=tiny.catalog, processes=1, **TINY)


# ---- what the fingerprint of the chunks covers (item 6) -----------------------------------------------------------------


PACKAGE = Path(grid.__file__).resolve().parents[1]  # pipeline/trioforge
SOURCE_ROOT = PACKAGE.parent  # pipeline

#: the modules the solves import that the fingerprint does not hash, each with why nothing it does can change a chunk
NOT_HASHED = {
    "trioforge.data.catalog": "builds the catalog and reads the seen flags; the fingerprint holds the hash of the catalog "
    "and of the seen keys, all of its output a result depends on",
    "trioforge.data.jsonio": "reads and writes strict JSON: a value passes through it unchanged or is refused",
    "trioforge.sources.client_tables": "reads and writes the client table files; the fingerprint holds the hash of each",
    "trioforge.precompute": "the runner: processes, files and summaries; nothing it computes enters a chunk",
    "trioforge.precompute.shards": "writes and reads the chunk and result files: their format is CODE_VERSION, and the "
    "order of a totals row is in the fingerprint",
    "trioforge.precompute.seals": "the seals and flip notes of the result files; not computed in a chunk",
    "trioforge.precompute.kitwhy": "the why of the default kit, made from the finished chunks' kits for defaults.json; not computed in a chunk",
    "trioforge.precompute.engine": "the browser engine's two files (bundle and item table), made from the inputs the fingerprint holds; "
    "not computed in a chunk",
    "trioforge.precompute.__main__": "the command line",
    "trioforge.precompute.assemble": "the release folder, its pointer and its asset: made from finished result files, with hashes; "
    "not computed in a chunk",
    "trioforge.precompute.release": "the PC release build: a pool of runs, the checks of finished result files, the privacy scan and the outputs; "
    "not computed in a chunk",
}


def module_file(name):
    base = SOURCE_ROOT.joinpath(*name.split("."))
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    return base / "__init__.py" if (base / "__init__.py").is_file() else None


def module_name(path):
    parts = path.relative_to(SOURCE_ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imports_of(path):
    """Every module of the package that a source file imports, anywhere in it (inside a function too)."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names if alias.name.split(".")[0] == "trioforge"}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path.name}: a relative import"
            if node.module and node.module.split(".")[0] == "trioforge":
                names.add(node.module)
                names |= {f"{node.module}.{alias.name}" for alias in node.names if module_file(f"{node.module}.{alias.name}")}
    return names


def is_marker(path):
    """A package file with no code in it: a docstring and dunder names (``__version__``) only."""
    body = ast.parse(path.read_text(encoding="utf-8")).body
    return path.name == "__init__.py" and all(
        isinstance(node, ast.Expr) or (isinstance(node, ast.Assign) and all(t.id.startswith("__") for t in node.targets))
        for node in body
    )


def test_the_chunk_fingerprint_covers_every_module_the_solves_import_or_says_why_it_need_not():
    hashed = {module_name(path) for path in grid.code_files()}
    assert "trioforge.sources.client_spells" in hashed  # LIMIT_SPA, which the buff engine reads
    unexplained: dict[str, list[str]] = {}
    reached: set[str] = set()
    for path in (PACKAGE / "precompute").glob("*.py"):  # the precompute package: grid is hashed, the rest is explained
        name = module_name(path)
        if name not in hashed:
            reached.add(name)
            if name not in NOT_HASHED:
                unexplained.setdefault(name, []).append("the precompute package")
    queue, visited = sorted(hashed), set()
    while queue:  # what a hashed module imports is hashed or explained; only a hashed module can change a chunk
        name = queue.pop()
        if name in visited:
            continue
        visited.add(name)
        for imported in imports_of(module_file(name)):
            if imported in hashed:
                queue.append(imported)
                continue
            reached.add(imported)
            if imported not in NOT_HASHED and not is_marker(module_file(imported)):
                unexplained.setdefault(imported, []).append(name)
    assert not unexplained, (
        f"imported by a module of the chunks, and neither hashed into their fingerprint (grid.CODE_FILES) nor listed in "
        f"NOT_HASHED with the reason no result depends on its code: {unexplained}"
    )
    assert set(NOT_HASHED) <= reached, f"no longer imported, take them out of NOT_HASHED: {sorted(set(NOT_HASHED) - reached)}"
    assert not set(NOT_HASHED) & hashed  # nothing is both


def test_a_change_in_a_hashed_source_file_changes_the_fingerprint_of_the_chunks(monkeypatch):
    before = grid._code_hash()
    spells = PACKAGE / "sources" / "client_spells.py"
    real = Path.read_bytes

    def changed(path):
        data = real(path)
        return data + b"# a change\n" if path == spells else data

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert grid._code_hash() != before  # the buff engine reads LIMIT_SPA from that file


def test_the_order_of_a_totals_row_is_part_of_the_fingerprint_so_chunks_in_another_order_are_redone(tmp_path, monkeypatch):
    catalog = write_catalog(tmp_path / "catalog.json")
    before = grid.load_inputs(TRIO, catalog_path=catalog)[0].fingerprint
    assert grid.load_inputs(TRIO, catalog_path=catalog)[0].fingerprint == before
    monkeypatch.setattr(grid.shards, "TOTALS_KEYS", tuple(reversed(grid.shards.TOTALS_KEYS)))
    assert grid.load_inputs(TRIO, catalog_path=catalog)[0].fingerprint != before
