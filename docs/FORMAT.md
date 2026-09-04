# Fantasy Life i: The Girl Who Steals Time — save format

Everything below was recovered from `NFL1-Win64-Shipping.exe` (Steam build
`2025_1226_1358_rev104282`) and verified against a real save. The Android build
(`lib/arm64-v8a/libUnreal.so`, v2.2.1.0) contains the **same** key literal and
the same code path, so the container format is identical on every platform —
Steam, Android and Switch saves are interchangeable at this level.

## 1. Files

| File | What it is |
|---|---|
| `002DAE74-00-gamedata.bin` | the character save (~150 KB encrypted, ~8 MB inflated) |
| `002DAE74-00-systemdata.bin` | global settings / title screen data (~2.4 KB) |

Steam (this machine): `Game/Binaries/Win64/SteamData/` for `gamedata`,
`%LOCALAPPDATA%Low/LEVEL5 Inc_/Win64/Users/<id>/Saved/` for `systemdata`.
Both files use exactly the same container.

## 2. Container

```
file      = AES-256-ECB( PKCS#7( body || trailer ) )
body      = uint32 uncompressed_size || zlib_stream
trailer   = uint32 b_is_valid (1) || MD5(body)[16] || 14 zero bytes    (34 bytes)
payload   = inflate(zlib_stream)                -> a UE5 "GVAS" blob
```

* **Cipher**: AES-256 in **ECB** mode, PKCS#7 padded. No IV, no per-file salt.
* **Integrity**: the loader recomputes `MD5(body)` and compares it with the
  trailer. A wrong hash produces the in-game *"save data is broken"* message,
  so the hash must be rebuilt after any edit. The editor does that
  automatically.
* The `b_is_valid` flag is serialised as a 4-byte UE `bool`.

### Key

The key is derived in `MakeKey` (VA `0x146F16FF0` in the Steam exe) from a
UTF‑16 string literal at `0x14B6C3DC0`:

```c
// buf[32] starts zeroed
for (i = 0; str[i] && i < 32; i++)
    buf[i] = (uint8)str[i] - 1;      // note the -1
for (i = 0; i < 32; i++)
    buf[i] += 1;                     // ... and the +1 that cancels it
```

The two passes cancel, so the effective key is the plain ASCII of the literal,
right-padded with `0x01` to 32 bytes. The literal is exactly 32 characters, so
no padding is needed:

```
gQPZXDDr8DsT7VU9mTZwJLYa8PnruSEU
= 6751505a5844447238447354375655396d545a774a4c596138506e7275534555
```

(The `-1`/`+1` split is why the assembled key never appears verbatim in the
binary — a plain byte-scan of the executable does not find it.)

Relevant functions in the Steam build:

| VA | Role |
|---|---|
| `0x14334B2E0` | AES-256 key expansion (Nk=8, 7 Rcon rounds via `btc`) |
| `0x14334A850` | build decryption round keys (equivalent inverse cipher) |
| `0x14334FB00` / `0x14334F190` | encrypt / decrypt dispatch (AES-NI vs software) |
| `0x146F16D60` | PKCS#7 pad + encrypt a `TArray<uint8>` |
| `0x146F16FF0` | key derivation from the passphrase FString |
| `0x147921540` | split the 34-byte trailer off the decrypted buffer |
| `0x1479219B0` | load path: decrypt → split trailer → MD5 → compare |

## 3. Payload — UE5 GVAS wrapper

```
"GVAS"
uint32  save_game_file_version      = 3
uint32  package_file_version_ue4    = 522
uint32  package_file_version_ue5    = 1012
uint16  engine major, minor, patch  = 5, 4, 4
uint32  changelist                  = 0
FString branch                      = "UE5"
uint32  custom_version_format       = 3
uint32  custom_version_count        = 119
{ FGuid guid; int32 version } x 119
FString save_class      "/Script/DP1Project.SaveData"  or ".SystemSaveData"
```

Immediately after the class name comes a LEVEL5 sub-header:

```
uint32  magic    = 0xAB16A21A
uint32  version  = 8
uint32  flags    = 0
FString build_id = "2025_1226_1358_rev104282"
```

Everything after that is a **hand-written binary stream**, not UE tagged
properties — there are no `IntProperty`/`StructProperty` markers anywhere. It
is a flat little-endian sequence of primitives with UE `FString`s
(`int32 length` + NUL-terminated bytes; a negative length means UTF‑16).
`FName`s are written as `FString`s, so empty slots read as the literal
`"None"` (250,775 of them in the sample save).

### Payload map (offsets from the sample save; they shift when items are added)

| Range | Contents |
|---|---|
| `0x000000`–`0x000976` | GVAS header |
| `0x000976`–`0x000FA0` | profile: play timestamps, player transform (double X/Y/Z), current map, emotes, stamps, quick-chat phrases, unlocked menu entries, DLC |
| `0x000FA0`–`0x02849A` | sparse event-flag / counter block |
| `0x02849A`–`0x0E3086` | **item containers** (see below) |
| `0x0E3086`–`0x0F8000` | quests: `qm*`, `qsa_life*`, `qsb*`, `qsd_*`, `qsf_active_event_*`, `qsf_rogue_event_*` |
| `0x0F7FDE`–`0x0F8A80` | **character block**: avatar params, HP/MaxHP/SP/MaxSP, name, current Life, the per-Life arrays, equipped models |
| `0x0FB153`–`0x669302` | **the Base Camp island** (magic `0x301BD677`): 65535 object slots plus their ex-parameters — the bulk of the file, see §9 |
| `0x669302`–`0x699F13` | the island's areas and room interiors (magic `0x566F4529`) |
| `0x6A0000`–`0x780000` | map gathering points (`grp_wood_*`, `pick_map_fish_*`, …) |
| `0x788F57`–`0x798FEE` | **which recipes are known** (`recipe_life*`, magic `0x31CCCDDC`) — see §5 |
| `0x79A223`+ | shops, shrines, NPC data |

## 4. Item containers

One contiguous block of 23 arrays. Each array is `uint32 count` followed by
`count` records; arrays are not always adjacent, so unrelated structs can sit
between them (the editor carries those through untouched).

The array index **is** `EInventoryCategory`, in enum order, and the record's
handle packs it into the top nibble:

| # | Enum | Slots | Holds |
|---|---|---|---|
| 0 | `CONSUME` | 999 | consumables (`ics*`) |
| 1 | `WEAPON` | 1099 | weapons (`iwp*`) |
| 2 | `LIFE_TOOLS` | 1099 | Life tools (`ilt*`) |
| 3 | `SHIELD` | 400 | **shields only** (`iam*`) |
| 4 | `ARMOR` | 1099 | the rest of the armour (`iam*`) |
| 5 | `CRAFT` | 2048 | craft items (`ico*`, `icf*`) |
| 6 | `KIT` | 256 | kits (`kit*`) |
| 7 | `MATERIAL` | 999 | materials (`imt*`) |
| 8 | `RECIPE` | 2048 | recipes (`irp*`) |
| 9 | `IMPORTANT` | 512 | key items, emotes and phrases (`iky*`) |
| 10 | `VEHICLE` | 256 | mounts (`ive*`) |
| 11–22 | `SUPPORT_CHARA_*`, `INSTANT_CHARA_*`, `POWER_UP`, … | 1–256 | the same categories again for companion characters |

`iam` splitting across two bags is the one that catches an editor out: armour
dropped into the shield bag exists in the save but never appears in game.
Shields are the items whose `GDSItemArmorData` row points at a `mdl_sld*`
model — twenty of them, which is what `data/fli_gear.json.gz` carries.

### The record

Every record is an `FInventoryInfoCore` — the game names it in the log line
*"Not Match MagicNumber in FInventoryInfoCore"* — followed by a
category-specific extension. Field names are the game's own, recovered from the
UE reflection data in the executable:

```
uint32  tag              = 0x189C9D08
uint16  handle           = (category << 12) | slot     (0 while free)
uint16  getOrder         = (slot + 1) * 4              (0 while free)
FString itemId                       "None" for an empty slot
uint32  uniqueId                     running acquisition counter
uint32  isFavorite                   a bool, serialised as four bytes
uint32  isPresented                  likewise
FString aocId                        "None" unless the item came from DLC
FString expiredItemId                "None"
FString <unnamed>                    "None"   -- newer builds only, see below
bytes   ext                          the extension
```

An empty stackable slot is 49 bytes on a build without that third FName and 58
on one with it. The extension differs per category, which is why the editor
learns its shape from the array's own records rather than assuming one:

```
stackable bags   uint16 num                            the quantity
kit bags         FString kitTargetId | uint32 ? | uint32 refCraftObjStHdl
equipment bags   uint8  itemTitle                      EItemTitleType
                 uint8  quality                        EItemQualityType, 0-3
                 uint32 count + count x (uint8 kind | uint32 value)
                                                       addEquipStatus
                 uint32 count + count x FString        grantSkillId, 3 slots
                 uint16 equipAbilityNum | uint16 equipViewNum
                 uint8  licenseItemCraftLv             custom version < 2 only
                 uint32 isBurying                      a bool, four bytes
                 uint16 ripeningAge                    the Aging Altar vintage
                 uint16 creatorSignNo                  custom version >= 6
                 uint8  ExEquipItemType                custom version >= 7
```

The equipment layout is the executable's own. UE registers every reflected
property with its name *and* its offset in the struct, and the table for
`InventoryInfoEquip` reads `itemTitle` @0x24, `quality` @0x25,
`addEquipStatus` @0x28, `grantSkillId` @0x30 (three of them), `equipAbilityNum`
@0x48, `equipViewNum` @0x4A, `licenseItemCraftLv` @0x4C, `isBurying` @0x4D,
`ripeningAge` @0x4E, `creatorSignNo` @0x50, `ExEquipItemType` @0x52 — which is
exactly the order the serialiser at `0x14702D030` writes them in. The three
version gates in that function (`CustomVer < 2`, `>= 6`, `>= 7`) account for
every byte: a June Switch save from `rev94200` has a 54-byte extension and a
December `rev104282` one has 55, and 54 + `ExEquipItemType` = 55.

**Equipment has no quantity field at all.** Each piece is its own record, and
the two bytes where a stackable bag keeps its count are `itemTitle` and
`quality` — so writing a quantity into an equipment record silently sets its
title instead. Nothing in the tail can be counted back from the end, because
the last two fields are version-gated; walk the two arrays and read forwards.

`addEquipStatus` entries are **not** strings — a `uint8` and a `uint32`, five
bytes flat. Reading that byte as an FString length happens to work while it is
zero, which it is on every empty slot, and then fails on the one record in ten
that has a real value: 181 of the 4027 equipment records in a complete save.

### The third FName, and the save it bricks

Builds from `2026_0818_1323_rev110414` -- the LEVEL5 sub-header's **version
10** -- write one more `FName` after `expiredItemId`. It is `"None"` on every
record of every save seen so far and nothing appears to read it, but it sits
**in front of** the extension, so every offset in `InventoryInfoEquip` shifts
by nine bytes. The December 2025 build (version 8) and the June Switch one
(version 5) do not have it; version 9 is untested.

Missing it is not a cosmetic error. `ext[0]` becomes the low byte of that
FName's length: writing `itemTitle` there puts a 5 over a 5 and looks fine,
and then `quality = 3` makes the length **773**. The game reads 773 bytes of
name, every byte after that record is misaligned, and **the save will not
load at all** -- twelve such records were enough to strand a real one. Two
quieter symptoms come from the same slip: every equipment title reads back as
`Legend`, because it is reading a string length, and stackable gives land at
quantity 0, because an 11-byte extension is not the 2-byte one a stack has.

The editor tells the two layouts apart from the file, never from a build id.
`_has_extra_name()` (`hasExtraName()` in the port) reads the head of the first
records -- the consumable bag, whose extension is a bare `uint16 num` -- and
asks whether an FString parses where the extension would start. Two bytes of
quantity followed by the next record's tag never do, because the tag puts
`0x9D08` in the high half of the length and it reads as a large negative;
`"None"` always does. The two cases cannot be confused, and one record that
disagrees is enough to fall back to the old shape.

`heal_core_names()` puts an already-damaged save back. The text was never
touched, so the length can simply be restored -- and the two bytes that landed
on it are exactly what the editor meant to write, so they go into the
extension at the offsets the game really reads. `python fli.py fix-gear <save>`
runs it, and the browser build offers it on the panel for a save that will not
parse.

### ripeningAge is the "1000-year vintage"

`ripeningAge` is the Aging Altar's number of years — the *Aging: &lt;n&gt;-year
vintage* line in the item card, `熟成<VALUE>年物` in Japanese, straight from
`GDSMenuText`. The Altar (`熟成祭壇` / *Aging Altar* / IT *Altare
dell'evoluzione*) sits in the Plant Dungeon; burying a piece there ages it and
rolls it three equipment skills into `grantSkillId`.

Those skills are `es_*` ids from `GDSSkillData`, and which three a piece can
get comes from `GDSAddSkillLotTable`: one lot table per kind of gear per grade,
named `addSkillTbl_ripening_{low|high}_{low|mid|high}_{category}` over sixteen
categories (`felling`, `mining`, `fishing`, `harvest`, `cooking`, `blacksmith`,
`woodworking`, `sewing`, `alchemy`, `art`, `sword`, `blade`, `bow`, `Staff`,
`rod`, `shield`). There is **no category for body armour** — the Altar does not
take it. Each item row names its own pool (`addSkillTbl_ax_01`,
`addSkillTbl_sword_02`), and the token in that name is what the categories key
on, so `ax` is `felling` and `pickaxe` is `mining`.

### itemTitle picks the stats

`itemTitle` is `EItemTitleType`: `None`, `Rag`, `Normal`, `Masterpiece`,
`Supreme`, `Legend` — the crafting grades, shown as `item_title_001..005`
(*Ordinary / Fine / Notable / Supreme / Legendary*). It is **not** decoration.
A weapon's attack is nowhere in the save: `GDItemWeaponData` gives each row a
`physicalOffenseList` and a `magicOffenseList` of five values, one per grade,
and the game reads the entry the title names. Armour is the same shape with
`physicalDefenseList` / `magicDefenseList`.

**Life tools are graded the same way**, out of their own table,
`GDSItemLifeToolsData` — one five-value list per row, no magic counterpart. A
True Axe of Time is `1, 1, 1, 1, 750` exactly like a True Sword of Time, so a
tool spawned at anything but Legend reads 0 power for exactly the same reason a
weapon does. The tool table was the missing half of the picture: with only
`GDSItemWeaponData` in the database nothing could pick a grade for an `ilt`
item at all, and every spawned tool came out untitled.

`1` is the table's filler for "this item does not exist at this grade", and the
game shows it as 0. So:

| Item | `physicalOffenseList` | Where its stats are |
|---|---|---|
| Branch, Borrowed Sword | `[60]*5`, `[100]*5` | every grade — handed out untitled |
| Squire's Sword | `130, 160, 200, 1, 1` | Rag … Masterpiece |
| Golden Sword | `1, 380, 410, 450, 1` | Normal … Supreme |
| Apocalypse Sword | `1, 1, 630, 660, 700` | Masterpiece … Legend |
| **True Sword of Time** | `1, 1, 1, 1, 750` | **Legend only** |
| **Bow of Time** | `1, 1, 1, 1, 440` | **Legend only** |

That last pair is why a spawned Sword of Time reads *Attack 0* in game: it only
has stats at Legend, and an editor that writes a quantity into the record lands
on `Rag`. A complete save confirms the reading — the game grants its own
Legend-only story weapons (Sleep Sword `[1,1,1,1,197]`, Sleep Bow
`[1,1,1,1,167]`) at exactly `Legend`, and across 507 game-written equipment
records the titles come out None 347, Rag 56, Normal 43, Masterpiece 31,
Supreme 12, Legend 18 — the distribution crafting would produce.

`equipAbilityNum` is the number of ability slots on the piece, a `uint16`. It
is 1 on everything in the small sample save but 0 on most gear in a complete
one, so it is a slot count and not a validity flag; the editor reads it but
does not write it. Gear in a complete save carries real `es_*` skills with
`equipAbilityNum` at 0, so the skills do not depend on it.

`quality` is `EItemQualityType` — `Quality_0` … `Quality_3`. Everything the
game hands out is 0; crafted gear carries 1–3, alongside a non-zero
`creatorSignNo` (the maker's signature).

Item id prefixes: `ics` consumable, `iwp` weapon, `iam` armour or shield,
`imt` material, `ilt` Life tool, `iky` key item, `ive` mount, `irp` recipe,
`ico`/`icf` craft item, `kit` kit, `ide` decoration.

## 5. Per-Life arrays

Five arrays keyed by `life0000`..`life0014` (15 entries each: index 0 is the
"no Life" slot, 1–14 are the fourteen Lives). Each is
`uint32 count` + `count` × (`FString life_id` + fixed-size body):

| Body | Fields | Sample save (`life0001`) |
|---|---|---|
| 9 B | `uint8 rank`, `uint16 rank_points`, `uint8 ?`, `uint8 flag`, `uint32 pa` | 2, 0, 0, 0, 40 |
| 2 B | `uint16 level` | 10 |
| 4 B | `uint32 exp` | 245 |
| 40 B | 10 × (`uint16 item_handle`, `uint16 item_sort`) | equipment loadout |
| 36 B | 9 × (`uint16 item_handle`, `uint16 item_sort`) | second loadout |

The handles in the loadout arrays are the same `handle` values that item
records carry, which is how equipped gear is referenced.

`pa` is **confirmed**: it is the ability points a Life spends on its abilities
(`PA` in the Italian UI, `LifeSkillPoint` in the executable — `GetSkillPoint`,
`ExeResetLifeSkillPoint`, `ELifeIconType::SkillPointIcon`). A live save whose
Paladin showed 40 PA in game reads 40 here.

`rank` is **confirmed** too, and it is **0-based**: it indexes the
`life_rank_XXXX` text rows starting at 1, so stored 0 → `life_rank_0001`
("None", the Life has not been started), 1 → "Novice", 2 → "Fledgling", and so
on to 7 → "Hero". A live save holding `rank = 2` shows *Principiante* in game,
the Italian for Fledgling.

**`rank` is one byte, not four** (corrected 2026-08-28). Reading it as a
`uint32` works only while the two bytes above it are zero, which they are on
any Life whose rank quests have never been touched — every save this editor was
first built against. They are `rank_points`: what a Life master's quests award
towards the next rank. A save with a rank 3 Blacksmith carrying 100 points read
as rank **25603** (`0x6403`), and writing a rank through the old `uint32` field
zeroed the points.

Both readings were checked against the game's own Life cards on that save:

| Life | Stored | Card |
|---|---|---|
| `life0001` Paladin | rank 2, 0 points, level 15 | *Paladino — Principiante, Liv. 15* |
| `life0010` Blacksmith | rank 3, 100 points, level 7 | *Fabbro — Apprendista, Liv. 7* |
| `life0006` Woodcutter | rank 2, level 17 | *Taglialegna — Principiante, Liv. 17* |

**The star total the card prints next to the rank is not in the save.** That
Paladin card reads ★400 and the Blacksmith ★2200, and neither number occurs
anywhere in the 8 MB payload as a `uint16` or as a `uint32` — every hit for
either is inside an item record, a `land_obj` or the GVAS header. So, like a
bulletin board's level (§8), it is worked out at load rather than stored.

*What* it counts is still open, and this save cannot settle it:

* it may be **what the next rank costs**, looked up by rank — the executable has
  `nextLifeRank`, `_lifeRankInfoList` and `InitLifeRankInfo`; or
* it may be the **Life's own accumulated stars**, summed from its finished
  `qsa_life*` quests the way the board level is summed from `qsd_*` ones.

Both fit the two cards seen. The Blacksmith is the only Life in that save far
enough along to tell them apart, and one glance at a second rank-2 Life settles
it: if Miner and Carpenter also read ★400 it is the rank's price, and if they
read less than the Paladin's 400 it is a personal total.

`rank_points` is unaffected either way — it is 100 on that Blacksmith, whose six
`qsa_life10_*` quests are finished, and 0 on every Life that has not finished a
rank quest since its last rank-up.

The byte at offset 3 is zero on every Life of every save seen and has no name
yet, so the editor reads it and never writes it.

### Recipes are two things, and a bench reads the other one

A recipe is stored twice, and an editor that writes only one half produces a
save where every recipe shows in the smartphone's recipe app and a crafting
bench still lists almost nothing:

1. an `irp*` item in bag 8 (`EInventoryCategory::RECIPE`) — the scroll itself,
   which is what the inventory and the phone list show, and
2. a bit in `FRecipeStatusP.recipeInfoMap`, which is what the **bench** reads.

The game writes both at the same moment and they stay in lockstep: on a played
Switch save 837 of the 839 recipe items in the bag have their bit set, and not
one bit is set without its item.

The block is one flat, fixed-length run near the end of the payload:

```
uint32  magic  = 0x31CCCDDC
uint32  count                       every recipe the build defines
count x { FString recipe_id; uint32 bit_flag }
```

`count` is the whole master table rather than a list of what the player has,
which is why it grows with the game build and not with progress: **1788**
entries on the June Switch build (`rev94200`), **1883** in December
(`rev104282`), **2012** on `rev110414`. Nothing in it changes length, so an
edit is a four-byte poke per recipe and no offset behind the block moves.

`bit_flag` is `ERecipeSaveCategory`, whose named members the executable's
enumerator table gives as `None = 0`, `Created = 2`, `Favorite = 4`,
`New = 8`, `GotWindow = 16`. **Bit 0 has no name in that enum** — it is the
"player has this recipe" flag the crafting UI reads as
`ItemCraftRecipeInfo_Ver2::isHave`, whose neighbour in the same struct is
`isCreated` (bit 1). Every value seen in a real save is 0, 1, 3 or 9:
`Created` and `New` never appear on their own, which is what pins bit 0 as the
one that means *known*.

Recipe ids are `recipe_life<NN>_<item>` and the `NN` is the Life that crafts
it, so only the six crafting Lives appear — `life0009` Cook, `life0010`
Blacksmith, `life0011` Carpenter, `life0012` Tailor, `life0013` Alchemist,
`life0014` Artist. The matching bag item is `irp_` + the id, with the leading
`recipe_` dropped on most of them (`recipe_life09_flash01` ↔
`irp_life09_flash01`) and kept on 58 (`irp_recipe_life13_ilt11000110`), which
is why the item list and this list stay two databases rather than one derived
from the other.

Rank still gates the *tabs*: a bench groups its list by the Life rank each
recipe is learned at (`ItemCraftRecipeSelectMenuInfo.rankList`,
`EItemCraftRecipeDetailHeaderIconType::Rank`), so a Life left at rank 0 shows a
short list however many bits are set here. Marking recipes known and raising
the Life's rank are two separate edits.

## 6. Currency

The game calls money **`Rich`** internally (`ECurrencyType::Rich`,
`GetRich`, `SellRichRate`, `RichOverFlow`). The full currency enum is:

```
None, Rich, Star, SkillPoint, TourCoin, GoddessSeed, ShineGoddessSeed,
RainbowGoddessSeed, GoddessHerbBlue, GoddessHerbGold, InteractionPoint,
RebuildStone, RebuildPoint, SweetChestnut, RipeningAltarSkillPoint,
PlantDungeon, PlantDungeonBranch, RoguelikePoint, GoldenFragment
```

Dosh lives in the player record at the head of the body, not in a currency
array. In a live save the amount the game displayed (11 486) appeared exactly
once in all 8 MB of payload, at the end of that record:

```
0x0009BF  uint64             FDateTime, when this save was written
0x0009C7  8 bytes            ?
0x0009CF  8 bytes            zero
0x0009D7  3 x double         position X / Y / Z
0x0009EF  uint32 + 2 x float ? + facing
0x0009FB  FString            current map        "Map_100101"
0x000A0A  FString            last warp point    "mjfp_Map_100101_to_Map_100100"
0x000A2C  FString            "None"
0x000A35  uint32             Dosh
0x000A39  uint32             ? (0 here)
0x000A3D  uint64             FDateTime, when this save was written
0x000A45  uint64             FDateTime, when the character was created
```

**The offset is not fixed.** Two of the fields ahead of it are map and warp
point names, so the record's length — and everything after it — moves when the
player changes location. `SaveFile.money_offset()` finds the field by that tail
instead: the `"None"` FString followed by two plausible `FDateTime`s, searched
inside the first 16 KB of the body. Never hard-code `0xA35`.

**Confirmed in game**: writing 999999 here and loading the save showed 999,999
Dosh. Two saves of the same character seven months apart had already ruled out
a time or step counter — position, save timestamp and several quest ids all
changed between them while this field did not.

## 7. The character block

Just in front of the per-Life arrays:

```
float32   1.0
uint32    HP            200
uint32    HP max        200
uint32    SP            118
uint32    SP max        118
uint32    ?
uint32    ?
FString   name          "Angel"
FString   current life  "life0001"
```

Like everything else here it moves — the item section sits in front of it, so
adding an item shifts the whole block. `flisave/character.py` finds it by the
one shape that is unique to it: a printable FString immediately followed by a
`lifeXXXX` FString. Inside the per-Life arrays a `lifeXXXX` id is always
preceded by another id or by an array count, never by a name.

Renaming the character changes the length of that FString and therefore the
size of the payload. That is safe: the payload is a sequential stream with no
internal absolute offsets, and every parser in this project locates its section
by pattern, so they all still find their data afterwards.

## 8. World progress: bulletin boards and Ginormosia

Two systems track progress through *places* rather than through the character.

### Bulletin boards

Every settlement has a board — *Bacheca* in the Italian UI, `BulletinBoard` in
the binary — carrying a list of small jobs and a level that rises as they are
finished. The game calls the level a **rank** and the points behind it **EXP**:
`GetBulletinBoardCurrentRank`, `GetBulletinBoardTotalEXP`,
`CalcBulletinBoardNextNeedEXP`, `SearchBulletinBoardRankMax`.

**Neither the rank nor the EXP is in the save.** Every name the binary has for
them is a `Get`, `Calc` or `Search` — there is no setter and no save field — so
both are recomputed at load from the individual job states. Completing the jobs
is therefore the whole edit; the level follows on its own. (Ginormosia below
*does* store its ranks, so this is a real distinction and not an assumption:
the format stores what it cannot recompute.)

A job is one record in the quest stream, the same shape the `qsb`/`qse` quest
records use:

```
FString  quest_id        "qsd_guild_quest_001"
uint32   counter         0 on every board job seen
uint8    state           see below
uint32   flag            1 on every board job seen
```

`EBulletinBoardQuestType` names seven boards — `Base, Kingdom, Tropica,
Swolean, Faraway` and two DLC ones — and the five in a DLC-less save line up
exactly with the five `qsd_` id prefixes:

| Save prefix | Enum | Map | Name |
|---|---|---|---|
| `qsd_guild_quest_` | `Base` | `Map_000100` | Base Camp (*Quartier generale*) |
| `qsd_map100100_quest_` | `Kingdom` | `Map_100100` | Tunoco Coast |
| `qsd_map100400_quest_` | `Tropica` | `Map_100400` | Tropica Isles |
| `qsd_map100500_quest_` | `Swolean` | `Map_100500` | Swolean Island |
| `qsd_map100300_quest_` | `Faraway` | `Map_100300` | Faraway Island |

The Base Camp's jobs are prefixed `qsd_guild_` because the Guild sits there.
`qsd_guild_quest_*` is 61 records; the four island boards are 17–18 each.

The state byte is `EBulltinBoardQuestStatus` (the game's own typo), whose
members are `Hide, CanRecieve, CanRecievePlayAnimation, Progress, Complate`.
The stored values do not run 0..4, so the byte is not that enum directly; what
the saves show is:

| Value | Reading |
|---|---|
| 0 | not offered yet |
| 1 | offered, not yet shown on the board |
| 2 | on the board |
| 254 | finished, reward not collected |
| 255 | **finished** |

255 is the completed marker, read off the direction of travel between two
saves of the same character 17 hours apart: the earlier one had 0 jobs at 255
and a Base Camp board at level 1, the later one had exactly 2 and a board
reading *Liv. 2, Tot. 35*. A far-progressed save has 41 of its 61 Base Camp
jobs at 255. The editor writes 255.

### Ginormosia

The huge continent — `Map_200000`, `HugeMap` in the UI code, *Continente
Moltogrande* in Italian. All of its progress sits in one self-contained block
introduced by a magic number, which is what the editor finds it by:

```
uint32   0x106E6021
uint32   area_count                                    15
area_count x {
    FString  area_id            "map200000_area001"
    uint8    rank                                      1..7
    uint8    rank_shown                                same value in every record
    uint32   points
}
uint32   camp_count;    camp_count   x FString         camps unlocked
uint32   found_count;   found_count  x FString         shrines found on the map
uint32   shrine_count;  shrine_count x {               20 of them
    FString  shrine_id          "shrine_01" .. "Shrine_20"
    uint32   cleared
}
```

Ranks run 1 to 7, and each area carries its own, so they are edited per area.
`GDSAreaRankPoint` holds the points each rank needs — 100, 900, 2000, 5000,
12000 and 130000 — and a save with eleven areas at rank 7 has between 150000
and 160000 points in each of them, past that last threshold. `GDSAreaRankLevel`
also stops at seven, which is why the editor treats 7 as the ceiling: a higher
value would index past the end of the game's own table.

The two rank bytes are equal in every record seen, so both are written. Rank
and points are stored independently and the game does not appear to reconcile
them — a far-progressed save has an area holding 1005 points while still at
rank 1 — so the editor moves the points with the rank by default rather than
leaving a pair that disagree.

The camp and shrine lists are the only variable-length parts, and they are why
this block can change size. `GDSCamp` defines ten camps,
`map200000_camp_000`..`009`. The area ids map to the `HugeMap_01`..`15` text
rows (*West Dryridge Desert*, *Viridia Plateau*, …) and the shrines to
`Map_200000_013`..`032` (*Jo'ee Shrine* … *Glehd Shrine*) in `shrine_01`..`20`
order, which is where the editor gets its labels.

Being found and being cleared are separate: a far-progressed save has 12
shrines in the found list but only 10 with `cleared = 1`. The camps and the
shrine list are both "discovery" state — `ExeCmd_DiscoveryCamp` and
`ExeCmd_DiscoveryShrine` — and the camps are fast-travel points, nothing more.

### The clouds are not in this block

The fog over the open-world map is **not** the area points, and **not** the
camps. Both were tried in game and neither moved it: giving all fifteen areas a
score left the map exactly as cloudy as before, and the ten camps are only
fast-travel points (`ExeCmd_DiscoveryCamp`). The points/fog correlation that
suggested otherwise was a coincidence -- the one area that had scored was also
the only one the player had walked into.

The clouds lift when the player talks to that zone's **eye tower** — fifteen of
them, one per zone, named `tower_001`..`tower_015` in the text tables and given
a joke name each -- *Googlina*, *Googlbert*, *Googlizabeth*
(IT *Occhilia*, *Occhignio*, *Occhiolito*). The binary backs them up with
`EFastTravelType::Tower`, `EMapIconType::Tower`/`TowerGrayOut`/`TowerRankup`
and `ETowerRankButtonType::Lock`/`Release`/`Unlock`.

What they set is known by name: `GDSGlobalSyncBitFlag` holds

| Index | Flag |
|---|---|
| 1 | `flg_guild_house_grade_up` |
| 10-89 | `map_200000_zone001_00` .. `map_200000_zone015_05` -- the cloud patches, five or six per zone |
| 100-114 | `flg_travelpoint_200000_01` .. `_15` -- one per tower |
| 115-120 | `flg_enemy_village_01` .. `_06` |

**Where the array lives.** The flag block is not one flat array — it is banks
behind a header, and the sync table is 2056 bytes into the second one:

```
bytes   0x96622B31            magic, appears exactly once in a payload
uint32  bank size             8192 in every save seen
bytes   bank size             the first bank
...
+2056                         the 121-entry sync table, one byte per flag
```

That holds across builds: the December PC save puts the table at `0x38BB` and a
June Switch save at `0x3915`, and the rule finds both. A set flag is `1` on the
PC build.

**Lighting a tower writes two things**, and an editor has to write both. It was
measured from a pair of saves taken either side of activating one tower
(`research/flagdiff.py`), which differ in exactly eight places — most of them
position, timestamps and dialogue. The two that matter:

| | What |
|---|---|
| the flag | `flg_travelpoint_200000_04` goes 0 → 1 |
| the warp point | the `lt_200000_326` record's state byte goes 0 → `0x50` |

A travel point is `FString lt_<map>_<n>` followed by five bytes whose first is
that state. The open value is build-specific — `0x50` on the December PC build,
`1` on the June Switch one — so the editor reads back whatever the save already
uses rather than assuming.

**`<n>` is per-save, not per-point.** It is stable inside one file — the two
halves of the tower diff above hold the same sixteen ids — but three saves here
carry 15, 16 and 18 `lt_200000_*` records with no id in common, and the set also
covers villages and camps rather than the fifteen eyes alone. So there is no way
to say which record belongs to which tower without a before/after pair for that
particular save. This is why the editor opens travel points only when it lights
*every* tower: one tower on its own writes its flag and nothing else.

A 68-byte record also appears, holding `Map_200000`, an id, a position and
`map200000_area004`. That looks like the queued `AreaOpen` animation
(`EHugeMapOpenAnimationType::AreaOpen`) rather than state: it was empty before
despite two towers already being lit. The editor does not write it, and the
clouds lift without it.

**Confirmed in game**: a save with all fifteen tower flags set and every
Ginormosia travel point opened loads with the whole map uncovered.

Camps could not have been the mechanism anyway — `GDSCamp` maps its ten
camps onto only ten of the fifteen areas, so five could never be uncovered.
Area points come from playing in the area: `ExeCmd_AddAreaPoint`, with
`EAreaRankStatusType` naming the sources (`MONSTER, FISH, ORE, VEGETABLE, WOOD,
TRESURE, EVENT`), and `DecideAreaRank`/`ChangeAreaRank` turning them into the
rank. `EHugeMapOpenAnimationType` has both an `AreaOpen` and an `AreaRankOpen`
animation, so the two are related but distinct events.

Uncovering a zone and ranking it up are therefore separate edits: one point is
enough to lift a cloud, and rank 2 does not begin until 100, so an opened zone
still reads rank 1 — the same as one that was never touched.

Rank and points do drift apart in a real save — one far-progressed area holds
1005 points while still stored at rank 1 — which fits a cached rank that is
only bumped when the game shows the rank-up notification
(`ENotificationMenuType::HugeMapAreaRankUp`). The editor writes both.

## 9. The Base Camp island

Everything the player builds, digs, floods and places on the island in the
present is one system, which the executable calls **CraftObj**. It sits in two
consecutive blocks of the payload, each found by its own magic:

| Magic | What it holds | Size in a real save |
|---|---|---|
| `0x301BD677` | `CraftStatusInfoP` — the object pool and its ex-parameters | ~5.4 MB |
| `0x566F4529` | `CraftAreaStatusP` — the areas, the rooms and their interiors | ~154 KB |
| `0xBD771C57` | the block after them, which is what bounds the second | — |

Each magic occurs **exactly once** in the payload, on every build seen (Steam
December 2025 `rev104282`, Switch June `rev94200`, iOS), so the pair is located
by search and never by offset. Together they are 70 % of the file, which is why
an 8 MB save holds a 6,600-object island.

### The object block

```
uint32  0x301BD677
uint32  version                  4 everywhere so far
byte    header[86]               see below
uint32  objectCount              65535 — a fixed pool, mostly empty
objectCount x CraftObjStatusP
uint32  landCount                10240
landCount x  { uint32 handle; FName tileID; uint32 }
uint32  houseCount               32
houseCount x CraftObjExParamHouse
uint32 n;  n x  8 bytes          CraftObjExParamPickPoint
uint32 n;  n x    variable       CraftObjExParamStand
uint32 n;  n x  8 bytes          CraftObjExParamPlantDungeon
uint32 n;  n x  8 bytes          CraftObjExParamVegetableField
uint32 n;  n x 24 bytes          CraftObjExParamPlannedConstruct
```

The seven pools after the objects are `CraftExParamP`'s seven arrays in
declaration order — `exParamLand, exParamHouse, exParamPickPoint,
exParamStand, exParamPlantDungeon, exParamVegetableField,
exParamPlannedConstruct`. That is how the shape was settled rather than
guessed: the block has to end exactly on the next magic, and this is the only
reading of it that does, on every save tried.

### The object record

`CraftObjStatusP`, in the order the generated UE property table declares it:

```
uint32   handle           slot | ((slot + 1) & 0xFF) << 24
uint32   exParamHandle    0, or  index | kind << 16 | 0xFF << 24
FName    craftObjId
FName    viewPatternId
double   location   x, y, z
double   rotation   pitch, yaw, roll
int32    gridIdx
uint32   mapId            an FName hash; 0x6BBD96BB is Map_000100, the camp
uint8    objStatusBitFlag ECraftObjStatusBitFlag: 1 Shave, 2 Put
```

83 bytes for an empty slot, 90 for a land tile. An unused slot is the same
record every time: both names `"None"`, `gridIdx` **-1** and everything else
zero — which is what lets an exported layout list only the slots in use and
still rebuild the block to the byte.

The two leading handles are what made the record hard to frame. They belong to
the record that *follows* them, not the one before, and reading them the other
way round still parses all 65,535 records — it just leaves the block eight
bytes long and the land pool without its count. `exParamHandle`'s `kind` byte
is the index of the ex-parameter pool it points into, so `0xFF000004` is land
entry 4 and `0xFF010001` is house entry 1.

### What the ids mean

`land_obj` and `water_obj` are the terrain itself, one record per tile on a
100-unit grid, and `viewPatternId` is how that tile is drawn: `Connect_All`
where it has neighbours all round, `Default` where it does not, and
`Scraped_UL` / `UR` / `DL` / `DR` for the four ways a corner can be cut away —
which is what a sculpted cliff is made of. Height is the tile's Z, and a save
uses three of them. The full list of ground types the game knows is
`blank_obj`, `land_obj`, `water_obj`, `waterfall_obj`, `land_desert_obj`,
`land_rock_obj` and their `h_` indoor counterparts.

Everything else names an item id after its prefix, so the text database names
it with no extra table:

| Prefix | What it is | Example |
|---|---|---|
| `obj_ico…` | furniture and decoration | `obj_ico04080010` → `ico04080010`, *Green Grass* |
| `obj_icf…` | structures: houses, squares, bridges, stairs | `obj_icf01020030` → *Thatched House* |
| `obj_limit_…` | invisible area markers (`window`, `way`) | — |
| `obstacle_NN` | the boulders, debris and big trees in the way | — |
| `house_…` | a building's row in the house pool | `house_icf01020030` |

Ids carry variant suffixes the text tables do not list — `icf03020010_03` is a
*Wooden Bridge*, `icf01020040_extension_2` a *Big Thatched House* that has been
extended — so a name lookup that misses falls back to the id before the
underscore.

**A road is not an object.** A path is a *land* tile carrying a land
ex-parameter whose `tileID` is the road item: `obj_icf05010040`, *Swolean
Road*. That is why the land pool travels with the terrain rather than with the
objects.

### Houses

`CraftObjExParamHouse` is what turns a placed building into a home:

```
uint32   handle
uint32 n;  n x uint32   indoorAreaStHdl        the rooms inside it
FName    placedMapId    the map it stands on — "Map_000100" is the Base Camp
FName    entranceMapId  where its door leads
FName    refAreaId
FName    houseDataId    "house_icf01020030"
uint8    houseCategory  ECraftHouseCategory: 1 player, 2 inhabitant,
                                             3 guild, 4 gallery
uint32   -
```

`entranceMapId` is the useful field: `Map_MyHouse` is the player's own house,
`NPCRoom_00xxxx` an inhabitant's, `Map_5000xx` the Guild office or the gallery.
The record does **not** store a position — the building that *is* the house is
the object whose `exParamHandle` points at it, so the player's house position
is that object's `location`.

### The header

86 bytes sit between the version and the pool count and are carried through
untouched. Three quarters of them are constant on every save seen: an FString
`"chr100400"`, then 32 bytes that end with `uint32 65535` — the pool capacity
again. The 52 bytes before the name are four 13-byte records, the first
constant and the other three carrying a small triple and an index; they change
as the island is built up (a save with one house has all three empty, one with
three houses has one to three of them filled) but what they count is not
identified. They move with the island, so a layout import brings them along.

### The area block

`CraftAreaStatusP` holds five lists — map, outdoor, indoor, wall and ceiling
areas — and the indoor ones carry each room's `childIndoorPartsInfoArray`, the
wallpaper and flooring design ids (`ide_thatch_00`) and the room's own name
(`room_6_6`, `npc_empty_room_10_10`). The houses in the block above point into
it by index, so the two are only consistent together; the editor parses the
first block and carries the second verbatim, which keeps houses and their
interiors inseparable without needing to model five more struct shapes.

### Sharing an island

`flisave/basecamp.py` exports both blocks as one gzipped JSON document
(`.flicamp`, about 80 KB for a full island): the used object slots, the used
land tiles, the house pool, the small ex-parameter pools and the area block as
base64. Nothing outside the two blocks points into them, so an import can
replace them outright.

The pool is addressed by slot and every handle is derived from that slot, which
is what makes a *partial* import possible as well: the kept objects and the
incoming ones are laid down together from slot 0 and every handle is rewritten
from its new position. Terrain-only and objects-only imports do that; each
takes the ex-parameter pools its half refers to, and leaves the others alone.

## 10. Re-encoding notes

* zlib level does not matter — the loader inflates whatever valid stream it
  finds and checks the result against the stored uncompressed size. The editor
  uses level 9, so re-encoded files are usually a little smaller than the
  originals; the payload is byte-identical.
* The MD5 trailer **must** be recomputed, otherwise the game rejects the save.
* The payload is a pure sequential stream with no internal absolute offsets,
  so inserting or removing bytes (for example a longer item id) is safe as
  long as the surrounding structure is re-serialised consistently.

## 11. Icons and other art

Item names come from the text DataTables (section 3); the art comes from
cooked `UTexture2D` packages under `Game/Content/Graphics/2D/UI/Icon/`. In the
Android build every one of them is `PF_ASTC_4x4`.

A cooked texture keeps its pixels in the `.uexp`, straight after the platform
data:

```
int32    SizeX
int32    SizeY
int32    packed (slice count / flags)
FString  pixel format        "PF_ASTC_4x4"
int32    first mip to serialise
int32    mip count
int32    0
bytes    mip 0               (W/4) * (H/4) * 16 bytes for ASTC 4x4
```

The UI textures are all single-mip and never spill into a `.ubulk`, so mip 0 is
simply the block data that follows. `flisave/texture.py` reads that.

What is actually there:

| Folder | Contents |
|---|---|
| `UI/Icon/Life` (under `L10N/<lang>/`) | the 14 Life emblems, each with a localised ribbon baked in |
| `UI/Icon/MoneyType` | the Dosh coin and the Star |
| `UI/Icon/Item_small`, `UI/Icon/Item` | 63 item icons — key items and a few pieces of armour |
| `UI/Icon/Item` (under `L10N/<lang>/`) | multiplayer chat stamps, not items |

There is **no icon for the ordinary item** — potions, weapons, materials and so
on are drawn as 3D models in the inventory, so their art is a mesh under
`Graphics/3D`, not a texture. The editor draws a category chip for those.

The Windows build ships the same content as IoStore (`.utoc`/`.ucas`) with an
encrypted index, so the Android APK is the practical source for all of this.
