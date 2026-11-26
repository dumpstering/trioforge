"""K10, the exchange rates of a kit: what one more point of each stat is worth to the objective that the kit was made for.

For a kit the rate of a term is the change of the objective when one point of that term is added to a worn item::

    evaluate_truthful(kit with one more point of the term on a worn item) - evaluate_truthful(kit)

under the profile of the trio, race and role (the weights of the role, the soft cap, the stat knee, the resist and regen caps ...), the buffs the shard names for the kit and its
weapon setup. It is **read-only use of the model**: :func:`trioforge.model.formulas.evaluate_truthful` (the value the solver's truthful optimum is the maximum of, and the
one ``precompute.kitwhy`` takes its losses from), a profile from :func:`trioforge.model.profile.make_profile` and the buffs of :func:`trioforge.model.buffs.own_buffs`. Nothing is
solved and nothing is approximated: a kit whose shard value is not the value the evaluator gives it (to the two decimals a shard keeps) is refused with the two numbers, because
then the results were not made by this evaluator and no rate of it would explain the kit. The weapon procs the kit counts are those its shard records
(:class:`trioforge.model.procs.RecordedProcs`): a proc does not change with a stat, so a rate is the same with it, and the value of the kit has to agree with it.

The terms are :data:`TERMS`: the stats STA STR AGI DEX WIS INT CHA AC HP MANA, each of the five resist schools the model scores (FIRE COLD MAGIC POISON DISEASE), one point of worn
haste and one point of ATK. A point of a stat or of a resist goes to the first worn item (the lowest place of the kit's 22: where a stat is worn does not change its value, which a
test holds); a point of worn haste goes to the worn item with the most haste (worn haste counts the best piece and not the sum), the first of them when none has any.
A rate past a cap (a resist over its cap, a stat over its limit) is 0, as it should be. ``vs_sta`` gives every rate in points of stamina, for a reader who wants an exchange rate
and not an amount; it is None where stamina is worth nothing.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from trioforge.checks.results import Kit, ResultsError
from trioforge.data.jsonio import load_strict
from trioforge.model import formulas as fm
from trioforge.model import tables as tables_module
from trioforge.model.buffs import buffsets
from trioforge.model.procs import RecordedProcs
from trioforge.model.profile import eval_buffs, make_profile

__all__ = ["TERMS", "TOLERANCE", "ExchangeRates"]

STATS = ("STA", "STR", "AGI", "DEX", "WIS", "INT", "CHA", "AC", "HP", "MANA")
SCHOOLS = ("FIRE", "COLD", "MAGIC", "POISON", "DISEASE")  # the schools the model scores (CORRUPTION never is)
TERMS: tuple[str, ...] = (*STATS, *SCHOOLS, "HASTE", "ATK")
TOLERANCE = 0.0051  # a shard keeps the value of a kit to two decimals: the evaluator may differ from it by the rounding and no more


class ExchangeRates:
    """The rates of the kits of one results folder (``context`` is the :class:`trioforge.checks.kits.Context`: the item table and the rules). The tables of the model, the
    spells of a level, and the buffs and profile of a trio, race and role are made once."""

    def __init__(self, context: Any) -> None:
        self.table = context.table
        self.rules = context.rules
        self._tables: Any = None
        self._buffsets: dict[tuple[tuple[str, ...], int], Any] = {}
        self._profiles: dict[tuple[Any, ...], Any] = {}

    def _model_tables(self) -> Any:
        if self._tables is None:
            try:
                self._tables = tables_module.load()
            except (OSError, ValueError) as error:
                raise ResultsError(f"K10: the tables of the model cannot be read ({type(error).__name__})") from None
        return self._tables

    def buffset(self, trio: tuple[str, ...], level: int) -> Any:
        """The own buffs of the trio at the level of the results, resolved as the precompute resolves them."""
        key = (trio, level)
        if key not in self._buffsets:
            path = tables_module.REPO / "derived" / "client" / f"spells-l{level}.json"
            try:
                spells = load_strict(path)
                self._buffsets[key] = buffsets(trio, level, spells, self.rules, ("own",))["own"]
            except (OSError, ValueError) as error:
                raise ResultsError(f"the buffs of the trio at level {level} cannot be made: {path.name} ({type(error).__name__})") from None
        return self._buffsets[key]

    def buff_totals(self, kit: Kit) -> dict[str, Any]:
        """The totals of the buffs of the kit (the buffs that are always on and the optional ones the shard names), in the shape the evaluator reads."""
        try:
            return eval_buffs(self.buffset(kit.trio, kit.level).totals(tuple(kit.buff_ids)))
        except KeyError as error:
            raise ResultsError(f"{kit.slug}: the buff {error.args[0]} that its shard names is not one of the own buffs of the trio") from None

    def _profile(self, kit: Kit) -> Any:
        key = (kit.trio, kit.race, kit.role, kit.level, kit.evidence)
        if key not in self._profiles:
            pool = [self.table.vec(r.key, 0) for r in self.table.eligible(kit.trio, kit.race, kit.evidence)]  # (only its shields are read: the setups follow the pool)
            buffset, tables = self.buffset(kit.trio, kit.level), self._model_tables()
            try:
                made = make_profile(kit.race, kit.trio, kit.level, kit.role, buffset, None, tables, evidence=kit.evidence, items=pool)
            except ValueError as error:
                raise ResultsError(f"{kit.slug} {kit.role}: the model has no profile for it ({error})") from None
            self._profiles[key] = fm.compile_profile(made.eval_profile)
        return self._profiles[key]

    def value(self, kit: Kit) -> float:
        """The value of the kit by the evaluator, as it is (not to two decimals)."""
        vecs = [None if key is None else self.table.vec(key, kit.tier) for key in kit.places]
        return float(self._evaluate(kit, vecs).F)

    def _evaluate(self, kit: Kit, vecs: list[Any]) -> Any:
        profile, totals = self._profile(kit), self.buff_totals(kit)
        try:
            return fm.evaluate_truthful(profile, vecs, totals, setup=kit.setup, procs=RecordedProcs(kit.procs) if kit.procs else None)
        except ValueError as error:
            raise ResultsError(f"{kit.slug} {kit.role} +{kit.tier}: the evaluator cannot value the kit ({error})") from None

    def rates(self, kit: Kit) -> dict[str, Any]:
        """``{"value": the evaluator's value of the kit, "rates": {term: change}, "vs_sta": {term: change in points of STA}}`` (see the module docstring); a
        :class:`~trioforge.checks.results.ResultsError` for a kit that wears nothing and for one whose shard value is not the evaluator's."""
        vecs = [None if key is None else self.table.vec(key, kit.tier) for key in kit.places]
        worn = [n for n, vec in enumerate(vecs) if vec is not None]
        if not worn:
            raise ResultsError(f"{kit.slug} {kit.role} +{kit.tier}: the kit wears nothing, so there is no item to add a point to")
        base = self._evaluate(kit, vecs)
        if abs(float(base.F) - kit.value) > TOLERANCE:
            raise ResultsError(
                f"K10: {kit.slug} {kit.role} +{kit.tier}: the evaluator values the kit at {float(base.F):.2f} and its shard says {kit.value}: the results were not made by this "
                "evaluator (other rules, other code, or the wrong buffs), so no rate of it is given"
            )
        first = worn[0]
        hasted = max(worn, key=lambda n: (vecs[n].haste, -n))
        rates: dict[str, float] = {}
        for term in TERMS:
            at = hasted if term == "HASTE" else first
            vec = vecs[at]
            if term == "HASTE":
                changed = dataclasses.replace(vec, haste=vec.haste + 1)
            elif term in SCHOOLS:
                changed = dataclasses.replace(vec, sv={**vec.sv, term: vec.sv.get(term, 0) + 1})
            else:
                changed = dataclasses.replace(vec, stats={**vec.stats, term: vec.stats.get(term, 0) + 1})
            trial = list(vecs)
            trial[at] = changed
            rates[term] = float(self._evaluate(kit, trial).F - base.F)
        sta = rates["STA"]
        return {
            "value": float(base.F),
            "rates": rates,
            "vs_sta": {term: (None if sta == 0 else (1.0 if term == "STA" else rate / sta)) for term, rate in rates.items()},
        }
