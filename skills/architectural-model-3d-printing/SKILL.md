---
name: architectural-model-3d-printing
description: Use when turning an architectural CAD model (Rhino, SketchUp, Revit or any STL/OBJ/3MF) into FDM 3D-print files for a physical study, massing or section model - choosing the scale and converting feet/inches to mm, checking wall thickness and thin parts, splitting by floor/bed/material, adding tenons, pins and clearances, making a base, exporting STL/3MF, laying parts out on the bed, estimating time with Bambu Studio, and fixing parts that failed or do not fit after printing. Also use when a print came out wrong or an STL is "not watertight".
---

# Architectural model 3D printing

How to get from a design model to plates on FDM printers (written on Bambu Lab X1C, A1
and H2S with a 0.4 mm nozzle and PLA; the rules carry over to other printers - change the
bed size). Numbers marked *(printed)* were printed and assembled; *(not test-fit)* were
designed and sliced but never assembled - print one piece first.

中文版：[SKILL.zh-CN.md](SKILL.zh-CN.md)

Scripts in `scripts/` (Python 3, `pip install -r requirements.txt`):

| step | script | does |
|---|---|---|
| export | `rhino_export_pieces.py` | runs inside Rhino; visible objects only, blocks exploded, solids kept separate -> JSON |
| prepare | `prepare_parts.py` | union each piece, fill hidden voids, drop slivers, scale to mm, z = 0, report |
| check | `check_print.py` | closed solid, bed fit at any rotation, thin walls/necks, islands, overhang |
| pack | `lay_flat_and_pack.py` | number parts, lay thin boards flat, pack plates, numbered map |
| base | `make_base.py` | plinth: offset, rounded/chamfered corners, hollow with ribs, split with pins |
| slice | `bambu_slice_estimate.py` | Bambu Studio CLI with system presets -> time, grams, warnings |

## 0. Ground rules

- Never change the source model. Every print file is a derived copy in its own folder,
  `..._v01`, `..._v02`; keep old versions. Each folder gets a short README: what changed
  and why, which file goes to which printer in what order, estimated time and grams,
  orientation, assembly steps, parts not to use.
- Print files are in **mm and already scaled**. Say "import at 100 %, do not scale again"
  in every README.
- File names say what, floor, material, printer and scale, e.g.
  `section_1-96_F2_white_X1C.stl`, `section_1-96_wood_plate1_X1C.stl`.
- Do not send jobs to a printer unless the user asks. (Bambu: with no SD card use
  "Send", not "Send to printer storage".)

## 1. Receive the model

Ask (or read from the brief) before building anything:
1. **Scale** and model **units**. mm on the print per model foot = 304.8 / N.

   | scale | 1:N | 1 ft = | 0.5 ft wall | 1 ft wall | 2 ft wall |
   |---|---|---|---|---|---|
   | 3/16" = 1'-0" | 64 | 4.763 mm | 2.38 | 4.76 | 9.53 |
   | 1/8" = 1'-0" | 96 | 3.175 mm | 1.59 | 3.18 | 6.35 |
   | 3/32" = 1'-0" | 128 | 2.381 mm | 1.19 | 2.38 | 4.76 |
   | 1/16" = 1'-0" | 192 | 1.588 mm | 0.79 (too thin) | 1.59 | 3.18 |

   An STL exported at full size in mm is scaled in the slicer by 100/N % (1:128 = 0.78125 %).
2. **Printers and filaments** available (decides bed size and how many parallel plates).
3. **How it will be assembled**: one piece (fastest), floors that lift off (shows plans,
   allows a colour per floor), upper/lower groups, halves. Ask before merging - a user who
   wanted "two pieces per floor, one plate per floor" had to undo a merged version.
4. **Colours/materials**: e.g. interior wood-tone, exterior white. One filament per plate.

Then inspect the file:
- **Blocks**: some exporters skip block references and export only the block definition
  (one copy instead of two). Explode blocks with their own transform.
- **Hidden objects / layers off**: skip them, but list them. A hidden copy is often the
  original of a moved or rotated piece and must not be printed twice.
- **Rotated or mirrored**: a half "turned 180 deg" has transform determinant +1 (rotation,
  same part twice); -1 is a mirror image (a different part).
- **Floors in separate files** may sit at different positions; find the translation that
  stacks them before splitting or checking.
- **Pick the scale from the bed**: if the largest piece needs cutting at one scale, check
  the next scale down. A 3/16" half section was 205 x 267 mm (cut in two, about 18 h of white
  on one printer); at 1/8" each floor was 137 x 178 mm, whole, about 2.4-3.3 h each.
  Keeping a roof in one piece by dropping the scale is a valid choice - ask.

## 2. Check

Run `check_print.py part.stl --printer x1c` on every part after step 5; fix in the model,
not by hand in the slicer.

- **Minimum feature 0.8 mm** for a 0.4 mm nozzle (two lines). 0.5 ft walls are fine at 1:96
  (1.59) and 1:128 (1.19), too thin at 1:192. A 3 in (0.25 ft) fin at 1:96 is 0.79 mm: thicken
  it or leave it out. Detail below 0.8 mm (0.65 mm shelves, 0.45 mm door slits) was only
  planned with 0.12 mm layers and Arachne walls *(not test-fit)*.
- **Thin necks fail physically** *(printed)*: a room model whose wide deck stood on thin
  wheels, sliced without supports, broke loose with strands of filament; the sliced
  preview showed a gap at the layer where the section jumped. Fix: 1 mm internal pillars
  from the wheels to the deck, 0.8 mm ties where parts only touch or float, supports on,
  and look at the sliced layers at that height before printing again.
- **Edge-only contact**: solids that touch only along a line give edges shared by four
  faces. Bambu Studio slices it; strict checkers and print-prep tools reject it as "not
  watertight". On the print it is a zero-width joint. If it must hold, give one part a
  short tongue (0.2 ft was enough) so the two share a face.
- **Gaps that look closed**: a stair that stopped 0.2 ft short of the slab, a stair landing
  that met its slab only along a line, outer walls overhanging the slab edge by 3 in
  (0.79 mm at 1:96). Close them in the model before printing.
- **Hidden voids**: fill enclosed cavities solid (`prepare_parts.py` does it).
- **What does not print**: glass (leave openings empty), thin shelves inside cabinets
  (fill the cabinet outline solid), loose furniture and fixture placeholders (remove when
  the user wants architecture only), zero-thickness surfaces.
- **"Solid" means two things**: a massing model "printed solid" has its rooms filled in
  the model; the printer still uses normal infill (15 %). Do not confuse it with 100 % infill.

## 3. Split

**Bed sizes** (from Bambu Studio's presets): X1C / P1S 256 x 256 mm with an 18 x 28 mm
keep-out at the front-left; A1 256 x 256; H2S 340 x 320. Plan X1C plates at about
230 x 248 mm. 257.2 mm does not fit a 256 mm bed, even diagonally.

Where to cut, in order of preference:
1. **Along gaps between masses** so no roof or volume is cut.
2. **On a wall face**: put the cut plane on the face of a wall line so both halves meet
   on a flat face and the seam hides in the wall.
3. **Per floor at the slab underside**: each floor keeps its own slab and lifts off.
4. **Upper/lower** just above the ground-floor walls (e.g. at +9.5 ft), the upper group
   sitting on the wall tops.
5. **Around an end room**, cutting 0.02 ft beyond the outer wall face so no zero-thickness
   sliver is left.

Also:
- One material/colour per plate; the same printer can print the wood plates, then the white.
- Keep each piece in its model orientation; a half that is turned 180 deg stays turned;
  pieces side by side 8 mm apart.
- A half-section model: cut on the section plane, print each half lying on its back wall.

## 4. Thicken, join and locate

Clearances (per side, PLA on X1C/H2S class printers):

| joint | value |
|---|---|
| board slid into a slot in the body, all round | 0.15 mm *(printed, 1:96 section model)* |
| pin into hole (diamond pins, base halves) | 0.2 mm *(not test-fit)* |
| alignment edge against existing geometry (stair opening) | 0.2 mm *(not test-fit)* |
| removable 1.20 mm partition plates in slots 1.70 wide x 1.80 deep (0.25 per side), 0.30 mm below the roof | *(not test-fit)* |
| lift-off roof on locating grooves | 0.2 mm in plan, 0.1 mm vertical *(not test-fit)* |
| cabinet feet into 0.60 mm deep base slots | 0.18 mm *(not test-fit)* |

- **Tenon into the slab** *(printed)*: a strip on top of a board, 0.6 mm tall at 1:96
  (1.0 mm at 1:64), 0.3 mm narrower than the board on each side (0.4 at 1:64) so a shoulder
  rests under the slab; a 1.59 mm slab keeps 0.84 mm above the pocket. Boards with no slab
  above them are held by end posts and the body behind, and glued.
- **Diamond pins**: a square prism turned 45 deg, 3 mm across, 3 mm long, prints sideways
  without support.
- **Prefer existing geometry for alignment** (a stair opening, the base seam) to tiny tenons.
- **Openings as shallow relief** in solid massing: windows, skylights, cabinet doors recessed
  0.25 ft (0.6 mm at 1:128); skylights keep a 0.5 ft rim. At 1:96, 0.5 mm deep door recesses
  with a 0.5 mm bevel, keeping at least 1.0 mm of wall behind.
- **Cabinet walls** (2 ft thick, 9 ft high) read as cabinets with grooves 0.25 ft wide and
  0.25 ft deep: verticals about every 3 ft starting 0.65 ft from each end, horizontals at
  0.5, 4.1 and 8.0 ft. Grooves on one face only, all facing one way, if the user will adjust.

### Two-material section model (wood interior, white exterior) *(printed)*

The recipe that came out of twelve rounds of corrections on a 1:96 half-building:
- 1 ft walls keep their total thickness. Each **interior face** gets a 0.5 ft (1.59 mm)
  wood board taken from inside the wall; the outer 0.5 ft stays white.
- **Interior face test**: a point 0.4 ft in front of the face lies inside the building
  outline (all floors united, holes filled). Do not also require a roof above - the printed
  floors have no roof, and that rule put the wood on the wrong side of whole rooms.
- **Free wall end**: a 1 x 1 ft white end post; the board runs between posts.
- **Partition with rooms on both sides**: board on one face only (two boards made it look
  1 ft thick again), on the more enclosed side: 25 rays over +-80 deg in plan, share hitting
  a wall within 30 ft; ties go south/east. Keep a short list of walls the user flips by hand.
- **Wall that changes from exterior to interior** along its length: the board breaks there.
- **2 ft cabinets**: the grooved front becomes the wood board with the grooves cut into
  it; the back stays white; white end strips only to the first groove (0.65 ft).
- **Narrow tall boards** (up to about 3.5 ft along the wall and 25 mm tall at 1:96) read as
  stray stripes: print them white. Faces narrower than 1 ft get no board.
- **Open top edges** (top floor without a roof): stop the board 1 ft below the open edge so
  a white band covers it; check every 0.1 ft along the top edge.
- **L-shaped boards** (two leaves meeting in a corner) stand upright on the bed and fail:
  cut them at the corner into flat legs `a` and `b`.
- White floors print upside down (slab on the bed, walls up, tenon pockets open upwards);
  a floor with sloped roofs prints upright with tree supports.

### Base (plinth)

`make_base.py`. What was used: building bounding rectangle offset 4 ft on every side,
1 ft thick, corners either cut 1 ft x 1 ft at 45 deg or rounded with a 4 ft radius. A tall
base (12.7 mm at 1:96, 210 x 214 mm) was made hollow: 2 mm walls and top, open bottom,
1.2 mm ribs every 25 mm both ways - no support needed, about 30 % of the solid volume. In
two halves it gets diamond pins; whole if it fits the bed. A site base larger than any bed
(about 450 x 330 mm) was planned as 3 mm board, cut rather than printed.

## 5. Export

- `rhino_export_pieces.py` in Rhino (mesh tolerance 3 mm at full size, about 0.01 ft),
  then `prepare_parts.py PIECES.json --scale 96 --out v01` (or mesh files with `--units ft`).
  Options: `--plate` (pieces side by side, 8 mm apart), `--merge` (one body),
  `--upside-down` (slab on the bed).
- Every part: one closed body, mm, already scaled, lowest point at z = 0, bodies under
  5 mm^3 dropped. `report.json` lists size, volume, bodies, edge contacts.
- STL per plate or part is enough for Bambu Studio; save an editable 3MF per printer if the
  user wants plates ready to open.

## 6. Plates and slicing

Orientation:

| part | on the bed |
|---|---|
| floor with walls and no roof | slab down, walls up |
| floor with sloped roof | upright, tree supports |
| roof panels printed separately | upside down, flat roof plane on the bed (slopes of 45 deg or steeper need no support) |
| thin boards, panels | flat, grooves and relief facing up |
| lift-off roof | outer face down, locating grooves up |
| half-section shell | lying on its back wall |

- `lay_flat_and_pack.py boards.stl --prefix F1- --printer x1c --out plates` numbers parts
  north to south, lays boards flat, packs columns 5 mm apart and draws the map.
- If Bambu Studio says a part is too close to the keep-out corner, press Arrange (A).
- Brim 3 mm, outer only, 6 mm clear between brims when used.

Settings that worked (0.4 nozzle):

| | value |
|---|---|
| layer | 0.20 mm Standard; 0.28 mm Extra Draft to save about 20 % (white bodies 18.3 h -> 14.7 h); 0.12 mm High Quality for small detailed parts. H2S has no 0.28 preset: 0.24 mm Standard with layer height 0.28 |
| walls / infill | 2 walls, 15 % |
| white body (PLA Matte) | tree supports (auto), top Z distance 0.25 mm, support-to-model XY 0.5 mm |
| wood-fill PLA boards | 220 C nozzle, 55 C bed, no supports (other brands: the spool's temperature) |
| hollow ribbed base | no supports |

- Estimate every plate: `bambu_slice_estimate.py plate.stl --machine "Bambu Lab X1 Carbon
  0.4 nozzle" --process "0.20mm Standard @BBL X1C" --filament "Bambu PLA Matte @BBL X1C"
  --set enable_support=1 "support_type=tree(auto)" support_top_z_distance=0.25
  support_object_xy_distance=0.5`. Check: nothing outside the plate, zero mesh repairs.
  "Bed temperature higher than the filament's softening temperature" comes from the stock
  presets, not from the geometry - match the filament to what is loaded.
- Spread plates over printers so they run in parallel; the slowest printer sets the
  finish time. Example *(printed)*: 1:96 half-building, three floors - white floors 2.4-3.3 h
  and 76-97 g each, wood boards on two plates about 2.8 h; three printers in parallel
  5-6.5 h including plate changes.

## 7. After printing

- **Assembly map**: every loose part named `F<floor>-<n>`, numbered north to south, west to
  east, shown on the plan (north up) and on each plate.
- **Test-fit one part** before printing a full set of slide-in parts.
- **Freeze plates once printing starts.** When plates were re-mixed mid-print, the user could
  no longer tell which boards were already printed. Corrections go on a patch plate with a
  "do not use" list for the replaced parts; numbering never changes.
- **Reprint by number**: three boards missing at assembly were one 8-minute patch plate.
  Small patch parts can ride on a plate that is printing anyway (white strips went on the
  base plate).
- **Failed print**: look at the failure height in the sliced preview, fix the geometry
  (necks, pillars, ties) and supports, clean the plate, then print again.

## Working with the user

- If a word allows two geometries ("chamfer" for a rounded corner, "solid"), follow the
  existing model, say which you chose and offer the other.
- Report per printer: file, order, time, grams, orientation. Keep it to what they need to
  press print.
