"""Accounts, free/paid plan gates, API keys and Stripe billing."""

from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from app.accounts import hash_password, verify_password
from app.billing.plans import GUEST, PLANS
from app.billing.stripe_client import StripeClient, sign_webhook, verify_webhook
from app.config import Settings
from app.main import create_app
from tests.conftest import manual_input, sign_in
from tests.test_api import upload

WHSEC = "whsec_test_secret"


def test_password_hashing_round_trip():
    stored = hash_password("s3cret-password")
    assert stored.startswith("scrypt$") and "s3cret" not in stored
    assert verify_password("s3cret-password", stored)
    assert not verify_password("wrong-password", stored)


def test_plans_endpoint_matches_config(guest):
    body = guest.get("/api/v1/plans").json()
    assert [p["key"] for p in body["plans"]] == list(PLANS)
    pro = next(p for p in body["plans"] if p["key"] == "pro")
    assert pro["price_eur_month"] == PLANS["pro"].price_cents_month / 100
    assert "ai_review" in pro["features"]
    assert body["checkout"] == "demo"  # no Stripe key in tests


def test_signup_login_logout(guest):
    r = guest.post("/api/v1/auth/signup", json={"email": "A@Example.com", "password": "longenough"})
    assert r.status_code == 201
    assert r.json()["account"]["email"] == "a@example.com"
    assert r.json()["account"]["plan"]["key"] == "free"
    dup = guest.post("/api/v1/auth/signup", json={"email": "a@example.com", "password": "longenough"})
    assert dup.status_code == 409
    assert guest.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "nope-nope"}).status_code == 401
    token = guest.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "longenough"}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert guest.get("/api/v1/me", headers=auth).json()["account"]["email"] == "a@example.com"
    assert guest.post("/api/v1/auth/logout", headers=auth).status_code == 204
    assert guest.get("/api/v1/me", headers=auth).status_code == 401


def test_guest_quota_and_quantity_limit(guest, samples):
    assert upload(guest, samples["shaft"], quantity=GUEST.max_quantity + 1).status_code == 402
    for _ in range(GUEST.quotes_per_month):
        assert upload(guest, samples["shaft"]).status_code == 201
    r = upload(guest, samples["shaft"])
    assert r.status_code == 402 and "free account" in r.json()["detail"]


def test_failed_upload_does_not_use_quota(guest, tmp_path):
    bad = tmp_path / "broken.step"
    bad.write_bytes(b"ISO-10303-21; not really")
    assert upload(guest, bad).status_code == 422
    assert guest.get("/api/v1/me").json()["usage"]["quotes_this_month"] == 0


def test_free_plan_hides_breakdown_paid_plan_shows_it(settings, samples):
    with TestClient(create_app(settings)) as c:
        sign_in(c, plan="free")
        free = upload(c, samples["bracket"]).json()
    assert free["entitlements"]["plan"] == "free"
    assert free["analysis"]["candidates"] == [] and free["analysis"]["material"] is None
    assert free["quote"]["cost_breakdown"]["gross_total_eur"] > 0  # the price itself is always shown
    with TestClient(create_app(settings)) as c:
        sign_in(c, plan="pro", email="pro@example.com")
        pro = upload(c, samples["bracket"]).json()
        assert len(pro["analysis"]["candidates"]) == 3
        assert c.get("/api/v1/account/quotes").json()[0]["quote_id"] == pro["quote"]["quote_id"]


def test_quote_history_requires_paid_plan(settings):
    with TestClient(create_app(settings)) as c:
        sign_in(c, plan="free")
        assert c.get("/api/v1/account/quotes").status_code == 402


def test_business_api_key_unlocks_engine_endpoint(client, settings):
    key = client.post("/api/v1/account/api-key").json()["api_key"]
    assert key.startswith("iqe_")
    with TestClient(create_app(settings)) as anon:
        r = anon.post("/api/v1/engine/evaluate", json=manual_input(), headers={"X-API-Key": key})
        assert r.status_code == 200, r.text
        assert (
            anon.post("/api/v1/engine/evaluate", json=manual_input(), headers={"X-API-Key": "iqe_x"}).status_code == 401
        )
        # Customer keys never reach the factory controls.
        assert anon.get("/api/v1/factory", headers={"X-API-Key": key}).status_code == 401


def test_pro_cannot_create_api_key(settings):
    with TestClient(create_app(settings)) as c:
        sign_in(c, plan="pro")
        assert c.post("/api/v1/account/api-key").status_code == 402


def test_demo_checkout_upgrades_without_stripe(settings):
    with TestClient(create_app(settings)) as c:
        sign_in(c, plan="free")
        r = c.post("/api/v1/billing/checkout", json={"plan": "pro"})
        assert r.status_code == 200 and r.json()["mode"] == "demo"
        assert c.get("/api/v1/me").json()["plan"]["key"] == "pro"
        assert c.post("/api/v1/billing/checkout", json={"plan": "free"}).status_code == 422


def test_checkout_disabled_in_production_without_stripe(tmp_path):
    s = Settings(environment="production", database_path=str(tmp_path / "q.db"), ai_mode="off")
    with TestClient(create_app(s)) as c:
        sign_in(c, plan="free")
        assert c.post("/api/v1/billing/checkout", json={"plan": "pro"}).status_code == 503


def test_stripe_checkout_request(settings):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"})

    s = Settings(**{**settings.model_dump(), "stripe_secret_key": "sk_test_123"})
    stripe = StripeClient(s, transport=httpx.MockTransport(handler))
    with TestClient(create_app(s, stripe=stripe)) as c:
        account = sign_in(c, plan="free")["account"]
        r = c.post("/api/v1/billing/checkout", json={"plan": "business"})
    assert r.json() == {"url": "https://checkout.stripe.com/c/pay/cs_test_1", "mode": "stripe"}
    form = dict(httpx.QueryParams(seen[0].content.decode()))
    assert seen[0].url.path == "/v1/checkout/sessions"
    assert form["mode"] == "subscription"
    assert form["client_reference_id"] == account["id"]
    assert form["line_items[0][price_data][unit_amount]"] == str(PLANS["business"].price_cents_month)
    assert form["line_items[0][price_data][currency]"] == "eur"


def test_webhook_signature_is_checked():
    payload = b'{"type": "ping"}'
    assert verify_webhook(payload, sign_webhook(payload, WHSEC), WHSEC)["type"] == "ping"
    for header in ("", "t=1,v1=deadbeef", sign_webhook(payload, "whsec_other")):
        try:
            verify_webhook(payload, header, WHSEC)
        except Exception:  # noqa: BLE001
            continue
        raise AssertionError(f"accepted bad signature {header!r}")
    old = sign_webhook(payload, WHSEC, timestamp=1_000)
    try:
        verify_webhook(payload, old, WHSEC)
        raise AssertionError("accepted replayed event")
    except Exception as exc:  # noqa: BLE001
        assert "tolerance" in str(exc)


def test_webhook_upgrades_and_downgrades(settings):
    s = Settings(**{**settings.model_dump(), "stripe_webhook_secret": WHSEC})
    with TestClient(create_app(s)) as c:
        account_id = sign_in(c, plan="free")["account"]["id"]

        def send(event: dict) -> int:
            body = json.dumps(event).encode()
            return c.post(
                "/api/v1/billing/webhook", content=body, headers={"Stripe-Signature": sign_webhook(body, WHSEC)}
            ).status_code

        assert (
            c.post("/api/v1/billing/webhook", content=b"{}", headers={"Stripe-Signature": "t=1,v1=x"}).status_code
            == 400
        )
        completed = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": account_id,
                    "customer": "cus_1",
                    "subscription": "sub_1",
                    "metadata": {"plan": "pro"},
                }
            },
        }
        assert send(completed) == 200
        assert c.get("/api/v1/me").json()["plan"]["key"] == "pro"
        deleted = {"type": "customer.subscription.deleted", "data": {"object": {"id": "sub_1", "customer": "cus_1"}}}
        assert send(deleted) == 200
        assert c.get("/api/v1/me").json()["plan"]["key"] == "free"
