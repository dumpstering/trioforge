"""The sliders and the buff choices of the trio page, as the generator and the build deliver them.

The page carries the little that has to be there before any script runs (a Full raid choice, an Enchanter checkbox, the Weights assumption with nothing in it, and the names of
the slider groups of the bundle); the sliders themselves, and the code that works out the answer for them, are a chunk that is loaded on the first use of either control and by no
page by itself. The browser side is tested in tests-js/weights.test.mjs and tests-e2e/weights.spec.mjs.
"""

from __future__ import annotations

import gzip
import json
import os
import re
from pathlib import Path

import pytest
from test_site_build import PAGES, RESULTS, need_node, page, read, run_build

from trioforge.site import build

REPO = Path(__file__).resolve().parents[2]
#: what the page may carry for the two controls, in bytes of HTML: the generator writes the choices and the empty assumption, the chunk draws the rest
MARKUP_BYTES = 640
#: the file that holds the weights code, by the name esbuild's metafile gives it (relative to static/)
WEIGHTS = "ui/weights.js"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    need_node()
    tmp = tmp_path_factory.mktemp("site-weights")
    out = tmp / "dist"
    summary = run_build(out, tmp)
    return out, summary


def bundle_groups() -> list[str]:
    """The slider groups of the bundle the fixture publishes, in its order."""
    bundle = json.loads((RESULTS / "pal-mnk-ber" / "engine-l50.json").read_text(encoding="utf-8"))
    return list(bundle["weight_groups"]["groups"])


# ---- the buffs --------------------------------------------------------------------------------------------------------------------


def test_the_buffs_assumption_has_a_full_raid_choice_and_an_enchanter_checkbox_under_the_group_choice(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    radios = html.find_all("input", name="buffs")
    assert [r.get("value") for r in radios] == ["own", "group", "raid"]
    assert [html.find("label", **{"for": r.get("id")}).text() for r in radios] == ["Your own buffs", "Common group buffs", "Full raid"]
    assert [r.get("data-phrase") for r in radios] == ["your own buffs", "common group buffs", "full raid buffs"]
    assert [r.get("id") for r in radios if r.has("checked")] == ["buffs-own"]
    assert all(r.has("disabled") for r in radios)  # (the page code enables them: without it there is nothing behind them)
    enchanter = html.by_id("buffs-ench")
    assert enchanter.get("type") == "checkbox" and not enchanter.has("checked") and enchanter.has("disabled")
    assert html.find("label", **{"for": "buffs-ench"}).text() == "Enchanter in group"
    assert enchanter.get("data-phrase") == "and an Enchanter"
    # one box holds the control and its label, as for every other choice, and the checkbox is in the fieldset of the buffs, after the choices it goes with
    box = enchanter.parent
    assert "opt" in box.classes and [c.tag for c in box.children if hasattr(c, "tag")] == ["input", "label"]
    fieldset = html.by_id("assume-buffs").find("fieldset")
    assert box.parent is fieldset and fieldset.find("legend").text() == "Buffs"
    after = [c for c in fieldset.children if hasattr(c, "tag")]
    assert after.index(box) > after.index(radios[1].parent)


def test_the_summary_of_the_buffs_still_names_the_default_choice(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    assert html.by_id("assume-buffs").find("summary").text() == "Buffs: your own buffs change"


# ---- the weights ------------------------------------------------------------------------------------------------------------------


def test_the_weights_assumption_is_collapsed_and_empty_beside_the_other_three(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    assumptions = html.find_all("details", cls="assume")
    assert [d.get("id") for d in assumptions] == ["assume-buffs", "assume-weapons", "assume-weights"]
    weights = html.by_id("assume-weights")
    assert not weights.has("open")
    assert weights.find("summary").text() == "Weights: role's own change"
    assert weights.find("summary").find(data_f="assume-weights").text() == "role's own"
    fieldset = weights.find("fieldset")
    assert fieldset.find("legend").text() == "Weights"
    assert fieldset.find_all("input") == [] and fieldset.find_all("fieldset") == []  # the sliders are drawn by the chunk, on the first use


def test_the_page_names_the_slider_groups_of_the_bundle_in_the_bundles_order(site):
    out, _ = site
    html = page(out, PAGES["trio"])
    main = html.find("main")
    groups = bundle_groups()
    assert groups[:2] == ["AC", "MANA"] and len(groups) == 5  # (the bundle has five: armor class, mana, attack and haste, resists, regeneration)
    assert main.get("data-groups") == " ".join(groups)


def test_what_the_page_carries_for_the_two_controls_is_about_six_hundred_bytes(site):
    out, _ = site
    text = read(out, PAGES["trio"])
    parts = {
        "the Full raid choice": r'<span class="opt"><input type="radio" name="buffs" id="buffs-raid"[^>]*><label for="buffs-raid">[^<]*</label></span>\n',
        "the Enchanter checkbox": r'<span class="opt[^"]*"><input type="checkbox" id="buffs-ench"[^>]*><label for="buffs-ench">[^<]*</label></span>\n',
        "the Weights assumption": r'<details class="assume" id="assume-weights">.*?</details>\n',
        "the names of the groups": r' data-groups="[^"]*"',
    }
    sizes = {}
    for name, pattern in parts.items():
        found = re.findall(pattern, text, flags=re.DOTALL)
        assert len(found) == 1, name
        sizes[name] = len(found[0].encode("utf-8"))
    assert sum(sizes.values()) <= MARKUP_BYTES, sizes
    assert "weights-body" not in text and 'name="w' not in text  # no slider is in the page


# ---- the chunk --------------------------------------------------------------------------------------------------------------------


def lazy_chunks(out: Path) -> list[Path]:
    return sorted(p for p in (out / "assets").glob("*.js") if not re.fullmatch(r"(?:app|boot)-[A-Z0-9]{8}\.js", p.name))


def test_the_weights_code_is_a_chunk_of_its_own_that_the_page_script_loads_only_when_a_control_is_used(site):
    out, summary = site
    assets = out / "assets"
    chunks = sorted(p for p in assets.glob("weights-*.js"))
    assert len(chunks) == 1 and re.fullmatch(r"weights-[A-Z0-9]{8}\.js", chunks[0].name), [p.name for p in assets.iterdir()]
    app = next(p for p in assets.glob("app-*.js"))
    app_text = app.read_text(encoding="utf-8")
    chunk_text = chunks[0].read_text(encoding="utf-8")
    words = ["Working out the kit for these settings", "Back to the precomputed answer", "Exact value (F)", "Reset weights", "Attack and haste", "Regeneration"]
    for word in words:
        assert word in chunk_text, word
        assert word not in app_text, word  # none of its words are in the first load
    # the page script asks for it by a dynamic import, and no page names it
    assert re.search(r'import\("\./weights-[A-Z0-9]{8}\.js"\)', app_text)
    assert not re.search(r'(?:^|[;}\s])import[^("]*"\./weights-', app_text)
    for html in out.rglob("*.html"):
        assert "weights-" not in html.read_text(encoding="utf-8"), html
    # it is counted with the code loaded on first use, within the budgets of a chunk
    assert summary.sizes["lazy_chunk_js"] <= build.LIMITS["lazy_chunk_js"] and summary.sizes["lazy_chunk_js_gzip"] <= build.LIMITS["lazy_chunk_js_gzip"]
    assert summary.sizes["lazy_js"] <= build.LIMITS["lazy_total_js"]
    gz = len(gzip.compress(chunks[0].read_bytes(), 9))
    assert len(chunks[0].read_bytes()) <= build.LIMITS["lazy_chunk_js"] and gz <= build.LIMITS["lazy_chunk_js_gzip"]


def test_the_first_load_does_not_grow_by_the_weights_code(site):
    out, summary = site
    text = read(out, PAGES["trio"])
    scripts = re.findall(r'(?:src|href)="(/assets/[^"]+)"', text)
    assert sorted(Path(s).name.split("-")[0] for s in scripts) == ["app", "boot", "site"]  # the page names the stylesheet and the two scripts, as before
    assert summary.sizes["first_load_js"] <= build.LIMITS["first_load_js"] and summary.sizes["first_load_js_gzip"] <= build.LIMITS["first_load_js_gzip"]
    assert summary.sizes["trio_html"] <= build.LIMITS["trio_html"]


def shaped(page_inputs, chunk_inputs):
    """A metafile in the shape of esbuild's: the page script with its inputs, and one chunk with its own."""
    outputs = {
        "app-AAAAAAAA.js": {"entryPoint": "app.js", "imports": [], "inputs": {name: {"bytesInOutput": 10} for name in page_inputs}},
    }
    if chunk_inputs is not None:
        outputs["weights-BBBBBBBB.js"] = {"imports": [], "inputs": {name: {"bytesInOutput": 10} for name in chunk_inputs}}
    return {"outputs": outputs}


def test_the_build_refuses_a_page_script_that_holds_the_weights_code_and_a_build_without_it():
    build.check_weights_chunk(shaped(["app.js", "trio.js"], [WEIGHTS, "engine/manifest.js"]))
    with pytest.raises(build.BuildError, match=re.escape(WEIGHTS)):
        build.check_weights_chunk(shaped(["app.js", "trio.js", WEIGHTS], [WEIGHTS]))  # a static import of it puts it into the page script
    with pytest.raises(build.BuildError, match=re.escape(WEIGHTS)):
        build.check_weights_chunk(shaped(["app.js", "trio.js", WEIGHTS], None))
    with pytest.raises(build.BuildError, match=re.escape(WEIGHTS)):
        build.check_weights_chunk(shaped(["app.js", "trio.js"], ["engine/manifest.js"]))  # left out of the build: no output holds it
    with pytest.raises(build.BuildError, match="no page script"):
        build.check_weights_chunk({"outputs": {"weights-BBBBBBBB.js": {"imports": [], "inputs": {WEIGHTS: {"bytesInOutput": 10}}}}})
    long_form = shaped(["app.js", "trio.js", f"pipeline/trioforge/site/static/{WEIGHTS}"], [WEIGHTS])  # (a path that is not relative to static/ is the same file)
    with pytest.raises(build.BuildError, match=re.escape(WEIGHTS)):
        build.check_weights_chunk(long_form)


def test_the_real_bundle_is_held_to_the_check(tmp_path):
    need_node()
    meta: dict = {}
    build.bundle_assets(keep_metafile=meta)
    build.check_weights_chunk(meta)  # (bundle_assets runs it too: a bundle that failed it would not have been made)
    holders = [name for name, info in meta["outputs"].items() if any(path.endswith(WEIGHTS) for path in info.get("inputs", {}))]
    assert len(holders) == 1 and Path(holders[0]).name.startswith("weights-")


def test_no_chunk_of_the_page_holds_the_evaluator_and_the_readers_of_the_data_share_a_leaf_module(tmp_path):
    """F13: the item reader, the tier rules and the profile reader imported evaluate.js only for ``safe``, so the lazy chunks of the sliders and of the Upgrade section (and the chunk they share)
    carried a part of the evaluator the page loads from its own script (kitvalue.js) when it needs it. ``safe`` and ``isPlainObject`` are in plain.js, with no import."""
    need_node()
    meta: dict = {}
    build.bundle_assets(keep_metafile=meta)
    holders = [Path(name).name for name, info in meta["outputs"].items() if any(path.endswith("engine/evaluate.js") for path in info.get("inputs", {}))]
    assert holders == [], f"the evaluator is in {holders}: a reader of the data imports it again"
    leaf = [Path(name).name for name, info in meta["outputs"].items() if any(path.endswith("engine/plain.js") for path in info.get("inputs", {}))]
    assert leaf, "the leaf module of plain data is in no chunk"
    source = (REPO / "pipeline" / "trioforge" / "site" / "static" / "engine" / "plain.js").read_text(encoding="utf-8")
    assert not re.search(r"^\s*import", source, re.M), "plain.js is a leaf: it imports nothing"


# ---- the real results -------------------------------------------------------------------------------------------------------------


def real_results() -> Path | None:
    given = os.environ.get("TRIOFORGE_RESULTS")
    folder = Path(given) if given else REPO / "build" / "results"
    return folder if (folder / "items.json").is_file() else None


def test_the_trio_page_of_the_real_results_stays_under_its_limit_with_the_weights_markup(tmp_path):
    need_node()
    folder = real_results()
    if folder is None:
        pytest.skip("there are no real results here ($TRIOFORGE_RESULTS, build/results)")
    out = tmp_path / "dist"
    summary = build.build(results=folder, out=out, noindex=True)
    pages = sorted((out / "trio").glob("*/index.html"))
    assert pages, "the build wrote no trio page"
    assert max(p.stat().st_size for p in pages) == summary.sizes["trio_html"] <= build.LIMITS["trio_html"] == 67584
    assert len(list((out / "assets").glob("weights-*.js"))) == 1
    assert summary.sizes["first_load_js"] <= build.LIMITS["first_load_js"] and summary.sizes["first_load_js_gzip"] <= build.LIMITS["first_load_js_gzip"]
    assert summary.sizes["lazy_chunk_js"] <= build.LIMITS["lazy_chunk_js"] and summary.sizes["lazy_chunk_js_gzip"] <= build.LIMITS["lazy_chunk_js_gzip"]
    assert summary.sizes["lazy_js"] <= build.LIMITS["lazy_total_js"]
