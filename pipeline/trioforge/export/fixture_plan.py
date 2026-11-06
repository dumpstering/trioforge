"""The plan of the parity fixtures: which scenarios each family holds, and which of them a smaller scale keeps.

``python -m trioforge.export.fixtures`` writes the families listed in :mod:`trioforge.export.fixtures`; this module says
*what* goes into the ones that are made of scenarios (``matrix/``, ``pmb36/``, ``upgrade/`` and ``brute/``) without solving
anything, so that the coverage the plan promises can be checked in a moment and a test, the small committed sample and the
real run all draw from one list.

The plan is the same for every seed except for its filler. The **core** of the matrix (the special recipes and the lattice)
is written out here and does not depend on the seed, so the coverage below holds for every seed; the **filler** is drawn with
the seed from the whole grid of trios, races, roles, setups and tiers ("random real-trio scenarios").

The strata (:data:`REQUIRED_STRATA`): a stratum is a tag that a scenario has or has not, and each of these appears at least
twice in the matrix, in the sample and in every scale that is not a test scale:

=========================  ==========================================================================================
``iksar``                  the race is Iksar (a racial armor class on top of the capped sheet)
``deity``                  the profile has a deity, so the deity-locked items of that deity stand in the pool
``setup:2h`` ...           the weapon setup (``2h``, ``dw``, ``1h-shield``, ``stick``)
``shield``                 a real shield in the off hand: the ``1h-shield`` setup. The run checks the solved kit too
                           (``shield-worn``) and the sample keeps two of those
``buffs:own`` ...          the buff key (``own``, ``group``, ``group+enchanter``, ``raid``)
``monk-below-10``          a trio with a Monk below +10, where the worn weight moves the Monk bonus
``mixed-mana``             three mana pools that mix WIS and INT (the pool selection needs binaries)
``end-trio``               a trio with no mana pool, so END is the resource
``role:...``               the role (``balanced``, ``tank``, ``melee``, ``caster``)
``tier:0`` ...             the tier of the pool (0, 4 and 10)
``composed-weights``       weights composed from at least two of the sliders, the custom weights and the regen window
=========================  ==========================================================================================

Besides them a scenario can carry ``evidence:strict-proxy`` (the pool is the hash-picked proxy of the strict level, never
the real one), ``level:55`` and ``prune-check`` (the case also records the pruning of the whole pool).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from trioforge.model import formulas as fm
from trioforge.model import weapons
from trioforge.model.roles import roles_for
from trioforge.precompute.grid import parse_trio

__all__ = [
    "BRUTE_COUNT",
    "MINI_STRATA",
    "REQUIRED_STRATA",
    "SAMPLE_SESSIONS",
    "SCALES",
    "UPGRADE_REQUIRED",
    "BuffKeys",
    "Scale",
    "ScenarioSpec",
    "UpgradeSpec",
    "brute_plan",
    "count_tags",
    "matrix_plan",
    "pick_cover",
    "pmb36_plan",
    "scenario_tags",
    "tag_counts",
    "upgrade_plan",
    "upgrade_tags",
]

BuffKeys = ("own", "group", "group+enchanter", "raid")
BRUTE_COUNT = 330
#: the Upgrade sessions of the committed sample: one of each tier mode, and between them steps that add a new item, another
#: copy and an owned-item tier upgrade (a run checks that they do), and a session whose first step upgrades an owned copy and whose
#: second copies the upgraded item (test_a_best_set_may_upgrade_an_owned_copy...: 12 had it for the catalog of 2026-10-14, 9 has it for
#: the one of 2026-10-27; which session has it depends on the items the seed has the visitor own, so the test looks for the shape), and
#: a session in the mode "as it arrives" whose Every slot rows offer an item the visitor has, in every copy the kit wears elsewhere
#: (the page says "get another copy": 14 for the catalog of 2026-10-27; the JS tests look for the shape)
SAMPLE_SESSIONS = (2, 7, 9, 14)
#: what the sessions of a run of three or more must show between them: each kind of step, each tier mode, an owned item that
#: is locked to a deity
UPGRADE_REQUIRED = (
    "step:new", "step:copy", "step:upgrade", "deity-locked-owned", "mode:ready4", "mode:arrives", "mode:fixed",
)  # fmt: skip

REQUIRED_STRATA = (
    "iksar", "deity", "setup:2h", "setup:dw", "setup:1h-shield", "setup:stick", "shield", "buffs:own", "buffs:group",
    "buffs:group+enchanter", "buffs:raid", "monk-below-10", "mixed-mana", "end-trio", "role:balanced", "role:tank",
    "role:melee", "role:caster", "tier:0", "tier:4", "tier:10", "composed-weights",
)  # fmt: skip
#: what the small scale of the tests keeps (one of each, not two)
MINI_STRATA = ("composed-weights", "deity", "iksar", "evidence:strict-proxy", "prune-check")

# trios (normalized to the class order of the pages)
PMB = parse_trio("PAL-MNK-BER")  # a Monk, a tank and a hybrid; one mana pool
END = parse_trio("WAR-ROG-BER")  # no mana pool: END is the resource
MIX = parse_trio("CLR-PAL-SHD")  # tank, melee and caster; three mana pools that mix WIS and INT
CAST = parse_trio("CLR-DRU-WIZ")  # all casters, WIS and INT mixed
PURE = parse_trio("WIZ-MAG-ENC")  # all casters, INT only
MONKC = parse_trio("WAR-CLR-MNK")  # a Monk with a tank and a caster
HYBRID = parse_trio("RNG-BRD-BST")  # melee classes with some mana
HEAL = parse_trio("CLR-DRU-SHM")  # casters, WIS only
LATTICE_TRIOS = (PMB, END, MIX, CAST, PURE, MONKC, HYBRID, HEAL)
LATTICE_RACES = (
    "HUM", "OGR", "ERU", "TRL", "DWF", "HIE", "BAR", "HFL", "GNM", "KER", "FRG", "HEF", "DEF", "ELF", "IKS",
)  # fmt: skip
DEFAULT_LEVEL = 50


# ---- scenarios (matrix and pmb36) -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioSpec:
    """One scenario of the ``matrix/`` or ``pmb36/`` family: a profile, a tier, a pool and a weapon setup.

    ``evidence`` is ``wiki`` or ``strict-proxy``. ``multipliers`` and ``custom`` are the slider positions and the custom
    weights, ``regen_T`` the regen window in minutes: together they compose the weights
    (:func:`trioforge.model.roles.weights_override`). ``prune_check`` makes the case record the pruning of the whole
    pool, which is more to write."""

    family: str
    number: int
    trio: tuple[str, ...]
    race: str
    role: str
    setup: str
    tier: int
    buffs: str
    evidence: str = "wiki"
    level: int = DEFAULT_LEVEL
    deity: str | None = None
    multipliers: tuple[tuple[str, float], ...] = ()
    custom: tuple[tuple[str, float], ...] = ()
    regen_T: float | None = None
    prune_check: bool = False
    note: str = ""
    tags: tuple[str, ...] = field(default=(), compare=False)

    @property
    def id(self) -> str:
        return f"{self.family}-{self.number:03d}"

    @property
    def composed(self) -> bool:
        return sum((bool(self.multipliers), bool(self.custom), self.regen_T is not None)) >= 2


def scenario_tags(spec: ScenarioSpec, tables: Any) -> tuple[str, ...]:
    """The strata of a scenario (see the module docstring), sorted."""
    tags = {
        f"setup:{spec.setup}", f"buffs:{spec.buffs}", f"role:{spec.role}", f"tier:{spec.tier}", f"trio:{'-'.join(spec.trio)}",
        f"evidence:{spec.evidence}",
    }  # fmt: skip
    if spec.race == "IKS":
        tags.add("iksar")
    if spec.deity is not None:
        tags.add("deity")
    if spec.setup == "1h-shield":
        tags.add("shield")
    if "MNK" in spec.trio and spec.tier < 10:
        tags.add("monk-below-10")
    pools = fm.pools_for(spec.trio, spec.level, tables)["MANA"]
    if not pools:
        tags.add("end-trio")
    elif len(pools) == 3 and len({pool.stat for pool in pools}) > 1:
        tags.add("mixed-mana")
    if spec.composed:
        tags.add("composed-weights")
    if spec.level != DEFAULT_LEVEL:
        tags.add(f"level:{spec.level}")
    if spec.prune_check:
        tags.add("prune-check")
    return tuple(sorted(tags))


def _special(number: int, *args: Any, **kwargs: Any) -> ScenarioSpec:
    trio, race, role, setup, tier, buffs, *rest = args
    return ScenarioSpec("matrix", number, trio, race, role, setup, tier, buffs, *rest, **kwargs)


def _specials() -> list[ScenarioSpec]:
    """The recipes written out by hand: each stratum is in at least two of them (and in the lattice besides)."""
    s = _special
    return [
        s(1, PMB, "IKS", "balanced", "dw", 4, "group", note="Iksar on a Monk trio below +10"),
        s(2, END, "IKS", "melee", "2h", 10, "raid", note="Iksar, an END trio at +10, the raid buffs"),
        s(3, MIX, "IKS", "tank", "1h-shield", 0, "own", note="Iksar with a shield and three mixed mana pools"),
        s(4, MIX, "HUM", "tank", "1h-shield", 4, "group", deity="Innoruuk", note="a deity admits its locked items"),
        s(5, END, "OGR", "melee", "dw", 4, "own", "strict-proxy", deity="Rallos Zek", note="strict proxy and a deity"),
        s(6, CAST, "ERU", "balanced", "stick", 10, "group", deity="Innoruuk", note="casters, mixed mana, a deity"),
        s(7, PMB, "OGR", "melee", "2h", 0, "own", prune_check=True, note="a Monk at +0 with a two-hander"),
        s(8, PMB, "HUM", "tank", "1h-shield", 10, "raid", note="a shield at +10 under the raid buffs"),
        s(9, PURE, "ERU", "balanced", "stick", 0, "group+enchanter", note="casters with the Enchanter's haste"),
        s(10, MIX, "DWF", "caster", "stick", 4, "group+enchanter", "strict-proxy", note="the caster role, strict proxy"),
        s(11, END, "HUM", "tank", "1h-shield", 0, "own", note="an END trio tanking with a shield"),
        s(12, MONKC, "HIE", "caster", "stick", 10, "raid", prune_check=True, note="a Monk trio in the caster role"),
        s(
            13, PMB, "OGR", "balanced", "dw", 4, "raid", prune_check=True,
            multipliers=(("AC", 2), ("regen", 0.5)), custom=(("HP", 1.5),), regen_T=5,
            note="every kind of weight override at once",
        ),  # fmt: skip
        s(
            14, MIX, "HUM", "caster", "stick", 10, "own", multipliers=(("MANA", 2), ("ATK+HASTE", 0.5)),
            custom=(("SV", 2.5),), regen_T=1.5, note="sliders, a custom resist weight and a window",
        ),  # fmt: skip
        s(
            15, END, "TRL", "melee", "dw", 10, "group", "strict-proxy", multipliers=(("SV", 2),), custom=(("ATK", 3),),
            regen_T=7.5, note="a custom ATK under a slider and a long window",
        ),  # fmt: skip
        s(16, MONKC, "OGR", "tank", "1h-shield", 4, "group", note="a Monk with a shield below +10"),
        s(17, PMB, "OGR", "balanced", "dw", 4, "group", level=55, prune_check=True, note="level 55"),
        s(18, END, "HUM", "melee", "2h", 10, "own", level=55, note="level 55, no mana"),
        s(
            19, PMB, "IKS", "tank", "2h", 0, "group+enchanter", multipliers=(("ATK+HASTE", 2),), regen_T=0,
            note="Iksar Monk with composed weights and a zero window",
        ),  # fmt: skip
        s(20, HYBRID, "ERU", "balanced", "dw", 4, "raid", deity="Karana", prune_check=True, note="a hybrid trio and a deity"),
    ]


def matrix_plan(seed: int, tables: Any, *, filler: int = 28, lattice: int = 48) -> list[ScenarioSpec]:
    """Every scenario of the ``matrix/`` family in the order of the files: the special recipes, the lattice and the
    seeded filler. The special recipes and the lattice do not depend on the seed."""
    specs = _specials()
    number = len(specs)
    for i in range(lattice):  # a lattice over the trios, roles, setups, tiers and buff keys that rotates all of them
        trio = LATTICE_TRIOS[i % len(LATTICE_TRIOS)]
        roles = roles_for(trio)
        role = roles[(i // len(LATTICE_TRIOS)) % len(roles)]
        setups = weapons.setups_for(trio, role, tables, level=DEFAULT_LEVEL)
        number += 1
        specs.append(
            ScenarioSpec(
                "matrix", number, trio, LATTICE_RACES[(i * 4 + 1) % len(LATTICE_RACES)], role,
                setups[(i // 3) % len(setups)], (0, 4, 10)[(2 * i + i // 8) % 3], BuffKeys[(i + i // 4) % 4],
                "strict-proxy" if i % 7 == 3 else "wiki", prune_check=i % 3 == 0, note="lattice",
            )
        )
    rng = random.Random(f"{seed}:matrix")
    trios = [parse_trio(trio) for trio in _all_trios()]
    for _ in range(filler):
        trio = rng.choice(trios)
        role = rng.choice(roles_for(trio))
        number += 1
        composed = rng.random() < 0.2
        specs.append(
            ScenarioSpec(
                "matrix", number, trio, rng.choice(LATTICE_RACES), role,
                rng.choice(weapons.setups_for(trio, role, tables, level=DEFAULT_LEVEL)), rng.choice((0, 4, 10)),
                rng.choice(BuffKeys), "strict-proxy" if rng.random() < 0.25 else "wiki",
                multipliers=(("AC", rng.choice((0.5, 2))), ("regen", rng.choice((0.5, 2)))) if composed else (),
                custom=(("HP", rng.choice((0.75, 2, 3.25))),) if composed else (),
                regen_T=rng.choice((1, 3, 6, 12.5)) if composed else None, note="random",
            )
        )
    return [_tagged(spec, tables) for spec in specs]


def _all_trios() -> list[tuple[str, ...]]:
    from itertools import combinations

    from trioforge.classes import CLASS_CODES

    return list(combinations(CLASS_CODES, 3))


def _tagged(spec: ScenarioSpec, tables: Any) -> ScenarioSpec:
    return ScenarioSpec(**{**spec.__dict__, "tags": scenario_tags(spec, tables)})


def pmb36_plan(tables: Any) -> list[ScenarioSpec]:
    """The neutral PAL/MNK/BER 36: three roles x tiers 0, 4 and 10 x own and group buffs x the wiki pool and its strict
    proxy, all for an Ogre. The setups go round the ones each role plays, so every role-and-setup pair is in the 36."""
    specs = []
    for role in ("balanced", "tank", "melee"):
        setups = weapons.setups_for(PMB, role, tables, level=DEFAULT_LEVEL)
        for k, (tier, buffs, evidence) in enumerate(
            (t, b, e) for t in (0, 4, 10) for b in ("own", "group") for e in ("wiki", "strict-proxy")
        ):
            number = len(specs) + 1
            specs.append(
                ScenarioSpec(
                    "pmb36", number, PMB, "OGR", role, setups[(k + k // 4) % len(setups)], tier, buffs, evidence,
                    prune_check=number % 6 == 1, note="the neutral 36",
                )
            )
    return [_tagged(spec, tables) for spec in specs]


# ---- upgrade sessions -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UpgradeSpec:
    """One session of the ``upgrade/`` family: an owned set, the candidates a tier mode gives, and the path of three steps.

    ``owned`` is how many catalog items are owned (at mixed tiers, a few twice); ``locked`` how many deity-locked items are
    owned besides them; with a ``deity`` the profile admits the items of that deity. ``focus`` is ``all`` (every item of the
    pool is a candidate) or ``owned`` (only the items the visitor owns are: the steps are then copies and owned-item tier
    upgrades, which a pool of every item would rarely choose)."""

    number: int
    trio: tuple[str, ...]
    race: str
    role: str
    setup: str
    buffs: str
    evidence: str
    mode: str
    D: int
    N: int | None
    owned: int
    locked: int = 0
    deity: str | None = None
    focus: str = "all"
    steps: int = 3
    note: str = ""
    tags: tuple[str, ...] = field(default=(), compare=False)

    @property
    def id(self) -> str:
        return f"upgrade-{self.number:03d}"


def upgrade_tags(spec: UpgradeSpec) -> tuple[str, ...]:
    tags = {
        f"mode:{spec.mode}", f"setup:{spec.setup}", f"buffs:{spec.buffs}", f"role:{spec.role}", f"evidence:{spec.evidence}",
        f"focus:{spec.focus}",
    }  # fmt: skip
    if spec.locked:
        tags.add("deity-locked-owned")
    if spec.deity is not None:
        tags.add("deity")
    return tuple(sorted(tags))


def upgrade_plan(seed: int) -> list[UpgradeSpec]:
    """The sessions of the ``upgrade/`` family: three tier modes, five trios, owned sets of 24 to 70 items, deity-locked
    owned items with and without the deity, and both evidence levels. The seed only changes which items are owned."""
    rows = [
        # trio, race, role, setup, buffs, evidence, mode, D, N, owned, locked, deity, focus
        (PMB, "OGR", "balanced", "dw", "group", "wiki", "ready4", 4, None, 60, 1, None, "all"),
        (PMB, "HUM", "tank", "1h-shield", "own", "wiki", "arrives", 3, None, 40, 2, "Karana", "owned"),
        (END, "IKS", "melee", "2h", "group", "strict-proxy", "fixed", 4, 6, 48, 1, None, "all"),
        (MIX, "DWF", "caster", "stick", "own", "wiki", "ready4", 4, None, 36, 0, None, "all"),
        (PURE, "ERU", "balanced", "stick", "group", "wiki", "arrives", 0, None, 24, 1, None, "all"),
        (MONKC, "OGR", "tank", "dw", "group+enchanter", "wiki", "fixed", 4, 10, 56, 2, "Brell Serilis", "all"),
        (HYBRID, "HUM", "balanced", "dw", "own", "strict-proxy", "ready4", 4, None, 44, 0, None, "owned"),
        (PMB, "OGR", "melee", "2h", "raid", "wiki", "arrives", 4, None, 70, 1, None, "all"),
        (END, "TRL", "tank", "1h-shield", "own", "wiki", "fixed", 4, 2, 32, 1, "Rallos Zek", "owned"),
        (CAST, "HIE", "balanced", "stick", "group", "strict-proxy", "arrives", 2, None, 30, 0, None, "all"),
        (MIX, "HUM", "tank", "1h-shield", "group", "wiki", "ready4", 4, None, 64, 2, "Innoruuk", "all"),
        (PMB, "IKS", "balanced", "dw", "own", "wiki", "fixed", 4, 10, 52, 1, None, "owned"),
        (HEAL, "BAR", "balanced", "stick", "raid", "wiki", "ready4", 4, None, 28, 1, None, "all"),
        (MONKC, "HUM", "melee", "2h", "own", "strict-proxy", "arrives", 4, None, 46, 0, None, "all"),
        (HYBRID, "OGR", "balanced", "dw", "group+enchanter", "wiki", "fixed", 4, 8, 38, 1, "Karana", "owned"),
        (PURE, "HUM", "balanced", "stick", "own", "wiki", "ready4", 4, None, 20, 0, None, "all"),
    ]
    del seed  # the plan is fixed; the seed picks the owned items when the session is made
    specs = [UpgradeSpec(n, *row, note="session") for n, row in enumerate(rows, start=1)]
    return [UpgradeSpec(**{**spec.__dict__, "tags": upgrade_tags(spec)}) for spec in specs]


def brute_plan(count: int = BRUTE_COUNT) -> list[int]:
    """The numbers of the brute-force instances; the instance of a number is drawn from the seed and the number."""
    return list(range(count))


# ---- choosing a part of a plan -----------------------------------------------------------------------------------------


def count_tags(tag_lists: Any) -> dict[str, int]:
    """How many of some lists of tags carry each tag, sorted by tag."""
    counts: dict[str, int] = {}
    for tags in tag_lists:
        for tag in set(tags):
            counts[tag] = counts.get(tag, 0) + 1
    return dict(sorted(counts.items()))


def tag_counts(specs: Any) -> dict[str, int]:
    """How many of ``specs`` (anything with ``tags``) carry each tag."""
    return count_tags(spec.tags for spec in specs)


def pick_cover(specs: list[Any], wanted: tuple[str, ...], copies: int) -> list[Any]:
    """The fewest specs, in plan order, that carry every tag of ``wanted`` at least ``copies`` times (a greedy cover: the next
    spec is the one that serves the most tags still short, the earliest on a tie). Raises ``ValueError`` if the plan has too
    few."""
    short = {tag: copies for tag in wanted}
    chosen: list[Any] = []
    while any(short.values()):
        best = max(
            (spec for spec in specs if spec not in chosen),
            key=lambda spec: (sum(1 for tag in spec.tags if short.get(tag, 0) > 0), -specs.index(spec)),
            default=None,
        )
        if best is None or not any(short.get(tag, 0) > 0 for tag in best.tags):
            lacking = ", ".join(tag for tag, left in short.items() if left > 0)
            raise ValueError(f"the plan has too few scenarios with: {lacking}")
        chosen.append(best)
        for tag in best.tags:
            if short.get(tag, 0) > 0:
                short[tag] -= 1
    return sorted(chosen, key=specs.index)


# ---- scales -----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scale:
    """How much of each family a run writes. ``full`` is the real set; ``mini`` and ``tiny`` are for tests (a few of each, and
    hardly any); ``sample`` is what is committed.

    A count of None means everything the plan has. ``matrix`` and ``pmb36`` may also be a number of scenarios chosen to
    cover the strata (``cover``: the tags and the copies of each)."""

    name: str
    brute: int
    cover: tuple[tuple[str, ...], int] | None
    pmb36: int | None
    upgrade: int | None
    evaluate: int
    profile_trios: int
    profile_races: int | None
    weights: int
    items: int | None
    compress: bool


SCALES = {
    "full": Scale("full", BRUTE_COUNT, None, None, None, 5000, 5, None, 500, None, True),
    "mini": Scale("mini", 6, (MINI_STRATA, 1), 1, 1, 30, 1, 2, 10, 16, True),
    "tiny": Scale("tiny", 2, (("composed-weights",), 1), 0, 0, 10, 1, 2, 5, 6, True),
    "sample": Scale(
        "sample", 40, (REQUIRED_STRATA + ("evidence:strict-proxy", "level:55", "prune-check"), 2), 6, len(SAMPLE_SESSIONS), 150, 1, None, 60, 150,
        False,
    ),
}
