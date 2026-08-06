import { useRef, useState } from "react";
import { type Category, type Params } from "../api/client";
import { colorForBlueox } from "../map/formations";
import {
  benchRows, composeGunbarrel, dealIdFor, genStale, useStore, zonesForGenerate,
  type BenchSource,
} from "../store";

const CATS: { key: Category; label: string }[] = [
  { key: "pdp", label: "PDP (existing)" },
  { key: "pud", label: "PUD (plan)" },
  { key: "res", label: "RES (resource)" },
];

function NumberField<K extends keyof Params>(
  { label, k, step, title }: { label: string; k: K; step?: number; title?: string },
) {
  const value = useStore((s) => s.params[k]) as number;
  const setParam = useStore((s) => s.setParam);
  return (
    <div className="field">
      <label title={title}>{label}</label>
      <input
        type="number"
        step={step ?? 1}
        value={Number.isFinite(value) ? value : 0}
        onChange={(e) => setParam(k, Number(e.target.value) as Params[K])}
      />
    </div>
  );
}

// One workflow, no curate/override toggle: pick a deal, load its inventory,
// then per bench either adopt the Novi baseline, generate your own wells, or
// drop it. The working set (kept Novi + generated + PDP reference) renders in
// one map / gun-barrel and saves as one scenario.
export function PlanPanel() {
  const fileRef = useRef<HTMLInputElement | null>(null);
  // inline deal-rename (uploads carry placeholder labels; the user names deals)
  const [editingLabel, setEditingLabel] = useState<string | null>(null);
  const [draftLabel, setDraftLabel] = useState("");
  const s = useStore();
  const {
    parcel, parcels, scenarios, inventory, benchSource, cats, culledWells,
    params, sourceAzimuth, benchSpacing, benchTvd, result, loading, error,
    feasibility, scan, scanning, runScan, adoptConfig,
    categoryOverrides, toggleCategoryOverride,
    selectParcel, renameParcel, loadSynthetic, uploadParcels, fetchInventory, setBenchSource,
    toggleCat, setParam, setSourceAzimuth, setBenchSpacing, setBenchTvd, generate,
    setDepthWindow,
  } = s;

  const dw = parcel?.depthWindow;
  const windowActive = dw != null && (dw.minFt != null || dw.maxFt != null);
  const attrs = parcel?.attributes ?? {};
  const attr = (k: string) => {
    const v = attrs[k];
    return v == null || v === "" ? null : String(v);
  };
  const hasDeclaredTerms = attr("Min_Depth") != null || attr("Max_Depth") != null
    || attr("DSU_WI") != null || (parcel?.tracts ?? []).length > 0;

  const rows = benchRows(s);
  const zones = zonesForGenerate(s);
  const stale = genStale(s);

  // working-set census (distinct wells; a U-turn is two legs, one well)
  const gb = composeGunbarrel(s);
  const planPts = (gb?.points ?? []).filter((p) => !p.context);
  const wellsOf = (pts: typeof planPts) => new Set(pts.map((p) => p.well_name)).size;
  const planWells = wellsOf(planPts);
  const noviWells = wellsOf(planPts.filter((p) => p.category === "pud" || p.category === "res"));
  const genWells = wellsOf(planPts.filter((p) => p.category === "generated"));
  const pdpWells = new Set((gb?.points ?? [])
    .filter((p) => p.category === "pdp").map((p) => p.well_name)).size;

  const savedDeals = new Set(scenarios.map((sc) => sc.deal_id));

  return (
    <>
      <div className="section">
        <h2>Deals</h2>
        <div className="row">
          <button className="ghost" onClick={() => loadSynthetic()}>Synthetic</button>
          <button className="ghost" onClick={() => fileRef.current?.click()}>Upload .zip / .gpkg</button>
        </div>
        <input ref={fileRef} type="file" accept=".zip,.gpkg" style={{ display: "none" }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadParcels(f); }} />
        {parcels.length > 0 && (
          <div style={{ marginTop: 8, maxHeight: 180, overflowY: "auto" }}>
            {parcels.map((p) => {
              const active = parcel?.label === p.label;
              return (
                <div
                  key={p.label}
                  className="scenario-row"
                  onClick={() => { if (!active) selectParcel(p); }}
                  style={{
                    cursor: "pointer",
                    background: active ? "var(--accent-soft, #eef2ff)" : undefined,
                    borderRadius: 5, padding: "2px 4px",
                  }}
                >
                  {editingLabel === p.label ? (
                    <input
                      autoFocus
                      value={draftLabel}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => setDraftLabel(e.target.value)}
                      onBlur={() => { renameParcel(p.label, draftLabel); setEditingLabel(null); }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") e.currentTarget.blur();
                        if (e.key === "Escape") setEditingLabel(null);
                      }}
                      style={{ width: "100%" }}
                    />
                  ) : (
                    <div style={{ fontWeight: active ? 600 : 400 }}>
                      {p.label}
                      {active && (
                        <span
                          title="rename deal"
                          onClick={(e) => {
                            e.stopPropagation();
                            setEditingLabel(p.label);
                            setDraftLabel(p.label);
                          }}
                          style={{ cursor: "pointer", marginLeft: 6, color: "var(--muted)" }}
                        >
                          ✎
                        </span>
                      )}
                    </div>
                  )}
                  <div className="meta" style={{ textAlign: "right" }}>
                    {p.area_ac} ac{savedDeals.has(dealIdFor(p.label)) && " · ✓ saved"}
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {parcel && !inventory && (
          <button className="primary" style={{ marginTop: 8 }} disabled={loading}
            onClick={() => fetchInventory()}>
            {loading ? "loading inventory…" : "Load inventory"}
          </button>
        )}
        {error && <div className="error">{error}</div>}
      </div>

      {parcel && (
        <div className="section">
          <h2>Deal terms</h2>
          {hasDeclaredTerms && (
            <>
              <div
                className="note"
                title="Depth text from the land department's file, shown verbatim. It may reference a stratigraphic-equivalent depth on a log miles away — never used for math here; enter the correlated window below."
              >
                declared (land file — uncorrelated)
              </div>
              {(attr("Min_Depth") != null || attr("Max_Depth") != null) && (
                <div className="field">
                  <label>depths</label>
                  <span style={{ fontSize: 12 }}>
                    {attr("Min_Depth") ?? "—"} → {attr("Max_Depth") ?? "—"}
                  </span>
                </div>
              )}
              {(attr("DSU_WI") != null || attr("DSU_NRI") != null) && (
                <div className="field">
                  <label>DSU WI / NRI</label>
                  <span style={{ fontSize: 12 }}>
                    {attr("DSU_WI") ?? "—"} / {attr("DSU_NRI") ?? "—"}
                  </span>
                </div>
              )}
              {(parcel.tracts ?? []).map((t) => {
                const ta = (k: string) => {
                  const v = t.attributes[k];
                  return v == null || v === "" ? null : String(v);
                };
                return (
                  <div className="field" key={t.label} style={{ paddingLeft: 12 }}>
                    <label style={{ color: "var(--muted)", fontSize: 11 }}>{t.label}</label>
                    <span style={{ fontSize: 11, color: "var(--muted)" }}>
                      {[
                        ta("Tract_WI") != null ? `WI ${ta("Tract_WI")}` : null,
                        ta("Tract_NRI") != null ? `NRI ${ta("Tract_NRI")}` : null,
                        ta("Max_Depth") != null ? `→ ${ta("Max_Depth")}` : null,
                      ].filter(Boolean).join(" · ") || "—"}
                    </span>
                  </div>
                );
              })}
            </>
          )}
          <div
            className="note"
            title="The number that drives bench flagging — YOUR correlated depth, typed here, never parsed from the file. Soft: out-of-window benches grey out and seed off but stay selectable."
          >
            working window (correlated, ft TVD)
          </div>
          <div className="field">
            <label style={{ fontSize: 11 }}>min / max</label>
            <span>
              <input type="number" step={50} style={{ width: 64 }}
                value={dw?.minFt ?? ""} placeholder="surface"
                onChange={(e) => setDepthWindow({
                  minFt: e.target.value === "" ? null : Number(e.target.value) })} />
              {" – "}
              <input type="number" step={50} style={{ width: 64 }}
                value={dw?.maxFt ?? ""} placeholder="open"
                onChange={(e) => setDepthWindow({
                  maxFt: e.target.value === "" ? null : Number(e.target.value) })} />
            </span>
          </div>
          <div className="field">
            <label style={{ fontSize: 11 }}
              title="Provenance of the window — e.g. 'correlated by RG; declared 9,515 on ref log 17 mi NW → ~9,950 local'. Saves with the scenario.">
              basis
            </label>
            <input type="text" style={{ width: 150, fontSize: 11 }}
              value={dw?.basis ?? ""} placeholder="who correlated it, and from what"
              onChange={(e) => setDepthWindow({ basis: e.target.value })} />
          </div>
        </div>
      )}

      <div className="section">
        <h2>Show</h2>
        {CATS.map((c) => (
          <div className="field" key={c.key}>
            <label>{c.label}</label>
            <input type="checkbox" checked={cats[c.key]} onChange={() => toggleCat(c.key)} />
          </div>
        ))}
      </div>

      <div className="section">
        <h2>Benches</h2>
        {windowActive && (
          <div
            className="note"
            title="Benches whose median landing TVD falls outside the working window are greyed and seed to off — but stay selectable. Turning one on is the engineer override (recorded in the scenario notes)."
          >
            depth window {dw?.minFt != null ? dw.minFt.toLocaleString() : "surface"}
            {"–"}
            {dw?.maxFt != null ? `${dw.maxFt.toLocaleString()} ft` : "open"} TVD active
            — flagged benches are overridable
          </div>
        )}
        {rows.length === 0 && (
          <div className="note">pick a deal and load its inventory to see benches</div>
        )}
        {rows.map((b) => {
          const src = benchSource[b.formation] ?? "off";
          const flagged = b.depthAllowed === false;
          const ctrl = [b.n_pdp ? `${b.n_pdp} PDP` : null, b.n_pud ? `${b.n_pud} PUD` : null,
            b.n_res ? `${b.n_res} RES` : null,
            (b.n_supported != null && b.n_pud + b.n_res > 0)
              ? `${b.n_supported}/${b.n_pud + b.n_res} supp` : null,
          ].filter(Boolean).join(" · ") || "no control";
          const sp = benchSpacing[b.formation] ?? b.suggested_spacing_ft ?? params.spacing_ft;
          return (
            <div key={b.formation}
              style={{ marginBottom: 4, opacity: src === "off" ? (flagged ? 0.45 : 0.55) : 1 }}>
              <div className="field">
                <label
                  title={`${ctrl}${b.median_tvd_ft != null ? ` @ ${b.median_tvd_ft.toLocaleString()}' TVD` : ""}${
                    flagged ? " — OUTSIDE the deal depth window (soft flag; enabling is an engineer override)" : ""}`}
                >
                  <i className="swatch" style={{ background: colorForBlueox(b.formation) }} />
                  {" "}{b.formation}
                  {flagged && <span style={{ color: "#b45309" }} aria-label="outside depth window"> ⚠</span>}
                  {b.median_tvd_ft != null && (
                    <span style={{ color: "var(--muted)" }}> {Math.round(b.median_tvd_ft).toLocaleString()}'</span>
                  )}
                  <span style={{ color: "var(--muted)", fontSize: 10 }}> · {ctrl}</span>
                </label>
                <select
                  value={src}
                  onChange={(e) => setBenchSource(b.formation, e.target.value as BenchSource)}
                  style={{ width: 92 }}
                >
                  <option value="novi" disabled={!b.hasNovi}>
                    {b.hasNovi ? `Novi (${b.n_pud + b.n_res})` : "Novi (—)"}
                  </option>
                  <option value="generate">generate</option>
                  <option value="off">off</option>
                </select>
              </div>
              {src === "generate" && (
                <>
                  <div className="field" style={{ paddingLeft: 12 }}>
                    <label style={{ color: "var(--muted)", fontSize: 11 }}
                      title="leg-to-leg for this bench; Novi develops Bone Spring wider than Wolfcamp">
                      spacing (ft)
                    </label>
                    <input type="number" step={10} style={{ width: 80 }}
                      value={Number.isFinite(sp) ? sp : 0}
                      onChange={(e) => setBenchSpacing(b.formation, Number(e.target.value))} />
                  </div>
                  <div className="field" style={{ paddingLeft: 12 }}>
                    <label
                      style={{ color: benchTvd[b.formation] != null ? "var(--accent)" : "var(--muted)", fontSize: 11 }}
                      title="hard TVD for generated locations in this bench (e.g. your geologist's pick) — empty uses the warehouse median; resets on parcel change"
                    >
                      TVD (ft){benchTvd[b.formation] != null ? " · override" : " · warehouse"}
                      {benchTvd[b.formation] != null && (
                        <>
                          {" "}
                          <span
                            onClick={() => setBenchTvd(b.formation, null)}
                            style={{ cursor: "pointer", textDecoration: "underline" }}
                            title="clear the override (back to warehouse median)"
                          >
                            reset
                          </span>
                        </>
                      )}
                    </label>
                    <input type="number" step={50} style={{ width: 80 }}
                      value={benchTvd[b.formation] ?? ""}
                      placeholder={b.median_tvd_ft != null ? String(Math.round(b.median_tvd_ft)) : "—"}
                      onChange={(e) => setBenchTvd(b.formation,
                        e.target.value === "" ? null : Number(e.target.value))} />
                  </div>
                </>
              )}
            </div>
          );
        })}
        {inventory && (
          <div className="summary">
            <div>
              <b>{planWells}</b> wells in plan
              {planWells > 0 && <> · {noviWells} Novi + {genWells} generated</>}
              {pdpWells > 0 && <span className="note" style={{ marginTop: 0 }}> · {pdpWells} PDP ref</span>}
            </div>
            {culledWells.length > 0 && (
              <div className="note">{culledWells.length} culled</div>
            )}
          </div>
        )}
      </div>

      {planPts.length > 0 && (() => {
        // Workbook-handoff categories: one row per PLANNED well (dedupe legs),
        // grouped by bench in TVD order. Auto = server scoring (pdp_count_3mi
        // >= 3 -> PUD); clicking the chip flips PUD/UPSIDE (an override, same
        // estimate-then-override pattern as the bench TVD field). PDP wells are
        // existing producers — counted, never editable.
        type HW = { name: string; auto: "PUD" | "UPSIDE"; eff: "PUD" | "UPSIDE";
                    overridden: boolean; n3: number | null };
        const seen = new Set<string>();
        const byBench = new Map<string, HW[]>();
        const pdpByBench = new Map<string, number>();
        for (const p of gb?.points ?? []) {
          if (seen.has(p.well_name)) continue;
          seen.add(p.well_name);
          if (p.category === "pdp") {
            if (!p.context || cats.pdp) {
              pdpByBench.set(p.formation, (pdpByBench.get(p.formation) ?? 0) + 1);
            }
            continue;
          }
          if (p.context) continue;
          const auto: "PUD" | "UPSIDE" = p.handoff_category === "PUD" ? "PUD" : "UPSIDE";
          const eff = categoryOverrides[p.well_name] ?? auto;
          const list = byBench.get(p.formation) ?? [];
          list.push({ name: p.well_name, auto, eff,
                      overridden: categoryOverrides[p.well_name] != null,
                      n3: p.pdp_count_3mi ?? null });
          byBench.set(p.formation, list);
        }
        const order = [
          ...rows.map((r) => r.formation).filter((f) => byBench.has(f)),
          ...[...byBench.keys()].filter((f) => !rows.some((r) => r.formation === f)),
        ];
        const chip = (w: HW) => (
          <button
            onClick={() => toggleCategoryOverride(w.name, w.auto)}
            title={`auto: ${w.auto}${w.n3 != null ? ` (${w.n3} PDP offsets @3mi)` : " (unscored)"} — click to flip`}
            style={{
              width: 64, fontSize: 10, fontWeight: 600, cursor: "pointer",
              border: `1px solid ${w.eff === "PUD" ? "#16a34a" : "#d97706"}`,
              color: w.eff === "PUD" ? "#166534" : "#92400e",
              background: w.eff === "PUD" ? "#f0fdf4" : "#fffbeb",
              borderRadius: 4, padding: "1px 0",
            }}
          >
            {w.eff}{w.overridden ? " *" : ""}
          </button>
        );
        return (
          <div className="section">
            <h2>Handoff</h2>
            <div className="note" style={{ marginTop: 0 }}>
              workbook categories — PUD = ≥3 PDP offsets @3mi, UPSIDE = thin/unscored;
              click a chip to flip (* = your override)
            </div>
            {order.map((f) => {
              const wells = byBench.get(f) ?? [];
              const nPud = wells.filter((w) => w.eff === "PUD").length;
              const nUp = wells.length - nPud;
              const nPdp = pdpByBench.get(f) ?? 0;
              return (
                <details key={f} style={{ marginBottom: 4 }}>
                  <summary style={{ cursor: "pointer", fontSize: 12, listStylePosition: "inside" }}>
                    <i className="swatch" style={{ background: colorForBlueox(f) }} />
                    {" "}{f}
                    <span style={{ color: "var(--muted)", fontSize: 10 }}>
                      {" "}· {nPud} PUD · {nUp} UPSIDE{nPdp > 0 ? ` · ${nPdp} PDP` : ""}
                    </span>
                  </summary>
                  {wells.map((w) => (
                    <div className="field" key={w.name} style={{ paddingLeft: 16 }}>
                      <label style={{ fontSize: 11 }}>
                        {w.name}
                        <span style={{ color: "var(--muted)", fontSize: 10 }}>
                          {w.n3 != null ? ` · ${w.n3} @3mi` : " · unscored"}
                        </span>
                      </label>
                      {chip(w)}
                    </div>
                  ))}
                </details>
              );
            })}
          </div>
        );
      })()}

      {inventory && (
        <div className="section">
          <h2>Generator</h2>
          {feasibility && feasibility.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              {feasibility.map((d) => {
                const tight = d.note.includes("min lateral");
                return (
                  <div key={d.label} className="note"
                    style={{ marginTop: 0, color: tight ? "#b45309" : undefined }}
                    title={d.note}>
                    {d.label} {d.azimuth_deg.toFixed(1)}° — rows ≤ {Math.round(d.max_lateral_ft).toLocaleString()}′,
                    {" "}{Math.round(d.cross_extent_ft).toLocaleString()}′ across{tight ? " · under min lateral" : ""}
                  </div>
                );
              })}
            </div>
          )}
          <button className="ghost" disabled={scanning} onClick={() => runScan()}
            title="sweep azimuth x well type x spacing through the placement engine and rank by completed footage">
            {scanning ? "scanning…" : "Scan configurations"}
          </button>
          {scan && (
            <div style={{ margin: "6px 0" }}>
              {scan.length === 0 && (
                <div className="note">no configuration places a well — relax min lateral or setbacks</div>
              )}
              {scan.slice(0, 6).map((c, i) => (
                <div key={i} className="field" title={c.note} style={{ fontSize: 11 }}>
                  <label style={{ fontSize: 11 }}>
                    {c.azimuth_label} {c.azimuth_deg.toFixed(0)}° · {c.well_type === "uturn" ? "U-turn" : "single"} @ {c.spacing_ft.toFixed(0)}′
                    <span style={{ color: "var(--muted)" }}>
                      {" "}· {c.wells}w · {Math.round(c.completed_ft / 1000)}k′ ({Math.round(c.ft_per_well).toLocaleString()}′/w)
                    </span>
                  </label>
                  <button className="ghost" style={{ padding: "0 8px" }}
                    onClick={() => adoptConfig(c)}
                    title="adopt: sets azimuth override, well type, and spacing (incl. generate benches)">
                    use
                  </button>
                </div>
              ))}
            </div>
          )}
          {zones.length === 0 && (
            <div className="note">set a bench to “generate” to design wells</div>
          )}
          <NumberField
            label="default spacing (ft)" k="spacing_ft" step={10}
            title={"fallback only: seeds a bench's spacing when it has no suggested or per-bench value "
              + "(each generate bench's own spacing is what places its wells and gates its "
              + "U-turn leg-to-leg floor)."}
          />
          <NumberField
            label="setback N/S (ft)" k="setback_ns_ft" step={10}
            title="setback on the N/S boundaries (the toe/heel ends for ~N-S development)"
          />
          <NumberField
            label="setback E/W (ft)" k="setback_ew_ft" step={10}
            title="setback on the E/W boundaries (the lateral-side section lines); 330 ft is the legal default"
          />
          <NumberField label="min lateral (ft)" k="min_lateral_ft" step={100} />
          <div className="field">
            <label>well type</label>
            <select value={params.well_type} onChange={(e) => setParam("well_type", e.target.value as Params["well_type"])}>
              <option value="single">single</option>
              <option value="uturn">U-turn</option>
            </select>
          </div>
          <div className="field">
            <label>objective</label>
            <select value={params.objective} onChange={(e) => setParam("objective", e.target.value as Params["objective"])}>
              <option value="max_lateral">max lateral</option>
              <option value="max_count">max count</option>
            </select>
          </div>
          <div className="field">
            <label title={"where the row pattern hangs across the unit. West/east LINE anchors derive "
              + "the azimuth from that lease line, so they're disabled while an azimuth override is set "
              + "(auto still tries edge-hung patterns at the overridden bearing)."}>anchor</label>
            <select value={params.anchor} onChange={(e) => setParam("anchor", e.target.value as Params["anchor"])}>
              <option value="auto">auto (max footage)</option>
              <option value="west" disabled={params.azimuth_deg != null}>west line</option>
              <option value="east" disabled={params.azimuth_deg != null}>east line</option>
              <option value="center">center</option>
            </select>
          </div>
          {params.well_type === "uturn" && (
            <>
              <div className="field">
                <label title="which side the pads/heels go; the U-turn sits at the opposite end">drill from</label>
                <select value={params.drill_from} onChange={(e) => setParam("drill_from", e.target.value as Params["drill_from"])}>
                  <option value="auto">auto (max footage)</option>
                  <option value="north">north</option>
                  <option value="south">south</option>
                </select>
              </div>
              <NumberField
                label="U-turn floor (ft)" k="uturn_min_leg_to_leg_ft" step={10}
                title={"tightest drillable turn: leg-to-leg spacing = turn diameter (radius = half). "
                  + "Pairs spaced under this fall back to singles — lower it to U-turn tighter rows."}
              />
            </>
          )}
          {(params.anchor === "west" || params.anchor === "east") ? (
            <div className="field">
              <label title={`azimuth comes from the ${params.anchor} lease line — laterals run parallel to the setback`}
                style={{ color: "var(--muted)" }}>
                grid azimuth (from {params.anchor} line)
              </label>
              <input type="checkbox" checked disabled />
            </div>
          ) : (
            <>
              <div className="field">
                <label title="adopt the offset-well grid azimuth sourced from the warehouse (ignored while an override is set below)"
                  style={params.azimuth_deg != null ? { color: "var(--muted)" } : undefined}>
                  grid azimuth (auto)
                </label>
                <input type="checkbox" checked={sourceAzimuth} disabled={params.azimuth_deg != null}
                  onChange={(e) => setSourceAzimuth(e.target.checked)} />
              </div>
              <div className="field">
                <label
                  title="hard bearing for the laterals, 0-180 deg (0 = N-S, 90 = E-W) — e.g. run down the long axis of a half-section instead of the offset grid; empty = auto"
                  style={{ color: params.azimuth_deg != null ? "var(--accent)" : undefined }}
                >
                  azimuth (deg){params.azimuth_deg != null ? " · override" : " · auto"}
                  {params.azimuth_deg != null && (
                    <>
                      {" "}
                      <span
                        onClick={() => setParam("azimuth_deg", null)}
                        style={{ cursor: "pointer", textDecoration: "underline" }}
                        title="clear the override (back to the sourced grid azimuth / long axis)"
                      >
                        reset
                      </span>
                    </>
                  )}
                </label>
                <input type="number" step={0.1} min={0} max={180} style={{ width: 80 }}
                  value={params.azimuth_deg ?? ""}
                  placeholder="auto"
                  onChange={(e) => setParam("azimuth_deg",
                    e.target.value === "" ? null : Number(e.target.value))} />
              </div>
            </>
          )}
          <button className="primary" disabled={loading || zones.length === 0} onClick={() => generate()}>
            {loading ? "working…" : stale && result ? "Re-generate" : "Generate"}
          </button>
          {stale && result && (
            <div className="note" style={{ color: "#b45309" }}>
              parameters changed — regenerate to update the plan
            </div>
          )}
          {result && result.mode !== "loaded" && (
            <div className="summary">
              <div><b>{result.placed_wells}</b> wells / {result.placed_legs} legs
                {result.azimuth_deg != null && <> · az {result.azimuth_deg.toFixed(1)}°</>}</div>
              <div className="note">{result.summary}</div>
              {result.warehouse_notes.length > 0 && (
                <div className="note">{result.warehouse_notes.join("\n")}</div>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}
