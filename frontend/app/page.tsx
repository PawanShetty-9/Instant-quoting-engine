"use client";

import { useEffect, useRef, useState } from "react";
import QuoteSheet, { EmptySheet } from "@/components/QuoteSheet";
import UploadPanel, { type QuoteRequest } from "@/components/UploadPanel";
import {
  ApiError,
  createQuote,
  getCapabilities,
  getMaterials,
  type Capabilities,
  type MaterialOption,
  type QuoteResponse,
} from "@/lib/api";
import { PROCESS_LABEL } from "@/lib/format";

function BrandMark() {
  // A part outline in a drawing frame corner - the portal's mark.
  return (
    <svg className="brand-mark" viewBox="0 0 28 28" fill="none" aria-hidden>
      <rect x="1" y="1" width="26" height="26" rx="3" stroke="var(--ink)" strokeWidth="1.5" />
      <path d="M7 19V9h8l6 5v5z" stroke="var(--blue)" strokeWidth="1.8" strokeLinejoin="round" />
      <circle cx="11.5" cy="14" r="1.8" fill="var(--blue)" />
    </svg>
  );
}

export default function Home() {
  const [materials, setMaterials] = useState<MaterialOption[]>([]);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<QuoteResponse | null>(null);
  const [error, setError] = useState<{ title: string; detail: string } | null>(null);
  const sheetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getMaterials().then(setMaterials).catch(() => undefined);
    getCapabilities().then(setCaps).catch(() => undefined);
  }, []);

  async function run(req: QuoteRequest) {
    setBusy(true);
    setError(null);
    setResult(null);
    const form = new FormData();
    form.append("file", req.file);
    form.append("material", req.material);
    form.append("quantity", String(req.quantity));
    form.append("units", req.units);
    if (req.threadCount !== null) form.append("thread_count", String(req.threadCount));
    if (req.reference) form.append("customer_reference", req.reference);
    if (window.matchMedia("(max-width: 1080px)").matches) {
      sheetRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    try {
      setResult(await createQuote(form));
    } catch (e) {
      const err = e as ApiError;
      const title =
        err.status === 413
          ? "Datei zu groß"
          : err.status === 429
            ? "Zu viele Anfragen"
            : err.status === 422
              ? "Datei konnte nicht kalkuliert werden"
              : "Kalkulation fehlgeschlagen";
      const hint =
        err.status === 422 ? " Exportieren Sie das Bauteil als Volumenkörper im Format STEP AP214 oder AP242." : "";
      setError({ title, detail: `${err.message}.${hint}` });
    } finally {
      setBusy(false);
    }
  }

  const category = materials.find((m) => m.key === result?.engine_input.cad_metadata.requested_material)?.category;
  const supplier = caps?.supplier;

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <BrandMark />
          <div>
            {supplier?.name ?? "Lohnfertigung"}
            <small>Sofortangebot · Instant quote</small>
          </div>
        </div>
        {caps && (
          <div className="capacity" aria-label="Maschinenverfügbarkeit">
            {caps.machines.map((m) => (
              <span key={m.process}>
                <span className={`dot${m.available ? "" : " off"}`} aria-hidden />
                {PROCESS_LABEL[m.process].de}
                {!m.available && " – ausgelastet"}
              </span>
            ))}
            <span>
              Vorlauf <span className="figure">{caps.current_backlog_days}</span> AT
            </span>
          </div>
        )}
      </header>

      <main>
        <section className="intro">
          <h1>
            Angebot für Ihr Frästeil oder Drehteil – <em>direkt aus der STEP-Datei.</em>
          </h1>
          <p>
            Wir erkennen Bohrungen, Gewinde, Taschen und Freiformflächen, wählen die passende Maschine und kalkulieren
            Preis und Lieferzeit mit unserer aktuellen Auslastung.
            <span className="en">
              Upload a STEP file: we recognise features, pick the machine and price it against today&apos;s shop-floor
              capacity.
            </span>
          </p>
        </section>

        <div className="workspace">
          <UploadPanel materials={materials} capabilities={caps} busy={busy} onSubmit={run} />
          <div ref={sheetRef} style={{ minWidth: 0, scrollMarginTop: 16 }}>
            {error && (
              <div className="error" role="alert" style={{ marginBottom: 16 }}>
                <strong>{error.title}</strong>
                {error.detail}
              </div>
            )}
            {result ? (
              <QuoteSheet
                data={result}
                materialCategory={category}
                onReset={() => {
                  setResult(null);
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
              />
            ) : (
              <EmptySheet busy={busy} />
            )}
          </div>
        </div>
      </main>
    </>
  );
}
