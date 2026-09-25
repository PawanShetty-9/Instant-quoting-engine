"""Quote orchestration: deterministic kernel -> Claude review -> reconciliation guardrail.

Division of labour
------------------
* The **kernel** (``costing`` + ``rules``) computes every candidate process
  cent-exactly. It is the single source of truth for money and time.
* **Claude** acts as the senior estimator: it confirms or (with justification)
  overrides the machine choice among the pre-computed candidates, escalates
  feasibility for risks the rules do not capture and writes the bilingual
  DE/EN notes.
* The **guardrail** re-derives all numbers from the kernel for whatever process
  Claude selected, never lets feasibility drop below the hard-rule severity,
  and records every correction in ``analysis.validation``. A hallucinated
  figure can therefore never reach a customer-facing quote.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from app.ai.claude import AIReview, AIUnavailableError, ClaudeQuoteEngine
from app.catalog.machines import Process
from app.catalog.materials import Material, resolve_material
from app.config import Settings
from app.engine import costing
from app.engine.costing import GeometryProfile, ProcessCost
from app.engine.rules import (
    Flag,
    RuleDecision,
    assess,
    notes_from_flags,
    overall,
    profile_from_metadata,
    select_process,
    worst,
)
from app.schemas import Analysis, CadMetadata, CostBreakdown, EngineInput, EngineQuote, ProcessCandidate

log = logging.getLogger(__name__)
MONEY_TOLERANCE_EUR = 0.01


class AIRequiredError(RuntimeError):
    """AI mode is 'required' but Claude could not produce a review."""


@dataclass
class EngineResult:
    quote: EngineQuote
    analysis: Analysis
    chosen: ProcessCost | None
    material: Material | None


def _candidate_model(c: ProcessCost) -> ProcessCandidate:
    return ProcessCandidate(
        process=c.process,
        fits_envelope=c.fits_envelope,
        machine_available=c.machine_available,
        hourly_rate_eur=c.hourly_rate,
        estimated_production_time_hours=c.hours,
        cost_breakdown=c.breakdown,
        recommended_lead_time_days=c.lead_time_days,
        time_breakdown=c.time,
    )


def _zero_breakdown() -> CostBreakdown:
    return CostBreakdown(
        material_cost_eur=0.0,
        machining_cost_eur=0.0,
        energy_surcharge_eur=0.0,
        net_total_eur=0.0,
        vat_19_eur=0.0,
        gross_total_eur=0.0,
    )


def _flag_dicts(flags: list[Flag]) -> list[dict]:
    return [{"code": f.code, "severity": f.severity, "de": f.de, "en": f.en} for f in flags]


class QuoteEngine:
    def __init__(self, settings: Settings, ai: ClaudeQuoteEngine | None = None) -> None:
        self.settings = settings
        self.ai = ai

    # ------------------------------------------------------------------ kernel
    def _kernel(self, data: EngineInput):
        s = self.settings
        cad = data.cad_metadata
        geo = profile_from_metadata(cad)
        material = resolve_material(cad.requested_material)
        fits = {p: costing.fits(p, geo) for p in Process}
        decision = select_process(geo, fits)
        candidates: dict[Process, ProcessCost] = {}
        if material is not None:
            for p in Process:
                candidates[p] = costing.cost_process(
                    p, geo, material, data.cost_vectors, data.factory_status, data.order.quantity, s
                )
        return geo, material, fits, decision, candidates

    def _flags_for(self, data, geo, decision, candidates, fits, material) -> list[Flag]:
        chosen = candidates.get(decision.process)
        return assess(data.cad_metadata, geo, decision, chosen, candidates, fits, material is not None, self.settings)

    # --------------------------------------------------------------- public API
    def rule_process(self, cad: CadMetadata) -> Process:
        """Machine class chosen by rule 1 (incl. envelope fallback) - no costing needed."""
        geo = profile_from_metadata(cad)
        return select_process(geo, {p: costing.fits(p, geo) for p in Process}).process

    async def evaluate(self, data: EngineInput, quote_id: str) -> EngineResult:
        geo, material, fits, decision, candidates = self._kernel(data)
        flags = self._flags_for(data, geo, decision, candidates, fits, material)
        chosen = candidates.get(decision.process)

        rules_quote = EngineQuote(
            quote_id=quote_id,
            feasibility=overall(flags),
            feasibility_notes=notes_from_flags(decision, flags, chosen),
            selected_process=decision.process.value,
            estimated_production_time_hours=chosen.hours if chosen else 0.0,
            cost_breakdown=chosen.breakdown if chosen else _zero_breakdown(),
            recommended_lead_time_days=chosen.lead_time_days if chosen else 0,
        )
        analysis = Analysis(
            engine="rules",
            rule_based_process=decision.rule_process.value,
            flags=[f.code for f in flags],
            candidates=[_candidate_model(c) for c in candidates.values()],
            time_breakdown=chosen.time if chosen else None,
            material=chosen.material if chosen else None,
            margin_eur=chosen.margin_eur if chosen else 0.0,
        )

        use_ai = self.ai is not None and self.settings.ai_mode != "off" and material is not None
        if not use_ai:
            if self.settings.ai_mode == "required" and material is not None:
                raise AIRequiredError("AI engine required but not configured")
            return EngineResult(rules_quote, analysis, chosen, material)

        payload = self._ai_payload(data, quote_id, geo, decision, candidates, flags, material)
        try:
            review = await self.ai.review(payload)
        except AIUnavailableError as exc:
            log.warning("AI review unavailable, falling back to rules: %s", exc)
            if self.settings.ai_mode == "required":
                raise AIRequiredError(str(exc)) from exc
            analysis.validation.append(f"AI review unavailable ({exc}); deterministic rules engine used")
            return EngineResult(rules_quote, analysis, chosen, material)

        return self._reconcile(data, quote_id, review, geo, fits, decision, candidates, material, analysis)

    # ------------------------------------------------------------------ helpers
    def _ai_payload(
        self,
        data: EngineInput,
        quote_id: str,
        geo: GeometryProfile,
        decision: RuleDecision,
        candidates: dict[Process, ProcessCost],
        flags: list[Flag],
        material: Material,
    ) -> dict:
        body = data.model_dump(mode="json")
        chosen = candidates[decision.process]
        body["engine_reference"] = {
            "quote_id": quote_id,
            "rule_based_process": decision.process.value,
            "rule_reasons": decision.reasons_en,
            "candidates": [_candidate_model(c).model_dump(mode="json") for c in candidates.values()],
            "material": {
                "catalogue_key": material.key,
                "name": material.name_en,
                "werkstoff_nr": material.werkstoff_nr,
                **chosen.material.model_dump(mode="json", exclude={"key", "name"}),
            },
            "geometry_profile": {
                "is_rotational": geo.is_rotational,
                "rotational_source": geo.rotational_source,
                "multi_sided": geo.multi_sided,
                "access_directions": list(geo.access_directions),
            },
            "flags": _flag_dicts(flags),
            "vat_rate_percent": self.settings.vat_rate_percent,
            "margin_mode": self.settings.margin_mode,
            "material_basis": self.settings.material_basis,
        }
        return body

    def _reconcile(
        self,
        data: EngineInput,
        quote_id: str,
        review: AIReview,
        geo: GeometryProfile,
        fits: dict[Process, bool],
        decision: RuleDecision,
        candidates: dict[Process, ProcessCost],
        material: Material,
        analysis: Analysis,
    ) -> EngineResult:
        ai = review.quote
        v: list[str] = []

        process = decision.process
        try:
            proposed = Process(ai.selected_process)
        except ValueError:
            v.append(f"AI proposed unknown process '{ai.selected_process}'; kept {process.value}")
            proposed = process
        if proposed is not process:
            if fits[proposed]:
                v.append(f"AI re-routed {process.value} -> {proposed.value}; technical review required")
                process = proposed
            else:
                v.append(f"AI proposed {proposed.value} which does not fit the work envelope; kept {process.value}")

        final_decision = (
            decision
            if process is decision.process
            else replace(
                decision,
                process=process,
                reasons_de=[f"Umplanung durch KI-Prüfung auf {process.value}"],
                reasons_en=[f"re-routed by AI review to {process.value}"],
            )
        )
        flags = self._flags_for(data, geo, final_decision, candidates, fits, material)
        ref = candidates[process]

        diffs = {
            name: (getattr(ai.cost_breakdown, name), getattr(ref.breakdown, name))
            for name in CostBreakdown.model_fields
        }
        off = {k: a for k, (a, b) in diffs.items() if abs(a - b) > MONEY_TOLERANCE_EUR}
        if off:
            v.append(
                "AI cost figures replaced by kernel values: "
                + ", ".join(f"{k} {diffs[k][0]:.2f}->{diffs[k][1]:.2f}" for k in off)
            )
        if abs(ai.estimated_production_time_hours - ref.hours) > 0.01:
            v.append(f"AI production time {ai.estimated_production_time_hours:.2f} h replaced by {ref.hours:.2f} h")
        if ai.recommended_lead_time_days != ref.lead_time_days:
            v.append(f"AI lead time {ai.recommended_lead_time_days} d replaced by {ref.lead_time_days} d")
        if ai.quote_id != quote_id:
            v.append("AI quote_id replaced by service-issued id")

        floor = overall(flags)
        if process is not decision.rule_process:
            floor = worst(floor, "Review Required")
        feasibility = worst(ai.feasibility, floor)
        if feasibility != ai.feasibility:
            v.append(f"feasibility escalated {ai.feasibility} -> {feasibility} by hard-rule flags")

        notes = ai.feasibility_notes.strip()
        if not notes.startswith("DE:") or "| EN:" not in notes:
            v.append("AI notes not in 'DE: ... | EN: ...' form; rules notes appended")
            notes = (
                f"{notes} || {notes_from_flags(final_decision, flags, ref)}"
                if notes
                else notes_from_flags(final_decision, flags, ref)
            )
        if "CAPACITY_DELAY" in {f.code for f in flags} and "capacity delay" not in notes.lower():
            cap = next(f for f in flags if f.code == "CAPACITY_DELAY")
            notes += f" [{cap.de} / {cap.en}]"
            v.append("capacity delay notice appended")

        quote = EngineQuote(
            quote_id=quote_id,
            feasibility=feasibility,
            feasibility_notes=notes,
            selected_process=process.value,
            estimated_production_time_hours=ref.hours,
            cost_breakdown=ref.breakdown,
            recommended_lead_time_days=ref.lead_time_days,
        )
        analysis.engine = "claude"
        analysis.model = review.model
        analysis.ai_latency_ms = review.latency_ms
        analysis.flags = [f.code for f in flags]
        analysis.time_breakdown = ref.time
        analysis.material = ref.material
        analysis.margin_eur = ref.margin_eur
        analysis.validation.extend(v)
        return EngineResult(quote, analysis, ref, material)
