"""Shared machinery for the Upgrade tests: the exact maximum of a pool under owned counts, and random ownership cases.

The owned-item options of the builder (``owned_caps``, ``new_keys``, ``max_new``, ``upgrades``; see
``trioforge.solver.model``) are checked against a brute force that shares nothing with the builder. It lists every legal
kit of a small pool with the machinery of ``solver_helpers`` (the independent enumerator and the exact oracle) and keeps
a kit only when :func:`allowed` says its wear counts fit the options, a definition written out here again:

* an **item** is named by its ident ``key@tier``;
* an owned item (``caps``) is worn at most its count over every group it stands in, **together with one copy for each
  item that is an upgrade of it and is worn** (the first copy of an upgrade is made from one of the source's copies: the copy
  stands in one place, at one tier; every further wear of the upgrade is a copy of the upgrade and costs one acquisition);
* an item in ``news`` that is not owned, and every upgrade, is a **new** wear: each wear costs one of ``max_new``;
* an owned item that is also in ``news`` (a duplicate) may be worn more often than it is owned: each wear above its count
  (the count shared with its upgrades) costs one of ``max_new``; a Lore duplicate adds nothing and costs nothing.

Every name here is invented.
"""

from __future__ import annotations

import dataclasses
import random
from collections import Counter
from fractions import Fraction

import numpy as np

import solver_helpers as H
from trioforge.model import formulas as fm
from trioforge.model.formulas import evaluate
from trioforge.solver._highs import solve_milp
from trioforge.solver.model import BuildOptions, build_milp

REL = 1e-9
#: the groups of two places: an item that fits one can be worn twice (``ownership_case(repeats=True)`` offers the twin of such an item)
WIDE_SLOTS = frozenset({"EAR", "FINGER", "WRIST"})


def ident(item):
    """The ident ``key@tier`` of an item, as the builder's options name it (written out again here)."""
    return f"{item.key}@{item.tier}"


def wears_of(groups):
    """``Counter`` of idents worn, over every group of ``{group: [items]}``."""
    return Counter(ident(item) for placed in groups.values() for item in placed)


def allowed(groups, items_by_ident, caps, news, ups, max_new):
    """Whether the wear counts of ``{group: [items]}`` fit the owned-item options (the definition in the module doc)."""
    wears = wears_of(groups)
    lore = Counter(i.key for placed in groups.values() for i in placed if i.lore)
    if any(count > 1 for count in lore.values()):  # a Lore key is worn once over every group and every tier of it
        return False
    spent = 0
    for source, cap in caps.items():
        if source in news and cap == 0:  # listed as owned with none, and a candidate: a plain new item (below)
            continue
        item = items_by_ident.get(source)
        shared = wears[source] + sum(min(wears[target], 1) for target, origin in ups.items() if origin == source)
        duplicate = source in news and item is not None and not item.lore
        if duplicate:
            spent += max(0, shared - cap)
        elif shared > cap:
            return False
    for name in set(news) - set(ups):
        if name not in caps or caps[name] == 0:  # not owned: every wear is a new one
            spent += wears[name]
    spent += sum(wears[target] for target in ups)  # every wear of an upgrade's target (the first made from a copy of the source) is one acquisition
    return max_new is None or spent <= max_new


class OwnedSpace(H.Space):
    """The space of legal kits of an instance, cut down to the kits whose wear counts fit the owned-item options."""

    def __init__(self, inst, caps, news, ups, max_new):
        self._by_ident = {ident(item): item for item in inst.items}
        self._rule = (dict(caps), set(news), dict(ups), max_new)
        super().__init__(inst)

    def _enumerate(self):
        kits = super()._enumerate()
        caps, news, ups, max_new = self._rule
        keep = [row for row in kits if allowed(self.groups_of(tuple(int(n) for n in row)), self._by_ident, caps, news, ups, max_new)]
        return np.array(keep, dtype=np.int64).reshape(len(keep), len(self.group_names))


def best_under(inst, caps=None, news=(), ups=None, max_new=None):
    """The exact maximum F (a ``Fraction``) of the instance under the owned-item options, by brute force."""
    return OwnedSpace(inst, caps or {}, news, ups or {}, max_new).best()[0]


def options_of(inst, caps=None, news=(), ups=None, max_new=None, **changes):
    return BuildOptions(
        any_rule=inst.any_rule, haste_assumed=inst.haste_assumed, owned_caps=caps or None, new_keys=frozenset(news),
        max_new=max_new, upgrades=ups or None, **changes,
    )


def check_owned(inst, caps=None, news=(), ups=None, max_new=None, rel=REL):
    """Solve the instance with the builder under the options and compare with the brute force; ``(ok, message)``.

    Also checks that the kit the MILP returns is legal, fits the options and is worth what the model says."""
    caps, news, ups = caps or {}, set(news), ups or {}
    best = best_under(inst, caps, news, ups, max_new)
    milp = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, options_of(inst, caps, news, ups, max_new))
    res = solve_milp(milp)
    if res.status != "optimal":
        return False, f"status {res.status}"
    decoded = milp.decode(res.x)
    if not H.legal(decoded.groups, inst.setup):
        return False, "the MILP's kit is not legal"
    by_ident = {ident(item): item for item in inst.items}
    if not allowed(decoded.groups, by_ident, caps, news, ups, max_new):
        return False, f"the MILP's kit breaks the owned-item options: {dict(wears_of(decoded.groups))}"
    exact = evaluate(
        inst.profile, H.kit_from_groups(decoded.groups), H.eval_totals(inst.buffset, decoded.buffs) if inst.buffset else None,
        setup=inst.setup, haste_assumed=inst.haste_assumed,
    ).F
    scale = float(max(Fraction(1), abs(best)))
    if abs(float(exact - best)) / scale > rel:
        return False, f"kit F {float(exact)!r} against the brute force {float(best)!r}"
    if abs(milp.const + res.objective - float(exact)) / scale > rel:
        return False, f"model objective {milp.const + res.objective!r} against the kit's F {float(exact)!r}"
    return True, ""


# ---- random ownership cases ---------------------------------------------------------------------------------------------


def _shrink(rng, inst, keep):
    """Drop random items (never one of ``keep``) until the instance has few enough kits for a brute force."""
    while H.option_product(inst.items, inst.setup, inst.any_rule) > H.KIT_LIMIT and len(inst.items) > 2:
        counts = {
            g: len(H.group_options(H.candidates(inst.items, g, inst.setup, inst.any_rule), size)) for g, size in H.SLOT_GROUPS
        }
        worst = max(counts, key=lambda g: counts[g])
        victims = [i for i in inst.items if H.fits(i, worst, inst.setup, inst.any_rule) and ident(i) not in keep]
        if not victims:
            victims = [i for i in inst.items if H.fits(i, worst, inst.setup, inst.any_rule)]
        gone = rng.choice(victims)
        inst.items = [i for i in inst.items if i is not gone]


def ownership_case(seed, *, upgrades=True, trio_index=None, pool="small", chains=False, repeats=False):
    """``(instance, caps, news, ups, max_new)``: a random pool with owned counts, candidates, duplicates (owned and
    candidate at once) and upgrades (a twin of an owned item at a higher tier, listed in ``ups``).

    ``pool="small"`` is short enough to list every kit (the brute force); ``"prunable"`` is the pool of the pruning tests
    (twins, better and worse variants, items of other classes and deities), too long for a brute force and made to lose
    items to the pruning. Tiers are labels here: an upgrade twin has better numbers than its source, as a higher tier
    would give.

    ``repeats=True`` makes the cases bind on the copies of an upgrade's source and leaves room to wear the target more than
    once: at least one twin, of an item of a group of two places, whose source is owned once or twice, and a limit on new
    items of none, 2 or 3 (the cases without it are the cases they were). A pool with no item of a group of two places
    (``WIDE_SLOTS``) falls back to twins of any item, which cannot be worn twice: the tests count those cases."""
    rng = random.Random(seed)
    if pool == "small":
        inst = H.random_instance(rng, trio_index=seed % len(H.TRIO_MENU) if trio_index is None else trio_index)
    else:
        import test_prune as TP

        inst = TP.case(seed, trio_index=trio_index)
    rng = random.Random(seed + 91)
    items = [dataclasses.replace(item, tier=rng.randint(0, 4)) for item in inst.items]
    twins, owned_twins, parents = [], set(), set()
    if upgrades:
        wide = [i for i in items if i.slots & WIDE_SLOTS] if repeats else []
        offered = wide or items
        for item in rng.sample(offered, min(len(offered), rng.randint(1 if repeats else 0, 2 if pool == "small" else 4))):
            parents.add(ident(item))
            if not chains:
                stats = {k: v + abs(v) // 4 + 1 for k, v in item.stats.items()}
                twins.append(dataclasses.replace(item, tier=item.tier + rng.randint(1, 3), stats=stats))
                continue
            tier, stats, chain = item.tier, dict(item.stats), []
            for _ in range(rng.choice((1, 2, 2))):
                tier += rng.randint(1, 2)
                stats = {k: v + abs(v) // 4 + 1 for k, v in stats.items()}
                chain.append(dataclasses.replace(item, tier=tier, stats=stats))
            twins += chain
            kept_low = [t for t in chain[:-1] if rng.random() < 0.7]  # the top of a chain is never owned
            owned_twins |= {ident(t) for t in kept_low}
            if kept_low:
                owned_twins.add(ident(item))  # the visitor owns the first of the key too: two tiers of one key
    inst.items = sorted([*items, *twins], key=lambda i: (i.key, i.tier))
    twin_idents = {ident(t) for t in twins}
    owned = [
        i for i in inst.items
        if ident(i) in owned_twins or (repeats and ident(i) in parents) or (ident(i) not in twin_idents and rng.random() < 0.55)
    ]
    caps = {ident(i): rng.choice((0, 1, 1, 1, 2, 2, 3)) for i in owned}
    if repeats:
        caps.update({name: rng.choice((1, 1, 2)) for name in sorted(parents) if name in caps})
    owned_idents = set(caps)
    news = {ident(i) for i in inst.items if ident(i) not in owned_idents and ident(i) not in twin_idents and rng.random() < 0.4}
    news |= {name for name in sorted(owned_idents) if rng.random() < 0.25}  # duplicates: owned and a candidate at once
    ups = {}
    for twin in twins:
        if ident(twin) in owned_idents:
            continue
        sources = [i for i in owned if i.key == twin.key and i.tier < twin.tier and caps[ident(i)] >= 1]
        if sources and rng.random() < 0.8:
            ups[ident(twin)] = ident(max(sources, key=lambda i: i.tier))
    news |= {t for t in sorted(twin_idents) if t not in ups and t not in owned_idents and rng.random() < 0.5}  # another new item
    max_new = rng.choice((None, 2, 2, 3) if repeats else (None, 0, 1, 1, 1, 2, 3))
    if pool == "small":
        _shrink(rng, inst, keep=set(caps) | set(news) | set(ups))
    present = {ident(i) for i in inst.items}
    caps = {k: v for k, v in caps.items() if k in present}
    news = {k for k in news if k in present}
    ups = {t: s for t, s in ups.items() if t in present and s in present}
    return inst, caps, news, ups, max_new


def restrict(items, caps, news, ups):
    """The owned-item options narrowed to the idents of ``items`` (a pruned pool has lost new items and upgrade targets)."""
    present = {ident(i) for i in items}
    return (
        {k: v for k, v in caps.items() if k in present}, {k for k in news if k in present},
        {t: s for t, s in ups.items() if t in present and s in present},
    )


# ---- single additions to an owned set (the farm path and the best sets), written out again ---------------------------------


def split_ident(name):
    key, _, tier = name.rpartition("@")
    return key, int(tier)


def single_additions(counts, candidates):
    """Every way to add **one** candidate to the owned counts ``{ident: count}``: ``(candidate, kind, source tier, counts
    after)``, by the rules of the plan.

    A candidate that is owned at its tier is another copy (a Lore item adds nothing and is no addition); a candidate whose
    key is owned at lower tiers is an upgrade of one copy of the highest of them (that copy becomes the candidate); any
    other candidate is a new copy at its tier."""
    tiers = {}
    for name in counts:
        key, tier = split_ident(name)
        tiers.setdefault(key, []).append(tier)
    out = []
    for cand in candidates:
        name = ident(cand)
        if name in counts:
            if not cand.lore:
                out.append((cand, "copy", None, {**counts, name: counts[name] + 1}))
            continue
        lower = [t for t in tiers.get(cand.key, ()) if t < cand.tier]
        if lower:
            source = f"{cand.key}@{max(lower)}"
            after = {**counts, source: counts[source] - 1}
            after = {k: v for k, v in after.items() if v > 0}
            out.append((cand, "upgrade", max(lower), {**after, name: 1}))
        else:
            out.append((cand, "new", None, {**counts, name: 1}))
    return out


def best_under_counts(inst, counts):
    """The exact maximum F of the instance when every item is worn at most ``counts[ident]`` times (0 when it is not
    listed), by brute force."""
    caps = {ident(item): counts.get(ident(item), 0) for item in inst.items}
    return best_under(inst, caps)


def farm_case(seed, **kwargs):
    """``(instance, owned, candidates)`` from a random ownership case: ``owned`` is ``{item: count}`` of the owned items,
    ``candidates`` the items offered (new items, duplicates of owned ones and the twins that upgrade them)."""
    inst, caps, news, ups, _ = ownership_case(seed, **kwargs)
    owned = {item: caps[ident(item)] for item in inst.items if caps.get(ident(item), 0) >= 1}
    candidates = [item for item in inst.items if ident(item) in news or ident(item) in ups]
    return inst, owned, candidates


# ---- the real catalog ---------------------------------------------------------------------------------------------------------

REAL_TRIO = ("PAL", "MNK", "BER")


def real_session(owned_count=60, seed=7):
    """The PAL/MNK/BER Ogre profile at the wiki evidence level, ``owned_count`` real wiki items owned at mixed tiers (a few
    in duplicate) and every wiki item as a candidate at +4 (the Ready +4 mode)."""
    import json

    from trioforge import upgrade
    from trioforge.model.buffs import group_preset, own_buffs, resolve
    from trioforge.model.items import at_tier
    from trioforge.model.profile import make_profile
    from trioforge.model.tables import REPO
    from trioforge.precompute import grid

    tables, rules = H.TABLES, H.TABLES.rules
    spells = json.loads((REPO / "derived" / "client" / "spells-l50.json").read_text(encoding="utf-8"))
    buffset = resolve([*own_buffs(REAL_TRIO, 50, spells, rules), *group_preset(spells)], rules)
    profile = make_profile("OGR", REAL_TRIO, 50, "tank", buffset, None, tables, evidence="wiki")
    pool = grid.pool_dicts(grid.select_items(H.catalog_items(), REAL_TRIO), "wiki")
    rng = random.Random(seed)
    owned = {at_tier(r, rng.choice((0, 0, 0, 2, 4, 4, 6)), rules): rng.choice((1, 1, 1, 2)) for r in rng.sample(pool, owned_count)}
    return profile, buffset, owned, upgrade.scored_candidates(pool, "ready4", rules), rules
