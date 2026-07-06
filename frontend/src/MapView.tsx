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

import { composeFC, useStore } from "./store";
import { LEG_LAYER_IDS, SCENARIO_LAYERS, SCENARIO_SOURCE } from "./map/scenarioLayers";
import {
  BLOCKS_LAYERS, BLOCKS_SOURCE, BLOCKS_URL,
  SECTIONS_LAYERS, SECTIONS_SOURCE, SECTIONS_URL,
} from "./map/gridLayers";
import { PDP_LAYERS, PDP_LAYER_IDS, PDP_SOURCE, pdpTileUrl } from "./map/pdpLayers";

// Grid overlays render UNDER the scenario legs so wells always stay on top.
const GRID_BEFORE_ID = SCENARIO_LAYERS[0].id;

// Lazy-add a survey-grid overlay on first enable, then flip visibility on
// subsequent toggles. ANY fetch failure (404, backend down, proxy error) turns
// the toggle back off — a checked box with no layers is a lie, and unchecking
// re-arms the fetch so the next toggle retries.
const gridFetchInFlight = new Set<string>();
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
  if (gridFetchInFlight.has(source)) return;
  gridFetchInFlight.add(source);
  fetch(url)
    .then((r) => {
      if (!r.ok) throw new Error(`${url} → ${r.status}`);
      return r.json();
    })
    .then((data) => {
      if (map.getSource(source)) return;
      map.addSource(source, { type: "geojson", data });
      const before = map.getLayer(GRID_BEFORE_ID) ? GRID_BEFORE_ID : undefined;
      for (const layer of layers) map.addLayer(layer, before);
    })
    .catch((e) => { console.error(e); onMissing(); })
    .finally(() => { gridFetchInFlight.delete(source); });
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

  const inventory = useStore((s) => s.inventory);
  const benchSource = useStore((s) => s.benchSource);
  const cats = useStore((s) => s.cats);
  const culledWells = useStore((s) => s.culledWells);
  const result = useStore((s) => s.result);
  const parcel = useStore((s) => s.parcel);
  const showBlocks = useStore((s) => s.showBlocks);
  const showSections = useStore((s) => s.showSections);
  const showPdpWells = useStore((s) => s.showPdpWells);

  const fc = useMemo<GeoJSON.FeatureCollection>(() => {
    const composed = composeFC({ inventory, result, benchSource, cats, culledWells });
    if (composed) return composed;
    return parcel ? parcelOnly(parcel.geojson) : EMPTY_FC;
  }, [inventory, result, benchSource, cats, culledWells, parcel]);

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
      // basin-wide PDP tiles first -> they render UNDER the scenario/grid layers
      map.addSource(PDP_SOURCE, {
        type: "vector", tiles: [pdpTileUrl()], minzoom: 6, maxzoom: 14,
      });
      for (const layer of PDP_LAYERS) map.addLayer(layer);
      map.addSource(SCENARIO_SOURCE, { type: "geojson", data: EMPTY_FC });
      for (const layer of SCENARIO_LAYERS) map.addLayer(layer);
      // hover tooltip — api10 / bench / TVD — on both the basin-wide PDP tiles
      // and the in-unit scenario legs
      const tip = new maplibregl.Popup({
        closeButton: false, closeOnClick: false, maxWidth: "260px", offset: 10,
      });
      const tvdTxt = (v: unknown) =>
        typeof v === "number" && isFinite(v) ? `${Math.round(v).toLocaleString()} ft` : "—";
      const tipHtml = (name: string, bench: unknown, tvd: unknown, tag?: string) =>
        `<div class="map-tip"><b>${name}</b><br/>${bench ?? "—"} · TVD ${tvdTxt(tvd)}` +
        `${tag ? `<br/><span class="map-tip-tag">${tag}</span>` : ""}</div>`;
      const onPdpTileMove = (e: maplibregl.MapLayerMouseEvent) => {
        const p = e.features?.[0]?.properties as Record<string, unknown> | undefined;
        if (!p) return;
        map.getCanvas().style.cursor = "pointer";
        tip.setLngLat(e.lngLat)
          .setHTML(tipHtml(String(p.api10 ?? "PDP"), p.formation_blueox, p.tvd,
            "click to hide / show in gun-barrel"))
          .addTo(map);
      };
      const hideTip = () => { tip.remove(); map.getCanvas().style.cursor = ""; };
      // click a PDP stick to de-select / re-select the well in the gun-barrel
      // (bad-data screening) — a scenario leg under the cursor wins instead,
      // since its own click handler culls by the same well_name (api10 for PDP)
      const onPdpClick = (e: maplibregl.MapLayerMouseEvent) => {
        if (map.queryRenderedFeatures(e.point, { layers: [...LEG_LAYER_IDS] }).length > 0) return;
        const api10 = e.features?.[0]?.properties?.api10;
        if (api10 != null) useStore.getState().toggleCull(String(api10));
      };
      for (const id of PDP_LAYER_IDS) {
        map.on("mousemove", id, onPdpTileMove);
        map.on("mouseleave", id, hideTip);
        map.on("click", id, onPdpClick);
      }
      // click a leg to cull its well (both U-turn legs + the turn arc drop with it)
      const onLegClick = (e: maplibregl.MapLayerMouseEvent) => {
        const wn = e.features?.[0]?.properties?.well_name;
        if (typeof wn === "string") useStore.getState().toggleCull(wn);
      };
      const onLegMove = (e: maplibregl.MapLayerMouseEvent) => {
        const p = e.features?.[0]?.properties as Record<string, unknown> | undefined;
        if (!p) return;
        map.getCanvas().style.cursor = "pointer";
        tip.setLngLat(e.lngLat)
          .setHTML(tipHtml(String(p.well_name ?? ""), p.formation, p.target_tvd_ft,
            String(p.category ?? "").toUpperCase()))
          .addTo(map);
      };
      for (const id of LEG_LAYER_IDS) {
        map.on("click", id, onLegClick);
        map.on("mousemove", id, onLegMove);
        map.on("mouseleave", id, hideTip);
      }
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
    const base = parcel ? parcelOnly(parcel.geojson) : (result?.geojson ?? EMPTY_FC);
    const b = fcBounds(base);
    if (b) map.fitBounds(b, { padding: 90, maxZoom: 14, duration: 600 });
  }, [parcel, result, ready]);

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

  // basin-wide PDP tile layer visibility
  useEffect(() => {
    if (!ready || !mapRef.current) return;
    const map = mapRef.current;
    for (const id of PDP_LAYER_IDS) {
      if (map.getLayer(id)) {
        map.setLayoutProperty(id, "visibility", showPdpWells ? "visible" : "none");
      }
    }
  }, [showPdpWells, ready]);

  return <div ref={containerRef} className="map-root" />;
}
