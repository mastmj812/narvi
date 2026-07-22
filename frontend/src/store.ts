import { create } from "zustand";
import {
  api,
  type Category,
  type ComposedSummary,
  type CurateSummary,
  type GenerateRequest,
  type GenerateResponse,
  type BenchInfo,
  type GunbarrelData,
  type InventoryResponse,
  type DirectionFeasibility,
  type OverrideSummary,
  type Params,
  type ParcelInfo,
  type ScanConfig,
  type ScenarioSummary,
} from "./api/client";

// Per-bench inventory source — the core of the unified (no curate/override
// toggle) model: for each bench the user either adopts the Novi baseline,
// generates their own wells, or drops it. The working set = the union across
// benches, plus PDP as reference.
export type BenchSource = "novi" | "generate" | "off";

const DEFAULT_PARAMS: Params = {
  // 330 ft setback is the typical section-line legal setback (default). N/S == E/W
  // by default => the engine uses a uniform buffer; differ them for an asymmetric
  // window (e.g. 100 N/S toe/heel, 330 E/W section lines).
  spacing_ft: 880, setback_ft: 330, setback_ns_ft: 330, setback_ew_ft: 330,
  formation: "WCA_1", target_tvd_ft: 11000,
  well_type: "single", objective: "max_lateral", drill_from: "auto", anchor: "auto",
  azimuth_deg: null, min_lateral_ft: 4000, uturn_min_leg_to_leg_ft: 990,
};

export function dealIdFor(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "deal";
}

// Params recoverable from a persisted ScenarioParams jsonb — the restore source
// for override saves that predate summary.generate (wine-rack zones weren't
// kept back then, so those restore single-bench fields only).
const SAVED_PARAM_KEYS = [
  "spacing_ft", "setback_ft", "setback_ns_ft", "setback_ew_ft", "formation",
  "target_tvd_ft", "well_type", "objective", "drill_from", "anchor",
  "azimuth_deg", "min_lateral_ft", "uturn_min_leg_to_leg_ft",
] as const;

function paramsFromScenario(sp: Record<string, unknown> | null | undefined): Partial<Params> {
  if (!sp) return {};
  const out: Record<string, unknown> = {};
  for (const k of SAVED_PARAM_KEYS) {
    if (sp[k] != null) out[k] = sp[k];
  }
  return out as Partial<Params>;
}

// One row per bench in the unified bench table: the union of the unit's overlap
// inventory (Novi counts) and the area-developable benches (generation TVD /
// spacing control). Overlap counts are the unit's truth; the dev median TVD is
// preferred for generation (producer-sourced — overlap medians can carry Novi
// placeholder TVDs, e.g. WDFD RES ~19k).
export interface BenchRow {
  formation: string;
  median_tvd_ft: number | null;
  n_pdp: number;
  n_pud: number;
  n_res: number;
  suggested_spacing_ft: number | null;
  hasNovi: boolean;               // any overlapping PUD/RES to adopt
  n_supported: number | null;     // pud/res sticks with offset support (sql/30); null in dev-only
}

export function benchRows(s: Pick<State, "benches" | "devBenches">): BenchRow[] {
  const map = new Map<string, BenchRow>();
  for (const b of s.devBenches) {
    map.set(b.formation, {
      formation: b.formation, median_tvd_ft: b.median_tvd_ft,
      n_pdp: b.n_pdp, n_pud: b.n_pud, n_res: b.n_res,
      suggested_spacing_ft: b.suggested_spacing_ft, hasNovi: false,
      n_supported: null,
    });
  }
  for (const b of s.benches) {
    const dev = map.get(b.formation);
    map.set(b.formation, {
      formation: b.formation,
      median_tvd_ft: dev?.median_tvd_ft ?? b.median_tvd_ft,
      n_pdp: b.n_pdp, n_pud: b.n_pud, n_res: b.n_res,
      suggested_spacing_ft: dev?.suggested_spacing_ft ?? b.suggested_spacing_ft,
      hasNovi: b.n_pud + b.n_res > 0,
      n_supported: b.n_supported ?? null,
    });
  }
  return [...map.values()].sort(
    (a, b) => (a.median_tvd_ft ?? Infinity) - (b.median_tvd_ft ?? Infinity));
}

// Default sources on inventory load: adopt Novi wherever the unit has PUD/RES;
// everything else (dev-only or PDP-only benches) starts off.
function seedBenchSources(inv: InventoryResponse): Record<string, BenchSource> {
  const src: Record<string, BenchSource> = {};
  for (const b of inv.dev_benches) src[b.formation] = "off";
  for (const b of inv.benches) src[b.formation] = b.n_pud + b.n_res > 0 ? "novi" : "off";
  return src;
}

// The generator zones implied by the bench table: every generate-sourced bench,
// TVD/spacing resolved hard-override -> bench control -> deal-level default.
export function zonesForGenerate(
  s: Pick<State, "benches" | "devBenches" | "benchSource" | "benchTvd" | "benchSpacing" | "params">,
): { formation: string; target_tvd_ft: number; spacing_ft: number }[] {
  return benchRows(s)
    .filter((r) => s.benchSource[r.formation] === "generate")
    .map((r) => ({
      formation: r.formation,
      target_tvd_ft: s.benchTvd[r.formation] ?? r.median_tvd_ft ?? s.params.target_tvd_ft,
      spacing_ft: s.benchSpacing[r.formation] ?? r.suggested_spacing_ft ?? s.params.spacing_ft,
    }));
}

export function buildRequestFrom(
  s: Pick<State, "parcel" | "params" | "sourceAzimuth" | "benches" | "devBenches"
    | "benchSource" | "benchTvd" | "benchSpacing">,
): GenerateRequest | null {
  if (!s.parcel) return null;
  const zones = zonesForGenerate(s);
  if (zones.length === 0) return null;
  return {
    parcel: s.parcel.geojson, params: s.params, mode: "winerack",
    zones, source_azimuth: s.sourceAzimuth, buffer_ft: 5280,
    // score fresh sticks so the gun-barrel shows the handoff category (the
    // same PDP/PUD/UPSIDE the workbook inventory tab will carry)
    score_support: true,
  };
}

// True when generate-sourced benches exist but the on-screen result doesn't
// match the current recipe (params/zone changed, or nothing generated yet) —
// the working set is missing/stale until the user regenerates.
export function genStale(s: State): boolean {
  const req = buildRequestFrom(s);
  if (!req) return false;
  return !s.result || s.lastGenKey !== JSON.stringify(req);
}

type ComposeSlice = Pick<State, "inventory" | "result" | "benchSource" | "cats" | "culledWells">;

// The composed working-set FeatureCollection: Novi-sourced benches' PUD/RES from
// the inventory + generate-sourced benches' wells from the result + PDP always
// (reality/reference, independent of bench source), culls across everything.
export function composeFC(s: ComposeSlice): GeoJSON.FeatureCollection | null {
  const inv = s.inventory?.geojson ?? null;
  const gen = s.result?.geojson ?? null;
  if (!inv && !gen) return null;
  const culled = new Set(s.culledWells);
  const features: GeoJSON.Feature[] = [];
  if (inv) {
    for (const f of inv.features) {
      const p = f.properties ?? {};
      if (p.kind === "leg" || p.kind === "turn") {
        if (culled.has(p.well_name)) continue;
        if (p.context || p.category === "pdp") {
          if (s.cats.pdp) features.push(f);
        } else if (p.kind === "turn") {
          if (s.benchSource[p.formation] === "novi") features.push(f);
        } else if ((p.category === "pud" || p.category === "res")
            && s.benchSource[p.formation] === "novi" && s.cats[p.category as Category]) {
          features.push(f);
        }
      } else if (p.kind !== "window") {
        features.push(f);         // parcel etc.
      }
    }
  }
  if (gen) {
    for (const f of gen.features) {
      const p = f.properties ?? {};
      if (p.kind === "parcel") { if (!inv) features.push(f); continue; }
      if (p.kind === "window") { features.push(f); continue; }
      if (culled.has(p.well_name)) continue;
      if (s.benchSource[p.formation] === "generate") features.push(f);
    }
  }
  return { type: "FeatureCollection", features };
}

// The composed gun-barrel: same source rules as composeFC. PDP points carry
// context=true so the chart's plan census excludes them (they render solid and
// full-size — reference, not dimmed).
export function composeGunbarrel(s: ComposeSlice): GunbarrelData | null {
  const inv = s.inventory?.gunbarrel ?? null;
  const gen = s.result?.gunbarrel ?? null;
  if (!inv && !gen) return null;
  const culled = new Set(s.culledWells);
  const points: GunbarrelData["points"] = [];
  const links: GunbarrelData["links"] = [];
  if (inv) {
    for (const p of inv.points) {
      if (culled.has(p.well_name)) continue;
      if (p.category === "pdp" || p.context) {
        if (s.cats.pdp) points.push({ ...p, context: true });
      } else if ((p.category === "pud" || p.category === "res")
          && s.benchSource[p.formation] === "novi" && s.cats[p.category as Category]) {
        points.push(p);
      }
    }
    for (const l of inv.links) {
      if (!culled.has(l.well_name) && s.benchSource[l.formation] === "novi") links.push(l);
    }
  }
  if (gen) {
    for (const p of gen.points) {
      if (culled.has(p.well_name)) continue;
      if (p.category !== "pdp" && s.benchSource[p.formation] === "generate") points.push(p);
    }
    for (const l of gen.links) {
      if (!culled.has(l.well_name) && s.benchSource[l.formation] === "generate") links.push(l);
    }
  }
  if (points.length === 0) return null;
  return {
    formations: [],               // legend rebuilt client-side (colorForBlueox)
    points, links,
    azimuth_deg: gen?.azimuth_deg ?? inv?.azimuth_deg ?? null,
  };
}

// The FC for EXPORT: composed working set minus context wells (offset background
// is for the eyes, never for the GeoJSON/CSV handoff).
export function exportFC(s: State): GeoJSON.FeatureCollection | null {
  const fc = composeFC(s);
  if (!fc) return null;
  return { ...fc, features: fc.features.filter((f) => !(f.properties?.context)) };
}

interface State {
  parcels: ParcelInfo[];
  parcel: ParcelInfo | null;

  // inventory (per-deal, fetched explicitly via "Load inventory")
  inventory: InventoryResponse | null;
  // parcel feasibility card (fetched alongside the inventory) + config scan
  feasibility: DirectionFeasibility[] | null;
  scan: ScanConfig[] | null;
  scanning: boolean;
  benches: BenchInfo[];            // overlap inventory (unit truth: Novi counts)
  devBenches: BenchInfo[];         // area-developable benches (generation control)
  benchSource: Record<string, BenchSource>;
  cats: Record<Category, boolean>;
  culledWells: string[];           // per-well cull (by well_name) — hidden from map/export
  // per-well handoff-category override (well_name -> PUD | UPSIDE). Auto value
  // comes from the server (pdp_count_3mi >= 3 -> PUD); shift-click on the
  // gun-barrel toggles. Applied server-side at save (PDP wells not overridable).
  categoryOverrides: Record<string, "PUD" | "UPSIDE">;

  // generator (deal-level params; per-bench TVD/spacing live on the bench rows)
  params: Params;
  sourceAzimuth: boolean;
  benchSpacing: Record<string, number>;   // per-bench leg-to-leg override (formation -> ft)
  // per-bench hard TVD override (formation -> ft) for generated locations —
  // trumps the warehouse median (novi_intel WCB_2 TVDs can run deep / mis-tagged;
  // the geologist's number wins). Structural, so it resets on parcel change.
  benchTvd: Record<string, number>;
  result: GenerateResponse | null;
  lastGenKey: string | null;       // JSON of the request behind `result` (staleness)
  // identity of the loaded / last-saved scenario — drives the "loaded" marker in
  // the scenario list, seeds the save-name box, and names exports
  loaded: { deal_id: string; scenario_id: string; name: string | null } | null;

  loading: boolean;
  error: string | null;
  scenarios: ScenarioSummary[];

  // map overlays: Texas/NM survey grid (blocks + sections) + basin-wide PDP tiles
  showBlocks: boolean;
  showSections: boolean;
  showPdpWells: boolean;
  supportColor: boolean;          // color pud/res legs by offset-PDP support (sql/30) + dim unsupported

  // gun-barrel: mirror the x-axis (offset sign is canonical +=E/S; the user may
  // prefer the section laid out the other way round)
  gbFlip: boolean;

  setParcels: (p: ParcelInfo[]) => void;
  selectParcel: (p: ParcelInfo | null) => void;
  // rename a deal in place (uploads carry placeholder labels — the shapefile is
  // geometry-only; the user names deals). Keeps inventory/results: same geometry.
  renameParcel: (oldLabel: string, newLabel: string) => void;
  loadSynthetic: () => Promise<void>;
  uploadParcels: (file: File) => Promise<void>;
  // seed: false keeps the current bench sources / params instead of reseeding
  // them from the discovered benches (used when restoring a saved scenario —
  // the recipe must survive the inventory arriving)
  fetchInventory: (opts?: { seed?: boolean }) => Promise<void>;
  // config scan (azimuth x type x spacing through the placement engine) + adopt
  runScan: () => Promise<void>;
  adoptConfig: (c: ScanConfig) => void;
  setBenchSource: (formation: string, src: BenchSource) => void;
  toggleCat: (c: Category) => void;
  toggleCull: (wellName: string) => void;
  restoreAllCulled: () => void;
  // toggle the PUD/UPSIDE override for a planned well; `auto` is the server's
  // classification (the toggle flips away from the effective value, and
  // clearing back to the auto value removes the override entirely)
  toggleCategoryOverride: (wellName: string, auto: "PUD" | "UPSIDE") => void;

  setParam: <K extends keyof Params>(k: K, v: Params[K]) => void;
  setSourceAzimuth: (v: boolean) => void;
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
  setSupportColor: (v: boolean) => void;
  toggleGbFlip: () => void;
}

// state cleared whenever the working parcel changes
const PARCEL_RESET = {
  result: null, inventory: null, benches: [] as BenchInfo[], devBenches: [] as BenchInfo[],
  benchSource: {} as Record<string, BenchSource>, benchSpacing: {} as Record<string, number>,
  benchTvd: {} as Record<string, number>, culledWells: [] as string[],
  feasibility: null, scan: null, scanning: false,
  categoryOverrides: {} as Record<string, "PUD" | "UPSIDE">,
  lastGenKey: null, loaded: null, error: null,
};

export const useStore = create<State>((set, get) => ({
  parcels: [],
  parcel: null,

  inventory: null,
  feasibility: null,
  scan: null,
  scanning: false,
  benches: [],
  devBenches: [],
  benchSource: {},
  cats: { pdp: true, pud: true, res: false },
  culledWells: [],
  categoryOverrides: {},

  params: { ...DEFAULT_PARAMS },
  sourceAzimuth: true,
  benchSpacing: {},
  benchTvd: {},
  result: null,
  lastGenKey: null,
  loaded: null,

  loading: false,
  error: null,
  scenarios: [],

  // survey grid on by default so it's visible without hunting for a toggle;
  // both are zoom-gated (blocks z8, sections z11) and lazy-fetched by MapView.
  showBlocks: true,
  showSections: true,
  showPdpWells: true,
  supportColor: false,
  gbFlip: false,

  setParcels: (parcels) => set({ parcels }),

  // Picking a parcel (upload / dropdown / synthetic) NEVER auto-queries the
  // warehouse — a multi-polygon upload would otherwise fire an expensive
  // inventory fetch for whichever DSU happens to be first. The user starts the
  // fetch explicitly via the "Load inventory" button (fetchInventory).
  selectParcel: (parcel) => set({ parcel, ...PARCEL_RESET }),

  renameParcel: (oldLabel, newLabel) =>
    set((s) => {
      const name = newLabel.trim();
      // empty or colliding with another deal's label -> ignore (labels key the
      // deal list and dealIdFor; a dup would merge two deals' saves)
      if (!name || name === oldLabel || s.parcels.some((p) => p.label === name)) return {};
      return {
        parcels: s.parcels.map((p) => (p.label === oldLabel ? { ...p, label: name } : p)),
        parcel: s.parcel?.label === oldLabel ? { ...s.parcel, label: name } : s.parcel,
      };
    }),

  loadSynthetic: async () => {
    try {
      const p = await api.syntheticParcel();
      set({ parcels: [p], parcel: p, ...PARCEL_RESET });
    } catch (e) { set({ error: String(e) }); }
  },

  uploadParcels: async (file) => {
    try {
      const { parcels } = await api.uploadParcels(file);
      set({ parcels, parcel: parcels[0] ?? null, ...PARCEL_RESET });
    } catch (e) { set({ error: String(e) }); }
  },

  // Discover the parcel's actual benches (basin-correct — Delaware OR Midland)
  // and seed the bench sources + the single-bench generator defaults from them,
  // so nothing is hardcoded to one basin.
  fetchInventory: async (opts) => {
    const s = get();
    if (!s.parcel) return;
    const seed = opts?.seed ?? true;
    set({ loading: true, error: null });
    try {
      const inv = await api.inventory(s.parcel.geojson);
      const sourceable = inv.dev_benches.filter((b) => b.n_pdp >= 3);
      const shallow = sourceable.find((b) => b.median_tvd_ft != null)
        ?? inv.benches.find((b) => b.median_tvd_ft != null);
      set({
        inventory: inv, benches: inv.benches, devBenches: inv.dev_benches,
        ...(seed ? {
          benchSource: seedBenchSources(inv),
          params: shallow
            ? { ...get().params, formation: shallow.formation,
                target_tvd_ft: shallow.median_tvd_ft ?? get().params.target_tvd_ft }
            : get().params,
        } : {}),
        loading: false,
      });
      // feasibility card rides along (best-effort — a failure never blocks the
      // inventory; the scan re-fetches with current params anyway)
      try {
        const f = await api.feasibility(s.parcel.geojson, get().params);
        set({ feasibility: f.directions });
      } catch { /* card just doesn't render */ }
    } catch (e) { set({ error: String(e), loading: false }); }
  },

  runScan: async () => {
    const s = get();
    if (!s.parcel) return;
    set({ scanning: true, error: null });
    try {
      // fresh feasibility so the scan honors the CURRENT setbacks/min-lateral
      const f = await api.feasibility(s.parcel.geojson, s.params);
      const r = await api.scan(s.parcel.geojson, s.params, f.directions);
      set({ feasibility: f.directions, scan: r.configs, scanning: false });
    } catch (e) { set({ error: String(e), scanning: false }); }
  },

  // Adopt a scan row: deal-level azimuth/type/spacing become the generator
  // params (azimuth as an EXPLICIT override — reproducible, not re-sourced),
  // and benches already set to generate follow the adopted spacing (per-bench
  // spacing otherwise overrides the deal default and the adoption would no-op).
  adoptConfig: (c) =>
    set((s) => {
      const benchSpacing = { ...s.benchSpacing };
      for (const [f, src] of Object.entries(s.benchSource)) {
        if (src === "generate") benchSpacing[f] = c.spacing_ft;
      }
      return {
        params: {
          ...s.params, azimuth_deg: c.azimuth_deg, spacing_ft: c.spacing_ft,
          well_type: c.well_type as Params["well_type"],
        },
        benchSpacing,
      };
    }),

  setBenchSource: (formation, src) =>
    set((s) => ({ benchSource: { ...s.benchSource, [formation]: src } })),

  toggleCat: (c) => set((s) => ({ cats: { ...s.cats, [c]: !s.cats[c] } })),

  toggleCull: (wellName) =>
    set((s) => ({
      culledWells: s.culledWells.includes(wellName)
        ? s.culledWells.filter((x) => x !== wellName)
        : [...s.culledWells, wellName],
    })),
  restoreAllCulled: () => set({ culledWells: [] }),

  toggleCategoryOverride: (wellName, auto) =>
    set((s) => {
      const overrides = { ...s.categoryOverrides };
      const effective = overrides[wellName] ?? auto;
      const next = effective === "PUD" ? "UPSIDE" : "PUD";
      // flipping back to the auto value clears the override (auto stays live)
      if (next === auto) delete overrides[wellName];
      else overrides[wellName] = next;
      return { categoryOverrides: overrides };
    }),

  setParam: (k, v) => set((s) => ({ params: { ...s.params, [k]: v } })),
  setSourceAzimuth: (sourceAzimuth) => set({ sourceAzimuth }),
  setBenchSpacing: (f, v) => set((s) => ({ benchSpacing: { ...s.benchSpacing, [f]: v } })),
  setBenchTvd: (f, v) => set((s) => {
    const benchTvd = { ...s.benchTvd };
    if (v == null || !Number.isFinite(v) || v <= 0) delete benchTvd[f];
    else benchTvd[f] = v;
    return { benchTvd };
  }),

  buildRequest: () => buildRequestFrom(get()),

  generate: async () => {
    const req = get().buildRequest();
    if (!req) { set({ error: "set at least one bench to generate" }); return; }
    set({ loading: true, error: null });
    try {
      set({ result: await api.generate(req), lastGenKey: JSON.stringify(req), loading: false });
    } catch (e) { set({ error: String(e), loading: false }); }
  },

  refreshScenarios: async () => {
    try { set({ scenarios: await api.listScenarios() }); }
    catch (e) { set({ error: String(e) }); }
  },

  // One save for the whole composed plan: the server re-derives the kept Novi
  // baseline, regenerates the generate-sourced benches from the recipe, merges,
  // bakes culls out, and persists — so the saved rows never depend on client
  // display state.
  save: async (name) => {
    const s = get();
    if (!s.parcel || !s.inventory) return;
    const deal = dealIdFor(s.parcel.label);
    // scenario_id derives from the NAME so differently-named saves are distinct
    // rows; re-saving under the same name overwrites that row (deliberate).
    const slug = dealIdFor(name || s.parcel.label);
    try {
      const finalName = name || s.parcel.label;
      await api.saveComposedScenario({
        deal_id: deal, scenario_id: `plan_${slug}`, name: finalName,
        parcel: s.parcel.geojson,
        bench_sources: s.benchSource,
        categories: (["pdp", "pud", "res"] as Category[]).filter((c) => s.cats[c]),
        culled_wells: s.culledWells,
        category_overrides: s.categoryOverrides,
        params: s.params,
        zones: zonesForGenerate(s),
        source_azimuth: s.sourceAzimuth,
      });
      await get().refreshScenarios();
      // the saved scenario is now "the one we're working on" — the loaded marker
      // and the name box follow it (a legacy-loaded id is superseded by plan_*)
      set({ loaded: { deal_id: deal, scenario_id: `plan_${slug}`, name: finalName } });
    } catch (e) { set({ error: String(e) }); }
  },

  load: async (deal_id, scenario_id) => {
    set({ loading: true, error: null });
    try {
      const r = await api.loadScenario(deal_id, scenario_id);
      const meta = get().scenarios.find((s) => s.deal_id === deal_id && s.scenario_id === scenario_id);
      const summary = r.header?.summary as
        Partial<ComposedSummary> | Partial<CurateSummary> | null | undefined;
      const mergeParcels = (restored: ParcelInfo) =>
        get().parcels.some((p) => p.label === restored.label)
          ? get().parcels : [...get().parcels, restored];

      if (summary?.mode === "composed" && r.parcel) {
        // composed save = the full recipe: restore bench sources + generator
        // inputs, refetch live inventory, regenerate the generate benches —
        // the working set reconstructs editable, exactly as saved
        const cs = summary as ComposedSummary;
        const zones = cs.generate?.zones ?? [];
        set({
          parcels: mergeParcels(r.parcel), parcel: r.parcel, ...PARCEL_RESET,
          loaded: { deal_id, scenario_id, name: meta?.name ?? null },
          params: { ...get().params, ...paramsFromScenario(cs.generate?.params) },
          sourceAzimuth: cs.generate?.source_azimuth ?? true,
          benchSource: (cs.bench_sources ?? {}) as Record<string, BenchSource>,
          cats: {
            pdp: (cs.categories ?? []).includes("pdp"),
            pud: (cs.categories ?? []).includes("pud"),
            res: (cs.categories ?? []).includes("res"),
          },
          benchTvd: Object.fromEntries(zones.map((z) => [z.formation, z.target_tvd_ft])),
          benchSpacing: Object.fromEntries(zones.filter((z) => z.spacing_ft != null)
            .map((z) => [z.formation, z.spacing_ft as number])),
        });
        await get().fetchInventory({ seed: false });
        set({
          culledWells: cs.culled_wells ?? [],
          categoryOverrides: cs.category_overrides ?? {},
          loading: false,
        });
        if (Object.values(cs.bench_sources ?? {}).includes("generate")) {
          await get().generate();
        }
        return;
      }

      if (summary?.mode === "curate" && r.parcel) {
        // legacy curate save = a filter recipe over live inventory — map it into
        // the unified model: kept benches with Novi inventory -> source 'novi'
        set({
          parcels: mergeParcels(r.parcel), parcel: r.parcel, ...PARCEL_RESET,
          loaded: { deal_id, scenario_id, name: meta?.name ?? null },
        });
        await get().fetchInventory({ seed: false });
        const kept = new Set(summary.kept_benches ?? []);
        const active = new Set(summary.categories ?? ["pdp", "pud", "res"]);
        const src: Record<string, BenchSource> = {};
        for (const row of benchRows(get())) {
          src[row.formation] = kept.has(row.formation) && row.hasNovi ? "novi" : "off";
        }
        set({
          benchSource: src,
          cats: { pdp: active.has("pdp"), pud: active.has("pud"), res: active.has("res") },
          culledWells: summary.culled_wells ?? [],
          loading: false,
        });
        return;
      }

      // legacy override save: show the persisted wells immediately (frozen
      // result) and map the recipe into the unified model — the generated
      // formations become generate-sourced benches, so the plan stays editable.
      const gen = (summary as OverrideSummary | null | undefined)?.generate;
      const restored = r.parcel;
      // deal_id derives from the parcel label on save, so it identifies the
      // parcel whether the current one carries the shapefile name or the slug
      const cur = get().parcel;
      const sameParcel = restored != null && cur != null && dealIdFor(cur.label) === deal_id;
      const parcels = restored && !sameParcel && !get().parcels.some((p) => p.label === restored.label)
        ? [...get().parcels, restored] : get().parcels;
      const params: Params = gen
        ? { ...get().params, ...gen.params }
        : { ...get().params, ...paramsFromScenario(r.header?.params) };
      const zones = gen?.zones ?? [];
      const src: Record<string, BenchSource> = {};
      for (const z of zones) src[z.formation] = "generate";
      if (zones.length === 0 && params.formation) src[params.formation] = "generate";
      for (const pt of (r.gunbarrel?.points ?? []) as GunbarrelData["points"]) {
        if (pt.category === "generated") src[pt.formation] = "generate";
      }
      set({
        parcels,
        parcel: sameParcel ? cur : restored ?? cur,
        ...(sameParcel ? {} : { inventory: null, benches: [], devBenches: [] }),
        params,
        sourceAzimuth: gen?.source_azimuth ?? get().sourceAzimuth,
        benchSource: src,
        benchTvd: zones.length
          ? Object.fromEntries(zones.map((z) => [z.formation, z.target_tvd_ft]))
          : (params.formation ? { [params.formation]: params.target_tvd_ft } : {}),
        benchSpacing: zones.length
          ? Object.fromEntries(zones.filter((z) => z.spacing_ft != null)
              .map((z) => [z.formation, z.spacing_ft as number]))
          : (params.formation ? { [params.formation]: params.spacing_ft } : {}),
        culledWells: [],
        lastGenKey: null,
        loaded: { deal_id, scenario_id, name: meta?.name ?? null },
        result: {
          mode: "loaded", placed_wells: 0, placed_legs: 0, azimuth_deg: null,
          summary: `loaded ${deal_id} / ${scenario_id}`, warehouse_notes: [],
          geojson: r.geojson, gunbarrel: r.gunbarrel,
        },
        loading: false,
      });
      // background refetch: the persisted wells render immediately; PDP context
      // fades in when the inventory for the restored parcel arrives. seed:false
      // so the arriving benches don't clobber the restored recipe.
      if (restored && (!sameParcel || !get().inventory)) void get().fetchInventory({ seed: false });
    } catch (e) { set({ error: String(e), loading: false }); }
  },

  remove: async (deal_id, scenario_id) => {
    try { await api.deleteScenario(deal_id, scenario_id); await get().refreshScenarios(); }
    catch (e) { set({ error: String(e) }); }
  },

  setShowBlocks: (showBlocks) => set({ showBlocks }),
  setShowSections: (showSections) => set({ showSections }),
  setShowPdpWells: (showPdpWells) => set({ showPdpWells }),
  setSupportColor: (supportColor) => set({ supportColor }),
  toggleGbFlip: () => set((s) => ({ gbFlip: !s.gbFlip })),
}));
