"use client";

import Link from "next/link";
import { num } from "@/lib/format";
import { useSession } from "@/lib/session";

/** Plan name and how many of this month's quotes are used, with the next step up. */
export default function UsageMeter() {
  const { me } = useSession();
  if (!me) return null;
  const { plan, usage } = me;
  const limit = usage.quotes_per_month;
  const share = limit ? Math.min(usage.quotes_this_month / limit, 1) : 0;

  return (
    <aside className="panel usage" aria-label="Kontingent">
      <div className="usage-head">
        <span className={`plan-badge plan-${plan.key}`}>{plan.name}</span>
        <span className="figure">
          {num(usage.quotes_this_month)} / {limit === null ? "∞" : num(limit)}
        </span>
      </div>
      <span className="label">
        Angebote diesen Monat <span className="en">· quotes this month</span>
      </span>
      {limit !== null && (
        <div
          className="meter"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={limit}
          aria-valuenow={usage.quotes_this_month}
        >
          <span style={{ width: `${share * 100}%` }} className={share >= 1 ? "full" : undefined} />
        </div>
      )}
      {!me.account ? (
        <p className="help">
          <Link href="/signup">Kostenloses Konto</Link> für mehr Angebote, oder <Link href="/pricing">Pro testen</Link>{" "}
          für KI-Prüfung und PDF-Angebote.
        </p>
      ) : (
        !plan.features.includes("cost_breakdown") && (
          <p className="help">
            <Link href="/pricing">Upgrade auf Pro</Link>: vollständige Kalkulation, KI-Prüfung, PDF-Angebot.
          </p>
        )
      )}
    </aside>
  );
}
