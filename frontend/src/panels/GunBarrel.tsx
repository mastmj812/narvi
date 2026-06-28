import { useStore } from "../store";

const W = 344, H = 180, PAD = 28;

// Cross-section: offset_ft on x, TVD on y (deeper = lower). Pure SVG so there's
// no chart dependency; colors come straight from the backend gun-barrel data.
export function GunBarrel() {
  const gb = useStore((s) => s.result?.gunbarrel);
  if (!gb || gb.points.length === 0) return null;

  const xs = gb.points.map((p) => p.offset_ft);
  const ys = gb.points.map((p) => p.tvd_ft);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const sx = (x: number) => PAD + ((x - minX) / spanX) * (W - 2 * PAD);
  const sy = (y: number) => PAD + ((y - minY) / spanY) * (H - 2 * PAD); // deeper -> larger y -> lower

  return (
    <div className="gunbarrel">
      <h3>Gun-barrel (offset vs TVD)</h3>
      <svg width={W} height={H} style={{ display: "block" }}>
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#e5e7eb" />
        <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="#e5e7eb" />
        {gb.links.map((l, i) => (
          <line
            key={`l${i}`} x1={sx(l.offset_a_ft)} y1={sy(l.tvd_ft)}
            x2={sx(l.offset_b_ft)} y2={sy(l.tvd_ft)} stroke={l.color} strokeWidth={1} opacity={0.5}
          />
        ))}
        {gb.points.map((p, i) => (
          <circle key={`p${i}`} cx={sx(p.offset_ft)} cy={sy(p.tvd_ft)} r={3.2} fill={p.color} />
        ))}
        <text x={PAD} y={H - 8} fontSize={9} fill="#6b7280">{minX.toFixed(0)} ft</text>
        <text x={W - PAD} y={H - 8} fontSize={9} fill="#6b7280" textAnchor="end">{maxX.toFixed(0)} ft</text>
        <text x={4} y={PAD + 4} fontSize={9} fill="#6b7280">{minY.toFixed(0)}</text>
        <text x={4} y={H - PAD} fontSize={9} fill="#6b7280">{maxY.toFixed(0)}</text>
      </svg>
      <div className="legend">
        {gb.formations.map((f) => (
          <span key={f.formation}>
            <i className="swatch" style={{ background: f.color }} />{f.formation}
          </span>
        ))}
      </div>
    </div>
  );
}
