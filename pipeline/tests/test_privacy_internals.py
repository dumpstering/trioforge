"""Unit tests for the pieces of the privacy scanner: tokens, digests, normalization, decoding,
the phrase masker, streaming and output masking. Test data is invented, and strings shaped
like log lines are built at run time."""

from __future__ import annotations

import base64
import io
import random
import re
import string
import unicodedata

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from test_privacy_helpers import (  # noqa: F401  (fixtures are used by name)
    DENY,
    KEY,
    OTHER_KEY,
    h,
    rules,
    scan,
    scan_blob,
    tag,
)
from trioforge.privacy import scan as S


def finding(path, line, col, rule, token=None):
    return S.Finding(path, line, col, rule, tag(token) if token else "-")


# ---- digest and load_list ----------------------------------------------------------------


def test_digest_is_hmac_sha256_lowercase_hex():
    for key in (KEY, OTHER_KEY, b"short key", b"k" * 100):
        value = S.digest(key, "zorblax")
        assert value == h("zorblax", key)
        assert re.fullmatch(r"[0-9a-f]{64}", value)


def test_digest_keys_matter_and_tokens_are_exact():
    assert S.digest(KEY, "zorblax") != S.digest(OTHER_KEY, "zorblax")
    assert S.digest(KEY, "zorblax") != S.digest(KEY, "Zorblax")


def test_digest_survives_text_that_cannot_be_encoded():
    assert re.fullmatch(r"[0-9a-f]{64}", S.digest(KEY, "a\ud800b"))


def test_load_list_skips_blanks_and_comments_and_lowercases(tmp_path):
    path = tmp_path / "list.txt"
    path.write_bytes(b"\xef\xbb\xbf# header\n  ABC123  \n\n#comment\r\ndef\r\nDEF\n")
    assert S.load_list(str(path)) == {"abc123", "def"}


# ---- tokens --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Zorblax's kit", [(1, 1, "zorblax"), (1, 11, "kit")]),
        ("ZorblaxBis", [(1, 1, "zorblax"), (1, 8, "bis")]),
        ("zorblax2", [(1, 1, "zorblax")]),
        ("zorblax123", [(1, 1, "zorblax"), (1, 8, "123")]),
        ("2zorblax", [(1, 2, "zorblax")]),
        ("ZORBLAX", [(1, 1, "zorblax")]),
        # A run of capitals followed by lower case is split where the capitals end.
        ("ZORBLAXbis", [(1, 1, "zorblax"), (1, 8, "bis")]),
        ("zorblaxBIS", [(1, 1, "zorblax"), (1, 8, "bis")]),
        ("McHale", [(1, 3, "hale")]),
        ("a-b c.d", []),
        ("ab\ncde\r\nfgh\rijk", [(2, 1, "cde"), (3, 1, "fgh"), (4, 1, "ijk")]),
        ("  indented", [(1, 3, "indented")]),
        ("under_score-and.dot", [(1, 1, "under"), (1, 7, "score"), (1, 13, "and"), (1, 17, "dot")]),
    ],
)
def test_tokens_split_on_punctuation_case_and_digits(text, expected):
    assert list(S.tokens(text)) == expected


def test_tokens_for_a_path_can_start_at_line_zero():
    assert list(S.tokens("notes/zorblax-bis.md", first_line=0)) == [
        (0, 1, "notes"),
        (0, 7, "zorblax"),
        (0, 15, "bis"),
    ]


def _is_latin(letter):
    return unicodedata.name(letter, "").startswith(("LATIN", "FULLWIDTH LATIN"))


def _reference_tokens(text):
    """A slow, independent statement of the tokenization rules."""
    found = []
    for number, line in enumerate(re.split(r"\r\n|\n|\r", text), start=1):
        i = 0
        while i < len(line):
            if not line[i].isalnum():
                i += 1
                continue
            j = i
            while j < len(line) and line[j].isalnum():
                j += 1
            run = line[i:j]
            cuts = [0]
            for k in range(1, len(run)):
                before, after = run[k - 1], run[k]
                if (before.islower() and after.isupper()) or before.isalpha() != after.isalpha():
                    cuts.append(k)
                elif before.isalpha() and after.isalpha() and _is_latin(before) != _is_latin(after):
                    cuts.append(k)  # a change of script: Latin letters against any other
                elif before.isupper() and after.islower() and k >= 2 and run[k - 2].isupper():
                    cuts.append(k)  # a run of two or more capitals, then lower case
            cuts.append(len(run))
            for a, b in zip(cuts, cuts[1:]):
                token = run[a:b].casefold()
                if len(token) >= 3:
                    found.append((number, i + a + 1, token))
            i = j
    return found


@settings(max_examples=300, deadline=None)
@given(st.text(alphabet=string.printable, max_size=120))
def test_tokens_agree_with_the_reference_on_ascii(text):
    assert list(S.tokens(text)) == _reference_tokens(text)


@settings(max_examples=300, deadline=None)
@given(
    st.text(
        alphabet=string.printable + "\u00e9\u00c9\u00df\u0130\u03a3\u0431\u4e2d\u00b2\u0663\uff21",
        max_size=60,
    )
)
def test_tokens_agree_with_the_reference_beyond_ascii(text):
    assert list(S.tokens(text)) == _reference_tokens(text)


# ---- normalization -----------------------------------------------------------------------

CYRILLIC_LOWER = dict(
    zip(
        "\u0430\u0435\u043e\u0440\u0441\u0443\u0445\u043a\u043c\u0442\u0432\u043d\u0456\u0458\u0455",
        "aeopcyxkmtbhijs",
    )
)
CYRILLIC_UPPER = dict(
    zip(
        "\u0410\u0415\u041e\u0420\u0421\u0423\u0425\u041a\u041c\u0422\u0412\u041d\u0406\u0408\u0405",
        "aeopcyxkmtbhijs",
    )
)
GREEK_LOWER = dict(zip("\u03b1\u03b2\u03b5\u03b9\u03ba\u03bd\u03bf\u03c1\u03c4\u03c5\u03c7", "abeikvoptux"))
GREEK_UPPER = dict(zip("\u0391\u0392\u0395\u0399\u039a\u039f\u03a1\u03a4\u03a7", "abeikoptx"))


@pytest.mark.parametrize("source,target", sorted({**CYRILLIC_LOWER, **GREEK_LOWER}.items()))
def test_confusable_lowercase_letters_fold_to_latin(source, target):
    assert S.normalize_for_scan("x" + source + "x") == "x" + target + "x"


@pytest.mark.parametrize("source,target", sorted({**CYRILLIC_UPPER, **GREEK_UPPER}.items()))
def test_confusable_uppercase_letters_fold_to_latin(source, target):
    assert S.normalize_for_scan("X" + source + "X").casefold() == "x" + target + "x"


def test_greek_capital_nu_and_upsilon_fold_to_ascii_letters():
    for source in ("\u039d", "\u03a5"):
        assert S.normalize_for_scan(source).isascii()


@pytest.mark.parametrize(
    "text",
    [
        "Zor\u200bblax",
        "Zor\u200cblax",
        "Zor\u200dblax",
        "Zor\u2060blax",
        "Zor\ufeffblax",
        "Zor\u00adblax",
        "Zor\u202eblax",
        "Zor\u200fblax",
        "Zorbla\u0301x",
        "Zorbla\u0308x",
        "Zor\u0336b\u0336lax",
        "\uff3a\uff4f\uff52\uff42\uff4c\uff41\uff58",
        "\u2124orblax",
        "Z\u043erblax",
        "Z\u03bfrblax",
        "Zorbl\u0430x",
        "ZORBL\u0410X",
    ],
)
def test_normalize_turns_disguised_spellings_into_the_plain_name(text):
    assert S.normalize_for_scan(text).casefold() == "zorblax"


def test_normalize_leaves_ordinary_text_alone():
    for text in ("", "Hello, world! 123", "line one\nline two.", "a - b", "tabs\tand  spaces"):
        assert S.normalize_for_scan(text) == text


def test_normalize_joins_a_hyphenated_line_wrap():
    assert S.normalize_for_scan("Zor-\nblax") == "Zorblax"
    assert S.normalize_for_scan("Zor-\r\nblax") == "Zorblax"
    assert S.normalize_for_scan("Zor-\rblax") == "Zorblax"
    assert S.normalize_for_scan("a - \nb") == "a - \nb"  # not a word split
    assert S.normalize_for_scan("end-\n\nnext") == "end-\n\nnext"  # a blank line breaks the join
    assert S.normalize_for_scan("x-\n12") == "x-\n12"  # digits are not a continuation


def test_normalize_removes_emphasis_markers_between_two_letters_only():
    assert S.normalize_for_scan("**Zor**blax") == "**Zorblax"
    assert S.normalize_for_scan("Zor_blax") == "Zorblax"
    assert S.normalize_for_scan("Zor`blax") == "Zorblax"
    assert S.normalize_for_scan("Zor*b*lax") == "Zorblax"
    assert S.normalize_for_scan("_snake_") == "_snake_"
    assert S.normalize_for_scan("x_1") == "x_1"
    assert S.normalize_for_scan("2*3") == "2*3"


# ---- decoded passes ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "&#90;orblax",
        "&#x5A;orblax",
        "&#X5a;orblax",
        "Zorbla&#120;",
        "Zor&#98;&#108;ax",
        "%5A%6F%72blax",
        "%5Aorblax",
        "Zor%2562lax",
        "Zor%252562lax",
        "Zor&amp;#98;lax",
        "Zor%26%2398%3Blax",
        "Zor\\u0062lax",
        "Zor\\u{62}lax",
        "Zor\\U00000062lax",
        "Zor\\x62lax",
        "Zor\\u0062\\u006cax",
    ],
)
def test_encoded_spellings_are_found(text):
    assert [f.rule for f in scan(text)] == ["denylist"]


def test_simple_escapes_separate_words_in_json_text():
    assert [f.rule for f in scan('"line one\\nzorblax says hi"')] == ["denylist"]
    assert [f.rule for f in scan('{"a":"x\\tzorblax"}')] == ["denylist"]


def test_every_finding_is_reported_once_whatever_number_of_views_sees_it():
    text = "Zorblax Zor&#98;lax Zorblax&amp; %5Aorblax"
    result = scan(text)
    assert [f.col for f in result] == [1, 9, 21, 34]


def test_decoded_columns_point_at_the_start_of_the_encoded_text():
    assert [(f.line, f.col) for f in scan("x Zor&#98;lax y")] == [(1, 3)]
    assert [(f.line, f.col) for f in scan("&#x41; Zor%62lax")] == [(1, 8)]


def test_base64_run_inside_a_longer_blob_is_found():
    blob = base64.b64encode(b'{"owner": "Zorblax", "level": 50, "note": "gear list"}').decode()
    assert [f.rule for f in scan("data: " + blob)] == ["denylist"]
    assert [f.rule for f in scan("data: " + blob.rstrip("="))] == ["denylist"]
    url_safe = base64.urlsafe_b64encode(b"~~~???>>>Zorblax<<<???~~~").decode()
    assert [f.rule for f in scan(url_safe)] == ["denylist"]


def test_base64_of_binary_data_and_plain_words_are_left_alone():
    rng = random.Random(5)
    noise = base64.b64encode(bytes(rng.randrange(256) for _ in range(300))).decode()
    assert scan(noise) == []
    assert scan("documentation internationalization uncharacteristically") == []
    assert scan("A" * 4096 + "b" * 10) == []


def test_base64_decoded_text_is_also_checked_for_log_shapes():
    encoded = base64.b64encode(b"You have " + b"looted a thing. and some more padding").decode()
    assert rules(scan(encoded)) == ["log-loot"]


# ---- hex strings are not words --------------------------------------------------------------


def test_long_hex_strings_are_not_tokenized():
    digest = "dead" + "face" * 3 + "beef" + "0123456789abcdef" * 2 + "cafe" * 4
    deny = {h("dead"), h("face"), h("beef"), h("cafe")}
    assert scan(digest, deny=deny) == []
    assert scan("# key-check: 0123456789abcdef", deny=deny) == []
    assert scan("face", deny=deny) != []
    assert scan(digest + " face", deny=deny)[0].col == len(digest) + 2


# ---- the phrase masker -----------------------------------------------------------------------


def test_masker_masks_whole_phrases_case_insensitively_and_keeps_the_length():
    masker = S.PhraseMasker(["Cazic Thule", "Ring of Fire"])
    assert masker.mask("Cazic Thule") == " " * 11
    assert masker.mask("go to CAZIC thule now") == "go to " + " " * 11 + " now"
    assert masker.mask("(Cazic Thule)") == "(" + " " * 11 + ")"
    assert masker.mask("Cazic Thule's ring of fire.") == " " * 11 + "'s " + " " * 12 + "."


def test_masker_needs_whole_words_and_exact_separators():
    masker = S.PhraseMasker(["Cazic Thule"])
    for text in ("xCazic Thule", "Cazic Thulex", "Cazic  Thule", "Cazic-Thule", "Cazic_Thule", "Cazic"):
        assert masker.mask(text) == text


def test_masker_prefers_the_longest_phrase_and_never_overlaps():
    masker = S.PhraseMasker(["Ring", "Ring of Fire", "Fire Giant"])
    assert masker.mask("Ring of Fire Giant") == " " * 12 + " Giant"
    assert masker.mask("Ring of Water") == " " * 4 + " of Water"
    assert masker.mask("Fire Giant") == " " * 10


def test_masker_handles_punctuation_inside_phrases():
    masker = S.PhraseMasker(["Ak'Anon", "Spell: Fire Bolt", "Dr. Nemo", "'Lil Pete's"])
    assert masker.mask("in Ak'Anon!") == "in " + " " * 7 + "!"
    assert masker.mask("Spell: Fire Bolt") == " " * 16
    assert masker.mask("Spell Fire Bolt") == "Spell Fire Bolt"
    assert masker.mask("Dr. Nemo") == " " * 8
    assert masker.mask("x Lil Pete's x") == "x " + " " * 10 + " x"


def test_masker_ignores_blank_phrases_and_counts_distinct_ones():
    masker = S.PhraseMasker(["", "   ", "...", "Cazic Thule", "cazic thule", "CAZIC THULE"])
    assert len(masker) == 1
    assert S.PhraseMasker([]).mask("anything") == "anything"


def test_masker_matches_both_the_accented_and_the_plain_spelling():
    masker = S.PhraseMasker(["Caf\u00e9 Ruins"])
    assert masker.mask("Caf\u00e9 Ruins") == " " * 10
    assert masker.mask("Cafe Ruins") == " " * 10


def test_masker_keeps_the_length_when_case_folding_would_change_it():
    masker = S.PhraseMasker(["Big Thing"])
    text = "\u0130 \u00df Big Thing"
    assert len(masker.mask(text)) == len(text)
    assert masker.mask(text) == text[:4] + " " * 9


def test_a_masked_name_inside_a_phrase_is_hidden_but_the_same_name_elsewhere_is_not():
    deny = DENY | {h("cazic")}
    masker = S.PhraseMasker(["Cazic Thule"])
    result = scan("Cazic Thule and Cazic and zorblax's Cazic Thule", deny=deny, phrases=masker)
    assert [(f.col, f.tag) for f in result] == [(17, tag("cazic")), (27, tag("zorblax"))]


def test_masking_does_not_apply_to_log_shape_rules():
    masker = S.PhraseMasker(["Vexandra tells you"])
    text = "Vexandra" + " tells you, 'hi'"
    assert rules(scan(text, phrases=masker)) == ["log-tell"]


def test_masking_also_applies_to_paths():
    masker = S.PhraseMasker(["Cazic Thule"])
    deny = DENY | {h("cazic")}
    assert scan("x", path="docs/Cazic Thule.md", deny=deny, phrases=masker) == []
    assert rules(scan("x", path="docs/cazic.md", deny=deny, phrases=masker)) == ["denylist"]


# ---- streaming: chunk boundaries, long lines, readers ------------------------------------


@pytest.mark.parametrize("size", [4, 5, 7, 16, 33])
def test_a_name_straddling_a_chunk_boundary_is_found_with_the_right_position(monkeypatch, size):
    monkeypatch.setattr(S, "CHUNK_SIZE", size)
    monkeypatch.setattr(S, "SAMPLE_SIZE", min(size, 8))
    data = b"first line\r\nsecond " + b"x" * 20 + b" Zorblax end\r\nthird\r\n"
    assert scan_blob("f.txt", data) == [finding("f.txt", 2, 29, "denylist", "zorblax")]


@pytest.mark.parametrize("size", [4, 5, 6, 7, 11])
def test_line_endings_split_across_chunks_still_count_once(monkeypatch, size):
    monkeypatch.setattr(S, "CHUNK_SIZE", size)
    monkeypatch.setattr(S, "SAMPLE_SIZE", min(size, 8))
    data = b"ab\r\ncd\r\nef\rgh\nij\r\n\r\nZorblax\r"
    assert scan_blob("f.txt", data) == [finding("f.txt", 7, 1, "denylist", "zorblax")]


@pytest.mark.parametrize("size", [4, 5, 6, 7])
def test_a_multibyte_character_split_across_chunks_decodes_cleanly(monkeypatch, size):
    monkeypatch.setattr(S, "CHUNK_SIZE", size)
    monkeypatch.setattr(S, "SAMPLE_SIZE", min(size, 8))
    data = "caf\u00e9 \u00e9\u00e9\u00e9 Zorblax \U0001f600 end".encode("utf-8")
    assert scan_blob("f.txt", data) == [finding("f.txt", 1, 10, "denylist", "zorblax")]


@pytest.mark.parametrize("size", [4, 6, 8, 10])
def test_utf16_streams_decode_across_chunks(monkeypatch, size):
    monkeypatch.setattr(S, "CHUNK_SIZE", size)
    monkeypatch.setattr(S, "SAMPLE_SIZE", 64)
    text = "filler line\n" * 10 + "second Zorblax\n"
    for encoding, bom in (("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff"), ("utf-16-le", b"")):
        data = bom + text.encode(encoding)
        assert scan_blob("w.txt", data) == [finding("w.txt", 11, 8, "denylist", "zorblax")], (
            encoding,
            bom,
        )


def test_the_strings_pass_joins_runs_that_cross_a_chunk_boundary(monkeypatch):
    monkeypatch.setattr(S, "CHUNK_SIZE", 16)
    monkeypatch.setattr(S, "SAMPLE_SIZE", 8)
    data = b"\x00" * 13 + b"Zorblax" + b"\x00\x01" * 5 + b"\nQuimmet\x00"
    result = scan_blob("blob.bin", data)
    assert [(f.rule, f.tag) for f in result] == [
        ("denylist", tag("zorblax")),
        ("denylist", tag("quimmet")),
    ]
    assert [(f.line, f.col) for f in result] == [(1, 14), (2, 1)]


def test_a_hyphenated_wrap_is_joined_across_chunks_too(monkeypatch):
    monkeypatch.setattr(S, "CHUNK_SIZE", 5)
    monkeypatch.setattr(S, "SAMPLE_SIZE", 5)
    assert scan_blob("f.txt", b"see Zor-\nblax now\n") == [finding("f.txt", 1, 5, "denylist", "zorblax")]


def test_very_long_lines_are_split_at_word_boundaries_without_losing_position(monkeypatch):
    monkeypatch.setattr(S, "CHUNK_SIZE", 40)
    monkeypatch.setattr(S, "SAMPLE_SIZE", 8)
    monkeypatch.setattr(S, "MAX_LINE", 50)
    line = " ".join(["alpha", "beta", "gamma", "delta"] * 30)
    data = (line + " Zorblax " + line + "\nnext Quimmet\n").encode()
    result = scan_blob("f.txt", data)
    assert [(f.line, f.col, f.tag) for f in result] == [
        (1, len(line) + 2, tag("zorblax")),
        (2, 6, tag("quimmet")),
    ]


def test_a_reader_may_return_a_file_object_and_it_is_read_in_bounded_chunks_then_closed():
    class Spy(io.BytesIO):
        closed_by_scanner = False

        def read(self, size=-1):
            self.sizes.append(size)
            return super().read(size)

        def close(self):
            self.closed_by_scanner = True
            super().close()

    stream = Spy(b"fine line\n" * 1000 + b"Zorblax\n")
    stream.sizes = []
    result = S.scan_paths(["big.txt"], KEY, set(DENY), set(), lambda p: stream)
    assert result == [finding("big.txt", 1001, 1, "denylist", "zorblax")]
    assert stream.sizes and all(0 < size <= S.CHUNK_SIZE for size in stream.sizes)
    assert stream.closed_by_scanner


def test_a_reader_error_becomes_a_scan_error_naming_the_path():
    def broken(path):
        raise PermissionError("locked")

    with pytest.raises(S.FileReadError) as caught:
        S.scan_paths(["locked.txt"], KEY, set(DENY), set(), broken)
    assert caught.value.path == "locked.txt"


# ---- results: order, caps and no key -----------------------------------------------------------


def test_findings_come_back_sorted_by_position():
    text = "Quimmet\nzorblax Quimmet\n" + "You have " + "looted a thing\n"
    result = scan(text)
    positions = [(f.line, f.col) for f in result]
    assert positions == sorted(positions)
    assert len(result) == 4


def test_without_a_key_only_the_log_shape_rules_run():
    text = "Zorblax\n" + "You have " + "looted a thing\n"
    result = S.scan_text("f.txt", text, None, set(), set())
    assert rules(result) == ["log-loot"]


def test_the_explain_sink_receives_the_token_for_each_finding():
    sink = {}
    result = scan("hi Zorblax\n" + "You have " + "looted a thing\n", explain=sink)
    by_rule = {f.rule: sink[f] for f in result}
    assert by_rule["denylist"] == "zorblax"
    assert by_rule["log-loot"].startswith("You have")


def test_a_path_with_a_private_name_is_masked_for_printing():
    assert S.mask_path("notes/zorblax-bis.md", KEY, set(DENY)) == (
        f"notes/[private:{tag('zorblax')}]-bis.md"
    )
    assert S.mask_path("Zorblax/Quimmet.md", KEY, set(DENY)) == (
        f"[private:{tag('zorblax')}]/[private:{tag('quimmet')}].md"
    )
    assert S.mask_path("docs/readme.md", KEY, set(DENY)) == "docs/readme.md"
    assert S.mask_path("notes/zorblax.md", None, set()) == "notes/zorblax.md"


def test_a_disguised_name_in_a_printed_path_is_masked_too():
    masked = S.mask_path("notes/Zor\u200bblax/x.md", KEY, set(DENY))
    assert "orblax" not in masked.lower() and f"[private:{tag('zorblax')}]" in masked
    masked = S.mask_path("notes/Zor%62lax/x.md", KEY, set(DENY))
    assert "zor" not in masked.lower() and "[private:" in masked


# ---- keys of any length use the standard HMAC key schedule -----------------------------------------


@pytest.mark.parametrize("key", [b"", b"abc", bytes(range(64)), bytes(range(65)), b"k" * 200])
def test_the_fast_digest_matches_standard_hmac_for_any_key_length(key):
    deny = {h("zorblax", key)}
    assert [f.rule for f in scan("Zorblax", key=key, deny=deny)] == ["denylist"]
    assert scan("Quimmet", key=key, deny=deny) == []


# ---- the maps that tie a changed view back to the original line ----------------------------------

_PIECES = [
    "a", "Z", "z", "x", "7", " ", "-", "_", "*", "`", "&#98;", "%62", "\\u0062", "\\x62", "&amp;",
    "\\n", "\u200b", "\u00ad", "\u0301", "\u00e9", "\u043e", "\uff3a", "\u4e2d", "Wm9yYmxheA==",
    "dead" * 4, "\ufb01", "\u2126",
]


@settings(max_examples=400, deadline=None)
@given(st.lists(st.sampled_from(_PIECES), max_size=14).map("".join))
def test_every_view_has_a_position_map_that_points_back_into_the_line(line):
    from trioforge.privacy.scan import _variants

    for text, imap in _variants(line):
        if imap is not None:
            assert len(imap) == len(text)
            assert all(0 <= index < max(len(line), 1) for index in imap)


@settings(max_examples=300, deadline=None)
@given(st.lists(st.sampled_from(_PIECES), max_size=14).map("".join))
def test_scanning_never_fails_and_columns_stay_inside_the_line(line):
    for found in scan(line):
        assert 1 <= found.col <= max(len(line), 1)
        assert found.line == 1


# ---- the worktree reader never opens what it should not -----------------------------------------------


def test_the_worktree_reader_refuses_special_files_and_untracked_links(monkeypatch, tmp_path):
    import os
    import stat

    from trioforge.privacy.scan import NotRegular, _worktree_reader

    real = tmp_path / "plain.txt"
    real.write_bytes(b"content")
    modes = {"fifo": stat.S_IFIFO, "device": stat.S_IFCHR, "socket": stat.S_IFSOCK, "link": stat.S_IFLNK}
    original = os.lstat

    def fake_lstat(path):
        name = os.path.basename(str(path))
        if name in modes:
            return os.stat_result((modes[name] | 0o644, 0, 0, 1, 0, 0, 0, 0, 0, 0))
        return original(path)

    monkeypatch.setattr(os, "lstat", fake_lstat)
    monkeypatch.setattr(os, "readlink", lambda path: "somewhere/else")
    reader = _worktree_reader(
        {name: str(tmp_path / name) for name in [*modes, "plain.txt"]}, untracked={"link"}
    )
    for name in ("fifo", "device", "socket", "link"):
        with pytest.raises(NotRegular):
            reader(name)
    tracked_link = _worktree_reader({"link": str(tmp_path / "link")}, untracked=set())
    assert tracked_link("link") == b"somewhere/else"  # the link text, never what it points to
    handle = reader("plain.txt")
    try:
        assert handle.read() == b"content"
    finally:
        handle.close()


def test_package_lock_integrity_values_are_hashes_not_words():
    integrity = "sha512-aBcDeZorblaxQwErTyUiOpAsDfGhJkL12345678901234567890xyz=="
    assert scan('"integrity": "' + integrity + '"') == []
    assert scan('"integrity": "' + integrity.upper() + '"') == []
    # The word before the dash is not blanked, and a name next to a hash is still found.
    assert [f.rule for f in scan("sha512 Zorblax " + integrity)] == ["denylist"]


def test_only_short_base64_runs_are_cached():
    from trioforge.privacy import textnorm

    textnorm._base64_cache.clear()
    short = base64.b64encode(b"a short printable sentence").decode()
    long_run = base64.b64encode(b"x" * 1500 + b"Zorblax").decode()
    assert len(short) <= 256 < len(long_run)
    scan("pad " + short + " pad")
    scan("pad " + long_run + " pad")
    assert short.rstrip("=") in textnorm._base64_cache
    assert long_run.rstrip("=") not in textnorm._base64_cache


@pytest.mark.parametrize("hyphen", [chr(0x2010), chr(0x2011), chr(0xAD)], ids=["hyphen", "non-breaking", "soft"])
def test_typographic_hyphens_at_a_line_end_join_the_word_too(hyphen):
    assert S.normalize_for_scan("Zor" + hyphen + "\nblax") == "Zorblax"
    assert [f.rule for f in scan("Zor" + hyphen + "\nblax crash")] == ["denylist"]
    assert [f.rule for f in scan("Zor" + hyphen + "\r\n  blax crash")] == ["denylist"]
    assert scan("Zor" + hyphen + " blax") == []  # no line break, so no join


def test_a_wrapped_word_with_an_indented_continuation_is_found_at_the_start_of_the_word():
    assert [(f.line, f.col) for f in scan("some text Zor-\n    blax more")] == [(1, 11)]


# ---- nothing crashes the scanner --------------------------------------------------------------------

_BOMS = [b"", b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"]


@settings(max_examples=300, deadline=None)
@given(st.binary(max_size=3000), st.sampled_from(_BOMS))
def test_arbitrary_bytes_never_crash_the_scanner(data, bom):
    result = S.scan_bytes("blob.bin", bom + data, KEY, set(DENY), set())
    assert all(isinstance(found, S.Finding) for found in result)


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=400))
def test_arbitrary_text_including_lone_surrogates_never_crashes_the_scanner(text):
    for found in S.scan_text("any.txt", text, KEY, set(DENY), set()):
        assert found.col >= 0 and found.line >= 0


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=80))
def test_arbitrary_paths_never_crash_the_scanner_or_the_masker(path):
    S.scan_text(path, "", KEY, set(DENY), set())
    assert isinstance(S.mask_path(path, KEY, set(DENY)), str)


# ---- streaming agrees with scanning the whole text -----------------------------------------------------

_STREAM_PIECES = [
    "Zorblax", "Quimmet", "Zor-", "blax", "Zor", "\n", "\r\n", "\r", " ", "  ", "x", "-", "Z",
    "&#98;", "%62", "_", "**", "\n\n", chr(0xE9), chr(0x200B), chr(0x4E2D), chr(0x1F600),
    "You have " + "looted a ", "[50 Paladin] " + "Vexandra (", "a" * 30,
]


@settings(max_examples=400, deadline=None)
@given(st.lists(st.sampled_from(_STREAM_PIECES), max_size=40).map("".join), st.integers(4, 48))
def test_streaming_gives_the_same_findings_as_scanning_the_whole_text(text, size):
    expected = S.scan_text("f.txt", text, KEY, set(DENY), set())
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(S, "CHUNK_SIZE", size)
        patch.setattr(S, "SAMPLE_SIZE", min(size, 8))
        streamed = S.scan_bytes("f.txt", text.encode("utf-8"), KEY, set(DENY), set())
    assert streamed == expected
