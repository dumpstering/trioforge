"""Tests for the content rules that flag text a public repository must not carry, and for the
kinds of file the scanner refuses.

* ``provenance``: words that point at the game client's binary (its name, a code listing, an
  address inside it, a section name).
* ``local-path``: a path into a user's profile folder on Windows, in Git Bash or on Linux.
* ``log-self``: the lines the client writes for the player's own chat.
* ``pdf`` and ``archive``: files that are refused whole.

Test data is invented. The words and paths these rules look for are built from pieces (see
``test_privacy_helpers``), so that no line of this file is itself a finding: the repository must
pass its own scanner.
"""

from __future__ import annotations

import base64

import pytest

from test_privacy_helpers import (  # noqa: F401  (fixtures are used by name)
    PROVENANCE_WORDS,
    SELF_FORMS,
    commit,
    gitbash_profile,
    gitenv,
    git,
    keyfile,
    parse_output,
    posix_home,
    privacy_files,
    repo,
    rules,
    run_cli,
    call_main,
    scan,
    scan_blob,
    self_line,
    windows_profile,
    write,
)
from trioforge.privacy import logshape
from trioforge.privacy import scan as S


def finding(path, line, col, rule):
    return S.Finding(path, line, col, rule, "-")


# ---- provenance ---------------------------------------------------------------------------


@pytest.mark.parametrize("word", list(PROVENANCE_WORDS.values()), ids=list(PROVENANCE_WORDS))
def test_provenance_words_are_found_in_contents(word):
    assert scan("notes about " + word + " here") == [finding("f.txt", 1, 13, "provenance")]


@pytest.mark.parametrize(
    "text",
    [
        "the rva of a thing",  # the lower-case form sits inside ordinary words
        "ARVA",
        "RVAs",
        "x.rdatax",
        "rdata",
        "assembler",
        "the game",
        "EQ",
    ],
)
def test_provenance_leaves_ordinary_words_alone(text):
    assert scan(text) == []


def test_provenance_is_found_in_a_decoded_form_too():
    percent = "%65" + "qgame"
    assert rules(scan("see " + percent)) == ["provenance"]
    note = base64.b64encode(("some note about " + PROVENANCE_WORDS["client name"] + " in a table").encode())
    assert rules(scan("data: " + note.decode())) == ["provenance"]


def test_provenance_is_found_in_a_commit_message_file(repo, keyfile):
    write(repo, "msg.txt", "fix " + PROVENANCE_WORDS["code listing, capitalised"] + " notes\n")
    done = run_cli(["--commit-msg", "msg.txt", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert [(f["path"], f["rule"]) for f in parse_output(done.stdout)] == [
        ("<commit-msg>", "provenance")
    ]


def test_provenance_is_found_in_the_history_of_messages_and_deleted_files(repo, keyfile):
    write(repo, "old.txt", "a line about " + PROVENANCE_WORDS["section"] + " here\n")
    git(repo, "add", "old.txt")
    commit(repo, "add a file")
    git(repo, "rm", "-q", "old.txt")
    commit(repo, "remove it, " + PROVENANCE_WORDS["client name in lower case"] + " notes")
    done = run_cli(["--history", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    found = sorted((f["path"].split(":")[0], f["rule"]) for f in parse_output(done.stdout))
    assert found == [("<commit", "provenance"), ("old.txt", "provenance")]


# ---- local-path ---------------------------------------------------------------------------

LOCAL_PATHS = {
    "windows, backslashes": (windows_profile("Vexandra") + "\\notes", 5),
    "windows, slashes": (windows_profile("Brannoc", "D", "/") + "/notes", 5),
    "windows, lower-case folder": ("c:\\" + "users" + "\\vexandra\\notes", 5),
    "git bash": (gitbash_profile("vexandra") + "/notes", 5),
    "git bash on another drive": (gitbash_profile("vexandra", "d") + "/notes", 5),
    "wsl": ("/mnt" + gitbash_profile("vexandra") + "/notes", 9),
    "linux home": (posix_home("vexandra") + "/notes", 5),
    "file url": ("file:///" + "home/vexandra/notes", 12),
}


@pytest.mark.parametrize(
    "path,column", list(LOCAL_PATHS.values()), ids=list(LOCAL_PATHS)
)
def test_local_profile_paths_are_found(path, column):
    assert scan("see " + path) == [finding("f.txt", 1, column, "local-path")]


def test_a_local_path_written_as_json_with_doubled_backslashes_is_found():
    assert scan(windows_profile("Vexandra", sep="\\\\")) == [finding("f.txt", 1, 1, "local-path")]


@pytest.mark.parametrize(
    "text",
    [
        windows_profile("<user>") + "\\AppData",
        windows_profile("<name>", "D", "/"),
        gitbash_profile("<name>") + "/notes",
        posix_home("<user>") + "/notes",
        posix_home("<name>"),
        "https://example.invalid/" + "home" + "/about",  # a web address, not a home folder
        "the Users folder",
        "C:" + "\\Windows\\System32",
        "/" + "homework/notes",
        "/c/" + "Usersguide/notes",
    ],
    ids=[
        "windows placeholder user",
        "windows placeholder name",
        "git bash placeholder",
        "linux placeholder user",
        "linux placeholder name",
        "web address",
        "the word Users",
        "system folder",
        "similar folder name",
        "similar guide name",
    ],
)
def test_placeholders_and_ordinary_paths_are_not_local_paths(text):
    assert scan(text) == []


def test_a_denylisted_name_inside_a_local_path_is_still_a_name_finding_too():
    result = scan(windows_profile("Zorblax"))
    assert sorted(rules(result)) == ["denylist", "local-path"]


# ---- log-self -----------------------------------------------------------------------------

MORE_SELF_FORMS = (
    "say to your guild",
    "say to your raid",
    "tell your guild",
    "tell your raid",
    "tell the group",
    "tell the raid",
)


@pytest.mark.parametrize("form", SELF_FORMS + MORE_SELF_FORMS)
def test_first_person_chat_lines_are_log_shaped(form):
    assert scan(self_line(form)) == [finding("f.txt", 1, 1, "log-self")]


def test_first_person_chat_in_a_longer_line_is_found_at_its_column():
    assert scan("pasted: " + self_line("shout")) == [finding("f.txt", 1, 9, "log-self")]


@pytest.mark.parametrize(
    "text",
    [
        "You " + "say hello",
        "You " + "said, '" + "x'",
        "You " + "tell Bob, '" + "x'",
        "They " + "say, '" + "x'",
        "You " + "tell General, '" + "x'",
        "if you " + "say, '" + "x'",
        "You " + "say, " + "x",
    ],
)
def test_text_that_is_not_a_first_person_chat_line_is_left_alone(text):
    assert scan(text) == []


def test_the_new_rules_are_listed_by_name():
    assert {"log-self", "local-path", "provenance"} <= set(logshape.RULE_NAMES)


# ---- files that are refused whole ---------------------------------------------------------


@pytest.mark.parametrize("path", ["report.pdf", "REPORT.PDF", "docs/a.b.pdf"])
def test_a_pdf_is_refused_by_its_name_without_reading_it(path):
    # The content would be a name finding if it were read.
    assert scan_blob(path, b"Zorblax") == [finding(path, 0, 0, "pdf")]


@pytest.mark.parametrize(
    "data",
    [b"%PDF-1.7\n1 0 obj\n", b"junk" + b"%PDF-1.4\n", b"x" * 1000 + b"%PDF-1.7\n"],
    ids=["at the start", "after a few bytes", "just inside the first kilobyte"],
)
def test_a_pdf_is_refused_by_its_magic_number_whatever_the_name(data):
    assert scan_blob("data.bin", data) == [finding("data.bin", 0, 0, "pdf")]


@pytest.mark.parametrize(
    "data",
    [b"The PDF format is common\n", b"%PDF without a dash\n", b"x" * 2000 + b"%PDF-1.7\n"],
    ids=["a mention", "no dash", "far from the start"],
)
def test_text_that_only_mentions_pdf_is_not_a_pdf(data):
    assert scan_blob("note.txt", data) == []


@pytest.mark.parametrize("name", ["sheet.xlsx", "letter.docx", "slides.pptx", "text.odt", "calc.ods"])
def test_office_and_open_document_files_are_zip_archives_and_are_refused(name):
    assert scan_blob(name, b"PK\x03\x04" + b"\x00" * 30) == [finding(name, 0, 0, "archive")]


def _filler(size: int) -> bytes:
    return (b"abcdefghij\n" * (size // 11 + 1))[:size]


@pytest.mark.parametrize("before", [100, 5000, 65536 - 4], ids=["100", "5000", "ends at the limit"])
def test_a_zip_header_anywhere_in_the_first_64_kib_marks_an_archive(before):
    data = _filler(before) + b"PK\x03\x04" + b"tail\n"
    assert before + 4 <= 65536
    assert scan_blob("data.bin", data) == [finding("data.bin", 0, 0, "archive")]


def test_a_zip_header_after_the_first_64_kib_is_not_looked_for():
    data = _filler(65536 - 3) + b"PK\x03\x04" + b"tail\n"  # the header ends one byte too late
    assert scan_blob("data.bin", data) == []


def test_a_zip_header_after_a_binary_stub_is_found():
    stub = b"MZ\x90\x00" + b"\x00" * 200
    assert scan_blob("tool.bin", stub + b"PK\x03\x04" + b"\x00" * 30) == [
        finding("tool.bin", 0, 0, "archive")
    ]
