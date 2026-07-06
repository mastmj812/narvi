import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GunbarrelData } from "../api/client";
import { colorForBlueox } from "../map/formations";
import { composeGunbarrel, useStore } from "../store";

const M = { l: 46, r: 12, t: 10, b: 22 };

type Pt = GunbarrelData["points"][number];

// Existing (PDP) = solid circle; planned (PUD + generated) = hollow (white)
// circle; RES = hollow triangle; color = formation_blueox (erebor convention).
// Click culls the well: culled wells disappear everywhere (chart, map, counts)
// and the TVD axis rescales without them. Restore: PDP via its stick on the
// basin-wide map layer; anything via "restore all" in the scenario bar.
// PDP are existing wells shown for spacing reference — they render solid + full
// opacity in both modes (in override they merge in as reference but stay out of
// the planned well/leg count). Only a genuinely non-PDP offset point renders
// small + faded (reserved for a future offset-context source).
function Marker({ p, cx, cy, color, on, onToggle }: {
  p: Pt; cx: number; cy: number; color: string;
  on: (p: Pt | null, e?: React.MouseEvent) => void;
  onToggle: (p: Pt) => void;
}) {
  const faded = p.context && p.category !== "pdp";
  const r = faded ? 3 : 4;
  const hollow = p.category === "pud" || p.category === "res" || p.category === "generated";
  const paint = {
    fill: hollow ? "#ffffff" : color,
    stroke: hollow ? color : "#3f3f46",
    strokeWidth: hollow ? 1.5 : 0.7,
    opacity: faded ? 0.35 : p.category === "res" ? 0.85 : 1,
  };
  const h = {
    onMouseEnter: (e: React.MouseEvent) => on(p, e),
    onMouseMove: (e: React.MouseEvent) => on(p, e),
    onMouseLeave: () => on(null),
    onClick: () => onToggle(p),
    style: { cursor: "pointer" as const },
  };
  const shape = p.category === "res"
    ? <polygon points={`${cx},${cy - r} ${cx - r},${cy + r} ${cx + r},${cy + r}`} {...paint} {...h} />
    : <circle cx={cx} cy={cy} r={r} {...paint} {...h} />;
  return (
    <g>
      <circle cx={cx} cy={cy} r={r + 4} fill="transparent" {...h} />
      {shape}
    </g>
  );
}

function Tooltip({ p, x, y }: { p: Pt; x: number; y: number }) {
  const flipX = x > window.innerWidth - 230;
  const flipY = y > window.innerHeight - 160;
  const style: React.CSSProperties = {
    ...(flipX ? { right: window.innerWidth - x + 14 } : { left: x + 14 }),
    ...(flipY ? { bottom: window.innerHeight - y + 14 } : { top: y + 14 }),
  };
  const row = (k: string, v: string) => (
    <tr><td style={{ color: "#9ca3af", paddingRight: 8 }}>{k}</td><td>{v}</td></tr>
  );
  return (
    <div className="gb-tip" style={style}>
      <div style={{ fontWeight: 600, marginBottom: 3 }}>{p.novi_wellname ?? p.well_name}</div>
      <table style={{ fontSize: 11, borderCollapse: "collapse" }}>
        <tbody>
          {row("Category", p.category.toUpperCase())}
          {p.context && p.category !== "pdp" ? row("Role", "offset context") : null}
          {row("Bench", p.formation)}
          {p.recon_status ? row("Status", p.recon_status.replace(/_/g, " ")) : null}
          {row("TVD", `${Math.round(p.tvd_ft).toLocaleString()} ft`)}
          {row("Offset", `${Math.round(p.offset_ft).toLocaleString()} ft`)}
        </tbody>
      </table>
    </div>
  );
}

export function GunBarrel() {
  const inventory = useStore((s) => s.inventory);
  const result = useStore((s) => s.result);
  const benchSource = useStore((s) => s.benchSource);
  const cats = useStore((s) => s.cats);
  const culledWells = useStore((s) => s.culledWells);
  const toggleCull = useStore((s) => s.toggleCull);
  const gbFlip = useStore((s) => s.gbFlip);
  const toggleGbFlip = useStore((s) => s.toggleGbFlip);
  const culledSet = useMemo(() => new Set(culledWells), [culledWells]);

  // One composed working set (store.composeGunbarrel): Novi-sourced benches from
  // the inventory + generate-sourced benches from the result + PDP reference.
  // The legend is ALWAYS rebuilt from the shared formation_blueox palette so
  // swatches match the markers (the backend's palette is ignored here).
  const gb = useMemo<GunbarrelData | null>(() => {
    const raw = composeGunbarrel({ inventory, result, benchSource, cats, culledWells });
    if (!raw) return null;
    const { points, links } = raw;
    const forms = [...new Set(points.map((p) => p.formation))]
      .sort((a, b) =>
        points.find((p) => p.formation === a)!.tvd_ft - points.find((p) => p.formation === b)!.tvd_ft)
      .map((formation) => ({ formation, color: colorForBlueox(formation) }));
    return { formations: forms, points, links, azimuth_deg: raw.azimuth_deg ?? null };
  }, [inventory, result, benchSource, cats, culledWells]);

  // count of PDP wells hidden from the chart (both modes source PDP from inventory)
  const hiddenPdp = useMemo(() => new Set(
    (inventory?.gunbarrel?.points ?? [])
      .filter((p) => p.category === "pdp" && culledSet.has(p.well_name))
      .map((p) => p.well_name)).size, [inventory, culledSet]);

  const [pos, setPos] = useState(() => ({
    x: Math.max(20, window.innerWidth - 460), y: Math.max(60, window.innerHeight - 320),
  }));
  const [dragging, setDragging] = useState(false);
  const off = useRef({ dx: 0, dy: 0 });
  const [bodyRef, size] = useElementSize();
  const [hover, setHover] = useState<{ p: Pt; x: number; y: number } | null>(null);
  const onHover = useCallback((p: Pt | null, e?: React.MouseEvent) =>
    setHover(p && e ? { p, x: e.clientX, y: e.clientY } : null), []);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => setPos({ x: e.clientX - off.current.dx, y: e.clientY - off.current.dy });
    const onUp = () => setDragging(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, [dragging]);

  if (!gb || gb.points.length === 0) return null;

  const onHeadDown = (e: React.MouseEvent) => {
    off.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y };
    setDragging(true);
    e.preventDefault();
  };

  const W = size.width, H = size.height;
  // flip mirrors the x-axis (scale on the signed values so min/max track the flip)
  const sgn = gbFlip ? -1 : 1;
  const xs = gb.points.map((p) => sgn * p.offset_ft), ys = gb.points.map((p) => p.tvd_ft);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const spanX = maxX - minX || 1, spanY = maxY - minY || 1;
  const sx = (x: number) => M.l + (((sgn * x - minX) / spanX) * 0.9 + 0.05) * (W - M.l - M.r);
  const sy = (y: number) => M.t + (((y - minY) / spanY) * 0.9 + 0.05) * (H - M.t - M.b);

  // compass direction of +offset: 90° clockwise of the folded azimuth (the
  // canonical cross_axis); the flip swaps which end is which.
  const WINDS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  const az = gb.azimuth_deg;
  const plusDir = az != null ? WINDS[Math.round((((az % 180) + 90) % 360) / 45) % 8] : null;
  const minusDir = az != null ? WINDS[(Math.round((((az % 180) + 90) % 360) / 45) + 4) % 8] : null;
  const rightLabel = gbFlip ? minusDir : plusDir;
  const leftLabel = gbFlip ? plusDir : minusDir;

  // header counts reflect the PLAN (culled wells are already gone; PDP carry
  // context=true so they're reference, shown separately)
  const keptPts = gb.points.filter((p) => !p.context);
  const keptLinks = gb.links;
  const pdpCount = new Set(
    gb.points.filter((p) => p.category === "pdp").map((p) => p.well_name)).size;
  const hasFaded = gb.points.some((p) => p.context && p.category !== "pdp");

  return (
    <div className="floatwin gb-win" style={{ left: pos.x, top: pos.y }}>
      <div className="win-head" onMouseDown={onHeadDown}>
        <span className="win-title">⠿ Gun-barrel — offset vs TVD</span>
        <span style={{ fontSize: 11, color: "#71717a" }}>
          {keptPts.length - keptLinks.length} wells / {keptPts.length} legs
          {pdpCount > 0 && <span style={{ color: "#a1a1aa" }}> · {pdpCount} PDP</span>}
          {culledSet.size > 0 && <span style={{ color: "#a1a1aa" }}> · {culledSet.size} culled</span>}
        </span>
        <button
          title="flip orientation (mirror the x-axis)"
          onMouseDown={(e) => e.stopPropagation()}
          onClick={toggleGbFlip}
          style={{ marginLeft: "auto", border: "1px solid var(--line, #e5e7eb)", borderRadius: 4,
            background: gbFlip ? "#eef2ff" : "#fff", cursor: "pointer", fontSize: 12,
            lineHeight: "16px", padding: "0 6px" }}
        >
          ⇋
        </button>
      </div>
      <div className="win-body" ref={bodyRef}>
        <svg width={W} height={H} style={{ display: "block" }}>
          <line x1={M.l} y1={H - M.b} x2={W - M.r} y2={H - M.b} stroke="#e5e7eb" />
          <line x1={M.l} y1={M.t} x2={M.l} y2={H - M.b} stroke="#e5e7eb" />
          {minX <= 0 && maxX >= 0 && (
            <line x1={sx(0)} y1={M.t} x2={sx(0)} y2={H - M.b} stroke="#eee" strokeDasharray="2 2" />
          )}
          {gb.links.map((l, i) => (
            <line key={`l${i}`} x1={sx(l.offset_a_ft)} y1={sy(l.tvd_ft)} x2={sx(l.offset_b_ft)} y2={sy(l.tvd_ft)}
              stroke={colorForBlueox(l.formation)} strokeWidth={1} opacity={0.5} />
          ))}
          {gb.points.map((p, i) => (
            <Marker key={`p${i}`} p={p} cx={sx(p.offset_ft)} cy={sy(p.tvd_ft)}
              color={colorForBlueox(p.formation)}
              on={onHover} onToggle={(pt) => toggleCull(pt.well_name)} />
          ))}
          <text x={M.l - 5} y={M.t + 6} textAnchor="end" fontSize={9} fill="#71717a">{minY.toFixed(0)}</text>
          <text x={M.l - 5} y={H - M.b} textAnchor="end" fontSize={9} fill="#71717a">{maxY.toFixed(0)}</text>
          <text x={W / 2} y={H - 6} textAnchor="middle" fontSize={9} fill="#52525b">offset (ft)</text>
          {leftLabel && (
            <text x={M.l + 4} y={H - 6} textAnchor="start" fontSize={9} fill="#52525b">← {leftLabel}</text>
          )}
          {rightLabel && (
            <text x={W - M.r - 4} y={H - 6} textAnchor="end" fontSize={9} fill="#52525b">{rightLabel} →</text>
          )}
        </svg>
      </div>
      <div className="gb-foot">
        <span>● PDP</span><span>○ planned (PUD / gen)</span><span>△ RES</span><span>· color = bench</span>
        {hasFaded && <span style={{ color: "#a1a1aa" }}>· faded = offset context</span>}
        {hiddenPdp > 0 && (
          <span style={{ color: "#a1a1aa" }}>· {hiddenPdp} PDP hidden — click its stick on the map to restore</span>
        )}
        {gb.formations.map((f) => (
          <span key={f.formation}><i className="swatch" style={{ background: f.color }} />{f.formation}</span>
        ))}
      </div>
      {hover && <Tooltip p={hover.p} x={hover.x} y={hover.y} />}
    </div>
  );
}

function useElementSize() {
  const [size, setSize] = useState({ width: 400, height: 220 });
  const roRef = useRef<ResizeObserver | null>(null);
  const ref = useCallback((node: HTMLDivElement | null) => {
    roRef.current?.disconnect();
    if (!node) return;
    const ro = new ResizeObserver((e) => {
      const cr = e[0].contentRect;
      setSize({ width: cr.width, height: cr.height });
    });
    ro.observe(node);
    roRef.current = ro;
  }, []);
  return [ref, size] as const;
}
