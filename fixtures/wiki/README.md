# Recorded eqlwiki pages

These files are raw replies from the eqlwiki MediaWiki API (<https://eqlwiki.com/api.php>), kept so that the parser tests run without a network. There are 67 files, one per page title: 20 item pages (the first table), 7 crafting pages (the second), 25 pages for the parser fixes, taken from the cached full pull (the third), and 15 pages for the second parser review, from the same pull (the fourth).

## Licence and attribution

The page text is from **eqlwiki** (<https://eqlwiki.com/>), written by the eqlwiki contributors and licensed under **CC BY-SA 4.0** (<https://creativecommons.org/licenses/by-sa/4.0/legalcode>). Each page's history on eqlwiki lists its authors; the page titles and revision ids below identify exactly what was recorded.

Changes: none to the content. The API's JSON reply was re-serialized with indentation, nothing else.

## How they were recorded

On 2026-10-14 between 04:02 and 04:03 UTC (the evening of 2026-10-13 in US Central time), by

```sh
PYTHONPATH=pipeline python -m trioforge.sources.eqlwiki record --out fixtures/wiki <the 20 titles below>
```

That is one request per title, serial and one second apart, to `api.php` with `action=query&prop=revisions&titles=<title>&rvprop=ids|timestamp|content&rvslots=main&format=json&formatversion=2&maxlag=5`. Redirects are not followed, so a redirect page would be recorded as itself. The user agent was `TrioForge-extractor/0.1 (non-commercial fan project; 1 request/s)`.

## The pages

None of the 20 titles is a redirect. One title has no page on the wiki; it is recorded as such and is a test case for the `missing` skip.

| File | Page title | Page id | Revision id | Revision timestamp (UTC) | Note |
|---|---|---|---|---|---|
| `engineers-ring.json` | Engineer's Ring | 42638 | 193407 | 2026-10-12T23:33:03Z | |
| `girdle-of-faith.json` | Girdle of Faith | 16279 | 180733 | 2026-10-03T05:28:30Z | |
| `cloak-of-flames.json` | Cloak of Flames | 42660 | 155619 | 2026-07-10T13:52:58Z | |
| `shield-of-the-stalwart-seas.json` | Shield of the Stalwart Seas | 42690 | 179970 | 2026-09-30T22:39:01Z | |
| `bladestopper.json` | Bladestopper | 35441 | 149848 | 2026-06-08T12:56:01Z | |
| `earthshaker.json` | Earthshaker | 34955 | 178691 | 2026-09-17T13:21:47Z | |
| `wus-fist-of-mastery.json` | Wu's Fist of Mastery | 16201 | 179238 | 2026-09-23T20:46:03Z | |
| `torrid-corruptor.json` | Torrid Corruptor | 59097 | 180357 | 2026-10-02T13:46:34Z | |
| `baton-of-the-sky.json` | Baton of the Sky | 57110 | 177378 | 2026-09-09T14:15:23Z | |
| `talisman-of-kejaar-kerrath.json` | Talisman of Kejaar Kerrath | 59028 | 164093 | 2026-07-30T02:21:56Z | |
| `skinners-belt.json` | Skinner's Belt | 42648 | 155788 | 2026-07-11T00:09:56Z | |
| `imbued-granite-spaulders.json` | Imbued Granite Spaulders | 546 | 157912 | 2026-07-15T21:47:24Z | |
| `darkwar-mask.json` | Darkwar Mask | 44308 | 145710 | 2026-06-04T00:45:37Z | |
| `rusty-dagger.json` | Rusty Dagger | 17039 | 139697 | 2026-06-04T00:18:08Z | |
| `bone-chips.json` | Bone Chips | 16452 | 194007 | 2026-10-13T23:46:17Z | |
| `backpack.json` | Backpack | 16791 | 193759 | 2026-10-13T23:41:25Z | |
| `mask-of-deception.json` | Mask of Deception | 301 | 162641 | 2026-07-27T20:18:01Z | |
| `dwarven-chain-tunic.json` | Dwarven Chain Tunic | none | none | none | missing: the wiki has no such page |
| `symbol-of-marr.json` | Symbol of Marr | 34998 | 173874 | 2026-08-27T20:56:53Z | |
| `ethereal-mist-chestplate.json` | Ethereal Mist Chestplate | 33469 | 174407 | 2026-08-28T20:31:52Z | |

## Crafting pages

Seven more pages were recorded on 2026-10-14 between 06:39:23 and 06:39:30 UTC, the same way (one request per title, serial and one second apart, the same user agent):

```sh
PYTHONPATH=pipeline python -m trioforge.sources.eqlwiki record --out fixtures/wiki <the 7 titles below>
```

They show how a "Player crafted" list is really written (a trade skill line, a yield, an `In [[Forge|Oggok Forge]]:` container line and `N x [[Ingredient]]` lines) and test the crafting reader in `pipeline/tests/test_itempage_crafting.py`. Two use a cultural forge (Oggok Forge, Teir`dal Forge), one lists three containers on one line, one has a trade skill and nothing else, one is a "Combine ... in a ..." sentence, and one is a note that the item is not made by a trade skill.

| File | Page title | Page id | Revision id | Revision timestamp (UTC) |
|---|---|---|---|---|
| `banded-belt.json` | Banded Belt | 32365 | 174342 | 2026-08-28T19:36:17Z |
| `ogre-bouncer-shield.json` | Ogre Bouncer Shield | 49376 | 166517 | 2026-08-05T20:13:19Z |
| `block-of-adamantite.json` | Block of Adamantite | 37149 | 193955 | 2026-10-13T23:45:16Z |
| `crystalline-silk-cloak.json` | Crystalline Silk Cloak | 33237 | 141222 | 2026-06-04T00:24:59Z |
| `large-patchwork-cloak.json` | Large Patchwork Cloak | 16742 | 166485 | 2026-08-05T19:59:36Z |
| `10-dose-greater-null-potion.json` | 10 Dose Greater Null Potion | 52595 | 193481 | 2026-10-13T23:35:58Z |
| `air-tight-box.json` | Air Tight Box | 53169 | 193661 | 2026-10-13T23:39:30Z |

## Pages for the parser fixes

Twenty-five more pages come from the cached full pull of `Category:Items` that was fetched on 2026-10-14 (`sources/eqlwiki/2026-10-14`, git-ignored). **No new request was made for them**: each file holds the cache's record of the page (page id, revision id, timestamp and text) in the shape of an API reply (`batchcomplete`, `query.pages[].revisions[].slots.main`), serialized like the other files. The one difference from a reply made by `record` is that `parentid` is left out, because the cache does not keep it.

They are real pages that show how a statsblock or a source list is really written, and the tests of the parser (`test_itempage.py`), the normalizer (`test_normalize.py`) and the evidence ladder (`test_evidence.py`) use them:

* deity lines: a hyphenated name, two gods joined by a slash, a name with no `Deity:` label, a line with only a name, and four gods in one line;
* charges: `EXPENDABLE  Charges: N`, a `Charges:` line before the stats, and a spell scroll;
* keys the first parser read badly: `BACKSTAB:`, `Fire DMG:`, `ENDUR:`, `[[Haste]]:`, `WIS +4` and `SV FIRE +5` with no colon, a class list wrapped onto a second line, a slot with no `Slot:`;
* `Race: ELF DEF VAH` (Vah Shir), `Class: NONE` and `Race: NONE`;
* the banners `{{Delete}}`, `{{:Does Not Exist}}`, `{{DNE}}` and `{{revamped}}`, and the notes a drop list may hold instead of a zone (`ITEM REMOVED FROM GAME`, `N O T _ C L A S S I C`, `Located in the following locations:`, `(ToV East mobs)`).

| File | Page title | Page id | Revision id | Revision timestamp (UTC) |
|---|---|---|---|---|
| `azzars-dreadful-hat.json` | Azzar's Dreadful Hat | 35122 | 177910 | 2026-09-11T05:41:50Z |
| `imbued-northman-long-dagger.json` | Imbued Northman Long Dagger | 49251 | 163531 | 2026-07-28T19:45:42Z |
| `kejekan-smithy-hammer.json` | Kejekan Smithy Hammer | 54156 | 148371 | 2026-06-04T00:57:47Z |
| `imbued-black-pearl-electrum-choker.json` | Imbued Black Pearl Electrum Choker | 48933 | 146156 | 2026-06-04T00:47:40Z |
| `blessed-champion-arrows.json` | Blessed Champion Arrows | 59714 | 169678 | 2026-08-15T05:01:15Z |
| `batling-eye.json` | Batling Eye | 35127 | 142780 | 2026-06-04T00:32:01Z |
| `10-dose-adrenaline-tap.json` | 10 Dose Adrenaline Tap | 52641 | 193474 | 2026-10-13T23:32:19Z |
| `a-crude-stein.json` | A Crude Stein | 16776 | 139453 | 2026-06-04T00:17:02Z |
| `serpents-tooth.json` | Serpent's Tooth | 34966 | 193414 | 2026-10-13T00:45:43Z |
| `kerasian-axe-of-ire.json` | Kerasian Axe of Ire | 56873 | 163066 | 2026-07-28T03:38:02Z |
| `yelinaks-talisman.json` | Yelinak's Talisman | 17133 | 155691 | 2026-07-10T14:21:51Z |
| `teir-dal-adamantite-vambraces.json` | Teir`Dal Adamantite Vambraces | 49231 | 160776 | 2026-07-23T19:28:14Z |
| `velvet-trimmed-satin-robe.json` | Velvet-Trimmed Satin Robe | 43936 | 161195 | 2026-07-24T16:00:37Z |
| `tri-plated-golden-hackle-hammer.json` | Tri-Plated Golden Hackle Hammer | 423 | 161788 | 2026-07-24T18:42:40Z |
| `azarack-skin-wristwraps.json` | Azarack Skin Wristwraps | 57049 | 177347 | 2026-09-09T14:06:06Z |
| `feir-dal-fletching-kit.json` | Feir`Dal Fletching Kit | 59726 | 194888 | 2026-10-14T00:03:36Z |
| `a-bowyers-guide.json` | A Bowyers Guide | 37017 | 193568 | 2026-10-13T23:37:40Z |
| `spell-aegolism.json` | Spell: Aegolism | 54635 | 197204 | 2026-10-14T00:50:18Z |
| `aerated-pauldrons.json` | Aerated Pauldrons | 16335 | 177585 | 2026-09-09T19:13:16Z |
| `basoon-haste-gauntlets.json` | Basoon Haste Gauntlets | 42685 | 176817 | 2026-09-06T14:44:16Z |
| `bronze-ulak.json` | Bronze Ulak | 44273 | 163817 | 2026-07-28T20:26:11Z |
| `crushbone-battle-beads.json` | Crushbone Battle Beads | 43866 | 194396 | 2026-10-13T23:53:56Z |
| `blackened-iron-armplates.json` | Blackened Iron Armplates | 16829 | 139505 | 2026-06-04T00:17:16Z |
| `robe-of-discord.json` | Robe of Discord | 54451 | 148652 | 2026-06-04T00:59:04Z |
| `unadorned-breastplate.json` | Unadorned Breastplate | 52836 | 147214 | 2026-06-04T00:52:34Z |

## Pages for the second parser review

Fifteen more pages come from the same cached full pull of `Category:Items` (`sources/eqlwiki/2026-10-14`, git-ignored), made into files the same way as the third table's: the cache's record of the page (page id, revision id, timestamp and text) in the shape of an API reply, with `parentid` left out. **No new request was made for them.**

They are real pages that show how a source list is really written, and the tests in `test_itempage_sources.py`, `test_normalize_sources.py`, `test_evidence_sources.py`, `test_real_pages_sources.py` and `test_catalog_sources.py` use them:

* a quest link whose label names one test and whose target names the page that holds all the tests, or a section of a page (`[[Beastlord Plane of Sky Tests|Beastlord Test of Harpy]]`, `[[Plane of Sky#Bard Tests|Bard Test of Tone]]`);
* a drop list written only as bullets, with the zone as a bullet (`* [[Plane of Sky]]`, `* Warrens` over `** [[a creature]]`, two zone bullets over one creature), with a map position (`{{Loc}}`) or with lines of prose;
* the `foraged` parameter: a list of zones, one with a label (`[[Freeport|East Freeport]]`);
* keys the reader missed: `HP. +3`, `Base Dmg: 9`, `Rec Level: 4`;
* a `Charges:` line after the effect it belongs to, and categories inside the template's last parameter;
* the `Required Level` of an effect, in its own line or after its casting time.

| File | Page title | Page id | Revision id | Revision timestamp (UTC) |
|---|---|---|---|---|
| `griffin-hide-armguards.json` | Griffin-Hide Armguards | 57119 | 171881 | 2026-08-23T14:30:36Z |
| `wind-rune-meda.json` | Wind Rune Meda | 59355 | 197813 | 2026-10-14T01:02:18Z |
| `large-empty-crate.json` | Large Empty Crate | 35145 | 195785 | 2026-10-14T00:21:42Z |
| `velium-spear.json` | Velium Spear | 43663 | 145108 | 2026-06-04T00:42:50Z |
| `crushed-diamonds.json` | Crushed Diamonds | 34693 | 194401 | 2026-10-13T23:54:01Z |
| `morning-dew.json` | Morning Dew | 43156 | 196136 | 2026-10-14T00:28:34Z |
| `chilled-tundra-root.json` | Chilled Tundra Root | 16551 | 194213 | 2026-10-13T23:50:20Z |
| `fishing-grubs.json` | Fishing Grubs | 37497 | 180133 | 2026-10-01T09:24:34Z |
| `chipped-jade.json` | Chipped Jade | 53672 | 194227 | 2026-10-13T23:50:37Z |
| `crude-coal.json` | Crude Coal | 60823 | 179608 | 2026-09-27T03:06:20Z |
| `keg-mallet.json` | Keg Mallet | 57366 | 162993 | 2026-07-28T02:16:33Z |
| `essence-of-earth.json` | Essence of Earth | 60345 | 179834 | 2026-09-30T01:05:29Z |
| `fine-steel-naginata.json` | Fine Steel Naginata | 43087 | 194916 | 2026-10-14T00:04:09Z |
| `shroud-of-the-sky.json` | Shroud of the Sky | 57138 | 177361 | 2026-09-09T14:09:27Z |
| `spiroc-beak-earcuff.json` | Spiroc Beak Earcuff | 57121 | 177346 | 2026-09-09T14:05:51Z |
