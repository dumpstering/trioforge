"""What changed between two releases, and why: the report the maintainer reads before a release is tagged.

::

    report = results_diff.diff(old_release, new_release)     # a folder or a tar.gz each; None for the old one of a first release
    report.summary, report.changes                           # counts, and every change
    report.markdown(), report.json_text()                    # reports/results-diff-<tag>.md and .json

A release is the folder :mod:`trioforge.precompute.assemble` describes. The report reads ``release.json`` of each (the code hash, the solver options, the
rules, the game patch), the item table, and for each trio its four shards, its defaults and its runner-up files. Only public data goes in: no fingerprint of
the inputs, no snapshot id, nothing of the maintainer's logs, and no word about how an item came to be strict.

**What is compared.** *Every* changed

* **scenario** (``kind: scenario``): a value ``F``, the ``gain`` (the value of the naked character, F less the gain, when it moved by more than the rounding
  of the two numbers), a kit, the optional buffs, the assumed haste or the totals of one race, role, tier, weapon setup, evidence level and buff set; a scenario
  that one release has and the other lacks is ``added`` or ``removed``;
* **default pick** (``default``): the whole selection of a trio's default: its race, runner-up, setup, value, margin and kit, the view it is made at (role, tier,
  evidence level, buff set) and its flip notes; a default that one release lacks is ``added`` or ``removed``;
* **runner-up** (``runner-up``): the swaps of any place, the setup they are for or the evidence level of the view, of every view that either release has (one
  that only a release has is ``added`` or ``removed``);
* **seal** (``seal``): the robustness seals (``robust.json``) of one role and tier, place by place, and the race they are for;
* **bundle** (``bundle``): the browser bundle of a trio (``engine-l<level>.json``), named with the SHA-256 of its file in each release and never its content
  (``inputs_only`` says that the two differ in their ``inputs`` field alone);
* **item record** (``item``): the catalog record of an item (``items.json``) and the arrival and source text of the shards' item rows (every row that any
  shard of any trio shows for it; a release holds one, which :func:`trioforge.precompute.release.check_item_rows` makes sure of).

A trio or a tier that only one release has is **one** record (``trio``, ``tier``) with the number of scenarios it brings: its rows are counted, not listed.

**Causes.** Each change lists every cause that applies, in the order of precedence ``code``, ``rule``, ``data``, ``community``:

* ``code``: the hash of the model, solver and precompute code, the solver options or the builder options differ, so nothing is the same input;
* ``rule``: ``rules.json`` changed (its value or its levels; its status is not a change) in a rule that the pick uses (:data:`RULE_SCOPES`: an Iksar rule is
  in the picks of an Iksar, a Monk rule in the picks of a trio with a Monk, the dual-wield factor in the dual-wield setup, the tier rules above +0; a rule
  that is neither scoped nor in :data:`UNREAD` is in every pick; a rule the solver never reads is in none, so that a change to it explains nothing);
* ``data``: the game patch of the client data differs, or the catalog changed for an item that is in the old kit or in the new one. A change of a field the
  solver reads (slots, classes, races, deity, Lore, stats, resists, weight, weapon, type, tier rule, the not-for-bis mark, or an item that one release lacks)
  explains every pick that wears the item. A move of its **evidence level** explains a pick only where it changes the item's membership of the pool the pick was
  made from: the strict pool holds the items of level strict, the wiki pool those of level strict or wiki, so an item that moves from wiki to strict changes
  the strict picks and none of the wiki picks, and one that moves from strict to wiki changes the strict picks only;
* ``community``: such an item changed its evidence level because a community entry was added (it became strict) or retracted (it stopped being so), and the
  move changes its membership of the pool of the pick (the same rule). **A report that stood outweighed and counts now** is a community cause too: an item that players
  reported and the wiki marks as gone, or whose zones are closed, stays hidden with the reason ``community-report-outweighed``; when the wiki takes the mark off, or the zone
  is opened, the item is strict by the report that was in the file already. The cause is the data (the wiki's edit let the report through) **and** the community (nothing else
  makes the item strict), so one report cannot reach the kits through a later edit of the wiki without the report saying so. An item that moves from strict to hidden because
  a mark of the wiki came while the report stands is the data's alone (it is listed all the same among the items that stopped being strict, as outweighed);
* ``new``: a trio or a tier the old release did not have.

A bundle's ``inputs`` field is one hash over the whole rules file and the catalog's levels, so a bundle that differs in that field alone is explained by any input
change (a rule or a new version of the rules, the catalog, an item record, the patch); a bundle that differs anywhere else is explained only by the code, the rules
and the patch (the source text of an item is no input of it).

**The community entries** are not inferred from the reason codes of the item table, which a retraction can leave as they were (a duplicate retracted while another report of
the item stands, a second report of an item already reported, an entry on an item that a patch or research removed). ``release.json`` records them
(:mod:`trioforge.precompute.assemble`: ``community``, the entries as the committed list holds them), and the report compares them by item and issue: the ones **added**, the ones
**retracted**, the ones **taken out of the file with no retraction**, and the ones **changed** in place (the fields that differ). A release made before the field existed lists
none: the report says so once ("the previous release does not list its community entries"), and takes no entry for added or retracted. The entries of the release that follows it
are listed as **recorded in this release for the first time** (``first``: the reports and the retractions, each entry, and the Markdown counts them): they were recorded before,
and nothing says when. What the entries did to the evidence is a
separate list: the items that are strict now because of a report (``strict_gained``) and the ones that stopped being so (``strict_lost``), each with ``why``: the report was
``retracted``, or it is ``outweighed`` and ``by`` which codes (the marks of the wiki, the reasons that say every zone is closed, a removal by a patch or by research; the report
stands in the file). Both lists are read from the reason codes of the public catalog and not from the levels of the item table, which have the maintainer's private flags merged.

**A change nothing explains is a solver diff**: the same inputs gave another answer. It is a bug unless the value ties (the same ``F``, or the same swaps
in another order): ``flag`` is ``tie`` for that, and ``solver-diff`` for the bug. The Markdown puts the solver diffs before everything else.

The Markdown shows the counts and the 20 largest changes of ``F``. The JSON lists every change; nothing is cut, and what the Markdown leaves out it says.

**What is public.** The Markdown is committed, so it names no item whose evidence changed: counts by kind and by cause, the rules and inputs that changed, the
solver diffs, the largest changes of ``F`` with their causes and no item, and the community entries (public, in ``rules/community-seen.json``, with their issues). The JSON lists
the items of every change and the evidence level of every item record that moved, which tells the maintainer's private list of seen items; it is for the
maintainer and stays in ``build/``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import weakref
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trioforge.community import REPORT_FIELDS, RETRACTED_FIELDS
from trioforge.data.evidence import REMOVAL_CODES, WIKI_MARK_CODES, ZONE_CLOSED_CODES
from trioforge.data.jsonio import JsonFileError, load_strict, render
from trioforge.precompute import assemble, shards

__all__ = ["CAUSES", "FORMAT", "RULE_SCOPES", "SHARD_NAMES", "TOP", "UNREAD", "Release", "Report", "Scope", "diff", "load_release", "rule_in_pick"]

FORMAT = 1
#: the causes of a change in the order of precedence (``new`` stands alone: a new trio or tier has no other)
CAUSES = ("code", "rule", "data", "community")
TOP = 20  # the changes of F the Markdown shows
SHARD_NAMES = ("strict-own", "strict-group", "wiki-own", "wiki-group")
KIND_ORDER = {"trio": 0, "tier": 1, "scenario": 2, "default": 3, "runner-up": 4, "seal": 5, "bundle": 6, "item": 7}
LIST_LIMIT = 20  # the keys and the solver diffs the Markdown lists before it says how many more there are
GAIN_SLACK = 0.0201  # F and the gain are kept to two decimals, each rounded on its own: the value of the naked character, F less the gain, is good to two units of that
#: the fields of an item record that the solver reads (its pool and its stats), and the ones that are only shown
SOLVER_FIELDS = ("slots", "classes", "races", "deity", "lore", "stats", "sv", "weight10", "weapon", "item_type", "tier_rule", "owned_only")
SHOWN_FIELDS = ("id", "name", "match_name", "aliases", "source", "item_type_source")
COMMUNITY = "community-report"  # the reason code of a strict item that rests on a report from players
OUTWEIGHED = "community-report-outweighed"  # ... and of an item that players reported but the wiki marks as gone or whose zones are closed: it stays hidden, and the report is only noted
COMMUNITY_CODES = (COMMUNITY, OUTWEIGHED)  # a community entry is in the record of an item by either
OUTWEIGHING = WIKI_MARK_CODES | ZONE_CLOSED_CODES  # what the ladder records beside the report it outweighed (a removal by a patch or research records no report: REMOVAL_CODES)
NOT_FOR_BIS = "not-for-bis"
#: the rules that decide the arrival tier of an item (shards.arrival_tier)
ARRIVAL_RULES = frozenset({"tier.max_fresh_drop", "tier.arrival"})


# ---- the scope of a rule ------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """What a rule or an item can be in: the classes of the trio, and (``None`` when a record does not say) the race, tier, weapon setup and evidence level of the
    pick (the evidence level is the pool the pick was made from: the strict pool holds the items of level strict, the wiki pool those of level strict or wiki)."""

    classes: frozenset[str]
    race: str | None = None
    tier: int | None = None
    setup: str | None = None
    evidence: str | None = None


def _tiered(scope: Scope) -> bool:
    return scope.tier is None or scope.tier > 0


#: where a rule is used, by rule id; a rule listed neither here nor in :data:`UNREAD` is in every pick. (The model reads these rules for the profile of a race and
#: trio and for the items at a tier: ``model/profile.py`` and ``model/items.py``.)
RULE_SCOPES: dict[str, Callable[[Scope], bool]] = {
    "race.iksar_ac_bonus": lambda s: s.race in (None, "IKS"),
    "race.iksar_ac_placement": lambda s: s.race in (None, "IKS"),
    "monk.weight_curve": lambda s: "MNK" in s.classes,
    "monk.bonus_placement": lambda s: "MNK" in s.classes,
    "haste.cap_pct_with_monk": lambda s: "MNK" in s.classes,
    "haste.cap_pct": lambda s: "MNK" not in s.classes,
    "haste.unbound_alacrity": lambda s: "MNK" in s.classes,
    "weapons.dual_wield_factor": lambda s: s.setup in (None, "dw"),
    "tier.weapon_damage_pct": _tiered,
    "tier.stat_rule": _tiered,
    "tier.weight_floor": _tiered,
    "tier.weight_pct": _tiered,
    "tier.negatives_scale": _tiered,
}

#: the rules the solver never reads: it uses a constant that mirrors the rule (``model/formulas.py``, ``model/tiers.py``; the tests compare the two), or only the
#: export, the site and the item rows of the shards read the rule. A change to one of them is in no pick, so it explains no change of a pick and hides no solver diff.
#: (A test keeps this list true: it follows the string constants of the files whose code hash is in the fingerprint of the chunks, and watches a real solve.)
UNREAD = frozenset(
    {
        "naked.cap", "naked.rule", "hp.pools_counted", "hp.sta_curve", "mana.pools_counted", "mana.base_l50", "mana.per_stat_l50", "end.formula",
        "ac.sheet.item_mult", "ac.sheet.defense_div", "ac.sheet.spell_ac_div", "ac.sheet.agi_div", "ac.softcap.past_cap_rate", "stats.knee", "stats.hard_cap",
        "stats.str_to_atk", "stats.agi_to_ac", "stats.dex_post255_slope", "packrat.pct_per_rank", "tier.accuracy_pct",
        "tier.socket_open", "tier.arrival", "tier.max_fresh_drop", "tier.exp_needed", "tier.void_mote", "roles.balanced",
        # the effects layer reads these after the solve (the exalt plan and its lists); the solver never does
        "effects.focus_value", "effects.spell_weight", "effects.cast_categories", "effects.cast_mass_full", "effects.late_level", "effects.click_relevance",
        "effects.dispel_relevance", "effects.gap_categories", "effects.own_compare", "effects.instant_categories", "effects.instant_bonus", "effects.proc_value",
        "effects.score_shape", "effects.haste_buff", "effects.near_best", "effects.access_cost", "effects.raid_zones", "effects.one_off_spas",
        "effects.restricted_targets", "effects.unverified_names", "effects.rows_kept",
    }
)  # fmt: skip


def rule_in_pick(rule: str, scope: Scope) -> bool:
    """Whether a rule can be in a pick of this scope: not if the solver never reads it, and where it is scoped only inside its scope."""
    if rule in UNREAD:
        return False
    applies = RULE_SCOPES.get(rule)
    return True if applies is None else applies(scope)


# ---- reading a release ----------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """A scenario of a shard: the value, its gain over the naked character, the 22 places of the kit as item keys, the optional buffs, the assumed haste and the totals."""

    F: float
    gain: float
    kit: tuple[str | None, ...]
    buffs: tuple[int, ...]
    haste: int
    totals: tuple[int, ...]


@dataclass(frozen=True)
class RunnerUp:
    """The runner-ups of one race at one tier: the weapon setup they are for, and for each place the swaps as ``(item key, delta)``."""

    evidence: str
    setup: str
    places: tuple[tuple[tuple[str, float], ...], ...]


@dataclass
class TrioData:
    """The files of one trio of a release, decoded."""

    slug: str
    place_names: tuple[str, ...]
    rows: dict[tuple[str, str, str, str, int, str], Row]  # (evidence, buffs, race, role, tier, setup)
    defaults: dict[str, Any]
    runnerups: dict[tuple[str, int, str], RunnerUp]  # (role, tier, race)
    item_rows: dict[str, set[tuple[Any, Any]]]  # item key -> the (arrival, source text) rows that any of the shards shows for it (one, in a release that is whole)
    seals: dict[str, Any]  # robust.json: the race and, for each role and tier (as text), the label of each place
    bundles: dict[str, str]  # file name -> SHA-256, for each engine-l<level>.json
    bundle_paths: dict[str, Path]  # file name -> where the bundle is, to read the two that differ and see where


def _plain(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Release:
    """A release read from a folder, or from its ``tar.gz`` (unpacked into a temporary folder that goes with the object)."""

    def __init__(self, source: str | os.PathLike[str]) -> None:
        path = Path(source)
        self._temporary: Path | None = None
        if path.is_file():
            self._temporary = Path(tempfile.mkdtemp(prefix="results-diff-"))
            weakref.finalize(self, shutil.rmtree, self._temporary, True)
            assemble.extract(path, self._temporary / "release")
            path = self._temporary / "release"
        elif not path.is_dir():
            raise assemble.ReleaseRefused(f"{path.name}: there is no release here")
        self.folder = path
        self.meta = assemble.read_release_json(path)
        self._items: dict[str, dict[str, Any]] | None = None

    def close(self) -> None:
        if self._temporary is not None:
            shutil.rmtree(self._temporary, ignore_errors=True)
            self._temporary = None

    @property
    def tag(self) -> str:
        return self.meta["release"]

    def tiers(self, slug: str) -> tuple[int, ...]:
        return tuple(self.meta["trios"].get(slug, ()))

    @property
    def community(self) -> dict[str, dict[tuple[str, int], dict[str, Any]]] | None:
        """The community entries that ``release.json`` records, ``reports`` and ``retracted`` by ``(key, issue)``; None for a release made before they were recorded."""
        recorded = self.meta.get("community")
        if recorded is None:
            return None
        return {name: {(entry["key"], entry["issue"]): entry for entry in recorded[name]} for name in ("reports", "retracted")}

    def items(self) -> dict[str, dict[str, Any]]:
        """The records of the item table by key, each with the table's defaults filled in and the evidence read as ``{"level", "codes"}``."""
        if self._items is None:
            try:
                table = load_strict(self.folder / assemble.ITEMS_FILE)
            except (OSError, JsonFileError) as error:
                raise assemble.ReleaseRefused(f"{assemble.ITEMS_FILE} of {self.tag} cannot be read: {error}") from None
            defaults = table.get("defaults", {})
            found: dict[str, dict[str, Any]] = {}
            for record in table.get("items", ()):
                key = record.get("key") or f"w{record['id']}"
                merged = {**defaults, **record}
                evidence = merged.get("evidence") or {}
                merged["evidence"] = {"level": evidence.get("level"), "codes": tuple(sorted(evidence.get("codes", ())))}
                found[key] = merged
            self._items = found
        return self._items

    def trio(self, slug: str) -> TrioData:
        folder = self.folder / slug
        rows: dict[tuple[str, str, str, str, int, str], Row] = {}
        item_rows: dict[str, set[tuple[Any, Any]]] = {}
        places: tuple[str, ...] = ()
        for name in SHARD_NAMES:
            path = folder / f"{name}.json"
            if not path.is_file():
                continue
            doc = _plain(path)
            evidence, buffs = name.split("-")
            places = tuple(doc["places"])
            items, totals, buff_sets = doc["items"], doc["totals"], doc["buff_sets"]
            kits = [tuple(None if index < 0 else items[index][0] for index in kit) for kit in doc["kits"]]
            for race, role, tier, setup, kit, value, gain, total, buff, haste in doc["scenarios"]:
                rows[(evidence, buffs, race, role, tier, setup)] = Row(value, gain, kits[kit], tuple(buff_sets[buff]), haste, tuple(totals[total]))
            for item in items:
                item_rows.setdefault(item[0], set()).add((item[4], item[5]))  # (every shard's row: a row that differs in a later shard is not lost to the first)
        runnerups: dict[tuple[str, int, str], RunnerUp] = {}
        folder_of_swaps = folder / "runnerups"
        for path in sorted(folder_of_swaps.glob("*.json")) if folder_of_swaps.is_dir() else ():
            if path.name == "index.json":
                continue
            doc = _plain(path)
            items = doc["items"]
            for tier, race, setup, swaps in doc["views"]:
                runnerups[(doc["role"], tier, race)] = RunnerUp(
                    doc["evidence"], setup, tuple(tuple((items[index][0], delta) for index, delta in place) for place in swaps)
                )
        defaults_path = folder / "defaults.json"
        seals_path = folder / "robust.json"
        bundle_paths = {path.name: path for path in sorted(folder.glob(f"{shards.ENGINE_PREFIX}*.json"))}
        bundles = {name: _sha256(path) for name, path in bundle_paths.items()}
        return TrioData(
            slug, places, rows, _plain(defaults_path) if defaults_path.is_file() else {}, runnerups, item_rows,
            _plain(seals_path) if seals_path.is_file() else {}, bundles, bundle_paths,
        )

    def scenario_count(self, slug: str, tier: int | None = None) -> int:
        """The scenarios of a trio (at one tier, or all) in its four shards."""
        total = 0
        for name in SHARD_NAMES:
            path = self.folder / slug / f"{name}.json"
            if path.is_file():
                total += sum(1 for row in _plain(path)["scenarios"] if tier is None or row[2] == tier)
        return total


def load_release(source: str | os.PathLike[str] | Release) -> Release:
    """A :class:`Release` from a folder or a ``tar.gz``; a :class:`Release` is returned as it is."""
    return source if isinstance(source, Release) else Release(source)


# ---- the inputs that changed -----------------------------------------------------------------------------------------------------------


@dataclass
class Inputs:
    """What differs between the two releases as a whole, before any change is looked at."""

    code: bool
    rules: dict[str, tuple[Any, Any]]
    patch: tuple[str, str] | None
    catalog_date: tuple[str, str] | None
    rules_version: tuple[str, str] | None
    catalog_changed: bool = False  # the SHA-256 of the public catalog differs (not in the summary: the date says it)

    def summary(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "rules": sorted(self.rules),
            "game_patch": list(self.patch) if self.patch else None,
            "catalog_date": list(self.catalog_date) if self.catalog_date else None,
            "rules_version": list(self.rules_version) if self.rules_version else None,
        }

    def rule_in(self, scopes: Iterable[Scope]) -> bool:
        """Whether a changed rule is in a pick of one of these scopes."""
        scopes = list(scopes)
        return any(rule_in_pick(rule, scope) for rule in self.rules for scope in scopes)


def _rule_content(entry: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """What of a rule counts as a change: its value and its levels (its status is a note about the rule, and no pick reads it)."""
    return None if entry is None else {name: entry[name] for name in ("value", "levels") if name in entry}


def _inputs(old: Release, new: Release) -> Inputs:
    before = {rule: _rule_content(entry) for rule, entry in old.meta["rules"].items()}
    after = {rule: _rule_content(entry) for rule, entry in new.meta["rules"].items()}
    changed = {rule: (before.get(rule), after.get(rule)) for rule in sorted(set(before) | set(after)) if before.get(rule) != after.get(rule)}
    code = (old.meta["code_hash"], old.meta["solver"], old.meta["build_options"]) != (new.meta["code_hash"], new.meta["solver"], new.meta["build_options"])

    def pair(name: str) -> tuple[str, str] | None:
        return (old.meta[name], new.meta[name]) if old.meta[name] != new.meta[name] else None

    return Inputs(
        code, changed, pair("game_patch"), pair("catalog_date"), pair("rules_version"), old.meta["catalog_sha256"] != new.meta["catalog_sha256"]
    )


# ---- the item records --------------------------------------------------------------------------------------------------------------------


@dataclass
class ItemChange:
    """How the record of one item differs between the releases, and what that explains.

    ``fields`` are the fields that differ (``record`` for an item that only one release has), ``community`` is ``added`` or ``removed`` when the
    ``community-report`` reason (or ``community-report-outweighed``, which an item the wiki marks as gone or whose zones are closed has instead) came or went, or is ``lifted``
    when a report that stood outweighed counts now (the item is strict by it and was not), ``solver_fields`` says that a field the solver reads differs (it explains every pick
    that wears the item), ``levels`` are the evidence level before and after (it explains a pick only where it changes the item's membership of the pool the pick was made
    from), ``moves_level`` that the community entry is why the evidence level moved, ``data_moves_level`` that a change of the data let it (the mark or the zone that
    outweighed the report went: the data is a cause of the picks too) and ``causes`` why the record itself changed (in the order of precedence).

    ``gained`` and ``lost`` are what the committed report says of the item, so they are read from the reason codes of the public catalog and never from the levels, which
    have the maintainer's private flags merged: ``gained`` is that a report made the item strict (``community-report`` is among its codes now and was not), ``lost`` that the
    report that made it strict no longer does (it was among the codes and is not now). Were they read from the levels, an item the maintainer has
    seen, whose level does not move, would be missing from a Markdown that is public, and the gap would tell which items they have seen. ``lost_why`` says why it no longer
    does: ``outweighed`` (``lost_by`` are the codes that outweigh it) or ``retracted`` (see :func:`_why_not_strict`)."""

    key: str
    change: str  # "changed", "added" or "removed"
    fields: list[str]
    levels: tuple[str | None, str | None]
    community: str | None
    solver_fields: bool
    moves_level: bool
    causes: list[str]
    data_moves_level: bool = False
    gained: bool = False
    lost: bool = False
    lost_why: str | None = None
    lost_by: tuple[str, ...] = ()


def _in_pool(level: str | None, pool: str) -> bool:
    """Whether an item of this evidence level is in the solve pool of an evidence level: the strict pool holds the items of level strict, the wiki pool those of
    level strict or wiki (the level of an item that is not in the catalog is None)."""
    return level == "strict" if pool == "strict" else level in ("strict", "wiki")


def _changes_pool(levels: tuple[str | None, str | None], evidences: Iterable[str | None]) -> bool:
    """Whether a move of the evidence level changes the item's membership of the pool of any of these evidence levels (None: a record that does not say which pool
    it was made from, so either)."""
    before, after = levels
    if before == after:
        return False
    return any(_in_pool(before, pool) != _in_pool(after, pool) for evidence in evidences for pool in (("strict", "wiki") if evidence is None else (evidence,)))


def _codes(record: Mapping[str, Any]) -> tuple[str, ...]:
    return record["evidence"]["codes"]


def _why_not_strict(codes: set[str], stands: bool | None) -> tuple[str, tuple[str, ...]]:
    """Why an item that a report made strict is not any more, from the codes it has now: ``outweighed`` and by which codes, or ``retracted``. The ladder records
    ``community-report-outweighed`` beside the mark of the wiki or the closed zone that outweighs a report it received, and the codes beside it are the marks and the closed zones
    only; a removal by a patch or by research hides the item before reports are looked at, and records none, so it outweighs the report only if the report stands in the file
    (``stands``: whether the file of the new release has a report of the item; None when the release does not list its entries, and the removal is taken to outweigh it).
    Anything else is the report gone: retracted."""
    if OUTWEIGHED in codes:
        return "outweighed", tuple(sorted(codes & OUTWEIGHING))
    removal = codes & REMOVAL_CODES
    if removal and stands is not False:
        return "outweighed", tuple(sorted(removal))
    return "retracted", ()


def _item_changes(
    old: Release, new: Release, old_rows: Mapping[str, set[tuple[Any, Any]]], new_rows: Mapping[str, set[tuple[Any, Any]]], inputs: Inputs
) -> dict[str, ItemChange]:
    before, after = old.items(), new.items()
    arrival_rule = bool(ARRIVAL_RULES & set(inputs.rules))
    entries = new.community
    reported = None if entries is None else {key for key, _ in entries["reports"]}  # (the items that have a report in the file of the new release)
    found: dict[str, ItemChange] = {}
    for key in sorted(set(before) | set(after)):
        a, b = before.get(key), after.get(key)
        if a is None or b is None:
            levels = ((a or {}).get("evidence", {}).get("level"), (b or {}).get("evidence", {}).get("level"))
            # a record that is new, and carries a community code, is a community change as well: the report was recorded already (a new entry is listed as one), the page is new
            community = "added" if a is None and any(code in COMMUNITY_CODES for code in _codes(b)) else None
            gained = a is None and COMMUNITY in _codes(b)
            moves = gained and levels[1] == "strict"
            found[key] = ItemChange(
                key, "added" if a is None else "removed", ["record"], levels, community, False, moves, ["data", "community"] if community else ["data"],
                data_moves_level=moves, gained=gained,
            )  # fmt: skip
            continue
        fields = [name for name in (*SOLVER_FIELDS, *SHOWN_FIELDS) if a.get(name) != b.get(name)]
        old_level, new_level = a["evidence"]["level"], b["evidence"]["level"]
        had, has = any(code in COMMUNITY_CODES for code in _codes(a)), any(code in COMMUNITY_CODES for code in _codes(b))
        community = "added" if has and not had else "removed" if had and not has else None
        # a report that stood outweighed (by a mark of the wiki, by a zone that was closed) counts now: the item is strict by it and was not
        lifted = community is None and COMMUNITY in _codes(b) and new_level == "strict" and old_level != "strict"
        if lifted:
            community = "lifted"
        moves = (community in ("added", "lifted") and new_level == "strict" and old_level != "strict") or (
            community == "removed" and old_level == "strict" and new_level != "strict"
        )
        if a["evidence"] != b["evidence"]:
            fields.append("evidence")
        if not fields:
            continue
        other_codes = {c for c in _codes(a) if c not in COMMUNITY_CODES} != {c for c in _codes(b) if c not in COMMUNITY_CODES}
        level_unexplained = old_level != new_level and not moves
        solver_fields = any(name in SOLVER_FIELDS for name in fields) or ((NOT_FOR_BIS in _codes(a)) != (NOT_FOR_BIS in _codes(b)))
        data = any(name not in ("evidence", "arrival") for name in fields) or level_unexplained or other_codes
        causes = [name for name, applies in (("data", data), ("community", community is not None)) if applies]
        lost = COMMUNITY in _codes(a) and COMMUNITY not in _codes(b)  # (the report made the item strict, and does not any more: retracted, or outweighed)
        lost_why, lost_by = _why_not_strict(set(_codes(b)), None if reported is None else key in reported) if lost else (None, ())
        found[key] = ItemChange(
            key, "changed", sorted(fields), (old_level, new_level), community, solver_fields, moves, causes, data_moves_level=lifted,
            gained=COMMUNITY in _codes(b) and COMMUNITY not in _codes(a), lost=lost, lost_why=lost_why, lost_by=lost_by,
        )  # fmt: skip
    for key in sorted(set(old_rows) & set(new_rows)):
        shown = [
            name
            for name, column in (("arrival", 0), ("source", 1))
            if {row[column] for row in old_rows[key]} != {row[column] for row in new_rows[key]}  # (every row any shard shows, not the first one)
        ]
        if not shown:
            continue
        moved = "arrival" in shown and arrival_rule  # the arrival tier follows the tier rules
        existing = found.get(key)
        if existing is None:
            a, b = before.get(key), after.get(key)
            levels = (a["evidence"]["level"] if a else None, b["evidence"]["level"] if b else None)
            existing = found[key] = ItemChange(key, "changed", [], levels, None, False, False, [])
        existing.fields = sorted(set(existing.fields) | set(shown))
        if moved:
            existing.causes = [c for c in CAUSES if c == "rule" or c in existing.causes]
        if set(shown) - ({"arrival"} if moved else set()) and "data" not in existing.causes:
            existing.causes = [c for c in CAUSES if c == "data" or c in existing.causes]
    return found


# ---- the community entries -----------------------------------------------------------------------------------------------------------------


def _entry_changes(old: Release | None, new: Release) -> dict[str, Any]:
    """The community entries that differ between two releases, from what ``release.json`` records, compared by ``(key, issue)``: ``added`` (reports the new release has and the
    old one lacks), ``retracted`` (retractions it has and the old one lacks, with the reason), ``deleted`` (entries of the old release that the new file lists in neither list,
    and retractions that it no longer lists), ``changed`` (the same item and issue with other fields) and ``note``: the sentence that says a release does not list its entries,
    if one does not (then nothing is taken for added or retracted: a release without the field is not a release without entries). When it is the previous release that does not,
    the entries of the new one are ``first``: recorded in this release for the first time, never additions or retractions. A first release has nothing to compare."""
    found: dict[str, Any] = {"added": [], "retracted": [], "deleted": [], "changed": [], "first": {"reports": [], "retracted": []}, "note": None}
    if old is None:
        return found
    before, after = old.community, new.community
    if before is None or after is None:
        found["note"] = f"the {'previous' if before is None else 'new'} release does not list its community entries"
        if before is None and after is not None:
            found["first"] = {
                "reports": [{"key": key, "issue": issue} for key, issue in sorted(after["reports"])],
                "retracted": [{"key": key, "issue": issue, "reason": after["retracted"][key, issue]["reason"]} for key, issue in sorted(after["retracted"])],
            }
        return found
    found["added"] = [{"key": key, "issue": issue} for key, issue in sorted(set(after["reports"]) - set(before["reports"]))]
    found["retracted"] = [
        {"key": key, "issue": issue, "reason": after["retracted"][key, issue]["reason"]} for key, issue in sorted(set(after["retracted"]) - set(before["retracted"]))
    ]
    gone_reports = sorted(set(before["reports"]) - set(after["reports"]) - set(after["retracted"]))
    gone_retractions = sorted(set(before["retracted"]) - set(after["retracted"]))
    found["deleted"] = [{"key": key, "issue": issue, "was": "report"} for key, issue in gone_reports] + [
        {"key": key, "issue": issue, "was": "retraction"} for key, issue in gone_retractions
    ]
    for name, fields in (("reports", REPORT_FIELDS), ("retracted", RETRACTED_FIELDS)):
        for key, issue in sorted(set(before[name]) & set(after[name])):
            differing = [field for field in fields if before[name][key, issue][field] != after[name][key, issue][field]]
            if differing:
                found["changed"].append({"key": key, "issue": issue, "list": name, "fields": differing})
    return found


# ---- classifying a change -----------------------------------------------------------------------------------------------------------------


class Context:
    """The inputs and the item changes of two releases, and the question every change asks: why?"""

    def __init__(self, inputs: Inputs, items: Mapping[str, ItemChange]) -> None:
        self.inputs = inputs
        self.items = items
        self.community_keys = {key for key, change in items.items() if change.moves_level}

    def _explains(self, key: str, evidences: Iterable[str | None], *, community: bool) -> bool:
        """Whether the change of an item explains a pick that wears it. A field the solver reads explains every pick; a move of the evidence level explains a pick
        only where it changes the item's membership of the pool the pick was made from (an item that moves from wiki to strict is in the wiki pool before and
        after); and a move that a community entry made is the community's cause, a move nothing public explains is the data's. (A report that stood outweighed and counts
        now is both: the wiki's edit let it through, and nothing else makes the item strict.)"""
        change = self.items.get(key)
        if change is None:
            return False
        if community:
            return change.moves_level and _changes_pool(change.levels, evidences)
        return change.solver_fields or ((not change.moves_level or change.data_moves_level) and _changes_pool(change.levels, evidences))

    def causes(self, keys: Iterable[str], scopes: Sequence[Scope]) -> list[str]:
        """Every cause of a change in the picks of these ``scopes`` that wear these item ``keys``, in the order of precedence."""
        keys = [key for key in keys if key]
        evidences = {scope.evidence for scope in scopes} or {None}
        found = []
        if self.inputs.code:
            found.append("code")
        if self.inputs.rule_in(scopes):
            found.append("rule")
        if self.inputs.patch is not None or any(self._explains(key, evidences, community=False) for key in keys):
            found.append("data")
        if any(self._explains(key, evidences, community=True) for key in keys):
            found.append("community")
        return found

    def bundle_causes(self, inputs_only: bool) -> list[str]:
        """Every cause of a change in the bundle of a trio, in the order of precedence. The bundle's ``inputs`` field is one hash over the whole rules file and the
        catalog's levels, so a bundle that differs in that field alone is explained by any input change: a rule or a new version of the rules, the catalog, an item
        record or the patch. A bundle that differs elsewhere is explained only by the code, the rules and the patch: the source text of an item is no input of it."""
        inputs = self.inputs
        found = []
        if inputs.code:
            found.append("code")
        if inputs.rules or inputs.rules_version is not None:  # (a status or a note of the rules file changes the hash too)
            found.append("rule")
        if inputs.patch is not None or (inputs_only and (inputs.catalog_date is not None or inputs.catalog_changed or self.items)):
            found.append("data")
        if inputs_only and self.community_keys:
            found.append("community")
        return found


def _finish(change: dict[str, Any], causes: list[str], *, tie: bool) -> dict[str, Any]:
    change["causes"] = causes
    change["primary"] = causes[0] if causes else None
    change["flag"] = None if causes else ("tie" if tie else "solver-diff")
    return change


def _kit_diff(places: Sequence[str], old: Sequence[str | None], new: Sequence[str | None]) -> list[dict[str, Any]]:
    return [{"place": places[at], "old": a, "new": b} for at, (a, b) in enumerate(zip(old, new)) if a != b]


def _keys(*kits: Iterable[str | None]) -> list[str]:
    return sorted({key for kit in kits for key in kit if key})


# ---- the scenarios of a trio ---------------------------------------------------------------------------------------------------------------------


def _scenario_changes(slug: str, old: TrioData, new: TrioData, tiers: set[int], context: Context) -> Iterable[dict[str, Any]]:
    classes = frozenset(slug.upper().split("-"))
    places = new.place_names or old.place_names
    for key in sorted(set(old.rows) | set(new.rows)):
        evidence, buffs, race, role, tier, setup = key
        if tier not in tiers:
            continue
        a, b = old.rows.get(key), new.rows.get(key)
        view = {"evidence": evidence, "buffs": buffs, "race": race, "role": role, "tier": tier, "setup": setup}
        scope = [Scope(classes, race, tier, setup, evidence)]
        if a is None or b is None:
            row = b or a
            assert row is not None
            change = {
                "kind": "scenario", "trio": slug, "view": view, "change": "added" if a is None else "removed", "fields": ["row"],
                "F": [a.F if a else None, b.F if b else None], "delta": None, "items": _keys(row.kit),
            }  # fmt: skip
            yield _finish(change, context.causes(_keys(row.kit), scope), tie=False)
            continue
        fields = [name for name in ("F", "kit", "buffs", "haste", "totals") if getattr(a, name) != getattr(b, name)]
        if abs((b.F - b.gain) - (a.F - a.gain)) > GAIN_SLACK:  # the gain moved otherwise than with F: the value of the naked character is another one
            fields.append("gain")
        if not fields:
            continue
        change = {
            "kind": "scenario", "trio": slug, "view": view, "change": "changed", "fields": sorted(fields), "F": [a.F, b.F],
            "delta": round(b.F - a.F, 2), "items": _keys(a.kit, b.kit),
        }  # fmt: skip
        if "gain" in fields:
            change["gain"] = [a.gain, b.gain]
        if "kit" in fields:
            change["kit"] = _kit_diff(places, a.kit, b.kit)
        for name in ("buffs", "haste", "totals"):
            if name in fields:
                change[name] = [list(getattr(a, name)) if name != "haste" else a.haste, list(getattr(b, name)) if name != "haste" else b.haste]
        yield _finish(change, context.causes(change["items"], scope), tie=(a.F, a.gain) == (b.F, b.gain))  # (another kit of the same value and the same gain)


# ---- the default pick and the runner-ups -------------------------------------------------------------------------------------------------------------


def _default_kit(data: TrioData) -> tuple[tuple[str | None, ...] | None, dict[str, Any]]:
    doc = data.defaults
    view = doc.get("view") or {}
    key = (view.get("evidence"), view.get("buffs"), doc.get("race"), view.get("role"), view.get("tier"), doc.get("setup"))
    row = data.rows.get(key)  # type: ignore[arg-type]
    return (row.kit if row else None), {name: doc.get(name) for name in ("race", "runner_up_race", "setup", "F", "margin")}


def _default_view(data: TrioData) -> dict[str, Any]:
    """The view the default pick is made at: its role, tier, evidence level and buff set."""
    view = data.defaults.get("view") or {}
    return {name: view.get(name) for name in ("role", "tier", "evidence", "buffs")}


def _default_changes(slug: str, old: TrioData, new: TrioData, context: Context) -> Iterable[dict[str, Any]]:
    """The default pick of a trio, whole: its race, runner-up, setup, value, margin, kit, the view it is made at and its flip notes; a default that one release lacks
    is added or removed."""
    if not old.defaults and not new.defaults:
        return
    classes = frozenset(slug.upper().split("-"))
    if not old.defaults or not new.defaults:
        data = new if new.defaults else old
        kit, now = _default_kit(data)
        view = _default_view(data)
        change: dict[str, Any] = {
            "kind": "default", "trio": slug, "view": data.defaults.get("view"), "change": "added" if not old.defaults else "removed", "fields": ["default"],
            "items": _keys(kit or ()),
        }  # fmt: skip
        scopes = [Scope(classes, now["race"], view["tier"], now["setup"], view["evidence"])]
        yield _finish(change, context.causes(change["items"], scopes), tie=False)
        return
    a_kit, a = _default_kit(old)
    b_kit, b = _default_kit(new)
    a_view, b_view = _default_view(old), _default_view(new)
    fields = [name for name in a if a[name] != b[name]]
    if a_view != b_view:
        fields.append("view")
    if a_kit != b_kit and (a_kit is not None or b_kit is not None):
        fields.append("kit")
    if old.defaults.get("flip_notes") != new.defaults.get("flip_notes"):
        fields.append("flip_notes")
    if not fields:
        return
    scopes = [Scope(classes, a["race"], a_view["tier"], a["setup"], a_view["evidence"]), Scope(classes, b["race"], b_view["tier"], b["setup"], b_view["evidence"])]
    change = {
        "kind": "default", "trio": slug, "view": new.defaults.get("view"), "change": "changed", "fields": sorted(fields), "old": a, "new": b,
        "items": _keys(a_kit or (), b_kit or ()),
    }  # fmt: skip
    if a_view != b_view:
        change["old_view"] = a_view
    if "kit" in fields and a_kit is not None and b_kit is not None:
        change["kit"] = _kit_diff(new.place_names or old.place_names, a_kit, b_kit)
    yield _finish(change, context.causes(change["items"], scopes), tie=a["F"] == b["F"] and a["margin"] == b["margin"] and a_view == b_view)


def _runnerup_changes(slug: str, old: TrioData, new: TrioData, tiers: set[int], context: Context) -> Iterable[dict[str, Any]]:
    """The swaps of every view that either release has, at a tier both have: a view that one release lacks is added or removed, and the evidence level of a view is
    compared with its setup and its swaps."""
    classes = frozenset(slug.upper().split("-"))
    places = new.place_names or old.place_names
    for key in sorted(set(old.runnerups) | set(new.runnerups)):
        role, tier, race = key
        if tier not in tiers:
            continue
        a, b = old.runnerups.get(key), new.runnerups.get(key)
        if a is None or b is None:
            swaps = b or a
            assert swaps is not None
            row = (new if a is None else old).rows.get((swaps.evidence, "own", race, role, tier, swaps.setup))
            items = sorted({item for place in swaps.places for item, _ in place} | {item for item in (row.kit if row else ()) if item})
            change: dict[str, Any] = {
                "kind": "runner-up", "trio": slug, "role": role, "tier": tier, "race": race, "change": "added" if a is None else "removed", "fields": ["view"],
                "setup": swaps.setup, "evidence": swaps.evidence, "items": items,
            }  # fmt: skip
            yield _finish(change, context.causes(items, [Scope(classes, race, tier, swaps.setup, swaps.evidence)]), tie=False)
            continue
        fields = []
        if a.evidence != b.evidence:
            fields.append("evidence")
        if a.setup != b.setup:
            fields.append("setup")
        differing = [at for at, (one, other) in enumerate(zip(a.places, b.places)) if one != other]
        if differing:
            fields.append("places")
        if not fields:
            continue
        kit_keys: list[str] = []
        for data, swaps in ((old, a), (new, b)):
            row = data.rows.get((swaps.evidence, "own", race, role, tier, swaps.setup))
            kit_keys.extend(key for key in (row.kit if row else ()) if key)
        swap_keys = [item for at in differing for swaps in (a.places[at], b.places[at]) for item, _ in swaps]
        items = sorted(set(swap_keys) | set(kit_keys))
        change = {"kind": "runner-up", "trio": slug, "role": role, "tier": tier, "race": race, "change": "changed", "fields": fields, "items": items}
        if "evidence" in fields:
            change["evidence"] = [a.evidence, b.evidence]
        if "setup" in fields:
            change["setup"] = [a.setup, b.setup]
        if differing:
            change["places"] = [
                {"place": places[at], "old": [[item, delta] for item, delta in a.places[at]], "new": [[item, delta] for item, delta in b.places[at]]} for at in differing
            ]
        tie = fields == ["places"] and all(sorted(d for _, d in a.places[at]) == sorted(d for _, d in b.places[at]) for at in differing)
        scopes = [Scope(classes, race, tier, a.setup, a.evidence), Scope(classes, race, tier, b.setup, b.evidence)]
        yield _finish(change, context.causes(items, scopes), tie=tie)


# ---- the seals and the bundles ------------------------------------------------------------------------------------------------------------------------


def _pick(data: TrioData, role: str, tier: int, race: Any) -> tuple[list[str], str | None, str | None]:
    """The items worn in the pick that the seals of a role and tier are about (the default view of the race: its runner-up view says the setup and the evidence
    level), its setup and its evidence level."""
    swaps = data.runnerups.get((role, tier, race))
    if swaps is None:
        return [], None, None
    row = data.rows.get((swaps.evidence, "own", race, role, tier, swaps.setup))
    return [key for key in (row.kit if row else ()) if key], swaps.setup, swaps.evidence


def _seal_changes(slug: str, old: TrioData, new: TrioData, tiers: set[int], context: Context) -> Iterable[dict[str, Any]]:
    classes = frozenset(slug.upper().split("-"))
    race_a, race_b = old.seals.get("race"), new.seals.get("race")
    before, after = old.seals.get("roles", {}), new.seals.get("roles", {})
    wanted = sorted({(role, int(tier)) for roles in (before, after) for role, by_tier in roles.items() for tier in by_tier})
    for role, tier in wanted:
        if tier not in tiers:
            continue
        a, b = before.get(role, {}).get(str(tier)), after.get(role, {}).get(str(tier))
        kind = "added" if a is None else "removed" if b is None else "changed"
        change: dict[str, Any] = {"kind": "seal", "trio": slug, "role": role, "tier": tier, "change": kind}
        if kind == "changed":
            change["race"] = race_b if race_b == race_a else [race_a, race_b]
            fields = []
            differing = [place for place in dict.fromkeys([*b, *a]) if a.get(place) != b.get(place)]
            if differing:
                fields.append("places")
                change["places"] = [{"place": place, "old": a.get(place), "new": b.get(place)} for place in differing]
            if race_a != race_b:
                fields.append("race")
            if not fields:
                continue
            change["fields"] = fields
        else:
            change["race"] = race_b if kind == "added" else race_a
            change["fields"] = ["seal"]
        keys_a, setup_a, evidence_a = _pick(old, role, tier, race_a)
        keys_b, setup_b, evidence_b = _pick(new, role, tier, race_b)
        change["items"] = sorted(set(keys_a) | set(keys_b))
        scopes = [Scope(classes, race_a, tier, setup_a, evidence_a), Scope(classes, race_b, tier, setup_b, evidence_b)]
        yield _finish(change, context.causes(change["items"], scopes), tie=False)


def _differs_in_inputs_only(one: Path, other: Path) -> bool:
    """Whether two bundles are the same but for their ``inputs`` field (the hash over the rules file and the catalog's levels)."""
    try:
        first, second = _plain(one), _plain(other)
    except (OSError, ValueError):
        return False
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    first.pop("inputs", None)
    second.pop("inputs", None)
    return first == second


def _bundle_changes(slug: str, old: TrioData, new: TrioData, context: Context) -> Iterable[dict[str, Any]]:
    for name in sorted(set(old.bundles) | set(new.bundles)):
        a, b = old.bundles.get(name), new.bundles.get(name)
        if a == b:
            continue
        kind = "added" if a is None else "removed" if b is None else "changed"
        change = {"kind": "bundle", "trio": slug, "file": name, "change": kind, "fields": ["sha256"], "sha256": [a, b]}
        if kind == "changed":
            change["inputs_only"] = _differs_in_inputs_only(old.bundle_paths[name], new.bundle_paths[name])
        yield _finish(change, ["new"] if kind == "added" else context.bundle_causes(change.get("inputs_only", False)), tie=False)


# ---- trios and tiers ----------------------------------------------------------------------------------------------------------------------------


def _structural(old: Release | None, new: Release) -> tuple[list[dict[str, Any]], list[str], dict[str, set[int]]]:
    """The records of the trios and tiers that only one release has, the trios both have, and for each of those the tiers both have."""
    records: list[dict[str, Any]] = []
    both: list[str] = []
    common: dict[str, set[int]] = {}
    old_trios = dict(old.meta["trios"]) if old else {}
    new_trios = dict(new.meta["trios"])
    for slug in sorted(set(old_trios) | set(new_trios)):
        if slug not in old_trios or slug not in new_trios:
            release = new if slug in new_trios else old
            assert release is not None
            records.append(
                {
                    "kind": "trio", "trio": slug, "change": "new" if slug in new_trios else "removed", "tiers": list((new_trios if slug in new_trios else old_trios)[slug]),
                    "scenarios": release.scenario_count(slug), "causes": ["new"] if slug in new_trios else [], "primary": "new" if slug in new_trios else None, "flag": None,
                }
            )  # fmt: skip
            continue
        both.append(slug)
        before, after = set(old_trios[slug]), set(new_trios[slug])
        common[slug] = before & after
        for tier in sorted(before ^ after):
            release = new if tier in after else old
            records.append(
                {
                    "kind": "tier", "trio": slug, "tier": tier, "change": "new" if tier in after else "removed", "scenarios": release.scenario_count(slug, tier),
                    "causes": ["new"] if tier in after else [], "primary": "new" if tier in after else None, "flag": None,
                }
            )  # fmt: skip
    return records, both, common


def _same_files(old: Release, new: Release, slug: str) -> bool:
    """Whether every file of a trio is byte for byte the same in both releases (then nothing in it can have changed)."""
    names: dict[str, bool] = {}
    for release in (old, new):
        for here, _dirs, files in os.walk(release.folder / slug):
            for name in files:
                names[Path(here, name).relative_to(release.folder / slug).as_posix()] = True
    return all(
        (old.folder / slug / name).is_file() and (new.folder / slug / name).is_file() and (old.folder / slug / name).read_bytes() == (new.folder / slug / name).read_bytes()
        for name in names
    )


# ---- the report ---------------------------------------------------------------------------------------------------------------------------------------


def _sort_key(change: Mapping[str, Any]) -> tuple[Any, ...]:
    kind = change["kind"]
    head = (KIND_ORDER[kind], change.get("trio") or "")
    if kind == "scenario":
        view = change["view"]
        return (*head, view["evidence"], view["buffs"], view["race"], view["role"], view["tier"], view["setup"])
    if kind == "tier":
        return (*head, change["tier"])
    if kind == "runner-up":
        return (*head, change["role"], change["tier"], change["race"])
    if kind == "seal":
        return (*head, change["role"], change["tier"])
    if kind == "bundle":
        return (*head, change["file"])
    if kind == "item":
        return (*head, change["key"])
    return head


@dataclass
class Report:
    """The result of :func:`diff`: the counts (``summary``), every change (``changes``) and the two renderings."""

    release: str
    previous: str | None
    summary: dict[str, Any]
    changes: list[dict[str, Any]]
    note: str | None = None  # a sentence the caller adds: why there is nothing to compare with, say
    trial: bool = False  # the new release is a trial build (some trios, no pointer): the report says so in its first line

    def top(self, count: int = TOP) -> list[dict[str, Any]]:
        """The ``count`` changes of a value ``F`` that move it the most, the largest first (a tie by trio and view)."""
        moved = [c for c in self.changes if c["kind"] == "scenario" and c.get("delta")]
        moved.sort(key=lambda c: (-abs(c["delta"]), c["trio"], tuple(c["view"].values())))
        return moved[:count]

    def json_text(self) -> str:
        """Every change, as JSON: one change to a line, in a fixed order, the same text for the same releases."""
        head: dict[str, Any] = {"format": FORMAT, "release": self.release, "previous": self.previous}
        if self.trial:
            head["trial"] = True
        if self.note is not None:
            head["note"] = self.note
        return render({**head, "summary": self.summary, "changes": self.changes}, per_line=("changes",))

    def markdown(self) -> str:
        return _markdown(self)


def _count(changes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_kind = Counter(c["kind"] for c in changes)
    by_cause = {name: 0 for name in (*CAUSES, "new", "unexplained")}
    for change in changes:
        if change["primary"] is not None:
            by_cause[change["primary"]] += 1
        elif change["flag"] is not None:
            by_cause["unexplained"] += 1
    picks = [c for c in changes if c["kind"] in ("scenario", "default", "runner-up")]
    return {
        "changes": len(changes),
        "by_kind": {kind: by_kind[kind] for kind in KIND_ORDER if by_kind[kind]},
        "by_cause": by_cause,
        "community_only": sum(1 for c in picks if c["causes"] == ["community"]),
        "solver_diffs": sum(1 for c in changes if c["flag"] == "solver-diff"),
        "ties": sum(1 for c in changes if c["flag"] == "tie"),
        "new_trios": sum(1 for c in changes if c["kind"] == "trio" and c["change"] == "new"),
        "removed_trios": sum(1 for c in changes if c["kind"] == "trio" and c["change"] == "removed"),
        "new_tiers": sum(1 for c in changes if c["kind"] == "tier" and c["change"] == "new"),
        "removed_tiers": sum(1 for c in changes if c["kind"] == "tier" and c["change"] == "removed"),
    }


def diff(old: str | os.PathLike[str] | Release | None, new: str | os.PathLike[str] | Release) -> Report:
    """The report of what changed from ``old`` to ``new`` (each a release folder, a ``tar.gz`` or a :class:`Release`); ``old`` is ``None`` for a first
    release, which has every trio new. :class:`trioforge.precompute.assemble.ReleaseRefused` for a folder that is no release."""
    after = load_release(new)
    before = load_release(old) if old is not None else None
    records, both, common = _structural(before, after)
    changes: list[dict[str, Any]] = list(records)
    inputs: Inputs | None = None
    items: dict[str, ItemChange] = {}
    if before is not None:
        inputs = _inputs(before, after)
        old_rows: dict[str, set[tuple[Any, Any]]] = {}
        new_rows: dict[str, set[tuple[Any, Any]]] = {}
        decoded: dict[str, tuple[TrioData, TrioData]] = {}
        for slug in both:
            if _same_files(before, after, slug):
                continue
            decoded[slug] = (before.trio(slug), after.trio(slug))
            for rows, data in ((old_rows, decoded[slug][0]), (new_rows, decoded[slug][1])):
                for key, variants in data.item_rows.items():
                    rows.setdefault(key, set()).update(variants)  # (every trio's rows: the row of a later trio does not overwrite the one of an earlier)
        items = _item_changes(before, after, old_rows, new_rows, inputs)
        context = Context(inputs, items)
        for slug, (a, b) in decoded.items():
            changes.extend(_scenario_changes(slug, a, b, common[slug], context))
            changes.extend(_default_changes(slug, a, b, context))
            changes.extend(_runnerup_changes(slug, a, b, common[slug], context))
            changes.extend(_seal_changes(slug, a, b, common[slug], context))
            changes.extend(_bundle_changes(slug, a, b, context))
        for change in items.values():
            record = {
                "kind": "item", "trio": None, "key": change.key, "change": change.change, "fields": change.fields,
                "evidence": list(change.levels) if change.levels[0] != change.levels[1] else None, "community": change.community,
            }  # fmt: skip
            record.update(causes=change.causes, primary=change.causes[0] if change.causes else None, flag=None, items=[change.key])
            changes.append(record)
    changes.sort(key=_sort_key)
    entries = _entry_changes(before, after)
    summary = _count(changes)
    summary.update(
        release=after.tag,
        previous=before.tag if before is not None else None,
        inputs=inputs.summary() if inputs is not None else None,
        community={
            **{name: value for name, value in entries.items() if name != "note"},
            "strict_gained": sorted(k for k, c in items.items() if c.gained),
            "strict_lost": [{"key": k, "why": c.lost_why, "by": list(c.lost_by)} for k, c in sorted(items.items()) if c.lost],
            "note": entries["note"],
        },
        retractions=len(entries["retracted"]),
    )
    return Report(after.tag, before.tag if before is not None else None, summary, changes, trial=bool(after.meta.get("trial")))


# ---- the Markdown ---------------------------------------------------------------------------------------------------------------------------------------


def _view(change: Mapping[str, Any]) -> str:
    v = change["view"]
    return f"{v['race']} {v['role']} +{v['tier']} {v['setup']} ({v['evidence']}, {v['buffs']} buffs)"


def _where(change: Mapping[str, Any]) -> str:
    """Where a change is, without an item: the view of a scenario, the file of a bundle, the kind, role, tier and race of the others."""
    if change["kind"] == "scenario":
        return _view(change)
    if change["kind"] == "bundle":
        return f"bundle {change['file']}"
    race = change.get("race")
    race = "->".join(map(str, race)) if isinstance(race, list) else race
    return " ".join(str(part) for part in (change["kind"], change.get("role"), change.get("tier"), race) if part is not None)


def _keys_line(keys: Sequence[str]) -> str:
    shown = ", ".join(f"`{key}`" for key in keys[:LIST_LIMIT])
    return shown + (f" and {len(keys) - LIST_LIMIT} more (the JSON lists them all)" if len(keys) > LIST_LIMIT else "")


def _entries_line(entries: Sequence[Mapping[str, Any]], detail: Callable[[Mapping[str, Any]], str]) -> str:
    """Up to ``LIST_LIMIT`` entries as ``key (issue N, ...)``; the rest are counted."""
    shown = ", ".join(f"`{entry['key']}` (issue {entry['issue']}{detail(entry)})" for entry in entries[:LIST_LIMIT])
    return shown + (f" and {len(entries) - LIST_LIMIT} more (the JSON lists them all)" if len(entries) > LIST_LIMIT else "")


def _lost_lines(lost: Sequence[Mapping[str, Any]]) -> list[str]:
    """One line for the items that stopped being strict because the report was retracted, and one for those whose report is outweighed (with what outweighs it)."""
    retracted = [entry["key"] for entry in lost if entry["why"] == "retracted"]
    outweighed = [entry for entry in lost if entry["why"] == "outweighed"]
    lines = []
    if retracted:
        lines.append(f"- no longer strict, the report retracted ({len(retracted)}): {_keys_line(retracted)}")
    if outweighed:
        shown = ", ".join(f"`{entry['key']}` (by {', '.join(entry['by'])})" if entry["by"] else f"`{entry['key']}`" for entry in outweighed[:LIST_LIMIT])
        more = f" and {len(outweighed) - LIST_LIMIT} more (the JSON lists them all)" if len(outweighed) > LIST_LIMIT else ""
        lines.append(f"- no longer strict, the report outweighed ({len(outweighed)}): {shown}{more}")
    return lines


def _markdown(report: Report) -> str:
    s = report.summary
    title = "TRIAL results diff" if report.trial else "Results diff"
    lines = [f"# {title}: {report.release}" + (f" against {report.previous}" if report.previous else ""), ""]
    if report.trial:
        lines += ["**TRIAL: a build of some trios, to try the build. It is no release: no pointer was written, and nothing of it is to be committed or tagged.**", ""]
    if report.note:
        lines += [f"Note: {report.note}", ""]
    if report.previous is None:
        lines += [
            f"This is the first release: there is nothing to compare it with. It has {s['new_trios']} trio(s), and every one of them is new.",
            "",
        ]
    elif s["changes"] == 0:
        lines += [f"No change: every trio, scenario, default pick, runner-up and item record is the same as in {report.previous}.", ""]
    else:
        lines += [f"{s['changes']} changes in all; the JSON file kept in the build folder (it is not published) lists every one of them, and none is left out.", ""]
    solver = [c for c in report.changes if c["flag"] == "solver-diff"]
    if solver:
        lines += [
            "## SOLVER DIFF",
            "",
            f"**SOLVER DIFF: {len(solver)} change(s) with the same inputs and another answer. Treat each as a bug until it is explained.** "
            "No rule, no catalog record of an item in the kits and no code change accounts for them.",
            "",
        ]
        for change in solver[:LIST_LIMIT]:
            lines.append(f"- {change['trio']}: {_where(change)}")
        if len(solver) > LIST_LIMIT:
            lines.append(f"- and {len(solver) - LIST_LIMIT} more (the JSON lists them all)")
        lines.append("")
    inputs = s["inputs"]
    if inputs is not None:
        lines += ["## What changed in the inputs", ""]
        lines.append(f"- code and solver options: {'changed' if inputs['code'] else 'the same'}")
        lines.append(f"- rules: {_keys_line(inputs['rules']) if inputs['rules'] else 'the same'}" + (f" (version {inputs['rules_version'][0]} to {inputs['rules_version'][1]})" if inputs["rules_version"] else ""))
        lines.append(f"- game client data: {'patch ' + inputs['game_patch'][0] + ' to ' + inputs['game_patch'][1] if inputs['game_patch'] else 'the same'}")
        lines.append(f"- catalog: {'snapshot ' + inputs['catalog_date'][0] + ' to ' + inputs['catalog_date'][1] if inputs['catalog_date'] else 'the same snapshot'}")
        lines.append("")
    if s["changes"]:
        lines += ["## Counts", "", "| kind | changes |", "|---|---|"]
        lines += [f"| {kind} | {count} |" for kind, count in s["by_kind"].items()]
        lines += ["", "| first cause | changes |", "|---|---|"]
        lines += [f"| {cause} | {count} |" for cause, count in s["by_cause"].items()]
        lines += [
            "",
            f"Ties (another kit or order of the same value): {s['ties']}. Solver diffs: {s['solver_diffs']}. Picks that rest on community evidence alone: {s['community_only']}.",
            "",
        ]
    community = s["community"]
    shown = [
        (f"- The entries of the list of reports cannot be compared: {community['note']}." if community["note"] else None),
        (
            f"- recorded in this release for the first time, reports ({len(community['first']['reports'])}): {_entries_line(community['first']['reports'], lambda e: '')}"
            if community["first"]["reports"]
            else None
        ),
        (
            f"- recorded in this release for the first time, retracted ({len(community['first']['retracted'])}): "
            f"{_entries_line(community['first']['retracted'], lambda e: ', ' + e['reason'])}"
            if community["first"]["retracted"]
            else None
        ),
        (f"- added ({len(community['added'])}): {_entries_line(community['added'], lambda e: '')}" if community["added"] else None),
        (f"- retracted ({len(community['retracted'])}): {_entries_line(community['retracted'], lambda e: ', ' + e['reason'])}" if community["retracted"] else None),
        (
            f"- taken out of the file with no retraction ({len(community['deleted'])}): {_entries_line(community['deleted'], lambda e: '')}"
            if community["deleted"]
            else None
        ),
        (
            f"- changed in place ({len(community['changed'])}): {_entries_line(community['changed'], lambda e: ', ' + e['list'] + ': ' + ', '.join(e['fields']))}"
            if community["changed"]
            else None
        ),
        (f"- strict now because of a report ({len(community['strict_gained'])}): {_keys_line(community['strict_gained'])}" if community["strict_gained"] else None),
        *_lost_lines(community["strict_lost"]),
    ]
    if any(shown):
        lines += ["## Community evidence", "", *(line for line in shown if line), ""]
    structural = [c for c in report.changes if c["kind"] in ("trio", "tier")]
    if structural:
        lines += ["## New and removed trios and tiers", ""]
        for change in structural[:LIST_LIMIT]:
            what = f"trio {change['trio']}" if change["kind"] == "trio" else f"+{change['tier']} of {change['trio']}"
            lines.append(f"- {change['change']} {what}: {change['scenarios']} scenarios")
        if len(structural) > LIST_LIMIT:
            lines.append(f"- and {len(structural) - LIST_LIMIT} more (the JSON lists them all)")
        lines.append("")
    top = report.top()
    if top:
        total = sum(1 for c in report.changes if c["kind"] == "scenario" and c.get("delta"))
        lines += [f"## The {len(top)} largest changes of F (of {total})", "", "| trio | view | old F | new F | change | causes |", "|---|---|---|---|---|---|"]
        for change in top:
            old_value, new_value = change["F"]
            causes = ", ".join(change["causes"]) or (change["flag"] or "")
            lines.append(f"| {change['trio']} | {_view(change)} | {old_value:.2f} | {new_value:.2f} | {change['delta']:+.2f} | {causes} |")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
