#!/usr/bin/env python3
"""Command line front-end for the Fantasy Life i save editor.

    python fli.py info       <save>
    python fli.py items      <save> [--container N] [--all]
    python fli.py lives      <save>
    python fli.py boards     <save> [--complete base|kingdom|...|all] [-o out]
    python fli.py ginormosia <save> [--unlock] [--rank 7] [-o out]
    python fli.py ginormosia <save> --area 3 --rank 5 [--points N]
    python fli.py towers     <save> [--unlock] [--tower N] [--off]
    python fli.py money      <save> [--set 99999] [--gift N] [--cashnuts N] [-o out]
    python fli.py set-life   <save> [--life life0001|all] --level 99 --exp 0 [-o out]
    python fli.py recipes    <save> [--learn all|blacksmith|10 ...] [--forget] [-o out]
    python fli.py basecamp   <save> [--kind furniture|buildings|terrain|roads|...]
    python fli.py basecamp   <save> --export island.flicamp [--note "my island"]
    python fli.py basecamp   <save> --import island.flicamp [--scope all|terrain|objects]
    python fli.py give       <save> --id ics01000780 --qty 99 [-o out]
    python fli.py give       <save> --id iwp02000220 [--title 5]
    python fli.py give       <save> --id ilt01000120 --super-op
    python fli.py set-slot   <save> --slot 0:12 --id iwp01000010 --qty 1 [-o out]
    python fli.py give-all   <save> --what materials|recipes|crafts [--qty N]
    python fli.py give-all   <save> --what weapons|tools|shields|armour
                             [--qty copies] [--title 5] [--super-op]
    python fli.py set-qty    <save> --container 7 --qty 999
    python fli.py fix-gear   <save> [--dry-run]
    python fli.py clear-slot <save> --slot 0:12 [-o out]
    python fli.py find       <save> --value 12345 [--type u32]
    python fli.py hunt       <save> --value 12345 [--state hunt.json] [--reset]
    python fli.py scan       <save> --value 12345
    python fli.py poke       <save> --at 0xF8019 --type u32 --value 9999999 [-o out]
    python fli.py dump       <save> --at 0xF8000 [--len 256]
    python fli.py decode     <save> <payload.gvas>
    python fli.py encode     <payload.gvas> <save.bin>
    python fli.py diff       <save-a> <save-b>
    python fli.py ids        <save>
    python fli.py search     "potion" [--lang it]
"""
from __future__ import annotations

import argparse
import sys

from flisave.codec import SaveContainer, decode_file
from flisave.hunt import Hunt, scan_all_types
from flisave.basecamp import SCOPES
from flisave.save import SaveFile, CURRENCIES
from flisave.world import BOARDS, BOARD_BY_KEY, MAX_RANK, TOWER_COUNT
from flisave import gear, items, names as namedb, recipes as reciped

TYPES = ["u8", "i8", "u16", "i16", "u32", "i32", "u64", "i64", "f32", "f64"]


def _num(text: str):
    t = text.strip()
    if t.lower().startswith("0x"):
        return int(t, 16)
    if "." in t or "e" in t.lower():
        return float(t)
    return int(t)


def _slot(text: str):
    a, _, b = text.partition(":")
    return int(a), int(b)


def _save_out(sf: SaveFile, args) -> None:
    out = getattr(args, "out", None) or sf.path
    path = sf.write(out, backup=not args.no_backup)
    print("written: %s" % path)


# --------------------------------------------------------------------- verbs
def cmd_info(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    print(sf.info())


def cmd_items(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    sec = sf.items
    if sec is None:
        sys.exit("item section unavailable: %s" % sf.items_error)
    print("%-5s %-6s %-20s %5s  %-34s %-12s %s"
          % ("cont", "slot", "item id", "qty", "name", "title", "attack"))
    shown = 0
    for arr in sec.arrays:
        if args.container is not None and arr.index != args.container:
            continue
        for r in arr.records:
            if r.empty and not args.all:
                continue
            atk = gear.attack(r.item_id, r.item_title) if r.equipment else None
            print("%-5d %-6d %-20s %5d  %-34s %-12s %s"
                  % (arr.index, r.index, r.item_id, r.quantity,
                     sf.item_name(r.item_id, args.lang) or "-",
                     r.title_name or r.category, "-" if atk is None else atk))
            shown += 1
    print("\n%d slot(s) listed" % shown)


def cmd_ids(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    sec = sf.items
    seen = {}
    for r in sec.records:
        if not r.empty:
            seen.setdefault(r.item_id, 0)
            seen[r.item_id] += r.quantity
    for k in sorted(seen):
        print("%-22s x%-6d %s" % (k, seen[k], sf.item_name(k, args.lang) or "-"))
    print("\n%d distinct item id(s) present in this save" % len(seen))


def cmd_lives(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    rows = sf.life_rows(args.lang)
    head = "%-10s %-14s %5s %-12s %7s %7s %9s %8s"
    print(head % ("id", "life", "rank", "rank name", "points", "level", "exp", "PA"))
    for r in rows:
        print(head
              % (r["life_id"], r.get("name", "?"), r.get("rank", "-"),
                 r.get("rank_name", ""), r.get("rank_points", "-"),
                 r.get("level", "-"), r.get("exp", "-"), r.get("pa", "-")))
    print()
    print(sf.lives.summary(bytes(sf.payload)).split("\n\n")[0])


def cmd_recipes(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    if sf.recipes is None:
        sys.exit("this save has no recipe table")
    if args.learn or args.forget:
        which = args.learn or args.forget
        lives = None if "all" in [w.lower() for w in which] \
            else reciped.resolve_lives(which)
        got = sf.learn_recipes(lives, on=not args.forget,
                               mark_new=args.mark_new,
                               give_items=args.items and not args.forget)
        print("%s: %d recipe(s) changed, %d of %d now known"
              % ("forgot" if args.forget else "learned",
                 got["changed"], got["known"], got["total"]))
        if got["items"]:
            print("  scrolls: %d added, %d topped up, of %d"
                  % (got["items"]["added"], got["items"]["topped_up"],
                     got["items"]["total"]))
        _save_out(sf, args)
        return
    print("%-10s %-14s %8s %8s" % ("id", "life", "known", "total"))
    for r in sf.recipe_rows(args.lang):
        print("%-10s %-14s %8d %8d"
              % (r["life_id"], r["label"][:14], r["known"], r["total"]))
    print()
    print(sf.recipes.summary())
    print()
    print("This is the list a crafting bench reads.  The irp scrolls in bag 8")
    print("are the other half of a recipe -- the phone's list shows those, so a")
    print("bag filled on its own leaves the bench with nothing new in it.")
    print("A bench still groups its list by Life rank, so a Life left at rank 0")
    print("shows a short list however many recipes are known.")


def cmd_basecamp(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    camp = sf.base_camp
    if camp is None:
        sys.exit("this save has no Base Camp block (%s)" % sf.base_camp_error)
    if args.export:
        got = sf.export_base_camp(args.export, note=args.note or "")
        print("written: %s (%.1f KB)" % (got["path"], got["bytes"] / 1024.0))
        print("  %d objects, %d houses, %d bytes of room interiors"
              % (got["used"], got["houses"], got["areas"]))
        return
    if getattr(args, "import_"):
        got = sf.import_base_camp(args.import_, args.scope)
        print("imported (%s): %d object(s) now on the island, %d house(s)"
              % (got["scope"], got["used"], got["houses"]))
        for note in got["kept_levels"]:
            print("  %s" % note)
        if got["houses_listed"]:
            print("  %d villager house(s) ready to move into"
                  % got["houses_listed"])
        if got["houses_unlisted"]:
            print("  %d more than this build can list -- they stand, but "
                  "nobody can move in" % got["houses_unlisted"])
        _save_out(sf, args)
        return

    c = camp.counts()
    print("Base Camp -- %d of %d object slots in use" % (c["used"], c["slots"]))
    print("  ground %d, water %d, cliff faces %d, %d height level(s), roads %d"
          % (c["ground"], c["water"], c["cliffs"], c["levels"], c["roads"]))
    print("  buildings %d, furniture %d, obstacles %d, houses %d"
          % (c["buildings"], c["furniture"], c["obstacles"], c["houses"]))
    print()
    print("%-11s %-30s %-22s %s"
          % ("whose", "house", "door leads to", "standing at"))
    for h in sf.house_rows(args.lang):
        pos = ("%.0f, %.0f, %.0f" % h["position"]) if h["position"] else "-"
        print("%-11s %-30s %-22s %s"
              % (h["kind"], h["name"][:30], h["entrance"], pos))
    print()
    print("%-22s %6s  %s" % (args.kind, "count", "name"))
    for r in sf.base_camp_rows(args.kind, args.lang):
        print("%-22s %6d  %s" % (r["id"], r["count"], r["name"]))


def cmd_boards(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    if args.complete:
        keys = [b.key for b in BOARDS] if args.complete == "all" else [args.complete]
        for key in keys:
            n = sf.complete_board(key)
            print("%-9s %-22s %d job(s) completed"
                  % (key, sf.place_name(BOARD_BY_KEY[key].map_id, args.lang), n))
        _save_out(sf, args)
        return
    print("%-9s %-26s %6s %9s %9s %8s"
          % ("zone", "place", "jobs", "complete", "on board", "hidden"))
    for r in sf.board_rows(args.lang):
        print("%-9s %-26s %6d %9d %9d %8d"
              % (r["key"], r["name"][:26], r["total"], r["complete"],
                 r["open"], r["hidden"]))
    print()
    print("The board level is not stored in the save -- the game works it out")
    print("from these job states -- so completing the jobs is what raises it.")


def cmd_ginormosia(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    hm = sf.ginormosia
    if hm is None:
        sys.exit("this save has no Ginormosia block")
    if args.area is not None:
        if args.rank is None and args.points is None:
            sys.exit("--area needs --rank and/or --points")
        if (args.rank is not None and args.rank > MAX_RANK and not args.over_max):
            sys.exit("rank %d is above the game's maximum of %d -- GDSAreaRankLevel "
                     "stops at %d, so a higher one sends the game's own lookup "
                     "past the end of its table. Pass --over-max if you want it "
                     "anyway." % (args.rank, MAX_RANK, MAX_RANK))
        targets = (hm.areas if args.area == "all"
                   else [hm.area(args.area)])
        for a in list(targets):
            rank = a.rank if args.rank is None else args.rank
            hm.set_area_rank(a.area_id, rank, args.points,
                             allow_over_max=args.over_max)
            print("%-20s %-28s rank %d, %d points"
                  % (a.area_id, sf.place_name(a.text_key, args.lang)[:28],
                     a.rank, a.points))
        _save_out(sf, args)
        return
    if args.unlock or args.rank is not None:
        r = sf.unlock_ginormosia(open_zones=False,
                                 camps=args.unlock and not args.no_camps,
                                 reveal=args.unlock and not args.no_shrines,
                                 clear=args.unlock and not args.no_shrines,
                                 ranks=args.unlock and not args.no_ranks
                                       and args.rank is not None,
                                 rank=args.rank)
        print("camps unlocked  : %d  %s" % (len(r["camps"]), ", ".join(r["camps"])))
        print("areas re-ranked : %d%s"
              % (r["ranks"], "" if r["ranks"] else "  (ranks are left alone "
                                                  "unless --rank says otherwise)"))
        print("shrines revealed: %d" % len(r["revealed"]))
        print("shrines cleared : %d" % r["cleared"])
        _save_out(sf, args)
        return
    print(hm.summary())
    print()
    print("%-20s %-28s %6s %10s" % ("area", "name", "rank", "points"))
    for r in sf.ginormosia_rows(args.lang):
        print("%-20s %-28s %6d %10d"
              % (r["area_id"], r["name"][:28], r["rank"], r["points"]))
    print()
    print("%-12s %-28s %7s %8s" % ("shrine", "name", "found", "cleared"))
    for r in sf.shrine_rows(args.lang):
        print("%-12s %-28s %7s %8s"
              % (r["shrine_id"], r["name"][:28],
                 "yes" if r["found"] else "-", "yes" if r["cleared"] else "-"))


def cmd_towers(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    if sf.sync_flags is None:
        sys.exit("this save has no sync-flag table")
    if args.unlock or args.tower:
        if args.unlock:
            r = sf.unlock_towers()
            print("towers lit      : %d  %s"
                  % (len(r["towers"]), ", ".join(map(str, r["towers"]))))
            print("travel points   : %d opened" % len(r["travel_points"]))
        else:
            for n in args.tower:
                changed = sf.set_tower(n, not args.off)
                print("tower %-3d %-18s %s" % (
                    n, sf.place_name("tower_%03d" % n, args.lang),
                    ("lit" if not args.off else "unlit") if changed
                    else "already that way"))
        _save_out(sf, args)
        return
    print("%-4s %-24s %s" % ("#", "name", "lit"))
    for r in sf.tower_rows(args.lang):
        print("%-4d %-24s %s" % (r["number"], r["name"],
                                 "yes" if r["lit"] else "-"))
    print()
    print(sf.sync_flags.summary())
    print(sf.travel_points.summary())
    print()
    print("Lighting a tower is what clears that zone's clouds off the map.")


def cmd_money(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    off = sf.money_offset()
    if off is None:
        sys.exit("could not find the Dosh field in this save")

    wanted = [("dosh", args.set)]
    wanted += [(k, getattr(args, k)) for k in CURRENCIES]
    if all(v is None for _k, v in wanted):
        print("dosh            : %12d  (at 0x%07X)" % (sf.money, off))
        for kind, (_slot, label) in CURRENCIES.items():
            where = sf.currency_offset(kind)
            print("%-16s: %12s  %s"
                  % (label, sf.currency(kind) if where else "not found",
                     "(at 0x%07X)" % where if where else ""))
        return

    for kind, value in wanted:
        if value is None:
            continue
        if kind == "dosh":
            before, at = sf.money, sf.set_money(value)
            print("dosh: %d -> %d  (at 0x%07X)" % (before, sf.money, at))
        else:
            before = sf.currency(kind)
            at = sf.set_currency(kind, value)
            print("%s: %s -> %d  (at 0x%07X)"
                  % (CURRENCIES[kind][1], before, sf.currency(kind), at))
    _save_out(sf, args)


def cmd_set_life(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    if args.life == "all":
        targets = [e.life_id for e in sf.lives.arrays[0].entries]
    else:
        targets = [args.life]
    for life in targets:
        for field, value in (("level", args.level), ("exp", args.exp),
                             ("rank", args.rank), ("pa", args.pa),
                             ("rank_points", args.rank_points)):
            if value is not None:
                sf.set_life_field(life, field, value)
                print("%s.%s = %d" % (life, field, value))
    _save_out(sf, args)


def cmd_search(args):
    db = namedb.get()
    if not db.loaded:
        sys.exit(db.error)
    hits = db.search(args.text, args.lang, limit=args.limit)
    for key, name in hits:
        print("%-22s %s" % (key, name))
    print("\n%d match(es) for %r in %s" % (len(hits), args.text, args.lang))


def _placed(sf, rec):
    """Describe a slot the way the player will see it in game."""
    lines = ["container %d (%s) slot %d -> %s x%d  %s"
             % (rec.array_index, sf.items.arrays[rec.array_index].label,
                rec.index, rec.item_id, rec.quantity,
                sf.item_name(rec.item_id, "en") or "")]
    if rec.equipment:
        atk = gear.attack(rec.item_id, rec.item_title)
        note = ("" if atk is None else "  ->  %s %d"
                % (gear.stat_label(rec.item_id), atk))
        if atk is not None and atk <= gear.get().sentinel:
            note += "   (this grade has no stats for this item)"
        lines.append("  title %s%s" % (rec.title_name, note))
        if rec.ripening_age:
            lines.append("  aged  %d-year vintage, quality %d"
                         % (rec.ripening_age, rec.quality))
        rolled = [k for k in rec.grant_skills if k != items.NO_SKILL]
        if rolled:
            lines.append("  skills %s" % ", ".join(rolled))
    return "\n".join(lines)


def cmd_give(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    rec = sf.give_item(args.id, args.qty, args.container, args.title,
                       args.super_op)
    if rec.equipment and args.age is not None:
        rec.ripening_age = args.age
    print(_placed(sf, rec))
    _save_out(sf, args)


def cmd_set_slot(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    cont, slot = _slot(args.slot)
    rec = sf.items.arrays[cont].records[slot]
    if args.id and args.id != "None":
        rec.place(args.id,
                  args.qty if args.qty is not None else max(1, rec.quantity),
                  rec.instance_id or sf.items.next_instance_id(),
                  args.title, args.super_op)
    elif args.qty is not None:
        rec.quantity = args.qty
    if rec.equipment and args.age is not None:
        rec.ripening_age = args.age
    print(_placed(sf, rec))
    _save_out(sf, args)


def cmd_give_all(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    got = sf.give_every(args.what, args.qty, title=args.title,
                        super_op=args.super_op)
    bag = sf.items.arrays[got["container"]]
    print("%s -> [%d] %s: %d added, %d topped up, of %d"
          % (args.what, got["container"], bag.label,
             got["added"], got["topped_up"], got["total"]))
    if bag.records and bag.records[0].equipment:
        # Equipment has no stack, so the quantity was copies of each piece and
        # the grade is what decides whether any of them read as more than zero.
        print("  %d piece(s) of each, at %s%s"
              % (max(1, args.qty),
                 items.ITEM_TITLES[args.title] if args.title is not None
                 else "the best grade each item has stats for",
                 ", aged %d years" % items.OP_RIPENING_AGE if args.super_op else ""))
    if "learned" in got:
        # The scrolls are only half of a recipe; without this the bench list
        # does not move, however full the bag is.
        print("  %d recipe(s) marked known, so the crafting benches list them"
              % got["learned"])
    if got["no_room"]:
        print("  %d did not fit -- the bag holds %d" % (got["no_room"], bag.count))
    print("  bag now %d/%d used" % (bag.used, bag.count))
    _save_out(sf, args)


def cmd_set_qty(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    bag = sf.items.arrays[args.container]
    n = sf.set_every_quantity(args.container, args.qty)
    print("[%d] %s: %d stack(s) set to %d"
          % (args.container, bag.label, n, args.qty))
    _save_out(sf, args)


def cmd_fix_gear(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    # Overwritten records come first: until their lengths add up again nothing
    # downstream of the damage can be parsed at all.
    healed = sf.repair_records(apply=not args.dry_run)
    if healed:
        print("healed %d overwritten record(s):" % len(healed))
        for n in healed:
            print("  " + n)
    if healed and args.dry_run:
        print("\n%d change(s) (dry run)" % len(healed))
        return
    notes = sf.repair_gear(apply=not args.dry_run)
    for n in notes:
        print("  " + n)
    notes = healed + notes
    if not notes:
        print("nothing to fix: every piece of gear is in the right bag with a "
              "grade the game has stats for")
        return
    print("\n%d change(s)%s" % (len(notes), " (dry run)" if args.dry_run else ""))
    if not args.dry_run:
        _save_out(sf, args)


def cmd_clear_slot(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    cont, slot = _slot(args.slot)
    sf.items.arrays[cont].records[slot].clear()
    print("container %d slot %d cleared" % (cont, slot))
    _save_out(sf, args)


def cmd_find(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    val = _num(args.value)
    hits = sf.find_value(val, args.type)
    for h in hits[: args.limit]:
        print("0x%07X" % h)
    print("\n%d hit(s) for %s = %s%s"
          % (len(hits), args.type, args.value,
             "" if len(hits) <= args.limit else " (truncated)"))


def cmd_hunt(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    h = Hunt.load(args.state)
    if args.reset:
        h = Hunt()
    cands = h.step(bytes(sf.payload), _num(args.value), args.type)
    h.save(args.state)
    for off in cands[: args.limit]:
        print("0x%07X  = %s" % (off, sf.read_value(off, h.kind)))
    last = h.history[-1]
    print("\npass %d: %d raw hit(s), %d candidate(s) remain%s"
          % (len(h.history), last["hits"], len(cands),
             "" if len(cands) <= args.limit else " (list truncated)"))
    if len(cands) > 1:
        print("change the value in game, save again, then re-run hunt with the "
              "new number and the same --state file")


def cmd_scan(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    res = scan_all_types(bytes(sf.payload), _num(args.value))
    for kind, hits in res.items():
        print("%-4s %6d hit(s)  %s" % (kind, len(hits),
              " ".join("0x%X" % h for h in hits[:12])))


def cmd_poke(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    at = _num(args.at)
    before = sf.read_value(at, args.type)
    sf.write_value(at, _num(args.value), args.type)
    print("0x%07X %s: %s -> %s" % (at, args.type, before, sf.read_value(at, args.type)))
    _save_out(sf, args)


def cmd_dump(args):
    sf = SaveFile.load(args.save, verify=not args.no_verify)
    print(sf.hexdump(_num(args.at), args.len))


def cmd_decode(args):
    c = decode_file(args.save)
    with open(args.out, "wb") as fh:
        fh.write(c.payload)
    print("payload: %d bytes -> %s" % (len(c.payload), args.out))


def cmd_encode(args):
    with open(args.payload, "rb") as fh:
        data = fh.read()
    n = len(SaveContainer(payload=data).encode())
    with open(args.out, "wb") as fh:
        fh.write(SaveContainer(payload=data).encode())
    print("save: %d bytes -> %s" % (n, args.out))


def cmd_diff(args):
    a = SaveFile.load(args.a, verify=not args.no_verify)
    b = SaveFile.load(args.b, verify=not args.no_verify)
    runs = SaveFile.diff(a, b, context=args.context)
    for off, x, y in runs[: args.limit]:
        print("0x%07X  %s\n            %s" % (off, x.hex(" "), y.hex(" ")))
    print("\n%d differing run(s)" % len(runs))


# --------------------------------------------------------------------- setup
def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--no-verify", action="store_true",
                        help="load even if the MD5 check fails")
    common.add_argument("--no-backup", action="store_true",
                        help="do not keep a timestamped .bak of the original")
    common.add_argument("--lang", default="en",
                        help="language for item/Life names "
                             "(ja en fr it de es zh-Hans zh-Hant ko)")

    p = argparse.ArgumentParser(
        prog="fli", parents=[common],
        description="Fantasy Life i: The Girl Who Steals Time save editor")
    sub = p.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda name, **kw: _add(name, parents=[common], **kw)

    s = sub.add_parser("info"); s.add_argument("save"); s.set_defaults(f=cmd_info)

    s = sub.add_parser("items")
    s.add_argument("save")
    s.add_argument("--container", type=int)
    s.add_argument("--all", action="store_true", help="include empty slots")
    s.set_defaults(f=cmd_items)

    s = sub.add_parser("ids"); s.add_argument("save"); s.set_defaults(f=cmd_ids)

    s = sub.add_parser("lives"); s.add_argument("save"); s.set_defaults(f=cmd_lives)

    s = sub.add_parser("recipes", help="which recipes the player knows -- the "
                                       "list a crafting bench reads, which is "
                                       "not the same thing as the scrolls in "
                                       "the bag")
    s.add_argument("save")
    s.add_argument("--learn", action="append", metavar="LIFE",
                   help="mark every recipe of this crafting Life known: all, a "
                        "name (blacksmith), a number (10) or an id (life0010); "
                        "repeatable")
    s.add_argument("--forget", action="append", metavar="LIFE",
                   help="the other way round, same values")
    s.add_argument("--items", action="store_true",
                   help="put the matching irp scrolls in the bag as well, "
                        "which is the pair the game itself writes")
    s.add_argument("--mark-new", action="store_true",
                   help='flag them "NEW!" the way a freshly learned one is')
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_recipes)

    s = sub.add_parser("basecamp", help="the Base Camp island: what is built on "
                                        "it, and export or import a whole "
                                        "layout to share it")
    s.add_argument("save")
    s.add_argument("--kind", default="furniture",
                   choices=["furniture", "buildings", "obstacles", "markers",
                            "terrain", "roads"],
                   help="which family of objects to list (default: furniture)")
    s.add_argument("--export", metavar="FILE",
                   help="write the island out as a shareable layout file; a "
                        ".json name stays readable, anything else is gzipped")
    s.add_argument("--import", dest="import_", metavar="FILE",
                   help="read a layout file into this save, replacing what is "
                        "there")
    s.add_argument("--scope", default="all", choices=list(SCOPES),
                   help="how much of the layout to bring across: all of it, "
                        "just the terrain (ground, water, cliffs, roads) or "
                        "just the objects standing on it")
    s.add_argument("--note", help="a line of your own to store in the export")
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_basecamp)

    s = sub.add_parser("boards", help="bulletin boards: show them, or finish "
                                      "every job on one so its level maxes out")
    s.add_argument("save")
    s.add_argument("--complete", metavar="ZONE",
                   choices=[b.key for b in BOARDS] + ["all"],
                   help="finish every job on this board (%s or all)"
                        % ", ".join(b.key for b in BOARDS))
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_boards)

    s = sub.add_parser("towers", help="the eye towers, which are what clear "
                                      "the open-world map")
    s.add_argument("save")
    s.add_argument("--unlock", action="store_true",
                   help="light every tower and open its travel point")
    s.add_argument("--tower", type=int, action="append", metavar="N",
                   help="one tower, 1-%d; repeatable" % TOWER_COUNT)
    s.add_argument("--off", action="store_true", help="unlight instead")
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_towers)

    s = sub.add_parser("ginormosia", help="Ginormosia: camps, area ranks and "
                                          "shrines")
    s.add_argument("save")
    s.add_argument("--unlock", action="store_true",
                   help="unlock every camp, reveal and clear every shrine "
                        "(ranks are left alone; the map's clouds are not "
                        "something this can reach)")
    s.add_argument("--rank", type=int, metavar="N",
                   help="rank to store (1-%d); every area, or just --area"
                        % MAX_RANK)
    s.add_argument("--area", metavar="WHICH",
                   help="one open-world area: its number 1-15, its id, or all")
    s.add_argument("--points", type=int,
                   help="points to store with the rank (default: what the "
                        "rank itself needs)")
    s.add_argument("--over-max", action="store_true",
                   help="allow a rank above %d, which the game's own table "
                        "does not define" % MAX_RANK)
    s.add_argument("--no-camps", action="store_true")
    s.add_argument("--no-ranks", action="store_true")
    s.add_argument("--no-shrines", action="store_true")
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_ginormosia)

    s = sub.add_parser("money", help="show or set Dosh and the other currencies")
    s.add_argument("save")
    s.add_argument("--set", type=int, help="new Dosh amount")
    for _kind, (_slot, _label) in CURRENCIES.items():
        s.add_argument("--%s" % _kind, type=int, help="new %s amount" % _label)
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_money)

    s = sub.add_parser("set-life")
    s.add_argument("save")
    s.add_argument("--life", default="all",
                   help="life0001 .. life0014, or 'all' (default)")
    s.add_argument("--level", type=int)
    s.add_argument("--exp", type=int)
    s.add_argument("--rank", type=int)
    s.add_argument("--rank-points", type=int,
                   help="progress towards the next rank, which is what the "
                        "Life master's quests award")
    s.add_argument("--pa", type=int, help="ability points for the Life")
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_set_life)

    s = sub.add_parser("search")
    s.add_argument("text", help="part of an item name, e.g. \"potion\"")
    s.add_argument("--limit", type=int, default=40)
    s.set_defaults(f=cmd_search)

    s = sub.add_parser("give")
    _OP_HELP = ("finish a piece of equipment the way the Aging Altar does: the "
                "grade its stats live at, a %d-year vintage, top quality and "
                "the three equipment skills the game rolls for that kind of "
                "gear" % items.OP_RIPENING_AGE)
    _AGE_HELP = "vintage in years on its own, 0-65535 (Aging Altar's ripeningAge)"
    _TITLE_HELP = ("equipment grade 0-5 (None/Rag/Normal/Masterpiece/Supreme/"
                   "Legend); it picks which entry of the item's stat list the "
                   "game reads, and defaults to the best one the item has")
    s.add_argument("save")
    s.add_argument("--id", required=True)
    s.add_argument("--qty", type=int, default=1)
    s.add_argument("--container", type=int)
    s.add_argument("--title", type=int, choices=range(6), help=_TITLE_HELP)
    s.add_argument("--super-op", action="store_true", help=_OP_HELP)
    s.add_argument("--age", type=int, help=_AGE_HELP)
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_give)

    s = sub.add_parser("set-slot")
    s.add_argument("save")
    s.add_argument("--slot", required=True, help="container:slot, e.g. 0:12")
    s.add_argument("--id")
    s.add_argument("--qty", type=int)
    s.add_argument("--title", type=int, choices=range(6), help=_TITLE_HELP)
    s.add_argument("--super-op", action="store_true", help=_OP_HELP)
    s.add_argument("--age", type=int, help=_AGE_HELP)
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_set_slot)

    s = sub.add_parser("give-all", help="give every item of one kind the game "
                       "defines: a whole bag at once")
    s.add_argument("save")
    s.add_argument("--what", choices=gear.EVERY_KINDS, required=True)
    s.add_argument("--qty", type=int, default=1,
                   help="how many of each -- the stack size in a bag that "
                        "stacks (recipes are always 1 in game), and how many "
                        "separate pieces in an equipment bag, which has no "
                        "stack at all")
    s.add_argument("--title", type=int, choices=range(6), help=_TITLE_HELP)
    s.add_argument("--super-op", action="store_true", help=_OP_HELP)
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_give_all)

    s = sub.add_parser("set-qty", help="set the stack size of everything in "
                       "one container")
    s.add_argument("save")
    s.add_argument("--container", type=int, required=True)
    s.add_argument("--qty", type=int, required=True)
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_set_qty)

    s = sub.add_parser("fix-gear", help="repair gear an older build of this "
                       "editor spawned: wrong bag, or a grade with no stats")
    s.add_argument("save")
    s.add_argument("--dry-run", action="store_true",
                   help="say what would change without touching the file")
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_fix_gear)

    s = sub.add_parser("clear-slot")
    s.add_argument("save")
    s.add_argument("--slot", required=True)
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_clear_slot)

    s = sub.add_parser("find")
    s.add_argument("save")
    s.add_argument("--value", required=True)
    s.add_argument("--type", choices=TYPES, default="u32")
    s.add_argument("--limit", type=int, default=60)
    s.set_defaults(f=cmd_find)

    s = sub.add_parser("hunt")
    s.add_argument("save")
    s.add_argument("--value", required=True)
    s.add_argument("--type", choices=TYPES, default="u32")
    s.add_argument("--state", default="hunt.json")
    s.add_argument("--reset", action="store_true")
    s.add_argument("--limit", type=int, default=40)
    s.set_defaults(f=cmd_hunt)

    s = sub.add_parser("scan")
    s.add_argument("save")
    s.add_argument("--value", required=True)
    s.set_defaults(f=cmd_scan)

    s = sub.add_parser("poke")
    s.add_argument("save")
    s.add_argument("--at", required=True)
    s.add_argument("--type", choices=TYPES, default="u32")
    s.add_argument("--value", required=True)
    s.add_argument("-o", "--out")
    s.set_defaults(f=cmd_poke)

    s = sub.add_parser("dump")
    s.add_argument("save")
    s.add_argument("--at", required=True)
    s.add_argument("--len", type=int, default=256)
    s.set_defaults(f=cmd_dump)

    s = sub.add_parser("decode")
    s.add_argument("save"); s.add_argument("out"); s.set_defaults(f=cmd_decode)

    s = sub.add_parser("encode")
    s.add_argument("payload"); s.add_argument("out"); s.set_defaults(f=cmd_encode)

    s = sub.add_parser("diff")
    s.add_argument("a"); s.add_argument("b")
    s.add_argument("--context", type=int, default=4)
    s.add_argument("--limit", type=int, default=80)
    s.set_defaults(f=cmd_diff)

    args = p.parse_args(argv)
    args.f(args)


if __name__ == "__main__":
    main()
