"""The model: item tier views, lookup tables, the exact-formula evaluator, buffs, weapons, roles and profiles.

* :mod:`trioforge.model.tables`: the client's class pools, softcaps and skill caps, the race and class
  tables and the rules, in one read-only object;
* :mod:`trioforge.model.items`: a catalog item at one upgrade tier;
* :mod:`trioforge.model.tiers`: the tier a candidate is scored at under a tier mode, and what reaching a tier costs;
* :mod:`trioforge.model.formulas`: the evaluator, written on its own so that it can check the solver;
* :mod:`trioforge.model.buffs`: which long buffs a trio has and how they stack;
* :mod:`trioforge.model.weapons`: weapon setups and the per-hand damage index;
* :mod:`trioforge.model.roles`: the roles a trio is offered and the weights of each;
* :mod:`trioforge.model.profile`: one scenario's constants, in a frozen record the evaluator and the builder read.
"""
