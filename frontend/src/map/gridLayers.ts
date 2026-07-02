// Texas/NM survey-grid overlays — Blocks (Texas block grid) + Sections
// (abstract/section grid). Ported from anduin (permian_type_curve) so the grid
// reads the same across the suite; the GeoJSON is served by narvi's backend from
// anduin's vendored infra/basemap assets. Fill + line + symbol-label per grid,
// zoom-gated (the BLM cadastral grid is too dense to label before then).
import type {
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

// text-field: try the common BLM/abstract property names in order; the trailing
// "" means "no label" if none are present, which keeps the layer from throwing.
const BLOCK_LABEL_EXPR = [
  "coalesce",
  ["get", "BLOCK_NO"], ["get", "BLOCK"], ["get", "BlockNo"],
  ["get", "Block"], ["get", "block"], ["get", "BLOCKID"], "",
] as unknown as ExpressionSpecification;

const SECTION_LABEL_EXPR = [
  "coalesce",
  ["get", "LEVEL3_SUR"],  // OTLS Texas GLO survey export: section number
  ["get", "SECTION_NO"], ["get", "SECTION"], ["get", "SEC"],
  ["get", "SectionNo"], ["get", "Section"], ["get", "section"],
  ["get", "SECTIONID"], "",
] as unknown as ExpressionSpecification;

const blocksFill: FillLayerSpecification = {
  id: "blocks-fill", type: "fill", source: BLOCKS_SOURCE, minzoom: BLOCKS_MIN_ZOOM,
  paint: { "fill-color": "#1e293b", "fill-opacity": 0.04 },
};
const blocksLine: LineLayerSpecification = {
  id: "blocks-line", type: "line", source: BLOCKS_SOURCE, minzoom: BLOCKS_MIN_ZOOM,
  paint: { "line-color": "#1e293b", "line-width": 0.9, "line-opacity": 0.55 },
};
const blocksLabel: SymbolLayerSpecification = {
  id: "blocks-label", type: "symbol", source: BLOCKS_SOURCE, minzoom: BLOCKS_MIN_ZOOM,
  layout: {
    "text-field": BLOCK_LABEL_EXPR, "text-size": 12,
    "text-allow-overlap": false, "symbol-placement": "point",
  },
  paint: {
    "text-color": "#0f172a", "text-halo-color": "rgba(255,255,255,0.9)",
    "text-halo-width": 1.5,
  },
};

const sectionsFill: FillLayerSpecification = {
  id: "sections-fill", type: "fill", source: SECTIONS_SOURCE, minzoom: SECTIONS_MIN_ZOOM,
  paint: { "fill-color": "#475569", "fill-opacity": 0.03 },
};
const sectionsLine: LineLayerSpecification = {
  id: "sections-line", type: "line", source: SECTIONS_SOURCE, minzoom: SECTIONS_MIN_ZOOM,
  paint: { "line-color": "#475569", "line-width": 0.6, "line-opacity": 0.5 },
};
const sectionsLabel: SymbolLayerSpecification = {
  id: "sections-label", type: "symbol", source: SECTIONS_SOURCE, minzoom: SECTIONS_MIN_ZOOM,
  layout: {
    "text-field": SECTION_LABEL_EXPR, "text-size": 10,
    "text-allow-overlap": false, "symbol-placement": "point",
  },
  paint: {
    "text-color": "#334155", "text-halo-color": "rgba(255,255,255,0.9)",
    "text-halo-width": 1.25,
  },
};

export const BLOCKS_LAYERS = [blocksFill, blocksLine, blocksLabel];
export const SECTIONS_LAYERS = [sectionsFill, sectionsLine, sectionsLabel];
