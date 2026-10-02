"""Runtime configuration (12-factor: everything comes from environment variables)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QUOTE_", env_file=".env", extra="ignore")

    # --- service -----------------------------------------------------------------
    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    database_path: str = "./data/quotes.sqlite3"
    quote_retention_days: int = Field(default=90, ge=1)
    admin_api_key: SecretStr | None = None
    # Reverse proxies in front of the API that append to X-Forwarded-For (Caddy, Render: 1).
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)

    # --- accounts & billing ------------------------------------------------------
    # Public URL of the web app; Stripe redirects back here after checkout.
    public_app_url: str = "http://localhost:3000"
    session_ttl_days: int = Field(default=30, ge=1)
    stripe_secret_key: SecretStr | None = None  # sk_test_... for test mode
    stripe_webhook_secret: SecretStr | None = None  # whsec_...
    stripe_automatic_tax: bool = False
    # Without Stripe keys, upgrade instantly on "checkout" so the paid flow can be tried
    # locally. Never active in production.
    billing_demo_mode: bool = True

    # --- upload hardening ----------------------------------------------------------
    max_upload_mb: float = Field(default=25.0, gt=0)
    parse_timeout_s: float = Field(default=45.0, gt=0)
    parse_memory_limit_mb: int = Field(default=2048, ge=256)
    max_concurrent_parses: int = Field(default=2, ge=1)
    rate_limit_per_window: int = Field(default=20, ge=1)
    rate_limit_window_s: int = Field(default=600, ge=1)
    preview_max_triangles: int = Field(default=150_000, ge=1_000)

    # --- AI engine -------------------------------------------------------------------
    ai_mode: Literal["auto", "off", "required"] = "auto"
    # Read without prefix so the standard Anthropic variable works out of the box.
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    anthropic_model: str = "claude-opus-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    anthropic_timeout_s: float = Field(default=90.0, gt=0)
    anthropic_server_fallbacks: bool = True

    # --- costing model -------------------------------------------------------------
    base_setup_minutes: float = 45.0
    additional_setup_minutes: float = 20.0
    hole_penalty_minutes: float = 5.0
    thread_penalty_minutes: float = 5.0
    pocket_penalty_minutes: float = 15.0
    complex_curve_penalty_minutes: float = 30.0
    # Feature time for parts 2..n as a share of the first-article time (CAM, prove-out).
    series_feature_factor: float = Field(default=0.3, ge=0, le=1)
    stock_allowance_mill_mm: float = 3.0
    stock_allowance_lathe_diameter_mm: float = 4.0
    stock_allowance_lathe_length_mm: float = 5.0
    # "stock" = raw blank incl. allowance (what the shop actually buys and pays for);
    # "part" = original contract formula on finished-part volume (underprices pockets/blades).
    material_basis: Literal["part", "stock"] = "stock"
    # "markup" = Gewinnzuschlag on cost; "margin" = share of the net price.
    margin_mode: Literal["markup", "margin"] = "markup"
    vat_rate_percent: float = 19.0
    productive_hours_per_day: float = Field(default=16.0, gt=0)
    qa_and_shipping_days: int = 2
    capacity_delay_days: int = 5
    quote_validity_days: int = 30
    high_value_review_threshold_eur: float = 25_000.0

    # --- factory defaults (overridable at runtime via PUT /api/v1/factory) -------------
    default_backlog_days: int = 3
    default_energy_surcharge_percent: float = 4.0
    default_target_margin_percent: float = 15.0
    rate_cnc_3_axis_eur_h: float = 85.0
    rate_cnc_5_axis_eur_h: float = 110.0
    rate_lathe_eur_h: float = 75.0

    # --- supplier master data printed on the quote (placeholders!) -----------------
    company_name: str = "Musterfertigung GmbH"
    company_street: str = "Industriestraße 1"
    company_city: str = "38440 Wolfsburg"
    company_country: str = "Deutschland"
    company_email: str = "angebote@musterfertigung.example"
    company_phone: str = "+49 5361 000000"
    company_vat_id: str = "DE000000000"
    company_register: str = "Amtsgericht Braunschweig HRB 000000"
    company_managing_director: str = "Max Mustermann"

    @field_validator("anthropic_api_key", "admin_api_key", "stripe_secret_key", "stripe_webhook_secret", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, v: object) -> object:
        # `ANTHROPIC_API_KEY=` in an env file means "not configured", not "empty key".
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v

    @property
    def billing_demo_active(self) -> bool:
        return self.billing_demo_mode and self.environment != "production" and self.stripe_secret_key is None

    @property
    def ai_enabled(self) -> bool:
        return self.ai_mode != "off" and self.anthropic_api_key is not None


@lru_cache
def get_settings() -> Settings:
    return Settings()
