# Recorded answers for the tests of the monthly pins check

These files stand in for the network and for a small repository when `scripts/pins_check.py` is tried or tested (`--root fixtures/checks/pins/repo --dry-run fixtures/checks/pins`). Every package, action, account, version, date and sentence in them is invented; only the shape of the answers is that of the real ones (the PyPI JSON API, the npm registry and the GitHub REST API).

`repo/` holds the three kinds of file the check reads: a workflow with actions pinned to a commit (and one local and one unpinned), a `requirements.txt` and a `package.json`. The other files are the answers to the requests the check makes for them (for an action, the list of its releases, `github-release-*.json`, from which the highest final release is taken, and the commit of that release's tag); `replay.json` says which request gets which file, and what versions of Python and Node "this computer" has.

The tests treat the date of the run as 2026-10-18, so the scenario is:

| Pin | Answer |
|---|---|
| `example-org/example-action` v2.0.0 | v2.1.0 was released 48 days before: newer, and old enough |
| `example-org/setup-thing` v1.4.2 | the latest release is v1.4.2 at the pinned commit: current |
| `example-org/setup-other` v3.0.0 | v3.1.0 was released 7 days before: newer, but too young |
| `examplelib` 1.2.0 | 1.3.0 is 78 days old (taken); 1.4.0 is 3 days old; 1.3.1 is yanked, 1.5.0rc1 is a pre-release and 1.6.0 has no files |
| `otherlib` 2.0.1 | nothing newer |
| `exampleone` 1.0.0 | 1.1.0 is old enough; 1.2.0 is deprecated and 2.0.0-beta.1 is a pre-release |
| `@example/tool` 2.0.0 | nothing newer |
| `looselib` ^3.1.0 | not an exact pin: not checked |
| Node 24 (this computer: 24.14.0) | 24.15.0 is old enough; 25.0.0 is 3 days old |
| Python 3.12 (this computer: 3.12.7) | 3.12.8 is old enough; 3.13.1 is a later series |
