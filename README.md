# Architectural model 3D printing - a Claude Code skill

[中文说明在下面](#中文)

A [Claude Code](https://claude.com/claude-code) skill for turning an architectural CAD model
into FDM print files for a physical model: scale and unit conversion, wall-thickness and
thin-part checks, splitting by floor / bed / material, tenons, pins and clearances, bases,
export, plate layout, slicing estimates, and what to do after printing.

It was distilled from about a month of study, massing and section models for a housing
studio project (1:64 to 1:300, Rhino in feet, Bambu Lab X1C / A1 / H2S, PLA): the numbers in
it are the ones that survived printing and the corrections that came with each version.

## What's inside

```
skills/architectural-model-3d-printing/
  SKILL.md            the skill (English) - what Claude reads
  SKILL.zh-CN.md      the same in Chinese
  requirements.txt
  scripts/
    rhino_export_pieces.py   run inside Rhino 7/8: visible objects -> pieces JSON
    prepare_parts.py         union, fill voids, scale to mm, z = 0, report
    check_print.py           closed solid, bed fit, thin walls/necks, islands, overhang
    lay_flat_and_pack.py     number parts, lay boards flat, pack plates, map
    make_base.py             plinth: offset, corners, hollow + ribs, split + pins
    bambu_slice_estimate.py  Bambu Studio CLI -> time, grams, warnings
    printkit.py              shared helpers
examples/
  make_example.py            writes a tiny made-up model to try the scripts on
  tiny_house_pieces_ft.json
```

## Install

Copy the skill folder into your personal skills (all projects) or one project's skills:

```bash
git clone <this repo>
# all projects
cp -r architectural-model-3d-printing-skill/skills/architectural-model-3d-printing ~/.claude/skills/
# or only one project
cp -r architectural-model-3d-printing-skill/skills/architectural-model-3d-printing <your project>/.claude/skills/
```

Windows PowerShell:

```powershell
Copy-Item -Recurse .\skills\architectural-model-3d-printing "$HOME\.claude\skills\"
```

The scripts need Python 3.9+ and `pip install -r requirements.txt` (numpy, trimesh,
manifold3d, shapely, matplotlib). `rhino_export_pieces.py` runs inside Rhino;
`bambu_slice_estimate.py` needs Bambu Studio installed.

## Use

In Claude Code, just ask, for example:

> My Rhino model `house.3dm` is in feet. Make 1/8" = 1'-0" print files for an X1C,
> one plate per floor, and tell me how long each plate takes.

Claude picks up the skill from the request (or type `/architectural-model-3d-printing`).

Try the scripts without Rhino, from the repository root:

```bash
S=skills/architectural-model-3d-printing/scripts
python examples/make_example.py
python $S/prepare_parts.py examples/tiny_house_pieces_ft.json --scale 96 --out demo --plate
python $S/check_print.py demo/upper_1-96_mm.stl --printer x1c        # flags the 3 in fin as too thin
python $S/lay_flat_and_pack.py demo/boards_1-96_mm.stl --prefix F1- --printer x1c --out demo/plates
python $S/make_base.py --footprint demo/ground_1-96_mm.stl --offset 12.7 --height 12.7 \
    --corner-radius 12.7 --hollow --split --out demo/base
# with Bambu Studio installed:
python $S/bambu_slice_estimate.py demo/plates/F1-plate1_mm.stl --out demo/slice \
    --machine "Bambu Lab X1 Carbon 0.4 nozzle" --process "0.20mm Standard @BBL X1C" \
    --filament "Bambu PLA Matte @BBL X1C"
```

`prepare_parts.py` also reports the one place where two walls of the example touch only
along an edge, and `lay_flat_and_pack.py` lists the L-shaped board that cannot lie flat.

## License

MIT, see [LICENSE](LICENSE).

---

## 中文

一个 [Claude Code](https://claude.com/claude-code) skill：把建筑 CAD 模型变成 FDM 打印文件，做实体模型。包括比例和单位换算、墙厚和细小部件检查、按楼层/热床/材料拆件、榫、销和间隙、底座、导出、排盘、切片估时，以及打完以后怎么办。

内容来自一个住宅设计课项目里约一个月的研究模型、体块模型和剖面模型（1:64 到 1:300，Rhino 用英尺，拓竹 X1C / A1 / H2S，PLA）：里面的数字是实际打印留下来的，以及每一版改过的问题。

### 里面有什么

- `skills/architectural-model-3d-printing/SKILL.md`：skill 本体（英文），Claude 读这个；
- `SKILL.zh-CN.md`：同样内容的中文版；
- `scripts/`：上面列的 6 个脚本加一个公用模块；
- `examples/`：生成一个很小的虚构模型，用来试脚本。

### 安装

把 skill 文件夹复制到个人 skills 目录（所有项目可用）或某个项目的 skills 目录：

```bash
git clone <本仓库>
# 所有项目
cp -r architectural-model-3d-printing-skill/skills/architectural-model-3d-printing ~/.claude/skills/
# 只给一个项目
cp -r architectural-model-3d-printing-skill/skills/architectural-model-3d-printing <你的项目>/.claude/skills/
```

Windows PowerShell：

```powershell
Copy-Item -Recurse .\skills\architectural-model-3d-printing "$HOME\.claude\skills\"
```

脚本要 Python 3.9 以上，`pip install -r requirements.txt`（numpy、trimesh、manifold3d、shapely、matplotlib）。`rhino_export_pieces.py` 在 Rhino 里运行；`bambu_slice_estimate.py` 要装 Bambu Studio。

### 用法

在 Claude Code 里直接说，比如：

> 我的 Rhino 模型 `house.3dm` 单位是英尺，帮我出 1/8" = 1'-0" 的打印文件，用 X1C，每层一盘，告诉我每盘要打多久。

Claude 会按请求自动用上这个 skill（也可以输入 `/architectural-model-3d-printing`）。

不装 Rhino 也能试，在仓库根目录运行上面英文部分那几行命令：先生成示例模型，再准备、检查、排盘、做底座、估时。`check_print.py` 会指出示例里 3 in 的薄片太薄，`prepare_parts.py` 会报出两道墙只沿一条棱接触的地方，`lay_flat_and_pack.py` 会列出放不平的 L 形板。

### 许可

MIT，见 [LICENSE](LICENSE)。
