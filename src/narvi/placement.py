"""Geometry core (slice 1): drillable window + parallel single-lateral placement.

All geometry is in the work CRS (UTM 13N, metres). Azimuth is the compass bearing
(clockwise from north) the laterals run along.

Method: rotate the window so the lateral azimuth aligns with +x, lay parallel
rows `spacing` apart in y, clip each row to the (possibly non-convex) window, keep
the rows whose drillable span meets the minimum length, then rotate back.
"""

from __future__ import annotations

from shapely.affinity import rotate
from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry

from .records import FT_PER_M


def drillable_window(parcel: BaseGeometry, setback_ft: float) -> BaseGeometry:
    """Inward offset by a uniform setback (slice 1; asymmetric edge-strip later).
    join_style=2 (mitre) keeps square corners; negative buffer is robust on
    non-convex parcels and may return a MultiPolygon (handled downstream)."""
    return parcel.buffer(-setback_ft / FT_PER_M, join_style=2)


def _longest_segment(geom: BaseGeometry) -> LineString | None:
    if geom.is_empty:
        return None
    if isinstance(geom, LineString):
        return geom
    if isinstance(geom, MultiLineString):
        return max(geom.geoms, key=lambda g: g.length)
    return None


def place_single_laterals(
    window: BaseGeometry,
    azimuth_deg: float,
    spacing_ft: float,
    min_lateral_ft: float,
) -> list[tuple[LineString, float]]:
    """Return [(lateral in work CRS, gunbarrel_x_ft), ...] sorted by cross-section
    offset. gunbarrel_x is the signed perpendicular distance (ft) from the window
    centroid — the cross-section coordinate for the gun-barrel view."""
    if window.is_empty:
        return []

    centroid = window.centroid
    phi = 90.0 - azimuth_deg                 # compass bearing -> math angle (CCW from +x)
    rot = rotate(window, -phi, origin=centroid, use_radians=False)  # laterals -> +x
    minx, miny, maxx, maxy = rot.bounds
    spacing_m = spacing_ft / FT_PER_M
    min_m = min_lateral_ft / FT_PER_M
    y_mid = (miny + maxy) / 2.0

    n_each = int(((maxy - miny) / 2.0) // spacing_m)
    out: list[tuple[LineString, float]] = []
    for k in range(-n_each, n_each + 1):
        y = y_mid + k * spacing_m
        row = LineString([(minx - 10.0, y), (maxx + 10.0, y)])
        seg = _longest_segment(row.intersection(rot))
        if seg is None or seg.length < min_m:
            continue
        seg_work = rotate(seg, phi, origin=centroid, use_radians=False)  # back to work CRS
        out.append((seg_work, (y - y_mid) * FT_PER_M))

    out.sort(key=lambda t: t[1])
    return out
