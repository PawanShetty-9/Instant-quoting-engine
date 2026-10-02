"use client";

import { useEffect, useState } from "react";
import SiteHeader from "@/components/SiteHeader";
import { getCapabilities, type Supplier } from "@/lib/api";

// Impressum (§ 5 DDG), privacy and terms. Company data come from the backend's QUOTE_COMPANY_*
// settings, the same data printed on every quote. The legal texts are templates: have them
// reviewed before selling.
const PLACEHOLDER_VAT = "DE000000000";

export default function Impressum() {
  const [s, setS] = useState<Supplier | null>(null);
  useEffect(() => {
    getCapabilities()
      .then((c) => setS(c.supplier))
      .catch(() => undefined);
  }, []);

  return (
    <>
      <SiteHeader />
      <main className="page legal">
        {s?.vat_id === PLACEHOLDER_VAT && (
          <p className="error" role="note">
            <strong>Platzhalterdaten</strong>
            Diese Angaben sind Beispielwerte. Vor dem Verkauf QUOTE_COMPANY_* im Backend setzen und die Texte juristisch
            prüfen lassen.
          </p>
        )}
        <h1>Impressum</h1>
        {s ? (
          <address>
            {s.name}
            <br />
            {s.street}
            <br />
            {s.city}
            <br />
            {s.country}
            <br />
            <br />
            Telefon: {s.phone}
            <br />
            E-Mail: <a href={`mailto:${s.email}`}>{s.email}</a>
            <br />
            Geschäftsführer: {s.managing_director}
            <br />
            {s.commercial_register}
            <br />
            USt-IdNr.: {s.vat_id}
          </address>
        ) : (
          <p className="en">Wird geladen …</p>
        )}

        <h2 id="datenschutz">Datenschutz</h2>
        <p>
          Hochgeladene CAD-Dateien werden ausschließlich zur Erstellung des Angebots auf unseren Servern verarbeitet und
          nach Ablauf der Aufbewahrungsfrist automatisch gelöscht. Für die optionale KI-Prüfung werden nur abgeleitete
          Kennwerte (Abmessungen, Volumen, Merkmalsanzahl) an einen Auftragsverarbeiter übermittelt, nie die Datei
          selbst. Für Konten speichern wir E-Mail-Adresse, Firma und ein Passwort-Hash; Zahlungsdaten verarbeitet
          ausschließlich Stripe. Ohne Konto speichern wir nur einen nicht umkehrbaren Hash Ihrer IP-Adresse zur
          Kontingentzählung. Es werden keine Tracking-Cookies gesetzt.
        </p>

        <h2 id="agb">AGB (Kurzfassung)</h2>
        <p>
          Automatische Angebote sind freibleibend. Ein Vertrag kommt erst mit unserer Auftragsbestätigung zustande. Es
          gelten die auf jedem Angebot abgedruckten Konditionen (Incoterms® 2020 FCA, ISO 2768-mK, § 377 HGB).
          Abonnements sind monatlich kündbar; Preise verstehen sich zzgl. 19 % MwSt. Das Angebot richtet sich
          ausschließlich an Unternehmer im Sinne von § 14 BGB.
        </p>
      </main>
    </>
  );
}
