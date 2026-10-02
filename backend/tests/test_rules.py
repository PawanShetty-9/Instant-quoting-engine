"""Rule 1 (machine selection), envelope handling and feasibility."""

from __future__ import annotations

import asyncio

import pytest

from app.catalog.materials import resolve_material
from app.config import Settings
from app.engine.quote import QuoteEngine
from app.schemas import CadMetadata, EngineInput
from tests.conftest import manual_input


def run(body: dict, settings: Settings | None = None):
    engine = QuoteEngine(settings or Settings(_env_file=None))
    return asyncio.run(engine.evaluate(EngineInput.model_validate(body), "AQ-20260101-TEST000000"))


def test_prismatic_part_goes_to_3_axis():
    r = run(manual_input())
    assert r.quote.selected_process == "CNC_3_Axis"
    assert r.quote.feasibility == "Feasible"
    assert r.quote.quote_id == "AQ-20260101-TEST000000"


def test_complex_curves_require_5_axis():
    body = manual_input()
    body["cad_metadata"]["features"]["complex_curves"] = 1
    assert run(body).quote.selected_process == "CNC_5_Axis"


def test_multi_sided_requires_5_axis():
    body = manual_input()
    body["cad_metadata"]["diagnostics"] = {"access_directions": ["+Z", "+X", "-Y"], "is_rotational": False}
    assert run(body).quote.selected_process == "CNC_5_Axis"


def test_cylindrical_part_goes_to_lathe():
    body = manual_input()
    body["cad_metadata"].update(
        bounding_box=[40.0, 40.0, 120.0],
        volume_cm3=140.0,
        surface_area_cm2=170.0,
        features={"holes": 1, "threads": 0, "pockets": 0, "complex_curves": 0},
    )
    r = run(body)
    assert r.quote.selected_process == "Lathe"
    assert "ROTATIONAL_HEURISTIC" in r.analysis.flags


def test_capacity_delay_flag_and_five_days():
    ok = run(manual_input())
    body = manual_input()
    # No free substitute: 3-axis busy and the 5-axis centre too.
    body["factory_status"]["machine_availability"].update(CNC_3_Axis=False, CNC_5_Axis=False)
    r = run(body)
    assert r.quote.selected_process == "CNC_3_Axis"
    assert "CAPACITY_DELAY" in r.analysis.flags
    assert "Capacity Delay" in r.quote.feasibility_notes
    assert r.quote.recommended_lead_time_days == ok.quote.recommended_lead_time_days + 5


def test_busy_3_axis_reroutes_to_free_5_axis():
    ok = run(manual_input())
    body = manual_input()
    body["factory_status"]["machine_availability"]["CNC_3_Axis"] = False
    r = run(body)
    assert r.analysis.rule_based_process == "CNC_3_Axis"
    assert r.quote.selected_process == "CNC_5_Axis"
    assert r.quote.feasibility == "Feasible"
    assert "CAPACITY_REROUTE" in r.analysis.flags
    assert "CAPACITY_DELAY" not in r.analysis.flags
    assert "ENVELOPE_REROUTE" not in r.analysis.flags
    assert r.quote.recommended_lead_time_days < ok.quote.recommended_lead_time_days + 5


def test_busy_lathe_reroutes_to_milling():
    body = manual_input()
    body["cad_metadata"].update(
        bounding_box=[40.0, 40.0, 120.0],
        volume_cm3=140.0,
        surface_area_cm2=170.0,
        features={"holes": 1, "threads": 0, "pockets": 0, "complex_curves": 0},
    )
    body["factory_status"]["machine_availability"]["Lathe"] = False
    r = run(body)
    assert r.analysis.rule_based_process == "Lathe"
    assert r.quote.selected_process == "CNC_3_Axis"
    assert "CAPACITY_REROUTE" in r.analysis.flags


def test_busy_5_axis_job_waits_instead_of_downgrading():
    body = manual_input()
    body["cad_metadata"]["features"]["complex_curves"] = 1
    body["factory_status"]["machine_availability"]["CNC_5_Axis"] = False
    r = run(body)
    assert r.quote.selected_process == "CNC_5_Axis"
    assert "CAPACITY_DELAY" in r.analysis.flags


def test_envelope_reroute_to_5_axis():
    body = manual_input()
    # 600 x 600 mm does not fit the 3-axis Y travel (500) but fits the 5-axis table.
    body["cad_metadata"].update(bounding_box=[600.0, 600.0, 50.0], volume_cm3=9000.0, surface_area_cm2=8000.0)
    r = run(body)
    assert r.analysis.rule_based_process == "CNC_3_Axis"
    assert r.quote.selected_process == "CNC_5_Axis"
    assert r.quote.feasibility == "Review Required"


def test_part_too_large_is_infeasible():
    body = manual_input()
    body["cad_metadata"].update(bounding_box=[2000.0, 900.0, 900.0], volume_cm3=50_000.0, surface_area_cm2=90_000.0)
    r = run(body)
    assert r.quote.feasibility == "Infeasible"
    assert "NO_MACHINE_FITS" in r.analysis.flags


def test_unknown_material_is_infeasible_with_zero_price():
    body = manual_input()
    body["cad_metadata"]["requested_material"] = "Unobtainium 9000"
    r = run(body)
    assert r.quote.feasibility == "Infeasible"
    assert r.quote.cost_breakdown.net_total_eur == 0
    assert "UNKNOWN_MATERIAL" in r.analysis.flags


def test_notes_are_bilingual():
    notes = run(manual_input()).quote.feasibility_notes
    assert notes.startswith("DE: ") and " | EN: " in notes


def test_high_value_requires_commercial_review():
    body = manual_input()
    body["order"] = {"quantity": 5000}
    r = run(body)
    assert "HIGH_VALUE" in r.analysis.flags
    assert r.quote.feasibility == "Review Required"


def test_feature_list_form_is_accepted():
    body = manual_input()
    body["cad_metadata"]["features"] = ["holes", "holes", "threads", "pockets"]
    cad = CadMetadata.model_validate(body["cad_metadata"])
    assert (cad.features.holes, cad.features.threads, cad.features.pockets) == (2, 1, 1)


def test_volume_larger_than_bbox_rejected():
    body = manual_input()
    body["cad_metadata"]["volume_cm3"] = 1000.0
    with pytest.raises(ValueError):
        CadMetadata.model_validate(body["cad_metadata"])


@pytest.mark.parametrize(
    "text,key",
    [
        ("Aluminium 6082", "AL_6082_T6"),
        ("EN AW-7075", "AL_7075_T651"),
        ("1.4301", "SS_1.4301"),
        ("V4A", "SS_1.4404"),
        ("Ti6Al4V", "TI_GRADE5"),
        ("CW614N", "BRASS_CW614N"),
        ("42CrMo4", "STEEL_42CRMO4"),
        ("delrin", "POM_C"),
    ],
)
def test_material_aliases(text, key):
    assert resolve_material(text).key == key
