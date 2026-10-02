"""HTTP API (v1)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status

from app.accounts import Viewer, current_viewer, require_engine_access
from app.billing.plans import Feature
from app.cad.brep import CadParseError
from app.cad.parser import ALLOWED_EXTENSIONS, CadTimeoutError, parse_cad_bytes
from app.catalog.machines import MACHINES, Process
from app.catalog.materials import MATERIALS
from app.config import Settings, get_settings
from app.engine.quote import AIRequiredError, QuoteEngine
from app.legal.terms import terms
from app.schemas import (
    CadMetadata,
    Commercial,
    CostVectors,
    EngineInput,
    EngineQuote,
    Entitlements,
    FactoryState,
    FactoryStateUpdate,
    Features,
    GeometryDiagnostics,
    OrderInfo,
    QuoteResponse,
    Supplier,
)
from app.security import client_ip, require_api_key
from app.storage import Store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")
HTTP_413 = 413  # "Content Too Large" (RFC 9110)
HTTP_422 = 422  # "Unprocessable Content" (RFC 9110)
BERLIN = ZoneInfo("Europe/Berlin")
QUOTE_ID_RE = re.compile(r"^AQ-\d{8}-[0-9A-Z]{10}$")
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_quote_id(now: datetime) -> str:
    # 50 bits of randomness: quote ids double as unguessable capability links.
    return f"AQ-{now:%Y%m%d}-" + "".join(secrets.choice(_CROCKFORD) for _ in range(10))


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_engine(request: Request) -> QuoteEngine:
    return request.app.state.engine


def supplier(settings: Settings) -> Supplier:
    return Supplier(
        name=settings.company_name,
        street=settings.company_street,
        city=settings.company_city,
        country=settings.company_country,
        email=settings.company_email,
        phone=settings.company_phone,
        vat_id=settings.company_vat_id,
        commercial_register=settings.company_register,
        managing_director=settings.company_managing_director,
    )


# --------------------------------------------------------------------------- catalogue
@router.get("/materials", summary="Material catalogue (public)")
def list_materials() -> list[dict]:
    return [m.public_dict() for m in MATERIALS.values()]


@router.get("/capabilities", summary="Machine park, upload limits and supplier data (public)")
def capabilities(settings: Settings = Depends(get_settings), store: Store = Depends(get_store)) -> dict:
    factory = store.get_factory()
    return {
        "machines": [
            {
                "process": m.process.value,
                "label_de": m.label_de,
                "label_en": m.label_en,
                "envelope_mm": list(m.envelope_mm),
                "available": factory.factory_status.machine_availability.is_available(m.process),
            }
            for m in MACHINES.values()
        ],
        "current_backlog_days": factory.factory_status.current_backlog_days,
        "accepted_extensions": sorted(ALLOWED_EXTENSIONS),
        "max_upload_mb": settings.max_upload_mb,
        "max_quantity": 10_000,
        "ai_enabled": settings.ai_enabled,
        "quote_retention_days": settings.quote_retention_days,
        "vat_rate_percent": settings.vat_rate_percent,
        "supplier": supplier(settings).model_dump(),
    }


# ------------------------------------------------------------------------------ quotes
async def _read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(HTTP_413, f"file exceeds {max_bytes // (1024 * 1024)} MB")
        chunks.append(chunk)
    if size == 0:
        raise HTTPException(HTTP_422, "empty file")
    return b"".join(chunks)


@router.post(
    "/quotes",
    response_model=QuoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a CAD file and receive an instant quote",
)
async def create_quote(
    request: Request,
    file: Annotated[UploadFile, File(description="STEP (.step/.stp), IGES or STL")],
    material: Annotated[str, Form(description="Material catalogue key, see /materials")],
    quantity: Annotated[int, Form(ge=1, le=10_000)] = 1,
    thread_count: Annotated[int | None, Form(ge=0, le=500, description="Override detected threads")] = None,
    units: Annotated[Literal["mm", "inch"], Form(description="Units of STL files (STEP carries its own)")] = "mm",
    customer_reference: Annotated[str | None, Form(max_length=80)] = None,
    settings: Settings = Depends(get_settings),
    store: Store = Depends(get_store),
    engine: QuoteEngine = Depends(get_engine),
    viewer: Viewer = Depends(current_viewer),
) -> QuoteResponse:
    retry_after = request.app.state.rate_limiter.check(client_ip(request))
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "too many quote requests", headers={"Retry-After": str(retry_after)}
        )
    if material not in MATERIALS:
        raise HTTPException(HTTP_422, f"unknown material '{material}'")
    plan = viewer.plan
    if quantity > plan.max_quantity:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"the {plan.name} plan quotes up to {plan.max_quantity} pieces - upgrade for series quantities",
        )
    if not store.consume_quote(viewer.subject, plan.quotes_per_month):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"monthly limit of {plan.quotes_per_month} quotes reached on the {plan.name} plan"
            + (" - create a free account for more" if viewer.is_guest else " - upgrade for more"),
        )
    try:
        return await _price_upload(
            request, file, material, quantity, thread_count, units, customer_reference, settings, store, engine, viewer
        )
    except BaseException:
        store.refund_quote(viewer.subject)  # failed quotes do not count against the plan
        raise


async def _price_upload(
    request: Request,
    file: UploadFile,
    material: str,
    quantity: int,
    thread_count: int | None,
    units: str,
    customer_reference: str | None,
    settings: Settings,
    store: Store,
    engine: QuoteEngine,
    viewer: Viewer,
) -> QuoteResponse:
    plan = viewer.plan
    max_bytes = int(settings.max_upload_mb * 1024 * 1024)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes + 64 * 1024:
        raise HTTPException(HTTP_413, f"file exceeds {settings.max_upload_mb:g} MB")

    filename = (file.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1][:120]
    data = await _read_limited(file, max_bytes)
    sha256 = hashlib.sha256(data).hexdigest()

    async with request.app.state.parse_semaphore:
        try:
            parsed = await asyncio.to_thread(
                parse_cad_bytes,
                data,
                filename,
                unit_scale=25.4 if units == "inch" else 1.0,
                timeout_s=settings.parse_timeout_s,
                mem_limit_mb=settings.parse_memory_limit_mb,
                max_triangles=settings.preview_max_triangles,
            )
        except CadTimeoutError as exc:
            raise HTTPException(HTTP_422, str(exc)) from exc
        except CadParseError as exc:
            raise HTTPException(HTTP_422, str(exc)) from exc

    features = Features(**parsed.features)
    diagnostics = GeometryDiagnostics(**parsed.diagnostics)
    if thread_count is not None:
        features.threads = thread_count
        diagnostics.thread_detection = "user_override"
    try:
        cad = CadMetadata(
            bounding_box=tuple(parsed.bounding_box),
            volume_cm3=parsed.volume_cm3,
            surface_area_cm2=parsed.surface_area_cm2,
            features=features,
            requested_material=material,
            diagnostics=diagnostics,
        )
    except ValueError as exc:
        raise HTTPException(HTTP_422, f"implausible geometry: {exc}") from exc

    factory = store.get_factory()
    mat = MATERIALS[material]
    price = factory.material_prices_eur_per_kg.get(material, mat.price_eur_per_kg)
    rates = dict(factory.machine_hourly_rates)
    rule_process = engine.rule_process(cad)
    engine_input = EngineInput(
        cad_metadata=cad,
        factory_status=factory.factory_status,
        cost_vectors=CostVectors(
            material_per_kg=price,
            machine_hourly_rate=rates.get(rule_process, rates[Process.CNC_3_AXIS]),
            energy_surcharge_percent=factory.energy_surcharge_percent,
            target_margin_percent=factory.target_margin_percent,
            machine_hourly_rates=rates,
        ),
        order=OrderInfo(quantity=quantity),
    )

    now = datetime.now(BERLIN)
    quote_id = new_quote_id(now)
    try:
        result = await engine.evaluate(engine_input, quote_id, ai_allowed=plan.has(Feature.AI_REVIEW))
    except AIRequiredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI quoting engine unavailable") from exc

    terms_de, terms_en = terms(settings, ai_used=result.analysis.engine == "claude")
    net = result.quote.cost_breakdown.net_total_eur
    response = QuoteResponse(
        quote=result.quote,
        engine_input=engine_input,
        analysis=result.analysis,
        commercial=Commercial(
            quantity=quantity,
            unit_price_net_eur=round(net / quantity, 2),
            vat_rate_percent=settings.vat_rate_percent,
            created_at=now.isoformat(timespec="seconds"),
            valid_until=(now + timedelta(days=settings.quote_validity_days)).date().isoformat(),
            customer_reference=customer_reference,
            file_name=filename,
            material_label=f"{mat.name_de} ({mat.werkstoff_nr})",
            supplier=supplier(settings),
            terms_de=terms_de,
            terms_en=terms_en,
        ),
        has_preview=parsed.preview_stl is not None,
        entitlements=Entitlements(plan=plan.key, features=sorted(f.value for f in plan.features)),
    )
    account_id = viewer.account.id if viewer.account else None
    await asyncio.to_thread(store.save_quote, response, sha256, parsed.preview_stl, account_id)
    log.info(
        "quote %s created: %s %s net=%.2f engine=%s",
        quote_id,
        result.quote.feasibility,
        result.quote.selected_process,
        net,
        result.analysis.engine,
    )
    return redact(response)


def redact(response: QuoteResponse) -> QuoteResponse:
    """Strip what the quote's plan does not include. The full record stays in the audit trail."""
    if Feature.COST_BREAKDOWN.value in response.entitlements.features:
        return response
    analysis = response.analysis.model_copy(
        update={"candidates": [], "time_breakdown": None, "material": None, "margin_eur": 0.0, "validation": []}
    )
    return response.model_copy(update={"analysis": analysis})


def _valid_id(quote_id: str) -> str:
    if not QUOTE_ID_RE.match(quote_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "quote not found")
    return quote_id


@router.get("/quotes/{quote_id}", response_model=QuoteResponse, summary="Retrieve a stored quote")
async def get_quote(quote_id: str, store: Store = Depends(get_store)) -> QuoteResponse:
    quote = await asyncio.to_thread(store.get_quote, _valid_id(quote_id))
    if quote is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "quote not found")
    return redact(quote)


@router.get(
    "/quotes/{quote_id}/preview.stl",
    summary="Tessellated preview mesh (binary STL)",
    response_class=Response,
    responses={200: {"content": {"model/stl": {}}}},
)
async def get_preview(quote_id: str, store: Store = Depends(get_store)) -> Response:
    blob = await asyncio.to_thread(store.get_preview, _valid_id(quote_id))
    if blob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "preview not available")
    return Response(content=blob, media_type="model/stl", headers={"Cache-Control": "private, max-age=3600"})


# ------------------------------------------------------------------- integration API
@router.post(
    "/engine/evaluate",
    response_model=EngineQuote,
    dependencies=[Depends(require_engine_access)],
    summary="Core engine: cad_metadata + factory_status + cost_vectors -> quote JSON",
)
async def evaluate(body: EngineInput, response: Response, engine: QuoteEngine = Depends(get_engine)) -> EngineQuote:
    quote_id = new_quote_id(datetime.now(BERLIN))
    try:
        result = await engine.evaluate(body, quote_id)
    except AIRequiredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI quoting engine unavailable") from exc
    response.headers["X-Quote-Engine"] = result.analysis.engine
    if result.analysis.validation:
        response.headers["X-Quote-Validation"] = str(len(result.analysis.validation))
    return result.quote


@router.get(
    "/factory",
    response_model=FactoryState,
    dependencies=[Depends(require_api_key)],
    summary="Current machine availability, backlog and cost vectors",
)
def get_factory(store: Store = Depends(get_store)) -> FactoryState:
    return store.get_factory()


@router.put(
    "/factory",
    response_model=FactoryState,
    dependencies=[Depends(require_api_key)],
    summary="Update factory state (e.g. from MES / telemetry gateway)",
)
def put_factory(update: FactoryStateUpdate, store: Store = Depends(get_store)) -> FactoryState:
    state = store.get_factory()
    if update.machine_availability is not None:
        state.factory_status.machine_availability = update.machine_availability
    if update.current_backlog_days is not None:
        state.factory_status.current_backlog_days = update.current_backlog_days
    if update.energy_surcharge_percent is not None:
        state.energy_surcharge_percent = update.energy_surcharge_percent
    if update.target_margin_percent is not None:
        state.target_margin_percent = update.target_margin_percent
    if update.machine_hourly_rates:
        state.machine_hourly_rates.update(update.machine_hourly_rates)
    if update.material_prices_eur_per_kg:
        unknown = set(update.material_prices_eur_per_kg) - set(MATERIALS)
        if unknown:
            raise HTTPException(HTTP_422, f"unknown materials: {sorted(unknown)}")
        state.material_prices_eur_per_kg.update(update.material_prices_eur_per_kg)
    return store.put_factory(state)
