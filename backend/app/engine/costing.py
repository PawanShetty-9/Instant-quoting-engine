"""Deterministic time & cost model (rules 2 and 3 of the engine contract).

All money is computed with ``Decimal`` and rounded half-up to the cent at each
published line item, so ``net = material + machining + energy + margin`` and
``gross = net + VAT`` hold exactly - a requirement for a quote that is printed
and potentially accepted as a contract offer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.catalog.machines import MACHINES, Process
from app.catalog.materials import Material
from app.config import Settings
from app.schemas import CostBreakdown, CostVectors, FactoryStatus, MaterialBreakdown, TimeBreakdown

CENT = Decimal("0.01")
ALL_DIRECTIONS = {f"{s}{a}" for s in "+-" for a in "XYZ"}


def money(value: Decimal | float) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class GeometryProfile:
    bbox: tuple[float, float, float]
    volume_cm3: float
    area_cm2: float
    holes: int
    threads: int
    pockets: int
    complex_curves: int
    is_rotational: bool
    rotational_source: str  # "parser" | "heuristic"
    turning_diameter: float | None
    turning_length: float | None
    access_directions: tuple[str, ...]
    inclined_features: int

    @property
    def multi_sided(self) -> bool:
        return len(self.access_directions) >= 3 or self.inclined_features > 0


@dataclass(frozen=True)
class ProcessCost:
    process: Process
    fits_envelope: bool
    machine_available: bool
    hourly_rate: float
    hours: float
    lead_time_days: int
    breakdown: CostBreakdown
    margin_eur: float
    time: TimeBreakdown
    material: MaterialBreakdown


def stock_for(process: Process, geo: GeometryProfile, settings: Settings) -> tuple[float, list[float]]:
    """Raw blank volume (cm3) and dimensions (mm) incl. machining allowance."""
    if process is Process.LATHE and geo.turning_diameter and geo.turning_length:
        d = geo.turning_diameter + settings.stock_allowance_lathe_diameter_mm
        length = geo.turning_length + settings.stock_allowance_lathe_length_mm
        return math.pi / 4 * d * d * length / 1000.0, [round(d, 2), round(length, 2)]
    a = 2 * settings.stock_allowance_mill_mm
    dims = [d + a for d in geo.bbox]
    return dims[0] * dims[1] * dims[2] / 1000.0, [round(d, 2) for d in dims]


def setups_for(process: Process, geo: GeometryProfile) -> int:
    if process is Process.LATHE:
        return 1
    dirs = set(geo.access_directions)
    if process is Process.CNC_5_AXIS:
        # One clamping reaches five sides; a sixth side forces a re-clamp.
        return 1 if len(dirs) < 6 else 2
    return max(1, len(dirs))


def fits(process: Process, geo: GeometryProfile) -> bool:
    machine = MACHINES[process]
    if process is Process.LATHE:
        return geo.is_rotational and machine.fits(geo.bbox, geo.turning_length, geo.turning_diameter)
    return machine.fits(geo.bbox)


def cost_process(
    process: Process,
    geo: GeometryProfile,
    material: Material,
    cost_vectors: CostVectors,
    factory: FactoryStatus,
    quantity: int,
    settings: Settings,
) -> ProcessCost:
    machine = MACHINES[process]

    # ---- time (rule 2) -------------------------------------------------------------
    stock_cm3, stock_dims = stock_for(process, geo, settings)
    removal_cm3 = max(stock_cm3 - geo.volume_cm3, 0.0)
    rough_min = removal_cm3 / (material.mrr_rough_cm3_min * machine.mrr_factor)
    finish_min = geo.area_cm2 / (material.finish_rate_cm2_min * machine.finish_factor)
    feature_min = (
        geo.holes * settings.hole_penalty_minutes
        + geo.threads * settings.thread_penalty_minutes
        + geo.pockets * settings.pocket_penalty_minutes
        + geo.complex_curves * settings.complex_curve_penalty_minutes
    )
    setups = setups_for(process, geo)
    setup_min = settings.base_setup_minutes + (setups - 1) * settings.additional_setup_minutes
    first_cycle = rough_min + finish_min + feature_min
    series_cycle = rough_min + finish_min + feature_min * settings.series_feature_factor
    total_min = setup_min + first_cycle + (quantity - 1) * series_cycle
    hours = round(total_min / 60.0, 2)

    # ---- money (rule 3) --------------------------------------------------------------
    density = material.density_g_cm3
    part_kg = geo.volume_cm3 * density / 1000.0
    stock_kg = stock_cm3 * density / 1000.0
    basis_kg = part_kg if settings.material_basis == "part" else stock_kg
    rate = cost_vectors.rate_for(process)

    material_cost = money(Decimal(str(basis_kg)) * Decimal(str(cost_vectors.material_per_kg)) * quantity)
    machining_cost = money(Decimal(str(hours)) * Decimal(str(rate)))
    base = material_cost + machining_cost
    energy = money(base * Decimal(str(cost_vectors.energy_surcharge_percent)) / 100)
    cost_total = base + energy
    m = Decimal(str(cost_vectors.target_margin_percent)) / 100
    if settings.margin_mode == "markup":
        margin = money(cost_total * m)
    else:
        margin = money(cost_total / (1 - m) - cost_total)
    net = cost_total + margin
    vat = money(net * Decimal(str(settings.vat_rate_percent)) / 100)
    gross = net + vat

    # ---- lead time ---------------------------------------------------------------------
    available = factory.machine_availability.is_available(process)
    lead = (
        factory.current_backlog_days
        + max(1, math.ceil(hours / settings.productive_hours_per_day))
        + settings.qa_and_shipping_days
        + (0 if available else settings.capacity_delay_days)
    )

    return ProcessCost(
        process=process,
        fits_envelope=fits(process, geo),
        machine_available=available,
        hourly_rate=rate,
        hours=hours,
        lead_time_days=lead,
        breakdown=CostBreakdown(
            material_cost_eur=float(material_cost),
            machining_cost_eur=float(machining_cost),
            energy_surcharge_eur=float(energy),
            net_total_eur=float(net),
            vat_19_eur=float(vat),
            gross_total_eur=float(gross),
        ),
        margin_eur=float(margin),
        time=TimeBreakdown(
            setup_minutes=round(setup_min, 2),
            setups=setups,
            roughing_minutes_per_part=round(rough_min, 2),
            finishing_minutes_per_part=round(finish_min, 2),
            feature_minutes_first_part=round(feature_min, 2),
            feature_minutes_series_part=round(feature_min * settings.series_feature_factor, 2),
            cycle_minutes_first_part=round(first_cycle, 2),
            total_minutes=round(total_min, 2),
        ),
        material=MaterialBreakdown(
            key=material.key,
            name=material.name_de,
            density_g_cm3=density,
            price_eur_per_kg=cost_vectors.material_per_kg,
            basis=settings.material_basis,
            part_mass_kg=round(part_kg, 4),
            stock_mass_kg=round(stock_kg, 4),
            stock_dimensions_mm=stock_dims,
            buy_to_fly_ratio=round(stock_cm3 / geo.volume_cm3, 2),
            removal_volume_cm3=round(removal_cm3, 3),
        ),
    )
