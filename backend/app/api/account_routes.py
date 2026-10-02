"""HTTP API (v1): plans, sign-up/sign-in, account and Stripe billing."""

from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from app.accounts import (
    DUMMY_HASH,
    Viewer,
    current_viewer,
    hash_password,
    new_account_id,
    new_token,
    require_account,
    token_hash,
    verify_password,
)
from app.billing.plans import FEATURE_LABELS, PLANS, Feature, Plan
from app.billing.stripe_client import StripeClient, StripeError, verify_webhook
from app.config import Settings, get_settings
from app.storage import Account, Store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_stripe(request: Request) -> StripeClient:
    return request.app.state.stripe


# ----------------------------------------------------------------------- models
class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("invalid e-mail address")
        return v


class SignUp(Credentials):
    company: str | None = Field(default=None, max_length=120)


class CheckoutRequest(BaseModel):
    plan: str


def account_view(account: Account, plan: Plan, used: int) -> dict:
    return {
        "id": account.id,
        "email": account.email,
        "company": account.company,
        "created_at": account.created_at,
        "plan": plan.public_dict(),
        "usage": {"quotes_this_month": used, "quotes_per_month": plan.quotes_per_month},
        "has_api_key": account.has_api_key,
        "has_billing": account.stripe_customer_id is not None,
    }


def _session_response(store: Store, account: Account) -> dict:
    token = new_token("sess")
    store.create_session(token_hash(token), account.id)
    plan = PLANS.get(account.plan, PLANS["free"])
    return {"token": token, "account": account_view(account, plan, store.quotes_used(account.id))}


# ------------------------------------------------------------------------ plans
@router.get("/plans", summary="Free and paid plans with prices, limits and features (public)")
def list_plans(stripe: StripeClient = Depends(get_stripe), settings: Settings = Depends(get_settings)) -> dict:
    return {
        "currency": "EUR",
        "vat_note": "Preise zzgl. 19 % MwSt. / Prices excl. 19 % VAT",
        "features": [{"key": f.value, "de": de, "en": en} for f, (de, en) in FEATURE_LABELS.items()],
        "plans": [p.public_dict() for p in PLANS.values()],
        "checkout": "stripe" if stripe.enabled else ("demo" if settings.billing_demo_active else "disabled"),
    }


# ------------------------------------------------------------------------- auth
@router.post("/auth/signup", status_code=status.HTTP_201_CREATED, summary="Create a free account")
async def signup(body: SignUp, store: Store = Depends(get_store)) -> dict:
    pw_hash = await asyncio.to_thread(hash_password, body.password)
    account = store.create_account(new_account_id(), body.email, pw_hash, (body.company or "").strip() or None)
    if account is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "an account with this e-mail already exists")
    log.info("account %s created", account.id)
    return _session_response(store, account)


@router.post("/auth/login", summary="Sign in and receive a session token")
async def login(body: Credentials, store: Store = Depends(get_store)) -> dict:
    found = store.password_hash_for(body.email)
    stored = found[1] if found else DUMMY_HASH
    ok = await asyncio.to_thread(verify_password, body.password, stored)
    account = store.get_account(found[0]) if found and ok else None
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong e-mail or password")
    return _session_response(store, account)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End the current session")
def logout(request: Request, store: Store = Depends(get_store), _: Viewer = Depends(require_account)) -> None:
    store.delete_session(token_hash(request.headers["Authorization"].partition(" ")[2]))


# ---------------------------------------------------------------------- account
@router.get("/me", summary="Who am I: plan, usage and entitlements (works for guests too)")
def me(viewer: Viewer = Depends(current_viewer), store: Store = Depends(get_store)) -> dict:
    used = store.quotes_used(viewer.subject)
    return {
        "account": account_view(viewer.account, viewer.plan, used) if viewer.account else None,
        "plan": viewer.plan.public_dict(),
        "usage": {"quotes_this_month": used, "quotes_per_month": viewer.plan.quotes_per_month},
    }


@router.get("/account/quotes", summary="Quote history (Pro and Business)")
def quote_history(viewer: Viewer = Depends(require_account), store: Store = Depends(get_store)) -> list[dict]:
    if not viewer.plan.has(Feature.QUOTE_HISTORY):
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "quote history is part of the Pro plan")
    return store.list_quotes(viewer.account.id)


@router.post("/account/api-key", summary="Create or rotate the personal API key (Business)")
def rotate_api_key(viewer: Viewer = Depends(require_account), store: Store = Depends(get_store)) -> dict:
    if not viewer.plan.has(Feature.API_ACCESS):
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "API access is part of the Business plan")
    key = new_token("iqe")
    store.update_account(viewer.account.id, api_key_hash=token_hash(key))
    return {"api_key": key, "note": "Shown once. Send it as the X-API-Key header to /api/v1/engine/evaluate."}


# ---------------------------------------------------------------------- billing
@router.post("/billing/checkout", summary="Start a Stripe Checkout for a paid plan")
def checkout(
    body: CheckoutRequest,
    viewer: Viewer = Depends(require_account),
    store: Store = Depends(get_store),
    stripe: StripeClient = Depends(get_stripe),
    settings: Settings = Depends(get_settings),
) -> dict:
    plan = PLANS.get(body.plan)
    if plan is None or not plan.purchasable:
        raise HTTPException(422, f"plan '{body.plan}' cannot be purchased")
    account = viewer.account
    if account.stripe_subscription_id:
        # One subscription per account: plan changes go through the Stripe portal.
        raise HTTPException(status.HTTP_409_CONFLICT, "you already have a subscription - change it in billing")
    if not stripe.enabled:
        if not settings.billing_demo_active:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "payments are not configured yet")
        # Local demo: no card, no Stripe - switch the plan straight away.
        store.update_account(account.id, plan=plan.key)
        log.warning("billing demo mode: account %s switched to %s without payment", account.id, plan.key)
        return {"url": f"{settings.public_app_url.rstrip('/')}/account?checkout=demo", "mode": "demo"}
    try:
        link = stripe.create_checkout(plan, account.id, account.email, account.stripe_customer_id)
    except StripeError as exc:
        log.error("stripe checkout failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "payment provider error, please try again") from exc
    return {"url": link.url, "mode": "stripe"}


@router.post("/billing/portal", summary="Open the Stripe customer portal (change card, cancel)")
def billing_portal(viewer: Viewer = Depends(require_account), stripe: StripeClient = Depends(get_stripe)) -> dict:
    if not viewer.account.stripe_customer_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "no paid subscription yet")
    try:
        return {"url": stripe.create_portal(viewer.account.stripe_customer_id)}
    except StripeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "payment provider error, please try again") from exc


# Subscription states in which the customer keeps the paid plan.
_ACTIVE = {"active", "trialing", "past_due"}


@router.post("/billing/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, settings: Settings = Depends(get_settings)) -> dict:
    """Stripe -> us. The only place a plan is upgraded or downgraded after payment."""
    secret = settings.stripe_webhook_secret
    if secret is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook secret not configured")
    payload = await request.body()
    try:
        event = verify_webhook(payload, request.headers.get("Stripe-Signature", ""), secret.get_secret_value())
    except StripeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    apply_stripe_event(request.app.state.store, event)
    return {"received": True}


def apply_stripe_event(store: Store, event: dict) -> None:
    kind = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    if kind == "checkout.session.completed":
        account_id = obj.get("client_reference_id") or obj.get("metadata", {}).get("account_id")
        plan = obj.get("metadata", {}).get("plan")
        if account_id and plan in PLANS and store.get_account(account_id):
            store.update_account(
                account_id,
                plan=plan,
                stripe_customer_id=obj.get("customer"),
                stripe_subscription_id=obj.get("subscription"),
            )
            log.info("account %s upgraded to %s", account_id, plan)
    elif kind in ("customer.subscription.updated", "customer.subscription.deleted"):
        account = store.account_by_stripe_customer(obj.get("customer", ""))
        if account is None or obj.get("id") != account.stripe_subscription_id:
            return  # unknown customer, or an old subscription that no longer drives the plan
        plan = obj.get("metadata", {}).get("plan")
        if kind == "customer.subscription.deleted" or obj.get("status") not in _ACTIVE:
            store.update_account(account.id, plan="free", stripe_subscription_id=None)
            log.info("account %s downgraded to free (%s)", account.id, obj.get("status", kind))
        elif plan in PLANS:
            store.update_account(account.id, plan=plan)
