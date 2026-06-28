import { create } from "zustand";
import {
  api,
  WAREHOUSE_STACK,
  type GenerateRequest,
  type GenerateResponse,
  type Mode,
  type Params,
  type ParcelInfo,
  type ScenarioSummary,
} from "./api/client";

const DEFAULT_PARAMS: Params = {
  spacing_ft: 880,
  setback_ft: 200,
  formation: "WCA_1",
  target_tvd_ft: 11000,
  well_type: "single",
  objective: "max_lateral",
  azimuth_deg: null,
  min_lateral_ft: 4000,
};

function dealIdFor(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "deal";
}

interface State {
  parcels: ParcelInfo[];
  parcel: ParcelInfo | null;
  mode: Mode;
  params: Params;
  sourceAzimuth: boolean;
  winerackFormations: string[];

  result: GenerateResponse | null;
  loading: boolean;
  error: string | null;

  scenarios: ScenarioSummary[];

  setParcels: (p: ParcelInfo[]) => void;
  selectParcel: (p: ParcelInfo | null) => void;
  setMode: (m: Mode) => void;
  setParam: <K extends keyof Params>(k: K, v: Params[K]) => void;
  setSourceAzimuth: (v: boolean) => void;
  toggleWinerackFormation: (f: string) => void;

  buildRequest: () => GenerateRequest | null;
  loadSynthetic: () => Promise<void>;
  uploadParcels: (file: File) => Promise<void>;
  generate: () => Promise<void>;
  refreshScenarios: () => Promise<void>;
  save: (name: string) => Promise<void>;
  load: (deal_id: string, scenario_id: string) => Promise<void>;
  remove: (deal_id: string, scenario_id: string) => Promise<void>;
}

export const useStore = create<State>((set, get) => ({
  parcels: [],
  parcel: null,
  mode: "single",
  params: { ...DEFAULT_PARAMS },
  sourceAzimuth: true,
  winerackFormations: [...WAREHOUSE_STACK],

  result: null,
  loading: false,
  error: null,
  scenarios: [],

  setParcels: (parcels) => set({ parcels }),
  selectParcel: (parcel) => set({ parcel, result: null, error: null }),
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
      parcel: s.parcel.geojson,
      params: s.params,
      mode: s.mode,
      source_azimuth: s.sourceAzimuth,
      buffer_ft: 5280,
    };
    if (s.mode === "winerack") {
      base.source_tvd = true;
      base.formations = s.winerackFormations;
    }
    return base;
  },

  loadSynthetic: async () => {
    try {
      const p = await api.syntheticParcel();
      set({ parcels: [p], parcel: p, result: null, error: null });
    } catch (e) {
      set({ error: String(e) });
    }
  },

  uploadParcels: async (file) => {
    try {
      const { parcels } = await api.uploadParcels(file);
      set({ parcels, parcel: parcels[0] ?? null, result: null, error: null });
    } catch (e) {
      set({ error: String(e) });
    }
  },

  generate: async () => {
    const req = get().buildRequest();
    if (!req) {
      set({ error: "select a parcel first" });
      return;
    }
    set({ loading: true, error: null });
    try {
      const result = await api.generate(req);
      set({ result, loading: false });
    } catch (e) {
      set({ error: String(e), loading: false });
    }
  },

  refreshScenarios: async () => {
    try {
      set({ scenarios: await api.listScenarios() });
    } catch (e) {
      set({ error: String(e) });
    }
  },

  save: async (name) => {
    const s = get();
    const req = s.buildRequest();
    if (!req || !s.parcel) return;
    const deal_id = dealIdFor(s.parcel.label);
    const scenario_id = `${s.params.well_type}_${s.params.objective}`;
    try {
      await api.saveScenario(deal_id, scenario_id, name || s.parcel.label, req);
      await get().refreshScenarios();
    } catch (e) {
      set({ error: String(e) });
    }
  },

  load: async (deal_id, scenario_id) => {
    set({ loading: true, error: null });
    try {
      const r = await api.loadScenario(deal_id, scenario_id);
      set({
        result: {
          mode: "loaded", placed_wells: 0, placed_legs: 0, azimuth_deg: null,
          summary: `loaded ${deal_id} / ${scenario_id}`, warehouse_notes: [],
          geojson: r.geojson, gunbarrel: r.gunbarrel,
        },
        loading: false,
      });
    } catch (e) {
      set({ error: String(e), loading: false });
    }
  },

  remove: async (deal_id, scenario_id) => {
    try {
      await api.deleteScenario(deal_id, scenario_id);
      await get().refreshScenarios();
    } catch (e) {
      set({ error: String(e) });
    }
  },
}));
