# Cost model & data sources

This document explains **every number the engine uses**: where it comes from, how it is
modelled, and how to calibrate it to your own shop. The defaults are researched German market
values (September 2026). They make the product usable on day one. They do not replace your own
*Maschinenstundensatz* calculation.

> **Calibration is mandatory before go-live.** Replay 30–50 historical quotes through
> `POST /api/v1/engine/evaluate`, compare with what your estimator quoted, and adjust rates,
> removal rates and penalties until at least 80 % of parts fall within ±15 %.

---

## 1. The formula (engine contract, rules 1–4)

```
Rule 1  process      = CNC_5_Axis  if complex_curves > 0 or multi-sided (>= 3 access directions / inclined features)
                     = Lathe       if rotationally symmetric (>= 85 % of surface coaxial)
                     = CNC_3_Axis  otherwise
        availability = false  ->  "Capacity Delay", lead time + 5 business days

Rule 2  t_setup      = 45 min + 20 min x (extra set-ups)
        t_rough      = (V_stock - V_part) / (MRR_material x f_machine)
        t_finish     = A_surface / (finish_rate_material x g_machine)
        t_features   = 5 x holes + 5 x threads + 15 x pockets + 30 x complex_curves   [min]
        t_total      = t_setup + (t_rough + t_finish + t_features)
                       + (n - 1) x (t_rough + t_finish + 0.3 x t_features)          # batch of n
        hours        = round(t_total / 60, 2)

Rule 3  material     = V_part x density x EUR/kg x n                       (or V_stock, see §5)
        machining    = hours x machine_hourly_rate
        base         = material + machining
        energy       = base x energy_surcharge_percent
        margin       = (base + energy) x target_margin_percent            (markup mode)
        net          = base + energy + margin

Rule 4  VAT          = net x 19 %          (§ 12 Abs. 1 UStG)
        gross        = net + VAT
```

Every published line item is rounded half-up to the cent with `Decimal`, so
`net = material + machining + energy + margin` and `gross = net + VAT` hold exactly. The engine
never shows a total that does not add up.

---

## 2. Machine hourly rates (*Maschinenstundensätze*)

| Process | Default | Market range (DE, 2025/26) | Source |
|---|---:|---|---|
| `CNC_3_Axis` 3-axis VMC | **85 €/h** | 70–100 €/h | pos.de: 3-axis ≈ 85 €/h |
| `CNC_5_Axis` 5-axis simultaneous | **110 €/h** | 100–150 €/h | pos.de: 5-axis ≈ 110 €/h |
| `Lathe` CNC turning | **75 €/h** | 50–90 €/h (up to 130 €/h for turn-mill) | mtb-metall.de, yonglihaocnc.de |

The rates are machine-plus-operator rates, i.e. they include depreciation (typically over 6 years),
imputed interest, space, maintenance (≈ 4 % of the investment per year), energy, tooling (Al ≈ 5 €/h,
steel ≈ 8 €/h, stainless ≥ 12 €/h) and personnel (CNC operator ≈ 26 €/h, setter ≈ 30 €/h). All
figures are from pos.de, *CNC-Bearbeitungskosten berechnen*. Replace them with your own VDI 3258
calculation: `PUT /api/v1/factory` → `machine_hourly_rates`.

## 3. Materials

Densities are material constants (EN 573-3, EN 10088-1, EN 10083, supplier data sheets). Prices are
**cut-to-size semi-finished goods, small quantities, Germany, September 2026**.

| Key | Material | Werkstoff-Nr. | ρ g/cm³ | €/kg | Effective roughing MRR cm³/min | Finish cm²/min |
|---|---|---|---:|---:|---:|---:|
| `AL_6082_T6` | EN AW-6082 T6 (AlSi1MgMn) | 3.2315 | 2.70 | 7.50 | 150 | 25 |
| `AL_6061_T6` | EN AW-6061 T6 | 3.3211 | 2.70 | 8.00 | 150 | 25 |
| `AL_7075_T651` | EN AW-7075 T651 | 3.4365 | 2.81 | 16.00 | 140 | 25 |
| `STEEL_S235JR` | S235JR | 1.0038 | 7.85 | 1.80 | 45 | 12 |
| `STEEL_C45` | C45 | 1.0503 | 7.85 | 2.20 | 40 | 12 |
| `STEEL_42CRMO4` | 42CrMo4+QT | 1.7225 | 7.85 | 3.20 | 30 | 10 |
| `STEEL_11SMNPB30` | 11SMnPb30 (free-cutting) | 1.0718 | 7.85 | 2.10 | 50 | 14 |
| `SS_1.4301` | X5CrNi18-10 (V2A) | 1.4301 | 7.90 | 5.60 | 22 | 8 |
| `SS_1.4305` | X8CrNiS18-9 | 1.4305 | 7.90 | 5.80 | 26 | 9 |
| `SS_1.4404` | X2CrNiMo17-12-2 (V4A) | 1.4404 | 8.00 | 7.40 | 20 | 8 |
| `BRASS_CW614N` | CuZn39Pb3 (Ms58) | CW614N | 8.47 | 8.50 | 110 | 22 |
| `TI_GRADE5` | Ti6Al4V | 3.7165 | 4.43 | 45.00 | 10 | 5 |
| `POM_C` | POM-C | – | 1.41 | 9.50 | 180 | 25 |
| `PA6` | PA 6 | – | 1.14 | 7.00 | 160 | 25 |
| `PEEK` | PEEK | – | 1.31 | 110.00 | 90 | 18 |

**How the prices were modelled**

- **Aluminium:** LME aluminium was 2,861 €/t (Alumeco, 24 Sep 2026). Add the billet premium, the
  conversion to plate or bar, and the distributor cutting and small-quantity surcharges. That gives
  typically 2.5–3× metal value for 6xxx alloys. 7075 is an aerospace plate grade at roughly 2× the
  6082 price.
- **Stainless:** base price plus the monthly German *Legierungszuschlag* (alloy surcharge). In
  September 2026 it was 2,235 €/t for 1.4301 and 4,047 €/t for 1.4404 (legierungszuschlag.info,
  Outokumpu). The standard terms therefore reserve an adjustment to the surcharge valid on the
  delivery date.
- **Steel, brass, titanium and plastics:** typical German distributor list prices for bar stock in
  small quantities. These are **estimates to be replaced with your purchase prices** via
  `PUT /api/v1/factory` → `material_prices_eur_per_kg`.

**Effective removal rates.** Tool makers publish peak rates, calculated as
`Q = ap × ae × vf / 1000` cm³/min (Sandvik Coromant). Published guideline values are: aluminium
roughing above 500 cm³/min, steel 100 cm³/min or more, titanium 16–49 cm³/min (MachinistX). A job
shop never sustains those peaks over a whole part: smaller tools in pockets, air cuts, tool changes
and approach moves all eat into it. The engine therefore uses **≈ 25–35 % of peak** as the
effective average. Machine factors: 5-axis ×0.85 (longer tools, tilted set-ups), lathe ×1.4 (turning
removes material far more efficiently than milling).

**Finishing** is modelled on surface area. For example, a 10 mm end mill with 1 mm step-over at
2,000 mm/min finishes 20 cm²/min in aluminium. Steel and stainless are proportionally slower.

## 4. Feature penalties (engine contract)

| Feature | Penalty | How it is recognised in the STEP file |
|---|---:|---|
| Hole | 5 min | concave cylinder groups (same axis and radius, ≥ 270° span) |
| Thread | +5 min | hole Ø equals an ISO 261 / DIN 336 tap drill (M6 → 5.0, M8 → 6.8, …) ± 0.06 mm. **Heuristic**: customers can override it in the UI |
| Pocket / step | 15 min | planar floor below the part envelope with free tool access along its normal (ray cast), excluding hole bottoms and turned shoulders |
| Complex curve | 30 min | connected clusters of B-spline / Bézier / offset faces |

Penalties apply in full to the first article (CAM programming, prove-out). For parts 2…n only
`series_feature_factor = 0.3` of the time is charged, because drilling a hole in series takes
seconds, not minutes.

## 5. Material basis: part vs. raw stock

The contract formula prices the **finished-part mass** (`QUOTE_MATERIAL_BASIS=part`, the default).
A real shop buys the **raw blank** (bounding box + 3 mm per side, or bar Ø + 4 mm × length + 5 mm).
On a pocketed part the difference can be 2–5×. For production we recommend
`QUOTE_MATERIAL_BASIS=stock`. The analysis block always reports both masses and the buy-to-fly
ratio.

## 6. Energy surcharge

Industrial electricity for SMEs cost **17.8 ct/kWh** on average in 2025, falling to 17.2 ct/kWh in
early 2026 (BDEW *Strompreisanalyse*).

| Machine | Average draw | €/h at 17.8 ct | Share of hourly rate |
|---|---:|---:|---:|
| 3-axis | 12 kW | 2.14 | 2.5 % |
| 5-axis | 18 kW | 3.20 | 2.9 % |
| Lathe | 10 kW | 1.78 | 2.4 % |

Adding compressed air, extraction, coolant filtration and hall climate (+30–50 %) gives a **default
of 4 %**. Surcharge it dynamically (`PUT /api/v1/factory` → `energy_surcharge_percent`) when your
energy contract changes.

## 7. Margin

`target_margin_percent` defaults to 15 %. `QUOTE_MARGIN_MODE=markup` applies it as the German
*Gewinnzuschlag* on cost (Zuschlagskalkulation). `QUOTE_MARGIN_MODE=margin` makes it a true share of
the net price, i.e. `net = cost / (1 − m)`.

## 8. Lead time

```
lead = current_backlog_days + ceil(hours / 16 productive h per day, two shifts)
     + 2 days QA/packing/shipping + 5 days if Capacity Delay
```

## 9. Worked example: aluminium bracket (`samples/bracket.step`)

The STEP parser extracts: 120 × 80 × 25 mm, V = 203.18 cm³, A = 331.70 cm², 6 holes (2 of them
M8 tap drills → 2 threads), 1 closed pocket + 1 open step, no free-form faces, access only from +Z →
`CNC_3_Axis`, 1 set-up.

| Step | Calculation | Result |
|---|---|---:|
| Stock | 126 × 86 × 31 mm | 335.92 cm³ |
| Roughing | (335.92 − 203.18) / 150 | 0.88 min |
| Finishing | 331.70 / 25 | 13.27 min |
| Features | 6×5 + 2×5 + 2×15 | 70 min |
| Set-up | 45 + 0 × 20 | 45 min |
| **Runtime** | 129.15 min | **2.15 h** |
| Material | 203.18 × 2.70 / 1000 = 0.5486 kg × 7.50 € | 4.11 € |
| Machining | 2.15 h × 85 €/h | 182.75 € |
| Energy 4 % | (4.11 + 182.75) × 0.04 | 7.47 € |
| Margin 15 % | 194.33 × 0.15 | 29.15 € |
| **Net** | | **223.48 €** |
| MwSt 19 % | | 42.46 € |
| **Gross** | | **265.94 €** |
| Lead time | 3 backlog + 1 production + 2 QA | 6 business days |

The one-off price is dominated by set-up and feature time (typical for single parts). At 50 pieces
the unit price drops to about 68 € net.

## 10. Known limitations of the model

- Tolerances, surface finish, GD&T, heat treatment and coatings are not in a STEP file. The quote
  assumes ISO 2768-mK and Ra 3.2 µm and says so on the document. Drawing (PDF) ingestion is on the
  roadmap.
- Thin-wall detection and tool-reach analysis (deep narrow pockets) are not yet implemented. Claude
  is instructed to escalate suspicious aspect ratios to *Review Required*.
- Thread recognition is heuristic: modelled threads, cosmetic threads and clearance holes can be
  confused. Hence the UI override and the `THREADS_ESTIMATED` flag.

## Sources

- pos.de – [CNC-Bearbeitungskosten berechnen: Material macht den Unterschied](https://pos.de/blog/wirtschaftliche-fertigung/cnc-bearbeitungskosten-im-griff-so-berechnen-sie-materialspezifische-zerspanungskosten-richtig/) (machine, personnel and tool rates)
- pos.de – [Maschinenstundensatz kalkulieren](https://pos.de/blog/fertigungs-know-how/maschinenstundensatz-korrekt-kalkulieren-schluss-mit-bauchgefuehl/)
- MTB Metall – [Was kostet eine Stunde CNC-Drehen?](https://mtb-metall.de/fragen/cnc-drehen-kosten/); Yonglihao – [Was kostet eine Stunde CNC drehen?](https://yonglihaocnc.de/kostet-eine-stunde-cnc-drehen/)
- Alumeco – [Aluminium price (LME, EUR/t)](https://www.alumeco.com/metal-prices/aluminium/)
- Legierungszuschlag.info – [1.4301](https://legierungszuschlag.info/en/wkst/4301), [1.4404](https://legierungszuschlag.info/en/wkst/4404); Outokumpu – [Legierungszuschläge Europa](https://www.outokumpu.com/de-de/surcharges/stainless-steel-alloy-surcharges-europe)
- BDEW – [Strompreisanalyse](https://www.bdew.de/service/daten-und-grafiken/bdew-strompreisanalyse/)
- Sandvik Coromant – [Milling formulas and definitions](https://www.sandvik.coromant.com/en-gb/knowledge/machining-formulas-definitions/milling-formulas-definitions)
- MachinistX – [Material removal rates: guidelines by material type](https://machinistx.com/articles/material-removal-rates-guidelines-by-material-type)
- Standards: DIN 336 / ISO 261 (tap drills), ISO 2768-1/-2 (general tolerances), EN 10204 (inspection documents), § 12 UStG (VAT)
