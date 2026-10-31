# -*- coding: utf-8 -*-
"""Run inside Rhino (7 or 8): export every VISIBLE object as a print piece, to a JSON file
that prepare_parts.py reads.

Why not just File > Export STL:
- block instances are exploded with their own transform (some exporters skip block
  references and export only the block definition - one copy instead of two);
- hidden objects and objects on hidden/locked-off layers are skipped and listed
  (a hidden copy is often the original of something moved or rotated);
- each solid stays separate, so prepare_parts.py can union solids that only touch
  along an edge (an STL export welds them into a non-manifold mesh);
- each block records its rotation and whether it is mirrored (determinant < 0):
  a half turned 180 deg is a rotation, not a mirror image - check before printing two.

How to run:
  Rhino 8: command  _ScriptEditor  -> open this file -> Run
           or        _-RunPythonScript "path/to/rhino_export_pieces.py"
  Rhino 7: _EditPythonScript -> open -> Run
Writes <model name>_pieces.json next to the .3dm (asks for a path if the model is unsaved).
Units are the model's units; prepare_parts.py converts them.
"""
import json
import math
import os

import Rhino
import Rhino.Geometry as rg
import scriptcontext

# ---- settings ---------------------------------------------------------------------------
PIECE_BY = "object"        # "object": each visible object (a block = one piece); "layer": one piece per layer
MESH_TOL_MM = 3.0          # meshing tolerance in REAL size mm (3 mm real = 0.03 mm at 1:96)
OUT_PATH = None            # None: next to the .3dm
# -------------------------------------------------------------------------------------------

doc = globals().get("__rhino_doc__") or scriptcontext.doc

MM = {Rhino.UnitSystem.Millimeters: 1.0, Rhino.UnitSystem.Centimeters: 10.0, Rhino.UnitSystem.Meters: 1000.0,
      Rhino.UnitSystem.Inches: 25.4, Rhino.UnitSystem.Feet: 304.8}
NAME = {Rhino.UnitSystem.Millimeters: "mm", Rhino.UnitSystem.Centimeters: "cm", Rhino.UnitSystem.Meters: "m",
        Rhino.UnitSystem.Inches: "in", Rhino.UnitSystem.Feet: "ft"}
units = doc.ModelUnitSystem
if units not in MM:
    raise Exception("model units %s not supported; use mm, cm, m, in or ft" % units)

mp = rg.MeshingParameters.QualityRenderMesh
mp.JaggedSeams = False
mp.SimplePlanes = True
mp.RefineGrid = True
mp.Tolerance = MESH_TOL_MM / MM[units]


def mesh_dict(mesh, closed):
    mesh.Faces.ConvertQuadsToTriangles()
    mesh.Vertices.CombineIdentical(True, True)
    mesh.Compact()
    v = [[p.X, p.Y, p.Z] for p in mesh.Vertices]
    f = [[fc.A, fc.B, fc.C] for fc in mesh.Faces]
    return dict(closed=bool(closed), v=v, f=f)


def solids_of(geom):
    """List of (mesh dict) for one piece of geometry, already in world position."""
    if isinstance(geom, rg.Extrusion):
        geom = geom.ToBrep(True)
    if hasattr(rg, "SubD") and isinstance(geom, rg.SubD):
        geom = geom.ToBrep(rg.SubDToBrepOptions.Default)
    if isinstance(geom, rg.Brep):
        mesh = rg.Mesh()
        for m in rg.Mesh.CreateFromBrep(geom, mp) or []:
            mesh.Append(m)
        mesh.Weld(math.pi)
        return [mesh_dict(mesh, geom.IsSolid)]
    if isinstance(geom, rg.Mesh):
        return [mesh_dict(geom.DuplicateMesh(), geom.IsClosed)]
    return None


def layer_visible(obj):
    layer = doc.Layers[obj.Attributes.LayerIndex]
    return layer.IsVisible


def explode(idef, xform, out, skipped, path):
    for member in idef.GetObjects():
        g = member.Geometry
        if isinstance(member, Rhino.DocObjects.InstanceObject):
            explode(member.InstanceDefinition, xform * member.InstanceXform, out, skipped,
                    path + "/" + member.InstanceDefinition.Name)
            continue
        g = g.Duplicate()
        g.Transform(xform)
        s = solids_of(g)
        if s is None:
            skipped.append(dict(why="not a solid (in block %s)" % path, type=str(member.ObjectType)))
        else:
            out += s


settings = Rhino.DocObjects.ObjectEnumeratorSettings()   # include hidden objects, so they can be listed
settings.HiddenObjects = True
settings.LockedObjects = True
settings.NormalObjects = True
settings.ReferenceObjects = True
settings.IncludeLights = False
settings.IncludeGrips = False

pieces, skipped = {}, []
for obj in doc.Objects.GetObjectList(settings):
    if obj.IsDeleted:
        continue
    sid = str(obj.Id)[:8]
    if obj.IsHidden or not obj.Visible or not layer_visible(obj):
        skipped.append(dict(why="hidden", id=sid, type=str(obj.ObjectType), name=obj.Name or ""))
        continue
    solids, meta = [], dict(id=sid, layer=doc.Layers[obj.Attributes.LayerIndex].FullPath)
    if isinstance(obj, Rhino.DocObjects.InstanceObject):
        xf = obj.InstanceXform
        explode(obj.InstanceDefinition, xf, solids, skipped, obj.InstanceDefinition.Name)
        meta.update(kind="block", block=obj.InstanceDefinition.Name,
                    rotation_deg=round(math.degrees(math.atan2(xf.M10, xf.M00)), 2),
                    mirrored=bool(xf.Determinant < 0))
    else:
        s = solids_of(obj.Geometry)
        if s is None:
            skipped.append(dict(why="not a solid", id=sid, type=str(obj.ObjectType), name=obj.Name or ""))
            continue
        solids = s
        meta.update(kind=str(obj.ObjectType))
    if not solids:
        continue
    key = meta["layer"] if PIECE_BY == "layer" else (obj.Name or meta.get("block") or "piece") + "_" + sid
    pc = pieces.setdefault(key, dict(name=key.replace("::", "_"), solids=[], members=[]))
    pc["solids"] += solids
    pc["members"].append(meta)

out_path = OUT_PATH
if not out_path:
    if doc.Path:
        out_path = os.path.splitext(doc.Path)[0] + "_pieces.json"
    else:
        import rhinoscriptsyntax as rs
        out_path = rs.SaveFileName("Save pieces JSON", "JSON (*.json)|*.json||")
if out_path:
    data = dict(units=NAME[units], mm_per_unit=MM[units], source=os.path.basename(doc.Path or "unsaved"),
                pieces=list(pieces.values()), skipped=skipped)
    with open(out_path, "w") as fh:
        json.dump(data, fh)
    open_solids = sum(1 for p in pieces.values() for s in p["solids"] if not s["closed"])
    print("wrote %s: %d pieces, %d solids (%d not closed), %d skipped" % (
        out_path, len(pieces), sum(len(p["solids"]) for p in pieces.values()), open_solids, len(skipped)))
    for p in pieces.values():
        for m in p["members"]:
            if m.get("kind") == "block":
                print("  %s: block %s, rotation %.1f deg%s" % (p["name"], m["block"], m["rotation_deg"],
                                                              ", MIRRORED" if m["mirrored"] else ""))
    for s in skipped:
        print("  skipped: %s" % s)
