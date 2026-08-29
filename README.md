# Fantasy Life i: The Girl Who Steals Time — save editor

Decrypts, edits and re-encrypts saves for *Fantasy Life i: The Girl Who Steals
Time* (LEVEL5). The container format is the same on **Steam, iOS, Android and
Switch**, so a save dumped from any of them works here. didn't test
with PS5 saves.

The encryption, compression and integrity hash were reverse-engineered from the
shipping executable — see [`docs/FORMAT.md`](docs/FORMAT.md) for the whole
format.

## Browser version

There is a web version of this editor, and for most edits it is the easier
way in:

### **[fli-web-se.vercel.app](https://fli-web-se.vercel.app/)**

No server and no upload — the save is read, edited and written inside the tab,
on your own machine. It covers the Items tab (containers, grades, vintages,
**Super OP Weapon Mode**, bulk fills, gear repair), the character name and
vitals, the wallet, the Lives (level, EXP, rank, PA) and the World (bulletin
boards, Ginormosia, the eye towers).

The two are the same editor: the browser build is a port of this Python one,
held to it byte for byte by a fixture suite that replays a fixed list of edits
on three real saves and compares SHA-256 of the payload after each — 136 checks.

What the page does **not** have is the value hunter (*Find / Edit values*), the
Cheat-Engine-style tool for whatever is still unmapped. That one is desktop
only, and it is the reason to run the Python editor below.

## What it supports

|  |  |
|---|---|
| **Game** | *Fantasy Life i: The Girl Who Steals Time* (LEVEL5) |
| **Game version** | Built and checked against **2.2.x**. The container has not changed shape across the game's updates so far, so older and newer saves are expected to load; the name, gear and icon databases can be rebuilt from any version's pak — see [Item and Life names](#item-and-life-names). |
| **Save platforms** | **Steam / Windows** and **Nintendo Switch**, both tested. **Android** and **iOS** — see below. |
| **Python** | 3.9 or newer |
| **Your OS** | Windows, Linux or macOS — the editor is pure Python. The GUI needs Tk, which ships with the standard Windows and macOS installers (`sudo apt install python3-tk` on Debian/Ubuntu). |
| **Dependencies** | `pycryptodome`, and nothing else |

### Android and iOS

The save is the same file with the same name (`002DAE74-00-gamedata.bin`), the
same AES-256 container, the same compression and the same MD5 trailer on every
platform LEVEL5 ships it on — and the name database in `data/` is in fact built
straight out of the **Android APK**. So a save pulled off a phone should open,
edit and re-encrypt exactly like a PC one.

**the Android and iOS releases have not been tested end to end.**
No edited save has been put back on a phone and confirmed
to load. It should work; it is not proven. If you try it, keep your own copy of
the original first.

## Quick start

```
git clone https://github.com/venustrikes/FantasyLife_i_SaveEditor.git
cd FantasyLife_i_SaveEditor
pip install -r requirements.txt
```

Then the window:

```
python fli_gui.py                                  # then Open save...
python fli_gui.py path\to\002DAE74-00-gamedata.bin # or straight into a file
```

...or the command line, which does everything the window does:

```
python fli.py info  path\to\002DAE74-00-gamedata.bin
python fli.py money path\to\002DAE74-00-gamedata.bin --set 999999
```

The file dialog starts wherever it finds the newest save, so on Steam you
should not have to go hunting. Nothing is written until you press **Save**, and
the previous file is kept as a timestamped `.bak`.

For help or any questions, check [Help and troubleshooting](#help-and-troubleshooting).

## GUI

```
python fli_gui.py                       # then Open save...
python fli_gui.py path\to\002DAE74-00-gamedata.bin
```

* **Character** — the name, HP and SP, the wallet, and who you are: the Life you
  are living with its emblem, level and rank, plus when the save was written,
  when the character was made and where you were standing.
* **World** — the bulletin boards, with a zone picker and a **Complete all
  quests** button, and Ginormosia: unlock every camp, put every area at its
  maximum rank, and reveal every shrine.
* **Items** — pick a container and edit any slot: item id, quantity, clear it,
  or drop something into the first free slot. Each row shows
  the item's icon and its real name, and **Find...** opens a searchable picker
  ("potion", "spada") that puts the id straight into the box.
  Equipment also has a **grade** — see [Gear grades](#gear-grades) — a
  **vintage** in years, and a **Super OP Weapon Mode** tick box that finishes a
  piece the way the Aging Altar does; see
  [Super OP Weapon Mode](#super-op-weapon-mode).
  **Add to first free slot** files it in the container the game itself uses,
  following the view there. **Fix gear...** repairs pieces spawned before the
  editor understood any of this. Underneath, a **Give every ...** panel fills
  the whole bag — every weapon, Life tool, shield, piece of armour, craft item,
  material or recipe the game defines, at a grade and with Super OP where those
  apply; see [Bulk fills](#bulk-fills).
* **Lives** — level, EXP, rank and PA (the ability points a Life spends on its
  abilities) for all fourteen Lives, each with its emblem. Rank is a dropdown
  of the game's own rank names. Apply to one Life or to every Life at once.
* **Find / Edit values** — a Cheat-Engine-style hunter for whatever is still
  unmapped, plus direct read/write and a hex dump.

The `names:` box in the toolbar switches every name and description in the
window between the game's nine languages. The title bar carries a `*` while
there are unsaved edits, and closing with edits pending asks first.

Edits stay in memory until you press **Save**. Saving keeps a timestamped
`.bak` of the previous file next to it, and the written file is decoded again
and compared before the call returns.

## Command line

```
python fli.py info       <save>                          # header + summary
python fli.py items      <save> [--container N] [--all]  # list slots
python fli.py ids        <save>                          # item ids present
python fli.py lives      <save>                          # per-Life table
python fli.py boards     <save>                          # bulletin boards
python fli.py ginormosia <save>                          # areas + shrines
python fli.py money      <save>                          # show the wallet
python fli.py search     "potion" [--lang it]            # item name -> item id

python fli.py give       <save> --id ics01000780 --qty 99
python fli.py give       <save> --id iwp02000220 [--title 5]   # a weapon
python fli.py give       <save> --id ilt01000120 --super-op   # ...fully aged
python fli.py give-all   <save> --what materials --qty 999
python fli.py give-all   <save> --what recipes
python fli.py give-all   <save> --what crafts --qty 999
python fli.py give-all   <save> --what weapons --title 5 --super-op
python fli.py give-all   <save> --what armour --qty 2   # two of each piece
python fli.py set-qty    <save> --container 7 --qty 999
python fli.py set-slot   <save> --slot 0:12 --id iwp01000010 --qty 1
python fli.py fix-gear   <save> [--dry-run]              # repair spawned gear
python fli.py clear-slot <save> --slot 0:12
python fli.py money      <save> --set 9999999            # ... or set it
python fli.py set-life   <save> --life life0003 --level 99 --exp 0 --pa 999
python fli.py set-life   <save> --life all --level 99    # every Life at once
python fli.py boards     <save> --complete base          # finish one board
python fli.py boards     <save> --complete all           # finish every board
python fli.py ginormosia <save> --unlock                 # camps + ranks + shrines

python fli.py find       <save> --value 12345 --type u32 # offsets holding it
python fli.py scan       <save> --value 12345            # all widths at once
python fli.py hunt       <save> --value 12345            # start narrowing
python fli.py hunt       <save2> --value 9876            # ... keep narrowing
python fli.py poke       <save> --at 0xF8008 --type u32 --value 9999
python fli.py dump       <save> --at 0xF8000 --len 256

python fli.py decode     <save> payload.gvas             # raw payload out
python fli.py encode     payload.gvas <save.bin>         # raw payload in
python fli.py diff       <save-a> <save-b>               # what changed
```

Add `-o out.bin` to write somewhere other than in place, and `--no-backup` to
skip the `.bak`. `--lang` picks the language names are printed in.

## The world

The **World** tab covers the two things the save tracks about places rather
than about you. It holds more than fits a 1080p window, so it scrolls: the
wheel moves the page, except over a table, where it moves the table.

**Bulletin boards.** Every settlement has a board — *Bacheca* — with a list of
small jobs and a level that climbs as they are finished. Pick a zone and press
**Complete all quests** and every job on that board is marked finished, which
takes the board to its maximum:

| Zone | Where |
|---|---|
| Base Camp | `Map_000100`, the guild board (61 jobs) |
| Tunoco Coast | `Map_100100` |
| Tropica Isles | `Map_100400` |
| Swolean Island | `Map_100500` |
| Faraway Island | `Map_100300` |

The board's level is **not** stored in the save. Every name the game has for it
is a `Get`/`Calc`/`Search` — there is no setter and no field — so it is worked
out from the job states when the save loads. Finishing the jobs is the whole
edit, and the level follows on its own.

**Ginormosia** (`Map_200000`) keeps its own progress,
and unlike the boards it really is stored, so it gets written directly:

* **Discover every camp** — adds all ten camps (`map200000_camp_000`..`009`).
  These are the fast-travel points (`ExeCmd_DiscoveryCamp`), *not* the fog.
* **Reveal every shrine** — puts all twenty shrines on the map and marks them
  cleared. Found and cleared are separate flags and both get set.
* **Unlock everything** — both at once. No ranks: those are progression and
  stay yours to set.
* **Eye Towers** — section for the eye towers, it removes the fog that
  covers the map.

```
python fli.py towers <save>                    # what is lit
python fli.py towers <save> --unlock           # light them all
python fli.py towers <save> --tower 7          # just tower 7
python fli.py towers <save> --tower 7 --off    # and back off again
```

Lighting a tower writes two things and the editor writes both, because that is
what the game does: the tower's flag in `GDSGlobalSyncBitFlag`, and the
Ginormosia warp point (`lt_200000_*`) that comes with it. **Confirmed in game**
— a save edited this way loads with the map fully uncovered.

The pairing is one to one — the before/after saves either side of lighting
tower 4 differ in exactly one warp record, `lt_200000_326` going `0x00` →
`0x50`. What the save does not say is *which* record goes with *which* eye. The
`lt_200000_*` numbers are stable inside one save file but share nothing between
save files (three saves here hold 15, 16 and 18 of them with no id in common),
and the list also covers villages and camps, so it cannot be lined up against
the fifteen eyes by position or by count.

So the two buttons differ in what they can reach. **Unlock every map area**
opens every warp point on the map along with all fifteen flags, and that is the
combination confirmed in game. **Apply to this eye** writes that eye's flag on
its own, which is the half that clears the fog; its warp point stays shut until
the whole-map button runs.

This one was measured rather than guessed: two saves taken either side of a
single in-game action, diffed down to only the bytes that moved. A save from
before and after activating one tower differs in eight places, and two of them
are the ones above.

**Per-zone ranks.** Each of the fifteen open-world zones carries its own rank,
so the **Zone rank** row edits them one at a time: pick a zone in the table,
choose a rank, and press **Apply to this zone** — or **Apply to every zone** to
give them all the same one. Selecting a zone fills the boxes with what it
currently holds, so you can see where you are before changing it.

Leave the **points** box blank and the points are set to whatever that rank
needs, keeping the two stored numbers consistent. Type a number instead to sit
part-way through a rank.

Ranks run **1 to 7**. Seven is the game's own maximum: `GDSAreaRankPoint` gives
the thresholds (100, 900, 2000, 5000, 12000, 130000) and `GDSAreaRankLevel`
stops at seven, so a higher rank would send the game's lookup past the end of
its table. The window will not offer one; `--over-max` on the command line will,
if you want to find out what happens.

The area and shrine tables show the real in-game names in whichever language
the toolbar is set to — *West Dryridge Desert*, *Jo'ee Shrine*, and so on.

```
python fli.py boards     <save>                 # what each board looks like
python fli.py boards     <save> --complete all
python fli.py ginormosia <save>                 # areas, ranks and shrines
python fli.py ginormosia <save> --open                       # uncover the map
python fli.py ginormosia <save> --unlock                    # + camps + shrines
python fli.py ginormosia <save> --rank 5                    # every zone's rank
python fli.py ginormosia <save> --area 3 --rank 5           # just that one
python fli.py ginormosia <save> --area map200000_area007 --rank 2 --points 555
python fli.py ginormosia <save> --area all --points 0       # ranks left alone
```

## Item and Life names

The save only stores ids (`ics01000780`, `life0003`), so the editor ships the
game's own text tables in `data/fli_text.json.gz` — about 5 000 item, Life,
rank, character and map names plus item descriptions, in all nine languages
(`ja en fr it de es zh-Hans zh-Hant ko`). Names come from the pak, not from a
hand-written list, so they match the game exactly.

Nothing depends on the database: with the file missing every name is simply
blank and the editor keeps working.

To rebuild it (after a game update, say) point the builder at a
`pakchunk0-*.pak` or straight at the Android APK, with an Oodle decompressor
available — any UE4/UE5 install ships one:

```
python tools/build_textdb.py FANTASY-LIFE-i-v2.2.1.0-full-apkvision.apk ^
       --oodle C:\path\to\oo2core_8_win64.dll
```

`FLI_TEXT_DB` points the editor at a database somewhere else.

### The Dark Dragon exception

One set of rows in the shipped tables does not match the game: the fourteen
**Dark Dragon** weapons and Life tools are named the wrong way round. The id
the tables call *Dark Dragon Sword* is the one the game shows as **True** Dark
Dragon Sword, and vice versa. The editor swaps those names back on load
(`names.SWAPPED_NAMES`), so picking a name here gives you that item in game.

Two things say the tables are the odd one out rather than the game. Every
other pair in the game reads as you would expect — *Axe of Time* 550, *True
Axe of Time* 750 — and these fourteen are the only pairs where the "True" id
carries the **weaker** stat list; and a player who spawned both and looked in
game read them back the other way round. The ids the save stores are right,
so nothing about the swap touches a save file: only the label moves.

The Dark Dragon **shield** looks the same shape but armour carries no stat
list to check it against and nobody has read it off the game yet, so it is
left as the tables have it.


## Bulk fills

Seven bags are worth having in full, and the editor knows every id in each.
Materials and recipes come out of `data/fli_gear.json.gz`, built from the
game’s own item tables — the name database cannot supply those, since it is
keyed by things that have a name and recipes have none. Nothing built a list
for the four equipment bags or the craft bag, so those ids are read off the
name database instead, which is the safe direction: an item the game has no
word for is a table row a player never sees.

| Bag | Ids | Where the list comes from | Slots |
|---|---|---|---|
| Weapons | 117 | `iwp` ids the game names | 1 099 |
| Life tools | 140 | `ilt` ids the game names | 1 099 |
| Shields | 19 | the `iam` ids the gear database marks as shields | 400 |
| Armour | 641 | every other named `iam` id | 1 099 |
| Craft items | 863 | `icf` + `ico` ids the game names | 2 048 |
| Materials | 486 | `GDSItemMaterialData` | 999 |
| Recipes | 2 011 | `GDSItemRecipeData` | 2 048 |

Every list fits its bag with room to spare. The blank placeholder rows the
tables carry (`irp00000000` and friends) are left out, and so are the unnamed
`iwp00000000` / `ilt00000000` / `iam00000007` slots the game itself parks in a
bag to mean “nothing equipped” — filling those would hand you a row of items
with no name.

The list is keyed on the ids **English** names, not on the union of all nine
languages, for two reasons. It is the table the browser build is guaranteed to
have loaded, so both editors derive the same list and the parity test can hold
them to it byte for byte. And it is the better data: the only rows English
leaves out are untranslated placeholders — `ico01070200` and `ico01080200` are
two prison tiles the Japanese table still marks `(仮)`, *provisional*.

**Equipment has no stack.** Every piece is its own record, so on the four
equipment bags the quantity is *how many copies of each item* rather than a
stack size, and the fill takes a **grade** and the **Super OP Weapon Mode**
tick box with it. The grade dropdown leads with *best grade for each item*,
which is the right answer for a whole bag at once: one grade across 117
different weapons leaves 68 of them reading zero, and the panel says how many
as soon as you pick one. Craft items, materials and recipes stack, so they take
only a number — a record that is nothing but a count has nowhere to keep a
grade.

```
python fli.py give-all <save> --what materials --qty 999
python fli.py give-all <save> --what recipes
python fli.py give-all <save> --what crafts --qty 999
python fli.py give-all <save> --what weapons --title 5 --super-op
python fli.py give-all <save> --what armour --qty 2
python fli.py set-qty  <save> --container 7 --qty 999
```

In the GUI a **Give every ...** panel sits under the slot editor and follows
the container dropdown: it names the bag on screen, is off screen entirely on
the bags with no fill, and only shows the grade and the tick box where they
mean something. Running it again tops up what is already there instead of
adding a second copy, so it is safe to repeat — and if you asked for a grade or
for Super OP, the pieces already in the bag are brought up to it rather than
being left behind at their old one.

**Set every quantity here...** appears on any bag whose items stack, and asks
for the number. It skips equipment on purpose: a piece of gear has no quantity,
and a number written into one of those records lands on its crafting grade
instead — which is the bug [Gear grades](#gear-grades) is about.


## Gear grades

A weapon's attack is **not stored in the save**. The item record carries a
*title* — the crafting grade: Ordinary, Fine, Notable, Supreme, Legendary — and
the game reads the item's attack out of its own table at that grade. Every
weapon has five entries, one per grade, and the grades an item cannot be made
at hold a filler the game displays as **0**.

Most items are made at three consecutive grades. Story rewards are the trap:
the *True Sword of Time* has `1, 1, 1, 1, 750` — it only exists at
**Legendary**. Spawn it at any other grade and the game shows Attack 0, which
is exactly what an editor that writes a quantity into an equipment record ends
up doing, because equipment has no quantity field and those bytes are the
title.

So the editor picks the best grade the item actually has stats for, shows what
each grade is worth, and lets you choose:

```
python fli.py give <save> --id iwp02000220
  container 1 (Weapons) slot 10 -> iwp02000220 x1  True Sword of Time
    title Legend  ->  attack 750
```

`fix-gear` walks a save and repairs anything spawned before this was understood
— a grade with no stats, or a piece filed in the wrong bag (armour and shields
are separate containers, and armour in the shield bag never appears in game):

```
python fli.py fix-gear <save> --dry-run
  iwp05000190: Rag reads 1 -> Legend reads 440
  iwp02000220: Rag reads 1 -> Legend reads 750
  iam01008210 belongs in [4] Armour
```

It only moves a grade when the item has a strictly better one, so gear you
crafted in game is left alone.

The stat tables live in `data/fli_gear.json.gz`, built from the pak like the
name database:

```
python tools/build_geardb.py FANTASY-LIFE-i-v2.2.1.0-full-apkvision.apk ^
       --oodle C:\path\to\oo2core_8_win64.dll
```

Life tools are in there too, out of `GDSItemLifeToolsData` — same five-entry
shape, so a *True Axe of Time* is `1, 1, 1, 1, 750` just like the sword and
reads **0 power** at any other grade.

Armour stats are not in there yet: armour ids appear in so many other rows of
`GDSItemArmorData` that the row cannot be pinned reliably, so armour is spawned
untitled — which is what the game itself writes on every piece of armour it
hands out.


## Super OP Weapon Mode

The gear in the "super OP" saves going round is not spawned gear with a big
number written into it. It is gear that has been through the **Aging Altar**
in the Plant Dungeon, and the save records three separate things about it — all inside the equipment
extension, all of which this editor used to carry through untouched:

| Field | What it does |
|---|---|
| `itemTitle` | the grade the stats are read at — Legendary or nothing, on a story weapon or tool |
| `ripeningAge` | the vintage in years, the *Aging: 1000-year vintage* line |
| `grantSkillId` | three `es_*` equipment skills the Altar rolls |
| `quality` | `EItemQualityType`, 0–3 |

Tick **Super OP Weapon Mode** and all four are written together: the best grade
the item actually has stats for, a 1000-year vintage (what the Altar itself
produces), top quality, and the three skills the game's own best-roll table
gives that kind of gear. The line beside the tick box spells out what it will
write before you press anything.

```
python fli.py give <save> --id ilt01000120 --super-op
  container 2 (Life tools) slot 12 -> ilt01000120 x1  True Axe of Time
    title Legend  ->  power 750
    aged  1000-year vintage, quality 3
    skills es_felling_up05, es_charge_time_reduce02, es_spot_attack_up04
```

The vintage is editable on its own as well — the **aged** box in the window, or
`--age N` on the command line — so a piece can be aged without the rest.

The skill rolls come from `GDSAddSkillLotTable`, one table per kind of gear:
an axe gets the woodcutting roll, a pickaxe the mining one, a sword the attack
one. Body armour gets **no** skills, because the Altar has no category for it —
the sixteen it does have are the weapon, Life tool and shield kinds.


## The wallet

Three of the game's `ECurrencyType` counters are editable, all found by the
shape of the player record rather than by fixed offsets, so they stay right
wherever you happen to be standing:

| Shown as | Enum | Where |
|---|---|---|
| Dosh | `Rich` | in the player record, after the map and warp names |
| Celestia's Gift | `GoddessSeed` | a short run of counters at the end of that record |
| Cashnuts | `SweetChestnut` | Ginormosia's acorns, two slots along from the Gift |

```
python fli.py money <save>                              # show all three
python fli.py money <save> --set 999999                 # Dosh
python fli.py money <save> --gift 9999 --cashnuts 999
```

The Character tab has a box each. Golden Celestia's Gift sits between the two
in the same run and is deliberately left out — it is not a currency you spend.

Both of the non-Dosh fields were confirmed against a save whose amounts the
player read off the game (99,999,999 and 476), which is the only way to be sure
of a counter with no landmark next to it. The remaining `ECurrencyType` entries
are in that run too but are not labelled here, because guessing which is which
without a number to check against is how an editor corrupts a save.


## Money

Dosh sits in the player record at the head of the payload, right after the
current map and warp-point names — so its offset **moves when you change
location**, and the editor locates it by the shape of the record rather than by
a fixed offset. `fli.py money` and the GUI's Dosh box both go through that
locator; there is nothing to hunt for.

Verified against the game: an amount written here is the amount the game shows
on the next load.

## Finding a value that is not mapped yet

For anything still unmapped, the hunter narrows it down in a couple of minutes:

1. Note the value the game shows you, then save in game.
2. `python fli.py hunt <save> --value <amount>` → a list of candidate offsets.
3. Change it in game, save again.
4. `python fli.py hunt <save> --value <new amount>` → the list shrinks.
5. Repeat until one offset is left, then
   `python fli.py poke <save> --at 0x<offset> --type u32 --value 9999`.

The GUI's *Find / Edit values* tab does the same thing with buttons, and drops
the offset straight into the write box once a single candidate remains.

## Safety

* Every write keeps a timestamped `.bak` unless you pass `--no-backup`.
* The MD5 the game checks is rebuilt on every save; a save the editor writes
  loads exactly like one the game wrote.
* Loading refuses a save whose MD5 does not match (pass `--no-verify` to force
  it) — that check catches a corrupt or truncated dump before you edit it.
* Keep your own copy of the original save somewhere the editor never touches.

## Layout

```
flisave/codec.py     AES-256-ECB + zlib + MD5 trailer container
flisave/gvas.py      UE5 GVAS header and the LEVEL5 sub-header
flisave/stream.py    UE archive primitives (FString etc.)
flisave/items.py     item container parser / serialiser
flisave/gear.py      per-grade equipment stats (reads data/fli_gear.json.gz)
flisave/lives.py     per-Life arrays
flisave/world.py     bulletin boards and Ginormosia
flisave/character.py the character block: name, HP/SP, current Life
flisave/hunt.py      progressive value hunting
flisave/names.py     name/description lookup (reads data/fli_text.json.gz)
flisave/icons.py     icon lookup (reads data/icons/)
flisave/save.py      high-level SaveFile facade
flisave/pak.py       UE pak reader          } only needed to (re)build the
flisave/oodle.py     Oodle decompression    } name database and the icons,
flisave/uasset.py    cooked package header  } never to edit a save
flisave/gamedata.py  the game's text DataTables
flisave/geardata.py  the equipment tables, for the gear database builder
flisave/texture.py   cooked UTexture2D reader
fli.py               command line
fli_gui.py           the editor window
tools/               build_textdb.py, build_geardb.py, build_icons.py
data/                the shipped name database and icons
docs/FORMAT.md       format documentation
```

## Help and troubleshooting

Anything at all — a save that will not open, an edit the game does not take, a
platform not covered above, or something you want the editor to do:

* **Discord** — DM **`twistedfeels`**
* **Telegram** — [**join the group**](https://t.me/+l0dNvVTtnHIxZmNk)

Ask in either. If it is a save that will not load, say which platform it came
off and paste what `python fli.py info <save>` prints — that is usually enough
to spot the problem straight away.
