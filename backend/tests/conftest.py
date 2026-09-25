from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai.claude import ClaudeQuoteEngine
from app.config import Settings
from app.main import create_app
from app.schemas import EngineQuote
from scripts.generate_samples import PARTS, write_step


@pytest.fixture(scope="session")
def samples(tmp_path_factory) -> dict[str, Path]:
    out = tmp_path_factory.mktemp("samples")
    paths = {}
    for name, build in PARTS.items():
        path = out / f"{name}.step"
        write_step(build(), path)
        paths[name] = path
    return paths


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        environment="test",
        database_path=str(tmp_path / "quotes.sqlite3"),
        ai_mode="off",
        admin_api_key="test-admin-key",
        rate_limit_per_window=1000,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


class FakeMessages:
    """Stands in for ``AsyncAnthropic().beta.messages`` and records every call."""

    def __init__(self, respond):
        self.respond = respond
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        payload = json.loads(kwargs["messages"][0]["content"])
        result = self.respond(payload)
        if isinstance(result, Exception):
            raise result
        if isinstance(result, SimpleNamespace):
            return result
        return SimpleNamespace(
            stop_reason="end_turn",
            stop_details=None,
            parsed_output=EngineQuote.model_validate(result),
            model="claude-opus-5",
            usage=SimpleNamespace(input_tokens=1000, output_tokens=300, cache_read_input_tokens=0),
            _request_id="req_test",
        )


def fake_ai(settings: Settings, respond) -> tuple[ClaudeQuoteEngine, FakeMessages]:
    messages = FakeMessages(respond)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return ClaudeQuoteEngine(settings, client=client), messages


def echo_reference(payload: dict, **overrides) -> dict:
    """A well-behaved model: copies the kernel's candidate for the rule-based process."""
    ref = payload["engine_reference"]
    process = overrides.pop("selected_process", ref["rule_based_process"])
    cand = next(c for c in ref["candidates"] if c["process"] == process)
    quote = {
        "quote_id": ref["quote_id"],
        "feasibility": "Feasible",
        "feasibility_notes": "DE: Fräsbearbeitung auf 3-Achs-BAZ. | EN: Milling on a 3-axis machining centre.",
        "selected_process": process,
        "estimated_production_time_hours": cand["estimated_production_time_hours"],
        "cost_breakdown": cand["cost_breakdown"],
        "recommended_lead_time_days": cand["recommended_lead_time_days"],
    }
    quote.update(overrides)
    return quote


def manual_input(**overrides) -> dict:
    """Engine-contract payload in exactly the documented input shape."""
    body = {
        "cad_metadata": {
            "bounding_box": [100.0, 60.0, 20.0],
            "volume_cm3": 100.0,
            "surface_area_cm2": 200.0,
            "features": {"holes": 4, "threads": 2, "pockets": 1, "complex_curves": 0},
            "requested_material": "Aluminium 6082",
        },
        "factory_status": {
            "machine_availability": {"CNC_5_Axis": True, "CNC_3_Axis": True, "Lathe": True},
            "current_backlog_days": 3,
        },
        "cost_vectors": {
            "material_per_kg": 7.5,
            "machine_hourly_rate": 85.0,
            "energy_surcharge_percent": 4.0,
            "target_margin_percent": 15.0,
        },
    }
    for key, value in overrides.items():
        section, _, field = key.partition("__")
        if field:
            body[section][field] = value
        else:
            body[section] = value
    return body
