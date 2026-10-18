# TrioForge

Exact best-in-slot gear plans for every class trio in EverQuest Legends — a fan project

TrioForge is a fan project, not affiliated with or endorsed by Daybreak Game Company. EverQuest is a registered trademark of Daybreak Game Company LLC.

## Licences

- Code: MIT, see [LICENSE](LICENSE).
- Data (`derived/`, `fixtures/`, `rules/` and the generated site data): CC BY-SA 4.0, see [LICENSE-DATA](LICENSE-DATA) and <https://creativecommons.org/licenses/by-sa/4.0/legalcode>.
- Third-party notices: [NOTICE.md](NOTICE.md).

## Contributing

Contributing: see CONTRIBUTING.md

## Running the tests

Requires Python 3.12 and Node 24. Every dependency is pinned to an exact version. `requirements.lock` pins the whole Python set, indirect dependencies included, and carries the sha256 of every file that may be installed; pip refuses anything else.

```sh
python -m venv .venv
.venv/bin/python -m pip install --require-virtualenv --require-hashes -r requirements.lock
.venv/bin/python -m pytest

npm ci --ignore-scripts
npm test
```

On Windows, use `.venv\Scripts\python.exe` in place of `.venv/bin/python`.
