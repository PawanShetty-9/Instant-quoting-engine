import type { Feasibility } from "@/lib/api";
import { FEASIBILITY } from "@/lib/format";

/** Inspection stamp (Prüfstempel). Icon + wording carry the state, colour only reinforces it. */
export default function Stamp({ value, engine }: { value: Feasibility; engine: "claude" | "rules" }) {
  const f = FEASIBILITY[value];
  return (
    <div className={`stamp ${f.tone}`} role="status" aria-label={`Machbarkeit: ${f.de} (${f.en})`}>
      <span className="icon" aria-hidden>
        {f.icon}
      </span>
      <span className="de">{f.de}</span>
      <span className="en">{f.en}</span>
      <span className="who">{engine === "claude" ? "KI-geprüft · AI reviewed" : "Regelwerk · Rules"}</span>
    </div>
  );
}
