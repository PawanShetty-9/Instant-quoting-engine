"use client";

import { useId, useMemo, useRef, useState } from "react";
import type { Capabilities, MaterialOption } from "@/lib/api";

export interface QuoteRequest {
  file: File;
  material: string;
  quantity: number;
  threadCount: number | null;
  units: "mm" | "inch";
  reference: string;
}

const SAMPLES = [
  { file: "bracket.step", de: "Halter", material: "AL_6082_T6" },
  { file: "shaft.step", de: "Welle", material: "STEEL_C45" },
  { file: "manifold.step", de: "Hydraulikblock", material: "AL_6082_T6" },
  { file: "blade.step", de: "Schaufel", material: "TI_GRADE5" },
];

export default function UploadPanel({
  materials,
  capabilities,
  busy,
  onSubmit,
}: {
  materials: MaterialOption[];
  capabilities: Capabilities | null;
  busy: boolean;
  onSubmit: (req: QuoteRequest) => void;
}) {
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [material, setMaterial] = useState("AL_6082_T6");
  const [quantity, setQuantity] = useState(1);
  const [threads, setThreads] = useState("");
  const [units, setUnits] = useState<"mm" | "inch">("mm");
  const [reference, setReference] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const accepted = capabilities?.accepted_extensions ?? [".step", ".stp", ".igs", ".iges", ".stl"];
  const maxMb = capabilities?.max_upload_mb ?? 25;
  const isStl = file?.name.toLowerCase().endsWith(".stl") ?? false;

  const groups = useMemo(() => {
    const map = new Map<string, MaterialOption[]>();
    for (const m of materials) map.set(m.category, [...(map.get(m.category) ?? []), m]);
    return [...map.entries()];
  }, [materials]);

  function accept(f: File | undefined | null) {
    setLocalError(null);
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!accepted.includes(ext)) {
      setLocalError(`Dateityp ${ext} wird nicht unterstützt. Bitte STEP (.step/.stp) hochladen.`);
      return;
    }
    if (f.size > maxMb * 1024 * 1024) {
      setLocalError(`Die Datei ist größer als ${maxMb} MB. Bitte vereinfachen oder als STEP AP242 exportieren.`);
      return;
    }
    setFile(f);
  }

  function submit(f: File | null = file, mat = material) {
    if (!f) {
      setLocalError("Bitte zuerst eine CAD-Datei auswählen.");
      return;
    }
    onSubmit({
      file: f,
      material: mat,
      quantity: Math.min(Math.max(quantity || 1, 1), capabilities?.max_quantity ?? 10000),
      threadCount: threads.trim() === "" ? null : Math.max(0, parseInt(threads, 10) || 0),
      units,
      reference: reference.trim(),
    });
  }

  async function loadSample(s: (typeof SAMPLES)[number]) {
    const res = await fetch(`/samples/${s.file}`);
    const f = new File([await res.blob()], s.file, { type: "application/step" });
    setFile(f);
    setMaterial(s.material);
    setThreads("");
    submit(f, s.material);
  }

  return (
    <form
      className="panel"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      aria-describedby={`${id}-privacy`}
    >
      <div
        className={`dropzone${drag ? " active" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          accept(e.dataTransfer.files?.[0]);
        }}
      >
        <input
          ref={inputRef}
          id={`${id}-file`}
          type="file"
          accept={accepted.join(",")}
          aria-label="CAD-Datei auswählen"
          onChange={(e) => accept(e.target.files?.[0])}
        />
        <svg width="34" height="34" viewBox="0 0 34 34" fill="none" stroke="var(--blue)" strokeWidth="1.6" aria-hidden>
          <path d="M17 22V6M10 13l7-7 7 7M6 22v6h22v-6" />
        </svg>
        <strong>STEP-Datei hier ablegen</strong>
        <span className="hint">oder klicken zum Auswählen · STEP, IGES, STL bis {maxMb} MB</span>
      </div>

      {file && (
        <div className="file-chip">
          <span>{file.name}</span>
          <button
            type="button"
            onClick={() => {
              setFile(null);
              if (inputRef.current) inputRef.current.value = "";
            }}
          >
            Entfernen
          </button>
        </div>
      )}

      <div className="field">
        <label className="label" htmlFor={`${id}-mat`}>
          Werkstoff <span className="en">· Material</span>
        </label>
        <select id={`${id}-mat`} className="control" value={material} onChange={(e) => setMaterial(e.target.value)}>
          {groups.length === 0 && <option value="AL_6082_T6">Aluminium EN AW-6082 T6</option>}
          {groups.map(([cat, items]) => (
            <optgroup key={cat} label={cat}>
              {items.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.name_de} · {m.werkstoff_nr}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>

      <div className="field-row">
        <div className="field">
          <label className="label" htmlFor={`${id}-qty`}>
            Stückzahl <span className="en">· Qty</span>
          </label>
          <input
            id={`${id}-qty`}
            className="control figure"
            type="number"
            inputMode="numeric"
            min={1}
            max={capabilities?.max_quantity ?? 10000}
            value={quantity}
            onChange={(e) => setQuantity(parseInt(e.target.value, 10) || 1)}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor={`${id}-thr`}>
            Gewinde <span className="en">· Threads</span>
          </label>
          <input
            id={`${id}-thr`}
            className="control figure"
            type="number"
            inputMode="numeric"
            min={0}
            placeholder="automatisch"
            value={threads}
            onChange={(e) => setThreads(e.target.value)}
            aria-describedby={`${id}-thr-help`}
          />
        </div>
      </div>
      <p id={`${id}-thr-help`} className="help" style={{ margin: "-10px 0 0" }}>
        Gewinde sind im 3D-Modell oft nicht modelliert. Tragen Sie die Anzahl ein, wenn sie abweicht.
      </p>

      {isStl && (
        <div className="field">
          <label className="label" htmlFor={`${id}-units`}>
            Einheit der STL-Datei <span className="en">· STL units</span>
          </label>
          <select
            id={`${id}-units`}
            className="control"
            value={units}
            onChange={(e) => setUnits(e.target.value as "mm" | "inch")}
          >
            <option value="mm">Millimeter</option>
            <option value="inch">Zoll (inch)</option>
          </select>
        </div>
      )}

      <div className="field">
        <label className="label" htmlFor={`${id}-ref`}>
          Ihr Zeichen <span className="en">· Your reference (optional)</span>
        </label>
        <input
          id={`${id}-ref`}
          className="control"
          maxLength={80}
          placeholder="z. B. Bestellanfrage 4711"
          value={reference}
          onChange={(e) => setReference(e.target.value)}
        />
      </div>

      {localError && (
        <div className="error" role="alert">
          {localError}
        </div>
      )}

      <button className="btn" type="submit" disabled={busy || !file}>
        {busy ? "Wird kalkuliert …" : "Angebot berechnen"}
      </button>

      <div className="field">
        <span className="label">
          Kein Modell zur Hand? <span className="en">· Try a sample part</span>
        </span>
        <div className="samples">
          {SAMPLES.map((s) => (
            <button key={s.file} type="button" disabled={busy} onClick={() => loadSample(s)}>
              {s.de}
            </button>
          ))}
        </div>
      </div>

      <p id={`${id}-privacy`} className="fineprint">
        Ihre CAD-Daten werden vertraulich behandelt und nach {capabilities?.quote_retention_days ?? 90} Tagen gelöscht.
        {capabilities?.ai_enabled && " Zur KI-Prüfung werden nur Kennwerte übermittelt, nie die Datei selbst."}
      </p>
    </form>
  );
}
