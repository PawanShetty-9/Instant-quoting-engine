"""Anthropic Claude client for the quoting engine.

Only derived numeric metadata is sent to the API - never the CAD file itself,
file names or customer references (trade-secret protection, GDPR data
minimisation).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import anthropic

from app.ai.prompt import SYSTEM_PROMPT
from app.config import Settings
from app.schemas import EngineQuote

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIUnavailableError(RuntimeError):
    """Claude could not deliver a usable quote; the caller falls back to the rules engine."""


@dataclass(frozen=True)
class AIReview:
    quote: EngineQuote
    model: str
    latency_ms: int
    request_id: str | None


class ClaudeQuoteEngine:
    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None) -> None:
        self._settings = settings
        if client is None:
            key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
            client = anthropic.AsyncAnthropic(api_key=key, timeout=settings.anthropic_timeout_s, max_retries=2)
        self._client = client

    async def review(self, payload: dict) -> AIReview:
        s = self._settings
        kwargs: dict = {
            "model": s.anthropic_model,
            "max_tokens": 16000,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": s.anthropic_effort},
            "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            # sort_keys keeps the serialisation deterministic for identical inputs.
            "messages": [{"role": "user", "content": json.dumps(payload, sort_keys=True, ensure_ascii=False)}],
            "output_format": EngineQuote,
        }
        if s.anthropic_server_fallbacks:
            # On a safety-classifier decline the API re-runs the request on Anthropic's
            # recommended fallback model instead of returning a refusal.
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"

        started = time.perf_counter()
        try:
            response = await self._client.beta.messages.parse(**kwargs)
        except anthropic.RateLimitError as exc:
            raise AIUnavailableError("Claude rate limit reached") from exc
        except anthropic.APIStatusError as exc:
            raise AIUnavailableError(f"Claude API error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise AIUnavailableError("Claude API not reachable") from exc
        except anthropic.APIError as exc:  # schema/parse problems in the SDK
            raise AIUnavailableError(f"Claude response unusable: {exc}") from exc
        except ValueError as exc:  # pydantic validation of the structured output
            raise AIUnavailableError("Claude output does not match the quote schema") from exc
        except Exception as exc:  # noqa: BLE001 - the AI layer is optional; never fail the quote
            log.exception("unexpected error in Claude review")
            raise AIUnavailableError(f"Claude client error ({type(exc).__name__})") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        request_id = getattr(response, "_request_id", None)
        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None) if response.stop_details else None
            raise AIUnavailableError(f"Claude declined the request (category={category})")
        if response.stop_reason == "max_tokens":
            raise AIUnavailableError("Claude response truncated (max_tokens)")
        parsed = response.parsed_output
        if parsed is None:
            raise AIUnavailableError("Claude returned no structured quote")

        usage = response.usage
        log.info(
            "claude quote review done",
            extra={
                "model": response.model,
                "latency_ms": latency_ms,
                "request_id": request_id,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            },
        )
        return AIReview(quote=parsed, model=response.model, latency_ms=latency_ms, request_id=request_id)
