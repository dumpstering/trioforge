# Contributing to TrioForge

TrioForge is a fan project that publishes exact best-in-slot gear plans for EverQuest Legends class trios. The most useful contributions are corrections: a wrong item stat, a missing source, or a rule that the evidence no longer supports. You can report those without writing code, using the issue forms under "New issue".

## The privacy rule

Do not include character names, player names, chat lines or screenshots of chat. Item names, zones and NPC names are fine.

The rule covers everything in and around the repository: code, tests, fixtures, data, documentation, issues, pull requests and screenshots. Game logs hold other players' names and private conversations, and a public git history cannot be cleaned up afterwards.

- Tests and fixtures use invented names only.
- A string with the shape of a game-log line is built at run time, by joining pieces, so that no source line itself looks like a log line. The same goes for a path into a user's profile folder and for a word that points at the game client's program file.
- To show a problem, describe it in words, or give the item name and the zone. Do not paste log text.
- Write a path into a profile folder with a placeholder: `<user>` or `<name>`, not a real folder name.

Two checks enforce the rule.

- **The git hooks** run on the maintainer's computer, where the privacy key is. Install them together, once per clone, with `sh scripts/install-hooks.sh`. The pre-commit hook scans the staged version of each changed file, not the working copy. The commit-msg hook scans the whole commit message, comment lines included. The pre-push hook scans every file and the index, the whole history (every file and message in it, and every branch and tag name), and what the push is about to send: the commits the remote lacks, even one that no branch reaches when it is pushed by id, and the names the refs will have on the remote. It also checks who made every commit: the author and the committer must use the address in `privacy/identity.txt`, which is committed (git config is not trusted for this), and every date must be in UTC, so make commits with `TZ=UTC git commit ...`. The hooks run the Python in `.venv`, so create it first (see "Running the tests"); without it a hook stops with an error instead of passing. A hook also blocks when the privacy key is missing (see below), so the hooks are meant for maintainers, who hold the key.
- **The `privacy` job in CI** scans every file and all of history on each push and each pull request, and on a push to `main` it checks who made each commit and in which time zone (for a pull request GitHub builds a merge commit with its own author, which would never pass). It does not need the key.

The scanner checks these things:

- A **denylist** of private names. The repository holds only keyed digests (HMAC-SHA256) of the names; the key is kept outside the repository, so the digests cannot be used to test guesses. Before a name is looked up, the text is read in several forms: as written, with encodings undone (HTML, percent, JSON and base64, one inside another), with look-alike and invisible characters folded, with hyphenated line breaks and Markdown emphasis removed, and, for a binary file, as the runs of printable text in it (ASCII and UTF-16).
- **Log-shape rules**, which flag text that looks like a line from a game log: a bracketed timestamp, a tell, a loot message, a `/who` row, a group change, or the player's own chat.
- **Local paths** into a user's profile folder, and **program-file words**, which point at the game client's own program file. Nothing public may cite those.
- **Refused files**: archives (a zip header anywhere in the first 64 KiB counts, so Office and OpenDocument files are archives), PDFs, Git LFS pointers, submodules, and the maintainer's private "seen in game" flags in every form they take: any file named `seen-flags.json`, any path with a `build` folder in it (a build made with the flags goes to the git-ignored `build/`), any `.json` file that holds a reason with the code `seen-in-game`, and the exporter's output under any name (a JSON object of exactly `version`, `license` and `keys`, whose keys are item keys). These need no key, so CI runs them.

The scanner never prints the text it matched, because the CI logs of a public repository are public. It prints only the path, the line and column, the rule and a short tag. A path with a private name in it is printed with that part replaced. Without a key no name can be recognised, so a path is then printed as a hash of itself (`<path:` and 8 hex digits).

The privacy key stays on the maintainer's computer and is never given to GitHub. CI runs repository code, so a secret there could be read by any change that reaches the repository, and the published digests would then become a dictionary of names. That is why CI does not need the key: it runs every check that works without one, and the hooks check the denylist before anything is pushed. The key is read from a file given with `--key-file`, or from the `TRIOFORGE_PRIVACY_KEY` environment variable on a computer you trust (never as a CI secret), or from the maintainer's own default location.

If you do not have the key, do not install the hooks. Run the scan that needs no key before you push; it applies every other check and says that the denylist check was skipped:

```sh
PYTHONPATH=pipeline python -m trioforge.privacy.scan --all --history
```

On Windows PowerShell, set the path first with `$env:PYTHONPATH = "pipeline"`. A maintainer runs the full scan with the key before merging a pull request. To see the paths and the matched text of a finding on your own computer, add `--explain`; it refuses to run in CI and when its output is not a terminal.

### Known limits

The scanner is a safety net, not a guarantee. It does not catch:

- capital letters scattered through a name (`zOrBlAx`);
- a name split by a plain space (`Zor blax`);
- a name inside an image, or inside a compressed stream other than a zip file (a zip file is refused whole), or inside a binary file apart from the runs of printable characters it extracts from it;
- an encoding nested deeper than six rounds;
- a name that is not on the denylist, which it cannot know. Read your own change before you push it.

## Running the tests

You need Python 3.12 and Node 24. Every dependency is pinned to an exact version. `requirements.lock` pins the whole set, indirect dependencies included, with the sha256 of every file that may be installed, and CI installs from it with `--require-hashes`.

```sh
python -m venv .venv
.venv/bin/python -m pip install --require-virtualenv --require-hashes -r requirements.lock
.venv/bin/python -m pytest

npm ci --ignore-scripts
npm test
```

On Windows, use `.venv\Scripts\python.exe` in place of `.venv/bin/python`.

The Python package is not installed. The tests find it through the `pythonpath` setting in `pyproject.toml`; when you run a module by hand, put `pipeline` on the path as shown above.

A wall-clock bound in a test of `tests-js/` goes through `expectWithin` of `tests-js/timing.mjs`, which lets the budget grow with how much slower the machine is than when it is idle (up to 8 times, so that a busy machine does not fail the test and a blow-up still does), and not through a comparison of `performance.now()` with a number.

The parity tests of the browser engine hold the JavaScript ports to the Python reference with fixtures made by `trioforge.export.fixtures`. `npm test` always runs them on the small sample that is committed under `fixtures/parity`. The full set is made on demand, takes several minutes and is ignored by git:

```sh
PYTHONPATH=pipeline .venv/bin/python -m trioforge.export.fixtures --out build/fixtures --seed 20261014
```

When `build/fixtures` is there the tests that want it run on it too; when it is absent they are skipped, with the reason in their name. CI makes it and sets `TRIOFORGE_FULL_FIXTURES=1`, which turns a missing full set into a failure.

The shard parity test (`tests-js/shard-parity.test.mjs`) holds the engine to what the precompute published. Every view in the shards of a folder of results (a race, role, tier, weapon setup, evidence level and buff set) is solved again by the engine, from the `items.json` and `engine-l<level>.json` of that folder and with the tie stage, by `bestKit` of `engine/bestkit.js` (the function the worker calls for the best kit of a view, so the test and the worker cannot drift; `tests-js/best-kit-parity.test.mjs` asks the worker itself for the same views), and must equal its shard in its value, its kit place for place and its assumed haste, and in its optional buffs unless the buffs are a tie: a view whose value, kit and haste are equal and whose buff sets differ passes, because two buffs of equal value give the same kit and the engine and the precompute may name the other one; it is counted and printed as a tie (the count in the summary line, then the views). A difference in the value, the kit or the haste fails, with a difference in the buffs or without it. `defaults.json` is held to the same values. A view that differs is printed with its first difference, and the check goes on and lists them all at the end. `npm test` runs it on `fixtures/site/results-solved`, the output of a narrow precompute run on the invented catalog of the site fixture (the shards of `fixtures/site/results` are written by hand, so no solver agrees with them). `pipeline/tests/shard_fixture.py` makes that folder and `test_shard_fixture.py` fails when it is stale; after a change to the model, the solver, the exporter or the rules, write it again with `PYTHONPATH=pipeline .venv/bin/python pipeline/tests/shard_fixture.py`. The results of a real run are checked on the maintainer's computer, where the folder is kept out of the repository:

```sh
TRIOFORGE_RESULTS=build/results npx vitest run tests-js/shard-parity.test.mjs --reporter=verbose
```

The precompute prunes the pool of a chunk once for each set of race-only items that a race can wear, with the first race that wears them, and `bestKit` prunes with the profile of the race itself; they are one pruning because `prune` reads nothing that differs between races but the race, to leave out the race-only items the race cannot wear. `tests-js/best-kit-prune-guard.test.mjs` holds that for every race of the bundle over the views of the same folder (and over pools in which a few items are made race-only, seeded): the kept items are the precompute's, and `prune` is run with a profile that records what it reads, which must be none of the fields that differ between the races of the bundle (worked out from the bundle: the naked attributes and the Iksar armor class) but the race. A pruning that read one of them fails it on any view, whether or not it changed a kept item. It takes the same `TRIOFORGE_RESULTS` and `TRIOFORGE_SHARD_SAMPLE`.

A whole folder of real results has thousands of views, each solved with the tie stage, and takes a long time. `TRIOFORGE_SHARD_SAMPLE=i/n` checks only the chunks i, i+n, i+2n ... of the folder (a chunk is one view across the races, in a fixed order), so `n` runs with `i` from 0 to n-1 check every view once and can run side by side; every sample also solves the views `defaults.json` is made from and checks it (so `n` runs check it `n` times). `TRIOFORGE_SHARD_PART=k/K` does the part k of K of all that work (the sample's chunks and the chunks of each `defaults.json`, which a part never shares), so `K` processes with `k` from 0 to K-1 do every view once and check each `defaults.json` once; a part beyond the units of the work checks nothing and passes. The release build starts them itself (`--parity-processes`). `TRIOFORGE_SHARD_LINES=all` lists every view that differs, where the default lists the first hundred.

To change a Python dependency, edit its exact `==` pin in `requirements.txt`, install into a fresh virtual environment, write the full set of pins with `pip freeze --exclude-editable`, and then run `python scripts/lock_hashes.py`, which adds the sha256 of every file PyPI lists for each pin. A package that is not in the lock, or a file whose hash is not listed, is refused by `--require-hashes`. npm dependencies use exact versions, and `package-lock.json` is committed.

### Browser tests and the preview

The built site is also tested in a real browser: Chromium, driven by Playwright, against `wrangler pages dev`, so that the response headers of `site/_headers` apply as they will on Cloudflare Pages. These tests need the Python environment above as well, because the run builds the site first.

```sh
npm ci --ignore-scripts
npx playwright install chromium
npm run e2e
```

`npm ci --ignore-scripts` installs the pinned tools without running their install scripts, so the browser is fetched by `npx playwright install chromium` (once; Playwright keeps it in its own cache). `npm run e2e` builds the site from the small synthetic results in `fixtures/site/results`, starts the preview by itself, runs every check in four views (a 1280 px and a 360 px wide window, each with the system in light and in dark mode) and stops the preview again. Failure traces and screenshots go under `build/e2e/`, which git ignores. The vitest tests of `npm test` do not need the browser.

The shards of those synthetic results are written by hand. Seven files of them are not, because the browser's engine needs a bundle and an item table that cannot be: `fixtures/site/results/pal-mnk-ber/engine-l50.json`, `fixtures/site/results/items.json`, `fixtures/site/equip-now.json` (the Equip now answers that the engine is held to), `fixtures/site/kit-values.json` (the value of those kits under each role and buff set, which the page's evaluator for a shared kit is held to) `fixtures/site/best-kit.json` (the best kits of whole-pool views, with the sliders at x0.5 and x2, a custom weight or a regen window, as Python solves them), `fixtures/site/weighted.json` (Equip now, a farm path, the best 2 and 3 sets and Every slot under weights drawn from fixed seeds, as Python's reference gives them) and `fixtures/site/weapon-rate.json` (the best kits at the weapon tier rate 5 and 10). `pipeline/tests/engine_fixture.py` makes them with the exporter and Python's reference from an invented catalog, and `test_site_engine_fixture.py` fails when a committed file is stale; after a change to the exporter, the rules or the invented items, write them again with `PYTHONPATH=pipeline .venv/bin/python pipeline/tests/engine_fixture.py`.

- `npm run e2e -- --project=phone-dark -g axe` runs one view and the tests whose title matches. The projects are `desktop-light`, `desktop-dark`, `phone-light`, `phone-dark` and `once`, which holds the tests that do not depend on the view.
- `TRIOFORGE_RESULTS` points the run at another folder of results, such as `build/results` after a precompute run, instead of the synthetic ones. The tests take every switch and value from the page, so they run unchanged on real results (the one test that asks the worker for Equip now is skipped there: its answers are those of the synthetic results).
- `TRIOFORGE_PREVIEW_PORT` is the port the preview serves on (8788 by default). An occupied port is an error, so a preview left over from an earlier run cannot hide a broken build; pick another port when another copy of the repository has one running.
- `TRIOFORGE_SOURCES_MANIFEST` names a sources manifest other than the default (`derived/sources-manifest.json`, or the fixture's own for the synthetic results), and `TRIOFORGE_PYTHON` the Python that builds the site (by default the one in `.venv`).
- `TRIOFORGE_PREVIEW_DIST` is the folder the preview builds the site into (`site/dist` by default), so that two previews can run side by side, and `TRIOFORGE_PREVIEW_EXALT` set to 1 builds it from a copy of the results (under `build/`) that has the two files of the effects layer, made by `python -m trioforge.effects.fixtures --site`: the fixture results were made before the layer, and the section Effects to exalt needs the files. The browser tests start a second preview this way, on the port after `TRIOFORGE_PREVIEW_PORT` (`TRIOFORGE_PREVIEW_EXALT_PORT` names another), for `tests-e2e/exalt.spec.mjs` alone.

On Windows PowerShell, set a variable before the command, for example `$env:TRIOFORGE_PREVIEW_PORT = "8800"`.

To look at the site yourself, `npm run preview` builds the same synthetic results into `site/dist` (git ignores it; the preview is built `--noindex`) and serves them at `http://127.0.0.1:8788/` until you press Ctrl+C. Give it a folder to serve real results: `npm run preview -- build/results`.

The site generator itself is `python -m trioforge.site.build --results build/results --out site/dist`, run with `PYTHONPATH=pipeline`. A few rules of the build:

- A **preview** (`--noindex`) can be made from anything, and needs no account for the report links: without `--owner` no page links to a repository ("Reports open when the project is public" stands in its place). A preview made from a narrowed precompute run (some races or roles, `--limit`, one evidence level or buff set) says "Preview: partial data" on every page. The tiers are not a narrowing: `--tiers` is the scope of a precompute run (+0, +4 and +10 by default, and every tier for pal-mnk-ber), the shards record it, the tier switch of a page offers those tiers and no others, and a run that has all of its scope is not partial.
- An **indexable** build (no `--noindex`) refuses partial results and a trio whose shards have other tiers than a full run of it (+0, +4 and +10, or every tier for pal-mnk-ber; a preview takes any), and needs `--owner NAME`, the GitHub account that owns the repository, because the report links point at its issues. The word `OWNER`, which stood for the account in earlier repository files, is a real account of someone else, and every build refuses it.
- The marker that says a folder may be replaced by the next build is the file `<folder>.trioforge-build` beside the output folder (git ignores it), so nothing of ours is inside the folder that is served. A build that fails before its new folder is in place removes a marker it made itself and keeps one that was there before, so a failed first build leaves no marker beside an empty folder of yours.
- The output folder is replaced whole or not at all: the build writes into a folder beside it (`<folder>.<token>.trioforge-tmp`, which git ignores and the build removes) and swaps that in, so a build that fails or is interrupted (Ctrl+C) part way leaves the old output as it was. If the old output cannot be deleted once the new one is in place (a read-only file in it, for one), the build still succeeds and says on stderr which folder (`<folder>.<token>.old.trioforge-tmp`) is left over and can be deleted. It refuses a link (a symbolic link or a junction) as the output folder or anywhere in it. `--out` may be a relative path; `--out .` replaces the folder you run the build from where the system can move it, and on Windows, which cannot, the build refuses it in one line (run it from another folder).

## Making a data release

A data release is made on the maintainer's computer, which holds the privacy key. Nothing in CI makes one. Wiki is the one evidence level of a release (DECISIONS, 2026-10-19), so the build takes the public catalog alone and no private flags.

```sh
python scripts/release-build.py --tag data-YYYY-MM-DD --privacy-key <the private key file> --processes 20
```

It refuses a catalog that has any strict item before the first hour is spent (the refusal names `rules/community-seen.json`, where a report that stays in force makes an item strict), so that a second evidence level cannot come into a release without a decision; with no strict item the strict pool of every trio is empty and the precompute makes the wiki view the default one. It precomputes every trio of the grid at its default scope (chunk files and their fingerprints stay in `build/results/`), checks the release (every trio present, none partial, each at its scope; the invariants; every bundle against the catalog and through the browser's own reader; the exact number of files of the site; a pruning spot check of one random scenario of each trio against the unpruned optimum; the parity suite on a sample of the chunks and on the defaults of every trio), reads the texts that are published for any path of this computer, runs the keyed privacy scan over everything that ships, packs one `tar.gz` into `build/release/` and writes two things for git: `releases/<tag>.json` (the pointer, with the SHA-256 of the asset) and `reports/results-diff-<tag>.md` (what changed since the last release, and why, in counts and the largest changes of the value; read it before tagging, and a solver diff first). The full diff, `build/reports/results-diff-<tag>.json`, lists every change with its items: it stays in `build/`, away from the asset, and is never committed or published. The build prints counts, the places of what it wrote, and warnings, never an item.

- **Run it from a worktree of its own, at the commit to release** (`git worktree add ../trioforge-release <commit>`; the private key is named by its path), never in a checkout that is being worked in. The build refuses a folder that is not a git worktree. It records, once, at its start, the hash of the code, the HEAD of the checkout with a digest of `git status` and one of `git diff HEAD`, the rules and the catalog, and writes `release.json` from those values; every worker uses the hashes of the code, and one that starts after a change (a respawn after a crash, for instance) imports the code, hashes it, and refuses its trios if the hashes are not the build's. It refuses the release if any of that has changed when the precompute ends or just before it packs (a merge, an edit or a new file in the checkout in the middle of the hours would otherwise stamp chunks with the hash of code that did not make them), and says to run it again. The chunks stay.
- **Upload exactly `build/release/<tag>.tar.gz`**, never a pattern such as `build/release/<tag>.*`. Nothing else in `build/release/` is named for the tag, but the upload names the one file.
- **A release is the whole grid.** `--trios a,b` builds a trial of some trios instead: it writes no pointer, nothing in `releases/` or `reports/`, and uses up no tag (its asset and its two reports, both headed TRIAL, are in `build/trial/`).
- **A run that is stopped is run again with the same command.** Finished trios are skipped, and chunk files made from the same inputs are kept. A trio that was finished before the code that writes its files changed (the shards, the defaults, the seals, the bundle) is written again from its chunks, and solves nothing. A run that did not end leaves nothing that looks like a release: at the start of a build of a tag with no pointer, what a killed run left under the tag is taken away by exact name (the staging folder, the scratch folder of the bundle check, the temporary asset, an asset that was renamed into place before the run ended, the full diff of the first round `build/release/<tag>.results-diff.json`, a Markdown report `reports/results-diff-<tag>.md` that git does not track, and the temporary files of a write of the pointer or of the report that was cut short, `releases/.<tag>.json.*.tmp` and `reports/.results-diff-<tag>.md.*.tmp`; a report or a temporary file that is tracked by git is refused, with the reason, and nothing is removed then). A decision to delete fails closed: when git cannot be asked whether a file is tracked (it does not start, it does not answer in time, its index is damaged), the build is refused, and no failure of git counts as "not tracked". From the packing of the asset to the writing of the pointer is one transaction: an error anywhere in it takes the asset away.
- **Private files are written only where git ignores them.** Before it writes the full diff, a trial's files or the temporary file of any of them, the build resolves the path, refuses a link or junction on the way, and asks `git check-ignore` about the path itself (an ignore rule for the names of the catalog alone is not enough). The build folder itself must be ignored as a whole, or lie outside the work tree: a path inside it that no rule for a part of it covers is asked about, so a `.gitignore` that covers the folder only in part is refused at the start and not by the state check at the end, after the hours.
- **A closed pipe is no failure.** The command exits 0 when the standard output closes (`| head`, a closed terminal) after the release is built, with a warning on standard error; a closed pipe during the build only stops the printing. A standard output that is not there at all (`sys.stdout` is None, as under `pythonw`) counts as closed, and a line that the encoding of the console cannot write is written with `?` for the characters it cannot, and silences nothing.
- **A refusal leaves no output.** Chunk files stay in `build/`.
- **The parity sample.** `--parity-stride n` makes the sample one chunk in `n` (the default, and the largest `n` allowed, is the number of chunks of the smallest trio, so that every trio has chunks in it; a smaller `n` is a bigger sample). The offset is drawn from the snapshot id of the release, and `release.json` records the sample.
- **Warnings.** Each of the weekly checks of the computer leaves `<name>.last-run` (an ISO time) in the folder of the checks, which is outside every worktree (`$TRIOFORGE_CHECKS_DIR`, an absolute path that is not in a git work tree and is refused otherwise, the build included; else `~/.local/state/trioforge/checks`, on Windows too), so that a build in a worktree of its own finds what the checks left from the main checkout; the build warns at the start when one is more than 10 days old or missing, and when the asset of the previous release is not in `build/release/` (the report is then compared with nothing). What the checks are, how to put them in the Task Scheduler and how to read what they leave is in `docs/runbook-weekly.md`.

## Issues and pull requests

- Use an issue form for data problems: Wrong item data, Seen in game, or Rule correction. Blank issues are turned off.
- Every rule lives in `rules/rules.json` with a seal, a source and a date. A change to a rule changes that file, and the seal says how well the value is known.
- Keep a pull request to one change, add or update tests with it, and fill in the checklist in the pull request template.

## Licences of contributions

- Code is licensed under the MIT licence; see `LICENSE`.
- Data (`derived/`, `fixtures/`, `rules/` and the generated site data) is licensed under CC BY-SA 4.0; see `LICENSE-DATA`.

By opening a pull request you agree that your contribution is licensed under these terms, so contribute only code and data you have the right to license that way. Data adapted from other sources keeps its attribution; see `NOTICE.md`.
