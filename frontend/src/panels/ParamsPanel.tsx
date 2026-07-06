import { useRef } from "react";
import { type Params } from "../api/client";
import { useStore } from "../store";

function NumberField<K extends keyof Params>(
  { label, k, step, title }: { label: string; k: K; step?: number; title?: string },
) {
  const value = useStore((s) => s.params[k]) as number;
  const setParam = useStore((s) => s.setParam);
  return (
    <div className="field">
      <label title={title}>{label}</label>
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
    parcel, parcels, mode, params, sourceAzimuth, winerackFormations, benchSpacing, benchTvd,
    devBenches, result, loading, error,
    selectParcel, setMode, setParam, setSourceAzimuth, toggleWinerackFormation, setBenchSpacing,
    setBenchTvd, loadSynthetic, uploadParcels, generate,
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
        <NumberField
          label="setback N/S (ft)" k="setback_ns_ft" step={10}
          title="setback on the N/S boundaries (the toe/heel ends for ~N-S development)"
        />
        <NumberField
          label="setback E/W (ft)" k="setback_ew_ft" step={10}
          title="setback on the E/W boundaries (the lateral-side section lines); 330 ft is the legal default"
        />
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
        <div className="field">
          <label title="where the row pattern hangs across the unit">anchor</label>
          <select value={params.anchor} onChange={(e) => setParam("anchor", e.target.value as Params["anchor"])}>
            <option value="auto">auto (max footage)</option>
            <option value="west">west line</option>
            <option value="east">east line</option>
            <option value="center">center</option>
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
        {(params.anchor === "west" || params.anchor === "east") ? (
          <div className="field">
            <label title={`azimuth comes from the ${params.anchor} lease line — laterals run parallel to the setback`}
              style={{ color: "var(--muted)" }}>
              grid azimuth (from {params.anchor} line)
            </label>
            <input type="checkbox" checked disabled />
          </div>
        ) : (
          <div className="field">
            <label title="adopt the offset-well grid azimuth sourced from the warehouse">grid azimuth (auto)</label>
            <input type="checkbox" checked={sourceAzimuth} onChange={(e) => setSourceAzimuth(e.target.checked)} />
          </div>
        )}
        {mode === "single" && (
          <>
            <div className="field">
              <label>formation</label>
              <input
                type="text" value={params.formation} style={{ width: 150 }}
                onChange={(e) => setParam("formation", e.target.value)}
              />
            </div>
            <NumberField label="target TVD (ft)" k="target_tvd_ft" step={50} />
          </>
        )}
      </div>

      {mode === "winerack" && (
        <div className="section">
          <h2>Benches (developable in area)</h2>
          {devBenches.length === 0 && <div className="note">select a parcel to discover its benches</div>}
          {devBenches.map((b) => {
            const checked = winerackFormations.includes(b.formation);
            const sp = benchSpacing[b.formation] ?? b.suggested_spacing_ft ?? params.spacing_ft;
            const ctrl = [b.n_pdp ? `${b.n_pdp} PDP` : null, b.n_pud ? `${b.n_pud} PUD` : null]
              .filter(Boolean).join(" · ") || "no control";
            return (
              <div key={b.formation} style={{ marginBottom: 4 }}>
                <div className="field">
                  <label title={`${ctrl}${b.median_tvd_ft != null ? ` @ ${b.median_tvd_ft.toLocaleString()}' TVD` : ""}`}>
                    {b.formation}
                    {b.median_tvd_ft != null && (
                      <span style={{ color: "var(--muted)" }}> {b.median_tvd_ft.toLocaleString()}' · {ctrl}</span>
                    )}
                  </label>
                  <input type="checkbox" checked={checked}
                    onChange={() => toggleWinerackFormation(b.formation)} />
                </div>
                {checked && (
                  <>
                    <div className="field" style={{ paddingLeft: 12 }}>
                      <label style={{ color: "var(--muted)", fontSize: 11 }}
                        title="leg-to-leg for this bench; Novi develops Bone Spring wider than Wolfcamp">
                        spacing (ft){b.n_pud ? ` · ${b.n_pud} PUD` : ""}
                      </label>
                      <input type="number" step={10} style={{ width: 80 }}
                        value={Number.isFinite(sp) ? sp : 0}
                        onChange={(e) => setBenchSpacing(b.formation, Number(e.target.value))} />
                    </div>
                    <div className="field" style={{ paddingLeft: 12 }}>
                      <label
                        style={{ color: benchTvd[b.formation] != null ? "var(--accent)" : "var(--muted)", fontSize: 11 }}
                        title="hard TVD for generated locations in this bench (e.g. your geologist's pick) — empty uses the warehouse median; resets on parcel change"
                      >
                        TVD (ft){benchTvd[b.formation] != null ? " · override" : " · warehouse"}
                        {benchTvd[b.formation] != null && (
                          <>
                            {" "}
                            <span
                              onClick={() => setBenchTvd(b.formation, null)}
                              style={{ cursor: "pointer", textDecoration: "underline" }}
                              title="clear the override (back to warehouse median)"
                            >
                              reset
                            </span>
                          </>
                        )}
                      </label>
                      <input type="number" step={50} style={{ width: 80 }}
                        value={benchTvd[b.formation] ?? ""}
                        placeholder={b.median_tvd_ft != null ? String(Math.round(b.median_tvd_ft)) : "—"}
                        onChange={(e) => setBenchTvd(b.formation,
                          e.target.value === "" ? null : Number(e.target.value))} />
                    </div>
                  </>
                )}
              </div>
            );
          })}
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
