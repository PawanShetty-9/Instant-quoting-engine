# API reference (v1)

Interactive OpenAPI docs: `http://<backend>:8000/docs`. They are disabled when
`QUOTE_ENVIRONMENT=production`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/healthz` | – | Liveness |
| `GET` | `/readyz` | – | Readiness (CAD kernel + DB) |
| `GET` | `/api/v1/materials` | – | Material catalogue (no purchase prices) |
| `GET` | `/api/v1/capabilities` | – | Machines, availability, backlog, upload limits, supplier data |
| `POST` | `/api/v1/quotes` | – (rate-limited) | **Upload CAD → instant quote** |
| `GET` | `/api/v1/quotes/{id}` | capability ID | Stored quote |
| `GET` | `/api/v1/quotes/{id}/preview.stl` | capability ID | Tessellated preview mesh |
| `POST` | `/api/v1/engine/evaluate` | `X-API-Key` | **Core engine:** contract JSON in → quote JSON out |
| `GET` | `/api/v1/factory` | `X-API-Key` | Live factory state |
| `PUT` | `/api/v1/factory` | `X-API-Key` | Update availability, backlog, rates, prices (MES/ERP) |

## Upload a CAD file

```bash
curl -s https://angebot.example.de/api/v1/quotes \
  -F file=@samples/bracket.step \
  -F material=AL_6082_T6 \
  -F quantity=10 \
  -F customer_reference="Anfrage 4711"
  # optional: -F thread_count=4   (override detected threads)
  #           -F units=inch        (STL only)
```

The response is a `QuoteResponse`:

```jsonc
{
  "quote": { ... exactly the engine contract, see below ... },
  "engine_input": { "cad_metadata": {...}, "factory_status": {...}, "cost_vectors": {...}, "order": {"quantity": 10} },
  "analysis": {
    "engine": "claude",                 // or "rules"
    "model": "claude-opus-5",
    "rule_based_process": "CNC_3_Axis",
    "flags": ["THREADS_ESTIMATED"],
    "candidates": [ /* time + cost for every machine class */ ],
    "time_breakdown": { "setup_minutes": 45, "roughing_minutes_per_part": 0.88, ... },
    "material": { "part_mass_kg": 0.5486, "stock_mass_kg": 0.907, "buy_to_fly_ratio": 1.65, ... },
    "margin_eur": 29.15,
    "validation": []                    // guardrail corrections, if any
  },
  "commercial": { "unit_price_net_eur": ..., "valid_until": "2026-10-25", "terms_de": [...], "terms_en": [...], "supplier": {...} },
  "has_preview": true
}
```

| Status | Meaning |
|---|---|
| 201 | Quote created |
| 413 | File larger than `QUOTE_MAX_UPLOAD_MB` |
| 422 | Unknown material, empty/forged/unsupported file, unreadable geometry, parse timeout |
| 429 | Rate limit exceeded (`Retry-After` header) |
| 503 | `QUOTE_AI_MODE=required` and the AI engine is unavailable |

## Core engine endpoint

`POST /api/v1/engine/evaluate` takes the contract input verbatim
([samples/example_engine_input.json](../samples/example_engine_input.json)):

```json
{
  "cad_metadata": {
    "bounding_box": [120.0, 80.0, 25.0],
    "volume_cm3": 203.18,
    "surface_area_cm2": 331.70,
    "features": {"holes": 6, "threads": 2, "pockets": 2, "complex_curves": 0},
    "requested_material": "Aluminium EN AW-6082 T6"
  },
  "factory_status": {
    "machine_availability": {"CNC_5_Axis": true, "CNC_3_Axis": true, "Lathe": true},
    "current_backlog_days": 3
  },
  "cost_vectors": {
    "material_per_kg": 7.50,
    "machine_hourly_rate": 85.0,
    "energy_surcharge_percent": 4.0,
    "target_margin_percent": 15.0
  }
}
```

and returns exactly the contract output
([samples/example_engine_output.json](../samples/example_engine_output.json)):

```json
{
  "quote_id": "AQ-20260925-EXAMPLE001",
  "feasibility": "Feasible",
  "feasibility_notes": "DE: Verfahren 3-Achs-Vertikal-Bearbeitungszentrum (CNC_3_Axis): prismatisches Frästeil. ... | EN: Process 3-axis vertical machining centre (CNC_3_Axis): prismatic milled part. ...",
  "selected_process": "CNC_3_Axis",
  "estimated_production_time_hours": 2.15,
  "cost_breakdown": {
    "material_cost_eur": 4.11,
    "machining_cost_eur": 182.75,
    "energy_surcharge_eur": 7.47,
    "net_total_eur": 223.48,
    "vat_19_eur": 42.46,
    "gross_total_eur": 265.94
  },
  "recommended_lead_time_days": 6
}
```

Response headers: `X-Quote-Engine: claude|rules`, and `X-Quote-Validation: <n>` when the guardrail
corrected AI output.

**Input extensions** (all optional; clients sending only the contract fields get a valid quote):

- `features` may also be a list of names: `["holes", "holes", "threads"]`
- `requested_material` accepts catalogue keys, Werkstoffnummern (`1.4301`) and trade names (`V2A`,
  `Ms58`, `Ti6Al4V`)
- `cad_metadata.diagnostics.access_directions` (e.g. `["+Z", "+X", "-Y"]`),
  `inclined_features`, `is_rotational`, `turning_diameter_mm`, `turning_length_mm`. Without
  diagnostics, turnability is inferred from the envelope
- `cost_vectors.machine_hourly_rates`: per-machine rates `{ "CNC_5_Axis": 110, ... }`
- `order.quantity`: batch size (default 1)

## Factory state (MES / ERP integration)

```bash
# e.g. called by the Industrie 4.0 telemetry gateway when a machine goes down
curl -X PUT https://angebot.example.de/api/v1/factory \
  -H "X-API-Key: $QUOTE_ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{
        "machine_availability": {"CNC_5_Axis": false, "CNC_3_Axis": true, "Lathe": true},
        "current_backlog_days": 6,
        "energy_surcharge_percent": 5.5,
        "machine_hourly_rates": {"CNC_5_Axis": 118},
        "material_prices_eur_per_kg": {"SS_1.4404": 7.90}
      }'
```

All fields are optional (partial update). Changes apply to the next quote immediately and are
shown live in the portal header.
