import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, {
  type GeoJSONSource,
  type LayerSpecification,
  type LngLatBoundsLike,
  type Map as MlMap,
  type StyleSpecification,
} from "maplibre-gl";
import { Protocol } from "pmtiles";
import layers from "protomaps-themes-base";
import "maplibre-gl/dist/maplibre-gl.css";

import { filterFC, useStore } from "./store";
import { SCENARIO_LAYERS, SCENARIO_SOURCE } from "./map/scenarioLayers";
import {
  BLOCKS_LAYERS, BLOCKS_SOURCE, BLOCKS_URL,
  SECTIONS_LAYERS, SECTIONS_SOURCE, SECTIONS_URL,
} from "./map/gridLayers";

// Grid overlays render UNDER the scenario legs so wells always stay on top.
const GRID_BEFORE_ID = SCENARIO_LAYERS[0].id;

// Lazy-add a survey-grid overlay on first enable, then flip visibility on
// subsequent toggles. A missing GeoJSON (404) turns the toggle back off rather
// than throwing — the overlay is optional.
function syncGridOverlay(
  map: MlMap,
  show: boolean,
  source: string,
  url: string,
  layers: readonly LayerSpecification[],
  onMissing: () => void,
): void {
  const layerIds = layers.map((l) => l.id);
  const setVis = (v: "visible" | "none") => {
    for (const id of layerIds) {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", v);
    }
  };
  if (!show) { setVis("none"); return; }
  if (map.getSource(source)) { setVis("visible"); return; }
  fetch(url)
    .then((r) => {
      if (r.status === 404) { onMissing(); return null; }
      if (!r.ok) throw new Error(`${url} → ${r.status}`);
      return r.json();
    })
    .then((data) => {
      if (!data || map.getSource(source)) return;
      map.addSource(source, { type: "geojson", data });
      const before = map.getLayer(GRID_BEFORE_ID) ? GRID_BEFORE_ID : undefined;
      for (const layer of layers) map.addLayer(layer, before);
    })
    .catch((e) => { console.error(e); });
}

function parcelOnly(geom: GeoJSON.Geometry): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: [{ type: "Feature", geometry: geom, properties: { kind: "parcel" } }],
  };
}

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

  const appMode = useStore((s) => s.appMode);
  const inventory = useStore((s) => s.inventory);
  const keptBenches = useStore((s) => s.keptBenches);
  const cats = useStore((s) => s.cats);
  const result = useStore((s) => s.result);
  const parcel = useStore((s) => s.parcel);
  const showBlocks = useStore((s) => s.showBlocks);
  const showSections = useStore((s) => s.showSections);

  const fc = useMemo<GeoJSON.FeatureCollection>(() => {
    if (appMode === "override") {
      if (result) return result.geojson;
      return parcel ? parcelOnly(parcel.geojson) : EMPTY_FC;
    }
    if (inventory) return filterFC(inventory.geojson, keptBenches, cats);
    return parcel ? parcelOnly(parcel.geojson) : EMPTY_FC;
  }, [appMode, inventory, keptBenches, cats, result, parcel]);

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

  // update the rendered data whenever the (filtered) FC changes
  useEffect(() => {
    if (!ready) return;
    const src = mapRef.current?.getSource(SCENARIO_SOURCE) as GeoJSONSource | undefined;
    src?.setData(fc);
  }, [fc, ready]);

  // re-fit to the PARCEL (the unit is the focus) when it changes — not to the
  // well sprawl, which can extend a couple miles past the unit on 2-mile laterals.
  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current;
    if (!map) return;
    const base = parcel
      ? parcelOnly(parcel.geojson)
      : appMode === "override" ? (result?.geojson ?? EMPTY_FC) : EMPTY_FC;
    const b = fcBounds(base);
    if (b) map.fitBounds(b, { padding: 90, maxZoom: 14, duration: 600 });
  }, [parcel, result, appMode, ready]);

  // survey-grid overlays (blocks + sections) — lazy-add / toggle visibility
  useEffect(() => {
    if (!ready || !mapRef.current) return;
    syncGridOverlay(mapRef.current, showBlocks, BLOCKS_SOURCE, BLOCKS_URL, BLOCKS_LAYERS,
      () => useStore.getState().setShowBlocks(false));
  }, [showBlocks, ready]);

  useEffect(() => {
    if (!ready || !mapRef.current) return;
    syncGridOverlay(mapRef.current, showSections, SECTIONS_SOURCE, SECTIONS_URL, SECTIONS_LAYERS,
      () => useStore.getState().setShowSections(false));
  }, [showSections, ready]);

  return <div ref={containerRef} className="map-root" />;
}
