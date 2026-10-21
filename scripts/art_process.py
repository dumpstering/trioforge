"""Make the site's pixel art from the artist's files: a maintainer's tool, not part of the build or of CI.

::

    python scripts/art_process.py SOURCE_FOLDER

``SOURCE_FOLDER`` holds the files the artist made (the manifest names them; no path of any computer is written to the repository). The committed manifest,
``pipeline/trioforge/site/static/art/manifest.json``, lists each asset that the site uses: the source file, its kind, its true size and what to do to it. The
script writes, beside the manifest, one optimised PNG for each asset and ``art.css`` (what the stylesheet imports: the address of each picture as a custom
property, and a class for each sprite). It reads the artist's files and never changes them. Add art by adding it to the manifest and running the script
again; an asset that is not in the manifest is not in the site, and the stylesheet and the pages work without it.

It needs Pillow, which the project does not require (run it with a Python that has it): ``python -m pip install Pillow`` in a scratch environment.

For each asset the script

* finds the whole-number scale the source was enlarged by (the largest ``s`` for which shrinking by ``s`` with nearest neighbour and enlarging again gives back
  every pixel; 1 for a picture that was never enlarged), checks it against the true size of the manifest, and shrinks the picture to it;
* keys the background out: every pixel of the exact background colour that can be reached from the border through pixels of that colour becomes transparent
  (an exact match, never a tolerance: the art has no anti-aliasing; a pixel of the same colour inside the picture stays);
* for a strip, cuts the frames the manifest keeps out of the grid of the sheet and writes them as one horizontal strip;
* crops to the smallest box that holds every kept pixel of every kept frame, when the manifest says ``"crop": "auto"`` (one box for all the frames, so that
  they stay aligned), or to the box the manifest gives.

Manifest, one entry for each asset (its key is the name of its file and of its class)::

    "torch": {
      "source": "trioforge-torch-sheet.png",   the artist's file
      "kind": "strip",                         "still", "tile" (repeats; no class, only the custom properties) or "strip" (frames in a grid)
      "size": [128, 128],                      the true size of the whole source: what the source shrinks to
      "background": null,                      or "#rrggbb", or "corner" (the colour of the top left pixel): the colour to key out (null: the source has transparency already)
      "trim": [1, 1, 1, 0],                    still and tile only: columns and rows to cut off the edges, [left, top, right, bottom], before any crop
      "grid": [4, 4],                          strip only: columns and rows of the sheet
      "frames": [0, 1, 2],                     strip only: the frames to keep, counted along the rows from 0
      "crop": "auto",                          or [left, top, width, height] in true pixels, or left out
      "duration_ms": 900,                      strip only: one run through the frames
      "slice": 8,                              still only: the border of a plate in true pixels (border-image-slice): one number, or [top, right, bottom, left]
      "scale": 2,                              the scale the classes show it at, 2 to 4 (the stylesheet multiplies it by --art-m on a big screen)
      "use": "what it is for"                  documentation only
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:  # (the tests skip when this is missing)
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]

REPO = Path(__file__).resolve().parents[1]
ART_DIR = REPO / "pipeline" / "trioforge" / "site" / "static" / "art"
KINDS = ("still", "tile", "strip")
#: the most the art of the site may weigh on the wire together (the PNGs are already compressed, so their size is what is sent)
BUDGET_BYTES = 120 * 1024


class ArtError(Exception):
    """A manifest entry or a source file that cannot be made into an asset."""


def find_scale(image: Any) -> int:
    """The largest whole number ``s`` for which the picture is exactly its own shrinking by ``s`` (nearest neighbour) enlarged by ``s``."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    raw = rgba.tobytes()
    for s in range(min(width, height), 0, -1):
        if width % s or height % s:
            continue
        small = rgba.resize((width // s, height // s), Image.NEAREST)
        if small.resize((width, height), Image.NEAREST).tobytes() == raw:
            return s
    return 1


def shrink(image: Any, size: tuple[int, int]) -> tuple[Any, int]:
    """The picture at its true size, and the scale it was enlarged by. Refuses a picture whose scale gives another size than the manifest's."""
    rgba = image.convert("RGBA")
    scale = find_scale(rgba)
    found = (rgba.width // scale, rgba.height // scale)
    if found != size:
        raise ArtError(f"the true size is {found[0]}x{found[1]} (scale {scale}), the manifest says {size[0]}x{size[1]}")
    return (rgba if scale == 1 else rgba.resize(size, Image.NEAREST)), scale


def parse_colour(text: str, image: Any = None) -> tuple[int, int, int]:
    """``#rrggbb``, or ``corner``: the colour of the top left pixel of the picture (the artist's icons have a flat square of a shade of their own)."""
    if text == "corner" and image is not None:
        r, g, b, a = image.convert("RGBA").getpixel((0, 0))
        if a != 255:
            raise ArtError("background is 'corner', and the corner pixel is transparent already")
        return r, g, b
    if not (isinstance(text, str) and len(text) == 7 and text[0] == "#"):
        raise ArtError(f"a background colour is written #rrggbb or corner, not {text!r}")
    return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)


def key_out(image: Any, colour: tuple[int, int, int] | None) -> Any:
    """Transparency for the exact background colour reached from the border; every pixel that is transparent already is made (0, 0, 0, 0), so that it compresses."""
    out = image.convert("RGBA")
    width, height = out.size
    pixels = out.load()
    if colour is not None:
        wanted = (*colour, 255)
        seen = bytearray(width * height)
        stack = [(x, y) for x in range(width) for y in (0, height - 1)] + [(x, y) for y in range(height) for x in (0, width - 1)]
        while stack:
            x, y = stack.pop()
            if seen[y * width + x]:
                continue
            seen[y * width + x] = 1
            if pixels[x, y] != wanted:
                continue
            pixels[x, y] = (0, 0, 0, 0)
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < width and 0 <= ny < height and not seen[ny * width + nx]:
                    stack.append((nx, ny))
    for y in range(height):
        for x in range(width):
            if pixels[x, y][3] == 0:
                pixels[x, y] = (0, 0, 0, 0)
    return out


def trim_edges(image: Any, trim: Any) -> Any:
    """The picture without the given number of columns and rows at its edges, ``[left, top, right, bottom]`` (a tile whose edge has a line of its own is seamless without it). A strip is
    not trimmed: its frames are cut from the sheet whole."""
    if trim is None:
        return image
    if not (isinstance(trim, list) and len(trim) == 4 and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in trim)):
        raise ArtError(f"trim is [left, top, right, bottom], whole numbers, not {trim!r}")
    left, top, right, bottom = trim
    if left + right >= image.width or top + bottom >= image.height:
        raise ArtError("trim leaves nothing of the picture")
    return image.crop((left, top, image.width - right, image.height - bottom))


def _box_of(images: list[Any]) -> tuple[int, int, int, int] | None:
    """The smallest box (left, top, right, bottom) that holds a visible pixel of any of the pictures, or None when none has one."""
    boxes = [box for box in (image.getchannel("A").getbbox() for image in images) if box is not None]
    if not boxes:
        return None
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def _crop_box(entry: dict[str, Any], frames: list[Any], bounds: tuple[int, int]) -> tuple[int, int, int, int] | None:
    crop = entry.get("crop")
    if crop is None:
        return None
    if crop == "auto":
        box = _box_of(frames)
        if box is None:
            raise ArtError("the picture is empty: nothing to crop to")
        return box
    if (
        isinstance(crop, list)
        and len(crop) == 4
        and all(isinstance(v, int) and not isinstance(v, bool) for v in crop)
        and crop[0] >= 0
        and crop[1] >= 0
        and crop[2] > 0
        and crop[3] > 0
    ):
        if crop[0] + crop[2] > bounds[0] or crop[1] + crop[3] > bounds[1]:  # (Pillow would pad what lies outside with transparency, and the picture would be wrong without a word)
            raise ArtError(f"crop {crop!r} lies outside the picture, which is {bounds[0]}x{bounds[1]} (after the trim)")
        return crop[0], crop[1], crop[0] + crop[2], crop[1] + crop[3]
    raise ArtError(f"crop is 'auto' or [left, top, width, height], not {crop!r}")


def make_asset(entry: dict[str, Any], source: Any) -> tuple[Any, dict[str, int]]:
    """The finished picture of one manifest entry (a strip as one row of frames) and its facts: ``w`` and ``h`` of one frame, ``frames`` and the source's ``scale``."""
    kind = entry.get("kind")
    if kind not in KINDS:
        raise ArtError(f"kind is one of {', '.join(KINDS)}, not {kind!r}")
    size = entry.get("size")
    if not (isinstance(size, list) and len(size) == 2 and all(isinstance(v, int) and v > 0 for v in size)):
        raise ArtError("size is [width, height] in true pixels")
    if entry.get("slice") is not None:
        slice_of(entry)
    colour = entry.get("background")
    small, scale = shrink(source, (size[0], size[1]))
    keyed = key_out(small, parse_colour(colour, small) if colour is not None else None)
    if entry.get("trim") is not None and kind == "strip":
        raise ArtError("trim is for a still or a tile (a strip's frames are cut from the sheet whole)")
    keyed = trim_edges(keyed, entry.get("trim"))
    if kind != "strip":
        box = _crop_box(entry, [keyed], keyed.size)
        done = keyed.crop(box) if box else keyed
        return done, {"w": done.width, "h": done.height, "frames": 1, "scale": scale}
    grid, kept = entry.get("grid"), entry.get("frames")
    if not (isinstance(grid, list) and len(grid) == 2 and all(isinstance(v, int) and v > 0 for v in grid)):
        raise ArtError("a strip has a grid [columns, rows]")
    columns, rows = grid
    if size[0] % columns or size[1] % rows:
        raise ArtError(f"the true size {size[0]}x{size[1]} does not divide into a grid of {columns}x{rows}")
    if not (isinstance(kept, list) and kept and all(isinstance(v, int) and 0 <= v < columns * rows for v in kept) and len(set(kept)) == len(kept)):
        raise ArtError(f"frames lists each frame to keep once, numbered from 0 to {columns * rows - 1}")
    fw, fh = size[0] // columns, size[1] // rows
    cells = [keyed.crop(((n % columns) * fw, (n // columns) * fh, (n % columns) * fw + fw, (n // columns) * fh + fh)) for n in kept]
    box = _crop_box(entry, cells, cells[0].size)
    if box:
        cells = [cell.crop(box) for cell in cells]
    cw, ch = cells[0].size
    strip = Image.new("RGBA", (cw * len(cells), ch), (0, 0, 0, 0))
    for i, cell in enumerate(cells):
        strip.paste(cell, (i * cw, 0))
    return strip, {"w": cw, "h": ch, "frames": len(cells), "scale": scale}


def slice_of(entry: dict[str, Any]) -> tuple[int, int, int, int]:
    """The border of a plate, in true pixels, as (top, right, bottom, left): the manifest gives one number for every side, or the four."""
    value = entry["slice"]
    sides = [value] * 4 if isinstance(value, int) and not isinstance(value, bool) else value
    if not (isinstance(sides, list) and len(sides) == 4 and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in sides)):
        raise ArtError(f"slice is a whole number or [top, right, bottom, left], not {value!r}")
    return sides[0], sides[1], sides[2], sides[3]


def render_css(manifest: dict[str, Any], facts: dict[str, dict[str, int]]) -> str:
    """``art.css``: for each asset the custom properties ``--art-<key>`` (its url), ``-w`` and ``-h`` (one frame, in true pixels, no unit), and for a plate ``-slice`` (the four sides, for ``border-image-slice``) and ``-st``, ``-sr``, ``-sb``, ``-sl`` (each side alone, no unit); for each still
    and strip the class ``.art-<key>``, sized in whole multiples of the true size (the manifest's ``scale`` or ``--art-s`` where a rule of the stylesheet sets it, times ``--art-m``, which the stylesheet raises on a big screen), and for a strip its animation."""
    props, rules = [], []
    for key, entry in manifest["assets"].items():
        f = facts[key]
        props.append(f'--art-{key}:url("{key}.png");--art-{key}-w:{f["w"]};--art-{key}-h:{f["h"]}')
        if entry.get("slice") is not None:
            top, right, bottom, left = slice_of(entry)
            props.append(f"--art-{key}-slice:{top} {right} {bottom} {left};--art-{key}-st:{top};--art-{key}-sr:{right};--art-{key}-sb:{bottom};--art-{key}-sl:{left}")
        if entry["kind"] == "tile":
            continue
        scale = entry.get("scale", 2)
        s = f"var(--art-s,{scale})*var(--art-m,1)"
        w, h, n = f["w"], f["h"], f["frames"]
        animated = entry["kind"] == "strip" and n > 1
        duration = int(entry.get("duration_ms", 1000))
        rules.append(
            f".art-{key}{{display:inline-block;flex:none;width:calc({w}px*{s});height:calc({h}px*{s});"
            f"background:var(--art-{key}) 0 0/calc({w * n}px*{s}) calc({h}px*{s}) no-repeat;image-rendering:crisp-edges;image-rendering:pixelated"
            + (f";animation:art-{key} {duration}ms steps({n}) infinite" if animated else "")
            + "}"
        )
        if animated:
            rules.append(f"@keyframes art-{key}{{to{{background-position:calc({-w * n}px*{s}) 0}}}}")
    lines = [
        "/* Made by scripts/art_process.py from manifest.json. Do not edit by hand: change the manifest and run the script again. */",
        ":root{" + ";".join(props) + "}" if props else "",
        *rules,
    ]
    return "\n".join(line for line in lines if line) + "\n"


def _keys_made_by_the_last_run(out_dir: Path) -> set[str]:
    """The assets that ``art.css`` of the last run in ``out_dir`` names (none when there was no run)."""
    try:
        text = (out_dir / "art.css").read_text(encoding="utf-8")
    except OSError:
        return set()
    return {key for key, name in re.findall(r'--art-([a-z0-9]+(?:-[a-z0-9]+)*):url\("([a-z0-9-]+)\.png"\)', text) if key == name}


def process(manifest_path: Path, source_dir: Path, out_dir: Path | None = None) -> dict[str, dict[str, int]]:
    """Read the manifest and the artist's files, write the PNGs and ``art.css`` into ``out_dir`` (the manifest's own folder by default), and return the facts of each asset."""
    if Image is None:
        raise ArtError("Pillow is not installed (run this with a Python that has it)")
    out_dir = out_dir or manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("assets"), dict):
        raise ArtError("the manifest has an 'assets' object")
    out_dir.mkdir(parents=True, exist_ok=True)
    made_before = _keys_made_by_the_last_run(out_dir)
    facts: dict[str, dict[str, int]] = {}
    made: dict[str, Any] = {}
    for key, entry in manifest["assets"].items():
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", key) is None:
            raise ArtError(f"{key}: the key is small letters, digits and hyphens")
        path = source_dir / str(entry.get("source", ""))
        if not path.is_file():
            raise ArtError(f"{key}: the source {entry.get('source')!r} is not in the source folder")
        try:
            with Image.open(path) as source:
                source.load()
                made[key], facts[key] = make_asset(entry, source)
        except ArtError as error:
            raise ArtError(f"{key}: {error}") from None
    for key, image in made.items():
        image.save(out_dir / f"{key}.png", format="PNG", optimize=True)
    with open(out_dir / "art.css", "w", encoding="utf-8", newline="\n") as handle:  # (LF on Windows too, so that the file is the same everywhere)
        handle.write(render_css(manifest, facts))
    for stale in sorted(made_before - set(made)):  # the pictures of an asset that left the manifest: only files this tool made (art.css of the last run names them), never another file of the folder
        (out_dir / f"{stale}.png").unlink(missing_ok=True)
    return facts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make the site's art from the artist's files and the manifest.")
    parser.add_argument("source", type=Path, help="the folder of the artist's files")
    parser.add_argument("--manifest", type=Path, default=ART_DIR / "manifest.json")
    parser.add_argument("--out", type=Path, help="where to write (default: beside the manifest)")
    args = parser.parse_args(argv)
    try:
        facts = process(args.manifest, args.source, args.out)
    except ArtError as error:
        print(f"art_process: {error}", file=sys.stderr)
        return 1
    out = args.out or args.manifest.parent
    total = sum(path.stat().st_size for path in out.glob("*.png"))
    for key, f in facts.items():
        print(f"{key}: {f['w']}x{f['h']}, {f['frames']} frame(s), source scale {f['scale']}")
    print(f"{len(facts)} assets, {total} bytes of PNG (budget {BUDGET_BYTES})")
    return 0 if total <= BUDGET_BYTES else 1


if __name__ == "__main__":
    raise SystemExit(main())
