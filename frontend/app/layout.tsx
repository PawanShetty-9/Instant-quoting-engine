import type { Metadata, Viewport } from "next";
// Fonts are self-hosted from npm (no request to Google at runtime - GDPR, cf. LG München I 3 O 17493/20).
import "@fontsource-variable/archivo/wdth.css";
import "@fontsource/b612-mono/400.css";
import "./globals.css";
import "./site.css";
import SiteFooter from "@/components/SiteFooter";
import { SessionProvider } from "@/lib/session";

export const metadata: Metadata = {
  title: { default: "Sofortangebot CNC – Instant quotes for CNC parts", template: "%s · Sofortangebot CNC" },
  description:
    "STEP-Datei hochladen und in Sekunden ein Angebot für CNC-Fräs- und Drehteile erhalten – mit Lieferzeit, MwSt und 3D-Ansicht.",
};

export const viewport: Viewport = {
  themeColor: "#e9eeeb",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de">
      <body>
        <SessionProvider>
          {children}
          <SiteFooter />
        </SessionProvider>
      </body>
    </html>
  );
}
