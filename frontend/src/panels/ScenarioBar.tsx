import { useEffect, useState } from "react";
import { exportFC, useStore } from "../store";
import { exportGeoJSON, exportWellCSV } from "../export";

export function ScenarioBar() {
  const { scenarios, parcel, result, inventory, culledWells, loaded,
    refreshScenarios, save, load, remove, toggleCull, restoreAllCulled } = useStore();
  const [name, setName] = useState("");

  // friendlier display name for a culled well (Novi wellname when we have it);
  // the cull itself keys on well_name
  const displayName = (wellName: string) => {
    const pts = [...(inventory?.gunbarrel?.points ?? []), ...(result?.gunbarrel?.points ?? [])];
    return pts.find((p) => p.well_name === wellName)?.novi_wellname ?? wellName;
  };

  useEffect(() => { refreshScenarios(); }, [refreshScenarios]);

  // the name box tracks the loaded/last-saved scenario, so "Save" overwrites it
  // by default; a new deal (loaded -> null) clears the box
  useEffect(() => { setName(loaded?.name ?? ""); }, [loaded]);

  // saving needs a parcel + inventory (the composed save re-derives the kept
  // Novi baseline and regenerates server-side); export only needs the current
  // FC, so it also works on a loaded scenario.
  const canSave = !!parcel && !!inventory;
  const canExport = !!inventory || !!result;

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

      {culledWells.length > 0 && (
        <div className="note" style={{ marginTop: 4, maxHeight: 110, overflowY: "auto" }}>
          {culledWells.map((w) => (
            <div key={w} style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ textDecoration: "line-through", opacity: 0.7 }}>{displayName(w)}</span>
              <button
                title="restore this well"
                onClick={() => toggleCull(w)}
                style={{ background: "none", border: 0, padding: "0 2px", color: "var(--accent, #2563eb)",
                  cursor: "pointer", font: "inherit" }}
              >
                ↩
              </button>
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 8 }}>
        {scenarios.length === 0 && <div className="note">no saved scenarios</div>}
        {scenarios.map((s) => {
          const isLoaded = loaded?.deal_id === s.deal_id && loaded?.scenario_id === s.scenario_id;
          return (
            <div
              className="scenario-row" key={`${s.deal_id}/${s.scenario_id}`}
              style={isLoaded
                ? { background: "var(--accent-soft, #eef2ff)", borderRadius: 5, padding: "2px 4px" }
                : undefined}
            >
              <div>
                <div style={{ fontWeight: isLoaded ? 600 : 400 }}>
                  {s.name ?? s.deal_id}
                  {isLoaded && <span style={{ color: "var(--accent, #2563eb)", fontSize: 10 }}> · loaded</span>}
                </div>
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
          );
        })}
      </div>
    </div>
  );
}
