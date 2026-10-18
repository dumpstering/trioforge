"""Tests for strict JSON reading and one-record-per-line writing."""

import json

import pytest

from trioforge.data.jsonio import JsonFileError, load_strict, loads_strict, render


@pytest.mark.parametrize(
    ("text", "mention"),
    [
        ('{"a": 1, "a": 2}', "repeats a key"),
        ('{"outer": {"a": 1, "b": 2, "a": 3}}', "repeats a key"),
        ('[{"a": 1}, {"b": 1, "b": 1}]', "repeats a key"),
        ('{"a": NaN}', "NaN"),
        ('{"a": Infinity}', "Infinity"),
        ('{"a": -Infinity}', "Infinity"),
        ("{'a': 1}", "not valid JSON"),
        ("", "not valid JSON"),
        ('{"a": 1,}', "not valid JSON"),
        pytest.param("[" * 100_000, "cannot be read", id="nesting"),
    ],
)
def test_bad_json_is_refused_with_a_message_that_names_the_file_not_the_content(text, mention):
    with pytest.raises(JsonFileError) as caught:
        loads_strict(text, "rules.json")
    message = str(caught.value)
    assert message.startswith("rules.json: ") and mention in message
    assert "\n" not in message and (not text.strip() or text.strip()[:20] not in message)


def test_good_json_loads_as_json_does():
    assert loads_strict('{"a": [1, 2.5, "x", null, true], "b": {"c": "\\u00e9"}}') == {
        "a": [1, 2.5, "x", None, True],
        "b": {"c": "é"},
    }


def test_a_file_is_read_as_utf_8_without_a_byte_order_mark(tmp_path):
    path = tmp_path / "x.json"
    path.write_bytes('{"name": "café"}'.encode("utf-8"))
    assert load_strict(path) == {"name": "café"}
    path.write_bytes(b"\xef\xbb\xbf" + b'{"a": 1}')
    with pytest.raises(JsonFileError):
        load_strict(path)
    path.write_bytes(b'{"a": "\xff"}')
    with pytest.raises(JsonFileError, match="UTF-8"):
        load_strict(path)


def test_a_missing_file_is_an_os_error_not_a_json_error(tmp_path):
    with pytest.raises(OSError):
        load_strict(tmp_path / "nothing.json")


def test_render_writes_the_keys_in_order_and_the_named_lists_one_item_per_line():
    text = render({"version": "1", "items": [{"k": "a"}, {"k": "b"}], "empty": [], "more": [1, 2]}, per_line=("items", "empty"))
    assert text == (
        "{\n"
        ' "version": "1",\n'
        ' "items": [\n'
        '  {"k":"a"},\n'
        '  {"k":"b"}\n'
        " ],\n"
        ' "empty": [],\n'
        ' "more": [1,2]\n'
        "}\n"
    )
    assert json.loads(text) == {"version": "1", "items": [{"k": "a"}, {"k": "b"}], "empty": [], "more": [1, 2]}


def test_render_writes_a_named_dict_one_entry_per_line():
    text = render({"items": {"w1": {"title": "A"}, "w2": {"title": "B"}}, "last": 1}, per_line=("items",))
    assert text == '{\n "items": {\n  "w1":{"title":"A"},\n  "w2":{"title":"B"}\n },\n "last": 1\n}\n'
    assert json.loads(text)["items"]["w2"] == {"title": "B"}


def test_render_keeps_non_ascii_text_and_is_the_same_bytes_every_time():
    data = {"name": "café ’s", "items": [{"n": "中"}]}
    assert render(data, per_line=("items",)) == render(dict(data), per_line=("items",))
    assert "café ’s" in render(data) and "\\u" not in render(data)
    assert "\r" not in render(data)


@pytest.mark.parametrize("bad", ["\ud800", "a\udfffb", "\ud83d"])
def test_render_refuses_a_lone_surrogate_instead_of_writing_it(bad):
    for data in ({"name": bad}, {"items": [{"name": bad}]}, {"items": {bad: 1}}):
        with pytest.raises(ValueError, match="lone surrogate"):
            render(data, per_line=("items",))


def test_render_refuses_nan_and_keys_that_are_not_text():
    with pytest.raises(ValueError):
        render({"x": float("nan")})
    with pytest.raises(TypeError):
        render({1: "x"})
    with pytest.raises(TypeError):
        render({"items": {1: "x"}}, per_line=("items",))
