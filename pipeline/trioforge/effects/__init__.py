"""Effects to exalt: which focus, click, worn and proc effects a trio should put on its items, and where in its kit.

The tool is a port of the private analysis of 2026-10-22, with three fixes and the dispel change of the approved spec (see DECISIONS.md). It reads only
what the site may use: the client's spell text (``derived/client/effect-spells.json``, made by :mod:`trioforge.effects.derive` from ``spells_us.txt``) and the
effects the wiki lists on the items of the public catalog. Every judgment constant is a rule of ``rules/rules.json`` with the seal ``model``
(:mod:`trioforge.effects.judgment`).

* :mod:`~trioforge.effects.spells`   the spell file, the category of a spell, the focus limits and what a focus touches
* :mod:`~trioforge.effects.donors`   the effects of the catalog items, as records with their donor items
* :mod:`~trioforge.effects.layer`    what a class needs, the score of every effect for a trio and role, the ranked lists
* :mod:`~trioforge.effects.plan`     the exalt plan: effects matched onto the items of a kit
* :mod:`~trioforge.effects.files`    the shared ``effects.json``, the per-trio ``exalt.json``, their budgets and the writer the release build calls

Nothing here changes the solver or the value of a kit: the plan is made after the kits are solved and only reads them.
"""

__all__: list[str] = []
