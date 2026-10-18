"""Acceptance tests of the scanner's second set of cases, A1-A23 (A17 and A18 are in test_privacy_hooks).

Inputs that hide a name by encoding it are written with escapes, so this file stays ASCII.

Cases worded differently from the scanner's rules, and what these tests do about it:

* A15 lists the tell example without a quote after the comma, but the scanner's ``log-tell``
  pattern requires one (``, '``), as every real log line has. The test uses the quoted form.
* A2 lists the base64 form of the invented name, which is 12 characters long. The addendum
  says runs of 16-4096 characters; the scanner accepts runs of 8-4096 so that this case
  passes (a short run must still decode to at least 90% printable ASCII).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from test_privacy_helpers import (  # noqa: F401  (fixtures are used by name)
    CI_VARS,
    KEY,
    KEY_HEX,
    OTHER_KEY,
    PIPELINE,
    call_main,
    chdir,
    cli_env,
    commit,
    git,
    gitenv,
    h,
    keyfile,
    parse_output,
    privacy_files,
    repo,
    rules,
    run_cli,
    scan,
    scan_blob,
    tag,
    write,
    write_key_file,
)
from trioforge.privacy import scan as S


def finding(path, line, col, rule, token=None):
    return S.Finding(path, line, col, rule, tag(token) if token else "-")


ZORBLAX = [finding("f.txt", 1, 1, "denylist", "zorblax")]


# ---- A1: characters that make a name look different ------------------------------------

A1_VARIANTS = {
    "zero-width space": "Zor\u200bblax",
    "soft hyphen": "Zor\u00adblax",
    "combining acute accent": "Zorbla\u0301x",
    "fullwidth letters": "\uff3a\uff4f\uff52\uff42\uff4c\uff41\uff58",
    "cyrillic o": "Z\u043erblax",
}


@pytest.mark.parametrize("text", list(A1_VARIANTS.values()), ids=list(A1_VARIANTS))
def test_a1_unicode_disguises_are_folded_before_matching(text):
    assert scan(text) == ZORBLAX


# ---- A2: encoded forms --------------------------------------------------------------------

A2_VARIANTS = {
    "decimal entity": ("f.txt", "Zor&#98;lax"),
    "hex entity": ("f.txt", "Zor&#x62;lax"),
    "percent encoding": ("f.txt", "Zor%62lax"),
    "json unicode escape": ("n.ipynb", "Zor\\u0062lax"),
    "js hex escape": ("f.txt", "Zor\\x62lax"),
    "base64": ("f.txt", "Wm9yYmxheA=="),
}


@pytest.mark.parametrize("path,text", list(A2_VARIANTS.values()), ids=list(A2_VARIANTS))
def test_a2_encoded_names_are_decoded_and_found_once(path, text):
    assert scan(text, path=path) == [finding(path, 1, 1, "denylist", "zorblax")]


def test_a2_a_name_that_is_visible_in_both_the_raw_and_the_decoded_text_is_reported_once():
    result = scan("Zorblax&amp;Quimmet")
    assert [(f.col, f.tag) for f in result] == [(1, tag("zorblax")), (13, tag("quimmet"))]


# ---- A3: wrapped and emphasised names -----------------------------------------------------


def test_a3_a_hyphenated_line_wrap_is_joined():
    assert scan("Zor-\nblax crash") == ZORBLAX
    assert scan("Zor-\r\nblax crash") == ZORBLAX


def test_a3_markdown_emphasis_between_letters_is_removed():
    assert scan("**Zor**blax") == [finding("f.txt", 1, 3, "denylist", "zorblax")]


# ---- A4 and A5: UTF-16 without a BOM, and binary files with text in them ---------------


def test_a4_utf16_without_a_bom_is_detected_and_decoded():
    for encoding in ("utf-16-le", "utf-16-be"):
        data = "hello Zorblax\n".encode(encoding)
        assert scan_blob("w.txt", data) == [finding("w.txt", 1, 7, "denylist", "zorblax")], encoding


def test_a5_text_after_many_nul_bytes_is_found_by_the_strings_pass():
    data = b"\x00" * 8192 + b"\nZorblax tells you, hi\n"
    result = scan_blob("blob.bin", data)
    assert rules(result) == ["denylist"]
    assert (result[0].line, result[0].col) == (2, 1)


def test_a5_printable_runs_shorter_than_four_characters_are_not_extracted():
    assert scan_blob("blob.bin", b"\x00\x01zor\x00\x02") == []


# ---- A6: archives, LFS pointers and submodules ------------------------------------------

LFS_POINTER = (
    "version https://git-lfs.github.com/spec/v1\n"
    "oid sha256:" + "ab" * 32 + "\n"
    "size 12345\n"
)


@pytest.mark.parametrize("path", ["logs.zip", "x.txt.gz", "a.tgz", "b.tar", "c.7z", "d.rar",
                                   "e.bz2", "f.xz", "g.zst", "H.ZIP"])
def test_a6_archives_are_refused_by_extension(path):
    assert scan_blob(path, b"anything at all") == [finding(path, 0, 0, "archive")]


@pytest.mark.parametrize(
    "data",
    [
        b"PK\x03\x04" + b"\x00" * 30,
        b"\x1f\x8b\x08\x00" + b"\x00" * 30,
        b"BZh9" + b"\x31\x41\x59\x26\x53\x59" + b"\x00" * 30,
        b"\xfd7zXZ\x00" + b"\x00" * 30,
        b"\x28\xb5\x2f\xfd" + b"\x00" * 30,
        b"7z\xbc\xaf\x27\x1c" + b"\x00" * 30,
        b"Rar!\x1a\x07\x00" + b"\x00" * 30,
        b"\x00" * 257 + b"ustar" + b"\x00" * 30,
    ],
    ids=["zip", "gzip", "bzip2", "xz", "zstd", "7z", "rar", "tar"],
)
def test_a6_archives_are_refused_by_magic_bytes_whatever_the_name(data):
    assert scan_blob("data.bin", data) == [finding("data.bin", 0, 0, "archive")]


def test_a6_text_that_only_starts_like_a_magic_number_is_not_an_archive():
    assert scan_blob("note.txt", b"PKnote about packing\n") == []
    assert scan_blob("note.txt", b"BZhello there\n") == []


def test_a6_an_lfs_pointer_is_refused():
    assert scan_blob("model.bin", LFS_POINTER.encode()) == [finding("model.bin", 0, 0, "lfs")]


def test_a6_staged_archives_lfs_pointers_and_gitlinks_are_refused(repo, keyfile):
    write(repo, "logs.zip", b"PK\x03\x04 not really a zip")
    write(repo, "x.txt.gz", b"\x1f\x8b\x08 not really gzip")
    write(repo, "data/model.bin", LFS_POINTER)
    git(repo, "add", "logs.zip", "x.txt.gz", "data/model.bin")
    git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        "160000,1111111111111111111111111111111111111111,vendor/sub",
    )
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    found = {(f["path"], f["rule"]) for f in parse_output(done.stdout)}
    assert found == {
        ("logs.zip", "archive"),
        ("x.txt.gz", "archive"),
        ("data/model.bin", "lfs"),
        ("vendor/sub", "submodule"),
    }


def test_a6_a_staged_symlink_is_scanned_as_its_target_text_and_never_followed(repo, keyfile):
    blob = git(repo, "hash-object", "-w", "--stdin", input=b"zorblax/target").stdout.decode().strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},docs/link")
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    found = parse_output(done.stdout)
    assert [(f["path"], f["rule"]) for f in found] == [("docs/link", "denylist")]
    assert "zorblax" not in (done.stdout + done.stderr).lower()


# ---- A7-A9: the key and the denylist ---------------------------------------------------------


def _clean_run(repo, env, *args, **kwargs):
    write(repo, "ok.txt", "nothing to see here\n")
    return call_main(["ok.txt", *args], cwd=repo, env=env, **kwargs)


def test_a7_the_key_may_carry_whitespace_and_a_line_ending(repo):
    code, out, err = _clean_run(repo, {"TRIOFORGE_PRIVACY_KEY": " " + KEY_HEX + "\r\n"})
    assert code == 0, out + err


def test_a7_a_key_file_may_start_with_a_utf8_bom(repo, tmp_path):
    key_file = write_key_file(tmp_path / "bomkey", b"\xef\xbb\xbf" + KEY_HEX.encode() + b"\r\n")
    code, out, err = _clean_run(repo, {}, "--key-file", key_file)
    assert code == 0, out + err


@pytest.mark.parametrize(
    "bad",
    ["", "   ", KEY_HEX[:-1], KEY_HEX + "0", "zz" * 32, "0x" + KEY_HEX[2:], KEY_HEX[:32] + " " + KEY_HEX[32:]],
    ids=["empty", "blank", "63 hex", "65 hex", "not hex", "prefix", "inner space"],
)
def test_a7_an_invalid_key_is_a_configuration_error_even_without_require_key(repo, bad):
    code, out, err = _clean_run(repo, {"TRIOFORGE_PRIVACY_KEY": bad})
    assert code == 2
    assert "privacy key invalid" in err
    assert bad.strip() == "" or bad.strip() not in err  # the key text is never echoed


def test_a7_an_invalid_key_file_is_a_configuration_error(repo, tmp_path):
    key_file = write_key_file(tmp_path / "badkey", "not a key\n")
    code, out, err = _clean_run(repo, {}, "--key-file", key_file)
    assert code == 2 and "privacy key invalid" in err


def test_a7_a_key_file_beats_the_environment_variable(repo, tmp_path):
    good = write_key_file(tmp_path / "goodkey", KEY_HEX)
    code, out, err = _clean_run(repo, {"TRIOFORGE_PRIVACY_KEY": "zz" * 32}, "--key-file", good)
    assert code == 0, out + err


def test_a7_the_default_key_file_is_used_when_nothing_else_is_given(repo, tmp_path):
    default = write_key_file(tmp_path / "default", KEY_HEX)
    code, out, err = _clean_run(repo, {}, default_key_file=str(default))
    assert code == 0, out + err
    assert "denylist check skipped" not in out


def test_a8_a_key_that_does_not_match_the_denylist_header_is_refused(repo, keyfile):
    privacy_files(repo, key=OTHER_KEY)  # the header carries the other key's check value
    write(repo, "ok.txt", "nothing\n")
    done = run_cli(["ok.txt", "--key-file", keyfile], repo)
    assert done.returncode == 2
    assert "does not match" in done.stderr


def test_a8_a_matching_header_passes_and_a_missing_header_is_not_an_error(repo, keyfile):
    write(repo, "ok.txt", "nothing\n")
    assert run_cli(["ok.txt", "--key-file", keyfile], repo).returncode == 0
    privacy_files(repo, with_key_check=False)
    assert run_cli(["ok.txt", "--key-file", keyfile], repo).returncode == 0


def test_a9_an_empty_denylist_fails_when_the_key_is_required(repo, keyfile):
    privacy_files(repo, deny=(), with_key_check=False)
    write(repo, "ok.txt", "nothing\n")
    done = run_cli(["ok.txt", "--require-key", "--key-file", keyfile], repo)
    assert done.returncode == 2
    assert "denylist empty" in done.stderr
    relaxed = run_cli(["ok.txt", "--key-file", keyfile], repo)
    assert relaxed.returncode == 0
    assert "denylist check skipped" in relaxed.stdout


# ---- A10-A12: git edge cases ---------------------------------------------------------------


def test_a10_a_staged_deletion_does_not_crash_and_is_not_a_finding(repo, keyfile):
    write(repo, "notes/zorblax.md", "clean\n")
    git(repo, "add", "notes/zorblax.md")
    commit(repo, "add note")
    git(repo, "rm", "-q", "notes/zorblax.md")
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "0 files, 0 findings" in done.stdout


def test_a10_the_deleted_path_is_still_caught_by_the_history_scan(repo, keyfile):
    write(repo, "notes/zorblax.md", "clean\n")
    git(repo, "add", "notes/zorblax.md")
    commit(repo, "add note")
    git(repo, "rm", "-q", "notes/zorblax.md")
    commit(repo, "drop note")
    done = run_cli(["--history", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert [f["rule"] for f in parse_output(done.stdout)] == ["denylist"]
    assert "zorblax" not in (done.stdout + done.stderr).lower()


def test_a11_unmerged_index_entries_stop_the_staged_scan(repo, keyfile):
    blobs = [
        git(repo, "hash-object", "-w", "--stdin", input=text).stdout.decode().strip()
        for text in (b"base\n", b"ours\n", b"theirs\n")
    ]
    entries = "".join(f"100644 {blob} {stage}\tconflict.txt\n" for stage, blob in enumerate(blobs, 1))
    git(repo, "update-index", "--index-info", input=entries.encode())
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 2
    assert "resolve merge conflicts first" in done.stderr


def test_a12_without_git_on_the_path_the_scanner_stops(repo, keyfile, tmp_path):
    empty = tmp_path / "no-git-here"
    empty.mkdir()
    env = {
        "PATH": str(empty),
        "PYTHONPATH": str(PIPELINE),
        "PYTHONUTF8": "1",
        "SystemRoot": os.environ.get("SystemRoot", ""),
    }
    done = run_cli(["--staged", "--key-file", keyfile], repo, env=env)
    assert done.returncode == 2, done.stdout + done.stderr
    assert "git not found" in done.stderr


def test_a12_an_empty_repository_works_for_all_and_history(repo, keyfile):
    for mode in ("--all", "--history", "--staged"):
        done = run_cli([mode, "--key-file", keyfile], repo)
        assert done.returncode == 0, (mode, done.stdout, done.stderr)


def test_paths_containing_a_colon_work_with_staging(repo, keyfile):
    # Windows forbids ':' in file names, so create the index entry directly (and tell git for
    # Windows not to refuse the name). The stage-qualified syntax ':1:x' would misread this path.
    git(repo, "config", "core.protectNTFS", "false")
    blob = git(repo, "hash-object", "-w", "--stdin", input=b"Zorblax\n").stdout.decode().strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},notes/1:2.txt")
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert [(f["path"], f["rule"]) for f in parse_output(done.stdout)] == [
        ("notes/1:2.txt", "denylist")
    ]


# ---- A13: output safety --------------------------------------------------------------------


def test_a13_a_private_name_in_a_printed_path_is_replaced(repo, keyfile):
    write(repo, "Zorblax/notes.md", "clean content\n")
    done = run_cli(["Zorblax/notes.md", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert "[private:" in done.stdout
    assert "zorblax" not in (done.stdout + done.stderr).lower()
    found = parse_output(done.stdout)
    assert found[0]["path"] == f"[private:{tag('zorblax')}]/notes.md"
    assert found[0]["line"] == "0"


# ---- A14: --explain guard ----------------------------------------------------------------------


@pytest.mark.parametrize("variable", CI_VARS)
@pytest.mark.parametrize("value", ["true", ""])
def test_a14_explain_is_refused_when_any_ci_variable_exists_even_if_empty(repo, variable, value):
    write(repo, "f.txt", "nothing\n")
    code, out, err = call_main(["--explain", "f.txt"], cwd=repo, env={variable: value}, tty=True)
    assert code == 2
    assert "explain" in err


def test_a14_explain_is_refused_when_stdout_is_not_a_terminal(repo):
    write(repo, "f.txt", "nothing\n")
    code, out, err = call_main(["--explain", "f.txt"], cwd=repo, env={}, tty=False)
    assert code == 2


@pytest.mark.parametrize(
    "extra", [{"GITHUB_ACTIONS": "true"}, {"TF_BUILD": ""}, {}], ids=["github", "tf_build", "piped"]
)
def test_a14_explain_is_refused_in_a_child_process(repo, keyfile, extra):
    write(repo, "f.txt", "nothing\n")
    done = run_cli(["--explain", "f.txt", "--key-file", keyfile], repo, env=cli_env(extra))
    assert done.returncode == 2, done.stdout + done.stderr


def test_a14_explain_prints_the_token_on_a_terminal_without_ci(repo, keyfile):
    write(repo, "f.txt", "hello Zorblax\n")
    code, out, err = call_main(
        ["--explain", "f.txt", "--key-file", keyfile], cwd=repo, env={}, tty=True
    )
    assert code == 1
    assert "zorblax" in out.lower()


# ---- A15: the extra log-shape rules ---------------------------------------------------------


def test_a15_out_of_character_told_and_interior_capital_names():
    assert rules(scan("Vexandra says " + "out of character, wts")) == ["log-ooc"]
    assert rules(scan("You told " + "Vexandra, hi")) == ["log-told"]
    assert rules(scan("McHale" + " tells you, 'hi'")) == ["log-tell"]


def test_a15_interior_capitals_are_accepted_by_the_other_name_rules_too():
    assert rules(scan("McHale" + " says, 'hi'")) == ["log-say"]
    assert rules(scan("McHale" + " has joined the group.")) == ["log-group"]
    assert rules(scan("[50 Paladin] " + "McHale (Ogre)")) == ["log-who"]


# ---- A16: line endings in the line exceptions --------------------------------------------


def test_a16_a_line_exception_made_from_an_lf_file_matches_the_crlf_checkout():
    import hashlib

    line = "You have " + "looted a Rusty Dagger."
    entry = ("docs/x.md", "log-loot", hashlib.sha256(line.encode()).hexdigest())
    lf = line + "\nsecond line\n"
    crlf = line + "\r\nsecond line\r\n"
    assert scan(lf, path="docs/x.md", line_allow={entry}) == []
    assert scan(crlf, path="docs/x.md", line_allow={entry}) == []
    cr_only = line + "\rsecond line\r"
    assert scan(cr_only, path="docs/x.md", line_allow={entry}) == []


# ---- A19: seen-flags by basename -------------------------------------------------------------


def test_a19_seen_flags_matches_any_path_with_that_basename(repo, keyfile):
    write(repo, "tests/fixtures/derived/seen-flags.json", "{}\n")
    git(repo, "add", "tests/fixtures/derived/seen-flags.json")
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert [(f["path"], f["rule"]) for f in parse_output(done.stdout)] == [
        ("tests/fixtures/derived/seen-flags.json", "seen-flags")
    ]


def test_a19_a_file_that_only_looks_similar_is_not_flagged():
    assert scan_blob("seen-flags.json.md", b"x") == []
    assert scan_blob("my-seen-flags.json", b"x") == []


# ---- A20-A22: line endings, BOM, empty file ----------------------------------------------------


def test_a20_classic_mac_line_endings_count_lines():
    assert scan_blob("f.txt", b"ok\rZorblax") == [finding("f.txt", 2, 1, "denylist", "zorblax")]
    assert scan("ok\rZorblax") == [finding("f.txt", 2, 1, "denylist", "zorblax")]


def test_a21_a_utf8_bom_does_not_shift_the_first_column():
    assert scan_blob("f.txt", b"\xef\xbb\xbfZorblax") == ZORBLAX
    assert scan("\ufeffZorblax") == ZORBLAX


def test_a22_an_empty_file_still_has_its_path_scanned():
    assert scan_blob("notes/Zorblax.md", b"") == [finding("notes/Zorblax.md", 0, 7, "denylist", "zorblax")]


# ---- A23: a 20 MB file ----------------------------------------------------------------------

CHILD = r'''
import json, sys, time

sys.path.insert(0, sys.argv[1])
from trioforge.privacy import scan

started = time.perf_counter()
code = scan.main([sys.argv[2], "--key-file", sys.argv[3]])
elapsed = time.perf_counter() - started


def peak_bytes():
    if sys.platform.startswith("linux"):
        # Not getrusage here: Linux hands the peak of the process that started this one down through fork and exec, so a child of a big test run reads the run's
        # memory and not its own. VmHWM is the peak of the program that is running now.
        try:
            with open("/proc/self/status", encoding="ascii", errors="replace") as status:
                for line in status:
                    if line.startswith("VmHWM:"):
                        return int(line.split()[1]) * 1024
        except OSError:
            pass
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value * 1024 if sys.platform.startswith("linux") else value
    except ImportError:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return counters.PeakWorkingSetSize


print(json.dumps({"code": code, "elapsed": elapsed, "peak": peak_bytes()}), file=sys.stderr)
'''


def _write_big_text(path, size=20 * 1024 * 1024):
    template = "lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor {n} labore\n"
    written = 0
    number = 0
    with open(path, "wb") as handle:
        while written < size:
            block = "".join(template.format(n=number + i) for i in range(5000)).encode()
            handle.write(block)
            written += len(block)
            number += 5000
    return written


def test_a23_a_twenty_megabyte_text_file_scans_quickly_in_little_memory(repo, keyfile, tmp_path):
    big = repo / "big.txt"  # a path given to the scanner must lie inside the repository
    size = _write_big_text(big)
    assert size >= 20 * 1024 * 1024
    done = subprocess.run(
        [sys.executable, "-c", CHILD, str(PIPELINE), str(big), str(keyfile)],
        cwd=repo,
        env=cli_env(),
        capture_output=True,
        text=True,
    )
    report = json.loads(done.stderr.strip().splitlines()[-1])
    print(
        f"\nA23: {size / 2**20:.1f} MiB scanned in {report['elapsed']:.2f} s, "
        f"peak memory {report['peak'] / 2**20:.0f} MiB"
    )
    assert report["code"] == 0, done.stdout + done.stderr
    assert report["elapsed"] < 30
    assert report["peak"] < 200 * 2**20


def test_a23_one_enormous_line_is_also_streamed(repo, keyfile, tmp_path):
    big = repo / "oneline.txt"  # a path given to the scanner must lie inside the repository
    with open(big, "wb") as handle:
        for _ in range(20):
            handle.write(b"word " * (200 * 1024))  # about 1 MB per write, no newline at all
        handle.write(b"Zorblax\n")
    done = subprocess.run(
        [sys.executable, "-c", CHILD, str(PIPELINE), str(big), str(keyfile)],
        cwd=repo,
        env=cli_env(),
        capture_output=True,
        text=True,
    )
    report = json.loads(done.stderr.strip().splitlines()[-1])
    print(f"\nA23b: one 20 MB line in {report['elapsed']:.2f} s, peak {report['peak'] / 2**20:.0f} MiB")
    assert report["code"] == 1  # the name at the very end is found
    assert report["elapsed"] < 30
    assert report["peak"] < 200 * 2**20


def test_a23_the_peak_read_is_the_scan_childs_own_and_not_the_one_of_the_run_that_started_it(repo, keyfile):
    """Linux hands the peak memory of a process down to the program it starts (through fork and exec), so a child that asks getrusage reads the larger of its own peak and its
    parent's. A23 runs inside a test run with thousands of tests loaded, and the first CI run on Linux read 545 MiB for a scan that peaks near 45 MiB. Here this process takes
    300 MiB and gives it back, then starts the same child on a tiny file: the reading must still be the child's own."""
    tiny = repo / "tiny.txt"  # a path given to the scanner must lie inside the repository
    tiny.write_text("a few plain words\n", encoding="utf-8")
    ballast = bytearray(b"x") * (300 * 2**20)  # (every page is written, so the memory is really taken)
    del ballast
    done = subprocess.run(
        [sys.executable, "-c", CHILD, str(PIPELINE), str(tiny), str(keyfile)],
        cwd=repo,
        env=cli_env(),
        capture_output=True,
        text=True,
    )
    report = json.loads(done.stderr.strip().splitlines()[-1])
    assert report["code"] == 0, done.stdout + done.stderr
    assert report["peak"] < 150 * 2**20, f"the child read {report['peak'] / 2**20:.0f} MiB"


def test_a16_through_the_command_line_a_crlf_checkout_keeps_its_line_exception(repo, keyfile):
    import hashlib

    line = "You have " + "looted a Rusty Dagger."
    entry = ("docs/x.md", "log-loot", hashlib.sha256(line.encode()).hexdigest())
    privacy_files(repo, allow_lines=[entry])
    (repo / "docs").mkdir()
    (repo / "docs" / "x.md").write_bytes((line + "\r\nmore text\r\n").encode())
    done = run_cli(["docs/x.md", "--key-file", keyfile], repo)
    assert done.returncode == 0, done.stdout + done.stderr
