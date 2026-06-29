"""Shared narvi visualization (Phase 4) — one source of truth for the plan-view
map and the gun-barrel cross-section, consumable by any front end.

Two renderer-agnostic serializers (pure, no matplotlib, no DB):
  * scenario_geojson() -> a WGS84 GeoJSON FeatureCollection for the plan-view map
    (MapLibre in a React shell, or pydeck/folium in Streamlit). The legs/turns
    already carry lon/lat from generate.py; only the parcel + drillable window are
    transformed here from the work CRS (UTM 13N).
  * gunbarrel_data() -> structured cross-section points/links (offset_ft, tvd_ft)
    so any chart library can draw the gun-barrel.

Plus matplotlib convenience renderers (planview_figure / gunbarrel_figure) for
static output and Streamlit's st.pyplot — matplotlib is imported lazily so the
GeoJSON path stays light.
"""

from __future__ import annotations

from pyproj import CRS, Transformer
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform

from .parcel import WORK_EPSG
from .records import InventoryWell

# bench palette (shallow -> deep order assigned by the caller); shared so the
# map and the gun-barrel color a formation the same way.
PALETTE = ["#f97316", "#2563eb", "#10b981", "#a855f7", "#dc2626",
           "#0891b2", "#eab308", "#db2777"]
_LEG_COLOR = "#f97316"     # producing leg (plan view)
_TURN_COLOR = "#a855f7"    # non-producing U-turn arc

_to_wgs = Transformer.from_crs(
    CRS.from_epsg(WORK_EPSG), CRS.from_epsg(4326), always_xy=True
).transform


def _to_wgs_geom(geom: BaseGeometry) -> BaseGeometry:
    """Reproject a work-CRS (UTM 13N) polygon to WGS84 for the map."""
    return shp_transform(lambda x, y, z=None: _to_wgs(x, y), geom)


def _round_coords(obj):
    """Round GeoJSON coordinates to 6 dp (≈0.1 m) for compact, stable output."""
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(c), 6) for c in obj]
        return [_round_coords(o) for o in obj]
    return obj


def _polygon_feature(geom: BaseGeometry, props: dict) -> dict:
    g = mapping(_to_wgs_geom(geom))
    g["coordinates"] = _round_coords(g["coordinates"])
    return {"type": "Feature", "geometry": g, "properties": props}


def formation_order(wells: list[InventoryWell]) -> list[str]:
    """Formations present, shallow -> deep by median landing TVD (palette order)."""
    return sorted({w.formation for w in wells},
                  key=lambda f: min(w.target_tvd_ft for w in wells if w.formation == f))


def formation_colors(wells: list[InventoryWell]) -> dict[str, str]:
    forms = formation_order(wells)
    return {f: PALETTE[i % len(PALETTE)] for i, f in enumerate(forms)}


def scenario_geojson(
    parcel: BaseGeometry | None,
    window: BaseGeometry | None,
    wells: list[InventoryWell],
    *,
    include_window: bool = True,
) -> dict:
    """A WGS84 GeoJSON FeatureCollection for the plan-view map: the parcel, the
    drillable window, every producing leg (LineString), and every non-producing
    U-turn arc (LineString). Properties drive styling + popups in the front end.
    parcel/window may be None (e.g. reloading a saved scenario from its wells)."""
    colors = formation_colors(wells)
    features: list[dict] = []
    if parcel is not None:
        features.append(_polygon_feature(parcel, {"kind": "parcel"}))
    if include_window and window is not None:
        features.append(_polygon_feature(window, {"kind": "window"}))

    for w in wells:
        for i, leg in enumerate(w.legs):
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString",
                             "coordinates": [list(leg.heel_lonlat), list(leg.toe_lonlat)]},
                "properties": {
                    "kind": "leg", "well_name": w.well_name, "well_type": w.well_type,
                    "category": w.category, "novi_wellname": w.novi_wellname,
                    "recon_status": w.recon_status,
                    "formation": w.formation, "formation_color": colors.get(w.formation, _LEG_COLOR),
                    "target_tvd_ft": w.target_tvd_ft, "leg_index": i,
                    "length_ft": leg.length_ft, "gunbarrel_x_ft": leg.gunbarrel_x_ft,
                    "completed_lateral_ft": w.completed_lateral_ft,
                    "drilled_lateral_ft": w.drilled_lateral_ft,
                    "lateral_azimuth_deg": w.lateral_azimuth_deg,
                    "nearest_neighbor_spacing_ft": w.nearest_neighbor_spacing_ft,
                },
            })
        if w.turn is not None:
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString",
                             "coordinates": [list(pt) for pt in w.turn.arc_lonlat]},
                "properties": {
                    "kind": "turn", "well_name": w.well_name, "formation": w.formation,
                    "radius_ft": w.turn.radius_ft, "arc_ft": w.turn.arc_ft,
                    "dls_deg_per_100ft": w.turn.dls_deg_per_100ft,
                },
            })
    return {"type": "FeatureCollection", "features": features}


def gunbarrel_data(wells: list[InventoryWell]) -> dict:
    """Cross-section data (looking down the lateral axis): each producing leg is a
    point at (cross-section offset_ft, target TVD); a U-turn's two legs are joined
    by a link at their TVD. `formations` is shallow->deep with palette colors so a
    chart can build a bench legend."""
    colors = formation_colors(wells)
    points, links = [], []
    for w in wells:
        for leg in w.legs:
            points.append({
                "well_name": w.well_name, "formation": w.formation,
                "color": colors[w.formation], "well_type": w.well_type,
                "category": w.category, "novi_wellname": w.novi_wellname,
                "recon_status": w.recon_status,
                "offset_ft": leg.gunbarrel_x_ft, "tvd_ft": w.target_tvd_ft,
            })
        if w.turn is not None and len(w.legs) == 2:
            links.append({
                "well_name": w.well_name, "formation": w.formation,
                "color": colors[w.formation], "tvd_ft": w.target_tvd_ft,
                "offset_a_ft": w.legs[0].gunbarrel_x_ft,
                "offset_b_ft": w.legs[1].gunbarrel_x_ft,
            })
    legend = [{"formation": f, "color": colors[f]} for f in formation_order(wells)]
    return {"formations": legend, "points": points, "links": links}


# --------------------------------------------------------------------------- #
# matplotlib convenience renderers (lazy import; for demo + Streamlit st.pyplot)
# --------------------------------------------------------------------------- #
def planview_figure(parcel, window, wells: list[InventoryWell], title: str):
    """Plan-view Figure: parcel + drillable window + producing legs + turn arcs."""
    import matplotlib.pyplot as plt
    from shapely.geometry import MultiPolygon

    fig, ax = plt.subplots(figsize=(8, 8))

    def ring(geom, **kw):
        polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
        for poly in polys:
            xs, ys = poly.exterior.xy
            ax.plot(xs, ys, **kw)

    ring(parcel, color="#1f2937", lw=1.5, label="parcel")
    if window is not None:
        ring(window, color="#2563eb", lw=1.0, ls="--", label="drillable window")
    for w in wells:
        for leg in w.legs:
            ax.plot([leg.heel_xy[0], leg.toe_xy[0]], [leg.heel_xy[1], leg.toe_xy[1]],
                    color=_LEG_COLOR, lw=2)
        if w.turn is not None:
            ax.plot([pt[0] for pt in w.turn.arc_xy], [pt[1] for pt in w.turn.arc_xy],
                    color=_TURN_COLOR, lw=1.5)
    ax.set_aspect("equal")
    ax.set_title(title)
    ax.legend(loc="upper right", fontsize=8)
    return fig


def gunbarrel_figure(wells: list[InventoryWell], title: str):
    """Gun-barrel cross-section Figure (offset vs TVD, deeper = lower)."""
    import matplotlib.pyplot as plt

    data = gunbarrel_data(wells)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for link in data["links"]:
        ax.plot([link["offset_a_ft"], link["offset_b_ft"]],
                [link["tvd_ft"], link["tvd_ft"]],
                color=link["color"], lw=0.8, alpha=0.5, zorder=2)
    for pt in data["points"]:
        ax.scatter(pt["offset_ft"], pt["tvd_ft"], color=pt["color"], s=20, zorder=3)
    handles = [plt.Line2D([], [], marker="o", ls="", color=f["color"], label=f["formation"])
               for f in data["formations"]]
    if handles:
        ax.legend(handles=handles, fontsize=8, loc="upper right", title="bench")
    ax.invert_yaxis()
    ax.set_xlabel("cross-section offset (ft)")
    ax.set_ylabel("TVD (ft)")
    ax.set_title(title)
    ax.grid(True, alpha=0.2)
    return fig
