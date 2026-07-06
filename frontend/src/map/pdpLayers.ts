// Basin-wide PDP well sticks from the backend's MVT tile endpoint (the anduin
// pattern, sourced from curated.erebor_locations). Display-only offset context:
// points z6-8, full sticks z9+, colored by bench but dimmer/thinner than the
// scenario's in-parcel PDP legs so curated wells still read on top.
import type {
  CircleLayerSpecification,
  LineLayerSpecification,
} from "maplibre-gl";
import { blueoxColorExpression } from "./formations";

export const PDP_SOURCE = "pdp-wells";
// MapLibre needs an absolute tile template; string-concat (NOT new URL(), which
// percent-encodes the {z}/{x}/{y} braces and breaks the template).
export const pdpTileUrl = (): string =>
  `${window.location.origin}/api/wells/tiles/{z}/{x}/{y}.mvt`;

const color = blueoxColorExpression("formation_blueox");

const pdpPoints: CircleLayerSpecification = {
  id: "pdp-points", type: "circle", source: PDP_SOURCE,
  "source-layer": "pdp_points", minzoom: 6, maxzoom: 9,
  paint: {
    "circle-color": color, "circle-opacity": 0.55,
    "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 1.5, 9, 2.5],
  },
};

const pdpLines: LineLayerSpecification = {
  id: "pdp-lines", type: "line", source: PDP_SOURCE,
  "source-layer": "pdp_lines", minzoom: 9,
  paint: {
    "line-color": color, "line-opacity": 0.35,
    "line-width": ["interpolate", ["linear"], ["zoom"], 9, 1, 14, 2.5],
  },
};

export const PDP_LAYERS = [pdpPoints, pdpLines];
export const PDP_LAYER_IDS = PDP_LAYERS.map((l) => l.id);
