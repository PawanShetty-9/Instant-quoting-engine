"""Pydantic contracts.

``EngineInput`` / ``EngineQuote`` implement the engine contract verbatim
(``cad_metadata`` / ``factory_status`` / ``cost_vectors`` in, the quote JSON
out). Fields marked *extension* are optional additions that the CAD parser
fills in so the engine does not have to guess; clients that only send the
spec fields still get a valid quote.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.billing.plans import Feature
from app.catalog.machines import Process

Feasibility = Literal["Feasible", "Review Required", "Infeasible"]
FEATURE_KEYS = ("holes", "threads", "pockets", "complex_curves")


class Features(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holes: int = Field(default=0, ge=0, le=10_000)
    threads: int = Field(default=0, ge=0, le=10_000)
    pockets: int = Field(default=0, ge=0, le=10_000)
    complex_curves: int = Field(default=0, ge=0, le=1_000)


class GeometryDiagnostics(BaseModel):
    """Extension: DFM-relevant measurements produced by the CAD parser."""

    source_format: Literal["STEP", "IGES", "STL", "manual"] = "manual"
    solid_count: int = 1
    face_count: int | None = None
    brep_valid: bool | None = None
    is_rotational: bool | None = None
    rotational_axis: Literal["X", "Y", "Z"] | None = None
    rotational_fraction: float | None = None
    turning_diameter_mm: float | None = None
    turning_length_mm: float | None = None
    access_directions: list[str] = Field(default_factory=list)
    inclined_features: int = 0
    min_hole_diameter_mm: float | None = None
    max_hole_depth_to_diameter: float | None = None
    min_internal_radius_mm: float | None = None
    freeform_area_fraction: float | None = None
    closed_pockets: int | None = None
    open_steps: int | None = None
    thread_detection: Literal["tap_drill_heuristic", "user_override", "none"] = "none"
    warnings: list[str] = Field(default_factory=list)


class CadMetadata(BaseModel):
    bounding_box: tuple[float, float, float] = Field(description="[x, y, z] in mm")
    volume_cm3: float = Field(gt=0)
    surface_area_cm2: float = Field(gt=0)
    features: Features = Field(default_factory=Features)
    requested_material: str = Field(min_length=1, max_length=120)
    diagnostics: GeometryDiagnostics | None = None  # extension

    @field_validator("bounding_box")
    @classmethod
    def _positive_bbox(cls, v: tuple[float, float, float]) -> tuple[float, float, float]:
        if any(d <= 0 for d in v):
            raise ValueError("bounding_box dimensions must be > 0 mm")
        if any(d > 20_000 for d in v):
            raise ValueError("bounding_box dimension exceeds 20 m - check units")
        return v

    @field_validator("features", mode="before")
    @classmethod
    def _accept_feature_list(cls, v: Any) -> Any:
        # The contract describes features as ``[holes, threads, pockets, complex_curves]``;
        # accept a list of feature names (counted) as well as a dict of counts.
        if isinstance(v, list):
            unknown = [f for f in v if f not in FEATURE_KEYS]
            if unknown:
                raise ValueError(f"unknown feature names: {unknown}")
            return dict(Counter(v))
        return v

    @model_validator(mode="after")
    def _volume_plausible(self) -> CadMetadata:
        x, y, z = self.bounding_box
        bbox_cm3 = x * y * z / 1000.0
        if self.volume_cm3 > bbox_cm3 * 1.001:
            raise ValueError(f"volume_cm3 ({self.volume_cm3:.3f}) exceeds bounding-box volume ({bbox_cm3:.3f})")
        return self


class MachineAvailability(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    CNC_5_Axis: bool = True
    CNC_3_Axis: bool = True
    Lathe: bool = True

    def is_available(self, process: Process) -> bool:
        return bool(getattr(self, process.value))


class FactoryStatus(BaseModel):
    machine_availability: MachineAvailability = Field(default_factory=MachineAvailability)
    current_backlog_days: int = Field(default=0, ge=0, le=365)


class CostVectors(BaseModel):
    material_per_kg: float = Field(ge=0, le=10_000)
    machine_hourly_rate: float = Field(ge=0, le=2_000)
    energy_surcharge_percent: float = Field(ge=0, le=100)
    target_margin_percent: float = Field(ge=0, le=95)
    # Extension: per-machine rates. When absent, machine_hourly_rate applies to all.
    machine_hourly_rates: dict[Process, float] | None = None

    def rate_for(self, process: Process) -> float:
        if self.machine_hourly_rates and process in self.machine_hourly_rates:
            return self.machine_hourly_rates[process]
        return self.machine_hourly_rate


class OrderInfo(BaseModel):
    """Extension: batch size. Omit for the single-part contract behaviour."""

    quantity: int = Field(default=1, ge=1, le=100_000)


class EngineInput(BaseModel):
    cad_metadata: CadMetadata
    factory_status: FactoryStatus
    cost_vectors: CostVectors
    order: OrderInfo = Field(default_factory=OrderInfo)


class CostBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_cost_eur: float
    machining_cost_eur: float
    energy_surcharge_eur: float
    net_total_eur: float
    vat_19_eur: float
    gross_total_eur: float


class EngineQuote(BaseModel):
    """The engine output contract - exactly the schema of the specification."""

    model_config = ConfigDict(extra="forbid")

    quote_id: str
    feasibility: Feasibility
    feasibility_notes: str
    selected_process: str
    estimated_production_time_hours: float
    cost_breakdown: CostBreakdown
    recommended_lead_time_days: int


# ----------------------------------------------------------------------------------
# API envelope
# ----------------------------------------------------------------------------------


class TimeBreakdown(BaseModel):
    setup_minutes: float
    setups: int
    roughing_minutes_per_part: float
    finishing_minutes_per_part: float
    feature_minutes_first_part: float
    feature_minutes_series_part: float
    cycle_minutes_first_part: float
    total_minutes: float


class MaterialBreakdown(BaseModel):
    key: str | None
    name: str
    density_g_cm3: float | None
    price_eur_per_kg: float
    basis: Literal["part", "stock"]
    part_mass_kg: float
    stock_mass_kg: float
    stock_dimensions_mm: list[float]
    buy_to_fly_ratio: float
    removal_volume_cm3: float


class ProcessCandidate(BaseModel):
    process: Process
    fits_envelope: bool
    machine_available: bool
    hourly_rate_eur: float
    estimated_production_time_hours: float
    cost_breakdown: CostBreakdown
    recommended_lead_time_days: int
    time_breakdown: TimeBreakdown


class Analysis(BaseModel):
    engine: Literal["claude", "rules"]
    model: str | None = None
    ai_latency_ms: int | None = None
    rule_based_process: str
    flags: list[str]
    candidates: list[ProcessCandidate]
    time_breakdown: TimeBreakdown | None
    material: MaterialBreakdown | None
    margin_eur: float
    validation: list[str] = Field(default_factory=list)


class Supplier(BaseModel):
    name: str
    street: str
    city: str
    country: str
    email: str
    phone: str
    vat_id: str
    commercial_register: str
    managing_director: str


class Commercial(BaseModel):
    currency: Literal["EUR"] = "EUR"
    quantity: int
    unit_price_net_eur: float
    vat_rate_percent: float
    created_at: str
    valid_until: str
    customer_reference: str | None = None
    file_name: str | None = None
    material_label: str
    supplier: Supplier
    terms_de: list[str]
    terms_en: list[str]


class Entitlements(BaseModel):
    """What the plan that created the quote unlocks - the web app shows or locks UI from this."""

    # Quotes stored before plans existed keep every detail.
    plan: str = "business"
    features: list[str] = Field(default_factory=lambda: [f.value for f in Feature])


class QuoteResponse(BaseModel):
    quote: EngineQuote
    engine_input: EngineInput
    analysis: Analysis
    commercial: Commercial
    has_preview: bool = False
    entitlements: Entitlements = Field(default_factory=Entitlements)


class FactoryState(BaseModel):
    factory_status: FactoryStatus
    energy_surcharge_percent: float = Field(ge=0, le=100)
    target_margin_percent: float = Field(ge=0, le=95)
    machine_hourly_rates: dict[Process, float]
    material_prices_eur_per_kg: dict[str, float] = Field(default_factory=dict)


class FactoryStateUpdate(BaseModel):
    """Partial update - e.g. pushed by an MES / the Industrie 4.0 telemetry gateway."""

    machine_availability: MachineAvailability | None = None
    current_backlog_days: int | None = Field(default=None, ge=0, le=365)
    energy_surcharge_percent: float | None = Field(default=None, ge=0, le=100)
    target_margin_percent: float | None = Field(default=None, ge=0, le=95)
    machine_hourly_rates: dict[Process, float] | None = None
    material_prices_eur_per_kg: dict[str, float] | None = None
