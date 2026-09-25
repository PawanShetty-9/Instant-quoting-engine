"""CAD parsing: STEP feature recognition, STL/IGES fallbacks and upload sniffing."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from app.cad.brep import CadParseError, analyse_step_file
from app.cad.parser import parse_cad_bytes, sniff_format
from app.cad.stl import analyse_stl_bytes


def test_bracket_prismatic(samples):
    r = analyse_step_file(str(samples["bracket"]))
    assert r["bounding_box"] == [120.0, 80.0, 25.0]
    assert r["features"] == {"holes": 6, "threads": 2, "pockets": 2, "complex_curves": 0}
    d = r["diagnostics"]
    assert d["access_directions"] == ["+Z"]
    assert d["is_rotational"] is False
    assert d["closed_pockets"] == 1 and d["open_steps"] == 1
    assert d["min_internal_radius_mm"] == pytest.approx(5.0)
    assert r["preview_stl"][:4] != b"soli"  # binary STL


def test_shaft_is_turned(samples):
    r = analyse_step_file(str(samples["shaft"]))
    d = r["diagnostics"]
    assert d["is_rotational"] is True
    assert d["rotational_axis"] == "X"
    assert d["turning_diameter_mm"] == pytest.approx(40.0, abs=0.05)
    assert d["turning_length_mm"] == pytest.approx(130.0, abs=0.05)
    assert r["features"]["holes"] == 1  # centre bore
    assert r["features"]["pockets"] == 0


def test_manifold_multi_sided(samples):
    r = analyse_step_file(str(samples["manifold"]))
    assert r["features"]["holes"] == 8
    assert r["features"]["threads"] == 4  # 4 x M6 tap drill 5.0 mm
    assert set(r["diagnostics"]["access_directions"]) == {"+X", "-X", "+Y", "+Z"}


def test_blade_freeform(samples):
    r = analyse_step_file(str(samples["blade"]))
    assert r["features"]["complex_curves"] == 1
    assert r["diagnostics"]["freeform_area_fraction"] > 0.3


def test_volume_matches_analytic(samples):
    r = analyse_step_file(str(samples["shaft"]))
    import math

    cone = math.pi * 2 / 3 * (10**2 + 10 * 8 + 8**2)  # chamfer frustum kept
    expected = math.pi * (20**2 * 30 + 15**2 * 60 + 10**2 * 38) + cone
    bore = math.pi * 5**2 * 20 + math.pi / 3 * 5**2 * (5 / math.tan(math.radians(59)))
    assert r["volume_cm3"] == pytest.approx((expected - bore) / 1000, rel=1e-3)


def _cube_stl(size: float = 10.0) -> bytes:
    v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float) * size
    faces = [
        (0, 2, 1),
        (0, 3, 2),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (1, 2, 6),
        (1, 6, 5),
        (2, 3, 7),
        (2, 7, 6),
        (3, 0, 4),
        (3, 4, 7),
    ]
    out = b"cube".ljust(80, b" ") + struct.pack("<I", len(faces))
    for a, b, c in faces:
        out += struct.pack("<12fH", 0, 0, 0, *v[a], *v[b], *v[c], 0)
    return out


def test_stl_binary_cube():
    r = analyse_stl_bytes(_cube_stl())
    assert r["volume_cm3"] == pytest.approx(1.0)
    assert r["surface_area_cm2"] == pytest.approx(6.0)
    assert r["diagnostics"]["brep_valid"] is True  # watertight


def test_stl_inch_scaling():
    r = analyse_stl_bytes(_cube_stl(1.0), unit_scale=25.4)
    assert r["bounding_box"] == [25.4, 25.4, 25.4]


def test_stl_ascii():
    text = (
        "solid t\n"
        + "".join(
            f"facet normal 0 0 0\nouter loop\nvertex {a}\nvertex {b}\nvertex {c}\nendloop\nendfacet\n"
            for a, b, c in [
                ("0 0 0", "0 10 0", "10 0 0"),
                ("0 0 0", "10 0 0", "0 0 10"),
                ("0 0 0", "0 0 10", "0 10 0"),
                ("10 0 0", "0 10 0", "0 0 10"),
            ]
        )
        + "endsolid t\n"
    )
    r = analyse_stl_bytes(text.encode())
    assert r["volume_cm3"] == pytest.approx(1000 / 6 / 1000, abs=1e-4)


def test_sniff_rejects_mismatch_and_unknown():
    with pytest.raises(CadParseError):
        sniff_format(b"MZ\x90\x00 not a cad file", "part.step")
    with pytest.raises(CadParseError):
        sniff_format(b"ISO-10303-21;\nHEADER;", "part.stl")
    with pytest.raises(CadParseError):
        sniff_format(b"ISO-10303-21;", "part.exe")
    assert sniff_format(b"\xef\xbb\xbf ISO-10303-21;\nHEADER;", "p.STP") == "STEP"


def test_isolated_parse_of_step(samples):
    parsed = parse_cad_bytes(samples["bracket"].read_bytes(), "bracket.step", timeout_s=60)
    assert parsed.format == "STEP"
    assert parsed.features["holes"] == 6


def test_isolated_parse_rejects_garbage_step():
    with pytest.raises(CadParseError):
        parse_cad_bytes(b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n", "x.step")


def test_iges_roundtrip(samples, tmp_path):
    from OCP.IGESControl import IGESControl_Writer

    from app.cad.brep import read_step

    path = tmp_path / "bracket.igs"
    writer = IGESControl_Writer("MM", 1)  # BRep mode
    writer.AddShape(read_step(str(samples["bracket"])))
    writer.ComputeModel()
    assert writer.Write(str(path))
    parsed = parse_cad_bytes(path.read_bytes(), "bracket.igs", timeout_s=60)
    assert parsed.format == "IGES"
    assert parsed.volume_cm3 == pytest.approx(203.18, rel=1e-3)
