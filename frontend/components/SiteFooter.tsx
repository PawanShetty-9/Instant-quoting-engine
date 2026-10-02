import Link from "next/link";

export default function SiteFooter() {
  return (
    <footer className="site-footer">
      <span>© {new Date().getFullYear()} Sofortangebot CNC</span>
      <nav aria-label="Rechtliches">
        <Link href="/pricing">Preise</Link>
        <Link href="/impressum">Impressum</Link>
        <Link href="/impressum#datenschutz">Datenschutz</Link>
        <Link href="/impressum#agb">AGB</Link>
      </nav>
    </footer>
  );
}
