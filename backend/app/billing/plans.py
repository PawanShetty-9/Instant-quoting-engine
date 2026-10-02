"""Free and paid plans - the ONE place where tiers, prices, limits and features live.

Change a price, a limit or what a plan includes here; the API enforces it, the
pricing page renders it (via ``GET /api/v1/plans``) and Stripe Checkout bills it.
Nothing else in the code base hard-codes a tier.

Prices are net (excl. 19 % MwSt), in euro cents, billed monthly. They are launch
placeholders - set your own before going live.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Feature(StrEnum):
    INSTANT_PRICE = "instant_price"  # net/gross price and lead time
    VIEWER_3D = "viewer_3d"  # interactive 3D part preview
    COST_BREAKDOWN = "cost_breakdown"  # time, material, machine comparison
    AI_REVIEW = "ai_review"  # Claude reviews the quote like a senior estimator
    PRINTABLE_QUOTE = "printable_quote"  # DIN 5008 quote letter / PDF
    QUOTE_HISTORY = "quote_history"  # list of past quotes in the account
    API_ACCESS = "api_access"  # personal API key for /engine/evaluate (ERP/MES)


# Order and wording of the comparison table on the pricing page.
FEATURE_LABELS: dict[Feature, tuple[str, str]] = {
    Feature.INSTANT_PRICE: ("Sofortpreis & Lieferzeit", "Instant price & lead time"),
    Feature.VIEWER_3D: ("Interaktive 3D-Ansicht", "Interactive 3D viewer"),
    Feature.COST_BREAKDOWN: (
        "Vollständige Kalkulation & Maschinenvergleich",
        "Full cost breakdown & machine comparison",
    ),
    Feature.AI_REVIEW: ("KI-Prüfung durch Claude", "AI estimator review by Claude"),
    Feature.PRINTABLE_QUOTE: ("Druckfertiges Angebot (DIN 5008, PDF)", "Printable quote (DIN 5008, PDF)"),
    Feature.QUOTE_HISTORY: ("Angebotsverlauf", "Quote history"),
    Feature.API_ACCESS: ("API-Zugang für ERP/MES", "API access for ERP/MES"),
}


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    tagline_de: str
    tagline_en: str
    price_cents_month: int
    quotes_per_month: int | None  # None = unlimited
    max_quantity: int
    features: frozenset[Feature]
    purchasable: bool  # can be bought through Stripe Checkout

    def has(self, feature: Feature) -> bool:
        return feature in self.features

    def public_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "tagline_de": self.tagline_de,
            "tagline_en": self.tagline_en,
            "price_eur_month": self.price_cents_month / 100,
            "quotes_per_month": self.quotes_per_month,
            "max_quantity": self.max_quantity,
            "features": [f.value for f in FEATURE_LABELS if f in self.features],
            "purchasable": self.purchasable,
        }


_BASIC = frozenset({Feature.INSTANT_PRICE, Feature.VIEWER_3D})
_PRO = _BASIC | {Feature.COST_BREAKDOWN, Feature.AI_REVIEW, Feature.PRINTABLE_QUOTE, Feature.QUOTE_HISTORY}

# Visitors without an account. Not shown on the pricing page.
GUEST = Plan(
    key="guest",
    name="Gast",
    tagline_de="Ohne Anmeldung testen",
    tagline_en="Try without an account",
    price_cents_month=0,
    quotes_per_month=3,
    max_quantity=25,
    features=_BASIC,
    purchasable=False,
)

PLANS: dict[str, Plan] = {
    "free": Plan(
        key="free",
        name="Free",
        tagline_de="Für gelegentliche Anfragen",
        tagline_en="For occasional enquiries",
        price_cents_month=0,
        quotes_per_month=10,
        max_quantity=25,
        features=_BASIC,
        purchasable=False,
    ),
    "pro": Plan(
        key="pro",
        name="Pro",
        tagline_de="Für Einkäufer und Konstrukteure",
        tagline_en="For buyers and design engineers",
        price_cents_month=4900,
        quotes_per_month=200,
        max_quantity=10_000,
        features=_PRO,
        purchasable=True,
    ),
    "business": Plan(
        key="business",
        name="Business",
        tagline_de="Für Teams mit ERP-Anbindung",
        tagline_en="For teams with ERP integration",
        price_cents_month=19900,
        quotes_per_month=None,
        max_quantity=10_000,
        features=_PRO | {Feature.API_ACCESS},
        purchasable=True,
    ),
}


def plan_for(key: str | None) -> Plan:
    """Plan for an account's stored key; anonymous visitors (None) are guests."""
    if key is None:
        return GUEST
    return PLANS.get(key, PLANS["free"])
