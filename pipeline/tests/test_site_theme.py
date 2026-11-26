"""The colours of the theme hold WCAG AA contrast where the words sit on a picture as well as on a flat colour, in both themes.

``test_site_build.py`` holds the flat pairs of the theme's own tokens (``--text`` on ``--surface`` and the rest). These tests add the pairs that have a picture under the words (the
content column is a tile under a veil, the menu buttons and the badges are plates), the pairs of the tokens that are the same in both themes (the frame, the bars, the item window),
and a few guards that the stylesheet and the templates stay inside the content security policy. The pixels are read from the committed PNGs, with the standard library.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_art_process import ART, committed, png_pixels
from test_site_build import contrast, luminance

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "pipeline" / "trioforge" / "site" / "static"
TEMPLATES = REPO / "pipeline" / "trioforge" / "site" / "templates"
CSS = (STATIC / "site.css").read_text(encoding="utf-8")

THEMES = {
    "light": ":root",
    "dark-system": ':root:not([data-theme="light"])',
    "dark-toggle": ':root[data-theme="dark"]',
}


def block(selector: str) -> str:
    found = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert found, selector
    return found.group(1)


def tokens(theme: str) -> dict[str, str]:
    return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", block(THEMES[theme])))


def veil(theme: str) -> tuple[int, int, int, float]:
    found = re.search(r"--veil:\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\)", block(THEMES[theme]))
    assert found, theme
    r, g, b, a = found.groups()
    return int(r), int(g), int(b), float(a)


def fixed() -> dict[str, str]:
    """The tokens that are the same in both themes: the second :root block, the one with the frame in it."""
    for found in re.finditer(r":root\s*\{([^}]*)\}", CSS):
        if "--frame:" in found.group(1):
            return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", found.group(1)))
    raise AssertionError("no block of fixed tokens")


def hex_of(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def over(veil_colour: tuple[int, int, int, float], pixel: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """The pixel of a picture under a veil, as a browser blends them (in sRGB, the veil on top)."""
    r, g, b, a = veil_colour
    return tuple(round(a * v + (1 - a) * p) for v, p in zip((r, g, b), pixel[:3]))  # type: ignore[return-value]


def extremes(pixels) -> tuple[str, str]:
    """The lightest and the darkest colour of a set of pixels, as hex."""
    ordered = sorted(pixels, key=lambda rgb: luminance(hex_of(rgb)))
    return hex_of(ordered[0]), hex_of(ordered[-1])


@pytest.mark.parametrize("theme", ["light", "dark-system", "dark-toggle"])
def test_the_words_on_the_content_column_hold_aa_on_every_pixel_of_its_tile_under_the_veil(theme):
    tile = "tile-parchment" if theme == "light" else "tile-stone"
    _, _, pixels = png_pixels(ART / f"{tile}.png")
    darkest, lightest = extremes([over(veil(theme), p) for p in pixels])
    t = tokens(theme)
    for name in ("--text", "--muted", "--accent", "--visited", "--heading"):
        for background in (darkest, lightest):
            assert contrast(t[name], background) >= 4.5, f"{theme}: {name} {t[name]} on {background} of {tile} under the veil is {contrast(t[name], background):.2f}:1"


@pytest.mark.parametrize("theme", ["light", "dark-system", "dark-toggle"])
def test_the_other_pairs_of_the_theme_hold_aa(theme):
    t = tokens(theme)
    for foreground, background in [
        ("--heading", "--surface"), ("--heading", "--tint"), ("--visited", "--surface"), ("--visited", "--tint"), ("--accent", "--tint"),
        ("--btn-text", "--btn-face"), ("--on-accent", "--accent-fill"), ("--text", "--btn-face"),
    ]:  # fmt: skip
        assert contrast(t[foreground], t[background]) >= 4.5, f"{theme}: {foreground} on {background} is {contrast(t[foreground], t[background]):.2f}:1"
    for foreground, background in [("--btn-light", "--btn-face"), ("--btn-dark", "--btn-face")]:
        assert contrast(t[foreground], t[background]) >= 1.0  # (the bevel's edges are decoration; the control's text is checked above)
    for foreground, background in [("--focus", "--surface"), ("--focus", "--tint"), ("--control", "--btn-face")]:  # (parts of the interface that tell a visitor where they are or what is a control: 3:1)
        assert contrast(t[foreground], t[background]) >= 3.0, f"{theme}: {foreground} on {background} is {contrast(t[foreground], t[background]):.2f}:1"


def test_the_dark_blocks_agree_on_the_veil_and_the_two_themes_define_one():
    assert veil("dark-system") == veil("dark-toggle") and veil("light") != veil("dark-toggle")


def test_the_fixed_tokens_hold_aa_where_they_are_used():
    f = fixed()
    pairs = [
        ("--bar-text", "--bar-1"), ("--bar-text", "--bar-2"),
        ("--frame-text", "--frame"), ("--frame-text", "--frame-2"), ("--frame-gold", "--frame"), ("--frame-gold", "--frame-2"), ("--frame-link", "--frame-2"),
        ("--frame-link", "--frame"), ("--frame-muted", "--frame"), ("--frame-muted", "--frame-2"),
        ("--win-text", "--win"), ("--win-text", "--win-alt"), ("--win-muted", "--win"), ("--win-muted", "--win-alt"), ("--win-link", "--win"),
        ("--win-link", "--win-alt"), ("--win-visited", "--win"), ("--win-visited", "--win-alt"), ("--win-gold", "--win-head"),
    ]  # fmt: skip
    for foreground, background in pairs:
        assert contrast(f[foreground], f[background]) >= 4.5, f"{foreground} on {background} is {contrast(f[foreground], f[background]):.2f}:1"
    assert contrast("#ffffff", f["--win-alt"]) >= 4.5  # the item names (.kit .name)
    for background in ("--frame", "--frame-2", "--win", "--win-alt", "--win-head"):
        assert contrast(f["--frame-focus"], f[background]) >= 3.0, f"the focus ring on {background}"
    assert f["--bar-text"] == "#f7e7b4" and f["--frame-focus"] != f["--frame"]


def interior(name: str, sides: tuple[int, int, int, int]) -> list[tuple[int, int, int, int]]:
    """The pixels of a plate that lie inside its border: the part the words are set over (``border-image-slice`` is the border)."""
    width, height, pixels = png_pixels(ART / f"{name}.png")
    top, right, bottom, left = sides
    return [pixels[y * width + x] for y in range(top, height - bottom) for x in range(left, width - right)]


def slice_of(name: str) -> tuple[int, int, int, int]:
    value = committed()[name]["slice"]
    return (value, value, value, value) if isinstance(value, int) else tuple(value)  # type: ignore[return-value]


def test_the_words_on_a_plate_hold_aa_on_every_pixel_inside_its_border():
    f = fixed()
    dark = interior("plate-dark", slice_of("plate-dark"))
    assert dark and all(p[3] == 255 for p in dark)  # a plate's middle is solid, so the page behind it never shows through the words
    worst_dark = extremes([p[:3] for p in dark])
    for foreground in (f["--frame-gold"], f["--frame-text"]):  # the dark badge's words and the menu's
        for background in worst_dark:
            assert contrast(foreground, background) >= 4.5, f"{foreground} on {background} of the dark plate"
    for plate in ("plate-light", "plate-scroll"):  # the light badges
        inside = interior(plate, slice_of(plate))
        assert inside and all(p[3] == 255 for p in inside), plate
        # the words are one line (nowrap) in the middle of the box: the middle half of the rows of the part that is stretched
        width = len(inside) // (png_pixels(ART / f"{plate}.png")[1] - slice_of(plate)[0] - slice_of(plate)[2])
        rows = [inside[i : i + width] for i in range(0, len(inside), width)]
        band = [p[:3] for row in rows[len(rows) // 4 : len(rows) - len(rows) // 4] for p in row]
        for background in extremes(band):
            assert contrast("#1a1208", background) >= 4.5, f"the light badge's words on {background} of {plate}"
    assert re.search(r"\.badge-light[^{]*\{[^}]*color:\s*#1a1208", CSS) and re.search(r"\.badge-scroll[^{]*\{[^}]*color:\s*#1a1208", CSS)
    assert re.search(r"\.badge-dark[^{]*\{[^}]*color:\s*var\(--frame-gold\)", CSS)
    assert contrast(f["--bar-text"], f["--bar-2"]) >= 4.5  # the plain badge: no picture under its words


def test_a_plate_without_its_asset_leaves_badges_that_keep_their_contrast():
    """The badges set their own flat colours under the plate (a border-image with 'fill' covers them), so without the picture the words are on those."""
    f = fixed()
    assert contrast(f["--frame-gold"], "#151a28") >= 4.5 and contrast("#1a1208", "#ead9b0") >= 4.5
    assert re.search(r"\.badge-dark[^{]*\{[^}]*background-color:\s*#151a28", CSS)
    for name in ("light", "scroll"):
        assert re.search(rf"\.badge-{name}[^{{]*\{{[^}}]*background-color:\s*#ead9b0", CSS), name


def test_every_rule_that_uses_a_picture_has_a_fallback_for_the_missing_one():
    """A picture that is not part of the site is a custom property that nothing defines: each use gives its fallback in var(), so the page is whole, only plainer."""
    uses = re.findall(r"var\((--art-[a-z0-9-]+)(,[^()]*(?:\([^()]*\))?)?\)", CSS)
    assert uses
    for name, fallback in uses:
        assert fallback, f"{name} is used without a fallback"


def test_the_stylesheet_and_the_templates_stay_inside_the_policy():
    art_css = (ART / "art.css").read_text(encoding="utf-8")
    for text in (CSS, art_css):
        assert "http://" not in text and "https://" not in text and "//cdn" not in text
        assert not re.search(r"url\(\s*['\"]?(?:https?:|//|data:)", text)
    for path in sorted(TEMPLATES.glob("*.j2")):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"\sstyle\s*=", source), f"{path.name}: an inline style attribute (style-src is 'self')"
        assert "<img" not in source and "@import" not in source and "<style" not in source, path.name
    scripts = "".join(p.read_text(encoding="utf-8") for p in STATIC.rglob("*.js"))
    assert not re.search(r"\.style\.cssText|setAttribute\(\s*['\"]style", scripts)  # (the page code never writes a style attribute either)


def test_the_art_is_shown_at_whole_scales_with_pixels_not_smoothed():
    art_css = (ART / "art.css").read_text(encoding="utf-8")
    shared: set[str] = set()  # the classes of a sheet's cells that one rule draws (a list of them): that rule is pixelated and at a whole scale, and each cell's own rule only says where it is
    for rules in re.findall(r"((?:\.art-[a-z0-9-]+,)+\.art-[a-z0-9-]+)\{[^}]*\}", art_css):
        shared.update(rules.split(","))
    for selector, rule in re.findall(r"(\.art-[a-z0-9-]+)(\{[^}]*\})", art_css):
        if selector in shared and rule.startswith("{--art-cx:"):
            assert re.fullmatch(r"\{--art-cx:\d+;--art-cy:\d+\}", rule), rule  # a cell's place: whole numbers of cells
            continue
        assert "image-rendering:crisp-edges;image-rendering:pixelated" in rule, rule
        assert not re.search(r"(?<![-\w])\d*\.\d+(?:px)?\*", rule), f"a fractional scale in {rule}"
    shared_rule = re.search(r"((?:\.art-[a-z0-9-]+,)+\.art-[a-z0-9-]+)(\{[^}]*\})", art_css)
    assert shared_rule and "image-rendering:crisp-edges;image-rendering:pixelated" in shared_rule.group(2) and not re.search(r"(?<![-\w])\d*\.\d+(?:px)?\*", shared_rule.group(2))
    assert len(shared) == len(committed()["icons"]["cells"]) and shared_rule.group(1).split(",") == [f".art-{name}" for name in committed()["icons"]["cells"]]
    scales = {int(entry.get("scale", 2)) for entry in committed().values() if entry["kind"] != "tile"}
    assert scales <= {1, 2, 3, 4}
    assert re.search(r"--art-m:\s*2\b", CSS) and not re.search(r"--art-m:\s*\d*\.\d", CSS)  # the big-screen multiplier is a whole number too
    assert CSS.count("image-rendering: pixelated") >= 5


def selectors_of(css: str, declaration: str) -> list[str]:
    """The selectors (one by one) of every rule whose body has this declaration."""
    found = []
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    for rule in re.finditer(r"([^{}@]+)\{([^{}]*)\}", css):
        if declaration in " ".join(rule.group(2).split()):
            found += [part.strip() for part in rule.group(1).split(",")]
    return found


def specificity(selector: str) -> tuple[int, int, int]:
    """(ids, classes, attributes and pseudo-classes, types) of a selector as this stylesheet writes them (:not() counts its argument, not itself)."""
    ids = len(re.findall(r"#[\w-]+", selector))
    classes = len(re.findall(r"\.[\w-]+|\[[^\]]*\]|:(?!not\b)[\w-]+", selector))
    types = len(re.findall(r"(?:^|[\s>+~(])[a-z][\w-]*", re.sub(r"\[[^\]]*\]", "", selector)))
    return ids, classes, types


def test_the_root_font_size_scales_from_the_visitors_own_setting_and_never_pins_pixels():
    body = re.search(r"(?m)^html\s*\{([^}]*)\}", CSS).group(1)
    size = re.search(r"font-size:[^;]*;", body).group(0)
    assert re.fullmatch(r"font-size:\s*clamp\(1rem,\s*calc\(0\.625rem \+ 0\.35vw\),\s*1\.3125rem\);", size), size


def test_the_focus_ring_has_a_colour_of_its_own_on_the_dark_frame_in_both_themes():
    f = fixed()
    for background in ("--frame", "--frame-2"):
        assert contrast(f["--frame-focus"], f[background]) >= 3.0, background
    ring = selectors_of(CSS, "outline-color: var(--frame-focus)")
    for scope in (".site-header :focus-visible", ".site-footer :focus-visible", ".skip-link:focus-visible"):
        assert scope in ring, scope
    for theme in ("light", "dark-system", "dark-toggle"):  # the page's own ring (--focus) is for the parchment and the stone, and is not what the frame uses
        assert contrast(tokens(theme)["--focus"], tokens(theme)["--surface"]) >= 3.0


def test_the_bar_of_a_heading_does_not_escape_the_shared_panel():
    bar = [s for s in selectors_of(CSS, "background: linear-gradient(var(--bar-1), var(--bar-2))") if "h2" in s]
    inside = [s for s in selectors_of(CSS, "margin-inline: 0") if "shared" in s and "h2" in s]
    assert bar and inside
    assert max(specificity(s) for s in inside) > max(specificity(s) for s in bar), (inside, bar)


def test_what_is_not_the_header_the_main_column_or_the_footer_is_out_of_the_flow_of_the_page_grid():
    for selector in (".sprite", ".skip-link"):
        assert "position: absolute" in " ".join(block(selector).split()), selector  # (an absolute child of a grid takes no cell, so no row of its own)


def test_the_slot_icons_are_twice_their_size_on_a_wide_screen_and_their_own_size_on_a_phone():
    wide = re.search(r"@media \(min-width: 56rem\) \{(.*?)\n\}\n", CSS, re.DOTALL).group(1)
    assert re.search(r"\.kit th \.art \{[^}]*--art-s: 2", wide)
    assert not re.search(r"\.kit th \.art \{[^}]*--art-s: 2", CSS.replace(wide, ""))
