// Thin fetch client for the narvi backend (same-origin /api via the Vite proxy).

export type WellType = "single" | "uturn";
export type Objective = "max_lateral" | "max_count";
export type DrillFrom = "auto" | "north" | "south";
export type Anchor = "auto" | "west" | "east" | "center";
export type Mode = "single" | "winerack";

export interface Params {
  spacing_ft: number;
  setback_ft: number;
  setback_ns_ft: number;   // along-leg (toe/heel ends)
  setback_ew_ft: number;   // across-leg (lateral-side section lines)
  formation: string;
  target_tvd_ft: number;
  well_type: WellType;
  objective: Objective;
  drill_from: DrillFrom;
  anchor: Anchor;
  azimuth_deg: number | null;
  min_lateral_ft: number;
}

export interface GenerateRequest {
  parcel: GeoJSON.Geometry;
  params: Params;
  mode: Mode;
  zones?: { formation: string; target_tvd_ft: number; spacing_ft?: number | null }[] | null;
  formations?: string[] | null;
  source_tvd?: boolean;
  source_azimuth?: boolean;
  buffer_ft?: number;
}

export interface GunbarrelData {
  formations: { formation: string; color: string }[];
  points: {
    well_name: string; formation: string; color: string; well_type: string;
    category: string; novi_wellname: string | null; recon_status: string | null;
    pdp_count_3mi: number | null;    // offset-PDP support (sql/30); null for pdp/generated
    inflation_ratio: number | null;
    context?: boolean;               // near-parcel PDP background (not unit inventory)
    offset_ft: number; tvd_ft: number;
  }[];
  links: {
    well_name: string; formation: string; color: string; tvd_ft: number;
    offset_a_ft: number; offset_b_ft: number;
  }[];
  azimuth_deg?: number | null;       // lateral azimuth -> compass axis end-labels
}

export interface GenerateResponse {
  mode: string;
  placed_wells: number;
  placed_legs: number;
  azimuth_deg: number | null;
  summary: string;
  warehouse_notes: string[];
  geojson: GeoJSON.FeatureCollection;
  gunbarrel: GunbarrelData;
}

export interface ParcelInfo {
  label: string;
  area_ac: number;
  geojson: GeoJSON.Geometry;
}

export interface BenchInfo {
  formation: string;
  median_tvd_ft: number | null;
  n_pdp: number;
  n_pud: number;
  n_res: number;
  suggested_spacing_ft: number | null;
  note: string;
  n_supported?: number | null;     // pud/res sticks with offset support (sql/30)
}

export interface InventoryResponse {
  well_count: number;
  geojson: GeoJSON.FeatureCollection;
  gunbarrel: GunbarrelData;
  benches: BenchInfo[];        // overlap inventory (curate)
  dev_benches: BenchInfo[];    // area-developable (override)
}

export type Category = "pdp" | "pud" | "res";

// summary stamped on a curate save (backend /scenarios/curate) — the filter
// recipe needed to restore the editable curate state on load
export interface CurateSummary {
  mode: "curate";
  kept_benches: string[];
  categories: Category[];
  culled_wells: string[];
}

// summary stamped on an override save — the note plus the exact GenerateRequest
// (minus parcel, which reloads from the stored AOI) so a loaded scenario
// restores as an editable recipe, not a frozen snapshot
export interface OverrideSummary {
  note?: string;
  warehouse_notes?: string[];
  generate?: Omit<GenerateRequest, "parcel">;
}

// summary stamped on a composed save (backend /scenarios/composed) — the full
// plan recipe (per-bench sources + generator inputs) so loads restore the
// editable working set
export interface ComposedSummary {
  mode: "composed";
  bench_sources: Record<string, string>;
  categories: Category[];
  culled_wells: string[];
  generate?: {
    params?: Record<string, unknown>;
    zones?: { formation: string; target_tvd_ft: number; spacing_ft?: number | null }[];
    source_azimuth?: boolean;
    buffer_ft?: number;
  };
  note?: string;
  warehouse_notes?: string[];
}

export interface SaveComposedBody {
  deal_id: string;
  scenario_id: string;
  name: string;
  parcel: GeoJSON.Geometry;
  bench_sources: Record<string, string>;
  categories: Category[];
  culled_wells: string[];
  params: Params;
  zones: { formation: string; target_tvd_ft: number; spacing_ft?: number | null }[];
  source_azimuth: boolean;
}

// what one lateral bearing can hold in the parcel (feasibility card + scan input)
export interface DirectionFeasibility {
  label: string;               // 'grid' | 'long-axis'
  azimuth_deg: number;
  max_lateral_ft: number;
  cross_extent_ft: number;
  note: string;
}

// one swept configuration from /generate/scan, ranked by completed footage
export interface ScanConfig {
  azimuth_label: string;
  azimuth_deg: number;
  well_type: string;           // 'single' | 'uturn'
  spacing_ft: number;
  wells: number;
  legs: number;
  completed_ft: number;
  ft_per_well: number;
  note: string;
}

export interface ScenarioSummary {
  deal_id: string;
  scenario_id: string;
  name: string | null;
  well_type: string;
  objective: string;
  total_wells: number | null;
  total_legs: number | null;
  total_completed_ft: number | null;
  azimuth_deg: number | null;
}

async function jpost<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `${url} -> ${r.status}`);
  return r.json();
}

async function jget<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

export const api = {
  generate: (req: GenerateRequest) => jpost<GenerateResponse>("/api/generate", req),

  syntheticParcel: () => jget<ParcelInfo>("/api/parcels/synthetic"),

  // context_radius_ft null = unit wells only (the PDP tile layer provides map
  // context; the gun-barrel is a unit cross-section, not a neighborhood one)
  inventory: (parcel: GeoJSON.Geometry, buffer_ft = 5280, categories: Category[] = ["pdp", "pud", "res"],
    context_radius_ft: number | null = null) =>
    jpost<InventoryResponse>("/api/parcels/inventory", { parcel, buffer_ft, categories, context_radius_ft }),

  // what each realistic bearing can hold (grid azimuth sourced server-side)
  feasibility: (parcel: GeoJSON.Geometry, p: Params) =>
    jpost<{ directions: DirectionFeasibility[] }>("/api/parcels/feasibility", {
      parcel, setback_ft: p.setback_ft, setback_ns_ft: p.setback_ns_ft,
      setback_ew_ft: p.setback_ew_ft, min_lateral_ft: p.min_lateral_ft,
    }),

  // azimuth x well-type x spacing sweep through the placement engine (pure geometry)
  scan: (parcel: GeoJSON.Geometry, params: Params, azimuths: DirectionFeasibility[]) =>
    jpost<{ configs: ScanConfig[] }>("/api/generate/scan", { parcel, params, azimuths }),

  uploadParcels: async (file: File): Promise<{ parcels: ParcelInfo[] }> => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/parcels/upload", { method: "POST", body: fd });
    if (!r.ok) throw new Error(`upload -> ${r.status}`);
    return r.json();
  },

  azimuth: (parcel: GeoJSON.Geometry, buffer_ft = 5280) =>
    jpost<{ azimuth_deg: number | null; confident: boolean; note: string }>(
      "/api/warehouse/azimuth", { parcel, buffer_ft }),

  listScenarios: (deal_id?: string) =>
    jget<ScenarioSummary[]>(`/api/scenarios${deal_id ? `?deal_id=${encodeURIComponent(deal_id)}` : ""}`),

  // culled_wells are baked out of the persisted plan server-side (not just hidden)
  saveScenario: (deal_id: string, scenario_id: string, name: string,
    generate: GenerateRequest, culled_wells: string[] = []) =>
    jpost<{ saved_wells: number }>("/api/scenarios",
      { deal_id, scenario_id, name, generate, culled_wells }),

  saveCurateScenario: (
    deal_id: string, scenario_id: string, name: string, parcel: GeoJSON.Geometry,
    // buffer matches api.inventory's fetch so the saved set is exactly the
    // curated view (membership is decided by co-extent overlap, not the buffer)
    kept_benches: string[], categories: Category[], culled_wells: string[] = [], buffer_ft = 5280,
  ) =>
    jpost<{ saved_wells: number }>("/api/scenarios/curate", {
      deal_id, scenario_id, name, parcel, kept_benches, categories, culled_wells, buffer_ft,
    }),

  // culled_wells bake out server-side; the kept Novi baseline + generated wells
  // persist together as one scenario
  saveComposedScenario: (body: SaveComposedBody) =>
    jpost<{ saved_wells: number }>("/api/scenarios/composed", body),

  loadScenario: (deal_id: string, scenario_id: string) =>
    jget<{
      header: Record<string, unknown> & {
        summary?: CurateSummary | OverrideSummary | Record<string, unknown> | null;
        params?: Record<string, unknown> | null;  // persisted ScenarioParams — the
                                                  // restore fallback for saves that
                                                  // predate summary.generate
      };
      geojson: GeoJSON.FeatureCollection; gunbarrel: GunbarrelData;
      parcel: ParcelInfo | null;          // rebuilt from the stored AOI (curate restore)
    }>(
      `/api/scenarios/${encodeURIComponent(deal_id)}/${encodeURIComponent(scenario_id)}`),

  // zipped shapefile of the FC's inventory legs (pud/res/generated — PDP is
  // filtered server-side). layer_name names the .shp/.dbf files inside the zip.
  exportShapefile: async (geojson: GeoJSON.FeatureCollection, layer_name: string): Promise<Blob> => {
    const r = await fetch("/api/export/shapefile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ geojson, layer_name }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `shapefile export -> ${r.status}`);
    return r.blob();
  },

  deleteScenario: async (deal_id: string, scenario_id: string) => {
    const r = await fetch(`/api/scenarios/${encodeURIComponent(deal_id)}/${encodeURIComponent(scenario_id)}`,
      { method: "DELETE" });
    if (!r.ok) throw new Error(`delete -> ${r.status}`);
    return r.json();
  },
};

export const WAREHOUSE_STACK = ["AVA_0", "BS2_S", "BS3_C", "WCXY", "WCA_1", "WCA_2", "WCB_1", "WCC"];
