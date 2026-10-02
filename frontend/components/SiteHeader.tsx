"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "@/lib/session";

export function BrandMark() {
  // A part outline in a drawing frame corner - the product's mark.
  return (
    <svg className="brand-mark" viewBox="0 0 28 28" fill="none" aria-hidden>
      <rect x="1" y="1" width="26" height="26" rx="3" stroke="var(--ink)" strokeWidth="1.5" />
      <path d="M7 19V9h8l6 5v5z" stroke="var(--blue)" strokeWidth="1.8" strokeLinejoin="round" />
      <circle cx="11.5" cy="14" r="1.8" fill="var(--blue)" />
    </svg>
  );
}

const NAV = [
  { href: "/#features", label: "Funktionen" },
  { href: "/pricing", label: "Preise" },
  { href: "/quote", label: "Angebot erstellen" },
];

export default function SiteHeader({ children }: { children?: React.ReactNode }) {
  const pathname = usePathname();
  const { me } = useSession();
  const account = me?.account;

  return (
    <header className="topbar">
      <Link href="/" className="brand" style={{ color: "inherit", textDecoration: "none" }}>
        <BrandMark />
        <div>
          Sofortangebot CNC
          <small>Instant quoting · Fräsen &amp; Drehen</small>
        </div>
      </Link>
      {children}
      <nav className="site-nav" aria-label="Hauptnavigation">
        {NAV.map((n) => (
          <Link key={n.href} href={n.href} aria-current={pathname === n.href ? "page" : undefined}>
            {n.label}
          </Link>
        ))}
        {account ? (
          <Link href="/account" className="nav-account" aria-current={pathname === "/account" ? "page" : undefined}>
            <span className={`plan-badge plan-${account.plan.key}`}>{account.plan.name}</span>
            Konto
          </Link>
        ) : (
          <Link href="/login" className="nav-account">
            Anmelden
          </Link>
        )}
      </nav>
    </header>
  );
}
