# Recorded eqlwiki race pages

Two race pages of eqlwiki (<https://eqlwiki.com/>), kept so that the parser of racial abilities (`trioforge.sources.racials`, tested in `pipeline/tests/test_racials.py`) runs without a network.

## Licence and attribution

The page text is from **eqlwiki**, written by the eqlwiki contributors and licensed under **CC BY-SA 4.0** (<https://creativecommons.org/licenses/by-sa/4.0/legalcode>). Each page's history on eqlwiki lists its authors; the page titles and revision ids below identify exactly what was recorded.

Changes: none to the content. Each file is the page record the fetcher saves (`pageid`, `ns`, `title`, `revid`, `timestamp`, `content`), re-serialized with indentation.

## How they were recorded

On 2026-11-08, by `python -m trioforge.sources.eqlwiki fetch --category "Category:Character Races"`: one request for the member list and one for the 16 pages, a second apart, to `api.php`, with the project's user agent and the robots.txt of the site read first (it allows everything). These two records are taken from that pull.

| File | Page title | Page id | Revision id | Revision timestamp (UTC) |
|---|---|---|---|---|
| `ogre.json` | Ogre | 50582 | 153426 | 2026-07-01T18:25:54Z |
| `iksar.json` | Iksar | 50574 | 163965 | 2026-07-29T14:01:47Z |

The Ogre page lists "Increased Consumption Rate, Infravision, Frontal Stun Immunity, Slam" and has a section for every one of them except Slam. The Iksar page lists seven racials, one of them with a figure in brackets (`Swimming (100)`) and two that are resists, and has a section for three.
