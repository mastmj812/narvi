// Layers for the generated-scenario GeoJSON (one source, filtered by `kind`).
// Legs are colored by the per-feature `formation_color` the backend emits, so the
// map and the gun-barrel agree on bench color.
import type {
  FillLayerSpecification,
  LineLayerSpecification,
} from "maplibre-gl";

export const SCENARIO_SOURCE = "scenario";

const parcelFill: FillLayerSpecification = {
  id: "scenario-parcel-fill",
  type: "fill",
  source: SCENARIO_SOURCE,
  filter: ["==", ["get", "kind"], "parcel"],
  paint: { "fill-color": "#1f2937", "fill-opacity": 0.04 },
};

const parcelLine: LineLayerSpecification = {
  id: "scenario-parcel-line",
  type: "line",
  source: SCENARIO_SOURCE,
  filter: ["==", ["get", "kind"], "parcel"],
  paint: { "line-color": "#1f2937", "line-width": 1.5 },
};

const windowLine: LineLayerSpecification = {
  id: "scenario-window-line",
  type: "line",
  source: SCENARIO_SOURCE,
  filter: ["==", ["get", "kind"], "window"],
  paint: {
    "line-color": "#2563eb",
    "line-width": 1,
    "line-dasharray": [2, 2],
    "line-opacity": 0.7,
  },
};

const legLine: LineLayerSpecification = {
  id: "scenario-leg-line",
  type: "line",
  source: SCENARIO_SOURCE,
  filter: ["==", ["get", "kind"], "leg"],
  paint: {
    "line-color": ["coalesce", ["get", "formation_color"], "#f97316"],
    "line-width": ["interpolate", ["linear"], ["zoom"], 9, 2, 14, 4],
    "line-opacity": 0.95,
  },
};

const turnLine: LineLayerSpecification = {
  id: "scenario-turn-line",
  type: "line",
  source: SCENARIO_SOURCE,
  filter: ["==", ["get", "kind"], "turn"],
  paint: {
    "line-color": "#a855f7",
    "line-width": 1.4,
    "line-dasharray": [1.5, 1.5],
  },
};

export const SCENARIO_LAYERS = [parcelFill, parcelLine, windowLine, legLine, turnLine];
