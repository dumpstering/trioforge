"""K9, the named cases: kits that the public feedback of 2026-11-18 asked about, printed whole, so that a reader can paste one into a discussion.

For each case and each of its roles, the kit at +4 and at +10 (the view that :mod:`trioforge.checks.results` describes) is listed place by place with the stats of each item
at that tier, then the result of every check for it and its exchange rates (K10, :mod:`trioforge.checks.exchange`): what one more point of each stat is worth to the objective
of that kit. No player is named: a case is a trio and, for one of them, a role.

A kit whose shard value the evaluator does not give stops the run (:class:`trioforge.checks.results.ResultsError`): no rate is made of results that the evaluator did not make.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from trioforge.checks import kits as kits_module
from trioforge.checks.exchange import ExchangeRates
from trioforge.checks.families import ARMOUR_SLOTS
from trioforge.checks.results import PLACE_NAMES, Kit, Results
from trioforge.model.roles import ROLES

__all__ = ["CASES", "NA_REASON", "TIERS", "named_cases", "render_cases", "render_na"]

#: (label, trio, the roles to print or None for every role the trio has)
CASES: tuple[tuple[str, tuple[str, ...], tuple[str, ...] | None], ...] = (
    ("SHD/WIZ/ENC", ("SHD", "WIZ", "ENC"), None),
    ("WAR/SHM/ENC", ("WAR", "SHM", "ENC"), None),
    ("PAL/MNK/ENC tank", ("PAL", "MNK", "ENC"), ("tank",)),
    ("RNG/SHM/CLR", ("RNG", "SHM", "CLR"), None),
    ("a Ranger and two melee: WAR/RNG/ROG", ("WAR", "RNG", "ROG"), None),
)
TIERS = (4, 10)
NA_REASON = "results made with other rules"  # why K9 and K10 are not applicable for a folder whose rules version is not the checkout's
CHECK_LINES = ("K1.attr", "K1.pool", "K2", "K3", "K3.robe", "K3.robe_worn", "K5.bow", "K5.windstriker", "K6", "K7", "K8", "K11", "K12")


def _stats(vec: Any) -> str:
    parts = [f"{stat} {vec.stats[stat]}" for stat in kits_module.POINT_STATS if vec.stats.get(stat)]
    return " ".join(parts + ([f"HASTE {vec.haste}"] if vec.haste else []))


def _entry(label: str, kit: Kit, context: kits_module.Context, exchange: ExchangeRates) -> dict[str, Any]:
    outcomes = context.evaluate(kit)
    sets = kits_module.set_pieces(kit, context.stems)  # (distinct items, as the scoreboard counts them)
    worn = dict(zip(PLACE_NAMES, kit.places, strict=True))
    rates = exchange.rates(kit)
    return {
        "case": label, "trio": kit.slug, "role": kit.role, "tier": kit.tier, "race": kit.race, "setup": kit.setup, "value": kit.value,
        "kit": [
            {"place": place, "item": None if key is None else context.name(key), "stats": "" if key is None else _stats(context.table.vec(key, kit.tier))}
            for place, key in worn.items()
        ],
        "checks": {
            check_id: {"status": outcome.status, "value": kits_module._round(outcome.value), "detail": dict(outcome.detail)}
            for check_id, outcome in outcomes.items()
        },
        "K4": {stem: len(keys) for stem, keys in sorted(sets.items()) if len(keys) >= 2},
        "K10": {
            "value": round(rates["value"], 2),
            "rates": {term: round(rate, 4) for term, rate in rates["rates"].items()},
            "vs_sta": {term: None if rate is None else round(rate, 3) for term, rate in rates["vs_sta"].items()},
        },
    }  # fmt: skip


def named_cases(results: Results, context: kits_module.Context) -> list[dict[str, Any]]:
    """The kits of the named cases at +4 and +10, with the result of every check and the exchange rates; a case whose trio the folder lacks has none."""
    exchange = ExchangeRates(context)
    found = []
    for label, trio, roles in CASES:
        for kit in results.kits(trio):
            if kit.tier in TIERS and kit.role in ROLES and (roles is None or kit.role in roles):  # (a kit of the earlier Balanced build has no weights to value it by)
                found.append(_entry(label, kit, context, exchange))
    return sorted(found, key=lambda e: ([c[0] for c in CASES].index(e["case"]), e["trio"], e["tier"], e["role"]))


def _line(check_id: str, entry: Mapping[str, Any]) -> str:
    result = entry["checks"][check_id]
    status, value, detail = result["status"], result["value"], result["detail"]
    if status == "na":
        return f"   {check_id:<15}n.a."
    shown = "" if value is None else f" {value}"
    if check_id == "K1.attr":
        shown += f"  (WIS and INT {detail['wis_int']} of {detail['attributes']} attribute points)"
    if check_id == "K1.pool":
        shown += f"  (mana-pool points {detail['pool']} of {detail['points']} stat points that count)"
    if check_id == "K2" and detail["items"]:
        shown += ": " + "; ".join(detail["items"])
    if check_id == "K3":
        slots = " ".join(f"{slot} {entry['checks'][f'K3.{slot}']['value']}" for slot in ARMOUR_SLOTS if entry["checks"][f"K3.{slot}"]["status"] != "na")
        shown += f"  (share of the best AC: {slots})"
    if check_id == "K3.robe" and detail["chest"]:
        shown = f": {detail['chest']}"
    if check_id.startswith("K5"):
        shown = f": {detail['range'] or 'nothing'}"
    if check_id == "K6":
        shown += f"  (strength {detail['gear']} of {detail['best']} reachable, the naked character's {detail['naked']} on top)"
    if check_id == "K8":
        shown += f"  (sheet AC {detail['ac']}, soft cap {detail['softcap']})"
    if check_id == "K11":
        shown += f"  (stamina {detail['sta']}: race and class {detail['naked']}, buffs {detail['buff']}, gear {detail['gear']}; the knee is {detail['knee']})"
    return f"   {check_id:<15}{status}{shown}"


def render_na() -> str:
    """The text of K9 and K10 for results made with other rules: the headings, and that they are not applicable."""
    lines = ["K9  Named cases (public feedback, 2026-11-18)", "K10  Exchange rates   [scoreboard only]", f"    n.a.: {NA_REASON}", ""]
    return "\n".join(lines)


def render_cases(entries: Sequence[Mapping[str, Any]]) -> str:
    """The text of the named cases."""
    lines = [
        "K9  Named cases (public feedback, 2026-11-18)",
        "K10  Exchange rates   [scoreboard only]",
        "    the change of the objective for one more point on a worn item, in HP-equivalents, by the evaluator of the model, for each named kit",
        "",
    ]
    if not entries:
        lines.append("    no kit of the named trios in this folder")
    for entry in entries:
        lines.append(f"== {entry['case']}  {entry['role']}  +{entry['tier']}   (race {entry['race']}, setup {entry['setup']}, value {entry['value']})")
        for row in entry["kit"]:
            lines.append(f"   {row['place']:<10}{row['item'] or '-':<42}{row['stats']}")
        for check_id in CHECK_LINES:
            lines.append(_line(check_id, entry))
        sets = ", ".join(f"{stem} x{count}" for stem, count in entry["K4"].items()) or "none"
        lines.append(f"   {'K4':<15}sets with two pieces or more: {sets}")
        rates = entry["K10"]
        lines.append(f"   {'K10':<15}+1 of " + ", ".join(f"{term} {rate:.3f}" for term, rate in rates["rates"].items()))
        lines.append(f"   {'':<15}in points of STA: " + ", ".join(f"{term} {'-' if rate is None else f'{rate:.2f}'}" for term, rate in rates["vs_sta"].items()))
        lines.append("")
    return "\n".join(lines)
