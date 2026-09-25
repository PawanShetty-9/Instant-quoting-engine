"use client";

import dynamic from "next/dynamic";
import type { QuoteResponse } from "@/lib/api";
import { previewUrl } from "@/lib/api";
import { PROCESS_LABEL, dateDe, duration, eur, num, splitNotes } from "@/lib/format";
import CostBar from "./CostBar";
import Stamp from "./Stamp";

const PartViewer = dynamic(() => import("./PartViewer"), { ssr: false });

const ZONES_H = ["A", "B", "C", "D", "E", "F"];
const ZONES_V = ["1", "2", "3", "4"];

const FLAG_LABEL: Record<string, string> = {
  CAPACITY_DELAY: "Kapazitätsengpass",
  THREADS_ESTIMATED: "Gewinde geschätzt",
  MESH_INPUT: "STL-Netz",
  MULTI_BODY: "Mehrkörper",
  INVALID_BREP: "Geometriefehler",
  DEEP_HOLES: "Tieflochbohrung",
  MICRO_FEATURES: "Mikromerkmale",
  SMALL_INTERNAL_RADIUS: "Kleiner Innenradius",
  THIN_PART: "Dünnwandig",
  SLENDER_TURNING: "Schlankes Drehteil",
  HIGH_BUY_TO_FLY: "Hoher Zerspanungsanteil",
  HIGH_VALUE: "Kaufm. Freigabe",
  ENVELOPE_REROUTE: "Arbeitsraum-Umplanung",
  NO_MACHINE_FITS: "Zu groß",
  UNKNOWN_MATERIAL: "Werkstoff unbekannt",
  ROTATIONAL_HEURISTIC: "Drehteil angenommen",
};

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <section className="sheet" aria-label="Angebotsblatt">
      {(["top", "bottom"] as const).map((side) => (
        <div key={side} className={`zones ${side}`} aria-hidden>
          {ZONES_H.map((z) => (
            <span key={z}>{z}</span>
          ))}
        </div>
      ))}
      {(["left", "right"] as const).map((side) => (
        <div key={side} className={`zones ${side}`} aria-hidden>
          {ZONES_V.map((z) => (
            <span key={z}>{z}</span>
          ))}
        </div>
      ))}
      <div className="sheet-inner">{children}</div>
    </section>
  );
}

export function EmptySheet({ busy }: { busy: boolean }) {
  return (
    <Frame>
      <div className="view">
        {busy && <div className="plotter" aria-hidden />}
        <div className="empty" aria-live="polite">
          <svg width="72" height="72" viewBox="0 0 72 72" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
            <path d="M12 26 36 12l24 14v24L36 64 12 50z" />
            <path d="M12 26l24 14 24-14M36 40v24" />
            <circle cx="46" cy="30" r="4" />
          </svg>
          {busy ? (
            <>
              <strong>Geometrie wird analysiert …</strong>
              <span>Merkmale erkennen, Maschine wählen, kalkulieren.</span>
              <span className="en">Recognising features, selecting a machine, costing.</span>
            </>
          ) : (
            <>
              <strong>Noch kein Bauteil auf dem Blatt</strong>
              <span>Legen Sie links eine STEP-Datei ab oder wählen Sie ein Beispielteil.</span>
              <span className="en">Drop a STEP file on the left or pick a sample part.</span>
            </>
          )}
        </div>
      </div>
      <div className="titleblock" aria-hidden>
        {["Angebots-Nr.", "Werkstoff", "Verfahren", "Lieferzeit"].map((l) => (
          <div key={l} className="tb">
            <span className="label">{l}</span>
            <span className="value" style={{ color: "var(--rule)" }}>
              —
            </span>
          </div>
        ))}
        <div className="tb stamp-cell" style={{ gridRow: "auto" }} />
      </div>
    </Frame>
  );
}

export default function QuoteSheet({
  data,
  materialCategory,
  onReset,
}: {
  data: QuoteResponse;
  materialCategory?: string;
  onReset: () => void;
}) {
  const { quote, analysis, commercial, engine_input } = data;
  const cad = engine_input.cad_metadata;
  const b = quote.cost_breakdown;
  const [x, y, z] = cad.bounding_box;
  const notes = splitNotes(quote.feasibility_notes);
  const proc = PROCESS_LABEL[quote.selected_process];
  const t = analysis.time_breakdown;
  const m = analysis.material;
  const diag = cad.diagnostics;

  return (
    <div>
      <Frame>
        <div className="view">
          {data.has_preview ? (
            <PartViewer url={previewUrl(quote.quote_id)} category={materialCategory} />
          ) : (
            <div className="empty">
              <strong>Keine Vorschau</strong>
            </div>
          )}
          <div className="view-caption">
            <span className="label">
              Hüllmaß <span className="en">· Envelope</span>
            </span>
            <span className="figure">
              {num(x, 1)} × {num(y, 1)} × {num(z, 1)} mm
            </span>
          </div>
          <div className="view-hint" aria-hidden>
            Ziehen zum Drehen · Scrollen zum Zoomen
          </div>
        </div>

        <div className="titleblock">
          <div className="tb">
            <span className="label">
              Angebots-Nr. <span className="en">Quote no.</span>
            </span>
            <span className="value code">{quote.quote_id}</span>
          </div>
          <div className="tb">
            <span className="label">
              Datum <span className="en">Date</span>
            </span>
            <span className="value figure">{dateDe(commercial.created_at)}</span>
          </div>
          <div className="tb">
            <span className="label">
              Gültig bis <span className="en">Valid until</span>
            </span>
            <span className="value figure">{dateDe(commercial.valid_until)}</span>
          </div>
          <div className="tb">
            <span className="label">
              Stückzahl <span className="en">Qty</span>
            </span>
            <span className="value figure">{num(commercial.quantity)}</span>
          </div>
          <div className="tb stamp-cell">
            <Stamp value={quote.feasibility} engine={analysis.engine} />
          </div>

          <div className="tb wide">
            <span className="label">
              Werkstoff <span className="en">Material</span>
            </span>
            <span className="value">{commercial.material_label}</span>
          </div>
          <div className="tb">
            <span className="label">
              Verfahren <span className="en">Process</span>
            </span>
            <span className="value">{proc.de}</span>
          </div>
          <div className="tb">
            <span className="label">
              Lieferzeit <span className="en">Lead time</span>
            </span>
            <span className="value">
              <span className="figure">{quote.recommended_lead_time_days}</span> Arbeitstage
            </span>
          </div>

          <div className="tb">
            <span className="label">
              Fertigungszeit <span className="en">Machine time</span>
            </span>
            <span className="value figure">{duration(quote.estimated_production_time_hours)}</span>
          </div>
          <div className="tb">
            <span className="label">
              Masse <span className="en">Mass</span>
            </span>
            <span className="value figure">{m ? `${num(m.part_mass_kg, 3)} kg` : "—"}</span>
          </div>
          <div className="tb">
            <span className="label">
              Volumen <span className="en">Volume</span>
            </span>
            <span className="value figure">{num(cad.volume_cm3, 1)} cm³</span>
          </div>
          <div className="tb">
            <span className="label">
              Stückpreis netto <span className="en">Unit, net</span>
            </span>
            <span className="value figure">{eur(commercial.unit_price_net_eur)}</span>
          </div>

          <div className="tb price">
            <span className="label">
              Netto <span className="en">Net</span>
            </span>
            <span className="value">{eur(b.net_total_eur)}</span>
          </div>
          <div className="tb price">
            <span className="label">
              MwSt {num(commercial.vat_rate_percent)} % <span className="en">VAT</span>
            </span>
            <span className="value">{eur(b.vat_19_eur)}</span>
          </div>
          <div className="tb price">
            <span className="label">
              Energie <span className="en">Energy</span>
            </span>
            <span className="value">{eur(b.energy_surcharge_eur)}</span>
          </div>
          <div className="tb price gross">
            <span className="label">
              Gesamt brutto <span className="en">Total incl. VAT</span>
            </span>
            <span className="value figure">{eur(b.gross_total_eur)}</span>
          </div>
        </div>
      </Frame>

      <div className="details">
        <div className="card span">
          <h2>
            Prüfhinweise<span className="en">Review notes</span>
          </h2>
          <div className="notes">
            <div>
              <span className="label">Deutsch</span>
              <p>{notes.de}</p>
            </div>
            {notes.en && (
              <div className="en-col">
                <span className="label">English</span>
                <p>{notes.en}</p>
              </div>
            )}
          </div>
          {analysis.flags.length > 0 && (
            <div className="chips" aria-label="Hinweise">
              {analysis.flags.map((f) => (
                <span key={f} className="chip">
                  {FLAG_LABEL[f] ?? f}
                </span>
              ))}
            </div>
          )}
          <p className="engine-note">
            {analysis.engine === "claude"
              ? `Kalkulation durch Regelwerk, Plausibilisierung durch KI (${analysis.model}); alle Beträge vom Rechenkern verifiziert.`
              : "Kalkulation durch das deterministische Regelwerk."}
          </p>
        </div>

        <div className="card">
          <h2>
            Kosten<span className="en">Cost</span>
          </h2>
          <CostBar
            material={b.material_cost_eur}
            machining={b.machining_cost_eur}
            energy={b.energy_surcharge_eur}
            margin={analysis.margin_eur}
          />
          <dl className="kv" style={{ marginTop: 16 }}>
            <dt>Materialpreis</dt>
            <dd className="figure">{eur(engine_input.cost_vectors.material_per_kg)}/kg</dd>
            <dt>Maschinenstundensatz</dt>
            <dd className="figure">
              {eur(
                b.machining_cost_eur && quote.estimated_production_time_hours
                  ? b.machining_cost_eur / quote.estimated_production_time_hours
                  : engine_input.cost_vectors.machine_hourly_rate,
              )}
              /h
            </dd>
            {m && (
              <>
                <dt>Rohteil</dt>
                <dd className="figure">
                  {m.stock_dimensions_mm.map((d) => num(d, 0)).join(" × ")} mm
                </dd>
                <dt>Zerspanungsverhältnis</dt>
                <dd className="figure">{num(m.buy_to_fly_ratio, 2)} : 1</dd>
              </>
            )}
          </dl>
        </div>

        <div className="card">
          <h2>
            Fertigung<span className="en">Manufacturing</span>
          </h2>
          <dl className="kv">
            {t && (
              <>
                <dt>Rüsten ({t.setups} Aufspannung{t.setups > 1 ? "en" : ""})</dt>
                <dd className="figure">{num(t.setup_minutes)} min</dd>
                <dt>Schruppen je Teil</dt>
                <dd className="figure">{num(t.roughing_minutes_per_part, 1)} min</dd>
                <dt>Schlichten je Teil</dt>
                <dd className="figure">{num(t.finishing_minutes_per_part, 1)} min</dd>
                <dt>Merkmale Erstteil</dt>
                <dd className="figure">{num(t.feature_minutes_first_part)} min</dd>
              </>
            )}
            <dt>Bohrungen / Gewinde</dt>
            <dd className="figure">
              {cad.features.holes} / {cad.features.threads}
              {diag?.thread_detection === "tap_drill_heuristic" && cad.features.threads > 0 ? " *" : ""}
            </dd>
            <dt>Taschen / Absätze</dt>
            <dd className="figure">{cad.features.pockets}</dd>
            <dt>Freiformbereiche</dt>
            <dd className="figure">{cad.features.complex_curves}</dd>
            {diag && diag.access_directions.length > 0 && (
              <>
                <dt>Bearbeitungsrichtungen</dt>
                <dd className="figure">{diag.access_directions.join(" ")}</dd>
              </>
            )}
          </dl>
          {diag?.thread_detection === "tap_drill_heuristic" && cad.features.threads > 0 && (
            <p className="help" style={{ marginBottom: 0 }}>
              * aus Kernlochdurchmessern abgeleitet – bei Abweichung Gewindeanzahl links angeben.
            </p>
          )}
        </div>
      </div>

      <div className="actions">
        <a className="btn" href={`/quotes/${quote.quote_id}`} target="_blank" rel="noopener">
          Angebot drucken · PDF
        </a>
        <button type="button" className="btn ghost" onClick={onReset}>
          Weiteres Bauteil kalkulieren
        </button>
      </div>
    </div>
  );
}
