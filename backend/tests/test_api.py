"""HTTP API behaviour, persistence and hardening."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import manual_input

ADMIN = {"X-API-Key": "test-admin-key"}


def upload(client, path, material="AL_6082_T6", **data):
    with open(path, "rb") as fh:
        return client.post(
            "/api/v1/quotes",
            files={"file": (path.name, fh, "application/octet-stream")},
            data={"material": material, **{k: str(v) for k, v in data.items()}},
        )


def test_health_and_catalogue(client):
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").json()["status"] == "ready"
    materials = client.get("/api/v1/materials").json()
    assert {"key", "name_de", "werkstoff_nr", "density_g_cm3"} <= set(materials[0])
    assert "price_eur_per_kg" not in materials[0]  # purchase prices stay internal
    caps = client.get("/api/v1/capabilities").json()
    assert {m["process"] for m in caps["machines"]} == {"CNC_3_Axis", "CNC_5_Axis", "Lathe"}


def test_upload_quote_roundtrip(client, samples):
    r = upload(client, samples["bracket"], quantity=10, customer_reference="PO-4711")
    assert r.status_code == 201, r.text
    body = r.json()
    q = body["quote"]
    assert set(q) == {
        "quote_id",
        "feasibility",
        "feasibility_notes",
        "selected_process",
        "estimated_production_time_hours",
        "cost_breakdown",
        "recommended_lead_time_days",
    }
    assert q["selected_process"] == "CNC_3_Axis"
    assert q["cost_breakdown"]["vat_19_eur"] == round(q["cost_breakdown"]["net_total_eur"] * 0.19, 2)
    assert body["engine_input"]["cad_metadata"]["features"]["holes"] == 6
    assert body["commercial"]["customer_reference"] == "PO-4711"
    assert body["commercial"]["terms_de"][0].startswith("Dieses Angebot")
    assert body["has_preview"] is True

    stored = client.get(f"/api/v1/quotes/{q['quote_id']}")
    assert stored.status_code == 200
    assert stored.json()["quote"] == q
    stl = client.get(f"/api/v1/quotes/{q['quote_id']}/preview.stl")
    assert stl.status_code == 200 and stl.headers["content-type"] == "model/stl"
    assert len(stl.content) > 84


def test_each_sample_routes_to_expected_machine(client, samples):
    expected = {"bracket": "CNC_3_Axis", "shaft": "Lathe", "manifold": "CNC_5_Axis", "blade": "CNC_5_Axis"}
    for name, process in expected.items():
        r = upload(client, samples[name], material="STEEL_C45")
        assert r.status_code == 201, r.text
        assert r.json()["quote"]["selected_process"] == process, name


def test_thread_override(client, samples):
    r = upload(client, samples["bracket"], thread_count=0)
    body = r.json()
    assert body["engine_input"]["cad_metadata"]["features"]["threads"] == 0
    assert body["engine_input"]["cad_metadata"]["diagnostics"]["thread_detection"] == "user_override"


def test_upload_validation(client, samples, tmp_path):
    assert upload(client, samples["bracket"], material="GOLD").status_code == 422
    bad = tmp_path / "evil.step"
    bad.write_bytes(b"#!/bin/sh\nrm -rf /\n")
    r = upload(client, bad)
    assert r.status_code == 422
    exe = tmp_path / "part.exe"
    exe.write_bytes(b"ISO-10303-21;")
    assert upload(client, exe).status_code == 422
    empty = tmp_path / "empty.step"
    empty.write_bytes(b"")
    assert upload(client, empty).status_code == 422


def test_upload_too_large(tmp_path, samples):
    s = Settings(environment="test", database_path=str(tmp_path / "q.db"), ai_mode="off", max_upload_mb=0.01)
    with TestClient(create_app(s)) as c:
        assert upload(c, samples["manifold"]).status_code == 413


def test_rate_limit(tmp_path, samples):
    s = Settings(environment="test", database_path=str(tmp_path / "q.db"), ai_mode="off", rate_limit_per_window=2)
    with TestClient(create_app(s)) as c:
        assert upload(c, samples["shaft"]).status_code == 201
        assert upload(c, samples["shaft"]).status_code == 201
        r = upload(c, samples["shaft"])
        assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_unknown_quote_id(client):
    assert client.get("/api/v1/quotes/AQ-20260101-ZZZZZZZZZZ").status_code == 404
    assert client.get("/api/v1/quotes/../../etc/passwd").status_code == 404
    assert client.get("/api/v1/quotes/not-an-id").status_code == 404


def test_engine_evaluate_requires_key(client):
    assert client.post("/api/v1/engine/evaluate", json=manual_input()).status_code == 401
    bad = client.post("/api/v1/engine/evaluate", json=manual_input(), headers={"X-API-Key": "nope"})
    assert bad.status_code == 401
    r = client.post("/api/v1/engine/evaluate", json=manual_input(), headers=ADMIN)
    assert r.status_code == 200
    assert r.headers["x-quote-engine"] == "rules"
    assert r.json()["selected_process"] == "CNC_3_Axis"


def test_engine_evaluate_disabled_without_key(tmp_path):
    s = Settings(environment="test", database_path=str(tmp_path / "q.db"), ai_mode="off", admin_api_key=None)
    with TestClient(create_app(s)) as c:
        assert c.post("/api/v1/engine/evaluate", json=manual_input(), headers=ADMIN).status_code == 503


def test_factory_update_drives_capacity_delay(client, samples):
    before = upload(client, samples["bracket"]).json()["quote"]
    r = client.put(
        "/api/v1/factory",
        json={
            "machine_availability": {"CNC_5_Axis": False, "CNC_3_Axis": False, "Lathe": True},
            "current_backlog_days": 10,
            "material_prices_eur_per_kg": {"AL_6082_T6": 9.0},
        },
        headers=ADMIN,
    )
    assert r.status_code == 200
    assert client.get("/api/v1/factory", headers=ADMIN).json()["factory_status"]["current_backlog_days"] == 10
    after = upload(client, samples["bracket"]).json()
    assert after["quote"]["recommended_lead_time_days"] == before["recommended_lead_time_days"] + 7 + 5
    assert "CAPACITY_DELAY" in after["analysis"]["flags"]
    assert after["engine_input"]["cost_vectors"]["material_per_kg"] == 9.0
    assert (
        client.put("/api/v1/factory", json={"material_prices_eur_per_kg": {"X": 1}}, headers=ADMIN).status_code == 422
    )


def test_security_headers(client):
    r = client.get("/api/v1/materials")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-request-id"]


def test_docs_disabled_in_production(tmp_path):
    s = Settings(environment="production", database_path=str(tmp_path / "q.db"), ai_mode="off")
    with TestClient(create_app(s)) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404


def test_client_ip_ignores_forged_forwarded_for(tmp_path, samples):
    s = Settings(
        environment="test",
        database_path=str(tmp_path / "q.db"),
        ai_mode="off",
        rate_limit_per_window=1,
        trusted_proxy_hops=1,
    )
    with TestClient(create_app(s)) as c:
        # The proxy appended the real address last; the forged first entry must not open a new bucket.
        first = {"X-Forwarded-For": "1.1.1.1, 203.0.113.7"}
        forged = {"X-Forwarded-For": "9.9.9.9, 203.0.113.7"}
        with open(samples["shaft"], "rb") as fh:
            ok = c.post(
                "/api/v1/quotes", files={"file": ("a.step", fh)}, data={"material": "AL_6082_T6"}, headers=first
            )
        assert ok.status_code == 201
        with open(samples["shaft"], "rb") as fh:
            r = c.post(
                "/api/v1/quotes", files={"file": ("a.step", fh)}, data={"material": "AL_6082_T6"}, headers=forged
            )
        assert r.status_code == 429
