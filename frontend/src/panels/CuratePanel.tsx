import { useRef } from "react";
import type { Category } from "../api/client";
import { colorForBlueox } from "../map/formations";
import { useStore } from "../store";

const CATS: { key: Category; label: string }[] = [
  { key: "pdp", label: "PDP (existing)" },
  { key: "pud", label: "PUD (plan)" },
  { key: "res", label: "RES (resource)" },
];

export function CuratePanel() {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const {
    parcel, parcels, benches, keptBenches, cats, inventory, culledWells, loading, error,
    selectParcel, loadSynthetic, uploadParcels, toggleBench, toggleCat,
  } = useStore();

  // culled wells are out of the deal, so every count excludes them; distinct
  // well_names (a U-turn contributes two gunbarrel points but is one well)
  const culledSet = new Set(culledWells);
  const culledPts = (inventory?.gunbarrel?.points ?? [])
    .filter((p) => culledSet.has(p.well_name));
  const nCulled = (category: string, formation?: string) => new Set(
    culledPts
      .filter((p) => p.category === category
        && (formation ? p.formation === formation : keptBenches.includes(p.formation)))
      .map((p) => p.well_name)).size;

  const keptPud = Math.max(0, benches
    .filter((b) => keptBenches.includes(b.formation))
    .reduce((n, b) => n + b.n_pud, 0) - nCulled("pud"));

  return (
    <>
      <div className="section">
        <h2>Parcel</h2>
        <div className="row">
          <button className="ghost" onClick={() => loadSynthetic()}>Synthetic</button>
          <button className="ghost" onClick={() => fileRef.current?.click()}>Upload .zip</button>
        </div>
        <input ref={fileRef} type="file" accept=".zip" style={{ display: "none" }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadParcels(f); }} />
        {parcels.length > 0 && (
          <div className="field" style={{ marginTop: 8 }}>
            <label>deal</label>
            <select value={parcel?.label ?? ""}
              onChange={(e) => selectParcel(parcels.find((p) => p.label === e.target.value) ?? null)}>
              {parcels.map((p) => <option key={p.label} value={p.label}>{p.label} ({p.area_ac} ac)</option>)}
            </select>
          </div>
        )}
        {loading && <div className="note">loading inventory…</div>}
        {error && <div className="error">{error}</div>}
      </div>

      <div className="section">
        <h2>Show</h2>
        {CATS.map((c) => (
          <div className="field" key={c.key}>
            <label>{c.label}</label>
            <input type="checkbox" checked={cats[c.key]} onChange={() => toggleCat(c.key)} />
          </div>
        ))}
      </div>

      <div className="section">
        <h2>Benches {benches.length > 0 && <span style={{ color: "var(--muted)" }}>({keptBenches.length}/{benches.length})</span>}</h2>
        {benches.length === 0 && <div className="note">select a parcel to load its inventory</div>}
        {benches.map((b) => {
          const kept = keptBenches.includes(b.formation);
          const suspectTvd = b.median_tvd_ft != null && b.median_tvd_ft > 15000;
          const nPdp = Math.max(0, b.n_pdp - nCulled("pdp", b.formation));
          const nPud = Math.max(0, b.n_pud - nCulled("pud", b.formation));
          const nRes = Math.max(0, b.n_res - nCulled("res", b.formation));
          const counts = [nPdp && `${nPdp} PDP`, nPud && `${nPud} PUD`, nRes && `${nRes} RES`]
            .filter(Boolean).join(" · ");
          return (
            <div className="scenario-row" key={b.formation} style={{ opacity: kept ? 1 : 0.5 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", flex: 1 }}>
                <input type="checkbox" checked={kept} onChange={() => toggleBench(b.formation)} />
                <i className="swatch" style={{ background: colorForBlueox(b.formation) }} />
                <span>{b.formation}</span>
              </label>
              <div className="meta" style={{ textAlign: "right" }}>
                <div>{b.median_tvd_ft != null ? `${b.median_tvd_ft.toLocaleString()} ft` : "—"}
                  {suspectTvd && <span title="placeholder depth?" style={{ color: "#f59e0b" }}> ⚠</span>}</div>
                <div>{counts}{b.suggested_spacing_ft ? ` · ~${b.suggested_spacing_ft.toFixed(0)}'` : ""}</div>
              </div>
            </div>
          );
        })}
      </div>

      {inventory && (
        <div className="summary">
          <div><b>{keptPud}</b> PUD locations in {keptBenches.length} kept benches</div>
          <div className="note">
            {Math.max(0, inventory.well_count
              - new Set(culledPts.filter((p) => !p.context).map((p) => p.well_name)).size)}
            {" "}existing (PDP+PUD+RES) in/around the unit
            {culledWells.length > 0 && ` · ${culledWells.length} culled`}
          </div>
        </div>
      )}
    </>
  );
}
