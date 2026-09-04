"""The Base Camp island: everything the player builds, digs, floods and places.

The game calls the whole system **CraftObj**.  One flat pool holds every object
that has ever been put down on the island -- the ground itself, the water, the
cliff faces, the roads, the fences and bridges, the houses, the furniture and
the rubble that was there before any of it -- and a second pool holds the extra
parameters that some of those objects need.  Both live in one contiguous block
of the payload, which is what makes an island shareable: copy the block and you
have copied the island.

The block
---------
It is found by its magic and runs to the magic of the block that follows::

    uint32  0x301BD677                  CraftStatusInfoP
    uint32  version                     4 on every build seen
    byte    header[86]                  carried through untouched
    uint32  objectCount                 65535 -- a fixed pool, mostly empty
    objectCount x CraftObjStatusP
    uint32  landCount                   10240
    landCount x CraftObjExParamLand
    uint32  houseCount                  32
    houseCount x CraftObjExParamHouse
    uint32 n; n x  8  bytes             CraftObjExParamPickPoint
    uint32 n; n x var                   CraftObjExParamStand
    uint32 n; n x  8  bytes             CraftObjExParamPlantDungeon
    uint32 n; n x  8  bytes             CraftObjExParamVegetableField
    uint32 n; n x 24  bytes             CraftObjExParamPlannedConstruct

The seven ex-parameter pools are ``CraftExParamP``'s seven arrays, in
declaration order, which is how the shape was pinned down: the block has to end
exactly on the next magic, and only this reading does.

The object record
-----------------
``CraftObjStatusP``, in the order the UE property table declares it::

    uint32   handle          slot | ((slot + 1) & 0xFF) << 24
    uint32   exParamHandle   0, or index | kind << 16 | 0xFF << 24
    FName    craftObjId      "land_obj", "obj_ico04080010", "obstacle_05", ...
    FName    viewPatternId   "Default", "Connect_All", "Scraped_UL", ...
    double   location    x, y, z
    double   rotation    pitch, yaw, roll
    int32    gridIdx
    uint32   mapId           an FName hash; 0x6BBD96BB is the Base Camp
    uint8    objStatusBitFlag  ECraftObjStatusBitFlag: 1 Shave, 2 Put

An empty slot writes ``"None"`` for both names and zero for everything else.

What the ids mean
-----------------
``land_obj`` and ``water_obj`` are the terrain: one record per tile, on a 100
unit grid, and the *viewPatternId* is how that tile is drawn -- ``Connect_All``
for a tile with neighbours on every side, ``Scraped_UL``/``UR``/``DL``/``DR``
for the four ways a corner can be cut away, which is what a sculpted cliff is
made of.  Height is the tile's Z.

``obj_`` and ``house_`` ids carry an item id after the prefix, so
``obj_ico04080010`` is item ``ico04080010``, *Green Grass*, and
``house_icf01020030`` is *Thatched House* -- the text database names them
without any extra table.  ``obstacle_NN`` are the boulders, debris and big
trees that block building until they are cleared.

Roads are neither: a path is a *land* tile carrying a land ex-parameter whose
``tileID`` is the road item (``obj_icf05010040``, *Swolean Road*).  That is why
the land pool travels with the terrain and not with the objects.

Houses
------
``CraftObjExParamHouse`` is what turns a placed building into a home::

    uint32   handle
    uint32 n; n x uint32   indoorAreaStHdl   rooms inside it
    FName    placedMapId      the map it stands on -- "Map_000100", Base Camp
    FName    entranceMapId    where its door leads
    FName    refAreaId
    FName    houseDataId      "house_icf01020030"
    uint8    houseCategory    ECraftHouseCategory
    uint32   -

``entranceMapId`` is the useful one: ``Map_MyHouse`` is the player's own house,
``NPCRoom_00xxxx`` an inhabitant's, ``Map_5000xx`` the Guild office or the
gallery.  The object that *is* that house is the one whose ``exParamHandle``
points at the record, so the player's house position is the location of the
object pointing at the ``Map_MyHouse`` entry.

The rooms themselves -- their walls, floors and the furniture inside them --
live in the *next* block (magic ``0x566F4529``, ``CraftAreaStatusP``), which
this module carries alongside as an opaque blob so that houses and their
interiors are always exported and imported together.
"""
from __future__ import annotations

import base64
import datetime
import gzip
import json
import math
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .stream import Reader, pack_fstring

CRAFT_MAGIC = 0x301BD677       # CraftStatusInfoP -- the island itself
AREA_MAGIC = 0x566F4529        # CraftAreaStatusP -- the areas and room interiors
AFTER_AREA_MAGIC = 0xBD771C57  # the block after the areas, which bounds them

HEADER_LEN = 86                # magic + version, then this, then the pool count
BASE_CAMP_MAP = 0x6BBD96BB     # mapId hash of Map_000100

#: ex-parameter pools, in the order ``CraftExParamP`` declares them -- which is
#: also the ``kind`` byte of an object's ``exParamHandle``.  The four
#: fixed-width ones are carried as raw records; land, house and stand have their
#: own parsers because they hold names, lists and a map.
POOL_KINDS = ("land", "house", "pick", "stand",
              "plant_dungeon", "vegetable_field", "planned_construct")
FIXED_POOLS = {"pick": 8, "plant_dungeon": 8, "vegetable_field": 8,
               "planned_construct": 24}
STAND_ENTRY = 16               # one standPlaceInfoMap pair

#: ``ECraftHouseCategory`` as the saves use it.
HOUSE_CATEGORIES = {0: "none", 1: "player", 2: "inhabitant", 3: "guild",
                    4: "gallery"}

#: every craftObjId the game treats as ground rather than as a thing on it.
TERRAIN_IDS = frozenset((
    "blank_obj", "land_obj", "water_obj", "waterfall_obj",
    "land_desert_obj", "land_rock_obj",
    "h_land_sur_obj", "h_land_in_obj", "h_water_obj",
    "h_land_sur_desert_obj", "h_land_in_desert_obj", "h_water_desert_obj",
    "h_land_sur_rock_obj", "h_land_in_rock_obj", "h_water_rock_obj",
))

EMPTY_NAME = "None"
EMPTY_GRID = -1                # what an unused object slot stores for gridIdx

LAYOUT_FORMAT = "fantasy-life-i-base-camp"
LAYOUT_VERSION = 1

#: what an exported layout may be asked to bring across.
SCOPES = ("all", "terrain", "objects")


class BaseCampError(Exception):
    pass


def _u32(v: int) -> bytes:
    return struct.pack("<I", v & 0xFFFFFFFF)


def _neg_zero(v: float) -> bool:
    """True for -0.0, which JSON cannot tell from 0.0 in every language.

    Python writes ``-0.0`` and reads it back; JavaScript's ``JSON.stringify``
    turns it into ``0``.  Four objects in one real save carry a negative zero
    rotation, so rather than trust the number the exporter lists them on the
    side and both implementations put the sign back.
    """
    return v == 0.0 and math.copysign(1.0, v) < 0


def ex_param_pool(handle: int) -> Optional[str]:
    """Which ex-parameter pool an ``exParamHandle`` points into, if any."""
    if not handle:
        return None
    kind = (handle >> 16) & 0xFF
    return POOL_KINDS[kind] if kind < len(POOL_KINDS) else None


# ------------------------------------------------------------------ records

@dataclass
class CraftObject:
    """One slot of the object pool -- a tile, a building, a chair or nothing."""

    slot: int
    ex_param: int = 0
    obj_id: str = EMPTY_NAME
    view_pattern: str = EMPTY_NAME
    location: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    grid_idx: int = EMPTY_GRID
    map_id: int = 0
    flags: int = 0
    handle: Optional[int] = None      # None = the ordinary rule for this slot

    @staticmethod
    def rule_handle(slot: int) -> int:
        """The handle the game writes for a filled slot."""
        return (slot | (((slot + 1) & 0xFF) << 24)) & 0xFFFFFFFF

    @property
    def used(self) -> bool:
        return self.obj_id != EMPTY_NAME

    @property
    def terrain(self) -> bool:
        return self.obj_id in TERRAIN_IDS

    @property
    def blank(self) -> bool:
        """True for a slot holding exactly what the game writes for "empty".

        Every unused slot in every save seen is this record to the byte, which
        is what lets an exported layout list only the slots in use.
        """
        return (not self.used and self.ex_param == 0 and self.map_id == 0
                and self.flags == 0 and self.handle is None
                and self.grid_idx == EMPTY_GRID
                and self.view_pattern == EMPTY_NAME
                and not any(self.location) and not any(self.rotation))

    @property
    def item_id(self) -> Optional[str]:
        """The item id behind an ``obj_``/``house_`` object, if it has one."""
        for prefix in ("obj_", "house_"):
            if self.obj_id.startswith(prefix):
                return self.obj_id[len(prefix):]
        return None

    @property
    def ex_param_pool(self) -> Optional[str]:
        """The pool this object's ex-parameter lives in -- ``house``, ``land``."""
        return ex_param_pool(self.ex_param)

    def stored_handle(self) -> int:
        if self.handle is not None:
            return self.handle
        return self.rule_handle(self.slot) if self.used else 0

    def pack(self) -> bytes:
        return b"".join((
            _u32(self.stored_handle()), _u32(self.ex_param),
            pack_fstring(self.obj_id), pack_fstring(self.view_pattern),
            struct.pack("<3d", *self.location),
            struct.pack("<3d", *self.rotation),
            struct.pack("<iIB", self.grid_idx, self.map_id & 0xFFFFFFFF,
                        self.flags & 0xFF),
        ))


@dataclass
class LandParam:
    """A land ex-parameter: the tile laid over a piece of ground, ie a road."""

    slot: int
    tile_id: str = EMPTY_NAME
    extra: int = 0
    handle: Optional[int] = None

    @staticmethod
    def rule_handle(slot: int) -> int:
        return (slot | 0xFF000000) & 0xFFFFFFFF

    @property
    def used(self) -> bool:
        return self.tile_id != EMPTY_NAME

    def stored_handle(self) -> int:
        if self.handle is not None:
            return self.handle
        return self.rule_handle(self.slot) if self.used else 0

    def pack(self) -> bytes:
        return (_u32(self.stored_handle()) + pack_fstring(self.tile_id)
                + _u32(self.extra))


@dataclass
class House:
    """A house ex-parameter: which building is whose home, and its rooms."""

    slot: int
    indoor_areas: List[int] = field(default_factory=list)
    placed_map: str = EMPTY_NAME
    entrance_map: str = EMPTY_NAME
    ref_area: str = EMPTY_NAME
    house_data: str = EMPTY_NAME
    category: int = 0
    extra: int = 0
    handle: Optional[int] = None

    @staticmethod
    def rule_handle(slot: int) -> int:
        return (slot | 0x0001_0000 | 0xFF000000) & 0xFFFFFFFF

    @property
    def used(self) -> bool:
        return self.house_data != EMPTY_NAME or self.entrance_map != EMPTY_NAME

    @property
    def is_player_house(self) -> bool:
        return self.entrance_map == "Map_MyHouse"

    @property
    def category_name(self) -> str:
        return HOUSE_CATEGORIES.get(self.category, "?")

    @property
    def item_id(self) -> Optional[str]:
        if self.house_data.startswith("house_"):
            return self.house_data[len("house_"):]
        return None

    def stored_handle(self) -> int:
        if self.handle is not None:
            return self.handle
        return self.rule_handle(self.slot) if self.used else 0

    def pack(self) -> bytes:
        return b"".join((
            _u32(self.stored_handle()), _u32(len(self.indoor_areas)),
            b"".join(_u32(h) for h in self.indoor_areas),
            pack_fstring(self.placed_map), pack_fstring(self.entrance_map),
            pack_fstring(self.ref_area), pack_fstring(self.house_data),
            bytes((self.category & 0xFF,)), _u32(self.extra),
        ))


@dataclass
class StandParam:
    """A display-stand ex-parameter: a handle plus its placement map."""

    handle: int = 0
    entries: List[bytes] = field(default_factory=list)

    def pack(self) -> bytes:
        return (_u32(self.handle) + _u32(len(self.entries))
                + b"".join(self.entries))


@dataclass
class FixedPool:
    """One of the ex-parameter pools whose records are all the same size."""

    name: str
    size: int
    records: List[bytes] = field(default_factory=list)

    def pack(self) -> bytes:
        return _u32(len(self.records)) + b"".join(self.records)


# -------------------------------------------------------------------- block

class BaseCamp:
    """The Base Camp block of one save, parsed and re-packable."""

    def __init__(self, payload: bytes):
        self.start = payload.find(_u32(CRAFT_MAGIC))
        if self.start < 0:
            raise BaseCampError("no Base Camp block in this save")
        self.area_start = payload.find(_u32(AREA_MAGIC), self.start)
        if self.area_start < 0:
            raise BaseCampError("no area block after the Base Camp block")
        self.area_end = payload.find(_u32(AFTER_AREA_MAGIC), self.area_start)
        if self.area_end < 0:
            raise BaseCampError("nothing bounds the Base Camp area block")
        self.end = self.area_start
        self.area_blob = bytes(payload[self.area_start:self.area_end])

        r = Reader(payload, self.start)
        r.u32()                                  # the magic, already matched
        self.version = r.u32()
        self.header = r.bytes(HEADER_LEN)

        self.objects: List[CraftObject] = []
        for slot in range(r.u32()):
            handle, ex = r.u32(), r.u32()
            obj = CraftObject(
                slot=slot, ex_param=ex,
                obj_id=r.fstring(), view_pattern=r.fstring(),
                location=struct.unpack("<3d", r.bytes(24)),
                rotation=struct.unpack("<3d", r.bytes(24)),
                grid_idx=r.i32(), map_id=r.u32(), flags=r.u8(),
            )
            if handle != obj.stored_handle():
                obj.handle = handle
            self.objects.append(obj)

        self.land: List[LandParam] = []
        for slot in range(r.u32()):
            handle = r.u32()
            lp = LandParam(slot=slot, tile_id=r.fstring(), extra=r.u32())
            if handle != lp.stored_handle():
                lp.handle = handle
            self.land.append(lp)

        self.houses: List[House] = []
        for slot in range(r.u32()):
            handle = r.u32()
            rooms = [r.u32() for _ in range(r.u32())]
            h = House(slot=slot, indoor_areas=rooms,
                      placed_map=r.fstring(), entrance_map=r.fstring(),
                      ref_area=r.fstring(), house_data=r.fstring(),
                      category=r.u8(), extra=r.u32())
            if handle != h.stored_handle():
                h.handle = handle
            self.houses.append(h)

        self.pools: Dict[str, FixedPool] = {}
        self.stands: List[StandParam] = []
        for name in ("pick", "stand", "plant_dungeon", "vegetable_field",
                     "planned_construct"):
            if name == "stand":
                for _ in range(r.u32()):
                    handle = r.u32()
                    self.stands.append(StandParam(
                        handle, [r.bytes(STAND_ENTRY) for _ in range(r.u32())]))
                continue
            size = FIXED_POOLS[name]
            self.pools[name] = FixedPool(
                name, size, [r.bytes(size) for _ in range(r.u32())])

        if r.pos != self.end:
            raise BaseCampError(
                "the Base Camp block ends at 0x%X but the next block starts at "
                "0x%X" % (r.pos, self.end))

        # A parse that cannot rebuild the bytes it came from is a parse that
        # would silently rewrite the island, so prove it before anyone edits.
        if self.pack() != bytes(payload[self.start:self.end]):
            raise BaseCampError("the Base Camp block does not round-trip")

    # ------------------------------------------------------------ packing
    def pack(self) -> bytes:
        out = [_u32(CRAFT_MAGIC), _u32(self.version), self.header,
               _u32(len(self.objects))]
        out += [o.pack() for o in self.objects]
        out.append(_u32(len(self.land)))
        out += [lp.pack() for lp in self.land]
        out.append(_u32(len(self.houses)))
        out += [h.pack() for h in self.houses]
        out.append(self.pools["pick"].pack())
        out.append(_u32(len(self.stands)))
        out += [s.pack() for s in self.stands]
        for name in ("plant_dungeon", "vegetable_field", "planned_construct"):
            out.append(self.pools[name].pack())
        return b"".join(out)

    # ------------------------------------------------------------ reading
    @property
    def used(self) -> List[CraftObject]:
        return [o for o in self.objects if o.used]

    @property
    def player_house(self) -> Optional[House]:
        for h in self.houses:
            if h.is_player_house:
                return h
        return None

    def object_for(self, house: House) -> Optional[CraftObject]:
        """The placed building that carries this house record."""
        want = house.stored_handle()
        if not want:
            return None
        for o in self.objects:
            if o.ex_param == want:
                return o
        return None

    def counts(self) -> Dict[str, int]:
        """A one-line summary of what is on the island."""
        used = self.used
        return {
            "slots": len(self.objects),
            "used": len(used),
            "ground": sum(1 for o in used if o.terrain
                          and not o.obj_id.startswith("water")),
            "water": sum(1 for o in used if o.obj_id.startswith("water")),
            "cliffs": sum(1 for o in used if o.view_pattern.startswith("Scraped")),
            "levels": len({o.location[2] for o in used if o.terrain}),
            "roads": sum(1 for lp in self.land if lp.used),
            "buildings": sum(1 for o in used if o.obj_id.startswith("obj_icf")),
            "furniture": sum(1 for o in used if o.obj_id.startswith("obj_ico")),
            "markers": sum(1 for o in used if o.obj_id.startswith("obj_")
                           and not o.obj_id.startswith(("obj_ico", "obj_icf"))),
            "obstacles": sum(1 for o in used if o.obj_id.startswith("obstacle")),
            "houses": sum(1 for h in self.houses if h.used),
            "areas": len(self.area_blob),
        }

    #: how :meth:`tally` groups the pool.  ``obj_icf`` are the structures the
    #: game builds -- houses, squares, bridges, roads -- and ``obj_ico`` the
    #: things placed on them; both name an item id after the prefix.
    KINDS = {
        "buildings": lambda o: o.obj_id.startswith("obj_icf"),
        "furniture": lambda o: o.obj_id.startswith("obj_ico"),
        "markers": lambda o: (o.obj_id.startswith("obj_")
                              and not o.obj_id.startswith(("obj_ico", "obj_icf"))),
        "obstacles": lambda o: o.obj_id.startswith("obstacle"),
        "terrain": lambda o: o.terrain,
    }

    def tally(self, kind: str = "furniture") -> List[Tuple[str, int, Optional[str]]]:
        """``(craftObjId, how many, item id)`` for one family of objects.

        *kind* is any key of :data:`KINDS`, or ``roads`` -- which is not a
        family of objects at all but the tiles laid over the ground.
        """
        seen: Dict[str, int] = {}
        if kind == "roads":
            for lp in self.land:
                if lp.used:
                    seen[lp.tile_id] = seen.get(lp.tile_id, 0) + 1
        else:
            test = self.KINDS[kind]
            for o in self.used:
                if test(o):
                    seen[o.obj_id] = seen.get(o.obj_id, 0) + 1
        rows = []
        for name, n in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0])):
            item = (name[4:] if name.startswith("obj_")
                    else name[6:] if name.startswith("house_") else None)
            rows.append((name, n, item))
        return rows

    # ------------------------------------------------------------ editing
    def replace_terrain(self, other: "BaseCamp") -> Dict[str, int]:
        """Take *other*'s ground, water, cliffs and roads; keep everything else.

        Objects live in a flat pool addressed by slot, and nothing outside the
        block points into it, so re-slotting is safe: the kept objects and the
        incoming terrain are laid down together and every handle is rewritten
        from its new slot.  The land ex-parameter pool comes across whole,
        because only terrain refers to it.
        """
        kept = [o for o in self.used if not o.terrain]
        incoming = [o for o in other.used if o.terrain]
        if len(kept) + len(incoming) > len(self.objects):
            raise BaseCampError(
                "%d objects will not fit in a %d slot pool"
                % (len(kept) + len(incoming), len(self.objects)))

        # A terrain tile's ex-parameter is its road, and the road pool is being
        # replaced wholesale, so those handles travel unchanged; a kept object's
        # handle points at a pool this edit does not touch.
        self.land = [LandParam(lp.slot, lp.tile_id, lp.extra, lp.handle)
                     for lp in other.land]
        self._relay(kept + incoming)
        return {"kept": len(kept), "added": len(incoming)}

    def replace_objects(self, other: "BaseCamp") -> Dict[str, int]:
        """Take *other*'s buildings, furniture, houses and rubble; keep the land."""
        kept = [o for o in self.used if o.terrain]
        incoming = [o for o in other.used if not o.terrain]
        if len(kept) + len(incoming) > len(self.objects):
            raise BaseCampError(
                "%d objects will not fit in a %d slot pool"
                % (len(kept) + len(incoming), len(self.objects)))
        self.houses = [House(h.slot, list(h.indoor_areas), h.placed_map,
                             h.entrance_map, h.ref_area, h.house_data,
                             h.category, h.extra, h.handle)
                       for h in other.houses]
        self.stands = [StandParam(s.handle, list(s.entries)) for s in other.stands]
        for name, pool in other.pools.items():
            self.pools[name] = FixedPool(name, pool.size, list(pool.records))
        self.area_blob = other.area_blob
        self._relay(kept + incoming)
        return {"kept": len(kept), "added": len(incoming)}

    def _relay(self, objects: Sequence[CraftObject]) -> None:
        """Lay *objects* out from slot 0 and blank the rest of the pool."""
        total = len(self.objects)
        fresh: List[CraftObject] = []
        for slot, o in enumerate(objects):
            fresh.append(CraftObject(
                slot=slot, ex_param=o.ex_param, obj_id=o.obj_id,
                view_pattern=o.view_pattern, location=o.location,
                rotation=o.rotation, grid_idx=o.grid_idx, map_id=o.map_id,
                flags=o.flags))
        fresh += [CraftObject(slot=s) for s in range(len(fresh), total)]
        self.objects = fresh

    # ------------------------------------------------------------- layouts
    def to_document(self, *, build: str = "", note: str = "") -> dict:
        """This island as the plain data an export file carries."""
        return {
            "format": LAYOUT_FORMAT,
            "version": LAYOUT_VERSION,
            "exported": datetime.datetime.now().replace(microsecond=0).isoformat(),
            "build": build,
            "note": note,
            "summary": self.counts(),
            "craft": {
                "version": self.version,
                "header": base64.b64encode(self.header).decode(),
                "capacity": len(self.objects),
                "object_fields": ["slot", "exParam", "craftObjId",
                                  "viewPatternId", "x", "y", "z",
                                  "pitch", "yaw", "roll", "gridIdx", "mapId",
                                  "flags", "handle"],
                "objects": [
                    [o.slot, o.ex_param, o.obj_id, o.view_pattern,
                     o.location[0] + 0.0, o.location[1] + 0.0,
                     o.location[2] + 0.0, o.rotation[0] + 0.0,
                     o.rotation[1] + 0.0, o.rotation[2] + 0.0,
                     o.grid_idx, o.map_id, o.flags, o.handle]
                    for o in self.objects if not o.blank
                ],
                # (slot, which of x y z pitch yaw roll) for every -0.0
                "negative_zeros": [
                    [o.slot, k]
                    for o in self.objects if not o.blank
                    for k, v in enumerate(tuple(o.location) + tuple(o.rotation))
                    if _neg_zero(v)
                ],
                "land_capacity": len(self.land),
                "land_fields": ["slot", "tileId", "extra", "handle"],
                "land": [[lp.slot, lp.tile_id, lp.extra, lp.handle]
                         for lp in self.land
                         if lp.used or lp.extra or lp.stored_handle()],
                "houses": [
                    {"slot": h.slot, "indoorAreas": list(h.indoor_areas),
                     "placedMap": h.placed_map, "entranceMap": h.entrance_map,
                     "refArea": h.ref_area, "houseData": h.house_data,
                     "category": h.category, "extra": h.extra,
                     "handle": h.handle}
                    for h in self.houses],
                "stands": [{"handle": s.handle,
                            "entries": [base64.b64encode(e).decode()
                                        for e in s.entries]}
                           for s in self.stands],
                "pools": {name: {"size": p.size,
                                 "data": base64.b64encode(
                                     b"".join(p.records)).decode()}
                          for name, p in self.pools.items()},
            },
            "areas": base64.b64encode(self.area_blob).decode(),
        }

    @classmethod
    def from_document(cls, doc: dict) -> "BaseCamp":
        """Rebuild an island from an export file, without needing a save."""
        if doc.get("format") != LAYOUT_FORMAT:
            raise BaseCampError("this is not a Base Camp layout file")
        if doc.get("version", 0) > LAYOUT_VERSION:
            raise BaseCampError(
                "this layout was written by a newer editor (format version %s)"
                % doc.get("version"))
        c = doc["craft"]
        self = cls.__new__(cls)
        self.start = self.end = self.area_start = self.area_end = -1
        self.version = c["version"]
        self.header = base64.b64decode(c["header"])
        self.area_blob = base64.b64decode(doc["areas"])

        self.objects = [CraftObject(slot=s) for s in range(c["capacity"])]
        for row in c["objects"]:
            slot = row[0]
            if not 0 <= slot < len(self.objects):
                raise BaseCampError("this layout has an object in slot %s of a "
                                    "%d slot pool" % (slot, len(self.objects)))
            self.objects[slot] = CraftObject(
                slot=slot, ex_param=row[1], obj_id=row[2], view_pattern=row[3],
                location=(row[4], row[5], row[6]),
                rotation=(row[7], row[8], row[9]),
                grid_idx=row[10], map_id=row[11], flags=row[12],
                handle=row[13] if len(row) > 13 else None)

        for slot, k in c.get("negative_zeros", ()):
            o = self.objects[slot]
            vals = list(o.location) + list(o.rotation)
            vals[k] = -0.0
            o.location, o.rotation = tuple(vals[:3]), tuple(vals[3:])

        self.land = [LandParam(slot=s) for s in range(c["land_capacity"])]
        for row in c["land"]:
            if not 0 <= row[0] < len(self.land):
                raise BaseCampError("this layout has a land tile in slot %s of "
                                    "a %d slot pool" % (row[0], len(self.land)))
            self.land[row[0]] = LandParam(
                slot=row[0], tile_id=row[1], extra=row[2],
                handle=row[3] if len(row) > 3 else None)

        self.houses = [House(slot=h["slot"], indoor_areas=list(h["indoorAreas"]),
                             placed_map=h["placedMap"],
                             entrance_map=h["entranceMap"],
                             ref_area=h["refArea"], house_data=h["houseData"],
                             category=h["category"], extra=h["extra"],
                             handle=h.get("handle"))
                       for h in c["houses"]]
        self.stands = [StandParam(s["handle"],
                                  [base64.b64decode(e) for e in s["entries"]])
                       for s in c["stands"]]
        self.pools = {}
        for name, p in c["pools"].items():
            blob = base64.b64decode(p["data"])
            size = p["size"]
            if size < 1 or len(blob) % size:
                raise BaseCampError("the %s pool in this layout is malformed"
                                    % name)
            self.pools[name] = FixedPool(
                name, size,
                [blob[i:i + size] for i in range(0, len(blob), size)])
        return self


# ----------------------------------------------------------------- the file

def write_layout(path: str, doc: dict) -> int:
    """Write a layout.  ``.json`` stays readable, anything else is gzipped."""
    text = json.dumps(doc, ensure_ascii=False,
                      indent=2 if path.lower().endswith(".json") else None)
    raw = text.encode("utf-8")
    if not path.lower().endswith(".json"):
        raw = gzip.compress(raw, 9)
    with open(path, "wb") as fh:
        fh.write(raw)
    return len(raw)


def read_layout(path: str) -> dict:
    """Read a layout file, gzipped or not."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise BaseCampError("this file is not a Base Camp layout (%s)" % exc)
