"use client";

import { useState } from "react";
import { eur, num } from "@/lib/format";

interface Segment {
  key: string;
  de: string;
  en: string;
  value: number;
  color: string;
}

/** Composition of the net price: one stacked bar, legend with values, per-segment tooltip. */
export default function CostBar({
  material,
  machining,
  energy,
  margin,
}: {
  material: number;
  machining: number;
  energy: number;
  margin: number;
}) {
  const segments: Segment[] = [
    { key: "material", de: "Material", en: "Material", value: material, color: "var(--s-material)" },
    { key: "machining", de: "Maschinenzeit", en: "Machining", value: machining, color: "var(--s-machining)" },
    { key: "energy", de: "Energiezuschlag", en: "Energy surcharge", value: energy, color: "var(--s-energy)" },
    { key: "margin", de: "Marge", en: "Margin", value: margin, color: "var(--s-margin)" },
  ];
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const [active, setActive] = useState<string | null>(null);

  let offset = 0;
  const positioned = segments.map((s) => {
    const share = s.value / total;
    const mid = offset + share / 2;
    offset += share;
    return { ...s, share, mid };
  });
  const hovered = positioned.find((s) => s.key === active);

  return (
    <figure className="costbar" style={{ margin: 0 }}>
      <figcaption className="label">
        Zusammensetzung Nettopreis <span className="en">· Net price composition</span>
      </figcaption>
      <div className="costbar-track" onMouseLeave={() => setActive(null)}>
        {positioned.map((s) => (
          <div
            key={s.key}
            className="costbar-seg"
            style={{ flexGrow: Math.max(s.share, 0.004), flexBasis: 0, background: s.color }}
            tabIndex={0}
            role="img"
            aria-label={`${s.de}: ${eur(s.value)} (${num(s.share * 100, 1)} %)`}
            onMouseEnter={() => setActive(s.key)}
            onFocus={() => setActive(s.key)}
            onBlur={() => setActive(null)}
          />
        ))}
        {hovered && (
          <div
            className="costbar-tip"
            style={{ left: `${Math.min(Math.max(hovered.mid * 100, 12), 88)}%` }}
            role="status"
          >
            {hovered.de} · <span className="figure">{eur(hovered.value)}</span> · {num(hovered.share * 100, 1)} %
          </div>
        )}
      </div>
      <ul className="legend">
        {positioned.map((s) => (
          <li key={s.key}>
            <span className="swatch" style={{ background: s.color }} aria-hidden />
            {s.de} <span className="figure">{eur(s.value)}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
