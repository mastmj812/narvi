// Thin fetch client for the narvi backend (same-origin /api via the Vite proxy).

export type WellType = "single" | "uturn";
export type Objective = "max_lateral" | "max_count";
export type DrillFrom = "auto" | "north" | "south";
export type Mode = "single" | "winerack";

export interface Params {
  spacing_ft: number;
  setback_ft: number;
  formation: string;
  target_tvd_ft: number;
  well_type: WellType;
  objective: Objective;
  drill_from: DrillFrom;
  azimuth_deg: number | null;
  min_lateral_ft: number;
}

export interface GenerateRequest {
  parcel: GeoJSON.Geometry;
  params: Params;
  mode: Mode;
  zones?: { formation: string; target_tvd_ft: number }[] | null;
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
    offset_ft: number; tvd_ft: number;
  }[];
  links: {
    well_name: string; formation: string; color: string; tvd_ft: number;
    offset_a_ft: number; offset_b_ft: number;
  }[];
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
}

export interface InventoryResponse {
  well_count: number;
  geojson: GeoJSON.FeatureCollection;
  gunbarrel: GunbarrelData;
  benches: BenchInfo[];        // overlap inventory (curate)
  dev_benches: BenchInfo[];    // area-developable (override)
}

export type Category = "pdp" | "pud" | "res";

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

  inventory: (parcel: GeoJSON.Geometry, buffer_ft = 330, categories: Category[] = ["pdp", "pud", "res"]) =>
    jpost<InventoryResponse>("/api/parcels/inventory", { parcel, buffer_ft, categories }),

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

  saveScenario: (deal_id: string, scenario_id: string, name: string, generate: GenerateRequest) =>
    jpost<{ saved_wells: number }>("/api/scenarios", { deal_id, scenario_id, name, generate }),

  loadScenario: (deal_id: string, scenario_id: string) =>
    jget<{ header: Record<string, unknown>; geojson: GeoJSON.FeatureCollection; gunbarrel: GunbarrelData }>(
      `/api/scenarios/${encodeURIComponent(deal_id)}/${encodeURIComponent(scenario_id)}`),

  deleteScenario: async (deal_id: string, scenario_id: string) => {
    const r = await fetch(`/api/scenarios/${encodeURIComponent(deal_id)}/${encodeURIComponent(scenario_id)}`,
      { method: "DELETE" });
    if (!r.ok) throw new Error(`delete -> ${r.status}`);
    return r.json();
  },
};

export const WAREHOUSE_STACK = ["AVA_0", "BS2_S", "BS3_C", "WCXY", "WCA_1", "WCA_2", "WCB_1", "WCC"];
