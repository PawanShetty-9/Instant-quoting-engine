"""Machine park definition.

The three process classes mirror the engine contract (``CNC_5_Axis``,
``CNC_3_Axis``, ``Lathe``). Envelopes correspond to common Mittelstand
machines (e.g. 3-axis VMC in the Haas VF-3 / DMG MORI CMX 1100 V class,
5-axis in the DMU 65 monoBLOCK class, 2-axis CNC lathe in the CLX 450 class)
reduced by a clamping margin. Hourly rates are German 2025/26 reference values
(pos.de: 3-axis 85 EUR/h, 5-axis 110 EUR/h; turning 60-90 EUR/h).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Process(StrEnum):
    CNC_5_AXIS = "CNC_5_Axis"
    CNC_3_AXIS = "CNC_3_Axis"
    LATHE = "Lathe"


@dataclass(frozen=True)
class Machine:
    process: Process
    label_de: str
    label_en: str
    default_hourly_rate_eur: float
    # Max part envelope in mm. Milling: (x, y, z). Lathe: (max diameter, max length, -).
    envelope_mm: tuple[float, float, float]
    # Multiplier on the material's reference roughing MRR / finishing rate.
    mrr_factor: float
    finish_factor: float
    # Average electrical draw while cutting (kW) - used for the energy model docs/UI.
    avg_power_kw: float

    def fits(
        self,
        bbox_mm: tuple[float, float, float],
        rotational_axis_len: float | None = None,
        rotational_diameter: float | None = None,
    ) -> bool:
        if self.process is Process.LATHE:
            if rotational_diameter is None or rotational_axis_len is None:
                return False
            max_d, max_l, _ = self.envelope_mm
            return rotational_diameter <= max_d and rotational_axis_len <= max_l
        part = sorted(bbox_mm, reverse=True)
        env = sorted(self.envelope_mm, reverse=True)
        return all(p <= e for p, e in zip(part, env, strict=True))


MACHINES: dict[Process, Machine] = {
    Process.CNC_3_AXIS: Machine(
        process=Process.CNC_3_AXIS,
        label_de="3-Achs-Vertikal-Bearbeitungszentrum",
        label_en="3-axis vertical machining centre",
        default_hourly_rate_eur=85.0,
        envelope_mm=(1000.0, 500.0, 450.0),
        mrr_factor=1.0,
        finish_factor=1.0,
        avg_power_kw=12.0,
    ),
    Process.CNC_5_AXIS: Machine(
        process=Process.CNC_5_AXIS,
        label_de="5-Achs-Simultan-Bearbeitungszentrum",
        label_en="5-axis simultaneous machining centre",
        default_hourly_rate_eur=110.0,
        envelope_mm=(650.0, 650.0, 450.0),
        # Longer tools and tilted set-ups reduce rigidity -> lower effective MRR.
        mrr_factor=0.85,
        finish_factor=0.9,
        avg_power_kw=18.0,
    ),
    Process.LATHE: Machine(
        process=Process.LATHE,
        label_de="CNC-Drehmaschine",
        label_en="CNC turning centre",
        default_hourly_rate_eur=75.0,
        envelope_mm=(300.0, 600.0, 0.0),
        # Turning removes material far more efficiently than milling.
        mrr_factor=1.4,
        finish_factor=1.5,
        avg_power_kw=10.0,
    ),
}
