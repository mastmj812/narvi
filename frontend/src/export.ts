// Client-side export of the current deal inventory (post-cull, post-filter). The
// scenario FeatureCollection already lives in the browser (curate inventory or an
// override/loaded result), so no backend round-trip is needed. Two formats:
//   * GeoJSON — the FC verbatim (leg LineStrings + parcel/window/turn features)
//   * CSV     — one row per producing leg, geometry flattened to heel/toe lon-lat

function download(filename: string, mime: string, text: string): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function exportGeoJSON(fc: GeoJSON.FeatureCollection, filename: string): void {
  download(filename, "application/geo+json", JSON.stringify(fc));
}

// leg property -> CSV column, in order. heel/toe lon-lat come from the geometry.
const LEG_PROPS = [
  "well_name", "novi_wellname", "formation", "category", "well_type", "leg_index",
  "target_tvd_ft", "length_ft", "completed_lateral_ft", "drilled_lateral_ft",
  "lateral_azimuth_deg", "nearest_neighbor_spacing_ft", "recon_status",
] as const;
const CSV_HEADER = [...LEG_PROPS, "heel_lon", "heel_lat", "toe_lon", "toe_lat"];
// bundle export prepends a `dsu` column (source scenario name) to every row.
const DSU_HEADER = ["dsu", ...CSV_HEADER];

function csvCell(v: unknown): string {
  if (v == null) return "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

// one producing leg -> a CSV row (geometry flattened to heel/toe lon-lat). Returns
// null for non-leg features (parcel/window/turn) so callers just skip them. When
// `dsu` is non-null it is prepended as the leading column (bundle export).
function legRow(f: GeoJSON.Feature, dsu: string | null): string | null {
  const p = f.properties ?? {};
  if (p.kind !== "leg") return null;
  const g = f.geometry;
  let heel: [unknown, unknown] = ["", ""];
  let toe: [unknown, unknown] = ["", ""];
  if (g && g.type === "LineString" && g.coordinates.length > 0) {
    const c = g.coordinates;
    heel = [c[0][0], c[0][1]];
    toe = [c[c.length - 1][0], c[c.length - 1][1]];
  }
  const cells = [
    ...LEG_PROPS.map((k) => p[k]),
    heel[0], heel[1], toe[0], toe[1],
  ];
  if (dsu !== null) cells.unshift(dsu);
  return cells.map(csvCell).join(",");
}

export function fcToWellCSV(fc: GeoJSON.FeatureCollection): string {
  const rows: string[] = [CSV_HEADER.join(",")];
  for (const f of fc.features) {
    const row = legRow(f, null);
    if (row !== null) rows.push(row);
  }
  return rows.join("\n");
}

export function exportWellCSV(fc: GeoJSON.FeatureCollection, filename: string): void {
  download(filename, "text/csv", fcToWellCSV(fc));
}

// ---- deal bundle: several saved scenarios -> one file, each record tagged with
// its source scenario name (`dsu`) so the finance handoff knows the DSU. ----

export interface BundleItem {
  dsu: string;                      // source scenario name (DSU/section label)
  fc: GeoJSON.FeatureCollection;    // that scenario's persisted geojson
}

export function bundleToWellCSV(items: BundleItem[]): string {
  const rows: string[] = [DSU_HEADER.join(",")];
  for (const item of items) {
    for (const f of item.fc.features) {
      const row = legRow(f, item.dsu);
      if (row !== null) rows.push(row);
    }
  }
  return rows.join("\n");
}

// all features across scenarios (legs + parcels + turns), each stamped with `dsu`
// on a fresh properties object (never mutate the loaded FCs).
export function bundleToGeoJSON(items: BundleItem[]): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  for (const item of items) {
    for (const f of item.fc.features) {
      features.push({ ...f, properties: { ...(f.properties ?? {}), dsu: item.dsu } });
    }
  }
  return { type: "FeatureCollection", features };
}

export function exportBundleCSV(items: BundleItem[], filename: string): void {
  download(filename, "text/csv", bundleToWellCSV(items));
}

export function exportBundleGeoJSON(items: BundleItem[], filename: string): void {
  download(filename, "application/geo+json", JSON.stringify(bundleToGeoJSON(items)));
}
