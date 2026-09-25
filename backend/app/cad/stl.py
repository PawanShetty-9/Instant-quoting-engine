"""STL (mesh) fallback parser.

Meshes carry no feature semantics, so only volume, area and bounding box are
extracted and the quote is always routed to manual review.
"""

from __future__ import annotations

import re
import struct

import numpy as np

from app.cad.brep import CadParseError, stl_bytes

_FLOAT = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_VERTEX_RE = re.compile(rf"vertex\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})")


def _load_triangles(data: bytes) -> np.ndarray:
    if len(data) >= 84:
        (count,) = struct.unpack_from("<I", data, 80)
        if len(data) == 84 + 50 * count and count > 0:
            rec = np.frombuffer(
                data,
                offset=84,
                count=count,
                dtype=[("n", "<f4", 3), ("a", "<f4", 3), ("b", "<f4", 3), ("c", "<f4", 3), ("attr", "<u2")],
            )
            return np.stack([rec["a"], rec["b"], rec["c"]], axis=1).astype(np.float64)
    head = data[:512].lstrip().lower()
    if head.startswith(b"solid"):
        text = data.decode("ascii", errors="replace")
        coords = np.array(_VERTEX_RE.findall(text), dtype=np.float64)
        if len(coords) and len(coords) % 3 == 0:
            return coords.reshape(-1, 3, 3)
    raise CadParseError("file is neither a valid binary nor ASCII STL")


def analyse_stl_bytes(data: bytes, unit_scale: float = 1.0, max_triangles: int = 150_000) -> dict:
    tris = _load_triangles(data) * unit_scale
    if not np.isfinite(tris).all():
        raise CadParseError("STL contains non-finite coordinates")
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    cross = np.cross(b - a, c - a)
    area_mm2 = float(0.5 * np.linalg.norm(cross, axis=1).sum())
    volume_mm3 = float(abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)
    if volume_mm3 < 1e-3:
        raise CadParseError("mesh encloses no volume")

    pts = tris.reshape(-1, 3)
    dims = pts.max(axis=0) - pts.min(axis=0)

    # Watertightness: every (welded) edge must be shared by exactly two triangles.
    scale = max(float(np.linalg.norm(dims)) * 1e-6, 1e-9)
    keys = np.round(pts / scale).astype(np.int64)
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    idx = inverse.reshape(-1, 3)
    edges = np.sort(np.concatenate([idx[:, [0, 1]], idx[:, [1, 2]], idx[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    watertight = bool((counts == 2).all())

    warnings = ["STL mesh: holes, threads and pockets cannot be recognised - upload STEP for a firm quote"]
    if not watertight:
        warnings.append("mesh is not watertight - volume may be inaccurate")

    preview = None
    if len(tris) <= max_triangles:
        verts = tris.reshape(-1, 3)
        preview = stl_bytes(verts, np.arange(len(verts)).reshape(-1, 3))

    return {
        "format": "STL",
        "bounding_box": [round(float(d), 3) for d in dims],
        "volume_cm3": round(volume_mm3 / 1000.0, 4),
        "surface_area_cm2": round(area_mm2 / 100.0, 4),
        "features": {"holes": 0, "threads": 0, "pockets": 0, "complex_curves": 0},
        "diagnostics": {
            "source_format": "STL",
            "solid_count": 1,
            "face_count": int(len(tris)),
            "brep_valid": watertight,
            "is_rotational": None,
            "access_directions": [],
            "inclined_features": 0,
            "thread_detection": "none",
            "warnings": warnings,
        },
        "preview_stl": preview,
    }
