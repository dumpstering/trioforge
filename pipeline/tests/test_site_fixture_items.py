"""The site fixture, its end-to-end specs and the generator of its engine data show no real item.

The fixture stands in for the results of a trio, and its items are at the level ``strict``. The public catalog has no strict item at all:
that level comes from the maintainer's own observations, which are never published. A real item of the wiki shown at that level in a public
fixture would read as a statement about them. So every item the fixture shows is invented, under a name and a key (``w`` and a number) that no
page of the wiki has, and these tests fail when the key or the name of an item of ``derived/catalog.json`` turns up in a file that holds or
makes the fixture. They do not read the observations, and they need nothing but the catalog, which is committed.

A key is looked for as a token of its own (``w12345``, ``w12345@4``, not ``w123456`` or ``raw12345``) and as the page id of an item record of
a JSON file (``{"id": 12345, "name": ...}``, how the engine's item table writes it). A name, or a wiki title, is looked for as a run of words
anywhere in a string or in the file when it is three words or more (whatever its case, punctuation or HTML escapes), and as the whole of a
string of the file (a JSON string, a quoted string of the code, the text of an element of a page) when it is one or two: the wiki has items
named Short Bow, File, Key and Note, and the invented Short Bow of the Fallen, a ``"key"`` of a JSON object or a ``'note'`` of a spec are none
of them. A name of one word is taken only as the wiki spells it.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CATALOG = REPO / "derived" / "catalog.json"
#: where the invented items are held (the fixture, with the data the build writes from it for the browser tests, and the dumps of inventory files made
#: from its items) and named (the end-to-end specs of the site, the generator of the engine data, which lists the stats of every item, the tests of the
#: Upgrade section, which read those dumps: the older files of tests-js name real items on purpose, to test the matcher against the names of the game, and
#: stay out of this scan, so the new ones are listed by name; the tests of the list of files of a site, whose item pages have invented keys, and the tests of the item
#: pages, which build them from the fixture and pick real items from the catalog by their shape, naming none)
UPGRADE_TESTS = (
    "gear-picker.test.mjs",
    "upgrade-input.test.mjs",
    "upgrade-load.test.mjs",
    "upgrade-helpers.mjs",
    "upgrade-answer.test.mjs",
    "upgrade-answer-page.test.mjs",
    "upgrade-answer-helpers.mjs",
    "upgrade-more.test.mjs",
    "upgrade-more-helpers.mjs",
    "upgrade-share.test.mjs",
    "upgrade-shared-kit.test.mjs",
    "upgrade-remember.test.mjs",
    "upgrade-remember-page.test.mjs",
    "kit-page.test.mjs",
    "engine-kitvalue.test.mjs",
    "engine-kitvalue-worker.test.mjs",
    "engine-manifest-kitvalue.test.mjs",
    "kitdecode.test.mjs",
)
SCANNED = (
    REPO / "fixtures" / "site",
    REPO / "fixtures" / "dumps",
    REPO / "tests-e2e",
    REPO / "pipeline" / "tests" / "engine_fixture.py",
    REPO / "pipeline" / "tests" / "test_site_counts.py",
    REPO / "pipeline" / "tests" / "test_site_files.py",
    REPO / "pipeline" / "tests" / "test_site_item_pages.py",
    REPO / "pipeline" / "tests" / "test_site_items.py",
    *(REPO / "tests-js" / name for name in UPGRADE_TESTS),
)
SKIPPED_FOLDERS = {"__pycache__", "node_modules", "test-results", "playwright-report"}

KEY = re.compile(r"(?<![\w])w([1-9][0-9]*)(?![\w])")
WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)*")
LITERAL = re.compile(r"\"((?:[^\"\\\n]|\\.)*)\"|'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`")
TAG = re.compile(r"<[^>]*>")


def files_of(roots: Iterable[Path]) -> list[Path]:
    """Every file under the roots (a root may be one file), in a fixed order, without caches and installed packages."""
    found = []
    for root in roots:
        candidates = [root] if root.is_file() else sorted(root.rglob("*")) if root.is_dir() else []
        found.extend(p for p in candidates if p.is_file() and not SKIPPED_FOLDERS & set(p.parts))
    return found


def keys_and_names(catalog: dict) -> tuple[set[str], set[str]]:
    """The keys, and the names with the wiki titles, of the items of a catalog document."""
    keys, names = set(), set()
    for item in catalog["items"]:
        keys.add(item["key"])
        names.add(item["name"])
        title = (item.get("wiki") or {}).get("title")
        if title:
            names.add(title)
    return keys, names


class Names:
    """A set of names to look for in strings: one word only as the whole string and spelt as it is, two words only as the whole string
    (whatever the case), three words or more as a run of words (whatever the case) wherever they are."""

    def __init__(self, names: Iterable[str]) -> None:
        self.single: set[str] = set()
        self.pairs: set[tuple[str, ...]] = set()
        self.runs: dict[str, list[tuple[str, ...]]] = {}
        for name in names:
            words = tuple(WORD.findall(name.casefold()))
            if len(words) == 1:
                self.single.add(name.strip())
            elif len(words) == 2:
                self.pairs.add(words)
            elif words:
                self.runs.setdefault(words[0], []).append(words)

    def in_string(self, text: str) -> set[str]:
        words = WORD.findall(text.casefold())
        found = {text.strip()} if text.strip() in self.single else set()
        if tuple(words) in self.pairs:
            found.add(" ".join(words))
        for at, word in enumerate(words):
            for run in self.runs.get(word, ()):
                if tuple(words[at : at + len(run)]) == run:
                    found.add(" ".join(run))
        return found


def json_strings(value) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from json_strings(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from json_strings(inner)


def record_keys(value) -> Iterator[str]:
    """The keys of the item records a JSON document holds: an object with a whole ``id`` (the page of the wiki) and a ``name``."""
    if isinstance(value, dict):
        if isinstance(value.get("id"), int) and not isinstance(value["id"], bool) and "name" in value:
            yield f"w{value['id']}"
        for inner in value.values():
            yield from record_keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from record_keys(inner)


def keys_in(path: Path, text: str) -> set[str]:
    found = {f"w{match.group(1)}" for match in KEY.finditer(text)}
    if path.suffix == ".json":
        try:
            found |= set(record_keys(json.loads(text)))
        except ValueError:
            pass
    return found


def strings_of(path: Path, text: str) -> Iterator[str]:
    """The strings of a file in which a name could stand: those a JSON file holds; for any other file its whole text (for a run of words in
    prose), its quoted strings and the text between its tags (for a name that is one word)."""
    if path.suffix == ".json":
        try:
            yield from json_strings(json.loads(text))
            return
        except ValueError:
            pass
    yield text
    for match in LITERAL.finditer(text):
        yield html.unescape(next(group for group in match.groups() if group is not None))
    for node in TAG.split(text):
        yield html.unescape(node)


def scan(roots: Iterable[Path], keys: set[str], names: Names) -> dict[str, tuple[list[str], list[str]]]:
    """For each file under the roots that holds a key or a name of the catalog: the keys and the names it holds."""
    held = {}
    for path in files_of(roots):
        text = path.read_text(encoding="utf-8", errors="replace")
        found_names: set[str] = set()
        for string in strings_of(path, text):
            found_names |= names.in_string(string)
        found_keys = keys_in(path, text) & keys
        if found_keys or found_names:
            held[path.relative_to(REPO).as_posix() if REPO in path.parents else path.name] = (sorted(found_keys), sorted(found_names))
    return held


@pytest.fixture(scope="module")
def held():
    assert CATALOG.is_file(), "derived/catalog.json is committed: the fixture cannot be checked without it"
    keys, names = keys_and_names(json.loads(CATALOG.read_text(encoding="utf-8")))
    assert len(keys) > 1000 and len(names) > 1000  # the catalog of the wiki, not an empty or a trimmed one
    return scan(SCANNED, keys, Names(names))


def test_the_scan_covers_the_fixture_its_end_to_end_specs_and_the_generator_of_its_engine_data():
    scanned = {p.relative_to(REPO).as_posix() for p in files_of(SCANNED)}
    assert {
        "fixtures/site/results/items.json",
        "fixtures/site/results/pal-mnk-ber/wiki-own.json",
        "fixtures/site/results/pal-mnk-ber/runnerups/balanced.json",
        "fixtures/site/contract/data/strict-own.json",
        "fixtures/site/contract/trio-main.html",
        "fixtures/site/equip-now.json",
        "fixtures/site/kit-values.json",
        "fixtures/site/sources-manifest.json",
        "tests-e2e/engine.spec.mjs",
        "pipeline/tests/engine_fixture.py",
        "pipeline/tests/test_site_counts.py",
        "pipeline/tests/test_site_files.py",
        "pipeline/tests/test_site_item_pages.py",
        "pipeline/tests/test_site_items.py",
    } <= scanned
    assert len(scanned) >= 30


def test_the_scan_covers_the_dumps_and_the_tests_of_the_upgrade_section():
    scanned = {p.relative_to(REPO).as_posix() for p in files_of(SCANNED)}
    assert {"fixtures/dumps/site-small.txt", "fixtures/dumps/site-mixed.txt", "tests-e2e/upgrade.spec.mjs"} <= scanned
    assert {f"tests-js/{name}" for name in UPGRADE_TESTS} <= scanned
    assert all(p.is_file() for p in (REPO / "tests-js" / name for name in UPGRADE_TESTS))  # a name that is not a file would be scanned as nothing
    assert not {p for p in scanned if p.startswith("tests-js/")} - {f"tests-js/{name}" for name in UPGRADE_TESTS}  # and no older test file, which names real items


def test_no_item_key_of_the_wiki_is_in_the_fixture_the_end_to_end_specs_or_the_generator(held):
    lines = [f"{where}: {keys[:8]}" for where, (keys, _) in held.items() if keys]
    assert not lines, "a key of a real item (derived/catalog.json) is in a file of the fixture:\n" + "\n".join(lines)


def test_no_item_name_of_the_wiki_is_in_the_fixture_the_end_to_end_specs_or_the_generator(held):
    lines = [f"{where}: {names[:8]}" for where, (_, names) in held.items() if names]
    assert not lines, "the name of a real item (derived/catalog.json) is in a file of the fixture:\n" + "\n".join(lines)


# ---- the scan itself ------------------------------------------------------------------------------------------------------------------------
# A scan that finds nothing proves nothing, so these make a small catalog of invented items and write each of them where the fixture could.

TINY = {
    "items": [
        {"key": "w7", "name": "Moon Blade", "wiki": {"title": "Moon Blade"}},
        {"key": "w4242", "name": "Ring of Two Moons", "wiki": {"title": "Ring of Two Moons (old)"}},
        {"key": "w9", "name": "Cap", "wiki": None},
    ]
}


def tiny_scan(tmp_path: Path, name: str, text: str) -> dict[str, tuple[list[str], list[str]]]:
    (tmp_path / name).write_text(text, encoding="utf-8")
    keys, names = keys_and_names(TINY)
    return scan([tmp_path], keys, Names(names))


@pytest.mark.parametrize(
    ("name", "text", "keys", "names"),
    [
        ("rows.json", json.dumps({"items": [["w4242", "x"]]}), ["w4242"], []),
        ("rows.json", json.dumps({"w7@4": 1}), ["w7"], []),
        ("rows.json", json.dumps({"items": [{"id": 4242, "name": "x"}]}), ["w4242"], []),  # how the item table of the engine writes a page
        ("rows.json", json.dumps({"items": [["w90001", "Moon Blade"]]}), [], ["moon blade"]),
        ("rows.json", json.dumps({"items": [["w90001", "MOON blade"]]}), [], ["moon blade"]),  # two words: the whole string, whatever the case
        ("rows.json", json.dumps({"label": "Ring of Two Moons +4"}), [], ["ring of two moons"]),
        ("rows.json", json.dumps({"label": "Ring of Two Moons (old)"}), [], ["ring of two moons", "ring of two moons old"]),
        ("rows.json", json.dumps({"Cap": 3}), [], ["Cap"]),
        ("page.html", "<td data-f='name'>Moon&#32;Blade</td>", [], ["moon blade"]),
        ("page.html", "<p>She wears the Ring of Two Moons today.</p>", [], ["ring of two moons"]),
        ("page.html", '<a title="Cap" href="#">x</a>', [], ["Cap"]),
        ("spec.mjs", 'expect(row).toBe("Moon Blade");', [], ["moon blade"]),
        ("spec.mjs", "const kit = ['w7@0', null];", ["w7"], []),
        ("fixture.py", '    "w4242": {"stats": {"AC": 3}},', ["w4242"], []),
        ("fixture.py", "# the Ring of Two Moons is not here\n", [], ["ring of two moons"]),
        ("notes.txt", "w7\n", ["w7"], []),
    ],
)
def test_the_scan_finds_a_key_or_a_name_wherever_a_file_could_write_it(tmp_path, name, text, keys, names):
    assert tiny_scan(tmp_path, name, text) == {name: (keys, names)}


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("rows.json", json.dumps({"items": [["w72", "x"], ["w42420", "y"], ["w07", "z"], ["rw7", "q"], ["w7x", "r"]]})),
        ("rows.json", json.dumps({"items": [{"id": 4242}, {"id": "4242", "name": "x"}, {"id": 7, "label": "x"}, {"id": True, "name": "x"}]})),
        ("rows.json", json.dumps({"label": "Moon Blades", "other": "Moon", "again": "Blade of the Moon"})),
        ("rows.json", json.dumps({"label": "Moon Blade of Old", "more": "the Moon Blade", "again": "Moon Blade +4"})),  # two words, not the whole string
        ("rows.json", json.dumps({"label": "Ring of Two Moonstones", "more": "Ring of Two"})),
        ("rows.json", json.dumps({"label": "The Cap fits", "count": 9})),  # a one-word name is the whole string or nothing
        ("rows.json", json.dumps({"cap": 3, "items_keys": ["key", "cap"]})),  # and it is spelt as the wiki spells it: Cap, not a "cap" of a schema
        ("page.html", "<td>Capital</td><td>Mooney Blade</td>"),
        ("spec.mjs", 'const w70001 = "Cap of the Wizard";\n'),
    ],
)
def test_the_scan_leaves_look_alikes_alone(tmp_path, name, text):
    assert tiny_scan(tmp_path, name, text) == {}


def test_the_scan_reads_the_files_it_is_given_and_nothing_under_a_cache_or_an_installed_package(tmp_path):
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "node_modules" / "pkg" / "a.json").write_text('{"k": "Moon Blade"}', encoding="utf-8")
    (tmp_path / "__pycache__" / "b.py").write_text("w7 = 'Moon Blade'", encoding="utf-8")
    (tmp_path / "ok.json").write_text('{"k": "Moonlight"}', encoding="utf-8")
    assert [p.name for p in files_of([tmp_path])] == ["ok.json"]
    assert files_of([tmp_path / "missing"]) == []
