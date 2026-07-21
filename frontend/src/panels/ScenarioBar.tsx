import { useEffect, useState } from "react";
import { exportFC, useStore } from "../store";
import {
  exportGeoJSON, exportWellCSV, exportShapefile,
  exportBundleCSV, exportBundleGeoJSON, exportBundleShapefile, type BundleItem,
} from "../export";
import { api, type ScenarioSummary } from "../api/client";

export function ScenarioBar() {
  const { scenarios, parcel, result, inventory, culledWells, loaded,
    refreshScenarios, save, load, remove, toggleCull, restoreAllCulled } = useStore();
  const [name, setName] = useState("");
  // deal bundle: ad-hoc multi-select of saved scenarios -> one CSV + one GeoJSON,
  // each record tagged with its source scenario name (the DSU/section label).
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bundleName, setBundleName] = useState("");
  const [busy, setBusy] = useState(false);
  const scenKey = (s: ScenarioSummary) => `${s.deal_id}/${s.scenario_id}`;
  const dsuLabel = (s: ScenarioSummary) => s.name?.trim() || s.deal_id;

  const toggleSelect = (key: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });

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
  const doExport = async (fmt: "geojson" | "csv" | "shp") => {
    const fc = exportFC(useStore.getState());
    if (!fc) return;
    const today = new Date().toISOString().slice(0, 10);
    const base = (name.trim() || loaded?.name || parcel?.label || today)
      .replace(/[\\/:*?"<>|]+/g, "_");
    if (fmt === "geojson") exportGeoJSON(fc, `${base}.geojson`);
    else if (fmt === "csv") exportWellCSV(fc, `${base}.csv`);
    else {
      // shapefile = backend round-trip; inventory sticks only (no PDP), so a
      // PDP-only curate view legitimately 400s — surface that, don't swallow it
      try {
        await exportShapefile(fc, base);
      } catch (e) {
        alert(`Shapefile export failed: ${e instanceof Error ? e.message : e}`);
      }
    }
  };

  // load each ticked scenario's persisted FC, tag records with its DSU (scenario
  // name), and download one combined CSV + one combined GeoJSON for the deal.
  const doBundleExport = async () => {
    const sel = scenarios.filter((s) => selected.has(scenKey(s)));
    if (sel.length === 0) return;
    setBusy(true);
    try {
      const items: BundleItem[] = [];
      let failed = 0;
      for (const s of sel) {
        try {
          const { geojson } = await api.loadScenario(s.deal_id, s.scenario_id);
          items.push({ dsu: dsuLabel(s), fc: geojson });
        } catch {
          failed += 1;
        }
      }
      if (items.length === 0) { alert("Bundle export failed: no scenarios could be loaded."); return; }
      const today = new Date().toISOString().slice(0, 10);
      const base = (bundleName.trim() || "deal_bundle").replace(/[\\/:*?"<>|]+/g, "_");
      exportBundleCSV(items, `${base}_${today}.csv`);
      exportBundleGeoJSON(items, `${base}_${today}.geojson`);
      // shapefile rides along for the GGX handoff; a bundle with zero inventory
      // sticks (all-PDP curates) 400s — report it but keep the CSV/GeoJSON
      try {
        await exportBundleShapefile(items, `${base}_${today}`);
      } catch (e) {
        alert(`Bundle shapefile skipped: ${e instanceof Error ? e.message : e}`);
      }
      if (failed > 0) alert(`Exported ${items.length} of ${sel.length} scenarios (${failed} failed to load).`);
    } finally {
      setBusy(false);
    }
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
        <button
          className="ghost" disabled={!canExport} onClick={() => doExport("shp")}
          title="zipped shapefile for GGX — created/generated inventory sticks only, no PDP"
        >
          ⬇ SHP
        </button>
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

      {scenarios.length > 0 && (
        <div className="row" style={{ marginTop: 10, alignItems: "center" }}>
          <input
            type="text" placeholder="deal name…" value={bundleName}
            onChange={(e) => setBundleName(e.target.value)}
            style={{ flex: 2, padding: "4px 6px", border: "1px solid var(--line)", borderRadius: 5 }}
          />
          <button className="ghost" disabled={selected.size === 0 || busy} onClick={doBundleExport}>
            {busy ? "…" : `⬇ Bundle (${selected.size})`}
          </button>
          {selected.size > 0 && (
            <button
              onClick={() => setSelected(new Set())}
              style={{ background: "none", border: 0, padding: 0, color: "var(--accent, #2563eb)",
                cursor: "pointer", textDecoration: "underline", font: "inherit" }}
            >
              clear
            </button>
          )}
        </div>
      )}

      <div style={{ marginTop: 8 }}>
        {scenarios.length === 0 && <div className="note">no saved scenarios</div>}
        {scenarios.map((s) => {
          const key = `${s.deal_id}/${s.scenario_id}`;
          const isLoaded = loaded?.deal_id === s.deal_id && loaded?.scenario_id === s.scenario_id;
          return (
            <div
              className="scenario-row" key={key}
              style={isLoaded
                ? { background: "var(--accent-soft, #eef2ff)", borderRadius: 5, padding: "2px 4px" }
                : undefined}
            >
              <input
                type="checkbox" title="add to deal bundle"
                checked={selected.has(key)} onChange={() => toggleSelect(key)}
                style={{ marginRight: 6, flex: "0 0 auto" }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
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
