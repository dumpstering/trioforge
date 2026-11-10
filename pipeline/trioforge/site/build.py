"""Build the static site::

    python -m trioforge.site.build --results build/results --out site/dist [--noindex]

reads the precompute's results (``build/results/<trio>/``, through :mod:`trioforge.site.data` only), the rules file, the
sources manifest and the changelog, and writes a folder Cloudflare Pages can serve:

* ``index.html`` and one page each for the trios, ``/rules/``, ``/sources/``, ``/about/`` and ``/changelog/``. The trio
  page has its default answer baked in, so it reads without JavaScript, and the home page lists the page of every trio in its own markup (folded into an expander when there are many), so
  that the pages are found without a script. ``404.html`` is the page for an address with no
  file (Cloudflare Pages answers 404 with it; without one it answers every unknown address with the home page and a 200). It has a script of its own in place of the page script
  (``assets/notfound-<HASH>.js``, made of three files and checked by :func:`check_notfound_script`) that takes an address of a trio in another order, case or form to the page of the trio, from
  the list of the build in the page (``data-trios``), keeping the query and the fragment. The page has no analytics beacon and none of the code that takes a kit link out of the address, since
  it hands that address on, and it gives a policy of its own (:data:`NOTFOUND_POLICY`, a meta element in its head: no script of another site and no connection of any kind, whoever
  put the script there); :func:`check_budgets` holds all three to the file;
* ``item/<key>/index.html``: the page of each item that has one, which is every wearable whose evidence level in the item table of the results is strict or wiki
  (:func:`item_page_keys`; a disputed or a hidden item has none, and nothing links to it). It is a static page with its tables of tiers in it, worked out by ``at_tier``,
  of at most 16 KB raw and 4 KB gzipped, that loads nothing but the stylesheet and the scripts every page loads (:func:`check_budgets` holds both). The names in
  Wear this on a trio page and the rows of the sources page link to the pages that exist;
* ``data/<trio>/<evidence>-<buffs>.json``, ``data/<trio>/runnerups/<role>.json`` (one file for each role, with every tier of the run in it:
  the page reads the tier from it) and ``robust.json``: what the page code fetches when a switch changes, in the compact format of
  :mod:`trioforge.site.data` (the results files themselves are never published);
* ``assets/``: the stylesheet and the page code, bundled by esbuild into content-hashed files. The code of the Upgrade section (the parser of the
  inventory dump, the matcher, the readers of the item table and the picker) is a chunk of its own, ``upgrade-input-<HASH>.js``, which the page code
  imports the first time the section is used and which no page loads by itself: the budget of a first load counts the page code and the stylesheet only,
  and the build refuses a split that would make the page code import a chunk at once (:func:`check_page_script`). The panel of a kit that came in a link
  and the decoder of the link are another chunk, ``shared-kit-<HASH>.js``, which the section imports (by a dynamic import) only when a kit link is opened;
  the build refuses a section chunk that holds either or imports them at once. What the two chunks share, esbuild writes as a ``chunk-<HASH>.js``
  that the section's chunk imports. The sliders of the Weights assumption and the answers for the settings the shards lack (the full raid, the Enchanter, a slider moved) are
  a third, ``weights-<HASH>.js``, which the page code imports the first time the assumption is opened or one of those choices is used, or when the address asks for one
  (:func:`check_weights_chunk` refuses a page script that holds it). The code loaded on first use (those chunks, or
  every chunk under ``assets/`` that no page loads by itself) is held apart from the first load: each chunk (its script and the stylesheet esbuild writes beside it) has
  100 KB raw and 40 KB gzipped of its own, and all the chunks together 250 KB raw. All the JavaScript the build writes is the first load, the code loaded on first use, or the
  optimizer's client, worker and evaluator: any other script is refused;
* ``assets/engine/`` and ``engine-manifest.json``: the optimizer, which no page loads on its first view. Its client (the page's side) and
  its worker (with the solver) are bundled as modules, the solver's WebAssembly is copied under a hash of its content, and the manifest
  names the three with their sizes and lists the trios and levels a request may name. A fourth script is there for a page that opens a
  kit link: ``kitvalue-<HASH>.js``, the evaluator of a shared kit (a bundle of its own, which the optimizer's client does not carry, with a
  budget of its own), listed in the manifest with its sizes and the SHA-256 the page checks it by before it runs it. The page and the worker both take every address
  from the manifest and from nowhere else. The manifest is the one file whose name is the same in every release, so it is outside
  ``assets/`` (which is kept for a year): it is asked for again on every visit, and so a release is seen at once. ``engine-trios/<trio>.json``
  is the manifest of a trio (the bundles of its levels), also outside ``assets/``, for the same reason, and with the same caching: the
  worker fetches the one of the trio a request names;
* ``assets/engine/data/``: what the optimizer's worker reads to work out an answer for a visitor's own gear, the two files the
  precompute writes for the purpose (:mod:`trioforge.precompute.engine`): the item table (``items-<HASH>.json``, every wearable of the
  catalog) and, for each trio and level, its bundle (``<trio>-l<level>-<HASH>.json``: profiles, buff sets, constants, tier and weapon
  rules). They are the results' own files, byte for byte, under the first 16 digits of their SHA-256 in capitals. **Manifest version 2**
  lists the item table, ``"items": {path, bytes, gzip, sha256}``, the release of the data (``"data_release"``, ``"rules_version"``) and, for
  each trio, only its levels, ``"trios": {"<trio>": [50]}``: the main manifest stays small however many trios there are (the page and the
  worker refuse one over 64 KB). The bundles are in the manifest of the trio, ``{version, data_release, rules_version, trio, bundles:
  {"50": {path, bytes, gzip, sha256}}}``, a bundle for each level the trio lists and for no other, in the release of the main one. The
  worker checks the type, the size and the SHA-256 of what it fetches against the manifests before it parses a byte. The build refuses a
  bundle over 64 KB, an item table over 4 MB (512 KB gzipped), a main manifest over 64 KB and a manifest of a trio over 8 KB, naming the file;
* ``_headers`` (the committed ``site/_headers``, plus ``X-Robots-Tag: noindex`` in its first block for a ``--noindex``
  build), ``robots.txt`` and, for an indexable build, ``sitemap.xml``.

The number of files is a budget as well: Cloudflare Pages takes at most 20,000, and the build refuses a site of more than 15,000
(:data:`LIMITS`). :func:`site_files` gives the exact list of the files of a site from what the build is given (the trios with their roles and
tier scopes, the item pages, the page code), so that the full grid of 560 trios is counted the way a build of three is, and a test holds
the list to the files that a build really writes.

Everything is made in memory and checked (the page budgets included) before a single file is written, and the output
folder is replaced only if it is empty or an earlier build of this program (a marker file beside the folder says so; the
folder itself is what Pages serves and holds nothing but the site). It is replaced whole or not at all: the files are
written into a folder beside it, which takes its place when it is complete, so a build that stops part way leaves the old
output as it was. A link (symbolic link or junction) in the output folder, or as the folder, is refused. Exit status 0 on
success; 2 with one line on stderr when the build is refused.

Two builds are refused outright. **An indexable build needs ``--owner``**, the GitHub account that owns the project's
repository, because the report links point at its issues; a preview (``--noindex``) needs none, and without one no page
links to a repository ("Reports open when the project is public" stands in the footer and on the about page). The word
OWNER, which the repository files use until the project has an account, is a real account of someone else and is refused in
every build. **An indexable build refuses partial results**: a narrowed precompute run (a few races or roles; the tiers of a
run are its scope and not a narrowing) can only make a preview, and a preview says so on every page. **It also refuses a trio whose shards
have other tiers than a full run of it** (+0, +4 and +10, or every tier for PAL/MNK/BER: :func:`check_scope`), since a run of any tiers is a
full one and nothing else in the results says that it was short; a preview takes any scope. The command line has no option for a scope: only a
caller of :func:`build` (a test of a sample, the check of a release) can name one.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import gzip
import hashlib
import html as html_module
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode
from xml.sax.saxutils import escape as xml_escape

import jinja2

from trioforge import rules as rules_module
from trioforge import scope as tier_scope
from trioforge.classes import CLASS_CODES, CLASS_NAMES
from trioforge.site import art, content, data, view

__all__ = [
    "ASSET_CACHE",
    "ATTRIBUTION",
    "LICENCE_NAME",
    "LICENCE_SENTENCE",
    "MANIFEST_FILE",
    "MANIFEST_MAX_LEVEL",
    "MANIFEST_MAX_LEVELS",
    "MANIFEST_MAX_TRIOS",
    "REPORT_VIEW",
    "BudgetError",
    "BuildError",
    "CSP",
    "DISCLAIMER",
    "ENGINE_DATA_DIR",
    "EngineAssets",
    "EngineData",
    "EngineFile",
    "SiteBuild",
    "TrioFiles",
    "build",
    "check_budgets",
    "check_file_budget",
    "check_scope",
    "check_scopes",
    "page_code_files",
    "check_engine_data",
    "check_manifest_sizes",
    "check_notfound_script",
    "check_owner",
    "check_page_script",
    "check_exalt_chunk",
    "check_weights_chunk",
    "credit_of",
    "attribution_parts",
    "home_context",
    "main",
    "make_env",
    "marker_path",
    "notfound_context",
    "render_manifest",
    "render_trio_manifest",
    "eqlt_item_rows",
    "revision_rows",
    "site_files",
    "trio_manifest_name",
    "FIXED_PAGES",
    "HASH_PLACEHOLDER",
    "HOME_LIST_OPEN",
    "ITEM_PAGE_LEVELS",
    "LIMITS",
    "NOTFOUND_INPUTS",
    "NOTFOUND_POLICY",
    "NOT_FOUND_LISTED",
    "TRIO_MANIFEST_DIR",
    "WEARABLE_SLOTS",
    "item_page_keys",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SITE_DIR = Path(__file__).resolve().parent
TEMPLATES = SITE_DIR / "templates"
STATIC = SITE_DIR / "static"

#: the solver package (npm ``highs``, pinned in package.json): its WebAssembly is copied into the site, its loader is bundled into the worker
HIGHS_PACKAGE = REPO_ROOT / "node_modules" / "highs" / "package.json"
HIGHS_WASM = REPO_ROOT / "node_modules" / "highs" / "build" / "highs.wasm"
ENGINE_DIR = "assets/engine"
#: the files the optimizer's worker reads for a visitor's own gear (the item table and the bundles): hashed, like everything under assets/
ENGINE_DATA_DIR = f"{ENGINE_DIR}/data"
#: the script that runs the browser engine's own readers on the data files (see :func:`check_engine_data`)
CHECK_SCRIPT = SITE_DIR / "check_engine_data.mjs"
#: the optimizer's list of files. Its name is the same in every release, so it is not under assets/ (the folder that is kept for a
#: year, see :data:`ASSET_CACHE`): at this fixed address it keeps the host's default and is asked for again on every visit.
#: static/engine/manifest.js has the same address.
MANIFEST_FILE = "engine-manifest.json"
#: the manifest of each trio (``engine-trios/<trio>.json``, the bundles of its levels): a file of its own, at a fixed address beside the main
#: manifest and outside /assets/ for the same reason; static/engine/manifest.js builds the address the same way
TRIO_MANIFEST_DIR = "engine-trios"
#: the counts the browser's reader of the manifest accepts (static/engine/manifest.js MANIFEST_LIMITS; a test holds them equal)
MANIFEST_MAX_TRIOS = 5000
MANIFEST_MAX_LEVELS = 8
MANIFEST_MAX_LEVEL = 100

DEFAULT_SITE_URL = "https://trioforge.pages.dev"
REPOSITORY = "trioforge"  # the name of the project's repository; the account that owns it is given with --owner
#: the marker of a build folder is a file beside it, ``<folder>.trioforge-build``: the folder is what Pages serves and every file
#: in it is public. Earlier builds put ``.trioforge-build`` inside the folder; one of those is still taken as a build to replace.
MARKER_SUFFIX = ".trioforge-build"
LEGACY_MARKER = ".trioforge-build"
#: the folders a build makes beside the output folder while it writes (and keeps the old output in while it removes it): git ignores them
TEMP_SUFFIX = ".trioforge-tmp"
#: the repository files wrote OWNER where the account will go, and that is a real account of someone else
PLACEHOLDER_OWNER = "owner"
#: a GitHub account name: letters, digits and single hyphens, no hyphen at either end, 39 characters at most
_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
#: what the footer and the contact text say when there is no account to link to
REPORTS_NOT_OPEN = "Reports open when the project is public"

#: shown in every footer, and on the about and sources pages (the same words as NOTICE.md and LICENSE-DATA)
DISCLAIMER = (
    "TrioForge is a fan project, not affiliated with or endorsed by Daybreak Game Company. "
    "EverQuest is a registered trademark of Daybreak Game Company LLC."
)
#: the one attribution text of the site, in every footer, on the sources page, in LICENSE-DATA and in every data file. It credits
#: the wiki, which the items come from, and EQL Tools, whose quest data gives the zones of the quest items in the source column.
ATTRIBUTION = (
    "Item data adapted from eqlwiki.com (CC BY-SA 4.0) by the eqlwiki contributors; "
    "quest giver data compiled by EQL Tools (CC BY-SA 4.0) from eqlwiki; "
    "changes: parsed, normalized, filtered, tier-scaled"
)
#: the names in ATTRIBUTION that the footer and the sources page link, and where to
LICENCE_URL = "https://creativecommons.org/licenses/by-sa/4.0/legalcode"
ATTRIBUTION_LINKS = (
    ("eqlwiki.com", "https://eqlwiki.com/"),
    ("EQL Tools", "https://eqltools.com/sources"),
    ("CC BY-SA 4.0", LICENCE_URL),
)
#: the name of the data licence in the data files
LICENCE_NAME = "CC BY-SA 4.0"
#: what the footer says about the licences; LICENSE-DATA has the same sentences, word for word (a test says so): the data is
#: CC BY-SA 4.0 except what comes from Daybreak's own files
LICENCE_SENTENCE = (
    "The site's data is licensed CC BY-SA 4.0, except the game facts read from Daybreak Game Company's files, "
    "which are Daybreak's and fall outside that licence. The code is licensed MIT."
)

#: the content security policy of the site (no analytics host yet: it is added when analytics are switched on).
#: site/_headers must carry exactly this.
CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'; img-src 'self' data:; "
    "style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'; "
    "require-trusted-types-for 'script'; trusted-types trioforge"
)

#: the one caching rule of site/_headers: the stylesheet and the scripts under /assets/ carry a hash of their content in their
#: names, so a copy never goes stale and may be kept for a year. The pages and the data files are not cached beyond the
#: host's default (ask again on every visit), so a new release shows at once.
ASSET_PATTERN = "/assets/*"
ASSET_CACHE = "public, max-age=31536000, immutable"

#: the page budgets: a first view stays light and so does every data file
LIMITS = {
    "trio_html": 66 * 1024,  # (60 KB until p7kit, which puts the stats and the why line of each of the 22 rows in the page: some 7 KB raw and 1.4 KB gzipped)
    "first_load_js_gzip": 30 * 1024,
    "first_load_gzip": 60 * 1024,
    "shard": 200 * 1024,
    "shard_gzip": 50 * 1024,
    # the section Effects to exalt fetches the shared effects file and the file of the trio once the page has shown, when the browser is idle (the hints under Wear this need them; they are the layer's own budgets, effects/files.py: a test holds them equal)
    "effects": 200 * 1024,
    "effects_gzip": 50 * 1024,
    "exalt_gzip": 20 * 1024,
    # the script is two budgets. What a page loads by itself (the page script and the boot script) has a raw limit of its own, beside the gzip one above; what it loads on
    # first use (the chunks under assets/ that no page loads by itself, and their styles: the code of the Upgrade section and of a shared kit) is held apart from the first load,
    # whatever that weighs: each chunk has 100 KB raw and 40 KB gzipped of its own (one budget for all the chunks would be spent by the first that came), and all the chunks
    # together 250 KB raw
    "first_load_js": 100 * 1024,
    "lazy_chunk_js": 100 * 1024,
    "lazy_chunk_js_gzip": 40 * 1024,
    "lazy_total_js": 250 * 1024,
    # the optimizer is loaded on request, never on a first view: its JavaScript (the client and the worker with the solver's loader, gzipped)
    # and its WebAssembly (raw, as it is stored) have budgets of their own
    "engine_js_gzip": 150 * 1024,
    # the evaluator of a shared kit is a script of its own, loaded for a kit link and for nothing else: not part of the optimizer's, and with a budget of its own
    "engine_kitvalue": 80 * 1024,
    "engine_kitvalue_gzip": 28 * 1024,
    "engine_wasm": 4 * 1024 * 1024,
    # what the optimizer's worker fetches when it works out an answer: the bundle of a trio, and the item table of the site
    "engine_bundle": 64 * 1024,
    "engine_items": 4 * 1024 * 1024,
    "engine_items_gzip": 512 * 1024,
    # the manifests the page and the worker read: the main one, and one for each trio. The browser refuses a larger one (protocol.js
    # LIMITS.maxManifestBytes and maxTrioManifestBytes; a test holds the numbers equal), so a build that makes one is a build whose optimizer
    # would not start
    "manifest": 64 * 1024,
    "trio_manifest": 8 * 1024,
    # the page of an item: it is a static page with its tables in it, and there are thousands of them. 16 KB raw, since twenty trios named in Best for add about 1.5 KB to the
    # 10.7 KB of the largest real page and a limit of 12 KB left no room; the gzip limit stays at 4 KB (the same pages reach 3.3 KB)
    "item_html": 16 * 1024,
    "item_html_gzip": 4 * 1024,
    # the home page lists every trio page in its own markup (about 90 bytes for each: some 50 KB raw and 4 KB gzipped for the 560 trios of the full grid), and the 404 page, which is sent for every
    # address that has no file, carries the list of the trios in one attribute (about 7 KB raw and 1.4 KB gzipped for the full grid) and names none. Each is held to its own limits, and to the
    # budget of the first load that every page has.
    "home_html": 80 * 1024,
    "home_html_gzip": 12 * 1024,
    "notfound_html": 16 * 1024,
    "notfound_html_gzip": 5 * 1024,
    # the files of the site: Cloudflare Pages takes at most 20,000, and the build holds itself to 15,000
    "files": 15_000,
    # the pictures of the site together (the PNGs under assets/; a PNG is sent as it is, so this is what a phone is sent if it loads them all): one constant, art.BUDGET_BYTES, which art_process.py reads too
    "art": art.BUDGET_BYTES,
}

#: the home page lists the pages of the trios in the page itself, in a list that is open up to this many and folded into an expander beyond it (a list of 560 would be most of the page), and
#: the 404 page names the trios it can open up to this many and none beyond it (it is sent for every address that has no file, and would otherwise weigh as much as the home page)
HOME_LIST_OPEN = 12
NOT_FOUND_LISTED = 8

_DRAWN_FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Ccircle cx='16' cy='9.5' r='7' fill='%239a3a0a' fill-opacity='.85'/%3E"
    "%3Ccircle cx='9.5' cy='21' r='7' fill='%239a3a0a' fill-opacity='.6'/%3E"
    "%3Ccircle cx='22.5' cy='21' r='7' fill='%239a3a0a' fill-opacity='.4'/%3E%3C/svg%3E"
)


def _favicon() -> str:
    """The icon of every page: the 32 pixel emblem of the art as a ``data:`` address (the policy's ``img-src`` allows it), the drawn logo when the site has no emblem."""
    return art.favicon() or _DRAWN_FAVICON


FAVICON = _favicon()

#: what a report about a view names, in this order (the keys of the default view of a trio page)
REPORT_VIEW = ("race", "role", "tier", "setup", "buffs")

_SHARD_FILE = re.compile(r"data/[^/]+/(?:strict|wiki)-(?:own|group)\.json")
#: the files of the section Effects to exalt, fetched once the page has shown (when the browser is idle), and not in the first load: the shared one, and one for each trio
_EFFECTS_FILE = re.compile(r"data/effects\.json")
_EXALT_FILE = re.compile(r"data/[^/]+/exalt\.json")
#: the file of a role's runner-ups (the page fetches it whole, the first time the runner-ups of a view of that role open)
_RUNNERUP_FILE = re.compile(r"data/[^/]+/runnerups/(?:" + "|".join(data.ROLES) + r")\.json")
#: the script a browser would run, whatever it is called
_SCRIPT_SUFFIXES = (".js", ".mjs", ".cjs")
#: the optimizer's client and worker, and the evaluator of a shared kit: the only scripts in assets/engine/ (they have budgets of their own)
_ENGINE_SCRIPT = re.compile(rf"{ENGINE_DIR}/(?:client|worker|kitvalue)-[A-Z0-9]{{8}}\.js")
#: what is loaded on first use, when no page loads it by itself: a script directly under assets/, and the stylesheet that esbuild writes beside a chunk
_LAZY_FILE = re.compile(r"assets/[^/]+\.(?:js|css)")
#: a file of the page code that a page names (the stylesheet, the boot script, the page script, anything else a template might add)
_ASSET_REFERENCE = re.compile(r'(?:href|src)="(/assets/[^"]*)"')


def _lazy_chunks(lazy: Mapping[str, bytes]) -> dict[str, list[str]]:
    """Group the files loaded on first use by chunk: a script and the stylesheet that esbuild writes beside it (the same name but for the suffix) are one chunk, named by the
    script; a stylesheet that no script goes with is a chunk of its own, named by the stylesheet."""
    chunks: dict[str, list[str]] = {}
    for name in sorted(lazy):
        stem = name.rsplit(".", 1)[0]
        scripts = f"{stem}.js"
        key = scripts if scripts in lazy else name
        chunks.setdefault(key, []).append(name)
    return chunks


class BuildError(Exception):
    """The build was refused or failed. The message is one line."""


class BudgetError(BuildError):
    """A page or file is over a page budget; the message names every one."""


# ---- Jinja ------------------------------------------------------------------------------------------------------------------------


def make_env() -> jinja2.Environment:
    """Autoescape on for every template (the files are ``.html.j2``, which ``select_autoescape`` would miss), and an
    undefined name or attribute is an error, so a template typo cannot print an empty string."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.globals["art"] = art  # the pictures a page draws only when the site has them (``art.has("torch")``)
    return env


# ---- the page code and the stylesheet ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineFile:
    """One of the optimizer's files as the manifest lists it: its address (root-absolute, hashed), its size and its gzip size. The WebAssembly
    and the data files also have their SHA-256 (64 lower-case hexadecimal digits): the worker checks what it downloads against it before it
    compiles or parses a byte."""

    path: str
    bytes: int
    gzip: int
    sha256: str | None = None


@dataclass(frozen=True)
class EngineAssets:
    """The optimizer's three files, the evaluator of a shared kit (a script of its own, with the SHA-256 the page checks it by) and the version of the solver
    package they come from."""

    highs: str
    client: EngineFile
    worker: EngineFile
    wasm: EngineFile
    kitvalue: EngineFile


@dataclass(frozen=True)
class EngineData:
    """The data files of the optimizer: the item table, and the bundle of each trio at each of its levels (``bundles[slug][level]``), and the
    release of the data they are of (``data_release`` such as ``data-2026-10-14``, ``rules_version`` such as ``2026-10-13``), which every
    manifest repeats so that the worker can tell the manifest of a trio of another release from the main one's."""

    items: EngineFile
    bundles: Mapping[str, Mapping[int, EngineFile]]
    data_release: str
    rules_version: str


@dataclass(frozen=True)
class Assets:
    """The files every page may name: the stylesheet, the boot script, the page script, the optimizer's files and the script of the 404 page (``notfound``, a bundle of its own that
    only that page loads)."""

    css: str
    boot: str
    app: str
    engine: EngineAssets
    notfound: str


def _run_esbuild(arguments: list[str]) -> None:
    node = shutil.which("node")
    esbuild = REPO_ROOT / "node_modules" / "esbuild" / "bin" / "esbuild"
    if node is None or not esbuild.is_file():
        raise BuildError("Node and esbuild are needed to bundle the page code: run `npm ci --ignore-scripts` first")
    try:
        done = subprocess.run(
            [node, str(esbuild), *arguments],
            cwd=STATIC,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BuildError(f"esbuild could not run ({type(error).__name__})") from None
    if done.returncode != 0:
        first = next((line for line in (done.stderr or "").splitlines() if line.strip()), "no message")
        raise BuildError(f"esbuild failed: {first.strip()}")


#: The files of the code of a shared kit: the panel and the decoder of the link, which only the panel imports. They are a chunk of their own, which the section loads by a dynamic
#: import when a kit link is opened, so the chunk of the section (which every visitor of the section loads) does not carry them.
KIT_INPUTS = ("ui/shared-kit.js", "input/kitdecode.js")

#: The files of the code of the Upgrade section, by the names esbuild's metafile gives its inputs (relative to the folder it runs in, ``static/``). They are in no output that a page
#: loads by itself: the chunk that the page script loads when the section is used, the chunk of a shared kit that it loads in turn, and what the two share.
SECTION_INPUTS = (
    "ui/upgrade-input.js",
    "ui/gear-picker.js",
    "input/dump.js",
    "input/match.js",
    "ui/remember.js",
    "ui/share.js",
    "input/kitcode.js",
    *KIT_INPUTS,
)

#: The files that the page script itself has to hold, by the same names: first.js, which takes a kit link out of the address before any other module of the page script is evaluated, and
#: input/kitlocation.js, the function it calls. The codec of the kit link (input/kitcode.js) is in SECTION_INPUTS, so the first load carries the take and not the codec.
PAGE_INPUTS = ("first.js", "input/kitlocation.js")


def _section_input(name: str) -> str | None:
    """Which file of the code of the Upgrade section an input of esbuild's metafile is, if it is one (named from ``static/`` or from the root of the repository)."""
    tail = "/".join(str(name).replace("\\", "/").split("/")[-2:])
    return tail if tail in SECTION_INPUTS else None


def _page_input(name: str) -> str | None:
    """Which file of PAGE_INPUTS an input of esbuild's metafile is, if it is one (named from ``static/`` or from the root of the repository)."""
    text = str(name).replace("\\", "/")
    return next((wanted for wanted in PAGE_INPUTS if text == wanted or text.endswith("/" + wanted)), None)


def check_page_script(meta: Mapping[str, Any]) -> None:
    """Refuse a bundle whose page script has the code of the Upgrade section in it, or imports another file at once. ``meta`` is esbuild's metafile of the bundle of ``app.js``.
    The page script may load a chunk by a dynamic import (that is how the code of the Upgrade section comes, when the section is used); a static import would load the chunk
    with the page, which the budget of the first load does not count. And a static import of a file of the code itself makes esbuild put it into the page script with no import
    statement at all, so the inputs of the page script are looked at as well, and the code must be in some other output. And the page script must hold the files that take a kit link out of
    the address (:data:`PAGE_INPUTS`): without them the fragment would be left for the other scripts of the page to read. The code of a shared kit (:data:`KIT_INPUTS`) is a chunk of
    its own that the section's chunk loads by a dynamic import: a section chunk that holds it, or imports at once an output that does, is refused (:func:`_check_kit_chunk`)."""
    found = False
    held: set[str] = set()
    for output, info in meta.get("outputs", {}).items():
        section = {name for name in map(_section_input, info.get("inputs", {})) if name is not None}
        if Path(str(info.get("entryPoint", ""))).name != "app.js":
            held |= section
            continue
        found = True
        at_once = [Path(entry["path"]).name for entry in info.get("imports", []) if entry.get("kind") == "import-statement"]
        if at_once:
            raise BuildError(
                f"the page script {Path(output).name} imports {at_once[0]} at once: a module that the page script and the code of a section share is split off as a chunk "
                f"that the page loads with it, and the budget of the first load would not count it"
            )
        if section:
            raise BuildError(
                f"the page script {Path(output).name} holds {sorted(section)[0]}, a file of the code of the Upgrade section: a static import of it puts it into the page script, "
                f"which the budget of the first load counts as if it were not there (the section is loaded by a dynamic import)"
            )
        taken = {name for name in map(_page_input, info.get("inputs", {})) if name is not None}
        absent = [name for name in PAGE_INPUTS if name not in taken]
        if absent:
            raise BuildError(
                f"the page script {Path(output).name} does not hold {absent[0]}: the kit link would not be taken out of the address before the other scripts of the page can read it"
            )
    if not found:
        raise BuildError("esbuild's account of the bundle has no page script (app.js)")
    missing = [name for name in SECTION_INPUTS if name not in held]
    if missing:
        raise BuildError(f"no output but the page script holds {missing[0]}: the code of the Upgrade section is not in the build as a chunk of its own")
    _check_kit_chunk(meta)


def _check_kit_chunk(meta: Mapping[str, Any]) -> None:
    """Refuse a build in which the chunk of the Upgrade section loads the code of a shared kit with it: either because the chunk holds a file of it
    (:data:`KIT_INPUTS`) or because it imports at once (by an import statement, which a browser follows before it runs a line of the chunk) an output that does,
    directly or through another. The panel and the decoder are loaded by a dynamic import, only when a kit link is opened."""
    outputs = meta.get("outputs", {})

    def inputs_of(output: str) -> set[str]:
        return {name for name in map(_section_input, outputs[output].get("inputs", {})) if name is not None}

    for start in outputs:
        if "ui/upgrade-input.js" not in inputs_of(start):
            continue
        seen = {start}
        stack = [start]
        while stack:
            here = stack.pop()
            stuck = next((name for name in KIT_INPUTS if name in inputs_of(here)), None)
            if stuck is not None:
                how = "holds" if here == start else f"imports {Path(here).name} at once, which holds"
                raise BuildError(
                    f"the chunk of the Upgrade section {Path(start).name} {how} {stuck}: the code of a shared kit is a chunk of its own, loaded by a dynamic import only "
                    f"when a kit link is opened, and a static import of it makes every visitor of the section load it"
                )
            for one in outputs[here].get("imports", []):
                if one.get("kind") == "import-statement" and one.get("path") in outputs and one["path"] not in seen:
                    seen.add(one["path"])
                    stack.append(one["path"])


#: What the 404 page says of itself in a <meta http-equiv="Content-Security-Policy"> element in its head, before anything it loads. A policy that a page gives adds to the one of the header (a page
#: is held to both), so nothing on this page can load a script of another site or send anything, whoever put it there: the 404 page is the one page that keeps a kit link in its address, and
#: a beacon that the host's own toggle put into it, or one that the header of an analytics build would let come, would see it. The page's own script asks for nothing.
NOTFOUND_POLICY = "script-src 'self'; connect-src 'none'"

#: The files the script of the 404 page is made of, by the names esbuild's metafile gives its inputs (relative to the folder it runs in, ``static/``). It is a bundle of its own with these three and no
#: others: above all not first.js (or input/kitlocation.js, which it calls), the code that takes a kit link out of the address. The 404 page hands the address to the page of the trio untouched,
#: and a page that cleared the fragment first would lose the kit.
NOTFOUND_INPUTS = ("notfound.js", "canonical.js", "theme.js")


def _static_name(name: object) -> str:
    """An input of esbuild's metafile as a path below ``static/`` (named from there, or from the root of the repository)."""
    text = str(name).replace("\\", "/")
    return text.split("/static/", 1)[1] if "/static/" in text else text


def check_notfound_script(meta: Mapping[str, Any]) -> None:
    """Refuse a bundle of the 404 page's script that is not one script made of :data:`NOTFOUND_INPUTS` alone and importing nothing. ``meta`` is esbuild's metafile of the bundle."""
    scripts = {name: info for name, info in meta.get("outputs", {}).items() if str(name).endswith(".js")}
    if len(scripts) != 1:
        raise BuildError(f"esbuild's account of the 404 script has {'no script' if not scripts else 'more than one script'} (notfound.js)")
    ((output, info),) = scripts.items()
    imports = [str(one.get("path", "?")) for one in info.get("imports", [])]
    if imports:
        raise BuildError(f"the 404 script {Path(output).name} imports {Path(imports[0]).name}: it is one file, so that the page asks for nothing more")
    held = {_static_name(name) for name in info.get("inputs", {})}
    for name in sorted(held):
        if name not in NOTFOUND_INPUTS:
            raise BuildError(
                f"the 404 script {Path(output).name} holds {name}, which is no file of its own ({', '.join(NOTFOUND_INPUTS)}): the 404 page hands the kit link in its address on untouched, "
                f"and the code of the page script takes it out"
            )
    for name in NOTFOUND_INPUTS:
        if name not in held:
            raise BuildError(
                f"the 404 script {Path(output).name} does not hold {name}, one of its own files ({', '.join(NOTFOUND_INPUTS)}): a 404 page whose script lacks one of them would not move "
                f"an address of a trio, or would not hint, or would not take the theme button"
            )


#: what esbuild is told for every bundle of the page code
ESBUILD_COMMON = [
    "--bundle",
    "--minify",
    "--charset=utf8",
    "--legal-comments=none",
    "--target=chrome110,firefox110,safari16.4",
    "--log-level=warning",
    "--entry-names=[name]-[hash]",
]


#: the pictures of the stylesheet (static/art/art.css, imported by site.css) are files that esbuild copies next to it under a hash of their content, and the stylesheet names them so
ART_LOADER = ["--loader:.png=file", "--asset-names=[name]-[hash]"]


def _bundle_notfound(out: Path) -> dict[str, Any]:
    """Bundle the script of the 404 page into the folder ``out`` as a module of its own (no ``--splitting``: what it shares with the page script is copied, not imported, so that the page asks
    for one file and the page script's code, which clears a kit link from the address, is not loaded with it), check what it is made of (:func:`check_notfound_script`) and return esbuild's account."""
    meta_path = out.with_name(out.name + "-meta.json")
    _run_esbuild([*ESBUILD_COMMON, "--format=esm", f"--metafile={meta_path}", f"--outdir={out}", str(STATIC / "notfound.js")])
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    check_notfound_script(meta)
    return meta


#: The files of the code of the sliders and of the answers for the settings the shards lack, by the names esbuild's metafile gives its inputs. The page script loads them by a dynamic
#: import, the first time the Weights assumption is opened or a buff choice the shards lack is used (or the address asks for one): no output that a page loads by itself holds them.
WEIGHTS_INPUTS = ("ui/weights.js",)


def check_weights_chunk(meta: Mapping[str, Any]) -> None:
    """Refuse a bundle whose page script holds the code of the sliders (a static import of it would put it into the first load, which the budget of the first load would count as if it
    were not there), and a bundle that has it in no output (it was left out). That the page script does not import a chunk at once is :func:`check_page_script`'s. ``meta`` is esbuild's
    metafile of the bundle of ``app.js``."""
    found = False
    held: set[str] = set()
    for output, info in meta.get("outputs", {}).items():
        mine = {name for name in map(_weights_input, info.get("inputs", {})) if name is not None}
        if Path(str(info.get("entryPoint", ""))).name != "app.js":
            held |= mine
            continue
        found = True
        if mine:
            raise BuildError(
                f"the page script {Path(output).name} holds {sorted(mine)[0]}, the code of the sliders and of the answers for the settings the shards lack: a static import of it puts it into the "
                f"page script, which the budget of the first load counts as if it were not there (it is loaded by a dynamic import, when a control for it is used)"
            )
    if not found:
        raise BuildError("esbuild's account of the bundle has no page script (app.js)")
    missing = [name for name in WEIGHTS_INPUTS if name not in held]
    if missing:
        raise BuildError(f"no output but the page script holds {missing[0]}: the code of the sliders is not in the build as a chunk of its own")


#: The files of the code of the section Effects to exalt, by the names esbuild's metafile gives its inputs: the section and the matcher of the plan. The page script loads them by a dynamic
#: import, once the page has shown or when the section is opened: no output that a page loads in its first load holds them.
EXALT_INPUTS = ("ui/exalt.js", "ui/exalt-plan.js")


def check_exalt_chunk(meta: Mapping[str, Any]) -> None:
    """Refuse a bundle whose page script holds the code of the section Effects to exalt (a static import of it would put it into the first load, which the budget of the first load would
    count as if it were not there), and a bundle that has it in no output. ``meta`` is esbuild's metafile of the bundle of ``app.js``."""
    found = False
    held: set[str] = set()
    for output, info in meta.get("outputs", {}).items():
        mine = {name for name in ("/".join(str(n).replace("\\", "/").split("/")[-2:]) for n in info.get("inputs", {})) if name in EXALT_INPUTS}
        if Path(str(info.get("entryPoint", ""))).name != "app.js":
            held |= mine
            continue
        found = True
        if mine:
            raise BuildError(
                f"the page script {Path(output).name} holds {sorted(mine)[0]}, the code of the section Effects to exalt: a static import of it puts it into the page script, which the budget "
                f"of the first load counts as if it were not there (it is loaded by a dynamic import, once the page has shown)"
            )
    if not found:
        raise BuildError("esbuild's account of the bundle has no page script (app.js)")
    missing = [name for name in EXALT_INPUTS if name not in held]
    if missing:
        raise BuildError(f"no output but the page script holds {missing[0]}: the code of the section Effects to exalt is not in the build as a chunk of its own")


def _weights_input(name: str) -> str | None:
    """Which file of the code of the sliders an input of esbuild's metafile is, if it is one (named from ``static/`` or from the root of the repository)."""
    tail = "/".join(str(name).replace("\\", "/").split("/")[-2:])
    return tail if tail in WEIGHTS_INPUTS else None


def bundle_assets(
    *, keep_metafile: dict[str, Any] | None = None, keep_notfound_metafile: dict[str, Any] | None = None
) -> tuple[Assets, dict[str, bytes]]:
    """Bundle and minify ``static/``: the module ``app.js`` and ``site.css`` together (``--splitting``: the code behind a dynamic import, the Upgrade section's, is
    a chunk of its own, and the code of a shared kit that the section loads by one is another), ``boot.js`` (which sets the saved theme before the page paints) as a
    classic script, and ``notfound.js``, the script of the 404 page, as a module of its own with nothing shared with the page script (:func:`check_notfound_script`). Names carry
    a hash of the content. The optimizer's files are made last (:func:`_bundle_engine`) and go under ``assets/engine/``. A dict given as ``keep_metafile`` is filled with esbuild's account
    of the bundle of the page script (what each output was made of), and one given as ``keep_notfound_metafile`` with that of the 404 script, for a test that looks at them."""
    common = ESBUILD_COMMON
    files: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory() as scratch:
        main_out, boot_out, notfound_out = Path(scratch) / "main", Path(scratch) / "boot", Path(scratch) / "notfound"
        meta_path = Path(scratch) / "main-meta.json"
        _run_esbuild(
            [
                *common, "--format=esm", "--splitting", *ART_LOADER, f"--metafile={meta_path}", f"--outdir={main_out}",
                str(STATIC / "app.js"), str(STATIC / "site.css"),
            ]
        )
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        check_page_script(meta)
        check_weights_chunk(meta)
        check_exalt_chunk(meta)
        if keep_metafile is not None:
            keep_metafile.update(meta)
        _run_esbuild([*common, "--format=iife", f"--outdir={boot_out}", str(STATIC / "boot.js")])
        notfound_meta = _bundle_notfound(notfound_out)  # (a bundle of its own: see there)
        if keep_notfound_metafile is not None:
            keep_notfound_metafile.update(notfound_meta)
        for folder in (main_out, boot_out, notfound_out):
            for path in sorted(folder.iterdir()):
                files[f"assets/{path.name}"] = path.read_bytes()

    def find(name: str, suffix: str) -> str:
        pattern = re.compile(rf"assets/{name}-[A-Z0-9]{{8}}\.{suffix}")
        found = [path for path in files if pattern.fullmatch(path)]
        if len(found) != 1:
            raise BuildError(f"esbuild did not produce exactly one {name}.{suffix}")
        return "/" + found[0]

    engine = _bundle_engine(files)
    return Assets(find("site", "css"), find("boot", "js"), find("app", "js"), engine, find("notfound", "js")), files


def _bundle_engine(files: dict[str, bytes]) -> EngineAssets:
    """The optimizer: the client and the worker (bundled as modules into ``assets/engine/``, the worker with the solver's loader) and the
    solver's WebAssembly (copied there under a hash of its content), and the evaluator of a shared kit (a bundle of its own: the page loads it for a kit link,
    and the client does not carry it). Adds the four files to ``files``.

    ``node:module`` stays an external import: the solver's loader asks for it only when it finds itself in Node, which a browser never is.
    The worker file is a bundle of the project's own ``static/engine/worker.js`` and the solver's loader, and the loader carries a few strings that read like a
    path of a computer (a URL scheme, and folders of Emscripten's in-memory file system). The release check for local paths
    (:data:`trioforge.precompute.release.VENDOR_LITERALS`) lets exactly those quoted strings through in that file, a fixed number of times; they name no place on
    any computer, and every other match in the file, the project's own code included, still refuses the release.
    The target is Firefox 114 because module workers need it."""
    if not HIGHS_PACKAGE.is_file() or not HIGHS_WASM.is_file():
        raise BuildError("the solver package (highs) is missing: run `npm ci --ignore-scripts` first")
    version = json.loads(HIGHS_PACKAGE.read_text(encoding="utf-8"))["version"]
    pinned = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))["dependencies"]["highs"]
    if version != pinned:
        raise BuildError(f"highs {version} is installed but package.json pins {pinned}: run `npm ci --ignore-scripts`")
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "engine"
        _run_esbuild(
            [
                "--bundle",
                "--minify",
                "--charset=utf8",
                "--legal-comments=none",
                "--target=chrome110,firefox114,safari16.4",
                "--log-level=warning",
                "--entry-names=[name]-[hash]",
                "--format=esm",
                "--external:node:module",
                f"--outdir={out}",
                str(STATIC / "engine" / "client.js"),
                str(STATIC / "engine" / "worker.js"),
                str(STATIC / "engine" / "kitvalue.js"),
            ]
        )
        for path in sorted(out.iterdir()):
            files[f"{ENGINE_DIR}/{path.name}"] = path.read_bytes()
    wasm = HIGHS_WASM.read_bytes()
    digest = hashlib.sha256(wasm).hexdigest()
    wasm_name = f"{ENGINE_DIR}/highs-{digest.upper()[:16]}.wasm"
    files[wasm_name] = wasm

    def entry(name: str, suffix: str) -> EngineFile:
        pattern = re.compile(rf"{ENGINE_DIR}/{name}-[A-Z0-9]{{8}}\.{suffix}")
        found = [path for path in files if pattern.fullmatch(path)]
        if len(found) != 1:
            raise BuildError(f"esbuild did not produce exactly one engine {name}.{suffix}")
        return EngineFile("/" + found[0], len(files[found[0]]), _gzip_size(files[found[0]]))

    evaluator = entry("kitvalue", "js")
    return EngineAssets(
        highs=version,
        client=entry("client", "js"),
        worker=entry("worker", "js"),
        wasm=EngineFile("/" + wasm_name, len(wasm), _gzip_size(wasm), sha256=digest),
        kitvalue=EngineFile(evaluator.path, evaluator.bytes, evaluator.gzip, sha256=hashlib.sha256(files[evaluator.path.lstrip("/")]).hexdigest()),
    )


#: what the browser accepts as an engine file; the same patterns as static/engine/manifest.js
_ENGINE_PATHS = {
    "client": re.compile(r"/assets/engine/client-[A-Z0-9]{8,32}\.js"),
    "worker": re.compile(r"/assets/engine/worker-[A-Z0-9]{8,32}\.js"),
    "wasm": re.compile(r"/assets/engine/highs-[A-Z0-9]{8,32}\.wasm"),
    "kitvalue": re.compile(r"/assets/engine/kitvalue-[A-Z0-9]{8,32}\.js"),
}
_TRIO_SLUG = re.compile(r"[a-z]{3}-[a-z]{3}-[a-z]{3}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
#: the data files: the name has the first 16 digits of the file's SHA-256 in capitals, and a bundle's the trio and the level it is for
_ITEMS_PATH = re.compile(r"/assets/engine/data/items-([A-Z0-9]{16})\.json")
_BUNDLE_PATH = re.compile(r"/assets/engine/data/([a-z]{3}-[a-z]{3}-[a-z]{3})-l([1-9][0-9]{0,2})-([A-Z0-9]{16})\.json")
_ENGINE_DATA_NAME = re.compile(r"assets/engine/data/(?:items|[a-z]{3}-[a-z]{3}-[a-z]{3}-l[1-9][0-9]{0,2})-[A-Z0-9]{16}\.json")
#: the release the manifests name, in the form the browser reads (static/engine/manifest.js)
_DATA_RELEASE = re.compile(r"data-[0-9]{4}-[0-9]{2}-[0-9]{2}")
_RULES_VERSION = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
MANIFEST_VERSION = 2
TRIO_MANIFEST_VERSION = 1


def _data_file(file: EngineFile, what: str) -> dict[str, object]:
    """A data file of the manifest: its address, sizes and SHA-256, the digest being the one the name carries."""
    digest = file.sha256
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise BuildError(f"{what} needs its SHA-256 (64 lower-case hexadecimal digits): the worker checks the file by it")
    for number in (file.bytes, file.gzip):
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise BuildError(f"{what} needs its sizes as whole numbers of bytes")
    return {"path": file.path, "bytes": file.bytes, "gzip": file.gzip, "sha256": digest}


def _canonical(document: Mapping[str, object]) -> bytes:
    """A manifest as canonical JSON (sorted keys, no spaces, one newline at the end), so that a build is reproducible."""
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _release(data_files: EngineData) -> dict[str, str]:
    """The release the manifests name, in the form the browser reads."""
    release, rules = data_files.data_release, data_files.rules_version
    if not isinstance(release, str) or not _DATA_RELEASE.fullmatch(release):
        raise BuildError(f"the data release {release!r} is not one the browser reads (data-YYYY-MM-DD)")
    if not isinstance(rules, str) or not _RULES_VERSION.fullmatch(rules):
        raise BuildError(f"the rules version {rules!r} is not one the browser reads (YYYY-MM-DD)")
    return {"data_release": release, "rules_version": rules}


def _check_trio(slug: object, levels: Mapping[int, EngineFile]) -> None:
    """A trio the browser would read: a code of three groups of three letters, and from one to eight levels, each a whole number up to 100."""
    if not isinstance(slug, str) or not _TRIO_SLUG.fullmatch(slug):
        raise BuildError(f"the trio {slug!r} has a code the browser would not read")
    if (
        not levels
        or len(levels) > MANIFEST_MAX_LEVELS
        or any(isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MANIFEST_MAX_LEVEL for n in levels)
    ):
        raise BuildError(
            f"the trio {slug!r} needs its levels as one to {MANIFEST_MAX_LEVELS} whole numbers from 1 to {MANIFEST_MAX_LEVEL}"
        )


def trio_manifest_name(slug: str) -> str:
    """The address of the manifest of a trio in the site (without the first slash): ``engine-trios/<trio>.json``."""
    if not isinstance(slug, str) or not _TRIO_SLUG.fullmatch(slug):
        raise BuildError(f"the trio {slug!r} has a code the browser would not read")
    return f"{TRIO_MANIFEST_DIR}/{slug}.json"


def render_manifest(engine: EngineAssets, data_files: EngineData) -> bytes:
    """``engine-manifest.json`` (:data:`MANIFEST_FILE`), version 2: the optimizer's three files and the evaluator of a shared kit with their sizes (the
    WebAssembly and the evaluator with the SHA-256 that the worker, and the page, check them by), the item table, the release of
    the data, and each trio with the levels a request may name (``"trios": {slug: [50, 55]}``; the bundles are in the manifest of the trio,
    :func:`render_trio_manifest`), as canonical JSON (sorted keys, no spaces), so that a build is reproducible. The browser reads it as
    strictly as it reads a request, so anything it would refuse is refused here, at build time."""
    for role in ("client", "worker", "wasm", "kitvalue"):
        path = getattr(engine, role).path
        if not _ENGINE_PATHS[role].fullmatch(path):
            raise BuildError(f"the engine file {role} has a path the browser would not load: {path!r}")
    digest = engine.wasm.sha256
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest) or not engine.wasm.path.endswith(f"highs-{digest[:16].upper()}.wasm"):
        raise BuildError("the WebAssembly needs its SHA-256 (64 lower-case hexadecimal digits, the first 16 of them the ones in its name)")
    evaluator = engine.kitvalue.sha256
    if not isinstance(evaluator, str) or not _SHA256.fullmatch(evaluator):
        raise BuildError("the evaluator of a shared kit needs its SHA-256 (64 lower-case hexadecimal digits): the page checks the script by it before it runs it")
    items = _data_file(data_files.items, "the item table")
    found = _ITEMS_PATH.fullmatch(items["path"])  # type: ignore[arg-type]
    if found is None or found.group(1) != str(items["sha256"])[:16].upper():
        raise BuildError(f"the engine file items has a path the browser would not load or that does not carry its SHA-256: {items['path']!r}")
    if not data_files.bundles:
        raise BuildError("the manifest needs at least one trio")
    if len(data_files.bundles) > MANIFEST_MAX_TRIOS:
        raise BuildError(f"the manifest lists {len(data_files.bundles)} trios, and the browser reads at most {MANIFEST_MAX_TRIOS}")
    listed: dict[str, list[int]] = {}
    for slug in sorted(data_files.bundles):
        _check_trio(slug, data_files.bundles[slug])
        listed[slug] = sorted(data_files.bundles[slug])

    def part(file: EngineFile) -> dict[str, object]:
        return {"path": file.path, "bytes": file.bytes, "gzip": file.gzip}

    document = {
        "version": MANIFEST_VERSION,
        "highs": engine.highs,
        **_release(data_files),
        "client": part(engine.client),
        "worker": part(engine.worker),
        "wasm": {**part(engine.wasm), "sha256": digest},
        "kitvalue": {**part(engine.kitvalue), "sha256": evaluator},
        "items": items,
        "trios": listed,
    }
    return _canonical(document)


def render_trio_manifest(slug: str, data_files: EngineData) -> bytes:
    """``engine-trios/<trio>.json`` (:func:`trio_manifest_name`), version 1: the bundle of the trio at each of its levels, with its path, sizes and
    SHA-256, and the release of the data, which the worker checks against the main manifest's. Canonical JSON, and as strict as the browser's
    reader: a bundle whose file name does not carry the trio, the level and its digest is refused here."""
    trio_manifest_name(slug)  # (refuses a name that is not a trio code)
    by_level = data_files.bundles.get(slug)
    if by_level is None:
        raise BuildError(f"the trio {slug!r} has no bundles")
    _check_trio(slug, by_level)
    bundles: dict[str, object] = {}
    for level in sorted(by_level):
        what = f"the bundle of the trio {slug!r} at level {level}"
        entry = _data_file(by_level[level], what)
        found = _BUNDLE_PATH.fullmatch(entry["path"])  # type: ignore[arg-type]
        if found is None or (found.group(1), int(found.group(2))) != (slug, level) or found.group(3) != str(entry["sha256"])[:16].upper():
            raise BuildError(
                f"the engine file bundle of the trio {slug!r} at level {level} has a path the browser would not load or that does not "
                f"carry the trio, the level and its SHA-256: {entry['path']!r}"
            )
        bundles[str(level)] = entry
    return _canonical({"version": TRIO_MANIFEST_VERSION, **_release(data_files), "trio": slug, "bundles": bundles})


def check_engine_data(items: data.BrowserFile, trios: Sequence[data.TrioResults]) -> dict[str, int]:
    """Run the browser engine's own readers (``static/engine/items.js`` and ``profile.js``, in Node: ``check_engine_data.mjs``) on the item table and on the
    bundles that are about to be published, so that what the worker would refuse stops the build. The item table is read with ``readItemTable`` and then
    worked out with ``atTier`` at every tier of every record; each bundle is read with ``readBundle``, its tier and weapon rules are compiled, and
    ``assembleProfile`` is run for every race, role, buff set and evidence level it lists. A refusal is a :class:`BuildError` that names the file and the
    record. Returns what was gone through: ``records``, ``tiers`` (of each), ``bundles`` and ``profiles``."""
    node = shutil.which("node")
    if node is None or not CHECK_SCRIPT.is_file():
        raise BuildError("Node is needed to check the engine's data with the engine's own readers: run `npm ci --ignore-scripts` first")
    job = {
        "items": {"name": items.name, "text": items.raw.decode("utf-8")},
        "bundles": [{"name": f"{trio.meta.slug}/{trio.bundle.name}", "text": trio.bundle.raw.decode("utf-8")} for trio in trios],
    }
    try:
        done = subprocess.run(
            [node, str(CHECK_SCRIPT)], input=json.dumps(job), capture_output=True, text=True, encoding="utf-8", timeout=600, check=False, cwd=REPO_ROOT
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BuildError(f"the check of the engine's data could not run ({type(error).__name__})") from None
    try:
        report = json.loads(done.stdout)
        problems, more, checked = report["problems"], int(report["more"]), report["checked"]
    except (ValueError, KeyError, TypeError):
        first = next((line for line in (done.stderr or "").splitlines() if line.strip()), "no message")
        raise BuildError(f"the check of the engine's data failed: {first.strip()[:200]}") from None
    if done.returncode != 0:
        raise BuildError(f"the check of the engine's data failed with status {done.returncode}")
    if problems:
        lines = [
            f"{problem['file']}: {'record ' + problem['record'] + ': ' if problem['record'] else ''}{problem['message']}"
            for problem in problems[:3]
        ]
        rest = len(problems) - 3 + more
        raise BuildError("the engine's own readers refuse the data: " + "; ".join(lines) + (f" (and {rest} more)" if rest > 0 else ""))
    return {name: int(checked[name]) for name in ("records", "tiers", "bundles", "profiles")}


def publish_engine_data(files: dict[str, bytes], items: data.BrowserFile, trios: Sequence[data.TrioResults]) -> EngineData:
    """Put the results' item table and the bundle of each trio into ``files`` under hashed names (``assets/engine/data/``), byte for
    byte as the results hold them, and say what was put where. The same bytes always have the same name."""

    def put(stem: str, raw: bytes) -> EngineFile:
        digest = hashlib.sha256(raw).hexdigest()
        name = f"{ENGINE_DATA_DIR}/{stem}-{digest.upper()[:16]}.json"
        files[name] = raw
        return EngineFile("/" + name, len(raw), _gzip_size(raw), sha256=digest)

    releases = {(trio.meta.data_tag, trio.meta.rules_version) for trio in trios}
    if len(releases) != 1:
        raise BuildError("the trios are not of one data release and one rules version, which the manifests name")
    ((release, rules),) = releases
    bundles: dict[str, dict[int, EngineFile]] = {}
    for trio in trios:
        bundles.setdefault(trio.meta.slug, {})[trio.meta.level] = put(f"{trio.meta.slug}-l{trio.meta.level}", trio.bundle.raw)
    return EngineData(put("items", items.raw), bundles, release, rules)


# ---- headers ---------------------------------------------------------------------------------------------------------------------------


def _header_blocks(text: str) -> list[tuple[str, list[tuple[int, str, str]]]]:
    """The blocks of a headers file: each path pattern (a line that starts with no space) and the header lines under it as
    ``(line number, name, value)``."""
    blocks: list[tuple[str, list[tuple[int, str, str]]]] = []
    for number, line in enumerate(text.splitlines()):
        if not line.strip() or line.lstrip().startswith("#"):  # a blank line or a comment
            continue
        if line[0] in " \t":
            if not blocks:
                raise BuildError("site/_headers has a header line before any path pattern")
            name, _, value = line.partition(":")
            blocks[-1][1].append((number, name.strip(), value.strip()))
        else:
            blocks.append((line.strip(), []))
    return blocks


def render_headers(text: str, *, noindex: bool) -> str:
    """The committed ``site/_headers``, checked against the policy this program expects, plus the noindex header if asked.

    The first block (``/*``) is what every path gets and must carry the content security policy. The only caching rule is
    the one for ``/assets/*`` (:data:`ASSET_CACHE`); no other path may set ``Cache-Control``, so the pages and the data
    keep the host's default, which is to ask again on every visit. The noindex header is for every path, so it goes at the
    end of the first block (a header appended to the end of the file would belong to the last block, here the assets)."""
    lines = text.splitlines()
    if not lines or lines[0] != "/*":
        raise BuildError("site/_headers must start with the path pattern /*")
    blocks = _header_blocks(text)
    csp = [value for _, name, value in blocks[0][1] if name == "Content-Security-Policy"]
    if csp != [CSP] or sum(1 for line in lines if line.strip().startswith("Content-Security-Policy:")) != 1:
        raise BuildError("site/_headers does not carry exactly the Content-Security-Policy this site is built for")
    for pattern, headers in blocks:
        for _, name, value in headers:
            if name.lower() == "cache-control" and (pattern != ASSET_PATTERN or value != ASSET_CACHE):
                raise BuildError(
                    f"site/_headers sets Cache-Control to {value!r} for {pattern}: only {ASSET_PATTERN} is cached, "
                    f"as {ASSET_CACHE!r}; the pages and the data are checked again on every visit"
                )
    if not text.endswith("\n"):
        text += "\n"
    if noindex:
        lines = text.splitlines()
        after = blocks[0][1][-1][0] if blocks[0][1] else 0  # the last header line of the first block
        lines.insert(after + 1, "  X-Robots-Tag: noindex")
        text = "\n".join(lines) + "\n"
    return text


# ---- budgets ---------------------------------------------------------------------------------------------------------------------------


#: what the messages of :func:`check_budgets` call the entry pages
ENTRY_PAGE_NAMES = {"home": "home page", "notfound": "404 page"}
#: the entry pages that may carry no analytics beacon, and what marks one (the host it is loaded from, the script's name and the attribute that holds its token), in lower case
NO_BEACON = ("notfound",)
BEACON_MARKERS = ("cloudflareinsights", "beacon.min.js", "data-cf-beacon")


def _policy_problem(text: str) -> str | None:
    """What is wrong with the policy that a page gives in a ``<meta http-equiv="Content-Security-Policy">`` element, as a clause that follows the name of the page, or None when it is the one
    policy :data:`NOTFOUND_POLICY`, once, before the first stylesheet or script of the page (a policy governs what comes after it)."""
    metas = [
        found
        for found in re.finditer(r"<meta\b[^>]*>", text, re.IGNORECASE)
        if re.search(r"""http-equiv\s*=\s*["']content-security-policy["']""", found.group(0), re.IGNORECASE)
    ]
    if len(metas) != 1:
        return f"has {len(metas)} <meta> policies, and needs one: {NOTFOUND_POLICY!r}"
    content = re.search(r"""\bcontent\s*=\s*(?:"([^"]*)"|'([^']*)')""", metas[0].group(0), re.IGNORECASE)
    value = None if content is None else html_module.unescape(content.group(1) if content.group(1) is not None else content.group(2))
    if value is None or " ".join(value.split()) != NOTFOUND_POLICY:
        return f"has a <meta> policy of {value!r}, and needs {NOTFOUND_POLICY!r}: it adds to the header's, so nothing on the page can load a script of another site or send anything"
    loads = [found.start() for found in re.finditer(r"<(?:link|script)\b", text, re.IGNORECASE)]
    if loads and metas[0].start() > min(loads):
        return "has its policy after the first thing it loads, which the policy then does not govern"
    return None


def _gzip_size(content_bytes: bytes) -> int:
    return len(gzip.compress(content_bytes, 9, mtime=0))


def check_budgets(
    files: Mapping[str, bytes],
    *,
    trio_pages: Sequence[str],
    first_load_assets: Mapping[str, Sequence[str]],
    item_pages: Sequence[str] = (),
    entry_pages: Mapping[str, str] | None = None,
) -> dict[str, int]:
    """Measure the page budgets; raise :class:`BudgetError` naming each that is broken.

    Returns the sizes of the largest trio page: ``trio_html`` (raw), the gzip sizes of its HTML, stylesheet and scripts
    (``first_load_*``; WebAssembly is not loaded on a first view) and the raw size of its scripts (``first_load_js``), what is loaded on
    first use, raw and gzipped, in all (``lazy_js``, ``lazy_js_gzip``: the scripts directly under ``assets/`` that no page loads by itself, and their stylesheets) and for the
    largest chunk of it (``lazy_chunk_js``, ``lazy_chunk_js_gzip``; ``lazy_chunks`` counts them: a chunk is a script and the stylesheet beside it), all the JavaScript but the
    optimizer's, raw (``total_js``: reported, no budget), the largest shard raw and gzipped, and ``first_view_gzip``: the first load plus the largest shard, the weight of a first switch.

    ``item_pages`` are the pages of the items (``item/<key>/index.html``): each has :data:`LIMITS` ``item_html`` bytes raw and ``item_html_gzip`` gzipped, and loads the files that
    ``first_load_assets`` gives it (the stylesheet, the boot script and the page script that every page loads) and nothing else, in two scripts: a page of an item that named another file
    (the chunk of the Upgrade section, say) or carried a script of its own would load more than the first load the budgets count. ``item_pages`` is their number, ``largest_item`` and
    ``largest_item_gzip`` the sizes of the largest.

    ``entry_pages`` are the two pages that have a first load of their own, by label: ``{"home": "index.html", "notfound": "404.html"}``. Each is held to the limits of its label
    (``home_html``, ``home_html_gzip``; ``notfound_html``, ``notfound_html_gzip``) and to the budgets of a first load, and loads the files ``first_load_assets`` gives it and nothing else, in two
    scripts: a page that named another file, or carried a script of its own, would load more than its first load. The 404 page has its own script in place of the page script, and may carry no
    analytics beacon (:data:`BEACON_MARKERS`): it has no guard for a kit link in its address, which the beacon would see. It must also give its own policy, :data:`NOTFOUND_POLICY`, once, in a
    meta element before the first stylesheet or script, which keeps a beacon that the host puts into it from loading or sending anything even where the header would allow it. Sizes are reported as ``<label>_html``, ``<label>_html_gzip`` and
    ``<label>_first_load_gzip`` (the page's HTML, stylesheet and scripts, gzipped).

    Every script in ``files`` is counted by one budget or another: the first load's (the files the pages name in ``first_load_assets``), the code loaded on first
    use, or the optimizer's client and worker. A script that is none of them (at the root of the site, in a folder of its own below ``assets/``, or in the optimizer's
    folder under another name) is a budget broken: it is named.
    """
    problems: list[str] = []
    sizes = {
        "trio_html": 0,
        "first_load_html_gzip": 0,
        "first_load_css_gzip": 0,
        "first_load_js": 0,
        "first_load_js_gzip": 0,
        "first_load_gzip": 0,
    }
    worst = ""
    for page in trio_pages:
        html = files[page]
        loaded = first_load_assets[page]
        html_gz = _gzip_size(html)
        css_gz = sum(_gzip_size(files[a]) for a in loaded if a.endswith(".css"))
        js_gz = sum(_gzip_size(files[a]) for a in loaded if a.endswith(".js"))
        js_raw = sum(len(files[a]) for a in loaded if a.endswith(".js"))
        if len(html) > sizes["trio_html"] or not worst:
            worst = page
            sizes.update(
                trio_html=len(html),
                first_load_html_gzip=html_gz,
                first_load_css_gzip=css_gz,
                first_load_js=js_raw,
                first_load_js_gzip=js_gz,
                first_load_gzip=html_gz + css_gz + js_gz,
            )
        if len(html) > LIMITS["trio_html"]:
            problems.append(f"trio page HTML {page} is {len(html) / 1024:.1f} KB (limit {LIMITS['trio_html'] // 1024} KB)")
        if js_raw > LIMITS["first_load_js"]:
            problems.append(f"first-load JS of {page} is {js_raw / 1024:.1f} KB raw (limit {LIMITS['first_load_js'] // 1024} KB)")
        if js_gz > LIMITS["first_load_js_gzip"]:
            problems.append(f"first-load JS of {page} is {js_gz / 1024:.1f} KB gzip (limit {LIMITS['first_load_js_gzip'] // 1024} KB)")
        if html_gz + css_gz + js_gz > LIMITS["first_load_gzip"]:
            problems.append(
                f"first load of {page} is {(html_gz + css_gz + js_gz) / 1024:.1f} KB gzip (limit {LIMITS['first_load_gzip'] // 1024} KB)"
            )
    # the optimizer is loaded on request: its files are not JavaScript on a page, they have their own budgets
    engine = {name: content_bytes for name, content_bytes in files.items() if name.startswith(f"{ENGINE_DIR}/")}
    # What a page loads only when its Upgrade section is used: every script directly under assets/ that no page loads by itself, and the stylesheet esbuild writes for a chunk. The
    # scripts are the first load, this, and the optimizer's client and worker, exactly: one that none of the budgets counts is refused, not only reported.
    first_load = {name for names in first_load_assets.values() for name in names}
    scripts = {name for name in files if name.endswith(_SCRIPT_SUFFIXES)}
    lazy = {name: content_bytes for name, content_bytes in files.items() if _LAZY_FILE.fullmatch(name) and name not in first_load}
    uncounted = sorted(name for name in scripts if name not in first_load and name not in lazy and not _ENGINE_SCRIPT.fullmatch(name))
    if uncounted:
        problems.append("JavaScript that no budget counts: " + ", ".join(uncounted))
    sizes["total_js"] = sum(len(files[name]) for name in scripts if name in first_load or name in lazy)
    sizes["lazy_js"] = sum(len(content_bytes) for content_bytes in lazy.values())
    sizes["lazy_js_gzip"] = sum(_gzip_size(content_bytes) for content_bytes in lazy.values())
    chunks = _lazy_chunks(lazy)
    raw_of = {key: sum(len(lazy[name]) for name in names) for key, names in chunks.items()}
    gzip_of = {key: sum(_gzip_size(lazy[name]) for name in names) for key, names in chunks.items()}
    sizes["lazy_chunks"] = len(chunks)
    sizes["lazy_chunk_js"] = max(raw_of.values(), default=0)
    sizes["lazy_chunk_js_gzip"] = max(gzip_of.values(), default=0)
    for key in sorted(chunks):
        if raw_of[key] > LIMITS["lazy_chunk_js"]:
            problems.append(f"the chunk {key} of the code loaded on first use is {raw_of[key] / 1024:.1f} KB raw (limit {LIMITS['lazy_chunk_js'] // 1024} KB for a chunk)")
        if gzip_of[key] > LIMITS["lazy_chunk_js_gzip"]:
            problems.append(f"the chunk {key} of the code loaded on first use is {gzip_of[key] / 1024:.1f} KB gzip (limit {LIMITS['lazy_chunk_js_gzip'] // 1024} KB for a chunk)")
    if sizes["lazy_js"] > LIMITS["lazy_total_js"]:
        problems.append(f"the code loaded on first use is {sizes['lazy_js'] / 1024:.1f} KB raw in all its chunks (limit {LIMITS['lazy_total_js'] // 1024} KB)")
    for role in ("client", "worker"):
        sizes[f"engine_{role}_gzip"] = sum(_gzip_size(c) for name, c in engine.items() if name.startswith(f"{ENGINE_DIR}/{role}-") and name.endswith(".js"))
    sizes["engine_js_gzip"] = sizes["engine_client_gzip"] + sizes["engine_worker_gzip"]
    evaluators = [c for name, c in engine.items() if name.startswith(f"{ENGINE_DIR}/kitvalue-") and name.endswith(".js")]
    sizes["engine_kitvalue"] = sum(len(c) for c in evaluators)
    sizes["engine_kitvalue_gzip"] = sum(_gzip_size(c) for c in evaluators)
    sizes["engine_wasm"] = sum(len(c) for name, c in engine.items() if name.endswith(".wasm"))
    if sizes["engine_js_gzip"] > LIMITS["engine_js_gzip"]:
        problems.append(f"engine JS is {sizes['engine_js_gzip'] / 1024:.1f} KB gzip (limit {LIMITS['engine_js_gzip'] // 1024} KB)")
    if sizes["engine_kitvalue"] > LIMITS["engine_kitvalue"]:
        problems.append(f"the evaluator of a shared kit is {sizes['engine_kitvalue'] / 1024:.1f} KB raw (limit {LIMITS['engine_kitvalue'] // 1024} KB)")
    if sizes["engine_kitvalue_gzip"] > LIMITS["engine_kitvalue_gzip"]:
        problems.append(f"the evaluator of a shared kit is {sizes['engine_kitvalue_gzip'] / 1024:.1f} KB gzip (limit {LIMITS['engine_kitvalue_gzip'] // 1024} KB)")
    if sizes["engine_wasm"] > LIMITS["engine_wasm"]:
        problems.append(
            f"engine WebAssembly is {sizes['engine_wasm'] / 1024 / 1024:.2f} MB (limit {LIMITS['engine_wasm'] // 1024 // 1024} MB)"
        )
    shards = {name: content_bytes for name, content_bytes in files.items() if _SHARD_FILE.fullmatch(name)}
    sizes["largest_shard"] = max((len(content_bytes) for content_bytes in shards.values()), default=0)
    sizes["largest_shard_gzip"] = max((_gzip_size(content_bytes) for content_bytes in shards.values()), default=0)
    sizes["first_view_gzip"] = sizes["first_load_gzip"] + sizes["largest_shard_gzip"]
    for name, content_bytes in sorted(shards.items()):
        if len(content_bytes) > LIMITS["shard"]:
            problems.append(f"shard {name} is {len(content_bytes) / 1024:.1f} KB (limit {LIMITS['shard'] // 1024} KB)")
        zipped = _gzip_size(content_bytes)
        if zipped > LIMITS["shard_gzip"]:
            problems.append(f"shard {name} is {zipped / 1024:.1f} KB gzip (limit {LIMITS['shard_gzip'] // 1024} KB)")
    # a role's runner-up file is fetched whole as well, and has every tier of the run in it: it is held to the budget of a shard
    runnerups = {name: content_bytes for name, content_bytes in files.items() if _RUNNERUP_FILE.fullmatch(name)}
    sizes["largest_runnerup"] = max((len(content_bytes) for content_bytes in runnerups.values()), default=0)
    sizes["largest_runnerup_gzip"] = max((_gzip_size(content_bytes) for content_bytes in runnerups.values()), default=0)
    for name, content_bytes in sorted(runnerups.items()):
        if len(content_bytes) > LIMITS["shard"]:
            problems.append(f"runner-up file {name} is {len(content_bytes) / 1024:.1f} KB (limit {LIMITS['shard'] // 1024} KB)")
        zipped = _gzip_size(content_bytes)
        if zipped > LIMITS["shard_gzip"]:
            problems.append(f"runner-up file {name} is {zipped / 1024:.1f} KB gzip (limit {LIMITS['shard_gzip'] // 1024} KB)")
    # the files of the section Effects to exalt (the page fetches both once it has shown, when the browser is idle, and not in the first load): their size is the weight of the section
    shared = {name: content_bytes for name, content_bytes in files.items() if _EFFECTS_FILE.fullmatch(name)}
    exalts = {name: content_bytes for name, content_bytes in files.items() if _EXALT_FILE.fullmatch(name)}
    sizes["effects"] = max((len(content_bytes) for content_bytes in shared.values()), default=0)
    sizes["effects_gzip"] = max((_gzip_size(content_bytes) for content_bytes in shared.values()), default=0)
    sizes["largest_exalt"] = max((len(content_bytes) for content_bytes in exalts.values()), default=0)
    sizes["largest_exalt_gzip"] = max((_gzip_size(content_bytes) for content_bytes in exalts.values()), default=0)
    sizes["exalt_files"] = len(exalts)
    for name, content_bytes in sorted(shared.items()):
        if len(content_bytes) > LIMITS["effects"]:
            problems.append(f"effects file {name} is {len(content_bytes) / 1024:.1f} KB (limit {LIMITS['effects'] // 1024} KB)")
        if _gzip_size(content_bytes) > LIMITS["effects_gzip"]:
            problems.append(f"effects file {name} is {_gzip_size(content_bytes) / 1024:.1f} KB gzip (limit {LIMITS['effects_gzip'] // 1024} KB)")
    for name, content_bytes in sorted(exalts.items()):
        if _gzip_size(content_bytes) > LIMITS["exalt_gzip"]:
            problems.append(f"exalt file {name} is {_gzip_size(content_bytes) / 1024:.1f} KB gzip (limit {LIMITS['exalt_gzip'] // 1024} KB)")
    if exalts and not shared:
        problems.append("the exalt files of the trios have no effects file to go with them")
    sizes["item_pages"] = len(item_pages)
    sizes["largest_item"] = sizes["largest_item_gzip"] = 0
    for page in item_pages:
        html = files[page]
        zipped = _gzip_size(html)
        sizes["largest_item"] = max(sizes["largest_item"], len(html))
        sizes["largest_item_gzip"] = max(sizes["largest_item_gzip"], zipped)
        if len(html) > LIMITS["item_html"]:
            problems.append(f"item page {page} is {len(html) / 1024:.1f} KB (limit {LIMITS['item_html'] // 1024} KB)")
        if zipped > LIMITS["item_html_gzip"]:
            problems.append(f"item page {page} is {zipped / 1024:.1f} KB gzip (limit {LIMITS['item_html_gzip'] // 1024} KB)")
        text = html.decode("utf-8", errors="replace")
        wanted = {"/" + name for name in first_load_assets[page]}
        named = set(_ASSET_REFERENCE.findall(text))
        if named - wanted:
            problems.append(f"item page {page} loads {', '.join(sorted(named - wanted))}, which is not part of the first load every page has")
        if wanted - named:
            problems.append(f"item page {page} does not load {', '.join(sorted(wanted - named))}, which every page does")
        scripts = len(re.findall(r"<script\b", text))
        if scripts != 2:
            problems.append(f"item page {page} has {scripts} scripts (the boot script and the page script, 2)")
    for label, page in (entry_pages or {}).items():
        what = ENTRY_PAGE_NAMES[label]
        html = files[page]
        loaded = first_load_assets[page]
        html_gz = _gzip_size(html)
        css_gz = sum(_gzip_size(files[a]) for a in loaded if a.endswith(".css"))
        js_gz = sum(_gzip_size(files[a]) for a in loaded if a.endswith(".js"))
        js_raw = sum(len(files[a]) for a in loaded if a.endswith(".js"))
        sizes[f"{label}_html"], sizes[f"{label}_html_gzip"] = len(html), html_gz
        sizes[f"{label}_first_load_gzip"] = html_gz + css_gz + js_gz
        if len(html) > LIMITS[f"{label}_html"]:
            problems.append(f"{what} {page} is {len(html) / 1024:.1f} KB (limit {LIMITS[f'{label}_html'] // 1024} KB)")
        if html_gz > LIMITS[f"{label}_html_gzip"]:
            problems.append(f"{what} {page} is {html_gz / 1024:.1f} KB gzip (limit {LIMITS[f'{label}_html_gzip'] // 1024} KB)")
        if js_raw > LIMITS["first_load_js"]:
            problems.append(f"first-load JS of {page} is {js_raw / 1024:.1f} KB raw (limit {LIMITS['first_load_js'] // 1024} KB)")
        if js_gz > LIMITS["first_load_js_gzip"]:
            problems.append(f"first-load JS of {page} is {js_gz / 1024:.1f} KB gzip (limit {LIMITS['first_load_js_gzip'] // 1024} KB)")
        if html_gz + css_gz + js_gz > LIMITS["first_load_gzip"]:
            problems.append(f"first load of {page} is {(html_gz + css_gz + js_gz) / 1024:.1f} KB gzip (limit {LIMITS['first_load_gzip'] // 1024} KB)")
        text = html.decode("utf-8", errors="replace")
        wanted = {"/" + name for name in loaded}
        named = set(_ASSET_REFERENCE.findall(text))
        if named - wanted:
            problems.append(f"{what} {page} loads {', '.join(sorted(named - wanted))}, which is not part of its first load")
        if wanted - named:
            problems.append(f"{what} {page} does not load {', '.join(sorted(wanted - named))}, which its first load is made of")
        scripts = len(re.findall(r"<script\b", text))
        if scripts != 2:
            problems.append(f"{what} {page} has {scripts} scripts (the boot script and its own page script, 2)")
        if label in NO_BEACON:
            beacon = next((marker for marker in BEACON_MARKERS if marker in text.lower()), None)
            if beacon is not None:
                problems.append(f"{what} {page} carries an analytics beacon ({beacon}): it has no guard for a kit link in its address, which a beacon would see")
            policy = _policy_problem(text)
            if policy is not None:
                problems.append(f"{what} {page} {policy}")
    sizes["art"] = sum(len(content_bytes) for name, content_bytes in files.items() if name.startswith("assets/") and name.endswith(".png"))
    if sizes["art"] > LIMITS["art"]:
        problems.append(f"the art is {sizes['art'] / 1024:.1f} KB in all (limit {LIMITS['art'] // 1024} KB)")
    sizes["files"] = len(files)
    if len(files) > LIMITS["files"]:
        problems.append(f"the site has {len(files):,} files (limit {LIMITS['files']:,})")
    # the data files the optimizer's worker fetches for a visitor's own gear: the item table of the site, and the bundle of each trio
    sizes["engine_items"] = sizes["engine_items_gzip"] = sizes["engine_bundle"] = 0
    for name, content_bytes in sorted(files.items()):
        found = _ENGINE_DATA_NAME.fullmatch(name)
        if found is None:
            continue
        zipped = _gzip_size(content_bytes)
        if name.startswith(f"{ENGINE_DATA_DIR}/items-"):
            sizes["engine_items"], sizes["engine_items_gzip"] = len(content_bytes), zipped
            if len(content_bytes) > LIMITS["engine_items"]:
                problems.append(f"the item table {name} is {len(content_bytes) / 1024 / 1024:.2f} MB (limit {LIMITS['engine_items'] // 1024 // 1024} MB)")
            if zipped > LIMITS["engine_items_gzip"]:
                problems.append(f"the item table {name} is {zipped / 1024:.1f} KB gzip (limit {LIMITS['engine_items_gzip'] // 1024} KB gzip)")
        else:
            sizes["engine_bundle"] = max(sizes["engine_bundle"], len(content_bytes))
            if len(content_bytes) > LIMITS["engine_bundle"]:
                problems.append(f"the bundle {name} is {len(content_bytes) / 1024:.1f} KB (limit {LIMITS['engine_bundle'] // 1024} KB)")
    manifest_sizes, manifest_problems = _manifest_sizes(files)
    sizes.update(manifest_sizes)
    problems.extend(manifest_problems)
    if problems:
        raise BudgetError("over budget: " + "; ".join(problems))
    return sizes


#: the pages of the site that no trio and no item has, as the files they are written to
FIXED_PAGES = ("index.html", "404.html", "about/index.html", "changelog/index.html", "rules/index.html", "sources/index.html")
#: stands for the digest in the name of an engine data file (``items-<hash>.json``), which is known only once the file is made
HASH_PLACEHOLDER = "<hash>"
_ITEM_KEY = re.compile(data.KEY_PATTERN)  # the one pattern of an item key: the reader of the results takes these and no others
#: the evidence levels of the item table whose items get a page of their own: the others (disputed and hidden) have none, and nothing links to them
ITEM_PAGE_LEVELS = ("strict", "wiki")
#: the slots of the places of a kit, which an item must list to be a wearable (equal to ``trioforge.precompute.grid.WEARABLE_SLOTS``; a test says so)
WEARABLE_SLOTS = frozenset(data.SLOT_INSTANCES)


def _record_key(record: Mapping[str, Any]) -> Any:
    """The item key of a record of the item table: its ``key``, else ``w`` and the number of its wiki page."""
    return record["key"] if record.get("key") is not None else f"w{record['id']}"


def item_page_keys(table: Mapping[str, Any]) -> list[str]:
    """The keys of the items that get a page, sorted: every wearable (it lists a slot of a place of a kit) whose evidence level in ``table``, the item table of the results (its
    ``items``; the release's own levels, and never a private flag), is ``strict`` or ``wiki``. A disputed or a hidden item gets none. The list feeds :func:`site_files` (``item_pages``),
    so the files of a site are counted exactly. A key of a page that is not an item key (:data:`_ITEM_KEY`, the reader's own pattern, which is also one segment of an address) is a
    :class:`BuildError`, and so is a key that two records of the table have, whatever their levels and slots: the page of a key is built from the record that a lookup by the key keeps, so
    a twin that gets no page of its own (a hidden, a disputed or a non-wearable record) would still decide it."""
    keys: list[str] = []
    every: Counter[str] = Counter()
    for record in table["items"]:
        key = _record_key(record)
        if isinstance(key, str):
            every[key] += 1
        if record["evidence"]["level"] not in ITEM_PAGE_LEVELS or not WEARABLE_SLOTS & set(record["slots"]):
            continue
        if not isinstance(key, str) or _ITEM_KEY.fullmatch(key) is None:
            raise BuildError(f"{key!r} is not an item key (small letters, digits and hyphens)")
        keys.append(key)
    twice = sorted(key for key, count in every.items() if count > 1)
    if twice:
        raise BuildError(f"the item {twice[0]} twice in the item table")
    return sorted(keys)


@dataclass(frozen=True)
class TrioFiles:
    """What the list of the files of a site needs to know of a trio: its code, the ``roles`` it is offered (a runner-up file for each), its tier
    ``scope`` (``tiers``, ascending: the tiers its run was given) and the character ``levels`` it has a bundle for.

    The tiers are an input so that a layout that made a file of a tier would show up in the list; today they change no count, since a tier is a
    row in the files of a trio and not a file of its own."""

    slug: str
    roles: tuple[str, ...]
    tiers: tuple[int, ...]
    levels: tuple[int, ...] = (50,)
    exalt: bool = False  # whether the trio has the file of the effects layer (``data/<trio>/exalt.json``, which makes the section Effects to exalt of its page)

    def check(self) -> None:
        """Refuse a trio that no build could have: the code, each role once, an ascending scope of real tiers, each level once."""
        if not isinstance(self.slug, str) or not _TRIO_SLUG.fullmatch(self.slug):
            raise BuildError(f"{self.slug!r} is not the code of a trio (three groups of three small letters, such as pal-mnk-ber)")
        if not self.roles:
            raise BuildError(f"the trio {self.slug} has no role: it would have no runner-up file")
        for role in self.roles:
            if role not in data.ROLES:
                raise BuildError(f"the trio {self.slug} lists {role!r}, which is not a role ({', '.join(data.ROLES)})")
            if self.roles.count(role) > 1:
                raise BuildError(f"the trio {self.slug} lists the role {role} twice")
        if not self.tiers:
            raise BuildError(f"the trio {self.slug} has no tier in its scope")
        for tier in self.tiers:
            if isinstance(tier, bool) or not isinstance(tier, int) or not 0 <= tier <= data.MAX_TIER:
                raise BuildError(f"the trio {self.slug} lists {tier!r} in its scope, which is not a tier (0 to {data.MAX_TIER})")
        if list(self.tiers) != sorted(set(self.tiers)):
            raise BuildError(f"the scope of the trio {self.slug} must list its tiers in ascending order, each once")
        if not self.levels:
            raise BuildError(f"the trio {self.slug} has no level: it would have no bundle")
        for level in self.levels:
            if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= MANIFEST_MAX_LEVEL:
                raise BuildError(f"the trio {self.slug} lists {level!r} as a level, which is not a level (1 to {MANIFEST_MAX_LEVEL})")
            if self.levels.count(level) > 1:
                raise BuildError(f"the trio {self.slug} lists the level {level} twice")

    def files(self) -> list[str]:
        """The files of the site that are this trio's: its page, the four shards, a runner-up file for each role, the seals, the manifest of the
        trio and a bundle for each level (named with :data:`HASH_PLACEHOLDER`)."""
        self.check()
        names = [f"trio/{self.slug}/index.html"]
        names += [f"data/{self.slug}/{evidence}-{buffs}.json" for evidence in data.EVIDENCE for buffs in data.BUFFS]
        names += [f"data/{self.slug}/runnerups/{role}.json" for role in self.roles]
        names += [f"data/{self.slug}/robust.json", trio_manifest_name(self.slug)]
        if self.exalt:
            names.append(f"data/{self.slug}/{data.EXALT_NAME}")
        names += [f"{ENGINE_DATA_DIR}/{self.slug}-l{level}-{HASH_PLACEHOLDER}.json" for level in self.levels]
        return names


def site_files(
    trios: Iterable[TrioFiles], *, assets: Sequence[str], item_pages: Iterable[str] = (), noindex: bool = False
) -> list[str]:
    """The exact list of the files of a built site, from what the build is given, and not from a smaller build.

    ``trios`` are the trios of the site (:class:`TrioFiles`), ``assets`` the files of the page code (the names under ``assets/`` that
    :func:`bundle_assets` makes: the stylesheet, the scripts, the optimizer's scripts and WebAssembly), ``item_pages`` the keys of the items that
    get a page of their own (``item/<key>/index.html``) and ``noindex`` whether the site is a preview (an indexable one has a sitemap). The fixed
    pages, ``_headers``, ``robots.txt``, the manifest of the optimizer and its item table are always there. A name that carries the digest of
    its file (an engine data file) is given with :data:`HASH_PLACEHOLDER` in its place. No name is in the list twice: a trio, an item or an asset
    given twice is a :class:`BuildError`, and so is a trio that no build could have. The number of files is ``len`` of the list, and
    :func:`check_file_budget` holds it to the budget of the site."""
    names = list(FIXED_PAGES)
    names += ["_headers", "robots.txt", MANIFEST_FILE]
    if not noindex:
        names.append("sitemap.xml")
    if not assets:
        raise BuildError("a site has files of the page code, and no file of the page code is given")
    for asset in assets:
        if not isinstance(asset, str) or not asset.startswith("assets/"):
            raise BuildError(f"{asset!r} is not under assets/, where the files of the page code are")
        if asset.startswith(f"{ENGINE_DATA_DIR}/"):
            raise BuildError(f"{asset} belongs to the data of a trio or to the item table, which the list makes itself")
    names += list(assets)
    names.append(f"{ENGINE_DATA_DIR}/items-{HASH_PLACEHOLDER}.json")
    trios = list(trios)
    if any(trio.exalt for trio in trios):
        names.append(f"data/{data.EFFECTS_NAME}")  # (the one file of the effects that the trios with an exalt file share)
    seen_trios: set[str] = set()
    for trio in trios:
        if trio.slug in seen_trios:
            raise BuildError(f"the trio {trio.slug} twice")
        seen_trios.add(trio.slug)
        names += trio.files()
    seen_items: set[str] = set()
    for key in item_pages:
        if not isinstance(key, str) or not _ITEM_KEY.fullmatch(key):
            raise BuildError(f"{key!r} is not an item key (small letters, digits and hyphens)")
        if key in seen_items:
            raise BuildError(f"the item page {key} twice")
        seen_items.add(key)
        names.append(f"item/{key}/index.html")
    listed: set[str] = set()
    for name in names:
        if name in listed:
            raise BuildError(f"{name} is in the list twice")
        listed.add(name)
    return names


def revision_rows(keys: Iterable[str], manifest: content.Manifest, pages: Collection[str]) -> list[SimpleNamespace]:
    """The rows of the table of wiki revisions on the sources page, sorted by title: the item ``key``, the wiki page's ``title`` and ``revid``, the ``url`` of that revision and the
    address of the item's own ``page`` (None where the item has no page of its own: its title stays plain text)."""
    rows = [
        SimpleNamespace(
            key=key,
            title=manifest.items[key][0],
            revid=manifest.items[key][1],
            url=content.wiki_url(*manifest.items[key]),
            page=view.item_href(key) if key in pages else None,
        )
        for key in keys
    ]
    return sorted(rows, key=lambda row: (row.title.lower(), row.key))


def eqlt_item_rows(keys: Iterable[str], manifest: content.Manifest, pages: Collection[str]) -> list[SimpleNamespace]:
    """The rows of the table of items read from EQ Legends Tools on the sources page, sorted by name: the item ``key``, its ``name``, the ``url`` of its page at that site and the
    address of the item's own ``page`` here (None where it has none)."""
    rows = [
        SimpleNamespace(key=key, name=manifest.eqlt[key][0], url=content.eqlt_item_url(manifest.eqlt[key][1]), page=view.item_href(key) if key in pages else None)
        for key in keys
    ]
    return sorted(rows, key=lambda row: (row.name.lower(), row.key))


def _tiers_text(tiers: Iterable[int]) -> str:
    return ", ".join(f"+{tier}" for tier in tiers) or "none"


def check_scope(slug: str, tiers: Sequence[int], wanted: Sequence[int] | None = None) -> None:
    """Hold a trio to the tiers of a full run of it, or refuse it with a :class:`BuildError` that says both lists and the way out.

    ``tiers`` are the tiers its shards have. A run of any tiers is a full one (the tiers are the scope of the run), so this is where an indexable
    site is kept from a milestone trio with three tiers, or a trio of the grid with no +10: ``wanted`` is the tiers it must have, which are
    :func:`trioforge.scope.default_tiers` of the slug when it is None (a sample says which scope it stands for). The check of a release calls this
    for each trio of the release."""
    try:
        expected = tier_scope.default_tiers(slug) if wanted is None else tuple(sorted(wanted))
    except ValueError as error:
        raise BuildError(f"{slug}: {error}") from None
    if sorted(tiers) != list(expected):  # (the tiers are a set: the order they are listed in does not matter)
        raise BuildError(
            f"{slug}: its shards have the tiers {_tiers_text(tiers)}, but an indexable build needs {_tiers_text(expected)} for this trio "
            "(the tiers of a full run of it): run the precompute with that scope, or build with --noindex for a preview"
        )


def check_scopes(trios: Iterable[data.TrioResults], scopes: Mapping[str, Sequence[int]] | None = None) -> None:
    """:func:`check_scope` for each trio of the results; ``scopes`` names, by slug, the tiers a trio needs where they are not the default.

    A scope named for a trio that is not in the results is a :class:`BuildError` as well: it would otherwise be a mistake that passes."""
    listed = list(trios)
    named = dict(scopes or {})
    for slug in named:
        if slug not in {trio.meta.slug for trio in listed}:
            raise BuildError(f"{slug} is not a trio of the results, and a scope was named for it")
    for trio in listed:
        try:
            tiers = trio.tiers  # the one list the shards and the runner-up files all hold, and not the first shard's
        except data.ResultsError as error:
            raise BuildError(str(error)) from None
        check_scope(trio.meta.slug, tiers, named.get(trio.meta.slug))


def page_code_files() -> tuple[str, ...]:
    """The names of the files of the page code as a build makes them (under ``assets/``, hashed), for :func:`site_files`: the stylesheet, the page
    scripts, the optimizer's scripts and WebAssembly. It bundles the page code, so it needs Node and esbuild, as a build does."""
    return tuple(sorted(bundle_assets()[1]))


def check_file_budget(names: Sequence[str]) -> int:
    """Hold the list of the files of a site (:func:`site_files`) to the budget of the number of files (:data:`LIMITS`), and say how many there are;
    a :class:`BudgetError` gives the count."""
    if len(names) > LIMITS["files"]:
        raise BudgetError(f"over budget: the site has {len(names):,} files (limit {LIMITS['files']:,})")
    return len(names)


def _manifest_sizes(files: Mapping[str, bytes]) -> tuple[dict[str, int], list[str]]:
    """The size of the main manifest and the largest manifest of a trio, and a line for each that is over the limit of the browser."""
    sizes = {"manifest": 0, "trio_manifest": 0}
    problems: list[str] = []
    main = files.get(MANIFEST_FILE)
    if main is not None:
        sizes["manifest"] = len(main)
        if len(main) > LIMITS["manifest"]:
            problems.append(f"{MANIFEST_FILE} is {len(main)} bytes (limit {LIMITS['manifest']} bytes): the page and the worker refuse a larger one")
    for name, raw in sorted(files.items()):
        if not name.startswith(f"{TRIO_MANIFEST_DIR}/"):
            continue
        sizes["trio_manifest"] = max(sizes["trio_manifest"], len(raw))
        if len(raw) > LIMITS["trio_manifest"]:
            problems.append(f"{name} is {len(raw)} bytes (limit {LIMITS['trio_manifest']} bytes): the worker refuses a larger one")
    return sizes, problems


def check_manifest_sizes(files: Mapping[str, bytes]) -> dict[str, int]:
    """Hold the manifests among ``files`` (the main one and one for each trio) to the limits of the browser's readers; raise
    :class:`BudgetError` naming each file that is over. Returns ``manifest`` (the size of the main one) and ``trio_manifest`` (the largest)."""
    sizes, problems = _manifest_sizes(files)
    if problems:
        raise BudgetError("over budget: " + "; ".join(problems))
    return sizes


# ---- checks on the inputs ---------------------------------------------------------------------------------------------------------


#: the rows hold F to two decimals and the margin is rounded to two as well, each from the exact value, so a margin and the
#: difference of two rows can be 0.015 apart; the tolerance is a little more than that. The setup of the answer needs none (see
#: :func:`check_defaults`): rounding keeps the order, so the setup the precompute chose by the exact F has the highest F in the rows too.
MARGIN_TOLERANCE = 0.016


def check_defaults(results: data.TrioResults) -> None:
    """The page states the best race as an answer, so it must be the right one: the creation-legal race with the highest
    value in the default view (``defaults.json``: its role, tier, evidence level and buffs), the runner-up the next, the margin
    their difference, and the setup and value those of the best race, all as the rows say.

    The setup is compared with no slack for rounding. The answer's setup is the best one by the precompute's exact F, the rows hold
    that F rounded to two decimals, and rounding keeps the order: no other setup of the race can have a higher F in the rows, so the
    setup of the answer must have the highest (a tie of two rounded values is no error, the rows cannot tell them apart).

    Whatever is wrong with the results is a :class:`BuildError` that names the trio: a lookup that finds nothing is an error with
    a message and not a ``KeyError``, and nothing here is an ``assert`` (``python -O`` removes those)."""
    meta, defaults = results.meta, results.defaults
    slug = meta.slug
    level = f"{defaults.evidence}-{defaults.buffs}"
    shard = results.shards.get((defaults.evidence, defaults.buffs))
    if shard is None:
        raise BuildError(f"{slug}: there is no {level} shard, which the default view is taken from")
    role, tier = defaults.role, defaults.tier
    if role not in shard.roles:
        raise BuildError(f"{slug}: {level}.json has no {role} role, which the default view is")
    if tier not in shard.tiers:
        raise BuildError(f"{slug}: {level}.json has no +{tier} tier, which the default view is")
    for what, race in (("default", defaults.race), ("runner-up", defaults.runner_up)):
        if race not in shard.races:
            raise BuildError(f"{slug}: the {what} race {race} has no rows in {level}.json")
    setups = shard.setups_for(role)
    if not setups:
        raise BuildError(f"{slug}: {level}.json has no weapon setup for the {role} role")
    rows: dict[str, dict[str, float]] = {}  # for each race, the F of each setup of the role in the default view
    for race in shard.races:
        rows[race] = {}
        for setup in setups:
            scenario = shard.scenario(race, role, tier, setup)
            if scenario is None:
                raise BuildError(f"{slug}: {level}.json has no row for {race} {role} +{tier} {setup}")
            rows[race][setup] = scenario.value
    value = {race: max(by_setup.values()) for race, by_setup in rows.items()}
    try:
        legal = {o.code: o.legal for o in view.race_options(shard.races, trio=meta.trio, best=defaults.race)}
        name = view.trio_name(meta.trio)
    except (KeyError, ValueError) as error:
        raise BuildError(f"{slug}: the tables of races and classes do not know a race or a class of {level}.json ({error})") from None
    if not legal[defaults.race]:
        raise BuildError(f"{slug}: the default race {defaults.race} cannot start a {name} at character creation")
    if not legal[defaults.runner_up]:
        raise BuildError(f"{slug}: the runner-up race {defaults.runner_up} cannot start a {name} at character creation")
    candidates = [race for race in shard.races if legal[race]]
    best = max(value[race] for race in candidates)
    if value[defaults.race] < best - 1e-6:
        top = max(candidates, key=lambda race: value[race])
        raise BuildError(f"{slug}: the default race {defaults.race} is not the creation-legal race with the highest value ({top})")
    others = sorted((race for race in candidates if race != defaults.race), key=lambda race: -value[race])
    if others and abs(value[defaults.runner_up] - value[others[0]]) > 1e-6:
        raise BuildError(f"{slug}: the runner-up race should be {others[0]}, not {defaults.runner_up}")
    gap = value[defaults.race] - value[defaults.runner_up]
    if abs(gap - defaults.margin) > MARGIN_TOLERANCE:
        raise BuildError(
            f"{slug}: the margin {defaults.margin} does not match the values ({gap:.3f} between {defaults.race} and {defaults.runner_up})"
        )
    chosen = rows[defaults.race].get(defaults.setup)
    if chosen is None or chosen < value[defaults.race]:
        raise BuildError(f"{slug}: the default setup {defaults.setup} is not the best setup of {defaults.race} for the {role} role at +{tier}")
    if abs(defaults.value - chosen) > MARGIN_TOLERANCE:
        raise BuildError(f"{slug}: the default value {defaults.value} does not match the rows ({chosen})")
    if defaults.why is not None:  # the why is of the kit of the default answer: place by place, the item it names is the one that kit wears
        scenario = shard.scenario(defaults.race, role, tier, defaults.setup)
        if scenario is None:
            raise BuildError(f"{slug}: {level}.json has no row for {defaults.race} {role} +{tier} {defaults.setup}")
        for n, (place, item) in enumerate(zip(defaults.why.places, scenario.kit, strict=True)):
            wears = None if item is None else item.key
            if (None if place is None else place.key) != wears:
                raise BuildError(
                    f"{slug}: defaults.json: why.places[{n}] is for {None if place is None else place.key}, but the default kit wears {wears} there: the files are not from one run"
                )


# ---- pages -----------------------------------------------------------------------------------------------------------------------


_CALENDAR_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _calendar_date(text: object, what: str) -> str:
    """``text`` when it is a calendar date written YYYY-MM-DD (the form a sitemap's ``lastmod`` takes), else a :class:`BuildError`.
    The results reader has checked the date already; this looks again at what the build writes for a crawler to read."""
    if isinstance(text, str) and _CALENDAR_DATE.fullmatch(text):
        try:
            datetime.date.fromisoformat(text)
        except ValueError:
            pass
        else:
            return text
    raise BuildError(f"{what} {text!r} is not a calendar date written YYYY-MM-DD")


def check_owner(owner: str | None, *, noindex: bool) -> str | None:
    """The GitHub account the report links point at, checked. An indexable build must be given one; a preview may do without
    (then the pages link to no repository). The placeholder of the repository files is refused in every build."""
    if owner is None:
        if noindex:
            return None
        raise BuildError(
            "an indexable build needs --owner NAME, the GitHub account that owns the project's repository: "
            "without it the report links would point at someone else's (or build with --noindex for a preview)"
        )
    if not isinstance(owner, str) or _OWNER.fullmatch(owner) is None:
        raise BuildError(
            "--owner must be the name of a GitHub account: letters, digits and single hyphens, no hyphen at either end, 39 characters at most"
        )
    if owner.lower() == PLACEHOLDER_OWNER:
        raise BuildError("--owner OWNER is the placeholder of the repository files, and a real account of someone else: give the project's own")
    return owner


def _issues_url(owner: str | None) -> str | None:
    return f"https://github.com/{owner}/{REPOSITORY}/issues" if owner else None


def _report_url(
    owner: str | None, site_url: str, path: str, subject: str, template: str, view: Mapping[str, object] | None = None
) -> str | None:
    """The address of a new issue about a page, or None while the project has no account to link to. A page that shows a view (the
    trio page) names it in the address of the page it reports: its race, role, tier, weapons, evidence and buffs, in this order. The
    page code rewrites that address when the visitor changes the view, with the same words (a test compares the two)."""
    base = _issues_url(owner)
    if base is None:
        return None
    address = site_url + path
    if view is not None:
        address += "?" + urlencode({key: view[key] for key in REPORT_VIEW})
    query = urlencode({"template": template, "title": f"Problem with {subject}", "page": address})
    return f"{base}/new?{query}"


def attribution_parts(text: str = ATTRIBUTION) -> tuple[tuple[str, str | None], ...]:
    """The attribution as pieces of ``(text, address)``, the names of the sources and the licence carrying their links. Put back to
    back the texts are the attribution again, to the letter (a test says so), so the footer shows the one text with links in it."""
    pieces: list[tuple[str, str | None]] = [(text, None)]
    for name, address in ATTRIBUTION_LINKS:
        split: list[tuple[str, str | None]] = []
        for chunk, link in pieces:
            if link is not None:
                split.append((chunk, link))
                continue
            for number, part in enumerate(chunk.split(name)):
                if number:
                    split.append((name, address))
                if part:
                    split.append((part, None))
        pieces = split
    return tuple(pieces)


def credit_of(meta: data.Meta) -> data.Credit:
    """What every data file says about itself."""
    return data.Credit(release=meta.data_tag, license=LICENCE_NAME, attribution=ATTRIBUTION)


def _nav(current: str) -> list[dict[str, object]]:
    items = [("/", "Trios"), ("/about/", "About"), ("/changelog/", "Changelog")]  # Rules and Sources are pages of the site but not of the menu (the footer links the sources, the trio pages link into the rules)
    return [{"href": href, "label": label, "current": href == current} for href, label in items]


def home_context(live: Sequence[Any]) -> dict[str, object]:
    """What the home page is given besides the frame: ``live`` (the trios the build made, each with its ``slug``, ``name`` and ``level``), the classes for the chips in the order of the site's
    classes, how many trios the grid has (so that the page can say that every one is ready) and whether the list of the pages is shown open (up to :data:`HOME_LIST_OPEN` trios) or
    folded into an expander."""
    return {
        "live": live,
        "classes": [SimpleNamespace(code=code, name=CLASS_NAMES[code]) for code in CLASS_CODES],
        "trio_total": math.comb(len(CLASS_CODES), 3),
        "list_open": len(live) <= HOME_LIST_OPEN,
    }


def notfound_context(live: Sequence[Any]) -> dict[str, object]:
    """What the 404 page is given besides the frame: ``live`` (the list in ``data-trios``, which its script checks an address against) and whether the page also names the trios it can open
    (up to :data:`NOT_FOUND_LISTED` of them: it is sent for every address that has no file)."""
    return {"live": live, "listed": 0 < len(live) <= NOT_FOUND_LISTED}


@dataclass(frozen=True)
class SiteBuild:
    """What a build made: the pages (path -> file), the sizes measured and the number of files written (the files of the output folder: the marker
    beside it is not one of them); ``partial`` names the trios whose results come from a narrowed precompute run (some races or roles are
    missing from their pages)."""

    pages: tuple[str, ...]
    files: int
    sizes: dict[str, int]
    out: Path
    partial: tuple[str, ...] = ()


def race_page_rows(races: content.Racials) -> list[SimpleNamespace]:
    """The rows of the sources page's table of race pages: the page, the revision and its address, and the race."""
    return [
        SimpleNamespace(code=page.race, title=page.title, revid=page.revid, url=page.url)
        for page in races.pages
    ]


def build(
    *,
    results: Path,
    out: Path,
    noindex: bool = False,
    site_url: str = DEFAULT_SITE_URL,
    rules: Path | None = None,
    sources_manifest: Path | None = None,
    racials: Path | None = None,
    changelog: Path | None = None,
    headers: Path | None = None,
    owner: str | None = None,
    scopes: Mapping[str, Sequence[int]] | None = None,
) -> SiteBuild:
    """Build the site (see the module docstring). ``scopes`` names, by slug, the tiers an indexable build needs a trio to have, where they are not
    those of a full run of it (:func:`check_scopes`); a preview needs none. The command line gives none."""
    results, out = Path(results), Path(out)
    rules = Path(rules) if rules else REPO_ROOT / "rules" / "rules.json"
    sources_manifest = Path(sources_manifest) if sources_manifest else REPO_ROOT / "derived" / "sources-manifest.json"
    racials = Path(racials) if racials else REPO_ROOT / "derived" / "racials.json"
    changelog = Path(changelog) if changelog else REPO_ROOT / "docs" / "CHANGELOG.md"
    headers = Path(headers) if headers else REPO_ROOT / "site" / "_headers"
    site_url = site_url.rstrip("/")

    # 1. read and check every input before anything is made
    slugs = data.list_trios(results)
    if not slugs:
        raise BuildError(f"no results: {results} has no trio folder with shards")
    owner = check_owner(owner, noindex=noindex)
    trios = [data.load_trio(results / slug) for slug in slugs]
    items = data.load_items(results, trios)
    partial = tuple(t.meta.slug for t in trios if t.meta.partial)
    if partial and not noindex:
        raise BuildError(
            f"{partial[0]} was made from a partial precompute run (a narrowed grid), which can only make a preview: "
            "run the precompute for the whole grid, or build with --noindex"
        )
    if not noindex:
        check_scopes(trios, scopes)  # a run of any tiers is a full one, so what an indexable site is made of is checked here
    book = content.load_rulebook(rules)
    manifest = content.load_manifest(sources_manifest)
    races = content.load_racials(racials)  # (the racial abilities of each race, read from the race pages of the wiki: shown, never scored)
    blocks = content.load_changelog(changelog)
    meta = trios[0].meta
    lastmod = _calendar_date(meta.data_date, "the data date")  # the date of every page in the sitemap
    for trio in trios:
        if (trio.meta.data_tag, trio.meta.data_date, trio.meta.game_patch, trio.meta.level) != (
            meta.data_tag,
            meta.data_date,
            meta.game_patch,
            meta.level,
        ):
            raise BuildError(f"{trio.meta.slug}: built from a different data release or level than {meta.slug}")
        if trio.meta.rules_version != book.version:
            raise BuildError(
                f"{trio.meta.slug}: the results were made with rules version {trio.meta.rules_version} "
                f"but {rules.name} is version {book.version}; run the precompute again"
            )
        check_defaults(trio)
    exalt = data.load_exalt(results, trios, items.document)  # (None for results made before the effects layer: no trio page then has the section; read after the defaults are checked, as it is held to them)
    shown = {item.key: item for trio in trios for item in data.used_items(trio)}
    missing = sorted(set(shown) - set(manifest.items) - set(manifest.eqlt))  # (an item read from EQ Legends Tools alone has no wiki revision, and its page credits that site)
    if missing:
        raise BuildError(f"{sources_manifest.name} has no wiki page for {len(missing)} item(s) shown, first {missing[0]}")
    table = items.document
    keys = item_page_keys(table)  # the items that get a page: the strict and wiki wearables of the item table, the release's own levels
    with_page = frozenset(keys)
    records = {_record_key(record): record for record in table["items"]}
    # a page credits the wiki page its item was read from, so an item that has one needs its entry in the manifest; an item that has none (an r key) has nothing to credit
    uncredited = sorted(key for key in keys if view.has_wiki_page(records[key]) and key not in manifest.items)
    if uncredited:
        raise BuildError(f"{sources_manifest.name} has no wiki page for {len(uncredited)} item(s) with a page of their own, first {uncredited[0]}: an item page credits its wiki page")
    headers_text = render_headers(headers.read_text(encoding="utf-8"), noindex=noindex)
    rules_obj = rules_module.load(rules)
    # the stats of an item at a tier, as the model sees it (the same ``at_tier`` the pages of the items use), for the rows of Wear this
    vecs = view.tier_vecs(records, table["defaults"], rules_obj)

    def stat_lines(key: str, tier: int) -> str:
        return view.item_stat_text(vecs(key, tier))

    # 2. the assets, then the pages
    assets, files = bundle_assets()
    env = make_env()
    page_meta = SimpleNamespace(data_date=meta.data_date, game_patch=meta.game_patch, level=meta.level, data_tag=meta.data_tag)
    issues_url = _issues_url(owner)
    credit = credit_of(meta)
    level_rule = view.rule_ref(book, "level.current")

    def render(
        template: str, path: str, *, title: str, description: str, subject: str, report: str = "page-problem.yml",
        report_view: Mapping[str, object] | None = None, canonical: bool = True, **extra,
    ) -> bytes:
        context = dict(
            page_title=title,
            page_description=description,
            canonical=site_url + path if canonical else None,
            noindex=noindex,
            favicon=FAVICON,
            assets=assets,
            nav=_nav(path),
            meta=page_meta,
            disclaimer=DISCLAIMER,
            attribution=ATTRIBUTION,
            attribution_parts=attribution_parts(),
            licence_sentence=LICENCE_SENTENCE,
            level_rule=level_rule,
            partial=bool(partial),
            reports_not_open=REPORTS_NOT_OPEN,
            report_url=_report_url(owner, site_url, path, subject, report, report_view),
        )
        context.update(extra)
        return env.get_template(template).render(**context).encode("utf-8")

    pages: dict[str, bytes] = {}
    trio_files: list[str] = []
    live = []
    wearers: dict[str, list[tuple[str, str]]] = {}  # item key -> (slug, name) of the trios whose default answer wears it
    for trio in trios:
        for key in view.default_kit_keys(trio):
            wearers.setdefault(key, []).append((trio.meta.slug, view.trio_name(trio.meta.trio)))
        caps = view.trio_caps(trio.meta.trio, trio.meta.level, rules_obj)
        try:
            page = view.trio_page(trio, book, caps, with_page, vecs, exalt, races)
        except ValueError as error:  # (an item the page can show has no page of its own: one line, naming the trio and the item)
            raise BuildError(str(error)) from None
        path = f"/trio/{trio.meta.slug}/"
        name = f"trio/{trio.meta.slug}/index.html"
        pages[name] = render(
            "trio.html.j2",
            path,
            title=page.title,
            description=page.description,
            subject=f"the {page.name} page",
            report="wrong-item.yml",
            report_view=page.default,
            page=page,
        )
        trio_files.append(name)
        live.append(SimpleNamespace(slug=trio.meta.slug, name=page.name, level=trio.meta.level))
        for shard in trio.shards.values():
            files[f"data/{trio.meta.slug}/{shard.evidence}-{shard.buffs}.json"] = data.site_shard_json(shard, credit, stat_lines).encode("utf-8")
        for role in trio.runnerups.roles():  # a file for each role, with every tier of the run in it
            name = f"data/{trio.meta.slug}/runnerups/{role}.json"
            files[name] = data.site_runnerups_json(trio.runnerups, role, credit).encode("utf-8")
        files[f"data/{trio.meta.slug}/robust.json"] = data.site_robust_json(trio.robust, credit).encode("utf-8")
        if exalt is not None and exalt.has(trio.meta.slug):
            files[f"data/{trio.meta.slug}/{data.EXALT_NAME}"] = data.site_exalt_json(exalt, trio.meta.slug, table, credit).encode("utf-8")
    if exalt is not None and exalt.trios:
        files[f"data/{data.EFFECTS_NAME}"] = data.site_effects_json(exalt, table, credit, with_page, rules_obj.get("effects.late_level")).encode("utf-8")

    pages["index.html"] = render(
        "home.html.j2",
        "/",
        title="TrioForge: best gear for every class trio",
        description="Exact best-in-slot gear for every class trio, with the evidence and confidence behind every rule. A fan project.",
        subject="the home page",
        **home_context(live),
    )
    pages["rules/index.html"] = render(
        "rules.html.j2",
        "/rules/",
        title="Rules and confidence seals · TrioForge",
        description="Every rule the planner uses, with its value, source, date and confidence seal.",
        subject="the rules page",
        report="rule-correction.yml",
        book=book,
        seal_legend=[(key, label, meaning) for key, (label, meaning) in content.SEALS.items()],
    )
    revisions = revision_rows([key for key in sorted(shown) if key in manifest.items], manifest, with_page)  # the items the trio pages show, each linked to its own page where it has one (an item page carries its own credit)
    eqlt_rows = eqlt_item_rows(sorted(key for key in manifest.eqlt if key in shown or key in with_page), manifest, with_page)
    pages["sources/index.html"] = render(
        "sources.html.j2",
        "/sources/",
        title="Sources and licences · TrioForge",
        description="Where the data comes from, its licences and the wiki revision of every item shown.",
        subject="the sources page",
        manifest=manifest,
        revisions=revisions,
        race_pages=race_page_rows(races),
        racials_date=races.date,
        racials_input=races.input,
        eqlt_rows=eqlt_rows,
        eqlt_name=content.EQLT_NAME,
        eqlt_site=content.EQLT_SITE,
    )
    item_files: list[str] = []
    try:
        made = [
            view.item_page(
                records[key],
                defaults=table["defaults"],
                rules=rules_obj,
                book=book,
                wiki=manifest.items[key] if view.has_wiki_page(records[key]) else None,
                wearers=wearers.get(key, ()),
                origin=manifest.eqlt[key][1] if key in manifest.eqlt else None,
            )
            for key in keys
        ]
    except ValueError as error:  # (a code of the evidence ladder that the site does not know: one line, naming the item)
        raise BuildError(str(error)) from None
    named = Counter(item.title for item in made)  # a title is a page's own: two items of one name are told apart by their keys
    for item in made:
        key = item.key
        if named[item.title] > 1:
            item = replace(item, title=f"{item.name} ({key}){view.TITLE_SUFFIX}")
        name = f"item/{key}/index.html"
        pages[name] = render(
            "item.html.j2",
            view.item_href(key),
            title=item.title,
            description=item.description,
            subject=f"the page of {item.name}",
            report="wrong-item.yml",
            page=item,
            licence_url=LICENCE_URL,
            licence_name=LICENCE_NAME,
        )
        item_files.append(name)
    pages["about/index.html"] = render(
        "about.html.j2",
        "/about/",
        title="About · TrioForge",
        description="What TrioForge is, the fan-project disclaimer, privacy and how to report a problem.",
        subject="the about page",
        issues_url=issues_url,
    )
    pages["changelog/index.html"] = render(
        "changelog.html.j2",
        "/changelog/",
        title="Changelog · TrioForge",
        description="What changed in each data and site release.",
        subject="the changelog",
        blocks=blocks,
    )
    # Pages answers an address it has no file for with this page and a 404, instead of the home page and a 200 (the answer it
    # gives a single-page app), so a data file that is missing is an error to the page code and not a web page that does not
    # parse. It is shown at whatever address was asked for, so it names no address of its own (no canonical link). Its script moves
    # an address of a trio in another order, case or form to the page of the trio, from the list of the build in the page.
    pages["404.html"] = render(
        "notfound.html.j2",
        "/404.html",
        title="Page not found · TrioForge",
        description="There is nothing at this address. Go to the home page to find a trio.",
        subject="the page-not-found page",
        canonical=False,
        **notfound_context(live),
    )

    # 3. everything else, then the budgets
    files.update(pages)
    engine_data = publish_engine_data(files, items, trios)
    engine_checked = check_engine_data(items, trios)  # the engine's own readers on what is about to be published
    files[MANIFEST_FILE] = render_manifest(assets.engine, engine_data)
    for slug in sorted(engine_data.bundles):
        files[trio_manifest_name(slug)] = render_trio_manifest(slug, engine_data)
    files["_headers"] = headers_text.encode("utf-8")
    files["robots.txt"] = (
        ("User-agent: *\nDisallow: /\n") if noindex else f"User-agent: *\nAllow: /\n\nSitemap: {site_url}/sitemap.xml\n"
    ).encode("utf-8")
    if not noindex:
        urls = ["/"] + [f"/trio/{t.meta.slug}/" for t in trios] + ["/rules/", "/sources/", "/about/", "/changelog/"]
        entries = "".join(
            f"<url><loc>{xml_escape(site_url + url)}</loc><lastmod>{lastmod}</lastmod></url>\n" for url in urls
        )
        files["sitemap.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + entries + "</urlset>\n"
        ).encode("utf-8")
    loaded = [assets.css.lstrip("/"), assets.boot.lstrip("/"), assets.app.lstrip("/")]
    first_load = {name: loaded for name in [*trio_files, *item_files, "index.html"]}
    first_load["404.html"] = [assets.css.lstrip("/"), assets.boot.lstrip("/"), assets.notfound.lstrip("/")]  # (its own script, in place of the page script)
    sizes = check_budgets(
        files, trio_pages=trio_files, first_load_assets=first_load, item_pages=item_files, entry_pages={"home": "index.html", "notfound": "404.html"}
    )
    sizes.update({f"checked_{name}": count for name, count in engine_checked.items()})

    # 4. write
    _write(out, files)
    return SiteBuild(tuple(sorted(pages)), len(files), sizes, out, partial)


def marker_path(out: Path) -> Path:
    """The marker file of a build folder: beside it, named after it (``site/dist`` has ``site/dist.trioforge-build``)."""
    folder = Path(os.path.abspath(out))
    if not folder.name:
        raise BuildError(f"{out} has no name to put a marker beside: give the output folder a name")
    return folder.with_name(folder.name + MARKER_SUFFIX)


def _is_link(path: str | os.PathLike[str]) -> bool:
    """Whether ``path`` is a symbolic link or, on Windows, a junction (a folder that stands for another one)."""
    return os.path.islink(path) or os.path.isjunction(path)


def _first_link(folder: Path) -> Path | None:
    """The first link under ``folder`` (in the order of the names, a folder after the files in it), found without following any."""
    with os.scandir(folder) as entries:
        for entry in sorted(entries, key=lambda e: e.name):
            if _is_link(entry.path):
                return Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                found = _first_link(Path(entry.path))
                if found is not None:
                    return found
    return None


def _write(out: Path, files: Mapping[str, bytes]) -> None:
    """Replace the output folder with the site, whole or not at all.

    The files are written into a folder beside ``out`` (``<name>.<token>.trioforge-tmp``) and that folder takes the place of the old
    output only when it is complete, so a build that stops part way (an error, or Ctrl-C) leaves the old output as it was (or none) and
    no folder that the next build would refuse as "not a TrioForge build output". The marker goes beside ``out`` before the swap, so that
    a folder in place always has one. A build that fails before the new folder has taken the place takes away a marker that it made
    itself (an empty folder of someone else's is replaced without a marker, and one left behind would vouch for whatever is put there
    next) and keeps one that was there before. A folder that holds something else is refused untouched, and so is a link: ``out``
    itself, the marker, or anything under ``out`` (a build does not follow a link and would not know what it was removing).

    ``out`` is made absolute first, without following a link: the folders and the marker beside it are named after it, and a relative
    path such as ``.`` has no name to give them. Where the platform cannot move the folder a program is working in (Windows), ``.`` is a
    BuildError like any folder that cannot be moved."""
    out = Path(os.path.abspath(out))
    marker = marker_path(out)
    if _is_link(marker):
        raise BuildError(f"{marker} is a link: the marker of a build folder is a file of its own")
    marker_was_there = os.path.lexists(marker)
    if _is_link(out):
        raise BuildError(f"{out} is a link, not a folder: give the build a folder of its own")
    if out.exists():
        if not out.is_dir():
            raise BuildError(f"{out} exists and is not a folder")
        if any(out.iterdir()) and not (marker.is_file() or (out / LEGACY_MARKER).is_file()):
            raise BuildError(f"{out} is not a TrioForge build output (there is no {marker.name} beside it); refusing to replace it")
        link = _first_link(out)
        if link is not None:
            raise BuildError(f"{out} holds a link ({link.relative_to(out).as_posix()}): remove it, or give the build a folder of its own")
    out.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(4)
    scratch = out.with_name(f"{out.name}.{token}{TEMP_SUFFIX}")
    aside = out.with_name(f"{out.name}.{token}.old{TEMP_SUFFIX}")
    scratch.mkdir()
    try:
        for name, content_bytes in sorted(files.items()):
            target = scratch / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content_bytes)
        marker.write_text("A TrioForge build output. Every build replaces the folder it is named after.\n", encoding="utf-8")
        _swap(scratch, out, aside)
    except BaseException:
        # told from the disk, not from a flag: the new folder is in place if it is no longer where it was written
        in_place = not os.path.lexists(scratch)
        shutil.rmtree(scratch, ignore_errors=True)
        if not in_place and not marker_was_there:
            with contextlib.suppress(OSError):
                marker.unlink()
        raise


def _swap(new: Path, out: Path, aside: Path) -> None:
    """Put the folder ``new`` in the place of ``out``: the old folder, if there is one, is moved to ``aside`` first and removed once ``new``
    has taken its place. If anything stops the swap before that, an error or an interruption (Ctrl-C), the old folder is put back and the
    stop is raised: an OSError as a BuildError, anything else as it was. Whether the old folder is out of its place is read from the disk
    (``aside`` is there and ``out`` is not), not from a note made after the move, which an interruption can come too soon for. A folder
    that a program holds open cannot be moved on Windows: that is a BuildError, and so is an old folder that cannot be put back (the
    error says where it is). An old folder that cannot be removed once ``new`` is in place does not fail the build (the new output is
    whole): one line on stderr names the folder that is left over and says it can be deleted."""

    def refused(error: OSError) -> BuildError:
        return BuildError(
            f"could not put the new build in the place of {out} ({error.strerror or error}): close whatever has the folder open and build again"
        )

    try:
        if out.exists():
            os.replace(out, aside)
        os.replace(new, out)
    except BaseException as error:
        if os.path.lexists(aside) and not os.path.lexists(out):
            try:
                os.replace(aside, out)
            except OSError:
                raise BuildError(f"could not put the new build in the place of {out}, and the old build could not be put back: it is in {aside}") from None
        if isinstance(error, OSError):
            raise refused(error) from None
        raise
    if os.path.lexists(aside):
        try:
            shutil.rmtree(aside)
        except OSError as error:
            # the new build is in place and whole, so this is not a failed build: the old one is only left over, and the line says where
            reason = " ".join(str(error.strerror or error).split())
            print(
                f"trioforge.site.build: warning: the old build could not be removed ({reason}); the folder {aside} is left over and can be deleted",
                file=sys.stderr,
            )


# ---- command line -----------------------------------------------------------------------------------------------------------------


def _kb(size: int) -> str:
    return f"{size / 1024:.1f} KB"


def main(argv: Sequence[str] | None = None, *, scopes: Mapping[str, Sequence[int]] | None = None) -> int:
    """The command ``python -m trioforge.site.build``. ``scopes`` is for a caller that builds a sample (a test): the command line itself has no option
    that names a scope, so a build from it is held to the scope of a full run of each trio."""
    parser = argparse.ArgumentParser(prog="python -m trioforge.site.build", description="Build the static site.")
    parser.add_argument("--results", type=Path, default=Path("build/results"), help="the precompute's results folder")
    parser.add_argument("--out", type=Path, default=Path("site/dist"), help="the folder to write (replaced on every build)")
    parser.add_argument(
        "--noindex", action="store_true",
        help="make a preview: tell search engines not to index this build. Only a preview can be made from partial results or from tiers other than "
        "those of a full run of each trio (+0, +4 and +10; every tier for pal-mnk-ber)",
    )
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL, help="the address the site is served at (canonical links)")
    parser.add_argument(
        "--owner",
        help="the GitHub account that owns the repository, for the report links (an indexable build needs it; a preview links to no repository without it)",
    )
    parser.add_argument("--rules", type=Path, help="the rules file (default rules/rules.json)")
    parser.add_argument("--sources-manifest", type=Path, help="the catalog's sources-manifest.json (default derived/)")
    parser.add_argument("--racials", type=Path, help="the racial abilities of the races, derived/racials.json (default derived/)")
    parser.add_argument("--changelog", type=Path, help="the changelog (default docs/CHANGELOG.md)")
    parser.add_argument("--headers", type=Path, help="the headers file (default site/_headers)")
    options = parser.parse_args(argv)
    try:
        result = build(
            results=options.results,
            out=options.out,
            noindex=options.noindex,
            site_url=options.site_url,
            rules=options.rules,
            sources_manifest=options.sources_manifest,
            racials=options.racials,
            changelog=options.changelog,
            headers=options.headers,
            owner=options.owner,
            scopes=scopes,
        )
    except (BuildError, data.ResultsError, content.ContentError, rules_module.RulesError, OSError) as error:
        line = "; ".join(part.strip() for part in str(error).splitlines() if part.strip())
        print(f"trioforge.site.build: {line}", file=sys.stderr)
        return 2
    sizes = result.sizes
    print(f"built {len(result.pages)} pages, {result.files} files into {result.out}{' (noindex)' if options.noindex else ''}")
    for slug in result.partial:
        print(f"warning: {slug} was built from a partial precompute run (a narrowed grid): its page has only the races and roles that were run")
    print(f"trio page HTML: {_kb(sizes['trio_html'])} raw (limit {LIMITS['trio_html'] // 1024} KB)")
    print(
        f"item pages: {sizes['item_pages']}, the largest {_kb(sizes['largest_item'])} raw (limit {LIMITS['item_html'] // 1024} KB), "
        f"{_kb(sizes['largest_item_gzip'])} gzip (limit {LIMITS['item_html_gzip'] // 1024} KB)"
    )
    print(
        f"first-load JS: {_kb(sizes['first_load_js_gzip'])} gzip (limit {LIMITS['first_load_js_gzip'] // 1024} KB), "
        f"{_kb(sizes['first_load_js'])} raw (limit {LIMITS['first_load_js'] // 1024} KB); "
        f"CSS {_kb(sizes['first_load_css_gzip'])} gzip; HTML {_kb(sizes['first_load_html_gzip'])} gzip"
    )
    print(f"first load of a trio page: {_kb(sizes['first_load_gzip'])} gzip (limit {LIMITS['first_load_gzip'] // 1024} KB)")
    for label, what in ENTRY_PAGE_NAMES.items():
        print(
            f"{what}: {_kb(sizes[f'{label}_html'])} raw (limit {LIMITS[f'{label}_html'] // 1024} KB), {_kb(sizes[f'{label}_html_gzip'])} gzip (limit {LIMITS[f'{label}_html_gzip'] // 1024} KB); "
            f"first load {_kb(sizes[f'{label}_first_load_gzip'])} gzip (limit {LIMITS['first_load_gzip'] // 1024} KB)"
        )
    print(
        f"code loaded on first use ({sizes['lazy_chunks']} chunks): {_kb(sizes['lazy_js'])} raw in all (limit {LIMITS['lazy_total_js'] // 1024} KB); "
        f"the largest chunk {_kb(sizes['lazy_chunk_js'])} raw (limit {LIMITS['lazy_chunk_js'] // 1024} KB), "
        f"{_kb(sizes['lazy_chunk_js_gzip'])} gzip (limit {LIMITS['lazy_chunk_js_gzip'] // 1024} KB)"
    )
    print(f"all the script but the optimizer's: {_kb(sizes['total_js'])} raw (no budget of its own)")
    print(
        f"largest shard: {_kb(sizes['largest_shard'])} raw (limit {LIMITS['shard'] // 1024} KB), "
        f"{_kb(sizes['largest_shard_gzip'])} gzip (limit {LIMITS['shard_gzip'] // 1024} KB)"
    )
    print(
        f"largest runner-up file (one for each role, every tier in it): {_kb(sizes['largest_runnerup'])} raw (limit {LIMITS['shard'] // 1024} KB), "
        f"{_kb(sizes['largest_runnerup_gzip'])} gzip (limit {LIMITS['shard_gzip'] // 1024} KB)"
    )
    if sizes["exalt_files"]:
        print(
            f"effects to exalt (fetched once the page has shown): the shared file {_kb(sizes['effects'])} raw (limit {LIMITS['effects'] // 1024} KB), {_kb(sizes['effects_gzip'])} gzip "
            f"(limit {LIMITS['effects_gzip'] // 1024} KB); {sizes['exalt_files']} trio files, the largest {_kb(sizes['largest_exalt'])} raw, {_kb(sizes['largest_exalt_gzip'])} gzip (limit {LIMITS['exalt_gzip'] // 1024} KB)"
        )
    print(f"first view with its data (first load + the largest shard): {_kb(sizes['first_view_gzip'])} gzip")
    print(f"files: {sizes['files']:,} (limit {LIMITS['files']:,}; Cloudflare Pages takes 20,000)")
    print(
        f"optimizer (loaded on request): worker {_kb(sizes['engine_worker_gzip'])} gzip, client {_kb(sizes['engine_client_gzip'])} gzip, "
        f"WebAssembly {sizes['engine_wasm'] / 1_000_000:.1f} MB "
        f"(limits: {LIMITS['engine_js_gzip'] // 1024} KB gzip for both scripts, {LIMITS['engine_wasm'] // 1024 // 1024} MiB)"
    )
    print(
        f"evaluator of a shared kit (loaded for a kit link): {_kb(sizes['engine_kitvalue'])} raw (limit {LIMITS['engine_kitvalue'] // 1024} KB), "
        f"{_kb(sizes['engine_kitvalue_gzip'])} gzip (limit {LIMITS['engine_kitvalue_gzip'] // 1024} KB)"
    )
    print(
        f"optimizer data (loaded on request): item table {_kb(sizes['engine_items'])} raw, {_kb(sizes['engine_items_gzip'])} gzip "
        f"(limits {LIMITS['engine_items'] // 1024 // 1024} MB, {LIMITS['engine_items_gzip'] // 1024} KB gzip); "
        f"largest bundle {_kb(sizes['engine_bundle'])} raw (limit {LIMITS['engine_bundle'] // 1024} KB)"
    )
    print(
        f"engine data checked with the engine's own readers: {sizes['checked_records']} item records at {sizes['checked_tiers']} tiers, "
        f"{sizes['checked_bundles']} bundle{'' if sizes['checked_bundles'] == 1 else 's'} with {sizes['checked_profiles']} profiles"
    )
    print(
        f"manifests (loaded on request): {MANIFEST_FILE} {_kb(sizes['manifest'])} (limit {LIMITS['manifest'] // 1024} KB), "
        f"largest trio manifest {sizes['trio_manifest']} bytes (limit {LIMITS['trio_manifest'] // 1024} KB)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
