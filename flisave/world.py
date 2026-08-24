"""World progress: the bulletin boards, and Ginormosia.

Two unrelated systems live here because they are the two things the save keeps
about *places* rather than about the character.

Bulletin boards
---------------
Every settlement has a board -- ``Bacheca`` in the Italian UI, ``BulletinBoard``
in the executable -- that carries a list of small jobs and a level that rises as
they are finished.  The game calls the level a *rank*
(``GetBulletinBoardCurrentRank``, ``SearchBulletinBoardRankMax``) and the points
behind it *EXP* (``GetBulletinBoardTotalEXP``, ``CalcBulletinBoardNextNeedEXP``).

**Neither the rank nor the EXP is stored in the save.**  Every name the binary
has for them is a ``Get``/``Calc``/``Search`` -- there is no setter and no save
field -- so both are recomputed at load from the state of the individual jobs.
That is what makes "complete all quests" work: finish the jobs and the level
follows on its own.  (Contrast Ginormosia below, which *does* store its ranks;
this save format stores what it cannot recompute.)

A job is one record in the quest stream::

    FString id            "qsd_guild_quest_001"
    uint32  counter       0 on every board job seen so far
    uint8   state         see STATES
    uint32  flag          1 on every board job seen so far

``EBulletinBoardQuestType`` names seven boards -- ``Base, Kingdom, Tropica,
Swolean, Faraway`` plus two DLC ones -- and the five in a DLC-less save line up
exactly with the five ``qsd_`` id prefixes.  ``Base`` is the Base Camp
(``Map_000100``, *Quartier generale*), whose jobs are the ones prefixed
``qsd_guild_`` because the Base Camp is where the Guild sits.

The state byte was read off two saves of very different length: in a
far-progressed save 41 of the 61 Base Camp jobs are 255, in an early one only 2.
0/1/2 are the states of a job still in play, and 254/255 both look finished --
most likely "done, reward not collected" and "done".  The editor writes 255,
which is the value a completed job has in a save the game itself wrote.

Ginormosia
----------
The huge continent, ``Map_200000`` internally and ``HugeMap`` in the UI code.
Its progress sits in one self-contained block that starts with a magic number::

    uint32  0x106E6021
    uint32  area_count                      15
    areas x { FString id; uint8 rank; uint8 rank_shown; uint32 points }
    uint32  camp_count;    camps  x FString      unlocked camps
    uint32  found_count;   found  x FString      shrines discovered on the map
    uint32  shrine_count;  shrines x { FString id; uint32 cleared }

Ranks run 1..7.  ``GDSAreaRankPoint`` gives the points each rank needs -- 100,
900, 2000, 5000, 12000 and 130000 -- and a save with seven areas sitting at rank
7 has between 150000 and 160000 points in each, comfortably past that last
threshold.  The two rank bytes are equal in every record seen, so the editor
writes both.

``GDSCamp`` defines ten camps, ``map200000_camp_000``..``009``; the fifteen
areas are named ``HugeMap_01``..``15`` in the text tables and the twenty shrines
``Map_200000_013``..``032``.

The eye towers
--------------
The clouds over the open-world map are none of the above -- not the area ranks,
not the points, not the camps.  They lift when the player talks to a zone's
**eye tower**: fifteen of them, ``tower_001``..``tower_015``, each with its own
name (*Googlina*, *Googlbert*, ... *Googleph*).  The binary calls them towers
too: ``EFastTravelType::Tower``, ``EMapIconType::Tower``/``TowerGrayOut``,
``ETowerRankButtonType::Lock``/``Release``/``Unlock``.

A tower sets one byte.  ``GDSGlobalSyncBitFlag`` is a 121-entry table stored one
byte per flag, and the towers are ``flg_travelpoint_200000_01``..``_15`` at
indices 100..114::

    index 1        flg_guild_house_grade_up
    index 10-89    map_200000_zone001_00 .. zone015_05
    index 100-114  flg_travelpoint_200000_01 .. _15      <- the towers
    index 115-120  flg_enemy_village_01 .. _06

This was measured, not guessed: two saves taken either side of activating one
tower differ by exactly one byte in this array -- index 103, the tower for
``map200000_area004``, which is the area named in the travel-point record the
same save gained.

The array is found from the flag block's own header: the magic ``0x96622B31``
is followed by a ``uint32`` bank size, then that many bytes, and the table sits
2056 bytes into the bank that follows.  That holds on both builds seen here --
the December PC one and a June Switch save whose offsets are otherwise
completely different.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------- board jobs

STATE_HIDDEN = 0            # not offered yet
STATE_ACCEPTED = 1          # taken
STATE_OPEN = 2              # showing on the board
STATE_DONE_UNCLAIMED = 254  # finished; reward not picked up (best reading)
STATE_COMPLETE = 255        # finished

STATES = {
    STATE_HIDDEN: "hidden",
    STATE_ACCEPTED: "accepted",
    STATE_OPEN: "on the board",
    STATE_DONE_UNCLAIMED: "done (unclaimed)",
    STATE_COMPLETE: "complete",
}

#: states that count as finished
DONE = (STATE_DONE_UNCLAIMED, STATE_COMPLETE)


@dataclass
class Board:
    """One settlement's bulletin board."""
    key: str
    prefix: str
    quest_type: str          # EBulletinBoardQuestType member
    map_id: str              # text-table key for the place name
    name: str                # English fallback name


#: The five boards a save without DLC carries, in the enum's own order.
BOARDS: Tuple[Board, ...] = (
    Board("base", "qsd_guild_quest_", "Base",
          "Map_000100_000", "Base Camp"),
    Board("kingdom", "qsd_map100100_quest_", "Kingdom",
          "Map_100100_000", "Tunoco Coast"),
    Board("tropica", "qsd_map100400_quest_", "Tropica",
          "Map_100400_000", "Tropica Isles"),
    Board("swolean", "qsd_map100500_quest_", "Swolean",
          "Map_100500_000", "Swolean Island"),
    Board("faraway", "qsd_map100300_quest_", "Faraway",
          "Map_100300_000", "Faraway Island"),
)

BOARD_BY_KEY = {b.key: b for b in BOARDS}

# A board job id, with the 4-byte FString length in front of it.
_JOB_ID = re.compile(rb"qsd_[A-Za-z0-9_]+\x00")
_BODY = 9                   # uint32 counter | uint8 state | uint32 flag


@dataclass
class Job:
    """One record in the quest stream."""
    quest_id: str
    offset: int              # the FString length prefix
    body: int                # first byte after the id
    counter: int
    state: int
    flag: int

    @property
    def state_name(self) -> str:
        return STATES.get(self.state, "unknown (%d)" % self.state)

    @property
    def done(self) -> bool:
        return self.state in DONE


class BoardSection:
    """Every bulletin-board job in a payload, grouped by board."""

    def __init__(self, jobs: Dict[str, List[Job]], unknown: List[Job]):
        self.jobs = jobs
        self.unknown = unknown

    @classmethod
    def parse(cls, payload: bytes) -> "BoardSection":
        jobs: Dict[str, List[Job]] = {b.key: [] for b in BOARDS}
        unknown: List[Job] = []
        for m in _JOB_ID.finditer(payload):
            head = m.start() - 4
            if head < 0:
                continue
            # The id has to be a real FString, and a body has to follow it.
            if struct.unpack_from("<i", payload, head)[0] != m.end() - m.start():
                continue
            body = m.end()
            if body + _BODY > len(payload):
                continue
            counter, state, flag = struct.unpack_from("<IBI", payload, body)
            quest_id = m.group()[:-1].decode("ascii")
            job = Job(quest_id, head, body, counter, state, flag)
            for b in BOARDS:
                if quest_id.startswith(b.prefix):
                    jobs[b.key].append(job)
                    break
            else:
                unknown.append(job)
        return cls(jobs, unknown)

    # ------------------------------------------------------------- querying
    def board_jobs(self, key: str) -> List[Job]:
        if key not in BOARD_BY_KEY:
            raise KeyError("no bulletin board called %r" % key)
        return self.jobs[key]

    def counts(self, key: str) -> Dict[str, int]:
        js = self.board_jobs(key)
        return {
            "total": len(js),
            "complete": sum(1 for j in js if j.state == STATE_COMPLETE),
            "done": sum(1 for j in js if j.done),
            "open": sum(1 for j in js if j.state == STATE_OPEN),
            "hidden": sum(1 for j in js if j.state == STATE_HIDDEN),
        }

    def table(self) -> List[dict]:
        rows = []
        for b in BOARDS:
            row = {"key": b.key, "name": b.name, "map_id": b.map_id,
                   "quest_type": b.quest_type}
            row.update(self.counts(b.key))
            rows.append(row)
        return rows

    # ------------------------------------------------------------- editing
    def complete(self, payload: bytearray, key: str,
                 state: int = STATE_COMPLETE) -> int:
        """Finish every job on one board.  Returns how many records changed.

        The board's level is not stored anywhere -- the game works it out from
        these states when the save loads -- so this is the whole edit.
        """
        changed = 0
        for job in self.board_jobs(key):
            if job.state == state:
                continue
            payload[job.body + 4] = state
            job.state = state
            changed += 1
        return changed

    def complete_all(self, payload: bytearray,
                     state: int = STATE_COMPLETE) -> Dict[str, int]:
        return {b.key: self.complete(payload, b.key, state) for b in BOARDS}

    def summary(self) -> str:
        out = ["bulletin boards:"]
        for r in self.table():
            out.append("  %-9s %-16s %3d jobs  %3d complete  %3d on the board  "
                       "%3d hidden"
                       % (r["key"], r["name"], r["total"], r["complete"],
                          r["open"], r["hidden"]))
        if self.unknown:
            out.append("  (%d qsd_ records outside the five known boards)"
                       % len(self.unknown))
        return "\n".join(out)


# ------------------------------------------------------------- the eye towers

#: header magic in front of the flag banks
SYNC_MAGIC = bytes.fromhex("312b6296")
#: how far into the second bank the 121-entry sync table starts
SYNC_OFFSET = 2056
#: entries in GDSGlobalSyncBitFlag
SYNC_SIZE = 121

TOWER_FIRST = 100           # flg_travelpoint_200000_01
TOWER_COUNT = 15
FLAG_ON = 1                 # what the game writes for a set flag

ZONE_FIRST, ZONE_LAST = 10, 89
VILLAGE_FIRST, VILLAGE_COUNT = 115, 6


class SyncFlags:
    """``GDSGlobalSyncBitFlag`` -- one byte per flag, the eye towers included."""

    def __init__(self, base: int, data: bytearray):
        self.base = base
        self.data = data

    @classmethod
    def parse(cls, payload: bytes) -> Optional["SyncFlags"]:
        at = payload.find(SYNC_MAGIC)
        if at < 0 or at + 8 > len(payload):
            return None
        bank = struct.unpack_from("<I", payload, at + 4)[0]
        if not 0 < bank < len(payload):
            return None
        base = at + 8 + bank + SYNC_OFFSET
        if base + SYNC_SIZE > len(payload):
            return None
        return cls(base, bytearray(payload[base:base + SYNC_SIZE]))

    # -------------------------------------------------------------- towers
    @property
    def towers(self) -> List[bool]:
        """One entry per tower, ``tower_001`` first."""
        return [bool(self.data[TOWER_FIRST + i]) for i in range(TOWER_COUNT)]

    def set_tower(self, number: int, on: bool = True) -> bool:
        """Turn one tower on or off.  *number* is 1-based.  True if it moved."""
        if not 1 <= number <= TOWER_COUNT:
            raise ValueError("towers run 1..%d" % TOWER_COUNT)
        i = TOWER_FIRST + number - 1
        want = FLAG_ON if on else 0
        if self.data[i] == want:
            return False
        self.data[i] = want
        return True

    def unlock_towers(self) -> List[int]:
        """Light every tower.  Returns the ones that were not already on."""
        return [n for n in range(1, TOWER_COUNT + 1) if self.set_tower(n, True)]

    # ------------------------------------------------------------ the rest
    @property
    def zones(self) -> List[int]:
        return list(self.data[ZONE_FIRST:ZONE_LAST + 1])

    @property
    def villages(self) -> List[bool]:
        return [bool(self.data[VILLAGE_FIRST + i]) for i in range(VILLAGE_COUNT)]

    def pack(self) -> bytes:
        return bytes(self.data)

    def summary(self) -> str:
        on = [i + 1 for i, t in enumerate(self.towers) if t]
        return ("eye towers: %d of %d lit%s"
                % (len(on), TOWER_COUNT, "  (%s)" % ", ".join(map(str, on)) if on else ""))


#: a travel point record: FString id, then five bytes whose first is the state
_TRAVEL_ID = re.compile(rb"lt_(\d{6})_(\d+)\x00")
TRAVEL_BODY = 5
TRAVEL_ON = 0x50            # what the December PC build writes for an open one
HUGEMAP_ID = "200000"


@dataclass
class TravelPoint:
    """One ``lt_<map>_<n>`` record - a place the player can warp to."""
    point_id: str
    map_id: str
    offset: int             # the FString length prefix
    body: int               # first byte after the id
    state: int

    @property
    def open(self) -> bool:
        return self.state != 0


class TravelPoints:
    """Every ``lt_`` travel-point record in a payload."""

    def __init__(self, points: List[TravelPoint]):
        self.points = points

    @classmethod
    def parse(cls, payload: bytes) -> "TravelPoints":
        out = []
        for m in _TRAVEL_ID.finditer(payload):
            head = m.start() - 4
            if head < 0 or head + 4 > len(payload):
                continue
            if struct.unpack_from("<i", payload, head)[0] != m.end() - m.start():
                continue
            if m.end() + TRAVEL_BODY > len(payload):
                continue
            out.append(TravelPoint(m.group()[:-1].decode("ascii"),
                                   m.group(1).decode("ascii"),
                                   head, m.end(), payload[m.end()]))
        return cls(out)

    def for_map(self, map_id: str = HUGEMAP_ID) -> List[TravelPoint]:
        return [p for p in self.points if p.map_id == map_id]

    def open_value(self, map_id: str = HUGEMAP_ID) -> int:
        """Whatever this save already uses for an open point, else the default.

        A December PC save writes 0x50 and a June Switch one writes 1, so the
        save is asked rather than assumed.
        """
        seen = [p.state for p in self.for_map(map_id) if p.state]
        if not seen:
            seen = [p.state for p in self.points if p.state]
        # Most common wins, and a tie goes to the lower value: iterating a set
        # would leave the answer to hash order, which the TypeScript port has no
        # way to reproduce.
        return max(sorted(set(seen)), key=seen.count) if seen else TRAVEL_ON

    def open_all(self, payload: bytearray,
                 map_id: str = HUGEMAP_ID) -> List[str]:
        """Open every travel point on one map.  Returns the ones that changed."""
        value = self.open_value(map_id)
        changed = []
        for p in self.for_map(map_id):
            if p.state == value:
                continue
            payload[p.body] = value
            p.state = value
            changed.append(p.point_id)
        return changed

    def summary(self, map_id: str = HUGEMAP_ID) -> str:
        pts = self.for_map(map_id)
        return ("travel points on map %s: %d of %d open"
                % (map_id, sum(1 for p in pts if p.open), len(pts)))


def tower_text_key(number: int) -> str:
    """The text-table row holding a tower's name."""
    return "tower_%03d" % number


# ---------------------------------------------------------------- Ginormosia

HUGEMAP_MAGIC = 0x106E6021
MAX_RANK = 7

#: points each rank needs, from GDSAreaRankPoint (rank 1 is free)
RANK_POINTS = {1: 0, 2: 100, 3: 900, 4: 2000, 5: 5000, 6: 12000, 7: 130000}

#: A token score, kept only so :meth:`HugeMap.open_areas` has a default.  It
#: does **not** uncover the map: giving all fifteen areas a point was tried in
#: game and the clouds stayed put.  See the note on the fog below.
OPEN_POINTS = 1

#: every camp GDSCamp defines
ALL_CAMPS = tuple("map200000_camp_%03d" % i for i in range(10))


@dataclass
class Area:
    area_id: str
    rank: int
    rank_shown: int
    points: int

    @property
    def index(self) -> int:
        """1-based area number, which is also its HugeMap_NN text key."""
        m = re.search(r"(\d+)$", self.area_id)
        return int(m.group(1)) if m else 0

    @property
    def text_key(self) -> str:
        return "HugeMap_%02d" % self.index


@dataclass
class Shrine:
    shrine_id: str
    cleared: int

    @property
    def index(self) -> int:
        m = re.search(r"(\d+)$", self.shrine_id)
        return int(m.group(1)) if m else 0

    @property
    def text_key(self) -> str:
        """The shrines are Map_200000_013..032, in shrine_01..20 order."""
        return "Map_200000_%03d" % (self.index + 12)


class HugeMap:
    """Ginormosia's progress block, parsed and re-packable."""

    def __init__(self, start: int, end: int, areas: List[Area],
                 camps: List[str], found: List[str], shrines: List[Shrine]):
        self.start = start
        self.end = end
        self.areas = areas
        self.camps = camps
        self.found = found
        self.shrines = shrines

    # -------------------------------------------------------------- parsing
    @staticmethod
    def _fstring(data: bytes, p: int) -> Tuple[str, int]:
        n = struct.unpack_from("<i", data, p)[0]
        if not 1 < n <= 140 or p + 4 + n > len(data):
            raise ValueError("bad FString length %d at 0x%X" % (n, p))
        raw = data[p + 4:p + 4 + n]
        if raw[-1] != 0:
            raise ValueError("unterminated FString at 0x%X" % p)
        return raw[:-1].decode("ascii", "replace"), p + 4 + n

    @classmethod
    def parse(cls, payload: bytes) -> Optional["HugeMap"]:
        needle = struct.pack("<I", HUGEMAP_MAGIC)
        at = -1
        while True:
            at = payload.find(needle, at + 1)
            if at < 0:
                return None
            try:
                return cls._parse_at(payload, at)
            except (ValueError, struct.error):
                continue           # a coincidental magic; keep looking

    @classmethod
    def _parse_at(cls, payload: bytes, start: int) -> "HugeMap":
        p = start + 4
        count = struct.unpack_from("<I", payload, p)[0]
        p += 4
        if not 1 <= count <= 64:
            raise ValueError("implausible area count %d" % count)
        areas: List[Area] = []
        for _ in range(count):
            name, p = cls._fstring(payload, p)
            if not name.startswith("map200000_area"):
                raise ValueError("not an area id: %r" % name)
            rank, shown = payload[p], payload[p + 1]
            pts = struct.unpack_from("<I", payload, p + 2)[0]
            p += 6
            areas.append(Area(name, rank, shown, pts))

        def name_list() -> List[str]:
            nonlocal p
            n = struct.unpack_from("<I", payload, p)[0]
            p += 4
            if n > 256:
                raise ValueError("implausible list length %d" % n)
            out = []
            for _ in range(n):
                s, p = cls._fstring(payload, p)
                out.append(s)
            return out

        camps = name_list()
        found = name_list()

        n = struct.unpack_from("<I", payload, p)[0]
        p += 4
        if not 1 <= n <= 256:
            raise ValueError("implausible shrine count %d" % n)
        shrines: List[Shrine] = []
        for _ in range(n):
            s, p = cls._fstring(payload, p)
            if s.lower()[:6] != "shrine":
                raise ValueError("not a shrine id: %r" % s)
            shrines.append(Shrine(s, struct.unpack_from("<I", payload, p)[0]))
            p += 4
        return cls(start, p, areas, camps, found, shrines)

    # -------------------------------------------------------------- packing
    @staticmethod
    def _pack_fstring(s: str) -> bytes:
        raw = s.encode("ascii") + b"\0"
        return struct.pack("<i", len(raw)) + raw

    def pack(self) -> bytes:
        out = [struct.pack("<II", HUGEMAP_MAGIC, len(self.areas))]
        for a in self.areas:
            out.append(self._pack_fstring(a.area_id))
            out.append(struct.pack("<BBI", a.rank & 0xFF, a.rank_shown & 0xFF,
                                   a.points & 0xFFFFFFFF))
        for names in (self.camps, self.found):
            out.append(struct.pack("<I", len(names)))
            out.extend(self._pack_fstring(n) for n in names)
        out.append(struct.pack("<I", len(self.shrines)))
        for s in self.shrines:
            out.append(self._pack_fstring(s.shrine_id))
            out.append(struct.pack("<I", s.cleared & 0xFFFFFFFF))
        return b"".join(out)

    # -------------------------------------------------------------- editing
    def area(self, which) -> Area:
        """One area, by id (``map200000_area003``) or by its number (``3``)."""
        text = str(which)
        if text.isdigit():
            n = int(text)
            for a in self.areas:
                if a.index == n:
                    return a
            raise KeyError("no Ginormosia area number %d" % n)
        for a in self.areas:
            if a.area_id == text:
                return a
        raise KeyError("no Ginormosia area called %r" % text)

    def set_area_rank(self, which, rank: int, points: Optional[int] = None,
                      allow_over_max: bool = False) -> Area:
        """Put one area at *rank*, on its own.

        The points follow the rank unless they are given explicitly, so the two
        stored numbers agree with each other.  Ranks above ``MAX_RANK`` are
        refused by default: ``GDSAreaRankLevel`` only has rows up to 7, so a
        higher one would send the game's own lookup past the end of its table.
        """
        a = self.area(which)
        rank = int(rank)
        if not allow_over_max:
            rank = max(1, min(MAX_RANK, rank))
        rank = max(0, min(0xFF, rank))
        a.rank = a.rank_shown = rank
        a.points = (RANK_POINTS.get(rank, RANK_POINTS[MAX_RANK])
                    if points is None else max(0, min(0xFFFFFFFF, int(points))))
        return a

    def set_ranks(self, rank: int = MAX_RANK,
                  points: Optional[int] = None) -> int:
        """Put every area at *rank*.  Returns how many areas changed.

        The points are raised to the rank's own threshold when they are below
        it, so the stored rank and the stored points agree with each other.
        """
        rank = max(1, min(MAX_RANK, int(rank)))
        floor = RANK_POINTS[rank] if points is None else int(points)
        changed = 0
        for a in self.areas:
            if a.rank == rank and a.rank_shown == rank and a.points >= floor:
                continue
            a.rank = a.rank_shown = rank
            a.points = max(a.points, floor)
            changed += 1
        return changed

    def open_areas(self, points: int = OPEN_POINTS) -> List[Area]:
        """Give every unscored area a token score, leaving its rank alone.

        This does **not** uncover the map -- that was the guess, and it was
        wrong; see the fog note in this module's docstring.  It survives only
        because scoring an area without ranking it up is a sensible thing to be
        able to do.
        """
        points = max(1, int(points))
        changed = []
        for a in self.areas:
            if a.points >= points:
                continue
            a.points = points
            changed.append(a)
        return changed

    def unlock_camps(self, camps: Tuple[str, ...] = ALL_CAMPS) -> List[str]:
        """Add every camp that is not there yet.  Returns the ones added."""
        added = [c for c in camps if c not in self.camps]
        self.camps.extend(added)
        return added

    def reveal_shrines(self) -> List[str]:
        """Put every shrine on the map.  Returns the ones added."""
        added = [s.shrine_id for s in self.shrines
                 if s.shrine_id not in self.found]
        self.found.extend(added)
        return added

    def clear_shrines(self, cleared: int = 1) -> int:
        """Mark every shrine cleared.  Returns how many changed."""
        changed = 0
        for s in self.shrines:
            if s.cleared != cleared:
                s.cleared = cleared
                changed += 1
        return changed

    # -------------------------------------------------------------- reading
    def summary(self) -> str:
        ranked = sum(1 for a in self.areas if a.rank >= MAX_RANK)
        return ("Ginormosia: %d areas (%d at rank %d), %d/%d camps, "
                "%d/%d shrines found, %d cleared"
                % (len(self.areas), ranked, MAX_RANK, len(self.camps),
                   len(ALL_CAMPS), len(self.found), len(self.shrines),
                   sum(1 for s in self.shrines if s.cleared)))
