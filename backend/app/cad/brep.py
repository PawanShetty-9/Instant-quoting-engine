"""STEP / B-Rep analysis with OpenCascade (OCP bindings).

Extracts the ``cad_metadata`` of the engine contract plus DFM diagnostics:

* volume, surface area, tight bounding box (mm, OCCT converts STEP units to mm)
* holes          - concave cylindrical faces grouped by axis & radius (>= 270 deg span)
* threads        - holes whose diameter matches an ISO 261 coarse tap drill (heuristic)
* pockets        - planar floors recessed below the part envelope (closed pockets and
                   open steps/slots), excluding hole bottoms and turned shoulders
* complex curves - connected clusters of free-form (B-spline / Bezier / offset) faces
* turnability    - share of the surface that is coaxial revolution geometry
* access directions / inclined features - drives the 3-axis vs 5-axis decision
"""

from __future__ import annotations

import math
import struct
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import (
    GeomAbs_BezierSurface,
    GeomAbs_BSplineSurface,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_OffsetSurface,
    GeomAbs_OtherSurface,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_SurfaceOfRevolution,
    GeomAbs_Torus,
)
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.IGESControl import IGESControl_Reader
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Shape

ANGLE_TOL = math.radians(1.0)
HOLE_MIN_SPAN = 1.5 * math.pi
ROTATIONAL_THRESHOLD = 0.85
INCLINED_FACE_AREA_SHARE = 0.02

# ISO 261 / DIN 336 coarse-thread tap drill diameters (mm) -> nominal thread.
TAP_DRILLS = {
    1.6: "M2",
    2.05: "M2.5",
    2.5: "M3",
    3.3: "M4",
    4.2: "M5",
    5.0: "M6",
    6.8: "M8",
    8.5: "M10",
    10.2: "M12",
    12.0: "M14",
    14.0: "M16",
    17.5: "M20",
    21.0: "M24",
}
TAP_DRILL_TOL = 0.06

FREEFORM_TYPES = {GeomAbs_BSplineSurface, GeomAbs_BezierSurface, GeomAbs_OffsetSurface, GeomAbs_OtherSurface}
REVOLUTION_TYPES = {GeomAbs_Cylinder, GeomAbs_Cone, GeomAbs_Torus, GeomAbs_SurfaceOfRevolution}
PRINCIPAL = {
    "X": np.array([1.0, 0.0, 0.0]),
    "Y": np.array([0.0, 1.0, 0.0]),
    "Z": np.array([0.0, 0.0, 1.0]),
}


class CadParseError(ValueError):
    """The file could not be interpreted as a manufacturable solid."""


@dataclass
class FaceInfo:
    idx: int
    face: TopoDS_Shape
    kind: int
    area: float
    centroid: np.ndarray
    normal: np.ndarray | None = None  # planes: outward unit normal
    axis_dir: np.ndarray | None = None  # revolution surfaces
    axis_pnt: np.ndarray | None = None
    radius: float | None = None
    concave: bool | None = None
    span: float = 0.0
    axial_range: tuple[float, float] | None = None
    samples: list[np.ndarray] = field(default_factory=list)  # points on the face (from mesh)
    neighbours: set[int] = field(default_factory=set)


def _vec(p) -> np.ndarray:
    return np.array([p.X(), p.Y(), p.Z()], dtype=float)


def _unsigned(d: np.ndarray) -> np.ndarray:
    """Canonical orientation for an undirected axis."""
    for c in d:
        if abs(c) > 1e-9:
            return d if c > 0 else -d
    return d


def _principal_name(d: np.ndarray) -> str | None:
    for name, axis in PRINCIPAL.items():
        if abs(abs(float(np.dot(d, axis))) - 1.0) < 1 - math.cos(ANGLE_TOL):
            return name
    return None


def _signed_dir(d: np.ndarray) -> str | None:
    name = _principal_name(d)
    if name is None:
        return None
    return ("+" if float(np.dot(d, PRINCIPAL[name])) > 0 else "-") + name


def read_step(path: str) -> TopoDS_Shape:
    reader = STEPControl_Reader()
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise CadParseError("STEP file could not be read (not ISO 10303-21 or corrupt)")
    if reader.TransferRoots() == 0:
        raise CadParseError("STEP file contains no transferable geometry")
    shape = reader.OneShape()
    if shape.IsNull():
        raise CadParseError("STEP file contains no geometry")
    return shape


def read_iges(path: str) -> TopoDS_Shape:
    reader = IGESControl_Reader()
    if reader.ReadFile(path) != IFSelect_RetDone:
        raise CadParseError("IGES file could not be read")
    if reader.TransferRoots() == 0:
        raise CadParseError("IGES file contains no transferable geometry")
    shape = reader.OneShape()
    if shape.IsNull():
        raise CadParseError("IGES file contains no geometry")
    return shape


def _solids(shape: TopoDS_Shape) -> list[TopoDS_Shape]:
    solids = []
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        solids.append(exp.Current())
        exp.Next()
    if solids:
        return solids
    # Surface-only exports: try to sew the shells into a closed solid.
    sewing = BRepBuilderAPI_Sewing(1e-3)
    sewing.Add(shape)
    sewing.Perform()
    sewed = sewing.SewedShape()
    exp = TopExp_Explorer(sewed, TopAbs_SHELL)
    while exp.More():
        maker = BRepBuilderAPI_MakeSolid(TopoDS.Shell(exp.Current()))
        if maker.IsDone():
            solids.append(maker.Solid())
        exp.Next()
    return solids


def _compound(shapes: list[TopoDS_Shape]) -> TopoDS_Compound:
    comp = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(comp)
    for s in shapes:
        builder.Add(comp, s)
    return comp


def _face_samples(face, count: int = 3) -> list[np.ndarray]:
    """Centroids of the largest mesh triangles - points guaranteed to lie on the face."""
    loc = TopLoc_Location()
    poly = BRep_Tool.Triangulation_s(face, loc)
    if poly is None or poly.NbTriangles() == 0:
        return []
    trsf = loc.Transformation()
    nodes = np.array([_vec(poly.Node(i).Transformed(trsf)) for i in range(1, poly.NbNodes() + 1)])
    tris = np.array([poly.Triangle(i).Get() for i in range(1, poly.NbTriangles() + 1)], dtype=np.int64) - 1
    a, b, c = nodes[tris[:, 0]], nodes[tris[:, 1]], nodes[tris[:, 2]]
    areas = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    order = np.argsort(-areas)[:count]
    return [(a[i] + b[i] + c[i]) / 3.0 for i in order]


def _face_infos(shape: TopoDS_Shape) -> list[FaceInfo]:
    infos: list[FaceInfo] = []
    edge_faces: dict[int, list[int]] = defaultdict(list)
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face(exp.Current())
        idx = len(infos)
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        adaptor = BRepAdaptor_Surface(face)
        kind = adaptor.GetType()
        info = FaceInfo(idx=idx, face=face, kind=kind, area=props.Mass(), centroid=_vec(props.CentreOfMass()))
        info.samples = _face_samples(face)

        umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)
        pnt, nrm = gp_Pnt(), gp_Vec()
        BRepGProp_Face(face).Normal((umin + umax) / 2, (vmin + vmax) / 2, pnt, nrm)
        p = _vec(pnt)
        n = _vec(nrm)
        n_len = np.linalg.norm(n)
        n = n / n_len if n_len > 1e-12 else n

        if kind == GeomAbs_Plane:
            info.normal = n
        elif kind in REVOLUTION_TYPES:
            if kind == GeomAbs_Cylinder:
                geom = adaptor.Cylinder()
                ax = geom.Axis()
                info.radius = geom.Radius()
            elif kind == GeomAbs_Cone:
                ax = adaptor.Cone().Axis()
            elif kind == GeomAbs_Torus:
                ax = adaptor.Torus().Axis()
            else:
                ax = adaptor.AxeOfRevolution()
            info.axis_dir = _vec(ax.Direction())
            info.axis_dir /= np.linalg.norm(info.axis_dir)
            info.axis_pnt = _vec(ax.Location())
            radial = p - info.axis_pnt
            radial -= np.dot(radial, info.axis_dir) * info.axis_dir
            info.concave = bool(np.dot(n, radial) < 0)
            info.span = abs(umax - umin)
            # Axial extent from the face vertices (robust against surface parametrisation).
            projections = []
            vexp = TopExp_Explorer(face, TopAbs_VERTEX)
            while vexp.More():
                vp = _vec(BRep_Tool.Pnt_s(TopoDS.Vertex(vexp.Current())))
                projections.append(float(np.dot(vp - info.axis_pnt, info.axis_dir)))
                vexp.Next()
            if projections:
                info.axial_range = (min(projections), max(projections))
        elif kind == GeomAbs_Sphere:
            info.axis_pnt = _vec(adaptor.Sphere().Location())
        infos.append(info)

        eexp = TopExp_Explorer(face, TopAbs_EDGE)
        while eexp.More():
            edge_faces[hash(eexp.Current())].append(idx)
            eexp.Next()
        exp.Next()

    for faces in edge_faces.values():
        uniq = set(faces)
        for a in uniq:
            infos[a].neighbours |= uniq - {a}
    return infos


def _same_axis(d1, p1, d2, p2, tol: float) -> bool:
    if abs(abs(float(np.dot(d1, d2))) - 1.0) > 1 - math.cos(ANGLE_TOL):
        return False
    delta = p2 - p1
    off = delta - np.dot(delta, d1) * d1
    return float(np.linalg.norm(off)) <= tol


def _mesh(shape: TopoDS_Shape, diag: float, max_triangles: int) -> tuple[np.ndarray, np.ndarray]:
    """Tessellate for preview + envelope measurements. Returns (vertices[n,3], tris[m,3])."""
    deflection = max(diag * 0.0015, 0.01)
    for _ in range(4):
        BRepMesh_IncrementalMesh(shape, deflection, False, 0.4, True)
        verts: list[np.ndarray] = []
        tris: list[np.ndarray] = []
        offset = 0
        exp = TopExp_Explorer(shape, TopAbs_FACE)
        while exp.More():
            face = TopoDS.Face(exp.Current())
            loc = TopLoc_Location()
            poly = BRep_Tool.Triangulation_s(face, loc)
            if poly is not None:
                trsf = loc.Transformation()
                nodes = np.array([_vec(poly.Node(i).Transformed(trsf)) for i in range(1, poly.NbNodes() + 1)])
                t = np.array([poly.Triangle(i).Get() for i in range(1, poly.NbTriangles() + 1)], dtype=np.int64) - 1
                if face.Orientation() == TopAbs_REVERSED:
                    t = t[:, [0, 2, 1]]
                verts.append(nodes)
                tris.append(t + offset)
                offset += len(nodes)
            exp.Next()
        if not verts:
            raise CadParseError("geometry could not be tessellated")
        v = np.vstack(verts)
        f = np.vstack(tris)
        if len(f) <= max_triangles:
            return v, f
        deflection *= 3.0
        BRepTools.Clean_s(shape)
    return v, f


def stl_bytes(vertices: np.ndarray, tris: np.ndarray) -> bytes:
    a, b, c = vertices[tris[:, 0]], vertices[tris[:, 1]], vertices[tris[:, 2]]
    normals = np.cross(b - a, c - a)
    lens = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lens, out=np.zeros_like(normals), where=lens > 0)
    rec = np.zeros(
        len(tris), dtype=[("n", "<f4", 3), ("a", "<f4", 3), ("b", "<f4", 3), ("c", "<f4", 3), ("attr", "<u2")]
    )
    rec["n"], rec["a"], rec["b"], rec["c"] = normals, a, b, c
    header = b"instant-quoting-engine preview".ljust(80, b" ")
    return header + struct.pack("<I", len(tris)) + rec.tobytes()


def analyse_shape(shape: TopoDS_Shape, max_triangles: int = 150_000) -> dict:
    solids = _solids(shape)
    if not solids:
        raise CadParseError("no closed solid found - export the part as a solid body (not surfaces)")
    body = _compound(solids)

    vprops = GProp_GProps()
    BRepGProp.VolumeProperties_s(body, vprops)
    volume_mm3 = abs(vprops.Mass())
    sprops = GProp_GProps()
    BRepGProp.SurfaceProperties_s(body, sprops)
    area_mm2 = sprops.Mass()
    if volume_mm3 < 1e-3 or area_mm2 < 1e-3:
        raise CadParseError("solid has zero volume")

    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(body, box, False, False)
    lo, hi = _vec(box.CornerMin()), _vec(box.CornerMax())
    dims = hi - lo
    diag = float(np.linalg.norm(dims))
    tol = max(diag * 1e-4, 1e-3)

    vertices, tris = _mesh(body, diag, max_triangles)
    warnings: list[str] = []
    brep_valid = bool(BRepCheck_Analyzer(body).IsValid())
    if not brep_valid:
        warnings.append("B-Rep check reported topology defects; volume may be inaccurate")
    if len(solids) > 1:
        warnings.append(f"file contains {len(solids)} solids - quoted as one multi-body part")

    faces = _face_infos(body)
    total_area = sum(f.area for f in faces) or 1.0

    # ---------------------------------------------------------------- turnability
    axis_groups: list[dict] = []
    for f in faces:
        if f.kind in REVOLUTION_TYPES and f.axis_dir is not None:
            for g in axis_groups:
                if _same_axis(g["dir"], g["pnt"], f.axis_dir, f.axis_pnt, tol * 10):
                    g["area"] += f.area
                    break
            else:
                axis_groups.append({"dir": _unsigned(f.axis_dir), "pnt": f.axis_pnt, "area": f.area})
    rot_axis = max(axis_groups, key=lambda g: g["area"]) if axis_groups else None

    def on_rot_axis(f: FaceInfo) -> bool:
        if rot_axis is None:
            return False
        d, p = rot_axis["dir"], rot_axis["pnt"]
        if f.kind in REVOLUTION_TYPES and f.axis_dir is not None:
            return _same_axis(d, p, f.axis_dir, f.axis_pnt, tol * 10)
        if f.kind == GeomAbs_Sphere and f.axis_pnt is not None:
            off = f.axis_pnt - p
            return float(np.linalg.norm(off - np.dot(off, d) * d)) <= tol * 10
        if f.kind == GeomAbs_Plane and f.normal is not None:
            if abs(abs(float(np.dot(f.normal, d))) - 1.0) > 1 - math.cos(ANGLE_TOL):
                return False
            off = f.centroid - p
            return float(np.linalg.norm(off - np.dot(off, d) * d)) <= tol * 10
        return False

    rot_area = sum(f.area for f in faces if on_rot_axis(f))
    rotational_fraction = rot_area / total_area if rot_axis else 0.0
    is_rotational = rotational_fraction >= ROTATIONAL_THRESHOLD
    turning_diameter = turning_length = None
    rotational_axis_name = None
    if rot_axis is not None:
        d, p = rot_axis["dir"], rot_axis["pnt"]
        rel = vertices - p
        axial = rel @ d
        radial = np.linalg.norm(rel - np.outer(axial, d), axis=1)
        turning_diameter = float(2 * radial.max())
        turning_length = float(axial.max() - axial.min())
        rotational_axis_name = _principal_name(d)

    # ---------------------------------------------------------------------- holes
    hole_groups: list[dict] = []
    internal_radii: list[float] = []
    for f in faces:
        if f.kind != GeomAbs_Cylinder or not f.concave:
            continue
        for g in hole_groups:
            if abs(g["radius"] - f.radius) <= tol and _same_axis(g["dir"], g["pnt"], f.axis_dir, f.axis_pnt, tol):
                g["faces"].append(f)
                break
        else:
            hole_groups.append({"radius": f.radius, "dir": _unsigned(f.axis_dir), "pnt": f.axis_pnt, "faces": [f]})

    holes: list[dict] = []
    hole_face_ids: set[int] = set()
    for g in hole_groups:
        span = sum(f.span for f in g["faces"])
        if span < HOLE_MIN_SPAN:
            internal_radii.append(g["radius"])
            continue
        ids = {f.idx for f in g["faces"]}
        hole_face_ids |= ids
        lo_ax = min((f.axial_range[0] for f in g["faces"] if f.axial_range), default=0.0)
        hi_ax = max((f.axial_range[1] for f in g["faces"] if f.axial_range), default=0.0)
        # Which side is open? Planar/conical caps perpendicular to the axis have their
        # outward normal pointing towards the opening; caps on both sides = through hole.
        signs = set()
        for f in g["faces"]:
            for nb in f.neighbours:
                nf = faces[nb]
                cap_normal = None
                if nf.kind == GeomAbs_Plane and nf.normal is not None:
                    if abs(abs(float(np.dot(nf.normal, g["dir"]))) - 1.0) < 1 - math.cos(ANGLE_TOL):
                        cap_normal = nf.normal
                elif nf.kind == GeomAbs_Cone and nf.axis_dir is not None:
                    pnt, nrm = gp_Pnt(), gp_Vec()
                    umin, umax, vmin, vmax = BRepTools.UVBounds_s(TopoDS.Face(nf.face))
                    BRepGProp_Face(TopoDS.Face(nf.face)).Normal((umin + umax) / 2, (vmin + vmax) / 2, pnt, nrm)
                    cap_normal = _vec(nrm)
                if cap_normal is not None:
                    s = float(np.dot(cap_normal, g["dir"]))
                    if abs(s) > 1e-6:
                        signs.add(1 if s > 0 else -1)
        through = len(signs) != 1
        diameter = 2 * g["radius"]
        holes.append(
            {
                "diameter": diameter,
                "depth": max(hi_ax - lo_ax, 0.0),
                "dir": g["dir"],
                "sign": None if through else signs.pop(),
                "coaxial": is_rotational
                and rot_axis is not None
                and _same_axis(rot_axis["dir"], rot_axis["pnt"], g["dir"], g["pnt"], tol * 10),
                "thread": next((m for td, m in TAP_DRILLS.items() if abs(diameter - td) <= TAP_DRILL_TOL), None),
            }
        )

    # ------------------------------------------------- pockets / steps (planar floors)
    extents: dict[str, float] = {}

    def extent(signed: str, direction: np.ndarray) -> float:
        if signed not in extents:
            extents[signed] = float((vertices @ direction).max())
        return extents[signed]

    ray = IntCurvesFace_ShapeIntersector()
    ray.Load(body, tol)

    def open_towards(f: FaceInfo) -> bool:
        """True if a ray leaving the face along its normal escapes the part (tool access)."""
        for pt in f.samples or [f.centroid]:
            ray.Perform(gp_Lin(gp_Pnt(*pt), gp_Dir(*f.normal)), max(tol * 10, 0.01), 1e7)
            if ray.IsDone() and ray.NbPnt() == 0:
                return True
        return False

    candidates: list[tuple[FaceInfo, str]] = []
    inclined = 0
    for f in faces:
        if f.kind != GeomAbs_Plane or f.normal is None or f.idx in hole_face_ids:
            continue
        if is_rotational and on_rot_axis(f):
            continue  # turned shoulders / end faces
        if f.neighbours and all(nb in hole_face_ids or faces[nb].kind == GeomAbs_Cone for nb in f.neighbours):
            continue  # flat hole bottom or counterbore step
        signed = _signed_dir(f.normal)
        if signed is None:
            if f.area / total_area >= INCLINED_FACE_AREA_SHARE and open_towards(f):
                inclined += 1
            continue  # small chamfers are machined with a chamfer mill
        plane_pos = float(np.dot(f.centroid, f.normal))
        if plane_pos >= extent(signed, f.normal) - max(tol * 10, 0.01):
            continue  # outer stock face
        if not open_towards(f):
            continue  # pocket wall facing material: cut with the tool flank
        candidates.append((f, signed))

    # Two perpendicular open faces sharing an edge (step floor + step wall): the larger
    # face is the floor that defines the access direction, the smaller one is its wall.
    walls: set[int] = set()
    by_idx = {f.idx: (f, d) for f, d in candidates}
    for f, d in candidates:
        for nb in f.neighbours:
            if nb in by_idx:
                g, e = by_idx[nb]
                if d[1] != e[1] and (g.area, g.idx) > (f.area, f.idx):
                    walls.add(f.idx)
    floors: list[dict] = []
    for f, signed in candidates:
        if f.idx in walls:
            continue
        axis_i = "XYZ".index(signed[1])
        fbox = Bnd_Box()
        BRepBndLib.Add_s(f.face, fbox, False)
        flo, fhi = _vec(fbox.CornerMin()), _vec(fbox.CornerMax())
        open_side = any(flo[i] <= lo[i] + tol * 10 or fhi[i] >= hi[i] - tol * 10 for i in range(3) if i != axis_i)
        floors.append({"dir": signed, "open": open_side})

    # ------------------------------------------------------------ free-form surfaces
    freeform_ids = {f.idx for f in faces if f.kind in FREEFORM_TYPES}
    clusters = 0
    seen: set[int] = set()
    for start in freeform_ids:
        if start in seen:
            continue
        clusters += 1
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(nb for nb in faces[cur].neighbours if nb in freeform_ids and nb not in seen)
    freeform_area = sum(faces[i].area for i in freeform_ids)

    # ------------------------------------------------------------ access directions
    directions: set[str] = {fl["dir"] for fl in floors}
    for h in holes:
        if h["coaxial"]:
            continue  # bored/drilled on the lathe spindle axis
        axis_name = _principal_name(h["dir"])
        if axis_name is None:
            inclined += 1
            continue
        if h["sign"] is None:  # through hole: reuse an existing side if possible
            if f"+{axis_name}" in directions or f"-{axis_name}" in directions:
                continue
            directions.add(f"+{axis_name}")
        else:
            directions.add(("+" if h["sign"] > 0 else "-") + axis_name)

    min_hole = min((h["diameter"] for h in holes), default=None)
    ld = max((h["depth"] / h["diameter"] for h in holes if h["diameter"] > 0), default=None)
    closed_pockets = sum(1 for fl in floors if not fl["open"])

    return {
        "format": "STEP",
        "bounding_box": [round(float(d), 3) for d in dims],
        "volume_cm3": round(volume_mm3 / 1000.0, 4),
        "surface_area_cm2": round(area_mm2 / 100.0, 4),
        "features": {
            "holes": len(holes),
            "threads": sum(1 for h in holes if h["thread"]),
            "pockets": len(floors),
            "complex_curves": clusters,
        },
        "diagnostics": {
            "source_format": "STEP",
            "solid_count": len(solids),
            "face_count": len(faces),
            "brep_valid": brep_valid,
            "is_rotational": is_rotational,
            "rotational_axis": rotational_axis_name if is_rotational else None,
            "rotational_fraction": round(rotational_fraction, 4),
            "turning_diameter_mm": round(turning_diameter, 3) if is_rotational and turning_diameter else None,
            "turning_length_mm": round(turning_length, 3) if is_rotational and turning_length else None,
            "access_directions": sorted(directions),
            "inclined_features": inclined,
            "min_hole_diameter_mm": round(min_hole, 3) if min_hole else None,
            "max_hole_depth_to_diameter": round(ld, 2) if ld else None,
            "min_internal_radius_mm": round(min(internal_radii), 3) if internal_radii else None,
            "freeform_area_fraction": round(freeform_area / total_area, 4),
            "closed_pockets": closed_pockets,
            "open_steps": len(floors) - closed_pockets,
            "thread_detection": "tap_drill_heuristic",
            "warnings": warnings,
        },
        "preview_stl": stl_bytes(vertices, tris),
    }


def analyse_step_file(path: str, max_triangles: int = 150_000) -> dict:
    return analyse_shape(read_step(path), max_triangles=max_triangles)


def analyse_iges_file(path: str, max_triangles: int = 150_000) -> dict:
    result = analyse_shape(read_iges(path), max_triangles=max_triangles)
    result["format"] = result["diagnostics"]["source_format"] = "IGES"
    result["diagnostics"]["warnings"].append("IGES input: prefer STEP AP214/AP242 for reliable solids")
    return result
