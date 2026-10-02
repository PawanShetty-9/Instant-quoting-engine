import Link from "next/link";

/** Placeholder for a feature the current plan does not include. */
export default function Upsell({ title, en, children }: { title: string; en: string; children: React.ReactNode }) {
  return (
    <div className="card upsell">
      <h2>
        {title}
        <span className="en">{en}</span>
      </h2>
      <p>{children}</p>
      <Link className="btn ghost" href="/pricing">
        Pro freischalten
      </Link>
    </div>
  );
}
