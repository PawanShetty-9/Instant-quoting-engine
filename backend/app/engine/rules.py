"""Machine selection (rule 1) and deterministic feasibility assessment."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.catalog.machines import MACHINES, Process
from app.config import Settings
from app.engine.costing import GeometryProfile, ProcessCost
from app.schemas import CadMetadata, Feasibility

_RANK = {"Feasible": 0, "Review Required": 1, "Infeasible": 2}


@dataclass(frozen=True)
class Flag:
    code: str
    severity: Feasibility
    de: str
    en: str


@dataclass
class RuleDecision:
    rule_process: Process  # what rule 1 asks for
    process: Process  # what we route to after envelope and capacity checks
    reasons_de: list[str] = field(default_factory=list)
    reasons_en: list[str] = field(default_factory=list)
    # Why `process` differs from `rule_process`: None, "envelope" or "capacity".
    reroute: str | None = None


def worst(*levels: Feasibility) -> Feasibility:
    return max(levels, key=lambda lv: _RANK[lv])


def profile_from_metadata(cad: CadMetadata) -> GeometryProfile:
    diag = cad.diagnostics
    x, y, z = cad.bounding_box
    f = cad.features
    if diag is not None and diag.is_rotational is not None:
        rotational = diag.is_rotational
        source = "parser"
        t_d, t_l = diag.turning_diameter_mm, diag.turning_length_mm
    else:
        # Manual payload without parser diagnostics: two equal bbox sides and a
        # solid-of-revolution-like fill ratio indicate a turned part.
        rotational, t_d, t_l = False, None, None
        dims = sorted([(x, "x"), (y, "y"), (z, "z")])
        for i, j, k in ((0, 1, 2), (1, 2, 0), (0, 2, 1)):
            a, b, c = dims[i][0], dims[j][0], dims[k][0]
            if abs(a - b) <= 0.02 * max(a, b):
                d, length = max(a, b), c
                cyl_cm3 = math.pi / 4 * d * d * length / 1000.0
                if (
                    cyl_cm3 > 0
                    and 0.5 <= cad.volume_cm3 / cyl_cm3 <= 1.001
                    and f.pockets == 0
                    and f.complex_curves == 0
                ):
                    rotational, t_d, t_l = True, d, length
                break
        source = "heuristic"
    return GeometryProfile(
        bbox=(x, y, z),
        volume_cm3=cad.volume_cm3,
        area_cm2=cad.surface_area_cm2,
        holes=f.holes,
        threads=f.threads,
        pockets=f.pockets,
        complex_curves=f.complex_curves,
        is_rotational=bool(rotational and not f.complex_curves),
        rotational_source=source,
        turning_diameter=t_d,
        turning_length=t_l,
        access_directions=tuple(diag.access_directions) if diag else (),
        inclined_features=diag.inclined_features if diag else 0,
    )


def select_process(geo: GeometryProfile, fits: dict[Process, bool]) -> RuleDecision:
    """Rule 1: complex curves / multi-sided -> 5-axis, simple cylindrical -> lathe, else 3-axis."""
    if geo.complex_curves > 0:
        rule = Process.CNC_5_AXIS
        de, en = (
            "Freiformflächen erfordern 5-Achs-Simultanbearbeitung",
            "complex free-form surfaces require 5-axis simultaneous machining",
        )
    elif geo.multi_sided:
        rule = Process.CNC_5_AXIS
        n = len(geo.access_directions)
        de = f"Bearbeitung von {n} Seiten/geneigten Achsen - 5-Achs-Bearbeitung in einer Aufspannung"
        en = f"features on {n} sides/inclined axes - 5-axis machining in a single clamping"
    elif geo.is_rotational:
        rule = Process.LATHE
        de, en = "rotationssymmetrisches Drehteil", "rotationally symmetric turned part"
    else:
        rule = Process.CNC_3_AXIS
        de, en = "prismatisches Frästeil", "prismatic milled part"
    decision = RuleDecision(rule_process=rule, process=rule, reasons_de=[de], reasons_en=[en])

    if fits[rule]:
        return decision
    # Envelope fallback: 3 <-> 5-axis can substitute each other (with more set-ups or a
    # higher rate); a lathe part can be milled on a machining centre.
    fallbacks = {
        Process.LATHE: [Process.CNC_3_AXIS, Process.CNC_5_AXIS],
        Process.CNC_5_AXIS: [Process.CNC_3_AXIS],
        Process.CNC_3_AXIS: [Process.CNC_5_AXIS],
    }[rule]
    for alt in fallbacks:
        if fits[alt]:
            decision.process = alt
            decision.reroute = "envelope"
            decision.reasons_de.append(f"Bauteil überschreitet Arbeitsraum {rule.value} - Umplanung auf {alt.value}")
            decision.reasons_en.append(f"part exceeds the {rule.value} work envelope - re-routed to {alt.value}")
            return decision
    return decision


# Machines that can take over a job when the preferred one is busy. A 5-axis centre can
# do anything a 3-axis centre can; a turned part can be milled. A 5-axis job has no
# substitute, so it waits (Capacity Delay).
CAPACITY_SUBSTITUTES: dict[Process, list[Process]] = {
    Process.LATHE: [Process.CNC_3_AXIS, Process.CNC_5_AXIS],
    Process.CNC_3_AXIS: [Process.CNC_5_AXIS],
    Process.CNC_5_AXIS: [],
}


def reroute_for_capacity(decision: RuleDecision, candidates: dict[Process, ProcessCost]) -> RuleDecision:
    """Move the job to a free, capable machine when the selected one is busy.

    The substitute is only taken if it actually delivers sooner; among equally fast
    substitutes the cheaper one wins. Without a better substitute the job stays put and
    `assess` raises the Capacity Delay flag.
    """
    current = candidates.get(decision.process)
    if current is None or current.machine_available:
        return decision
    options = [
        candidates[p]
        for p in CAPACITY_SUBSTITUTES[decision.process]
        if p in candidates and candidates[p].fits_envelope and candidates[p].machine_available
    ]
    options = [c for c in options if c.lead_time_days < current.lead_time_days]
    if not options:
        return decision
    best = min(options, key=lambda c: (c.lead_time_days, c.breakdown.net_total_eur))
    busy = decision.process.value
    return RuleDecision(
        rule_process=decision.rule_process,
        process=best.process,
        reasons_de=[
            *decision.reasons_de,
            f"{busy} ausgelastet - Umplanung auf freie Maschine {best.process.value}",
        ],
        reasons_en=[*decision.reasons_en, f"{busy} is busy - re-routed to free machine {best.process.value}"],
        reroute="capacity",
    )


def assess(
    cad: CadMetadata,
    geo: GeometryProfile,
    decision: RuleDecision,
    chosen: ProcessCost | None,
    candidates: dict[Process, ProcessCost],
    fits: dict[Process, bool],
    material_known: bool,
    settings: Settings,
) -> list[Flag]:
    diag = cad.diagnostics
    flags: list[Flag] = []

    def add(code: str, severity: Feasibility, de: str, en: str) -> None:
        flags.append(Flag(code, severity, de, en))

    if not material_known:
        add(
            "UNKNOWN_MATERIAL",
            "Infeasible",
            f"Werkstoff '{cad.requested_material}' ist nicht im Katalog - Einzelanfrage erforderlich",
            f"material '{cad.requested_material}' is not in the catalogue - manual quotation required",
        )
    if not fits[decision.process]:
        add(
            "NO_MACHINE_FITS",
            "Infeasible",
            "Bauteil überschreitet den Arbeitsraum aller verfügbaren Maschinen",
            "part exceeds the work envelope of every machine in the park",
        )
    if decision.reroute == "envelope" and fits[decision.process]:
        add("ENVELOPE_REROUTE", "Review Required", decision.reasons_de[-1], decision.reasons_en[-1])
    if decision.reroute == "capacity":
        add("CAPACITY_REROUTE", "Feasible", decision.reasons_de[-1], decision.reasons_en[-1])
    if chosen is not None and not chosen.machine_available:
        alt = [
            p.value
            for p, c in candidates.items()
            if p is not decision.process and c.machine_available and c.fits_envelope and p is not Process.LATHE
        ]
        de = f"Capacity Delay: {decision.process.value} derzeit nicht verfügbar, Lieferzeit +{settings.capacity_delay_days} Arbeitstage"
        en = f"Capacity Delay: {decision.process.value} currently unavailable, lead time +{settings.capacity_delay_days} business days"
        if alt:
            de += f" (Alternative prüfbar: {', '.join(alt)})"
            en += f" (alternative to evaluate: {', '.join(alt)})"
        add("CAPACITY_DELAY", "Feasible", de, en)

    if diag is not None:
        if diag.source_format == "STL":
            add(
                "MESH_INPUT",
                "Review Required",
                "STL-Netz: Bohrungen, Gewinde und Taschen nicht automatisch erkennbar - bitte STEP-Datei senden",
                "STL mesh: holes, threads and pockets cannot be recognised - please provide a STEP file",
            )
        if diag.solid_count > 1:
            add(
                "MULTI_BODY",
                "Review Required",
                f"Datei enthält {diag.solid_count} Volumenkörper - Baugruppe/Mehrteil prüfen",
                f"file contains {diag.solid_count} solids - verify assembly/multi-part scope",
            )
        if diag.brep_valid is False and diag.source_format != "STL":
            add(
                "INVALID_BREP",
                "Review Required",
                "Geometrieprüfung meldet Topologiefehler - Volumen evtl. ungenau",
                "geometry check reports topology defects - volume may be inaccurate",
            )
        if diag.max_hole_depth_to_diameter and diag.max_hole_depth_to_diameter > 10:
            add(
                "DEEP_HOLES",
                "Review Required",
                f"Tieflochbohrung (L/D {diag.max_hole_depth_to_diameter:.1f} > 10) - Sonderwerkzeug/Tiefbohren",
                f"deep-hole drilling (L/D {diag.max_hole_depth_to_diameter:.1f} > 10) - special tooling required",
            )
        if (diag.min_hole_diameter_mm is not None and diag.min_hole_diameter_mm < 1.0) or (
            diag.min_internal_radius_mm is not None and diag.min_internal_radius_mm < 0.5
        ):
            add(
                "MICRO_FEATURES",
                "Review Required",
                "Mikrobohrungen/-radien < 1 mm - Mikrozerspanung prüfen",
                "micro holes/radii below 1 mm - micro-machining review",
            )
        elif diag.min_internal_radius_mm is not None and diag.min_internal_radius_mm < 1.5:
            add(
                "SMALL_INTERNAL_RADIUS",
                "Feasible",
                f"kleiner Innenradius R{diag.min_internal_radius_mm:.2f} - Kleinstfräser, längere Bearbeitung",
                f"small internal radius R{diag.min_internal_radius_mm:.2f} - small end mills, slower machining",
            )
        if cad.features.threads and diag.thread_detection == "tap_drill_heuristic":
            add(
                "THREADS_ESTIMATED",
                "Feasible",
                f"{cad.features.threads} Gewinde anhand Kernlochdurchmesser (ISO 261) erkannt - bitte Zeichnung prüfen",
                f"{cad.features.threads} threads inferred from tap-drill diameters (ISO 261) - confirm on drawing",
            )
    elif geo.rotational_source == "heuristic" and geo.is_rotational:
        add(
            "ROTATIONAL_HEURISTIC",
            "Feasible",
            "Drehteil anhand Hüllgeometrie angenommen",
            "turned part inferred from envelope geometry",
        )

    if min(cad.bounding_box) < 1.0:
        add(
            "THIN_PART",
            "Review Required",
            "Wandstärke/Bauteildicke < 1 mm - Spann- und Verzugsrisiko",
            "wall/part thickness below 1 mm - clamping and distortion risk",
        )
    if decision.process is Process.LATHE and geo.turning_diameter and geo.turning_length:
        slenderness = geo.turning_length / geo.turning_diameter
        if slenderness > 10:
            add(
                "SLENDER_TURNING",
                "Review Required",
                f"schlankes Drehteil (L/D {slenderness:.1f}) - Lünette/Reitstock erforderlich",
                f"slender turned part (L/D {slenderness:.1f}) - steady rest/tailstock required",
            )
    if chosen is not None:
        if chosen.material.buy_to_fly_ratio > 8:
            add(
                "HIGH_BUY_TO_FLY",
                "Feasible",
                f"hoher Zerspanungsanteil (Rohteil/Fertigteil {chosen.material.buy_to_fly_ratio:.1f}) - Guss/Schmiedeteil erwägen",
                f"high buy-to-fly ratio ({chosen.material.buy_to_fly_ratio:.1f}) - consider casting/forging",
            )
        if chosen.breakdown.net_total_eur > settings.high_value_review_threshold_eur:
            add(
                "HIGH_VALUE",
                "Review Required",
                f"Auftragswert über {settings.high_value_review_threshold_eur:,.0f} EUR - kaufmännische Freigabe",
                f"order value above EUR {settings.high_value_review_threshold_eur:,.0f} - commercial sign-off",
            )
    return flags


def overall(flags: list[Flag]) -> Feasibility:
    return worst("Feasible", *(f.severity for f in flags))


def notes_from_flags(decision: RuleDecision, flags: list[Flag], chosen: ProcessCost | None) -> str:
    machine = MACHINES[decision.process]
    de = [f"Verfahren {machine.label_de} ({decision.process.value}): {decision.reasons_de[0]}."]
    en = [f"Process {machine.label_en} ({decision.process.value}): {decision.reasons_en[0]}."]
    if chosen is not None:
        t = chosen.time
        de.append(f"{t.setups} Aufspannung(en), Zyklus Erstteil {t.cycle_minutes_first_part:.0f} min.")
        en.append(f"{t.setups} set-up(s), first-article cycle {t.cycle_minutes_first_part:.0f} min.")
    for f in flags:
        de.append(f.de[0].upper() + f.de[1:] + ".")
        en.append(f.en[0].upper() + f.en[1:] + ".")
    if not flags:
        de.append("Keine Fertigungsrisiken erkannt.")
        en.append("No manufacturability risks detected.")
    return "DE: " + " ".join(de) + " | EN: " + " ".join(en)
