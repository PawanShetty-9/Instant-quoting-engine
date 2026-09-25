import type { Feasibility, ProcessKey } from "./api";

const eurFmt = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
const numFmt = (digits: number) =>
  new Intl.NumberFormat("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const eur = (v: number) => eurFmt.format(v);
export const num = (v: number, digits = 0) => numFmt(digits).format(v);

export function duration(hours: number): string {
  const total = Math.round(hours * 60);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h > 0 ? `${h} h ${String(m).padStart(2, "0")} min` : `${m} min`;
}

export function dateDe(iso: string): string {
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export const PROCESS_LABEL: Record<ProcessKey, { de: string; en: string }> = {
  CNC_3_Axis: { de: "3-Achs-Fräsen", en: "3-axis milling" },
  CNC_5_Axis: { de: "5-Achs-Fräsen", en: "5-axis milling" },
  Lathe: { de: "CNC-Drehen", en: "CNC turning" },
};

export const FEASIBILITY: Record<Feasibility, { de: string; en: string; tone: "ok" | "review" | "no"; icon: string }> = {
  Feasible: { de: "Freigegeben", en: "Feasible", tone: "ok", icon: "✓" },
  "Review Required": { de: "Prüfung erforderlich", en: "Review required", tone: "review", icon: "!" },
  Infeasible: { de: "Nicht fertigbar", en: "Infeasible", tone: "no", icon: "✕" },
};

export function splitNotes(notes: string): { de: string; en: string } {
  const m = notes.match(/^DE:\s*([\s\S]*?)\s*\|\s*EN:\s*([\s\S]*)$/);
  if (!m) return { de: notes, en: "" };
  return { de: m[1].trim(), en: m[2].replace(/\s*\|\|[\s\S]*$/, "").trim() };
}
