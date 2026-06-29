import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GunbarrelData } from "../api/client";
import { colorForBlueox } from "../map/formations";
import { catActive, useStore } from "../store";

const M = { l: 46, r: 12, t: 10, b: 22 };

// Marker convention mirrors erebor: PDP = solid circle, PUD = hollow (white) circle,
// RES = hollow triangle. Color = formation_blueox.
function Marker({ cat, cx, cy, color }: { cat: string; cx: number; cy: number; color: string }) {
  const r = 4;
  const hollow = cat === "pud" || cat === "res";
  const paint = {
    fill: hollow ? "#ffffff" : color,
    stroke: hollow ? color : "#3f3f46",
    strokeWidth: hollow ? 1.5 : 0.7,
    opacity: cat === "res" ? 0.85 : 1,
  };
  if (cat === "res")
    return <polygon points={`${cx},${cy - r} ${cx - r},${cy + r} ${cx + r},${cy + r}`} {...paint} />;
  return <circle cx={cx} cy={cy} r={r} {...paint} />;
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

export function GunBarrel() {
  const appMode = useStore((s) => s.appMode);
  const inventory = useStore((s) => s.inventory);
  const result = useStore((s) => s.result);
  const keptBenches = useStore((s) => s.keptBenches);
  const cats = useStore((s) => s.cats);

  const gb = useMemo<GunbarrelData | null>(() => {
    const raw = appMode === "override" ? result?.gunbarrel : inventory?.gunbarrel;
    if (!raw) return null;
    if (appMode === "override") return raw;
    const keptSet = new Set(keptBenches);
    const keep = (formation: string, category: string) =>
      keptSet.has(formation) && catActive(cats, category);
    const points = raw.points.filter((p) => keep(p.formation, p.category));
    const links = raw.links.filter((l) => keptSet.has(l.formation));
    const forms = [...new Set(points.map((p) => p.formation))]
      .sort((a, b) =>
        points.find((p) => p.formation === a)!.tvd_ft - points.find((p) => p.formation === b)!.tvd_ft)
      .map((formation) => ({ formation, color: colorForBlueox(formation) }));
    return { formations: forms, points, links };
  }, [appMode, inventory, result, keptBenches, cats]);

  const [pos, setPos] = useState(() => ({
    x: Math.max(20, window.innerWidth - 460), y: Math.max(60, window.innerHeight - 320),
  }));
  const [dragging, setDragging] = useState(false);
  const off = useRef({ dx: 0, dy: 0 });
  const [bodyRef, size] = useElementSize();

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
  const xs = gb.points.map((p) => p.offset_ft), ys = gb.points.map((p) => p.tvd_ft);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const spanX = maxX - minX || 1, spanY = maxY - minY || 1;
  const sx = (x: number) => M.l + (((x - minX) / spanX) * 0.9 + 0.05) * (W - M.l - M.r);
  const sy = (y: number) => M.t + (((y - minY) / spanY) * 0.9 + 0.05) * (H - M.t - M.b);

  return (
    <div className="floatwin gb-win" style={{ left: pos.x, top: pos.y }}>
      <div className="win-head" onMouseDown={onHeadDown}>
        <span className="win-title">⠿ Gun-barrel — offset vs TVD</span>
        <span style={{ fontSize: 11, color: "#71717a" }}>{gb.points.length} wells</span>
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
            <Marker key={`p${i}`} cat={p.category} cx={sx(p.offset_ft)} cy={sy(p.tvd_ft)}
              color={colorForBlueox(p.formation)} />
          ))}
          <text x={M.l - 5} y={M.t + 6} textAnchor="end" fontSize={9} fill="#71717a">{minY.toFixed(0)}</text>
          <text x={M.l - 5} y={H - M.b} textAnchor="end" fontSize={9} fill="#71717a">{maxY.toFixed(0)}</text>
          <text x={W / 2} y={H - 6} textAnchor="middle" fontSize={9} fill="#52525b">offset (ft)</text>
        </svg>
      </div>
      <div className="gb-foot">
        <span>● PDP</span><span>○ PUD</span><span>△ RES</span><span>· color = bench</span>
        {gb.formations.map((f) => (
          <span key={f.formation}><i className="swatch" style={{ background: f.color }} />{f.formation}</span>
        ))}
      </div>
    </div>
  );
}
