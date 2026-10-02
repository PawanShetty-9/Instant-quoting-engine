import type { Metadata } from "next";
import PricingTable from "@/components/PricingTable";
import SiteHeader from "@/components/SiteHeader";

export const metadata: Metadata = { title: "Preise" };

const FAQ = [
  {
    q: "Was ist im kostenlosen Plan enthalten?",
    a: "Sofortpreis mit Lieferzeit und 3D-Ansicht für bis zu 10 Angebote im Monat. Ohne Konto können Sie 3 Angebote testen.",
  },
  {
    q: "Kann ich jederzeit kündigen?",
    a: "Ja. Pro und Business sind monatlich kündbar – direkt im Kundenkonto über das Stripe-Kundenportal.",
  },
  {
    q: "Wer sieht meine CAD-Dateien?",
    a: "Niemand außer uns. Die Datei wird auf dem Server analysiert und nach der Aufbewahrungsfrist gelöscht. Für die KI-Prüfung werden nur Kennzahlen übermittelt, nie die Datei.",
  },
  {
    q: "Sind die Preise verbindlich?",
    a: "Automatische Angebote sind freibleibend. Teile mit Prüfhinweis werden vor Auftragsbestätigung technisch geprüft.",
  },
];

export default function PricingPage() {
  return (
    <>
      <SiteHeader />
      <main className="page">
        <header className="page-head">
          <h1>
            Ein Plan für jede Anfrage <span className="en">Plans for every enquiry</span>
          </h1>
          <p>
            Starten Sie kostenlos. Upgraden Sie, wenn Sie Kalkulation im Detail, KI-Prüfung oder API-Zugang brauchen.
          </p>
        </header>
        <PricingTable />
        <section className="faq" aria-label="Häufige Fragen">
          {FAQ.map((f) => (
            <details key={f.q}>
              <summary>{f.q}</summary>
              <p>{f.a}</p>
            </details>
          ))}
        </section>
      </main>
    </>
  );
}
