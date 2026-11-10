# Notice

TrioForge is a fan project, not affiliated with or endorsed by Daybreak Game Company. EverQuest is a registered trademark of Daybreak Game Company LLC.

## Data sources

- **eqlwiki** (<https://eqlwiki.com/>): licensed CC BY-SA 4.0 by the eqlwiki contributors. Item data in this project is adapted from it; changes: parsed, normalized, filtered, tier-scaled. The racial abilities in `derived/racials.json` are adapted from its race pages; changes: parsed from each page's Racial(s) list, each name given the first sentence of the page's section of that name where there is one, strings sanitized. Licence: <https://creativecommons.org/licenses/by-sa/4.0/legalcode>
- **EQL Tools** (<https://eqltools.com/sources>): its gear and quest JSON is licensed CC BY-SA 4.0 (compiled from eqlwiki). The gear data is used as a cross-check; the quest data supplies quest giver zones (`derived/quests.json`). Licence: <https://creativecommons.org/licenses/by-sa/4.0/legalcode>
- **EQL Tools attributes table** (<https://eqltools.com/attributes>): the race base stats and class modifiers in `rules/races.json` are cited from it. They are game facts (EQL Tools reads them from the game client), so they fall outside the CC BY-SA grant, see LICENSE-DATA.

## Acknowledgements

- **EQEmu**: Some formulas and constants are modelled on the EQEmu server project (https://github.com/EQEmu/Server, GPL-3.0); no EQEmu code is used.

## Software

- **HiGHS** (<https://github.com/ERGO-Code/HiGHS>): MIT licence. The full licence text ships with the `highspy` package.
- **highs-js** (<https://github.com/lovasoa/highs-js>): MIT licence. The full licence text ships with the `highs` npm package.
