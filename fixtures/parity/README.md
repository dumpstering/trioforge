# Parity fixtures (the committed sample)

These files hold the browser engine to the Python reference. Each one is a JSON document with the inputs of a computation and
what Python computed from them: the model JSON the builder makes, the exact value `F` of the best kit, the canonical kit and the
exact breakdown (every exact number is a reduced `"p/q"` string). The JS tests compare their own results with these.

This folder is a **small sample** (under 2 MB gzipped, plain text so that the privacy scan can read it). The full set, with the
5,000 evaluations, all 330 brute-force instances and every wearable at every tier, is made on demand into `build/fixtures`, which
git ignores.

## What is here

| Folder | What it holds |
|---|---|
| `brute/` | 40 small invented instances (item keys start with `it`), each with the exact maximum by enumeration of every legal kit |
| `matrix/` | 11 scenarios chosen so that every stratum is in at least two: Iksar, a deity, each weapon setup, a real shield in the off hand, each buff key, a Monk trio below +10, mixed WIS/INT mana, a trio with END only, each role, tiers 0, 4 and 10, composed weights |
| `upgrade/` | 3 Upgrade sessions, one per tier mode, each with Equip now, three farm steps, the best 2 and 3 sets and Every slot (between them a new item, another copy of an owned one and a tier upgrade of an owned one; two own a deity-locked item), and 3 invented sessions that pin Every slot |
| `pmb36/` | 6 of the neutral PAL/MNK/BER 36 scenarios |
| `evaluate/` | 150 random kits with their exact breakdowns, and the Monk bins of each level that has a Monk profile |
| `profiles/` | the PAL/MNK/BER bundle, the profile of every race, role and buff key (with no evidence level, and at each one: the weapon setups follow the level), and 60 weight compositions |
| `items/` | 150 item records, the item at every tier and both weapon rates, the tier modes and merge costs |

`manifest.json` lists every file with the size and SHA-256 of its text, the data release, the rules version, the seed and how
many scenarios cover each stratum. The format is described in the docstring of `pipeline/trioforge/export/fixtures.py` and
checked by `pipeline/trioforge/export/fixtures.schema.json`.

## Making them again

```sh
# the sample (this folder); a test fails when its release fields differ from the catalog and the rules
PYTHONPATH=pipeline python -m trioforge.export.fixtures --out fixtures/parity --sample

# everything, for the JS parity tests (several minutes)
PYTHONPATH=pipeline python -m trioforge.export.fixtures --out build/fixtures --seed 20261014

# check a folder: the schema, the hashes, the release fields and that nothing in it is private
PYTHONPATH=pipeline python -m trioforge.export.fixtures --out fixtures/parity --validate
```

The same seed writes the same bytes. Nothing here is edited by hand.

## Where they come from

Only the public catalog is used. Item records are those of the browser's item table, made from the eqlwiki pages of
`derived/catalog.json`. A real "strict" item (one the maintainer or a player saw in game) is never in a fixture: a case that says
`strict-proxy` is built from the hash-picked stand-in for the strict level (`trioforge.bench.strict_proxy`), and the generator
refuses a catalog that has a strict item. Invented items have keys that cannot be a catalog key.

## Licence and attribution

The item records and names are from **eqlwiki** (<https://eqlwiki.com/>), written by the eqlwiki contributors and licensed under
**CC BY-SA 4.0** (<https://creativecommons.org/licenses/by-sa/4.0/legalcode>); see `LICENSE-DATA`. The numbers computed from them
are this project's, under the same licence.
