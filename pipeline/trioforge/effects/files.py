"""The files of the effects layer: the shared ``effects.json``, the per-trio ``exalt.json``, their budgets, and the writer the release build calls.

``<results>/effects.json`` (beside ``items.json``; one for the whole release)::

    {"version": 1, "data_release", "rules_version", "license", "attribution", "spells_us": SHA-256 of the client spell text, "cap": 50, "mass": {class: how much it fights by casting, 0 to 1},
     "effects": [{"id": "e131", "n": name, "k": kind, "c": category, "m": magnitude, "u": unit, "q": cast level, "r": proc rate percent,
                  "x": [why it is unverified], "d": [[donor item key, access cost], ...], "f": {focus}}]}

``k`` is ``focus``, ``click`` (must be equipped), ``carry`` (an "Any Slot" click: carry the item), ``worn`` or ``proc``. ``d`` lists the items that carry the effect
and can be worn (an effect that no wearable item carries has no row), the easiest to get first; an item's classes and slots are those of the item table. A focus ``f`` is ``{"fam": family, "tier", "kind", "type": the stacking
type, "lo", "hi": percent, "max": highest spell level, "pen": percent lost for each level above it, "lim": the limits in words, "cov": {class: percent of the class's
late spells it touches}}``. An unverified effect says why in ``x``: ``ambiguous`` (several spells have the name), ``equip`` (the wiki does not say whether the click
must be equipped), ``inferred`` (a proc inferred from a weapon with no trigger wording) or ``description`` (players describe it differently from the spell data).

``<trio>/exalt.json``, written for each trio of the release, holds the offered roles only and item keys only::

    {"version": 1, "trio", "classes", "data_release", "rules_version", "race": the default race, "tier": the tier of the kit,
     "roles": {role: {"focus": [row], "click": [row], "carry": [row], "worn": [row], "proc": [row],
                      "plan": [{"k", "e", "d", "p", "h", "c", "u"}], "noroom": [{"k", "e", "w"}]}}}

A row is ``{"e": effect id, "d": the best donor's item key, "o": other donors' keys, "s": score, "m": the class that gains most}`` and, for a focus, ``"t"`` (its stacking
type), ``"l"`` (the families that lost the type) and ``"g"`` (what each trio class adds to the score, so that a plan can weigh a host that only some of them can use). The plan is made against the default kit of the role (default race, ``tier``): see :mod:`trioforge.effects.plan`. ``w`` is the reason an effect has no host: ``tier``, ``donor``, ``primary``, ``slot``, ``class`` or ``taken`` (:data:`trioforge.effects.plan.REASONS`).
A trio file is held to 20 KB gzip (:data:`TRIO_GZIP_LIMIT`), the shared file to 200 KB raw and 50 KB gzip.

The release build writes both after the precompute (:func:`write_release`) and checks them (:func:`check_release`). Nothing here depends on the seen flags: the pool is
the public catalog and the kits are the shipped results.
"""

from __future__ import annotations

import gzip
import json
import os
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trioforge.data.jsonio import JsonFileError, load_strict, render
from trioforge.effects import donors as dn
from trioforge.effects import layer, plan, spells
from trioforge.effects.judgment import Judgment
from trioforge.model.roles import roles_for
from trioforge.sources.client_tables import commit_files

__all__ = [
    "EFFECTS_FILE",
    "SHARED_GZIP_LIMIT",
    "SHARED_RAW_LIMIT",
    "TRIO_FILE",
    "TRIO_GZIP_LIMIT",
    "Built",
    "EffectsError",
    "build",
    "check_release",
    "default_kits",
    "remove_release",
    "shared_document",
    "trio_document",
    "write_release",
]

VERSION = 1
EFFECTS_FILE = "effects.json"
TRIO_FILE = "exalt.json"
TRIO_GZIP_LIMIT = 20 * 1024
SHARED_RAW_LIMIT = 200 * 1024
SHARED_GZIP_LIMIT = 50 * 1024
LISTS = ("focus", "click", "carry", "worn", "proc")


class EffectsError(ValueError):
    """A file of the effects layer is wrong or over its budget; the message names it."""


@dataclass
class Built:
    """The inputs of the layer, read once: the judgment, the effect records, the context and the items of the catalog by key."""

    j: Judgment
    effects: list[dict[str, Any]]
    misses: list[dict[str, str]]
    ctx: layer.Context
    items: dict[str, dict[str, Any]]
    data_release: str
    rules_version: str
    license: str
    attribution: str
    spell_sha256: str | None


def build(catalog: dict[str, Any], book: spells.SpellBook, j: Judgment, rules_version: str) -> Built:
    """Read the effects of the wiki-level items of a catalog document into records and make the context."""
    pool = [item for item in catalog["items"] if item["evidence"]["level"] == "wiki"]
    effects, misses = dn.build_effects(pool, book, j)
    ctx = layer.build_context(effects, book, j)
    items = {item["key"]: {"classes": item["classes"], "slots": item["slots"] or [], "name": item["name"]} for item in catalog["items"]}
    return Built(j, effects, misses, ctx, items, f"data-{catalog['version']}", rules_version, catalog["license"], catalog["attribution"], book.source_sha256)


# ---- the shared file -----------------------------------------------------------------------------------------------


def _kind(effect: dict[str, Any]) -> str:
    kind = dn.kind_of(effect)
    return "carry" if kind == "click" and effect.get("mode") == "carry" else kind


def _focus(effect: dict[str, Any], ctx: layer.Context) -> dict[str, Any]:
    focus = effect["focus"]
    lim = focus["limits"]
    shares = ctx.cov.get(effect["id"], {})
    return {
        "fam": focus["family"], "tier": focus["tier"], "kind": focus["kind"], "type": spells.focus_type(focus),
        "lo": focus["min_pct"], "hi": focus["max_pct"], "max": lim["max_level"], "pen": lim["level_penalty"] or 0,
        "lim": spells.limit_text(focus), "cov": {c: round(100 * v["share"]) for c, v in shares.items() if v["share"] > 0},
    }  # fmt: skip


def shared_document(built: Built) -> dict[str, Any]:
    """The shared ``effects.json`` document."""
    rows = []
    for effect in built.effects:
        if effect.get("category") == "unresolved" or (effect["kind"] == "focus" and "focus" not in effect):
            continue  # (a label of focus on a spell that is no focus effect: the analysis keeps the record, the lists never offer it, and a row would have no "f")
        donors = sorted((d for d in effect["items"] if d["eligible"]), key=lambda d: (d["access"], -len(d["slots"]), d["key"]))
        if not donors:
            continue  # (a mount in the ammo slot, a potion, a poison, a scroll: no item of the item table carries it, no list of a trio offers it, and a row would have no donor)
        row: dict[str, Any] = {
            "id": effect["id"], "n": effect["name"], "k": _kind(effect), "c": effect["category"], "m": effect.get("magnitude"), "u": effect.get("unit"),
            "q": effect["cast_level"], "r": effect["rate_pct"], "x": effect["unverified"], "d": [[d["key"], d["access"]] for d in donors],
        }  # fmt: skip
        if "focus" in effect:
            row["f"] = _focus(effect, built.ctx)
        rows.append(row)
    return {
        "version": VERSION, "data_release": built.data_release, "rules_version": built.rules_version, "license": built.license,
        "attribution": built.attribution, "spells_us": built.spell_sha256, "cap": built.j.cap, "mass": {c: round(m, 4) for c, m in built.ctx.mass.items()}, "effects": rows,
    }  # fmt: skip


# ---- the kits ---------------------------------------------------------------------------------------------------------------


def default_kits(trio_dir: str | os.PathLike[str]) -> tuple[str, int, dict[str, list[tuple[str, str]]]] | None:
    """The default kit of each role of a trio's results: ``(race, tier, {role: [(place, item key), ...]})``, or ``None`` when the results have no default race.

    The kit is the solved one of the default view (the evidence level and buffs of ``defaults.json``, its tier) for the default race, in the best setup (the greatest value)
    of each role the shard holds, but for the opening build, whose setup is the one ``defaults.json`` names (the file's value is the exact one; the rows keep two decimals, and two
    setups that tie to the cent may be told apart by the exact values). Empty places are left out."""
    folder = Path(trio_dir)
    defaults = load_strict(folder / "defaults.json")
    race, view = defaults.get("race"), defaults["view"]
    if race is None:
        return None
    shard = load_strict(folder / f"{view['evidence']}-{view['buffs']}.json")
    keys = [row[shard["items_keys"].index("key")] for row in shard["items"]]
    found: dict[str, list[list[Any]]] = {}
    for row in shard["scenarios"]:
        if row[0] == race and row[2] == view["tier"]:
            found.setdefault(row[1], []).append(row)
    best: dict[str, list[Any]] = {}
    for role, rows in found.items():
        named = [row for row in rows if row[3] == defaults.get("setup")] if role == view["role"] else []  # (a setup the shard has no row for: the best row stands)
        best[role] = max(named or rows, key=lambda row: row[5])  # (the first of equal rows)
    kits: dict[str, list[tuple[str, str]]] = {}
    for role, row in best.items():
        kits[role] = [(place, keys[index]) for place, index in zip(shard["places"], shard["kits"][row[4]], strict=True) if index >= 0]
    return race, view["tier"], kits


# ---- the trio file ---------------------------------------------------------------------------------------------------------


def _row(option: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {"e": option["effect"], "d": option["donor"], "o": option["others"], "s": option["score"], "m": option["member"]}
    if "type" in option:
        row["t"] = option["type"]
        row["l"] = option["losers"]
        row["g"] = option["gains"]
    return row


def trio_document(built: Built, slug: str, race: str, tier: int, kits: dict[str, list[tuple[str, str]]]) -> dict[str, Any]:
    """The ``exalt.json`` document of a trio from its default kits (``kits``: role to ``(place, item key)``)."""
    classes = [part.upper() for part in slug.split("-")]
    roles: dict[str, Any] = {}
    for role in roles_for(classes, bow=None):  # (the lists of every role the trio can have: the pool of the results decides which of them the page offers)
        if role not in kits:
            continue
        options = layer.layer(classes, role, built.ctx)
        placed = plan.plan_kit(options, kits[role], built.items, built.ctx, classes, role, tier)
        entry: dict[str, Any] = {name: [_row(o) for o in options[name]] for name in LISTS}
        entry["plan"], entry["noroom"] = placed["rows"], placed["noroom"]
        roles[role] = entry
    return {
        "version": VERSION, "trio": slug, "classes": classes, "data_release": built.data_release, "rules_version": built.rules_version,
        "race": race, "tier": tier, "roles": roles,
    }  # fmt: skip


# ---- the release -----------------------------------------------------------------------------------------------------------


def gzip_size(data: bytes) -> int:
    return len(gzip.compress(data, 9, mtime=0))


def write_release(
    results: str | os.PathLike[str], trios: Sequence[str], built: Built, say: Callable[[str], None] = print
) -> dict[str, tuple[int, int]]:
    """Write ``effects.json`` into the results folder and ``exalt.json`` into the folder of each of ``trios`` that has results and a default race.

    A trio folder without a ``defaults.json`` or without a default race gets no file, and an ``exalt.json`` an earlier run left in it is removed. Returns ``{name: (bytes, gzip bytes)}``."""
    root = Path(results)
    sizes: dict[str, tuple[int, int]] = {}
    texts: dict[str, str] = {}
    for slug in trios:
        folder = root / slug
        found = default_kits(folder) if (folder / "defaults.json").is_file() else None
        if found is None:
            (folder / TRIO_FILE).unlink(missing_ok=True)  # (nothing was made for this trio this time: nothing of an earlier time may stay)
            continue
        race, tier, kits = found
        texts[slug] = render(trio_document(built, slug, race, tier, kits))
    for slug, text in texts.items():
        commit_files(root / slug, {TRIO_FILE: text}, last=TRIO_FILE)
        sizes[f"{slug}/{TRIO_FILE}"] = (len(text.encode("utf-8")), gzip_size(text.encode("utf-8")))
    shared = render(shared_document(built), per_line=("effects",))
    commit_files(root, {EFFECTS_FILE: shared}, last=EFFECTS_FILE)
    sizes[EFFECTS_FILE] = (len(shared.encode("utf-8")), gzip_size(shared.encode("utf-8")))
    return sizes


def remove_release(results: str | os.PathLike[str], trios: Sequence[str]) -> list[str]:
    """Take away the effects files of an earlier run: ``effects.json`` and the ``exalt.json`` of each of ``trios``. A build that does not make the files this time calls this, so
    that what an earlier build left in the results is not staged as if it were this one's. Returns the names removed."""
    root = Path(results)
    removed = []
    for name in (EFFECTS_FILE, *(f"{slug}/{TRIO_FILE}" for slug in trios)):
        path = root / name
        if path.is_file():
            path.unlink()
            removed.append(name)
    return removed


def _need(ok: bool, name: str, what: str) -> None:
    if not ok:
        raise EffectsError(f"{name}: {what}")


def _is_list_of(value: Any, kind: type) -> bool:
    return isinstance(value, list) and all(isinstance(item, kind) for item in value)


def check_release(folder: str | os.PathLike[str], trios: Sequence[str], items: Collection[str] | None = None) -> int:
    """Hold the effects files of a staged release to their form and budgets; returns the number of trio files checked.

    Nothing is required: a release made before the layer has none, and is not refused. When ``effects.json`` is there, every trio file must carry the version, the slug,
    the effect ids that exist in it, donors that it lists and (given ``items``, the keys of the item table) hosts and donors (the best and the other ones) that the table has, and each file is within its budget. A file
    that is JSON but not of the form (a scalar, a missing key, a wrong type) is refused like any other fault. Given ``items``, a donor of the shared file that the table lacks is refused too (the site's reader refuses it).
    ``EffectsError`` names the first fault and the file."""
    root = Path(folder)
    shared_path = root / EFFECTS_FILE
    present = [slug for slug in trios if (root / slug / TRIO_FILE).is_file()]
    if not shared_path.is_file():
        if present:
            raise EffectsError(f"{present[0]}/{TRIO_FILE} is there but {EFFECTS_FILE} is not")
        return 0
    raw = shared_path.read_bytes()
    if len(raw) > SHARED_RAW_LIMIT or gzip_size(raw) > SHARED_GZIP_LIMIT:
        raise EffectsError(f"{EFFECTS_FILE} is {len(raw):,} bytes raw and {gzip_size(raw):,} gzip, over its {SHARED_RAW_LIMIT:,} and {SHARED_GZIP_LIMIT:,}")
    try:
        shared = load_strict(shared_path)
    except JsonFileError as error:
        raise EffectsError(str(error)) from None
    ids, known = _read_shared(shared)
    wanted = set(items) if items is not None else None
    if wanted is not None:
        for row in shared["effects"]:
            for key, _ in row["d"]:
                _need(key in wanted, EFFECTS_FILE, f"effect {row['id']} lists the donor {key}, which is not in the item table")
    for slug in present:
        name = f"{slug}/{TRIO_FILE}"
        data = (root / slug / TRIO_FILE).read_bytes()
        if gzip_size(data) > TRIO_GZIP_LIMIT:
            raise EffectsError(f"{name} is {gzip_size(data):,} bytes gzip, over the {TRIO_GZIP_LIMIT:,}-byte budget")
        try:
            doc = json.loads(data)
        except ValueError:
            raise EffectsError(f"{name} is not JSON") from None
        try:
            _check_trio(doc, slug, name, shared, ids, known, wanted)
        except EffectsError:
            raise
        except (KeyError, TypeError, AttributeError, ValueError, IndexError) as error:
            raise EffectsError(f"{name}: not of the form of a trio file ({type(error).__name__})") from None
    return len(present)


def _read_shared(shared: Any) -> tuple[set[str], set[str]]:
    """The effect ids and donor keys of a shared file, after checking its form."""
    name = EFFECTS_FILE
    _need(isinstance(shared, dict), name, "is not an object")
    _need(shared.get("version") == VERSION, name, f"version must be {VERSION}")
    rows = shared.get("effects")
    _need(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), name, "effects must be a list of objects")
    try:
        ids = {row["id"] for row in rows}
        known = {key for row in rows for key, _ in row["d"]}
    except (KeyError, TypeError, ValueError):
        raise EffectsError(f"{name}: an effect lacks an id or a donor list of pairs") from None
    for row in rows:
        _need(row.get("k") != "focus" or isinstance(row.get("f"), dict), name, f"effect {row.get('id')} is a focus effect with no f")
    _need(all(isinstance(i, str) for i in ids) and all(isinstance(k, str) for k in known), name, "ids and donor keys must be text")
    return ids, known


def _check_trio(doc: Any, slug: str, name: str, shared: dict[str, Any], ids: set[str], known: set[str], wanted: set[str] | None) -> None:
    _need(isinstance(doc, dict), name, "is not an object")
    _need(doc.get("version") == VERSION and doc.get("trio") == slug, name, "wrong version or trio")
    _need(doc.get("data_release") == shared.get("data_release"), name, f"made for another data release than {EFFECTS_FILE}")
    _need(_is_list_of(doc.get("classes"), str) and isinstance(doc.get("roles"), dict), name, "classes must be a list of codes and roles an object")
    offered = roles_for(doc["classes"], bow=None)
    for role, entry in doc["roles"].items():
        _need(role in offered, name, f"role {role} is not offered to the trio")
        _need(isinstance(entry, dict) and all(isinstance(entry.get(part), list) for part in (*LISTS, "plan", "noroom")), name, f"role {role} lacks a list")
        rows = [row for part in (*LISTS, "plan", "noroom") for row in entry[part]]
        _need(all(isinstance(row, dict) for row in rows), name, "a row is not an object")
        for part in LISTS:
            _need(all(isinstance(r.get("o"), list) for r in entry[part]), name, "a row lacks its list of other donors")
        for row in rows:
            effect = row["e"]
            _need(isinstance(effect, str) and effect in ids, name, f"effect {effect} is not in {EFFECTS_FILE}")
        donors = [r["d"] for part in LISTS for r in entry[part]] + [k for part in LISTS for r in entry[part] for k in r["o"]] + [r["d"] for r in entry["plan"]]
        for key in donors:
            _need(isinstance(key, str) and key in known, name, f"donor {key} is not an item of {EFFECTS_FILE}")
            _need(wanted is None or key in wanted, name, f"donor {key} is not in the item table")
        for key in [r["h"] for r in entry["plan"]]:
            _need(isinstance(key, str) and (wanted is None or key in wanted), name, f"host {key} is not in the item table")
