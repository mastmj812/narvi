// Texas/NM survey-grid overlays — Blocks (Texas block grid) + Sections
// (abstract/section grid). Ported from anduin (permian_type_curve) so the grid
// reads the same across the suite; the GeoJSON is served by narvi's backend from
// anduin's vendored infra/basemap assets. Fill + line + symbol-label per grid,
// zoom-gated (the BLM cadastral grid is too dense to label before then).
//
// GOTCHA (verified headlessly 2026-07-03): layer `minzoom` on these GeoJSON
// sources renders NOTHING in this maplibre 4.7 setup (minzoom <=6 works, >=8
// silently draws zero features even at z12; setLayerZoomRange and zoom-filters
// share the broken path). The zoom gates are therefore expressed as step()
// expressions instead: opacity 0 below the gate for fill/line, and an empty
// text-field below the gate for labels (empty text skips symbol placement, so
// the 50k-feature sections grid doesn't pay collision cost basin-wide).
import type {
  DataDrivenPropertyValueSpecification,
  ExpressionSpecification,
  FillLayerSpecification,
  LineLayerSpecification,
  SymbolLayerSpecification,
} from "maplibre-gl";

export const BLOCKS_SOURCE = "blocks";
export const BLOCKS_URL = "/api/basemap/blocks_tx_nm.geojson";
export const BLOCKS_MIN_ZOOM = 8;

export const SECTIONS_SOURCE = "sections";
export const SECTIONS_URL = "/api/basemap/sections_tx_nm.geojson";
export const SECTIONS_MIN_ZOOM = 11;

// step() gate replacing layer minzoom (see GOTCHA above)
const gated = (gate: number, value: number): ExpressionSpecification =>
  ["step", ["zoom"], 0, gate, value] as unknown as ExpressionSpecification;

// text-field: try the common BLM/abstract property names in order; the trailing
// "" means "no label" if none are present, which keeps the layer from throwing.
// Wrapped in a zoom step() so no label is even placed below the gate.
const BLOCK_LABEL_EXPR = [
  "step", ["zoom"], "",
  BLOCKS_MIN_ZOOM, [
    "coalesce",
    ["get", "BLOCK_NO"], ["get", "BLOCK"], ["get", "BlockNo"],
    ["get", "Block"], ["get", "block"], ["get", "BLOCKID"], "",
  ],
] as unknown as DataDrivenPropertyValueSpecification<string>;

const SECTION_LABEL_EXPR = [
  "step", ["zoom"], "",
  SECTIONS_MIN_ZOOM, [
    "coalesce",
    ["get", "LEVEL3_SUR"],  // OTLS Texas GLO survey export: section number
    ["get", "SECTION_NO"], ["get", "SECTION"], ["get", "SEC"],
    ["get", "SectionNo"], ["get", "Section"], ["get", "section"],
    ["get", "SECTIONID"], "",
  ],
] as unknown as DataDrivenPropertyValueSpecification<string>;

const blocksFill: FillLayerSpecification = {
  id: "blocks-fill", type: "fill", source: BLOCKS_SOURCE,
  paint: { "fill-color": "#1e293b", "fill-opacity": gated(BLOCKS_MIN_ZOOM, 0.04) },
};
const blocksLine: LineLayerSpecification = {
  id: "blocks-line", type: "line", source: BLOCKS_SOURCE,
  paint: {
    "line-color": "#1e293b", "line-width": 0.9,
    "line-opacity": gated(BLOCKS_MIN_ZOOM, 0.55),
  },
};
const blocksLabel: SymbolLayerSpecification = {
  id: "blocks-label", type: "symbol", source: BLOCKS_SOURCE,
  layout: {
    "text-field": BLOCK_LABEL_EXPR, "text-size": 12,
    "text-font": ["Noto Sans Regular"],  // must exist on the protomaps glyph server
    "text-allow-overlap": false, "symbol-placement": "point",
  },
  paint: {
    "text-color": "#0f172a", "text-halo-color": "rgba(255,255,255,0.9)",
    "text-halo-width": 1.5,
  },
};

const sectionsFill: FillLayerSpecification = {
  id: "sections-fill", type: "fill", source: SECTIONS_SOURCE,
  paint: { "fill-color": "#475569", "fill-opacity": gated(SECTIONS_MIN_ZOOM, 0.03) },
};
const sectionsLine: LineLayerSpecification = {
  id: "sections-line", type: "line", source: SECTIONS_SOURCE,
  paint: {
    "line-color": "#475569", "line-width": 0.6,
    "line-opacity": gated(SECTIONS_MIN_ZOOM, 0.5),
  },
};
const sectionsLabel: SymbolLayerSpecification = {
  id: "sections-label", type: "symbol", source: SECTIONS_SOURCE,
  layout: {
    "text-field": SECTION_LABEL_EXPR, "text-size": 10,
    "text-font": ["Noto Sans Regular"],
    "text-allow-overlap": false, "symbol-placement": "point",
  },
  paint: {
    "text-color": "#334155", "text-halo-color": "rgba(255,255,255,0.9)",
    "text-halo-width": 1.25,
  },
};

export const BLOCKS_LAYERS = [blocksFill, blocksLine, blocksLabel];
export const SECTIONS_LAYERS = [sectionsFill, sectionsLine, sectionsLabel];
