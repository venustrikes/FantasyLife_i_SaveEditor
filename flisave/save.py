"""High level save-file object: load, inspect, edit, write back."""
from __future__ import annotations

import datetime
import os
import shutil
import struct
import time
from typing import Iterable, List, Optional, Tuple

from .codec import SaveContainer, SaveCodecError
from .gvas import GvasHeader
from .items import (ItemSection, ItemRecord, EMPTY, _fstring_len, heal_core_names,
                    category_for as _items_category)
from .lives import LifeSection
from .world import (BoardSection, HugeMap, SyncFlags, TravelPoints, BOARDS,
                    BOARD_BY_KEY, TOWER_COUNT, HUGEMAP_ID, tower_text_key)
from . import character as _character
from . import names as _names

# The player record at the head of the body finishes with
#     FString "None" | uint32 dosh | uint32 ? | FDateTime saved | FDateTime made
# The FStrings ahead of it are map names, so the record's length moves with the
# player; the money field is located by that tail, never by a fixed offset.
_MONEY_ANCHOR = b"\x05\x00\x00\x00None\x00"
_MONEY_WINDOW = 0x4000        # how far into the body to look for it

# The player record carries on past the Dosh, and a short run of the other
# ECurrencyType counters sits at the end of it:
#
#   uint32 dosh | uint32 ? | FDateTime saved | FDateTime made | uint32 x3
#   FString current map | 32 bytes | uint32 x5 | FString ...
#
# The map name in the middle is what makes this move, so the run is walked to
# rather than measured from the Dosh.  Only the two counters below are
# confirmed against a save whose amounts the player read off the game.
_CURRENCY_SKIP = 36           # Dosh -> the map name that follows it
_CURRENCY_PAD = 32            # that map name -> the counters
_CURRENCY_RUN = 5             # counters before the next FString

CURRENCIES = {
    # name          slot  what the game calls it
    "gift": (0, "Celestia's Gift"),        # ECurrencyType::GoddessSeed
    "cashnuts": (2, "Cashnuts"),           # ECurrencyType::SweetChestnut
}

_TICKS_2015 = 635_500_000_000_000_000     # FDateTime ticks, 100 ns since year 1
_TICKS_2100 = 662_500_000_000_000_000


def _is_datetime(ticks: int) -> bool:
    return _TICKS_2015 <= ticks <= _TICKS_2100


def _from_ticks(ticks: int) -> Optional[datetime.datetime]:
    """An FDateTime (100 ns since year 1) as a datetime."""
    if not _is_datetime(ticks):
        return None
    return datetime.datetime(1, 1, 1) + datetime.timedelta(microseconds=ticks // 10)


def _fstring_ending_at(payload, end: int, longest: int = 160):
    """The FString that finishes at *end*, walking backwards.  ('', -1) if none."""
    for n in range(2, longest):
        start = end - 4 - n
        if start < 0:
            break
        if struct.unpack_from("<i", payload, start)[0] != n:
            continue
        raw = bytes(payload[start + 4:end])
        if raw[-1] == 0 and all(0x20 <= c < 0x7F for c in raw[:-1]):
            return raw[:-1].decode("ascii"), start
    return "", -1


_FMT = {
    "u8": ("<B", 1), "i8": ("<b", 1),
    "u16": ("<H", 2), "i16": ("<h", 2),
    "u32": ("<I", 4), "i32": ("<i", 4),
    "u64": ("<Q", 8), "i64": ("<q", 8),
    "f32": ("<f", 4), "f64": ("<d", 8),
}


class SaveFile:
    """A decoded Fantasy Life i save."""

    def __init__(self, container: SaveContainer, path: Optional[str] = None):
        self.container = container
        self.path = path
        self.payload = bytearray(container.payload)
        self.header = GvasHeader.parse(bytes(self.payload))
        self._items: Optional[ItemSection] = None
        self._items_error: Optional[str] = None
        self._lives: Optional[LifeSection] = None
        self._boards: Optional[BoardSection] = None
        self._hugemap: Optional[HugeMap] = None
        self._flags: Optional[SyncFlags] = None

    # ------------------------------------------------------------- lifecycle
    @classmethod
    def load(cls, path: str, *, verify: bool = True) -> "SaveFile":
        with open(path, "rb") as fh:
            blob = fh.read()
        return cls(SaveContainer.decode(blob, verify=verify), path)

    @classmethod
    def from_payload(cls, payload: bytes) -> "SaveFile":
        return cls(SaveContainer(payload=bytes(payload)))

    def write(self, path: Optional[str] = None, *, backup: bool = True,
              level: int = 9) -> str:
        """Re-encode and write.  Returns the path written."""
        target = path or self.path
        if target is None:
            raise ValueError("no output path given")
        self.flush_items()
        if backup and os.path.exists(target):
            stamp = time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(target, "%s.%s.bak" % (target, stamp))
        blob = SaveContainer(
            payload=bytes(self.payload),
            md5_valid_flag=self.container.md5_valid_flag,
            trailer_pad=self.container.trailer_pad,
        ).encode(level=level)
        with open(target, "wb") as fh:
            fh.write(blob)
        # Prove the file we just wrote decodes back to what we intended.
        check = SaveContainer.decode(blob)
        if check.payload != bytes(self.payload):
            raise SaveCodecError("verification failed: written save does not round-trip")
        return target

    def export_payload(self, path: str) -> int:
        with open(path, "wb") as fh:
            fh.write(self.payload)
        return len(self.payload)

    def import_payload(self, path: str) -> None:
        with open(path, "rb") as fh:
            self.payload = bytearray(fh.read())
        self.header = GvasHeader.parse(bytes(self.payload))
        self._items = None
        self._items_error = None
        self._lives = None
        self._boards = None
        self._hugemap = None
        self._flags = None

    # ----------------------------------------------------------------- items
    @property
    def items(self) -> Optional[ItemSection]:
        if self._items is None and self._items_error is None:
            try:
                self._items = ItemSection.parse(bytes(self.payload))
            except Exception as exc:            # keep the rest usable
                self._items_error = str(exc)
        return self._items

    @property
    def items_error(self) -> Optional[str]:
        self.items
        return self._items_error

    # ----------------------------------------------------------------- lives
    @property
    def lives(self) -> LifeSection:
        if self._lives is None:
            self._lives = LifeSection.parse(bytes(self.payload))
        return self._lives

    def life_table(self):
        return self.lives.table(bytes(self.payload))

    def set_life_field(self, life_id: str, field: str, value: int) -> None:
        """Write one named per-Life field (level, exp, rank, pa)."""
        for arr in self.lives.arrays:
            if not any(n == field for n, _o, _c in arr.fields):
                continue
            for e in arr.entries:
                if e.life_id == life_id:
                    arr.write(self.payload, e, field, value)
                    return
        raise KeyError("no array carries field %r for %s" % (field, life_id))

    def flush_items(self) -> None:
        """Write pending item edits back into the payload."""
        # Ginormosia sits behind the item block, so it has to be written at its
        # current offsets before the item splice moves it.
        self.flush_world()
        self.flush_flags()
        sec = self._items
        if sec is None:
            return
        blob = sec.pack()
        old = bytes(self.payload[sec.start:sec.end])
        if blob == old:
            return
        self.payload[sec.start:sec.end] = blob
        sec.end = sec.start + len(blob)
        # every offset after the item block has moved
        self._lives = None
        self._boards = None
        self._hugemap = None
        self._flags = None

    def give_item(self, item_id: str, quantity: int = 1,
                  array_index: Optional[int] = None,
                  title: Optional[int] = None,
                  super_op: bool = False) -> ItemRecord:
        """Put *item_id* into an empty slot (or top up an existing stack).

        The container is the one the game itself would use, which for ``iam``
        means telling shields from the rest of the armour -- an item dropped in
        the wrong bag never appears in game.  Equipment never stacks: each piece
        is its own record, and *title* picks the grade its stats come from.

        With *super_op* a piece of equipment comes out the way a fully aged one
        does -- see :meth:`~flisave.items.ItemRecord.make_super_op`.
        """
        sec = self.items
        if sec is None:
            raise RuntimeError("item section unavailable: %s" % self._items_error)
        if array_index is None:
            arr = sec.array_for_item(item_id)
            if arr is None:
                raise ValueError(
                    "no container holds %r items; pass array_index explicitly"
                    % item_id[:3])
            array_index = arr.index
        for rec in sec.arrays[array_index].records:
            if rec.item_id == item_id and rec.stackable:
                rec.quantity = min(65535, rec.quantity + quantity)
                return rec
        rec = sec.first_empty(array_index)
        if rec is None:
            raise ValueError("container %d has no free slot" % array_index)
        rec.place(item_id, quantity, sec.next_instance_id(), title, super_op)
        return rec

    def give_every(self, kind: str, quantity: int = 1, *,
                   title: Optional[int] = None, super_op: bool = False) -> dict:
        """Put every item of one *kind* into the bag the game keeps it in.

        *kind* is one of :data:`flisave.gear.EVERY_KINDS`.  What *quantity*
        means depends on the bag, because the two shapes of record count
        differently: a stackable bag (materials, recipes, craft items) gets one
        record per id holding *quantity* of it, while equipment has no count at
        all -- every piece is its own record -- so there *quantity* is how many
        separate pieces of each item to leave in the bag.

        *title* is the grade each new piece is spawned at, or None for the best
        grade the item has stats for; *super_op* finishes it the way the Aging
        Altar does.  Both are ignored by a stackable bag, which has neither
        field.

        Running it twice does not fill the bag with a second copy of
        everything: a bag that already holds enough of an id is left alone.
        Asking for a *title* or for *super_op* does re-grade the pieces already
        there, since that is the state the caller just asked every one of them
        to be in.

        Returns ``{"added", "topped_up", "no_room", "total", "container"}``.
        """
        from . import gear as _gear
        sec = self.items
        if sec is None:
            raise RuntimeError("item section unavailable: %s" % self._items_error)
        every = _gear.every(kind)
        if not every:
            # Which database is missing depends on the kind: materials and
            # recipes come from the gear database, the rest from the names.
            raise RuntimeError(
                "no %s list to fill from -- rebuild the databases with "
                "tools/build_textdb.py and tools/build_geardb.py" % kind)

        index = _items_category(every[0])
        if index is None or index >= len(sec.arrays):
            raise RuntimeError("no bag holds %r items" % every[0][:3])
        bag = sec.arrays[index]
        quantity = max(1, int(quantity))
        equipment = bool(bag.records) and bag.records[0].equipment
        here: dict = {}
        for rec in bag.records:
            if not rec.empty:
                here.setdefault(rec.item_id, []).append(rec)

        # Both of these are walked once rather than re-derived per placement:
        # ``first_empty`` and ``next_instance_id`` each scan the whole section,
        # and a fill of two thousand ids calls them two thousand times.  The
        # ids handed out are the same ones the repeated scan would produce.
        free = (r for r in bag.records if r.empty)
        instance = sec.next_instance_id()

        added = topped = no_room = 0
        for item_id in every:
            have = here.get(item_id) or []
            if equipment:
                if title is not None or super_op:
                    for rec in have:
                        if title is not None:
                            rec.item_title = title
                        if super_op:
                            rec.make_super_op(keep_title=title is not None)
                        topped += 1
                want = quantity - len(have)
            else:
                if have and have[0].quantity < quantity:
                    have[0].quantity = quantity
                    topped += 1
                want = 0 if have else 1
            for _ in range(want):
                rec = next(free, None)
                if rec is None:
                    no_room += 1
                    continue
                rec.place(item_id, quantity, instance, title, super_op)
                instance += 1
                added += 1
        return {"added": added, "topped_up": topped, "no_room": no_room,
                "total": len(every), "container": index}

    def set_every_quantity(self, array_index: int, quantity: int) -> int:
        """Set the stack size of everything in one bag.  Returns how many changed.

        Only bags that stack are touched: equipment has no quantity, and writing
        one into an equipment record sets its crafting grade instead.
        """
        sec = self.items
        if sec is None:
            raise RuntimeError("item section unavailable: %s" % self._items_error)
        changed = 0
        for rec in sec.arrays[array_index].records:
            if rec.empty or not rec.stackable or rec.quantity == quantity:
                continue
            rec.quantity = quantity
            changed += 1
        return changed

    def repair_records(self, *, apply: bool = True) -> List[str]:
        """Heal item records an editor blind to ``extra_name`` overwrote.

        This is the damage that stops a save loading at all rather than merely
        looking wrong, so it runs on the raw payload before anything tries to
        parse the item block -- by the time the parser gets there the record
        lengths have already stopped adding up.  See
        :func:`flisave.items.heal_core_names`.
        """
        healed, notes = heal_core_names(bytes(self.payload))
        if notes and apply:
            self.payload = bytearray(healed)
            self._items = None
            self._items_error = None
            self._lives = None
            self._boards = None
            self._hugemap = None
            self._flags = None
        return notes

    def repair_gear(self, *, apply: bool = True) -> List[str]:
        """Put earlier-spawned gear right: correct bag, and a title with stats.

        Two things an editor can get wrong leave a piece of gear looking broken
        in game rather than missing: filing it in a bag the game shows under a
        different tab, and giving it a title the item has no stats at, which
        reads as zero.  Both are fixable in place.  Gear the game itself wrote
        is left alone -- untitled is normal and means "no crafting grade".
        """
        from . import gear as _gear
        sec = self.items
        if sec is None:
            raise RuntimeError("item section unavailable: %s" % self._items_error)
        db = _gear.get()
        notes: List[str] = []

        for rec in list(sec.records):
            if rec.empty or not rec.equipment:
                continue
            want = _items_category(rec.item_id)
            if want is not None and want != rec.array_index and want < len(sec.arrays):
                free = sec.first_empty(want)
                if free is None:
                    notes.append("%s: [%d] %s is full, left where it is"
                                 % (rec.item_id, want, sec.arrays[want].label))
                elif apply:
                    # Being in the wrong bag is proof this record came from the
                    # editor and not from the game, so its title came from a
                    # quantity rather than from crafting: start it over.
                    iid, inst = rec.item_id, rec.instance_id
                    rec.clear()
                    free.place(iid, 1, inst)
                    notes.append("%s moved to [%d] %s slot %d, grade %s"
                                 % (iid, want, sec.arrays[want].label,
                                    free.index, free.title_name))
                    rec = free
                else:
                    notes.append("%s belongs in [%d] %s"
                                 % (rec.item_id, want, sec.arrays[want].label))

            now = db.attack(rec.item_id, rec.item_title)
            if now is None or now > db.sentinel:
                continue                       # no stat list, or already fine
            best = db.best_title(rec.item_id)
            gain = db.attack(rec.item_id, best)
            if gain is None or gain <= db.sentinel or best == rec.item_title:
                continue
            notes.append("%s: %s reads %d -> %s reads %d"
                         % (rec.item_id, rec.title_name, now,
                            db.titles[best], gain))
            if apply:
                rec.item_title = best
        return notes

    # ----------------------------------------------------------------- world
    @property
    def boards(self) -> BoardSection:
        """Every bulletin-board job, grouped by settlement."""
        self.flush_items()
        if self._boards is None:
            self._boards = BoardSection.parse(bytes(self.payload))
        return self._boards

    @property
    def ginormosia(self) -> Optional[HugeMap]:
        """Ginormosia's area ranks, camps and shrines.  None if absent."""
        self.flush_items()
        if self._hugemap is None:
            self._hugemap = HugeMap.parse(bytes(self.payload))
        return self._hugemap

    def flush_world(self) -> None:
        """Write pending Ginormosia edits back into the payload.

        Board edits go straight into the payload -- they only ever change one
        byte -- so only Ginormosia needs splicing back, and it can change
        length because the camp and shrine lists grow.
        """
        hm = self._hugemap
        if hm is None:
            return
        blob = hm.pack()
        if blob == bytes(self.payload[hm.start:hm.end]):
            return
        self.payload[hm.start:hm.end] = blob
        hm.end = hm.start + len(blob)

    @property
    def sync_flags(self) -> Optional[SyncFlags]:
        """The GDSGlobalSyncBitFlag table, which is where the eye towers live.

        It sits ahead of the item block, so nothing the editor does to items or
        to the character name can move it.
        """
        if self._flags is None:
            self._flags = SyncFlags.parse(bytes(self.payload))
        return self._flags

    def flush_flags(self) -> None:
        """Write pending flag edits back.  The table is fixed-size."""
        f = self._flags
        if f is None:
            return
        blob = f.pack()
        if blob != bytes(self.payload[f.base:f.base + len(blob)]):
            self.payload[f.base:f.base + len(blob)] = blob

    def tower_rows(self, language: str = "en"):
        """One row per eye tower: its name and whether it has been lit."""
        f = self.sync_flags
        if f is None:
            return []
        lit = f.towers
        return [{"number": n + 1,
                 "name": self.place_name(tower_text_key(n + 1), language),
                 "lit": lit[n]} for n in range(TOWER_COUNT)]

    def set_tower(self, number: int, on: bool = True) -> bool:
        """Light or unlight one eye tower.  Returns True if it changed."""
        f = self.sync_flags
        if f is None:
            raise RuntimeError("this save has no sync-flag table")
        changed = f.set_tower(number, on)
        self.flush_flags()
        return changed

    @property
    def travel_points(self) -> TravelPoints:
        """The ``lt_`` warp-point records."""
        return TravelPoints.parse(bytes(self.payload))

    def unlock_towers(self) -> dict:
        """Light every eye tower, which is what clears the open-world map.

        Activating a tower in game writes two things, and this writes both:
        the tower's own flag in the sync table, and the Ginormosia warp point
        that comes with it.  Confirmed in game -- a save edited this way loads
        with the clouds gone.
        """
        f = self.sync_flags
        if f is None:
            raise RuntimeError("this save has no sync-flag table")
        lit = f.unlock_towers()
        self.flush_flags()
        opened = self.travel_points.open_all(self.payload, HUGEMAP_ID)
        return {"towers": lit, "travel_points": opened}

    def complete_board(self, key: str) -> int:
        """Finish every job on one bulletin board.  Returns records changed.

        The board's level is worked out by the game from these job states when
        the save loads, so there is nothing else to write for it to go up.
        """
        return self.boards.complete(self.payload, key)

    def complete_all_boards(self) -> dict:
        """Finish every job on every bulletin board."""
        return self.boards.complete_all(self.payload)

    def set_area_rank(self, which, rank: int, points: Optional[int] = None,
                      allow_over_max: bool = False):
        """Set one open-world area's rank.  *which* is its number or its id."""
        hm = self.ginormosia
        if hm is None:
            raise RuntimeError("this save has no Ginormosia block")
        return hm.set_area_rank(which, rank, points, allow_over_max)

    def unlock_ginormosia(self, *, open_zones: bool = True, camps: bool = True,
                          reveal: bool = True, clear: bool = True,
                          ranks: bool = False, rank: int = None) -> dict:
        """Open Ginormosia up: uncover the map, add the camps and the shrines.

        Ranks are progression rather than map cover, so they are **not** touched
        unless *ranks* or *rank* asks for it -- uncovering a zone only needs it
        to have scored at all.  Returns what changed, so a caller can report it
        rather than guess.
        """
        hm = self.ginormosia
        if hm is None:
            raise RuntimeError("this save has no Ginormosia block")
        from .world import MAX_RANK
        out = {"opened": [], "camps": [], "ranks": 0,
               "revealed": [], "cleared": 0}
        if open_zones:
            out["opened"] = hm.open_areas()
        if camps:
            out["camps"] = hm.unlock_camps()
        if ranks or rank is not None:
            out["ranks"] = hm.set_ranks(MAX_RANK if rank is None else rank)
        if reveal:
            out["revealed"] = hm.reveal_shrines()
        if clear:
            out["cleared"] = hm.clear_shrines()
        return out

    # ------------------------------------------------------------- character
    @property
    def character(self):
        """Name, vitals and current Life, located by shape.  None if absent."""
        self.flush_items()
        return _character.find(bytes(self.payload))

    def set_name(self, name: str) -> None:
        """Rename the character.  The payload grows or shrinks to suit."""
        ch = self.character
        if ch is None:
            raise RuntimeError("this save has no character block")
        if not name.strip():
            raise ValueError("the character needs a name")
        blob = _character.pack_name(name)
        self.payload[ch.name_offset:ch.name_offset + ch.name_bytes] = blob
        self._items = None            # every offset behind the name has moved
        self._items_error = None
        self._lives = None
        self._boards = None
        self._hugemap = None
        self._flags = None

    def set_vital(self, field: str, value: int) -> None:
        """Write one of hp / hp_max / sp / sp_max."""
        ch = self.character
        if ch is None:
            raise RuntimeError("this save has no character block")
        if field not in _character.FIELDS:
            raise KeyError("no vital called %r" % field)
        self.write_value(ch.vital_offset(field),
                         max(0, min(0xFFFFFFFF, int(value))), "u32")

    # ----------------------------------------------------------------- money
    def money_offset(self) -> Optional[int]:
        """Where this payload keeps the Dosh (``ECurrencyType::Rich``) field.

        The two FStrings in front of it are the current map and warp point, so
        the field slides as the player moves; it is found by the shape of the
        record around it rather than by a fixed offset.
        """
        self.flush_items()
        data = bytes(self.payload)
        start = self.header.body_offset
        end = min(len(data), start + _MONEY_WINDOW)
        i = start
        while True:
            i = data.find(_MONEY_ANCHOR, i, end)
            if i < 0:
                return None
            off = i + len(_MONEY_ANCHOR)
            if off + 24 <= len(data):
                saved, made = struct.unpack_from("<QQ", data, off + 8)
                if _is_datetime(saved) and _is_datetime(made) and made <= saved:
                    return off
            i += 1

    def currency_offset(self, kind: str = "gift") -> Optional[int]:
        """Where this payload keeps one of the non-Dosh currencies.

        Found the same way as the Dosh: by walking the shape of the player
        record rather than by a fixed offset, because the map name sitting in
        the middle of it changes length as the player moves.
        """
        if kind not in CURRENCIES:
            raise KeyError("no currency called %r" % kind)
        money = self.money_offset()
        if money is None:
            return None
        data = bytes(self.payload)
        span = _fstring_len(data, money + _CURRENCY_SKIP)     # the map name
        if span is None:
            return None
        run = money + _CURRENCY_SKIP + span + _CURRENCY_PAD
        # The run is followed by an FString; without that this is not the place.
        if _fstring_len(data, run + _CURRENCY_RUN * 4) is None:
            return None
        return run + CURRENCIES[kind][0] * 4

    def currency(self, kind: str = "gift") -> Optional[int]:
        off = self.currency_offset(kind)
        return None if off is None else self.read_value(off, "u32")

    def set_currency(self, kind: str, amount: int) -> int:
        """Set one of the non-Dosh currencies.  Returns the offset written."""
        off = self.currency_offset(kind)
        if off is None:
            raise RuntimeError("could not find the %s field in this save"
                               % CURRENCIES[kind][1])
        self.write_value(off, max(0, min(0xFFFFFFFF, int(amount))), "u32")
        return off

    def timestamps(self):
        """(last saved, character created), from the player record."""
        off = self.money_offset()
        if off is None:
            return None, None
        saved, made = struct.unpack_from("<QQ", self.payload, off + 8)
        return _from_ticks(saved), _from_ticks(made)

    def location(self):
        """(current map, last warp point) - the two names before the money."""
        off = self.money_offset()
        if off is None:
            return "", ""
        warp, start = _fstring_ending_at(self.payload, off - len(_MONEY_ANCHOR))
        map_name = _fstring_ending_at(self.payload, start)[0] if start > 0 else ""
        return map_name, warp

    @property
    def money(self) -> Optional[int]:
        off = self.money_offset()
        return None if off is None else self.read_value(off, "u32")

    def set_money(self, amount: int) -> int:
        """Set the Dosh amount.  Returns the offset written."""
        off = self.money_offset()
        if off is None:
            raise RuntimeError("could not find the Dosh field in this save")
        self.write_value(off, max(0, min(0xFFFFFFFF, int(amount))), "u32")
        return off

    # ----------------------------------------------------------------- names
    @property
    def db(self):
        return _names.get()

    def item_name(self, item_id: str, language: str = "en") -> str:
        return self.db.resolve(item_id, language) or ""

    def place_name(self, key: str, language: str = "en") -> str:
        """A map / area / shrine name from the text tables, or the key itself."""
        return self.db.resolve(key, language) or key

    def board_rows(self, language: str = "en"):
        """One row per bulletin board, with the settlement's own name."""
        rows = self.boards.table()
        for r in rows:
            r["name"] = self.place_name(r["map_id"], language)
        return rows

    def ginormosia_rows(self, language: str = "en"):
        """One row per Ginormosia area, with its in-game name."""
        hm = self.ginormosia
        if hm is None:
            return []
        return [{"area_id": a.area_id, "index": a.index,
                 "name": self.place_name(a.text_key, language),
                 "rank": a.rank, "points": a.points} for a in hm.areas]

    def shrine_rows(self, language: str = "en"):
        """One row per Ginormosia shrine, with its in-game name."""
        hm = self.ginormosia
        if hm is None:
            return []
        return [{"shrine_id": s.shrine_id,
                 "name": self.place_name(s.text_key, language),
                 "found": s.shrine_id in hm.found,
                 "cleared": bool(s.cleared)} for s in hm.shrines]

    def life_rows(self, language: str = "en"):
        """life_table() with the Life and rank names filled in."""
        db = self.db
        rows = self.life_table()
        for r in rows:
            r["name"] = db.life_name(r["life_id"], language) or r["life_id"]
            if "rank" in r:
                r["rank_name"] = db.life_rank_name(int(r["rank"]), language) or ""
        return rows

    # ---------------------------------------------------------------- search
    def find_value(self, value, kind: str = "u32", *, align: int = 1,
                   start: int = 0, end: Optional[int] = None) -> List[int]:
        self.flush_items()
        fmt, size = _FMT[kind]
        needle = struct.pack(fmt, value)
        data = bytes(self.payload)
        end = len(data) if end is None else end
        hits, i = [], start
        while True:
            i = data.find(needle, i, end)
            if i < 0:
                break
            if (i - start) % align == 0:
                hits.append(i)
            i += 1
        return hits

    def read_value(self, offset: int, kind: str = "u32"):
        self.flush_items()
        fmt, size = _FMT[kind]
        return struct.unpack_from(fmt, self.payload, offset)[0]

    def write_value(self, offset: int, value, kind: str = "u32") -> None:
        # Commit any pending item edits first so the offset the caller is using
        # refers to the same bytes we are about to change.
        self.flush_items()
        fmt, size = _FMT[kind]
        struct.pack_into(fmt, self.payload, offset, value)
        self._items = None
        self._items_error = None
        self._lives = None
        self._boards = None
        self._hugemap = None
        self._flags = None

    def hexdump(self, offset: int, length: int = 128) -> str:
        self.flush_items()
        out = []
        data = bytes(self.payload[offset:offset + length])
        for i in range(0, len(data), 16):
            row = data[i:i + 16]
            txt = "".join(chr(c) if 0x20 <= c < 0x7F else "." for c in row)
            out.append("%08X  %-47s |%s|" % (offset + i, row.hex(" "), txt))
        return "\n".join(out)

    # ------------------------------------------------------------------ diff
    @staticmethod
    def diff(a: "SaveFile", b: "SaveFile", *, context: int = 0
             ) -> List[Tuple[int, bytes, bytes]]:
        """Byte ranges that differ between two payloads of equal length."""
        pa, pb = bytes(a.payload), bytes(b.payload)
        if len(pa) != len(pb):
            raise ValueError("payload sizes differ (%d vs %d); diff needs the "
                             "same save at two points in time" % (len(pa), len(pb)))
        runs, i, n = [], 0, len(pa)
        while i < n:
            if pa[i] != pb[i]:
                j = i
                gap = 0
                while j < n and (pa[j] != pb[j] or gap < 8):
                    gap = gap + 1 if pa[j] == pb[j] else 0
                    j += 1
                j -= gap
                lo = max(0, i - context)
                hi = min(n, j + context)
                runs.append((lo, pa[lo:hi], pb[lo:hi]))
                i = j
            i += 1
        return runs

    # ----------------------------------------------------------------- info
    def info(self) -> str:
        h = self.header
        lines = [
            "class            : %s" % h.save_class,
            "engine           : %s" % h.engine_version,
            "build id         : %s" % h.build_id,
            "l5 header        : magic=0x%08X version=%d flags=%d"
            % (h.l5_magic, h.l5_version, h.l5_flags),
            "custom versions  : %d" % len(h.custom_versions),
            "payload size     : %d bytes" % len(self.payload),
            "body offset      : 0x%X" % h.body_offset,
        ]
        lines.extend(_character.summary(self.character))
        off = self.money_offset()
        lines.append("dosh             : %s"
                     % ("%d  (at 0x%X)" % (self.read_value(off, "u32"), off)
                        if off is not None else "field not found"))
        try:
            lines.append("")
            lines.append(self.lives.summary(bytes(self.payload)))
        except Exception as exc:
            lines.append("per-Life arrays : unavailable (%s)" % exc)
        try:
            lines.append("")
            lines.append(self.boards.summary())
            hm = self.ginormosia
            lines.append("  " + (hm.summary() if hm is not None
                                 else "Ginormosia: block not found"))
        except Exception as exc:
            lines.append("world sections  : unavailable (%s)" % exc)
        sec = self.items
        if sec is not None:
            lines.append("")
            lines.append(sec.summary())
        elif self._items_error:
            lines.append("item section     : unavailable (%s)" % self._items_error)
        return "\n".join(lines)
