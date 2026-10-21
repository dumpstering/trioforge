"""Everything the trio page and the page of an item say, as data the templates print.

The words and number formats here are repeated by the browser code (``static/format.js`` and ``static/trio.js``), which
rewrites parts of the page when a switch changes. ``tests-js/trio.test.mjs`` checks that the two agree, by re-rendering the
default view in the browser and comparing what the reader sees.

Numbers shown are whole: ``display_int`` rounds half up with one floating-point addition and a floor, the same two
operations the browser does, so both always print the same digit. Negative numbers use the true minus sign.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from trioforge.classes import CLASS_CODES, CLASS_NAMES
from trioforge.data import races as races_module
from trioforge.site import art, data
from trioforge.site.content import SEALS, RuleBook, RuleView, wiki_url

__all__ = [
    "BEST_FOR_MAX",
    "BuffOption",
    "EVIDENCE_CODES",
    "EvidenceNote",
    "Fact",
    "ITEM_BASE",
    "ITEM_NOTES",
    "ItemPage",
    "KitRow",
    "RaceOption",
    "SLOT_LABELS",
    "STAT_LABELS",
    "SourceLine",
    "TIERS",
    "TITLE_SUFFIX",
    "TierRow",
    "TrioLink",
    "TrioPage",
    "WeaponTable",
    "aa_text",
    "arrival_label",
    "default_kit_keys",
    "deity_text",
    "display_int",
    "flip_text",
    "flips_more",
    "fmt_int",
    "fmt_signed",
    "has_wiki_page",
    "haste_text",
    "item_href",
    "item_page",
    "race_options",
    "reach_text",
    "robust_note",
    "rule_ref",
    "tier_label",
    "trio_caps",
    "trio_name",
    "trio_page",
    "weakest",
]

MINUS = "−"
EN_DASH = "–"
DASH = "—"

SLOT_LABELS: tuple[str, ...] = (
    "Head", "Face", "Ear 1", "Ear 2", "Neck", "Shoulders", "Arms", "Back", "Wrist 1", "Wrist 2", "Hands", "Finger 1",
    "Finger 2", "Chest", "Legs", "Feet", "Waist", "Range", "Any slot 1", "Any slot 2", "Main hand", "Off hand",
)  # fmt: skip
assert len(SLOT_LABELS) == data.KIT_SIZE

ROLE_LABELS = {"balanced": "Balanced", "tank": "Tank", "melee": "Melee", "caster": "Caster (healing or nuking)"}
ROLE_HINTS = {
    "balanced": "An equal blend of staying alive and doing damage, for this trio's classes.",
    "tank": "Staying alive first: armour class, hit points and haste.",
    "melee": "Damage first: attack, haste and dexterity, then hit points.",
    "caster": "Mana first, for healing or nuking.",
}
SETUP_LABELS = {"1h-shield": "1H + shield", "2h": "Two-hander", "dw": "Dual wield", "stick": "Stat stick"}
SETUP_PHRASES = {"1h-shield": "1H + shield", "2h": "two-hander", "dw": "dual wield", "stick": "stat stick"}
BUFF_LABELS = {"own": "Your own buffs", "group": "Common group buffs", "raid": "Full raid"}
BUFF_PHRASES = {"own": "your own buffs", "group": "common group buffs", "raid": "full raid buffs"}
#: the choices of the Buffs assumption: the two buff sets the precompute has answers for, and the raid, which the optimizer works out for the visitor (with an Enchanter in the group the
#: page code makes a fourth set of the two, "group+enchanter", a checkbox of its own)
BUFF_CHOICES = (*data.BUFFS, "raid")
#: the evidence levels of an item that have a page (wiki is the one level a release is built from, and no page words a level: the decision of 2026-10-19)
PAGE_LEVELS = ("strict", "wiki")
SEAL_ORDER = tuple(SEALS)  # the seals, the surest first: a figure made from several rules is as sure as the least sure of them
MAX_FLIPS = 3  # the notes of the open rules that could change the best race that the page shows; the rest are counted
SEAL_ICON = {key: f"i-{key}" for key in SEALS}
EMPTY_NAME = "Leave empty"
SPELL_RANK = "spell rank"
#: where the pages of the items are (``/item/<key>/``); the page code of a trio page links the names it paints by the same base (the ``data-items`` of the page)
ITEM_BASE = "/item/"

#: the pieces of the default weapons the page names in a search-result description, most telling first
_DESCRIPTION_SLOTS = (20, 13, 0)


# ---- numbers and wording the browser code repeats ---------------------------------------------------------------------------


def display_int(value: float) -> int:
    """Round half up (toward plus infinity): one addition and a floor, exactly what the browser does."""
    return math.floor(value + 0.5)


def fmt_int(number: int) -> str:
    text = f"{abs(number):,}"
    return MINUS + text if number < 0 else text


def fmt_signed(number: int) -> str:
    """``+7,770``, ``0`` or ``−1,234``."""
    return "+" + fmt_int(number) if number > 0 else fmt_int(number)


def tier_label(tier: int) -> str:
    return f"+{tier}"


def haste_text(percent: int) -> str:
    """The haste the weapons were scored at, as the Assumes line shows it."""
    return f"{percent}%"


def deity_text(names: tuple[str, ...] | None) -> str:
    """The badge of an item only some deities can use, as the pages and the browser code show it."""
    return "Needs deity: " + " or ".join(names) if names else ""


def reach_text(arrival: int | None, tier: int) -> str:
    """What reaching ``tier`` costs for an item that arrives at ``arrival``: a duplicate at +k gives 2^k of the 2^N needed.
    A summoned item (no arrival tier) is made at its spell rank, so there is nothing to count."""
    if arrival is None or tier <= arrival:
        return ""
    return f"{fmt_int(2 ** (tier - arrival))} copies to reach {tier_label(tier)}"


def arrival_label(arrival: int | None) -> str:
    """The "Arrives at" cell: a tier, or the spell rank of a summoned item."""
    return SPELL_RANK if arrival is None else tier_label(arrival)


def flip_text(notes: Sequence[str]) -> str:
    """The first :data:`MAX_FLIPS` notes of what could change the best race, one after the other."""
    return "; ".join(notes[:MAX_FLIPS])


def flips_more(notes: Sequence[str]) -> int:
    """How many notes :func:`flip_text` leaves out."""
    return max(0, len(notes) - MAX_FLIPS)


def aa_text(rank: int, enhancement: bool) -> str:
    """The AA choices of the default view, as the Assumes line words them."""
    return ", ".join(label for label, _ in _aa_labels(rank, enhancement))


def _aa_labels(rank: int, enhancement: bool) -> tuple[tuple[str, str], ...]:
    """``(words, rule id)`` for the two AA choices: Combat Stability by rank, and Physical Enhancement, which a trio of casters only
    has only if the open rule says so."""
    return (
        (f"Combat Stability {rank}" if rank else "no Combat Stability", "ac.softcap.combat_stability_pct"),
        (
            "Physical Enhancement" if enhancement else "no Physical Enhancement",
            "ac.softcap.physical_enhancement_pct" if enhancement else "ac.softcap.pe_for_caster_only_trios",
        ),
    )


def trio_name(trio: tuple[str, ...]) -> str:
    return " / ".join(CLASS_NAMES[code] for code in trio)


def item_href(key: str) -> str:
    """The address of the page of an item."""
    return f"{ITEM_BASE}{key}/"


# ---- races -----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RaceOption:
    code: str
    name: str
    legal: bool  # can a new character start as one of the trio's classes in this race?
    best: bool


def race_options(codes: list[str] | tuple[str, ...], *, trio: tuple[str, ...], best: str) -> list[RaceOption]:
    """The races to offer: the best one first, then the others that can start the trio, then those that need an unlock."""
    table = races_module.load()
    options = []
    for code in codes:
        primaries = set(races_module.legal_primaries(code, data=table))
        options.append(RaceOption(code, races_module.RACE_NAMES[code], bool(primaries & set(trio)), code == best))
    return sorted(options, key=lambda o: (not o.best, not o.legal, o.name))


# ---- the trio page --------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleOption:
    code: str
    label: str
    hint: str
    setups: tuple[str, ...]
    checked: bool


@dataclass(frozen=True)
class TierOption:
    value: int
    label: str
    text: str
    selected: bool


@dataclass(frozen=True)
class SetupOption:
    code: str
    label: str
    phrase: str
    visible: bool
    checked: bool


@dataclass(frozen=True)
class BuffOption:
    """A radio of the Assumes panel: the buffs."""

    code: str
    label: str
    phrase: str
    checked: bool


@dataclass(frozen=True)
class KitRow:
    slot: str
    empty: bool
    name: str
    deity: str
    tier: str
    arrival: str
    reach: str
    source: str
    href: str | None = None  # the page of the item, where it has one: the name is a link to it; plain text where it has none
    icon: str | None = None  # the art of the place (art.SLOT_ICONS), for the picture beside its name: None where the place has none or the art is not part of the site


@dataclass(frozen=True)
class RuleRef:
    """A link to one rule with its seal, for a number on the page."""

    id: str
    title: str
    seal: str
    seal_label: str
    seal_icon: str
    open_test: str | None


@dataclass(frozen=True)
class TotalsRow:
    """A line of "Why this kit". ``cap_rules`` is set for a cap that is itself made from rules (the softcap of the sheet AC): the
    words to link each with, and ``cap_seal`` the seal of the weakest of them."""

    field: str
    label: str
    value: str
    cap: str
    rule: RuleRef
    cap_rules: tuple[tuple[str, RuleRef], ...] = ()
    cap_seal: RuleRef | None = None


@dataclass(frozen=True)
class Swap:
    name: str
    delta: str
    deity: str


@dataclass(frozen=True)
class RunnerRow:
    slot: str
    swaps: tuple[Swap, ...]


@dataclass(frozen=True)
class Caps:
    softcap: int
    haste: int
    resist: int
    regen: tuple[int, int, int]  # HP, mana, endurance
    haste_rule: str
    cs_rank: int  # the Combat Stability rank the softcap assumes (the top rank by default)
    pe: bool  # whether it assumes Physical Enhancement (a trio with a melee class has it)


@dataclass(frozen=True)
class TrioPage:
    slug: str
    name: str
    level: int
    title: str
    description: str
    best_name: str
    runner_up_name: str
    margin: str
    flips: str
    races: tuple[RaceOption, ...]
    roles: tuple[RoleOption, ...]
    tiers: tuple[TierOption, ...]
    setups: tuple[SetupOption, ...]
    buffs: tuple[BuffOption, ...]
    weight_groups: tuple[str, ...]  # the slider groups of the trio's bundle, in its order: the page code draws a slider for each, and a `w` of the address has a character for each
    default: dict[str, Any]
    verdict_race: str
    verdict_role: str
    verdict_tier: str
    verdict_setup: str
    role_hint: str
    assume_buffs: str
    assume_setup: str
    assume_haste: str
    summary_assumes: str
    runnerups_assumes: str
    rows: tuple[KitRow, ...]
    value: str
    gain: str
    totals: tuple[TotalsRow, ...]
    w_setup: str
    w_main: str
    w_off: str
    w_others: tuple[str, ...]
    weapons_rule: RuleRef
    roles_rule: RuleRef
    runnerups: tuple[RunnerRow, ...]
    runnerups_available: bool
    runnerups_files: tuple[str, ...]
    robust_summary: str
    robust_items: tuple[str, ...]
    robust_note: str
    data_base: str
    release: str
    flips_more: int
    margin_rules: tuple[RuleRef, ...]
    tier_rules: tuple[RuleRef, ...]
    haste_rules: tuple[RuleRef, ...]
    delta_rules: tuple[RuleRef, ...]
    aa: tuple[tuple[str, RuleRef], ...]
    aa_seal: RuleRef
    items_base: str = ""  # the address the page code links the names of the items it paints by, or nothing when no pages of items were given


def rule_ref(book: RuleBook, rule_id: str) -> RuleRef:
    rule: RuleView = book.get(rule_id)
    return RuleRef(
        id=rule.id,
        title=rule.title,
        seal=rule.seal,
        seal_label=rule.seal_label,
        seal_icon=SEAL_ICON[rule.seal],
        open_test=rule.test if rule.status == "open" else None,
    )


def weakest(refs: Sequence[RuleRef]) -> RuleRef:
    """The rule with the weakest seal of these: a figure made from all of them carries that seal."""
    return max(refs, key=lambda ref: SEAL_ORDER.index(ref.seal))


@functools.lru_cache(maxsize=4)
def _tables():
    from trioforge.model import tables

    return tables.load()


def trio_caps(trio: tuple[str, ...], level: int, rules: Any) -> Caps:
    """The caps a trio's totals are shown against, from the model's own profile (so the page never re-derives them)."""
    from trioforge.model.profile import make_profile

    profile = make_profile("HUM", trio, level, "balanced", None, None, _tables(), rules)
    regen = profile.caps["regen"]
    return Caps(
        softcap=profile.effective_softcap,
        haste=int(profile.haste_cap),
        resist=int(profile.caps["resist"]),
        regen=(int(regen["HP"]), int(regen["MANA"]), int(regen["END"])),
        haste_rule="haste.cap_pct_with_monk" if "MNK" in trio else "haste.cap_pct",
        cs_rank=int(profile.aa["combat_stability"]),
        pe=bool(profile.aa["physical_enhancement"]),
    )


def kit_rows(scenario: data.Scenario, pages: Collection[str] | None = None) -> tuple[KitRow, ...]:
    """The 22 rows of "Wear this". ``pages`` are the keys of the items that have a page of their own (:func:`trioforge.site.build.item_page_keys`): the name of such an item links to
    its page, and that of any other (a disputed or a hidden item has no page) stays plain text, as it does when no pages are given."""
    rows = []
    for label, group, item in zip(SLOT_LABELS, data.SLOT_INSTANCES, scenario.kit, strict=True):
        icon = art.slot_icon(group)
        if item is None:
            rows.append(KitRow(label, True, EMPTY_NAME, "", DASH, DASH, "", DASH, icon=icon))
            continue
        rows.append(
            KitRow(
                slot=label,
                empty=False,
                name=item.name,
                deity=deity_text(item.deity),
                tier=tier_label(scenario.tier),
                arrival=arrival_label(item.arrival),
                reach=reach_text(item.arrival, scenario.tier),
                source=item.source,
                href=item_href(item.key) if pages is not None and item.key in pages else None,
                icon=icon,
            )
        )
    return tuple(rows)


def totals_rows(scenario: data.Scenario, caps: Caps, book: RuleBook) -> tuple[TotalsRow, ...]:
    t = scenario.totals
    ref = lambda rule_id: rule_ref(book, rule_id)  # noqa: E731
    resist_rule = ref("resist.cap")
    regen_rule = ref("regen.gear_caps")
    none = "no cap"
    # the softcap is the client's table of caps raised by the percentages of Combat Stability and Physical Enhancement, which are the
    # model's: it carries the seal of the weakest of the three and links them all
    softcap_rules = (
        ("client AC table", ref("ac.softcap.past_cap_rate")),
        ("Combat Stability", ref("ac.softcap.combat_stability_pct")),
        ("Physical Enhancement", ref("ac.softcap.physical_enhancement_pct" if caps.pe else "ac.softcap.pe_for_caster_only_trios")),
    )
    rows = [
        TotalsRow(
            "ac", "Sheet AC", fmt_int(t.ac), f"{fmt_int(caps.softcap)} softcap", ref("ac.softcap.past_cap_rate"),
            cap_rules=softcap_rules, cap_seal=weakest([r for _, r in softcap_rules]),
        ),  # fmt: skip
        TotalsRow("hp", "Hit points", fmt_int(t.hp), none, ref("hp.pools_counted")),
        TotalsRow("mana", "Mana", fmt_int(t.mana), none, ref("mana.pools_counted")),
        TotalsRow("end", "Endurance", fmt_int(t.end), none, ref("end.formula")),
        TotalsRow("haste", "Haste", f"{t.haste}%", f"{caps.haste}%", ref(caps.haste_rule)),
        TotalsRow("atk", "Attack", fmt_int(t.atk), none, ref("stats.str_to_atk")),
    ]
    for field_name, label, value in zip(("mr", "fr", "cr", "dr", "pr"), ("Magic", "Fire", "Cold", "Disease", "Poison"), t.resists):
        rows.append(TotalsRow(field_name, f"{label} resist", fmt_int(value), fmt_int(caps.resist), resist_rule))
    for field_name, label, value, cap in zip(
        ("hpreg", "manareg", "endreg"), ("HP regen", "Mana regen", "Endurance regen"), t.regen, caps.regen
    ):
        rows.append(TotalsRow(field_name, label, fmt_int(value), fmt_int(cap), regen_rule))
    return tuple(rows)


def _hand_names(scenario: data.Scenario) -> tuple[str, str]:
    main, off = scenario.kit[20], scenario.kit[21]
    return (main.name if main else "Empty", off.name if off else "Empty")


def other_setups(shard: data.Shard, scenario: data.Scenario) -> tuple[str, ...]:
    lines = []
    for setup in shard.setups_for(scenario.role):
        if setup == scenario.setup:
            continue
        other = shard.scenario(scenario.race, scenario.role, scenario.tier, setup)
        assert other is not None
        main, off = other.kit[20], other.kit[21]
        pair = main.name if main else "nothing"
        if off is not None:
            pair += f" + {off.name}"
        lines.append(f"{SETUP_LABELS[setup]}: {pair} ({fmt_signed(display_int(other.value - scenario.value))})")
    return tuple(lines)


def runner_rows(view: data.RunnerUpView | None) -> tuple[RunnerRow, ...]:
    rows = []
    for index, label in enumerate(SLOT_LABELS):
        swaps = view.slots[index] if view is not None else ()
        rows.append(
            RunnerRow(
                label,
                tuple(
                    Swap(s.item.name, fmt_signed(display_int(s.delta)), deity_text(s.item.deity))
                    for s in swaps
                ),
            )
        )
    return tuple(rows)


def robust_text(labels: tuple[str, ...] | None, scenario: data.Scenario) -> tuple[str, tuple[str, ...]]:
    """The summary sentence and the list of picks that depend on an assumption."""
    if labels is None:
        return ("", ())
    depending = [(i, label) for i, label in enumerate(labels) if label != "robust"]
    held = len(labels) - len(depending)
    if not depending:
        return (f"All {len(labels)} picks hold in every check.", ())
    verb = "depends" if len(depending) == 1 else "depend"
    summary = f"{held} of {len(labels)} picks hold in every check. The other {len(depending)} {verb} on an assumption:"
    items = []
    for index, label in depending:
        item = scenario.kit[index]
        items.append(f"{SLOT_LABELS[index]}: {item.name if item else 'empty'} {EN_DASH} {label}")
    return (summary, tuple(items))


def robust_note(robust: data.Robust) -> str:
    """What the robust-core box says for a view that has no seals: they exist for the default race at some tiers only."""
    tiers = [tier_label(tier) for tier in sorted({view.tier for view in robust.views})]
    if not tiers:
        return "Robustness checks were not computed for this trio."
    named = tiers[0] if len(tiers) == 1 else ", ".join(tiers[:-1]) + " and " + tiers[-1]
    return f"Robustness checks cover the default race at {named} only."


def description(scenario: data.Scenario, name: str, level: int) -> str:
    picks = [scenario.kit[i].name for i in _DESCRIPTION_SLOTS if scenario.kit[i] is not None]
    while True:
        if len(picks) > 1:
            named = ", ".join(picks[:-1]) + " and " + picks[-1]
        else:
            named = picks[0] if picks else "a full kit"
        text = f"The best gear for a level {level} {name}: {named}, in all {data.KIT_SIZE} slots, for every race, role and tier."
        if len(text) <= 240 or len(picks) <= 1:
            return text
        picks.pop()


def trio_page(results: data.TrioResults, book: RuleBook, caps: Caps, pages: Collection[str] | None = None) -> TrioPage:
    """The trio page with its default answer baked in. The answer is the view ``defaults.json`` names: its role, tier,
    evidence level (the wiki level: no item is strict in a release) and buffs, the best race there and that race's best setup. The page words no evidence level and offers no
    choice of one; the level is only the shard the page code reads (``default["ev"]``).

    ``pages`` are the keys of the items that have a page (:func:`kit_rows`). The page code paints other kits when a switch changes, and links their names the same way, by
    ``items_base``: it is set when pages are given, and they must then cover every item the page can show, so that a name the code paints is never a link that leads nowhere.
    Kits hold strict and wiki wearables only, and those have pages, so it holds; a ``ValueError`` that names the trio and the item says so when it does not, where a page that
    quietly lost every link would hide it."""
    meta = results.meta
    if pages is not None:
        unlinked = sorted(item.key for item in data.used_items(results) if item.key not in pages)
        if unlinked:
            more = f" (and {len(unlinked) - 1} more like it)" if len(unlinked) > 1 else ""
            raise ValueError(
                f"{meta.slug}: the trio page can show {unlinked[0]}{more}, which has no page of its own: every item a trio page can show must have one, "
                "since the page code links the names it paints by one base"
            )
    defaults = results.defaults
    shard = results.shards[(defaults.evidence, defaults.buffs)]
    role, tier, race, setup = defaults.role, defaults.tier, defaults.race, defaults.setup
    scenario = shard.scenario(race, role, tier, setup)
    assert scenario is not None
    name = trio_name(meta.trio)
    race_opts = race_options(shard.races, trio=meta.trio, best=race)
    race_names = {o.code: o.name for o in race_opts}
    role_setups = {r: shard.setups_for(r) for r in shard.roles}  # what the default level offers, which the page shows first
    # The page code shows the choices of whichever evidence level is picked next, and a level can have a setup the default level
    # has not (the shield setup, while the strict pool has no shield): every setup of any level gets a choice in the page, and
    # the ones the default level does not offer are hidden.
    every = {s for level in results.shards.values() for r in level.roles for s in level.setups_for(r)}
    all_setups = [s for s in data.SETUPS if s in every]
    # the seals are baked in only if they were made for the view the page opens on
    summary, items = robust_text(results.robust.labels_for(race, role, tier, setup, defaults.evidence, defaults.buffs), scenario)
    runner_view = results.runnerups.view(race, role, tier)
    if runner_view is not None and runner_view.setup != setup:
        runner_view = None  # runner-ups are for the role's best setup only
    value, gain = display_int(scenario.value), display_int(scenario.gain)
    return TrioPage(
        slug=meta.slug,
        name=name,
        level=meta.level,
        title=f"{name} best gear, level {meta.level} · TrioForge",
        description=description(scenario, name, meta.level),
        best_name=race_names[race],
        runner_up_name=race_names[defaults.runner_up],
        margin=fmt_signed(display_int(defaults.margin)),
        flips=flip_text(defaults.flips),
        flips_more=flips_more(defaults.flips),
        races=tuple(race_opts),
        roles=tuple(
            RoleOption(r, ROLE_LABELS[r], ROLE_HINTS[r], role_setups[r], r == role) for r in shard.roles
        ),
        tiers=tuple(
            TierOption(t, tier_label(t), tier_label(t) + (" (endgame)" if t == data.MAX_TIER else ""), t == tier)
            for t in shard.tiers
        ),
        setups=tuple(
            SetupOption(s, SETUP_LABELS[s], SETUP_PHRASES[s], s in role_setups[role], s == setup) for s in all_setups
        ),
        buffs=tuple(BuffOption(b, BUFF_LABELS[b], BUFF_PHRASES[b], b == defaults.buffs) for b in BUFF_CHOICES),
        weight_groups=tuple(results.bundle.document["weight_groups"]["groups"]),
        default={"race": race, "role": role, "tier": tier, "setup": setup, "ev": defaults.evidence, "buffs": defaults.buffs},
        verdict_race=race_names[race],
        verdict_role=ROLE_LABELS[role],
        verdict_tier=tier_label(tier),
        verdict_setup=SETUP_LABELS[setup],
        role_hint=ROLE_HINTS[role],
        assume_buffs=BUFF_PHRASES[defaults.buffs],
        assume_setup=SETUP_PHRASES[setup],
        assume_haste=haste_text(scenario.haste_assumed),
        summary_assumes=f"{SETUP_PHRASES[setup]}, {BUFF_PHRASES[defaults.buffs]}",
        runnerups_assumes=f"{BUFF_PHRASES[defaults.buffs]}, the role's best weapon setup and the role's own weights",
        rows=kit_rows(scenario, pages),
        value=fmt_int(value),
        gain=fmt_signed(gain),
        totals=totals_rows(scenario, caps, book),
        w_setup=SETUP_LABELS[setup],
        w_main=_hand_names(scenario)[0],
        w_off=_hand_names(scenario)[1],
        w_others=other_setups(shard, scenario),
        weapons_rule=rule_ref(book, "weapons.damage_weight"),
        roles_rule=rule_ref(book, "roles.templates"),
        runnerups=runner_rows(runner_view),
        runnerups_available=runner_view is not None,
        runnerups_files=results.runnerups.roles(),  # the files the page may ask for: one for each role, with every tier of the run in it
        robust_summary=summary,
        robust_items=items,
        robust_note=robust_note(results.robust),
        data_base=f"/data/{meta.slug}/",
        release=meta.data_tag,
        margin_rules=tuple(rule_ref(book, rule_id) for rule_id in ("roles.balanced", "roles.templates")),
        tier_rules=tuple(rule_ref(book, rule_id) for rule_id in ("tier.stat_rule", "tier.arrival", "tier.exp_needed")),
        haste_rules=tuple(rule_ref(book, rule_id) for rule_id in (caps.haste_rule, "haste.worn_per_tier")),
        delta_rules=tuple(rule_ref(book, rule_id) for rule_id in ("roles.balanced", "roles.templates")),
        aa=tuple((label, rule_ref(book, rule_id)) for label, rule_id in _aa_labels(caps.cs_rank, caps.pe)),
        aa_seal=weakest([rule_ref(book, rule_id) for _, rule_id in _aa_labels(caps.cs_rank, caps.pe)]),
        items_base=ITEM_BASE if pages is not None else "",
    )


# ---- the item page ---------------------------------------------------------------------------------------------------------------


#: the tiers a page shows, +0 to +10: every one is worked out by ``at_tier``, none is estimated from the others
TIERS = tuple(range(data.MAX_TIER + 1))
#: the most trios an item page names as the ones it is best for; the others are counted
BEST_FOR_MAX = 20
TITLE_SUFFIX = " · TrioForge"
DESCRIPTION_MAX = 240
#: a slot of the table, as a page says it (the places of a kit have their own labels, :data:`SLOT_LABELS`; these are the groups an item lists)
SLOT_NAMES = {
    "HEAD": "Head", "FACE": "Face", "EAR": "Ear", "NECK": "Neck", "SHOULDERS": "Shoulders", "ARMS": "Arms", "BACK": "Back", "WRIST": "Wrist",
    "HANDS": "Hands", "FINGER": "Finger", "CHEST": "Chest", "LEGS": "Legs", "FEET": "Feet", "WAIST": "Waist", "RANGE": "Range",
    "PRIMARY": "Main hand", "SECONDARY": "Off hand", "ANY": "Any slot", "AMMO": "Ammo", "CHARM": "Charm", "POWERSOURCE": "Power source",
}  # fmt: skip
#: the row of a stat in the table of tiers
STAT_LABELS = {
    "AC": "AC", "STR": "Strength", "STA": "Stamina", "AGI": "Agility", "DEX": "Dexterity", "WIS": "Wisdom", "INT": "Intelligence",
    "CHA": "Charisma", "HP": "Hit points", "MANA": "Mana", "END": "Endurance", "ATK": "Attack", "HPREG": "HP regen",
    "MANAREG": "Mana regen", "ENDREG": "Endurance regen", "HASTE": "Haste (%)", "FIRE": "Fire resist", "COLD": "Cold resist",
    "MAGIC": "Magic resist", "POISON": "Poison resist", "DISEASE": "Disease resist", "CORRUPTION": "Corruption resist",
    "WEIGHT": "Weight (stone)", "DAMAGE": "Damage", "DELAY": "Delay",
}  # fmt: skip
#: where an item comes from, in the order the trio page words it (a drop, a quest, a vendor, a recipe, foraging): the key of the table's ``source`` and the label of the line
SOURCE_LINES = (("drops", "Drops in"), ("quests", "Quests"), ("sold", "Vendors in"), ("crafted", "Crafted"), ("forage", "Foraged in"))
LORE_TEXT = "Yes (only one can be carried)"
#: the codes the evidence ladder gives to the evidence of an item, the reasons that it is at its level (data/evidence.py: classify). A page never shows one: the item table keeps the
#: reasons of the public catalog on an item that a seen flag made strict, so one of them (the reason the item was hidden or disputed for) would tell that a sighting rescued it, and a
#: page words no evidence at all. A test holds this list and the notes below to the codes the ladder's source gives, so that a new code has to be worded
#: or set aside here before a page can meet it.
EVIDENCE_CODES = frozenset(
    {
        "removed-by-patch", "removed-by-research", "seen-in-game", "community-report", "community-report-outweighed", "eql-catalog", "conflict-note", "wiki-marked-not-in-eql",
        "wiki-marked-removed", "out-of-era-tag-live-zone", "conflicting-era-tags", "zone-unreleased", "zones-unmapped", "zones-not-in-eql",
        "out-of-era", "cultural-container", "out-of-era-ingredient", "no-known-source",
    }
)  # fmt: skip
#: the notes that are about the item and not about its evidence (data/evidence.py: NOTE_CODES), the only codes a page shows, each as the seal that says where the claim comes from and a
#: sentence. The table has the code and not the sentence, so the sentence is the ladder's, made general where the ladder's names the cause
ITEM_NOTES = {
    "not-for-bis": (
        "model",
        "Kept in the catalog and not used for best-in-slot: a temporary item, one a quest takes on hand-in, one open to no class or race, or a hand weapon that cannot be scored.",
    ),
    "not-for-default-kits": ("model", "Deity-locked: left out of default kits, offered as a runner-up."),
    "wiki-marked-revamped": ("player", "The wiki page is marked as revamped: its stats or sources may have changed."),
}


@dataclass(frozen=True)
class Fact:
    label: str
    value: str


@dataclass(frozen=True)
class TierRow:
    """A row of a table of tiers: the stat (``key``: a stat of the model, ``HASTE``, a school, ``WEIGHT``, or ``DAMAGE`` and ``DELAY`` of a weapon), its label, and the figure for each tier."""

    key: str
    label: str
    cells: tuple[str, ...]


@dataclass(frozen=True)
class WeaponTable:
    skill: str | None
    two_handed: bool
    bonus: str | None
    rows: tuple[TierRow, ...]
    rule: RuleRef


@dataclass(frozen=True)
class SourceLine:
    label: str
    text: str


@dataclass(frozen=True)
class EvidenceNote:
    seal: str
    icon: str
    seal_label: str
    text: str


@dataclass(frozen=True)
class TrioLink:
    slug: str
    name: str


@dataclass(frozen=True)
class ItemPage:
    """Everything an item page says, as data the template prints."""

    key: str
    name: str
    title: str
    description: str
    facts: tuple[Fact, ...]
    tiers: tuple[str, ...]
    rows: tuple[TierRow, ...]
    rules: tuple[RuleRef, ...]
    weapon: WeaponTable | None
    sources: tuple[SourceLine, ...]
    notes: tuple[EvidenceNote, ...]
    best_for: tuple[TrioLink, ...]
    best_more: int
    wiki_title: str | None  # the credit to the wiki page the item was read from; all three are None for an item that has no wiki page (its page has no credit)
    wiki_revid: int | None
    wiki_href: str | None


def default_kit_keys(results: data.TrioResults) -> frozenset[str]:
    """The keys of the items the default answer of a trio wears: the kit of the scenario ``defaults.json`` names (the view, the best race and its best setup), the answer the page opens on."""
    defaults = results.defaults
    shard = results.shards[(defaults.evidence, defaults.buffs)]
    scenario = shard.scenario(defaults.race, defaults.role, defaults.tier, defaults.setup)
    if scenario is None:
        raise ValueError(f"{results.meta.slug}: the default view has no scenario")
    return frozenset(item.key for item in scenario.kit if item is not None)


def _stone(tenths: int) -> str:
    """A weight in tenths of a stone, as a page writes it: ``40`` is ``4.0``."""
    return f"{tenths // 10}.{tenths % 10}"


def _list_text(names: Sequence[str], more: int = 0) -> str:
    text = ", ".join(names)
    return f"{text} and {fmt_int(more)} more" if more else text


def _ordered(codes: Sequence[str], order: Sequence[str]) -> list[str]:
    """``codes`` in the order of ``order``, those it does not know last, in the order they came."""
    known = [code for code in order if code in codes]
    return known + [code for code in codes if code not in order]


def _rows(vecs: Sequence[Any]) -> tuple[TierRow, ...]:
    from trioforge.model import items as item_model

    rows = []

    def add(key: str, values: Sequence[str]) -> None:
        rows.append(TierRow(key, STAT_LABELS[key], tuple(values)))

    for key in (*item_model.STAT_KEYS, *item_model.REGEN_KEYS):
        figures = [vec.stats.get(key, 0) for vec in vecs]
        if any(figures):
            add(key, map(fmt_int, figures))
    figures = [vec.haste for vec in vecs]
    if any(figures):
        add("HASTE", map(fmt_int, figures))
    for key in item_model.SV_KEYS:
        figures = [vec.sv.get(key, 0) for vec in vecs]
        if any(figures):
            add(key, map(fmt_int, figures))
    if vecs[0].weight_known:
        add("WEIGHT", [_stone(vec.weight10) for vec in vecs])
    return tuple(rows)


def _rules_of(rows: Sequence[TierRow], book: RuleBook) -> tuple[RuleRef, ...]:
    """The rules the rows follow, each with its seal: the stat rule for the stats and the resists, the step of worn haste, the step of regeneration and the floor of the weight."""
    from trioforge.model import items as item_model

    keys = {row.key for row in rows}
    wanted = []
    if keys & {*item_model.STAT_KEYS, *item_model.SV_KEYS}:
        wanted.append("tier.stat_rule")
    if "HASTE" in keys:
        wanted.append("haste.worn_per_tier")
    if keys & set(item_model.REGEN_KEYS):
        wanted.append("regen.per_tier")
    if "WEIGHT" in keys:
        wanted.append("tier.weight_floor")
    return tuple(rule_ref(book, rule_id) for rule_id in wanted)


def _weapon(vecs: Sequence[Any], book: RuleBook) -> WeaponTable | None:
    weapon = vecs[0].weapon
    if weapon is None:
        return None
    rows = (
        TierRow("DAMAGE", STAT_LABELS["DAMAGE"], tuple(fmt_int(vec.weapon.dmg) for vec in vecs)),
        TierRow("DELAY", STAT_LABELS["DELAY"], tuple(fmt_int(vec.weapon.delay) for vec in vecs)),
    )
    bonus = None if weapon.bonus is None else fmt_int(weapon.bonus)
    return WeaponTable(weapon.skill, weapon.two_handed, bonus, rows, rule_ref(book, "tier.weapon_damage_pct"))


def _facts(record: Mapping[str, Any], original: Mapping[str, Any], vec: Any) -> tuple[Fact, ...]:
    slots = [SLOT_NAMES.get(slot, slot.title()) for slot in record["slots"]]
    classes = original["classes"]
    races = original["races"]
    if any(str(code).upper() == "ALL" for code in classes):
        class_text = "All"
    else:
        class_text = ", ".join(CLASS_NAMES.get(code, code) for code in _ordered(classes, CLASS_CODES)) or "None"
    if any(str(code).upper() == "ALL" for code in races):
        race_text = "All"
    else:
        race_text = ", ".join(sorted(races_module.RACE_NAMES.get(code, code) for code in races)) or "None"  # by name, as the race switch of a trio page lists them
    facts = [
        Fact("Slot" if len(slots) == 1 else "Slots", ", ".join(slots)),
        Fact("Classes", class_text),
        Fact("Races", race_text),
    ]
    if original["deity"]:
        facts.append(Fact("Deity", deity_text(tuple(original["deity"]))))
    if "lore" in original["flags"]:
        facts.append(Fact("Lore", LORE_TEXT))
    if original.get("item_type"):
        facts.append(Fact("Type", str(original["item_type"])))
    facts.append(Fact("Weight", f"{_stone(vec.weight10)} stone" if vec.weight_known else "not listed"))
    return tuple(facts)


def _sources(source: Mapping[str, Any] | None) -> tuple[SourceLine, ...]:
    """The lines of the sources the table holds: the zones it drops in, the quests, the zones that sell it, the recipes and the zones it is foraged in, each with the number of places
    that did not fit in the table (``more``)."""
    if not source:
        return ()
    more = source.get("more") or {}
    lines = []
    for kind, label in SOURCE_LINES:
        if kind == "crafted":
            if source.get("crafted"):
                count = source["crafted"]
                lines.append(SourceLine(label, f"{fmt_int(count)} recipe{'' if count == 1 else 's'}"))
        elif source.get(kind):
            lines.append(SourceLine(label, _list_text(source[kind], more.get(kind, 0))))
    return tuple(lines)


def _notes(key: str, codes: Sequence[str]) -> tuple[EvidenceNote, ...]:
    """The notes of an item that its page shows: those of the codes of its record that are about the item (:data:`ITEM_NOTES`), in the order of the table. A code that is a reason of
    the evidence (:data:`EVIDENCE_CODES`) is left out whatever the item's level is, and a code that is neither is a ``ValueError`` that names the item: a page says nothing that it does
    not know the meaning of, and never shows a code raw."""
    for code in codes:
        if code not in ITEM_NOTES and code not in EVIDENCE_CODES:
            raise ValueError(
                f"item {key}: the evidence code {code!r} is not one the ladder gives, so no page can say what it means "
                "(word it in view.ITEM_NOTES or list it in view.EVIDENCE_CODES)"
            )
    notes = []
    for code in codes:
        if code in ITEM_NOTES:
            seal, text = ITEM_NOTES[code]
            notes.append(EvidenceNote(seal, SEAL_ICON[seal], SEALS[seal][0], text))
    return tuple(notes)


def _description(name: str) -> str:
    rest = ": stats at every tier from +0 to +10, where it comes from, and the trios it is best for."
    room = DESCRIPTION_MAX - len(rest)
    return (name if len(name) <= room else name[: room - 1].rstrip() + "…") + rest


def has_wiki_page(record: Mapping[str, Any]) -> bool:
    """Whether the item of a record of the item table has a page on the wiki: its record has the id of that page. An item with none (its key starts with ``r``) was not read from the wiki."""
    return record.get("id") is not None


def item_page(
    record: Mapping[str, Any],
    *,
    defaults: Mapping[str, Any],
    rules: Any,
    book: RuleBook,
    wiki: tuple[str, int] | None,
    wearers: Sequence[tuple[str, str]] = (),
) -> ItemPage:
    """The page of one item, from its record in the item table of the results (``defaults`` is the table's own; ``rules`` the rules object ``at_tier`` reads, ``book`` the rules as the
    pages show them). ``wiki`` is the title and the revision of the wiki page the item was read from, ``wearers`` the ``(slug, name)`` of every trio whose default answer wears it.

    The page credits the wiki page it was read from, and an item that has no wiki page (:func:`has_wiki_page`) has none to credit: ``wiki`` is None for it, and its page has no credit. The two
    go together, and a record and a ``wiki`` that do not are a ``ValueError`` that names the item: an item from the wiki must not lose its credit, and a credit must not name a page that is not there.

    The figures of the tables are ``at_tier`` of the item at each of the tiers :data:`TIERS`, the catalog item rebuilt from the record, and nothing else. Only a strict or a wiki item has a page."""
    from trioforge.export import browser
    from trioforge.model import items as item_model

    level = record["evidence"]["level"]
    if level not in PAGE_LEVELS:
        raise ValueError(f"an item of the {level} level has no page: only a strict or a wiki item does")
    key = browser.record_key(record)
    if has_wiki_page(record) and wiki is None:
        raise ValueError(f"item {key} is from the wiki page {record['id']} and its page credits that page, but no title and revision were given")
    if not has_wiki_page(record) and wiki is not None:
        raise ValueError(f"item {key} has no wiki page, so its page has no wiki page to credit")
    original = browser.item_to_catalog(record, defaults)
    vecs = [item_model.at_tier(original, tier, rules) for tier in TIERS]
    name = record["name"]
    rows = _rows(vecs)
    ordered = sorted(wearers)
    title, revid = wiki if wiki is not None else (None, None)
    return ItemPage(
        key=key,
        name=name,
        title=f"{name}{TITLE_SUFFIX}",
        description=_description(name),
        facts=_facts(record, original, vecs[0]),
        tiers=tuple(tier_label(tier) for tier in TIERS),
        rows=rows,
        rules=_rules_of(rows, book),
        weapon=_weapon(vecs, book),
        sources=_sources(record.get("source")),
        notes=_notes(key, record["evidence"].get("codes", ())),
        best_for=tuple(TrioLink(slug, trio) for slug, trio in ordered[:BEST_FOR_MAX]),
        best_more=max(0, len(ordered) - BEST_FOR_MAX),
        wiki_title=title,
        wiki_revid=revid,
        wiki_href=None if wiki is None else wiki_url(title, revid),
    )
