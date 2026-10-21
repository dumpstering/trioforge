"""Tests for ``scripts/art_process.py`` (the maintainer's tool that makes the site's pixel art) and for the art it made.

The tool needs Pillow, which the project does not require, so the tests that run it are skipped where Pillow is missing (run them with a Python that has it: ``python -m pytest
pipeline/tests/test_art_process.py``). The images are tiny ones made here. The last tests read only the committed art, and need nothing.
"""

from __future__ import annotations

import importlib.util
import json
import re
import zlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "pipeline" / "trioforge" / "site" / "static" / "art"

_spec = importlib.util.spec_from_file_location("art_process", REPO / "scripts" / "art_process.py")
art_process = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(art_process)

needs_pillow = pytest.mark.skipif(art_process.Image is None, reason="Pillow is not installed")

CREAM = (246, 231, 189, 255)
RED = (200, 30, 30, 255)
BLUE = (30, 30, 200, 255)
CLEAR = (0, 0, 0, 0)


def picture(rows: list[list[tuple[int, int, int, int]]], scale: int = 1):
    """An image from rows of pixels, enlarged by a whole number."""
    image = art_process.Image.new("RGBA", (len(rows[0]), len(rows)))
    for y, row in enumerate(rows):
        for x, pixel in enumerate(row):
            image.putpixel((x, y), pixel)
    return image if scale == 1 else image.resize((image.width * scale, image.height * scale), art_process.Image.NEAREST)


@needs_pillow
def test_the_scale_is_the_largest_whole_number_that_gives_the_picture_back():
    rows = [[RED, BLUE, RED], [BLUE, RED, BLUE]]
    assert art_process.find_scale(picture(rows, 4)) == 4
    assert art_process.find_scale(picture(rows, 1)) == 1
    odd = [[RED, RED, BLUE], [RED, RED, BLUE]]  # 3x2 enlarged by 2 is 6x4, whose blocks are 2 wide, and the whole is two blocks high: not more than 2
    assert art_process.find_scale(picture(odd, 2)) == 2


@needs_pillow
def test_a_noisy_picture_is_not_taken_for_an_enlarged_one():
    rows = [[RED, BLUE, BLUE, RED], [BLUE, RED, RED, BLUE], [RED, BLUE, BLUE, RED], [BLUE, RED, RED, (0, 0, 0, 255)]]
    big = picture(rows, 3)
    big.putpixel((1, 1), BLUE)  # one pixel off its block
    assert art_process.find_scale(big) == 1


@needs_pillow
def test_the_picture_is_shrunk_to_its_true_size_and_a_wrong_true_size_is_refused():
    rows = [[RED, BLUE], [BLUE, RED]]
    small, scale = art_process.shrink(picture(rows, 8), (2, 2))
    assert scale == 8 and small.size == (2, 2) and small.getpixel((1, 0)) == BLUE
    with pytest.raises(art_process.ArtError, match="manifest says 4x4"):
        art_process.shrink(picture(rows, 8), (4, 4))


@needs_pillow
def test_the_background_is_keyed_out_by_the_exact_colour_from_the_border_only():
    near = (246, 231, 190, 255)  # one step off the background: part of the picture
    rows = [
        [CREAM, CREAM, CREAM, CREAM, CREAM],
        [CREAM, RED, RED, RED, CREAM],
        [CREAM, RED, CREAM, near, CREAM],  # a cream pixel inside the picture is not reached from the border
        [CREAM, RED, RED, RED, CREAM],
        [CREAM, CREAM, CREAM, CREAM, CREAM],
    ]
    out = art_process.key_out(picture(rows), (246, 231, 189))
    assert out.getpixel((0, 0)) == CLEAR and out.getpixel((4, 4)) == CLEAR
    assert out.getpixel((2, 2)) == CREAM and out.getpixel((3, 2)) == near and out.getpixel((1, 1)) == RED


@needs_pillow
def test_the_corner_colour_is_keyed_out_whatever_shade_the_square_is():
    for shade in ((38, 44, 64, 255), (60, 50, 90, 255)):
        rows = [[shade] * 4, [shade, RED, RED, shade], [shade] * 4]
        image, facts = art_process.make_asset({"kind": "still", "size": [4, 3], "background": "corner"}, picture(rows))
        assert image.getpixel((0, 0)) == CLEAR and image.getpixel((1, 1)) == RED
    with pytest.raises(art_process.ArtError, match="transparent already"):
        art_process.make_asset({"kind": "still", "size": [1, 1], "background": "corner"}, picture([[CLEAR]]))


@needs_pillow
def test_a_tile_is_trimmed_at_its_edges_before_it_is_used():
    gold = (183, 147, 63, 255)
    rows = [[gold] * 5] + [[gold, CREAM, BLUE, CREAM, gold] for _ in range(3)] + [[CREAM] * 5]
    image, facts = art_process.make_asset({"kind": "tile", "size": [5, 5], "trim": [1, 1, 1, 1]}, picture(rows))
    assert image.size == (3, 3) and facts["w"] == 3 and image.getpixel((1, 1)) == BLUE
    for bad, message in (([1, 1], "trim is"), ([3, 0, 2, 0], "leaves nothing"), ("x", "trim is")):
        with pytest.raises(art_process.ArtError, match=message):
            art_process.make_asset({"kind": "tile", "size": [5, 5], "trim": bad}, picture(rows))
    with pytest.raises(art_process.ArtError, match="for a still or a tile"):
        art_process.make_asset({"kind": "strip", "size": [4, 2], "grid": [2, 1], "frames": [0], "trim": [1, 0, 0, 0]}, picture([[RED, BLUE, RED, BLUE], [BLUE, RED, BLUE, RED]]))


@needs_pillow
def test_pixels_that_are_transparent_already_are_all_made_the_same_nothing():
    image = picture([[(9, 9, 9, 0), RED]])
    assert art_process.key_out(image, None).getpixel((0, 0)) == CLEAR


@needs_pillow
def test_a_strip_keeps_the_chosen_frames_in_one_row_and_crops_them_alike():
    # a sheet of 2 x 2 cells of 4 x 4 pixels, each with a dot in a different place; enlarged by 2
    def cell(dot):
        rows = [[CLEAR] * 4 for _ in range(4)]
        rows[dot[1]][dot[0]] = RED
        return rows

    cells = [cell((0, 1)), cell((3, 1)), cell((1, 3)), cell((2, 2))]
    rows = [cells[0][y] + cells[1][y] for y in range(4)] + [cells[2][y] + cells[3][y] for y in range(4)]
    entry = {"kind": "strip", "size": [8, 8], "grid": [2, 2], "frames": [0, 1, 3], "crop": "auto"}
    strip, facts = art_process.make_asset(entry, picture(rows, 2))
    assert facts == {"w": 4, "h": 2, "frames": 3, "scale": 2}  # the dots of frames 0, 1 and 3 are at x 0..3 and y 1..2: one box for all of them
    assert strip.size == (12, 2)
    assert strip.getpixel((0, 0)) == RED  # frame 0's dot at x 0, y 1 is at y 0 of the crop
    assert strip.getpixel((4 + 3, 0)) == RED  # frame 1's dot is at x 3
    assert strip.getpixel((8 + 2, 1)) == RED  # frame 3's dot is at x 2, y 2


@needs_pillow
@needs_pillow
def test_a_plate_may_have_a_border_of_its_own_on_each_side(tmp_path):
    entry = {**MANIFEST["assets"]["plate"], "slice": [9, 8, 11, 8]}
    css = art_process.render_css({"assets": {"plate": entry}}, {"plate": {"w": 30, "h": 30, "frames": 1, "scale": 1}})
    assert "--art-plate-slice:9 8 11 8;--art-plate-st:9;--art-plate-sr:8;--art-plate-sb:11;--art-plate-sl:8" in css


@needs_pillow
@pytest.mark.parametrize("box", [[3, 0, 3, 2], [0, 2, 5, 3], [-1, 0, 2, 2], [0, 0, 6, 3], [0, 0, 5, 4]])
def test_an_explicit_crop_outside_the_picture_is_refused_and_never_padded(box):
    rows = [[CLEAR] * 5, [CLEAR, RED, BLUE, CLEAR, CLEAR], [CLEAR] * 5]
    with pytest.raises(art_process.ArtError, match="crop"):
        art_process.make_asset({"kind": "still", "size": [5, 3], "crop": box}, picture(rows))
    image, _ = art_process.make_asset({"kind": "still", "size": [5, 3], "crop": [2, 1, 3, 2]}, picture(rows))  # a box that ends on the edge is inside
    assert image.size == (3, 2)


@needs_pillow
def test_the_crop_is_checked_against_the_picture_after_its_trim():
    rows = [[CLEAR] * 5 for _ in range(5)]
    rows[2][2] = RED
    with pytest.raises(art_process.ArtError, match="crop"):
        art_process.make_asset({"kind": "tile", "size": [5, 5], "trim": [1, 1, 1, 1], "crop": [0, 0, 4, 3]}, picture(rows))  # 3 x 3 is left after the trim
    image, _ = art_process.make_asset({"kind": "tile", "size": [5, 5], "trim": [1, 1, 1, 1], "crop": [0, 0, 3, 3]}, picture(rows))
    assert image.size == (3, 3)


@needs_pillow
def test_a_still_is_cropped_to_what_shows_and_a_box_may_be_given():
    rows = [[CLEAR] * 5, [CLEAR, RED, BLUE, CLEAR, CLEAR], [CLEAR] * 5]
    image, facts = art_process.make_asset({"kind": "still", "size": [5, 3], "crop": "auto"}, picture(rows))
    assert image.size == (2, 1) and facts["w"] == 2
    image, _ = art_process.make_asset({"kind": "still", "size": [5, 3], "crop": [1, 1, 3, 2]}, picture(rows))
    assert image.size == (3, 2)


@needs_pillow
@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"kind": "movie", "size": [2, 2]}, "kind is one of"),
        ({"kind": "still", "size": [2]}, "size is"),
        ({"kind": "still", "size": [2, 2], "background": "red"}, "#rrggbb"),
        ({"kind": "strip", "size": [2, 2], "grid": [2, 2], "frames": [4]}, "frames lists each frame"),
        ({"kind": "strip", "size": [2, 2], "grid": [3, 1], "frames": [0]}, "does not divide"),
        ({"kind": "still", "size": [2, 2], "crop": "all"}, "crop is"),
        ({"kind": "still", "size": [2, 2], "slice": [1, 2]}, "slice is a whole number"),
    ],
)
def test_a_bad_entry_is_refused_with_its_reason(entry, message):
    with pytest.raises(art_process.ArtError, match=message):
        art_process.make_asset(entry, picture([[RED, BLUE], [BLUE, RED]]))


def write_source(folder: Path) -> None:
    folder.mkdir()
    picture([[CREAM, CREAM, CREAM], [CREAM, RED, CREAM], [CREAM, CREAM, CREAM]], 4).save(folder / "plate.png")
    picture([[CLEAR, RED, CLEAR, BLUE], [CLEAR, RED, CLEAR, BLUE]], 2).save(folder / "sheet.png")
    picture([[RED, BLUE], [BLUE, RED]], 3).save(folder / "ground.png")


MANIFEST = {
    "assets": {
        "plate": {"source": "plate.png", "kind": "still", "size": [3, 3], "background": "#f6e7bd", "crop": "auto", "slice": 1},
        "flame": {"source": "sheet.png", "kind": "strip", "size": [4, 2], "grid": [2, 1], "frames": [0, 1], "duration_ms": 500},
        "ground": {"source": "ground.png", "kind": "tile", "size": [2, 2]},
    }
}


@needs_pillow
def test_the_tool_writes_the_pngs_and_the_stylesheet_and_nothing_of_this_computer(tmp_path):
    source, out = tmp_path / "artist", tmp_path / "out"
    write_source(source)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
    facts = art_process.process(manifest, source, out)
    assert facts["plate"] == {"w": 1, "h": 1, "frames": 1, "scale": 4}
    assert facts["flame"] == {"w": 2, "h": 2, "frames": 2, "scale": 2}
    assert sorted(path.name for path in out.iterdir()) == ["art.css", "flame.png", "ground.png", "plate.png"]
    assert art_process.Image.open(out / "flame.png").size == (4, 2)
    assert art_process.Image.open(out / "plate.png").getpixel((0, 0)) == RED
    css = (out / "art.css").read_text(encoding="utf-8")
    assert "--art-ground:url(\"ground.png\")" in css and "--art-plate-slice:1 1 1 1;--art-plate-st:1;--art-plate-sr:1;--art-plate-sb:1;--art-plate-sl:1" in css
    assert ".art-plate{" in css and ".art-ground{" not in css  # a tile has no class, only its properties
    assert "animation:art-flame 500ms steps(2) infinite" in css and "@keyframes art-flame{to{background-position:calc(-4px*var(--art-s,2)*var(--art-m,1)) 0}}" in css
    assert "image-rendering:pixelated" in css and "image-rendering:crisp-edges" in css
    assert str(tmp_path) not in css and str(source) not in css and "\\" not in css


@needs_pillow
def test_a_png_that_left_the_manifest_is_taken_away_and_the_files_are_the_same_on_a_second_run(tmp_path):
    source, out = tmp_path / "artist", tmp_path / "out"
    write_source(source)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
    art_process.process(manifest, source, out)
    first = {path.name: path.read_bytes() for path in out.iterdir()}
    art_process.process(manifest, source, out)
    assert {path.name: path.read_bytes() for path in out.iterdir()} == first
    smaller = {"assets": {"plate": MANIFEST["assets"]["plate"]}}
    manifest.write_text(json.dumps(smaller), encoding="utf-8")
    art_process.process(manifest, source, out)
    assert sorted(path.name for path in out.iterdir()) == ["art.css", "plate.png"]
    assert "flame" not in (out / "art.css").read_text(encoding="utf-8")


@needs_pillow
def test_only_the_pngs_the_last_run_made_are_taken_away_never_a_file_that_is_not_the_tools(tmp_path):
    source, out = tmp_path / "artist", tmp_path / "out"
    write_source(source)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
    art_process.process(manifest, source, out)
    (out / "notes.png").write_bytes(b"someone else's")  # a file in the folder that is not the tool's, named like a picture
    (out / "readme.txt").write_text("keep", encoding="utf-8")
    manifest.write_text(json.dumps({"assets": {"plate": MANIFEST["assets"]["plate"]}}), encoding="utf-8")
    art_process.process(manifest, source, out)
    assert sorted(path.name for path in out.iterdir()) == ["art.css", "notes.png", "plate.png", "readme.txt"]  # flame and ground went; the others stayed


@needs_pillow
def test_a_folder_that_was_never_made_by_the_tool_loses_nothing(tmp_path):
    source, out = tmp_path / "artist", tmp_path / "out"
    write_source(source)
    out.mkdir()
    (out / "old.png").write_bytes(b"x")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
    art_process.process(manifest, source, out)
    assert (out / "old.png").exists()


@needs_pillow
def test_a_missing_source_and_a_bad_key_are_errors_that_name_the_asset(tmp_path):
    source = tmp_path / "artist"
    write_source(source)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"assets": {"plate": {**MANIFEST["assets"]["plate"], "source": "gone.png"}}}), encoding="utf-8")
    with pytest.raises(art_process.ArtError, match="plate: the source 'gone.png'"):
        art_process.process(manifest, source, tmp_path / "out")
    manifest.write_text(json.dumps({"assets": {"Bad Key": MANIFEST["assets"]["plate"]}}), encoding="utf-8")
    with pytest.raises(art_process.ArtError, match="small letters"):
        art_process.process(manifest, source, tmp_path / "out")


@needs_pillow
def test_the_command_line_says_what_it_made_and_fails_on_a_bad_manifest(tmp_path, capsys):
    source = tmp_path / "artist"
    write_source(source)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
    assert art_process.main([str(source), "--manifest", str(manifest)]) == 0
    assert "3 assets" in capsys.readouterr().out
    manifest.write_text("{}", encoding="utf-8")
    assert art_process.main([str(source), "--manifest", str(manifest)]) == 1
    assert "art_process:" in capsys.readouterr().err


# ---- the committed art (no Pillow needed) -------------------------------------------------------------------------------------------------------


def png_pixels(path: Path) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    """The size and the RGBA pixels of a PNG written by the tool (8 bits, RGBA or RGB, not interlaced), read with the standard library."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path.name
    pos, chunks = 8, []
    while pos < len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        chunks.append((data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + length]))
        pos += 12 + length
    header = dict(chunks)[b"IHDR"]
    width, height = int.from_bytes(header[:4], "big"), int.from_bytes(header[4:8], "big")
    depth, colour, _, _, interlace = header[8:13]
    assert (depth, interlace) == (8, 0) and colour in (2, 6), f"{path.name}: expected 8-bit RGB or RGBA, not interlaced"
    step = 4 if colour == 6 else 3
    raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    stride, rows, previous = width * step, [], bytearray(width * step)
    for y in range(height):
        kind, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)])
        for i in range(stride):
            left = line[i - step] if i >= step else 0
            up = previous[i]
            upleft = previous[i - step] if i >= step else 0
            if kind == 1:
                line[i] = (line[i] + left) & 255
            elif kind == 2:
                line[i] = (line[i] + up) & 255
            elif kind == 3:
                line[i] = (line[i] + (left + up) // 2) & 255
            elif kind == 4:
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                line[i] = (line[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else upleft)) & 255
        rows.append(line)
        previous = line
    pixels = []
    for line in rows:
        for x in range(width):
            r, g, b = line[x * step : x * step + 3]
            pixels.append((r, g, b, line[x * step + 3] if step == 4 else 255))
    return width, height, pixels


def committed():
    return json.loads((ART / "manifest.json").read_text(encoding="utf-8"))["assets"]


def test_every_committed_asset_has_its_file_and_every_file_has_its_asset():
    assets = committed()
    assert {path.name for path in ART.glob("*.png")} == {f"{key}.png" for key in assets}
    assert (ART / "art.css").is_file()


def test_the_art_of_the_theme_stays_under_120_kb_on_the_wire():
    total = sum(path.stat().st_size for path in ART.glob("*.png"))
    assert total <= 120 * 1024, f"{total} bytes of PNG"


def test_the_committed_files_name_no_path_of_any_computer():
    for path in [ART / "manifest.json", ART / "art.css"]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"[A-Za-z]:[\\/]|/(?:Users|home)/|\\\\", text), path.name
    for entry in committed().values():
        assert "/" not in entry["source"] and "\\" not in entry["source"]  # a file name, of a folder that is given on the command line


def test_the_stylesheet_of_the_art_agrees_with_the_files_it_names():
    css = (ART / "art.css").read_text(encoding="utf-8")
    assert set(re.findall(r'--art-([a-z0-9-]+):url\("([a-z0-9-]+)\.png"\)', css)) == {(key, key) for key in committed()}
    for key, entry in committed().items():
        width, height, _ = png_pixels(ART / f"{key}.png")
        frames = len(entry["frames"]) if entry["kind"] == "strip" else 1
        assert f"--art-{key}-w:{width // frames};--art-{key}-h:{height}" in css, key
