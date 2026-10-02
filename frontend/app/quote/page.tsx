"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import QuoteSheet, { EmptySheet } from "@/components/QuoteSheet";
import SiteHeader from "@/components/SiteHeader";
import UploadPanel, { type QuoteRequest } from "@/components/UploadPanel";
import UsageMeter from "@/components/UsageMeter";
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
import { useSession } from "@/lib/session";

export default function QuotePage() {
  const [materials, setMaterials] = useState<MaterialOption[]>([]);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<QuoteResponse | null>(null);
  const [error, setError] = useState<{ title: string; detail: string; upgrade?: boolean } | null>(null);
  const { me, refresh } = useSession();
  const sheetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getMaterials()
      .then(setMaterials)
      .catch(() => undefined);
    getCapabilities()
      .then(setCaps)
      .catch(() => undefined);
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
        err.status === 402
          ? "Planlimit erreicht"
          : err.status === 413
            ? "Datei zu groß"
            : err.status === 429
              ? "Zu viele Anfragen"
              : err.status === 422
                ? "Datei konnte nicht kalkuliert werden"
                : "Kalkulation fehlgeschlagen";
      const hint =
        err.status === 422 ? " Exportieren Sie das Bauteil als Volumenkörper im Format STEP AP214 oder AP242." : "";
      setError({ title, detail: `${err.message}.${hint}`, upgrade: err.status === 402 });
    } finally {
      setBusy(false);
      void refresh(); // usage meter
    }
  }

  // The plan may allow fewer pieces than the shop's technical maximum.
  const effectiveCaps = useMemo(
    () => (caps && me ? { ...caps, max_quantity: Math.min(caps.max_quantity, me.plan.max_quantity) } : caps),
    [caps, me],
  );

  const category = materials.find((m) => m.key === result?.engine_input.cad_metadata.requested_material)?.category;

  return (
    <>
      <SiteHeader>
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
      </SiteHeader>

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
          <div style={{ display: "grid", gap: 16, minWidth: 0 }}>
            <UploadPanel materials={materials} capabilities={effectiveCaps} busy={busy} onSubmit={run} />
            <UsageMeter />
          </div>
          <div ref={sheetRef} style={{ minWidth: 0, scrollMarginTop: 16 }}>
            {error && (
              <div className="error" role="alert" style={{ marginBottom: 16 }}>
                <strong>{error.title}</strong>
                {error.detail}
                {error.upgrade && (
                  <p style={{ margin: "8px 0 0" }}>
                    <Link href={me?.account ? "/pricing" : "/signup"}>
                      {me?.account ? "Pläne vergleichen und upgraden →" : "Kostenloses Konto anlegen →"}
                    </Link>
                  </p>
                )}
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
