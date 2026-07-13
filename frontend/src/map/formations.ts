// formation_blueox color palette — mirrored from erebor/anduin so a bench is the
// same color across the suite. One source of truth for the map paint expression,
// the gun-barrel, and the bench legend. narvi is Delaware-first; Midland codes are
// included for completeness (shared codes keep one color across basins).
import type { ExpressionSpecification } from "maplibre-gl";

export const OTHER_COLOR = "#9ca3af";

const SHARED: Record<string, string> = {
  WCA_1: "#f97316", WCB_1: "#22c55e", WCB_2: "#ec4899", WCC: "#8b5cf6",
  WCD: "#0ea5e9", STRN: "#78716c", BRNT: "#2563eb", MISS: "#dc2626",
  WDFD: "#4d7c0f", OTHER: OTHER_COLOR,
};

const DELAWARE: Record<string, string> = {
  ...SHARED,
  AVA_0: "#06b6d4", AVA_1: "#f43f5e", AVA_2: "#84cc16",
  BS1_S: "#eab308", BS2_C: "#a855f7", BS2_S: "#14b8a6",
  BS3_C: "#fb923c", BS3_S: "#d946ef", WCXY: "#65a30d", WCA_2: "#e11d48",
};

const MIDLAND: Record<string, string> = {
  ...SHARED,
  US: "#06b6d4", MS: "#f43f5e", JM: "#a855f7",
  LSSH: "#eab308", DEAN: "#14b8a6", MRMC: "#d946ef",
};

// merged lookup (Delaware preferred; shared codes identical either way)
const MERGED: Record<string, string> = { ...MIDLAND, ...DELAWARE };

export function colorForBlueox(code: string | null | undefined): string {
  if (!code) return OTHER_COLOR;
  return MERGED[code] ?? OTHER_COLOR;
}

// Offset-PDP support ramp (curated.intel_pdp_support, sql/30) — the SVG/JS twin of
// SUPPORT_COLOR in scenarioLayers.ts, for the gun-barrel. null (generated /
// unscorable) -> gray, then 0=red / 1-2=orange / 3-7=amber / 8+=green.
export function colorForSupport(count: number | null | undefined): string {
  if (count == null) return OTHER_COLOR;
  if (count === 0) return "#dc2626";
  if (count <= 2) return "#f97316";
  if (count <= 7) return "#f59e0b";
  return "#16a34a";
}
export const SUPPORT_LEGEND: { label: string; color: string }[] = [
  { label: "0", color: "#dc2626" },
  { label: "1-2", color: "#f97316" },
  { label: "3-7", color: "#f59e0b" },
  { label: "8+", color: "#16a34a" },
  { label: "n/a", color: OTHER_COLOR },
];

// MapLibre `match` on a formation_blueox property -> color. Scenario legs carry
// the code as `formation`; the PDP tile layer carries it as `formation_blueox`.
export function blueoxColorExpression(property = "formation"): ExpressionSpecification {
  const pairs: unknown[] = [];
  for (const [code, color] of Object.entries(MERGED)) pairs.push(code, color);
  return ["match", ["get", property], ...pairs, OTHER_COLOR] as unknown as ExpressionSpecification;
}
