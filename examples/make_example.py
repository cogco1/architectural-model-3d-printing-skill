"""Write a tiny made-up model (feet) in the same JSON format rhino_export_pieces.py writes, so the
scripts can be tried without Rhino:

  ground  - 0.5 ft slab, 1 ft outer walls 9 ft tall, a 0.5 ft partition; two walls touch only
            along an edge (a classic non-manifold export);
  upper   - 0.5 ft slab with a 4 ft cantilever, walls, and a 3 in (0.25 ft) fin that is too thin
            at 1:96 (0.79 mm);
  boards  - five 0.5 ft wall boards in assembled position, one of them L-shaped.

usage: python make_example.py   (writes tiny_house_pieces_ft.json next to this file)
"""
import json
from pathlib import Path

FACES = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
         [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]


def box(x0, y0, z0, x1, y1, z1):
    v = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
         [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]
    return dict(closed=True, v=v, f=FACES)


ground = [
    box(0, 0, 0, 24, 16, 0.5),           # slab
    box(0, 0, 0.5, 24, 1, 9.5),          # south wall
    box(0, 15, 0.5, 24, 16, 9.5),        # north wall
    box(0, 1, 0.5, 1, 15, 9.5),          # west wall
    box(23, 1, 0.5, 24, 15, 9.5),        # east wall
    box(11.75, 1, 0.5, 12.25, 10, 9.5),  # 0.5 ft partition, stops short: a free end
    box(12.25, 10, 0.5, 16, 10.5, 9.5),  # meets the partition only along one vertical edge
]
upper = [
    box(0, 0, 0, 28, 16, 0.5),           # slab, 4 ft cantilever to the east
    box(0, 0, 0.5, 24, 1, 9),
    box(0, 15, 0.5, 24, 16, 9),
    box(0, 1, 0.5, 1, 15, 9),
    box(23, 1, 0.5, 24, 15, 9),
    box(26, 2, 0.5, 26.25, 14, 3.5),     # 3 in fin on the cantilever: too thin at 1:96
]
boards = [                               # lining boards, 0.5 ft thick, 0.1 ft apart
    box(1, 1, 0.5, 11.75, 1.5, 9.5),
    box(12.25, 1, 0.5, 23, 1.5, 9.5),
    box(1, 14.5, 0.5, 23, 15, 9.5),
    box(22.5, 1.6, 0.5, 23, 14.4, 9.5),
    # an L: two leaves meeting in a room corner - cannot lie flat
    box(1, 1.6, 0.5, 1.5, 13.9, 9.5),
    box(1.5, 13.4, 0.5, 6, 13.9, 9.5),
]
data = dict(units="ft", mm_per_unit=304.8, source="made-up example", skipped=[],
            pieces=[dict(name="ground", solids=ground), dict(name="upper", solids=upper),
                    dict(name="boards", solids=boards)])
out = Path(__file__).resolve().parent / "tiny_house_pieces_ft.json"
out.write_text(json.dumps(data), encoding="utf-8")
print("wrote", out)
