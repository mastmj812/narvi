// Layers for the scenario / inventory GeoJSON (one source, filtered by `kind`
// and `category`). Legs are colored by formation_blueox (shared palette); the
// three categories are separate layers so existing PDP, the PUD plan, and RES
// read differently. `generated` (override mode) styles like the plan.
import type {
  FillLayerSpecification,
  LineLayerSpecification,
} from "maplibre-gl";
import { blueoxColorExpression } from "./formations";

export const SCENARIO_SOURCE = "scenario";

const color = blueoxColorExpression();

const parcelFill: FillLayerSpecification = {
  id: "scenario-parcel-fill", type: "fill", source: SCENARIO_SOURCE,
  filter: ["==", ["get", "kind"], "parcel"],
  paint: { "fill-color": "#1f2937", "fill-opacity": 0.04 },
};

const parcelLine: LineLayerSpecification = {
  id: "scenario-parcel-line", type: "line", source: SCENARIO_SOURCE,
  filter: ["==", ["get", "kind"], "parcel"],
  paint: { "line-color": "#1f2937", "line-width": 1.5 },
};

const windowLine: LineLayerSpecification = {
  id: "scenario-window-line", type: "line", source: SCENARIO_SOURCE,
  filter: ["==", ["get", "kind"], "window"],
  paint: { "line-color": "#2563eb", "line-width": 1, "line-dasharray": [2, 2], "line-opacity": 0.7 },
};

// existing producers — context: colored but muted/thin
const legPdp: LineLayerSpecification = {
  id: "scenario-leg-pdp", type: "line", source: SCENARIO_SOURCE,
  filter: ["all", ["==", ["get", "kind"], "leg"], ["==", ["get", "category"], "pdp"]],
  paint: {
    "line-color": color, "line-opacity": 0.45,
    "line-width": ["interpolate", ["linear"], ["zoom"], 9, 1.5, 14, 3],
  },
};

// the plan: Novi PUD pass-through (and generated/override) — prominent
const legPlan: LineLayerSpecification = {
  id: "scenario-leg-plan", type: "line", source: SCENARIO_SOURCE,
  filter: ["all", ["==", ["get", "kind"], "leg"],
    ["in", ["get", "category"], ["literal", ["pud", "generated"]]]],
  paint: {
    "line-color": color, "line-opacity": 0.95,
    "line-width": ["interpolate", ["linear"], ["zoom"], 9, 2.5, 14, 4.5],
  },
};

// resource — usually dropped: dashed + faint
const legRes: LineLayerSpecification = {
  id: "scenario-leg-res", type: "line", source: SCENARIO_SOURCE,
  filter: ["all", ["==", ["get", "kind"], "leg"], ["==", ["get", "category"], "res"]],
  paint: {
    "line-color": color, "line-opacity": 0.5, "line-dasharray": [2, 1.5],
    "line-width": ["interpolate", ["linear"], ["zoom"], 9, 1.5, 14, 2.5],
  },
};

const turnLine: LineLayerSpecification = {
  id: "scenario-turn-line", type: "line", source: SCENARIO_SOURCE,
  filter: ["==", ["get", "kind"], "turn"],
  paint: { "line-color": "#a855f7", "line-width": 1.4, "line-dasharray": [1.5, 1.5] },
};

export const SCENARIO_LAYERS = [
  parcelFill, parcelLine, windowLine, legPdp, legRes, legPlan, turnLine,
];
