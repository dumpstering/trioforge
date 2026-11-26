"""Tests for the ways the scanner reads a line or a file, beyond the first rows of tests: the
tokenizer, hash blanking, nested encodings, base64, numeric character references, text that
hides inside binary or mislabelled files, masking of public names, and the map from a folded view
back to the original text.

Test data is invented. Inputs that hide a name are written with escapes, so this file stays ASCII
apart from escapes.
"""

from __future__ import annotations

import base64
import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from test_privacy_helpers import (  # noqa: F401  (fixtures are used by name)
    DENY,
    KEY,
    h,
    keyfile,
    gitenv,
    parse_output,
    privacy_files,
    repo,
    rules,
    run_cli,
    scan,
    scan_blob,
    tag,
    windows_profile,
    write,
)
from trioforge.privacy import scan as S
from trioforge.privacy import textnorm


def finding(path, line, col, rule, token=None):
    return S.Finding(path, line, col, rule, tag(token) if token else "-")


ZORBLAX_AT_1 = [finding("f.txt", 1, 1, "denylist", "zorblax")]
CJK = "\u4e2d\u6587\u5b57"  # three ideographs: a token of its own
CYRILLIC = "\u043f\u0440\u0438\u0432\u0435\u0442"


# ---- the tokenizer: runs of capitals, and changes of script ----------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ZORBLAXgear", [(1, 1, "zorblax"), (1, 8, "gear")]),
        ("ZOrblax", [(1, 3, "rblax")]),  # "ZO" is too short to be a token
        ("Zorblax", [(1, 1, "zorblax")]),
        ("ZorblaxBis", [(1, 1, "zorblax"), (1, 8, "bis")]),
        ("ZORBLAX", [(1, 1, "zorblax")]),
        ("Zorblax" + CJK, [(1, 1, "zorblax"), (1, 8, CJK)]),
        (CJK + "Zorblax", [(1, 1, CJK), (1, 4, "zorblax")]),
        ("Zorblax" + CYRILLIC, [(1, 1, "zorblax"), (1, 8, CYRILLIC)]),
        (CYRILLIC + "x2", [(1, 1, CYRILLIC)]),
        ("caf\u00e9bar", [(1, 1, "caf\u00e9bar")]),  # accents do not change the script
    ],
)
def test_tokens_split_a_run_of_capitals_from_the_lower_case_after_it_and_at_script_changes(
    text, expected
):
    assert list(S.tokens(text)) == expected


def test_a_name_in_capitals_joined_to_a_lower_case_word_is_found():
    assert scan("ZORBLAXgear") == ZORBLAX_AT_1


def test_a_name_next_to_text_in_another_script_is_found():
    assert scan("Zorblax" + CJK) == ZORBLAX_AT_1
    assert scan(CJK + "Zorblax") == [finding("f.txt", 1, 4, "denylist", "zorblax")]
    assert scan("Zorblax" + CYRILLIC) == ZORBLAX_AT_1
    assert scan(CYRILLIC + "Zorblax") == [finding("f.txt", 1, 7, "denylist", "zorblax")]


@pytest.mark.parametrize("text", ["ZOrblax", "ZORblax", "ZORBLAXBis"])
def test_other_capital_runs_are_still_checked_as_a_whole_and_in_both_splits(text):
    # "ZOrblax" and "ZORblax" were found as one token before capital runs were split off;
    # "ZORBLAXBis" is capitals followed by a capitalised word.
    assert scan(text) == ZORBLAX_AT_1


def test_two_names_joined_in_capitals_and_a_capitalised_word_are_both_found():
    deny = DENY | {h("vexandra")}
    result = scan("ZORBLAXVexandra", deny=deny)
    assert [(f.col, f.tag) for f in result] == [(1, tag("zorblax")), (8, tag("vexandra"))]


@pytest.mark.parametrize("text", ["zorblaxian", "ZORBLAXIAN", "Zorb", "ZorblaxianBis"])
def test_longer_words_are_still_not_names(text):
    assert scan(text) == []


# ---- hashes are not words, but mixed case is not a hash ----------------------------------------


def test_a_run_of_hex_digits_in_one_case_is_a_hash_and_mixed_case_is_not():
    deny = {h("fade")}
    assert scan("0123456789abcdeffade", deny=deny) == []
    assert scan("0123456789ABCDEFFADE", deny=deny) == []
    mixed = scan("0123456789abcdefFade", deny=deny)
    assert [(f.rule, f.col, f.tag) for f in mixed] == [("denylist", 17, tag("fade"))]
    assert list(S.tokens("0123456789abcdefFade"))[-1] == (1, 17, "fade")


# ---- encodings that only work after a fold, and encodings inside encodings -----------------------


def test_a_fullwidth_percent_sign_hides_an_escape_until_it_is_folded():
    assert scan("Zor" + "\uff05" + "62lax") == ZORBLAX_AT_1


def test_a_zero_width_joiner_inside_an_escape_is_dropped_before_the_escape_is_read():
    assert scan("Zor%" + "\u200d" + "62lax") == ZORBLAX_AT_1
    assert scan("Zor%" + "\\u200d" + "62lax") == ZORBLAX_AT_1  # the same joiner, as a JSON escape


@pytest.mark.parametrize("depth", [3, 4, 5, 6])
def test_nested_percent_encoding_is_followed_for_six_rounds(depth):
    encoded = "%" + "25" * (depth - 1) + "62"
    assert scan("Zor" + encoded + "lax") == ZORBLAX_AT_1


def test_encodings_of_different_kinds_can_be_nested():
    assert scan("Zor%26%2398%3Blax") == ZORBLAX_AT_1
    assert scan("Zor&amp;amp;#98;lax") == ZORBLAX_AT_1


@pytest.mark.parametrize(
    "text",
    ["&#90orblax", "&#x5Aorblax", "Zor&#98lax", "Zorbla&#120", "Zor&#98&#108ax"],
)
def test_numeric_character_references_without_a_semicolon_are_decoded(text):
    assert scan(text) == ZORBLAX_AT_1


# ---- base64 ------------------------------------------------------------------------------------


def test_base64_without_any_capital_letter_is_decoded_too():
    name = "joknorvik"  # chosen so that its base64 has no capital letter
    encoded = base64.b64encode(name.encode()).decode()
    assert encoded == encoded.lower()
    result = scan("data: " + encoded, deny={h(name)})
    assert [(f.rule, f.col) for f in result] == [("denylist", 7)]


@pytest.mark.parametrize("position", [3030, 3066, 3067, 3068, 6090, 6141])
def test_a_name_across_a_seam_of_a_long_base64_run_is_found_once(position):
    payload = b"." * position + b"Zorblax" + b"." * 300
    run = base64.b64encode(payload).decode()
    assert len(run) > 4096
    assert scan("data: " + run) == [finding("f.txt", 1, 7, "denylist", "zorblax")]


def test_a_very_long_base64_run_of_binary_data_is_still_left_alone():
    rng = random.Random(7)
    noise = base64.b64encode(bytes(rng.randrange(256) for _ in range(9000))).decode()
    assert len(noise) > 4096 * 2
    assert scan("blob: " + noise) == []


# ---- text that hides in binary or mislabelled files ---------------------------------------------

LOG_AND_NAME = ("--" + "Zorblax" + " has " + "looted a Bone Chip.--").encode()


@pytest.mark.parametrize(
    "bom",
    [b"\xff\xfe", b"\xfe\xff", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"],
    ids=["utf-16 le", "utf-16 be", "utf-32 le", "utf-32 be"],
)
def test_a_byte_order_mark_over_plain_ascii_text_still_gets_the_raw_strings_pass(bom):
    result = scan_blob("w.txt", bom + LOG_AND_NAME)
    assert sorted(set(rules(result))) == ["denylist", "log-loot"]
    assert {f.line for f in result} == {1}


def _wide(text, little):
    return text.encode("utf-16-le" if little else "utf-16-be")


# Bytes that make a file binary and keep what follows at an even offset.
HEAD = bytes(range(8))
TAIL = b"\xff\x00\x01\x02\x03\x04"


@pytest.mark.parametrize("little", [True, False], ids=["le", "be"])
def test_utf16_text_inside_a_binary_file_is_found(little):
    data = HEAD + _wide("hello Zorblax now", little) + TAIL
    result = scan_blob("blob.bin", data)
    assert [(f.rule, f.line, f.tag) for f in result] == [("denylist", 1, tag("zorblax"))]


@pytest.mark.parametrize("little", [True, False], ids=["le", "be"])
def test_utf16_runs_shorter_than_four_characters_are_not_extracted(little):
    data = HEAD + _wide("Zor", little) + TAIL
    assert scan_blob("blob.bin", data) == []


@pytest.mark.parametrize(
    "bom,little",
    [(b"\xff\xfe", False), (b"\xfe\xff", True)],
    ids=["bom says le, text is be", "bom says be, text is le"],
)
def test_a_byte_order_mark_that_names_the_wrong_order_does_not_hide_the_text(bom, little):
    result = scan_blob("w.txt", bom + _wide("hello Zorblax now", little))
    assert [(f.rule, f.line, f.tag) for f in result] == [("denylist", 1, tag("zorblax"))]


@pytest.mark.parametrize(
    "data",
    [
        _wide("x " + "Zorblax", True),
        _wide("x " + "Zorblax", False),
        "x Zorblax".encode("utf-16"),
        b"\xfe\xff" + _wide("x " + "Zorblax", False),
    ],
    ids=["le", "be", "le with bom", "be with bom"],
)
def test_real_utf16_text_is_reported_once_not_again_for_the_other_byte_order(data):
    assert scan_blob("w.txt", data) == [finding("w.txt", 1, 3, "denylist", "zorblax")]


def test_utf16_text_with_crlf_lines_reports_the_same_position_from_every_pass():
    data = "line one\r\nsecond Zorblax\r\n".encode("utf-16")
    assert scan_blob("w.txt", data) == [finding("w.txt", 2, 8, "denylist", "zorblax")]


# ---- UTF-16 that follows UTF-8 (a file appended to by a tool that writes the other encoding) ------------------

LONG_ASCII = b"plain text, no NUL byte in it\n" * 300  # more than the 8 KiB that decide the encoding of a file


@pytest.mark.parametrize("little", [True, False], ids=["le", "be"])
def test_utf16_text_appended_to_a_long_utf8_file_is_found(little):
    assert len(LONG_ASCII) > S.SAMPLE_SIZE
    result = scan_blob("log.txt", LONG_ASCII + _wide("a note about Zorblax here", little))
    assert [(f.rule, f.tag) for f in result] == [("denylist", tag("zorblax"))]


def test_utf16_text_appended_to_a_long_utf8_file_is_found_at_its_line_and_column():
    result = scan_blob("log.txt", LONG_ASCII + _wide("first\nsee Zorblax here", True))
    line = LONG_ASCII.count(b"\n") + 2
    assert [(f.line, f.rule) for f in result] == [(line, "denylist")]
    assert result[0].col == 10  # (the column in the line as it is: a little-endian line feed leaves a NUL at the start of the next line, and the NULs between the characters count)


@pytest.mark.parametrize("little", [True, False], ids=["le", "be"])
def test_utf16_text_after_a_utf8_byte_order_mark_is_found(little):
    result = scan_blob("w.txt", b"\xef\xbb\xbf" + _wide("hello Zorblax now", little))
    assert [(f.rule, f.tag) for f in result] == [("denylist", tag("zorblax"))]


def test_utf32_text_appended_to_a_long_utf8_file_is_found():
    result = scan_blob("log.txt", LONG_ASCII + "see Zorblax here".encode("utf-32-le"))
    assert [(f.rule, f.tag) for f in result] == [("denylist", tag("zorblax"))]


def test_a_local_path_in_utf16_after_utf8_text_is_found_without_a_key():
    path = windows_profile("Vexandra") + "\\notes"
    result = scan_blob("log.txt", LONG_ASCII + _wide("at " + path + " ok", True), key=None)
    assert rules(result) == ["local-path"]


def test_utf8_text_with_a_stray_nul_byte_is_still_read_as_it_is():
    assert [(f.rule, f.line, f.col) for f in scan_blob("w.txt", b"a\x00b Zorblax c\n")] == [("denylist", 1, 5)]
    assert scan_blob("w.txt", b"fine\x00text\nZ\x00o\x00\n") == []  # (a name needs all its letters)


# ---- UTF-16 at an odd offset of a binary file ----------------------------------------------------------------


@pytest.mark.parametrize("little", [True, False], ids=["le", "be"])
def test_utf16_text_at_an_odd_offset_of_a_binary_file_is_found_whole(little):
    data = HEAD + b"\x01" + _wide("Zorblax", little) + TAIL
    assert [(f.rule, f.tag) for f in scan_blob("blob.bin", data)] == [("denylist", tag("zorblax"))]
    assert [(f.rule, f.tag) for f in scan_blob("blob.bin", HEAD + _wide("Zorblax", little) + TAIL)] == [("denylist", tag("zorblax"))]  # (and at an even one, once)


@pytest.mark.parametrize("little", [True, False], ids=["le", "be"])
def test_a_local_path_in_utf16_at_an_odd_offset_of_a_binary_file_is_found(little):
    data = HEAD + b"\x01" + _wide(windows_profile("Vexandra") + "\\notes", little) + TAIL
    assert rules(scan_blob("blob.bin", data, key=None)) == ["local-path"]


@pytest.mark.parametrize("size", [4, 5, 6, 7, 9, 16])
def test_utf16_text_inside_a_binary_file_is_found_across_chunk_boundaries(monkeypatch, size):
    pieces = [_wide("filler text one", True), b"\x00\x01", _wide("see Zorblax now", True), TAIL]
    data = HEAD + b"".join(pieces)
    expected = scan_blob("blob.bin", data)
    assert [(f.rule, f.tag) for f in expected] == [("denylist", tag("zorblax"))]
    monkeypatch.setattr(S, "CHUNK_SIZE", size)
    monkeypatch.setattr(S, "SAMPLE_SIZE", min(size, 8))
    assert scan_blob("blob.bin", data) == expected


# ---- public names are masked, unless the whole name is one denylisted word -----------------------

CAZIC_DENY = DENY | {h("cazic")}


def test_a_one_word_public_name_that_is_a_denylisted_token_is_not_masked():
    masker = S.PhraseMasker(["Cazic", "Cazic Thule"])
    alone = scan("Cazic", deny=CAZIC_DENY, phrases=masker)
    assert [(f.rule, f.tag) for f in alone] == [("denylist", tag("cazic"))]
    # A longer name that holds the same word keeps masking it.
    assert scan("Drops from Cazic Thule", deny=CAZIC_DENY, phrases=masker) == []


def test_a_public_name_of_one_token_with_short_words_around_it_is_also_not_masked():
    masker = S.PhraseMasker(["a Cazic"])
    assert rules(scan("a Cazic", deny=CAZIC_DENY, phrases=masker)) == ["denylist"]


def test_a_one_word_name_made_of_two_tokens_keeps_masking_the_denylisted_one_inside_it():
    masker = S.PhraseMasker(["QeynosCazic"])
    assert scan("QeynosCazic", deny=CAZIC_DENY, phrases=masker) == []


def test_the_cli_reports_a_one_word_catalog_name_that_is_a_denylisted_token(repo, keyfile):
    import json

    privacy_files(repo, deny=("zorblax", "cazic"))
    catalog = {"items": [{"name": "Cazic"}, {"name": "Cazic Thule Bracer"}]}
    write(repo, "derived/catalog.json", json.dumps(catalog))
    write(repo, "docs/one.md", "Cazic\n")
    write(repo, "docs/many.md", "Cazic Thule Bracer\n")
    assert run_cli(["docs/many.md", "--key-file", keyfile], repo).returncode == 0
    done = run_cli(["docs/one.md", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert [f["rule"] for f in parse_output(done.stdout)] == ["denylist"]


# ---- a folded view keeps its map to the original text --------------------------------------------


@pytest.mark.parametrize(
    "text,folded,origin",
    [
        ("Zor\u200bbl\u0430x", "Zorblax", [0, 1, 2, 4, 5, 6, 7]),
        ("Zor-\nblax", "Zorblax", [0, 1, 2, 5, 6, 7, 8]),
        ("Zor_blax", "Zorblax", [0, 1, 2, 4, 5, 6, 7]),
        ("Hello", "Hello", [0, 1, 2, 3, 4]),
        ("", "", []),
    ],
)
def test_normalize_for_scan_can_return_the_origin_of_each_character(text, folded, origin):
    assert textnorm.normalize_for_scan_mapped(text) == (folded, origin)
    assert textnorm.normalize_for_scan(text) == folded


@pytest.mark.parametrize(
    "path,masked",
    [
        ("notes/Z\u043erblax-bis.md", "notes/{p}-bis.md"),
        ("notes/Zor\u200bblax-bis/x.md", "notes/{p}-bis/x.md"),
        ("notes/Zor%62lax-bis/x.md", "notes/{p}-bis/x.md"),
        ("notes/Zorbla%78-bis/x.md", "notes/{p}-bis/x.md"),
        ("notes/\uff3a\uff4f\uff52\uff42\uff4c\uff41\uff58-bis.md", "notes/{p}-bis.md"),
        ("notes/Zor&#98;lax-bis.md", "notes/{p}-bis.md"),
    ],
)
def test_a_name_found_only_in_a_folded_view_is_masked_at_its_original_span(path, masked):
    placeholder = f"[private:{tag('zorblax')}]"
    assert S.mask_path(path, KEY, set(DENY)) == masked.format(p=placeholder)


def test_the_cli_masks_a_folded_name_in_a_printed_path_at_its_span(repo, keyfile):
    name = "notes/Z\u043erblax-bis.md"
    write(repo, name, "clean\n")
    done = run_cli([name, "--key-file", keyfile], repo)
    assert done.returncode == 1
    found = parse_output(done.stdout)
    assert [(f["path"], f["rule"]) for f in found] == [
        (f"notes/[private:{tag('zorblax')}]-bis.md", "denylist")
    ]


# ---- a hyphenated word is joined whatever the line ending ----------------------------------------


@pytest.mark.parametrize(
    "text",
    ["Zor-\r\nblax crash", "Zor-\rblax crash", "Zor- \r\n  blax crash", "Zor\u00ad\r\nblax crash"],
    ids=["crlf", "cr", "spaces around a crlf", "soft hyphen and crlf"],
)
def test_a_wrapped_name_is_joined_whatever_the_line_ending(text):
    assert scan(text) == ZORBLAX_AT_1


@pytest.mark.parametrize("text", ["Zor-\r\n\r\nblax", "Zor-\r\r\nblax", "Zor-\r \nblax"])
def test_a_blank_line_between_the_two_halves_stops_the_join(text):
    assert scan(text) == []


@pytest.mark.parametrize("size", [4, 5, 6, 7, 9, 12])
def test_a_wrap_with_a_crlf_is_joined_across_chunk_boundaries(monkeypatch, size):
    monkeypatch.setattr(S, "CHUNK_SIZE", size)
    monkeypatch.setattr(S, "SAMPLE_SIZE", min(size, 8))
    assert scan_blob("f.txt", b"see Zor-\r\nblax now\r\n") == [finding("f.txt", 1, 5, "denylist", "zorblax")]


# ---- properties of the pieces added for the checks above ---------------------------------------


@settings(max_examples=300, deadline=None)
@given(st.text(alphabet="ABCDEFGHIJabcdefghij .-_0123", max_size=60))
def test_the_extra_readings_of_capital_runs_are_the_same_for_ascii_and_general_text(text):
    # A line with a letter outside ASCII is read by the general code; a space keeps that letter
    # apart from the ASCII part, whose extra readings must not change.
    general = textnorm.capital_run_extras(text + " " + chr(0xE9))
    assert [piece for piece in general if piece[1] <= len(text)] == textnorm.capital_run_extras(
        text
    )


@settings(max_examples=300, deadline=None)
@given(st.text(alphabet="Zorblax-_*` \n\r.&;#9%62", max_size=50))
def test_the_mapped_normalizer_agrees_with_the_plain_one_and_maps_into_the_original(text):
    folded, origin = textnorm.normalize_for_scan_mapped(text)
    assert folded == textnorm.normalize_for_scan(text)
    assert len(origin) == len(folded)
    assert all(0 <= index < max(len(text), 1) for index in origin)
    assert origin == sorted(origin)


@pytest.mark.parametrize("size", [64, 200])
def test_one_enormous_utf16_run_is_checked_in_pieces_without_losing_a_name_at_its_start(
    monkeypatch, size
):
    monkeypatch.setattr(S, "MAX_LINE", size)
    run = "see Zorblax " + "word " * 400
    data = HEAD + _wide(run, True) + TAIL
    result = scan_blob("blob.bin", data)
    assert [(f.rule, f.line, f.tag) for f in result] == [("denylist", 1, tag("zorblax"))]


def test_the_extra_readings_of_capital_runs_also_apply_to_a_line_with_other_scripts_in_it():
    # The line holds a letter outside ASCII, so the general code reads it, not the ASCII code.
    assert scan("ZOrblax " + chr(0xE9)) == ZORBLAX_AT_1
    assert scan("ZORBLAXBis " + chr(0x4E2D)) == ZORBLAX_AT_1
    assert scan(chr(0x4E2D) + " ZORBLAXgear") == [finding("f.txt", 1, 3, "denylist", "zorblax")]
