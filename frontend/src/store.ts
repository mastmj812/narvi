import { create } from "zustand";
import {
  api,
  WAREHOUSE_STACK,
  type Category,
  type GenerateRequest,
  type GenerateResponse,
  type BenchInfo,
  type InventoryResponse,
  type Mode,
  type Params,
  type ParcelInfo,
  type ScenarioSummary,
} from "./api/client";

export type AppMode = "curate" | "override";

const DEFAULT_PARAMS: Params = {
  spacing_ft: 880, setback_ft: 200, formation: "WCA_1", target_tvd_ft: 11000,
  well_type: "single", objective: "max_lateral", azimuth_deg: null, min_lateral_ft: 4000,
};

function dealIdFor(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "deal";
}

// A leg is shown if its bench is kept AND its category is active. Non-leg
// features (parcel/window/turn) and `generated` legs always pass.
export function catActive(cats: Record<Category, boolean>, category: string): boolean {
  if (category === "pdp" || category === "pud" || category === "res") return cats[category];
  return true;
}

export function filterFC(
  fc: GeoJSON.FeatureCollection, kept: string[], cats: Record<Category, boolean>,
): GeoJSON.FeatureCollection {
  const keptSet = new Set(kept);
  return {
    type: "FeatureCollection",
    features: fc.features.filter((f) => {
      const p = f.properties ?? {};
      if (p.kind !== "leg") return true;
      return keptSet.has(p.formation) && catActive(cats, p.category);
    }),
  };
}

interface State {
  appMode: AppMode;
  parcels: ParcelInfo[];
  parcel: ParcelInfo | null;

  // curate
  inventory: InventoryResponse | null;
  benches: BenchInfo[];
  keptBenches: string[];
  cats: Record<Category, boolean>;

  // override (generator)
  mode: Mode;
  params: Params;
  sourceAzimuth: boolean;
  winerackFormations: string[];
  result: GenerateResponse | null;

  loading: boolean;
  error: string | null;
  scenarios: ScenarioSummary[];

  setAppMode: (m: AppMode) => void;
  setParcels: (p: ParcelInfo[]) => void;
  selectParcel: (p: ParcelInfo | null) => void;
  loadSynthetic: () => Promise<void>;
  uploadParcels: (file: File) => Promise<void>;
  fetchInventory: () => Promise<void>;
  toggleBench: (code: string) => void;
  toggleCat: (c: Category) => void;

  setMode: (m: Mode) => void;
  setParam: <K extends keyof Params>(k: K, v: Params[K]) => void;
  setSourceAzimuth: (v: boolean) => void;
  toggleWinerackFormation: (f: string) => void;
  buildRequest: () => GenerateRequest | null;
  generate: () => Promise<void>;

  refreshScenarios: () => Promise<void>;
  save: (name: string) => Promise<void>;
  load: (deal_id: string, scenario_id: string) => Promise<void>;
  remove: (deal_id: string, scenario_id: string) => Promise<void>;
}

export const useStore = create<State>((set, get) => ({
  appMode: "curate",
  parcels: [],
  parcel: null,

  inventory: null,
  benches: [],
  keptBenches: [],
  cats: { pdp: true, pud: true, res: false },

  mode: "single",
  params: { ...DEFAULT_PARAMS },
  sourceAzimuth: true,
  winerackFormations: [...WAREHOUSE_STACK],
  result: null,

  loading: false,
  error: null,
  scenarios: [],

  setAppMode: (appMode) => {
    set({ appMode });
    if (appMode === "curate" && get().parcel && !get().inventory) void get().fetchInventory();
  },
  setParcels: (parcels) => set({ parcels }),

  selectParcel: (parcel) => {
    set({ parcel, result: null, inventory: null, error: null });
    if (parcel && get().appMode === "curate") void get().fetchInventory();
  },

  loadSynthetic: async () => {
    try {
      const p = await api.syntheticParcel();
      set({ parcels: [p], parcel: p, result: null, inventory: null, error: null });
      if (get().appMode === "curate") await get().fetchInventory();
    } catch (e) { set({ error: String(e) }); }
  },

  uploadParcels: async (file) => {
    try {
      const { parcels } = await api.uploadParcels(file);
      set({ parcels, parcel: parcels[0] ?? null, result: null, inventory: null, error: null });
      if (parcels[0] && get().appMode === "curate") await get().fetchInventory();
    } catch (e) { set({ error: String(e) }); }
  },

  fetchInventory: async () => {
    const s = get();
    if (!s.parcel) return;
    set({ loading: true, error: null });
    try {
      const inv = await api.inventory(s.parcel.geojson);
      set({
        inventory: inv, benches: inv.benches,
        keptBenches: inv.benches.map((b) => b.formation), loading: false,
      });
    } catch (e) { set({ error: String(e), loading: false }); }
  },

  toggleBench: (code) =>
    set((s) => ({
      keptBenches: s.keptBenches.includes(code)
        ? s.keptBenches.filter((x) => x !== code)
        : [...s.keptBenches, code],
    })),

  toggleCat: (c) => set((s) => ({ cats: { ...s.cats, [c]: !s.cats[c] } })),

  setMode: (mode) => set({ mode }),
  setParam: (k, v) => set((s) => ({ params: { ...s.params, [k]: v } })),
  setSourceAzimuth: (sourceAzimuth) => set({ sourceAzimuth }),
  toggleWinerackFormation: (f) =>
    set((s) => ({
      winerackFormations: s.winerackFormations.includes(f)
        ? s.winerackFormations.filter((x) => x !== f)
        : [...s.winerackFormations, f],
    })),

  buildRequest: () => {
    const s = get();
    if (!s.parcel) return null;
    const base: GenerateRequest = {
      parcel: s.parcel.geojson, params: s.params, mode: s.mode,
      source_azimuth: s.sourceAzimuth, buffer_ft: 5280,
    };
    if (s.mode === "winerack") { base.source_tvd = true; base.formations = s.winerackFormations; }
    return base;
  },

  generate: async () => {
    const req = get().buildRequest();
    if (!req) { set({ error: "select a parcel first" }); return; }
    set({ loading: true, error: null });
    try {
      set({ result: await api.generate(req), loading: false });
    } catch (e) { set({ error: String(e), loading: false }); }
  },

  refreshScenarios: async () => {
    try { set({ scenarios: await api.listScenarios() }); }
    catch (e) { set({ error: String(e) }); }
  },

  save: async (name) => {
    const s = get();
    const req = s.buildRequest();
    if (!req || !s.parcel) return;
    try {
      await api.saveScenario(dealIdFor(s.parcel.label),
        `${s.params.well_type}_${s.params.objective}`, name || s.parcel.label, req);
      await get().refreshScenarios();
    } catch (e) { set({ error: String(e) }); }
  },

  load: async (deal_id, scenario_id) => {
    set({ loading: true, error: null });
    try {
      const r = await api.loadScenario(deal_id, scenario_id);
      set({
        appMode: "override",
        result: {
          mode: "loaded", placed_wells: 0, placed_legs: 0, azimuth_deg: null,
          summary: `loaded ${deal_id} / ${scenario_id}`, warehouse_notes: [],
          geojson: r.geojson, gunbarrel: r.gunbarrel,
        },
        loading: false,
      });
    } catch (e) { set({ error: String(e), loading: false }); }
  },

  remove: async (deal_id, scenario_id) => {
    try { await api.deleteScenario(deal_id, scenario_id); await get().refreshScenarios(); }
    catch (e) { set({ error: String(e) }); }
  },
}));
