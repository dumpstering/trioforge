"""Put the items of EQ Legends Tools into the catalog: override the wiki's copy, add what the wiki lacks.

The maintainers decided on 2026-10-25 that https://eqlegendstools.com/zones/nektropos-castle/ is the source of truth
for every item it lists. :func:`merge_eqlegendstools` takes the items the wiki pages gave (``wiki_items``, from
:func:`trioforge.data.catalog.parse_pages`) and the pages of that site (:class:`trioforge.sources.eqlegendstools.EqltItem`)
and returns the items of the catalog and a report.

* **An item the wiki also has** (the one wiki item with the same name, compared by :func:`trioforge.data.evidence.title_key`:
  case, accents, apostrophes and spacing do not count) keeps its key and its ``wiki`` field, and **the tooltip of this site wins**:
  slots, classes, stats, resists, flags, effects, weapon fields, level fields, weight, size and where it drops. What the
  tooltip does not carry stays the wiki's: the quests, vendors, recipes and foraging places, the categories, the era tags, the
  picture id, and the flags of the wiki *page* (its banners). A field the tooltip leaves out stays unknown on the site's side and
  keeps the wiki's value (a weight, a size, a level, a type, a race list, a deity list), and the report says so: nothing is made up.
  The parse warnings are those of the tooltip, the wiki text being no longer the text read. The flags are the tooltip's only when the
  page has a flags line the parser reads (at least one flag, or "none"); with none, or one it cannot read, the wiki's flags stay (Lore is never dropped for want of a line) and ``flags`` is listed as unknown.
  The weapon is merged field by field like the scalars (a value the tooltip shows wins; a field it omits keeps the wiki's value and is
  listed as ``weapon.<field>``). A tooltip that shows no weapon field but states a type that is no weapon (``Type: Shield``) drops the wiki's weapon.
* **An item the wiki lacks** is added with the key ``rlt-<slug>``, **no wiki page** (``wiki`` is null) and the tooltip's data. Its
  tooltip must state a ``Class:`` line and a ``Slot:`` line, or the item is left out and listed in the report under ``skipped`` (the
  parser's default of all classes would be made up, and a missing slot cannot be solved); the catalog build warns about each.
* **A name on more than one wiki page** is a build error naming the item (``ValueError``): a person must say which page it is.
* Every item that comes from this site has ``origin`` = ``{"source": "eqlegendstools", "slug": ..., "overrides_wiki": bool}``;
  the page of the item is ``https://eqlegendstools.com/items/<slug>/``.

The report (``eqlegendstools`` in the catalog summary) says what was done: how many pages were read, which items were
overridden and which added or skipped, every field where the two disagree (``{"key", "name", "field", "wiki", "eqlt"}``), the
fields the site left unknown for an item the wiki has, and the pages that gave a parse warning.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Sequence
from typing import Any

from trioforge.data.evidence import title_key
from trioforge.data.normalize import FLAGS, _tier_rule, normalize, validate_item
from trioforge.sources.eqlegendstools import SOURCE_ID, EqltItem, to_parsed_page

__all__ = ["KEY_PREFIX", "OVERRIDDEN", "build_item", "eqlt_key", "merge_eqlegendstools", "stated_fields"]

KEY_PREFIX = "rlt-"
# the page flags that belong to the wiki page, not to the tooltip: an override keeps them
_PAGE_FLAGS = frozenset({"removed_note", "wiki_banner_delete", "wiki_banner_does_not_exist", "wiki_banner_dne", "wiki_banner_revamped"})
#: the fields of an item that the tooltip of this site settles (the order the report lists them in)
OVERRIDDEN = (
    "slots",
    "classes",
    "races",
    "deity",
    "flags",
    "stats",
    "sv",
    "weight",
    "size",
    "item_type",
    "weapon",
    "container_capacity",
    "instrument_mods",
    "effects",
    "required_level",
    "recommended_level",
    "charges",
    "drops",
)
_SCALARS = ("weight", "size", "required_level", "recommended_level", "container_capacity", "charges")
_LINE_KEYS = {
    "slot": re.compile(r"(?:^|\s)slot\s*:", re.IGNORECASE),
    "class": re.compile(r"(?:^|\s)class\s*:", re.IGNORECASE),
    "race": re.compile(r"(?:^|\s)race\s*:", re.IGNORECASE),
    "deity": re.compile(r"(?:^|\s)(?:deity|diety|deities|dieties)\s*:", re.IGNORECASE),
    "type": re.compile(r"(?:^|\s)type\s*:", re.IGNORECASE),
}


# a Type: line whose value names a weapon (a skill, "Weapon"); any other stated type says the item is no weapon
_WEAPON_TYPE = re.compile(r"weapon|slash|pierc|blunt|archery|\bbow\b|throw|hand[\s-]*to[\s-]*hand|\bh2h\b|\b[12][\s-]*h|two[\s-]*hand|\bbows?\b", re.IGNORECASE)
# a flags line that says the item has none
_NO_FLAGS = re.compile(r"(?:none|no flags)\.?", re.IGNORECASE)

_QUOTES = dict.fromkeys(map(ord, "'`‘’´"))


def _same_name(text: str) -> str:
    """A name for comparison: :func:`title_key`, and no apostrophe or backtick (the site writes ``Gamblers Gambit`` where the wiki writes ``Gambler's Gambit``)."""
    return " ".join(title_key(text).translate(_QUOTES).split())


def eqlt_key(slug: str) -> str:
    """The catalog key of an item the wiki lacks: ``rlt-`` and the slug of its page."""
    return KEY_PREFIX + slug


def stated_fields(item: EqltItem) -> frozenset[str]:
    """Which of ``slot``, ``class``, ``race``, ``deity`` and ``type`` the tooltip's lines state: a field a tooltip does not show is unknown there, whatever default the statsblock parser gives it."""
    return frozenset(name for name, pattern in _LINE_KEYS.items() if any(pattern.search(line) for line in item.lines))


def build_item(item: EqltItem) -> dict[str, Any]:
    """The catalog item (before the evidence ladder) for one page of the site: the statsblock parser's item with the key ``rlt-<slug>``, no wiki page and the origin.

    ``origin.overrides_wiki`` is false here; :func:`merge_eqlegendstools` sets it for an item that replaces a wiki copy.
    """
    built = normalize(to_parsed_page(item))
    built["key"] = eqlt_key(item.slug)
    built["wiki"] = None
    built["origin"] = {"source": SOURCE_ID, "slug": item.slug, "overrides_wiki": False}
    built["sources"]["drops"] = _drops(built)
    built["tier_rule"] = _tier_rule(built["name"], set(built["flags"]), built["sources"])
    return built


def _drops(built: dict[str, Any]) -> list[dict]:
    return copy.deepcopy(built["sources"]["drops"])


def _override(
    wiki_item: dict[str, Any], built: dict[str, Any], stated: frozenset[str], slug: str, flags_stated: bool = True
) -> tuple[dict[str, Any], list[str]]:
    """The wiki item with the tooltip's fields in place of its own (see the module docstring), and the fields the tooltip left unknown."""
    merged = copy.deepcopy(wiki_item)
    unknown: list[str] = []
    for field in ("stats", "sv", "effects", "instrument_mods"):  # (a tooltip lists every stat, resist and effect the item has)
        merged[field] = copy.deepcopy(built[field])
    for field, key in (("slots", "slot"), ("classes", "class"), ("races", "race"), ("deity", "deity")):
        if key in stated:
            merged[field] = copy.deepcopy(built[field])
        else:
            unknown.append(field)  # the tooltip does not show it: the wiki's value stays
    for field in _SCALARS:
        if built.get(field) is not None:
            merged[field] = built[field]
        elif wiki_item.get(field) is not None:
            unknown.append(field)
    if "type" in stated:
        merged["item_type"], merged["item_type_source"] = built["item_type"], built["item_type_source"]
    elif wiki_item.get("item_type") is not None:
        unknown.append("item_type")
    not_a_weapon = "type" in stated and built["item_type"] is not None and _WEAPON_TYPE.search(built["item_type"]) is None
    merged["weapon"], weapon_unknown = _merge_weapon(wiki_item.get("weapon"), built["weapon"], not_a_weapon)
    unknown.extend(weapon_unknown)
    if flags_stated:
        flags = set(built["flags"]) | {flag for flag in wiki_item.get("flags", ()) if flag in _PAGE_FLAGS}
    else:  # the page has no flags line: that says nothing about the item's flags (Lore, No Trade), so the wiki's stay
        flags = set(built["flags"]) | set(wiki_item.get("flags", ()))
        unknown.append("flags")
    merged["flags"] = [flag for flag in FLAGS if flag in flags]
    merged["sources"]["drops"] = _drops(built)
    merged["parse_warnings"] = copy.deepcopy(built["parse_warnings"])
    merged["parse_warnings_overflow"] = built["parse_warnings_overflow"]
    merged["tier_rule"] = _tier_rule(merged["name"], set(merged["flags"]), merged["sources"])
    merged["origin"] = {"source": SOURCE_ID, "slug": slug, "overrides_wiki": True}
    return merged, unknown


def _flags_stated(page: EqltItem, built: dict[str, Any]) -> bool:
    """True if the page's flags line says something about the item's flags: at least one flag was read from it, or it says there are none. A line the parser cannot
    read (an unknown spelling) says nothing, as no line at all says nothing: the wiki's flags stay and ``flags`` is listed as unknown."""
    return page.flags_text is not None and (bool(built["flags"]) or _NO_FLAGS.fullmatch(page.flags_text.strip()) is not None)


def _merge_weapon(
    wiki_weapon: dict[str, Any] | None, tooltip_weapon: dict[str, Any] | None, not_a_weapon: bool = False
) -> tuple[dict[str, Any] | None, list[str]]:
    """The weapon fields field by field, as the scalars are: a value the tooltip shows wins; a field it does not show keeps the wiki's value and is listed as unknown
    (``weapon.<field>``, or ``weapon`` when the tooltip shows no weapon field at all). A tooltip that shows no weapon field but states a type that is no weapon
    (``Type: Shield``) says the item is not one: the wiki's weapon (a page that wrongly typed it) goes, and nothing about the weapon is unknown."""
    if tooltip_weapon is None and not_a_weapon:
        return None, []
    if tooltip_weapon is None:
        return copy.deepcopy(wiki_weapon), (["weapon"] if wiki_weapon is not None else [])
    if wiki_weapon is None:
        return copy.deepcopy(tooltip_weapon), []
    merged: dict[str, Any] = {}
    unknown: list[str] = []
    for name in dict.fromkeys([*tooltip_weapon, *wiki_weapon]):
        if tooltip_weapon.get(name) is not None:
            merged[name] = copy.deepcopy(tooltip_weapon[name])
        elif wiki_weapon.get(name) is not None:
            merged[name] = copy.deepcopy(wiki_weapon[name])
            unknown.append(f"weapon.{name}")
        elif name in tooltip_weapon or name in wiki_weapon:
            merged[name] = None
    return merged, unknown


def _value(item: dict[str, Any], field: str) -> Any:
    return item["sources"]["drops"] if field == "drops" else item.get(field)


def _disagreements(wiki_item: dict[str, Any], merged: dict[str, Any]) -> list[dict[str, Any]]:
    """Every field where the wiki's copy and the merged item (the site's copy) differ, one entry for each stat or resist of the two dicts."""
    found: list[dict[str, Any]] = []

    def add(field: str, before: Any, after: Any) -> None:
        found.append({"key": merged["key"], "name": merged["name"], "field": field, "wiki": before, "eqlt": after})

    for field in OVERRIDDEN:
        before, after = _value(wiki_item, field), _value(merged, field)
        if field in ("stats", "sv"):
            for name in sorted(set(before) | set(after)):
                if before.get(name) != after.get(name):
                    add(f"{field}.{name}", before.get(name), after.get(name))
        elif field == "weapon":
            left, right = before or {}, after or {}
            if before is None or after is None:
                if before != after:
                    add("weapon", before, after)
            else:
                for name in sorted(set(left) | set(right)):
                    if left.get(name) != right.get(name):
                        add(f"weapon.{name}", left.get(name), right.get(name))
        elif field == "effects":
            names = lambda value: sorted((e["kind"], e["name"]) for e in value)  # noqa: E731 - (the raw text differs in form, not in meaning)
            if names(before) != names(after):
                add("effects", [f"{kind}:{name}" for kind, name in names(before)], [f"{kind}:{name}" for kind, name in names(after)])
        elif field == "drops":
            simple = lambda value: sorted((d.get("zone"), tuple(d.get("npcs", ()))) for d in value)  # noqa: E731
            if simple(before) != simple(after):
                add("drops", [[d.get("zone"), list(d.get("npcs", ()))] for d in before], [[d.get("zone"), list(d.get("npcs", ()))] for d in after])
        elif before != after:
            add(field, before, after)
    return found


def merge_eqlegendstools(
    wiki_items: Sequence[dict[str, Any]], pages: Iterable[EqltItem]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The items of the catalog after the site's pages are put in, and the report. ``wiki_items`` is not changed.

    Every item that results is checked against the item schema. Two pages with one slug are one page. Raises ``ValueError`` if a page
    names a wiki item that another page already replaced (two pages for one item are a conflict a person must settle).
    """
    items = [copy.deepcopy(item) for item in wiki_items]
    by_name: dict[str, list[int]] = {}
    for index, item in enumerate(items):
        by_name.setdefault(_same_name(item["name"]), []).append(index)
        title = (item.get("wiki") or {}).get("title")
        if title and _same_name(title) != _same_name(item["name"]):
            by_name.setdefault(_same_name(title), []).append(index)
    taken_keys = {item["key"] for item in items}
    replaced: dict[int, str] = {}
    added: list[dict[str, Any]] = []
    overridden: list[dict[str, str]] = []
    new: list[dict[str, str]] = []
    disagreements: list[dict[str, Any]] = []
    left_unknown: list[dict[str, Any]] = []
    warned: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for page in pages:
        if page.slug in seen_slugs:
            continue
        seen_slugs.add(page.slug)
        built = build_item(page)
        validate_item(built)
        matches = sorted(set(by_name.get(_same_name(page.name), [])))
        if len(matches) > 1:  # a guess would be wrong, and a copy added beside both would put the item in the catalog three times
            raise ValueError(
                f"the page {page.slug} ({page.name}) names {len(matches)} wiki items with that name ({', '.join(items[i]['key'] for i in matches)}): "
                "a person must settle which one it is"
            )
        stated = stated_fields(page)
        if built["parse_warnings"]:  # (before the skip: the warning of a line the parser could not read is often why the page is skipped)
            warned.append({"slug": page.slug, "warnings": [f"{w['code']}:{w['field']}" for w in built["parse_warnings"]]})
        missing = [] if matches else [name for name in ("slot", "class") if name not in stated]
        if missing:  # a new item has no wiki copy to fall back on: the parser's default (all classes, no slot) would be made up
            skipped.append({"slug": page.slug, "name": built["name"], "missing": missing})
            continue
        if len(matches) == 1:
            index = matches[0]
            if index in replaced:
                raise ValueError(f"the pages {replaced[index]} and {page.slug} are both the wiki item {items[index]['key']}")
            replaced[index] = page.slug
            merged, unknown = _override(items[index], built, stated, page.slug, _flags_stated(page, built))
            validate_item(merged)
            disagreements.extend(_disagreements(items[index], merged))
            if unknown:
                left_unknown.append({"key": merged["key"], "name": merged["name"], "fields": unknown})
            overridden.append({"key": merged["key"], "name": merged["name"], "slug": page.slug})
            items[index] = merged
            continue
        if built["key"] in taken_keys:
            raise ValueError(f"the key {built['key']} is taken")
        taken_keys.add(built["key"])
        added.append(built)
        new.append({"key": built["key"], "name": built["name"], "slug": page.slug, "slots": list(built["slots"])})
    result = items + added
    report = {
        "pages": len(seen_slugs),
        "overridden": overridden,
        "added": new,
        "skipped": skipped,
        "disagreements": disagreements,
        "left_unknown": left_unknown,
        "parse_warnings": warned,
    }
    return result, report
