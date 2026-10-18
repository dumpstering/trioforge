"""Acceptance tests for the privacy scanner, rows 1-27 of its table of cases.

The key is 32 zero bytes and the denylist holds the digests of two invented names.
See test_privacy_helpers for the shared fixtures and for the reasons strings shaped like
log lines are built at run time.

Rows that the second set of cases changed:

* Row 10 and row 11 said that content with a NUL byte in its first 8 KiB is skipped and only
  the path is scanned. Addendum case A5 replaces that with a ``strings``-style pass over the
  printable runs of binary content. The tests below keep each row's original intent (a binary
  file does not crash the scanner, and its path is always scanned) with bytes that hold no
  printable run, and also pin the new behaviour with the rows' own bytes.
"""

from __future__ import annotations

import hashlib
import random
import time

import pytest

from test_privacy_helpers import (  # noqa: F401  (fixtures are used by name)
    DENY,
    call_main,
    commit,
    git,
    gitenv,
    h,
    keyfile,
    loot_line,
    named_loot_line,
    parse_output,
    privacy_files,
    repo,
    rules,
    run_cli,
    scan,
    scan_blob,
    tag,
    write,
)
from trioforge.privacy import scan as S

OPAQUE = b"\x00\x01\x02\x03\xfe\xff" * 50  # NUL bytes and no printable run of 4 characters


def finding(path, line, col, rule, token=None):
    return S.Finding(path, line, col, rule, tag(token) if token else "-")


# ---- rows 1-3: a private name hidden by case, punctuation or joining -----------------


def test_row01_possessive_name_is_found_at_line_1_col_1():
    assert scan("Zorblax's kit") == [finding("f.txt", 1, 1, "denylist", "zorblax")]


@pytest.mark.parametrize(
    "text", ["ZORBLAX", "zorblax.json", "zorblax-bis", "ZorblaxBis", "zorblax2"]
)
def test_row02_name_hidden_by_case_punctuation_or_joining_is_found_once(text):
    assert scan(text) == [finding("f.txt", 1, 1, "denylist", "zorblax")]


@pytest.mark.parametrize("text", ["zorblaxian", "bis", "Zorb"])
def test_row03_longer_words_and_fragments_are_not_found(text):
    assert scan(text) == []


# ---- row 4: the path is scanned at line 0 -------------------------------------------------


def test_row04_a_private_name_in_the_path_is_a_line_0_finding():
    result = scan("clean content", path="notes/zorblax-bis.md")
    assert result == [finding("notes/zorblax-bis.md", 0, 7, "denylist", "zorblax")]


# ---- row 5: the allow list -----------------------------------------------------------------


def test_row05_an_allowed_digest_silences_only_its_own_token():
    assert scan("Quimmet waves", allow={h("quimmet")}) == []
    both = scan("Quimmet and Zorblax", allow={h("quimmet")})
    assert rules(both) == ["denylist"]
    assert both[0].tag == tag("zorblax")


# ---- rows 6-9: log-shape rules ---------------------------------------------------------


def test_row06_timestamp_line():
    text = "[" + "Mon Oct 13 19:53:47 2026" + "] hi"
    assert scan(text) == [finding("f.txt", 1, 1, "log-timestamp")]


def test_row07_tell_line_from_a_name_that_is_not_denylisted():
    assert scan("Vexandra" + " tells you, 'hello'") == [finding("f.txt", 1, 1, "log-tell")]


def test_row08_loot_line():
    assert scan("You have " + "looted a Rusty Dagger.") == [finding("f.txt", 1, 1, "log-loot")]


def test_row09_who_row():
    assert scan("[50 Paladin] " + "Vexandra (Ogre) <Guild>") == [
        finding("f.txt", 1, 1, "log-who")
    ]


# ---- rows 10-12: binary and non-UTF-8 content ------------------------------------------


def test_row10_binary_content_does_not_crash_and_has_no_findings():
    assert scan_blob("a.bin", OPAQUE) == []


def test_row10_adapted_binary_bytes_with_a_name_get_a_strings_pass():
    """Row 10's own bytes. The row said no content finding; addendum A5 changed that."""
    result = scan_blob("a.bin", b"\x00\x01zorblax")
    assert rules(result) == ["denylist"]
    assert result[0].path == "a.bin" and result[0].line >= 1


def test_row11_a_binary_files_path_is_still_scanned():
    result = scan_blob("zorblax.bin", OPAQUE)
    assert result == [finding("zorblax.bin", 0, 1, "denylist", "zorblax")]


def test_row11_adapted_path_finding_plus_the_strings_pass_finding():
    result = scan_blob("zorblax.bin", b"\x00\x01zorblax")
    assert rules(result) == ["denylist", "denylist"]
    assert [f.line for f in result][0] == 0 and [f.line for f in result][1] >= 1


def test_row12_utf16_with_a_bom_decodes_as_text():
    for data in (
        "Zorblax".encode("utf-16"),
        b"\xff\xfe" + "Zorblax".encode("utf-16-le"),
        b"\xfe\xff" + "Zorblax".encode("utf-16-be"),
    ):
        assert scan_blob("w.txt", data) == [finding("w.txt", 1, 1, "denylist", "zorblax")]


# ---- row 13: line endings -----------------------------------------------------------------


def test_row13_crlf_text_counts_lines_correctly():
    assert scan("ok\r\nZorblax\r\n") == [finding("f.txt", 2, 1, "denylist", "zorblax")]


# ---- rows 14-17: the CLI ---------------------------------------------------------------


def test_row14_no_key_and_require_key_is_a_configuration_error(tmp_path, gitenv):
    target = write(tmp_path, "a.txt", "nothing here\n")
    code, out, err = call_main(["--require-key", target], cwd=tmp_path)
    assert code == 2
    assert "privacy key missing" in err


def test_row15_no_key_still_runs_the_log_rules_and_says_the_denylist_was_skipped(
    tmp_path, gitenv
):
    target = write(tmp_path, "a.txt", loot_line() + "\n")
    code, out, err = call_main([target], cwd=tmp_path)
    assert code == 1
    assert "denylist check skipped (no key)" in out
    assert [f["rule"] for f in parse_output(out)] == ["log-loot"]


def test_row16_the_output_never_contains_the_matched_name(repo, keyfile):
    write(repo, "f.txt", "Zorblax\n")
    done = run_cli(["f.txt", "--key-file", keyfile], repo, process=True)  # a real child process
    assert done.returncode == 1
    combined = (done.stdout + done.stderr).lower()
    assert "zorblax" not in combined
    assert tag("zorblax") in done.stdout
    assert done.stdout.splitlines()[0] == f"f.txt:1:1: denylist [{tag('zorblax')}]"
    assert done.stdout.splitlines()[-1] == "privacy scan: 1 files, 1 findings"


def test_row17_explain_is_refused_when_ci_is_set(repo):
    write(repo, "f.txt", "nothing\n")
    code, out, err = call_main(["--explain", "f.txt"], cwd=repo, env={"CI": "true"}, tty=True)
    assert code == 2


# ---- row 18: staged versus working-tree content ---------------------------------------


def test_row18_the_staged_version_is_scanned_not_the_working_copy(repo, keyfile):
    write(repo, "f.txt", "Zorblax\n")
    git(repo, "add", "f.txt")
    write(repo, "f.txt", "clean\n")
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert [f["rule"] for f in parse_output(done.stdout)] == ["denylist"]

    # The reverse: a clean index passes even though the working copy now holds a name.
    git(repo, "add", "f.txt")
    write(repo, "f.txt", "Zorblax\n")
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 0, done.stdout + done.stderr


# ---- row 19: speed ---------------------------------------------------------------------------


def test_row19_two_hundred_thousand_clean_lines_scan_in_under_ten_seconds():
    text = "\n".join(
        f"line {n} of the clean text, with ordinary words and a few numbers {n * 7}"
        for n in range(200_000)
    )
    started = time.perf_counter()
    result = scan(text)
    elapsed = time.perf_counter() - started
    print(f"\nrow 19: 200,000 clean lines scanned in {elapsed:.2f} s")
    assert result == []
    assert elapsed < 10


# ---- row 20: reviewed per-line exceptions to the log-shape rules --------------------------


def _line_entry(path, rule, line):
    return (path, rule, hashlib.sha256(line.encode("utf-8")).hexdigest())


def test_row20_an_allowlisted_line_is_ignored_only_for_its_own_path_and_rule():
    line = loot_line()
    allow = {_line_entry("docs/x.md", "log-loot", line)}
    assert scan(line + "\n", path="docs/x.md", line_allow=allow) == []
    other = scan(line + "\n", path="docs/y.md", line_allow=allow)
    assert rules(other) == ["log-loot"]
    # The same line under another rule name does not borrow the exception.
    wrong_rule = {_line_entry("docs/x.md", "log-tell", line)}
    assert rules(scan(line + "\n", path="docs/x.md", line_allow=wrong_rule)) == ["log-loot"]


def test_row20_a_denylist_finding_is_never_silenced_by_a_line_exception():
    line = named_loot_line("Zorblax")
    allow = {_line_entry("docs/x.md", "log-loot", line)}
    result = scan(line + "\n", path="docs/x.md", line_allow=allow)
    assert rules(result) == ["denylist"]


def test_row20_the_cli_reads_privacy_allowlist_lines_txt(repo, keyfile):
    line = loot_line()
    privacy_files(repo, allow_lines=[_line_entry("docs/x.md", "log-loot", line)])
    write(repo, "docs/x.md", line + "\n")
    write(repo, "docs/y.md", line + "\n")
    ok = run_cli(["docs/x.md", "--key-file", keyfile], repo)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = run_cli(["docs/y.md", "--key-file", keyfile], repo)
    assert bad.returncode == 1
    assert [f["rule"] for f in parse_output(bad.stdout)] == ["log-loot"]


# ---- row 21: seen-flags is never committed ---------------------------------------------


def test_row21_a_staged_seen_flags_file_is_a_finding(repo, keyfile):
    write(repo, "derived/seen-flags.json", '["anything"]\n')
    git(repo, "add", "derived/seen-flags.json")
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert [f["rule"] for f in parse_output(done.stdout)] == ["seen-flags"]
    assert "1 findings" in done.stdout


# ---- rows 22-23: masking public game names ---------------------------------------------


MASK_DENY = DENY | {h("cazic")}


def test_row22_a_public_phrase_masks_the_name_inside_it_only():
    masker = S.PhraseMasker(["Cazic Thule"])
    assert scan("Drops from Cazic Thule", deny=MASK_DENY, phrases=masker) == []
    alone = scan("Cazic says hi", deny=MASK_DENY, phrases=masker)
    assert rules(alone) == ["denylist"] and alone[0].tag == tag("cazic")


def test_row22_phrases_may_be_given_as_a_plain_collection_too():
    assert scan("Drops from Cazic Thule", deny=MASK_DENY, phrases={"Cazic Thule"}) == []


def test_row23_masking_keeps_the_columns_of_what_follows():
    masker = S.PhraseMasker(["Cazic Thule"])
    result = scan("x Cazic Thule Zorblax", deny=MASK_DENY, phrases=masker)
    assert result == [finding("f.txt", 1, 15, "denylist", "zorblax")]


# ---- row 24: commit messages ---------------------------------------------------------------


def test_row24_commit_msg_scans_the_message_file(repo, keyfile):
    write(repo, "msg.txt", "fix Zorblax regression\n")
    done = run_cli(["--commit-msg", "msg.txt", "--require-key", "--key-file", keyfile], repo)
    assert done.returncode == 1
    found = parse_output(done.stdout)
    assert [(f["path"], f["rule"]) for f in found] == [("<commit-msg>", "denylist")]
    assert "zorblax" not in (done.stdout + done.stderr).lower()


# ---- row 25: the whole history --------------------------------------------------------------


def test_row25_history_finds_a_deleted_blob_a_message_and_a_branch_name(repo, keyfile):
    write(repo, "old.txt", "Zorblax\n")
    git(repo, "add", "old.txt")
    commit(repo, "add old file")
    git(repo, "rm", "-q", "old.txt")
    commit(repo, "remove old file")
    commit(repo, "Zorblax", "--allow-empty")
    git(repo, "branch", "zorblax-wip")

    done = run_cli(["--history", "--require-key", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    found = parse_output(done.stdout)
    assert [f["rule"] for f in found] == ["denylist"] * 3
    paths = sorted(f["path"] for f in found)
    assert any(p == "old.txt" for p in paths)
    assert any(p.startswith("<commit:") for p in paths)
    assert any(p.startswith("<ref") for p in paths)
    assert "zorblax" not in (done.stdout + done.stderr).lower()


# ---- row 26: author and committer identity -------------------------------------------------


def test_row26_a_foreign_identity_is_reported_by_commit_not_by_address(repo):
    write(repo, "a.txt", "clean\n")
    git(repo, "add", "a.txt")
    git(
        repo,
        "-c",
        "user.name=Someone",
        "-c",
        "user.email=someone@example.com",
        "commit",
        "-q",
        "-m",
        "work",
    )
    abbreviated = git(repo, "log", "-1", "--format=%h").stdout.decode().strip()
    done = run_cli(["--identity", "maintainers@trioforge.invalid"], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    found = parse_output(done.stdout)
    assert [f["rule"] for f in found] == ["identity"]
    assert abbreviated in found[0]["path"]
    assert "someone@example.com" not in (done.stdout + done.stderr).lower()


def test_row26_the_right_identity_passes(repo):
    git(repo, "config", "user.email", "maintainers@trioforge.invalid")
    write(repo, "a.txt", "clean\n")
    git(repo, "add", "a.txt")
    commit(repo, "work")
    done = run_cli(["--identity", "maintainers@trioforge.invalid"], repo)
    assert done.returncode == 0, done.stdout + done.stderr


# ---- row 27: the phrase masker is fast on a large catalog -------------------------------


def _random_word(rng):
    return "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(3, 9)))


def _phrases(rng, vocabulary, count=15_000):
    found = set()
    while len(found) < count:
        found.add(" ".join(rng.choice(vocabulary) for _ in range(rng.randint(2, 4))))
    return sorted(found)


def test_row27_fifteen_thousand_phrases_over_two_hundred_thousand_lines():
    rng = random.Random(27)
    vocabulary = [_random_word(rng) for _ in range(400)]  # few words, so first words repeat
    phrases = _phrases(rng, vocabulary)

    started = time.perf_counter()
    masker = S.PhraseMasker(phrases)
    built = time.perf_counter() - started

    lines = []
    for n in range(200_000):
        words = [rng.choice(vocabulary) for _ in range(8)]
        if n % 20 == 0:
            words[2:2] = phrases[n % len(phrases)].split()
        lines.append(" ".join(words))

    started = time.perf_counter()
    masked_lines = 0
    for line in lines:
        out = masker.mask(line)
        assert len(out) == len(line)
        masked_lines += out != line
    elapsed = time.perf_counter() - started
    print(
        f"\nrow 27: {len(phrases)} phrases built in {built:.2f} s; mask() over 200,000 lines "
        f"took {elapsed:.2f} s ({masked_lines} lines masked)"
    )
    assert built + elapsed < 20
    assert masked_lines >= 10_000  # every 20th line carries a phrase


def test_row27_scan_text_with_a_masker_over_two_hundred_thousand_lines():
    rng = random.Random(28)
    vocabulary = [_random_word(rng) for _ in range(400)]
    masker = S.PhraseMasker(_phrases(rng, vocabulary))
    # Many lines carry a denylisted word, so the masker really runs on them.
    deny = {h(vocabulary[0]), h(vocabulary[1]), h(vocabulary[2])}
    text = "\n".join(
        " ".join(rng.choice(vocabulary) for _ in range(8)) for _ in range(200_000)
    )
    started = time.perf_counter()
    result = scan(text, deny=deny, phrases=masker)
    elapsed = time.perf_counter() - started
    print(f"\nrow 27b: scan_text with a 15,000-phrase masker: {len(result)} findings, {elapsed:.2f} s")
    assert elapsed < 20
    assert result  # unmasked occurrences exist
