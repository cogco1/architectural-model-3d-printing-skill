"""Shared helpers for the architectural-model-3d-printing scripts.

Needs: numpy, trimesh, manifold3d, shapely (see requirements.txt).
"""
import json
from pathlib import Path

import manifold3d as md
import numpy as np
import trimesh

# millimetres per model unit
MM_PER_UNIT = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}

# Bed sizes (mm) and keep-out areas, as listed in Bambu Studio's own machine presets.
# Other printers: pass --bed W D [--exclude X0 Y0 X1 Y1] instead.
PRINTERS = {
    "x1c": dict(bed=(256.0, 256.0), height=250.0, exclude=[(0.0, 0.0, 18.0, 28.0)]),
    "p1s": dict(bed=(256.0, 256.0), height=250.0, exclude=[(0.0, 0.0, 18.0, 28.0)]),
    "a1": dict(bed=(256.0, 256.0), height=256.0, exclude=[]),
    "h2s": dict(bed=(340.0, 320.0), height=340.0, exclude=[]),
}
MARGIN = 4.0  # mm kept clear along every bed edge when packing


def usable_area(printer=None, bed=None, exclude=None, margin=MARGIN):
    """Width and depth (mm) of the rectangle that is safe to fill.

    The keep-out strip is taken off the width, which is conservative: a plate
    this size can always be placed clear of it (Bambu Studio: Arrange, key A).
    """
    if printer:
        p = PRINTERS[printer.lower()]
        bed, exclude = p["bed"], p["exclude"]
    exclude = exclude or []
    w = bed[0] - 2 * margin - sum(x1 - x0 for x0, _, x1, _ in exclude)
    d = bed[1] - 2 * margin
    return w, d


def to_manifold(tm):
    """trimesh -> manifold3d. Raises ValueError if the mesh has holes.

    Vertices are merged only where that keeps the solid manifold, so two blocks that
    touch along an edge (an edge shared by four faces once welded) still load.
    Load STL files with process=False so that this merge, not trimesh's, decides."""
    mesh = md.Mesh(np.asarray(tm.vertices, np.float32), np.asarray(tm.faces, np.uint32))
    m = md.Manifold(mesh)
    if m.status() != md.Error.NoError:
        mesh.merge()
        m = md.Manifold(mesh)
    if m.status() != md.Error.NoError:
        raise ValueError(str(m.status()))
    return m


def edge_report(tm, k=1.0):
    """Edges with one face (holes) and with more than two faces (solids touching along an edge)
    once vertices are welded by position, as strict mesh checkers see it. k converts the
    sample locations (e.g. back to model units)."""
    w = tm.copy()
    w.merge_vertices()
    edges, counts = np.unique(w.edges_sorted, axis=0, return_counts=True)
    contact = edges[counts > 2]
    where = (w.vertices[contact].mean(1) / k).round(2).tolist()[:6] if len(contact) else []
    return dict(open_edges=int((counts == 1).sum()), edge_contacts=int(len(contact)), edge_contact_at=where)


def to_trimesh(m):
    mesh = m.to_mesh()
    return trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=False)


def union(parts):
    if not parts:
        return md.Manifold()
    return md.Manifold.batch_boolean(parts, md.OpType.Add)


def solid_from_arrays(v, f):
    tm = trimesh.Trimesh(np.asarray(v, float), np.asarray(f, np.int64), process=False)
    tm.update_faces(tm.nondegenerate_faces())
    if tm.volume < 0:
        tm.invert()
    return tm


def load_pieces(paths):
    """Return (pieces, units). Each piece is dict(name, solids=[trimesh], meta).

    - *.json written by rhino_export_pieces.py: its pieces, units from the file.
    - any mesh file trimesh reads (stl, obj, 3mf, ply, glb, off): one piece per file;
      a scene's separate geometries become separate solids. Units: unknown (None).
    """
    pieces, units = [], None
    for p in map(Path, paths):
        if p.suffix.lower() == ".json":
            d = json.loads(p.read_text(encoding="utf-8"))
            units = d.get("units", units)
            for pc in d["pieces"]:
                solids = [solid_from_arrays(s["v"], s["f"]) for s in pc["solids"] if s["f"]]
                meta = {k: v for k, v in pc.items() if k != "solids"}
                pieces.append(dict(name=pc.get("name") or p.stem, solids=solids, meta=meta))
            continue
        loaded = trimesh.load(str(p), process=False)  # keep raw: see to_manifold
        if isinstance(loaded, trimesh.Scene):
            geoms = [g for g in loaded.dump() if isinstance(g, trimesh.Trimesh)]
        else:
            geoms = [loaded]
        solids = [solid_from_arrays(g.vertices, g.faces) for g in geoms if len(g.faces)]
        pieces.append(dict(name=p.stem, solids=solids, meta=dict(source=p.name)))
    return pieces, units


def piece_to_manifold(solids, log):
    """Union the solids of one piece. Solids that touch only along an edge share that
    edge between four faces; a mesh tool then calls the result 'not watertight'. A real
    boolean union removes that. Solids that are not closed are reported and skipped."""
    parts = []
    for i, tm in enumerate(solids):
        try:
            parts.append(to_manifold(tm))
        except ValueError:
            # one mesh may hold several closed shells that touch: try them one by one
            bodies = tm.split(only_watertight=False)
            ok = []
            for b in bodies:
                try:
                    ok.append(to_manifold(b))
                except ValueError:
                    ok = None
                    break
            if ok:
                parts += ok
            else:
                log.append("solid %d is not closed (open edges or self-touching); skipped" % i)
    return union(parts)


def fill_cavities(m):
    """Drop enclosed inner shells (negative volume) so hidden voids print solid."""
    comps = m.decompose()
    outer = [c for c in comps if c.volume() > 0]
    return union(outer), len(comps) - len(outer)


def drop_slivers(m, min_volume):
    comps = m.decompose()
    keep = [c for c in comps if c.volume() >= min_volume]
    return union(keep), len(comps) - len(keep)


def bodies(tm, min_volume=0.0):
    """Split a (possibly multi-part) mesh into closed bodies as trimesh objects."""
    try:
        comps = to_manifold(tm).decompose()
        return [to_trimesh(c) for c in comps if c.volume() >= min_volume]
    except ValueError:
        return [b for b in tm.split(only_watertight=False) if abs(b.volume) >= min_volume]


def to_bed(tm):
    tm = tm.copy()
    tm.apply_translation(-tm.bounds[0])
    return tm
