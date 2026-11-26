"""The optional file of expected items: cases for the kits to agree with (``--expected cases.json``).

The file is one JSON list of cases and is never part of the repository. A case is an object::

    {"trio": ["PAL", "MNK", "ENC"], "role": "tank", "slot": "CHEST", "any_of": ["Item Name", ...]}

* ``trio``: three class codes (a list, or ``"pal-mnk-enc"``), in any order.
* ``role``: a build of the trio (``tank``, ``shield``, ``melee``, ``ranged``, ``castertank`` or ``caster``), or ``"any"``, which looks at the kit of every build the trio has at that tier and
  says which builds satisfy the case and which do not. A case for ``balanced`` (the build of an earlier release, which no longer exists) or for a build the trio is not offered is ``na``, never
  ``agree`` or ``disagree``. With
  ``any_of`` the case holds when **at least one** role's kit satisfies it; with ``none_of`` only when **every** role's kit does (the item is wanted in no role).
* ``slot``: a place (``HEAD``, ``CHEST``, ``EAR1``, ``FINGER2``, ``ANY1``, ``PRIMARY`` ...), a pair of places (``EAR``, ``WRIST``, ``FINGER``: either place) or ``"any"``:
  anywhere in the kit (a legal kit wears an item only in an Any place or in a place its slots list, so this is the same as either of the two).
* ``any_of``: the case holds when the kit's item in the slot is one of these names. ``none_of`` replaces it: the case holds when the item is none of them (an empty slot
  holds nothing, so it holds none of them, and satisfies ``none_of``). A case has one of the two.
* ``tier``: the tier of the kit (default 4, the tier of the page's default view).
* ``race``: a race code; only that race's kits are looked at (default: the trio's default race).
* Any other key (``mentions``, ``note``, ``source`` ...) is ignored.

Names are compared in any case and without punctuation or apostrophes (:func:`trioforge.checks.results.norm_name`). A name that no item of the table carries is reported
as unknown in the case; it is never an error, and it can match nothing. **A case whose names are all unknown is ``invalid``**, not judged: a misspelt ``none_of`` would agree with
every kit and a misspelt ``any_of`` would disagree with every one. The summary counts the distinct unknown names. A case that cannot be read (no trio, an unknown slot, no
names) is reported as ``invalid`` and the rest are still checked. A case is ``agree`` or ``disagree``, or ``na`` when the results have no such kit (no such trio, role, tier or
race). The agreement share is ``agree / (agree + disagree)``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from trioforge.checks.results import PLACE_NAMES, Kit, Results, norm_name, parse_trio
from trioforge.model.roles import REMOVED_ROLES, ROLES, roles_for

__all__ = ["DEFAULT_TIER", "ExpectedError", "check_case", "check_expected", "load_cases", "render_report"]

DEFAULT_TIER = 4
ANY = "ANY"
_PAIRS = {"EAR": ("EAR1", "EAR2"), "WRIST": ("WRIST1", "WRIST2"), "FINGER": ("FINGER1", "FINGER2")}


class ExpectedError(ValueError):
    """The file of expected cases cannot be read as a list of cases."""


def load_cases(path: Path | str) -> list[Any]:
    """The cases of a file (a JSON list); a case is not checked here, :func:`check_expected` reports one that is unusable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ExpectedError(f"{Path(path).name}: not found") from None
    except (OSError, ValueError) as error:
        raise ExpectedError(f"{Path(path).name}: cannot be read as JSON ({type(error).__name__})") from None
    if not isinstance(data, list):
        raise ExpectedError(f"{Path(path).name}: not a list of cases")
    return data


def _names(case: Mapping[str, Any], mode: str) -> list[str]:
    names = case[mode]
    if not isinstance(names, list) or not names or not all(isinstance(name, str) and norm_name(name) for name in names):
        raise ValueError(f"{mode} is a list of item names")
    return list(names)


def _read_case(case: Any) -> dict[str, Any]:
    """The parts of a case, or ``ValueError`` saying what is wrong with it."""
    if not isinstance(case, Mapping):
        raise ValueError("a case is an object")
    modes = [mode for mode in ("any_of", "none_of") if mode in case]
    if len(modes) != 1:
        raise ValueError("a case has any_of or none_of, one of them")
    try:
        trio = parse_trio(case.get("trio") if isinstance(case.get("trio"), str) else list(case.get("trio") or ()))
    except (ValueError, TypeError):
        raise ValueError("trio is three different class codes") from None
    role, slot = case.get("role"), case.get("slot")
    if not isinstance(role, str) or role.strip().lower() not in {"any", *ROLES, *REMOVED_ROLES}:
        raise ValueError(f"role is a build of the rules ({', '.join(ROLES)}), {', '.join(sorted(REMOVED_ROLES))} (a build that is gone) or any, not {role!r}")
    if not isinstance(slot, str) or slot.strip().upper() not in {*PLACE_NAMES, *_PAIRS, ANY}:
        raise ValueError("slot is a place, a pair of places or any")
    tier = case.get("tier", DEFAULT_TIER)
    if type(tier) is not int or not 0 <= tier <= 10:
        raise ValueError("tier is a whole number from 0 to 10")
    race = case.get("race")
    if race is not None and (not isinstance(race, str) or not race.strip()):
        raise ValueError("race is a race code")
    return {
        "trio": trio, "role": role.strip().lower(), "slot": slot.strip().upper(), "tier": tier, "race": race.strip().upper() if race else None,
        "mode": modes[0], "names": _names(case, modes[0]),
    }  # fmt: skip


def slot_items(kit: Kit, slot: str, results: Results) -> list[tuple[str, str]]:
    """``(place, item name)`` for what the kit wears in ``slot`` (a place, a pair of places, or ``ANY``: anywhere in the kit)."""
    wanted = {slot} if slot in PLACE_NAMES else set(_PAIRS.get(slot, ()))
    return [(place, results.table.records[key].name) for place, key in kit.worn() if slot == ANY or place in wanted]


def check_case(case: Any, index: int, results: Results) -> dict[str, Any]:
    """The report of one case (see the module docstring)."""
    try:
        read = _read_case(case)
    except ValueError as error:
        return {"index": index, "status": "invalid", "reason": str(error)}
    report: dict[str, Any] = {
        "index": index, "trio": "-".join(code.lower() for code in read["trio"]), "role": read["role"], "slot": read["slot"], "tier": read["tier"], "race": read["race"],
        "mode": read["mode"], "names": read["names"],
        "unknown_names": [name for name in read["names"] if not results.table.keys_named(name)],
    }  # fmt: skip
    if len(report["unknown_names"]) == len(read["names"]):
        return {**report, "status": "invalid", "reason": "no item of the table has any of its names, so the case cannot be judged"}
    wanted = {norm_name(name) for name in read["names"]}
    role = read["role"]
    if role in REMOVED_ROLES:  # a case written for the Balanced build of an earlier release: that build no longer exists, so the case is judged by no kit
        return {**report, "status": "na", "reason": f"the {role} build no longer exists"}
    if role != "any" and role in ROLES and role not in roles_for(read["trio"], bow=None):
        return {**report, "status": "na", "reason": f"the trio is not offered the {role} build"}
    kits = [kit for kit in results.kits(read["trio"], read["race"]) if kit.tier == read["tier"] and read["role"] in ("any", kit.role)]
    if not kits:
        what = "no such trio in the results" if read["trio"] not in results.folders else "no kit of that role, tier and race"
        return {**report, "status": "na", "reason": what}
    roles: dict[str, Any] = {}
    for kit in kits:
        worn = slot_items(kit, read["slot"], results)
        hit = any(norm_name(name) in wanted for _, name in worn)
        roles[kit.role] = {"holds": hit if read["mode"] == "any_of" else not hit, "worn": [name for _, name in worn], "race": kit.race}
    holding = [role for role, entry in roles.items() if entry["holds"]]
    failing = [role for role, entry in roles.items() if not entry["holds"]]
    agree = not failing if read["mode"] == "none_of" else bool(holding)
    return {**report, "status": "agree" if agree else "disagree", "roles": roles, "roles_holding": holding, "roles_failing": failing}


def check_expected(cases: Sequence[Any], results: Results) -> dict[str, Any]:
    """The report of a list of cases: each case, the counts, and the agreement share."""
    reports = [check_case(case, index, results) for index, case in enumerate(cases, 1)]
    counts = {status: sum(r["status"] == status for r in reports) for status in ("agree", "disagree", "na", "invalid")}
    decided = counts["agree"] + counts["disagree"]
    unknown = {norm_name(name) for r in reports for name in r.get("unknown_names", ())}
    return {**counts, "unknown_name_count": len(unknown), "agreement": round(counts["agree"] / decided, 3) if decided else None, "cases": reports}


def render_report(report: Mapping[str, Any]) -> str:
    """The text of a report: a line for each case, then the counts."""
    lines = ["Expected cases"]
    for case in report["cases"]:
        label = f"  #{case['index']} [{case['status']}]"
        if case["status"] == "invalid":
            lines.append(f"{label} {case['reason']}")
            if case.get("unknown_names"):
                lines.append(f"      unknown names (no item of the table has them): {'; '.join(case['unknown_names'])}")
            continue
        where = f"{case['trio']} {case['role']} +{case['tier']} {case['slot']}" + (f" ({case['race']})" if case["race"] else "")
        rule = f"{case['mode']} ({'; '.join(case['names'])})"
        lines.append(f"{label} {where} {rule}")
        if case["status"] == "na":
            lines.append(f"      {case['reason']}")
        else:
            for role, entry in case["roles"].items():
                lines.append(f"      {role}: {'holds' if entry['holds'] else 'does not hold'}; the kit wears {'; '.join(entry['worn']) or 'nothing there'}")
            if case["role"] == "any":
                lines.append(f"      roles that satisfy it: {', '.join(case['roles_holding']) or 'none'}; roles that do not: {', '.join(case['roles_failing']) or 'none'}")
        if case["unknown_names"]:
            lines.append(f"      unknown names (no item of the table has them): {'; '.join(case['unknown_names'])}")
    share = report["agreement"]
    lines.append(
        f"  agree {report['agree']}, disagree {report['disagree']}, n.a. {report['na']}, invalid {report['invalid']}; unknown names {report['unknown_name_count']}; agreement "
        + ("none" if share is None else f"{share:.1%}")
    )
    return "\n".join(lines) + "\n"
