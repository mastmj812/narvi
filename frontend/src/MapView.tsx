import { useEffect, useRef, useState } from "react";
import maplibregl, {
  type GeoJSONSource,
  type LngLatBoundsLike,
  type Map as MlMap,
  type StyleSpecification,
} from "maplibre-gl";
import { Protocol } from "pmtiles";
import layers from "protomaps-themes-base";
import "maplibre-gl/dist/maplibre-gl.css";

import { useStore } from "./store";
import { SCENARIO_LAYERS, SCENARIO_SOURCE } from "./map/scenarioLayers";

const EMPTY_FC: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

let pmtilesRegistered = false;
function registerPmtilesProtocol() {
  if (pmtilesRegistered) return;
  maplibregl.addProtocol("pmtiles", new Protocol().tile);
  pmtilesRegistered = true;
}

function buildStyle(): StyleSpecification {
  return {
    version: 8,
    glyphs: "https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf",
    sources: {
      protomaps: {
        type: "vector",
        url: "pmtiles:///api/basemap/permian.pmtiles",
        attribution:
          '<a href="https://protomaps.com">Protomaps</a> © <a href="https://openstreetmap.org">OpenStreetMap</a>',
      },
    },
    layers: layers("protomaps", "light", "en"),
  };
}

// Walk every coordinate in a FeatureCollection -> [[minLon,minLat],[maxLon,maxLat]].
function fcBounds(fc: GeoJSON.FeatureCollection): LngLatBoundsLike | null {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const visit = (c: unknown): void => {
    if (typeof (c as number[])[0] === "number") {
      const [x, y] = c as number[];
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    } else {
      for (const p of c as unknown[]) visit(p);
    }
  };
  for (const f of fc.features) {
    const g = f.geometry as GeoJSON.Geometry;
    if ("coordinates" in g) visit(g.coordinates);
  }
  if (minX === Infinity) return null;
  return [[minX, minY], [maxX, maxY]];
}

export function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const [ready, setReady] = useState(false);

  const result = useStore((s) => s.result);
  const parcel = useStore((s) => s.parcel);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    registerPmtilesProtocol();
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: buildStyle(),
      center: [-103.6, 31.85],
      zoom: 8,
      minZoom: 4,
      maxZoom: 16,
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-right");

    const setup = () => {
      if (map.getSource(SCENARIO_SOURCE)) return;
      map.addSource(SCENARIO_SOURCE, { type: "geojson", data: EMPTY_FC });
      for (const layer of SCENARIO_LAYERS) map.addLayer(layer);
      setReady(true);
    };
    map.on("load", setup);

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current;
    if (!map) return;
    const src = map.getSource(SCENARIO_SOURCE) as GeoJSONSource | undefined;
    if (!src) return;

    let fc: GeoJSON.FeatureCollection | undefined = result?.geojson;
    if (!fc && parcel) {
      fc = {
        type: "FeatureCollection",
        features: [{ type: "Feature", geometry: parcel.geojson, properties: { kind: "parcel" } }],
      };
    }
    fc = fc ?? EMPTY_FC;
    src.setData(fc);
    const b = fcBounds(fc);
    if (b) map.fitBounds(b, { padding: 60, maxZoom: 14, duration: 600 });
  }, [result, parcel, ready]);

  return <div ref={containerRef} className="map-root" />;
}
