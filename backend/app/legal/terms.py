"""Standard commercial terms printed on every automated quote (DE binding, EN convenience).

These texts are a professionally drafted *template* for German B2B contract
manufacturing. Have them reviewed by your legal counsel and aligned with your
own AGB (Allgemeine Verkaufs- und Lieferbedingungen) before production use.
"""

from __future__ import annotations

from app.config import Settings


def terms(settings: Settings, ai_used: bool) -> tuple[list[str], list[str]]:
    vat = f"{settings.vat_rate_percent:g}"
    days = settings.quote_validity_days
    retention = settings.quote_retention_days
    ai_de = (
        " Zur KI-gestützten Plausibilitätsprüfung werden ausschließlich abgeleitete geometrische"
        " Kennwerte (Abmessungen, Volumen, Merkmalsanzahl) an einen KI-Dienstleister als"
        " Auftragsverarbeiter übermittelt, nicht jedoch die CAD-Datei selbst."
        if ai_used
        else ""
    )
    ai_en = (
        " For AI-assisted plausibility checks only derived geometric parameters (dimensions, volume,"
        " feature counts) are transmitted to an AI service provider acting as processor - never the"
        " CAD file itself."
        if ai_used
        else ""
    )
    de = [
        "Dieses Angebot wurde automatisiert auf Grundlage der übermittelten 3D-Daten erstellt und ist"
        " freibleibend. Ein Vertrag kommt erst mit unserer schriftlichen Auftragsbestätigung zustande.",
        f"Alle Preise verstehen sich in Euro netto zuzüglich der gesetzlichen Umsatzsteuer von derzeit"
        f" {vat} % (§ 12 Abs. 1 UStG). Innergemeinschaftliche Lieferungen an Unternehmer mit gültiger"
        " USt-IdNr. erfolgen steuerfrei gemäß § 4 Nr. 1 Buchst. b i. V. m. § 6a UStG.",
        f"Preisbindung: {days} Kalendertage ab Angebotsdatum. Bei Edelstahl und Buntmetallen bleibt die"
        " Anpassung an den am Liefertag gültigen Legierungs- bzw. Metallzuschlag vorbehalten.",
        "Technische Grundlage sind ausschließlich die übermittelten CAD-Daten. Ohne Zeichnung gelten"
        " Allgemeintoleranzen nach DIN ISO 2768-1 m und DIN ISO 2768-2 K sowie Rauheit Ra 3,2 µm."
        " Wärmebehandlung, Oberflächenbeschichtung, Entgraten über Standard hinaus und Sonderprüfungen"
        " sind nicht enthalten. Gewinde werden gemäß Zeichnungsangabe gefertigt.",
        "Werkstoffnachweis: Werkszeugnis 2.2 nach DIN EN 10204 inklusive; Abnahmeprüfzeugnis 3.1 gegen Aufpreis.",
        "Lieferzeit in Arbeitstagen ab Auftragsbestätigung und Klärung aller technischen Einzelheiten."
        " Lieferung FCA Werk (Incoterms® 2020), Standardverpackung inklusive.",
        "Zahlungsbedingungen: 30 Tage netto ab Rechnungsdatum.",
        "Es gelten die Untersuchungs- und Rügeobliegenheiten gemäß § 377 HGB sowie unsere Allgemeinen"
        " Verkaufs- und Lieferbedingungen. Abweichende Einkaufsbedingungen des Bestellers werden nicht"
        " Vertragsbestandteil.",
        "Vertraulichkeit und Datenschutz: Ihre CAD-Daten werden als Geschäftsgeheimnis (GeschGehG)"
        " behandelt, ausschließlich zur Angebotserstellung verarbeitet (Art. 6 Abs. 1 lit. b DSGVO) und"
        f" nach {retention} Tagen gelöscht.{ai_de}",
    ]
    en = [
        "This quotation was generated automatically from the 3D data provided and is non-binding"
        " (freibleibend). A contract is only concluded upon our written order confirmation.",
        f"All prices are in euros, net, plus statutory German VAT of currently {vat} % (Sec. 12 (1)"
        " UStG). Intra-community supplies to businesses with a valid VAT ID are VAT-exempt under"
        " Sec. 4 No. 1(b) in conjunction with Sec. 6a UStG.",
        f"Price validity: {days} calendar days from the quotation date. For stainless steel and"
        " non-ferrous metals we reserve the right to adjust to the alloy/metal surcharge valid on the"
        " delivery date.",
        "The technical basis is exclusively the CAD data provided. Without a drawing, general"
        " tolerances per ISO 2768-1 m and ISO 2768-2 K and surface roughness Ra 3.2 um apply. Heat"
        " treatment, coating, deburring beyond standard and special inspections are not included."
        " Threads are produced as specified on the drawing.",
        "Material certification: inspection document 2.2 per EN 10204 included; 3.1 certificate at extra charge.",
        "Lead time in business days from order confirmation and clarification of all technical"
        " details. Delivery FCA works (Incoterms® 2020), standard packaging included.",
        "Payment terms: 30 days net from invoice date.",
        "The inspection and notification duties of Sec. 377 German Commercial Code (HGB) and our"
        " General Terms of Sale and Delivery apply. Conflicting purchasing terms of the buyer do not"
        " become part of the contract.",
        "Confidentiality and data protection: your CAD data is treated as a trade secret (GeschGehG),"
        " processed solely to prepare this quotation (Art. 6(1)(b) GDPR) and deleted after"
        f" {retention} days.{ai_en}",
    ]
    return de, en
