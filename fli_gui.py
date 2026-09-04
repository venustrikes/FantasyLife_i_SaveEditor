#!/usr/bin/env python3
"""Fantasy Life i: The Girl Who Steals Time - save editor.

    python fli_gui.py  [path to 002DAE74-00-gamedata.bin]

Six tabs: the character (name, Dosh, vitals), the item containers, the Lives,
the world (bulletin boards and Ginormosia), the Base Camp island -- which can
be exported and imported whole, so a layout can be shared -- and a value hunter
for anything still unmapped.  Edits are held in memory until Save, which keeps
a timestamped .bak of the file it replaces.
"""
from __future__ import annotations

import os
import sys
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from flisave import icons as iconset
from flisave import gear, items, names as namedb, recipes as reciped
from flisave.character import FIELDS as VITALS
from flisave.hunt import Hunt, TYPES as HUNT_TYPES
from flisave.save import SaveFile, CURRENCIES
from flisave.world import (BOARDS, BOARD_BY_KEY, MAX_RANK, ALL_CAMPS,
                           TOWER_COUNT)

APP = "Fantasy Life i - Save Editor"

LANGUAGES = ["en", "it", "fr", "de", "es", "ja", "ko", "zh-Hans", "zh-Hant"]
STACK_FULL = 999                  # what "fill every stack" means
GREY = "#666666"

# Which containers "Give every ..." can fill: the gear.every() kind each one
# asks for, and the word for a single one of them.  The four equipment bags
# take a grade and Super OP with the fill; the rest are bags that stack, whose
# record is a bare count with nowhere to put either.
BULK_FILLS = {
    items.WEAPON: ("weapons", "weapon"),
    items.LIFE_TOOLS: ("tools", "Life tool"),
    items.SHIELD: ("shields", "shield"),
    items.ARMOR: ("armour", "piece of armour"),
    items.CRAFT: ("crafts", "craft item"),
    items.MATERIAL: ("materials", "material"),
    items.RECIPE: ("recipes", "recipe"),
}
# Recipes are always 1 in game and equipment has no stack at all, so only the
# bags that really hold a pile of something start full.
BULK_FULL_STACK = ("materials", "crafts")
# The grade dropdown's first row: no single grade at all, but each item spawned
# at the best one it has stats for, which is what the game itself hands out.
BULK_BEST_GRADE = "best grade for each item"

# The Base Camp tab's two dropdowns: what the list says, and what it means.
CAMP_KINDS = (
    ("furniture placed on it", "furniture"),
    ("buildings, bridges and squares", "buildings"),
    ("ground and water tiles", "terrain"),
    ("roads laid over the ground", "roads"),
    ("obstacles still in the way", "obstacles"),
    ("area markers", "markers"),
)
CAMP_SCOPES = (
    ("everything - the whole island", "all"),
    ("terrain only - ground, water, cliffs, roads", "terrain"),
    ("objects only - buildings, furniture, houses", "objects"),
)
CAMP_SCOPE_HELP = {
    "all": "Replaces the island outright: every tile and every object, the "
           "houses and the rooms inside them. This is the one that gives you "
           "the layout exactly as it was exported.",
    "terrain": "Takes the ground, the water, the cliff faces and the roads, "
               "and leaves your own buildings and furniture where they are. "
               "They keep their old positions, so anything that stood on "
               "ground the new terrain does not have will be left floating or "
               "buried.",
    "objects": "Takes the buildings, furniture, obstacles, houses and room "
               "interiors, and leaves your own ground and water alone. The "
               "incoming objects keep their positions, so they can land on "
               "terrain that is not shaped for them.",
}
IMPORT_UNCONFIRMED = (
    "Importing a layout throws away what is on your island now.\n\n"
    'Tick "replace what I have now" to confirm, and keep a copy of the save '
    "first - the editor writes a .bak, but only of the file it replaces."
)

SAVE_NAME = "002DAE74-00-gamedata.bin"

# Where a character save turns up.  The plain Steam release keeps it in Steam's
# userdata; a repacked build keeps it inside the game folder instead, so both
# are worth looking in.
SAVE_GLOBS = [
    r"%USERPROFILE%\Documents\*Fantasy Life*\**\SteamData\<name>",
    r"%USERPROFILE%\Desktop\*Fantasy Life*\**\SteamData\<name>",
    r"%LOCALAPPDATA%Low\LEVEL5 Inc_\**\<name>",
    r"%PROGRAMFILES(X86)%\Steam\userdata\*\*\remote\<name>",
    r"%USERPROFILE%\Documents\**\<name>",
]

DEFAULT_DIRS = [
    os.path.expandvars(r"%LOCALAPPDATA%Low\LEVEL5 Inc_"),
    os.path.expandvars(r"%USERPROFILE%\Documents"),
]


def find_saves():
    """Character saves in the usual places, newest first."""
    import glob
    found = {}
    for pattern in SAVE_GLOBS:
        pattern = os.path.expandvars(pattern.replace("<name>", SAVE_NAME))
        for path in glob.glob(pattern, recursive=True):
            if os.path.isfile(path):
                found[os.path.normcase(path)] = path
    return sorted(found.values(), key=os.path.getmtime, reverse=True)


def guess_dir() -> str:
    """Where the Open dialog should start."""
    saves = find_saves()
    if saves:
        return os.path.dirname(saves[0])
    for d in DEFAULT_DIRS:
        if os.path.isdir(d):
            return d
    return os.getcwd()


def as_int(text, default=0):
    text = str(text).strip()
    if not text:
        return default
    return int(text, 16) if text.lower().startswith("0x") else int(text)


class ItemPicker(tk.Toplevel):
    """Search the game's item list by name and pick one, with its icon."""

    def __init__(self, master, app, initial=""):
        super().__init__(master)
        self.app = app
        self.choice = None
        self.title("Find an item")
        self.transient(master)
        self.geometry("620x460")
        self.minsize(480, 320)

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Name or id:").pack(side="left")
        self.ent = ttk.Entry(top)
        self.ent.pack(side="left", fill="x", expand=True, padx=6)
        self.ent.insert(0, initial)
        self.ent.bind("<Return>", lambda _e: self.search())
        self.ent.bind("<KeyRelease>", lambda _e: self.after(220, self.search))
        ttk.Button(top, text="Search", command=self.search).pack(side="left")

        body = ttk.Frame(self, padding=(8, 0))
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("id",), show="tree headings",
                                 height=8, style="Picker.Treeview")
        self.tree.heading("#0", text="item")
        self.tree.heading("id", text="id")
        self.tree.column("#0", width=400)
        self.tree.column("id", width=140)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self.choose())
        self.tree.bind("<Return>", lambda _e: self.choose())

        foot = ttk.Frame(self, padding=8)
        foot.pack(fill="x")
        self.lbl = ttk.Label(foot, text="", foreground=GREY)
        self.lbl.pack(side="left")
        ttk.Button(foot, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(foot, text="Use this item",
                   command=self.choose).pack(side="right", padx=6)

        self.ent.focus_set()
        if initial:
            self.search()

    def search(self):
        text = self.ent.get().strip()
        for i in self.tree.get_children():
            self.tree.delete(i)
        if not text:
            return
        db = namedb.get()
        if not db.loaded:
            self.lbl.configure(text=db.error or "no name database")
            return
        hits = db.search(text, self.app.lang(), limit=200)
        for key, name in hits:
            self.tree.insert("", "end", iid=key, text="  " + name,
                             image=self.app.icons.item(key, iconset.LARGE) or "",
                             values=(key,))
        self.lbl.configure(text="%d match(es)" % len(hits))
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0])

    def choose(self):
        sel = self.tree.selection()
        if sel:
            self.choice = sel[0]
            self.destroy()


class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)
        self.pack(fill="both", expand=True)
        self.master.minsize(980, 660)
        self.save: SaveFile | None = None
        self.path: str | None = None
        self.dirty = False
        self.hunt = Hunt()
        self.icons = iconset.get()
        self._hits = []
        self._build()
        self.retitle()
        master.protocol("WM_DELETE_WINDOW", self.on_close)
        master.bind("<Control-o>", lambda _e: self.on_open())
        master.bind("<Control-s>", lambda _e: self.on_save())

    # ------------------------------------------------------------------- ui
    def _build(self):
        style = ttk.Style()
        for theme in ("vista", "clam", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("Treeview", rowheight=iconset.SMALL + 6)
        style.configure("Picker.Treeview", rowheight=iconset.LARGE + 6)
        style.configure("Head.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Big.TLabel", font=("Segoe UI", 14, "bold"))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="Open save...", command=self.on_open).pack(side="left")
        ttk.Button(bar, text="Save", command=self.on_save).pack(side="left", padx=4)
        ttk.Button(bar, text="Save as...", command=self.on_save_as).pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="Export payload...",
                   command=self.on_export).pack(side="left")
        ttk.Button(bar, text="Import payload...",
                   command=self.on_import).pack(side="left", padx=4)

        self.lbl_file = ttk.Label(bar, text="no file loaded", foreground=GREY)
        self.lbl_file.pack(side="right")
        self.cmb_lang = ttk.Combobox(bar, state="readonly", width=8,
                                     values=LANGUAGES)
        self.cmb_lang.set("en")
        self.cmb_lang.pack(side="right", padx=(0, 10))
        self.cmb_lang.bind("<<ComboboxSelected>>", lambda _e: self.on_lang())
        ttk.Label(bar, text="names:").pack(side="right", padx=(0, 4))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self.nb = nb
        nb.add(self._tab_character(nb), text="  Character  ")
        nb.add(self._tab_items(nb), text="  Items  ")
        nb.add(self._tab_lives(nb), text="  Lives  ")
        nb.add(self._tab_world(nb), text="  World  ")
        nb.add(self._tab_camp(nb), text="  Base Camp  ")
        nb.add(self._tab_tools(nb), text="  Find / Edit values  ")

        self.status = ttk.Label(self, text="Open a save to begin.",
                                relief="sunken", anchor="w", padding=(6, 3))
        self.status.pack(fill="x", pady=(8, 0))

    # ------------------------------------------------------------ character
    def _tab_character(self, parent):
        f = ttk.Frame(parent, padding=10)
        top = ttk.Frame(f)
        top.pack(fill="x")
        top.columnconfigure(0, weight=1, uniform="half")
        top.columnconfigure(1, weight=1, uniform="half")

        who = ttk.LabelFrame(top, text="Character", padding=10)
        who.grid(row=0, column=0, sticky="nsew")
        self.lbl_life_icon = ttk.Label(who)
        self.lbl_life_icon.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        self.lbl_who = ttk.Label(who, text="-", style="Big.TLabel")
        self.lbl_who.grid(row=0, column=1, columnspan=3, sticky="w")
        self.lbl_life = ttk.Label(who, text="", foreground=GREY)
        self.lbl_life.grid(row=1, column=1, columnspan=3, sticky="w")

        ttk.Label(who, text="name").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.ent_name = ttk.Entry(who, width=24)
        self.ent_name.grid(row=2, column=1, sticky="w", pady=(10, 0))

        ttk.Label(who, text="HP").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.ent_hp = ttk.Entry(who, width=8)
        self.ent_hp.grid(row=3, column=1, sticky="w", pady=(6, 0))
        ttk.Label(who, text="of").grid(row=3, column=2, pady=(6, 0))
        self.ent_hp_max = ttk.Entry(who, width=8)
        self.ent_hp_max.grid(row=3, column=3, sticky="w", pady=(6, 0))

        ttk.Label(who, text="SP").grid(row=4, column=0, sticky="w", pady=(4, 0))
        self.ent_sp = ttk.Entry(who, width=8)
        self.ent_sp.grid(row=4, column=1, sticky="w", pady=(4, 0))
        ttk.Label(who, text="of").grid(row=4, column=2, pady=(4, 0))
        self.ent_sp_max = ttk.Entry(who, width=8)
        self.ent_sp_max.grid(row=4, column=3, sticky="w", pady=(4, 0))
        ttk.Button(who, text="Apply", command=self.on_apply_character
                   ).grid(row=5, column=1, columnspan=3, sticky="w", pady=(10, 0))

        right = ttk.Frame(top)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        wallet = ttk.LabelFrame(right, text="Wallet", padding=10)
        wallet.pack(fill="x")
        self.lbl_coin = ttk.Label(wallet)
        self.lbl_coin.grid(row=0, column=0, padx=(0, 8))
        ttk.Label(wallet, text="Dosh").grid(row=0, column=1, sticky="w")
        self.ent_money = ttk.Entry(wallet, width=14)
        self.ent_money.grid(row=0, column=2, padx=6)
        self.ent_money.bind("<Return>", lambda _e: self.on_apply_money())
        ttk.Button(wallet, text="Set", command=self.on_apply_money
                   ).grid(row=0, column=3)

        # The other currencies the game keeps beside the Dosh, in the same
        # record, found the same way.
        self.ent_currency = {}
        for row, (kind, (_slot, label)) in enumerate(CURRENCIES.items(), start=1):
            ttk.Label(wallet, text=label).grid(row=row, column=1, sticky="w",
                                               pady=(6, 0))
            box = ttk.Entry(wallet, width=14)
            box.grid(row=row, column=2, padx=6, pady=(6, 0))
            box.bind("<Return>",
                     lambda _e, k=kind: self.on_apply_currency(k))
            ttk.Button(wallet, text="Set",
                       command=lambda k=kind: self.on_apply_currency(k)
                       ).grid(row=row, column=3, pady=(6, 0))
            self.ent_currency[kind] = box

        ttk.Label(wallet, text="all found by shape, so they stay right wherever "
                              "you are standing", foreground=GREY
                  ).grid(row=len(CURRENCIES) + 1, column=0, columnspan=4,
                         sticky="w", pady=(8, 0))

        info = ttk.LabelFrame(right, text="This save", padding=10)
        info.pack(fill="both", expand=True, pady=(10, 0))
        self.lbl_meta = ttk.Label(info, text="-", justify="left", foreground=GREY)
        self.lbl_meta.pack(anchor="w")

        det = ttk.LabelFrame(f, text="Details", padding=6)
        det.pack(fill="both", expand=True, pady=(10, 0))
        self.txt_info = tk.Text(det, wrap="none", height=10,
                                font=("Consolas", 9), relief="flat")
        sb = ttk.Scrollbar(det, orient="vertical", command=self.txt_info.yview)
        self.txt_info.configure(yscrollcommand=sb.set)
        self.txt_info.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return f

    # ---------------------------------------------------------------- items
    def _tab_items(self, parent):
        f = ttk.Frame(parent, padding=10)

        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="Container").pack(side="left")
        self.cmb_cont = ttk.Combobox(top, state="readonly", width=44)
        self.cmb_cont.pack(side="left", padx=6)
        self.cmb_cont.bind("<<ComboboxSelected>>", lambda _e: self.refresh_items())
        self.var_empty = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="show empty slots", variable=self.var_empty,
                        command=self.refresh_items).pack(side="left", padx=8)
        ttk.Label(top, text="filter").pack(side="left", padx=(12, 2))
        self.ent_filter = ttk.Entry(top, width=18)
        self.ent_filter.pack(side="left")
        self.ent_filter.bind("<KeyRelease>", lambda _e: self.refresh_items())

        ed = ttk.LabelFrame(f, text="Selected slot", padding=10)
        ed.pack(side="bottom", fill="x", pady=(8, 0))

        mid = ttk.Frame(f)
        mid.pack(fill="both", expand=True, pady=8)
        cols = ("id", "qty", "title", "attack", "aged")
        self.tree = ttk.Treeview(mid, columns=cols, show="tree headings", height=10)
        self.tree.heading("#0", text="slot / item")
        self.tree.column("#0", width=360)
        for c, w, head in (("id", 140, "id"), ("qty", 55, "qty"),
                           ("title", 110, "grade"), ("attack", 80, "atk / pow"),
                           ("aged", 70, "aged")):
            self.tree.heading(c, text=head)
            self.tree.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_pick_slot)

        self.lbl_item_icon = ttk.Label(ed)
        self.lbl_item_icon.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        ttk.Label(ed, text="item id").grid(row=0, column=1, sticky="w")
        self.ent_id = ttk.Entry(ed, width=20)
        self.ent_id.grid(row=0, column=2, padx=4)
        self.ent_id.bind("<KeyRelease>", lambda _e: self.on_id_typed())
        ttk.Button(ed, text="Find...", command=self.on_pick_item
                   ).grid(row=0, column=3, padx=(0, 12))
        ttk.Label(ed, text="quantity").grid(row=0, column=4, sticky="w")
        self.spn_qty = ttk.Spinbox(ed, from_=0, to=65535, width=8)
        self.spn_qty.grid(row=0, column=5, padx=4)
        # Equipment has no quantity; what it has is a title, and the title is
        # what the game reads the item's stats at.
        ttk.Label(ed, text="grade").grid(row=0, column=6, sticky="w", padx=(12, 0))
        self.cmb_title = ttk.Combobox(ed, state="readonly", width=30)
        self.cmb_title.grid(row=0, column=7, padx=4)
        self.lbl_item_name = ttk.Label(ed, text="", style="Head.TLabel")
        self.lbl_item_name.grid(row=1, column=1, columnspan=7, sticky="w")
        self.lbl_desc = ttk.Label(ed, text="", foreground=GREY, wraplength=820,
                                  justify="left")
        self.lbl_desc.grid(row=2, column=0, columnspan=8, sticky="w", pady=(6, 8))

        # Super OP mode.  The three things it writes are the three the Aging
        # Altar writes, so they are spelled out rather than hidden behind the
        # tick box: the grade the stats are read at, the vintage, and the
        # skills.  The tick box drives the two boxes next to it, and both Apply
        # buttons below honour it.
        op = ttk.Frame(ed)
        op.grid(row=3, column=0, columnspan=8, sticky="w", pady=(0, 8))
        self.var_op = tk.BooleanVar(value=False)
        ttk.Checkbutton(op, text="Super OP Weapon Mode", variable=self.var_op,
                        command=self.on_toggle_op).pack(side="left")
        ttk.Label(op, text="aged").pack(side="left", padx=(14, 2))
        self.spn_age = ttk.Spinbox(op, from_=0, to=65535, width=7,
                                   command=self.on_age_typed)
        self.spn_age.pack(side="left")
        self.spn_age.bind("<KeyRelease>", lambda _e: self.on_age_typed())
        ttk.Label(op, text="years").pack(side="left", padx=(2, 0))
        self.lbl_op = ttk.Label(op, text="", foreground=GREY)
        self.lbl_op.pack(side="left", padx=(14, 0))

        btns = ttk.Frame(ed)
        btns.grid(row=4, column=0, columnspan=8, sticky="w")
        ttk.Button(btns, text="Apply to slot",
                   command=self.on_apply_slot).pack(side="left")
        ttk.Button(btns, text="Clear slot",
                   command=self.on_clear_slot).pack(side="left", padx=6)
        ttk.Button(btns, text="Add to first free slot",
                   command=self.on_give).pack(side="left", padx=(18, 6))
        ttk.Button(btns, text="Fix gear...",
                   command=self.on_fix_gear).pack(side="right")
        # Shown only where it means something -- see sync_bulk_buttons.
        self.btn_set_qty = ttk.Button(btns, text="Set every quantity here...",
                                      command=self.on_set_quantities)

        self._bulk_panel(f, ed)
        return f

    def _bulk_panel(self, parent, above):
        """The "Give every ..." row, which follows the container dropdown.

        One panel rather than one button per bag: what a bulk fill needs asked
        differs by bag -- equipment has no stack, so its number is copies of
        each piece, and it is the only kind with a grade to pick -- and the
        panel says so on screen instead of behind a dialog.  It is packed
        *before* the Selected slot frame so it comes out underneath it, and it
        is off screen entirely on the bags that have no fill.
        """
        self.frm_slot = above
        self._bulk_kind = None
        self.bulk = ttk.LabelFrame(parent, text="Give every ...", padding=10)
        row = ttk.Frame(self.bulk)
        row.pack(fill="x")

        ttk.Label(row, text="how many").pack(side="left")
        self.spn_bulk_qty = ttk.Spinbox(row, from_=1, to=65535, width=8)
        self.spn_bulk_qty.pack(side="left", padx=4)
        self.lbl_bulk_qty = ttk.Label(row, text="of each")
        self.lbl_bulk_qty.pack(side="left")

        # Packed and unpacked per bag, so they keep this order on the row.
        self.lbl_bulk_grade = ttk.Label(row, text="grade")
        self.cmb_bulk_title = ttk.Combobox(row, state="readonly", width=26)
        self.cmb_bulk_title["values"] = [BULK_BEST_GRADE] + [
            "%d  %s" % (i, n) for i, n in enumerate(items.ITEM_TITLES)]
        self.cmb_bulk_title.current(0)
        self.cmb_bulk_title.bind("<<ComboboxSelected>>",
                                 lambda _e: self.describe_bulk())
        self.var_bulk_op = tk.BooleanVar(value=False)
        self.chk_bulk_op = ttk.Checkbutton(
            row, text="Super OP Weapon Mode", variable=self.var_bulk_op,
            command=self.describe_bulk)

        # Right-hand end of the row, like Fix gear... above it: the button
        # keeps its width whatever the window is narrowed to, and it is the
        # grade dropdown that gives ground instead of the label saying what
        # the button does.
        self.btn_bulk = ttk.Button(row, text="Give every item",
                                   command=self.on_give_every)
        self.btn_bulk.pack(side="right")
        self.lbl_bulk_note = ttk.Label(self.bulk, text="", foreground=GREY,
                                       wraplength=900, justify="left")
        self.lbl_bulk_note.pack(anchor="w", pady=(6, 0))

    # ---------------------------------------------------------------- lives
    def _tab_lives(self, parent):
        f = ttk.Frame(parent, padding=10)
        ttk.Label(f, text="Level, EXP, rank and PA for each Life. PA is the "
                          "ability points a Life spends on its abilities; rank "
                          "runs 0 = not started, 1 = Novice, up to 7 = Hero.",
                  foreground=GREY).pack(anchor="w")

        ed = ttk.LabelFrame(f, text="Edit", padding=10)
        ed.pack(side="bottom", fill="x", pady=(8, 0))

        mid = ttk.Frame(f)
        mid.pack(fill="both", expand=True, pady=8)
        cols = ("rank", "rank name", "points", "level", "exp", "PA")
        self.tree_life = ttk.Treeview(mid, columns=cols, show="tree headings",
                                      height=15)
        self.tree_life.heading("#0", text="Life")
        self.tree_life.column("#0", width=240)
        for c, w in zip(cols, (55, 130, 70, 70, 100, 70)):
            self.tree_life.heading(c, text=c)
            self.tree_life.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree_life.yview)
        self.tree_life.configure(yscrollcommand=sb.set)
        self.tree_life.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree_life.bind("<<TreeviewSelect>>", self.on_pick_life)

        self.life_entries = {}
        for i, (key, label, width) in enumerate((("level", "level", 8),
                                                 ("exp", "exp", 12),
                                                 ("pa", "PA", 8))):
            ttk.Label(ed, text=label).grid(row=0, column=i * 2,
                                           padx=(0 if i == 0 else 14, 3))
            e = ttk.Entry(ed, width=width)
            e.grid(row=0, column=i * 2 + 1)
            self.life_entries[key] = e
        ttk.Label(ed, text="rank").grid(row=0, column=6, padx=(14, 3))
        self.cmb_rank = ttk.Combobox(ed, state="readonly", width=18)
        self.cmb_rank.grid(row=0, column=7)
        # The points the Life master's quests award towards the next rank.  They
        # live in the two bytes above the rank, so they get a box of their own
        # rather than being carried along silently by a rank write.
        ttk.Label(ed, text="points").grid(row=0, column=8, padx=(14, 3))
        e = ttk.Entry(ed, width=8)
        e.grid(row=0, column=9)
        self.life_entries["rank_points"] = e
        ttk.Button(ed, text="Apply to this Life",
                   command=lambda: self.on_apply_life(False)
                   ).grid(row=0, column=10, padx=(18, 6))
        ttk.Button(ed, text="Apply to every Life",
                   command=lambda: self.on_apply_life(True)).grid(row=0, column=11)

        self._recipe_panel(f, ed)
        return f

    def _recipe_panel(self, parent, above):
        """"Recipes known" -- the list a crafting bench reads.

        A recipe is two things: the ``irp`` scroll in the Recipes bag, which is
        what the phone's list shows, and a bit in the save's recipe table,
        which is what the bench reads.  Filling the bag alone -- which is all
        "Give every recipe" on the Items tab used to do -- leaves the bench
        empty, so the flag gets a control of its own here, next to the ranks
        that decide which of those recipes a bench will actually offer.

        Packed before the Edit frame so it comes out underneath it.
        """
        self._recipe_lives = []
        self._recipe_rows = {}
        self.frm_recipes = ttk.LabelFrame(parent, text="Recipes known", padding=10)
        row = ttk.Frame(self.frm_recipes)
        row.pack(fill="x")
        ttk.Label(row, text="Life").pack(side="left")
        self.cmb_recipe = ttk.Combobox(row, state="readonly", width=40)
        self.cmb_recipe.pack(side="left", padx=6)
        self.cmb_recipe.bind("<<ComboboxSelected>>", self.on_pick_recipe_life)
        self.var_recipe = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="known (listed at the bench)",
                        variable=self.var_recipe).pack(side="left", padx=8)
        self.var_recipe_items = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="give the scrolls too",
                        variable=self.var_recipe_items).pack(side="left")
        ttk.Button(row, text="Learn every recipe",
                   command=lambda: self.on_apply_recipes(True)
                   ).pack(side="right")
        ttk.Button(row, text="Apply to this Life",
                   command=lambda: self.on_apply_recipes(False)
                   ).pack(side="right", padx=6)
        # The panel is the full width of the tab; wrapping at 900 pushed this
        # note to three lines on a save with longer counts in it and took the
        # tab past the height the window opens at.
        self.lbl_recipe = ttk.Label(self.frm_recipes, text="", foreground=GREY,
                                    wraplength=1080, justify="left")
        self.lbl_recipe.pack(anchor="w", pady=(6, 0))
        self.frm_recipes.pack(side="bottom", fill="x", pady=(8, 0), before=above)

    # ---------------------------------------------------------------- world
    def _tab_world(self, parent):
        # Two tables, three edit rows and three button rows do not fit in the
        # window on a 1080p screen, and the eye towers sit at the bottom of the
        # pile, so this tab scrolls.  Wheeling over a table still scrolls the
        # table; everywhere else scrolls the page.
        outer = ttk.Frame(parent)
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        wsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=wsb.set)
        wsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        f = ttk.Frame(canvas, padding=10)
        window = canvas.create_window((0, 0), window=f, anchor="nw")

        def fit(_evt=None):
            canvas.itemconfigure(window, width=canvas.winfo_width())
            canvas.configure(scrollregion=canvas.bbox("all"))
        f.bind("<Configure>", fit)
        canvas.bind("<Configure>", fit)

        # ------------------------------------------------------- boards
        bb = ttk.LabelFrame(f, text="Bulletin boards", padding=10)
        bb.pack(fill="both", expand=True)
        ttk.Label(bb, wraplength=980, foreground=GREY,
                  text="Every settlement has a board whose level rises as its "
                       "jobs are finished. The level itself is not stored in "
                       "the save - the game works it out from the jobs when the "
                       "save loads - so finishing them all is what takes a "
                       "board to its maximum.").pack(anchor="w")

        bmid = ttk.Frame(bb)
        bmid.pack(fill="both", expand=True, pady=(6, 0))
        bcols = ("jobs", "complete", "on board", "hidden")
        self.tree_board = ttk.Treeview(bmid, columns=bcols,
                                       show="tree headings", height=5)
        self.tree_board.heading("#0", text="zone")
        self.tree_board.column("#0", width=300)
        for c, w in zip(bcols, (80, 90, 90, 80)):
            self.tree_board.heading(c, text=c)
            self.tree_board.column(c, width=w, anchor="w")
        self.tree_board.pack(side="left", fill="both", expand=True)
        bsb = ttk.Scrollbar(bmid, orient="vertical",
                            command=self.tree_board.yview)
        self.tree_board.configure(yscrollcommand=bsb.set)
        bsb.pack(side="right", fill="y")

        brow = ttk.Frame(bb)
        brow.pack(fill="x", pady=(8, 0))
        ttk.Label(brow, text="zone").pack(side="left", padx=(0, 4))
        self.cmb_zone = ttk.Combobox(brow, state="readonly", width=34)
        self.cmb_zone.pack(side="left")
        ttk.Button(brow, text="Complete all quests",
                   command=lambda: self.guard(self.on_complete_board)
                   ).pack(side="left", padx=10)
        self.lbl_board = ttk.Label(brow, text="", foreground=GREY)
        self.lbl_board.pack(side="left", padx=8)

        # -------------------------------------------------- Ginormosia
        gn = ttk.LabelFrame(f, text="Ginormosia", padding=10)
        gn.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(gn, wraplength=980, foreground=GREY,
                  text="Zone ranks (1 to %d), the camps, and the twenty "
                       "shrines. The clouds over the map are none of these -- "
                       "they are the eye towers, below."
                       % MAX_RANK).pack(anchor="w")

        gmid = ttk.Frame(gn)
        gmid.pack(fill="both", expand=True, pady=(6, 0))
        gcols = ("rank", "points")
        self.tree_area = ttk.Treeview(gmid, columns=gcols,
                                      show="tree headings", height=8)
        self.tree_area.heading("#0", text="area")
        self.tree_area.column("#0", width=340)
        for c, w in zip(gcols, (80, 120)):
            self.tree_area.heading(c, text=c)
            self.tree_area.column(c, width=w, anchor="w")
        self.tree_area.pack(side="left", fill="both", expand=True)
        gsb = ttk.Scrollbar(gmid, orient="vertical",
                            command=self.tree_area.yview)
        self.tree_area.configure(yscrollcommand=gsb.set)
        gsb.pack(side="right", fill="y")
        self.tree_area.bind("<<TreeviewSelect>>", self.on_pick_area)

        ged = ttk.LabelFrame(gn, text="Zone rank", padding=10)
        ged.pack(fill="x", pady=(8, 0))
        ttk.Label(ged, text="rank").grid(row=0, column=0, padx=(0, 3))
        self.cmb_area_rank = ttk.Combobox(
            ged, state="readonly", width=5,
            values=[str(i) for i in range(1, MAX_RANK + 1)])
        self.cmb_area_rank.grid(row=0, column=1)
        ttk.Label(ged, text="points").grid(row=0, column=2, padx=(14, 3))
        self.ent_area_points = ttk.Entry(ged, width=12)
        self.ent_area_points.grid(row=0, column=3)
        ttk.Label(ged, text="leave the points blank to use whatever that rank "
                            "needs", foreground=GREY
                  ).grid(row=0, column=4, sticky="w", padx=(10, 0))
        ttk.Button(ged, text="Apply to this zone",
                   command=lambda: self.guard(self.on_apply_area, False)
                   ).grid(row=0, column=5, padx=(18, 6))
        ttk.Button(ged, text="Apply to every zone",
                   command=lambda: self.guard(self.on_apply_area, True)
                   ).grid(row=0, column=6)

        tw = ttk.LabelFrame(gn, text="Eye towers", padding=10)
        tw.pack(fill="x", pady=(8, 0))
        ttk.Label(tw, wraplength=980, foreground=GREY,
                  text="One eye tower per zone; lighting it clears that zone's "
                       "map area. Unlock every map area opens the warp points "
                       "too."
                  ).pack(anchor="w")

        self._tower_rows, self._tower_numbers = {}, []   # filled on refresh
        trow = ttk.Frame(tw)
        trow.pack(fill="x", pady=(8, 0))
        ttk.Label(trow, text="eye").pack(side="left", padx=(0, 4))
        self.cmb_tower = ttk.Combobox(trow, state="readonly", width=32)
        self.cmb_tower.pack(side="left")
        self.cmb_tower.bind("<<ComboboxSelected>>", self.on_pick_tower)
        self.var_tower_lit = tk.BooleanVar(value=False)
        ttk.Checkbutton(trow, text="map area unlocked",
                        variable=self.var_tower_lit).pack(side="left", padx=12)
        ttk.Button(trow, text="Apply to this eye",
                   command=lambda: self.guard(self.on_apply_tower)
                   ).pack(side="left")
        ttk.Separator(trow, orient="vertical").pack(side="left", fill="y",
                                                    padx=10)
        ttk.Button(trow, text="Unlock every map area",
                   command=lambda: self.guard(self.on_light_towers)
                   ).pack(side="left")
        self.lbl_tower = ttk.Label(trow, text="", foreground=GREY)
        self.lbl_tower.pack(side="left", padx=10)

        grow = ttk.Frame(gn)
        grow.pack(fill="x", pady=(8, 0))
        for text, what in (("Discover every camp", "camps"),
                           ("Reveal every shrine", "shrines")):
            ttk.Button(grow, text=text,
                       command=lambda w=what: self.guard(self.on_ginormosia, w)
                       ).pack(side="left", padx=(0, 6))
        ttk.Separator(grow, orient="vertical").pack(side="left", fill="y",
                                                    padx=8)
        ttk.Button(grow, text="Unlock everything",
                   command=lambda: self.guard(self.on_ginormosia, "all")
                   ).pack(side="left")
        self.lbl_gino = ttk.Label(grow, text="", foreground=GREY)
        self.lbl_gino.pack(side="left", padx=10)

        def wheel(evt):
            canvas.yview_scroll(-3 if evt.delta > 0 else 3, "units")
            return "break"

        def wire(w):
            # Tables keep their own wheel; a combobox loses it, so that
            # scrolling past one cannot quietly change what it is set to.
            if not isinstance(w, ttk.Treeview):
                w.bind("<MouseWheel>", wheel)
            for child in w.winfo_children():
                wire(child)
        wire(f)
        canvas.bind("<MouseWheel>", wheel)
        return outer

    def refresh_world(self):
        keep = self.tree_area.selection()      # before the rows go away
        for tree in (self.tree_board, self.tree_area):
            tree.delete(*tree.get_children())
        self.lbl_board.configure(text="")
        self.lbl_tower.configure(text="")
        self.lbl_gino.configure(text="")
        if self.save is None:
            self.cmb_zone["values"] = []
            self.cmb_tower["values"] = []
            self.cmb_tower.set("")
            return

        rows = self.save.board_rows(self.lang())
        for r in rows:
            self.tree_board.insert("", "end", iid=r["key"], text=r["name"],
                                   values=(r["total"], r["complete"],
                                           r["open"], r["hidden"]))
        labels = [r["name"] for r in rows] + ["Every zone"]
        self._zone_keys = [r["key"] for r in rows] + ["all"]
        self.cmb_zone["values"] = labels
        if self.cmb_zone.get() not in labels:
            self.cmb_zone.set(labels[0])
        self.lbl_board.configure(
            text="%d of %d jobs finished"
                 % (sum(r["complete"] for r in rows),
                    sum(r["total"] for r in rows)))

        on_eye = self.selected_tower()         # before the labels are rebuilt
        rows = self.save.tower_rows(self.lang())
        self._tower_rows = {r["number"]: r for r in rows}
        self._tower_numbers = [r["number"] for r in rows]
        self.cmb_tower["values"] = [
            "%d.  %s  -  %s" % (r["number"], r["name"],
                                "unlocked" if r["lit"] else "covered")
            for r in rows]
        self.pick_tower(on_eye if on_eye in self._tower_rows
                        else (self._tower_numbers[0] if rows else None))
        self.lbl_tower.configure(
            text="%d of %d unlocked" % (sum(1 for r in rows if r["lit"]),
                                       len(rows))
            if rows else "no eye-tower flags in this save")

        hm = self.save.ginormosia
        if hm is None:
            self.lbl_gino.configure(text="no Ginormosia block in this save")
            return
        for r in self.save.ginormosia_rows(self.lang()):
            self.tree_area.insert("", "end", iid=r["area_id"], text=r["name"],
                                  values=(r["rank"], "{:,}".format(r["points"])))
        still = [i for i in keep if self.tree_area.exists(i)]
        if still:
            self.tree_area.selection_set(still)
        self.lbl_gino.configure(
            text="%d/%d camps, %d/%d shrines found, %d cleared"
                 % (len(hm.camps), len(ALL_CAMPS), len(hm.found),
                    len(hm.shrines), sum(1 for x in hm.shrines if x.cleared)))

    def selected_zone(self) -> str:
        labels = list(self.cmb_zone["values"])
        try:
            return self._zone_keys[labels.index(self.cmb_zone.get())]
        except (ValueError, AttributeError, IndexError):
            return "all"

    def selected_tower(self):
        """Which eye the dropdown is on, as a 1-based number, or None."""
        try:
            return self._tower_numbers[
                list(self.cmb_tower["values"]).index(self.cmb_tower.get())]
        except (ValueError, AttributeError, IndexError):
            return None

    def pick_tower(self, number):
        """Put the dropdown on one eye and fill the tick box from the save."""
        try:
            i = self._tower_numbers.index(number)
        except (ValueError, AttributeError):
            self.cmb_tower.set("")
            return
        self.cmb_tower.current(i)
        self.var_tower_lit.set(self._tower_rows[number]["lit"])

    def on_pick_tower(self, _evt=None):
        """The tick box follows whichever eye is chosen."""
        self.pick_tower(self.selected_tower())

    def on_complete_board(self):
        sf = self.need()
        key = self.selected_zone()
        if key == "all":
            total = sum(sf.complete_all_boards().values())
            where = "every zone"
        else:
            total = sf.complete_board(key)
            where = sf.place_name(BOARD_BY_KEY[key].map_id, self.lang())
        self.refresh_world()
        if not total:
            self.say("%s: every job was already finished" % where)
            return
        self.touch("%s: %d job(s) completed" % (where, total))

    def on_pick_area(self, _evt=None):
        """Fill the rank boxes from whichever zone is selected."""
        sel = self.tree_area.selection()
        if not sel or self.save is None:
            return
        hm = self.save.ginormosia
        if hm is None:
            return
        try:
            a = hm.area(sel[0])
        except KeyError:
            return
        self.cmb_area_rank.set(str(a.rank))
        self.ent_area_points.delete(0, "end")
        self.ent_area_points.insert(0, str(a.points))

    def on_apply_area(self, everyone):
        sf = self.need()
        hm = sf.ginormosia
        if hm is None:
            raise RuntimeError("this save has no Ginormosia block")
        rank = as_int(self.cmb_area_rank.get(), 0)
        if not 1 <= rank <= MAX_RANK:
            raise ValueError("pick a rank between 1 and %d" % MAX_RANK)
        text = self.ent_area_points.get().strip()
        points = None
        if text:
            try:
                points = as_int(text)
            except ValueError:
                raise ValueError("%r is not a number of points" % text)
            if points < 0:
                raise ValueError("points cannot be negative")

        if everyone:
            for a in list(hm.areas):
                hm.set_area_rank(a.area_id, rank, points)
            where = "every zone"
        else:
            sel = self.tree_area.selection()
            if not sel:
                raise RuntimeError("pick a zone in the table first")
            a = hm.set_area_rank(sel[0], rank, points)
            where = sf.place_name(a.text_key, self.lang())
        sf.flush_world()
        self.refresh_world()
        self.touch("%s: rank %d%s"
                   % (where, rank,
                      "" if points is None else ", %d points" % points))

    def on_apply_tower(self):
        """Unlock or re-cover the map area of the eye the dropdown is on."""
        sf = self.need()
        n = self.selected_tower()
        if n is None:
            raise RuntimeError("this save has no eye-tower flags")
        want = bool(self.var_tower_lit.get())
        name = self._tower_rows[n]["name"]
        changed = sf.set_tower(n, want)
        self.refresh_world()           # puts the dropdown back on this eye
        if not changed:
            self.say("%s: its map area was already %s"
                     % (name, "unlocked" if want else "covered"))
            return
        self.touch("%s: map area %s"
                   % (name, "unlocked" if want else "covered"))

    def on_light_towers(self):
        """Every eye at once - the flags and their warp points together."""
        sf = self.need()
        r = sf.unlock_towers()
        self.refresh_world()
        if not r["towers"] and not r["travel_points"]:
            self.say("every map area was already unlocked")
            return
        self.touch("%d map area(s) unlocked, %d travel point(s) opened"
                   % (len(r["towers"]), len(r["travel_points"])))

    def on_ginormosia(self, what):
        sf = self.need()
        if sf.ginormosia is None:
            raise RuntimeError("this save has no Ginormosia block")
        r = sf.unlock_ginormosia(open_zones=False,
                                 camps=what in ("camps", "all"),
                                 ranks=what == "ranks",
                                 reveal=what in ("shrines", "all"),
                                 clear=what in ("shrines", "all"))
        bits = []
        if r["opened"]:
            bits.append("%d zone(s) uncovered" % len(r["opened"]))
        if r["camps"]:
            bits.append("%d camp(s) unlocked" % len(r["camps"]))
        if r["ranks"]:
            bits.append("%d area(s) at rank %d" % (r["ranks"], MAX_RANK))
        if r["revealed"]:
            bits.append("%d shrine(s) revealed" % len(r["revealed"]))
        if r["cleared"]:
            bits.append("%d shrine(s) cleared" % r["cleared"])
        self.refresh_world()
        if not bits:
            self.say("Ginormosia: nothing left to unlock there")
            return
        self.touch("Ginormosia: " + ", ".join(bits))

    # ---------------------------------------------------------------- tools
    # ------------------------------------------------------------ base camp
    def _tab_camp(self, parent):
        # Two tables and the share panel do not fit at the default height, so
        # this tab scrolls the way the World tab does.
        outer = ttk.Frame(parent)
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        wsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=wsb.set)
        wsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        f = ttk.Frame(canvas, padding=10)
        window = canvas.create_window((0, 0), window=f, anchor="nw")

        def fit(_evt=None):
            canvas.itemconfigure(window, width=canvas.winfo_width())
            canvas.configure(scrollregion=canvas.bbox("all"))
        f.bind("<Configure>", fit)
        canvas.bind("<Configure>", fit)

        ttk.Label(f, wraplength=980, foreground=GREY,
                  text="The island in the present: the ground you sculpted, "
                       "the water and the cliffs you cut into it, the roads, "
                       "the buildings and everything placed on them. All of it "
                       "sits in one block of the save, which is what makes a "
                       "whole layout something you can hand to someone else."
                  ).pack(anchor="w")
        self.lbl_camp = ttk.Label(f, text="-", style="Head.TLabel")
        self.lbl_camp.pack(anchor="w", pady=(8, 0))
        self.lbl_camp2 = ttk.Label(f, text="", foreground=GREY, wraplength=980,
                                   justify="left")
        self.lbl_camp2.pack(anchor="w")

        # --------------------------------------------------------- share
        sh = ttk.LabelFrame(f, text="Share this island", padding=10)
        sh.pack(fill="x", pady=(12, 0))
        ttk.Label(sh, wraplength=980, foreground=GREY,
                  text="An export is one small file holding the whole layout: "
                       "every tile, every object and where it stands, the "
                       "houses and the rooms inside them. Anyone with this "
                       "editor can import it into their own save."
                  ).pack(anchor="w")

        erow = ttk.Frame(sh)
        erow.pack(fill="x", pady=(8, 0))
        ttk.Label(erow, text="note").pack(side="left", padx=(0, 4))
        self.ent_camp_note = ttk.Entry(erow, width=44)
        self.ent_camp_note.pack(side="left")
        ttk.Label(erow, text="a line of your own, stored in the file",
                  foreground=GREY).pack(side="left", padx=8)
        ttk.Button(erow, text="Export layout...",
                   command=lambda: self.guard(self.on_camp_export)
                   ).pack(side="left", padx=(10, 0))

        irow = ttk.Frame(sh)
        irow.pack(fill="x", pady=(10, 0))
        ttk.Label(irow, text="bring across").pack(side="left", padx=(0, 4))
        self.cmb_camp_scope = ttk.Combobox(
            irow, state="readonly", width=40,
            values=[label for label, _key in CAMP_SCOPES])
        self.cmb_camp_scope.current(0)
        self.cmb_camp_scope.pack(side="left")
        self.cmb_camp_scope.bind("<<ComboboxSelected>>",
                                 lambda _e: self.describe_camp_scope())
        self.var_camp_ok = tk.BooleanVar(value=False)
        ttk.Checkbutton(irow, text="replace what I have now",
                        variable=self.var_camp_ok).pack(side="left", padx=12)
        ttk.Button(irow, text="Import layout...",
                   command=lambda: self.guard(self.on_camp_import)
                   ).pack(side="left")
        self.lbl_camp_scope = ttk.Label(sh, text="", foreground=GREY,
                                        wraplength=980, justify="left")
        self.lbl_camp_scope.pack(anchor="w", pady=(6, 0))
        self.describe_camp_scope()

        # ------------------------------------------------- what is on it
        wb = ttk.LabelFrame(f, text="On the island", padding=10)
        wb.pack(fill="both", expand=True, pady=(12, 0))
        wrow = ttk.Frame(wb)
        wrow.pack(fill="x")
        ttk.Label(wrow, text="show").pack(side="left", padx=(0, 4))
        self.cmb_camp_kind = ttk.Combobox(
            wrow, state="readonly", width=34,
            values=[label for label, _key in CAMP_KINDS])
        self.cmb_camp_kind.current(0)
        self.cmb_camp_kind.pack(side="left")
        self.cmb_camp_kind.bind("<<ComboboxSelected>>",
                                lambda _e: self.refresh_camp_list())
        self.lbl_camp_kind = ttk.Label(wrow, text="", foreground=GREY)
        self.lbl_camp_kind.pack(side="left", padx=10)

        wmid = ttk.Frame(wb)
        wmid.pack(fill="both", expand=True, pady=(6, 0))
        ccols = ("count", "id")
        self.tree_camp = ttk.Treeview(wmid, columns=ccols,
                                      show="tree headings", height=7)
        self.tree_camp.heading("#0", text="what")
        self.tree_camp.column("#0", width=420)
        for c, w in zip(ccols, (80, 240)):
            self.tree_camp.heading(c, text=c)
            self.tree_camp.column(c, width=w, anchor="w")
        self.tree_camp.pack(side="left", fill="both", expand=True)
        csb = ttk.Scrollbar(wmid, orient="vertical",
                            command=self.tree_camp.yview)
        self.tree_camp.configure(yscrollcommand=csb.set)
        csb.pack(side="right", fill="y")

        # -------------------------------------------------------- houses
        hb = ttk.LabelFrame(f, text="Houses", padding=10)
        hb.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(hb, wraplength=980, foreground=GREY,
                  text="Every building the game treats as a home, and where "
                       "that building stands. The player's own is the one "
                       "whose door leads to Map_MyHouse."
                  ).pack(anchor="w")
        hmid = ttk.Frame(hb)
        hmid.pack(fill="both", expand=True, pady=(6, 0))
        hcols = ("whose", "door leads to", "rooms", "standing at", "facing")
        self.tree_house = ttk.Treeview(hmid, columns=hcols,
                                       show="tree headings", height=6)
        self.tree_house.heading("#0", text="house")
        self.tree_house.column("#0", width=300)
        for c, w in zip(hcols, (100, 170, 60, 190, 70)):
            self.tree_house.heading(c, text=c)
            self.tree_house.column(c, width=w, anchor="w")
        self.tree_house.pack(side="left", fill="both", expand=True)
        hsb = ttk.Scrollbar(hmid, orient="vertical",
                            command=self.tree_house.yview)
        self.tree_house.configure(yscrollcommand=hsb.set)
        hsb.pack(side="right", fill="y")

        def wheel(evt):
            canvas.yview_scroll(-3 if evt.delta > 0 else 3, "units")
            return "break"

        def wire(w):
            # Tables keep their own wheel; a combobox loses it, so that
            # scrolling past one cannot quietly change what it is set to.
            if not isinstance(w, ttk.Treeview):
                w.bind("<MouseWheel>", wheel)
            for child in w.winfo_children():
                wire(child)
        wire(f)
        canvas.bind("<MouseWheel>", wheel)
        return outer

    def camp_kind(self) -> str:
        return CAMP_KINDS[max(0, self.cmb_camp_kind.current())][1]

    def camp_scope(self) -> str:
        return CAMP_SCOPES[max(0, self.cmb_camp_scope.current())][1]

    def describe_camp_scope(self):
        self.lbl_camp_scope.configure(text=CAMP_SCOPE_HELP[self.camp_scope()])

    def refresh_camp(self):
        self.tree_house.delete(*self.tree_house.get_children())
        self.lbl_camp2.configure(text="")
        if self.save is None:
            self.lbl_camp.configure(text="-")
            self.refresh_camp_list()
            return
        camp = self.save.base_camp
        if camp is None:
            self.lbl_camp.configure(text="this save has no Base Camp block")
            self.lbl_camp2.configure(text=self.save.base_camp_error or "")
            self.refresh_camp_list()
            return
        c = camp.counts()
        self.lbl_camp.configure(text="%d of %d object slots in use"
                                     % (c["used"], c["slots"]))
        self.lbl_camp2.configure(
            text="ground %d, water %d, %d cliff face(s) over %d height "
                 "level(s), roads %d   --   buildings %d, furniture %d, "
                 "obstacles %d, houses %d"
                 % (c["ground"], c["water"], c["cliffs"], c["levels"],
                    c["roads"], c["buildings"], c["furniture"], c["obstacles"],
                    c["houses"]))
        for h in self.save.house_rows(self.lang()):
            pos = ("%.0f, %.0f, %.0f" % h["position"]) if h["position"] else "-"
            face = ("%.0f deg" % h["rotation"]) if h["rotation"] is not None \
                else "-"
            self.tree_house.insert("", "end", text=h["name"],
                                   values=(h["kind"], h["entrance"],
                                           h["rooms"], pos, face))
        self.refresh_camp_list()

    def refresh_camp_list(self):
        self.tree_camp.delete(*self.tree_camp.get_children())
        self.lbl_camp_kind.configure(text="")
        if self.save is None or self.save.base_camp is None:
            return
        rows = self.save.base_camp_rows(self.camp_kind(), self.lang())
        for r in rows:
            self.tree_camp.insert("", "end", text=r["name"],
                                  values=(r["count"], r["id"]))
        self.lbl_camp_kind.configure(
            text="%d kind(s), %d in all"
                 % (len(rows), sum(r["count"] for r in rows)))

    def on_camp_export(self):
        sf = self.need()
        if sf.base_camp is None:
            raise RuntimeError("this save has no Base Camp block")
        path = filedialog.asksaveasfilename(
            title="Export island layout", defaultextension=".flicamp",
            initialfile="island.flicamp",
            filetypes=[("Island layout", "*.flicamp"),
                       ("Readable JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        got = sf.export_base_camp(path, note=self.ent_camp_note.get().strip())
        self.say("layout written: %s (%.0f KB, %d objects, %d houses)"
                 % (os.path.basename(path), got["bytes"] / 1024.0,
                    got["used"], got["houses"]))

    def on_camp_import(self):
        sf = self.need()
        if sf.base_camp is None:
            raise RuntimeError("this save has no Base Camp block")
        if not self.var_camp_ok.get():
            messagebox.showinfo(APP, IMPORT_UNCONFIRMED)
            return
        path = filedialog.askopenfilename(
            title="Import island layout",
            filetypes=[("Island layout", "*.flicamp *.json"),
                       ("All files", "*.*")])
        if not path:
            return
        got = sf.import_base_camp(path, self.camp_scope())
        self.var_camp_ok.set(False)
        note = ("; " + "; ".join(got["kept_levels"])) if got["kept_levels"] else ""
        self.touch("island imported (%s): %d object(s), %d house(s)%s -- Save "
                   "to write it to the file"
                   % (got["scope"], got["used"], got["houses"], note))
        self.refresh_camp()

    def _tab_tools(self, parent):
        f = ttk.Frame(parent, padding=10)

        hb = ttk.LabelFrame(f, text="Value hunter", padding=10)
        hb.pack(fill="x")
        ttk.Label(hb, text="value shown in game").grid(row=0, column=0, sticky="w")
        self.ent_hval = ttk.Entry(hb, width=14)
        self.ent_hval.grid(row=0, column=1, padx=4)
        ttk.Label(hb, text="type").grid(row=0, column=2, padx=(12, 2))
        self.cmb_htype = ttk.Combobox(hb, state="readonly", width=6,
                                      values=list(HUNT_TYPES))
        self.cmb_htype.set("u32")
        self.cmb_htype.grid(row=0, column=3)
        ttk.Button(hb, text="First scan",
                   command=lambda: self.on_hunt(True)).grid(row=0, column=4, padx=8)
        ttk.Button(hb, text="Narrow",
                   command=lambda: self.on_hunt(False)).grid(row=0, column=5)
        ttk.Label(hb, text="scan, change the value in game, save, load the new "
                           "file, then Narrow", foreground=GREY
                  ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(6, 0))

        pb = ttk.LabelFrame(f, text="Read / write an offset", padding=10)
        pb.pack(fill="x", pady=10)
        ttk.Label(pb, text="at").grid(row=0, column=0, sticky="w")
        self.ent_at = ttk.Entry(pb, width=14)
        self.ent_at.grid(row=0, column=1, padx=4)
        ttk.Label(pb, text="type").grid(row=0, column=2, padx=(12, 2))
        self.cmb_ptype = ttk.Combobox(pb, state="readonly", width=6,
                                      values=list(HUNT_TYPES))
        self.cmb_ptype.set("u32")
        self.cmb_ptype.grid(row=0, column=3)
        ttk.Label(pb, text="value").grid(row=0, column=4, padx=(12, 2))
        self.ent_pval = ttk.Entry(pb, width=14)
        self.ent_pval.grid(row=0, column=5, padx=4)
        ttk.Button(pb, text="Read", command=self.on_read).grid(row=0, column=6, padx=8)
        ttk.Button(pb, text="Write", command=self.on_write).grid(row=0, column=7)
        ttk.Button(pb, text="Hex dump", command=self.on_dump).grid(row=0, column=8,
                                                                   padx=8)

        out = ttk.LabelFrame(f, text="Output", padding=6)
        out.pack(fill="both", expand=True)
        self.txt_out = tk.Text(out, wrap="none", height=14, font=("Consolas", 9),
                               relief="flat")
        sb = ttk.Scrollbar(out, orient="vertical", command=self.txt_out.yview)
        self.txt_out.configure(yscrollcommand=sb.set)
        self.txt_out.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return f

    # -------------------------------------------------------------- helpers
    def lang(self) -> str:
        return self.cmb_lang.get() or "en"

    def say(self, msg):
        self.status.configure(text=msg)

    def out(self, msg):
        self.txt_out.insert("end", msg + "\n")
        self.txt_out.see("end")

    def need(self) -> SaveFile:
        if self.save is None:
            raise RuntimeError("open a save file first")
        return self.save

    def touch(self, msg=None):
        self.dirty = True
        self.retitle()
        if msg:
            self.say(msg + "  -  press Save to write it to disk")

    def retitle(self):
        name = os.path.basename(self.path) if self.path else "no file"
        self.master.title("%s%s - %s" % ("*" if self.dirty else "", name, APP))
        self.lbl_file.configure(
            text="%s%s" % (name, " (unsaved changes)" if self.dirty else ""))

    def guard(self, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror(APP, str(exc))
            self.say("error: %s" % exc)

    # ------------------------------------------------------------- file ops
    def on_open(self):
        if not self.confirm_discard():
            return
        found = find_saves()
        path = filedialog.askopenfilename(
            title="Open a Fantasy Life i save",
            initialdir=os.path.dirname(found[0]) if found else guess_dir(),
            initialfile=os.path.basename(found[0]) if found else "",
            filetypes=[("Fantasy Life i save", "*.bin"), ("All files", "*.*")])
        if path:
            self.guard(self.load, path)

    def load(self, path):
        try:
            self.save = SaveFile.load(path)
        except Exception as exc:
            if "MD5" not in str(exc):
                raise
            if not messagebox.askyesno(APP, "%s\n\nLoad anyway?" % exc):
                return
            self.save = SaveFile.load(path, verify=False)
        self.path = path
        self.dirty = False
        self.hunt = Hunt()
        if self.refresh_containers():
            self.cmb_cont.current(0)
        self.refresh_all()
        self.say("loaded %s  (%d byte payload)" % (path, len(self.save.payload)))

    def on_save(self):
        def go():
            sf = self.need()
            path = sf.write(self.path, backup=True)
            self.dirty = False
            self.retitle()
            self.refresh_all()
            self.say("saved %s  (a .bak of the previous file is next to it)" % path)
        self.guard(go)

    def on_save_as(self):
        def go():
            sf = self.need()
            path = filedialog.asksaveasfilename(
                title="Save as", initialdir=guess_dir(), defaultextension=".bin",
                filetypes=[("Fantasy Life i save", "*.bin")])
            if not path:
                return
            sf.write(path, backup=True)
            self.path = path
            self.dirty = False
            self.retitle()
            self.say("saved %s" % path)
        self.guard(go)

    def on_export(self):
        def go():
            sf = self.need()
            path = filedialog.asksaveasfilename(
                title="Export the raw payload", defaultextension=".gvas",
                filetypes=[("GVAS payload", "*.gvas"), ("All files", "*.*")])
            if path:
                self.say("wrote %d bytes to %s" % (sf.export_payload(path), path))
        self.guard(go)

    def on_import(self):
        def go():
            sf = self.need()
            path = filedialog.askopenfilename(
                title="Import a raw payload",
                filetypes=[("GVAS payload", "*.gvas"), ("All files", "*.*")])
            if not path:
                return
            sf.import_payload(path)
            self.refresh_all()
            self.touch("imported %s" % path)
        self.guard(go)

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        return messagebox.askyesno(
            APP, "This save has changes you have not written to disk.\n\n"
                 "Throw them away?")

    def on_close(self):
        if self.confirm_discard():
            self.master.destroy()

    # -------------------------------------------------------------- refresh
    def refresh_all(self):
        self.refresh_character()
        self.refresh_items()
        self.refresh_lives()
        self.refresh_world()
        self.refresh_camp()
        self.retitle()

    def on_lang(self):
        self.refresh_character()
        self.refresh_items()
        self.refresh_lives()
        self.refresh_world()
        self.refresh_camp()
        self.say("names shown in %s" % self.lang())

    def refresh_character(self):
        self.txt_info.delete("1.0", "end")
        for e in (self.ent_name, self.ent_money, self.ent_hp, self.ent_hp_max,
                  self.ent_sp, self.ent_sp_max):
            e.delete(0, "end")
        coin = self.icons.currency("coin", iconset.SMALL)
        self.lbl_coin.configure(image=coin or "")
        if self.save is None:
            self.lbl_who.configure(text="-")
            self.lbl_life.configure(text="")
            self.lbl_life_icon.configure(image="")
            self.lbl_meta.configure(text="open a save to see it here")
            return

        sf = self.save
        db = namedb.get()
        self.txt_info.insert("1.0", sf.info())

        ch = sf.character
        if ch is not None:
            self.ent_name.insert(0, ch.name)
            self.ent_hp.insert(0, str(ch.hp))
            self.ent_hp_max.insert(0, str(ch.hp_max))
            self.ent_sp.insert(0, str(ch.sp))
            self.ent_sp_max.insert(0, str(ch.sp_max))
            self.lbl_who.configure(text=ch.name)
            emblem = self.icons.life(ch.life_id, iconset.LARGE)
            self.lbl_life_icon.configure(image=emblem or "")
            row = next((r for r in sf.life_rows(self.lang())
                        if r["life_id"] == ch.life_id), None)
            life_name = db.life_name(ch.life_id, self.lang()) or ch.life_id
            if row:
                self.lbl_life.configure(
                    text="%s  -  level %s, %s"
                         % (life_name, row.get("level", "?"),
                            row.get("rank_name") or "no rank"))
            else:
                self.lbl_life.configure(text=life_name)
        else:
            self.lbl_who.configure(text="(no character block)")
            self.lbl_life.configure(text="")
            self.lbl_life_icon.configure(image="")

        if sf.money is not None:
            self.ent_money.insert(0, str(sf.money))
        for kind, box in self.ent_currency.items():
            box.delete(0, "end")
            amount = sf.currency(kind)
            box.insert(0, "-" if amount is None else str(amount))
            box.configure(state="normal" if amount is not None else "disabled")
        saved, made = sf.timestamps()
        map_name, warp = sf.location()
        self.lbl_meta.configure(text="\n".join((
            "last saved   %s" % (saved.strftime("%Y-%m-%d %H:%M") if saved else "?"),
            "created      %s" % (made.strftime("%Y-%m-%d %H:%M") if made else "?"),
            "map          %s" % (map_name or "?"),
            "warp point   %s" % (warp or "-"),
            "payload      %d bytes" % len(sf.payload),
        )))

    def cur_array(self):
        if self.save is None or self.save.items is None:
            return None
        i = self.cmb_cont.current()
        arrays = self.save.items.arrays
        return arrays[i] if 0 <= i < len(arrays) else None

    def refresh_containers(self):
        """Rebuild the container list, keeping the used counts honest."""
        sec = self.save.items if self.save else None
        names = ["[%d] %s  -  %d/%d used" % (a.index, a.label, a.used, a.count)
                 for a in (sec.arrays if sec else [])]
        keep = self.cmb_cont.current()
        self.cmb_cont["values"] = names
        if names and 0 <= keep < len(names):
            self.cmb_cont.current(keep)
        return names

    def bulk_equipment(self, arr=None) -> bool:
        """Whether the bag on screen keeps a record per piece rather than a count."""
        arr = arr or self.cur_array()
        return bool(arr and arr.records and arr.records[0].equipment)

    def sync_bulk_buttons(self):
        """Offer the bulk fills only on the bags they apply to.

        "Give every ..." exists for the bags whose whole contents are worth
        having at once, and setting every quantity only means anything where the
        items stack -- equipment has no count, and a number written into one of
        those records lands on its crafting grade instead.

        The panel is only rebuilt when the container changes kind, because
        every edit refreshes the table and rebuilding it would throw away the
        quantity and the grade the user had just typed in.
        """
        arr = self.cur_array()
        stacks = bool(arr and arr.records and arr.records[0].stackable)
        if stacks:
            self.btn_set_qty.pack(side="left", padx=(0, 6))
        else:
            self.btn_set_qty.pack_forget()

        fill = BULK_FILLS.get(arr.index) if arr else None
        if fill is None:
            self.bulk.pack_forget()
            self._bulk_kind = None
            return
        kind, one = fill
        if kind != self._bulk_kind:
            self._bulk_kind = kind
            equipment = self.bulk_equipment(arr)
            self.btn_bulk.configure(text="Give every %s" % one)
            self.lbl_bulk_qty.configure(
                text="copies of each" if equipment else "of each")
            self.spn_bulk_qty.delete(0, "end")
            self.spn_bulk_qty.insert(
                0, str(STACK_FULL if kind in BULK_FULL_STACK else 1))
            for w in (self.lbl_bulk_grade, self.cmb_bulk_title, self.chk_bulk_op):
                w.pack_forget()
                if equipment:
                    w.pack(side="left", padx=(12, 0))
            self.describe_bulk()
        self.bulk.pack(side="bottom", fill="x", pady=(8, 0), before=self.frm_slot)

    def bulk_title(self):
        """The grade the fill spawns at, or None for each item's own best."""
        i = self.cmb_bulk_title.current()
        return None if i <= 0 else i - 1

    def describe_bulk(self):
        """Say what the fill will write, the way the Super OP line does."""
        if self._bulk_kind is None:
            return
        if not self.bulk_equipment():
            note = ("these stack, so each item lands in one slot holding that "
                    "many - a record that is only a count has nowhere to keep "
                    "a grade")
            if self._bulk_kind == "recipes":
                note += ("  -  the scrolls are half of a recipe, so this marks "
                         "them known too, which is what a crafting bench reads")
            self.lbl_bulk_note.configure(text=note)
            return
        title = self.bulk_title()
        bits = ["every piece is its own slot, so the number is how many copies "
                "of each item",
                "grade: %s" % (items.ITEM_TITLES[title] if title is not None
                               else "the best one each item has stats for")]
        if self.var_bulk_op.get():
            bits.append("a %d-year vintage, top quality and the three skills "
                        "the Aging Altar rolls for that kind of gear"
                        % items.OP_RIPENING_AGE)
        warning = self.grade_note(self._bulk_kind, title)
        if warning:
            bits.append(warning)
        self.lbl_bulk_note.configure(text="  -  ".join(bits))

    def grade_note(self, kind, title) -> str:
        """What is worth saying about spawning a whole bag at one grade.

        One grade across a bag is this fill's own footgun, and there are two
        different unknowns behind it.  An item the database *has* a stat list
        for but no entry at this grade reads as zero in game, which is worth
        counting.  A bag it has no stat lists for at all -- armour, whose rows
        the builder cannot pin down -- cannot be checked either way, and saying
        so is better than saying nothing.  Grade 0 is neither: it has no entry
        of its own in the lists, which is why the per-item picker leaves it
        unannotated too.
        """
        if not title:
            return ""
        sentinel = gear.get().sentinel
        misses = checked = 0
        for item_id in gear.every(kind):
            stat = gear.attack(item_id, title)
            if stat is None:
                continue
            checked += 1
            misses += stat <= sentinel
        if not checked:
            return ("the database has no stat lists for these, so a grade "
                    "cannot be checked here - untitled is what the game itself "
                    "writes on them")
        if misses:
            return ("careful: %d of them have no stats at that grade and would "
                    "read as zero" % misses)
        return ""

    def refresh_items(self):
        self.refresh_containers()
        self.sync_bulk_buttons()
        for i in self.tree.get_children():
            self.tree.delete(i)
        arr = self.cur_array()
        if arr is None:
            return
        needle = self.ent_filter.get().strip().lower()
        lang = self.lang()
        for r in arr.records:
            if r.empty and not self.var_empty.get():
                continue
            name = self.save.item_name(r.item_id, lang) if not r.empty else ""
            if needle and needle not in r.item_id.lower() \
                    and needle not in name.lower():
                continue
            atk = gear.attack(r.item_id, r.item_title) if r.equipment else None
            age = r.ripening_age if r.equipment and not r.empty else 0
            self.tree.insert(
                "", "end", iid=str(r.index),
                text="  %4d   %s" % (r.index, name or ("-" if r.empty else r.item_id)),
                image=self.icons.item(r.item_id, iconset.SMALL) or "",
                values=(r.item_id if not r.empty else "", r.quantity or "",
                        r.title_name if not r.empty else "",
                        "" if atk is None or r.empty else atk,
                        "%d yr" % age if age else ""))

    def refresh_lives(self):
        for i in self.tree_life.get_children():
            self.tree_life.delete(i)
        db = namedb.get()
        ranks, i = [], 0
        while True:
            name = db.life_rank_name(i, self.lang())
            if not name or i > 32:
                break
            ranks.append(name)
            i += 1
        if not ranks:                      # no name database - plain numbers
            ranks = [str(n) for n in range(8)]
        self.cmb_rank["values"] = ["%d  %s" % (i, r) for i, r in enumerate(ranks)]
        # 0 is "not started" and the last row is as high as a Life goes; the
        # recipe panel needs it to tell a rank that is holding a bench back.
        self._max_life_rank = len(ranks) - 1
        if self.save is None:
            return
        try:
            rows = self.save.life_rows(self.lang())
        except Exception as exc:
            self.say("per-Life arrays unavailable: %s" % exc)
            return
        for r in rows:
            self.tree_life.insert(
                "", "end", iid=r["life_id"],
                text="  " + (r.get("name") or r["life_id"]),
                image=self.icons.life(r["life_id"], iconset.SMALL) or "",
                values=(r.get("rank", "-"), r.get("rank_name", ""),
                        r.get("rank_points", "-"), r.get("level", "-"),
                        r.get("exp", "-"), r.get("pa", "-")))
        self.refresh_recipes()

    def refresh_recipes(self):
        """Refill the recipe dropdown, each entry carrying its own count.

        The rows are kept, because reading them walks the whole recipe table
        and the tick box below wants the same numbers.
        """
        self._recipe_lives = []
        rows = [] if self.save is None else self.save.recipe_rows(self.lang())
        self._recipe_rows = {r["life_id"]: r for r in rows}
        if not rows:
            self.cmb_recipe["values"] = []
            self.cmb_recipe.set("")
            self.lbl_recipe.configure(
                text="this save has no recipe table"
                     if self.save is not None else "")
            return
        keep = self.cmb_recipe.current()
        self.cmb_recipe["values"] = [
            "%s  -  %d of %d known" % (r["label"], r["known"], r["total"])
            for r in rows]
        self._recipe_lives = [r["life_id"] for r in rows]
        self.cmb_recipe.current(keep if 0 <= keep < len(rows) else 0)
        self.on_pick_recipe_life()

    def selected_recipe_life(self):
        i = self.cmb_recipe.current()
        if not self._recipe_lives or i < 0:
            raise RuntimeError("open a save with a recipe table first")
        return self._recipe_lives[i]

    def on_pick_recipe_life(self, _evt=None):
        """Refill the tick box from the save, and say what the bench will do."""
        if self.save is None or not self._recipe_lives:
            return
        life_id = self.selected_recipe_life()
        row = self._recipe_rows.get(life_id,
                                    {"known": 0, "total": 0, "label": life_id})
        self.var_recipe.set(row["known"] >= row["total"])
        # The rank is the other half of what a bench shows, and it is the half
        # the player can see going wrong: a Life at rank 0 has one short tab
        # whatever is ticked here.  It is read off the table above rather than
        # the save, which has just filled that table from it.
        rank = 0
        if self.tree_life.exists(life_id):
            rank = as_int(self.tree_life.item(life_id, "values")[0], 0)
        note = ("%d of %d %s recipes are known -- that is the list the crafting "
                "bench reads, not the scrolls in the bag."
                % (row["known"], row["total"], row["label"]))
        if rank < getattr(self, "_max_life_rank", 7):
            note += ("  A bench groups its list by Life rank and %s is rank %d, "
                     "so raise the rank above as well to see the whole catalogue."
                     % (row["label"], rank))
        self.lbl_recipe.configure(text=note)

    def on_apply_recipes(self, everyone):
        def go():
            sf = self.need()
            if sf.recipes is None:
                raise RuntimeError("this save has no recipe table")
            lives = None if everyone else [self.selected_recipe_life()]
            on = True if everyone else bool(self.var_recipe.get())
            got = sf.learn_recipes(lives, on=on,
                                   give_items=on and bool(
                                       self.var_recipe_items.get()))
            self.refresh_lives()
            note = "%d recipe(s) %s, %d of %d known" % (
                got["changed"], "learned" if on else "forgotten",
                got["known"], got["total"])
            if got["items"]:
                note += "  -  %d scroll(s) added" % got["items"]["added"]
            self.touch(note)
        self.guard(go)

    # ------------------------------------------------------ character edits
    def on_apply_character(self):
        def go():
            sf = self.need()
            ch = sf.character
            if ch is None:
                raise RuntimeError("this save has no character block")
            changed = []
            name = self.ent_name.get().strip()
            if name and name != ch.name:
                sf.set_name(name)
                changed.append("name")
            for field, entry in (("hp", self.ent_hp), ("hp_max", self.ent_hp_max),
                                 ("sp", self.ent_sp), ("sp_max", self.ent_sp_max)):
                value = as_int(entry.get(), getattr(ch, field))
                if value != getattr(ch, field):
                    sf.set_vital(field, value)
                    changed.append(field)
            if not changed:
                self.say("nothing to change")
                return
            self.refresh_character()
            self.touch("character: %s" % ", ".join(changed))
        self.guard(go)

    def on_apply_money(self):
        def go():
            sf = self.need()
            amount = as_int(self.ent_money.get())
            off = sf.set_money(amount)
            self.refresh_character()
            self.touch("Dosh = %d (at 0x%X)" % (amount, off))
        self.guard(go)

    def on_apply_currency(self, kind):
        def go():
            sf = self.need()
            amount = as_int(self.ent_currency[kind].get())
            off = sf.set_currency(kind, amount)
            self.refresh_character()
            self.touch("%s = %d (at 0x%X)" % (CURRENCIES[kind][1], amount, off))
        self.guard(go)

    # ---------------------------------------------------------- item edits
    def selected_record(self):
        arr = self.cur_array()
        sel = self.tree.selection()
        if not arr or not sel:
            raise RuntimeError("select a slot in the list first")
        return arr.records[int(sel[0])]

    def on_pick_slot(self, _evt=None):
        arr = self.cur_array()
        sel = self.tree.selection()
        if not arr or not sel:
            return
        r = arr.records[int(sel[0])]
        self.ent_id.delete(0, "end")
        self.ent_id.insert(0, "" if r.empty else r.item_id)
        self.spn_qty.delete(0, "end")
        self.spn_qty.insert(0, str(r.quantity))
        self.set_age(r.ripening_age if r.equipment else 0)
        self._last_id = r.item_id
        self.show_item(r.item_id, r.item_title, r)

    def on_id_typed(self):
        item_id = self.ent_id.get().strip()
        if item_id != getattr(self, "_last_id", None):
            # The vintage belongs to the piece, not to the box: a different id
            # starts from nothing rather than inheriting the last slot's years.
            self._last_id = item_id
            self.set_age(items.OP_RIPENING_AGE if self.var_op.get() else 0)
        self.show_item(item_id)

    def fill_titles(self, item_id, current=None):
        """Offer the grades this item has stats for, with what each one buys.

        A grade the item has no entry for reads as zero in game, which is what
        makes an otherwise valid piece of gear look broken, so the attack each
        one gives is spelled out rather than left to the item id.
        """
        choices = gear.title_choices(item_id) if item_id else []
        sentinel = gear.get().sentinel
        label = gear.stat_label(item_id) if item_id else "attack"
        rows = ["%d  %s" % (0, items.ITEM_TITLES[0])]
        self._titles = [0]
        for value, name, attack in choices:
            rows.append("%d  %-12s %s %s"
                        % (value, name, label,
                           "-" if attack <= sentinel else attack))
            self._titles.append(value)
        self.cmb_title["values"] = rows
        if not choices:
            # No stat list for this item (armour, tools): the grade is still
            # editable, it just cannot be annotated.
            self.cmb_title["values"] = [
                "%d  %s" % (i, n) for i, n in enumerate(items.ITEM_TITLES)]
            self._titles = list(range(len(items.ITEM_TITLES)))
        want = gear.best_title(item_id) if current is None else current
        self.cmb_title.current(self._titles.index(want) if want in self._titles else 0)

    def title_choice(self):
        i = self.cmb_title.current()
        titles = getattr(self, "_titles", [0])
        return titles[i] if 0 <= i < len(titles) else 0

    # ------------------------------------------------------ Super OP mode
    def set_age(self, years):
        self.spn_age.delete(0, "end")
        self.spn_age.insert(0, str(int(years)))

    def age_choice(self) -> int:
        return max(0, min(65535, as_int(self.spn_age.get())))

    def on_age_typed(self):
        self.describe_op(self.ent_id.get().strip())

    def on_toggle_op(self):
        """Fill the grade and the vintage in, so the tick box shows its work."""
        item_id = self.ent_id.get().strip()
        if self.var_op.get():
            best = gear.best_title(item_id)
            if best and best in getattr(self, "_titles", []):
                self.cmb_title.current(self._titles.index(best))
            self.set_age(items.OP_RIPENING_AGE)
        self.describe_op(item_id)

    def describe_op(self, item_id, rec=None):
        """Say what Super OP would write, or what the selected piece already has."""
        if not item_id:
            self.lbl_op.configure(text="")
            return
        skills = gear.op_skills(item_id)
        if self.var_op.get():
            best = gear.best_title(item_id)
            stat = gear.attack(item_id, best) if best else None
            bits = [items.ITEM_TITLES[best] if best else "grade as chosen"]
            if stat is not None:
                bits.append("%s %d" % (gear.stat_label(item_id), stat))
            bits.append("%d-year vintage" % self.age_choice())
            bits.append("%d skills" % len(skills) if skills
                        else "no skill roll for this kind")
            self.lbl_op.configure(text="will write: " + ", ".join(bits))
            return
        if rec is not None and rec.equipment and not rec.empty:
            have = [s for s in rec.grant_skills if s != items.NO_SKILL]
            self.lbl_op.configure(
                text="in this slot: %d-year vintage, quality %d, %s"
                     % (rec.ripening_age, rec.quality,
                        ", ".join(have) if have else "no skills"))
            return
        self.lbl_op.configure(
            text="" if not skills else "aging roll: " + ", ".join(skills))

    def show_item(self, item_id, title=None, rec=None):
        db = namedb.get()
        lang = self.lang()
        name = db.resolve(item_id, lang) if item_id else None
        desc = db.description(item_id, lang) if item_id else None
        self.lbl_item_icon.configure(
            image=self.icons.item(item_id, iconset.LARGE) or "")
        self.lbl_item_name.configure(text=name or (item_id or ""))
        self.lbl_desc.configure(
            text=(desc or "").replace("\r\n", " ").replace("\n", " "))
        self.fill_titles(item_id, title)
        self.describe_op(item_id, rec)

    def on_pick_item(self):
        def go():
            dlg = ItemPicker(self.master, self, self.ent_id.get().strip())
            self.master.wait_window(dlg)
            if dlg.choice:
                self.ent_id.delete(0, "end")
                self.ent_id.insert(0, dlg.choice)
                if not self.spn_qty.get().strip() or self.spn_qty.get() == "0":
                    self.spn_qty.delete(0, "end")
                    self.spn_qty.insert(0, "1")
                self.on_id_typed()
        self.guard(go)

    def on_apply_slot(self):
        def go():
            sf = self.need()
            r = self.selected_record()
            item_id = self.ent_id.get().strip()
            qty = as_int(self.spn_qty.get())
            if item_id and item_id != "None":
                r.place(item_id, qty, r.instance_id or sf.items.next_instance_id(),
                        self.title_choice())
                if r.equipment:
                    # The vintage is editable on its own, so it is written
                    # whether or not Super OP is on -- what the tick box adds is
                    # the skills and the quality.
                    if self.var_op.get():
                        r.make_super_op(age=self.age_choice(), keep_title=True)
                    else:
                        r.ripening_age = self.age_choice()
                self.warn_wrong_bag(r)
            else:
                r.clear()
            self.refresh_items()
            self.touch("slot %d = %s%s"
                       % (r.index, item_id or "empty", self.gear_note(r)))
        self.guard(go)

    def gear_note(self, rec) -> str:
        """The bit of a status line that only equipment has."""
        if not rec.equipment or rec.empty:
            return ""
        bits = [rec.title_name]
        if rec.ripening_age:
            bits.append("%d-year" % rec.ripening_age)
        have = [s for s in rec.grant_skills if s != items.NO_SKILL]
        if have:
            bits.append(", ".join(have))
        return "  (%s)" % "; ".join(bits)

    def on_clear_slot(self):
        def go():
            self.need()
            r = self.selected_record()
            r.clear()
            self.set_age(0)
            self.refresh_items()
            self.touch("cleared slot %d" % r.index)
        self.guard(go)

    def on_give(self):
        def go():
            sf = self.need()
            item_id = self.ent_id.get().strip()
            if not item_id:
                raise RuntimeError("type or pick an item id first")
            # "Give" files the item where the game would, which is not always
            # the container being looked at, so follow it there.
            rec = sf.give_item(item_id, max(1, as_int(self.spn_qty.get(), 1)),
                               None, self.title_choice(), self.var_op.get())
            if rec.equipment:
                rec.ripening_age = self.age_choice()
            if rec.array_index != (self.cur_array().index if self.cur_array() else -1):
                self.cmb_cont.current(rec.array_index)
            self.refresh_items()
            self.tree.selection_set(str(rec.index))
            self.tree.see(str(rec.index))
            self.touch("%s x%d into %s slot %d%s"
                       % (rec.item_id, rec.quantity,
                          sf.items.arrays[rec.array_index].label, rec.index,
                          self.gear_note(rec)))
        self.guard(go)

    def warn_wrong_bag(self, rec):
        """Say so when a slot now holds something this bag does not show."""
        want = items.category_for(rec.item_id)
        if want is not None and want != rec.array_index:
            here = self.save.items.arrays
            self.say("note: the game keeps %s in [%d] %s, not [%d] %s - it will "
                     "not appear in game from here"
                     % (rec.item_id, want, here[want].label,
                        rec.array_index, here[rec.array_index].label))

    def on_fix_gear(self):
        """Offer to repair gear that an older build of this editor spawned."""
        def go():
            sf = self.need()
            found = sf.repair_gear(apply=False)
            if not found:
                self.say("every piece of gear is in the right bag with a grade "
                         "the game has stats for - nothing to fix")
                return
            ok = messagebox.askokcancel(
                "Fix gear",
                "%d piece(s) of gear will not read properly in game:\n\n%s\n\n"
                "Repair them?" % (len(found), "\n".join(found[:14])
                                  + ("\n..." if len(found) > 14 else "")),
                parent=self.master)
            if not ok:
                return
            done = sf.repair_gear(apply=True)
            self.refresh_items()
            self.touch("repaired %d piece(s) of gear" % len(done))
        self.guard(go)

    def on_set_quantities(self):
        """Set the stack size of everything in the bag being looked at."""
        def go():
            sf = self.need()
            arr = self.cur_array()
            if arr is None:
                raise RuntimeError("pick a container first")
            amount = simpledialog.askinteger(
                "Set every quantity", "How many of each, in %s?" % arr.label,
                initialvalue=STACK_FULL, minvalue=0, maxvalue=65535,
                parent=self.master)
            if amount is None:
                return
            n = sf.set_every_quantity(arr.index, amount)
            self.refresh_items()
            self.touch("%d stack(s) in %s set to %d" % (n, arr.label, amount))
        self.guard(go)

    def on_give_every(self):
        """Fill the container on screen with every item the game keeps in it."""
        def go():
            sf = self.need()
            arr = self.cur_array()
            fill = BULK_FILLS.get(arr.index) if arr else None
            if fill is None:
                raise RuntimeError("this container has no bulk fill")
            kind = fill[0]
            equipment = self.bulk_equipment(arr)
            amount = max(1, as_int(self.spn_bulk_qty.get(), 1))
            title = self.bulk_title() if equipment else None
            super_op = equipment and bool(self.var_bulk_op.get())

            # Equipment does not stack, so asking for copies of each can want
            # more slots than the bag has -- and what does not fit is dropped in
            # id order, which would quietly leave out everything near the end.
            want = len(gear.every(kind)) * (amount if equipment else 1)
            room = arr.count - arr.used
            if want > room and not messagebox.askokcancel(
                    APP, "That asks for about %d slot(s) in %s, which has %d "
                         "free.\n\nFill it as far as it goes?"
                         % (want, arr.label, room)):
                return
            self.master.config(cursor="watch")
            self.master.update_idletasks()
            try:
                got = sf.give_every(kind, amount, title=title,
                                    super_op=super_op)
            finally:
                self.master.config(cursor="")
            self.cmb_cont.current(got["container"])
            self.refresh_items()
            done = ("regraded" if equipment and (title is not None or super_op)
                    else "topped up")
            note = "%d added, %d %s, of %d %s" % (
                got["added"], got["topped_up"], done, got["total"], kind)
            if got.get("learned"):
                # The scrolls are only half of a recipe; without the flag the
                # crafting benches list nothing new, however full the bag is.
                note += ("  -  %d marked known, so the crafting benches "
                         "list them" % got["learned"])
                self.refresh_recipes()
            if got["no_room"]:
                note += "  -  %d did not fit" % got["no_room"]
            self.touch(note)
        self.guard(go)

    # ---------------------------------------------------------- life edits
    def on_pick_life(self, _evt=None):
        sel = self.tree_life.selection()
        if not sel:
            return
        vals = self.tree_life.item(sel[0], "values")
        rank, _rank_name, points, level, exp, pa = vals
        for key, value in (("level", level), ("exp", exp), ("pa", pa),
                           ("rank_points", points)):
            self.life_entries[key].delete(0, "end")
            self.life_entries[key].insert(0, str(value))
        try:
            self.cmb_rank.current(int(rank))
        except (ValueError, tk.TclError):
            pass

    def on_apply_life(self, everyone):
        def go():
            sf = self.need()
            if everyone:
                targets = [e.life_id for e in sf.lives.arrays[0].entries]
            else:
                sel = self.tree_life.selection()
                if not sel:
                    raise RuntimeError("select a Life in the list first")
                targets = [sel[0]]
            fields = {}
            for key, entry in self.life_entries.items():
                text = entry.get().strip()
                if text:
                    fields[key] = as_int(text)
            if self.cmb_rank.current() >= 0:
                fields["rank"] = self.cmb_rank.current()
            if not fields:
                raise RuntimeError("nothing filled in to apply")
            for life_id in targets:
                for field, value in fields.items():
                    sf.set_life_field(life_id, field, value)
            self.refresh_lives()
            self.touch("%s on %d Life/Lives"
                       % (", ".join("%s=%d" % kv for kv in sorted(fields.items())),
                          len(targets)))
        self.guard(go)

    # --------------------------------------------------------------- tools
    def on_hunt(self, first):
        def go():
            sf = self.need()
            kind = self.cmb_htype.get()
            value = as_int(self.ent_hval.get())
            if first:
                self.hunt = Hunt(kind)
            left = self.hunt.step(bytes(sf.payload), value, kind)
            self.out("%s %s -> %d candidate(s)"
                     % ("scan" if first else "narrow", value, len(left)))
            for off in left[:40]:
                self.out("    0x%07X" % off)
            if len(left) > 40:
                self.out("    ... %d more" % (len(left) - 40))
            if len(left) == 1:
                self.ent_at.delete(0, "end")
                self.ent_at.insert(0, "0x%X" % left[0])
                self.cmb_ptype.set(kind)
                self.out("  -> offset dropped into the write box")
            self.say("%d candidate(s) left" % len(left))
        self.guard(go)

    def on_read(self):
        def go():
            sf = self.need()
            at, kind = as_int(self.ent_at.get()), self.cmb_ptype.get()
            self.out("0x%07X %s = %s" % (at, kind, sf.read_value(at, kind)))
        self.guard(go)

    def on_write(self):
        def go():
            sf = self.need()
            at, kind = as_int(self.ent_at.get()), self.cmb_ptype.get()
            before = sf.read_value(at, kind)
            sf.write_value(at, as_int(self.ent_pval.get()), kind)
            self.out("0x%07X %s: %s -> %s" % (at, kind, before,
                                              sf.read_value(at, kind)))
            self.refresh_all()
            self.touch("wrote 0x%07X" % at)
        self.guard(go)

    def on_dump(self):
        def go():
            sf = self.need()
            self.out(sf.hexdump(as_int(self.ent_at.get()), 256))
        self.guard(go)


def sharpen():
    """Ask Windows for real pixels; a stretched Tk window looks blurry."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    sharpen()
    root = tk.Tk()
    root.geometry("1180x800")
    app = App(root)
    if argv and os.path.exists(argv[0]):
        app.guard(app.load, argv[0])
    else:
        found = find_saves()
        if found:
            app.say("found your save at %s  -  press Open save... to load it"
                    % found[0])
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
