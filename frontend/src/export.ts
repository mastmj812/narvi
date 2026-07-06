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

function csvCell(v: unknown): string {
  if (v == null) return "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function fcToWellCSV(fc: GeoJSON.FeatureCollection): string {
  const rows: string[] = [CSV_HEADER.join(",")];
  for (const f of fc.features) {
    const p = f.properties ?? {};
    if (p.kind !== "leg") continue;
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
    rows.push(cells.map(csvCell).join(","));
  }
  return rows.join("\n");
}

export function exportWellCSV(fc: GeoJSON.FeatureCollection, filename: string): void {
  download(filename, "text/csv", fcToWellCSV(fc));
}
