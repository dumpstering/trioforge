"""The sheet of icons: one PNG that holds the small pictures of the places and the items, how the tool packs it, and what the committed one is.

The tool needs Pillow, which the project does not require, so the tests that run it are skipped where it is missing (run them with a Python that has it). The last tests read
only the committed art with the standard library.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from test_art_process import ART, BLUE, CLEAR, CREAM, RED, art_process, needs_pillow, picture, png_pixels, write_source  # noqa: F401

from trioforge.site import art, itemicon

REPO = Path(__file__).resolve().parents[2]
GREEN = (30, 200, 30, 255)


def sheet_entry(**more):
    return {
        "kind": "sheet",
        "size": [2, 2],
        "columns": 2,
        "cells": {"a": {"source": "a.png"}, "b": {"source": "b.png"}, "c": {"source": "c.png"}},
        **more,
    }


def cells_of(rows_by_name: dict[str, list[list[tuple[int, int, int, int]]]]):
    return {name: picture(rows) for name, rows in rows_by_name.items()}


CELLS = {
    "a": [[RED, CLEAR], [CLEAR, RED]],
    "b": [[BLUE, BLUE], [CLEAR, CLEAR]],
    "c": [[CLEAR, GREEN], [GREEN, CLEAR]],
}


# ---- the tool: packing --------------------------------------------------------------------------------------------------------------------------


@needs_pillow
def test_a_sheet_packs_its_cells_in_rows_of_the_given_width_in_the_order_of_the_manifest():
    image, facts = art_process.make_sheet(sheet_entry(), cells_of(CELLS))
    assert image.size == (4, 4) and facts == {"w": 4, "h": 4, "frames": 1, "scale": 1}  # two columns of 2 x 2, two rows (the third cell starts the second row)
    assert image.getpixel((0, 0)) == RED and image.getpixel((1, 1)) == RED  # a
    assert image.getpixel((2, 0)) == BLUE and image.getpixel((3, 0)) == BLUE and image.getpixel((2, 1)) == CLEAR  # b
    assert image.getpixel((1, 2)) == GREEN and image.getpixel((0, 3)) == GREEN and image.getpixel((0, 2)) == CLEAR  # c, under a
    assert image.getpixel((2, 2)) == CLEAR and image.getpixel((3, 3)) == CLEAR  # nothing in the last place


@needs_pillow
def test_the_pictures_of_a_sheet_are_shrunk_to_their_true_size_and_keyed_and_a_wrong_size_names_the_cell():
    enlarged = {name: picture(rows, 4) for name, rows in CELLS.items()}
    image, facts = art_process.make_sheet(sheet_entry(), enlarged)
    assert image.size == (4, 4) and image.getpixel((2, 0)) == BLUE
    entry = sheet_entry(background="#f6e7bd")
    cream = {"a": picture([[CREAM, CREAM], [CREAM, RED]]), "b": picture([[CREAM, BLUE], [CREAM, CREAM]]), "c": picture([[CREAM, CREAM], [CREAM, GREEN]])}
    keyed, _ = art_process.make_sheet(entry, cream)
    assert keyed.getpixel((0, 0)) == CLEAR and keyed.getpixel((1, 1)) == RED and keyed.getpixel((3, 0)) == BLUE and keyed.getpixel((1, 3)) == GREEN
    wrong = {**cells_of(CELLS), "b": picture([[RED, BLUE, RED], [BLUE, RED, BLUE], [RED, BLUE, RED]])}
    with pytest.raises(art_process.ArtError, match="b: the true size is 3x3"):
        art_process.make_sheet(sheet_entry(), wrong)


@needs_pillow
@pytest.mark.parametrize(
    ("more", "message"),
    [
        ({"columns": 0}, "columns"),
        ({"columns": "2"}, "columns"),
        ({"cells": {}}, "cells"),
        ({"cells": {"Bad Name": {"source": "a.png"}}}, "small letters"),
        ({"cells": {"a": {}}}, "source"),
        ({"cells": {"a": {"source": "a.png"}, "b": {"source": "a.png/../b.png"}}}, "source"),
        ({"size": [2]}, "size"),
    ],
)
def test_a_bad_sheet_is_refused_with_its_reason(more, message):
    with pytest.raises(art_process.ArtError, match=message):
        art_process.make_sheet(sheet_entry(**more), cells_of(CELLS))


@needs_pillow
def test_a_sheet_may_keep_a_clear_gap_between_its_cells_so_that_no_neighbour_can_bleed_in():
    image, facts = art_process.make_sheet(sheet_entry(gap=2), cells_of(CELLS))
    assert image.size == (8, 8) and facts == {"w": 8, "h": 8, "frames": 1, "scale": 1}  # two columns of 2 + 2 and two rows of 2 + 2: the gap follows every cell
    assert image.getpixel((0, 0)) == RED and image.getpixel((1, 1)) == RED  # a
    assert image.getpixel((4, 0)) == BLUE and image.getpixel((5, 0)) == BLUE  # b, one pitch (4) to the right
    assert image.getpixel((1, 4)) == GREEN and image.getpixel((0, 5)) == GREEN  # c, one pitch below a
    gap = [(x, y) for y in range(8) for x in range(8) if x % 4 >= 2 or y % 4 >= 2]
    assert all(image.getpixel(point)[3] == 0 for point in gap)  # nothing in the gap
    for bad in (-1, "2", 1.5, True):
        with pytest.raises(art_process.ArtError, match="gap"):
            art_process.make_sheet(sheet_entry(gap=bad), cells_of(CELLS))


@needs_pillow
def test_the_stylesheet_of_a_sheet_with_a_gap_moves_by_a_cell_and_its_gap_and_draws_one_cell(tmp_path):
    source, out = tmp_path / "artist", tmp_path / "out"
    source.mkdir()
    for name, rows in CELLS.items():
        picture(rows, 3).save(source / f"{name}.png")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"assets": {"set": sheet_entry(palette=255, gap=2, scale=2)}}), encoding="utf-8")
    facts = art_process.process(manifest, source, out)
    assert facts["set"] == {"w": 8, "h": 8, "frames": 1, "scale": 1}
    css = (out / "art.css").read_text(encoding="utf-8")
    assert "width:calc(2px*var(--art-s,2)*var(--art-m,1));height:calc(2px*var(--art-s,2)*var(--art-m,1))" in css  # a cell is drawn at its own size
    assert "background-size:calc(8px*var(--art-s,2)*var(--art-m,1)) calc(8px*var(--art-s,2)*var(--art-m,1))" in css  # of a sheet that is as big as it is with its gaps
    assert "background-position:calc(var(--art-cx,0)*-4px*var(--art-s,2)*var(--art-m,1)) calc(var(--art-cy,0)*-4px*var(--art-s,2)*var(--art-m,1))" in css  # and each step is the pitch
    assert ".art-c{--art-cx:0;--art-cy:1}" in css


# ---- the tool: the palette ----------------------------------------------------------------------------------------------------------------------


def noisy(size: int = 24):
    """A picture of many colours, each a little off the one beside it: more than 255 of them, and nothing transparent but a corner."""
    image = art_process.Image.new("RGBA", (size, size))
    for y in range(size):
        for x in range(size):
            image.putpixel((x, y), ((x * 10) % 256, (y * 10) % 256, (x * 7 + y * 5) % 256, 255))
    image.putpixel((0, 0), CLEAR)
    return image


@needs_pillow
def test_a_picture_with_few_colours_is_written_with_a_palette_and_the_same_pixels():
    source = picture([[RED, BLUE, CLEAR], [GREEN, RED, BLUE]])
    indexed = art_process.to_indexed(source, 255, 0)
    assert indexed.mode == "P" and indexed.convert("RGBA").tobytes() == source.tobytes()  # lossless: every colour has its own entry, and the clear pixels are the clear colour


@needs_pillow
def test_a_picture_of_many_colours_is_cut_to_the_palette_and_the_error_stays_under_the_tolerance_or_the_tool_refuses():
    source = noisy()
    assert len({p for p in source.getdata() if p[3]}) > 255
    indexed = art_process.to_indexed(source, 255, 40)
    assert indexed.mode == "P" and len(indexed.getpalette()) // 3 <= 256
    back = indexed.convert("RGBA")
    assert back.getpixel((0, 0))[3] == 0  # (the corner stays clear)
    worst = max(max(abs(a - b) for a, b in zip(p, q)) for p, q in zip(source.getdata(), back.getdata()) if p[3])
    assert 0 < worst <= 40
    with pytest.raises(art_process.ArtError, match=r"tolerance"):
        art_process.to_indexed(source, 255, 0)  # the same picture with no error allowed does not fit 255 colours
    with pytest.raises(art_process.ArtError, match="palette"):
        art_process.to_indexed(source, 300, 40)  # a PNG palette has 256 entries, one of them for clear


@needs_pillow
def test_a_picture_with_half_clear_pixels_is_refused_for_a_palette():
    half = picture([[(10, 20, 30, 128), RED]])
    with pytest.raises(art_process.ArtError, match="partly transparent"):
        art_process.to_indexed(half, 255, 0)


def colour_type(path: Path) -> int:
    return path.read_bytes()[25]


@needs_pillow
def test_the_tool_writes_a_sheet_as_one_indexed_png_with_a_shared_rule_and_no_picture_for_a_cell(tmp_path):
    source, out = tmp_path / "artist", tmp_path / "out"
    source.mkdir()
    for name, rows in CELLS.items():
        picture(rows, 3).save(source / f"{name}.png")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"assets": {"set": sheet_entry(palette=255, tolerance=0, scale=2, use="a sheet")}}), encoding="utf-8")
    facts = art_process.process(manifest, source, out)
    assert facts["set"] == {"w": 4, "h": 4, "frames": 1, "scale": 1}
    assert sorted(path.name for path in out.iterdir()) == ["art.css", "set.png"]  # no file for a cell
    assert colour_type(out / "set.png") == 3 and (out / "set.png").read_bytes().count(b"tRNS") == 1
    assert art_process.Image.open(out / "set.png").convert("RGBA").getpixel((2, 0)) == BLUE
    css = (out / "art.css").read_text(encoding="utf-8")
    assert '--art-set:url("set.png");--art-set-w:4;--art-set-h:4' in css
    assert css.count("background-image:var(--art-set)") == 1  # the one rule they share
    assert re.search(r"\.art-a,\.art-b,\.art-c\{display:inline-block;flex:none;width:calc\(2px\*var\(--art-s,2\)\*var\(--art-m,1\)\);height:calc\(2px\*var\(--art-s,2\)\*var\(--art-m,1\)\)", css)
    assert "background-size:calc(4px*var(--art-s,2)*var(--art-m,1)) calc(4px*var(--art-s,2)*var(--art-m,1))" in css
    assert ".art-a{--art-cx:0;--art-cy:0}" in css and ".art-b{--art-cx:1;--art-cy:0}" in css and ".art-c{--art-cx:0;--art-cy:1}" in css
    assert css.count("{--art-cx:") == 3 and ".art-set{" not in css  # a position for each cell and no class of the sheet's own
    assert str(tmp_path) not in css and "\\" not in css


@needs_pillow
def test_a_cell_that_left_the_manifest_leaves_no_file_behind_and_a_second_run_writes_the_same_bytes(tmp_path):
    source, out = tmp_path / "artist", tmp_path / "out"
    source.mkdir()
    for name, rows in CELLS.items():
        picture(rows, 3).save(source / f"{name}.png")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"assets": {"set": sheet_entry(palette=255)}}), encoding="utf-8")
    art_process.process(manifest, source, out)
    first = {path.name: path.read_bytes() for path in out.iterdir()}
    art_process.process(manifest, source, out)
    assert {path.name: path.read_bytes() for path in out.iterdir()} == first
    fewer = sheet_entry(palette=255, cells={"a": {"source": "a.png"}})
    manifest.write_text(json.dumps({"assets": {"set": fewer}}), encoding="utf-8")
    art_process.process(manifest, source, out)
    css = (out / "art.css").read_text(encoding="utf-8")
    assert ".art-b" not in css and ".art-c" not in css and ".art-a{--art-cx:0;--art-cy:0}" in css


@needs_pillow
def test_a_still_may_ask_for_a_palette_too_and_gets_the_same_pixels(tmp_path):
    source, out = tmp_path / "artist", tmp_path / "out"
    write_source(source)
    manifest = tmp_path / "manifest.json"
    entries = {"ground": {"source": "ground.png", "kind": "still", "size": [2, 2], "background": None, "palette": 255}, "plain": {"source": "ground.png", "kind": "still", "size": [2, 2], "background": None}}
    manifest.write_text(json.dumps({"assets": entries}), encoding="utf-8")
    art_process.process(manifest, source, out)
    assert colour_type(out / "ground.png") == 3 and colour_type(out / "plain.png") == 6
    assert art_process.Image.open(out / "ground.png").convert("RGBA").tobytes() == art_process.Image.open(out / "plain.png").convert("RGBA").tobytes()


# ---- the committed sheet (no Pillow needed) -----------------------------------------------------------------------------------------------------


def committed():
    return json.loads((ART / "manifest.json").read_text(encoding="utf-8"))["assets"]


def test_the_manifest_has_the_sheet_of_icons_and_it_says_what_each_cell_is_for():
    entry = committed()["icons"]
    assert entry["kind"] == "sheet" and entry["size"] == [32, 32] and entry["scale"] == 1 and entry["use"]
    assert entry["gap"] == 2  # a clear gap after every cell: at a fractional pixel ratio (a browser zoomed to 110%) no neighbour's edge is drawn into a cell
    assert isinstance(entry["columns"], int) and entry["palette"] <= 255 and entry["tolerance"] <= 16  # a cut of the colours that no eye sees: at most 16 of 255 in a channel
    cells = entry["cells"]
    assert len(cells) == len(set(cells)) and all(cell["use"] and "/" not in cell["source"] and "\\" not in cell["source"] for cell in cells.values())
    assert not [name for name in committed() if name.startswith("icon-")]  # no icon of its own file any more: the sheet has them all


def test_every_picture_the_pages_can_draw_for_a_place_or_an_item_is_a_cell_of_the_sheet():
    cells = set(committed()["icons"]["cells"])
    assert set(itemicon.ALL_ICONS) <= cells
    assert set(art.SLOT_ICONS.values()) <= cells
    assert cells == set(itemicon.ALL_ICONS) | set(art.SLOT_ICONS.values()) | {art.HELD_ICON}, "a picture that nothing draws is bytes for nothing"  # (the pouch is drawn on a held row that has no picture of its own)
    assert {"icon-hands-leather"} <= set(art.SLOT_ICONS.values())  # the place of the hands has its picture
    for name in cells:
        assert art.has(name), name


def test_the_sheet_is_as_big_as_its_cells_with_their_gaps_and_every_cell_has_a_picture_in_it_and_the_gaps_are_clear():
    entry = committed()["icons"]
    width, height, pixels = png_pixels(ART / "icons.png")
    columns, (cw, ch), count, gap = entry["columns"], entry["size"], len(entry["cells"]), entry["gap"]
    rows = -(-count // columns)
    assert (width, height) == (columns * (cw + gap), rows * (ch + gap))
    for index, name in enumerate(entry["cells"]):
        x0, y0 = (index % columns) * (cw + gap), (index // columns) * (ch + gap)
        seen = sum(1 for y in range(ch) for x in range(cw) if pixels[(y0 + y) * width + x0 + x][3] == 255)
        assert seen > 20, f"{name}: the cell is empty"
    assert all(pixels[y * width + x][3] == 0 for y in range(height) for x in range(width) if x % (cw + gap) >= cw or y % (ch + gap) >= ch), "a gap is not clear"
    css = (ART / "art.css").read_text(encoding="utf-8")
    for index, name in enumerate(entry["cells"]):
        assert f".art-{name}{{--art-cx:{index % columns};--art-cy:{index // columns}}}" in css, name
    assert f"background-position:calc(var(--art-cx,0)*-{cw + gap}px*var(--art-s,1)*var(--art-m,1)) calc(var(--art-cy,0)*-{ch + gap}px*var(--art-s,1)*var(--art-m,1))" in css


def test_the_sheet_is_an_indexed_png_whose_pixels_are_all_clear_or_whole():
    data = (ART / "icons.png").read_bytes()
    assert data[25] == 3  # indexed colour
    _, _, pixels = png_pixels(ART / "icons.png")
    assert {p[3] for p in pixels} == {0, 255}
    assert len({p for p in pixels if p[3]}) <= committed()["icons"]["palette"]


def pixel_digest(path: Path) -> tuple[int, int, str]:
    """The size of a PNG and the SHA-256 of its pixels (a clear pixel is clear, whatever colour a file gives it): what a picture IS, which no encoder changes. The bytes of a file are the encoder's
    (another Pillow writes other bytes for the same pixels), so no test holds the bytes of a picture, only its pixels."""
    width, height, pixels = png_pixels(path)
    return width, height, hashlib.sha256(b"".join(bytes((0, 0, 0, 0) if p[3] == 0 else p) for p in pixels)).hexdigest()


#: the three pictures that the maintainer drew again (the froglok, the iksar and the hyena people), by their pixels: width, height and the digest of the pixels
REDRAWN = {
    "race-froglok": (117, 124, "4dccd0ae441e8947d02a1c749a37943877890dabb865c3d9cfe20668ef2c99c8"),
    "race-iksar": (116, 150, "2fe7f01f7fa334e4c30b72451cd76d1e43b55f2ac24d5e4551a43fa6e913b7d9"),
    "hyenamen": (192, 128, "b8462b9f360dd765ace2dafe22248473de92e0e0685d3643d56e5fdabd5ec49d"),
}


def test_the_three_pictures_that_were_replaced_are_the_new_pictures():
    for name, want in REDRAWN.items():
        assert pixel_digest(ART / f"{name}.png") == want, name
    assert committed()["race-froglok"]["source"] == "frogman.png" and committed()["race-iksar"]["source"] == "lizardman.png" and committed()["hyenamen"]["source"] == "hyenamen.png"  # (the same assets: only the picture changed)
    assert (ART / "race-froglok.png").read_bytes()[25] == 3 and (ART / "race-iksar.png").read_bytes()[25] == 3 and (ART / "hyenamen.png").read_bytes()[25] == 2  # (colour types are the tool's own choice, not an encoder's)


def test_the_stylesheet_has_no_long_rule_for_a_picture_of_the_sheet():
    css = (ART / "art.css").read_text(encoding="utf-8")
    cells = set(committed()["icons"]["cells"])
    assert not [name for name in re.findall(r"--art-(icon-[a-z0-9-]+):url", css)], "a cell has no picture of its own"
    assert css.count("background-image:var(--art-icons)") == 1
    for name in cells:
        assert f".art-{name}{{background" not in css, name  # (the position is all that a cell sets)
    assert len(css) < 17398  # (art.css was 17.4 KB with fifteen long rules; fifty-six cells with a short one each are less)


#: the thirteen pictures the maintainer drew for the held things, then the pouch, in the order they were added to the sheet: after the 55 that were there, so that no cell moved
HELD_CELLS = ["idol", "stone", "horn", "lantern", "cup", "scroll", "rod", "whip", "claw", "pick", "polearm", "charm", "fishing-pole", "pouch"]


def test_the_fourteen_new_pictures_are_cells_of_the_sheet_after_the_old_ones_each_with_a_source_and_a_use():
    cells = committed()["icons"]["cells"]
    names = list(cells)
    assert names[-len(HELD_CELLS) :] == [f"icon-{name}" for name in HELD_CELLS]  # (appended: the 55 cells that were there keep their column and row)
    assert len(names) == len(set(names)) == 55 + len(HELD_CELLS)
    for name in HELD_CELLS:
        cell = cells[f"icon-{name}"]
        assert cell["source"] == f"icon-{name}.png", name
        assert len(cell["use"]) > 40 and "held" in cell["use"].lower(), name
    assert "held row" in cells["icon-pouch"]["use"] and "never" in cells["icon-pouch"]["use"]  # (what it is: the fallback of a held row, and not an item's own picture)
    for name in names[:55]:  # (a use line that says what the item pictures do now: held places show the pouch)
        assert cells[name]["use"], name


def test_the_first_cells_of_the_sheet_keep_their_place_in_the_stylesheet_and_the_new_ones_follow():
    entry = committed()["icons"]
    css = (ART / "art.css").read_text(encoding="utf-8")
    columns = entry["columns"]
    names = list(entry["cells"])
    for index in (0, 1, 7, 8, 54):  # (the cells that were there: icon-helm, icon-face, ..., icon-hands-plate: the same column and row as before)
        assert f".art-{names[index]}{{--art-cx:{index % columns};--art-cy:{index // columns}}}" in css, names[index]
    assert names[0] == "icon-helm" and names[54] == "icon-hands-plate" and names[55] == "icon-idol" and names[-1] == "icon-pouch"
    assert css.count("background-image:var(--art-icons)") == 1  # (one shared rule for all the cells: a cell is a column and a row)
    for name in HELD_CELLS:
        assert f".art-icon-{name}{{--art-cx:" in css, name


def test_every_cell_of_the_sheet_that_is_new_has_a_picture_of_its_own_and_none_is_a_copy_of_another():
    entry = committed()["icons"]
    width, height, pixels = png_pixels(ART / "icons.png")
    columns, (cw, ch), gap = entry["columns"], entry["size"], entry["gap"]
    seen: dict[tuple, str] = {}
    for index, name in enumerate(entry["cells"]):
        x0, y0 = (index % columns) * (cw + gap), (index // columns) * (ch + gap)
        cell = tuple(pixels[(y0 + y) * width + x0 + x] for y in range(ch) for x in range(cw))
        assert name not in HELD_CELLS or sum(1 for p in cell if p[3] == 255) > 120, name  # (a picture of a thing, not a speck)
        assert cell not in seen, f"{name} is the same picture as {seen[cell]}"
        seen[cell] = name
