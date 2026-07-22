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
    selectParcel, renameParcel, loadSynthetic, uploadParcels, fetchInventory, setBenchSource,
    toggleCat, setParam, setSourceAzimuth, setBenchSpacing, setBenchTvd, generate,
  } = s;

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
          <button className="ghost" onClick={() => fileRef.current?.click()}>Upload .zip</button>
        </div>
        <input ref={fileRef} type="file" accept=".zip" style={{ display: "none" }}
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
        {rows.length === 0 && (
          <div className="note">pick a deal and load its inventory to see benches</div>
        )}
        {rows.map((b) => {
          const src = benchSource[b.formation] ?? "off";
          const ctrl = [b.n_pdp ? `${b.n_pdp} PDP` : null, b.n_pud ? `${b.n_pud} PUD` : null,
            b.n_res ? `${b.n_res} RES` : null,
            (b.n_supported != null && b.n_pud + b.n_res > 0)
              ? `${b.n_supported}/${b.n_pud + b.n_res} supp` : null,
          ].filter(Boolean).join(" · ") || "no control";
          const sp = benchSpacing[b.formation] ?? b.suggested_spacing_ft ?? params.spacing_ft;
          return (
            <div key={b.formation} style={{ marginBottom: 4, opacity: src === "off" ? 0.55 : 1 }}>
              <div className="field">
                <label title={`${ctrl}${b.median_tvd_ft != null ? ` @ ${b.median_tvd_ft.toLocaleString()}' TVD` : ""}`}>
                  <i className="swatch" style={{ background: colorForBlueox(b.formation) }} />
                  {" "}{b.formation}
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

      {inventory && (
        <div className="section">
          <h2>Generator</h2>
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
            <label title="where the row pattern hangs across the unit">anchor</label>
            <select value={params.anchor} onChange={(e) => setParam("anchor", e.target.value as Params["anchor"])}>
              <option value="auto">auto (max footage)</option>
              <option value="west">west line</option>
              <option value="east">east line</option>
              <option value="center">center</option>
            </select>
          </div>
          {params.well_type === "uturn" && (
            <div className="field">
              <label title="which side the pads/heels go; the U-turn sits at the opposite end">drill from</label>
              <select value={params.drill_from} onChange={(e) => setParam("drill_from", e.target.value as Params["drill_from"])}>
                <option value="auto">auto (max footage)</option>
                <option value="north">north</option>
                <option value="south">south</option>
              </select>
            </div>
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
