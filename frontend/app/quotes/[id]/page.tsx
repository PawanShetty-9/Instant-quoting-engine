"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, getQuote, type QuoteResponse } from "@/lib/api";
import { FEASIBILITY, PROCESS_LABEL, dateDe, duration, eur, num, splitNotes } from "@/lib/format";
import "./print.css";

type Lang = "de" | "en";

const T = {
  de: {
    title: "Angebot",
    returnLine: "",
    recipient: "Online-Anfrage",
    quoteNo: "Angebots-Nr.",
    date: "Datum",
    valid: "Gültig bis",
    yourRef: "Ihr Zeichen",
    handledBy: "Bearbeitung",
    auto: "Automatisches Angebot",
    intro: "vielen Dank für Ihre Anfrage. Auf Grundlage der übermittelten 3D-Daten bieten wir Ihnen freibleibend an:",
    salutation: "Sehr geehrte Damen und Herren,",
    pos: "Pos.",
    desc: "Bezeichnung",
    qty: "Menge",
    unit: "Einzelpreis",
    total: "Gesamtpreis",
    pcs: "Stk.",
    net: "Nettobetrag",
    vat: "zzgl. Umsatzsteuer",
    gross: "Gesamtbetrag",
    lead: "Lieferzeit",
    leadText: (d: number) => `${d} Arbeitstage nach Auftragsbestätigung`,
    process: "Verfahren",
    material: "Werkstoff",
    envelope: "Hüllmaß",
    time: "Fertigungszeit",
    review: "Technische Prüfung",
    terms: "Konditionen",
    closing: "Mit freundlichen Grüßen",
    footerMd: "Geschäftsführer",
    print: "Drucken / als PDF speichern",
    back: "Zurück zum Portal",
    nonBinding: "Unverbindliches Richtangebot – technische Prüfung erforderlich",
  },
  en: {
    title: "Quotation",
    returnLine: "",
    recipient: "Online request",
    quoteNo: "Quote no.",
    date: "Date",
    valid: "Valid until",
    yourRef: "Your reference",
    handledBy: "Prepared by",
    auto: "Automated quotation",
    intro: "thank you for your enquiry. Based on the 3D data provided we offer, without obligation:",
    salutation: "Dear Sir or Madam,",
    pos: "Item",
    desc: "Description",
    qty: "Qty",
    unit: "Unit price",
    total: "Amount",
    pcs: "pcs",
    net: "Net amount",
    vat: "plus VAT",
    gross: "Total amount",
    lead: "Lead time",
    leadText: (d: number) => `${d} business days after order confirmation`,
    process: "Process",
    material: "Material",
    envelope: "Envelope",
    time: "Machine time",
    review: "Technical review",
    terms: "Terms",
    closing: "Kind regards",
    footerMd: "Managing director",
    print: "Print / save as PDF",
    back: "Back to portal",
    nonBinding: "Non-binding indicative quote – technical review required",
  },
} as const;

export default function PrintableQuote() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<QuoteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState<Lang>("de");

  useEffect(() => {
    getQuote(id)
      .then(setData)
      .catch((e: ApiError) => setError(e.status === 404 ? "Angebot nicht gefunden oder bereits gelöscht." : e.message));
  }, [id]);

  useEffect(() => {
    if (data) document.title = `${T[lang].title} ${data.quote.quote_id}`;
  }, [data, lang]);

  if (error) {
    return (
      <main className="letter-screen">
        <div className="error" role="alert">
          <strong>Angebot {id}</strong>
          {error}
        </div>
      </main>
    );
  }
  if (!data) {
    return (
      <main className="letter-screen">
        <p className="en">Angebot wird geladen …</p>
      </main>
    );
  }

  if (!data.entitlements.features.includes("printable_quote")) {
    return (
      <main className="letter-screen">
        <div className="error" role="alert">
          <strong>Druckfertiges Angebot ist Teil von Pro</strong>
          Das Angebot {data.quote.quote_id} wurde im {data.entitlements.plan}-Plan erstellt.{" "}
          <a href="/pricing">Pläne ansehen</a>
        </div>
      </main>
    );
  }

  const t = T[lang];
  const { quote, commercial: c, engine_input: ei } = data;
  const s = c.supplier;
  const b = quote.cost_breakdown;
  const [x, y, z] = ei.cad_metadata.bounding_box;
  const notes = splitNotes(quote.feasibility_notes);
  const f = FEASIBILITY[quote.feasibility];
  const terms = lang === "de" ? c.terms_de : c.terms_en;

  return (
    <main className="letter-screen">
      <div className="toolbar no-print">
        <a href="/" className="btn ghost">
          ← {t.back}
        </a>
        <div className="lang" role="group" aria-label="Sprache / Language">
          {(["de", "en"] as const).map((l) => (
            <button key={l} type="button" aria-pressed={lang === l} onClick={() => setLang(l)}>
              {l.toUpperCase()}
            </button>
          ))}
        </div>
        <button type="button" className="btn" onClick={() => window.print()}>
          {t.print}
        </button>
      </div>

      <article className="letter" lang={lang}>
        <header className="letterhead">
          <div className="lh-name">{s.name}</div>
          <div className="lh-contact">
            {s.street} · {s.city}
            <br />
            {s.phone} · {s.email}
          </div>
        </header>

        <section className="address-zone">
          <div className="return-line">
            {s.name} · {s.street} · {s.city}
          </div>
          <div className="recipient">
            {c.customer_reference ? `${t.yourRef}: ${c.customer_reference}` : t.recipient}
          </div>
        </section>

        <dl className="info-block">
          <dt>{t.quoteNo}</dt>
          <dd className="code">{quote.quote_id}</dd>
          <dt>{t.date}</dt>
          <dd className="figure">{dateDe(c.created_at)}</dd>
          <dt>{t.valid}</dt>
          <dd className="figure">{dateDe(c.valid_until)}</dd>
          {c.customer_reference && (
            <>
              <dt>{t.yourRef}</dt>
              <dd>{c.customer_reference}</dd>
            </>
          )}
          <dt>{t.handledBy}</dt>
          <dd>{t.auto}</dd>
        </dl>

        <h1 className="subject">
          {t.title} {quote.quote_id}
          {c.file_name ? ` – ${c.file_name}` : ""}
        </h1>
        {quote.feasibility !== "Feasible" && (
          <p className={`banner ${f.tone}`}>
            <span aria-hidden>{f.icon}</span> {t.nonBinding}
          </p>
        )}

        <p>{t.salutation}</p>
        <p>{t.intro}</p>

        <table className="positions">
          <thead>
            <tr>
              <th>{t.pos}</th>
              <th>{t.desc}</th>
              <th className="num">{t.qty}</th>
              <th className="num">{t.unit}</th>
              <th className="num">{t.total}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>1</td>
              <td>
                <strong>{c.file_name ?? "CAD-Bauteil"}</strong>
                <div className="pos-meta">
                  {t.material}: {c.material_label}
                  <br />
                  {t.process}: {PROCESS_LABEL[quote.selected_process][lang]} · {t.envelope} {num(x, 1)} × {num(y, 1)} ×{" "}
                  {num(z, 1)} mm
                  <br />
                  {t.time}: {duration(quote.estimated_production_time_hours)}
                </div>
              </td>
              <td className="num figure">
                {num(c.quantity)} {t.pcs}
              </td>
              <td className="num figure">{eur(c.unit_price_net_eur)}</td>
              <td className="num figure">{eur(b.net_total_eur)}</td>
            </tr>
          </tbody>
        </table>

        <table className="totals">
          <tbody>
            <tr>
              <th>{t.net}</th>
              <td className="figure">{eur(b.net_total_eur)}</td>
            </tr>
            <tr>
              <th>
                {t.vat} {num(c.vat_rate_percent)} %
              </th>
              <td className="figure">{eur(b.vat_19_eur)}</td>
            </tr>
            <tr className="grand">
              <th>{t.gross}</th>
              <td className="figure">{eur(b.gross_total_eur)}</td>
            </tr>
          </tbody>
        </table>

        <p>
          <strong>{t.lead}:</strong> {t.leadText(quote.recommended_lead_time_days)}
        </p>

        <h2>{t.review}</h2>
        <p className="review">
          <span className={`tone ${f.tone}`}>
            {f.icon} {lang === "de" ? f.de : f.en}
          </span>{" "}
          {lang === "de" ? notes.de : notes.en || notes.de}
        </p>

        <h2>{t.terms}</h2>
        <ol className="terms">
          {terms.map((term) => (
            <li key={term}>{term}</li>
          ))}
        </ol>

        <p className="closing">
          {t.closing}
          <br />
          {s.name}
        </p>

        <footer className="letter-footer">
          <div>
            {s.name}
            <br />
            {s.street}
            <br />
            {s.city}, {s.country}
          </div>
          <div>
            {s.commercial_register}
            <br />
            {t.footerMd}: {s.managing_director}
          </div>
          <div>
            USt-IdNr.: {s.vat_id}
            <br />
            {s.email}
          </div>
        </footer>
      </article>
    </main>
  );
}
