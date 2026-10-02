import type { Metadata } from "next";
import Link from "next/link";
import PricingTable from "@/components/PricingTable";
import SiteHeader from "@/components/SiteHeader";
import HeroPartLoader from "@/components/HeroPartLoader";

export const metadata: Metadata = {
  title: { absolute: "Sofortangebot CNC – Angebot für Frästeile und Drehteile in Sekunden" },
};

const STEPS = [
  {
    n: "01",
    de: "STEP-Datei hochladen",
    en: "Upload STEP, IGES or STL",
    text: "Ziehen Sie Ihr 3D-Modell auf die Seite. Die Datei bleibt auf unserem Server in Deutschland.",
  },
  {
    n: "02",
    de: "Geometrie wird analysiert",
    en: "Features & machine",
    text: "Bohrungen, Gewinde, Taschen und Freiformflächen werden erkannt, die passende Maschine gewählt.",
  },
  {
    n: "03",
    de: "Preis & Lieferzeit",
    en: "Price & lead time",
    text: "Netto, 19 % MwSt und brutto centgenau – mit Lieferzeit aus der aktuellen Maschinenauslastung.",
  },
];

const FEATURES = [
  {
    de: "Echte CAD-Analyse",
    text: "OpenCascade-Kernel wie in professionellen CAM-Systemen: Volumen, Rohteil, Bearbeitungsrichtungen, Lochtiefen.",
  },
  {
    de: "Live-Kapazität",
    text: "Ist eine Maschine ausgelastet, plant das System auf eine freie, geeignete Maschine um – statt pauschal Tage aufzuschlagen.",
  },
  {
    de: "Rohteil statt Fertigteil",
    text: "Material wird auf den gekauften Rohling gerechnet. Kein Unterpreis bei Titan-Schaufeln oder Taschenteilen.",
  },
  {
    de: "KI-Prüfung mit Leitplanken",
    text: "Claude prüft wie ein erfahrener Kalkulator. Jeder Euro wird vom deterministischen Rechenkern verifiziert.",
  },
  {
    de: "Rechtssicher in Deutschland",
    text: "DIN-5008-Angebot, Incoterms® 2020, ISO 2768-mK, § 377 HGB, DSGVO – zweisprachig Deutsch/Englisch.",
  },
  {
    de: "ERP/MES-Schnittstelle",
    text: "REST-API mit eigenem Schlüssel: Angebote aus dem ERP anfragen, Auslastung aus dem MES einspeisen.",
  },
];

export default function Landing() {
  return (
    <>
      <SiteHeader />
      <main>
        <section className="hero">
          <div className="hero-copy">
            <span className="label">Instant quoting · CNC-Fräsen &amp; Drehen</span>
            <h1>
              Vom 3D-Modell zum Angebot – <em>in Sekunden.</em>
            </h1>
            <p>
              Laden Sie eine STEP-Datei hoch und erhalten Sie sofort Preis, Lieferzeit und ein druckfertiges Angebot.
              Kalkuliert mit echter Geometrie und der aktuellen Auslastung der Fertigung.
              <span className="en">
                Upload a STEP file, get a VAT-compliant quote with lead time in seconds – priced from real geometry and
                live shop-floor capacity.
              </span>
            </p>
            <div className="hero-cta">
              <Link className="btn" href="/quote">
                Kostenlos Angebot erstellen
              </Link>
              <Link className="btn ghost" href="/pricing">
                Preise ansehen
              </Link>
            </div>
            <p className="fineprint">Ohne Anmeldung testen · keine Kreditkarte nötig</p>
          </div>
          <HeroPartLoader />
        </section>

        <section className="band" aria-labelledby="how">
          <h2 id="how" className="section-title">
            So funktioniert&apos;s <span className="en">How it works</span>
          </h2>
          <ol className="steps">
            {STEPS.map((s) => (
              <li key={s.n}>
                <span className="step-n figure">{s.n}</span>
                <h3>
                  {s.de}
                  <span className="en">{s.en}</span>
                </h3>
                <p>{s.text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="band" id="features" aria-labelledby="features-title">
          <h2 id="features-title" className="section-title">
            Funktionen <span className="en">Features</span>
          </h2>
          <div className="feature-grid">
            {FEATURES.map((f) => (
              <div key={f.de} className="card">
                <h3>{f.de}</h3>
                <p>{f.text}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="band" id="pricing" aria-labelledby="pricing-title">
          <h2 id="pricing-title" className="section-title">
            Preise <span className="en">Pricing</span>
          </h2>
          <PricingTable />
        </section>

        <section className="band cta-band">
          <h2>Probieren Sie es mit Ihrem eigenen Bauteil.</h2>
          <Link className="btn" href="/quote">
            Jetzt Angebot erstellen
          </Link>
        </section>
      </main>
    </>
  );
}
