"""Tests for the parity fixtures: ``trioforge.export.fixtures`` and the modules behind it.

The fixtures hold the browser engine to the Python reference. Each file is one JSON document, and the tests check, on a small
run made for the purpose and on the sample that is committed under ``fixtures/parity``:

* **the format**: every file validates against ``fixtures.schema.json`` and the rules the schema cannot say, the manifest lists
  exactly the files with the size and SHA-256 of their text, and a run writes the same bytes for the same seed;
* **self-containment**: a case rebuilds its model from its own profile, buff set, records, pool and options, and the rebuilt
  model equals the stored one under the parity rules; the stored kit is worth, by the exact evaluator, the stored breakdown;
  the stored model solves to the stored value; the pruning a case records is reproduced from the case;
* **the families**: the brute-force maximum is exact and independent, the matrix and the neutral 36 cover what the plan
  promises, an Upgrade case is what the reference makes (Equip now, the farm path, the best 2 and 3 sets, Every slot), the
  evaluations, profiles, weight compositions, item vectors and tier tables are what the Python functions give;
* **publicness**: a fixture with real strict evidence, or one that names a key outside the public catalog, is rejected, and
  "strict" in a fixture is only the hash proxy;
* **the sample**: it is within its size budget, covers every stratum twice, and carries the data release and rules version of
  the shipped release (the test fails when they differ).

Every name in an invented instance is invented.
"""

import copy
import dataclasses
import gzip
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import solver_helpers as H
from after_an_add import AfterAnAdd, evidence_of
from trioforge import bench
from trioforge import upgrade as UP
from trioforge.data.jsonio import load_strict
from trioforge.export import brute, browser, fixture_cases, fixture_plan, fixture_tables, fixtures, milp_json
from trioforge.export.fixture_plan import REQUIRED_STRATA, matrix_plan, pmb36_plan, upgrade_plan
from trioforge.model import formulas as fm
from trioforge.model import roles, weapons
from trioforge.model.items import SLOT_GROUPS, SLOT_INSTANCES, at_tier
from trioforge.model.profile import Profile, eval_buffs, make_profile
from trioforge.model.tables import load as load_tables
from trioforge.model.tiers import cost_to_reach, tier_for_mode
from trioforge.precompute import grid
from trioforge.solver.prune import prune
from trioforge.solver.solve import TIE_TOLERANCE, solve_canonical

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "fixtures" / "parity"
TABLES = load_tables()
RULES = TABLES.rules
SEED = 7
REGENERATE = "python -m trioforge.export.fixtures --out fixtures/parity --sample"


# ---- helpers -----------------------------------------------------------------------------------------------------------------


def documents(root):
    """``{path: document}`` of every file the manifest of a folder lists."""
    manifest = fixtures.read_document(Path(root) / "manifest.json")
    return {entry["path"]: fixtures.read_document(Path(root) / entry["path"]) for entry in manifest["files"]}


def of_kind(docs, kind):
    return {path: doc for path, doc in docs.items() if doc.get("kind") == kind}


def cases_of(docs, *families):
    return {doc["id"]: doc for doc in docs.values() if doc.get("kind") == "case" and (not families or doc["family"] in families)}


def kit_of(items, entries):
    return [None if entry is None else items[f"{entry[0]}@{entry[1]}"] for entry in entries]


def stored_totals(case, buffs):
    buffset = fixture_cases.buffset_from_doc(case["inputs"]["buffset"])
    return None if buffset is None else fixture_cases.eval_totals_for(buffset, buffs)


def a_case(docs, family="matrix", needs=None):
    """A deep copy of a case of the family (the first one that ``needs`` accepts), to damage."""
    for doc in docs.values():
        if doc.get("kind") == "case" and doc["family"] == family and (needs is None or needs(doc)):
            return copy.deepcopy(doc)
    raise AssertionError(f"no {family} case")


def flagged(doc, catalog_keys, text):
    """Whether some reason ``public_problems`` gives for the document has the text in it."""
    return any(text in problem for problem in fixtures.public_problems(doc, catalog_keys))


def session_of(case):
    """The owned set and the candidates of an Upgrade case, read from the case alone."""
    items = fixtures.load_items(case)
    return {items[name]: count for name, count in case["inputs"]["owned"]}, [items[name] for name in case["inputs"]["candidates"]]


def base_options(case):
    """The options an Upgrade session is started with: the first program's, without the owned counts and the fixed haste."""
    return fixture_cases.options_from_json({**case["solves"][0]["options"], "haste_assumed": None, "owned_caps": {}})


@pytest.fixture(scope="module")
def inputs():
    return fixtures.shared_inputs()


@pytest.fixture(scope="module")
def catalog_keys(inputs):
    return set(inputs.items_by_key)


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    """A run at the test scale: a few of every family, as gzip files."""
    out = tmp_path_factory.mktemp("mini")
    return out, fixtures.generate(out, SEED, scale="mini", inputs=fixtures.shared_inputs())


@pytest.fixture(scope="module")
def mini_docs(mini):
    return documents(mini[0])


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    """A run at the smallest scale (hardly any case; every family is there), as gzip files."""
    out = tmp_path_factory.mktemp("tiny")
    return out, fixtures.generate(out, 42, scale="tiny", inputs=fixtures.shared_inputs())


@pytest.fixture(scope="module")
def sample_manifest():
    assert (SAMPLE / "manifest.json").is_file(), f"the sample is missing: run {REGENERATE}"
    return fixtures.read_document(SAMPLE / "manifest.json")


@pytest.fixture(scope="module")
def sample_docs(sample_manifest):
    return documents(SAMPLE)


# ---- a run: what it writes ---------------------------------------------------------------------------------------------------


def test_a_run_writes_every_family_and_a_manifest_that_lists_every_file(mini, inputs):
    out, manifest = mini
    assert manifest["complete"] is True and manifest["scale"] == "mini" and manifest["seed"] == SEED
    assert list(manifest["families"]) == list(fixtures.FAMILIES)
    counts = {name: row["count"] for name, row in manifest["families"].items()}
    assert counts["brute"] == 6 and counts["pmb36"] == 1 and counts["evaluate"] == 30 and counts["items"] == 16
    assert counts["upgrade"] == 4 and counts["profiles"] == 1 and counts["matrix"] == 3
    assert fixtures.read_document(out / "manifest.json") == manifest
    listed = [entry["path"] for entry in manifest["files"]]
    assert listed == sorted(listed) and len(set(listed)) == len(listed)
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == sorted([*listed, "manifest.json"])
    assert all(name.endswith(".json.gz") for name in listed)  # the test scale writes gzip files
    assert (manifest["data_release"], manifest["rules_version"]) == (inputs.data_release, RULES.version)
    assert manifest["solver"]["highs"] == "1.15.1"


def test_the_folder_validates_and_every_file_is_public(mini, catalog_keys):
    assert fixtures.validate_directory(mini[0], catalog_keys) == []


def test_a_gzip_file_holds_the_text_the_manifest_hashes_and_carries_no_time(mini):
    out, manifest = mini
    for entry in manifest["files"][:6]:
        raw = (out / entry["path"]).read_bytes()
        assert raw[:2] == b"\x1f\x8b" and raw[4:8] == b"\0\0\0\0"  # gzip, with a modification time of 0
        text = gzip.decompress(raw)
        assert len(text) == entry["bytes"] and hashlib.sha256(text).hexdigest() == entry["sha256"]
        text.decode("ascii")  # plain ASCII
        assert text.endswith(b"}\n") and b"\r" not in text


def test_a_second_run_in_another_process_with_another_hash_seed_writes_the_same_bytes(tiny, tmp_path):
    first, manifest = tiny
    other = tmp_path / "other"
    env = {**os.environ, "PYTHONHASHSEED": "2", "PYTHONPATH": str(REPO / "pipeline")}
    done = subprocess.run(
        [sys.executable, "-m", "trioforge.export.fixtures", "--out", str(other), "--seed", "42", "--scale", "tiny"],
        capture_output=True, text=True, env=env, cwd=REPO,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    names = sorted(p.relative_to(first).as_posix() for p in first.rglob("*") if p.is_file())
    assert len(names) >= 10 and names == sorted(p.relative_to(other).as_posix() for p in other.rglob("*") if p.is_file())
    for name in names:
        assert (first / name).read_bytes() == (other / name).read_bytes(), name
    assert manifest == fixtures.read_document(first / "manifest.json")


def test_a_second_run_in_this_process_writes_the_same_bytes_too_and_the_seed_matters(tiny, tmp_path, inputs):
    first, _ = tiny
    again = tmp_path / "again"
    fixtures.generate(again, 42, scale="tiny", inputs=inputs)
    names = sorted(p.relative_to(first).as_posix() for p in first.rglob("*") if p.is_file())
    assert names == sorted(p.relative_to(again).as_posix() for p in again.rglob("*") if p.is_file())
    assert all((first / name).read_bytes() == (again / name).read_bytes() for name in names)
    other = tmp_path / "seed"
    fixtures.generate(other, 43, scale="tiny", inputs=inputs, families=["brute", "evaluate"])
    assert (other / "brute" / "brute-000.json.gz").read_bytes() != (first / "brute" / "brute-000.json.gz").read_bytes()


# ---- the plan --------------------------------------------------------------------------------------------------------------


def test_the_seed_changes_the_filler_but_not_the_core_of_the_plan():
    one, two = matrix_plan(1, TABLES), matrix_plan(2, TABLES)
    core = len(one) - 28  # the special recipes and the lattice
    assert one[:core] == two[:core] and one[core:] != two[core:]
    assert [spec.id for spec in one] == [spec.id for spec in two] and len(one) == len({spec.id for spec in one})


def test_every_planned_role_and_setup_is_one_that_the_trio_plays():
    for plan in (matrix_plan(3, TABLES), pmb36_plan(TABLES), upgrade_plan(3)):
        for spec in plan:
            level = getattr(spec, "level", 50)
            assert spec.role in roles.roles_for(spec.trio), spec.id
            assert spec.setup in weapons.setups_for(spec.trio, spec.role, TABLES, level=level), spec.id


@pytest.mark.parametrize("seed", [1, 2, 20261014])
def test_the_matrix_plan_has_every_stratum_at_least_twice_for_every_seed(seed):
    plan = matrix_plan(seed, TABLES)
    counts = fixture_plan.tag_counts(plan)
    assert len(plan) >= 90
    for stratum in REQUIRED_STRATA:
        assert counts.get(stratum, 0) >= 2, stratum
    assert counts["evidence:strict-proxy"] >= 2 and counts["level:55"] >= 2 and counts["prune-check"] >= 5
    assert counts["deity"] >= 2 and counts["iksar"] >= 2 and counts["composed-weights"] >= 2


def test_the_strata_mean_what_the_plan_says_they_mean():
    by_id = {spec.id: spec for spec in matrix_plan(1, TABLES)}
    assert "mixed-mana" in by_id["matrix-003"].tags and "end-trio" in by_id["matrix-002"].tags
    assert "monk-below-10" in by_id["matrix-001"].tags and "monk-below-10" not in by_id["matrix-008"].tags  # +10
    assert "composed-weights" in by_id["matrix-013"].tags and "composed-weights" not in by_id["matrix-007"].tags
    assert not by_id["matrix-001"].composed and by_id["matrix-019"].composed  # a slider and a window make two
    for spec in by_id.values():
        assert ("iksar" in spec.tags) == (spec.race == "IKS") and ("deity" in spec.tags) == (spec.deity is not None)


def test_the_neutral_36_is_three_roles_three_tiers_two_buff_sets_and_two_pools_with_every_role_and_setup_pair():
    plan = pmb36_plan(TABLES)
    assert len(plan) == 36 and {spec.race for spec in plan} == {"OGR"} and {spec.trio for spec in plan} == {("PAL", "MNK", "BER")}
    assert {(spec.role, spec.tier, spec.buffs, spec.evidence) for spec in plan} == {
        (r, t, b, e)
        for r in ("balanced", "tank", "melee") for t in (0, 4, 10) for b in ("own", "group") for e in ("wiki", "strict-proxy")
    }
    assert len({(spec.role, spec.setup) for spec in plan}) == 8  # all eight pairs PAL/MNK/BER plays
    assert sum(spec.prune_check for spec in plan) == 6


def test_the_upgrade_plan_has_three_tier_modes_deities_locked_items_and_both_pools():
    plan = upgrade_plan(1)
    assert len(plan) == 16 and fixture_plan.brute_plan() == list(range(330))
    counts = fixture_plan.tag_counts(plan)
    assert counts["mode:ready4"] >= 4 and counts["mode:arrives"] >= 4 and counts["mode:fixed"] >= 4
    assert counts["deity-locked-owned"] >= 8 and counts["deity"] >= 4 and counts["focus:owned"] >= 4
    assert counts["evidence:strict-proxy"] >= 3 and {spec.deity for spec in plan if spec.deity} >= {"Karana", "Rallos Zek"}


def test_pick_cover_serves_every_tag_the_asked_number_of_times_in_plan_order_and_says_when_it_cannot():
    plan = matrix_plan(1, TABLES)
    wanted = ("iksar", "deity", "setup:stick")
    chosen = fixture_plan.pick_cover(plan, wanted, 2)
    assert chosen == sorted(chosen, key=plan.index) and fixture_plan.pick_cover(plan, wanted, 2) == chosen
    counts = fixture_plan.tag_counts(chosen)
    assert all(counts[tag] >= 2 for tag in wanted) and len(chosen) <= 6
    with pytest.raises(ValueError, match="too few"):
        fixture_plan.pick_cover(plan, ("deity",), 99)


def test_a_run_that_cannot_cover_its_strata_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture_plan, "_specials", lambda: [])  # no recipe with a deity is left
    scale = fixture_plan.Scale("tiny-cover", 1, (("deity",), 1), 0, 0, 1, 1, 1, 1, 1, True)
    with pytest.raises(ValueError, match="too few"):
        fixtures.generate(tmp_path / "x", 1, scale=scale, families=["matrix"], inputs=fixtures.shared_inputs())


def test_a_run_whose_cases_miss_a_required_stratum_is_refused_by_name():
    full, mini = fixture_plan.SCALES["full"], fixture_plan.SCALES["mini"]
    coverage = {
        "matrix": dict.fromkeys((*REQUIRED_STRATA, "shield-worn"), 2),
        "upgrade": dict.fromkeys(fixture_plan.UPGRADE_REQUIRED, 1),
        "evaluate": dict.fromkeys((*fixture_tables.EVALUATE_COMMON, *fixture_tables.EVALUATE_EXTREMES), 99),
    }
    families = ("matrix", "upgrade", "evaluate")
    fixtures._check_coverage(full, coverage, families)  # nothing is missing: quiet
    for family, tag in (("matrix", "iksar"), ("upgrade", "step:copy"), ("upgrade", "mode:fixed"), ("evaluate", "sta>510")):
        broken = {**coverage, family: {name: n for name, n in coverage[family].items() if name != tag}}
        with pytest.raises(fixtures.FixtureError, match=f"{family} family.*{tag}"):
            fixtures._check_coverage(full, broken, families)
    thin = {**coverage, "matrix": {**coverage["matrix"], "iksar": 1}}
    with pytest.raises(fixtures.FixtureError, match="fewer than 2"):
        fixtures._check_coverage(full, thin, families)
    fixtures._check_coverage(mini, {"upgrade": {}}, ("upgrade",))  # one session cannot show every kind of step: not asked


# ---- cases: the programs -----------------------------------------------------------------------------------------------------


def test_every_case_rebuilds_its_models_from_its_own_inputs(mini_docs):
    cases = cases_of(mini_docs)
    assert {doc["family"] for doc in cases.values()} == {"brute", "matrix", "pmb36", "upgrade"}
    checked = 0
    for case in cases.values():
        for number, solve in enumerate(case["solves"]):
            built = fixtures.build_solve(case, number)
            assert milp_json.compare(milp_json.to_dict(built), solve["model"]) == [], (case["id"], number)
            assert milp_json.validate(solve["model"]) == []
            checked += 1
    assert checked >= 18


def test_the_options_of_a_solve_are_the_ones_the_model_was_built_with(mini_docs):
    for case in cases_of(mini_docs).values():
        for solve in case["solves"]:
            options = fixture_cases.options_from_json(solve["options"])
            assert fixture_cases.options_json(options) == solve["options"]
            assert solve["model"]["info"]["haste_assumed"] == solve["result"]["haste_assumed"]
            if solve["options"]["haste_assumed"] is not None:
                assert solve["options"]["haste_assumed"] == solve["result"]["haste_assumed"]


def test_the_stored_kit_is_worth_exactly_its_breakdown_and_never_less_than_the_model_said(mini_docs):
    seen = 0
    for case in cases_of(mini_docs).values():
        items = fixtures.load_items(case)
        profile = Profile.from_dict(case["inputs"]["profile"])
        for solve in case["solves"]:
            result = solve["result"]
            got = fm.evaluate(
                profile, kit_of(items, result["kit"]), stored_totals(case, result["buffs"]), setup=case["inputs"]["setup"],
                haste_assumed=result["haste_assumed"],
            )  # fmt: skip
            assert fixture_cases.breakdown_json(got) == result["breakdown"], (case["id"], solve["label"])
            assert result["F"] == result["breakdown"]["F"] == browser.rat(got.F)
            # the model never overstates its kit (the solver's own check allows 1e-6), and the tie stage, which keeps
            # F >= F* - 1e-7 max(1, |F*|), leaves it under the exact value by that band at most
            under = (float(got.F) - result["model_F"]) / max(1.0, abs(float(got.F)))
            assert -1e-6 <= under <= TIE_TOLERANCE * (1 + 1e-6), (case["id"], solve["label"], under)
            seen += 1
    assert seen >= 18


def test_a_stored_model_solves_to_the_stored_value_and_its_canonical_kit(mini_docs):
    cases = cases_of(mini_docs)
    picks = [(case, 0) for case in cases.values() if case["family"] == "brute"]
    picks += [(case, 0) for case in cases.values() if case["family"] in ("matrix", "pmb36")][:2]
    picks += [(cases["upgrade-slots-softcap"], 1)]
    for case, number in picks:
        want = case["solves"][number]["result"]
        solution = solve_canonical(fixtures.build_solve(case, number))
        value = float(solution.breakdown.F)
        assert solution.status == "optimal" and abs(value - float(fm.fr(want["F"]))) <= 1e-9 * max(1.0, abs(value)), case["id"]
        if want["tie_stage"] == solution.tie_stage == "applied":
            assert fixture_cases.kit_json(solution.kit) == want["kit"] and list(solution.buffs) == want["buffs"], case["id"]


def test_the_pruning_a_case_records_is_reproduced_from_the_case_alone(mini_docs):
    checked = dropped = 0
    for case in cases_of(mini_docs).values():
        for solve in case["solves"]:
            record = solve["prune"]
            if record is None:
                continue
            items = fixtures.load_items(case)
            kept = prune(
                [items[name] for name in record["input"]], Profile.from_dict(case["inputs"]["profile"]), record["tier"],
                case["inputs"]["setup"], fixture_cases.buffset_from_doc(case["inputs"]["buffset"]),
                fixture_cases.options_from_json(record["options"]), owned=record["owned"],
            )  # fmt: skip
            assert fixture_cases.idents(kept) == record["kept"] == solve["pool"]
            assert len(record["kept"]) <= len(record["input"])
            dropped += len(record["input"]) - len(record["kept"])
            checked += 1
    assert checked >= 5 and dropped >= 1000  # the real pools lose most of their items


def test_a_case_that_asks_for_the_pruning_check_keeps_the_whole_pool_in_its_records(mini_docs):
    scenarios = cases_of(mini_docs, "matrix", "pmb36").values()
    flagged = [case for case in scenarios if "prune-check" in case["tags"]]
    plain = [case for case in scenarios if "prune-check" not in case["tags"]]
    assert flagged and plain
    for case in flagged:
        assert case["solves"][0]["prune"] is not None and len(case["records"]) > len(case["solves"][0]["pool"])
    for case in plain:
        assert case["solves"][0]["prune"] is None and len(case["records"]) == len(case["solves"][0]["pool"])


# ---- cases: scenarios --------------------------------------------------------------------------------------------------------


def test_a_scenario_case_says_what_the_scenario_is_and_its_profile_is_the_one_the_bundle_assembles(mini_docs, inputs):
    checked = 0
    for case in cases_of(mini_docs, "matrix", "pmb36").values():
        meta = case["inputs"]
        label = "strict" if meta["evidence"] == "strict-proxy" else "wiki"
        assert meta["profile"]["evidence"] == label and meta["profile"]["deity"] == meta["deity"]
        spells = inputs.spells(meta["level"])
        bundle = browser.bundle(tuple(meta["trio"]), meta["level"], TABLES, RULES, spells, data_release=inputs.data_release)
        assembled = browser.assemble(bundle, meta["race"], meta["role"], meta["buffs"], evidence=label, deity=meta["deity"])
        if meta["weights"] is None:
            assert meta["profile"] == assembled
        else:
            assert meta["profile"] == {**assembled, "weights": meta["weights"]["result"]}
            assert meta["weights"]["base"] == assembled["weights"]
        assert meta["setup"] in meta["profile"]["setups"] and meta["weapon_pct"] == RULES.get("tier.weapon_damage_pct")
        assert fixture_cases.buffset_doc(fixture_cases.buffset_from_doc(meta["buffset"])) == meta["buffset"]
        assert meta["buffset"]["set"] == bundle["buffs"][meta["buffs"]]["set"]
        checked += 1
    assert checked == 4  # three of the matrix and one of the neutral 36


def test_composed_weights_are_what_the_override_makes_of_the_roles_weights(mini_docs):
    composed = [case for case in cases_of(mini_docs, "matrix").values() if case["inputs"]["weights"] is not None]
    assert composed
    for case in composed:
        w = case["inputs"]["weights"]
        again = roles.weights_override(w["base"], w["multipliers"], w["custom"], w["regen_T"], mana_reachable=w["mana_reachable"])
        assert again == w["result"] and again != w["base"]
        assert bool(w["multipliers"]) + bool(w["custom"]) + (w["regen_T"] is not None) >= 2


def test_the_buff_sets_of_a_case_are_the_bundles_for_all_four_keys(inputs):
    codes = ("PAL", "MNK", "BER")
    bundle = browser.bundle(codes, 50, TABLES, RULES, inputs.spells(50), data_release=inputs.data_release)
    assert list(inputs.buffsets(codes, 50)) == list(browser.BUFF_SETS)
    for key, buffset in inputs.buffsets(codes, 50).items():
        doc = fixture_cases.buffset_doc(buffset)
        assert doc["set"] == bundle["buffs"][key]["set"]
        used = (*doc["set"]["always_on"], *doc["set"]["optional"])
        assert all(doc["table"][str(i)] == bundle["buff_table"][str(i)] for i in used)
        assert fixture_cases.buffset_doc(fixture_cases.buffset_from_doc(doc)) == doc


def test_a_strict_case_is_built_from_the_hash_proxy_and_a_deity_case_from_a_pool_with_the_locked_items(mini_docs):
    proxy = [case for case in cases_of(mini_docs, "matrix", "pmb36").values() if case["inputs"]["evidence"] == "strict-proxy"]
    deity = [case for case in cases_of(mini_docs, "matrix").values() if case["inputs"]["deity"]]
    assert proxy and deity
    for case in proxy:
        keys = [browser.record_key(record) for record in case["records"]]
        assert keys == [item["key"] for item in bench.strict_proxy([{"key": key} for key in keys])]
    for case in deity:
        pool = set(case["solves"][0]["pool"])
        locked = [r for r in case["records"] if "deity" in r and f"{browser.record_key(r)}@{case['inputs']['tier']}" in pool]
        assert locked and all(case["inputs"]["deity"] in record["deity"] for record in locked)


# ---- cases: brute force ------------------------------------------------------------------------------------------------------


def test_the_brute_force_value_is_exact_independent_and_the_solvers(mini_docs):
    cases = cases_of(mini_docs, "brute")
    assert len(cases) == 6 and all(case["synthetic"] for case in cases.values())
    for case in cases.values():
        want, got = fm.fr(case["expected"]["brute_F"]), fm.fr(case["solves"][0]["result"]["F"])
        assert abs(float(got - want)) <= 1e-9 * max(1.0, abs(float(want))), case["id"]
        # the instance is drawn again from the text that is stored, and enumerated once more
        number = int(case["id"].split("-")[1])
        inst = brute.random_instance(
            random.Random(case["inputs"]["seed"]), trio_index=number % len(brute.TRIO_MENU), haste_buffs=number % 8 == 5
        )
        space = brute.Space(inst)
        assert browser.rat(space.best()[0]) == case["expected"]["brute_F"]
        assert case["expected"]["kits"] == len(space.kits) and case["expected"]["buff_sets"] == len(space.buff_sets)
        assert fixture_cases.buffset_doc(inst.buffset) == case["inputs"]["buffset"]
        assert inst.profile.to_dict() == case["inputs"]["profile"]


@pytest.mark.parametrize("seed", range(12))
def test_the_brute_force_module_is_the_one_of_the_solver_tests(seed):
    index = seed % len(H.TRIO_MENU)
    theirs = H.random_instance(random.Random(seed), trio_index=index)
    ours = brute.random_instance(random.Random(seed), trio_index=index)
    assert ours.label == theirs.label and ours.items == theirs.items and ours.setup == theirs.setup
    assert ours.haste_assumed == theirs.haste_assumed and ours.any_rule == theirs.any_rule
    # the Profile reads back as the evaluator's own record (a profile does not keep a buff total of 0: a missing one is 0)
    theirs_profile = dataclasses.replace(theirs.profile, buff_totals=eval_buffs(theirs.profile.buff_totals))
    assert fm.compile_profile(ours.profile) == theirs_profile
    assert (ours.buffset is None) == (theirs.buffset is None)
    if ours.buffset is not None:  # the same buffs (ours say where they come from: nowhere in the game)
        pairs = ((ours.buffset.always_on, theirs.buffset.always_on), (ours.buffset.optional, theirs.buffset.optional))
        for ours_buffs, theirs_buffs in pairs:
            assert [(b.id, b.vec) for b in ours_buffs] == [(b.id, b.vec) for b in theirs_buffs]
        assert ours.buffset.conflicts == theirs.buffset.conflicts and ours.buffset.cardinality == theirs.buffset.cardinality
    assert brute.Space(ours).best()[0] == H.Space(theirs).best()[0]


def test_an_invented_item_reads_back_from_its_record_as_the_same_item(inputs):
    rng = random.Random(5)
    for number in range(30):
        for item in brute.random_instance(rng, trio_index=number % 5).items:
            record = brute.item_record(item)
            assert at_tier(browser.item_to_catalog(record, browser.ITEM_DEFAULTS), 0, RULES) == item, item.key
            assert record["key"].startswith("it") and record["id"] is None
    with pytest.raises(ValueError, match="tier 0"):
        brute.item_record(at_tier(next(iter(inputs.items_by_key.values())), 4, RULES))


# ---- cases: the Upgrade tab --------------------------------------------------------------------------------------------------


def test_an_upgrade_case_is_what_the_reference_makes_of_its_owned_set(mini_docs):
    cases = cases_of(mini_docs, "upgrade")
    assert len(cases) == 4
    for case in cases.values():
        owned, candidates = session_of(case)
        profile = Profile.from_dict(case["inputs"]["profile"])
        buffset = fixture_cases.buffset_from_doc(case["inputs"]["buffset"])
        setup = case["inputs"]["setup"]
        steps = UP.farm_path(profile, owned, candidates, setup, buffset, case["inputs"]["steps"], base_options(case))
        want = case["expected"]["steps"]
        made = [(s.index, f"{s.item.key}@{s.item.tier}", s.kind, s.source_tier) for s in steps]
        assert made == [(w["index"], w["item"], w["kind"], w["source_tier"]) for w in want]
        assert [(browser.rat(s.F), browser.rat(s.gain)) for s in steps] == [(w["F"], w["gain"]) for w in want]
        assert case["expected"]["stopped"] == ("limit" if len(steps) == case["inputs"]["steps"] else "no-gain")
        fixed = dataclasses.replace(base_options(case), haste_assumed=case["expected"]["session_haste"])
        assert browser.rat(UP.equip_now(profile, owned, setup, buffset, fixed).breakdown.F) == case["solves"][0]["result"]["F"]
        session_haste = case["expected"]["session_haste"]
        assert [step["haste_assumed"] for step in want] == [session_haste] * len(want)  # fixed for the session
        assert [step["solve"] for step in want] == list(range(1, len(want) + 1))


def best_solves(case):
    """``{k: solve}`` of the programs a case records for its best sets."""
    return {int(solve["label"].partition("-")[2]): solve for solve in case["solves"] if solve["label"].startswith("best-")}


def test_an_upgrade_case_records_the_best_two_and_three_sets_the_reference_makes_and_the_program_of_each(mini_docs):
    for case in cases_of(mini_docs, "upgrade").values():
        owned, candidates = session_of(case)
        profile = Profile.from_dict(case["inputs"]["profile"])
        buffset = fixture_cases.buffset_from_doc(case["inputs"]["buffset"])
        setup = case["inputs"]["setup"]
        entries = case["expected"]["best_sets"]
        assert [entry["k"] for entry in entries] == [2, 3], case["id"]
        equip, programs = case["solves"][0]["result"], best_solves(case)
        for entry in entries:
            best = UP.best_sets(profile, owned, candidates, entry["k"], setup, buffset, base_options(case))
            assert entry == {
                "k": entry["k"], "acquired": [f"{a.item.key}@{a.item.tier}" for a in best.acquisitions],
                "F": browser.rat(best.F), "gain": browser.rat(best.gain), "haste_assumed": best.haste_assumed,
            }, case["id"]  # fmt: skip
            assert fm.fr(entry["F"]) - fm.fr(equip["F"]) == fm.fr(entry["gain"]) >= 0
            assert entry["haste_assumed"] == case["expected"]["session_haste"]
            if entry["acquired"]:  # the kit of the best set is the result of its program
                assert fm.fr(programs[entry["k"]]["result"]["F"]) == fm.fr(entry["F"]), case["id"]
        labels = [solve["label"] for solve in case["solves"]]
        assert labels[0] == "equip-now" and labels[1 : 1 + len(case["expected"]["steps"])] == [
            f"step-{n}" for n in range(1, len(case["expected"]["steps"]) + 1)
        ]
        assert labels[1 + len(case["expected"]["steps"]) :] == [f"best-{k}" for k in sorted(programs)]
        assert set(programs) == {2, 3}, case["id"]  # every session of the fixtures offers additions


def test_the_program_of_a_best_set_is_built_and_pruned_as_the_reference_does_it(mini_docs):
    for case in cases_of(mini_docs, "upgrade").values():
        started = dict(case["inputs"]["owned"])
        for k, solve in best_solves(case).items():
            options = solve["options"]
            assert options["max_new"] == k and options["owned_caps"] == started
            assert options["new_keys"] or options["upgrades"]  # something to acquire
            assert options["haste_assumed"] == case["expected"]["session_haste"]
            assert solve["prune"] is not None and solve["prune"]["owned"] == sorted(started)
            assert solve["prune"]["kept"] == solve["pool"] and solve["prune"]["options"]["max_new"] == k
            milp_now = milp_json.to_dict(fixtures.build_solve(case, case["solves"].index(solve)))
            assert milp_json.compare(milp_now, solve["model"]) == []


def test_a_best_set_is_no_worse_than_the_first_step_nor_than_the_path_after_as_many_steps(mini_docs, sample_docs):
    compared = 0
    for case in [*cases_of(mini_docs, "upgrade").values(), *cases_of(sample_docs, "upgrade").values()]:
        steps = case["expected"]["steps"]
        two, three = case["expected"]["best_sets"]
        assert fm.fr(three["F"]) >= fm.fr(two["F"]), case["id"]
        for entry in (two, three):
            assert len(entry["acquired"]) <= entry["k"]
            if steps:  # the best set of one is the first step, so a larger set is no worse
                assert fm.fr(entry["F"]) >= fm.fr(steps[0]["F"]), (case["id"], entry["k"])
            if len(steps) >= entry["k"]:  # the k steps of the path are k additions, and a set may make any k additions
                assert fm.fr(entry["F"]) >= fm.fr(steps[entry["k"] - 1]["F"]), (case["id"], entry["k"])
                compared += 1
    assert compared >= 8


def test_a_best_set_may_upgrade_an_owned_copy_and_add_a_copy_of_the_upgrade_as_the_path_does(sample_docs):
    # upgrade-012: step 1 upgrades an owned copy to +10 and step 2 copies the upgraded item; so does the set of two additions
    case = cases_of(sample_docs, "upgrade")["upgrade-012"]
    steps = case["expected"]["steps"]
    assert [(step["kind"], step["item"]) for step in steps[:2]] == [("upgrade", "w16201@10"), ("copy", "w16201@10")]
    two, three = case["expected"]["best_sets"]
    assert two["acquired"] == ["w16201@10", "w16201@10"] and fm.fr(two["F"]) == fm.fr(steps[1]["F"])
    assert fm.fr(three["F"]) >= fm.fr(two["F"])


def test_every_step_adds_one_item_to_the_owned_set_and_the_gains_add_up(mini_docs):
    for case in cases_of(mini_docs, "upgrade").values():
        owned = dict(case["inputs"]["owned"])
        before = fm.fr(case["solves"][0]["result"]["F"])
        for step in case["expected"]["steps"]:
            if step["kind"] == "upgrade":
                source = f"{step['item'].rpartition('@')[0]}@{step['source_tier']}"
                owned[source] -= 1
                owned = {name: count for name, count in owned.items() if count}
            owned[step["item"]] = owned.get(step["item"], 0) + 1
            assert sorted(owned.items()) == [tuple(x) for x in step["owned"]]
            assert fm.fr(step["F"]) - before == fm.fr(step["gain"]) > 0
            assert fm.fr(step["F"]) == fm.fr(case["solves"][step["solve"]]["result"]["F"])
            before = fm.fr(step["F"])


def test_each_program_of_a_session_is_built_under_the_owned_counts_before_its_step(mini_docs):
    case = cases_of(mini_docs, "upgrade")["upgrade-016"]
    steps = case["expected"]["steps"]
    assert len(steps) == 3 and len(case["solves"]) == 6  # Equip now, three steps, and the programs of the best 2 and 3 sets
    owned = dict(case["inputs"]["owned"])
    started = dict(owned)
    for number, solve in enumerate(case["solves"][:4]):
        options, rows = solve["options"], set(solve["model"]["row_names"])
        assert options["owned_caps"] == owned  # the counts before the step: a step's addition joins them only afterwards
        assert options["haste_assumed"] == case["expected"]["session_haste"]  # one assumed haste for the whole session
        if number == 0:
            assert options["max_new"] is None and not options["new_keys"] and "new.limit" not in rows
        else:
            assert options["max_new"] == 1 and "new.limit" in rows  # the Best-1 program has the new-item row
            assert any(row.startswith("own.") for row in rows)
            owned = dict(steps[number - 1]["owned"])
    for solve, k in zip(case["solves"][4:], (2, 3)):  # a best set is a choice from the owned set as it started, not after a step
        assert solve["label"] == f"best-{k}"
        assert solve["options"]["owned_caps"] == started and solve["options"]["max_new"] == k
        assert solve["options"]["haste_assumed"] == case["expected"]["session_haste"]
        assert "new.limit" in solve["model"]["row_names"]


def test_every_slot_values_a_swap_with_the_rest_of_the_kit_fixed_and_offers_only_a_swap_of_one_place(mini_docs):
    cases = cases_of(mini_docs, "upgrade")
    soft = cases["upgrade-slots-softcap"]
    items = fixtures.load_items(soft)
    profile = Profile.from_dict(soft["inputs"]["profile"])
    solve = soft["solves"][0]
    kit = kit_of(items, solve["result"]["kit"])
    haste = solve["result"]["haste_assumed"]
    held = fm.evaluate(profile, kit, None, setup="stick", haste_assumed=haste)
    assert held.totals["sheet"]["X"] > held.totals["sheet"]["Y"]  # the kit is past the armor class softcap already
    swap = next(row for row in soft["expected"]["every_slot"] if row["place"] == "CHEST")["swaps"][0]
    trial = list(kit)
    trial[SLOT_INSTANCES.index("CHEST")] = items["it-chest-plus@0"]
    swapped = fm.evaluate(profile, trial, None, setup="stick", haste_assumed=haste)
    assert swap["item"] == "it-chest-plus@0" and fm.fr(swap["delta"]) == swapped.F - held.F == 15
    assert 15 < 6 * 10  # ten more armor class at a weight of 6 would be 60 by the linear estimate: past the cap it is 15
    hands = cases["upgrade-slots-twohand"]
    primary = next(row for row in hands["expected"]["every_slot"] if row["place"] == "PRIMARY")
    assert primary["current"] == "it-sword@0"
    assert primary["swaps"] == []  # a two-hander over a worn off hand is no swap of one place
    assert [step["item"] for step in hands["expected"]["steps"]] == ["it-axe@0"]  # though a farm step may take it and drop both
    rows = {row["place"]: row for row in cases["upgrade-slots-twohand-2h"]["expected"]["every_slot"]}
    assert [swap["item"] for swap in rows["PRIMARY"]["swaps"]] == ["it-axe-two@0"] and rows["SECONDARY"]["swaps"] == []


def test_every_slot_rows_are_the_references_for_every_upgrade_case(mini_docs, sample_docs):
    for case in [*cases_of(mini_docs, "upgrade").values(), *cases_of(sample_docs, "upgrade").values()]:
        owned, candidates = session_of(case)
        profile = Profile.from_dict(case["inputs"]["profile"])
        buffset = fixture_cases.buffset_from_doc(case["inputs"]["buffset"])
        options = dataclasses.replace(base_options(case), haste_assumed=case["expected"]["session_haste"])
        equip = UP.equip_now(profile, owned, case["inputs"]["setup"], buffset, options)
        rows = UP.every_slot(profile, equip, candidates, case["inputs"]["setup"], buffset, options, limit=3, owned=owned)
        got = [
            {
                "place": row.place, "index": row.index,
                "current": None if row.current is None else f"{row.current.key}@{row.current.tier}",
                "swaps": [{"item": f"{swap.item.key}@{swap.item.tier}", "delta": browser.rat(swap.delta)} for swap in row.swaps],
            }
            for row in rows
        ]  # fmt: skip
        assert got == case["expected"]["every_slot"], case["id"]
        assert [row["place"] for row in got] == list(SLOT_INSTANCES)


def test_an_every_slot_swap_to_an_owned_item_that_is_not_a_candidate_stays_within_the_counts_and_never_gains(mini_docs, sample_docs):
    """Read from the documents alone, without the reference: in Equip now's kit an owned item that the tier mode does not offer is
    a swap only while the visitor owns more copies than the kit wears in the other places, and as Equip now is the best kit of what
    is owned, such a swap is never a gain."""
    seen = 0
    for case in [*cases_of(mini_docs, "upgrade").values(), *cases_of(sample_docs, "upgrade").values()]:
        owned = {name: count for name, count in case["inputs"]["owned"]}
        candidates = set(case["inputs"]["candidates"])
        kit = [None if entry is None else f"{entry[0]}@{entry[1]}" for entry in case["solves"][case["expected"]["equip_now"]]["result"]["kit"]]
        worn = {name: kit.count(name) for name in set(kit) if name is not None}
        for row in case["expected"]["every_slot"]:
            for swap in row["swaps"]:
                name = swap["item"]
                if name in candidates:
                    continue  # a candidate may be got again: no count
                assert owned.get(name, 0) > worn.get(name, 0), (case["id"], row["place"], name)
                assert fm.fr(swap["delta"]) <= 0, (case["id"], row["place"], name)
                seen += 1
    assert seen >= 10


def test_an_owned_deity_locked_item_has_a_column_only_when_the_profiles_deity_admits_it(inputs):
    spec = fixture_plan.UpgradeSpec(
        90, ("PAL", "MNK", "BER"), "HUM", "tank", "1h-shield", "own", "wiki", "ready4", 4, None, 8, 2, "Karana", "owned", 1
    )
    plain = dataclasses.replace(spec, number=91, deity=None)
    admitted = fixture_cases.upgrade_case(inputs, fixture_cases.make_session(inputs, spec, SEED))
    refused = fixture_cases.upgrade_case(inputs, fixture_cases.make_session(inputs, plain, SEED))
    for case, deity in ((admitted, "Karana"), (refused, None)):
        records = {browser.record_key(record): record for record in case["records"]}
        locked = {name.rpartition("@")[0] for name, _ in case["inputs"]["owned"] if "deity" in records[name.rpartition("@")[0]]}
        usable = {key for key in locked if deity is not None and deity in records[key]["deity"]}
        columns = {key for _, _, key, _ in case["solves"][0]["model"]["item_cols"]}
        assert len(locked) == (3 if deity else 2)  # the deity's items and one of another deity, or two of any
        assert len(usable) == (2 if deity else 0)
        assert columns & locked == usable  # the others are owned but have no column: the profile cannot use them
        worn = {entry[0] for entry in case["solves"][0]["result"]["kit"] if entry}
        assert worn & locked <= usable


# ---- the other families ------------------------------------------------------------------------------------------------------


def evaluation_inputs(docs):
    profiles = next(iter(of_kind(docs, "evaluate-profiles").values()))
    return profiles, {browser.record_key(record): record for record in profiles["records"]}


def evaluation_of(profiles, records, evaluation):
    """The breakdown of a stored evaluation, made again from its profile, buff set, records and kit."""
    row = profiles["profiles"][evaluation["profile"]]
    pct = profiles["weapon_pct"]
    kit = [
        None if entry is None
        else at_tier(browser.item_to_catalog(records[entry[0]], browser.ITEM_DEFAULTS), entry[1], RULES, weapon_pct=pct)
        for entry in evaluation["kit"]
    ]  # fmt: skip
    buffset = fixture_cases.buffset_from_doc(row["buffset"])
    totals = None if evaluation["buffs"] is None else fixture_cases.eval_totals_for(buffset, evaluation["buffs"])
    profile = Profile.from_dict(row["profile"])
    return fm.evaluate(profile, kit, totals, setup=evaluation["setup"], haste_assumed=evaluation["haste"])


def test_every_evaluation_is_the_exact_breakdown_of_its_kit(mini_docs):
    profiles, records = evaluation_inputs(mini_docs)
    (kits,) = of_kind(mini_docs, "evaluate-kits").values()
    assert len(kits["evaluations"]) == 30
    for evaluation in kits["evaluations"]:
        assert fixture_cases.breakdown_json(evaluation_of(profiles, records, evaluation)) == evaluation["breakdown"]
        row = profiles["profiles"][evaluation["profile"]]
        buffset = fixture_cases.buffset_from_doc(row["buffset"])
        assert evaluation["buffs"] is None or buffset.is_legal(evaluation["buffs"])


def monk_bonuses_from_the_bins(docs):
    """How many of the stored Monk bonuses the Monk bins of the evaluate profiles give again, by the whole stones of the
    stored worn weight (the last bin for a weight past the table). Fails on the first one that they do not, and when a Monk
    profile has no bins for its level or the bins are not those of the bundle."""
    profiles, _ = evaluation_inputs(docs)
    monk_levels = sorted({row["level"] for row in profiles["profiles"] if row["profile"]["monk"] is not None})
    assert monk_levels, "no Monk profile among the evaluations"
    assert list(profiles["monk_bins"]) == [str(level) for level in monk_levels]
    for level, block in profiles["monk_bins"].items():
        assert block == browser.monk_bins(int(level), RULES)
    seen = 0
    for kits in of_kind(docs, "evaluate-kits").values():
        for evaluation in kits["evaluations"]:
            row = profiles["profiles"][evaluation["profile"]]
            if row["profile"]["monk"] is None:
                continue
            bins = [browser.unrat(text) for text in profiles["monk_bins"][str(row["level"])]["bonus"]]
            totals = evaluation["breakdown"]["totals"]
            stones = browser.unrat(totals["weight10"]) // 10
            assert bins[min(stones, len(bins) - 1)] == browser.unrat(totals["sheet"]["monk_bonus"]), (row["id"], stones)
            seen += 1
    return seen


def test_the_evaluations_carry_the_monk_bins_of_each_level_that_has_a_monk_and_the_bins_give_every_stored_bonus(mini_docs):
    """The port of the evaluator reads the Monk bonus from the bins (a table the float arithmetic of Python made), so a
    list of evaluations must carry the bins of every level it has a Monk profile at: not every level has a bundle among
    the fixtures (the sample has the bundle of level 50 only)."""
    assert monk_bonuses_from_the_bins(mini_docs) > 0


def test_the_aimed_evaluations_reach_the_extremes_of_the_evaluator_and_the_same_seed_gives_the_same_kits(inputs):
    assert set(fixture_tables.EVALUATE_COVERAGE) == set(fixture_tables.EVALUATE_COMMON) | set(fixture_tables.EVALUATE_EXTREMES)
    assert set(fixture_tables.EVALUATE_RARE) == {"cha>510", "regen-capped"}
    scenarios = [fixture_cases.make_scenario(inputs, spec) for spec in matrix_plan(1, TABLES)[:24]]
    docs, coverage = fixture_tables.evaluate_docs(inputs, scenarios, 300, 5)
    assert sum(coverage.get(tag, 0) >= 1 for tag in fixture_tables.EVALUATE_COMMON) >= len(fixture_tables.EVALUATE_COMMON) - 4
    assert coverage["sta>255"] >= 5 and coverage["end-average>201"] >= 5 and coverage["softcap-binds"] >= 20
    assert fixture_tables.evaluate_docs(inputs, scenarios, 300, 5)[1] == coverage


def test_every_profile_of_a_list_is_what_the_bundle_assembles(mini_docs, inputs):
    (listed,) = of_kind(mini_docs, "profiles").values()
    bundle = next(doc for path, doc in mini_docs.items() if path.endswith(".bundle.json.gz"))
    assert listed["bundle"] == "pal-mnk-ber-l50.bundle.json" and bundle["trio"] == ["PAL", "MNK", "BER"]
    offered = list(bundle["roles"])
    plain = {(e["race"], e["role"], e["buffs"]) for e in listed["profiles"] if not e["options"]}
    assert plain == {(r, role, b) for r in ("HUM", "IKS") for role in offered for b in browser.BUFF_SETS}
    options = [entry["options"] for entry in listed["profiles"]]
    assert any(o.get("evidence") == "wiki" for o in options) and any("deity" in o for o in options)
    for entry in listed["profiles"]:
        assert browser.assemble(bundle, entry["race"], entry["role"], entry["buffs"], **entry["options"]) == entry["profile"]
        buffset = inputs.buffsets(tuple(bundle["trio"]), 50)[entry["buffs"]]
        label = entry["options"].get("evidence")  # a profile at an evidence level is made given the solve pool of the level
        made = make_profile(
            entry["race"], bundle["trio"], 50, entry["role"], buffset, None, TABLES,
            evidence=label or "strict", deity=entry["options"].get("deity"),
            items=None if label is None else inputs.solve_pool(tuple(bundle["trio"]), label),
        )  # fmt: skip
        assert made.to_dict() == entry["profile"] and Profile.from_dict(entry["profile"]) == made


def test_the_profile_lists_hold_every_race_role_and_buff_key_with_no_evidence_level_and_with_each_one(inputs):
    """The port of ``assemble`` is held to this list, so it has each combination three ways: with no evidence level (the
    setups of a profile with no pool to read: a shield is assumed) and at each evidence level (the setups of the solve pool of
    that level, ``setups_by_evidence``), and every profile is what ``make_profile`` makes given that pool."""
    docs = dict(fixture_tables.profile_docs(inputs, 1, 2, level_55=False))
    bundle, listed = docs["profiles/pal-mnk-ber-l50.bundle.json"], docs["profiles/pal-mnk-ber-l50.profiles.json"]
    codes = tuple(bundle["trio"])
    assert bundle["evidence_levels"] == ["strict", "wiki"]
    assert all(set(row["setups_by_evidence"]) == {"strict", "wiki"} for row in bundle["roles"].values())
    ways = ({}, {"evidence": "strict"}, {"evidence": "wiki"})
    found: dict[tuple[str, str, str, str], dict] = {}
    for entry in listed["profiles"]:
        way = (entry["race"], entry["role"], entry["buffs"], json.dumps(entry["options"], sort_keys=True))
        assert way not in found, f"{way} is listed twice"
        found[way] = entry
    wanted = {
        (race, role, buffs, json.dumps(way)) for race in ("HUM", "IKS") for role in bundle["roles"]
        for buffs in browser.BUFF_SETS for way in ways
    }  # fmt: skip
    assert {way for way in found if "deity" not in way[3]} == wanted
    assert sum("deity" in way[3] for way in found) >= 3  # the deity is held to the list as well, with and without a level
    selection = inputs.selection(codes)
    pools = {label: [at_tier(item, 0, RULES) for item in grid.pool_dicts(selection, label)] for label in bundle["evidence_levels"]}
    for (race, role, buffs, text), entry in found.items():
        options = json.loads(text)
        assert browser.assemble(bundle, race, role, buffs, **options) == entry["profile"]
        label = options.get("evidence")
        made = make_profile(
            race, codes, 50, role, inputs.buffsets(codes, 50)[buffs], None, TABLES, evidence=label or "strict",
            deity=options.get("deity"), items=None if label is None else pools[label],
        )  # fmt: skip
        assert made.to_dict() == entry["profile"] and Profile.from_dict(entry["profile"]) == made, (race, role, buffs, text)
    # the public catalog has no strict item, so the strict pool has no shield: the setups of the strict profiles lack the
    # shield setup that the profiles with no evidence level have, and the list holds both
    fallback, strict = ("HUM", "tank", "own", "{}"), ("HUM", "tank", "own", json.dumps({"evidence": "strict"}))
    assert "1h-shield" in found[fallback]["profile"]["setups"] and "1h-shield" not in found[strict]["profile"]["setups"]
    assert found[fallback]["profile"]["evidence"] == found[strict]["profile"]["evidence"] == "strict"


def test_the_weight_compositions_are_what_the_override_makes_of_the_roles_own_weights(mini_docs):
    (doc,) = of_kind(mini_docs, "weights").values()
    assert len(doc["compositions"]) == 10
    moved = 0
    for row in doc["compositions"]:
        base = roles.weights_for(row["trio"], row["role"], RULES, mana_reachable=row["mana_reachable"])
        assert row["base"] == base
        reachable = row["mana_reachable"]
        again = roles.weights_override(base, row["multipliers"], row["custom"], row["regen_T"], mana_reachable=reachable)
        assert again == row["result"]
        moved += again != base
    assert moved >= 5


def test_the_item_vectors_are_the_item_at_every_tier_and_both_weapon_rates(mini_docs):
    table = mini_docs["items/table.json.gz"]
    records = {browser.record_key(record): record for record in table["items"]}
    vectors = [doc for _, doc in sorted(mini_docs.items()) if doc.get("kind") == "item-vectors"]
    entries = [entry for doc in vectors for entry in doc["items"]]
    assert [entry["key"] for entry in entries] == list(records) and len(entries) == table["count"] == 16
    stat_order, sv_order = vectors[0]["stat_order"], vectors[0]["sv_order"]
    assert stat_order[:12] == ["AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK"]
    assert stat_order[12:] == ["HPREG", "MANAREG", "ENDREG"] and sv_order[-1] == "CORRUPTION"
    weapons_seen = 0
    for entry in entries:
        catalog = browser.item_to_catalog(records[entry["key"]], table["defaults"])
        for tier in range(11):
            for pct in (5, 10):
                item = at_tier(catalog, tier, RULES, weapon_pct=pct)
                row = entry["tiers"][tier]
                assert row[: len(stat_order)] == [item.stats.get(name, 0) for name in stat_order]
                assert row[len(stat_order) : -2] == [item.sv.get(name, 0) for name in sv_order]
                assert row[-2:] == [item.haste, item.weight10]
                if item.weapon is not None:
                    assert entry["damage"][str(pct)][tier] == item.weapon.dmg
        item = at_tier(catalog, 0, RULES)
        assert entry["fixed"]["slots"] == sorted(item.slots) and entry["fixed"]["classes"] == sorted(item.classes)
        assert entry["fixed"]["is_shield"] == item.is_shield and (entry["damage"] is None) == (item.weapon is None)
        weapons_seen += item.weapon is not None
    assert weapons_seen >= 2


def test_the_tier_tables_are_the_modes_and_merge_costs_of_the_reference(mini_docs):
    (doc,) = of_kind(mini_docs, "tiers").values()
    assert len(doc["modes"]) == 3 * (5 + 5 + 55) and len(doc["costs"]) == 3 * 5 * 66
    for row in doc["modes"]:
        assert row["tier"] == tier_for_mode(row["rule"], row["mode"], row["D"], row["N"])
    for row in doc["costs"]:
        want = cost_to_reach(row["rule"], row["from"], row["to"], row["D"])
        assert {key: row[key] for key in want} == want
    # the figures the plan pins: one D4 copy brings +0 to +4, 63 copies +4 to +10 (1,008 experience), 64 copies +0 to +10
    by = {(r["rule"], r["D"], r["from"], r["to"]): r for r in doc["costs"]}
    assert by[("drop", 4, 0, 4)]["copies_at_arrival"] == 1 and by[("drop", 0, 0, 4)]["copies_at_arrival"] == 15
    assert by[("drop", 4, 4, 10)]["exp"] == 1008 and by[("drop", 4, 4, 10)]["copies_at_arrival"] == 63
    assert by[("drop", 4, 0, 10)]["exp"] == 1023 and by[("drop", 4, 0, 10)]["copies_at_arrival"] == 64
    assert doc["exp_needed"] == fixture_cases.exact_json(RULES.get("tier.exp_needed"))


def test_the_item_table_holds_every_wearable_including_the_hidden_ones_flagged_owned_only(inputs):
    table = fixture_tables.item_table(inputs, None)
    places = {name for name, _ in SLOT_GROUPS}
    wearable = [item for item in inputs.document["items"] if places & set(item["slots"])]
    assert table["count"] == len(table["items"]) == len(wearable) > 6000 and table == browser.items(inputs.document, RULES)
    hidden = {item["key"] for item in wearable if item["evidence"]["level"] == "hidden"}
    assert {browser.record_key(r) for r in table["items"] if r.get("owned_only")} == hidden and len(hidden) > 3000
    # the match name of a record is the title without one trailing parenthesis, whatever else the title holds
    # (a strip of every trailing group would leave "Band of" of the first)
    examples = ("Band of (Fire) (RoF)", "Chestguard", "X (Level 90 required)")
    assert [browser.match_name(title) for title in examples] == ["Band of (Fire)", "Chestguard", "X"]
    by_key = {item["key"]: item for item in wearable}
    titles = {key: item["wiki"]["title"] for key, item in by_key.items()}
    assert all(browser.effective_match_name(r) == browser.match_name(titles[browser.record_key(r)]) for r in table["items"])
    sampled = fixture_tables.item_table(inputs, 150)
    assert sampled["count"] == len(sampled["items"]) == 150 and sampled["defaults"] == table["defaults"]
    keys = [browser.record_key(r) for r in sampled["items"]]
    assert keys == sorted(keys, key=list(inputs.records).index)  # in the order of the table
    features = {f for r in sampled["items"] for f in fixture_tables._features(r)}
    assert {"weapon-1h", "weapon-2h", "shield", "lore", "owned-only", "match-name", "deity", "weight-unknown"} <= features


# ---- public only -------------------------------------------------------------------------------------------------------------


def test_the_public_catalog_has_no_strict_item_the_flags_made_and_the_generator_refuses_a_catalog_that_has_one(tmp_path, inputs):
    assert not [item for item in inputs.document["items"] if item["evidence"]["level"] == "strict"]
    committed = load_strict(REPO / "derived" / "catalog.json")["items"]  # (what the committed catalog holds as strict rests on a community report, which is public)
    assert [item["key"] for item in committed if item["evidence"]["level"] == "strict" and "community-report" not in {r["code"] for r in item["evidence"]["reasons"]}] == []
    document = {**inputs.document, "items": copy.deepcopy(inputs.document["items"][:6])}  # a few items are enough to be refused
    reason = {"code": "seen-in-game", "seal": "measured", "text": "Seen."}
    document["items"][3]["evidence"] = {"level": "strict", "reasons": [reason]}
    path = tmp_path / "strict-catalog.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(fixtures.FixtureError, match="strict"):
        fixtures.generate(tmp_path / "out", 1, scale="tiny", catalog=path)
    assert not (tmp_path / "out").exists()
    assert fixtures.main(["--out", str(tmp_path / "out2"), "--scale", "tiny", "--catalog", str(path)]) == 2
    reason = {"code": "seen-in-game:x", "seal": "measured", "text": "Seen."}
    document["items"][3]["evidence"] = {"level": "wiki", "reasons": [reason]}
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(fixtures.FixtureError, match="sighting"):
        fixtures.generate(tmp_path / "out3", 1, scale="tiny", catalog=path)
    assert fixtures.shared_inputs() is inputs  # the refusals did not cost the loaded inputs


def test_a_fixture_with_real_strict_evidence_is_rejected(mini_docs, catalog_keys):
    case = a_case(mini_docs)
    assert fixtures.public_problems(case, catalog_keys) == []
    case["records"][0]["evidence"] = {"level": "strict"}
    assert any("real strict evidence" in problem for problem in fixtures.public_problems(case, catalog_keys))
    assert fixtures.validate_document(case)  # the schema has no strict level either
    case = a_case(mini_docs)
    case["records"][0]["evidence"] = {"level": "wiki", "codes": ["seen-in-game"]}
    assert any("names a sighting" in problem for problem in fixtures.public_problems(case, catalog_keys))
    table = copy.deepcopy(mini_docs["items/table.json.gz"])
    table["items"][0]["evidence"]["level"] = "strict"
    assert any("real strict" in problem for problem in fixtures.public_problems(table, catalog_keys))


def test_a_fixture_that_names_a_key_outside_the_public_catalog_is_rejected(mini_docs, catalog_keys):
    case = a_case(mini_docs)
    case["records"][0] = {**case["records"][0], "key": "w999999999"}
    assert flagged(case, catalog_keys, "w999999999: not a key of the public catalog")
    vectors = copy.deepcopy(next(doc for doc in mini_docs.values() if doc.get("kind") == "item-vectors"))
    vectors["items"][0]["key"] = "rsomething-private"
    assert any("rsomething-private" in problem for problem in fixtures.public_problems(vectors, catalog_keys))
    evaluation = copy.deepcopy(next(iter(of_kind(mini_docs, "evaluate-kits").values())))
    slot = next(i for i, entry in enumerate(evaluation["evaluations"][0]["kit"]) if entry)
    evaluation["evaluations"][0]["kit"][slot][0] = "w123456789"
    assert any("w123456789" in problem for problem in fixtures.public_problems(evaluation, catalog_keys))


def test_an_invented_item_must_have_a_key_that_cannot_be_a_catalog_key(mini_docs, catalog_keys):
    case = a_case(mini_docs, "brute")
    assert case["synthetic"] and fixtures.public_problems(case, catalog_keys) == []
    catalog_shaped = json.loads(json.dumps(case).replace("it00", "w4242"))
    assert any("invented item" in problem for problem in fixtures.public_problems(catalog_shaped, catalog_keys))
    real = min(catalog_keys)
    borrowed = json.loads(json.dumps(case).replace("it00", real))
    assert any(real in problem and "invented item" in problem for problem in fixtures.public_problems(borrowed, catalog_keys))
    real_case = a_case(mini_docs)  # a case that is not marked synthetic cannot use an invented key
    real_case["records"][0] = {**real_case["records"][0], "key": "it00"}
    assert flagged(real_case, catalog_keys, "it00: not a key of the public catalog")


def test_strict_in_a_fixture_is_only_the_hash_proxy(mini_docs, catalog_keys):
    kept = {item["key"] for item in bench.strict_proxy([{"key": key} for key in sorted(catalog_keys)])}
    outsider = next(key for key in sorted(catalog_keys) if key not in kept)
    assert 0.3 < len(kept) / len(catalog_keys) < 0.6  # about the share the proxy keeps
    strict = a_case(mini_docs, needs=lambda doc: doc["inputs"]["evidence"] == "strict-proxy")
    assert strict["inputs"]["profile"]["evidence"] == "strict" and fixtures.public_problems(strict, catalog_keys) == []
    strict["records"][0] = {**strict["records"][0], "key": outsider}
    assert flagged(strict, catalog_keys, f"{outsider}: not picked by the strict proxy")
    wiki = a_case(mini_docs, needs=lambda doc: doc["inputs"]["evidence"] == "wiki")
    assert wiki["inputs"]["profile"]["evidence"] == "wiki" and fixtures.public_problems(wiki, catalog_keys) == []
    wiki["inputs"]["profile"]["evidence"] = "strict"  # a strict label on a pool that is not the proxy
    assert any("labelled strict" in problem for problem in fixtures.public_problems(wiki, catalog_keys))


def test_a_word_that_belongs_to_the_private_flags_is_rejected_wherever_it_is(mini_docs, catalog_keys):
    for word in ("seen-flags", "seen_keys", "seen-in-game"):
        case = a_case(mini_docs)
        case["label"] = f"about {word}"
        assert any(word in problem for problem in fixtures.public_problems(case, catalog_keys))
    for doc in mini_docs.values():
        text = json.dumps(doc).lower()
        assert not any(word in text for word in fixtures.FORBIDDEN_WORDS)


def test_a_word_is_matched_whole_and_a_community_report_is_public(mini_docs, catalog_keys):
    """The words of the private flags are matched as whole codes and names, never as a part of another: the reasons of a community report (which are public) contain none of
    them as a whole, and a name that merely starts with one is not the word."""
    assert tuple(fixtures.FORBIDDEN_WORDS) == ("seen-in-game", "seen_keys", "seen-flags") and fixture_cases.FORBIDDEN_REASONS == ("seen-in-game",)
    for harmless in ("community-report", "community-report-outweighed", "seen-in-game-notes", "unseen-flags", "preseen_keys"):
        case = a_case(mini_docs)
        case["label"] = f"about {harmless}"
        assert not any("private flags" in problem for problem in fixtures.public_problems(case, catalog_keys)), harmless
    for private in ("seen-in-game", "seen-in-game:Some Zone", "the seen_keys of", "seen-flags.json"):
        case = a_case(mini_docs)
        case["label"] = f"about {private}"
        assert any("private flags" in problem for problem in fixtures.public_problems(case, catalog_keys)), private
    table = copy.deepcopy(mini_docs["items/table.json.gz"])
    table["items"][0]["evidence"] = {"level": "hidden", "codes": ["community-report-outweighed", "wiki-marked-removed"]}
    assert fixtures.public_problems(table, catalog_keys) == []  # (a hidden item whose report the wiki outweighed is in the item table of every release)
    table["items"][0]["evidence"] = {"level": "hidden", "codes": ["seen-in-game"]}
    assert any("names a sighting" in problem for problem in fixtures.public_problems(table, catalog_keys))


# ---- the first accepted report -----------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def after_an_add(tmp_path_factory, inputs):
    return AfterAnAdd(tmp_path_factory.mktemp("after-an-add"), inputs.document)


def test_the_catalog_after_an_add_is_what_the_builder_writes_for_a_report(after_an_add):
    """The setup holds what it claims: one strict item that rests on a report alone, and two hidden ones whose reasons say that a report was received and outweighed."""
    live, marked, closed = (evidence_of(after_an_add, key) for key in after_an_add.keys)
    assert live["level"] == "strict" and [r["code"] for r in live["reasons"]] == ["community-report"]
    assert marked["level"] == "hidden" and "community-report-outweighed" in {r["code"] for r in marked["reasons"]} and "conflict-note" not in {r["code"] for r in marked["reasons"]}
    assert closed["level"] == "hidden" and "community-report-outweighed" in {r["code"] for r in closed["reasons"]}
    assert sum(1 for item in after_an_add.document["items"] if item["evidence"]["level"] == "strict") == 1


def test_the_exporter_takes_an_item_that_is_strict_by_community_reports_alone_for_a_wiki_item(after_an_add, inputs):
    """Community reports are public and the guard is about the private flags: the first accepted report must not stop the fixtures, and the fixtures must not change for it."""
    after = fixture_cases.Inputs(REPO, after_an_add.path)  # (no FixtureError: "the catalog has 1 strict items and 1 with a sighting")
    assert not [item for item in after.document["items"] if item["evidence"]["level"] == "strict"]
    live = after_an_add.live["key"]
    assert after.items_by_key[live]["evidence"]["level"] == "wiki" and "community-report" not in {r["code"] for r in after.items_by_key[live]["evidence"]["reasons"]}
    assert after.records[live] == inputs.records[live]  # (the record of the item table is the one the catalog without the report gives)
    assert after.table["count"] == inputs.table["count"]


def test_the_item_table_names_the_outweighed_report_and_is_public(after_an_add):
    after = fixture_cases.Inputs(REPO, after_an_add.path)
    for key in after_an_add.keys[1:]:
        assert "community-report-outweighed" in after.records[key]["evidence"]["codes"]
    table = fixture_tables.item_table(after, None)  # (all of it: the full set holds every wearable, and so the hidden items a report was received for)
    assert fixtures.public_problems(table, set(after.items_by_key)) == []


def test_a_strict_item_that_the_flags_made_is_still_refused_beside_one_that_a_report_made(after_an_add, tmp_path):
    document = copy.deepcopy(after_an_add.document)
    seen = next(item for item in document["items"] if item["evidence"]["level"] == "hidden" and item["key"] not in after_an_add.keys)
    seen["evidence"] = {"level": "strict", "reasons": [{"code": "seen-in-game", "seal": "measured", "text": "Seen."}]}
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(fixtures.FixtureError, match=r"1 strict items"):
        fixture_cases.Inputs(REPO, path)
    seen["evidence"] = {"level": "strict", "reasons": [{"code": "community-report", "seal": "player", "text": "x"}, {"code": "seen-in-game", "seal": "measured", "text": "x"}]}
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(fixtures.FixtureError, match=r"1 strict items"):
        fixture_cases.Inputs(REPO, path)  # (a report beside a sighting is not a report alone: the item is still strict, and is counted as such)
    seen["evidence"] = {"level": "strict", "reasons": [{"code": "community-report", "seal": "player", "text": "x"}, {"code": "eql-catalog", "seal": "player", "text": "x"}]}
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(fixtures.FixtureError, match=r"1 strict items"):
        fixture_cases.Inputs(REPO, path)  # (nor is a report beside a listing of the EQ Legends Tools catalog)


@pytest.fixture(scope="module")
def after_an_add_lifted(tmp_path_factory, inputs):
    """The catalog after a report for a disputed wearable (the report lifts it to strict) and for a live one."""
    return AfterAnAdd(tmp_path_factory.mktemp("after-an-add-lifted"), inputs.document, kinds=("disputed", "live"))


def test_an_item_a_report_made_strict_is_what_the_ladder_gives_it_without_the_report_whatever_the_level(after_an_add_lifted, inputs):
    """The strict record of an item lists the report and a conflict-note, and not the signals the report lifted it over: nothing of its dispute is left in it. So the exporter asks
    the ladder again, without the reports (the same function, the rules and the client data of the checkout), and what it answers is the evidence of the fixture, whether that
    is wiki, disputed or hidden: the item is what the catalog without the report has, and the fixtures do not change for the first report."""
    after = fixture_cases.Inputs(REPO, after_an_add_lifted.path)
    disputed, live = after_an_add_lifted.disputed, after_an_add_lifted.live
    assert evidence_of(after_an_add_lifted, disputed["key"])["level"] == "strict" and evidence_of(after_an_add_lifted, live["key"])["level"] == "strict"  # (the setup)
    assert inputs.items_by_key[disputed["key"]]["evidence"]["level"] == "disputed"
    for key in after_an_add_lifted.keys:
        assert after.items_by_key[key]["evidence"] == inputs.items_by_key[key]["evidence"], key
        assert after.records[key] == inputs.records[key], key
    assert after.items_by_key[disputed["key"]]["evidence"]["reasons"]  # (its dispute is there to be seen)


def test_the_record_of_an_item_that_is_not_strict_is_never_touched_whatever_its_reasons_say(after_an_add, tmp_path):
    document = copy.deepcopy(after_an_add.document)
    hidden = next(item for item in document["items"] if item["evidence"]["level"] == "hidden" and item["key"] not in after_an_add.keys)
    hidden["evidence"] = {"level": "hidden", "reasons": [{"code": "community-report", "seal": "player", "text": "Reported."}]}  # (no ladder gives this: the level stands)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    after = fixture_cases.Inputs(REPO, path)
    assert after.items_by_key[hidden["key"]]["evidence"] == hidden["evidence"]


def test_the_fixtures_can_still_be_made_after_the_first_accepted_report(after_an_add, tmp_path):
    after = fixture_cases.Inputs(REPO, after_an_add.path)
    manifest = fixtures.generate(tmp_path / "out", 42, scale="tiny", inputs=after)
    assert manifest["complete"] is True
    assert fixtures.validate_directory(tmp_path / "out", set(after.items_by_key)) == []
    assert fixtures.main(["--out", str(tmp_path / "again"), "--scale", "tiny", "--seed", "42", "--catalog", str(after_an_add.path)]) == 0


# ---- validation catches ------------------------------------------------------------------------------------------------------


def test_the_schema_is_a_valid_schema_with_a_definition_for_every_kind_of_file():
    schema = json.loads(fixtures.SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert set(fixtures.KIND_OF_DEF.values()) <= set(schema["$defs"])
    assert set(fixtures.KIND_OF_DEF) == {
        "manifest", "case", "evaluate-profiles", "evaluate-kits", "profiles", "weights", "item-vectors", "tiers", "bundle",
        "item-table",
    }  # fmt: skip


@pytest.mark.parametrize(
    ("change", "word"),
    [
        (lambda c: c.pop("tags"), "tags"),
        (lambda c: c.__setitem__("family", "other"), "family"),
        (lambda c: c["solves"][0]["result"]["kit"].pop(), "kit"),
        (lambda c: c["solves"][0]["result"].__setitem__("F", "2/4"), "lowest terms"),
        (lambda c: c["solves"][0]["result"].__setitem__("F", "1.5"), "F"),
        (lambda c: c["solves"][0]["result"]["breakdown"]["parts"].__setitem__("HP", 3), "parts"),
        (lambda c: c["solves"][0]["result"]["breakdown"]["totals"]["pools"].__setitem__("HP", "5/2/1"), "neither a p/q"),
        (lambda c: c["solves"][0]["model"].__setitem__("version", 2), "model"),
        (lambda c: c["solves"][0]["pool"].append(c["solves"][0]["pool"][0]), "twice"),
        (lambda c: c["solves"][0]["pool"].append("w1@4"), "no record"),
        (lambda c: c["solves"][0]["options"].__setitem__("any_rule", "some"), "any_rule"),
        (lambda c: c["records"].append(copy.deepcopy(c["records"][0])), "twice"),
        (lambda c: c["inputs"]["profile"].__setitem__("format", 2), "format"),
        (lambda c: c.__setitem__("extra", 1), "extra"),
    ],
)
def test_a_defective_case_is_reported(mini_docs, change, word):
    case = a_case(mini_docs, "brute")
    assert fixtures.validate_document(case) == []
    change(case)
    problems = fixtures.validate_document(case, name="case")
    assert problems and any(word in problem for problem in problems), problems


def drop_best_solve(case, k):
    case["solves"] = [solve for solve in case["solves"] if solve["label"] != f"best-{k}"]


def empty_the_best_set(case, k=2):
    """The best set of ``k`` as if it acquired nothing (Equip now's value, no gain), though its program found a better value."""
    entry = next(entry for entry in case["expected"]["best_sets"] if entry["k"] == k)
    entry.update(acquired=[], F=case["solves"][0]["result"]["F"], gain="0/1")


def drop_every_best_program(case):
    case["solves"] = [solve for solve in case["solves"] if not solve["label"].startswith("best-")]


@pytest.mark.parametrize(
    ("change", "word"),
    [
        (lambda c: c["expected"].pop("best_sets"), "best_sets"),
        (lambda c: c["expected"]["best_sets"].pop(), "best_sets"),
        (lambda c: c["expected"]["best_sets"][0].__setitem__("k", 4), "best_sets"),
        (lambda c: c["expected"]["best_sets"].reverse(), "best_sets"),
        (lambda c: c["expected"]["best_sets"][0].__setitem__("F", "2/4"), "lowest terms"),
        (lambda c: c["expected"]["best_sets"][0].__setitem__("gain", "1.5"), "gain"),
        (lambda c: c["expected"]["best_sets"][0].__setitem__("gain", "1/1000"), "gain"),
        (lambda c: c["expected"]["best_sets"][0].__setitem__("haste_assumed", 99), "haste"),
        (lambda c: c["expected"]["best_sets"][0]["acquired"].append("w9@4"), "no record"),
        (lambda c: c["expected"]["best_sets"][0]["acquired"].append("not an ident"), "acquired"),
        (lambda c: c["expected"]["best_sets"][0].__setitem__("extra", 1), "extra"),
        (lambda c: drop_best_solve(c, 2), "best-2"),
        (lambda c: c["solves"][-1]["result"].__setitem__("F", "1/1"), "F"),
        (lambda c: empty_the_best_set(c, 2), "above Equip now"),
        (lambda c: empty_the_best_set(c, 3), "above Equip now"),
    ],
)
def test_a_defective_best_sets_entry_is_reported(mini_docs, change, word):
    case = a_case(mini_docs, "upgrade", needs=lambda c: c["expected"]["best_sets"][0]["acquired"] and not c["synthetic"])
    assert fixtures.validate_document(case) == []
    change(case)
    problems = fixtures.validate_document(case, name="case")
    assert problems and any(word in problem for problem in problems), problems


def test_a_best_set_that_acquires_nothing_is_valid_with_no_program_and_with_a_program_that_found_nothing_better(mini_docs):
    case = a_case(mini_docs, "upgrade", needs=lambda c: not c["synthetic"])
    for k in (2, 3):
        empty_the_best_set(case, k)
    # a program that exists but found no better value than Equip now's: the set is empty because no addition improves the value
    found_nothing = copy.deepcopy(case)
    for solve in found_nothing["solves"]:
        if solve["label"].startswith("best-"):
            solve["result"] = copy.deepcopy(found_nothing["solves"][0]["result"])
    assert fixtures.validate_document(found_nothing) == []
    # and when the candidates offer nothing to acquire, best_sets builds only Equip now: the sets are empty and no program is recorded
    drop_every_best_program(case)
    assert [solve["label"] for solve in case["solves"]][-1].startswith("step-") or case["solves"][-1]["label"] == "equip-now"
    assert fixtures.validate_document(case) == []


def test_the_events_of_a_best_set_are_the_build_of_equip_now_and_the_pruning_and_build_of_the_set():
    equip_prune, equip_build = ("prune", {"id": "equip"}, "kept-equip"), ("build", {"id": "equip"}, "equip-milp")
    set_prune, set_build = ("prune", {"id": "set"}, "kept-set"), ("build", {"id": "set"}, "set-milp")
    pick = fixture_cases._best_set_events
    assert pick([equip_build, set_prune, set_build]) == (equip_build, set_prune, set_build)  # the order of today
    # an Equip now that pruned too: its pruning comes before its own build, and the first pruning of the run is not the set's
    assert pick([equip_prune, equip_build, set_prune, set_build]) == (equip_build, set_prune, set_build)
    # a pruning after the build of the set is not its pruning, and one that came before Equip now's build is not either
    assert pick([equip_build, set_prune, set_build, equip_prune]) == (equip_build, set_prune, set_build)
    assert pick([equip_prune, equip_build, set_build]) == (equip_build, None, set_build)
    # nothing to acquire: only Equip now was built
    assert pick([equip_build]) == (equip_build, None, None)
    for events in ([], [equip_build, set_build, equip_build], [set_prune]):
        with pytest.raises(fixture_cases.FixtureError):
            pick(events)


def test_a_folder_with_a_changed_missing_unlisted_or_unreadable_file_is_reported(tiny, catalog_keys, tmp_path):
    copy_dir = tmp_path / "copy"
    shutil.copytree(tiny[0], copy_dir)
    assert fixtures.validate_directory(copy_dir, catalog_keys) == []
    changed = copy_dir / "brute" / "brute-000.json.gz"
    text = bytearray(gzip.decompress(changed.read_bytes()))
    text[text.index(b'"label"') + 12] ^= 1
    changed.write_bytes(gzip.compress(bytes(text), mtime=0))
    (copy_dir / "brute" / "brute-001.json.gz").unlink()
    (copy_dir / "upgrade" / "upgrade-slots-softcap.json.gz").write_bytes(b"not a gzip file")
    (copy_dir / "stray.json").write_text("{}", encoding="ascii")
    problems = fixtures.validate_directory(copy_dir, catalog_keys)
    assert any("brute-000" in p and "SHA-256" in p for p in problems)
    assert any("brute-001" in p and "missing" in p for p in problems)
    assert any("upgrade-slots-softcap" in p and "gzip" in p for p in problems)
    assert any("stray.json" in p and "not listed" in p for p in problems)


def test_a_release_check_names_what_differs(mini):
    _, manifest = mini
    assert fixtures.check_release(manifest, manifest["data_release"], manifest["rules_version"]) == []
    problems = fixtures.check_release(manifest, "data-2999-01-01", "2999-01-01")
    assert len(problems) == 2 and "data release" in problems[0] and "rules version" in problems[1]
    assert fixtures.check_release(manifest, None, manifest["rules_version"])


# ---- the command -------------------------------------------------------------------------------------------------------------


def test_the_command_reports_what_it_wrote_validates_a_folder_and_refuses_bad_asks(tmp_path, capsys):
    out = tmp_path / "run"
    assert fixtures.main(["--out", str(out), "--scale", "tiny", "--seed", "9", "--families", "brute,tiers-not-a-family"]) == 2
    assert "unknown families" in capsys.readouterr().err and not out.exists()
    assert fixtures.main(["--out", str(out), "--scale", "tiny", "--seed", "9", "--families", "brute,items"]) == 0
    report = capsys.readouterr().out
    assert "brute" in report and "items" in report and "seed 9" in report and "data-" in report
    manifest = fixtures.read_document(out / "manifest.json")
    assert list(manifest["families"]) == ["brute", "items"] and manifest["scale"] == "tiny"
    assert fixtures.main(["--out", str(out), "--validate"]) == 0 and "valid" in capsys.readouterr().out
    # an earlier run of the command may be written over: its families are replaced, the stale files go
    (out / "brute" / "old.json").write_text("{}", encoding="ascii")
    assert fixtures.main(["--out", str(out), "--scale", "tiny", "--families", "brute"]) == 0
    assert not (out / "brute" / "old.json").exists() and not (out / "items").exists()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("keep", encoding="ascii")
    assert fixtures.main(["--out", str(foreign), "--scale", "tiny"]) == 2
    assert "not parity fixtures" in capsys.readouterr().err and (foreign / "notes.txt").read_text() == "keep"
    assert fixtures.main(["--out", str(tmp_path / "x"), "--sample", "--scale", "mini"]) == 2
    (out / "brute" / "brute-000.json.gz").write_bytes(b"not a gzip file")
    assert fixtures.main(["--out", str(out), "--validate"]) == 1


# ---- the committed sample ----------------------------------------------------------------------------------------------------


def test_the_sample_carries_the_release_it_was_made_for(sample_manifest, sample_docs, inputs):
    """Fails when the catalog or the rules change: regenerate the sample with ``python -m trioforge.export.fixtures --out
    fixtures/parity --sample``."""
    problems = fixtures.check_release(sample_manifest, inputs.data_release, inputs.rules_version)
    assert not problems, f"{problems}; regenerate the sample: {REGENERATE}"
    for path, doc in sample_docs.items():
        assert (doc["data_release"], doc["rules_version"]) == (inputs.data_release, inputs.rules_version), path


def test_the_sample_is_within_its_size_budget_and_is_plain_text(sample_manifest):
    assert sample_manifest["scale"] == "sample" and sample_manifest["complete"] is True
    assert sample_manifest["seed"] == fixtures.DEFAULT_SEED
    assert fixtures.gzip_size(SAMPLE) <= fixtures.SAMPLE_BUDGET == 2_000_000
    # no archive in it: the privacy scan refuses them
    assert not [p for p in SAMPLE.rglob("*") if p.is_file() and p.suffix not in (".json", ".md")]


def test_the_sample_validates_is_public_and_lists_exactly_its_files(sample_manifest, catalog_keys):
    assert fixtures.validate_directory(SAMPLE, catalog_keys) == []


def test_the_sample_has_every_family_and_covers_every_stratum_at_least_twice(sample_manifest, sample_docs):
    assert list(sample_manifest["families"]) == list(fixtures.FAMILIES)
    counts = sample_manifest["coverage"]["matrix"]
    for stratum in (*REQUIRED_STRATA, "shield-worn", "evidence:strict-proxy", "level:55", "prune-check"):
        assert counts.get(stratum, 0) >= 2, stratum
    assert counts == fixture_plan.count_tags(doc["tags"] for doc in cases_of(sample_docs, "matrix").values())
    families = sample_manifest["families"]
    assert families["brute"]["count"] == 40 and families["pmb36"]["count"] == 6 and families["evaluate"]["count"] == 150
    upgrades = cases_of(sample_docs, "upgrade")
    assert len(upgrades) == 6
    modes = {c["inputs"]["tier_mode"]["mode"] for c in upgrades.values() if c["inputs"]["tier_mode"]}
    assert modes == {"ready4", "arrives", "fixed"}
    kinds = {step["kind"] for case in upgrades.values() for step in case["expected"]["steps"]}
    assert kinds == {"new", "copy", "upgrade"}  # a new item, another copy of an owned one, and a tier upgrade of an owned one
    shown = sample_manifest["coverage"]["upgrade"]
    assert shown == fixture_plan.count_tags(case["tags"] for case in upgrades.values())
    assert all(shown.get(tag, 0) >= 1 for tag in fixture_plan.UPGRADE_REQUIRED)


def test_the_sample_models_are_what_the_builder_makes_now(sample_docs):
    built = 0
    for case in cases_of(sample_docs).values():
        for number, solve in enumerate(case["solves"]):
            built_now = milp_json.to_dict(fixtures.build_solve(case, number))
            assert milp_json.compare(built_now, solve["model"]) == [], (case["id"], number)
            built += 1
    assert built >= 60


def test_the_sample_results_are_the_exact_values_of_the_kits_and_the_brute_force_agrees(sample_docs):
    for case in cases_of(sample_docs).values():
        items = fixtures.load_items(case)
        profile = Profile.from_dict(case["inputs"]["profile"])
        for solve in case["solves"]:
            result = solve["result"]
            got = fm.evaluate(
                profile, kit_of(items, result["kit"]), stored_totals(case, result["buffs"]), setup=case["inputs"]["setup"],
                haste_assumed=result["haste_assumed"],
            )  # fmt: skip
            assert fixture_cases.breakdown_json(got) == result["breakdown"], case["id"]
        if case["family"] == "brute":
            want, got = fm.fr(case["expected"]["brute_F"]), fm.fr(case["solves"][0]["result"]["F"])
            assert abs(float(want - got)) <= 1e-9 * max(1.0, abs(float(want))), case["id"]


def test_the_sample_evaluations_and_vectors_are_what_the_functions_give_now(sample_docs):
    profiles, records = evaluation_inputs(sample_docs)
    seen = 0
    for doc in of_kind(sample_docs, "evaluate-kits").values():
        for evaluation in doc["evaluations"]:
            assert fixture_cases.breakdown_json(evaluation_of(profiles, records, evaluation)) == evaluation["breakdown"]
            seen += 1
    assert seen == 150
    table = sample_docs["items/table.json"]
    assert table["count"] == 150
    by_key = {browser.record_key(record): record for record in table["items"]}
    for doc in of_kind(sample_docs, "item-vectors").values():
        for entry in doc["items"]:
            item = at_tier(browser.item_to_catalog(by_key[entry["key"]], table["defaults"]), 7, RULES, weapon_pct=10)
            assert entry["tiers"][7][-2:] == [item.haste, item.weight10]


def test_the_sample_evaluations_carry_the_monk_bins_of_both_of_their_levels(sample_docs):
    profiles, _ = evaluation_inputs(sample_docs)
    assert list(profiles["monk_bins"]) == ["50", "55"]  # a Monk profile at level 55 has no bundle in the sample
    assert monk_bonuses_from_the_bins(sample_docs) >= 40


def test_the_sample_invented_sessions_are_what_the_reference_makes(sample_docs):
    for case in cases_of(sample_docs, "upgrade").values():
        if not case["synthetic"]:
            continue
        owned, candidates = session_of(case)
        profile = Profile.from_dict(case["inputs"]["profile"])
        setup, count = case["inputs"]["setup"], case["inputs"]["steps"]
        steps = UP.farm_path(profile, owned, candidates, setup, None, count, base_options(case))
        assert [(f"{s.item.key}@{s.item.tier}", browser.rat(s.gain)) for s in steps] == [
            (w["item"], w["gain"]) for w in case["expected"]["steps"]
        ], case["id"]
        sets = [UP.best_sets(profile, owned, candidates, entry["k"], setup, None, base_options(case)) for entry in case["expected"]["best_sets"]]
        assert [(b.k, [f"{a.item.key}@{a.item.tier}" for a in b.acquisitions], browser.rat(b.F)) for b in sets] == [
            (e["k"], e["acquired"], e["F"]) for e in case["expected"]["best_sets"]
        ], case["id"]


def test_every_upgrade_case_of_the_sample_has_its_best_two_and_three_sets_and_their_programs(sample_docs):
    for case in cases_of(sample_docs, "upgrade").values():
        assert [entry["k"] for entry in case["expected"]["best_sets"]] == [2, 3], case["id"]
        assert set(best_solves(case)) == {2, 3}, case["id"]


def test_the_sample_brute_force_cases_are_the_ones_the_command_makes_now(sample_manifest, sample_docs, inputs):
    """A change of the builder, the evaluator or the brute force that is not followed by a new sample is reported: these
    cases depend on nothing but the code, so they are made again and compared. What the solver chose among equally good kits
    (the kit, the chosen buffs, the tie stage) and the float it reports are left out: they may differ between machines."""
    for number in (0, 7, 21, 39):
        again = fixture_cases.brute_case(inputs, sample_manifest["seed"], number)
        stored = sample_docs[f"brute/brute-{number:03d}.json"]
        for part in ("inputs", "records", "expected", "tags", "label"):
            assert again[part] == stored[part], (number, part)
        (new,), (old,) = again["solves"], stored["solves"]
        for part in ("options", "pool", "prune", "model"):
            assert new[part] == old[part], (number, part)
        assert new["result"]["F"] == old["result"]["F"] == again["expected"]["brute_F"]
