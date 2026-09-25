"""Claude integration: request shape, reconciliation guardrail and fallbacks."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.engine.quote import AIRequiredError, QuoteEngine
from app.main import create_app
from app.schemas import EngineInput
from tests.conftest import echo_reference, fake_ai, manual_input

QID = "AQ-20260101-TEST000000"


def evaluate(respond, body=None, **settings_kw):
    s = Settings(_env_file=None, **settings_kw)
    ai, calls = fake_ai(s, respond)
    engine = QuoteEngine(s, ai)
    result = asyncio.run(engine.evaluate(EngineInput.model_validate(body or manual_input()), QID))
    return result, calls


def test_request_shape():
    result, calls = evaluate(echo_reference)
    kw = calls.calls[0]
    assert kw["model"] == "claude-opus-5"
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    assert kw["output_format"].__name__ == "EngineQuote"
    assert result.analysis.engine == "claude"
    assert result.analysis.validation == []
    assert result.quote.feasibility_notes.startswith("DE:")


def test_payload_contains_contract_and_reference_only():
    _, calls = evaluate(echo_reference)
    import json

    payload = json.loads(calls.calls[0]["messages"][0]["content"])
    assert set(payload) == {"cad_metadata", "factory_status", "cost_vectors", "order", "engine_reference"}
    ref = payload["engine_reference"]
    assert ref["quote_id"] == QID
    assert {c["process"] for c in ref["candidates"]} == {"CNC_3_Axis", "CNC_5_Axis", "Lathe"}


def test_hallucinated_numbers_are_replaced():
    def liar(payload):
        q = echo_reference(payload)
        q["cost_breakdown"] = {k: v * 0.5 for k, v in q["cost_breakdown"].items()}
        q["estimated_production_time_hours"] = 0.1
        q["recommended_lead_time_days"] = 1
        q["quote_id"] = "made-up"
        return q

    result, _ = evaluate(liar)
    rules = asyncio.run(QuoteEngine(Settings(_env_file=None)).evaluate(EngineInput.model_validate(manual_input()), QID))
    assert result.quote.cost_breakdown == rules.quote.cost_breakdown
    assert result.quote.estimated_production_time_hours == rules.quote.estimated_production_time_hours
    assert result.quote.recommended_lead_time_days == rules.quote.recommended_lead_time_days
    assert result.quote.quote_id == QID
    assert any("replaced by kernel values" in v for v in result.analysis.validation)


def test_ai_can_escalate_but_not_downgrade():
    escalate, _ = evaluate(lambda p: echo_reference(p, feasibility="Review Required"))
    assert escalate.quote.feasibility == "Review Required"

    body = manual_input()
    body["cad_metadata"]["requested_material"] = "AL_6082_T6"
    body["cad_metadata"].update(bounding_box=[600.0, 600.0, 50.0], volume_cm3=9000.0, surface_area_cm2=8000.0)
    downgrade, _ = evaluate(lambda p: echo_reference(p, feasibility="Feasible"), body=body)
    assert downgrade.quote.feasibility == "Review Required"  # ENVELOPE_REROUTE is a hard flag
    assert any("escalated" in v for v in downgrade.analysis.validation)


def test_ai_reroute_is_accepted_but_forces_review():
    result, _ = evaluate(lambda p: echo_reference(p, selected_process="CNC_5_Axis"))
    assert result.quote.selected_process == "CNC_5_Axis"
    assert result.quote.feasibility == "Review Required"
    five = next(c for c in result.analysis.candidates if c.process == "CNC_5_Axis")
    assert result.quote.cost_breakdown == five.cost_breakdown


def test_ai_reroute_to_non_fitting_machine_is_rejected():
    body = manual_input()
    body["cad_metadata"].update(bounding_box=[900.0, 400.0, 100.0], volume_cm3=20000.0, surface_area_cm2=12000.0)

    def pick_5(p):
        q = echo_reference(p)
        q["selected_process"] = "CNC_5_Axis"  # 900 mm does not fit the 650 mm 5-axis table
        return q

    result, _ = evaluate(pick_5, body=body)
    assert result.quote.selected_process == "CNC_3_Axis"
    assert any("does not fit" in v for v in result.analysis.validation)


def test_capacity_delay_notice_enforced():
    body = manual_input()
    body["factory_status"]["machine_availability"]["CNC_3_Axis"] = False
    result, _ = evaluate(echo_reference, body=body)
    assert "Capacity Delay" in result.quote.feasibility_notes


def test_refusal_falls_back_to_rules():
    refusal = SimpleNamespace(
        stop_reason="refusal",
        stop_details=SimpleNamespace(category="cyber"),
        parsed_output=None,
        model="claude-opus-5",
        usage=None,
        _request_id="r",
    )
    result, _ = evaluate(lambda p: refusal)
    assert result.analysis.engine == "rules"
    assert any("declined" in v for v in result.analysis.validation)


def test_api_error_falls_back_or_raises_when_required():
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.InternalServerError("boom", response=httpx2.Response(500, request=req), body=None)
    result, _ = evaluate(lambda p: err)
    assert result.analysis.engine == "rules"
    with pytest.raises(AIRequiredError):
        evaluate(lambda p: err, ai_mode="required")


def test_upload_uses_ai_and_hides_file_identity(tmp_path, samples):
    s = Settings(environment="test", database_path=str(tmp_path / "q.db"), ai_mode="auto", rate_limit_per_window=100)
    ai, calls = fake_ai(s, echo_reference)
    with TestClient(create_app(s, ai_engine=ai)) as c, open(samples["bracket"], "rb") as fh:
        r = c.post(
            "/api/v1/quotes",
            files={"file": ("secret-customer-part.step", fh)},
            data={"material": "AL_6082_T6", "customer_reference": "ACME-PO-99"},
        )
    assert r.status_code == 201, r.text
    assert r.json()["analysis"]["engine"] == "claude"
    sent = calls.calls[0]["messages"][0]["content"]
    assert "secret-customer-part" not in sent and "ACME-PO-99" not in sent


def test_blank_api_key_disables_ai(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("QUOTE_ADMIN_API_KEY", "  ")
    s = Settings(_env_file=None)
    assert s.anthropic_api_key is None and s.admin_api_key is None
    assert s.ai_enabled is False


def test_unexpected_client_error_falls_back_to_rules():
    result, _ = evaluate(lambda p: TypeError("Could not resolve authentication method"))
    assert result.analysis.engine == "rules"
    assert any("TypeError" in v for v in result.analysis.validation)
