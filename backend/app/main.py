"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.ai.claude import ClaudeQuoteEngine
from app.api.routes import router
from app.config import Settings, get_settings
from app.engine.quote import QuoteEngine
from app.security import SecurityHeadersMiddleware, SlidingWindowRateLimiter
from app.storage import Store

log = logging.getLogger("quote")


def create_app(settings: Settings | None = None, ai_engine: ClaudeQuoteEngine | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(settings)
        purged = store.purge_expired()
        ai = ai_engine
        if ai is None and settings.ai_enabled:
            ai = ClaudeQuoteEngine(settings)
        app.state.store = store
        app.state.engine = QuoteEngine(settings, ai)
        app.state.rate_limiter = SlidingWindowRateLimiter(settings.rate_limit_per_window, settings.rate_limit_window_s)
        app.state.parse_semaphore = asyncio.Semaphore(settings.max_concurrent_parses)
        log.info(
            "quoting engine ready (engine=%s, model=%s, purged=%d expired quotes)",
            "claude" if ai else "rules",
            settings.anthropic_model if ai else "-",
            purged,
        )
        yield
        store.close()

    docs = settings.environment != "production"
    app = FastAPI(
        title="Instant Quoting Engine",
        version=__version__,
        summary="STEP upload -> machine selection, lead time and VAT-compliant quote for CNC contract manufacturing",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Quote-Engine"],
        max_age=600,
    )
    app.include_router(router)
    # Routes and auth resolve settings through this dependency; bind it to this app's instance.
    app.dependency_overrides[get_settings] = lambda: settings

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> JSONResponse:
        try:
            import OCP.STEPControl  # noqa: F401 - CAD kernel importable

            app.state.store.get_factory()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"status": "unavailable", "reason": type(exc).__name__}, status_code=503)
        return JSONResponse({"status": "ready", "ai_enabled": app.state.engine.ai is not None})

    return app


app = create_app()
