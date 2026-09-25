"""Rules 2-4: time model, financial formula, VAT and lead time."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from app.catalog.machines import Process
from app.catalog.materials import MATERIALS
from app.config import Settings
from app.engine import costing
from app.engine.rules import profile_from_metadata
from app.schemas import EngineInput
from tests.conftest import manual_input


def _cost(settings: Settings, process=Process.CNC_3_AXIS, quantity=1, **overrides):
    data = EngineInput.model_validate(manual_input(**overrides))
    geo = profile_from_metadata(data.cad_metadata)
    return costing.cost_process(
        process, geo, MATERIALS["AL_6082_T6"], data.cost_vectors, data.factory_status, quantity, settings
    )


def test_spec_formula_hand_calculation():
    s = Settings(_env_file=None)
    c = _cost(s)
    # Time: stock (106 x 66 x 26) - part 100 cm3 at 150 cm3/min, 200 cm2 at 25 cm2/min,
    # features 4*5 + 2*5 + 1*15 = 45 min, set-up 45 min.
    stock = 106 * 66 * 26 / 1000
    minutes = 45 + (stock - 100) / 150 + 200 / 25 + 45
    assert c.time.total_minutes == pytest.approx(minutes, abs=0.01)
    hours = round(minutes / 60, 2)
    assert c.hours == hours

    material = round(100 * 2.70 / 1000 * 7.5, 2)  # Volume * density * EUR/kg
    machining = round(hours * 85.0, 2)
    energy = round((material + machining) * 0.04, 2)
    margin = round((material + machining + energy) * 0.15, 2)
    net = round(material + machining + energy + margin, 2)
    b = c.breakdown
    assert b.material_cost_eur == material
    assert b.machining_cost_eur == machining
    assert b.energy_surcharge_eur == energy
    assert b.net_total_eur == net
    assert b.vat_19_eur == round(net * 0.19, 2)
    assert b.gross_total_eur == round(net + b.vat_19_eur, 2)


def test_money_identities_are_cent_exact():
    s = Settings(_env_file=None)
    for qty in (1, 7, 250):
        c = _cost(s, quantity=qty)
        b = c.breakdown
        d = lambda v: Decimal(str(v))  # noqa: E731
        assert d(b.material_cost_eur) + d(b.machining_cost_eur) + d(b.energy_surcharge_eur) + d(c.margin_eur) == d(
            b.net_total_eur
        )
        assert d(b.net_total_eur) + d(b.vat_19_eur) == d(b.gross_total_eur)


def test_margin_mode_margin_vs_markup():
    markup = _cost(Settings(_env_file=None, margin_mode="markup"))
    margin = _cost(Settings(_env_file=None, margin_mode="margin"))
    cost = markup.breakdown.net_total_eur - markup.margin_eur
    assert markup.margin_eur == pytest.approx(cost * 0.15, abs=0.01)
    # True margin: margin / net price = 15 %
    assert margin.margin_eur / margin.breakdown.net_total_eur == pytest.approx(0.15, abs=1e-3)


def test_stock_basis_charges_raw_blank():
    part = _cost(Settings(_env_file=None, material_basis="part"))
    stock = _cost(Settings(_env_file=None, material_basis="stock"))
    assert stock.breakdown.material_cost_eur > part.breakdown.material_cost_eur
    assert stock.breakdown.material_cost_eur == round(stock.material.stock_mass_kg * 7.5, 2)


def test_series_amortises_setup_and_feature_time():
    s = Settings(_env_file=None)
    one = _cost(s, quantity=1)
    many = _cost(s, quantity=100)
    assert many.breakdown.net_total_eur / 100 < one.breakdown.net_total_eur / 3
    series_cycle = one.time.cycle_minutes_first_part - one.time.feature_minutes_first_part * (
        1 - s.series_feature_factor
    )
    assert many.time.total_minutes == pytest.approx(
        one.time.total_minutes + 99 * series_cycle, abs=1.0
    )  # per-field rounding x 99


def test_lead_time_and_capacity_delay():
    s = Settings(_env_file=None)
    ok = _cost(s)
    assert ok.lead_time_days == 3 + max(1, math.ceil(ok.hours / 16)) + 2
    blocked = _cost(s, factory_status={"machine_availability": {"CNC_3_Axis": False}, "current_backlog_days": 3})
    assert blocked.machine_available is False
    assert blocked.lead_time_days == ok.lead_time_days + 5


def test_per_machine_rate_extension():
    s = Settings(_env_file=None)
    c = _cost(
        s,
        process=Process.CNC_5_AXIS,
        cost_vectors={
            "material_per_kg": 7.5,
            "machine_hourly_rate": 85,
            "energy_surcharge_percent": 4,
            "target_margin_percent": 15,
            "machine_hourly_rates": {"CNC_5_Axis": 110},
        },
    )
    assert c.hourly_rate == 110
    assert c.breakdown.machining_cost_eur == round(c.hours * 110, 2)
