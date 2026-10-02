"""Minimal Stripe integration: Checkout, Customer Portal and webhook verification.

Talks to the Stripe REST API with ``httpx`` instead of the SDK so every request is
visible in one file. Prices are sent inline (``price_data``) from ``plans.py``, so no
products or prices have to be created in the Stripe dashboard - a test-mode secret
key (``sk_test_...``) is all that is needed to try the full flow.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import httpx

from app.billing.plans import Plan
from app.config import Settings

API = "https://api.stripe.com/v1"
SIGNATURE_TOLERANCE_S = 300


class StripeError(RuntimeError):
    """Stripe rejected a request or is not configured."""


@dataclass(frozen=True)
class CheckoutLink:
    id: str
    url: str


class StripeClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        key = settings.stripe_secret_key
        self._client = (
            httpx.Client(base_url=API, auth=(key.get_secret_value(), ""), timeout=20.0, transport=transport)
            if key
            else None
        )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def live_mode(self) -> bool:
        key = self.settings.stripe_secret_key
        return bool(key and key.get_secret_value().startswith("sk_live_"))

    def _post(self, path: str, form: dict[str, str]) -> dict:
        if self._client is None:
            raise StripeError("payments not configured (QUOTE_STRIPE_SECRET_KEY not set)")
        res = self._client.post(path, data=form)
        body = res.json()
        if res.status_code >= 400:
            raise StripeError(body.get("error", {}).get("message", f"Stripe HTTP {res.status_code}"))
        return body

    def create_checkout(self, plan: Plan, account_id: str, email: str, customer_id: str | None) -> CheckoutLink:
        """Subscription checkout for ``plan``; the webhook upgrades the account on success."""
        base = self.settings.public_app_url.rstrip("/")
        form = {
            "mode": "subscription",
            "success_url": f"{base}/account?checkout=success",
            "cancel_url": f"{base}/pricing?checkout=cancelled",
            "client_reference_id": account_id,
            "metadata[account_id]": account_id,
            "metadata[plan]": plan.key,
            "subscription_data[metadata][account_id]": account_id,
            "subscription_data[metadata][plan]": plan.key,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": "eur",
            "line_items[0][price_data][unit_amount]": str(plan.price_cents_month),
            "line_items[0][price_data][recurring][interval]": "month",
            "line_items[0][price_data][tax_behavior]": "exclusive",
            "line_items[0][price_data][product_data][name]": f"Instant Quoting {plan.name}",
            "allow_promotion_codes": "true",
            "billing_address_collection": "required",
            "tax_id_collection[enabled]": "true",  # B2B: collect the customer's USt-IdNr.
        }
        if self.settings.stripe_automatic_tax:  # needs Stripe Tax activated in the dashboard
            form["automatic_tax[enabled]"] = "true"
        if customer_id:
            form["customer"] = customer_id
            form["customer_update[name]"] = "auto"
            form["customer_update[address]"] = "auto"
        else:
            form["customer_email"] = email
        session = self._post("/checkout/sessions", form)
        return CheckoutLink(id=session["id"], url=session["url"])

    def create_portal(self, customer_id: str) -> str:
        """Stripe-hosted page where a customer changes card, plan or cancels."""
        base = self.settings.public_app_url.rstrip("/")
        return self._post("/billing_portal/sessions", {"customer": customer_id, "return_url": f"{base}/account"})["url"]


def verify_webhook(payload: bytes, signature_header: str, secret: str, now: float | None = None) -> dict:
    """Check a ``Stripe-Signature`` header and return the parsed event.

    Implements https://docs.stripe.com/webhooks#verify-manually: HMAC-SHA256 over
    ``"{timestamp}.{payload}"`` with the endpoint secret, plus a replay window.
    """
    parts: dict[str, list[str]] = {}
    for item in signature_header.split(","):
        k, _, v = item.strip().partition("=")
        parts.setdefault(k, []).append(v)
    try:
        timestamp = int(parts["t"][0])
    except (KeyError, ValueError) as exc:
        raise StripeError("malformed Stripe-Signature header") from exc
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", [])):
        raise StripeError("invalid webhook signature")
    if abs((now or time.time()) - timestamp) > SIGNATURE_TOLERANCE_S:
        raise StripeError("webhook timestamp outside tolerance")
    return json.loads(payload)


def sign_webhook(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Build a valid ``Stripe-Signature`` header (used by tests and local replays)."""
    t = timestamp or int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={sig}"
