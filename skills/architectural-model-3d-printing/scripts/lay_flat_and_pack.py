"""Number the loose parts of a model, lay thin boards flat and pack them onto bed-sized plates.

Typical use: the thin wall boards / panels / inserts of a section or kit model. Each
input STL (mm, already scaled) may hold many bodies in their assembled positions.

- Parts are named <prefix><k>, numbered north to south (in bands of --band mm), then
  west to east, from their assembled positions. Keep these numbers once printing starts.
- A part whose plan thickness is <= --flat-t lies down on its face; the face with more
  flat area goes on the bed (grooves and reliefs face up). Anything else stays upright
  and is listed: an L- or U-shaped board cannot lie flat - cut it at the corner into
  flat legs and run this again.
- Packing: long side along x, biggest first, in columns, --gap mm apart, onto as many
  plates as needed. The plate size is the usable bed (bed minus keep-out strip minus a
  4 mm margin); if the slicer still warns about the keep-out corner, press Arrange (A).
- Writes plate STLs, a JSON list (part -> plate, position, flat/upright) and, if
  matplotlib is installed, a map: plan with every part numbered + each plate numbered.

usage:
  python lay_flat_and_pack.py boards.stl --prefix F1- --printer x1c --out plates_v01
  python lay_flat_and_pack.py a.stl b.stl --prefix W --bed 220 220 --gap 5 --out plates

needs: numpy, trimesh, manifold3d, shapely; matplotlib for the map
"""
import argparse
import json
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Polygon

from printkit import PRINTERS, bodies, to_bed, to_manifold, usable_area


def lay(tm, flat_t):
    e = tm.extents
    if e[1] <= flat_t and e[1] <= e[0]:          # thin in y: turn about x
        R = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
    elif e[0] <= flat_t:                         # thin in x: turn about y
        R = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
    else:
        return tm.copy(), e[2] <= flat_t         # already flat, or upright
    out = tm.copy()
    out.apply_transform(R)
    nz, area = out.face_normals[:, 2], out.area_faces
    if area[nz > 0.99].sum() > area[nz < -0.99].sum():   # more flat area facing up: turn over
        out.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))
    return out, True


def pack(items, bed_w, bed_d, gap):
    turned = []
    for name, tm in items:
        tm = to_bed(tm)
        if tm.extents[1] > tm.extents[0]:
            tm.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]))
            tm = to_bed(tm)
        turned.append((name, tm))
    turned.sort(key=lambda it: (-it[1].extents[0], -it[1].extents[1]))
    plates = []
    for name, tm in turned:
        w, d = tm.extents[0], tm.extents[1]
        if w > bed_w or d > bed_d:
            raise SystemExit("part %s (%.1f x %.1f mm) is larger than the plate %.0f x %.0f mm: split it first"
                             % (name, w, d, bed_w, bed_d))
        spot = None
        for pl in plates:
            for col in pl["cols"]:
                if w <= col[1] + 1e-6 and col[2] + d <= bed_d:
                    spot = (pl, col)
                    break
            if spot is None and pl["x"] + w <= bed_w:
                col = [pl["x"], w, 0.0]
                pl["cols"].append(col)
                pl["x"] += w + gap
                spot = (pl, col)
            if spot:
                break
        if spot is None:
            pl = dict(x=w + gap, cols=[[0.0, w, 0.0]], parts=[])
            plates.append(pl)
            spot = (pl, pl["cols"][0])
        pl, col = spot
        placed = tm.copy()
        placed.apply_translation([col[0], col[2], 0])
        col[2] += d + gap
        pl["parts"].append((name, placed))
    return [pl["parts"] for pl in plates]


def draw_map(path, inplace, plates, bed_w, bed_d, title):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    n = 1 + len(plates)
    fig, axs = plt.subplots(1, n, figsize=(7 * n, 8))
    axs = np.atleast_1d(axs)
    def plan(ax, tm, name):
        """Fill the part's plan outline (holes in white) and label it."""
        try:
            contours = to_manifold(tm).project().to_polygons()
        except ValueError:
            b = tm.bounds
            contours = [np.array([b[0][:2], [b[1][0], b[0][1]], b[1][:2], [b[0][0], b[1][1]]])]
        for c in contours:
            signed = 0.5 * np.sum(c[:, 0] * np.roll(c[:, 1], -1) - np.roll(c[:, 0], -1) * c[:, 1])
            ax.add_patch(plt.Polygon(c, closed=True, fc="#e8c39e" if signed > 0 else "white", ec="#7a4a1e", lw=0.8))
        big = max(contours, key=lambda c: Polygon(c).area)
        pt = Polygon(big).buffer(0).representative_point()   # inside the part, also for an L
        ax.text(pt.x, pt.y, name, ha="center", va="center", fontsize=8, weight="bold",
                bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.8))

    ax = axs[0]
    for name, tm in inplace:
        plan(ax, tm, name)
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.set_title("%s: assembled position (north up)" % title)
    for ax, (k, pl) in zip(axs[1:], enumerate(plates, 1)):
        ax.add_patch(plt.Rectangle((0, 0), bed_w, bed_d, fill=False, ec="black", ls="--"))
        for name, tm in pl:
            plan(ax, tm, name)
        ax.set_xlim(-5, bed_w + 5)
        ax.set_ylim(-5, bed_d + 5)
        ax.set_aspect("equal")
        ax.set_title("plate %d as on the bed (mm)" % k)
    plt.tight_layout()
    plt.savefig(path, dpi=90)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="STL files in mm, parts in assembled position")
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="P", help="part name prefix, e.g. F1- (floor 1)")
    ap.add_argument("--printer", choices=sorted(PRINTERS))
    ap.add_argument("--bed", type=float, nargs=2, metavar=("W", "D"))
    ap.add_argument("--flat-t", type=float, default=2.6, help="mm; thinner parts lie flat (default 2.6)")
    ap.add_argument("--gap", type=float, default=5.0, help="mm between parts (default 5)")
    ap.add_argument("--band", type=float, default=20.0, help="mm; numbering rows, north to south")
    ap.add_argument("--sliver", type=float, default=5.0, help="ignore bodies under this many mm^3")
    ap.add_argument("--no-flat", action="store_true", help="keep every part as it stands")
    a = ap.parse_args()
    if not (a.printer or a.bed):
        ap.error("give --printer or --bed")
    bed_w, bed_d = usable_area(a.printer, a.bed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    parts = []
    for f in a.inputs:
        tm = trimesh.load(f, process=False)
        if isinstance(tm, trimesh.Scene):
            tm = trimesh.util.concatenate(tm.dump())
        parts += bodies(tm, a.sliver)
    parts.sort(key=lambda p: (-round(p.bounds[1][1] / a.band), p.bounds[0][0]))
    inplace, items, rows = [], [], []
    for k, p in enumerate(parts, 1):
        name = "%s%d" % (a.prefix, k)
        inplace.append((name, p))
        flat, ok = (p.copy(), p.extents[2] <= a.flat_t) if a.no_flat else lay(p, a.flat_t)
        items.append((name, flat))
        rows.append(dict(name=name, size_assembled_mm=p.extents.round(2).tolist(),
                         printed="flat" if ok else "upright", volume_mm3=round(float(p.volume), 1)))
    plates = pack(items, bed_w, bed_d, a.gap)
    where = {}
    for i, pl in enumerate(plates, 1):
        mesh = trimesh.util.concatenate([m for _, m in pl])
        fn = "%splate%d_mm.stl" % (a.prefix, i)
        mesh.export(out / fn)
        for name, m in pl:
            where[name] = dict(plate=fn, xy_mm=m.bounds[0][:2].round(1).tolist())
        print("%s: %d parts, %s mm" % (fn, len(pl), mesh.extents.round(1).tolist()))
    for r in rows:
        r.update(where[r["name"]])
    upright = [r["name"] for r in rows if r["printed"] == "upright"]
    report = dict(usable_plate_mm=[round(bed_w, 1), round(bed_d, 1)], parts=rows, upright=upright)
    (out / ("%sparts.json" % a.prefix)).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if draw_map(out / ("%smap.png" % a.prefix), inplace, plates, bed_w, bed_d, a.prefix.rstrip("-_ ") or "parts"):
        print("map:", out / ("%smap.png" % a.prefix))
    if upright:
        print("standing upright (cut L/U shapes at the corner into flat legs):", ", ".join(upright))


if __name__ == "__main__":
    main()
