"""Slice an STL/3MF with the Bambu Studio command line to get print time and filament weight,
using Bambu's own system presets. Nothing is sent to a printer.

Bambu Studio's CLI does not resolve preset inheritance by name, so this flattens the
machine / process / filament presets ("inherits" chain) into plain JSON first, applies
your overrides, slices, and reads time and weight from the G-code header.

usage:
  python bambu_slice_estimate.py plate.stl --out slice_x1c \
      --machine "Bambu Lab X1 Carbon 0.4 nozzle" --process "0.20mm Standard @BBL X1C" \
      --filament "Bambu PLA Matte @BBL X1C" \
      --set enable_support=1 "support_type=tree(auto)" support_top_z_distance=0.25 support_object_xy_distance=0.5

  # list preset names
  python bambu_slice_estimate.py --list X1C

Default locations (override with --bambu / --system):
  Windows: %ProgramFiles%\\Bambu Studio\\bambu-studio.exe, %APPDATA%\\BambuStudio\\system\\BBL
  macOS:   /Applications/BambuStudio.app/Contents/MacOS/BambuStudio,
           ~/Library/Application Support/BambuStudio/system/BBL

needs: Bambu Studio installed (tested with 2.05); Python standard library only
"""
import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path


def default_paths():
    if sys.platform.startswith("win"):
        exe = Path(os.environ.get("ProgramFiles", "")) / "Bambu Studio" / "bambu-studio.exe"
        system = Path(os.environ.get("APPDATA", "")) / "BambuStudio" / "system" / "BBL"
    elif sys.platform == "darwin":
        exe = Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio")
        system = Path.home() / "Library" / "Application Support" / "BambuStudio" / "system" / "BBL"
    else:
        exe = Path("bambu-studio")
        system = Path.home() / ".config" / "BambuStudio" / "system" / "BBL"
    return exe, system


def load(system, kind, name):
    f = system / kind / ("%s.json" % name)
    if not f.is_file():
        raise SystemExit("no %s preset named %r in %s (try --list)" % (kind, name, system / kind))
    data = json.loads(f.read_text(encoding="utf-8"))
    if data.get("inherits"):
        base = load(system, kind, data["inherits"])
        base.update(data)
        data = base
    return data


def header_value(code, label):
    m = re.search(r";\s*%s\s*[:=]\s*([^;\n]+)" % re.escape(label), code)
    return m.group(1).strip() if m else None


def main():
    exe0, sys0 = default_paths()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model", nargs="?")
    ap.add_argument("--out", default="slice_out")
    ap.add_argument("--machine")
    ap.add_argument("--process")
    ap.add_argument("--filament")
    ap.add_argument("--set", nargs="*", default=[], help="process overrides key=value")
    ap.add_argument("--arrange", default="1", help="1 = let Bambu place the parts clear of keep-out areas (default)")
    ap.add_argument("--bambu", default=str(exe0))
    ap.add_argument("--system", default=str(sys0))
    ap.add_argument("--list", metavar="FILTER", help="print preset names containing FILTER and stop")
    a = ap.parse_args()
    system = Path(a.system)

    if a.list is not None:
        for kind in ("machine", "process", "filament"):
            names = sorted(p.stem for p in (system / kind).glob("*.json") if a.list.lower() in p.stem.lower())
            print("[%s]" % kind)
            for n in names:
                print("  " + n)
        return
    if not (a.model and a.machine and a.process and a.filament):
        ap.error("model, --machine, --process and --filament are needed")

    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for kind, name in (("machine", a.machine), ("process", a.process), ("filament", a.filament)):
        d = load(system, kind, name)
        d.pop("inherits", None)
        d["from"] = "system"
        if kind == "process":
            for kv in a.set:
                k, v = kv.split("=", 1)
                d[k] = v
        files[kind] = out / ("%s.json" % kind)
        files[kind].write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

    sliced = Path(a.model).stem + ".gcode.3mf"
    cmd = [a.bambu, "--slice", "0", "--arrange", a.arrange, "--orient", "0",
           "--load-settings", "%s;%s" % (files["machine"], files["process"]),
           "--load-filaments", str(files["filament"]),
           "--outputdir", str(out), "--export-3mf", sliced, str(Path(a.model).resolve())]
    kw = dict(capture_output=True, timeout=1800)
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x08000000             # no console window
    run = subprocess.run(cmd, **kw)
    log = (run.stdout + run.stderr).decode("utf-8", errors="replace")
    (out / "slicing_log.txt").write_text(log, encoding="utf-8")
    if run.returncode != 0 or not (out / sliced).is_file():
        raise SystemExit("slicing failed (exit %s); see %s" % (run.returncode, out / "slicing_log.txt"))

    result = dict(model=str(a.model), machine=a.machine, process=a.process, filament=a.filament, overrides=a.set,
                  plates=[])
    with zipfile.ZipFile(out / sliced) as z:
        for g in sorted(n for n in z.namelist() if n.endswith(".gcode")):
            code = z.read(g).decode("utf-8", errors="replace")[:20000]
            result["plates"].append(dict(
                gcode=g, print_time=header_value(code, "model printing time"),
                total_time=header_value(code, "total estimated time"),
                filament_g=header_value(code, "total filament weight [g]"),
                layers=header_value(code, "total layer number")))
        if "Metadata/slice_info.config" in z.namelist():
            info = z.read("Metadata/slice_info.config").decode("utf-8", errors="replace")
            result["outside_plate"] = "true" in re.findall(r'key="outside" value="(\w+)"', info)
            result["warnings"] = sorted(set(re.findall(r'<warning[^>]*msg="([^"]+)"', info)))
    result["sliced_file"] = str(out / sliced)
    (out / "estimate.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
