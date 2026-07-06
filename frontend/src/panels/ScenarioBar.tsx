import { useEffect, useState } from "react";
import { exportFC, useStore } from "../store";
import { exportGeoJSON, exportWellCSV } from "../export";

export function ScenarioBar() {
  const { scenarios, parcel, result, appMode, inventory, culledWells, loaded,
    refreshScenarios, save, load, remove, restoreAllCulled } = useStore();
  const [name, setName] = useState("");

  useEffect(() => { refreshScenarios(); }, [refreshScenarios]);

  // saving needs a parcel (curate re-derives inventory / override regenerates from it);
  // export only needs the current FC, so it also works on a loaded scenario (no parcel).
  const hasFC = appMode === "override" ? !!result : !!inventory;
  const canSave = !!parcel && hasFC;
  const canExport = hasFC;

  // export the current (post-cull, post-filter, context-stripped) inventory FC as
  // GeoJSON or CSV. filename = the scenario name (typed name > loaded scenario >
  // parcel label), sanitized for the filesystem.
  const doExport = (fmt: "geojson" | "csv") => {
    const fc = exportFC(useStore.getState());
    if (!fc) return;
    const today = new Date().toISOString().slice(0, 10);
    const base = (name.trim() || loaded?.name || parcel?.label || today)
      .replace(/[\\/:*?"<>|]+/g, "_");
    if (fmt === "geojson") exportGeoJSON(fc, `${base}.geojson`);
    else exportWellCSV(fc, `${base}.csv`);
  };

  return (
    <div className="section" style={{ marginTop: 18 }}>
      <h2>Scenarios</h2>
      <div className="row">
        <input
          type="text" placeholder="name…" value={name}
          onChange={(e) => setName(e.target.value)}
          style={{ flex: 2, padding: "4px 6px", border: "1px solid var(--line)", borderRadius: 5 }}
        />
        <button className="ghost" disabled={!canSave} onClick={() => save(name)}>Save</button>
      </div>

      <div className="row" style={{ marginTop: 6, alignItems: "center" }}>
        <button className="ghost" disabled={!canExport} onClick={() => doExport("geojson")}>⬇ GeoJSON</button>
        <button className="ghost" disabled={!canExport} onClick={() => doExport("csv")}>⬇ CSV</button>
        {culledWells.length > 0 && (
          <span className="note" style={{ marginLeft: "auto", marginTop: 0 }}>
            {culledWells.length} culled ·{" "}
            <button
              onClick={restoreAllCulled}
              style={{ background: "none", border: 0, padding: 0, color: "var(--accent, #2563eb)",
                cursor: "pointer", textDecoration: "underline", font: "inherit" }}
            >
              restore all
            </button>
          </span>
        )}
      </div>

      <div style={{ marginTop: 8 }}>
        {scenarios.length === 0 && <div className="note">no saved scenarios</div>}
        {scenarios.map((s) => (
          <div className="scenario-row" key={`${s.deal_id}/${s.scenario_id}`}>
            <div>
              <div>{s.name ?? s.deal_id}</div>
              <div className="meta">
                {s.scenario_id} · {s.total_wells ?? 0}w
                {s.total_completed_ft != null && <> · {(s.total_completed_ft / 1000).toFixed(0)}k ft</>}
              </div>
            </div>
            <div className="row" style={{ flex: "0 0 auto" }}>
              <button className="ghost" onClick={() => load(s.deal_id, s.scenario_id)}>Load</button>
              <button className="ghost" onClick={() => remove(s.deal_id, s.scenario_id)}>✕</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
