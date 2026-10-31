"""Turn exported model pieces into print-ready STL files in millimetres, at scale.

For every piece: union its solids into one body (fixes solids that only touch along
an edge), fill enclosed hidden voids, drop slivers, scale model units -> mm at 1:N,
put it on the bed (lowest point z = 0) and report size, volume and closed-ness.

The source model is never changed. Output STLs are already scaled: import them in
the slicer at 100 %.

usage:
  python prepare_parts.py PIECES.json --scale 96 --out print_v01
  python prepare_parts.py floor1.stl floor2.stl --units ft --scale 128 --out print_v01 --plate
  python prepare_parts.py PIECES.json --scale 96 --out v01 --merge          # everything as one body
  python prepare_parts.py PIECES.json --scale 96 --out v01 --upside-down    # slab on the bed, walls up

needs: numpy, trimesh, manifold3d, shapely
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
import trimesh

from printkit import (MM_PER_UNIT, drop_slivers, edge_report, fill_cavities, load_pieces, piece_to_manifold,
                      to_bed, to_trimesh, union)


def safe(name):
    return re.sub(r"[^\w.-]+", "_", name).strip("_") or "piece"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="pieces JSON from rhino_export_pieces.py, or mesh files (one piece each)")
    ap.add_argument("--units", choices=sorted(MM_PER_UNIT), help="model units (required for mesh files)")
    ap.add_argument("--scale", type=float, required=True, help="N in 1:N, e.g. 96 for 1/8\" = 1'-0\", 128 for 3/32\"")
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="", help="file name prefix, e.g. 'F1_white_' ")
    ap.add_argument("--merge", action="store_true", help="union all pieces into one body")
    ap.add_argument("--plate", action="store_true", help="also write all pieces side by side in one STL")
    ap.add_argument("--gap", type=float, default=8.0, help="mm between pieces on --plate (default 8)")
    ap.add_argument("--assembly", action="store_true", help="also write all pieces in model position (check only)")
    ap.add_argument("--upside-down", action="store_true", help="turn every piece over (e.g. floor plate slab-down)")
    ap.add_argument("--sliver", type=float, default=5.0, help="drop bodies under this many mm^3 (default 5)")
    ap.add_argument("--keep-cavities", action="store_true", help="do not fill enclosed inner voids")
    a = ap.parse_args()

    pieces, file_units = load_pieces(a.inputs)
    units = a.units or file_units
    if units is None:
        ap.error("mesh files carry no units: pass --units (ft, in, m, cm, mm)")
    k = MM_PER_UNIT[units] / a.scale                    # mm on the print per model unit
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    report = dict(scale="1:%g" % a.scale, model_units=units, mm_per_model_unit=round(k, 6),
                  note="STLs are in mm and already scaled; import at 100 %", pieces=[])
    built = []
    for pc in pieces:
        log = []
        m = piece_to_manifold(pc["solids"], log).scale([k, k, k])
        if m.is_empty():
            report["pieces"].append(dict(name=pc["name"], error="no closed solid", log=log))
            continue
        cav = 0
        if not a.keep_cavities:
            m, cav = fill_cavities(m)
        m, slivers = drop_slivers(m, a.sliver)
        built.append((pc, m, cav, slivers, log))

    if a.merge and built:
        m = union([b[1] for b in built])
        built = [(dict(name="merged", meta=dict(pieces=[b[0]["name"] for b in built])), m,
                  sum(b[2] for b in built), sum(b[3] for b in built), sum((b[4] for b in built), []))]

    placed_inplace, placed_plate, x = [], [], 0.0
    for pc, m, cav, slivers, log in built:
        tm = to_trimesh(m)
        placed_inplace.append(tm.copy())
        if a.upside_down:
            tm.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))
        tm = to_bed(tm)
        fn = "%s%s_1-%g_mm.stl" % (a.prefix, safe(pc["name"]), a.scale)
        tm.export(out / fn)
        row = dict(name=pc["name"], file=fn, size_mm=tm.extents.round(2).tolist(),
                   volume_cm3=round(tm.volume / 1000, 2), bodies=len(m.decompose()),
                   closed=bool(tm.is_watertight and tm.is_winding_consistent and tm.volume > 0),
                   cavities_filled=cav, slivers_dropped=slivers, source=pc.get("meta", {}))
        edges = edge_report(placed_inplace[-1], k)          # locations in model units
        if edges["open_edges"]:
            row["closed"] = False
        if edges["edge_contacts"]:
            row["edge_contacts"] = edges["edge_contacts"]
            row["edge_contact_at_model_units"] = edges["edge_contact_at"]
            log.append("%d edge(s) where solids touch only along a line: fine for Bambu Studio, rejected by strict "
                       "checkers, and a zero-width joint on the print - add a short tongue if it must hold"
                       % edges["edge_contacts"])
        if log:
            row["warnings"] = log
        report["pieces"].append(row)
        if a.plate:
            p = tm.copy()
            p.apply_translation([x, 0, 0])
            x += p.extents[0] + a.gap
            placed_plate.append(p)
        print("%-40s %s mm  %s cm3  bodies=%d  closed=%s%s" % (fn, row["size_mm"], row["volume_cm3"], row["bodies"],
                                                              row["closed"], "  edge contacts=%d" % edges["edge_contacts"]
                                                              if edges["edge_contacts"] else ""))
    if a.plate and placed_plate:
        plate = trimesh.util.concatenate(placed_plate)
        fn = "%splate_1-%g_mm.stl" % (a.prefix, a.scale)
        plate.export(out / fn)
        report["plate"] = dict(file=fn, size_mm=plate.extents.round(2).tolist())
        print("plate:", fn, report["plate"]["size_mm"])
    if a.assembly and placed_inplace:
        asm = trimesh.util.concatenate(placed_inplace)
        asm.apply_translation([0, 0, -asm.bounds[0][2]])
        fn = "%sassembly_check_1-%g_mm.stl" % (a.prefix, a.scale)
        asm.export(out / fn)
        report["assembly_check"] = dict(file=fn, size_mm=asm.extents.round(2).tolist(),
                                        note="pieces in model position; for checking, not a print plate")
    (out / ("%sreport.json" % a.prefix)).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
