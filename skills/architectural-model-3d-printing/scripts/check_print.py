"""Check a print-ready STL (mm, already scaled) before slicing.

Reports, layer by layer the way an FDM printer builds it:
  1. closed solid: watertight, consistent winding, positive volume, number of bodies, bottom at z = 0;
  2. bed fit: does the footprint fit the usable bed at any rotation (and the height);
  3. thin features: cross-sections that vanish or break apart when shrunk by half the
     minimum feature (default 0.8 mm = two lines of a 0.4 mm nozzle) - thin walls,
     hairline necks, point or edge contacts;
  4. islands: parts of a layer that touch nothing below (they start in mid air: support needed);
  5. overhang: area per layer that sticks out more than the overhang angle (default 45 deg).
     Includes bridges; short bridges (the hollow bases here span 25 mm) print without support.

Exit code 1 if the mesh is not a closed solid or does not fit the bed.

usage:
  python check_print.py part.stl --printer x1c
  python check_print.py part.stl --bed 220 220 --nozzle 0.4 --layer 0.2 --json part_check.json

needs: numpy, trimesh, manifold3d, shapely
"""
import argparse
import json
import math
import sys

import numpy as np
import trimesh
from shapely.geometry import MultiPoint, Polygon
from shapely.ops import unary_union

from printkit import PRINTERS, edge_report, to_manifold, usable_area


def section(m, z):
    """Cross-section at height z as a shapely geometry; counter-clockwise contours are
    material, clockwise ones are holes (the inside of a ring of walls)."""
    outer, holes = [], []
    for p in m.slice(float(z)).to_polygons():
        if len(p) < 3:
            continue
        signed = 0.5 * float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))
        (outer if signed > 0 else holes).append(Polygon(p).buffer(0))
    if not outer:
        return Polygon()
    return unary_union(outer).difference(unary_union(holes)) if holes else unary_union(outer)


def parts(g):
    if g.is_empty:
        return []
    return [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon" and p.area > 1e-4]


def fits(hull_xy, w, d, step=1.0):
    """Smallest-rotation fit of a convex footprint in a w x d rectangle. Returns angle or None."""
    pts = np.asarray(hull_xy)
    for ang in np.arange(0.0, 90.0 + 1e-9, step):
        t = math.radians(ang)
        R = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
        q = pts @ R.T
        ex = q.max(0) - q.min(0)
        if (ex[0] <= w and ex[1] <= d) or (ex[1] <= w and ex[0] <= d):
            return float(ang)
    return None


def ranges(zs, layer):
    """[z, z, z] -> [[z0, z1], ...] merging consecutive layers."""
    out = []
    for z in zs:
        if out and z - out[-1][1] <= layer * 1.5:
            out[-1][1] = z
        else:
            out.append([z, z])
    return [[round(a, 2), round(b, 2)] for a, b in out]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stl")
    ap.add_argument("--printer", choices=sorted(PRINTERS))
    ap.add_argument("--bed", type=float, nargs=2, metavar=("W", "D"))
    ap.add_argument("--exclude", type=float, nargs=4, metavar=("X0", "Y0", "X1", "Y1"), help="keep-out area on the bed")
    ap.add_argument("--height", type=float, help="max print height, mm")
    ap.add_argument("--nozzle", type=float, default=0.4)
    ap.add_argument("--min-feature", type=float, help="mm; default 2 x nozzle")
    ap.add_argument("--layer", type=float, default=0.2)
    ap.add_argument("--overhang-angle", type=float, default=45.0, help="degrees from vertical")
    ap.add_argument("--overhang-area", type=float, default=2.0, help="mm^2 per layer worth reporting")
    ap.add_argument("--json")
    a = ap.parse_args()

    tm = trimesh.load(a.stl, process=False)
    if isinstance(tm, trimesh.Scene):
        tm = trimesh.util.concatenate(tm.dump())
    rep = dict(file=a.stl, size_mm=tm.extents.round(2).tolist())
    hard = []

    # 1. closed solid
    try:
        m = to_manifold(tm)
        rep["bodies"] = len(m.decompose())
        rep["volume_cm3"] = round(m.volume() / 1000, 2)
    except ValueError as e:
        m = None
        rep["manifold_error"] = str(e)
    edges = edge_report(tm)
    rep["closed_solid"] = bool(m is not None and edges["open_edges"] == 0 and m.volume() > 0)
    rep.update(edges)
    if not rep["closed_solid"]:
        hard.append("not a closed solid (holes or open edges): re-export from CAD as closed solids")
    if edges["edge_contacts"]:
        rep["note_edges"] = ("solids touch only along an edge (xy z listed, mm). Bambu Studio slices this; strict "
                             "checkers call it 'not watertight'. On the print it is a zero-width joint: if it must "
                             "hold, extend one part by a short tongue so they share a face.")
    rep["z_min"] = round(float(tm.bounds[0][2]), 3)
    if abs(rep["z_min"]) > 0.01:
        rep["note_z"] = "lowest point is not at z = 0 (slicers drop it, but check the intended bottom face)"

    # 2. bed fit
    if a.printer or a.bed:
        excl = [tuple(a.exclude)] if a.exclude else None
        w, d = usable_area(a.printer, a.bed, excl)
        height = a.height or (PRINTERS[a.printer]["height"] if a.printer else None)
        hull = MultiPoint([tuple(p) for p in tm.vertices[:, :2]]).convex_hull
        ang = fits(np.asarray(hull.exterior.coords), w, d) if hull.geom_type == "Polygon" else 0.0
        rep["bed"] = dict(usable_mm=[round(w, 1), round(d, 1)], fits=ang is not None,
                          rotation_deg=ang, height_ok=None if height is None else bool(tm.extents[2] <= height))
        if ang is None:
            hard.append("does not fit the usable bed %.0f x %.0f mm at any rotation: split it, or use a bigger bed"
                        % (w, d))
        elif ang:
            rep["bed"]["note"] = "fits only when turned %.0f deg on the plate" % ang
        if height is not None and tm.extents[2] > height:
            hard.append("taller than the printer's %.0f mm" % height)

    # 3-5. layer checks
    if m is not None:
        mf = a.min_feature or 2 * a.nozzle
        shrink = mf / 2 - 0.001
        grow = a.layer * math.tan(math.radians(a.overhang_angle))
        z0, z1 = tm.bounds[0][2], tm.bounds[1][2]
        thin, islands, over = [], [], []
        prev = None
        for z in np.arange(z0 + a.layer / 2, z1, a.layer):
            sec = section(m, z)
            for p in parts(sec):
                core = parts(p.buffer(-shrink, join_style=2))
                if not core:
                    thin.append((z, "thinner than %.2f mm" % mf, p.representative_point()))
                elif len(core) > 1:
                    thin.append((z, "neck under %.2f mm" % mf, p.representative_point()))
            if prev is not None:
                below = prev.buffer(0.01)
                for p in parts(sec):
                    if not p.intersects(below):
                        islands.append((z, p.area, p.representative_point()))
                hang = sec.difference(prev.buffer(grow, join_style=2))
                if hang.area > a.overhang_area:
                    over.append((z, hang.area))
            prev = sec

        def where(items):
            seen, out = set(), []
            for z, w, pt in items:                      # first layer of each distinct place
                key = (round(pt.x), round(pt.y), w)
                if key not in seen:
                    seen.add(key)
                    out.append(dict(z_from=round(z, 2), xy=[round(pt.x, 1), round(pt.y, 1)], what=w))
            return out[:8]

        rep["min_feature_mm"] = mf
        rep["thin"] = dict(layers=len({round(t[0], 3) for t in thin}),
                           z_ranges=ranges(sorted({t[0] for t in thin}), a.layer), examples=where(thin))
        rep["islands"] = [dict(z=round(z, 2), area_mm2=round(ar, 2), xy=[round(pt.x, 1), round(pt.y, 1)])
                          for z, ar, pt in islands[:12]]
        rep["overhang"] = dict(layers=len(over), z_ranges=ranges([o[0] for o in over], a.layer),
                               worst=[dict(z=round(z, 2), area_mm2=round(ar, 1))
                                      for z, ar in sorted(over, key=lambda o: -o[1])[:5]])
        rep["overhang"]["note"] = ("includes bridges between walls or ribs; spans up to about 25 mm bridged "
                                   "cleanly in practice, larger overhangs need support or another orientation")
        rep["needs_support"] = bool(islands)

    rep["problems"] = hard
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1)
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()
