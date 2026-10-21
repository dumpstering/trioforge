# Recorded answers for the tests of the weekly sources check

These files stand in for the network when `scripts/sources_check.py` is tried or tested (`--dry-run fixtures/checks/sources`). Every name, title, number and sentence in them is invented; only the shape of the answers is that of the real ones (the MediaWiki API with `format=json&formatversion=2`, and the JSON files of a static site).

| File | Stands in for |
|---|---|
| `catalog.json` | the part of `derived/catalog.json` that the check reads: the key and the wiki title and revision of each item |
| `recentchanges-1.json`, `recentchanges-2.json` | the two pages of `list=recentchanges` for the main namespace, with changes that the check must leave out: other namespaces, a log entry, a title that is not in the catalog, a field of free text |
| `patch-notes.json` | the wikitext of the patch notes page |
| `gear.json`, `quests.json` | the gear and the quest JSON files of EQL Tools |
| `replay.json` | which request gets which file (`ReplayTransport` in `scripts/checks_common.py`) |
