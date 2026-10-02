"use client";

// Free vs paid plans. Everything shown comes from GET /api/v1/plans, i.e. from the
// backend's billing/plans.py - change a price or feature there, not here.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, getPlans, startCheckout, type Plan, type PlanCatalog } from "@/lib/api";
import { eur, num } from "@/lib/format";
import { useSession } from "@/lib/session";

export default function PricingTable() {
  const [catalog, setCatalog] = useState<PlanCatalog | null>(null);
  const [failed, setFailed] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { me } = useSession();
  const router = useRouter();

  useEffect(() => {
    getPlans()
      .then(setCatalog)
      .catch(() => setFailed(true));
  }, []);

  async function choose(plan: Plan) {
    setError(null);
    if (!me?.account) {
      router.push(`/signup?plan=${plan.key}`);
      return;
    }
    if (!plan.purchasable) {
      router.push("/quote");
      return;
    }
    setPending(plan.key);
    try {
      const { url } = await startCheckout(plan.key);
      window.location.assign(url); // Stripe Checkout (or /account in demo mode)
    } catch (e) {
      setError((e as ApiError).message);
      setPending(null);
    }
  }

  if (failed) return <p className="error">Preise konnten nicht geladen werden. Bitte später erneut versuchen.</p>;
  if (!catalog) return <div className="pricing-grid skeleton" aria-busy="true" />;

  const current = me?.plan.key;
  return (
    <div>
      <div className="pricing-grid">
        {catalog.plans.map((plan) => {
          const featured = plan.key === "pro";
          const isCurrent = current === plan.key;
          return (
            <article key={plan.key} className={`price-card${featured ? " featured" : ""}`}>
              {featured && <span className="ribbon">Beliebt</span>}
              <h3>{plan.name}</h3>
              <p className="tagline">
                {plan.tagline_de}
                <span className="en">{plan.tagline_en}</span>
              </p>
              <p className="price">
                <span className="figure">{plan.price_eur_month === 0 ? "0 €" : eur(plan.price_eur_month)}</span>
                <span className="per">/ Monat zzgl. MwSt.</span>
              </p>
              <ul className="limits">
                <li>
                  <b className="figure">{plan.quotes_per_month === null ? "Unbegrenzt" : num(plan.quotes_per_month)}</b>{" "}
                  Angebote / Monat
                </li>
                <li>
                  bis <b className="figure">{num(plan.max_quantity)}</b> Stück je Angebot
                </li>
              </ul>
              <ul className="feature-list">
                {catalog.features.map((f) => {
                  const on = plan.features.includes(f.key);
                  return (
                    <li key={f.key} className={on ? "on" : "off"}>
                      <span aria-hidden>{on ? "✓" : "–"}</span>
                      {!on && <span className="sr-only">Nicht enthalten: </span>}
                      {f.de}
                    </li>
                  );
                })}
              </ul>
              {isCurrent ? (
                <Link className="btn ghost" href="/account">
                  Ihr aktueller Plan
                </Link>
              ) : (
                <button
                  type="button"
                  className={`btn${featured ? "" : " ghost"}`}
                  disabled={pending !== null || (catalog.checkout === "disabled" && plan.purchasable)}
                  onClick={() => choose(plan)}
                >
                  {pending === plan.key
                    ? "Weiterleitung …"
                    : plan.purchasable
                      ? `${plan.name} wählen`
                      : me?.account
                        ? "Angebot erstellen"
                        : "Kostenlos starten"}
                </button>
              )}
            </article>
          );
        })}
      </div>
      {error && (
        <p className="error" role="alert" style={{ marginTop: 16 }}>
          {error}
        </p>
      )}
      <p className="fineprint" style={{ marginTop: 16 }}>
        {catalog.vat_note}. Monatlich kündbar. Sichere Zahlung über Stripe.
        {catalog.checkout === "demo" && " Demo-Modus: Upgrades werden ohne Zahlung freigeschaltet."}
        {catalog.checkout === "disabled" && " Online-Zahlung ist derzeit nicht aktiviert."}
      </p>
    </div>
  );
}
