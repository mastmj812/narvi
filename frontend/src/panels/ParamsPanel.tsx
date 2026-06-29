import { useRef } from "react";
import { type Params } from "../api/client";
import { useStore } from "../store";

function NumberField<K extends keyof Params>({ label, k, step }: { label: string; k: K; step?: number }) {
  const value = useStore((s) => s.params[k]) as number;
  const setParam = useStore((s) => s.setParam);
  return (
    <div className="field">
      <label>{label}</label>
      <input
        type="number"
        step={step ?? 1}
        value={Number.isFinite(value) ? value : 0}
        onChange={(e) => setParam(k, Number(e.target.value) as Params[K])}
      />
    </div>
  );
}

export function ParamsPanel() {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const {
    parcel, parcels, mode, params, sourceAzimuth, winerackFormations, benches,
    result, loading, error,
    selectParcel, setMode, setParam, setSourceAzimuth, toggleWinerackFormation,
    loadSynthetic, uploadParcels, generate,
  } = useStore();

  return (
    <>
      <div className="section">
        <h2>Parcel</h2>
        <div className="row">
          <button className="ghost" onClick={() => loadSynthetic()}>Synthetic</button>
          <button className="ghost" onClick={() => fileRef.current?.click()}>Upload .zip</button>
        </div>
        <input
          ref={fileRef} type="file" accept=".zip" style={{ display: "none" }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadParcels(f); }}
        />
        {parcels.length > 0 && (
          <div className="field" style={{ marginTop: 8 }}>
            <label>deal</label>
            <select
              value={parcel?.label ?? ""}
              onChange={(e) => selectParcel(parcels.find((p) => p.label === e.target.value) ?? null)}
            >
              {parcels.map((p) => (
                <option key={p.label} value={p.label}>{p.label} ({p.area_ac} ac)</option>
              ))}
            </select>
          </div>
        )}
      </div>

      <div className="section">
        <h2>Mode</h2>
        <div className="segmented">
          <button className={mode === "single" ? "active" : ""} onClick={() => setMode("single")}>Single bench</button>
          <button className={mode === "winerack" ? "active" : ""} onClick={() => setMode("winerack")}>Wine-rack</button>
        </div>
      </div>

      <div className="section">
        <h2>Parameters</h2>
        <NumberField label="spacing (ft)" k="spacing_ft" step={10} />
        <NumberField label="setback (ft)" k="setback_ft" step={10} />
        <NumberField label="min lateral (ft)" k="min_lateral_ft" step={100} />
        <div className="field">
          <label>well type</label>
          <select value={params.well_type} onChange={(e) => setParam("well_type", e.target.value as Params["well_type"])}>
            <option value="single">single</option>
            <option value="uturn">U-turn</option>
          </select>
        </div>
        <div className="field">
          <label>objective</label>
          <select value={params.objective} onChange={(e) => setParam("objective", e.target.value as Params["objective"])}>
            <option value="max_lateral">max lateral</option>
            <option value="max_count">max count</option>
          </select>
        </div>
        {params.well_type === "uturn" && (
          <div className="field">
            <label title="which side the pads/heels go; the U-turn sits at the opposite end">drill from</label>
            <select value={params.drill_from} onChange={(e) => setParam("drill_from", e.target.value as Params["drill_from"])}>
              <option value="auto">auto (max footage)</option>
              <option value="north">north</option>
              <option value="south">south</option>
            </select>
          </div>
        )}
        <div className="field">
          <label>grid azimuth (auto)</label>
          <input type="checkbox" checked={sourceAzimuth} onChange={(e) => setSourceAzimuth(e.target.checked)} />
        </div>
        {mode === "single" && (
          <>
            <div className="field">
              <label>formation</label>
              <input
                type="text" value={params.formation} style={{ width: 120 }}
                onChange={(e) => setParam("formation", e.target.value)}
              />
            </div>
            <NumberField label="target TVD (ft)" k="target_tvd_ft" step={50} />
          </>
        )}
      </div>

      {mode === "winerack" && (
        <div className="section">
          <h2>Benches (warehouse TVD)</h2>
          {benches.length === 0 && <div className="note">select a parcel to discover its benches</div>}
          {benches.map((b) => (
            <div className="field" key={b.formation}>
              <label>{b.formation}
                {b.median_tvd_ft != null && (
                  <span style={{ color: "var(--muted)" }}> {b.median_tvd_ft.toLocaleString()}'</span>
                )}
              </label>
              <input
                type="checkbox" checked={winerackFormations.includes(b.formation)}
                onChange={() => toggleWinerackFormation(b.formation)}
              />
            </div>
          ))}
        </div>
      )}

      <button className="primary" disabled={loading || !parcel} onClick={() => generate()}>
        {loading ? "generating…" : "Generate"}
      </button>
      {error && <div className="error">{error}</div>}
      {result && (
        <div className="summary">
          <div><b>{result.placed_wells}</b> wells / {result.placed_legs} legs
            {result.azimuth_deg != null && <> · az {result.azimuth_deg.toFixed(1)}°</>}</div>
          <div className="note">{result.summary}</div>
          {result.warehouse_notes.length > 0 && (
            <div className="note">{result.warehouse_notes.join("\n")}</div>
          )}
        </div>
      )}
    </>
  );
}
