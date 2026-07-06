import { create } from "zustand";
import {
  api,
  WAREHOUSE_STACK,
  type Category,
  type CurateSummary,
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
  // 330 ft setback is the typical section-line legal setback (default). N/S == E/W
  // by default => the engine uses a uniform buffer; differ them for an asymmetric
  // window (e.g. 100 N/S toe/heel, 330 E/W section lines).
  spacing_ft: 880, setback_ft: 330, setback_ns_ft: 330, setback_ew_ft: 330,
  formation: "WCA_1", target_tvd_ft: 11000,
  well_type: "single", objective: "max_lateral", drill_from: "auto", anchor: "auto",
  azimuth_deg: null, min_lateral_ft: 4000,
};

export function dealIdFor(label: string): string {
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
  culled: string[] = [],
): GeoJSON.FeatureCollection {
  const keptSet = new Set(kept);
  const culledSet = new Set(culled);
  return {
    type: "FeatureCollection",
    features: fc.features.filter((f) => {
      const p = f.properties ?? {};
      // culling keys on well_name -> drops both legs of a U-turn AND its turn arc
      if (culledSet.has(p.well_name)) return false;
      if (p.kind !== "leg") return true;
      // near-parcel PDP context: not part of the unit, so it bypasses the bench
      // filter — the PDP category toggle (or a cull, above) hides it
      if (p.context) return cats.pdp;
      return keptSet.has(p.formation) && catActive(cats, p.category);
    }),
  };
}

// Cull-only filter (override mode: the generated plan isn't bench/cat filtered).
export function cullFC(
  fc: GeoJSON.FeatureCollection, culled: string[],
): GeoJSON.FeatureCollection {
  if (culled.length === 0) return fc;
  const culledSet = new Set(culled);
  return {
    type: "FeatureCollection",
    features: fc.features.filter((f) => !culledSet.has((f.properties ?? {}).well_name)),
  };
}

// The FC currently on the map / for export: inventory (curate — bench + category
// + cull filtered) or the generated result (override — cull filtered). null when
// nothing is loaded yet (parcel-only outline is handled by the caller).
export function currentFC(s: State): GeoJSON.FeatureCollection | null {
  if (s.appMode === "override") {
    return s.result ? cullFC(s.result.geojson, s.culledWells) : null;
  }
  return s.inventory ? filterFC(s.inventory.geojson, s.keptBenches, s.cats, s.culledWells) : null;
}

// The FC for EXPORT: currentFC minus context wells (offset background is for the
// eyes, never for the GeoJSON/CSV handoff).
export function exportFC(s: State): GeoJSON.FeatureCollection | null {
  const fc = currentFC(s);
  if (!fc) return null;
  return { ...fc, features: fc.features.filter((f) => !(f.properties?.context)) };
}

interface State {
  appMode: AppMode;
  parcels: ParcelInfo[];
  parcel: ParcelInfo | null;

  // curate
  inventory: InventoryResponse | null;
  benches: BenchInfo[];            // overlap inventory (curate menu)
  devBenches: BenchInfo[];         // area-developable benches (override menu)
  keptBenches: string[];
  cats: Record<Category, boolean>;
  culledWells: string[];           // per-well cull (by well_name) — hidden from map/export

  // override (generator)
  mode: Mode;
  params: Params;
  sourceAzimuth: boolean;
  winerackFormations: string[];
  benchSpacing: Record<string, number>;   // per-bench leg-to-leg override (formation -> ft)
  // per-bench hard TVD override (formation -> ft) for generated locations —
  // trumps the warehouse median (novi_intel WCB_2 TVDs can run deep / mis-tagged;
  // the geologist's number wins). Structural, so it resets on parcel change.
  benchTvd: Record<string, number>;
  result: GenerateResponse | null;
  loaded: { deal_id: string; name: string | null } | null;  // identity of a loaded scenario (export naming when no parcel)

  loading: boolean;
  error: string | null;
  scenarios: ScenarioSummary[];

  // map overlays: Texas/NM survey grid (blocks + sections) + basin-wide PDP tiles
  showBlocks: boolean;
  showSections: boolean;
  showPdpWells: boolean;

  // gun-barrel: mirror the x-axis (offset sign is canonical +=E/S; the user may
  // prefer the section laid out the other way round)
  gbFlip: boolean;

  setAppMode: (m: AppMode) => void;
  setParcels: (p: ParcelInfo[]) => void;
  selectParcel: (p: ParcelInfo | null) => void;
  loadSynthetic: () => Promise<void>;
  uploadParcels: (file: File) => Promise<void>;
  fetchInventory: () => Promise<void>;
  toggleBench: (code: string) => void;
  toggleCat: (c: Category) => void;
  toggleCull: (wellName: string) => void;
  restoreAllCulled: () => void;

  setMode: (m: Mode) => void;
  setParam: <K extends keyof Params>(k: K, v: Params[K]) => void;
  setSourceAzimuth: (v: boolean) => void;
  toggleWinerackFormation: (f: string) => void;
  setBenchSpacing: (f: string, v: number) => void;
  setBenchTvd: (f: string, v: number | null) => void;   // null/NaN clears the override
  buildRequest: () => GenerateRequest | null;
  generate: () => Promise<void>;

  refreshScenarios: () => Promise<void>;
  save: (name: string) => Promise<void>;
  load: (deal_id: string, scenario_id: string) => Promise<void>;
  remove: (deal_id: string, scenario_id: string) => Promise<void>;

  setShowBlocks: (v: boolean) => void;
  setShowSections: (v: boolean) => void;
  setShowPdpWells: (v: boolean) => void;
  toggleGbFlip: () => void;
}

export const useStore = create<State>((set, get) => ({
  appMode: "curate",
  parcels: [],
  parcel: null,

  inventory: null,
  benches: [],
  devBenches: [],
  keptBenches: [],
  cats: { pdp: true, pud: true, res: false },
  culledWells: [],

  mode: "single",
  params: { ...DEFAULT_PARAMS },
  sourceAzimuth: true,
  winerackFormations: [...WAREHOUSE_STACK],
  benchSpacing: {},
  benchTvd: {},
  result: null,
  loaded: null,

  loading: false,
  error: null,
  scenarios: [],

  // survey grid on by default so it's visible without hunting for a toggle;
  // both are zoom-gated (blocks z8, sections z11) and lazy-fetched by MapView.
  showBlocks: true,
  showSections: true,
  showPdpWells: true,
  gbFlip: false,

  setAppMode: (appMode) => {
    set({ appMode });
    if (appMode === "curate" && get().parcel && !get().inventory) void get().fetchInventory();
  },
  setParcels: (parcels) => set({ parcels }),

  selectParcel: (parcel) => {
    set({ parcel, result: null, inventory: null, culledWells: [], benchTvd: {}, loaded: null, error: null });
    if (parcel) void get().fetchInventory();   // benches feed BOTH curate + override
  },

  loadSynthetic: async () => {
    try {
      const p = await api.syntheticParcel();
      set({ parcels: [p], parcel: p, result: null, inventory: null, culledWells: [], benchTvd: {}, loaded: null, error: null });
      await get().fetchInventory();
    } catch (e) { set({ error: String(e) }); }
  },

  uploadParcels: async (file) => {
    try {
      const { parcels } = await api.uploadParcels(file);
      set({ parcels, parcel: parcels[0] ?? null, result: null, inventory: null, culledWells: [], benchTvd: {}, loaded: null, error: null });
      if (parcels[0]) await get().fetchInventory();
    } catch (e) { set({ error: String(e) }); }
  },

  // Discover the parcel's actual benches (basin-correct — Delaware OR Midland)
  // and seed both the curate keptBenches and the override wine-rack + single
  // defaults from them, so nothing is hardcoded to one basin.
  fetchInventory: async () => {
    const s = get();
    if (!s.parcel) return;
    set({ loading: true, error: null });
    try {
      const inv = await api.inventory(s.parcel.geojson);
      // curate menu = what overlaps the unit; override menu = area-developable
      // benches with producing TVD control (>=3 PDP), so e.g. WCA shows even with
      // no well crossing the parcel.
      const sourceable = inv.dev_benches.filter((b) => b.n_pdp >= 3);
      const shallow = sourceable.find((b) => b.median_tvd_ft != null)
        ?? inv.benches.find((b) => b.median_tvd_ft != null);
      set({
        inventory: inv, benches: inv.benches, devBenches: inv.dev_benches,
        keptBenches: inv.benches.map((b) => b.formation),
        winerackFormations: sourceable.map((b) => b.formation),
        params: shallow
          ? { ...get().params, formation: shallow.formation,
              target_tvd_ft: shallow.median_tvd_ft ?? get().params.target_tvd_ft }
          : get().params,
        loading: false,
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

  toggleCull: (wellName) =>
    set((s) => ({
      culledWells: s.culledWells.includes(wellName)
        ? s.culledWells.filter((x) => x !== wellName)
        : [...s.culledWells, wellName],
    })),
  restoreAllCulled: () => set({ culledWells: [] }),

  setMode: (mode) => set({ mode }),
  setParam: (k, v) => set((s) => ({ params: { ...s.params, [k]: v } })),
  setSourceAzimuth: (sourceAzimuth) => set({ sourceAzimuth }),
  toggleWinerackFormation: (f) =>
    set((s) => ({
      winerackFormations: s.winerackFormations.includes(f)
        ? s.winerackFormations.filter((x) => x !== f)
        : [...s.winerackFormations, f],
    })),
  setBenchSpacing: (f, v) => set((s) => ({ benchSpacing: { ...s.benchSpacing, [f]: v } })),
  setBenchTvd: (f, v) => set((s) => {
    const benchTvd = { ...s.benchTvd };
    if (v == null || !Number.isFinite(v) || v <= 0) delete benchTvd[f];
    else benchTvd[f] = v;
    return { benchTvd };
  }),

  buildRequest: () => {
    const s = get();
    if (!s.parcel) return null;
    const base: GenerateRequest = {
      parcel: s.parcel.geojson, params: s.params, mode: s.mode,
      source_azimuth: s.sourceAzimuth, buffer_ft: 5280,
    };
    if (s.mode === "winerack") {
      // explicit per-bench zones: TVD from discovered benches (PDP or Novi-PUD
      // sourced), spacing per bench (user override -> derived -> base). Bypasses the
      // PDP-only source_tvd gate so Novi-PUD-only benches (BS1_S, WCB_1…) develop.
      base.zones = s.winerackFormations.map((f) => {
        const b = s.devBenches.find((d) => d.formation === f);
        return {
          formation: f,
          // hard user TVD (geologist's pick) -> warehouse median -> base param
          target_tvd_ft: s.benchTvd[f] ?? b?.median_tvd_ft ?? s.params.target_tvd_ft,
          spacing_ft: s.benchSpacing[f] ?? b?.suggested_spacing_ft ?? s.params.spacing_ft,
        };
      });
    }
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
    if (!s.parcel) return;
    const deal = dealIdFor(s.parcel.label);
    // scenario_id derives from the NAME so differently-named saves are distinct
    // rows; re-saving under the same name overwrites that row (deliberate).
    const slug = dealIdFor(name || s.parcel.label);
    try {
      if (s.appMode === "curate") {
        // persist the kept Novi inventory baseline (selected benches + active cats)
        const cats = (["pdp", "pud", "res"] as Category[]).filter((c) => s.cats[c]);
        await api.saveCurateScenario(deal, `curate_${slug}`, name || s.parcel.label,
          s.parcel.geojson, s.keptBenches, cats, s.culledWells);
      } else {
        const req = s.buildRequest();
        if (!req) return;
        await api.saveScenario(deal, `${s.params.well_type}_${s.params.objective}_${slug}`,
          name || s.parcel.label, req, s.culledWells);
      }
      await get().refreshScenarios();
    } catch (e) { set({ error: String(e) }); }
  },

  load: async (deal_id, scenario_id) => {
    set({ loading: true, error: null });
    try {
      const r = await api.loadScenario(deal_id, scenario_id);
      const meta = get().scenarios.find((s) => s.deal_id === deal_id && s.scenario_id === scenario_id);
      const summary = r.header?.summary as Partial<CurateSummary> | null | undefined;
      if (summary?.mode === "curate" && r.parcel) {
        // a curate save is a filter recipe over live inventory — restore the
        // EDITABLE curate state (re-select the parcel, refetch inventory,
        // re-apply the recipe) so the loaded scenario renders through the same
        // path it was saved from and stays curate-editable
        const restored = r.parcel;
        const parcels = get().parcels.some((p) => p.label === restored.label)
          ? get().parcels : [...get().parcels, restored];
        set({
          appMode: "curate", parcels, parcel: restored, result: null,
          inventory: null, benchTvd: {}, culledWells: [],
          loaded: { deal_id, name: meta?.name ?? null },
        });
        await get().fetchInventory();
        const active = new Set(summary.categories ?? ["pdp", "pud", "res"]);
        set({
          keptBenches: summary.kept_benches ?? get().keptBenches,
          cats: { pdp: active.has("pdp"), pud: active.has("pud"), res: active.has("res") },
          culledWells: summary.culled_wells ?? [],
          loading: false,
        });
        return;
      }
      // Restore the saved parcel here too: the gun-barrel merges the store's
      // inventory PDP as offset context, so inventory left over from a
      // previously selected parcel would overlay foreign wells in the wrong
      // offset frame (its offsets are relative to THAT parcel's centroid).
      // Refetch only when the parcel actually changes — inventory queries are
      // the expensive part of a load.
      const restored = r.parcel;
      // deal_id derives from the parcel label on save, so it identifies the
      // parcel whether the current one carries the shapefile name or the slug
      const cur = get().parcel;
      const sameParcel = restored != null && cur != null && dealIdFor(cur.label) === deal_id;
      const parcels = restored && !sameParcel && !get().parcels.some((p) => p.label === restored.label)
        ? [...get().parcels, restored] : get().parcels;
      set({
        appMode: "override",
        parcels,
        parcel: sameParcel ? cur : restored ?? cur,
        ...(sameParcel ? {} : { inventory: null, benchTvd: {} }),
        culledWells: [],
        loaded: { deal_id, name: meta?.name ?? null },
        result: {
          mode: "loaded", placed_wells: 0, placed_legs: 0, azimuth_deg: null,
          summary: `loaded ${deal_id} / ${scenario_id}`, warehouse_notes: [],
          geojson: r.geojson, gunbarrel: r.gunbarrel,
        },
        loading: false,
      });
      // background refetch: the persisted wells render immediately; PDP context
      // fades in when the inventory for the restored parcel arrives
      if (restored && (!sameParcel || !get().inventory)) void get().fetchInventory();
    } catch (e) { set({ error: String(e), loading: false }); }
  },

  remove: async (deal_id, scenario_id) => {
    try { await api.deleteScenario(deal_id, scenario_id); await get().refreshScenarios(); }
    catch (e) { set({ error: String(e) }); }
  },

  setShowBlocks: (showBlocks) => set({ showBlocks }),
  setShowSections: (showSections) => set({ showSections }),
  setShowPdpWells: (showPdpWells) => set({ showPdpWells }),
  toggleGbFlip: () => set((s) => ({ gbFlip: !s.gbFlip })),
}));
