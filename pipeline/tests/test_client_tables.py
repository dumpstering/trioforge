"""Tests for the client text tables: zones, class pools, softcaps and skill caps.

The unit tests write small synthetic files under ``tmp_path``, in the shape of the shipped
text resources (``^`` separated, CRLF line endings), and never copy a game file. The tests
that read the real install folder carry the ``client`` mark and skip when it is absent.
"""

import argparse
import calendar
import datetime
import hashlib
import itertools
import json
import os
import re
from pathlib import Path

import pytest

import trioforge
from trioforge.sources import client_tables as ct

CLIENT_DIR = ct.resolve_client_dir()
HAVE_CLIENT = CLIENT_DIR is not None and all((CLIENT_DIR / name).is_file() for name in ct.INPUT_FILES)
REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_CLIENT_FILES = REPO_ROOT / "derived" / "client"

# The row floors as shipped, captured before any test lowers them.
REAL_FLOORS = dict(ct.MINIMUM_ROWS)


def real_client(test):
    """Mark a test as reading the real install folder, and skip it when the folder is absent."""
    test = pytest.mark.client(test)
    return pytest.mark.skipif(not HAVE_CLIENT, reason="EverQuest Legends client folder not found")(test)


@pytest.fixture(autouse=True)
def small_tables(monkeypatch):
    """The synthetic tables below hold a few rows, so the row floors are lowered to one for every
    test; the tests of the floors themselves put the planned numbers back."""
    for name in REAL_FLOORS:
        monkeypatch.setitem(ct.MINIMUM_ROWS, name, 1)


def crlf(*lines: str) -> str:
    return "".join(line + "\r\n" for line in lines)


def write_text(path: Path, text: str, encoding: str = "latin-1") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode(encoding))
    return path


def set_date(path: Path, year: int, month: int, day: int, hour: int = 12) -> None:
    """Give a file a last-write time on a given UTC calendar day (noon unless told otherwise)."""
    stamp = calendar.timegm((year, month, day, hour, 0, 0))
    os.utime(path, (stamp, stamp))


# 64 and 65 separate the two flag columns: only the third decides.
ZONES_TEXT = crlf("1^South Qeynos^12^60", "7^Highpass Caves^0^0", "64^Kedge Keep^12^0", "65^X^0^60")
BASEDATA_TEXT = crlf(
    "50^2^1320^900^456^7^13^4.4^4.5^3.250^",
    "50^3^1440^900^652^7^13^4.8^4.5^3.250^",
)
AC_TEXT = crlf("#CLASS^LVL^AC_CAP^SOFT_CAP_MULTIPLIER^", "3^50^392^0.33^")
SKILLCAPS_TEXT = crlf("1^0^50^200^0^")

FAKE_FILES = {
    ct.ZONES_FILE: (ZONES_TEXT, (2026, 9, 21)),
    ct.BASEDATA_FILE: (BASEDATA_TEXT, (2026, 5, 11)),
    ct.ACMITIGATION_FILE: (AC_TEXT, (2026, 5, 12)),
    ct.SKILLCAPS_FILE: (SKILLCAPS_TEXT, (2026, 6, 19)),
}


def make_client(root: Path) -> Path:
    """A fake install folder holding the four synthetic tables, each with a fixed file date."""
    for name, (text, date) in FAKE_FILES.items():
        set_date(write_text(root / name, text), *date)
    return root


# ---- zones ------------------------------------------------------------------------------------


def test_zones_keep_numeric_rows_and_count_the_flagged(tmp_path):
    # a junk line is an error (see test_a_line_that_fits_no_row_is_an_error_naming_the_line_but_not_showing_it),
    # so the fixture has none; 64 and 65 are the rows that separate the flag columns
    path = write_text(tmp_path / "ZoneNames.txt", ZONES_TEXT)
    assert ct.read_zones(path) == {
        "zones": [
            {"id": 1, "name": "South Qeynos", "c3": 12, "c4": 60, "flagged": True},
            {"id": 7, "name": "Highpass Caves", "c3": 0, "c4": 0, "flagged": False},
            {"id": 64, "name": "Kedge Keep", "c3": 12, "c4": 0, "flagged": True},
            {"id": 65, "name": "X", "c3": 0, "c4": 60, "flagged": False},
        ],
        "flagged_count": 2,
    }


def test_the_flag_follows_the_third_column_alone(tmp_path):
    path = write_text(tmp_path / "ZoneNames.txt", crlf("64^Kedge Keep^12^0", "65^X^0^60"))
    by_id = {zone["id"]: zone for zone in ct.read_zones(path)["zones"]}
    assert by_id[64]["flagged"] is True  # c3 set, c4 zero
    assert by_id[65]["flagged"] is False  # c3 zero, c4 set


def test_zones_accept_lf_endings_blank_lines_and_a_missing_final_newline(tmp_path):
    path = write_text(tmp_path / "ZoneNames.txt", "1^South Qeynos^12^60\n\n7^Highpass Caves^0^0")
    assert [zone["id"] for zone in ct.read_zones(path)["zones"]] == [1, 7]


def test_a_byte_above_127_in_a_zone_name_is_an_error_naming_the_line(tmp_path):
    # the files are plain ASCII, so a name with a byte above 127 means a different file, not a latin-1 name
    path = tmp_path / "ZoneNames.txt"
    path.write_bytes(b"1^South Qeynos^12^60\r\n5^Caf\xe9 Zone^12^60\r\n")
    with pytest.raises(ValueError, match=r"line 2.*ASCII") as caught:
        ct.read_zones(path)
    assert "Caf" not in str(caught.value)


def test_a_byte_order_mark_does_not_hide_the_first_row(tmp_path):
    path = tmp_path / "ZoneNames.txt"
    path.write_bytes(b"\xef\xbb\xbf1^South Qeynos^12^60\r\n")
    assert [zone["id"] for zone in ct.read_zones(path)["zones"]] == [1]


def test_a_line_break_character_inside_a_name_does_not_split_the_row(tmp_path):
    # 0x0b (vertical tab) is a line break to str.splitlines, as NEL (0x85) is, and it is plain ASCII
    path = tmp_path / "ZoneNames.txt"
    path.write_bytes(b"5^North\x0bSouth^12^60\r\n")
    zones = ct.read_zones(path)["zones"]
    assert [zone["id"] for zone in zones] == [5]
    assert zones[0]["name"] == "North\x0bSouth"


@pytest.mark.parametrize(
    "line",
    ["9^Broken^x^60", "9^Broken^12", "9^Broken^12^6.5", "9^Broken^^60"],
    ids=["flag-not-a-number", "too-few-fields", "fractional-field", "empty-field"],
)
def test_a_numbered_zone_row_that_is_malformed_is_an_error_not_a_silent_skip(tmp_path, line):
    path = write_text(tmp_path / "ZoneNames.txt", crlf("1^South Qeynos^12^60", line))
    with pytest.raises(ValueError, match="line 2"):
        ct.read_zones(path)


# ---- basedata ---------------------------------------------------------------------------------


def test_basedata_rows_hold_floats_in_the_file_order(tmp_path):
    path = write_text(tmp_path / "basedata.txt", BASEDATA_TEXT)
    rows = ct.read_basedata(path)["rows"]
    assert rows == [
        {
            "class": 2,
            "level": 50,
            "hp": 1320.0,
            "mana": 900.0,
            "end": 456.0,
            "hp_regen": 7.0,
            "end_regen": 13.0,
            "hp_fac": 4.4,
            "mana_fac": 4.5,
            "end_fac": 3.25,
        },
        {
            "class": 3,
            "level": 50,
            "hp": 1440.0,
            "mana": 900.0,
            "end": 652.0,
            "hp_regen": 7.0,
            "end_regen": 13.0,
            "hp_fac": 4.8,
            "mana_fac": 4.5,
            "end_fac": 3.25,
        },
    ]
    assert all(type(rows[0][key]) is float for key in rows[0] if key not in ("class", "level"))
    assert type(rows[0]["class"]) is int and type(rows[0]["level"]) is int


def test_basedata_is_level_then_class_and_a_factor_keeps_its_decimal_text(tmp_path):
    # the file lists the level first; 4.6 must come back as 4.6, not 4.6000000000000005
    path = write_text(tmp_path / "basedata.txt", crlf("50^4^1380^900^652^7^13^4.6^4.5^3.250^"))
    (row,) = ct.read_basedata(path)["rows"]
    assert (row["level"], row["class"], row["hp_fac"]) == (50, 4, 4.6)


def test_basedata_allows_a_missing_trailing_caret_and_skips_header_and_blank_lines(tmp_path):
    text = crlf("#LEVEL^CLASS", "", "1^1^25^0^15^2^5^0.083^0^0.075")
    (row,) = ct.read_basedata(write_text(tmp_path / "basedata.txt", text))["rows"]
    assert (row["level"], row["class"], row["hp"], row["end_fac"]) == (1, 1, 25.0, 0.075)


def test_a_short_basedata_row_is_an_error(tmp_path):
    path = write_text(tmp_path / "basedata.txt", crlf("1^1^25^0^15^2^5^0.083^0"))
    with pytest.raises(ValueError, match="line 1"):
        ct.read_basedata(path)


# ---- ACMitigation -----------------------------------------------------------------------------


def test_acmitigation_skips_the_header_and_reads_the_cap_and_the_rate(tmp_path):
    path = write_text(tmp_path / "ACMitigation.txt", AC_TEXT)
    assert ct.read_acmitigation(path) == {
        "rows": [{"class": 3, "level": 50, "ac_cap": 392, "past_cap_rate": 0.33}]
    }


def test_acmitigation_cap_is_an_integer_and_the_rate_a_float(tmp_path):
    # the file starts with its header, which is checked
    text = crlf("#CLASS^LVL^AC_CAP^SOFT_CAP_MULTIPLIER^", "1^1^312^1^")
    (row,) = ct.read_acmitigation(write_text(tmp_path / "a.txt", text))["rows"]
    assert type(row["ac_cap"]) is int
    assert type(row["past_cap_rate"]) is float


def test_an_acmitigation_row_with_a_bad_number_is_an_error(tmp_path):
    path = write_text(tmp_path / "a.txt", crlf("#CLASS^LVL^AC_CAP^SOFT_CAP_MULTIPLIER^", "3^50^x^0.33^"))
    with pytest.raises(ValueError, match="line 2"):
        ct.read_acmitigation(path)


# ---- skillcaps --------------------------------------------------------------------------------


def test_skillcaps_rows_and_the_skill_name_map(tmp_path):
    path = write_text(tmp_path / "skillcaps.txt", SKILLCAPS_TEXT)
    data = ct.read_skillcaps(path)
    assert data["rows"] == [{"class": 1, "skill": 0, "level": 50, "cap": 200}]
    assert data["skill_names"]["15"] == "Defense"
    assert data["skill_names"]["22"] == "Dual Wield"


def test_skillcaps_without_a_trailing_caret_are_read_the_same(tmp_path):
    path = write_text(tmp_path / "skillcaps.txt", "1^0^50^200^0")
    assert ct.read_skillcaps(path)["rows"] == [{"class": 1, "skill": 0, "level": 50, "cap": 200}]


def test_the_skill_name_map_holds_the_thirty_ported_ids():
    assert sorted(ct.SKILL_NAMES) == [
        0, 1, 2, 3, 4, 5, 7, 8, 10, 11, 13, 14, 15, 18, 19, 20, 22, 24, 28, 30,
        31, 33, 34, 36, 37, 51, 71, 73, 76, 77,
    ]  # fmt: skip
    assert ct.SKILL_NAMES[33] == "Offense"
    assert len(set(ct.SKILL_NAMES.values())) == len(ct.SKILL_NAMES)


def test_a_short_skillcaps_row_is_an_error(tmp_path):
    path = write_text(tmp_path / "skillcaps.txt", crlf("1^0^50"))
    with pytest.raises(ValueError, match="line 1"):
        ct.read_skillcaps(path)


# ---- the JSON writer --------------------------------------------------------------------------


def test_write_json_puts_each_list_item_on_its_own_line_and_round_trips(tmp_path):
    data = {"note": "café", "count": 2, "rows": [{"a": 1, "b": 0.5}, {"a": 2, "b": None}], "empty": []}
    path = tmp_path / "out.json"
    ct.write_json(path, data)
    text = path.read_text(encoding="utf-8")
    assert json.loads(text) == data
    assert text.endswith("}\n") and "\r" not in text
    assert "café" in text  # not escaped to é
    assert '  {"a":1,"b":0.5},' in text.splitlines()
    assert ' "empty": []' in text.splitlines()[-2]


def test_write_json_is_the_same_bytes_every_time(tmp_path):
    data = {"rows": [{"x": i, "y": i / 3} for i in range(50)]}
    ct.write_json(tmp_path / "a.json", data)
    ct.write_json(tmp_path / "b.json", data)
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


# ---- the client folder ------------------------------------------------------------------------


def test_the_client_folder_comes_from_the_argument_then_the_environment_then_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv(ct.ENV_CLIENT_DIR, str(tmp_path / "env"))
    assert ct.resolve_client_dir(tmp_path / "arg") == tmp_path / "arg"
    assert ct.resolve_client_dir() == tmp_path / "env"
    monkeypatch.delenv(ct.ENV_CLIENT_DIR)
    monkeypatch.setenv("PUBLIC", str(tmp_path / "public"))
    assert ct.resolve_client_dir() == (
        tmp_path / "public" / "Daybreak Game Company" / "Installed Games" / "EverQuest Legends"
    )
    monkeypatch.delenv("PUBLIC")
    assert ct.resolve_client_dir() is None


def test_an_empty_environment_value_counts_as_unset(monkeypatch, tmp_path):
    monkeypatch.setenv(ct.ENV_CLIENT_DIR, "")
    monkeypatch.setenv("PUBLIC", str(tmp_path))
    assert ct.resolve_client_dir() == tmp_path / "Daybreak Game Company" / "Installed Games" / "EverQuest Legends"


# ---- provenance and the manifest --------------------------------------------------------------


def test_an_input_record_has_the_relative_name_the_sha256_and_the_file_date(tmp_path):
    client = make_client(tmp_path / "client")
    record = ct.input_record(client, ct.ZONES_FILE)
    assert record == {
        "file": "Resources/ZoneNames.txt",
        "sha256": hashlib.sha256(ZONES_TEXT.encode("latin-1")).hexdigest(),
        "date": "2026-09-21",
    }


def test_the_file_date_is_the_utc_calendar_date_of_the_last_write(tmp_path):
    # The date is the UTC calendar date. The times are UTC, so the answer is the same on every
    # machine; on a machine west of Greenwich the local date of 02:30 UTC is the day before.
    path = write_text(tmp_path / "x.txt", "x")
    set_date(path, 2026, 10, 13, hour=2)
    assert ct.input_record(tmp_path, "x.txt")["date"] == "2026-10-13"
    set_date(path, 2026, 10, 12, hour=23)
    assert ct.input_record(tmp_path, "x.txt")["date"] == "2026-10-12"


def test_utc_date_reads_a_timestamp_in_utc():
    assert ct.utc_date(0) == "1970-01-01"
    assert ct.utc_date(calendar.timegm((2026, 10, 13, 2, 30, 0))) == "2026-10-13"
    assert ct.utc_date(calendar.timegm((2026, 10, 12, 23, 59, 59))) == "2026-10-12"
    assert ct.utc_date(calendar.timegm((2026, 10, 13, 0, 0, 0))) == "2026-10-13"


def test_today_utc_converts_an_aware_time_and_refuses_a_naive_one():
    west = datetime.timezone(datetime.timedelta(hours=-5))
    east = datetime.timezone(datetime.timedelta(hours=9))
    assert ct.today_utc(datetime.datetime(2026, 10, 12, 21, 30, tzinfo=west)) == "2026-10-13"
    assert ct.today_utc(datetime.datetime(2026, 10, 13, 6, 30, tzinfo=east)) == "2026-10-12"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", ct.today_utc())
    with pytest.raises(ValueError, match="time zone"):
        ct.today_utc(datetime.datetime(2026, 10, 13, 6, 30))


def test_update_manifest_merges_by_file_name_and_keeps_the_rest(tmp_path):
    first = {"file": "Resources/a.txt", "sha256": "1" * 64, "date": "2026-05-11"}
    second = {"file": "spells_us.txt", "sha256": "2" * 64, "date": "2026-10-12"}
    out_a = {"file": "a.json", "inputs": ["Resources/a.txt"], "generated": "2026-10-13"}
    out_s = {"file": "s.json", "inputs": ["spells_us.txt"], "generated": "2026-10-14"}
    ct.update_manifest(tmp_path, [first], [out_a], "2026-10-13")
    ct.update_manifest(tmp_path, [second], [out_s], "2026-10-14")
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generated"] == "2026-10-14"
    assert manifest["inputs"] == [first, second]
    assert manifest["outputs"] == [out_a, out_s]
    newer = dict(first, sha256="3" * 64)
    ct.update_manifest(tmp_path, [newer], [out_a], "2026-10-15")
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["inputs"] == [newer, second]
    assert len(manifest["outputs"]) == 2


def test_update_manifest_refuses_to_overwrite_a_manifest_it_cannot_read(tmp_path):
    (tmp_path / "manifest.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest"):
        ct.update_manifest(tmp_path, [], [], "2026-10-13")
    assert (tmp_path / "manifest.json").read_text(encoding="utf-8") == "{ not json"


def test_read_checked_returns_the_record_and_what_the_reader_returned(tmp_path):
    client = make_client(tmp_path / "client")
    record, result = ct.read_checked(client, ct.ZONES_FILE, ct.read_zones)
    assert record == ct.input_record(client, ct.ZONES_FILE)
    assert result["flagged_count"] == 2  # zones 1 and 64


def test_read_checked_refuses_a_file_that_changes_while_it_is_read(tmp_path):
    client = make_client(tmp_path / "client")

    def reader_that_races_a_patch(path):
        data = ct.read_zones(path)
        write_text(path, ZONES_TEXT + crlf("9^New Zone^12^60"))  # the launcher rewrites the file
        return data

    with pytest.raises(ValueError, match="changed while"):
        ct.read_checked(client, ct.ZONES_FILE, reader_that_races_a_patch)


@pytest.mark.parametrize("text", ["2026-10-13", "2024-02-29"])
def test_iso_date_accepts_a_calendar_date(text):
    assert ct.iso_date(text) == text


@pytest.mark.parametrize(
    "text",
    ["2026-13-40", "13/10/2026", "20261013", "2026-10-13T00:00", "2026-2-3", "2026-W41-2", ""],
)
def test_iso_date_refuses_anything_else(text):
    with pytest.raises(argparse.ArgumentTypeError):
        ct.iso_date(text)


# ---- the command line -------------------------------------------------------------------------


def run_cli(client: Path, out: Path, *extra: str) -> int:
    return ct.main(["--client-dir", str(client), "--out", str(out), "--date", "2026-10-13", *extra])


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_cli_writes_the_four_tables_and_the_manifest(tmp_path, capsys):
    client = make_client(tmp_path / "client")
    out = tmp_path / "out" / "client"
    assert run_cli(client, out) == 0
    assert sorted(path.name for path in out.iterdir()) == [
        "acmitigation.json",
        "basedata.json",
        "manifest.json",
        "skillcaps.json",
        "zones.json",
    ]
    zones = load(out / "zones.json")
    assert zones["flagged_count"] == 2 and len(zones["zones"]) == 4  # adapted: the fixture gained two rows
    assert load(out / "acmitigation.json")["rows"][0]["ac_cap"] == 392
    assert load(out / "basedata.json")["rows"][1]["hp"] == 1440.0
    assert load(out / "skillcaps.json")["rows"] == [{"class": 1, "skill": 0, "level": 50, "cap": 200}]
    assert "flagged" in capsys.readouterr().out


def test_every_derived_file_carries_provenance_with_the_input_hash(tmp_path):
    client = make_client(tmp_path / "client")
    out = tmp_path / "out"
    assert run_cli(client, out) == 0
    for table, name in (
        ("zones.json", ct.ZONES_FILE),
        ("basedata.json", ct.BASEDATA_FILE),
        ("acmitigation.json", ct.ACMITIGATION_FILE),
        ("skillcaps.json", ct.SKILLCAPS_FILE),
    ):
        text, (year, month, day) = FAKE_FILES[name]
        assert load(out / table)["provenance"] == {
            "inputs": [
                {
                    "file": name,
                    "sha256": hashlib.sha256(text.encode("latin-1")).hexdigest(),
                    "date": f"{year:04d}-{month:02d}-{day:02d}",
                }
            ],
            "generator": f"trioforge.sources.client_tables {trioforge.__version__}",
            "generated": "2026-10-13",
        }


def test_the_manifest_records_each_input_hash_and_which_outputs_use_it(tmp_path):
    client = make_client(tmp_path / "client")
    out = tmp_path / "out"
    assert run_cli(client, out) == 0
    manifest = load(out / "manifest.json")
    assert manifest["generated"] == "2026-10-13"
    assert [item["file"] for item in manifest["inputs"]] == sorted(FAKE_FILES)
    for item in manifest["inputs"]:
        assert re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["date"])
    assert {entry["file"]: entry["inputs"] for entry in manifest["outputs"]} == {
        "zones.json": [ct.ZONES_FILE],
        "basedata.json": [ct.BASEDATA_FILE],
        "acmitigation.json": [ct.ACMITIGATION_FILE],
        "skillcaps.json": [ct.SKILLCAPS_FILE],
    }


def test_no_derived_file_names_a_local_path(tmp_path):
    client = make_client(tmp_path / "client")
    out = tmp_path / "out"
    assert run_cli(client, out) == 0
    for path in out.iterdir():
        text = path.read_text(encoding="utf-8")
        assert str(tmp_path) not in text and tmp_path.as_posix() not in text
        assert not re.search(r"[A-Za-z]:[\\/]", text), path.name
        assert "\\\\" not in text, path.name


def test_the_cli_output_is_byte_for_byte_repeatable(tmp_path):
    client = make_client(tmp_path / "client")
    assert run_cli(client, tmp_path / "one") == 0
    assert run_cli(client, tmp_path / "two") == 0
    for path in (tmp_path / "one").iterdir():
        assert path.read_bytes() == (tmp_path / "two" / path.name).read_bytes()


def test_a_missing_input_file_stops_the_cli_with_exit_2_before_it_writes_anything(tmp_path, capsys):
    client = make_client(tmp_path / "client")
    (client / ct.SKILLCAPS_FILE).unlink()
    out = tmp_path / "out"
    assert run_cli(client, out) == 2
    assert ct.SKILLCAPS_FILE in capsys.readouterr().err
    assert not out.exists() or not list(out.iterdir())


def test_a_malformed_table_stops_the_cli_with_exit_2_and_no_partial_output(tmp_path, capsys):
    client = make_client(tmp_path / "client")
    write_text(client / ct.ACMITIGATION_FILE, crlf("3^50^x^0.33^"))
    out = tmp_path / "out"
    assert run_cli(client, out) == 2
    assert "ACMitigation" in capsys.readouterr().err
    assert not out.exists() or not list(out.iterdir())


def test_the_cli_without_a_client_folder_says_what_to_set(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv(ct.ENV_CLIENT_DIR, raising=False)
    monkeypatch.delenv("PUBLIC", raising=False)
    assert ct.main(["--out", str(tmp_path / "out")]) == 2
    assert ct.ENV_CLIENT_DIR in capsys.readouterr().err


def test_without_a_date_argument_the_run_date_is_today_in_utc(tmp_path):
    # the run date is the UTC date, whatever the machine's time zone
    client = make_client(tmp_path / "client")
    now = datetime.timezone.utc
    before = datetime.datetime.now(now).date().isoformat()
    assert ct.main(["--client-dir", str(client), "--out", str(tmp_path / "out")]) == 0
    after = datetime.datetime.now(now).date().isoformat()
    assert load(tmp_path / "out" / "zones.json")["provenance"]["generated"] in {before, after}


def test_the_default_run_date_comes_from_today_utc(tmp_path, monkeypatch):
    client = make_client(tmp_path / "client")
    monkeypatch.setattr(ct, "today_utc", lambda: "2031-02-03")
    assert ct.main(["--client-dir", str(client), "--out", str(tmp_path / "out")]) == 0
    assert load(tmp_path / "out" / "zones.json")["provenance"]["generated"] == "2031-02-03"
    assert load(tmp_path / "out" / "manifest.json")["generated"] == "2031-02-03"


def test_a_bad_date_argument_is_refused(tmp_path):
    client = make_client(tmp_path / "client")
    with pytest.raises(SystemExit) as stopped:
        ct.main(["--client-dir", str(client), "--out", str(tmp_path / "out"), "--date", "13/10/2026"])
    assert stopped.value.code == 2


# ---- fail closed on bad input ------------------------------------------------------------------

HEADER = "#CLASS^LVL^AC_CAP^SOFT_CAP_MULTIPLIER^"
READERS = {
    "zones": ct.read_zones,
    "basedata": ct.read_basedata,
    "acmitigation": ct.read_acmitigation,
    "skillcaps": ct.read_skillcaps,
}
KINDS = list(READERS)
GOOD_ROW = {
    "zones": "1^South Qeynos^12^60",
    "basedata": "50^2^1320^900^456^7^13^4.4^4.5^3.250^",
    "acmitigation": "3^50^392^0.33^",
    "skillcaps": "1^0^50^200^0^",
}


def table_path(tmp_path: Path, kind: str, *lines: str) -> Path:
    """A synthetic table file; the ACMitigation header comes first where the table needs it."""
    head = [HEADER] if kind == "acmitigation" else []
    return write_text(tmp_path / "table.txt", crlf(*head, *lines))


def first_row_line(kind: str) -> int:
    return 2 if kind == "acmitigation" else 1  # the header is line 1


def rows_of(table: dict) -> list:
    return table["zones"] if "zones" in table else table["rows"]


@pytest.mark.parametrize("junk", ["junk", "SECRETWORD^junk", "7 SECRETWORD", "SECRETWORD"])
@pytest.mark.parametrize("kind", KINDS)
def test_a_line_that_fits_no_row_is_an_error_naming_the_line_but_not_showing_it(tmp_path, kind, junk):
    path = table_path(tmp_path, kind, GOOD_ROW[kind], junk)
    with pytest.raises(ValueError, match=rf"line {first_row_line(kind) + 1}\b") as caught:
        READERS[kind](path)
    assert "SECRETWORD" not in str(caught.value) and "junk" not in str(caught.value)


@pytest.mark.parametrize("kind", KINDS)
def test_only_blank_and_hash_lines_are_skipped(tmp_path, kind):
    path = table_path(tmp_path, kind, "", "# a note", GOOD_ROW[kind], "   ", "#another note")
    assert len(rows_of(READERS[kind](path))) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_a_byte_above_127_anywhere_is_an_error_naming_the_line(tmp_path, kind):
    path = table_path(tmp_path, kind, GOOD_ROW[kind])
    path.write_bytes(path.read_bytes() + b"# caf\xe9\r\n")  # even a comment must be plain ASCII
    with pytest.raises(ValueError, match=rf"line {first_row_line(kind) + 1}\b.*ASCII") as caught:
        READERS[kind](path)
    assert "caf" not in str(caught.value)


@pytest.mark.parametrize("kind", KINDS)
def test_every_reader_drops_a_leading_byte_order_mark(tmp_path, kind):
    path = table_path(tmp_path, kind, GOOD_ROW[kind])
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert len(rows_of(READERS[kind](path))) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_a_row_with_an_extra_column_is_an_error(tmp_path, kind):
    path = table_path(tmp_path, kind, GOOD_ROW[kind].rstrip("^") + "^7")
    with pytest.raises(ValueError, match=rf"line {first_row_line(kind)}\b.*columns"):
        READERS[kind](path)


@pytest.mark.parametrize("kind", KINDS)
def test_a_row_one_column_short_is_an_error(tmp_path, kind):
    short = GOOD_ROW[kind].rstrip("^").rsplit("^", 1)[0]
    with pytest.raises(ValueError, match=rf"line {first_row_line(kind)}\b.*columns"):
        READERS[kind](table_path(tmp_path, kind, short))


@pytest.mark.parametrize("kind", ["basedata", "acmitigation", "skillcaps"])
def test_one_closing_caret_is_allowed_and_two_are_not(tmp_path, kind):
    bare = GOOD_ROW[kind].rstrip("^")
    for row in (bare, bare + "^"):
        assert len(READERS[kind](table_path(tmp_path, kind, row))["rows"]) == 1
    with pytest.raises(ValueError, match="columns"):
        READERS[kind](table_path(tmp_path, kind, bare + "^^"))


def test_a_zone_row_may_not_end_in_a_caret(tmp_path):
    with pytest.raises(ValueError, match=r"line 1\b.*columns"):
        ct.read_zones(table_path(tmp_path, "zones", GOOD_ROW["zones"] + "^"))


@pytest.mark.parametrize(
    "text",
    [
        crlf(HEADER, "3^50^392^0.33^"),
        crlf(HEADER.rstrip("^"), "3^50^392^0.33^"),
        crlf("", HEADER, "3^50^392^0.33^"),
        crlf(HEADER, "# a comment after the header", "3^50^392^0.33^"),
    ],
    ids=["header", "header-without-the-closing-caret", "blank-line-first", "comment-after-the-header"],
)
def test_acmitigation_accepts_its_header(tmp_path, text):
    assert len(ct.read_acmitigation(write_text(tmp_path / "a.txt", text))["rows"]) == 1


@pytest.mark.parametrize(
    "text",
    [
        crlf("3^50^392^0.33^"),
        crlf("#CLASS^LEVEL^AC_CAP^SOFT_CAP_MULTIPLIER^", "3^50^392^0.33^"),
        crlf("#class^lvl^ac_cap^soft_cap_multiplier^", "3^50^392^0.33^"),
        crlf("#CLASS^LVL^AC_CAP^SOFT_CAP_MULTIPLIER^EXTRA^", "3^50^392^0.33^"),
        crlf("#CLASS^LVL^AC_CAP", "3^50^392^0.33^"),
        crlf("3^50^392^0.33^", HEADER),
        crlf("# a note first", HEADER, "3^50^392^0.33^"),
    ],
    ids=["no-header", "renamed-column", "lowercase", "extra-column", "short-header", "header-after-row", "note-first"],
)
def test_acmitigation_without_its_exact_header_first_is_an_error(tmp_path, text):
    with pytest.raises(ValueError, match=r"line 1\b.*header"):
        ct.read_acmitigation(write_text(tmp_path / "a.txt", text))


DUPLICATE_ROWS = {
    "zones": ("1^South Qeynos^12^60", "1^Another Name^0^0"),
    "basedata": ("50^2^1320^900^456^7^13^4.4^4.5^3.250^", "50^2^1^1^1^1^1^1^1^1^"),
    "acmitigation": ("3^50^392^0.33^", "3^50^1^0.5^"),
    "skillcaps": ("1^0^50^200^0^", "1^0^50^201^0^"),
}
DUPLICATE_ROWS_ABOVE_LEVEL_60 = {
    "basedata": ("100^2^1^1^1^1^1^1^1^1^", "100^2^2^2^2^2^2^2^2^2^"),
    "acmitigation": ("3^100^392^0.33^", "3^100^1^0.5^"),
    "skillcaps": ("1^0^100^200^0^", "1^0^100^201^0^"),
}


@pytest.mark.parametrize("kind", KINDS)
def test_a_repeated_key_is_an_error_naming_the_second_line(tmp_path, kind):
    first, second = DUPLICATE_ROWS[kind]
    with pytest.raises(ValueError, match=rf"line {first_row_line(kind) + 1}\b.*duplicate"):
        READERS[kind](table_path(tmp_path, kind, first, second))


def test_rows_that_differ_in_any_part_of_the_key_are_not_duplicates(tmp_path):
    basedata = [f"{level}^{klass}^1^1^1^1^1^1^1^1^" for level, klass in ((50, 2), (50, 3), (51, 2))]
    assert len(ct.read_basedata(table_path(tmp_path, "basedata", *basedata))["rows"]) == 3
    ac = [f"{klass}^{level}^1^0.5^" for klass, level in ((3, 50), (3, 51), (4, 50))]
    assert len(ct.read_acmitigation(table_path(tmp_path, "acmitigation", *ac))["rows"]) == 3
    caps = [f"{klass}^{skill}^{level}^1^0^" for klass, skill, level in ((1, 0, 50), (2, 0, 50), (1, 1, 50), (1, 0, 51))]
    assert len(ct.read_skillcaps(table_path(tmp_path, "skillcaps", *caps))["rows"]) == 4
    assert len(ct.read_zones(table_path(tmp_path, "zones", "1^A^0^0", "2^A^0^0"))["zones"]) == 2  # names may repeat


OUT_OF_RANGE_ROWS = [
    pytest.param("zones", "-1^A^0^0", id="zone-id-negative"),
    pytest.param("zones", "1^A^-1^0", id="c3-negative"),
    pytest.param("zones", "1^A^0^-1", id="c4-negative"),
    pytest.param("basedata", "50^0^1320^900^456^7^13^4.4^4.5^3.250^", id="basedata-class-0"),
    pytest.param("basedata", "50^17^1320^900^456^7^13^4.4^4.5^3.250^", id="basedata-class-17"),
    pytest.param("basedata", "0^2^1320^900^456^7^13^4.4^4.5^3.250^", id="basedata-level-0"),
    pytest.param("basedata", "131^2^1320^900^456^7^13^4.4^4.5^3.250^", id="basedata-level-131"),
    pytest.param("basedata", "50^2^-1^900^456^7^13^4.4^4.5^3.250^", id="basedata-negative-pool"),
    pytest.param("basedata", "50^2^1320^900^456^7^13^-0.1^4.5^3.250^", id="basedata-negative-factor"),
    pytest.param("basedata", "50^2^" + "9" * 400 + "^900^456^7^13^4.4^4.5^3.250^", id="basedata-too-big-for-a-number"),
    pytest.param("acmitigation", "0^50^392^0.33^", id="acmitigation-class-0"),
    pytest.param("acmitigation", "17^50^392^0.33^", id="acmitigation-class-17"),
    pytest.param("acmitigation", "3^0^392^0.33^", id="acmitigation-level-0"),
    pytest.param("acmitigation", "3^131^392^0.33^", id="acmitigation-level-131"),
    pytest.param("acmitigation", "3^50^-1^0.33^", id="acmitigation-negative-cap"),
    pytest.param("acmitigation", "3^50^392^-0.33^", id="acmitigation-negative-rate"),
    pytest.param("skillcaps", "0^0^50^200^0^", id="skillcaps-class-0"),
    pytest.param("skillcaps", "17^0^50^200^0^", id="skillcaps-class-17"),
    pytest.param("skillcaps", "1^0^0^200^0^", id="skillcaps-level-0"),
    pytest.param("skillcaps", "1^0^131^200^0^", id="skillcaps-level-131"),
    pytest.param("skillcaps", "1^-1^50^200^0^", id="skillcaps-negative-skill"),
    pytest.param("skillcaps", "1^0^50^-1^0^", id="skillcaps-negative-cap"),
]


@pytest.mark.parametrize(("kind", "row"), OUT_OF_RANGE_ROWS)
def test_a_value_out_of_range_is_an_error_naming_the_line(tmp_path, kind, row):
    path = table_path(tmp_path, kind, GOOD_ROW[kind], row)
    with pytest.raises(ValueError, match=rf"line {first_row_line(kind) + 1}\b.*out of range"):
        READERS[kind](path)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("lines", [[], [""], ["# only a note"]], ids=["empty-file", "blank-line", "only-a-comment"])
def test_a_table_with_no_data_rows_is_an_error(tmp_path, kind, lines):
    with pytest.raises(ValueError, match="no data rows"):
        READERS[kind](table_path(tmp_path, kind, *lines))


def test_a_reader_can_be_told_how_many_rows_a_whole_table_has(tmp_path):
    path = table_path(tmp_path, "zones", "1^A^0^0", "2^B^0^0")
    assert len(ct.read_zones(path, minimum_rows=2)["zones"]) == 2
    with pytest.raises(ValueError, match="only 2 data rows"):
        ct.read_zones(path, minimum_rows=3)


def test_the_row_floor_counts_the_rows_read_not_the_rows_kept(tmp_path):
    lines = [f"{level}^1^100^10^50^2^5^0.5^0.1^0.1^" for level in (59, 61, 130)]
    path = table_path(tmp_path, "basedata", *lines)
    assert [row["level"] for row in ct.read_basedata(path, minimum_rows=3)["rows"]] == [59]
    with pytest.raises(ValueError, match="only 3 data rows"):
        ct.read_basedata(path, minimum_rows=4)


def many_rows(kind: str, count: int) -> list[str]:
    """``count`` valid, distinct rows of a table; basedata and the others run up to level 130."""
    if kind == "zones":
        return [f"{n}^Test Zone {n}^0^0" for n in range(1, count + 1)]
    if kind == "basedata":
        keys = itertools.product(range(1, 131), range(1, 17))  # level, class
        return [f"{level}^{klass}^100^10^50^2^5^0.5^0.1^0.1^" for level, klass in itertools.islice(keys, count)]
    if kind == "acmitigation":
        keys = itertools.product(range(1, 17), range(1, 131))  # class, level
        return [f"{klass}^{level}^312^0.35^" for klass, level in itertools.islice(keys, count)]
    keys = itertools.product(range(1, 17), range(0, 80), range(1, 131))  # class, skill, level
    return [f"{klass}^{skill}^{level}^50^0^" for klass, skill, level in itertools.islice(keys, count)]


def test_the_row_floors_are_the_planned_numbers():
    assert REAL_FLOORS == {"zones": 600, "basedata": 1000, "acmitigation": 1000, "skillcaps": 10000, "spells": 200}


@pytest.mark.parametrize("kind", KINDS)
def test_a_table_below_its_floor_stops_the_cli_and_a_table_at_the_floor_passes(tmp_path, monkeypatch, capsys, kind):
    monkeypatch.setitem(ct.MINIMUM_ROWS, kind, REAL_FLOORS[kind])
    resource = {
        "zones": ct.ZONES_FILE,
        "basedata": ct.BASEDATA_FILE,
        "acmitigation": ct.ACMITIGATION_FILE,
        "skillcaps": ct.SKILLCAPS_FILE,
    }[kind]
    head = [HEADER] if kind == "acmitigation" else []
    client = make_client(tmp_path / "client")
    out = tmp_path / "out"
    write_text(client / resource, crlf(*head, *many_rows(kind, REAL_FLOORS[kind] - 1)))
    assert run_cli(client, out) == 2
    assert Path(resource).name in capsys.readouterr().err
    assert not out.exists()
    write_text(client / resource, crlf(*head, *many_rows(kind, REAL_FLOORS[kind])))
    assert run_cli(client, out) == 0


# ---- the scope of the derived tables ----------------------------------------------------------

LEVEL_ROW = {
    "basedata": "{level}^1^100^10^50^2^5^0.5^0.1^0.1^",
    "acmitigation": "1^{level}^312^0.35^",
    "skillcaps": "1^0^{level}^50^0^",
}
LEVELLED = list(LEVEL_ROW)


def at_levels(kind: str, *levels: int) -> list[str]:
    return [LEVEL_ROW[kind].format(level=level) for level in levels]


@pytest.mark.parametrize("kind", LEVELLED)
def test_only_levels_up_to_60_are_kept(tmp_path, kind):
    path = table_path(tmp_path, kind, *at_levels(kind, 1, 59, 60, 61, 130))
    assert [row["level"] for row in READERS[kind](path)["rows"]] == [1, 59, 60]


@pytest.mark.parametrize("kind", LEVELLED)
def test_the_level_limit_is_a_keyword_and_60_is_the_default(tmp_path, kind):
    assert ct.MAX_TABLE_LEVEL == 60
    path = table_path(tmp_path, kind, *at_levels(kind, 1, 60, 61, 130))
    assert [row["level"] for row in READERS[kind](path, max_level=130)["rows"]] == [1, 60, 61, 130]
    assert [row["level"] for row in READERS[kind](path, max_level=1)["rows"]] == [1]


@pytest.mark.parametrize("kind", LEVELLED)
def test_rows_above_the_limit_are_checked_before_they_are_dropped(tmp_path, kind):
    first, second = DUPLICATE_ROWS_ABOVE_LEVEL_60[kind]
    with pytest.raises(ValueError, match="duplicate"):
        READERS[kind](table_path(tmp_path, kind, first, second))
    bad_class = {
        "basedata": "100^17^1^1^1^1^1^1^1^1^",
        "acmitigation": "17^100^392^0.33^",
        "skillcaps": "17^0^100^200^0^",
    }[kind]
    with pytest.raises(ValueError, match="out of range"):
        READERS[kind](table_path(tmp_path, kind, GOOD_ROW[kind], bad_class))


def test_zones_keep_id_name_c3_c4_and_flagged_for_every_row(tmp_path):
    path = table_path(tmp_path, "zones", "1^A^12^60", "999^B^0^0")
    zones = ct.read_zones(path)["zones"]
    assert [sorted(zone) for zone in zones] == [["c3", "c4", "flagged", "id", "name"]] * 2


def test_the_cli_writes_no_row_above_level_60(tmp_path):
    client = make_client(tmp_path / "client")
    write_text(client / ct.BASEDATA_FILE, crlf(*at_levels("basedata", 1, 60, 61, 130)))
    write_text(client / ct.ACMITIGATION_FILE, crlf(HEADER, *at_levels("acmitigation", 1, 60, 61, 130)))
    write_text(client / ct.SKILLCAPS_FILE, crlf(*at_levels("skillcaps", 1, 60, 61, 130)))
    out = tmp_path / "out"
    assert run_cli(client, out) == 0
    for name in ("basedata.json", "acmitigation.json", "skillcaps.json"):
        assert [row["level"] for row in load(out / name)["rows"]] == [1, 60], name


# ---- atomic output ------------------------------------------------------------------------------


def snapshot(folder: Path) -> dict[str, bytes]:
    """Every file in a folder by name, with its bytes (a leftover temporary file would show up)."""
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir()) if path.is_file()}


def first_run(tmp_path: Path):
    client = make_client(tmp_path / "client")
    out = tmp_path / "out"
    assert run_cli(client, out) == 0
    return client, out, snapshot(out)


def test_a_rerun_replaces_every_file_and_leaves_no_temporary_file(tmp_path):
    client, out, before = first_run(tmp_path)
    assert run_cli(client, out, "--date", "2026-10-14") == 0
    after = snapshot(out)
    assert sorted(after) == sorted(before)
    assert all(after[name] != before[name] for name in after)  # the date is in every file


def test_the_manifest_is_put_in_place_last(tmp_path, monkeypatch):
    real_replace = os.replace
    targets: list[str] = []

    def recording_replace(source, target):
        targets.append(Path(target).name)
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", recording_replace)
    assert run_cli(make_client(tmp_path / "client"), tmp_path / "out") == 0
    assert targets[-1] == "manifest.json"
    assert sorted(targets[:-1]) == ["acmitigation.json", "basedata.json", "skillcaps.json", "zones.json"]


INVALID_MANIFESTS = {
    "not-json": "{ not json",
    "not-an-object": "[]",
    "inputs-not-a-list": '{"inputs": 5, "outputs": []}',
    "outputs-missing": '{"inputs": []}',
    "input-without-a-hash": '{"inputs": [{"file": "a"}], "outputs": []}',
    "input-hash-not-hex": '{"inputs": [{"file": "a", "sha256": "zz", "date": "2026-05-11"}], "outputs": []}',
    "input-date-not-a-date": '{"inputs": [{"file": "a", "sha256": "%s", "date": "May 11"}], "outputs": []}'
    % ("1" * 64),
    "repeated-input": '{"inputs": [{"file": "a", "sha256": "%s", "date": "2026-05-11"}, '
    '{"file": "a", "sha256": "%s", "date": "2026-05-12"}], "outputs": []}' % ("1" * 64, "2" * 64),
    "output-inputs-not-a-list": '{"inputs": [], "outputs": '
    '[{"file": "a.json", "inputs": "a", "generated": "2026-10-13"}]}',
    "output-without-a-date": '{"inputs": [], "outputs": [{"file": "a.json", "inputs": ["a"]}]}',
}


@pytest.mark.parametrize("text", list(INVALID_MANIFESTS.values()), ids=list(INVALID_MANIFESTS))
def test_update_manifest_refuses_a_manifest_that_is_not_valid_and_leaves_it_alone(tmp_path, text):
    (tmp_path / "manifest.json").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="manifest"):
        ct.update_manifest(tmp_path, [], [], "2026-10-13")
    assert (tmp_path / "manifest.json").read_text(encoding="utf-8") == text


@pytest.mark.parametrize("text", list(INVALID_MANIFESTS.values()), ids=list(INVALID_MANIFESTS))
def test_an_invalid_manifest_stops_the_cli_before_any_file_is_touched(tmp_path, capsys, text):
    client, out, _ = first_run(tmp_path)
    (out / "manifest.json").write_text(text, encoding="utf-8")
    before = snapshot(out)
    write_text(client / ct.ZONES_FILE, ZONES_TEXT + crlf("9^New Zone^12^60"))
    capsys.readouterr()
    assert run_cli(client, out, "--date", "2026-10-14") == 2
    assert "manifest" in capsys.readouterr().err
    assert snapshot(out) == before


def test_a_manifest_that_is_a_folder_stops_the_cli_before_any_file_is_touched(tmp_path, capsys):
    client, out, _ = first_run(tmp_path)
    (out / "manifest.json").unlink()
    (out / "manifest.json").mkdir()
    before = snapshot(out)
    capsys.readouterr()
    assert run_cli(client, out, "--date", "2026-10-14") == 2
    assert "manifest" in capsys.readouterr().err
    assert snapshot(out) == before and (out / "manifest.json").is_dir()


def test_a_failure_while_rendering_leaves_the_old_files_alone(tmp_path, monkeypatch, capsys):
    client, out, before = first_run(tmp_path)
    real_render = ct.render_json
    calls: list[int] = []

    def fail_on_the_manifest(data):
        calls.append(1)
        if len(calls) == 5:  # four tables, then the manifest: the last text to be made
            raise ValueError("cannot render")
        return real_render(data)

    monkeypatch.setattr(ct, "render_json", fail_on_the_manifest)
    capsys.readouterr()
    assert run_cli(client, out, "--date", "2026-10-14") == 2
    assert "cannot render" in capsys.readouterr().err
    assert snapshot(out) == before


def test_a_failure_while_putting_the_files_in_place_puts_the_old_ones_back(tmp_path, monkeypatch, capsys):
    client, out, before = first_run(tmp_path)
    real_replace = os.replace
    calls: list[str] = []

    def lock_the_third(source, target):
        calls.append(Path(target).name)
        if len(calls) == 3:
            raise PermissionError("locked by another program")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", lock_the_third)
    capsys.readouterr()
    assert run_cli(client, out, "--date", "2026-10-14") == 2
    assert "locked by another program" in capsys.readouterr().err
    assert snapshot(out) == before


def test_a_file_that_cannot_be_replaced_leaves_the_others_as_they_were(tmp_path, capsys):
    client, out, before = first_run(tmp_path)
    (out / "skillcaps.json").unlink()
    (out / "skillcaps.json").mkdir()  # a folder where the last table belongs: it cannot be replaced
    kept = snapshot(out)
    capsys.readouterr()
    assert run_cli(client, out, "--date", "2026-10-14") == 2
    assert capsys.readouterr().err.startswith("error: ")
    assert snapshot(out) == kept
    assert (out / "skillcaps.json").is_dir()
    assert set(kept) == set(before) - {"skillcaps.json"}


def test_write_json_leaves_the_old_file_whole_when_the_new_text_cannot_be_made(tmp_path):
    path = tmp_path / "out.json"
    ct.write_json(path, {"a": 1})
    before = path.read_bytes()
    with pytest.raises(ValueError):
        ct.write_json(path, {"a": float("nan")})
    assert path.read_bytes() == before
    assert sorted(item.name for item in tmp_path.iterdir()) == ["out.json"]


# ---- the command line's errors -----------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [PermissionError("denied\nin two lines"), ValueError("bad\nthing"), OSError("device gone"), FileNotFoundError("x")],
    ids=["permission-error", "value-error", "os-error", "file-not-found"],
)
def test_any_os_or_value_error_ends_the_cli_with_exit_2_and_a_one_line_message(tmp_path, monkeypatch, capsys, error):
    client = make_client(tmp_path / "client")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(ct, "read_checked", fail)
    assert run_cli(client, tmp_path / "out") == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and err.count("\n") == 1


def test_an_output_folder_that_is_a_file_ends_the_cli_with_exit_2(tmp_path, capsys):
    client = make_client(tmp_path / "client")
    out = tmp_path / "out"
    out.write_text("not a folder", encoding="utf-8")
    assert run_cli(client, out) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and err.count("\n") == 1
    assert out.read_text(encoding="utf-8") == "not a folder"


def test_a_bad_line_stops_the_cli_with_its_number_and_never_its_text(tmp_path, capsys):
    client = make_client(tmp_path / "client")
    write_text(client / ct.ZONES_FILE, ZONES_TEXT + crlf("SECRETWORD^junk"))
    assert run_cli(client, tmp_path / "out") == 2
    err = capsys.readouterr().err
    assert "line 5" in err and "SECRETWORD" not in err and not (tmp_path / "out").exists()


# ---- the committed files and the install ------------------------------------------------------


def stale_extract_message(manifest: dict, client_dir: Path) -> str | None:
    """None when every input the manifest lists is in the install with the recorded sha256; else
    the message that says the extract is stale and names the files."""
    stale = []
    for item in manifest["inputs"]:
        path = client_dir / item["file"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            stale.append(item["file"])
    if not stale:
        return None
    return (
        "stale extract: derived/client/manifest.json was made from other client files than the "
        "installed ones (" + ", ".join(stale) + "); run the client_tables and client_spells extracts "
        "again and commit the derived files"
    )


def test_a_stale_extract_is_reported_with_the_files_that_changed(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"one")
    (tmp_path / "b.txt").write_bytes(b"two")
    manifest = {
        "inputs": [
            {"file": "a.txt", "sha256": hashlib.sha256(b"one").hexdigest(), "date": "2026-10-13"},
            {"file": "b.txt", "sha256": hashlib.sha256(b"two").hexdigest(), "date": "2026-10-13"},
        ]
    }
    assert stale_extract_message(manifest, tmp_path) is None
    (tmp_path / "b.txt").write_bytes(b"patched")
    message = stale_extract_message(manifest, tmp_path)
    assert message is not None and message.startswith("stale extract") and "b.txt" in message and "a.txt" not in message
    (tmp_path / "b.txt").unlink()
    assert "b.txt" in stale_extract_message(manifest, tmp_path)


def test_the_committed_derived_files_agree_with_their_manifest():
    manifest = load(COMMITTED_CLIENT_FILES / "manifest.json")
    inputs = {item["file"]: item for item in manifest["inputs"]}
    outputs = {item["file"]: item for item in manifest["outputs"]}
    derived = sorted(path.name for path in COMMITTED_CLIENT_FILES.glob("*.json") if path.name != "manifest.json")
    assert sorted(outputs) == derived
    for name in derived:
        provenance = load(COMMITTED_CLIENT_FILES / name)["provenance"]
        assert [record["file"] for record in provenance["inputs"]] == outputs[name]["inputs"], name
        assert all(record == inputs[record["file"]] for record in provenance["inputs"]), name
        assert provenance["generated"] == outputs[name]["generated"], name


@real_client
def test_the_committed_manifest_matches_the_installed_files():
    manifest = load(COMMITTED_CLIENT_FILES / "manifest.json")
    message = stale_extract_message(manifest, CLIENT_DIR)
    if message is not None:
        pytest.fail(message, pytrace=False)


# ---- the real client --------------------------------------------------------------------------


@real_client
def test_the_real_zone_names_have_at_least_700_rows_and_exactly_78_flagged():
    data = ct.read_zones(CLIENT_DIR / ct.ZONES_FILE)
    assert len(data["zones"]) >= 700
    assert data["flagged_count"] == 78
    assert len({zone["id"] for zone in data["zones"]}) == len(data["zones"])


@real_client
def test_the_real_paladin_softcap_at_level_50_is_392():
    rows = ct.read_acmitigation(CLIENT_DIR / ct.ACMITIGATION_FILE)["rows"]
    (row,) = [r for r in rows if r["class"] == 3 and r["level"] == 50]
    assert row["ac_cap"] == 392
    assert row["past_cap_rate"] == 0.33
    assert len({(r["class"], r["level"]) for r in rows}) == len(rows)


@real_client
def test_every_real_class_has_a_level_50_basedata_row():
    rows = ct.read_basedata(CLIENT_DIR / ct.BASEDATA_FILE)["rows"]
    assert {r["class"] for r in rows if r["level"] == 50} == set(range(1, 17))
    assert len({(r["class"], r["level"]) for r in rows}) == len(rows)
    (warrior,) = [r for r in rows if r["class"] == 1 and r["level"] == 50]
    # the warrior's level-50 numbers come from the file's own text, by plain splitting, and are not
    # typed in here (a patch may change them)
    (raw,) = [
        fields
        for fields in (line.split("^") for line in (CLIENT_DIR / ct.BASEDATA_FILE).read_text("ascii").splitlines())
        if fields[0] == "50" and fields[1] == "1"
    ]
    assert (warrior["hp"], warrior["mana"], warrior["end"]) == (float(raw[2]), float(raw[3]), float(raw[4]))
    assert (warrior["hp_regen"], warrior["end_regen"]) == (float(raw[5]), float(raw[6]))
    assert (warrior["hp_fac"], warrior["mana_fac"], warrior["end_fac"]) == (float(raw[7]), float(raw[8]), float(raw[9]))


@real_client
def test_the_real_skill_caps_cover_every_class_and_the_defense_skill_at_level_50():
    data = ct.read_skillcaps(CLIENT_DIR / ct.SKILLCAPS_FILE)
    rows = data["rows"]
    assert len({(r["class"], r["skill"], r["level"]) for r in rows}) == len(rows)
    defense = {r["class"]: r["cap"] for r in rows if r["skill"] == 15 and r["level"] == 50}
    assert set(defense) == set(range(1, 17))
    assert all(0 < cap <= 500 for cap in defense.values())
    assert {int(skill) for skill in data["skill_names"]} <= {r["skill"] for r in rows}
