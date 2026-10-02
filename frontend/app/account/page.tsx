"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import SiteHeader from "@/components/SiteHeader";
import UsageMeter from "@/components/UsageMeter";
import { ApiError, getQuoteHistory, openBillingPortal, rotateApiKey, type QuoteSummary } from "@/lib/api";
import { FEASIBILITY, PROCESS_LABEL, dateDe, eur, num } from "@/lib/format";
import { useSession } from "@/lib/session";

const BANNER: Record<string, string> = {
  success: "Vielen Dank! Ihr Abo ist aktiv – es kann einige Sekunden dauern, bis der Plan hier erscheint.",
  demo: "Demo-Modus: Der Plan wurde ohne Zahlung freigeschaltet.",
};

export default function AccountPage() {
  const router = useRouter();
  const { me, loading, refresh, signOut, can } = useSession();
  const [history, setHistory] = useState<QuoteSummary[] | null>(null);
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const checkout = new URLSearchParams(window.location.search).get("checkout");
    if (checkout && BANNER[checkout]) {
      setBanner(BANNER[checkout]);
      // The Stripe webhook may land a moment after the redirect.
      const t = setTimeout(() => void refresh(), 2500);
      return () => clearTimeout(t);
    }
  }, [refresh]);

  useEffect(() => {
    if (!loading && !me?.account) router.replace("/login");
  }, [loading, me, router]);

  const showHistory = can("quote_history");
  useEffect(() => {
    if (showHistory)
      getQuoteHistory()
        .then(setHistory)
        .catch(() => setHistory([]));
  }, [showHistory]);

  async function run(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  const account = me?.account;
  if (!account) {
    return (
      <>
        <SiteHeader />
        <main className="page">
          <p className="en">Konto wird geladen …</p>
        </main>
      </>
    );
  }

  return (
    <>
      <SiteHeader />
      <main className="page">
        <header className="page-head">
          <h1>
            Ihr Konto <span className="en">Account</span>
          </h1>
          <p>
            {account.email}
            {account.company && ` · ${account.company}`}
          </p>
        </header>
        {banner && <p className="notice">{banner}</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <div className="account-grid">
          <UsageMeter />

          <section className="card">
            <h2>
              Plan & Abrechnung <span className="en">Billing</span>
            </h2>
            <p>
              Aktueller Plan: <b>{account.plan.name}</b>
              {account.plan.price_eur_month > 0 && ` · ${eur(account.plan.price_eur_month)} / Monat zzgl. MwSt.`}
            </p>
            <div className="actions">
              {account.plan.key !== "business" && (
                <Link className="btn" href="/pricing">
                  Upgrade
                </Link>
              )}
              {account.has_billing && (
                <button
                  className="btn ghost"
                  type="button"
                  onClick={() => run(async () => window.location.assign((await openBillingPortal()).url))}
                >
                  Zahlung & Kündigung verwalten
                </button>
              )}
              <button
                className="btn ghost"
                type="button"
                onClick={() =>
                  run(async () => {
                    await signOut();
                    router.push("/");
                  })
                }
              >
                Abmelden
              </button>
            </div>
          </section>

          {can("api_access") && (
            <section className="card">
              <h2>
                API-Zugang <span className="en">API key</span>
              </h2>
              <p className="help">
                Für ERP/MES: <code className="code">POST /api/v1/engine/evaluate</code> mit Header{" "}
                <code className="code">X-API-Key</code>.
              </p>
              {apiKey ? (
                <>
                  <p className="help">Nur jetzt sichtbar – bitte sicher speichern:</p>
                  <pre className="key">{apiKey}</pre>
                </>
              ) : (
                <button
                  className="btn ghost"
                  type="button"
                  onClick={() =>
                    run(async () => {
                      setApiKey((await rotateApiKey()).api_key);
                      await refresh();
                    })
                  }
                >
                  {account.has_api_key ? "Neuen Schlüssel erzeugen (alter wird ungültig)" : "API-Schlüssel erzeugen"}
                </button>
              )}
            </section>
          )}
        </div>

        <section className="card" style={{ marginTop: 16 }}>
          <h2>
            Angebotsverlauf <span className="en">Quote history</span>
          </h2>
          {!showHistory ? (
            <p className="help">
              Der Verlauf ist Teil von Pro. <Link href="/pricing">Pläne vergleichen</Link>
            </p>
          ) : history === null ? (
            <p className="en">Wird geladen …</p>
          ) : history.length === 0 ? (
            <p className="help">
              Noch keine Angebote. <Link href="/quote">Erstes Angebot erstellen</Link>
            </p>
          ) : (
            <div className="table-wrap">
              <table className="history">
                <thead>
                  <tr>
                    <th>Angebot</th>
                    <th>Datum</th>
                    <th>Datei</th>
                    <th>Verfahren</th>
                    <th className="num">Stück</th>
                    <th className="num">Netto</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((q) => (
                    <tr key={q.quote_id}>
                      <td>
                        <Link className="code" href={`/quotes/${q.quote_id}`}>
                          {q.quote_id}
                        </Link>
                      </td>
                      <td className="figure">{dateDe(q.created_at)}</td>
                      <td>{q.file_name ?? "—"}</td>
                      <td>{PROCESS_LABEL[q.selected_process]?.de ?? q.selected_process}</td>
                      <td className="num figure">{num(q.quantity)}</td>
                      <td className="num figure">{eur(q.net_total_eur)}</td>
                      <td>{FEASIBILITY[q.feasibility].de}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </>
  );
}
