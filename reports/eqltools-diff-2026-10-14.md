# EQL Tools cross-check

Generated 2026-10-14 by trioforge.reports.eqltools_diff 0.0.1.

EQL Tools publishes a gear list compiled from the same wiki pages as our catalog. A difference below means that one of the two parsers read a page differently, or that one of them skipped it. Nothing here says which side is right: each difference has to be checked against the wiki page.

Credit: EQL Tools (eqltools.com), gear data CC BY-SA 4.0, used as a cross-check. EQL Tools compiled its data from eqlwiki (https://eqlwiki.com/), CC BY-SA 4.0. Our side of the comparison is item data adapted from eqlwiki.com (CC BY-SA 4.0) by the eqlwiki contributors. This report is released under CC BY-SA 4.0.

## Inputs

| input | file | sha256 | note |
|---|---|---|---|
| TrioForge catalog | `catalog.json` | `b85797db97f38d75a1336e7f8d126cd7ecbbf2cbde5e04866383e7f22fef4b5b` | version `2026-10-14` |
| EQL Tools gear data | `gear-data-2026-10-11.json` | `3280d5ad74abdb76e1141c38bfd0d2ab23d9238172f02aca7faaa650d6b8002f` | licence `CC BY-SA 4.0` |

## How items are matched

Items are matched by name: lowercase, accents and apostrophes dropped, a leading "a", "an" or "the" ignored, `*` read as the word star, every other run of punctuation as one space. A name that several items share on either side is not compared; the shared names are listed below.

## Items

| | items |
|---|---:|
| Items in our catalog | 11250 |
| Items in EQL Tools' gear data | 6970 |
| Matched one to one by name | 6803 |
| Names shared by several items, not compared | 31 |
| Our items in those names | 39 |
| EQL Tools items in those names | 59 |
| Only in our catalog | 4408 |
| Only in our catalog, with a slot | 10 |
| Only in EQL Tools | 108 |
| Entries that could not be read, our catalog | 0 |
| Entries that could not be read, EQL Tools | 0 |

## Fields

Compared: slots, classes, the stats EQL Tools carries (it has no regeneration stats), the resists (including Void, which only EQL Tools has), weight, era and the out-of-era flag. Not compared: races, deities, flags, weapon data, effects and sources.

Counted over the matched pairs. equal: both sides have a value and it is the same. different: both have a value and they differ. missing-ours: EQL Tools has a value and our catalog has none. missing-theirs: our catalog has a value and EQL Tools has none. A field neither side has is not counted, and a stat of 0 is no value.

| field | equal | different | missing-ours | missing-theirs |
|---|---:|---:|---:|---:|
| slots | 6778 | 25 | 0 | 0 |
| classes | 6764 | 37 | 0 | 2 |
| AC | 4589 | 2 | 0 | 1 |
| STR | 1716 | 0 | 0 | 1 |
| STA | 1225 | 0 | 0 | 1 |
| AGI | 932 | 0 | 0 | 1 |
| DEX | 1069 | 0 | 0 | 0 |
| WIS | 1331 | 0 | 0 | 0 |
| INT | 1181 | 0 | 0 | 0 |
| CHA | 876 | 0 | 0 | 0 |
| HP | 1382 | 0 | 0 | 1 |
| MANA | 1289 | 0 | 0 | 0 |
| END | 54 | 0 | 0 | 2 |
| ATK | 1 | 0 | 0 | 0 |
| HASTE | 65 | 0 | 0 | 0 |
| SV FIRE | 1035 | 0 | 0 | 0 |
| SV COLD | 1048 | 0 | 0 | 0 |
| SV MAGIC | 1286 | 0 | 0 | 0 |
| SV POISON | 945 | 0 | 1 | 1 |
| SV DISEASE | 939 | 0 | 0 | 1 |
| SV VOID | 0 | 0 | 4 | 0 |
| weight | 6657 | 1 | 0 | 138 |
| era | 5156 | 3 | 51 | 4 |
| out of era (oe) | 5675 | 1128 | 0 | 0 |

The out-of-era row compares EQL Tools' `oe` flag with our evidence level, where hidden and disputed count as out of era.

## Out of era against our evidence level

| EQL Tools says | strict | wiki | disputed | hidden | no evidence |
|---|---:|---:|---:|---:|---:|
| out of era | 0 | 8 | 224 | 2996 | 0 |
| in era | 0 | 2455 | 0 | 1120 | 0 |

## Out of era disagreements by reason

For the matched pairs that disagree about out of era, how many times each of our reason codes occurs. An item counts once for every reason code it carries.

| reason | ours out of era, EQL Tools in era | ours in era, EQL Tools out of era |
|---|---:|---:|
| `cultural-container` | 637 | 0 |
| `not-for-default-kits` | 283 | 0 |
| `no-known-source` | 273 | 0 |
| `wiki-marked-not-in-eql` | 173 | 0 |
| `not-for-bis` | 78 | 1 |
| `out-of-era-ingredient` | 26 | 0 |
| `live-source` | 0 | 8 |
| `removed-by-research` | 4 | 0 |
| `zones-not-in-eql` | 3 | 0 |
| `out-of-era` | 2 | 0 |
| `zones-unmapped` | 2 | 0 |
| `removed-by-patch` | 1 | 0 |
| `wiki-marked-removed` | 1 | 0 |

## Examples

Up to 20 for each list, in name order.

### Only in EQL Tools

- `Bladesman's Axe` (page ``Bladesman`s Axe``)
- `Carved Ashwood Recurve Bow` (page `Carved Ashwood Recurve Bow (Hemp)`)
- `Carved Ashwood Recurve Bow` (page `Carved Ashwood Recurve Bow (Linen)`)
- `Carved Ashwood Recurve Bow` (page `Carved Ashwood Recurve Bow (Silk)`)
- `Carved Darkwood 1-Cam Bow` (page `Carved Darkwood 1-Cam Bow (Hemp)`)
- `Carved Darkwood 1-Cam Bow` (page `Carved Darkwood 1-Cam Bow (Linen)`)
- `Carved Darkwood 1-Cam Bow` (page `Carved Darkwood 1-Cam Bow (Silk)`)
- `Carved Darkwood Compound Bow` (page `Carved Darkwood Compound Bow (Hemp)`)
- `Carved Darkwood Compound Bow` (page `Carved Darkwood Compound Bow (Linen)`)
- `Carved Darkwood Compound Bow` (page `Carved Darkwood Compound Bow (Silk)`)
- `Carved Darkwood Recurve Bow` (page `Carved Darkwood Recurve Bow (Hemp)`)
- `Carved Darkwood Recurve Bow` (page `Carved Darkwood Recurve Bow (Linen)`)
- `Carved Darkwood Recurve Bow` (page `Carved Darkwood Recurve Bow (Silk)`)
- `Carved Elm Recurve Bow` (page `Carved Elm Recurve Bow (Hemp)`)
- `Carved Elm Recurve Bow` (page `Carved Elm Recurve Bow (Linen)`)
- `Carved Elm Recurve Bow` (page `Carved Elm Recurve Bow (Silk)`)
- `Carved Elm Recurve Bow` (page `Carved Elm, Silk`)
- `Carved Oak 1-Cam Bow` (page `Carved Oak 1-Cam Bow (Hemp)`)
- `Carved Oak 1-Cam Bow` (page `Carved Oak 1-Cam Bow (Linen)`)
- `Carved Oak 1-Cam Bow` (page `Carved Oak 1-Cam Bow (Silk)`)

### Only in our catalog, with a slot

- `Azarack Skin Wristwraps` (`w57049`)
- `Broken Blam Stick` (`w53595`)
- `Coldain Crossbow` (`w52883`)
- `Collar of Necropotence` (`w60529`)
- `Enchanted Fine Steel Great Staff` (`w58344`)
- `Golem Metal Wand` (`w35544`)
- `Guise of the Deceived` (`w60533`)
- `Shadowed Ball` (`w53190`)
- `Shadowed Book` (`w54547`)
- `Tattered Gnomish Cloak` (`w43589`)

### Names shared by several items

- `Adarra's bow of the Unseen`: ours `w52822`, `w53474`; EQL Tools `Adarra's Bow of the Unseen`
- `Bllizent's Fang`: ours `w53552`; EQL Tools `Blizzent's Fang`, `Bllizent's Fang`
- `Cloak of Leaves`: ours `w34725`; EQL Tools `Cloak of Leaves`, `Cloak of Leaves (Sky)`
- `Crimson Training Tunic*`: ours `w17688`, `w53722`; EQL Tools `Crimson Training Tunic*`
- `Dark Stained Training Robe*`: ours `w17690`; EQL Tools `Dark Stained Training Robe`, `Dark Stained Training Robe*`
- `Double Recurved Velium Bow`: ours `w35315`; EQL Tools `Double Recurved Velium Bow`, `Double recurve velium bow`
- `An Elven Charm Necklace`: ours `w57222`, `w57357`; EQL Tools `An Elven Charm Necklace`, `Elven Charm Necklace`
- `Engraved Velium Spear`: ours `w35316`; EQL Tools `Engraved Velium Spear`, `Engraved velium spear (duplicate)`
- `Fine Steel Rapier`: ours `w42741`; EQL Tools `Fine Steel Rapier`, `Fine Steel Rapier (Gunthak Pirate Rapier)`
- `Frost Covered Tome`: ours `w35209`; EQL Tools `Frost Covered Tome`, `Frost Covered Tome Alt`
- `Giant Laceless Sandal`: ours `w34717`; EQL Tools `Gaint Laceless Sandal`, `Giant Laceless Sandal`
- `Golden Locket`: ours `w44073`; EQL Tools `Golden Locket`, `Golden Locket (Locket of Courage)`
- `Jade Chokidai Prod (nerfed)`: ours `w34321`; EQL Tools `Jade Chokidai Prod (Pre-Nerf)`, `Jade Chokidai Prod (nerfed)`
- `Large Ruby`: ours `w60752`; EQL Tools `Large Ruby`, `Large Ruby (Eye of Toque)`
- `Lion-skin Leggings`: ours `w34720`, `w53200`; EQL Tools `Lion-Skin Leggings`
- `Order of Thunder`: ours `w53000`; EQL Tools `Order of Thunder`, `Order of Thunder (Drosco)`
- `Pestilence Scythe`: ours `w16416`; EQL Tools `Pestilence Scythe`, `Pestilence Scythe (droppable)`
- `Ringmail Bracelet`: ours `w32335`; EQL Tools `Ringmail Bracelet`, `Small Ringmail Bracelet`
- `Rough Elm Recurve Bow`: ours `w17065`; EQL Tools `Rough Elm Recurve Bow`, `Rough Elm Recurve Bow (Hemp)`, `Rough Elm Recurve Bow (Linen)`, `Rough Elm Recurve Bow (Silk)`
- ``Rusty Fer`Esh``: ours `w42925`, `w59105`; EQL Tools `Rusty Fer'Esh`

### slots: different

- `Agilmente's Flute of Flight` (`w17617`): ours `PRIMARY`, theirs `PRIMARY SECONDARY`
- `Conch Shell Horn` (`w35273`): ours `SECONDARY`, theirs `PRIMARY SECONDARY`
- `Drums of the Beast` (`w35291`): ours `PRIMARY`, theirs `PRIMARY SECONDARY`
- `Ervaj's Flute of Flight` (`w16067`): ours `PRIMARY`, theirs `PRIMARY SECONDARY`
- `Faun Flute` (`w35278`): ours `SECONDARY`, theirs `PRIMARY SECONDARY`
- `Fine Steel Tonfa` (`w52934`): ours `PRIMARY`, theirs `PRIMARY SECONDARY`
- `Flute of the Sacred Glade` (`w35339`): ours `SECONDARY`, theirs `PRIMARY SECONDARY`
- `Hand Drum` (`w17085`): ours `SECONDARY`, theirs `PRIMARY SECONDARY`
- `Horn` (`w37036`): ours `SECONDARY`, theirs `PRIMARY SECONDARY`
- `Immaculate Shell Horn` (`w35293`): ours `SECONDARY`, theirs `PRIMARY SECONDARY`
- ``Kelin`s Seven Stringed Lute`` (`w42688`): ours `SECONDARY`, theirs `PRIMARY SECONDARY`
- `Lianna's Flute` (`w43188`): ours `SECONDARY`, theirs `PRIMARY SECONDARY`
- `Lute` (`w37037`): ours `SECONDARY`, theirs `PRIMARY SECONDARY`
- `Lute of the Howler` (`w35220`): ours `PRIMARY`, theirs `PRIMARY SECONDARY`
- `Lyendlln's Lute` (`w44098`): ours `SECONDARY`, theirs `PRIMARY SECONDARY`
- `Mandolin` (`w37038`): ours `SECONDARY`, theirs `PRIMARY SECONDARY`
- `Mystical Lute` (`w54287`): ours `SECONDARY`, theirs `PRIMARY SECONDARY`
- `Nostrolo Tambourine` (`w16972`): ours `SECONDARY`, theirs `PRIMARY SECONDARY`
- `Reinforced Bamboo Tanto Bo` (`w33408`): ours `PRIMARY`, theirs `PRIMARY SECONDARY`
- `Reinforced Bamboo Wakizashi Bo` (`w33409`): ours `PRIMARY`, theirs `PRIMARY SECONDARY`

### classes: different

- `Agilmente's Flute of Flight` (`w17617`): ours `BRD`, theirs `ALL`
- `Blam Stick` (`w52988`): ours `WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM`, theirs `WAR CLR PAL RNG SHD DRU`
- `Bloodstar Pendant` (`w42631`): ours `WAR CLR PAL RNG SHD DRU MNK BRD ROG NEC WIZ MAG ENC`, theirs `WAR CLR PAL RNG SHD DRU MNK BRD ROG NEC WIZ MAG ENC BST BER`
- `Cloak of Scales` (`w42634`): ours `WAR SHD MNK SHM NEC BST`, theirs `WAR SHD MNK SHM NEC`
- `Conch Shell Horn` (`w35273`): ours `BRD`, theirs `ALL`
- `Drums of the Beast` (`w35291`): ours `BRD`, theirs `ALL`
- `Ervaj's Flute of Flight` (`w16067`): ours `BRD`, theirs `ALL`
- `Faun Flute` (`w35278`): ours `BRD`, theirs `ALL`
- `Flute of the Sacred Glade` (`w35339`): ours `BRD`, theirs `ALL`
- `Fool's Gold Stein` (`w37387`): ours `WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC`, theirs `WAR CLR PAL RNG SHD DRU MNK`
- `Forge Hammer of Dalnir` (`w34427`): ours `WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC`, theirs `WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC`
- `Glowing Red Stone` (`w35212`): ours `WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC`, theirs `WAR CLR PAL RNG SHD DRU MNK`
- `Hand Drum` (`w17085`): ours `BRD`, theirs `ALL`
- `Horn` (`w37036`): ours `BRD`, theirs `ALL`
- `Immaculate Shell Horn` (`w35293`): ours `BRD`, theirs `ALL`
- `Ivory Handled Dagger` (`w37807`): ours `WAR RNG SHD BRD ROG NEC WIZ MAG ENC`, theirs `WAR RNG SHD BRD ROG NEC`
- `Journeyman's Walking Stick` (`w34611`): ours `WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM`, theirs `WAR CLR PAL RNG SHD DRU`
- ``Kelin`s Seven Stringed Lute`` (`w42688`): ours `BRD`, theirs `ALL`
- `Lianna's Flute` (`w43188`): ours `BRD`, theirs `ALL`
- `Long Iron Rod` (`w17214`): ours `WAR CLR SHD DRU MNK SHM NEC WIZ MAG ENC`, theirs `WAR CLR SHD DRU MNK SHM`

### classes: missing-theirs

- `Bracers of Erollisi` (`w34936`): ours `WAR CLR PAL DRU MNK BRD ROG SHM`, theirs none
- `Soft Leather Shoes` (`w34759`): ours `ALL`, theirs none

### AC: different

- `Lustrous Russet Boots` (`w33319`): ours `14`, theirs `15`
- `Lustrous Russet Gauntlets` (`w33322`): ours `11`, theirs `12`

### AC: missing-theirs

- `Essence of Earth` (`w60345`): ours `4`, theirs none

### STR: missing-theirs

- `Essence of Earth` (`w60345`): ours `5`, theirs none

### STA: missing-theirs

- `Essence of Earth` (`w60345`): ours `5`, theirs none

### AGI: missing-theirs

- `Dusty Burlap Cord` (`w33362`): ours `1`, theirs none

### HP: missing-theirs

- `Dusty Burlap Cord` (`w33362`): ours `5`, theirs none

### END: missing-theirs

- `Cloak of Scales` (`w42634`): ours `50`, theirs none
- `Woven Shadow Gauntlets` (`w33591`): ours `10`, theirs none

### SV POISON: missing-ours

- `Paebala Fetish` (`w17736`): ours none, theirs `5`

### SV POISON: missing-theirs

- `Slave Trammels` (`w58503`): ours `4`, theirs none

### SV DISEASE: missing-theirs

- `Slave Trammels` (`w58503`): ours `4`, theirs none

### SV VOID: missing-ours

- `Anthemion Armbands` (`w58377`): ours none, theirs `2`
- `Clawed Knuckle-Ring` (`w34749`): ours none, theirs `1`
- `Darkspun Shroud` (`w58079`): ours none, theirs `1`
- `Rotting Faydark Mask` (`w58516`): ours none, theirs `1`

### weight: different

- `Anthemion Jerkin` (`w60158`): ours `0.2`, theirs `0.3`

### weight: missing-theirs

- `Abandoned Orc Shovel` (`w53472`): ours `6`, theirs none
- `Antonian Javelin` (`w49489`): ours `1.5`, theirs none
- `Arrow of Acknowledgment` (`w42934`): ours `0.1`, theirs none
- `Arrow of Bravery` (`w42935`): ours `0.1`, theirs none
- `Arrow of Contagion` (`w16537`): ours `0.1`, theirs none
- `Arrow of Defiance` (`w42936`): ours `0.1`, theirs none
- `Arrow of Fire` (`w43214`): ours `0.1`, theirs none
- `Arrow of Fortitude` (`w42937`): ours `0.1`, theirs none
- `Arrow of Frost` (`w16538`): ours `0.1`, theirs none
- `Arrow of Gallantry` (`w42938`): ours `0.1`, theirs none
- `Arrow of Lightning` (`w43215`): ours `0.1`, theirs none
- `Arrow of Poison` (`w43471`): ours `0.1`, theirs none
- `Arrow of Recognition` (`w42939`): ours `0.1`, theirs none
- `Arrow of Stunning` (`w43472`): ours `0.1`, theirs none
- `Balanced Rat Tooth` (`w57335`): ours `0.5`, theirs none
- `Blessed Champion Arrows` (`w59714`): ours `0.1`, theirs none
- `Blessed Guardian Arrows` (`w58965`): ours `0.1`, theirs none
- `Bow of the Destroyer` (`w44384`): ours `0.5`, theirs none
- `Bow of the Huntsman` (`w17586`): ours `2`, theirs none
- `Bow of the Icepaw` (`w35199`): ours `0`, theirs none

### era: different

- `Dusty Burlap Cord` (`w33362`): ours `Classic Era`, theirs `Velious Era`
- `Staff of Temperate Flux` (`w400`): ours `Classic Era`, theirs `Temple Era`
- `Withered Leather Tunic` (`w674`): ours `Classic Era`, theirs `Kunark Era`

### era: missing-ours

- `Book of the Rings` (`w34388`): ours none, theirs `Kunark Era`
- `Broad Sword` (`w36903`): ours none, theirs `Velious Era`
- `Dented Battleshield` (`w43270`): ours none, theirs `Kunark Era`
- `Drape of the Seacasters` (`w43702`): ours none, theirs `Kunark Era`
- `Faun Flute` (`w35278`): ours none, theirs `Velious Era`
- `Finely Crafted Targ Shield` (`w43165`): ours none, theirs `Kunark Era`
- `Flight Arrow` (`w37373`): ours none, theirs `Kunark Era`
- `Gem Encrusted Circlet` (`w44173`): ours none, theirs `Kunark Era`
- `Goblin Sparring Gloves` (`w34310`): ours none, theirs `Kunark Era`
- `Halberd` (`w36998`): ours none, theirs `Kunark Era`
- `Hand of the Reaper` (`w34540`): ours none, theirs `Kunark Era`
- `Ice Enchanced Bracer` (`w43991`): ours none, theirs `Velious Era`
- `Iksar Skull Helm` (`w34318`): ours none, theirs `Kunark Era`
- `Iksar Targ Shield` (`w42931`): ours none, theirs `Kunark Era`
- ``Korzanz Kit`ioukl`` (`w34572`): ours none, theirs `Kunark Era`
- `Lost Staff of the Scorned` (`w296`): ours none, theirs `Kunark Era`
- `Reinforced Rhino Skullcap` (`w33538`): ours none, theirs `Kunark Era`
- `Reinforced Rhino Wrist Guard` (`w33539`): ours none, theirs `Kunark Era`
- `Rotbone Bracelet` (`w34550`): ours none, theirs `Kunark Era`
- `Rotwood Club` (`w44504`): ours none, theirs `Kunark Era`

### era: missing-theirs

- `Crown of Elemental Mastery` (`w16380`): ours `Classic Era`, theirs none
- `Flayed Turmoilskin Belt` (`w33766`): ours `Classic Era`, theirs none
- `Flowing Red Silk Sash` (`w52581`): ours `Kunark Era`, theirs none
- `Leech Husk Tunic` (`w16820`): ours `Kunark Era`, theirs none

### out of era (oe): different

- `Aegis of the Wind` (`w16106`): ours `hidden (no-known-source)`, theirs `in era`
- `Aerated Pauldrons` (`w16335`): ours `hidden (wiki-marked-not-in-eql)`, theirs `in era`
- `Aldryn, Blade of the Ocean` (`w16273`): ours `hidden (no-known-source)`, theirs `in era`
- ``Al`Kabor's Cap of Binding`` (`w16356`): ours `hidden (no-known-source)`, theirs `in era`
- `Amulet of Planar Transference` (`w34975`): ours `hidden (wiki-marked-not-in-eql)`, theirs `in era`
- `Amulet of the Fae` (`w16061`): ours `hidden (no-known-source)`, theirs `in era`
- `Amulet of the Fang` (`w16289`): ours `hidden (no-known-source)`, theirs `in era`
- `Amulet of the Sphinx Eye` (`w16310`): ours `hidden (no-known-source)`, theirs `in era`
- `Amulet of the Void` (`w16358`): ours `hidden (no-known-source)`, theirs `in era`
- `Antonian Javelin` (`w49489`): ours `hidden (cultural-container)`, theirs `in era`
- `Antonian Long Sword` (`w49490`): ours `hidden (cultural-container)`, theirs `in era`
- `Apprentice Skullcap - 1st Rank` (`w16510`): ours `hidden (no-known-source)`, theirs `in era`
- `Apprentice Skullcap - 3rd Rank` (`w16512`): ours `hidden (no-known-source)`, theirs `in era`
- `Arctic Wyvern Boots` (`w33443`): ours `hidden (cultural-container)`, theirs `in era`
- `Arctic Wyvern Shoulderpads` (`w33449`): ours `hidden (cultural-container)`, theirs `in era`
- `Arctic Wyvern Skullcap` (`w33450`): ours `hidden (cultural-container)`, theirs `in era`
- `Arydryidriyorn` (`w16220`): ours `hidden (no-known-source)`, theirs `in era`
- `Augmentor's Mask` (`w16360`): ours `hidden (no-known-source)`, theirs `in era`
- `Azure Ruby Ring` (`w16337`): ours `hidden (no-known-source)`, theirs `in era`
- `Back Straps of Mastery` (`w16181`): ours `hidden (no-known-source)`, theirs `in era`
