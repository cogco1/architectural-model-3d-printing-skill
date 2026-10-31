"""Make a base (plinth) for a printed model: a rectangle around the building, with rounded or
chamfered corners, solid or hollow with ribs, whole or split in two with locating pins.

Defaults are the ones that worked for a 1/8" (1:96) section model base, 210 x 214 x 12.7 mm:
2 mm skin, 1.2 mm ribs every 25 mm both ways, open bottom - prints without support and
uses about 30 % of the solid volume. Split halves get two diamond pins (3 mm across,
3 mm long) and matching holes with 0.2 mm clearance per side; a diamond needs no support.

All sizes in mm on the print. Work out model distances first: mm = feet * 304.8 / N.
At 1:96 one foot is 3.175 mm, at 1:128 it is 2.381 mm.

usage:
  # building footprint + 4 ft margin at 1:96, 1 ft thick, 4 ft corner radius, hollow, in two halves
  python make_base.py --footprint building.stl --offset 12.7 --height 12.7 --corner-radius 12.7 \
      --hollow --split --out base_v01
  # plain 1 ft slab with 1 ft chamfered corners at 1:96
  python make_base.py --size 180 200 --height 3.175 --chamfer 3.175 --out base_v01

needs: numpy, trimesh, manifold3d, shapely
"""
import argparse
import json
from pathlib import Path

import manifold3d as md
import numpy as np
import shapely.geometry
import trimesh

from printkit import to_bed, to_trimesh, union


def outline(w, d, radius, chamfer):
    r = shapely.geometry.box(0, 0, w, d)
    if radius:
        r = r.buffer(-radius, join_style=2).buffer(radius, quad_segs=24)
    elif chamfer:
        # 45 deg corner cut with legs of `chamfer`
        c = chamfer
        r = shapely.geometry.Polygon([(c, 0), (w - c, 0), (w, c), (w, d - c), (w - c, d), (c, d), (0, d - c), (0, c)])
    return r


def prism(poly, z0, z1):
    rings = [np.asarray(poly.exterior.coords)[:-1]] + [np.asarray(i.coords)[:-1] for i in poly.interiors]
    return md.CrossSection(rings, md.FillRule.EvenOdd).extrude(z1 - z0).translate([0, 0, z0])


def diamond(cx, cz, y0, y1, size):
    """Square prism turned 45 deg, axis along +y: every face at 45 deg, so it prints without support."""
    h = size / 2
    cs = md.CrossSection([np.array([[h, 0], [0, h], [-h, 0], [0, -h]])])
    return cs.extrude(y1 - y0).rotate([-90, 0, 0]).translate([cx, y0, cz])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--size", type=float, nargs=2, metavar=("W", "D"), help="base size in mm (before --offset)")
    g.add_argument("--footprint", help="STL of the model in mm; its plan bounding box is used")
    ap.add_argument("--offset", type=float, default=0.0, help="margin added on every side, mm")
    ap.add_argument("--height", type=float, required=True, help="mm")
    c = ap.add_mutually_exclusive_group()
    c.add_argument("--corner-radius", type=float, default=0.0)
    c.add_argument("--chamfer", type=float, default=0.0, help="45 deg corner cut, leg length in mm")
    ap.add_argument("--hollow", action="store_true", help="shell with ribs, open bottom")
    ap.add_argument("--skin", type=float, default=2.0)
    ap.add_argument("--rib", type=float, default=1.2)
    ap.add_argument("--rib-step", type=float, default=25.0)
    ap.add_argument("--split", action="store_true", help="cut across the long side into A (pins) and B (holes)")
    ap.add_argument("--pin", type=float, default=3.0, help="pin size across the diamond, mm")
    ap.add_argument("--pin-len", type=float, default=3.0)
    ap.add_argument("--clear", type=float, default=0.2, help="hole clearance per side, mm")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="base")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    if a.footprint:
        fp = trimesh.load(a.footprint, process=True)
        if isinstance(fp, trimesh.Scene):
            fp = trimesh.util.concatenate(fp.dump())
        w, d = fp.extents[0], fp.extents[1]
    else:
        w, d = a.size
    W, D, H = w + 2 * a.offset, d + 2 * a.offset, a.height
    shape = outline(W, D, a.corner_radius, a.chamfer)
    body = prism(shape, 0, H)
    notes = []
    hollow = a.hollow
    if hollow and H < 3 * a.skin:
        notes.append("height under 3 x skin: printed solid instead of hollow")
        hollow = False
    cavity = None
    if hollow:
        inner = shape.buffer(-a.skin, join_style=2)
        cavity = prism(inner, -1, H - a.skin)
        ribs = [md.Manifold.cube([a.rib, D + 2, H + 2]).translate([x - a.rib / 2, -1, -2])
                for x in np.arange(a.rib_step, W, a.rib_step)]
        ribs += [md.Manifold.cube([W + 2, a.rib, H + 2]).translate([-1, y - a.rib / 2, -2])
                 for y in np.arange(a.rib_step, D, a.rib_step)]
        if ribs:
            cavity = cavity - union(ribs)

    report = dict(size_mm=[round(W, 2), round(D, 2), round(H, 2)], corner_radius=a.corner_radius,
                  chamfer=a.chamfer, hollow=hollow, notes=notes, parts=[])
    if hollow:
        report.update(skin=a.skin, rib=a.rib, rib_step=a.rib_step, max_unsupported_span_mm=a.rib_step)

    def save(m, tag):
        tm = to_bed(to_trimesh(m))
        fn = "%s%s_mm.stl" % (a.name, tag)
        tm.export(out / fn)
        report["parts"].append(dict(file=fn, size_mm=tm.extents.round(2).tolist(), volume_cm3=round(tm.volume / 1000, 1),
                                    bodies=len(m.decompose()), closed=bool(tm.is_watertight)))
        print(fn, tm.extents.round(1).tolist(), "mm", round(tm.volume / 1000, 1), "cm3")

    solid_vol = body.volume()
    if not a.split:
        piece = body - cavity if cavity is not None else body
        report["share_of_solid"] = round(piece.volume() / solid_vol, 2)
        save(piece, "")
    else:
        turned = W > D                              # cut across the long side: make the long side y
        if turned:
            body = body.rotate([0, 0, 90]).translate([D, 0, 0])
            cavity = cavity.rotate([0, 0, 90]).translate([D, 0, 0]) if cavity is not None else None
            W, D = D, W
        cut = D / 2
        halves = []
        for lo in (True, False):
            region = md.Manifold.cube([W + 2, cut + 1, H + 2]).translate([-1, -1 if lo else cut, -1])
            piece = body ^ region
            if cavity is not None:              # a closed wall SKIN thick on each cut face
                keep = md.Manifold.cube([W + 2, cut - a.skin + 1, H + 2]).translate([-1, -1 if lo else cut + a.skin, -1])
                piece = piece - (cavity ^ keep)
            halves.append(piece)
        zc = (H - a.skin) / 2 if cavity is not None else H / 2
        if a.pin + 3 * a.clear >= 2 * zc:
            raise SystemExit("base too thin for %.1f mm pins: use --pin smaller or no --split" % a.pin)
        pins = [diamond(W * f, zc, cut - (a.skin if cavity is not None else 1.0), cut + a.pin_len, a.pin)
                for f in (0.3, 0.7)]
        # the diamond's size is measured corner to corner; widen it so each flat face clears by --clear
        holes = [diamond(W * f, zc, cut - 0.01, cut + a.pin_len + 0.6, a.pin + 2 * a.clear * 2 ** 0.5)
                 for f in (0.3, 0.7)]
        A = halves[0] + union(pins)
        B = halves[1] - union(holes)
        report.update(cut="across the long side at its middle", pins=dict(size=a.pin, length=a.pin_len,
                                                                            clearance_per_side=a.clear))
        save(A, "_A_pins")
        save(B, "_B_holes")
    (out / ("%s_report.json" % a.name)).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
