"""Tests for the pieces of the PC release build that need no solver: the checks that read a release, the keyed privacy gate, the outputs and the stamps.

Each check refuses the release with a message that says what and where; each test here injects the fault that check is for, into a copy of the
hand-written site fixture (invented names and numbers) or into a made-up input, and holds the check to its refusal and to the clean case. The checks
that run Node (the browser's own reader of the bundles, the parity suite, the bundling of the page code) skip without Node and ``npm ci``, as the
other tests of the site do.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from release_helpers import SLUG, edit, load, save
from test_privacy_helpers import commit, gitenv, make_repo, privacy_files, tell_line, write, write_key_file  # noqa: F401 (gitenv is a fixture)
from test_privacy_helpers import git as run_git
from test_release_assemble import make_junction
from test_site_build import need_node

from trioforge.precompute import assemble, release
from trioforge.precompute.assemble import ReleaseRefused
from trioforge.site import build

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "fixtures" / "site" / "results"
SOLVED = REPO / "fixtures" / "site" / "results-solved"
NOW = datetime.datetime(2026, 10, 17, 12, 0, 0, tzinfo=datetime.timezone.utc)


def results_copy(tmp_path: Path, name: str = "results") -> Path:
    target = tmp_path / name
    shutil.copytree(RESULTS, target)
    return target


# ---- the stamps of the scheduled checks ---------------------------------------------------------------------------------------------


def stamp(folder: Path, name: str, when: datetime.datetime | str | None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if when is not None:
        text = when if isinstance(when, str) else when.isoformat().replace("+00:00", "Z")
        (folder / f"{name}.last-run").write_text(text + "\n", encoding="utf-8")


def test_a_check_that_ran_lately_gives_no_warning(tmp_path):
    for name in release.SCHEDULED_CHECKS:
        stamp(tmp_path, name, NOW - datetime.timedelta(days=3))
    assert release.scheduled_warnings(tmp_path, NOW) == []


def test_exactly_ten_days_is_not_yet_stale_and_a_little_more_is(tmp_path):
    for name in release.SCHEDULED_CHECKS:
        stamp(tmp_path, name, NOW - datetime.timedelta(days=10))
    assert release.scheduled_warnings(tmp_path, NOW) == []
    for name in release.SCHEDULED_CHECKS:
        stamp(tmp_path, name, NOW - datetime.timedelta(days=10, seconds=1))
    warnings = release.scheduled_warnings(tmp_path, NOW)
    assert len(warnings) == len(release.SCHEDULED_CHECKS) and all("10 days" in w for w in warnings)


def test_a_stale_check_names_itself_and_says_how_long_ago(tmp_path):
    names = list(release.SCHEDULED_CHECKS)
    stamp(tmp_path, names[0], NOW - datetime.timedelta(days=23))
    for name in names[1:]:
        stamp(tmp_path, name, NOW)
    (warning,) = release.scheduled_warnings(tmp_path, NOW)
    assert names[0] in warning and "23 days" in warning


def test_a_missing_stamp_is_a_warning_and_no_refusal(tmp_path):
    warnings = release.scheduled_warnings(tmp_path / "no-such-folder", NOW)
    assert len(warnings) == len(release.SCHEDULED_CHECKS) and all("never" in w or "no stamp" in w for w in warnings)


@pytest.mark.parametrize("text", ["", "yesterday", "2026-13-45T00:00:00Z", "\x00\x01", "2026-10-17T99:00:00Z"])
def test_a_stamp_that_cannot_be_read_counts_as_missing(tmp_path, text):
    for name in release.SCHEDULED_CHECKS:
        stamp(tmp_path, name, text)
    assert len(release.scheduled_warnings(tmp_path, NOW)) == len(release.SCHEDULED_CHECKS)


def test_a_stamp_in_the_future_is_no_reason_to_warn_and_a_stamp_without_a_zone_is_taken_as_utc(tmp_path):
    for name in release.SCHEDULED_CHECKS:
        stamp(tmp_path, name, "2026-10-18T00:00:00")
    assert release.scheduled_warnings(tmp_path, NOW) == []
    for name in release.SCHEDULED_CHECKS:
        stamp(tmp_path, name, "2026-09-01T00:00:00")
    assert len(release.scheduled_warnings(tmp_path, NOW)) == len(release.SCHEDULED_CHECKS)


# ---- the previous release ------------------------------------------------------------------------------------------------------------


def pointer_for(root: Path, tag: str, asset: Path | None, *, sha: str | None = None) -> Path:
    """A pointer in ``root/releases`` for an asset (its real digest, unless told otherwise)."""
    document = assemble.release_document(
        tag=tag, catalog_date="2026-10-14", catalog_sha256="ab" * 32, rules_version="2026-10-13", rules={}, code_hash="cd" * 32, solver={}, build_options={},
        level=50, game_patch="2026-09-22", trios={SLUG: [0, 4, 10]}, evidence={}, snapshot_id="ef" * 16, parity_sample="0/36",
    )
    digest = sha or (assemble._sha256_of(asset) if asset else "00" * 32)
    return assemble.write_pointer(root / "releases" / f"{tag}.json", assemble.pointer_document(document, digest))


def asset_for(build_dir: Path, tag: str, content: bytes = b"an asset") -> Path:
    path = build_dir / "release" / f"{tag}.tar.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_the_previous_release_is_the_newest_older_one_that_has_a_pointer_and_an_asset(tmp_path):
    root, build_dir = tmp_path, tmp_path / "build"
    for tag in ("data-2026-10-03", "data-2026-10-10", "data-2026-10-10-2", "data-2026-10-17", "data-2026-10-20"):
        pointer_for(root, tag, asset_for(build_dir, tag, tag.encode()))
    found, note = release.resolve_previous(root, build_dir, "data-2026-10-17", "auto")
    assert found == build_dir / "release" / "data-2026-10-10-2.tar.gz" and note is None  # (not itself, not a later one, the second of a day after the first)


def test_a_serial_orders_the_releases_of_one_day(tmp_path):
    root, build_dir = tmp_path, tmp_path / "build"
    for tag in ("data-2026-10-10", "data-2026-10-10-1", "data-2026-10-10-9", "data-2026-10-10-10"):
        pointer_for(root, tag, asset_for(build_dir, tag, tag.encode()))
    found, _ = release.resolve_previous(root, build_dir, "data-2026-10-17", "auto")
    assert found.name == "data-2026-10-10-10.tar.gz"  # ten after nine: a number, not text


def test_with_no_earlier_release_there_is_nothing_to_compare_and_nothing_to_say(tmp_path):
    assert release.resolve_previous(tmp_path, tmp_path / "build", "data-2026-10-17", "auto") == (None, None)
    pointer_for(tmp_path, "data-2026-10-20", None)
    assert release.resolve_previous(tmp_path, tmp_path / "build", "data-2026-10-17", "auto") == (None, None)


def test_an_earlier_release_whose_asset_is_not_here_is_said_and_not_guessed_at(tmp_path):
    pointer_for(tmp_path, "data-2026-10-10", None)
    found, note = release.resolve_previous(tmp_path, tmp_path / "build", "data-2026-10-17", "auto")
    assert found is None and "data-2026-10-10" in note and "asset" in note
    assert str(tmp_path) not in note and not re.search(r"[A-Za-z]:[\\/]", note)  # the note is published: it names the tag, and never a place on this computer


def test_an_asset_that_is_not_the_one_its_pointer_names_is_refused(tmp_path):
    asset = asset_for(tmp_path / "build", "data-2026-10-10")
    pointer_for(tmp_path, "data-2026-10-10", asset, sha="11" * 32)
    with pytest.raises(ReleaseRefused, match="data-2026-10-10.*differs|differs.*data-2026-10-10"):
        release.resolve_previous(tmp_path, tmp_path / "build", "data-2026-10-17", "auto")


def test_a_pointer_that_is_not_a_pointer_is_refused(tmp_path):
    (tmp_path / "releases").mkdir()
    (tmp_path / "releases" / "data-2026-10-10.json").write_text('{"release": "data-2026-10-10"}', encoding="utf-8")
    with pytest.raises(ReleaseRefused, match="pointer"):
        release.resolve_previous(tmp_path, tmp_path / "build", "data-2026-10-17", "auto")


def test_a_file_in_releases_that_is_no_tag_is_left_alone(tmp_path):
    (tmp_path / "releases").mkdir()
    (tmp_path / "releases" / "notes.json").write_text("{}", encoding="utf-8")
    assert release.resolve_previous(tmp_path, tmp_path / "build", "data-2026-10-17", "auto") == (None, None)


def test_the_previous_release_can_be_named_or_switched_off(tmp_path):
    asset = asset_for(tmp_path, "elsewhere", b"x")
    assert release.resolve_previous(tmp_path, tmp_path / "build", "data-2026-10-17", str(asset)) == (asset, None)
    assert release.resolve_previous(tmp_path, tmp_path / "build", "data-2026-10-17", "none") == (None, None)
    with pytest.raises(ReleaseRefused, match="previous"):
        release.resolve_previous(tmp_path, tmp_path / "build", "data-2026-10-17", str(tmp_path / "missing.tar.gz"))


# ---- the outputs --------------------------------------------------------------------------------------------------------------------------


def test_the_outputs_are_written_together_and_the_pointer_last(tmp_path, monkeypatch):
    texts = {"reports/a.md": "a\n", "reports/a.json": "{}\n", "releases/data-2026-10-17.json": "{}\n"}
    order = []
    real = os.replace

    def spy(source, target):
        order.append(Path(target).name)
        return real(source, target)

    monkeypatch.setattr(os, "replace", spy)
    release.write_outputs(tmp_path, texts, last="releases/data-2026-10-17.json")
    assert {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()} == set(texts)
    assert order[-1] == "data-2026-10-17.json"


def test_a_failure_while_writing_leaves_none_of_the_outputs(tmp_path, monkeypatch):
    texts = {"reports/a.md": "a\n", "reports/a.json": "{}\n", "releases/data-2026-10-17.json": "{}\n"}
    real = os.replace

    def fail_on_the_pointer(source, target):
        if Path(target).name == "data-2026-10-17.json":
            raise OSError("the disk is full")
        return real(source, target)

    monkeypatch.setattr(os, "replace", fail_on_the_pointer)
    with pytest.raises(OSError, match="full"):
        release.write_outputs(tmp_path, texts, last="releases/data-2026-10-17.json")
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []  # not the reports either, and no temporary file


def test_an_output_that_exists_is_never_overwritten(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "a.md").write_text("old\n", encoding="utf-8")
    with pytest.raises(ReleaseRefused, match=r"a\.md"):
        release.write_outputs(tmp_path, {"reports/a.md": "new\n", "releases/p.json": "{}\n"}, last="releases/p.json")
    assert (tmp_path / "reports" / "a.md").read_text(encoding="utf-8") == "old\n" and not (tmp_path / "releases").exists()


# ---- the keyed privacy gate -----------------------------------------------------------------------------------------------------------------


@pytest.fixture
def privacy(tmp_path):
    """A repository's ``privacy/`` folder for a synthetic key, the key file, and a release folder to scan."""
    root = tmp_path / "root"
    privacy_files(root)
    key = write_key_file(tmp_path / "keys")
    folder = tmp_path / "build" / "release" / "stage"  # (a path with a build folder in it: the scan labels files by the release's own names)
    shutil.copytree(RESULTS, folder)
    return SimpleNamespace(root=root, key=key, folder=folder)


def scanner(privacy, **kwargs):
    return release.PrivacyScanner(privacy.key, privacy.root / "privacy", **kwargs)


def test_a_clean_release_passes_the_keyed_scan(privacy):
    report = scanner(privacy).scan(privacy.folder)
    assert report.findings == [] and report.files == len(list(privacy.folder.rglob("*.json")))
    assert release.privacy_gate(scanner(privacy), privacy.folder) == report.files


def test_a_name_on_the_denylist_in_a_file_of_the_release_refuses_it(privacy):
    target = privacy.folder / SLUG / "wiki-own.json"
    target.unlink()  # (a staged file may be a link to the results)
    target.write_text('{"note": "Zorblax was here"}\n', encoding="utf-8")
    with pytest.raises(ReleaseRefused, match=r"privacy scan.*1 finding") as raised:
        release.privacy_gate(scanner(privacy), privacy.folder)
    message = str(raised.value)
    assert "pal-mnk-ber/wiki-own.json:1:" in message and "denylist" in message
    assert "zorblax" not in message.lower()  # the scan never prints what it found


def test_a_name_in_the_text_of_the_pointer_or_the_report_refuses_the_release_too(privacy):
    clean = {"releases/data-2026-10-17.json": b'{"release": "data-2026-10-17"}\n', "reports/results-diff-data-2026-10-17.md": b"# Results diff\n"}
    assert scanner(privacy).scan(privacy.folder, clean).findings == []
    planted = {**clean, "reports/results-diff-data-2026-10-17.md": b"# Results diff\n\nthe Quimmet cap\n"}
    (finding,) = scanner(privacy).scan(privacy.folder, planted).findings
    assert finding.path == "reports/results-diff-data-2026-10-17.md" and finding.rule == "denylist"


def test_the_log_shape_rules_run_on_a_release_as_they_do_on_the_repository(privacy):
    target = privacy.folder / SLUG / "defaults.json"
    target.unlink()
    target.write_text(json.dumps({"x": tell_line()}) + "\n", encoding="utf-8")  # (a line of a game log, built from pieces)
    findings = scanner(privacy).scan(privacy.folder).findings
    assert findings and {f.path for f in findings} == {"pal-mnk-ber/defaults.json"}


def test_the_scan_labels_a_file_by_its_place_in_the_release_so_a_build_folder_above_it_is_no_finding(privacy):
    assert "build" in privacy.folder.parts
    assert scanner(privacy).scan(privacy.folder).findings == []


def test_a_release_with_a_file_the_scan_cannot_read_is_refused_and_not_passed(privacy, monkeypatch):
    real_open = open

    def fail_on_the_defaults(path, *args, **kwargs):
        if str(path).endswith("defaults.json"):
            raise OSError("denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(release, "open", fail_on_the_defaults, raising=False)
    with pytest.raises(ReleaseRefused, match="privacy scan.*cannot read"):
        release.privacy_gate(scanner(privacy), privacy.folder)


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (lambda p: p.key.unlink(), "key"),
        (lambda p: p.key.write_text("not a key\n", encoding="utf-8"), "key"),
        (lambda p: p.key.write_text("11" * 32 + "\n", encoding="utf-8"), "does not match"),
        (lambda p: (p.root / "privacy" / "denylist.hmac").unlink(), "denylist"),
        (lambda p: (p.root / "privacy" / "denylist.hmac").write_text("# empty\n", encoding="utf-8"), "denylist"),
        (lambda p: (p.root / "privacy" / "denylist.hmac").write_text("# key-check: 0000000000000000\nnot a digest\n", encoding="utf-8"), "denylist"),
    ],
    ids=["no key file", "key that is not hex", "key that does not fit the denylist", "no denylist", "empty denylist", "damaged denylist"],
)
def test_the_gate_cannot_be_set_up_without_the_key_and_the_denylist_and_never_runs_without_them(privacy, break_it, message):
    break_it(privacy)
    with pytest.raises(ReleaseRefused, match=message):
        scanner(privacy)


def test_the_key_comes_from_the_file_given_and_never_from_the_environment(privacy, monkeypatch):
    monkeypatch.setenv("TRIOFORGE_PRIVACY_KEY", "22" * 32)
    privacy.key.unlink()
    with pytest.raises(ReleaseRefused, match="key"):
        scanner(privacy)


def test_the_names_of_the_public_catalog_are_known_to_the_scan_as_they_are_in_the_repository(privacy, tmp_path):
    """An item name of the public catalog that holds a word of the denylist is no finding where it stands whole, and the bare word still is one."""
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"items": [{"name": "Quimmet Ring"}]}), encoding="utf-8")
    target = privacy.folder / SLUG / "defaults.json"
    target.unlink()
    target.write_text('{"note": "Quimmet Ring"}\n', encoding="utf-8")
    assert scanner(privacy).scan(privacy.folder).findings != []
    assert scanner(privacy, phrases_catalog=catalog).scan(privacy.folder).findings == []
    target.unlink()
    target.write_text('{"note": "Quimmet"}\n', encoding="utf-8")
    assert scanner(privacy, phrases_catalog=catalog).scan(privacy.folder).findings != []


# ---- the file budget -------------------------------------------------------------------------------------------------------------------------


ASSETS = tuple(f"assets/part-{n:08X}.js" for n in range(14))


def facts_of_the_grid():
    from itertools import combinations

    from trioforge.classes import CLASS_CODES
    from trioforge.model.roles import roles_for
    from trioforge.scope import default_tiers

    found = []
    for codes in combinations(CLASS_CODES, 3):
        found.append(
            release.TrioFacts("-".join(c.lower() for c in codes), default_tiers(codes), tuple(roles_for(codes)), (50,), "data-2026-10-14", "2026-10-13", "2026-09-22", 50)
        )
    return found


def evidence_of(count: int, level: str = "wiki") -> dict[str, str]:
    return {f"w{90000 + n}": level for n in range(count)}


def test_the_full_grid_with_2500_item_pages_is_counted_exactly_and_is_within_the_budget():
    facts = facts_of_the_grid()
    count = release.check_file_count(facts, evidence_of(2500), assets=ASSETS)
    names = build.site_files(
        [build.TrioFiles(f.slug, f.roles, f.tiers, f.levels) for f in facts], assets=ASSETS, item_pages=sorted(evidence_of(2500)), noindex=False
    )
    assert count == len(names) <= 15_000 and 8_000 < count


def test_only_the_strict_and_wiki_items_get_a_page(tmp_path):
    facts = facts_of_the_grid()
    evidence = {**evidence_of(100, "strict"), **{f"w{95000 + n}": "wiki" for n in range(50)}, **{f"w{96000 + n}": "hidden" for n in range(30)}, **{f"w{97000 + n}": "disputed" for n in range(20)}}
    base = release.check_file_count(facts, {}, assets=ASSETS)
    assert release.check_file_count(facts, evidence, assets=ASSETS) == base + 150


def test_a_release_whose_pages_would_pass_15000_files_is_refused_with_its_count():
    facts = facts_of_the_grid()
    with pytest.raises(ReleaseRefused, match=r"over budget.*files \(limit 15,000\)"):
        release.check_file_count(facts, evidence_of(9000), assets=ASSETS)


def test_an_item_key_no_page_can_have_is_refused():
    with pytest.raises(ReleaseRefused, match="item key"):
        release.check_file_count(facts_of_the_grid()[:3], {"W 1": "wiki"}, assets=ASSETS)


def test_the_real_page_code_is_bundled_for_the_count_when_no_assets_are_given():
    need_node()
    facts = facts_of_the_grid()[:2]
    count = release.check_file_count(facts, {}, assets=None)
    assert count == len(build.site_files([build.TrioFiles(f.slug, f.roles, f.tiers, f.levels) for f in facts], assets=build.page_code_files(), noindex=False))


# ---- the browser's own reader of the bundles --------------------------------------------------------------------------------------------------


def test_every_bundle_is_read_by_the_browsers_own_reader(tmp_path):
    need_node()
    folder = results_copy(tmp_path)
    counts = release.check_bundle_reader(folder, [SLUG])
    assert counts["bundles"] == 1 and counts["profiles"] > 0


def bundle_path(folder: Path) -> Path:
    return folder / SLUG / "engine-l50.json"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda b: b.update(surprise=1), "surprise|field"),
        (lambda b: b["constants"].update(**{"__proto__": "1/2"}), "proto|key"),
        (lambda b: b["constants"].update(many=[f"{n}/7" for n in range(1, 2700) if n % 7]), "exact number|too many|2500|2,500"),
        (lambda b: b.update(version=2), "version"),
        (lambda b: b["races"][0].update(code=5), "race|code"),
    ],
    ids=["a field it does not know", "a forbidden name", "too many exact numbers", "another version", "a race code that is no text"],
)
def test_a_bundle_the_browsers_reader_refuses_refuses_the_release(tmp_path, change, message):
    need_node()
    folder = results_copy(tmp_path)
    edit(bundle_path(folder), change)
    with pytest.raises(ReleaseRefused, match="bundle") as raised:
        release.check_bundle_reader(folder, [SLUG])
    assert f"{SLUG}/engine-l50.json" in str(raised.value) and re.search(message, str(raised.value), re.IGNORECASE), str(raised.value)


def test_a_trio_with_no_bundle_is_refused_by_name(tmp_path):
    folder = results_copy(tmp_path)
    bundle_path(folder).unlink()
    with pytest.raises(ReleaseRefused, match=rf"{SLUG}.*engine-l"):
        release.check_bundle_reader(folder, [SLUG])


# ---- the parity suite --------------------------------------------------------------------------------------------------------------------


def test_the_parity_suite_passes_when_the_runner_says_so(tmp_path):
    seen = {}

    def runner(folder, sample, files):
        seen.update(folder=folder, sample=sample, files=tuple(files))
        return 0, "all good\n"

    release.check_parity(tmp_path, sample="3/50", runner=runner)
    assert seen["folder"] == tmp_path and seen["sample"] == "3/50"
    assert set(seen["files"]) == {"tests-js/parity-fixtures.test.mjs", "tests-js/engine-solve-parity.test.mjs", "tests-js/shard-parity.test.mjs"}


def test_a_failing_parity_suite_refuses_the_release_and_shows_the_end_of_its_output(tmp_path):
    lines = [f"line {n}" for n in range(100)] + ["FAIL  tests-js/shard-parity.test.mjs", "3 of 40 views differ from their shard"]

    def runner(folder, sample, files):
        return 1, "\n".join(lines) + "\n"

    with pytest.raises(ReleaseRefused, match="parity suite") as raised:
        release.check_parity(tmp_path, sample="0/1", runner=runner)
    text = str(raised.value)
    assert "3 of 40 views differ" in text and "line 5\n" not in text + "\n"  # the end, not the beginning


def test_a_parity_suite_that_cannot_be_started_refuses_the_release(tmp_path):
    def runner(folder, sample, files):
        raise OSError("node is not here")

    with pytest.raises(ReleaseRefused, match="parity suite.*could not"):
        release.check_parity(tmp_path, sample="0/1", runner=runner)


@pytest.mark.parametrize("sample", ["", "1", "a/b", "5/3", "0/0", "-1/4", "1/2/3", "0/ 1"])
def test_a_sample_that_is_not_i_over_n_is_refused_before_anything_runs(tmp_path, sample):
    with pytest.raises(ReleaseRefused, match="sample"):
        release.check_parity(tmp_path, sample=sample, runner=lambda *a: (0, ""))


def test_the_real_shard_parity_runs_on_the_solved_fixture_and_refuses_a_shard_that_is_not_what_the_engine_solves(tmp_path):
    need_node()
    release.check_parity(SOLVED, sample="0/1", files=("tests-js/shard-parity.test.mjs",))
    broken = tmp_path / "solved"
    shutil.copytree(SOLVED, broken)
    shard = broken / SLUG / "wiki-own.json"
    document = load(shard)
    document["scenarios"][0][5] += 7.0  # a value the engine will not find
    save(shard, document)
    with pytest.raises(ReleaseRefused, match="parity suite"):
        release.check_parity(broken, sample="0/1", files=("tests-js/shard-parity.test.mjs",))


# ---- no path of this computer in what is published ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "the asset is at C:\\Users\\<user>\\trioforge\\build\\release\\data-2026-10-10.tar.gz",  # (<user>: the privacy scan's placeholder for a name, so that this file holds none)
        "D:/tf-build/release/data-2026-10-10.tar.gz",
        "kept at E:\\tf\\x",
        "\\\\nas\\share\\tf\\x",
        '{"path": "C:\\\\Users\\\\<user>"}',  # the same, as JSON writes a backslash
        "see /home/<user>/trioforge/build",
        "in /Users/<user>/trioforge",
        "file:///C:/Users/<user>/y",
        "/tmp/pytest-of-someone/pytest-1/x",
        "the build folder /mnt/d/tf-build",
    ],
)
def test_an_absolute_path_in_a_published_text_is_refused_wherever_the_build_folder_is(tmp_path, text):
    with pytest.raises(ReleaseRefused, match="absolute path") as raised:
        release.check_no_local_paths(None, {"reports/results-diff-data-2026-10-17.md": text.encode("utf-8") + b"\n"})
    assert "reports/results-diff-data-2026-10-17.md:1" in str(raised.value)
    assert "<user>" not in str(raised.value) and "tf-build" not in str(raised.value) and "someone" not in str(raised.value)  # (it names the file and the line, not the path)


@pytest.mark.parametrize(
    "text",
    [
        "# Results diff: data-2026-10-17 against data-2026-10-10",
        "1/2 and/or +4/+10 and 3:1, a ratio like 5:/",
        "see https://eqlwiki.com/index.php?title=Cap:Test and releases/data-2026-10-10.json",
        "the folder releases/ and reports/results-diff-data-2026-10-17.md, or build/release/x.tar.gz",
        "Quest in Lake Rathetear: speak to the Invented Guard / Banker",
        '{"HEAD": "MANA x2", "note": "Monk curve full until 34"}',
    ],
)
def test_ordinary_text_and_relative_names_are_no_path(text):
    release.check_no_local_paths(None, {"reports/x.md": text.encode("utf-8") + b"\n"})


def test_a_path_in_a_file_of_the_release_is_refused_by_its_place_and_line(tmp_path):
    folder = results_copy(tmp_path)
    target = folder / SLUG / "defaults.json"
    target.write_text('{"a": 1}\n{"where": "C:\\\\Users\\\\<user>\\\\x"}\n', encoding="utf-8")
    with pytest.raises(ReleaseRefused, match="absolute path") as raised:
        release.check_no_local_paths(folder, {})
    assert f"{SLUG}/defaults.json:2" in str(raised.value) and str(tmp_path) not in str(raised.value)


def test_the_fixture_release_has_no_path_in_any_of_its_files(tmp_path):
    release.check_no_local_paths(results_copy(tmp_path), {})
    release.check_no_local_paths(SOLVED, {})


def test_the_gate_refuses_a_path_before_the_keyed_scan_runs_and_whatever_the_build_folder_is(privacy, monkeypatch):
    called = []
    monkeypatch.setattr(release.PrivacyScanner, "scan", lambda self, *args, **kwargs: called.append(1))
    with pytest.raises(ReleaseRefused, match="absolute path"):
        release.privacy_gate(scanner(privacy), privacy.folder, {"reports/x.md": b"the asset is at D:\\tf-build\\release\\x.tar.gz\n"})
    with pytest.raises(ReleaseRefused, match="absolute path"):
        release.privacy_gate(scanner(privacy), None, {"releases/x.json": b'{"path": "/home/<user>/tf"}\n'})
    assert called == []


def test_the_gate_runs_the_keyed_scan_when_no_path_is_found(privacy):
    assert release.privacy_gate(scanner(privacy), privacy.folder, {"reports/x.md": b"# Results diff\n"}) > 0


# ---- the key-check line of the denylist ------------------------------------------------------------------------------------------------------


def test_a_denylist_without_a_key_check_line_is_refused_as_a_wrong_key_could_not_be_told(privacy):
    path = privacy.root / "privacy" / "denylist.hmac"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert any("key-check" in line for line in lines)  # (the synthetic denylist has one)
    path.write_text("\n".join(line for line in lines if "key-check" not in line) + "\n", encoding="utf-8")
    with pytest.raises(ReleaseRefused, match="key-check|key check"):
        scanner(privacy)


# ---- the sample of the parity suite ------------------------------------------------------------------------------------------------------------


def facts_with_chunks(*counts: int) -> list[release.TrioFacts]:
    return [
        release.TrioFacts(f"war-clr-{code}", (0, 4, 10), ("balanced",), (50,), "data-2030-01-02", "2026-10-13", "2026-09-22", 50, chunks)
        for code, chunks in zip(("pal", "rng", "shd", "dru", "mnk", "brd"), counts)
    ]


def test_the_offset_of_the_sample_is_drawn_from_the_snapshot_id_and_is_the_same_for_the_same_id():
    samples = {release.parity_sample(f"{n:032x}", 50) for n in range(60)}
    assert len({int(s.split("/")[0]) for s in samples}) > 20 and all(re.fullmatch(r"[0-9]{1,2}/50", s) and int(s.split("/")[0]) < 50 for s in samples)
    assert release.parity_sample("ab" * 16, 50) == release.parity_sample("ab" * 16, 50)
    assert release.parity_sample("ab" * 16, 1) == "0/1"


def test_the_stride_is_bounded_so_that_every_trio_has_at_least_the_minimum_of_chunks_in_the_sample():
    facts = facts_with_chunks(96, 30, 84)
    assert release.parity_stride_limit(facts) == 30 // release.PARITY_MIN_CHUNKS
    default = release.choose_parity_sample(facts, "ab" * 16)
    assert default.endswith(f"/{release.parity_stride_limit(facts)}")  # (nothing is asked: the lightest sample that is allowed)
    assert release.choose_parity_sample(facts, "ab" * 16, stride=1) == "0/1"
    for too_big in (release.parity_stride_limit(facts) + 1, 999_999):
        with pytest.raises(ReleaseRefused, match=r"stride.*(largest|at most)"):
            release.choose_parity_sample(facts, "ab" * 16, stride=too_big)
    for bad in (0, -3):
        with pytest.raises(ReleaseRefused, match="stride"):
            release.choose_parity_sample(facts, "ab" * 16, stride=bad)


@pytest.mark.parametrize("counts", [(96, 30, 84), (36, 36), (88, 41, 97, 60), (30,)])
def test_every_trio_has_a_chunk_in_the_sample_whatever_the_offset(counts):
    """The chunks of the folder are numbered trio by trio, so a trio is a run of consecutive numbers: a stride no longer than the run cannot miss it."""
    facts = facts_with_chunks(*counts)
    for n in range(40):
        index, count = map(int, release.choose_parity_sample(facts, f"{n:032x}").split("/"))
        start = 0
        for chunks in counts:
            hit = [at for at in range(start, start + chunks) if at % count == index]
            assert len(hit) >= release.PARITY_MIN_CHUNKS, (counts, n, chunks)
            start += chunks


# ---- the rules in release.json -----------------------------------------------------------------------------------------------------------------


def test_the_rules_of_a_release_are_their_values_and_levels_and_not_their_status():
    snapshot = release._rules_snapshot(REPO)
    document = json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))
    assert set(snapshot) == {rule["id"] for rule in document["rules"]}
    for rule in document["rules"]:
        assert snapshot[rule["id"]] == {name: rule[name] for name in ("value", "levels") if name in rule}
    assert not any("status" in entry for entry in snapshot.values())


# ---- file URLs with one slash, and shares written with forward slashes ----------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["file:/data/export.json", "see file:/data/x and more", "FILE:/data/x", "file:///data/x", "(file:/srv)"])
def test_a_file_url_with_one_slash_or_more_is_refused(text):
    with pytest.raises(ReleaseRefused, match="absolute path"):
        release.check_no_local_paths(None, {"reports/x.md": text.encode("utf-8") + b"\n"})


@pytest.mark.parametrize("text", ["//server/share/tf/x", "the share //nas/tf-build/release", '{"path": "//nas/share/x"}', "(//host.example/share/)", "=//nas/tf"])
def test_a_share_written_with_forward_slashes_is_refused(text):
    with pytest.raises(ReleaseRefused, match="absolute path") as raised:
        release.check_no_local_paths(None, {"reports/x.md": text.encode("utf-8") + b"\n"})
    assert "reports/x.md:1" in str(raised.value)


@pytest.mark.parametrize(
    "text",
    [
        "https://eqlwiki.com/index.php?title=Test_Item",
        "http://example.org//a/b/c and https://eqlwiki.com/",
        "a//b/c and 1//2/3 and a // b and the end //",
        "ab:// y and profile:/x and compile:/y",
        "(https://eqlwiki.com/) // not a share",
    ],
)
def test_a_web_address_and_an_ordinary_double_slash_are_no_share_and_no_file_url(text):
    release.check_no_local_paths(None, {"reports/x.md": text.encode("utf-8") + b"\n"})


def test_the_real_catalog_with_the_urls_of_its_wiki_has_no_path_in_it():
    catalog = REPO / "derived" / "catalog.json"
    data = catalog.read_bytes()
    assert b"https://" in data  # (the addresses of the wiki are there to be passed)
    release.check_no_local_paths(None, {"derived/catalog.json": data})


# ---- an item has one row in a release ---------------------------------------------------------------------------------------------------------------


def test_every_shard_and_trio_of_a_release_shows_an_item_with_the_same_row(tmp_path):
    folder = results_copy(tmp_path)
    assert release.check_item_rows(folder, [SLUG]) > 0


def test_an_item_whose_row_differs_in_a_shard_refuses_the_release_naming_the_item_and_the_two_shards(tmp_path):
    folder = results_copy(tmp_path)

    def change(document):
        for row in document["items"]:
            if row[0] == "w80113":
                row[5] = "Quest in Another Zone"

    edit(folder / SLUG / "wiki-group.json", change)
    with pytest.raises(ReleaseRefused, match=r"w80113.*strict-own\.json.*wiki-group\.json|w80113.*wiki-group\.json.*strict-own\.json") as raised:
        release.check_item_rows(folder, [SLUG])
    assert "Another Zone" not in str(raised.value)  # (it names the item and the files, not the text)


def test_an_item_whose_row_differs_between_two_trios_refuses_the_release(tmp_path):
    folder = results_copy(tmp_path)
    shutil.copytree(folder / SLUG, folder / "war-clr-pal")

    def change(document):
        for row in document["items"]:
            if row[0] == "w80113":
                row[4] = 9  # the arrival tier

    edit(folder / "war-clr-pal" / "strict-own.json", change)
    with pytest.raises(ReleaseRefused, match=r"w80113.*war-clr-pal"):
        release.check_item_rows(folder, [SLUG, "war-clr-pal"])


# ---- the questions the build asks git, and the places a private file may be written -------------------------------------------------------------------


def test_the_state_of_a_git_worktree_changes_with_a_commit_an_edit_and_a_new_file_and_not_otherwise(tmp_path, gitenv):
    repo = make_repo(tmp_path / "repo")
    write(repo, "a.txt", "one\n")
    write(repo, "b.bin", b"\x00\x01\x02")
    run_git(repo, "add", "a.txt", "b.bin")
    commit(repo, "one")
    git = release.Git(repo)
    start = git.state()
    assert len(start) == 3 and re.fullmatch(r"[0-9a-f]{40}", start[0]) and git.state() == start
    write(repo, "a.txt", "two\n")  # an edit of a tracked file: the status and the diff, not the head
    edited = git.state()
    assert edited[0] == start[0] and edited[1] != start[1] and edited[2] != start[2]
    run_git(repo, "checkout", "--", "a.txt")
    assert git.state() == start
    write(repo, "b.bin", b"\x00\x01\x03")  # a binary file: the diff holds it (--binary)
    assert git.state()[2] != start[2]
    run_git(repo, "checkout", "--", "b.bin")
    write(repo, "new.txt", "x")  # an untracked file: the status only
    added = git.state()
    assert added[1] != start[1] and added[2] == start[2] and added[0] == start[0]
    run_git(repo, "add", "new.txt")
    commit(repo, "two")
    assert git.state()[0] != start[0]


def test_git_says_which_paths_are_tracked_and_which_are_ignored(tmp_path, gitenv):
    repo = make_repo(tmp_path / "repo")
    write(repo, "a.txt", "one\n")
    write(repo, ".gitignore", "build/\n")
    run_git(repo, "add", "a.txt", ".gitignore")
    commit(repo, "one")
    git = release.Git(repo)
    assert git.tracked(repo / "a.txt") and not git.tracked(repo / "reports" / "x.md")
    assert git.ignored(repo / "build" / "reports" / "x.json") and not git.ignored(repo / "reports" / "x.json")


def test_git_that_cannot_be_asked_whether_a_path_is_tracked_refuses_and_never_answers_untracked(tmp_path, gitenv, monkeypatch):
    """The answer decides whether the build may delete a file. A failure of git (it does not start, it does not answer in time, it dies on a damaged index) is no answer;
    only git's own word that the path is not tracked counts as untracked."""
    repo = make_repo(tmp_path / "repo")
    write(repo, "reports/results-diff-x.md", "one\n")
    run_git(repo, "add", "reports")
    commit(repo, "a tracked report")
    git = release.Git(repo)
    report = repo / "reports" / "results-diff-x.md"
    assert git.tracked(report) is True and git.tracked(repo / "reports" / "results-diff-y.md") is False  # (git's own answers)
    asked = r"git could not be asked whether reports/results-diff-x\.md is tracked"
    for fault in (OSError("git cannot be started"), subprocess.TimeoutExpired("git", release.GIT_TIMEOUT)):

        def broken(*args, **kwargs):
            raise fault

        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "run", broken)
            with pytest.raises(ReleaseRefused, match=asked):
                git.tracked(report)
    (repo / ".git" / "index").write_bytes(b"not an index")  # git stops with status 128 on it
    with pytest.raises(ReleaseRefused, match=asked):
        git.tracked(report)
    with pytest.raises(ReleaseRefused, match=r"results-diff-y\.md is tracked"):  # (nor can it say that a path is not in an index it cannot read)
        git.tracked(repo / "reports" / "results-diff-y.md")


def test_a_path_outside_the_work_tree_is_one_that_git_cannot_say_is_untracked(tmp_path, gitenv):
    repo = make_repo(tmp_path / "repo")
    git = release.Git(repo)
    with pytest.raises(ReleaseRefused, match=r"git could not be asked whether x\.md is tracked"):
        git.tracked(tmp_path / "elsewhere" / "x.md")


def test_a_folder_that_is_not_a_git_worktree_is_refused(tmp_path, gitenv):
    (tmp_path / "plain").mkdir()
    with pytest.raises(ReleaseRefused, match="git worktree"):
        release.Git(tmp_path / "plain")


def test_a_private_output_must_be_where_git_ignores_it(tmp_path, gitenv):
    repo = make_repo(tmp_path / "repo")
    write(repo, ".gitignore", "build/\n")
    run_git(repo, "add", ".gitignore")
    commit(repo, "ignore")
    git = release.Git(repo)
    release.check_private_output(repo / "build" / "reports" / "results-diff-x.json", git)  # ignored: fine
    with pytest.raises(ReleaseRefused, match="ignore") as raised:
        release.check_private_output(repo / "reports" / "results-diff-x.json", git)
    assert "results-diff-x.json" in str(raised.value)
    release.check_private_output(tmp_path / "elsewhere" / "results-diff-x.json", git)  # outside every work tree: git cannot commit it


def test_a_private_output_is_checked_by_the_path_itself_and_not_by_the_names_of_the_catalog(tmp_path, gitenv):
    repo = make_repo(tmp_path / "repo")
    write(repo, ".gitignore", "catalog.json\ncatalog-summary.json\ncatalog-warnings.json\nsources-manifest.json\n")
    run_git(repo, "add", ".gitignore")
    commit(repo, "a rule that is too narrow")
    git = release.Git(repo)
    with pytest.raises(ReleaseRefused, match="ignore"):
        release.check_private_output(repo / "build" / "seen-flags-snapshot.json", git)
    with pytest.raises(ReleaseRefused, match="ignore"):
        release.check_private_output(repo / "build" / "reports" / ".results-diff-x.json.x.tmp", git)


def test_the_build_folder_must_be_ignored_as_a_whole_or_lie_outside_every_work_tree(tmp_path, gitenv):
    repo = make_repo(tmp_path / "repo")
    write(repo, ".gitignore", "build/results/\nbuild/reports/\n")  # rules for some of what a build writes there
    run_git(repo, "add", ".gitignore")
    commit(repo, "rules that ignore the build folder in part")
    git = release.Git(repo)
    assert git.ignored(repo / "build" / "results" / "x.json") and git.ignored(repo / "build" / "reports" / "x.json")  # (the parts are ignored ...)
    with pytest.raises(ReleaseRefused, match=r"the build folder build is not ignored by git as a whole"):  # (... and the folder is not)
        release.check_build_folder(repo / "build", git)
    write(repo, ".gitignore", "build/\n")
    release.check_build_folder(repo / "build", git)  # ignored as a whole (it need not exist yet)
    release.check_build_folder(tmp_path / "elsewhere" / "build", git)  # outside every work tree: git cannot commit anything in it


def test_a_link_or_junction_on_the_way_to_a_private_output_is_refused_whatever_git_says(tmp_path, gitenv):
    repo = make_repo(tmp_path / "repo")
    write(repo, ".gitignore", "build/\n")
    run_git(repo, "add", ".gitignore")
    commit(repo, "ignore")
    (repo / "reports").mkdir()
    (repo / "build").mkdir()
    make_junction(repo / "build" / "reports", repo / "reports")  # build/reports/x.json is ignored by the text of its path, and is written to reports/x.json
    git = release.Git(repo)
    assert git.ignored(repo / "build" / "reports" / "x.json")  # (git reads the text of the path)
    with pytest.raises(ReleaseRefused, match="link|junction") as raised:
        release.check_private_output(repo / "build" / "reports" / "x.json", git)
    assert "reports" in str(raised.value)
