"""Generate reference STEP parts used by the tests, the demo UI and the docs.

    python -m scripts.generate_samples ../samples

Each part exercises one branch of the machine-selection rules:

* bracket.step   - prismatic, all features from +Z            -> CNC_3_Axis
* shaft.step     - stepped turned shaft with centre bore        -> Lathe
* manifold.step  - hydraulic block, bores from 4 sides          -> CNC_5_Axis (multi-sided)
* blade.step     - lofted free-form turbine blade on a root     -> CNC_5_Axis (complex curves)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Transform
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder
from OCP.GC import GC_MakeEllipse
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.Interface import Interface_Static
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape


def _cut(a: TopoDS_Shape, b: TopoDS_Shape) -> TopoDS_Shape:
    return BRepAlgoAPI_Cut(a, b).Shape()


def _fuse(a: TopoDS_Shape, b: TopoDS_Shape) -> TopoDS_Shape:
    return BRepAlgoAPI_Fuse(a, b).Shape()


def _drill(
    p: tuple[float, float, float], d: tuple[float, float, float], dia: float, depth: float, point: bool = True
) -> TopoDS_Shape:
    """Drill body starting at p going along d (twist-drill 118 deg point for blind holes)."""
    direction = gp_Dir(*d)
    body = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*p), direction), dia / 2, depth).Shape()
    if point:
        tip_len = (dia / 2) / math.tan(math.radians(59))
        tip_start = gp_Pnt(p[0] + d[0] * depth, p[1] + d[1] * depth, p[2] + d[2] * depth)
        tip = BRepPrimAPI_MakeCone(gp_Ax2(tip_start, direction), dia / 2, 0.0, tip_len).Shape()
        body = _fuse(body, tip)
    return body


def _translated(shape: TopoDS_Shape, v: tuple[float, float, float]) -> TopoDS_Shape:
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(*v))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def bracket() -> TopoDS_Shape:
    part = BRepPrimAPI_MakeBox(120.0, 80.0, 25.0).Shape()
    # Closed pocket 60 x 30 x 10 with R5 corners.
    pocket = BRepPrimAPI_MakeBox(gp_Pnt(30, 25, 15), 60.0, 30.0, 10.01).Shape()
    fillet = BRepFilletAPI_MakeFillet(pocket)
    exp = TopExp_Explorer(pocket, TopAbs_EDGE)
    while exp.More():
        edge = TopoDS.Edge(exp.Current())
        from OCP.BRepAdaptor import BRepAdaptor_Curve

        c = BRepAdaptor_Curve(edge)
        a, b = c.Value(c.FirstParameter()), c.Value(c.LastParameter())
        if abs(a.X() - b.X()) < 1e-6 and abs(a.Y() - b.Y()) < 1e-6:  # vertical edge
            fillet.Add(5.0, edge)
        exp.Next()
    part = _cut(part, fillet.Shape())
    # Open step along the front edge: 120 x 15 x 8.
    part = _cut(part, BRepPrimAPI_MakeBox(gp_Pnt(-1, -1, 17), 122.0, 16.0, 9.0).Shape())
    # 4 x through holes 6.6 mm (M6 clearance, DIN EN 20273 medium).
    for x, y in ((10, 70), (110, 70), (10, 25), (110, 25)):
        part = _cut(part, _drill((x, y, -1), (0, 0, 1), 6.6, 27.0, point=False))
    # 2 x M8 tapped blind holes (tap drill 6.8, depth 16) on the top face.
    for x in (45, 75):
        part = _cut(part, _drill((x, 67.5, 25.001), (0, 0, -1), 6.8, 16.0))
    return part


def shaft() -> TopoDS_Shape:
    ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0))
    part = BRepPrimAPI_MakeCylinder(ax, 20.0, 30.0).Shape()
    part = _fuse(part, BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(30, 0, 0), gp_Dir(1, 0, 0)), 15.0, 60.0).Shape())
    part = _fuse(part, BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(90, 0, 0), gp_Dir(1, 0, 0)), 10.0, 40.0).Shape())
    # 45 deg chamfer on the small end, modelled as a cone.
    chamfer_tool = _cut(
        BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(128, 0, 0), gp_Dir(1, 0, 0)), 12.0, 3.0).Shape(),
        BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(128, 0, 0), gp_Dir(1, 0, 0)), 10.0, 8.0, 2.0).Shape(),
    )
    part = _cut(part, chamfer_tool)
    # Centre bore 10 mm x 20 mm deep from the large end.
    part = _cut(part, _drill((-0.001, 0, 0), (1, 0, 0), 10.0, 20.0))
    return part


def manifold() -> TopoDS_Shape:
    part = BRepPrimAPI_MakeBox(80.0, 80.0, 80.0).Shape()
    part = _cut(part, _drill((40, 40, 80.001), (0, 0, -1), 16.0, 50.0))  # +Z main bore
    part = _cut(part, _drill((80.001, 40, 40), (-1, 0, 0), 10.0, 45.0))  # +X port
    part = _cut(part, _drill((-0.001, 40, 55), (1, 0, 0), 8.0, 30.0))  # -X port
    part = _cut(part, _drill((40, 80.001, 30), (0, -1, 0), 8.0, 45.0))  # +Y port
    for x, y in ((10, 10), (70, 10), (10, 70), (70, 70)):  # M6 mounting threads, top
        part = _cut(part, _drill((x, y, 80.001), (0, 0, -1), 5.0, 12.0))
    return part


def blade() -> TopoDS_Shape:
    loft = BRepOffsetAPI_ThruSections(True, False)
    for i, z in enumerate((20.0, 60.0, 100.0)):
        major, minor = 30.0 - 6 * i, 6.0 - 1.5 * i
        angle = math.radians(20 * i)
        ax = gp_Ax2(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1), gp_Dir(math.cos(angle), math.sin(angle), 0))
        edge = BRepBuilderAPI_MakeEdge(GC_MakeEllipse(ax, major, minor).Value()).Edge()
        loft.AddWire(BRepBuilderAPI_MakeWire(edge).Wire())
    loft.Build()
    root = BRepPrimAPI_MakeBox(gp_Pnt(-40, -20, 0), 80.0, 40.0, 20.001).Shape()
    part = _fuse(root, loft.Shape())
    rot = gp_Trsf()
    rot.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 0.0)
    return _translated(part, (40, 20, 0))


PARTS = {"bracket": bracket, "shaft": shaft, "manifold": manifold, "blade": blade}


def write_step(shape: TopoDS_Shape, path: Path) -> None:
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    Interface_Static.SetCVal_s("write.step.product.name", path.stem)
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    if writer.Write(str(path)) != 1:
        raise RuntimeError(f"failed to write {path}")


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, build in PARTS.items():
        write_step(build(), out / f"{name}.step")
        print(f"wrote {out / name}.step")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "samples")
