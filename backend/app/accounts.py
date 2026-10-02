"""Customer accounts: password hashing, session tokens, API keys and the request's plan.

* Passwords are hashed with scrypt (stdlib, memory-hard), never stored in clear.
* Session tokens and API keys are random 256-bit strings; only their SHA-256 is
  stored, so a database leak does not leak working credentials.
* ``current_viewer`` resolves who is calling (account or guest) and which plan
  applies. Every feature gate in the API reads from that one object.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.billing.plans import Feature, Plan, plan_for
from app.config import Settings, get_settings
from app.security import client_ip, require_api_key
from app.storage import Account, Store

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
_bearer = HTTPBearer(auto_error=False)


# ------------------------------------------------------------------ secrets
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), dklen=32, **_SCRYPT)
    return hmac.compare_digest(digest.hex(), digest_hex)


# A real hash to compare against when the e-mail is unknown, so login timing does not
# reveal which addresses have accounts.
DUMMY_HASH = hash_password(secrets.token_hex(8))


API_KEY_PREFIX = "iqe_"  # customer API keys; anything else is checked against the admin key


def new_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_account_id() -> str:
    return "acc_" + secrets.token_hex(8)


# ------------------------------------------------------------------- viewer
@dataclass(frozen=True)
class Viewer:
    """Who is making the request and what their plan allows."""

    account: Account | None
    plan: Plan
    # Quota subject: the account id, or a hash of the guest's IP address (no raw IPs stored).
    subject: str

    @property
    def is_guest(self) -> bool:
        return self.account is None


def _store(request: Request) -> Store:
    return request.app.state.store


def current_viewer(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Viewer:
    """Optional auth: a valid Bearer session token -> account, otherwise guest.

    A token that is present but invalid/expired is rejected with 401 so the web app can
    drop it and ask the user to sign in again, instead of silently downgrading them.
    """
    if creds is not None:
        account = _store(request).account_for_session(token_hash(creds.credentials))
        if account is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired - please sign in again")
        return Viewer(account=account, plan=plan_for(account.plan), subject=account.id)
    guest = "guest:" + hashlib.sha256(client_ip(request).encode()).hexdigest()[:24]
    return Viewer(account=None, plan=plan_for(None), subject=guest)


def require_account(viewer: Viewer = Depends(current_viewer)) -> Viewer:
    if viewer.account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in required", headers={"WWW-Authenticate": "Bearer"})
    return viewer


def require_engine_access(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Integration endpoint: the operator's admin key, or a Business customer's API key.

    Factory endpoints stay admin-only (``security.require_api_key``); customers may only
    evaluate quotes.
    """
    key = request.headers.get("X-API-Key") or ""
    if key.startswith(API_KEY_PREFIX):
        account = _store(request).account_by_api_key(token_hash(key))
        if account is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key", headers={"WWW-Authenticate": "ApiKey"})
        if not plan_for(account.plan).has(Feature.API_ACCESS):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "API access requires the Business plan")
        return
    require_api_key(key or None, settings)
