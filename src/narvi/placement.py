"""Geometry core: drillable window + parallel leg placement.

All geometry is in the work CRS (UTM 13N, metres). Azimuth is the compass bearing
(cw from N) the laterals run along.

Method: rotate the window so the azimuth aligns with +x, lay parallel rows
`spacing` apart in y, clip each to the (possibly non-convex) window, keep the rows
meeting the minimum length. Leg placement returns the rows IN THE ROTATED FRAME
(heels at low x, toes at high x) so the generator can build U-turn arcs trivially,
then map points back with unrotate().
"""

from __future__ import annotations

import math

from shapely.affinity import rotate
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from .records import FT_PER_M


def dominant_azimuth(parcel: BaseGeometry) -> float:
    """Compass bearing (deg, 0-180) of the parcel's long axis, from its minimum
    rotated rectangle. A dependency-free stand-in for the RRC survey-section grid
    until the survey shapefiles are wired (Phase 4): for a section-shaped parcel
    the long edge tracks the grid, so laterals laid along it stay full-length
    instead of getting clipped by a tilted boundary."""
    rect = parcel.minimum_rotated_rectangle
    pts = list(rect.exterior.coords)[:4]
    edges = [(pts[i], pts[i + 1]) for i in range(3)]
    (x0, y0), (x1, y1) = max(edges, key=lambda e: math.dist(e[0], e[1]))
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 180.0


def drillable_window(
    parcel: BaseGeometry, setback_ns_ft: float, setback_ew_ft: float | None = None
) -> BaseGeometry:
    """Inward setback. Uniform (one value, or N/S == E/W) uses a robust negative
    buffer; asymmetric (N/S vs E/W differ) uses per-edge strip subtraction."""
    ew = setback_ns_ft if setback_ew_ft is None else setback_ew_ft
    if abs(setback_ns_ft - ew) < 1e-6:
        return parcel.buffer(-setback_ns_ft / FT_PER_M, join_style=2)
    return _edge_strip_window(parcel, setback_ns_ft, ew)


def _edge_strip_window(parcel: BaseGeometry, setback_ns_ft: float, setback_ew_ft: float) -> BaseGeometry:
    """Per-edge inward strips: classify each boundary edge as N/S- or E/W-facing by
    its outward normal and subtract a strip of the matching setback. Local strips
    (not infinite half-planes), so it's robust to non-convex parcels / notches."""
    ns = setback_ns_ft / FT_PER_M
    ew = setback_ew_ft / FT_PER_M
    polys = list(parcel.geoms) if isinstance(parcel, MultiPolygon) else [parcel]
    strips = []
    for poly in polys:
        poly = orient(poly, 1.0)  # exterior CCW, holes CW -> interior is LEFT of each edge
        for ring in [poly.exterior, *poly.interiors]:
            cs = list(ring.coords)
            for (ax, ay), (bx, by) in zip(cs, cs[1:]):
                dx, dy = bx - ax, by - ay
                if dx == 0 and dy == 0:
                    continue
                # outward normal = (dy, -dx); N/S-facing when |dx| >= |dy|
                d = ns if abs(dx) >= abs(dy) else ew
                if d > 0:  # single_sided buffers left of the line = inward (CCW ring)
                    strips.append(LineString([(ax, ay), (bx, by)]).buffer(d, single_sided=True))
    if not strips:
        return parcel
    return parcel.difference(unary_union(strips))


def _longest_segment(geom: BaseGeometry) -> LineString | None:
    if geom.is_empty:
        return None
    if isinstance(geom, LineString):
        return geom
    if isinstance(geom, MultiLineString):
        return max(geom.geoms, key=lambda g: g.length)
    return None


def laterals_rotated(
    window: BaseGeometry,
    azimuth_deg: float,
    spacing_ft: float,
    min_lateral_ft: float,
    row_offset_ft: float = 0.0,
    anchor: str = "center",
) -> tuple[list[tuple[float, float, float]], Point, float, float]:
    """Place parallel rows along `azimuth_deg`. Returns (legs, centroid, phi, y_mid)
    where legs = [(y, x_heel, x_toe), ...] in the rotated frame (azimuth -> +x),
    sorted by y. `row_offset_ft` phase-shifts the rows (the wine-rack stagger across
    zones). `anchor` sets where the row pattern HANGS — 'center' (rows symmetric
    about the unit), 'west' / 'east' (first lateral at that section-line setback,
    stepping across) — which is how development is actually laid out and which row
    falls in an irregular cutout. Map a rotated point back with unrotate()."""
    if window.is_empty:
        return [], window.centroid, 0.0, 0.0

    centroid = window.centroid
    phi = 90.0 - azimuth_deg                 # compass bearing -> math angle
    rot = rotate(window, -phi, origin=centroid, use_radians=False)  # laterals -> +x
    minx, miny, maxx, maxy = rot.bounds
    spacing_m = spacing_ft / FT_PER_M
    min_m = min_lateral_ft / FT_PER_M
    y_mid = (miny + maxy) / 2.0

    if anchor == "center":
        anchor_y = y_mid
    else:
        # rotated +y is one cross-section direction; find which y-edge is WEST
        # (smaller Easting in the work CRS) so 'west'/'east' map correctly.
        xmid = (minx + maxx) / 2.0
        e_lo = rotate(Point(xmid, miny), phi, origin=centroid, use_radians=False).x
        e_hi = rotate(Point(xmid, maxy), phi, origin=centroid, use_radians=False).x
        west_y, east_y = (miny, maxy) if e_lo <= e_hi else (maxy, miny)
        anchor_y = west_y if anchor == "west" else east_y

    # rows at anchor + offset + k*spacing, k chosen to span the whole window
    base = anchor_y + row_offset_ft / FT_PER_M
    k_lo = math.ceil((miny - base) / spacing_m)
    k_hi = math.floor((maxy - base) / spacing_m)
    legs: list[tuple[float, float, float]] = []
    for k in range(k_lo, k_hi + 1):
        y = base + k * spacing_m
        seg = _longest_segment(LineString([(minx - 10.0, y), (maxx + 10.0, y)]).intersection(rot))
        if seg is None or seg.length < min_m:
            continue
        xs = [c[0] for c in seg.coords]
        legs.append((y, min(xs), max(xs)))  # heel = low x (west), toe = high x (east)

    legs.sort(key=lambda t: t[0])
    return legs, centroid, phi, y_mid


def unrotate(x: float, y: float, centroid: Point, phi: float) -> tuple[float, float]:
    """Map a rotated-frame point back to the work CRS."""
    p = rotate(Point(x, y), phi, origin=centroid, use_radians=False)
    return (p.x, p.y)
